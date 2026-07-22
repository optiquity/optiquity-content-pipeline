"""Production adapter-set wiring — `folder` is registered alongside `graphify` at EVERY
site that builds the real adapter set, so a `adapter: folder` source is reachable through
the normal path (`begin-session`/`invoke` + the driver's `run_thread`).

Before this wiring only `graphify` was registered, so `adapters.get("folder")` returned
None on every production path: grounding could not resolve the adapter and `pin_commit`
was skipped. These tests pin the fix at each site and exercise a folder source grounding +
pinning THROUGH the default adapter set (hermetic; a synthetic-generic `tmp_path` corpus,
this instance's own throwaway git checkout, never client content — CLAUDE.md rules 1/4).
"""

from __future__ import annotations

import datetime
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import driver
from pipeline.adapters import default_adapters
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.folder import FolderAdapter
from pipeline.adapters.graphify import GraphifyAdapter
from pipeline.api import session
from pipeline.grounding import SourceInstance, ground_item
from pipeline.m3 import resolve_selection

NOW = datetime.date(2026, 7, 12)

WIDGET_DOC = """\
# Widget service

The widget service default timeout is 30 seconds.
"""


def make_corpus(root: Path) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "widget.md").write_text(WIDGET_DOC, encoding="utf-8")
    return root


# --- the production adapter set now registers ALL THREE adapters at every site ---------------


class TestProductionAdapterSet:
    def test_factory_registers_graphify_folder_and_fsast(self):
        # The single registration point (`pipeline.adapters.default_adapters`).
        adapters = default_adapters()
        assert set(adapters) == {"graphify", "folder", "fsast"}
        assert isinstance(adapters["graphify"], GraphifyAdapter)
        assert isinstance(adapters["folder"], FolderAdapter)
        assert all(isinstance(a, SourceAdapter) for a in adapters.values())
        # each adapter is keyed under its own declared name (no mislabeling).
        assert all(k == v.name for k, v in adapters.items())

    def test_session_default_adapters_registers_all_three(self):
        # The API path (`begin-session`/`invoke` resolve adapters from here).
        adapters = session._default_adapters()
        assert set(adapters) == {"graphify", "folder", "fsast"}
        assert isinstance(adapters["folder"], FolderAdapter)

    def test_session_resolves_from_the_single_source(self):
        # session's `_default_adapters` delegates to the ONE factory — a future
        # adapter is a one-file change, and API + driver never drift apart.
        assert session.default_adapters is default_adapters

    def test_driver_resolves_from_the_single_source(self):
        # the driver's `run_thread` builds its adapter set from the SAME factory, so a
        # folder source pins its commit through the same provenance grounding uses (CF-1).
        assert driver.default_adapters is default_adapters

    def test_fresh_instances_per_call(self):
        # a fresh dict of fresh instances per call — a caller may mutate the mapping
        # (e.g. `dict(adapters)` in the session begin/generate paths) without bleed.
        first, second = default_adapters(), default_adapters()
        assert first is not second
        assert first["folder"] is not second["folder"]


# --- a folder source grounds + pins THROUGH the default wiring (the fixed gap) ----------------

HAS_GIT = shutil.which("git") is not None
requires_git = pytest.mark.skipif(not HAS_GIT, reason="git binary not available")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def make_git_corpus(tmp_path: Path) -> Path:
    root = make_corpus(tmp_path / "gitcorpus")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Adapter Registration Test")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "corpus")
    return root


def real_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


class TestFolderResolvesThroughDefaultWiring:
    def test_plain_folder_grounds_via_default_adapters_no_git(self, tmp_path):
        # Hermetic, no git required: a `adapter: folder` source grounds through the
        # DEFAULT adapter set (before this wiring `adapters.get("folder")` was None, so
        # the resolver could not reach the folder adapter at all).
        root = make_corpus(tmp_path / "corpus")
        inst = SourceInstance(id="x-notes", adapter="folder", connection={"path": str(root)})
        adapters = session._default_adapters()
        outcome = ground_item(
            item="item-1",
            query="widget",
            pool=[inst],
            selection=resolve_selection(),
            adapters=adapters,
            now=NOW,
        )
        assert outcome.status == "ok"
        assert outcome.facts, "the folder corpus must ground through the default set"
        assert dict(outcome.commit_map) == {"x-notes": None}  # plain folder: commitless

    @requires_git
    def test_git_folder_grounds_and_pins_via_default_adapters(self, tmp_path):
        # The FULL wired path for a git-checkout folder: grounding AND the §7.2 commit
        # pin both resolve the folder adapter through the default set, and agree on HEAD
        # (CF-1). This is exactly what could not happen before folder was registered.
        root = make_git_corpus(tmp_path)
        head = real_head(root)
        inst = SourceInstance(id="x-repo", adapter="folder", connection={"path": str(root)})
        adapters = session._default_adapters()

        # pin path: session's begin-session commit-map (drives the artifact-id §7.2 pin).
        commit_map = session._pin_source_commit_map([inst], adapters, pins=None)
        assert commit_map == {"x-repo": head}

        # driver path: the same pin helper the driver's run_thread uses, same adapter set.
        assert driver._pin_source_commit(adapters.get("folder"), inst.connection) == head

        # grounding path: the ledger commit agrees with the identity pin (CF-1).
        outcome = ground_item(
            item="item-1",
            query="",
            pool=[inst],
            selection=resolve_selection(),
            adapters=adapters,
            now=NOW,
        )
        assert outcome.status == "ok"
        assert dict(outcome.commit_map) == {"x-repo": head}
