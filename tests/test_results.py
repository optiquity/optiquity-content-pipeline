"""Step-32 tests: the typed result contract + the CONSOLIDATED §21.7/§22.6 code taxonomy.

The load-bearing test here is the LITERAL code-list (§21.7 + §22.6): `ALL_CODES` must equal
exactly the design's enumeration — every code present, no extras, no omissions. The 34
strings below are transcribed straight from `docs/design.md` §21.7 (generation + contract
tiers), §22.6 (parallel-path tier), the DR-6 §6.5/§19 `grounding-uncovered` abstain, the
DR-4 §15/§16 `section-conformance-violation` typed-section gate, the DR-5 C4 §15/§16
`citation-unresolved` `[@key]`→projected-`references` compose gate, the DR-7 A §15/§16/§10
rule-2 asset-containment gate (`asset-ref-uncontained`, `asset-ref-invalid`,
`body-raw-markup-forbidden`), and the DR-9 §21.7 outline continuation-handle codes
(`outline-config-drift`, `outline-config-unverified`); a
drift check then proves the consolidation is
faithful to the codes the producing modules already emit (`reconcile`, `drift`, `grounding`,
`fit_resolution`, `serialize`, `migration`, `folios`, `overrides`, `dispatch`, `transport`).

Everything is obviously generic — the taxonomy is framework vocabulary, no instance content.
"""

from __future__ import annotations

import pytest

from pipeline.api import results
from pipeline.api.results import CodeSpec, Envelope, ResultContractError, ResultItem, make_result

# --- The design's §21.7 + §22.6 enumeration, transcribed literally --------------------------

# §21.7 generation tier.
GENERATION = {
    "hard-limit-exceeded",
    "advisory-constraint-overridden",
    "nonsensical-pairing",
    "drift-block",
    "out-of-window",
    "empty-pool",
    "low-confidence-grounding",
    "capability-infeasible",
    "render-input-mismatch",
    "re-reconciled",
    "re-serialized",
    "member-updated",
    "ambiguous-migration-decisions",
    "grounding-uncovered",
    "section-conformance-violation",
    "citation-unresolved",
    "asset-ref-uncontained",
    "asset-ref-invalid",
    "body-raw-markup-forbidden",
    "outline-config-drift",
    "outline-config-unverified",
}
# §21.7 contract tier.
CONTRACT = {
    "unknown-verb",
    "unknown-action",
    "invalid-override",
    "isolation-violation",
    "invalid-token",
    "not-found",
    "unresolved-member",
}
# §22.6 parallel-path tier (`already-materialized` REUSED, not new — counted once, here).
PARALLEL = {
    "already-materialized",
    "claim-held",
    "lease-expired-redrive",
    "plan-stale",
    "collision-averted",
    "rate-limit-backpressure",
}
EXPECTED_CODES = GENERATION | CONTRACT | PARALLEL

# Codes the design deliberately does NOT define (must be absent — see §20/§21.3/§21.8/FR7.3).
FORBIDDEN_CODES = {"stale-token", "superseded-fit", "non-current-fit", "serialize-input-mismatch"}


class TestCodeTaxonomy:
    def test_all_codes_equals_the_design_enumeration(self):
        # The literal-list pin (§21.7 + §22.6): exact set equality — no extras, no omissions.
        assert results.ALL_CODES == EXPECTED_CODES
        assert set(results.CODES) == EXPECTED_CODES
        assert len(results.ALL_CODES) == 34

    def test_forbidden_codes_are_absent(self):
        assert results.ALL_CODES.isdisjoint(FORBIDDEN_CODES)

    def test_tiers_partition_the_taxonomy(self):
        assert results.GENERATION_CODES == GENERATION
        assert results.CONTRACT_CODES == CONTRACT
        assert results.PARALLEL_CODES == PARALLEL
        # A clean partition: union = whole, pairwise disjoint.
        assert results.GENERATION_CODES | results.CONTRACT_CODES | results.PARALLEL_CODES == (
            results.ALL_CODES
        )
        assert not (results.GENERATION_CODES & results.CONTRACT_CODES)
        assert not (results.GENERATION_CODES & results.PARALLEL_CODES)
        assert not (results.CONTRACT_CODES & results.PARALLEL_CODES)

    def test_every_spec_is_well_formed(self):
        for code, spec in results.CODES.items():
            assert isinstance(spec, CodeSpec)
            assert spec.code == code
            assert spec.tier in results.TIERS
            assert spec.statuses  # at least one status
            assert set(spec.statuses) <= set(results.STATUSES)
            assert spec.section.startswith("§")
            assert spec.summary
            assert spec.remediation_action is None or (
                spec.remediation_action in results.REMEDIATION_ACTIONS
            )

    def test_canonical_statuses_match_the_design(self):
        # Spot-check the design's status rulings for representative codes.
        assert results.CODES["hard-limit-exceeded"].statuses == ("block",)
        # DR-5 C4: the citation compose gate blocks (never persisted), GENERATION-tier.
        assert results.CODES["citation-unresolved"].statuses == ("block",)
        assert results.CODES["citation-unresolved"].tier == results.TIER_GENERATION
        assert results.CODES["re-reconciled"].statuses == ("ok",)
        assert results.CODES["re-serialized"].statuses == ("ok",)
        assert results.CODES["member-updated"].statuses == ("warn",)
        assert results.CODES["ambiguous-migration-decisions"].statuses == ("needs-input",)
        assert results.CODES["unresolved-member"].statuses == ("needs-input",)
        # The two dual-status codes (§17, §22.5): warn|block.
        assert results.CODES["capability-infeasible"].statuses == ("warn", "block")
        assert results.CODES["rate-limit-backpressure"].statuses == ("warn", "block")
        # DR-3 / C7: outline-config-drift is one condition with two dispositions — a deterministic
        # pre-spend BLOCK by default, an accepted WARN under --allow-drift. `block` is status[0]
        # (the unchanged default refusal path); it stays a deterministic block so the async
        # terminal-code contract (B-1) is untouched. unverified stays warn-only (no-handle case).
        assert results.CODES["outline-config-drift"].statuses == ("block", "warn")
        assert results.CODES["outline-config-unverified"].statuses == ("warn",)

    def test_design_fixed_remediation_actions(self):
        # Where the design fixes the machine action, the spec carries it (§21.8/§21.7/§22.5).
        assert results.CODES["render-input-mismatch"].remediation_action == "force-re-reconcile"
        assert results.CODES["empty-pool"].remediation_action == "relax-clause"
        assert results.CODES["out-of-window"].remediation_action == "run-migrate"
        assert results.CODES["drift-block"].remediation_action == "run-migrate"
        assert results.CODES["ambiguous-migration-decisions"].remediation_action == "run-migrate"
        assert results.CODES["rate-limit-backpressure"].remediation_action == "retry-after"

    def test_consolidation_is_faithful_no_omissions(self):
        # Every code the producing modules already emit is a MEMBER of the consolidated set —
        # proving the taxonomy omits nothing that actually reaches the wire.
        from pipeline.dispatch import CapabilityInfeasibleError
        from pipeline.drift import CODE_DRIFT_BLOCK, CODE_OUT_OF_WINDOW
        from pipeline.fit_resolution import (
            CODE_ALREADY_MATERIALIZED as FIT_AM,
        )
        from pipeline.fit_resolution import (
            CODE_RE_RECONCILED,
            CODE_RENDER_INPUT_MISMATCH,
        )
        from pipeline.folios import CrossWorkspaceMemberError, FolioNotFoundError
        from pipeline.grounding import CODE_EMPTY_POOL, CODE_LOW_CONFIDENCE_GROUNDING
        from pipeline.migration import CODE_AMBIGUOUS_MIGRATION_DECISIONS
        from pipeline.overrides import OverrideError
        from pipeline.reconcile import CODE_HARD_LIMIT_EXCEEDED
        from pipeline.serialize import (
            CODE_ALREADY_MATERIALIZED as SER_AM,
        )
        from pipeline.serialize import (
            CODE_RE_SERIALIZED,
        )

        emitted = {
            CODE_HARD_LIMIT_EXCEEDED,
            CODE_DRIFT_BLOCK,
            CODE_OUT_OF_WINDOW,
            CODE_EMPTY_POOL,
            CODE_LOW_CONFIDENCE_GROUNDING,
            CODE_RENDER_INPUT_MISMATCH,
            CODE_RE_RECONCILED,
            FIT_AM,
            SER_AM,
            CODE_RE_SERIALIZED,
            CODE_AMBIGUOUS_MIGRATION_DECISIONS,
            CapabilityInfeasibleError.code,
            OverrideError.code,
            CrossWorkspaceMemberError.code,
            FolioNotFoundError.code,
            # literal-string emitters (no module constant): claims, transport, plan.
            "claim-held",
            "lease-expired-redrive",
            "rate-limit-backpressure",
            "nonsensical-pairing",
            "member-updated",
        }
        missing = emitted - results.ALL_CODES
        assert not missing, f"consolidated taxonomy OMITS emitted codes: {sorted(missing)}"


class TestResultItem:
    def test_wire_shape_of_a_taxonomy_result(self):
        item = make_result(
            results.CODE_EMPTY_POOL,
            item="topic=x/persona=y",
            context={"clause": "require topic=x"},
        )
        assert item.status == "block"
        assert item.category == results.TIER_GENERATION
        wire = item.as_dict()
        assert wire["status"] == "block"
        assert wire["code"] == "empty-pool"
        assert wire["category"] == "generation"
        assert wire["remediation"]["action"] == "relax-clause"
        assert wire["context"]["clause"] == "require topic=x"

    def test_category_auto_derives_from_code(self):
        item = ResultItem(item="x", status="warn", code=results.CODE_PLAN_STALE)
        assert item.category == results.TIER_PARALLEL

    def test_ok_result_without_a_code_omits_code_and_remediation(self):
        item = ResultItem(item="a-9f3c07d21b44e8aa", status="ok", ids={"artifact": "a-9f3c"})
        wire = item.as_dict()
        assert wire == {"item": "a-9f3c07d21b44e8aa", "status": "ok", "ids": {"artifact": "a-9f3c"}}
        assert "code" not in wire and "remediation" not in wire

    def test_unknown_code_is_refused(self):
        with pytest.raises(ResultContractError):
            ResultItem(item="x", status="block", code="not-a-real-code")

    def test_status_inconsistent_with_code_is_refused(self):
        # hard-limit-exceeded is block-only (§16) — an `ok` instance is a contract violation.
        with pytest.raises(ResultContractError):
            ResultItem(item="x", status="ok", code=results.CODE_HARD_LIMIT_EXCEEDED)

    def test_category_inconsistent_with_code_is_refused(self):
        with pytest.raises(ResultContractError):
            ResultItem(
                item="x", status="block", code=results.CODE_EMPTY_POOL, category="contract"
            )

    def test_dual_status_code_accepts_both(self):
        assert ResultItem(item="x", status="warn", code=results.CODE_CAPABILITY_INFEASIBLE)
        assert ResultItem(item="x", status="block", code=results.CODE_CAPABILITY_INFEASIBLE)

    def test_bad_status_is_refused(self):
        with pytest.raises(ResultContractError):
            ResultItem(item="x", status="fatal")

    def test_remediation_extra_key_is_refused(self):
        with pytest.raises(ResultContractError):
            ResultItem(item="x", status="warn", remediation={"hint": "h", "foo": "bar"})

    def test_make_result_status_override(self):
        # capability-infeasible defaults to its first status (warn); block is selectable.
        assert make_result(results.CODE_CAPABILITY_INFEASIBLE, item="x").status == "warn"
        blocked = make_result(results.CODE_CAPABILITY_INFEASIBLE, item="x", status="block")
        assert blocked.status == "block"

    def test_make_result_render_input_mismatch_carries_machine_action(self):
        item = make_result(
            results.CODE_RENDER_INPUT_MISMATCH,
            item="a-9f3c07d21b44e8aa.linkedin.en",
            context={"current_inputs_digest": "abc123"},
        )
        assert item.status == "warn"
        assert item.remediation == {"action": "force-re-reconcile"}


class TestEnvelope:
    def test_ok_envelope_wire_shape(self):
        env = Envelope(ok=True, verb="render", workspace="wsA")
        assert env.as_dict() == {"ok": True, "verb": "render", "workspace": "wsA"}

    def test_fatal_envelope_carries_code_and_message(self):
        env = Envelope(
            ok=False, verb="frob", workspace="wsA", code="unknown-verb", message="verb 'frob'..."
        )
        wire = env.as_dict()
        assert wire["ok"] is False
        assert wire["code"] == "unknown-verb"
        assert wire["message"].startswith("verb")
