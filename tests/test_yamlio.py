"""Step-8 tests: pinned YAML 1.2 typed safe-load + the bounded frontmatter splitter.

Fixture provenance: the Norway-problem regression reproduces the step-2 G4 gate transcript
(probe 2.2, k01-k28 + the key-coercion row) verbatim; the splitter cases are the gate's
S-E1..S-E12 edge-case table, one test per row, plus the four splitter invariants.
"""

import datetime
import math

import pytest

from pipeline.yamlio import (
    FrontmatterDirectiveError,
    FrontmatterNotAMappingError,
    UnterminatedFrontmatterError,
    YAMLLoadError,
    load_frontmatter,
    load_yaml,
    split_frontmatter,
)

# ---------------------------------------------------------------------------
# The Norway-problem regression (gate G4, step-2 probe 2.2 — verbatim fixture)
# ---------------------------------------------------------------------------

_G4_DOC = """\
k01: no
k02: No
k03: NO
k04: yes
k05: Yes
k06: on
k07: On
k08: off
k09: OFF
k10: y
k11: n
k12: true
k13: True
k14: TRUE
k15: false
k16: 1_000
k17: 0o777
k18: 0777
k19: 0x1A
k20: 1:20
k21: 1.5
k22: .inf
k23: .NaN
k24: ~
k25: null
k26: 2026-07-12
k27: +12
k28: 001
no: key-coercion-check
"""


@pytest.fixture(scope="module")
def g4_loaded() -> dict:
    return load_yaml(_G4_DOC)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("k01", "no"),  # the Norway problem: a 1.1 loader gives False
        ("k02", "No"),
        ("k03", "NO"),
        ("k04", "yes"),
        ("k05", "Yes"),
        ("k06", "on"),  # the GitHub-Actions `on:` class
        ("k07", "On"),
        ("k08", "off"),
        ("k09", "OFF"),
        ("k10", "y"),
        ("k11", "n"),
    ],
)
def test_norway_problem_tokens_stay_strings(g4_loaded: dict, key: str, expected: str) -> None:
    value = g4_loaded[key]
    assert value == expected
    assert type(value) is str


@pytest.mark.parametrize(
    ("key", "expected"),
    [("k12", True), ("k13", True), ("k14", True), ("k15", False)],
)
def test_only_true_false_are_booleans(g4_loaded: dict, key: str, expected: bool) -> None:
    value = g4_loaded[key]
    assert value is expected


def test_numeric_semantics_are_yaml_12_core(g4_loaded: dict) -> None:
    assert g4_loaded["k16"] == 1000  # D1 deviation, documented; type-gated in attrtypes
    assert type(g4_loaded["k16"]) is int
    assert g4_loaded["k17"] == 511  # 0o777 — correct 1.2 octal
    assert g4_loaded["k18"] == 777  # 0777 — a 1.1 loader gives octal 511
    assert g4_loaded["k19"] == 26  # 0x1A
    assert g4_loaded["k20"] == "1:20"  # sexagesimal DEAD (PyYAML gives 80)
    assert type(g4_loaded["k20"]) is str
    assert g4_loaded["k21"] == 1.5
    assert g4_loaded["k22"] == math.inf
    assert math.isnan(g4_loaded["k23"])
    assert g4_loaded["k24"] is None
    assert g4_loaded["k25"] is None
    assert g4_loaded["k27"] == 12
    assert g4_loaded["k28"] == 1


def test_bare_date_loads_as_date_object(g4_loaded: dict) -> None:
    # D2 deviation (timestamp resolver active) — type-gated to date-window in attrtypes.
    assert g4_loaded["k26"] == datetime.date(2026, 7, 12)
    assert type(g4_loaded["k26"]) is datetime.date


def test_key_no_stays_a_string_key(g4_loaded: dict) -> None:
    # PyYAML 1.1 corrupts the KEY too (`no:` -> False); the pinned loader must not.
    assert "no" in g4_loaded
    assert False not in g4_loaded
    assert g4_loaded["no"] == "key-coercion-check"


def test_crlf_document_loads_with_norway_guard_intact() -> None:
    # Step-2 probe 2.4: ruamel accepts \r\n natively; 'no' still a string.
    assert load_yaml("a: no\r\nb: 2\r\n") == {"a": "no", "b": 2}


def test_empty_document_loads_as_none() -> None:
    # Step-2 probe 2.4: empty input loads as None, not {} — load_frontmatter normalizes.
    assert load_yaml("") is None


# ---------------------------------------------------------------------------
# The splitter: S-E1..S-E12 (step-2 §4 edge-case table, one test per row)
# ---------------------------------------------------------------------------


def test_s_e1_bom_before_fence_is_consumed() -> None:
    fm, body = split_frontmatter("\ufeff---\na: 1\n---\nbody\n")
    assert fm == "a: 1\n"
    assert body == "body\n"


def test_s_e1_bom_without_fence_returned_verbatim_including_bom() -> None:
    text = "\ufeffno fence here\n"
    fm, body = split_frontmatter(text)
    assert fm is None
    assert body == text  # BOM consumed only as part of fence recognition


def test_s_e2_crlf_fences_and_body_byte_fidelity() -> None:
    text = "---\r\na: no\r\nb: 2\r\n---\r\nbody line\r\n"
    fm, body = split_frontmatter(text)
    assert fm == "a: no\r\nb: 2\r\n"  # CRLF preserved verbatim
    assert body == "body line\r\n"
    data, _ = load_frontmatter(text)
    assert data == {"a": "no", "b": 2}  # Norway guard intact through CRLF


def test_s_e3_thematic_break_in_body_is_body() -> None:
    text = "---\na: 1\n---\nintro\n---\noutro\n"
    fm, body = split_frontmatter(text)
    assert fm == "a: 1\n"
    assert body == "intro\n---\noutro\n"  # first close fence wins; never re-split


def test_s_e4_missing_frontmatter_returns_text_untouched() -> None:
    text = "# just a document\n---\nnot frontmatter\n"
    fm, body = split_frontmatter(text)
    assert fm is None
    assert body == text
    data, body2 = load_frontmatter(text)
    assert data is None  # caller policy: registry loader (step 11) rejects; others may accept
    assert body2 == text


def test_s_e5_empty_frontmatter_is_empty_string_then_empty_mapping() -> None:
    text = "---\n---\nbody\n"
    fm, body = split_frontmatter(text)
    assert fm == ""  # distinct from S-E4's None
    assert body == "body\n"
    data, _ = load_frontmatter(text)
    assert data == {}  # loader normalizes None -> {}


@pytest.mark.parametrize(
    "text",
    [
        "\n---\na: 1\n---\nbody\n",  # blank line before the fence
        " ---\na: 1\n---\nbody\n",  # indented fence
    ],
)
def test_s_e6_leading_whitespace_means_no_fence(text: str) -> None:
    fm, body = split_frontmatter(text)
    assert fm is None
    assert body == text


@pytest.mark.parametrize(
    "text",
    [
        "---\na: 1\n",  # open fence, no close, trailing newline
        "---\na: 1",  # open fence, no close, EOF mid-line
        "---",  # open fence alone at EOF
        "---\n",  # open fence alone, newline
    ],
)
def test_s_e7_unterminated_frontmatter_is_a_typed_error(text: str) -> None:
    with pytest.raises(UnterminatedFrontmatterError) as excinfo:
        split_frontmatter(text)
    assert excinfo.value.code == "unterminated-frontmatter"


def test_s_e8_percent_directive_line_is_refused() -> None:
    # Hazard D3: an in-document `%YAML 1.1` directive re-enables the Norway problem.
    text = "---\n%YAML 1.1\na: no\n---\nbody\n"
    with pytest.raises(FrontmatterDirectiveError) as excinfo:
        load_frontmatter(text)
    assert excinfo.value.code == "frontmatter-directive-refused"
    # The SPLIT itself is pure text and still succeeds — the refusal is load_frontmatter's.
    fm, _ = split_frontmatter(text)
    assert fm == "%YAML 1.1\na: no\n"


def test_s_e8_any_percent_line_is_refused_not_just_yaml_directives() -> None:
    with pytest.raises(FrontmatterDirectiveError):
        load_frontmatter("---\n%TAG ! tag:example.com,2000:\na: 1\n---\n")


@pytest.mark.parametrize(
    "text",
    [
        "---\njust-a-scalar\n---\nbody\n",  # scalar document (loads fine — check is OURS)
        "---\n- a\n- b\n---\nbody\n",  # sequence document
    ],
)
def test_s_e9_non_mapping_frontmatter_is_a_typed_error(text: str) -> None:
    with pytest.raises(FrontmatterNotAMappingError) as excinfo:
        load_frontmatter(text)
    assert excinfo.value.code == "frontmatter-not-a-mapping"


def test_s_e10_block_scalar_bare_dash_line_closes_the_fence_early() -> None:
    # Documented limitation (step-2 §4): a bare `---` line inside a block scalar closes the
    # fence early — inherent to line-based splitting. The truncation is deterministic and
    # fully visible (the leaked lines land verbatim in the body, and the truncated
    # frontmatter is missing keys), so downstream schema validation (step 11) fails LOUDLY;
    # nothing is silent.
    text = "---\nnotes: |\n  first\n---\n  second\nid: x\n---\nbody\n"
    fm, body = split_frontmatter(text)
    assert fm == "notes: |\n  first\n"  # truncated at the early close fence
    assert body == "  second\nid: x\n---\nbody\n"  # the remainder is body, verbatim
    data, _ = load_frontmatter(text)
    assert data == {"notes": "first\n"}  # `id` is GONE from the mapping — a loud
    # missing-required-key failure at the step-11 entry loader, never a silent reinterpret.


def test_s_e11_close_fence_at_eof_without_trailing_newline() -> None:
    fm, body = split_frontmatter("---\na: 1\n---")
    assert fm == "a: 1\n"
    assert body == ""


def test_s_e12_fence_with_trailing_spaces_and_tabs_is_recognized() -> None:
    fm, body = split_frontmatter("--- \na: 1\n---\t\nbody\n")
    assert fm == "a: 1\n"
    assert body == "body\n"


def test_dashes_with_extra_characters_are_not_fences() -> None:
    for text in ("----\na: 1\n---\n", "--- x\na: 1\n---\n"):
        fm, body = split_frontmatter(text)
        assert fm is None
        assert body == text


# ---------------------------------------------------------------------------
# Splitter invariants (step-2 §4)
# ---------------------------------------------------------------------------


def test_invariant_split_is_deterministic() -> None:
    text = "---\na: 1\n---\nbody with --- inside\n"
    assert split_frontmatter(text) == split_frontmatter(text)


def test_invariant_body_is_byte_identical_to_post_fence_remainder() -> None:
    body_payload = "line1\r\nline2\n\ttabbed\n  spaced \n\ufeffbom-in-body\n---\n"
    text = "---\na: 1\n---\n" + body_payload
    _, body = split_frontmatter(text)
    assert body == body_payload


def test_invariant_split_is_total_over_str() -> None:
    # Every input either splits or raises the one typed error — no undefined behavior.
    for text in ("", "\n", "x", "---\n---\n", "\ufeff", "---"):
        try:
            fm, body = split_frontmatter(text)
        except UnterminatedFrontmatterError:
            continue
        assert fm is None or isinstance(fm, str)
        assert isinstance(body, str)


def test_invariant_loader_yaml_syntax_errors_propagate_loudly() -> None:
    with pytest.raises(YAMLLoadError):
        load_frontmatter("---\na: [unclosed\n---\nbody\n")


def test_empty_string_input() -> None:
    assert split_frontmatter("") == (None, "")
    assert load_frontmatter("") == (None, "")
