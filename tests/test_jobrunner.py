"""DR-1 Commit 4 tests: the detached Tier-B runner (verb-aware H3 outcome router) + the
detached-spawn primitive.

Injected seams only — an injected `invoke` (RETURN or RAISE) drives every outcome branch, and a
mock `Popen` drives the spawn primitive. NO live transport, NO real subprocess, NO real socket
(the REAL detached-spawn / cross-process `peek` end-to-end proof is the Commit-I integration
harness). The load-bearing invariants proven here (`pipeline.api.jobrunner`):

- **Clean success** → the id materializes by output existence; the runner records NO terminal
  (§22.7 — DONE is authored by the output, never by a job record).
- **H3 verb-asymmetry:** a RETURNED coded `timeout` block (`generate-next`) → a re-drivable
  terminal via the RETURNED-code path (NOT a caught exception); a RAISED `_EngineError` (`render`)
  → a re-drivable terminal via the CATCH. A code-less transport block (the REAL `generate-next`
  path) routes the SAME way as a structured code.
- **N-5:** a DETERMINISTIC block RESULT stores NOTHING (the sweep re-derives it).
- **Idempotent re-entry:** running the same key twice does not double-store / fork the record.
- **Crash recovery:** a truly-unexpected exception PROPAGATES with no terminal (the poll's
  re-drivable path + the claim-lease expiry recover it).
- **Spawn primitive:** `Popen` is called `start_new_session=True, close_fds=True` with NO secret
  on argv, and `spawn_runner` returns without waiting; a spawn failure leaves the record stealable.

Everything lives under pytest `tmp_path` — nothing is created under the repo's `workspaces/`.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from pipeline.api.invoke import HandlerNotWired
from pipeline.api.jobrunner import (
    RE_DRIVABLE_CODE,
    RUNNER_MODULE,
    TERMINAL_FAILED_CODE,
    JobSpec,
    RunOutcome,
    run_job,
    spawn_runner,
)
from pipeline.api.render import _EngineError
from pipeline.api.results import CODE_EMPTY_POOL, CODE_HARD_LIMIT_EXCEEDED
from pipeline.driver import DriverError
from pipeline.jobs import JobState, JobStore, job_key
from pipeline.opdefaults import STARTUP_GRACE_SECONDS
from pipeline.transport import ApiKeyPresentError, BinaryNotFoundError

# §7.4 literal artifact ids — the predictable target ids a generate-next job fans out to.
A = "a-9f3c07d21b44e8aa"
B = "a-1111111111111111"

T0 = 1_000_000.0  # the injected epoch-seconds base (the test owns time)
GRACE = float(STARTUP_GRACE_SECONDS)
WS = "ws"
IDK = "idk-1"


def _never_done(_id: str) -> bool:
    return False


def _never_claimed(_id: str):
    return None


@pytest.fixture
def jobs_dir(tmp_path):
    return tmp_path / "workspaces" / WS / "jobs"


@pytest.fixture
def store(jobs_dir) -> JobStore:
    return JobStore(jobs_dir)


def _submit_record(store: JobStore, targets=(A,), idk: str = IDK) -> str:
    """Create the job record (as `JobStore.submit`/Commit 6 does BEFORE the spawn) and return the
    key the runner records terminals against."""
    out = store.submit(targets, idk, now=T0, is_done=_never_done, peek=_never_claimed)
    return out.key


def _spec(key: str, *, verb: str = "continue-session", token=None, params=None) -> JobSpec:
    return JobSpec(
        key=key,
        verb=verb,
        workspace=WS,
        params=params or {"action": "generate-next"},
        idempotency_key=IDK,
        root="/repo-root",
        token=token,
        pins=None,
    )


# --- injected `invoke` seams (each accepts the real invoke() call shape) --------------------


def _envelope(ok: bool = True, code: str | None = None) -> dict:
    env = {"ok": ok, "verb": "continue-session", "workspace": WS}
    if code is not None:
        env["code"] = code
    return env


def _invoke_clean(*_a, **_k) -> dict:
    return {"envelope": _envelope(), "results": [{"item": A, "status": "ok", "ids": {}}]}


def _invoke_returned_timeout(*_a, **_k) -> dict:
    # generate-next H3: a RETURNED coded timeout block — envelope ok, per-item block (NOT a raise).
    return {"envelope": _envelope(), "results": [{"item": A, "status": "block", "code": "timeout"}]}


def _invoke_returned_codeless_block(*_a, **_k) -> dict:
    # The REAL generate-next path: a CODE-LESS `_block` (the transport code rides the hint only).
    return {
        "envelope": _envelope(),
        "results": [{"item": A, "status": "block", "remediation": {"hint": "…code=timeout…"}}],
    }


def _invoke_deterministic_block(*_a, **_k) -> dict:
    return {
        "envelope": _envelope(),
        "results": [{"item": A, "status": "block", "code": CODE_EMPTY_POOL}],
    }


def _invoke_whole_invocation_failure(*_a, **_k) -> dict:
    return {
        "envelope": _envelope(ok=False, code="unknown-verb"),
        "results": [{"item": "bogus-verb", "status": "block", "code": "unknown-verb"}],
    }


def _raiser(exc: BaseException):
    def seam(*_a, **_k):
        raise exc

    return seam


# ---------------------------------------------------------------------------
# The outcome router (H3).
# ---------------------------------------------------------------------------


class TestCleanSuccess:
    def test_clean_success_records_no_terminal(self, store):
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_clean)
        assert outcome == RunOutcome("clean", None, False)
        # DONE is authored by output existence, never a terminal — the record stays terminal-free.
        assert store.load(key).terminal is None


class TestReturnedFailures:
    def test_h3_generate_next_returned_timeout_records_redrivable_terminal(self, store):
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_returned_timeout)
        # The RETURNED-code path (NOT a caught exception): disposition names the returned branch.
        assert outcome == RunOutcome("terminal-returned", "timeout", True)
        record = store.load(key)
        assert record.terminal is not None
        assert record.terminal.code == "timeout"  # Commit 6 maps timeout → a re-drivable 504
        # A poll past grace with no live claim surfaces the stored terminal (resolver branch 4).
        state = store.resolve(key, A, now=T0 + GRACE + 1, is_done=_never_done, peek=_never_claimed)
        assert state.kind == "failed" and state.detail == "stored-terminal"

    def test_h3_generate_next_codeless_block_records_redrivable_terminal(self, store):
        # The REAL generate-next path (code-less _block) routes the SAME as a structured code.
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_returned_codeless_block)
        assert outcome == RunOutcome("terminal-returned", RE_DRIVABLE_CODE, True)
        assert store.load(key).terminal.code == RE_DRIVABLE_CODE

    def test_deterministic_block_returned_stores_nothing(self, store):
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_deterministic_block)
        assert outcome == RunOutcome("skip-deterministic", None, False)
        # N-5: the sweep re-derives the block, so the runner stores NOTHING.
        assert store.load(key).terminal is None
        state = store.resolve(key, A, now=T0 + GRACE + 1, is_done=_never_done, peek=_never_claimed)
        assert state == JobState("failed-redrivable", "no-live-work")

    def test_every_deterministic_generation_block_is_skipped(self, store):
        def block_seam(code: str):
            def seam(*_a, **_k):
                return {
                    "envelope": _envelope(),
                    "results": [{"item": A, "status": "block", "code": code}],
                }

            return seam

        for code in (CODE_EMPTY_POOL, CODE_HARD_LIMIT_EXCEEDED):
            key = _submit_record(store, idk=f"idk-{code}")
            outcome = run_job(_spec(key), job_store=store, invoke=block_seam(code))
            assert outcome.disposition == "skip-deterministic" and outcome.stored is False

    def test_whole_invocation_failure_records_terminal(self, store):
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_whole_invocation_failure)
        assert outcome == RunOutcome("terminal-returned", "unknown-verb", True)
        assert store.load(key).terminal.code == "unknown-verb"


class TestRaisedFailures:
    def test_h3_render_engine_error_raise_records_redrivable_terminal(self, store):
        key = _submit_record(store)
        exc = _EngineError("reconcile did not fit a-… (status=error code=timeout)")
        outcome = run_job(_spec(key, verb="render"), job_store=store, invoke=_raiser(exc))
        # The CATCH path (render): a synthesized re-drivable terminal, NOT the returned-code path.
        assert outcome == RunOutcome("terminal-raised", RE_DRIVABLE_CODE, True)
        term = store.load(key).terminal
        assert term.code == RE_DRIVABLE_CODE
        assert term.envelope["ok"] is False
        assert "reconcile did not fit" in term.envelope["message"]

    @pytest.mark.parametrize(
        ("exc", "expected_code"),
        [
            (ApiKeyPresentError("an explicit env_overrides entry"), "api-key-present"),
            (BinaryNotFoundError("binary-not-found: claude"), "binary-not-found"),
            (DriverError("driver-error: wiring defect"), "driver-error"),
            (HandlerNotWired("render"), TERMINAL_FAILED_CODE),
        ],
    )
    def test_env_wiring_raisers_record_a_terminal_failed(self, store, exc, expected_code):
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_raiser(exc))
        assert outcome == RunOutcome("terminal-raised", expected_code, True)
        assert store.load(key).terminal.code == expected_code

    def test_truly_unexpected_exception_propagates_and_records_no_terminal(self, store):
        key = _submit_record(store)
        with pytest.raises(RuntimeError, match="boom"):
            run_job(_spec(key), job_store=store, invoke=_raiser(RuntimeError("boom — unexpected")))
        # Crash → no terminal → the poll's re-drivable path + the claim-lease expiry recover it.
        assert store.load(key).terminal is None


class TestIdempotentReentry:
    def test_same_key_reentry_does_not_double_store_or_fork_the_record(self, store, jobs_dir):
        key = _submit_record(store)
        first = run_job(_spec(key), job_store=store, invoke=_invoke_returned_timeout)
        second = run_job(_spec(key), job_store=store, invoke=_invoke_returned_timeout)
        assert first == second == RunOutcome("terminal-returned", "timeout", True)
        # Exactly ONE record file for the key — the re-entry overwrites, it never forks/duplicates.
        assert [p.name for p in sorted(jobs_dir.iterdir())] == [key]
        assert store.load(key).terminal.code == "timeout"


# ---------------------------------------------------------------------------
# The detached-spawn primitive.
# ---------------------------------------------------------------------------


class _RecordingPopen:
    """A mock `Popen`: records the argv + kwargs, never spawns, exposes a wait probe."""

    def __init__(self) -> None:
        self.argv: list[str] | None = None
        self.kwargs: dict | None = None
        self.pid = 4242
        self.waited = False

    def __call__(self, argv, **kwargs):
        self.argv = list(argv)
        self.kwargs = kwargs
        return self

    def wait(self, *_a, **_k):  # pragma: no cover — asserted NEVER called
        self.waited = True

    def communicate(self, *_a, **_k):  # pragma: no cover — asserted NEVER called
        self.waited = True


class TestSpawnPrimitive:
    def test_spawn_detaches_with_flags_and_no_secret_on_argv(self, tmp_path):
        popen = _RecordingPopen()
        spec = _spec(job_key((A,), IDK), token="SECRET-CURSOR-VALUE")
        handle = spawn_runner(spec, spawn_dir=tmp_path / "spawn", popen=popen)

        # Detach flags (child outlives the shim; does not inherit the server socket).
        assert popen.kwargs == {"start_new_session": True, "close_fds": True}
        # `python -m pipeline.api.jobrunner <spawn_file>` — the ONLY argv is the spawn-file path.
        assert popen.argv[0] == sys.executable
        assert popen.argv[1:3] == ["-m", RUNNER_MODULE]
        assert popen.argv[3] == str(handle.spawn_file)
        # NO secret / structured param on argv — the token (a §20 cursor) rides the spawn FILE only.
        assert not any("SECRET-CURSOR-VALUE" in str(a) for a in popen.argv)
        assert JobSpec.from_json(handle.spawn_file.read_text()).token == "SECRET-CURSOR-VALUE"
        # Returned immediately, never waited on.
        assert handle.pid == 4242 and popen.waited is False

    def test_spawn_uses_real_popen_default(self):
        # The default `popen` seam IS `subprocess.Popen` (the real detached primitive) — pinned so a
        # refactor that drops the default is caught (the injection is a TEST seam, not the default).
        import inspect

        assert inspect.signature(spawn_runner).parameters["popen"].default is subprocess.Popen

    def test_spawn_failure_leaves_the_record_stealable_and_cleans_the_spawn_file(
        self, store, jobs_dir, tmp_path
    ):
        # record → spawn → claim: the record is written by submit BEFORE the spawn. A Popen failure
        # is the H2 stale-record case — the durable record survives and is re-spawnable (Commit 3).
        key = _submit_record(store)

        def failing_popen(_argv, **_k):
            raise OSError("cannot fork")

        with pytest.raises(OSError, match="cannot fork"):
            spawn_runner(_spec(key), spawn_dir=jobs_dir, popen=failing_popen)

        # The orphan spawn file is cleaned up; the durable job record is untouched.
        assert not (jobs_dir / f"spawn-{key}.json").exists()
        assert (jobs_dir / key).exists()
        # Past grace, no claim, no output → the record resolves re-drivable AND a re-submit steals.
        state = store.resolve(key, A, now=T0 + GRACE + 1, is_done=_never_done, peek=_never_claimed)
        assert state == JobState("failed-redrivable", "no-live-work")
        again = store.submit(
            (A,), IDK, now=T0 + GRACE + 1, is_done=_never_done, peek=_never_claimed
        )
        assert again.disposition == "stolen" and again.spawn is True


# ---------------------------------------------------------------------------
# The `-m` entry point.
# ---------------------------------------------------------------------------


class TestMain:
    def test_main_reads_spawn_file_runs_job_and_deletes_it(self, tmp_path, monkeypatch):
        from pipeline.api import jobrunner

        # A valid workspace name + tmp root so `_store_for` resolves a contained store root.
        spawn_dir = tmp_path / "spawn"
        spawn_dir.mkdir()
        spec = JobSpec(
            key=job_key((A,), IDK),
            verb="continue-session",
            workspace=WS,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
        )
        spawn_file = spawn_dir / "spawn.json"
        spawn_file.write_text(spec.as_json(), encoding="utf-8")
        monkeypatch.setattr(jobrunner.invoke_mod, "invoke", _invoke_clean)

        assert jobrunner.main([str(spawn_file)]) == 0
        # The transient spawn file is always cleaned up; a clean success records no terminal.
        assert not spawn_file.exists()

    def test_main_usage_error_on_wrong_argc(self):
        from pipeline.api import jobrunner

        assert jobrunner.main([]) == 2
