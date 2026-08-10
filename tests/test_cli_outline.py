"""CLI-UX C3b: `pipeline outline emit` / `pipeline outline drive` — the FRIENDLY two-phase door.

These wire the EXISTING DR-3 legs (`emit-outline` + begin-session's ingest) into the operator CLI
via the SAME C3a DIRECT-LIBRARY-HANDLER pattern: `invoke.invoke(..., handlers={verb: handler})`.
`handlers=` is a PER-CALL override that NEVER writes the module-global `_VERB_HANDLERS` (R1), so:

  - the §21.9 money-safety invariant holds — `pipeline invoke begin-session` stays `HandlerNotWired`
    (exit 3), and the CLI door only ever registers the safe stateless verbs (render + fetch-by-id);
  - `outline emit` (Tier-A) and `outline drive` (without `--go`) construct NO continue-session
    handler → the LIVE runner is never instantiated → ZERO spend by construction;
  - `outline drive --go` drives `continue-session generate-next` through an INJECTED `run_artifact`
    seam, proving the spend path works WITHOUT spending live subscription quota.

Runs against the REAL shipped registries (copied into `tmp_path` — the repo is read-only toward the
suite), so `resolve_compose` / `resolve_plan` bind real entries. No live subscription call, no
network. `outline drive <f>` and `generate --outline <f>` are asserted to be the SAME normalizer
path (identical begin-session params).

HARD C3b/C7 BOUNDARY: these tests assert the two subcommand wrappers ONLY — NO drift guard, NO
`--from`/`--allow-drift`, NO `outline-config-*` codes. Those land in C6/C7.

S-2: this file carries an AUTOUSE snapshot/restore fixture around the module-global
`invoke._VERB_HANDLERS` (the idiom copied from `tests/test_emit_outline.py:89-97`), so the
AFTER-work negative assertions can never be polluted by a sibling test's registration.
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
from pipeline.ids import parse_id
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.store import WorkspaceStore, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
OUTLINE_MD = "# Launch outline\n\n- Problem\n- Approach\n- Ship\n"


# --- fixtures ---------------------------------------------------------------------------------


def build_root(
    tmp_path: Path, *, topics: tuple[tuple[str, str], ...] = (("x-t-alpha", "First."),)
) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (REC-3 read-only) — the
    SAME shape `tests/test_cli_generate.py` / `tests/test_emit_outline.py` build."""
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
    topics_dir = root / "users" / USER / "zones" / "default" / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    for tid, why in topics:
        (topics_dir / f"{tid}.md").write_text(TOPIC.format(tid=tid, why=why), encoding="utf-8")
    return root


def store_for(root: Path) -> WorkspaceStore:
    return WorkspaceStore.at(root, USER, WS, zone="default")


def write_outline(tmp_path: Path, text: str = OUTLINE_MD, *, name: str = "draft.md") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


class FakeRun:
    """The injected per-item generation seam (stands in for `driver._run_artifact`): it
    MATERIALIZES the artifact-id in the store (so `is_done` is true) and returns a minimal outcome
    carrying the deliverable ids — never a live compose/render call. `block_all` fails with a
    `DriverError` (the SM1 per-item-block probe)."""

    def __init__(self, *, block_all: bool = False) -> None:
        self.calls: list[str] = []
        self._block_all = block_all

    def __call__(self, *, store: WorkspaceStore, item, **_kwargs):
        aid = item.artifact_id
        self.calls.append(aid)
        if self._block_all:
            raise DriverError(f"driver-error: injected per-item block for {aid}")
        store.output_path(aid).write_bytes(b"{}\n")
        deliverables = tuple(
            SimpleNamespace(deliverable_id=d.deliverable_id) for d in item.deliverables
        )
        return SimpleNamespace(artifact_id=aid, deliverables=deliverables)


@pytest.fixture(autouse=True)
def _clean_registry():
    """S-2: snapshot/restore the module-global invoke dispatch registry so the AFTER-work negative
    assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def emit_flags(root: Path, *extra: str) -> list[str]:
    """The minimal friendly emit invocation (NO render axes — emit is compose-only)."""
    return [
        "--recipe", "explainer-post",
        "--topic", "x-t-alpha",
        "--workspace", WS, "--user", USER,
        "--root", str(root),
        *extra,
    ]


def drive_flags(root: Path, *extra: str) -> list[str]:
    """The minimal friendly drive invocation (mirrors `test_cli_generate.base_argv`): one topic +
    one platform → a one-item plan the ingested outline attaches to."""
    return [
        "--recipe", "explainer-post",
        "--topic", "x-t-alpha",
        "--platform", "github",
        "--workspace", WS, "--user", USER,
        "--root", str(root),
        *extra,
    ]


def _handle_id(out: str) -> str:
    """Extract the printed artifact-id from the `handle` line (a relative assertion — no pin)."""
    line = next(line for line in out.splitlines() if line.startswith("handle"))
    return line.split(":", 1)[1].strip()


# --- §21.9 money-safety invariant -------------------------------------------------------------


def test_invoke_begin_session_is_exit_3_and_render_fetch_only(tmp_path):
    # The §21.9 test: `pipeline invoke begin-session` reaches a KNOWN but CLI-unwired verb →
    # `HandlerNotWired` → exit 3, and the ONLY KNOWN verbs the door registers are render +
    # fetch-by-id (the live-quota session verbs stay structurally out).
    root = build_root(tmp_path)
    code = invoke_mod.main_cli(
        [
            "begin-session", "--workspace", WS, "--user", USER,
            "--params-json", "{}", "--root", str(root),
        ]
    )
    assert code == 3
    assert set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS) == {"render", "fetch-by-id"}


# --- outline emit: Tier-A, prints the handle, no spend ----------------------------------------


def test_outline_emit_prints_artifact_id(tmp_path, capsys):
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    code = cli._cmd_outline(["emit", str(ofile), *emit_flags(root)])
    out = capsys.readouterr().out
    assert code == 0
    aid = _handle_id(out)
    assert parse_id(aid).family == "artifact"  # a real a-… artifact-id (relative, no pin)
    assert "artifact-id:" in out
    # The direct-handler pattern never touched the module-global registry (no verb registered).
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))

    # A re-emit of the SAME bytes is the idempotent already-materialized no-op — same handle id.
    code2 = cli._cmd_outline(["emit", str(ofile), *emit_flags(root)])
    out2 = capsys.readouterr().out
    assert code2 == 0
    assert "already-materialized" in out2
    assert _handle_id(out2) == aid


def test_outline_emit_builds_no_continue_handler(tmp_path, monkeypatch):
    # emit is Tier-A: it must construct ONLY `emit_outline_handler` — never the continue-session
    # handler (whose default `run_artifact` is the LIVE transport). Spy the factory.
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    constructed: list[str] = []
    real = session.continue_session_handler

    def spy(*args, **kwargs):
        constructed.append("continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "continue_session_handler", spy)
    code = cli._cmd_outline(["emit", str(ofile), *emit_flags(root)])
    assert code == 0
    assert constructed == []  # NO continue-session handler / live runner instantiated on emit


def test_outline_emit_never_registers_session_verbs(tmp_path, monkeypatch):
    # The direct-handler pattern never calls `register_api_handlers`/`register_session_handlers`,
    # so the module-global registry stays clean (§21.9).
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    called: list[str] = []
    monkeypatch.setattr(session, "register_api_handlers", lambda *a, **k: called.append("api"))
    monkeypatch.setattr(
        session, "register_session_handlers", lambda *a, **k: called.append("session")
    )
    code = cli._cmd_outline(["emit", str(ofile), *emit_flags(root)])
    assert code == 0
    assert called == []
    assert "emit-outline" not in invoke_mod._VERB_HANDLERS
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_outline_emit_missing_file_is_usage_exit_2(tmp_path):
    root = build_root(tmp_path)
    code = cli._cmd_outline(["emit", str(tmp_path / "nope.md"), *emit_flags(root)])
    assert code == 2


def test_outline_emit_empty_outline_is_refusal_exit_1(tmp_path):
    # An empty / no-substance outline is a typed per-item block (§15) that mints no artifact → a
    # refusal (exit 1); nothing spent.
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path, "   \n\n  \n")
    code = cli._cmd_outline(["emit", str(ofile), *emit_flags(root)])
    assert code == 1


def test_outline_emit_missing_workspace_is_usage_exit_2(tmp_path):
    # No --workspace and nothing to infer → a usage error (exit 2) — never a silent default.
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    code = cli._cmd_outline(
        ["emit", str(ofile), "--recipe", "explainer-post", "--topic", "x-t-alpha",
         "--root", str(root)]
    )
    assert code == 2


# --- outline drive: dry-run (default) vs. --go (drive) ----------------------------------------


def test_outline_drive_dry_run_prints_spend_scope(tmp_path, capsys):
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    code = cli._cmd_outline(["drive", str(ofile), *drive_flags(root)])  # no --go → dry-run
    out = capsys.readouterr().out
    assert code == 0
    assert "spend-scope:" in out
    assert "dry-run: nothing spent" in out
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_outline_drive_without_go_builds_no_continue_handler(tmp_path, monkeypatch):
    # The zero-spend-by-construction guarantee: `outline drive` without `--go` constructs ONLY the
    # begin-session handler — never `continue_session_handler` (no live runner seam instantiated).
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    constructed: list[str] = []
    real = session.continue_session_handler

    def spy(*args, **kwargs):
        constructed.append("continue")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "continue_session_handler", spy)
    code = cli._cmd_outline(["drive", str(ofile), *drive_flags(root)])
    assert code == 0
    assert constructed == []
    assert "begin-session" not in invoke_mod._VERB_HANDLERS
    assert "continue-session" not in invoke_mod._VERB_HANDLERS


def test_outline_drive_go_drives_via_injected_runner(tmp_path, capsys):
    # `outline drive --go` drives the plan to completion through an INJECTED fake runner — the spend
    # path runs to real materialization WITHOUT touching live subscription quota.
    root = build_root(tmp_path)
    store = store_for(root)
    ofile = write_outline(tmp_path)
    run = FakeRun()
    code = cli._cmd_outline(["drive", str(ofile), *drive_flags(root), "--go"], run_artifact=run)
    out = capsys.readouterr().out
    assert code == 0
    assert len(run.calls) == 1  # one topic + the ingested outline → one driven artifact
    assert is_done(store, run.calls[0]) is True  # materialized (the spend path works)
    assert "driving to completion" in out


def test_outline_drive_go_never_registers_session_verbs(tmp_path, monkeypatch):
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    called: list[str] = []
    monkeypatch.setattr(session, "register_api_handlers", lambda *a, **k: called.append("api"))
    monkeypatch.setattr(
        session, "register_session_handlers", lambda *a, **k: called.append("session")
    )
    run = FakeRun()
    code = cli._cmd_outline(["drive", str(ofile), *drive_flags(root), "--go"], run_artifact=run)
    assert code == 0
    assert called == []
    assert "begin-session" not in invoke_mod._VERB_HANDLERS
    assert "continue-session" not in invoke_mod._VERB_HANDLERS
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_outline_drive_go_per_item_block_is_spend_failure_exit_1(tmp_path, capsys):
    # A per-item generation BLOCK during a `--go` drive is a spend failure → exit 1 (SM1), while
    # the envelope itself stays ok.
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    run = FakeRun(block_all=True)
    code = cli._cmd_outline(["drive", str(ofile), *drive_flags(root), "--go"], run_artifact=run)
    out = capsys.readouterr().out
    assert code == 1
    assert "block" in out
    assert len(run.calls) == 1  # the single driven item was attempted (then blocked)


def test_outline_drive_malformed_set_is_usage_exit_2(tmp_path):
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    code = cli._cmd_outline(
        ["drive", str(ofile), *drive_flags(root), "--set", "not-a-valid-override"]
    )
    assert code == 2


# --- outline drive == generate --outline (the single normalizer path) -------------------------


def _spy_begin_params(monkeypatch) -> list[dict]:
    """Patch `invoke.invoke` to record the params of every begin-session call; return the log."""
    seen: list[dict] = []
    real = invoke_mod.invoke

    def spy(verb, workspace, user, params=None, *args, **kwargs):
        if verb == "begin-session":
            seen.append(params)
        return real(verb, workspace, user, params, *args, **kwargs)

    monkeypatch.setattr(invoke_mod, "invoke", spy)
    return seen


def test_outline_drive_is_generate_with_outline(tmp_path, monkeypatch):
    # `outline drive <f>` and `generate --outline <f>` are the SAME normalizer path: identical
    # begin-session params (the ingested-outline drive leg included).
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    seen = _spy_begin_params(monkeypatch)
    assert cli._cmd_outline(["drive", str(ofile), *drive_flags(root)]) == 0
    assert cli._cmd_generate([*drive_flags(root), "--outline", str(ofile)]) == 0
    assert len(seen) == 2
    assert seen[0] == seen[1]  # same begin-session params → single normalizer path
    # the drive leg carries the raw outline text + the coordinate the fanout attaches it to.
    entry = seen[0]["ingest_outlines"][0]
    assert entry["text"] == OUTLINE_MD
    assert entry["coordinate"]["topic"] == "x-t-alpha"


def test_generate_outline_flag_attaches_the_outline(tmp_path, monkeypatch):
    # `generate` WITHOUT `--outline` carries no ingest leg; WITH `--outline` it does (the flag is
    # what attaches the authored outline) — proving the outline is not silently dropped.
    root = build_root(tmp_path)
    ofile = write_outline(tmp_path)
    seen = _spy_begin_params(monkeypatch)
    assert cli._cmd_generate(drive_flags(root)) == 0  # plain generate
    assert cli._cmd_generate([*drive_flags(root), "--outline", str(ofile)]) == 0
    assert "ingest_outlines" not in seen[0]
    assert seen[1]["ingest_outlines"][0]["text"] == OUTLINE_MD


# --- dispatch / usage -------------------------------------------------------------------------


def test_outline_unknown_subcommand_is_usage_exit_2():
    assert cli._cmd_outline(["frobnicate"]) == 2


def test_outline_help_lists_emit_and_drive(capsys):
    code = cli._cmd_outline(["--help"])
    out = capsys.readouterr().out
    assert code == 0
    assert "emit" in out and "drive" in out
