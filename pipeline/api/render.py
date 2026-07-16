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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pipeline import fit_resolution, ir, presentation, reconcile, serialize
from pipeline.api import invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
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
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, is_done, write_new

__all__ = [
    "FitLeg",
    "RenderEngine",
    "SerializeLeg",
    "DefaultRenderEngine",
    "render_handler",
    "register_render_handler",
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


class RenderEngine(Protocol):
    """The reconcile/serialize seam (§16/§17). `reconcile_preimage`/`serialize_preimage` compute
    the CURRENT effective inputs preimages the resolution rules compare against;
    `mint_fit`/`mint_deliverable` perform the actual (expensive) mints, returning the reshaped IR
    + the fit-binding, and the bytes + the render-binding + the layer-2 extension. Injected in
    tests so no live subscription call ever runs (the same seam the reconcile/serialize/compose
    tests use)."""

    def reconcile_preimage(self, leg: FitLeg) -> Mapping[str, Any]: ...

    def mint_fit(
        self, leg: FitLeg, *, preimage: Mapping[str, Any], revision: bool
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]: ...

    def serialize_preimage(self, leg: SerializeLeg) -> Mapping[str, Any]: ...

    def mint_deliverable(
        self, leg: SerializeLeg, *, preimage: Mapping[str, Any], serialize_revision: bool
    ) -> tuple[bytes, Mapping[str, Any], str]: ...


# ---------------------------------------------------------------------------
# The render handler (§21.8): resolve fit → (mint|serve) → resolve serialize → (mint|serve).
# ---------------------------------------------------------------------------


def _render(
    ctx: invoke_mod.HandlerContext, *, engine: RenderEngine
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """One `render` call (§21.8): fit resolution + serialize resolution over the store, minting
    baseline/revision ids via the engine ONLY when the resolution says so; idempotent by id
    existence, and `force_reconcile` mints a NEW revision fit, never mutating the old."""
    params = ctx.params
    item = params.get("item")
    coords = _coordinates(params)
    if not isinstance(item, str) or not item or coords is None:
        return ([_block(
            "render needs `item` + platform/language/output_type/presentation (§21.2)"
        )], None)
    platform, language, output_type, presentation = coords
    force = bool(params.get("force_reconcile", False))

    canonical_record = _read_record(ctx.store, item)
    if canonical_record is None:
        return ([results.make_result(
            results.CODE_NOT_FOUND, item=item, ids={"id": item},
            hint=f"no artifact record for {item!r} in this workspace (§21.8)",
        )], None)
    # GAP-1a: read via `ir.unwrap_ir`, tolerating BOTH persisted shapes — a FITTED/render record
    # wraps the IR under `["ir"]`; a fresh COMPOSE record IS the raw envelope. The old
    # `"ir" not in record` gate 404'd EVERY real composed artifact (compose persists raw); this
    # gates on a REAL absence (`record is None`) and unwraps whichever shape is stored (§15 RI4).
    canonical_ir = ir.unwrap_ir(canonical_record)

    root = ctx.store.root.parent.parent
    fit_leg = FitLeg(
        root=root, workspace=ctx.workspace, store=ctx.store, item=item,
        platform=platform, language=language, canonical_ir=canonical_ir,
    )

    # -- FIT resolution (§16 FR2 / the force matrix) --------------------------------------------
    try:
        coordinate = FitCoordinate(artifact_id=item, platform=platform, language=language)
    except fit_resolution.FitResolutionError as exc:
        return ([_block(f"render: {exc}")], None)
    fit_preimage = engine.reconcile_preimage(fit_leg)
    fit_bindings = _fit_bindings(ctx.store, item, platform, language)
    if force:
        fit_res = fit_resolution.resolve_force_reconcile(coordinate, fit_bindings, fit_preimage)
    else:
        fit_res = fit_resolution.resolve_fit(coordinate, fit_bindings, fit_preimage)
    fitted_id = fit_resolution.resolved_fitted_id(fit_res, coordinate)

    if fit_res.should_mint and not is_done(ctx.store, fitted_id):
        fitted_ir, fit_binding = engine.mint_fit(
            fit_leg, preimage=fit_preimage, revision=fit_res.revision
        )
        if fit_binding.get("fitted_id") != fitted_id:
            return ([_block(
                f"render: engine minted fit {fit_binding.get('fitted_id')!r} but the "
                f"resolution fixed {fitted_id!r} (§7.4)"
            )], None)
        _persist(ctx.store, fitted_id, {"ir": fitted_ir, "binding": fit_binding})
    fitted_ir = _load_ir(ctx.store, fitted_id)
    if fitted_ir is None:
        return ([_block(f"render: resolved fit {fitted_id!r} has no stored IR (§16)")], None)

    # -- SERIALIZE resolution (§17 FR7.3) -------------------------------------------------------
    ser_leg = SerializeLeg(
        root=root, workspace=ctx.workspace, store=ctx.store, fitted_id=fitted_id,
        fitted_ir=fitted_ir, output_type=output_type, presentation=presentation,
    )
    try:
        del_coord = DeliverableCoordinate(
            fitted_id=fitted_id, output_type=output_type, presentation=presentation
        )
    except serialize.SerializeError as exc:
        return ([_block(f"render: {exc}")], None)
    ser_preimage = engine.serialize_preimage(ser_leg)
    render_bindings = _render_bindings(ctx.store, fitted_id, output_type, presentation)
    ser_res = serialize.resolve_deliverable(del_coord, render_bindings, ser_preimage)
    deliverable_id = serialize.resolved_deliverable_id(ser_res, del_coord)

    output_path: str | None = None
    if ser_res.should_mint and not is_done(ctx.store, deliverable_id):
        output_bytes, render_binding, extension = engine.mint_deliverable(
            ser_leg, preimage=ser_preimage, serialize_revision=ser_res.revision
        )
        if render_binding.get("deliverable_id") != deliverable_id:
            return ([_block(
                f"render: engine minted deliverable {render_binding.get('deliverable_id')!r} "
                f"but the resolution fixed {deliverable_id!r} (§7.4)"
            )], None)
        output_path = _persist_deliverable(
            ctx.store, deliverable_id, render_binding, output_bytes, extension
        )
    else:
        output_path = _existing_deliverable_path(ctx.store, deliverable_id)

    return ([_result(item, fitted_id, deliverable_id, fit_res, ser_res, output_path)], None)


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


def _existing_deliverable_path(store: WorkspaceStore, deliverable_id: str) -> str | None:
    record = _read_record(store, deliverable_id)
    if isinstance(record, Mapping) and isinstance(record.get("layer2"), Mapping):
        path = record["layer2"].get("path")
        return path if isinstance(path, str) else None
    return None


def _block(hint: str) -> results.ResultItem:
    """A code-less block (§21.7 closed) — a malformed render call the taxonomy does not name."""
    return results.ResultItem(item="render", status="block", remediation={"hint": hint})


# ---------------------------------------------------------------------------
# B1 (§5.3 PD3/PD5) — presentation lowering on the render-verb minting path.
# ---------------------------------------------------------------------------


def _deferred_asset_loader(path: str) -> bytes:
    """The render-verb Presentation asset loader (B1) — a DEFERRED, loud no-op. Invoked ONLY for
    an entry declaring a `css`/`template`/`reference_doc` lever (no framework entry does — only
    `plain.md` ships — and the MVP styled entry is asset-free), so it never fires on any existing
    or MVP path; raising (vs the old silent lever-drop) is strictly more honest (§3.1). A real
    filesystem asset loader is §17/step-29 scope, not this step."""
    raise presentation.PresentationError(
        "presentation-error: asset levers (css/template/reference_doc) are not yet lowerable on "
        f"the render-verb path — deferred to §17/step-29; an entry references asset {path!r}"
    )


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
        load_asset=_deferred_asset_loader,
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
        target_values, render_inputs_view, _render_inputs = self._serialize_inputs(leg)
        return serialize.serialize_inputs_preimage(
            render_target=target_values, render_inputs=render_inputs_view
        )

    def mint_deliverable(
        self, leg: SerializeLeg, *, preimage: Mapping[str, Any], serialize_revision: bool
    ) -> tuple[bytes, Mapping[str, Any], str]:
        from pipeline.dispatch import dispatch, render_target_from_entry

        # B1: the SAME lowered `render_inputs` the preimage was built from (`_serialize_inputs`)
        # drives the dispatch flags — one lowering, so flags and preimage cannot diverge.
        target_values, _render_inputs_view, render_inputs = self._serialize_inputs(leg)
        units = serialize.serialize_fitted(leg.fitted_ir)
        if len(units) != 1:
            raise _EngineError(
                f"standalone render expects one serialized document, got {len(units)}"
            )
        target = render_target_from_entry(target_values)
        dout = dispatch(target, units[0].ast, render_inputs=render_inputs)
        if dout.output_bytes is None:
            raise _EngineError(f"render target {leg.output_type!r} produced no layer-2 bytes")
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
        return dout.output_bytes, render_binding, serialize.extension_for(leg.output_type)

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
