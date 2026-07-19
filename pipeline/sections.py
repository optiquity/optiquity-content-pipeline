"""F1 sentinel section grammar — a pure, pandoc-3.10-faithful section parser (DR-4 / C1).

Design authority: `docs/design.md` §7.2 (canonical preimages — identical logical inputs
yield identical bytes) and the FINAL RECONCILED DR-4 build plan, COMMIT C1 (the F1 sentinel
grammar). This module is the FOUNDATION half of DR-4 typed-section conformance: it turns the
NORMALIZED outline (the output of `pipeline.outline.normalize_outline`, "N") into a tuple of
typed `Section` records. C2 layers the conformance checker on the `SECTION_TYPES` carrier
defined here.

WHY THIS IS PURE + IMPORT-LIGHT (the identity discipline)
--------------------------------------------------------
`parse_sections` is a **pure read-only consumer of the output of N**. It performs NO I/O, mints
NO identity, calls NO LLM, and imports NOTHING from `pipeline.ids`. The `role` key it computes is
a BARE slug (pandoc's auto-identifier), mirroring `outline.py`'s "bare content hash, NOT an
identity" discipline (`outline.py` module docstring): the slug carries no prefix and is never
`parse_id`-parsed. This module does NOT touch `normalize_outline`/`outline_digest` in any way, so
it cannot churn the outline digest (the #3a N-INVARIANCE RESERVATION in `outline.py` is honored:
boundaries derive only from N-preserved structure — full-line content + leading indentation —
never from trailing whitespace, blank-run counts, or nesting depth).

EXPECTED INPUT: the output of N. `parse_sections` assumes its argument is already normalized
(NFC, LF-only line endings, no trailing per-line whitespace, blank runs collapsed). It does not
re-normalize (that would duplicate N); callers pass `normalize_outline(md)`.

THE SENTINEL GRAMMAR (pandoc 3.10, default `markdown` reader — verified at source)
---------------------------------------------------------------------------------
A section boundary is an ATX heading line, recognized EXACTLY as pandoc's default markdown does:

  * ZERO leading spaces. A `#`-line indented 1-3 spaces is a paragraph, 4+ an indented code
    block — neither is a heading (verified: `   ## H` -> Para, `    ## H` -> CodeBlock).
  * `#{1,}` then a space/tab (or end-of-line): `##H` (no space) is NOT a heading. `level` is the
    hash count (pandoc does not cap it; `####### g` -> level 7).
  * Recognized ONLY OUTSIDE fenced code. BOTH ``` and ~~~ fences are tracked (fence length +
    info-string rules): a `## X` inside either fence is inert exactly as pandoc treats it.
  * A trailing run of `#` (the ATX close, e.g. `## H ##`) is stripped from the heading text.

V1 RECOGNITION LIMITS (SAFE, fail-closed): ONLY ATX (`#`) headings are recognized as section
sentinels. A SETEXT heading (a title underlined by a `===`/`---` run) and a BLOCKQUOTED heading
(`> ## X`) are treated as ordinary BODY — NOT typed or keyed in v1. This is fail-CLOSED: an
unrecognized heading is never forged into a role/type; at worst its section goes un-enforced (an
under-counted boundary), never a false or mistyped section. Broadening to setext would invite the
`===`/`---` vs. thematic-break / YAML-fence ambiguity the plan flags as a parse-divergence risk, so
it is deferred to a later commit's known-issues entry.

Trailing `{...}` ATTRIBUTE recognition is pandoc's REAL rule, EXACTLY: a trailing `{...}` is an
attribute block ONLY IF it is line-final AND its whole interior parses as whitespace-separated
valid attribute words (`#id` | `.class` | `key=value`, value may be quoted). A SINGLE bare word
voids the entire block, making the heading LITERAL text (its id auto-slugs from the literal
text). Verified: `## H {type=figure}` -> ATTR, `## H {.a b}` -> LITERAL, `## Q3 revenue {2024}`
-> LITERAL (auto-slug `q3-revenue-2024`), `## H {#i} trailing` -> LITERAL. The block must be
preceded by whitespace (or be the whole content): `## [x]{#id}` binds `{#id}` to the inner span
in pandoc (heading auto-slugs), so F1 does NOT read it as a heading attribute (the nit-9 span
overlap). F1 raises NO syntax error on any brace shape — `{#}`, `{# bad}`, `{=v}`, `{.}` all fall
back to LITERAL.

THE ONE LOUD REFUSAL is SEMANTIC, never syntactic: a recognized `type=<value>` whose value is not
in the open `SECTION_TYPES` carrier raises `UnknownSectionTypeError` ("unknown section type
'<value>'"). `abstract`/`methods`/`results` are ROLES (via `{#id}`), never types; they never
appear in the carrier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "DEFAULT_SECTION_TYPE",
    "SECTION_TYPES",
    "Section",
    "SectionGrammarError",
    "UnknownSectionTypeError",
    "parse_sections",
]

# The OPEN, one-file-add carrier of genre-NEUTRAL STRUCTURAL section KINDS (v1). Adding a kind is
# a ONE-LINE change here; C2 builds the conformance layer on this set. These are STRUCTURAL kinds,
# NOT roles: `abstract`/`methods`/`results` are ROLES (carried by `{#id}`) and never appear here.
SECTION_TYPES = frozenset({"prose", "figure", "table", "callout"})

# The default `type` when a heading declares no `type=` kv.
DEFAULT_SECTION_TYPE = "prose"

# The identifier / class / key character set pandoc accepts (letters, digits, and `-_:.`),
# verified: `{#i.j}` -> id "i.j", `{.a.b}` -> class "a.b", `{my_key-2=v}` -> key "my_key-2".
# This set (WITH `:`) is for EXPLICIT-id parsing (`_is_attr_char`); pandoc DOES allow `:` in a
# declared `{#i:j}` id.
_ATTR_WORD_CHARS = "-_:."

# The auto-identifier (auto-slug) punctuation set — pandoc's DEFAULT auto-identifier keeps only
# `-_.` and DROPS the colon: `## a:b` -> id "ab", `## Figure 3: Throughput` ->
# "figure-3-throughput". Deliberately DISTINCT from `_ATTR_WORD_CHARS` (which keeps `:` for
# explicit ids); used by the `_autoslug` path ONLY.
_AUTOSLUG_PUNCT = "-_."

# An ATX heading: zero leading spaces, one-or-more `#`, then a space/tab or end-of-line.
_ATX_RE = re.compile(r"(#+)(?=[ \t]|$)")

# A fence-OPEN line: 0-3 leading spaces (4+ is indented code, not a fence), then a run of 3+
# identical fence chars, then an info string. `.match` anchors at the string start.
_FENCE_OPEN_RE = re.compile(r"( {0,3})(`{3,}|~{3,})(.*)$")

# A fence-CLOSE candidate: 0-3 leading spaces, a homogeneous run of fence chars, only whitespace
# after. The caller checks the char matches and the run length is >= the opening length.
_FENCE_CLOSE_RE = re.compile(r" {0,3}(`+|~+)[ \t]*$")


class SectionGrammarError(ValueError):
    """Base F1 section-grammar refusal — loud, typed, never repaired."""

    code = "section-grammar-invalid"


class UnknownSectionTypeError(SectionGrammarError):
    """A recognized `type=<value>` whose value is not in the `SECTION_TYPES` carrier."""

    code = "unknown-section-type"


@dataclass(frozen=True, slots=True)
class Section:
    """One heading-delimited section of a normalized outline.

    * `level`   — the ATX heading level (the `#` count; pandoc does not cap it).
    * `role`    — the BARE section key: the explicit `{#id}` if present, else the pandoc
                  auto-slug of the heading text. NOT an identity; never `parse_id`-parsed.
    * `type`    — the structural KIND from the `type=` kv, or `DEFAULT_SECTION_TYPE` when absent.
    * `heading` — the displayed heading text (attribute block removed, ATX close stripped).
    * `body`    — the section content between this heading and the next (leading/trailing blank
                  lines stripped), as a verbatim slice of the normalized input.
    * `span`    — the half-open `(start, end)` line-index range over `normalized_md.split("\\n")`;
                  `lines[start:end]` is the whole section including its heading line.
    """

    level: int
    role: str
    type: str
    heading: str
    body: str
    span: tuple[int, int]


def parse_sections(normalized_md: str) -> tuple[Section, ...]:
    """Parse the NORMALIZED outline into its heading-delimited sections (pure, total-ish).

    Expects the output of `pipeline.outline.normalize_outline` (N). Content before the first
    heading is not a section (there is no heading to key it). Duplicate roles are RETAINED (the
    result COUNTS every section; it never silently de-duplicates). Raises
    `UnknownSectionTypeError` — and only that — when a heading declares a `type=` value outside
    the `SECTION_TYPES` carrier; every malformed brace shape is a LITERAL heading, never a raise.
    """
    lines = normalized_md.split("\n")
    heads = _find_heading_lines(lines)

    sections: list[Section] = []
    for i, (idx, level, content) in enumerate(heads):
        end = heads[i + 1][0] if i + 1 < len(heads) else len(lines)
        role, type_, heading_text = _parse_heading(content)
        body_lines = lines[idx + 1 : end]
        while body_lines and body_lines[0] == "":
            body_lines.pop(0)
        while body_lines and body_lines[-1] == "":
            body_lines.pop()
        sections.append(
            Section(
                level=level,
                role=role,
                type=type_,
                heading=heading_text,
                body="\n".join(body_lines),
                span=(idx, end),
            )
        )
    return tuple(sections)


def _find_heading_lines(lines: list[str]) -> list[tuple[int, int, str]]:
    """Return `(line_index, level, content_after_hashes)` for every ATX heading OUTSIDE a fence.

    Tracks BOTH ``` and ~~~ fenced code so a `## X` inside either fence is inert. An unterminated
    fence swallows the rest of the input (matching pandoc's "no heading inside an open fence").
    """
    heads: list[tuple[int, int, str]] = []
    in_fence = False
    fence_char = ""
    fence_len = 0

    for idx, line in enumerate(lines):
        if in_fence:
            close = _FENCE_CLOSE_RE.match(line)
            if close:
                run = close.group(1)
                if run[0] == fence_char and len(run) >= fence_len:
                    in_fence = False
            continue

        fence = _FENCE_OPEN_RE.match(line)
        if fence:
            run = fence.group(2)
            info = fence.group(3)
            # A backtick fence with a backtick in its info string is NOT a valid opening fence.
            if not (run[0] == "`" and "`" in info):
                in_fence = True
                fence_char = run[0]
                fence_len = len(run)
                continue

        atx = _ATX_RE.match(line)
        if atx:
            level = len(atx.group(1))
            content = line[level:].lstrip(" \t")
            heads.append((idx, level, content))

    return heads


def _parse_heading(content: str) -> tuple[str, str, str]:
    """Resolve `(role, type, heading_text)` for a heading's post-`#` content.

    Extracts a line-final attribute block (pandoc's real rule), strips the ATX close run, computes
    the role (explicit `{#id}` else auto-slug) and the type (`type=` kv else the default). Raises
    `UnknownSectionTypeError` on a `type=` value outside the carrier.
    """
    attr_words = _extract_attr_block(content)
    if attr_words is None:
        heading_text = _strip_atx_close(content)
        return _autoslug(heading_text), DEFAULT_SECTION_TYPE, heading_text

    words, heading_src = attr_words
    heading_text = _strip_atx_close(heading_src)

    explicit_id: str | None = None
    type_value: str | None = None
    for word in words:
        if word[0] == "id":
            explicit_id = word[1]  # pandoc: the LAST id wins.
        elif word[0] == "kv" and word[1] == "type":
            if word[2] not in SECTION_TYPES:
                raise UnknownSectionTypeError(
                    f"unknown section type '{word[2]}' (section heading '{heading_text}'): "
                    f"add it to the SECTION_TYPES carrier (one-file change) or declare one of "
                    f"{sorted(SECTION_TYPES)}"
                )
            type_value = word[2]  # pandoc keeps repeats; the LAST valid value is the type.

    role = explicit_id if explicit_id is not None else _autoslug(heading_text)
    return role, (type_value if type_value is not None else DEFAULT_SECTION_TYPE), heading_text


def _extract_attr_block(content: str) -> tuple[list[tuple], str] | None:
    """If `content` ends with a valid line-final attribute block, return `(words, text_before)`.

    Otherwise `None` (the heading is LITERAL). The block must be preceded by whitespace or be the
    whole content — an interior `{` binding rule that keeps `## [x]{#id}` a span (nit-9), and a
    single bare interior word voids the block (returns `None`).
    """
    if not content.endswith("}"):
        return None
    open_idx = content.rfind("{")
    if open_idx == -1:
        return None
    interior = content[open_idx + 1 : -1]
    # A single line-final block: no stray brace inside the candidate.
    if "{" in interior or "}" in interior:
        return None
    # Binding rule: the block attaches to the heading only when preceded by whitespace or start.
    if open_idx != 0 and content[open_idx - 1] not in " \t":
        return None
    words = _parse_attr_words(interior)
    if words is None:
        return None
    return words, content[:open_idx]


def _parse_attr_words(interior: str) -> list[tuple] | None:
    """Parse a `{...}` interior as pandoc's attribute-word sequence, or `None` if any word is bad.

    Words: `#id`, `.class`, `key=value` (value bare or single/double quoted, backslash escapes).
    A bare word (no `#`/`.`/`=`), an empty id/class/key, or an unterminated quote voids the block.
    """
    i = 0
    n = len(interior)
    words: list[tuple] = []
    while i < n:
        while i < n and interior[i] in " \t":
            i += 1
        if i >= n:
            break
        char = interior[i]
        if char in "#.":
            i += 1
            start = i
            while i < n and _is_attr_char(interior[i]):
                i += 1
            if i == start:  # empty id / class
                return None
            words.append(("id" if char == "#" else "class", interior[start:i]))
        else:
            start = i
            while i < n and _is_attr_char(interior[i]):
                i += 1
            if i == start or i >= n or interior[i] != "=":  # bare word / missing `=`
                return None
            key = interior[start:i]
            i += 1  # consume '='
            value, i = _read_attr_value(interior, i, n)
            if value is None:  # unterminated quote
                return None
            words.append(("kv", key, value))
        # Attribute words are whitespace-separated: anything else here voids the block.
        if i < n and interior[i] not in " \t":
            return None
    return words


def _read_attr_value(interior: str, i: int, n: int) -> tuple[str | None, int]:
    """Read a bare or quoted attribute value starting at `i`; return `(value, next_index)`.

    An unterminated quote yields `(None, i)` to void the block. Both bare and quoted values honor
    backslash escapes (verified: `{type=a\\ b}` -> value "a b")."""
    if i < n and interior[i] in "\"'":
        quote = interior[i]
        i += 1
        chars: list[str] = []
        while i < n and interior[i] != quote:
            if interior[i] == "\\" and i + 1 < n:
                i += 1
            chars.append(interior[i])
            i += 1
        if i >= n:  # unterminated quote
            return None, i
        return "".join(chars), i + 1
    chars = []
    while i < n and interior[i] not in " \t":
        if interior[i] == "\\" and i + 1 < n:
            i += 1
        chars.append(interior[i])
        i += 1
    return "".join(chars), i


def _is_attr_char(char: str) -> bool:
    """A pandoc identifier / class / key character: alphanumeric or one of `-_:.`."""
    return char.isalnum() or char in _ATTR_WORD_CHARS


def _strip_atx_close(text: str) -> str:
    """Strip a trailing ATX close run of `#` (and surrounding whitespace) — `## H ##` -> "H"."""
    trimmed = text.rstrip()
    without_hashes = trimmed.rstrip("#")
    if without_hashes != trimmed:
        return without_hashes.rstrip()
    return without_hashes


def _autoslug(text: str) -> str:
    """Pandoc's default auto-identifier for a heading (no `ascii_identifiers`), applied verbatim.

    Lowercase, keep alphanumerics + `_-.` + spaces, split on whitespace, join with `-`, drop
    everything up to the first alphabetic character, and fall back to "section" when empty. The
    input is post-N (NFC), and this transform never decomposes, so the slug stays NFC (nit-1a).
    Verified against pandoc: `Q3 revenue {2024}` -> "q3-revenue-2024", `3 things` -> "things",
    `123` -> "section", `Figure 3: Throughput` -> "figure-3-throughput" (the colon is DROPPED:
    pandoc's auto-identifier keeps only `-_.`, unlike an explicit `{#i:j}` id which retains `:`).
    """
    kept = [c for c in text.lower() if c.isalnum() or c in _AUTOSLUG_PUNCT or c.isspace()]
    ident = "-".join("".join(kept).split())
    start = 0
    while start < len(ident) and not ident[start].isalpha():
        start += 1
    ident = ident[start:]
    return ident if ident else "section"
