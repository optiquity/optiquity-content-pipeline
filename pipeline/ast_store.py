"""The layer-3 AST store: keyed by (fitted-id, reader-pin digest) — plan step 27.

Design authority: `docs/design.md`
  §18 — **What persists, keyed how.** `Pandoc AST | fitted-id (+ reader-pin digest) | yes —
        the interchange + fanout pivot.` **The AST store key's disambiguator is the
        reader-pin digest (FR7.1): api-version + the Markdown-reader extension set + the
        Pandoc version — api-version remains its dominant component. The AST's bytes depend
        on all three, so a reader-pin drift at an unchanged api-version lands the re-derived
        AST on a FRESH key, never an in-place rewrite.** This is internal store keying, not a
        D2 id — the AST is not an id-family member, so no grammar change (§7.4).
  §17 — a persisted AST whose reader-pin digest mismatches the pinned toolchain is re-derived
        from IR-fitted onto its new key (free, §18) — NEVER misread, never overwritten. A
        stale-pin AST is never silently served.
  §22.7 — the no-replace commit is the existence authority; this store mirrors
        `pipeline.store`'s content-addressed, no-overwrite discipline. No SSOT import.

**The store surface.** AST records live under `WorkspaceStore.artifacts_dir` (the §23 home for
"IR-canonical + IR-fitted + AST records"), with a filename that (a) never collides with the
bare-`fitted-id` IR-fitted record and (b) makes the reader-pin the key's visible disambiguator:

    <fitted-id>.ast.<reader-pin-hex12>.json              — a whole-fitted-id document (RI9)
    <fitted-id>~<part-slug>.ast.<reader-pin-hex12>.json  — a standalone part's own AST (RI9)

Two ASTs of one fitted-id under two reader-pins are two files, side by side — the drift history,
never an overwrite. The filename is constructed from the VALIDATED fitted-id (parsed §7.4) plus
the reader-pin digest and an optional slug label; it is never itself parsed as an id.

**Content-addressed idempotency.** Under ONE reader-pin key the AST is byte-reproducible (the
emitter + the single pinned parse are deterministic, §17). `put_ast` therefore treats an
already-present key with byte-identical content as an idempotent success (the no-replace commit
loser path), and refuses a same-key/different-bytes write LOUDLY as a determinism violation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pipeline.canonical import canonical_json_bytes, digest_hex12
from pipeline.ids import IdError, parse_id
from pipeline.ir import PANDOC_API_VERSION
from pipeline.serialize import PANDOC_VERSION_PIN, READER_PIN
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, write_new

__all__ = [
    "AstStoreError",
    "ast_path",
    "default_reader_pin_bundle",
    "get_ast",
    "put_ast",
    "reader_pin_bundle",
    "reader_pin_digest",
]

#: The `.ast.` infix + `.json` suffix that distinguish an AST record from the bare-`fitted-id`
#: IR-fitted record and from any id-family name (both `.` neighbours are non-slug: `ast`/`json`
#: are slugs but the composite name is never parsed as an id — see the module docstring).
_AST_INFIX = "ast"
_AST_SUFFIX = "json"


class AstStoreError(RuntimeError):
    """An AST-store contract breach — a same-key/different-bytes write, or a bad key. Loud."""

    code = "ast-store-error"


# ---------------------------------------------------------------------------
# The reader-pin bundle + its hex12 digest (the AST-store key disambiguator, §18/FR7.1).
# ---------------------------------------------------------------------------


def reader_pin_bundle(
    *,
    pandoc_version: str = PANDOC_VERSION_PIN,
    pandoc_api_version: tuple[int, ...] = PANDOC_API_VERSION,
    reader: str = READER_PIN,
) -> dict[str, Any]:
    """The three components whose canonical digest keys an AST (§18): the Pandoc version, the
    AST api-version (the dominant component), and the Markdown-reader extension set (the pin
    string). Config-pure — the PINNED bundle, never the installed environment (§17 FR7.1)."""
    return {
        "pandoc_api_version": list(pandoc_api_version),
        "pandoc_version": pandoc_version,
        "reader": reader,
    }


def reader_pin_digest(bundle: dict[str, Any]) -> str:
    """The `hex12` reader-pin digest — the AST store key's disambiguator (§18/FR7.1).

    Any drift in api-version, pandoc version, or the reader extension set changes this digest,
    so a re-derived AST lands on a FRESH key. Deterministic (canonical JSON, sorted keys).
    """
    return digest_hex12(bundle)


# ---------------------------------------------------------------------------
# Key → path (under artifacts_dir); the filename is built from a VALIDATED fitted-id.
# ---------------------------------------------------------------------------


def _require_fitted(fitted_id: str) -> None:
    try:
        parsed = parse_id(fitted_id)
    except IdError as exc:
        raise AstStoreError(f"ast-store-error: {fitted_id!r} is not a valid id ({exc})") from exc
    if parsed.family != "artifact" or parsed.level != "fitted" or parsed.part is not None:
        raise AstStoreError(
            f"ast-store-error: the AST store keys by a fitted-level id (§18), got {fitted_id!r}"
        )


def ast_path(
    store: WorkspaceStore, fitted_id: str, digest: str, *, label: str | None = None
) -> Path:
    """The on-disk path for an AST keyed by (`fitted_id`, reader-pin `digest`), optional part
    `label` (a standalone part's slug, RI9). Under `artifacts_dir`; filename never parsed as an
    id. `digest` must be the `hex12` reader-pin digest (12 lowercase hex)."""
    _require_fitted(fitted_id)
    if not (
        isinstance(digest, str)
        and len(digest) == 12
        and all(c in "0123456789abcdef" for c in digest)
    ):
        raise AstStoreError(
            f"ast-store-error: reader-pin digest must be 12 lowercase hex chars, got {digest!r}"
        )
    stem = fitted_id if label is None else f"{fitted_id}~{label}"
    return store.artifacts_dir / f"{stem}.{_AST_INFIX}.{digest}.{_AST_SUFFIX}"


# ---------------------------------------------------------------------------
# put / get — content-addressed, no-overwrite, drift → fresh key (§18, mirrors store.py).
# ---------------------------------------------------------------------------


def put_ast(
    store: WorkspaceStore,
    fitted_id: str,
    ast: dict[str, Any],
    *,
    bundle: dict[str, Any],
    label: str | None = None,
) -> tuple[Path, str]:
    """Persist `ast` under (`fitted_id`, reader-pin digest of `bundle`), optional part `label`.

    No-overwrite (§22.7/§18): a fresh key is written atomically via `store.write_new`. If the
    key already exists, the AST is byte-compared — identical content is an idempotent success
    (the deterministic re-derivation of the SAME pin), and a DIFFERENT content under the same
    key is refused LOUDLY (a determinism violation). Reader-pin DRIFT changes the digest, hence
    the filename, so a drifted AST always lands on a fresh key — the old key is never touched.
    Returns `(path, reader_pin_digest)`.
    """
    digest = reader_pin_digest(bundle)
    path = ast_path(store, fitted_id, digest, label=label)
    data = canonical_json_bytes(ast)
    try:
        write_new(path, data)
    except AlreadyMaterializedError:
        existing = path.read_bytes()
        if existing != data:
            raise AstStoreError(
                f"ast-store-error: {path.name} already holds DIFFERENT bytes under the same "
                "reader-pin key — serialize is meant to be deterministic under a fixed pin; "
                "a mismatch is a determinism defect, never a silent overwrite (§18)"
            ) from None
    return path, digest


def get_ast(
    store: WorkspaceStore,
    fitted_id: str,
    *,
    bundle: dict[str, Any],
    label: str | None = None,
) -> dict[str, Any] | None:
    """Fetch the AST for (`fitted_id`, reader-pin digest of `bundle`), or None if none exists.

    A stale-pin AST is NEVER silently served: fetching under a drifted `bundle` computes a
    different key and returns None, so the caller re-derives onto the fresh key (§17/§18).
    """
    digest = reader_pin_digest(bundle)
    path = ast_path(store, fitted_id, digest, label=label)
    if not path.exists():
        return None
    return json.loads(path.read_bytes())


def default_reader_pin_bundle() -> dict[str, Any]:
    """The pinned reader-pin bundle of record (gate step 3) — the common-case key input."""
    return reader_pin_bundle()
