"""`fetch-by-id` — the DUMB HOT PATH of the external-actor API (§21.5).

Design authority: `docs/design.md`
  §21.5  — `fetch-by-id(id, return = path | bytes)` — default `path`: a workspace path/link
           is stable and lets the external publisher stream bytes itself; `bytes` is opt-in
           for small payloads (e.g. the AST JSON). Works on any id type; the response names
           the id and pins, self-describing.
  §21.8  — retrieval is the DUMB HOT PATH: ZERO currency evaluation, ZERO minting, no
           resolution. `fetch-by-id` on ANY old/superseded id returns its UNCHANGED bytes
           forever (immutability / indefinite retention, §21.8) — currency is a computed
           FIELD on the discovery read surfaces (§21.3), NEVER touched here, so fetch stays
           dumb and the code set stays small (FR4). Minting happens in `render` ONLY.
  §22.7  — content-addressed retrieval: the stored output IS the authority. This handler
           reads the OUTPUT STORE only (never the SSOT, never a resolution pass).

**What this handler does NOT do (by construction):** it evaluates no `fit_current`/
`serialize_current`, resolves no fit/serialize revision, mints nothing, and reads no config.
Given a workspace-gated id (Gate 3 already vetted it, §21.1), it returns the stored payload's
path or bytes, verbatim. The isolation gate guarantees the id resolves in this workspace, so a
`not-found` here is only the narrow case where the id's record was reachable at gate time but
its payload is unreadable — surfaced honestly, never guessed.
"""

from __future__ import annotations

import base64
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pipeline.api import invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.ids import IdError, parse_id
from pipeline.store import WorkspaceStore

__all__ = [
    "RETURN_BYTES",
    "RETURN_PATH",
    "fetch_handler",
    "register_fetch_handler",
    "resolve_payload_path",
]

#: §21.5 `return` modes — `path` (default; the stable workspace link) and `bytes` (opt-in).
RETURN_PATH = "path"
RETURN_BYTES = "bytes"


def resolve_payload_path(store: WorkspaceStore, id_str: str) -> Path | None:
    """The stored payload path for `id_str` — content-addressed, ZERO resolution (§21.8).

    For a deliverable-id the meaningful payload is the persisted layer-2 BYTES sibling
    (`deliverables/<id>.<ext>`) when present; otherwise (and for artifact-/fitted-level ids)
    the id-keyed output RECORD (`output_path`, the §18 store location — e.g. the AST JSON the
    §21.5 `bytes` mode is meant for). Reads the output store ONLY; mints nothing, resolves no
    revision. `None` when neither exists (the id was gate-reachable but has no payload here).
    """
    try:
        parsed = parse_id(id_str)
    except IdError:
        return None
    if parsed.family != "artifact":
        return None  # folio/run ids are not fetchable outputs (§18)
    if parsed.level == "deliverable":
        # Prefer the layer-2 bytes sibling (the real deliverable); the extension is not part
        # of the id (§7.4), so scan for `<id>` or `<id>.<ext>` — an exact content-addressed
        # match, never a prefix-of-a-longer-id match (a longer id would sort under a DIFFERENT
        # base name because ids never embed a bare `.` except the coordinate dots already in id).
        bytes_hit = _layer2_bytes(store, id_str)
        if bytes_hit is not None:
            return bytes_hit
    record = store.output_path(id_str)
    return record if record.exists() else None


def _layer2_bytes(store: WorkspaceStore, deliverable_id: str) -> Path | None:
    """The persisted layer-2 bytes file for a deliverable-id, or None (§18: `deliverables/`).

    The extensioned form is `<id>.<ext>`; the bare `<id>` is the render-binding RECORD (handled
    by the caller's record fallback, never here). Only the extensioned layer-2 payload is
    returned — the real deliverable bytes."""
    for entry in sorted(store.deliverables_dir.glob(f"{deliverable_id}.*")):
        if entry.is_file():
            return entry
    return None


def _fetch_by_id(
    ctx: invoke_mod.HandlerContext,
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """`fetch-by-id` (§21.5): return the stored payload's path or bytes — dumb, no minting.

    `params.id` is already Gate-3-isolated (§21.1), so it resolves in this workspace. `params
    .return` is `path` (default) or `bytes`. The result names the id, echoes the `return`
    mode, and self-describes with the payload location; a `bytes` payload is returned as UTF-8
    text where decodable, else base64 (`context.encoding`), never a lie about the bytes."""
    params: Mapping[str, Any] = ctx.params
    id_str = params.get("id")
    if not isinstance(id_str, str) or not id_str:
        return (
            [results.make_result(
                results.CODE_NOT_FOUND,
                item=str(id_str) if id_str is not None else "",
                hint="fetch-by-id needs an `id` (§21.5) — the id to retrieve",
            )],
            None,
        )

    return_mode = params.get("return", RETURN_PATH)
    if return_mode not in (RETURN_PATH, RETURN_BYTES):
        return (
            [results.make_result(
                results.CODE_NOT_FOUND,
                item=id_str,
                ids={"id": id_str},
                hint=f"`return` is {RETURN_PATH!r} (default) or {RETURN_BYTES!r} (§21.5), "
                f"got {return_mode!r}",
            )],
            None,
        )

    payload = resolve_payload_path(ctx.store, id_str)
    if payload is None:
        # Gate 3 vetted the id resolves here, so this is the narrow unreadable-payload case —
        # honest, never a guessed or minted substitute (the dumb path mints NOTHING, §21.8).
        return (
            [results.make_result(
                results.CODE_NOT_FOUND,
                item=id_str,
                ids={"id": id_str},
                hint=f"no stored payload for {id_str!r} in this workspace (§21.5)",
            )],
            None,
        )

    rel = _workspace_relative(ctx.store, payload)
    if return_mode == RETURN_PATH:
        return (
            [results.ResultItem(
                item=id_str,
                status="ok",
                ids={"id": id_str},
                output={"path": rel},
                context={"return": RETURN_PATH},
            )],
            None,
        )

    raw = payload.read_bytes()  # verbatim — a superseded id returns byte-identical old content
    output, encoding = _encode_bytes(raw)
    return (
        [results.ResultItem(
            item=id_str,
            status="ok",
            ids={"id": id_str},
            output=output,
            context={"return": RETURN_BYTES, "path": rel, "encoding": encoding},
        )],
        None,
    )


def _workspace_relative(store: WorkspaceStore, path: Path) -> str:
    """The workspace-relative path string (§21.5: a stable workspace link)."""
    try:
        return str(path.relative_to(store.root))
    except ValueError:  # pragma: no cover — payloads always live under the store root
        return str(path)


def _encode_bytes(raw: bytes) -> tuple[dict[str, Any], str]:
    """`{bytes: <text>}` UTF-8 where decodable (the AST-JSON case, §21.5), else base64."""
    try:
        return {"bytes": raw.decode("utf-8")}, "utf-8"
    except UnicodeDecodeError:
        return {"bytes": base64.b64encode(raw).decode("ascii")}, "base64"


def fetch_handler() -> invoke_mod.Handler:
    """The `fetch-by-id` handler (no seams — retrieval is pure store I/O, §21.5)."""

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _fetch_by_id(ctx)

    return handler


def register_fetch_handler() -> None:
    """Wire `fetch-by-id` into the invoke dispatch registry (§21.1). EXPLICIT — never at
    import (keeps the step-32 unwired-registry tests valid)."""
    invoke_mod.register_handler("fetch-by-id", fetch_handler())
