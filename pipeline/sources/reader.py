"""`CacheReaderAdapter` — the READ-ONLY cache-reader source adapter (design §6.1; sources P1).

Grounds over a PINNED, immutable slice of the sealed slice store (`pipeline.sources.cache`): it
reads a sealed slice by path, FTS5-queries it deterministically, and returns up to `budget` facts.
NO network, NO LLM, NO acquisition — the acquisition bodies (feeds P2, research P3) TARGET this
same core; the reader only reads it. Rule 1 is STRUCTURAL: this module holds no write primitive.

**The connection (§3.3 closed keyset, NO secrets):**
  - `path`   — the absolute cache-namespace directory (`…/sources/cache/<namespace>/`). Unlike the
               `folder` adapter, this path is EXPECTED inside the workspace's `users/` tree (it is
               the pipeline's OWN acquired-content store, not an external source repo), so no
               outside-`users/` guard applies. Read-only.
  - `budget` — a positive int, the deterministic first-`budget` cap on grounded facts (the
               `folder`/graphify `budget` analog).
  - `slice`  — OPTIONAL: an explicit sealed-slice digest to PIN. Present ⇒ full N2 immunity (see
               below). Absent ⇒ the namespace's published `HEAD` (convenience "latest" mode).

**THE SLICE-PINNING MECHANISM (the §3 design point): (c) the connection NAMES the slice.**
`ground(connection, query)` never receives the pinned digest as an argument, yet CF-1 requires it
read the SAME slice `pin_commit()` pinned, and N2 requires immunity to a mid-session acquire (an
out-of-band ingest that seals a NEW slice between plan-time pin and drive-time ground must NOT
shift what ground reads). Against the REAL driver flow — `driver.run_thread` builds ONE
`SourceInstance.connection` from static config and passes that SAME mapping to both
`adapter.pin_commit(connection)` (plan-time §7.2 pin) and `adapter.ground(connection=…)`
(drive-time), never mutating it between — the mechanisms decompose as:

  - **`slice: <digest>` (PINNED, the N2-immune form):** both `pin_commit` and `ground` resolve to
    that exact digest; the slice is content-addressed + IMMUTABLE + retained, so an out-of-band
    acquire that seals — even seals AND publishes — a NEW slice cannot shift it. CF-1 by
    construction; N2 by content-addressed immutability. This is the form P1 proves N2 against.
  - **`HEAD` (no `slice`, the convenience form):** both reads resolve the namespace HEAD; within
    the driver's single process, with P1's no-acquisition posture, pin and ground read the same
    HEAD (CF-1 holds). It is NOT immune to a mid-session PUBLISH (a HEAD advance shifts a later
    "latest" read) — the documented boundary of this form.

**THE DRIVER HEAD-FREEZE (mechanism (a); WIRED at P2a):** to give a `HEAD`-mode config full N2 the
DRIVER FREEZES the namespace HEAD digest captured at plan-time pin into the connection's `slice`
before grounding — the driver already captures the pin into the §7.2 `source_commit` map, and now
threads it back into the connection this adapter grounds. This is done via the `freeze_connection`
contract hook (`adapters.base.SourceAdapter.freeze_connection`, connection-AUGMENTATION — the
`ground` signature is untouched), which THIS adapter OVERRIDES to set `slice` to the pinned digest;
graphify/folder/fsast keep the default no-op (external-snapshot stability, CLOSED keysets
undisturbed). Applied at BOTH pin→ground seams — `driver.run_thread` and the production
`session._generate_next` drive path. CF-1 holds by construction: `pin_commit` over the frozen
connection re-resolves the SAME digest (the `slice` selector routes through the SAME `_resolve`).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pipeline.adapters.base import AdapterError, GroundingResult, SourceAdapter
from pipeline.sources.cache import (
    CacheError,
    query_facts,
    read_head,
    read_slice,
    require_digest,
    slice_path,
)

__all__ = ["CONNECTION_KEYS", "DEFAULT_BUDGET", "CacheReaderAdapter"]

#: The per-invocation fact budget default — the `folder` adapter's ceiling, so either adapter caps
#: its contribution to the writer prompt at the same order of magnitude.
DEFAULT_BUDGET = 2000

#: The CLOSED connection keyset (§3.3): the namespace path + the fact budget + the optional pinned
#: slice selector, nothing else. An unknown key fails LOUD (never a silent typo).
CONNECTION_KEYS = frozenset({"path", "budget", "slice"})


class CacheReaderAdapter(SourceAdapter):
    """`adapter: cache` — read-only FTS5 grounding over one PINNED, immutable sealed slice."""

    name = "cache"

    def _resolve(self, connection: Mapping[str, Any]) -> tuple[Path, int, str | None]:
        """Validate the closed connection and resolve `(namespace_dir, budget, digest_or_None)`.

        `digest` is the pinned `slice` when present, else the namespace `HEAD` (or `None` when
        nothing is published). BOTH `pin_commit` and `ground` route through this ONE resolver, so
        they can never disagree about which slice is in play (CF-1)."""
        if not isinstance(connection, Mapping):
            raise AdapterError(
                f"adapter-failure: cache connection must be a mapping, "
                f"got {type(connection).__name__}"
            )
        unknown = sorted(set(connection) - CONNECTION_KEYS)
        if unknown:
            raise AdapterError(
                f"adapter-failure: unknown cache connection key(s) {unknown!r} — the key set is "
                f"CLOSED ({', '.join(sorted(CONNECTION_KEYS))})"
            )
        raw_path = connection.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            raise AdapterError(
                "adapter-failure: cache connection requires `path`: the sealed-slice namespace "
                f"directory (read by path, rule 1); got {raw_path!r}"
            )
        path = Path(raw_path)
        if not path.is_absolute():
            raise AdapterError(
                f"adapter-failure: cache connection path must be ABSOLUTE, got {raw_path!r}"
            )
        ns_dir = path.resolve()
        if not ns_dir.exists():
            raise AdapterError(
                f"adapter-failure: cache namespace not found: {ns_dir} — an absent cache is a "
                "typed error, never a silent empty"
            )
        if not ns_dir.is_dir():
            raise AdapterError(
                f"adapter-failure: cache connection path is not a directory: {ns_dir}"
            )
        budget = connection.get("budget", DEFAULT_BUDGET)
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 1:
            raise AdapterError(
                f"adapter-failure: cache connection budget must be a positive integer "
                f"(deterministic first-N cap on grounded facts, default {DEFAULT_BUDGET}), "
                f"got {budget!r}"
            )
        digest = self._pinned_digest(connection, ns_dir)
        return ns_dir, budget, digest

    def _pinned_digest(self, connection: Mapping[str, Any], ns_dir: Path) -> str | None:
        """The digest this connection binds: the explicit `slice` pin, else the namespace HEAD
        (or `None` when nothing is published). A malformed `slice` / corrupt HEAD fails LOUD."""
        if "slice" in connection:
            raw = connection.get("slice")
            if not isinstance(raw, str):
                raise AdapterError(
                    f"adapter-failure: cache `slice` must be a 64-hex sealed digest, got {raw!r}"
                )
            try:
                return require_digest(raw)
            except CacheError as exc:
                raise AdapterError(f"adapter-failure: {exc}") from exc
        try:
            return read_head(ns_dir)
        except CacheError as exc:
            raise AdapterError(f"adapter-failure: {exc}") from exc

    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        """Read the PINNED slice and FTS5-query it deterministically (read-only, no network/LLM).

        Returns up to `budget` facts (subject/claim/tier/anchors/as_of) in the deterministic
        `rank, stable-id` order. `built_at_commit` is the sealed slice digest — the SAME marker
        `pin_commit` returns (CF-1). A namespace with nothing pinned/published grounds EMPTY +
        commitless (`None`) — the resolver's SM1 owns the empty outcome (the folder posture); a
        pinned-but-missing slice fails LOUD (a corrupt pin, never a silent empty)."""
        if not isinstance(query, str):
            raise AdapterError(
                f"adapter-failure: query must be a string, got {type(query).__name__}"
            )
        ns_dir, budget, digest = self._resolve(connection)
        if digest is None:
            return GroundingResult(facts=(), built_at_commit=None)  # nothing acquired yet (SM1)
        if not slice_path(ns_dir, digest).exists():
            raise AdapterError(
                f"adapter-failure: pinned slice {digest} is absent under {ns_dir} — a pinned "
                "slice is immutable + retained, so a missing one is a corrupt pin, never empty"
            )
        try:
            facts = read_slice(ns_dir, digest)
            grounded = query_facts(facts, query, budget)
        except CacheError as exc:
            raise AdapterError(f"adapter-failure: {exc}") from exc
        return GroundingResult(facts=grounded, built_at_commit=digest)

    def pin_commit(self, connection: Mapping[str, Any]) -> str | None:
        """The §7.2 identity commit-map value for a cache source — the SAME sealed digest `ground`
        reports for the SAME connection (both route through `_resolve`), so the artifact-id
        commit-map (identity) and the §15 grounding ledger never disagree about provenance (CF-1).
        `None` when nothing is pinned/published (the commitless posture; `ground` then grounds
        empty, so no diverged id is ever persisted). Read-only, never a write (rule 1)."""
        return self._resolve(connection)[2]

    def freeze_connection(
        self, connection: Mapping[str, Any], pinned_commit: str
    ) -> Mapping[str, Any]:
        """Freeze the plan-time pinned slice into the connection's `slice` selector, so the
        DRIVE-time `ground()` reads THAT sealed slice — not the (possibly-advanced) namespace
        HEAD. This is mechanism (a): it upgrades a `HEAD`-mode config (which a static config MUST
        use — it cannot hardcode a per-acquisition digest) to full N2, exactly as the pinned-digest
        form already has. `pinned_commit` is the digest THIS adapter's `pin_commit` returned for
        `connection` (validated as a bare 64-hex content address); it becomes the `slice` selector
        (an existing CLOSED-keyset member — the connection stays valid).

        Idempotent + CF-1-safe: a connection already carrying `slice` gets the SAME digest back
        (its `pin_commit` returned exactly that), and `pin_commit(frozen)` re-resolves it through
        the SAME `_resolve`, so identity never shifts. A malformed pin fails LOUD here (a corrupt
        pin, never a silent live-HEAD fallthrough)."""
        try:
            digest = require_digest(pinned_commit)
        except CacheError as exc:
            raise AdapterError(
                f"adapter-failure: cannot freeze a non-digest cache commit {pinned_commit!r} "
                f"into `slice` ({exc}) — the plan-time pin must be a sealed slice digest"
            ) from exc
        frozen = dict(connection)
        frozen["slice"] = digest
        return frozen
