"""Hermetic DR-3 R1 outline-brief ablation test (build step, DR-3 R1).

Proves the `scripts/dr3_outline_ablation.py` harness + its directional metric WORK -- WITHOUT
any live subscription call. The compose transport is a FAKE `Runner` returned in-process (a
`ProcessOutcome`, NO child `claude` spawned, NO `ANTHROPIC_API_KEY`, NO spend); grounding rides
a `MockAdapter` over a synthetic pool. The world is built entirely in a tmp dir (real framework
registries + a tmp workspace), so it reads NO real client graph and passes
`scripts/check-no-content.sh`.

The fake writer returns text that FOLLOWS the outline for V1 (the prompt carrying the DR-3
`Drive brief` block) and GENERIC text for V0 -- so the metric MUST compute V1 struct/content >
V0. It also asserts the identity sanity check (V1 id != V0 id; V0 is the outline-less 4-key id;
V1 rides the outline-digest). That is what makes the LIVE run the main session drives afterward
trustworthy: the harness is proven correct here first.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from pipeline.adapters.base import TIER_EXTRACTED, Anchor, Fact
from pipeline.adapters.mock import MockAdapter
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.outline import normalize_outline, outline_digest
from pipeline.transport import ProcessOutcome, ProcessRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = REPO_ROOT / "scripts" / "dr3_outline_ablation.py"

WS = "dr3-ablation"
USER = "acme"
NOW = date(2026, 7, 7)
TOPIC_ID = "x-architecture"

_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
_TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
_SOURCE = (
    "---\n"
    "id: {sid}\n"
    "provenance: instance\n"
    "schema_version: 1\n"
    "adapter: mock\n"
    "connection:\n"
    "  dataset: {ds}\n"
    "content_kind: general\n"
    "trusted: 4\n"
    "independence: first-party\n"
    "primariness: primary\n"
    "---\n\nSynthetic mock source.\n"
)

#: A hand-authored outline: 4 headings + point keywords the V1 fake body echoes and the V0 does
#: not. Distinct keywords per point so the content metric cleanly separates V1 from V0.
OUTLINE = (
    "# Architecture overview\n\n"
    "## What it is\n"
    "- a concise definition of the system\n"
    "- the primary responsibility\n\n"
    "## How it is arranged\n"
    "- the major components and their boundaries\n"
    "- how a request flows between them\n\n"
    "## Why it is shaped this way\n"
    "- the constraints that drove the design\n"
    "- the tradeoffs accepted\n"
)

#: V1 fake body -- FOLLOWS the outline: the exact headings, and the point keywords in prose.
_V1_BODY = (
    "# Architecture overview\n\n"
    "## What it is\n\n"
    "A concise definition of the system and its primary responsibility.\n\n"
    "## How it is arranged\n\n"
    "The major components and their boundaries, and how a request flows between them.\n\n"
    "## Why it is shaped this way\n\n"
    "The constraints that drove the design and the tradeoffs accepted.\n"
)
#: V0 fake body -- GENERIC short-opinion prose: no outline headings, none of its keywords.
_V0_BODY = (
    "Hook: a sharp observation earns the read. The point, stated plainly: it matters. "
    "Evidence: measurements back the claim. Takeaway: reconsider your prior assumptions.\n"
)


def _load_harness():
    spec = importlib.util.spec_from_file_location("dr3_outline_ablation", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclass string-annotation resolution needs it
    spec.loader.exec_module(module)
    return module


harness = _load_harness()


def build_world(tmp_path: Path) -> Path:
    """A full framework root (real registries) + a tmp workspace with a synthetic mock source."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2, encoding="utf-8")
    topics = root / "users" / USER / "workspaces" / WS / "topics"
    topics.mkdir(parents=True)
    (topics / f"{TOPIC_ID}.md").write_text(
        _TOPIC.format(tid=TOPIC_ID, why="Architecture."), encoding="utf-8"
    )
    sources = root / "users" / USER / "workspaces" / WS / "sources"
    sources.mkdir(parents=True)
    (sources / "x-arch-src.md").write_text(
        _SOURCE.format(sid="x-arch-src", ds="arch"), encoding="utf-8"
    )
    return root


def _adapters() -> dict:
    """A mock pool of EXTRACTED facts that match the humanized `architecture` query."""
    facts = (
        Fact(
            subject="architecture.layers",
            claim="The architecture is arranged in three layers.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("file-line", "docs/arch.md:1"),),
            as_of=date(2026, 5, 1),
        ),
        Fact(
            subject="architecture.components",
            claim="The architecture separates ingest and serving components.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("file-line", "docs/arch.md:9"),),
            as_of=date(2026, 5, 1),
        ),
    )
    return {"mock": MockAdapter({"arch": facts})}


def _envelope(text: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": text,
            "session_id": "s",
            "uuid": "u",
        }
    )


def _ok(text: str) -> ProcessOutcome:
    return ProcessOutcome(timed_out=False, returncode=0, stdout=_envelope(text), stderr="")


class AblationRunner:
    """The INJECTED fake writer transport: V1 (the prompt carries the DR-3 `## Drive brief` block)
    -> outline-following text; V0 -> generic text. Records every request (no live call proof)."""

    def __init__(self) -> None:
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        follows = "## Drive brief" in request.stdin_text
        return _ok(json.dumps({"body": _V1_BODY if follows else _V0_BODY}))


def _run(tmp_path: Path):
    root = build_world(tmp_path)
    runner = AblationRunner()
    result = harness.run_ablation(
        root=root,
        user=USER,
        workspace=WS,
        outline_md=OUTLINE,
        topic=TOPIC_ID,
        now=NOW,
        model="fake-model",
        adapters=_adapters(),
        runner=runner,
    )
    return result, runner


# ---------------------------------------------------------------------------
# The harness works: the metric shows V1 > V0, with NO live call.
# ---------------------------------------------------------------------------


def test_metric_shows_v1_follows_outline_more_than_v0(tmp_path):
    result, runner = _run(tmp_path)

    # NO live call: only the injected fake ran -- and it ran for BOTH composes.
    assert len(runner.requests) == 2, "exactly two composes (V0 + V1), no live subprocess"

    # The metric computes V1 > V0 on BOTH axes -- the harness + metric WORK.
    assert result.v1_struct > result.v0_struct
    assert result.v1_content > result.v0_content
    assert result.v1_wins is True
    # And the fake bodies land at the metric's poles (V0 realizes nothing structurally).
    assert result.v0_struct == 0.0
    assert result.v1_struct == 1.0


def test_identity_sanity_v0_is_outline_less_and_v1_rides_the_digest(tmp_path):
    result, _runner = _run(tmp_path)

    # Distinct ids; V0 is the outline-less 4-key id; V1 rides the outline-digest (Commit 6).
    assert result.v0_id != result.v1_id
    assert result.v0_outline_absent is True
    assert result.v1_rides_digest is True
    assert "outline-digest" not in result.v0_preimage
    assert result.v1_preimage["outline-digest"] == outline_digest(OUTLINE)
    assert result.outline_digest == outline_digest(OUTLINE)


def test_the_outline_brief_actually_rode_the_v1_prompt_only(tmp_path):
    _result, runner = _run(tmp_path)

    v0_prompt = next(r.stdin_text for r in runner.requests if "## Drive brief" not in r.stdin_text)
    v1_prompt = next(r.stdin_text for r in runner.requests if "## Drive brief" in r.stdin_text)
    # The normalized outline rode the V1 (drive) prompt only -- V0's prompt is outline-free.
    assert normalize_outline(OUTLINE) in v1_prompt
    assert normalize_outline(OUTLINE) not in v0_prompt


def test_grounding_is_shared_once_and_publishes_extracted_facts(tmp_path):
    result, _runner = _run(tmp_path)
    assert result.published_fact_count >= 1
    assert result.survivor_instances == ["x-arch-src"]
    assert result.query == "architecture"  # the driver's humanized topic-id query


# ---------------------------------------------------------------------------
# The metric functions in isolation (transparent + defensible, no compose).
# ---------------------------------------------------------------------------


def test_structure_fidelity_rewards_presence_and_order():
    outline_headings = ["What it is", "How it is arranged", "Why it is shaped this way"]
    # Same headings, in order -> full structure fidelity.
    ordered = ["What it is", "How it is arranged", "Why it is shaped this way"]
    fidelity, matched, total = harness.structure_fidelity(
        outline_headings, harness.output_headings("")
    )
    assert (fidelity, matched, total) == (0.0, 0, 3)  # no output headings -> 0
    fidelity, matched, total = harness.structure_fidelity(outline_headings, ordered)
    assert (fidelity, matched, total) == (1.0, 3, 3)
    # Out of order -> the greedy in-order walk cannot match all three.
    shuffled = ["Why it is shaped this way", "What it is", "How it is arranged"]
    fidelity, matched, _ = harness.structure_fidelity(outline_headings, shuffled)
    assert matched < 3 and fidelity < 1.0


def test_content_fidelity_is_whole_word_keyword_coverage():
    points = ["a concise definition of the system", "the primary responsibility"]
    # keywords: concise, definition, system, primary, responsibility
    full = "A concise definition of the system and the primary responsibility."
    fidelity, present, total = harness.content_fidelity(points, full)
    assert (present, total) == (5, 5) and fidelity == 1.0
    none = "An unrelated remark about weather and travel."
    fidelity, present, _ = harness.content_fidelity(points, none)
    assert present == 0 and fidelity == 0.0
