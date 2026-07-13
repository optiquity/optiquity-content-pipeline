"""Step-36 tests: the §22.2 wave plan + the §22.6 parallel-path code wiring (`pipeline.parallel`).

Covers:
- **build_wave_plan (§22.2/PC1):** two waves — wave 0 compose (keyed by artifact-id), wave 1
  render (keyed by deliverable-id); every unit carries `prereqs` (a render unit's compose
  artifact; a compose unit none) + a `shard` (its root artifact-id); `suggested_width =
  min(unit-count, instance cap)` (§22.5); the plan is an exactly-once cover (PC2 — no dup ids).
- **begin-session(want_parallel_plan=true) (§22.4/PC6):** the wire hands back the wave plan +
  `suggested_width` + the ADVISORY `recommended_width` (never auto-applied) — via NO new verb;
  the returned token is UNCHANGED (an immutable plan-context: workers coordinate via store/
  claims, never by mutating the token), and its `plan_hash` binds the wave plan.
- **the §22.6 code wiring:** `result_for_spine` maps a `SpineResult` to the EXISTING codes —
  `claim-held`/`already-materialized`/`collision-averted`/`lease-expired-redrive`/plain-ok; the
  `rate-limit-backpressure` + `plan-stale` builders. The taxonomy is CLOSED — every code used
  is already a `results.CODE_*` constant.

No `live` marker: begin-session runs against copied real registries with `generate = none`.
"""

from __future__ import annotations

# Reuse the step-33 session harness (real registries copied into tmp_path; read-only suite).
from test_session import base_params, begin, build_root, decode, handlers, store_for

from pipeline import parallel
from pipeline.api import results
from pipeline.claims import AcquireOutcome
from pipeline.plan import DeliverableItem, Plan, PlanItem
from pipeline.spine import SpineResult

ART_A = "a-9f3c07d21b44e8aa"
ART_B = "a-1111222233334444"
DEL_A1 = f"{ART_A}.github.en.md.plain"
DEL_A2 = f"{ART_A}.linkedin.en.md.plain"
DEL_B1 = f"{ART_B}.github.en.md.plain"


def _deliverable(did: str, platform: str) -> DeliverableItem:
    fitted = did.rsplit(".", 2)[0]
    return DeliverableItem(
        deliverable_id=did,
        fitted_id=fitted,
        platform=platform,
        language="en",
        output_type="md",
        presentation="plain",
        reconcile_strategy="verbatim",
    )


def _item(aid: str, deliverables: tuple[DeliverableItem, ...]) -> PlanItem:
    # build_wave_plan reads only `artifact_id` + `deliverables`; the rest is inert filler.
    return PlanItem(
        artifact_id=aid,
        preimage={},
        topic="t",
        persona="p",
        format="f",
        voice="v",
        goals=(),
        m3=None,  # type: ignore[arg-type]
        deliverables=deliverables,
    )


def make_plan(*items: PlanItem, plan_hash: str = "feedfacefeedface") -> Plan:
    return Plan(
        workspace="ws",
        recipe="r",
        source_subset=(),
        source_commit={},
        items=items,
        plan_hash=plan_hash,
        warnings=(),
    )


# ---------------------------------------------------------------------------
# build_wave_plan: two waves, prereqs, shard, suggested_width (§22.2/§22.5).
# ---------------------------------------------------------------------------


class TestWavePlan:
    def test_two_waves_keyed_by_artifact_then_deliverable(self):
        plan = make_plan(
            _item(ART_A, (_deliverable(DEL_A1, "github"), _deliverable(DEL_A2, "linkedin"))),
            _item(ART_B, (_deliverable(DEL_B1, "github"),)),
        )
        wp = parallel.build_wave_plan(plan)
        assert [w.kind for w in wp.waves] == ["compose", "render"]
        assert wp.waves[0].key == "artifact-id"
        assert wp.waves[1].key == "deliverable-id"
        assert [u.id for u in wp.waves[0].units] == [ART_A, ART_B]
        assert {u.id for u in wp.waves[1].units} == {DEL_A1, DEL_A2, DEL_B1}
        assert wp.plan_hash == plan.plan_hash  # binds the immutable plan-context (§22.4)

    def test_compose_units_have_no_prereqs_and_self_shard(self):
        plan = make_plan(_item(ART_A, (_deliverable(DEL_A1, "github"),)))
        wp = parallel.build_wave_plan(plan)
        (unit,) = wp.waves[0].units
        assert unit.prereqs == ()  # v1 has no cross-item edges (§22.1)
        assert unit.shard == ART_A  # its own root artifact-id

    def test_render_units_prereq_their_compose_artifact_and_share_its_shard(self):
        plan = make_plan(
            _item(ART_A, (_deliverable(DEL_A1, "github"), _deliverable(DEL_A2, "linkedin")))
        )
        wp = parallel.build_wave_plan(plan)
        for unit in wp.waves[1].units:
            assert unit.prereqs == (ART_A,)  # the compose artifact must exist first
            assert unit.shard == ART_A  # grouped into the item's row-per-item chain (§22.2)

    def test_suggested_width_is_min_unit_count_and_cap(self):
        # cap defaults to min(MAX_PARALLEL_SESSIONS=3, MAX_PARALLEL_PER_WORKSPACE=2) = 2.
        plan = make_plan(
            _item(ART_A, (_deliverable(DEL_A1, "github"), _deliverable(DEL_A2, "linkedin"))),
            _item(ART_B, (_deliverable(DEL_B1, "github"),)),
        )
        wp = parallel.build_wave_plan(plan)
        assert wp.instance_cap == 2
        assert wp.waves[0].suggested_width == 2  # min(2 compose units, cap 2)
        assert wp.waves[1].suggested_width == 2  # min(3 render units, cap 2)
        assert wp.suggested_width == 2  # widest wave (3) capped at 2

    def test_suggested_width_respects_an_explicit_smaller_cap(self):
        plan = make_plan(
            _item(ART_A, (_deliverable(DEL_A1, "github"),)),
            _item(ART_B, (_deliverable(DEL_B1, "github"),)),
        )
        wp = parallel.build_wave_plan(plan, cap=1)
        assert wp.waves[0].suggested_width == 1
        assert wp.suggested_width == 1

    def test_empty_plan_yields_two_empty_waves_width_zero(self):
        wp = parallel.build_wave_plan(make_plan())
        assert all(w.units == () for w in wp.waves)
        assert wp.suggested_width == 0

    def test_payload_is_json_native_with_prereqs_and_shard(self):
        plan = make_plan(_item(ART_A, (_deliverable(DEL_A1, "github"),)))
        payload = parallel.wave_plan_payload(parallel.build_wave_plan(plan))
        assert payload["plan_hash"] == plan.plan_hash
        assert payload["waves"][1]["units"][0] == {
            "id": DEL_A1,
            "prereqs": [ART_A],
            "shard": ART_A,
        }


# ---------------------------------------------------------------------------
# begin-session(want_parallel_plan=true): §22.4/PC6 — no new verb, token unchanged.
# ---------------------------------------------------------------------------


class TestBeginSessionParallelPlan:
    def test_wave_plan_is_returned_and_token_is_an_immutable_plan_context(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(want_parallel_plan=True), hs=handlers())
        assert out["envelope"]["ok"] is True
        ctx = out["results"][0]["context"]
        assert ctx["parallel_mode"] is True
        wp = ctx["parallel_plan"]
        assert [w["kind"] for w in wp["waves"]] == ["compose", "render"]
        # the wave plan binds the SAME plan_hash the token carries (immutable plan-context).
        token = decode(out["token"])
        assert wp["plan_hash"] == token.plan_hash == ctx["plan_hash"]
        # asking for the parallel plan advanced NOTHING — the token is untouched (§22.4).
        assert token.cursor == {"consumed": []}
        assert token.produced_ids == ()
        # the compose wave covers exactly the plan's artifact ids (PC2 exactly-once cover).
        assert [u["id"] for u in wp["waves"][0]["units"]] == out["results"][0]["ids"][
            "artifact_ids"
        ]

    def test_width_advice_present_and_never_auto_applied(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        ctx = begin(root, store, base_params(want_parallel_plan=True), hs=handlers())[
            "results"
        ][0]["context"]
        assert ctx["suggested_width"] >= 1
        # no telemetry yet ⇒ recommend the full cap, not below it (advice only, §22.5).
        assert ctx["recommended_width"] == ctx["parallel_plan"]["instance_cap"]
        assert ctx["recommended_width_below_cap"] is False

    def test_default_begin_session_omits_the_parallel_block(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        ctx = begin(root, store, base_params(), hs=handlers())["results"][0]["context"]
        assert "parallel_plan" not in ctx  # opt-in only — the default path is unchanged
        assert ctx["generate"] == "none"


# ---------------------------------------------------------------------------
# §22.6 code wiring: SpineResult → the EXISTING closed-taxonomy codes.
# ---------------------------------------------------------------------------


def _acquire(code: str, holder: str | None = "w") -> AcquireOutcome:
    return AcquireOutcome(code=code, acquired=code != "claim-held", holder=holder, lease_expiry=1.0)


def _spine(
    *, code: str, materialized: bool, short_circuit: bool, claim: AcquireOutcome | None
) -> SpineResult:
    return SpineResult(
        id=ART_A,
        code=code,  # type: ignore[arg-type]
        materialized=materialized,
        short_circuit=short_circuit,
        claim=claim,
        folio=(),
        advanced=True,
        advance_error=None,
        release=None,
    )


class TestParallelCodeWiring:
    def test_all_six_parallel_codes_are_pre_existing_constants(self):
        # The taxonomy is CLOSED — this step wires, never adds (§22.6).
        for code in (
            results.CODE_ALREADY_MATERIALIZED,
            results.CODE_CLAIM_HELD,
            results.CODE_LEASE_EXPIRED_REDRIVE,
            results.CODE_PLAN_STALE,
            results.CODE_COLLISION_AVERTED,
            results.CODE_RATE_LIMIT_BACKPRESSURE,
        ):
            assert code in results.PARALLEL_CODES

    def test_plain_win_is_ok_with_no_parallel_code(self):
        item = parallel.result_for_spine(
            _spine(code="ok", materialized=True, short_circuit=False, claim=_acquire("ok"))
        )
        assert item.status == "ok" and item.code is None

    def test_short_circuit_maps_to_already_materialized(self):
        item = parallel.result_for_spine(
            _spine(code="already-materialized", materialized=False, short_circuit=True, claim=None)
        )
        assert item.code == results.CODE_ALREADY_MATERIALIZED and item.status == "ok"

    def test_lost_no_replace_commit_maps_to_collision_averted(self):
        item = parallel.result_for_spine(
            _spine(
                code="already-materialized",
                materialized=False,
                short_circuit=False,
                claim=_acquire("ok"),
            )
        )
        assert item.code == results.CODE_COLLISION_AVERTED and item.status == "warn"

    def test_stolen_lease_win_maps_to_lease_expired_redrive(self):
        item = parallel.result_for_spine(
            _spine(
                code="ok",
                materialized=True,
                short_circuit=False,
                claim=_acquire("lease-expired-redrive"),
            )
        )
        assert item.code == results.CODE_LEASE_EXPIRED_REDRIVE and item.status == "ok"

    def test_claim_held_maps_to_claim_held(self):
        item = parallel.result_for_spine(
            _spine(
                code="claim-held",
                materialized=False,
                short_circuit=False,
                claim=_acquire("claim-held", holder="incumbent"),
            )
        )
        assert item.code == results.CODE_CLAIM_HELD and item.status == "warn"
        assert item.context == {"holder": "incumbent"}

    def test_backpressure_builder_carries_retry_after_and_reduce_width_hint(self):
        item = parallel.backpressure_result(item=ART_A, observed_inflight=3, retry_after=12.0)
        assert item.code == results.CODE_RATE_LIMIT_BACKPRESSURE and item.status == "warn"
        assert item.context["observed_inflight"] == 3
        assert item.context["retry_after"] == 12.0
        assert item.remediation["action"] == results.ACTION_RETRY_AFTER

    def test_backpressure_can_be_a_block_when_the_unit_cannot_proceed(self):
        item = parallel.backpressure_result(item=ART_A, observed_inflight=9, status="block")
        assert item.status == "block" and item.code == results.CODE_RATE_LIMIT_BACKPRESSURE

    def test_plan_stale_builder_names_both_hashes(self):
        item = parallel.plan_stale_result(
            item="plan", plan_hash_token="aaaa", plan_hash_current="bbbb"
        )
        assert item.code == results.CODE_PLAN_STALE and item.status == "warn"
        assert item.context == {"plan_hash_token": "aaaa", "plan_hash_current": "bbbb"}
