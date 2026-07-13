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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pipeline.canonical import canonical_json_str, digest_hex12
from pipeline.filters.provenance_strip import STRIP_FILTER_VERSION
from pipeline.ids import IdError, deliverable_id
from pipeline.ir import PANDOC_API_VERSION

__all__ = [
    "PANDOC_API_VERSION",
    "PANDOC_BINARY_DEFAULT",
    "PANDOC_VERSION_PIN",
    "READER_PIN",
    "DocumentPlan",
    "PandocBytesOutcome",
    "PandocOutcome",
    "PandocParseError",
    "PandocUnavailableError",
    "run_pandoc",
    "run_pandoc_bytes",
    "SerializeError",
    "SerializedUnit",
    "build_render_binding",
    "emit_claim_span",
    "emit_document_markdown",
    "emit_fitted_markdown",
    "emit_part_div",
    "enrich_leaf",
    "escape_span_text",
    "is_ci",
    "pandoc_available",
    "pandoc_gate",
    "pandoc_version",
    "parse_to_ast",
    "plan_documents",
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
# The balanced-bracket span rewriter — the byte-for-byte twin of `ir._match_bracket`.
# ---------------------------------------------------------------------------


def _match_bracket(text: str, start: int) -> int | None:
    """Given `text[start] == '['`, the index of the BALANCED matching `]`, or None.

    Byte-for-byte identical to `ir._match_bracket` (the step-24 reader): `\\` escapes the next
    char, a nested `[…]` closes before the outer one. Reimplemented (not imported) to keep
    serialize self-contained; `tests/test_serialize.py` cross-checks the symmetry.
    """
    depth = 0
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\":
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


def emit_document_markdown(plan: DocumentPlan, ledger: Mapping[str, Any]) -> str:
    """Emit one document's fully-annotated Pandoc-Markdown (fenced Divs + enriched Spans).

    Deterministic: leaves are concatenated in plan order, each claim Span enriched from the
    ledger, no wall-clock, stable kv ordering. This is the exact byte input to the single
    pinned parse.
    """
    chunks: list[str] = []
    for part, sequence, body in plan.leaves:
        enriched = enrich_leaf(body, ledger)
        chunks.append(enriched if part is None else emit_part_div(part, sequence, enriched))
    return "\n\n".join(chunks) + "\n"


def emit_fitted_markdown(fitted_ir: Mapping[str, Any]) -> str:
    """Emit the WHOLE fitted IR as one annotated Markdown string (the combined view).

    Convenience for the single-document (flat or all-`in-document`) case and for the
    determinism test; the packaging-aware N-document path is `plan_documents` +
    `emit_document_markdown`. When `standalone` parts exist this returns their concatenation
    too, in stable plan order — a faithful whole-artifact rendering, not the per-file split.
    """
    ledger = fitted_ir.get("grounding", {})
    return "\n\n".join(
        emit_document_markdown(plan, ledger).rstrip("\n") for plan in plan_documents(fitted_ir)
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
    """
    ledger = fitted_ir.get("grounding", {})
    units: list[SerializedUnit] = []
    for plan in plan_documents(fitted_ir):
        markdown = emit_document_markdown(plan, ledger)
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
    *, render_target: Mapping[str, Any], render_inputs: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the canonical serialize-inputs preimage SKELETON (FR7.1; full form is step 29).

    Everything that determines the output bytes given the fitted AST + coordinates: (1) the
    pinned tool bundle — config-pure LITERAL pins, never ambient; (2) the render-target's
    byte-determining effective values (`writer`, `engine`, `reference_doc`) — `side` and the
    coordinate slugs EXCLUDED (`_TARGET_PREIMAGE_EXCLUDED`); (3) the lowered `RenderInputs`.
    Wall-clock and `minted_ts` are structurally absent — identity is byte-reproducible.
    """
    target_values = {
        key: value
        for key, value in render_target.items()
        if key not in _TARGET_PREIMAGE_EXCLUDED
    }
    preimage = {
        "tool_bundle": {
            "pandoc_version": PANDOC_VERSION_PIN,
            "pandoc_api_version": list(PANDOC_API_VERSION),
            "reader": READER_PIN,
            "strip_filter_version": STRIP_FILTER_VERSION,
        },
        "render_target": target_values,
        "render_inputs": dict(render_inputs),
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


def build_render_binding(
    *,
    fitted_id: str,
    output_type: str,
    presentation: str,
    preimage: Mapping[str, Any],
    fit_binding_ref: Mapping[str, Any],
    minted_ts: str | None = None,
    serialize_revision: bool = False,
) -> dict[str, Any]:
    """Assemble the per-deliverable render-binding (RI13/FR7.1): the serialize-inputs preimage,
    its `hex12` digest, the full deliverable-id (minted via `ids.deliverable_id`), `minted_ts`,
    and the fit-binding reference.

    CRITICAL (the byte-reproducible-identity rule, mirroring `reconcile.build_fit_binding`):
    `minted_ts` is a RECORD field ONLY — NOT in the preimage, NOT in the digest — so
    preimage → digest → deliverable-id is byte-reproducible across runs regardless of wall
    clock (§17). A `serialize_revision` fit carries the `_hex12` qualifier on the presentation
    segment (§7.4); the resolution rule that DECIDES baseline-vs-revision is step 29 (FR7.3) —
    this only mints and records.
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
        "fit_binding_ref": {
            "fitted_id": fit_binding_ref["fitted_id"],
            "digest": fit_binding_ref.get("digest"),
        },
    }
