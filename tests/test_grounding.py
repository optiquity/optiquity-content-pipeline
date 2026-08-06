"""Step-17 tests — `pipeline/grounding.py` + the adapter contract, against the mock.

Covers: the §6.3 resolver walk branch by branch — instance-scope filter, span,
union + corroboration (tier upgrade ONLY across genuinely independent, distinctly
BOUND sources — adapter + connection dedupe, RV-1;
§6.5), per-fact effective scores (all nine consumed, incl. the G6 `review_status`
degradation to `unknown`), the freshness policy/clauses against the INJECTED clock,
fact-scope filters, ranking (prefer never excludes; trusted/primariness/coverage
tie-breaks), every shipped `on_conflict` strategy (factual-beats-opinion +
contradiction surfacing on fixture conflicts, SM4), the SM1 `empty-pool` block shape
with the batch continuing, the SM3 relax warning end-to-end, tier ⟂ traceability +
the unrelaxable EXTRACTED publish floor (SM9/§6.5), and the PA-9a user-assertion
stamps with the one-time divergence advisory. The end-to-end leg runs the SHIPPED
`convince` goal and registries through `resolve_compose` → `resolve_selection` →
`ground_item` (REC-3: registries copied to tmp; the repo stays read-only).
"""

from __future__ import annotations

import datetime
import shutil
from pathlib import Path

import pytest

from pipeline.adapters.base import (
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    TIER_INFERRED,
    AdapterError,
    Anchor,
    Fact,
    GroundingResult,
    SourceAdapter,
    tier_rank,
    upgrade_tier,
)
from pipeline.adapters.mock import MockAdapter, default_datasets, synthetic_commit
from pipeline.cascade import CascadeEnv, RunSelection, resolve_compose
from pipeline.grounding import (
    ASSERTABLE_SCORES,
    CODE_EMPTY_POOL,
    CODE_LOW_CONFIDENCE_GROUNDING,
    INSTANCE_SCORE_FLOORS,
    KIND_SCORE_FLOORS,
    REUSE_RIGHTS,
    REUSE_RIGHTS_FLOOR,
    REUSE_RIGHTS_PUBLISH_THRESHOLD,
    STATUS_BLOCK,
    STATUS_OK,
    STATUS_WARN,
    GroundedFact,
    GroundingError,
    GroundingRequest,
    RefinementError,
    ReuseRightsError,
    SourceInstance,
    UnknownConflictStrategyError,
    build_instance,
    build_pool,
    conflict_strategies,
    ground_batch,
    ground_item,
    register_conflict_strategy,
    reuse_rights_rank,
)
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m1 import DanglingRefError
from pipeline.m3 import (
    SCORES,
    SELECTABLE_CHARACTERISTICS,
    UnknownScoreError,
    WindowExpressionError,
    parse_clause,
    resolve_selection,
)
from pipeline.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.date(2026, 7, 1)
WS = "testws"
USER = "acme"

RECORD_KIND = {  # a merged-code-style bundle (§6.1 SM5)
    "authoritative": 4,
    "opinionated": 1,
    "review_status": "reviewed",
    "freshness": "",
}
NOTES_KIND = {  # a research-notes-style bundle
    "authoritative": 2,
    "opinionated": 4,
    "review_status": "unreviewed",
    "freshness": "12mo",
}


def fact(
    subject: str,
    claim: str,
    *,
    tier: str = TIER_EXTRACTED,
    anchored: bool = True,
    as_of: datetime.date | None = datetime.date(2026, 5, 1),
    refinements: dict | None = None,
) -> Fact:
    anchors = (Anchor("file-line", f"docs/{subject}.md:1"),) if anchored else ()
    return Fact(
        subject=subject,
        claim=claim,
        tier=tier,
        anchors=anchors,
        as_of=as_of,
        refinements=refinements or {},
    )


def inst(instance_id: str, dataset: str, **kwargs) -> SourceInstance:
    kwargs.setdefault("adapter", "mock")
    kwargs.setdefault("connection", {"dataset": dataset})
    return SourceInstance(id=instance_id, **kwargs)


def ground(pool, selection=None, *, datasets, query="", item="item-1", **kwargs):
    kwargs.setdefault("now", NOW)
    return ground_item(
        item=item,
        query=query,
        pool=pool,
        selection=selection if selection is not None else resolve_selection(),
        adapters={"mock": MockAdapter(datasets)},
        **kwargs,
    )


# --- adapter contract (base) ----------------------------------------------------------------


class TestAdapterContract:
    def test_tier_helpers(self):
        assert tier_rank(TIER_AMBIGUOUS) < tier_rank(TIER_INFERRED) < tier_rank(TIER_EXTRACTED)
        assert upgrade_tier(TIER_AMBIGUOUS) == TIER_INFERRED
        assert upgrade_tier(TIER_INFERRED) == TIER_EXTRACTED
        assert upgrade_tier(TIER_EXTRACTED) == TIER_EXTRACTED  # never above the top
        with pytest.raises(AdapterError, match="unknown confidence tier"):
            tier_rank("PROVEN")

    def test_anchor_validation(self):
        with pytest.raises(AdapterError, match="anchor kind"):
            Anchor("line", "x.py:1")
        with pytest.raises(AdapterError, match="non-empty"):
            Anchor("sha", "  ")

    def test_fact_validation(self):
        with pytest.raises(AdapterError, match="tier"):
            fact("s", "c", tier="TRUE")
        with pytest.raises(AdapterError, match="non-empty"):
            Fact(subject="", claim="c", tier=TIER_EXTRACTED)
        with pytest.raises(AdapterError, match="date-granular"):
            Fact(subject="s", claim="c", tier=TIER_EXTRACTED, as_of=datetime.datetime(2026, 1, 1))
        with pytest.raises(AdapterError, match="tuple of Anchor"):
            Fact(subject="s", claim="c", tier=TIER_EXTRACTED, anchors=["x"])
        with pytest.raises(AdapterError, match="string-keyed"):
            Fact(subject="s", claim="c", tier=TIER_EXTRACTED, refinements={1: "x"})

    def test_grounding_result_validation(self):
        with pytest.raises(AdapterError, match="tuple of Fact"):
            GroundingResult(facts=[fact("s", "c")])
        with pytest.raises(AdapterError, match="built_at_commit"):
            GroundingResult(facts=(), built_at_commit="")

    def test_contract_is_read_only_shaped(self):
        # The ABC exposes exactly the query capability — no write primitive exists.
        assert SourceAdapter.capabilities == frozenset({"query"})
        assert not any(
            name in vars(SourceAdapter) for name in ("write", "save", "update", "extract")
        )


class TestMockAdapter:
    def test_deterministic_and_filterable(self):
        adapter = MockAdapter()
        both = adapter.ground(connection={"dataset": "alpha-docs"}, query="")
        again = adapter.ground(connection={"dataset": "alpha-docs"}, query="")
        assert both == again  # same facts, same order, same commit — every time
        widget = adapter.ground(connection={"dataset": "alpha-docs"}, query="widget")
        assert {f.subject for f in widget.facts} == {
            "widget-service.timeout",
            "widget-service.retries",
        }
        assert both.built_at_commit == synthetic_commit("alpha-docs")

    def test_unknown_dataset_and_bad_connection_loud(self):
        adapter = MockAdapter()
        with pytest.raises(AdapterError, match="unknown mock dataset"):
            adapter.ground(connection={"dataset": "nope"}, query="")
        with pytest.raises(AdapterError, match="`dataset`"):
            adapter.ground(connection={}, query="")

    def test_commit_override_and_none(self):
        adapter = MockAdapter({"d": (fact("s", "c"),)}, commits={"d": None})
        assert adapter.ground(connection={"dataset": "d"}, query="").built_at_commit is None

    def test_default_datasets_cover_the_needed_branches(self):
        datasets = default_datasets()
        tiers = {f.tier for facts in datasets.values() for f in facts}
        assert tiers == {TIER_EXTRACTED, TIER_INFERRED, TIER_AMBIGUOUS}
        # the authored conflict + agreement seeds exist
        claims = {
            (f.subject, f.claim) for facts in datasets.values() for f in facts
        }
        subjects = [s for s, _ in claims]
        assert subjects.count("widget-service.timeout") == 2  # one agreement + one conflict
        assert subjects.count("gadget-cache.capacity") == 2
        anchorless = [
            f for facts in datasets.values() for f in facts
            if f.tier == TIER_EXTRACTED and not f.anchors
        ]
        assert anchorless  # the SM9 seed

    def test_pin_commit_agrees_with_ground(self):
        # CF-1: `pin_commit` (the §7.2 identity commit-map value) MUST equal the commit
        # `ground()` records — else the artifact-id commit-map would OMIT a commit the §15
        # ledger keeps, exactly the divergence CF-1 closed for graphify/folder. Mirrors
        # `test_adapter_graphify.py`'s `test_pin_commit_agrees_with_ground_*` and the
        # folder-adapter agreement test.
        adapter = MockAdapter()
        pinned = adapter.pin_commit({"dataset": "alpha-docs"})
        grounded = adapter.ground(connection={"dataset": "alpha-docs"}, query="").built_at_commit
        assert pinned == grounded == synthetic_commit("alpha-docs")

    def test_pin_commit_honors_commit_override_including_none(self):
        # The `commits` override rides BOTH paths: an explicit None (a commitless kind) pins
        # None matching ground(); a concrete override pins that same value on both.
        none_adapter = MockAdapter({"d": (fact("s", "c"),)}, commits={"d": None})
        assert none_adapter.pin_commit({"dataset": "d"}) is None
        assert none_adapter.ground(connection={"dataset": "d"}, query="").built_at_commit is None
        set_adapter = MockAdapter({"d": (fact("s", "c"),)}, commits={"d": "beef1234"})
        assert set_adapter.pin_commit({"dataset": "d"}) == "beef1234"

    def test_pin_commit_unknown_or_malformed_connection_is_none(self):
        # An unknown/malformed connection pins nothing — ground() then fails loudly, so no
        # diverged id is ever persisted (the graphify absent-graph → None posture).
        adapter = MockAdapter()
        assert adapter.pin_commit({"dataset": "nope"}) is None
        assert adapter.pin_commit({}) is None


# --- instance config (SourceInstance / build_instance) ---------------------------------------


class TestSourceInstance:
    def test_floor_mirrors_pin_against_the_shipped_schemas(self):
        sources = load_schema(REPO_ROOT / "sources" / "_schema.yaml")
        for score, floor in INSTANCE_SCORE_FLOORS.items():
            assert sources.attributes[score].default == floor, score
        kinds = load_schema(REPO_ROOT / "content-kinds" / "_schema.yaml")
        for score, floor in KIND_SCORE_FLOORS.items():
            assert kinds.attributes[score].default == floor, score

    def test_validation(self):
        with pytest.raises(GroundingError, match="no adapter bound"):
            SourceInstance(id="x-a", adapter="")
        with pytest.raises(GroundingError, match="1-5"):
            inst("x-a", "d", trusted=6)
        with pytest.raises(GroundingError, match="independence"):
            inst("x-a", "d", independence="unaffiliated")
        with pytest.raises(GroundingError, match="non-assertable"):
            inst("x-a", "d", assertions={"trusted": 5})

    def test_freshness_expressions_validated_on_load(self):
        # the step-15 carry-forward: the text carrier no longer accepts garbage silently
        with pytest.raises(WindowExpressionError):
            inst("x-a", "d", assertions={"freshness": "12months"})
        with pytest.raises(WindowExpressionError):
            inst("x-a", "d", kind_defaults={"freshness": "soon"})

    def test_kind_value_floors(self):
        bare = inst("x-a", "d")  # no kind bundle: the G6 degradation floor
        assert bare.kind_value("review_status") == "unknown"
        assert bare.kind_value("authoritative") == 3
        assert bare.kind_value("freshness") == ""


# --- SM1: empty pool blocks the ITEM; the batch continues -------------------------------------


class TestEmptyPoolBlocks:
    def test_failed_instance_require_blocks_with_clause_named(self):
        pool = [inst("x-a", "d", primariness="secondary")]
        sel = resolve_selection(workspace={"require": ["primariness == primary"]})
        out = ground(pool, sel, datasets={"d": (fact("s", "c"),)})
        assert out.status == STATUS_BLOCK
        assert out.code == CODE_EMPTY_POOL
        assert out.context["clause"] == "primariness == primary"
        assert out.context["set_at"] == "workspace"
        assert out.remediation["action"] == "relax-clause"
        assert out.facts == ()

    def test_empty_pool_itself_blocks(self):
        out = ground([], resolve_selection(), datasets={})
        assert (out.status, out.code) == (STATUS_BLOCK, CODE_EMPTY_POOL)
        assert out.context["clause"] is None
        assert out.remediation["action"] == "add-source"

    def test_no_facts_for_query_blocks(self):
        out = ground(
            [inst("x-a", "d")], datasets={"d": (fact("s", "c"),)}, query="unrelated-term"
        )
        assert (out.status, out.code) == (STATUS_BLOCK, CODE_EMPTY_POOL)
        assert "no facts" in out.context["detail"]

    def test_failed_fact_require_blocks_with_clause_named(self):
        pool = [inst("x-a", "d")]
        sel = resolve_selection(recipe={"require": ["corroboration >= 2"]})
        out = ground(pool, sel, datasets={"d": (fact("s", "c"),)})
        assert (out.status, out.code) == (STATUS_BLOCK, CODE_EMPTY_POOL)
        assert out.context["clause"] == "corroboration >= 2"
        assert out.context["set_at"] == "recipe"

    def test_batch_continues_past_a_blocked_item(self):
        # SM1: a per-item block never fails the batch — siblings proceed.
        pool = [inst("x-a", "d")]
        blocked = GroundingRequest(
            item="blocked-item",
            query="",
            selection=resolve_selection(workspace={"require": ["trusted >= 5"]}),
        )
        fine = GroundingRequest(item="fine-item", query="", selection=resolve_selection())
        outcomes = ground_batch(
            [blocked, fine],
            pool=pool,
            adapters={"mock": MockAdapter({"d": (fact("s", "c"),)})},
            now=NOW,
        )
        assert [o.status for o in outcomes] == [STATUS_BLOCK, STATUS_OK]
        assert outcomes[1].facts  # the sibling actually grounded


# --- span (§6.3/§6.4) --------------------------------------------------------------------------


class TestSpan:
    def test_span_satisfied(self):
        pool = [
            inst("x-a", "d1", content_kind="merged-code", kind_defaults=RECORD_KIND),
            inst("x-b", "d2", content_kind="research-notes", kind_defaults=NOTES_KIND),
        ]
        sel = resolve_selection(
            workspace={"span": {"content-kind": ["merged-code", "research-notes"]}}
        )
        out = ground(
            pool, sel, datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        )
        assert out.status == STATUS_OK

    def test_span_miss_blocks_naming_the_member(self):
        pool = [inst("x-a", "d1", content_kind="merged-code", kind_defaults=RECORD_KIND)]
        sel = resolve_selection(
            workspace={"span": {"content-kind": ["merged-code", "research-notes"]}}
        )
        out = ground(pool, sel, datasets={"d1": (fact("s1", "c1"),)})
        assert (out.status, out.code) == (STATUS_BLOCK, CODE_EMPTY_POOL)
        assert out.context["clause"] == "span content-kind: research-notes"
        assert out.context["set_at"] == "workspace"

    def test_span_checks_the_filtered_pool(self):
        # An instance the hard filter removed cannot cover a span member (§6.3 order:
        # instance-scope filter → span check on SURVIVORS).
        pool = [
            inst("x-a", "d1", content_kind="merged-code", trusted=2, kind_defaults=RECORD_KIND),
            inst("x-b", "d2", content_kind="research-notes", trusted=4, kind_defaults=NOTES_KIND),
        ]
        sel = resolve_selection(
            workspace={
                "require": ["trusted >= 3"],
                "span": {"content-kind": ["merged-code", "research-notes"]},
            }
        )
        out = ground(
            pool, sel, datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        )
        assert out.status == STATUS_BLOCK
        assert out.context["clause"] == "span content-kind: merged-code"

    def test_span_on_independence_axis(self):
        pool = [
            inst("x-a", "d1", independence="first-party"),
            inst("x-b", "d2", independence="independent"),
        ]
        sel = resolve_selection(
            workspace={"span": {"independence": ["first-party", "independent"]}}
        )
        out = ground(
            pool, sel, datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        )
        assert out.status == STATUS_OK


# --- SM3: relax end-to-end ----------------------------------------------------------------------


class TestRelaxEndToEnd:
    def test_run_relax_unblocks_with_warning(self):
        pool = [inst("x-a", "d", primariness="secondary")]
        datasets = {"d": (fact("s", "c"),)}
        blocked = ground(
            pool,
            resolve_selection(workspace={"require": ["primariness == primary"]}),
            datasets=datasets,
        )
        assert blocked.status == STATUS_BLOCK
        relaxed = ground(
            pool,
            resolve_selection(
                workspace={"require": ["primariness == primary"]},
                run={"relax": ["primariness == primary"]},
            ),
            datasets=datasets,
        )
        assert relaxed.status == STATUS_OK
        messages = [w.message for w in relaxed.warnings]
        assert any("run relaxed `require: primariness == primary`" in m for m in messages)


# --- prefer: never excludes; ranking (§6.3) ------------------------------------------------------


class TestPreferAndRanking:
    def test_prefer_never_excludes(self):
        # Nothing matches the preferred characteristic — everything still grounds.
        pool = [inst("x-a", "d", independence="first-party")]
        sel = resolve_selection(workspace={"prefer": [{"independence == independent": 5}]})
        out = ground(pool, sel, datasets={"d": (fact("s", "c"),)})
        assert out.status == STATUS_OK
        assert len(out.facts) == 1
        assert out.facts[0].weight == 0.0

    def test_bare_and_predicate_weights_rank(self):
        pool = [
            inst("x-notes", "d1", trusted=3, content_kind="research-notes",
                 kind_defaults=NOTES_KIND),
            inst("x-record", "d2", trusted=3, content_kind="merged-code",
                 kind_defaults=RECORD_KIND),
        ]
        sel = resolve_selection(
            workspace={"prefer": [{"authoritative": 2}, {"content-kind == merged-code": 1}]}
        )
        out = ground(
            pool, sel, datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        )
        assert [f.instance_id for f in out.facts] == ["x-record", "x-notes"]
        assert out.facts[0].weight == 4 * 2 + 1  # bare auth 4×2 + predicate match
        assert out.facts[1].weight == 2 * 2

    def test_trusted_primariness_and_coverage_tie_breaks(self):
        pool = [
            inst("x-low", "d1", trusted=2),
            inst("x-high", "d2", trusted=4),
        ]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)},
        )
        assert [f.instance_id for f in out.facts] == ["x-high", "x-low"]
        # primariness breaks a trusted tie
        pool = [
            inst("x-sec", "d1", primariness="secondary"),
            inst("x-pri", "d2", primariness="primary"),
        ]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)},
        )
        assert [f.instance_id for f in out.facts] == ["x-pri", "x-sec"]
        # coverage (SM8, resolver-internal) breaks the rest: two facts vs one
        pool = [inst("x-one", "d1"), inst("x-two", "d2")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={
                "d1": (fact("s1", "c1"),),
                "d2": (fact("s2", "c2"), fact("s3", "c3")),
            },
        )
        assert [f.instance_id for f in out.facts] == ["x-two", "x-two", "x-one"]

    def test_deterministic_across_runs(self):
        pool = [inst("x-a", "d1"), inst("x-b", "d2")]
        datasets = {"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        sel = resolve_selection(workspace={"prefer": [{"trusted": 1}]})
        first = ground(pool, sel, datasets=datasets)
        second = ground(pool, sel, datasets=datasets)
        assert first.facts == second.facts
        assert first.commit_map == second.commit_map


# --- corroboration & the tier upgrade (§6.5) ------------------------------------------------------


class TestCorroboration:
    def agreeing_pool(self, independence_b: str):
        pool = [
            inst("x-a", "da", independence="first-party"),
            inst("x-b", "db", independence=independence_b),
        ]
        claim = fact("widget.timeout", "The timeout is 30 seconds.", tier=TIER_INFERRED)
        return pool, {"da": (claim,), "db": (claim,)}

    def test_upgrade_across_genuinely_independent_instances(self):
        pool, datasets = self.agreeing_pool("independent")
        out = ground(pool, resolve_selection(), datasets=datasets)
        assert all(f.corroboration == 1 for f in out.facts)
        assert all(f.tier == TIER_EXTRACTED for f in out.facts)  # INFERRED + 1 level
        assert all(f.base_tier == TIER_INFERRED for f in out.facts)
        assert all(f.agreeing_instances == ("x-a", "x-b") for f in out.facts)

    def test_no_upgrade_without_an_independent_instance(self):
        # Two first-party instances agree: corroboration counts, the tier NEVER rises
        # (§6.5 "genuinely independent"; the acceptance pin).
        pool, datasets = self.agreeing_pool("first-party")
        out = ground(pool, resolve_selection(), datasets=datasets)
        assert all(f.corroboration == 1 for f in out.facts)
        assert all(f.tier == TIER_INFERRED for f in out.facts)

    def test_affiliated_agreement_never_upgrades(self):
        pool, datasets = self.agreeing_pool("affiliated")
        out = ground(pool, resolve_selection(), datasets=datasets)
        assert all(f.tier == TIER_INFERRED for f in out.facts)

    def test_single_instance_never_upgrades_itself(self):
        pool = [inst("x-a", "da", independence="independent")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"da": (fact("s", "c", tier=TIER_INFERRED),)},
        )
        assert out.facts[0].corroboration == 0
        assert out.facts[0].tier == TIER_INFERRED

    def test_upgrade_is_one_level_only(self):
        pool, datasets = self.agreeing_pool("independent")
        datasets = {
            name: tuple(
                Fact(subject=f.subject, claim=f.claim, tier=TIER_AMBIGUOUS, anchors=f.anchors,
                     as_of=f.as_of)
                for f in facts
            )
            for name, facts in datasets.items()
        }
        out = ground(pool, resolve_selection(), datasets=datasets)
        assert all(f.tier == TIER_INFERRED for f in out.facts)  # never straight to the top

    def test_corroboration_selects_facts(self):
        pool, datasets = self.agreeing_pool("independent")
        sel = resolve_selection(workspace={"require": ["corroboration >= 1"]})
        out = ground(pool, sel, datasets=datasets)
        assert out.status == STATUS_OK

    def test_identical_binding_pair_never_upgrades(self):
        # RV-1: two instances bound to the IDENTICAL adapter + connection are ONE
        # bound source — one corpus read twice is zero confirmations, even when an
        # instance is (mis)characterized `independent`. Instance ids remain the
        # provenance surface (`agreeing_instances`).
        claim = fact("widget.timeout", "The timeout is 30 seconds.", tier=TIER_INFERRED)
        pool = [
            inst("x-a", "shared", independence="first-party"),
            inst("x-b", "shared", independence="independent"),
        ]
        out = ground(pool, resolve_selection(), datasets={"shared": (claim,)})
        assert all(f.corroboration == 0 for f in out.facts)
        assert all(f.tier == TIER_INFERRED for f in out.facts)  # NOT upgraded
        assert all(f.agreeing_instances == ("x-a", "x-b") for f in out.facts)

    def test_distinct_bindings_still_count_as_sources(self):
        # The RV-1 dedupe narrows ONLY the identical-binding case: the same pair over
        # genuinely distinct connections keeps confirming and upgrading.
        claim = fact("widget.timeout", "The timeout is 30 seconds.", tier=TIER_INFERRED)
        pool = [
            inst("x-a", "da", independence="first-party"),
            inst("x-b", "db", independence="independent"),
        ]
        out = ground(pool, resolve_selection(), datasets={"da": (claim,), "db": (claim,)})
        assert all(f.corroboration == 1 for f in out.facts)
        assert all(f.tier == TIER_EXTRACTED for f in out.facts)


# --- tier ⟂ traceability; the publish floor (§6.5, SM9) -------------------------------------------


class TestTierAndTraceability:
    def test_extracted_without_anchor_refused_citability(self):
        pool = [inst("x-a", "d")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d": (fact("s", "c", anchored=False),)},
        )
        the_fact = out.facts[0]
        assert the_fact.tier == TIER_EXTRACTED
        assert the_fact.publishable  # the floor is about tier…
        assert not the_fact.citable  # …citability is the anchor truth — independent axes

    def test_inferred_with_anchor_is_citable_but_not_publishable(self):
        pool = [inst("x-a", "d")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d": (fact("s", "c", tier=TIER_INFERRED),)},
        )
        the_fact = out.facts[0]
        assert the_fact.citable and not the_fact.publishable
        assert out.leads == (the_fact,)

    def test_traceability_clause_filters_computed_anchorless(self):
        pool = [inst("x-a", "d")]
        sel = resolve_selection(goals=[("convince", {"require": ["traceability is true"]})])
        out = ground(
            pool,
            sel,
            datasets={"d": (fact("s1", "c1"), fact("s2", "c2", anchored=False))},
        )
        assert [f.subject for f in out.facts] == ["s1"]

    def test_no_extracted_fact_warns_low_confidence(self):
        pool = [inst("x-a", "d")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d": (fact("s", "c", tier=TIER_INFERRED),)},
        )
        assert out.status == STATUS_WARN
        assert out.code == CODE_LOW_CONFIDENCE_GROUNDING
        assert out.publishable_facts == ()
        assert out.facts  # grounded — leads survive as leads, never as published fact
        assert any("leads to verify" in w.message for w in out.warnings)

    def test_the_floor_is_outside_the_grammar(self):
        # No selectable "tier" characteristic exists: the floor cannot be addressed,
        # let alone relaxed, by any require/prefer/relax configuration (§6.5).
        with pytest.raises(UnknownScoreError):
            parse_clause("tier == INFERRED")
        with pytest.raises(UnknownScoreError):
            parse_clause("confidence >= EXTRACTED")

    def test_publishable_is_computed_from_tier_alone(self):
        # Every configuration surface exercised at once — publishability still tracks
        # the tier and nothing else.
        pool = [inst("x-a", "d", assertions={"traceability": True})]
        sel = resolve_selection(
            workspace={
                "require": ["traceability is true"],
                "prefer": [{"trusted": 5}],
                "on_conflict": "preserve-and-attribute",
            },
            run={"relax": ["traceability is true"]},
        )
        out = ground(
            pool, sel, datasets={"d": (fact("s", "c", tier=TIER_INFERRED),)}
        )
        assert out.facts[0].publishable is False


# --- freshness: policies + clauses against the injected clock -------------------------------------


class TestFreshness:
    def test_explicit_clause_filters_by_window(self):
        pool = [inst("x-a", "d")]
        sel = resolve_selection(workspace={"require": ["freshness < 6mo"]})
        out = ground(
            pool,
            sel,
            datasets={
                "d": (
                    fact("s-new", "c1", as_of=datetime.date(2026, 5, 1)),
                    fact("s-old", "c2", as_of=datetime.date(2025, 6, 1)),
                )
            },
        )
        assert [f.subject for f in out.facts] == ["s-new"]

    def test_clock_is_injected_not_ambient(self):
        pool = [inst("x-a", "d")]
        sel = resolve_selection(workspace={"require": ["freshness < 6mo"]})
        datasets = {"d": (fact("s", "c", as_of=datetime.date(2025, 6, 1)),)}
        assert ground(pool, sel, datasets=datasets).status == STATUS_BLOCK
        earlier = ground(pool, sel, datasets=datasets, now=datetime.date(2025, 8, 1))
        assert earlier.status == STATUS_OK  # same fact, different injected clock

    def test_unknown_as_of_fails_the_hard_gate(self):
        pool = [inst("x-a", "d")]
        sel = resolve_selection(workspace={"require": ["freshness < 24mo"]})
        out = ground(pool, sel, datasets={"d": (fact("s", "c", as_of=None),)})
        assert out.status == STATUS_BLOCK
        assert out.context["clause"] == "freshness < 24mo"

    def test_kind_policy_filters_and_blocks_naming_the_policy(self):
        # research-notes-style kind policy: 12mo (§6.2 filter + weight input).
        pool = [inst("x-notes", "d", content_kind="research-notes", kind_defaults=NOTES_KIND)]
        out = ground(
            pool,
            resolve_selection(),
            datasets={
                "d": (
                    fact("s-new", "c1", as_of=datetime.date(2026, 5, 1), tier=TIER_INFERRED),
                    fact("s-old", "c2", as_of=datetime.date(2024, 1, 1), tier=TIER_INFERRED),
                )
            },
        )
        assert [f.subject for f in out.facts] == ["s-new"]
        blocked = ground(
            pool,
            resolve_selection(),
            datasets={"d": (fact("s-old", "c2", as_of=datetime.date(2024, 1, 1)),)},
        )
        assert blocked.status == STATUS_BLOCK
        assert blocked.context["clause"] == "content-kinds/research-notes.freshness < 12mo"
        assert blocked.context["set_at"] == "config"

    def test_instance_assertion_wins_over_kind_policy(self):
        # the more-specific instance policy (6mo) tightens over the kind's 12mo
        pool = [
            inst(
                "x-notes",
                "d",
                content_kind="research-notes",
                kind_defaults=NOTES_KIND,
                assertions={"freshness": "6mo"},
            )
        ]
        eight_months_old = fact("s", "c", as_of=datetime.date(2025, 11, 1))
        blocked = ground(pool, resolve_selection(), datasets={"d": (eight_months_old,)})
        assert blocked.status == STATUS_BLOCK
        assert blocked.context["clause"] == "sources/x-notes.freshness < 6mo"

    def test_policy_block_carries_a_policy_remediation_action(self):
        # RV-2 / §21.7 machine-token honesty: a freshness POLICY is config — the M3
        # relax surface cannot name it, so its block must NOT divert callers to
        # `relax-clause`. The hint names the config home; grammar-clause blocks keep
        # `relax-clause`.
        stale = fact("s-old", "c", as_of=datetime.date(2024, 1, 1))
        kind_pool = [
            inst("x-notes", "d", content_kind="research-notes", kind_defaults=NOTES_KIND)
        ]
        policy_block = ground(kind_pool, resolve_selection(), datasets={"d": (stale,)})
        assert policy_block.context["set_at"] == "config"
        assert policy_block.remediation["action"] == "adjust-freshness-policy"
        assert "content-kinds/research-notes" in policy_block.remediation["hint"]

        asserted_pool = [
            inst(
                "x-notes",
                "d",
                content_kind="research-notes",
                kind_defaults=NOTES_KIND,
                assertions={"freshness": "6mo"},
            )
        ]
        asserted_block = ground(asserted_pool, resolve_selection(), datasets={"d": (stale,)})
        assert asserted_block.remediation["action"] == "adjust-freshness-policy"
        assert "sources/x-notes" in asserted_block.remediation["hint"]

        clause_sel = resolve_selection(workspace={"require": ["freshness < 12mo"]})
        clause_block = ground([inst("x-a", "d")], clause_sel, datasets={"d": (stale,)})
        assert clause_block.remediation["action"] == "relax-clause"
        assert policy_block.remediation["action"] != clause_block.remediation["action"]


# --- the nine characteristics consumed from the mock (§6.2; G6) -----------------------------------


class TestScoresConsumed:
    def test_effective_score_view_carries_all_nine(self):
        pool = [
            inst(
                "x-a",
                "d",
                content_kind="merged-code",
                trusted=4,
                independence="independent",
                primariness="primary",
                kind_defaults=RECORD_KIND,
            )
        ]
        out = ground(pool, resolve_selection(), datasets={"d": (fact("s", "c"),)})
        scores = out.facts[0].scores
        assert scores["trusted"] == 4
        assert scores["independence"] == "independent"
        assert scores["primariness"] == "primary"
        assert scores["authoritative"] == 4  # kind default (§6.1 SM5)
        assert scores["opinionated"] == 1
        assert scores["review_status"] == "reviewed"
        assert scores["freshness"] == datetime.date(2026, 5, 1)  # = as_of
        assert scores["corroboration"] == 0
        assert scores["traceability"] is True
        assert scores["content-kind"] == "merged-code"

    def test_review_status_degrades_to_unknown(self):
        # G6: no kind bundle, no refinement → the `unknown` floor is the designed
        # degradation; a reviewed-only require then excludes those facts.
        pool = [inst("x-a", "d")]
        out = ground(pool, resolve_selection(), datasets={"d": (fact("s", "c"),)})
        assert out.facts[0].scores["review_status"] == "unknown"
        sel = resolve_selection(workspace={"require": ["review_status == reviewed"]})
        blocked = ground(pool, sel, datasets={"d": (fact("s", "c"),)})
        assert blocked.status == STATUS_BLOCK
        assert blocked.context["clause"] == "review_status == reviewed"

    def test_per_fact_refinement_beats_kind_default(self):
        pool = [inst("x-a", "d", content_kind="merged-code", kind_defaults=RECORD_KIND)]
        sel = resolve_selection(
            workspace={"require": ["review_status == formally-vetted"]}
        )
        out = ground(
            pool,
            sel,
            datasets={
                "d": (
                    fact("s1", "c1", refinements={"review_status": "formally-vetted"}),
                    fact("s2", "c2"),  # rides the kind default: reviewed
                )
            },
        )
        assert [f.subject for f in out.facts] == ["s1"]

    def test_each_instance_score_filters_the_pool(self):
        pool = [
            inst("x-weak", "d1", trusted=2, independence="first-party",
                 primariness="tertiary"),
            inst("x-strong", "d2", trusted=5, independence="independent",
                 primariness="primary"),
        ]
        datasets = {"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        for clause in ("trusted >= 4", "independence == independent",
                       "primariness == primary", "content-kind == general"):
            sel = resolve_selection(workspace={"require": [clause]})
            out = ground(pool, sel, datasets=datasets)
            assert out.status == STATUS_OK, clause
            if clause != "content-kind == general":
                assert [f.instance_id for f in out.facts] == ["x-strong"], clause

    def test_fact_scope_kind_scores_filter_facts(self):
        pool = [
            inst("x-notes", "d1", content_kind="research-notes", kind_defaults=NOTES_KIND),
            inst("x-record", "d2", content_kind="merged-code", kind_defaults=RECORD_KIND),
        ]
        datasets = {"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)}
        sel = resolve_selection(workspace={"require": ["authoritative >= 4"]})
        out = ground(pool, sel, datasets=datasets)
        assert [f.instance_id for f in out.facts] == ["x-record"]
        sel = resolve_selection(workspace={"require": ["opinionated < 3"]})
        out = ground(pool, sel, datasets=datasets)
        assert [f.instance_id for f in out.facts] == ["x-record"]


# --- on_conflict: every shipped strategy (§6.3 SM4) -----------------------------------------------


def conflict_pool(*, opinion_trusted: int = 3, factual_trusted: int = 3):
    """A factual-vs-opinion conflict on one subject (the SM4 fixture seed)."""
    pool = [
        inst("x-record", "rec", content_kind="merged-code", trusted=factual_trusted,
             kind_defaults=RECORD_KIND),
        inst("x-notes", "op", content_kind="research-notes", trusted=opinion_trusted,
             kind_defaults=NOTES_KIND),
    ]
    datasets = {
        "rec": (fact("cache.size", "The cache holds 512 entries."),),
        "op": (fact("cache.size", "The cache holds 1024 entries.", tier=TIER_INFERRED),),
    }
    return pool, datasets


def factual_conflict_pool():
    """A factual-vs-factual conflict (two record kinds disagree)."""
    pool = [
        inst("x-rec-a", "a", content_kind="merged-code", trusted=4, kind_defaults=RECORD_KIND),
        inst("x-rec-b", "b", content_kind="merged-code", trusted=2, kind_defaults=RECORD_KIND),
    ]
    datasets = {
        "a": (fact("timeout", "The timeout is 30 seconds."),),
        "b": (fact("timeout", "The timeout is 60 seconds."),),
    }
    return pool, datasets


class TestOnConflict:
    def test_shipped_strategy_set(self):
        assert set(conflict_strategies()) >= {
            "downgrade-AMBIGUOUS",
            "preserve-and-attribute",
            "priority-wins",
            "surface-contradictions",
        }

    def test_default_downgrades_factual_vs_factual(self):
        pool, datasets = factual_conflict_pool()
        out = ground(pool, resolve_selection(), datasets=datasets)
        assert all(f.tier == TIER_AMBIGUOUS for f in out.facts)
        assert all(f.conflict is not None and f.conflict.role == "downgraded" for f in out.facts)
        assert out.code == CODE_LOW_CONFIDENCE_GROUNDING  # nothing publishable remains

    def test_default_factual_beats_opinion(self):
        # the SM4 required property, in the DEFAULT strategy
        pool, datasets = conflict_pool()
        out = ground(pool, resolve_selection(), datasets=datasets)
        by_instance = {f.instance_id: f for f in out.facts}
        assert by_instance["x-record"].tier == TIER_EXTRACTED  # kept
        assert by_instance["x-record"].conflict.role == "kept"
        assert by_instance["x-notes"].tier == TIER_AMBIGUOUS  # the opinion downgraded
        assert by_instance["x-notes"].conflict.strategy == "downgrade-AMBIGUOUS"

    def test_preserve_and_attribute_keeps_both(self):
        pool, datasets = conflict_pool()
        sel = resolve_selection(workspace={"on_conflict": "preserve-and-attribute"})
        out = ground(pool, sel, datasets=datasets)
        assert all(f.attributed for f in out.facts)
        assert all(f.conflict.role == "attributed" for f in out.facts)
        assert {f.tier for f in out.facts} == {TIER_EXTRACTED, TIER_INFERRED}  # untouched

    def test_priority_wins_factual_beats_opinion_regardless_of_weights(self):
        # the opinion side gets every weight lever — the factual claim still wins
        pool, datasets = conflict_pool(opinion_trusted=5, factual_trusted=2)
        sel = resolve_selection(workspace={"on_conflict": "priority-wins"})
        out = ground(pool, sel, datasets=datasets)
        by_instance = {f.instance_id: f for f in out.facts}
        assert by_instance["x-record"].conflict.role == "kept"
        assert by_instance["x-notes"].tier == TIER_AMBIGUOUS

    def test_priority_wins_weight_driven_between_factual_sides(self):
        pool, datasets = factual_conflict_pool()
        sel = resolve_selection(workspace={"on_conflict": "priority-wins"})
        out = ground(pool, sel, datasets=datasets)
        by_instance = {f.instance_id: f for f in out.facts}
        assert by_instance["x-rec-a"].conflict.role == "kept"  # trusted 4 beats 2
        assert by_instance["x-rec-b"].tier == TIER_AMBIGUOUS

    def test_surface_contradictions_emits_the_contradiction(self):
        # §6.3: the disagreement IS the content — debunk / correct-the-record material.
        pool, datasets = conflict_pool()
        sel = resolve_selection(workspace={"on_conflict": "surface-contradictions"})
        out = ground(pool, sel, datasets=datasets)
        assert len(out.contradictions) == 1
        contradiction = out.contradictions[0]
        assert contradiction.subject == "cache.size"
        assert contradiction.factual_claim == "The cache holds 512 entries."
        assert contradiction.factual_instances == ("x-record",)
        assert contradiction.opinion_claim == "The cache holds 1024 entries."
        assert contradiction.opinion_instances == ("x-notes",)
        by_instance = {f.instance_id: f for f in out.facts}
        assert by_instance["x-record"].conflict.role == "kept"
        assert by_instance["x-record"].tier == TIER_EXTRACTED
        assert by_instance["x-notes"].conflict.role == "attributed"

    def test_surface_contradictions_falls_back_without_a_lone_factual_side(self):
        pool, datasets = factual_conflict_pool()
        sel = resolve_selection(workspace={"on_conflict": "surface-contradictions"})
        out = ground(pool, sel, datasets=datasets)
        assert out.contradictions == ()
        assert all(f.tier == TIER_AMBIGUOUS for f in out.facts)

    def test_agreement_is_never_a_conflict(self):
        pool = [inst("x-a", "da"), inst("x-b", "db")]
        same = fact("s", "the same claim")
        out = ground(pool, resolve_selection(), datasets={"da": (same,), "db": (same,)})
        assert all(f.conflict is None for f in out.facts)

    def test_unknown_strategy_is_loud(self):
        pool, datasets = conflict_pool()
        sel = resolve_selection(run={"on_conflict": "sky-hook"})
        with pytest.raises(UnknownConflictStrategyError, match="sky-hook"):
            ground(pool, sel, datasets=datasets)

    def test_strategies_are_extensible_one_registration(self):
        # SM4: "more addable, goal-driven, one-file-add" — one call registers.
        def keep_everything(group, ctx):
            for facts in group.sides.values():
                for wf in facts:
                    wf.attributed = True

        register_conflict_strategy("keep-everything-test", keep_everything)
        assert "keep-everything-test" in conflict_strategies()
        pool, datasets = conflict_pool()
        sel = resolve_selection(run={"on_conflict": "keep-everything-test"})
        out = ground(pool, sel, datasets=datasets)
        assert all(f.attributed for f in out.facts)
        with pytest.raises(GroundingError, match="already registered"):
            register_conflict_strategy("downgrade-AMBIGUOUS", keep_everything)


# --- PA-9a: user-asserted scores — stamped; one-time divergence advisory --------------------------


class TestUserAssertions:
    def test_assertion_wins_selection_and_warns_once(self):
        pool = [inst("x-a", "d", assertions={"corroboration": 4})]
        sel = resolve_selection(workspace={"require": ["corroboration >= 2"]})
        out = ground(
            pool, sel, datasets={"d": (fact("s1", "c1"), fact("s2", "c2"))}
        )
        # the assertion rides as authoritative config (§3.1): the require passes
        assert out.status == STATUS_OK
        record = next(a for a in out.assertions if a.score == "corroboration")
        assert (record.asserted, record.computed, record.divergent) == (4, 0, True)
        divergence_warnings = [
            w for w in out.warnings if w.key.startswith("user-assertion-divergence:")
        ]
        assert len(divergence_warnings) == 1  # two facts diverge — ONE advisory
        assert "advisory" in divergence_warnings[0].message

    def test_traceability_assertion_cannot_conjure_an_anchor(self):
        pool = [inst("x-a", "d", assertions={"traceability": True})]
        sel = resolve_selection(workspace={"require": ["traceability is true"]})
        out = ground(pool, sel, datasets={"d": (fact("s", "c", anchored=False),)})
        assert out.status == STATUS_OK  # selection honors the assertion…
        assert out.facts[0].citable is False  # …citability stays the computed truth (SM9)
        record = next(a for a in out.assertions if a.score == "traceability")
        assert record.divergent is True

    def test_non_divergent_assertion_stamped_without_warning(self):
        pool = [inst("x-a", "d", assertions={"authoritative": 4})]
        out = ground(pool, resolve_selection(), datasets={"d": (fact("s", "c"),)})
        record = next(a for a in out.assertions if a.score == "authoritative")
        assert (record.computed, record.divergent) == (None, False)  # nothing computed
        assert not [w for w in out.warnings if "divergence" in w.key]

    def test_refined_slider_divergence(self):
        pool = [inst("x-a", "d", assertions={"authoritative": 5})]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d": (fact("s", "c", refinements={"authoritative": 1}),)},
        )
        record = next(a for a in out.assertions if a.score == "authoritative")
        assert record.divergent is True
        # the assertion still WINS the effective view (§3.1)
        assert out.facts[0].scores["authoritative"] == 5

    def test_one_time_across_a_batch(self):
        pool = [inst("x-a", "d", assertions={"corroboration": 4})]
        requests = [
            GroundingRequest(item="one", query="", selection=resolve_selection()),
            GroundingRequest(item="two", query="", selection=resolve_selection()),
        ]
        outcomes = ground_batch(
            requests,
            pool=pool,
            adapters={"mock": MockAdapter({"d": (fact("s", "c"),)})},
            now=NOW,
        )
        keys = [
            w.key
            for o in outcomes
            for w in o.warnings
            if w.key.startswith("user-assertion-divergence:")
        ]
        assert len(keys) == 1  # exactly once — shared one-time scope (§6.2)


# --- adapter wiring & refinement discipline -------------------------------------------------------


class TestAdapterWiring:
    def test_unknown_adapter_fails_loudly(self):
        pool = [inst("x-a", "d", adapter="graphify")]  # not wired until step 18
        with pytest.raises(AdapterError, match="unknown adapter 'graphify'"):
            ground(pool, resolve_selection(), datasets={"d": ()})

    def test_refinement_outside_the_refinable_set_is_loud(self):
        pool = [inst("x-a", "d")]
        with pytest.raises(RefinementError, match="corroboration"):
            ground(
                pool,
                resolve_selection(),
                datasets={"d": (fact("s", "c", refinements={"corroboration": 3}),)},
            )

    def test_refinement_values_validated(self):
        pool = [inst("x-a", "d")]
        with pytest.raises(RefinementError, match="1-5"):
            ground(
                pool,
                resolve_selection(),
                datasets={"d": (fact("s", "c", refinements={"authoritative": 9}),)},
            )
        with pytest.raises(RefinementError, match="review_status"):
            ground(
                pool,
                resolve_selection(),
                datasets={"d": (fact("s", "c", refinements={"review_status": "vetted"}),)},
            )

    def test_per_fact_commit_and_commit_map(self):
        pool = [inst("x-a", "d1"), inst("x-b", "d2")]
        out = ground(
            pool,
            resolve_selection(),
            datasets={"d1": (fact("s1", "c1"),), "d2": (fact("s2", "c2"),)},
        )
        assert out.commit_map == {
            "x-a": synthetic_commit("d1"),
            "x-b": synthetic_commit("d2"),
        }
        for grounded in out.facts:
            assert grounded.commit == out.commit_map[grounded.instance_id]
            assert grounded.adapter == "mock"


# --- end to end: shipped registries + the shipped convince goal -----------------------------------


BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

TOPIC_ENTRY = (
    "---\nid: x-sample-topic\nprovenance: instance\nschema_version: 1\n"
    "why: A generic fixture subject.\n---\n\nSample topic body.\n"
)

RECIPE_ENTRY = (
    "---\nid: x-grounded-post\nprovenance: instance\nschema_version: 1\n"
    "topic: x-sample-topic\ngoals: [convince]\n---\n\nFixture recipe.\n"
)

WORKSPACE_DEFAULTS = """\
source_selection:
  require:
    - freshness < 24mo
  prefer:
    - trusted: +1
"""

ALPHA_SOURCE = """\
---
id: x-alpha-record
provenance: instance
schema_version: 1
adapter: mock
connection:
  dataset: alpha
content_kind: merged-code
trusted: 4
independence: first-party
primariness: primary
---

Fixture source: the project record (synthetic).
"""

DELTA_SOURCE = """\
---
id: x-delta-notes
provenance: instance
schema_version: 1
adapter: mock
connection:
  dataset: delta
content_kind: research-notes
independence: independent
---

Fixture source: working notes (synthetic).
"""


@pytest.fixture()
def e2e_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    for name in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, name)
        if src.is_dir():
            dst = registry_dir(root, name)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    ws = root / "users" / USER / "workspaces" / WS
    (ws / "topics").mkdir(parents=True)
    (ws / "topics" / "x-sample-topic.md").write_text(TOPIC_ENTRY, encoding="utf-8")
    (ws / "recipes").mkdir()
    (ws / "recipes" / "x-grounded-post.md").write_text(RECIPE_ENTRY, encoding="utf-8")
    (ws / "sources").mkdir()
    (ws / "sources" / "x-alpha-record.md").write_text(ALPHA_SOURCE, encoding="utf-8")
    (ws / "sources" / "x-delta-notes.md").write_text(DELTA_SOURCE, encoding="utf-8")
    (ws / "defaults.yaml").write_text(WORKSPACE_DEFAULTS, encoding="utf-8")
    return root


class TestEndToEnd:
    def test_build_instance_resolves_kind_bundles_via_m1(self, e2e_root: Path):
        env = CascadeEnv(e2e_root, user=USER, workspace=WS)
        alpha = build_instance(env.resolver, "x-alpha-record")
        assert alpha.adapter == "mock"
        assert alpha.content_kind == "merged-code"
        assert alpha.kind_defaults["authoritative"] == 4  # the shipped kind entry
        assert alpha.kind_defaults["review_status"] == "reviewed"
        assert alpha.trusted == 4 and alpha.primariness == "primary"
        delta = build_instance(env.resolver, "x-delta-notes")
        assert delta.kind_defaults["freshness"] == "12mo"  # shipped research-notes policy
        assert delta.independence == "independent"

    def test_unknown_content_kind_is_loud(self, e2e_root: Path):
        bad = ALPHA_SOURCE.replace("id: x-alpha-record", "id: x-bad-kind").replace(
            "content_kind: merged-code", "content_kind: no-such-kind"
        )
        (e2e_root / "users" / USER / "workspaces" / WS / "sources" / "x-bad-kind.md").write_text(
            bad, encoding="utf-8"
        )
        env = CascadeEnv(e2e_root, user=USER, workspace=WS)
        with pytest.raises(DanglingRefError, match="no-such-kind"):
            build_instance(env.resolver, "x-bad-kind")

    def test_convince_clauses_resolve_and_ground_end_to_end(self, e2e_root: Path):
        env = CascadeEnv(e2e_root, user=USER, workspace=WS)
        resolution = resolve_compose(env, RunSelection(recipe="x-grounded-post"))
        m3_inputs = resolution.m3_inputs

        # the four-layer fold over EXACTLY the cascade's M3 hand-off (§12.1)
        selection = resolve_selection(
            workspace=m3_inputs.workspace_baseline, goals=list(m3_inputs.goal_implied)
        )
        assert [c.canonical() for c in selection.require] == [
            "freshness < 24mo",  # workspace layer (T10 defaults.yaml)
            "traceability is true",  # the shipped convince entry (§6.3's own example)
        ]
        assert selection.require_origins["traceability is true"] == "goal:convince"
        weights = {p.term.key: (p.weight, p.origin) for p in selection.prefer}
        assert weights == {
            "trusted": (1, "workspace"),
            "authoritative": (2, "goal:convince"),
        }

        pool = build_pool(env.resolver, ["x-alpha-record", "x-delta-notes"])
        datasets = {
            "alpha": (
                fact("widget.timeout", "The timeout is 30 seconds.",
                     as_of=datetime.date(2026, 5, 1)),
                fact("widget.retries", "The client retries three times.",
                     as_of=datetime.date(2026, 5, 1), anchored=False),
            ),
            "delta": (
                fact("widget.timeout", "The timeout is 30 seconds.",
                     tier=TIER_INFERRED, as_of=datetime.date(2026, 6, 1)),
            ),
        }
        out = ground_item(
            item="x-grounded-post",
            query="",
            pool=pool,
            selection=selection,
            adapters={"mock": MockAdapter(datasets)},
            now=NOW,
            workspace=WS,
        )
        assert out.status == STATUS_OK
        assert out.workspace == WS
        # convince's traceability require dropped the anchorless fact
        assert {(f.instance_id, f.subject) for f in out.facts} == {
            ("x-alpha-record", "widget.timeout"),
            ("x-delta-notes", "widget.timeout"),
        }
        # agreement across first-party + independent: corroborated AND tier-upgraded
        delta_fact = next(f for f in out.facts if f.instance_id == "x-delta-notes")
        assert delta_fact.corroboration == 1
        assert (delta_fact.base_tier, delta_fact.tier) == (TIER_INFERRED, TIER_EXTRACTED)
        # prefer authoritative +2 (goal) + trusted +1 (workspace) rank the record first
        assert out.facts[0].instance_id == "x-alpha-record"
        assert out.facts[0].weight == 4 * 2 + 4 * 1
        # provenance for the §15 ledger: instance + commit per fact, workspace on top
        assert out.commit_map["x-alpha-record"] == synthetic_commit("alpha")
        assert all(f.commit == out.commit_map[f.instance_id] for f in out.facts)


# --- DR-6 attestation carrier on GroundedFact (§15 RI3): absent-by-default + pass-through ---


def grounded_fact(**overrides) -> GroundedFact:
    """One minimal `GroundedFact` for the carrier tests — the resolver walk itself is exercised
    end-to-end elsewhere; here we pin only the DR-6 `attestation` carrier field."""
    base = dict(
        subject="parser",
        claim="runs in linear time",
        instance_id="acme-graph",
        adapter="graphify",
        commit="c0ffee",
        base_tier=TIER_EXTRACTED,
        tier=TIER_EXTRACTED,
        corroboration=0,
        agreeing_instances=("acme-graph",),
        anchors=(Anchor("file-line", "src/parser.py:42"),),
        citable=True,
        as_of=datetime.date(2026, 6, 1),
        scores={"trusted": 5},
        weight=1.0,
    )
    base.update(overrides)
    return GroundedFact(**base)


class TestAttestationCarrier:
    def test_attestation_defaults_to_none(self):
        # Absent-by-default: a scenario-1 fact (in-pool primary) carries no attestation.
        assert grounded_fact().attestation is None

    def test_grounded_fact_carries_attestation_when_set(self):
        att = {
            "primary": {"type": "article-journal", "title": "On Parsing"},
            "anchor": "file-line:docs/refs.md:5",
            "relation": "wasQuotedFrom",
        }
        assert grounded_fact(attestation=att).attestation == att

    def test_resolver_facts_carry_none_attestation(self):
        # The resolver does not SET attestation in this carrier commit (no scenario-2 detection):
        # every fact from a real walk carries the None default (absent-by-default pass-through).
        out = ground([inst("x-a", "d")], datasets={"d": (fact("s", "c"),)})
        assert out.facts  # the walk produced facts
        assert all(f.attestation is None for f in out.facts)


# --- §6.1 reuse_rights / republishable (the publish-vs-lead RIGHTS gate) --------------------


def _published(out):
    """The driver seam (`pipeline/driver.py`): the two ORTHOGONAL publish gates ANDed — the
    §6.5 confidence floor (`publishable_facts`) AND the §6.1 rights gate (`republishable`)."""
    return tuple(f for f in out.publishable_facts if f.republishable)


class TestReuseRights:
    """The §6.1 reuse_rights dimension + the computed `republishable` gate: a fact publishes
    only when it clears BOTH the §6.5 confidence floor AND the rights threshold. The floor
    `full` keeps today's published set byte-identical (backward compat); a lead-only/
    internal-only/forbidden kind holds even an EXTRACTED fact back as a LEAD."""

    # -- the ordinal + its schema pin -------------------------------------------------------

    def test_ordinal_is_ordered_low_to_high(self):
        assert REUSE_RIGHTS == (
            "forbidden", "internal-only", "lead-only", "attribution", "full"
        )
        ranks = [reuse_rights_rank(v) for v in REUSE_RIGHTS]
        assert ranks == [0, 1, 2, 3, 4] == sorted(ranks)
        assert REUSE_RIGHTS_FLOOR == "full"
        assert REUSE_RIGHTS_PUBLISH_THRESHOLD == "attribution"

    def test_schema_enum_and_floor_match_the_ordinal(self):
        # The content-kinds schema declares the SAME closed member set + the `full` floor;
        # the RANK order of record is the grounding tuple (the schema list is documentation).
        kinds = load_schema(REPO_ROOT / "content-kinds" / "_schema.yaml")
        spec = kinds.attributes["reuse_rights"]
        assert set(spec.type.values) == set(REUSE_RIGHTS)
        assert spec.default == REUSE_RIGHTS_FLOOR == "full"

    def test_unknown_value_is_a_loud_typed_error(self):
        # The ordinal fails CLOSED (typed) on an unknown value — never a silent pass/fail.
        with pytest.raises(ReuseRightsError, match="unknown reuse_rights value"):
            reuse_rights_rank("public-domain")
        with pytest.raises(ReuseRightsError, match="unknown reuse_rights value"):
            bool(grounded_fact(reuse_rights="public-domain").republishable)

    # -- the property: threshold + orthogonality to confidence ------------------------------

    def test_property_gates_exactly_at_attribution(self):
        assert grounded_fact(reuse_rights="full").republishable is True
        assert grounded_fact(reuse_rights="attribution").republishable is True
        assert grounded_fact(reuse_rights="lead-only").republishable is False
        assert grounded_fact(reuse_rights="internal-only").republishable is False
        assert grounded_fact(reuse_rights="forbidden").republishable is False

    def test_floor_default_is_full_and_republishable(self):
        # A fact built WITHOUT reuse_rights rides the `full` floor -> republishable (the
        # backward-compat default: absence of rights info means full reuse).
        f = grounded_fact()
        assert f.reuse_rights == REUSE_RIGHTS_FLOOR == "full"
        assert f.republishable is True

    def test_rights_gate_is_orthogonal_to_the_confidence_gate(self):
        # publishable is tier-ONLY in every rights case; republishable is rights-ONLY in
        # every tier case — the two gates never touch (SM9-style orthogonality).
        for rights in REUSE_RIGHTS:
            ext = grounded_fact(reuse_rights=rights, tier=TIER_EXTRACTED, base_tier=TIER_EXTRACTED)
            inf = grounded_fact(reuse_rights=rights, tier=TIER_INFERRED, base_tier=TIER_INFERRED)
            assert ext.publishable is True and inf.publishable is False  # tier-only
            expected = reuse_rights_rank(rights) >= reuse_rights_rank("attribution")
            assert ext.republishable == inf.republishable == expected  # rights-only

    # -- the score/selection grammar invariant: reuse_rights is NOT selectable --------------

    def test_reuse_rights_is_not_in_the_selection_grammar(self):
        assert "reuse_rights" not in SCORES
        assert "reuse_rights" not in SELECTABLE_CHARACTERISTICS
        assert "reuse_rights" not in ASSERTABLE_SCORES
        # a clause naming it is refused as an unknown score (never a legal `prefer`/`require`).
        with pytest.raises(UnknownScoreError):
            parse_clause("reuse_rights >= attribution")

    # -- resolver-level: the gate over a real §6.3 walk -------------------------------------

    def test_resolver_attaches_reuse_rights_from_the_content_kind(self):
        # Default (no kind reuse_rights) rides the `full` floor via `kind_value`.
        out = ground([inst("x-a", "d")], datasets={"d": (fact("s", "c"),)})
        assert out.facts[0].reuse_rights == "full"
        # An explicit kind reuse_rights (the extends/override path) rides through unchanged.
        lead = ground(
            [inst("x-b", "d", kind_defaults={"reuse_rights": "lead-only"})],
            datasets={"d": (fact("s", "c"),)},
        )
        assert lead.facts[0].reuse_rights == "lead-only"

    def test_backward_compat_published_set_is_byte_identical(self):
        # HEADLINE BACKWARD-COMPAT PROOF: with every kind at the `full` floor, the rights
        # filter is a NO-OP — the driver's published set equals `publishable_facts` EXACTLY
        # (same facts, same order), so today's output is unchanged by this dimension.
        pool = [
            inst("x-a", "d1", content_kind="merged-code", kind_defaults=RECORD_KIND),
            inst("x-b", "d2"),  # general kind -> `full` floor
        ]
        out = ground(
            pool,
            datasets={
                "d1": (fact("s1", "c1"), fact("s2", "c2")),
                "d2": (fact("s3", "c3", tier=TIER_INFERRED),),  # a lead by CONFIDENCE
            },
        )
        assert all(f.republishable for f in out.facts)  # full floor everywhere
        assert out.publishable_facts  # the proof is meaningful (non-empty published set)
        assert _published(out) == out.publishable_facts  # BYTE-IDENTICAL

    def test_lead_only_kind_holds_an_extracted_fact_back_as_a_lead(self):
        # RIGHTS MATRIX: a lead-only kind's EXTRACTED fact stays publishable (confidence is
        # UNCHANGED) yet is NOT republishable -> excluded from the published set (a lead).
        out = ground(
            [inst("x-a", "d", kind_defaults={"reuse_rights": "lead-only"})],
            datasets={"d": (fact("s", "c"),)},  # EXTRACTED + anchored
        )
        f = out.facts[0]
        assert f.tier == TIER_EXTRACTED and f.publishable is True  # confidence untouched
        assert f.republishable is False
        assert f in out.publishable_facts  # the §6.5 floor still keeps it
        assert _published(out) == ()  # the §6.1 rights gate holds it back

    def test_forbidden_and_internal_only_never_publish_even_at_extracted(self):
        for rights in ("forbidden", "internal-only", "lead-only"):
            out = ground(
                [inst("x-a", "d", kind_defaults={"reuse_rights": rights})],
                datasets={"d": (fact("s", "c"),)},
            )
            assert out.facts[0].publishable is True  # EXTRACTED — confidence unchanged
            assert _published(out) == ()  # < attribution -> never a published fact

    def test_attribution_and_full_kinds_publish(self):
        for rights in ("attribution", "full"):
            out = ground(
                [inst("x-a", "d", kind_defaults={"reuse_rights": rights})],
                datasets={"d": (fact("s", "c"),)},
            )
            # every fact EXTRACTED + republishable -> the published set is the full fact set.
            assert _published(out) == out.publishable_facts == out.facts
