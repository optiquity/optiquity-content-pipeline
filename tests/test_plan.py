"""Step-19 tests — `pipeline/plan.py`: plan resolution + `plan_hash` (design §8, §21.6, §22.2).

Runs against the REAL shipped registries (copied into `tmp_path` — REC-3: the repo is
read-only toward this suite) plus tmp instance/workspace surfaces. Covers: single
selection → single artifact; content + rendering fanout cross products (id-distinct,
exactly-once — PC2); the real-registry probe (2 topics × tech-journalist ×
how-to-documentation × [corporate-website, medium-post] × plain-text → 4 deliverables);
plan determinism (same inputs → identical `plan_hash` across processes and hash seeds;
any input change → a different hash; canonical under request permutation); the §21.8
clause-only-difference conformance test (M3 is not an identity input — step-06
disposition 6); the emergent allow-list (no pairing veto — advisory warn only, catalog
sans folio triggers); goal-set overload (warns, never blocks); the fanout-collapse
exactly-once dedupe; compose-only plans + the step-16 RV-1 inert-platform advisory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.canonical import canonical_json_str, digest_full
from pipeline.cascade import CascadeEnv, RunSelection, resolve_compose
from pipeline.fanout import ContentCombination, FanoutError, SelectionRequest
from pipeline.ids import PreimageError, parse_id
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m1 import UnknownEntryError
from pipeline.outline import outline_digest
from pipeline.plan import Plan, plan_payload, resolve_plan

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"

#: The CA8 mandatory globals (all shipped framework ids — generic values only).
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

#: §12.6: the brand-authoritative hard-lock variant (the fanout-collapse fixture).
BRAND_C_L2 = "voice:\n  entry: clear-explainer\n  authoritative: c\nlanguage: en\noutput_type: md\n"

#: Test-only set attribute appended to a COPIED voices schema (the §7.2 "a new schema
#: attribute at default churns no id" acceptance probe). Appending without a version
#: bump is safe: definition_version 1 == every shipped stamp.
VOICES_SCHEMA_APPEND = """\
  step19_probe:
    type: text
    default: ""
    definition: Test-only additive attribute at its default (step-19 churn probe).
    definition_version: 1
"""

TOPIC_BODY = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"

SUBSET = ("x-repo",)
COMMITS = {"x-repo": "c0ffee0123ab"}


def build_root(
    tmp_path: Path,
    *,
    l2: str = BASE_L2,
    l3: str | None = None,
    schema_append: str | None = None,
    name: str = "root",
) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = REPO_ROOT / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    if schema_append is not None:
        schema_path = root / "voices" / "_schema.yaml"
        schema_path.write_text(
            schema_path.read_text(encoding="utf-8") + schema_append, encoding="utf-8"
        )
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(l2, encoding="utf-8")
    topics = root / "workspaces" / WS / "topics"
    topics.mkdir(parents=True)
    for tid, why in (("x-t-alpha", "First fixture subject."), ("x-t-beta", "Second one.")):
        (topics / f"{tid}.md").write_text(TOPIC_BODY.format(tid=tid, why=why), encoding="utf-8")
    if l3 is not None:
        (root / "workspaces" / WS / "defaults.yaml").write_text(l3, encoding="utf-8")
    return root


def write_entry(root: Path, collection: str, entry_id: str, frontmatter: str = "") -> Path:
    dirpath = root / "workspaces" / WS / collection
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / f"{entry_id}.md"
    path.write_text(
        f"---\nid: {entry_id}\nprovenance: instance\nschema_version: 1\n{frontmatter}---\n\n"
        "Test fixture body.\n",
        encoding="utf-8",
    )
    return path


def make_env(root: Path, **kwargs) -> CascadeEnv:
    return CascadeEnv(root, workspace=WS, **kwargs)


def plan_for(root: Path, request: SelectionRequest, **kwargs) -> Plan:
    return resolve_plan(
        make_env(root), request, source_subset=SUBSET, source_commit=COMMITS, **kwargs
    )


def warning_keys(plan: Plan) -> list[str]:
    return [w.key for w in plan.warnings]


# ------------------------------------------------------------------------------------
# Single selection → single artifact; id shapes (§8, §7.4)
# ------------------------------------------------------------------------------------


def test_single_selection_yields_one_artifact_one_deliverable(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"]),
    )
    (item,) = plan.items
    assert parse_id(item.artifact_id).level == "artifact"
    assert item.topic == "x-t-alpha"
    assert item.persona == "technical-evaluator"  # the recipe's binding (§8)
    assert item.goals == ("explain",)
    (deliverable,) = item.deliverables
    # Unselected slots resolved by the cascade: language en (L2), output-type md
    # (github's weak default == the L2 value), presentation plain (PD7 floor).
    assert deliverable.deliverable_id == f"{item.artifact_id}.github.en.md.plain"
    assert deliverable.fitted_id == f"{item.artifact_id}.github.en"
    assert parse_id(deliverable.deliverable_id).level == "deliverable"
    assert deliverable.reconcile_strategy in ("adapt", "split", "pass", "truncate")


def test_unknown_recipe_and_unknown_topic_are_loud(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    with pytest.raises(UnknownEntryError):
        plan_for(root, SelectionRequest(recipe="x-nope", topics=["x-t-alpha"]))
    with pytest.raises(UnknownEntryError):
        plan_for(root, SelectionRequest(recipe="explainer-post", topics=["x-missing"]))


def test_commit_map_must_cover_the_subset_exactly(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    request = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"])
    with pytest.raises(PreimageError, match="one commit per"):
        resolve_plan(
            make_env(root),
            request,
            source_subset=("x-repo", "x-other"),
            source_commit=COMMITS,
        )


# ------------------------------------------------------------------------------------
# Content fanout: the full cross product, each item id-distinct (§8; PC2)
# ------------------------------------------------------------------------------------


def test_multi_topic_multi_persona_full_cross_product(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            personas=["tech-journalist", "product-reviewer"],
            platforms=["github"],
        ),
    )
    assert len(plan.items) == 4
    assert len(set(plan.artifact_ids())) == 4  # id-distinct — exactly-once (PC2)
    assert {(i.topic, i.persona) for i in plan.items} == {
        ("x-t-alpha", "tech-journalist"),
        ("x-t-alpha", "product-reviewer"),
        ("x-t-beta", "tech-journalist"),
        ("x-t-beta", "product-reviewer"),
    }
    # The plan is canonical in itself: items sorted by artifact-id (§22.2).
    assert list(plan.artifact_ids()) == sorted(plan.artifact_ids())


def test_goal_set_variants_fan_out_stacked_sets_do_not(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    stacked = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            goal_sets=[["explain", "convince"]],
        ),
    )
    assert len(stacked.items) == 1
    assert stacked.items[0].goals == ("convince", "explain")  # §7.2 sorted canonical
    variants = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            goal_sets=[["explain"], ["convince"]],
        ),
    )
    assert len(variants.items) == 2
    assert {i.goals for i in variants.items} == {("explain",), ("convince",)}


# ------------------------------------------------------------------------------------
# Rendering fanout (§8): platforms × output-types × presentations × languages
# ------------------------------------------------------------------------------------


def test_rendering_fanout_full_product(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(root, "presentations", "x-fancy")
    write_entry(root, "languages", "x-fr", "name: French (fixture)\n")
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            platforms=["github", "linkedin"],
            languages=["en", "x-fr"],
            output_types=["md", "html"],
            presentations=["plain", "x-fancy"],
        ),
    )
    (item,) = plan.items
    assert len(item.deliverables) == 2 * 2 * 2 * 2
    ids = plan.deliverable_ids()
    assert len(set(ids)) == 16  # exactly-once cover (PC2)
    assert all(d.startswith(f"{item.artifact_id}.") for d in ids)
    # One fitted-id per (platform, language) — the reconcile cache key (§7.1).
    assert len({d.fitted_id for d in item.deliverables}) == 4
    assert list(ids) == sorted(ids)  # canonical order (§22.2)


def test_real_registry_probe_two_topics_two_platforms(tmp_path: Path) -> None:
    """The mandated R1-entry probe: 2 topics × tech-journalist × how-to-documentation
    × [corporate-website, medium-post] × plain-text → 4 deliverable-ids."""
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            personas=["tech-journalist"],
            formats=["how-to-documentation"],
            platforms=["corporate-website", "medium-post"],
            output_types=["plain-text"],
        ),
    )
    assert len(plan.items) == 2
    assert len(set(plan.artifact_ids())) == 2
    assert {i.format for i in plan.items} == {"how-to-documentation"}
    assert {i.persona for i in plan.items} == {"tech-journalist"}
    deliverables = plan.deliverable_ids()
    assert len(deliverables) == 4
    expected = {
        f"{item.artifact_id}.{platform}.en.plain-text.plain"
        for item in plan.items
        for platform in ("corporate-website", "medium-post")
    }
    assert set(deliverables) == expected
    for did in deliverables:
        parsed = parse_id(did)
        assert parsed.level == "deliverable"
        assert parsed.output_type == "plain-text"
        assert parsed.presentation == "plain"


# ------------------------------------------------------------------------------------
# Plan determinism (§21.6): pure function; plan_hash guards the plan
# ------------------------------------------------------------------------------------


def test_same_inputs_same_plan_hash_fresh_envs(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post",
        topics=["x-t-alpha", "x-t-beta"],
        platforms=["github"],
        goal_sets=[["explain", "convince"]],
    )
    first = plan_for(root, request)
    second = plan_for(root, request)  # a fresh env — re-resolution from inputs
    assert first.plan_hash == second.plan_hash
    assert first.artifact_ids() == second.artifact_ids()
    assert first.deliverable_ids() == second.deliverable_ids()


def test_re_resolve_with_the_same_env_is_stable(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    request = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"])
    first = resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS)
    second = resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS)
    # One-time warnings were consumed by the first resolve; the PLAN is unchanged.
    assert first.plan_hash == second.plan_hash
    assert first.artifact_ids() == second.artifact_ids()


def test_request_permutation_is_hash_neutral(tmp_path: Path) -> None:
    # The cover is keyed by settled ids (PC2): a permuted multi-select is the same plan.
    root = build_root(tmp_path)
    a = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            platforms=["github", "linkedin"],
        ),
    )
    b = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-beta", "x-t-alpha"],
            platforms=["linkedin", "github"],
        ),
    )
    assert a.plan_hash == b.plan_hash


def test_goal_set_input_order_is_identity_neutral(tmp_path: Path) -> None:
    # Acceptance: identical goal-sets in any input order → identical artifact-id (§7.2).
    root = build_root(tmp_path)
    a = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post", topics=["x-t-alpha"], goal_sets=[["explain", "convince"]]
        ),
    )
    b = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post", topics=["x-t-alpha"], goal_sets=[["convince", "explain"]]
        ),
    )
    assert a.artifact_ids() == b.artifact_ids()
    assert a.plan_hash == b.plan_hash


@pytest.mark.parametrize(
    "change",
    ["extra-topic", "other-commit", "m3-clause", "recipe-m3-clause"],
)
def test_any_input_change_changes_the_hash(tmp_path: Path, change: str) -> None:
    root = build_root(tmp_path)
    request = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"])
    baseline = plan_for(root, request)
    if change == "extra-topic":
        changed = plan_for(
            root,
            SelectionRequest(
                recipe="explainer-post", topics=["x-t-alpha", "x-t-beta"], platforms=["github"]
            ),
        )
    elif change == "other-commit":
        changed = resolve_plan(
            make_env(root),
            request,
            source_subset=SUBSET,
            source_commit={"x-repo": "deadbeef4567"},
        )
    elif change == "m3-clause":
        changed = plan_for(root, request, run_selection={"require": ["freshness < 12mo"]})
    else:
        changed = plan_for(root, request, recipe_selection={"require": ["trusted >= 3"]})
    assert changed.plan_hash != baseline.plan_hash


def test_plan_hash_is_stable_across_processes_and_hash_seeds(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    script = tmp_path / "hash_probe.py"
    script.write_text(
        "import sys\n"
        "from pipeline.cascade import CascadeEnv\n"
        "from pipeline.fanout import SelectionRequest\n"
        "from pipeline.plan import resolve_plan\n"
        "env = CascadeEnv(sys.argv[1], workspace='testws')\n"
        "request = SelectionRequest(\n"
        "    recipe='explainer-post',\n"
        "    topics=('x-t-alpha', 'x-t-beta'),\n"
        "    personas=('tech-journalist', 'product-reviewer'),\n"
        "    platforms=('github', 'linkedin'),\n"
        "    output_types=('md', 'html'),\n"
        "    goal_sets=(('explain', 'convince'),),\n"
        ")\n"
        "plan = resolve_plan(env, request, source_subset=('x-repo',),\n"
        "                    source_commit={'x-repo': 'c0ffee0123ab'},\n"
        "                    run_selection={'require': ['freshness < 12mo']})\n"
        "print(plan.plan_hash)\n",
        encoding="utf-8",
    )
    hashes = []
    for seed in ("1", "31337"):  # different hash randomization per process
        result = subprocess.run(
            [sys.executable, str(script), str(root)],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT), "PYTHONHASHSEED": seed},
        )
        hashes.append(result.stdout.strip())
    assert hashes[0] == hashes[1]
    assert len(hashes[0]) == 64  # the full SHA-256 hex (§7.4: full digests recorded)


def test_new_schema_attribute_at_default_churns_no_id_and_no_hash(tmp_path: Path) -> None:
    # Acceptance (§7.2): a newly shipped attribute at its default is absent from the
    # delta map — no artifact-id churns, and the plan hash holds.
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha", "x-t-beta"], platforms=["github"]
    )
    before = plan_for(build_root(tmp_path, name="root-a"), request)
    after = plan_for(
        build_root(tmp_path, name="root-b", schema_append=VOICES_SCHEMA_APPEND), request
    )
    assert before.artifact_ids() == after.artifact_ids()
    assert before.plan_hash == after.plan_hash


def test_plan_payload_round_trip(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"]),
    )
    payload = plan_payload(plan)
    assert digest_full(payload) == plan.plan_hash
    assert [i["artifact-id"] for i in payload["items"]] == list(plan.artifact_ids())


# ------------------------------------------------------------------------------------
# §21.8 conformance (step-06 disposition 6): M3 is NOT an identity input (Q17)
# ------------------------------------------------------------------------------------


def test_clause_only_difference_yields_identical_ids(tmp_path: Path) -> None:
    root = build_root(tmp_path, l3="source_selection:\n  require:\n    - freshness < 24mo\n")
    request = SelectionRequest(
        recipe="explainer-post",
        topics=["x-t-alpha", "x-t-beta"],
        platforms=["github"],
        goal_sets=[["explain", "convince"]],
    )
    baseline = plan_for(root, request)
    for clauses in (
        {"require": ["trusted >= 4", "freshness < 6mo"]},
        {"span": {"content-kind": ["general", "research-notes"]}},
        {"on_conflict": "surface-both"},
        {"grounding_posture": "block"},  # DR-6: a policy selection — rides the plan, not the id
    ):
        varied = plan_for(root, request, run_selection=clauses)
        # Identical artifact-ids AND deliverable-ids: the selection expression rides
        # the plan, never the preimage (§21.8 documented behavior; §7.2).
        assert varied.artifact_ids() == baseline.artifact_ids()
        assert varied.deliverable_ids() == baseline.deliverable_ids()
        # The plan itself honestly moves (the §21.6 plan-stale guard covers M3 edits).
        assert varied.plan_hash != baseline.plan_hash


def test_m3_rides_the_plan_but_not_the_preimage(tmp_path: Path) -> None:
    root = build_root(tmp_path, l3="source_selection:\n  require:\n    - freshness < 24mo\n")
    plan = plan_for(
        root,
        SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], goal_sets=[["explain"]]),
        run_selection={"require": ["trusted >= 3"]},
    )
    (item,) = plan.items
    rendered = [clause.canonical() for clause in item.m3.require]
    assert "freshness < 24mo" in rendered  # the L3 workspace baseline (§12.1)
    assert "trusted >= 3" in rendered  # the run layer, supplied run-side
    # Neither the workspace- nor run-layer clause reaches the identity preimage (Q17).
    preimage_text = canonical_json_str(item.preimage)
    assert "freshness" not in preimage_text
    assert "trusted" not in preimage_text
    assert "grounding_posture" not in preimage_text  # DR-6: policy, never the id preimage
    # The payload carries the M3 lane for the grounding stage.
    payload = plan_payload(plan)
    assert payload["items"][0]["m3"]["require"] == rendered
    # DR-6 (§6.5/§19): the selection payload carries grounding_posture UNCONDITIONALLY, defaulting
    # to `warn` — it rides plan_hash (like on_conflict), never the artifact-id preimage.
    assert payload["items"][0]["m3"]["grounding_posture"] == "warn"


def test_goal_implied_m3_layer_reaches_the_item(tmp_path: Path) -> None:
    # convince ships the design's own §6.3 clause contribution (goal-implied layer).
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post", topics=["x-t-alpha"], goal_sets=[["explain", "convince"]]
        ),
    )
    (item,) = plan.items
    assert "traceability is true" in [c.canonical() for c in item.m3.require]
    assert [(p.term.key, p.weight) for p in item.m3.prefer] == [("authoritative", 2)]


# ------------------------------------------------------------------------------------
# The emergent allow-list (§8/Q4): no veto — advisory warn only, once
# ------------------------------------------------------------------------------------


def test_weird_pairing_resolves_with_one_advisory_warning(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            formats=["readme"],
            platforms=["linkedin"],
        ),
    )
    # NO veto (Q4): both items resolve, deliverables minted, nothing blocked.
    assert len(plan.items) == 2
    assert all(len(item.deliverables) == 1 for item in plan.items)
    # The advisory fires EXACTLY ONCE for the pairing, not once per item (§8).
    pairing = [w for w in plan.warnings if w.key.startswith("nonsensical-pairing")]
    assert len(pairing) == 1
    assert pairing[0].key == "nonsensical-pairing:readme:linkedin"
    assert "honored" in pairing[0].message


def test_uncataloged_pairing_draws_no_warning(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            formats=["product-requirements-document"],
            platforms=["linkedin"],
        ),
    )
    assert len(plan.items) == 1
    assert not [w for w in plan.warnings if w.key.startswith("nonsensical-pairing")]


# ------------------------------------------------------------------------------------
# Goal-set overload (§8): warns, never blocks
# ------------------------------------------------------------------------------------


def test_goal_set_overload_warns_and_never_blocks(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(root, "goals", "x-goal-extra")
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            goal_sets=[["explain", "convince", "try-it", "x-goal-extra"]],
        ),
    )
    (item,) = plan.items  # resolved — never blocked (§8)
    assert item.goals == ("convince", "explain", "try-it", "x-goal-extra")
    overload = [w for w in plan.warnings if w.key.startswith("goal-set-overload")]
    assert len(overload) == 1
    assert "never blocked" in overload[0].message


def test_three_goals_do_not_warn(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            goal_sets=[["explain", "convince", "try-it"]],
        ),
    )
    assert not [w for w in plan.warnings if w.key.startswith("goal-set-overload")]


# ------------------------------------------------------------------------------------
# Duplicate-item impossibility (PC2): the plan is an exactly-once cover
# ------------------------------------------------------------------------------------


def test_brand_lock_collapse_dedupes_exactly_once_with_warning(tmp_path: Path) -> None:
    # §12.6 strength-c: both run voices resolve to the flagged voice → ONE designed
    # item; the plan carries it once (PC2) and surfaces the collapse (§3.1).
    root = build_root(tmp_path, l2=BRAND_C_L2)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            voices=["clear-explainer", "confident-advocate"],
            platforms=["github"],
        ),
    )
    (item,) = plan.items
    assert item.voice == "clear-explainer"
    keys = warning_keys(plan)
    assert f"fanout-collapse:{item.artifact_id}" in keys
    assert any(key.startswith("brand-voice-hard-lock") for key in keys)
    # The single deliverable set survives the collapse untouched.
    assert plan.deliverable_ids() == (f"{item.artifact_id}.github.en.md.plain",)


def test_plan_ids_are_globally_unique(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            personas=["tech-journalist", "executive-coach"],
            platforms=["github", "linkedin"],
            output_types=["md", "html"],
        ),
    )
    artifact_ids = plan.artifact_ids()
    deliverable_ids = plan.deliverable_ids()
    assert len(set(artifact_ids)) == len(artifact_ids) == 4
    assert len(set(deliverable_ids)) == len(deliverable_ids) == 16


# ------------------------------------------------------------------------------------
# Compose-only plans + the step-16 RV-1 decision (inert platform config → WARN)
# ------------------------------------------------------------------------------------


def test_no_rendering_selection_is_a_compose_only_plan(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    plan = plan_for(root, SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"]))
    (item,) = plan.items
    assert item.deliverables == ()
    assert plan.deliverable_ids() == ()
    # No platform.* config anywhere → nothing inert, nothing to surface.
    assert not [k for k in warning_keys(plan) if k.startswith("inert-platform")]


def test_inert_platform_configuration_warns_once_on_compose_only(tmp_path: Path) -> None:
    # Step-16 RV-1, decided at step 19: configured L2/L3/L5 platform.* values on a
    # platform-less plan are surfaced (§3.1; Q3 surface-don't-bend) — warn-only (Q4).
    l3 = "values:\n  platform.reconcile_strategy: truncate\n"
    root = build_root(tmp_path, l3=l3)
    plan = plan_for(root, SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"]))
    (item,) = plan.items
    assert item.deliverables == ()  # still resolves — never a block
    inert = [w for w in plan.warnings if w.key == f"inert-platform-configuration:{WS}"]
    assert len(inert) == 1
    assert "reconcile_strategy" in inert[0].message
    assert "inert" in inert[0].message


def test_platform_configuration_consumed_when_a_platform_routes(tmp_path: Path) -> None:
    l3 = "values:\n  platform.reconcile_strategy: truncate\n"
    root = build_root(tmp_path, l3=l3)
    plan = plan_for(
        root,
        SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"]),
    )
    (item,) = plan.items
    (deliverable,) = item.deliverables
    assert deliverable.reconcile_strategy == "truncate"  # the L3 binding, consumed
    assert not [k for k in warning_keys(plan) if k.startswith("inert-platform")]


def test_rendering_selection_without_platform_refuses_through_resolve_plan(
    tmp_path: Path,
) -> None:
    root = build_root(tmp_path)
    with pytest.raises(FanoutError, match="no platform"):
        plan_for(
            root,
            SelectionRequest(
                recipe="explainer-post", topics=["x-t-alpha"], output_types=["plain-text"]
            ),
        )


# ------------------------------------------------------------------------------------
# Per-item render semantics riding the plan (§12.3 through §8 fanout)
# ------------------------------------------------------------------------------------


def test_reconcile_strategy_is_per_item_from_the_projection_table(tmp_path: Path) -> None:
    # github's per-format table (real registry data) differs across formats — the
    # plan records the per-(format × platform) strategy on each deliverable (§12.3).
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha"],
            formats=["readme", "short-opinion-post"],
            platforms=["github"],
        ),
    )
    strategies = {item.format: item.deliverables[0].reconcile_strategy for item in plan.items}
    # github's shipped table: readme -> pass; short-opinion-post has no row -> the
    # L0 schema floor `adapt` (§12.3 two-tier defaulting).
    assert strategies == {"readme": "pass", "short-opinion-post": "adapt"}


def test_weak_platform_output_type_default_rides_the_coordinates(tmp_path: Path) -> None:
    # corporate-website implies html (weak default, §12.3) when nothing explicit is
    # selected; the deliverable-id records the RESOLVED coordinate.
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post", topics=["x-t-alpha"], platforms=["corporate-website"]
        ),
    )
    (item,) = plan.items
    (deliverable,) = item.deliverables
    assert deliverable.output_type == "html"
    assert deliverable.deliverable_id.endswith(".corporate-website.en.html.plain")


# ------------------------------------------------------------------------------------
# DR-3 (horn (a) / B1): the outline DRIVE path — the edit is identity-bearing via the digest
# ------------------------------------------------------------------------------------

_D_A = outline_digest("# A\n\n- alpha\n- beta\n")
_D_B = outline_digest("# B\n\n- gamma\n")


def test_outline_drives_a_distinct_artifact_id(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    # the outline map keys on the pre-resolution content COORDINATE (unselected slots are None).
    coord = ContentCombination(topic="x-t-alpha", persona=None, format=None, voice=None, goals=None)
    req = lambda outlines: SelectionRequest(  # noqa: E731
        recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"], outlines=outlines
    )
    base = plan_for(root, req({}))
    plan_a = plan_for(root, req({coord: _D_A}))
    plan_b = plan_for(root, req({coord: _D_B}))
    (base_item,) = base.items
    (ia,) = plan_a.items
    (ib,) = plan_b.items

    # (i) two DIFFERENT edited outlines over the SAME coordinate -> DIFFERENT driven artifact-ids.
    assert ia.artifact_id != ib.artifact_id
    # the digest rides the item AND enters the §7.2 preimage (the SOLE new component).
    assert ia.outline_digest == _D_A and ia.preimage["outline-digest"] == _D_A
    assert ib.outline_digest == _D_B and ib.preimage["outline-digest"] == _D_B
    # (iii) the outline-LESS coordinate is byte-identical to today: NO outline-digest key; the
    # 4-key id; and driving changes identity (an outline-less id != a driven id).
    assert base_item.outline_digest is None
    assert "outline-digest" not in base_item.preimage
    assert base_item.artifact_id != ia.artifact_id
    # the plan_hash moves honestly with the outline (the preimage-digest carries it).
    assert base.plan_hash != plan_a.plan_hash
    assert plan_a.plan_hash != plan_b.plan_hash


def test_outline_less_plan_is_byte_identical_to_no_outlines_arg(tmp_path: Path) -> None:
    # regression proof (iii), plan-level: passing an EMPTY outline map yields the byte-identical
    # plan (same artifact-ids, same plan_hash) as passing no map at all.
    root = build_root(tmp_path)
    r = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"])
    r_empty = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"], outlines={}
    )
    assert plan_for(root, r).plan_hash == plan_for(root, r_empty).plan_hash


# ------------------------------------------------------------------------------------
# DR-2 C3: the house-style Lexicon threads through the plan (identity + lineage)
# ------------------------------------------------------------------------------------


def _copy_lexicons(root: Path) -> None:
    """Copy the real `lexicons/` registry into the test root (class-(ii), not a matrix axis)."""
    if not (root / "lexicons").exists():
        shutil.copytree(REPO_ROOT / "lexicons", root / "lexicons")


def test_plan_item_carries_the_lexicon_and_it_matches_the_preimage(tmp_path: Path) -> None:
    # One-resolution consistency at the plan level: the SINGLE `resolve_compose` per item feeds
    # BOTH the artifact preimage (identity) AND the PlanItem lineage carrier — so they agree.
    root = build_root(tmp_path)
    _copy_lexicons(root)
    write_entry(root, "recipes", "x-lex", "extends: explainer-post\nlexicon: house-standard\n")
    plan = plan_for(
        root, SelectionRequest(recipe="x-lex", topics=["x-t-alpha"], platforms=["github"])
    )
    (item,) = plan.items
    assert item.lexicon == "house-standard"  # the lineage carrier (the outline_digest twin)
    assert item.preimage["lexicon"]["entry"] == "house-standard"  # identity
    assert item.lexicon == item.preimage["lexicon"]["entry"]  # one-resolution consistency


def test_plan_without_lexicon_is_byte_identical(tmp_path: Path) -> None:
    # The golden-corpus floor: a recipe with no lexicon slot -> no `lexicon` key in the preimage,
    # None lineage carrier, and the artifact-id/plan_hash are byte-identical to a plan built with
    # the lexicons registry ENTIRELY ABSENT (its mere presence perturbs nothing).
    with_reg = build_root(tmp_path, name="with")
    _copy_lexicons(with_reg)
    without_reg = build_root(tmp_path, name="without")
    req = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"])
    plan_with = plan_for(with_reg, req)
    plan_without = plan_for(without_reg, req)
    (item,) = plan_with.items
    assert item.lexicon is None
    assert "lexicon" not in item.preimage
    assert plan_with.plan_hash == plan_without.plan_hash  # id + plan_hash unperturbed


def test_unknown_recipe_lexicon_is_loud_through_resolve_plan(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    _copy_lexicons(root)
    write_entry(root, "recipes", "x-badlex", "extends: explainer-post\nlexicon: x-no-such\n")
    with pytest.raises(UnknownEntryError):
        plan_for(root, SelectionRequest(recipe="x-badlex", topics=["x-t-alpha"]))


# ------------------------------------------------------------------------------------
# CLI-UX C1: the `explain` projection (effective settings + spend estimate) is a pure
# READ side-channel — identity-neutral, captured from the SINGLE resolve (S-1).
# ------------------------------------------------------------------------------------


def test_explain_is_byte_identical(tmp_path: Path) -> None:
    """The C1 identity gate: `explain` moves NOTHING. `plan_hash` AND `artifact_ids()`
    (and the whole canonical payload) are byte-identical with and without it."""
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post",
        topics=["x-t-alpha", "x-t-beta"],
        platforms=["github", "linkedin"],
    )
    a = plan_for(root, request, explain=False)
    b = plan_for(root, request, explain=True)
    # The load-bearing assertion: BOTH the fingerprint and the paid cover are unchanged.
    assert a.plan_hash == b.plan_hash
    assert a.artifact_ids() == b.artifact_ids()
    assert a.deliverable_ids() == b.deliverable_ids()
    # The projection is present only when asked, and it never enters the canonical payload.
    assert a.effective_settings is None
    assert b.effective_settings is not None
    assert plan_payload(a) == plan_payload(b)


def test_effective_settings_capture_compose_and_render(tmp_path: Path) -> None:
    """With `explain=True`, a routed item's view carries the compose dims (values+provenance
    equal to a fresh `resolve_compose`) AND the render dims captured from the single resolve."""
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"]
    )
    plan = plan_for(root, request, explain=True)
    (item,) = plan.items
    assert plan.effective_settings is not None
    settings = plan.effective_settings[item.artifact_id]

    # Compose dims equal a freshly recomputed resolution (the internal `_content_selection`
    # for a topic-only request is `RunSelection(recipe, topic=…)`).
    compose = resolve_compose(
        make_env(root), RunSelection(recipe="explainer-post", topic="x-t-alpha")
    )
    assert settings["voice"]["values"] == compose.voice.values
    assert settings["voice"]["provenance"] == compose.voice.provenance
    assert settings["persona"]["entry"] == compose.persona.entry_id
    assert settings["topic"]["entry"] == "x-t-alpha"

    # Render dims captured from the SINGLE resolve (S-1), keyed by deliverable-id.
    assert settings["render"]  # a platform routed → non-empty
    (deliverable,) = item.deliverables
    assert set(settings["render"]) == {deliverable.deliverable_id}
    render_view = settings["render"][deliverable.deliverable_id]
    assert render_view["platform"]["entry"] == deliverable.platform
    assert "values" in render_view["platform"] and "provenance" in render_view["platform"]
    assert "values" in render_view["output_type"] and "provenance" in render_view["output_type"]


def test_effective_settings_compose_only_plan_has_no_render_dims(tmp_path: Path) -> None:
    """A compose-only plan (no platform coordinates) → the item view holds compose dims and an
    EMPTY render map — the loop runs zero times, so no render dims are captured and nothing
    crashes (the S-1 compose-only branch)."""
    root = build_root(tmp_path)
    plan = plan_for(
        root, SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"]), explain=True
    )
    (item,) = plan.items
    assert item.deliverables == ()  # compose-only
    assert plan.effective_settings is not None
    settings = plan.effective_settings[item.artifact_id]
    assert settings["render"] == {}  # no render dims, no crash
    assert settings["voice"]["values"]  # compose dims still present
