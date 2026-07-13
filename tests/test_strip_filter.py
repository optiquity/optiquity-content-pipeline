"""Step-27 tests: the pinned provenance-strip filter (§17 R-4) — the security-critical surface.

Coverage (plan step-27 acceptance):
- **Provably removes the provenance Attr for html5 (and epub3)** — at the AST level
  (`has_provenance` before/after) AND at the rendered-bytes level (no `data-*`/tier in the HTML).
- **Not reachable from Presentation config** — `should_strip` is a PURE function of the writer
  (its only parameter); the dispatcher's strip decision ignores `RenderInputs` entirely, so no
  client/Presentation lever can disable it.
- **Does NOT strip for md/docx internal record targets** — provenance is retained for the
  internal record (§17: consumed at the IR/AST layers, kept in the internal record).
- **Non-mutating**: the caller's AST (the persisted layer-3 record) is untouched by a public
  render — the strip returns a deep copy.
- The fact-anchor id is removed while a structural (part-Div) id survives.

pandoc is required for the rendered-bytes assertions; the guard fails loudly under CI-absent.
"""

import copy
import inspect
import json

import pytest

from pipeline import dispatch as D
from pipeline.filters.provenance_strip import (
    SAFE_WRITERS,
    has_provenance,
    should_strip,
    strip_provenance,
)
from pipeline.serialize import (
    is_ci,
    pandoc_available,
    pandoc_gate,
    run_pandoc,
    serialize_fitted,
)

_PANDOC_AVAILABLE = pandoc_available()


@pytest.fixture(autouse=True)
def _require_pandoc():
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize/strip pass MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the strip tests exercise the real serialize AST/writers")


_FITTED = {
    "grounding": {
        "f0": {
            "tier": "EXTRACTED",
            "source_instance_id": "repo-a",
            "source_repo": "github.com/x/a",
            "source_commit": "abc123",
            "traceability_anchor": ["src/x.py:9"],
            "scores_snapshot": {},
        }
    },
    "parts": [
        {
            "part-id": "a-0123456789abcdef~intro",
            "role": "intro",
            "packaging_hint": "in-document",
            "body": 'Rate [100/s]{.EXTRACTED data-fact="f0"} holds.',
        },
        {
            "part-id": "a-0123456789abcdef~outro",
            "role": "outro",
            "packaging_hint": "in-document",
            "body": "Plain outro, no claims.",
        },
    ],
}


def _ast():
    return serialize_fitted(_FITTED)[0].ast


# ---------------------------------------------------------------------------
# The removal property (AST level).
# ---------------------------------------------------------------------------


def test_strip_removes_all_provenance_from_ast():
    ast = _ast()
    assert has_provenance(ast) is True  # the full AST carries data-* kv + tier classes
    stripped = strip_provenance(ast)
    assert has_provenance(stripped) is False  # provably clean


def test_strip_is_non_mutating():
    ast = _ast()
    before = copy.deepcopy(ast)
    _ = strip_provenance(ast)
    assert ast == before  # the persisted record is untouched — strip is per-render, on a copy


def test_strip_removes_fact_anchor_kv_but_keeps_structural_part_id_class():
    stripped = strip_provenance(_ast())

    def _find(node, kind, out):
        if isinstance(node, dict):
            if node.get("t") == kind:
                out.append(node["c"][0])
            for v in node.values():
                _find(v, kind, out)
        elif isinstance(node, list):
            for v in node:
                _find(v, kind, out)
        return out

    spans = _find(stripped["blocks"], "Span", [])
    for _id, classes, kvs in spans:
        assert all(not k.startswith("data-") for k, _ in kvs)  # no provenance kv survives
        assert "EXTRACTED" not in classes and "INFERRED" not in classes  # no tier class
    divs = _find(stripped["blocks"], "Div", [])
    intro = next(a for a in divs if a[1] == ["intro"])  # the role class SURVIVES (structural)
    assert intro[0] == "intro"  # FIX 2: the structural role-slug id SURVIVES (a public anchor)
    assert all(not k.startswith("data-") for k, _ in intro[2])  # but data-part-id is gone

    # FIX 2 (converse): a fact-anchor Span carrying an id + provenance data- kv has its id
    # BLANKED — the structural-routing carve-out is data-part-id ONLY, never a true provenance
    # marker, so a fact anchor can never surface as a published id="…".
    anchored = {
        "meta": {},
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Span",
                        "c": [
                            [
                                "fact-anchor-1",
                                ["EXTRACTED"],
                                [["data-fact", "f0"], ["data-source-instance", "repo-a"]],
                            ],
                            [{"t": "Str", "c": "x"}],
                        ],
                    }
                ],
            }
        ],
    }
    anchor = _find(strip_provenance(anchored)["blocks"], "Span", [])[0]
    assert anchor[0] == ""  # the fact-anchor id is blanked — never a published id="…"
    assert "EXTRACTED" not in anchor[1]  # tier class gone
    assert all(not k.startswith("data-") for k, _ in anchor[2])  # provenance kv gone


# ---------------------------------------------------------------------------
# The security property: not reachable from Presentation config.
# ---------------------------------------------------------------------------


def test_should_strip_is_a_pure_function_of_the_writer_only():
    # The ONLY parameter is `writer` — there is no config/presentation/style hook to disable it.
    params = list(inspect.signature(should_strip).parameters)
    assert params == ["writer"]
    assert should_strip("html5") is True
    assert should_strip("epub3") is True
    # Fail-closed: the SAFE allowlist is the ONLY exemption; every writer outside it strips.
    assert SAFE_WRITERS == frozenset({"markdown", "json", "docx", "pptx", "pdf", "plain"})
    for safe in SAFE_WRITERS:
        assert should_strip(safe) is False, safe


def test_leaky_writer_family_strips_by_default_fail_closed():
    # Fail-closed (§3.3): every public writer NOT on the SAFE allowlist strips by DEFAULT — the
    # whole HTML/EPUB/slide family. None is in today's registry, but a one-file render-target
    # could add any one of them; an ALLOWLIST of html5/epub3 would fail-OPEN and silently publish
    # provenance for e.g. revealjs or bare `epub` (both empirically leak). The inversion closes it.
    leaky = ["revealjs", "s5", "slidy", "slideous", "dzslides", "html", "html4", "chunkedhtml",
             "epub"]
    for w in leaky:
        assert should_strip(w) is True, w
    # And the strip actually RUNS on the dispatch hand-off AST for a leaky writer (revealjs is
    # external — an internal target would be capability-infeasible), so a rendered revealjs
    # artifact carries no data-fact / no provenance kv / no tier class.
    out = D.dispatch(D.RenderTarget(writer="revealjs", side="external"), _ast())
    assert out.stripped is True
    assert has_provenance(out.payload_ast) is False
    rendered = run_pandoc(("-f", "json", "-t", "revealjs"), json.dumps(out.payload_ast)).stdout
    assert "data-fact" not in rendered
    assert "data-source-instance" not in rendered
    assert "EXTRACTED" not in rendered


def test_dispatch_strip_decision_ignores_render_inputs():
    # No RenderInputs value can turn the strip off for a public writer, nor on for an internal one.
    ast = _ast()
    html_t = D.RenderTarget(writer="html5", side="internal")
    md_t = D.RenderTarget(writer="markdown", side="internal")
    for inputs in (D.RenderInputs(), D.RenderInputs(flags=("--wrap=none",), variables={"x": "y"})):
        assert D.dispatch(html_t, ast, render_inputs=inputs).stripped is True
        assert D.dispatch(md_t, ast, render_inputs=inputs).stripped is False


def test_dispatch_html5_bytes_carry_no_provenance():
    ast = _ast()
    out = D.dispatch(D.RenderTarget(writer="html5", side="internal"), ast)
    assert out.stripped is True
    assert b"data-fact" not in out.output_bytes
    assert b"data-source-instance" not in out.output_bytes
    assert b"EXTRACTED" not in out.output_bytes


# ---------------------------------------------------------------------------
# The retention property: md/docx internal records keep provenance.
# ---------------------------------------------------------------------------


def test_md_internal_record_retains_provenance():
    ast = _ast()
    out = D.dispatch(D.RenderTarget(writer="markdown", side="internal"), ast)
    assert out.stripped is False
    assert b"data-fact" in out.output_bytes  # the internal record keeps the provenance


def test_docx_internal_record_is_not_stripped():
    # The docx writer drops unknown attrs itself (observed), and the strip filter never runs for
    # it — provenance is consumed at the IR/AST layers, retained in the internal record (§17 RI8).
    assert should_strip("docx") is False
    ast = _ast()
    out = D.dispatch(D.RenderTarget(writer="docx", side="internal"), ast)
    assert out.stripped is False and out.output_bytes and len(out.output_bytes) > 100


def test_epub3_external_payload_is_stripped_before_handoff():
    # epub3 publishes (external side) — its hand-off AST must carry no provenance (RI14).
    ast = _ast()
    out = D.dispatch(D.RenderTarget(writer="epub3", side="external"), ast)
    assert out.code == D.EXTERNAL_DEFERRED and out.stripped is True
    assert has_provenance(out.payload_ast) is False
