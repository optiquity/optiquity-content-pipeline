"""CLI-UX C3a: `pipeline preview` / `pipeline generate` — the FRIENDLY operator subcommands.

These wire C1 (the `explain` plan projection) + C2 (the door-class-aware normalizer) into the
operator CLI via the DIRECT-LIBRARY-HANDLER pattern: `invoke.invoke(..., handlers={verb: handler})`.
`handlers=` is a PER-CALL override that NEVER writes the module-global `_VERB_HANDLERS` (R1), so:

  - the §21.9 money-safety invariant holds — `pipeline invoke begin-session` stays `HandlerNotWired`
    (exit 3), and the CLI door only ever registers the safe stateless verbs (render + fetch-by-id);
  - `preview` / `generate` (without `--go`) construct ONLY the begin-session handler → the LIVE
    runner is never instantiated → ZERO spend by construction;
  - `generate --go` drives `continue-session generate-next` through an INJECTED `run_artifact` seam,
    proving the spend path works WITHOUT spending live subscription quota.

Runs against the REAL shipped registries (copied into `tmp_path` — the repo is read-only toward the
suite), so `resolve_plan` binds real entries. No live subscription call, no network.

S-2: this file carries an AUTOUSE snapshot/restore fixture around the module-global
`invoke._VERB_HANDLERS`. The negative assertions run AFTER the subcommands run (unlike the
import-time guards at `tests/test_jobrunner.py:526` / `tests/test_session.py`), so without the
snapshot/restore a sibling test's registration could pollute them (the idiom copied from
`tests/test_emit_outline.py:89-97`).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline import __main__ as cli
from pipeline.api.invoke import KNOWN_VERBS
from pipeline.driver import DriverError
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.store import WorkspaceStore, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"


# --- fixtures ---------------------------------------------------------------------------------


def build_root(
    tmp_path: Path, *, topics: tuple[tuple[str, str], ...] = (("x-t-alpha", "First."),)
) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (REC-3 read-only) —
    the SAME shape `tests/test_session.py` builds, so `resolve_plan` binds shipped entries."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    topics_dir = root / "users" / USER / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    for tid, why in topics:
        (topics_dir / f"{tid}.md").write_text(TOPIC.format(tid=tid, why=why), encoding="utf-8")
    return root


def store_for(root: Path) -> WorkspaceStore:
    return WorkspaceStore.at(root, USER, WS)


class FakeRun:
    """The injected per-item generation seam (stands in for `driver._run_artifact`): it
    MATERIALIZES the artifact-id in the store (so `is_done` is true) and returns a minimal outcome
    carrying the deliverable ids — never a live compose/render call. `block`/`block_all` fail with
    a `DriverError` (the SM1 per-item-block probe; a bare `DriverError` carries `stage_code=None` →
    the code-less `block` status)."""

    def __init__(self, *, block: str | None = None, block_all: bool = False) -> None:
        self.calls: list[str] = []
        self._block = block
        self._block_all = block_all

    def __call__(self, *, store: WorkspaceStore, item, **_kwargs):
        aid = item.artifact_id
        self.calls.append(aid)
        if self._block_all or aid == self._block:
            raise DriverError(f"driver-error: injected per-item block for {aid}")
        store.output_path(aid).write_bytes(b"{}\n")
        deliverables = tuple(
            SimpleNamespace(deliverable_id=d.deliverable_id) for d in item.deliverables
        )
        return SimpleNamespace(artifact_id=aid, deliverables=deliverables)


@pytest.fixture(autouse=True)
def _clean_registry():
    """S-2: snapshot/restore the module-global invoke dispatch registry so the AFTER-work
    negative assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def base_argv(root: Path, *extra: str) -> list[str]:
    """The minimal friendly invocation resolving a one-item plan in `testws` (mirrors
    `test_session.base_params`): recipe + one topic + one platform + the workspace/root."""
    return [
        "--recipe", "explainer-post",
        "--topic", "x-t-alpha",
        "--platform", "github",
        "--workspace", WS, "--user", USER,
        "--root", str(root),
        *extra,
    ]


# --- §21.9 money-safety invariant -------------------------------------------------------------


def test_invoke_begin_session_is_exit_3_and_render_fetch_only(tmp_path):
    # The corrected §21.9 test: `pipeline invoke begin-session` reaches a KNOWN but CLI-unwired
    # verb → `HandlerNotWired` → exit 3, and the ONLY KNOWN verbs the door ever registers are the
    # safe stateless render + fetch-by-id (the live-quota session verbs stay structurally out).
    root = build_root(tmp_path)
    code = invoke_mod.main_cli(
        [
            "begin-session", "--workspace", WS, "--user", USER,
            "--params-json", "{}", "--root", str(root),
        ]
    )
    assert code == 3
    assert set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS) == {"render", "fetch-by-id"}


# --- preview: free plan-only door -------------------------------------------------------------


def test_preview_prints_spend_scope(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_preview(base_argv(root))
    out = capsys.readouterr().out
    assert code == 0
    assert "spend-scope:" in out  # the exact spend-estimate line the operator reads for free
    assert "effective settings" in out  # the C1 projection block
    # The direct-handler pattern never touched the module-global registry (no verb registered).
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_preview_builds_no_continue_handler(tmp_path, monkeypatch):
    # preview is plan-only: it must construct ONLY begin-session, never the continue-session
    # handler (whose default `run_artifact` is the LIVE transport). Spy the factory.
    root = build_root(tmp_path)
    constructed: list[str] = []
    real = session.continue_session_handler

    def spy(*args, **kwargs):
        constructed.append("continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "continue_session_handler", spy)
    code = cli._cmd_preview(base_argv(root))
    assert code == 0
    assert constructed == []  # NO continue-session handler / live runner instantiated


# --- generate: dry-run (default) vs. --go (drive) ---------------------------------------------


def test_generate_dry_run_prints_spend_scope(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_generate(base_argv(root))  # no --go → dry-run, identical to preview
    out = capsys.readouterr().out
    assert code == 0
    assert "spend-scope:" in out
    assert "dry-run: nothing spent" in out
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_generate_without_go_builds_no_continue_handler(tmp_path, monkeypatch):
    # The zero-spend-by-construction guarantee: `generate` without `--go` constructs ONLY the
    # begin-session handler — never `continue_session_handler` (no live runner seam instantiated).
    root = build_root(tmp_path)
    constructed: list[str] = []
    real = session.continue_session_handler

    def spy(*args, **kwargs):
        constructed.append("continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "continue_session_handler", spy)
    code = cli._cmd_generate(base_argv(root))
    assert code == 0
    assert constructed == []  # dry-run built no continue-session handler
    assert "begin-session" not in invoke_mod._VERB_HANDLERS
    assert "continue-session" not in invoke_mod._VERB_HANDLERS


def test_generate_go_drives_via_injected_runner(tmp_path, capsys):
    # `generate --go` drives the plan to completion through an INJECTED fake runner — the spend
    # path runs to real materialization WITHOUT touching live subscription quota.
    root = build_root(tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B.")))
    store = store_for(root)
    run = FakeRun()
    code = cli._cmd_generate(
        base_argv(root, "--topic", "x-t-beta", "--go"), run_artifact=run
    )
    out = capsys.readouterr().out
    assert code == 0
    assert len(run.calls) == 2  # both artifacts driven through the injected runner
    for aid in run.calls:
        assert is_done(store, aid) is True  # materialized (the spend path works)
    assert "driving to completion" in out


def test_generate_never_registers_session_verbs(tmp_path, monkeypatch):
    # After a full `generate --go` (injected runner), the module-global registry is UNCHANGED:
    # the direct-handler pattern never calls `register_api_handlers`/`register_session_handlers`.
    root = build_root(tmp_path)
    called: list[str] = []
    monkeypatch.setattr(
        session, "register_api_handlers", lambda *a, **k: called.append("api")
    )
    monkeypatch.setattr(
        session, "register_session_handlers", lambda *a, **k: called.append("session")
    )
    run = FakeRun()
    code = cli._cmd_generate(base_argv(root, "--go"), run_artifact=run)
    assert code == 0
    assert called == []  # never registered a session verb (§21.9 direct-handler pattern)
    assert "begin-session" not in invoke_mod._VERB_HANDLERS
    assert "continue-session" not in invoke_mod._VERB_HANDLERS
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


# --- exit codes -------------------------------------------------------------------------------


def test_generate_refusal_is_exit_1(tmp_path):
    # A begin-session that mints NO token (here: an unknown selection → `not-found`) is a
    # refusal → exit 1 (nothing was spent, nothing to drive).
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        [
            "--recipe", "explainer-post",
            "--topic", "x-missing-topic",
            "--platform", "github",
            "--workspace", WS, "--user", USER,
            "--root", str(root),
        ]
    )
    assert code == 1


def test_generate_malformed_set_is_usage_exit_2(tmp_path):
    # A malformed `--set` is a pre-engine `NormalizeError` (a usage error) → exit 2.
    root = build_root(tmp_path)
    code = cli._cmd_generate(base_argv(root, "--set", "not-a-valid-override"))
    assert code == 2


def test_generate_missing_workspace_is_usage_exit_2(tmp_path):
    # No `--workspace` and nothing to infer → a usage error → exit 2 (never a silent default).
    root = build_root(tmp_path)
    code = cli._cmd_generate(
        ["--recipe", "explainer-post", "--topic", "x-t-alpha", "--platform", "github",
         "--root", str(root)]
    )
    assert code == 2


# --- F1: render axes fan out (repeatable, never last-wins) ------------------------------------


def test_render_axes_repeat_not_last_wins():
    # F1: the four render axes (`--platform`/`--language`/`--output-type`/`--presentation`) are
    # REPEATABLE like the five content axes — a repeated flag ACCUMULATES, never silently drops
    # earlier values (the pre-fix `--platform a --platform b` kept only `b`).
    import argparse

    parser = argparse.ArgumentParser()
    cli._add_friendly_generate_args(parser)
    args = parser.parse_args(
        [
            "--platform", "github", "--platform", "linkedin",
            "--language", "en", "--language", "fr",
            "--output-type", "md", "--output-type", "html",
            "--presentation", "plain", "--presentation", "documentation",
            "--topic", "x-t-alpha",
        ]
    )
    friendly = cli._friendly_from_args(args, spend=False)
    assert friendly["platforms"] == ["github", "linkedin"]  # NOT silently ["linkedin"]
    assert friendly["languages"] == ["en", "fr"]
    assert friendly["output_types"] == ["md", "html"]
    assert friendly["presentations"] == ["plain", "documentation"]
    assert friendly["topics"] == ["x-t-alpha"]  # a content axis — the SAME repeat behavior


def test_two_platforms_fan_out_two_deliverables(tmp_path):
    # F1 end-to-end (through the SAME direct-handler path the CLI uses): one topic × two platforms
    # → ONE artifact, TWO render deliverables (the design's render fan-out — recipes/_schema.yaml
    # "multiple pins = rendering fanout"; `render_coordinates` uses `request.platforms`).
    from pipeline.api.normalize import normalize

    root = build_root(tmp_path)
    friendly = {
        "recipe": "explainer-post",
        "workspace": WS,
        "user": USER,
        "topics": ["x-t-alpha"],
        "platforms": ["github", "linkedin"],
        "explain": True,
        "spend": False,
    }
    normalized = normalize(friendly, door_class="interactive")
    result = invoke_mod.invoke(
        "begin-session",
        normalized.workspace,
        normalized.user,
        normalized.params,
        handlers={"begin-session": session.begin_session_handler()},
        root=str(root),
    )
    ids = result["results"][0]["ids"]
    assert len(ids["artifact_ids"]) == 1  # one topic → one artifact
    assert len(ids["deliverable_ids"]) == 2  # two platforms → two deliverables (fan-out)


def test_generate_go_per_item_block_is_spend_failure_exit_1(tmp_path, capsys):
    # A per-item generation BLOCK during a `--go` drive is a spend failure → exit 1 (the divergence
    # from raw `invoke` the exit map names), while the envelope itself stays ok (SM1).
    root = build_root(tmp_path)
    run = FakeRun(block_all=True)
    code = cli._cmd_generate(base_argv(root, "--go"), run_artifact=run)
    out = capsys.readouterr().out
    assert code == 1
    assert "block" in out
    assert len(run.calls) == 1  # the single planned item was attempted (then blocked)
