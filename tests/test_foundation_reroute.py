"""Reorg B-3 acceptance proofs: the `foundation/` flip is COMPLETE + BEHAVIOR-PRESERVING.

Two permanent guards that only pass once every framework registry resolves through
`pipeline.layout.registry_dir` against the MOVED (`foundation/`-anchored) on-disk tree:

  1. **Anti-regression — `list <registry>` off the REAL moved repo.** The discovery layer
     (`_list_registry`, the reroute-exercising core of the `list` verb) enumerates each shipped
     registry via `registry_dir`. If ANY of the reroute sites had been left flat, the corresponding
     registry would resolve to a now-empty/absent path and come back EMPTY — so a non-empty
     assertion over the whole matrix FAILS LOUD on a missed reroute. `dimensions` is the strongest
     single signal: it proves all nine §3/§4 axis directories resolve `foundation/`-anchored.

  2. **Journal-csl render proof.** A `journal-strict-look` presentation is resolved from the moved
     repo and lowered through the REAL production `filesystem_asset_loader`, FENCED to
     `registry_dir(root, "presentations")` (= `foundation/dimensions/presentations`). The look's
     declared `csl` now points at `foundation/dimensions/presentations/assets/csl/numeric.csl`, and
     the fenced loader reads those bytes WITHOUT a `PresentationError` — proving the citation-style
     asset moved WITH its fence (the asset resolves INSIDE the moved presentations home). No pandoc,
     no live LLM: the full citing byte-render is covered by `tests/test_journal_scenario.py`.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pipeline import layout
from pipeline.api import discovery
from pipeline.asset_loader import filesystem_asset_loader
from pipeline.cascade import CascadeEnv
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.presentation import lower, presentation_from_entry

REPO_ROOT = Path(__file__).resolve().parents[1]
USER = "acme"
WS = "reroute-demo"
_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"


# ---------------------------------------------------------------------------------------------
# (1) Anti-regression: every registry resolves NON-EMPTY off the moved repo via the reroute.
# ---------------------------------------------------------------------------------------------


def _reg_ids(type_name: str) -> set[str]:
    """The ids the discovery `list` core enumerates for a directly-listable §5 registry — read
    through `registry_dir` off the REAL moved repo."""
    return {r["id"] for r in discovery._list_registry(REPO_ROOT, type_name)}


def _axis_ids(axis: str) -> set[str]:
    """The entry ids for one §3/§4 dimension axis (via `dimension-entries`, which walks every axis
    through `registry_dir`)."""
    return {
        r["id"]
        for r in discovery._list_registry(REPO_ROOT, "dimension-entries")
        if r.get("dimension") == axis
    }


def test_foundation_reroute_lists_every_registry_off_the_moved_repo() -> None:
    """Anti-regression: the discovery `list` layer resolves the whole matrix NON-EMPTY off the
    MOVED tree. A missed reroute site would surface an empty registry and fail here."""
    # dimensions: all nine axis DIRECTORIES resolve `foundation/`-anchored (the strongest signal).
    assert {r["id"] for r in discovery._list_registry(REPO_ROOT, "dimensions")} == set(
        layout.DIMENSION_AXES
    )

    # recipes: the framework default recipe is enumerable.
    assert "explainer-post" in _reg_ids("recipes")

    # §3/§4 dimension axes that ship framework entries — exact membership counts (topics is
    # workspace-owned, so it legitimately ships zero framework entries and is not counted here).
    assert len(_axis_ids("personas")) == 6
    assert len(_axis_ids("formats")) == 9
    assert len(_axis_ids("platforms")) == 9
    assert len(_axis_ids("voices")) == 2
    assert len(_axis_ids("goals")) == 3
    assert len(_axis_ids("languages")) == 1
    assert len(_axis_ids("output-types")) == 7
    assert len(_axis_ids("presentations")) == 4

    # directly-listable §5 registries — non-empty with their shipped membership.
    assert len(_reg_ids("content-kinds")) == 6
    assert len(_reg_ids("render-targets")) == 7
    assert len(_reg_ids("lexicons")) == 1
    # NOTE: the shipped folio-types registry has exactly ONE framework entry (`repo-docs`); the
    # build note's "(7)" was inaccurate. Assert the real, non-empty state.
    assert _reg_ids("folio-types") == {"repo-docs"}

    # grounding `sources` ships schema-only (no framework entries), but its DIR must still resolve
    # `foundation/`-anchored — proving the grounding-bin reroute (a bare `root / "sources"` would
    # miss it entirely).
    assert (registry_dir(REPO_ROOT, "sources") / "_schema.yaml").is_file()

    # And every registry token's home is genuinely under `foundation/` (the physical flip landed).
    for token in REGISTRY_ROOTS:
        home = registry_dir(REPO_ROOT, token)
        assert home.is_dir(), f"{token} did not resolve to a real dir — a reroute site was missed"
        assert home.relative_to(REPO_ROOT).parts[0] == "foundation"


# ---------------------------------------------------------------------------------------------
# (2) Journal-csl render proof: the citation-style asset resolves INSIDE the moved fence.
# ---------------------------------------------------------------------------------------------


def _build_reroute_root(tmp_path: Path) -> Path:
    """A hermetic world with the REAL framework registries copied through `registry_dir` (so they
    land `foundation/`-anchored, incl. `presentations/assets/csl/*.csl`) + an instance defaults file
    + an empty workspace — the minimum the presentation resolve + lower path needs."""
    root = tmp_path / "root"
    root.mkdir()
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2_DEFAULTS, encoding="utf-8")
    (root / "users" / USER / "workspaces" / WS).mkdir(parents=True)
    return root


def test_journal_strict_look_csl_resolves_inside_the_moved_fence(tmp_path) -> None:
    """The `journal-strict-look` citation style resolves + reads through the PRODUCTION fenced
    loader pointed at the MOVED presentations home — proving the fence moved WITH the csl."""
    root = _build_reroute_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    look = env.resolver.resolve("presentations", "journal-strict-look")

    # The REAL production loader, FENCED to the moved presentations home
    # (`<root>/foundation/dimensions/presentations`).
    loader = filesystem_asset_loader(
        resolve_base=root, contain_root=registry_dir(root, "presentations")
    )
    pres = presentation_from_entry(
        {**look.defaults(), **look.effective, "id": look.id},
        load_asset=loader,
        defaults=look.defaults(),
    )
    render_inputs = lower(pres, "html5", "html", target_engine="")

    # The look declares its citation STYLE at the `foundation/`-anchored home (B-3 rewrite).
    assert render_inputs.csl is not None
    csl_path = render_inputs.csl[0]
    assert csl_path == "foundation/dimensions/presentations/assets/csl/numeric.csl"

    # PROOF the fence moved WITH the csl: the production loader resolves that repo-root-relative
    # path INSIDE the `foundation/dimensions/presentations` fence and reads the real bytes — a
    # `PresentationError` here would mean the asset escaped (or missed) the moved fence.
    data = loader(csl_path)
    assert data, "the moved csl asset read back empty"
    on_disk = registry_dir(root, "presentations") / "assets" / "csl" / "numeric.csl"
    assert data == on_disk.read_bytes()
