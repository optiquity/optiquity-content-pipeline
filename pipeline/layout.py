"""The framework-registry physical-location map — where a collection TOKEN lives on disk.

Design authority: the reconciled Phase-B design of record (the `foundation/` reorg). This module
is the SINGLE SOURCE OF TRUTH for the PHYSICAL directory a framework-registry collection resolves
to — the sibling of `pipeline.workspace_name` (which owns the per-user / instance side,
`users/<user>/workspaces/<workspace>/…`). This module owns ONLY the FRAMEWORK layer.

**Why a map, not a hardcoded join.** Every framework path-builder used to join `root / <token>`
directly, so the physical layout was smeared across ~19 call sites in a dozen modules. Moving a
registry under a new parent (the `foundation/` grouping) would have been a many-file edit — a
§3/§4 "adding a value is a one-file change" violation waiting to happen. This module collapses that
knowledge to ONE place: callers pass the bare collection TOKEN (`"voices"`, `"recipes"`, …) —
unchanged everywhere — and `registry_dir(root, token)` resolves the physical prefix.

**B-1 shipped the map EMPTY, B-3 filled it.** In B-1 `REGISTRY_BASE == {}`, so
`registry_dir(root, t)` was exactly `root / t` (the old FLAT layout) — a provable IDENTITY no-op
that introduced this seam with no file moves. B-3 THEN filled `REGISTRY_BASE` with the
`foundation/`-prefixed values and moved the 17 registries on disk
(`scripts/migrate-to-foundation-layout.sh`); because every framework path-builder already routed
through `registry_dir`, that flip was a single-file edit here. An unmapped token (a synthetic/test
token like `gadgets`) still resolves FLAT via the fallback below.

**The `.get(token, token)` fallback is load-bearing.** A token with no map entry resolves flat
(`root / token`). That keeps synthetic / test tokens (e.g. `gadgets`) and any not-yet-mapped
collection working unchanged, and is exactly what makes B-1 an identity refactor with an empty map.

Dependency-free by construction: this module imports only `pathlib`, so every `pipeline` module may
import it with no cycle risk (the same discipline `pipeline.workspace_name` follows).
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "DIMENSION_AXES",
    "FOUNDATION_DIRNAME",
    "REGISTRY_BASE",
    "registry_dir",
]

#: The grouping directory the B-3 flip re-homes the framework registries under. Named here as the
#: single home for the literal (every `REGISTRY_BASE` value is anchored under it); exported for
#: callers that need the grouping name without parsing a mapped path.
FOUNDATION_DIRNAME = "foundation"

#: `collection token → physical prefix` for the FRAMEWORK registry layer. FILLED at B-3 — the 17
#: framework registries now live `foundation/`-anchored on disk, so each token resolves to its
#: `foundation/…` home via `registry_dir`. Because every framework path-builder already routes
#: through `registry_dir` (B-1), this ONE map is the whole physical-layout SSOT: moving a registry
#: is a one-line edit here (plus the on-disk `mv`, scripted in
#: `scripts/migrate-to-foundation-layout.sh`).
#:
#: These values are VERBATIM the guard's `FOUNDATION_REGISTRY_DIRS` whitelist (the bash mirror in
#: `scripts/check-no-content.sh`) — the parity test
#: `tests/test_layout_guard_parity.py::test_foundation_dirs_match_registry_base_once_populated`
#: locks the two together, and its keys are EXACTLY `pipeline.lint.REGISTRY_ROOTS`. The
#: authoritative Option-3 binning (reconciled design of record): the nine §3/§4 dimension axes home
#: under `foundation/dimensions/<axis>`; grounding (`sources`, `content-kinds`) under
#: `foundation/grounding/`; composition (`recipes`, `selections`, `folio-types`) under
#: `foundation/composition/`; render-config (`render-targets`, `diagram-styles`) under
#: `foundation/render-config/`; and `lexicons` sits flat at `foundation/lexicons` (the sole depth-2
#: singleton).
REGISTRY_BASE: dict[str, str] = {
    # dimensions — the nine §3/§4 axes
    "topics": "foundation/dimensions/topics",
    "personas": "foundation/dimensions/personas",
    "formats": "foundation/dimensions/formats",
    "voices": "foundation/dimensions/voices",
    "goals": "foundation/dimensions/goals",
    "platforms": "foundation/dimensions/platforms",
    "languages": "foundation/dimensions/languages",
    "output-types": "foundation/dimensions/output-types",
    "presentations": "foundation/dimensions/presentations",
    # grounding
    "sources": "foundation/grounding/sources",
    "content-kinds": "foundation/grounding/content-kinds",
    # composition
    "recipes": "foundation/composition/recipes",
    "selections": "foundation/composition/selections",
    "folio-types": "foundation/composition/folio-types",
    # render-config
    "render-targets": "foundation/render-config/render-targets",
    "diagram-styles": "foundation/render-config/diagram-styles",
    # lexicons — the sole depth-2 singleton
    "lexicons": "foundation/lexicons",
}

#: The §3/§4 dimension axes — the MEMBERSHIP set + canonical order (folded in from the former
#: `pipeline.api.discovery._AXIS_DIRS`). This is a VOCABULARY tuple, NOT a set of paths: the
#: discovery `list dimensions` / `list dimension-entries` verbs iterate it, and each axis's physical
#: directory is resolved through `registry_dir` like every other token. Order is load-bearing (it is
#: the discovery `dimension-entries` enumeration order).
DIMENSION_AXES: tuple[str, ...] = (
    "personas",
    "platforms",
    "formats",
    "topics",
    "voices",
    "goals",
    "languages",
    "output-types",
    "presentations",
)


def registry_dir(root: str | Path, token: str) -> Path:
    """The physical directory a framework-registry `token` resolves to under `root`.

    `root / REGISTRY_BASE.get(token, token)` — an unmapped token resolves FLAT (the identity
    fallback), so with the B-1 empty map this is exactly `root / token`. The ONE place a framework
    registry's physical location is decided (the sibling of `workspace_name.workspace_path`, which
    owns the per-user side)."""
    return Path(root) / REGISTRY_BASE.get(token, token)
