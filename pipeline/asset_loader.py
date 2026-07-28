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

Module boundary (import-cycle-checked): imports ONLY `pipeline.presentation` (`AssetLoader`,
`PresentationError`). It is never imported by `presentation`/`dispatch`/`serialize`, so it stays a
one-way DAG leaf (`asset_loader → presentation → {dispatch, ids, canonical}`).
"""

from __future__ import annotations

from pathlib import Path

from pipeline.presentation import AssetLoader, PresentationError

__all__ = ["filesystem_asset_loader"]


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
