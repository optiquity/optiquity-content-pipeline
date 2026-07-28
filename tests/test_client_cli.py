"""Tests for the thin CLI (`python -m pipeline.client`), Commit 3 of the API-client build.

The CLI is a small argparse front over the committed :class:`pipeline.client.Client`; these tests
pin the F-F guarantees and the 1:1 method mapping WITHOUT any live network:

* the verb surface is EXACTLY ``{generate, render, list, get}`` — no generic ``invoke`` passthrough;
* the secret is env-ONLY (``OPTIQUITY_SHIM_SECRET``) — there is no ``--secret``/``--api-key`` flag,
  and neither the top-level nor a subcommand ``--help`` leaks a secret;
* each subcommand maps to the matching Client method, driven against the SAME in-process scripted
  ``http.server`` harness the Commit-2 client tests use (reused from ``test_client``);
* a failure outcome maps to a non-zero exit with a clear stderr message that never contains the
  secret.

The scripted-server harness (`_ScriptedShim` / `_scripted_server` / `_done`) is imported from
``test_client`` (pytest's prepend import mode puts ``tests/`` on ``sys.path``; the same pattern
``test_parallel_plan`` already uses for ``test_session``). All fixtures are obviously generic
(``wsA``, literal ids); no instance/client content, no secrets.
"""

from __future__ import annotations

import argparse
import json

import pytest
from test_client import _done, _scripted_server, _ScriptedShim

import pipeline.client.client as client_mod
from pipeline.client import __main__ as cli

# A sentinel secret used to prove it never leaks into --help / stderr / stdout.
_SENTINEL_SECRET = "sekret-sentinel-value"


# =============================================================================================
# Verb surface + the no-secret-flag guarantees (F-F).
# =============================================================================================


def test_verb_surface_is_exactly_the_four_pinned() -> None:
    """The subcommand set is EXACTLY {generate, render, list, get} — no `invoke` passthrough."""
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {"generate", "render", "list", "get"}
    assert "invoke" not in sub.choices
    assert set(cli.VERBS) == set(sub.choices)


def test_invoke_passthrough_is_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """`python -m pipeline.client invoke <verb>` is rejected as an unknown command (exit 2)."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    monkeypatch.setenv("OPTIQUITY_SHIM_URL", "http://127.0.0.1:9")
    with pytest.raises(SystemExit) as exc:
        cli.main(["invoke", "render", "--workspace", "wsA"])
    assert exc.value.code == 2


def test_no_secret_flag_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """There is no `--secret` flag — passing one is an unrecognized-argument usage error
    (exit 2)."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    monkeypatch.setenv("OPTIQUITY_SHIM_URL", "http://127.0.0.1:9")
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "render", "i", "--workspace", "wsA", "--platform", "p", "--language", "en",
                "--output-type", "post", "--secret", "LEAK",
            ]
        )
    assert exc.value.code == 2


def test_top_level_help_lists_verbs_and_has_no_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--help` shows the four pinned verbs, exits 0, and never leaks the secret VALUE. (The prose
    legitimately states there is no --secret flag; the no-flag guarantee itself is proven
    behaviorally by ``test_no_secret_flag_is_rejected``.)"""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for verb in ("generate", "render", "list", "get"):
        assert verb in out
    assert _SENTINEL_SECRET not in out


def test_subcommand_help_is_secret_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A subcommand `--help` names the env-var but carries no secret and no
    `--secret`/`--api-key`."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    with pytest.raises(SystemExit) as exc:
        cli.main(["render", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--secret" not in out
    assert "--api-key" not in out
    assert _SENTINEL_SECRET not in out
    assert "OPTIQUITY_SHIM_SECRET" in out  # the env-var NAME is fine to surface


def test_env_constants_match_client_module() -> None:
    """Anti-drift: the CLI's env keys are the client library's SSOT, not a private re-spelling."""
    assert cli._ENV_URL == client_mod._ENV_URL
    assert cli._ENV_SECRET == client_mod._ENV_SECRET


# =============================================================================================
# The 1:1 method mapping (driven against the scripted in-process server; no live network).
# =============================================================================================


def test_render_maps_to_client_and_prints_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`render` → render_and_wait: a cache-hit 200 at submit returns a Result whose body is printed
    as one JSON object; the /invoke body carries verb=render + the render coordinates."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    shim = _ScriptedShim()
    shim.invoke_script = [_done("r-1", ["t-1"], [{"item": "rendered"}])]
    with _scripted_server(shim) as url:
        monkeypatch.setenv("OPTIQUITY_SHIM_URL", url)
        code = cli.main(
            [
                "render", "deck-intro", "--workspace", "wsA", "--platform", "linkedin",
                "--language", "en", "--output-type", "post",
            ]
        )
    captured = capsys.readouterr()
    assert code == 0
    printed = json.loads(captured.out)
    assert printed["results"] == [{"item": "rendered"}]
    assert _SENTINEL_SECRET not in captured.out
    path, body, _headers = shim.received[0]
    assert path == "/invoke"
    assert body["verb"] == "render"
    assert body["params"]["item"] == "deck-intro"
    assert body["params"]["platform"] == "linkedin"
    assert body["params"]["output_type"] == "post"


def test_generate_maps_to_begin_then_generate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`generate` → begin_session (generate FORCED "none") then generate_and_wait: the stub sees a
    begin-session invoke then a continue-session{generate-next} invoke carrying the key; the final
    generate Result body is what is printed. --url overrides the env URL here."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    shim = _ScriptedShim()
    shim.invoke_script = [
        {"status": 200, "json": {"envelope": {"ok": True}, "results": [], "token": "tok-1"}},
        _done("r-2", ["t-2"], [{"item": "generated"}]),
    ]
    with _scripted_server(shim) as url:
        code = cli.main(
            [
                "generate", "--workspace", "wsA", "--selection", '{"topic": "t"}',
                "--idempotency-key", "idem-1", "--url", url,
            ]
        )
    captured = capsys.readouterr()
    assert code == 0
    printed = json.loads(captured.out)
    assert printed["results"] == [{"item": "generated"}]
    bodies = [b for (p, b, _h) in shim.received if p == "/invoke"]
    assert [b["verb"] for b in bodies] == ["begin-session", "continue-session"]
    assert bodies[0]["params"]["generate"] == "none"  # FORCED regardless of the caller
    assert bodies[1]["params"]["action"] == "generate-next"
    assert bodies[1]["params"]["idempotency_key"] == "idem-1"


def test_list_maps_to_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`list <type>` → Client.list: the Tier-A envelope is printed and the /invoke body is verb=list
    with params.type."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    envelope = {"ok": True, "verb": "list", "workspace": "wsA", "results": [{"id": "p1"}]}
    shim = _ScriptedShim()
    shim.invoke_script = [{"status": 200, "json": envelope}]
    with _scripted_server(shim) as url:
        code = cli.main(["list", "persona", "--workspace", "wsA", "--url", url])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == envelope
    _path, body, _headers = shim.received[0]
    assert body["verb"] == "list"
    assert body["params"]["type"] == "persona"


def test_get_maps_to_client(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`get <type> <id>` → Client.get: the /invoke body is verb=get with params.type + params.id."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    envelope = {"ok": True, "verb": "get", "workspace": "wsA", "results": [{"id": "p1"}]}
    shim = _ScriptedShim()
    shim.invoke_script = [{"status": 200, "json": envelope}]
    with _scripted_server(shim) as url:
        code = cli.main(["get", "persona", "p1", "--workspace", "wsA", "--url", url])
    captured = capsys.readouterr()
    assert code == 0
    assert json.loads(captured.out) == envelope
    _path, body, _headers = shim.received[0]
    assert body["verb"] == "get"
    assert body["params"]["type"] == "persona"
    assert body["params"]["id"] == "p1"


# =============================================================================================
# Failure outcomes → non-zero exit + a clear, secret-free stderr message.
# =============================================================================================


def test_render_blocked_outcome_is_nonzero_and_secret_free(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused render (400 render-blocked) is a failure outcome: exit 1 with a clear stderr line,
    and neither stdout nor stderr contains the secret."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    shim = _ScriptedShim()
    shim.invoke_script = [
        {
            "status": 400,
            "json": {"error": "render-blocked", "block": {"code": "grounding-uncovered"}},
        }
    ]
    with _scripted_server(shim) as url:
        code = cli.main(
            [
                "render", "i", "--workspace", "wsA", "--platform", "p", "--language", "en",
                "--output-type", "post", "--url", url,
            ]
        )
    captured = capsys.readouterr()
    assert code == 1
    assert "RenderBlocked" in captured.err
    assert _SENTINEL_SECRET not in captured.err
    assert _SENTINEL_SECRET not in captured.out


def test_list_error_envelope_is_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A Tier-A error (a non-2xx envelope) still prints its JSON but exits non-zero."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    shim = _ScriptedShim()
    shim.invoke_script = [{"status": 400, "json": {"ok": False, "code": "unknown-verb"}}]
    with _scripted_server(shim) as url:
        code = cli.main(["list", "persona", "--workspace", "wsA", "--url", url])
    captured = capsys.readouterr()
    assert code == 1
    assert json.loads(captured.out) == {"ok": False, "code": "unknown-verb"}
    assert "status=400" in captured.err


# =============================================================================================
# Configuration errors (env-only secret) → usage exit 2.
# =============================================================================================


def test_missing_secret_is_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With no OPTIQUITY_SHIM_SECRET in the env, the CLI exits 2 and points at the env-var (never a
    flag)."""
    monkeypatch.delenv("OPTIQUITY_SHIM_SECRET", raising=False)
    monkeypatch.setenv("OPTIQUITY_SHIM_URL", "http://127.0.0.1:9")
    code = cli.main(
        [
            "render", "i", "--workspace", "wsA", "--platform", "p", "--language", "en",
            "--output-type", "post",
        ]
    )
    assert code == 2
    assert "OPTIQUITY_SHIM_SECRET" in capsys.readouterr().err


def test_missing_url_is_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With neither --url nor OPTIQUITY_SHIM_URL, the CLI exits 2 and points at the URL source."""
    monkeypatch.setenv("OPTIQUITY_SHIM_SECRET", _SENTINEL_SECRET)
    monkeypatch.delenv("OPTIQUITY_SHIM_URL", raising=False)
    code = cli.main(["list", "persona", "--workspace", "wsA"])
    assert code == 2
    assert "OPTIQUITY_SHIM_URL" in capsys.readouterr().err
