"""Increment C, Commit C1+C2 tests: `pipeline/diagram.py` — the INERT {type=diagram} node/edge
grammar + parser (C1) and the HARD grounding gate (C2).

No LLM, no subprocess, no network — pure grammar + the pure gate. The suite pins:

- a valid grounded list parses (nodes, edges, fail-closed posture) — the plan's literal
  verification (`2 1 grounded '[routes]{.EXTRACTED data-fact="f1"}'`);
- the VERBATIM-SPAN contract (MINOR-3): the edge citation is stored byte-for-byte and re-scans
  cleanly through `ir.extract_fact_refs` — the exact reuse C2's gate depends on. A span with no
  `data-fact` (`[routes]{.EXTRACTED}`) is stored intact and yields ZERO refs (the BLOCKER-1 setup
  C2 catches);
- FAIL-CLOSED posture (SERIOUS-2): absent OR unrecognized -> grounded; ONLY the exact token
  `illustrative` opts in, so a near-miss like `ILLUSTRATIVE` can never become a silent gate-bypass;
- every malformed vector REFUSES with a typed `DiagramGrammarError` (never a crash, never a silent
  drop): dangling edge, duplicate node id, missing field, partial/garbled list;
- the OPEN `attrs` carrier round-trips an arbitrary, read-only node attribute (D-preserving);
- C2 — the HARD grounding gate (`gate_diagram`): a grounded edge must resolve to >= 1 known,
  tier-honest fact or the document is REFUSED. Coverage is REF-COUNT, not span-presence
  (BLOCKER-1): a `[routes]{.EXTRACTED}` span with no `data-fact` REFUSES `grounding-uncovered`
  BEFORE the vacuous `validate_refs(())` can pass. The unknown-id / tier-dishonest refusals REUSE
  the SAME `ir.UnknownFactError` / `ir.TierViolation` the IR body gate raises (via the promoted
  `ir.validate_refs`). Endpoint integrity fires for BOTH postures; the illustrative bypass skips
  grounding ONLY for the explicit token;
- INERTNESS: `{type=diagram}` still fails closed via `sections.UnknownSectionTypeError` — nothing
  added to `SECTION_TYPES`; the gate is imported by this test only, no live path touched.
"""

from __future__ import annotations

import pytest

from pipeline import ir, sections
from pipeline.diagram import (
    POSTURE_GROUNDED,
    POSTURE_ILLUSTRATIVE,
    DiagramEdge,
    DiagramGrammarError,
    DiagramGroundingError,
    DiagramNode,
    DiagramSpec,
    gate_diagram,
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
# C2 — the HARD grounding gate (BLOCKER-1: coverage is REF-COUNT, not span-presence).#
# --------------------------------------------------------------------------- #

#: The §15 grounding ledger the gate checks refs against: {fact_id: {"tier": <TIER>}}.
LEDGER = {
    "f1": {"tier": "EXTRACTED"},
    "f2": {"tier": "EXTRACTED"},
    "f3": {"tier": "INFERRED"},
    "f4": {"tier": "AMBIGUOUS"},
}


def gated(edges: str, nodes: str = NODES, header: str = "") -> None:
    """Parse a well-formed body (one part swapped in) and run the gate against LEDGER."""
    gate_diagram(parse_diagram(body(nodes=nodes, edges=edges, header=header)), LEDGER)


def _spec(edges, *, nodes=(("gw", "Gateway"), ("auth", "Auth")), posture=POSTURE_GROUNDED):
    """A directly-constructed spec — bypasses `parse_diagram` so the gate's own always-on endpoint
    check (defense-in-depth) can be exercised on a dangling edge parse would have refused first."""
    return DiagramSpec(
        nodes=tuple(DiagramNode(id=node_id, label=label) for node_id, label in nodes),
        edges=tuple(edges),
        posture=posture,
    )


# ---- grounded PASSES ----


def test_grounded_single_edge_passes():
    assert gated(EDGE) is None  # the canonical [routes]{.EXTRACTED data-fact="f1"} — no raise


def test_grounded_multi_edge_list_passes():
    src = (
        "nodes:\n- a: A\n- b: B\n- c: C\n"
        'edges:\n- a -> b [x]{.EXTRACTED data-fact="f1"}\n'
        '- b -> c [y]{.EXTRACTED data-fact="f2"}\n'
    )
    assert gate_diagram(parse_diagram(src), LEDGER) is None  # both edges cited + honest


def test_grounded_honest_inferred_tier_passes():
    # The REUSED ir.validate_refs checks tier CONSISTENCY (ref tier == ledger tier), not level:
    # an INFERRED fact drawn AS INFERRED is tier-honest and PASSES — the SAME rule prose spans obey.
    assert gated('- gw -> auth [lead]{.INFERRED data-fact="f3"}\n') is None


# ---- (b) coverage REFUSES: ref-COUNT, never span-presence (BLOCKER-1 crown jewel) ----


def test_uncited_edge_no_span_refuses_grounding_uncovered():
    with pytest.raises(DiagramGroundingError) as exc:
        gated("- gw -> auth\n")
    assert exc.value.code == "grounding-uncovered"


def test_classed_span_without_fact_refuses_grounding_uncovered():
    # BLOCKER-1: a green-looking `[routes]{.EXTRACTED}` span that names NO fact yields () refs and
    # would sail through a vacuous validate_refs(()) — the ref-count guard REFUSES it first. This is
    # the exact case the initial plan's span-presence check did NOT catch.
    with pytest.raises(DiagramGroundingError) as exc:
        gated("- gw -> auth [routes]{.EXTRACTED}\n")
    assert exc.value.code == "grounding-uncovered"
    assert "gw->auth" in str(exc.value)  # the refusal names the offending edge


def test_bare_bracket_span_refuses_grounding_uncovered():
    # `[routes]` with no attr block -> () refs -> REFUSED (coverage is not "a bracket is present").
    with pytest.raises(DiagramGroundingError) as exc:
        gated("- gw -> auth [routes]\n")
    assert exc.value.code == "grounding-uncovered"


# ---- (a) tier-honesty REFUSES via the REUSED ir errors (one place of record) ----


def test_unknown_fact_id_refuses_with_reused_ir_error():
    with pytest.raises(ir.UnknownFactError) as exc:
        gated('- gw -> auth [x]{.EXTRACTED data-fact="f9"}\n')
    assert exc.value.code == "ir-unknown-fact"


def test_inferred_drawn_as_extracted_refuses_with_reused_ir_error():
    # f3 is INFERRED in the ledger; drawing it as `.EXTRACTED` is a tier promotion -> REFUSED.
    with pytest.raises(ir.TierViolation) as exc:
        gated('- gw -> auth [x]{.EXTRACTED data-fact="f3"}\n')
    assert exc.value.code == "ir-tier-violation"


def test_ambiguous_drawn_as_extracted_refuses():
    # The other tier-promotion direction: an AMBIGUOUS lead asserted as EXTRACTED fact -> REFUSED.
    with pytest.raises(ir.TierViolation):
        gated('- gw -> auth [x]{.EXTRACTED data-fact="f4"}\n')


def test_classless_grounded_ref_refuses_tier():
    # A `data-fact` with NO tier class is a class-less grounded ref -> TierViolation (reused).
    with pytest.raises(ir.TierViolation):
        gated('- gw -> auth [x]{data-fact="f1"}\n')


def test_gate_reuses_the_same_ir_machinery_as_the_body_gate():
    # The plan pins the reuse: the unknown-id / tier refusals raise the SAME ir error TYPES the IR
    # body gate raises, through the PROMOTED `ir.validate_refs` (MINOR-2 rename) the gate calls.
    assert "validate_refs" in ir.__all__ and callable(ir.validate_refs)
    with pytest.raises(ir.IRError):  # both reused refusals are ir.IRError-family
        gated('- gw -> auth [x]{.EXTRACTED data-fact="f9"}\n')


# ---- (c) endpoint integrity — BOTH postures, always (defense-in-depth over parse) ----


def test_dangling_endpoint_refuses_grounded():
    spec = _spec(
        [DiagramEdge(src_id="gw", dst_id="ghost", citation_span='[r]{.EXTRACTED data-fact="f1"}')]
    )
    with pytest.raises(DiagramGroundingError) as exc:
        gate_diagram(spec, LEDGER)
    assert "diagram-grounding:" in str(exc.value)


def test_dangling_endpoint_refuses_even_illustrative():
    # Endpoint integrity is NOT a grounding claim: an illustrative sketch is still held to it, so
    # the illustrative bypass can never smuggle an edge to an undeclared node.
    spec = _spec(
        [DiagramEdge(src_id="ghost", dst_id="auth", citation_span=None)],
        posture=POSTURE_ILLUSTRATIVE,
    )
    with pytest.raises(DiagramGroundingError):
        gate_diagram(spec, LEDGER)


# ---- illustrative bypass: skips (a)+(b) ONLY, and ONLY for the explicit token ----


def test_illustrative_uncited_edges_pass_the_gate():
    # An explicitly-illustrative spec with fully uncited edges PASSES (grounding is bypassed);
    # posture stays the flag C3 reads to stamp the SVG and C4 reads to mark the alt-text.
    spec = parse_diagram("posture: illustrative\nnodes:\n- a: A\n- b: B\nedges:\n- a -> b\n")
    assert spec.posture == POSTURE_ILLUSTRATIVE
    assert gate_diagram(spec, LEDGER) is None  # no raise despite the uncited edge


def test_illustrative_bypass_is_only_the_explicit_token():
    # SERIOUS-2: a near-miss `ILLUSTRATIVE` resolved to grounded in C1, so it can NEVER become a
    # silent gate-bypass — its uncited edge REFUSES.
    spec = parse_diagram("posture: ILLUSTRATIVE\nnodes:\n- a: A\n- b: B\nedges:\n- a -> b\n")
    assert spec.posture == POSTURE_GROUNDED
    with pytest.raises(DiagramGroundingError) as exc:
        gate_diagram(spec, LEDGER)
    assert exc.value.code == "grounding-uncovered"


def test_absent_posture_is_gated_not_bypassed():
    # SERIOUS-2: no posture header -> grounded -> the uncited edge REFUSES (never a silent bypass).
    spec = parse_diagram("nodes:\n- a: A\n- b: B\nedges:\n- a -> b\n")
    assert spec.posture == POSTURE_GROUNDED
    with pytest.raises(DiagramGroundingError):
        gate_diagram(spec, LEDGER)


def test_grounding_error_is_ir_error_family():
    # C4 routes it (via a dedicated except placed AHEAD of the generic `except ir.IRError`) to the
    # single diagram-grounding-violation compose code.
    assert issubclass(DiagramGroundingError, ir.IRError)
    assert DiagramGroundingError.code == "grounding-uncovered"


# --------------------------------------------------------------------------- #
# Inertness — C1+C2 are a library only; the type is not wired, the gate is     #
# imported by this test only.                                                  #
# --------------------------------------------------------------------------- #


def test_diagram_type_still_fails_closed_in_sections():
    assert "diagram" not in sections.SECTION_TYPES
    with pytest.raises(sections.UnknownSectionTypeError):
        sections.parse_sections("## Architecture {type=diagram}\n\nbody\n")
