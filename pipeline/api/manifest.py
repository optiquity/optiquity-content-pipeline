"""`emit-manifest` — the point-in-time WORK ORDER for a folio (§21.5), NO MINT, SSOT-FREE.

Design authority: `docs/design.md`
  §21.5  — `emit-manifest` is a **point-in-time work order** (F7, closing Q9): a snapshot pinned
           to member `artifact-id`s + commits, handed to the external publisher. The folio stays
           open and mutable; the SSOT is updated from run RESULTS, never from the manifest; the
           manifest is never written into the SSOT and is not a slice of it — it is a generated,
           **deterministically regenerable** derived output (same membership + same targets +
           same store state ⇒ the SAME work order). It is persisted under
           `workspaces/<client>/output/manifests/`, keyed by folio-id + emission timestamp (the
           `<ts>` is a point-in-time marker in the FILENAME only), AND returned in-band.
  §21.5  — **member→deliverable resolution, never from folio state.** Each platform-agnostic
           artifact-member resolves to concrete deliverable-ids via emit-time `member_targets`
           and/or the member record's per-member `pin`. A member with NO emit-time target and NO
           pin is `needs-input: unresolved-member` (`results.CODE_UNRESOLVED_MEMBER`) — never
           guessed (§3.1).
  §21.5  — **resolution semantics, two levels, NO minting at emit** (FR3/FR7.4). Emit-time
           `member_targets` are coordinates and resolve through the SAME resolution rules as
           `render` (§21.8) — but emit-manifest is a snapshot, NEVER a mint verb: at the **fit
           level** a current-matching fit's deliverable resolves if one exists, else the
           latest-minted fit's, with the `render-input-mismatch` warn RIDING that manifest row
           (annotated stale, not re-fitted); at the **serialize level**, when the current-matching
           deliverable is resolvable but not yet materialized, the row surfaces `render-needed`
           (the caller renders — which auto-mints, §17 — and re-emits). The per-member `pin` is
           id-form and FROZEN (§9.2): the row references exactly those bytes verbatim, annotated
           with COMPUTED currency when non-current (§21.3), and is NEVER re-resolved by the system.
  §21.5/§9.2 (A4-4 condition i) — the rows expose the SORTABLE FACTS per member (`added_ts`, the
           resolved id coordinates, lineage `generating_run`/`source_commit`/`created`, the `pin`,
           the `role`) so the consumer computes any ordering CLIENT-SIDE. The manifest carries
           **no folio-level ordering or schedule columns** (a folio holds zero ordering/schedule
           state, §9.1); intra-work part `sequence` rides the layer-3 payload (§17), never a column.
  §21.5/§17 RI14 — for a resolved `side: external` deliverable the row references its **layer-3
           contract payload**; for `side: internal` the row points at the persisted bytes (path)
           + the RI13 pins.
  §13.3  — the manifest is TABULAR: rows over a fixed column set, referencing JSON layer-3
           payloads for external deliverables (a machine record; workspace data, never public).
  §22.7  — **SSOT never gates; the manifest is SSOT-FREE.** Like `discovery`, this module reads
           the content-addressed OUTPUT STORE + the folio membership and persists ONLY the manifest
           artifact; it imports no SSOT module, branches on no tracker read, and touches no
           `ssot.csv`. Currency rides `discovery`'s injectable `CurrencyResolver` seam (the SAME
           no-mint current-digest machinery `list`/`get` use — it computes what a fresh render WOULD
           digest to, WITHOUT minting).

**NO MINT is the load-bearing invariant.** emit-manifest is a READ/PLAN: it resolves what WOULD be
rendered and never mints a fit/serialize/artifact id nor writes any output bytes. Resolution reuses
`discovery.deliverable_detail` (which computes the currency fields via the no-mint resolver) and a
store scan over the ALREADY-materialized fit/deliverable records — never the minting `render`
path. The only bytes this module writes are the manifest artifact under `output/manifests/`.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.api import discovery, results
from pipeline.api import invoke as invoke_mod
from pipeline.api import token as token_mod
from pipeline.api.discovery import CurrencyResolver, DefaultCurrencyResolver
from pipeline.canonical import canonical_json_bytes
from pipeline.folios import FolioError, FolioNotFoundError, MemberFact, list_folio_members
from pipeline.ids import IdError, parse_id
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, is_temp_name, write_new

__all__ = [
    "MANIFEST_COLUMNS",
    "STATE_CURRENT",
    "STATE_FROZEN_PIN",
    "STATE_RENDER_NEEDED",
    "STATE_STALE_FIT",
    "STATE_UNRESOLVED_MEMBER",
    "Clock",
    "emit_manifest_handler",
    "register_emit_manifest_handler",
]

# ---------------------------------------------------------------------------
# The row taxonomy (§21.5) and the fixed column set (§13.3 tabular; A4-4 sortable facts).
# ---------------------------------------------------------------------------

#: A resolved coordinate served by a CURRENT-matching fit's materialized deliverable.
STATE_CURRENT = "current"
#: Resolved, but only the latest-minted (non-current) fit's deliverable is materialized — the
#: `render-input-mismatch` warn rides this row (annotated stale, NOT re-fitted).
STATE_STALE_FIT = "stale-fit"
#: The coordinate is resolvable but its deliverable is not yet materialized — the work order says
#: "render this" (the caller renders, which auto-mints §17, and re-emits). Nothing rendered here.
STATE_RENDER_NEEDED = "render-needed"
#: A FROZEN id-form pin — referenced verbatim, annotated with computed currency, never re-resolved.
STATE_FROZEN_PIN = "frozen-pin"
#: A member with no emit-time target and no pin — `needs-input: unresolved-member`, never guessed.
STATE_UNRESOLVED_MEMBER = "unresolved-member"

#: The fixed manifest column set (§13.3 tabular; §21.5/§9.2 A4-4 condition i). Exposes the
#: per-member SORTABLE FACTS (`added_ts`, resolved id coordinates, lineage, `pin`, `role`) and the
#: resolution outcome. There is DELIBERATELY no folio-level ordering/schedule/sequence column — a
#: folio holds zero ordering state (§9.1); intra-work `sequence` rides the layer-3 payload (§17).
MANIFEST_COLUMNS = (
    "member_artifact_id",  # sortable fact: the member's bare artifact-id (its coordinates parse)
    "added_ts",  # sortable fact: insertion-order source (§9.2)
    "role",  # sortable fact: structural-order source in a typed folio (§9.6)
    "pin",  # the member's frozen deliverable pin (or null)
    "platform",  # resolved id coordinate (sortable)
    "language",  # resolved id coordinate (sortable)
    "output_type",  # resolved id coordinate (sortable)
    "presentation",  # resolved id coordinate (sortable)
    "fitted_id",  # the resolved/referenced fit (or null)
    "deliverable_id",  # the resolved/referenced deliverable (or null — render-needed/unresolved)
    "state",  # one of the five row states above
    "warn",  # `render-input-mismatch` on a stale-fit row (§21.8), else null
    "side",  # external | internal — drives the payload shape (or null when unresolved)
    "fit_current",  # computed currency annotation (§21.3), or null
    "serialize_current",  # computed currency annotation (§21.3), or null
    "generating_run",  # lineage (sortable, §9.2)
    "source_commit",  # lineage (sortable, §9.2)
    "created",  # lineage (sortable, §9.2)
    "payload",  # external → layer-3 reference; internal → {path, pins}; else null
)


class Clock:  # noqa: D401 — a typing alias placeholder is clearer than a bare Callable in __all__
    """Type marker for the injectable emission clock — see `_DefaultNow`. Not instantiated."""


#: The emission clock: returns the wall-clock instant that stamps the manifest FILENAME only
#: (never the tabular body — that keeps the work-order content byte-identical, §21.5). Injected in
#: tests so the filename is deterministic and no ambient clock touches the CONTENT.
NowFn = Callable[[], datetime.datetime]


def _default_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _timestamp(now: NowFn) -> str:
    """The FILENAME point-in-time marker — colon-free so it is a safe store filename (§7.4)."""
    return now().strftime("%Y%m%dT%H%M%S%fZ")


# ---------------------------------------------------------------------------
# Store reads (no mint): the already-materialized fit/deliverable records.
# ---------------------------------------------------------------------------


def _root_of(store: WorkspaceStore) -> Path:
    """The framework root for a workspace store — the store's RECORDED identity (§23), never
    depth-fragile positional path math (`.at()` set it at the door)."""
    return store.framework_root


def _iter_deliverable_ids(store: WorkspaceStore) -> list[str]:
    """Every materialized deliverable RECORD id in this workspace (a store scan — never a mint)."""
    out: list[str] = []
    directory = store.deliverables_dir
    if not directory.is_dir():
        return out
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or is_temp_name(entry.name):
            continue
        try:
            parsed = parse_id(entry.name)
        except IdError:
            continue  # a layer-2 bytes sibling `<id>.<ext>` fails parse — skipped (§7.4)
        if parsed.family == "artifact" and parsed.level == "deliverable" and parsed.part is None:
            out.append(entry.name)
    return out


def _fit_minted_ts(store: WorkspaceStore, fitted_id: str | None) -> str | None:
    """The FIT-binding `minted_ts` for a fitted-id (§21.8 rule 2 keys the stale-fit choice on
    the latest-minted FIT, NOT the deliverable's minted_ts). A record read; mints nothing."""
    if not isinstance(fitted_id, str):
        return None
    record = discovery._read_json(store.output_path(fitted_id))
    binding = record.get("binding") if isinstance(record, Mapping) else None
    minted = binding.get("minted_ts") if isinstance(binding, Mapping) else None
    return minted if isinstance(minted, str) else None


def _resolvable_fit(
    store: WorkspaceStore,
    *,
    root: Path,
    user: str,
    workspace: str,
    resolver: CurrencyResolver,
    artifact_id: str,
    platform: str,
    language: str,
) -> str | None:
    """The fitted-id to NAME on a render-needed row when NO deliverable is materialized (§21.8 fit
    rule 1): the CURRENT-matching fit if one exists, else the LATEST-MINTED fit (fit-binding
    minted_ts; deterministic lexicographic-id tiebreak). An unqualified render binds the
    current-matching fit when one exists, so the work order names it — latest-minted is only the
    fallback when no fit matches. A store scan + the no-mint currency seam; mints nothing."""
    try:
        root_hex = parse_id(artifact_id).root_hex
    except IdError:
        return None
    directory = store.artifacts_dir
    latest: tuple[str, str] | None = None  # (minted_ts, fitted_id) — the fallback
    current_match: str | None = None  # the current-matching fit (preferred), lexicographic-min id
    for entry in sorted(directory.iterdir()) if directory.is_dir() else []:
        if not entry.is_file() or is_temp_name(entry.name):
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
        record = discovery._read_json(store.output_path(entry.name))
        binding = record.get("binding") if isinstance(record, Mapping) else None
        if not isinstance(binding, Mapping):
            continue
        key = (str(binding.get("minted_ts") or ""), entry.name)
        if latest is None or key > latest:
            latest = key
        recorded = binding.get("digest")
        preimage = binding.get("preimage")
        if isinstance(recorded, str):
            current_d = resolver.current_fit_digest(
                root=root,
                user=user,
                workspace=workspace,
                fitted_id=entry.name,
                stored_preimage=preimage if isinstance(preimage, Mapping) else {},
            )
            if recorded == current_d and (current_match is None or entry.name < current_match):
                current_match = entry.name
    if current_match is not None:
        return current_match
    return latest[1] if latest is not None else None


def _candidate_deliverables(
    store: WorkspaceStore,
    *,
    root: Path,
    user: str,
    workspace: str,
    resolver: CurrencyResolver,
    artifact_id: str,
    platform: str,
    language: str,
    output_type: str,
    presentation: str,
) -> list[dict[str, Any]]:
    """The materialized deliverable DETAILS matching a coordinate across all fits (baseline +
    revisions). Each detail is `discovery.deliverable_detail` — currency computed via the no-mint
    resolver; the scan reads records only (§22.7). Never mints."""
    try:
        root_hex = parse_id(artifact_id).root_hex
    except IdError:
        return []
    out: list[dict[str, Any]] = []
    for did in _iter_deliverable_ids(store):
        parsed = parse_id(did)
        if (
            parsed.root_hex != root_hex
            or parsed.platform != platform
            or parsed.language != language
            or parsed.output_type != output_type
            or parsed.presentation != presentation
        ):
            continue
        detail = discovery.deliverable_detail(
            store, did, root=root, user=user, workspace=workspace, resolver=resolver
        )
        if detail is not None:
            out.append(detail)
    return out


def _fitted_of(store: WorkspaceStore, deliverable_id: str) -> str | None:
    """The fitted-id a deliverable record cites (`binding.fit_binding_ref.fitted_id`) — a read."""
    record = discovery._read_json(store.output_path(deliverable_id))
    if not isinstance(record, Mapping):
        return None
    binding = record.get("binding")
    ref = binding.get("fit_binding_ref") if isinstance(binding, Mapping) else None
    fitted = ref.get("fitted_id") if isinstance(ref, Mapping) else None
    return fitted if isinstance(fitted, str) else None


def _did(detail: Mapping[str, Any]) -> str:
    """A candidate detail's deliverable-id as a string sort/lookup key (total; never raises)."""
    return str(detail.get("deliverable_id") or "")


# ---------------------------------------------------------------------------
# Row assembly (§21.5): the payload-by-side + the frozen-pin / resolved / render-needed shapes.
# ---------------------------------------------------------------------------


def _blank_row() -> dict[str, Any]:
    return {col: None for col in MANIFEST_COLUMNS}


def _payload_for(detail: Mapping[str, Any]) -> dict[str, Any]:
    """The payload shape by SIDE (§21.5/§17 RI14): `side: external` → a layer-3 payload REFERENCE
    (the external actor fetches the RI14 contract by these ids); internal → the persisted bytes
    path + the RI13 pins. A reference only — emit-manifest never materializes the layer-3."""
    deliverable_id = detail.get("deliverable_id")
    if detail.get("side") == "external":
        return {
            "kind": "layer-3",
            "deliverable_id": deliverable_id,
            "artifact_id": detail.get("artifact_id"),
        }
    return {
        "kind": "path",
        "path": detail.get("path"),
        "pins": detail.get("pin_bundle"),
    }


def _row_from_detail(
    base: Mapping[str, Any],
    coord: Mapping[str, Any],
    detail: Mapping[str, Any],
    *,
    state: str,
    warn: str | None,
    fitted_id: str | None,
) -> dict[str, Any]:
    row = _blank_row()
    row.update(base)
    row.update(coord)
    row["fitted_id"] = fitted_id
    row["deliverable_id"] = detail.get("deliverable_id")
    row["state"] = state
    row["warn"] = warn
    row["side"] = detail.get("side")
    row["fit_current"] = detail.get("fit_current")
    row["serialize_current"] = detail.get("serialize_current")
    row["payload"] = _payload_for(detail)
    return row


def _frozen_pin_row(
    store: WorkspaceStore,
    *,
    root: Path,
    user: str,
    workspace: str,
    resolver: CurrencyResolver,
    base: Mapping[str, Any],
    pin: str,
) -> dict[str, Any]:
    """A FROZEN pin row (§9.2/§21.5): the pinned id-form deliverable, referenced VERBATIM and
    annotated with computed currency when non-current — the system NEVER re-resolves the pin."""
    detail: dict[str, Any] | None = None
    try:
        detail = discovery.deliverable_detail(
            store, pin, root=root, user=user, workspace=workspace, resolver=resolver
        )
    except IdError:
        detail = None  # a malformed pin (add-time shape-validated) — still referenced verbatim
    row = _blank_row()
    row.update(base)
    row["state"] = STATE_FROZEN_PIN
    row["deliverable_id"] = pin  # EXACTLY the pinned id-form — never re-resolved (the freeze)
    if detail is not None:
        row["platform"] = detail.get("platform")
        row["language"] = detail.get("language")
        row["output_type"] = detail.get("output_type")
        row["presentation"] = detail.get("presentation")
        row["fitted_id"] = _fitted_of(store, pin)
        row["side"] = detail.get("side")
        row["fit_current"] = detail.get("fit_current")  # annotation only (§21.3)
        row["serialize_current"] = detail.get("serialize_current")  # annotation only
        row["payload"] = _payload_for(detail)
    return row


def _resolved_row(
    store: WorkspaceStore,
    *,
    root: Path,
    user: str,
    workspace: str,
    resolver: CurrencyResolver,
    base: Mapping[str, Any],
    artifact_id: str,
    coord: tuple[str, str, str, str],
) -> dict[str, Any]:
    """Resolve ONE emit-time coordinate through the render resolution rules WITHOUT minting
    (§21.5/FR7.4) — TWO levels in sequence. FIT level (§21.8 fit rule): use the current-matching
    fit if any candidate is fit-current, else the LATEST-MINTED fit (fit-binding minted_ts) with
    the `render-input-mismatch` warn. SERIALIZE level (§21.8 serialize rule) WITHIN that fit's
    candidates: reference the `serialize_current` materialized deliverable (→ `current`/`stale`);
    if none is materialized the serialize-current deliverable-id is resolvable but NOT yet
    materialized → `render-needed` (FR7.3: never present serialize-stale bytes as current). No
    candidate at all → `render-needed`, naming the resolvable fit. Mints nothing."""
    platform, language, output_type, presentation = coord
    coord_cols = {
        "platform": platform,
        "language": language,
        "output_type": output_type,
        "presentation": presentation,
    }
    candidates = _candidate_deliverables(
        store,
        root=root,
        user=user,
        workspace=workspace,
        resolver=resolver,
        artifact_id=artifact_id,
        platform=platform,
        language=language,
        output_type=output_type,
        presentation=presentation,
    )
    if candidates:
        # -- FIT level (§21.8 fit rule): pick the fit, then apply the serialize level within it.
        fit_of: dict[str, str | None] = {_did(c): _fitted_of(store, _did(c)) for c in candidates}
        fit_current_cands = [c for c in candidates if c.get("fit_current") is True]
        if fit_current_cands:  # rule 1: the current-matching fit — its deliverables resolve
            chosen_fit = fit_of[_did(fit_current_cands[0])]
            fit_cands = fit_current_cands
            state, warn = STATE_CURRENT, None
        else:  # rule 2: no current fit → the LATEST-MINTED FIT + `render-input-mismatch`
            fit_ids = {f for f in fit_of.values() if f}
            chosen_fit = (
                max(fit_ids, key=lambda f: (str(_fit_minted_ts(store, f) or ""), f))
                if fit_ids
                else None
            )
            fit_cands = [c for c in candidates if fit_of[_did(c)] == chosen_fit]
            state, warn = STATE_STALE_FIT, results.CODE_RENDER_INPUT_MISMATCH
        # -- SERIALIZE level (§21.8 serialize rule) within the chosen fit's candidates: reference
        # the serialize-current materialized deliverable; if none, the current-matching serialize
        # id is resolvable but unmaterialized → render-needed (FR7.3, never serialize-stale-as-cur).
        serialize_current_cands = [c for c in fit_cands if c.get("serialize_current") is True]
        if serialize_current_cands:
            chosen = min(serialize_current_cands, key=_did)
            return _row_from_detail(
                base,
                coord_cols,
                chosen,
                state=state,
                warn=warn,
                fitted_id=fit_of[_did(chosen)],
            )
        row = _blank_row()
        row.update(base)
        row.update(coord_cols)
        row["state"] = STATE_RENDER_NEEDED
        row["fitted_id"] = chosen_fit  # the chosen fit (current-matching, or latest-minted stale)
        # §21.8 rule 2: the `render-input-mismatch` warn RIDES the latest-minted (stale) fit's row
        # regardless of the serialize level, so carry it onto this render-needed-from-stale-fit
        # branch too (else a stale fit with no materialized serialize-current under-reports its
        # fit-staleness for one cycle). `warn` is None on a fit-current fit → byte-identical there.
        row["warn"] = warn
        return row
    # No materialized deliverable for the coordinate → render-needed (resolvable from a fit if one
    # exists; the work order says "render this"). Nothing is rendered here (§21.5).
    row = _blank_row()
    row.update(base)
    row.update(coord_cols)
    row["state"] = STATE_RENDER_NEEDED
    row["fitted_id"] = _resolvable_fit(
        store,
        root=root,
        user=user,
        workspace=workspace,
        resolver=resolver,
        artifact_id=artifact_id,
        platform=platform,
        language=language,
    )
    return row


def _coords(targets: Any) -> list[tuple[str, str, str, str]]:
    """The emit-time coordinates for a member (§21.5): a list of `{platform, language,
    output-type, presentation}` maps, deduped and sorted for a deterministic work order."""
    if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)):
        return []
    seen: set[tuple[str, str, str, str]] = set()
    for target in targets:
        if not isinstance(target, Mapping):
            continue
        platform = target.get("platform")
        language = target.get("language")
        output_type = target.get("output_type", target.get("output-type"))
        presentation = target.get("presentation")
        if all(isinstance(v, str) and v for v in (platform, language, output_type, presentation)):
            seen.add((platform, language, output_type, presentation))  # type: ignore[arg-type]
    return sorted(seen)


def _member_base(member: MemberFact, artifact_detail: Mapping[str, Any] | None) -> dict[str, Any]:
    """The per-member sortable facts common to every row for the member (A4-4 condition i)."""
    return {
        "member_artifact_id": member.artifact_id,
        "added_ts": member.added_ts,
        "role": member.role,
        "pin": member.pin,
        "generating_run": artifact_detail.get("generating_run") if artifact_detail else None,
        "source_commit": artifact_detail.get("source_commit") if artifact_detail else None,
        "created": artifact_detail.get("created") if artifact_detail else None,
    }


def _member_rows(
    store: WorkspaceStore,
    *,
    root: Path,
    user: str,
    workspace: str,
    resolver: CurrencyResolver,
    member: MemberFact,
    targets: Any,
) -> tuple[list[dict[str, Any]], list[results.ResultItem]]:
    """Every manifest row for one folio member + any per-member ResultItem (§21.5). A frozen pin
    yields a frozen-pin row; each emit-time coordinate a resolved/render-needed row; a member with
    NEITHER a pin NOR a target yields an `unresolved-member` row AND a needs-input ResultItem."""
    aid = member.artifact_id
    artifact_detail = discovery.artifact_detail(store, aid)
    base = _member_base(member, artifact_detail)
    rows: list[dict[str, Any]] = []
    items: list[results.ResultItem] = []

    if member.pin is not None:
        rows.append(
            _frozen_pin_row(
                store, root=root, user=user, workspace=workspace, resolver=resolver,
                base=base, pin=member.pin,
            )
        )

    coords = _coords(targets)
    for coord in coords:
        rows.append(
            _resolved_row(
                store,
                root=root,
                user=user,
                workspace=workspace,
                resolver=resolver,
                base=base,
                artifact_id=aid,
                coord=coord,
            )
        )

    if member.pin is None and not coords:
        row = _blank_row()
        row.update(base)
        row["state"] = STATE_UNRESOLVED_MEMBER
        rows.append(row)
        items.append(
            results.make_result(
                results.CODE_UNRESOLVED_MEMBER,
                item=aid,
                ids={"artifact_id": aid},
                hint=(
                    f"member {aid!r} has no emit-time `member_targets` and no pin — supply one; "
                    "the manifest never guesses a deliverable (§21.5/§3.1)"
                ),
            )
        )
    return rows, items


def _row_sort_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(row.get(col) if row.get(col) is not None else "")
        for col in (
            "member_artifact_id",
            "platform",
            "language",
            "output_type",
            "presentation",
            "deliverable_id",
            "state",
        )
    )


# ---------------------------------------------------------------------------
# Persistence (the manifest artifact ONLY — never the SSOT) + the handler.
# ---------------------------------------------------------------------------


def _persist_manifest(
    store: WorkspaceStore, folio_id: str, ts: str, manifest: Mapping[str, Any]
) -> Path:
    """Persist the work order under `output/manifests/<folio-id>-<ts>` (§21.5, §13.3). The `<ts>`
    is a point-in-time marker in the FILENAME only — the tabular CONTENT is byte-identical for a
    fixed store state. Atomic no-replace; a same-name re-emit is byte-identical, so an
    already-materialized collision is a benign no-op (deterministic regenerability, §21.5)."""
    path = store.manifests_dir / f"{folio_id}-{ts}"
    try:
        write_new(path, canonical_json_bytes(manifest))
    except AlreadyMaterializedError:
        pass  # identical content already emitted at this ts — the work order is regenerable
    return path


def _emit_manifest(
    ctx: invoke_mod.HandlerContext, *, resolver: CurrencyResolver, now: NowFn
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """One `emit-manifest` call (§21.5): a point-in-time work order over a folio's members —
    resolved through the render rules with MINTING DISABLED, persisted under `output/manifests/`
    AND returned in-band. Mints nothing; touches no SSOT."""
    store = ctx.store
    root = _root_of(store)
    folio_id = ctx.params.get("folio_id")
    if not isinstance(folio_id, str) or not folio_id:
        return ([_block("emit-manifest needs a `folio_id` (§21.5)")], None)

    try:
        members = list_folio_members(store, folio_id)
    except FolioNotFoundError:
        return (
            [results.make_result(
                results.CODE_NOT_FOUND,
                item=folio_id,
                ids={"folio_id": folio_id},
                hint=f"no folio {folio_id!r} in this workspace — create-folio first (§9.3/§21.5)",
            )],
            None,
        )
    except FolioError as exc:
        return ([_block(f"emit-manifest: {exc}")], None)

    member_targets = ctx.params.get("member_targets")
    targets_map = member_targets if isinstance(member_targets, Mapping) else {}

    rows: list[dict[str, Any]] = []
    member_items: list[results.ResultItem] = []
    for member in members:  # list_folio_members is deterministically artifact-id ordered
        member_rows, items = _member_rows(
            store,
            root=root,
            user=ctx.user,
            workspace=ctx.workspace,
            resolver=resolver,
            member=member,
            targets=targets_map.get(member.artifact_id),
        )
        rows.extend(member_rows)
        member_items.extend(items)

    rows.sort(key=_row_sort_key)
    manifest = {"folio_id": folio_id, "columns": list(MANIFEST_COLUMNS), "rows": rows}

    path = _persist_manifest(store, folio_id, _timestamp(now), manifest)
    summary = results.ResultItem(
        item=folio_id,
        status="ok",
        ids={"folio_id": folio_id},
        output={"path": str(path.relative_to(store.root))},
        context={"manifest": manifest},
    )
    return ([summary, *member_items], None)


def _block(hint: str) -> results.ResultItem:
    """A code-less block (§21.7 closed) — a malformed emit-manifest call the taxonomy does not
    name (a bad `folio_id`; a corrupt folio). The detail rides `remediation.hint`."""
    return results.ResultItem(item="emit-manifest", status="block", remediation={"hint": hint})


# ---------------------------------------------------------------------------
# Handler factory + the wiring point (§21.1). EXPLICIT — never at import.
# ---------------------------------------------------------------------------


def emit_manifest_handler(
    *, resolver: CurrencyResolver | None = None, now: NowFn | None = None
) -> invoke_mod.Handler:
    """The `emit-manifest` verb handler. `resolver` is the SAME no-mint currency seam `list`/`get`
    use (default: `DefaultCurrencyResolver`; injected in tests so no live config read runs); `now`
    stamps the manifest FILENAME only (default: UTC wall clock)."""
    r = resolver if resolver is not None else DefaultCurrencyResolver()
    clock = now if now is not None else _default_now

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _emit_manifest(ctx, resolver=r, now=clock)

    return handler


def register_emit_manifest_handler(
    *, resolver: CurrencyResolver | None = None, now: NowFn | None = None
) -> None:
    """Wire `emit-manifest` into the invoke dispatch registry (§21.1). EXPLICIT — never at import.
    """
    invoke_mod.register_handler(
        "emit-manifest", emit_manifest_handler(resolver=resolver, now=now)
    )
