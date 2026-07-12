"""The REAL `graphify` adapter (plan step 18) — read-only query of a client graph by path.

Contract of record: the step-05 report §6 (graphify v0.8.39, as observed live):

- **Invocation:** ``graphify query "<question>" --graph <ABS>/graphify-out/graph.json
  --budget <N> [--context <c>]... [--dfs]``. The question is POSITIONAL and MUST precede
  all flags (argv[2]); ``--graph`` is always passed absolute (the tool default is
  CWD-relative); ``--budget`` is an int, tool default 2000; ``--context`` is repeatable
  over the canonical closed value set.
- **Env:** the command's ONLY side effect is a JSONL append to
  ``~/.cache/graphify-queries.log``; this adapter sets ``GRAPHIFY_QUERY_LOG_DISABLE=1``
  on every invocation, so a grounding run leaves zero traces anywhere (rule 1 posture:
  it never writes to the graph or any repo even without the flag).
- **stdout grammar (exit 0):** header line ``Traversal: BFS|DFS depth=N | Start: [...]
  [| Context: ...] | N nodes found``, blank line, then ``NODE <label> [src=<file|None>
  loc=<loc|None> community=<n>]`` lines, ``EDGE <src> --<relation>
  [<TIER>[ context=<c>]]--> <dst>`` lines, an optional trailing ``... (truncated —``
  marker, OR the single body ``No matching nodes found.``. Anything else is LOUD
  (`AdapterError`) — parsing never silently skips a line it does not recognize.
- **Error surface:** any exit != 0 is `adapter-failure` with stderr line 1 as the
  message; an absent graph file and an absent binary are typed errors too — never a
  silent empty result.
- **graph.json (read-only, same file):** top-level ``built_at_commit`` (the git SHA of
  the graphed checkout) feeds `GroundingResult.built_at_commit` → the resolver's
  commit-map → the §15 grounding ledger's source-commit field.

Design authority: `docs/design.md` §6.1 (adapter = read-only grounding CODE), §6.2
(per-fact tier + anchors + freshness basis "derived (commit/mtime)"), §3.3 + CLAUDE.md
rule 1 (source/client repos READ-ONLY, ALWAYS).

Rule 1 is STRUCTURAL here:

- The module contains **no write primitive at all** — the graph is read via
  `Path.read_text`; the only subprocesses are ``graphify query …`` and
  ``git … rev-parse HEAD`` (both read-only; the plan step-18 objective names the
  read-only git command). A step-18 test scans this source for write primitives and
  snapshots a source dir across `ground()` byte-for-byte.
- The spawned subcommand is the module constant `QUERY_SUBCOMMAND` — argv is built in
  exactly one place with that literal in slot 1, so the step-05 forbidden write verbs
  (`FORBIDDEN_SUBCOMMANDS`: extract/save-result/merge-graphs/…) are UNREACHABLE: no
  connection value, query string, or config key can ever select a different subcommand
  (connection keys are a closed set; the query rides argv[2] as data, list-form exec,
  no shell).
- The graph path is asserted OUTSIDE this repo's `workspaces/` (plan step 18: client
  content lives in workspaces, grounding SOURCES live outside them — a path under
  `workspaces/` is a wiring defect, refused loudly).

In-latitude decisions (step-18 coder; grounded):

- **Facts are the EDGE lines** — the confidence tier rides edges (`links[].confidence`;
  step-05 §3.3), so an edge is the retrievable CLAIM; NODE lines carry the anchors
  (`src=`/`loc=`) and contribute them to the facts of the edges they terminate. Nodes
  alone carry no tier and therefore cannot be facts under the §6.2 contract.
- **`subject` = `claim` = the canonical edge text** (``"<src> --<relation>--> <dst>"``).
  A graph edge ADDRESSES the edge itself (`base.Fact`: subject = "what the claim
  addresses"): graph relations are multi-valued in general (`references`, `calls`, …),
  and this adapter has no functional-relation knowledge, so keying the subject on
  anything coarser (source label, or source+relation) makes every fan-out read as a
  §6.3 conflict and the DEFAULT `downgrade-AMBIGUOUS` strategy silently guts valid
  EXTRACTED facts (observed live: 26/29 facts falsely downgraded — an overstep, §3.1).
  Two graphs asserting the same edge still yield byte-equal (subject, claim), so the
  §6.5 corroboration arithmetic works unchanged; genuinely contradictory edges from a
  graph source are out of the adapter's semantic reach and stay the review gates' lane
  (§19). A future graphify version declaring functional relations can narrow this per
  relation — a one-place change in `_facts`.
- **`as_of` = the graph file's mtime date** — the §6.2 freshness basis is "derived
  (commit/mtime)"; the graph build time is when its facts were last known-true.
- **`review_status` (gate G6, CLOSED degrade-to-unknown):** graphify persists NO
  per-symbol review metadata (step-05 §5, verified on two real graphs), so this adapter
  emits NO `review_status` refinement — the fact rides its content-kind default down to
  the schema floor `unknown` (`content-kinds/_schema.yaml`: "the floor IS the designed
  degradation"). Emitting a literal ``unknown`` refinement instead would clobber a
  user's kind characterization (e.g. `merged-code: reviewed`) — an overstep (§3.1).
- **`built_at_commit` fallback:** when graph.json lacks the field, the plan's read-only
  git command (``git -C <graph dir> rev-parse HEAD``) supplies the checkout's commit;
  when that fails too (not a git checkout), the source is commitless (`None`) — the
  folder-style posture `base.GroundingResult` documents.
- **The binary and the process runner are CONSTRUCTOR wiring, never connection config**
  — a source instance's `connection:` map is user data (§6.1) and must not be able to
  choose executables; tests inject a recording runner through the constructor.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.adapters.base import (
    TIERS,
    AdapterError,
    Anchor,
    Fact,
    GroundingResult,
    SourceAdapter,
)

__all__ = [
    "CANONICAL_CONTEXTS",
    "CONNECTION_KEYS",
    "DEFAULT_BINARY",
    "DEFAULT_BUDGET",
    "FORBIDDEN_SUBCOMMANDS",
    "GraphifyAdapter",
    "NO_MATCH_BODY",
    "ParsedEdge",
    "ParsedNode",
    "ParsedQuery",
    "QUERY_LOG_DISABLE_ENV",
    "QUERY_SUBCOMMAND",
    "REPO_WORKSPACES",
    "RunOutcome",
    "Runner",
    "TRUNCATION_PREFIX",
    "parse_query_output",
]

#: The ONE graphify subcommand this adapter can ever spawn (read-only whitelist member;
#: step-05 report §6). argv slot 1 is built from THIS constant in exactly one place.
QUERY_SUBCOMMAND = "query"

#: The step-05 §6 rule-1 forbidden verbs — every graphify subcommand that writes inside
#: a client checkout (plus `merge-graphs`, which writes an output graph). Kept as data
#: so tests can pin the invocation surface against it; the adapter has NO code path
#: that could place any of these in argv.
FORBIDDEN_SUBCOMMANDS = frozenset(
    {
        "save-result",
        "extract",
        "update",
        "add",
        "watch",
        "label",
        "cluster-only",
        "export",
        "hook",
        "merge-graphs",
    }
)

if QUERY_SUBCOMMAND in FORBIDDEN_SUBCOMMANDS:  # pragma: no cover — structural pin
    raise AssertionError("graphify adapter: the query subcommand collides with a forbidden verb")

#: The querylog kill switch (step-05 §3.5): set on every invocation.
QUERY_LOG_DISABLE_ENV = "GRAPHIFY_QUERY_LOG_DISABLE"

#: Tool defaults per the step-05 contract. The budget is ALWAYS passed explicitly so a
#: tool-side default drift never changes a run silently.
DEFAULT_BINARY = "graphify"
DEFAULT_BUDGET = 2000

#: Canonical `--context` values (step-05 §3.1, from the tool's own alias table).
CANONICAL_CONTEXTS = (
    "call",
    "import",
    "field",
    "parameter_type",
    "return_type",
    "generic_arg",
    "export",
    "attribute",
)

#: The closed connection-key set (`sources/_schema.yaml` `connection:` for this
#: adapter). Closed = a connection can never smuggle extra flags or subcommands.
CONNECTION_KEYS = frozenset({"path", "budget", "context", "dfs"})

#: This repo's workspaces root (CLAUDE.md rule 2): client CONTENT lives there; grounding
#: SOURCES live outside it. A graph path under it is refused loudly (plan step 18).
REPO_WORKSPACES = Path(__file__).resolve().parents[2] / "workspaces"

# --- subprocess seam (injectable for tests; the default is the real thing) ------------------


@dataclass(frozen=True)
class RunOutcome:
    """One finished read-only subprocess: exit code + captured text streams."""

    returncode: int
    stdout: str
    stderr: str


#: The process seam: (argv, env) -> RunOutcome. `FileNotFoundError` = binary absent.
Runner = Callable[[Sequence[str], Mapping[str, str]], RunOutcome]


def _subprocess_runner(argv: Sequence[str], env: Mapping[str, str]) -> RunOutcome:
    """The real runner: list-form exec (no shell), captured output, no check."""
    proc = subprocess.run(  # noqa: S603 — list-form, fixed subcommand, no shell
        list(argv), env=dict(env), capture_output=True, text=True, check=False
    )
    return RunOutcome(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


# --- stdout grammar (step-05 report §6) ------------------------------------------------------

_HEADER_RE = re.compile(r"^Traversal: (?:BFS|DFS) depth=\d+ \| Start: .* \| \d+ nodes found$")
_NODE_RE = re.compile(
    r"^NODE (?P<label>.+?) \[src=(?P<src>.*?) loc=(?P<loc>.*?) community=(?P<community>[^\]]*)\]$"
)
_EDGE_RE = re.compile(
    r"^EDGE (?P<src>.+?) --(?P<relation>[A-Za-z0-9_]+) "
    r"\[(?P<tier>[A-Z]+)(?: context=(?P<context>[^\]]*))?\]--> (?P<dst>.+)$"
)

#: The in-band budget-cut marker (exit stays 0; step-05 §3.4).
TRUNCATION_PREFIX = "... (truncated"

#: The whole-body no-seed answer (exit 0; from the tool source: `_query_graph_text`).
NO_MATCH_BODY = "No matching nodes found."


@dataclass(frozen=True)
class ParsedNode:
    """One NODE line: the label plus its anchor material (`None` = tool-printed None/empty)."""

    label: str
    src: str | None
    loc: str | None


@dataclass(frozen=True)
class ParsedEdge:
    """One EDGE line: the §6.2-carrying unit (the tier rides here)."""

    source: str
    relation: str
    tier: str
    target: str


@dataclass(frozen=True)
class ParsedQuery:
    """One parsed `graphify query` stdout body."""

    nodes: tuple[ParsedNode, ...]
    edges: tuple[ParsedEdge, ...]
    truncated: bool
    no_match: bool


def _none_field(value: str) -> str | None:
    """The tool prints ``str(None)`` / ``str('')`` for absent fields — map both back."""
    return None if value in ("", "None") else value


def parse_query_output(stdout: str) -> ParsedQuery:
    """Parse one `graphify query` stdout body per the step-05 grammar — LOUDLY.

    Every line must be the header, a NODE line, an EDGE line, the truncation marker,
    or blank; the single-line ``No matching nodes found.`` body is the legitimate
    zero-result answer. Any other shape raises `AdapterError` naming the line —
    malformed output is broken machinery, never skippable data.
    """
    if not isinstance(stdout, str):
        raise AdapterError(
            f"adapter-failure: graphify stdout must be text, got {type(stdout).__name__}"
        )
    content = [line for line in stdout.splitlines() if line.strip() != ""]
    if not content:
        raise AdapterError(
            "adapter-failure: graphify query printed nothing — an empty exit-0 body is "
            "outside the step-05 grammar (expected a Traversal header or "
            f"{NO_MATCH_BODY!r})"
        )
    if content[0] == NO_MATCH_BODY:
        if len(content) > 1:
            raise AdapterError(
                "adapter-failure: unexpected output after the no-match body: "
                f"{content[1]!r}"
            )
        return ParsedQuery(nodes=(), edges=(), truncated=False, no_match=True)
    if not _HEADER_RE.match(content[0]):
        raise AdapterError(
            f"adapter-failure: unrecognized graphify header line: {content[0]!r} "
            "(step-05 grammar: 'Traversal: BFS|DFS depth=N | Start: [...] | N nodes found')"
        )
    nodes: list[ParsedNode] = []
    edges: list[ParsedEdge] = []
    truncated = False
    for line in content[1:]:
        if line.startswith("NODE "):
            match = _NODE_RE.match(line)
            if match is None:
                raise AdapterError(f"adapter-failure: malformed NODE line: {line!r}")
            nodes.append(
                ParsedNode(
                    label=match["label"],
                    src=_none_field(match["src"]),
                    loc=_none_field(match["loc"]),
                )
            )
        elif line.startswith("EDGE "):
            match = _EDGE_RE.match(line)
            if match is None:
                raise AdapterError(f"adapter-failure: malformed EDGE line: {line!r}")
            tier = match["tier"]
            if tier not in TIERS:
                raise AdapterError(
                    f"adapter-failure: unknown confidence tier {tier!r} on EDGE line "
                    f"{line!r} (§6.2 tiers: {', '.join(TIERS)})"
                )
            edges.append(
                ParsedEdge(
                    source=match["src"],
                    relation=match["relation"],
                    tier=tier,
                    target=match["dst"],
                )
            )
        elif line.startswith(TRUNCATION_PREFIX):
            truncated = True
        else:
            raise AdapterError(
                f"adapter-failure: unrecognized graphify output line: {line!r} — the "
                "step-05 grammar knows NODE/EDGE/truncation lines only; parsing stays "
                "loud, never silently skips"
            )
    return ParsedQuery(nodes=tuple(nodes), edges=tuple(edges), truncated=truncated, no_match=False)


# --- connection validation -------------------------------------------------------------------


@dataclass(frozen=True)
class _Connection:
    graph_path: Path
    budget: int
    contexts: tuple[str, ...]
    dfs: bool


def _outside_repo_workspaces(path: Path, *, adapter: str) -> Path:
    """Resolve `path` and refuse it under this repo's `workspaces/` (plan step 18)."""
    resolved = path.resolve()
    if resolved == REPO_WORKSPACES or REPO_WORKSPACES in resolved.parents:
        raise AdapterError(
            f"adapter-failure: {adapter} source path {str(resolved)!r} lies inside this "
            f"repo's workspaces ({str(REPO_WORKSPACES)!r}) — grounding sources live "
            "OUTSIDE the pipeline's client workspaces (CLAUDE.md rules 1/2; plan step 18)"
        )
    return resolved


def _validate_connection(connection: Mapping[str, Any]) -> _Connection:
    if not isinstance(connection, Mapping):
        raise AdapterError(
            f"adapter-failure: graphify connection must be a mapping, "
            f"got {type(connection).__name__}"
        )
    unknown = sorted(set(connection) - CONNECTION_KEYS)
    if unknown:
        raise AdapterError(
            f"adapter-failure: unknown graphify connection key(s) {unknown!r} — the key "
            f"set is CLOSED ({', '.join(sorted(CONNECTION_KEYS))}); a connection can "
            "never smuggle flags or subcommands (rule 1, structural)"
        )
    raw_path = connection.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise AdapterError(
            "adapter-failure: graphify connection requires `path`: the client graph, "
            "e.g. <client-checkout>/graphify-out/graph.json (read by path, rule 1); "
            f"got {raw_path!r}"
        )
    path = Path(raw_path)
    if not path.is_absolute():
        raise AdapterError(
            f"adapter-failure: graphify connection path must be ABSOLUTE (the tool "
            f"default is CWD-relative — step-05 contract), got {raw_path!r}"
        )
    if path.suffix != ".json":
        raise AdapterError(
            f"adapter-failure: graphify connection path must name a .json graph file, "
            f"got {raw_path!r}"
        )
    graph_path = _outside_repo_workspaces(path, adapter="graphify")
    budget = connection.get("budget", DEFAULT_BUDGET)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
        raise AdapterError(
            f"adapter-failure: graphify connection budget must be a positive integer "
            f"(tool contract: --budget int, default {DEFAULT_BUDGET}), got {budget!r}"
        )
    raw_contexts = connection.get("context", ())
    if isinstance(raw_contexts, str) or not isinstance(raw_contexts, Sequence):
        raise AdapterError(
            "adapter-failure: graphify connection context must be a sequence of "
            f"canonical context values, got {raw_contexts!r}"
        )
    for value in raw_contexts:
        if value not in CANONICAL_CONTEXTS:
            raise AdapterError(
                f"adapter-failure: unknown graphify context value {value!r} "
                f"(canonical: {', '.join(CANONICAL_CONTEXTS)})"
            )
    dfs = connection.get("dfs", False)
    if not isinstance(dfs, bool):
        raise AdapterError(
            f"adapter-failure: graphify connection dfs must be a boolean, got {dfs!r}"
        )
    return _Connection(
        graph_path=graph_path, budget=budget, contexts=tuple(raw_contexts), dfs=dfs
    )


# --- the adapter ------------------------------------------------------------------------------


class GraphifyAdapter(SourceAdapter):
    """`adapter: graphify` — read-only BFS/DFS query of `<client>/graphify-out/graph.json`."""

    name = "graphify"

    def __init__(self, *, binary: str = DEFAULT_BINARY, run: Runner | None = None) -> None:
        """`binary`/`run` are machinery wiring (never connection config — see module
        docstring); `run=None` means the real subprocess runner."""
        if not isinstance(binary, str) or not binary.strip():
            raise AdapterError(
                f"adapter-failure: graphify binary must be a non-empty string, got {binary!r}"
            )
        self._binary = binary
        self._run: Runner = _subprocess_runner if run is None else run

    # -- invocation plumbing (rule 1: read-only commands only) --------------------------------

    def _env(self) -> dict[str, str]:
        """The invocation env: the ambient env plus the querylog kill switch."""
        env = dict(os.environ)
        env[QUERY_LOG_DISABLE_ENV] = "1"
        return env

    def _query_argv(self, *, conn: _Connection, query: str) -> list[str]:
        """The ONE place graphify argv is built: `QUERY_SUBCOMMAND` in slot 1, the
        question POSITIONAL in slot 2 (before every flag — step-05 contract)."""
        argv = [
            self._binary,
            QUERY_SUBCOMMAND,
            query,
            "--graph",
            str(conn.graph_path),
            "--budget",
            str(conn.budget),
        ]
        for context in conn.contexts:
            argv.extend(["--context", context])
        if conn.dfs:
            argv.append("--dfs")
        return argv

    def _invoke(self, argv: Sequence[str], env: Mapping[str, str]) -> RunOutcome:
        try:
            return self._run(argv, env)
        except FileNotFoundError as exc:
            raise AdapterError(
                f"adapter-failure: executable not found: {argv[0]!r} — install it or "
                "wire the adapter's `binary` to its location (never a silent empty)"
            ) from exc

    def _graph_provenance(
        self, graph_path: Path, env: Mapping[str, str]
    ) -> tuple[str | None, datetime.date]:
        """Read (built_at_commit, as_of) from graph.json — read-only, loud on damage.

        `built_at_commit` is the graphed checkout's SHA (step-05 §6 — feeds the §15
        ledger via the resolver's commit-map); absent, the plan's read-only git
        fallback asks the checkout itself; failing that the source is commitless.
        `as_of` is the graph file's mtime date (§6.2 freshness basis: commit/mtime).
        """
        try:
            raw = graph_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AdapterError(
                f"adapter-failure: could not read graph file {str(graph_path)!r}: {exc}"
            ) from exc
        except UnicodeDecodeError as exc:
            raise AdapterError(
                f"adapter-failure: graph file {str(graph_path)!r} is not UTF-8 text: {exc}"
            ) from exc
        try:
            document = json.loads(raw)
        except ValueError as exc:
            raise AdapterError(
                f"adapter-failure: graph file {str(graph_path)!r} is not valid JSON: {exc}"
            ) from exc
        if not isinstance(document, Mapping):
            raise AdapterError(
                f"adapter-failure: graph file {str(graph_path)!r} must hold a JSON "
                f"object (node-link graph), got {type(document).__name__}"
            )
        commit = document.get("built_at_commit")
        if not isinstance(commit, str) or not commit.strip():
            commit = self._source_commit_fallback(graph_path, env)
        as_of = datetime.date.fromtimestamp(graph_path.stat().st_mtime)
        return commit, as_of

    def _source_commit_fallback(
        self, graph_path: Path, env: Mapping[str, str]
    ) -> str | None:
        """`git -C <graph dir> rev-parse HEAD` — the plan step-18 READ-ONLY git command
        (git discovers the checkout root itself). Any failure = commitless (`None`),
        the designed folder-style posture; never an error, never a write."""
        argv = ["git", "-C", str(graph_path.parent), "rev-parse", "HEAD"]
        try:
            outcome = self._run(argv, env)
        except FileNotFoundError:
            return None
        if outcome.returncode != 0:
            return None
        lines = outcome.stdout.strip().splitlines()
        head = lines[0].strip() if lines else ""
        return head or None

    # -- fact mapping (module docstring: edges carry the claims, nodes the anchors) -----------

    @staticmethod
    def _node_anchor(node: ParsedNode) -> Anchor | None:
        if node.src is None:
            return None
        kind = "url-fragment" if node.src.startswith(("http://", "https://")) else "file-line"
        value = node.src if node.loc is None else f"{node.src}:{node.loc}"
        return Anchor(kind, value)

    @classmethod
    def _facts(cls, parsed: ParsedQuery, *, as_of: datetime.date) -> tuple[Fact, ...]:
        anchors_by_label: dict[str, Anchor] = {}
        for node in parsed.nodes:
            anchor = cls._node_anchor(node)
            if anchor is not None:
                anchors_by_label.setdefault(node.label, anchor)
        facts: list[Fact] = []
        seen: set[tuple[str, str]] = set()
        for edge in parsed.edges:
            # subject = claim: a graph edge addresses ITSELF (module docstring — the
            # multi-valued-relation ruling, observed live).
            claim = f"{edge.source} --{edge.relation}--> {edge.target}"
            key = (claim, edge.tier)
            if key in seen:  # one instance asserting one edge twice is one fact
                continue
            seen.add(key)
            anchors: list[Anchor] = []
            for label in (edge.source, edge.target):
                anchor = anchors_by_label.get(label)
                if anchor is not None and anchor not in anchors:
                    anchors.append(anchor)
            facts.append(
                Fact(
                    subject=claim,
                    claim=claim,
                    tier=edge.tier,
                    anchors=tuple(anchors),
                    as_of=as_of,
                    # G6 disposition: NO review_status refinement — the kind default
                    # rides (degrade-to-unknown lives at the schema floor).
                    refinements={},
                )
            )
        return tuple(facts)

    # -- the contract entry point --------------------------------------------------------------

    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        if not isinstance(query, str):
            raise AdapterError(
                f"adapter-failure: query must be a string, got {type(query).__name__}"
            )
        conn = _validate_connection(connection)
        if not conn.graph_path.is_file():
            raise AdapterError(
                f"adapter-failure: graph file not found: {conn.graph_path} — graphify "
                "reads <client-checkout>/graphify-out/graph.json BY PATH (rule 1); an "
                "absent graph is a typed error, never a silent empty"
            )
        env = self._env()
        commit, as_of = self._graph_provenance(conn.graph_path, env)
        outcome = self._invoke(self._query_argv(conn=conn, query=query), env)
        if outcome.returncode != 0:
            stderr_lines = [line for line in outcome.stderr.splitlines() if line.strip()]
            message = stderr_lines[0].strip() if stderr_lines else f"exit {outcome.returncode}"
            raise AdapterError(
                f"adapter-failure: graphify query failed (exit {outcome.returncode}): {message}"
            )
        parsed = parse_query_output(outcome.stdout)
        return GroundingResult(facts=self._facts(parsed, as_of=as_of), built_at_commit=commit)
