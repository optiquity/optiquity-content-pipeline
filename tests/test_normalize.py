"""CLI-UX C2 — the door-class-aware friendly normalizer (`pipeline/api/normalize.py`).

Covers the ratified door-class default table (recipe/workspace/idempotency-key), the
`--set` typed-scalar + union grammar, the neutral cross-wrapper fixture table
(`tests/fixtures/normalize_spec.json`, the DR-8 contract), and — the S-4 correction — that
a `--set` TYPE MISMATCH is refused at the REAL M1 wall (`attrtypes.validate_value` /
`validate_combine_operator`, wrapped `invalid-override`), NOT in the normalizer. The
normalizer is a PURE LEAF: it emits typed values and adds no guard code of its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# The real fixture-root builder + workspace name + owning user (a live registry copy in tmp_path).
from test_cascade import USER, WS, build_root

from pipeline.api import normalize as normalize_mod
from pipeline.api.normalize import (
    DEFAULT_RECIPE,
    DOOR_AUTOMATION,
    DOOR_INTERACTIVE,
    NormalizeError,
    compile_overrides,
    normalize,
)
from pipeline.attrtypes import CombineOperatorError, ValueValidationError
from pipeline.cascade import CascadeEnv
from pipeline.overrides import OverrideError

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "normalize_spec.json"

_FLOOR = {"recipe": "explainer-post", "workspace": "self", "user": "self"}


# --- door-class: idempotency key policy (the no-double-charge door) ----------------------


def test_normalize_interactive_autokeys_and_prints() -> None:
    """Interactive + paid verb + key omitted → auto-generate AND surface it (the caller
    prints it so a scripting user can pin it) — plus a printable notice."""
    result = normalize({**_FLOOR, "spend": True}, DOOR_INTERACTIVE, key_factory=lambda: "k-abc")
    assert result.params["idempotency_key"] == "k-abc"
    assert result.generated_key == "k-abc"
    assert result.notices == ("generated idempotency key k-abc — reuse it to make a retry safe",)


def test_normalize_automation_omits_key() -> None:
    """Automation + paid verb + key omitted → the key is ABSENT (never auto-filled), so
    the shim's missing-key→400 anti-double-charge path stays reachable
    (`known-issues.md:198-199`)."""
    result = normalize({**_FLOOR, "spend": True}, DOOR_AUTOMATION)
    assert "idempotency_key" not in result.params
    assert result.generated_key is None


def test_normalize_automation_passes_explicit_key_through() -> None:
    result = normalize(
        {**_FLOOR, "spend": True, "idempotency_key": "exec-42"}, DOOR_AUTOMATION
    )
    assert result.params["idempotency_key"] == "exec-42"
    assert result.generated_key is None


def test_normalize_read_verb_needs_no_key() -> None:
    for door in (DOOR_INTERACTIVE, DOOR_AUTOMATION):
        result = normalize(_FLOOR, door)
        assert "idempotency_key" not in result.params
        assert result.generated_key is None


def test_normalize_interactive_target_folio_auto_warns() -> None:
    result = normalize(
        {**_FLOOR, "spend": True, "target_folio": "auto"},
        DOOR_INTERACTIVE,
        key_factory=lambda: "k-1",
    )
    assert result.params["target_folio"] == "auto"
    assert result.params["idempotency_key"] == "k-1"
    assert any("second empty folio" in n for n in result.notices)


# --- door-class: fatal-on-automation vs. interactive defaults ----------------------------


def test_normalize_automation_fatal_on_missing_recipe() -> None:
    with pytest.raises(NormalizeError) as ei:
        normalize({"workspace": "self", "spend": True}, DOOR_AUTOMATION)
    assert ei.value.field == "recipe"


def test_normalize_automation_fatal_on_missing_workspace_on_spend() -> None:
    with pytest.raises(NormalizeError) as ei:
        normalize({"recipe": "explainer-post", "spend": True}, DOOR_AUTOMATION)
    assert ei.value.field == "workspace"


def test_normalize_automation_fatal_on_missing_user() -> None:
    # §23 never-None invariant (F3): the automation door refuses a workspace with no owning user —
    # `field="user"` (never a silent default, never a `users/None/` path). Pins `_resolve_user` so a
    # future refactor cannot silently drop it.
    with pytest.raises(NormalizeError) as ei:
        normalize({"recipe": "explainer-post", "workspace": "self"}, DOOR_AUTOMATION)
    assert ei.value.field == "user"


def test_normalize_interactive_workspace_without_user_is_fatal() -> None:
    # §23 never-None invariant (F3): even on the lenient interactive door, a RESOLVED workspace with
    # no user is refused at the pairing check (`field="user"`; a workspace always carries an owner).
    with pytest.raises(NormalizeError) as ei:
        normalize({"recipe": "explainer-post", "workspace": "self"}, DOOR_INTERACTIVE)
    assert ei.value.field == "user"


def test_normalize_interactive_recipe_defaults_to_explainer_post() -> None:
    result = normalize({"workspace": "self", "user": "self"}, DOOR_INTERACTIVE)
    assert result.params["recipe"] == DEFAULT_RECIPE == "explainer-post"


def test_normalize_interactive_sole_workspace_infers() -> None:
    result = normalize(
        {
            "recipe": "explainer-post", "spend": True,
            "available_workspaces": ["self"], "user": "self",
        },
        DOOR_INTERACTIVE,
    )
    assert result.workspace == "self"


def test_normalize_interactive_ambiguous_workspace_on_spend_requires_explicit() -> None:
    with pytest.raises(NormalizeError) as ei:
        normalize(
            {"recipe": "explainer-post", "spend": True, "available_workspaces": ["a", "b"]},
            DOOR_INTERACTIVE,
        )
    assert ei.value.field == "workspace"


def test_normalize_invalid_door_class_is_fatal() -> None:
    with pytest.raises(NormalizeError) as ei:
        normalize(_FLOOR, "batch")
    assert ei.value.field == "door_class"


# --- by-name axes + multi-select ---------------------------------------------------------


def test_multiselect_repeat_fans_out_and_goals_stack() -> None:
    result = normalize(
        {
            **_FLOOR,
            "personas": ["principal-engineer", "staff-engineer"],
            "goals": ["explain", "persuade"],
        },
        DOOR_INTERACTIVE,
    )
    # Each persona is a separate list member (fan-out); goals STACK into ONE goal-set.
    assert result.params["personas"] == ["principal-engineer", "staff-engineer"]
    assert result.params["goal_sets"] == [["explain", "persuade"]]


# --- `--set` grammar (shape) -------------------------------------------------------------


def test_set_typed_scalar_int() -> None:
    result = normalize({**_FLOOR, "set": ["voice.formality=2"]}, DOOR_INTERACTIVE)
    assert result.params["overrides"] == {"voice.formality": 2}
    assert isinstance(result.params["overrides"]["voice.formality"], int)


def test_set_typed_scalar_bool_null_and_string() -> None:
    assert compile_overrides(["x.y=true"]) == {"x.y": True}
    assert compile_overrides(["x.y=false"]) == {"x.y": False}
    assert compile_overrides(["x.y=null"]) == {"x.y": None}
    assert compile_overrides(["x.y=high"]) == {"x.y": "high"}


def test_set_explicit_cast_escape() -> None:
    assert compile_overrides(["x.y=str:2"]) == {"x.y": "2"}
    assert compile_overrides(["x.y=int:2"]) == {"x.y": 2}
    assert compile_overrides(["x.y=bool:true"]) == {"x.y": True}


def test_set_union_operand_is_a_list() -> None:
    assert compile_overrides(["format.tags+=x"]) == {"format.tags+": ["x"]}
    assert compile_overrides(["format.tags+=a,b"]) == {"format.tags+": ["a", "b"]}


def test_set_double_bind_is_refused_loud() -> None:
    with pytest.raises(NormalizeError) as ei:
        compile_overrides(["voice.formality=2", "voice.formality+=3"])
    assert ei.value.field == "set"


def test_set_missing_operator_is_refused() -> None:
    with pytest.raises(NormalizeError) as ei:
        compile_overrides(["voice.formality"])
    assert ei.value.field == "set"


# --- `--set` typing meets the REAL enforcement wall (S-4 corrected trace) -----------------


def test_set_typed_int_passes_the_real_wall(tmp_path: Path) -> None:
    """`voice.formality=2` (a slider = §13.2 integer) → int 2, IN range → accepted by the
    real `CascadeEnv` override validation."""
    result = normalize({**_FLOOR, "set": ["voice.formality=2"]}, DOOR_INTERACTIVE)
    root = build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS, overrides=result.params["overrides"])
    assert env is not None  # no raise — the typed int clears the wall


def test_set_type_mismatch_is_invalid_override_at_the_real_wall(tmp_path: Path) -> None:
    """S-4: the normalizer TYPES but never VALIDATES. `voice.formality=high` infers the
    STRING "high"; the refusal fires DOWNSTREAM at `attrtypes.validate_value`
    (`attrtypes.py:246`), wrapped `invalid-override` — never in the normalizer, never
    originating in `overrides.py`."""
    result = normalize({**_FLOOR, "set": ["voice.formality=high"]}, DOOR_INTERACTIVE)
    # The normalizer itself does NOT raise — it emits the (wrong-typed) string.
    assert result.params["overrides"] == {"voice.formality": "high"}

    root = build_root(tmp_path)
    with pytest.raises(OverrideError) as ei:
        CascadeEnv(root, user=USER, workspace=WS, overrides=result.params["overrides"])
    assert "invalid-override" in str(ei.value)
    # The ORIGIN is the value-type wall (attrtypes), carried as the cause — the S-4 trace.
    assert isinstance(ei.value.__cause__, ValueValidationError)


def test_set_union_on_non_set_is_invalid_override_at_the_operator_wall(tmp_path: Path) -> None:
    """`+=` on a non-set attribute (slider) is refused at `validate_combine_operator`
    (`attrtypes.py:206-219`), wrapped `invalid-override`."""
    result = normalize({**_FLOOR, "set": ["voice.formality+=2"]}, DOOR_INTERACTIVE)
    assert result.params["overrides"] == {"voice.formality+": [2]}

    root = build_root(tmp_path)
    with pytest.raises(OverrideError) as ei:
        CascadeEnv(root, user=USER, workspace=WS, overrides=result.params["overrides"])
    assert "invalid-override" in str(ei.value)
    assert isinstance(ei.value.__cause__, CombineOperatorError)


# --- the neutral cross-wrapper fixture table (DR-8 contract) ------------------------------


def test_neutral_spec_table() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sentinel = data["auto_key_sentinel"]
    rows = data["rows"]
    assert rows, "the neutral spec must carry rows"
    for row in rows:
        name = row["name"]
        friendly, door = row["friendly_inputs"], row["door_class"]
        if row["expect"] == "error":
            with pytest.raises(NormalizeError) as ei:
                normalize(friendly, door)
            assert ei.value.field == row["error_field"], name
            continue
        result = normalize(friendly, door)
        assert result.workspace == row["workspace"], name
        expected_params = dict(row["params"])
        if row.get("generated_key"):
            actual = result.params.get("idempotency_key")
            assert isinstance(actual, str) and actual, name
            assert result.generated_key == actual, name
            expected_params["idempotency_key"] = actual
            expected_notices = [n.replace(sentinel, actual) for n in row["notices"]]
        else:
            assert result.generated_key is None, name
            expected_notices = list(row["notices"])
        assert result.params == expected_params, name
        assert list(result.notices) == expected_notices, name


# --- structural invariants (R8 leaf-ness; the self-declared default is real) --------------


def test_normalize_is_a_leaf_no_pipeline_imports() -> None:
    """R8: the module must stay import-cycle-safe — it imports only the stdlib, never a
    `pipeline` module (so wiring it into a door in C3a cannot introduce a cycle)."""
    src = Path(normalize_mod.__file__).read_text(encoding="utf-8")
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import ", "from ")):
            assert "pipeline" not in stripped, f"normalize.py must stay a leaf (R8): {stripped!r}"


def test_default_recipe_entry_exists() -> None:
    """The interactive default (`explainer-post`) must resolve to a real shipped recipe."""
    repo_root = Path(__file__).resolve().parents[1]
    assert (repo_root / "recipes" / f"{DEFAULT_RECIPE}.md").is_file()


def test_target_folio_sentinels_match_session() -> None:
    """The `target_folio` sentinels are mirrored (leaf discipline); pin them to session's
    canonical constants so they never drift."""
    from pipeline.api import session

    assert normalize_mod.TARGET_FOLIO_AUTO == session.TARGET_FOLIO_AUTO
    assert normalize_mod.TARGET_FOLIO_NONE == session.TARGET_FOLIO_NONE
