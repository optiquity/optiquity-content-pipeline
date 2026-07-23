"""DR-1 Commit 4: the detached Tier-B job runner + the detached-spawn primitive (H3).

Design authority: `docs/design.md` §22.7 (OUTPUT EXISTENCE + the S1 claim/lease are the SOLE
DONE / exactly-once authorities; a job record is lagging bookkeeping that gates nothing), §21.9
(the persistent transport FRONT is stateless — this runner re-enters the SAME synchronous
`invoke()` a CLI caller would, per-call statelessness intact), §22.5 (a backpressure/timeout hit
is surfaced typed, never a crash); plus the DR-1 reconciliation resolution H3 (transport is
VERB-ASYMMETRIC, so the runner does BOTH: it classifies the RETURNED result codes AND catches the
genuine raiser set).

**This module is a THIN outcome-router over `invoke()` + `JobStore.record_terminal`.** It never
re-classifies or duplicates `invoke()` logic: it calls `invoke(verb, workspace, params, …)`
(which acquires the S1 claim INSIDE the handler) and then routes the ONE outcome to at most ONE
`record_terminal` write. There are exactly three outcomes (§22.7):

1. **Clean success** — the output materialized (`is_done` becomes true by output existence). The
   runner records NOTHING; DONE is authored by the output, never by a job record.
2. **A failure surfaced as a RETURNED coded result** (the `generate-next` shape — the driver/
   session carry a transport failure as a per-item `block` in `results[]`, `envelope.ok` still
   True). A NONDETERMINISTIC block (timeout / backpressure / a code-less transport block) →
   `record_terminal` a re-drivable terminal (so the poll surfaces the reason; Commit 6 maps the
   code to a re-drivable 504 / a 429+retry-after). A DETERMINISTIC block
   (`empty-pool`/`out-of-window`/`drift-block`/`hard-limit-exceeded`) → store NOTHING (the §21.7
   completeness sweep re-derives it; Commit 3's N-5 discipline).
3. **A failure surfaced as a RAISED exception** (the `render` shape — `mint_fit` converts a
   non-ok reconcile, including a transport-carried timeout, into a raised `_EngineError`, and
   `invoke()` has no dispatch-level catch, so it propagates here; plus the env/wiring raisers).
   The runner CATCHES the raiser set, SYNTHESIZES a terminal envelope, and records it. A
   TRULY-UNEXPECTED exception (outside the raiser set) is left to PROPAGATE: the process crashes
   with no terminal, and recovery is the poll resolver's re-drivable path + the claim-lease
   expiry (§22.3/§22.7) — never a fabricated terminal for an unknown fault (§3.1).

## H3 finding carried in code (verb-asymmetry — VERIFIED against `main`)

For `render`, `mint_fit` RAISES `_EngineError` on a non-ok reconcile (`render.py`), and `_render`
catches only `FitResolutionError`/`SerializeError`, so `_EngineError` (and the transport env
raisers) reach this runner — the RAISED path (2).

For `generate-next`, a transport failure is CARRIED, never raised: `transport` RETURNS a coded
`TransportResult` → `compose_artifact` returns `status="error", code=transport.code` →
`driver._run_artifact` raises a `DriverError` **without** a §21.7 `stage_code` →
`session._generate_next` CATCHES that `DriverError` and surfaces it as a CODE-LESS `_block`
(`session.py` — the transport code rides `remediation.hint`, NOT a structured `result.code`,
because a §21.7 `ResultItem` cannot carry the transport-only `timeout` code, `results.py`
rejects it). So on the REAL `generate-next` path the runner sees a CODE-LESS block, which
`_classify_returned` treats as a NONDETERMINISTIC (re-drivable) failure — the same routing an
injected STRUCTURED `timeout`/`rate-limit-backpressure` code takes. Only the DETERMINISTIC
generation-tier blocks are threaded as structured codes (the driver's `stage_code`), so those are
the codes `is_deterministic_block` recognizes to store NOTHING.

Note: `DriverError` is in the caught raiser set DEFENSIVELY. Through the two Tier-B verbs it is
NOT a live raiser — `session` catches it for `generate-next`, and `render` uses the engine (not
the driver). It is caught so any future `invoke()` path that lets it escape records a terminal
rather than crashing. (See the Commit-4 implementation report's H3 finding.)

**No `schema_version`/`ir_version` bump.** The spawn spec is transient invocation input and the
job terminal is §22.7-class lossy bookkeeping — neither is identity. The REAL detached-spawn
end-to-end proof (a runner surviving the shim exit, a cross-process `peek`) is the Commit-I
integration harness; here the spawn primitive is tested with a mock `Popen` and the outcome
router with an injected `invoke` seam.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pipeline.api import invoke as invoke_mod
from pipeline.api.invoke import HandlerNotWired
from pipeline.api.render import _EngineError
from pipeline.canonical import canonical_json_str
from pipeline.driver import DriverError
from pipeline.jobs import JobStore, is_deterministic_block
from pipeline.store import WorkspaceStore
from pipeline.transport import ApiKeyPresentError, BinaryNotFoundError
from pipeline.workspace_name import validate_workspace_name

__all__ = [
    "RE_DRIVABLE_CODE",
    "RUNNER_MODULE",
    "TERMINAL_FAILED_CODE",
    "JobSpec",
    "RunOutcome",
    "SpawnHandle",
    "main",
    "run_job",
    "spawn_runner",
]

#: The `-m` entry point a detached runner is launched as (`python -m pipeline.api.jobrunner`).
RUNNER_MODULE = "pipeline.api.jobrunner"

#: The synthesized terminal code for a TIMEOUT-CLASS / transient runtime failure the same-key
#: re-drive may clear (the render `_EngineError` mint path, and a code-less `generate-next`
#: transport block). NOT a §21.7 code — `JobTerminal.code` is free-form bookkeeping; Commit 6's
#: poll maps it to a re-drivable 504. It is deliberately NOT a `DETERMINISTIC_BLOCK_CODE`, so
#: `record_terminal` always STORES it (the sweep does not re-derive a transport failure).
RE_DRIVABLE_CODE = "re-drivable"

#: The synthesized terminal code for a WIRING/ENV failure a re-drive cannot fix (a missing binary,
#: an unwired handler). Commit 6's poll maps it to a terminal FAILED. Also not deterministic-block.
TERMINAL_FAILED_CODE = "runner-failed"

#: The GENUINE raiser set that propagates out of `invoke()` to this runner (H3, verified against
#: `main`). `_EngineError` is the render timeout-class mint failure (→ re-drivable); the rest are
#: env/wiring faults (→ terminal FAILED). `DriverError` is defensive (see the module docstring).
#: Anything OUTSIDE this tuple is truly-unexpected and is left to propagate (crash → no terminal).
_RAISER_SET: tuple[type[BaseException], ...] = (
    _EngineError,
    HandlerNotWired,
    ApiKeyPresentError,
    BinaryNotFoundError,
    DriverError,
)


# ---------------------------------------------------------------------------
# The spawn spec (the runner's invocation input) + the run outcome value object.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobSpec:
    """Everything a detached runner needs to re-enter `invoke()` for ONE job.

    `key` is the run-family job key `JobStore.submit` ALREADY minted + wrote the record under
    (Commit 6): the runner records terminals against this exact key, it does NOT recompute or
    re-write the initial record (record → spawn → claim ordering). `root`/`workspace` locate the
    workspace store (→ the `jobs/` dir) for `record_terminal`; `params`/`token`/`pins` are the
    `invoke()` arguments. This crosses the process boundary as a small JSON SPAWN FILE (not argv)
    so structured params ride cleanly and NO secret is placed on argv — `token` is a §20 cursor,
    not a credential, and the subscription transport carries no API key at all (F10)."""

    key: str
    verb: str
    workspace: str
    params: Mapping[str, Any]
    idempotency_key: str | None
    root: str
    token: Any = None
    pins: Any = None

    def as_json(self) -> str:
        """Canonical JSON for the spawn file (byte-stable, matching the repo convention)."""
        return canonical_json_str(
            {
                "idempotency_key": self.idempotency_key,
                "key": self.key,
                "params": dict(self.params),
                "pins": self.pins,
                "root": self.root,
                "token": self.token,
                "verb": self.verb,
                "workspace": self.workspace,
            }
        )

    @classmethod
    def from_json(cls, text: str) -> JobSpec:
        import json

        obj = json.loads(text)
        if not isinstance(obj, Mapping):
            raise ValueError("jobrunner: a spawn spec must be a JSON object")
        return cls(
            key=obj["key"],
            verb=obj["verb"],
            workspace=obj["workspace"],
            params=obj.get("params") or {},
            idempotency_key=obj.get("idempotency_key"),
            root=obj["root"],
            token=obj.get("token"),
            pins=obj.get("pins"),
        )


@dataclass(frozen=True)
class RunOutcome:
    """One runner outcome (diagnostics + the tests pin it). `disposition` names the routed branch;
    `code` is the terminal code stored (or None); `stored` is whether a terminal was written."""

    disposition: Literal["clean", "skip-deterministic", "terminal-returned", "terminal-raised"]
    code: str | None
    stored: bool


@dataclass(frozen=True)
class SpawnHandle:
    """The detached-spawn result — the transient spawn-file path + the child pid (diagnostics).
    `spawn_runner` RETURNS immediately; it never waits on the child (the runner outlives BOTH the
    202 response and the shim process)."""

    spawn_file: Path
    pid: int | None
    handle: Any = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# The detached-spawn primitive (record → spawn → claim; the record is Commit 6's).
# ---------------------------------------------------------------------------


def spawn_runner(
    spec: JobSpec,
    *,
    spawn_dir: Path,
    popen: Any = subprocess.Popen,
) -> SpawnHandle:
    """Launch the runner as a DETACHED subprocess that outlives the 202 response AND the shim.

    The invocation SPEC is written to a small JSON spawn file under `spawn_dir` (the workspace's
    gitignored `jobs/` tree in production; a tmp dir in tests) and its PATH is the ONLY argv the
    child receives — structured params ride the file, and NO secret is placed on argv. The child
    is `python -m pipeline.api.jobrunner <spawn_file>` with `start_new_session=True` (a new
    session/process-group via `setsid`, so the runner survives the shim exit and is not swept by
    the parent's signals) and `close_fds=True` (it does NOT inherit the server socket).

    Returns IMMEDIATELY (never waits) — the job RECORD was already written by `JobStore.submit`
    BEFORE this call (record → spawn → claim), so a spawn FAILURE here is exactly the H2 stale-
    record case: the record stays stealable and the next poll/submit re-spawns. On a `Popen`
    failure the transient spawn file is cleaned up and the error re-raised (the caller records the
    spawn failure); the durable record is untouched.
    """
    spawn_dir = Path(spawn_dir)
    spawn_dir.mkdir(parents=True, exist_ok=True)
    spawn_file = spawn_dir / f"spawn-{spec.key}.json"
    spawn_file.write_text(spec.as_json(), encoding="utf-8")
    argv = [sys.executable, "-m", RUNNER_MODULE, str(spawn_file)]
    try:
        child = popen(argv, start_new_session=True, close_fds=True)
    except OSError:
        # A spawn failure after the record write → the H2 stale-record case. Drop the orphan spec
        # file (the durable job record is NOT ours to touch) and re-raise so the caller records it.
        spawn_file.unlink(missing_ok=True)
        raise
    return SpawnHandle(spawn_file=spawn_file, pid=getattr(child, "pid", None), handle=child)


# ---------------------------------------------------------------------------
# The runner body — the verb-aware outcome router (H3).
# ---------------------------------------------------------------------------


def _store_for(spec: JobSpec) -> JobStore:
    """The workspace's `jobs/` store for `record_terminal`. `validate_workspace_name` contains the
    name to a direct child of `workspaces/` (the SAME §10/§21.1 containment `invoke()` applies), so
    a malformed workspace can never move the record root."""
    ws_root = validate_workspace_name(spec.workspace, spec.root)
    return JobStore(WorkspaceStore(ws_root).jobs_dir)


def _raised_terminal_code(exc: BaseException) -> str:
    """The terminal code for a CAUGHT raiser. `_EngineError` is the render timeout-class mint
    failure → re-drivable; every other raiser is an env/wiring fault → its own `.code` (or the
    terminal-failed fallback), which Commit 6 maps to a terminal FAILED."""
    if isinstance(exc, _EngineError):
        return RE_DRIVABLE_CODE
    code = getattr(exc, "code", None)
    return code if isinstance(code, str) and code else TERMINAL_FAILED_CODE


_ReturnedKind = Literal["record", "skip", "clean"]


def _classify_returned(out: Mapping[str, Any]) -> tuple[_ReturnedKind, str | None]:
    """Route a RETURNED `{envelope, results}` to ONE store decision (H3), reading `status`+`code`
    ONLY — never parsing a hint (that would re-classify `invoke()` logic).

    - envelope `ok=False` (a whole-invocation failure: unknown-verb / isolation / invalid-token)
      → `("record", <envelope code>)` — surface the reason (Commit 6 maps it to a terminal 4xx).
    - envelope `ok=True`, any `results[]` item that is a NONDETERMINISTIC block (a `status=block`
      whose `code` is NOT a `DETERMINISTIC_BLOCK_CODE` — a structured transport code OR a code-less
      real-path block) → `("record", <that code, or RE_DRIVABLE_CODE if code-less>)`.
    - only DETERMINISTIC blocks present → `("skip", None)` — the sweep re-derives them (N-5).
    - otherwise → `("clean", None)` — success; DONE is authored by output existence, no terminal.
    """
    envelope = out.get("envelope") if isinstance(out, Mapping) else None
    if isinstance(envelope, Mapping) and envelope.get("ok") is False:
        code = envelope.get("code")
        return "record", (code if isinstance(code, str) and code else RE_DRIVABLE_CODE)

    results = out.get("results") if isinstance(out, Mapping) else None
    deterministic_seen = False
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, Mapping) or item.get("status") != "block":
            continue
        code = item.get("code")
        if isinstance(code, str) and is_deterministic_block(code):
            deterministic_seen = True
            continue
        # A nondeterministic block: a structured transport code, or a code-less transport block
        # (the REAL generate-next path — see the module docstring's H3 finding). Re-drivable.
        return "record", (code if isinstance(code, str) and code else RE_DRIVABLE_CODE)
    return ("skip", None) if deterministic_seen else ("clean", None)


def run_job(
    spec: JobSpec,
    *,
    job_store: JobStore | None = None,
    invoke: Any = None,
) -> RunOutcome:
    """Run ONE job: re-enter `invoke()` (which acquires the S1 claim inside the handler) and route
    the single outcome to at most one `record_terminal` write (H3). `invoke`/`job_store` are
    injectable seams — the tests drive every branch with an injected `invoke` return/raise and a
    tmp `JobStore`, no live transport. A raiser in `_RAISER_SET` is caught and synthesized into a
    terminal; anything else PROPAGATES (crash → no terminal → the poll's re-drivable recovery)."""
    store = job_store if job_store is not None else _store_for(spec)
    call = invoke_mod.invoke if invoke is None else invoke
    try:
        out = call(
            spec.verb,
            spec.workspace,
            dict(spec.params),
            spec.token,
            spec.pins,
            root=spec.root,
        )
    except _RAISER_SET as exc:
        code = _raised_terminal_code(exc)
        envelope = {
            "ok": False,
            "verb": spec.verb,
            "workspace": spec.workspace,
            "code": code,
            "message": str(exc),
        }
        stored = store.record_terminal(spec.key, code=code, envelope=envelope, results=[])
        return RunOutcome("terminal-raised", code, stored)

    kind, code = _classify_returned(out if isinstance(out, Mapping) else {})
    if kind == "record":
        assert code is not None  # the record branch always names a code
        stored = store.record_terminal(
            spec.key,
            code=code,
            envelope=out.get("envelope"),
            results=out.get("results"),
        )
        return RunOutcome("terminal-returned", code, stored)
    return RunOutcome("clean" if kind == "clean" else "skip-deterministic", code, False)


def main(argv: list[str] | None = None) -> int:
    """`python -m pipeline.api.jobrunner <spawn_file>` — the detached entry point. Reads the spawn
    spec, runs the job, and deletes the transient spawn file. A truly-unexpected exception
    propagates (non-zero exit, no terminal); the spawn file is cleaned up either way."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m pipeline.api.jobrunner <spawn_file>", file=sys.stderr)
        return 2
    spawn_file = Path(args[0])
    spec = JobSpec.from_json(spawn_file.read_text(encoding="utf-8"))
    try:
        run_job(spec)
    finally:
        spawn_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
