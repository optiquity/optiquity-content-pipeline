"""Step-16 tests — `pipeline/overrides.py`: the L6 run-layer override mechanism.

Covers §12.5 (CA5/CA7: ephemeral, collect-once) and the §21.4 API5 hard M1 guard —
all three refusal shapes (add an attr · pick an entry · touch schema) plus the
union-on-list refusal, every one surfacing as the ONE typed code `invalid-override`.
End-to-end application through the cascade is `tests/test_cascade.py`'s scope.
"""

from __future__ import annotations

import pytest

from pipeline.overrides import (
    Override,
    OverrideError,
    OverrideSet,
    collect_overrides,
    validate_override_against_schema,
)
from pipeline.schema import load_schema_text

# A synthetic dimension schema exercising every operator×type branch.
_SCHEMA = load_schema_text(
    """\
schema_version: 1
attributes:
  formality:
    type: slider
    default: 3
    definition: Test slider.
    definition_version: 1
  tags:
    type:
      type: set
      element: text
    default: []
    definition: Test unordered set (union legal).
    definition_version: 1
  parts:
    type:
      type: list
      element: text
    default: []
    definition: Test ordered list (union is a schema error, s11.1).
    definition_version: 1
""",
    collection="voices",
)


# ------------------------------------------------------------------------------------
# Collection: the two §13.2 surfaces
# ------------------------------------------------------------------------------------


def test_collect_mapping_surface_bare_key_is_replace() -> None:
    overrides = collect_overrides({"voice.formality": 2})
    assert len(overrides) == 1
    (override,) = overrides.items
    assert override == Override(
        dimension="voice", attribute="formality", op="replace", value=2, explicit=False
    )
    assert override.path == "voice.formality"


def test_collect_mapping_surface_union_suffix_and_wrapper() -> None:
    overrides = collect_overrides(
        {
            "voice.tags+": ["a"],
            "format.parts": {"combine": "replace", "add": ["intro"]},
        }
    )
    by_path = {o.path: o for o in overrides.items}
    assert by_path["voice.tags"].op == "union"
    assert by_path["voice.tags"].explicit is True
    assert by_path["format.parts"].op == "replace"
    assert by_path["format.parts"].explicit is True  # wrapper = explicit operator


def test_collect_wire_surface() -> None:
    overrides = collect_overrides([{"path": "voice.tags", "op": "union", "value": ["a"]}])
    (override,) = overrides.items
    assert (override.dimension, override.attribute, override.op) == ("voice", "tags", "union")
    assert override.explicit is True  # the wire always names its operator


def test_collect_none_is_empty() -> None:
    overrides = collect_overrides(None)
    assert isinstance(overrides, OverrideSet)
    assert not overrides
    assert len(overrides) == 0


def test_collected_values_are_isolated_copies() -> None:
    payload = ["a"]
    overrides = collect_overrides({"voice.tags+": payload})
    payload.append("mutated-later")
    assert overrides.items[0].value == ["a"]  # collect-once state never moves (CA7)


def test_duplicate_path_refused() -> None:
    with pytest.raises(OverrideError, match="twice"):
        collect_overrides(
            [
                {"path": "voice.formality", "op": "replace", "value": 1},
                {"path": "voice.formality", "op": "replace", "value": 2},
            ]
        )


def test_collect_rejects_non_surface_shapes() -> None:
    with pytest.raises(OverrideError):
        collect_overrides("voice.formality = 2")
    with pytest.raises(OverrideError):
        collect_overrides([{"field": "voice.formality", "op": "eq", "value": 2}])


# ------------------------------------------------------------------------------------
# The hard M1 guard, structural half (§21.4 API5) — all refusals = invalid-override
# ------------------------------------------------------------------------------------


def test_guard_never_picks_an_entry() -> None:
    with pytest.raises(OverrideError, match="selection"):
        collect_overrides({"voice": "some-other-voice"})


def test_guard_path_is_exactly_dimension_attribute() -> None:
    with pytest.raises(OverrideError):
        collect_overrides({"voice.sliders.pace": 1})


def test_guard_unknown_dimension_refused() -> None:
    with pytest.raises(OverrideError, match="not a dimension"):
        collect_overrides({"recipe.values": {}})


@pytest.mark.parametrize(
    "attribute", ["id", "provenance", "schema_version", "extends", "metadata", "aliases"]
)
def test_guard_never_touches_schema_or_envelope(attribute: str) -> None:
    with pytest.raises(OverrideError) as exc:
        collect_overrides({f"voice.{attribute}": "anything"})
    assert exc.value.code == "invalid-override"


def test_guard_hard_limits_never_overridable() -> None:
    with pytest.raises(OverrideError, match="reconcile gate"):
        collect_overrides({"platform.hard_limits": {"post_char_limit": 1}})


def test_grammar_refusals_wrap_as_invalid_override() -> None:
    # Reserved set-subtract suffix (§13.2/§26) → CombineOperatorError → wrapped.
    with pytest.raises(OverrideError) as exc:
        collect_overrides({"voice.tags-": ["a"]})
    assert exc.value.code == "invalid-override"
    assert exc.value.__cause__ is not None
    # Malformed wrapper (reserved shape) → SurfaceSyntaxError → wrapped.
    with pytest.raises(OverrideError):
        collect_overrides({"voice.tags": {"combine": "union", "extra": 1}})


# ------------------------------------------------------------------------------------
# The schema half (validate_override_against_schema, apply-at-bind)
# ------------------------------------------------------------------------------------


def test_schema_guard_never_adds_an_attribute() -> None:
    (override,) = collect_overrides({"voice.undeclared_attr": 1}).items
    with pytest.raises(OverrideError, match="never ADDS"):
        validate_override_against_schema(override, _SCHEMA)


def test_schema_guard_union_on_ordered_list_refused() -> None:
    (override,) = collect_overrides({"format.parts+": ["extra"]}).items
    with pytest.raises(OverrideError) as exc:
        validate_override_against_schema(override, _SCHEMA)
    assert exc.value.code == "invalid-override"
    assert "union" in str(exc.value)


def test_schema_guard_operand_type_refused() -> None:
    (override,) = collect_overrides({"voice.formality": "very"}).items
    with pytest.raises(OverrideError):
        validate_override_against_schema(override, _SCHEMA)


def test_schema_guard_accepts_declared_typed_binding() -> None:
    (override,) = collect_overrides({"voice.tags+": ["a"]}).items
    validate_override_against_schema(override, _SCHEMA)  # returns None — valid


# ------------------------------------------------------------------------------------
# CA7 staging split
# ------------------------------------------------------------------------------------


def test_stage_split_compose_vs_render() -> None:
    overrides = collect_overrides(
        {
            "voice.formality": 2,
            "topic.why": "prose",
            "platform.reconcile_strategy": "split",
            "output-type.name": "x",
            "presentation.css": "",
            "language.name": "English",
        }
    )
    compose_dims = {o.dimension for o in overrides.compose_items}
    render_dims = {o.dimension for o in overrides.render_items}
    assert compose_dims == {"voice", "topic"}
    assert render_dims == {"platform", "output-type", "presentation", "language"}
    assert len(overrides.compose_items) + len(overrides.render_items) == len(overrides)
    assert [o.path for o in overrides.for_dimension("voice")] == ["voice.formality"]
