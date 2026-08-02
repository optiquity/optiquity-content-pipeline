"""Step-18 tests — `pipeline/adapters/graphify.py`, the REAL graphify adapter.

Covers: connection validation over the CLOSED key set (incl. the repo-workspaces
boundary refusal — rule 1/2 structural); the subprocess invocation contract (question
positional-first, `--graph` absolute, `--budget` explicit, env carries the querylog
kill switch, forbidden write verbs structurally unreachable); stdout parsing on
RECORDED synthetic transcripts (every tier tag, every anchor shape, context-suffixed
brackets, truncation marker, the no-match body, malformed lines LOUD); fact mapping
(edges carry claims, nodes contribute anchors, SM9 anchorless facts, dedupe, G6 no
`review_status` refinement); `built_at_commit` from graph.json with the read-only git
fallback; the typed error surface (absent binary / absent graph / nonzero exit — never
silent empties); byte-level read-only behavior; and resolver integration (commit-map,
review-status degradation, publish floor — fixture-driven parity with the step-17 mock
contract).

Fixtures are SYNTHETIC-GENERIC (CLAUDE.md rule 4): the in-repo
`tests/fixtures/adapters/graphify/graph.json` is an invented widget/gadget graph;
`RECORDED_TRANSCRIPT` was recorded 2026-07-12 by running graphify 0.8.39 against that
fixture — never a copy of any client graph. Tests that touch the machine-local REAL
demo graphs (read-only, per the step-18 spawn spec) are marked `live` and deselected
by the default run (pyproject `addopts`, PA-5); they assert SHAPE only — no client
content value ever appears in this repo.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shutil
from pathlib import Path

import pytest

from pipeline.adapters.base import (
    ANCHOR_KINDS,
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    TIER_INFERRED,
    TIERS,
    AdapterError,
    Anchor,
    GroundingResult,
    SourceAdapter,
)
from pipeline.adapters.graphify import (
    CANONICAL_CONTEXTS,
    CONNECTION_KEYS,
    DEFAULT_BINARY,
    DEFAULT_BUDGET,
    FORBIDDEN_SUBCOMMANDS,
    NO_MATCH_BODY,
    QUERY_LOG_DISABLE_ENV,
    QUERY_SUBCOMMAND,
    REPO_USERS,
    GraphifyAdapter,
    RunOutcome,
    parse_query_output,
)
from pipeline.grounding import SourceInstance, ground_item
from pipeline.m3 import resolve_selection

NOW = datetime.date(2026, 7, 12)

FIXTURE_GRAPH = (
    Path(__file__).parent / "fixtures" / "adapters" / "graphify" / "graph.json"
).resolve()
FIXTURE_COMMIT = "1111111111222222222233333333334444444444"

#: Recorded 2026-07-12: `graphify query "widget" --graph <fixture graph.json>
#: --budget 2000` (graphify 0.8.39) — synthetic content, real grammar. Covers all
#: three tier tags, a context-suffixed bracket, `src=None`, `loc=None`, a `lines A-B`
#: loc, and a URL src.
RECORDED_TRANSCRIPT = """\
Traversal: BFS depth=2 | Start: ['Widget service configuration'] | 4 nodes found

NODE Gadget cache sizing note [src=notes/gadget-sizing.md loc=lines 3-9 community=1]
NODE Widget service configuration [src=src/widget/config.py loc=L42 community=1]
NODE Timeout review thread [src=https://example.test/review#timeout loc=None community=2]
NODE Anchorless roadmap idea [src=None loc=None community=2]
EDGE Widget service configuration --references [EXTRACTED context=call]--> Gadget cache sizing note
EDGE Widget service configuration --rationale_for [AMBIGUOUS]--> Anchorless roadmap idea
EDGE Gadget cache sizing note --conceptually_related_to [INFERRED]--> Timeout review thread
"""

#: Recorded 2026-07-12 (same tool, `--budget 800` against the real optiquity-site
#: graph — line shape only, no client text): the in-band budget-cut marker.
TRUNCATION_LINE = (
    "... (truncated — 16 more nodes cut by ~800-token budget. Narrow with "
    "context_filter=['call'] or use get_node for a specific symbol)"
)

# The machine-local REAL graphs (step-18 spawn spec; read-only, `live`-marked below).
# Bindings are ENV-SOURCED so no instance-specific path ever rides the framework file
# (rules 4/5): set both vars to run the live battery on any machine.
DEMO_GRAPH_ENV = "PIPELINE_LIVE_DEMO_GRAPH"
TIER_GRAPH_ENV = "PIPELINE_LIVE_TIER_GRAPH"
_demo = os.environ.get(DEMO_GRAPH_ENV, "")
_tier = os.environ.get(TIER_GRAPH_ENV, "")
DEMO_GRAPH = Path(_demo) if _demo else None
TIER_COVERAGE_GRAPH = Path(_tier) if _tier else None


class FakeRunner:
    """A recording process seam: scripted outcomes per executable, zero subprocesses.

    `graphify`/`git` take a `RunOutcome`, an exception instance to raise, or (git)
    None = the binary is absent (`FileNotFoundError`).
    """

    def __init__(self, *, graphify=None, git=None):
        self.calls: list[tuple[list[str], dict[str, str]]] = []
        self._graphify = (
            graphify if graphify is not None else RunOutcome(0, RECORDED_TRANSCRIPT, "")
        )
        self._git = git

    def __call__(self, argv, env) -> RunOutcome:
        argv = list(argv)
        self.calls.append((argv, dict(env)))
        if argv[0] == "git":
            if isinstance(self._git, BaseException):
                raise self._git
            if self._git is None:
                raise FileNotFoundError("git")
            return self._git
        if isinstance(self._graphify, BaseException):
            raise self._graphify
        return self._graphify

    @property
    def graphify_calls(self) -> list[tuple[list[str], dict[str, str]]]:
        return [(argv, env) for argv, env in self.calls if argv[0] != "git"]


def adapter_with(runner: FakeRunner | None = None) -> tuple[GraphifyAdapter, FakeRunner]:
    fake = runner if runner is not None else FakeRunner()
    return GraphifyAdapter(run=fake), fake


def conn(**overrides) -> dict:
    connection = {"path": str(FIXTURE_GRAPH)}
    connection.update(overrides)
    return connection


def write_graph(tmp_path: Path, document: dict | str, name: str = "graph.json") -> Path:
    path = tmp_path / name
    text = document if isinstance(document, str) else json.dumps(document)
    path.write_text(text, encoding="utf-8")
    return path


# --- connection validation (closed keys; rule-1/2 boundary) ----------------------------------


class TestConnectionValidation:
    def test_non_mapping_connection_refused(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="must be a mapping"):
            adapter.ground(connection=[("path", str(FIXTURE_GRAPH))], query="q")

    def test_unknown_key_refused_closed_set(self):
        adapter, fake = adapter_with()
        with pytest.raises(AdapterError, match="CLOSED"):
            adapter.ground(connection=conn(subcommand="extract"), query="q")
        assert fake.calls == []  # refused before any process spawn

    def test_binary_is_wiring_not_connection_config(self):
        # The executable can never be chosen by connection data (module docstring).
        assert "binary" not in CONNECTION_KEYS
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="CLOSED"):
            adapter.ground(connection=conn(binary="evil-tool"), query="q")

    @pytest.mark.parametrize("bad", [None, "", "   ", 7])
    def test_missing_or_empty_path_refused(self, bad):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="requires `path`"):
            adapter.ground(connection={"path": bad}, query="q")

    def test_relative_path_refused(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="ABSOLUTE"):
            adapter.ground(connection={"path": "graphify-out/graph.json"}, query="q")

    def test_non_json_path_refused(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match=r"\.json"):
            adapter.ground(connection={"path": "/somewhere/graph.yaml"}, query="q")

    def test_path_inside_repo_users_refused(self):
        # Plan step 18 / §23: grounding sources live OUTSIDE this repo's users/ client tree.
        inside = REPO_USERS / "some-user" / "workspaces" / "some-client" / "graphify-out" / "g.json"
        adapter, fake = adapter_with()
        with pytest.raises(AdapterError, match="users"):
            adapter.ground(connection={"path": str(inside)}, query="q")
        assert fake.calls == []

    @pytest.mark.parametrize("bad", [True, 0, -5, "2000", 2.5])
    def test_bad_budget_refused(self, bad):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="budget"):
            adapter.ground(connection=conn(budget=bad), query="q")

    @pytest.mark.parametrize("bad", ["call", 7, {"call": True}])
    def test_context_must_be_a_sequence(self, bad):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="context"):
            adapter.ground(connection=conn(context=bad), query="q")

    def test_non_canonical_context_value_refused(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="canonical"):
            adapter.ground(connection=conn(context=["calls"]), query="q")

    def test_bad_dfs_refused(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="dfs"):
            adapter.ground(connection=conn(dfs=1), query="q")

    def test_query_must_be_a_string(self):
        adapter, _ = adapter_with()
        with pytest.raises(AdapterError, match="query must be a string"):
            adapter.ground(connection=conn(), query=None)

    def test_bad_binary_wiring_refused(self):
        with pytest.raises(AdapterError, match="binary"):
            GraphifyAdapter(binary="  ")


# --- subprocess invocation contract (step-05 report §6) --------------------------------------


class TestInvocationContract:
    def test_argv_question_positional_first_then_flags(self):
        adapter, fake = adapter_with()
        adapter.ground(connection=conn(), query="widget timeout behavior")
        [(argv, _)] = fake.graphify_calls
        assert argv == [
            DEFAULT_BINARY,
            QUERY_SUBCOMMAND,
            "widget timeout behavior",  # argv[2]: positional, BEFORE every flag
            "--graph",
            str(FIXTURE_GRAPH),
            "--budget",
            str(DEFAULT_BUDGET),
        ]

    def test_argv_reflects_budget_context_dfs(self):
        adapter, fake = adapter_with()
        adapter.ground(
            connection=conn(budget=500, context=["call", "import"], dfs=True), query="q"
        )
        [(argv, _)] = fake.graphify_calls
        assert argv[1] == QUERY_SUBCOMMAND
        assert argv[2] == "q"
        assert argv[argv.index("--budget") + 1] == "500"
        assert argv.count("--context") == 2
        assert argv[argv.index("--context") + 1] == "call"
        assert "--dfs" in argv

    def test_env_carries_querylog_kill_switch_and_ambient(self):
        before = dict(os.environ)
        adapter, fake = adapter_with()
        adapter.ground(connection=conn(), query="q")
        [(_, env)] = fake.graphify_calls
        assert env[QUERY_LOG_DISABLE_ENV] == "1"  # step-05 §3.5: the ONLY side effect, off
        assert env.get("PATH") == before.get("PATH")  # ambient env rides along
        assert dict(os.environ) == before  # the process env itself is never mutated

    def test_forbidden_subcommands_structurally_unreachable(self):
        # The rule-1 write verbs (step-05 §6) are data here, never reachable code.
        assert QUERY_SUBCOMMAND == "query"
        assert QUERY_SUBCOMMAND not in FORBIDDEN_SUBCOMMANDS
        assert {"save-result", "extract", "export", "merge-graphs"} <= FORBIDDEN_SUBCOMMANDS
        adapter, fake = adapter_with()
        # Adversarial QUERIES ride argv[2] as data — the verb slot stays "query".
        for hostile in ("extract", "save-result --graph /x", "--dfs", "hook install"):
            adapter.ground(connection=conn(), query=hostile)
        for argv, _ in fake.graphify_calls:
            assert argv[1] == QUERY_SUBCOMMAND
            assert argv[2] in ("extract", "save-result --graph /x", "--dfs", "hook install")
            assert not FORBIDDEN_SUBCOMMANDS.intersection({argv[1]})

    def test_module_source_has_no_write_primitives(self):
        # Rule 1 structural: the adapter module cannot write — no write primitive
        # appears anywhere in its source (reads via read_text; subprocesses are
        # `graphify query` and `git rev-parse` only).
        import pipeline.adapters.graphify as module

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
            assert token not in source, f"write primitive {token!r} found in graphify adapter"

    def test_contract_shape(self):
        assert issubclass(GraphifyAdapter, SourceAdapter)
        assert GraphifyAdapter.name == "graphify"
        assert GraphifyAdapter.capabilities == frozenset({"query"})


# --- stdout parsing on recorded synthetic transcripts ----------------------------------------


class TestStdoutParsing:
    def test_recorded_transcript_parses_every_tier_and_anchor_shape(self):
        parsed = parse_query_output(RECORDED_TRANSCRIPT)
        assert not parsed.no_match and not parsed.truncated
        assert len(parsed.nodes) == 4
        assert {edge.tier for edge in parsed.edges} == set(TIERS)  # all three tags
        by_label = {node.label: node for node in parsed.nodes}
        assert by_label["Gadget cache sizing note"].loc == "lines 3-9"  # range loc
        assert by_label["Widget service configuration"].loc == "L42"  # line loc
        assert by_label["Timeout review thread"].src.startswith("https://")  # URL src
        assert by_label["Timeout review thread"].loc is None  # printed None
        assert by_label["Anchorless roadmap idea"].src is None  # printed None

    def test_context_suffix_inside_bracket_parses(self):
        parsed = parse_query_output(RECORDED_TRANSCRIPT)
        extracted = [edge for edge in parsed.edges if edge.tier == TIER_EXTRACTED]
        assert [edge.relation for edge in extracted] == ["references"]
        assert extracted[0].target == "Gadget cache sizing note"

    def test_truncation_marker_recognized(self):
        parsed = parse_query_output(RECORDED_TRANSCRIPT + TRUNCATION_LINE + "\n")
        assert parsed.truncated is True
        assert len(parsed.edges) == 3  # marker is metadata, not a fact

    def test_no_match_body_is_a_legit_empty(self):
        parsed = parse_query_output(NO_MATCH_BODY + "\n")
        assert parsed.no_match is True
        assert parsed.nodes == () and parsed.edges == ()

    def test_no_match_with_trailing_garbage_is_loud(self):
        with pytest.raises(AdapterError, match="after the no-match body"):
            parse_query_output(NO_MATCH_BODY + "\nNODE x [src=a loc=b community=1]\n")

    def test_empty_stdout_is_loud(self):
        with pytest.raises(AdapterError, match="printed nothing"):
            parse_query_output("\n\n")

    def test_unrecognized_header_is_loud(self):
        with pytest.raises(AdapterError, match="unrecognized graphify header"):
            parse_query_output("Something completely different\n")

    def test_header_with_context_part_parses(self):
        header = "Traversal: DFS depth=2 | Start: ['x'] | Context: call (auto) | 1 nodes found"
        parsed = parse_query_output(header + "\n\nNODE x [src=None loc=None community=1]\n")
        assert len(parsed.nodes) == 1

    def test_malformed_node_line_is_loud(self):
        with pytest.raises(AdapterError, match="malformed NODE line"):
            parse_query_output(
                RECORDED_TRANSCRIPT.splitlines()[0] + "\n\nNODE broken without bracket\n"
            )

    def test_malformed_edge_line_is_loud(self):
        with pytest.raises(AdapterError, match="malformed EDGE line"):
            parse_query_output(
                RECORDED_TRANSCRIPT.splitlines()[0] + "\n\nEDGE a ---> b\n"
            )

    def test_unknown_tier_tag_is_loud(self):
        with pytest.raises(AdapterError, match="unknown confidence tier 'PROVEN'"):
            parse_query_output(
                RECORDED_TRANSCRIPT.splitlines()[0] + "\n\nEDGE a --references [PROVEN]--> b\n"
            )

    def test_unrecognized_line_kind_is_loud_never_skipped(self):
        with pytest.raises(AdapterError, match="unrecognized graphify output line"):
            parse_query_output(
                RECORDED_TRANSCRIPT.splitlines()[0] + "\n\nHYPEREDGE a b c\n"
            )

    def test_non_string_stdout_is_loud(self):
        with pytest.raises(AdapterError, match="stdout must be text"):
            parse_query_output(None)


# --- fact mapping (edges = claims, nodes = anchors; G6; SM9) ----------------------------------


class TestFactMapping:
    def ground(self) -> GroundingResult:
        adapter, _ = adapter_with()
        return adapter.ground(connection=conn(), query="widget")

    def test_edges_become_facts_with_canonical_subject_claim(self):
        result = self.ground()
        assert len(result.facts) == 3
        extracted = next(f for f in result.facts if f.tier == TIER_EXTRACTED)
        assert (
            extracted.claim
            == "Widget service configuration --references--> Gadget cache sizing note"
        )
        # A graph edge addresses ITSELF (multi-valued-relation ruling, module docstring):
        assert extracted.subject == extracted.claim

    def test_multi_valued_relations_are_not_conflicts(self):
        # Regression (observed live): one node referencing MANY targets must never
        # read as a §6.3 conflict — the default downgrade-AMBIGUOUS strategy would
        # silently gut valid EXTRACTED facts otherwise (§3.1 no-overstep).
        stdout = (
            "Traversal: BFS depth=2 | Start: ['Hub doc'] | 3 nodes found\n\n"
            "NODE Hub doc [src=docs/hub.md loc=None community=1]\n"
            "NODE Spoke one [src=docs/one.md loc=None community=1]\n"
            "NODE Spoke two [src=docs/two.md loc=None community=1]\n"
            "EDGE Hub doc --references [EXTRACTED]--> Spoke one\n"
            "EDGE Hub doc --references [EXTRACTED]--> Spoke two\n"
        )
        adapter, _ = adapter_with(FakeRunner(graphify=RunOutcome(0, stdout, "")))
        outcome = ground_item(
            item="fanout",
            query="hub",
            pool=[
                SourceInstance(
                    id="x-fanout-graph",
                    adapter="graphify",
                    connection={"path": str(FIXTURE_GRAPH)},
                )
            ],
            selection=resolve_selection(),
            adapters={"graphify": adapter},
            now=NOW,
        )
        assert outcome.status == "ok"
        assert len(outcome.facts) == 2
        assert {fact.tier for fact in outcome.facts} == {TIER_EXTRACTED}  # NOT downgraded
        assert all(fact.conflict is None for fact in outcome.facts)

    def test_endpoint_nodes_contribute_anchors(self):
        result = self.ground()
        extracted = next(f for f in result.facts if f.tier == TIER_EXTRACTED)
        assert extracted.anchors == (
            Anchor("file-line", "src/widget/config.py:L42"),
            Anchor("file-line", "notes/gadget-sizing.md:lines 3-9"),
        )
        inferred = next(f for f in result.facts if f.tier == TIER_INFERRED)
        assert Anchor("url-fragment", "https://example.test/review#timeout") in inferred.anchors

    def test_anchorless_endpoint_yields_partial_anchors(self):
        result = self.ground()
        ambiguous = next(f for f in result.facts if f.tier == TIER_AMBIGUOUS)
        # Target node printed src=None — only the source endpoint anchors the fact.
        assert ambiguous.anchors == (Anchor("file-line", "src/widget/config.py:L42"),)

    def test_fully_anchorless_fact_is_legal_sm9(self):
        # SM9 (§6.5): tier ⟂ traceability — EXTRACTED yet anchor-less parses fine.
        stdout = (
            "Traversal: BFS depth=2 | Start: ['Alpha idea'] | 2 nodes found\n\n"
            "NODE Alpha idea [src=None loc=None community=1]\n"
            "NODE Beta idea [src=None loc=None community=1]\n"
            "EDGE Alpha idea --references [EXTRACTED]--> Beta idea\n"
        )
        adapter, _ = adapter_with(FakeRunner(graphify=RunOutcome(0, stdout, "")))
        result = adapter.ground(connection=conn(), query="alpha")
        [fact] = result.facts
        assert fact.tier == TIER_EXTRACTED and fact.anchors == ()

    def test_duplicate_edge_lines_dedupe_to_one_fact(self):
        line = "EDGE Alpha idea --references [EXTRACTED]--> Beta idea\n"
        stdout = (
            "Traversal: BFS depth=2 | Start: ['Alpha idea'] | 2 nodes found\n\n"
            "NODE Alpha idea [src=None loc=None community=1]\n"
            "NODE Beta idea [src=None loc=None community=1]\n" + line + line
        )
        adapter, _ = adapter_with(FakeRunner(graphify=RunOutcome(0, stdout, "")))
        result = adapter.ground(connection=conn(), query="alpha")
        assert len(result.facts) == 1

    def test_as_of_is_the_graph_mtime_date(self):
        result = self.ground()
        expected = datetime.date.fromtimestamp(FIXTURE_GRAPH.stat().st_mtime)
        assert {fact.as_of for fact in result.facts} == {expected}

    def test_g6_no_review_status_refinement_ever(self):
        # Gate G6 CLOSED (step-05 §5): graphify persists no review metadata, so the
        # adapter refines NOTHING — the content-kind default rides down to `unknown`.
        result = self.ground()
        assert all(fact.refinements == {} for fact in result.facts)

    def test_no_match_grounds_an_empty_result_not_an_error(self):
        adapter, _ = adapter_with(FakeRunner(graphify=RunOutcome(0, NO_MATCH_BODY + "\n", "")))
        result = adapter.ground(connection=conn(), query="zzz")
        assert result.facts == ()
        assert result.built_at_commit == FIXTURE_COMMIT  # provenance still real


# --- built_at_commit provenance (graph.json → read-only git fallback → None) ------------------


class TestCommitProvenance:
    def test_built_at_commit_read_from_graph_json(self):
        adapter, _ = adapter_with()
        result = adapter.ground(connection=conn(), query="widget")
        assert result.built_at_commit == FIXTURE_COMMIT

    def commitless_graph(self, tmp_path) -> Path:
        document = json.loads(FIXTURE_GRAPH.read_text(encoding="utf-8"))
        del document["built_at_commit"]
        return write_graph(tmp_path, document)

    def test_git_fallback_supplies_the_checkout_head(self, tmp_path):
        sha = "ab" * 20
        fake = FakeRunner(git=RunOutcome(0, sha + "\n", ""))
        adapter, _ = adapter_with(fake)
        graph = self.commitless_graph(tmp_path)
        result = adapter.ground(connection={"path": str(graph)}, query="widget")
        assert result.built_at_commit == sha
        [git_argv] = [argv for argv, _ in fake.calls if argv[0] == "git"]
        # The plan's READ-ONLY git command, exactly — never a state-changing verb.
        assert git_argv == ["git", "-C", str(graph.parent), "rev-parse", "HEAD"]

    def test_commitless_when_git_fails(self, tmp_path):
        fake = FakeRunner(git=RunOutcome(128, "", "fatal: not a git repository"))
        adapter, _ = adapter_with(fake)
        graph = self.commitless_graph(tmp_path)
        result = adapter.ground(connection={"path": str(graph)}, query="w")
        assert result.built_at_commit is None  # commitless source — the designed posture

    def test_commitless_when_git_binary_absent(self, tmp_path):
        adapter, _ = adapter_with(FakeRunner(git=None))  # git raises FileNotFoundError
        graph = self.commitless_graph(tmp_path)
        result = adapter.ground(connection={"path": str(graph)}, query="w")
        assert result.built_at_commit is None

    def test_pin_commit_agrees_with_ground_on_built_at_commit(self):
        # CF-1: `pin_commit` (the §7.2 identity commit-map value) reads the SAME provenance
        # `ground()` reports, so identity and the §15 ledger never disagree.
        adapter, _ = adapter_with()
        pinned = adapter.pin_commit(conn())
        grounded = adapter.ground(connection=conn(), query="widget").built_at_commit
        assert pinned == grounded == FIXTURE_COMMIT

    def test_pin_commit_agrees_with_ground_via_git_fallback(self, tmp_path):
        # CF-1's core case: a commitless-but-git checkout. `pin_commit` MUST also hit the
        # read-only git fallback — otherwise identity would OMIT the commit the grounding
        # ledger records (the latent divergence generate-next activates).
        sha = "cd" * 20
        graph = self.commitless_graph(tmp_path)
        pin_fake = FakeRunner(git=RunOutcome(0, sha + "\n", ""))
        pin_adapter, _ = adapter_with(pin_fake)
        pinned = pin_adapter.pin_commit({"path": str(graph)})
        ground_fake = FakeRunner(git=RunOutcome(0, sha + "\n", ""))
        ground_adapter, _ = adapter_with(ground_fake)
        grounded = ground_adapter.ground(connection={"path": str(graph)}, query="w").built_at_commit
        assert pinned == sha == grounded  # no divergence

    def test_pin_commit_absent_graph_is_none(self, tmp_path):
        # An absent graph pins nothing (grounding then fails loudly — no diverged id persists).
        adapter, _ = adapter_with()
        assert adapter.pin_commit({"path": str(tmp_path / "missing.json")}) is None


# --- typed error surface (never silent empties) -----------------------------------------------


class TestErrorSurface:
    def test_absent_binary_is_a_typed_error(self):
        fake = FakeRunner(graphify=FileNotFoundError("graphify"))
        adapter, _ = adapter_with(fake)
        with pytest.raises(AdapterError, match="executable not found: 'graphify'"):
            adapter.ground(connection=conn(), query="q")

    def test_absent_graph_is_typed_and_spawns_nothing(self, tmp_path):
        adapter, fake = adapter_with()
        missing = tmp_path / "graphify-out" / "graph.json"
        with pytest.raises(AdapterError, match="graph file not found"):
            adapter.ground(connection={"path": str(missing)}, query="q")
        assert fake.calls == []  # no subprocess, no silent empty

    def test_nonzero_exit_maps_stderr_first_line(self):
        fake = FakeRunner(
            graphify=RunOutcome(1, "", "error: graph file not found: /x\nsecond line")
        )
        adapter, _ = adapter_with(fake)
        with pytest.raises(AdapterError, match=r"exit 1.*error: graph file not found"):
            adapter.ground(connection=conn(), query="q")

    def test_nonzero_exit_with_empty_stderr_still_typed(self):
        adapter, _ = adapter_with(FakeRunner(graphify=RunOutcome(3, "", "")))
        with pytest.raises(AdapterError, match="exit 3"):
            adapter.ground(connection=conn(), query="q")

    def test_damaged_graph_json_is_loud(self, tmp_path):
        adapter, _ = adapter_with()
        graph = write_graph(tmp_path, "this is not json {")
        with pytest.raises(AdapterError, match="not valid JSON"):
            adapter.ground(connection={"path": str(graph)}, query="q")

    def test_non_object_graph_json_is_loud(self, tmp_path):
        adapter, _ = adapter_with()
        graph = write_graph(tmp_path, "[1, 2, 3]")
        with pytest.raises(AdapterError, match="JSON object"):
            adapter.ground(connection={"path": str(graph)}, query="q")


# --- rule 1: zero write syscalls toward the source --------------------------------------------


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class TestReadOnly:
    def test_ground_leaves_the_source_dir_byte_identical(self, tmp_path):
        source = tmp_path / "client-checkout" / "graphify-out"
        source.mkdir(parents=True)
        shutil.copyfile(FIXTURE_GRAPH, source / "graph.json")
        (source / "GRAPH_REPORT.md").write_text("synthetic sibling\n", encoding="utf-8")
        before = snapshot(tmp_path)
        adapter, _ = adapter_with()
        adapter.ground(connection={"path": str(source / "graph.json")}, query="widget")
        assert snapshot(tmp_path) == before  # zero writes toward the source, ever


# --- resolver integration: parity with the mock contract (plan step-18 acceptance) ------------


class TestResolverIntegration:
    def outcome(self, instance: SourceInstance | None = None):
        pool = [
            instance
            if instance is not None
            else SourceInstance(
                id="x-demo-graph",
                adapter="graphify",
                connection={"path": str(FIXTURE_GRAPH)},
            )
        ]
        adapter, _ = adapter_with()
        return ground_item(
            item="item-1",
            query="widget",
            pool=pool,
            selection=resolve_selection(),
            adapters={"graphify": adapter},
            now=NOW,
        )

    def test_built_at_commit_surfaces_into_the_commit_map(self):
        outcome = self.outcome()
        assert outcome.status == "ok"
        assert dict(outcome.commit_map) == {"x-demo-graph": FIXTURE_COMMIT}
        assert {fact.commit for fact in outcome.facts} == {FIXTURE_COMMIT}
        assert {fact.adapter for fact in outcome.facts} == {"graphify"}

    def test_review_status_degrades_to_unknown_through_the_kind_chain(self):
        # G6: no refinement from the adapter + no kind bundle ⇒ the schema floor.
        outcome = self.outcome()
        assert {fact.scores["review_status"] for fact in outcome.facts} == {"unknown"}

    def test_adapter_never_clobbers_a_kind_characterization(self):
        # The no-overstep half of G6 (§3.1): a user's `merged-code: reviewed` kind
        # default SURVIVES grounding, because the adapter refines nothing.
        instance = SourceInstance(
            id="x-merged-code-graph",
            adapter="graphify",
            connection={"path": str(FIXTURE_GRAPH)},
            content_kind="merged-code",
            kind_defaults={"review_status": "reviewed", "authoritative": 4, "opinionated": 1},
        )
        outcome = self.outcome(instance)
        assert {fact.scores["review_status"] for fact in outcome.facts} == {"reviewed"}

    def test_publish_floor_holds_over_real_adapter_facts(self):
        outcome = self.outcome()
        assert {fact.tier for fact in outcome.facts} == set(TIERS)
        assert all(fact.publishable for fact in outcome.publishable_facts)
        assert {fact.tier for fact in outcome.publishable_facts} == {TIER_EXTRACTED}
        assert {fact.tier for fact in outcome.leads} == {TIER_INFERRED, TIER_AMBIGUOUS}


# --- live smoke (machine-local real graphs + real binary; read-only; SHAPE ONLY) --------------

needs_demo_graph = pytest.mark.skipif(
    DEMO_GRAPH is None or not DEMO_GRAPH.is_file() or shutil.which("graphify") is None,
    reason=f"set {DEMO_GRAPH_ENV} to a machine-local demo graph (+ graphify on PATH)",
)
needs_tier_graph = pytest.mark.skipif(
    TIER_COVERAGE_GRAPH is None or not TIER_COVERAGE_GRAPH.is_file(),
    reason=f"set {TIER_GRAPH_ENV} to a machine-local tier-coverage graph",
)
needs_binary = pytest.mark.skipif(
    shutil.which("graphify") is None, reason="graphify binary absent"
)

HEX_COMMIT = re.compile(r"^[0-9a-f]{40}$")


@pytest.mark.live
@needs_binary
def test_live_real_binary_against_the_synthetic_fixture():
    """The real binary over the SYNTHETIC in-repo graph: pins the recorded grammar."""
    adapter = GraphifyAdapter()  # the real subprocess runner
    result = adapter.ground(connection=conn(), query="widget")
    assert result.built_at_commit == FIXTURE_COMMIT
    assert {fact.tier for fact in result.facts} == set(TIERS)
    claims = {fact.claim for fact in result.facts}
    assert "Widget service configuration --references--> Gadget cache sizing note" in claims


@pytest.mark.live
@needs_demo_graph
def test_live_real_query_parses_and_grounds_shape_only():
    """A real query against the designated demo graph — SHAPE assertions only (no
    client content value ever lands in this repo)."""
    adapter = GraphifyAdapter()
    result = adapter.ground(
        connection={"path": str(DEMO_GRAPH), "budget": 4000},
        query="high-level architecture and main components",
    )
    assert isinstance(result, GroundingResult)
    assert result.built_at_commit is not None and HEX_COMMIT.match(result.built_at_commit)
    assert len(result.facts) >= 1
    for fact in result.facts:
        assert fact.tier in TIERS
        assert fact.subject and fact.claim
        assert isinstance(fact.as_of, datetime.date)
        for anchor in fact.anchors:
            assert anchor.kind in ANCHOR_KINDS and anchor.value.strip()


@pytest.mark.live
@needs_demo_graph
def test_live_grounds_through_the_resolver_shape_only():
    outcome = ground_item(
        item="live-smoke",
        query="high-level architecture and main components",
        pool=[
            SourceInstance(
                id="x-live-demo",
                adapter="graphify",
                connection={"path": str(DEMO_GRAPH), "budget": 4000},
            )
        ],
        selection=resolve_selection(),
        adapters={"graphify": GraphifyAdapter()},
        now=datetime.date.today(),
    )
    assert outcome.status in ("ok", "warn")
    assert set(outcome.commit_map) == {"x-live-demo"}
    assert HEX_COMMIT.match(outcome.commit_map["x-live-demo"])
    assert all(fact.scores["review_status"] == "unknown" for fact in outcome.facts)  # G6


@pytest.mark.live
@needs_tier_graph
def test_live_tier_vocabulary_matches_the_real_graph():
    """READ-ONLY json load of the tier-coverage graph: the §6.2 tier vocabulary is
    exactly the real tool's — a shape/vocabulary assertion, no content values."""
    document = json.loads(TIER_COVERAGE_GRAPH.read_text(encoding="utf-8"))
    assert {link["confidence"] for link in document["links"]} == set(TIERS)
    assert isinstance(document["built_at_commit"], str)
    assert HEX_COMMIT.match(document["built_at_commit"])


def test_canonical_contexts_are_the_step_05_set():
    assert CANONICAL_CONTEXTS == (
        "call",
        "import",
        "field",
        "parameter_type",
        "return_type",
        "generic_arg",
        "export",
        "attribute",
    )
