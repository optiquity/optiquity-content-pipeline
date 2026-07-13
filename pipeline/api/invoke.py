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

__all__ = [
    "KNOWN_VERBS",
    "HandlerContext",
    "HandlerNotWired",
    "invoke",
    "main_cli",
    "referenced_ids",
    "register_handler",
    "resolve_in_workspace",
]

#: §21.1 verb map — the closed verb set. Read/Discovery: `list`, `get`. Generation/Session:
#: `begin-session`, `continue-session`. Folio: `create-folio`, `add-to-folio`. Output/
#: Retrieval: `emit-manifest`, `fetch-by-id`, `render`. Anything else → `unknown-verb`.
KNOWN_VERBS = frozenset(
    {
        "list",
        "get",
        "begin-session",
        "continue-session",
        "create-folio",
        "add-to-folio",
        "emit-manifest",
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
    the verb, the invoked workspace, the raw params, the DECODED token (or None), the
    supplied pins (or None), and the resolved workspace store."""

    verb: str
    workspace: str
    params: Mapping[str, Any]
    token: token_mod.Token | None
    pins: Any
    store: WorkspaceStore


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
    store: WorkspaceStore, workspace: str, referenced: list[tuple[str, str]]
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
                    context={"id": id_str, "workspace": workspace, "at": location},
                    hint=(
                        f"id {id_str!r} does not resolve inside workspace {workspace!r} — "
                        "workspaces never cross (§10)"
                    ),
                )
            )
    return violations


# ---------------------------------------------------------------------------
# The invocation (§21.1): gates → dispatch → {envelope, results, [token']}.
# ---------------------------------------------------------------------------


def _fatal(
    verb: str, workspace: str, items: Sequence[results.ResultItem], code: str, message: str
) -> dict[str, Any]:
    """A whole-invocation failure (§21.7): ok=False, the fatal items, and NO echoed token."""
    envelope = results.Envelope(
        ok=False, verb=verb, workspace=workspace, code=code, message=message
    )
    return {"envelope": envelope.as_dict(), "results": [i.as_dict() for i in items]}


def invoke(
    verb: str,
    workspace: str,
    params: Mapping[str, Any] | None = None,
    token: Any = None,
    pins: Any = None,
    *,
    store: WorkspaceStore | None = None,
    root: str | Path = ".",
    handlers: Mapping[str, Handler] | None = None,
) -> dict[str, Any]:
    """One synchronous external-actor call (§21.1): `{envelope, results, [token]}`.

    The three whole-invocation GATES run first, each envelope-fatal (§21.7):
    1. **unknown-verb** — `verb` not in `KNOWN_VERBS`;
    2. **invalid-token** — a supplied `token` fails `token.decode` against `workspace`
       (malformed/tampered/cross-version/wrong-workspace, §20);
    3. **isolation-violation** — any params-referenced id does not resolve in `workspace`
       (§21.1/§10).
    Past the gates, the verb dispatches to its registered handler; at step 32 the registry is
    empty, so a known verb raises `HandlerNotWired` (honest — never a fake success). A wired
    handler returns `(result_items, next_token?)`; per-item blocks ride `results` with `ok`
    still True (SM1). `store` (or `root` → `workspaces/<workspace>/`) locates the workspace;
    `handlers` overrides the registry (test/injection seam).
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
        return _fatal(verb, workspace, [item], results.CODE_UNKNOWN_VERB, str(item.item))

    ws_store = (
        store if store is not None else WorkspaceStore(Path(root) / "workspaces" / workspace)
    )

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
            return _fatal(verb, workspace, [item], results.CODE_INVALID_TOKEN, exc.detail)

    # Gate 3 — workspace isolation on every referenced id (§21.1/§10).
    violations = _isolation_violations(ws_store, workspace, referenced_ids(verb, params))
    if violations:
        return _fatal(
            verb,
            workspace,
            violations,
            results.CODE_ISOLATION_VIOLATION,
            f"{len(violations)} id(s) do not resolve inside workspace {workspace!r}",
        )

    # Dispatch — the thin real seam (step 32: unwired verbs raise HandlerNotWired).
    handler = handlers.get(verb)
    if handler is None:
        raise HandlerNotWired(verb)
    result_items, next_token = handler(
        HandlerContext(
            verb=verb,
            workspace=workspace,
            params=params,
            token=decoded,
            pins=pins,
            store=ws_store,
        )
    )
    envelope = results.Envelope(ok=True, verb=verb, workspace=workspace)
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


def main_cli(argv: list[str] | None = None) -> int:
    """`invoke` on the CLI: params/token/pins as JSON in, one JSON object out.

    Exit codes: 0 = envelope ok; 1 = a whole-invocation failure (ok=False envelope still
    printed to stdout); 2 = usage/JSON error (stderr); 3 = a known verb whose handler is not
    wired yet (step-32 honesty — no fake success).
    """
    parser = argparse.ArgumentParser(
        prog="pipeline invoke",
        description=(
            "The external-actor API (design §21): one synchronous verb invocation → a single "
            "JSON object {envelope, results, [token]} on stdout (the n8n-facing shape)."
        ),
    )
    parser.add_argument("verb", help="the API verb (design §21.1 verb map)")
    parser.add_argument("--workspace", required=True, help="the invoked workspace (§21.1)")
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
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
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

    try:
        result = invoke(args.verb, args.workspace, params, token, pins, root=args.root)
    except HandlerNotWired as exc:
        print(f"pipeline invoke: {exc}", file=sys.stderr)
        return 3

    sys.stdout.write(canonical_json_str(result) + "\n")
    return 0 if result["envelope"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main_cli())
