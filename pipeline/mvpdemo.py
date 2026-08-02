"""The ★ MVP demonstration scenario (§25) — ONE scripted, reproducible §25 acceptance run.

Design authority: `docs/design.md` §25 (the MVP exercises ALL NINE dimensions end to end,
interacting — no staged/partial axis set): grounding with the full selection grammar (§6);
resolution over the full cascade including one run override (§12); compose → reconcile →
serialize across ≥1 internal AND ≥1 external-side target (§14–§17); both review gates (§19); a
folio with a typed-run member and an untyped member (§9); `emit-manifest` with member targets
(§21.5); the sequential AND parallel consumption modes (§21.6, §22); the SSOT projection (§24).

**ONE callable, two drivers (the clean mock/live split).** `run_mvp_scenario` takes injectable
SEAMS — `runner` (writer), `review_runner`, `adapters`, `render_engine`, `currency_resolver`,
`now`, `model` — and builds ONE handler dict from them (M1), driving the whole scenario via
`invoke(handlers=…)` (ZERO global-registry mutation — `register_api_handlers` is never called).
The hermetic CI test (`tests/test_mvp_scenario.py`) injects fakes (no subscription spend); the
authored-but-unexecuted `pipeline mvp-demo` subcommand supplies the real transport + graphify
adapter + the MVP fail-safe currency resolver (`MvpFailSafeCurrencyResolver`). No fake is
reachable from the subcommand; no live call is reachable from the test.

**This module is an ORCHESTRATOR, like `pipeline.driver`/`pipeline.api.session`.** It MAY import
`driver`/`plan`/`session`/`ssot`, but it MUST NOT be imported by `pipeline/__init__.py` — that
keeps it off the INV-CORRECTNESS BFS roots (`tests/test_inv_correctness.py`).

**GATE-2 (§21.9 currency, HIGH).** The `currency_resolver` seam is passed EXPLICITLY at BOTH
edges, so `discovery.DefaultCurrencyResolver` (the unsafe `except → stored_digest` partial
detector) is NEVER reached on the mvp-demo path. The live subcommand supplies the fail-safe
resolver below (conservative-by-design: any un-verifiable input reads as NOT-current → over-force,
idempotent under render); the test injects a precise fake (exact current annotations).
"""

from __future__ import annotations

import datetime
import functools
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pipeline import driver, serialize
from pipeline import payload as payload_mod
from pipeline.adapters.base import SourceAdapter
from pipeline.api import discovery, fetch, folio_verbs, manifest, session
from pipeline.api import invoke as invoke_mod
from pipeline.api import render as render_api
from pipeline.cascade import CascadeEnv, RunSelection, resolve_compose
from pipeline.dispatch import dispatch, render_target_from_entry
from pipeline.grounding import TIER_EXTRACTED, ground_item
from pipeline.m3 import render_clause
from pipeline.plan import Plan, PlanItem
from pipeline.spine import registry_for
from pipeline.store import WorkspaceStore
from pipeline.transport import Runner

__all__ = [
    "MvpFailSafeCurrencyResolver",
    "MvpReport",
    "run_mvp_scenario",
]

# --- The fixed §25 scenario shape (the ONE reproducible scenario; the world matches it) -----

#: The framework recipe the scenario binds (persona technical-evaluator, format
#: short-opinion-post, goals [explain]). The live/tmp workspace must declare the source pool,
#: the two topics, and the styled presentation this scenario names (see the report / §6).
RECIPE = "explainer-post"

#: The sequential branch topics (batch+cursor over TWO artifacts). `x-widget-service` carries the
#: ≥2-instance grounding conflict; `x-gadget-cache` a distinct grounded artifact.
SEQ_TOPICS = ("x-widget-service", "x-gadget-cache")

#: The single-valued render coordinate + the TWO presentations the sequential branch fans out to.
PLATFORM = "github"
LANGUAGE = "en"
INTERNAL_OUTPUT_TYPE = "md"
STYLED_PRESENTATION = "documentation"  # the workspace-local styled entry (§5.3 PD5 / B1)
PLAIN_PRESENTATION = "plain"

#: The ≥1 EXTERNAL-side target (§14.2/§17 RI14): the `epub` render-target ships `side: external`.
EXTERNAL_OUTPUT_TYPE = "epub"

#: The parallel branch runs a DISTINCT persona over the same topics → DISJOINT artifact-ids un-
#: materialized by the sequential branch (M3: a genuine incomplete→complete sweep, not the floor).
PARALLEL_PERSONA = "product-reviewer"

#: The L6 run override (§12.5/§21.4) — alters a RESOLVED `effective_values` entry the compose
#: prompt honors (voice.formality 3 → 5), NOT merely the id hash.
OVERRIDES: dict[str, Any] = {"voice.formality": 5}
OVERRIDE_ATTRIBUTE = "voice.formality"

#: The FULL §6.3 selection grammar (require + span + prefer + on_conflict) over ≥2 source
#: instances. `preserve-and-attribute` keeps BOTH conflicting timeout claims (30s vs 60s),
#: attributed — a genuine ≥2-instance resolved conflict in the grounding survivors.
M3_RUN_SELECTION: dict[str, Any] = {
    "require": ["trusted >= 3"],
    "span": {"independence": ["first-party", "independent"]},
    "prefer": [{"authoritative": 1}],
    "on_conflict": "preserve-and-attribute",
}

#: The typed folio (§9.6) + the member roles: one TYPED member (a repo-docs role) + one UNTYPED.
FOLIO_TYPE = "repo-docs"
TYPED_MEMBER_ROLE = "architecture"

#: The conflict subject the grounding survivors must carry both sides of (the resolved conflict).
_CONFLICT_SUBJECT = "widget-service.timeout"


# --- GATE-2: the MVP fail-safe currency resolver (live edge; §21.9) -------------------------


@dataclass(frozen=True)
class MvpFailSafeCurrencyResolver:
    """The MVP live-edge currency resolver (GATE-2): CONSERVATIVE BY DESIGN, never the unsafe
    `discovery.DefaultCurrencyResolver`.

    `current_fit_digest`/`current_serialize_digest` return a distinct NON-matching sentinel on
    EVERY input, so a deliverable always reads as NOT-current (`fit_current`/`serialize_current`
    = False). That is the gate's prescribed fail-safe direction: over-force (idempotent under
    render), never the `except → stored_digest` "reads an error as no-drift" behaviour §21.9
    closes. It performs NO §21.9 recompute; the live currency columns are conservative, and the
    deliverables are in fact freshly minted (documented in the run report)."""

    #: A sentinel that is NOT a `hex12` digest, so it can never equal a recorded fit/serialize
    #: digest (12 lowercase hex) — the deliverable always annotates NOT-current.
    _SENTINEL = "mvp-fail-safe-not-current"

    def current_fit_digest(
        self,
        *,
        root: Path,
        user: str,
        workspace: str,
        fitted_id: str,
        stored_preimage: Mapping[str, Any],
    ) -> str:
        return self._SENTINEL

    def current_serialize_digest(
        self,
        *,
        root: Path,
        user: str,
        workspace: str,
        deliverable_id: str,
        stored_preimage: Mapping[str, Any],
    ) -> str:
        return self._SENTINEL


# --- The §25 clause → evidence report ------------------------------------------------------


@dataclass
class MvpReport:
    """The §25 clause→evidence checklist captured by one scenario run — the report the maintainer
    reads and the CI test asserts against. Every field is literal evidence (ids, records,
    rendered clauses, sweep transitions), never a claim of success."""

    workspace: str
    axes: dict[str, Any] = field(default_factory=dict)
    grounding: dict[str, Any] = field(default_factory=dict)
    override: dict[str, Any] = field(default_factory=dict)
    styled: dict[str, Any] = field(default_factory=dict)
    external: dict[str, Any] = field(default_factory=dict)
    reviews: dict[str, Any] = field(default_factory=dict)
    sequential: dict[str, Any] = field(default_factory=dict)
    parallel: dict[str, Any] = field(default_factory=dict)
    folio: dict[str, Any] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)
    ssot: dict[str, Any] = field(default_factory=dict)
    discovery: dict[str, Any] = field(default_factory=dict)


# --- Handler wiring (M1): ONE dict from the seams, zero global-registry mutation ------------


def _build_handlers(
    *,
    adapters: Mapping[str, SourceAdapter],
    runner: Runner | None,
    review_runner: Runner | None,
    render_engine: Any,
    currency_resolver: Any,
    now: date,
    model: str | None,
    manifest_now: manifest.NowFn,
) -> dict[str, invoke_mod.Handler]:
    """Build the invoke handler dict from the injected seams (the documented `invoke(handlers=…)`
    seam). The generate-next writer/review transports ride a `functools.partial` wrapping
    `driver._run_artifact` as the session's `run_artifact` seam (session._generate_next calls it
    with a fixed kwarg set that does NOT include runner/review_runner, so the partial supplies
    them cleanly). `None` seams fall through to the REAL transports (the live edge). The currency
    resolver is threaded to `list`/`get`/`emit-manifest` EXPLICITLY (GATE-2 — never the default)."""
    run_artifact = (
        functools.partial(driver._run_artifact, runner=runner, review_runner=review_runner)
        if (runner is not None or review_runner is not None)
        else None  # None → session defaults to the real driver._run_artifact (live transport)
    )
    return {
        "begin-session": session.begin_session_handler(adapters=adapters),
        "continue-session": session.continue_session_handler(
            adapters=adapters,
            run_artifact=run_artifact,
            now=now,
            model=model,
            render_engine=render_engine,
            currency_resolver=currency_resolver,
        ),
        "render": render_api.render_handler(engine=render_engine),
        "fetch-by-id": fetch.fetch_handler(),
        "create-folio": folio_verbs.create_folio_handler(),
        "add-to-folio": folio_verbs.add_to_folio_handler(),
        "list": discovery.list_handler(
            resolver=currency_resolver, action_vocab=session.CONTINUE_ACTIONS
        ),
        "get": discovery.get_handler(resolver=currency_resolver),
        "emit-manifest": manifest.emit_manifest_handler(
            resolver=currency_resolver, now=manifest_now
        ),
    }


# --- Small helpers --------------------------------------------------------------------------


def _item_for_topic(plan: Plan, topic: str) -> PlanItem:
    for item in plan.items:
        if item.topic == topic:
            return item
    raise RuntimeError(f"mvp-scenario: plan resolved no item for topic {topic!r}")


def _read_record(store: WorkspaceStore, id_str: str) -> Mapping[str, Any] | None:
    try:
        raw = store.output_path(id_str).read_bytes()
    except FileNotFoundError:
        return None
    return json.loads(raw)


def _read_review(store: WorkspaceStore, id_str: str) -> Mapping[str, Any] | None:
    try:
        raw = store.review_path(id_str).read_bytes()
    except FileNotFoundError:
        return None
    return json.loads(raw)


def _preimage_variables(record: Mapping[str, Any] | None) -> Any:
    return (
        (record or {})
        .get("binding", {})
        .get("preimage", {})
        .get("render_inputs", {})
        .get("variables")
    )


# --- The external-serialize helper (m5): mint ≥1 external deliverable from the fitted IR ------


def _mint_external(store: WorkspaceStore, env: CascadeEnv, *, fitted_id: str) -> dict[str, Any]:
    """Mint the ≥1 external-side deliverable from the ALREADY-composed fitted IR (m5: same
    (platform, language) as the internal `md` deliverable → zero extra reconcile): read the fitted
    IR → `serialize_fitted` → `dispatch(external target)` → `payload.build_payload` (unconditional
    provenance strip) → spine `_persist_record`. m4: the external target has NO SSOT row and NO
    Review 2 (it bypasses `_run_deliverable`), so no SSOT advance hook is wired here."""
    fit_record = _read_record(store, fitted_id)
    if fit_record is None or "ir" not in fit_record:
        raise RuntimeError(f"mvp-scenario: no fitted record for {fitted_id!r}")
    fitted_ir = fit_record["ir"]
    fit_binding = fit_record["binding"]

    target_values = driver._render_target_values(env, EXTERNAL_OUTPUT_TYPE)
    target = render_target_from_entry(target_values)  # side: external (epub3)

    units = serialize.serialize_fitted(fitted_ir)
    if len(units) != 1:
        raise RuntimeError("mvp-scenario: the flat MVP artifact must serialize to one document")
    ast = units[0].ast
    # external → payload_ast (stripped for epub3), deferred. B (F4): the EXTERNAL hand-off embeds no
    # body figure (embedding is internal html5/docx only), so `resource_paths=()` is passed
    # explicitly — the external deliverable-id intentionally does NOT fold body-figure content.
    dout = dispatch(target, ast, resource_paths=())

    # The serialize-inputs preimage + render-binding (the deliverable-level identity, §17 RI13).
    # An external plain-floor target lowers to the empty RenderInputs (B1 parity).
    render_inputs_view = {"flags": [], "variables": {}, "assets": [], "engine": target.engine}
    preimage = serialize.serialize_inputs_preimage(
        render_target=target_values,
        render_inputs=render_inputs_view,
        section_attr_transformed=dout.section_attr_transformed,
        citeproc_enabled=dout.citeproc_enabled,
        # B (F4): the external hand-off folds NO body figure — the defaults keep the external
        # deliverable-id byte-identical to pre-B (no `asset_embed_version`, no `embedded_assets`).
        assets_embedded=False,
        embedded_assets=(),
    )
    render_binding = serialize.build_render_binding(
        fitted_id=fitted_id,
        output_type=EXTERNAL_OUTPUT_TYPE,
        presentation=PLAIN_PRESENTATION,
        preimage=preimage,
        fit_binding_ref=fit_binding,
    )
    external_did = render_binding["deliverable_id"]

    # The RI14 layer-3 contract payload — provenance stripped UNCONDITIONALLY (fail-closed).
    contract = payload_mod.build_payload(
        ast=ast,
        deliverable_id=external_did,
        render_target=target,
        pin_bundle=render_binding["pin_bundle"],
        fitted_ir=fitted_ir,
        requested_output_types=[EXTERNAL_OUTPUT_TYPE],
        extension=EXTERNAL_OUTPUT_TYPE,
        # C10: thread the citeproc REQUIREMENT. The MVP external target is the plain-floor epub3
        # of a non-citing artifact → `dout.citeproc_enabled` is False and there is no csl lever
        # (`dispatch(target, ast)` carries no RenderInputs), so the `citeproc` block is OMITTED →
        # the MVP external payload is byte-identical to pre-C10.
        citeproc_enabled=dout.citeproc_enabled,
        csl=None,
    )

    claims = registry_for(store)
    driver._persist_record(  # m4: advance=None — an external target keys no SSOT row
        store,
        claims,
        external_did,
        {
            "binding": render_binding,
            "side": target.side,
            "payload": contract,
            "stripped": dout.stripped,
        },
        preimage=preimage,
        advance=None,
    )
    return {
        "deliverable_id": external_did,
        "fitted_id": fitted_id,
        "side": target.side,
        "writer": target.writer,
        "provenance_stripped": dout.stripped,
        "payload_kind_persisted": "layer-3",
    }


# --- Evidence extractors --------------------------------------------------------------------


def _selection_summary(item: PlanItem) -> dict[str, Any]:
    """The rendered §6.3 selection (require/span/prefer/on_conflict/grounding_posture)."""
    sel = item.m3
    return {
        "require": [render_clause(c) for c in sel.require],
        "span": {axis: list(members) for axis, members in sel.span.items()},
        "prefer": [[term.term.key, term.weight] for term in sel.prefer],
        "on_conflict": sel.on_conflict,
        "grounding_posture": sel.grounding_posture,
    }


def _grounding_evidence(
    env: CascadeEnv,
    pool: Sequence[Any],
    item: PlanItem,
    now: date,
    workspace: str,
    adapters: Mapping[str, SourceAdapter],
) -> dict[str, Any]:
    """Ground the primary item directly (READ-ONLY, no LLM) to capture the §6.3 evidence the
    generate-next path consumes but discards: the rendered selection, the ≥2 survivors, the
    published (EXTRACTED-tier) fact count, and the resolved conflict — BOTH timeout claims,
    preserved-and-attributed (`preserve-and-attribute`)."""
    outcome = ground_item(
        item=item.artifact_id,
        query=driver._query_for_topic(item.topic),
        pool=pool,
        selection=item.m3,
        adapters=adapters,
        now=now,
        workspace=workspace,
    )
    conflict_claims = sorted({f.claim for f in outcome.facts if f.subject == _CONFLICT_SUBJECT})
    published = sum(1 for f in outcome.facts if f.tier == TIER_EXTRACTED)
    return {
        "selection": _selection_summary(item),
        "survivor_instances": list(outcome.instances),
        "published_fact_count": published,
        "conflict_subject": _CONFLICT_SUBJECT,
        "conflict_claims": conflict_claims,
        "conflict_strategy": item.m3.on_conflict,
        "contradiction_count": len(outcome.contradictions),
    }


def _override_evidence(root: Path, user: str, workspace: str) -> dict[str, Any]:
    """Prove the L6 override altered a RESOLVED `effective_values` entry the compose prompt honors
    (driver `_effective_values`), NOT merely the id hash (§8d)."""
    sel = RunSelection(recipe=RECIPE, topic=SEQ_TOPICS[0])
    env_ov = CascadeEnv(root, user=user, workspace=workspace, overrides=OVERRIDES)
    env_base = CascadeEnv(root, user=user, workspace=workspace)
    ev_ov = driver._effective_values(resolve_compose(env_ov, sel))
    ev_base = driver._effective_values(resolve_compose(env_base, sel))
    dimension, attribute = OVERRIDE_ATTRIBUTE.split(".", 1)
    return {
        "attribute": OVERRIDE_ATTRIBUTE,
        "with_override": ev_ov[dimension][attribute],
        "without_override": ev_base[dimension][attribute],
    }


# --- The scenario ---------------------------------------------------------------------------


def run_mvp_scenario(
    *,
    root: str | Path,
    user: str,
    workspace: str,
    adapters: Mapping[str, SourceAdapter],
    runner: Runner | None,
    review_runner: Runner | None,
    render_engine: Any,
    currency_resolver: Any,
    now: date,
    model: str | None = None,
    log: Callable[[str], None] | None = None,
) -> MvpReport:
    """Drive the whole §25 scenario over `invoke(handlers=…)` and return the clause→evidence
    report. The seams decide mock vs live; NOTHING here calls `register_api_handlers` or mutates
    the global verb registry. GATE-2: `currency_resolver` is passed EXPLICITLY at every edge, so
    `DefaultCurrencyResolver` is never reached."""
    root = Path(root)
    log = log or (lambda _m: None)
    store = WorkspaceStore.at(root, user, workspace)
    store.ensure_layout()

    def manifest_now() -> datetime.datetime:  # the §21.5 deterministic-filename clock seam
        return datetime.datetime.combine(now, datetime.time(0, 0, 0), tzinfo=datetime.UTC)

    handlers = _build_handlers(
        adapters=adapters,
        runner=runner,
        review_runner=review_runner,
        render_engine=render_engine,
        currency_resolver=currency_resolver,
        now=now,
        model=model,
        manifest_now=manifest_now,
    )

    def do(verb: str, params: Mapping[str, Any], token: Any = None) -> dict[str, Any]:
        return invoke_mod.invoke(
            verb, workspace, user, dict(params), token,
            store=store, root=str(root), handlers=handlers,
        )

    def decode(wire: Any) -> Any:
        return invoke_mod.token_mod.decode(wire, expected_workspace=workspace)

    report = MvpReport(workspace=workspace)

    # -- SEQUENTIAL branch: begin (generate NONE); then re-resolve the plan from the token's OWN
    #    inputs (§21.6) so the id-mapping is byte-identical to what generate-next materializes. ---
    seq_begin = do(
        "begin-session",
        {
            "recipe": RECIPE,
            "topics": list(SEQ_TOPICS),
            "platforms": [PLATFORM],
            "languages": [LANGUAGE],
            "output_types": [INTERNAL_OUTPUT_TYPE],
            "presentations": [PLAIN_PRESENTATION, STYLED_PRESENTATION],
            "overrides": OVERRIDES,
            "run_selection": M3_RUN_SELECTION,
        },
    )
    log(f"sequential begin-session ok={seq_begin['envelope']['ok']}")
    seq_token = seq_begin["token"]
    seq_plan, env, pool, _repos = session._resolve_from_inputs(
        root, user, workspace, decode(seq_token).inputs
    )
    seq_widget = _item_for_topic(seq_plan, SEQ_TOPICS[0])

    # §6.3 grounding grammar + §12.5 override evidence (read-only, no LLM).
    report.grounding = _grounding_evidence(env, pool, seq_widget, now, workspace, adapters)
    report.override = _override_evidence(root, user, workspace)

    # generate-next batch_size=1 × K → cursor 0 → 1 → … → K (§21.6 batch + cursor).
    token = seq_token
    cursor_progression: list[int] = [len(decode(token).cursor.get("consumed", []))]
    generate_results: list[list[dict[str, Any]]] = []
    for _ in range(len(SEQ_TOPICS)):
        step = do("continue-session", {"action": "generate-next", "batch_size": 1}, token)
        token = step.get("token", token)
        generate_results.append(step["results"])
        cursor_progression.append(len(decode(token).cursor.get("consumed", [])))
    seq_status = do("continue-session", {"action": "status"}, token)
    report.sequential = {
        "plan_hash": seq_plan.plan_hash,
        "artifact_ids": list(seq_begin["results"][0]["ids"]["artifact_ids"]),
        "cursor_progression": cursor_progression,
        "generate_results": generate_results,
        "status_progress": seq_status["results"][0]["context"],
    }

    # -- B1 (§5.3 PD5): plain vs styled deliverables (both through the presentation-aware
    #    _run_deliverable). The styled preimage carries a variables snapshot; plain's is empty. ---
    plain_did = next(
        d.deliverable_id for d in seq_widget.deliverables if d.presentation == PLAIN_PRESENTATION
    )
    styled_did = next(
        d.deliverable_id for d in seq_widget.deliverables if d.presentation == STYLED_PRESENTATION
    )
    report.styled = {
        "plain_deliverable_id": plain_did,
        "styled_deliverable_id": styled_did,
        "distinct_ids": plain_did != styled_did,
        "plain_variables": _preimage_variables(_read_record(store, plain_did)),
        "styled_variables": _preimage_variables(_read_record(store, styled_did)),
    }

    # -- Both review gates (§19): Review 1 (compose) + Review 2 (_run_deliverable) ran with the
    #    injected review_runner; records exist under reviews/. ------------------------------------
    art_review = _read_review(store, seq_widget.artifact_id) or {}
    del_review = _read_review(store, plain_did) or {}
    report.reviews = {
        "artifact_review_id": seq_widget.artifact_id,
        "artifact_review_present": bool(art_review),
        "artifact_verdict": art_review.get("verdict"),
        "deliverable_review_id": plain_did,
        "deliverable_review_present": bool(del_review),
        "deliverable_verdict": del_review.get("verdict"),
    }

    # -- ≥1 external target (§14–§17): mint it from the sequential widget artifact's fitted IR. ----
    report.external = _mint_external(store, env, fitted_id=seq_widget.deliverables[0].fitted_id)

    # -- §21.3 discovery reads: get (one artifact) + list (deliverables, with currency computed
    #    through the injected resolver — GATE-2). NOTE: the §21.8 standalone `render` verb is not
    #    exercised by THIS scenario; it has its own hermetic suite (tests/test_render_verb.py). The
    #    GAP-1a read-shape bug this note used to flag — `render._render` 404'd every REAL composed
    #    artifact because it read `record["ir"]` while `compose` persists the RAW IR envelope (no
    #    `ir` wrapper) — is now FIXED: `_render` reads through `ir.unwrap_ir`, tolerating BOTH the
    #    wrapped fitted record and the raw compose envelope (GAP-1a). B1 in render.py is proven by
    #    the green suite (zero id/byte churn) + the driver path's styled-variables evidence above. -
    get_out = do("get", {"type": "artifacts", "id": seq_widget.artifact_id})
    list_out = do("list", {"type": "deliverables"})
    report.discovery = {
        "get_artifact_present": get_out["results"][0]["status"] == "ok",
        "list_deliverable_count": len(list_out["results"]),
        "list_deliverable_ids": [r["ids"].get("deliverable_id") for r in list_out["results"]],
    }

    # -- PARALLEL branch (§22): DISTINCT selection (persona), want_parallel_plan → wave plan →
    #    sweep incomplete → partial → complete over TWO un-materialized artifacts. ----------------
    parallel_ctx = _run_parallel(do)
    par_token = parallel_ctx.pop("_token")
    report.parallel = parallel_ctx
    par_plan, _e2, _p2, _r2 = session._resolve_from_inputs(
        root, user, workspace, decode(par_token).inputs
    )
    par_widget = _item_for_topic(par_plan, SEQ_TOPICS[0])

    # -- Folio (§9): typed + untyped member; emit-manifest with member targets (§21.5). ----------
    report.folio, report.manifest = _run_folio_and_manifest(
        do, seq_widget.artifact_id, par_widget.artifact_id
    )

    # -- SSOT (§24): both row kinds + `ssot derive-state` mirror. ---------------------------------
    from pipeline.ssot import derive_state

    ssot_csv = store.root / "ssot.csv"
    csv_text = ssot_csv.read_bytes().decode("utf-8") if ssot_csv.is_file() else ""
    # The SSOT CSV keys the row kind in the FIRST column (`row_kind,id,…`); read it there.
    row_kinds = {line.split(",", 1)[0] for line in csv_text.splitlines()[1:] if line}
    report.ssot = {
        "csv_path": str(ssot_csv),
        "csv_text": csv_text,
        "has_artifact_rows": "artifact" in row_kinds,
        "has_deliverable_rows": "deliverable" in row_kinds,
        "derive_state": derive_state(ssot_csv) if ssot_csv.is_file() else "",
    }

    # -- The nine axes coordinate summary (the §25 mandate: all NINE, interacting). ---------------
    report.axes = {
        "topic": seq_widget.topic,
        "persona": seq_widget.persona,
        "format": seq_widget.format,
        "voice": seq_widget.voice,
        "goals": list(seq_widget.goals),
        "platform": PLATFORM,
        "language": LANGUAGE,
        "output_type": [INTERNAL_OUTPUT_TYPE, EXTERNAL_OUTPUT_TYPE],
        "presentation": [PLAIN_PRESENTATION, STYLED_PRESENTATION],
    }
    return report


def _run_parallel(do: Callable[..., dict[str, Any]]) -> dict[str, Any]:
    """The M3 non-vacuous parallel branch: wave plan (waves 0/1) → sweep BEFORE (incomplete) →
    drive artifact #1 (partial) → drive artifact #2 (complete). A genuine ∪-check across waves.
    Returns the evidence dict plus a private `_token` (popped by the caller to re-resolve the
    parallel plan for id-mapping)."""
    begin = do(
        "begin-session",
        {
            "recipe": RECIPE,
            "topics": list(SEQ_TOPICS),
            "personas": [PARALLEL_PERSONA],
            "platforms": [PLATFORM],
            "languages": [LANGUAGE],
            "output_types": [INTERNAL_OUTPUT_TYPE],
            "presentations": [PLAIN_PRESENTATION],
            # The same §6.3 grammar the sequential branch uses (so both topics ground); the
            # parallel artifacts stay DISJOINT from the sequential ones via the DISTINCT persona
            # (the selection is a grounding-time filter, never part of artifact identity, §7.2).
            "run_selection": M3_RUN_SELECTION,
            "want_parallel_plan": True,
        },
    )
    token = begin["token"]
    plan_ctx = begin["results"][0]["context"]
    aids = list(begin["results"][0]["ids"]["artifact_ids"])

    def sweep() -> dict[str, Any]:
        return do("continue-session", {"action": "status"}, token)["results"][0]["context"]["sweep"]

    before = sweep()
    step1 = do("continue-session", {"action": "generate-next", "only": [aids[0]]}, token)
    token = step1.get("token", token)
    partial = sweep()
    step2 = do("continue-session", {"action": "generate-next", "only": [aids[1]]}, token)
    token = step2.get("token", token)
    after = sweep()
    waves = plan_ctx.get("parallel_plan", {}).get("waves", [])
    return {
        "_token": token,  # popped by the caller after re-resolving the plan for id-mapping
        "artifact_ids": aids,
        "wave_count": len(waves),
        "wave_kinds": [w["kind"] for w in waves],
        "sweep_before": before,
        "sweep_partial": partial,
        "sweep_after": after,
    }


def _run_folio_and_manifest(
    do: Callable[..., dict[str, Any]],
    typed_aid: str,
    untyped_aid: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Create a TYPED folio (repo-docs); add a TYPED member (role) + an UNTYPED member (no role);
    emit-manifest with member_targets resolving an INTERNAL (path) + an EXTERNAL (layer-3) row."""
    created = do(
        "create-folio",
        {"purpose": "mvp-demo folio", "folio_type": FOLIO_TYPE, "idempotency_key": "mvp-folio"},
    )
    folio_id = created["results"][0]["ids"]["folio_id"]
    do(
        "add-to-folio",
        {
            "folio_id": folio_id,
            "members": [
                {"artifact_id": typed_aid, "role": TYPED_MEMBER_ROLE},
                {"artifact_id": untyped_aid},
            ],
        },
    )
    members_out = do("list", {"type": "folio-members", "folio_id": folio_id})
    member_roles = {
        r["ids"]["artifact_id"]: r["context"].get("role") for r in members_out["results"]
    }

    emit = do(
        "emit-manifest",
        {
            "folio_id": folio_id,
            "member_targets": {
                typed_aid: [
                    {
                        "platform": PLATFORM,
                        "language": LANGUAGE,
                        "output_type": INTERNAL_OUTPUT_TYPE,
                        "presentation": STYLED_PRESENTATION,
                    },
                    {
                        "platform": PLATFORM,
                        "language": LANGUAGE,
                        "output_type": EXTERNAL_OUTPUT_TYPE,
                        "presentation": PLAIN_PRESENTATION,
                    },
                ],
                untyped_aid: [
                    {
                        "platform": PLATFORM,
                        "language": LANGUAGE,
                        "output_type": INTERNAL_OUTPUT_TYPE,
                        "presentation": PLAIN_PRESENTATION,
                    },
                ],
            },
        },
    )
    rows = emit["results"][0]["context"]["manifest"]["rows"]
    payload_kinds = [
        (row.get("payload") or {}).get("kind") for row in rows if row.get("payload") is not None
    ]
    folio = {
        "folio_id": folio_id,
        "folio_type": FOLIO_TYPE,
        "typed_member": typed_aid,
        "typed_member_role": member_roles.get(typed_aid),
        "untyped_member": untyped_aid,
        "untyped_member_role": member_roles.get(untyped_aid),
    }
    manifest_evidence = {
        "path": emit["results"][0]["output"]["path"],
        "row_count": len(rows),
        "payload_kinds": payload_kinds,
        "has_internal_path": "path" in payload_kinds,
        "has_external_layer3": "layer-3" in payload_kinds,
    }
    return folio, manifest_evidence
