"""DR-4 COMMIT C3 tests: the Format base `section_schema` attribute (identity-critical).

Design authority: `docs/design.md` §5.2/§7.2/§15 and the FINAL RECONCILED DR-4 build plan,
COMMIT C3 (the Format `section_schema` attribute; floor `[]`; the golden artifact-id corpus).

What C3 adds: a `section_schema` attribute to `formats/_schema.yaml` (floor `[]` = no contract)
and one framework academic-paper genre entry declaring a `section_schema` in the C2 vocabulary
(`pipeline.sections`). THE constraint this file proves: adding a new attribute AT ITS FLOOR
re-mints EVERY existing artifact-id BYTE-IDENTICAL — the floored attribute is omitted by
`delta_vs_floor` (`ids.py` §7.2), and a manifest `schema_version` bump is never an identity
input (`IDENTITY_EXCLUSIONS`). The golden corpus below pins that byte-identity with literal
hexes captured before the attribute existed.

Roles (`abstract`/`methods`/`results`) are ROLE selectors AUTHORED IN THE GENRE ENTRY — never
structural `type` kinds and never in the `pipeline.sections.SECTION_TYPES` carrier (which holds
genre-neutral structural kinds only). This file proves that separation too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.entries import load_entry
from pipeline.ids import (
    IDENTITY_EXCLUSIONS,
    EntryBinding,
    PreimageError,
    build_artifact_preimage,
    delta_vs_floor,
    mint_artifact_id,
)
from pipeline.layout import registry_dir
from pipeline.outline import normalize_outline
from pipeline.schema import SCHEMA_FILENAME, load_schema
from pipeline.sections import (
    AXIS_ROLE,
    SECTION_TYPES,
    SEVERITY_ERROR,
    Count,
    Length,
    Order,
    Presence,
    Selector,
    UnknownSectionTypeError,
    check_conformance,
    parse_sections,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FORMATS_DIR = registry_dir(REPO_ROOT, "formats")


# ---------------------------------------------------------------------------
# The schema: `section_schema` is declared, list-of-map, floored `[]`.
# ---------------------------------------------------------------------------


def _formats_schema():
    return load_schema(FORMATS_DIR / SCHEMA_FILENAME)


def test_formats_schema_declares_section_schema_at_empty_floor() -> None:
    schema = _formats_schema()
    assert "section_schema" in schema.attributes
    spec = schema.attributes["section_schema"]
    # A `list` of `map` rule-dicts (the C2 vocabulary, serialized).
    assert spec.type.kind == "list"
    assert spec.type.element is not None and spec.type.element.kind == "map"
    # Floor `[]` = NO contract → every existing Format is byte-safe (delta omits it).
    assert spec.default == []
    # The whole L0 floor: `parts` (pre-existing), `section_schema` (DR-4), and the DR-9
    # `diagram_disposition` empty-member enum — each at its empty floor (additive-at-floor: an
    # unset Format rides every floor, so `delta_vs_floor` omits them and every id is byte-safe).
    assert schema.defaults() == {"parts": [], "section_schema": [], "diagram_disposition": ""}


def test_existing_formats_still_validate_and_ride_the_section_schema_floor() -> None:
    """Every shipped Format loads + schema-validates; the ones that don't declare a
    `section_schema` set nothing new (they ride the floor — missing-attr is never an error)."""
    schema = _formats_schema()
    loaded = {}
    for path in sorted(FORMATS_DIR.glob("*.md")):
        if path.name.endswith(".template.md"):
            continue
        entry = load_entry(path, schema)
        loaded[entry.id] = entry
        assert entry.provenance == "framework"
    # The pre-existing genres exist and do NOT set section_schema (they floor to `[]`).
    for genre in ("readme", "long-form-essay", "product-requirements-document", "outline"):
        assert genre in loaded
        assert "section_schema" not in loaded[genre].set_attributes


# ---------------------------------------------------------------------------
# THE golden artifact-id corpus: a battery of existing coordinates re-mints
# BYTE-IDENTICAL after `section_schema` lands at its floor.
#
# GOLDEN hexes were captured BEFORE the attribute existed (the pre-DR-4 world:
# the Format binding carried only `parts: []`). `_mint(..., with_section_schema=…)`
# toggles whether the Format binding also carries `section_schema: []` at floor —
# the POST-DR-4 world the real resolver produces. Both must equal the golden.
# ---------------------------------------------------------------------------

GOLDEN_ARTIFACT_IDS = {
    "readme_cto": "a-e7c0eec15a261001",
    "essay_multi_goal": "a-9a31f3accc807f1f",
    "prd_plain": "a-7d7582bd77a37df8",
    "howto_two_src": "a-86bf98e14fddbbb3",
    "short_opinion": "a-f77401d4d025839a",
    "medium_review": "a-6574dff30af658b5",
}


def _fmt(entry_id: str, *, with_section_schema: bool) -> EntryBinding:
    """The Format binding. Pre-DR-4 carries only `parts: []`; post-DR-4 also carries
    `section_schema: []` (the new floor) in BOTH effective and defaults — the resolver
    emits floor-riding attributes into `effective`, so `delta_vs_floor` sees it in both."""
    floor = {"parts": []}
    if with_section_schema:
        floor = {"parts": [], "section_schema": []}
    return EntryBinding(entry_id, effective=dict(floor), defaults=dict(floor))


def _case(name: str, *, with_section_schema: bool) -> str:
    common = dict(
        topic=EntryBinding("graphify"),
        persona=EntryBinding("cto"),
        voice=EntryBinding("crisp"),
        goals=[EntryBinding("explain")],
        source_subset=["x-acme-repo"],
        source_commit={"x-acme-repo": "0" * 40},
    )
    specs = {
        "readme_cto": dict(
            format=_fmt("readme", with_section_schema=with_section_schema),
            voice=EntryBinding("crisp", effective={"formality": 4}, defaults={"formality": 3}),
        ),
        "essay_multi_goal": dict(
            format=_fmt("long-form-essay", with_section_schema=with_section_schema),
            voice=EntryBinding("crisp", effective={"formality": 4}, defaults={"formality": 3}),
            goals=[
                EntryBinding("explain"),
                EntryBinding("convince", effective={"cta": "book-a-demo"}, defaults={"cta": ""}),
            ],
            source_subset=["x-acme-repo", "x-acme-docs"],
            source_commit={"x-acme-repo": "0" * 40, "x-acme-docs": "1" * 40},
        ),
        "prd_plain": dict(
            format=_fmt("product-requirements-document", with_section_schema=with_section_schema),
            source_commit={"x-acme-repo": "a" * 40},
        ),
        "howto_two_src": dict(
            format=_fmt("how-to-documentation", with_section_schema=with_section_schema),
            voice=EntryBinding("crisp", effective={"formality": 2}, defaults={"formality": 3}),
            goals=[EntryBinding("explain"), EntryBinding("convince")],
            source_subset=["x-acme-repo", "x-acme-docs"],
            source_commit={"x-acme-repo": "9" * 40, "x-acme-docs": "3" * 40},
        ),
        "short_opinion": dict(
            format=_fmt("short-opinion-post", with_section_schema=with_section_schema),
            source_subset=["x-acme-docs"],
            source_commit={"x-acme-docs": "f" * 40},
        ),
        "medium_review": dict(
            format=_fmt("medium-review-post", with_section_schema=with_section_schema),
            voice=EntryBinding("crisp", effective={"formality": 5}, defaults={"formality": 3}),
            goals=[EntryBinding("convince", effective={"cta": "sign-up"}, defaults={"cta": ""})],
            source_commit={"x-acme-repo": "7" * 40},
        ),
    }
    kwargs = {**common, **specs[name]}
    return mint_artifact_id(build_artifact_preimage(**kwargs))


@pytest.mark.parametrize("name", sorted(GOLDEN_ARTIFACT_IDS))
def test_golden_corpus_pins_the_pre_dr4_bytes(name: str) -> None:
    """The pre-DR-4 mint (Format binding carries only `parts: []`) is byte-identical to the
    checked-in golden hex — a canonicalization change would move these and fail loudly."""
    assert _case(name, with_section_schema=False) == GOLDEN_ARTIFACT_IDS[name]


@pytest.mark.parametrize("name", sorted(GOLDEN_ARTIFACT_IDS))
def test_section_schema_at_floor_re_mints_every_id_unchanged(name: str) -> None:
    """THE identity constraint: the Format binding now ALSO carries `section_schema: []` at its
    floor (post-DR-4), yet every existing artifact-id re-mints BYTE-IDENTICAL to its golden —
    the floored attribute is omitted by `delta_vs_floor` (§7.2). Zero identity churn."""
    assert _case(name, with_section_schema=True) == GOLDEN_ARTIFACT_IDS[name]


def test_delta_vs_floor_omits_section_schema_at_floor() -> None:
    """The mechanism, unit-level: a floored `section_schema` never enters the identity delta,
    and a pre-existing floored `parts` is likewise absent."""
    delta = delta_vs_floor(
        {"parts": [], "section_schema": []}, {"parts": [], "section_schema": []}
    )
    assert delta == {}


def test_schema_version_bump_is_never_an_identity_input() -> None:
    """The manifest `schema_version` bump cannot churn any id: `schema_version` is an identity
    EXCLUSION (§7.3) and is refused outright if it ever reaches the preimage constructor."""
    assert "schema_version" in IDENTITY_EXCLUSIONS
    with pytest.raises(PreimageError, match="never an identity input"):
        delta_vs_floor({"schema_version": 2}, {})


def test_a_declared_section_schema_deviates_from_floor_and_changes_the_id() -> None:
    """The delta is NOT vacuous: a Format that DECLARES a non-empty `section_schema` deviates
    from the floor, enters `dimensions.format.delta`, and mints a DISTINCT id — proving the
    floor-omit above is a real identity carrier, not a dead attribute."""
    declared = [{"rule": "presence", "axis": "role", "value": "abstract",
                 "required": True, "severity": "error"}]
    floored = build_artifact_preimage(
        topic=EntryBinding("graphify"),
        persona=EntryBinding("cto"),
        format=_fmt("academic-paper", with_section_schema=True),
        voice=EntryBinding("crisp"),
        goals=[EntryBinding("explain")],
        source_subset=["x-acme-repo"],
        source_commit={"x-acme-repo": "0" * 40},
    )
    deviating = build_artifact_preimage(
        topic=EntryBinding("graphify"),
        persona=EntryBinding("cto"),
        format=EntryBinding(
            "academic-paper",
            effective={"parts": [], "section_schema": declared},
            defaults={"parts": [], "section_schema": []},
        ),
        voice=EntryBinding("crisp"),
        goals=[EntryBinding("explain")],
        source_subset=["x-acme-repo"],
        source_commit={"x-acme-repo": "0" * 40},
    )
    assert deviating["dimensions"]["format"]["delta"]["section_schema"] == declared
    assert mint_artifact_id(floored) != mint_artifact_id(deviating)


# ---------------------------------------------------------------------------
# The academic-paper entry parses into the C2 vocabulary via `pipeline.sections`.
# Roles live in the ENTRY (role selectors), never in the structural `type` carrier.
# ---------------------------------------------------------------------------


def _selector(spec: dict) -> Selector:
    return Selector(spec["axis"], spec["value"])


def _to_rule(spec: dict):
    kind = spec["rule"]
    if kind == "presence":
        return Presence(_selector(spec), required=spec["required"], severity=spec["severity"])
    if kind == "order":
        return Order(tuple(_selector(s) for s in spec["selectors"]), severity=spec["severity"])
    if kind == "count":
        return Count.from_spec(_selector(spec), spec["cardinality"], spec["severity"])
    if kind == "length":
        return Length(_selector(spec), spec["min_len"], spec["max_len"], spec["severity"])
    raise AssertionError(f"unknown rule kind {kind!r}")


def _academic_paper_schema():
    schema = _formats_schema()
    entry = load_entry(FORMATS_DIR / "academic-paper.md", schema)
    return entry, tuple(_to_rule(spec) for spec in entry.attributes["section_schema"])


_CONFORMING = normalize_outline(
    "## Abstract {#abstract}\n\nWe study X and report Y.\n\n"
    "## Introduction {#introduction}\n\nWhy X matters.\n\n"
    "## Methods {#methods}\n\nWhat we did.\n\n"
    "## Results {#results}\n\nWhat we observed.\n\n"
    "## Discussion {#discussion}\n\nWhat it means.\n\n"
    "## Conclusion {#conclusion}\n\nThe claim, restated.\n"
)

_MISSING_METHODS = normalize_outline(
    "## Abstract {#abstract}\n\nWe study X and report Y.\n\n"
    "## Results {#results}\n\nWhat we observed.\n"
)


def test_academic_paper_section_schema_parses_into_the_c2_vocabulary() -> None:
    entry, schema = _academic_paper_schema()
    assert entry.provenance == "framework"
    # Five rules: three presence + one order + one length, exactly as authored.
    assert len(schema) == 5
    assert sum(isinstance(r, Presence) for r in schema) == 3
    assert sum(isinstance(r, Order) for r in schema) == 1
    assert sum(isinstance(r, Length) for r in schema) == 1
    # abstract/methods/results are ROLE-axis selectors (author-declared), not type kinds.
    presence_values = {r.selector.value for r in schema if isinstance(r, Presence)}
    assert presence_values == {"abstract", "methods", "results"}
    for r in schema:
        if isinstance(r, Presence):
            assert r.selector.axis == AXIS_ROLE
            assert r.required is True
            assert r.severity == SEVERITY_ERROR


def test_academic_paper_conforming_body_has_no_error_violations() -> None:
    _entry, schema = _academic_paper_schema()
    violations = check_conformance(parse_sections(_CONFORMING), schema)
    errors = [v for v in violations if v.severity == SEVERITY_ERROR]
    assert errors == []


def test_academic_paper_missing_required_section_is_an_error() -> None:
    _entry, schema = _academic_paper_schema()
    violations = check_conformance(parse_sections(_MISSING_METHODS), schema)
    errors = [v for v in violations if v.severity == SEVERITY_ERROR]
    # The absent `methods` presence rule fires at error severity.
    assert errors
    assert all(isinstance(v.rule, Presence) for v in errors)
    assert any(v.rule.selector.value == "methods" for v in errors)


def test_roles_live_in_the_entry_never_in_the_structural_type_carrier() -> None:
    """abstract/methods/results are ROLES: valid as role selectors, but NEVER structural `type`
    kinds — a type selector for one is refused (fail-closed), and none is in SECTION_TYPES."""
    for role in ("abstract", "methods", "results"):
        assert role not in SECTION_TYPES
        assert Selector.by_role(role).axis == AXIS_ROLE  # OK: roles are open
        with pytest.raises(UnknownSectionTypeError):
            Selector.by_type(role)  # refused: not a structural kind
