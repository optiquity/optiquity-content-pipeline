"""The production filesystem asset loader (increment B, Commit 1) — resolve-and-contain.

Design authority: `docs/design.md`
  §5.3 PD2/PD4 — a Presentation `AssetLoader` (`Callable[[str], bytes]`) resolves a declared
        asset PATH (`css`/`template`/`reference_doc`/`csl`) to its BYTES. `presentation_from_entry`
        injects it; `lower` stays pure. This module ships the REAL one that replaces the two
        deferred, loud `_deferred_asset_loader` raises (driver + render-verb legs) — the §17/step-29
        filesystem resolver.
  §17 FR7.1 — the asset's content hash rides the serialize-inputs preimage, so the loader must read
        the ACTUAL file bytes (a byte edit churns the render digest). The three shipped journal
        looks (`presentations/journal-*-look.md`) declare a `csl` STYLE under
        `presentations/assets/csl/`, so this loader is reachable on the production generate-next
        path for a CITING journal render.

**Increment B / F3 fence (CLAUDE.md rule 2 — client isolation).** This is the first code path that
actually reads a styling file off disk. It is FENCED to a `contain_root` (wired to
`<repo_root>/presentations` at every call site): it resolves the repo-root-relative path against
`resolve_base`, refuses any absolute path or `..` traversal, and then ASSERTS the resolved file is
inside `contain_root` — so a tampered/legacy entry pointing at another client's `workspaces/…` (or
`../…`) is refused loudly (`PresentationError`) and NO bytes are ever read. The body-figure base is
distinct (A's `store.root` guard); this fence governs only the presentation-asset loader.

**Increment B / F1 render-time full gate (`hash_embedded_assets`).** Embedding actively OPENS and
COPIES the file a body figure points at, so BEFORE any embed flag is emitted the render leg re-runs
A's *complete* compose-time gate on the persisted AST — `asset_ref.has_raw_markup` (refuse a raw
`<img>`/`\\includegraphics`) plus `asset_ref.assert_asset_refs_contained` over ALL image targets,
with the SAME `store.root` base A proved at compose. An uncontained `../workspaces/other/…` or a
raw-markup body REFUSES the whole render and NO bytes are ever read or embedded. Only after the gate
passes does it sha256 the sorted/deduped `assets/…` subset into the `(rel, hex)` identity fold.

Module boundary (import-cycle-checked, PART 3): imports ONLY `pipeline.presentation` (`AssetLoader`,
`PresentationError`), `pipeline.asset_ref` (the gate), `pipeline.canonical` (`sha256_hex`), and
`pipeline.dispatch` (`EMBED_WRITERS`, `embeddable_image_targets`). It is NEVER imported by
`presentation`/`dispatch`/`serialize`, so it stays a one-way DAG leaf.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import asset_ref
from pipeline.canonical import sha256_hex
from pipeline.dispatch import EMBED_WRITERS, embeddable_image_targets
from pipeline.presentation import AssetLoader, PresentationError

__all__ = [
    "AssetEmbedError",
    "filesystem_asset_loader",
    "hash_embedded_assets",
]

#: A's raw-markup refusal code (§15/§16/§10, DR-7 A). Mirrored as a LITERAL, not imported from
#: `pipeline.api.results`, to keep this module the DAG leaf the PART-3 boundary pins (its four
#: imports are exhaustive). The image-containment refusals propagate `asset_ref.AssetRefError`
#: directly (its `.kind` maps to `asset-ref-uncontained`/`asset-ref-invalid`, A4's codes).
CODE_BODY_RAW_MARKUP_FORBIDDEN = "body-raw-markup-forbidden"


class AssetEmbedError(Exception):
    """A render-time embed refusal (F1): the persisted body about to be embedded carries a raw
    passthrough node (`RawInline`/`RawBlock`) — a vector A's compose gate already bans. Carries A's
    `code` (`body-raw-markup-forbidden`) so the render leg refuses loudly and NO bytes are embedded.
    (Image-target containment escapes raise `asset_ref.AssetRefError`, not this — see the module
    docstring.)"""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def filesystem_asset_loader(*, resolve_base: Path, contain_root: Path) -> AssetLoader:
    """Build a Presentation `AssetLoader` that reads a declared asset path off disk, FENCED to
    `contain_root` (F3).

    The returned `load(path) -> bytes`:
      1. refuses an ABSOLUTE path (asset paths are repo-root-relative refs) — `PresentationError`;
      2. refuses any `..` traversal component — `PresentationError`;
      3. resolves `resolve_base / path` and asserts the result is inside `contain_root`
         (`is_relative_to`) — a path escaping the fence (e.g. `workspaces/<other>/x.csl`) is refused
         BEFORE any read, so no cross-client bytes are ever opened (CLAUDE.md rule 2);
      4. asserts the resolved file EXISTS (a missing/broken asset is refused loudly, §3.1);
      5. returns the file BYTES (the §17 FR7.1 content-hash preimage).

    `resolve_base` is the repo/instance root (`env.root` / `leg.root`); `contain_root` is
    `<root>/presentations`. Every failure raises `presentation.PresentationError` — the SAME typed
    error the injected test loaders and `presentation_from_entry` already speak.
    """
    base = Path(resolve_base)
    fence = Path(contain_root).resolve()

    def load(path: str) -> bytes:
        candidate = Path(path)
        if candidate.is_absolute():
            raise PresentationError(
                "presentation-error: a presentation asset path must be a repo-root-relative "
                f"reference, not an absolute path: {path!r}"
            )
        if ".." in candidate.parts:
            raise PresentationError(
                "presentation-error: a presentation asset path must not traverse parent "
                f"directories ('..'): {path!r}"
            )
        resolved = (base / candidate).resolve()
        if not resolved.is_relative_to(fence):
            raise PresentationError(
                "presentation-error: a presentation asset path must resolve inside the "
                f"presentations/ fence ({fence}); {path!r} escapes it (CLAUDE.md rule 2)"
            )
        if not resolved.is_file():
            raise PresentationError(
                "presentation-error: the presentation asset file does not exist under the "
                f"presentations/ fence: {path!r} (resolved to {resolved})"
            )
        return resolved.read_bytes()

    return load


def hash_embedded_assets(
    ast: dict, writer: str, *, store_root: Path
) -> tuple[tuple[str, str], ...]:
    """The F1 render-time gate + the embedded-figure identity fold, for one about-to-render leg.

    For a NON-embed writer (`markdown`/`plain`/`json`/external — anything outside `EMBED_WRITERS`)
    this is a no-op returning `()`: they open no file, embed nothing, and a legacy `../` path stays
    a harmless broken *reference* exactly as pre-B (running the gate there would newly refuse legacy
    md deliverables — an unwanted behavior change). The gate is coupled to the embed-emission
    surface, the only place the open+copy escalation exists.

    For an EMBED writer (html5/docx) it runs A's FULL compose-time gate on the persisted `ast`
    BEFORE reading a single byte — the EXACT two checks from `compose.py` (`has_raw_markup` →
    refuse; `assert_asset_refs_contained` over ALL `iter_image_targets(ast)`, not just the
    `assets/`-prefixed subset), with the base == `store.root` (the S5 invariant: guard base ==
    render resource-path base). A raw-markup body raises `AssetEmbedError` (code
    `body-raw-markup-forbidden`); a non-contained/broken image target propagates
    `asset_ref.AssetRefError` (`.kind` →
    `asset-ref-uncontained`/`asset-ref-invalid`). In EITHER refusal NO bytes are read and the whole
    render is refused — the file pandoc would open is provably the file A proved safe, so listing
    `repo_root` in `--resource-path` cannot resolve an escaping ref.

    Only AFTER the gate passes does it sha256 each figure in `embeddable_image_targets(ast, writer)`
    (the sorted/deduped `assets/…` subset) read at `store_root/<rel>`, returning `((rel, hex), …)` —
    the OMIT-WHEN-ABSENT `embedded_assets` content half of the serialize preimage. The gate's
    existence check already proved each contained figure is a real file, so the read is safe."""
    if writer not in EMBED_WRITERS:
        return ()
    # F1 FULL gate — order and semantics mirror `compose.py` exactly, and run BEFORE any read.
    if asset_ref.has_raw_markup(ast):
        raise AssetEmbedError(
            CODE_BODY_RAW_MARKUP_FORBIDDEN,
            "the persisted body about to be EMBEDDED carries raw HTML/markup passthrough (e.g. an "
            "`<img>` tag or a raw-TeX `\\includegraphics{…}`) — embedding would open+copy a file "
            "the Markdown-image walk never gated; refusing the render (CLAUDE.md rule 2, §10)",
        )
    asset_ref.assert_asset_refs_contained(
        asset_ref.iter_image_targets(ast), workspace_root=store_root
    )
    root = Path(store_root)
    return tuple(
        (rel, sha256_hex((root / rel).read_bytes()))
        for rel in embeddable_image_targets(ast, writer)
    )
