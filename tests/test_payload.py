"""Step-29 tests: the layer-3 contract payload (§17 RI14) — `pipeline/payload.py`.

The zero-provenance guarantee is proven two ways: on a HAND-BUILT provenance-bearing AST (pandoc
free, always runs) AND on a REAL serialized AST (pandoc-guarded like `tests/test_serialize.py`).

Covers the plan step-29 acceptance for the payload:

- **all FIVE RI14 components** — AST, reproducibility sidecar, part structure, metadata bag,
  language — present for a `side: external` target;
- **ZERO provenance** — the payload AST carries no `data-*` kv, no tier class, no fact-anchor id
  (`has_provenance` False, and the whole payload JSON greps clean of `data-fact`/tier/`data-`);
- **explicit `sequence`** in the part structure (the external actor reassembles from stated order);
- **conditional extension-append naming** (§7.4) for the deliverable and each part file;
- **external-only** — an internal target is refused (§21.5);
- **no SSOT import** (INV-CORRECTNESS, §22.7).
"""

from __future__ import annotations

import ast as ast_mod
import json
from pathlib import Path

import pytest

from pipeline.dispatch import RenderTarget
from pipeline.filters.provenance_strip import has_provenance
from pipeline.ir import PANDOC_API_VERSION
from pipeline.payload import PayloadError, build_payload, part_structure
from pipeline.serialize import (
    READER_PIN,
    is_ci,
    pandoc_available,
    pandoc_gate,
    pin_bundle,
    serialize_fitted,
    serialize_inputs_preimage,
)

_PANDOC_AVAILABLE = pandoc_available()

ART = "a-0123456789abcdef"
DELIV = "a-0123456789abcdef.linkedin.en.epub.plain"
EXTERNAL = RenderTarget(writer="epub3", side="external", engine="", reference_doc="")

_LEDGER = {
    "f0": {
        "tier": "EXTRACTED",
        "source_instance_id": "repo-a",
        "source_commit": "abc123def456",
        "traceability_anchor": ["src/limits.py:42"],
    },
    "f1": {
        "tier": "INFERRED",
        "source_instance_id": "repo-b",
        "source_commit": None,
        "traceability_anchor": [],
    },
}


@pytest.fixture
def require_pandoc():
    """PA-12 guard (only the real-AST tests request it): absent + CI ⇒ FAIL; absent local ⇒ skip."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize pass MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the real-AST payload test requires the pinned binary")


def _parts_fitted():
    return {
        "grounding": _LEDGER,
        "metadata": {"campaign": "q3", "client": "acme"},
        "parts": [
            {
                "part-id": f"{ART}~intro",
                "role": "intro",
                "packaging_hint": "in-document",
                "body": 'Rate [100 req/s]{.EXTRACTED data-fact="f0"} holds.',
            },
            {
                "part-id": f"{ART}~body",
                "role": "body",
                "packaging_hint": "standalone",
                "body": 'See [the note]{.INFERRED data-fact="f1"}.',
            },
        ],
    }


def _provenance_ast():
    """A hand-built Pandoc AST carrying the full RI8 provenance signature (no pandoc needed)."""
    return {
        "pandoc-api-version": list(PANDOC_API_VERSION),
        "meta": {},
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Span",
                        "c": [
                            [
                                "anchor-f0",
                                ["EXTRACTED"],
                                [
                                    ["data-fact", "f0"],
                                    ["data-source-instance", "repo-a"],
                                    ["data-source-commit", "abc123def456"],
                                    ["data-traceability", "src/limits.py:42"],
                                ],
                            ],
                            [{"t": "Str", "c": "100req/s"}],
                        ],
                    }
                ],
            }
        ],
    }


def _pins():
    pre = serialize_inputs_preimage(
        render_target={"id": "epub", "writer": "epub3", "side": "external", "reader": READER_PIN},
        render_inputs={"flags": [], "variables": {}, "assets": [], "engine": ""},
    )
    return pin_bundle(pre)


def _build(ast, fitted_ir):
    return build_payload(
        ast=ast,
        deliverable_id=DELIV,
        render_target=EXTERNAL,
        pin_bundle=_pins(),
        fitted_ir=fitted_ir,
        requested_output_types=["epub"],
        extension="epub",
    )


# ---------------------------------------------------------------------------
# All five RI14 components + the id projection.
# ---------------------------------------------------------------------------


def test_payload_has_all_five_ri14_components():
    payload = _build(_provenance_ast(), _parts_fitted())
    assert set(payload) == {"ast", "reproducibility", "parts", "metadata", "language"}
    repro = payload["reproducibility"]
    assert repro["deliverable_id"] == DELIV
    assert repro["artifact_id"] == ART  # the bare artifact root
    assert repro["fitted_id"] == "a-0123456789abcdef.linkedin.en"  # deliverable minus out/pres
    assert repro["requested_output_types"] == ["epub"]
    assert repro["writer"] == "epub3" and repro["pandoc_version"] == "3.10"
    assert repro["pins"] == _pins()
    assert payload["metadata"] == {"campaign": "q3", "client": "acme"}  # opaque, untouched
    assert payload["language"] == "en"  # already localized — the actor never re-localizes


def test_part_structure_carries_explicit_sequence_and_filenames():
    parts = part_structure(_parts_fitted(), extension="epub")
    assert [p["sequence"] for p in parts] == [1, 2]  # EXPLICIT order, not implicit position
    assert parts[0]["part_id"] == f"{ART}~intro" and parts[0]["role"] == "intro"
    assert parts[0]["packaging_hint"] == "in-document"
    assert parts[0]["filename"] == f"{ART}~intro.epub"  # §7.4 conditional extension-append
    assert parts[1]["filename"] == f"{ART}~body.epub"


def test_flat_fitted_ir_has_no_part_structure():
    assert part_structure({"grounding": {}, "body": "x"}, extension="epub") == []


def test_conditional_extension_append_names_the_deliverable_file():
    repro = _build(_provenance_ast(), {"body": "x"})["reproducibility"]
    assert repro["filename"] == f"{DELIV}.epub"


# ---------------------------------------------------------------------------
# ZERO provenance — the security guarantee (§17 RI14).
# ---------------------------------------------------------------------------


def test_synthetic_provenance_ast_is_fully_stripped():
    payload = _build(_provenance_ast(), {"body": "x"})
    assert has_provenance(payload["ast"]) is False
    blob = json.dumps(payload)
    for token in ("data-fact", "data-source", "EXTRACTED", "INFERRED", "data-"):
        assert token not in blob, f"provenance token {token!r} leaked into the external payload"


def test_real_serialized_ast_payload_has_zero_provenance(require_pandoc):
    # A provenance-bearing fixture → real serialize → the external payload greps clean (verify 7).
    units = serialize_fitted(_parts_fitted())
    assert has_provenance(units[0].ast) is True  # the source AST DOES carry provenance
    payload = _build(units[0].ast, _parts_fitted())
    assert has_provenance(payload["ast"]) is False
    blob = json.dumps(payload)
    for token in ("data-fact", "data-source", "EXTRACTED", "INFERRED", "data-"):
        assert token not in blob


# ---------------------------------------------------------------------------
# C10 — the citeproc REQUIREMENT in the reproducibility sidecar (§17 R-4 family).
# ---------------------------------------------------------------------------

_CSL = ("styles/ieee.csl", "sha256:deadbeef")


def _citing_ast():
    """A hand-built citing AST (pandoc-free): a pre-citeproc `Cite` node in the body +
    `meta.references` (a MetaMap — no `Attr` — so the provenance strip's attr-walk never touches
    it), PLUS a provenance-bearing Span so the unconditional strip demonstrably runs. There is NO
    `data-cites` span: citeproc resolves on the ACTOR's side, so the payload carries the UNRESOLVED
    Cite (why `has_provenance` never trips on a citing hand-off AST)."""
    return {
        "pandoc-api-version": list(PANDOC_API_VERSION),
        "meta": {
            "references": {
                "t": "MetaList",
                "c": [
                    {
                        "t": "MetaMap",
                        "c": {
                            "id": {"t": "MetaString", "c": "s0"},
                            "type": {"t": "MetaString", "c": "webpage"},
                            "title": {"t": "MetaInlines", "c": [{"t": "Str", "c": "Acme"}]},
                        },
                    }
                ],
            }
        },
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Cite",
                        "c": [
                            [
                                {
                                    "citationId": "s0",
                                    "citationPrefix": [],
                                    "citationSuffix": [],
                                    "citationMode": {"t": "AuthorInText"},
                                    "citationNoteNum": 0,
                                    "citationHash": 0,
                                }
                            ],
                            [{"t": "Str", "c": "[@s0]"}],
                        ],
                    },
                    {  # a provenance-bearing Span — PROVES the unconditional strip runs
                        "t": "Span",
                        "c": [
                            ["anchor-f0", ["EXTRACTED"], [["data-fact", "f0"]]],
                            [{"t": "Str", "c": "100req/s"}],
                        ],
                    },
                ],
            }
        ],
    }


def _find_cites(node):
    """Every `Cite` node anywhere in `node` — a walk (not `has_citations`), so the test asserts the
    ACTUAL nodes survive the strip, not merely the boolean."""
    out = []
    if isinstance(node, dict):
        if node.get("t") == "Cite":
            out.append(node)
        for v in node.values():
            out.extend(_find_cites(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_find_cites(v))
    return out


def _build_citing(*, citeproc_enabled, csl, ast=None):
    return build_payload(
        ast=_citing_ast() if ast is None else ast,
        deliverable_id=DELIV,
        render_target=EXTERNAL,
        pin_bundle=_pins(),
        fitted_ir={"body": "x"},
        requested_output_types=["epub"],
        extension="epub",
        citeproc_enabled=citeproc_enabled,
        csl=csl,
    )


def test_citing_external_payload_carries_citeproc_requirement_with_csl():
    citeproc = _build_citing(citeproc_enabled=True, csl=_CSL)["reproducibility"]["citeproc"]
    assert citeproc["enabled"] is True
    assert citeproc["csl"] == {"path": _CSL[0], "content_hash": _CSL[1]}  # path+hash, a REQUIREMENT
    assert citeproc["pandoc_version"] == "3.10"  # the pinned pandoc the actor must honor


def test_citing_external_payload_default_style_has_null_csl():
    # citeproc enabled but NO csl lever → the writer's default author-date; `csl` is None.
    citeproc = _build_citing(citeproc_enabled=True, csl=None)["reproducibility"]["citeproc"]
    assert citeproc["enabled"] is True and citeproc["csl"] is None


def test_citing_external_payload_ast_keeps_references_and_cite_and_passes_failclosed_guard():
    # The strip runs UNCONDITIONALLY (fail-closed): provenance is removed, but `meta.references`
    # (a MetaMap — no Attr) and the pre-citeproc `Cite` nodes SURVIVE, and `has_provenance` is
    # False (no `data-cites` exists — citeproc runs on the actor's side), so the guard never trips.
    src = _citing_ast()
    assert has_provenance(src) is True  # the source AST carries provenance (the Span) …
    assert _find_cites(src["blocks"])  # … and a Cite
    out_ast = _build_citing(citeproc_enabled=True, csl=_CSL, ast=src)["ast"]
    assert has_provenance(out_ast) is False  # the fail-closed guard held (build did not raise)
    assert out_ast["meta"]["references"] == src["meta"]["references"]  # references survive intact
    cites = _find_cites(out_ast["blocks"])
    assert len(cites) == 1 and cites[0]["c"][0][0]["citationId"] == "s0"  # the Cite survives


def test_non_citing_external_payload_omits_citeproc_block_backward_compat():
    # OMIT-WHEN-ABSENT: a non-citing external payload gains NO `citeproc` key → the reproducibility
    # sidecar is byte-identical to a pre-C10 payload. A csl lever on a NON-citing render is dropped
    # too (mirroring dispatch content-gating `--csl` WITH `--citeproc`, never alone).
    plain = _build(_provenance_ast(), {"body": "x"})  # default citeproc_enabled=False
    assert "citeproc" not in plain["reproducibility"]
    with_csl = _build_citing(citeproc_enabled=False, csl=_CSL, ast=_provenance_ast())
    assert "citeproc" not in with_csl["reproducibility"]
    assert with_csl["reproducibility"] == plain["reproducibility"]  # byte-identical sidecar


# ---------------------------------------------------------------------------
# External-only + loud on a bad shape (§21.5 / §3.1).
# ---------------------------------------------------------------------------


def test_internal_target_is_refused():
    with pytest.raises(PayloadError):
        build_payload(
            ast=_provenance_ast(),
            deliverable_id=DELIV,
            render_target=RenderTarget(writer="docx", side="internal"),
            pin_bundle=_pins(),
            fitted_ir={"body": "x"},
            requested_output_types=["docx"],
            extension="docx",
        )


def test_non_deliverable_id_is_refused():
    with pytest.raises(PayloadError):
        build_payload(
            ast=_provenance_ast(),
            deliverable_id="a-0123456789abcdef.linkedin.en",  # fitted, not deliverable
            render_target=EXTERNAL,
            pin_bundle=_pins(),
            fitted_ir={"body": "x"},
            requested_output_types=["epub"],
            extension="epub",
        )


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: payload imports no SSOT.
# ---------------------------------------------------------------------------


def test_payload_imports_no_ssot():
    src = (Path(__file__).resolve().parents[1] / "pipeline" / "payload.py").read_text()
    tree = ast_mod.parse(src)
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Import):
            assert all("ssot" not in alias.name for alias in node.names)
        elif isinstance(node, ast_mod.ImportFrom):
            assert node.module is None or "ssot" not in node.module
