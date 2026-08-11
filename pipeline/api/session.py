"""The session/generation half of the external-actor API (§20, §21) — `begin-session`
and `continue-session`, on top of step-32's already-complete contract (invoke, workspace
isolation, the token, the result taxonomy).

Design authority: `docs/design.md`
  §20    — the pure-function run contract: session state is EPHEMERAL and actor-held; the
           system persists none of it. The token is the documented cursor carrying the
           plan_hash, the run inputs, the cursor, the produced ids, and the target folio
           ref (ids only). `begin-session` MINTS it; `continue-session` CONSUMES + RETURNS.
  §21.1  — the token is a CURSOR, not a capability gate; every call carries `workspace` and
           isolation is enforced by the API, not by trust.
  §21.2  — the CLOSED continue-session action vocabulary (API2): exactly `generate-next`,
           `render`, `add-to-folio`, `emit-manifest`, `fetch`, `status`, `list`/`get`. An
           action outside the set → `unknown-action`. Overrides are NOT an action — they are
           fixed at `begin-session` for the whole plan (§12.5; changing them = a new session).
  §21.4  — run-layer overrides bind at `begin-session` only, under the hard M1 guard
           (`invalid-override`); they ride L6 → M2 bind and enter identity (§7.2).
  §21.6  — batching: `begin-session` defaults to plan-only (`generate = none`);
           `generate-next` composes `batch_size` items per call. The plan is RE-RESOLVED
           each call from the token's inputs (a pure, LLM-free function — never a cached
           plan); a re-resolve whose `plan_hash` ≠ the token's surfaces `plan-stale` (§22.6),
           never a silent skip or dup. The cursor keys on item COORDINATES, not indexes.
  §21.8  — idempotency by construction: `generate-next` is idempotent on `artifact-id`
           EXISTENCE (an already-materialized id is a no-op `already-materialized`, never
           regenerated); the source commit-map is fixed at `begin-session` (captured, or
           supplied via the `[pins]` slot), so a later resume reproduces identical ids.
  §22.7  — this is an ORCHESTRATOR layer (like `pipeline.driver`), NOT an INV-CORRECTNESS
           root: it MAY import `ssot`/`driver`. It honors §22.7 all the same — it never
           BRANCHES on an SSOT read; the SSOT advances ride the driver's write-only S5 hooks.
           Idempotency reads OUTPUT EXISTENCE (`store`/`is_done`), never the SSOT, never the
           token (the token is a cursor, not a correctness boundary).
  §22.2/§22.4/§22.5 — `begin-session(want_parallel_plan=true)` hands back the WAVE PLAN
           (`pipeline.parallel.build_wave_plan`): wave 0 compose (keyed by artifact-id), wave 1
           render (keyed by deliverable-id), each unit carrying `prereqs`/`shard`, plus
           `suggested_width` and the ADVISORY `recommended_width` from the content-free
           telemetry window (`pipeline.telemetry`, never auto-applied). No new verb (PC6); the
           token is UNCHANGED — an immutable plan-context under parallel mode (workers
           coordinate via the store/claims, never by mutating it). `status` exposes the §22.3
           completeness SWEEP (the wave barrier) read from MATERIALIZED ids only (store-only,
           ssot-free) — `pipeline.parallel` is the ssot-free correctness root that computes it.

**Isolation is enforced by the API gate (ONE authoritative path).** continue-session's ids
are ACTION-nested (`render.item`, `add-to-folio` members/`folio_id`, `fetch.id`,
`emit-manifest.folio_id`, `get.id`); the invoke gate isolates them uniformly by mapping each
action to its mirror VERB's id extractor (`invoke._extract_continue_session`), so a
cross-workspace nested id is refused `isolation-violation` WHOLE-INVOCATION-fatally
(`ok=False`) — exactly like the standalone verb path (§21.7/§21.1), and the action never
reaches a stage. This handler holds NO isolation branch of its own: exactly ONE enforcement
path, no dead or contradictory code.

**The closed vocabulary is FULLY wired (step 35 — the capstone).**
`render`/`fetch`/`add-to-folio`/`list`/`get`/`emit-manifest` each delegate to their standalone
verb handler (`pipeline.api.render`/`fetch`/`folio_verbs`/`discovery`/`manifest`), which owns the
real logic; the continue-session action path and the standalone verb path share ONE implementation
(contract parity, §21.1). The delegated handler receives the SAME already-gated `HandlerContext`
(its ids sit flat alongside `action`), and the session ECHOES the token unchanged (these actions
are read/side-outputs, not cursor advances — like `status`; `emit-manifest` is a READ/PLAN that
mints nothing, §21.5). No action is a `NotYetWired` stub anymore — step 35 retired the last one and
closed the honest empty seam step 32 opened; `tests/test_action_completeness.py` asserts every
`CONTINUE_ACTIONS` member dispatches to a REAL handler.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pipeline import compose, driver, parallel, telemetry
from pipeline.adapters import default_adapters
from pipeline.adapters.base import AdapterError, SourceAdapter
from pipeline.api import discovery, fetch, folio_verbs, manifest, render, results
from pipeline.api import invoke as invoke_mod
from pipeline.api import token as token_mod
from pipeline.canonical import canonical_json_str
from pipeline.cascade import CascadeEnv, RunSelection, SelectionError, resolve_compose
from pipeline.compose import build_outline_ir
from pipeline.fanout import (
    FanoutError,
    SelectionRequest,
    coordinate_from_payload,
    coordinate_payload,
    render_coordinate_from_payload,
    render_coordinate_payload,
)
from pipeline.folios import FolioError, create_folio
from pipeline.grounding import build_pool
from pipeline.ids import PreimageError, mint_artifact_id
from pipeline.m1 import UnknownEntryError
from pipeline.outline import OutlineError, normalize_outline
from pipeline.outline_store import put_outline
from pipeline.overrides import OverrideError
from pipeline.plan import Plan, resolve_plan
from pipeline.spine import registry_for
from pipeline.ssot import Ssot
from pipeline.store import is_done

__all__ = [
    "CONTINUE_ACTIONS",
    "NotYetWired",
    "begin_session_handler",
    "continue_session_handler",
    "emit_outline_handler",
    "plan_next_batch_ids",
    "register_api_handlers",
    "register_emit_outline_handler",
    "register_session_handlers",
]

#: §21.2 (API2): the CLOSED continue-session action vocabulary. Anything else → the
#: `unknown-action` result code. Discoverable via `list actions` (§21.3) — the single source
#: `pipeline.api.discovery` reads at wiring, so a change here flows there with no second edit.
CONTINUE_ACTIONS = frozenset(
    {"generate-next", "render", "add-to-folio", "emit-manifest", "fetch", "status", "list", "get"}
)

#: `begin-session(target_folio=…)` sentinels (§21.1).
TARGET_FOLIO_NONE = "none"
TARGET_FOLIO_AUTO = "auto"

#: §21.6 "default small" — one item per `generate-next` unless `batch_size` says otherwise.
_DEFAULT_BATCH_SIZE = 1


def _nolog(_message: str) -> None:
    """A silent driver log sink — generation stage lines are not surfaced on the wire."""


class NotYetWired(RuntimeError):
    """INTERNAL, DEFENSIVE seam: a KNOWN continue-session action reached dispatch with no wired
    handler. After step 35 the closed vocabulary is FULLY wired — `generate-next`/`status` inline,
    the rest (`render`/`fetch`/`add-to-folio`/`list`/`get`/`emit-manifest`) delegate — so NO current
    action raises this (`tests/test_action_completeness.py` proves it). It survives only to trip an
    honest, loud failure if a FUTURE action is added to `CONTINUE_ACTIONS` without a handler, rather
    than misdispatch or fabricate a success — the action-level sibling of `invoke.HandlerNotWired`.
    """

    def __init__(self, action: str) -> None:
        super().__init__(
            f"action-not-yet-wired: continue-session action {action!r} is in the closed "
            "vocabulary but its handler is not wired yet (lands at a later build step)"
        )
        self.action = action


# ---------------------------------------------------------------------------
# Shared plan resolution (§21.6: a pure, deterministic, LLM-free function).
# ---------------------------------------------------------------------------


def _root_of(store: Any) -> Path:
    """The framework root for a workspace store — the dir the §5 registries +
    `instance/defaults.yaml` live under (`CascadeEnv` reads them there). Reads the store's
    RECORDED identity (`.at(...)` sets it), never depth-fragile positional path math (§23)."""
    return store.framework_root


def _telemetry_log(root: Path) -> telemetry.TelemetryLog:
    """The instance-scoped telemetry log under `instance/ops/` (§22.5/§23) — content-free,
    gitignored-in-public. Read here only for the advisory `recommended_width` (never a
    correctness read)."""
    return telemetry.TelemetryLog(root / "instance" / "ops" / "telemetry.jsonl")


def _parallel_plan_context(root: Path, plan: Plan) -> dict[str, Any]:
    """The §22.2 wave-plan block for `begin-session(want_parallel_plan=true)` (§22.4).

    Returns the wave plan (waves × units with `prereqs`/`shard`), `suggested_width` (§22.5),
    and the ADVISORY `recommended_width` from the recent telemetry window — never auto-applied
    (§22.5); the user's cap stays authoritative. `parallel_mode` flags that the returned token
    is an IMMUTABLE plan-context: parallel workers coordinate through the store/claims, NEVER by
    mutating the token (§22.4)."""
    wave_plan = parallel.build_wave_plan(plan)
    advisory = telemetry.recommend_width(_telemetry_log(root), cap=wave_plan.instance_cap)
    return {
        "parallel_mode": True,
        "parallel_plan": parallel.wave_plan_payload(wave_plan),
        "suggested_width": wave_plan.suggested_width,
        "recommended_width": advisory.recommended_width,
        "recommended_width_below_cap": advisory.below_cap,
        "recommended_width_basis": advisory.basis,
    }


def _default_adapters() -> dict[str, SourceAdapter]:
    """The real source-adapter set (grounding + the §7.2 commit pin via `pin_commit`) —
    delegates to the single registration point so `graphify` + `folder` (and any future
    adapter) resolve identically through the API and the driver."""
    return default_adapters()


def _outlines_from_fields(raw: Any) -> list[tuple[Any, str]]:
    """The DR-3 drive map from the request payload (§20): a list of
    `{"coordinate": {...}, "outline_digest": <64hex>}` entries -> a list of
    `(ContentCombination, digest)` pairs `SelectionRequest` normalizes (a duplicate coordinate
    stays loud there — the list keeps both). Absent/empty -> `[]` (outline-less; byte-identical
    to today). Round-trips with `_request_payload`."""
    if not raw:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise FanoutError(
            "invalid-selection: `outlines` must be a list of {coordinate, outline_digest} "
            f"entries (DR-3 drive map), got {type(raw).__name__}"
        )
    pairs: list[tuple[Any, str]] = []
    for entry in raw:
        if (
            not isinstance(entry, Mapping)
            or "coordinate" not in entry
            or "outline_digest" not in entry
        ):
            raise FanoutError(
                "invalid-selection: each `outlines` entry is "
                "{coordinate: {...}, outline_digest: <64hex>} (DR-3), got "
                f"{entry!r}"
            )
        pairs.append((coordinate_from_payload(entry["coordinate"]), entry["outline_digest"]))
    return pairs


def _render_map_from_fields(raw: Any) -> list[tuple[Any, Any]]:
    """The CLI-UX C5c saved-selection DRIVE map from the request payload (§20): a FLAT list of
    `{"coordinate": {...}, "render": {...}}` variants -> a list of `(ContentCombination,
    RenderCoordinate)` pairs `SelectionRequest` GROUPS by content coord (a same-(content, render)
    duplicate stays loud there). Round-trips with `_request_payload`. Absent/empty -> `[]` (a normal
    cartesian request; byte-identical to a non-driven session)."""
    if not raw:
        return []
    if not isinstance(raw, Sequence) or isinstance(raw, str | bytes):
        raise FanoutError(
            "invalid-selection: `render_map` must be a list of {coordinate, render} variants "
            f"(the C5c saved-selection DRIVE), got {type(raw).__name__}"
        )
    pairs: list[tuple[Any, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or "coordinate" not in entry or "render" not in entry:
            raise FanoutError(
                "invalid-selection: each `render_map` item is {coordinate: {...}, render: {...}} "
                f"(C5c), got {entry!r}"
            )
        pairs.append(
            (
                coordinate_from_payload(entry["coordinate"]),
                render_coordinate_from_payload(entry["render"]),
            )
        )
    return pairs


def _request_from_fields(fields: Mapping[str, Any]) -> SelectionRequest:
    """Build a `SelectionRequest` from a recipe + per-axis multi-selects (§8) + the DR-3
    per-coordinate outline drive map (`outlines`) + the CLI-UX C5c saved-selection DRIVE map
    (`render_map` — the explicit fan-out replayed 1:1, grouped by content coordinate)."""
    return SelectionRequest(
        recipe=fields.get("recipe", ""),
        topics=tuple(fields.get("topics") or ()),
        personas=tuple(fields.get("personas") or ()),
        formats=tuple(fields.get("formats") or ()),
        voices=tuple(fields.get("voices") or ()),
        goal_sets=tuple(tuple(gs) for gs in (fields.get("goal_sets") or ())),
        platforms=tuple(fields.get("platforms") or ()),
        languages=tuple(fields.get("languages") or ()),
        output_types=tuple(fields.get("output_types") or ()),
        presentations=tuple(fields.get("presentations") or ()),
        outlines=_outlines_from_fields(fields.get("outlines")),
        render_map=_render_map_from_fields(fields.get("render_map")),
    )


def _request_payload(request: SelectionRequest) -> dict[str, Any]:
    """The canonical (JSON-native) request projection stored in the token inputs (§20).

    The DR-3 `outlines` drive map is OMITTED when empty (the omit-when-absent zero-churn
    guarantee — an outline-less session's token inputs are byte-identical to pre-DR-3)."""
    payload: dict[str, Any] = {
        "recipe": request.recipe,
        "topics": list(request.topics),
        "personas": list(request.personas),
        "formats": list(request.formats),
        "voices": list(request.voices),
        "goal_sets": [list(gs) for gs in request.goal_sets],
        "platforms": list(request.platforms),
        "languages": list(request.languages),
        "output_types": list(request.output_types),
        "presentations": list(request.presentations),
    }
    outlines = [
        {"coordinate": coordinate_payload(combo), "outline_digest": digest}
        for combo, digest in request.outlines
    ]
    if outlines:
        payload["outlines"] = outlines
    # CLI-UX C5c: FLATTEN the grouped saved-selection DRIVE map back to its wire form (one
    # `{coordinate, render}` per render coord) so `continue-session` re-groups + re-resolves the
    # identical plan (§21.6). OMITTED when empty — a non-driven session's token inputs are
    # byte-identical to pre-C5c.
    render_map = [
        {"coordinate": coordinate_payload(combo), "render": render_coordinate_payload(coordinate)}
        for combo, coordinates in request.render_map
        for coordinate in coordinates
    ]
    if render_map:
        payload["render_map"] = render_map
    return payload


def _resolve_from_inputs(
    root: Path, user: str, workspace: str, zone: str, inputs: Mapping[str, Any]
) -> tuple[Plan, CascadeEnv, tuple[Any, ...], dict[str, str]]:
    """Re-resolve the plan from the token's inputs (§21.6 — never a cached plan).

    Reads config + registries only (LLM-free, deterministic): a mid-session config edit
    that changes the resolved plan changes the `plan_hash` — the `plan-stale` guard value.
    The source commit-map is the FROZEN pin from `begin-session` (§21.8), never re-pinned.
    `user`+`zone`+`workspace` scope the L3 config shadow at
    `users/<user>/zones/<zone>/workspaces/<ws>/` (§23, Z4).
    """
    request = _request_from_fields(inputs.get("request") or {})
    env = CascadeEnv(
        root, user=user, workspace=workspace, zone=zone, overrides=inputs.get("overrides") or None
    )
    source_subset = tuple(inputs.get("source_subset") or ())
    source_commit = dict(inputs.get("source_commit") or {})
    pool = build_pool(env.resolver, source_subset)
    source_repos = {inst.id: driver._source_repo_for(inst.id, inst.connection) for inst in pool}
    plan = resolve_plan(
        env,
        request,
        source_subset=source_subset,
        source_commit=source_commit,
        recipe_selection=inputs.get("recipe_selection"),
        run_selection=inputs.get("run_selection"),
    )
    return plan, env, pool, source_repos


# ---------------------------------------------------------------------------
# begin-session (§20, §21.1, §21.6): resolve the plan, mint the resumption token.
# ---------------------------------------------------------------------------


def _pin_source_commit_map(
    pool: Sequence[Any], adapters: Mapping[str, SourceAdapter], pins: Any
) -> dict[str, str]:
    """The §7.2 source commit-map, fixed at `begin-session` (§21.8). Supplied pins win
    (`pins["source_commit"]`, the `[pins]` slot — regenerate/extend earlier work); else
    each commit is CAPTURED via `adapter.pin_commit` — the SAME provenance read grounding
    uses (CF-1: identity and the §15 ledger never disagree)."""
    if isinstance(pins, Mapping) and isinstance(pins.get("source_commit"), Mapping):
        supplied = pins["source_commit"]
        return {inst.id: supplied[inst.id] for inst in pool if inst.id in supplied}
    commit_map: dict[str, str] = {}
    for inst in pool:
        commit = driver._pin_source_commit(adapters.get(inst.adapter), inst.connection)
        if commit is not None:
            commit_map[inst.id] = commit
    return commit_map


def _resolve_target_folio(
    store: Any, params: Mapping[str, Any], request: SelectionRequest
) -> str | None:
    """The token's target folio ref (§21.1): `none` → None; a concrete folio-id → itself
    (already isolation-checked at the invoke gate); `auto` → a fresh EMPTY folio minted
    now (the one-shot inline convenience), keyed by `idempotency_key` so an n8n retry
    reproduces the same folio, never a duplicate (§21.8)."""
    target = params.get("target_folio", TARGET_FOLIO_NONE)
    if target == TARGET_FOLIO_NONE:
        return None
    if target == TARGET_FOLIO_AUTO:
        purpose = params.get("purpose") or f"session-auto:{request.recipe}"
        outcome = create_folio(store, purpose=purpose, nonce=params.get("idempotency_key"))
        return outcome.folio_id
    return target  # a concrete folio-id — its existence + workspace were vetted upstream


def _ingest_outlines(store: Any, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    """DR-3 (B1) ingest: put any hand-authored raw outline (`ingest_outlines`:
    `[{"coordinate": {...}, "text": <md>}]`) into the pre-compose store and return the drive
    map as digest entries, APPENDED to any already-stored `outlines` digest entries. Idempotent
    / content-addressed (`put_outline`): the same text yields the same digest, so a retried
    begin-session reproduces the identical plan_hash (§21.8). Raises `OutlineError` on an
    empty/secret outline (§15/§3.3) — loud, never a silent skip."""
    entries: list[dict[str, Any]] = list(params.get("outlines") or [])
    for raw in params.get("ingest_outlines") or []:
        if not isinstance(raw, Mapping):
            raise OutlineError(
                f"outline-invalid: each ingest_outlines entry is {{coordinate, text}}, got {raw!r}"
            )
        md = raw.get("text")
        if not isinstance(md, str):
            raise OutlineError(
                "outline-invalid: an ingest_outlines `text` must be a string (the raw authored "
                f"outline Markdown), got {type(md).__name__}"
            )
        digest = put_outline(store, md)  # N + §15/§3.3 refusals; content-addressed no-replace
        entries.append({"coordinate": raw.get("coordinate"), "outline_digest": digest})
    return entries


# ---------------------------------------------------------------------------
# CLI-UX C7 (DR-3): the outline continuation-handle drift guard. It lives in `_begin_session`
# so EVERY door (CLI, in-process, HTTP shim) inherits it, and runs BEFORE any folio mint / token
# mint so a mismatch refuses pre-spend (nothing spends, no empty folio leaks — R7).
# ---------------------------------------------------------------------------

#: The EDIT-INVARIANT, FORMAT-INDEPENDENT content dimensions the drift guard compares (DR-3).
#: `format` is EXCLUDED — emit fixes `format=outline` while drive resolves the real format, a
#: difference that legitimately holds across the two phases.
_OUTLINE_SIGMA_DIMENSIONS = ("topic", "persona", "voice")


def _outline_config_sigma(preimage: Mapping[str, Any]) -> dict[str, Any]:
    """Project a §7.2 preimage to the EDIT-INVARIANT, FORMAT-INDEPENDENT subset σ the C7 drift
    guard compares (DR-3): the topic/persona/voice dimension bindings, the goal-set, the
    source-subset, and the lexicon binding (when present). EXCLUDES `dimensions[format]`
    (emit=outline vs drive=real), `source-commit` (live-pinned afresh at drive, `session.py`
    `_pin_source_commit_map`), and `outline-digest` (D1 at emit vs the hand-edited D2 at drive) —
    the three keys that legitimately differ emit→drive, so their difference never false-alarms.
    Overrides need no separate field: they are folded into each dimension's `delta`
    (`ids.build_artifact_preimage`), so comparing the per-dimension bindings compares the override
    effect too (§7.2)."""
    dimensions = preimage.get("dimensions") or {}
    projection: dict[str, Any] = {
        "dimensions": {name: dimensions.get(name) for name in _OUTLINE_SIGMA_DIMENSIONS},
        "goals": preimage.get("goals"),
        "source-subset": preimage.get("source-subset"),
    }
    if "lexicon" in preimage:
        projection["lexicon"] = preimage["lexicon"]
    return projection


def _outline_drift_guard(
    ctx: invoke_mod.HandlerContext, plan: Plan
) -> tuple[results.ResultItem | None, list[results.ResultItem]]:
    """The C7 outline continuation-handle drift guard (DR-3). Returns `(block, warns)`:

    - a non-None `block` means the caller must REFUSE pre-spend — mint no token, spend nothing;
    - `warns` are advisory items to ride the ok summary (proceed).

    The handle `outline_parent` (friendly `--from`) is the phase-1 emit-outline artifact-id; its
    stored `binding.preimage` records the phase-1 config, recovered by id from THIS workspace's
    output store (`compose._recorded_preimage_lookup` — zero new storage; a cross-workspace id
    physically cannot resolve → None, isolation-safe, R2). `outline_parent`/`allow_drift` are pure
    guard inputs, never part of identity (see `_begin_session`).
    """
    outline_parent = ctx.params.get("outline_parent")
    allow_drift = bool(ctx.params.get("allow_drift"))
    driven = [item for item in plan.items if item.outline_digest is not None]
    if not driven:
        return (None, [])  # nothing outline-driven — the guard is inert

    if outline_parent:
        p1 = compose._recorded_preimage_lookup(ctx.store)(str(outline_parent))
        if p1 is None:
            # S-3: a PRESENT-but-unresolved --from is a LOUD pre-spend not-found refusal (the user
            # asked to guard against a handle that does not exist) — distinct from a genuinely
            # ABSENT --from (the unverified warn below). Reuses CODE_NOT_FOUND (no new taxonomy).
            return (
                results.make_result(
                    results.CODE_NOT_FOUND,
                    item=str(outline_parent),
                    hint=(
                        "the --from handle did not resolve in this workspace — re-emit the "
                        "outline (a new handle) or drop --from (DR-3 §21.7)"
                    ),
                ),
                [],
            )
        if len(driven) != 1:
            # R3: a single --from guards EXACTLY one driven outline; multi is JSON / phase-5.
            return (
                _block(
                    "a single --from handle guards exactly one driven outline; this run drives "
                    f"{len(driven)} — drive one outline at a time or drop --from (DR-3)"
                ),
                [],
            )
        item = driven[0]
        if canonical_json_str(_outline_config_sigma(p1)) == canonical_json_str(
            _outline_config_sigma(item.preimage)
        ):
            return (None, [])  # σ match — proceed silently (consistency confirmed)
        if allow_drift:
            # --allow-drift: downgrade the BLOCK to a recorded WARN under the SAME §21.7 code and
            # STILL proceed (the honest "I meant to change it"). `outline-config-drift` carries two
            # dispositions — block by default, warn here (C6 `("block", "warn")`); `status="warn"`
            # is explicit (`statuses[0] == "block"` is the unchanged default refusal path).
            return (
                None,
                [
                    results.make_result(
                        results.CODE_OUTLINE_CONFIG_DRIFT,
                        item=item.artifact_id,
                        status="warn",
                        hint=(
                            "outline-config-drift accepted via --allow-drift — driving the outline "
                            "under a config that differs from its emit-time config (DR-3)"
                        ),
                    )
                ],
            )
        # Mismatch, no --allow-drift → the loud pre-spend block (mint no token; nothing spends).
        return (
            results.make_result(
                results.CODE_OUTLINE_CONFIG_DRIFT,
                item=item.artifact_id,
                hint=(
                    "the config this run drives the outline under differs from the config it was "
                    "emitted under (--from) — re-emit under the new config, or pass --allow-drift "
                    "(DR-3)"
                ),
            ),
            [],
        )

    # A driven outline with NO --from handle: no phase-1 record to check against — the ONLY warned
    # case for a driven outline (honest: proceed unverified).
    return (
        None,
        [
            results.make_result(
                results.CODE_OUTLINE_CONFIG_UNVERIFIED,
                item=driven[0].artifact_id,
                hint=(
                    "no emit-time --from handle to verify the driven outline's config against "
                    "(hand-authored, or --from omitted) — proceeding unverified (DR-3)"
                ),
            )
        ],
    )


def _begin_session(
    ctx: invoke_mod.HandlerContext, *, adapters: Mapping[str, SourceAdapter]
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """Resolve the plan (`generate = none` — nothing generated yet) and mint the token."""
    root = _root_of(ctx.store)
    try:
        # DR-3 (B1) INGEST leg: a hand-authored outline supplied as raw text under
        # `ingest_outlines` is put into the pre-compose outline store NOW (content-addressed,
        # §22.7) and folded into the drive map as its BARE digest — so the token carries only
        # digests and generate-next re-resolves purely (§21.6). Already-stored digests supplied
        # directly under `outlines` pass through unchanged. No new verb (reuses begin-session).
        outline_entries = _ingest_outlines(ctx.store, ctx.params)
    except OutlineError as exc:
        return ([_block(f"begin-session could not ingest an outline (§15/§3.3): {exc}")], None)
    try:
        request = _request_from_fields({**ctx.params, "outlines": outline_entries})
    except FanoutError as exc:
        return ([_block(f"begin-session needs a valid recipe + selection (§8): {exc}")], None)
    try:
        env = CascadeEnv(
            root, user=ctx.user, workspace=ctx.workspace, zone=ctx.zone,
            overrides=ctx.params.get("overrides"),
        )
    except OverrideError as exc:
        return ([results.make_result(
            results.CODE_INVALID_OVERRIDE, item="overrides", hint=str(exc)
        )], None)

    source_subset = tuple(driver._list_source_ids(root, ctx.user, ctx.workspace, ctx.zone))
    pool = build_pool(env.resolver, source_subset)
    try:
        source_commit = _pin_source_commit_map(pool, adapters, ctx.pins)
    except AdapterError as exc:
        # begin-session is plan-only (no grounding pass), so a malformed source `connection:`
        # (relative / non-`.json` / unknown-key) first surfaces HERE, at the §7.2 commit pin
        # (`adapter.pin_commit` → `_validate_connection`). The CLOSED §21.7 vocabulary names no
        # code for a bad source config, so surface it the same typed, code-less way the sibling
        # FanoutError/FolioError handlers do — never an untyped raise escaping the API.
        return ([_block(
            f"begin-session could not pin a source commit — a source `connection:` is "
            f"malformed (§6.1/§7.2): {exc}"
        )], None)

    # CLI-UX C1: the read-only `explain` projection. A pure guard/preview input — read from
    # `ctx.params` but NEVER added to `inputs` below, so the minted token + its `plan_hash`
    # (and every artifact-id) are untouched (the C1 identity invariant).
    explain = bool(ctx.params.get("explain"))
    try:
        plan = resolve_plan(
            env,
            request,
            source_subset=source_subset,
            source_commit=source_commit,
            run_selection=ctx.params.get("run_selection"),
            explain=explain,
        )
    except UnknownEntryError as exc:
        not_found = results.make_result(results.CODE_NOT_FOUND, item="selection", hint=str(exc))
        return ([not_found], None)

    # CLI-UX C7 (DR-3): the outline continuation-handle drift guard. It runs BEFORE the auto-folio
    # mint (`_resolve_target_folio`) and the token mint below, so a mismatch RETURNS with NO token
    # and NO minted folio — nothing spends, no empty folio leaks (R7). Its inputs
    # `outline_parent`/`allow_drift` are pure guard inputs: read from `ctx.params` but NEVER added
    # to `inputs` below (nor to the request/preimage), so the driven artifact-id + its preimage are
    # byte-identical with and without the handle (DR-3 horn-(a); the C7 identity invariant).
    guard_block, guard_warns = _outline_drift_guard(ctx, plan)
    if guard_block is not None:
        return ([guard_block], None)

    try:
        folio_id = _resolve_target_folio(ctx.store, ctx.params, request)
    except FolioError as exc:
        return ([_block(f"begin-session could not target the folio (§21.1): {exc}")], None)

    inputs: dict[str, Any] = {
        "request": _request_payload(request),
        "overrides": dict(ctx.params.get("overrides") or {}),
        "source_subset": list(source_subset),
        "source_commit": dict(source_commit),
    }
    run_selection = ctx.params.get("run_selection")
    if run_selection is not None:
        inputs["run_selection"] = run_selection

    token = token_mod.mint(
        ctx.workspace,
        plan.plan_hash,
        inputs=inputs,
        cursor={"consumed": []},
        produced_ids=(),
        folio_id=folio_id,
    )
    ids: dict[str, Any] = {
        "artifact_ids": list(plan.artifact_ids()),
        "deliverable_ids": list(plan.deliverable_ids()),
    }
    if folio_id is not None:
        ids["folio_id"] = folio_id
    # The advisory warnings the plan resolver raised, plus any C7 drift-guard warns (the
    # `outline-config-unverified` no-handle case, or an `--allow-drift` downgrade) so `preview`
    # surfaces them; the same warns also ride `results[]` below as typed items.
    warnings = [w.message for w in plan.warnings]
    warnings.extend(
        gw.remediation["hint"]
        for gw in guard_warns
        if gw.remediation and "hint" in gw.remediation
    )
    context: dict[str, Any] = {
        "plan_hash": plan.plan_hash,
        "generate": "none",
        "warnings": warnings,
    }
    if explain:
        # C1: the read side-channel — the effective compose+render settings (each dimension's
        # bound values + provenance) and the spend estimate `spend_scope = len(artifact_ids)`
        # (printed `spend-scope: N paid artifact(s)`). Nothing here feeds `inputs`/the token.
        context["effective_settings"] = plan.effective_settings
        context["spend_scope"] = len(plan.artifact_ids())
        # C5b: the floor-faithful per-deliverable variant capture the friendly `generate
        # --save-selection` door serializes (`__main__._save_selection`). A JSON-native read
        # side-channel captured off this SAME resolve — never folded into `inputs`/the token,
        # so the minted plan_hash/ids are byte-identical with and without the capture.
        context["selection_variants"] = list(plan.selection_variants or ())
    if ctx.params.get("want_parallel_plan"):
        # §22.2/§22.4: hand back the wave plan + width advice — no new verb (PC6). The token
        # is unchanged (an immutable plan-context under parallel mode; workers coordinate via
        # the store/claims, never by mutating it).
        context.update(_parallel_plan_context(root, plan))
    summary = results.ResultItem(item="begin-session", status="ok", ids=ids, context=context)
    return ([summary, *guard_warns], token)


# ---------------------------------------------------------------------------
# continue-session (§21.2): the closed action vocabulary + nested-id isolation.
# ---------------------------------------------------------------------------


def _block(hint: str, *, item: str = "continue-session") -> results.ResultItem:
    """A per-item block with NO taxonomy code — for a condition the closed §21.7 vocabulary
    does not name (a malformed call / a non-taxonomy driver failure). Honest: the code set is
    CLOSED, so no code is fabricated; the detail rides `remediation.hint`.

    HARD GATE-1 (§21.7 code threading) — CLOSED at step 39. A code-bearing GENERATION block is
    no longer a gap: the driver threads its true §21.7 stage code (`empty-pool` at grounding,
    `hard-limit-exceeded` at the reconcile terminal gate) across the driver→session boundary, so
    `_generate_next`'s `DriverError` branch surfaces `results.make_result(code, …)` for those.
    A code-less `_block` now covers ONLY the conditions the taxonomy genuinely does not name —
    malformed CALLS (bad recipe, unmapped folio, malformed source `connection:`) and non-taxonomy
    generation failures (compose-contract, transport codes) — and stays code-less forever
    (§3.1: no fabrication)."""
    return results.ResultItem(item=item, status="block", remediation={"hint": hint})


def _continue_session(
    ctx: invoke_mod.HandlerContext,
    *,
    adapters: Mapping[str, SourceAdapter],
    run_artifact: Callable[..., Any],
    now: date | None,
    model: str | None,
    delegates: Mapping[str, invoke_mod.Handler],
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """Dispatch one continue-session action over the CLOSED vocabulary (§21.2).

    `generate-next`/`status` are handled inline; every other action
    (`render`/`fetch`/`add-to-folio`/`list`/`get`/`emit-manifest`) DELEGATES to its standalone
    verb handler (`delegates`) over the SAME `HandlerContext` and ECHOES the token unchanged (a
    read/side-output, not a cursor advance — §21.1 contract parity). After step 35 the closed
    vocabulary is FULLY wired — no action is a `NotYetWired` stub (the `NotYetWired` raise below is
    a defensive guard proven UNREACHABLE by `tests/test_action_completeness.py`)."""
    action = ctx.params.get("action")
    if not isinstance(action, str) or action not in CONTINUE_ACTIONS:
        return ([results.make_result(
            results.CODE_UNKNOWN_ACTION,
            item=action if isinstance(action, str) else "",
            hint=(
                f"action {action!r} is not in the closed continue-session set "
                f"{sorted(CONTINUE_ACTIONS)!r} (§21.2; discover via `list actions`)"
            ),
        )], ctx.token)

    if action == "generate-next":
        return _generate_next(
            ctx, adapters=adapters, run_artifact=run_artifact, now=now, model=model
        )
    if action == "status":
        return _status(ctx)
    if action in delegates:
        # The action path and the standalone verb path share ONE handler (§21.1). The delegate
        # mints no token (emit-manifest included — it is a READ/PLAN, §21.5); the session echoes
        # the incoming cursor unchanged (like `status`).
        items, _next = delegates[action](ctx)
        return (items, ctx.token)
    # DEFENSIVE (unreachable given the closed vocabulary is fully wired): a future action added to
    # `CONTINUE_ACTIONS` without a handler trips this honest seam rather than misdispatching —
    # `tests/test_action_completeness.py` asserts NO current action reaches it.
    raise NotYetWired(action)  # pragma: no cover


# ---------------------------------------------------------------------------
# generate-next (§21.6, §12.5): batch + cursor, plan-re-resolving, idempotent.
# ---------------------------------------------------------------------------


def _append_unique(seq: list[str], value: str) -> None:
    if value not in seq:
        seq.append(value)


def _batch_size(raw: Any, remaining: int) -> int:
    """`batch_size` (§21.6): a positive int, or `all` = the whole remaining cover; a missing
    or unrecognized value falls to the small default (never a silent large run)."""
    if raw == "all":
        return remaining or 1
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 1:
        return raw
    return _DEFAULT_BATCH_SIZE


def _select_batch(plan: Plan, consumed: Sequence[str], params: Mapping[str, Any]) -> list[Any]:
    """The PURE pre-transport batch selection (§21.6) — the ORDERED plan items a `generate-next`
    call composes this turn: the `only`-filtered set when `params['only']` is a list, else the
    not-yet-`consumed` cursor complement, sliced to `_batch_size`. This is the SINGLE source both
    the MATERIALIZER (`_generate_next`) and the async predictable-id resolver
    (`plan_next_batch_ids`) consume, so the id set a job is keyed/polled on can NEVER drift from the
    set the paid call actually composes (one source, not two hand-synced copies)."""
    only = params.get("only")
    if isinstance(only, Sequence) and not isinstance(only, str | bytes):
        wanted = {v for v in only if isinstance(v, str)}
        candidates = [item for item in plan.items if item.artifact_id in wanted]
    else:
        seen = set(consumed)
        candidates = [item for item in plan.items if item.artifact_id not in seen]
    return candidates[: _batch_size(params.get("batch_size"), len(candidates))]


def plan_next_batch_ids(
    root: Path,
    user: str,
    workspace: str,
    zone: str,
    token: token_mod.Token,
    params: Mapping[str, Any],
) -> list[str]:
    """The PREDICTABLE target artifact-id set the NEXT `generate-next` call will materialize —
    resolved PURELY (LLM-free, §22.2), so an async transport (the DR-1 shim) can KEY + POLL a job
    BEFORE the paid call and be certain the keyed set == the composed set.

    Re-resolves the plan from the token inputs (`_resolve_from_inputs` — a deterministic config
    read, never a cached plan, never a live call); returns `[]` on a `plan_hash` mismatch (plan-
    stale → generate-next composes NOTHING, §21.6) or an empty batch; else the batch's artifact-ids
    IN PLAN ORDER. Shares `_select_batch` with `_generate_next`, so the returned ids are EXACTLY the
    batch that call composes — the anti-drift invariant holds BY CONSTRUCTION, not by hand-sync."""
    plan, _env, _pool, _repos = _resolve_from_inputs(root, user, workspace, zone, token.inputs)
    if plan.plan_hash != token.plan_hash:
        return []
    consumed = list(token.cursor.get("consumed", []))
    return [item.artifact_id for item in _select_batch(plan, consumed, params)]


def _transport_enforced(root: Path, override: str | None) -> bool:
    """True iff the plan-G7 transport RESOLUTION runs for this spend batch. An explicit per-run
    override ALWAYS enforces; otherwise enforcement activates once a transport config exists
    (`instance/ops/transport/config.yaml` — any assigned key / entitled user / umbrella cap). An
    install that has configured NOTHING keeps the pre-G7 subscription-only behavior (`transport_plan
    = None`), so existing generation is byte-unchanged and no new refusal is introduced until the
    operator opts in by configuring transport (the money-safety activation model)."""
    if override:
        return True
    from pipeline.spend.assignment import config_path

    return config_path(root).is_file()


def _admit_batch_transport(
    root: Path,
    user: str,
    zone: str,
    workspace: str,
    override: str | None,
    to_generate: Sequence[Any],
    plan: Plan,
) -> tuple[Any, Any, str | None]:
    """The plan-G7 run-admission step for ONE generate-next batch: RESOLVE the transport (the ONLY
    mode-selector, `pipeline.spend.resolve`) and ADMIT the batch's worst-case ceiling against the
    assignment bucket + the umbrella BEFORE any spawn.

    Returns `(admission, transport_plan, spend_refusal)`:
    - enforcement inactive OR nothing to generate → `(None, None, None)` (the subscription/None path
      — no admit, no metering);
    - a resolved transport → `(AdmittedTransport, TransportPlan, None)` — caller drives under the
      plan and settles `admission` in a `finally`;
    - a PRE-SPEND refusal (no key + unentitled, a cap-over ceiling, a bad override, a missing/
      unreadable secret) → `(None, None, <reason>)` — the caller blocks each un-done item with the
      reason (no hold, no spawn), never a crash across `invoke()`."""
    if not to_generate or not _transport_enforced(root, override):
        return None, None, None
    from pipeline.spend import resolve as resolve_mod
    from pipeline.spend.assignment import AssignmentError
    from pipeline.spend.keystore import KeyStoreError
    from pipeline.spend.meter import MeterError

    n_artifacts = len(to_generate)
    n_deliverables = sum(len(item.deliverables) for item in to_generate)
    try:
        admission = resolve_mod.resolve_transport(
            root,
            user,
            zone,
            workspace,
            override=override,
            n_artifacts=n_artifacts,
            n_deliverables=n_deliverables,
            run_id=f"{workspace}:{plan.plan_hash[:12]}",
        )
    except (
        resolve_mod.TransportResolutionError,
        MeterError,
        KeyStoreError,
        AssignmentError,
    ) as exc:
        # A PRE-SPEND refusal — typed, no hold written, nothing spawned. Surface the reason as a
        # per-item block (the caller decides), never a raise across the shared `invoke()` boundary.
        # `AssignmentError` (LOW-2) covers a MALFORMED transport config (`ConfigError` from
        # `load_store`) — an operator typo becomes a clean refusal block, never a runner crash.
        return None, None, str(exc)
    return admission, admission.plan, None


def _generate_next(
    ctx: invoke_mod.HandlerContext,
    *,
    adapters: Mapping[str, SourceAdapter],
    run_artifact: Callable[..., Any],
    now: date | None,
    model: str | None,
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """Compose the next `batch_size` missing plan items and advance the cursor (§21.6).

    Re-resolves the plan from the token's inputs on EVERY call; a `plan_hash` mismatch
    surfaces `plan-stale` (warn) and generates NOTHING (never a silent skip/dup). Idempotent
    by artifact-id EXISTENCE: an already-materialized id is `already-materialized` (ok), never
    regenerated. A per-item generation failure (driver `DriverError`) is a per-item BLOCK —
    the batch continues (SM1). Advances the cursor by item COORDINATE (the artifact-id), never
    by index, and returns the updated token (new cursor + appended produced ids).
    """
    token = ctx.token
    if token is None:
        need = _block("generate-next requires the resumption token from begin-session (§21.1)")
        return ([need], None)

    root = _root_of(ctx.store)
    plan, env, pool, source_repos = _resolve_from_inputs(
        root, ctx.user, ctx.workspace, ctx.zone, token.inputs
    )
    # N2 HEAD-FREEZE (mechanism (a), the PRODUCTION drive seam): the plan-time §7.2 commit-map is
    # FROZEN in the token (`begin-session`, §21.8); the pool is re-BUILT from static config here, so
    # a HEAD-mode cache connection would otherwise ground the LIVE HEAD an out-of-band acquire may
    # have advanced across the begin→generate gap. Thread the frozen commit BACK into each drive
    # connection (the SAME `driver._freeze_pool` the `run_thread` seam uses) so ground() reads the
    # PINNED slice. A no-op for graphify/folder/fsast; the frozen source_commit (and every
    # artifact-id) is untouched (CF-1).
    pool = driver._freeze_pool(pool, adapters, dict(token.inputs.get("source_commit") or {}))
    if plan.plan_hash != token.plan_hash:
        stale = results.make_result(
            results.CODE_PLAN_STALE,
            item="plan",
            context={"plan_hash_token": token.plan_hash, "plan_hash_current": plan.plan_hash},
            hint=(
                "the plan changed since begin-session — re-fetch the plan / begin a new "
                "session (§21.6); NOTHING was generated (never a silent skip or dup)"
            ),
        )
        return ([stale], token)  # echo the token unchanged — the caller's checkpoint survives

    store = ctx.store
    store.ensure_layout()
    claims = registry_for(store)
    ssot = Ssot(store.root / "ssot.csv")

    consumed = list(token.cursor.get("consumed", []))
    produced = list(token.produced_ids)
    # The batch selection is the SHARED pure `_select_batch` (§21.6) — the SAME source the async
    # `plan_next_batch_ids` uses, so the DR-1 shim's job key can never drift from what this call
    # materializes (one source of truth, no hand-synced fork).
    batch = _select_batch(plan, consumed, ctx.params)

    # plan G7 — the RUN-ADMISSION tier at the SHARED spend chokepoint both doors traverse (CLI +
    # `jobrunner→invoke()` re-enter this handler identically): resolve the transport for THIS batch
    # and ADMIT its worst-case ceiling vs the assignment bucket + the umbrella BEFORE any spawn,
    # then SETTLE the accumulated ACTUAL cost in a `finally` on EVERY exit path. The per-call disarm
    # (transport.py) fires ONLY under the live hold this admit produces. A refusal (no key +
    # not entitled, a cap-exceeding ceiling, a bad override, a missing secret) is surfaced as a
    # per-item BLOCK — never a spawn, never a crash across `invoke()`.
    to_generate = [item for item in batch if not is_done(store, item.artifact_id)]
    admission, transport_plan, spend_refusal = _admit_batch_transport(
        root, ctx.user, ctx.zone, ctx.workspace, ctx.transport_override, to_generate, plan
    )
    # plan G8 — the pre-spend COST DISCLOSURE, emitted at the admission spot so it reflects the REAL
    # resolved+admitted plan (mode / charged bucket / worst-case ceiling / live headroom), BEFORE
    # the first spawn below. A READ-ONLY projection off the admitted plan + the same meter; it
    # admits nothing and spends nothing. To STDERR (the shared chokepoint both doors traverse — CLI
    # drive + the detached jobrunner re-entry): a money-safety notice, never on the stdout JSON
    # envelope. Fires only when transport is enforced (an `admission` exists); the unconfigured
    # subscription-only path (`admission is None`) discloses nothing, byte-unchanged (§ activation).
    if admission is not None:
        print(admission.disclose().line(), file=sys.stderr)

    now = now or date.today()
    out: list[results.ResultItem] = []
    try:
        for item in batch:
            aid = item.artifact_id
            # §21.8 idempotency floor: correctness comes from id EXISTENCE, never the cursor.
            if is_done(store, aid):
                out.append(results.make_result(
                    results.CODE_ALREADY_MATERIALIZED, item=aid, ids={"artifact_id": aid}
                ))
                _append_unique(produced, aid)
            elif spend_refusal is not None:
                # A PRE-SPEND transport refusal (plan G7): no hold, no spawn — surfaced as a
                # per-item block naming the reason. Nothing was admitted or spent for this item.
                out.append(_block(spend_refusal, item=aid))
            else:
                try:
                    # plan G7: the admitted api-key plan (or the subscription/None plan when
                    # enforcement is inactive) — the run-admission tier resolved+admitted it above.
                    result = run_artifact(
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
                        log=_nolog,
                        transport_plan=transport_plan,
                    )
                except driver.DriverError as exc:
                    # SM1: a per-item block never fails the batch; siblings proceed.
                    # HARD GATE-1 (§21.7 code threading) — CLOSED at step 39 (`mvp-demo` is the
                    # first real caller wiring generate-next to the LIVE transport). The driver now
                    # threads the TRUE §21.7 taxonomy code across the driver→session boundary on its
                    # three generation-tier gates (`empty-pool` at grounding, `hard-limit-exceeded`
                    # at the reconcile terminal gate, `grounding-uncovered` at the post-review
                    # abstain gate); a coded block surfaces it with its taxonomy
                    # `category`. A NON-taxonomy driver failure (malformed call, compose-contract,
                    # transport code) carries NO code and stays a code-less `_block` FOREVER — the
                    # §3.1 no-fabrication rule. `make_result` DEFAULTS the status from the code's
                    # `CodeSpec.statuses[0]` (never hardcoded `status="block"`), so a future code
                    # code threaded here can never raise an uncaught `ResultContractError`, and the
                    # remediation `action` defaults from the CodeSpec when the driver supplies none.
                    code = exc.stage_code if exc.stage_code in results.ALL_CODES else None
                    if code is not None:
                        out.append(results.make_result(
                            code,
                            item=aid,
                            ids={"artifact_id": aid},
                            action=exc.remediation_action,
                            hint=str(exc),
                        ))
                    else:
                        out.append(_block(str(exc), item=aid))  # malformed-call stays codeless
                else:
                    deliverable_ids = [
                        d.deliverable_id for d in getattr(result, "deliverables", ())
                    ]
                    ids: dict[str, Any] = {"artifact_id": aid}
                    if deliverable_ids:
                        ids["deliverable_ids"] = deliverable_ids
                    out.append(results.ResultItem(item=aid, status="ok", ids=ids))
                    _append_unique(produced, aid)
                    for did in deliverable_ids:
                        _append_unique(produced, did)
            _append_unique(consumed, aid)  # advance the cursor by COORDINATE (§21.6), not index

        new_token = token_mod.mint(
            ctx.workspace,
            plan.plan_hash,
            inputs=token.inputs,
            cursor={**dict(token.cursor), "consumed": consumed},
            produced_ids=produced,
            folio_id=token.folio_id,
        )
        return (out, new_token)
    finally:
        # SETTLE on EVERY exit path (a clean return OR a mid-loop raise): append the settled ledger
        # line with the accumulated ACTUAL cost and drop the hold (plan G7). A no-op for the
        # subscription / unconfigured path (no admission). A crash that skips this self-expires the
        # hold at its full ceiling (the G6 TTL) — never a leaked reservation.
        if admission is not None and transport_plan is not None:
            admission.settle(transport_plan.cost_accumulator.total)


# ---------------------------------------------------------------------------
# status (§21.2): progress + drift + plan-hash check — a READ, never generation.
# ---------------------------------------------------------------------------


def _status(
    ctx: invoke_mod.HandlerContext,
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """Report cursor/progress from the token and check for plan drift (§21.2). A pure read:
    it re-resolves the plan (LLM-free) to compute the current `plan_hash`, but generates
    nothing and advances nothing. Drift surfaces `plan-stale` (warn); otherwise `ok`."""
    token = ctx.token
    if token is None:
        return ([_block("status requires the resumption token from begin-session (§21.1)")], None)
    root = _root_of(ctx.store)
    plan, _env, _pool, _repos = _resolve_from_inputs(
        root, ctx.user, ctx.workspace, ctx.zone, token.inputs
    )
    consumed = list(token.cursor.get("consumed", []))
    drift = plan.plan_hash != token.plan_hash
    # §22.3 completeness sweep exposed via `status` — the wave barrier read from MATERIALIZED
    # ids (store existence, ssot-free), NEVER the cursor and NEVER the SSOT (§22.7). `missing`
    # surfaces any expected unit neither materialized nor blocked (the anti-silent-gap view;
    # status supplies no blocked set, so unmaterialized == pending/missing here).
    sweep_result = parallel.sweep(parallel.build_wave_plan(plan), ctx.store)
    progress = {
        "consumed": len(consumed),
        "produced": len(token.produced_ids),
        "planned": len(plan.items),
        "plan_hash_token": token.plan_hash,
        "plan_hash_current": plan.plan_hash,
        "drift": drift,
        "sweep": {
            "expected": len(sweep_result.expected),
            "materialized": len(sweep_result.materialized),
            "blocked": len(sweep_result.blocked),
            "missing": len(sweep_result.missing),
            "complete": sweep_result.complete,
            "waves": [
                {
                    "index": w.index,
                    "kind": w.kind,
                    "expected": len(w.expected),
                    "materialized": len(w.materialized),
                    "missing": len(w.missing),
                    "complete": w.complete,
                }
                for w in sweep_result.waves
            ],
        },
    }
    if drift:
        item = results.make_result(
            results.CODE_PLAN_STALE,
            item="status",
            context=progress,
            hint="the plan changed since begin-session (§21.6) — re-fetch the plan / re-begin",
        )
    else:
        item = results.ResultItem(item="status", status="ok", context=progress)
    return ([item], token)  # echo the token unchanged — status is side-effect-free


# ---------------------------------------------------------------------------
# emit-outline (§21.1, DR-3 horn (a) / B1): a HAND-AUTHORED outline + a target coordinate ->
# a byte-faithful `Format=outline` artifact, minted + persisted and returned by artifact-id
# (renderable/fetchable through the EXISTING render/fetch verbs, UNCHANGED). The dual, output
# sibling of the outline-as-INPUT drive path.
# ---------------------------------------------------------------------------


def _goal_ids(raw: Any) -> tuple[str, ...] | None:
    """The run goal-set from the emit request (§12.3): a list of goal ids -> a tuple (an
    explicit `[]` is an explicit empty set); absent (`None`) -> `None`, so the recipe/workspace
    cascade default applies (never silently emptied). A non-list is a loud `SelectionError`."""
    if raw is None:
        return None
    if isinstance(raw, str | bytes) or not isinstance(raw, Sequence):
        raise SelectionError(
            f"invalid-selection: `goals` is a list of goal ids (§12.3), not {type(raw).__name__}"
        )
    return tuple(str(goal) for goal in raw)


def _emit_outline(
    ctx: invoke_mod.HandlerContext, *, adapters: Mapping[str, SourceAdapter]
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """One `emit-outline` call (DR-3 horn (a) / B1): realize a HAND-AUTHORED outline as an
    ordinary `Format=outline` artifact, minted by its target coordinate + the outline's OWN
    normalized bytes (the R4 own-body digest), and persisted idempotently.

    Flow: accept + persist the raw outline (`put_outline` = N + §15 substance floor + §3.3
    secret scan; an empty / secret outline is refused LOUDLY as a typed block, nothing
    persisted) -> resolve the target coordinate through the SAME cascade the compose/drive path
    uses (`resolve_compose`, `format` FIXED = `outline`) -> `compose.artifact_preimage(
    outline_digest=…)` -> `mint_artifact_id` -> `build_outline_ir` (the Commit-4 emit bridge —
    NO new IR type/schema/registry root). The id rides the `outline-digest` ONLY (the Commit-2
    preimage extension; horn (a) adds no new preimage key): two different edited outlines over
    one coordinate mint DIFFERENT ids, a cosmetic edit mints the SAME id, and a re-emit is the
    idempotent `already-materialized` no-op (§22.7). The emitted artifact renders/fetches
    through the UNCHANGED render/fetch verbs.

    §21.7 codes: a fresh emit is plain `ok`; a re-emit is the reused `already-materialized`
    (§22.6/§22.3). The §21.7 vocabulary names NO outline-refusal code, so an empty/secret
    outline (and a malformed call) is a CODE-LESS `block` (§3.1: no fabricated code) — the SAME
    honest shape begin-session's ingest leg uses for the identical `OutlineError`.
    """
    params = ctx.params
    md = params.get("outline")
    if not isinstance(md, str) or not md:
        return ([_block(
            "emit-outline needs `outline` (the raw authored Markdown) + a target coordinate "
            "(topic/persona/voice/goals/source-subset/source-commit; format is fixed = outline)",
            item="emit-outline",
        )], None)
    recipe = params.get("recipe")
    if not isinstance(recipe, str) or not recipe:
        return ([_block(
            "emit-outline needs a `recipe` to resolve the target coordinate (§8/§12.3)",
            item="emit-outline",
        )], None)

    # 1. Accept + persist the outline NOW (content-addressed, §22.7). `put_outline` runs
    #    `accept_outline` FIRST (N + §15 substance floor + §3.3 secret scan) and RAISES BEFORE
    #    any write, so an empty / secret-shaped outline is a LOUD typed block and never reaches
    #    disk (nothing persisted). The digest returned IS `outline_digest(md)`.
    try:
        digest = put_outline(ctx.store, md)
    except OutlineError as exc:
        return ([_block(
            f"emit-outline refused the outline ({exc.code}, §15/§3.3): {exc}", item="emit-outline"
        )], None)

    # 2. Resolve the target coordinate through the SAME cascade as compose/drive; `format` is
    #    FIXED = `outline` (the emit posture — the selection pick outranks the recipe slot).
    root = _root_of(ctx.store)
    try:
        env = CascadeEnv(
            root, user=ctx.user, workspace=ctx.workspace, zone=ctx.zone,
            overrides=params.get("overrides"),
        )
    except OverrideError as exc:
        return ([results.make_result(
            results.CODE_INVALID_OVERRIDE, item="overrides", hint=str(exc)
        )], None)
    try:
        selection = RunSelection(
            recipe=recipe,
            topic=params.get("topic"),
            persona=params.get("persona"),
            format="outline",  # FIXED — the emit produces a `Format=outline` artifact (horn (a))
            voice=params.get("voice"),
            goals=_goal_ids(params.get("goals")),
        )
        compose = resolve_compose(env, selection)
    except UnknownEntryError as exc:
        return (
            [results.make_result(results.CODE_NOT_FOUND, item="selection", hint=str(exc))],
            None,
        )
    except (SelectionError, OverrideError) as exc:
        return ([_block(
            f"emit-outline could not resolve the coordinate (§12.3): {exc}", item="emit-outline"
        )], None)

    # 3a. B-2 (the safe-outline crux): default the emit-side `source_subset` (and its commit-map)
    #     to the SAME workspace pool the drive path computes (`_begin_session:378-381`), so a
    #     legitimate emit→edit→drive MATCHES on the C7 σ guard — both phases mint their preimage
    #     under the same source pool. Previously the friendly emit path passed the EMPTY subset
    #     while drive passed the full pool, so σ.source-subset always differed → the guard blocked
    #     EVERY real run. A §7.2 preimage requires the commit-map keys to EQUAL the subset, so the
    #     pool default MUST pin its commits too (a read-only, LLM-free provenance read, CF-1);
    #     source-commit is EXCLUDED from σ, so an emit-time vs drive-time commit difference never
    #     false-alarms. An EXPLICIT power-form `source_subset`/`source_commit` is honored unchanged.
    #     Zero identity churn on a workspace with no `sources/` (the pool is [] = the prior ()).
    try:
        if params.get("source_subset"):
            source_subset: tuple[str, ...] = tuple(params["source_subset"])
            source_commit: dict[str, str] = dict(params.get("source_commit") or {})
        else:
            source_subset = tuple(driver._list_source_ids(root, ctx.user, ctx.workspace, ctx.zone))
            pool = build_pool(env.resolver, source_subset)
            source_commit = _pin_source_commit_map(pool, adapters, ctx.pins)
    except AdapterError as exc:
        # A malformed source `connection:` first surfaces at the §7.2 commit pin — surface it the
        # same typed, code-less way begin-session's sibling handler does (never an untyped raise).
        return ([_block(
            f"emit-outline could not pin a source commit — a source `connection:` is malformed "
            f"(§6.1/§7.2): {exc}",
            item="emit-outline",
        )], None)

    # 3b. The §7.2 preimage carries the R4 own-body `outline-digest` as its SOLE new component;
    #     the id round-trips via `mint_artifact_id(preimage)` (`build_ir` re-mints + refuses a
    #     forgery inside `build_outline_ir`). A malformed source-subset/commit map is a loud block.
    try:
        preimage = compose.artifact_preimage(
            source_subset=source_subset,
            source_commit=source_commit,
            outline_digest=digest,
        )
    except PreimageError as exc:
        return ([_block(
            f"emit-outline coordinate is malformed (§7.2): {exc}", item="emit-outline"
        )], None)
    artifact_id = mint_artifact_id(preimage)

    # 4. Persist via the Commit-4 emit bridge (idempotent no-replace; the IR body IS `N(md)`).
    #    Idempotency reads OUTPUT EXISTENCE (§22.7): a re-emit of the same outline+coordinate is
    #    the `already-materialized` no-op, the winner's bytes untouched.
    already = is_done(ctx.store, artifact_id)
    build_outline_ir(
        normalize_outline(md), artifact_id=artifact_id, preimage=preimage, store=ctx.store
    )
    ids: dict[str, Any] = {"artifact_id": artifact_id}
    if already:
        return ([results.make_result(
            results.CODE_ALREADY_MATERIALIZED, item=artifact_id, ids=ids
        )], None)
    return ([results.ResultItem(item=artifact_id, status="ok", ids=ids)], None)


# ---------------------------------------------------------------------------
# Handler factories + the wiring point (§21.1). Registration is EXPLICIT (never a module
# import side effect) so it never wires verbs the step-32 unwired-registry tests assume.
# ---------------------------------------------------------------------------


def begin_session_handler(
    *, adapters: Mapping[str, SourceAdapter] | None = None
) -> invoke_mod.Handler:
    """The `begin-session` handler; `adapters` is the injection seam (default: the real
    graphify adapter, for the §7.2 commit pin). Consumed via `invoke(handlers=…)` or
    `register_session_handlers`."""
    resolved = dict(adapters) if adapters is not None else _default_adapters()

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _begin_session(ctx, adapters=resolved)

    return handler


def _continue_session_delegates(
    *, render_engine: Any, currency_resolver: Any
) -> dict[str, invoke_mod.Handler]:
    """Build the verb handlers the wired continue-session actions delegate to (§21.1 contract
    parity). `render`/`get`/`list`/`emit-manifest` carry their injectable seams (the render engine,
    the currency resolver); `discovery`'s `actions` meta-type is fed the single-source
    `CONTINUE_ACTIONS`. After step 35 EVERY id-bearing/side-output action delegates — no stub
    remains (the completeness assertion, `tests/test_action_completeness.py`)."""
    return {
        "render": render.render_handler(engine=render_engine),
        "fetch": fetch.fetch_handler(),
        "add-to-folio": folio_verbs.add_to_folio_handler(),
        "list": discovery.list_handler(resolver=currency_resolver, action_vocab=CONTINUE_ACTIONS),
        "get": discovery.get_handler(resolver=currency_resolver),
        "emit-manifest": manifest.emit_manifest_handler(resolver=currency_resolver),
    }


def continue_session_handler(
    *,
    adapters: Mapping[str, SourceAdapter] | None = None,
    run_artifact: Callable[..., Any] | None = None,
    now: date | None = None,
    model: str | None = None,
    render_engine: Any = None,
    currency_resolver: Any = None,
) -> invoke_mod.Handler:
    """The `continue-session` handler; seams: `adapters` (grounding), `run_artifact` (the
    per-item generation thread — default `driver._run_artifact`, injectable so tests never
    make a live subscription call), `now` (the grounding clock), `model` (the writer pin), and
    the step-34 delegation seams `render_engine` (the reconcile/serialize legs) +
    `currency_resolver` (the discovery currency reader) — both injectable so the delegated
    actions stay live-call-free."""
    resolved = dict(adapters) if adapters is not None else _default_adapters()
    generate = run_artifact if run_artifact is not None else driver._run_artifact
    delegates = _continue_session_delegates(
        render_engine=render_engine, currency_resolver=currency_resolver
    )

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _continue_session(
            ctx, adapters=resolved, run_artifact=generate, now=now, model=model, delegates=delegates
        )

    return handler


def emit_outline_handler(
    *, adapters: Mapping[str, SourceAdapter] | None = None
) -> invoke_mod.Handler:
    """The `emit-outline` handler (DR-3 horn (a) / B1). The emit is deterministic store I/O + the
    pure, LLM-free cascade resolution — there is NO reconcile/serialize leg, so no engine to inject
    and no live subscription call is ever reachable here (unlike `render`). `adapters` is the ONLY
    seam: the SAME §7.2 commit-pin adapter set begin-session uses (default: the real graphify
    adapter), so the B-2 emit-side `source_subset`/commit-map default is computed identically to the
    drive path (the C7 σ guard matches on a legitimate emit→edit→drive). `pin_commit` is read-only
    (rule 1) — never a grounding/live call."""
    resolved = dict(adapters) if adapters is not None else _default_adapters()

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _emit_outline(ctx, adapters=resolved)

    return handler


def register_emit_outline_handler() -> None:
    """Wire `emit-outline` into the invoke dispatch registry (§21.1). EXPLICIT — never at import
    (keeps the empty-registry gate tests valid), the same discipline as the other producers."""
    invoke_mod.register_handler("emit-outline", emit_outline_handler())


def register_session_handlers(
    *,
    adapters: Mapping[str, SourceAdapter] | None = None,
    run_artifact: Callable[..., Any] | None = None,
    now: date | None = None,
    model: str | None = None,
    render_engine: Any = None,
    currency_resolver: Any = None,
) -> None:
    """Wire `begin-session` + `continue-session` into the invoke dispatch registry (§21.1).

    EXPLICIT by design — never called at import time, so importing this module never wires
    verbs that step-32's unwired-registry tests expect empty. The production edge calls this
    (or `register_api_handlers`) once at startup; tests use `invoke(handlers=…)` or call this
    inside a snapshot/restore fixture."""
    invoke_mod.register_handler("begin-session", begin_session_handler(adapters=adapters))
    invoke_mod.register_handler(
        "continue-session",
        continue_session_handler(
            adapters=adapters,
            run_artifact=run_artifact,
            now=now,
            model=model,
            render_engine=render_engine,
            currency_resolver=currency_resolver,
        ),
    )


def register_api_handlers(
    *,
    adapters: Mapping[str, SourceAdapter] | None = None,
    run_artifact: Callable[..., Any] | None = None,
    now: date | None = None,
    model: str | None = None,
    render_engine: Any = None,
    currency_resolver: Any = None,
) -> None:
    """Wire the WHOLE API surface into the invoke dispatch registry (§21.1) — the single production
    startup call. Wires `begin-session`/`continue-session` (with the delegation seams), the
    standalone `render`/`fetch-by-id`/`create-folio`/`add-to-folio`, discovery `list`/`get` (fed the
    single-source `CONTINUE_ACTIONS` for the `actions` meta-type), `emit-manifest` (§21.5), and
    `emit-outline` (DR-3 horn (a)/B1). After step 35 EVERY known verb dispatches to a REAL
    handler — ZERO `HandlerNotWired` reachable (`tests/test_action_completeness.py` asserts it
    over the full `invoke.KNOWN_VERBS` set).

    EXPLICIT — never at import (keeps the empty-registry gate tests valid). Seams pass through so a
    test/edge can inject the render engine + currency resolver (no live call)."""
    register_session_handlers(
        adapters=adapters,
        run_artifact=run_artifact,
        now=now,
        model=model,
        render_engine=render_engine,
        currency_resolver=currency_resolver,
    )
    render.register_render_handler(engine=render_engine)
    fetch.register_fetch_handler()
    folio_verbs.register_folio_handlers()
    discovery.register_discovery_handlers(
        resolver=currency_resolver, action_vocab=CONTINUE_ACTIONS
    )
    manifest.register_emit_manifest_handler(resolver=currency_resolver)
    register_emit_outline_handler()
