"""`pipeline.layout` — the framework-registry physical-location map (the `foundation/` reorg seam).

These tests pin the B-3 CONTRACT: `REGISTRY_BASE` is FILLED, so `registry_dir(root, token)` resolves
each of the 17 framework registries to its `foundation/`-anchored home (no longer the flat
identity).
They are the committed guard that the layout SSOT holds its Option-3 binning — a registry can only
move by a deliberate one-line edit here — and that the dimension-axis vocabulary folded in from the
former `pipeline.api.discovery._AXIS_DIRS` keeps its exact membership + order. An UNMAPPED token
(synthetic/test, e.g. `gadgets`) still resolves flat via the `.get(token, token)` fallback.
"""

from __future__ import annotations

from pathlib import Path

from pipeline import layout
from pipeline.layout import registry_dir

#: Every REAL framework registry token routed through `registry_dir` (the §5 registries + the §3/§4
#: dimension axes). B-3 resolves each one to its `foundation/`-anchored home.
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


def test_b3_map_is_filled_foundation_anchored() -> None:
    """B-3 fills `REGISTRY_BASE` with the 17 `foundation/`-anchored homes — its keys are exactly the
    real registry tokens, and the Option-3 binning holds (one home per token, all under
    `foundation/`)."""
    assert set(layout.REGISTRY_BASE) == set(_REAL_TOKENS)
    assert len(layout.REGISTRY_BASE) == 17
    assert all(v.startswith("foundation/") for v in layout.REGISTRY_BASE.values())
    # spot-check one home per bin (dimensions / grounding / composition / render-config / singleton)
    assert layout.REGISTRY_BASE["topics"] == "foundation/dimensions/topics"
    assert layout.REGISTRY_BASE["sources"] == "foundation/grounding/sources"
    assert layout.REGISTRY_BASE["recipes"] == "foundation/composition/recipes"
    assert layout.REGISTRY_BASE["render-targets"] == "foundation/render-config/render-targets"
    assert layout.REGISTRY_BASE["lexicons"] == "foundation/lexicons"


def test_registry_dir_resolves_foundation_for_every_real_token() -> None:
    """The load-bearing B-3 claim: `registry_dir(root, t) == root / REGISTRY_BASE[t]` for all 17
    real registry tokens — each is now `foundation/`-anchored (no longer the flat identity)."""
    root = Path("/some/framework/root")
    assert len(_REAL_TOKENS) == 17
    for token in _REAL_TOKENS:
        assert registry_dir(root, token) == root / layout.REGISTRY_BASE[token]
        assert registry_dir(root, token) != root / token  # no longer the flat identity


def test_unmapped_token_stays_flat() -> None:
    """The `.get(token, token)` fallback keeps synthetic / test tokens (e.g. `gadgets`) and any
    not-yet-mapped collection flat — the reason B-1 is an identity refactor with an empty map."""
    root = Path("/r")
    assert registry_dir(root, "gadgets") == root / "gadgets"


def test_registry_dir_accepts_str_root() -> None:
    """A `str` root is coerced (`Path(root)`), matching the bare-join call sites it replaced."""
    assert registry_dir("/r", "voices") == Path("/r") / "foundation/dimensions/voices"


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


def test_foundation_dirname_is_named() -> None:
    """The `foundation/` grouping directory name has a single home here — every `REGISTRY_BASE`
    value is anchored under it."""
    assert layout.FOUNDATION_DIRNAME == "foundation"
