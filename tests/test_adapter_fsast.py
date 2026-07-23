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
    CLI_FACET_KEYS,
    CONNECTION_KEYS,
    DEFAULT_BUDGET,
    MODE_BOTH,
    MODE_CLI,
    MODE_SIGNATURES,
    MODE_TREE,
    MODES,
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

# A synthetic argparse module for the #CLI (`mode: cli`) family: a literal long flag with
# facets, a multi-string `-v`/`--verbose` flag, a positional, a DYNAMIC (non-literal) flag
# that must be skipped in-band, and — crucially — the SAME `--workspace` flag redeclared in
# two subparsers so the `@L<lineno>` call-site scope is exercised (distinct subjects).
CLI_PY = '''\
"""A CLI entrypoint."""
import argparse


def build_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", help="the client workspace", type=Path, required=True)
    parser.add_argument("-v", "--verbose", action="store_true", help="be chatty")
    parser.add_argument("path", help="input file")
    parser.add_argument(dynamic_flag, help="not groundable")  # non-literal first arg -> skip

    sub = parser.add_subparsers()
    build = sub.add_parser("build")
    build.add_argument("--workspace", help="build workspace", default="./out")

    serve = sub.add_parser("serve")
    serve.add_argument("--workspace", help="serve workspace", default="./srv")
    return parser
'''


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


def make_skip_tree(root: Path) -> Path:
    """`make_tree` plus a `skip_dirs` target `foo/` and a NON-skipped sibling `keep/`, each
    carrying a distinctly-named signature so pruning vs. survival is unambiguous."""
    make_tree(root)  # pkg/, readme.md, workspaces/ (always pruned), .hidden-dir, .draft.py
    (root / "foo").mkdir()
    (root / "foo" / "mod.py").write_text("def foo_fn():\n    return 1\n", encoding="utf-8")
    (root / "keep").mkdir()
    (root / "keep" / "kept.py").write_text("def kept_fn():\n    return 2\n", encoding="utf-8")
    return root


def make_cli_tree(root: Path) -> Path:
    """A one-file corpus whose `cli.py` declares a battery of argparse flags (literal, multi-
    string, positional, dynamic-skip, and `--workspace` redeclared in two subparsers)."""
    root.mkdir(parents=True)
    (root / "cli.py").write_text(CLI_PY, encoding="utf-8")
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
        assert CONNECTION_KEYS == frozenset({"path", "budget", "mode", "skip_dirs"})
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
        assert CONNECTION_KEYS == frozenset({"path", "budget", "mode", "skip_dirs"})

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


# --- C2b: `mode` — scoped grounding (tree #3 vs. signatures #9 as SEPARATE sources) -----------


def ground_mode(root: Path, mode, query: str = "q"):
    return FsAstAdapter().ground(connection={"path": str(root), "mode": mode}, query=query)


class TestScopeMode:
    def test_mode_constants_and_default(self):
        assert MODE_BOTH == "both" and MODE_TREE == "tree" and MODE_SIGNATURES == "signatures"
        assert MODE_CLI == "cli"
        assert MODES == frozenset({"both", "tree", "signatures", "cli"})

    def test_mode_absent_equals_both_byte_identical(self, tmp_path):
        # omit-when-absent, no churn: an absent `mode` is byte-identical to `mode: both`.
        root = make_tree(tmp_path / "corpus")
        absent = FsAstAdapter().ground(connection={"path": str(root)}, query="q")
        both = ground_mode(root, MODE_BOTH)
        assert absent.facts == both.facts and len(absent.facts) > 0

    def test_mode_tree_emits_only_tree_facts(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        result = ground_mode(root, MODE_TREE)
        assert len(result.facts) >= 1
        assert all(" contains:" in f.claim for f in result.facts)  # every fact is a #3 tree fact
        assert all("::" not in f.subject for f in result.facts)  # NO #9 signature fact present
        # the #3 family is EXACTLY the tree subset `both` emits, same objects, same order
        both = ground_mode(root, MODE_BOTH)
        assert result.facts == tuple(f for f in both.facts if " contains:" in f.claim)

    def test_mode_signatures_emits_only_signature_facts(self, tmp_path):
        root = make_tree(tmp_path / "corpus")
        result = ground_mode(root, MODE_SIGNATURES)
        assert len(result.facts) >= 1
        assert all("::" in f.subject for f in result.facts)  # every fact is a #9 signature
        assert all(" contains:" not in f.claim for f in result.facts)  # NO #3 tree fact present
        # the #9 family is EXACTLY the signature subset `both` emits, same objects, same order
        both = ground_mode(root, MODE_BOTH)
        assert result.facts == tuple(f for f in both.facts if "::" in f.subject)

    def test_tree_plus_signatures_partition_both(self, tmp_path):
        # tree + signatures is a clean partition of both: no loss, no overlap, no duplication.
        root = make_tree(tmp_path / "corpus")

        def keys(mode):
            return [(f.subject, f.claim) for f in ground_mode(root, mode).facts]

        both, tree, sigs = keys(MODE_BOTH), keys(MODE_TREE), keys(MODE_SIGNATURES)
        assert set(tree) | set(sigs) == set(both)
        assert set(tree) & set(sigs) == set()
        assert len(tree) + len(sigs) == len(both)

    @pytest.mark.parametrize("bad", ["signature", "TREE", "all", "", "sigs", 3, None, True])
    def test_unknown_mode_is_loud(self, tmp_path, bad):
        root = make_tree(tmp_path / "corpus")
        with pytest.raises(AdapterError, match="mode must be one of"):
            ground_mode(root, bad)

    @pytest.mark.parametrize("mode", [MODE_BOTH, MODE_TREE, MODE_SIGNATURES])
    def test_query_insensitivity_and_reproducibility_hold_per_mode(self, tmp_path, mode):
        # R4 + reproducibility survive the scoping: within each mode the query content
        # NEVER changes the (non-empty) output, and repeat grounding is byte-identical.
        root = make_tree(tmp_path / "corpus")
        empty = ground_mode(root, mode, query="")
        real = ground_mode(root, mode, query="the framework itself")
        token = ground_mode(root, mode, query="pkg")
        assert empty.facts == real.facts == token.facts and len(empty.facts) > 0
        assert ground_mode(root, mode) == ground_mode(root, mode)  # reproducible per mode


# --- C2b: `skip_dirs` — extra mid-walk prunes, IN ADDITION to the always-pruned set ------------


class TestSkipDirs:
    def test_skip_dirs_prunes_named_dir_and_sibling_survives(self, tmp_path):
        root = make_skip_tree(tmp_path / "corpus")
        result = FsAstAdapter().ground(
            connection={"path": str(root), "skip_dirs": ["foo"]}, query="q"
        )
        blob = " ".join(f"{f.subject} {f.claim} {f.anchors[0].value}" for f in result.facts)
        assert "foo" not in blob  # planted foo/ pruned everywhere: no tree fact, no listing...
        assert "foo_fn" not in blob  # ...and no signature grounded from foo/mod.py
        # the NON-skipped sibling keep/ survives: listed at root, own tree fact, own signature
        root_listing = by_subject(result)["."].claim
        assert "keep/" in root_listing and "foo/" not in root_listing
        assert "keep" in by_subject(result)  # keep/ still gets its own #3 tree fact
        assert by_subject(result)["keep/kept.py::kept_fn"].claim == "def kept_fn()"

    def test_skip_dirs_adds_to_the_always_pruned_set(self, tmp_path):
        # skip_dirs is IN ADDITION to workspaces/__pycache__/dot-dirs — all stay pruned.
        root = make_skip_tree(tmp_path / "corpus")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\x00")
        result = FsAstAdapter().ground(
            connection={"path": str(root), "skip_dirs": ["foo"]}, query="q"
        )
        blob = " ".join(f"{f.subject} {f.claim}" for f in result.facts)
        for pruned in (
            "foo", WORKSPACES_DIRNAME, "__pycache__", ".hidden-dir",
            "secret_code", "leaked_symbol",
        ):
            assert pruned not in blob
        assert by_subject(result)["pkg/core.py::build"]  # the ordinary tree still grounds

    def test_skip_dirs_absent_or_empty_is_current_behavior(self, tmp_path):
        # absent == [] : no extra prune, no churn against pre-C2b behavior.
        root = make_tree(tmp_path / "corpus")
        absent = FsAstAdapter().ground(connection={"path": str(root)}, query="q")
        empty = FsAstAdapter().ground(connection={"path": str(root), "skip_dirs": []}, query="q")
        assert absent.facts == empty.facts and len(absent.facts) > 0

    def test_skip_dirs_query_insensitive_and_reproducible(self, tmp_path):
        root = make_skip_tree(tmp_path / "corpus")
        conn = {"path": str(root), "skip_dirs": ["foo"]}
        a = FsAstAdapter().ground(connection=conn, query="")
        b = FsAstAdapter().ground(connection=conn, query="the framework itself")
        assert a == b and len(a.facts) > 0  # the extra prune is query-insensitive + reproducible

    def test_mode_and_skip_dirs_combine(self, tmp_path):
        # tree mode + skip_dirs together: only #3 facts, and foo/ still pruned from them.
        root = make_skip_tree(tmp_path / "corpus")
        result = FsAstAdapter().ground(
            connection={"path": str(root), "mode": MODE_TREE, "skip_dirs": ["foo"]}, query="q"
        )
        assert len(result.facts) >= 1
        assert all(" contains:" in f.claim for f in result.facts)  # tree only
        blob = " ".join(f.claim for f in result.facts)
        assert "foo" not in blob and "keep/" in by_subject(result)["."].claim

    @pytest.mark.parametrize("bad", ["foo", 7, {"foo"}, True, None])
    def test_skip_dirs_non_list_is_loud(self, tmp_path, bad):
        root = make_tree(tmp_path / "corpus")
        with pytest.raises(AdapterError, match="skip_dirs must be a list"):
            FsAstAdapter().ground(connection={"path": str(root), "skip_dirs": bad}, query="q")

    @pytest.mark.parametrize("bad", [[""], ["ok", ""], ["   "], [123], ["ok", None], [True]])
    def test_skip_dirs_bad_element_is_loud(self, tmp_path, bad):
        root = make_tree(tmp_path / "corpus")
        with pytest.raises(AdapterError, match="skip_dirs entries must be non-empty"):
            FsAstAdapter().ground(connection={"path": str(root), "skip_dirs": bad}, query="q")


# --- MG-2 byte-identity: the pre-cli legacy-mode shape is pinned + unchanged -------------------

#: A golden snapshot of the DEFAULT (`both`) output for `make_tree`, captured pre-cli under
#: py312 `ast.unparse`. Adding `mode: cli` is purely ADDITIVE, so this exact ordered
#: (subject, claim) sequence must survive byte-for-byte — the fact-level proof that the legacy
#: modes are untouched (complements the walk-order/anchor/tier assertions elsewhere).
DEFAULT_MODE_SNAPSHOT = [
    (".", "./ contains: pkg/, readme.md"),
    ("pkg", "pkg/ contains: __init__.py, core.py"),
    ("pkg/core.py::build", "def build(plan, item, *, budget: int=10) -> str"),
    ("pkg/core.py::fetch", "async def fetch(url)"),
    ("pkg/core.py::Widget", "class Widget(Base)"),
    ("pkg/core.py::Widget.run", "def run(self, mode: str='fast') -> bool"),
    ("pkg/core.py::Widget.close", "async def close(self)"),
]


class TestLegacyModeByteIdentity:
    def test_default_mode_full_ordered_snapshot_is_unchanged(self, tmp_path):
        # absent-mode and explicit `both` both reproduce the pinned pre-cli shape, verbatim.
        root = make_tree(tmp_path / "corpus")
        for conn in ({"path": str(root)}, {"path": str(root), "mode": MODE_BOTH}):
            result = FsAstAdapter().ground(connection=conn, query="the framework itself")
            assert [(f.subject, f.claim) for f in result.facts] == DEFAULT_MODE_SNAPSHOT

    def test_grounded_twice_stable_across_all_legacy_modes(self, tmp_path):
        # grounded-twice-stable for every pre-cli mode: repeat grounding is byte-identical.
        root = make_tree(tmp_path / "corpus")
        for conn in (
            {"path": str(root)},
            {"path": str(root), "mode": MODE_BOTH},
            {"path": str(root), "mode": MODE_TREE},
            {"path": str(root), "mode": MODE_SIGNATURES},
        ):
            first = FsAstAdapter().ground(connection=conn, query="q")
            second = FsAstAdapter().ground(connection=conn, query="q")
            assert first == second


# --- MG-2: `mode: cli` — argparse command-line-flag grounding (opt-in, additive) --------------


def ground_cli(root: Path, query: str = "q", **extra):
    return FsAstAdapter().ground(
        connection={"path": str(root), "mode": MODE_CLI, **extra}, query=query
    )


class TestCliMode:
    def test_cli_facet_keys_are_a_fixed_deterministic_tuple(self):
        assert CLI_FACET_KEYS == ("help", "type", "required", "default", "action")

    def test_cli_mode_emits_expected_flag_facts(self, tmp_path):
        facts = by_subject(ground_cli(make_cli_tree(tmp_path / "cli-corpus")))
        # a literal long flag folds its cheap facets (help/type/required) in the fixed order:
        top_ws = facts["cli.py::--workspace@L7"]
        assert top_ws.claim == (
            "--workspace (help='the client workspace', type=Path, required=True)"
        )
        assert top_ws.tier == TIER_EXTRACTED and top_ws.refinements == {}
        # a multi-string flag lists ALL options, keys on the first `--` long option, and pulls
        # help + action (default/type/required absent, so dropped) in CLI_FACET_KEYS order:
        assert facts["cli.py::--verbose@L8"].claim == (
            "-v, --verbose (help='be chatty', action='store_true')"
        )
        # a bare positional keys on itself (no `--` long option present):
        assert facts["cli.py::path@L9"].claim == "path (help='input file')"

    def test_cli_subject_scoped_by_call_site_line_with_anchor(self, tmp_path):
        # subject = <relpath>::<flag>@L<lineno>; anchor = the add_argument call site (#9 scheme).
        facts = by_subject(ground_cli(make_cli_tree(tmp_path / "cli-corpus")))
        fact = facts["cli.py::--verbose@L8"]
        assert fact.anchors == (Anchor("file-line", "cli.py:L8"),)
        assert anchor_line(fact) == 8
        assert "--verbose" in CLI_PY.splitlines()[anchor_line(fact) - 1]

    def test_same_flag_in_two_subparsers_gets_distinct_subjects(self, tmp_path):
        # THE collision test: `--workspace` is declared THREE times (top parser + `build` +
        # `serve` subparsers). The @L<lineno> call-site scope keeps every one a DISTINCT,
        # collision-free subject — WITHOUT it they collapse into one subject (a same-subject-
        # different-claim resolver conflict).
        facts = ground_cli(make_cli_tree(tmp_path / "cli-corpus")).facts
        ws = [f for f in facts if f.subject.startswith("cli.py::--workspace@L")]
        assert len(ws) == 3
        assert len({f.subject for f in ws}) == 3       # three distinct subjects
        assert len({anchor_line(f) for f in ws}) == 3  # each at its own call-site line
        assert len({f.claim for f in ws}) == 3         # each carries its own help/default facet
        assert sorted(f.subject for f in ws) == [
            "cli.py::--workspace@L14",
            "cli.py::--workspace@L17",
            "cli.py::--workspace@L7",
        ]

    def test_dynamic_nonliteral_add_argument_is_skipped_in_band(self, tmp_path):
        # `add_argument(dynamic_flag, ...)` — first positional is NOT a string literal, so it
        # is NOT groundable and is SKIPPED IN-BAND (no error, no fact), like the budget cap.
        result = ground_cli(make_cli_tree(tmp_path / "cli-corpus"))
        assert len(result.facts) == 5  # 3 top-level literal flags + 2 subparser --workspace
        for fact in result.facts:
            assert "dynamic_flag" not in fact.subject and "dynamic_flag" not in fact.claim
            assert "not groundable" not in fact.claim  # the skipped call's help never rode a fact

    def test_cli_facts_are_extracted_with_line_anchor_and_file_mtime(self, tmp_path):
        root = make_cli_tree(tmp_path / "cli-corpus")
        expected_as_of = datetime.date.fromtimestamp((root / "cli.py").stat().st_mtime)
        for fact in ground_cli(root).facts:
            assert fact.tier == TIER_EXTRACTED
            assert fact.anchors[0].kind == "file-line"
            assert fact.anchors[0].value.startswith("cli.py:L")
            assert fact.as_of == expected_as_of
            assert fact.refinements == {}

    def test_cli_mode_emits_no_tree_or_signature_facts(self, tmp_path):
        # cli is standalone: no #3 tree fact (no " contains:") and no #9 signature fact.
        result = ground_cli(make_cli_tree(tmp_path / "cli-corpus"))
        assert all(" contains:" not in f.claim for f in result.facts)  # NO tree fact
        assert all("@L" in f.subject for f in result.facts)  # every subject is a #CLI call site
        # a tree WITH signatures but NO argparse grounds ZERO facts under cli (empty != error).
        assert ground_cli(make_tree(tmp_path / "plain")).facts == ()

    def test_cli_query_insensitive_and_reproducible(self, tmp_path):
        root = make_cli_tree(tmp_path / "cli-corpus")
        empty = ground_cli(root, query="")
        real = ground_cli(root, query="the framework itself")
        token = ground_cli(root, query="workspace")
        assert empty.facts == real.facts == token.facts and len(empty.facts) > 0
        assert ground_cli(root) == ground_cli(root)  # byte-identical repeat

    def test_cli_budget_caps_first_n_in_deterministic_walk_order(self, tmp_path):
        # in-band first-N cap holds for cli: the first two call sites in ascending-line order.
        root = make_cli_tree(tmp_path / "cli-corpus")
        capped = ground_cli(root, budget=2)
        assert [f.subject for f in capped.facts] == [
            "cli.py::--workspace@L7",
            "cli.py::--verbose@L8",
        ]
        assert ground_cli(root, budget=2) == capped  # deterministic first-N, every time

    def test_cli_unparseable_py_is_loud(self, tmp_path):
        # cli reads via the SAME loud read path as _signatures: a broken .py is a typed error.
        root = make_cli_tree(tmp_path / "cli-corpus")
        (root / "broken.py").write_text("def (:\n", encoding="utf-8")
        with pytest.raises(AdapterError, match="does not parse"):
            ground_cli(root)

    def test_cli_undecodable_py_is_loud(self, tmp_path):
        root = make_cli_tree(tmp_path / "cli-corpus")
        (root / "binary.py").write_bytes(b"\xff\xfe\x00garbage")
        with pytest.raises(AdapterError, match="not UTF-8"):
            ground_cli(root)

    @pytest.mark.parametrize("bad", ["CLI", "cli ", "argparse", "flags"])
    def test_unknown_mode_still_loud_and_cli_is_accepted(self, tmp_path, bad):
        # cli joined MODES (accepted); a look-alike is still the loud unknown-mode error.
        root = make_cli_tree(tmp_path / "cli-corpus")
        assert len(ground_cli(root).facts) == 5  # `cli` itself is NOT rejected
        with pytest.raises(AdapterError, match="mode must be one of"):
            FsAstAdapter().ground(connection={"path": str(root), "mode": bad}, query="q")
