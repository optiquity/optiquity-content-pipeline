"""The IR-canonical model + its JSON validation schema (§15 RI1–RI4) — plan step 24.

Design authority: `docs/design.md`
  §15 RI1 — **Envelope: JSON, Markdown in the leaves.** The IR is machine-generated,
         machine-consumed, immutable, and the input to a deterministic transform; JSON
         keeps layers 1→3 in one serialization family. This module validates that JSON.
  §15 RI2 — **Structure: an ordered `parts` list.** Each part =
         `{part-id, role, constraints?, packaging_hint, body}`; `role` is the
         Format-declared part name; `part-id` is the composite handle
         `(artifact-id, part-id)` (`pipeline.ids.part_id`); `packaging_hint ∈
         {in-document, standalone}` (§17 RI9). **Sequence is IMPLICIT** — a part's advisory
         intra-work sequence (§9.5, §17) is its ORDINAL POSITION in this ordered list,
         materialized as an explicit AST attribute only at serialize (RI8/RI14); the IR
         part shape carries NO separate `sequence` field (this validator refuses one — it
         is the A4-4 no-folio-state ruling applied to the IR). **Single-part formats
         collapse to a flat body** (§15): a format with 0 or 1 declared parts yields a
         top-level `body`, never a one-element `parts` list.
  §15 RI3 — **The grounding ledger:** `grounding: { fact-id → { tier, source_instance_id,
         source_repo, source_commit, traceability_anchor, scores_snapshot } }`, with inline
         `fact-id` references on claims in the Markdown leaves (Pandoc bracketed Spans
         `[claim]{.TIER data-fact="fact-id"}`, §17 RI8). The ledger stores **ids, anchors,
         commits — NEVER secret values** (§3.3, RI3, PC11c): this validator runs a
         closed-schema check (an undeclared ledger key is a smuggling surface — refused)
         AND a secret-shaped-value scan; a secret-shaped value ANYWHERE in the ledger (or
         the metadata bag) is REJECTED. An entry MAY additionally carry the OPTIONAL DR-6
         `attestation` carrier (`LEDGER_OPTIONAL`; the scenario-2 pool-relation record
         `{primary, anchor, relation}`) — validated only when present, so a scenario-1 entry
         stays byte-identical to pre-DR-6 (§15 RI3 note).
  §15 RI4 — **Composition binding:** the envelope records the resolved `artifact-id`
         preimage (§7.2) plus the computed `artifact-id` and the FULL digest (§7.4). The
         binding is self-describing and reproducible: `mint_artifact_id(preimage)` MUST
         reproduce the recorded `artifact_id` byte-exact and `digest_full(preimage)` the
         recorded `digest`. **Version stamps:** `ir_version` + the `pandoc-api-version` pin
         (render-reproducibility pins, not migration targets — the IR is immutable, §11.6).
  §11.3 — **The opaque `metadata` bag rides the envelope:** stored, passed through, never
         interpreted, never routed into AST content. This validator never interprets it —
         but §3.3 forbids a secret in ANY persisted record, so the bag is secret-scanned.
  §6.5 / §16 — **The EXTRACTED publish floor + no tier promotion.** Only EXTRACTED facts
         publish as fact; INFERRED/AMBIGUOUS are leads. Tier promotion is impossible
         downstream of ground. This validator enforces it at the ADDRESSABLE layer: every
         inline `data-fact` reference MUST carry, as its Span class, the SAME tier the
         ledger records for that fact-id — so a non-EXTRACTED fact rendered with an
         EXTRACTED class (asserting a lead AS fact) is caught, as is any unknown fact-id.
         (Un-addressable prose that states a lead as fact is the review gate's domain, §19;
         the IR gate guarantees every ADDRESSABLE reference is known and tier-honest.)

Layering: this module is the IR MODEL — it validates plain JSON dicts and imports only
`pipeline.ids` (binding math), `pipeline.canonical` (digests), and the tier vocabulary from
`pipeline.adapters.base`. It does NOT import `pipeline.grounding` or `pipeline.transport`;
mapping a resolved `GroundedFact` into a ledger entry, and the writer invocation, are the
compose stage's job (`pipeline.compose`).

In-latitude decisions (step-24 coder; grounded in the report):

- **The persisted IR is `parts` XOR `body`** — exactly one. A `parts` list, when present,
  has ≥ 2 entries (a single part would have collapsed to `body`, §15); an empty or
  one-element `parts` list is a defect, refused. Top-level keys are a closed set (an
  unknown top-level key is a smuggling/typo surface — refused).
- **A grounded inline reference is a Pandoc bracketed Span whose FIRST tier-valued class is
  the fact's tier** (§17 RI8: class = tier). A `data-fact` span with no tier class, or a
  tier class the ledger contradicts, is a contract violation — the single check that
  subsumes "unknown fact-id" and "non-EXTRACTED asserted as fact".
- **`source_commit` and `traceability_anchor` are tier-independent (SM9) and may be
  empty/absent-shaped:** commitless adapters (folder-style) ship `source_commit = null`;
  an EXTRACTED-yet-anchor-less fact ships `traceability_anchor = []`. Both are legal.
- **The secret scan is pattern-based, never entropy-based** — a 40-hex commit SHA is a
  legitimate `source_commit` and must never be flagged; only structurally secret shapes
  (credential-in-URL, PEM private-key blocks, known token prefixes, `secret=`/`token=`
  assignments, bearer headers) are refused. Reject-don't-leak: a match is a hard refusal.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.adapters.base import TIERS
from pipeline.canonical import CanonicalizationError, digest_full
from pipeline.ids import IdError, PreimageError, mint_artifact_id, parse_id, part_id
from pipeline.sections import (
    Count,
    Length,
    Order,
    Presence,
    SectionGrammarError,
    Selector,
)

__all__ = [
    "ATTESTATION_RELATIONS",
    "IR_VERSION",
    "KNOWN_IR_VERSIONS",
    "LEDGER_FIELDS",
    "LEDGER_OPTIONAL",
    "LEDGER_REQUIRED",
    "PACKAGING_HINTS",
    "PACKAGING_HINT_DEFAULT",
    "PANDOC_API_VERSION",
    "TOP_LEVEL_KEYS",
    "BindingMismatchError",
    "EmptySubstanceError",
    "FactRef",
    "IRError",
    "SchemaViolation",
    "SecretShapedValueError",
    "TierViolation",
    "UnknownFactError",
    "build_ir",
    "extract_fact_refs",
    "looks_secret_shaped",
    "match_bracket",
    "unwrap_ir",
    "validate_grounding_ledger",
    "validate_ir",
]

#: §15 RI4 render-reproducibility stamps. `ir_version` is the IR schema generation; the IR
#: is immutable and never schema-migrated (§11.6), so this is a provenance stamp, not a
#: migration target. `build_ir` STAMPS this on every fresh envelope, so fresh IRs are v2.
IR_VERSION = 2

#: The IR-schema generations this validator reads (F-a, DR-6 build). Read-compatibility is
#: RESERVED for ADDITIVE-OPTIONAL generations: a generation that only adds optional fields
#: (e.g. an optional ledger carrier) leaves every older envelope valid, so both may be read.
#: A BREAKING change (a removed / retyped / newly-required field) must NOT join this set — it
#: has to GATE (refuse + route to a migration), never silently read. Membership here is the
#: explicit promise that a generation is read-compatible with the ones alongside it.
KNOWN_IR_VERSIONS = frozenset({1, 2})

#: §17 RI13 / gate-3 pin (step-06 BUILD PARAMETER SHEET item "Pandoc pin"): the AST
#: `pandoc-api-version` the serialize pass parses under. Carried on every IR so a later
#: serialize is reproducible against the exact reader. Stored as a JSON list `[1,23,1,2]`;
#: the pin OF RECORD is the verbatim post-install printout (pandoc lands at step 27) — this
#: is the expected value the gate computed, reused here rather than reinvented.
PANDOC_API_VERSION = (1, 23, 1, 2)

#: §17 RI9: the per-part packaging hint — `in-document` parts co-render into one AST/file;
#: `standalone` parts are N files/N ASTs. Closed v1 set.
PACKAGING_HINTS = ("in-document", "standalone")

#: The default when a Format part declares no packaging hint (the common case: composite
#: parts co-render — slides + presenter-notes → one pptx). The actual 1-vs-N call is a
#: serialize-time dispatcher concern (§17); the IR only needs a valid, reproducible value.
PACKAGING_HINT_DEFAULT = "in-document"

#: §15 RI3: the CLOSED ledger-entry key set, split REQUIRED + OPTIONAL (F-a, DR-6 build). An
#: undeclared key is a secret/scope smuggling surface (a stray `access_token` field) — refused,
#: never carried. `LEDGER_REQUIRED` are the fields EVERY entry must carry; an additive-optional
#: generation appends names to `LEDGER_OPTIONAL` so an older 6-field entry stays valid while a
#: newer entry MAY carry the optional carrier.
LEDGER_REQUIRED = (
    "tier",
    "source_instance_id",
    "source_repo",
    "source_commit",
    "traceability_anchor",
    "scores_snapshot",
)

#: Additive-optional ledger keys (F-a landed the empty envelope governance; DR-6 COMMIT 2 lands
#: the first carrier). `attestation` is the OPTIONAL PROV-O-shaped scenario-2 pool-relation record
#: (§15 RI3): an in-pool-primary scenario-1 entry OMITS it (6-field, byte-unchanged) while a
#: scenario-2 entry MAY carry it. A later generation appends more names; the governance stays
#: `LEDGER_REQUIRED ⊆ keys ⊆ LEDGER_REQUIRED ∪ LEDGER_OPTIONAL` (an undeclared key is refused).
LEDGER_OPTIONAL: tuple[str, ...] = ("attestation",)

#: Back-compat alias (exported): the pre-F-a name for the required set. Callers importing
#: `LEDGER_FIELDS` keep working; it equals `LEDGER_REQUIRED`.
LEDGER_FIELDS = LEDGER_REQUIRED

#: The closed ledger-entry key set = required ∪ optional (mirrors `_PART_KEYS`, §15 RI2).
_LEDGER_KEYS = frozenset((*LEDGER_REQUIRED, *LEDGER_OPTIONAL))

#: §15 RI3 (DR-6): the CLOSED `attestation` sub-key set — the optional PROV-O scenario-2 carrier is
#: EXACTLY {primary, anchor, relation}. An undeclared sub-key is a smuggling/typo surface, refused
#: (mirrors the ledger-entry closure).
_ATTESTATION_KEYS = frozenset({"primary", "anchor", "relation"})

#: §15 RI3 (DR-6): the accepted PROV-O `relation` vocabulary. v1 carries `wasQuotedFrom` (a
#: secondary pool source QUOTED the out-of-pool primary). A NAMED, one-file-extensible frozenset —
#: append a PROV-O token to widen the set; NEVER an inline literal, so the vocabulary has one place
#: of record.
ATTESTATION_RELATIONS = frozenset({"wasQuotedFrom"})

#: The closed top-level envelope key set. `parts`/`body` are mutually exclusive (§15
#: flat-body collapse); `metadata` (§11.3), `section_conformance` (§15/DR-4 C4), and
#: `references` (a list of CSL-JSON citation items, DR-5 C1) are ADDITIVE-OPTIONAL keys — a
#: fresh IR carrying none of them is byte-identical to a pre-DR-4 envelope (NO
#: `ir_version`/`KNOWN_IR_VERSIONS` bump; `validate_ir` accepts them via `keys <=
#: TOP_LEVEL_KEYS`, mirroring `LEDGER_OPTIONAL`'s `attestation`). Anything else is refused.
TOP_LEVEL_KEYS = frozenset(
    {
        "ir_version",
        "pandoc_api_version",
        "binding",
        "grounding",
        "parts",
        "body",
        "metadata",
        "section_conformance",
        "references",
    }
)

#: A fact-id: a short lowercase identifier token (compose assigns `f0`, `f1`, …). Never a
#: path, never whitespace-bearing — the inline-reference and ledger-key alphabet.
_FACT_ID_RE = re.compile(r"\A[a-z][a-z0-9_-]*\Z")

#: One `.class` token inside a Span attr block (§17 RI8: the tier rides as a class).
_CLASS_RE = re.compile(r"\.([A-Za-z0-9_-]+)")

#: `data-fact="f1"` / `data-fact='f1'` / `data-fact=f1` — the inline fact-id reference.
_DATA_FACT_RE = re.compile(r"""data-fact\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s}]+))""")


# ---------------------------------------------------------------------------
# Typed errors (§3.1: loud, typed, never repaired — each carries a §21.7-style code).
# ---------------------------------------------------------------------------


class IRError(ValueError):
    """The base IR contract refusal — a machine-checkable IR defect, never guessed."""

    code = "ir-invalid"


class SchemaViolation(IRError):
    """The envelope violates the §15 structural schema (shape, keys, types, XOR, stamps)."""

    code = "ir-schema-invalid"


class EmptySubstanceError(SchemaViolation):
    """A §15 body/part-body has no substantive content — its VISIBLE text (Pandoc bracketed-span
    attr blocks `[…]{.CLASS data-…}` stripped) carries ZERO Unicode letters or digits: `"..."`,
    `"…"`, `"###"`, whitespace-only, or a markup-wrapped placeholder `[...]{.EXTRACTED
    data-fact="f0"}` whose visible text is just `...`. Such a body PARSES and validates as
    non-empty under bare truthiness yet ships an EMPTY artifact (GAP-6, VERIFIED by execution).

    This is the loud-fail GUARDRAIL that closes the valid-JSON-empty hole: the floor makes a
    substance-free body fail into the §21.9 bounded re-ask, NEVER persisted. It complements
    GAP-8's `writer.md` header strip (the FIX for the pre-parse refusal that produced such
    bodies) — the two sit on opposite sides of the parser gate. Distinct code so the derail is
    OBSERVABLE (F1), not swallowed as a generic schema fault."""

    code = "ir-empty-substance"


class UnknownFactError(IRError):
    """A leaf `data-fact` reference names a fact-id absent from the grounding ledger (§15)."""

    code = "ir-unknown-fact"


class TierViolation(IRError):
    """A grounded inline reference's tier class contradicts the ledger tier (§6.5/§16): a
    non-EXTRACTED lead asserted as fact, a tier promotion, or a class-less grounded span."""

    code = "ir-tier-violation"


class SecretShapedValueError(IRError):
    """A secret-shaped value reached the ledger or the metadata bag — refused (§3.3)."""

    code = "ir-secret-shaped-value"


class BindingMismatchError(IRError):
    """The composition binding does not reproduce the `artifact-id`/digest from its preimage
    (§15 RI4/§7.4) — a forged or corrupt binding, refused loudly."""

    code = "ir-binding-mismatch"


# ---------------------------------------------------------------------------
# The no-secrets scan (§3.3): pattern-based, never entropy-based (a commit SHA is legal).
# ---------------------------------------------------------------------------

#: Structurally secret-shaped patterns. Deliberately SPECIFIC — none matches a plain hex
#: commit SHA, a repo slug, or ordinary prose — so `source_commit`/`source_repo`/scores
#: never false-positive, while real credentials are refused. Kept as data so a future
#: tightening is a one-place edit.
_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # user:password@host inside a URL authority (a credential-bearing clone URL).
    ("credential-in-url", re.compile(r"://[^/\s:@]+:[^/\s@]+@")),
    # PEM private-key block header.
    ("pem-private-key", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    # AWS access key id.
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    # OpenAI-style / generic `sk-` secret keys (incl. sk-live-, sk-proj-).
    ("sk-secret-key", re.compile(r"\bsk-[A-Za-z0-9._-]{16,}\b")),
    # GitHub personal-access / server tokens.
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b")),
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    # Slack tokens.
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    # Google API key.
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")),
    # A JWT (three base64url segments) — bearer/session tokens.
    (
        "jwt",
        re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"),
    ),
    # `bearer <token>` header value.
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{10,}")),
    # An inline secret assignment: `password: …`, `api_key=…`, `client_secret: …`.
    (
        "secret-assignment",
        re.compile(
            r"(?i)\b(?:pass(?:word|wd)?|secret|api[_-]?key|access[_-]?key|"
            r"client[_-]?secret|private[_-]?key|auth[_-]?token|access[_-]?token)\b"
            r"\s*[:=]\s*\S"
        ),
    ),
)


def looks_secret_shaped(value: str) -> str | None:
    """Return the NAME of the first secret pattern `value` matches, or None (§3.3).

    Pattern-based by design (module docstring): a plain hex commit SHA, a repo slug, and
    ordinary prose never match — only structurally secret shapes do.
    """
    if not isinstance(value, str):
        return None
    for name, pattern in _SECRET_PATTERNS:
        if pattern.search(value):
            return name
    return None


def _scan_no_secrets(obj: Any, where: str) -> None:
    """Recursively refuse any secret-shaped STRING under `obj` (§3.3, PC11c)."""
    if isinstance(obj, str):
        hit = looks_secret_shaped(obj)
        if hit is not None:
            raise SecretShapedValueError(
                f"ir-secret-shaped-value: {where} carries a {hit}-shaped value — the "
                "grounding ledger and metadata bag store ids/anchors/commits, NEVER secret "
                "values (§3.3); refusing to persist it"
            )
        return
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            _scan_no_secrets(key, f"{where} (key)")
            _scan_no_secrets(value, f"{where}.{key}")
        return
    if isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _scan_no_secrets(item, f"{where}[{i}]")


# ---------------------------------------------------------------------------
# Inline grounded references (§17 RI8): `[claim]{.TIER data-fact="fact-id"}`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactRef:
    """One inline grounded reference parsed from a leaf body.

    `tier` is the FIRST class that is a valid confidence tier (§17 RI8: class = tier), or
    None when a `data-fact` span carries no tier class at all (a violation). `fact_id` is
    the `data-fact` value. `where` locates the leaf for error messages.
    """

    fact_id: str
    tier: str | None
    where: str


def match_bracket(text: str, start: int) -> int | None:
    """Given `text[start] == '['`, return the index of the BALANCED matching `]`, or None if
    the brackets never balance.

    A backslash escapes the next character (Pandoc reads `\\[` / `\\]` as literal, never a
    delimiter), and a nested `[...]` must close before the outer one does. This mirrors
    Pandoc's inline reader, which parses a span's visible text as balanced-bracket inlines —
    so `items[0]`, a footnote `[1]`, or any nested `[...]` inside the visible text is spanned,
    not truncated (the blind spot of a `[^\\]]*` regex, §17 RI7 pin).

    This is the ONE shared balanced-bracket scanner: the serialize emit path imports it as
    `pipeline.serialize.match_bracket` so the reader (extract) and rewriter (emit) can never
    drift (the step-27 F3 dedup; `tests/test_serialize.py::test_match_bracket_twins_agree_
    byte_for_byte` still guards the two module attributes)."""
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":  # escape: the next char is literal, never a bracket delimiter
            i += 2
            continue
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


#: Backward-compatible private alias — internal callers and the twins-agree guard test
#: (`from pipeline.ir import _match_bracket`) keep working after the step-27 F3 dedup.
_match_bracket = match_bracket


def _iter_span_attrs(markdown: str):
    """Yield the attribute text of every Pandoc bracketed Span `[visible]{attrs}` in
    `markdown` — INCLUDING a span nested inside another span's visible text.

    A span is `[` + visible text with BALANCED nested brackets + `]` IMMEDIATELY followed by a
    brace-delimited `{attrs}` block (Pandoc's `bracketed_spans` reader, §17 RI8): a bare
    markdown link `[x](url)` never matches (its `]` is followed by `(`, not `{`), while a span
    whose visible text nests brackets IS matched. Python `re` cannot match arbitrarily-nested
    brackets, so this is a hand-rolled stdlib scanner (no third-party `regex` dependency).
    Pandoc parses the visible text as inlines too, so a grounded span nested inside it is
    itself addressable — the scanner recurses into the visible text to surface it."""
    i = 0
    n = len(markdown)
    while i < n:
        ch = markdown[i]
        if ch == "\\":  # escaped char — skip both, mirroring Pandoc's literal `\[` / `\]`
            i += 2
            continue
        if ch == "[":
            close = match_bracket(markdown, i)
            if close is not None and close + 1 < n and markdown[close + 1] == "{":
                attr_end = markdown.find("}", close + 2)
                if attr_end != -1:
                    yield markdown[close + 2 : attr_end]
                    # Recurse into the visible text so a grounded span nested inside it is not
                    # missed (and the fail-closed cross-check never false-refuses honest nested
                    # grounded content).
                    yield from _iter_span_attrs(markdown[i + 1 : close])
                    i = attr_end + 1
                    continue
        i += 1


def extract_fact_refs(markdown: str, *, where: str) -> tuple[FactRef, ...]:
    """Extract every inline grounded reference from one Markdown leaf (§15/§17 RI8).

    A reference is a Pandoc bracketed Span carrying a `data-fact` attribute; its tier is
    the first tier-valued class. Spans with no `data-fact` (ordinary styled text) are
    ignored — only grounded references are addressable and checked. Span matching is
    balanced-bracket-aware (`_iter_span_attrs`), so a grounded span whose visible text nests
    brackets (`items[0]`, a footnote `[1]`) is seen and tier-checked, not silently skipped.

    Fail-closed backstop (§6.5/§16, defense-in-depth): if the raw count of `data-fact`
    attribute occurrences in the body EXCEEDS the references the scanner captured, our reader
    and Pandoc's have diverged (or a `data-fact` escaped a span) — refuse rather than persist
    a reference no tier check ever saw. With the balanced scanner this never fires on
    legitimate content; it only bites a genuine undercount.
    """
    refs: list[FactRef] = []
    for attrs in _iter_span_attrs(markdown):
        fact_match = _DATA_FACT_RE.search(attrs)
        if fact_match is None:
            continue  # a styled span with no grounding reference — not our concern
        fact_id = next(g for g in fact_match.groups() if g is not None)
        classes = _CLASS_RE.findall(attrs)
        tier = next((c for c in classes if c in TIERS), None)
        refs.append(FactRef(fact_id=fact_id, tier=tier, where=where))
    raw_data_facts = len(_DATA_FACT_RE.findall(markdown))
    if raw_data_facts > len(refs):
        raise SchemaViolation(
            f"ir-schema-invalid: {where} carries {raw_data_facts} data-fact attribute "
            f"occurrence(s) but span extraction captured {len(refs)} grounded reference(s) — an "
            "unextracted grounded span cannot be tier-checked (§6.5/§16); refusing to persist an "
            "unchecked reference"
        )
    return tuple(refs)


# ---------------------------------------------------------------------------
# The grounding ledger (§15 RI3): closed-schema + secret scan.
# ---------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SchemaViolation(f"ir-schema-invalid: {message}")


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _visible_text(value: str) -> str:
    """The reader-VISIBLE text of one Markdown leaf, with Pandoc bracketed-span attr blocks
    (`[visible]{attrs}`) stripped to their visible text (§15 substance floor).

    A NEW sibling scanner that reuses ONLY `match_bracket` (NOT `_iter_span_attrs`, which yields
    the ATTRS and DISCARDS the visible text — the exact inverse of what a substance measure needs).
    It KEEPS a span's visible text, DROPS each `{attrs}` block, and recurses into the visible text
    so a nested span's text survives: `[a]{.X}[b]{.Y}` → `ab`, `[[in]{.X}]{.Y}` → `in`, an
    all-markup placeholder `[...]{.EXTRACTED data-fact="f0"}` → `...`. A backslash escapes the next
    char (mirroring the reader's literal `\\[` / `\\]`); a `[x](url)` link (its `]` followed by `(`,
    not `{`) is left verbatim. Pure and content-blind — no Markdown parse, no §21.9 boundary
    crossing."""
    out: list[str] = []
    i = 0
    n = len(value)
    while i < n:
        ch = value[i]
        if ch == "\\":  # escaped char — the next char is literal visible text
            out.append(value[i : i + 2])
            i += 2
            continue
        if ch == "[":
            close = match_bracket(value, i)
            if close is not None and close + 1 < n and value[close + 1] == "{":
                attr_end = value.find("}", close + 2)
                if attr_end != -1:
                    out.append(_visible_text(value[i + 1 : close]))  # keep visible, drop {attrs}
                    i = attr_end + 1
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def _has_substance(value: Any) -> bool:
    """§15 substance floor: True iff the VISIBLE text (span attrs stripped) carries ≥1 Unicode
    letter or digit (category `L*`/`N*`), NFC-normalized. `_has_substance ⊂ _nonempty_str` (any
    letter/digit survives `.strip()`), so swapping it in at the two BODY sites is a MONOTONE
    strengthening — it rejects everything the old check did PLUS punctuation/symbol/whitespace-only
    and markup-wrapped placeholders, with ZERO regression on `body="x"`/`"文"`/`"5"` fixtures. A
    hard SHAPE gate, not a quality judgment: a letter-bearing placeholder is Review-1's domain
    (§19)."""
    if not isinstance(value, str):
        return False
    return any(
        unicodedata.category(ch)[0] in ("L", "N")
        for ch in unicodedata.normalize("NFC", _visible_text(value))
    )


def _require_substance(value: Any, where: str) -> None:
    """The §15 substance floor as a `_require`-style guard, raising the REQUIRED typed
    `EmptySubstanceError` (`ir-empty-substance`) — NOT the generic `SchemaViolation` — so the
    GAP-6 guardrail is observable. Its MESSAGE is substance-specific ("non-empty" is a lie for a
    `"..."` placeholder, which IS non-empty and would produce a useless re-ask)."""
    if not _has_substance(value):
        raise EmptySubstanceError(
            f"ir-empty-substance: {where} has no substantive content (letters/digits) — write the "
            "full artifact, not a placeholder like '...' (§15 RI1)"
        )


def _validate_attestation(value: Any, loc: str) -> None:
    """Validate one OPTIONAL §15 RI3 `attestation` carrier (DR-6 scenario-2 pool-relation).

    The carrier is a PROV-O-shaped Mapping with EXACTLY `{primary, anchor, relation}`:
    - `primary` is a STRUCTURED CSL-JSON-shaped Mapping (a citation descriptor for the out-of-pool
      primary B — NEVER a bare string, checklist #8). It must BE a Mapping; its key set stays OPEN
      (CSL-JSON keys — `type`, `title`, `author`, `issued`, `DOI`, `container-title`, … — are
      accepted without closing the set), so the descriptor is one-file-upgradeable. A non-Mapping
      (a bare "Smith 2020" string) is refused.
    - `anchor` is a non-empty string pointing INTO the held pool source — the same shape as a
      `traceability_anchor` entry — which is what makes the attestation itself checkable.
    - `relation` is a PROV-O token from the one-file-extensible `ATTESTATION_RELATIONS` set.
    The recursive no-secrets scan (`_scan_no_secrets`) already covers this nested Mapping, so no
    new secret scan is added here.
    """
    _require(isinstance(value, Mapping), f"{loc} must be a PROV-O attestation map (§15 RI3)")
    keys = set(value)
    _require(
        keys == _ATTESTATION_KEYS,
        f"{loc} must carry EXACTLY {sorted(_ATTESTATION_KEYS)} (§15 RI3, closed schema), got "
        f"{sorted(keys)}",
    )
    _require(
        isinstance(value["primary"], Mapping),
        f"{loc}.primary must be a STRUCTURED CSL-JSON-shaped citation descriptor (a Mapping), "
        f"never a bare string (§15 RI3, DR-6 #8), got {type(value['primary']).__name__}",
    )
    _require(
        _nonempty_str(value["anchor"]),
        f"{loc}.anchor must be a non-empty anchor string into the held pool source (§15 RI3)",
    )
    _require(
        value["relation"] in ATTESTATION_RELATIONS,
        f"{loc}.relation must be a PROV-O token in {sorted(ATTESTATION_RELATIONS)} (§15 RI3), "
        f"got {value['relation']!r}",
    )


def _validate_references(value: Any, loc: str) -> None:
    """Validate the OPTIONAL top-level `references` block — a list of CSL-JSON-shaped citation
    items recorded on the envelope for per-venue citation styling (DR-5 C1 foundation; nothing
    consumes it yet — C2 projects it from the ledger, C3+ teach `[@key]`).

    `references` is CSL-JSON-shaped like `attestation.primary` (§15 RI3) but a DISTINCT, STRICTER
    schema: every item is CITABLE (a later `[@key]` must resolve to exactly one entry), so each
    entry MUST carry a non-empty-string `id` (the citation key) — where `attestation.primary`
    requires NO `id`. The NON-`id` keys stay OPEN (CSL-JSON descriptor fields — `type`, `title`,
    `author`, `issued`, `DOI`, `container-title`, … — accepted without closing the set), so the
    descriptor is one-file-upgradeable (checklist #8, the same open-descriptor rule
    `attestation.primary` uses). `id`s MUST be UNIQUE across the list: a duplicate key is an
    ambiguous `[@key]` target (C4), refused LOUDLY. A non-list, a non-Mapping entry, a bare-string
    entry, or a missing/empty/non-string `id` is a typed `SchemaViolation`.

    Unlike `attestation` (nested INSIDE the already-scanned `grounding` ledger), `references` is a
    NEW top-level key, so the §3.3 recursive no-secrets scan is added here — a `references` entry
    can never smuggle a secret-shaped value past persistence. OMIT-WHEN-ABSENT + NOT an identity
    input — recorded OUTSIDE `binding.preimage`, so it moves NO artifact-id (body-blind).
    """
    _require(
        isinstance(value, list),
        f"{loc} must be a list of CSL-JSON citation items (DR-5 C1), never a bare "
        f"{type(value).__name__}",
    )
    _require(
        len(value) >= 1,
        f"{loc} is present but empty — an artifact with no citations OMITS the key entirely "
        "(never []/null); only a real list of citation items is recorded (DR-5 C1)",
    )
    seen: set[str] = set()
    for index, entry in enumerate(value):
        item = f"{loc}[{index}]"
        _require(
            isinstance(entry, Mapping),
            f"{item} must be a CSL-JSON-shaped citation item (a Mapping), never a bare string "
            f"(DR-5 C1), got {type(entry).__name__}",
        )
        _require(
            _nonempty_str(entry.get("id")),
            f"{item} must carry a non-empty string `id` citation key (DR-5 C1 — STRICTER than "
            "attestation.primary; every reference is citable by `[@key]`)",
        )
        cite_key = entry["id"]
        _require(
            cite_key not in seen,
            f"{item}.id {cite_key!r} is a DUPLICATE citation key — every `references` id must be "
            "unique so a later `[@key]` resolves to exactly one item (DR-5 C1)",
        )
        seen.add(cite_key)
    _scan_no_secrets(value, loc)


def validate_grounding_ledger(ledger: Any, *, where: str = "grounding") -> None:
    """Validate one §15 grounding ledger: closed entry schema + the §3.3 no-secrets scan.

    Every fact-id is a simple token; every entry carries the `LEDGER_REQUIRED` fields and MAY
    carry `LEDGER_OPTIONAL` ones (the DR-6 `attestation` carrier) — `LEDGER_REQUIRED ⊆ keys ⊆
    LEDGER_REQUIRED ∪
    LEDGER_OPTIONAL`; an undeclared key is a smuggling surface, refused. `source_commit` may be
    null (commitless adapters) and `traceability_anchor` may be empty (an anchor-less EXTRACTED
    fact is legal — SM9). After the shape check, a recursive scan refuses any secret-shaped
    string anywhere in the ledger.
    """
    _require(isinstance(ledger, Mapping), f"{where} must be a map of fact-id -> entry")
    for fact_id, entry in ledger.items():
        _require(
            isinstance(fact_id, str) and bool(_FACT_ID_RE.match(fact_id)),
            f"{where}: {fact_id!r} is not a valid fact-id ([a-z][a-z0-9_-]*)",
        )
        loc = f"{where}[{fact_id!r}]"
        _require(isinstance(entry, Mapping), f"{loc} must be a ledger-entry map")
        keys = set(entry)
        _require(
            keys <= _LEDGER_KEYS,
            f"{loc} has unknown key(s) {sorted(keys - _LEDGER_KEYS)} — a ledger entry is "
            f"{sorted(LEDGER_REQUIRED)}(+ optional {sorted(LEDGER_OPTIONAL)}) (§15 RI3, closed "
            "schema)",
        )
        for required in LEDGER_REQUIRED:
            _require(required in entry, f"{loc} is missing required key {required!r} (§15 RI3)")
        _require(
            entry["tier"] in TIERS, f"{loc}.tier must be one of {TIERS}, got {entry['tier']!r}"
        )
        _require(
            _nonempty_str(entry["source_instance_id"]), f"{loc}.source_instance_id must be set"
        )
        _require(_nonempty_str(entry["source_repo"]), f"{loc}.source_repo must be set")
        commit = entry["source_commit"]
        _require(
            commit is None or _nonempty_str(commit),
            f"{loc}.source_commit must be a non-empty string or null (commitless adapters)",
        )
        anchors = entry["traceability_anchor"]
        _require(
            isinstance(anchors, list) and all(_nonempty_str(a) for a in anchors),
            f"{loc}.traceability_anchor must be a list of non-empty anchor strings (may be empty)",
        )
        _require(
            isinstance(entry["scores_snapshot"], Mapping),
            f"{loc}.scores_snapshot must be a map of characteristic -> value",
        )
        if "attestation" in entry:  # DR-6 optional scenario-2 carrier — validated only when present
            _validate_attestation(entry["attestation"], f"{loc}.attestation")
    _scan_no_secrets(ledger, where)


# ---------------------------------------------------------------------------
# Inline-reference gate (§6.5/§16): every addressable reference is known + tier-honest.
# ---------------------------------------------------------------------------


def _validate_refs(refs: Sequence[FactRef], ledger: Mapping[str, Any]) -> None:
    """Every `data-fact` reference names a ledger fact-id AND carries that fact's exact
    ledger tier as its class (§17 RI8). This one check subsumes "unknown fact-id" and
    "non-EXTRACTED asserted as fact / tier promotion" (§6.5/§16)."""
    for ref in refs:
        if ref.fact_id not in ledger:
            raise UnknownFactError(
                f"ir-unknown-fact: {ref.where} references data-fact={ref.fact_id!r}, which is "
                "absent from the grounding ledger — every inline reference must resolve (§15)"
            )
        ledger_tier = ledger[ref.fact_id]["tier"]
        if ref.tier is None:
            raise TierViolation(
                f"ir-tier-violation: {ref.where} references data-fact={ref.fact_id!r} without a "
                f"tier class — a grounded reference must carry its ledger tier ({ledger_tier}) as "
                "a Span class (§17 RI8), so a lead can never read as asserted fact (§6.5)"
            )
        if ref.tier != ledger_tier:
            raise TierViolation(
                f"ir-tier-violation: {ref.where} references data-fact={ref.fact_id!r} with tier "
                f"class .{ref.tier} but the ledger records {ledger_tier} — tier promotion is "
                "impossible downstream of ground (§6.5/§16); a non-EXTRACTED lead may never be "
                "asserted as EXTRACTED fact"
            )


# ---------------------------------------------------------------------------
# Parts (§15 RI2): the ordered part shape, implicit sequence, no `sequence` field.
# ---------------------------------------------------------------------------

_PART_REQUIRED = ("part-id", "role", "packaging_hint", "body")
_PART_OPTIONAL = ("constraints",)
_PART_KEYS = frozenset((*_PART_REQUIRED, *_PART_OPTIONAL))


def _validate_part(part: Any, artifact_id: str, index: int, ledger: Mapping[str, Any]) -> str:
    """Validate one part; return its role (for the uniqueness check)."""
    loc = f"parts[{index}]"
    _require(isinstance(part, Mapping), f"{loc} must be a part map")
    keys = set(part)
    _require(
        {"sequence", "sequence_id"}.isdisjoint(keys),
        f"{loc} carries an explicit sequence field — sequence is IMPLICIT (positional, §15 "
        "RI2/A4-4); the ordinal is materialized only at serialize (RI8/RI14)",
    )
    _require(
        keys <= _PART_KEYS,
        f"{loc} has unknown key(s) {sorted(keys - _PART_KEYS)} — a part is "
        f"{sorted(_PART_REQUIRED)}(+ optional constraints) (§15 RI2)",
    )
    for required in _PART_REQUIRED:
        _require(required in part, f"{loc} is missing required key {required!r} (§15 RI2)")
    role = part["role"]
    _require(_nonempty_str(role), f"{loc}.role must be a non-empty Format part name")
    try:
        expected_part_id = part_id(artifact_id, role)
    except IdError as exc:
        raise SchemaViolation(
            f"ir-schema-invalid: {loc}.role {role!r} is not a §7.4 slug, so no composite "
            f"part-id can address it ({exc})"
        ) from exc
    _require(
        part["part-id"] == expected_part_id,
        f"{loc}.part-id must be the composite handle (artifact-id, role) = "
        f"{expected_part_id!r} (§15 RI2/§7.1), got {part['part-id']!r}",
    )
    _require(
        part["packaging_hint"] in PACKAGING_HINTS,
        f"{loc}.packaging_hint must be one of {PACKAGING_HINTS} (§17 RI9), "
        f"got {part['packaging_hint']!r}",
    )
    _require_substance(part["body"], f"{loc}.body")  # §15 substance floor (GAP-6) — precedes refs
    if "constraints" in part:
        _require(
            isinstance(part["constraints"], Mapping),
            f"{loc}.constraints must be a map (per-part values; interpretation deferred, §26)",
        )
    _validate_refs(extract_fact_refs(part["body"], where=f"{loc}.body"), ledger)
    return role


# ---------------------------------------------------------------------------
# Section conformance (§15, DR-4 C4): the OPTIONAL resolved base (Format) section-schema,
# recorded on the envelope for audit + so reconcile need not re-resolve it compose-side
# (D-5 record-on-IR). ADDITIVE-OPTIONAL + OMIT-WHEN-ABSENT: a Format at the `section_schema`
# floor `[]` records NO key (never `[]`/`null`), so a PRESENT field is a non-empty list. The
# field is a DERIVED projection of the Format delta already in `binding.preimage`, so it is OUT
# of identity (it never enters the preimage; the artifact-id/digest are unchanged whether or not
# it is present). When present, every rule is RECONSTRUCTED through its real `pipeline.sections`
# (C2) constructor, so the axis/severity/section-type/cardinality vocabularies keep ONE place of
# record and a malformed rule is refused LOUDLY as a typed `SchemaViolation`.
# ---------------------------------------------------------------------------

#: Per-kind closed key sets for a `section_conformance` rule map: `(REQUIRED, OPTIONAL)` (mirrors
#: `_PART_KEYS`, §15 RI2). A rule carries EXACTLY `rule` + its kind's required (+ optional) keys;
#: an undeclared key is a smuggling/typo surface, refused. `count`/`length` carry a REQUIRED
#: `severity` (the C2 dataclasses give it no default); `presence`/`order` may omit it (dataclass
#: default applies). `count`'s `cardinality` is the C2 spec string (`?`/`*`/`+`/`{n,m}`).
_CONFORMANCE_RULE_KEYS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "presence": (frozenset({"rule", "axis", "value"}), frozenset({"required", "severity"})),
    "order": (frozenset({"rule", "selectors"}), frozenset({"severity"})),
    "count": (frozenset({"rule", "axis", "value", "cardinality", "severity"}), frozenset()),
    "length": (
        frozenset({"rule", "axis", "value", "min_len", "max_len", "severity"}),
        frozenset(),
    ),
}


def _conformance_selector(axis: Any, value: Any, where: str) -> Selector:
    """Reconstruct one C2 `Selector` (raising on a bad axis, or a `type` outside the carrier)."""
    _require(isinstance(axis, str), f"{where}.axis must be a string (§15/DR-4 C2)")
    _require(isinstance(value, str), f"{where}.value must be a string (§15/DR-4 C2)")
    return Selector(axis, value)


def _conformance_rule(rule: Any, where: str) -> None:
    """Reconstruct + shape-check ONE `section_conformance` rule against the C2 vocabulary.

    Each rule is REBUILT through its real `pipeline.sections` constructor, so the axis / severity /
    section-type / cardinality vocabularies stay single-sourced in C2; a malformed rule surfaces
    the C2 typed error, which `_validate_section_conformance` wraps as a `SchemaViolation`."""
    _require(isinstance(rule, Mapping), f"{where} must be a conformance-rule map (§15/DR-4 C4)")
    kind = rule.get("rule")
    _require(
        kind in _CONFORMANCE_RULE_KEYS,
        f"{where}.rule must name a C2 menu kind {sorted(_CONFORMANCE_RULE_KEYS)}, got {kind!r}",
    )
    required, optional = _CONFORMANCE_RULE_KEYS[kind]
    allowed = required | optional
    keys = set(rule)
    _require(
        keys <= allowed,
        f"{where} has unknown key(s) {sorted(keys - allowed)} — a {kind} rule is "
        f"{sorted(required)}(+ optional {sorted(optional)}) (§15/DR-4 C2)",
    )
    _require(
        required <= keys,
        f"{where} is missing required key(s) {sorted(required - keys)} for a {kind} rule (§15)",
    )
    if kind == "presence":
        kwargs: dict[str, Any] = {}
        if "required" in rule:
            _require(
                isinstance(rule["required"], bool),
                f"{where}.required must be a boolean (§15/DR-4 C2)",
            )
            kwargs["required"] = rule["required"]
        if "severity" in rule:
            kwargs["severity"] = rule["severity"]
        Presence(_conformance_selector(rule["axis"], rule["value"], where), **kwargs)
    elif kind == "order":
        raw = rule["selectors"]
        _require(
            isinstance(raw, list), f"{where}.selectors must be a list of selector maps (§15/DR-4)"
        )
        built: list[Selector] = []
        for i, sel in enumerate(raw):
            loc = f"{where}.selectors[{i}]"
            _require(isinstance(sel, Mapping), f"{loc} must be a selector map {{axis, value}}")
            selkeys = set(sel)
            _require(
                selkeys == {"axis", "value"},
                f"{loc} must carry EXACTLY {{axis, value}} (§15/DR-4 C2), got {sorted(selkeys)}",
            )
            built.append(_conformance_selector(sel["axis"], sel["value"], loc))
        order_kwargs: dict[str, Any] = {}
        if "severity" in rule:
            order_kwargs["severity"] = rule["severity"]
        Order(tuple(built), **order_kwargs)
    elif kind == "count":
        spec = rule["cardinality"]
        _require(
            isinstance(spec, str),
            f"{where}.cardinality must be a C2 spec string (?/*/+/{{n,m}}) (§15/DR-4 C2)",
        )
        Count.from_spec(
            _conformance_selector(rule["axis"], rule["value"], where), spec, rule["severity"]
        )
    else:  # length
        min_len = rule["min_len"]
        max_len = rule["max_len"]
        _require(
            isinstance(min_len, int) and not isinstance(min_len, bool),
            f"{where}.min_len must be an integer (§15/DR-4 C2)",
        )
        _require(
            max_len is None or (isinstance(max_len, int) and not isinstance(max_len, bool)),
            f"{where}.max_len must be an integer or null (unbounded) (§15/DR-4 C2)",
        )
        Length(
            _conformance_selector(rule["axis"], rule["value"], where),
            min_len,
            max_len,
            rule["severity"],
        )


def _validate_section_conformance(schema: Any) -> None:
    """Validate the OPTIONAL `section_conformance` field — the RESOLVED base (Format) section-schema
    recorded on the envelope for audit (§15/DR-4 C4; D-5 record-on-IR, so reconcile need not
    re-resolve it compose-side). OMIT-WHEN-ABSENT: a Format at the `section_schema` floor `[]`
    records NO key, so a PRESENT field is a NON-EMPTY list; each rule is reconstructed through the
    C2 vocabulary (`pipeline.sections`) and a malformed rule is refused LOUDLY as a typed
    `SchemaViolation`. NOT an identity input — `build_ir` records it OUTSIDE `binding.preimage`."""
    _require(
        isinstance(schema, list),
        "section_conformance must be an ordered list of C2 conformance rules (§15/DR-4 C4)",
    )
    _require(
        len(schema) >= 1,
        "section_conformance is present but empty — a Format at the section_schema floor OMITS the "
        "key entirely (never []/null); only a real resolved schema is recorded (§15/DR-4 C4)",
    )
    for index, rule in enumerate(schema):
        try:
            _conformance_rule(rule, f"section_conformance[{index}]")
        except SectionGrammarError as exc:
            raise SchemaViolation(
                f"ir-schema-invalid: section_conformance[{index}] is not a valid C2 conformance "
                f"rule ({exc}) — validate it against pipeline.sections (§15/DR-4 C4)"
            ) from exc


# ---------------------------------------------------------------------------
# The full-envelope validator (§15 RI1–RI4).
# ---------------------------------------------------------------------------


def _validate_binding(binding: Any) -> str:
    """Validate the §15 RI4 composition binding; return the confirmed `artifact_id`."""
    _require(isinstance(binding, Mapping), "binding must be the composition-binding map (§15 RI4)")
    _require(
        set(binding) == {"artifact_id", "preimage", "digest"},
        "binding must carry EXACTLY {artifact_id, preimage, digest} (§15 RI4), "
        f"got {sorted(binding)}",
    )
    artifact_id = binding["artifact_id"]
    _require(isinstance(artifact_id, str) and bool(artifact_id), "binding.artifact_id must be set")
    try:
        parsed = parse_id(artifact_id)
    except IdError as exc:
        raise SchemaViolation(f"ir-schema-invalid: binding.artifact_id {exc}") from exc
    _require(
        parsed.family == "artifact" and parsed.level == "artifact" and parsed.part is None,
        f"binding.artifact_id must be a bare artifact-id (§7.1), got {artifact_id!r}",
    )
    try:
        minted = mint_artifact_id(binding["preimage"])
        digest = digest_full(binding["preimage"])
    except (PreimageError, IdError, CanonicalizationError) as exc:
        raise SchemaViolation(
            f"ir-schema-invalid: binding.preimage is not a canonical §7.2 artifact preimage "
            f"({exc}) — build it with pipeline.ids.build_artifact_preimage"
        ) from exc
    if minted != artifact_id:
        raise BindingMismatchError(
            f"ir-binding-mismatch: binding.preimage mints {minted!r} but the binding records "
            f"artifact_id {artifact_id!r} — the preimage must reproduce the id byte-exact (§7.4)"
        )
    if binding["digest"] != digest:
        raise BindingMismatchError(
            f"ir-binding-mismatch: binding.digest {binding['digest']!r} != digest_full(preimage) "
            f"{digest!r} — the recorded full digest must match its preimage (§15 RI4/§7.4)"
        )
    return artifact_id


def validate_ir(doc: Any) -> None:
    """Validate a complete persisted IR-canonical envelope against the §15 schema.

    Checks (in order): top-level closed key set + required keys; the `ir_version` /
    `pandoc-api-version` stamps; the composition binding reproduces the artifact-id and
    full digest (§15 RI4/§7.4); the grounding ledger's closed schema + no-secrets scan
    (§15 RI3/§3.3); the metadata bag (optional, secret-scanned, never interpreted, §11.3);
    the OPTIONAL `section_conformance` resolved base schema (validated against the C2
    vocabulary when present, OMIT-WHEN-ABSENT, DR-4 C4); the OPTIONAL `references` CSL-JSON
    citation block (a list of items each with a unique `id`, secret-scanned, OMIT-WHEN-ABSENT,
    DR-5 C1); and the `parts` XOR flat-`body` structure with every inline grounded reference
    known and tier-honest (§15 RI2, §6.5/§16). Raises a typed `IRError` on the first defect.
    """
    _require(isinstance(doc, Mapping), "an IR envelope is a JSON object (§15 RI1)")
    keys = set(doc)
    _require(
        keys <= TOP_LEVEL_KEYS,
        f"unknown top-level key(s) {sorted(keys - TOP_LEVEL_KEYS)} — the envelope is a closed "
        f"set {sorted(TOP_LEVEL_KEYS)} (§15)",
    )
    for required in ("ir_version", "pandoc_api_version", "binding", "grounding"):
        _require(required in doc, f"the envelope is missing required key {required!r} (§15)")
    _require(
        doc["ir_version"] in KNOWN_IR_VERSIONS,
        f"ir_version must be a known IR-schema generation {sorted(KNOWN_IR_VERSIONS)} "
        f"(additive-optional read-compatibility, F-a), got {doc['ir_version']!r}",
    )
    _require(
        doc["pandoc_api_version"] == list(PANDOC_API_VERSION),
        f"pandoc_api_version must be the pinned {list(PANDOC_API_VERSION)} (§17 RI13), "
        f"got {doc['pandoc_api_version']!r}",
    )
    artifact_id = _validate_binding(doc["binding"])
    validate_grounding_ledger(doc["grounding"])
    ledger = doc["grounding"]
    if "metadata" in doc:
        _require(
            isinstance(doc["metadata"], Mapping), "metadata must be a map (§11.3), never a leaf"
        )
        _scan_no_secrets(doc["metadata"], "metadata")
    if "section_conformance" in doc:
        _validate_section_conformance(doc["section_conformance"])
    if "references" in doc:  # DR-5 C1 optional CSL-JSON block — validated only when present
        _validate_references(doc["references"], "references")

    has_parts = "parts" in doc
    has_body = "body" in doc
    _require(
        has_parts != has_body,
        "an IR envelope carries EXACTLY one of `parts` (composite) or `body` (flat) — "
        "single-part formats collapse to a flat body (§15)",
    )
    if has_body:
        _require_substance(doc["body"], "flat body")  # §15 substance floor (GAP-6) — precedes refs
        _validate_refs(extract_fact_refs(doc["body"], where="body"), ledger)
        return
    parts = doc["parts"]
    _require(isinstance(parts, list), "parts must be an ordered JSON list (§15 RI2)")
    _require(
        len(parts) >= 2,
        f"a `parts` list has ≥ 2 entries — a single part collapses to a flat body (§15); "
        f"got {len(parts)}",
    )
    roles: list[str] = []
    for index, part in enumerate(parts):
        roles.append(_validate_part(part, artifact_id, index, ledger))
    _require(
        len(set(roles)) == len(roles),
        f"part roles must be unique within one artifact (§15 RI2), got {roles}",
    )


# ---------------------------------------------------------------------------
# The stored-record read shape (§15 RI4 / §21.8): unwrap either persisted envelope shape.
# ---------------------------------------------------------------------------

#: NEW-E (§15, GAP-1a): `unwrap_ir`'s discriminator is coupled to `TOP_LEVEL_KEYS` — a raw compose
#: IR envelope must NEVER carry a top-level `"ir"` key (else it would be misread as a wrapper). Make
#: the hidden coupling EXPLICIT and fail LOUD at import if a future schema adds `"ir"` — a silent
#: misread otherwise (R7). `validate_ir` already refuses a top-level `"ir"` (closed key set), so
#: this assert is a totality guard, not a runtime check.
assert "ir" not in TOP_LEVEL_KEYS, "unwrap_ir would misread a raw IR carrying a top-level 'ir' key"


def unwrap_ir(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the canonical IR envelope from a stored output record, tolerating BOTH persisted
    shapes (GAP-1a): a FITTED / render-binding record WRAPS the IR under `record["ir"]`
    (`driver.py`/`render.py`), while a fresh COMPOSE record IS the raw IR envelope, no wrapper
    (`compose.py` persists `canonical_json_bytes(doc)` with `doc` the full envelope). The
    discriminator is TOTAL and backward-compatible: `"ir"` is not in the closed `TOP_LEVEL_KEYS`
    (asserted above), so a raw compose envelope can never carry a spurious top-level `"ir"` and a
    fitted record always does — this never misreads either shape (§15 RI4)."""
    return record["ir"] if "ir" in record else record


# ---------------------------------------------------------------------------
# The builder: assemble + validate a full IR-canonical envelope (§15).
# ---------------------------------------------------------------------------


def build_ir(
    *,
    artifact_id: str,
    preimage: Mapping[str, Any],
    grounding: Mapping[str, Any],
    parts: Sequence[Mapping[str, Any]] | None = None,
    body: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    section_conformance: Sequence[Mapping[str, Any]] | None = None,
    references: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Assemble one IR-canonical envelope and validate it (§15 RI1–RI4).

    Exactly one of `parts` / `body` (single-part formats pass `body` — the §15 collapse).
    The composition binding is computed here: `mint_artifact_id(preimage)` must reproduce
    `artifact_id` (else a `BindingMismatchError`) and the recorded digest is
    `digest_full(preimage)`. The returned dict is validated by `validate_ir` before it is
    handed back, so a caller can never build an envelope that would fail persistence.

    `section_conformance` (optional, DR-4 C4) records the RESOLVED base (Format) section-schema
    for audit. It is OMIT-WHEN-ABSENT (a floor `[]`/`None` records NO key) and is NOT an
    identity input — it is recorded OUTSIDE `binding.preimage`, so the artifact-id/digest are
    byte-identical whether or not it is present.

    `references` (optional, DR-5 C1) records a list of CSL-JSON citation items (each with a unique
    `id` key) for per-venue citation styling. Like `section_conformance` it is OMIT-WHEN-ABSENT
    (`None`/empty records NO key), BODY-BLIND, and NOT an identity input — recorded OUTSIDE
    `binding.preimage`, so the artifact-id/digest are byte-identical with or without it.
    """
    if (parts is None) == (body is None):
        raise SchemaViolation(
            "ir-schema-invalid: build_ir needs EXACTLY one of parts / body (§15 flat-body collapse)"
        )
    try:
        minted = mint_artifact_id(preimage)
    except (PreimageError, IdError, CanonicalizationError) as exc:
        raise SchemaViolation(
            f"ir-schema-invalid: preimage is not a canonical §7.2 artifact preimage ({exc})"
        ) from exc
    if minted != artifact_id:
        raise BindingMismatchError(
            f"ir-binding-mismatch: preimage mints {minted!r}, not the given artifact_id "
            f"{artifact_id!r} (§7.4) — the roster and other run-scoped compose context are NOT "
            "identity inputs (§9.6); only the §7.2 coordinates are"
        )
    doc: dict[str, Any] = {
        "ir_version": IR_VERSION,
        "pandoc_api_version": list(PANDOC_API_VERSION),
        "binding": {
            "artifact_id": artifact_id,
            "preimage": dict(preimage),
            "digest": digest_full(preimage),
        },
        "grounding": dict(grounding),
    }
    if parts is not None:
        doc["parts"] = [dict(part) for part in parts]
    else:
        doc["body"] = body
    if metadata is not None:
        doc["metadata"] = dict(metadata)
    if section_conformance:  # OMIT-WHEN-ABSENT: a floor [] (or None) records NO key (DR-4 C4).
        doc["section_conformance"] = [dict(rule) for rule in section_conformance]
    if references:  # OMIT-WHEN-ABSENT: None/empty records NO key (body-blind, DR-5 C1).
        doc["references"] = [dict(item) for item in references]
    validate_ir(doc)
    return doc
