"""DR-4 COMMIT 1 tests: `pipeline/sections.py` — the F1 sentinel section grammar.

Every recognition-table expectation below was verified DIRECTLY against pandoc 3.10's default
`markdown` reader (`printf ... | pandoc -f markdown -t native`); the comments name the probe. The
suite pins:

- **The full recognition table** — ATTR vs LITERAL, including `## H {type=figure}` (attr),
  `## H {.a b}` / `## Q3 revenue {2024}` / `## H {#i} trailing` (literal), and every degenerate
  brace shape (`{#}`, `{# bad}`, `{=v}`, `{.}`) falling back to LITERAL with NO syntax error.
- **FORGE tests** — a `## …` / `{type=…}` inside BOTH a ``` fence and a ~~~ fence is inert.
- **The nit trio** — indented `#`-lines (pandoc 3-space→Para / 4-space→CodeBlock), the
  `## [x]{#id}` span-grammar overlap (safe: no forged role/type), and post-N NFC ids.
- **Duplicate slugs COUNT** — the parser never silently de-duplicates roles.
- **The N-invariance golden-digest corpus** — `outline_digest(md)` is byte-identical to a
  checked-in golden under trailing-WS / blank-count / CRLF / NFD perturbation (N is untouched;
  `parse_sections` is a pure read-only consumer that cannot churn the outline digest).
- **The one loud SEMANTIC refusal** — an unknown `type=` value raises exactly one typed error,
  never a crash; nothing else raises.
"""

from __future__ import annotations

import unicodedata

import pytest

from pipeline.outline import normalize_outline, outline_digest
from pipeline.sections import (
    DEFAULT_SECTION_TYPE,
    SECTION_TYPES,
    Section,
    SectionGrammarError,
    UnknownSectionTypeError,
    parse_sections,
)


def _one(md: str) -> Section:
    sections = parse_sections(md)
    assert len(sections) == 1, f"expected exactly one section, got {sections!r}"
    return sections[0]


# ---------------------------------------------------------------------------
# The recognition table: (markdown, level, role, type, heading). Each row is a
# pandoc-3.10 probe result — F1 must reproduce it EXACTLY.
# ---------------------------------------------------------------------------
RECOGNITION_TABLE = [
    # --- ATTR: a valid line-final attribute block ---
    ("## H {type=figure}", 2, "h", "figure", "H"),
    ("## H {#i}", 2, "i", "prose", "H"),
    ("## H {.a}", 2, "h", "prose", "H"),
    ('## H {type="figure"}', 2, "h", "figure", "H"),
    ("## H {#i .c type=figure}", 2, "i", "figure", "H"),
    ("## H ## {type=figure}", 2, "h", "figure", "H"),  # ATX close before the attr block
    ("## H {#a #b}", 2, "b", "prose", "H"),  # pandoc: the LAST id wins
    ("## {type=figure}", 2, "section", "figure", ""),  # attr-only heading, empty text -> "section"
    ("## H {type=table}", 2, "h", "table", "H"),
    ("## H {type=callout}", 2, "h", "callout", "H"),
    ("## H {type=prose}", 2, "h", "prose", "H"),
    # --- LITERAL: a single bare word (or non-line-final block) voids the whole block ---
    ("## H {.a b}", 2, "h-.a-b", "prose", "H {.a b}"),
    ("## Q3 revenue {2024}", 2, "q3-revenue-2024", "prose", "Q3 revenue {2024}"),
    ("## H {#i} trailing", 2, "h-i-trailing", "prose", "H {#i} trailing"),
    ("## H {type=figure} ##", 2, "h-typefigure", "prose", "H {type=figure}"),  # attr not line-final
    # --- LITERAL: every degenerate brace shape — NO syntax error, id auto-slugs ---
    ("## H {#}", 2, "h", "prose", "H {#}"),
    ("## H {# bad}", 2, "h-bad", "prose", "H {# bad}"),
    ("## H {=v}", 2, "h-v", "prose", "H {=v}"),
    ("## H {.}", 2, "h-.", "prose", "H {.}"),
    # --- level + empty-heading edges ---
    ("####### g", 7, "g", "prose", "g"),  # pandoc does not cap the level
    ("## ", 2, "section", "prose", ""),  # empty heading -> the "section" fallback slug
    ("## 3 things", 2, "things", "prose", "3 things"),  # drop up to the first letter
    ("## 123", 2, "section", "prose", "123"),  # no letter -> "section"
    # --- COLON in the auto-slug: pandoc's default auto-identifier DROPS `:` (F-1) ---
    # `printf '## Figure 3: Throughput\n' | pandoc ...` -> id "figure-3-throughput".
    (
        "## Figure 3: Throughput {type=figure}",
        2,
        "figure-3-throughput",
        "figure",
        "Figure 3: Throughput",
    ),
    # `printf '## Section: Overview\n' | pandoc ...` -> id "section-overview".
    ("## Section: Overview", 2, "section-overview", "prose", "Section: Overview"),
    # `printf '## a:b\n' | pandoc ...` -> id "ab" (the bare colon collapses, NOT "a:b").
    ("## a:b", 2, "ab", "prose", "a:b"),
]


@pytest.mark.parametrize("md, level, role, type_, heading", RECOGNITION_TABLE)
def test_recognition_table_matches_pandoc(md, level, role, type_, heading):
    sec = _one(md)
    assert (sec.level, sec.role, sec.type, sec.heading) == (level, role, type_, heading)


def test_no_brace_shape_raises():
    """F1 raises NO syntax error on any brace shape — every one is a LITERAL heading."""
    for md in ("## H {#}", "## H {# bad}", "## H {=v}", "## H {.}", "## H {}", "## H {  }"):
        sec = _one(md)
        assert sec.type == DEFAULT_SECTION_TYPE  # never typed, never a raise


# ---------------------------------------------------------------------------
# FORGE tests — a heading sentinel is recognized ONLY outside fenced code.
# ---------------------------------------------------------------------------
def test_backtick_fence_makes_heading_inert():
    md = "## Real {#real}\nbody\n\n```\n## Forged {type=figure}\n```"
    roles = [s.role for s in parse_sections(md)]
    assert roles == ["real"]  # the fenced `## Forged` is inert


def test_tilde_fence_makes_heading_inert():
    md = "## Real {#real}\nbody\n\n~~~\n## Forged {type=figure}\n~~~"
    roles = [s.role for s in parse_sections(md)]
    assert roles == ["real"]  # backtick-only tracking would MISS this ~~~ boundary


def test_fence_length_and_char_matching():
    # A longer close still closes; a mismatched fence char inside does NOT close.
    assert [s.role for s in parse_sections("```\n## A\n````\n## B {#b}")] == ["b"]
    assert parse_sections("```\n~~~\n## Inside\n~~~\n```") == ()  # ~~~ never closes a ``` fence


def test_backtick_in_backtick_info_string_is_not_a_fence():
    # A backtick fence whose info string contains a backtick is NOT a valid opening fence,
    # so the `## H` below IS a real heading (matches pandoc's non-fence fallback).
    md = "``` foo`bar\n## H {#h}"
    assert [s.role for s in parse_sections(md)] == ["h"]


# ---------------------------------------------------------------------------
# The nit trio: indentation (nit-1b), the span overlap (nit-9), NFC ids (nit-1a).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("md", [" ## H", "  ## H", "   ## H", "    ## H", " ## H {type=figure}"])
def test_indented_hash_line_is_not_a_heading(md):
    # pandoc: 1-3 leading spaces -> Para, 4+ -> CodeBlock. Either way, NOT a section heading.
    assert parse_sections(md) == ()


def test_zero_indent_is_a_heading():
    assert _one("## H").role == "h"


def test_span_overlap_does_not_forge_a_role(md_x="## [x]{#id}"):
    # pandoc binds `{#id}` to the inner span `[x]`, auto-slugging the heading. F1 must NOT read
    # it as a heading attribute: the role must NOT be "id" and the type must NOT be forged.
    sec = _one(md_x)
    assert sec.role != "id"
    assert sec.type == DEFAULT_SECTION_TYPE


def test_post_n_ids_are_nfc():
    # An NFD-spelled heading, once normalized by N, yields an NFC role slug (the slug transform
    # never decomposes). nit-1a.
    nfd = unicodedata.normalize("NFD", "## Café {#café}")
    sec = _one(normalize_outline(nfd))
    assert unicodedata.is_normalized("NFC", sec.role)
    assert sec.role == "café"


# ---------------------------------------------------------------------------
# Duplicate slugs COUNT — never silently unique.
# ---------------------------------------------------------------------------
def test_duplicate_slugs_are_counted_not_deduplicated():
    sections = parse_sections("## Overview\na\n\n## Overview\nb\n\n## Overview {#overview}\nc")
    assert [s.role for s in sections] == ["overview", "overview", "overview"]
    assert len(sections) == 3  # three distinct sections, one repeated role


# ---------------------------------------------------------------------------
# Body + span slicing.
# ---------------------------------------------------------------------------
def test_body_and_span_slice_the_normalized_lines():
    md = "## A {#a}\nbody a\n\n## B {#b}\nbody b1\nbody b2"
    lines = md.split("\n")
    a, b = parse_sections(md)
    assert a.span == (0, 3) and a.body == "body a"
    assert b.span == (3, 6) and b.body == "body b1\nbody b2"
    assert lines[a.span[0] : a.span[1]][0] == "## A {#a}"  # span[0] is the heading line


def test_content_before_first_heading_is_not_a_section():
    assert [s.role for s in parse_sections("preamble text\n\n## Body {#body}\nx")] == ["body"]


def test_no_headings_yields_empty():
    assert parse_sections("just a flat paragraph\nwith two lines") == ()


# ---------------------------------------------------------------------------
# The ONE loud SEMANTIC refusal: an unknown `type=` value.
# ---------------------------------------------------------------------------
def test_unknown_type_raises_one_typed_refusal():
    with pytest.raises(UnknownSectionTypeError) as exc:
        parse_sections("## H {type=bogus}")
    assert "unknown section type 'bogus'" in str(exc.value)
    assert isinstance(exc.value, SectionGrammarError)
    assert isinstance(exc.value, ValueError)


def test_roles_are_never_types_abstract_methods_results():
    # `abstract`/`methods`/`results` are ROLES (via `{#id}`), never carrier types.
    for role in ("abstract", "methods", "results"):
        assert role not in SECTION_TYPES
        sec = _one(f"## Heading {{#{role}}}")
        assert sec.role == role and sec.type == DEFAULT_SECTION_TYPE
    # As a `type=` they are SEMANTIC refusals, not silent acceptances.
    for kind in ("abstract", "methods", "results"):
        with pytest.raises(UnknownSectionTypeError):
            parse_sections(f"## Heading {{type={kind}}}")


def test_carrier_is_the_open_one_file_add_surface():
    assert SECTION_TYPES == frozenset({"prose", "figure", "table", "callout", "diagram"})
    assert DEFAULT_SECTION_TYPE == "prose" and DEFAULT_SECTION_TYPE in SECTION_TYPES


# ---------------------------------------------------------------------------
# Documented, SAFE divergences from pandoc (fail-closed; never forge a role).
# ---------------------------------------------------------------------------
def test_no_space_before_brace_is_a_safe_literal():
    # pandoc treats `## H{type=figure}` (no space) as an ATTR heading; F1 requires whitespace
    # before the block, so it fails CLOSED to a LITERAL (a false-negative that can never forge a
    # type/role). Pinned so the divergence is intentional and visible.
    sec = _one("## H{type=figure}")
    assert sec.type == DEFAULT_SECTION_TYPE and sec.role != "h"


# ---------------------------------------------------------------------------
# N-INVARIANCE golden-digest corpus. parse_sections is a pure read-only consumer of N's output;
# it does NOT (and cannot) churn `outline_digest`. Each golden is the digest of the canonical
# (already-normalized) member; every perturbation N erases must reproduce it byte-for-byte.
# ---------------------------------------------------------------------------
_N_GOLDEN_CORPUS = {
    "typed": (
        "## Abstract {#abstract}\nWe present.\n\n## Method {type=figure}\nA diagram.",
        "4a64b91f1d604d3651112e0988237d5c15f3757e964e995f1d842da459538a39",
    ),
    "fenced": (
        "## Intro\nText.\n\n```\n## NotAHeading {type=figure}\n```\n\n## Close\nDone.",
        "a85472b9a398061b6bf28724853a208e722f213d0b73fa83d725627f98e41dd4",
    ),
    "unicode": (
        "## Résumé {#resume}\nCafé details.\n\n## Naïve table {type=table}\nRows.",
        "e9730cadf16a9ba0d6835804fe7cbcc6ed24cf6076b764b4432cf409ad8113ae",
    ),
    "literal_braces": (
        "## Q3 revenue {2024}\nNumbers.\n\n## H {.a b}\nMore.",
        "29c205b24b4c600d7b36bb6c60112c48dae1519330c8a60e93199b0dba3d4b39",
    ),
}


@pytest.mark.parametrize("name", sorted(_N_GOLDEN_CORPUS))
def test_n_invariance_golden_digest(name):
    base, golden = _N_GOLDEN_CORPUS[name]
    # The canonical member is already at N's fixed point (idempotent authoring).
    assert normalize_outline(base) == base
    assert outline_digest(base) == golden
    perturbations = {
        "trailing_ws": "\n".join(line + "   \t" for line in base.split("\n")),
        "blank_runs": base.replace("\n\n", "\n\n\n\n"),
        "crlf": base.replace("\n", "\r\n"),
        "nfd": unicodedata.normalize("NFD", base),
    }
    # NON-VACUITY (reviewer F-3): the NFD perturbation only exercises N's NFC fold when it
    # actually CHANGES bytes. The `unicode` member carries precomposed accents (é/ï/…), so its
    # NFD form MUST differ from the (NFC) base -- otherwise the nfd assertion below would just
    # re-hash identical ASCII bytes and never test the NFC step. Asserting the digest is then
    # byte-identical NFD-vs-NFC on a genuinely-changed member is the real N-invariance check.
    if name == "unicode":
        assert perturbations["nfd"] != base
        assert not unicodedata.is_normalized("NFC", perturbations["nfd"])
    for label, perturbed in perturbations.items():
        assert outline_digest(perturbed) == golden, f"{name}/{label} churned the digest"


def test_parse_sections_does_not_churn_the_outline_digest():
    # Calling parse_sections (a pure consumer) never mutates N's surface: the digest is stable.
    for base, golden in _N_GOLDEN_CORPUS.values():
        before = outline_digest(base)
        parse_sections(base)
        assert outline_digest(base) == before == golden
