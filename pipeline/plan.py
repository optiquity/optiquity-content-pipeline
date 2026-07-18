"""Plan resolution (design §8, §21.6, §22.2): the deterministic complete item set + `plan_hash`.

Design authority: `docs/design.md`
  §8     — content fanout → artifacts; rendering fanout → deliverables; every item
           id-keyed, commit-pinned, idempotent (§7). No hard compatibility filter (Q4):
           the emergent allow-list is what the cascade resolves; the only pairing
           machinery here is the ONE-TIME advisory `nonsensical-pairing` warn and the
           goal-set-overload warn — never a block, never a veto.
  §21.6  — the plan is re-resolved from its inputs by "a pure, deterministic, LLM-FREE
           function" — this module's `resolve_plan`: same inputs → the same plan and the
           same `plan_hash`, in any process; a mid-session config edit that changes the
           plan changes the hash (the `plan-stale` guard value — the TOKEN layer that
           compares hashes lands with the API steps).
  §22.2  — **the plan is a deterministic, exactly-once cover (PC2)**: keyed by settled
           ids, disjoint by construction; a missed item is detectable by re-resolve +
           diff (`plan_payload`/`artifact_ids`/`deliverable_ids` support exactly that).
           v1 exposes two levels: compose items keyed by `artifact-id`, render items
           keyed by `deliverable-id` (the full wave/prereqs/shard structure lands at
           plan step 36 per the reconciled plan).
  §7.1/§7.2 — identity: the artifact preimage assembles from the M2-compose effective
           deltas + the pinned source-subset + commit-map, minted via `pipeline.ids`
           (step-10 machinery, imported, never duplicated); fitted/deliverable ids
           extend it structurally (§7.4).
  §12.5  — overrides' effects are captured in identity via the effective deltas (CA6);
           this module adds NO injection point — it consumes `CascadeEnv` (collect-once,
           CA7) and the M2 resolvers as-is.
  §21.8 (Q17) — **the M3 selection expression is NOT an identity input**: the effective
           selection RIDES each plan item (for the grounding stage) but never enters the
           preimage — two resolutions differing only in selection clauses yield
           identical artifact-ids.
  §22.7  — boundary: plan resolution is coordinate resolution — it reads config +
           registries ONLY (via `CascadeEnv`/M1); no output store, no claims, no SSOT
           import, structurally.

In-latitude decisions (step-19 coder; grounded in the report):

- **Recipe-layer M3 arrives run-side (the step-17 carry-forward, decided here):** the
  shipped recipes `_schema.yaml` carries no `source_selection` (ratified step-15 scope)
  and is NOT extended: SV11's cross-collection `schema_version` equality makes even an
  additive recipes-only change a multi-file blast radius outside this step's scope, and
  §12.1 fixes the LAYER ORDER, not the carrier. The mechanism of record:
  `resolve_plan(recipe_selection=…)` supplies the recipe layer to
  `resolve_selection(recipe=…)`; `run_selection=…` supplies the run layer. Carrier
  choice churns nothing (Q17: M3 is not an identity input); a future persisted carrier
  remains one additive §11.5 schema change + one plumbing line here.
- **The no-platform advisory (the step-16 RV-1 carry-forward, decided here): WARN.**
  When a plan resolves compose-only (zero deliverables — no platform anywhere) while
  platform.* value bindings are configured at L2/L3/L5, those bindings are inert; the
  plan surfaces the one-time `inert-platform-configuration` warning naming them —
  surfaced, never silent (§3.1; Q3 surface-don't-bend), warn-only, never a block (Q4:
  the plan still resolves and the config is untouched). L6 platform overrides already
  refuse loudly in the cascade (§21.4); this covers the persistent rungs.
- **`plan_hash` = the full SHA-256 over the canonical plan payload** (`plan_payload`):
  items sorted by `artifact-id`, deliverables by `deliverable-id` — the cover is keyed
  by settled ids (PC2), so a permuted REQUEST yields the identical plan and hash, while
  any input that changes the resolved plan (selection, config, pins, commit-map, or an
  M3 clause) changes it. The M3 payload is INCLUDED: a mid-session clause edit changes
  what the plan will ground, and §21.6's `plan-stale` exists to surface exactly such
  edits — ids stay untouched (Q17), the hash honestly moves.
- **Fanout collapse dedupes with a warning:** distinct combinations can resolve to ONE
  preimage (the §12.6 brand-`c` hard-lock beating different run voices). The plan
  carries the item once (PC2 exactly-once), verified by the §7.4 preimage check
  (identical preimages = the same designed item; different preimages under one id =
  loud `PreimageMismatchError`), and surfaces a one-time `fanout-collapse` warning
  (§3.1: never a silent drop).
- **Warnings aggregate deduped by stable key** across compose/render/M3/lint sources —
  the §8 "one-time" semantics; cascade-emitted warnings are already once-per-`env`
  (session-scoped), lint warnings ride `env.warn` with stable keys, M3 relax warnings
  dedupe at aggregation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.canonical import digest_full
from pipeline.cascade import (
    CascadeEnv,
    ComposeResolution,
    RunSelection,
    ValueBinding,
    parse_value_bindings,
    resolve_compose,
    resolve_render,
)
from pipeline.fanout import (
    ContentCombination,
    RenderCoordinate,
    SelectionRequest,
    content_combinations,
    goal_set_overloaded,
    pairing_advisory,
    render_coordinates,
)
from pipeline.ids import deliverable_id, fitted_id, mint_artifact_id, preimage_check
from pipeline.m1 import ResolutionWarning
from pipeline.m3 import EffectiveSelection, render_clause, resolve_selection

__all__ = [
    "DeliverableItem",
    "Plan",
    "PlanError",
    "PlanItem",
    "plan_payload",
    "resolve_plan",
    "selection_payload",
]


class PlanError(ValueError):
    """A plan-resolution defect — loud, typed, never repaired (§3.1)."""

    code = "invalid-plan"


@dataclass(frozen=True)
class DeliverableItem:
    """One render-level plan item (§8 rendering fanout; §22.2: keyed by `deliverable-id`).

    Coordinates are the RESOLVED entry ids (an unselected slot resolves via the §12.3
    rungs before the id is minted, so the id names the concrete coordinate, never a
    default marker). `reconcile_strategy` is the M2-bound render attribute the §16 gate
    consumes — per-item because the per-(format × platform) table differs per artifact.
    """

    deliverable_id: str
    fitted_id: str
    platform: str
    language: str
    output_type: str
    presentation: str
    reconcile_strategy: str


@dataclass(frozen=True)
class PlanItem:
    """One compose-level plan item (§8 content fanout; §22.2: keyed by `artifact-id`).

    `preimage` is the canonical §7.2 preimage (what the IR binding records and the S0
    preimage check reads back, §7.4/§22.3). `m3` is the effective §6.3 selection this
    item grounds under — riding the plan, NEVER the preimage (Q17, §21.8).
    """

    artifact_id: str
    preimage: Mapping[str, Any]
    topic: str
    persona: str
    format: str
    voice: str
    #: The sorted, deduped resolved goal-set (§7.2 canonical order).
    goals: tuple[str, ...]
    m3: EffectiveSelection
    deliverables: tuple[DeliverableItem, ...]


@dataclass(frozen=True)
class Plan:
    """The §21.6/§22.2 plan: the deterministic complete item set + `plan_hash`.

    Items are sorted by `artifact-id`, deliverables by `deliverable-id` — the plan is
    canonical in itself (PC2: keyed by settled ids), so equality of `plan_hash` is
    equality of the plan.
    """

    workspace: str
    recipe: str
    source_subset: tuple[str, ...]
    source_commit: Mapping[str, str]
    items: tuple[PlanItem, ...]
    plan_hash: str
    warnings: tuple[ResolutionWarning, ...]

    def artifact_ids(self) -> tuple[str, ...]:
        """The wave-0 cover keys (§22.2; re-resolve + diff detects a missed item)."""
        return tuple(item.artifact_id for item in self.items)

    def deliverable_ids(self) -> tuple[str, ...]:
        """The wave-1 cover keys (§22.2), across all items."""
        return tuple(d.deliverable_id for item in self.items for d in item.deliverables)


# --- Canonical payloads (the plan-hash preimage; §21.6) -------------------------------------


def selection_payload(selection: EffectiveSelection) -> dict[str, Any]:
    """The canonical JSON projection of one effective M3 selection (§6.3).

    Clauses render via their canonical §6.3 surface (`render_clause`); prefer terms as
    `[key, weight]` pairs in fold order; span as axis → member list. Deterministic for
    identical folded inputs — the plan-hash carrier for the M3 lane (rides the plan,
    never the preimage; Q17).
    """
    return {
        "require": [render_clause(clause) for clause in selection.require],
        "span": {axis: list(members) for axis, members in selection.span.items()},
        "prefer": [[term.term.key, term.weight] for term in selection.prefer],
        "on_conflict": selection.on_conflict,
        "grounding_posture": selection.grounding_posture,
    }


def _deliverable_payload(item: DeliverableItem) -> dict[str, Any]:
    return {
        "deliverable-id": item.deliverable_id,
        "fitted-id": item.fitted_id,
        "platform": item.platform,
        "language": item.language,
        "output-type": item.output_type,
        "presentation": item.presentation,
        "reconcile-strategy": item.reconcile_strategy,
    }


def _item_payload(item: PlanItem) -> dict[str, Any]:
    return {
        "artifact-id": item.artifact_id,
        # The FULL preimage digest (§7.4: the id carries its hex16 truncation; the full
        # digest is the recorded form) — any preimage change moves the plan hash.
        "preimage-digest": digest_full(item.preimage),
        "coordinates": {
            "topic": item.topic,
            "persona": item.persona,
            "format": item.format,
            "voice": item.voice,
            "goals": list(item.goals),
        },
        "m3": selection_payload(item.m3),
        "deliverables": [_deliverable_payload(d) for d in item.deliverables],
    }


def _payload(
    workspace: str,
    recipe: str,
    source_subset: Sequence[str],
    source_commit: Mapping[str, str],
    items: Sequence[PlanItem],
) -> dict[str, Any]:
    return {
        "workspace": workspace,
        "recipe": recipe,
        "source-subset": sorted(source_subset),
        "source-commit": dict(source_commit),
        "items": [_item_payload(item) for item in items],
    }


def plan_payload(plan: Plan) -> dict[str, Any]:
    """The canonical plan payload: `digest_full(plan_payload(plan)) == plan.plan_hash`.

    The token layer's `plan-stale` comparison (§21.6/§22.6, later steps) and the PC2
    re-resolve + diff both consume this canonical structure.
    """
    return _payload(plan.workspace, plan.recipe, plan.source_subset, plan.source_commit, plan.items)


# --- The resolve (§21.6: pure, deterministic, LLM-free) ------------------------------------


class _WarningLog:
    """Ordered aggregation, deduped by stable key (§8 one-time semantics)."""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._ordered: list[ResolutionWarning] = []

    def add(self, warning: ResolutionWarning | None) -> None:
        if warning is not None and warning.key not in self._seen:
            self._seen.add(warning.key)
            self._ordered.append(warning)

    def extend(self, warnings: Sequence[ResolutionWarning]) -> None:
        for warning in warnings:
            self.add(warning)

    def collected(self) -> tuple[ResolutionWarning, ...]:
        return tuple(self._ordered)


def _content_selection(recipe: str, combo: ContentCombination) -> RunSelection:
    return RunSelection(
        recipe=recipe,
        topic=combo.topic,
        persona=combo.persona,
        format=combo.format,
        voice=combo.voice,
        goals=combo.goals,
    )


def _render_selection(recipe: str, coordinate: RenderCoordinate) -> RunSelection:
    return RunSelection(
        recipe=recipe,
        platform=coordinate.platform,
        language=coordinate.language,
        output_type=coordinate.output_type,
        presentation=coordinate.presentation,
    )


def _resolve_deliverables(
    env: CascadeEnv,
    request: SelectionRequest,
    compose: ComposeResolution,
    artifact_id: str,
    coordinates: Sequence[RenderCoordinate],
    log: _WarningLog,
) -> tuple[DeliverableItem, ...]:
    """The rendering fanout for one artifact (§8): one deliverable per coordinate set."""
    deliverables: dict[str, DeliverableItem] = {}
    for coordinate in coordinates:
        render = resolve_render(env, compose, _render_selection(request.recipe, coordinate))
        log.extend(render.warnings)
        if render.platform is None:  # structurally unreachable: coordinates carry a platform
            raise PlanError(
                f"invalid-plan: coordinate {coordinate!r} resolved platform-less — a "
                "deliverable requires routing (§12.3/§7.4)"
            )
        platform_id = render.platform.entry_id
        fitted = fitted_id(artifact_id, platform_id, render.language.entry_id)
        deliverable = deliverable_id(
            fitted, render.output_type.entry_id, render.presentation.entry_id
        )
        if deliverable in deliverables:  # defense-in-depth: PC2 exactly-once cover
            raise PlanError(
                f"invalid-plan: deliverable {deliverable!r} resolved twice in one plan — "
                "the plan is an exactly-once cover (PC2, §22.2)"
            )
        # §8: the one-time ADVISORY pairing lint — warn, never block, never a veto (Q4).
        trigger = pairing_advisory(compose.format.entry_id, platform_id)
        if trigger is not None:
            log.add(
                env.warn(
                    f"nonsensical-pairing:{trigger.format}:{trigger.platform}",
                    (
                        f"nonsensical-pairing (advisory, §8): format {trigger.format!r} "
                        f"paired with platform {trigger.platform!r} — {trigger.rationale}; "
                        "the pairing is honored (no hard compatibility filter, Q4)"
                    ),
                )
            )
        deliverables[deliverable] = DeliverableItem(
            deliverable_id=deliverable,
            fitted_id=fitted,
            platform=platform_id,
            language=render.language.entry_id,
            output_type=render.output_type.entry_id,
            presentation=render.presentation.entry_id,
            reconcile_strategy=render.reconcile_strategy,
        )
    return tuple(deliverables[key] for key in sorted(deliverables))


def _inert_platform_bindings(env: CascadeEnv, recipe_values: Sequence[ValueBinding]) -> list[str]:
    """The configured L2/L3/L5 `platform.*` value bindings (the step-16 RV-1 surface)."""
    configured = (*env.global_defaults.values, *env.workspace_defaults.values, *recipe_values)
    return [
        f"{binding.where} (platform.{binding.attribute})"
        for binding in configured
        if binding.dimension == "platform"
    ]


def resolve_plan(
    env: CascadeEnv,
    request: SelectionRequest,
    *,
    source_subset: Sequence[str],
    source_commit: Mapping[str, str],
    recipe_selection: Mapping[str, Any] | None = None,
    run_selection: Mapping[str, Any] | None = None,
) -> Plan:
    """Resolve one request to the complete plan — the §21.6 pure function.

    Pure in its inputs: the collected env (config + registries, CA7), the request, the
    pinned source-subset + commit-map (§7.2/§21.8 — captured or supplied at
    `begin-session` by later steps), and the optional recipe-/run-layer M3 maps (§12.1;
    supplied run-side — see the module docstring). Deterministic and LLM-free: same
    inputs → the identical plan and `plan_hash` in any process; reads config +
    registries only — never the output store, never the SSOT (§22.7).
    """
    log = _WarningLog()
    recipe_entry = env.resolver.resolve("recipes", request.recipe)
    recipe_values = parse_value_bindings(
        recipe_entry.effective.get("values"), where=f"recipes/{recipe_entry.id}"
    )
    coordinates = render_coordinates(
        request,
        pinned_platforms=tuple(recipe_entry.effective.get("platforms") or ()),
        pinned_languages=tuple(recipe_entry.effective.get("languages") or ()),
        pinned_output_types=tuple(recipe_entry.effective.get("output_types") or ()),
        pinned_presentations=tuple(recipe_entry.effective.get("presentations") or ()),
    )

    items: dict[str, PlanItem] = {}
    for combo in content_combinations(request):
        compose = resolve_compose(env, _content_selection(request.recipe, combo))
        log.extend(compose.warnings)
        preimage = compose.artifact_preimage(
            source_subset=source_subset, source_commit=source_commit
        )
        artifact_id = mint_artifact_id(preimage)
        goals = tuple(sorted(goal.entry_id for goal in compose.goals))
        if goal_set_overloaded(goals):
            # §8: goal-set overload warns, never blocks.
            log.add(
                env.warn(
                    f"goal-set-overload:{','.join(goals)}",
                    (
                        f"goal-set {list(goals)!r} stacks {len(goals)} goals into one "
                        "artifact — likely overloaded (advisory, §8; warned once, "
                        "never blocked)"
                    ),
                )
            )
        if artifact_id in items:
            # Distinct combinations collapsing to ONE designed item (e.g. the §12.6
            # brand-c hard-lock): verify same-preimage (loud on mismatch, §7.4) and
            # carry the item exactly once (PC2) — surfaced, never silent (§3.1).
            preimage_check(artifact_id, preimage, items[artifact_id].preimage)
            log.add(
                env.warn(
                    f"fanout-collapse:{artifact_id}",
                    (
                        f"two selection combinations resolve to one artifact "
                        f"({artifact_id}) — carried once (exactly-once cover, PC2/§22.2)"
                    ),
                )
            )
            continue
        # The M3 lane (§12.1 four layers): rides the plan item, never the preimage (Q17).
        m3 = resolve_selection(
            workspace=compose.m3_inputs.workspace_baseline,
            goals=compose.m3_inputs.goal_implied,
            recipe=recipe_selection,
            run=run_selection,
        )
        log.extend(m3.warnings)
        items[artifact_id] = PlanItem(
            artifact_id=artifact_id,
            preimage=preimage,
            topic=compose.topic.entry_id,
            persona=compose.persona.entry_id,
            format=compose.format.entry_id,
            voice=compose.voice.entry_id,
            goals=goals,
            m3=m3,
            deliverables=_resolve_deliverables(
                env, request, compose, artifact_id, coordinates, log
            ),
        )

    if not coordinates:
        # The step-16 RV-1 decision: a compose-only plan with configured platform.*
        # bindings surfaces them as inert — one-time, warn-only (§3.1/Q3; never a
        # block, Q4). See the module docstring.
        inert = _inert_platform_bindings(env, recipe_values)
        if inert:
            log.add(
                env.warn(
                    f"inert-platform-configuration:{env.workspace}",
                    (
                        "this plan resolves no platform-routed deliverable, so the "
                        f"configured platform value binding(s) {inert} are inert for "
                        "every item (surfaced per §3.1; advisory only — nothing is "
                        "blocked or changed)"
                    ),
                )
            )

    ordered = tuple(items[key] for key in sorted(items))
    payload = _payload(env.workspace, request.recipe, source_subset, source_commit, ordered)
    return Plan(
        workspace=env.workspace,
        recipe=request.recipe,
        source_subset=tuple(sorted(source_subset)),
        source_commit=dict(source_commit),
        items=ordered,
        plan_hash=digest_full(payload),
        warnings=log.collected(),
    )
