"""Authoring layer C5b: `pipeline generate --save-selection ID` — the SAVE side (§8, D4/D9/D10).

`--save-selection` persists a run's OWN fan-out as a replayable `selections/<id>.md`:
`{base, variants}` where `base` is the recipe REFERENCE the run used (kept as a reference so a
later base edit surfaces honestly as a new id, D10) and `variants` is the EXPLICIT per-deliverable
array — the product ALREADY applied, driven 1:1 on reload (C5c), NEVER re-multiplied (B4). Each
variant is FLOOR-FAITHFUL: the content `coordinate` carries only the run's explicit content picks
(unselected axes ride the base/cascade on reload); `render` carries the deliverable's single render
coordinate (platform always concrete). The run's shared `--set` tweaks persist under `values`
(§12.5 terminology — a persisted scope holds CONFIGURATION, never an "override").

Two doors are exercised: the per-deliverable capture off the SINGLE resolve (`resolve_plan`,
`Plan.selection_variants`) — a pure read side-channel, byte-identical to a resolve WITHOUT it — and
the friendly `generate --save-selection` CLI end to end on the no-spend (preview) door AND the
`--go` drive. The boundary (rule 4) holds exactly like a recipe: a client (`x-`) binding is REFUSED
from the public `selections/` root and homes under `workspaces/<ws>/selections/x-…`.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline import __main__ as cli
from pipeline import authoring
from pipeline.cascade import CascadeEnv
from pipeline.entries import load_entry
from pipeline.fanout import SelectionRequest
from pipeline.lint import REGISTRY_ROOTS
from pipeline.plan import Plan, plan_payload, resolve_plan
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC_BODY = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
SUBSET = ("x-repo",)
COMMITS = {"x-repo": "c0ffee0123ab"}

#: A minimal framework-only variant (no `x-` binding → the public homing path).
FW_VARIANT = {"coordinate": {"persona": "technical-evaluator"}, "render": {"platform": "github"}}


# --- fixtures ---------------------------------------------------------------------------------


def build_root(tmp_path: Path) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (mirrors
    `tests/test_cli_generate.build_root`), so `resolve_plan` binds shipped entries."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = REPO_ROOT / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    topics = root / "workspaces" / WS / "topics"
    topics.mkdir(parents=True)
    for tid, why in (("x-t-alpha", "First."), ("x-t-beta", "Second.")):
        (topics / f"{tid}.md").write_text(TOPIC_BODY.format(tid=tid, why=why), encoding="utf-8")
    return root


def plan_for(root: Path, request: SelectionRequest, **kwargs) -> Plan:
    env = CascadeEnv(root, workspace=WS)
    return resolve_plan(env, request, source_subset=SUBSET, source_commit=COMMITS, **kwargs)


def selection_variants(path: Path) -> list[dict]:
    """Round-trip the written selection through the C5a schema and return its variant list."""
    entry = load_entry(path, authoring.load_selection_schema())
    return list(entry.attributes.get("variants") or [])


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


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke dispatch registry so the AFTER-work money-safety
    assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def argv(root: Path, *extra: str) -> list[str]:
    return [
        "--recipe", "explainer-post",
        "--workspace", WS,
        "--root", str(root),
        *extra,
    ]


# --- the per-deliverable capture off the SINGLE resolve (Plan.selection_variants) -------------


def test_capture_is_identity_neutral(tmp_path: Path) -> None:
    """The load-bearing gate: the capture is a pure read side-channel. `plan_hash`,
    `artifact_ids()`, `deliverable_ids()` AND the whole canonical payload are byte-identical with
    the capture (explain=True) and without it — base ref/filename NEVER enter any preimage."""
    root = build_root(tmp_path)
    request = SelectionRequest(
        recipe="explainer-post",
        topics=["x-t-alpha", "x-t-beta"],
        platforms=["github", "linkedin"],
    )
    off = plan_for(root, request, explain=False)
    on = plan_for(root, request, explain=True)
    assert off.plan_hash == on.plan_hash
    assert off.artifact_ids() == on.artifact_ids()
    assert off.deliverable_ids() == on.deliverable_ids()
    assert plan_payload(off) == plan_payload(on)
    # present only when captured, and never part of the canonical payload
    assert off.selection_variants is None
    assert on.selection_variants is not None


def test_capture_is_floor_faithful_and_per_deliverable(tmp_path: Path) -> None:
    """One variant PER DELIVERABLE, in `deliverable_ids()` order; each coordinate omits the
    UNSELECTED content axes (persona/format/voice/goals ride the base recipe) and each render omits
    the unselected render slots — only the run's explicit picks survive (reference-faithful)."""
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(recipe="explainer-post", topics=["x-t-alpha"], platforms=["github"]),
        explain=True,
    )
    assert plan.selection_variants is not None
    assert len(plan.selection_variants) == len(plan.deliverable_ids()) == 1
    (variant,) = plan.selection_variants
    # floor-faithful: ONLY the explicit topic pick (the recipe pins persona/format/goals — omitted)
    assert variant["coordinate"] == {"topic": "x-t-alpha"}
    # render carries the concrete platform; the cascade-defaulted slots are omitted
    assert variant["render"] == {"platform": "github"}


def test_capture_multi_platform_is_n_by_m_grouped_by_content(tmp_path: Path) -> None:
    """A multi-platform run: each artifact yields MULTIPLE variants that SHARE one content
    coordinate — the C5c flag (the reload must group them back into one artifact). The saved array
    is the run's OWN product already applied (N content × M render), driven 1:1 on reload."""
    root = build_root(tmp_path)
    plan = plan_for(
        root,
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-t-alpha", "x-t-beta"],
            platforms=["github", "linkedin"],
        ),
        explain=True,
    )
    variants = list(plan.selection_variants or [])
    assert len(variants) == len(plan.deliverable_ids()) == 4  # 2 content × 2 render
    # each content coordinate appears with BOTH platforms (the group-by-content C5c case)
    by_topic: dict[str, set[str]] = {}
    for v in variants:
        by_topic.setdefault(v["coordinate"]["topic"], set()).add(v["render"]["platform"])
    assert by_topic == {"x-t-alpha": {"github", "linkedin"}, "x-t-beta": {"github", "linkedin"}}


# --- the friendly `generate --save-selection` CLI, no-spend (preview) door --------------------


def test_generate_save_selection_writes_n_variants_no_cartesian(tmp_path: Path, capsys) -> None:
    """Real end-to-end on the no-spend door: `--topic a --topic b --platform github
    --save-selection` writes a selection with EXACTLY 2 variants (== the planned deliverable
    count), each carrying its OWN render — never a cross product beyond the run's own fan-out."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--topic", "x-t-beta", "--platform", "github",
             "--save-selection", "x-launch-set")
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "saved selection 'x-launch-set'" in out
    # instance provenance (x- topics) → homed under the workspace, NEVER the public root
    path = root / "workspaces" / WS / "selections" / "x-launch-set.md"
    assert path.exists()
    assert not list((root / "selections").glob("x-launch-set.md"))
    text = path.read_text(encoding="utf-8")
    # the `grep -c '^- '` variant-count assertion == the planned deliverable count (2)
    assert sum(1 for line in text.splitlines() if line.startswith("- ")) == 2
    variants = selection_variants(path)
    assert len(variants) == 2
    assert {v["coordinate"]["topic"] for v in variants} == {"x-t-alpha", "x-t-beta"}
    # each variant carries its own render (platform), not a broadcast cross product
    assert all(v["render"] == {"platform": "github"} for v in variants)


def test_single_run_saves_one_variant(tmp_path: Path, capsys) -> None:
    """A single-artifact run → a 1-variant selection (per-deliverable == one-per-artifact here)."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--platform", "github", "--save-selection", "x-one")
    )
    assert code == 0
    path = root / "workspaces" / WS / "selections" / "x-one.md"
    assert len(selection_variants(path)) == 1


def test_variant_field_named_values_not_overrides(tmp_path: Path, capsys) -> None:
    """The run's shared `--set` tweaks persist under `values`, NEVER `overrides` (D4/§12.5)."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--platform", "github",
             "--set", "voice.formality=2", "--save-selection", "x-tuned")
    )
    assert code == 0
    path = root / "workspaces" / WS / "selections" / "x-tuned.md"
    text = path.read_text(encoding="utf-8")
    assert "values:" in text
    assert "overrides" not in text
    (variant,) = selection_variants(path)
    assert variant["values"] == {"voice.formality": 2}


def test_client_binding_refused_from_public(tmp_path: Path, capsys) -> None:
    """A client (`x-`) content binding under a FRAMEWORK (non-`x-`) selection id is refused from
    the public root (rule 4) — exit 1, and NO file lands anywhere."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--platform", "github",
             "--save-selection", "public-leak")
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "not an instance id" in err or "client/instance" in err
    assert not (root / "selections" / "public-leak.md").exists()
    assert not (root / "workspaces" / WS / "selections" / "public-leak.md").exists()


def test_save_selection_without_go_builds_no_continue_handler(tmp_path, monkeypatch) -> None:
    """Money-safety (§21.9): saving a PREVIEWED plan (no --go) constructs ONLY the begin-session
    handler — the save is a pure file write, never a session/spend verb or a live runner."""
    root = build_root(tmp_path)
    constructed: list[str] = []
    real = session.continue_session_handler

    def spy(*args, **kwargs):
        constructed.append("continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "continue_session_handler", spy)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--platform", "github", "--save-selection", "x-safe")
    )
    assert code == 0
    assert constructed == []  # no continue-session handler / live runner instantiated
    assert (root / "workspaces" / WS / "selections" / "x-safe.md").exists()


def test_save_selection_refused_when_no_deliverable(tmp_path: Path, capsys) -> None:
    """A compose-only plan (no platform) resolves no deliverable → the save is refused loudly
    (a saved selection replays a fan-out; there is nothing to replay)."""
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--save-selection", "x-empty")
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "no deliverable" in err
    assert not (root / "workspaces" / WS / "selections" / "x-empty.md").exists()


# --- the `--go` drive door: save AFTER the drive ----------------------------------------------


def test_save_selection_with_go_saves_after_drive(tmp_path: Path, capsys) -> None:
    """`--save-selection` works WITH `--go` too: the plan drives to completion through the injected
    runner (no live spend), then the fan-out is saved."""
    root = build_root(tmp_path)
    runner = FakeRun()
    code = cli._cmd_generate(
        argv(root, "--topic", "x-t-alpha", "--platform", "github", "--go",
             "--save-selection", "x-go"),
        run_artifact=runner,
    )
    assert code == 0
    assert runner.calls  # the drive actually ran (through the injected seam)
    path = root / "workspaces" / WS / "selections" / "x-go.md"
    assert len(selection_variants(path)) == 1


# --- the pure serializer (public homing, round-trip, overwrite guard) -------------------------


def test_public_framework_only_selection_via_serializer(tmp_path: Path) -> None:
    """A framework-only selection (no `x-` binding) homes PUBLIC (`selections/<id>.md`) and
    round-trips through the C5a schema — the envelope floors ride (base text, variants list)."""
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "selections", root / "selections")
    variants = [
        {"coordinate": {"persona": "technical-evaluator", "format": "short-opinion-post"},
         "render": {"platform": "github"}}
    ]
    target = authoring.write_selection(root, "launch-set", "explainer-post", variants)
    assert target.provenance == "framework"
    assert target.path == root / "selections" / "launch-set.md"
    reparsed = selection_variants(target.path)
    assert reparsed == variants  # byte-round-trip of the delta interior


def test_client_binding_homes_under_workspace_via_serializer(tmp_path: Path) -> None:
    """An `x-`-id selection with a client binding homes under `workspaces/<ws>/selections/`."""
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "selections", root / "selections")
    (root / "workspaces" / WS).mkdir(parents=True)
    variants = [{"coordinate": {"topic": "x-t-alpha"}, "render": {"platform": "github"}}]
    target = authoring.write_selection(root, "x-client", "explainer-post", variants, workspace=WS)
    assert target.provenance == "instance"
    assert target.path == root / "workspaces" / WS / "selections" / "x-client.md"


def test_overwrite_guard_headless_then_force(tmp_path: Path) -> None:
    """Refuse-if-exists headless; `--force` overrides (D8, reused from C2a)."""
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "selections", root / "selections")
    variants = [FW_VARIANT]
    authoring.write_selection(root, "dup", "explainer-post", variants, isatty=lambda: False)
    with pytest.raises(authoring.AuthoringError, match="already exists"):
        authoring.write_selection(root, "dup", "explainer-post", variants, isatty=lambda: False)
    # --force overrides
    target = authoring.write_selection(root, "dup", "explainer-post", variants, force=True)
    assert target.path.exists()


def test_non_slug_selection_id_refused_loud(tmp_path: Path) -> None:
    """A non-§7.4 selection id is a loud typed refusal (never a silent repair, §3.1)."""
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "selections", root / "selections")
    variants = [FW_VARIANT]
    with pytest.raises(authoring.AuthoringError, match="slug"):
        authoring.write_selection(root, "Not A Slug", "explainer-post", variants)


def test_variant_missing_platform_refused(tmp_path: Path) -> None:
    """A variant without a concrete `platform` is refused (§7.4: a deliverable requires routing)."""
    root = tmp_path / "root"
    root.mkdir()
    shutil.copytree(REPO_ROOT / "selections", root / "selections")
    with pytest.raises(authoring.AuthoringError, match="platform"):
        authoring.write_selection(
            root, "bad", "explainer-post",
            [{"coordinate": {"persona": "technical-evaluator"}, "render": {}}],
        )
