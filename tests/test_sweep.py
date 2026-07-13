"""Step-36 tests: the §22.3/PC5 completeness sweep + wave barrier (`pipeline.parallel.sweep`).

The sweep is the anti-silent-gap guarantee: it re-resolves the plan and diffs against
MATERIALIZED ids (OUTPUT EXISTENCE, store-only — §22.7), with the caller's own `blocked` set,
and the WAVE BARRIER holds iff `materialized ∪ blocked = expected`. A unit that is neither
materialized nor blocked lands in `missing` and is SURFACED — never silently 'done'.

Proven here:
- expected/materialized/blocked/missing computed from the STORE (`is_done`), never the SSOT;
- a DELIBERATELY-MISSED unit (materialized everything but one, no blocked) is DETECTED;
- `blocked ≠ missing` (a caller-blocked §6.4 item is visible, not lost);
- the per-wave barrier + the whole-plan barrier;
- **SSOT-INDEPENDENCE:** an id marked done in the SSOT but ABSENT from the store still counts
  MISSING — the sweep ignores the SSOT entirely (§22.7).
"""

from __future__ import annotations

from pipeline import parallel
from pipeline.plan import DeliverableItem, Plan, PlanItem
from pipeline.ssot import Ssot
from pipeline.store import WorkspaceStore, write_new

ART_A = "a-9f3c07d21b44e8aa"
ART_B = "a-1111222233334444"
DEL_A1 = f"{ART_A}.github.en.md.plain"
DEL_B1 = f"{ART_B}.github.en.md.plain"


def _deliverable(did: str) -> DeliverableItem:
    return DeliverableItem(
        deliverable_id=did,
        fitted_id=did.rsplit(".", 2)[0],
        platform="github",
        language="en",
        output_type="md",
        presentation="plain",
        reconcile_strategy="verbatim",
    )


def _item(aid: str, dids: tuple[str, ...]) -> PlanItem:
    return PlanItem(
        artifact_id=aid,
        preimage={},
        topic="t",
        persona="p",
        format="f",
        voice="v",
        goals=(),
        m3=None,  # type: ignore[arg-type]
        deliverables=tuple(_deliverable(d) for d in dids),
    )


def _plan() -> Plan:
    return Plan(
        workspace="ws",
        recipe="r",
        source_subset=(),
        source_commit={},
        items=(_item(ART_A, (DEL_A1,)), _item(ART_B, (DEL_B1,))),
        plan_hash="feedfacefeedface",
        warnings=(),
    )


def _wave_plan():
    return parallel.build_wave_plan(_plan())


def _store(tmp_path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "ws")


def _materialize(store: WorkspaceStore, *ids: str) -> None:
    for i in ids:
        write_new(store.output_path(i), b"{}\n")  # output existence = the idempotency authority


# ---------------------------------------------------------------------------
# The sweep over the store (§22.3) — expected/materialized/blocked/missing.
# ---------------------------------------------------------------------------


class TestSweep:
    def test_nothing_materialized_is_all_missing_and_incomplete(self, tmp_path):
        result = parallel.sweep(_wave_plan(), _store(tmp_path))
        assert set(result.missing) == {ART_A, ART_B, DEL_A1, DEL_B1}
        assert result.materialized == ()
        assert result.complete is False

    def test_everything_materialized_is_complete_no_missing(self, tmp_path):
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B, DEL_A1, DEL_B1)
        result = parallel.sweep(_wave_plan(), store)
        assert set(result.materialized) == {ART_A, ART_B, DEL_A1, DEL_B1}
        assert result.missing == ()
        assert result.complete is True
        assert all(w.complete for w in result.waves)

    def test_a_deliberately_missed_unit_is_detected_never_silently_done(self, tmp_path):
        # Materialize EVERYTHING except DEL_B1, and declare NOTHING blocked: the missed unit
        # is neither materialized nor blocked, so the barrier must SURFACE it (the anti-silent-
        # gap guarantee, §22.3/PC5) — never report the wave 'done'.
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B, DEL_A1)
        result = parallel.sweep(_wave_plan(), store)
        assert result.missing == (DEL_B1,)
        assert result.complete is False
        render_wave = result.waves[1]
        assert render_wave.missing == (DEL_B1,)
        assert render_wave.complete is False

    def test_blocked_is_not_missing_and_satisfies_the_barrier(self, tmp_path):
        # Blocked ≠ missing (§6.4 items are visible, not lost): materialize all but DEL_B1 and
        # declare DEL_B1 blocked → materialized ∪ blocked = expected → the barrier is complete.
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B, DEL_A1)
        result = parallel.sweep(_wave_plan(), store, blocked={DEL_B1})
        assert result.blocked == (DEL_B1,)
        assert result.missing == ()
        assert result.complete is True

    def test_materialized_beats_a_stale_blocked_claim(self, tmp_path):
        # If an id is BOTH materialized and named in `blocked`, materialization wins — a
        # re-drive cleared the block; it is never double-counted or reported missing.
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B, DEL_A1, DEL_B1)
        result = parallel.sweep(_wave_plan(), store, blocked={DEL_B1})
        assert DEL_B1 in result.materialized
        assert result.blocked == ()
        assert result.complete is True

    def test_wave_barrier_is_per_wave(self, tmp_path):
        # Wave 0 (compose) complete, wave 1 (render) not: the barriers are independent.
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B)
        result = parallel.sweep(_wave_plan(), store)
        compose, render = result.waves
        assert compose.kind == "compose" and compose.complete is True
        assert render.kind == "render" and render.complete is False
        assert set(render.missing) == {DEL_A1, DEL_B1}
        assert result.complete is False

    def test_empty_blocked_default_is_frozenset_safe(self, tmp_path):
        # The default blocked set is empty and never mutated across calls (a fresh frozenset).
        store = _store(tmp_path)
        first = parallel.sweep(_wave_plan(), store)
        second = parallel.sweep(_wave_plan(), store)
        assert first.missing == second.missing


# ---------------------------------------------------------------------------
# SSOT-INDEPENDENCE (§22.7): the sweep reads the store, never the SSOT.
# ---------------------------------------------------------------------------


class TestSweepIgnoresTheSsot:
    def test_ssot_says_done_but_store_is_empty_still_counts_missing(self, tmp_path):
        # Advance the SSOT rows to 'composed'/'fitted' WITHOUT materializing the outputs. The
        # sweep must ignore the SSOT and report the units MISSING — correctness rides output
        # existence, never the bookkeeping projection (§22.7 INV-CORRECTNESS).
        store = _store(tmp_path)
        ssot = Ssot(store.root / "ssot.csv")
        ssot.register(ART_A, "artifact")
        ssot.advance(ART_A, "composed")
        ssot.register(DEL_A1, "deliverable")
        ssot.advance(DEL_A1, "fitted")
        result = parallel.sweep(_wave_plan(), store)
        assert ART_A in result.missing  # SSOT 'composed' is irrelevant to the sweep
        assert DEL_A1 in result.missing
        assert result.complete is False

    def test_store_materialized_but_ssot_untouched_still_complete(self, tmp_path):
        # The mirror image: the store is authoritative — a materialized id is DONE to the sweep
        # even with no SSOT row at all.
        store = _store(tmp_path)
        _materialize(store, ART_A, ART_B, DEL_A1, DEL_B1)
        assert not (store.root / "ssot.csv").exists()  # no SSOT written
        result = parallel.sweep(_wave_plan(), store)
        assert result.complete is True
