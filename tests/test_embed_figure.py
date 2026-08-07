"""Increment B, Commit 2 — figure EMBEDDING + the render-time FULL re-gate + the identity fold.

Hermetic acceptance at the dispatch/serialize seam (no live LLM thread): a real
`![alt](assets/x.png)` body is serialized through the pinned pandoc reader, a real PNG lives at
`store.root/assets/x.png`, and the render leg's exact wiring (`hash_embedded_assets` gate →
`resource_paths` → `dispatch`) is exercised.

Proves the B acceptance:
- html5 bytes carry the figure as `src="data:image/png;base64,…"`; docx a `word/media/` part.
- md keeps the figure BY REFERENCE (`assets/x.png`), byte-identical to pre-B; plain shows alt only.
- honest identity: an EMBED render folds the figure by content-hash → editing the image bytes
  re-mints the html/docx serialize digest, while the md (by-reference) id is UNCHANGED.
- zero churn: an image-LESS html5 preimage is byte-identical to the pre-B form.
- F1 render-time REFUSAL: a persisted `../workspaces/other/secret.png` body refuses (`asset-ref-
  uncontained`) and a raw-`<img>` body refuses (`body-raw-markup-forbidden`) — the escaping file's
  bytes are read/inlined NOWHERE. No absolute path leaks into the html/docx bytes.

Embed assertions require the pinned pandoc 3.10 (§17 PA-12 `pandoc_gate`; CI installs it).
"""

from __future__ import annotations

import base64
import zipfile
from pathlib import Path

import pytest

from pipeline import diagram
from pipeline import dispatch as D
from pipeline.asset_loader import AssetEmbedError, hash_embedded_assets
from pipeline.asset_ref import AssetRefError
from pipeline.canonical import sha256_hex
from pipeline.serialize import (
    is_ci,
    pandoc_available,
    pandoc_gate,
    serialize_digest,
    serialize_fitted,
    serialize_inputs_preimage,
)

_PANDOC_AVAILABLE = pandoc_available()

REPO_ROOT = Path(__file__).resolve().parents[1]

# The diagram-SVG embed tests below build a REAL `dot`-compiled SVG (optional tool) and, for docx,
# rasterize it via `rsvg-convert` (optional). Both are OPTIONAL — a tool-less host degrades (the SVG
# is never generated at compose; a docx SVG embed → alt text), so these SKIP when absent. The skip
# markers are the SINGLE canonical copy in `tests/conftest.py`.
from conftest import requires_dot, requires_rsvg  # noqa: E402

#: A tiny valid 1x1 PNG (the figure-A bytes) and a DIFFERENT 2x1 PNG (the edited figure) — distinct
#: content so the content-hash fold visibly re-mints on an edit.
_PNG_A = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_PNG_B = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAEklEQVR42mP8z8BQz0AEYBxVSFYSAKrfA/8AAAAASUVORK5CYII="
)

#: The internal render-target VALUES a preimage is built from (mirrors test_serialize_revision.RT).
_RT_HTML = {"writer": "html5", "engine": "", "reference_doc": ""}
_RT_MD = {"writer": "markdown", "engine": "", "reference_doc": ""}
_RI_PLAIN = {"flags": [], "variables": {}, "assets": [], "engine": ""}


@pytest.fixture(autouse=True)
def _require_pandoc():
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the B embed pass MUST run in CI (PA-12)", pytrace=False
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the embed tests exercise the real serialize AST")


def _store_with_figure(tmp_path: Path, png: bytes = _PNG_A) -> Path:
    """A store root carrying one real figure at `assets/x.png` (A's containment base)."""
    root = tmp_path / "store"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "x.png").write_bytes(png)
    return root


def _figure_ast() -> dict:
    """A serialized AST for a body that references the contained figure (real pinned reader)."""
    return serialize_fitted({"grounding": {}, "body": "![alt text](assets/x.png)"})[0].ast


def _no_figure_ast() -> dict:
    return serialize_fitted({"grounding": {}, "body": "Just prose, no image."})[0].ast


def _render_leg(ast: dict, writer: str, store_root: Path, *, repo_root: Path = REPO_ROOT):
    """Mirror the driver/render leg's exact wiring: gate+hash, order resource_paths, dispatch."""
    embedded = hash_embedded_assets(ast, writer, store_root=store_root)
    resource_paths = (str(store_root), str(repo_root)) if embedded else ()
    dout = D.dispatch(
        D.RenderTarget(writer=writer, side="internal"), ast, resource_paths=resource_paths
    )
    return dout, embedded, resource_paths


# --- the figure REALLY embeds (html data-URI + docx media part) --------------------------------


def test_html5_inlines_the_figure_as_a_data_uri(tmp_path):
    root = _store_with_figure(tmp_path)
    ast = _figure_ast()
    dout, embedded, _ = _render_leg(ast, "html5", root)
    assert dout.assets_embedded is True
    expected_hash = hash_embedded_assets(ast, "html5", store_root=root)[0][1]
    assert embedded == (("assets/x.png", expected_hash),)
    assert b'src="data:image/png;base64,' in dout.output_bytes  # the figure is INLINED, not a path
    assert b"assets/x.png" not in dout.output_bytes  # …and the path is gone (fully embedded)


def test_docx_carries_a_native_media_part(tmp_path):
    root = _store_with_figure(tmp_path)
    dout, _, _ = _render_leg(_figure_ast(), "docx", root)
    assert dout.assets_embedded is True
    zf = zipfile.ZipFile(__import__("io").BytesIO(dout.output_bytes))
    media = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert media, "docx must carry the embedded figure as a word/media/ part"


def test_no_absolute_path_leaks_into_html_or_docx_bytes(tmp_path):
    root = _store_with_figure(tmp_path)
    html, _, _ = _render_leg(_figure_ast(), "html5", root)
    docx, _, _ = _render_leg(_figure_ast(), "docx", root)
    for abs_path in (str(root).encode(), str(REPO_ROOT).encode()):
        assert abs_path not in html.output_bytes
        assert abs_path not in docx.output_bytes


# --- md references by path (pre-B), plain shows alt only -----------------------------------------


def test_markdown_keeps_the_figure_by_reference_byte_identical_to_pre_b(tmp_path):
    root = _store_with_figure(tmp_path)
    ast = _figure_ast()
    dout, embedded, resource_paths = _render_leg(ast, "markdown", root)
    assert embedded == () and resource_paths == () and dout.assets_embedded is False
    assert b"assets/x.png" in dout.output_bytes  # md points at the file, never embeds it
    # byte-identical to a pre-B dispatch (no resource_paths param at all).
    pre_b = D.dispatch(D.RenderTarget(writer="markdown", side="internal"), ast)
    assert dout.output_bytes == pre_b.output_bytes


def test_plain_writer_shows_the_alt_only(tmp_path):
    root = _store_with_figure(tmp_path)
    dout, embedded, _ = _render_leg(_figure_ast(), "plain", root)
    assert embedded == () and dout.assets_embedded is False
    text = dout.output_bytes.decode("utf-8")
    assert "alt text" in text and "assets/x.png" not in text


# --- honest identity: an image edit re-mints html/docx, NOT md ----------------------------------


def _html_preimage(ast: dict, root: Path) -> dict:
    fold = hash_embedded_assets(ast, "html5", store_root=root)
    return serialize_inputs_preimage(
        render_target=_RT_HTML,
        render_inputs=_RI_PLAIN,
        assets_embedded=bool(fold),
        embedded_assets=fold,
    )


def _md_preimage(ast: dict, root: Path) -> dict:
    fold = hash_embedded_assets(ast, "markdown", store_root=root)  # () — md embeds nothing
    return serialize_inputs_preimage(
        render_target=_RT_MD,
        render_inputs=_RI_PLAIN,
        assets_embedded=bool(fold),
        embedded_assets=fold,
    )


def test_editing_the_figure_remints_html_and_docx_but_not_md(tmp_path):
    ast = _figure_ast()
    root_a = _store_with_figure(tmp_path / "a", _PNG_A)
    root_b = _store_with_figure(tmp_path / "b", _PNG_B)  # SAME body, EDITED figure bytes

    html_a, html_b = _html_preimage(ast, root_a), _html_preimage(ast, root_b)
    assert "asset_embed_version" in html_a["tool_bundle"]  # the embed pin rides only when embedding
    assert html_a["render_inputs"]["embedded_assets"][0][0] == "assets/x.png"
    assert serialize_digest(html_a) != serialize_digest(html_b)  # the edit RE-MINTS the html id

    md_a, md_b = _md_preimage(ast, root_a), _md_preimage(ast, root_b)
    assert "asset_embed_version" not in md_a["tool_bundle"]  # md folds no figure content
    assert serialize_digest(md_a) == serialize_digest(md_b)  # the md id is UNCHANGED by the edit


def test_same_inputs_same_html_id(tmp_path):
    ast = _figure_ast()
    root = _store_with_figure(tmp_path)
    a, b = _html_preimage(ast, root), _html_preimage(ast, root)
    assert serialize_digest(a) == serialize_digest(b)


# --- zero churn: an image-LESS html5 preimage is byte-identical to pre-B -------------------------


def test_image_less_html5_preimage_is_byte_identical_to_pre_b(tmp_path):
    root = tmp_path / "empty-store"
    (root / "assets").mkdir(parents=True)
    ast = _no_figure_ast()
    fold = hash_embedded_assets(ast, "html5", store_root=root)
    assert fold == ()  # no figure → nothing to embed
    pre_b = serialize_inputs_preimage(render_target=_RT_HTML, render_inputs=_RI_PLAIN)
    with_new_params = serialize_inputs_preimage(
        render_target=_RT_HTML, render_inputs=_RI_PLAIN, assets_embedded=False, embedded_assets=()
    )
    assert with_new_params == pre_b  # the new params default to a byte-identical preimage
    assert "asset_embed_version" not in with_new_params["tool_bundle"]
    assert "embedded_assets" not in with_new_params["render_inputs"]


# --- F1: a `../` or raw-`<img>` body REFUSES at render and is never embedded ---------------------


def _uncontained_ast() -> dict:
    """An AST whose body Image points OUTSIDE the client's asset root (a tampered/legacy escape)."""
    return {
        "pandoc-api-version": [1, 23, 1, 2],
        "meta": {},
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Image",
                        "c": [["", [], []], [{"t": "Str", "c": "x"}],
                              ["../workspaces/other/secret.png", ""]],
                    }
                ],
            }
        ],
    }


def _raw_img_ast() -> dict:
    """An AST with a raw-HTML `<img>` (a `RawInline` — a vector the Markdown-image walk misses)."""
    return {
        "pandoc-api-version": [1, 23, 1, 2],
        "meta": {},
        "blocks": [
            {"t": "Para", "c": [{"t": "RawInline", "c": ["html", '<img src="assets/x.png">']}]}
        ],
    }


def test_uncontained_body_refuses_at_render_and_never_embeds(tmp_path):
    # A secret figure EXISTS one dir outside the store (proving the refusal is containment, not a
    # missing file). The escaping bytes must be read NOWHERE — the gate raises BEFORE any read.
    root = _store_with_figure(tmp_path / "store")
    secret_dir = tmp_path / "workspaces" / "other"
    secret_dir.mkdir(parents=True)
    secret_bytes = b"OTHER-CLIENT-SECRET-PNG"
    (secret_dir / "secret.png").write_bytes(secret_bytes)

    for writer in ("html5", "docx"):
        with pytest.raises(AssetRefError) as exc:
            hash_embedded_assets(_uncontained_ast(), writer, store_root=root)
        assert exc.value.kind == "uncontained"  # maps to A's `asset-ref-uncontained`
    # Because the gate refuses, no resource_paths is ever computed and no writer runs → the secret
    # bytes appear in NO output (there IS no output). Belt-and-braces: the plain-passthrough writer
    # would still never see the secret file since dispatch opens nothing itself.


def test_raw_markup_body_refuses_at_render(tmp_path):
    root = _store_with_figure(tmp_path)
    for writer in ("html5", "docx"):
        with pytest.raises(AssetEmbedError) as exc:
            hash_embedded_assets(_raw_img_ast(), writer, store_root=root)
        assert exc.value.code == "body-raw-markup-forbidden"


def test_non_embed_writer_does_not_run_the_gate_on_a_legacy_ref(tmp_path):
    # The gate is coupled to the EMBED surface: a non-embed writer (md/plain) over a legacy `../`
    # body opens no file and stays a harmless broken *reference* — running the gate there would
    # newly refuse legacy md deliverables (an unwanted change). So md/plain never raise here.
    root = _store_with_figure(tmp_path)
    for writer in ("markdown", "plain", "json"):
        assert hash_embedded_assets(_uncontained_ast(), writer, store_root=root) == ()
        assert hash_embedded_assets(_raw_img_ast(), writer, store_root=root) == ()


# --- increment C (C4): a compose-minted diagram SVG rides B's embed on every target --------------


def _store_with_diagram_svg(tmp_path: Path) -> tuple[Path, str]:
    """A store root carrying a REAL `dot`-compiled diagram SVG under `assets/diagrams/<hash>.svg`
    (exactly what the C4 compose transform mints via `store.commit_asset`)."""
    spec = diagram.parse_diagram(
        "nodes:\n- gw: Gateway\n- auth: Auth\n"
        'edges:\n- gw -> auth [routes]{.EXTRACTED data-fact="f1"}\n'
    )
    svg = diagram.compile_diagram(spec, tool="dot").svg
    digest = sha256_hex(svg)
    target = tmp_path / "store" / "assets" / "diagrams" / f"{digest}.svg"
    target.parent.mkdir(parents=True)
    target.write_bytes(svg)
    return tmp_path / "store", digest


def _diagram_figure_ast(digest: str) -> dict:
    """The AST for the C4-persisted figure body `![alt](assets/diagrams/<hash>.svg)`."""
    body = f"![architecture](assets/diagrams/{digest}.svg)"
    return serialize_fitted({"grounding": {}, "body": body})[0].ast


@requires_dot
def test_diagram_svg_embeds_on_html5_as_a_data_uri(tmp_path):
    root, digest = _store_with_diagram_svg(tmp_path)
    dout, embedded, _ = _render_leg(_diagram_figure_ast(digest), "html5", root)
    assert dout.assets_embedded is True
    assert b"data:image/svg+xml" in dout.output_bytes  # the diagram SVG is INLINED into the html
    assert f"assets/diagrams/{digest}.svg".encode() not in dout.output_bytes  # path gone (embedded)


@requires_dot
@requires_rsvg
def test_diagram_svg_docx_carries_a_native_media_part(tmp_path):
    # When rsvg-convert IS installed the diagram rides into a real word/media/ part (with the rsvg
    # PNG fallback). When it is ABSENT the docx embed DEGRADES to alt text (test_dispatch.py) — so
    # this embed-present test SKIPS on a tool-less host rather than failing (rsvg is optional).
    root, digest = _store_with_diagram_svg(tmp_path)
    dout, _, _ = _render_leg(_diagram_figure_ast(digest), "docx", root)
    assert dout.assets_embedded is True
    zf = zipfile.ZipFile(__import__("io").BytesIO(dout.output_bytes))
    media = [n for n in zf.namelist() if n.startswith("word/media/")]
    assert media, "docx must carry the embedded diagram as a word/media/ part"


@requires_dot
def test_diagram_svg_markdown_keeps_it_by_reference(tmp_path):
    root, digest = _store_with_diagram_svg(tmp_path)
    dout, embedded, resource_paths = _render_leg(_diagram_figure_ast(digest), "markdown", root)
    assert embedded == () and dout.assets_embedded is False
    assert f"assets/diagrams/{digest}.svg".encode() in dout.output_bytes  # md points at the file


@requires_dot
def test_diagram_svg_plain_shows_the_alt_only(tmp_path):
    root, digest = _store_with_diagram_svg(tmp_path)
    dout, _, _ = _render_leg(_diagram_figure_ast(digest), "plain", root)
    text = dout.output_bytes.decode("utf-8")
    assert "architecture" in text and f"assets/diagrams/{digest}.svg" not in text


# --- FR7.3: the driver's rsvg-aware fold — no silent same-id/different-bytes when rsvg absent ---

_RT_DOCX = {"writer": "docx", "engine": "", "reference_doc": ""}


def _docx_svg_preimage(embedded_assets: tuple) -> dict:
    """The docx serialize preimage for a given (post-fold) embedded-asset set."""
    return serialize_inputs_preimage(
        render_target=_RT_DOCX,
        render_inputs=_RI_PLAIN,
        assets_embedded=bool(embedded_assets),
        embedded_assets=embedded_assets,
    )


@requires_dot
def test_driver_rsvg_absent_docx_fold_differs_from_rsvg_present_no_silent_collision(tmp_path):
    # FR7.3 DRIVER-LEVEL regression on the exact `driver._rsvg_aware_embed_fold` seam the render leg
    # uses. A docx deliverable whose body carries a real SVG diagram: when `rsvg-convert` is ABSENT
    # the driver DROPS the `.svg` fold → the RECORDED preimage folds NO diagram asset → serialize
    # DIGEST DIFFERS from the rsvg-PRESENT render. Same deliverable-id, DIFFERENT recorded
    # preimage ⇒ NO silent same-id/different-bytes: the record honestly matches the produced bytes,
    # and a cross-env conflict is caught by the S0 preimage-check (never a silent reuse).
    from pipeline import driver

    root, digest = _store_with_diagram_svg(tmp_path)
    fold = hash_embedded_assets(_diagram_figure_ast(digest), "docx", store_root=root)
    assert fold and fold[0][0].endswith(".svg")  # the docx WOULD embed the diagram SVG

    present = driver._rsvg_aware_embed_fold(fold, "docx", rsvg_present=True)
    absent = driver._rsvg_aware_embed_fold(fold, "docx", rsvg_present=False)
    assert present == fold  # rsvg present → the fold is byte-identical (the svg embeds)
    assert absent == ()  # rsvg absent → the svg is dropped (the docx degrades to alt text)

    pre_present, pre_absent = _docx_svg_preimage(present), _docx_svg_preimage(absent)
    assert "asset_embed_version" in pre_present["tool_bundle"]  # embed CLAIMED only when embedding
    assert "asset_embed_version" not in pre_absent["tool_bundle"]  # degraded → no embed claimed
    assert serialize_digest(pre_present) != serialize_digest(pre_absent)  # no same-id/diff-bytes

    # A non-docx writer (html5) is UNAFFECTED — its SVG data-URI embed needs no rsvg, so the fold
    # (and thus the recorded identity) is byte-identical regardless of rsvg presence.
    assert driver._rsvg_aware_embed_fold(fold, "html5", rsvg_present=False) == fold
