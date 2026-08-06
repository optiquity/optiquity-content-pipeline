"""Parity lock: the bash guard's registry whitelists ↔ the Python layout/lint SSOTs.

Makes an 18th-registry drift between `scripts/check-no-content.sh` and
`pipeline.layout` / `pipeline.lint` IMPOSSIBLE — the guard hardcodes its registry
whitelists in bash (it cannot import Python), so without this lock the two SSOTs could
silently diverge and a new registry could ship UNSCANNED / unvetted (exactly the GAP-4a
hazard, one level up).

DUAL-SAFE for the B-2 → B-3 window (mirrors the guard's own dual-safety). The invariants
that hold on today's still-FLAT repo are asserted unconditionally:

  * the guard's flat `REGISTRY_ROOTS` == `pipeline.lint.REGISTRY_ROOTS`;
  * the guard's `FOUNDATION_REGISTRY_DIRS` is a `foundation/`-anchored bijection onto those
    same 17 roots (one home per root);
  * the tokens homed under `foundation/dimensions/` are EXACTLY
    `pipeline.layout.DIMENSION_AXES`.

The value-parity that needs the (still-empty at B-2) map —
`FOUNDATION_REGISTRY_DIRS == set(pipeline.layout.REGISTRY_BASE.values())` and
`set(REGISTRY_BASE) == set(lint.REGISTRY_ROOTS)` — is asserted CONDITIONALLY: inert while
`REGISTRY_BASE` is empty (B-1/B-2, the foundation registries have not moved), engaging the
moment B-3 fills it. From then on any drift between the guard and the layout SSOT fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipeline import layout, lint

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "check-no-content.sh"


def _bash_var_tokens(name: str) -> set[str]:
    """The whitespace-separated token set of a top-level `NAME="..."` assignment in the guard.

    Anchored at start-of-line so the descriptive comments that also name the variable never
    match; the value is a single double-quoted line with no embedded quotes."""
    text = GUARD.read_text(encoding="utf-8")
    m = re.search(rf'(?m)^{re.escape(name)}="([^"]*)"', text)
    assert m, f"{name}= assignment not found in {GUARD}"
    return set(m.group(1).split())


def test_bash_registry_roots_mirror_lint_registry_roots():
    """The FLAT whitelist the guard scans today == the Python lint SSOT — a new flat registry
    cannot desync bash↔Python (checkable NOW, independent of the foundation move)."""
    assert _bash_var_tokens("REGISTRY_ROOTS") == set(lint.REGISTRY_ROOTS)


def test_foundation_dirs_home_exactly_the_registry_roots():
    """Every FOUNDATION_REGISTRY_DIRS entry is `foundation/`-anchored, and the set of basename
    tokens is EXACTLY the 17 registry roots (a bijection, one home per root) — so a registry can
    never appear in one whitelist without a matching entry in the other."""
    fdirs = _bash_var_tokens("FOUNDATION_REGISTRY_DIRS")
    assert fdirs, "FOUNDATION_REGISTRY_DIRS is empty"
    assert all(p.startswith("foundation/") for p in fdirs)
    bases = {p.rsplit("/", 1)[-1] for p in fdirs}
    assert bases == set(lint.REGISTRY_ROOTS)
    # No two roots share a home (bijection): equal cardinalities across paths, bases, roots.
    assert len(fdirs) == len(bases) == len(lint.REGISTRY_ROOTS)


def test_dimension_axes_live_under_foundation_dimensions():
    """(3E) The tokens homed under `foundation/dimensions/` are EXACTLY the §3/§4 dimension axes
    (`pipeline.layout.DIMENSION_AXES`) — no axis misfiled elsewhere, no non-axis smuggled in."""
    fdirs = _bash_var_tokens("FOUNDATION_REGISTRY_DIRS")
    under_dims = {
        p.rsplit("/", 1)[-1] for p in fdirs if p.startswith("foundation/dimensions/")
    }
    assert under_dims == set(layout.DIMENSION_AXES)


def test_foundation_dirs_match_registry_base_once_populated():
    """DUAL-SAFE value-parity: the hard lock that `FOUNDATION_REGISTRY_DIRS` == the VALUES of the
    Python SSOT `pipeline.layout.REGISTRY_BASE`, and its keys == the registry roots. INERT while
    `REGISTRY_BASE` is empty (B-1/B-2, pre-foundation-move); it engages the moment B-3 fills the
    map — from then on a guard↔layout drift fails this test."""
    if not layout.REGISTRY_BASE:
        pytest.skip(
            "pipeline.layout.REGISTRY_BASE is empty (B-2, pre-foundation-move) — "
            "value-parity engages once B-3 fills the map"
        )
    fdirs = _bash_var_tokens("FOUNDATION_REGISTRY_DIRS")
    assert fdirs == set(layout.REGISTRY_BASE.values())
    assert set(layout.REGISTRY_BASE) == set(lint.REGISTRY_ROOTS)
