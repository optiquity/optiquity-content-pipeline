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

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from pipeline import driver
from pipeline.adapters.base import AdapterError, SourceAdapter
from pipeline.adapters.graphify import GraphifyAdapter
from pipeline.api import discovery, fetch, folio_verbs, manifest, render, results
from pipeline.api import invoke as invoke_mod
from pipeline.api import token as token_mod
from pipeline.cascade import CascadeEnv
from pipeline.fanout import FanoutError, SelectionRequest
from pipeline.folios import FolioError, create_folio
from pipeline.grounding import build_pool
from pipeline.m1 import UnknownEntryError
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
    "register_api_handlers",
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
    """The framework root for a workspace store: production builds the store at
    `root/workspaces/<ws>` (invoke §21.1), so the root is its grandparent — the dir the
    §5 registries + `instance/defaults.yaml` live under (`CascadeEnv` reads them there)."""
    return store.root.parent.parent


def _default_adapters() -> dict[str, SourceAdapter]:
    """The real source-adapter set (grounding + the §7.2 commit pin via `pin_commit`)."""
    return {"graphify": GraphifyAdapter()}


def _request_from_fields(fields: Mapping[str, Any]) -> SelectionRequest:
    """Build a `SelectionRequest` from a recipe + per-axis multi-selects (§8)."""
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
    )


def _request_payload(request: SelectionRequest) -> dict[str, Any]:
    """The canonical (JSON-native) request projection stored in the token inputs (§20)."""
    return {
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


def _resolve_from_inputs(
    root: Path, workspace: str, inputs: Mapping[str, Any]
) -> tuple[Plan, CascadeEnv, tuple[Any, ...], dict[str, str]]:
    """Re-resolve the plan from the token's inputs (§21.6 — never a cached plan).

    Reads config + registries only (LLM-free, deterministic): a mid-session config edit
    that changes the resolved plan changes the `plan_hash` — the `plan-stale` guard value.
    The source commit-map is the FROZEN pin from `begin-session` (§21.8), never re-pinned.
    """
    request = _request_from_fields(inputs.get("request") or {})
    env = CascadeEnv(root, workspace=workspace, overrides=inputs.get("overrides") or None)
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


def _begin_session(
    ctx: invoke_mod.HandlerContext, *, adapters: Mapping[str, SourceAdapter]
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """Resolve the plan (`generate = none` — nothing generated yet) and mint the token."""
    root = _root_of(ctx.store)
    try:
        request = _request_from_fields(ctx.params)
    except FanoutError as exc:
        return ([_block(f"begin-session needs a valid recipe + selection (§8): {exc}")], None)
    try:
        env = CascadeEnv(root, workspace=ctx.workspace, overrides=ctx.params.get("overrides"))
    except OverrideError as exc:
        return ([results.make_result(
            results.CODE_INVALID_OVERRIDE, item="overrides", hint=str(exc)
        )], None)

    source_subset = tuple(driver._list_source_ids(root, ctx.workspace))
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

    try:
        plan = resolve_plan(
            env,
            request,
            source_subset=source_subset,
            source_commit=source_commit,
            run_selection=ctx.params.get("run_selection"),
        )
    except UnknownEntryError as exc:
        not_found = results.make_result(results.CODE_NOT_FOUND, item="selection", hint=str(exc))
        return ([not_found], None)

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
    summary = results.ResultItem(
        item="begin-session",
        status="ok",
        ids=ids,
        context={
            "plan_hash": plan.plan_hash,
            "generate": "none",
            "warnings": [w.message for w in plan.warnings],
        },
    )
    return ([summary], token)


# ---------------------------------------------------------------------------
# continue-session (§21.2): the closed action vocabulary + nested-id isolation.
# ---------------------------------------------------------------------------


def _block(hint: str, *, item: str = "continue-session") -> results.ResultItem:
    """A per-item block with NO taxonomy code — for a condition the closed §21.7 vocabulary
    does not name (a malformed call / a driver-level generation failure). Honest: the code
    set is CLOSED, so no code is fabricated; the detail rides `remediation.hint`.

    HARD GATE (step-33 carry-forward, reviewer-ratified): a code-LESS *generation* block is a
    transitional gap, NOT the end state. Before `generate-next` is wired to the LIVE CLI, the
    driver MUST thread the real §21.7 stage codes (`empty-pool`/`hard-limit-exceeded`/
    `low-confidence-grounding`/…) up so a generation failure carries its true code instead of a
    bare hint — see `_generate_next`'s `DriverError` branch. Malformed-CALL blocks (bad recipe,
    unmapped folio, malformed source `connection:`) legitimately have no §21.7 code and stay
    code-less."""
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
    plan, env, pool, source_repos = _resolve_from_inputs(root, ctx.workspace, token.inputs)
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
    only = ctx.params.get("only")
    if isinstance(only, Sequence) and not isinstance(only, str | bytes):
        wanted = {v for v in only if isinstance(v, str)}
        candidates = [item for item in plan.items if item.artifact_id in wanted]
    else:
        seen = set(consumed)
        candidates = [item for item in plan.items if item.artifact_id not in seen]
    batch = candidates[: _batch_size(ctx.params.get("batch_size"), len(candidates))]

    now = now or date.today()
    out: list[results.ResultItem] = []
    for item in batch:
        aid = item.artifact_id
        # §21.8 idempotency floor: correctness comes from id EXISTENCE, never the cursor.
        if is_done(store, aid):
            out.append(results.make_result(
                results.CODE_ALREADY_MATERIALIZED, item=aid, ids={"artifact_id": aid}
            ))
            _append_unique(produced, aid)
        else:
            try:
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
                )
            except driver.DriverError as exc:
                # SM1: a per-item block never fails the batch; siblings proceed. The driver
                # collapses stage blocks into DriverError WITHOUT a taxonomy code, so this is a
                # code-less block carrying only the detail — no code is fabricated (§21.7 closed).
                # CARRY-FORWARD (step-33 reviewer, ratified) — KNOWN gap, HARD GATE: before
                # `generate-next` is wired to the LIVE CLI, the driver MUST thread the real
                # §21.7 stage codes (`empty-pool`/`hard-limit-exceeded`/`low-confidence-grounding`
                # /…) up so this block carries its true code instead of a bare hint. Threading
                # them is a driver-contract restructure that lands with the generation-tier/
                # wiring steps (34-35); a code-less generation block MUST NOT reach a production
                # caller.
                out.append(_block(str(exc), item=aid))
            else:
                deliverable_ids = [d.deliverable_id for d in getattr(result, "deliverables", ())]
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
    plan, _env, _pool, _repos = _resolve_from_inputs(root, ctx.workspace, token.inputs)
    consumed = list(token.cursor.get("consumed", []))
    drift = plan.plan_hash != token.plan_hash
    progress = {
        "consumed": len(consumed),
        "produced": len(token.produced_ids),
        "planned": len(plan.items),
        "plan_hash_token": token.plan_hash,
        "plan_hash_current": plan.plan_hash,
        "drift": drift,
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
    single-source `CONTINUE_ACTIONS` for the `actions` meta-type), and `emit-manifest` (§21.5).
    After step 35 EVERY known verb dispatches to a REAL handler — ZERO `HandlerNotWired` reachable
    (`tests/test_action_completeness.py` asserts it over the full `invoke.KNOWN_VERBS` set).

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
