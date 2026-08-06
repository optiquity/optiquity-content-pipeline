"""Increment B, Commit 3 — the A<->B base-equality contract drift-catcher (F5 / S5).

The SAFETY of turning embedding on rests on ONE invariant, pinned at `asset_ref.py:13-19`:

    guard base (A gate)  ==  render re-gate base (B)  ==  --resource-path[0] (B)  ==  store.root

A's compose gate proves — PRE-persist — that every body image reference is contained under
`<store.root>/assets` (`compose.py:540`, `workspace_root=store.root`). B then re-runs that SAME gate
at render time and hands pandoc a `--resource-path` so it opens the figure at that SAME base. If any
one of those three bases silently drifts (e.g. a refactor sets B's base to `store.root/assets`, or
lists `repo_root` first), the compose-time containment proof no longer covers the render-time read —
the whole point of the gate evaporates. This module spies the three bases where the REAL production
code computes them and asserts they are the SAME `store.root`, IN ONE PLACE, so a future drift is
caught by a red test rather than a silent cross-client read.

How it stays faithful (not a re-implementation): it drives
  - the REAL A gate  `compose._asset_containment_note(doc, store)`  — captures A's `workspace_root`;
  - the REAL B leg   `DefaultRenderEngine.serialize_preimage` + `mint_deliverable`  — captures the
    `store_root` B passes to `hash_embedded_assets` AND the `resource_paths` B passes to `dispatch`.
Both A and B call the SAME `asset_ref.assert_asset_refs_contained`, so a single spy on that function
captures A's gate base and B's re-gate base from production code. `dispatch` is spied for the
emitted `resource_paths`. Both spies DELEGATE to the real callee, so containment/render still run.

Drift proof (the plan's literal check): a deliberate source edit changing B's base to
`store.root / "assets"` makes `test_resource_path_base_is_store_root_in_pinned_order` and
`test_all_three_bases_are_the_same_store_root` FAIL (the captured base/resource_paths[0] cease to
equal `str(store.root)`). The in-code `assert` added to each render leg (driver + render engine)
trips on the SAME drift at runtime — belt and suspenders.

Needs pinned pandoc 3.10 (the A gate and the B leg both shell the reader; §17 PA-12 `pandoc_gate`).
"""

from __future__ import annotations

import base64
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from pipeline import asset_ref, compose
from pipeline import dispatch as dispatch_mod
from pipeline.api.render import DefaultRenderEngine, SerializeLeg
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.reconcile import build_fit_binding
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "base-contract"
USER = "acme"
_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
_PANDOC_AVAILABLE = pandoc_available()

#: A tiny valid 1x1 PNG — the contained body figure at `store.root/assets/x.png`.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
_FIGURE_BODY = "![alt text](assets/x.png)"


def _build_root(tmp_path: Path) -> Path:
    """A tmp world carrying the REAL framework registries + an instance defaults file — the minimum
    `DefaultRenderEngine._serialize_inputs` needs to resolve the `html` render-target + `plain`
    presentation (mirrors `tests/test_journal_scenario._build_root`)."""
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


def _embed_leg(root: Path, store: WorkspaceStore) -> SerializeLeg:
    """A `SerializeLeg` for a figure-bearing `html` render on the SAME `store` the A gate is handed,
    with a persisted fit record so `mint_deliverable` reads its ref (mirrors the journal e2e)."""
    fb = build_fit_binding(
        artifact_id="a-0123456789abcdef",
        platform="linkedin",
        language="en",
        preimage={"strategy": {}, "hard-limits": {}, "advisory": {}, "render-dims": {}},
        strategy="pass",
        localize_languages=[],
        gate_outcome="ok",
        revision=False,
        minted_ts="2026-01-01T00:00:00+00:00",
    )
    store.output_path(fb["fitted_id"]).parent.mkdir(parents=True, exist_ok=True)
    store.output_path(fb["fitted_id"]).write_bytes(
        (json.dumps({"ir": {"body": "x"}, "binding": fb}) + "\n").encode()
    )
    return SerializeLeg(
        root=root,
        user=USER,
        workspace=WS,
        store=store,
        fitted_id=fb["fitted_id"],
        fitted_ir={"grounding": {}, "body": _FIGURE_BODY},
        output_type="html",
        presentation="plain",
    )


@dataclass
class _Capture:
    """What the spied A gate + B render leg computed for the SAME figure on the SAME store."""

    store_root: Path
    repo_root: Path
    gate_bases: list  # every `workspace_root` A's gate + B's re-gate passed (all == store.root)
    resource_paths: tuple  # the exact tuple B passed to `dispatch` (order + base pinned)


@pytest.fixture(scope="module")
def capture(tmp_path_factory) -> _Capture:
    """Drive the REAL A gate and the REAL B render leg once, over ONE figure on ONE store, with the
    two production seams spied. Module-scoped (one pandoc-bearing run); manual patch/restore because
    the pytest `monkeypatch` fixture is function-scoped."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the B base-contract MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the base-contract drives the real A gate + B render leg")

    root = _build_root(tmp_path_factory.mktemp("base-contract"))
    store = WorkspaceStore.at(root, USER, WS)
    store.ensure_layout()
    (store.root / "assets").mkdir(parents=True, exist_ok=True)
    (store.root / "assets" / "x.png").write_bytes(_PNG)
    leg = _embed_leg(root, store)

    gate_bases: list = []
    resource_paths_seen: list = []
    real_contain = asset_ref.assert_asset_refs_contained
    real_dispatch = dispatch_mod.dispatch

    def _spy_contain(targets, *, workspace_root):
        # A's compose gate AND B's `hash_embedded_assets` both reach this one function — record the
        # base each passes, then DELEGATE so real containment still runs (the figure IS contained).
        gate_bases.append(workspace_root)
        return real_contain(targets, workspace_root=workspace_root)

    def _spy_dispatch(target, ast, **kwargs):
        # B's render leg hands the emitted `resource_paths` here — record it, then render for real.
        resource_paths_seen.append(kwargs.get("resource_paths", ()))
        return real_dispatch(target, ast, **kwargs)

    asset_ref.assert_asset_refs_contained = _spy_contain
    dispatch_mod.dispatch = _spy_dispatch
    try:
        # (A) the REAL compose-time gate on a figure body handed the SAME store → captures A's base.
        assert compose._asset_containment_note({"body": _FIGURE_BODY}, store) is None
        # (B) the REAL two-phase render leg → captures B's re-gate base (both phases) + res-path.
        engine = DefaultRenderEngine()
        preimage = engine.serialize_preimage(leg)
        mint = engine.mint_deliverable(leg, preimage=preimage, serialize_revision=False)
    finally:
        asset_ref.assert_asset_refs_contained = real_contain
        dispatch_mod.dispatch = real_dispatch

    # sanity: the figure really embedded (else resource_paths would be empty and the test vacuous).
    assert b'src="data:image/png;base64,' in mint.output_bytes
    assert len(resource_paths_seen) == 1 and resource_paths_seen[0], "B must emit a resource-path"
    assert len(gate_bases) >= 2, "both A's gate and B's re-gate must have been captured"
    return _Capture(
        store_root=store.root,
        repo_root=leg.root,
        gate_bases=gate_bases,
        resource_paths=resource_paths_seen[0],
    )


def test_a_gate_and_b_regate_share_the_store_root_base(capture: _Capture):
    # Every base A's compose gate AND B's render re-gate passed to the ONE containment guard is the
    # SAME `store.root` — so A's compose-time containment proof covers B's render-time read (S5).
    assert capture.gate_bases, "the containment guard was never reached"
    for base in capture.gate_bases:
        assert str(base) == str(capture.store_root)


def test_resource_path_base_is_store_root_in_pinned_order(capture: _Capture):
    # The emitted `--resource-path` is `(store.root, repo_root)` — store-root FIRST (a same-named
    # framework asset can never shadow a client figure), repo-root SECOND (resolves a `--csl`).
    assert capture.resource_paths == (str(capture.store_root), str(capture.repo_root))
    assert capture.resource_paths[0] == str(capture.store_root)


def test_all_three_bases_are_the_same_store_root(capture: _Capture):
    # The whole contract in one place: guard == re-gate == resource_paths[0] == store.root.
    bases = {str(b) for b in capture.gate_bases} | {capture.resource_paths[0]}
    assert bases == {str(capture.store_root)}


def test_the_store_root_slash_assets_drift_form_is_rejected(capture: _Capture):
    # The specific drift the plan names: a base of `store.root/assets` (the asset ROOT, not the
    # store root) would break the S5 proof. Assert the captured bases are the store root itself, NOT
    # that drifted form — so editing B's base to `store.root / "assets"` in source makes the two
    # tests above go red (the plan's drift check). Belt: the in-code `assert` in each leg trips too.
    drifted = str(capture.store_root / "assets")
    for base in capture.gate_bases:
        assert str(base) != drifted
    assert capture.resource_paths[0] != drifted
