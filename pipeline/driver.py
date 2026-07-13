"""The thin end-to-end thread driver (plan step 28 — the FIRST END-TO-END OUTPUT).

Design authority: `docs/design.md`
  §2.1 stages 1–5 — the pipeline spine this module threads: GROUND (a source adapter
        reads the client graph by path, §6) → RESOLVE/BIND (fanout → plan → M2 compose
        cascade → M2 render cascade, §8/§12) → COMPOSE (the writer stage, a LIVE
        subscription LLM call, §15) → RECONCILE (the fit pass, §16) → SERIALIZE (the
        pinned Pandoc pass + dispatch, §17) → PERSIST (the S0–S6 spine, §22.3) → the
        two REVIEW gates (§19: the artifact review once post-compose, the deliverable
        review post-bytes on every deliverable — advisory, advancing SSOT STATUS only,
        never mutating the persisted output) → the SSOT row advance (§24, the derived
        convenience). The reviews ride the existing compose/dispatch advance-hook
        mechanism; the driver stays thin and imports the SSOT only as the orchestrator.
  §25 — this is a BUILD MILESTONE, explicitly NOT the MVP. It exercises ONE concrete
        thread from a REAL graph through a REAL LLM to a REAL deliverable, the earliest
        real end-to-end output the design's own gates allow (gates precede build; every
        upstream stage is a hard dependency). It never stages a "minimal subset" of the
        MVP and must never be read as one.

This module ORCHESTRATES the already-built, already-tested stage APIs; it reimplements
no stage logic. It is the ORCHESTRATOR, not a correctness module (the INV-CORRECTNESS
import lint watches store/claims/spine/sweep/parallel — never the driver), so it MAY
import `pipeline.ssot`: it drives the spine (the sole content-addressed correctness
basis) and THEN advances the SSOT rows as the derived, side-effect-only convenience
(the spine's S5 `advance_hook`, plus the deliverable-row `fitted` write).

Durable rules on this thread (CLAUDE.md 1/2/4):
  1. The client graph is READ-ONLY, always: grounding reads it by path via the graphify
     adapter; the source-commit pin reads `built_at_commit` from the same graph.json.
     Nothing here writes, moves, or mutates anything under a source/client repo.
  2. Client isolation via the workspace: the store, claims, SSOT, and all output live
     under `workspaces/<client>/` and never leak elsewhere.
  4. The demo instance (`instance/defaults.yaml` + `workspaces/<client>/`) is INSTANCE
     data — untracked, never committed. This module is framework mechanism
     (`provenance: framework`); only it and the `demo-thread` subcommand are committable.

It becomes the step-32/33 `invoke` core, so `run_thread` takes the selection as input
(the `demo-thread` subcommand supplies the demo's concrete thread) and keeps the wiring
generic; identity flows from the resolved plan (never re-minted here, §9.6).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pipeline import presentation as _presentation
from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.graphify import GraphifyAdapter
from pipeline.api import results
from pipeline.canonical import canonical_json_bytes, digest_full
from pipeline.cascade import (
    CascadeEnv,
    ComposeResolution,
    RenderResolution,
    RunSelection,
    resolve_compose,
    resolve_render,
)
from pipeline.compose import ComposeRequest, compose_artifact
from pipeline.dispatch import (
    dispatch,
    render_target_from_entry,
    review_deliverable,
)
from pipeline.fanout import SelectionRequest
from pipeline.grounding import GroundingOutcome, build_pool, ground_item
from pipeline.ids import mint_artifact_id
from pipeline.plan import DeliverableItem, Plan, PlanItem, resolve_plan
from pipeline.reconcile import ReconcileRequest, reconcile
from pipeline.serialize import (
    build_render_binding,
    serialize_fitted,
    serialize_inputs_preimage,
)
from pipeline.spine import AdvanceHook, SpineResult, WorkUnit, drive, registry_for
from pipeline.ssot import Ssot
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, write_new
from pipeline.transport import Runner

__all__ = [
    "DeliverableResult",
    "DriverError",
    "ThreadResult",
    "demo_selection",
    "run_thread",
]

#: The demo output layer-2 extension for the `md` output-type (§7.4: never part of the id).
_DEMO_OUTPUT_EXTENSION = "md"

Log = Callable[[str], None]


def _deferred_asset_loader(path: str) -> bytes:
    """The production-path Presentation asset loader (B1) — a DEFERRED, loud no-op.

    `presentation.presentation_from_entry` invokes this ONLY for an entry declaring a
    `css`/`template`/`reference_doc` asset lever. No framework entry declares any (only
    `plain.md` ships), so it is NEVER called on any existing or MVP path; raising here (vs the
    old `lower_plain` silent lever-drop) is strictly more honest (§3.1). Shipping a real
    filesystem asset loader (the asset-path resolution convention) is §17/step-29 scope."""
    raise _presentation.PresentationError(
        "presentation-error: asset levers (css/template/reference_doc) are not yet lowerable on "
        f"the production generate-next path — deferred to §17/step-29; an entry declares a "
        f"file-backed asset lever referencing {path!r}"
    )


class DriverError(RuntimeError):
    """A driver-level WIRING defect the thread can never proceed past — loud, typed,
    never a silent skip (§3.1). A stage's own typed failure (compose contract, reconcile
    block, transport error) is carried as a result, not raised as this.

    HARD GATE-1 (§21.7 code threading) — CLOSED at step 39. Two GENERATION-TIER raise sites
    thread the stage's TRUE §21.7 taxonomy code so `session._generate_next` can surface it as
    a coded `block` (`empty-pool` at the grounding gate, `hard-limit-exceeded` at the reconcile
    terminal gate) instead of a bare code-less hint. `stage_code`/`remediation_action` are NEW
    INSTANCE fields, `None` for every OTHER raise (a non-taxonomy failure stays code-less — the
    §3.1 no-fabrication rule). The CLASS attribute `code = "driver-error"` is UNTOUCHED (it is
    the exception's own kind, not a §21.7 result code)."""

    code = "driver-error"

    def __init__(
        self,
        message: str,
        *,
        stage_code: str | None = None,
        remediation_action: str | None = None,
    ) -> None:
        super().__init__(message)
        #: The threaded §21.7 stage code (a taxonomy `block` code) or None. Never fabricated:
        #: only a real `("block",)` generation code (`empty-pool`/`hard-limit-exceeded`) is
        #: ever passed here; every other raise leaves it None (§3.1).
        self.stage_code = stage_code
        #: The optional machine remediation action; None lets the session default it from the
        #: threaded code's CodeSpec (`results.make_result`), never a hardcoded guess.
        self.remediation_action = remediation_action


# --- Result records (the transcript the subcommand renders) --------------------------------


@dataclass(frozen=True)
class DeliverableResult:
    """One rendered deliverable: its id, on-disk bytes, the identity records, and the §19
    deliverable-review (Review 2) verdict/code (advisory — never gates the thread)."""

    deliverable_id: str
    fitted_id: str
    reconcile_strategy: str
    reconcile_is_noop: bool
    writer: str
    side: str
    bytes_path: str
    byte_count: int
    sha256: str
    preview: str
    fit_binding: Mapping[str, Any]
    render_binding: Mapping[str, Any]
    review_code: str = ""
    review_verdict: str | None = None


@dataclass(frozen=True)
class ArtifactResult:
    """One composed artifact + its deliverables, plus the composition-binding proof and the §19
    artifact-review (Review 1) verdict/code (advisory — never gates the thread)."""

    artifact_id: str
    query: str
    fact_count: int
    published_fact_count: int
    composition_verified: bool
    composition_digest: str
    transport_cost_usd: float | None
    artifact_record_path: str
    deliverables: tuple[DeliverableResult, ...]
    review_code: str = ""
    review_verdict: str | None = None


@dataclass(frozen=True)
class ThreadResult:
    """One full thread's outcome — the report/transcript payload."""

    workspace: str
    recipe: str
    plan_hash: str
    source_subset: tuple[str, ...]
    source_commit: Mapping[str, str]
    axes: Mapping[str, Any]
    ssot_csv_path: str
    ssot_report: str
    artifacts: tuple[ArtifactResult, ...]


# --- The demo selection (the ONE concrete thread step 28 threads) --------------------------


def demo_selection() -> SelectionRequest:
    """The step-28 demo thread's nine axes as one fanout request (§8).

    Content dims ride the framework `explainer-post` recipe (persona
    `technical-evaluator`, format `short-opinion-post`, goal `explain`) plus the
    workspace topic; rendering dims name platform `github` + `en` + `md` + `plain`. The
    voice resolves via the §12.3 chain (the persona's `clear-explainer` default over the
    instance L2 global). Exactly one content combination × one render coordinate → one
    artifact, one deliverable — the smallest honest end-to-end thread.
    """
    return SelectionRequest(
        recipe="explainer-post",
        topics=("x-architecture-overview",),
        platforms=("github",),
        languages=("en",),
        output_types=("md",),
        presentations=("plain",),
    )


# --- Grounding inputs (pool, query, commit pin) --------------------------------------------


def _list_source_ids(root: Path, workspace: str) -> list[str]:
    """The workspace's declared source pool (§6.1): every `sources/<id>.md` instance
    entry, in id order. Templates and the co-located schema are not entries."""
    sources_dir = root / "workspaces" / workspace / "sources"
    if not sources_dir.is_dir():
        return []
    ids: list[str] = []
    for path in sorted(sources_dir.glob("*.md")):
        if ".template." in path.name:
            continue
        ids.append(path.stem)
    return ids


def _query_for_topic(topic_id: str) -> str:
    """Derive the grounding question from the topic id (the milestone's query carrier).

    The topic dimension owns the subject matter (§5.2); v1's topic schema carries no
    structured query field, so the driver humanizes the entry id (strip the `x-`
    instance prefix, hyphens → spaces) into the §6.3 grounding question. The full
    `invoke` (step 32/33) will carry a richer topic-seeded query; this is the milestone's
    honest, deterministic derivation.
    """
    return topic_id.removeprefix("x-").replace("-", " ").strip()


def _source_repo_for(instance_id: str, connection: Mapping[str, Any]) -> str:
    """The §15 ledger `source_repo` for one source instance.

    For a graphify source the graph lives at `<checkout>/graphify-out/graph.json`; the
    repo is that checkout (the graph's grandparent dir). A plain path is not
    secret-shaped, so it rides the ledger's §3.3 scan cleanly. Falls back to the instance
    id when no path is bound (never a silent blank — compose refuses that loudly)."""
    raw_path = connection.get("path")
    if isinstance(raw_path, str) and raw_path:
        parent = Path(raw_path).parent
        checkout = parent.parent if parent.name == "graphify-out" else parent
        return str(checkout)
    return instance_id


def _pin_source_commit(
    adapter: SourceAdapter | None, connection: Mapping[str, Any]
) -> str | None:
    """Pin the source commit for the artifact-id commit-map (§7.2), read-only.

    CF-1: this delegates to `adapter.pin_commit`, the SAME provenance read the grounding
    pass uses (`SourceAdapter.ground` → `GroundingResult.built_at_commit`), so the
    commit-map that enters IDENTITY and the commit the §15 grounding LEDGER records can
    never disagree. A graphify source reads graph.json's `built_at_commit` and, for a
    commitless-but-git checkout, falls back to the read-only `git rev-parse HEAD` — the
    exact value grounding will also report (previously this function read only
    `built_at_commit` and OMITTED the git-fallback commit, so identity and the ledger
    diverged for such a source; the step-28 demo did not trigger it, but generate-next
    over real selections can). `None` for an unbound adapter or a commitless source (the
    designed folder-style posture)."""
    return adapter.pin_commit(connection) if adapter is not None else None


# --- Persistence (spine-driven records over the workspace store) ---------------------------


def _recorded_preimage_lookup(store: WorkspaceStore) -> Callable[[str], Any]:
    """The S0 preimage-check reader (§22.3): the recorded §7.4 preimage from a stored
    record's `binding.preimage`, or None when the id is unseen. Reads the OUTPUT STORE
    only — the driver's records (IR-canonical, IR-fitted, render-binding) all key their
    preimage under `binding.preimage`, exactly as compose's own lookup does."""

    def lookup(id_str: str) -> Any:
        try:
            raw = store.output_path(id_str).read_bytes()
        except FileNotFoundError:
            return None
        doc = json.loads(raw)
        return doc.get("binding", {}).get("preimage") if isinstance(doc, dict) else None

    return lookup


def _persist_record(
    store: WorkspaceStore,
    claims: Any,
    id_str: str,
    record: Mapping[str, Any],
    *,
    preimage: Any,
    advance: AdvanceHook | None = None,
) -> SpineResult:
    """Persist one id-keyed output record through the S0–S6 spine (§22.3): a claim on the
    id, an atomic no-replace commit, holder-checked release. `advance` is the write-only
    S5 SSOT hook (None for the fitted-level record, which keys no SSOT row)."""
    payload = canonical_json_bytes(record)
    unit = WorkUnit(id=id_str, payload=lambda data=payload: data, preimage=preimage)
    return drive(
        unit,
        store=store,
        claims=claims,
        recorded_preimage=_recorded_preimage_lookup(store),
        advance=advance,
    )


# --- Effective-value + resolution helpers --------------------------------------------------


def _json_safe(values: Mapping[str, Any]) -> dict[str, Any]:
    """A bound-dimension value view for the writer prompt (context, never identity). The
    content dims bind text/markdown/slider/enum/list attributes — all JSON-native; a
    non-serializable value would be a schema defect, surfaced loudly by json below."""
    return {key: value for key, value in values.items()}


def _effective_values(compose: ComposeResolution) -> dict[str, Any]:
    """The per-dimension M2-compose view the writer prompt honors (§15)."""
    return {
        "topic": _json_safe(compose.topic.values),
        "persona": _json_safe(compose.persona.values),
        "format": _json_safe(compose.format.values),
        "voice": _json_safe(compose.voice.values),
        "goals": {g.entry_id: _json_safe(g.values) for g in compose.goals},
    }


def _render_target_values(env: CascadeEnv, output_type: str) -> dict[str, Any]:
    """The resolved render-target entry values (§17 RI12: target id == output-type slug).
    The dispatcher + serialize-inputs preimage consume this flat frontmatter view."""
    entry = env.resolver.resolve("render-targets", output_type)
    values = {**entry.defaults(), **entry.effective}
    values["id"] = entry.id
    return values


def _platform_hard_limits(env: CascadeEnv, platform: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The platform's HARD limits (CA9) + the schema floor — the §16 terminal-gate input.
    Hard limits live entirely OUTSIDE M2 (never bound), so they are read from the raw
    platform entry, never from the render resolution's bound values."""
    entry = env.resolver.resolve("platforms", platform)
    schema = env.resolver.schema("platforms")
    limits = entry.effective.get("hard_limits") or {}
    floor = schema.attributes["hard_limits"].default or {}
    return dict(limits), dict(floor)


# --- The one-deliverable render leg (reconcile → serialize → persist) ----------------------


def _run_deliverable(
    *,
    env: CascadeEnv,
    store: WorkspaceStore,
    claims: Any,
    ssot: Ssot,
    compose: ComposeResolution,
    recipe: str,
    item: PlanItem,
    deliverable: DeliverableItem,
    canonical_ir: Mapping[str, Any],
    source_commit_digest: str,
    model: str | None,
    log: Log,
    review_runner: Runner | None = None,
) -> DeliverableResult:
    """Thread one deliverable coordinate: reconcile (fit) → serialize (pinned Pandoc) →
    persist the fitted IR + the render-binding + the layer-2 bytes; advance the
    deliverable SSOT row `planned → fitted → rendered`; then run the §19 deliverable
    review (Review 2) POST-bytes, advancing the row to `deliverable-reviewed`."""
    d = deliverable
    ssot.register(
        d.deliverable_id,
        "deliverable",
        coordinates=f"{d.platform}/{d.language}/{d.output_type}/{d.presentation}",
        source_commit=source_commit_digest,
        output_path=str(store.output_path(d.deliverable_id).relative_to(store.root)),
    )

    render: RenderResolution = resolve_render(
        env,
        compose,
        RunSelection(
            recipe=recipe,
            platform=d.platform,
            language=d.language,
            output_type=d.output_type,
            presentation=d.presentation,
        ),
    )
    hard_limits, hard_limit_defaults = _platform_hard_limits(env, d.platform)

    # -- reconcile (§16): the demo binds `pass`, so a same-language fit is a ZERO-LLM
    #    passthrough; the terminal hard-limit gate still runs (fit-or-block, never silent).
    rout = reconcile(
        ReconcileRequest(
            canonical_ir=canonical_ir,
            artifact_id=item.artifact_id,
            platform=d.platform,
            language=d.language,
            source_language=d.language,
            strategy=d.reconcile_strategy,
            hard_limits=hard_limits,
            hard_limit_defaults=hard_limit_defaults,
            advisory=render.advisories,
            advisory_defaults={},
        )
    )
    if rout.status != "ok" or rout.fitted_ir is None or rout.fit_binding is None:
        # HARD GATE-1 (§21.7): thread the reconcile stage's TRUE taxonomy code — GUARDED to
        # a real §21.7 code (`hard-limit-exceeded` on the terminal-gate block; else the typed
        # non-taxonomy `fit-fidelity-violation`/transport codes stay code-less, never
        # fabricated, §3.1). `session._generate_next` derives the block STATUS from the code's
        # CodeSpec (`("block",)`), never a hardcoded status.
        raise DriverError(
            f"driver-error: reconcile did not fit deliverable {d.deliverable_id} — "
            f"status={rout.status} code={rout.code} blocked_limits={rout.blocked_limits} "
            f"violations={rout.violations}",
            stage_code=rout.code if rout.code in results.ALL_CODES else None,
        )
    fitted_ir = rout.fitted_ir
    fit_binding = rout.fit_binding
    fitted_id = rout.fitted_id
    assert fitted_id is not None  # ok status guarantees it
    log(
        f"    reconcile: {d.reconcile_strategy} -> fitted-id {fitted_id} "
        f"({'no-op passthrough' if rout.is_noop else f'{rout.attempts} attempt(s)'})"
    )

    # Persist the IR-fitted record (fitted-level key; keys no SSOT row of its own —
    # `fitted` is a deliverable-row STATUS). CF-2: route the deliverable-row `fitted`
    # advance through the spine's S5 CONTAINED-hook (§22.7 guardrail 3), exactly like
    # `composed`/`rendered` — never a raw `ssot.advance` outside the S5 exception
    # containment. The hook fires on both the fresh and the already-materialized re-drive
    # (S4/S5 always run), reproducing the prior unconditional advance. The fitted record's
    # own id keys no row, so the hook targets the DELIVERABLE id (a fixed capture),
    # ignoring the persisted fitted-id the spine hands it.
    def _advance_fitted_row(_fitted_id: str, _deliverable_id: str = d.deliverable_id) -> None:
        ssot.advance(_deliverable_id, "fitted")  # outcome DISCARDED — write-only (§22.7)

    _persist_record(
        store,
        claims,
        fitted_id,
        {"ir": fitted_ir, "binding": fit_binding},
        preimage=fit_binding["preimage"],
        advance=_advance_fitted_row,
    )

    # -- serialize (§17): the fitted IR → the pinned Pandoc AST → dispatch to the internal
    #    writer for layer-2 bytes. `plain` presentation lowers to the empty RenderInputs.
    units = serialize_fitted(fitted_ir)
    if len(units) != 1:
        raise DriverError(
            f"driver-error: the flat demo artifact serialized to {len(units)} documents; "
            "expected exactly one (single-part `short-opinion-post`, §15 flat-body collapse)"
        )
    ast = units[0].ast

    target_values = _render_target_values(env, d.output_type)
    target = render_target_from_entry(target_values)
    # B1 (§5.3 PD3/PD5): lower the RESOLVED presentation on the production path. The bound
    # presentation is already in scope as `render.presentation` (a BoundDimension whose
    # `.values` is the total post-M2 view, so any L6 presentation override is honored); no
    # re-resolve. For the `plain` floor this yields RenderInputs(flags=(), variables={},
    # assets=(), engine=target.engine) — byte-identical to the retired `lower_plain(target)`,
    # so every existing (all-`plain`) deliverable-id + bytes are UNCHANGED (PD5 zero-churn); a
    # styled entry lowers to real `--variable`/`--highlight-style` flags + a variables snapshot.
    pres = _presentation.presentation_from_entry(
        {**render.presentation.values, "id": render.presentation.entry_id},
        load_asset=_deferred_asset_loader,
        defaults=render.presentation.entry.defaults(),
    )
    render_inputs = _presentation.lower(
        pres, target.writer, d.output_type, target_engine=target.engine
    )
    dout = dispatch(target, ast, render_inputs=render_inputs)
    if dout.output_bytes is None:
        raise DriverError(
            f"driver-error: internal render-target {d.output_type!r} produced no layer-2 "
            f"bytes (side={dout.side}) — the demo threads an INTERNAL target (§25 ≥1 internal)"
        )
    output_bytes = dout.output_bytes

    render_inputs_view = {
        "flags": list(render_inputs.flags),
        "variables": dict(render_inputs.variables),
        "assets": [list(asset) for asset in render_inputs.assets],
        "engine": render_inputs.engine,
    }
    serialize_preimage = serialize_inputs_preimage(
        render_target=target_values, render_inputs=render_inputs_view
    )
    render_binding = build_render_binding(
        fitted_id=fitted_id,
        output_type=d.output_type,
        presentation=d.presentation,
        preimage=serialize_preimage,
        fit_binding_ref=fit_binding,
    )
    if render_binding["deliverable_id"] != d.deliverable_id:
        raise DriverError(
            f"driver-error: serialize minted deliverable-id "
            f"{render_binding['deliverable_id']!r} but the plan resolved {d.deliverable_id!r} "
            "— the render leg must extend the SAME fitted coordinate (§7.4)"
        )

    # The layer-2 bytes: the real deliverable, keyed by deliverable-id + a conventional
    # extension (§7.4). Atomic no-replace; an already-materialized re-run keeps the bytes.
    bytes_path = store.bytes_path(d.deliverable_id, _DEMO_OUTPUT_EXTENSION)
    try:
        write_new(bytes_path, output_bytes)
    except AlreadyMaterializedError:
        pass

    # The render-binding record (deliverable-level key) drives the spine + advances the
    # deliverable row to `rendered` via S5.
    digest = hashlib.sha256(output_bytes).hexdigest()
    _persist_record(
        store,
        claims,
        d.deliverable_id,
        {
            "binding": render_binding,
            "layer2": {
                "path": str(bytes_path.relative_to(store.root)),
                "sha256": digest,
                "byte_count": len(output_bytes),
            },
            "writer": target.writer,
            "side": target.side,
            "stripped": dout.stripped,
        },
        preimage=serialize_preimage,
        advance=ssot.advance_hook("rendered"),
    )
    log(
        f"    serialize: {target.writer} ({target.side}) -> "
        f"{bytes_path.name} ({len(output_bytes)} bytes)"
    )

    # §19 Review 2: the FULL deliverable review runs POST-bytes (row now at `rendered`),
    # advancing the deliverable row to `deliverable-reviewed`. It reads the fitted IR + the
    # AST + the hard limits and NEVER mutates the persisted bytes/records (advisory).
    review = review_deliverable(
        store=store,
        deliverable_id=d.deliverable_id,
        fitted_ir=fitted_ir,
        ast=ast,
        hard_limits=hard_limits,
        context={
            "platform": d.platform,
            "language": d.language,
            "output_type": d.output_type,
            "presentation": d.presentation,
            "writer": target.writer,
            "side": target.side,
            "document_count": len(units),
        },
        review_advance=ssot.advance_hook("deliverable-reviewed"),
        review_model=model,
        review_runner=review_runner,
    )
    log(f"    review: deliverable {review.code} verdict={review.verdict}")

    preview = output_bytes.decode("utf-8", errors="replace")
    return DeliverableResult(
        deliverable_id=d.deliverable_id,
        fitted_id=fitted_id,
        reconcile_strategy=d.reconcile_strategy,
        reconcile_is_noop=rout.is_noop,
        writer=target.writer,
        side=target.side,
        bytes_path=str(bytes_path.relative_to(store.root)),
        byte_count=len(output_bytes),
        sha256=digest,
        preview=preview[:600],
        fit_binding=fit_binding,
        render_binding=render_binding,
        review_code=review.code,
        review_verdict=review.verdict,
    )


# --- The one-artifact compose leg (ground → compose → deliverables) ------------------------


def _run_artifact(
    *,
    env: CascadeEnv,
    store: WorkspaceStore,
    claims: Any,
    ssot: Ssot,
    plan: Plan,
    item: PlanItem,
    pool: Sequence[Any],
    adapters: Mapping[str, SourceAdapter],
    source_repos: Mapping[str, str],
    now: date,
    model: str | None,
    log: Log,
    runner: Runner | None = None,
    review_runner: Runner | None = None,
) -> ArtifactResult:
    """Thread one artifact: ground the topic, compose (LIVE LLM), then each deliverable.

    `runner`/`review_runner` are the generate-next TRANSPORT SEAMS (default `None` = the real
    subscription transport): `runner` is the writer (compose), `review_runner` the §19 reviewer
    (Review 1 rides `compose_artifact`; Review 2 rides each `_run_deliverable`). The hermetic
    `run_mvp_scenario` injects fakes here (via a `functools.partial` wrapping this function as
    the session's `run_artifact` seam) so NO live subscription call is reachable from the test;
    the live `mvp-demo` subcommand leaves them `None`."""
    ssot.register(
        item.artifact_id,
        "artifact",
        coordinates=f"{item.topic}/{item.persona}/{item.format}/{item.voice}/{','.join(item.goals)}",
        source_commit=digest_full(dict(plan.source_commit)),
        output_path=str(store.output_path(item.artifact_id).relative_to(store.root)),
    )

    query = _query_for_topic(item.topic)
    log(f"  ground: topic {item.topic!r} query={query!r} over pool {list(source_repos)}")
    outcome: GroundingOutcome = ground_item(
        item=item.artifact_id,
        query=query,
        pool=pool,
        selection=item.m3,
        adapters=adapters,
        now=now,
        workspace=env.workspace,
    )
    if outcome.status == "block":
        # HARD GATE-1 (§21.7): the grounding gate blocks with the real `empty-pool` code
        # (§6.4, always `("block",)`); thread it so the session surfaces a coded block, not a
        # bare hint. Guarded to a real §21.7 code (defensive — grounding only ever blocks with
        # `empty-pool`); the remediation action rides through so the session need not guess it.
        raise DriverError(
            f"driver-error: grounding BLOCKED for {item.artifact_id} "
            f"(code={outcome.code}): {dict(outcome.context)}",
            stage_code=outcome.code if outcome.code in results.ALL_CODES else None,
            remediation_action=(
                outcome.remediation.get("action")
                if isinstance(outcome.remediation, Mapping)
                else None
            ),
        )
    published = outcome.publishable_facts
    log(
        f"  ground: {len(outcome.facts)} fact(s), {len(published)} publishable (EXTRACTED); "
        f"commits {dict(outcome.commit_map)}"
    )
    if not published:
        raise DriverError(
            f"driver-error: grounding returned no publishable (EXTRACTED) facts for "
            f"{item.artifact_id} — the milestone thread must produce a GROUNDED artifact"
        )

    compose = resolve_compose(
        env,
        RunSelection(
            recipe=plan.recipe,
            topic=item.topic,
            persona=item.persona,
            format=item.format,
            voice=item.voice,
            goals=item.goals,
        ),
    )
    format_parts = tuple(compose.format.values.get("parts") or ())

    request = ComposeRequest(
        artifact_id=item.artifact_id,
        preimage=item.preimage,
        format_parts=format_parts,
        effective_values=_effective_values(compose),
        grounded_facts=published,
        source_repos=source_repos,
    )
    log(f"  compose: LIVE writer call ({len(published)} grounded fact(s))...")
    cout = compose_artifact(
        request,
        store=store,
        claims=claims,
        runner=runner,  # the writer transport seam (None = real subscription)
        advance=ssot.advance_hook("composed"),
        model=model,
        # §19 Review 1: post-mint artifact review, advancing the row to `artifact-reviewed`.
        review_runner=review_runner,  # the Review-1 transport seam (None = real subscription)
        review_advance=ssot.advance_hook("artifact-reviewed"),
        review_model=model,
    )
    if cout.status != "ok" or cout.ir is None:
        raise DriverError(
            f"driver-error: compose did not persist artifact {item.artifact_id} — "
            f"status={cout.status} code={cout.code} attempts={cout.attempts} "
            f"violations={cout.violations}"
        )
    canonical_ir = cout.ir
    binding = canonical_ir["binding"]
    verified = (
        mint_artifact_id(binding["preimage"]) == item.artifact_id
        and binding["digest"] == digest_full(item.preimage)
        and binding["artifact_id"] == item.artifact_id
    )
    cost = cout.transport_result.total_cost_usd if cout.transport_result else None
    log(
        f"  compose: OK ({cout.code}); binding digest {binding['digest'][:16]}… "
        f"reproduces {item.artifact_id} -> {'VERIFIED' if verified else 'MISMATCH'}"
    )
    # §19 Review 1 rode inside compose_artifact (post-mint, advancing `artifact-reviewed`).
    review = cout.review
    if review is not None:
        log(f"  review: artifact {review.code} verdict={review.verdict}")

    deliverables = tuple(
        _run_deliverable(
            env=env,
            store=store,
            claims=claims,
            ssot=ssot,
            compose=compose,
            recipe=plan.recipe,
            item=item,
            deliverable=d,
            canonical_ir=canonical_ir,
            source_commit_digest=digest_full(dict(plan.source_commit)),
            model=model,
            log=log,
            review_runner=review_runner,  # Review 2 transport seam (None = real subscription)
        )
        for d in item.deliverables
    )

    return ArtifactResult(
        artifact_id=item.artifact_id,
        query=query,
        fact_count=len(outcome.facts),
        published_fact_count=len(published),
        composition_verified=verified,
        composition_digest=binding["digest"],
        transport_cost_usd=cost,
        artifact_record_path=str(store.output_path(item.artifact_id).relative_to(store.root)),
        deliverables=deliverables,
        review_code=review.code if review is not None else "",
        review_verdict=review.verdict if review is not None else None,
    )


# --- The thread entry point ----------------------------------------------------------------


def run_thread(
    *,
    root: str | Path,
    workspace: str,
    request: SelectionRequest | None = None,
    now: date | None = None,
    model: str | None = None,
    log: Log | None = None,
) -> ThreadResult:
    """Drive ONE full thread end to end and return the transcript (§2.1 stages 1–5).

    `request` defaults to the step-28 demo selection; `now` injects the grounding clock
    (default today — the edge injects it, never ambient); `model` pins the writer model
    (default None: the module pins nothing, §3.1). `log` receives stage lines for the
    live transcript. The LIVE subscription writer call happens inside `compose_artifact`
    (transport strips `ANTHROPIC_API_KEY`, runs in a non-repo cwd). A stage failure raises
    `DriverError` with the exact failing stage + message — never a fabricated success.
    """
    root = Path(root)
    now = now or date.today()
    log = log or (lambda _msg: None)
    request = request or demo_selection()

    env = CascadeEnv(root, workspace=workspace)

    # -- source pool + the pinned commit-map (§7.2): read the graph's commit BY PATH.
    source_ids = _list_source_ids(root, workspace)
    if not source_ids:
        raise DriverError(
            f"driver-error: workspace {workspace!r} declares no source instances under "
            "workspaces/<ws>/sources/ — grounding needs a source pool (§6.1)"
        )
    pool = build_pool(env.resolver, source_ids)
    # Build the adapter set FIRST so the commit-map is pinned through the SAME provenance
    # read grounding uses (CF-1): `_pin_source_commit` delegates to `adapter.pin_commit`.
    adapters: dict[str, SourceAdapter] = {"graphify": GraphifyAdapter()}
    source_commit: dict[str, str] = {}
    source_repos: dict[str, str] = {}
    for inst in pool:
        source_repos[inst.id] = _source_repo_for(inst.id, inst.connection)
        commit = _pin_source_commit(adapters.get(inst.adapter), inst.connection)
        if commit is not None:
            source_commit[inst.id] = commit
    log(
        f"pool: {source_ids}; commit-map {source_commit}; "
        f"repos {source_repos}"
    )

    # -- resolve the plan (§21.6 pure function): the complete id-keyed item cover.
    plan = resolve_plan(
        env,
        request,
        source_subset=tuple(source_ids),
        source_commit=source_commit,
    )
    log(
        f"plan: hash {plan.plan_hash[:16]}…; {len(plan.items)} artifact item(s), "
        f"{len(plan.deliverable_ids())} deliverable(s)"
    )
    for warning in plan.warnings:
        log(f"plan-warning: {warning.message}")
    if not plan.items:
        raise DriverError(
            "driver-error: the plan resolved zero artifact items — the demo selection "
            "must fan out to exactly one artifact (§8)"
        )

    # -- the store, claims, and SSOT under the workspace (rule 2; instance data).
    store = WorkspaceStore(root / "workspaces" / workspace)
    store.ensure_layout()
    claims = registry_for(store)
    ssot_csv = store.root / "ssot.csv"
    ssot = Ssot(ssot_csv)

    artifacts = tuple(
        _run_artifact(
            env=env,
            store=store,
            claims=claims,
            ssot=ssot,
            plan=plan,
            item=item,
            pool=pool,
            adapters=adapters,
            source_repos=source_repos,
            now=now,
            model=model,
            log=log,
        )
        for item in plan.items
    )

    ssot_report = ssot_csv.read_bytes().decode("utf-8")
    axes = {
        "recipe": request.recipe,
        "topics": list(request.topics),
        "platforms": list(request.platforms),
        "languages": list(request.languages),
        "output_types": list(request.output_types),
        "presentations": list(request.presentations),
        "personas": [item.persona for item in plan.items],
        "formats": [item.format for item in plan.items],
        "voices": [item.voice for item in plan.items],
        "goals": [list(item.goals) for item in plan.items],
    }
    return ThreadResult(
        workspace=workspace,
        recipe=request.recipe,
        plan_hash=plan.plan_hash,
        source_subset=tuple(source_ids),
        source_commit=source_commit,
        axes=axes,
        ssot_csv_path=str(ssot_csv),
        ssot_report=ssot_report,
        artifacts=artifacts,
    )
