"""Step-17 tests — `pipeline/m3.py`: the §6.3 selection grammar + the four-layer fold.

Covers: the score vocabulary as CODE CONSTANTS (the step-15 carry-forward) pinned
against the SHIPPED sources/content-kinds schemas; the A7 operator-vocabulary drift
pins against `pipeline.opgrammar`; typed clause parsing per §6.2 score type (incl. the
date-window operators); identity predicates refused (§6.3); freshness window-expression
validation + evaluation against the INJECTED clock; prefer/span/relax surfaces; the
§12.1 fold with SM3 relax warnings and the CA10 weight lanes; and the shipped
`convince` goal entry's clauses as live §6.3 sample data.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from pipeline import opgrammar
from pipeline.m3 import (
    CATEGORICAL_MEMBERS,
    CONTENT_KIND,
    DEFAULT_GROUNDING_POSTURE,
    DEFAULT_ON_CONFLICT,
    LAYER_KEYS,
    M3_CLAUSE_TOKENS,
    M3_CONTAINS,
    M3_IS,
    M3_ONLY_OPERATORS,
    M3_OVERLAPS,
    ORDINAL_MEMBERS,
    PER_FACT_REFINABLE_SCORES,
    SCOPE_FACT,
    SCOPE_INSTANCE,
    SCORE_ATTACH_TIERS,
    SCORE_SELECTION_SCOPES,
    SCORE_TYPES,
    SCORES,
    SELECTABLE_CHARACTERISTICS,
    SPAN_AXES,
    M3GrammarError,
    M3OperatorError,
    PreferTerm,
    RelaxTargetError,
    SelectionClause,
    UnknownScoreError,
    WindowExpressionError,
    bare_score_contribution,
    evaluate_clause,
    fold_layers,
    goal_layer_origin,
    month_window,
    parse_clause,
    parse_prefer_item,
    parse_selection_layer,
    parse_window_expression,
    render_clause,
    resolve_selection,
)
from pipeline.schema import load_schema
from pipeline.yamlio import load_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.date(2026, 7, 1)


# --- The score vocabulary: code constants (step-15 carry-forward i) ------------------------


class TestScoreVocabulary:
    def test_the_nine_scores(self):
        # §6.2: eight scores + review_status (SM6). volatility (SM7) and coverage (SM8)
        # are deliberately absent.
        assert SCORES == {
            "trusted",
            "independence",
            "primariness",
            "authoritative",
            "opinionated",
            "freshness",
            "corroboration",
            "traceability",
            "review_status",
        }
        assert "volatility" not in SELECTABLE_CHARACTERISTICS
        assert "coverage" not in SELECTABLE_CHARACTERISTICS
        assert CONTENT_KIND in SELECTABLE_CHARACTERISTICS

    def test_attach_tiers_match_the_662_table(self):
        assert SCORE_ATTACH_TIERS == {
            "trusted": "instance",
            "independence": "instance",
            "primariness": "instance",
            "authoritative": "content-kind",
            "opinionated": "content-kind",
            "freshness": "content-kind",
            "review_status": "content-kind",
            "corroboration": "per-fact",
            "traceability": "per-fact",
        }

    def test_selection_scopes_gate_per_fact_scores_off_instances(self):
        # SM2's scope rule: per-fact scores cannot select instances.
        for score in ("corroboration", "traceability"):
            assert SCORE_SELECTION_SCOPES[score] == SCOPE_FACT
        # §6.3's own comment labels: primariness instance-scope; freshness fact-scope.
        assert SCORE_SELECTION_SCOPES["primariness"] == SCOPE_INSTANCE
        assert SCORE_SELECTION_SCOPES["freshness"] == SCOPE_FACT
        assert SCORE_SELECTION_SCOPES[CONTENT_KIND] == SCOPE_INSTANCE
        assert set(SCORE_SELECTION_SCOPES) == SELECTABLE_CHARACTERISTICS

    def test_constants_pin_against_the_shipped_schemas(self):
        # The mirror is mechanical: MEMBER SETS come from the SHIPPED sources/
        # content-kinds schemas (the §6.2 vocabulary of record) — member drift fails
        # here. The ORDER of ORDINAL_MEMBERS is m3's own semantic low→high rank
        # declaration (the schemas author §6.2's table order, e.g. `primary |
        # secondary | tertiary`), so order is asserted as m3's, not the schema's.
        sources = load_schema(REPO_ROOT / "sources" / "_schema.yaml")
        assert set(sources.attributes["independence"].type.values) == set(
            ORDINAL_MEMBERS["independence"]
        )
        assert set(sources.attributes["primariness"].type.values) == set(
            ORDINAL_MEMBERS["primariness"]
        )
        assert ORDINAL_MEMBERS["independence"] == ("first-party", "affiliated", "independent")
        assert ORDINAL_MEMBERS["primariness"] == ("tertiary", "secondary", "primary")
        kinds = load_schema(REPO_ROOT / "content-kinds" / "_schema.yaml")
        assert tuple(kinds.attributes["review_status"].type.values) == CATEGORICAL_MEMBERS[
            "review_status"
        ]

    def test_refinable_set_excludes_resolver_computed_scores(self):
        assert PER_FACT_REFINABLE_SCORES == {
            "authoritative",
            "opinionated",
            "review_status",
            "primariness",
        }


# --- A7: operator-vocabulary drift pins ----------------------------------------------------


class TestOperatorVocabulary:
    def test_m3_only_set_equals_opgrammars_reservation(self):
        # opgrammar reserves the M3 date-window operators by name; the two modules
        # share ONE vocabulary (§13.2/A7) — drift fails mechanically (also at import).
        assert {M3_CONTAINS, M3_OVERLAPS} == opgrammar._M3_ONLY_OPERATORS
        assert M3_ONLY_OPERATORS == {M3_IS, M3_CONTAINS, M3_OVERLAPS}
        assert not M3_ONLY_OPERATORS & (opgrammar.PRED_OPS | opgrammar.BIND_OPS)

    def test_comparison_tokens_are_derived_from_opgrammar(self):
        # The shared six ride opgrammar's OWN canonical names.
        assert M3_CLAUSE_TOKENS["=="] is opgrammar.PRED_EQ
        assert M3_CLAUSE_TOKENS[">="] is opgrammar.PRED_GE
        assert M3_CLAUSE_TOKENS["<="] is opgrammar.PRED_LE
        assert M3_CLAUSE_TOKENS[">"] is opgrammar.PRED_GT
        assert M3_CLAUSE_TOKENS["<"] is opgrammar.PRED_LT
        assert M3_CLAUSE_TOKENS["in"] is opgrammar.PRED_IN
        # `=` is the Pred token, never M3's (§13.2 disambiguation, both directions).
        assert "=" not in M3_CLAUSE_TOKENS

    def test_pred_equals_token_refused_with_pointer(self):
        with pytest.raises(M3OperatorError, match="'==' "):
            parse_clause("primariness = primary")

    def test_pred_only_operators_refused(self):
        for text in ("trusted prefix 3", "trusted range [1, 3]"):
            with pytest.raises(M3OperatorError, match="pred_op"):
                parse_clause(text)

    def test_bind_side_tokens_refused(self):
        for token in ("union", "replace", "-"):
            with pytest.raises(M3OperatorError, match="bind-side"):
                parse_clause(f"trusted {token} 3")

    def test_opgrammar_refuses_m3_operators_symmetrically(self):
        # The reverse guard already shipped at step 9 — assert the pairing holds.
        with pytest.raises(opgrammar.PredOperatorError):
            opgrammar.parse_pred_string("freshness contains 2026-01-01")


# --- Window expressions (step-15 carry-forward ii) ------------------------------------------


class TestWindowExpressions:
    def test_valid(self):
        assert parse_window_expression("12mo") == 12
        assert parse_window_expression("1mo") == 1
        assert parse_window_expression(" 24mo ") == 24

    @pytest.mark.parametrize(
        "bad", ["", "mo", "12", "12months", "-3mo", "0mo", "1.5mo", "12MO", "12 mo"]
    )
    def test_garbage_refused(self, bad):
        with pytest.raises(WindowExpressionError, match="Nmo"):
            parse_window_expression(bad)

    def test_non_string_refused(self):
        with pytest.raises(WindowExpressionError):
            parse_window_expression(12)

    def test_month_window_clamps_day_to_month_end(self):
        # 2026-07-31 minus 1 month: June has 30 days.
        start, end = month_window(datetime.date(2026, 7, 31), 1)
        assert start == datetime.date(2026, 6, 30)
        assert end == datetime.date(2026, 7, 31)
        # year boundary
        start, _ = month_window(datetime.date(2026, 2, 28), 3)
        assert start == datetime.date(2025, 11, 28)


# --- Clause parsing: typed by the score (§6.2) ----------------------------------------------


class TestClauseParsing:
    def test_the_663_block_parses_verbatim(self):
        # The design's own require examples (§6.3).
        for text in ("primariness == primary", "freshness < 12mo", "corroboration >= 2"):
            clause = parse_clause(text)
            assert render_clause(clause) == text

    def test_shipped_convince_require_parses(self):
        clause = parse_clause("traceability is true")
        assert clause.score == "traceability"
        assert clause.op == M3_IS
        assert clause.operand is True

    def test_canonical_round_trip(self):
        for text in (
            "trusted >= 4",
            "independence in [independent, affiliated]",
            "review_status == reviewed",
            "content-kind == merged-code",
            "freshness contains 2026-01-15",
            "freshness overlaps 6mo",
            "freshness overlaps [2025-01-01, 2025-06-30]",
        ):
            clause = parse_clause(text)
            again = parse_clause(render_clause(clause))
            assert again == clause

    def test_scope_property(self):
        assert parse_clause("trusted >= 4").scope == SCOPE_INSTANCE
        assert parse_clause("corroboration >= 2").scope == SCOPE_FACT

    def test_ordinal_order_comparisons(self):
        clause = parse_clause("independence >= affiliated")
        assert clause.op == opgrammar.PRED_GE

    def test_categorical_refuses_order(self):
        # review_status is categorical (SM6): `unknown` breaks any total order.
        with pytest.raises(M3OperatorError, match="unknown"):
            parse_clause("review_status >= reviewed")

    def test_bool_refuses_equals(self):
        with pytest.raises(M3OperatorError, match="`is`"):
            parse_clause("traceability == true")

    def test_scalar_refuses_in(self):
        with pytest.raises(M3OperatorError):
            parse_clause("trusted in [3, 4]")

    def test_freshness_refuses_ge(self):
        with pytest.raises(M3OperatorError):
            parse_clause("freshness >= 12mo")

    def test_slider_operand_bounds(self):
        with pytest.raises(M3GrammarError, match="out of scale"):
            parse_clause("trusted >= 6")
        with pytest.raises(M3GrammarError, match="integer"):
            parse_clause("trusted >= 3.5")

    def test_count_operand_nonnegative(self):
        with pytest.raises(M3GrammarError, match="negative"):
            parse_clause("corroboration >= -1")

    def test_enum_member_validated(self):
        with pytest.raises(M3GrammarError, match="not a member"):
            parse_clause("primariness == principal")

    def test_in_requires_nonempty_distinct_members(self):
        with pytest.raises(M3GrammarError, match="non-empty"):
            parse_clause("independence in []")
        with pytest.raises(M3GrammarError, match="duplicate"):
            parse_clause("independence in [independent, independent]")

    def test_content_kind_members_are_slugs(self):
        parse_clause("content-kind in [merged-code, research-notes]")
        with pytest.raises(M3GrammarError, match="slug"):
            parse_clause("content-kind == Merged_Code")

    def test_window_operand_validated(self):
        with pytest.raises(WindowExpressionError):
            parse_clause("freshness < 12months")

    def test_contains_requires_bare_date(self):
        with pytest.raises(M3GrammarError, match="bare date"):
            parse_clause("freshness contains 12mo")

    def test_overlaps_pair_ordered(self):
        with pytest.raises(M3GrammarError, match="start <= end"):
            parse_clause("freshness overlaps [2026-06-01, 2026-01-01]")

    def test_malformed_shapes_refused(self):
        for bad in ("trusted >=", "trusted", "", "trusted >= 3 extra ok?"):
            if bad == "trusted >= 3 extra ok?":
                # three-way split leaves the tail as one operand literal — not valid YAML
                with pytest.raises(M3GrammarError):
                    parse_clause(bad)
            else:
                with pytest.raises(M3GrammarError, match="score op value|single line|string"):
                    parse_clause(bad)
        with pytest.raises(M3GrammarError, match="single line"):
            parse_clause("trusted >= 3\ntrusted >= 4")
        with pytest.raises(M3GrammarError):
            parse_clause(["trusted", ">=", 3])


class TestIdentityRefusal:
    def test_source_id_predicates_refused_pointedly(self):
        # §6.3 acceptance: selection by characteristics only — no source-id predicates.
        for name in ("source-id", "source_id", "id", "instance", "adapter"):
            with pytest.raises(UnknownScoreError, match="never identity"):
                parse_clause(f"{name} == x-my-source")

    def test_unknown_score_refused_with_vocabulary(self):
        with pytest.raises(UnknownScoreError, match="characteristics only"):
            parse_clause("velocity >= 3")

    def test_direct_construction_validates_too(self):
        with pytest.raises(UnknownScoreError):
            SelectionClause(score="x-my-source", op=opgrammar.PRED_EQ, operand="anything")


# --- prefer terms (§6.3) ---------------------------------------------------------------------


class TestPreferParsing:
    def test_bare_score_weight(self):
        term, weight = parse_prefer_item({"authoritative": 2})
        assert (term.key, term.score, term.clause) == ("authoritative", "authoritative", None)
        assert weight == 2

    def test_predicate_key(self):
        term, weight = parse_prefer_item({"independence == independent": 1})
        assert weight == 1
        assert term.clause is not None
        assert term.key == "independence == independent"

    def test_yaml_plus_two_loads_as_int_two(self):
        # The step-15 note: YAML 1.2 loads `+2` as int 2 — straight from the shipped file.
        text = (REPO_ROOT / "goals" / "convince.md").read_text(encoding="utf-8")
        frontmatter, _ = load_frontmatter(text)
        weight = frontmatter["source_selection"]["prefer"][0]["authoritative"]
        assert weight == 2 and isinstance(weight, int)

    def test_bare_categorical_refused(self):
        with pytest.raises(M3GrammarError, match="no scalar contribution"):
            parse_prefer_item({"review_status": 1})
        with pytest.raises(M3GrammarError, match="no scalar contribution"):
            PreferTerm(key=CONTENT_KIND, score=CONTENT_KIND, clause=None)

    def test_non_integer_weights_refused(self):
        for weight in (1.5, "2", True, None):
            with pytest.raises(M3GrammarError, match="integer"):
                parse_prefer_item({"trusted": weight})

    def test_shape_refusals(self):
        with pytest.raises(M3GrammarError, match="single-key"):
            parse_prefer_item({"trusted": 1, "authoritative": 2})
        with pytest.raises(M3GrammarError, match="single-key"):
            parse_prefer_item("trusted")

    def test_negative_weights_legal(self):
        _, weight = parse_prefer_item({"opinionated": -2})
        assert weight == -2


# --- span (§6.3) ------------------------------------------------------------------------------


class TestSpanParsing:
    def test_axes(self):
        assert SPAN_AXES == (CONTENT_KIND, "independence", "primariness")

    def test_valid_span(self):
        layer = parse_selection_layer(
            {"span": {"content-kind": ["merged-code", "research-notes"]}}, origin="workspace"
        )
        assert layer.span == {"content-kind": ("merged-code", "research-notes")}

    def test_unknown_axis_refused(self):
        with pytest.raises(M3GrammarError, match="unknown span axis"):
            parse_selection_layer({"span": {"trusted": ["3"]}}, origin="workspace")

    def test_members_validated_per_axis(self):
        with pytest.raises(M3GrammarError, match="not a member"):
            parse_selection_layer(
                {"span": {"independence": ["first-party", "unaffiliated"]}}, origin="workspace"
            )

    def test_empty_and_duplicate_members_refused(self):
        with pytest.raises(M3GrammarError, match="non-empty"):
            parse_selection_layer({"span": {"content-kind": []}}, origin="workspace")
        with pytest.raises(M3GrammarError, match="duplicate span member"):
            parse_selection_layer(
                {"span": {"content-kind": ["merged-code", "merged-code"]}}, origin="workspace"
            )


# --- layer parsing -----------------------------------------------------------------------------


class TestLayerParsing:
    def test_closed_key_vocabulary(self):
        assert LAYER_KEYS == {
            "require", "prefer", "span", "on_conflict", "relax", "grounding_posture"
        }
        with pytest.raises(M3GrammarError, match="unknown selection key"):
            parse_selection_layer({"required": ["trusted >= 3"]}, origin="workspace")

    def test_none_is_the_empty_layer(self):
        layer = parse_selection_layer(None, origin="workspace")
        assert layer.require == () and layer.prefer == () and layer.on_conflict is None

    def test_on_conflict_token_shape(self):
        layer = parse_selection_layer({"on_conflict": "downgrade-AMBIGUOUS"}, origin="run")
        assert layer.on_conflict == "downgrade-AMBIGUOUS"
        with pytest.raises(M3GrammarError, match="single strategy"):
            parse_selection_layer({"on_conflict": "two words"}, origin="run")
        with pytest.raises(M3GrammarError, match="strategy"):
            parse_selection_layer({"on_conflict": ["downgrade-AMBIGUOUS"]}, origin="run")

    def test_grounding_posture_token_shape(self):
        # DR-6 (§6.5/§19): a closed value set — `warn`|`block` parse; anything else is refused.
        assert parse_selection_layer(
            {"grounding_posture": "block"}, origin="run"
        ).grounding_posture == "block"
        with pytest.raises(M3GrammarError, match="grounding_posture"):
            parse_selection_layer({"grounding_posture": "halt"}, origin="run")

    def test_grounding_posture_non_str_value_refused(self):
        # F1 (DR-6): a non-str (unhashable) value is refused with the layer's M3GrammarError
        # idiom, never a bare TypeError from the frozenset membership test.
        with pytest.raises(M3GrammarError, match="grounding_posture"):
            parse_selection_layer({"grounding_posture": ["block"]}, origin="run")

    def test_duplicate_prefer_key_in_one_layer_refused(self):
        with pytest.raises(M3GrammarError, match="duplicate prefer key"):
            parse_selection_layer(
                {"prefer": [{"trusted": 1}, {"trusted": 2}]}, origin="workspace"
            )

    def test_require_and_relax_are_lists(self):
        with pytest.raises(M3GrammarError, match="clause list"):
            parse_selection_layer({"require": "trusted >= 3"}, origin="workspace")
        with pytest.raises(M3GrammarError, match="list"):
            parse_selection_layer({"relax": "trusted >= 3"}, origin="run")

    def test_relax_targets_parse(self):
        layer = parse_selection_layer(
            {"relax": ["trusted >= 4", "span content-kind"]}, origin="run"
        )
        assert layer.relax == ("trusted >= 4", "span content-kind")
        with pytest.raises(M3GrammarError, match="unknown span axis"):
            parse_selection_layer({"relax": ["span trusted"]}, origin="run")


# --- the four-layer fold (§12.1; SM3; CA10) ----------------------------------------------------


class TestFold:
    def test_require_unions_and_dedupes(self):
        sel = resolve_selection(
            workspace={"require": ["trusted >= 3"]},
            goals=[("convince", {"require": ["traceability is true", "trusted >= 3"]})],
            recipe={"require": ["corroboration >= 1"]},
        )
        assert [render_clause(c) for c in sel.require] == [
            "trusted >= 3",
            "traceability is true",
            "corroboration >= 1",
        ]
        # dedupe keeps the FIRST setting layer's origin
        assert sel.require_origins["trusted >= 3"] == "workspace"
        assert sel.require_origins["traceability is true"] == "goal:convince"

    def test_span_unions_members(self):
        sel = resolve_selection(
            workspace={"span": {"content-kind": ["merged-code"]}},
            recipe={"span": {"content-kind": ["research-notes"], "independence": ["independent"]}},
        )
        assert sel.span == {
            "content-kind": ("merged-code", "research-notes"),
            "independence": ("independent",),
        }
        assert sel.span_origins == {"content-kind": "workspace", "independence": "recipe"}

    def test_on_conflict_most_local_wins_no_warning(self):
        sel = resolve_selection(
            workspace={"on_conflict": "preserve-and-attribute"},
            run={"on_conflict": "priority-wins"},
        )
        assert (sel.on_conflict, sel.on_conflict_origin) == ("priority-wins", "run")
        assert sel.warnings == ()

    def test_default_on_conflict(self):
        sel = resolve_selection()
        assert (sel.on_conflict, sel.on_conflict_origin) == (DEFAULT_ON_CONFLICT, "default")

    def test_grounding_posture_most_local_wins_no_warning(self):
        # DR-6 (§6.5/§19): resolves like on_conflict — a selection, most-local-wins, NO warning.
        # The recipe beats the workspace baseline; the run layer then beats the recipe.
        assert resolve_selection(
            workspace={"grounding_posture": "warn"},
            recipe={"grounding_posture": "block"},
        ).grounding_posture == "block"
        sel = resolve_selection(
            recipe={"grounding_posture": "warn"},
            run={"grounding_posture": "block"},
        )
        assert sel.grounding_posture == "block"
        assert sel.warnings == ()

    def test_default_grounding_posture_is_warn(self):
        # absent from every layer → the regression-neutral default (today's behavior EXACTLY).
        assert resolve_selection().grounding_posture == DEFAULT_GROUNDING_POSTURE == "warn"

    def test_relax_most_local_wins_with_warning(self):
        # SM3: the run relaxes a workspace hard clause — warned, never silent (§3.1).
        sel = resolve_selection(
            workspace={"require": ["primariness == primary", "trusted >= 3"]},
            run={"relax": ["primariness == primary"]},
        )
        assert [render_clause(c) for c in sel.require] == ["trusted >= 3"]
        assert len(sel.relaxed) == 1
        event = sel.relaxed[0]
        assert (event.target, event.set_at, event.relaxed_by) == (
            "primariness == primary",
            "workspace",
            "run",
        )
        assert len(sel.warnings) == 1
        assert "run relaxed `require: primariness == primary` set at workspace scope" in (
            sel.warnings[0].message
        )
        assert "never relaxes on its own initiative" in sel.warnings[0].message

    def test_relax_span_axis(self):
        sel = resolve_selection(
            workspace={"span": {"independence": ["first-party", "independent"]}},
            run={"relax": ["span independence"]},
        )
        assert sel.span == {}
        assert len(sel.warnings) == 1

    def test_recipe_may_relax_goal_implied(self):
        sel = resolve_selection(
            goals=[("convince", {"require": ["traceability is true"]})],
            recipe={"relax": ["traceability is true"]},
        )
        assert sel.require == ()
        assert sel.relaxed[0].set_at == "goal:convince"

    def test_relax_of_nothing_is_loud(self):
        with pytest.raises(RelaxTargetError, match="no.*inherited layer set that clause"):
            resolve_selection(run={"relax": ["trusted >= 4"]})
        with pytest.raises(RelaxTargetError, match="span"):
            resolve_selection(run={"relax": ["span content-kind"]})

    def test_a_layer_never_relaxes_its_own_clause(self):
        # relax acts on what a layer INHERITS (§6.4) — same-layer relax finds nothing.
        with pytest.raises(RelaxTargetError):
            resolve_selection(run={"require": ["trusted >= 4"], "relax": ["trusted >= 4"]})

    def test_ca10_goal_nudges_adjust_workspace_baseline(self):
        sel = resolve_selection(
            workspace={"prefer": [{"authoritative": 1}]},
            goals=[
                ("convince", {"prefer": [{"authoritative": 2}]}),
                ("explain", {"prefer": [{"authoritative": 1}, {"trusted": 1}]}),
            ],
        )
        weights = {p.term.key: (p.weight, p.origin) for p in sel.prefer}
        # baseline 1 + nudges 2 + 1 = 4; goal-only key starts from baseline 0.
        assert weights["authoritative"] == (4, "workspace")
        assert weights["trusted"] == (1, "goal:explain")

    def test_ca10_explicit_recipe_run_weight_wins_outright(self):
        sel = resolve_selection(
            workspace={"prefer": [{"authoritative": 1}]},
            goals=[("convince", {"prefer": [{"authoritative": 2}]})],
            recipe={"prefer": [{"authoritative": 3}]},
        )
        weights = {p.term.key: (p.weight, p.origin) for p in sel.prefer}
        assert weights["authoritative"] == (3, "recipe")  # never 3+2 — nudges don't move it
        sel = resolve_selection(
            workspace={"prefer": [{"authoritative": 1}]},
            goals=[("convince", {"prefer": [{"authoritative": 2}]})],
            recipe={"prefer": [{"authoritative": 3}]},
            run={"prefer": [{"authoritative": -1}]},
        )
        weights = {p.term.key: (p.weight, p.origin) for p in sel.prefer}
        assert weights["authoritative"] == (-1, "run")

    def test_fold_layer_origin_labels(self):
        assert goal_layer_origin("convince") == "goal:convince"
        with pytest.raises(M3GrammarError, match="unknown layer origin"):
            fold_layers(
                [
                    parse_selection_layer(
                        {"prefer": [{"trusted": 1}]}, origin="folio"  # no folio rung, ever
                    )
                ]
            )


# --- the shipped convince entry as live sample data (§6.3) -------------------------------------


class TestShippedConvinceGoal:
    def test_clauses_parse_from_the_shipped_file(self):
        text = (REPO_ROOT / "goals" / "convince.md").read_text(encoding="utf-8")
        frontmatter, _ = load_frontmatter(text)
        sel = resolve_selection(goals=[("convince", frontmatter["source_selection"])])
        assert [render_clause(c) for c in sel.require] == ["traceability is true"]
        assert sel.require_origins["traceability is true"] == "goal:convince"
        assert [(p.term.key, p.weight) for p in sel.prefer] == [("authoritative", 2)]


# --- evaluation semantics (typed ops; the injected clock) ---------------------------------------


class TestEvaluateClause:
    def test_scalar_ops(self):
        clause = parse_clause("trusted >= 4")
        assert evaluate_clause(clause, 4, now=NOW)
        assert not evaluate_clause(clause, 3, now=NOW)
        assert evaluate_clause(parse_clause("opinionated < 3"), 1, now=NOW)
        assert evaluate_clause(parse_clause("corroboration == 2"), 2, now=NOW)

    def test_ordinal_order(self):
        clause = parse_clause("independence >= affiliated")
        assert evaluate_clause(clause, "independent", now=NOW)
        assert evaluate_clause(clause, "affiliated", now=NOW)
        assert not evaluate_clause(clause, "first-party", now=NOW)
        member = parse_clause("primariness in [primary, secondary]")
        assert evaluate_clause(member, "primary", now=NOW)

    def test_bool_is(self):
        assert evaluate_clause(parse_clause("traceability is true"), True, now=NOW)
        assert not evaluate_clause(parse_clause("traceability is true"), False, now=NOW)
        assert evaluate_clause(parse_clause("traceability is false"), False, now=NOW)

    def test_unknown_value_never_satisfies_a_hard_clause(self):
        for text in ("trusted >= 1", "traceability is false", "freshness < 12mo"):
            assert not evaluate_clause(parse_clause(text), None, now=NOW)

    def test_freshness_window_against_the_injected_clock(self):
        clause = parse_clause("freshness < 12mo")
        cutoff, _ = month_window(NOW, 12)
        assert cutoff == datetime.date(2025, 7, 1)
        assert evaluate_clause(clause, datetime.date(2025, 7, 2), now=NOW)
        assert not evaluate_clause(clause, cutoff, now=NOW)  # exactly N months: strict
        assert not evaluate_clause(clause, datetime.date(2024, 1, 1), now=NOW)
        # the SAME value flips with a different injected clock — never ambient time
        assert evaluate_clause(clause, datetime.date(2024, 1, 1), now=datetime.date(2024, 6, 1))

    def test_freshness_contains_and_overlaps(self):
        contains = parse_clause("freshness contains 2026-01-15")
        assert evaluate_clause(contains, datetime.date(2026, 1, 15), now=NOW)
        assert not evaluate_clause(contains, datetime.date(2026, 1, 16), now=NOW)
        assert evaluate_clause(
            contains, [datetime.date(2026, 1, 1), datetime.date(2026, 2, 1)], now=NOW
        )
        overlaps = parse_clause("freshness overlaps 6mo")
        assert evaluate_clause(overlaps, datetime.date(2026, 6, 1), now=NOW)
        assert not evaluate_clause(overlaps, datetime.date(2025, 1, 1), now=NOW)
        pair = parse_clause("freshness overlaps [2025-01-01, 2025-06-30]")
        assert evaluate_clause(pair, datetime.date(2025, 3, 1), now=NOW)
        assert not evaluate_clause(pair, datetime.date(2025, 7, 1), now=NOW)


class TestBareScoreContribution:
    def test_conventions(self):
        assert bare_score_contribution("trusted", 4, now=NOW) == 4.0
        assert bare_score_contribution("independence", "independent", now=NOW) == 2.0
        assert bare_score_contribution("traceability", True, now=NOW) == 1.0
        assert bare_score_contribution("traceability", False, now=NOW) == 0.0
        assert bare_score_contribution("trusted", None, now=NOW) == 0.0

    def test_freshness_recency_factor(self):
        assert bare_score_contribution("freshness", NOW, now=NOW) == 1.0
        year_old = bare_score_contribution(
            "freshness", NOW - datetime.timedelta(days=365), now=NOW
        )
        assert year_old == 0.0
        half = bare_score_contribution("freshness", NOW - datetime.timedelta(days=182), now=NOW)
        assert 0.0 < half < 1.0

    def test_unknown_score_refused(self):
        with pytest.raises(UnknownScoreError):
            bare_score_contribution("coverage", 1, now=NOW)  # SM8: resolver-internal


# --- type table sanity ---------------------------------------------------------------------------


def test_every_characteristic_has_type_scope_and_operators():
    assert set(SCORE_TYPES) == SELECTABLE_CHARACTERISTICS
    for name in SELECTABLE_CHARACTERISTICS:
        assert name in SCORE_SELECTION_SCOPES
    for score in SCORES:
        assert score in SCORE_ATTACH_TIERS
