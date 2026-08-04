"""Sources P2b-core, part 2: the `pipeline sources ingest` CLI door + the Tier-A money-safety proof.

The ingest command is an OUT-OF-BAND Tier-A maintenance verb (the `migrate.sh` / `workspace new`
family): it fetches FREE HTTP and writes the LOCAL sealed cache, and NEVER spends quota, mints a
token, or touches the paid job path. These tests prove that structurally (a grep over the sources
code + a driven command with an injected fetch seam) — no test hits the network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_sources
from pipeline.adapters.base import AdapterError, GroundingResult
from pipeline.sources.reader import CONNECTION_KEYS
from tests.test_sources_ingest import _8K, _10Q, CIK, UA, edgar_bytes, make_http_get

REPO_ROOT = Path(__file__).resolve().parents[1]

FEED_YAML = f"""\
kind: edgar
namespace: edgar-widget
content_kind: regulatory-filing
temporality: archival
budget:
  max_facts: 100
connection:
  user_agent: "{UA}"
  cik: "{CIK}"
  forms: ["8-K"]
"""


def _make_workspace(tmp_path, user="acme", workspace="widgets", *, feed=True):
    feeds_dir = tmp_path / "users" / user / "workspaces" / workspace / "sources" / "feeds"
    feeds_dir.mkdir(parents=True, exist_ok=True)
    if feed:
        (feeds_dir / "x-edgar.yaml").write_text(FEED_YAML, encoding="utf-8")
    return user, workspace


# ---------------------------------------------------------------------------
# The CLI ingest door — driven end to end with an INJECTED fetch seam (no network).
# ---------------------------------------------------------------------------


class TestCliIngest:
    def test_ingest_command_seals_and_is_idempotent(self, tmp_path, capsys):
        user, workspace = _make_workspace(tmp_path)
        http_get = make_http_get(edgar_bytes([_8K, _10Q]))
        argv = ["ingest", workspace, "--user", user, "--root", str(tmp_path)]

        code = _cmd_sources(argv, http_get=http_get)
        assert code == 0
        out = capsys.readouterr().out
        assert "newly cached" in out and "θ-stop" in out and "$0 model spend" in out
        head = (
            tmp_path
            / "users" / user / "workspaces" / workspace
            / "sources" / "cache" / "edgar-widget" / "HEAD"
        )
        assert head.is_file(), "the ingest must seal a slice + advance HEAD"

        # re-ingest of the SAME fixture → a content-addressed no-op (idempotent)
        code2 = _cmd_sources(argv, http_get=make_http_get(edgar_bytes([_8K, _10Q])))
        assert code2 == 0
        assert "HEAD unchanged (idempotent no-op)" in capsys.readouterr().out

    def test_ingest_with_no_feed_descriptors_refuses(self, tmp_path, capsys):
        user, workspace = _make_workspace(tmp_path, feed=False)
        code = _cmd_sources(
            ["ingest", workspace, "--user", user, "--root", str(tmp_path)],
            http_get=make_http_get(b"{}"),
        )
        assert code == 1
        assert "no feed sources found" in capsys.readouterr().err

    def test_ingest_missing_subcommand_is_usage(self, capsys):
        assert _cmd_sources([]) == 2
        assert "a subcommand is required" in capsys.readouterr().err

    def test_ingest_bad_user_refuses(self, tmp_path, capsys):
        # an UPPERCASE user fails the §23 isolation door (never a traceback)
        code = _cmd_sources(
            ["ingest", "widgets", "--user", "BadUser", "--root", str(tmp_path)],
            http_get=make_http_get(b"{}"),
        )
        assert code == 1

    def test_ingest_bad_namespace_is_clean_exit_1_no_traceback(self, tmp_path, capsys):
        # A malformed feed `namespace:` surfaces from the cache-store gate as a typed CacheError —
        # the CLI catches it → clean exit-1 refusal (as --help advertises), never a raw traceback.
        user, workspace = "acme", "widgets"
        feeds_dir = tmp_path / "users" / user / "workspaces" / workspace / "sources" / "feeds"
        feeds_dir.mkdir(parents=True)
        (feeds_dir / "x-bad.yaml").write_text(
            'kind: edgar\nnamespace: "../escape"\n'
            'connection:\n  user_agent: "u"\n  cik: "0000012345"\n',
            encoding="utf-8",
        )
        code = _cmd_sources(
            ["ingest", workspace, "--user", user, "--root", str(tmp_path)],
            http_get=make_http_get(b"{}"),
        )
        assert code == 1
        err = capsys.readouterr().err
        assert "Traceback" not in err and "sources ingest" in err


# ---------------------------------------------------------------------------
# Money-safety: the sources subsystem references NO paid path; begin-session stays exit 3.
# ---------------------------------------------------------------------------


class TestTierAMoneySafety:
    def test_sources_code_references_no_paid_path(self):
        # A structural grep: the acquisition code never imports the transport/session/invoke/driver
        # machinery, carries no `--go`, and registers no paid handler (`register_`). Free HTTP + a
        # local cache write only — $0 model spend.
        sources_dir = REPO_ROOT / "pipeline" / "sources"
        text = "\n".join(
            p.read_text(encoding="utf-8") for p in sorted(sources_dir.rglob("*.py"))
        )
        forbidden = [
            "pipeline.transport",
            "pipeline.driver",
            "pipeline.api.invoke",
            "pipeline.api.session",
            "pipeline.jobs",
            "run_artifact",
            "continue_session",
            "begin_session",
            "register_",
            "--go",
        ]
        hits = [tok for tok in forbidden if tok in text]
        assert not hits, f"sources code must reference no paid path — found {hits}"

    def test_begin_session_stays_unwired_exit_3(self):
        # The ingest verb does NOT wire begin-session onto the external-actor door: a known-but-
        # unwired verb still exits 3 (§21.9 — the paid session door is unreachable). `main_cli`
        # registers the safe verbs into the module-global registry as a side effect, so snapshot +
        # restore it (the invoke door's own test discipline) — never pollute a sibling test.
        from pipeline.api import invoke as invoke_mod
        from pipeline.api.invoke import main_cli

        snapshot = dict(invoke_mod._VERB_HANDLERS)
        try:
            code = main_cli(
                [
                    "begin-session",
                    "--workspace",
                    "workspace.template",
                    "--user",
                    "acme",
                    "--params-json",
                    "{}",
                ]
            )
        finally:
            invoke_mod._VERB_HANDLERS.clear()
            invoke_mod._VERB_HANDLERS.update(snapshot)
        assert code == 3

    def test_sources_is_not_an_invoke_verb(self):
        # `sources ingest` is a LOCAL CLI verb only — never reachable through the external door.
        from pipeline.api.invoke import KNOWN_VERBS

        assert "sources" not in KNOWN_VERBS and "ingest" not in KNOWN_VERBS


# ---------------------------------------------------------------------------
# The temporality carrier: connection key + GroundingResult validation.
# ---------------------------------------------------------------------------


class TestTemporalityCarrier:
    def test_temporality_is_a_cache_connection_key(self):
        assert "temporality" in CONNECTION_KEYS

    def test_grounding_result_accepts_none_and_known_token(self):
        assert GroundingResult(facts=()).temporality is None
        assert GroundingResult(facts=(), temporality="archival").temporality == "archival"

    def test_grounding_result_refuses_an_unknown_temporality(self):
        with pytest.raises(AdapterError):
            GroundingResult(facts=(), temporality="made-up")
