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

import pipeline.api.invoke as invoke_mod
from pipeline.api.invoke import KNOWN_VERBS, HandlerNotWired
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
from pipeline.opdefaults import JOB_LIFETIME_SECONDS, NASCENT_RECORD_GRACE_SECONDS
from pipeline.transport import ApiKeyPresentError, BinaryNotFoundError

# §7.4 literal artifact ids — the predictable target ids a generate-next job fans out to.
A = "a-9f3c07d21b44e8aa"
B = "a-1111111111111111"

T0 = 1_000_000.0  # the injected epoch-seconds base (the test owns time)
LIFETIME = float(JOB_LIFETIME_SECONDS)  # the running-vs-dead / job-lifetime window (22 min)
NASCENT = float(NASCENT_RECORD_GRACE_SECONDS)  # the short torn/nascent-record grace (seconds-scale)
WS = "ws"
USER = "acme"
IDK = "idk-1"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the invoke dispatch registry (the house pattern of `test_http_shim`/
    `test_action_completeness`). REQUIRED because the non-injected `main()` test now calls
    `register_api_handlers()` IN-PROCESS: without restore the real handlers would LEAK into the
    empty-registry gate tests (`test_session`/`test_workspace_name`), which assert the registry is
    unwired. Every other test here injects the `invoke` seam and never registers, so the snapshot is
    a no-op for them."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def _never_done(_id: str) -> bool:
    return False


def _never_claimed(_id: str):
    return None


@pytest.fixture
def jobs_dir(tmp_path):
    return tmp_path / "users" / USER / "zones" / "default" / "workspaces" / WS / "jobs"


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
        user=USER,
        params=params or {"action": "generate-next"},
        idempotency_key=IDK,
        root="/repo-root",
        token=token,
        pins=None,
        zone="default",
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
        # A poll surfaces the stored terminal PROMPTLY (resolver branch 3, above the window): even
        # WITHIN the lifetime window with no live claim, a recorded failure is not masked.
        state = store.resolve(
            key, A, now=T0 + NASCENT + 5, is_done=_never_done, peek=_never_claimed
        )
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
        # Past the window with no claim, no output, no stored terminal → re-drivable (branch 5).
        state = store.resolve(
            key, A, now=T0 + LIFETIME + 1, is_done=_never_done, peek=_never_claimed
        )
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
# The account-wide PRESENCE lease (DR-1 Commit 10 — the ADVISORY concurrency cap, Path A). The
# runner REGISTERS a lease around the paid work and RELEASES it in a `finally`, so the shim's
# `live_count()` reflects in-flight DR-1 runners. Best-effort / off the critical path: a presence
# I/O failure NEVER breaks the paid job.
# ---------------------------------------------------------------------------


class TestPresenceLease:
    def test_runner_counts_while_in_flight_and_releases_after(self, store, tmp_path):
        # `live_count` reflects the in-flight runner DURING the paid work and DROPS to 0 after — the
        # register-around-run + finally-release wiring the shim's advisory cap reads.
        from pipeline.telemetry import PresenceRegistry

        registry = PresenceRegistry(tmp_path / "instance" / "ops" / "presence")
        seen: dict = {}

        def _invoke_observing(*_a, **_k):
            seen["during"] = registry.live_count()  # observed WHILE the runner holds its lease
            return {"envelope": _envelope(), "results": [{"item": A, "status": "ok", "ids": {}}]}

        assert registry.live_count() == 0  # nothing registered before the run
        key = _submit_record(store)
        outcome = run_job(_spec(key), job_store=store, invoke=_invoke_observing, presence=registry)
        assert outcome == RunOutcome("clean", None, False)
        assert seen["during"] == 1  # the in-flight runner COUNTED toward the account-wide cap
        assert registry.live_count() == 0  # released in the `finally` after the run

    def test_a_raising_run_still_releases_the_lease_no_leak(self, store, tmp_path):
        # A truly-unexpected raise PROPAGATES (crash → no terminal), but the `finally` still drops
        # the presence lease — no leaked in-flight count that would wedge the advisory cap.
        from pipeline.telemetry import PresenceRegistry

        registry = PresenceRegistry(tmp_path / "instance" / "ops" / "presence")
        key = _submit_record(store)
        with pytest.raises(RuntimeError, match="boom"):
            run_job(
                _spec(key),
                job_store=store,
                invoke=_raiser(RuntimeError("boom — unexpected")),
                presence=registry,
            )
        assert registry.live_count() == 0  # released even on a truly-unexpected raise

    def test_a_caught_raiser_terminal_run_also_releases(self, store, tmp_path):
        # The caught-raiser branch (render `_EngineError` → a recorded re-drivable terminal) returns
        # normally THROUGH the finally — it too drops the lease.
        from pipeline.telemetry import PresenceRegistry

        registry = PresenceRegistry(tmp_path / "instance" / "ops" / "presence")
        key = _submit_record(store)
        exc = _EngineError("reconcile did not fit a-… (status=error code=timeout)")
        outcome = run_job(
            _spec(key, verb="render"), job_store=store, invoke=_raiser(exc), presence=registry
        )
        assert outcome == RunOutcome("terminal-raised", RE_DRIVABLE_CODE, True)
        assert registry.live_count() == 0

    def test_presence_io_failure_never_blocks_the_paid_job(self, store):
        # Best-effort / off the critical path: a registry whose register() RAISES must NOT break
        # run_job — the paid job still runs and returns its outcome (telemetry never wedges spend).
        class _BrokenRegistry:
            def register(self):
                raise OSError("presence dir unwritable")

            def release(self, token):  # pragma: no cover — a None token is never released
                raise AssertionError("release must not run for a best-effort no-op token")

        key = _submit_record(store)
        outcome = run_job(
            _spec(key), job_store=store, invoke=_invoke_clean, presence=_BrokenRegistry()
        )
        assert outcome == RunOutcome("clean", None, False)  # ran despite the presence failure

    def test_default_presence_registry_is_root_scoped_instance_ops(self, tmp_path):
        # The default (non-injected) registry homes under `<root>/instance/ops/presence` — the SAME
        # account-wide registry the shim's advisory cap + begin-session's width advisory consult.
        from pipeline.api.jobrunner import _presence_for

        spec = JobSpec(
            key=job_key((A,), IDK),
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
            zone="default",
        )
        registry = _presence_for(spec)
        assert registry.ops_dir == tmp_path / "instance" / "ops" / "presence"


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

    def test_callback_url_rides_the_spawn_file_round_trip(self):
        # W3b/W3c: the (already submit-validated) callback_url + the predictable target_ids + the
        # FROZEN operator allow-list snapshot all ride the JobSpec spawn FILE to the detached runner
        # (W3c delivers against them) — as_json/from_json round-trip each; absent ⇒ None / empty.
        cb = "http://hooks.example.com/exec-1"
        hosts = frozenset({"hooks.example.com", "other.example.com:5678"})
        spec = JobSpec(
            key=job_key((A,), IDK),
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root="/repo-root",
            callback_url=cb,
            target_ids=(A, B),
            allowed_callback_hosts=hosts,
            zone="default",
        )
        restored = JobSpec.from_json(spec.as_json())
        assert restored.callback_url == cb
        assert restored.target_ids == (A, B)
        assert restored.allowed_callback_hosts == hosts  # frozenset ↔ sorted-list round-trip
        # A spec with no callback fields round-trips to the poll-only defaults.
        bare = JobSpec.from_json(_spec(job_key((A,), IDK)).as_json())
        assert bare.callback_url is None
        assert bare.target_ids == ()
        assert bare.allowed_callback_hosts == frozenset()

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
        # Past the window, no claim, no output → the record resolves re-drivable AND a re-submit
        # steals (the runner died before acquiring a claim; the durable record is re-spawnable).
        state = store.resolve(
            key, A, now=T0 + LIFETIME + 1, is_done=_never_done, peek=_never_claimed
        )
        assert state == JobState("failed-redrivable", "no-live-work")
        again = store.submit(
            (A,), IDK, now=T0 + LIFETIME + 1, is_done=_never_done, peek=_never_claimed
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
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
            zone="default",
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

    def test_main_non_injected_registers_then_dispatches_to_the_real_handler(self, tmp_path):
        """DR-1 rework W2 (the inert-runner regression guard): the detached runner is a FRESH
        process whose `invoke()` dispatches against the GLOBAL registry, so `main()` MUST wire it
        (`register_api_handlers()`, like `serve()`) BEFORE `run_job`, or every real Tier-B job hits
        `HandlerNotWired` → a `runner-failed` terminal and the whole async door is inert.

        Proven WITHOUT the injected `invoke`/handlers seam that hid the bug: the REAL registry, the
        REAL `invoke`, a REAL `JobStore`. No LLM — a TOKEN-LESS `generate-next` returns the
        token-required BLOCK inside the real handler BEFORE any transport, so the runner records a
        plain re-drivable terminal. If `main()` forgot to register, `invoke` would raise
        `HandlerNotWired` and the terminal would be `runner-failed` instead — the assertion below
        pins the difference."""
        from pipeline.api import jobrunner

        # (b) The IMPORT-EMPTY gate holds at test entry: importing `pipeline.api.jobrunner` (top of
        # this module) wired NOTHING. main() must register at RUNTIME, never at import.
        assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))

        # A REAL JobStore at the EXACT path main() resolves (`_store_for`), with the record already
        # written by submit (record → spawn → claim). No injected store, no injected invoke.
        key = job_key((A,), IDK)
        spec = JobSpec(
            key=key,
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},  # token-less → the real handler blocks, no LLM
            idempotency_key=IDK,
            root=str(tmp_path),
            zone="default",
        )
        job_store = jobrunner._store_for(spec)  # the SAME store main() records into
        submitted = job_store.submit((A,), IDK, now=T0, is_done=_never_done, peek=_never_claimed)
        assert submitted.key == key

        spawn_dir = tmp_path / "spawn"
        spawn_dir.mkdir()
        spawn_file = spawn_dir / "spawn.json"
        spawn_file.write_text(spec.as_json(), encoding="utf-8")

        assert jobrunner.main([str(spawn_file)]) == 0
        assert not spawn_file.exists()  # the transient spawn file is always cleaned up

        # (a) main() REGISTERED the whole production surface — the closed verb map is wired now.
        assert set(KNOWN_VERBS) <= set(invoke_mod._VERB_HANDLERS)

        # The runner DISPATCHED to the REAL handler (not the empty-registry seam): a token-less
        # generate-next is a code-less block → a RE_DRIVABLE terminal. With the bug (no
        # registration) invoke would raise HandlerNotWired → a `runner-failed` terminal instead.
        terminal = job_store.load(key).terminal
        assert terminal is not None
        assert terminal.code == RE_DRIVABLE_CODE
        assert terminal.code != TERMINAL_FAILED_CODE  # NOT the HandlerNotWired `runner-failed` path

    def _spawn_for(self, tmp_path, spec):
        """Write `spec`'s record (record → spawn → claim) + its spawn file; return the JobStore."""
        from pipeline.api import jobrunner

        job_store = jobrunner._store_for(spec)  # the SAME store main() records into
        job_store.submit(
            list(spec.target_ids), IDK, now=T0, is_done=_never_done, peek=_never_claimed
        )
        spawn_dir = tmp_path / "spawn"
        spawn_dir.mkdir()
        spawn_file = spawn_dir / "spawn.json"
        spawn_file.write_text(spec.as_json(), encoding="utf-8")
        return job_store, spawn_file

    def test_main_delivers_the_callback_and_records_the_status(self, tmp_path, monkeypatch):
        """W3c: after run_job settles, main() DELIVERS the wakeup callback (production defaults) and
        records the returned status on the job record. The delivery seam is stubbed so no real
        network is touched — this proves the WIRING (spec + RunOutcome reach it; status lands)."""
        import pipeline.callback_delivery as cbd
        from pipeline.api import jobrunner

        cb = "https://hooks.example.com/exec-1"
        hosts = frozenset({"hooks.example.com"})
        key = job_key((A,), IDK)
        spec = JobSpec(
            key=key,
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
            callback_url=cb,
            target_ids=(A,),
            allowed_callback_hosts=hosts,
            zone="default",
        )
        job_store, spawn_file = self._spawn_for(tmp_path, spec)

        captured = {}

        def _fake_deliver(spec_, outcome_, *, allowed_hosts, **_kw):  # noqa: ANN001, ANN202
            captured["callback_url"] = spec_.callback_url
            captured["allowed_hosts"] = allowed_hosts
            captured["disposition"] = outcome_.disposition
            return "delivered"

        monkeypatch.setattr(cbd, "deliver_callback", _fake_deliver)
        monkeypatch.setattr(jobrunner.invoke_mod, "invoke", _invoke_clean)

        assert jobrunner.main([str(spawn_file)]) == 0
        # The delivery ran against the spec's URL + the FROZEN submit-time allow-list, on settled
        # RunOutcome; and the returned status was recorded on the (lossy) job record.
        assert captured == {
            "callback_url": cb,
            "allowed_hosts": hosts,
            "disposition": "clean",
        }
        assert job_store.load(key).callback_status == "delivered"

    def test_main_callback_failure_does_not_affect_the_job_outcome(self, tmp_path, monkeypatch):
        """A callback FAILURE is NOT a job failure: main() still returns 0, the failed status is
        recorded, and the clean job's terminal/output is untouched (poll floor is unaffected)."""
        import pipeline.callback_delivery as cbd
        from pipeline.api import jobrunner

        key = job_key((A,), IDK)
        spec = JobSpec(
            key=key,
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
            callback_url="https://hooks.example.com/exec-1",
            target_ids=(A,),
            allowed_callback_hosts=frozenset({"hooks.example.com"}),
            zone="default",
        )
        job_store, spawn_file = self._spawn_for(tmp_path, spec)
        monkeypatch.setattr(cbd, "deliver_callback", lambda *a, **k: "failed")  # noqa: ARG005
        monkeypatch.setattr(jobrunner.invoke_mod, "invoke", _invoke_clean)

        assert jobrunner.main([str(spawn_file)]) == 0  # a failed callback ≠ a failed job
        record = job_store.load(key)
        assert record.callback_status == "failed"
        assert record.terminal is None  # the clean job's terminal is untouched by the delivery

    def test_main_with_no_callback_url_delivers_nothing(self, tmp_path, monkeypatch):
        """No callback_url ⇒ deliver_callback is NEVER invoked (poll-only) and callback_status stays
        None. The seam is stubbed to RAISE if called — main() returning 0 proves it was not."""
        import pipeline.callback_delivery as cbd
        from pipeline.api import jobrunner

        key = job_key((A,), IDK)
        spec = JobSpec(
            key=key,
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next"},
            idempotency_key=IDK,
            root=str(tmp_path),
            target_ids=(A,),
            zone="default",
        )
        job_store, spawn_file = self._spawn_for(tmp_path, spec)

        def _must_not_deliver(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("deliver_callback must not run when no callback_url is set")

        monkeypatch.setattr(cbd, "deliver_callback", _must_not_deliver)
        monkeypatch.setattr(jobrunner.invoke_mod, "invoke", _invoke_clean)

        assert jobrunner.main([str(spawn_file)]) == 0  # returned 0 ⇒ the seam was never called
        assert job_store.load(key).callback_status is None

    def test_module_import_does_not_register_in_a_fresh_process(self):
        """The import-empty gate, proven in a genuinely FRESH interpreter (exactly the real detached
        process): importing `pipeline.api.jobrunner` must NOT wire any verb — registration is
        RUNTIME-only (inside `main()`, function-scoped like `serve()`). A module-level register
        import would silently break the empty-registry gate tests (`test_session`/
        `test_workspace_name`); this catches that independently of in-process test ordering."""
        probe = (
            "import pipeline.api.jobrunner\n"
            "import pipeline.api.invoke as i\n"
            "leaked = set(i.KNOWN_VERBS) & set(i._VERB_HANDLERS)\n"
            "assert not leaked, sorted(leaked)\n"
            "print('import-empty-ok')\n"
        )
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "import-empty-ok" in proc.stdout
