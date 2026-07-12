"""Tests for pipeline/migration.py — plan step 12 (design §11.6, MIG-1…MIG-7).

Covers: the declarative append-only step registry (forward-only: a lower-target entry is
refused); the ONE fold over (entry-stamp, current] (skip-safe N-3 → current in one run;
empty interval no-op; composition in registry order); the 1-year window BLOCK with the
design's take-responsibility message; MIG-4 binary-by-shape (deterministic auto-apply vs
prompt → the decisions-needed worklist, grouped, group-defaulted, RESUMABLE, object-atomic
re-stamp); MIG-7 config-only scope (framework entries skipped, artifact stores untouched,
`metadata` untargetable); the CLI + `scripts/migrate.sh` (user-triggered, idempotent,
NOT a `pipeline` subcommand).

All fixture content is obviously generic; every document lives under pytest tmp_path.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from pipeline.drift import DriftKind, check_entry
from pipeline.migration import (
    CODE_AMBIGUOUS_MIGRATION_DECISIONS,
    CODE_OUT_OF_WINDOW,
    STATUS_BLOCKED,
    STATUS_ERROR,
    STATUS_MIGRATED,
    STATUS_NEEDS_INPUT,
    STATUS_SKIPPED_FRAMEWORK,
    STATUS_UP_TO_DATE,
    WINDOW_DAYS,
    DecisionSet,
    ForwardOnlyError,
    MigrationError,
    OutOfWindowError,
    RegistryError,
    StepRegistry,
    TotalityError,
    WorklistError,
    _dump_yaml,
    fold_entry,
    load_step_registry,
    load_step_registry_text,
    load_worklist_decisions,
    main,
    require_in_window,
    run_migration,
)
from pipeline.schema import SCHEMA_FILENAME, load_schema_text
from pipeline.yamlio import load_yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = date(2026, 7, 12)
IN_WINDOW = date(2026, 6, 1)  # comfortably inside the 1-year window at NOW

GADGETS_SCHEMA = """\
schema_version: 5
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 4
  mood:
    type:
      type: enum
      values: [calm, bold]
    default: calm
    definition: The example mood token.
    definition_version: 5
  size:
    type: number
    default: 1
    definition: The example size number.
    definition_version: 1
"""


def make_schema(text: str = GADGETS_SCHEMA, collection: str = "gadgets"):
    return load_schema_text(text, collection=collection)


def entry_text(
    entry_id: str,
    stamp: int,
    attrs: str = "",
    provenance: str = "instance",
    body: str = "\nBody prose.\n",
) -> str:
    fm = f"id: {entry_id}\nprovenance: {provenance}\nschema_version: {stamp}\n"
    if attrs:
        fm += attrs.rstrip("\n") + "\n"
    return f"---\n{fm}---{body}"


def make_entry(schema, entry_id: str, stamp: int, attrs: str = "", provenance: str = "instance"):
    from pipeline.drift import parse_entry_lenient

    return parse_entry_lenient(
        entry_text(entry_id, stamp, attrs, provenance), filename_slug=entry_id, schema=schema
    )


def write_schema(root: Path, text: str = GADGETS_SCHEMA, collection: str = "gadgets") -> Path:
    d = root / collection
    d.mkdir(parents=True, exist_ok=True)
    (d / SCHEMA_FILENAME).write_text(text, encoding="utf-8")
    return d


def write_entry(
    root: Path,
    collection: str,
    entry_id: str,
    stamp: int,
    attrs: str = "",
    provenance: str = "instance",
) -> Path:
    d = root / collection
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{entry_id}.md"
    p.write_text(entry_text(entry_id, stamp, attrs, provenance), encoding="utf-8")
    return p


def step_yaml(
    sid: str,
    version: int,
    action: str,
    released: date = IN_WINDOW,
    collection: str = "gadgets",
    attribute: str | None = None,
    scope: str | None = None,
    suggested: str | None = None,
) -> str:
    lines = [
        f"  - id: {sid}",
        f"    version: {version}",
        f"    released: {released.isoformat()}",
        f"    collection: {collection}",
    ]
    if scope:
        lines.append(f"    scope: {scope}")
    if attribute:
        lines.append(f"    attribute: {attribute}")
    lines.append(action)  # pre-indented action block
    if suggested is not None:
        lines.append(f"    suggested: {suggested}")
    return "\n".join(lines) + "\n"


def registry_of(*steps: str) -> StepRegistry:
    return load_step_registry_text("steps:\n" + "".join(steps), source="<test>")


MAP_COLOR_V4 = step_yaml("4-gadgets-color-map", 4, "    map:\n      teal: blue", attribute="color")
PROMPT_MOOD_V5 = step_yaml(
    "5-gadgets-mood-prompt",
    5,
    "    prompt: mood semantics changed; choose calm or bold per entry",
    attribute="mood",
    suggested="calm",
)


def outcomes_by_id(result):
    return {o.entry_id: o for o in result.outcomes}


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------------------
# MIG-1: the registry — declarative, append-only, forward-only, binary by shape (MIG-4)
# ---------------------------------------------------------------------------------------


class TestRegistry:
    def test_valid_registry_parses_with_shapes_classified(self):
        reg = registry_of(MAP_COLOR_V4, PROMPT_MOOD_V5)
        m, p = reg.steps
        assert m.action == "map" and m.is_deterministic  # MIG-4: shape IS the class
        assert p.action == "prompt" and not p.is_deterministic
        assert m.value_map == {"teal": "blue"}
        assert p.prompt.startswith("mood semantics") and p.suggested == "calm"

    def test_forward_only_lower_target_refused(self):
        # MIG-1: append-only + forward-only — a step appended with a LOWER trigger
        # version than its predecessor is refused (no inverse is representable).
        with pytest.raises(ForwardOnlyError, match="forward-only"):
            registry_of(PROMPT_MOOD_V5, MAP_COLOR_V4)  # v5 then v4

    def test_no_inverse_shape_exists(self):
        bad = step_yaml("4-gadgets-revert", 4, "    revert: true", attribute="color")
        with pytest.raises(RegistryError, match="forward-only is structural"):
            registry_of(bad)

    def test_exactly_one_shape_map_and_prompt_refused(self):
        both = step_yaml(
            "4-gadgets-two-shapes",
            4,
            "    map:\n      teal: blue\n    prompt: also ambiguous?",
            attribute="color",
        )
        with pytest.raises(RegistryError, match="EXACTLY ONE"):
            registry_of(both)

    def test_no_shape_refused(self):
        neither = step_yaml("4-gadgets-no-shape", 4, "    # nothing", attribute="color")
        with pytest.raises(RegistryError, match="EXACTLY ONE"):
            registry_of(neither)

    def test_reserved_attribute_targets_refused(self):
        # MIG-7: the metadata bag (and the envelope) are structurally untouchable.
        for name in ("metadata", "id", "schema_version", "provenance"):
            bad = step_yaml("4-gadgets-bad", 4, "    drop: true", attribute=name)
            with pytest.raises(RegistryError, match="reserved"):
                registry_of(bad)

    def test_duplicate_step_id_refused(self):
        with pytest.raises(RegistryError, match="append-only"):
            registry_of(MAP_COLOR_V4, MAP_COLOR_V4)

    def test_released_must_be_a_bare_date(self):
        bad = MAP_COLOR_V4.replace("released: 2026-06-01", "released: '2026-06-01'")
        with pytest.raises(RegistryError, match="bare YAML date"):
            registry_of(bad)

    def test_scope_shape_pairings_enforced(self):
        with pytest.raises(RegistryError, match="object-scope"):
            registry_of(step_yaml("4-gadgets-om", 4, "    map:\n      a: b", scope="object"))
        with pytest.raises(RegistryError, match="object-scope"):
            registry_of(
                step_yaml(
                    "4-gadgets-oe",
                    4,
                    "    edit:\n      set:\n        color: red",
                    scope="object",
                    attribute="color",
                )
            )
        with pytest.raises(RegistryError, match="attribute-scope"):
            registry_of(
                step_yaml(
                    "4-gadgets-ae",
                    4,
                    "    edit:\n      set:\n        color: red",
                    attribute="color",
                )
            )

    def test_suggested_only_with_prompt(self):
        bad = step_yaml("4-gadgets-sug", 4, "    drop: true", attribute="color", suggested="blue")
        with pytest.raises(RegistryError, match="suggested"):
            registry_of(bad)

    def test_drop_must_be_exactly_true(self):
        bad = step_yaml("4-gadgets-drop", 4, "    drop: maybe", attribute="color")
        with pytest.raises(RegistryError, match="exactly"):
            registry_of(bad)

    def test_closed_vocabulary(self):
        bad = MAP_COLOR_V4.rstrip("\n") + "\n    undo_hint: nope\n"
        with pytest.raises(RegistryError, match="unknown key"):
            registry_of(bad)

    def test_directive_refused(self):
        with pytest.raises(RegistryError, match="%-directive"):
            load_step_registry_text("%YAML 1.1\n---\nsteps: []\n", source="<test>")

    def test_missing_file_is_the_empty_registry(self, tmp_path):
        reg = load_step_registry(tmp_path / "absent.yaml")
        assert reg.steps == ()
        with pytest.raises(RegistryError, match="does not exist"):
            load_step_registry(tmp_path / "absent.yaml", missing_ok=False)

    def test_interval_selection_is_half_open(self):
        reg = registry_of(MAP_COLOR_V4, PROMPT_MOOD_V5)
        assert [s.id for s in reg.steps_for("gadgets", after=3, up_to=5)] == [
            "4-gadgets-color-map",
            "5-gadgets-mood-prompt",
        ]
        # `after` is EXCLUSIVE: a step AT the stamp was already applied.
        assert [s.id for s in reg.steps_for("gadgets", after=4, up_to=5)] == [
            "5-gadgets-mood-prompt",
        ]
        # `up_to` is INCLUSIVE; other collections never match.
        assert reg.steps_for("gadgets", after=5, up_to=5) == []
        assert reg.steps_for("widgets", after=0, up_to=9) == []


# ---------------------------------------------------------------------------------------
# MIG-2: the 1-year window (dates injected, never ambient)
# ---------------------------------------------------------------------------------------


class TestWindow:
    def test_within_window_is_migratable(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        reg = registry_of(MAP_COLOR_V4)
        assert reg.out_of_window(schema, entry, now=NOW) is None

    def test_boundary_exactly_one_year_is_still_inside(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        boundary = NOW - timedelta(days=WINDOW_DAYS)
        reg = registry_of(
            step_yaml(
                "4-gadgets-color-map",
                4,
                "    map:\n      teal: blue",
                released=boundary,
                attribute="color",
            )
        )
        assert reg.out_of_window(schema, entry, now=NOW) is None

    def test_older_than_one_year_blocks_with_the_design_message(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        stale = NOW - timedelta(days=WINDOW_DAYS + 1)
        reg = registry_of(
            step_yaml(
                "4-gadgets-color-map",
                4,
                "    map:\n      teal: blue",
                released=stale,
                attribute="color",
            )
        )
        msg = reg.out_of_window(schema, entry, now=NOW)
        assert msg is not None
        # MIG-2's own words + the take-responsibility path (user-owned, unsupported).
        assert "past the 1-year support window" in msg
        assert "regenerate or hand-fix; unsupported" in msg
        assert "user-owned" in msg and "UNSUPPORTED" in msg
        assert "git" in msg.lower()

    def test_uncovered_meaning_change_is_out_of_window(self):
        # A meaning change with NO shipped step = pruned past the window (or an SV11
        # lint defect upstream) — same unsupported state, same block.
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        msg = StepRegistry().out_of_window(schema, entry, now=NOW)
        assert msg is not None and "no shipped migration step" in msg

    def test_unaffecting_old_steps_do_not_block(self):
        # The stale step targets an attribute this entry does not set: no block.
        schema = make_schema()
        entry = make_entry(schema, "x-a", 4, "size: 2")
        stale = NOW - timedelta(days=WINDOW_DAYS + 100)
        reg = registry_of(
            step_yaml(
                "5-gadgets-mood-prompt",
                5,
                "    prompt: pick a mood",
                released=stale,
                attribute="mood",
            )
        )
        assert reg.out_of_window(schema, entry, now=NOW) is None

    def test_current_entry_never_out_of_window(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 5, "color: red")
        assert StepRegistry().out_of_window(schema, entry, now=NOW) is None

    def test_require_in_window_raises_typed_exception(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        with pytest.raises(OutOfWindowError, match="past the 1-year support window") as ei:
            require_in_window(schema, entry, StepRegistry(), now=NOW)
        assert ei.value.code == CODE_OUT_OF_WINDOW == "out-of-window"

    def test_drift_check_entry_consumes_the_real_oracle(self):
        # Integration: the migration registry IS drift's WindowOracle (MIG-6).
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        findings = check_entry(schema, entry, window=StepRegistry(), now=NOW)
        assert DriftKind.OUT_OF_WINDOW in {f.kind for f in findings}


# ---------------------------------------------------------------------------------------
# The fold (MIG-1/MIG-4): deterministic shapes, composition, totality, decisions
# ---------------------------------------------------------------------------------------


class TestFold:
    def test_map_applies_and_composes_in_registry_order(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal")
        reg = registry_of(
            step_yaml("4-gadgets-map-a", 4, "    map:\n      teal: blue", attribute="color"),
            step_yaml("5-gadgets-map-b", 5, "    map:\n      blue: green", attribute="color"),
        )
        fold = fold_entry(schema, entry, reg.steps_for("gadgets", after=3, up_to=5), DecisionSet())
        assert fold.resolved
        assert fold.attributes == {"color": "green"}  # teal -> blue -> green, in order
        assert fold.applied == ["4-gadgets-map-a", "5-gadgets-map-b"]

    def test_map_skips_entries_not_setting_the_attribute(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "size: 2")
        reg = registry_of(MAP_COLOR_V4)
        fold = fold_entry(schema, entry, list(reg.steps), DecisionSet())
        assert fold.resolved and fold.attributes == {"size": 2} and fold.applied == []

    def test_totality_violation_is_loud(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: magenta")
        reg = registry_of(MAP_COLOR_V4)  # maps teal only
        with pytest.raises(TotalityError, match="TOTAL"):
            fold_entry(schema, entry, list(reg.steps), DecisionSet())

    def test_rename_and_drop(self):
        # Current schema declares `colour` (renamed at v4); `legacy` was removed at v5.
        schema_text = GADGETS_SCHEMA.replace("  color:", "  colour:")
        schema = make_schema(schema_text)
        entry = make_entry(schema, "x-a", 3, "color: red\nlegacy: 7\nsize: 2")
        reg = registry_of(
            step_yaml("4-gadgets-rename", 4, "    rename_to: colour", attribute="color"),
            step_yaml("5-gadgets-droplegacy", 5, "    drop: true", attribute="legacy"),
        )
        fold = fold_entry(schema, entry, list(reg.steps), DecisionSet())
        assert fold.resolved
        assert fold.attributes == {"colour": "red", "size": 2}

    def test_rename_collision_refused_loudly(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: red\nmood: calm")
        reg = registry_of(step_yaml("4-gadgets-rn", 4, "    rename_to: mood", attribute="color"))
        with pytest.raises(MigrationError, match="lossless"):
            fold_entry(schema, entry, list(reg.steps), DecisionSet())

    def test_object_scope_edit_escape_hatch(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: red\nlegacy: 7")
        reg = registry_of(
            step_yaml(
                "4-gadgets-objedit",
                4,
                "    edit:\n      set:\n        mood: bold\n      drop: [legacy]",
                scope="object",
            )
        )
        fold = fold_entry(schema, entry, list(reg.steps), DecisionSet())
        assert fold.resolved
        assert fold.attributes == {"color": "red", "mood": "bold"}

    def test_undecided_prompts_pend_as_a_union_across_versions(self):
        # MIG-5: a skip-span migration surfaces the UNION of pending decisions in ONE
        # pass — both prompts pend; nothing half-applies.
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: teal\nmood: calm")
        reg = registry_of(
            step_yaml("4-gadgets-colorq", 4, "    prompt: pick a color", attribute="color"),
            PROMPT_MOOD_V5,
        )
        fold = fold_entry(schema, entry, list(reg.steps), DecisionSet())
        assert not fold.resolved
        assert [s.id for s in fold.pending] == ["4-gadgets-colorq", "5-gadgets-mood-prompt"]

    def test_group_decision_fans_and_object_decision_overrides(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 4, "mood: calm")
        reg = registry_of(PROMPT_MOOD_V5)
        group = DecisionSet(group={"5-gadgets-mood-prompt": "bold"})
        fold = fold_entry(schema, entry, list(reg.steps), group)
        assert fold.resolved and fold.attributes == {"mood": "bold"}
        override = DecisionSet(
            group={"5-gadgets-mood-prompt": "bold"},
            per_object={("5-gadgets-mood-prompt", "x-a"): "calm"},
        )
        fold = fold_entry(schema, entry, list(reg.steps), override)
        assert fold.resolved and fold.attributes == {"mood": "calm"}

    def test_invalid_decision_pends_with_error_never_applies(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 4, "mood: calm")
        reg = registry_of(PROMPT_MOOD_V5)
        bad = DecisionSet(group={"5-gadgets-mood-prompt": "furious"})  # not in enum
        fold = fold_entry(schema, entry, list(reg.steps), bad)
        assert not fold.resolved
        assert fold.attributes["mood"] == "calm"  # untouched
        assert any("invalid-migration-decision" in e for e in fold.errors)

    def test_suggested_is_never_auto_applied(self):
        # §11.5: "never a silent partial-map guess" — the authored suggestion is
        # display-only; with no decision the step PENDS.
        schema = make_schema()
        entry = make_entry(schema, "x-a", 4, "mood: calm")
        reg = registry_of(PROMPT_MOOD_V5)  # suggested: calm
        fold = fold_entry(schema, entry, list(reg.steps), DecisionSet())
        assert not fold.resolved and [s.id for s in fold.pending] == ["5-gadgets-mood-prompt"]

    def test_object_scope_decision_must_be_a_mapping(self):
        schema = make_schema()
        entry = make_entry(schema, "x-a", 3, "color: red")
        reg = registry_of(
            step_yaml("4-gadgets-objq", 4, "    prompt: rework this object", scope="object")
        )
        good = DecisionSet(group={"4-gadgets-objq": {"mood": "bold"}})
        fold = fold_entry(schema, entry, list(reg.steps), good)
        assert fold.resolved and fold.attributes == {"color": "red", "mood": "bold"}
        bad = DecisionSet(group={"4-gadgets-objq": "bold"})
        fold = fold_entry(schema, entry, list(reg.steps), bad)
        assert not fold.resolved and any("mapping" in e for e in fold.errors)


# ---------------------------------------------------------------------------------------
# The runner: skip-safe fold, no-op, blocks, the resumable worklist, object-atomicity
# ---------------------------------------------------------------------------------------


def write_registry(root: Path, *steps: str) -> Path:
    p = root / "pipeline" / "migrations.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("steps:\n" + "".join(steps), encoding="utf-8")
    return p


def run(root: Path, *steps: str, now: date = NOW):
    registry = load_step_registry(write_registry(root, *steps))
    worklist = root / "instance" / "ops" / "migration-worklist.yaml"
    return run_migration(root, registry=registry, now=now, worklist_path=worklist)


def set_decisions(root: Path, group: dict | None = None, per_object: dict | None = None):
    """Edit ONLY the decision slots of the generated worklist (what a human does)."""
    p = root / "instance" / "ops" / "migration-worklist.yaml"
    data = load_yaml(p.read_text(encoding="utf-8"))
    for g in data["groups"]:
        if group and g["step"] in group:
            g["decision"] = group[g["step"]]
        for obj in g["objects"]:
            if per_object and (g["step"], obj["id"]) in per_object:
                obj["decision"] = per_object[(g["step"], obj["id"])]
    p.write_text(_dump_yaml(data), encoding="utf-8")


class TestRunner:
    def test_skip_safe_fold_three_versions_in_one_run(self, tmp_path):
        # Version N-3 -> current in ONE run: stamp 2, current 5, steps at v3/v4/v5.
        schema_text = GADGETS_SCHEMA.replace("  color:", "  colour:")
        write_schema(tmp_path, schema_text)
        p = write_entry(tmp_path, "gadgets", "x-span", 2, "color: teal\nlegacy: 7\nsize: 3")
        result = run(
            tmp_path,
            step_yaml("3-gadgets-rename", 3, "    rename_to: colour", attribute="color"),
            step_yaml("4-gadgets-map", 4, "    map:\n      teal: blue", attribute="colour"),
            step_yaml("5-gadgets-drop", 5, "    drop: true", attribute="legacy"),
        )
        o = outcomes_by_id(result)["x-span"]
        assert o.status == STATUS_MIGRATED
        assert o.old_stamp == 2 and o.new_stamp == 5
        text = p.read_text(encoding="utf-8")
        assert "schema_version: 5" in text
        assert "colour: blue" in text and "legacy" not in text
        assert text.endswith("---\nBody prose.\n")  # body verbatim (MIG-7: config only)
        assert result.exit_code() == 0
        # The rename step composed BEFORE the map (registry order): the map targeted the
        # NEW name — proof the fold is one ordered pass, not per-step scans.

    def test_already_current_is_a_structural_no_op(self, tmp_path):
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-new", 5, "color: red")
        before = p.read_bytes()
        result = run(tmp_path, MAP_COLOR_V4)
        assert outcomes_by_id(result)["x-new"].status == STATUS_UP_TO_DATE
        assert p.read_bytes() == before  # empty interval -> nothing written (MIG-1)
        assert result.exit_code() == 0

    def test_idempotent_second_run_is_a_no_op(self, tmp_path):
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-a", 3, "color: teal")
        assert outcomes_by_id(run(tmp_path, MAP_COLOR_V4))["x-a"].status == STATUS_MIGRATED
        after_first = p.read_bytes()
        second = run(tmp_path, MAP_COLOR_V4)
        assert outcomes_by_id(second)["x-a"].status == STATUS_UP_TO_DATE
        assert p.read_bytes() == after_first

    def test_out_of_window_blocks_loudly_and_touches_nothing(self, tmp_path):
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-old", 3, "color: teal")
        before = p.read_bytes()
        stale = NOW - timedelta(days=WINDOW_DAYS + 1)
        result = run(
            tmp_path,
            step_yaml(
                "4-gadgets-color-map",
                4,
                "    map:\n      teal: blue",
                released=stale,
                attribute="color",
            ),
        )
        o = outcomes_by_id(result)["x-old"]
        assert o.status == STATUS_BLOCKED
        assert o.code == CODE_OUT_OF_WINDOW
        assert "past the 1-year support window" in o.detail
        assert "regenerate or hand-fix; unsupported" in o.detail
        assert "user-owned" in o.detail  # the take-responsibility message
        assert p.read_bytes() == before
        assert result.exit_code() == 1

    def test_ambiguous_halts_into_worklist_then_resumes(self, tmp_path):
        # MIG-4 prompt shape -> MIG-5 worklist -> human decision -> resume -> re-stamp.
        write_schema(tmp_path)
        pa = write_entry(tmp_path, "gadgets", "x-a", 4, "mood: calm")
        pb = write_entry(tmp_path, "gadgets", "x-b", 4, "mood: calm")
        before = (pa.read_bytes(), pb.read_bytes())

        result = run(tmp_path, PROMPT_MOOD_V5)
        by_id = outcomes_by_id(result)
        assert by_id["x-a"].status == STATUS_NEEDS_INPUT
        assert by_id["x-a"].code == CODE_AMBIGUOUS_MIGRATION_DECISIONS
        assert result.exit_code() == 3
        assert (pa.read_bytes(), pb.read_bytes()) == before  # nothing half-applied

        wl = tmp_path / "instance" / "ops" / "migration-worklist.yaml"
        assert result.worklist_path == str(wl)
        data = load_yaml(wl.read_text(encoding="utf-8"))
        [group] = data["groups"]  # grouped BY CHANGE (MIG-5)
        assert group["step"] == "5-gadgets-mood-prompt"
        assert group["decision"] is None  # suggested is displayed, never pre-decided
        assert group["suggested"] == "calm"
        assert [o["id"] for o in group["objects"]] == ["x-a", "x-b"]
        assert all(o["decision"] is None for o in group["objects"])
        assert all(o["current_value"] == "calm" for o in group["objects"])

        # ONE group-level answer fans across every config sharing the change.
        set_decisions(tmp_path, group={"5-gadgets-mood-prompt": "bold"})
        resumed = run(tmp_path, PROMPT_MOOD_V5)
        by_id = outcomes_by_id(resumed)
        assert by_id["x-a"].status == by_id["x-b"].status == STATUS_MIGRATED
        assert "mood: bold" in pa.read_text(encoding="utf-8")
        assert "mood: bold" in pb.read_text(encoding="utf-8")
        assert not wl.exists() and resumed.worklist_removed
        assert resumed.exit_code() == 0

    def test_per_object_decision_overrides_the_group(self, tmp_path):
        write_schema(tmp_path)
        pa = write_entry(tmp_path, "gadgets", "x-a", 4, "mood: calm")
        pb = write_entry(tmp_path, "gadgets", "x-b", 4, "mood: calm")
        run(tmp_path, PROMPT_MOOD_V5)
        set_decisions(
            tmp_path,
            group={"5-gadgets-mood-prompt": "bold"},
            per_object={("5-gadgets-mood-prompt", "x-b"): "calm"},
        )
        run(tmp_path, PROMPT_MOOD_V5)
        assert "mood: bold" in pa.read_text(encoding="utf-8")
        assert "mood: calm" in pb.read_text(encoding="utf-8")

    def test_object_atomic_restamp_holds_back_deterministic_results(self, tmp_path):
        # MIG-5: an object with a resolved map AND an unresolved prompt is written NOT
        # AT ALL — it re-stamps only when every step resolves.
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-mixed", 3, "color: teal\nmood: calm")
        before = p.read_bytes()
        result = run(tmp_path, MAP_COLOR_V4, PROMPT_MOOD_V5)
        assert outcomes_by_id(result)["x-mixed"].status == STATUS_NEEDS_INPUT
        assert p.read_bytes() == before  # the deterministic map was NOT half-applied
        set_decisions(tmp_path, group={"5-gadgets-mood-prompt": "bold"})
        result = run(tmp_path, MAP_COLOR_V4, PROMPT_MOOD_V5)
        o = outcomes_by_id(result)["x-mixed"]
        assert o.status == STATUS_MIGRATED and o.new_stamp == 5
        text = p.read_text(encoding="utf-8")
        assert "color: blue" in text and "mood: bold" in text  # both landed together

    def test_partial_resume_keeps_remaining_worklist(self, tmp_path):
        # Two pending groups; the human answers one; the regenerated worklist carries
        # ONLY the remainder (resumable + diffable, MIG-5).
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-two", 3, "color: teal\nmood: calm")
        colorq = step_yaml("4-gadgets-colorq", 4, "    prompt: pick a color", attribute="color")
        run(tmp_path, colorq, PROMPT_MOOD_V5)
        wl = tmp_path / "instance" / "ops" / "migration-worklist.yaml"
        data = load_yaml(wl.read_text(encoding="utf-8"))
        assert [g["step"] for g in data["groups"]] == [
            "4-gadgets-colorq",
            "5-gadgets-mood-prompt",
        ]
        set_decisions(tmp_path, group={"4-gadgets-colorq": "blue"})
        result = run(tmp_path, colorq, PROMPT_MOOD_V5)
        assert outcomes_by_id(result)["x-two"].status == STATUS_NEEDS_INPUT
        data = load_yaml(wl.read_text(encoding="utf-8"))
        assert [g["step"] for g in data["groups"]] == ["5-gadgets-mood-prompt"]

    def test_invalid_decision_stays_pending_and_is_preserved(self, tmp_path):
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-a", 4, "mood: calm")
        run(tmp_path, PROMPT_MOOD_V5)
        set_decisions(tmp_path, group={"5-gadgets-mood-prompt": "furious"})
        before = p.read_bytes()
        result = run(tmp_path, PROMPT_MOOD_V5)
        o = outcomes_by_id(result)["x-a"]
        assert o.status == STATUS_NEEDS_INPUT
        assert "invalid-migration-decision" in o.detail
        assert p.read_bytes() == before
        # The (bad) decision survives regeneration for the human to fix, not retype.
        wl = tmp_path / "instance" / "ops" / "migration-worklist.yaml"
        data = load_yaml(wl.read_text(encoding="utf-8"))
        assert data["groups"][0]["decision"] == "furious"

    def test_framework_entries_are_never_migrated(self, tmp_path):
        # MIG-7: framework defaults are lockstep-maintained upstream.
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "example-fw", 3, "color: teal", provenance="framework")
        before = p.read_bytes()
        result = run(tmp_path, MAP_COLOR_V4)
        o = outcomes_by_id(result)["example-fw"]
        assert o.status == STATUS_SKIPPED_FRAMEWORK
        assert "lockstep" in o.detail
        assert p.read_bytes() == before

    def test_stamp_ahead_of_current_is_an_error(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-future", 9, "size: 2")
        result = run(tmp_path)
        o = outcomes_by_id(result)["x-future"]
        assert o.status == STATUS_ERROR and "forward-only" in o.detail
        assert result.exit_code() == 1

    def test_post_fold_validation_gates_the_write(self, tmp_path):
        # An (ill-authored) object edit landing an undeclared attribute is refused at
        # the post-fold closed-schema gate: loud error, file untouched.
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-a", 3, "color: red")
        before = p.read_bytes()
        result = run(
            tmp_path,
            step_yaml(
                "4-gadgets-bad-edit", 4, "    edit:\n      set:\n        bogus: 1", scope="object"
            ),
        )
        o = outcomes_by_id(result)["x-a"]
        assert o.status == STATUS_ERROR and "post-fold validation failed" in o.detail
        assert p.read_bytes() == before

    def test_totality_violation_surfaces_as_error_outcome(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-a", 3, "color: magenta")
        result = run(tmp_path, MAP_COLOR_V4)
        o = outcomes_by_id(result)["x-a"]
        assert o.status == STATUS_ERROR and "migration-map-not-total" in o.detail

    def test_restamp_when_no_step_affects_the_entry(self, tmp_path):
        # Interval non-empty but nothing applies: the entry is valid under current, all
        # zero of its steps resolved -> object-atomically re-stamped to current.
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-plain", 3, "size: 2")
        result = run(tmp_path, MAP_COLOR_V4)
        o = outcomes_by_id(result)["x-plain"]
        assert o.status == STATUS_MIGRATED and o.new_stamp == 5
        assert "re-stamp only" in o.detail
        assert "schema_version: 5" in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------------------
# MIG-7: config-only scope — artifacts immutable, stores never walked
# ---------------------------------------------------------------------------------------


class TestConfigOnlyScope:
    def test_artifact_stores_are_never_touched(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-a", 3, "color: teal")
        # A workspace config collection (IS migrated) ...
        write_schema(tmp_path / "workspaces" / "acme", collection="topics")
        wsp = write_entry(tmp_path / "workspaces" / "acme", "topics", "x-t", 3, "color: teal")
        # ... and artifact/machine stores (NEVER touched), incl. a decoy _schema.yaml.
        stores = {}
        for rel in (
            "workspaces/acme/artifacts/a-0011223344556677.json",
            "workspaces/acme/deliverables/d.md",
            "workspaces/acme/output/manifest.json",
            "workspaces/acme/claims/claim.json",
            "instance/ops/telemetry.jsonl",
        ):
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("machine record — immutable\n", encoding="utf-8")
            stores[rel] = f
        (tmp_path / "workspaces" / "acme" / "artifacts" / SCHEMA_FILENAME).write_text(
            GADGETS_SCHEMA, encoding="utf-8"
        )
        # ... plus a decoy ENTRY a de-pruned walker WOULD rewrite (`size` has no
        # definition bump in (3, 5], so a visitor re-stamps it to v5 — nothing blocks):
        # the byte-assert below itself proves MIG-7's name-pruning, independent of the
        # outcome-collection assert (mutation-verified both ways).
        decoy_entry = tmp_path / "workspaces" / "acme" / "artifacts" / "x-decoy.md"
        decoy_entry.write_text(entry_text("x-decoy", 3, "size: 3"), encoding="utf-8")
        decoy_before = decoy_entry.read_bytes()
        result = run(
            tmp_path,
            MAP_COLOR_V4,
            step_yaml(
                "4-topics-map",
                4,
                "    map:\n      teal: blue",
                collection="topics",
                attribute="color",
            ),
        )
        by_id = outcomes_by_id(result)
        assert by_id["x-a"].status == STATUS_MIGRATED
        assert by_id["x-t"].status == STATUS_MIGRATED  # workspace CONFIG migrates
        assert "color: blue" in wsp.read_text(encoding="utf-8")
        for rel, f in stores.items():
            assert f.read_text(encoding="utf-8") == "machine record — immutable\n", rel
        assert decoy_entry.read_bytes() == decoy_before  # byte-identical: never rewritten
        # The decoy store schema was never visited as a collection.
        assert all(o.collection != "artifacts" for o in result.outcomes)

    def test_worklist_loading_rules(self, tmp_path):
        # Missing worklist = no decisions (a fresh run); malformed = typed refusal.
        empty = load_worklist_decisions(tmp_path / "absent.yaml")
        assert empty.group == {} and empty.per_object == {}
        bad = tmp_path / "bad.yaml"
        bad.write_text("no groups here: true\n", encoding="utf-8")
        with pytest.raises(WorklistError, match="groups"):
            load_worklist_decisions(bad)

    def test_metadata_is_structurally_untargetable(self):
        # (Also asserted at registry validation; restated here as the MIG-7 contract.)
        with pytest.raises(RegistryError, match="reserved"):
            registry_of(step_yaml("4-gadgets-meta", 4, "    drop: true", attribute="metadata"))


# ---------------------------------------------------------------------------------------
# CLI (`python -m pipeline.migration` behind scripts/migrate.sh)
# ---------------------------------------------------------------------------------------


class TestCLI:
    def test_main_exit_codes(self, tmp_path, capsys):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-a", 4, "mood: calm")
        write_registry(tmp_path, PROMPT_MOOD_V5)
        argv = ["--root", str(tmp_path), "--now", "2026-07-12"]
        assert main(argv) == 3  # decisions needed
        out = capsys.readouterr().out
        assert "needs-input" in out and "[ambiguous-migration-decisions]" in out
        assert "decisions-needed worklist written" in out
        set_decisions(tmp_path, group={"5-gadgets-mood-prompt": "bold"})
        assert main(argv) == 0
        out = capsys.readouterr().out
        assert "worklist fully consumed and removed" in out
        assert main(argv) == 0  # idempotent

    def test_main_bad_now_is_usage_error(self, tmp_path, capsys):
        assert main(["--root", str(tmp_path), "--now", "soon"]) == 2

    def test_main_registry_error_is_usage_error(self, tmp_path, capsys):
        write_registry(tmp_path, PROMPT_MOOD_V5, MAP_COLOR_V4)  # v5 then v4
        assert main(["--root", str(tmp_path), "--now", "2026-07-12"]) == 2
        assert "forward-only" in capsys.readouterr().err

    def test_migrate_sh_wires_through(self, tmp_path):
        # The shim itself (bash) — user-triggered maintenance verb; --root override wins.
        write_schema(tmp_path)
        p = write_entry(tmp_path, "gadgets", "x-a", 3, "color: teal")
        write_registry(tmp_path, MAP_COLOR_V4)
        proc = subprocess.run(
            [
                "bash",
                str(REPO_ROOT / "scripts" / "migrate.sh"),
                "--root",
                str(tmp_path),
                "--now",
                "2026-07-12",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        assert "migrated" in proc.stdout
        assert "color: blue" in p.read_text(encoding="utf-8")

    def test_concurrent_double_run_both_exit_zero(self, tmp_path):
        # Regression: two RACING processes over the SAME tree (an operator error — real
        # locking is the step-20 G1 module) must BOTH exit 0 with every entry intact.
        # Per-process temp names make each commit an atomic os.replace of fully-written
        # content; racers converge on the identical deterministic fold (last-wins). A
        # shared fixed temp name crashed the loser (FileNotFoundError under os.replace)
        # and opened a torn-write window on the live entry.
        write_schema(tmp_path)
        paths = [write_entry(tmp_path, "gadgets", f"x-e{i}", 3, "color: teal") for i in range(40)]
        write_registry(tmp_path, MAP_COLOR_V4)
        cmd = [
            sys.executable,
            "-m",
            "pipeline.migration",
            "--root",
            str(tmp_path),
            "--now",
            "2026-07-12",
        ]
        procs = [
            subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            for _ in range(2)
        ]
        streams = [p.communicate(timeout=120) for p in procs]
        for p, (out, err) in zip(procs, streams, strict=True):
            assert p.returncode == 0, f"racer exited {p.returncode}\n{out}\n{err}"
        for path in paths:
            text = path.read_text(encoding="utf-8")  # intact, fully-migrated bytes
            assert "color: blue" in text and "schema_version: 5" in text
            assert text.endswith("---\nBody prose.\n")
        assert not list(tmp_path.rglob("*.migrate-tmp*"))  # no temp litter left behind
