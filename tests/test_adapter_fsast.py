"""Tests for `pipeline/adapters/fsast.py` — the REAL FS/AST source adapter (planner-03
Part C, FD1-b), end to end.

Covers: connection validation over the CLOSED key set (incl. the repo-workspaces boundary
refusal — rule 1/2); the make-or-break QUERY-INSENSITIVITY (R4: empty vs. real query →
identical non-empty fact set); the `workspaces/` mid-walk prune (R6); deterministic walk
(parent-first lexicographic, hidden entries / symlinks skipped); #3 tree facts (subject,
sorted listing, directory `file-line` anchor, EXTRACTED tier, dir-mtime `as_of`); #9
signature facts (`::qualname` subjects incl. one-level class methods, reconstructed
one-line signatures, `file-line` anchors at the def/class lineno); secret-scan cleanliness
(compose refuses secret-shaped fact strings pre-LLM); byte-level read-only behavior + a
source write-primitive scan (rule 1 structural); the git-HEAD commit pin (CF-1) with the
commitless plain-directory posture; and the budget cap (in-band first-N truncation).

All corpora are SYNTHETIC-GENERIC (CLAUDE.md rule 4) built under pytest `tmp_path` — never
client content, never inside any source repo.
"""

from __future__ import annotations

import datetime
import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import ir
from pipeline.adapters.base import (
    TIER_EXTRACTED,
    AdapterError,
    Anchor,
    SourceAdapter,
)
from pipeline.adapters.fsast import (
    CONNECTION_KEYS,
    DEFAULT_BUDGET,
    PY_SUFFIX,
    REPO_WORKSPACES,
    WORKSPACES_DIRNAME,
    FsAstAdapter,
)
from pipeline.grounding import SourceInstance, ground_item
from pipeline.m3 import resolve_selection

NOW = datetime.date(2026, 7, 12)

CORE_PY = '''\
"""Core module."""


def build(plan, item, *, budget: int = 10) -> str:
    return "x"


async def fetch(url):
    return url


class Widget(Base):
    def run(self, mode: str = "fast") -> bool:
        return True

    async def close(self):
        pass
'''

README = "# Project\n\nGeneric readme prose.\n"
LEAKED_PY = "def leaked_symbol():\n    return 1\n"


def make_tree(root: Path) -> Path:
    """One synthetic tree: a package with signatures, a non-.py file, and a battery of
    must-be-skipped entries (a `workspaces/` subdir, a hidden dir, a hidden file)."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (root / "pkg" / "core.py").write_text(CORE_PY, encoding="utf-8")
    (root / "readme.md").write_text(README, encoding="utf-8")
    (root / WORKSPACES_DIRNAME).mkdir()  # R6: pruned mid-walk, never grounded
    (root / WORKSPACES_DIRNAME / "secret_code.py").write_text(LEAKED_PY, encoding="utf-8")
    (root / ".hidden-dir").mkdir()
    (root / ".hidden-dir" / "inside.py").write_text(LEAKED_PY, encoding="utf-8")
    (root / "pkg" / ".draft.py").write_text(LEAKED_PY, encoding="utf-8")
    return root


def make_symlinked_tree(tmp_path: Path) -> Path:
    """A tree with symlinks pointing OUTSIDE it — none may ever be walked or read."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text(LEAKED_PY, encoding="utf-8")
    root = make_tree(tmp_path / "corpus")
    (root / "linked.py").symlink_to(outside / "evil.py")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    return root


def ground_all(root: Path, query: str = ""):
    return FsAstAdapter().ground(connection={"path": str(root)}, query=query)


def by_subject(result) -> dict:
    return {fact.subject: fact for fact in result.facts}


def anchor_line(fact) -> int:
    return int(fact.anchors[0].value.rsplit(":L", 1)[1])


# --- connection validation (closed keys; rule-1/2 boundary) ----------------------------------


class TestConnectionValidation:
    def test_non_mapping_connection_refused(self):
        with pytest.raises(AdapterError, match="must be a mapping"):
            FsAstAdapter().ground(connection=[("path", "/x")], query="q")

    def test_unknown_key_refused_closed_set(self):
        assert CONNECTION_KEYS == frozenset({"path", "budget"})
        with pytest.raises(AdapterError, match="CLOSED"):
            FsAstAdapter().ground(connection={"path": "/x", "glob": "*.py"}, query="q")

    @pytest.mark.parametrize("bad", [None, "", "   ", 7])
    def test_missing_or_empty_path_refused(self, bad):
        with pytest.raises(AdapterError, match="requires `path`"):
            FsAstAdapter().ground(connection={"path": bad}, query="q")

    def test_relative_path_refused(self):
        with pytest.raises(AdapterError, match="ABSOLUTE"):
            FsAstAdapter().ground(connection={"path": "pkg/core"}, query="q")

    def test_absent_directory_is_typed_never_silent(self, tmp_path):
        with pytest.raises(AdapterError, match="directory not found"):
            FsAstAdapter().ground(connection={"path": str(tmp_path / "nope")}, query="q")

    def test_non_directory_path_refused(self, tmp_path):
        file = tmp_path / "mod.py"
        file.write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(AdapterError, match="not a directory"):
            FsAstAdapter().ground(connection={"path": str(file)}, query="q")

    def test_path_inside_repo_workspaces_refused(self):
        # planner-03 R6: grounding sources live OUTSIDE this repo's workspaces — the
        # boundary refusal fires BEFORE any existence probe.
        inside = REPO_WORKSPACES / "some-client" / "src"
        with pytest.raises(AdapterError, match="workspaces"):
            FsAstAdapter().ground(connection={"path": str(inside)}, query="q")

    def test_workspaces_root_itself_refused(self):
        with pytest.raises(AdapterError, match="workspaces"):
            FsAstAdapter().ground(connection={"path": str(REPO_WORKSPACES)}, query="q")

    def test_query_must_be_a_string(self, tmp_path):
        with pytest.raises(AdapterError, match="query must be a string"):
            FsAstAdapter().ground(connection={"path": str(tmp_path)}, query=None)


# --- R4: query INSENSITIVITY (the make-or-break) ---------------------------------------------


class TestQueryInsensitivity:
    def test_empty_and_real_query_give_the_identical_nonempty_set(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        empty = ground_all(root, query="")
        real = ground_all(root, query="the framework itself")
        s0 = {(f.subject, f.claim) for f in empty.facts}
        sq = {(f.subject, f.claim) for f in real.facts}
        assert s0 == sq and len(s0) > 0  # content of the query never changes the output
        # a genuinely different, high-frequency single token must ALSO not filter:
        assert {(f.subject, f.claim) for f in ground_all(root, query="pkg").facts} == s0

    def test_every_fact_is_extracted_tier(self, tmp_path):
        result = ground_all(make_tree(tmp_path / "corpus"))
        assert {fact.tier for fact in result.facts} == {TIER_EXTRACTED}


# --- R6: the `workspaces/` mid-walk prune + hidden/symlink skips -------------------------------


class TestWalkScope:
    def test_workspaces_subdir_is_pruned_mid_walk(self, tmp_path):
        # The tmp root is NOT under REPO_WORKSPACES (so the connection refusal does not
        # fire) — this exercises the mid-walk prune folder.py lacks (R6): the nested
        # `workspaces/secret_code.py` and its `leaked_symbol` must never appear anywhere.
        result = ground_all(make_tree(tmp_path / "corpus"))
        for fact in result.facts:
            blob = f"{fact.subject} {fact.claim} {fact.anchors[0].value}"
            assert WORKSPACES_DIRNAME not in blob
            assert "secret_code" not in blob
            assert "leaked_symbol" not in blob
        # and the root tree fact does not even LIST the pruned dir
        assert "workspaces/" not in by_subject(result)["."].claim

    def test_hidden_and_symlinked_entries_never_ground(self, tmp_path):
        result = ground_all(make_symlinked_tree(tmp_path))
        subjects = " ".join(fact.subject for fact in result.facts)
        claims = " ".join(fact.claim for fact in result.facts)
        for leaked in (".hidden-dir", ".draft", "linked.py", "linked-dir", "evil"):
            assert leaked not in subjects
            assert leaked not in claims

    def test_deterministic_order_and_repeatability(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        assert ground_all(root) == ground_all(root)  # same facts, same order, every time


# --- commit-pin reproducibility: gitignored build artifacts can't leak ------------------------


class TestReproducibility:
    def test_pycache_build_artifacts_never_leak_and_facts_stay_byte_identical(self, tmp_path):
        # The adapter pins built_at_commit = HEAD, so its facts must be a function of the
        # COMMITTED source. `__pycache__` holds gitignored `.pyc` build artifacts whose
        # names embed the interpreter version and accumulate run-to-run — they must NEVER
        # enter the #3 tree listings, or the fact set would drift while HEAD is unchanged.
        root = make_tree(tmp_path / "corpus")
        before = FsAstAdapter().ground(connection={"path": str(root)}, query="")
        baseline = {(f.subject, f.claim) for f in before.facts}
        # accumulate bytecode caches at the root AND under a subpackage
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\x00pyc-root")
        (root / "pkg" / "__pycache__").mkdir()
        (root / "pkg" / "__pycache__" / "core.cpython-312.pyc").write_bytes(b"\x00pyc-pkg")
        after = FsAstAdapter().ground(connection={"path": str(root)}, query="")
        # byte-identical fact set: build noise cannot change the committed-source facts
        assert after.facts == before.facts
        assert {(f.subject, f.claim) for f in after.facts} == baseline
        # and nothing references the cache dir or its artifacts anywhere
        for fact in after.facts:
            blob = f"{fact.subject} {fact.claim} {fact.anchors[0].value}"
            assert "__pycache__" not in blob and ".pyc" not in blob

    def test_repeated_ground_yields_a_stable_fact_count(self, tmp_path):
        # No cross-run drift: grounding the same tree twice gives an equal fact count
        # (the property that `.pyc` accumulation used to violate over a live tree).
        root = make_tree(tmp_path / "corpus")
        assert len(ground_all(root).facts) == len(ground_all(root).facts)


# --- #3 filesystem tree facts -----------------------------------------------------------------


class TestTreeFacts:
    def test_root_tree_fact_shape_and_citable_anchor(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        fact = by_subject(ground_all(root))["."]
        assert fact.tier == TIER_EXTRACTED
        assert fact.claim == "./ contains: pkg/, readme.md"  # sorted; workspaces/ pruned
        # a directory locator is a valid, non-empty anchor -> the fact is citable
        assert fact.anchors == (Anchor("file-line", "."),)
        assert fact.refinements == {}

    def test_subdirectory_tree_fact_lists_immediate_entries(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        fact = by_subject(ground_all(root))["pkg"]
        assert fact.subject == "pkg"
        assert fact.claim == "pkg/ contains: __init__.py, core.py"  # .draft.py hidden -> out
        assert fact.anchors == (Anchor("file-line", "pkg"),)

    def test_tree_fact_as_of_is_the_directory_mtime(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        fact = by_subject(ground_all(root))["pkg"]
        expected = datetime.date.fromtimestamp((root / "pkg").stat().st_mtime)
        assert fact.as_of == expected

    def test_empty_directory_lists_an_empty_sentinel(self, tmp_path):
        root = tmp_path / "bare"
        root.mkdir()
        result = ground_all(root)
        # a lone directory still grounds one (non-empty-claim) tree fact
        assert [f.subject for f in result.facts] == ["."]
        assert result.facts[0].claim == "./ contains: (empty)"


# --- #9 API-surface signature facts -----------------------------------------------------------


class TestSignatureFacts:
    def test_top_level_def_and_class_signatures(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        facts = by_subject(ground_all(root))
        build = facts["pkg/core.py::build"]
        assert build.tier == TIER_EXTRACTED and build.refinements == {}
        assert build.claim.startswith("def build(") and "plan, item" in build.claim
        assert build.claim.endswith(" -> str")
        assert facts["pkg/core.py::fetch"].claim == "async def fetch(url)"
        assert facts["pkg/core.py::Widget"].claim == "class Widget(Base)"

    def test_one_level_class_methods_are_qualnamed(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        facts = by_subject(ground_all(root))
        run = facts["pkg/core.py::Widget.run"]
        assert run.claim.startswith("def run(self") and run.claim.endswith(" -> bool")
        assert facts["pkg/core.py::Widget.close"].claim == "async def close(self)"

    def test_signature_anchor_points_at_the_def_line(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        facts = by_subject(ground_all(root))
        lines = CORE_PY.splitlines()
        assert facts["pkg/core.py::build"].anchors[0].kind == "file-line"
        assert "def build" in lines[anchor_line(facts["pkg/core.py::build"]) - 1]
        assert "class Widget" in lines[anchor_line(facts["pkg/core.py::Widget"]) - 1]
        assert "async def close" in lines[anchor_line(facts["pkg/core.py::Widget.close"]) - 1]

    def test_signature_as_of_is_the_file_mtime(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        fact = by_subject(ground_all(root))["pkg/core.py::build"]
        expected = datetime.date.fromtimestamp((root / "pkg" / "core.py").stat().st_mtime)
        assert fact.as_of == expected

    def test_py_suffix_constant(self):
        assert PY_SUFFIX == ".py"

    def test_undecodable_py_is_loud(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        (root / "pkg" / "binary.py").write_bytes(b"\xff\xfe\x00garbage")
        with pytest.raises(AdapterError, match="not UTF-8"):
            ground_all(root)

    def test_unparseable_py_is_loud(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        (root / "pkg" / "broken.py").write_text("def (:\n", encoding="utf-8")
        with pytest.raises(AdapterError, match="does not parse"):
            ground_all(root)


# --- §3.3: secret-scan cleanliness (compose refuses secret-shaped fact strings) ---------------


class TestSecretShapeCleanliness:
    def test_every_representative_fact_string_is_clean(self, tmp_path):
        result = ground_all(make_tree(tmp_path / "corpus"))
        assert result.facts, "the corpus must ground at least one fact"
        for fact in result.facts:
            assert ir.looks_secret_shaped(fact.subject) is None
            assert ir.looks_secret_shaped(fact.claim) is None


# --- rule 1: zero write syscalls + no graph ---------------------------------------------------


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


class TestReadOnly:
    def test_ground_leaves_the_tree_byte_identical(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        before = snapshot(tmp_path)
        ground_all(root, query="the framework itself")
        ground_all(root)  # and the unfiltered pass
        assert snapshot(tmp_path) == before  # zero writes toward the source, ever

    def test_module_source_has_no_write_primitives(self):
        # Rule 1 structural: the adapter module cannot write and stores no graph — no
        # filesystem write primitive appears in its source (reads via read_text + os.walk
        # + ast.parse), and its ONLY subprocess is the read-only `git rev-parse HEAD`.
        import pipeline.adapters.fsast as module

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
            assert token not in source, f"write primitive {token!r} found in fsast adapter"
        assert source.count("subprocess.run(") == 1
        assert '"rev-parse"' in source and '"HEAD"' in source

    def test_contract_shape(self):
        assert issubclass(FsAstAdapter, SourceAdapter)
        assert FsAstAdapter.name == "fsast"
        assert FsAstAdapter.capabilities == frozenset({"query"})


# --- resolver integration: real anchors -> citable ---------------------------------------------


class TestResolverIntegration:
    def test_facts_are_citable_through_the_resolver(self, tmp_path):
        # SM9 through the resolver: every #3/#9 fact carries a resolvable file-line anchor,
        # so the COMPUTED citability is True (grounding.py: citable = len(anchors) > 0).
        root = make_tree(tmp_path / "corpus")
        outcome = ground_item(
            item="item-1",
            query="the framework itself",
            pool=[SourceInstance(id="x-code", adapter="fsast", connection={"path": str(root)})],
            selection=resolve_selection(),
            adapters={"fsast": FsAstAdapter()},
            now=NOW,
        )
        assert outcome.status == "ok"
        assert outcome.facts
        assert all(fact.citable for fact in outcome.facts)


# --- CF-1: git-checkout commit provenance (ground == pin_commit) + commitless posture ----------

HAS_GIT = shutil.which("git") is not None
requires_git = pytest.mark.skipif(not HAS_GIT, reason="git binary not available")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def make_git_tree(tmp_path: Path) -> Path:
    root = make_tree(tmp_path / "gittree")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "FsAst Adapter Test")
    _git(root, "add", "-A")
    _git(root, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "tree")
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
        root = make_git_tree(tmp_path)
        head = real_head(root)
        assert len(head) == 40
        adapter = FsAstAdapter()
        pinned = adapter.pin_commit({"path": str(root)})
        grounded = adapter.ground(connection={"path": str(root)}, query="").built_at_commit
        assert pinned == grounded == head  # CF-1: identity + ledger agree on HEAD

    def test_plain_directory_is_commitless(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        assert FsAstAdapter()._head_commit(root) is None
        assert FsAstAdapter().pin_commit({"path": str(root)}) is None
        assert ground_all(root).built_at_commit is None

    def test_git_helper_returns_none_when_git_absent(self, tmp_path, monkeypatch):
        import pipeline.adapters.fsast as module

        def boom(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(module.subprocess, "run", boom)
        root = make_tree(tmp_path / "corpus")
        assert FsAstAdapter()._head_commit(root) is None
        assert ground_all(root).built_at_commit is None


class TestReadOnlyGitCall:
    def test_only_subprocess_is_read_only_git_rev_parse(self, tmp_path, monkeypatch):
        import pipeline.adapters.fsast as module

        recorded: list[list[str]] = []

        class _Outcome:
            returncode = 0
            stdout = "ab" * 20 + "\n"
            stderr = ""

        def recorder(argv, **kwargs):
            recorded.append(list(argv))
            return _Outcome()

        monkeypatch.setattr(module.subprocess, "run", recorder)
        root = make_tree(tmp_path / "corpus")
        result = ground_all(root)
        assert result.built_at_commit == "ab" * 20
        assert recorded == [["git", "-C", str(root.resolve()), "rev-parse", "HEAD"]]


# --- budget: in-band first-N truncation -------------------------------------------------------


class TestBudget:
    def test_budget_is_a_connection_key_in_the_closed_set(self):
        assert CONNECTION_KEYS == frozenset({"path", "budget"})

    def test_budget_caps_total_facts_first_n_in_walk_order(self, tmp_path):
        # walk order: root tree, pkg tree, then pkg/core.py signatures (source order).
        root = make_tree(tmp_path / "corpus")
        capped = FsAstAdapter().ground(connection={"path": str(root), "budget": 3}, query="")
        assert [f.subject for f in capped.facts] == [".", "pkg", "pkg/core.py::build"]

    def test_over_budget_truncates_deterministically_not_an_error(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        one = FsAstAdapter().ground(connection={"path": str(root), "budget": 1}, query="")
        assert [f.subject for f in one.facts] == ["."]  # just the root tree fact
        again = FsAstAdapter().ground(connection={"path": str(root), "budget": 1}, query="")
        assert one == again  # deterministic first-N, every time

    def test_budget_absent_applies_default(self, tmp_path):
        assert DEFAULT_BUDGET == 2000
        root = make_tree(tmp_path / "corpus")
        result = FsAstAdapter().ground(connection={"path": str(root)}, query="")
        assert 0 < len(result.facts) < DEFAULT_BUDGET  # small tree, well under the cap

    @pytest.mark.parametrize("bad", [0, -1, -5, 3.0, "2", True, False, None])
    def test_invalid_budget_is_a_typed_error(self, tmp_path, bad):
        root = make_tree(tmp_path / "corpus")
        with pytest.raises(AdapterError, match="budget must be a positive integer"):
            FsAstAdapter().ground(connection={"path": str(root), "budget": bad}, query="")
