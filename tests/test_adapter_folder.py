"""Step-18 tests — `pipeline/adapters/folder.py`, the REAL folder adapter, end to end.

Covers: connection validation over the CLOSED key set (incl. the repo-workspaces
boundary refusal — rule 1/2 structural); deterministic corpus walking (parent-first
lexicographic, hidden entries / foreign extensions / symlinks skipped); verbatim
paragraph extraction (subjects, claims, `file-line` anchors with line spans, EXTRACTED
tier, per-file mtime `as_of`, `built_at_commit=None`); the mock-parity query filter;
the typed loud error surface (absent folder, non-directory, undecodable document —
never silent empties); byte-level read-only behavior; and resolver integration —
content-kind tagging (§6.1 SM5: the kind bundle rides the INSTANCE and characterizes
every folder fact), the commit-map's commitless entry, and mirror corroboration
(fixture-driven parity with the step-17 mock contract).

All corpora are SYNTHETIC-GENERIC (CLAUDE.md rule 4: invented widget/gadget prose)
built under pytest `tmp_path` — never client content, never inside any source repo.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline.adapters.base import (
    TIER_EXTRACTED,
    AdapterError,
    Anchor,
    SourceAdapter,
)
from pipeline.adapters.folder import (
    CONNECTION_KEYS,
    DEFAULT_BUDGET,
    DOC_SUFFIXES,
    REPO_USERS,
    FolderAdapter,
)
from pipeline.grounding import SourceInstance, ground_item
from pipeline.m3 import resolve_selection

NOW = datetime.date(2026, 7, 12)

WIDGET_DOC = """\
# Widget service

The widget service default timeout is 30 seconds.

The widget client retries failed calls
three times in a row.
"""

CACHE_NOTE = "The gadget cache holds 512 entries.\n"


def make_corpus(root: Path) -> Path:
    """One synthetic corpus: two docs plus a battery of must-be-skipped entries."""
    (root / "docs").mkdir(parents=True)
    (root / "notes").mkdir()
    (root / "docs" / "widget.md").write_text(WIDGET_DOC, encoding="utf-8")
    (root / "notes" / "cache.txt").write_text(CACHE_NOTE, encoding="utf-8")
    # Must all be skipped: hidden dir, hidden file, foreign extension.
    (root / ".hidden-dir").mkdir()
    (root / ".hidden-dir" / "inside.md").write_text("hidden dir doc\n", encoding="utf-8")
    (root / "docs" / ".draft.md").write_text("hidden file\n", encoding="utf-8")
    (root / "docs" / "script.py").write_text("print('not a doc')\n", encoding="utf-8")
    return root


def make_symlinked_corpus(tmp_path: Path) -> Path:
    """A corpus with symlinks pointing OUTSIDE it — none may ever be read."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.md").write_text("escaped content must never ground\n", encoding="utf-8")
    root = make_corpus(tmp_path / "corpus")
    (root / "linked.md").symlink_to(outside / "evil.md")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    return root


EXPECTED_SUBJECTS = (
    "docs/widget.md#p1",
    "docs/widget.md#p2",
    "docs/widget.md#p3",
    "notes/cache.txt#p1",
)


def ground_all(root: Path, query: str = ""):
    return FolderAdapter().ground(connection={"path": str(root)}, query=query)


# --- connection validation (closed keys; rule-1/2 boundary) ----------------------------------


class TestConnectionValidation:
    def test_non_mapping_connection_refused(self):
        with pytest.raises(AdapterError, match="must be a mapping"):
            FolderAdapter().ground(connection=[("path", "/x")], query="q")

    def test_unknown_key_refused_closed_set(self):
        assert CONNECTION_KEYS == frozenset({"path", "budget"})
        with pytest.raises(AdapterError, match="CLOSED"):
            FolderAdapter().ground(connection={"path": "/x", "glob": "*.md"}, query="q")

    @pytest.mark.parametrize("bad", [None, "", "   ", 7])
    def test_missing_or_empty_path_refused(self, bad):
        with pytest.raises(AdapterError, match="requires `path`"):
            FolderAdapter().ground(connection={"path": bad}, query="q")

    def test_relative_path_refused(self):
        with pytest.raises(AdapterError, match="ABSOLUTE"):
            FolderAdapter().ground(connection={"path": "notes/corpus"}, query="q")

    def test_absent_folder_is_typed_never_silent(self, tmp_path):
        with pytest.raises(AdapterError, match="folder not found"):
            FolderAdapter().ground(connection={"path": str(tmp_path / "nope")}, query="q")

    def test_non_directory_path_refused(self, tmp_path):
        file = tmp_path / "doc.md"
        file.write_text("x\n", encoding="utf-8")
        with pytest.raises(AdapterError, match="not a directory"):
            FolderAdapter().ground(connection={"path": str(file)}, query="q")

    def test_path_inside_repo_users_refused(self):
        # Plan step 18 / §23: grounding sources live OUTSIDE this repo's users/ client tree —
        # the boundary refusal fires BEFORE any existence probe.
        inside = REPO_USERS / "some-user" / "workspaces" / "some-client" / "output"
        with pytest.raises(AdapterError, match="users"):
            FolderAdapter().ground(connection={"path": str(inside)}, query="q")

    def test_users_root_itself_refused(self):
        with pytest.raises(AdapterError, match="users"):
            FolderAdapter().ground(connection={"path": str(REPO_USERS)}, query="q")

    def test_query_must_be_a_string(self, tmp_path):
        with pytest.raises(AdapterError, match="query must be a string"):
            FolderAdapter().ground(connection={"path": str(tmp_path)}, query=None)


# --- verbatim paragraph extraction -------------------------------------------------------------


class TestExtraction:
    def test_subjects_claims_anchors_tier(self, tmp_path):
        result = ground_all(make_corpus(tmp_path / "corpus"))
        assert tuple(fact.subject for fact in result.facts) == EXPECTED_SUBJECTS
        by_subject = {fact.subject: fact for fact in result.facts}
        assert by_subject["docs/widget.md#p1"].claim == "# Widget service"
        assert (
            by_subject["docs/widget.md#p2"].claim
            == "The widget service default timeout is 30 seconds."
        )
        # Verbatim multi-line block, newline preserved:
        assert (
            by_subject["docs/widget.md#p3"].claim
            == "The widget client retries failed calls\nthree times in a row."
        )
        assert by_subject["docs/widget.md#p1"].anchors == (
            Anchor("file-line", "docs/widget.md:L1"),
        )
        assert by_subject["docs/widget.md#p3"].anchors == (
            Anchor("file-line", "docs/widget.md:L5-L6"),
        )
        assert by_subject["notes/cache.txt#p1"].anchors == (
            Anchor("file-line", "notes/cache.txt:L1"),
        )
        assert {fact.tier for fact in result.facts} == {TIER_EXTRACTED}  # verbatim

    def test_as_of_is_the_document_mtime_date(self, tmp_path):
        root = make_corpus(tmp_path / "corpus")
        stale = datetime.datetime(2024, 11, 3, 12, 0).timestamp()
        os.utime(root / "notes" / "cache.txt", (stale, stale))
        result = ground_all(root)
        by_subject = {fact.subject: fact for fact in result.facts}
        assert by_subject["notes/cache.txt#p1"].as_of == datetime.date(2024, 11, 3)
        today_doc = by_subject["docs/widget.md#p2"]
        expected = datetime.date.fromtimestamp((root / "docs" / "widget.md").stat().st_mtime)
        assert today_doc.as_of == expected

    def test_commitless_and_refinement_free(self, tmp_path):
        # base.GroundingResult names the folder adapter as THE commitless kind; and
        # the adapter classifies nothing per fact (kind defaults ride — SM5).
        result = ground_all(make_corpus(tmp_path / "corpus"))
        assert result.built_at_commit is None
        assert all(fact.refinements == {} for fact in result.facts)

    def test_pin_commit_agrees_with_ground_commitless(self, tmp_path):
        # CF-1 for a PLAIN (non-git) folder: `pin_commit` OVERRIDES the base to hit the
        # read-only `git rev-parse HEAD`, which fails over a non-repo tmp dir -> None,
        # matching `ground().built_at_commit` — identity and the §15 ledger agree (both
        # commitless), the designed plain-folder posture. (The git-checkout case, where
        # both AGREE on the real HEAD, is TestCommitProvenance below.)
        root = make_corpus(tmp_path / "corpus")
        assert FolderAdapter().pin_commit({"path": str(root)}) is None
        assert ground_all(root).built_at_commit is None

    def test_deterministic_order_and_repeatability(self, tmp_path):
        root = make_corpus(tmp_path / "corpus")
        first = ground_all(root)
        second = ground_all(root)
        assert first == second  # same facts, same order — every time

    def test_query_filter_is_case_insensitive_substring(self, tmp_path):
        root = make_corpus(tmp_path / "corpus")
        widget = ground_all(root, query="WIDGET")
        # subject+claim filter (mock parity): every docs/widget.md block matches.
        assert tuple(f.subject for f in widget.facts) == EXPECTED_SUBJECTS[:3]
        gadget = ground_all(root, query="gadget cache")
        assert tuple(f.subject for f in gadget.facts) == ("notes/cache.txt#p1",)
        nothing = ground_all(root, query="zzz-not-present")
        assert nothing.facts == ()  # a legit empty, not an error

    def test_empty_query_grounds_the_whole_corpus(self, tmp_path):
        # Mock parity: empty query = the whole dataset.
        result = ground_all(make_corpus(tmp_path / "corpus"), query="")
        assert len(result.facts) == len(EXPECTED_SUBJECTS)

    def test_hidden_foreign_and_symlinked_entries_never_ground(self, tmp_path):
        root = make_symlinked_corpus(tmp_path)
        result = ground_all(root)
        assert tuple(fact.subject for fact in result.facts) == EXPECTED_SUBJECTS
        all_text = " ".join(fact.claim for fact in result.facts)
        for leaked in ("hidden", "not a doc", "escaped content"):
            assert leaked not in all_text

    def test_empty_folder_is_a_legit_empty_result(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        result = ground_all(empty)
        assert result.facts == () and result.built_at_commit is None

    def test_undecodable_document_is_loud(self, tmp_path):
        root = make_corpus(tmp_path / "corpus")
        (root / "docs" / "binary.md").write_bytes(b"\xff\xfe\x00garbage")
        with pytest.raises(AdapterError, match="not UTF-8"):
            ground_all(root)

    def test_doc_suffix_allowlist_is_the_closed_v1_set(self):
        assert DOC_SUFFIXES == (".md", ".txt")


# --- rule 1: zero write syscalls toward the source ---------------------------------------------


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class TestReadOnly:
    def test_ground_leaves_the_corpus_byte_identical(self, tmp_path):
        root = make_corpus(tmp_path / "corpus")
        before = snapshot(tmp_path)
        ground_all(root, query="widget")
        ground_all(root)  # and the unfiltered pass
        assert snapshot(tmp_path) == before  # zero writes toward the source, ever

    def test_module_source_has_no_write_primitives(self):
        # Rule 1 structural: the adapter module cannot write — no filesystem write
        # primitive appears anywhere in its source (reads via read_text + os.walk), and
        # its ONLY subprocess is the read-only `git rev-parse HEAD` (asserted below).
        import pipeline.adapters.folder as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        for token in (
            "write_text",
            "write_bytes",
            ".write(",
            "open(",
            "mkdir",
            "unlink",
            "rmtree",
            "rename(",
            "remove(",
            "chmod",
            "symlink_to",
            "touch(",
            "shutil",
        ):
            assert token not in source, f"write primitive {token!r} found in folder adapter"
        # The sole subprocess is the READ-ONLY rev-parse HEAD — exactly one call site,
        # never a state-changing git verb.
        assert source.count("subprocess.run(") == 1
        assert '"rev-parse"' in source and '"HEAD"' in source

    def test_contract_shape(self):
        assert issubclass(FolderAdapter, SourceAdapter)
        assert FolderAdapter.name == "folder"
        assert FolderAdapter.capabilities == frozenset({"query"})


# --- resolver integration: content-kind tagging + mock-contract parity -------------------------


class TestResolverIntegration:
    def test_content_kind_bundle_characterizes_folder_facts(self, tmp_path):
        # §6.1 SM5 (plan step 18 "content-kind tagging"): the kind tag rides the
        # SOURCE INSTANCE; its default score bundle characterizes every fact this
        # adapter returns — and survives untouched because the adapter refines nothing.
        root = make_corpus(tmp_path / "corpus")
        instance = SourceInstance(
            id="x-research-notes",
            adapter="folder",
            connection={"path": str(root)},
            content_kind="research-notes",
            kind_defaults={
                "authoritative": 2,
                "opinionated": 4,
                "review_status": "unreviewed",
                "freshness": "",
            },
        )
        outcome = ground_item(
            item="item-1",
            query="widget",
            pool=[instance],
            selection=resolve_selection(),
            adapters={"folder": FolderAdapter()},
            now=NOW,
        )
        assert outcome.status == "ok"
        for fact in outcome.facts:
            assert fact.scores["content-kind"] == "research-notes"
            assert fact.scores["authoritative"] == 2
            assert fact.scores["opinionated"] == 4
            assert fact.scores["review_status"] == "unreviewed"
        assert dict(outcome.commit_map) == {"x-research-notes": None}  # commitless entry

    def test_mirror_corroboration_parity_with_the_mock_contract(self, tmp_path):
        # Two GENUINELY distinct folder instances carrying an identical doc at the
        # same relative path agree on (subject, claim) — the §6.5 corroboration
        # arithmetic works over the real adapter exactly as over the mock.
        root_a = make_corpus(tmp_path / "corpus-a")
        root_b = tmp_path / "corpus-b"
        (root_b / "docs").mkdir(parents=True)
        (root_b / "docs" / "widget.md").write_text(WIDGET_DOC, encoding="utf-8")
        pool = [
            SourceInstance(
                id="x-first-party-docs",
                adapter="folder",
                connection={"path": str(root_a)},
            ),
            SourceInstance(
                id="x-independent-mirror",
                adapter="folder",
                connection={"path": str(root_b)},
                independence="independent",
            ),
        ]
        outcome = ground_item(
            item="item-1",
            query="timeout",
            pool=pool,
            selection=resolve_selection(),
            adapters={"folder": FolderAdapter()},
            now=NOW,
        )
        assert outcome.status == "ok"
        timeout_facts = [f for f in outcome.facts if f.subject == "docs/widget.md#p2"]
        assert timeout_facts, "the shared paragraph must ground"
        for fact in timeout_facts:
            assert fact.corroboration == 1
            assert fact.agreeing_instances == ("x-first-party-docs", "x-independent-mirror")
            assert fact.tier == TIER_EXTRACTED  # already the top tier — never above

    def test_citability_from_real_anchors(self, tmp_path):
        # SM9 through the resolver: folder facts carry resolvable file-line anchors,
        # so the COMPUTED citability is True for every grounded fact.
        root = make_corpus(tmp_path / "corpus")
        outcome = ground_item(
            item="item-1",
            query="",
            pool=[
                SourceInstance(
                    id="x-notes", adapter="folder", connection={"path": str(root)}
                )
            ],
            selection=resolve_selection(),
            adapters={"folder": FolderAdapter()},
            now=NOW,
        )
        assert outcome.status == "ok"
        assert all(fact.citable for fact in outcome.facts)
        assert all(fact.commit is None for fact in outcome.facts)


# --- git-checkout commit provenance (CF-1: ground == pin_commit) + fact budget ----------------

HAS_GIT = shutil.which("git") is not None
requires_git = pytest.mark.skipif(not HAS_GIT, reason="git binary not available")


def _git(root: Path, *args: str) -> None:
    """Run a git subcommand in the TEST (never in the adapter) to build a real checkout."""
    subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    )


def make_git_corpus(tmp_path: Path) -> Path:
    """`make_corpus` under a REAL initialized git checkout with one commit — synthetic-
    generic content under `tmp_path`, this instance's own throwaway repo, never a client."""
    root = make_corpus(tmp_path / "gitcorpus")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Folder Adapter Test")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "corpus")
    return root


def real_head(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


class TestCommitProvenance:
    @requires_git
    def test_git_checkout_pins_head_and_ground_agrees(self, tmp_path):
        # CF-1: for a git-checkout folder, pin_commit == ground().built_at_commit ==
        # the REAL HEAD — identity (§7.2 commit-map) and the §15 ledger AGREE, so the
        # folder adapter is compose-capable (it can mint a commit-pinned artifact-id).
        root = make_git_corpus(tmp_path)
        head = real_head(root)
        assert len(head) == 40  # a real 40-hex commit SHA
        adapter = FolderAdapter()
        pinned = adapter.pin_commit({"path": str(root)})
        grounded = adapter.ground(connection={"path": str(root)}, query="").built_at_commit
        assert pinned == grounded == head

    def test_git_helper_returns_none_when_not_a_repo(self, tmp_path):
        # A plain folder is not a git repo → `git rev-parse` exits non-zero → None,
        # never raised: the designed commitless posture (unchanged for plain folders).
        root = make_corpus(tmp_path / "corpus")
        assert FolderAdapter()._head_commit(root) is None

    def test_git_helper_returns_none_when_git_absent(self, tmp_path, monkeypatch):
        # git binary absent → FileNotFoundError is CAUGHT → None, never raised.
        import pipeline.adapters.folder as module

        def boom(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(module.subprocess, "run", boom)
        root = make_corpus(tmp_path / "corpus")
        adapter = FolderAdapter()
        assert adapter._head_commit(root) is None
        assert adapter.pin_commit({"path": str(root)}) is None
        assert adapter.ground(connection={"path": str(root)}, query="").built_at_commit is None

    def test_git_helper_returns_none_on_nonzero_exit(self, tmp_path, monkeypatch):
        # A non-zero git exit → None, never raised (commitless posture).
        import pipeline.adapters.folder as module

        class _Outcome:
            returncode = 128
            stdout = ""
            stderr = "fatal: not a git repository"

        monkeypatch.setattr(module.subprocess, "run", lambda *a, **k: _Outcome())
        root = make_corpus(tmp_path / "corpus")
        assert FolderAdapter()._head_commit(root) is None


class TestReadOnlyGitCall:
    def test_only_subprocess_is_read_only_git_rev_parse(self, tmp_path, monkeypatch):
        # Rule 1 behavioral: the SOLE subprocess the adapter spawns is the READ-ONLY
        # `git -C <root> rev-parse HEAD` — captured argv, never a state-changing verb.
        import pipeline.adapters.folder as module

        recorded: list[list[str]] = []

        class _Outcome:
            returncode = 0
            stdout = "ab" * 20 + "\n"
            stderr = ""

        def recorder(argv, **kwargs):
            recorded.append(list(argv))
            return _Outcome()

        monkeypatch.setattr(module.subprocess, "run", recorder)
        root = make_corpus(tmp_path / "corpus")
        result = ground_all(root)
        assert result.built_at_commit == "ab" * 20
        assert recorded == [["git", "-C", str(root.resolve()), "rev-parse", "HEAD"]]


class TestBudget:
    def test_budget_is_a_connection_key_in_the_closed_set(self):
        assert CONNECTION_KEYS == frozenset({"path", "budget"})

    def test_budget_caps_fact_count_first_n(self, tmp_path):
        # `budget` caps grounded facts to the first N in the deterministic walk order.
        root = make_corpus(tmp_path / "corpus")
        result = FolderAdapter().ground(connection={"path": str(root), "budget": 2}, query="")
        assert len(result.facts) == 2
        assert tuple(f.subject for f in result.facts) == EXPECTED_SUBJECTS[:2]

    def test_over_budget_corpus_truncates_deterministically_not_an_error(self, tmp_path):
        # An over-budget corpus is NOT an error — it truncates to the first N, idempotently.
        root = make_corpus(tmp_path / "corpus")  # 4 facts; budget 1
        capped = FolderAdapter().ground(connection={"path": str(root), "budget": 1}, query="")
        assert tuple(f.subject for f in capped.facts) == EXPECTED_SUBJECTS[:1]
        again = FolderAdapter().ground(connection={"path": str(root), "budget": 1}, query="")
        assert capped == again  # deterministic first-N, every time

    def test_budget_counts_matching_facts_after_filter(self, tmp_path):
        # The cap counts query-MATCHING facts (post-filter), first-N in walk order.
        root = make_corpus(tmp_path / "corpus")
        result = FolderAdapter().ground(
            connection={"path": str(root), "budget": 2}, query="widget"
        )
        assert tuple(f.subject for f in result.facts) == EXPECTED_SUBJECTS[:2]

    def test_budget_absent_applies_default(self, tmp_path):
        # No `budget` key → DEFAULT_BUDGET applies; the small corpus is well under it.
        assert DEFAULT_BUDGET == 2000
        root = make_corpus(tmp_path / "corpus")
        result = FolderAdapter().ground(connection={"path": str(root)}, query="")
        assert len(result.facts) == len(EXPECTED_SUBJECTS)

    @pytest.mark.parametrize("bad", [0, -1, -5, 3.0, "2", True, False, None])
    def test_invalid_budget_is_a_typed_error(self, tmp_path, bad):
        # Non-int or ≤0 budget is a typed, loud AdapterError (never a silent default).
        root = make_corpus(tmp_path / "corpus")
        with pytest.raises(AdapterError, match="budget must be a positive integer"):
            FolderAdapter().ground(connection={"path": str(root), "budget": bad}, query="")
