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
from pipeline.telemetry import PresenceRegistry, TelemetryError
from pipeline.transport import ApiKeyPresentError, BinaryNotFoundError
from pipeline.workspace_name import validate_workspace_path

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
    re-write the initial record (record → spawn → claim ordering). `root`/`user`/`zone`/`workspace`
    locate the workspace store leaf `root/users/<user>/zones/<zone>/workspaces/<ws>/` (→ the `jobs/`
    dir) for `record_terminal`; `params`/`token`/`pins` are the `invoke()` arguments. `user` AND
    `zone` are MANDATORY (§23/Z4): a spawn-JSON written PRE-cutover LACKS them, so `from_json` fails
    loudly rather than build a `users/None/…` or `zones/None/…` path — safe because a job record is
    §22.7-class lossy bookkeeping (loud-fail + poll re-drive). This crosses the process boundary as
    a small JSON SPAWN FILE (not argv)
    so structured params ride cleanly and NO secret is placed on argv — `token` is a §20 cursor,
    not a credential, and the subscription transport carries no API key at all (F10).

    `callback_url` is the OPTIONAL, already-validated (submit-time allow-list + SSRF guard, W3b)
    webhook the runner will POST a completion WAKEUP to once delivery lands (W3c). `target_ids` is
    the predictable artifact-id set the submit resolved LLM-free — carried so the delivery wakeup's
    payload (`job.target_ids`, the poll pointer) needs no record read. `allowed_callback_hosts` is
    the FROZEN operator allow-list SNAPSHOT taken at submit, so the detached runner RE-VALIDATES the
    callback URL at delivery (the DNS-rebinding re-check) against the SAME list the submit used,
    without re-reading instance config. All three ride the spawn file so the detached runner — the
    only component that outlives the shim and knows the job finished — has them in hand; they are
    transient invocation input, never identity (no bump). `callback_url` None ⇒ poll-only."""

    key: str
    verb: str
    workspace: str
    user: str
    zone: str
    params: Mapping[str, Any]
    idempotency_key: str | None
    root: str
    token: Any = None
    pins: Any = None
    callback_url: str | None = None
    target_ids: tuple[str, ...] = ()
    allowed_callback_hosts: frozenset[str] = frozenset()

    def as_json(self) -> str:
        """Canonical JSON for the spawn file (byte-stable, matching the repo convention). The
        `allowed_callback_hosts` frozenset is written as a SORTED list (JSON has no set); from_json
        restores the frozenset — the membership check is order-independent, so the round-trip is
        lossless for the guard."""
        return canonical_json_str(
            {
                "allowed_callback_hosts": sorted(self.allowed_callback_hosts),
                "callback_url": self.callback_url,
                "idempotency_key": self.idempotency_key,
                "key": self.key,
                "params": dict(self.params),
                "pins": self.pins,
                "root": self.root,
                "target_ids": list(self.target_ids),
                "token": self.token,
                "user": self.user,
                "verb": self.verb,
                "workspace": self.workspace,
                "zone": self.zone,
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
            # §23: MANDATORY — a pre-cutover spawn-JSON LACKS `user`, so this bare subscript RAISES
            # KeyError loudly (never a `users/None/…` path); a job record is §22.7-lossy, so the
            # loud fail + poll re-drive is safe (mirrors the bare `key`/`verb`/`workspace`/`root`).
            user=obj["user"],
            # §23/Z4: MANDATORY the same way — a pre-cutover spawn-JSON LACKS `zone`, so this bare
            # subscript RAISES KeyError loudly (never a silent `zones/None/…` or default guess),
            # completing the zone round-trip across the process boundary.
            zone=obj["zone"],
            params=obj.get("params") or {},
            idempotency_key=obj.get("idempotency_key"),
            root=obj["root"],
            token=obj.get("token"),
            pins=obj.get("pins"),
            callback_url=obj.get("callback_url"),
            target_ids=tuple(obj.get("target_ids") or ()),
            allowed_callback_hosts=frozenset(obj.get("allowed_callback_hosts") or ()),
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
    record case: the record stays stealable and the next poll/submit re-spawns. On a `Popen` OSError
    the transient spawn file is cleaned up and the OSError is RE-RAISED to the caller; the durable
    job record is left UNTOUCHED (never `record_terminal`-ed). Recovery is the H2 self-heal, not an
    explicit terminal: the un-spawned record simply lapses past `spawn_expiry` with no live claim /
    no output, so the next poll resolves it re-drivable and the next same-key submit steals-and-
    respawns it. (The DR-1 shim caller therefore lets the OSError propagate — a 500 to the client —
    and relies on that H2 re-drive; it deliberately writes no terminal for a spawn failure.)
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
        # file (the durable job record is NOT ours to touch) and RE-RAISE. The caller writes NO
        # terminal — the un-spawned record self-heals via the H2 re-drive (poll → re-drivable →
        # same-key re-submit steals-and-respawns).
        spawn_file.unlink(missing_ok=True)
        raise
    return SpawnHandle(spawn_file=spawn_file, pid=getattr(child, "pid", None), handle=child)


# ---------------------------------------------------------------------------
# The runner body — the verb-aware outcome router (H3).
# ---------------------------------------------------------------------------


def _store_for(spec: JobSpec) -> JobStore:
    """The workspace's `jobs/` store for `record_terminal`. `validate_workspace_path` contains the
    `(user, workspace)` pair to a leaf under `users/<user>/workspaces/` (the SAME §10/§21.1/§23
    containment `invoke()` applies), so a malformed user/workspace can never move the record root;
    `.at()` then builds the byte-identical leaf WITH recorded identity."""
    validate_workspace_path(spec.root, spec.user, spec.workspace, zone=spec.zone)
    return JobStore(
        WorkspaceStore.at(spec.root, spec.user, spec.workspace, zone=spec.zone).jobs_dir
    )


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


# ---------------------------------------------------------------------------
# The account-wide PRESENCE lease (DR-1 Commit 10 — the ADVISORY concurrency cap, Path A).
#
# The detached runner registers a presence lease AROUND the paid work and releases it in a
# `finally`, so `PresenceRegistry.live_count()` reflects in-flight DR-1 runners — the input the
# HTTP shim's ADVISORY pre-spawn cap reads (`http_shim._deny_over_capacity`) and `begin-session`'s
# `recommended_width` advisory consults. This is the MINIMAL Path-A wiring.
#
# PATH B (DEFERRED — the fidelity follow-up). Path A counts ONLY DR-1 runners, because only THIS
# module registers a lease. A CLI / interactive `main_cli` session that spends against the SAME
# subscription is NOT counted, so `live_count()` under-reports true account concurrency and the
# advisory cap can pass while the account is actually busy. The fix is to register the lease at the
# shared transport CHOKEPOINT (`transport.invoke_headless`) so EVERY paid session — HTTP, CLI,
# interactive — increments the same count. That is intentionally NOT done here (it would move a
# telemetry side effect onto the innermost hot path for every caller); the always-correct bound is
# the RETURNED `rate-limit-backpressure` → 429 backstop regardless, so Path A + the backstop is the
# reconciled Commit-10 scope and Path B is a later refinement.
# ---------------------------------------------------------------------------


def _presence_for(spec: JobSpec) -> PresenceRegistry:
    """The account-wide presence-lease registry (§22.5) under `<root>/instance/ops/presence` — the
    SAME registry the shim's advisory cap and `begin-session`'s width advisory consult (framework
    MECHANISM, instance DATA, gitignored). Content-free: a lease is a random opaque token, never a
    workspace name."""
    return PresenceRegistry(Path(spec.root) / "instance" / "ops" / "presence")


def _acquire_presence(registry: PresenceRegistry) -> str | None:
    """Register this runner's account-wide presence lease around the paid work (Path A, §22.5) so it
    COUNTS toward `live_count()` while in flight. Returns the opaque lease token, or None.

    BEST-EFFORT / OFF THE CRITICAL PATH: the presence registry is operational telemetry (§22.5), NOT
    an INV-CORRECTNESS root, so a registry I/O failure yields NO lease (None) and the paid job runs
    UNIMPEDED — telemetry never breaks the critical path (and the 429 backstop still bounds real
    overspend). NO heartbeat/refresh is needed: the 30-min lease TTL (`LEASE_TTL_SECONDS`)
    comfortably exceeds the 20-min wrapper hard timeout (`WRAPPER_HARD_TIMEOUT_SECONDS`), so a
    single job's lease never lapses mid-work; a DEAD runner's lease self-expires within the TTL
    (§22.5 self-healing), so a crash that skips the `finally` release leaks no permanent count."""
    try:
        return registry.register().token
    except (OSError, TelemetryError):
        return None


def _release_presence(registry: PresenceRegistry, token: str | None) -> None:
    """Release the presence lease in a `finally` — a run that RAISES still drops its lease (no
    leaked count). A None token (register was a best-effort no-op) is itself a no-op; a release I/O
    error is swallowed (the lease self-expires at the TTL anyway — never break the runner on a
    telemetry hiccup)."""
    if token is None:
        return
    try:
        registry.release(token)
    except OSError:
        pass


def run_job(
    spec: JobSpec,
    *,
    job_store: JobStore | None = None,
    invoke: Any = None,
    presence: PresenceRegistry | None = None,
) -> RunOutcome:
    """Run ONE job: re-enter `invoke()` (which acquires the S1 claim inside the handler) and route
    the single outcome to at most one `record_terminal` write (H3). `invoke`/`job_store`/`presence`
    are injectable seams — the tests drive every branch with an injected `invoke` return/raise, a
    tmp `JobStore`, and a tmp `PresenceRegistry`, no live transport. A raiser in `_RAISER_SET` is
    caught and synthesized into a terminal; anything else PROPAGATES (crash → no terminal → the
    poll's re-drivable recovery).

    Concurrency (DR-1 Commit 10, Path A): the runner REGISTERS an account-wide presence lease around
    the paid work and RELEASES it in a `finally` — even a truly-unexpected raise drops the lease
    (no leaked count) — so `PresenceRegistry.live_count()` reflects this in-flight runner for the
    shim's ADVISORY cap. Presence is best-effort (off the critical path): a registry I/O failure
    never blocks the job."""
    store = job_store if job_store is not None else _store_for(spec)
    call = invoke_mod.invoke if invoke is None else invoke
    registry = presence if presence is not None else _presence_for(spec)
    lease_token = _acquire_presence(registry)
    try:
        try:
            out = call(
                spec.verb,
                spec.workspace,
                spec.user,
                dict(spec.params),
                spec.token,
                spec.pins,
                root=spec.root,
                zone=spec.zone,
            )
        except _RAISER_SET as exc:
            code = _raised_terminal_code(exc)
            envelope = {
                "ok": False,
                "verb": spec.verb,
                "workspace": spec.workspace,
                "user": spec.user,
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
    finally:
        # RELEASE in a finally: a return (any branch) OR a truly-unexpected raise still drops the
        # lease — no leaked in-flight count. (A crash that never reaches here self-heals at TTL.)
        _release_presence(registry, lease_token)


def _deliver_callback(spec: JobSpec, outcome: RunOutcome) -> None:
    """W3c: POST the completion WAKEUP callback if one was registered, then record the delivery
    status on the job record. A NO-OP when the spec carries no `callback_url` (poll-only) — the
    common path, so nothing is imported/opened.

    This NEVER affects the job outcome and NEVER crashes the runner: `deliver_callback` catches all
    delivery failure (network/redirect/timeout/rebind) and RETURNS a status instead of raising, and
    `record_callback_status` is a tolerant lossy write (a stolen/vanished record → a no-op). A lost
    or failed callback simply degrades the client to the always-available poll — the job's output
    already materialized. The re-validation uses the FROZEN submit-time allow-list snapshot on the
    spec (the DNS-rebinding re-check), so the detached runner never re-reads instance config. The
    import is FUNCTION-SCOPED (like `main()`'s handler wiring) so the module import graph stays
    acyclic: `pipeline.callback_delivery` imports THIS module, never the reverse at import time."""
    if not spec.callback_url:
        return
    from pipeline.callback_delivery import deliver_callback

    status = deliver_callback(spec, outcome, allowed_hosts=spec.allowed_callback_hosts)
    _store_for(spec).record_callback_status(spec.key, status)


def main(argv: list[str] | None = None) -> int:
    """`python -m pipeline.api.jobrunner <spawn_file>` — the detached entry point. Reads the spawn
    spec, WIRES the production handler surface, runs the job, DELIVERS the optional completion
    wakeup callback (W3c), and deletes the transient spawn file. A truly-unexpected exception
    propagates (non-zero exit, no terminal); the spawn file is cleaned up either way.

    **The runner is a FRESH process, so it MUST wire its own registry (mirrors `serve()`).** The
    detached runner is launched as `python -m pipeline.api.jobrunner <spawn_file>` — a brand-new
    interpreter whose GLOBAL `invoke` handler registry is EMPTY. `run_job` re-enters the SAME
    synchronous `invoke()` a CLI caller would (§21.9), which dispatches against that registry; if
    nothing wires it, EVERY real Tier-B job hits `HandlerNotWired` → a `runner-failed` terminal, and
    the whole DR-1 async door (submit → detached run → materialize) is INERT. So this calls the SAME
    single production startup wiring `http_shim.serve()` runs — `register_api_handlers()` — BEFORE
    `run_job(spec)`. The import is FUNCTION-SCOPED (exactly like `serve()`), so importing this
    module never wires verbs the empty-registry gate tests (`test_session`/`test_workspace_name`)
    rely on staying empty — registration is RUNTIME-only, never at import. `register_handler` is
    overwrite-safe, so this wiring is idempotent."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m pipeline.api.jobrunner <spawn_file>", file=sys.stderr)
        return 2
    spawn_file = Path(args[0])
    spec = JobSpec.from_json(spawn_file.read_text(encoding="utf-8"))
    # Wire the production handler surface into this fresh process's (empty) global registry BEFORE
    # dispatch, so the runner's `invoke()` reaches the REAL handlers instead of the empty-registry
    # `HandlerNotWired` seam. Function-scoped like `serve()`: import-time stays registration-free.
    from pipeline.api.session import register_api_handlers

    register_api_handlers()
    try:
        outcome = run_job(spec)
        # W3c: deliver the optional completion-wakeup callback AFTER the job settled. A callback
        # failure is NOT a job failure — `_deliver_callback` catches everything and records a lossy
        # status; the poll floor is unaffected. A no-op when no callback_url was registered.
        _deliver_callback(spec, outcome)
    finally:
        spawn_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
