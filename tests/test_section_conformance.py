"""DR-4 COMMIT 2 tests: the typed-section conformance vocabulary + the pure checker.

C2 layers a section-conformance schema (an ORDERED list of à-la-carte MENU rules) and a
PURE `check_conformance(sections, schema) -> tuple[Violation, ...]` over C1's parsed
`Section` records. This suite pins:

- **Cardinality edges** — `?`={0,1}, `*`={0,}, `+`={1,}, the brace forms incl. a
  duplicate-count `{n}`/`{n,m}` bound, and the typed (never-a-crash) refusal of a bad spec.
- **The D-2 default-severity table** — required-missing -> error, forbidden-present ->
  error, order -> warning (overridable per-schema), Count/Length -> per-schema (no default).
- **Selector on EITHER axis** — a rule keyed by structural `type` AND a rule keyed by
  author `role` both enforce, and NEITHER axis re-owns the other.
- **The carrier discipline** — a `type` selector naming a non-carrier member is a
  one-file-add omission surfaced as a TYPED error, never a crash; `abstract`/`methods`/
  `results` are ROLE selectors, never `type` members.
- **Graduated flexibility** — a presence-ONLY schema (and the empty schema) is valid.
- **Purity** — `check_conformance` is a total function over parsed sections + a schema.
"""

from __future__ import annotations

import pytest

from pipeline.sections import (
    SECTION_TYPES,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    Cardinality,
    Count,
    Length,
    Order,
    Presence,
    Section,
    SectionGrammarError,
    SectionSchemaError,
    Selector,
    UnknownSectionTypeError,
    check_conformance,
    parse_cardinality,
    parse_sections,
)


def sec(role: str, type_: str = "prose", body: str = "", level: int = 2) -> Section:
    """Build a `Section` directly for precise role/type/body control in a check."""
    return Section(
        level=level, role=role, type=type_, heading=role, body=body, span=(0, 0)
    )


# ---------------------------------------------------------------------------
# Cardinality — the `?`/`*`/`+`/`{n,m}` parser and its edges.
# ---------------------------------------------------------------------------
def test_cardinality_symbolic_forms():
    assert parse_cardinality("?") == Cardinality(0, 1)
    assert parse_cardinality("*") == Cardinality(0, None)
    assert parse_cardinality("+") == Cardinality(1, None)


def test_cardinality_brace_forms():
    assert parse_cardinality("{2}") == Cardinality(2, 2)  # exact / duplicate-count
    assert parse_cardinality("{1,3}") == Cardinality(1, 3)
    assert parse_cardinality("{2,}") == Cardinality(2, None)
    assert parse_cardinality("{,3}") == Cardinality(0, 3)


def test_cardinality_sugar_equals_brace():
    assert parse_cardinality("?") == parse_cardinality("{0,1}")
    assert parse_cardinality("+") == parse_cardinality("{1,}")
    assert parse_cardinality("*") == parse_cardinality("{0,}")


def test_cardinality_whitespace_tolerated():
    assert parse_cardinality("  {1,2}  ") == Cardinality(1, 2)


@pytest.mark.parametrize("bad", ["{}", "{a}", "3", "{2,1}", "??", "{1,2,3}", "", "{,}x"])
def test_cardinality_invalid_is_typed_not_a_crash(bad):
    with pytest.raises(SectionSchemaError) as exc:
        parse_cardinality(bad)
    assert isinstance(exc.value, SectionGrammarError)
    assert isinstance(exc.value, ValueError)


def test_cardinality_direct_inverted_bounds_rejected():
    with pytest.raises(SectionSchemaError):
        Cardinality(3, 1)
    with pytest.raises(SectionSchemaError):
        Cardinality(-1, None)


# ---------------------------------------------------------------------------
# Count — cardinality bounds over the number of matching sections.
# ---------------------------------------------------------------------------
def test_count_exact_duplicate_bound():
    rule = Count(Selector.by_type("figure"), parse_cardinality("{2}"), SEVERITY_ERROR)
    one = (sec("f1", "figure"),)
    two = (sec("f1", "figure"), sec("f2", "figure"))
    three = (sec("f1", "figure"), sec("f2", "figure"), sec("f3", "figure"))
    assert check_conformance(one, (rule,)) != ()  # 1 < 2 -> under
    assert check_conformance(two, (rule,)) == ()  # exactly 2 -> conformant
    over = check_conformance(three, (rule,))
    assert len(over) == 1 and over[0].severity == SEVERITY_ERROR
    assert over[0].section is three[2]  # first section beyond the allowance


def test_count_optional_and_plus_and_star():
    opt = Count(Selector.by_role("abstract"), parse_cardinality("?"), SEVERITY_WARNING)
    plus = Count(Selector.by_role("ack"), parse_cardinality("+"), SEVERITY_ERROR)
    star = Count(Selector.by_role("note"), parse_cardinality("*"), SEVERITY_INFO)
    assert check_conformance((), (opt,)) == ()  # `?` allows zero
    assert check_conformance((sec("abstract"),), (opt,)) == ()  # ...or one
    assert check_conformance((sec("abstract"), sec("abstract")), (opt,)) != ()  # not two
    assert check_conformance((), (plus,)) != ()  # `+` needs >=1
    assert check_conformance((sec("ack"),), (plus,)) == ()
    # `*` never fails on count alone
    for n in range(4):
        assert check_conformance(tuple(sec("note") for _ in range(n)), (star,)) == ()


def test_count_bounded_range():
    rule = Count(Selector.by_type("table"), parse_cardinality("{1,2}"), SEVERITY_WARNING)
    assert check_conformance((), (rule,)) != ()  # 0 < 1
    assert check_conformance((sec("t", "table"),), (rule,)) == ()  # 1 ok
    two = (sec("t1", "table"), sec("t2", "table"))
    assert check_conformance(two, (rule,)) == ()  # 2 ok
    three = (*two, sec("t3", "table"))
    assert check_conformance(three, (rule,)) != ()  # 3 > 2


def test_count_from_spec_helper():
    rule = Count.from_spec(Selector.by_type("figure"), "+", SEVERITY_ERROR)
    assert rule.cardinality == Cardinality(1, None)
    assert check_conformance((), (rule,)) != ()


# ---------------------------------------------------------------------------
# Presence — required-missing and forbidden-present (both default to error, D-2).
# ---------------------------------------------------------------------------
def test_required_missing_is_error_by_default():
    rule = Presence(Selector.by_role("abstract"))  # required=True by default
    v = check_conformance((sec("intro"),), (rule,))
    assert len(v) == 1
    assert v[0].severity == SEVERITY_ERROR  # D-2 default
    assert v[0].section is None  # aggregate breach: nothing to point at
    assert v[0].rule is rule
    assert check_conformance((sec("abstract"),), (rule,)) == ()  # present -> conformant


def test_forbidden_present_is_error_by_default():
    rule = Presence(Selector.by_role("acknowledgements"), required=False)
    present = sec("acknowledgements")
    v = check_conformance((sec("intro"), present), (rule,))
    assert len(v) == 1
    assert v[0].severity == SEVERITY_ERROR  # D-2 default
    assert v[0].section is present  # points at the forbidden section
    assert check_conformance((sec("intro"),), (rule,)) == ()  # absent -> conformant


def test_forbidden_reports_each_present_occurrence():
    rule = Presence(Selector.by_type("callout"), required=False)
    sections = (sec("c1", "callout"), sec("body"), sec("c2", "callout"))
    v = check_conformance(sections, (rule,))
    assert [x.section for x in v] == [sections[0], sections[2]]  # document order


def test_presence_severity_override():
    rule = Presence(Selector.by_role("abstract"), severity=SEVERITY_WARNING)
    v = check_conformance((), (rule,))
    assert v[0].severity == SEVERITY_WARNING  # overridden from the error default


# ---------------------------------------------------------------------------
# Order — a relative-order sequence; default warning (D-2), overridable to error.
# ---------------------------------------------------------------------------
def test_order_violation_defaults_to_warning():
    rule = Order((Selector.by_role("abstract"), Selector.by_role("methods")))
    good = (sec("abstract"), sec("methods"))
    bad = (sec("methods"), sec("abstract"))
    assert check_conformance(good, (rule,)) == ()
    v = check_conformance(bad, (rule,))
    assert len(v) == 1
    assert v[0].severity == SEVERITY_WARNING  # D-2 default
    assert v[0].rule is rule


def test_order_severity_override_to_error():
    rule = Order(
        (Selector.by_role("abstract"), Selector.by_role("methods")),
        severity=SEVERITY_ERROR,
    )
    v = check_conformance((sec("methods"), sec("abstract")), (rule,))
    assert len(v) == 1 and v[0].severity == SEVERITY_ERROR


def test_order_absent_middle_selector_still_catches_a_breach():
    # abstract -> methods -> results, with methods ABSENT: an out-of-order abstract/results
    # pair must still be caught (all i<j pairs are checked, not just adjacent).
    rule = Order(
        (
            Selector.by_role("abstract"),
            Selector.by_role("methods"),
            Selector.by_role("results"),
        )
    )
    bad = (sec("results"), sec("abstract"))  # results before abstract, methods absent
    assert check_conformance(bad, (rule,)) != ()


def test_order_needs_two_selectors():
    with pytest.raises(SectionSchemaError):
        Order((Selector.by_role("solo"),))


# ---------------------------------------------------------------------------
# Length — min/max over each matched section's body (per-schema severity).
# ---------------------------------------------------------------------------
def test_length_min_violation():
    rule = Length(Selector.by_role("abstract"), min_len=10, max_len=None, severity=SEVERITY_ERROR)
    short = (sec("abstract", body="tiny"),)  # len 4 < 10
    ok = (sec("abstract", body="a sufficiently long body"),)
    assert check_conformance(ok, (rule,)) == ()
    v = check_conformance(short, (rule,))
    assert len(v) == 1 and v[0].severity == SEVERITY_ERROR and v[0].section is short[0]


def test_length_max_violation():
    rule = Length(Selector.by_role("abstract"), min_len=0, max_len=5, severity=SEVERITY_WARNING)
    long = (sec("abstract", body="way too long"),)  # len 12 > 5
    ok = (sec("abstract", body="short"),)  # len 5
    assert check_conformance(ok, (rule,)) == ()
    v = check_conformance(long, (rule,))
    assert len(v) == 1 and v[0].severity == SEVERITY_WARNING


def test_length_is_per_matched_section():
    rule = Length(Selector.by_type("prose"), min_len=3, max_len=None, severity=SEVERITY_ERROR)
    sections = (sec("a", "prose", body="ok body"), sec("b", "prose", body="x"))
    v = check_conformance(sections, (rule,))
    assert [x.section for x in v] == [sections[1]]  # only the too-short one


def test_length_inverted_bounds_rejected():
    with pytest.raises(SectionSchemaError):
        Length(Selector.by_role("x"), min_len=10, max_len=5, severity=SEVERITY_ERROR)


# ---------------------------------------------------------------------------
# Selector — EITHER axis; neither re-owns the other.
# ---------------------------------------------------------------------------
def test_selector_by_type_and_by_role_both_enforce():
    by_type = Presence(Selector.by_type("figure"))  # require >=1 figure-typed section
    by_role = Presence(Selector.by_role("abstract"))  # require an abstract-role section
    sections = (sec("intro", "prose"), sec("fig-1", "figure"), sec("abstract", "prose"))
    assert check_conformance(sections, (by_type, by_role)) == ()
    no_fig = (sec("intro", "prose"), sec("abstract", "prose"))
    v = check_conformance(no_fig, (by_type,))
    assert len(v) == 1 and v[0].rule is by_type
    no_abs = (sec("intro", "prose"), sec("fig-1", "figure"))
    v2 = check_conformance(no_abs, (by_role,))
    assert len(v2) == 1 and v2[0].rule is by_role


def test_neither_axis_reowns_the_other():
    role_fig = Selector.by_role("figure")
    type_fig = Selector.by_type("figure")
    # role "diagram", type "figure": only the TYPE selector matches.
    typed = sec("diagram", "figure")
    assert type_fig.matches(typed) is True
    assert role_fig.matches(typed) is False
    # role "figure", type "prose": only the ROLE selector matches.
    named = sec("figure", "prose")
    assert role_fig.matches(named) is True
    assert type_fig.matches(named) is False


# ---------------------------------------------------------------------------
# Carrier discipline — an unknown `type` selector member is a TYPED omission.
# ---------------------------------------------------------------------------
def test_unknown_type_selector_is_typed_omission_not_a_crash():
    with pytest.raises(UnknownSectionTypeError) as exc:
        Selector.by_type("bogus")
    assert "unknown section type 'bogus'" in str(exc.value)
    assert isinstance(exc.value, SectionGrammarError)
    assert isinstance(exc.value, ValueError)
    # a valid carrier member constructs and matches fine.
    assert Selector.by_type("figure").matches(sec("x", "figure")) is True


def test_abstract_methods_results_are_roles_not_type_selectors():
    for name in ("abstract", "methods", "results"):
        assert name not in SECTION_TYPES
        # a ROLE selector on the same name is fine (roles are open).
        assert Selector.by_role(name).matches(sec(name)) is True
        # a TYPE selector is a typed one-file-add omission, never a silent accept / crash.
        with pytest.raises(UnknownSectionTypeError):
            Selector.by_type(name)


def test_bad_axis_and_empty_value_are_typed():
    with pytest.raises(SectionSchemaError):
        Selector("kind", "figure")  # unknown axis
    with pytest.raises(SectionSchemaError):
        Selector.by_role("")  # empty value


def test_bad_severity_is_typed():
    with pytest.raises(SectionSchemaError):
        Presence(Selector.by_role("x"), severity="fatal")
    with pytest.raises(SectionSchemaError):
        Length(Selector.by_role("x"), 0, 5, "loud")
    with pytest.raises(SectionSchemaError):
        Count(Selector.by_role("x"), Cardinality(0, 1), "boom")


# ---------------------------------------------------------------------------
# Graduated flexibility — a presence-only (or empty) schema is valid.
# ---------------------------------------------------------------------------
def test_presence_only_schema_is_valid():
    schema = (
        Presence(Selector.by_role("abstract")),
        Presence(Selector.by_role("references"), required=False),
    )
    ok = (sec("abstract"), sec("methods"))
    assert check_conformance(ok, schema) == ()  # no order/count rules -> flexible


def test_empty_schema_is_always_conformant():
    assert check_conformance((sec("anything"),), ()) == ()
    assert check_conformance((), ()) == ()


# ---------------------------------------------------------------------------
# Multi-rule composition + purity over parsed sections.
# ---------------------------------------------------------------------------
def test_violations_returned_in_schema_order():
    r1 = Presence(Selector.by_role("abstract"))  # missing -> error
    r2 = Presence(Selector.by_role("ack"), required=False)  # present -> error
    r3 = Order((Selector.by_role("intro"), Selector.by_role("body")))  # out of order -> warning
    sections = (sec("body"), sec("intro"), sec("ack"))
    v = check_conformance(sections, (r1, r2, r3))
    assert [x.rule for x in v] == [r1, r2, r3]
    assert [x.severity for x in v] == [SEVERITY_ERROR, SEVERITY_ERROR, SEVERITY_WARNING]


def test_check_conformance_over_parsed_markdown():
    md = "## Abstract {#abstract}\nWe present findings.\n\n## Method {type=figure}\nA diagram."
    sections = parse_sections(md)
    schema = (
        Presence(Selector.by_role("abstract")),
        Presence(Selector.by_type("figure")),
        Order((Selector.by_role("abstract"), Selector.by_type("figure"))),
    )
    assert check_conformance(sections, schema) == ()
    # a schema demanding a forbidden figure fails loudly on the same parsed body.
    forbid_fig = (Presence(Selector.by_type("figure"), required=False),)
    v = check_conformance(sections, forbid_fig)
    assert len(v) == 1 and v[0].severity == SEVERITY_ERROR and v[0].section is sections[1]


def test_check_conformance_is_pure_no_mutation():
    sections = (sec("abstract", body="x"), sec("methods", body="y"))
    before = tuple(sections)
    check_conformance(sections, (Presence(Selector.by_role("abstract")),))
    assert sections == before  # inputs untouched (pure function)
