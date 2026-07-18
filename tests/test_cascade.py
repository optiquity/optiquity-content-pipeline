"""Step-16 tests — `pipeline/cascade.py`: the M2 spine fold (design §12.2–§12.7).

Runs against the REAL steps-14/15 registries (copied into `tmp_path` — REC-3: the repo
is read-only toward this suite) plus tmp instance/workspace T10 surfaces. Covers: the
six-rung precedence order on real data; M1-before-M2; the CA2 voice chain end-to-end
(+ §12.6 BO2 elevation, strengths, run-deviation warnings); CA8 mandatory-global
enforcement; CM3 operators through the cascade; CA9 advisory-vs-hard split; CA10 M3
lane separation; MIG-6 blocking through the cascade; and the §7.2 identity integration
(a cascade resolution mints a stable `artifact-id`).
"""

from __future__ import annotations

import shutil
from dataclasses import replace as dc_replace
from pathlib import Path

import pytest

from pipeline import ids
from pipeline.attrtypes import CombineOperatorError
from pipeline.cascade import (
    GLOBAL_SCOPE,
    PRESENTATION_FLOOR_ENTRY,
    RUNG_L0,
    RUNG_L1,
    RUNG_L2,
    RUNG_L3,
    RUNG_L5,
    RUNG_L6,
    RUNG_PROJECTION,
    WORKSPACE_SCOPE,
    AmbiguousSelectionError,
    CascadeEnv,
    HardLimitBindingError,
    MandatoryGlobalError,
    RunSelection,
    ScopeDefaultsError,
    SelectionError,
    UnbindableAttributeError,
    VoiceDefault,
    parse_scope_defaults,
    resolve_compose,
    resolve_render,
)
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m1 import DanglingRefError, StaleEntryError, UnknownEntryError
from pipeline.overrides import OverrideError, collect_overrides

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"

#: The CA8 mandatory globals (all shipped framework ids — generic values only).
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

#: Test-only set attributes appended to the COPIED voices schema (CM3 coverage needs a
#: set-typed dimension attribute; no shipped dimension schema declares one). Appending
#: without a version bump is safe: definition_version 1 == every shipped stamp.
VOICES_SCHEMA_APPEND = """\
  tags:
    type:
      type: set
      element: text
    default: []
    definition: Test-only replace-default set (step-16 cascade tests).
    definition_version: 1
  audience:
    type:
      type: set
      element: text
    default: []
    definition: Test-only union-default set (schema default operator, s12.4).
    definition_version: 1
    combine: union
"""

TOPIC_ENTRY = (
    "---\nid: x-sample-topic\nprovenance: instance\nschema_version: 1\n"
    "why: A generic fixture subject.\n---\n\nSample topic body.\n"
)


def build_root(tmp_path: Path, *, l2: str | None = BASE_L2, l3: str | None = None) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for name in REGISTRY_ROOTS:
        src = REPO_ROOT / name
        if src.is_dir():
            shutil.copytree(src, root / name)
    schema_path = root / "voices" / "_schema.yaml"
    schema_path.write_text(
        schema_path.read_text(encoding="utf-8") + VOICES_SCHEMA_APPEND, encoding="utf-8"
    )
    if l2 is not None:
        (root / "instance").mkdir()
        (root / "instance" / "defaults.yaml").write_text(l2, encoding="utf-8")
    topics = root / "workspaces" / WS / "topics"
    topics.mkdir(parents=True)
    (topics / "x-sample-topic.md").write_text(TOPIC_ENTRY, encoding="utf-8")
    if l3 is not None:
        (root / "workspaces" / WS / "defaults.yaml").write_text(l3, encoding="utf-8")
    return root


def write_entry(
    root: Path,
    collection: str,
    entry_id: str,
    frontmatter: str = "",
    *,
    workspace: str | None = None,
    stamp: int = 1,
    body: str = "Test fixture body.",
) -> Path:
    provenance = "instance" if entry_id.startswith("x-") else "framework"
    dirpath = root / "workspaces" / workspace / collection if workspace else root / collection
    dirpath.mkdir(parents=True, exist_ok=True)
    path = dirpath / f"{entry_id}.md"
    path.write_text(
        f"---\nid: {entry_id}\nprovenance: {provenance}\nschema_version: {stamp}\n"
        f"{frontmatter}---\n\n{body}\n",
        encoding="utf-8",
    )
    return path


def make_env(root: Path, overrides=None, **kwargs) -> CascadeEnv:
    return CascadeEnv(root, workspace=WS, overrides=overrides, **kwargs)


SEL = RunSelection(recipe="explainer-post", topic="x-sample-topic")


# ------------------------------------------------------------------------------------
# CA8: the mandatory-global set (§12.3)
# ------------------------------------------------------------------------------------


def test_missing_instance_defaults_file_is_a_typed_error(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=None)
    with pytest.raises(MandatoryGlobalError) as exc:
        make_env(root)
    assert exc.value.code == "missing-mandatory-global"


@pytest.mark.parametrize("missing", ["voice", "language", "output_type"])
def test_missing_mandatory_global_key_is_a_typed_error(tmp_path: Path, missing: str) -> None:
    lines = [line for line in BASE_L2.splitlines() if not line.startswith(missing)]
    root = build_root(tmp_path, l2="\n".join(lines) + "\n")
    with pytest.raises(MandatoryGlobalError) as exc:
        make_env(root)
    assert missing in str(exc.value)


def test_platform_absence_is_fine_and_strategy_reads_the_schema_floor(
    tmp_path: Path,
) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    compose = resolve_compose(env, SEL)
    render = resolve_render(env, compose, SEL)
    # Platform has no mandatory global (CA8): absence is a valid state.
    assert render.platform is None
    assert render.advisories == {}
    # The no-platform strategy edge (step-14 carry-forward): the L0 floor comes from
    # the platforms collection MANIFEST, independent of any entry.
    assert render.reconcile_strategy == "adapt"
    assert render.reconcile_strategy_provenance == RUNG_L0
    # Language and Output-type resolve from the mandatory L2 globals.
    assert render.language.entry_id == "en"
    assert render.output_type.entry_id == "md"


def test_presentation_floors_to_plain(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    render = resolve_render(env, resolve_compose(env, SEL), SEL)
    assert render.presentation.entry_id == PRESENTATION_FLOOR_ENTRY  # PD7


# ------------------------------------------------------------------------------------
# T10: the ratified scope-default shapes (step-15 carry-forward 2)
# ------------------------------------------------------------------------------------


def test_shipped_template_surfaces_parse_clean() -> None:
    global_template = (REPO_ROOT / "instance" / "defaults.template.yaml").read_text(
        encoding="utf-8"
    )
    workspace_template = (
        REPO_ROOT / "workspaces" / "workspace.template" / "defaults.yaml"
    ).read_text(encoding="utf-8")
    parsed_global = parse_scope_defaults(global_template, scope=GLOBAL_SCOPE, where="t")
    parsed_workspace = parse_scope_defaults(workspace_template, scope=WORKSPACE_SCOPE, where="t")
    # Both templates are 100% comments → empty surfaces, accepted by the real parser.
    assert parsed_global.voice is None and parsed_workspace.voice is None


def test_populated_template_shapes_parse_including_dual_voice_form() -> None:
    parsed = parse_scope_defaults(
        "voice: clear-explainer\nlanguage: en\noutput_type: md\nvalues:\n  voice.warmth: 4\n",
        scope=GLOBAL_SCOPE,
        where="t",
    )
    assert parsed.voice == VoiceDefault(entry="clear-explainer")
    assert parsed.values[0].dimension == "voice"
    # The dual mapping form: bare `true` = strength b (§12.6).
    flagged = parse_scope_defaults(
        "voice:\n  entry: x-house-voice\n  authoritative: true\nlanguage: en\noutput_type: md\n",
        scope=GLOBAL_SCOPE,
        where="t",
    )
    assert flagged.voice == VoiceDefault(entry="x-house-voice", authoritative="b")
    for strength in ("a", "b", "c"):
        parsed = parse_scope_defaults(
            f"voice:\n  entry: x-v\n  authoritative: {strength}\n",
            scope=WORKSPACE_SCOPE,
            where="t",
        )
        assert parsed.voice == VoiceDefault(entry="x-v", authoritative=strength)
    workspace = parse_scope_defaults(
        "voice: x-client-voice\nvalues:\n  voice.formality: 4\n"
        "source_selection:\n  require:\n    - freshness < 24mo\n  prefer:\n    - trusted: 1\n",
        scope=WORKSPACE_SCOPE,
        where="t",
    )
    assert workspace.source_selection is not None
    assert "require" in workspace.source_selection


def test_scope_defaults_vocabulary_is_closed() -> None:
    with pytest.raises(ScopeDefaultsError):
        parse_scope_defaults("nonsense_key: 1\n", scope=GLOBAL_SCOPE, where="t")
    # Workspace-only keys are refused on the global surface (§12.3 rung table).
    for key in ("topic: x-t", "source_selection: {}"):
        with pytest.raises(ScopeDefaultsError):
            parse_scope_defaults(f"{key}\n", scope=GLOBAL_SCOPE, where="t")


def test_scope_defaults_refusals() -> None:
    with pytest.raises(ScopeDefaultsError, match="authoritative"):
        parse_scope_defaults(
            "voice:\n  entry: x-v\n  authoritative: strong\n",
            scope=GLOBAL_SCOPE,
            where="t",
        )
    with pytest.raises(ScopeDefaultsError, match="%"):
        parse_scope_defaults("%YAML 1.1\n---\nvoice: v\n", scope=GLOBAL_SCOPE, where="t")
    with pytest.raises(ScopeDefaultsError, match="duplicate"):
        parse_scope_defaults("goals: [explain, explain]\n", scope=GLOBAL_SCOPE, where="t")


# ------------------------------------------------------------------------------------
# The six-rung precedence order (§12.2), each rung beating the one below — real data
# ------------------------------------------------------------------------------------


def test_l1_entry_default_beats_l0_floor(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    voice = resolve_compose(env, SEL).voice
    # clear-explainer SETS humor 2 (floor 3) — L1 wins; unset attrs ride L0.
    assert voice.values["humor"] == 2
    assert voice.provenance["humor"] == RUNG_L1
    assert voice.values["tags"] == []
    assert voice.provenance["tags"] == RUNG_L0


def test_l2_beats_l1(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.energy: 4\n")
    voice = resolve_compose(make_env(root), SEL).voice
    assert voice.entry.effective["energy"] == 3  # the M1 entry value (L1)
    assert voice.values["energy"] == 4
    assert voice.provenance["energy"] == RUNG_L2


def test_l3_l5_l6_each_beat_the_rung_below(tmp_path: Path) -> None:
    root = build_root(
        tmp_path,
        l2=BASE_L2 + "values:\n  voice.energy: 4\n",
        l3="values:\n  voice.energy: 5\n",
    )
    write_entry(root, "recipes", "x-l5", "extends: explainer-post\nvalues:\n  voice.energy: 1\n")
    # L3 beats L2.
    voice = resolve_compose(make_env(root), SEL).voice
    assert (voice.values["energy"], voice.provenance["energy"]) == (5, RUNG_L3)
    # L5 beats L3.
    voice = resolve_compose(make_env(root), dc_replace(SEL, recipe="x-l5")).voice
    assert (voice.values["energy"], voice.provenance["energy"]) == (1, RUNG_L5)
    # L6 beats L5.
    env = make_env(root, overrides=collect_overrides({"voice.energy": 2}))
    voice = resolve_compose(env, dc_replace(SEL, recipe="x-l5")).voice
    assert (voice.values["energy"], voice.provenance["energy"]) == (2, RUNG_L6)


# ------------------------------------------------------------------------------------
# M1 fully resolves BEFORE M2 binds (Q18a; §12.1)
# ------------------------------------------------------------------------------------


def test_m1_field_merge_completes_before_any_binding(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.warmth: 1\n")
    write_entry(root, "voices", "x-warm", "extends: clear-explainer\nwarmth: 5\n")
    write_entry(root, "recipes", "x-warm-recipe", "extends: explainer-post\nvoice: x-warm\n")
    env = make_env(root, overrides=collect_overrides({"voice.warmth": 2}))
    voice = resolve_compose(env, dc_replace(SEL, recipe="x-warm-recipe")).voice
    # The effective ENTRY is the completed field-merge: declared field + inherited rest.
    assert voice.entry_id == "x-warm"
    assert voice.entry.effective["warmth"] == 5
    assert voice.entry.effective["guidelines"].startswith("Plain language over jargon")
    # M2 then binds on top: L6 (2) beats L2 (1) beats the merged L1 (5).
    assert voice.values["warmth"] == 2
    assert voice.provenance["warmth"] == RUNG_L6
    assert voice.provenance["guidelines"] == RUNG_L1
    # Overrides never touched M1 (CA7): the resolver's cached entry is unchanged.
    assert env.resolver.resolve("voices", "x-warm").effective["warmth"] == 5


def test_workspace_shadowing_resolves_before_binding(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(root, "voices", "x-brand-voice", "extends: clear-explainer\nformality: 5\n")
    write_entry(
        root,
        "voices",
        "x-brand-voice",
        "extends: x-brand-voice\nformality: 1\n",
        workspace=WS,
    )
    env = make_env(root)
    voice = resolve_compose(env, dc_replace(SEL, voice="x-brand-voice")).voice
    assert voice.values["formality"] == 1  # the workspace layer shadowed (§12.1)
    assert voice.entry.field_provenance["formality"].scope == "workspace"


# ------------------------------------------------------------------------------------
# The voice selection chain (CA2, §12.3) + brand-authoritative elevation (BO2, §12.6)
# ------------------------------------------------------------------------------------


def _chain_root(tmp_path: Path, *, l2: str = BASE_L2, l3: str | None = None) -> Path:
    root = build_root(tmp_path, l2=l2, l3=l3)
    write_entry(root, "voices", "x-house-voice", "extends: clear-explainer\nenergy: 4\n")
    write_entry(root, "voices", "x-client-voice", "extends: clear-explainer\nwarmth: 4\n")
    # A persona that does NOT set default_voice → no CA2 insert (module docstring).
    write_entry(root, "personas", "x-plain-persona", "role: A generic evaluator.\n")
    write_entry(
        root, "recipes", "x-plain-recipe", "extends: explainer-post\npersona: x-plain-persona\n"
    )
    write_entry(root, "recipes", "x-voiced", "extends: explainer-post\nvoice: confident-advocate\n")
    return root


def test_chain_l2_when_persona_bundles_no_voice(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path))
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-plain-recipe"))
    assert compose.voice.entry_id == "clear-explainer"
    assert compose.voice_selected_by == RUNG_L2


def test_chain_l3_beats_l2(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path, l3="voice: x-client-voice\n"))
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-plain-recipe"))
    assert compose.voice.entry_id == "x-client-voice"
    assert compose.voice_selected_by == RUNG_L3


def test_chain_persona_default_voice_beats_scope_defaults(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path, l3="voice: x-client-voice\n"))
    compose = resolve_compose(env, SEL)  # technical-evaluator SETS default_voice
    assert compose.voice.entry_id == "clear-explainer"
    assert compose.voice_selected_by == "persona-default-voice"


def test_chain_recipe_beats_persona(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path))
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-voiced"))
    assert compose.voice.entry_id == "confident-advocate"
    assert compose.voice_selected_by == RUNG_L5


def test_chain_run_beats_recipe(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path))
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-voiced", voice="x-client-voice"))
    assert compose.voice.entry_id == "x-client-voice"
    assert compose.voice_selected_by == RUNG_L6


FLAGGED_L2 = (
    "voice:\n  entry: x-house-voice\n  authoritative: true\nlanguage: en\noutput_type: md\n"
)


def test_flag_b_beats_recipe_and_run_deviation_warns_once(tmp_path: Path) -> None:
    env = make_env(_chain_root(tmp_path, l2=FLAGGED_L2))
    # The bare flag (= strength b) beats through the recipe (§12.6).
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-voiced"))
    assert compose.voice.entry_id == "x-house-voice"
    assert compose.voice_selected_by == "brand-authoritative-b"
    # Only a run can deviate — warned, once per session.
    deviated = resolve_compose(env, dc_replace(SEL, recipe="x-voiced", voice="confident-advocate"))
    assert deviated.voice.entry_id == "confident-advocate"
    assert deviated.voice_selected_by == RUNG_L6
    keys = [w.key for w in deviated.warnings if w.key.startswith("brand-voice-deviation")]
    assert len(keys) == 1
    again = resolve_compose(env, dc_replace(SEL, recipe="x-voiced", voice="confident-advocate"))
    assert not [w for w in again.warnings if w.key.startswith("brand-voice-deviation")]


def test_flag_a_beats_persona_but_not_recipe(tmp_path: Path) -> None:
    l2 = FLAGGED_L2.replace("authoritative: true", "authoritative: a")
    env = make_env(_chain_root(tmp_path, l2=l2))
    compose = resolve_compose(env, SEL)  # persona default would win without the flag
    assert compose.voice.entry_id == "x-house-voice"
    assert compose.voice_selected_by == "brand-authoritative-a"
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-voiced"))
    assert compose.voice.entry_id == "confident-advocate"  # a stops below L5 (§12.6)
    assert compose.voice_selected_by == RUNG_L5


def test_flag_c_hard_lock_beats_the_run_and_surfaces(tmp_path: Path) -> None:
    l2 = FLAGGED_L2.replace("authoritative: true", "authoritative: c")
    env = make_env(_chain_root(tmp_path, l2=l2))
    compose = resolve_compose(env, dc_replace(SEL, voice="confident-advocate"))
    assert compose.voice.entry_id == "x-house-voice"  # opt-in hard-lock (§12.6)
    assert compose.voice_selected_by == "brand-authoritative-c"
    assert any(w.key.startswith("brand-voice-hard-lock") for w in compose.warnings)


def test_most_local_flag_arbitrates(tmp_path: Path) -> None:
    env = make_env(
        _chain_root(
            tmp_path,
            l2=FLAGGED_L2,
            l3="voice:\n  entry: x-client-voice\n  authoritative: b\n",
        )
    )
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-voiced"))
    assert compose.voice.entry_id == "x-client-voice"  # the client brand, not the house


# ------------------------------------------------------------------------------------
# Selection edges & loudness through the cascade
# ------------------------------------------------------------------------------------


def test_topic_required_when_nothing_supplies_it(tmp_path: Path) -> None:
    env = make_env(build_root(tmp_path))
    with pytest.raises(SelectionError, match="topic"):
        resolve_compose(env, RunSelection(recipe="explainer-post"))


def test_topic_from_workspace_default(tmp_path: Path) -> None:
    env = make_env(build_root(tmp_path, l3="topic: x-sample-topic\n"))
    compose = resolve_compose(env, RunSelection(recipe="explainer-post"))
    assert compose.topic.entry_id == "x-sample-topic"


def test_unknown_selection_ids_are_loud(tmp_path: Path) -> None:
    env = make_env(build_root(tmp_path))
    with pytest.raises(UnknownEntryError):
        resolve_compose(env, dc_replace(SEL, topic="x-no-such-topic"))
    with pytest.raises(UnknownEntryError):
        resolve_compose(env, dc_replace(SEL, recipe="x-no-such-recipe"))


def test_recipe_dangling_voice_is_loud_at_compose(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(root, "recipes", "x-bad", "extends: explainer-post\nvoice: x-no-such-voice\n")
    with pytest.raises(DanglingRefError):
        resolve_compose(make_env(root), dc_replace(SEL, recipe="x-bad"))


# ------------------------------------------------------------------------------------
# Overrides through the cascade (§21.4 API5; §12.5 CA6/CA7)
# ------------------------------------------------------------------------------------


def test_override_schema_guard_fires_at_env_construction(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    with pytest.raises(OverrideError):  # never ADD an attribute
        make_env(root, overrides=collect_overrides({"voice.undeclared": 1}))
    with pytest.raises(OverrideError):  # union on an ordered list (§11.1)
        make_env(
            root,
            overrides=collect_overrides(
                [{"path": "persona.objections", "op": "union", "value": ["x"]}]
            ),
        )


def test_platform_override_requires_a_selected_platform(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root, overrides=collect_overrides({"platform.reconcile_strategy": "split"}))
    compose = resolve_compose(env, SEL)
    with pytest.raises(OverrideError, match="ALREADY-SELECTED"):
        resolve_render(env, compose, SEL)  # no platform anywhere
    render = resolve_render(env, compose, dc_replace(SEL, platform="linkedin"))
    assert render.reconcile_strategy == "split"
    assert render.reconcile_strategy_provenance == RUNG_L6


def test_goal_override_with_empty_goal_set_is_refused(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(
        root,
        "recipes",
        "x-nogoals",
        "persona: technical-evaluator\nformat: short-opinion-post\n",
    )
    env = make_env(root, overrides=collect_overrides({"goal.kind": "action"}))
    with pytest.raises(OverrideError):
        resolve_compose(env, dc_replace(SEL, recipe="x-nogoals"))


def test_override_is_captured_in_the_effective_delta_and_the_id(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    subset, commits = ["x-src"], {"x-src": "abc123"}
    base = resolve_compose(make_env(root), SEL)
    base_id = ids.mint_artifact_id(
        base.artifact_preimage(source_subset=subset, source_commit=commits)
    )
    env = make_env(root, overrides=collect_overrides({"voice.energy": 5}))
    overridden = resolve_compose(env, SEL)
    # CA6: the override is visible in the effective delta (§7.2 resolved-overrides) …
    assert overridden.deltas()["voice"]["energy"] == 5
    assert "energy" not in base.deltas()["voice"]  # entry value 3 == floor 3
    # … and therefore in the id.
    new_id = ids.mint_artifact_id(
        overridden.artifact_preimage(source_subset=subset, source_commit=commits)
    )
    assert new_id != base_id


# ------------------------------------------------------------------------------------
# CM3: inline combine operators through the cascade (§12.4/§13.2)
# ------------------------------------------------------------------------------------


def test_union_suffix_in_recipe_values(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.tags: [alpha]\n")
    write_entry(
        root, "recipes", "x-tagged", "extends: explainer-post\nvalues:\n  voice.tags+: [beta]\n"
    )
    voice = resolve_compose(make_env(root), dc_replace(SEL, recipe="x-tagged")).voice
    assert voice.values["tags"] == ["alpha", "beta"]
    assert voice.provenance["tags"] == RUNG_L5


def test_wrapper_union_in_an_override(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.tags: [alpha]\n")
    env = make_env(
        root,
        overrides=collect_overrides({"voice.tags": {"combine": "union", "add": ["gamma"]}}),
    )
    voice = resolve_compose(env, SEL).voice
    assert voice.values["tags"] == ["alpha", "gamma"]
    assert voice.provenance["tags"] == RUNG_L6


def test_schema_default_union_fires_across_rungs_and_explicit_replace_stops_it(
    tmp_path: Path,
) -> None:
    # `audience` declares `combine: union`: bare bindings at two rungs UNION (§12.4).
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.audience: [insiders]\n")
    write_entry(
        root,
        "recipes",
        "x-aud",
        "extends: explainer-post\nvalues:\n  voice.audience: [newcomers]\n",
    )
    env = make_env(root)
    voice = resolve_compose(env, dc_replace(SEL, recipe="x-aud")).voice
    assert voice.values["audience"] == ["insiders", "newcomers"]
    # An explicit replace wrapper beats the schema default operator (CM3).
    env = make_env(
        root,
        overrides=collect_overrides({"voice.audience": {"combine": "replace", "add": ["runtime"]}}),
    )
    voice = resolve_compose(env, dc_replace(SEL, recipe="x-aud")).voice
    assert voice.values["audience"] == ["runtime"]


def test_union_on_list_refused_in_configured_values(tmp_path: Path) -> None:
    root = build_root(tmp_path, l3="values:\n  persona.objections+: [more]\n")
    with pytest.raises(CombineOperatorError):
        make_env(root)


# ------------------------------------------------------------------------------------
# CA9: advisory norms ride M2; hard limits provably never enter it (§12.7)
# ------------------------------------------------------------------------------------


def test_advisory_projection_merges_and_hard_limits_are_absent(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    compose = resolve_compose(env, SEL)
    render = resolve_render(env, compose, dc_replace(SEL, platform="linkedin"))
    assert render.platform is not None
    # The per-format projection refined the platform-wide norm (map-merge below L5).
    assert render.advisories == {"preferred_char_count": 1200, "hashtag_count_max": 5}
    assert render.platform.provenance["advisory_norms"] == RUNG_PROJECTION
    # THE CA9 acceptance: no hard limit among bound values — and no projection table.
    for never_bound in (
        "hard_limits",
        "format_advisories",
        "reconcile_strategy_defaults",
        "default_output_type",
        "destination",
    ):
        assert never_bound not in render.platform.values
    # The advisory class, by contrast, IS bound (rides M2).
    assert "advisory_norms" in render.platform.values


def test_advisory_deviation_warns_once(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(
        root,
        "recipes",
        "x-dev",
        "extends: explainer-post\nvalues:\n  platform.advisory_norms:\n"
        "    preferred_char_count: 900\n",
    )
    env = make_env(root)
    selection = dc_replace(SEL, recipe="x-dev", platform="linkedin")
    render = resolve_render(env, resolve_compose(env, selection), selection)
    assert render.advisories["preferred_char_count"] == 900  # the deviation binds …
    keys = [w.key for w in render.warnings if w.key.startswith("advisory-deviation")]
    assert keys == ["advisory-deviation:linkedin:preferred_char_count"]  # … warned once
    render_again = resolve_render(env, resolve_compose(env, selection), selection)
    assert not [w for w in render_again.warnings if w.key.startswith("advisory-deviation")]


def test_hard_limits_are_unbindable_at_every_rung(tmp_path: Path) -> None:
    # L2 (env construction).
    root = build_root(
        tmp_path, l2=BASE_L2 + "values:\n  platform.hard_limits:\n    post_char_limit: 1\n"
    )
    with pytest.raises(HardLimitBindingError):
        make_env(root)
    # L5 (recipe values, at compose).
    root = build_root(tmp_path.joinpath("second"))
    write_entry(
        root,
        "recipes",
        "x-hard",
        "extends: explainer-post\nvalues:\n  platform.hard_limits:\n    post_char_limit: 1\n",
    )
    with pytest.raises(HardLimitBindingError):
        resolve_compose(make_env(root), dc_replace(SEL, recipe="x-hard"))
    # L6 (overrides — refused at collect; also covered in tests/test_overrides.py).
    with pytest.raises(OverrideError):
        collect_overrides({"platform.hard_limits": {"post_char_limit": 1}})


def test_projection_tables_and_m3_carriers_are_unbindable(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  platform.format_advisories: {}\n")
    with pytest.raises(UnbindableAttributeError):
        make_env(root)
    root = build_root(
        tmp_path.joinpath("second"),
        l2=BASE_L2 + "values:\n  goal.source_selection:\n    require: []\n",
    )
    with pytest.raises(UnbindableAttributeError, match="M2 never touches"):
        make_env(root)


# ------------------------------------------------------------------------------------
# Reconcile-strategy: the §12.3 two-tier defaulting + L5/L6 overrides
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("platform", "format_id", "strategy", "provenance"),
    [
        ("linkedin", "short-opinion-post", "adapt", RUNG_PROJECTION),
        ("linkedin", "long-form-essay", "split", RUNG_PROJECTION),
        ("github", "long-form-essay", "pass", RUNG_PROJECTION),
        ("github", "short-opinion-post", "adapt", RUNG_L0),  # no table row → the floor
    ],
)
def test_strategy_two_tier_defaulting(
    tmp_path: Path, platform: str, format_id: str, strategy: str, provenance: str
) -> None:
    env = make_env(build_root(tmp_path))
    selection = dc_replace(SEL, platform=platform, format=format_id)
    render = resolve_render(env, resolve_compose(env, selection), selection)
    assert render.reconcile_strategy == strategy
    assert render.reconcile_strategy_provenance == provenance


def test_strategy_recipe_l5_beats_the_table(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(
        root,
        "recipes",
        "x-strat",
        "extends: explainer-post\nvalues:\n  platform.reconcile_strategy: truncate\n",
    )
    env = make_env(root)
    selection = dc_replace(SEL, recipe="x-strat", platform="linkedin")
    render = resolve_render(env, resolve_compose(env, selection), selection)
    assert render.reconcile_strategy == "truncate"
    assert render.reconcile_strategy_provenance == RUNG_L5


# ------------------------------------------------------------------------------------
# Output-type weak default & language defaults (§12.3)
# ------------------------------------------------------------------------------------


def test_platform_weak_output_type_beats_l2_loses_to_explicit(tmp_path: Path) -> None:
    l2 = "voice: clear-explainer\nlanguage: en\noutput_type: html\n"
    root = build_root(tmp_path, l2=l2)
    env = make_env(root)
    compose = resolve_compose(env, SEL)
    # linkedin implies md — the weak default beats the L2 global …
    render = resolve_render(env, compose, dc_replace(SEL, platform="linkedin"))
    assert render.output_type.entry_id == "md"
    # … but any explicit run coordinate beats it.
    render = resolve_render(env, compose, dc_replace(SEL, platform="linkedin", output_type="docx"))
    assert render.output_type.entry_id == "docx"
    # An explicit L3 value beats it too.
    root = build_root(tmp_path.joinpath("second"), l2=l2, l3="output_type: html\n")
    env = make_env(root)
    render = resolve_render(env, resolve_compose(env, SEL), dc_replace(SEL, platform="linkedin"))
    assert render.output_type.entry_id == "html"


def test_language_l3_beats_l2_and_run_beats_both(tmp_path: Path) -> None:
    root = build_root(tmp_path, l3="language: x-xx\n")
    write_entry(root, "languages", "x-xx", "name: Test Language\n")
    env = make_env(root)
    compose = resolve_compose(env, SEL)
    assert resolve_render(env, compose, SEL).language.entry_id == "x-xx"
    assert resolve_render(env, compose, dc_replace(SEL, language="en")).language.entry_id == "en"


def test_multiple_pins_require_an_explicit_coordinate(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(
        root, "recipes", "x-multi", "extends: explainer-post\nplatforms: [github, linkedin]\n"
    )
    env = make_env(root)
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-multi"))
    with pytest.raises(AmbiguousSelectionError):
        resolve_render(env, compose, dc_replace(SEL, recipe="x-multi"))
    render = resolve_render(env, compose, dc_replace(SEL, recipe="x-multi", platform="github"))
    assert render.platform is not None and render.platform.entry_id == "github"


def test_single_pin_routes_without_a_coordinate(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    write_entry(root, "recipes", "x-pinned", "extends: explainer-post\nplatforms: [github]\n")
    env = make_env(root)
    selection = dc_replace(SEL, recipe="x-pinned")
    render = resolve_render(env, resolve_compose(env, selection), selection)
    assert render.platform is not None and render.platform.entry_id == "github"


# ------------------------------------------------------------------------------------
# The goal-set (§12.3: L0 baseline · L2/L3 optional · L5 primary · L6)
# ------------------------------------------------------------------------------------


def test_goal_set_selection_replaces_and_canonicalizes(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    env = make_env(root)
    compose = resolve_compose(env, dc_replace(SEL, goals=("try-it", "explain")))
    assert {g.entry_id for g in compose.goals} == {"try-it", "explain"}
    preimage = compose.artifact_preimage(source_subset=["x-src"], source_commit={"x-src": "abc123"})
    assert [pair[0] for pair in preimage["goals"]] == ["explain", "try-it"]  # sorted
    with pytest.raises(SelectionError, match="duplicate"):
        resolve_compose(env, dc_replace(SEL, goals=("explain", "explain")))


def test_goal_set_scope_rungs_replace_each_other(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "goals: [explain]\n", l3="goals: [convince]\n")
    write_entry(
        root,
        "recipes",
        "x-nogoals",
        "persona: technical-evaluator\nformat: short-opinion-post\n",
    )
    env = make_env(root)
    # The recipe sets no goal-set → L3 replaces L2 (goal-set default combine = replace).
    compose = resolve_compose(env, dc_replace(SEL, recipe="x-nogoals"))
    assert [g.entry_id for g in compose.goals] == ["convince"]
    # The recipe's own set (L5) replaces the scope defaults.
    compose = resolve_compose(env, SEL)
    assert [g.entry_id for g in compose.goals] == ["explain"]
    # An explicit empty run set replaces everything (the L0 baseline is empty anyway).
    compose = resolve_compose(env, dc_replace(SEL, goals=()))
    assert compose.goals == ()


# ------------------------------------------------------------------------------------
# CA10 / M3 lane separation (§12.1, §12.7)
# ------------------------------------------------------------------------------------


def test_m3_lanes_stay_separate(tmp_path: Path) -> None:
    l3 = "source_selection:\n  require:\n    - traceability is true\n  prefer:\n    - trusted: 1\n"
    root = build_root(tmp_path, l3=l3)
    env = make_env(root)
    compose = resolve_compose(env, dc_replace(SEL, goals=("convince", "explain")))
    m3 = compose.m3_inputs
    # The workspace baseline is carried exactly as authored — no goal nudge folded in.
    assert m3.workspace_baseline == {
        "require": ["traceability is true"],
        "prefer": [{"trusted": 1}],
    }
    # Goal-implied clauses ride their own lane, keyed by goal id; goals without
    # clauses contribute nothing (explain sets no source_selection).
    assert [goal_id for goal_id, _ in m3.goal_implied] == ["convince"]
    convince_clauses = dict(m3.goal_implied)["convince"]
    assert convince_clauses["prefer"] == [{"authoritative": 2}]
    # CA10: the nudge never appears in any other dimension's bound values.
    for bound in (compose.topic, compose.persona, compose.format, compose.voice):
        assert "source_selection" not in bound.values


# ------------------------------------------------------------------------------------
# MIG-6 through the cascade (§11.5)
# ------------------------------------------------------------------------------------


def test_stale_entry_blocks_compose(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    schema_path = root / "topics" / "_schema.yaml"
    text = schema_path.read_text(encoding="utf-8")
    text = text.replace("schema_version: 1", "schema_version: 2")
    text = text.replace("definition_version: 1", "definition_version: 2")
    schema_path.write_text(text, encoding="utf-8")
    write_entry(root, "topics", "x-stale-topic", "why: Authored under v1.\n", workspace=WS)
    env = make_env(root)
    with pytest.raises(StaleEntryError) as exc:
        resolve_compose(env, dc_replace(SEL, topic="x-stale-topic"))
    assert exc.value.code == "drift-block"


# ------------------------------------------------------------------------------------
# Identity integration (§7.2): the cascade feeds ids.build_artifact_preimage
# ------------------------------------------------------------------------------------


def test_cascade_resolution_mints_a_stable_artifact_id(tmp_path: Path) -> None:
    root = build_root(tmp_path, l2=BASE_L2 + "values:\n  voice.energy: 4\n")
    subset, commits = ["x-src"], {"x-src": "abc123"}

    def mint() -> str:
        env = make_env(root)  # a FRESH env: fresh resolver, fresh fold
        compose = resolve_compose(env, SEL)
        return ids.mint_artifact_id(
            compose.artifact_preimage(source_subset=subset, source_commit=commits)
        )

    first, second = mint(), mint()
    assert first == second  # same inputs re-resolve to the same id (§7.2/§21.8)
    assert ids.parse_id(first).level == "artifact"


def test_floor_equal_override_churns_nothing(tmp_path: Path) -> None:
    root = build_root(tmp_path)
    subset, commits = ["x-src"], {"x-src": "abc123"}
    base = resolve_compose(make_env(root), SEL)
    base_id = ids.mint_artifact_id(
        base.artifact_preimage(source_subset=subset, source_commit=commits)
    )
    # An override equal to the already-effective value changes no delta and no id.
    env = make_env(root, overrides=collect_overrides({"voice.humor": 2}))
    same = resolve_compose(env, SEL)
    same_id = ids.mint_artifact_id(
        same.artifact_preimage(source_subset=subset, source_commit=commits)
    )
    assert same_id == base_id



def test_artifact_preimage_threads_the_outline_digest(tmp_path: Path) -> None:
    # DR-3 §7.2: the outline_digest pass-through. The default (None) path is byte-identical
    # to the pre-DR-3 4-key preimage; a supplied 64-char lowercase-hex digest flows through
    # to build_artifact_preimage, enters as one top-level key, and changes the id.
    root = build_root(tmp_path)
    env = make_env(root)
    compose = resolve_compose(env, SEL)
    subset, commits = ["x-src"], {"x-src": "abc123"}
    base = compose.artifact_preimage(source_subset=subset, source_commit=commits)
    explicit_none = compose.artifact_preimage(
        source_subset=subset, source_commit=commits, outline_digest=None
    )
    assert "outline-digest" not in base
    assert base == explicit_none  # default path unchanged, byte-identical
    assert ids.mint_artifact_id(base) == ids.mint_artifact_id(explicit_none)
    digest = "a" * 64
    driven = compose.artifact_preimage(
        source_subset=subset, source_commit=commits, outline_digest=digest
    )
    assert driven["outline-digest"] == digest
    assert ids.mint_artifact_id(driven) != ids.mint_artifact_id(base)
