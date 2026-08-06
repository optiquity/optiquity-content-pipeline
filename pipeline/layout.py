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

**B-1 ships the map EMPTY (this file).** With `REGISTRY_BASE == {}`, `registry_dir(root, t)` is
exactly `root / t` — the current FLAT layout — so introducing this seam is a provable IDENTITY
no-op: no file moves, byte-identical behavior. A later increment (B-3) fills `REGISTRY_BASE` with
the `foundation/`-prefixed values, and because every framework path-builder already routes through
`registry_dir`, that flip is a single-file change here.

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
#: single home for the literal; UNUSED while `REGISTRY_BASE` is empty (B-1 is behavior-neutral
#: prep).
FOUNDATION_DIRNAME = "foundation"

#: `collection token → physical prefix` for the FRAMEWORK registry layer. EMPTY in B-1 — every token
#: resolves flat (`root / token`) via the `registry_dir` fallback, so this whole increment is an
#: identity no-op. B-3 fills the 17 foundation values; because every framework path-builder already
#: routes through `registry_dir`, that flip is a one-file change here.
REGISTRY_BASE: dict[str, str] = {}

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
