#!/usr/bin/env python3
"""DR-3 R1 outline-brief ablation harness (BUILD-TIME EXPERIMENT, not shipped runtime code).

Question (DR-3, horn (a)): does the DRIVING outline brief measurably STEER composed output?
Method: for ONE content coordinate, GROUND ONCE (so V0/V1 share identical grounding) then
COMPOSE TWICE against the SAME grounded facts:

  * V0 -- `outline_brief=None`, the pre-DR-3 4-key preimage (outline-less identity).
  * V1 -- `outline_brief=<a hand-authored outline>`, the 5-key preimage carrying the
    `outline-digest` (compose's digest-fidelity guard binds the shown brief to identity).

Then a DIRECTIONAL, transparent fidelity metric asks whether V1 follows the outline MORE
than V0 (structure + content). n=1, directional -- NOT a claim of statistical proof.

This is a STANDALONE `scripts/` experiment: it is NEVER imported by `pipeline/` (it is a
consumer of the pipeline, off the INV-CORRECTNESS BFS roots). The compose transport is an
INJECTABLE seam (`runner`): `None` -> the real subscription writer (the LIVE edge the MAIN
SESSION runs); a fake `Runner` -> hermetic (`tests/test_dr3_ablation.py`, NO live spend).

Grounding rides the EXACT `pipeline.driver` helpers the live pipeline uses
(`_list_source_ids`/`_pin_source_commit`/`_source_repo_for`/`_query_for_topic`/
`_effective_values`), so what this harness grounds + composes is byte-faithful to the real
generate-next path -- that is what makes the LIVE run trustworthy.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pipeline import ir
from pipeline.adapters.graphify import GraphifyAdapter
from pipeline.cascade import CascadeEnv, RunSelection, resolve_compose
from pipeline.compose import ComposeRequest, compose_artifact
from pipeline.driver import (
    _effective_values,
    _list_source_ids,
    _pin_source_commit,
    _query_for_topic,
    _source_repo_for,
)
from pipeline.grounding import build_pool, ground_item
from pipeline.ids import mint_artifact_id
from pipeline.m3 import resolve_selection
from pipeline.outline import normalize_outline, outline_digest
from pipeline.spine import registry_for
from pipeline.store import WorkspaceStore
from pipeline.transport import Runner

__all__ = [
    "DEFAULT_OUTLINE",
    "AblationError",
    "AblationResult",
    "content_fidelity",
    "main",
    "output_headings",
    "parse_outline",
    "run_ablation",
    "structure_fidelity",
]

#: A sensible built-in outline for the `x-architecture-overview` demo topic (4-6 sections,
#: each with an authored intent). The MAIN SESSION may pass its own via `--outline-file`.
DEFAULT_OUTLINE = """# Architecture overview

## What it is
- a one-paragraph definition of the system
- the primary job it exists to do

## How it is arranged
- the major components and their boundaries
- how a request flows between them

## Why it is shaped this way
- the constraints that drove the design
- the tradeoffs deliberately accepted

## What to read next
- the narrower pieces that build on this overview
"""


class AblationError(RuntimeError):
    """A harness-level wiring/stage defect -- loud, typed, never a fabricated success."""


# ---------------------------------------------------------------------------
# The transparent, directional fidelity metric (structure + content).
# ---------------------------------------------------------------------------

#: A Markdown ATX heading line (1-6 `#`), capturing the heading text.
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
#: A Markdown bullet / ordered list item, capturing the point text.
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*\S)\s*$")
#: Lowercase alphanumeric word tokens.
_WORD_RE = re.compile(r"[a-z0-9]+")
#: A small, EXPLICIT stopword set (documented so the metric stays defensible/transparent).
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "with", "is", "are",
        "be", "by", "as", "at", "it", "its", "that", "this", "from", "into", "between",
    }
)


def _tokens(text: str) -> list[str]:
    """Significant lowercase word tokens (>= 2 chars, stopwords dropped)."""
    return [t for t in _WORD_RE.findall(text.lower()) if len(t) >= 2 and t not in _STOPWORDS]


def parse_outline(md: str) -> tuple[list[str], list[str]]:
    """Parse an outline into its (heading texts, bullet-point texts), in document order."""
    headings: list[str] = []
    points: list[str] = []
    for line in md.splitlines():
        heading = _HEADING_RE.match(line)
        if heading is not None:
            headings.append(heading.group(2).strip())
            continue
        bullet = _BULLET_RE.match(line)
        if bullet is not None:
            points.append(bullet.group(1).strip())
    return headings, points


def output_headings(text: str) -> list[str]:
    """Every ATX heading in a composed body, in order (the structure the writer emitted)."""
    out: list[str] = []
    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading is not None:
            out.append(heading.group(2).strip())
    return out


def _heading_matches(outline_h: str, output_h: str) -> bool:
    """An outline heading is REALIZED by an output heading iff the outline heading's
    significant tokens are all present in the output heading (so `Problem` matches
    `## The Problem`). Token-subset -- transparent, no fuzzy scoring."""
    outline_tokens = set(_tokens(outline_h))
    return bool(outline_tokens) and outline_tokens <= set(_tokens(output_h))


def structure_fidelity(
    outline_headings: list[str], out_headings: list[str]
) -> tuple[float, int, int]:
    """Fraction of the outline's headings realized as output headings IN THE OUTLINE'S ORDER.

    A greedy in-order walk: for each outline heading in turn, find the next (not-yet-consumed)
    output heading that realizes it. Rewards both PRESENCE and ORDER in one honest number.
    Returns (fidelity, matched, total).
    """
    total = len(outline_headings)
    if total == 0:
        return 0.0, 0, 0
    matched = 0
    cursor = 0
    for heading in outline_headings:
        for j in range(cursor, len(out_headings)):
            if _heading_matches(heading, out_headings[j]):
                matched += 1
                cursor = j + 1
                break
    return matched / total, matched, total


def content_fidelity(points: list[str], body_text: str) -> tuple[float, int, int]:
    """Fraction of the outline's point KEYWORDS present as whole words in the body.

    Keywords = the de-duplicated significant tokens across the outline's points; a keyword
    is present iff it appears as a whole word token in the body. Transparent whole-word
    coverage -- no partial/substring credit. Returns (fidelity, present, total).
    """
    keywords: list[str] = []
    seen: set[str] = set()
    for point in points:
        for token in _tokens(point):
            if token not in seen:
                seen.add(token)
                keywords.append(token)
    total = len(keywords)
    if total == 0:
        return 0.0, 0, 0
    body_tokens = set(_tokens(body_text))
    present = sum(1 for keyword in keywords if keyword in body_tokens)
    return present / total, present, total


# ---------------------------------------------------------------------------
# The ablation run: ground once, compose twice (V0 / V1), measure.
# ---------------------------------------------------------------------------


@dataclass
class AblationResult:
    """One ablation run's evidence -- ids, preimages, bodies, and the directional metric."""

    workspace: str
    topic: str
    query: str
    outline_digest: str
    published_fact_count: int
    survivor_instances: list[str]
    outline_headings: list[str]
    outline_points: list[str]
    v0_id: str
    v1_id: str
    v0_preimage: dict
    v1_preimage: dict
    v0_outline_absent: bool
    v1_rides_digest: bool
    v0_body: str
    v1_body: str
    v0_bytes: int
    v1_bytes: int
    v0_attempts: int
    v1_attempts: int
    v0_struct: float
    v1_struct: float
    v0_struct_hits: tuple[int, int]
    v1_struct_hits: tuple[int, int]
    v0_content: float
    v1_content: float
    v0_content_hits: tuple[int, int]
    v1_content_hits: tuple[int, int]
    v1_wins: bool


def _ir_body_text(doc: dict) -> str:
    """The composed prose: the flat `body`, or the concatenated part bodies (§15)."""
    if "body" in doc:
        return doc["body"]
    return "\n\n".join(part.get("body", "") for part in (doc.get("parts") or []))


def _compose_one(
    *, request: ComposeRequest, store: WorkspaceStore, claims, runner: Runner | None, model
) -> tuple[int, str]:
    """Compose one artifact via the injectable transport; return (attempts, body_text).

    On the idempotent no-op (`status=ok, ir=None`, an already-materialized re-run) the stored
    canonical envelope is loaded so the metric always has a body (mirrors the driver's re-drive).
    """
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner, model=model)
    if outcome.status != "ok":
        raise AblationError(
            f"compose did not persist {request.artifact_id}: status={outcome.status} "
            f"code={outcome.code} attempts={outcome.attempts} violations={list(outcome.violations)}"
        )
    doc = outcome.ir
    if doc is None:  # already-materialized re-run -> load the stored envelope (§21.8)
        raw = store.output_path(request.artifact_id).read_bytes()
        doc = ir.unwrap_ir(json.loads(raw))
    return outcome.attempts, _ir_body_text(dict(doc))


def run_ablation(
    *,
    root: str | Path,
    workspace: str,
    outline_md: str,
    recipe: str = "explainer-post",
    topic: str = "x-architecture-overview",
    persona: str | None = None,
    fmt: str | None = None,
    voice: str | None = None,
    goals: tuple[str, ...] | None = None,
    query: str | None = None,
    run_selection: dict | None = None,
    now: date | None = None,
    model: str | None = None,
    adapters: dict | None = None,
    runner: Runner | None = None,
) -> AblationResult:
    """Ground ONE coordinate once, compose V0 (no outline) + V1 (outline brief), and measure.

    `runner=None` uses the REAL subscription writer (the LIVE edge); a fake `Runner` makes the
    run hermetic. `adapters=None` uses the real graphify adapter (LIVE grounding); a fake pool
    (e.g. a `MockAdapter`) makes grounding hermetic too.
    """
    root = Path(root)
    now = now or date.today()
    env = CascadeEnv(root, workspace=workspace)

    # -- source pool + the pinned §7.2 commit-map/repo-map (the driver's own read, read-only).
    source_ids = _list_source_ids(root, workspace)
    if not source_ids:
        raise AblationError(
            f"workspace {workspace!r} declares no sources under sources/ -- grounding needs a "
            "pool (§6.1)"
        )
    pool = build_pool(env.resolver, source_ids)
    if adapters is None:
        adapters = {"graphify": GraphifyAdapter()}
    source_commit: dict[str, str] = {}
    source_repos: dict[str, str] = {}
    for inst in pool:
        source_repos[inst.id] = _source_repo_for(inst.id, inst.connection)
        commit = _pin_source_commit(adapters.get(inst.adapter), inst.connection)
        if commit is not None:
            source_commit[inst.id] = commit

    # -- resolve the content coordinate (M2-compose) once -- V0/V1 share it.
    compose = resolve_compose(
        env,
        RunSelection(recipe=recipe, topic=topic, persona=persona, format=fmt, voice=voice,
                     goals=goals),
    )
    format_parts = tuple(compose.format.values.get("parts") or ())
    effective_values = _effective_values(compose)

    # -- the two identities: V0 (4-key, outline-less) and V1 (5-key, rides the outline-digest).
    normalized = normalize_outline(outline_md)
    digest = outline_digest(outline_md)  # == sha256_hex(normalized)
    v0_preimage = compose.artifact_preimage(source_subset=source_ids, source_commit=source_commit)
    v0_id = mint_artifact_id(v0_preimage)
    v1_preimage = compose.artifact_preimage(
        source_subset=source_ids, source_commit=source_commit, outline_digest=digest
    )
    v1_id = mint_artifact_id(v1_preimage)

    # -- GROUND ONCE (identical grounding feeds both composes).
    grounding_query = query or _query_for_topic(topic)
    m3 = resolve_selection(
        workspace=compose.m3_inputs.workspace_baseline,
        goals=compose.m3_inputs.goal_implied,
        recipe=None,
        run=run_selection,
    )
    outcome = ground_item(
        item=v0_id, query=grounding_query, pool=pool, selection=m3, adapters=adapters,
        now=now, workspace=workspace,
    )
    if outcome.status == "block":
        raise AblationError(
            f"grounding BLOCKED for topic {topic!r} (code={outcome.code}): {dict(outcome.context)}"
        )
    published = outcome.publishable_facts
    if not published:
        raise AblationError(
            f"grounding returned no EXTRACTED (publishable) facts for {topic!r} -- the ablation "
            "needs a grounded artifact"
        )

    store = WorkspaceStore(root / "workspaces" / workspace)
    store.ensure_layout()
    claims = registry_for(store)

    # -- COMPOSE TWICE over the SAME grounded facts, differing ONLY in the outline brief.
    v0_attempts, v0_body = _compose_one(
        request=ComposeRequest(
            artifact_id=v0_id, preimage=v0_preimage, format_parts=format_parts,
            effective_values=effective_values, grounded_facts=published,
            source_repos=source_repos, outline_brief=None,
        ),
        store=store, claims=claims, runner=runner, model=model,
    )
    v1_attempts, v1_body = _compose_one(
        request=ComposeRequest(
            artifact_id=v1_id, preimage=v1_preimage, format_parts=format_parts,
            effective_values=effective_values, grounded_facts=published,
            source_repos=source_repos, outline_brief=normalized,
        ),
        store=store, claims=claims, runner=runner, model=model,
    )

    # -- MEASURE (directional; the outline is the reference).
    outline_headings, outline_points = parse_outline(normalized)
    content_points = outline_points or outline_headings
    v0_struct, v0_sm, v0_st = structure_fidelity(outline_headings, output_headings(v0_body))
    v1_struct, v1_sm, v1_st = structure_fidelity(outline_headings, output_headings(v1_body))
    v0_content, v0_cm, v0_ct = content_fidelity(content_points, v0_body)
    v1_content, v1_cm, v1_ct = content_fidelity(content_points, v1_body)

    return AblationResult(
        workspace=workspace,
        topic=topic,
        query=grounding_query,
        outline_digest=digest,
        published_fact_count=len(published),
        survivor_instances=list(outcome.instances),
        outline_headings=outline_headings,
        outline_points=outline_points,
        v0_id=v0_id,
        v1_id=v1_id,
        v0_preimage=v0_preimage,
        v1_preimage=v1_preimage,
        v0_outline_absent="outline-digest" not in v0_preimage,
        v1_rides_digest=v1_preimage.get("outline-digest") == digest,
        v0_body=v0_body,
        v1_body=v1_body,
        v0_bytes=len(v0_body.encode("utf-8")),
        v1_bytes=len(v1_body.encode("utf-8")),
        v0_attempts=v0_attempts,
        v1_attempts=v1_attempts,
        v0_struct=v0_struct,
        v1_struct=v1_struct,
        v0_struct_hits=(v0_sm, v0_st),
        v1_struct_hits=(v1_sm, v1_st),
        v0_content=v0_content,
        v1_content=v1_content,
        v0_content_hits=(v0_cm, v0_ct),
        v1_content_hits=(v1_cm, v1_ct),
        v1_wins=(v1_struct + v1_content) > (v0_struct + v0_content),
    )


# ---------------------------------------------------------------------------
# The report (the transcript the maintainer reads after the LIVE run).
# ---------------------------------------------------------------------------


def _print_report(r: AblationResult) -> None:
    print("=== DR-3 R1 outline-brief ablation (directional, n=1) ===")
    print(f"workspace : {r.workspace}")
    print(f"topic     : {r.topic}  query={r.query!r}")
    print(f"grounding : {r.published_fact_count} EXTRACTED fact(s) over {r.survivor_instances}")
    print(
        f"outline   : {len(r.outline_headings)} heading(s), {len(r.outline_points)} point(s); "
        f"digest {r.outline_digest[:16]}"
    )
    print()
    print("identity sanity (the live path):")
    print(f"  V0 id : {r.v0_id}   [4-key, outline-less: {r.v0_outline_absent}]")
    print(f"  V1 id : {r.v1_id}   [rides outline-digest: {r.v1_rides_digest}]")
    print(f"  distinct ids: {r.v0_id != r.v1_id}")
    print(f"  compose attempts: V0={r.v0_attempts} V1={r.v1_attempts}")
    print()
    print("metric (fraction in [0,1]; higher = follows the outline more):")
    print(f"  {'':12}{'struct':>8}{'content':>9}{'bytes':>9}")
    print(f"  {'V0 (none)':12}{r.v0_struct:8.2f}{r.v0_content:9.2f}{r.v0_bytes:9d}")
    print(f"  {'V1 (brief)':12}{r.v1_struct:8.2f}{r.v1_content:9.2f}{r.v1_bytes:9d}")
    print(
        f"  {'delta V1-V0':12}{r.v1_struct - r.v0_struct:+8.2f}"
        f"{r.v1_content - r.v0_content:+9.2f}{r.v1_bytes - r.v0_bytes:+9d}"
    )
    print()
    print(
        f"  struct detail : V0 {r.v0_struct_hits[0]}/{r.v0_struct_hits[1]} vs "
        f"V1 {r.v1_struct_hits[0]}/{r.v1_struct_hits[1]} outline headings realized, in order"
    )
    print(
        f"  content detail: V0 {r.v0_content_hits[0]}/{r.v0_content_hits[1]} vs "
        f"V1 {r.v1_content_hits[0]}/{r.v1_content_hits[1]} outline keywords in the body"
    )
    print()
    verdict = (
        "V1 follows the outline MORE than V0"
        if r.v1_wins
        else "no directional lift from the outline brief"
    )
    print(
        f"VERDICT (directional, n=1): {verdict} "
        f"(struct delta {r.v1_struct - r.v0_struct:+.2f}, "
        f"content delta {r.v1_content - r.v0_content:+.2f})"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dr3_outline_ablation",
        description=(
            "DR-3 R1 outline-brief ablation (build-time experiment): ground once, compose V0 "
            "(no outline) + V1 (outline brief), and measure whether V1 follows the outline more. "
            "runner=None here -> the LIVE subscription writer (spends quota)."
        ),
    )
    parser.add_argument("--workspace", required=True, help="the workspace (e.g. mvp-demo)")
    parser.add_argument("--root", default=".", help="framework repo root (default: cwd)")
    parser.add_argument("--recipe", default="explainer-post", help="the content recipe")
    parser.add_argument("--topic", default="x-architecture-overview", help="the topic entry id")
    parser.add_argument("--persona", default=None, help="override the resolved persona")
    parser.add_argument("--format", dest="fmt", default=None, help="override the resolved format")
    parser.add_argument("--voice", default=None, help="override the resolved voice")
    parser.add_argument(
        "--query", default=None, help="grounding query (default: humanized from the topic id)"
    )
    parser.add_argument(
        "--now", default=None, metavar="YYYY-MM-DD", help="grounding clock (default: today)"
    )
    parser.add_argument("--model", default=None, help="writer model to pin (default: CLI's own)")
    parser.add_argument(
        "--outline-file",
        default=None,
        metavar="PATH",
        help="a hand-authored Markdown outline (default: the built-in demo outline)",
    )
    args = parser.parse_args(argv)

    try:
        now = date.fromisoformat(args.now) if args.now else date.today()
    except ValueError:
        print(f"dr3_outline_ablation: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2

    if args.outline_file:
        outline_md = Path(args.outline_file).read_text(encoding="utf-8")
    else:
        outline_md = DEFAULT_OUTLINE

    print(
        f"=== dr3-ablation: workspace={args.workspace} root={args.root} topic={args.topic} "
        f"now={now} (LIVE compose) ==="
    )
    try:
        result = run_ablation(
            root=args.root,
            workspace=args.workspace,
            outline_md=outline_md,
            recipe=args.recipe,
            topic=args.topic,
            persona=args.persona,
            fmt=args.fmt,
            voice=args.voice,
            query=args.query,
            now=now,
            model=args.model,
            runner=None,  # None -> the REAL subscription writer (the LIVE edge)
        )
    except AblationError as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 1

    _print_report(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
