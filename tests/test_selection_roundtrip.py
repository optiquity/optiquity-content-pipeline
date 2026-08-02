"""Authoring layer C5c: `pipeline generate --selection ID` — LOAD + DRIVE a saved selection (§8,
D4/D10). The round-trip crux: a saved fan-out reloads and re-resolves to a BYTE-IDENTICAL plan, with
NO cartesian re-expansion and NO stale-frozen base.

C5b saved a run's OWN fan-out as `selections/<id>.md` = `{base, variants}` (one
`{coordinate, render}` variant per deliverable — the product ALREADY applied). C5c drives it 1:1:

  1. NO re-product — the driven plan enumerates the saved variants, never `content_combinations` ×
     `render_coordinates`; a curated diagonal reloads to N deliverables, never N×M.
  2. GROUP by content coordinate — a multi-render save (2 topics × 2 platforms → 4 variants) reloads
     to EXACTLY 2 artifacts / 4 deliverables, so `artifact_ids()` gains no duplicate (PC2).
  3. Reference-faithful base ⊕ delta (D10) — `base` is a recipe REFERENCE resolved fresh; a later
     base-recipe EDIT surfaces as a NEW id on reload, never a stale copy.
  4. A duplicate (content, render) variant is a LOUD refusal (PC2 exactly-once), never last-wins.

Both round-trip LEVELS are asserted — `artifact_ids()` (content cover) AND `deliverable_ids()`
(content × render cover): the earlier proof asserting only `artifact_ids()` was inert to a render
blow-up. The CLI door is exercised end to end (preview spends nothing; `--go` drives the grouped
plan through the injected runner and the token round-trip).
"""

from __future__ import annotations

import inspect
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import __main__ as cli
from pipeline import authoring
from pipeline import plan as plan_mod
from pipeline.cascade import CascadeEnv
from pipeline.fanout import (
    FanoutError,
    SelectionRequest,
    coordinate_from_payload,
    render_coordinate_from_payload,
)
from pipeline.lint import REGISTRY_ROOTS
from pipeline.plan import Plan, resolve_plan
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC_BODY = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
SUBSET = ("x-repo",)
COMMITS = {"x-repo": "c0ffee0123ab"}


def build_root(tmp_path: Path) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (mirrors
    `tests/test_save_selection.build_root`), so `resolve_plan` binds shipped entries."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = REPO_ROOT / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    topics = root / "users" / USER / "workspaces" / WS / "topics"
    topics.mkdir(parents=True)
    for tid, why in (("x-t-alpha", "First."), ("x-t-beta", "Second.")):
        (topics / f"{tid}.md").write_text(TOPIC_BODY.format(tid=tid, why=why), encoding="utf-8")
    return root


def original_plan(root: Path, request: SelectionRequest) -> Plan:
    """The plan a fresh cartesian run resolves (explain=True → the C5b variant capture to save)."""
    env = CascadeEnv(root, user=USER, workspace=WS)
    return resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS, explain=True)


def _driven_request(base: str, variants: list[dict]) -> SelectionRequest:
    pairs = [
        (coordinate_from_payload(v["coordinate"]), render_coordinate_from_payload(v["render"]))
        for v in variants
    ]
    return SelectionRequest(recipe=base, render_map=pairs)


def driven_plan(root: Path, base: str, variants: list[dict], values=None) -> Plan:
    """The plan a saved-selection DRIVE re-resolves — the explicit grouped variant list, the run's
    shared `values` lifted back to the override layer (§12.5)."""
    env = CascadeEnv(root, user=USER, workspace=WS, overrides=values or None)
    request = _driven_request(base, variants)
    return resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS)


class FakeRun:
    """The injected per-item generation seam (stands in for `driver._run_artifact`): materializes
    the artifact-id in the store and returns a minimal outcome — never a live render call."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *, store: WorkspaceStore, item, **_kwargs):
        aid = item.artifact_id
        self.calls.append(aid)
        store.output_path(aid).write_bytes(b"{}\n")
        deliverables = tuple(
            SimpleNamespace(deliverable_id=d.deliverable_id) for d in item.deliverables
        )
        return SimpleNamespace(artifact_id=aid, deliverables=deliverables)


# --- the round-trip PROOF (both levels; multi-render exercises the grouping) ------------------


def test_selection_roundtrip_same_plan_hash_artifact_and_deliverable_ids(tmp_path: Path) -> None:
    """The mandatory round-trip: a MULTI-render save (2 topics × 2 platforms → 4 variants) reloads +
    re-resolves to a BYTE-IDENTICAL `plan_hash` AND `artifact_ids()` AND `deliverable_ids()` — and
    to EXACTLY 2 artifacts / 4 deliverables (the grouping; asserting `deliverable_ids()` is what
    makes this inert-proof against a render blow-up)."""
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha", "x-t-beta"], platforms=["github", "linkedin"]
    )
    orig = original_plan(root, request)
    assert len(orig.artifact_ids()) == 2
    assert len(orig.deliverable_ids()) == 4
    authoring.write_selection(
        root, "x-rt", "explainer-post", orig.selection_variants, user=USER, workspace=WS
    )

    base, variants, values = authoring.load_selection(root, "x-rt", user=USER, workspace=WS)
    assert base == "explainer-post"
    reload = driven_plan(root, base, variants, values)

    assert reload.plan_hash == orig.plan_hash
    assert reload.artifact_ids() == orig.artifact_ids()
    assert reload.deliverable_ids() == orig.deliverable_ids()
    # the grouping: 4 saved variants → 2 artifacts × 2 deliverables (NOT re-multiplied to 4×?)
    assert len(reload.artifact_ids()) == 2
    assert len(reload.deliverable_ids()) == 4


def test_multi_render_per_artifact_groups_to_one_item(tmp_path: Path) -> None:
    """The C5c-flagged correctness point: a multi-render save carries MULTIPLE variants sharing one
    content coordinate; on reload they MUST collapse into ONE artifact carrying BOTH render
    coordinates — else `artifact_ids()` gains a duplicate and the cover is not exactly-once."""
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha", "x-t-beta"], platforms=["github", "linkedin"]
    )
    orig = original_plan(root, request)
    authoring.write_selection(
        root, "x-grp", "explainer-post", orig.selection_variants, user=USER, workspace=WS
    )
    base, variants, values = authoring.load_selection(root, "x-grp", user=USER, workspace=WS)
    plan = driven_plan(root, base, variants, values)

    aids = plan.artifact_ids()
    assert len(aids) == 2
    assert len(set(aids)) == 2  # NO duplicate (A,A) — the 4 variants grouped into 2 artifacts
    for item in plan.items:
        assert len(item.deliverables) == 2  # each artifact carries BOTH render coordinates


def test_curated_diagonal_render_yields_n_not_nxm(tmp_path: Path) -> None:
    """A curated DIAGONAL {(topicA, github), (topicB, linkedin)} reloads to EXACTLY 2 deliverables —
    NOT the 4 of the cross product; `deliverable_ids()` == the saved pair (the two off-diagonal
    combos are ABSENT)."""
    root = build_root(tmp_path)
    variants = [
        {"coordinate": {"topic": "x-t-alpha"}, "render": {"platform": "github"}},
        {"coordinate": {"topic": "x-t-beta"}, "render": {"platform": "linkedin"}},
    ]
    authoring.write_selection(root, "x-diag", "explainer-post", variants, user=USER, workspace=WS)
    base, loaded, values = authoring.load_selection(root, "x-diag", user=USER, workspace=WS)
    plan = driven_plan(root, base, loaded, values)

    assert len(plan.artifact_ids()) == 2
    assert len(plan.deliverable_ids()) == 2  # the crux: N, never N×M

    # the diagonal == the union of the two individual single-runs (proves it is exactly those two)
    a = original_plan(
        root, SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"])
    )
    b = original_plan(
        root, SelectionRequest(recipe="explainer-post", topics=["x-t-beta"], platforms=["linkedin"])
    )
    expected = tuple(sorted([*a.deliverable_ids(), *b.deliverable_ids()]))
    assert tuple(sorted(plan.deliverable_ids())) == expected

    # the cross product would ALSO carry (alpha,linkedin) + (beta,github); the diagonal is a strict
    # subset — the two off-diagonal deliverables never materialize
    cross = original_plan(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            platforms=["github", "linkedin"],
        ),
    )
    assert len(cross.deliverable_ids()) == 4
    assert set(plan.deliverable_ids()) < set(cross.deliverable_ids())


def test_roundtrip_with_shared_values_byte_identical(tmp_path: Path) -> None:
    """A run's shared `--set` tweaks persist under `values` and reload to the OVERRIDE layer
    (§12.5): the driven plan is byte-identical (`plan_hash`/ids) to the original tuned run — the
    tweak enters identity via the effective delta, on save AND on reload."""
    root = build_root(tmp_path)
    overrides = {"voice.formality": 2}
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-t-alpha", "x-t-beta"], platforms=["github"]
    )
    env = CascadeEnv(root, user=USER, workspace=WS, overrides=overrides)
    orig = resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS, explain=True)
    authoring.write_selection(
        root,
        "x-tuned-rt",
        "explainer-post",
        orig.selection_variants,
        values=overrides,
        user=USER,
        workspace=WS,
    )

    base, variants, values = authoring.load_selection(root, "x-tuned-rt", user=USER, workspace=WS)
    assert values == overrides  # the shared tweak map lifted back off the variants
    reload = driven_plan(root, base, variants, values)
    assert reload.plan_hash == orig.plan_hash
    assert reload.artifact_ids() == orig.artifact_ids()
    assert reload.deliverable_ids() == orig.deliverable_ids()


def test_n_variants_yield_n_deliverables(tmp_path: Path) -> None:
    """N curated variants (distinct content, one render each) → N deliverables, N artifacts."""
    root = build_root(tmp_path)
    variants = [
        {"coordinate": {"topic": "x-t-alpha"}, "render": {"platform": "github"}},
        {"coordinate": {"topic": "x-t-beta"}, "render": {"platform": "github"}},
    ]
    authoring.write_selection(root, "x-nv", "explainer-post", variants, user=USER, workspace=WS)
    base, loaded, values = authoring.load_selection(root, "x-nv", user=USER, workspace=WS)
    plan = driven_plan(root, base, loaded, values)
    assert len(plan.deliverable_ids()) == 2
    assert len(plan.artifact_ids()) == 2


# --- structural: no product in the load path -------------------------------------------------


def test_no_product_in_selection_load_path() -> None:
    """The saved-array iterator uses NO `itertools`/`product` — the cartesian machinery stays
    EXCLUSIVELY on the non-selection path (`content_combinations` / `render_coordinates` in
    `fanout.py`). `resolve_plan` drives the explicit `request.render_map` instead."""
    src = Path(plan_mod.__file__).read_text(encoding="utf-8")
    assert "itertools" not in src
    assert "product(" not in src
    rp_src = inspect.getsource(plan_mod.resolve_plan)
    # the driven branch drives the EXPLICIT saved array …
    assert "request.render_map" in rp_src
    # … while the product machinery is confined to the non-selection branch (still present there)
    assert "content_combinations(request)" in rp_src
    assert "render_coordinates(" in rp_src


# --- reference-faithful base ⊕ delta (D10): a base edit surfaces as a new id ------------------


def test_base_edit_surfaces_as_new_id_not_stale_copy(tmp_path: Path) -> None:
    """`base` is a REFERENCE, never an inlined copy: a saved variant omits the base's pinned voice,
    so a later EDIT to the base recipe's voice must surface as a NEW id on reload (resolved fresh),
    never a stale frozen config."""
    root = build_root(tmp_path)
    authoring.write_recipe(
        root,
        "mybase",
        {
            "persona": "technical-evaluator",
            "format": "short-opinion-post",
            "voice": "clear-explainer",
            "goals": ["explain"],
        },
    )
    request = SelectionRequest(recipe="mybase", topics=["x-t-alpha"], platforms=["github"])
    orig = original_plan(root, request)
    authoring.write_selection(
        root, "x-be", "mybase", orig.selection_variants, user=USER, workspace=WS
    )

    base, variants, values = authoring.load_selection(root, "x-be", user=USER, workspace=WS)
    # the saved variant omits voice (it rode the base) — so it MUST resolve fresh, not be frozen
    assert all("voice" not in v["coordinate"] for v in variants)
    id_before = driven_plan(root, base, variants, values).artifact_ids()
    assert id_before == orig.artifact_ids()  # faithful round-trip before the edit

    # EDIT the base recipe's voice pin — a different voice enters the identity honestly
    authoring.write_recipe(
        root,
        "mybase",
        {
            "persona": "technical-evaluator",
            "format": "short-opinion-post",
            "voice": "confident-advocate",
            "goals": ["explain"],
        },
        force=True,
    )
    id_after = driven_plan(root, base, variants, values).artifact_ids()
    assert id_after != id_before  # the base edit surfaced as a NEW id (reference-faithful, D10)


# --- a duplicate (content, render) variant is refused loudly ---------------------------------


def test_duplicate_variant_refused(tmp_path: Path) -> None:
    """Two variants resolving to the same (content coordinate, render coordinate) → a loud typed
    refusal on drive (PC2 exactly-once cover; mirrors the DR-3 dedupe), never a silent last-wins."""
    root = build_root(tmp_path)
    variants = [
        {"coordinate": {"topic": "x-t-alpha"}, "render": {"platform": "github"}},
        {"coordinate": {"topic": "x-t-alpha"}, "render": {"platform": "github"}},
    ]
    authoring.write_selection(root, "x-dup", "explainer-post", variants, user=USER, workspace=WS)
    base, loaded, values = authoring.load_selection(root, "x-dup", user=USER, workspace=WS)
    with pytest.raises(FanoutError, match="exactly-once cover"):
        driven_plan(root, base, loaded, values)


# --- the non-selection path is byte-unchanged (the C5c identity invariant) --------------------


def test_non_selection_path_omits_render_map_from_token_inputs(tmp_path: Path) -> None:
    """A NORMAL (non-driven) request's token payload carries NO `render_map` key — omit-when-absent,
    so a non-driven session's token inputs (and thus its re-resolve) stay byte-identical to
    pre-C5c."""
    from pipeline.api.session import _request_payload

    request = SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"])
    assert "render_map" not in _request_payload(request)


# --- the friendly CLI door: preview spends nothing; --go drives the grouped plan --------------


def _argv(root: Path, *extra: str) -> list[str]:
    return ["--workspace", WS, "--user", USER, "--root", str(root), *extra]


def test_generate_selection_previews_then_go_drives(tmp_path: Path, capsys) -> None:
    """End to end on the friendly door: save a 2-variant selection, PREVIEW it (no --go → spends
    nothing, exit 0), then `--go` DRIVES the grouped plan (2 artifacts) through the injected
    runner — exercising the token round-trip (`continue-session` re-resolves the render_map)."""
    root = build_root(tmp_path)
    save_code = cli._cmd_generate(
        _argv(
            root, "--recipe", "explainer-post", "--topic", "x-t-alpha", "--topic", "x-t-beta",
            "--platform", "github", "--save-selection", "x-cli",
        )
    )
    capsys.readouterr()
    assert save_code == 0

    # preview the saved selection — no --go → spends nothing
    code = cli._cmd_generate(_argv(root, "--selection", "x-cli"))
    out = capsys.readouterr().out
    assert code == 0
    assert "dry-run" in out

    # --go drives the grouped plan (2 artifacts) through the injected runner (no live spend)
    runner = FakeRun()
    code = cli._cmd_generate(_argv(root, "--selection", "x-cli", "--go"), run_artifact=runner)
    assert code == 0
    assert len(runner.calls) == 2  # 2 grouped artifacts driven


def test_generate_selection_refuses_axis_flags(tmp_path: Path, capsys) -> None:
    """`--selection` fully specifies the run — combining it with an axis flag is a usage error
    (exit 2), never a silent re-expansion of the curated set."""
    root = build_root(tmp_path)
    cli._cmd_generate(
        _argv(
            root, "--recipe", "explainer-post", "--topic", "x-t-alpha", "--platform", "github",
            "--save-selection", "x-cli2",
        )
    )
    capsys.readouterr()
    code = cli._cmd_generate(_argv(root, "--selection", "x-cli2", "--topic", "x-t-beta"))
    err = capsys.readouterr().err
    assert code == 2
    assert "re-expand" in err


def test_generate_selection_missing_refused(tmp_path: Path, capsys) -> None:
    """A --selection id with no saved file is a loud refusal (exit 1), never a silent empty run."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(_argv(root, "--selection", "x-nope"))
    err = capsys.readouterr().err
    assert code == 1
    assert "no saved selection" in err
