"""The ``{type=diagram}`` node/edge grammar + parser + HARD grounding gate (increment C, C1+C2).

INERT LIBRARY. This module is imported by NOTHING on the compose path yet: a ``{type=diagram}``
section still fails closed via ``sections.UnknownSectionTypeError`` (``"diagram"`` is not in
``SECTION_TYPES``) until the C4 flip wires the transform. C1 shipped the pure GRAMMAR half; C2
added :func:`gate_diagram` — the HARD grounding gate; C3 (THIS commit) adds the ``dot``/``d2``
compiler (:func:`to_dot`/:func:`to_d2`/:func:`compile_diagram`) — the FIRST subprocess in this
module, shelling to the pinned ``dot``/``d2`` binary (the ``serialize._subprocess_pandoc`` seam,
mirrored) to render a gated spec to SVG BYTES. Every function here is a LIBRARY function called
only by its own test today; C4 runs the gate + compile inside ``compose`` BEFORE any picture is
referenced, then stores the returned bytes via ``store.commit_asset(..., subdir="diagrams",
extension="svg")`` — so a diagram that would lie is REFUSED before a single SVG byte is stored.
The pieces layered onto ``DiagramSpec``:

* C2 runs the HARD grounding gate (:func:`gate_diagram`) over ``spec.edges``: per-edge REF-COUNT
  coverage (re-scanning each edge's verbatim ``citation_span`` with
  :func:`pipeline.ir.extract_fact_refs`) + the reused :func:`pipeline.ir.validate_refs` tier check
  + always-on endpoint integrity;
* C3 (THIS commit) compiles the same ``DiagramSpec`` to deterministic SVG bytes
  (:func:`compile_diagram`), MANDATORY-ESCAPING every node/edge label so an LLM-authored label can
  never inject a node or edge (BLOCKER-2 — the ``-Tcanon``/self-compile step is a malformed-source
  catch, explicitly NOT the injection defense), and baking the reader-visible
  ``illustrative — not source-checked`` stamp into an illustrative diagram's SVG (SERIOUS-1(a); the
  alt-text half is C4/SERIOUS-1(b)). The compile is byte-deterministic (same spec -> byte-identical
  SVG), so the content hash keys the stored ``assets/diagrams/<hash>.svg``; ``(tool, version)`` is
  returned as author-time provenance, NOT identity-bearing (§O3).

Grammar (strict, line-oriented — a parseable list, NOT a free-text DSL)::

    posture: illustrative          # OPTIONAL header; absent OR unrecognized => "grounded"
    nodes:
    - <id>: <label>                # >= 1 node; <id> unique, [A-Za-z0-9_][A-Za-z0-9_-]*
    - <id>: <label> {k=v ...}      # OPEN trailing attr block (D-forward: badge / group)
    edges:
    - <src> -> <dst> <citation>    # >= 1 edge; <src>/<dst> MUST be declared node ids

``<citation>`` is the VERBATIM pandoc span ``[label]{.TIER data-fact="fX"}`` — or absent, or a
bare ``[label]`` / ``[label]{.TIER}`` (all PARSE; C2's gate is what refuses an uncited edge).

VERBATIM-SPAN CONTRACT (MINOR-3, feeds C2/BLOCKER-1). ``DiagramEdge.citation_span`` stores the
edge's citation EXACTLY as authored — braces and all. The parser MUST NOT pre-extract the fact-id
or strip the braces, because C2 re-scans that same string with ``ir.extract_fact_refs`` (which only
sees ``[...]{...}`` spans); pre-extraction would make that reuse silently find zero refs and turn
the coverage check vacuous. ``DiagramEdge.label`` is a best-effort DISPLAY convenience derived from
the span's leading ``[...]``; it is never the grounding source of truth.

FAIL-CLOSED POSTURE (SERIOUS-2). An absent OR unrecognized posture parses as ``"grounded"`` (the
strict gate applies). ``"illustrative"`` is a POSITIVE, explicit author opt-in — it is never
inferred and can never become a silent gate-bypass: ONLY the exact token ``illustrative`` yields
the illustrative posture; everything else (absent, ``grounded``, a typo, garbage) => grounded.

REFUSALS. Every malformed list raises a typed :class:`DiagramGrammarError` (a
``SchemaViolation``-family IR error) — never a crash, never a silently-dropped node or edge:

* a dangling edge (a ``src``/``dst`` that is not a declared node id);
* a duplicate node id;
* a missing required field (a node without an id or a label; an edge without ``->``);
* a partial / garbled list (a stray line, a ``- `` item outside any section, an empty section).
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pipeline import ir

__all__ = [
    "D2_BINARY_DEFAULT",
    "DOT_BINARY_DEFAULT",
    "ILLUSTRATIVE_STAMP",
    "POSTURE_GROUNDED",
    "POSTURE_ILLUSTRATIVE",
    "TOOL_D2",
    "TOOL_DOT",
    "DiagramArtifact",
    "DiagramCompileError",
    "DiagramEdge",
    "DiagramGrammarError",
    "DiagramGroundingError",
    "DiagramNode",
    "DiagramRunOutcome",
    "DiagramSpec",
    "DiagramToolUnavailableError",
    "compile_diagram",
    "gate_diagram",
    "parse_diagram",
    "to_d2",
    "to_dot",
]

#: The two recognized diagram postures. ``grounded`` (the fail-closed default) subjects every edge
#: to C2's HARD grounding gate; ``illustrative`` is the explicit, reader-flagged escape hatch.
POSTURE_GROUNDED = "grounded"
POSTURE_ILLUSTRATIVE = "illustrative"

#: A shared, immutable empty attribute mapping — the default carrier for a node with no attrs.
_EMPTY_ATTRS: Mapping[str, str] = MappingProxyType({})

#: A node id (and an edge endpoint reference): a leading alphanumeric/underscore, then any of
#: alphanumeric/underscore/hyphen. Deliberately tight — the id keys the graph and (in C3) reaches
#: the ``dot``/``d2`` source, so an exotic id is refused here rather than escaped downstream.
_NODE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_-]*\Z")

#: An attribute key inside a node's ``{...}`` block.
_ATTR_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")

#: A top-level ``key:`` / ``key: value`` header line (``posture:`` / ``nodes:`` / ``edges:``).
_HEADER_RE = re.compile(r"(?P<key>[A-Za-z_][A-Za-z0-9_-]*)[ \t]*:[ \t]*(?P<value>.*)\Z")

#: A ``- <content>`` list item: optional indent, a dash, required whitespace, then the content.
_LIST_ITEM_RE = re.compile(r"[ \t]*-[ \t]+(?P<item>.*)\Z")

#: The edge arrow ``->`` with optional surrounding whitespace (splits ``<src>`` from the rest).
_ARROW_RE = re.compile(r"\s*->\s*")


class DiagramGrammarError(ir.SchemaViolation):
    """A ``{type=diagram}`` node/edge list violates the strict grammar (§C C1).

    A ``SchemaViolation``-family refusal: loud, typed, never repaired and never a silent drop. C4
    routes this — alongside C2's ``DiagramGroundingError`` and the reused ``ir`` refusals — to the
    single ``diagram-grounding-violation`` compose code via a dedicated ``except`` placed ahead of
    the generic ``except ir.IRError``.
    """

    code = "diagram-grammar-invalid"


class DiagramGroundingError(ir.IRError):
    """A grounded ``{type=diagram}`` edge is uncited or its endpoint is not a declared node (§C C2).

    Raised by :func:`gate_diagram` for the two refusals the gate OWNS: (b) an edge that resolves to
    ZERO known facts — REF-COUNT coverage, never span-presence (BLOCKER-1) — and (c) an edge whose
    endpoint is not a declared node. The other two grounded-edge refusals (an UNKNOWN fact-id, an
    INFERRED/AMBIGUOUS drawn as EXTRACTED) are the REUSED :class:`pipeline.ir.UnknownFactError` /
    :class:`pipeline.ir.TierViolation` — one place of record for the tier-honesty rule.

    An :class:`pipeline.ir.IRError` subclass (like the reused refusals), so C4's dedicated
    ``except`` — placed AHEAD of the generic ``except ir.IRError`` — catches this alongside
    :class:`DiagramGrammarError` and routes all of them to the single
    ``diagram-grounding-violation`` compose code. ``code`` is the machine-checkable umbrella; the
    message discriminates the coverage refusal (``grounding-uncovered: ...``) from the endpoint
    refusal (``diagram-grounding: ...``).
    """

    code = "grounding-uncovered"


@dataclass(frozen=True, slots=True)
class DiagramNode:
    """One box in the diagram.

    * ``id``    — the graph key; unique within the spec, ``[A-Za-z0-9_][A-Za-z0-9_-]*``.
    * ``label`` — the human-readable box text (verbatim; C3 escapes it for rendering).
    * ``attrs`` — an OPEN, read-only attribute carrier. Empty in C1; the seam that lets D add a
      grounded ``badge``/``group`` (plus its own citation span) with a one-file grammar addition
      and NO node-shape rewrite.
    """

    id: str
    label: str
    attrs: Mapping[str, str] = _EMPTY_ATTRS


@dataclass(frozen=True, slots=True)
class DiagramEdge:
    """One arrow in the diagram.

    * ``src_id`` / ``dst_id`` — declared node ids (endpoint integrity is enforced at parse time).
    * ``citation_span`` — the VERBATIM pandoc span the edge cites (``[label]{.TIER data-fact=...}``)
      or ``None`` when the edge carries no citation. Stored EXACTLY as authored for C2's re-scan
      (see the module docstring's verbatim-span contract).
    * ``label`` — a best-effort DISPLAY label pulled from the citation span's leading ``[...]``, or
      ``None``. A convenience only; never the grounding source of truth.
    """

    src_id: str
    dst_id: str
    citation_span: str | None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class DiagramSpec:
    """A parsed, ungated diagram: nodes, edges, the resolved posture, and a style ref slot.

    ``posture`` is always one of :data:`POSTURE_GROUNDED` / :data:`POSTURE_ILLUSTRATIVE` (never
    ``None`` — the parser resolves the fail-closed default). ``style_ref`` is a forward slot for
    the C5 tool/style selection (there is no inline style grammar); C1 always leaves it ``None``.
    """

    nodes: tuple[DiagramNode, ...]
    edges: tuple[DiagramEdge, ...]
    posture: str
    style_ref: str | None = None


def _msg(lineno: int, detail: str) -> str:
    return f"{DiagramGrammarError.code}: line {lineno}: {detail}"


def _tokenize_attrs(block: str, lineno: int) -> list[str]:
    """Split a node ``{...}`` attribute block into whitespace-separated tokens, keeping a
    double-quoted value (which may contain spaces, braces, or brackets) intact — so a future D
    ``badge="[net]{.EXTRACTED data-fact=\\"f2\\"}"`` value survives as one opaque token."""
    tokens: list[str] = []
    current: list[str] = []
    in_quote = False
    for ch in block:
        if in_quote:
            current.append(ch)
            if ch == '"':
                in_quote = False
        elif ch == '"':
            current.append(ch)
            in_quote = True
        elif ch.isspace():
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if in_quote:
        raise DiagramGrammarError(_msg(lineno, "a node attribute value has an unbalanced quote"))
    if current:
        tokens.append("".join(current))
    return tokens


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _parse_attr_block(block: str, lineno: int) -> Mapping[str, str]:
    attrs: dict[str, str] = {}
    for token in _tokenize_attrs(block, lineno):
        if "=" not in token:
            raise DiagramGrammarError(
                _msg(lineno, f"a node attribute {token!r} is not `key=value`")
            )
        key, value = token.split("=", 1)
        key = key.strip()
        if not _ATTR_KEY_RE.match(key):
            raise DiagramGrammarError(_msg(lineno, f"a node attribute key {key!r} is invalid"))
        if key in attrs:
            raise DiagramGrammarError(_msg(lineno, f"node attribute {key!r} is declared twice"))
        attrs[key] = _unquote(value.strip())
    return MappingProxyType(attrs)


def _split_node_attrs(item: str, lineno: int) -> tuple[str, Mapping[str, str]]:
    """Peel an OPTIONAL trailing ``{...}`` attribute block off a node item, returning the
    ``<id>: <label>`` remainder and the parsed attrs. A trailing ``}`` with a matching ``{`` is
    ALWAYS read as an attribute block (a malformed one refuses) — a node label reserving literal
    braces is out of scope for C1."""
    if not item.endswith("}"):
        return item, _EMPTY_ATTRS
    open_idx = item.rfind("{")
    if open_idx == -1:
        return item, _EMPTY_ATTRS
    attrs = _parse_attr_block(item[open_idx + 1 : -1], lineno)
    return item[:open_idx].rstrip(), attrs


def _parse_node_item(item: str, lineno: int) -> DiagramNode:
    body, attrs = _split_node_attrs(item, lineno)
    if ":" not in body:
        raise DiagramGrammarError(_msg(lineno, f"a node needs `id: label` (got {item!r})"))
    raw_id, label = body.split(":", 1)
    node_id = raw_id.strip()
    label = label.strip()
    if not node_id:
        raise DiagramGrammarError(_msg(lineno, "a node has an empty id"))
    if not _NODE_ID_RE.match(node_id):
        raise DiagramGrammarError(
            _msg(lineno, f"node id {node_id!r} is not [A-Za-z0-9_][A-Za-z0-9_-]*")
        )
    if not label:
        raise DiagramGrammarError(_msg(lineno, f"node {node_id!r} has an empty label"))
    return DiagramNode(id=node_id, label=label, attrs=attrs)


def _edge_label(citation_span: str | None) -> str | None:
    """The DISPLAY label from a citation span's leading balanced ``[...]``, or ``None``. Reuses
    the shared bracket scanner so a nested-bracket visible text (``[items[0]]``) survives."""
    if not citation_span or not citation_span.startswith("["):
        return None
    close = ir.match_bracket(citation_span, 0)
    if close is None:
        return None
    return citation_span[1:close]


def _parse_edge_item(item: str, lineno: int) -> DiagramEdge:
    arrow = _ARROW_RE.search(item)
    if arrow is None:
        raise DiagramGrammarError(_msg(lineno, f"an edge needs `<src> -> <dst>` (got {item!r})"))
    src = item[: arrow.start()].strip()
    rest = item[arrow.end() :].split(None, 1)
    dst = rest[0] if rest else ""
    citation = rest[1].strip() if len(rest) > 1 and rest[1].strip() else None
    if not src:
        raise DiagramGrammarError(_msg(lineno, "an edge has no source node"))
    if not dst:
        raise DiagramGrammarError(_msg(lineno, "an edge has no destination node"))
    if not _NODE_ID_RE.match(src):
        raise DiagramGrammarError(_msg(lineno, f"edge source id {src!r} is not a valid node id"))
    if not _NODE_ID_RE.match(dst):
        raise DiagramGrammarError(
            _msg(lineno, f"edge destination id {dst!r} is not a valid node id")
        )
    if citation is not None and not citation.startswith("["):
        raise DiagramGrammarError(
            _msg(lineno, f"an edge citation must be a `[label]{{...}}` span (got {citation!r})")
        )
    return DiagramEdge(src_id=src, dst_id=dst, citation_span=citation, label=_edge_label(citation))


def _resolve_posture(declared: str | None) -> str:
    """Fail-closed (SERIOUS-2): ONLY the explicit token ``illustrative`` opts into the
    illustrative posture; absent, ``grounded``, a typo, or garbage all resolve to ``grounded`` so
    the strict gate applies. An unknown posture can never become a silent gate-bypass."""
    if declared == POSTURE_ILLUSTRATIVE:
        return POSTURE_ILLUSTRATIVE
    return POSTURE_GROUNDED


def parse_diagram(section_body: str) -> DiagramSpec:
    """Parse a strict ``{type=diagram}`` node/edge list into a :class:`DiagramSpec`.

    Pure and inert: no I/O, no gate, no compile. A malformed list raises
    :class:`DiagramGrammarError`; a well-formed one returns nodes, edges (each carrying its
    VERBATIM ``citation_span``), and the fail-closed resolved posture. See the module docstring for
    the grammar, the verbatim-span contract, and the fail-closed posture rule.
    """
    posture: str | None = None
    section: str | None = None
    seen_sections: set[str] = set()
    nodes: list[DiagramNode] = []
    node_lines: dict[str, int] = {}
    edges: list[tuple[DiagramEdge, int]] = []

    for lineno, raw_line in enumerate(section_body.splitlines(), start=1):
        if not raw_line.strip():
            continue
        if raw_line.lstrip().startswith("-"):
            item_match = _LIST_ITEM_RE.match(raw_line)
            if item_match is None or not item_match.group("item").strip():
                raise DiagramGrammarError(
                    _msg(lineno, "a malformed list item (expected `- <content>`)")
                )
            if section is None:
                raise DiagramGrammarError(
                    _msg(lineno, "a list item appears before any `nodes:`/`edges:` section")
                )
            item = item_match.group("item").strip()
            if section == "nodes":
                node = _parse_node_item(item, lineno)
                if node.id in node_lines:
                    raise DiagramGrammarError(
                        _msg(
                            lineno,
                            f"duplicate node id {node.id!r} (first at line {node_lines[node.id]})",
                        )
                    )
                node_lines[node.id] = lineno
                nodes.append(node)
            else:
                edges.append((_parse_edge_item(item, lineno), lineno))
            continue

        header = _HEADER_RE.match(raw_line.strip())
        if header is None:
            raise DiagramGrammarError(
                _msg(
                    lineno,
                    f"unrecognized line (expected a header or `- ` item): {raw_line.strip()!r}",
                )
            )
        key = header.group("key")
        value = header.group("value").strip()
        if key == "posture":
            if posture is not None:
                raise DiagramGrammarError(_msg(lineno, "posture is declared more than once"))
            if not value:
                raise DiagramGrammarError(_msg(lineno, "the posture header has no value"))
            posture = value
        elif key in ("nodes", "edges"):
            if value:
                raise DiagramGrammarError(
                    _msg(lineno, f"the `{key}:` section header carries trailing text {value!r}")
                )
            if key in seen_sections:
                raise DiagramGrammarError(_msg(lineno, f"the `{key}:` section is declared twice"))
            seen_sections.add(key)
            section = key
        else:
            raise DiagramGrammarError(_msg(lineno, f"unknown header {key!r}"))

    if "nodes" not in seen_sections:
        raise DiagramGrammarError(_msg(0, "the diagram has no `nodes:` section"))
    if not nodes:
        raise DiagramGrammarError(_msg(0, "the `nodes:` section is empty"))
    if "edges" not in seen_sections:
        raise DiagramGrammarError(_msg(0, "the diagram has no `edges:` section"))
    if not edges:
        raise DiagramGrammarError(_msg(0, "the `edges:` section is empty"))

    for edge, lineno in edges:
        if edge.src_id not in node_lines:
            raise DiagramGrammarError(
                _msg(lineno, f"edge source {edge.src_id!r} is not a declared node")
            )
        if edge.dst_id not in node_lines:
            raise DiagramGrammarError(
                _msg(lineno, f"edge destination {edge.dst_id!r} is not a declared node")
            )

    return DiagramSpec(
        nodes=tuple(nodes),
        edges=tuple(edge for edge, _ in edges),
        posture=_resolve_posture(posture),
        style_ref=None,
    )


def gate_diagram(spec: DiagramSpec, ledger: Mapping[str, Any]) -> None:
    """The HARD grounding gate (§C C2, BLOCKER-1): a grounded diagram cannot lie. Raises on refuse.

    Runs BEFORE any picture is drawn (C4 calls it inside compose ahead of the compiler). For a
    ``grounded``-posture spec — the C1 fail-closed default for an absent/unrecognized posture —
    EVERY edge must resolve to at least one known, tier-honest source fact, or the whole document
    is REFUSED (never warned, never repaired). The three grounded refusals:

    * ``grounding-uncovered`` (:class:`DiagramGroundingError`) — an edge that resolves to ZERO
      facts. Coverage is **REF-COUNT, never span-presence**: a ``[routes]{.EXTRACTED}`` span with
      no ``data-fact`` yields ``()`` from :func:`pipeline.ir.extract_fact_refs`, and the vacuous
      ``validate_refs(())`` would pass — so the ``len(refs) < 1`` guard runs FIRST, making that
      vacuous pass unreachable. A green-looking tier class that names no fact is the exact bypass
      BLOCKER-1 names, and it is closed here.
    * ``ir-unknown-fact`` (REUSED :class:`pipeline.ir.UnknownFactError`) — an edge's ``data-fact``
      names a fact-id absent from the ledger.
    * ``ir-tier-violation`` (REUSED :class:`pipeline.ir.TierViolation`) — an INFERRED/AMBIGUOUS lead
      drawn as an EXTRACTED fact (tier promotion), or a class-less grounded ref.

    The unknown-id / tier refusals reuse :func:`pipeline.ir.validate_refs` UNCHANGED — the identical
    existence+tier check the IR body gate runs — so there is ONE place of record for the honesty
    rule and a diagram edge can never be held to a weaker bar than prose.

    ENDPOINT INTEGRITY (c) fires for BOTH postures, ALWAYS (it is not a grounding-honesty claim, so
    an illustrative sketch is still held to it). It is defense-in-depth: :func:`parse_diagram`
    already refuses a dangling endpoint, but a directly-constructed :class:`DiagramSpec` is
    re-checked here.

    ILLUSTRATIVE BYPASS skips coverage + tier (a)+(b) ONLY, never endpoint (c), and ONLY for the
    C1-resolved EXPLICIT ``illustrative`` token — never a silent bypass (SERIOUS-2: an absent, typo,
    or garbage posture already resolved to ``grounded`` in the parser, so it can never reach this
    branch). The bypass is not a free pass to ship uncited: an illustrative diagram renders only
    carrying the reader-visible "illustrative — not source-checked" stamp (baked into the SVG at C3,
    written into the alt/caption at C4). C2 only skips the grounding requirement for that explicit
    opt-in; ``spec.posture`` IS the flag C3/C4 read.

    ``ledger`` is the §15 grounding ledger: ``{fact_id: {"tier": <TIER>, ...}}``.
    """
    node_ids = {node.id for node in spec.nodes}
    # (c) ENDPOINT INTEGRITY — both postures, always (defense-in-depth over parse_diagram).
    for edge in spec.edges:
        if edge.src_id not in node_ids or edge.dst_id not in node_ids:
            raise DiagramGroundingError(
                f"diagram-grounding: edge {edge.src_id}->{edge.dst_id} endpoint is not a "
                "declared node"
            )
    # ILLUSTRATIVE BYPASS — skips (a)+(b) ONLY, never (c); only the C1-resolved explicit token.
    if spec.posture == POSTURE_ILLUSTRATIVE:
        return
    # GROUNDED posture (the fail-closed default): every edge >= 1 known, tier-honest fact.
    for edge in spec.edges:
        refs = ir.extract_fact_refs(
            edge.citation_span or "", where=f"diagram edge {edge.src_id}->{edge.dst_id}"
        )
        if len(refs) < 1:  # (b) COVERAGE = REF-COUNT — a classed span with no data-fact -> () here.
            raise DiagramGroundingError(
                f"grounding-uncovered: diagram edge {edge.src_id}->{edge.dst_id} cites no known "
                "fact (a citation span without a data-fact is not coverage)"
            )
        # (a) TIER-HONESTY — the REUSED ir check; runs AFTER coverage, so validate_refs(()) is
        #     unreachable. Raises ir.UnknownFactError (unknown id) / ir.TierViolation (bad tier).
        ir.validate_refs(refs, ledger)


# --------------------------------------------------------------------------- #
# C3 — the dot/d2 compiler: escaped source -> deterministic SVG bytes.         #
# (INERT: called only by this module's own test today; C4 wires it in.)        #
# --------------------------------------------------------------------------- #

#: The two supported diagram tools + their pinned binaries. ``dot`` is the default (the amendment
#: pin); C5 wires the selectable ``tool`` knob. Both are hierarchical layout engines run on a
#: content-addressed SVG, so a tool swap can only change bytes/hash, never add/drop/rename an edge.
TOOL_DOT = "dot"
TOOL_D2 = "d2"
DOT_BINARY_DEFAULT = "dot"
D2_BINARY_DEFAULT = "d2"
_TOOL_BINARY = {TOOL_DOT: DOT_BINARY_DEFAULT, TOOL_D2: D2_BINARY_DEFAULT}

#: The MANDATORY, reader-visible illustrative marker (SERIOUS-1). C3 bakes it into an illustrative
#: diagram's SVG (this module); C4 ALSO writes it into the Markdown alt/caption so it shows on
#: plain-text/alt-text — the SVG bake alone is invisible to the ``plain`` writer (SERIOUS-1(b)).
ILLUSTRATIVE_STAMP = "illustrative — not source-checked"


class DiagramToolUnavailableError(ir.IRError):
    """The pinned ``dot``/``d2`` binary could not be executed (§C C3).

    A LOUD refusal (never a silent no-op / empty SVG), the diagram-compiler twin of
    :class:`pipeline.serialize.PandocUnavailableError` — the same PA-12 presence discipline. Raised
    by the real runner when the tool binary is absent; C4/C5 surface it as an install signal.
    """

    code = "diagram-tool-unavailable"


class DiagramCompileError(ir.IRError):
    """The tool RAN but rejected the emitted source / failed to render (§C C3).

    Distinct from :class:`DiagramToolUnavailableError` (binary missing): the tool is present but the
    pre-store ``dot -Tcanon`` / d2 self-compile step (a MALFORMED-SOURCE catch, NOT the injection
    defense — escaping is) or the SVG render exited non-zero. In practice the escaped emitter never
    trips this; it is defense-in-depth over a directly-broken source.
    """

    code = "diagram-compile-failed"


@dataclass(frozen=True)
class DiagramRunOutcome:
    """One diagram-tool subprocess result: BYTE stdout (the SVG), text stderr (the tool log)."""

    returncode: int
    stdout: bytes
    stderr: str


#: The process seam (default ``runner=None`` -> :func:`_subprocess_diagram`). ``(binary, args,
#: stdin_bytes) -> DiagramRunOutcome`` — injectable so a test can stub the tool, no subprocess.
DiagramRunner = Callable[[str, tuple[str, ...], bytes], "DiagramRunOutcome"]


@dataclass(frozen=True, slots=True)
class DiagramArtifact:
    """A compiled diagram: the SVG bytes + the author-time compile provenance.

    * ``svg``     — the rendered SVG bytes (byte-deterministic for a given spec+tool+version). C4
      stores these via ``store.commit_asset(svg, subdir="diagrams", extension="svg")``, so the
      content hash IS the identity — ``assets/diagrams/<sha256hex>.svg``.
    * ``tool``    — ``"dot"`` / ``"d2"``, the engine that produced the bytes.
    * ``version`` — the tool version string (``dot`` 15.1.0 / ``d2`` 0.7.1). Recorded as author-time
      provenance ONLY (§O3); it is NOT part of the render preimage/identity (a tool upgrade re-mints
      a new content hash = new identity, exactly as the design wants — MINOR-4).
    """

    svg: bytes
    tool: str
    version: str


def _escape_label(text: str) -> str:
    r"""Escape an LLM-authored label for a ``dot``/``d2`` DOUBLE-QUOTED string (BLOCKER-2).

    Both tools read a ``"..."``-wrapped label as a C-style quoted string, so ONE escape neutralizes
    both: backslash -> ``\\`` FIRST (so a literal ``\N``/``\l``/``\n`` can never become a tool
    escape/justify), ``"`` -> ``\"`` (so a label can never close its own quote and inject the tokens
    after it), and every control char (newline/CR/tab, anything < 0x20, or DEL) -> a single space
    (so a label can never open a new line / shape / edge). With no surviving unescaped ``"`` a
    metacharacter like ``->``, ``{``, or ``;`` is inert literal text INSIDE the quotes — THIS is the
    injection defense; the later ``-Tcanon``/self-compile is only a malformed-source catch. Proven
    against dot 15.1.0 + d2 0.7.1: an all-metacharacter label renders as literal text and the graph
    keeps EXACTLY the spec's node/edge count.
    """
    out: list[str] = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch in "\n\r" or ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(" ")
        else:
            out.append(ch)
    return "".join(out)


def _quoted(text: str) -> str:
    """A double-quoted, escaped ``dot``/``d2`` string literal (shared — both use the same form)."""
    return f'"{_escape_label(text)}"'


def to_dot(spec: DiagramSpec) -> str:
    r"""Emit Graphviz DOT source for ``spec`` — every node/edge label ESCAPED (BLOCKER-2). PURE.

    Hierarchical ``dot`` engine, ``rankdir=TB`` (NOT neato/fdp). Node ids — already restricted to
    ``[A-Za-z0-9_][A-Za-z0-9_-]*`` by :func:`parse_diagram` — are quoted so a hyphenated id is legal
    DOT; every LLM-authored label is escaped via :func:`_escape_label`. An illustrative spec bakes
    the MANDATORY ``illustrative — not source-checked`` graph caption (SERIOUS-1(a)) at the bottom —
    it cannot be emitted without it. String in, string out; no I/O.
    """
    lines = ["digraph G {", "  rankdir=TB;"]
    if spec.posture == POSTURE_ILLUSTRATIVE:
        lines.append(f"  label={_quoted(ILLUSTRATIVE_STAMP)};")
        lines.append('  labelloc="b";')
    for node in spec.nodes:
        lines.append(f"  {_quoted(node.id)} [label={_quoted(node.label)}];")
    for edge in spec.edges:
        head = f"  {_quoted(edge.src_id)} -> {_quoted(edge.dst_id)}"
        if edge.label is not None:
            lines.append(f"{head} [label={_quoted(edge.label)}];")
        else:
            lines.append(f"{head};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def to_d2(spec: DiagramSpec) -> str:
    r"""Emit D2 source for ``spec`` — every node/edge label a double-quoted, ESCAPED string. PURE.

    Node ids and labels are double-quoted (the d2-0.7.1 quoted-string form, empirically confirmed):
    :func:`_escape_label` neutralizes ``"``, ``\``, and every control char so a label can never open
    a new shape or connection. An illustrative spec appends the MANDATORY
    ``illustrative — not source-checked`` stamp as a borderless ``shape: text`` near the bottom
    (SERIOUS-1(a)). String in, string out; no I/O.
    """
    lines: list[str] = []
    for node in spec.nodes:
        lines.append(f"{_quoted(node.id)}: {_quoted(node.label)}")
    for edge in spec.edges:
        conn = f"{_quoted(edge.src_id)} -> {_quoted(edge.dst_id)}"
        lines.append(f"{conn}: {_quoted(edge.label)}" if edge.label is not None else conn)
    if spec.posture == POSTURE_ILLUSTRATIVE:
        stamp = _quoted(ILLUSTRATIVE_STAMP)
        lines.append(f"_diagram_stamp: {stamp} {{shape: text; near: bottom-center}}")
    return "\n".join(lines) + "\n"


def _subprocess_diagram(binary: str, args: tuple[str, ...], stdin: bytes) -> DiagramRunOutcome:
    """The real runner: list-form exec (no shell), stdin-fed BYTES, on the pinned binary.

    Mirrors :func:`pipeline.serialize.run_pandoc_bytes` (serialize.py) — a missing binary raises the
    loud :class:`DiagramToolUnavailableError` (never a silent no-op), the same PA-12 presence gate
    the pandoc seam uses. Deterministic: no timestamps/env leak into stdout for either tool.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — list-form, fixed binary slot, no shell
            [binary, *args],
            input=stdin,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise DiagramToolUnavailableError(
            f"{DiagramToolUnavailableError.code}: executable {binary!r} not found — install the "
            "pinned diagram tool (dot 15.1.0 / d2 0.7.1); never a silent no-op (§17 PA-12 pattern)"
        ) from exc
    return DiagramRunOutcome(
        completed.returncode, completed.stdout, completed.stderr.decode("utf-8", "replace")
    )


_DOT_VERSION_RE = re.compile(r"version\s+(?P<v>\S+)")


def _tool_version(tool: str, binary: str, run: DiagramRunner) -> str:
    """The tool's version string — author-time provenance only (NOT identity-bearing, §O3).

    ``dot -V`` prints ``dot - graphviz version 15.1.0 (...)`` to STDERR; ``d2 --version`` prints
    ``0.7.1`` to STDOUT. Best-effort: falls back to the raw first line if the shape ever changes.
    """
    if tool == TOOL_DOT:
        out = run(binary, ("-V",), b"")
        text = out.stderr.strip() or out.stdout.decode("utf-8", "replace").strip()
        match = _DOT_VERSION_RE.search(text)
        return match.group("v") if match else text
    out = run(binary, ("--version",), b"")
    return out.stdout.decode("utf-8", "replace").strip() or out.stderr.strip()


def compile_diagram(
    spec: DiagramSpec, *, tool: str = TOOL_DOT, runner: DiagramRunner | None = None
) -> DiagramArtifact:
    """Compile a gated ``spec`` to deterministic SVG bytes with ``tool`` (§C C3). INERT LIBRARY.

    The caller (C4) has ALREADY run :func:`gate_diagram`; this function only draws. Steps mirror the
    plan: (1) emit ESCAPED source for ``tool`` (:func:`to_dot`/:func:`to_d2` — the injection
    defense, BLOCKER-2); (2) pre-store validate (``dot -Tcanon`` / d2's own compile) as a
    malformed-source catch only; (3) render to SVG via the pinned binary through the ``runner`` seam
    — a missing
    binary raises the loud :class:`DiagramToolUnavailableError`; (4) an illustrative spec already
    carries its baked stamp from step 1 (SERIOUS-1(a)); (5) return the bytes + ``(tool, version)``
    author-time provenance. The bytes are byte-deterministic for a given spec+tool, so C4's
    ``store.commit_asset(artifact.svg, subdir="diagrams", extension="svg")`` is content-addressed.

    ``tool`` defaults to ``"dot"`` (the C4 hard-pin / C5 default); ``runner`` defaults to the real
    subprocess seam. Raises :class:`DiagramCompileError` if the tool rejects the source or fails to
    render, :class:`DiagramToolUnavailableError` if the binary is absent.
    """
    if tool not in _TOOL_BINARY:
        raise DiagramCompileError(
            f"{DiagramCompileError.code}: unknown diagram tool {tool!r} "
            f"(expected one of {sorted(_TOOL_BINARY)})"
        )
    run = runner if runner is not None else _subprocess_diagram
    binary = _TOOL_BINARY[tool]
    if tool == TOOL_DOT:
        source_bytes = to_dot(spec).encode("utf-8")
        # (2) pre-store validate — MALFORMED-SOURCE catch ONLY, explicitly NOT the injection defense
        #     (escaping in to_dot is; -Tcanon errors only on a genuine syntax break).
        canon = run(binary, ("-Tcanon",), source_bytes)
        if canon.returncode != 0:
            raise DiagramCompileError(
                f"{DiagramCompileError.code}: `dot -Tcanon` rejected the emitted source "
                f"(exit {canon.returncode}): {canon.stderr.strip()}"
            )
        rendered = run(binary, ("-Tsvg",), source_bytes)
    else:  # TOOL_D2 — the single self-compile IS the malformed-source validation
        source_bytes = to_d2(spec).encode("utf-8")
        rendered = run(binary, ("-", "-"), source_bytes)
    if rendered.returncode != 0:
        raise DiagramCompileError(
            f"{DiagramCompileError.code}: `{tool}` failed to render the diagram "
            f"(exit {rendered.returncode}): {rendered.stderr.strip()}"
        )
    return DiagramArtifact(
        svg=rendered.stdout, tool=tool, version=_tool_version(tool, binary, run)
    )
