"""`pipeline.layout` — the framework-registry physical-location map (the `foundation/` reorg seam).

These tests pin the B-1 CONTRACT: the map ships EMPTY, so `registry_dir(root, token)` is a pure
IDENTITY (`root / token`) and the whole reroute is a no-op. They are the committed guard that the
B-3 flip (filling `REGISTRY_BASE`) is a deliberate, single-file change here — never an accidental
layout drift — and that the dimension-axis vocabulary folded in from the former
`pipeline.api.discovery._AXIS_DIRS` keeps its exact membership + order.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import layout
from pipeline.layout import registry_dir

#: Every REAL framework registry token routed through `registry_dir` by the B-1 reroute (the §5
#: registries + the §3/§4 dimension axes). B-1 resolves each one FLAT.
_REAL_TOKENS = (
    "topics",
    "personas",
    "formats",
    "voices",
    "goals",
    "platforms",
    "languages",
    "output-types",
    "presentations",
    "sources",
    "content-kinds",
    "recipes",
    "selections",
    "folio-types",
    "render-targets",
    "diagram-styles",
    "lexicons",
)


def test_b1_map_is_empty() -> None:
    """B-1 ships `REGISTRY_BASE` EMPTY — filling the `foundation/` values is B-3's single edit."""
    assert layout.REGISTRY_BASE == {}


def test_registry_dir_is_identity_for_every_real_token() -> None:
    """The load-bearing B-1 claim: with an empty map, `registry_dir(root, t) == root / t` for all 17
    real registry tokens — so no file moves and behavior is byte-identical (the flat layout)."""
    root = Path("/some/framework/root")
    assert len(_REAL_TOKENS) == 17
    for token in _REAL_TOKENS:
        assert registry_dir(root, token) == root / token


def test_unmapped_token_stays_flat() -> None:
    """The `.get(token, token)` fallback keeps synthetic / test tokens (e.g. `gadgets`) and any
    not-yet-mapped collection flat — the reason B-1 is an identity refactor with an empty map."""
    root = Path("/r")
    assert registry_dir(root, "gadgets") == root / "gadgets"


def test_registry_dir_accepts_str_root() -> None:
    """A `str` root is coerced (`Path(root)`), matching the bare-join call sites it replaced."""
    assert registry_dir("/r", "voices") == Path("/r") / "voices"


def test_dimension_axes_membership_and_order() -> None:
    """The axis vocabulary folded in from `discovery._AXIS_DIRS` keeps its exact membership AND
    order (the `list dimension-entries` enumeration order is load-bearing)."""
    assert layout.DIMENSION_AXES == (
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


def test_foundation_dirname_is_named_but_unused_in_b1() -> None:
    """The B-3 grouping directory name has a single home here, even though B-1 never joins it."""
    assert layout.FOUNDATION_DIRNAME == "foundation"
