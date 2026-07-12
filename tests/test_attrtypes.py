"""Step-8 tests: the §11.1 attribute-type system — typed validation REFUSES coercions.

Includes the two MANDATORY negative fixtures the G4 gate assigned to step 8 (step-2 §3,
step-6 parameter sheet item 2): D1 — `1_000` in a text-typed field; D2 — a bare date in a
non-`date-window` field. Both are driven through the real pinned YAML loader end to end.
Also covers the load-bearing list/set distinction: union-on-list = schema ERROR (§11.1).
"""

import datetime

import pytest

from pipeline.attrtypes import (
    SLIDER_MAX,
    SLIDER_MIN,
    AttrTypeSpec,
    CombineOperatorError,
    SchemaTypeError,
    ValueValidationError,
    parse_type_spec,
    validate_combine_operator,
    validate_value,
)
from pipeline.yamlio import load_frontmatter

TEXT = AttrTypeSpec(kind="text")
MARKDOWN = AttrTypeSpec(kind="markdown")
NUMBER = AttrTypeSpec(kind="number")
SLIDER = AttrTypeSpec(kind="slider")
RANGE = AttrTypeSpec(kind="range")
REF = AttrTypeSpec(kind="ref")
BOOL = AttrTypeSpec(kind="bool")
DATE_WINDOW = AttrTypeSpec(kind="date-window")
ENUM_PROVENANCE = AttrTypeSpec(kind="enum", values=("framework", "instance"))
ENUM_NORWAY = AttrTypeSpec(kind="enum", values=("no", "yes", "on", "off"))
LIST_OF_REFS = AttrTypeSpec(kind="list", element=REF)
SET_OF_REFS = AttrTypeSpec(kind="set", element=REF)
UNTYPED_SET = AttrTypeSpec(kind="set")
MAP_OF_SLIDERS = AttrTypeSpec(kind="map", element=SLIDER)


# ---------------------------------------------------------------------------
# The two MANDATORY gate fixtures (step-2 §3 dispositions D1 and D2)
# ---------------------------------------------------------------------------


def test_d1_underscore_numeric_in_text_field_is_refused() -> None:
    """D1: `1_000` loads as int 1000 (1.1 leniency); a text field must refuse it loudly."""
    data, _ = load_frontmatter("---\ntitle: 1_000\n---\nbody\n")
    assert data is not None
    assert data["title"] == 1000  # the documented loader deviation
    assert type(data["title"]) is int
    with pytest.raises(ValueValidationError) as excinfo:
        validate_value(TEXT, data["title"], path="title")
    assert excinfo.value.code == "value-type-refused"


def test_d2_bare_date_in_non_date_window_field_is_refused() -> None:
    """D2: a bare date loads as datetime.date; ONLY date-window may accept it."""
    data, _ = load_frontmatter("---\npublished: 2026-07-12\n---\nbody\n")
    assert data is not None
    loaded = data["published"]
    assert loaded == datetime.date(2026, 7, 12)  # the documented loader deviation
    for spec in (TEXT, MARKDOWN, NUMBER, ENUM_PROVENANCE, REF):
        with pytest.raises(ValueValidationError):
            validate_value(spec, loaded, path="published")
    validate_value(DATE_WINDOW, loaded, path="published")  # the one legitimate home


# ---------------------------------------------------------------------------
# Per-type acceptance + coercion refusal
# ---------------------------------------------------------------------------


def test_text_and_markdown_accept_strings_only() -> None:
    validate_value(TEXT, "prose")
    validate_value(MARKDOWN, "## heading\n\nprose")
    for bad in (1000, 1.5, True, None, ["a"], {"a": 1}):
        with pytest.raises(ValueValidationError):
            validate_value(TEXT, bad)
        with pytest.raises(ValueValidationError):
            validate_value(MARKDOWN, bad)


def test_enum_accepts_declared_members_only() -> None:
    validate_value(ENUM_PROVENANCE, "framework")
    validate_value(ENUM_PROVENANCE, "instance")
    with pytest.raises(ValueValidationError):
        validate_value(ENUM_PROVENANCE, "Framework")  # case is meaning; no casefold coercion
    with pytest.raises(ValueValidationError):
        validate_value(ENUM_PROVENANCE, "unknown-member")
    with pytest.raises(ValueValidationError):
        validate_value(ENUM_PROVENANCE, True)  # a 1.1-style coerced bool is refused


def test_enum_norway_tokens_are_legal_members_under_the_pinned_loader() -> None:
    # The exact token class G4 protects: 'no'/'yes'/'on'/'off' as enum members.
    data, _ = load_frontmatter("---\nreply: no\n---\n")
    assert data is not None
    validate_value(ENUM_NORWAY, data["reply"])  # loads as the STRING 'no' -> valid member


def test_number_accepts_int_and_float_refuses_bool_and_nonfinite() -> None:
    validate_value(NUMBER, 42)
    validate_value(NUMBER, 1.5)
    validate_value(NUMBER, -12)
    with pytest.raises(ValueValidationError):
        validate_value(NUMBER, True)  # bool subclasses int; still refused
    with pytest.raises(ValueValidationError):
        validate_value(NUMBER, False)
    with pytest.raises(ValueValidationError):
        validate_value(NUMBER, "42")  # no string-to-number coercion
    for nonfinite in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueValidationError):
            validate_value(NUMBER, nonfinite)  # .inf/.NaN load fine but are not preimageable


def test_bool_accepts_exactly_bool() -> None:
    validate_value(BOOL, True)
    validate_value(BOOL, False)
    for bad in ("no", "true", 0, 1, None):
        with pytest.raises(ValueValidationError):
            validate_value(BOOL, bad)


def test_slider_bounds_and_int_strictness() -> None:
    for ok in range(SLIDER_MIN, SLIDER_MAX + 1):
        validate_value(SLIDER, ok)
    for bad in (SLIDER_MIN - 1, SLIDER_MAX + 1, 0, 6, -3):
        with pytest.raises(ValueValidationError):
            validate_value(SLIDER, bad)
    with pytest.raises(ValueValidationError):
        validate_value(SLIDER, 3.0)  # no float-to-int coercion
    with pytest.raises(ValueValidationError):
        validate_value(SLIDER, True)  # bool is not a slider notch
    with pytest.raises(ValueValidationError):
        validate_value(SLIDER, "3")


def test_range_is_a_two_element_ordered_numeric_pair() -> None:
    validate_value(RANGE, [1, 10])
    validate_value(RANGE, [0.5, 0.5])  # degenerate lo == hi is a valid window
    validate_value(RANGE, [-5, 5])
    for bad in ([10, 1], [1], [1, 2, 3], "1-10", {"lo": 1, "hi": 10}, [1, "10"], [True, 2]):
        with pytest.raises(ValueValidationError):
            validate_value(RANGE, bad)
    with pytest.raises(ValueValidationError):
        validate_value(RANGE, [1, float("inf")])


def test_ref_enforces_the_slug_alphabet() -> None:
    validate_value(REF, "linkedin")
    validate_value(REF, "x-our-cto")  # the §11.4 instance prefix is part of the id
    validate_value(REF, "a")  # 1 char minimum
    validate_value(REF, "a" * 40)  # 40 char maximum
    for bad in (
        "Our-CTO",  # uppercase
        "our_cto",  # underscore not in the slug alphabet
        "-leading",
        "trailing-",
        "",
        "a" * 41,
        "dots.not.allowed",
        "tilde~no",
        123,
        None,
    ):
        with pytest.raises(ValueValidationError):
            validate_value(REF, bad)


def test_date_window_accepts_dates_and_ordered_date_pairs() -> None:
    validate_value(DATE_WINDOW, datetime.date(2026, 7, 12))
    validate_value(DATE_WINDOW, [datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)])
    validate_value(DATE_WINDOW, [datetime.date(2026, 7, 12), datetime.date(2026, 7, 12)])
    with pytest.raises(ValueValidationError):
        validate_value(DATE_WINDOW, [datetime.date(2026, 12, 31), datetime.date(2026, 1, 1)])
    with pytest.raises(ValueValidationError):
        validate_value(DATE_WINDOW, "2026-07-12")  # strings do not silently become dates
    with pytest.raises(ValueValidationError):
        validate_value(DATE_WINDOW, datetime.datetime(2026, 7, 12, 10, 0))  # date-granular
    with pytest.raises(ValueValidationError):
        validate_value(
            DATE_WINDOW, [datetime.datetime(2026, 7, 12, 0, 0), datetime.date(2026, 7, 13)]
        )


def test_list_is_ordered_and_element_typed() -> None:
    validate_value(LIST_OF_REFS, ["intro", "body", "outro"])
    validate_value(LIST_OF_REFS, [])
    validate_value(LIST_OF_REFS, ["dup", "dup"])  # ordered lists MAY repeat (they are not sets)
    with pytest.raises(ValueValidationError):
        validate_value(LIST_OF_REFS, ["ok", "NOT-OK"])
    with pytest.raises(ValueValidationError):
        validate_value(LIST_OF_REFS, "not-a-sequence")


def test_set_elements_are_leaf_and_exact_duplicates_are_refused() -> None:
    validate_value(SET_OF_REFS, ["alpha", "beta"])
    validate_value(UNTYPED_SET, ["a", 1, True])  # heterogeneous leaves are fine
    with pytest.raises(ValueValidationError):
        validate_value(SET_OF_REFS, ["alpha", "alpha"])  # duplicate = authoring error, loud
    with pytest.raises(ValueValidationError):
        validate_value(UNTYPED_SET, [{"nested": "map"}])  # leaf elements only (§11.1)
    with pytest.raises(ValueValidationError):
        validate_value(UNTYPED_SET, [datetime.date(2026, 7, 12)])  # dates are not set leaves
    # Type-distinguishing dedupe: True is not 1, 1 is not 1.0 — no silent merge.
    validate_value(UNTYPED_SET, [True, 1, 1.0])


def test_set_duplicate_key_agrees_with_canonicalization_on_negative_zero() -> None:
    # RV-1 alignment: -0.0 and 0.0 render differently, so canonical_set keeps both —
    # duplicate detection here must agree (an ==-keyed check refused them as duplicates).
    validate_value(UNTYPED_SET, [0.0, -0.0])  # two distinct members, not a duplicate
    validate_value(AttrTypeSpec(kind="set", element=NUMBER), [-0.0, 0.0])
    with pytest.raises(ValueValidationError):
        validate_value(UNTYPED_SET, [-0.0, -0.0])  # a true duplicate is still refused


def test_untyped_set_elements_refuse_non_finite_floats() -> None:
    # RV-2: the untyped-element branch mirrors `number`'s finite check — .inf/.NaN must
    # be refused at validation, not first at canonicalization.
    for bad in (float("inf"), float("-inf"), float("nan")):
        with pytest.raises(ValueValidationError):
            validate_value(UNTYPED_SET, [bad])
    validate_value(UNTYPED_SET, [1.5])  # finite floats remain valid members


def test_map_requires_string_keys_and_validates_typed_values() -> None:
    validate_value(MAP_OF_SLIDERS, {"formality": 4, "energy": 2})
    with pytest.raises(ValueValidationError):
        validate_value(MAP_OF_SLIDERS, {"formality": 9})  # element validation recurses
    with pytest.raises(ValueValidationError):
        validate_value(MAP_OF_SLIDERS, {1: 3})  # non-string key
    with pytest.raises(ValueValidationError):
        validate_value(MAP_OF_SLIDERS, ["not", "a", "map"])
    untyped_map = AttrTypeSpec(kind="map")
    validate_value(untyped_map, {"anything": ["goes", {"here": 1}]})


# ---------------------------------------------------------------------------
# Combine operators: the load-bearing list/set distinction (§11.1/§12.4)
# ---------------------------------------------------------------------------


def test_union_on_list_is_a_schema_error() -> None:
    with pytest.raises(CombineOperatorError) as excinfo:
        validate_combine_operator(LIST_OF_REFS, "union")
    assert excinfo.value.code == "invalid-combine-operator"


def test_union_is_valid_only_on_sets() -> None:
    validate_combine_operator(SET_OF_REFS, "union")
    validate_combine_operator(UNTYPED_SET, "union")
    for spec in (TEXT, NUMBER, MAP_OF_SLIDERS, ENUM_PROVENANCE, BOOL, LIST_OF_REFS):
        with pytest.raises(CombineOperatorError):
            validate_combine_operator(spec, "union")


def test_replace_is_valid_everywhere() -> None:
    for spec in (TEXT, NUMBER, MAP_OF_SLIDERS, ENUM_PROVENANCE, LIST_OF_REFS, SET_OF_REFS):
        validate_combine_operator(spec, "replace")


def test_set_subtract_is_reserved_and_refused() -> None:
    with pytest.raises(CombineOperatorError) as excinfo:
        validate_combine_operator(SET_OF_REFS, "-")
    assert "reserved" in str(excinfo.value)


def test_unknown_combine_operators_are_refused() -> None:
    for bad in ("merge", "append", "subtract", "UNION"):
        with pytest.raises(CombineOperatorError):
            validate_combine_operator(SET_OF_REFS, bad)


def test_set_of_maps_is_undeclarable() -> None:
    # §11.1: set elements are leaf — a set-of-maps cannot even be declared, which closes
    # the union-on-set-of-maps schema-error class at the declaration site.
    with pytest.raises(SchemaTypeError):
        AttrTypeSpec(kind="set", element=AttrTypeSpec(kind="map"))
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "set", "element": "map"})


# ---------------------------------------------------------------------------
# Type-spec parsing (the surface step 11's _schema.yaml loader drives)
# ---------------------------------------------------------------------------


def test_parse_type_spec_from_bare_string() -> None:
    assert parse_type_spec("number") == NUMBER
    assert parse_type_spec("date-window") == DATE_WINDOW


def test_parse_type_spec_from_mapping() -> None:
    assert parse_type_spec({"type": "enum", "values": ["framework", "instance"]}) == ENUM_PROVENANCE
    assert parse_type_spec({"type": "set", "element": "ref"}) == SET_OF_REFS
    assert parse_type_spec({"type": "map", "element": "slider"}) == MAP_OF_SLIDERS


def test_parse_type_spec_refuses_malformed_declarations() -> None:
    with pytest.raises(SchemaTypeError):
        parse_type_spec("no-such-type")
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "enum"})  # enum requires values
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "enum", "values": ["a", "a"]})  # duplicate members
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "number", "values": ["a"]})  # values only on enum
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "number", "element": "ref"})  # element only on collections
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "list", "element": {"type": "list", "element": "ref"}})
    with pytest.raises(SchemaTypeError):
        parse_type_spec({"type": "text", "extra": True})  # unknown keys are refused
    with pytest.raises(SchemaTypeError):
        parse_type_spec(42)  # type: ignore[arg-type]


def test_validator_never_transforms_the_value() -> None:
    # Refusal-not-coercion, structurally: validate_value returns None, so no call site can
    # ever consume a "converted" value.
    assert validate_value(NUMBER, 42) is None
    assert validate_value(SET_OF_REFS, ["a", "b"]) is None
