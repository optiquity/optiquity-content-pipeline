"""Unit tests for the shared authoring core (`pipeline.authoring`; authoring layer C2a).

Covers the four pure pieces the design ratifies (D5–D10): the PICK/TWEAK/CLEAR router (with
the S1 segment-count `--unset` and the no-collision-with-`--set path=""` proof), the
`base ⊕ edits` merge (the primitive C2b derive AND C5c `base ⊕ deltaᵢ` reuse), the
conforming-recipe serializer (round-trips: bundle → a recipe that lints green → the same
bundle), all-slot provenance inference (framework → public, a client binding → workspace and
REFUSED from public), and the TTY-gated overwrite guard (headless fail-fast, `--force`,
injected prompt). Also pins the module's binding vocabulary to the recipe schema SSOT.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pipeline import overrides
from pipeline.attrtypes import ValueValidationError
from pipeline.authoring import (
    AXIS_TO_SLOT,
    ENTRY_REFERENCING_SLOTS,
    RECIPE_COLLECTION,
    SET_VALUED_SLOTS,
    SINGLE_VALUED_SLOTS,
    VALUES_SLOT,
    AuthoringError,
    build_edit_set,
    bundle_from_entry,
    ensure_writable,
    infer_provenance,
    load_recipe_schema,
    merge_bundle,
    resolve_recipe_target,
    serialize_recipe,
    write_recipe,
)
from pipeline.entries import PROVENANCE_FRAMEWORK, PROVENANCE_INSTANCE, load_entry
from pipeline.fanout import CONTENT_AXES, RENDERING_AXES
from pipeline.lint import lint_tree, render_report
from pipeline.schema import SCHEMA_FILENAME, load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = date(2026, 7, 30)


def _recipe_root(tmp_path: Path) -> Path:
    """A tmp registry root carrying the real recipe schema (a lintable, loadable tree)."""
    dst = tmp_path / RECIPE_COLLECTION / SCHEMA_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (REPO_ROOT / RECIPE_COLLECTION / SCHEMA_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp_path


# --- SSOT consistency: the module vocabulary IS the recipe schema -------------------------


def test_slot_metadata_matches_recipe_schema() -> None:
    """The entry-referencing slots + their cardinality are the recipe schema's, minus `values`."""
    schema = load_recipe_schema()
    assert set(ENTRY_REFERENCING_SLOTS) == set(schema.attributes) - {VALUES_SLOT}
    for slot in SINGLE_VALUED_SLOTS:
        assert schema.attributes[slot].type.kind in {"text", "ref"}, slot
    for slot in SET_VALUED_SLOTS:
        assert schema.attributes[slot].type.kind == "set", slot


def test_axis_map_matches_fanout_axes() -> None:
    """`AXIS_TO_SLOT` covers every fan-out axis (+goals); rendering axes map to themselves."""
    assert set(AXIS_TO_SLOT) == set(CONTENT_AXES) | set(RENDERING_AXES) | {"goals"}
    for axis in RENDERING_AXES:
        assert AXIS_TO_SLOT[axis] == axis


# --- The router: PICK ---------------------------------------------------------------------


def test_pick_replaces_axis_set() -> None:
    """Mentioning an axis REPLACES the base's set for that axis (§2)."""
    base = {"platforms": ["twitter"]}
    edits = build_edit_set(picks={"platforms": ["linkedin"]})
    merged = merge_bundle(base, edits)
    assert merged["platforms"] == ["linkedin"]  # replaced, not unioned


def test_repeated_flag_accumulates_set() -> None:
    """Repeated values accumulate into the ONE set you are stating."""
    edits = build_edit_set(picks={"platforms": ["twitter", "linkedin"]})
    merged = merge_bundle({}, edits)
    assert merged["platforms"] == ["twitter", "linkedin"]


def test_pick_accepts_fanout_axis_key_and_maps_to_slot() -> None:
    """A plural fan-out axis key (`personas`) resolves to its singular recipe slot."""
    edits = build_edit_set(picks={"personas": ["technical-evaluator"]})
    merged = merge_bundle({}, edits)
    assert merged == {"persona": "technical-evaluator"}


def test_single_valued_slot_refuses_multiple() -> None:
    """A recipe binds ONE per content dimension — two ids on a single slot is loud (§8)."""
    edits = build_edit_set(picks={"persona": ["a", "b"]})
    with pytest.raises(AuthoringError, match="single-valued"):
        merge_bundle({}, edits)


def test_non_slug_pick_refused_loud() -> None:
    with pytest.raises(AuthoringError, match="slug"):
        build_edit_set(picks={"persona": ["Not A Slug!"]})


# --- The router: TWEAK --------------------------------------------------------------------


def test_set_equals_replaces_plus_unions() -> None:
    """`=` → a replace key; `+=` → the `+` union key (the §13.2 grammar, values-only)."""
    edits = build_edit_set(set_entries=["voice.formality=4", "format.tags+=x"])
    assert edits.tweaks == {"voice.formality": 4, "format.tags+": ["x"]}


def test_tweak_one_segment_path_refused_by_override_guard() -> None:
    """A value tweak is `<dim>.<attr>`; a bare dimension is the M1 wall refusal (§21.4)."""
    with pytest.raises(overrides.OverrideError):
        build_edit_set(set_entries=["voice=2"])


# --- The router: CLEAR (S1 segment-count) -------------------------------------------------


def test_unset_one_segment_clears_axis() -> None:
    """One segment clears the axis SLOT (falls through to the cascade floor)."""
    edits = build_edit_set(unset=["platforms"])
    assert edits.clears_axis == frozenset({"platforms"})
    assert edits.clears_value == frozenset()
    merged = merge_bundle({"platforms": ["linkedin"], "persona": "technical-evaluator"}, edits)
    assert "platforms" not in merged
    assert merged["persona"] == "technical-evaluator"


def test_unset_two_segments_clears_value() -> None:
    """Two segments clear a value BINDING from the values map."""
    edits = build_edit_set(unset=["voice.formality"])
    assert edits.clears_value == frozenset({"voice.formality"})
    assert edits.clears_axis == frozenset()
    merged = merge_bundle({"values": {"voice.formality": 2}}, edits)
    assert VALUES_SLOT not in merged  # the map emptied → the slot is omitted


def test_unset_clears_both_replace_and_union_value_spellings() -> None:
    """`--unset voice.formality` drops both the `voice.formality` and `voice.formality+` keys."""
    edits = build_edit_set(unset=["voice.formality"])
    merged = merge_bundle({"values": {"voice.formality+": [1], "voice.tone": "warm"}}, edits)
    assert merged[VALUES_SLOT] == {"voice.tone": "warm"}


def test_unset_axis_does_not_call_override_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """[S1] the 1-segment axis clear NEVER routes through `overrides._override_from_bind`
    (which RAISES on a 1-segment path) — the router owns its own segment-count logic."""
    calls: list[object] = []
    original = overrides._override_from_bind

    def _spy(*args: object, **kwargs: object):
        calls.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(overrides, "_override_from_bind", _spy)
    edits = build_edit_set(unset=["voice"])  # 1-segment axis clear
    assert edits.clears_axis == frozenset({"voice"})
    assert calls == []  # the guard was never consulted for the axis clear


def test_unset_three_segments_refused() -> None:
    with pytest.raises(AuthoringError, match="segments"):
        build_edit_set(unset=["a.b.c"])


def test_unset_unknown_axis_refused() -> None:
    with pytest.raises(AuthoringError, match="not a recipe slot"):
        build_edit_set(unset=["nonsense"])


def test_unset_reserved_value_attribute_refused() -> None:
    with pytest.raises(AuthoringError, match="not a bindable attribute"):
        build_edit_set(unset=["voice.provenance"])


# --- No collision: `--unset path` (clear) vs `--set path=""` (bind empty) -----------------


def test_unset_value_does_not_collide_with_set_empty() -> None:
    """`--set voice.tone=` BINDS an empty value; `--unset voice.tone` CLEARS the binding —
    different verbs, different results (design §2)."""
    via_set = merge_bundle({}, build_edit_set(set_entries=["voice.tone="]))
    assert via_set[VALUES_SLOT] == {"voice.tone": ""}  # empty value bound, present

    via_unset = merge_bundle(
        {"values": {"voice.tone": "warm"}}, build_edit_set(unset=["voice.tone"])
    )
    assert VALUES_SLOT not in via_unset  # binding removed, absent

    assert via_set != via_unset


# --- The router: conflicts ----------------------------------------------------------------


def test_pick_and_axis_clear_conflict_refused() -> None:
    with pytest.raises(AuthoringError, match="both picked and --unset"):
        build_edit_set(picks={"platforms": ["linkedin"]}, unset=["platforms"])


def test_tweak_and_value_clear_conflict_refused() -> None:
    with pytest.raises(AuthoringError, match="both --set and --unset"):
        build_edit_set(set_entries=["voice.formality=4"], unset=["voice.formality"])


# --- The base ⊕ edits merge ---------------------------------------------------------------


def test_merge_pick_replaces_tweak_sets_clear_drops() -> None:
    """One merge exercises all three verbs at once (the C2b derive shape)."""
    base = {
        "persona": "technical-evaluator",
        "format": "short-opinion-post",
        "diagram_style": "default",
        "values": {"voice.formality": 1},
    }
    edits = build_edit_set(
        picks={"platforms": ["linkedin"]},
        set_entries=["voice.formality=4"],
        unset=["diagram_style"],
    )
    merged = merge_bundle(base, edits)
    assert merged["platforms"] == ["linkedin"]  # PICK added the render pin
    assert merged["values"] == {"voice.formality": 4}  # TWEAK replaced the value
    assert "diagram_style" not in merged  # CLEAR dropped the slot
    assert merged["persona"] == "technical-evaluator"  # untouched base slot inherited


def test_merge_does_not_mutate_base() -> None:
    base = {"platforms": ["twitter"], "values": {"voice.formality": 1}}
    merge_bundle(
        base, build_edit_set(picks={"platforms": ["linkedin"]}, set_entries=["voice.formality=4"])
    )
    assert base == {"platforms": ["twitter"], "values": {"voice.formality": 1}}


def test_merge_refuses_unknown_base_slot() -> None:
    with pytest.raises(AuthoringError, match="not a recipe binding slot"):
        merge_bundle({"not_a_slot": "x"}, build_edit_set())


# --- Provenance inference + home resolution (D9) ------------------------------------------


def test_infer_provenance_framework_and_instance() -> None:
    assert infer_provenance({"persona": "technical-evaluator"}) == PROVENANCE_FRAMEWORK
    assert infer_provenance({"topic": "x-architecture"}) == PROVENANCE_INSTANCE
    assert infer_provenance({"platforms": ["linkedin", "x-internal"]}) == PROVENANCE_INSTANCE


def test_framework_only_homes_public(tmp_path: Path) -> None:
    target = resolve_recipe_target(tmp_path, "explainer-brief", {"persona": "technical-evaluator"})
    assert target.provenance == PROVENANCE_FRAMEWORK
    assert target.path == tmp_path / RECIPE_COLLECTION / "explainer-brief.md"
    assert target.workspace is None


def test_provenance_instance_id_homes_under_workspace(tmp_path: Path) -> None:
    target = resolve_recipe_target(
        tmp_path, "x-launch-brief", {"topic": "x-architecture"}, workspace="mvp-demo"
    )
    assert target.provenance == PROVENANCE_INSTANCE
    expected = tmp_path / "workspaces" / "mvp-demo" / RECIPE_COLLECTION / "x-launch-brief.md"
    assert target.path == expected
    assert target.workspace == "mvp-demo"


def test_client_binding_refused_from_public(tmp_path: Path) -> None:
    """A client (`x-`) binding under a non-`x-` public id is REFUSED (rule 4, §10)."""
    with pytest.raises(AuthoringError, match="never the public repo"):
        resolve_recipe_target(tmp_path, "launch-brief", {"topic": "x-architecture"})


def test_client_binding_via_values_refused_from_public(tmp_path: Path) -> None:
    """The rule-4 leak: a client id reaching `values` through a ref-typed attribute
    (`--set persona.default_voice=x-client-voice`), with framework picks otherwise, is STILL
    instance — refused from public and homed under the workspace, never written to public."""
    edits = build_edit_set(
        picks={"personas": ["technical-evaluator"]},
        set_entries=["persona.default_voice=x-client-voice"],
    )
    bundle = merge_bundle({}, edits)
    assert bundle[VALUES_SLOT] == {"persona.default_voice": "x-client-voice"}
    # infer_provenance must see the values-borne client id (the leak the reviewer caught).
    assert infer_provenance(bundle) == PROVENANCE_INSTANCE
    # A `+=` union operand carrying a client id is caught too (list operand recursion).
    union_bundle = merge_bundle({}, build_edit_set(set_entries=["format.tags+=x-client-tag"]))
    assert infer_provenance(union_bundle) == PROVENANCE_INSTANCE
    # A public id is refused; the same bundle homes under a workspace with an `x-` id.
    with pytest.raises(AuthoringError, match="never the public repo"):
        resolve_recipe_target(tmp_path, "brief", bundle)
    target = resolve_recipe_target(tmp_path, "x-brief", bundle, workspace="mvp-demo")
    assert target.provenance == PROVENANCE_INSTANCE
    assert target.workspace == "mvp-demo"


def test_instance_id_requires_workspace(tmp_path: Path) -> None:
    with pytest.raises(AuthoringError, match="requires a --workspace"):
        resolve_recipe_target(tmp_path, "x-launch-brief", {"topic": "x-architecture"})


def test_non_slug_id_refused_loud(tmp_path: Path) -> None:
    with pytest.raises(AuthoringError, match="slug"):
        resolve_recipe_target(tmp_path, "Not A Slug!", {})


# --- The conforming-recipe serializer -----------------------------------------------------


def test_serializer_omits_unset_slots() -> None:
    text = serialize_recipe(
        {"persona": "technical-evaluator", "format": "short-opinion-post"},
        recipe_id="x2",
        provenance=PROVENANCE_FRAMEWORK,
    )
    assert "persona: technical-evaluator" in text
    assert "format: short-opinion-post" in text
    assert "topic:" not in text  # an unset slot is omitted → it falls through the cascade
    assert "voice:" not in text


def test_serializer_round_trips_and_lints_green(tmp_path: Path) -> None:
    """A bundle → a conforming recipe file that lints green AND re-parses to the same bundle."""
    root = _recipe_root(tmp_path)
    bundle = {
        "persona": "technical-evaluator",
        "format": "short-opinion-post",
        "goals": ["explain"],
        "platforms": ["linkedin", "twitter"],
        "values": {"voice.formality": 2, "format.tags+": ["deep"]},
    }
    target = write_recipe(root, "round-trip", bundle, force=True)

    report = lint_tree(root, now=NOW, baseline=None)
    assert report.ok, render_report(report)  # lints GREEN — zero findings

    schema = load_schema(root / RECIPE_COLLECTION / SCHEMA_FILENAME)
    reparsed = bundle_from_entry(load_entry(target.path, schema))
    assert reparsed == bundle  # re-parses to the SAME bindings (byte-round-trip of config)


def test_serialized_recipe_bundle_equals_inline_flags(tmp_path: Path) -> None:
    """Identity-neutral: a recipe authored from flags carries the SAME effective config as the
    same flags inlined — the merge is the only source of the bundle either path takes."""
    root = _recipe_root(tmp_path)
    edits = build_edit_set(
        picks={"personas": ["technical-evaluator"], "platforms": ["linkedin"]},
        set_entries=["voice.formality=3"],
    )
    inline_bundle = merge_bundle({}, edits)
    target = write_recipe(root, "inline-eq", inline_bundle, force=True)

    schema = load_schema(root / RECIPE_COLLECTION / SCHEMA_FILENAME)
    from_file = bundle_from_entry(load_entry(target.path, schema))
    assert from_file == inline_bundle


def test_serializer_refuses_typed_wrong_binding() -> None:
    """The serializer closed-schema validates — a set given for a single ref is refused (SV3)."""
    with pytest.raises(ValueValidationError):  # a ref must be a slug string, not a list
        serialize_recipe({"persona": ["a", "b"]}, recipe_id="bad", provenance=PROVENANCE_FRAMEWORK)


def test_serializer_namespace_coupling() -> None:
    with pytest.raises(AuthoringError, match="prefix"):
        serialize_recipe({}, recipe_id="x-foo", provenance=PROVENANCE_FRAMEWORK)
    with pytest.raises(AuthoringError, match="must carry"):
        serialize_recipe({}, recipe_id="foo", provenance=PROVENANCE_INSTANCE)


# --- The overwrite guard (D8) -------------------------------------------------------------


def test_overwrite_refused_headless(tmp_path: Path) -> None:
    """An existing target with no `--force` fails FAST when non-interactive — never hangs."""
    existing = tmp_path / "r.md"
    existing.write_text("x", encoding="utf-8")
    with pytest.raises(AuthoringError, match="already exists"):
        ensure_writable(existing, force=False, isatty=lambda: False)


def test_overwrite_force(tmp_path: Path) -> None:
    existing = tmp_path / "r.md"
    existing.write_text("x", encoding="utf-8")
    ensure_writable(existing, force=True)  # no raise — force overrides


def test_overwrite_missing_target_passes(tmp_path: Path) -> None:
    ensure_writable(tmp_path / "absent.md", isatty=lambda: False)  # no raise


def test_tty_prompt_via_injected_isatty_seam(tmp_path: Path) -> None:
    """Interactive: the prompt runs; approve → writes, decline → refuses."""
    existing = tmp_path / "r.md"
    existing.write_text("x", encoding="utf-8")
    ensure_writable(existing, isatty=lambda: True, confirm=lambda _p: True)  # approved
    with pytest.raises(AuthoringError, match="declined"):
        ensure_writable(existing, isatty=lambda: True, confirm=lambda _p: False)


def test_write_recipe_writes_one_file_and_guards_reruns(tmp_path: Path) -> None:
    root = _recipe_root(tmp_path)
    bundle = {"persona": "technical-evaluator"}
    target = write_recipe(root, "once", bundle)
    assert target.path.is_file()
    # A second write is refused headless (never clobbers) but `--force` overwrites.
    with pytest.raises(AuthoringError, match="already exists"):
        write_recipe(root, "once", bundle, isatty=lambda: False)
    write_recipe(
        root, "once", {"persona": "technical-evaluator", "format": "short-opinion-post"}, force=True
    )
    schema = load_schema(root / RECIPE_COLLECTION / SCHEMA_FILENAME)
    assert "format" in load_entry(target.path, schema).attributes
