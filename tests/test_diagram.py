"""Increment C, Commit C1+C2+C3 tests: `pipeline/diagram.py` — the INERT {type=diagram} node/edge
grammar + parser (C1), the HARD grounding gate (C2), and the dot/d2 compiler (C3).

C1+C2 are pure (no LLM/subprocess/network); C3 shells to the REAL `dot`/`d2` when they are installed
(no LLM, no network) — but both are OPTIONAL, so each generation test SKIPS when its tool is absent
(`requires_dot`/`requires_d2`), never failing a tool-less CI (the ratified "works without graphviz"
contract; tool-ABSENCE degrades to the text-alt, proven in `test_diagram_styles.py`). Pins:

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
- C3 — the dot/d2 compiler (`to_dot`/`to_d2`/`compile_diagram`): a gated spec compiles to
  BYTE-DETERMINISTIC SVG for both tools; a tool switch changes bytes (hence the content hash);
  BLOCKER-2 — a node/edge label full of `"`, a newline, `->`, `{`, `;` renders as LITERAL text and
  the compiled graph keeps EXACTLY the spec's node/edge count (no injected node/edge) for BOTH
  tools; SERIOUS-1(a) — an illustrative spec bakes the reader-visible stamp into the SVG; a
  malformed source is caught by `-Tcanon` (`DiagramCompileError`) and a missing binary raises the
  loud `DiagramToolUnavailableError`; the SVG bytes store cleanly under `assets/diagrams/<hash>.svg`
  via `commit_asset` (the C4 contract, exercised here);
- THE C4 FLIP: `diagram` is now IN `SECTION_TYPES`, so `sections.parse_sections` accepts a
  `{type=diagram}` heading (no longer `UnknownSectionTypeError`) — the atomic flip added the type
  and wired the compose parse->gate->compile->store->embed transform in the SAME commit (the
  end-to-end wiring lives in `tests/test_compose.py`).
"""

from __future__ import annotations

import re
import subprocess

import pytest

# The C3 compiler tests SHELL to the real `dot`/`d2`. Both binaries are OPTIONAL (a tool-less host
# degrades a requested diagram to its text-alt — the ratified "works without graphviz" contract), so
# a generation test SKIPS when its tool is absent rather than failing CI; the tool-ABSENCE behavior
# itself is proven tool-lessly by `test_missing_binary_raises_tool_unavailable` + the compose
# degradation tests in `test_diagram_styles.py`. The skip markers are the SINGLE canonical copy in
# `tests/conftest.py` (imported here and in every other tool-driving module).
from conftest import requires_d2, requires_dot  # noqa: E402

from pipeline import diagram, ir, sections
from pipeline.canonical import sha256_hex
from pipeline.diagram import (
    ILLUSTRATIVE_STAMP,
    POSTURE_GROUNDED,
    POSTURE_ILLUSTRATIVE,
    DiagramArtifact,
    DiagramCompileError,
    DiagramEdge,
    DiagramGrammarError,
    DiagramGroundingError,
    DiagramNode,
    DiagramSpec,
    DiagramToolUnavailableError,
    compile_diagram,
    gate_diagram,
    parse_diagram,
    to_d2,
    to_dot,
)
from pipeline.store import WorkspaceStore

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
# The C4 FLIP — `diagram` is now a live, gated section type (the atomic flip    #
# added it to SECTION_TYPES + wired the compose transform in the SAME commit).  #
# --------------------------------------------------------------------------- #


def test_diagram_type_is_now_a_live_section_type():
    # C4 ATOMIC FLIP: `diagram` is IN the carrier and `parse_sections` no longer refuses it — the
    # compose transform (test_compose.py) is what gates + compiles + rewrites the section.
    assert "diagram" in sections.SECTION_TYPES
    parsed = sections.parse_sections("## Architecture {type=diagram}\n\nbody\n")
    assert parsed[0].type == "diagram"


# --------------------------------------------------------------------------- #
# C3 — the dot/d2 compiler (real dot 15.1.0 / d2 0.7.1; no LLM, no network).   #
# --------------------------------------------------------------------------- #

TOOLS = ["dot", "d2"]
#: Per-tool parametrization that SKIPS the leg whose binary is absent (each tool is independently
#: optional), so a host with only `dot` still runs the `dot` legs and skips the `d2` ones.
TOOL_PARAMS = [
    pytest.param("dot", marks=requires_dot),
    pytest.param("d2", marks=requires_d2),
]


def _dot_plain_counts(spec: DiagramSpec) -> tuple[int, int]:
    """Re-run `dot -Tplain` on the emitted source; count top-level node/edge RECORDS. `-Tplain`
    emits exactly one `node `/`edge ` line per real element regardless of label content (labels are
    quoted on the same line), so an injected element would show as an extra line — the authoritative
    BLOCKER-2 count."""
    plain = subprocess.run(
        ["dot", "-Tplain"], input=to_dot(spec).encode("utf-8"), capture_output=True, check=True
    ).stdout.decode("utf-8")
    nodes = sum(1 for line in plain.splitlines() if line.startswith("node "))
    edges = sum(1 for line in plain.splitlines() if line.startswith("edge "))
    return nodes, edges


def _d2_shape_count(svg: bytes) -> int:
    """Count d2 shapes in the rendered SVG — one `class="shape"` per real node (the plan's d2
    invariant: shape count == spec node count; an injected shape would bump it)."""
    return svg.count(b'class="shape"')


# ---- deterministic compile + tool switch ----


@pytest.mark.parametrize("tool", TOOL_PARAMS)
def test_grounded_spec_compiles_to_byte_deterministic_svg(tool):
    spec = parse_diagram(GROUNDED)
    first = compile_diagram(spec, tool=tool)
    second = compile_diagram(spec, tool=tool)
    assert isinstance(first, DiagramArtifact)
    assert first.svg == second.svg  # byte-identical across two runs (content-addressable)
    assert first.svg[:5] == b"<?xml"  # it is an SVG document
    assert first.tool == tool


@requires_dot
@requires_d2
def test_compile_records_tool_and_version_provenance():
    dot = compile_diagram(parse_diagram(GROUNDED), tool="dot")
    d2 = compile_diagram(parse_diagram(GROUNDED), tool="d2")
    # (tool, version) is author-time provenance (NOT identity-bearing, §O3): assert a REAL version
    # string was recorded, robustly across environments — NOT a hard pin on `15.`/`0.7` (which would
    # break on any other distro `dot`/`d2`). The version churns the SVG content hash, never an id.
    assert dot.tool == "dot" and dot.version[:1].isdigit() and "." in dot.version
    assert d2.tool == "d2" and d2.version[:1].isdigit() and "." in d2.version


@requires_dot
@requires_d2
def test_tool_switch_changes_bytes_hence_hash():
    spec = parse_diagram(GROUNDED)
    dot = compile_diagram(spec, tool="dot")
    d2 = compile_diagram(spec, tool="d2")
    assert dot.svg != d2.svg  # different engine -> different bytes
    assert sha256_hex(dot.svg) != sha256_hex(d2.svg)  # -> different content hash (identity)


@requires_dot
def test_compile_defaults_to_dot():
    assert compile_diagram(parse_diagram(GROUNDED)).tool == "dot"  # amendment pin


# ---- BLOCKER-2: label injection is neutralized (EXACT node/edge count, BOTH tools) ----

#: A directly-constructed HOSTILE spec — a node label AND an edge label each packed with every
#: dot/d2 metacharacter the task names (`"`, a real newline, `->`, `{`, `;`), plus a would-be
#: injected node/edge. A parsed body cannot carry a newline inside a label (the grammar is
#: line-oriented), so this is built straight from the dataclasses to prove the ESCAPING — not the
#: parser — is the injection defense, even for a spec that never came from `parse_diagram`.
_HOSTILE_NODE_LABEL = 'Gateway"]; injnode_a -> injnode_b [label="z {  ; \n injline: pwned\n x -> y'
_HOSTILE_EDGE_LABEL = 'routes"]; injedge_a -> injedge_b [label="q {  ; \n more'


def _hostile_spec() -> DiagramSpec:
    return DiagramSpec(
        nodes=(
            DiagramNode(id="n0", label=_HOSTILE_NODE_LABEL),
            DiagramNode(id="n1", label="Auth"),
        ),
        edges=(
            DiagramEdge(
                src_id="n0",
                dst_id="n1",
                citation_span='[routes]{.EXTRACTED data-fact="f1"}',
                label=_HOSTILE_EDGE_LABEL,
            ),
        ),
        posture=POSTURE_GROUNDED,
    )


@requires_dot
def test_injection_dot_keeps_exact_node_edge_count():
    # BLOCKER-2 (dot): the escaped source renders every metacharacter as literal label text; the
    # canonical graph has EXACTLY 2 nodes + 1 edge — no injected node, no injected edge.
    spec = _hostile_spec()
    assert _dot_plain_counts(spec) == (2, 1)
    svg = compile_diagram(spec, tool="dot").svg
    assert b"pwned" in svg  # the hostile text survives as LITERAL label content
    assert b"injnode_a" in svg  # the would-be-injected token is present only as label text...
    # ...never as a graph node: the plain-format node names are exactly n0 and n1.
    plain = subprocess.run(
        ["dot", "-Tplain"], input=to_dot(spec).encode("utf-8"), capture_output=True, check=True
    ).stdout.decode("utf-8")
    node_names = {line.split()[1] for line in plain.splitlines() if line.startswith("node ")}
    assert node_names == {"n0", "n1"}


@requires_d2
def test_injection_d2_keeps_exact_shape_count():
    # BLOCKER-2 (d2): the escaped source renders as literal text; the SVG has EXACTLY 2 shapes
    # (one per real node) — no injected shape/connection.
    spec = _hostile_spec()
    svg = compile_diagram(spec, tool="d2").svg
    assert _d2_shape_count(svg) == 2  # == spec node count; an injected shape would bump this
    assert b"pwned" in svg  # the hostile text survives as literal label content


@requires_dot
@requires_d2
def test_injection_via_parsed_body_dot_and_d2():
    # The plan's literal-verification vector, parsed from a real body: a node label carrying
    # `"`, `]`, `;`, `->`, `[label="` renders as text; both tools keep exactly 2 nodes / 1 edge.
    body_src = (
        'nodes:\n- n0: Gateway" ]; injected_a -> injected_b [label="pwned\n'
        "- n1: Auth\n"
        'edges:\n- n0 -> n1 [x]{.EXTRACTED data-fact="f1"}\n'
    )
    spec = parse_diagram(body_src)
    assert (len(spec.nodes), len(spec.edges)) == (2, 1)
    assert _dot_plain_counts(spec) == (2, 1)  # dot: no injected_a -> injected_b edge
    assert _d2_shape_count(compile_diagram(spec, tool="d2").svg) == 2  # d2: no injected shape


def test_escape_label_leaves_no_unescaped_quote():
    # The core invariant behind BLOCKER-2: after escaping, no `"` can close the wrapping quote and
    # no control char survives — so a metacharacter can only ever be inert literal text.
    escaped = diagram._escape_label('a"b\\c\nd\te ->{;')
    # every `"` is preceded by a `\`; no raw newline/tab remains.
    assert '\n' not in escaped and '\t' not in escaped
    for i, ch in enumerate(escaped):
        if ch == '"':
            assert escaped[i - 1] == "\\"


# ---- SERIOUS-1(a): the illustrative stamp is baked into the SVG ----

_STAMP_FRAGMENTS = (b"illustrative", b"not source", b"checked")


def _illustrative_spec() -> DiagramSpec:
    return parse_diagram("posture: illustrative\nnodes:\n- a: A\n- b: B\nedges:\n- a -> b\n")


@pytest.mark.parametrize("tool", TOOL_PARAMS)
def test_illustrative_spec_bakes_stamp_into_svg(tool):
    # SERIOUS-1(a): an illustrative diagram's SVG carries the reader-visible marker. (Asserted on
    # robust ASCII fragments — dot entity-encodes the hyphen as `not source&#45;checked`.)
    svg = compile_diagram(_illustrative_spec(), tool=tool).svg
    for fragment in _STAMP_FRAGMENTS:
        assert fragment in svg, f"{tool} SVG missing stamp fragment {fragment!r}"


@pytest.mark.parametrize("tool", TOOL_PARAMS)
def test_grounded_spec_carries_no_stamp(tool):
    # A grounded diagram makes a source claim and must NOT wear the illustrative marker.
    svg = compile_diagram(parse_diagram(GROUNDED), tool=tool).svg
    assert b"illustrative" not in svg


def test_illustrative_source_cannot_be_emitted_without_the_stamp():
    # The bake is non-optional: it lives in the emitted SOURCE for both tools.
    assert ILLUSTRATIVE_STAMP in to_dot(_illustrative_spec())
    assert ILLUSTRATIVE_STAMP in to_d2(_illustrative_spec())
    assert ILLUSTRATIVE_STAMP not in to_dot(parse_diagram(GROUNDED))


# ---- malformed source + missing binary + unknown tool ----


@requires_dot
def test_broken_source_is_caught_by_canon(monkeypatch):
    # The pre-store `-Tcanon` catch (malformed-source ONLY): a directly-broken source refuses. In
    # practice the escaped emitter never produces one — this is defense-in-depth, forced here.
    monkeypatch.setattr(diagram, "to_dot", lambda spec: "digraph G { a -> }")
    with pytest.raises(DiagramCompileError) as exc:
        compile_diagram(parse_diagram(GROUNDED), tool="dot")
    assert exc.value.code == "diagram-compile-failed"


def test_missing_binary_raises_tool_unavailable():
    # A bogus binary path -> a LOUD refusal (never a silent empty SVG), the PA-12 presence gate.
    def bogus_runner(binary, args, stdin):
        return diagram._subprocess_diagram("no-such-diagram-binary-xyz", args, stdin)

    with pytest.raises(DiagramToolUnavailableError) as exc:
        compile_diagram(parse_diagram(GROUNDED), tool="dot", runner=bogus_runner)
    assert exc.value.code == "diagram-tool-unavailable"


def test_unknown_tool_refuses():
    with pytest.raises(DiagramCompileError):
        compile_diagram(parse_diagram(GROUNDED), tool="mermaid")


# ---- the store contract: SVG bytes land under assets/diagrams/<hash>.svg (C4 uses this) ----


@requires_dot
def test_compiled_svg_stores_content_addressed_under_assets_diagrams(tmp_path):
    spec = parse_diagram(GROUNDED)
    artifact = compile_diagram(spec, tool="dot")
    ws = WorkspaceStore(tmp_path / "ws")
    path = ws.commit_asset(artifact.svg, subdir="diagrams", extension="svg")
    # assets/diagrams/<64hex>.svg — a PATTERN (MINOR-4: never a frozen golden; a tool upgrade
    # re-mints a new hash by design).
    assert path.parent == ws.root / "assets" / "diagrams"
    assert re.fullmatch(r"[0-9a-f]{64}\.svg", path.name)
    assert path.stem == sha256_hex(artifact.svg)
    assert path.read_bytes() == artifact.svg
    # idempotent re-commit of identical bytes -> same path, no raise (content-addressed no-op).
    assert ws.commit_asset(artifact.svg, subdir="diagrams", extension="svg") == path


@requires_dot
def test_same_spec_recompiles_to_the_same_hash():
    # Determinism -> stable identity: a re-compile of the same spec yields the same content hash.
    spec = parse_diagram(GROUNDED)
    assert sha256_hex(compile_diagram(spec, tool="dot").svg) == sha256_hex(
        compile_diagram(spec, tool="dot").svg
    )


def test_diagram_is_a_live_section_type_after_the_flip():
    # C4 flipped it on: the C1-C3 library is now reachable through the compose transform.
    assert "diagram" in sections.SECTION_TYPES
