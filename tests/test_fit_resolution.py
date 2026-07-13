"""Step-26 tests: `pipeline/fit_resolution.py` — the FR2 rule, the force matrix, split parts,
and claims. PURE resolution over step-25 fit-bindings; the reconcile LLM path is NEVER invoked
(these tests build fit-bindings via `reconcile.build_fit_binding` — no transport, no `claude`).

Covers, per the acceptance list:

- **the FR2 three-row matrix** (§21.8): digest match → hit; fits exist, none match →
  latest-minted + `render-input-mismatch` warn; no fit → first baseline mint;
- **config revert self-heals** (rule-1 branch): reverting inputs re-selects the matching
  existing fit as a HIT — no warn, no re-mint;
- **the `force_reconcile` matrix**: no-fit → baseline; match → `already-materialized`;
  none-match → revision `_hex12`, `re-reconciled`;
- **two forcers with the same inputs → ONE claim key** (§22.3): the content-addressed fitted-id
  makes both compute the same key → exactly one winner (B4-4);
- **split ordinals are SAVE-STABLE across re-saves** (§9.5/§16);
- **latest-minted is deterministic without a wall-clock tiebreak hole** (§21.8);
- the two step-25 carry-forwards owned here: obs-3 (consumed-scoping stops fit-revision churn)
  and obs-1 (a non-numeric hard limit fails fast before the LLM path);
- **no SSOT import** (INV-CORRECTNESS, §22.7).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pipeline import ir, reconcile
from pipeline.claims import ClaimRegistry
from pipeline.fit_resolution import (
    CODE_ALREADY_MATERIALIZED,
    CODE_RE_RECONCILED,
    CODE_RENDER_INPUT_MISMATCH,
    DISPOSITION_FORCED_BASELINE,
    DISPOSITION_FORCED_MATCH,
    DISPOSITION_FORCED_REVISION,
    DISPOSITION_HIT,
    DISPOSITION_MISMATCH,
    DISPOSITION_MISS,
    REMEDIATION_FORCE_RE_RECONCILE,
    FitCoordinate,
    FitResolutionError,
    claim_fit,
    parse_fit_binding,
    resolve_fit,
    resolve_force_reconcile,
    resolved_fitted_id,
    scope_consumed,
    scope_request,
    split_part_addresses,
)
from pipeline.ids import (
    EntryBinding,
    build_artifact_preimage,
    fitted_id,
    mint_artifact_id,
    part_id,
)
from pipeline.reconcile import ReconcileRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT_SHA = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"

PLATFORM = "linkedin"
LANGUAGE = "en"


# --- fixtures + builders -------------------------------------------------------------------


def make_preimage() -> dict:
    return build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("readme"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
    )


def ledger_entry(*, tier: str = "EXTRACTED") -> dict:
    return {
        "tier": tier,
        "source_instance_id": "acme-graph",
        "source_repo": "github.com/acme/widget",
        "source_commit": COMMIT_SHA,
        "traceability_anchor": ["file-line:src/parser.py:42"],
        "scores_snapshot": {"trusted": 5, "review_status": "merged"},
    }


def make_canonical_ir(*, body=None, parts=None) -> dict:
    """A valid §15 IR-canonical envelope (via ir.build_ir) — the fit input."""
    preimage = make_preimage()
    artifact_id = mint_artifact_id(preimage)
    if body is None and parts is None:
        body = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
    return ir.build_ir(
        artifact_id=artifact_id,
        preimage=preimage,
        grounding={"f0": ledger_entry()},
        body=body,
        parts=parts,
    )


def make_request(*, canonical_ir=None, strategy="adapt", **overrides) -> ReconcileRequest:
    ci = canonical_ir if canonical_ir is not None else make_canonical_ir()
    base = {
        "canonical_ir": ci,
        "artifact_id": ci["binding"]["artifact_id"],
        "platform": PLATFORM,
        "language": LANGUAGE,
        "source_language": LANGUAGE,
        "strategy": strategy,
        "hard_limits": {},
        "voice_content_params": {"tone": "business"},
    }
    base.update(overrides)
    return ReconcileRequest(**base)


def preimage_of(request: ReconcileRequest) -> dict:
    return reconcile.reconcile_inputs_preimage(request)


def binding_for(request: ReconcileRequest, *, revision: bool = False, minted_ts: str) -> dict:
    """A step-25 fit-binding for `request` — the REAL `build_fit_binding` machinery, no LLM."""
    return reconcile.build_fit_binding(
        artifact_id=request.artifact_id,
        platform=request.platform,
        language=request.language,
        preimage=preimage_of(request),
        strategy=request.strategy,
        localize_languages=[],
        gate_outcome="fit",
        minted_ts=minted_ts,
        revision=revision,
    )


def coordinate_for(request: ReconcileRequest) -> FitCoordinate:
    return FitCoordinate(request.artifact_id, request.platform, request.language)


# ---------------------------------------------------------------------------
# The FR2 fit-resolution rule (§21.8) — the three-row matrix.
# ---------------------------------------------------------------------------


class TestResolveFitMatrix:
    def test_row1_digest_match_is_a_hit(self):
        request = make_request(strategy="adapt")
        baseline = binding_for(request, minted_ts="2026-01-01T00:00:00+00:00")
        # current effective inputs equal the baseline's inputs → a true cache hit.
        out = resolve_fit(coordinate_for(request), [baseline], preimage_of(request))
        assert out.disposition == DISPOSITION_HIT
        assert out.status == "ok" and out.code == "ok"
        assert out.should_mint is False and out.warning is None
        assert out.selected is not None and out.selected.fitted_id == baseline["fitted_id"]

    def test_row3_no_fit_is_a_first_baseline_mint(self):
        request = make_request()
        out = resolve_fit(coordinate_for(request), [], preimage_of(request))
        assert out.disposition == DISPOSITION_MISS
        assert out.status == "ok" and out.code == "ok"
        assert out.should_mint is True and out.revision is False
        assert out.selected is None
        # The minted id is the UNQUALIFIED baseline fitted-id.
        assert resolved_fitted_id(out, coordinate_for(request)) == fitted_id(
            request.artifact_id, PLATFORM, LANGUAGE
        )

    def test_row2_none_match_serves_latest_minted_with_warn(self):
        base_req = make_request(strategy="adapt")  # digest D0
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        # Current inputs deviate (strategy split → digest D1 ≠ D0): fits exist, none match.
        current_req = make_request(strategy="split")
        out = resolve_fit(coordinate_for(base_req), [baseline], preimage_of(current_req))
        assert out.disposition == DISPOSITION_MISMATCH
        assert out.status == "warn" and out.code == CODE_RENDER_INPUT_MISMATCH
        assert out.should_mint is False  # the stale bytes are served UNCHANGED, never re-minted
        assert out.selected.fitted_id == baseline["fitted_id"]  # the latest-minted fit
        warn = out.warning
        assert warn is not None
        assert warn.code == CODE_RENDER_INPUT_MISMATCH
        assert warn.served_fitted_id == baseline["fitted_id"]
        assert warn.current_inputs_digest == out.current_inputs_digest
        assert warn.served_inputs_digest == baseline["digest"]
        assert "strategy" in warn.differing_components
        assert warn.remediation_action == REMEDIATION_FORCE_RE_RECONCILE


class TestConfigRevertSelfHeals:
    def test_revert_reselects_the_matching_existing_fit_no_remint(self):
        base_req = make_request(strategy="adapt")  # baseline digest D0
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        rev_req = make_request(strategy="split")  # revision digest D1
        revision = binding_for(rev_req, revision=True, minted_ts="2026-02-01T00:00:00+00:00")
        records = [baseline, revision]

        # While config sits at D1 the revision is a hit; while it sits at D0 the baseline is.
        out_d1 = resolve_fit(coordinate_for(base_req), records, preimage_of(rev_req))
        assert out_d1.disposition == DISPOSITION_HIT
        assert out_d1.selected.fitted_id == revision["fitted_id"]

        # REVERT the config back to D0 → the baseline matches again → HIT, no warn, no re-mint.
        out_reverted = resolve_fit(coordinate_for(base_req), records, preimage_of(base_req))
        assert out_reverted.disposition == DISPOSITION_HIT
        assert out_reverted.should_mint is False and out_reverted.warning is None
        assert out_reverted.selected.fitted_id == baseline["fitted_id"]


class TestLatestMintedDeterminism:
    def test_latest_minted_by_minted_ts(self):
        base_req = make_request(strategy="adapt")
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        rev_req = make_request(strategy="split")
        revision = binding_for(rev_req, revision=True, minted_ts="2026-06-01T00:00:00+00:00")
        # Current inputs match NEITHER (truncate → D2); latest by minted_ts is the revision.
        current = make_request(strategy="truncate")
        out = resolve_fit(coordinate_for(base_req), [baseline, revision], preimage_of(current))
        assert out.disposition == DISPOSITION_MISMATCH
        assert out.selected.fitted_id == revision["fitted_id"]

    def test_equal_minted_ts_falls_back_to_deterministic_id_tiebreak(self):
        # The wall-clock hole: two fits minted in the SAME instant must resolve to ONE fit.
        base_req = make_request(strategy="adapt")
        same_ts = "2026-03-03T03:03:03+00:00"
        baseline = binding_for(base_req, minted_ts=same_ts)  # id `…en`
        rev_req = make_request(strategy="split")
        revision = binding_for(rev_req, revision=True, minted_ts=same_ts)  # id `…en_<hex12>`
        current = make_request(strategy="truncate")  # matches neither
        coord = coordinate_for(base_req)
        # `…en` < `…en_<hex12>`, so the deterministic MAX tiebreak selects the revision — and
        # the pick is invariant to record order (no insertion-order luck).
        expected = revision["fitted_id"]
        out_a = resolve_fit(coord, [baseline, revision], preimage_of(current))
        out_b = resolve_fit(coord, [revision, baseline], preimage_of(current))
        assert out_a.selected.fitted_id == expected
        assert out_b.selected.fitted_id == expected


# ---------------------------------------------------------------------------
# The force_reconcile behavior matrix (§21.8).
# ---------------------------------------------------------------------------


class TestForceReconcileMatrix:
    def test_no_fit_forces_a_baseline_mint(self):
        request = make_request()
        out = resolve_force_reconcile(coordinate_for(request), [], preimage_of(request))
        assert out.disposition == DISPOSITION_FORCED_BASELINE
        assert out.status == "ok" and out.code == "ok"
        assert out.should_mint is True and out.revision is False
        assert resolved_fitted_id(out, coordinate_for(request)) == fitted_id(
            request.artifact_id, PLATFORM, LANGUAGE
        )

    def test_match_is_already_materialized_no_mint(self):
        request = make_request(strategy="adapt")
        baseline = binding_for(request, minted_ts="2026-01-01T00:00:00+00:00")
        out = resolve_force_reconcile(coordinate_for(request), [baseline], preimage_of(request))
        assert out.disposition == DISPOSITION_FORCED_MATCH
        assert out.status == "ok" and out.code == CODE_ALREADY_MATERIALIZED
        assert out.should_mint is False
        assert out.selected.fitted_id == baseline["fitted_id"]

    def test_force_matches_an_existing_revision_too(self):
        base_req = make_request(strategy="adapt")
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        rev_req = make_request(strategy="split")
        revision = binding_for(rev_req, revision=True, minted_ts="2026-02-01T00:00:00+00:00")
        # Forcing while config == the revision's inputs matches the REVISION (no mint).
        out = resolve_force_reconcile(
            coordinate_for(base_req), [baseline, revision], preimage_of(rev_req)
        )
        assert out.disposition == DISPOSITION_FORCED_MATCH
        assert out.selected.fitted_id == revision["fitted_id"]

    def test_none_match_mints_a_revision(self):
        base_req = make_request(strategy="adapt")
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        current = make_request(strategy="split")
        coord = coordinate_for(base_req)
        out = resolve_force_reconcile(coord, [baseline], preimage_of(current))
        assert out.disposition == DISPOSITION_FORCED_REVISION
        assert out.status == "ok" and out.code == CODE_RE_RECONCILED
        assert out.should_mint is True and out.revision is True
        # The revision fitted-id carries the current-inputs _hex12 (§7.4).
        assert resolved_fitted_id(out, coord) == fitted_id(
            base_req.artifact_id, PLATFORM, LANGUAGE, fit_revision=out.current_inputs_digest
        )


# ---------------------------------------------------------------------------
# Claims on the fitted-id (§22.3): two forcers, same inputs → ONE claim key, one winner.
# ---------------------------------------------------------------------------


class TestClaimsOnFittedId:
    def test_two_forcers_same_inputs_one_claim_key_one_winner(self, tmp_path):
        base_req = make_request(strategy="adapt")
        baseline = binding_for(base_req, minted_ts="2026-01-01T00:00:00+00:00")
        current = make_request(strategy="split")  # none-match → both would mint the revision
        coord = coordinate_for(base_req)
        records = [baseline]

        # Two independent forcers resolve identically (deterministic, content-addressed).
        res_w1 = resolve_force_reconcile(coord, records, preimage_of(current))
        res_w2 = resolve_force_reconcile(coord, records, preimage_of(current))
        key_w1 = resolved_fitted_id(res_w1, coord)
        key_w2 = resolved_fitted_id(res_w2, coord)
        assert key_w1 == key_w2  # SAME claim key by construction (§22.3)

        # Both acquire the SAME key against one registry dir → exactly one winner (B4-4).
        claims_dir = tmp_path / "ws" / "claims"
        reg_w1 = ClaimRegistry(claims_dir, holder="w1")
        reg_w2 = ClaimRegistry(claims_dir, holder="w2")
        out_w1 = claim_fit(reg_w1, res_w1, coord)
        out_w2 = claim_fit(reg_w2, res_w2, coord)
        winners = [o for o in (out_w1, out_w2) if o.acquired]
        assert len(winners) == 1  # exactly one LLM run; the loser is held
        loser = out_w2 if out_w1.acquired else out_w1
        assert loser.code == "claim-held" and loser.acquired is False


# ---------------------------------------------------------------------------
# Split parts (§16/§9.5): (deliverable-id, part-id) with SAVE-STABLE ordinals.
# ---------------------------------------------------------------------------


def make_parts_ir() -> dict:
    """A valid multi-part IR-canonical envelope — three parts, stable order."""
    preimage = make_preimage()
    artifact_id = mint_artifact_id(preimage)
    parts = [
        {
            "part-id": part_id(artifact_id, role),
            "role": role,
            "packaging_hint": "standalone",
            "body": f"Body for {role}.",
        }
        for role in ("intro", "middle", "outro")
    ]
    return ir.build_ir(
        artifact_id=artifact_id,
        preimage=preimage,
        grounding={"f0": ledger_entry()},
        parts=parts,
    )


class TestSplitParts:
    def test_addresses_each_part_by_deliverable_and_part_id(self):
        fitted = make_parts_ir()
        fid = fitted_id(fitted["binding"]["artifact_id"], PLATFORM, LANGUAGE)
        addresses = split_part_addresses(
            fitted, fitted_id=fid, output_type="thread", presentation="plain"
        )
        assert [a.ordinal for a in addresses] == [1, 2, 3]
        assert [a.part_label for a in addresses] == ["p01", "p02", "p03"]
        assert [a.role for a in addresses] == ["intro", "middle", "outro"]
        deliverable = f"{fid}.thread.plain"
        assert all(a.deliverable_id == deliverable for a in addresses)
        assert [a.part_id for a in addresses] == [f"{deliverable}~p0{n}" for n in (1, 2, 3)]

    def test_ordinals_are_stable_across_re_saves(self):
        import json

        from pipeline.canonical import canonical_json_str

        fitted = make_parts_ir()
        fid = fitted_id(fitted["binding"]["artifact_id"], PLATFORM, LANGUAGE)
        first = split_part_addresses(
            fitted, fitted_id=fid, output_type="thread", presentation="plain"
        )
        # A "re-save": round-trip the immutable fit through canonical JSON and re-derive. The
        # ordinals are a pure function of the content-addressed fit — they renumber NOTHING.
        reloaded = json.loads(canonical_json_str(fitted))
        second = split_part_addresses(
            reloaded, fitted_id=fid, output_type="thread", presentation="plain"
        )
        assert first == second

    def test_flat_fit_is_not_a_split(self):
        with pytest.raises(FitResolutionError, match="not a split"):
            split_part_addresses(
                make_canonical_ir(), fitted_id=fitted_id("a-" + "0" * 16, PLATFORM, LANGUAGE),
                output_type="thread", presentation="plain",
            )


# ---------------------------------------------------------------------------
# obs-3 (consumed-scoping) + obs-1 (numeric hard-limit fail-fast) — owned here.
# ---------------------------------------------------------------------------


class TestConsumedScopingObs3:
    def test_unconsumed_attribute_does_not_churn_the_fit_revision(self):
        consumed = {"tone_hint"}
        req_a = make_request(advisory={"tone_hint": "warm", "unused": "aaa"})
        req_b = make_request(advisory={"tone_hint": "warm", "unused": "bbb"})
        scoped_a = scope_request(
            req_a, consumed_advisory_keys=consumed, consumed_render_dim_keys=()
        )
        scoped_b = scope_request(
            req_b, consumed_advisory_keys=consumed, consumed_render_dim_keys=()
        )
        dig_a = reconcile.fit_digest(reconcile.reconcile_inputs_preimage(scoped_a))
        dig_b = reconcile.fit_digest(reconcile.reconcile_inputs_preimage(scoped_b))
        assert dig_a == dig_b  # the unconsumed change churned the fit-revision NOTHING
        # And without scoping the SAME change WOULD churn identity — proving the scope matters.
        unscoped_a = reconcile.fit_digest(reconcile.reconcile_inputs_preimage(req_a))
        unscoped_b = reconcile.fit_digest(reconcile.reconcile_inputs_preimage(req_b))
        assert unscoped_a != unscoped_b

    def test_scope_consumed_projects_to_only_consumed_keys(self):
        scoped = scope_consumed({"a": 1, "b": 2, "c": 3}, {"a", "c"})
        assert scoped == {"a": 1, "c": 3}


class TestNumericHardLimitObs1:
    def test_nonnumeric_hard_limit_fails_fast(self):
        req = make_request(hard_limits={"max_chars": "lots"})
        with pytest.raises(FitResolutionError, match="numeric ceiling"):
            scope_request(req, consumed_advisory_keys=(), consumed_render_dim_keys=())

    def test_bool_hard_limit_is_refused(self):
        req = make_request(hard_limits={"max_chars": True})
        with pytest.raises(FitResolutionError, match="numeric ceiling"):
            scope_request(req, consumed_advisory_keys=(), consumed_render_dim_keys=())

    def test_numeric_hard_limit_passes(self):
        req = make_request(hard_limits={"max_chars": 500})
        scoped = scope_request(req, consumed_advisory_keys=(), consumed_render_dim_keys=())
        assert scoped.hard_limits == {"max_chars": 500}


# ---------------------------------------------------------------------------
# Record parsing + coordinate discipline (loud wiring guards, §3.1).
# ---------------------------------------------------------------------------


class TestRecordParsing:
    def test_wrong_coordinate_record_is_refused(self):
        request = make_request()
        # A fit-binding under a DIFFERENT platform must not resolve against this coordinate.
        other = binding_for(
            make_request(platform="mastodon"), minted_ts="2026-01-01T00:00:00+00:00"
        )
        with pytest.raises(FitResolutionError, match="not under the resolution coordinate"):
            resolve_fit(coordinate_for(request), [other], preimage_of(request))

    def test_malformed_binding_is_refused(self):
        with pytest.raises(FitResolutionError, match="digest"):
            parse_fit_binding(
                {
                    "fitted_id": fitted_id("a-" + "0" * 16, PLATFORM, LANGUAGE),
                    "digest": "not-hex",
                    "minted_ts": "2026-01-01T00:00:00+00:00",
                    "preimage": {},
                }
            )

    def test_non_artifact_coordinate_is_refused(self):
        with pytest.raises(FitResolutionError, match="BARE artifact root"):
            FitCoordinate(fitted_id("a-" + "0" * 16, PLATFORM, LANGUAGE), PLATFORM, LANGUAGE)


# ---------------------------------------------------------------------------
# INV-CORRECTNESS (§22.7): the resolution module never imports the SSOT.
# ---------------------------------------------------------------------------


class TestNoSsotImport:
    def test_fit_resolution_imports_no_ssot(self):
        tree = ast.parse((REPO_ROOT / "pipeline" / "fit_resolution.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all("ssot" not in alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module is None or "ssot" not in node.module
