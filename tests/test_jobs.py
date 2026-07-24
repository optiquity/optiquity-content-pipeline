"""DR-1 Commit 3 tests: the lossy job record + TTL+steal lifecycle (H2) + poll resolver (H3).

Pure logic under test — a fake clock (`now` is always an explicit float) and injected
`is_done`/`peek` authorities drive EVERY branch with NO sockets/HTTP/subprocess. The load-bearing
invariants proven here (`pipeline.jobs`):

- **Idempotency floor (N-2):** the same logical request (same sorted+deduped target set + same
  `idempotency_key`) → the SAME `r-<hex16>` key; a different set/key → a different key.
- **H2 lifecycle:** happy `create_exclusive` → one record, spawn; a re-submit within the JOB-
  LIFETIME window (even past the old 120 s line) or with a live claim → existing, NO re-spawn (the
  anti-double-charge guard); a stored terminal → STEAL + re-spawn (the retry path); a runner-died-
  pre-claim past the window (no claim, output absent) → STEAL + re-spawn.
- **Reshaped truth-table (all 5 branches, in order):** DONE (output) → RUNNING (live claim) →
  FAILED (stored terminal, surfaced PROMPTLY above the window) → RUNNING (within the JOB-LIFETIME
  window) → FAILED-re-drivable (past the window). An EXPIRED-lease `peek` is NOT live (the resolver
  compares `lease_expiry` to `now` itself).
- **§22.7 lossy discipline:** a present record with the output absent is NEVER DONE; a DELETED
  record with the output present IS DONE (output authority); a deleted record with no output / no
  claim / past the window resolves re-drivable — never a wedge, never a false DONE.
- **N-5:** a deterministic block stores NOTHING (the sweep re-derives it); a nondeterministic
  failure round-trips the terminal envelope and surfaces at resolver step 3 (above the window).

Everything lives under pytest `tmp_path` — nothing is created under the repo's `workspaces/`.
"""

from __future__ import annotations

import json
import os

import pytest

from pipeline.api.results import (
    CODE_DRIFT_BLOCK,
    CODE_EMPTY_POOL,
    CODE_HARD_LIMIT_EXCEEDED,
    CODE_OUT_OF_WINDOW,
)
from pipeline.claims import ClaimRecord
from pipeline.ids import IdError, parse_id
from pipeline.jobs import (
    DETERMINISTIC_BLOCK_CODES,
    JobError,
    JobRecord,
    JobState,
    JobStore,
    JobTerminal,
    is_deterministic_block,
    job_key,
    resolve_job_state,
)
from pipeline.opdefaults import JOB_LIFETIME_SECONDS, NASCENT_RECORD_GRACE_SECONDS

# §7.4 literal artifact ids — the "predictable target ids" a generate-next job fans out to.
A = "a-9f3c07d21b44e8aa"
B = "a-1111111111111111"
C = "a-2222222222222222"

T0 = 1_000_000.0  # the injected epoch-seconds base — the test owns time (no ambient now())
# The reshape splits the old single 120 s grace into TWO windows:
LIFETIME = float(JOB_LIFETIME_SECONDS)  # the assume-still-running / running-vs-dead window (22 min)
NASCENT = float(NASCENT_RECORD_GRACE_SECONDS)  # the short torn/nascent-record grace (seconds-scale)


class Authorities:
    """The injected §22.7 authorities: a set of materialized (done) ids + a claim/lease table.

    `peek` returns a ClaimRecord for ANY id in `claims` — even an EXPIRED lease (mirroring
    `claims.peek`, which does no clock check) — so the resolver must compare `lease_expiry` to
    `now` itself. A NASCENT-None claim is modeled by simply leaving the id out of `claims`.
    """

    def __init__(self) -> None:
        self.done: set[str] = set()
        self.claims: dict[str, float] = {}  # target_id -> lease_expiry (live OR expired)

    def is_done(self, target_id: str) -> bool:
        return target_id in self.done

    def peek(self, target_id: str) -> ClaimRecord | None:
        expiry = self.claims.get(target_id)
        return None if expiry is None else ClaimRecord(holder="runner", lease_expiry=expiry)


@pytest.fixture()
def auth() -> Authorities:
    return Authorities()


@pytest.fixture()
def jobs_dir(tmp_path):
    return tmp_path / "ws" / "jobs"


@pytest.fixture()
def store(jobs_dir) -> JobStore:
    return JobStore(jobs_dir)


# ---------------------------------------------------------------------------
# The reshaped window constants: one generous lifetime line + a short nascent grace.
# ---------------------------------------------------------------------------


class TestWindowConstants:
    def test_job_lifetime_sits_above_a_paid_call_and_below_the_lease_ttl(self):
        # The derived window is load-bearing for the reshape: it must sit ABOVE one full paid call
        # (WRAPPER_HARD_TIMEOUT) so active work of ANY duration is covered by the live-claim check
        # (not this window), and BELOW the lease TTL so a claim acquired late in a long batch stays
        # live past the record window. The window then only ever governs the brief no-claim spans.
        from pipeline.opdefaults import (
            LEASE_TTL_SECONDS,
            WRAPPER_HARD_TIMEOUT_SECONDS,
        )

        assert JOB_LIFETIME_SECONDS == WRAPPER_HARD_TIMEOUT_SECONDS + NASCENT_RECORD_GRACE_SECONDS
        assert WRAPPER_HARD_TIMEOUT_SECONDS < JOB_LIFETIME_SECONDS < LEASE_TTL_SECONDS
        # The nascent grace stays seconds-scale — far below the lifetime window (the split that
        # ended the Commit-6 double-meaning).
        assert NASCENT_RECORD_GRACE_SECONDS < WRAPPER_HARD_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# The job key: the idempotency floor (N-2) + input validation.
# ---------------------------------------------------------------------------


class TestJobKey:
    def test_same_request_same_key_regardless_of_target_order(self):
        # Same sorted+deduped target set + same idempotency_key → byte-identical preimage → SAME
        # r-<hex16> key: a retry of the same request collides on ONE key (the idempotency floor).
        k1 = job_key([A, B, C], "idk-1")
        k2 = job_key([C, A, B], "idk-1")  # different order
        k3 = job_key([A, B, B, C, A], "idk-1")  # duplicates
        assert k1 == k2 == k3

    def test_a_different_target_set_or_key_yields_a_different_key(self):
        base = job_key([A, B], "idk-1")
        assert base != job_key([A, C], "idk-1")  # different set
        assert base != job_key([A, B], "idk-2")  # different idempotency_key
        assert base != job_key([A], "idk-1")  # different cardinality

    def test_none_idempotency_key_is_stable_and_distinct_from_a_string(self):
        assert job_key([A, B], None) == job_key([B, A], None)
        assert job_key([A, B], None) != job_key([A, B], "idk-1")

    def test_the_key_is_a_run_family_id_never_an_artifact_id(self):
        # The Commit-2 boundary pin: the key parses as a run id, so it can never collide with an
        # artifact output name nor route through output_path/is_done.
        assert parse_id(job_key([A, B], "idk-1")).family == "run"

    def test_empty_target_set_is_refused(self):
        with pytest.raises(JobError, match="at least one target id"):
            job_key([], "idk-1")

    def test_a_non_id_target_is_refused(self):
        with pytest.raises(IdError):
            job_key(["not a valid id"], "idk-1")

    def test_an_empty_idempotency_key_string_is_refused(self):
        with pytest.raises(JobError, match="idempotency_key"):
            job_key([A], "")


# ---------------------------------------------------------------------------
# (b-H2) submit: create-exclusive happy path + TTL+steal lifecycle.
# ---------------------------------------------------------------------------


class TestSubmitLifecycle:
    def _submit(self, store, auth, targets=(A, B), idk="idk-1", *, now):
        return store.submit(targets, idk, now=now, is_done=auth.is_done, peek=auth.peek)

    def test_happy_create_exclusive_writes_one_record_and_spawns(self, store, auth, jobs_dir):
        out = self._submit(store, auth, now=T0)
        assert out.spawn is True
        assert out.disposition == "spawned"
        # Exactly ONE record file, named the run-family key, parsing to a running record.
        files = list(jobs_dir.iterdir())
        assert [f.name for f in files] == [out.key]
        record = json.loads(files[0].read_bytes())
        assert record["status"] == "running"
        assert record["spawn_time"] == T0
        assert record["terminal"] is None
        assert record["target_ids"] == sorted([A, B])  # canonical order

    def test_a_one_shot_iterator_input_is_materialized_once(self, store, auth, jobs_dir):
        # REGRESSION: target_ids may be a one-shot generator. submit must materialize it EXACTLY
        # once — a second iteration of a spent generator would persist an EMPTY target set, which
        # defeats the done/existing short-circuits and spuriously steals a live/materialized job.
        out = store.submit(
            (x for x in (A, B)), "idk-1", now=T0, is_done=auth.is_done, peek=auth.peek
        )
        record = json.loads((jobs_dir / out.key).read_bytes())
        assert record["target_ids"] == list(tuple(sorted((A, B))))  # NOT empty, canonical order
        assert store.load(out.key).target_ids == tuple(sorted((A, B)))
        # And a re-submit (fresh generator) of the now-fully-materialized job returns DONE, not a
        # spurious steal — proving the persisted target set drives the short-circuit.
        auth.done.update({A, B})
        again = store.submit(
            (x for x in (A, B)),
            "idk-1",
            now=T0 + LIFETIME + 1,
            is_done=auth.is_done,
            peek=auth.peek,
        )
        assert again.disposition == "done"
        assert again.spawn is False

    def test_a_resubmit_within_the_lifetime_window_does_not_respawn(self, store, auth):
        first = self._submit(store, auth, now=T0)
        second = self._submit(store, auth, now=T0 + LIFETIME / 2)  # within the job-lifetime window
        assert first.spawn is True
        assert second.spawn is False
        assert second.disposition == "existing"
        assert second.key == first.key  # the same key — no second record, no second spawn (N-2)

    def test_a_resubmit_past_120s_but_within_lifetime_does_not_respawn(self, store, auth, jobs_dir):
        # THE ANTI-DOUBLE-CHARGE CORE: a retry landing PAST the old 120 s line but WITHIN the
        # 22-min job-lifetime window — with NO live claim (a no-claim gap: startup / between
        # artifacts / the commit tail) — must be answered `existing`, NOT stolen+re-spawned. Under
        # the Commit-6 120 s boundary this exact case hit submit's stale branch → a SECOND paid run.
        first = self._submit(store, auth, now=T0)
        assert first.spawn is True
        second = self._submit(store, auth, now=T0 + NASCENT + 5)  # past 120 s, no claim, no output
        assert second.spawn is False  # NO second spawn — the double-charge is prevented
        assert second.disposition == "existing"
        assert second.key == first.key
        # And there is exactly ONE record on disk — the re-submit created no second job.
        assert [f.name for f in jobs_dir.iterdir()] == [first.key]

    def test_a_live_claim_past_the_window_does_not_respawn(self, store, auth):
        # Past the job-lifetime window, but a runner holds a LIVE claim on a target → actively
        # running (a claim acquired late in a long batch), so the re-submit returns the existing
        # job (no re-spawn). The live claim is the authority for active work of ANY duration.
        self._submit(store, auth, now=T0)
        auth.claims[A] = T0 + LIFETIME + 10_000  # a live lease past the window
        out = self._submit(store, auth, now=T0 + LIFETIME + 1)
        assert out.spawn is False
        assert out.disposition == "existing"

    def test_runner_died_pre_claim_past_the_window_steals_and_respawns(self, store, auth, jobs_dir):
        # THE H2 case: submit → runner dies BEFORE acquiring any claim → PAST the window, no live
        # claim, output absent → a re-submit STEALS the stale record and re-spawns (not a
        # FileExistsError wedge, and not a second spawn while still within the window — see above).
        first = self._submit(store, auth, now=T0)
        out = self._submit(store, auth, now=T0 + LIFETIME + 1)
        assert out.spawn is True
        assert out.disposition == "stolen"
        assert out.key == first.key
        # The steal reset the window: the record's spawn_time is now the re-submit's clock.
        record = json.loads((jobs_dir / out.key).read_bytes())
        assert record["spawn_time"] == T0 + LIFETIME + 1
        assert record["terminal"] is None  # a fresh running record

    def test_a_fully_materialized_job_resolves_done_without_spawning(self, store, auth):
        self._submit(store, auth, now=T0)
        auth.done.update({A, B})  # every target's output now exists (§22.7 authority #1)
        out = self._submit(store, auth, now=T0 + LIFETIME + 1)
        assert out.spawn is False
        assert out.disposition == "done"

    def test_a_partially_materialized_job_past_the_window_still_steals(self, store, auth):
        # Only SOME targets done, no live claim, past the window → the job is not complete and the
        # runner is gone → steal + re-spawn (the runner re-drives the incomplete targets).
        self._submit(store, auth, now=T0)
        auth.done.add(A)  # A done, B not
        out = self._submit(store, auth, now=T0 + LIFETIME + 1)
        assert out.spawn is True
        assert out.disposition == "stolen"

    def test_a_non_run_key_is_refused_at_the_jobs_path(self, store):
        with pytest.raises(JobError, match="run-family id"):
            store.path_for(A)  # an artifact id can never be a job key


class TestSubmitNascentWindow:
    """The §22.3 nascent-write window for the record itself, guarded by the SHORT `nascent_grace`
    (the renamed, seconds-scale grace): a torn record within the mtime grace is NOT stolen (that
    would double-spawn a live job); past it, it is stealable. This window is DISTINCT from — and
    much smaller than — the job-lifetime window."""

    def _torn_record(self, store, targets=(A, B), idk="idk-1") -> str:
        key = job_key(targets, idk)
        path = store.path_for(key)
        path.write_bytes(b"{ not json")  # a torn/partial create — _read → "unreadable"
        return key

    def test_a_torn_record_within_the_nascent_grace_is_not_respawned(self, store, auth):
        key = self._torn_record(store)
        os.utime(store.path_for(key), (T0, T0))  # anchor the implicit grace at T0
        out = store.submit(
            (A, B), "idk-1", now=T0 + 1, is_done=auth.is_done, peek=auth.peek
        )
        assert out.spawn is False
        assert out.disposition == "existing"

    def test_a_torn_record_past_the_nascent_grace_is_stolen(self, store, auth):
        # Past the SHORT nascent grace (seconds-scale) a torn record is stealable — a crashed
        # submitter's torn write does not wedge for the full job lifetime.
        key = self._torn_record(store)
        os.utime(store.path_for(key), (T0, T0))
        out = store.submit(
            (A, B), "idk-1", now=T0 + NASCENT + 1, is_done=auth.is_done, peek=auth.peek
        )
        assert out.spawn is True
        assert out.disposition == "stolen"


# ---------------------------------------------------------------------------
# resolve_job_state: the reshaped truth-table, all 5 branches (terminal above the window).
# ---------------------------------------------------------------------------


def _record(*, spawn_time=T0, terminal=None, targets=(A,)) -> JobRecord:
    return JobRecord(
        target_ids=tuple(targets),
        idempotency_key="idk-1",
        spawn_time=spawn_time,
        status="failed" if terminal is not None else "running",
        terminal=terminal,
    )


def _resolve(record, auth, *, now, target=A) -> JobState:
    return resolve_job_state(record, target, now=now, is_done=auth.is_done, peek=auth.peek)


class TestResolverTruthTable:
    def test_branch1_output_exists_is_done(self, auth):
        auth.done.add(A)
        state = _resolve(_record(spawn_time=T0), auth, now=T0)
        assert state == JobState("done", "output-exists")

    def test_branch2_live_claim_is_running(self, auth):
        auth.claims[A] = T0 + LIFETIME + 500  # live lease past the window
        # Past the window so ONLY the live claim can produce RUNNING (isolates branch 2).
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert state == JobState("running", "claim-live")

    def test_branch3_stored_terminal_surfaces_promptly_within_the_window(self, auth):
        # A stored terminal is checked ABOVE the window: a runner that recorded a terminal has
        # EXITED, so even WELL WITHIN the 22-min window (past the old 120 s line) the failure
        # surfaces PROMPTLY — it is never masked as RUNNING for the full job lifetime.
        terminal = JobTerminal(code="api-error", envelope={"ok": False}, results=[])
        state = _resolve(_record(spawn_time=T0, terminal=terminal), auth, now=T0 + NASCENT + 5)
        assert state.kind == "failed"
        assert state.detail == "stored-terminal"
        assert state.terminal == terminal

    def test_branch3_stored_terminal_also_surfaces_past_the_window(self, auth):
        terminal = JobTerminal(code="api-error", envelope={"ok": False}, results=[])
        state = _resolve(_record(spawn_time=T0, terminal=terminal), auth, now=T0 + LIFETIME + 1)
        assert state == JobState("failed", "stored-terminal", terminal=terminal)

    def test_branch4_within_the_lifetime_window_is_running_keep_checking(self, auth):
        # THE CORE FIX: a nascent-None claim (peek None) PAST the old 120 s line but WITHIN the
        # job-lifetime window → RUNNING/keep-checking (a slow start or a no-claim gap), NOT dead.
        # Under the Commit-6 120 s boundary this exact poll fell through to FAILED-re-drivable and
        # told a still-running job to resend — the double-charge trigger.
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + NASCENT + 5)
        assert state == JobState("running", "within-lifetime")
        # And still RUNNING right up to (just before) the window's edge.
        edge = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME - 1)
        assert edge == JobState("running", "within-lifetime")

    def test_branch5_past_the_window_no_live_work_is_redrivable(self, auth):
        # Record present, PAST the window, no claim, no terminal, output absent → re-drivable.
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert state == JobState("failed-redrivable", "no-live-work")


class TestResolverExpiredLease:
    def test_an_expired_lease_peek_is_not_running(self, auth):
        # peek returns a record EVEN for an expired lease — the resolver must compare lease_expiry
        # to now itself. Past the window so branch 4 cannot mask it: an EXPIRED lease → NOT running.
        auth.claims[A] = T0  # lease_expiry == T0; now is later ⇒ expired
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert state.kind != "running"
        assert state == JobState("failed-redrivable", "no-live-work")

    def test_a_lease_exactly_at_now_is_expired_not_live(self, auth):
        # Liveness is strict: now < lease_expiry. At now == lease_expiry the lease is NOT live.
        auth.claims[A] = T0 + LIFETIME + 1
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert state.kind != "running"

    def test_a_live_lease_one_second_before_expiry_is_running(self, auth):
        auth.claims[A] = T0 + LIFETIME + 2
        state = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert state == JobState("running", "claim-live")


# ---------------------------------------------------------------------------
# §22.7 lossy discipline (load-bearing): output existence + the claim are the SOLE authorities.
# ---------------------------------------------------------------------------


class TestLossyDiscipline:
    def test_record_present_output_absent_is_never_done(self, auth):
        # A present record with the output absent is NEVER DONE — whether within the window
        # (running) or past it (re-drivable), the kind is never "done".
        within = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME / 2)
        past = _resolve(_record(spawn_time=T0), auth, now=T0 + LIFETIME + 1)
        assert within.kind != "done"
        assert past.kind != "done"

    def test_deleted_record_output_present_is_done(self, auth):
        # A DELETED/missing record (record=None) with the output present IS DONE — output existence
        # is the authority, not the bookkeeping record.
        auth.done.add(A)
        state = _resolve(None, auth, now=T0 + 10 * LIFETIME)
        assert state == JobState("done", "output-exists")

    def test_deleted_record_no_output_no_claim_past_window_is_redrivable(self, auth):
        # A deleted record + output absent + no claim → re-drivable (no wedge, no false DONE). The
        # record branches (3/4) cannot fire with record=None, so it lands at branch 5 at any time.
        state = _resolve(None, auth, now=T0 + 10 * LIFETIME)
        assert state == JobState("failed-redrivable", "no-live-work")

    def test_store_resolve_reads_a_real_record_and_an_unreadable_one_is_absent(self, store, auth):
        # JobStore.resolve loads by key. A live record within the window → running; a torn record
        # resolves as ABSENT (load → None) → the read-only side degrades safely, never wedges.
        out = store.submit((A, B), "idk-1", now=T0, is_done=auth.is_done, peek=auth.peek)
        running = store.resolve(
            out.key, A, now=T0 + LIFETIME / 2, is_done=auth.is_done, peek=auth.peek
        )
        assert running == JobState("running", "within-lifetime")
        store.path_for(out.key).write_bytes(b"garbage")  # torn record
        assert store.load(out.key) is None
        absent = store.resolve(
            out.key, A, now=T0 + LIFETIME + 1, is_done=auth.is_done, peek=auth.peek
        )
        assert absent == JobState("failed-redrivable", "no-live-work")


# ---------------------------------------------------------------------------
# (N-5) record_terminal: NONDETERMINISTIC failures stored; deterministic blocks NOT.
# ---------------------------------------------------------------------------


class TestRecordTerminal:
    def test_every_deterministic_block_code_is_classified(self):
        for code in (
            CODE_EMPTY_POOL,
            CODE_OUT_OF_WINDOW,
            CODE_DRIFT_BLOCK,
            CODE_HARD_LIMIT_EXCEEDED,
        ):
            assert is_deterministic_block(code) is True
            assert code in DETERMINISTIC_BLOCK_CODES
        assert is_deterministic_block("timeout") is False
        assert is_deterministic_block("api-error") is False

    def test_a_deterministic_block_stores_nothing(self, store, auth):
        out = store.submit((A, B), "idk-1", now=T0, is_done=auth.is_done, peek=auth.peek)
        stored = store.record_terminal(
            out.key, code=CODE_EMPTY_POOL, envelope={"ok": False}, results=[]
        )
        assert stored is False
        # The record still carries NO terminal — the completeness sweep re-derives the block.
        assert store.load(out.key).terminal is None
        # And a poll past the window with no claim resolves re-drivable (branch 5), not FAILED.
        state = store.resolve(
            out.key, A, now=T0 + LIFETIME + 1, is_done=auth.is_done, peek=auth.peek
        )
        assert state == JobState("failed-redrivable", "no-live-work")

    def test_a_nondeterministic_failure_round_trips_and_surfaces(self, store, auth):
        out = store.submit((A, B), "idk-1", now=T0, is_done=auth.is_done, peek=auth.peek)
        envelope = {"ok": False, "code": "timeout"}
        results = [{"item": A, "status": "block", "code": "timeout"}]
        stored = store.record_terminal(out.key, code="timeout", envelope=envelope, results=results)
        assert stored is True
        record = store.load(out.key)
        assert record.status == "failed"
        assert record.terminal == JobTerminal(code="timeout", envelope=envelope, results=results)
        # A poll surfaces the stored terminal PROMPTLY (branch 3) — even WITHIN the window, past the
        # old 120 s line, with no live claim, the failure is not masked for 22 min.
        state = store.resolve(
            out.key, A, now=T0 + NASCENT + 5, is_done=auth.is_done, peek=auth.peek
        )
        assert state.kind == "failed"
        assert state.detail == "stored-terminal"
        assert state.terminal.code == "timeout"

    def test_record_terminal_is_a_noop_when_no_record_exists(self, store):
        # Lossy bookkeeping never fabricates a record: attaching a terminal to a vanished key is a
        # no-op (the resolver still resolves safely).
        key = job_key((A,), "idk-1")
        assert store.record_terminal(key, code="timeout", envelope={}, results=[]) is False
        assert store.load(key) is None

    def test_a_terminal_recorded_resubmit_steals_and_respawns_the_retry_path(self, store, auth):
        # THE RETRY PATH: a re-submit of a TERMINAL-recorded job STEALS + re-spawns — PROMPTLY,
        # even WITHIN the job-lifetime window (past the old 120 s line). A recorded terminal means
        # the runner EXITED, so re-driving by the same key is correct; without the terminal→steal
        # branch this retry would be answered `existing` and WEDGE for up to 22 min. The steal
        # writes a FRESH running record — the old terminal is gone (the job is genuinely re-driven).
        out = store.submit((A, B), "idk-1", now=T0, is_done=auth.is_done, peek=auth.peek)
        store.record_terminal(out.key, code="timeout", envelope={"ok": False}, results=[])
        stolen = store.submit(
            (A, B), "idk-1", now=T0 + NASCENT + 5, is_done=auth.is_done, peek=auth.peek
        )
        assert stolen.disposition == "stolen"
        assert stolen.spawn is True
        record = store.load(out.key)
        assert record.terminal is None
        assert record.status == "running"
