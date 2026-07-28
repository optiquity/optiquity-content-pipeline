"""Increment B, Commit 1 — the production `filesystem_asset_loader` (resolve-and-contain).

Covers the F3 fence (CLAUDE.md rule 2 — client isolation): the presentation-asset loader resolves a
repo-root-relative path against `resolve_base` and REFUSES anything that lands outside
`contain_root` (wired to `<root>/presentations`) — an absolute path, a `..` traversal, or a
cross-client `workspaces/<other>/…` reach-in — reading NO bytes. A contained `presentations/…` asset
(and every shipped `presentations/assets/csl/*.csl`) reads OK.

(`hash_embedded_assets` + the F1 render-time re-gate are Commit 2 scope; this file covers C1 only.)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.asset_loader import filesystem_asset_loader
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
    (root / "presentations" / "assets" / "csl").mkdir(parents=True)
    (root / "presentations" / "assets" / "csl" / "house.csl").write_bytes(b"<style/>house")
    (root / "workspaces" / "other").mkdir(parents=True)
    (root / "workspaces" / "other" / "secret.csl").write_bytes(b"<style/>OTHER-CLIENT-SECRET")
    return root


def _loader(root: Path):
    return filesystem_asset_loader(resolve_base=root, contain_root=root / "presentations")


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
