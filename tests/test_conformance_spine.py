"""Step-36: the FULL §22.7 conformance proof — the crash battery under the REAL CSV SSOT.

This EXTENDS the step-21 spine crash battery (`tests/test_spine.py`) to the full §22.7
guardrail 4, with the JSONL spy hook REPLACED by the actual `pipeline.ssot.Ssot` — the
CSV-serialized single-writer SSOT — so the whole four-write-target machine is exercised end to
end. Every scenario runs ACTUAL processes with real step interleaving (never a mock that hides
the race):

- **(a) a crash injected at EVERY S-point (S0–S6)** — `os._exit(17)` at the checkpoint seam;
- **(b) CONCURRENT workers** — a barrier-synced fan-out re-drives the same id;
- **(c) the CSV-serialized single-writer SSOT under contention** — every worker's S5 advances
  the SSOT through the `fcntl.flock` funnel; a dedicated test drives N processes advancing N
  DISTINCT rows at once (the classic lost-update hazard) and proves no row is lost, no CSV torn;
- **(d) the slow-holder STEAL interleaving** — a steal during S2 while the original holder is
  parked, then the ORIGINAL resumes S3–S6: its late no-replace commit LOSES, its holder-checked
  release NO-OPS. Collision-resistant holders (RV-4) make the release safe: only genuine lease
  EXPIRY permits a redrive; a non-holder can neither steal a LIVE claim nor release another's.

The proof at every scenario: EXACTLY-ONCE materialization (one winner's bytes, intact preimage),
no torn state (the CSV parses + `derive_state` renders), no double-write (the no-replace commit
admits one winner), no lost unit (the completeness sweep finds nothing missing), and the SSOT is
a LAGGING MONOTONIC PROJECTION that only ever advances to `composed` — never gating control flow.

No `live` marker: no subscription transport is touched (the payload is a local byte record).
"""

from __future__ import annotations

import csv
import io
import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

from pipeline import parallel
from pipeline.canonical import canonical_json_str
from pipeline.claims import ClaimRegistry
from pipeline.plan import Plan, PlanItem
from pipeline.spine import FolioMembership, WorkUnit, drive, mint_holder
from pipeline.ssot import Ssot, derive_state
from pipeline.store import WorkspaceStore, is_temp_name

ART = "a-9f3c07d21b44e8aa"
FOLIO = "f-0123456789ab"
PREIMAGE = {"kind": "step-36-conformance", "seed": 36}
_SPAWN = multiprocessing.get_context("spawn")


def _record_bytes(preimage, worker: str) -> bytes:
    return (canonical_json_str({"preimage": preimage, "worker": worker}) + "\n").encode()


def _row_status(csv_path: Path, row_id: str) -> str | None:
    """The status of one SSOT row read straight from the CSV — and it must be exactly ONE row
    (a single-writer, torn-free table). None when absent."""
    text = csv_path.read_bytes().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    matches = [r for r in reader if r["id"] == row_id]
    assert len(matches) <= 1, f"{len(matches)} rows for {row_id!r} — not single-writer"
    return matches[0]["status"] if matches else None


def _sweep_one(store: WorkspaceStore, artifact_id: str):
    """A one-item wave plan sweep for the no-lost-unit check (store-only, §22.7)."""
    plan = Plan(
        workspace="ws",
        recipe="r",
        source_subset=(),
        source_commit={},
        items=(
            PlanItem(
                artifact_id=artifact_id,
                preimage={},
                topic="t",
                persona="p",
                format="f",
                voice="v",
                goals=(),
                m3=None,  # type: ignore[arg-type]
                deliverables=(),
            ),
        ),
        plan_hash="feedfacefeedface",
        warnings=(),
    )
    return parallel.sweep(parallel.build_wave_plan(plan), store)


# ---------------------------------------------------------------------------
# The conformance worker: one spine drive in its own process, S5 = the real SSOT.
# ---------------------------------------------------------------------------


def _conformance_worker(
    root_str, unit_id, preimage_json, worker_tag, crash_at, folio_id,
    csv_path_str, ttl, barrier, queue, wait_flag_str,
) -> None:
    """One spine worker; S5 advances the REAL CSV SSOT (holder-checked, monotonic). Crashes hard
    (`os._exit(17)`) at `crash_at`; else reports its SpineResult primitives + its minted holder."""
    try:
        store = WorkspaceStore(Path(root_str))
        reg = ClaimRegistry(
            store.claims_dir, holder=mint_holder(), ttl_seconds=ttl, clock=time.time
        )
        ssot = Ssot(Path(csv_path_str))
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
                os._exit(17)

        def lookup(id_str: str):
            try:
                return json.loads(store.output_path(id_str).read_bytes())["preimage"]
            except FileNotFoundError:
                return None

        advance = ssot.advance_hook("composed")  # S5: the real single-writer CSV advance
        if barrier is not None:
            barrier.wait(timeout=60)
        result = drive(
            WorkUnit(
                id=unit_id, payload=payload, preimage=preimage,
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
                "holder": reg.holder,
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
    record = json.loads(claim_path.read_bytes())
    time.sleep(max(0.0, record["lease_expiry"] - time.time()) + 0.3)


def _spawn(args):
    return _SPAWN.Process(target=_conformance_worker, args=args)


# ---------------------------------------------------------------------------
# (a)+(b)+(c): crash at EVERY S-point, concurrent re-drive, real CSV SSOT.
# ---------------------------------------------------------------------------


class TestFullConformanceUnderSsot:
    @pytest.mark.parametrize("crash_at", ("S0", "S1", "S2", "S3", "S4", "S5", "S6"))
    def test_crash_then_concurrent_redrive_is_exactly_once_and_ssot_coherent(
        self, tmp_path, crash_at
    ):
        root = tmp_path / "ws"
        store = WorkspaceStore(root)
        csv_path = root / "ssot.csv"
        Ssot(csv_path).register(ART, "artifact")  # the fanout row (planning-time, §24)
        out = store.output_path(ART)
        claim = store.claims_dir / ART
        marker = root / "folios" / FOLIO / "members" / ART
        preimage_json = json.dumps(PREIMAGE)

        # --- Phase A: one worker dies EXACTLY at the S-point (short ttl). --------------
        qa = _SPAWN.Queue()  # kept in a variable so its semaphore is not GC'd before spawn
        pa = _spawn((str(root), ART, preimage_json, "wA", crash_at, FOLIO,
                     str(csv_path), 1.0, None, qa, None))
        pa.start()
        pa.join(timeout=60)
        assert pa.exitcode == 17  # it really died at the injection point

        # SSOT advanced only if the crash was AT/after S5 (S5 fires the advance, then checkpoint).
        assert _row_status(csv_path, ART) == ("composed" if crash_at in ("S5", "S6") else "planned")

        # --- Phase B: FOUR concurrent workers re-drive the same id. -------------------
        if crash_at in ("S1", "S2"):
            _sleep_past_lease(claim)  # the dead worker's lease must self-expire (PC7)
        n = 4
        barrier = _SPAWN.Barrier(n)
        qb = _SPAWN.Queue()
        procs = [
            _spawn((str(root), ART, preimage_json, f"wB{i}", None, FOLIO,
                    str(csv_path), 60.0, barrier, qb, None))
            for i in range(n)
        ]
        for p in procs:
            p.start()
        results = [qb.get(timeout=120) for _ in range(n)]
        for p in procs:
            p.join(timeout=60)
        assert all(p.exitcode == 0 for p in procs)
        assert [r for r in results if str(r["code"]).startswith("ERROR")] == []

        # --- EXACTLY-ONCE: one materialization, intact preimage, benign codes only. ---
        record = json.loads(out.read_bytes())
        assert record["preimage"] == PREIMAGE
        assert {r["code"] for r in results} <= {"ok", "already-materialized", "claim-held"}
        if crash_at in ("S0", "S1", "S2"):
            materializers = [r for r in results if r["materialized"]]
            assert len(materializers) == 1  # NO double-write: exactly one winner
            assert record["worker"] == materializers[0]["worker"]
            if crash_at in ("S1", "S2"):
                assert any(r["claim_code"] == "lease-expired-redrive" for r in results)
        else:
            assert record["worker"] == "wA"  # already materialized by the dead worker
            assert all(r["code"] == "already-materialized" for r in results)
            assert all(r["short_circuit"] for r in results)

        # --- NO TORN STATE: the CSV parses, the row is single + at `composed`. ---------
        assert _row_status(csv_path, ART) == "composed"  # the re-drive's S5 advanced it
        assert "composed" in derive_state(csv_path)  # the human projection renders cleanly
        # --- NO LOST UNIT: the completeness sweep finds nothing missing. ---------------
        assert _sweep_one(store, ART).missing == ()
        # --- The folio marker is present and valid (S4 idempotent append). ------------
        assert json.loads(marker.read_bytes())["added_ts"] > 0
        # --- The committed record is the id EXACTLY; any crash-dropped temp is inert. --
        assert (root / "artifacts" / ART).is_file()  # the no-replace commit landed the id


# ---------------------------------------------------------------------------
# (d): the slow-holder steal interleaving under the real SSOT.
# ---------------------------------------------------------------------------


class TestSlowHolderStealUnderSsot:
    def test_steal_during_s2_original_resumes_s3_to_s6_exactly_once(self, tmp_path):
        root = tmp_path / "ws"
        store = WorkspaceStore(root)
        csv_path = root / "ssot.csv"
        Ssot(csv_path).register(ART, "artifact")
        flag = tmp_path / "resume-flag"
        out = store.output_path(ART)
        claim = store.claims_dir / ART
        preimage_json = json.dumps(PREIMAGE)

        # Worker A: short lease; parks mid-S2 until the test says resume.
        qa = _SPAWN.Queue()
        pa = _spawn((str(root), ART, preimage_json, "wA", None, FOLIO,
                     str(csv_path), 0.75, None, qa, str(flag)))
        pa.start()
        deadline = time.time() + 60
        a_holder = None
        while a_holder is None and time.time() < deadline:
            try:
                a_holder = json.loads(claim.read_bytes())["holder"]
            except (FileNotFoundError, ValueError):
                time.sleep(0.01)
        assert a_holder is not None  # A holds the claim and is parked inside S2

        # Worker B: after A's lease expires, steals + works + commits — dies at S5, so its
        # claim is STILL LIVE (holder-mismatch case) when A resumes.
        _sleep_past_lease(claim)
        qb = _SPAWN.Queue()
        pb = _spawn((str(root), ART, preimage_json, "wB", "S5", FOLIO,
                     str(csv_path), 60.0, None, qb, None))
        pb.start()
        pb.join(timeout=60)
        assert pb.exitcode == 17
        assert json.loads(out.read_bytes())["worker"] == "wB"  # the stealer committed
        b_holder = json.loads(claim.read_bytes())["holder"]
        assert b_holder != a_holder  # collision-resistant holders: the steal replaced the record
        assert _row_status(csv_path, ART) == "composed"  # B's S5 advanced before it died

        # Resume A: it drives S3–S6 against the stolen state.
        flag.write_text("resume\n")
        result_a = qa.get(timeout=60)
        pa.join(timeout=60)
        assert pa.exitcode == 0
        assert result_a["claim_code"] == "ok"  # A had acquired normally back at S1
        assert result_a["code"] == "already-materialized"  # (a) A's late commit LOST
        assert result_a["materialized"] is False
        assert result_a["release_code"] == "claim-held"  # (b) A's late release NO-OPED
        # A could neither overwrite B's output nor unlock B's live claim:
        assert json.loads(out.read_bytes())["worker"] == "wB"
        assert json.loads(claim.read_bytes())["holder"] == b_holder
        # EXACTLY-ONCE + coherent SSOT + no lost unit + no stray temp.
        assert _row_status(csv_path, ART) == "composed"
        assert _sweep_one(store, ART).missing == ()
        assert not [n for n in os.listdir(root / "artifacts") if is_temp_name(n)]


# ---------------------------------------------------------------------------
# (c) alone: the CSV single-writer under contention on DISTINCT rows.
# ---------------------------------------------------------------------------


def _advance_own_row(csv_path_str, row_id, barrier, queue) -> None:
    try:
        ssot = Ssot(Path(csv_path_str))
        barrier.wait(timeout=60)
        outcome = ssot.advance(row_id, "composed")  # funnel-serialized single writer
        queue.put({"id": row_id, "code": outcome.code})
    except Exception as exc:  # noqa: BLE001
        queue.put({"id": row_id, "code": f"ERROR:{type(exc).__name__}:{exc}"})


class TestSsotSingleWriterUnderContention:
    def test_concurrent_advances_of_distinct_rows_lose_no_row(self, tmp_path):
        csv_path = tmp_path / "ssot.csv"
        ssot = Ssot(csv_path)
        n = 8
        ids = [f"a-{i:016x}" for i in range(1, n + 1)]
        for rid in ids:  # register all rows first (planning-time)
            ssot.register(rid, "artifact")

        barrier = _SPAWN.Barrier(n)
        q = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(target=_advance_own_row, args=(str(csv_path), rid, barrier, q))
            for rid in ids
        ]
        for p in procs:
            p.start()
        outcomes = [q.get(timeout=120) for _ in ids]
        for p in procs:
            p.join(timeout=60)
        assert all(p.exitcode == 0 for p in procs)
        assert [o for o in outcomes if str(o["code"]).startswith("ERROR")] == []
        assert all(o["code"] == "advanced" for o in outcomes)  # each advance landed

        # NO LOST UPDATE: every row is present and advanced — the funnel serialized all N
        # writers through the ONE CSV without dropping a concurrent write.
        text = csv_path.read_bytes().decode("utf-8")
        rows = {r["id"]: r["status"] for r in csv.DictReader(io.StringIO(text, newline=""))}
        assert set(rows) == set(ids)
        assert all(status == "composed" for status in rows.values())
        assert derive_state(csv_path)  # the table renders — never torn


# ---------------------------------------------------------------------------
# Collision-resistant holders (RV-4, BINDING): only genuine expiry permits a steal.
# ---------------------------------------------------------------------------


class ManualClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestCollisionResistantHolders:
    def test_a_non_holder_can_neither_steal_a_live_claim_nor_release_it(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        clock = ManualClock()
        ttl = 60.0
        # Two workers, distinct MINTED holders (RV-4: distinct even on one pid).
        reg_a = ClaimRegistry(store.claims_dir, holder=mint_holder(), ttl_seconds=ttl, clock=clock)
        reg_b = ClaimRegistry(store.claims_dir, holder=mint_holder(), ttl_seconds=ttl, clock=clock)
        assert reg_a.holder != reg_b.holder

        assert reg_a.acquire(ART).code == "ok"
        # A non-holder RELEASE is a holder-mismatch no-op — B can't unlock A's live claim.
        rel = reg_b.release(ART)
        assert rel.code == "claim-held" and rel.released is False
        assert (store.claims_dir / ART).exists()
        # A non-holder ACQUIRE on a LIVE lease is refused — no steal of a live claim.
        assert reg_b.acquire(ART).code == "claim-held"
        assert json.loads((store.claims_dir / ART).read_bytes())["holder"] == reg_a.holder

        # ONLY genuine EXPIRY permits a redrive (the steal).
        clock.advance(ttl + 1)
        stolen = reg_b.acquire(ART)
        assert stolen.code == "lease-expired-redrive" and stolen.acquired is True
        assert json.loads((store.claims_dir / ART).read_bytes())["holder"] == reg_b.holder
        # A's late release now no-ops (holder mismatch) — it can't unlock B's live claim.
        assert reg_a.release(ART).code == "claim-held"
        assert reg_b.release(ART).code == "ok"
