"""Step-21 tests: the S0–S6 execution spine (§22.3/§22.7) over the step-20 primitives.

Plan step-21 acceptance under test here: the canonical S0→S6 ordering (checkpoint-spied);
S0 short-circuit — existing id + matching preimage → NO work, NO claim; mismatched
preimage → LOUD (§7.4); the stolen-from worker's late commit LOSES and its release
NO-OPS (B4-4, in-process deterministic + process-level interleaving); S4 folio-marker
semantics (§21.2: dedupe / `member-updated`, `added_ts` preserved); S5 as the pluggable
write-only hook (spy records advance calls; return value never consumed; failure
contained); collision-resistant holder minting (step-20 carry-forward RV-4 — two workers
on one pid get distinct holders); and the REC-3/PC12e crash-point conformance battery —
a crash injected at EVERY S-point, then a concurrent re-drive, asserting no-double-work /
no-miss / benign outcomes per the §22.7 crash table (the SSOT does not exist yet; S5 is
the spy hook — step 36 re-runs the battery under the CSV-serialized SSOT).
"""

import json
import multiprocessing
import os
import re
import time
from pathlib import Path

import pytest

from pipeline.canonical import canonical_json_str
from pipeline.claims import DEFAULT_LEASE_TTL_SECONDS, ClaimRegistry
from pipeline.ids import PreimageMismatchError
from pipeline.spine import (
    S_POINTS,
    FolioAppendOutcome,
    FolioMembership,
    SpineError,
    WorkUnit,
    append_folio_member,
    drive,
    mint_holder,
    registry_for,
)
from pipeline.store import (
    StorePathError,
    WorkspaceStore,
    append_jsonl_line,
    is_temp_name,
    write_new,
    write_replace,
)

# The §7.4 literal examples, verbatim (as in the step-20 batteries).
ART = "a-9f3c07d21b44e8aa"
FIT = "a-9f3c07d21b44e8aa.linkedin.en"
FOLIO = "f-0123456789ab"
FOLIO2 = "f-00000000000a"

#: The candidate/recorded §7.4 preimage for S0's check — any canonicalizable JSON value
#: (the FROZEN artifact shape is §7.2's own concern, tested at test_ids; S0 compares
#: canonical bytes, §7.4).
PREIMAGE = {"kind": "step-21-spine", "seed": 21}
OTHER_PREIMAGE = {"kind": "step-21-spine", "seed": 22}

_SPAWN = multiprocessing.get_context("spawn")


def _record_bytes(preimage, worker: str) -> bytes:
    """An output record carrying its own preimage — the stand-in for the owning binding
    (§15/§16/§17 land later); the recorded-preimage lookup reads it back (§22.7: output
    store ONLY)."""
    return (canonical_json_str({"preimage": preimage, "worker": worker}) + "\n").encode()


def _lookup_for(store: WorkspaceStore):
    def lookup(id_str: str):
        try:
            return json.loads(store.output_path(id_str).read_bytes())["preimage"]
        except FileNotFoundError:
            return None

    return lookup


class ManualClock:
    """An injected epoch-seconds clock — the test owns time (no ambient now())."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class PayloadSpy:
    """S2 spy: counts invocations; the S0-short-circuit tests assert it is NEVER called."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1
        return self.data


@pytest.fixture()
def ws(tmp_path):
    return WorkspaceStore(tmp_path / "ws")


@pytest.fixture()
def clock():
    return ManualClock()


def registry(ws, holder, clock, ttl=DEFAULT_LEASE_TTL_SECONDS):
    return ClaimRegistry(ws.claims_dir, holder=holder, ttl_seconds=ttl, clock=clock)


def unit(worker="worker-a", *, id_str=ART, preimage=PREIMAGE, folios=()):
    return WorkUnit(
        id=id_str,
        payload=PayloadSpy(_record_bytes(preimage, worker)),
        preimage=preimage,
        folios=folios,
    )


# ---------------------------------------------------------------------------
# The canonical sequence (§22.3): S0 → S1 → S2 → S3 → S4 → S5 → S6, spied.
# ---------------------------------------------------------------------------


class TestCanonicalSequence:
    def test_happy_path_fires_every_s_point_in_the_canonical_order(self, ws, clock):
        labels = []
        result = drive(
            unit("worker-a"),
            store=ws,
            claims=registry(ws, "worker-a", clock),
            recorded_preimage=_lookup_for(ws),
            checkpoint=labels.append,
        )
        assert labels == list(S_POINTS)  # §22.3/§22.7: the ordering IS the crash safety
        assert result.code == "ok"
        assert result.materialized is True
        assert result.short_circuit is False
        assert result.claim is not None and result.claim.code == "ok"
        assert result.release is not None
        assert result.release.code == "ok" and result.release.released is True
        assert ws.output_path(ART).read_bytes() == _record_bytes(PREIMAGE, "worker-a")
        assert not (ws.root / "claims" / ART).exists()  # S6 released
        assert result.folio == () and result.advanced is False

    def test_live_claim_skips_with_claim_held_and_never_works(self, ws, clock):
        registry(ws, "incumbent", clock).acquire(ART)
        labels = []
        work = unit("worker-b")
        result = drive(
            work, store=ws, claims=registry(ws, "worker-b", clock), checkpoint=labels.append
        )
        assert labels == ["S0", "S1"]  # nothing past S1 runs on a live lease (§22.3)
        assert result.code == "claim-held"
        assert result.claim is not None and result.claim.holder == "incumbent"
        assert result.release is None and result.folio == ()
        assert work.payload.calls == 0  # the expensive work never ran
        assert not ws.output_path(ART).exists()

    def test_expired_claim_is_stolen_and_driven_to_completion(self, ws, clock):
        registry(ws, "dead-worker", clock).acquire(ART)
        clock.advance(DEFAULT_LEASE_TTL_SECONDS + 1)
        result = drive(unit("worker-b"), store=ws, claims=registry(ws, "worker-b", clock))
        assert result.claim is not None
        assert result.claim.code == "lease-expired-redrive"  # §22.6, visible in the result
        assert result.code == "ok" and result.materialized is True
        assert result.release is not None and result.release.code == "ok"
        assert json.loads(ws.output_path(ART).read_bytes())["worker"] == "worker-b"

    def test_non_bytes_payload_is_refused_loudly(self, ws, clock):
        bad = WorkUnit(id=ART, payload=lambda: "not-bytes", preimage=PREIMAGE)
        with pytest.raises(SpineError, match="not bytes"):
            drive(bad, store=ws, claims=registry(ws, "worker-a", clock))
        assert not ws.output_path(ART).exists()

    def test_payload_exception_propagates_and_the_lease_later_self_expires(self, ws, clock):
        def explode() -> bytes:
            raise RuntimeError("llm fell over")

        with pytest.raises(RuntimeError, match="llm fell over"):
            drive(WorkUnit(id=ART, payload=explode), store=ws, claims=registry(ws, "w-a", clock))
        # Indistinguishable from a crash at S2 (module doc): claim held, target absent.
        assert (ws.root / "claims" / ART).exists()
        assert not ws.output_path(ART).exists()
        # §22.4 PC7: the lease expires → safe re-drive by anyone.
        clock.advance(DEFAULT_LEASE_TTL_SECONDS + 1)
        result = drive(unit("worker-b"), store=ws, claims=registry(ws, "worker-b", clock))
        assert result.code == "ok" and result.claim.code == "lease-expired-redrive"


# ---------------------------------------------------------------------------
# S0: the idempotency pre-check — output store ONLY (§22.7).
# ---------------------------------------------------------------------------


class TestS0ShortCircuit:
    def test_existing_id_matching_preimage_no_work_no_claim(self, ws, clock):
        write_new(ws.output_path(ART), _record_bytes(PREIMAGE, "earlier-run"))
        advanced_ids = []
        labels = []
        work = unit("worker-b", folios=(FolioMembership(FOLIO),))
        result = drive(
            work,
            store=ws,
            claims=registry(ws, "worker-b", clock),
            recorded_preimage=_lookup_for(ws),
            advance=advanced_ids.append,
            checkpoint=labels.append,
        )
        assert result.code == "already-materialized"
        assert result.short_circuit is True
        assert result.materialized is False
        assert result.claim is None and result.release is None  # NO claim was taken
        assert work.payload.calls == 0  # NO work ran
        assert not (ws.root / "claims" / ART).exists()
        assert labels == ["S0", "S4", "S5"]  # S1–S3 and S6 never fire
        # …but the lagging bookkeeping completes (§22.7 crash table: "+ advance"):
        assert advanced_ids == [ART]
        assert (ws.root / "folios" / FOLIO / "members" / ART).is_file()
        # The winner's bytes are untouched.
        assert json.loads(ws.output_path(ART).read_bytes())["worker"] == "earlier-run"

    def test_existing_id_mismatched_preimage_is_loud(self, ws, clock):
        write_new(ws.output_path(ART), _record_bytes(OTHER_PREIMAGE, "earlier-run"))
        work = unit("worker-b", preimage=PREIMAGE)
        with pytest.raises(PreimageMismatchError, match="DIFFERENT recorded"):
            drive(
                work,
                store=ws,
                claims=registry(ws, "worker-b", clock),
                recorded_preimage=_lookup_for(ws),
            )
        assert work.payload.calls == 0
        assert not (ws.root / "claims" / ART).exists()  # refused BEFORE any claim
        # The stored output is untouched by the refusal.
        assert json.loads(ws.output_path(ART).read_bytes())["worker"] == "earlier-run"

    def test_existence_alone_governs_when_no_lookup_is_wired(self, ws, clock):
        # Until the owning binding lands, recorded preimage reads back None — §7.4's
        # check treats None as unseen and existence stays the authority (§22.7).
        write_new(ws.output_path(ART), b"opaque-record\n")
        work = unit("worker-b")
        result = drive(work, store=ws, claims=registry(ws, "worker-b", clock))
        assert result.code == "already-materialized" and result.short_circuit is True
        assert work.payload.calls == 0

    def test_full_drive_then_redrive_short_circuits(self, ws, clock):
        first = drive(
            unit("worker-a"),
            store=ws,
            claims=registry(ws, "worker-a", clock),
            recorded_preimage=_lookup_for(ws),
        )
        assert first.code == "ok"
        again = unit("worker-b")  # same id, same preimage, different worker
        result = drive(
            again,
            store=ws,
            claims=registry(ws, "worker-b", clock),
            recorded_preimage=_lookup_for(ws),
        )
        assert result.code == "already-materialized" and result.short_circuit is True
        assert again.payload.calls == 0
        assert json.loads(ws.output_path(ART).read_bytes())["worker"] == "worker-a"


# ---------------------------------------------------------------------------
# B4-4, deterministic and in-process: steal during S2; the original holder
# resumes through S3–S6 — its late commit LOSES, its release NO-OPS.
# ---------------------------------------------------------------------------


class TestSlowHolderInProcess:
    def test_stolen_from_workers_late_commit_loses_and_release_noops(self, ws, clock):
        ttl = 60.0
        reg_a = registry(ws, "worker-a", clock, ttl=ttl)
        reg_b = registry(ws, "worker-b", clock, ttl=ttl)
        b_steal = {}

        def slow_payload() -> bytes:
            # Mid-S2, worker-a's lease expires and worker-b steals + commits (B4-4).
            clock.advance(ttl + 1)
            b_steal["acquire"] = reg_b.acquire(ART)
            write_new(ws.output_path(ART), _record_bytes(PREIMAGE, "worker-b"))
            return _record_bytes(PREIMAGE, "worker-a")

        result = drive(
            WorkUnit(id=ART, payload=slow_payload, preimage=PREIMAGE),
            store=ws,
            claims=reg_a,
            recorded_preimage=_lookup_for(ws),
        )
        assert b_steal["acquire"].code == "lease-expired-redrive"
        assert result.claim is not None and result.claim.code == "ok"  # a acquired at S1
        # (a) the late S3 commit LOSES to the no-replace primitive:
        assert result.code == "already-materialized" and result.materialized is False
        assert json.loads(ws.output_path(ART).read_bytes())["worker"] == "worker-b"
        # (b) the late S6 release NO-OPS on holder mismatch — b's claim stays live:
        assert result.release is not None
        assert result.release.code == "claim-held" and result.release.released is False
        assert json.loads((ws.root / "claims" / ART).read_bytes())["holder"] == "worker-b"
        # No loser temp survives (the commit primitive discarded it, §22.3).
        assert not [n for n in os.listdir(ws.artifacts_dir) if is_temp_name(n)]
        # The stealer's own release still works — a can never have unlocked it.
        assert reg_b.release(ART).code == "ok"


# ---------------------------------------------------------------------------
# S4: folio append — §21.2 semantics over the §13.3 marker encoding.
# ---------------------------------------------------------------------------


class TestS4FolioAppend:
    def test_fresh_member_marker_created_with_full_record(self, ws, clock):
        memberships = (FolioMembership(FOLIO, pin="v3", role="chapter"),)
        result = drive(
            unit("worker-a", folios=memberships),
            store=ws,
            claims=registry(ws, "worker-a", clock),
        )
        assert result.folio == (FolioAppendOutcome(FOLIO, code="ok", created=True),)
        marker = ws.root / "folios" / FOLIO / "members" / ART
        assert json.loads(marker.read_bytes()) == {
            "added_ts": clock.now,
            "pin": "v3",
            "role": "chapter",
        }

    def test_pinless_roleless_record_omits_the_optional_keys(self, ws, clock):
        append_folio_member(ws, FolioMembership(FOLIO), ART, clock=clock)
        marker = ws.root / "folios" / FOLIO / "members" / ART
        assert json.loads(marker.read_bytes()) == {"added_ts": clock.now}  # A4-4 `pin?/role?`

    def test_identical_reappend_is_the_idempotent_dedupe_noop(self, ws, clock):
        membership = FolioMembership(FOLIO, pin="v3", role="chapter")
        first = append_folio_member(ws, membership, ART, clock=clock)
        t0 = clock.now
        clock.advance(500.0)
        again = append_folio_member(ws, membership, ART, clock=clock)
        assert first == FolioAppendOutcome(FOLIO, code="ok", created=True)
        assert again == FolioAppendOutcome(FOLIO, code="ok", created=False)
        marker = ws.root / "folios" / FOLIO / "members" / ART
        assert json.loads(marker.read_bytes())["added_ts"] == t0  # untouched

    def test_differing_reappend_updates_marker_preserving_added_ts(self, ws, clock):
        append_folio_member(ws, FolioMembership(FOLIO, role="chapter"), ART, clock=clock)
        t0 = clock.now
        clock.advance(500.0)
        out = append_folio_member(ws, FolioMembership(FOLIO, role="appendix"), ART, clock=clock)
        assert out == FolioAppendOutcome(FOLIO, code="member-updated", created=False)
        marker = ws.root / "folios" / FOLIO / "members" / ART
        record = json.loads(marker.read_bytes())
        assert record == {"added_ts": t0, "role": "appendix"}  # §21.2: added_ts PRESERVED

    def test_two_folios_both_appended_in_order(self, ws, clock):
        memberships = (FolioMembership(FOLIO), FolioMembership(FOLIO2, role="lead"))
        result = drive(
            unit("worker-a", folios=memberships),
            store=ws,
            claims=registry(ws, "worker-a", clock),
        )
        assert [f.folio_id for f in result.folio] == [FOLIO, FOLIO2]
        assert (ws.root / "folios" / FOLIO / "members" / ART).is_file()
        assert (ws.root / "folios" / FOLIO2 / "members" / ART).is_file()

    def test_corrupt_marker_is_refused_loudly(self, ws, clock):
        marker = ws.folio_member_path(FOLIO, ART)
        write_replace(marker, b"\x00 not json \x00")
        with pytest.raises(SpineError, match="corrupt folio member marker"):
            append_folio_member(ws, FolioMembership(FOLIO), ART, clock=clock)

    def test_folio_membership_attaches_to_artifact_level_ids_only(self, ws, clock):
        # §9.2 via the store's own validation: markers key by BARE artifact-id.
        bad = WorkUnit(
            id=FIT,
            payload=lambda: _record_bytes(PREIMAGE, "worker-a"),
            preimage=PREIMAGE,
            folios=(FolioMembership(FOLIO),),
        )
        with pytest.raises(StorePathError, match="bare artifact-id"):
            drive(bad, store=ws, claims=registry(ws, "worker-a", clock))


# ---------------------------------------------------------------------------
# S5: the pluggable, write-only SSOT hook — defined here, implemented at step 22.
# ---------------------------------------------------------------------------


class TestS5AdvanceHook:
    def test_spy_hook_records_exactly_one_advance_per_drive(self, ws, clock):
        advanced = []
        result = drive(
            unit("worker-a"),
            store=ws,
            claims=registry(ws, "worker-a", clock),
            advance=advanced.append,
        )
        assert advanced == [ART]
        assert result.advanced is True and result.advance_error is None

    def test_no_hook_means_no_advance_and_no_error(self, ws, clock):
        result = drive(unit("worker-a"), store=ws, claims=registry(ws, "worker-a", clock))
        assert result.advanced is False and result.advance_error is None

    def test_hook_return_value_is_never_consumed_by_control_flow(self, tmp_path, clock):
        # Identical drives; hooks return maximally branch-worthy values (falsy vs truthy)
        # — the spine's outcome and the store end-state must be bit-identical (§22.7
        # guardrail 3: write-only w.r.t. control flow).
        results = []
        for name, ret in (("falsy", False), ("truthy", object())):
            store = WorkspaceStore(tmp_path / name)
            results.append(
                drive(
                    unit("worker-a"),
                    store=store,
                    claims=registry(store, "worker-a", clock),
                    advance=lambda _id, _ret=ret: _ret,
                )
            )
            assert store.output_path(ART).read_bytes() == _record_bytes(PREIMAGE, "worker-a")
            assert not (store.root / "claims" / ART).exists()
        assert results[0] == results[1]  # SpineResult equality, field for field

    def test_hook_failure_is_contained_and_s6_still_releases(self, ws, clock):
        def broken(_id: str) -> None:
            raise RuntimeError("ssot writer offline")

        labels = []
        result = drive(
            unit("worker-a"),
            store=ws,
            claims=registry(ws, "worker-a", clock),
            advance=broken,
            checkpoint=labels.append,
        )
        # §22.7: a failing SSOT writer only lags the human view — never control flow.
        assert result.code == "ok" and result.materialized is True
        assert result.advanced is False
        assert result.advance_error == "RuntimeError: ssot writer offline"
        assert labels == list(S_POINTS)  # S6 still fired
        assert result.release is not None and result.release.code == "ok"
        assert not (ws.root / "claims" / ART).exists()


# ---------------------------------------------------------------------------
# Holder minting (step-20 carry-forward RV-4): collision-resistant tokens.
# ---------------------------------------------------------------------------


class TestHolderMinting:
    def test_holder_token_shape_pid_prefix_plus_128_random_bits(self):
        assert re.fullmatch(rf"h{os.getpid()}-[0-9a-f]{{32}}", mint_holder())

    def test_two_workers_on_the_same_pid_get_distinct_holders(self):
        # RV-4: pid (or any ambient identity) is never the identity — entropy is.
        assert mint_holder() != mint_holder()
        assert len({mint_holder() for _ in range(500)}) == 500

    def test_registry_for_mints_and_wires_a_fresh_holder(self, ws, clock):
        reg_a = registry_for(ws, clock=clock)
        reg_b = registry_for(ws, clock=clock)
        assert reg_a.holder != reg_b.holder
        assert reg_a.claims_dir == ws.claims_dir
        assert reg_a.ttl_seconds == DEFAULT_LEASE_TTL_SECONDS
        # The behavioral point of RV-4: one worker can never satisfy another's
        # holder-compare, so it can never release (or be blamed for) another's claim.
        assert reg_a.acquire(ART).code == "ok"
        out = reg_b.release(ART)
        assert out.code == "claim-held" and out.released is False
        assert (ws.root / "claims" / ART).exists()
        assert reg_a.release(ART).code == "ok"


# ---------------------------------------------------------------------------
# The REC-3/PC12e conformance battery: crash at EVERY S-point, concurrent
# re-drive, benign outcomes — the permanent executable proof of §22.7's table.
# ---------------------------------------------------------------------------


def _conformance_worker(
    root_str: str,
    unit_id: str,
    preimage_json: str,
    worker_tag: str,
    crash_at,
    folio_id: str,
    advance_log_str: str,
    ttl: float,
    barrier,
    queue,
    wait_flag_str,
) -> None:
    """One spine worker in its own process. Crashes hard (`os._exit(17)`) at `crash_at`;
    otherwise reports its SpineResult (as primitives) on the queue and exits 0."""
    try:
        store = WorkspaceStore(Path(root_str))
        reg = ClaimRegistry(
            store.claims_dir, holder=mint_holder(), ttl_seconds=ttl, clock=time.time
        )
        preimage = json.loads(preimage_json)

        def payload() -> bytes:
            if wait_flag_str is not None:  # the SLOW holder: parked mid-S2 by the test
                deadline = time.time() + 60
                while not Path(wait_flag_str).exists():
                    if time.time() > deadline:
                        raise RuntimeError("resume flag never appeared")
                    time.sleep(0.01)
            return _record_bytes(preimage, worker_tag)

        def checkpoint(label: str) -> None:
            if crash_at is not None and label == crash_at:
                os._exit(17)  # a hard crash exactly at this S-point

        def lookup(id_str: str):
            try:
                return json.loads(store.output_path(id_str).read_bytes())["preimage"]
            except FileNotFoundError:
                return None

        def advance(id_str: str) -> None:
            append_jsonl_line(Path(advance_log_str), {"worker": worker_tag, "id": id_str})

        if barrier is not None:
            barrier.wait(timeout=60)
        result = drive(
            WorkUnit(
                id=unit_id,
                payload=payload,
                preimage=preimage,
                folios=(FolioMembership(folio_id),),
            ),
            store=store,
            claims=reg,
            recorded_preimage=lookup,
            advance=advance,
            checkpoint=checkpoint,
        )
        queue.put(
            {
                "worker": worker_tag,
                "code": result.code,
                "materialized": result.materialized,
                "short_circuit": result.short_circuit,
                "claim_code": result.claim.code if result.claim is not None else None,
                "release_code": result.release.code if result.release is not None else None,
                "advanced": result.advanced,
            }
        )
    except Exception as exc:  # noqa: BLE001 — any other outcome is a dirty failure
        queue.put({"worker": worker_tag, "code": f"ERROR:{type(exc).__name__}:{exc}"})


def _sleep_past_lease(claim_path: Path) -> None:
    """Sleep (real time) until the recorded lease is expired, with a safety margin."""
    record = json.loads(claim_path.read_bytes())
    time.sleep(max(0.0, record["lease_expiry"] - time.time()) + 0.3)


class TestCrashPointConformance:
    """REC-3/PC12e: crash injected at every S-point; concurrent workers re-drive; the
    §22.7 crash table holds — no double work, no missed work, benign codes only. (No
    SSOT exists yet — S5 is the JSONL spy hook; step 36 re-runs this battery under the
    CSV-serialized SSOT.)"""

    @pytest.mark.parametrize("crash_at", S_POINTS)
    def test_crash_then_concurrent_redrive_is_benign(self, tmp_path, crash_at):
        root = tmp_path / "ws"
        store = WorkspaceStore(root)
        log = tmp_path / "advance.jsonl"
        out = store.output_path(ART)
        claim = store.claims_dir / ART
        marker = root / "folios" / FOLIO / "members" / ART
        preimage_json = json.dumps(PREIMAGE)

        # --- Phase A: one worker dies EXACTLY at the S-point (ttl kept short). --------
        qa = _SPAWN.Queue()
        args_a = (
            str(root),
            ART,
            preimage_json,
            "wA",
            crash_at,
            FOLIO,
            str(log),
            1.0,
            None,
            qa,
            None,
        )
        pa = _SPAWN.Process(target=_conformance_worker, args=args_a)
        pa.start()
        pa.join(timeout=60)
        assert pa.exitcode == 17  # it really died at the injection point

        # --- The §22.7 crash-table postconditions at this S-point. --------------------
        if crash_at == "S0":
            assert not out.exists() and not claim.exists()
        elif crash_at in ("S1", "S2"):
            assert not out.exists() and claim.exists()  # lock held by a dead worker
        else:  # S3..S6: the id is materialized; bookkeeping may lag, never contradicts
            assert json.loads(out.read_bytes())["worker"] == "wA"
        assert marker.exists() == (crash_at in ("S4", "S5", "S6"))
        assert log.exists() == (crash_at in ("S5", "S6"))
        assert claim.exists() == (crash_at in ("S1", "S2", "S3", "S4", "S5"))
        artifacts_dir = root / "artifacts"
        orphan_temps = (
            {n for n in os.listdir(artifacts_dir) if is_temp_name(n)}
            if artifacts_dir.is_dir()
            else set()
        )
        if crash_at == "S2":
            assert len(orphan_temps) == 1  # the staged temp, inert + identifiable (A4)

        # --- Phase B: FOUR concurrent workers re-drive the same id. -------------------
        if crash_at in ("S1", "S2"):
            _sleep_past_lease(claim)  # the dead worker's lease must self-expire (PC7)
        n_procs = 4
        barrier = _SPAWN.Barrier(n_procs)
        qb = _SPAWN.Queue()
        procs = []
        for i in range(n_procs):
            args_b = (
                str(root),
                ART,
                preimage_json,
                f"wB{i}",
                None,
                FOLIO,
                str(log),
                60.0,
                barrier,
                qb,
                None,
            )
            procs.append(_SPAWN.Process(target=_conformance_worker, args=args_b))
        for p in procs:
            p.start()
        results = [qb.get(timeout=120) for _ in range(n_procs)]
        for p in procs:
            p.join(timeout=60)
        assert all(p.exitcode == 0 for p in procs)
        errors = [r for r in results if str(r["code"]).startswith("ERROR")]
        assert errors == []

        # --- NO-MISS: the id is materialized, wholly present, preimage intact. --------
        record = json.loads(out.read_bytes())
        assert record["preimage"] == PREIMAGE
        # --- Benign codes only (closed §21.7/§22.6 vocabulary). -----------------------
        assert {r["code"] for r in results} <= {"ok", "already-materialized", "claim-held"}
        # --- NO-DOUBLE-WORK: exactly one materializer ever, per the crash point. ------
        if crash_at in ("S0", "S1", "S2"):
            materializers = [r for r in results if r["materialized"]]
            assert len(materializers) == 1
            assert record["worker"] == materializers[0]["worker"]
            if crash_at in ("S1", "S2"):
                # The dead worker's expired lease was STOLEN, visibly (§22.6).
                assert any(r["claim_code"] == "lease-expired-redrive" for r in results)
            assert not claim.exists()  # the final holder's S6 released it
        else:
            # Already materialized by the dead worker: every re-drive is the benign
            # `already-materialized` no-op that completes the lagging bookkeeping.
            assert record["worker"] == "wA"
            assert all(r["code"] == "already-materialized" for r in results)
            assert all(r["short_circuit"] for r in results)
            assert not any(r["materialized"] for r in results)
            # No re-driver touched the dead worker's claim (no claim is taken at S0
            # short-circuit); it stays until its lease self-expires (§22.3).
            assert claim.exists() == (crash_at in ("S3", "S4", "S5"))
        # --- Bookkeeping completed by the re-drive (crash table: "… + advance"). ------
        assert json.loads(marker.read_bytes())["added_ts"] > 0
        advances = [json.loads(line) for line in log.read_text().splitlines()]
        assert [a for a in advances if a["id"] == ART]
        assert all(r["advanced"] for r in results if r["code"] != "claim-held")
        # --- A4: a crash-dropped temp is inert and never GC'd by the re-drive. --------
        temps_after = {n for n in os.listdir(root / "artifacts") if is_temp_name(n)}
        assert orphan_temps <= temps_after


class TestSlowHolderStealInterleavingAcrossProcesses:
    """The §22.7 guardrail-4 interleaving, process-level: steal during S2; the original
    holder resumes through S3–S6 — late commit loses, late release no-ops (B4-4)."""

    def test_steal_during_s2_original_holder_resumes_s3_to_s6(self, tmp_path):
        root = tmp_path / "ws"
        store = WorkspaceStore(root)
        log = tmp_path / "advance.jsonl"
        flag = tmp_path / "resume-flag"
        out = store.output_path(ART)
        claim = store.claims_dir / ART
        preimage_json = json.dumps(PREIMAGE)

        # Worker A: short lease; its payload parks mid-S2 until the test says resume.
        qa = _SPAWN.Queue()
        args_a = (
            str(root),
            ART,
            preimage_json,
            "wA",
            None,
            FOLIO,
            str(log),
            0.75,
            None,
            qa,
            str(flag),
        )
        pa = _SPAWN.Process(target=_conformance_worker, args=args_a)
        pa.start()
        deadline = time.time() + 60
        a_holder = None
        while a_holder is None and time.time() < deadline:
            try:
                a_holder = json.loads(claim.read_bytes())["holder"]
            except (FileNotFoundError, ValueError):
                time.sleep(0.01)
        assert a_holder is not None  # A holds the claim and is parked inside S2

        # Worker B: arrives after A's lease expired, steals, works, commits — and dies
        # at S5, so its claim is STILL LIVE when A resumes (the holder-mismatch case).
        _sleep_past_lease(claim)
        qb = _SPAWN.Queue()
        args_b = (
            str(root),
            ART,
            preimage_json,
            "wB",
            "S5",
            FOLIO,
            str(log),
            60.0,
            None,
            qb,
            None,
        )
        pb = _SPAWN.Process(target=_conformance_worker, args=args_b)
        pb.start()
        pb.join(timeout=60)
        assert pb.exitcode == 17
        assert json.loads(out.read_bytes())["worker"] == "wB"  # the stealer committed
        b_holder = json.loads(claim.read_bytes())["holder"]
        assert b_holder != a_holder  # the steal replaced the claim record
        assert [json.loads(x)["worker"] for x in log.read_text().splitlines()] == ["wB"]

        # Resume A: it drives S3–S6 against the stolen state.
        flag.write_text("resume\n")
        result_a = qa.get(timeout=60)
        pa.join(timeout=60)
        assert pa.exitcode == 0
        assert result_a["claim_code"] == "ok"  # A had acquired normally back at S1
        assert result_a["code"] == "already-materialized"  # (a) its late commit LOST
        assert result_a["materialized"] is False
        assert result_a["release_code"] == "claim-held"  # (b) its late release NO-OPED
        # A could neither overwrite the stealer's output nor unlock its live claim:
        assert json.loads(out.read_bytes())["worker"] == "wB"
        assert json.loads(claim.read_bytes())["holder"] == b_holder
        # A's re-drive completed the lagging bookkeeping (advance for the id, again).
        advances = [json.loads(x) for x in log.read_text().splitlines()]
        assert [a["worker"] for a in advances] == ["wB", "wA"]
        assert all(a["id"] == ART for a in advances)
        # No stray temps: A's losing temp was discarded by the commit primitive.
        assert not [n for n in os.listdir(root / "artifacts") if is_temp_name(n)]
