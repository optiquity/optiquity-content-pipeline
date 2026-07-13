"""Step-29 tests: `pipeline/presentation.py` — the full PD3 lowering (§17 PD3/PD4, FR7.1).

Pure, pandoc-free (the lowering reads no filesystem and runs no writer). Covers the plan
step-29 acceptance for Presentation:

- **the `plain` floor causes ZERO id churn** (PD5): `lower(plain, …)` is the EMPTY RenderInputs,
  byte-identical to the step-27 skeleton, so the deliverable-id does not move;
- **an edited css asset churns the serialize digest** (§17 FR7.1) — same path, edited bytes →
  a different per-asset content hash → a different preimage → a different digest, with NO schema
  version moved;
- **per-asset content hashing** and **css load-bearing order** (PD2);
- **writer-family gating** (css → html/epub only; reference_doc → docx/pptx/odt; template ≠ pptx);
- **variables delta-vs-floor** (PD5 zero-churn: a variable at its floor emits no flag, no snapshot);
- **`presentation_from_entry`** maps a PD2 registry entry + an asset loader → a resolved
  Presentation, and a `plain`-shaped entry lowers to the empty struct;
- **no SSOT import** (INV-CORRECTNESS, §22.7).
"""

from __future__ import annotations

import ast as ast_mod
from pathlib import Path

import pytest

from pipeline.dispatch import RenderInputs
from pipeline.presentation import (
    Presentation,
    PresentationAsset,
    PresentationError,
    lower,
    plain_presentation,
    presentation_from_entry,
    render_inputs_to_mapping,
)
from pipeline.serialize import (
    READER_PIN,
    build_render_binding,
    serialize_digest,
    serialize_inputs_preimage,
)

FIT = "a-0123456789abcdef.linkedin.en"
FIT_REF = {"fitted_id": FIT, "digest": "4b7a90ce12d3"}

# A render-target's resolved values (RI12) — the html target, internal.
RT = {
    "id": "html",
    "writer": "html5",
    "side": "internal",
    "engine": "",
    "reference_doc": "",
    "pandoc_version": "3.10",
    "pandoc_api_version": [1, 23, 1, 2],
    "reader": READER_PIN,
    "schema_version": 1,
}


def _preimage(render_inputs):
    return serialize_inputs_preimage(render_target=RT, render_inputs=render_inputs)


# ---------------------------------------------------------------------------
# The `plain` floor → the empty struct → zero id churn (PD5).
# ---------------------------------------------------------------------------


def test_plain_floor_lowers_to_the_empty_struct():
    ri = lower(plain_presentation(), "html5", "html")
    assert ri == RenderInputs(flags=(), variables={}, assets=(), engine="")
    # the canonical mapping is byte-identical to the step-27 skeleton input
    assert render_inputs_to_mapping(ri) == {
        "flags": [],
        "variables": {},
        "assets": [],
        "engine": "",
    }


def test_plain_floor_causes_zero_deliverable_id_churn():
    # The step-27 skeleton input and the step-29 `plain` lowering must produce the SAME preimage,
    # digest, and baseline deliverable-id — shipping the dimension moves no id (PD5, §7.2).
    skeleton = {"flags": [], "variables": {}, "assets": [], "engine": ""}
    plain_map = render_inputs_to_mapping(lower(plain_presentation(), "html5", "html"))
    assert serialize_digest(_preimage(plain_map)) == serialize_digest(_preimage(skeleton))
    rb = build_render_binding(
        fitted_id=FIT,
        output_type="html",
        presentation="plain",
        preimage=_preimage(plain_map),
        fit_binding_ref=FIT_REF,
        minted_ts="2020-01-01T00:00:00+00:00",
    )
    assert rb["deliverable_id"] == "a-0123456789abcdef.linkedin.en.html.plain"  # baseline


def test_plain_carries_the_target_engine_through():
    ri = lower(plain_presentation(), "pdf", "pdf", target_engine="typst")
    assert ri.engine == "typst" and ri.flags == () and ri.assets == ()


# ---------------------------------------------------------------------------
# The edited-css churn (§17 FR7.1) — the headline acceptance.
# ---------------------------------------------------------------------------


def test_edited_css_asset_churns_the_serialize_digest_with_no_schema_move():
    v1 = PresentationAsset("css", "brand.css", b"body{color:red}")
    v2 = PresentationAsset("css", "brand.css", b"body{color:blue}")  # SAME path, edited bytes
    ri1 = lower(Presentation(presentation_id="corp", css=(v1,)), "html5", "html")
    ri2 = lower(Presentation(presentation_id="corp", css=(v2,)), "html5", "html")
    # same path in the flag, DIFFERENT content hash in the asset → the preimage churns
    assert ri1.assets != ri2.assets
    assert ri1.flags == ri2.flags == ("--css=brand.css",)
    d1 = serialize_digest(_preimage(render_inputs_to_mapping(ri1)))
    d2 = serialize_digest(_preimage(render_inputs_to_mapping(ri2)))
    assert d1 != d2  # the css edit alone churns the render digest (no schema version moved)


def test_per_asset_content_hash_is_the_bytes_digest():
    a = PresentationAsset("css", "x.css", b"same")
    b = PresentationAsset("template", "x.css", b"same")  # different role/label, same bytes
    assert a.content_hash == b.content_hash  # the hash is of CONTENT only
    assert PresentationAsset("css", "x.css", b"other").content_hash != a.content_hash


def test_css_order_is_load_bearing():
    a = PresentationAsset("css", "a.css", b"a{}")
    b = PresentationAsset("css", "b.css", b"b{}")
    ri_ab = lower(Presentation(css=(a, b)), "html5", "html")
    ri_ba = lower(Presentation(css=(b, a)), "html5", "html")
    # the cascade order lives in the ordered flags — a reorder churns the digest
    assert ri_ab.flags == ("--css=a.css", "--css=b.css")
    assert ri_ba.flags == ("--css=b.css", "--css=a.css")
    assert serialize_digest(_preimage(render_inputs_to_mapping(ri_ab))) != serialize_digest(
        _preimage(render_inputs_to_mapping(ri_ba))
    )


# ---------------------------------------------------------------------------
# Writer-family gating (PD2).
# ---------------------------------------------------------------------------


def test_css_only_applies_to_html_epub_writers():
    pres = Presentation(css=(PresentationAsset("css", "s.css", b"s{}"),))
    assert lower(pres, "html5", "html").flags == ("--css=s.css",)
    assert lower(pres, "epub3", "epub").flags == ("--css=s.css",)
    # a docx writer takes no css — the lever is silently inapplicable (not an error)
    assert lower(pres, "docx", "docx").flags == ()
    assert lower(pres, "docx", "docx").assets == ()


def test_reference_doc_applies_to_docx_and_is_hashed():
    ref = PresentationAsset("reference-doc", "brand.docx", b"PK\x03\x04zip")
    pres = Presentation(reference_docs={"docx": ref})
    ri = lower(pres, "docx", "docx")
    assert ri.flags == ("--reference-doc=brand.docx",)
    assert ri.assets == (("brand.docx", ref.content_hash),)
    # html5 does not consume a docx reference-doc
    assert lower(pres, "html5", "html").flags == ()


def test_template_applies_per_writer_but_never_pptx():
    tmpl = PresentationAsset("template", "letter.html", b"$body$")
    pres = Presentation(templates={"html5": tmpl, "pptx": tmpl})
    assert lower(pres, "html5", "html").flags == ("--template=letter.html",)
    # pptx has no template lever (PD2) — even a template[pptx] entry emits no flag
    assert lower(pres, "pptx", "pptx").flags == ()


def test_pdf_engine_and_options_lower_into_engine_and_flags():
    pres = Presentation(pdf={"engine": "typst", "options": ["--foo", "--bar"]})
    ri = lower(pres, "pdf", "pdf", target_engine="xelatex")
    assert ri.engine == "typst"  # the presentation engine overrides the target's
    assert ri.flags == ("--pdf-engine-opt=--foo", "--pdf-engine-opt=--bar")
    # the pdf lever is inert for a non-pdf output-type
    assert lower(pres, "html5", "html").engine == ""


# ---------------------------------------------------------------------------
# Variables delta-vs-floor (PD5 zero-churn) + scalar/non-scalar flag emission.
# ---------------------------------------------------------------------------


def test_variable_at_its_floor_emits_no_flag_and_no_snapshot():
    pres = Presentation(
        variables={"fontsize": "11pt", "lang": "en"},
        variable_defaults={"fontsize": "11pt"},  # fontsize at floor → dropped
    )
    ri = lower(pres, "html5", "html")
    assert ri.variables == {"lang": "en"}  # only the deviation survives (PD5)
    assert ri.flags == ("--variable=lang=en",)


def test_non_scalar_variable_rides_the_snapshot_only():
    pres = Presentation(variables={"linkcolor": "blue", "geometry": {"margin": "1in"}})
    ri = lower(pres, "html5", "html")
    # both enter the identity snapshot; only the scalar becomes a pandoc -V flag (v1 PD2)
    assert ri.variables == {"linkcolor": "blue", "geometry": {"margin": "1in"}}
    assert ri.flags == ("--variable=linkcolor=blue",)


def test_bool_variable_uses_pandoc_truthy_tokens():
    ri = lower(Presentation(variables={"numbersections": True}), "html5", "html")
    assert ri.flags == ("--variable=numbersections=true",)


# ---------------------------------------------------------------------------
# presentation_from_entry (the PD2 registry entry → resolved Presentation).
# ---------------------------------------------------------------------------


def test_presentation_from_entry_resolves_assets_via_the_loader():
    files = {"brand.css": b"body{}", "ref.docx": b"PKzip"}
    entry = {
        "id": "corp",
        "variables": {"fontsize": "12pt"},
        "highlight_style": "pygments",
        "css": ["brand.css"],
        "reference_doc": {"docx": "ref.docx"},
    }
    pres = presentation_from_entry(entry, load_asset=files.__getitem__)
    ri_html = lower(pres, "html5", "html")
    assert "--css=brand.css" in ri_html.flags
    assert "--highlight-style=pygments" in ri_html.flags
    assert "--variable=fontsize=12pt" in ri_html.flags
    ri_docx = lower(pres, "docx", "docx")
    assert ri_docx.flags == ("--variable=fontsize=12pt", "--highlight-style=pygments",
                             "--reference-doc=ref.docx")


def test_plain_entry_lowers_to_the_empty_struct():
    # A `plain`-shaped entry (sets nothing) resolves to the floor → the empty lowering (PD5/PD7).
    pres = presentation_from_entry({"id": "plain"}, load_asset=lambda p: b"")
    assert lower(pres, "html5", "html") == RenderInputs(engine="")


def test_from_entry_refuses_a_non_map_css():
    with pytest.raises(PresentationError):
        presentation_from_entry({"id": "x", "css": "one.css"}, load_asset=lambda p: b"")


def test_asset_content_must_be_bytes():
    with pytest.raises(PresentationError):
        PresentationAsset("css", "x.css", "not-bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: presentation imports no SSOT.
# ---------------------------------------------------------------------------


def test_presentation_imports_no_ssot():
    src = (Path(__file__).resolve().parents[1] / "pipeline" / "presentation.py").read_text()
    tree = ast_mod.parse(src)
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Import):
            assert all("ssot" not in alias.name for alias in node.names)
        elif isinstance(node, ast_mod.ImportFrom):
            assert node.module is None or "ssot" not in node.module
