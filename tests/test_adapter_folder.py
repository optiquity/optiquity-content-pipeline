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
    DOC_SUFFIXES,
    REPO_WORKSPACES,
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
        assert CONNECTION_KEYS == frozenset({"path"})
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

    def test_path_inside_repo_workspaces_refused(self):
        # Plan step 18: grounding sources live OUTSIDE this repo's workspaces —
        # the boundary refusal fires BEFORE any existence probe.
        inside = REPO_WORKSPACES / "some-client" / "output"
        with pytest.raises(AdapterError, match="workspaces"):
            FolderAdapter().ground(connection={"path": str(inside)}, query="q")

    def test_workspaces_root_itself_refused(self):
        with pytest.raises(AdapterError, match="workspaces"):
            FolderAdapter().ground(connection={"path": str(REPO_WORKSPACES)}, query="q")

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
        # Rule 1 structural: the adapter module cannot write — no write primitive
        # appears anywhere in its source (reads via read_text + os.walk only).
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
            "subprocess",
        ):
            assert token not in source, f"write primitive {token!r} found in folder adapter"

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
