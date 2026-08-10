"""CLI-UX C3c: `pipeline list <type>` / `pipeline get <type> <id>` — the FRIENDLY read-only
discovery subcommands (design §21.3).

These wire the discovery `list`/`get` layer into the operator CLI via the SAME direct-handler
pattern as C3a/C3b: `invoke.invoke(..., handlers={"list": <discovery handler>})`, a PER-CALL
override that NEVER writes the module-global `_VERB_HANDLERS` (R1). So the §21.9 money-safety
invariant holds: `pipeline invoke begin-session` stays exit 3, no session verb is ever registered,
and `register_api_handlers`/`register_session_handlers` are never called.

Runs against the REAL shipped registries (copied into `tmp_path`), so `list voices` / `list
lexicons` / `list recipes` enumerate real entries; `list outlines` reads the workspace outline
store. `get` enumerates-then-matches (invoke's Gate-3 isolation refuses a registry NAME / bare
outline digest through the `get` VERB — so the CLI `get` cannot route through it).

S-2: an AUTOUSE snapshot/restore fixture around `invoke._VERB_HANDLERS` (the idiom from
`tests/test_cli_generate.py:97-106`) so the AFTER-work negative assertions can't be polluted.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline import __main__ as cli
from pipeline import outline_store
from pipeline.api import discovery, results
from pipeline.api.invoke import KNOWN_VERBS
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"


def build_root(tmp_path: Path) -> Path:
    """A framework root with the REAL shipped registries (voices/lexicons/recipes/…) + an empty
    workspace store — so `list voices`/`list recipes` bind real entries, off the shared repo."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    WorkspaceStore.at(root, USER, WS, zone="default").ensure_layout()
    return root


@pytest.fixture(autouse=True)
def _clean_registry():
    """S-2: snapshot/restore the module-global invoke dispatch registry so the AFTER-work negative
    money-safety assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


# --- list: enumerate a discovery type by name -------------------------------------------------


def test_list_voices_prints_the_real_entries(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_list(["voices", "--workspace", WS, "--user", USER, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    assert "clear-explainer" in out and "confident-advocate" in out
    assert "provenance=" in out and "path=voices/" in out  # the {id, provenance, path} row shape


def test_list_lexicons_resolves(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_list(["lexicons", "--workspace", WS, "--user", USER, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    assert "house-standard" in out


def test_list_recipes_and_codes_resolve(tmp_path, capsys):
    root = build_root(tmp_path)
    assert cli._cmd_list(["recipes", "--workspace", WS, "--user", USER, "--root", str(root)]) == 0
    assert "explainer-post" in capsys.readouterr().out
    # `codes` is a meta-type: item == the code string, no provenance/path tail.
    assert cli._cmd_list(["codes", "--workspace", WS, "--user", USER, "--root", str(root)]) == 0
    codes_out = capsys.readouterr().out
    for code_name in list(results.CODES)[:3]:
        assert code_name in codes_out


def test_list_outlines_reads_the_workspace_store(tmp_path, capsys):
    root = build_root(tmp_path)
    digest = outline_store.put_outline(
        WorkspaceStore.at(root, USER, WS, zone="default"), "# Intro\n\nReal outline body.\n"
    )
    code = cli._cmd_list(["outlines", "--workspace", WS, "--user", USER, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    assert digest in out  # the bare content-addressed outline digest


def test_list_unknown_type_is_not_found_exit_1(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_list(["nope", "--workspace", WS, "--user", USER, "--root", str(root)])
    err = capsys.readouterr().err
    assert code == 1  # a not-found refusal, NEVER a silent empty exit 0
    assert "not-found" in err or "unknown discovery type" in err


def test_list_filters_narrow_by_provenance(tmp_path, capsys):
    root = build_root(tmp_path)

    def _list_voices(provenance: str) -> int:
        return cli._cmd_list(
            ["voices", "--workspace", WS, "--user", USER, "--root", str(root),
             "--filters", f'{{"provenance": "{provenance}"}}']
        )

    # framework filter → every shipped voice (all provenance: framework) still lists.
    assert _list_voices("framework") == 0
    assert "clear-explainer" in capsys.readouterr().out
    # instance filter → none of the shipped framework voices → an EMPTY (but ok) listing.
    assert _list_voices("instance") == 0
    assert "clear-explainer" not in capsys.readouterr().out


def test_list_bad_filters_json_is_usage_exit_2(tmp_path):
    root = build_root(tmp_path)
    code = cli._cmd_list(
        ["voices", "--workspace", WS, "--user", USER, "--root", str(root), "--filters", "{not json"]
    )
    assert code == 2  # a pre-engine usage error, never a silent proceed


# --- get: fetch one entry by id ---------------------------------------------------------------


def test_get_voice_returns_the_entry(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_get(
        ["voices", "clear-explainer", "--workspace", WS, "--user", USER, "--root", str(root)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "clear-explainer" in out
    assert "provenance:" in out and "path:" in out  # the entry's fields printed


def test_get_outline_returns_the_entry(tmp_path, capsys):
    root = build_root(tmp_path)
    digest = outline_store.put_outline(
        WorkspaceStore.at(root, USER, WS, zone="default"), "# Intro\n\nReal outline body.\n"
    )
    code = cli._cmd_get(
        ["outlines", digest, "--workspace", WS, "--user", USER, "--root", str(root)]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert digest in out and "provenance:" in out


def test_get_unknown_id_is_exit_1(tmp_path, capsys):
    root = build_root(tmp_path)
    code = cli._cmd_get(
        ["voices", "no-such-voice", "--workspace", WS, "--user", USER, "--root", str(root)]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "no voices entry" in err


def test_get_unknown_type_is_exit_1(tmp_path):
    root = build_root(tmp_path)
    assert cli._cmd_get(["nope", "x", "--workspace", WS, "--user", USER, "--root", str(root)]) == 1


# --- §21.9 money-safety: list/get register nothing, spend nothing -----------------------------


def test_list_registers_no_verb_on_a_clean_registry(tmp_path):
    # The direct-handler pattern: `pipeline list` uses a PER-CALL `handlers=` override, so on a
    # clean registry it registers NOTHING (mirrors C3a `test_preview_prints_spend_scope`).
    root = build_root(tmp_path)
    invoke_mod._VERB_HANDLERS.clear()
    cli._cmd_list(["voices", "--workspace", WS, "--user", USER, "--root", str(root)])
    assert not (set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS))


def test_list_leaves_the_safe_render_fetch_baseline_exactly(tmp_path):
    # The coordinator's literal invariant: with the invoke door's safe baseline registered
    # (render + fetch-by-id, exactly as `pipeline invoke <verb>` establishes it, invoke.py:488-489),
    # a `pipeline list` run leaves it UNCHANGED — no session verb added, no safe verb removed.
    root = build_root(tmp_path)
    invoke_mod.main_cli(
        [
            "begin-session", "--workspace", WS, "--user", USER,
            "--params-json", "{}", "--root", str(root),
        ]
    )  # exit 3 (CLI-unwired) but registers the safe render + fetch-by-id baseline
    cli._cmd_list(["voices", "--workspace", WS, "--user", USER, "--root", str(root)])
    assert set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS) == {"render", "fetch-by-id"}


def test_list_and_get_never_register_session_or_api_handlers(tmp_path, monkeypatch):
    root = build_root(tmp_path)
    called: list[str] = []
    monkeypatch.setattr(session, "register_api_handlers", lambda *a, **k: called.append("api"))
    monkeypatch.setattr(
        session, "register_session_handlers", lambda *a, **k: called.append("session")
    )
    monkeypatch.setattr(
        discovery, "register_discovery_handlers", lambda *a, **k: called.append("discovery")
    )
    cli._cmd_list(["voices", "--workspace", WS, "--user", USER, "--root", str(root)])
    cli._cmd_get(
        ["voices", "clear-explainer", "--workspace", WS, "--user", USER, "--root", str(root)]
    )
    assert called == []  # never registered a session/api/discovery verb (direct-handler pattern)
    assert "begin-session" not in invoke_mod._VERB_HANDLERS
    assert "continue-session" not in invoke_mod._VERB_HANDLERS


def test_invoke_begin_session_still_exit_3(tmp_path):
    # The §21.9 door invariant is UNMOVED by C3c: the live-quota session verb stays CLI-unwired.
    root = build_root(tmp_path)
    code = invoke_mod.main_cli(
        [
            "begin-session", "--workspace", WS, "--user", USER,
            "--params-json", "{}", "--root", str(root),
        ]
    )
    assert code == 3
