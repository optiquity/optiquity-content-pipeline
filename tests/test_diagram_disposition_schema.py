"""C4a — the `formats.diagram_disposition` enum attribute + its identity / pre-spend guarantees
(DR-9).

The attribute joins `formats/_schema.yaml` at the NEUTRAL empty member `""` with NO schema_version
bump: an empty-member enum is a genuine empty L0 floor, so it is additive-at-floor (the lint rule
`pipeline/lint.py._is_empty_floor_default`, exercised in tests/test_lint.py). These tests lock the
three properties that make that safe:

  * ZERO identity churn at the floor — a Format riding `""` mints the byte-IDENTICAL artifact-id to
    the pre-attribute state (the `""` floor is omitted from the §7.2 preimage delta, ids.py).
  * HONEST churn off the floor — a real member (`require`) enters the delta and changes the id.
  * PRE-SPEND typo refusal — a non-member value is refused at plan resolution (the closed-schema
    enum validation, reached via `validate_override_against_schema` at begin-session) BEFORE any
    writer call, and no `neutral` token exists (neutral is the `""` floor, never a literal member).

C4a DECLARES the attribute only; the per-artifact require/suppress compose gate is C4b.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.attrtypes import ValueValidationError
from pipeline.ids import (
    EntryBinding,
    build_artifact_preimage,
    delta_vs_floor,
    mint_artifact_id,
)
from pipeline.overrides import OverrideError, collect_overrides, validate_override_against_schema
from pipeline.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMATS_SCHEMA = load_schema(REPO_ROOT / "formats" / "_schema.yaml")

_ATTR = "diagram_disposition"


def _preimage(format_binding: EntryBinding) -> dict:
    """A minimal, deterministic §7.2 artifact preimage varying ONLY the Format binding — the home
    of `diagram_disposition`. Everything else is held constant, so any id difference is attributable
    solely to the disposition."""
    return build_artifact_preimage(
        topic=EntryBinding("graphify"),
        persona=EntryBinding("cto"),
        format=format_binding,
        voice=EntryBinding("crisp", effective={"formality": 4}, defaults={"formality": 3}),
        goals=[EntryBinding("explain")],
        source_subset=["x-acme-repo"],
        source_commit={"x-acme-repo": "0" * 40},
    )


# --- the attribute is declared at the neutral "" floor, no version bump ------------------------


def test_declared_at_empty_floor_with_no_version_bump() -> None:
    # The chosen path: the attribute ships WITHOUT a schema_version bump (formats stays v1).
    assert FORMATS_SCHEMA.schema_version == 1
    spec = FORMATS_SCHEMA.attributes[_ATTR]
    assert spec.type.kind == "enum"
    assert list(spec.type.values) == ["", "suppress", "resist", "prefer", "require"]
    assert spec.default == ""  # the NEUTRAL empty member is the floor
    assert FORMATS_SCHEMA.defaults()[_ATTR] == ""


# --- ZERO identity churn at the floor (the crux) ----------------------------------------------


def test_diagram_disposition_floor_omits_from_id() -> None:
    # A Format riding the "" floor mints the byte-IDENTICAL artifact-id to a Format that never
    # declared the attribute (the pre-change state) — the floor value is omitted from the §7.2
    # preimage delta (ids.py), so shipping the attribute churns NO existing id.
    baseline = _preimage(EntryBinding("linkedin-post"))  # attribute ABSENT (pre-change state)
    at_floor = _preimage(
        EntryBinding("linkedin-post", effective={_ATTR: ""}, defaults={_ATTR: ""})
    )
    assert at_floor == baseline  # the "" floor is invisible to the preimage
    assert mint_artifact_id(at_floor) == mint_artifact_id(baseline)


def test_delta_vs_floor_omits_the_empty_member() -> None:
    # The mechanism the id-identity rests on: `delta_vs_floor` drops any attribute equal to its
    # schema default, so the "" floor never enters the identity delta (§7.2).
    defaults = FORMATS_SCHEMA.defaults()
    delta = delta_vs_floor({**defaults, _ATTR: ""}, defaults, where="format")
    assert _ATTR not in delta


# --- HONEST churn off the floor ----------------------------------------------------------------


def test_non_neutral_enters_id() -> None:
    # A real member honestly ENTERS the delta and CHANGES the id — off-floor is a genuine content
    # change, never free. This is the honest counterpart to the zero-churn floor.
    baseline = _preimage(EntryBinding("linkedin-post"))
    required = _preimage(
        EntryBinding("linkedin-post", effective={_ATTR: "require"}, defaults={_ATTR: ""})
    )
    assert required != baseline
    assert mint_artifact_id(required) != mint_artifact_id(baseline)
    defaults = FORMATS_SCHEMA.defaults()
    delta = delta_vs_floor({**defaults, _ATTR: "require"}, defaults, where="format")
    assert delta[_ATTR] == "require"


# --- pre-spend refusals (before any writer call) ----------------------------------------------


def test_no_neutral_token_accepted() -> None:
    # "neutral" is the "" floor, NEVER a literal member. A `neutral` value in an authored Format
    # entry is refused by the closed-schema enum validation (there is no such member)...
    with pytest.raises(ValueValidationError):
        FORMATS_SCHEMA.validate_attribute_values({_ATTR: "neutral"})
    # ...and the same refusal holds on the `--set` run surface.
    (override,) = collect_overrides({"format.diagram_disposition": "neutral"}).items
    with pytest.raises(OverrideError):
        validate_override_against_schema(override, FORMATS_SCHEMA)


def test_enum_typo_refused_pre_spend() -> None:
    # A `--set format.diagram_disposition=requre` typo is refused at plan resolution by the exact
    # `validate_override_against_schema` the cascade runs at begin-session — BEFORE any writer call,
    # so a typo spends zero tokens. The knob is inert in C4a but fully validated.
    (override,) = collect_overrides({"format.diagram_disposition": "requre"}).items
    with pytest.raises(OverrideError) as exc:
        validate_override_against_schema(override, FORMATS_SCHEMA)
    assert exc.value.code == "invalid-override"


def test_valid_member_override_accepted() -> None:
    # Positive control: a real member passes the same pre-spend guard cleanly.
    (override,) = collect_overrides({"format.diagram_disposition": "require"}).items
    validate_override_against_schema(override, FORMATS_SCHEMA)  # returns None — valid
