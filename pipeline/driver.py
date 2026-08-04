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
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from pipeline import diagram, ir
from pipeline import presentation as _presentation
from pipeline.adapters import default_adapters
from pipeline.adapters.base import SourceAdapter
from pipeline.api import results
from pipeline.asset_loader import filesystem_asset_loader, hash_embedded_assets
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
from pipeline.grounding import GroundingOutcome, SourceInstance, build_pool, ground_item
from pipeline.ids import mint_artifact_id
from pipeline.outline_store import get_outline
from pipeline.plan import DeliverableItem, Plan, PlanItem, resolve_plan
from pipeline.reconcile import ReconcileRequest, reconcile
from pipeline.serialize import (
    build_render_binding,
    extension_for,
    serialize_fitted,
    serialize_inputs_preimage,
)
from pipeline.spine import AdvanceHook, SpineResult, WorkUnit, drive, registry_for
from pipeline.ssot import Ssot
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, write_new
from pipeline.transport import Runner
from pipeline.workspace_name import workspace_path

__all__ = [
    "DeliverableResult",
    "DriverError",
    "ThreadResult",
    "demo_selection",
    "run_thread",
]

Log = Callable[[str], None]


class DriverError(RuntimeError):
    """A driver-level WIRING defect the thread can never proceed past — loud, typed,
    never a silent skip (§3.1). A stage's own typed failure (compose contract, reconcile
    block, transport error) is carried as a result, not raised as this.

    HARD GATE-1 (§21.7 code threading) — CLOSED at step 39. Three GENERATION-TIER raise sites
    thread the stage's TRUE §21.7 taxonomy code so `session._generate_next` can surface it as
    a coded `block` (`empty-pool` at the grounding gate, `hard-limit-exceeded` at the reconcile
    terminal gate, `grounding-uncovered` at the post-review abstain gate) instead of a bare
    code-less hint. `stage_code`/`remediation_action` are NEW
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
        #: only a real `("block",)` generation code
        #: (`empty-pool`/`hard-limit-exceeded`/`grounding-uncovered`) is ever passed here;
        #: every other raise leaves it None (§3.1).
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

    user: str
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


def _list_source_ids(root: Path, user: str, workspace: str) -> list[str]:
    """The workspace's declared source pool (§6.1): every `sources/<id>.md` instance
    entry, in id order. Templates and the co-located schema are not entries. The pool lives
    under `users/<user>/workspaces/<ws>/sources/` (§23) — a pure door-validated join."""
    sources_dir = workspace_path(root, user, workspace, "sources")
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


def _freeze_pool(
    pool: Sequence[SourceInstance],
    adapters: Mapping[str, SourceAdapter],
    source_commit: Mapping[str, str],
) -> tuple[SourceInstance, ...]:
    """FREEZE each source's plan-time pinned commit into the connection the DRIVE-time
    `ground()` reads (§6 mechanism (a)) — so a HEAD/'latest'-mode source grounds the PINNED
    snapshot (full N2), never a live pointer a mid-session acquire may have advanced.

    The pin already ran (it produced `source_commit`); this threads that pinned commit BACK
    into the connection via the adapter's `freeze_connection` hook (connection-AUGMENTATION —
    the `ground` contract signature is untouched). Adapters whose sources are externally
    snapshot-stable (graphify/folder/fsast) keep the default NO-OP, so their CLOSED connection
    keysets stay undisturbed AND their instance identity is unchanged (no `replace`); only the
    cache reader names its pinned slice. CF-1 is preserved: `pin_commit` over the frozen
    connection re-resolves the SAME commit. A commitless source (no `source_commit` entry) has
    nothing pinned to freeze and rides through unchanged (the SM1 empty posture)."""
    frozen: list[SourceInstance] = []
    for inst in pool:
        commit = source_commit.get(inst.id)
        adapter = adapters.get(inst.adapter)
        if commit is None or adapter is None:
            frozen.append(inst)
            continue
        connection = adapter.freeze_connection(inst.connection, commit)
        frozen.append(
            inst if connection is inst.connection else replace(inst, connection=connection)
        )
    return tuple(frozen)


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


def _read_stored_record(store: WorkspaceStore, id_str: str) -> Mapping[str, Any] | None:
    """Read one id-keyed output record as a JSON mapping (§22.3), or None when the record is absent
    or corrupt. The GAP-1d idempotent re-drive uses this to LOAD the stored canonical IR when
    compose short-circuits (`status="ok", ir=None`); NEW-F: it returns None (never raises) on a
    vanished/corrupt record so the caller raises a clear `DriverError`, not `ir.unwrap_ir(None)`."""
    try:
        raw = store.output_path(id_str).read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return doc if isinstance(doc, Mapping) else None


def _grounding_abstain_check(store: WorkspaceStore, item: PlanItem) -> None:
    """DR-6 (§6.5/§19) item-level abstain — the D1 enforcement seam (§2.4).

    Under `grounding_posture=block` ONLY, a PERSISTED Review-1 record whose advisory `grounding`
    check reads `concern` makes THIS item ABSTAIN: a coded `grounding-uncovered` block (siblings
    continue). Default `warn` never abstains — today's behavior EXACTLY (regression-neutral). The
    gate is FAIL-OPEN: a record that is absent / unreadable / partial / malformed SHIPS (never
    raises), deterministically identical on re-drive. `pipeline/review.py` stays advisory and
    SSOT-free; this driver seam is the sole place that advisory concern can gate a ship.
    """
    if item.m3.grounding_posture != "block":
        return
    path = store.review_path(item.artifact_id)
    if not path.exists():
        return  # fail-OPEN: no persisted Review-1 record -> SHIP (identical on re-drive)
    try:
        record = json.loads(path.read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return  # fail-OPEN: unreadable/corrupt record -> SHIP
    if not isinstance(record, Mapping):
        return  # fail-OPEN: a non-object record -> SHIP
    checks = record.get("checks")
    grounding = checks.get("grounding") if isinstance(checks, Mapping) else None
    status = grounding.get("status") if isinstance(grounding, Mapping) else None
    if status == "concern":
        raise DriverError(
            f"driver-error: grounding-uncovered for {item.artifact_id} — grounding_posture=block "
            "and its advisory Review-1 grounding check flagged a `concern` (§6.5/§19); this item "
            "ABSTAINED from shipping (siblings continue)",
            stage_code=results.CODE_GROUNDING_UNCOVERED,
            remediation_action=None,
        )


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


def _platform_format_structural(
    env: CascadeEnv, platform: str, format_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """This platform's per-format HARD `format_structural` venue schema for THIS artifact's format
    (DR-4 C6/C8) + the schema floor `{}` — the §16 terminal structural-gate input.

    `format_structural` lives entirely OUTSIDE M2 (M2-EXCLUDED, the sibling of `hard_limits`), so it
    is read from the raw platform entry's `effective`, NEVER from the render resolution's bound
    values. SINGLE-ENTRY scoping is the C7→C8 identity obligation: only THIS `format_id`'s venue
    schema is threaded — `({format_id: <that C2 schema>}, {})` when the platform tightens this
    format, else `({}, {})`. An UNRELATED format's venue-tightening must never enter this fit's
    preimage (it would churn `fit_digest`), so the whole `format_structural` map is indexed down to
    the pinned format-id (matching C7's `_format_forbids` / reconcile's pinned-format resolution).
    The defaults are the schema floor `{}` (a floor `format_structural` contributes no `structural`
    preimage key and an INERT gate)."""
    entry = env.resolver.resolve("platforms", platform)
    all_structural = entry.effective.get("format_structural") or {}
    this_format = all_structural.get(format_id)
    if this_format is None:
        return {}, {}
    return {format_id: this_format}, {}


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
    # DR-4 C8: this artifact's pinned-format HARD venue structural class (SINGLE-ENTRY scoped —
    # an unrelated format's tightening never enters this fit's identity). `item.format` is the
    # format entry-id (the artifact-level dimension). M2-EXCLUDED, like `hard_limits`.
    format_structural, format_structural_defaults = _platform_format_structural(
        env, d.platform, item.format
    )

    # -- reconcile (§16): the demo binds `pass`, so a same-language fit is a ZERO-LLM
    #    passthrough; the terminal joint gate still runs (fit-or-block, never silent) — the
    #    hard-limit gate AND the DR-4 C8 venue-structural gate (INERT at a floor format).
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
            format_structural=format_structural,
            format_structural_defaults=format_structural_defaults,
        )
    )
    if rout.status != "ok" or rout.fitted_ir is None or rout.fit_binding is None:
        # HARD GATE-1 (§21.7): thread the reconcile stage's TRUE taxonomy code — GUARDED to
        # a real §21.7 code (`hard-limit-exceeded` on the terminal hard-limit block, or DR-4 C8's
        # `section-conformance-violation` on a venue-structural block — both `("block",)` in
        # `ALL_CODES`; else the typed non-taxonomy `fit-fidelity-violation`/transport codes stay
        # code-less, never fabricated, §3.1). Both concern-sets (`blocked_limits` +
        # `structural_violations`) ride the message. `session._generate_next` derives the block
        # STATUS from the code's CodeSpec (`("block",)`), never a hardcoded status.
        raise DriverError(
            f"driver-error: reconcile did not fit deliverable {d.deliverable_id} — "
            f"status={rout.status} code={rout.code} blocked_limits={rout.blocked_limits} "
            f"structural_violations={rout.structural_violations} violations={rout.violations}",
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
        # B (§17/step-29): the REAL filesystem asset loader replaces the deferred raise, FENCED to
        # `<root>/presentations` (F3, CLAUDE.md rule 2) — a css/csl/template path resolves against
        # `env.root` and must land inside `presentations/`, never a client `workspaces/…`.
        load_asset=filesystem_asset_loader(
            resolve_base=env.root, contain_root=env.root / "presentations"
        ),
        defaults=render.presentation.entry.defaults(),
    )
    render_inputs = _presentation.lower(
        pres, target.writer, d.output_type, target_engine=target.engine
    )
    # B (body-figure EMBED, F1/F5): compute the containment base ONCE — `store.root`, the SAME base
    # A's compose gate proved (asset_ref.py:13-19, S5). `hash_embedded_assets` re-runs A's FULL gate
    # on the persisted AST BEFORE any embed flag is emitted (an uncontained `../` or raw-`<img>`
    # body REFUSES here and is never opened), then returns the `(rel, hex)` fold for an html5/docx
    # figure; md/plain embed nothing → `()`. `resource_paths` is emitted ONLY when a figure embeds,
    # ordered store-root FIRST, repo-root (`env.root`) SECOND (a same-named framework asset can
    # never shadow the client figure); repo-root also resolves any repo-relative `--csl` a citing
    # render feeds.
    base = store.root
    embedded_assets = hash_embedded_assets(ast, target.writer, store_root=base)
    resource_paths = (str(base), str(env.root)) if embedded_assets else ()
    # C3 (S5 drift-catcher, asset_ref.py:13-19): pin guard base == hash base == resource_paths[0]
    # == store.root. A refactor that drifts B's base off `store.root` (e.g. to `store.root/assets`)
    # trips HERE at runtime AND in tests/test_asset_base_contract.py. No behavior change — the pin
    # holds today (empty when nothing embeds; else store-root FIRST, repo-root SECOND).
    assert resource_paths in ((), (str(store.root), str(env.root)))
    dout = dispatch(target, ast, render_inputs=render_inputs, resource_paths=resource_paths)
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
        render_target=target_values,
        render_inputs=render_inputs_view,
        section_attr_transformed=dout.section_attr_transformed,
        citeproc_enabled=dout.citeproc_enabled,
        # C7 (S3×S4): the csl asset (path, hash) — labeled on RenderInputs, kept OUT of the manual
        # `render_inputs_view` above. It enters the preimage's render_inputs ONLY when citeproc ran.
        csl=render_inputs.csl,
        # B (§17 FR7.1): the body-figure embed fold — the `asset_embed_version` pin + each embedded
        # figure's content hash enter the preimage ONLY when a figure embedded (an html5/docx
        # `assets/…` render). An image-less/md/plain render leaves them absent → byte-identical id.
        assets_embedded=bool(embedded_assets),
        embedded_assets=embedded_assets,
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
    bytes_path = store.bytes_path(d.deliverable_id, extension_for(d.output_type))
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
            "section_attr_transformed": dout.section_attr_transformed,
            "citeproc_enabled": dout.citeproc_enabled,
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
    # The publish set ANDs the two ORTHOGONAL gates at this ONE seam: the §6.5 confidence
    # floor (`publishable` — EXTRACTED tier, a framework invariant) AND the §6.1 rights gate
    # (`republishable` — the content-kind's reuse_rights clears `attribution`). With every
    # content-kind at the `full` floor this is byte-identical to `publishable_facts`; a
    # lead-only/internal-only/forbidden kind holds its EXTRACTED facts back as leads.
    published = tuple(f for f in outcome.publishable_facts if f.republishable)
    log(
        f"  ground: {len(outcome.facts)} fact(s), {len(published)} published "
        f"(EXTRACTED + republishable); commits {dict(outcome.commit_map)}"
    )
    if not published:
        # GAP-12: an empty `published` set has TWO distinct causes — split them so the operator
        # debugs the RIGHT axis (§6.5 tiers/anchoring vs §6.1 rights config), never guesses.
        # `published = publishable_facts (EXTRACTED) AND republishable`; so a non-empty
        # `publishable_facts` here ⇒ EXTRACTED facts EXIST but reuse_rights held them ALL back.
        if outcome.publishable_facts:
            raise DriverError(
                f"driver-error: grounding produced {len(outcome.publishable_facts)} EXTRACTED "
                f"fact(s) for {item.artifact_id}, but ALL were WITHHELD BY reuse_rights (leads "
                "only) — every publishable fact's content-kind clears BELOW the `attribution` "
                "republish threshold, so none may be republished as fact. Debug the source "
                "content-kind `reuse_rights` (§6.1 rights gate), NOT the confidence "
                "tiers/anchoring — the facts are correctly held as leads."
            )
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

    # C5: resolve the diagram-style `tool` knob (mixed-media amendment §2.K, Open Item O2). The
    # recipe's `diagram_style` ref (already validated loudly at M1 inside `resolve_compose`) selects
    # a diagram-style entry; an unset ref ("" floor) rides the framework `default` style (pinned
    # `dot`). The style's raw `tool` value (`dot`/`d2`/`auto`) is threaded onto the request; the
    # compose transform resolves `auto` -> a concrete installed tool LAZILY, only for an artifact
    # that actually carries a `{type=diagram}` section (so a diagram-free run never probes tools).
    diagram_style_id = compose.recipe.effective.get("diagram_style") or "default"
    diagram_style = env.resolver.resolve("diagram-styles", diagram_style_id)
    diagram_tool = diagram_style.effective.get("tool", diagram.TOOL_DOT)

    # C4b (DR-9): resolve the genre's `diagram_disposition` stance from the Format entry and thread
    # it onto the request (EXACTLY like `diagram_tool`). The per-artifact require/suppress GATE
    # reads it post-mint; the writer directives read the SAME value from `effective_values.format`.
    # The `""` floor (an unset Format) leaves the request byte-identical to the pre-C4b assembly.
    diagram_disposition = compose.format.values.get("diagram_disposition", "")

    # DR-3 (horn (a)): load the DRIVING outline brief from the pre-compose outline store by the
    # item's `outline-digest`. The digest already rode identity (item.preimage carries it); the
    # brief is the compose INPUT the digest-fidelity guard binds to that identity. An item that
    # claims an outline the store lacks is a loud wiring defect, never a silent skip (§3.1).
    outline_brief: str | None = None
    if item.outline_digest is not None:
        outline_brief = get_outline(store, item.outline_digest)
        if outline_brief is None:
            raise DriverError(
                f"driver-error: artifact {item.artifact_id} is driven by outline-digest "
                f"{item.outline_digest} but no such outline is in the store — ingest it before "
                "driving (DR-3 drive path); never a silent skip (§3.1)"
            )

    request = ComposeRequest(
        artifact_id=item.artifact_id,
        preimage=item.preimage,
        format_parts=format_parts,
        effective_values=_effective_values(compose),
        grounded_facts=published,
        source_repos=source_repos,
        outline_brief=outline_brief,
        # DR-2: ONE resolution, TWO consumers. The lexicon `EntryBinding` resolved above
        # (`compose.lexicon`) fed the artifact preimage at plan time (its id rides
        # `item.preimage["lexicon"]["entry"]`); HERE the SAME binding's resolved ATTRIBUTES
        # feed the prompt-only house-style block — so the compose-context lexicon is provably
        # the same entry whose id is in the preimage. None -> no block (omit-when-absent).
        lexicon=compose.lexicon.effective if compose.lexicon is not None else None,
        # C5: the resolved diagram-style tool (replaces the C4 hard-pin). Byte-identical to the
        # pre-C5 default when the recipe selects no style (the `default` style pins `dot`).
        diagram_tool=diagram_tool,
        # C4b (DR-9): the resolved genre diagram_disposition stance (default "" = neutral). The
        # per-artifact gate acts on the HARD members (`require`/`suppress`) post-mint.
        diagram_disposition=diagram_disposition,
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
    if cout.status != "ok":
        raise DriverError(
            f"driver-error: compose did not persist artifact {item.artifact_id} — "
            f"status={cout.status} code={cout.code} attempts={cout.attempts} "
            f"violations={cout.violations}"
        )
    if cout.ir is None:
        # GAP-1d idempotent re-drive (§21.8): compose short-circuited on an already-materialized
        # artifact (`status="ok", ir=None`, the TOTAL discriminator — a fresh success returns
        # `ir=doc`, transport/exhaustion carry `status="error"`, and this branch fires only under
        # `is_done`), so LOAD the stored canonical IR and continue to the serialize legs — a
        # re-drive re-serializes, it NEVER re-composes. The old guard hard-blocked this no-op (it
        # raised on `ir is None`). NEW-F: guard the load — a record that vanished/corrupted between
        # compose's `is_done` check and here is a clear DriverError, never `ir.unwrap_ir(None)`.
        stored = _read_stored_record(store, item.artifact_id)
        if stored is None:
            raise DriverError(
                f"driver-error: artifact {item.artifact_id} reported already-materialized "
                f"({cout.code}) but its stored record is missing or corrupt — cannot re-drive the "
                "serialize legs (§21.8/§22.3)"
            )
        canonical_ir = ir.unwrap_ir(stored)
    else:
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
    # F1 (§21.9 observability, GAP-6): SURFACE a RECOVERED derail on the SUCCESS path — attempt-1
    # failed the contract (a refusal, or the §15 substance floor) and the bounded re-ask recovered
    # it (`status="ok", attempts>1, violations=(…)`). Today this signal is discarded here; the
    # maintainer's "log every re-ask" requirement covers the RECOVERED case, so the derail RATE
    # (recovered included) is observable, not silently swallowed. The idempotent no-op
    # (`attempts=0, violations=()`) correctly does NOT emit.
    if cout.attempts > 1 or cout.violations:
        log(
            f"  compose: RE-ASK ×{cout.attempts} recovered — violations={list(cout.violations)}"
        )
    # §19 Review 1 rode inside compose_artifact (post-mint, advancing `artifact-reviewed`).
    review = cout.review
    if review is not None:
        log(f"  review: artifact {review.code} verdict={review.verdict}")

    # DR-6 (§6.5/§19; D1, §2.4): under grounding_posture=block ONLY, ABSTAIN when this item's
    # PERSISTED Review-1 record shows an advisory `grounding` concern — FAIL-OPEN when the record is
    # absent/partial (ships, identical on re-drive). Default `warn` (today's behavior) never fires.
    _grounding_abstain_check(store, item)

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
    user: str,
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

    env = CascadeEnv(root, user=user, workspace=workspace)

    # -- source pool + the pinned commit-map (§7.2): read the graph's commit BY PATH.
    source_ids = _list_source_ids(root, user, workspace)
    if not source_ids:
        raise DriverError(
            f"driver-error: workspace {workspace!r} declares no source instances under "
            "users/<user>/workspaces/<ws>/sources/ — grounding needs a source pool (§6.1)"
        )
    pool = build_pool(env.resolver, source_ids)
    # Build the adapter set FIRST so the commit-map is pinned through the SAME provenance
    # read grounding uses (CF-1): `_pin_source_commit` delegates to `adapter.pin_commit`.
    adapters: dict[str, SourceAdapter] = default_adapters()
    source_commit: dict[str, str] = {}
    source_repos: dict[str, str] = {}
    for inst in pool:
        source_repos[inst.id] = _source_repo_for(inst.id, inst.connection)
        commit = _pin_source_commit(adapters.get(inst.adapter), inst.connection)
        if commit is not None:
            source_commit[inst.id] = commit
    # N2 HEAD-FREEZE (mechanism (a)): thread each plan-time pinned commit BACK into the
    # connection the drive-time `ground()` reads, so a HEAD-mode cache source grounds the PINNED
    # slice — not a mid-session-advanced HEAD. A no-op for graphify/folder/fsast (unchanged
    # identity); the pin (and thus every artifact-id) is untouched (CF-1).
    pool = _freeze_pool(pool, adapters, source_commit)
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

    # -- the store, claims, and SSOT under the workspace (rule 2; instance data). `.at()` records
    #    the (user, workspace) identity so depth-robust framework-root recovery holds (§23).
    store = WorkspaceStore.at(root, user, workspace)
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
        user=user,
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
