"""Increment C, Commit C1 tests: `pipeline/diagram.py` — the INERT {type=diagram} node/edge
grammar + parser.

No LLM, no subprocess, no network — pure grammar. The suite pins:

- a valid grounded list parses (nodes, edges, fail-closed posture) — the plan's literal
  verification (`2 1 grounded '[routes]{.EXTRACTED data-fact="f1"}'`);
- the VERBATIM-SPAN contract (MINOR-3): the edge citation is stored byte-for-byte and re-scans
  cleanly through `ir.extract_fact_refs` — the exact reuse C2's gate depends on. A span with no
  `data-fact` (`[routes]{.EXTRACTED}`) is stored intact and yields ZERO refs (the BLOCKER-1 setup
  C2 must catch);
- FAIL-CLOSED posture (SERIOUS-2): absent OR unrecognized -> grounded; ONLY the exact token
  `illustrative` opts in, so a near-miss like `ILLUSTRATIVE` can never become a silent gate-bypass;
- every malformed vector REFUSES with a typed `DiagramGrammarError` (never a crash, never a silent
  drop): dangling edge, duplicate node id, missing field, partial/garbled list;
- the OPEN `attrs` carrier round-trips an arbitrary, read-only node attribute (D-preserving);
- INERTNESS: `{type=diagram}` still fails closed via `sections.UnknownSectionTypeError` — nothing
  added to `SECTION_TYPES`, no live path touched.
"""

from __future__ import annotations

import pytest

from pipeline import ir, sections
from pipeline.diagram import (
    POSTURE_GROUNDED,
    POSTURE_ILLUSTRATIVE,
    DiagramGrammarError,
    parse_diagram,
)

NODES = "- gw: Gateway\n- auth: Auth\n"
EDGE = '- gw -> auth [routes]{.EXTRACTED data-fact="f1"}\n'


def body(nodes: str = NODES, edges: str = EDGE, header: str = "") -> str:
    """A well-formed body with the named part swapped in — so each refusal isolates one defect."""
    return f"{header}nodes:\n{nodes}edges:\n{edges}"


GROUNDED = body()


# --------------------------------------------------------------------------- #
# A valid list parses (the plan's literal verification).                       #
# --------------------------------------------------------------------------- #


def test_grounded_list_parses():
    spec = parse_diagram(GROUNDED)
    assert len(spec.nodes) == 2
    assert len(spec.edges) == 1
    assert spec.posture == POSTURE_GROUNDED == "grounded"
    assert [n.id for n in spec.nodes] == ["gw", "auth"]
    assert [n.label for n in spec.nodes] == ["Gateway", "Auth"]
    edge = spec.edges[0]
    assert (edge.src_id, edge.dst_id) == ("gw", "auth")
    assert spec.style_ref is None


def test_multi_edge_list_parses():
    src = (
        "nodes:\n- a: A\n- b: B\n- c: C\n"
        'edges:\n- a -> b [x]{.EXTRACTED data-fact="f1"}\n'
        '- b -> c [y]{.EXTRACTED data-fact="f2"}\n'
    )
    spec = parse_diagram(src)
    assert len(spec.nodes) == 3
    assert len(spec.edges) == 2
    assert [(e.src_id, e.dst_id) for e in spec.edges] == [("a", "b"), ("b", "c")]


def test_blank_lines_and_indentation_tolerated():
    src = (
        "\nnodes:\n\n- gw: Gateway\n   - auth: Auth\n\nedges:\n"
        '- gw -> auth [routes]{.EXTRACTED data-fact="f1"}\n\n'
    )
    spec = parse_diagram(src)
    assert len(spec.nodes) == 2
    assert len(spec.edges) == 1


# --------------------------------------------------------------------------- #
# The verbatim-span contract (MINOR-3) — the exact reuse C2 depends on.        #
# --------------------------------------------------------------------------- #


def test_citation_span_stored_verbatim():
    span = parse_diagram(GROUNDED).edges[0].citation_span
    assert span == '[routes]{.EXTRACTED data-fact="f1"}'
    # Braces intact, fact-id NOT pre-extracted:
    assert span.startswith("[") and span.endswith("}")
    assert "data-fact" in span
    # The exact reuse C2's gate performs re-scans cleanly:
    refs = ir.extract_fact_refs(span, where="diagram edge gw->auth")
    assert [r.fact_id for r in refs] == ["f1"]
    assert refs[0].tier == "EXTRACTED"


def test_edge_display_label_derived_from_span():
    # A convenience only; the verbatim span remains the grounding source of truth.
    assert parse_diagram(GROUNDED).edges[0].label == "routes"


def test_bare_bracket_span_parses_ungated():
    # `[routes]` (no attr block) PARSES here; C2's gate is what refuses an uncited edge.
    spec = parse_diagram(body(edges="- gw -> auth [routes]\n"))
    assert spec.edges[0].citation_span == "[routes]"
    assert spec.edges[0].label == "routes"


def test_classed_span_without_fact_parses_but_yields_zero_refs():
    # The BLOCKER-1 setup: a span WITH a tier class but NO data-fact parses verbatim, and the
    # reused scanner finds zero refs — proving C2 will catch it as `grounding-uncovered`.
    spec = parse_diagram(body(edges="- gw -> auth [routes]{.EXTRACTED}\n"))
    assert spec.edges[0].citation_span == "[routes]{.EXTRACTED}"
    assert ir.extract_fact_refs(spec.edges[0].citation_span, where="e") == ()


def test_edge_without_citation_parses_ungated():
    spec = parse_diagram(body(edges="- gw -> auth\n"))
    assert spec.edges[0].citation_span is None
    assert spec.edges[0].label is None


# --------------------------------------------------------------------------- #
# Fail-closed posture (SERIOUS-2).                                             #
# --------------------------------------------------------------------------- #


def test_absent_posture_defaults_grounded():
    assert parse_diagram(GROUNDED).posture == POSTURE_GROUNDED


def test_explicit_illustrative_posture():
    assert parse_diagram(body(header="posture: illustrative\n")).posture == POSTURE_ILLUSTRATIVE


def test_explicit_grounded_posture():
    assert parse_diagram(body(header="posture: grounded\n")).posture == POSTURE_GROUNDED


@pytest.mark.parametrize("token", ["ILLUSTRATIVE", "Illustrative", "illustration", "sketch", "x"])
def test_unrecognized_posture_fails_closed_to_grounded(token):
    # SERIOUS-2: a near-miss of `illustrative` must NEVER become a gate-bypass; it resolves to
    # grounded so the strict gate applies.
    assert parse_diagram(body(header=f"posture: {token}\n")).posture == POSTURE_GROUNDED


def test_illustrative_parses_without_citations():
    # The parser never gates: an explicitly-illustrative spec with uncited edges parses fine.
    src = "posture: illustrative\nnodes:\n- a: A\n- b: B\nedges:\n- a -> b\n"
    spec = parse_diagram(src)
    assert spec.posture == POSTURE_ILLUSTRATIVE
    assert spec.edges[0].citation_span is None


# --------------------------------------------------------------------------- #
# The OPEN attribute carrier (D-preserving).                                   #
# --------------------------------------------------------------------------- #


def test_node_attrs_roundtrip_open_carrier():
    spec = parse_diagram(body(nodes="- gw: Gateway {group=data-plane}\n- auth: Auth\n"))
    assert spec.nodes[0].label == "Gateway"
    assert dict(spec.nodes[0].attrs) == {"group": "data-plane"}
    assert dict(spec.nodes[1].attrs) == {}  # a plain node carries an empty attrs map


def test_node_attr_quoted_value_with_spaces_kept_intact():
    # A quoted value survives whitespace as ONE opaque token (the seam D's badge citation uses).
    spec = parse_diagram(body(nodes='- gw: Gateway {group="data plane" shape=box}\n- auth: Auth\n'))
    assert dict(spec.nodes[0].attrs) == {"group": "data plane", "shape": "box"}


def test_node_attrs_are_read_only():
    spec = parse_diagram(body(nodes="- gw: Gateway {group=x}\n- auth: Auth\n"))
    with pytest.raises(TypeError):
        spec.nodes[0].attrs["group"] = "y"  # type: ignore[index]


# --------------------------------------------------------------------------- #
# Typed refusals — every malformed vector REFUSES (never a crash / silent drop).#
# --------------------------------------------------------------------------- #


REFUSAL_VECTORS = {
    # dangling edges (endpoint integrity)
    "dangling-dst": body(edges='- gw -> ghost [r]{.EXTRACTED data-fact="f1"}\n'),
    "dangling-src": body(edges='- ghost -> auth [r]{.EXTRACTED data-fact="f1"}\n'),
    # duplicate node id
    "duplicate-node-id": body(
        nodes="- gw: Gateway\n- gw: Other\n", edges='- gw -> gw [r]{.EXTRACTED data-fact="f1"}\n'
    ),
    # missing required field — nodes
    "node-empty-label": body(nodes="- gw:\n- auth: Auth\n"),
    "node-empty-id": body(nodes="- : Gateway\n- auth: Auth\n"),
    "node-missing-colon": body(nodes="- gw Gateway\n- auth: Auth\n"),
    "node-bad-id-punct": body(nodes="- gw!: Gateway\n- auth: Auth\n"),
    "node-bad-id-space": body(nodes="- g w: Gateway\n- auth: Auth\n"),
    # missing required field — edges
    "edge-missing-arrow": body(edges="- gw auth\n"),
    "edge-missing-dst": body(edges="- gw ->\n"),
    "edge-missing-src": body(edges="- -> auth\n"),
    "edge-bad-src-id": body(edges='- gw! -> auth [r]{.EXTRACTED data-fact="f1"}\n'),
    # partial / garbled list
    "edge-chained": body(edges="- gw -> auth -> auth\n"),
    "edge-garbled-citation": body(edges="- gw -> auth routes\n"),
    "list-item-before-section": "- stray: Node\n" + GROUNDED,
    "malformed-list-item": body(nodes="-gw: Gateway\n- auth: Auth\n"),
    "garbled-trailing-line": GROUNDED + "garbage line\n",
    "unknown-header": "widget: x\n" + GROUNDED,
    "section-trailing-text": "nodes: junk\n" + NODES + "edges:\n" + EDGE,
    "duplicate-section": "nodes:\n- gw: Gateway\nnodes:\n- auth: Auth\nedges:\n" + EDGE,
    "empty-nodes-section": "nodes:\nedges:\n" + EDGE,
    "empty-edges-section": "nodes:\n" + NODES + "edges:\n",
    "missing-nodes-section": "edges:\n" + EDGE,
    "missing-edges-section": "nodes:\n" + NODES,
    "posture-no-value": "posture:\n" + GROUNDED,
    "duplicate-posture": "posture: grounded\nposture: illustrative\n" + GROUNDED,
    # malformed node attribute block
    "attr-no-equals": body(nodes="- gw: Gateway {bad}\n- auth: Auth\n"),
    "attr-unbalanced-quote": body(nodes='- gw: Gateway {group="unclosed}\n- auth: Auth\n'),
}


@pytest.mark.parametrize("name", sorted(REFUSAL_VECTORS))
def test_malformed_list_refuses(name):
    with pytest.raises(DiagramGrammarError):
        parse_diagram(REFUSAL_VECTORS[name])


def test_refusal_is_typed_with_stable_code():
    with pytest.raises(DiagramGrammarError) as exc:
        parse_diagram(body(edges='- gw -> ghost [r]{.EXTRACTED data-fact="f1"}\n'))
    assert exc.value.code == "diagram-grammar-invalid"


def test_grammar_error_is_schema_violation_family():
    # The plan pins DiagramGrammarError to the SchemaViolation family so C4 can route it (ahead of
    # the generic `except ir.IRError`) to the single diagram-grounding-violation compose code.
    assert issubclass(DiagramGrammarError, ir.SchemaViolation)
    assert issubclass(DiagramGrammarError, ir.IRError)


# --------------------------------------------------------------------------- #
# Inertness — C1 is a library only; the type is not wired.                     #
# --------------------------------------------------------------------------- #


def test_diagram_type_still_fails_closed_in_sections():
    assert "diagram" not in sections.SECTION_TYPES
    with pytest.raises(sections.UnknownSectionTypeError):
        sections.parse_sections("## Architecture {type=diagram}\n\nbody\n")
