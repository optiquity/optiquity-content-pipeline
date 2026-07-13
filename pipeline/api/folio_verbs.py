"""The standalone folio write verbs — `create-folio` + `add-to-folio` (§21.2, §9).

Design authority: `docs/design.md`
  §21.1  — both `create-folio` and `begin-session(target_folio=…)` exist (A1a): `create-folio`
           serves the disconnected create-empty-first pattern; it is token-OPTIONAL and writes
           an empty folio, returning its id.
  §21.2  — the `add-to-folio` member parameter contract (the member-record write path): the
           verb takes `members: [{artifact_id, pin?, role?}]`; `artifact_ids: […]` is the sugar
           for pin-less, role-less records; default = the produced ids. Re-append is EXPLICIT:
           an identical record → the idempotent dedupe no-op (`ok`); a differing `pin`/`role` →
           an atomic in-place update preserving `added_ts`, surfaced `member-updated` (warn).
  §21.8  — `create-folio` is a MINT verb — the optional `idempotency_key` makes a retried call
           return the SAME folio instead of duplicating (n8n retry safety).
  §9     — folios are pure purposeful sets; membership is intra-workspace (§9.2/§10) and
           append-only in v1; a member `pin` is a FROZEN deliverable-id (B4-2/FR3).

**Reuse, never reimplement (step 31).** Both verbs are thin API adapters over
`pipeline.folios` — `create_folio` and `add_to_folio` (which itself rides the proven §21.2 S4
`pipeline.spine.append_folio_member` atomic marker write). This module adds ONLY the API-shape
mapping: params → the folios call, and its typed folios outcome/error → the §21.7 `ResultItem`
taxonomy. It reimplements no folio policy (folio-must-exist, isolation, pin/role validation,
atomic member write all live in `pipeline.folios`).

**Isolation is the invoke gate's (ONE path).** `create-folio` references no incoming id;
`add-to-folio`'s `folio_id` + member ids are Gate-3-isolated (§21.1,
`invoke._extract_add_to_folio`), so a cross-workspace id is refused envelope-fatally BEFORE
dispatch — this handler holds no
isolation branch of its own (folios' intra-workspace re-check is defense-in-depth, mapped honestly
if it ever fires).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pipeline.api import invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.folios import (
    CreateFolioOutcome,
    CrossWorkspaceMemberError,
    FolioError,
    FolioNotFoundError,
    add_to_folio,
    create_folio,
)
from pipeline.spine import FolioAppendOutcome

__all__ = [
    "add_to_folio_handler",
    "create_folio_handler",
    "member_params",
    "register_folio_handlers",
]


# ---------------------------------------------------------------------------
# create-folio (§21.1/§9.3): mint an empty folio; idempotency_key = n8n retry safety.
# ---------------------------------------------------------------------------


def _create_folio(
    ctx: invoke_mod.HandlerContext,
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """`create-folio` (§21.1): mint an EMPTY folio, return its id. `idempotency_key` (§21.8)
    reproduces the same folio on a retry. A bad purpose / mint collision is a code-less block
    (the closed §21.7 vocabulary names no code for it — never a fabricated code)."""
    params: Mapping[str, Any] = ctx.params
    purpose = params.get("purpose")
    if not isinstance(purpose, str) or not purpose:
        return ([_block(
            "create-folio needs a non-empty `purpose` (§9.1)", item="create-folio"
        )], None)
    try:
        outcome: CreateFolioOutcome = create_folio(
            ctx.store,
            purpose=purpose,
            folio_type=params.get("folio_type"),
            nonce=params.get("idempotency_key"),
        )
    except FolioError as exc:
        # FolioExistsError (mint collision) / a malformed folio_type slug — no §21.7 code, so a
        # typed code-less block carrying the detail (never a fabricated taxonomy code, §21.7).
        return ([_block(
            f"create-folio could not mint the folio (§9.3): {exc}", item="create-folio"
        )], None)
    if outcome.created:
        item = results.ResultItem(
            item=outcome.folio_id,
            status="ok",
            ids={"folio_id": outcome.folio_id},
            context={"created": True, "purpose": purpose},
        )
    else:
        # §21.8: the idempotency_key re-create hit the SAME folio — an idempotent no-op.
        item = results.make_result(
            results.CODE_ALREADY_MATERIALIZED,
            item=outcome.folio_id,
            ids={"folio_id": outcome.folio_id},
            context={"created": False, "purpose": purpose},
            hint="an idempotency_key re-create returned the existing folio (§21.8), not a dup",
        )
    return ([item], None)


# ---------------------------------------------------------------------------
# add-to-folio (§21.2): the member-record write path over pipeline.folios.add_to_folio.
# ---------------------------------------------------------------------------


def member_params(
    params: Mapping[str, Any], token: token_mod.Token | None
) -> list[Any]:
    """The §21.2 member list: `members[{artifact_id,pin?,role?}]` + the `artifact_ids` sugar,
    defaulting to the session's produced ids (a token's `produced_ids`) when neither is given.

    Returns the raw member items (mappings + bare-id strings) — `pipeline.folios.add_to_folio`
    coerces + validates each (shape, isolation, pin/role forms), never this module."""
    members: list[Any] = []
    raw_members = params.get("members")
    if isinstance(raw_members, Sequence) and not isinstance(raw_members, (str, bytes)):
        members.extend(raw_members)
    for aid in _iter_str(params.get("artifact_ids")):
        members.append(aid)
    if not members and token is not None:
        # §21.2 default = the produced ids (the in-session convenience). Bare artifact-ids only;
        # a deliverable-id in produced_ids is not a member (membership is artifact-level, §9.2) —
        # folios.add_to_folio refuses a non-bare id, so filter to bare artifact-ids here is not
        # needed: pass the artifact-level produced ids through and let folios validate.
        members.extend(
            aid for aid in token.produced_ids if isinstance(aid, str) and _is_bare_artifact(aid)
        )
    return members


def _is_bare_artifact(id_str: str) -> bool:
    """A bare `a-<hex16>` artifact id (no fitted/deliverable coords) — the only membership level."""
    from pipeline.ids import IdError, parse_id

    try:
        parsed = parse_id(id_str)
    except IdError:
        return False
    return parsed.family == "artifact" and parsed.level == "artifact" and parsed.part is None


def _iter_str(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [v for v in value if isinstance(v, str)]
    return []


def _add_to_folio(
    ctx: invoke_mod.HandlerContext,
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """`add-to-folio` (§21.2): append members to an EXISTING folio; explicit re-append semantics.

    `folio_id` + member ids are Gate-3-isolated (§21.1). Delegates the whole write to
    `pipeline.folios.add_to_folio` (folio-must-exist, isolation re-check, pin/role validation,
    atomic S4 marker write). Each outcome maps to the taxonomy: `ok` → ok, `member-updated` →
    the §21.2 warn. A folio-not-found is `not-found`; a member-shape / lingering isolation defect
    is surfaced honestly (isolation as the envelope code, a shape defect as a code-less block)."""
    params: Mapping[str, Any] = ctx.params
    folio_id = params.get("folio_id")
    if not isinstance(folio_id, str) or not folio_id:
        return ([_block("add-to-folio needs a `folio_id` (§21.2)", item="add-to-folio")], None)

    members = member_params(params, ctx.token)
    if not members:
        return (
            [results.make_result(
                results.CODE_UNRESOLVED_MEMBER,
                item=folio_id,
                ids={"folio_id": folio_id},
                hint="add-to-folio has no members and no produced ids to default to (§21.2) — "
                "supply `members` or `artifact_ids`; never guessed",
            )],
            ctx.token,
        )

    try:
        outcomes: tuple[FolioAppendOutcome, ...] = add_to_folio(ctx.store, folio_id, members)
    except FolioNotFoundError as exc:
        return (
            [results.make_result(
                results.CODE_NOT_FOUND, item=folio_id, ids={"folio_id": folio_id}, hint=str(exc)
            )],
            ctx.token,
        )
    except CrossWorkspaceMemberError as exc:
        # Defense-in-depth: the invoke gate already refuses cross-workspace member ids
        # envelope-fatally, so this fires only if an id resolved at the gate but not as a
        # materialized artifact — surfaced as the honest isolation code (§9.2/§10).
        return (
            [results.make_result(
                results.CODE_ISOLATION_VIOLATION, item=folio_id, ids={"folio_id": folio_id},
                hint=str(exc),
            )],
            ctx.token,
        )
    except FolioError as exc:
        # MemberShapeError / other typed folio refusals: no §21.7 code names them → code-less block.
        return ([_block(f"add-to-folio refused a member (§21.2): {exc}", item=folio_id)], ctx.token)

    items = [
        _outcome_result(folio_id, member, outcome)
        for member, outcome in zip(members, outcomes, strict=True)
    ]
    return (items, ctx.token)


def _outcome_result(folio_id: str, member: Any, outcome: FolioAppendOutcome) -> results.ResultItem:
    """Map one §21.2 folios append outcome to the §21.7 taxonomy (`ok` / `member-updated`)."""
    artifact_id = member.get("artifact_id") if isinstance(member, Mapping) else member
    aid = artifact_id if isinstance(artifact_id, str) else str(artifact_id)
    ids = {"folio_id": folio_id, "artifact_id": aid}
    if outcome.code == "member-updated":
        return results.make_result(
            results.CODE_MEMBER_UPDATED,
            item=aid,
            ids=ids,
            context={"created": outcome.created},
            hint="the member's pin/role was atomically updated; added_ts preserved (§21.2)",
        )
    return results.ResultItem(
        item=aid, status="ok", ids=ids, context={"created": outcome.created}
    )


# ---------------------------------------------------------------------------
# Shared: a code-less block (the honest sibling of session._block, §21.7 closed).
# ---------------------------------------------------------------------------


def _block(hint: str, *, item: str) -> results.ResultItem:
    """A per-item block with NO taxonomy code — for a condition the closed §21.7 vocabulary does
    not name (a malformed call / a mint collision). Honest: no code is fabricated (§21.7)."""
    return results.ResultItem(item=item, status="block", remediation={"hint": hint})


# ---------------------------------------------------------------------------
# Handler factories + the wiring point (§21.1). EXPLICIT — never at import.
# ---------------------------------------------------------------------------


def create_folio_handler() -> invoke_mod.Handler:
    """The `create-folio` handler (no seams — a pure folios mint over the store, §9.3)."""

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _create_folio(ctx)

    return handler


def add_to_folio_handler() -> invoke_mod.Handler:
    """The `add-to-folio` handler (no seams — a pure folios member write over the store, §21.2)."""

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _add_to_folio(ctx)

    return handler


def register_folio_handlers() -> None:
    """Wire `create-folio` + `add-to-folio` into the invoke dispatch registry (§21.1). EXPLICIT
    — never at import (keeps the step-32 unwired-registry tests valid)."""
    invoke_mod.register_handler("create-folio", create_folio_handler())
    invoke_mod.register_handler("add-to-folio", add_to_folio_handler())
