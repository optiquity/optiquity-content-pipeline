"""The external-actor `invoke` contract (§21.1): one synchronous call, one JSON object out.

Design authority: `docs/design.md` §21.1 (`invoke(verb, workspace, params, [token], [pins])
→ {envelope, results, [token']}`; the closed verb map; every call carries `workspace` and
isolation is enforced by the API, not by trust — every id must resolve inside that workspace
or the item is refused, `isolation-violation`), §21.7 (the envelope's `ok` = whole-invocation
validity only: unknown verb, isolation breach, malformed/invalid token; a per-item `block`
never fails the batch), §20 (the token — decoded/verified against the invoked workspace),
§10 (client isolation is structural — a workspace holds only its own artifacts).

**Step-32 scope (plan step 32).** The contract, the envelope, workspace isolation on every
id, token handling, and the result shape are COMPLETE and real here. The verb DISPATCH is a
thin real seam: `_VERB_HANDLERS` is a registry the real handlers populate at later steps
(generate-next: step 33; render/fetch/emit: steps 34-35). A known verb whose handler is not
yet wired raises the INTERNAL `HandlerNotWired` — never a fabricated success and never a
design result code presented as implemented (the honest sibling of step-33's action-level
`NotYetWired`; the assertion that every verb dispatches to a REAL handler is deferred). The
three whole-invocation GATES (unknown-verb, invalid-token, isolation-violation) run BEFORE
dispatch and are fully real and tested now.

**INV-CORRECTNESS (§22.7).** This module imports no SSOT and reads correctness only from the
content-addressed output store: isolation resolves an id by OUTPUT EXISTENCE (`store` /
`ids`), never via the SSOT and never via the token (the token is a cursor, not a correctness
boundary — §21.1).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.canonical import canonical_json_str
from pipeline.ids import IdError, parse_id
from pipeline.store import WorkspaceStore
from pipeline.workspace_name import DEFAULT_ZONE, WorkspaceNameError, validate_workspace_path

__all__ = [
    "KNOWN_VERBS",
    "HandlerContext",
    "HandlerNotWired",
    "build_invoke_parser",
    "invoke",
    "main_cli",
    "referenced_ids",
    "register_handler",
    "resolve_in_workspace",
]

#: §21.1 verb map — the closed verb set. Read/Discovery: `list`, `get`. Generation/Session:
#: `begin-session`, `continue-session`. Folio: `create-folio`, `add-to-folio`. Output/
#: Emit/Retrieval: `emit-manifest`, `emit-outline` (DR-3 horn (a)/B1 — a hand-authored outline
#: -> a byte-faithful `Format=outline` artifact), `fetch-by-id`, `render`. Anything else →
#: `unknown-verb`.
KNOWN_VERBS = frozenset(
    {
        "list",
        "get",
        "begin-session",
        "continue-session",
        "create-folio",
        "add-to-folio",
        "emit-manifest",
        "emit-outline",
        "fetch-by-id",
        "render",
    }
)


class HandlerNotWired(RuntimeError):
    """Internal (step-32): a KNOWN verb reached dispatch but its handler lands at a later
    step. Never a wire result code, never a fabricated success — surfaced only to the CLI
    and tests (the honest verb-level sibling of step-33's `NotYetWired`)."""

    def __init__(self, verb: str) -> None:
        super().__init__(
            f"handler-not-wired: verb {verb!r} is recognized but its handler is not wired "
            "yet (lands at a later build step)"
        )
        self.verb = verb


@dataclass(frozen=True)
class HandlerContext:
    """The bundle a verb handler consumes (steps 33-35). Everything the gates already vetted:
    the verb, the invoked workspace, the owning user (§23 isolation prefix), the owning zone (§23,
    Z4 — carried EXPLICITLY, not read off `store.zone`, so an INJECTED bare store still yields the
    zone a handler threads into its own path builds), the raw params, the DECODED token (or None),
    the supplied pins (or None), and the resolved workspace store."""

    verb: str
    workspace: str
    user: str
    zone: str
    params: Mapping[str, Any]
    token: token_mod.Token | None
    pins: Any
    store: WorkspaceStore
    #: The per-run transport override (plan G7: `subscription` | `api` | `key:<handle>`), threaded
    #: from both doors so a spend handler passes it to the resolver. `None` = no override (the
    #: cascade decides). It selects a MODE / a handle, NEVER a user (I3, structural).
    transport_override: str | None = None


#: A verb handler: given a vetted context, produce the result items + an optional next token.
Handler = Callable[[HandlerContext], "tuple[Sequence[results.ResultItem], token_mod.Token | None]"]

#: The dispatch registry. EMPTY at step 32 — real handlers register at their owning steps.
_VERB_HANDLERS: dict[str, Handler] = {}


def register_handler(verb: str, handler: Handler) -> None:
    """Register the real handler for a known verb (the later-step wiring point, §21.1)."""
    if verb not in KNOWN_VERBS:
        raise ValueError(f"cannot register a handler for unknown verb {verb!r} (§21.1)")
    _VERB_HANDLERS[verb] = handler


# ---------------------------------------------------------------------------
# Workspace isolation on every id (§21.1/§10): resolution by output existence.
# ---------------------------------------------------------------------------


def resolve_in_workspace(store: WorkspaceStore, id_str: str) -> bool:
    """Does `id_str` resolve INSIDE this workspace's store? (§21.1 "every id must resolve").

    Ids are workspace-agnostic content-addressed strings (§7); an id "belongs to" a
    workspace exactly when it MATERIALIZES there (§10 isolation is structural). Artifact-
    family ids resolve by output existence (`store.output_path(...).exists()`, the §22.7
    existence authority); folio ids by their folio directory. A run id or an unparseable
    string resolves nowhere here → refused by the caller. Reads the output store ONLY — no
    SSOT, no token (INV-CORRECTNESS, §22.7).
    """
    try:
        parsed = parse_id(id_str)
    except IdError:
        return False
    if parsed.family == "artifact":
        return store.output_path(id_str).exists()
    if parsed.family == "folio":
        return (store.folios_dir / id_str).exists()
    return False


def _iter_ids(value: Any) -> list[str]:
    """The id strings inside a param value: a bare string, or the strings in a sequence."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [v for v in value if isinstance(v, str)]
    return []


def _members_ids(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """§21.2 add-to-folio member ids: `artifact_ids` sugar + `members[].artifact_id`/`.pin`."""
    out: list[tuple[str, str]] = []
    for aid in _iter_ids(params.get("artifact_ids")):
        out.append(("artifact_ids", aid))
    members = params.get("members")
    if isinstance(members, Sequence) and not isinstance(members, (str, bytes)):
        for member in members:
            if isinstance(member, Mapping):
                aid = member.get("artifact_id")
                if isinstance(aid, str):
                    out.append(("members.artifact_id", aid))
                pin = member.get("pin")
                if isinstance(pin, str):
                    out.append(("members.pin", pin))
    return out


def _extract_render(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [("item", v) for v in _iter_ids(params.get("item"))]


def _extract_get(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [("id", v) for v in _iter_ids(params.get("id"))]


def _extract_add_to_folio(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = [("folio_id", v) for v in _iter_ids(params.get("folio_id"))]
    out.extend(_members_ids(params))
    return out


def _extract_emit_manifest(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    out = [("folio_id", v) for v in _iter_ids(params.get("folio_id"))]
    targets = params.get("member_targets")
    if isinstance(targets, Mapping):
        out.extend(("member_targets", aid) for aid in targets if isinstance(aid, str))
    return out


def _extract_begin_session(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    target = params.get("target_folio")
    if isinstance(target, str) and target not in ("auto", "none"):
        return [("target_folio", target)]
    return []


#: §21.1/§21.2: continue-session's nested ids MIRROR a standalone verb — each id-bearing
#: action maps to the verb whose extractor already locates its ids, so the whole-invocation
#: isolation gate treats the action path and the verb path identically (they never diverge).
_ACTION_MIRROR_VERB = {
    "render": "render",
    "fetch": "fetch-by-id",
    "get": "get",
    "add-to-folio": "add-to-folio",
    "emit-manifest": "emit-manifest",
}


def _extract_continue_session(params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """continue-session ids are ACTION-nested (§21.2): map `action` to its mirror verb and
    reuse that verb's extractor, so a cross-workspace nested id is refused by Gate 3 exactly
    like the standalone verb path — WHOLE-INVOCATION-fatal (§21.1/§21.7). The location is
    prefixed with the action (`render.item`) so the violation names where the id sat. An
    action with no id-bearing mirror (`status`/`list`/`generate-next`/unknown) references
    nothing here — that shape is the handler's concern (`unknown-action` stays a per-item
    block, never an isolation refusal)."""
    action = params.get("action")
    verb = _ACTION_MIRROR_VERB.get(action) if isinstance(action, str) else None
    if verb is None:
        return []
    extractor = _ID_EXTRACTORS.get(verb)
    if extractor is None:  # pragma: no cover — every mirror verb has an extractor
        return []
    return [(f"{action}.{location}", id_str) for location, id_str in extractor(params)]


#: Per-verb id-bearing param positions (§21.1) — the isolation surface. `list`/`create-folio`
#: reference no incoming id; `continue-session` maps each action to its mirror verb's extractor
#: (`_extract_continue_session`) so its ACTION-nested ids ride the SAME envelope-fatal gate.
_ID_EXTRACTORS: dict[str, Callable[[Mapping[str, Any]], list[tuple[str, str]]]] = {
    "render": _extract_render,
    "fetch-by-id": _extract_get,
    "get": _extract_get,
    "add-to-folio": _extract_add_to_folio,
    "emit-manifest": _extract_emit_manifest,
    "begin-session": _extract_begin_session,
    "continue-session": _extract_continue_session,
}


def referenced_ids(verb: str, params: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The (location, id) pairs a call references in its PARAMS — the isolation surface.

    The token's own ids are not re-checked here: a decoded token is workspace-bound already
    (a wrong-workspace token was refused as `invalid-token`, §20), so its `produced_ids`
    are this-workspace ids by construction. Isolation guards the UNTRUSTED caller input.
    """
    extractor = _ID_EXTRACTORS.get(verb)
    return extractor(params) if extractor is not None else []


def _isolation_violations(
    store: WorkspaceStore, workspace: str, user: str, referenced: list[tuple[str, str]]
) -> list[results.ResultItem]:
    """One `isolation-violation` (§21.1) per referenced id that does not resolve here."""
    violations: list[results.ResultItem] = []
    for location, id_str in referenced:
        if not isinstance(id_str, str) or not id_str:
            continue  # not an id — shape is the handler's concern (step 33)
        if not resolve_in_workspace(store, id_str):
            violations.append(
                results.make_result(
                    results.CODE_ISOLATION_VIOLATION,
                    item=id_str,
                    ids={"id": id_str},
                    context={
                        "id": id_str,
                        "workspace": workspace,
                        "user": user,
                        "at": location,
                    },
                    hint=(
                        f"id {id_str!r} does not resolve inside workspace {workspace!r} "
                        f"(user {user!r}) — workspaces never cross (§10)"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# The invocation (§21.1): gates → dispatch → {envelope, results, [token']}.
# ---------------------------------------------------------------------------


def _fatal(
    verb: str,
    workspace: str,
    user: str,
    items: Sequence[results.ResultItem],
    code: str,
    message: str,
    *,
    zone: str = DEFAULT_ZONE,
) -> dict[str, Any]:
    """A whole-invocation failure (§21.7): ok=False, the fatal items, and NO echoed token. `zone`
    (§23/Z4) is ECHOED on the fatal envelope too, so even a refusal names the zone the caller asked
    for — parallel to the echoed `verb`/`workspace`/`user`."""
    envelope = results.Envelope(
        ok=False, verb=verb, workspace=workspace, user=user, zone=zone, code=code, message=message
    )
    return {"envelope": envelope.as_dict(), "results": [i.as_dict() for i in items]}


#: The whole-invocation code for the uniform-S4 zone-required refusal (plan G7 / B-1). A SPEND verb
#: invoked by a user who owns >1 zone WITHOUT an explicit zone is refused at THIS shared chokepoint
#: (both the CLI and the served `jobrunner→invoke()` re-entry pass through it), never a silent spend
#: in the wrong zone. It reuses the same rule the CLI `_resolve_spend_zone_or_refuse` applies early.
CODE_ZONE_REQUIRED = "zone-required"


def _is_spend_call(verb: str, params: Mapping[str, Any]) -> bool:
    """True iff this invocation is a SPEND door subject to the uniform-S4 zone-required rule (B-1).

    The paid/served surfaces: `continue-session{action: generate-next}` (the generation door) and
    `render` (the reshape/mint door). `begin-session{generate != none}` would be one too, but it is
    still deferred (501), so `begin-session` stays Tier-A here (generate defaults to `none`). Every
    OTHER verb/action — begin-session plan-only, CRUD, list/get, fetch, the cheap continue-session
    actions — is Tier-A and NEVER resolves/refuses (S2: Tier-A never spends)."""
    if verb == "render":
        return True
    if verb == "continue-session" and params.get("action") == "generate-next":
        return True
    if verb == "begin-session":
        generate = params.get("generate")
        return generate is not None and generate != "none"
    return False


def _zone_required_or_none(
    verb: str,
    workspace: str,
    user: str,
    params: Mapping[str, Any],
    *,
    root: str | Path,
    zone: str,
    zone_explicit: bool,
) -> dict[str, Any] | None:
    """The UNIFORM S4 gate (G7, B-1): for a SPEND call with a NON-explicit zone, a user who owns
    MORE THAN ONE zone is REFUSED here — the whole-invocation `zone-required` fatal — rather than
    silently defaulting `zone` and spending in the wrong bucket. Returns the fatal envelope on a
    refusal, else `None` (proceed). Reuses `workspacescaffold.resolve_spend_zone` (the SAME
    `list_zones` scan the CLI early-refusal uses), so the CLI door and the served
    `generate-next`/`render` re-entry enforce ONE rule. Tier-A verbs never reach here (they never
    spend); an EXPLICIT zone (named by the caller) is honored with no scan."""
    if zone_explicit or not _is_spend_call(verb, params):
        return None
    from pipeline import workspacescaffold

    try:
        workspacescaffold.resolve_spend_zone(root, user, None)
    except workspacescaffold.SpendZoneError as exc:
        # A whole-invocation refusal (§21.7): the coded envelope carries the reason. `zone-required`
        # is an ENVELOPE code (the `Envelope` does not gate `code` against the §21.7 ResultItem
        # taxonomy, so no new §21.7 code is registered); the empty results list keeps the refusal a
        # pure envelope-fatal, parallel to the other three whole-invocation gates.
        return _fatal(
            verb, workspace, user, [], CODE_ZONE_REQUIRED, str(exc), zone=zone
        )
    return None


def invoke(
    verb: str,
    workspace: str,
    user: str,
    params: Mapping[str, Any] | None = None,
    token: Any = None,
    pins: Any = None,
    *,
    store: WorkspaceStore | None = None,
    root: str | Path = ".",
    zone: str = DEFAULT_ZONE,
    zone_explicit: bool = True,
    transport_override: str | None = None,
    handlers: Mapping[str, Handler] | None = None,
) -> dict[str, Any]:
    """One synchronous external-actor call (§21.1): `{envelope, results, [token]}`.

    `user` is MANDATORY and never defaulted (§23): it is the isolation PREFIX of the store leaf
    `root/users/<user>/zones/<zone>/workspaces/<workspace>/`, so a missing/None user fails LOUD at
    the door (`validate_workspace_path`) rather than ever building a `users/None/…` path. `zone`
    (§23, Z4) selects the zone segment between user and workspace; it defaults to `DEFAULT_ZONE`
    (the door materializes the real value at exactly one chokepoint) and is threaded into the
    workspace-root gate, the store build, AND `HandlerContext.zone`.

    The whole-invocation GATES run first, each envelope-fatal (§21.7):
    1. **unknown-verb** — `verb` not in `KNOWN_VERBS`;
    2. **isolation-violation (workspace root)** — when the store is built from the caller's
       `(user, workspace)` names (`store` not injected), the pair must resolve to a CONTAINED
       leaf under `users/<user>/workspaces/` (`pipeline.workspace_name.validate_workspace_path`);
       a `../other-client`, an absolute path, or a symlink escape at ANY of the three levels
       would move the very store root Gate 3 checks against, so it is refused BEFORE the store
       exists (§10/§21.1/§23 — the root sibling of the per-id gate);
    3. **invalid-token** — a supplied `token` fails `token.decode` against `workspace`
       (malformed/tampered/cross-version/wrong-workspace, §20);
    4. **isolation-violation** — any params-referenced id does not resolve in `workspace`
       (§21.1/§10).
    Past the gates, the verb dispatches to its registered handler; at step 32 the registry is
    empty, so a known verb raises `HandlerNotWired` (honest — never a fake success). A wired
    handler returns `(result_items, next_token?)`; per-item blocks ride `results` with `ok`
    still True (SM1). `store` (or `root` → `users/<user>/workspaces/<workspace>/`) locates the
    workspace; `handlers` overrides the registry (test/injection seam).
    """
    params = params or {}
    handlers = _VERB_HANDLERS if handlers is None else handlers

    # Gate 1 — unknown verb (whole-invocation invalid, §21.7).
    if verb not in KNOWN_VERBS:
        item = results.make_result(
            results.CODE_UNKNOWN_VERB,
            item=verb,
            hint=f"verb {verb!r} is not in the closed API verb set {sorted(KNOWN_VERBS)!r}",
        )
        return _fatal(
            verb, workspace, user, [item], results.CODE_UNKNOWN_VERB, str(item.item), zone=zone
        )

    # Workspace-root containment (§10/§21.1/§23): when the store is built from the CALLER-SUPPLIED
    # names, the `(user, workspace)` pair must resolve to a contained leaf under
    # `users/<user>/workspaces/` BEFORE the store exists — else a `../other-client`, an absolute
    # path, or a symlink escape at ANY level would MOVE the store root the isolation gate (Gate 3)
    # validates ids against, so ids would resolve in the WRONG workspace and pass. A breach is
    # whole-invocation-fatal, `isolation-violation`-class (the root sibling of the per-id gate). An
    # INJECTED store places nothing from the names. Validate ONCE here; `.at()` then builds the same
    # (byte-identical) leaf WITH identity so downstream reads user/workspace/framework_root loudly.
    if store is not None:
        ws_store = store
    else:
        try:
            validate_workspace_path(root, user, workspace, zone=zone)
        except WorkspaceNameError as exc:
            item = results.make_result(
                results.CODE_ISOLATION_VIOLATION,
                item=str(workspace),
                context={
                    "workspace": str(workspace),
                    "user": str(user),
                    "reason": exc.reason,
                    "segment": exc.segment,
                },
                hint=exc.detail,
            )
            return _fatal(
                verb,
                str(workspace),
                str(user),
                [item],
                results.CODE_ISOLATION_VIOLATION,
                exc.detail,
                zone=zone,
            )
        ws_store = WorkspaceStore.at(root, user, workspace, zone=zone)

    # Gate 2 — token decode/verification against the invoked workspace (§20).
    decoded: token_mod.Token | None = None
    if token is not None:
        try:
            decoded = token_mod.decode(token, expected_workspace=workspace)
        except token_mod.InvalidTokenError as exc:
            item = results.make_result(
                results.CODE_INVALID_TOKEN,
                item="token",
                context={"reason": exc.reason},
                hint=exc.detail,
            )
            return _fatal(
                verb, workspace, user, [item], results.CODE_INVALID_TOKEN, exc.detail, zone=zone
            )

    # Gate 3 — workspace isolation on every referenced id (§21.1/§10).
    violations = _isolation_violations(ws_store, workspace, user, referenced_ids(verb, params))
    if violations:
        return _fatal(
            verb,
            workspace,
            user,
            violations,
            results.CODE_ISOLATION_VIOLATION,
            f"{len(violations)} id(s) do not resolve inside workspace {workspace!r}",
            zone=zone,
        )

    # Gate 4 (plan G7 / B-1) — UNIFORM S4 at the shared chokepoint: a SPEND call by a >1-zone user
    # WITHOUT an explicit zone is refused HERE, so the CLI door AND the served `generate-next`/
    # `render` re-entry enforce ONE rule (never a silent spend in the wrong zone). Tier-A verbs and
    # an explicit zone pass straight through; the driver/transport apply the run-admission +
    # per-call tiers below the handler.
    zone_fatal = _zone_required_or_none(
        verb, workspace, user, params, root=root, zone=zone, zone_explicit=zone_explicit
    )
    if zone_fatal is not None:
        return zone_fatal

    # Dispatch — the thin real seam (step 32: unwired verbs raise HandlerNotWired).
    handler = handlers.get(verb)
    if handler is None:
        raise HandlerNotWired(verb)
    result_items, next_token = handler(
        HandlerContext(
            verb=verb,
            workspace=workspace,
            user=user,
            zone=zone,
            params=params,
            token=decoded,
            pins=pins,
            store=ws_store,
            transport_override=transport_override,
        )
    )
    envelope = results.Envelope(ok=True, verb=verb, workspace=workspace, user=user, zone=zone)
    out: dict[str, Any] = {
        "envelope": envelope.as_dict(),
        "results": [item.as_dict() for item in result_items],
    }
    if next_token is not None:
        out["token"] = token_mod.encode(next_token)
    return out


# ---------------------------------------------------------------------------
# The CLI (§21.1/§21.9): `scripts/pipeline invoke <verb> --workspace W --params-json …`
# → a single JSON object on stdout (the n8n-facing shape). Behind the `scripts/pipeline`
# shim, which routes `invoke` here (`python -m pipeline.api.invoke`).
# ---------------------------------------------------------------------------


def _load_json(label: str, raw: str | None, *, default: Any) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--{label} must be valid JSON: {exc}") from exc


def build_invoke_parser(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Configure the `pipeline invoke` parser (args + help) on a supplied parser, and return it.

    The SINGLE source of truth for `invoke`'s CLI surface: `main_cli` builds the runtime parser
    from it, and `pipeline.__main__.build_parser()` registers the `invoke` doc node from it too — so
    the runtime `invoke --help` and the generated `docs/reference/cli.md` share ONE definition (no
    hand-mirror that could drift). Behavior-neutral extraction (same parser as the inline one)."""
    parser.description = (
        "The external-actor API (design §21): one synchronous verb invocation → a single "
        "JSON object {envelope, results, [token]} on stdout (the n8n-facing shape)."
    )
    parser.add_argument("verb", help="the API verb (design §21.1 verb map)")
    parser.add_argument("--workspace", required=True, help="the invoked workspace (§21.1)")
    parser.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
    parser.add_argument(
        "--params-json", default=None, metavar="JSON", help="verb params as a JSON object"
    )
    parser.add_argument(
        "--token-json", default=None, metavar="JSON", help="the resumption token as JSON (§20)"
    )
    parser.add_argument(
        "--pins-json", default=None, metavar="JSON", help="explicit reproducibility pins (§21.8)"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/workspaces/<ws>/ (default: cwd)",
    )
    parser.add_argument(
        "--zone",
        default=None,
        help=(
            "the zone segment between user and workspace (§23; "
            f"users/<user>/zones/<zone>/workspaces/<workspace>/, default: {DEFAULT_ZONE}). For a "
            "SPEND verb (render), OMITTING it lets a >1-zone user be refused (uniform S4, G7); "
            "naming it (even 'default') is honored verbatim."
        ),
    )
    parser.add_argument(
        "--transport",
        default=None,
        metavar="MODE",
        help=(
            "per-run transport override (G7): 'subscription' | 'api' | 'key:<namespace>:<name>'. "
            "Selects a MODE / an assigned handle, never a user (I3). Default: the cascade decides."
        ),
    )
    return parser


def main_cli(argv: list[str] | None = None) -> int:
    """`invoke` on the CLI: params/token/pins as JSON in, one JSON object out.

    This is BOTH the human door and the n8n **Execute Command** door (§21.9, GAP-2):
    `pipeline invoke <verb> --workspace W --params-json JSON` → one JSON envelope on stdout.
    C7 wires the SAFE, STATELESS verbs — `render` (mint) + `fetch-by-id` (retrieve) — so the
    full render→retrieve loop is reachable here. SECURITY (§21.9): only those two verbs are
    wired. Operator-only verbs (`drift-report`, …) are NOT in `KNOWN_VERBS` → structurally
    unreachable through this door (they answer `unknown-verb`); the live-quota session verbs
    (`begin-session`/`continue-session`/…) and the `emit-outline` producer verb (reachable via
    programmatic `invoke()`, deliberately not CLI-wired) stay honestly `HandlerNotWired` → exit 3.

    n8n Execute Command CAVEAT (research 3a): the node is **off by default starting n8n v2.0**
    and is **unavailable on n8n Cloud** — SELF-HOSTED only. To drive this door from n8n, self-host
    and enable Execute Command; a cloud-hosted n8n (or Make/Zapier/Google) needs the deferred HTTP
    shim over this same `invoke()` (docs/known-issues.md DR-1). Per-item blocks (a `not-found`,
    `render-input-mismatch`) ride `results[]` at envelope `ok:true` → exit 0, so Execute Command
    never throws on them; only the three whole-invocation failures return exit 1 (JSON still on
    stdout).

    Exit codes: 0 = envelope ok; 1 = a whole-invocation failure (ok=False envelope still
    printed to stdout); 2 = usage/JSON error (stderr); 3 = a known verb whose handler is not
    wired (the honest unwired seam — never a fabricated success).
    """
    parser = build_invoke_parser(argparse.ArgumentParser(prog="pipeline invoke"))
    args = parser.parse_args(argv)

    try:
        params = _load_json("params-json", args.params_json, default={})
        token = _load_json("token-json", args.token_json, default=None)
        pins = _load_json("pins-json", args.pins_json, default=None)
    except ValueError as exc:
        print(f"pipeline invoke: {exc}", file=sys.stderr)
        return 2
    if not isinstance(params, Mapping):
        print("pipeline invoke: --params-json must be a JSON object", file=sys.stderr)
        return 2

    # C7 (GAP-2): wire the SAFE, STATELESS external-actor + human door — `render` + `fetch-by-id`
    # ONLY (never a live-quota session verb, never an operator verb). The function-scoped import is
    # MANDATORY: `render`/`fetch` top-import THIS module, so a top-level import here is circular.
    # `register_handler` is overwrite-safe, so re-wiring on every call is idempotent and hermetic.
    from pipeline.api import fetch as fetch_mod
    from pipeline.api import render as render_mod

    render_mod.register_render_handler()
    fetch_mod.register_fetch_handler()

    try:
        result = invoke(
            args.verb,
            args.workspace,
            args.user,
            params,
            token,
            pins,
            root=args.root,
            zone=args.zone if args.zone is not None else DEFAULT_ZONE,
            zone_explicit=args.zone is not None,
            transport_override=args.transport,
        )
    except HandlerNotWired as exc:
        print(f"pipeline invoke: {exc}", file=sys.stderr)
        return 3

    sys.stdout.write(canonical_json_str(result) + "\n")
    return 0 if result["envelope"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
