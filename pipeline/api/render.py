"""The standalone, token-free `render` verb (§21.8, §21.1) — fit + serialize RESOLUTION.

Design authority: `docs/design.md`
  §21.1  — `render` is BOTH a standalone verb and a continue-session action (A1b): render is
           deterministic given an id + render coordinate, so it is fundamentally id-addressed
           and token-free. The `item` is Gate-3-isolated (§21.1); this handler receives an
           already-gated id.
  §21.8  — the fit-resolution rule (FR2) + the serialize-resolution rule (FR7.3) + the
           `force_reconcile` matrix. An UNQUALIFIED render that hits a none-matching cached fit
           serves the latest-minted fit + `render-input-mismatch` (warn) with the
           `force-re-reconcile` remedy; the force re-reconciles → a REVISION fit (`re-reconciled`,
           ok — a NEW id, the old untouched). Serialize auto-mints a revision (`re-serialized`)
           when its inputs drift. Idempotent by id EXISTENCE: a same-inputs re-run mints nothing
           (`already-materialized`). Minting happens HERE only — never in `fetch-by-id`, never at
           `emit-manifest` (§21.5).
  §16/§17 — reconcile/serialize are NOT reimplemented here: this handler ORCHESTRATES
           `pipeline.fit_resolution` (the FR2/force decision), `pipeline.serialize`
           (`resolve_deliverable`), and a `RenderEngine` seam that performs the actual
           reconcile/serialize mints (default: `pipeline.reconcile`/`pipeline.serialize`;
           injected in tests so NO live subscription call ever runs).
  §22.7  — idempotency reads OUTPUT EXISTENCE (`is_done`), never the SSOT; the atomic no-replace
           commit (`write_new`) is the §22.3 existence authority (a same-id re-mint is a benign
           `AlreadyMaterialized` no-op — the old bytes are untouched).

**The engine seam (why).** The RESOLUTION decisions (which fit/deliverable a render resolves to,
whether to mint a baseline/revision, the claim key, the codes) live in THIS handler and are what
the acceptance tests drive; the expensive MINT legs (a reconcile LLM reshape, a pandoc serialize)
are delegated to a `RenderEngine` — the same injection discipline as
`session.continue_session_handler(run_artifact=…)`, so a test never makes a live call and the
blast-radius/idempotency/force paths are exercised hermetically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from pipeline import fit_resolution, ir, payload, presentation, reconcile, serialize
from pipeline.api import invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.asset_loader import filesystem_asset_loader, hash_embedded_assets
from pipeline.canonical import canonical_json_bytes
from pipeline.dispatch import RenderInputs, RenderTarget
from pipeline.fit_resolution import (
    DISPOSITION_FORCED_MATCH,
    DISPOSITION_FORCED_REVISION,
    DISPOSITION_MISMATCH,
    FitCoordinate,
    FitResolution,
)
from pipeline.ids import IdError, parse_id
from pipeline.serialize import (
    DISPOSITION_REVISION as SERIALIZE_DISPOSITION_REVISION,
)
from pipeline.serialize import (
    DeliverableCoordinate,
    SerializeResolution,
)
from pipeline.spine import registry_for
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, is_done, write_new

__all__ = [
    "FitLeg",
    "MintOutcome",
    "RenderEngine",
    "RenderResolution",
    "SerializeLeg",
    "DefaultRenderEngine",
    "render_handler",
    "register_render_handler",
    "resolve_render_target",
]


# ---------------------------------------------------------------------------
# The engine seam (§16/§17): the current preimages + the expensive mint legs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FitLeg:
    """The fit-level render context handed to the engine: the coordinate + the loaded IR."""

    root: Path
    workspace: str
    store: WorkspaceStore
    item: str
    platform: str
    language: str
    canonical_ir: Mapping[str, Any]


@dataclass(frozen=True)
class SerializeLeg:
    """The serialize-level render context: the resolved fit + its coordinate slugs."""

    root: Path
    workspace: str
    store: WorkspaceStore
    fitted_id: str
    fitted_ir: Mapping[str, Any]
    output_type: str
    presentation: str


@dataclass(frozen=True)
class MintOutcome:
    """The side-tagged result of `RenderEngine.mint_deliverable` (GAP-1b, §17 RI12/§14.2).

    An INTERNAL mint carries the layer-2 `output_bytes` + their conventional `extension` (C4); an
    EXTERNAL mint carries the zero-provenance layer-3 contract `payload` (`payload.build_payload`)
    + the dispatch-level `stripped` flag. Both carry the deliverable-level render `binding`. The
    CALLER owns persistence and routes on `side`: internal → layer-2 bytes + render-binding record
    (`_persist_deliverable`); external → the `{binding, side, payload, stripped}` contract record
    (`_persist_external_payload`) — the SAME shape `mvpdemo._mint_external` writes, so the ONE
    `fetch-by-id`/`emit-manifest` reader handles BOTH producers identically (the hard invariant).

    `stripped` reflects the DISPATCH-level provenance strip (`should_strip(writer)` — True for
    epub3/html5, False for pptx/pdf), NOT the contract-level guarantee: the persisted external
    `payload` is ALWAYS zero-provenance because `payload.build_payload` strips unconditionally and
    fail-closed re-checks `has_provenance()` (§17 RI14). It rides here only to match the record
    shape — never present it as the zero-provenance guarantee."""

    binding: Mapping[str, Any]
    side: str  # "internal" | "external"
    output_bytes: bytes | None = None  # internal only (layer-2 bytes)
    extension: str | None = None  # internal only (the §7.4 conventional extension)
    payload: Mapping[str, Any] | None = None  # external only (the RI14 contract payload)
    stripped: bool = False


class RenderEngine(Protocol):
    """The reconcile/serialize seam (§16/§17). `reconcile_preimage`/`serialize_preimage` compute
    the CURRENT effective inputs preimages the resolution rules compare against;
    `mint_fit`/`mint_deliverable` perform the actual (expensive) mints, returning the reshaped IR
    + the fit-binding, and (GAP-1b) a side-tagged `MintOutcome` — internal layer-2 bytes + the
    render-binding + the layer-2 extension, OR the external zero-provenance contract payload + the
    render-binding + the strip flag. Injected in tests so no live subscription call ever runs (the
    same seam the reconcile/serialize/compose tests use)."""

    def reconcile_preimage(self, leg: FitLeg) -> Mapping[str, Any]: ...

    def mint_fit(
        self, leg: FitLeg, *, preimage: Mapping[str, Any], revision: bool
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]: ...

    def serialize_preimage(self, leg: SerializeLeg) -> Mapping[str, Any]: ...

    def mint_deliverable(
        self, leg: SerializeLeg, *, preimage: Mapping[str, Any], serialize_revision: bool
    ) -> MintOutcome: ...


# ---------------------------------------------------------------------------
# The render handler (§21.8): resolve fit → (mint|serve) → resolve serialize → (mint|serve).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderResolution:
    """The LLM-FREE render resolution (§21.8/§22.2): the predictable fitted-id + deliverable-id
    plus the fit leg/preimage/resolution the (paid) fit mint consumes. Produced by
    `resolve_render_target` from the SAME `_resolve_fit`/`_resolve_deliverable` primitives the
    `render` handler (`_render`, the materializer) resolves through — so the deliverable-id a DR-1
    async transport (the HTTP shim) keys/polls a job on is BY CONSTRUCTION the id the handler
    materializes (no hand-synced fork; the render analogue of `session.plan_next_batch_ids`).

    `block` carries a validation / not-found / coordinate short-circuit (the handler returns it
    verbatim as its one ResultItem; the shim maps its presence to a blocked submit, never a job).
    When `block` is set every id field is None.

    `fit_materialized` records whether the fit's IR was ALREADY present at resolve time: True → the
    serialize resolution read the STORED fitted IR (a local pandoc reader — still LLM-free, no paid
    reshape); False → the fit must still MINT (the paid reshape), so its IR is absent and the
    deliverable is necessarily a FRESH BASELINE (no prior deliverables under an unmaterialized
    fitted-id) whose id is preimage-INDEPENDENT — resolvable WITHOUT the paid call."""

    block: results.ResultItem | None
    item: str | None = None
    platform: str | None = None
    language: str | None = None
    output_type: str | None = None
    presentation: str | None = None
    force: bool = False
    root: Path | None = None
    coordinate: FitCoordinate | None = None
    fit_leg: FitLeg | None = None
    fit_preimage: Mapping[str, Any] | None = None
    fit_res: FitResolution | None = None
    fitted_id: str | None = None
    fit_materialized: bool = False
    deliverable_id: str | None = None


@dataclass(frozen=True)
class _DeliverableResolution:
    """The serialize half of the resolution (`_resolve_deliverable`) — the predictable
    deliverable-id + the serialize leg/preimage/resolution the (local) deliverable mint consumes.
    `block` short-circuits a coordinate error; when set every other field is None. `ser_leg`/
    `ser_preimage` are None on the fit-not-yet-materialized baseline path (no IR to build them)."""

    block: results.ResultItem | None
    del_coord: DeliverableCoordinate | None = None
    ser_leg: SerializeLeg | None = None
    ser_preimage: Mapping[str, Any] | None = None
    ser_res: SerializeResolution | None = None
    deliverable_id: str | None = None


def _resolve_fit(
    store: WorkspaceStore, params: Mapping[str, Any], *, engine: RenderEngine, workspace: str
) -> RenderResolution:
    """LLM-FREE FIT resolution (§16 FR2 / the force matrix) → the predictable fitted-id + the fit
    leg/preimage/resolution. Returns a `RenderResolution` carrying ONLY the fit fields (the
    deliverable fields stay None); `block` is set on a validation / not-found / coordinate error.
    The SINGLE fit-resolution path — shared by `_render` (the materializer) and
    `resolve_render_target` (the shim's predictable-id resolver), so there is no forked copy."""
    item = params.get("item")
    coords = _coordinates(params)
    if not isinstance(item, str) or not item or coords is None:
        return RenderResolution(block=_block(
            "render needs `item` + platform/language/output_type/presentation (§21.2)"
        ))
    platform, language, output_type, presentation = coords
    force = bool(params.get("force_reconcile", False))

    canonical_record = _read_record(store, item)
    if canonical_record is None:
        return RenderResolution(block=results.make_result(
            results.CODE_NOT_FOUND, item=item, ids={"id": item},
            hint=f"no artifact record for {item!r} in this workspace (§21.8)",
        ))
    # GAP-1a: read via `ir.unwrap_ir`, tolerating BOTH persisted shapes — a FITTED/render record
    # wraps the IR under `["ir"]`; a fresh COMPOSE record IS the raw envelope. The old
    # `"ir" not in record` gate 404'd EVERY real composed artifact (compose persists raw); this
    # gates on a REAL absence (`record is None`) and unwraps whichever shape is stored (§15 RI4).
    canonical_ir = ir.unwrap_ir(canonical_record)

    root = store.root.parent.parent
    fit_leg = FitLeg(
        root=root, workspace=workspace, store=store, item=item,
        platform=platform, language=language, canonical_ir=canonical_ir,
    )
    try:
        coordinate = FitCoordinate(artifact_id=item, platform=platform, language=language)
    except fit_resolution.FitResolutionError as exc:
        return RenderResolution(block=_block(f"render: {exc}"))
    fit_preimage = engine.reconcile_preimage(fit_leg)
    fit_bindings = _fit_bindings(store, item, platform, language)
    if force:
        fit_res = fit_resolution.resolve_force_reconcile(coordinate, fit_bindings, fit_preimage)
    else:
        fit_res = fit_resolution.resolve_fit(coordinate, fit_bindings, fit_preimage)
    fitted_id = fit_resolution.resolved_fitted_id(fit_res, coordinate)
    return RenderResolution(
        block=None, item=item, platform=platform, language=language,
        output_type=output_type, presentation=presentation, force=force, root=root,
        coordinate=coordinate, fit_leg=fit_leg, fit_preimage=fit_preimage,
        fit_res=fit_res, fitted_id=fitted_id,
    )


def _resolve_deliverable(
    store: WorkspaceStore,
    workspace: str,
    root: Path,
    fitted_id: str,
    output_type: str,
    presentation: str,
    *,
    engine: RenderEngine,
    fitted_ir: Mapping[str, Any] | None,
) -> _DeliverableResolution:
    """LLM-FREE SERIALIZE resolution (§17 FR7.3) → the predictable deliverable-id + the serialize
    leg/preimage/resolution. The SINGLE serialize-resolution path — shared by `_render`
    (post-fit-mint, with the materialized IR) and `resolve_render_target` (pre-mint prediction).

    `fitted_ir` is the fit's materialized IR when present; when None the fit is NOT yet materialized
    (it will MINT the paid reshape), so there are NO deliverables under its (fresh) fitted-id and
    the resolution is necessarily a BASELINE MISS whose id is preimage-INDEPENDENT — resolved
    WITHOUT computing a serialize preimage (no paid call needed to key the job). A fresh fit yields
    the SAME baseline deliverable-id whether resolved here pre-mint or by `_render` post-mint, so
    the shim's predicted id == the id the handler materializes."""
    try:
        del_coord = DeliverableCoordinate(
            fitted_id=fitted_id, output_type=output_type, presentation=presentation
        )
    except serialize.SerializeError as exc:
        return _DeliverableResolution(block=_block(f"render: {exc}"))
    render_bindings = _render_bindings(store, fitted_id, output_type, presentation)
    if fitted_ir is None:
        # The fit is unmaterialized → its fresh fitted-id has no deliverables (a deliverable-id
        # embeds its fitted-id's coordinates), so `render_bindings` is empty and
        # `resolve_deliverable` returns a BASELINE MISS — an empty preimage suffices because a
        # baseline id never consults the serialize digest (§21.8). Goes through the SAME shared
        # `resolve_deliverable`/`resolved_deliverable_id` the materialized path uses (no fork).
        ser_leg = None
        ser_preimage = None
        ser_res = serialize.resolve_deliverable(del_coord, render_bindings, {})
    else:
        ser_leg = SerializeLeg(
            root=root, workspace=workspace, store=store, fitted_id=fitted_id,
            fitted_ir=fitted_ir, output_type=output_type, presentation=presentation,
        )
        ser_preimage = engine.serialize_preimage(ser_leg)
        ser_res = serialize.resolve_deliverable(del_coord, render_bindings, ser_preimage)
    deliverable_id = serialize.resolved_deliverable_id(ser_res, del_coord)
    return _DeliverableResolution(
        block=None, del_coord=del_coord, ser_leg=ser_leg, ser_preimage=ser_preimage,
        ser_res=ser_res, deliverable_id=deliverable_id,
    )


def resolve_render_target(
    store: WorkspaceStore,
    params: Mapping[str, Any],
    *,
    engine: RenderEngine | None = None,
    workspace: str | None = None,
) -> RenderResolution:
    """Resolve a `render` request to its PREDICTABLE fitted-id + deliverable-id, LLM-FREE (§22.2),
    via the SAME `_resolve_fit`/`_resolve_deliverable` primitives the `render` handler materializes
    through — so a DR-1 async transport (the HTTP shim) can KEY + POLL a render job on the
    deliverable-id BEFORE the paid reshape and be certain the keyed id == the id the handler
    materializes (no hand-synced fork; the render analogue of `session.plan_next_batch_ids`).

    The deliverable-id is resolvable WITHOUT the paid call in BOTH cases: a fit that is already
    materialized reads the stored IR (a local pandoc reader — still LLM-free) and resolves the FULL
    serialize; a fit that must still mint yields a fresh BASELINE deliverable whose id is
    preimage-independent. `block` is set (ids None) on a validation / not-found / coordinate error.
    `engine` defaults to the production `DefaultRenderEngine` (injected out in tests); `workspace`
    defaults to the store's own name."""
    e = engine if engine is not None else DefaultRenderEngine()
    ws = workspace if workspace is not None else store.root.name
    fit = _resolve_fit(store, params, engine=e, workspace=ws)
    if fit.block is not None:
        return fit
    assert fit.fitted_id is not None  # a non-block fit always fixes a fitted-id
    fit_materialized = is_done(store, fit.fitted_id)
    fitted_ir = _load_ir(store, fit.fitted_id) if fit_materialized else None
    deliverable = _resolve_deliverable(
        store, ws, fit.root, fit.fitted_id, fit.output_type, fit.presentation,
        engine=e, fitted_ir=fitted_ir,
    )
    if deliverable.block is not None:
        return replace(fit, block=deliverable.block)
    return replace(
        fit, fit_materialized=fit_materialized, deliverable_id=deliverable.deliverable_id
    )


def _render(
    ctx: invoke_mod.HandlerContext, *, engine: RenderEngine
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """One `render` call (§21.8): fit resolution + serialize resolution over the store, minting
    baseline/revision ids via the engine ONLY when the resolution says so; idempotent by id
    existence, and `force_reconcile` mints a NEW revision fit, never mutating the old. The
    resolution rides the SHARED `_resolve_fit`/`_resolve_deliverable` primitives (the SAME ones the
    DR-1 shim's `resolve_render_target` uses to predict the id — one resolution path, no fork)."""
    fit = _resolve_fit(ctx.store, ctx.params, engine=engine, workspace=ctx.workspace)
    if fit.block is not None:
        return ([fit.block], None)
    item, fitted_id = fit.item, fit.fitted_id
    # GAP-10: ONE workspace-scoped claim registry (fresh minted holder, RV-4) brackets BOTH paid
    # mints below — the SAME §22.3 acquire→work→release the generate-next spine runs (spine S1→S6).
    # Constructing it touches only the workspace `claims/` dir (a `mkdir` via `store.claims_dir`),
    # never a claim file — so the no-acquire cache-hit path stays behaviour-neutral (an empty dir
    # is invisible to the byte-snapshots, and a cache-hit implies a prior mint already created it).
    registry = registry_for(ctx.store)

    # GAP-10: bracket the PAID fit mint in a §22.3 claim (mirror the generate-next spine S1→S6).
    # A bare check-then-mint let two concurrent identical renders BOTH pass `not is_done` and BOTH
    # run the paid reshape — a double-spend. The content-addressed fitted-id is the claim key, so
    # both contenders `acquire` the SAME key: exactly one wins, the other gets `claim-held` and is
    # re-driven by id. Release rides a `finally` — even an `_EngineError` leaves no dangling claim.
    if fit.fit_res.should_mint and not is_done(ctx.store, fitted_id):
        acq = fit_resolution.claim_fit(registry, fit.fit_res, fit.coordinate)
        if not acq.acquired:
            return ([_claim_held(item, fitted_id, holder=acq.holder)], None)
        try:
            # Re-check UNDER the claim: another render may have materialized (and released) in the
            # check→acquire window — fall through to fetch, never re-spend the mint (acquire-then-
            # is_done-became-true race).
            if not is_done(ctx.store, fitted_id):
                fitted_ir, fit_binding = engine.mint_fit(
                    fit.fit_leg, preimage=fit.fit_preimage, revision=fit.fit_res.revision
                )
                if fit_binding.get("fitted_id") != fitted_id:
                    return ([_block(
                        f"render: engine minted fit {fit_binding.get('fitted_id')!r} but the "
                        f"resolution fixed {fitted_id!r} (§7.4)"
                    )], None)
                _persist(ctx.store, fitted_id, {"ir": fitted_ir, "binding": fit_binding})
        finally:
            registry.release(fitted_id)  # holder-checked (B4-4b); no-op if we never held
    fitted_ir = _load_ir(ctx.store, fitted_id)
    if fitted_ir is None:
        return ([_block(f"render: resolved fit {fitted_id!r} has no stored IR (§16)")], None)

    # -- SERIALIZE resolution (§17 FR7.3) — the SHARED primitive, now with the materialized IR (a
    #    fresh fit resolves to the SAME baseline deliverable-id the shim predicted pre-mint) -------
    deliverable = _resolve_deliverable(
        ctx.store, ctx.workspace, fit.root, fitted_id, fit.output_type, fit.presentation,
        engine=engine, fitted_ir=fitted_ir,
    )
    if deliverable.block is not None:
        return ([deliverable.block], None)
    ser_res = deliverable.ser_res
    deliverable_id = deliverable.deliverable_id

    output_path: str | None = None
    if ser_res.should_mint and not is_done(ctx.store, deliverable_id):
        # GAP-10: the SAME §22.3 claim bracket for the paid deliverable mint (`claim_deliverable`
        # mirrors `claim_fit`; the content-addressed deliverable-id is the key). Held → the
        # re-drivable `claim-held`; release in a `finally`.
        acq = serialize.claim_deliverable(registry, ser_res, deliverable.del_coord)
        if not acq.acquired:
            return ([_claim_held(item, fitted_id, deliverable_id, holder=acq.holder)], None)
        try:
            if not is_done(ctx.store, deliverable_id):
                mint = engine.mint_deliverable(
                    deliverable.ser_leg,
                    preimage=deliverable.ser_preimage,
                    serialize_revision=ser_res.revision,
                )
                render_binding = mint.binding
                if render_binding.get("deliverable_id") != deliverable_id:
                    return ([_block(
                        f"render: engine minted deliverable "
                        f"{render_binding.get('deliverable_id')!r} but the resolution fixed "
                        f"{deliverable_id!r} (§7.4)"
                    )], None)
                # GAP-1b: persist by side. INTERNAL → the layer-2 bytes + render-binding record (the
                # existing path); EXTERNAL → the zero-provenance contract payload as the
                # `{binding, side, payload, stripped}` record (`mvpdemo._mint_external`'s exact
                # shape). An external deliverable has NO layer-2 bytes: the id rides `ids` and
                # retrieval is the existing `fetch-by-id` (§21.5/§21.8), so `output_path` stays None
                # → `_result` emits `output=None` for the external side.
                if mint.side == "external":
                    _persist_external_payload(ctx.store, deliverable_id, mint)
                else:
                    output_path = _persist_deliverable(
                        ctx.store, deliverable_id, render_binding,
                        mint.output_bytes, mint.extension,
                    )
            else:
                # is_done became true under the claim (another render won) — fall through to fetch.
                output_path = _existing_deliverable_path(ctx.store, deliverable_id)
        finally:
            registry.release(deliverable_id)  # holder-checked (B4-4b)
    else:
        output_path = _existing_deliverable_path(ctx.store, deliverable_id)

    return ([_result(item, fitted_id, deliverable_id, fit.fit_res, ser_res, output_path)], None)


def _result(
    item: str,
    fitted_id: str,
    deliverable_id: str,
    fit_res: FitResolution,
    ser_res: SerializeResolution,
    output_path: str | None,
) -> results.ResultItem:
    """Map the two resolutions to ONE §21.7 ResultItem (the code precedence of §21.8)."""
    ids = {
        "item": item,
        "fitted_id": fitted_id,
        "deliverable_id": deliverable_id,
        "deliverable_ids": [deliverable_id],
    }
    output = {"path": output_path} if output_path else None

    # 1. An UNQUALIFIED stale-fit serve → `render-input-mismatch` (warn) + the force remedy (§21.8).
    if fit_res.disposition == DISPOSITION_MISMATCH and fit_res.warning is not None:
        w = fit_res.warning
        return results.make_result(
            results.CODE_RENDER_INPUT_MISMATCH,
            item=item,
            ids=ids,
            output=output,
            context={
                "served_fitted_id": w.served_fitted_id,
                "current_inputs_digest": w.current_inputs_digest,
                "differing_components": list(w.differing_components),
            },
            hint="render served a cached fit whose reconcile inputs differ from current; "
            "force_reconcile to re-reconcile (§21.8)",
        )
    # 2. A FORCED revision fit → `re-reconciled` (ok): a NEW fitted-id + deliverable, old untouched.
    if fit_res.disposition == DISPOSITION_FORCED_REVISION:
        return results.make_result(
            results.CODE_RE_RECONCILED, item=item, ids=ids, output=output,
            hint="force_reconcile minted a revision fit (§21.8)",
        )
    # 3. A serialize revision auto-mint → `re-serialized` (ok): the free+deterministic sibling.
    if ser_res.disposition == SERIALIZE_DISPOSITION_REVISION:
        return results.make_result(
            results.CODE_RE_SERIALIZED, item=item, ids=ids, output=output,
            hint="render auto-minted a serialize revision (§17/§21.8)",
        )
    # 4. An idempotent re-issue (forced-match / a hit already materialized) → already-materialized.
    context = {
        "fit_disposition": fit_res.disposition,
        "serialize_disposition": ser_res.disposition,
    }
    idempotent = (
        fit_res.disposition == DISPOSITION_FORCED_MATCH
        or ser_res.code == results.CODE_ALREADY_MATERIALIZED
    )
    if idempotent:
        return results.make_result(
            results.CODE_ALREADY_MATERIALIZED, item=item, ids=ids, output=output, context=context
        )
    # 5. A fresh baseline render → plain ok.
    return results.ResultItem(item=item, status="ok", ids=ids, output=output, context=context)


# ---------------------------------------------------------------------------
# Store reads/writes (the §22.7 existence authority — no SSOT).
# ---------------------------------------------------------------------------


def _coordinates(params: Mapping[str, Any]) -> tuple[str, str, str, str] | None:
    """The four render coordinate slugs (§21.2), accepting `output_type`/`output-type`."""
    platform = params.get("platform")
    language = params.get("language")
    output_type = params.get("output_type", params.get("output-type"))
    presentation = params.get("presentation")
    if all(isinstance(v, str) and v for v in (platform, language, output_type, presentation)):
        return platform, language, output_type, presentation  # type: ignore[return-value]
    return None


def _read_record(store: WorkspaceStore, id_str: str) -> Mapping[str, Any] | None:
    import json

    try:
        raw = store.output_path(id_str).read_bytes()
    except (FileNotFoundError, IsADirectoryError, IdError):
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, Mapping) else None


def _load_ir(store: WorkspaceStore, fitted_id: str) -> Mapping[str, Any] | None:
    record = _read_record(store, fitted_id)
    if record is None:
        return None
    ir = record.get("ir")
    return ir if isinstance(ir, Mapping) else None


def _fit_bindings(
    store: WorkspaceStore, item: str, platform: str, language: str
) -> list[Mapping[str, Any]]:
    """Every stored fit-binding under the `artifact.platform.language` prefix (§21.8) — baseline
    and revision alike (fit_revision distinguishes them under the prefix)."""
    root_hex = parse_id(item).root_hex
    out: list[Mapping[str, Any]] = []
    for entry in sorted(store.artifacts_dir.iterdir()) if store.artifacts_dir.is_dir() else []:
        if not entry.is_file():
            continue
        try:
            parsed = parse_id(entry.name)
        except IdError:
            continue
        if (
            parsed.level != "fitted"
            or parsed.root_hex != root_hex
            or parsed.platform != platform
            or parsed.language != language
        ):
            continue
        record = _read_record(store, entry.name)
        if record is not None and isinstance(record.get("binding"), Mapping):
            out.append(record["binding"])
    return out


def _render_bindings(
    store: WorkspaceStore, fitted_id: str, output_type: str, presentation: str
) -> list[Mapping[str, Any]]:
    """Every stored render-binding under the `fitted-id.output-type.presentation` prefix (§21.8)."""
    want = parse_id(fitted_id)
    out: list[Mapping[str, Any]] = []
    deliverables_dir = store.deliverables_dir
    for entry in sorted(deliverables_dir.iterdir()) if deliverables_dir.is_dir() else []:
        if not entry.is_file():
            continue
        try:
            parsed = parse_id(entry.name)
        except IdError:
            continue
        if parsed.level != "deliverable":
            continue
        same = (
            parsed.root_hex == want.root_hex
            and parsed.platform == want.platform
            and parsed.language == want.language
            and parsed.fit_revision == want.fit_revision
            and parsed.output_type == output_type
            and parsed.presentation == presentation
        )
        if not same:
            continue
        record = _read_record(store, entry.name)
        if record is not None and isinstance(record.get("binding"), Mapping):
            out.append(record["binding"])
    return out


def _persist(store: WorkspaceStore, id_str: str, record: Mapping[str, Any]) -> None:
    """Atomic no-replace commit of an id-keyed record (§22.3 existence authority). An
    already-materialized target is a benign no-op — the winner's bytes are untouched."""
    try:
        write_new(store.output_path(id_str), canonical_json_bytes(record))
    except AlreadyMaterializedError:
        pass  # idempotent — the id already exists; the old bytes stand (§22.3)


def _persist_deliverable(
    store: WorkspaceStore,
    deliverable_id: str,
    render_binding: Mapping[str, Any],
    output_bytes: bytes,
    extension: str,
) -> str:
    """Persist the layer-2 bytes + the render-binding record (deliverable-level, §18). Returns the
    workspace-relative bytes path."""
    bytes_path = store.bytes_path(deliverable_id, extension)
    try:
        write_new(bytes_path, output_bytes)
    except AlreadyMaterializedError:
        pass
    rel = str(bytes_path.relative_to(store.root))
    layer2 = {"path": rel, "byte_count": len(output_bytes)}
    _persist(store, deliverable_id, {"binding": render_binding, "layer2": layer2})
    return rel


def _persist_external_payload(
    store: WorkspaceStore, deliverable_id: str, mint: MintOutcome
) -> None:
    """Persist the layer-3 EXTERNAL contract record (deliverable-level, §17 RI14/§21.5/§14.2).

    HARD INVARIANT (GAP-1b): writes EXACTLY the `{binding, side, payload, stripped}` shape
    `mvpdemo._mint_external` persists, so the ONE `fetch-by-id`/`emit-manifest` reader handles
    BOTH producers identically (a divergent shape is a silent two-reader defect). No layer-2
    bytes: an external deliverable is handed off as the zero-provenance contract payload for an
    external actor to render layer-4 — the id rides `ids` and retrieval is the existing
    `fetch-by-id` (§21.8), never a bytes sibling. The atomic no-replace commit rides `_persist`
    (the §22.3 existence authority; a same-id re-mint is a benign no-op)."""
    _persist(
        store,
        deliverable_id,
        {
            "binding": mint.binding,
            "side": mint.side,
            "payload": mint.payload,
            "stripped": mint.stripped,
        },
    )


def _existing_deliverable_path(store: WorkspaceStore, deliverable_id: str) -> str | None:
    record = _read_record(store, deliverable_id)
    if isinstance(record, Mapping) and isinstance(record.get("layer2"), Mapping):
        path = record["layer2"].get("path")
        return path if isinstance(path, str) else None
    return None


def _block(hint: str) -> results.ResultItem:
    """A code-less block (§21.7 closed) — a malformed render call the taxonomy does not name."""
    return results.ResultItem(item="render", status="block", remediation={"hint": hint})


def _claim_held(
    item: str,
    fitted_id: str,
    deliverable_id: str | None = None,
    *,
    holder: str | None = None,
) -> results.ResultItem:
    """The re-drivable `claim-held` (GAP-10) — another render holds a LIVE §22.3 claim on this id
    (a paid mint is in progress), so this contender skips the mint and the caller re-drives by id.

    The SAME existing coded outcome the generate-next spine returns for a held work unit
    (`parallel.result_for_spine`) — one uniform liveness model, no new taxonomy code. A `warn`,
    never a `block`: the work is in flight, not refused. `holder` (the incumbent, when the claim
    is readable) rides `context` exactly as the spine mapping records it."""
    ids: dict[str, Any] = {"item": item, "fitted_id": fitted_id}
    if deliverable_id is not None:
        ids["deliverable_id"] = deliverable_id
    return results.make_result(
        results.CODE_CLAIM_HELD,
        item=item,
        ids=ids,
        context={"holder": holder} if holder is not None else None,
        hint="another render holds a live claim on this id — re-drive by id; exactly one "
        "contender mints (§22.3/§21.8)",
    )


# ---------------------------------------------------------------------------
# B1 (§5.3 PD3/PD5) — presentation lowering on the render-verb minting path.
# ---------------------------------------------------------------------------


def _lower_for_leg(env: Any, leg: SerializeLeg, target: RenderTarget) -> RenderInputs:
    """Lower the resolved presentation for one serialize leg (B1) — the ONE lowering both
    `_serialize_inputs` (the preimage) and `mint_deliverable` (the dispatched flags) consume, so
    the dispatched flags and the identity preimage can NEVER diverge (§17 FR7.1 watch-item). The
    render engine resolves the presentation at M1 level (best-effort standalone path, no M2 fold —
    consistent with its existing character); the `plain` floor lowers to the empty RenderInputs
    (byte-identical to the retired `lower_plain(target)`, PD5 zero-churn)."""
    entry = env.resolver.resolve("presentations", leg.presentation)
    pres = presentation.presentation_from_entry(
        {**entry.defaults(), **entry.effective, "id": entry.id},
        # B (§17/step-29): the REAL filesystem asset loader replaces the deferred raise, FENCED to
        # `<root>/presentations` (F3, CLAUDE.md rule 2) — resolves the asset path against `leg.root`
        # and refuses anything outside `presentations/` (no client `workspaces/…` reach-in).
        load_asset=filesystem_asset_loader(
            resolve_base=leg.root, contain_root=leg.root / "presentations"
        ),
        defaults=entry.defaults(),
    )
    return presentation.lower(pres, target.writer, leg.output_type, target_engine=target.engine)


# ---------------------------------------------------------------------------
# The default engine (best-effort real reconcile/serialize for the passthrough case).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DefaultRenderEngine:
    """The production render engine — real `pipeline.reconcile`/`pipeline.serialize` for the
    passthrough (`pass`-strategy, empty-advisory) case; richer recipe-aware resolution rides the
    gated transport-wiring step (§21.9). Injected out in every test (no live call).

    `model` pins the reconcile writer (default None). The reconcile-inputs are read minimally
    from live config — the platform hard-limits — with `pass` strategy and empty advisory/
    render-dims (the standalone-render passthrough); a caller needing the full recipe-scoped
    inputs injects its own engine."""

    model: str | None = None
    #: Memoizes `serialize_fitted(leg.fitted_ir)` by fitted-id so the two-phase seam shells the
    #: pinned pandoc reader ONCE per fitted artifact — `serialize_preimage` (RT: it reads the AST to
    #: compute the SD-5 flag) and `mint_deliverable` consult the SAME units. `init=False` /
    #: `compare=False` keep the frozen dataclass's value-semantics; the dict is MUTATED in place
    #: (allowed on a frozen instance), never reassigned.
    _fitted_units_cache: dict[str, Any] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )

    def _fitted_units(self, leg: SerializeLeg) -> list[Any]:
        """The `serialize_fitted` units for this leg's fitted IR, memoized by fitted-id (§17). The
        two-phase seam consults it in `serialize_preimage` and again in `mint_deliverable`, so the
        pinned pandoc reader runs once, not twice, on the typed standalone-render path."""
        units = self._fitted_units_cache.get(leg.fitted_id)
        if units is None:
            units = serialize.serialize_fitted(leg.fitted_ir)
            self._fitted_units_cache[leg.fitted_id] = units
        return units

    def reconcile_preimage(self, leg: FitLeg) -> Mapping[str, Any]:
        request = self._reconcile_request(leg)
        return reconcile.reconcile_inputs_preimage(request)

    def mint_fit(
        self, leg: FitLeg, *, preimage: Mapping[str, Any], revision: bool
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        request = self._reconcile_request(leg)
        outcome = reconcile.reconcile(request, revision=revision, model=self.model)
        if outcome.status != "ok" or outcome.fitted_ir is None or outcome.fit_binding is None:
            raise _EngineError(
                f"reconcile did not fit {leg.item} (status={outcome.status} code={outcome.code})"
            )
        return outcome.fitted_ir, outcome.fit_binding

    def serialize_preimage(self, leg: SerializeLeg) -> Mapping[str, Any]:
        from pipeline.dispatch import render_target_from_entry
        from pipeline.filters.citeproc_enablement import has_citations
        from pipeline.filters.provenance_strip import should_strip
        from pipeline.filters.section_attr_validity import strip_section_attrs

        target_values, render_inputs_view, render_inputs = self._serialize_inputs(leg)
        # RT: BOTH serialize-filter versions (§17 R-4 family) are derived from the fitted AST HERE,
        # BEFORE dispatch (two-phase), from ONE `_fitted_units` read — the memo makes it a single
        # pinned-pandoc reader shell that `mint_deliverable` reuses. Each OMIT-WHEN-ABSENT version
        # rides the preimage so the deliverable's id matches the bytes dispatch emits (and
        # `current_serialize_digest` reports no spurious drift). The SD-5 section-attr strip is
        # WRITER-GATED (`should_strip`, public writers only); C6 citeproc is CONTENT-driven (any
        # writer whose AST carries a `Cite`), so it reads the units UNCONDITIONALLY. A non-typed /
        # non-citing render yields False for its flag → the key is omitted → byte-identical to the
        # pre-C6/pre-RT corpus. (The provenance strip is order-independent for both detections, so
        # it need not run here.)
        units = self._fitted_units(leg)
        target = render_target_from_entry(target_values)
        citeproc_enabled = any(has_citations(unit.ast) for unit in units)
        section_attr_transformed = False
        if should_strip(target.writer):
            section_attr_transformed = any(strip_section_attrs(unit.ast)[1] for unit in units)
        # B (F1/F5): the SAME containment base `store.root` A proved (asset_ref.py:13-19, S5). The
        # two-phase seam re-runs A's FULL gate here on `units[0].ast` (BEFORE dispatch) so the id it
        # mints records EXACTLY the fold `mint_deliverable` will dispatch. An uncontained/raw-markup
        # body REFUSES the whole render (no bytes read); md/plain embed nothing → `()` → zero churn.
        base = leg.store.root
        embedded_assets = hash_embedded_assets(units[0].ast, target.writer, store_root=base)
        # C7 (S3×S4): thread the lowered `RenderInputs.csl` labeled field (kept OUT of the
        # `render_inputs_view` by `render_inputs_to_mapping`). It enters the preimage's
        # render_inputs ONLY when `citeproc_enabled` — so a citation-less csl-set render matches
        # `plain` (S4), and `mint_deliverable` dispatches the SAME `render_inputs` (its `--csl` and
        # this hash agree).
        return serialize.serialize_inputs_preimage(
            render_target=target_values,
            render_inputs=render_inputs_view,
            section_attr_transformed=section_attr_transformed,
            citeproc_enabled=citeproc_enabled,
            csl=render_inputs.csl,
            # B: the body-figure embed fold — present ONLY for an html5/docx figure render.
            assets_embedded=bool(embedded_assets),
            embedded_assets=embedded_assets,
        )

    def mint_deliverable(
        self, leg: SerializeLeg, *, preimage: Mapping[str, Any], serialize_revision: bool
    ) -> MintOutcome:
        from pipeline.dispatch import dispatch, render_target_from_entry

        # B1: the SAME lowered `render_inputs` the preimage was built from (`_serialize_inputs`)
        # drives the dispatch flags — one lowering, so flags and preimage cannot diverge.
        target_values, _render_inputs_view, render_inputs = self._serialize_inputs(leg)
        units = self._fitted_units(leg)
        if len(units) != 1:
            raise _EngineError(
                f"standalone render expects one serialized document, got {len(units)}"
            )
        target = render_target_from_entry(target_values)
        # B (F1/F5): recompute the fold at mint time (the F1 gate re-runs on the persisted AST
        # BEFORE dispatch — an uncontained/raw-markup body refuses and never reaches pandoc). `base`
        # is `store.root` (S5); `resource_paths` is emitted ONLY for a figure-bearing embed writer,
        # ordered store-root FIRST then repo-root (`leg.root`) — the SAME base the preimage folded.
        base = leg.store.root
        embedded_assets = hash_embedded_assets(units[0].ast, target.writer, store_root=base)
        resource_paths = (str(base), str(leg.root)) if embedded_assets else ()
        # `serialize_fitted` shells the pinned pandoc READER (§17 RI7) both sides; the external
        # dispatch itself is pure-Python (persist AST + hand off, dispatch.py) — the pandoc
        # dependency is the reader, not an epub/pptx binary (why the C6 tests ride the pandoc gate).
        dout = dispatch(
            target, units[0].ast, render_inputs=render_inputs, resource_paths=resource_paths
        )
        fit_record = _read_record(leg.store, leg.fitted_id)
        fit_binding = fit_record.get("binding", {}) if isinstance(fit_record, Mapping) else {}
        render_binding = serialize.build_render_binding(
            fitted_id=leg.fitted_id,
            output_type=leg.output_type,
            presentation=leg.presentation,
            preimage=preimage,
            fit_binding_ref=fit_binding,
            serialize_revision=serialize_revision,
        )

        # GAP-1b: route on `target.side` (surfaced by `render_target_from_entry`). EXTERNAL is now
        # a FIRST-CLASS path — the old pre-branch `dout.output_bytes is None` guard (F2) fired on
        # EVERY external target (external `output_bytes` is always None) and is deleted; the side
        # branch replaces it. EXTERNAL → the fitted AST is routed through the zero-provenance
        # layer-3 contract payload builder (`payload.build_payload`, unconditional fail-closed
        # strip, §17 RI14). INTERNAL → the pinned-pandoc layer-2 bytes path (unchanged).
        if target.side == "external":
            contract = payload.build_payload(
                ast=units[0].ast,
                deliverable_id=render_binding["deliverable_id"],
                render_target=target,
                pin_bundle=render_binding["pin_bundle"],
                fitted_ir=leg.fitted_ir,
                requested_output_types=[leg.output_type],
                extension=serialize.extension_for(leg.output_type),
                # C10: carry the citeproc REQUIREMENT (content-gated) + the C7 csl style so the
                # external actor resolves `[@key]` under the pinned pandoc + the venue's style.
                citeproc_enabled=dout.citeproc_enabled,
                csl=render_inputs.csl,
            )
            return MintOutcome(
                binding=render_binding,
                side="external",
                payload=contract,
                stripped=dout.stripped,
            )

        # INTERNAL: dispatch guarantees layer-2 bytes for an internal target (`capability_check`
        # admits only in-system writers → the passthrough/pandoc path always sets `output_bytes`),
        # so no pre-branch None-guard is needed — the deleted F2 guard was dead for internal and
        # wrong for external.
        return MintOutcome(
            binding=render_binding,
            side="internal",
            output_bytes=dout.output_bytes,
            extension=serialize.extension_for(leg.output_type),
            stripped=dout.stripped,
        )

    def _reconcile_request(self, leg: FitLeg) -> reconcile.ReconcileRequest:
        from pipeline.cascade import CascadeEnv
        from pipeline.ids import delta_vs_floor  # noqa: F401 — parity with the driver's read

        env = CascadeEnv(leg.root, workspace=leg.workspace)
        entry = env.resolver.resolve("platforms", leg.platform)
        schema = env.resolver.schema("platforms")
        limits = dict(entry.effective.get("hard_limits") or {})
        floor = dict(schema.attributes["hard_limits"].default or {})
        return reconcile.ReconcileRequest(
            canonical_ir=leg.canonical_ir,
            artifact_id=leg.item,
            platform=leg.platform,
            language=leg.language,
            source_language=leg.language,
            strategy="pass",
            hard_limits=limits,
            hard_limit_defaults=floor,
        )

    def _serialize_inputs(
        self, leg: SerializeLeg
    ) -> tuple[dict[str, Any], dict[str, Any], RenderInputs]:
        """The render-target values + the lowered RenderInputs (B1) — the preimage view AND the
        `RenderInputs` object, so `serialize_preimage` and `mint_deliverable` lower ONCE."""
        from pipeline.cascade import CascadeEnv
        from pipeline.dispatch import render_target_from_entry

        env = CascadeEnv(leg.root, workspace=leg.workspace)
        entry = env.resolver.resolve("render-targets", leg.output_type)
        target_values = {**entry.defaults(), **entry.effective, "id": entry.id}
        target = render_target_from_entry(target_values)
        render_inputs = _lower_for_leg(env, leg, target)
        render_inputs_view = presentation.render_inputs_to_mapping(render_inputs)
        return target_values, render_inputs_view, render_inputs


class _EngineError(RuntimeError):
    """A default-engine mint could not proceed (a config/stage defect) — loud, never a fake fit."""


# ---------------------------------------------------------------------------
# Handler factory + the wiring point (§21.1). EXPLICIT — never at import.
# ---------------------------------------------------------------------------


def render_handler(*, engine: RenderEngine | None = None) -> invoke_mod.Handler:
    """The `render` verb handler. `engine` is the reconcile/serialize seam (default:
    `DefaultRenderEngine`; injected in tests so no live subscription call runs)."""
    e = engine if engine is not None else DefaultRenderEngine()

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _render(ctx, engine=e)

    return handler


def register_render_handler(*, engine: RenderEngine | None = None) -> None:
    """Wire `render` into the invoke dispatch registry (§21.1). EXPLICIT — never at import."""
    invoke_mod.register_handler("render", render_handler(engine=engine))
