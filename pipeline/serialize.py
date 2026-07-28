"""The serialize pass (§17): IR-fitted → annotated Pandoc-Markdown → pinned AST — plan step 27.

Design authority: `docs/design.md`
  §17 RI6 — serialize is DETERMINISTIC and always produces + persists the layer-3 AST.
  §17 RI7 — **IR→AST path.** Reconcile emits IR-fitted as fully-annotated Pandoc-Markdown —
         parts as fenced Divs `::: {#id .role}`, provenance as bracketed Spans
         `[claim]{.tier data-fact=…}` — and a SINGLE pinned `pandoc -f markdown -t json`
         parse yields the AST with every attribute intact. The reader version + extension
         set are pinned (gate step 3: reader `markdown+fenced_divs+bracketed_spans`,
         api-version `[1,23,1,2]`, pandoc `3.10`; verified lossless attribute round-trip).
  §17 RI8 — **Attr mapping.** A composite part → a `Div` (class = role, kv = advisory
         `sequence`, packaging hint, and the part-id — see the ADDRESSING note below). A
         grounded claim → a `Span` (class = tier, kv = the fact anchor `data-fact` + the
         provenance: `data-source-instance`, `data-source-commit`, `data-traceability`).
  §17 RI9 — **One AST per physical output document; the pipeline orchestrates N.** The
         per-part `packaging_hint` decides: `in-document` parts co-render into ONE AST;
         each `standalone` part is its own AST, `(fitted-id, part-id)`-addressable.
  §17 RI13/FR7.1 — **the render-binding** (per deliverable): the canonical serialize-inputs
         preimage, its `hex12` digest, the deliverable-id, `minted_ts`, and the fit-binding
         reference. `minted_ts` and ALL wall-clock stay OUT of the preimage/digest — the
         same byte-reproducible-identity rule as the fit-binding (§16). Same IR-fitted +
         same pins ⇒ byte-identical output.
  §14.2 — Pandoc's binary version + AST api-version are pinned; the AST is single-document.

**Emit/extract symmetry with step 24 (`pipeline.ir`).** The claim-Span emitter here is the
INVERSE of `ir.extract_fact_refs`: every claim it emits is recoverable by `extract_fact_refs`
(same balanced-bracket, backslash-escape discipline as `ir._match_bracket`) AND round-trips
through the pinned pandoc reader. `_match_bracket` below is the byte-for-byte twin of the
step-24 reader's matcher; `tests/test_serialize.py` asserts the symmetry over concrete claims
whose visible text nests/escapes brackets, so the two can never silently diverge.

**part-id ADDRESSING (a resolved ambiguity — flagged for review).** RI8 says a part Div's
`id` is the part-id. The part-id grammar (§7.4) uses `~` (`a-…~intro`), but the pinned reader
enables `+subscript`, which CLAIMS `~` — a raw `#a-…~intro` breaks fenced-div parsing (proven
locally). So the full part-id is carried in a `data-part-id="…"` kv (a quoted value, proven to
round-trip byte-equal through pandoc) and the Div's `#id` holds the doc-unique part SLUG (the
role, or the `pNN` split label) which is `[a-z0-9-]`-safe. Addressability is preserved both
ways; the strip filter removes `data-part-id` for public writers with the rest of the `data-`
kv (it is routing metadata, not published content).

**No SSOT import (INV-CORRECTNESS, §22.7):** correctness rides content-addressed output
existence, never the SSOT. This module imports none of it.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pipeline import ids
from pipeline.canonical import canonical_json_str, digest_hex12
from pipeline.claims import AcquireOutcome, ClaimRegistry
from pipeline.filters.citeproc_enablement import CITEPROC_ENABLEMENT_VERSION
from pipeline.filters.provenance_strip import STRIP_FILTER_VERSION
from pipeline.filters.section_attr_validity import SECTION_ATTR_TRANSFORM_VERSION
from pipeline.ids import IdError, PreimageError, deliverable_id, delta_vs_floor
from pipeline.ir import PANDOC_API_VERSION, match_bracket

__all__ = [
    "ASSET_EMBED_VERSION",
    "PANDOC_API_VERSION",
    "PANDOC_BINARY_DEFAULT",
    "PANDOC_VERSION_PIN",
    "READER_PIN",
    "CODE_ALREADY_MATERIALIZED",
    "CODE_RE_SERIALIZED",
    "DISPOSITION_HIT",
    "DISPOSITION_MISS",
    "DISPOSITION_REVISION",
    "DeliverableCoordinate",
    "DocumentPlan",
    "DuplicatePartIdError",
    "PandocBytesOutcome",
    "PandocOutcome",
    "PandocParseError",
    "PandocUnavailableError",
    "RenderBindingRecord",
    "SerializeResolution",
    "run_pandoc",
    "run_pandoc_bytes",
    "SerializeError",
    "SerializedUnit",
    "build_render_binding",
    "claim_deliverable",
    "emit_claim_span",
    "emit_document_markdown",
    "emit_fitted_markdown",
    "emit_part_div",
    "enrich_leaf",
    "escape_span_text",
    "extension_for",
    "is_ci",
    "pandoc_available",
    "pandoc_gate",
    "pandoc_version",
    "parse_render_binding",
    "parse_to_ast",
    "pin_bundle",
    "plan_documents",
    "resolve_deliverable",
    "resolved_deliverable_id",
    "serialize_digest",
    "serialize_fitted",
    "serialize_inputs_preimage",
]

# ---------------------------------------------------------------------------
# The pinned toolchain (gate step 3; step-06 BUILD PARAMETER SHEET item 3). Config-pure:
# these are the PINNED values (config), never read from the installed environment (§17 FR7.1).
# ---------------------------------------------------------------------------

#: The pinned reader + extension set for the single IR-fitted → AST parse (RI7). fenced_divs
#: carries parts, bracketed_spans carries provenance spans. Kept explicit as drift armor even
#: though both are default-on at the pinned binary (step-06 sheet item 3).
READER_PIN = "markdown+fenced_divs+bracketed_spans"

#: The pinned Pandoc BINARY version this pass is certified against (gate step 3). Config-pure.
PANDOC_VERSION_PIN = "3.10"

#: The default pandoc executable (resolved on PATH). Injectable at every entry point so a test
#: can point at a bad path to exercise the unavailable branch without uninstalling pandoc.
PANDOC_BINARY_DEFAULT = "pandoc"

#: The pinned version of the body-figure EMBED behavior (increment B). Bumped only when the embed
#: mechanics change the published bytes (the `--resource-path`/`--embed-resources` surface, or the
#: writer set that embeds). It rides the serialize preimage OMIT-WHEN-ABSENT — present only when a
#: render actually embedded a figure (`assets_embedded`), so the pre-B render-digest corpus is
#: byte-identical. Defined HERE (not in `asset_loader`) to keep the module graph acyclic: importing
#: it from `asset_loader` would create serialize→asset_loader→dispatch→serialize (PART 3).
ASSET_EMBED_VERSION = "v0"

#: The provenance kv keys the emitter materializes onto a claim Span (RI8). `data-fact` (the
#: fact anchor) rides in from compose; the emitter ENRICHES with the ledger's provenance.
_ENRICH_KEYS = ("data-source-instance", "data-source-commit", "data-traceability")

#: `data-fact="f1"` / `'f1'` / `f1` — the inline fact-id reference (the step-24 reader's regex).
_DATA_FACT_RE = re.compile(r"""data-fact\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s}]+))""")


# ---------------------------------------------------------------------------
# Typed errors (§3.1: loud, typed, never repaired).
# ---------------------------------------------------------------------------


class SerializeError(RuntimeError):
    """Base serialize-pass failure — a machine-checkable defect, never guessed."""

    code = "serialize-error"


class PandocUnavailableError(SerializeError):
    """The pinned pandoc binary could not be executed — never a silent skip (§17, PA-12)."""

    code = "pandoc-unavailable"


class PandocParseError(SerializeError):
    """Pandoc parsed nonzero, emitted unparseable JSON, or emitted an off-pin api-version."""

    code = "pandoc-parse-failed"


class DuplicatePartIdError(SerializeError):
    """Two part Divs co-rendering into ONE document share a `#id` (role slug) — the emitted HTML
    would carry duplicate ids (invalid). Refused loudly (§15/RI8: a part role slug is doc-unique),
    never silently serialized."""

    code = "duplicate-part-id"


# ---------------------------------------------------------------------------
# The pandoc subprocess seam (injectable; mirrors `pipeline.transport`'s Runner pattern).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PandocOutcome:
    """One finished pandoc call: return code + captured streams (no ambient reads)."""

    returncode: int
    stdout: str
    stderr: str


#: The process seam. Default (`runner=None`) is the real `subprocess.run` below.
PandocRunner = Callable[[tuple[str, ...], str], PandocOutcome]


def _subprocess_pandoc(binary: str) -> PandocRunner:
    """The real runner factory: list-form exec (no shell), stdin-fed, on the pinned binary."""

    def _run(args: tuple[str, ...], stdin_text: str) -> PandocOutcome:
        try:
            completed = subprocess.run(  # noqa: S603 — list-form, fixed binary slot, no shell
                [binary, *args],
                input=stdin_text,
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PandocUnavailableError(
                f"pandoc-unavailable: executable {binary!r} not found — install the pinned "
                f"pandoc {PANDOC_VERSION_PIN} (never a silent no-op, §17 PA-12)"
            ) from exc
        return PandocOutcome(completed.returncode, completed.stdout, completed.stderr)

    return _run


def run_pandoc(
    args: tuple[str, ...],
    stdin_text: str,
    *,
    runner: PandocRunner | None = None,
    binary: str = PANDOC_BINARY_DEFAULT,
) -> PandocOutcome:
    """Invoke pandoc with `args`, feeding `stdin_text` on stdin. Raises `PandocUnavailableError`
    if the binary cannot be executed — the presence guard the CI step (PA-12) relies on."""
    run = runner if runner is not None else _subprocess_pandoc(binary)
    return run(args, stdin_text)


@dataclass(frozen=True)
class PandocBytesOutcome:
    """A pandoc call whose stdout may be BINARY (the docx writer) — bytes stdout, text stderr."""

    returncode: int
    stdout: bytes
    stderr: str


def run_pandoc_bytes(
    args: tuple[str, ...],
    stdin_bytes: bytes,
    *,
    binary: str = PANDOC_BINARY_DEFAULT,
) -> PandocBytesOutcome:
    """Invoke pandoc capturing BYTE stdout — for internal writers whose output is binary (docx).

    No text seam: the writer path renders real bytes and is exercised with the pinned binary
    present (the serialize tests require pandoc). Raises `PandocUnavailableError` if absent.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — list-form, fixed binary slot, no shell
            [binary, *args],
            input=stdin_bytes,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise PandocUnavailableError(
            f"pandoc-unavailable: executable {binary!r} not found — install the pinned "
            f"pandoc {PANDOC_VERSION_PIN} (never a silent no-op, §17 PA-12)"
        ) from exc
    return PandocBytesOutcome(
        completed.returncode, completed.stdout, completed.stderr.decode("utf-8", "replace")
    )


# ---------------------------------------------------------------------------
# The pandoc presence gate (PA-12): absent + CI ⇒ FAIL, never a silent skip.
# ---------------------------------------------------------------------------

_CI_TRUTHY = frozenset({"1", "true", "yes", "on"})


def is_ci(env: Mapping[str, str] | None = None) -> bool:
    """True iff the `CI` env var is truthy (`1/true/yes/on`, case-insensitive)."""
    environ = env if env is not None else os.environ
    return str(environ.get("CI", "")).strip().lower() in _CI_TRUTHY


def pandoc_available(
    *, runner: PandocRunner | None = None, binary: str = PANDOC_BINARY_DEFAULT
) -> bool:
    """True iff pandoc can be executed (`--version` exits 0). Never raises."""
    try:
        return run_pandoc(("--version",), "", runner=runner, binary=binary).returncode == 0
    except PandocUnavailableError:
        return False


def pandoc_version(
    *, runner: PandocRunner | None = None, binary: str = PANDOC_BINARY_DEFAULT
) -> str:
    """The installed pandoc version string (first line of `--version`), e.g. `3.10`."""
    out = run_pandoc(("--version",), "", runner=runner, binary=binary)
    first = out.stdout.splitlines()[0] if out.stdout else ""
    return first.replace("pandoc", "", 1).strip()


def pandoc_gate(*, available: bool, ci: bool) -> Literal["run", "skip", "fail"]:
    """The PA-12 gate decision — a PURE function, unit-testable without touching the binary.

    `available` ⇒ `run` (the serialize tests execute). Absent under CI ⇒ **`fail`** — a silent
    skip must never make CI green (§17 PA-12). Absent locally ⇒ `skip` (a dev without pandoc is
    not a red build). The CI step installs the pinned binary, so CI always lands on `run`.
    """
    if available:
        return "run"
    return "fail" if ci else "skip"


# ---------------------------------------------------------------------------
# The layer-2 file extension per output-type (§7.4 — a filename/record convenience, NEVER identity).
# ---------------------------------------------------------------------------

#: Explicit extensions for the writer families whose file extension differs from the output-type
#: slug (`plain-text` → `txt`) or where an explicit pin is clearer. An unmapped output-type defaults
#: to its own slug when that slug is a valid single-run extension (`ids._EXTENSION_RE`).
_EXTENSION_BY_OUTPUT_TYPE = {
    "md": "md",
    "html": "html",
    "docx": "docx",
    "plain-text": "txt",
    "epub": "epub",
    "pptx": "pptx",
    "pdf": "pdf",
}


def extension_for(output_type: str) -> str:
    """The conventional layer-2 file extension for one output-type (§7.4: a filename/record
    convenience, NEVER part of the content-addressed id). Known writer families map explicitly
    (`plain-text` → `txt`); an unmapped output-type defaults to its OWN slug when that slug is a
    valid single-run extension (`ids._EXTENSION_RE`, ``\\A[a-z0-9]+\\Z``) — so a newly reachable
    internal html/docx re-render labels its bytes `.html`/`.docx`, not a mislabeled `.md`, without a
    second edit. A dotted/hyphenated slug with no explicit mapping fails loud (§3.1), never mints an
    illegal extension. `extension_for("md") == "md"`, so every existing md path is a no-op."""
    mapped = _EXTENSION_BY_OUTPUT_TYPE.get(output_type)
    if mapped is not None:
        return mapped
    if isinstance(output_type, str) and ids._EXTENSION_RE.match(output_type):
        return output_type
    raise SerializeError(
        f"serialize-error: no conventional file extension for output-type {output_type!r} — add it "
        "to extension_for's map (§7.4: an extension is one [a-z0-9] run)"
    )


# ---------------------------------------------------------------------------
# Emit primitives — the INVERSE of `ir.extract_fact_refs` (emit/extract symmetry).
# ---------------------------------------------------------------------------


def escape_span_text(raw: str) -> str:
    """Escape a claim's raw visible text so a `[`/`]`/`\\` cannot break the span delimiters.

    Backslash-escapes `\\`, `[`, `]` — the exact delimiters `ir._match_bracket` treats as
    escaped/depth chars — so an emitted `[…]{attr}` round-trips through both the step-24 reader
    AND the pinned pandoc reader (which reads `\\[` / `\\]` as literal brackets). Escaping ALL
    brackets (not only unbalanced ones) is the robust rule: the result is always balanced.
    """
    return raw.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _escape_kv_value(value: str) -> str:
    """Escape a kv value for `key="value"` (backslash + doublequote). Proven to round-trip."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def emit_claim_span(
    raw_visible: str, fact_id: str, tier: str, provenance: Mapping[str, Any]
) -> str:
    """Build one grounded claim Span from scratch (the pure RI8 inverse primitive).

    `[escaped visible]{.tier data-fact="fact-id" data-source-instance=… …}`. Used for
    from-scratch emission and exercised by the round-trip tests; the enrichment path
    (`enrich_leaf`) preserves compose's already-valid visible text verbatim and only appends
    the provenance kv.
    """
    attrs = f'.{tier} data-fact="{_escape_kv_value(fact_id)}"'
    attrs = _append_provenance(attrs, provenance)
    return f"[{escape_span_text(raw_visible)}]{{{attrs}}}"


def _append_provenance(attrs: str, entry: Mapping[str, Any]) -> str:
    """Append the ledger's provenance kv (RI8) to an attr string, idempotently (never dups)."""
    values = {
        "data-source-instance": str(entry.get("source_instance_id", "")),
        "data-source-commit": str(entry.get("source_commit") or ""),
        "data-traceability": ", ".join(entry.get("traceability_anchor") or []),
    }
    additions = [
        f'{key}="{_escape_kv_value(values[key])}"' for key in _ENRICH_KEYS if key not in attrs
    ]
    if not additions:
        return attrs
    return f"{attrs.rstrip()} {' '.join(additions)}"


# ---------------------------------------------------------------------------
# The balanced-bracket span rewriter shares ONE scanner with the reader: `ir.match_bracket`
# (the step-27 F3 dedup — emit and extract can no longer drift). `_match_bracket` stays as a
# module-local alias so `tests/test_serialize.py::test_match_bracket_twins_agree_byte_for_byte`
# still guards the two module attributes.
# ---------------------------------------------------------------------------

_match_bracket = match_bracket


def _rewrite_spans(markdown: str, rewrite_attr: Callable[[str], str]) -> str:
    """Rewrite the attr block of every bracketed Span in `markdown` via `rewrite_attr`.

    Preserves the visible text VERBATIM (compose already produced valid Pandoc-Markdown), so no
    re-escaping and no round-trip risk; recurses into a span's visible text so a nested grounded
    span is rewritten too (mirrors `ir._iter_span_attrs`). Non-span text passes through byte-exact.
    """
    out: list[str] = []
    i = 0
    n = len(markdown)
    while i < n:
        ch = markdown[i]
        if ch == "\\":  # escaped char — copy both, mirroring the reader's literal `\[` / `\]`
            out.append(markdown[i : i + 2])
            i += 2
            continue
        if ch == "[":
            close = _match_bracket(markdown, i)
            if close is not None and close + 1 < n and markdown[close + 1] == "{":
                attr_end = markdown.find("}", close + 2)
                if attr_end != -1:
                    interior = _rewrite_spans(markdown[i + 1 : close], rewrite_attr)
                    new_attrs = rewrite_attr(markdown[close + 2 : attr_end])
                    out.append(f"[{interior}]{{{new_attrs}}}")
                    i = attr_end + 1
                    continue
        out.append(ch)
        i += 1
    return "".join(out)


def enrich_leaf(body: str, ledger: Mapping[str, Any]) -> str:
    """Enrich every grounded claim Span in one Markdown leaf with its ledger provenance (RI8).

    A grounded Span is one whose attr carries `data-fact`; the enrichment APPENDS the source
    instance / commit / traceability kv looked up from `ledger[fact-id]`, idempotently. The
    tier class and `data-fact` (already written by compose) are preserved; the visible text is
    preserved verbatim. Non-grounded spans and prose are untouched. Emit/extract symmetry holds
    because only kv are appended — bracket matching is unaffected.
    """

    def _rewrite(attrs: str) -> str:
        match = _DATA_FACT_RE.search(attrs)
        if match is None:
            return attrs  # a styled span with no grounding reference — leave it
        fact_id = next(g for g in match.groups() if g is not None)
        entry = ledger.get(fact_id)
        if entry is None:
            return attrs  # unknown fact-id — upstream validation owns this; never invent
        return _append_provenance(attrs, entry)

    return _rewrite_spans(body, _rewrite)


# ---------------------------------------------------------------------------
# Fenced-Div part emission (RI8) + the packaging_hint 1-vs-N document plan (RI9).
# ---------------------------------------------------------------------------


def emit_part_div(part: Mapping[str, Any], sequence: int, enriched_body: str) -> str:
    """Wrap one enriched part body in a fenced Div (RI8): `::: {#slug .role kv…}` … `:::`.

    `#slug` is the part role (a doc-unique `[a-z0-9-]` slug, §15); the FULL part-id rides in
    `data-part-id` (the `~` grammar breaks a raw `#id` under `+subscript` — see the module
    docstring). `sequence` is the part's ordinal position in the ordered `parts` list — the
    advisory intra-work sequence materialized here (§15/§17), deterministic and clock-free.
    """
    role = part["role"]
    kvs = " ".join(
        (
            f'data-part-id="{_escape_kv_value(str(part["part-id"]))}"',
            f'sequence="{sequence}"',
            f'packaging-hint="{_escape_kv_value(str(part["packaging_hint"]))}"',
        )
    )
    return f"::: {{#{role} .{role} {kvs}}}\n{enriched_body}\n:::"


@dataclass(frozen=True)
class DocumentPlan:
    """One physical output document (RI9): the leaves that co-render into ONE AST.

    `label` is None for the whole-fitted-id document (flat body, or all `in-document` parts)
    and the standalone part's slug otherwise — it becomes the `ast_store` sub-key. `part_ids`
    are the part-ids this document carries (`()` for a flat body). `leaves` are `(part | None,
    sequence, body)`: a None part is a flat body (no Div wrapping).
    """

    label: str | None
    part_ids: tuple[str, ...]
    leaves: tuple[tuple[Mapping[str, Any] | None, int, str], ...]


def plan_documents(fitted_ir: Mapping[str, Any]) -> list[DocumentPlan]:
    """Decide one-AST-vs-N from the per-part `packaging_hint` (RI9).

    Flat body → one document. Composite: every `in-document` part co-renders into ONE combined
    document (label None); every `standalone` part is its OWN document (label = its slug),
    `(fitted-id, part-id)`-addressable. `sequence` is the ordinal over the FULL ordered parts
    list (§15), so it is stable regardless of which document a part lands in.
    """
    if "body" in fitted_ir:
        return [DocumentPlan(label=None, part_ids=(), leaves=((None, 1, fitted_ir["body"]),))]

    combined_leaves: list[tuple[Mapping[str, Any], int, str]] = []
    standalone: list[DocumentPlan] = []
    for ordinal, part in enumerate(fitted_ir["parts"], start=1):
        if part["packaging_hint"] == "standalone":
            standalone.append(
                DocumentPlan(
                    label=str(part["role"]),
                    part_ids=(str(part["part-id"]),),
                    leaves=((part, ordinal, part["body"]),),
                )
            )
        else:
            combined_leaves.append((part, ordinal, part["body"]))

    documents: list[DocumentPlan] = []
    if combined_leaves:
        documents.append(
            DocumentPlan(
                label=None,
                part_ids=tuple(str(p["part-id"]) for p, _, _ in combined_leaves),
                leaves=tuple(combined_leaves),
            )
        )
    documents.extend(standalone)  # stable: combined first, then standalone in part order
    return documents


def _references_frontmatter(references: Sequence[Mapping[str, Any]]) -> str:
    """The canonical YAML frontmatter block carrying the CSL-JSON `references` (DR-5 C5, D2).

    The value is emitted as CANONICAL JSON — a strict subset of YAML — so the single pinned
    reader's native YAML→meta normalization lands it at `ast["meta"]["references"]` (C0 leg b)
    with NO extra tool and NO `--citeproc`. `canonical_json_str` (sorted keys, compact separators,
    raw UTF-8, NO wall-clock) makes the block byte-deterministic — same IR ⇒ byte-identical
    markdown ⇒ byte-identical AST (the RI7 determinism invariant) — and its full quoting prevents
    the YAML parser from type-coercing a scalar such as a `true`/`123`/`null`-valued descriptor
    field. `references` is a list (the C1 schema), rendered as a single-line YAML flow sequence.
    """
    yaml_value = canonical_json_str([dict(item) for item in references])
    return f"---\nreferences: {yaml_value}\n---\n\n"


def _check_unique_part_div_ids(plan: DocumentPlan) -> None:
    """Refuse a document whose part Divs would emit DUPLICATE `#id`s (invalid HTML).

    Every part leaf co-renders into ONE AST as a fenced Div `::: {#role .role …}`
    (`emit_part_div`, where the `#id` is the part `role` slug). Two parts sharing a `role` slug
    within a single document therefore emit two Divs with the SAME `#id` — invalid HTML. The role
    slug is documented doc-unique (§15/RI8); this makes that assumption a LOUD, typed guard rather
    than a silent invalid-HTML emission (fail-loud posture, §3.1). Standalone parts are each their
    OWN document (one Div) → never collide; a flat body carries no part Div. Happy path (unique
    slugs, the corpus): scans silently, emits identical bytes."""
    seen: set[str] = set()
    for part, _sequence, _body in plan.leaves:
        if part is None:  # a flat body — no Div, no id
            continue
        role = str(part["role"])
        if role in seen:
            raise DuplicatePartIdError(
                f"duplicate-part-id: two parts in one document both render the `#{role}` Div id "
                "— a part role slug must be doc-unique (§15/RI8), else the emitted HTML carries "
                "duplicate ids; refusing to serialize invalid HTML"
            )
        seen.add(role)


def emit_document_markdown(
    plan: DocumentPlan,
    ledger: Mapping[str, Any],
    *,
    references: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    """Emit one document's fully-annotated Pandoc-Markdown (fenced Divs + enriched Spans).

    Deterministic: leaves are concatenated in plan order, each claim Span enriched from the
    ledger, no wall-clock, stable kv ordering. This is the exact byte input to the single
    pinned parse.

    **`references` → frontmatter (DR-5 C5, D2 = FRONTMATTER).** When the fitted IR carries a
    NON-EMPTY CSL-JSON `references` block (present ONLY when the artifact cites — the C2 gate), it
    is PREPENDED as a canonical YAML frontmatter block so `serialize_fitted`'s single pinned
    `parse_to_ast` lands it at `ast["meta"]["references"]` (C0 leg b) — exactly what pandoc
    citeproc RESOLVES at C6. This step stays `--citeproc`-free (PD5: the AST is presentation-
    independent — citeproc runs at the C6 writer step): the body keeps its UNRESOLVED `Cite`
    nodes and NO bibliography is resolved here; C5 only makes `meta.references` PRESENT.

    **N3 — scoped to the FLAT-BODY / single-document render.** The frontmatter is prepended ONLY
    for the flat body (`plan.part_ids == ()` — the driving academic-paper case, one
    `plan_documents` entry). A composite/standalone plan carries part-ids, so it gets NO
    frontmatter: the MULTI-document per-document-meta partitioning (which document's `references`
    ride which physical AST) is REGISTERED here but NOT built — a multi-document citing artifact is
    out of scope for C5 and none occurs yet (the C2 gate + the flat driving example).

    `references=None`/empty ⇒ NO frontmatter ⇒ byte-identical to pre-C5 for every citation-less
    artifact (the whole existing render corpus parses to the identical AST; zero golden churn).

    HTML-VALIDITY GUARD: the part Divs' `#id`s (role slugs) must be doc-unique — a duplicate raises
    `DuplicatePartIdError` BEFORE any bytes are emitted (fail-loud, §3.1). Unique slugs (the
    corpus) pass silently → identical bytes.
    """
    _check_unique_part_div_ids(plan)
    chunks: list[str] = []
    for part, sequence, body in plan.leaves:
        enriched = enrich_leaf(body, ledger)
        chunks.append(enriched if part is None else emit_part_div(part, sequence, enriched))
    document = "\n\n".join(chunks) + "\n"
    if references and not plan.part_ids:  # N3: flat-body single document only (see docstring)
        return _references_frontmatter(references) + document
    return document


def emit_fitted_markdown(fitted_ir: Mapping[str, Any]) -> str:
    """Emit the WHOLE fitted IR as one annotated Markdown string (the combined view).

    Convenience for the single-document (flat or all-`in-document`) case and for the
    determinism test; the packaging-aware N-document path is `plan_documents` +
    `emit_document_markdown`. When `standalone` parts exist this returns their concatenation
    too, in stable plan order — a faithful whole-artifact rendering, not the per-file split.

    DR-5 C5: threads the fitted IR's `references` to each document so the flat-body single
    document gains the canonical `references` frontmatter (`emit_document_markdown`'s N3 scope);
    a citation-less IR carries no `references`, so this is byte-identical to pre-C5.
    """
    ledger = fitted_ir.get("grounding", {})
    references = fitted_ir.get("references")
    return "\n\n".join(
        emit_document_markdown(plan, ledger, references=references).rstrip("\n")
        for plan in plan_documents(fitted_ir)
    ) + "\n"


# ---------------------------------------------------------------------------
# The single pinned parse (RI7): one `pandoc -f markdown+… -t json`, api-version verified.
# ---------------------------------------------------------------------------


def parse_to_ast(
    markdown: str, *, runner: PandocRunner | None = None, binary: str = PANDOC_BINARY_DEFAULT
) -> dict[str, Any]:
    """Parse annotated Markdown to the Pandoc AST via the SINGLE pinned reader (RI7).

    `pandoc -f markdown+fenced_divs+bracketed_spans -t json` (the gate-3 pin). Verifies the
    emitted `pandoc-api-version` equals the pin (§17 RI13) — an off-pin binary is a loud
    `PandocParseError`, never silently trusted. Returns the parsed AST dict.
    """
    outcome = run_pandoc(("-f", READER_PIN, "-t", "json"), markdown, runner=runner, binary=binary)
    if outcome.returncode != 0:
        raise PandocParseError(
            f"pandoc-parse-failed: reader exited {outcome.returncode} — {outcome.stderr.strip()!r}"
        )
    try:
        ast = json.loads(outcome.stdout)
    except json.JSONDecodeError as exc:
        raise PandocParseError(
            f"pandoc-parse-failed: reader emitted unparseable JSON ({exc})"
        ) from exc
    api = ast.get("pandoc-api-version")
    if api != list(PANDOC_API_VERSION):
        raise PandocParseError(
            f"pandoc-parse-failed: emitted pandoc-api-version {api!r} != pinned "
            f"{list(PANDOC_API_VERSION)} (§17 RI13) — the reader is off-pin"
        )
    return ast


@dataclass(frozen=True)
class SerializedUnit:
    """One serialized document (RI9): its ast_store sub-`label`, the part-ids it carries, the
    emitted Markdown (kept for provenance/debug), and the parsed Pandoc AST."""

    label: str | None
    part_ids: tuple[str, ...]
    markdown: str
    ast: dict[str, Any]


def serialize_fitted(
    fitted_ir: Mapping[str, Any],
    *,
    runner: PandocRunner | None = None,
    binary: str = PANDOC_BINARY_DEFAULT,
) -> list[SerializedUnit]:
    """Serialize one IR-fitted envelope to its layer-3 AST(s) (RI6/RI7/RI9).

    Emits annotated Markdown per the packaging plan, parses each through the single pinned
    reader, and returns one `SerializedUnit` per physical document. Deterministic: same
    IR-fitted + same pinned reader ⇒ byte-identical Markdown ⇒ byte-identical ASTs.

    DR-5 C5: threads the fitted IR's CSL-JSON `references` (present only when the artifact cites —
    the C2 gate) to the emission point, so the flat-body single document's markdown gains the
    canonical `references` frontmatter and this parse lands it at `ast["meta"]["references"]`
    (`emit_document_markdown`'s N3 scope). Stays `--citeproc`-free (C6 resolves the bibliography):
    the AST carries UNRESOLVED `Cite` nodes plus a PRESENT `meta.references`. A citation-less IR
    carries no `references` ⇒ no frontmatter ⇒ byte-identical Markdown/AST to pre-C5.
    """
    ledger = fitted_ir.get("grounding", {})
    references = fitted_ir.get("references")
    units: list[SerializedUnit] = []
    for plan in plan_documents(fitted_ir):
        markdown = emit_document_markdown(plan, ledger, references=references)
        ast = parse_to_ast(markdown, runner=runner, binary=binary)
        units.append(SerializedUnit(plan.label, plan.part_ids, markdown, ast))
    return units


# ---------------------------------------------------------------------------
# The per-deliverable render-binding (RI13/FR7.1) — the deliverable-level fit-binding analogue.
# ---------------------------------------------------------------------------

#: Render-target entry keys EXCLUDED from the serialize-inputs preimage (§17 FR7.1): `side` is
#: dispatch routing, not byte-determining; the pandoc pins live in `tool_bundle` (no double
#: count); `id`/`output_type` are coordinate slugs; `schema_version`/`metadata` are §7.3
#: exclusions; `provenance`/`reader` are framework bookkeeping / covered by `tool_bundle`.
_TARGET_PREIMAGE_EXCLUDED = frozenset(
    {
        "id",
        "side",
        "output_type",
        "output-type",
        "schema_version",
        "provenance",
        "metadata",
        "reader",
        "pandoc_version",
        "pandoc_api_version",
    }
)


def serialize_inputs_preimage(
    *,
    render_target: Mapping[str, Any],
    render_inputs: Mapping[str, Any],
    render_target_defaults: Mapping[str, Any] | None = None,
    section_attr_transformed: bool = False,
    citeproc_enabled: bool = False,
    csl: tuple[str, str] | None = None,
    assets_embedded: bool = False,
    embedded_assets: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Build the COMPLETE canonical serialize-inputs preimage (§17 FR7.1).

    Everything that determines the output bytes given the fitted AST + coordinates:

    1. **the pinned tool bundle** — config-pure LITERAL pins, never ambient: pandoc version +
       AST api-version + reader extension set + the provenance-strip filter's pinned version
       (it deterministically alters html5/epub3 bytes, so it belongs in the preimage, §17 R-4).
       Read LITERALLY (they have no schema floor and are always present — they churn only when
       they actually change, which is exactly when bytes change, §17 FR7.1). The SD-5 section-attr
       transform's version (`section_attr_transform_version`) joins the bundle OMIT-WHEN-ABSENT:
       the key is present ONLY when `section_attr_transformed is True` — i.e. when the transform
       actually stripped a bare `type=`/`role=` heading kv and thereby altered the published bytes.
       On every non-typed / SAFE-writer render (`section_attr_transformed=False`) the key is ABSENT,
       so the `tool_bundle` bytes are BYTE-IDENTICAL to the pre-SD-5 form — zero churn across the
       whole existing render-digest corpus. This is UNLIKE `strip_filter_version` (an always-present
       v0 pin): a new always-present key would re-mint every existing binding for zero byte
       difference, so this one is omit-when-absent — present only when it has teeth (a typed render,
       or a future SD-5 rule change that re-mints the version), absent otherwise. The C6 citeproc-
       enablement version (`citeproc_enablement_version`) is the CONTENT-driven TWIN and joins the
       bundle the SAME OMIT-WHEN-ABSENT way: present ONLY when `citeproc_enabled is True` — when the
       render cited and `--citeproc` resolved it against `meta.references`, altering the published
       bytes. On every NON-CITING render (`citeproc_enabled=False`) the key is ABSENT,
       so the bundle bytes are BYTE-IDENTICAL to the pre-C6 form — zero churn across the existing
       corpus. The two keys are DISJOINT and INDEPENDENT (section-attr is writer-gated, citeproc is
       content-driven), so a render may carry neither, one, or both.
    2. **the render-target's byte-determining effective values, DELTA-VS-FLOOR** (`writer`,
       `engine`, `reference_doc`, writer options — the output-type *slug* is a coordinate and
       excluded via `_TARGET_PREIMAGE_EXCLUDED`; `side` is dispatch routing and excluded). The
       delta is taken against `render_target_defaults` (the registry schema floor); a value at
       its floor is ABSENT, preserving zero-churn (the same coordinate-vs-content line §16 drew).
       With no floor supplied every effective value enters literally (the step-27 skeleton form).
    3. **the lowered Presentation `RenderInputs`** (`presentation.render_inputs_to_mapping`): the
       flags, the delta-vs-floor variables snapshot, `engine`, and **every asset by CONTENT
       hash** — an edited css file churns the digest even when no schema version moved (§17). The
       DR-5 C7 `csl` STYLE asset (a `(path, content-hash)` passed via the `csl` kwarg) joins this
       component OMIT-WHEN-ABSENT: it is added as `render_inputs["csl"]` ONLY when
       `citeproc_enabled` (the style resolved). A citation-LESS render — even under a csl-set look —
       omits it, so its preimage is byte-identical to the same render without a csl (== `plain`,
       the S3×S4 identity gate); a citing render includes it, so an edited csl churns the digest for
       citing renders only. It is a Presentation ASSET, so it rides `render_inputs`, NOT the
       `tool_bundle` version surface (the SIBLING gate of `citeproc_enablement_version`).

    Increment B (body-figure EMBED) adds ONE more OMIT-WHEN-ABSENT pair, gated on `assets_embedded`
    (True only for an html5/docx render that actually inlined an `assets/…` body figure — the embed
    writers): (a) the `asset_embed_version` PIN joins `tool_bundle` (the exact twin of the
    section-attr / citeproc version keys — present only when embedding altered the bytes, so a
    NON-embedding render is byte-identical to pre-B); (b) each embedded figure's `(rel-path,
    content-hash)` joins `render_inputs["embedded_assets"]` (a CONTENT hash, kept DISJOINT from the
    presentation `assets` list) so an edited image byte re-mints the html/docx deliverable. The
    Markdown/plain writers embed nothing → `assets_embedded=False` → both keys are absent → their
    by-reference deliverable-id is unchanged (an image edit never re-mints md). `embedded_assets` is
    the sorted/deduped set (F7), so identity is order-stable.

    The `render-inputs` **exclusion set** — the inputs that are deliberately NOT part of the
    serialize-inputs IDENTITY (§17 FR7.1) — is:
      - everything fitted-level (reconcile inputs live in the fit-binding and are covered by the
        deliverable-id's fitted PREFIX, including any fit-revision qualifier);
      - the four coordinate slugs themselves (platform/language/output-type/presentation);
      - **`side: internal | external`** (dispatch routing — flipping it neither invalidates
        existing bytes nor changes what identical inputs would produce), enumerated in
        `_TARGET_PREIMAGE_EXCLUDED`;
      - `schema_version` and the `metadata` bag (§7.3), also in `_TARGET_PREIMAGE_EXCLUDED`;
      - **`minted_ts` and ALL wall-clock** — structurally absent here, so identity is
        byte-reproducible across runs regardless of the clock (the same rule as the fit-binding).

    Wall-clock and `minted_ts` are structurally absent — identity is byte-reproducible.
    """
    excluded_effective = {
        key: value for key, value in render_target.items() if key not in _TARGET_PREIMAGE_EXCLUDED
    }
    floor = render_target_defaults or {}
    excluded_floor = {
        key: value for key, value in floor.items() if key not in _TARGET_PREIMAGE_EXCLUDED
    }
    try:
        target_values = delta_vs_floor(excluded_effective, excluded_floor, where="render_target")
    except PreimageError as exc:  # pragma: no cover — defensive: a malformed render-target
        # preimage surfaces as SerializeError, uniform with the other id/preimage wraps below.
        raise SerializeError(f"serialize-error: render-target preimage: {exc}") from exc
    tool_bundle: dict[str, Any] = {
        "pandoc_version": PANDOC_VERSION_PIN,
        "pandoc_api_version": list(PANDOC_API_VERSION),
        "reader": READER_PIN,
        "strip_filter_version": STRIP_FILTER_VERSION,
    }
    # OMIT-WHEN-ABSENT (SD-5, §17 FR7.1): record the section-attr transform version ONLY when the
    # transform actually altered bytes. Absent for every non-typed / SAFE-writer render → the
    # bundle bytes are byte-identical to pre-SD-5 → the golden render-digest corpus is unchanged.
    if section_attr_transformed:
        tool_bundle["section_attr_transform_version"] = SECTION_ATTR_TRANSFORM_VERSION
    # OMIT-WHEN-ABSENT (C6, §17 R-4 family): the EXACT twin of the SD-5 line above — record the
    # citeproc-enablement version ONLY when the render actually resolved citations (`--citeproc`
    # appended over a `Cite`-bearing AST). Absent for every NON-CITING render → the bundle bytes are
    # byte-identical to pre-C6 → the golden render-digest corpus is unchanged. Disjoint from the
    # section-attr key (citeproc is content-driven, section-attr is writer-gated); the two ride
    # independently, and either present alone still leaves every other pin literal.
    if citeproc_enabled:
        tool_bundle["citeproc_enablement_version"] = CITEPROC_ENABLEMENT_VERSION
    # OMIT-WHEN-ABSENT (B, §17 FR7.1): record the body-figure embed version ONLY when the render
    # actually embedded a figure (`assets_embedded` — an html5/docx render over an `assets/…` body
    # image). Absent for every NON-embedding render (md/plain, or an image-less html/docx) → the
    # bundle bytes are byte-identical to pre-B → the golden render-digest corpus is unchanged. The
    # SIBLING content half (`embedded_assets`) rides `render_inputs` below.
    if assets_embedded:
        tool_bundle["asset_embed_version"] = ASSET_EMBED_VERSION
    # C7 (S3×S4, §17 FR7.1): the `csl` Presentation STYLE asset — a `(path, content-hash)` — enters
    # the `render_inputs` component ONLY when citeproc actually ran (`citeproc_enabled`). It is the
    # OMIT-WHEN-ABSENT SIBLING of `citeproc_enablement_version`, but a Presentation ASSET (a content
    # hash), so it rides `render_inputs` (the asset surface), not `tool_bundle` (the pinned-version
    # surface). Gating on `citeproc_enabled` discharges the identity obligation both ways: a
    # citation-LESS render under a csl-set presentation OMITS it → byte-identical to the same render
    # without a csl (== `plain`, S4, no spurious id churn); a citing render INCLUDES it → an edited
    # csl churns the digest (§17 FR7.1) — for citing renders ONLY. `csl=None` / a non-citing render
    # leaves `render_inputs` untouched → byte-identical to the pre-C7 preimage (zero golden churn).
    render_inputs_component = dict(render_inputs)
    if citeproc_enabled and csl is not None:
        render_inputs_component["csl"] = [csl[0], csl[1]]
    # B (§17 FR7.1): the SIBLING content half of `asset_embed_version` — each embedded body figure
    # by `(rel-path, content-hash)`, gated on `assets_embedded` and a non-empty set. Kept DISJOINT
    # from the presentation `assets` list (a body figure is not a presentation asset). An empty set
    # (image-less embed writer) or a non-embedding writer leaves `render_inputs` untouched → the
    # preimage is byte-identical to pre-B. Threaded as lists so the value is canonical pure-JSON.
    if assets_embedded and embedded_assets:
        render_inputs_component["embedded_assets"] = [[rel, hex_] for rel, hex_ in embedded_assets]
    preimage = {
        "tool_bundle": tool_bundle,
        "render_target": target_values,
        "render_inputs": render_inputs_component,
    }
    # Round-trip through canonical JSON so the returned value is itself canonical pure-JSON —
    # exactly what the render-binding records and the S0 preimage check read back.
    return json.loads(canonical_json_str(preimage))


def serialize_digest(preimage: Mapping[str, Any]) -> str:
    """The `hex12` serialize-inputs digest (the serialize-revision qualifier, §7.4/§17).

    Deterministic — the SAME preimage always yields the SAME digest, and `minted_ts` is
    excluded by construction (it never enters the preimage).
    """
    return digest_hex12(preimage)


def _now_iso() -> str:
    """Wall-clock UTC ISO-8601 — the DEFAULT `minted_ts` (a RECORD field only, never identity)."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def pin_bundle(
    preimage: Mapping[str, Any], *, ast_reader_pin_digest: str | None = None
) -> dict[str, Any]:
    """Assemble the RI13 pin bundle from a serialize-inputs preimage (§17 RI13).

    The §17 RI13 pin set — Pandoc binary version · AST api-version · reader extension set · the
    provenance-strip filter's pinned version · the PDF engine · `reference_doc` · Presentation
    asset content hashes + the variable snapshot — is EXACTLY what the serialize-inputs preimage
    already carries (its `tool_bundle` + `render_target` + `render_inputs`), so the bundle is a
    faithful MANIFEST projection of the preimage, not a second source of pins (one record the
    identity digest, the S0 check, and the reproducibility sidecar all read, §17). Optionally
    cites the consumed AST by its §18 reader-pin digest (`ast_reader_pin_digest`) — the caller
    computes it via `pipeline.ast_store` (serialize cannot import ast_store without a cycle).

    A record-only manifest: it is NOT hashed into the deliverable-id (its byte-determining
    components already ride the preimage), so assembling it never moves an id.
    """
    tool = dict(preimage.get("tool_bundle", {}))
    target = dict(preimage.get("render_target", {}))
    inputs = dict(preimage.get("render_inputs", {}))
    bundle = {
        "pandoc_version": tool.get("pandoc_version"),
        "pandoc_api_version": tool.get("pandoc_api_version"),
        "reader": tool.get("reader"),
        "strip_filter_version": tool.get("strip_filter_version"),
        "engine": inputs.get("engine", "") or target.get("engine", ""),
        "reference_doc": target.get("reference_doc", ""),
        "assets": [list(pair) for pair in inputs.get("assets", [])],
        "variables": dict(inputs.get("variables", {})),
    }
    if ast_reader_pin_digest is not None:
        bundle["ast_reader_pin_digest"] = ast_reader_pin_digest
    return bundle


def build_render_binding(
    *,
    fitted_id: str,
    output_type: str,
    presentation: str,
    preimage: Mapping[str, Any],
    fit_binding_ref: Mapping[str, Any],
    minted_ts: str | None = None,
    serialize_revision: bool = False,
    ast_reader_pin_digest: str | None = None,
) -> dict[str, Any]:
    """Assemble the per-deliverable render-binding (RI13/FR7.1): the serialize-inputs preimage,
    its `hex12` digest, the full deliverable-id (minted via `ids.deliverable_id`), `minted_ts`,
    the RI13 **pin bundle**, and the fit-binding reference.

    CRITICAL (the byte-reproducible-identity rule, mirroring `reconcile.build_fit_binding`):
    `minted_ts` is a RECORD field ONLY — NOT in the preimage, NOT in the digest — so
    preimage → digest → deliverable-id is byte-reproducible across runs regardless of wall
    clock (§17). The `pin_bundle` is a record-only manifest, likewise never hashed into the id.
    A `serialize_revision` fit carries the `_hex12` qualifier on the presentation segment (§7.4);
    the resolution rule that DECIDES baseline-vs-revision is `resolve_deliverable` (FR7.3) — this
    only mints and records.
    """
    if not isinstance(fit_binding_ref, Mapping) or "fitted_id" not in fit_binding_ref:
        raise SerializeError(
            "serialize-error: fit_binding_ref must reference the fitted level "
            "({fitted_id, digest}); the render-binding cites the fit-binding it extends (§17)"
        )
    digest = serialize_digest(preimage)
    revision = digest if serialize_revision else None
    try:
        del_id = deliverable_id(
            fitted_id, output_type, presentation, serialize_revision=revision
        )
    except IdError as exc:
        raise SerializeError(f"serialize-error: cannot mint the deliverable-id ({exc})") from exc
    return {
        "deliverable_id": del_id,
        "preimage": dict(preimage),
        "digest": digest,
        "minted_ts": minted_ts if minted_ts is not None else _now_iso(),
        "pin_bundle": pin_bundle(preimage, ast_reader_pin_digest=ast_reader_pin_digest),
        "fit_binding_ref": {
            "fitted_id": fit_binding_ref["fitted_id"],
            "digest": fit_binding_ref.get("digest"),
        },
    }


# ---------------------------------------------------------------------------
# The serialize-resolution rule (§17 FR7.3 / §21.8) — the DELIVERABLE-level analogue of the
# FR2 fit-resolution rule (`pipeline.fit_resolution`), with the stale-serve branch replaced by
# AUTO-MINT. Free + deterministic ⇒ no consent needed (the asymmetry principle, §17): matching
# inputs mean the byte-identical output already exists; differing inputs auto-mint a revision.
# Same three-row shape, same content-addressed identity, same rule-1 self-heal as FR2.
# ---------------------------------------------------------------------------

#: §21.7/§22.6 stable codes (REUSED, not new): a serialize-resolution HIT is `already-materialized`
#: (§21.7 REUSES it for "serialize-resolution hits" — an idempotent re-issue: the byte-identical
#: deliverable already exists); an auto-minted revision is `re-serialized` (§17/§21.8). There is
#: deliberately NO serialize-level mismatch warn — an unqualified render never returns
#: serialize-stale bytes (FR7.3), so `render-input-mismatch` stays reconcile-scoped only (§21.8).
CODE_ALREADY_MATERIALIZED = "already-materialized"
CODE_RE_SERIALIZED = "re-serialized"

#: The FR7.3 dispositions (§21.8): a true cache hit (self-heal), a none-match auto-mint revision,
#: or a no-binding first baseline mint. There is no latest-minted stale branch at this level.
DISPOSITION_HIT = "hit"
DISPOSITION_REVISION = "revision"
DISPOSITION_MISS = "miss"

#: The §7.4 serialize-revision qualifier shape (first 12 hex of SHA-256 over the preimage).
_HEX12_RE = re.compile(r"\A[0-9a-f]{12}\Z")


@dataclass(frozen=True)
class DeliverableCoordinate:
    """The `(fitted-id, output-type, presentation)` triple a deliverable resolves under (§21.8).

    `fitted_id` is a FITTED-level id (carrying any fit-revision qualifier — the fitted prefix
    covers reconcile inputs, §17); `output_type`/`presentation` are the BASE coordinate slugs the
    deliverable-id extends (§7.4). Validated so a resolution can mint the baseline / revision
    deliverable-id from it without a second parse."""

    fitted_id: str
    output_type: str
    presentation: str

    def __post_init__(self) -> None:
        try:
            parsed = ids.parse_id(self.fitted_id)
        except IdError as exc:
            raise SerializeError(
                f"serialize-error: fitted_id {self.fitted_id!r} is not a valid id ({exc})"
            ) from exc
        if parsed.family != "artifact" or parsed.level != "fitted" or parsed.part is not None:
            raise SerializeError(
                f"serialize-error: a deliverable coordinate needs a FITTED-level id (§7.1), got "
                f"level {parsed.level!r}"
            )
        # Validate the two extending slugs eagerly (a bad slug is a wiring defect, not a decision).
        try:
            ids.deliverable_id(self.fitted_id, self.output_type, self.presentation)
        except IdError as exc:
            raise SerializeError(
                f"serialize-error: {self.output_type!r}.{self.presentation!r} are not valid "
                f"deliverable coordinates ({exc})"
            ) from exc


@dataclass(frozen=True)
class RenderBindingRecord:
    """A parsed render-binding view (`build_render_binding` output): the deliverable-id, its
    `hex12` serialize-inputs digest, `minted_ts` (a record field — order lives here, never in the
    id, §21.8), and the canonical serialize-inputs preimage. The matcher reads `digest`."""

    deliverable_id: str
    digest: str
    minted_ts: str
    preimage: Mapping[str, Any]


def parse_render_binding(binding: Mapping[str, Any]) -> RenderBindingRecord:
    """Validate one render-binding dict into a `RenderBindingRecord` (loud on a malformed record,
    §3.1). Mirrors `fit_resolution.parse_fit_binding`.

    The deliverable-id must parse to the deliverable level (§7.4); the digest must be a `hex12`
    string; `minted_ts` must be a non-empty string; the preimage must be a mapping. The recorded
    `digest` is TRUSTED as the match key (§21.8 reads `binding.digest`), not recomputed here."""
    if not isinstance(binding, Mapping):
        raise SerializeError(
            f"serialize-error: a render-binding must be a mapping, got {type(binding).__name__}"
        )
    del_id = binding.get("deliverable_id")
    if not isinstance(del_id, str) or not del_id:
        raise SerializeError("serialize-error: render-binding is missing a `deliverable_id`")
    try:
        parsed = ids.parse_id(del_id)
    except IdError as exc:
        raise SerializeError(
            f"serialize-error: render-binding deliverable_id {del_id!r} is not a valid id ({exc})"
        ) from exc
    if parsed.level != "deliverable":
        raise SerializeError(
            f"serialize-error: a render-binding names a deliverable-level id (§7.1), got level "
            f"{parsed.level!r} in {del_id!r}"
        )
    digest = binding.get("digest")
    if not isinstance(digest, str) or not _HEX12_RE.match(digest):
        raise SerializeError(
            f"serialize-error: render-binding digest must be 12 lowercase hex chars (§7.4), "
            f"got {digest!r}"
        )
    minted_ts = binding.get("minted_ts")
    if not isinstance(minted_ts, str) or not minted_ts:
        raise SerializeError(
            f"serialize-error: render-binding {del_id!r} is missing a `minted_ts` record field"
        )
    preimage = binding.get("preimage")
    if not isinstance(preimage, Mapping):
        raise SerializeError(
            f"serialize-error: render-binding {del_id!r} is missing its serialize-inputs preimage"
        )
    return RenderBindingRecord(
        deliverable_id=del_id, digest=digest, minted_ts=minted_ts, preimage=preimage
    )


def _parse_binding_records(
    coordinate: DeliverableCoordinate, records: Sequence[Mapping[str, Any]]
) -> tuple[RenderBindingRecord, ...]:
    """Parse every render-binding and CONFIRM each belongs to `coordinate` (§21.8: the bindings
    under prefix `fitted-id.output-type.presentation`). Mirrors `fit_resolution._parse_records`.

    The comparison is on the BASE coordinate (the serialize-revision qualifier is what DISTINGUISHES
    revisions under the same prefix, so it is intentionally excluded from the match). A
    wrong-coordinate record is a caller wiring defect — refused loudly, never silently resolved
    against the wrong triple."""
    want = ids.parse_id(coordinate.fitted_id)
    parsed: list[RenderBindingRecord] = []
    for raw in records:
        record = parse_render_binding(raw)
        got = ids.parse_id(record.deliverable_id)
        same = (
            got.root_hex == want.root_hex
            and got.platform == want.platform
            and got.language == want.language
            and got.fit_revision == want.fit_revision
            and got.output_type == coordinate.output_type
            and got.presentation == coordinate.presentation
        )
        if not same:
            raise SerializeError(
                f"serialize-error: render-binding {record.deliverable_id!r} is not under the "
                f"resolution coordinate {coordinate.fitted_id}.{coordinate.output_type}."
                f"{coordinate.presentation} (§21.8 resolves within one prefix)"
            )
        parsed.append(record)
    return tuple(parsed)


@dataclass(frozen=True)
class SerializeResolution:
    """One serialize-resolution decision (§21.8 FR7.3) — a typed value, never an exception.

    `disposition` is the `DISPOSITION_*` row; `should_mint` + `revision` tell the caller HOW to
    materialize (mint nothing / mint the baseline `revision=False` / auto-mint the revision
    `revision=True`); `selected` is the binding to SERVE on a hit (None otherwise);
    `current_inputs_digest` is `s` (§21.8). The claim key (§22.3) is `resolved_deliverable_id(...)`.
    There is no `warning` field — this level has no mismatch warn (FR7.3)."""

    disposition: str
    status: Literal["ok"]
    code: str
    should_mint: bool
    revision: bool
    selected: RenderBindingRecord | None
    current_inputs_digest: str


def _match_binding(
    records: Sequence[RenderBindingRecord], digest: str
) -> RenderBindingRecord | None:
    """The binding whose recorded digest equals `digest`, or None (§21.8 rule 1). Distinct bindings
    for one coordinate carry DISTINCT digests by construction (a revision is minted only when its
    digest is new, §21.8), so there is at most one match; a deterministic deliverable-id sort makes
    the pick total even against a degenerate store. Mirrors `fit_resolution._match`."""
    matches = sorted(
        (r for r in records if r.digest == digest), key=lambda r: r.deliverable_id
    )
    return matches[0] if matches else None


def resolve_deliverable(
    coordinate: DeliverableCoordinate,
    records: Sequence[Mapping[str, Any]],
    current_preimage: Mapping[str, Any],
) -> SerializeResolution:
    """The FR7.3 serialize-resolution rule for an unqualified render (§17/§21.8).

    `records` are the render-bindings under the coordinate's prefix (an output-store read, §22.7);
    `current_preimage` is the CURRENT effective serialize-inputs preimage
    (`serialize_inputs_preimage`). Never reads the SSOT (§22.7 — plan/coordinate resolution).
    The DELIVERABLE-level analogue of `fit_resolution.resolve_fit`, with rule 2 AUTO-MINTING
    instead of serving stale bytes + a warn (free + deterministic ⇒ no consent, §17):
      - **hit** (rule 1): some binding matches `s` → serve it (`should_mint=False`), `ok` /
        `already-materialized` — this is what makes a tool-pin or asset revert SELF-HEALING (the
        reverted baseline's digest matches again → a hit, no re-mint), exactly like fit rule 1;
      - **miss** (rule 3): no bindings → first baseline mint (`should_mint=True, revision=False`);
      - **revision** (rule 2): bindings exist, none match → AUTO-MINT the serialize revision
        `…_<hex12>` (`should_mint=True, revision=True`), `ok` / `re-serialized`.
    Same inputs → same `s` → same revision deliverable-id → same claim key: PC3 disjointness
    (§22.3) follows by construction. Minting happens in the `render` verb ONLY — never in
    `fetch-by-id`, never at `emit-manifest` (§21.5/§21.8); this function only DECIDES."""
    bindings = _parse_binding_records(coordinate, records)
    current_digest = serialize_digest(current_preimage)

    match = _match_binding(bindings, current_digest)
    if match is not None:
        return SerializeResolution(
            disposition=DISPOSITION_HIT,
            status="ok",
            code=CODE_ALREADY_MATERIALIZED,
            should_mint=False,
            revision=False,
            selected=match,
            current_inputs_digest=current_digest,
        )
    if not bindings:
        return SerializeResolution(
            disposition=DISPOSITION_MISS,
            status="ok",
            code="ok",
            should_mint=True,
            revision=False,
            selected=None,
            current_inputs_digest=current_digest,
        )
    return SerializeResolution(
        disposition=DISPOSITION_REVISION,
        status="ok",
        code=CODE_RE_SERIALIZED,
        should_mint=True,
        revision=True,
        selected=None,
        current_inputs_digest=current_digest,
    )


def resolved_deliverable_id(
    resolution: SerializeResolution, coordinate: DeliverableCoordinate
) -> str:
    """The deliverable-id this resolution SERVES or MINTS — the §22.3 claim key.

    A hit serves the `selected` record's id. A baseline mint (miss) is the UNQUALIFIED
    deliverable-id; a revision mint carries the current-inputs `_hex12` on the presentation
    segment (§7.4). Minted via `ids.deliverable_id`, never hand-rolled — so two renders with
    identical inputs compute the IDENTICAL id (§22.3). Mirrors `resolved_fitted_id`."""
    if resolution.selected is not None and not resolution.should_mint:
        return resolution.selected.deliverable_id
    serialize_revision = resolution.current_inputs_digest if resolution.revision else None
    return deliverable_id(
        coordinate.fitted_id,
        coordinate.output_type,
        coordinate.presentation,
        serialize_revision=serialize_revision,
    )


def claim_deliverable(
    registry: ClaimRegistry,
    resolution: SerializeResolution,
    coordinate: DeliverableCoordinate,
) -> AcquireOutcome:
    """Acquire the claim on the resolution's deliverable-id before the mint (§22.3). Thin over the
    step-20 `ClaimRegistry.acquire` — no new lock logic; mirrors `fit_resolution.claim_fit`. The
    deliverable-id is content-addressed, so two renders with identical inputs pass the SAME key to
    `acquire`; the no-replace create-if-absent admits EXACTLY one winner (B4-4). Meaningful only
    when `resolution.should_mint` (a serve is read-only, needs no claim)."""
    return registry.acquire(resolved_deliverable_id(resolution, coordinate))
