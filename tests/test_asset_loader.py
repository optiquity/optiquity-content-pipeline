"""Increment B — the production `filesystem_asset_loader` (C1) + `hash_embedded_assets` (C2).

C1 covers the F3 fence (CLAUDE.md rule 2 — client isolation): the presentation-asset loader resolves
a repo-root-relative path against `resolve_base` and REFUSES anything that lands outside
`contain_root` (wired to `<root>/presentations`) — an absolute path, a `..` traversal, or a
cross-client `workspaces/<other>/…` reach-in — reading NO bytes. A contained `presentations/…` asset
(and every shipped `presentations/assets/csl/*.csl`) reads OK.

C2 covers `hash_embedded_assets` — the F1 render-time FULL gate + the identity fold: for an EMBED
writer it re-runs A's compose gate on the persisted AST (raw-markup refusal + containment over ALL
image targets) BEFORE reading a byte, then sha256s the sorted/deduped `assets/…` subset. A
non-contained target propagates `AssetRefError`; a raw-`<img>` body raises `AssetEmbedError`; a
non-embed writer is a no-op (`()`). These tests build ASTs directly (no pandoc needed).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.asset_loader import AssetEmbedError, filesystem_asset_loader, hash_embedded_assets
from pipeline.asset_ref import AssetRefError
from pipeline.canonical import sha256_hex
from pipeline.layout import registry_dir
from pipeline.presentation import PresentationError

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The three generic framework citation styles shipped under the `presentations/` fence.
SHIPPED_CSL = (
    "presentations/assets/csl/author-date.csl",
    "presentations/assets/csl/numeric.csl",
    "presentations/assets/csl/note.csl",
)


def _fenced_root(tmp_path: Path) -> Path:
    """A tmp world with a `presentations/` fence carrying one real asset AND a cross-client
    `workspaces/other/` file that EXISTS on disk (so a refusal proves the fence blocks BEFORE any
    read, not merely that the file is absent)."""
    root = tmp_path / "root"
    pres = registry_dir(root, "presentations")
    (pres / "assets" / "csl").mkdir(parents=True)
    (pres / "assets" / "csl" / "house.csl").write_bytes(b"<style/>house")
    (root / "workspaces" / "other").mkdir(parents=True)
    (root / "workspaces" / "other" / "secret.csl").write_bytes(b"<style/>OTHER-CLIENT-SECRET")
    return root


def _loader(root: Path):
    return filesystem_asset_loader(
        resolve_base=root, contain_root=registry_dir(root, "presentations")
    )


# --- contained reads ---------------------------------------------------------


def test_reads_a_contained_presentation_asset(tmp_path):
    root = _fenced_root(tmp_path)
    load = _loader(root)
    assert load("presentations/assets/csl/house.csl") == b"<style/>house"


def test_reads_every_shipped_csl_off_the_real_repo_fence(tmp_path):
    """The real shipped styles resolve + read through the production loader against the REAL repo
    root (the C11 journal looks declare exactly these repo-root-relative `csl` paths)."""
    load = filesystem_asset_loader(
        resolve_base=REPO_ROOT, contain_root=REPO_ROOT / "presentations"
    )
    for rel in SHIPPED_CSL:
        assert load(rel) == (REPO_ROOT / rel).read_bytes()


# --- F3 refusals (no bytes read) ---------------------------------------------


def test_refuses_a_cross_client_workspaces_path(tmp_path):
    """A `workspaces/<other>/…` asset EXISTS on disk under the same root but is OUTSIDE the
    `presentations/` fence — the loader REFUSES it (rule 2), never reading the other client."""
    root = _fenced_root(tmp_path)
    load = _loader(root)
    with pytest.raises(PresentationError) as exc:
        load("workspaces/other/secret.csl")
    assert exc.value.code == "presentation-error"


def test_refuses_a_parent_traversal_path(tmp_path):
    root = _fenced_root(tmp_path)
    load = _loader(root)
    with pytest.raises(PresentationError):
        load("../workspaces/other/secret.csl")
    # a `..` that would re-enter the fence after escaping is ALSO refused (explicit `..` ban):
    with pytest.raises(PresentationError):
        load("presentations/../workspaces/other/secret.csl")


def test_refuses_an_absolute_path(tmp_path):
    root = _fenced_root(tmp_path)
    load = _loader(root)
    with pytest.raises(PresentationError):
        load(str(root / "workspaces" / "other" / "secret.csl"))
    with pytest.raises(PresentationError):
        load("/etc/passwd")


def test_refuses_a_missing_asset_inside_the_fence(tmp_path):
    """A path that stays INSIDE the fence but names no file is refused loudly (§3.1), not silently
    dropped."""
    root = _fenced_root(tmp_path)
    load = _loader(root)
    with pytest.raises(PresentationError):
        load("presentations/assets/csl/does-not-exist.csl")


# --- C2: hash_embedded_assets — the F1 gate + the identity fold ------------------------------


def _img(url: str) -> dict:
    return {"t": "Image", "c": [["", [], []], [{"t": "Str", "c": "alt"}], [url, ""]]}


def _ast(*inlines: dict) -> dict:
    return {
        "pandoc-api-version": [1, 23, 1, 2],
        "meta": {},
        "blocks": [{"t": "Para", "c": list(inlines)}],
    }


def _store_with(tmp_path: Path, **files: bytes) -> Path:
    root = tmp_path / "store"
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


def test_hash_embedded_assets_reads_and_hashes_the_contained_subset(tmp_path):
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA", "assets/sub/y.png": b"OTHER"})
    ast = _ast(_img("assets/sub/y.png"), _img("assets/x.png"))
    for writer in ("html5", "docx"):
        fold = hash_embedded_assets(ast, writer, store_root=root)
        # SORTED + typed as (rel, hex) with the REAL file content hash.
        assert fold == (
            ("assets/sub/y.png", sha256_hex(b"OTHER")),
            ("assets/x.png", sha256_hex(b"PNGDATA")),
        )


def test_hash_embedded_assets_dedups_a_repeated_target(tmp_path):
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})
    ast = _ast(_img("assets/x.png"), _img("assets/x.png"))  # same figure twice
    fold = hash_embedded_assets(ast, "html5", store_root=root)
    assert fold == (("assets/x.png", sha256_hex(b"PNGDATA")),)  # deduped → one entry


def test_hash_embedded_assets_is_a_noop_for_non_embed_writers(tmp_path):
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})
    ast = _ast(_img("assets/x.png"))
    for writer in ("markdown", "plain", "json", "epub3"):
        assert hash_embedded_assets(ast, writer, store_root=root) == ()


def test_f1_uncontained_target_refuses_before_any_read(tmp_path):
    # A secret figure EXISTS just outside the store (so a refusal proves containment, not absence).
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})
    (tmp_path / "workspaces" / "other").mkdir(parents=True)
    (tmp_path / "workspaces" / "other" / "secret.png").write_bytes(b"SECRET")
    ast = _ast(_img("../workspaces/other/secret.png"))
    for writer in ("html5", "docx"):
        with pytest.raises(AssetRefError) as exc:
            hash_embedded_assets(ast, writer, store_root=root)
        assert exc.value.kind == "uncontained"  # → A's `asset-ref-uncontained`


def test_f1_broken_contained_figure_refuses_as_invalid(tmp_path):
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})  # y.png does NOT exist
    ast = _ast(_img("assets/missing.png"))
    with pytest.raises(AssetRefError) as exc:
        hash_embedded_assets(ast, "html5", store_root=root)
    assert exc.value.kind == "invalid"  # a contained-but-missing figure cannot be hashed → refused


def test_f1_raw_markup_body_refuses_with_a_body_code(tmp_path):
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})
    ast = _ast({"t": "RawInline", "c": ["html", '<img src="assets/x.png">']})
    for writer in ("html5", "docx"):
        with pytest.raises(AssetEmbedError) as exc:
            hash_embedded_assets(ast, writer, store_root=root)
        assert exc.value.code == "body-raw-markup-forbidden"


def test_f1_raw_markup_is_checked_before_containment(tmp_path):
    # A body carrying BOTH a raw node AND an uncontained image → the raw-markup refusal wins (it
    # runs first, mirroring compose.py's order), and NO bytes are read either way.
    root = _store_with(tmp_path, **{"assets/x.png": b"PNGDATA"})
    ast = _ast(
        {"t": "RawInline", "c": ["html", "<img>"]}, _img("../workspaces/other/secret.png")
    )
    with pytest.raises(AssetEmbedError) as exc:
        hash_embedded_assets(ast, "html5", store_root=root)
    assert exc.value.code == "body-raw-markup-forbidden"
