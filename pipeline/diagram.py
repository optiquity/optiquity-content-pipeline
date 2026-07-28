"""The ``{type=diagram}`` node/edge grammar + parser + HARD grounding gate (increment C, C1+C2).

INERT LIBRARY. This module is imported by NOTHING on the compose path yet: a ``{type=diagram}``
section still fails closed via ``sections.UnknownSectionTypeError`` (``"diagram"`` is not in
``SECTION_TYPES``) until the C4 flip wires the transform. C1 shipped the pure GRAMMAR half; C2
adds :func:`gate_diagram` — the HARD grounding gate — still with no I/O, no subprocess, and no
``dot``/``d2`` compile (C3). The gate is a LIBRARY function, called only by its own test today;
C4 runs it inside ``compose`` BEFORE any picture is drawn, so a diagram that would lie is REFUSED
before a single SVG byte exists. Later commits layer onto ``DiagramSpec``:

* C2 (THIS commit) runs the HARD grounding gate (:func:`gate_diagram`) over ``spec.edges``:
  per-edge REF-COUNT coverage (re-scanning each edge's verbatim ``citation_span`` with
  :func:`pipeline.ir.extract_fact_refs`) + the reused :func:`pipeline.ir.validate_refs` tier
  check + always-on endpoint integrity;
* C3 compiles the same ``DiagramSpec`` to a content-addressed SVG.

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
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from pipeline import ir

__all__ = [
    "POSTURE_GROUNDED",
    "POSTURE_ILLUSTRATIVE",
    "DiagramEdge",
    "DiagramGrammarError",
    "DiagramGroundingError",
    "DiagramNode",
    "DiagramSpec",
    "gate_diagram",
    "parse_diagram",
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
