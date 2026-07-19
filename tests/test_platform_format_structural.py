"""DR-4 COMMIT C6 tests: the Platform per-format HARD structural class `format_structural`.

Design authority: `docs/design.md` §5.3/§12.7/§16 and the FINAL RECONCILED DR-4 build plan,
COMMIT C6 (the Platform `format_structural` attribute; floor `{}`; the THIRD §12.7 class).

What C6 adds: a `format_structural` attribute to `platforms/_schema.yaml` (floor `{}` = no
per-venue tightening) — a per-(format-id -> section-conformance-schema) map that TIGHTENS the
Format's base `section_schema` for a venue (optional->required, forbid a section, tighten a
per-section numeric bound). It is a HARD class (blocks at the reconcile structural gate, wired
in C8), the sibling of advisory `format_advisories` and numeric `hard_limits`, and it is
M2-EXCLUDED exactly like `hard_limits` (M1-resolved from `entry.effective`, never overridable).

This file proves, WITHOUT shipping any real journal Platform entry (those land in C10):
  * the schema declares `format_structural` at floor `{}` (a bare untyped map, like `hard_limits`)
    with NO `schema_version` bump (the global version-equality lint stays green, C3 finding);
  * every shipped Platform validates and rides the floor (byte-safe additive change);
  * a FIXTURE `format_structural` (a journal-B "forbid acknowledgements" shape) parses into the
    SAME C2 vocabulary (`pipeline.sections`) — single-sourced, never forked;
  * the S-3 disjointness lint (#4a): a `format_structural` section-limit NAME must never also be
    a `hard_limits` key — it fires on a double-homed fixture, stays clean on a partitioned one;
  * a platform at floor `{}` yields a byte-identical `fit_digest` (trivially now — the 5th
    OMIT-WHEN-FLOOR preimage component lands in C8; this file asserts the current 4-key preimage).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.canonical import canonical_json_bytes
from pipeline.entries import load_entry
from pipeline.outline import normalize_outline
from pipeline.reconcile import (
    RECONCILE_INPUT_COMPONENTS,
    ReconcileRequest,
    fit_digest,
    reconcile_inputs_preimage,
)
from pipeline.schema import SCHEMA_FILENAME, load_schema
from pipeline.sections import (
    AXIS_ROLE,
    SEVERITY_ERROR,
    Count,
    Length,
    Order,
    Presence,
    Selector,
    check_conformance,
    parse_sections,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PLATFORMS_DIR = REPO_ROOT / "platforms"
REGISTRY_ROOTS = ("topics", "personas", "platforms", "formats", "presentations", "output-types")


def _platforms_schema():
    return load_schema(PLATFORMS_DIR / SCHEMA_FILENAME)


# ---------------------------------------------------------------------------
# The schema: `format_structural` is declared, a bare untyped `map`, floored `{}`.
# ---------------------------------------------------------------------------


def test_platforms_schema_declares_format_structural_at_empty_floor() -> None:
    schema = _platforms_schema()
    assert "format_structural" in schema.attributes
    spec = schema.attributes["format_structural"]
    # A bare untyped `map` (element None): a per-format value is a LIST of rule-dicts, which
    # attrtypes cannot deep-declare as a map element (map-of-list is not v1) — so the interior
    # is validated by parsing into the C2 vocabulary, not by a nested type spec. This mirrors
    # `hard_limits` (also a bare `map`), the M2-EXCLUDED HARD sibling.
    assert spec.type.kind == "map"
    assert spec.type.element is None
    # Floor `{}` = NO per-venue tightening -> every existing Platform is byte-safe.
    assert spec.default == {}
    assert schema.defaults()["format_structural"] == {}


def test_format_structural_mirrors_the_hard_limits_shape() -> None:
    """The M2-EXCLUDED HARD sibling: both are bare `map`s floored `{}` (not the nested
    `format_advisories` map-of-map, which is the ADVISORY per-format projection)."""
    schema = _platforms_schema()
    hard = schema.attributes["hard_limits"]
    structural = schema.attributes["format_structural"]
    assert structural.type.kind == hard.type.kind == "map"
    assert structural.type.element is hard.type.element is None
    assert structural.default == hard.default == {}


def test_no_schema_version_bump_keeps_the_version_equality_lint_green() -> None:
    """C3 finding: `_lint_version_equality` enforces ONE GLOBAL `schema_version`, so a
    per-schema bump goes RED in the standing gate. `format_structural` ships additive-at-floor
    WITHOUT any bump — the platforms schema stays at v1, equal to every other registry schema."""
    assert _platforms_schema().schema_version == 1
    versions = set()
    for root in REGISTRY_ROOTS:
        schema_path = REPO_ROOT / root / SCHEMA_FILENAME
        if schema_path.exists():
            versions.add(load_schema(schema_path).schema_version)
    # The ONE global number, copied across every co-located _schema.yaml (SV2 §11.2).
    assert versions == {1}


def test_existing_platforms_validate_and_ride_the_format_structural_floor() -> None:
    """Every shipped Platform loads + schema-validates; none SETS `format_structural`
    (they ride the floor — a missing attribute is never an error, §11.1/§12.2)."""
    schema = _platforms_schema()
    loaded = {}
    for path in sorted(PLATFORMS_DIR.glob("*.md")):
        if path.name.endswith(".template.md"):
            continue
        entry = load_entry(path, schema)
        loaded[entry.id] = entry
        assert entry.provenance == "framework"
        assert "format_structural" not in entry.set_attributes
    # The shipped platform set exists and rides the floor.
    for pid in ("linkedin", "github", "medium-post", "corporate-website"):
        assert pid in loaded


# ---------------------------------------------------------------------------
# A FIXTURE `format_structural` (a journal-B "forbid acknowledgements" shape) parses into
# the SAME C2 vocabulary (`pipeline.sections`) — single-sourced, never a forked grammar.
# The SHIPPED journal Platform entries land in C10; this file exercises the SHAPE via fixtures.
# ---------------------------------------------------------------------------


def _selector(spec: dict) -> Selector:
    return Selector(spec["axis"], spec["value"])


def _to_rule(spec: dict):
    """Reduce ONE serialized rule-dict into the C2 vocabulary — the SAME reduction the base
    Format `section_schema` uses (C3). A per-venue `format_structural` schema is NOT a forked
    grammar; it is the identical menu of rules."""
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


def _parse_format_structural(format_structural: dict, format_id: str):
    """Parse a per-format `format_structural` value (a list of rule-dicts) into a C2 Schema."""
    return tuple(_to_rule(spec) for spec in format_structural[format_id])


# journal-B TIGHTENS the base academic-paper genre for its venue: it FORBIDS an
# acknowledgements section (the base allowed it) and tightens the abstract's per-section
# NUMERIC length bound (#4a: section-addressed HERE, never in hard_limits).
JOURNAL_B_FORMAT_STRUCTURAL = {
    "academic-paper": [
        {"rule": "presence", "axis": "role", "value": "acknowledgements",
         "required": False, "severity": "error"},
        {"rule": "length", "axis": "role", "value": "abstract",
         "min_len": 0, "max_len": 200, "severity": "error"},
    ],
}

_BODY_WITH_ACKS = normalize_outline(
    "## Abstract {#abstract}\n\nWe study X.\n\n"
    "## Methods {#methods}\n\nWhat we did.\n\n"
    "## Acknowledgements {#acknowledgements}\n\nThanks to the reviewers.\n"
)

_BODY_NO_ACKS = normalize_outline(
    "## Abstract {#abstract}\n\nWe study X and report Y.\n\n"
    "## Methods {#methods}\n\nWhat we did.\n"
)


def test_journal_b_format_structural_parses_into_the_c2_vocabulary() -> None:
    schema = _parse_format_structural(JOURNAL_B_FORMAT_STRUCTURAL, "academic-paper")
    # Two rules: one forbidden-presence (forbid acknowledgements) + one per-section length.
    assert len(schema) == 2
    assert sum(isinstance(r, Presence) for r in schema) == 1
    assert sum(isinstance(r, Length) for r in schema) == 1
    forbidden = next(r for r in schema if isinstance(r, Presence))
    assert forbidden.required is False
    assert forbidden.selector.axis == AXIS_ROLE
    assert forbidden.selector.value == "acknowledgements"
    assert forbidden.severity == SEVERITY_ERROR
    length = next(r for r in schema if isinstance(r, Length))
    assert length.selector.axis == AXIS_ROLE
    assert length.selector.value == "abstract"
    assert length.max_len == 200


def test_journal_b_forbidden_section_fires_on_a_body_that_carries_it() -> None:
    schema = _parse_format_structural(JOURNAL_B_FORMAT_STRUCTURAL, "academic-paper")
    violations = check_conformance(parse_sections(_BODY_WITH_ACKS), schema)
    errors = [v for v in violations if v.severity == SEVERITY_ERROR]
    # The venue's forbidden acknowledgements section is present -> a HARD (error) violation.
    assert errors
    forbidden = [v for v in errors if isinstance(v.rule, Presence) and v.rule.required is False]
    assert forbidden
    assert any(v.rule.selector.value == "acknowledgements" for v in forbidden)


def test_journal_b_conforming_body_has_no_error_violations() -> None:
    schema = _parse_format_structural(JOURNAL_B_FORMAT_STRUCTURAL, "academic-paper")
    violations = check_conformance(parse_sections(_BODY_NO_ACKS), schema)
    errors = [v for v in violations if v.severity == SEVERITY_ERROR]
    # No acknowledgements section, abstract under the 200-char venue bound -> conformant.
    assert errors == []


# ---------------------------------------------------------------------------
# S-3 disjointness lint (D-6, #4a): a `format_structural` section-limit NAME must never ALSO
# be a `hard_limits` key. The two are disjoint by SCOPE — DR-4 governs a NAMED section
# (per-section numeric limits, section-addressed here), §16 governs the WHOLE artifact
# (capacity limits in hard_limits). This validator enforces the partition (a cheap lint the
# real reconcile/driver gate reuses in C8; homed here in-scope for C6).
# ---------------------------------------------------------------------------

_NUMERIC_RULE_KINDS = frozenset({"length", "count"})


def _section_limit_names(format_structural: dict) -> set[str]:
    """The NAMES carrying a per-section NUMERIC limit (a `length`/`count` rule on a named
    section) across every per-format schema in a `format_structural` map (#4a)."""
    names: set[str] = set()
    for schema in format_structural.values():
        for rule in schema:
            if rule.get("rule") in _NUMERIC_RULE_KINDS:
                names.add(rule["value"])
    return names


def format_structural_hard_limit_collisions(
    format_structural: dict, hard_limits: dict
) -> list[str]:
    """S-3 disjointness (#4a): the section-limit names that ALSO appear as `hard_limits` keys —
    empty iff the section/artifact partition holds. A non-empty result is an authoring defect:
    a per-section numeric limit must live in `format_structural` (section-addressed), NOT be
    double-homed as a whole-artifact `hard_limits` key."""
    return sorted(_section_limit_names(format_structural) & set(hard_limits))


def test_s3_disjointness_clean_partition_has_no_collisions() -> None:
    # journal-B section-limits its `abstract`; the venue's WHOLE-ARTIFACT cap is a disjoint key.
    hard_limits = {"post_char_limit": 65536}
    assert format_structural_hard_limit_collisions(JOURNAL_B_FORMAT_STRUCTURAL, hard_limits) == []


def test_s3_disjointness_lint_fires_on_a_double_homed_name() -> None:
    # WRONG: the `abstract` section-limit is ALSO homed as a whole-artifact hard_limits key —
    # the exact #4a double-home the partition forbids. The lint names the collision loudly.
    hard_limits = {"abstract": 200, "post_char_limit": 65536}
    collisions = format_structural_hard_limit_collisions(JOURNAL_B_FORMAT_STRUCTURAL, hard_limits)
    assert collisions == ["abstract"]


def test_s3_only_numeric_section_limits_partition_against_hard_limits() -> None:
    """The partition is about per-section NUMERIC limits (#4a). A FORBIDDEN section (a presence
    rule) is not a numeric section-limit, so a hard_limits key sharing that name is not an S-3
    collision — only `length`/`count` selector names are section-limit names."""
    presence_only = {
        "academic-paper": [
            {"rule": "presence", "axis": "role", "value": "acknowledgements",
             "required": False, "severity": "error"},
        ],
    }
    assert format_structural_hard_limit_collisions(presence_only, {"acknowledgements": 1}) == []


# ---------------------------------------------------------------------------
# fit_digest byte-identity at floor `{}` — trivially true NOW: the reconcile-inputs preimage
# does not yet read `format_structural`. The 5th OMIT-WHEN-FLOOR `structural` component lands
# in C8; this file pins the current 4-key preimage so C8's addition is a visible, tested delta.
# ---------------------------------------------------------------------------


def _floor_request(**overrides) -> ReconcileRequest:
    base = {
        "canonical_ir": {},  # reconcile_inputs_preimage never reads it (only the constraints)
        "artifact_id": "a-0000000000000000",
        "platform": "journal-b",
        "language": "en",
        "source_language": "en",
        "strategy": "adapt",
    }
    base.update(overrides)
    return ReconcileRequest(**base)


def test_reconcile_preimage_has_no_structural_component_yet() -> None:
    """C6 declares the schema attribute; the 5th preimage component is C8. Today the preimage
    is EXACTLY the four §16 components — no `structural` key exists to churn a `fit_digest`."""
    preimage = reconcile_inputs_preimage(_floor_request())
    assert set(preimage) == set(RECONCILE_INPUT_COMPONENTS)
    assert set(preimage) == {"strategy", "hard-limits", "advisory", "render-dims"}
    assert "structural" not in preimage
    assert "structural" not in RECONCILE_INPUT_COMPONENTS


def test_floor_format_structural_yields_a_byte_identical_fit_digest() -> None:
    """A Platform declaring `format_structural` at floor `{}` contributes ZERO to the fit
    identity: the preimage does not read it, so two logically-identical fits produce a
    byte-identical preimage and an identical `fit_digest`. (In C8 the 5th component is
    OMIT-WHEN-FLOOR, so a floor `{}` platform stays byte-identical there too.)"""
    a = reconcile_inputs_preimage(_floor_request())
    b = reconcile_inputs_preimage(_floor_request())
    assert canonical_json_bytes(a) == canonical_json_bytes(b)
    assert fit_digest(a) == fit_digest(b)
    assert len(fit_digest(a)) == 12


def test_declared_hard_limit_still_churns_the_fit_digest_structural_absent() -> None:
    """A control: the preimage DOES respond to a non-floor `hard_limits` deviation (proving the
    byte-identity above is a real floor-omit, not a dead preimage), while NO `structural`
    component participates yet (that arrives in C8)."""
    floor = reconcile_inputs_preimage(_floor_request(hard_limits={"max_chars": 1000},
                                                      hard_limit_defaults={"max_chars": 1000}))
    deviating = reconcile_inputs_preimage(_floor_request(hard_limits={"max_chars": 280},
                                                         hard_limit_defaults={"max_chars": 1000}))
    assert floor["hard-limits"] == {}
    assert deviating["hard-limits"] == {"max_chars": 280}
    assert fit_digest(floor) != fit_digest(deviating)
    assert "structural" not in floor and "structural" not in deviating


@pytest.mark.parametrize("bad_rule_kind", ["length", "count"])
def test_numeric_rule_kinds_are_recognized_section_limits(bad_rule_kind: str) -> None:
    """Both `length` AND `count` are per-section numeric limits under #4a, so either double-homed
    against a hard_limits key is an S-3 collision."""
    fs = {"g": [{"rule": bad_rule_kind, "axis": "role", "value": "abstract",
                 "min_len": 0, "max_len": 200, "cardinality": "?", "severity": "error"}]}
    assert format_structural_hard_limit_collisions(fs, {"abstract": 1}) == ["abstract"]
