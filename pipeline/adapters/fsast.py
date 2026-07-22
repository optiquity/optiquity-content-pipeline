"""The REAL `fsast` adapter — read-only FILESYSTEM + Python-AST source grounding.

Design authority: `docs/design.md` §6.1 — a source is a pluggable READ-ONLY grounding
provider; the ADAPTER is code, the SOURCE INSTANCE is config. §6.2 — per-fact tier,
anchors, freshness basis "derived (commit/mtime)". §3.3 + CLAUDE.md rule 1 — sources are
READ-ONLY, always. This is the project-manual genre's structural source (planner-03
Part C, FD1-b): it grounds a repository's own SHAPE — its directory tree (#3 repository
layout) and its Python API surface (#9) — as EXTRACTED facts a manual can cite.

What it does: walks one bound local directory (deterministically: parent-first,
lexicographic; hidden entries, symlinks, and any `workspaces`/`__pycache__` subdir skipped)
and emits two families of `Fact`, ALL `tier = EXTRACTED` (each claim is mechanically derived,
resolvable statement about the source — "the tree literally contains this", "this file
literally declares this signature" — exactly §6.5's EXTRACTED answer to *how sure*):

- **#3 filesystem tree — one fact per walked directory.** `subject` = the directory
  relpath-from-root (`.` for the root, POSIX); `claim` = a deterministic sorted one-line
  listing of the directory's immediate entries (subdirs suffixed `/`), e.g.
  ``adapters/ contains: __init__.py, base.py, folder.py, fsast.py, graphify.py, mock.py``;
  `anchors` = one `file-line` anchor whose locator is the directory relpath (a directory
  locator is a resolvable position — `base.Anchor` requires only a non-empty string — so
  the fact is `citable`); `as_of` = the directory's mtime date.
- **#9 API surface — one fact per top-level `def`/`class` (plus one level of class
  methods) in each `.py`.** Parsed via the `ast` stdlib. `subject` =
  ``<file-relpath>::<qualname>`` (e.g. ``driver.py::run_thread`` or
  ``folder.py::FolderAdapter.ground``); `claim` = the reconstructed one-line signature
  (``def run_thread(plan, item, ...) -> ArtifactResult`` / ``class FolderAdapter(SourceAdapter)``),
  arg names + cheap annotations via `ast.unparse`; `anchors` = one `file-line` anchor
  ``<relpath>:L<lineno>``; `as_of` = the file's mtime date.

**Query-INSENSITIVE (planner-03 R4).** The adapter validates that `query` is a `str`
(loud if not) and then IGNORES its content: it emits the FULL tree + signature set
regardless of the query, budget-capped in deterministic walk order. The single humanized
topic query the driver hands every source (grounding.py) must NOT be able to silently
drop the structural facts — so, unlike `folder`'s coarse substring, `fsast` never filters.

- **`built_at_commit`** = the bound directory's git **HEAD** for a git-checkout (via the
  same read-only `git rev-parse HEAD` the graphify/folder adapters use), so the adapter is
  compose-capable and its §7.2 identity commit-map agrees with the §15 grounding ledger
  (CF-1: `ground()` and `pin_commit()` report the SAME commit). A plain non-git directory
  has no HEAD → `None` (`base.GroundingResult`'s commitless posture).
- **Fact budget (`budget` connection key)** — a positive int (default `DEFAULT_BUDGET`)
  that caps the TOTAL emitted facts to the first `budget` in the deterministic walk order
  (parent-first, lexicographic). The cap is deterministic and IN-BAND — an over-budget
  tree truncates to the first N; it is NOT an error.
- **Content-kind tagging (§6.1 SM5):** the kind tag rides the SOURCE INSTANCE, not the
  adapter; the adapter classifies nothing per fact (it has no signal to), so it emits NO
  refinements and the instance's kind defaults ride intact — the same no-overstep posture
  as `folder`/`graphify`.

Rule 1 is STRUCTURAL: the module contains no write primitive at all — it READS via
`Path.read_text` + `ast.parse`, walks via `os.walk` with `followlinks=False`, and its ONLY
subprocess is the read-only `git rev-parse HEAD` (never a state-changing git verb, never a
write). The bound path is refused if it IS or lies inside this repo's `workspaces/` (rule
1/2), AND any `workspaces` directory met mid-walk is pruned (planner-03 R6). A `__pycache__`
bytecode-cache dir is pruned too, so the fact set stays a function of the COMMITTED source
(reproducible under the commit pin), never of transient `.pyc` build artifacts. A test scans
this source for write primitives and snapshots a grounded tree byte-for-byte.

Loud, never silent: an absent/relative/non-directory path, an unknown connection key, an
undecodable file, and an unparseable `.py` are typed `AdapterError`s. An EMPTY result (a
directory with nothing to ground) is NOT an error — the resolver's walk owns that outcome.
"""

from __future__ import annotations

import ast
import datetime
import os
import subprocess
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.adapters.base import (
    TIER_EXTRACTED,
    AdapterError,
    Anchor,
    Fact,
    GroundingResult,
    SourceAdapter,
)

__all__ = [
    "CONNECTION_KEYS",
    "DEFAULT_BUDGET",
    "FsAstAdapter",
    "PY_SUFFIX",
    "PYCACHE_DIRNAME",
    "REPO_WORKSPACES",
    "WORKSPACES_DIRNAME",
]

#: The parsed-source extension: `fsast` reads Python files for their API surface.
PY_SUFFIX = ".py"

#: The per-invocation fact budget default — mirrors folder/graphify. `fsast` emits one tree
#: fact per directory plus one signature fact per top-level def/class (+ one level of class
#: methods), so a large repo can emit many facts; the budget caps the output to the first N
#: in walk order. 2000 keeps every adapter's contribution to the writer prompt at one ceiling.
DEFAULT_BUDGET = 2000

#: The closed connection-key set: the bound directory + its fact budget, nothing else.
CONNECTION_KEYS = frozenset({"path", "budget"})

#: The directory name that is NEVER walked into (planner-03 R6): client CONTENT lives under
#: `workspaces/`, grounding SOURCES live outside it. Pruned wherever it is met mid-walk.
WORKSPACES_DIRNAME = "workspaces"

#: Python's compiled-bytecode cache dir: gitignored, accumulating BUILD artifacts whose
#: `.pyc` names embed the interpreter version and appear/disappear run-to-run. Pruned
#: mid-walk so the emitted fact set is a function of the COMMITTED source (reproducible
#: under the `built_at_commit` pin), never of whatever `.pyc` files happen to sit on disk.
PYCACHE_DIRNAME = "__pycache__"

#: This repo's workspaces root (CLAUDE.md rule 2): a bound path that IS or lies inside it is
#: refused loudly (grounding sources live OUTSIDE the pipeline's client workspaces).
REPO_WORKSPACES = Path(__file__).resolve().parents[2] / "workspaces"


@dataclass(frozen=True)
class _Connection:
    """One validated connection: the resolved read-only root + the fact budget."""

    root: Path
    budget: int


def _validate_connection(connection: Mapping[str, Any]) -> _Connection:
    if not isinstance(connection, Mapping):
        raise AdapterError(
            f"adapter-failure: fsast connection must be a mapping, "
            f"got {type(connection).__name__}"
        )
    unknown = sorted(set(connection) - CONNECTION_KEYS)
    if unknown:
        raise AdapterError(
            f"adapter-failure: unknown fsast connection key(s) {unknown!r} — the key "
            f"set is CLOSED ({', '.join(sorted(CONNECTION_KEYS))})"
        )
    raw_path = connection.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise AdapterError(
            "adapter-failure: fsast connection requires `path`: the local directory to "
            f"ground from (read by path, rule 1); got {raw_path!r}"
        )
    path = Path(raw_path)
    if not path.is_absolute():
        raise AdapterError(
            f"adapter-failure: fsast connection path must be ABSOLUTE, got {raw_path!r}"
        )
    resolved = path.resolve()
    if resolved == REPO_WORKSPACES or REPO_WORKSPACES in resolved.parents:
        raise AdapterError(
            f"adapter-failure: fsast source path {str(resolved)!r} lies inside this "
            f"repo's workspaces ({str(REPO_WORKSPACES)!r}) — grounding sources live "
            "OUTSIDE the pipeline's client workspaces (CLAUDE.md rules 1/2; planner-03 R6)"
        )
    if not resolved.exists():
        raise AdapterError(
            f"adapter-failure: directory not found: {resolved} — an absent source is a "
            "typed error, never a silent empty"
        )
    if not resolved.is_dir():
        raise AdapterError(
            f"adapter-failure: fsast connection path is not a directory: {resolved}"
        )
    budget = connection.get("budget", DEFAULT_BUDGET)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise AdapterError(
            f"adapter-failure: fsast connection budget must be a positive integer "
            f"(deterministic first-N cap on emitted facts, default {DEFAULT_BUDGET}), "
            f"got {budget!r}"
        )
    return _Connection(root=resolved, budget=budget)


def _function_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """A one-line `def`/`async def` signature reconstructed from the AST (arg names +
    cheap annotations/defaults via `ast.unparse`, plus the return annotation if present)."""
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    signature = f"{prefix} {node.name}({ast.unparse(node.args)})"
    if node.returns is not None:
        signature += f" -> {ast.unparse(node.returns)}"
    return signature


def _class_signature(node: ast.ClassDef) -> str:
    """A one-line `class` signature: name + base list (and metaclass/kw bases if any)."""
    parts = [ast.unparse(base) for base in node.bases]
    parts += [
        f"{kw.arg}={ast.unparse(kw.value)}" if kw.arg else f"**{ast.unparse(kw.value)}"
        for kw in node.keywords
    ]
    signature = f"class {node.name}"
    if parts:
        signature += "(" + ", ".join(parts) + ")"
    return signature


def _signatures(file: Path, relpath: str) -> list[tuple[str, str, int]]:
    """Every top-level `def`/`class` (plus one level of class methods) in a `.py` file, as
    ``(subject, claim, lineno)`` triples in source (ascending-lineno) order. Reads via
    `read_text` + `ast.parse` — no write. Undecodable bytes / unparseable Python are loud
    typed `AdapterError`s (never a silent skip), mirroring folder's undecodable posture."""
    try:
        source = file.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AdapterError(
            f"adapter-failure: source file {relpath!r} is not UTF-8 text: {exc} "
            "(undecodable sources fail loudly, never silently skip)"
        ) from exc
    except OSError as exc:
        raise AdapterError(
            f"adapter-failure: could not read source file {relpath!r}: {exc}"
        ) from exc
    try:
        tree = ast.parse(source, filename=str(file))
    except SyntaxError as exc:
        raise AdapterError(
            f"adapter-failure: source file {relpath!r} does not parse as Python: {exc} "
            "(an unparseable .py is a typed error, never a silent skip)"
        ) from exc
    facts: list[tuple[str, str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts.append((f"{relpath}::{node.name}", _function_signature(node), node.lineno))
        elif isinstance(node, ast.ClassDef):
            facts.append((f"{relpath}::{node.name}", _class_signature(node), node.lineno))
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    facts.append(
                        (
                            f"{relpath}::{node.name}.{child.name}",
                            _function_signature(child),
                            child.lineno,
                        )
                    )
    return facts


class FsAstAdapter(SourceAdapter):
    """`adapter: fsast` — read-only tree(#3) + Python-AST signature(#9) grounding over one
    local directory. Query-INSENSITIVE: it emits the whole structural fact set regardless
    of the query (planner-03 R4)."""

    name = "fsast"

    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        if not isinstance(query, str):
            raise AdapterError(
                f"adapter-failure: query must be a string, got {type(query).__name__}"
            )
        conn = _validate_connection(connection)  # query content is deliberately IGNORED (R4)
        facts: list[Fact] = []
        for fact in self._walk_facts(conn.root):
            facts.append(fact)
            if len(facts) >= conn.budget:
                break  # first-N cap: in-band truncation, NOT an error (docstring)
        return GroundingResult(facts=tuple(facts), built_at_commit=self._head_commit(conn.root))

    def _walk_facts(self, root: Path) -> Iterator[Fact]:
        """The deterministic fact stream: for each directory (parent-first, lexicographic)
        one tree(#3) fact, then the signature(#9) facts of its `.py` files (sorted). Hidden
        entries, symlinks, and any `workspaces`/`__pycache__` subdir are pruned (rule 1/2;
        planner-03 R6 + commit-pin reproducibility)."""
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(dirpath)
            kept_dirs = sorted(
                name
                for name in dirnames
                if not name.startswith(".")
                and name != WORKSPACES_DIRNAME
                and name != PYCACHE_DIRNAME
                and not (here / name).is_symlink()
            )
            dirnames[:] = kept_dirs  # prune the walk to the kept, sorted subdirs
            kept_files = sorted(
                name
                for name in filenames
                if not name.startswith(".") and not (here / name).is_symlink()
            )
            relpath = here.relative_to(root).as_posix()
            yield self._tree_fact(here, relpath, kept_dirs, kept_files)
            for name in kept_files:
                if not name.endswith(PY_SUFFIX):
                    continue
                file = here / name
                file_rel = file.relative_to(root).as_posix()
                file_as_of = datetime.date.fromtimestamp(file.stat().st_mtime)
                for subject, claim, lineno in _signatures(file, file_rel):
                    yield Fact(
                        subject=subject,
                        claim=claim,
                        tier=TIER_EXTRACTED,  # a mechanically derived signature (docstring)
                        anchors=(Anchor("file-line", f"{file_rel}:L{lineno}"),),
                        as_of=file_as_of,
                        refinements={},  # the adapter classifies nothing; kind defaults ride
                    )

    def _tree_fact(
        self, here: Path, relpath: str, kept_dirs: list[str], kept_files: list[str]
    ) -> Fact:
        """One #3 directory-listing fact: subject = dir relpath, claim = a sorted one-line
        listing (subdirs suffixed `/`), anchor = the dir relpath locator (citable)."""
        listing = sorted([f"{name}/" for name in kept_dirs] + list(kept_files))
        entries = ", ".join(listing) if listing else "(empty)"
        return Fact(
            subject=relpath,
            claim=f"{relpath}/ contains: {entries}",
            tier=TIER_EXTRACTED,  # the tree literally contains these entries (docstring)
            anchors=(Anchor("file-line", relpath),),
            as_of=datetime.date.fromtimestamp(here.stat().st_mtime),
            refinements={},  # the adapter classifies nothing; kind defaults ride
        )

    def _head_commit(self, root: Path) -> str | None:
        """`git -C <bound dir> rev-parse HEAD` — the READ-ONLY commit pin (git discovers the
        enclosing checkout root itself). ANY failure — git absent, not a repo, non-zero exit
        — is commitless (`None`), the designed plain-directory posture; never an error, never
        a write (rule 1). Mirrors the folder/graphify adapters."""
        argv = ["git", "-C", str(root), "rev-parse", "HEAD"]
        try:
            proc = subprocess.run(  # noqa: S603 — list-form read-only rev-parse, no shell
                argv, capture_output=True, text=True, check=False
            )
        except FileNotFoundError:
            return None
        if proc.returncode != 0:
            return None
        lines = proc.stdout.strip().splitlines()
        head = lines[0].strip() if lines else ""
        return head or None

    def pin_commit(self, connection: Mapping[str, Any]) -> str | None:
        """The §7.2 identity commit-map value — read by the SAME read-only provenance path
        `ground()` uses (`git rev-parse HEAD` over the bound dir), so the artifact-id
        commit-map (identity, §7.2) and the §15 grounding ledger NEVER disagree about
        provenance (CF-1). A git checkout pins its HEAD; a plain directory stays commitless
        (`None`). Read-only, never a write (rule 1)."""
        conn = _validate_connection(connection)
        return self._head_commit(conn.root)
