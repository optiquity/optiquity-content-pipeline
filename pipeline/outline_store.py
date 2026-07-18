"""The pre-compose outline store: authored-and-edited outline Markdown, content-addressed by its
BARE `outline-digest` — DR-3 build, Commit 5 (horn (a) / B1).

Design authority: `docs/design.md`
  §22.7 — the no-replace commit is the existence authority; this store mirrors
        `pipeline.store`'s content-addressed, no-overwrite discipline (reused VERBATIM through
        `write_new` / `AlreadyMaterializedError`). No SSOT import, no id minting, no time.
  §15 / §3.3 — the accept path refuses an empty / no-substance outline and a secret-shaped one
        LOUDLY, through `pipeline.outline.accept_outline` (one place of record for both floors).
  §21.8 / §27.3 — RETAIN-ALL (v1): every authored scaffold and every intermediate edit is kept
        indefinitely, content-addressed. This store exposes NO delete / NO GC — an abandoned
        outline and every edit-in-flight are retained BY DESIGN; a future GC is registered
        (§27.3), never designed here.

**The bare-digest key (NOT a §7.4 id).** The key is `pipeline.outline.outline_digest(md)` — the
FULL 64-char lowercase-hex SHA-256 of `normalize_outline(md)`. It is a CONTENT ADDRESS in the
`source-commit` category, NOT an artifact/run/folio id: it carries no `a-`/`f-`/`r-` prefix, is
NEVER minted through `pipeline.ids`, and is NEVER `parse_id`-parsed. This module imports neither
`pipeline.ids` nor `parse_id`; the digest shape is validated DIRECTLY (`_require_digest`: 64
lowercase hex), keeping the bare-digest addressing ISOLATED from the id family. That isolation is
exactly why this lives in its own module and is not folded into `pipeline.store`, whose every
path method routes through `parse_id` (a bare digest would be refused there as a malformed id).

**The store home.** Outlines live in a dedicated `outlines/` directory under the workspace root
(`<root>/outlines/<digest>`) — a flat, digest-addressed namespace, one file per distinct
normalized outline, the filename the bare digest with NO extension (the filename IS the key IS
the content address). A bare 64-hex filename can never collide with a §7.4 id-named record (ids
carry a family prefix), and keeping outlines OUT of `artifacts/` (§18: IR-canonical / IR-fitted /
AST records) keeps a pre-compose SOURCE distinct from the IR record it later becomes the body of
(the Commit 4 emit bridge). Directory creation is on demand (the caller owns workspace placement,
rule 2); this module names / creates nothing outside the caller-supplied `store.root`.

**Content-addressed idempotency (§22.7).** The filename IS the digest of the EXACT bytes stored,
so persisting the same outline twice is an idempotent no-op: the no-replace commit loser path
(`AlreadyMaterializedError`) finds byte-identical content and returns quietly. A same-digest /
DIFFERENT-bytes write is impossible without a SHA-256 collision; were one ever to surface it is
refused LOUDLY (a collision / corruption guard), never a silent overwrite — the same defensive
posture as `pipeline.ast_store`.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.outline import accept_outline, outline_digest
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, write_new

__all__ = [
    "OUTLINES_SUBDIR",
    "OutlineStoreError",
    "get_outline",
    "outline_path",
    "put_outline",
]

#: The dedicated per-workspace home for content-addressed outlines: `<root>/outlines/<digest>`.
#: NOT in `store.STORE_SUBDIRS` (that is the §23 id-addressed core) — a DR-3 pre-compose store,
#: created on demand by `write_new`. The §27.3 layout note is batched into the later doc-sync.
OUTLINES_SUBDIR = "outlines"

_DIGEST_HEX = frozenset("0123456789abcdef")
#: A FULL SHA-256 in lowercase hex (§7.4 digest form) — the bare outline content address.
_DIGEST_LEN = 64


class OutlineStoreError(RuntimeError):
    """An outline-store contract breach — a malformed digest key, or a same-digest / different-
    bytes write (a SHA-256 collision or on-disk corruption). Loud, never a silent overwrite."""

    code = "outline-store-error"


def _require_digest(digest: str) -> None:
    """Validate the BARE `outline-digest` key DIRECTLY (§7.4 digest form) — never via `parse_id`.

    The key is a content address, NOT an id: exactly 64 lowercase-hex chars, no family prefix.
    This is the keying-discipline teeth — the store never routes the digest through `pipeline.ids`.
    """
    if not (isinstance(digest, str) and len(digest) == _DIGEST_LEN and set(digest) <= _DIGEST_HEX):
        raise OutlineStoreError(
            "outline-store-error: an outline key is a BARE 64-char lowercase-hex outline-digest "
            f"(a content address, NOT a §7.4 id), got {digest!r}"
        )


def outline_path(store: WorkspaceStore, digest: str) -> Path:
    """The on-disk path for the outline content-addressed by `digest`: `<root>/outlines/<digest>`.

    `digest` is validated as a bare 64-hex content address (`_require_digest`) — NEVER parsed as
    an id. The filename IS the key IS the digest (no extension), so a directory listing is a clean
    set of content addresses and `path.name == digest` by construction.
    """
    _require_digest(digest)
    return store.root / OUTLINES_SUBDIR / digest


def put_outline(store: WorkspaceStore, md: str) -> str:
    """Accept + persist a raw outline; return its bare `outline-digest` (the content address).

    The accept path (`pipeline.outline.accept_outline`) runs `N` + the §15 substance floor + the
    §3.3 secret scan and raises LOUDLY on an empty / no-substance outline (`EmptyOutlineError`)
    or a secret-shaped one (`SecretShapedOutlineError`) — an invalid outline never reaches disk.
    The NORMALIZED bytes `N(md)` are committed under `outline_digest(md)` via the no-replace
    `write_new` (§22.3 / §22.7). Persisting the same outline twice is an idempotent no-op
    (content-addressed: same digest -> byte-identical `N(md)` -> the `already-materialized` loser
    path, swallowed); a same-digest / DIFFERENT-bytes collision is refused LOUDLY. Returns the
    digest.
    """
    normalized = accept_outline(md)  # N + §15/§3.3 refusals — raises BEFORE any write
    data = normalized.encode("utf-8")
    digest = outline_digest(md)  # the ONE shared content-address fn (== sha256_hex(data))
    path = outline_path(store, digest)
    try:
        write_new(path, data)
    except AlreadyMaterializedError:
        existing = path.read_bytes()
        if existing != data:  # impossible without a SHA-256 collision — refuse, never overwrite
            raise OutlineStoreError(
                f"outline-store-error: {digest} already stores DIFFERENT bytes — an outline is "
                "content-addressed by the SHA-256 of its normalized form, so a mismatch is a "
                "collision or corruption, never a silent overwrite (§22.7)"
            ) from None
    return digest


def get_outline(store: WorkspaceStore, digest: str) -> str | None:
    """Load the normalized outline `N(md)` content-addressed by `digest`, or None if none exists.

    Absence is signalled by None (the clean not-found path — the store never crashes on an unknown
    digest), mirroring how `pipeline.store` signals a missing object by existence. The returned
    string is exactly `normalize_outline(md)`; its UTF-8 bytes are byte-for-byte the persisted
    `N(md)`. `digest` is validated as a bare content address, never `parse_id`-parsed.
    """
    path = outline_path(store, digest)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")
