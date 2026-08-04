"""The sealed, content-addressed slice store — the sources subsystem's shared read+storage core
(design §6; sources P1). Populated by FIXTURES in P1; by the feeds (P2) / research (P3)
acquisition bodies later. There is NO acquisition body here.

Design authority + reused precedents (this module INVENTS no new store discipline):
  §22.7 / §21.8 — the no-replace commit is the existence authority; RETAIN-ALL. A sealed slice
        is content-addressed, written ONCE via `pipeline.store.write_new`, and NEVER mutated —
        the exact discipline of `pipeline.outline_store` (bare-digest filename = the key = the
        content address) and `pipeline.ast_store` (idempotent same-bytes re-seal; a same-digest/
        DIFFERENT-bytes write is refused LOUDLY as a collision/corruption, never a silent
        overwrite).
  §6.2 — a fact carries the confidence TIER, traceability ANCHORS, and a date-granular freshness
        basis (`as_of`); those five fields (subject/claim/tier/anchors/as_of) are exactly what a
        slice stores and the reader hands back. reuse_rights (P0, from the source instance's
        content-kind, applied by the RESOLVER) and temporality/ledger (P2) are NOT stored here.
  §22.3 — the acquire/ground mutex is the §22.3 lease (`pipeline.claims.ClaimRegistry`), keyed by
        a `mint_run_id` run-family id derived from the namespace (a NON-artifact id, so it can
        never masquerade as an output). Built + unit-tested here; the FUTURE acquire takes it.

**A SLICE** is a set of tier-stamped facts sealed together and content-addressed by the SHA-256
DIGEST of its canonical bytes. The digest IS the identity (the graphify `built_at_commit` analog):
it changes iff the content changes, so it is collision-proof and NEVER `None` (a `None` pin would
collide different content onto one artifact-id — cf. `pipeline.ids` §7.2). Facts are deduped by a
stable content id (exact-id dedup; a near-dup MinHash/SimHash hook is registered, not built — v1
exact-id is fine) and SORTED by that id before sealing, so identical fact SETS (any input order)
yield the identical slice digest, and different sets yield different digests.

**THE QUERYABLE PROJECTION is SQLite + FTS5, REBUILT FROM THE RAW LOG on every query** (the log —
the sealed slice files — is the truth). P1 materializes the projection IN-MEMORY per query: the
simplest honest form of "rebuildable from the log" (it is ALWAYS rebuilt, is deterministic, and
carries zero stale-index / concurrent-write surface). A persisted per-slice index is a transparent
future optimization behind this same interface (the log stays truth). FTS5 is a compile-time SQLite
option: `probe_fts5()` fails LOUD (a typed `FtsUnavailableError`) if it is absent — never a silent
degrade. Any budget-LIMITed query orders by `rank, <stable-id tiebreak>` (FTS5's default order is
unstable), so the same slice+query+budget returns the same rows in the same order — resolver
idempotency.

**The store home** is `users/<user>/workspaces/<ws>/sources/cache/<namespace>/` (a `store.py`
`sources/cache` STORE_SUBDIR — identity-inert, gitignored via `users/*/workspaces/`). A namespace
holds `slices/<digest>` (immutable, bare-digest-addressed) and an atomic `HEAD` marker naming the
current published slice. This module names/creates nothing outside a CALLER-supplied namespace dir.
"""

from __future__ import annotations

import datetime
import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.adapters.base import Anchor, Fact
from pipeline.canonical import canonical_json_bytes, canonical_json_str, sha256_hex
from pipeline.claims import AcquireOutcome, ClaimRegistry, ReleaseOutcome
from pipeline.ids import mint_run_id
from pipeline.store import (
    AlreadyMaterializedError,
    WorkspaceStore,
    write_new,
    write_replace,
)

__all__ = [
    "CACHE_SLICE_VERSION",
    "HEAD_MARKER",
    "SLICES_SUBDIR",
    "CacheError",
    "CacheNamespaceLock",
    "FtsUnavailableError",
    "fact_from_record",
    "fact_to_record",
    "namespace_dir",
    "namespace_lease_id",
    "probe_fts5",
    "publish_head",
    "query_facts",
    "read_head",
    "read_slice",
    "require_digest",
    "seal_slice",
    "slice_digest",
    "slice_path",
    "stable_fact_id",
]

#: The sealed-slice envelope version (a slice is `{version, facts:[...]}`). A bump changes the
#: canonical bytes → every digest → a fresh key; existing sealed slices are never rewritten.
CACHE_SLICE_VERSION = 1

#: A namespace's immutable slices live here (`<namespace>/slices/<digest>`), bare-digest-named
#: (the filename IS the key IS the content address — the `outline_store` discipline).
SLICES_SUBDIR = "slices"

#: The atomic marker naming a namespace's currently-published slice (`<namespace>/HEAD`). Updated
#: via `write_replace` (§21.2 marker semantics) under the acquire/ground lease.
HEAD_MARKER = "HEAD"

_DIGEST_HEX = frozenset("0123456789abcdef")
_DIGEST_LEN = 64  # a FULL SHA-256 in lowercase hex (§7.4 digest form)

#: A namespace name is a single safe path segment: a slug of `[a-z0-9._-]`, no leading dot, no
#: separator, no traversal. (The reader binds a namespace by absolute PATH; this validation guards
#: the store-side `namespace_dir` join and the fixture/acquire seal path.)
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

#: FTS5 word tokens for the deterministic MATCH (unicode word runs; quoted as phrases so a query
#: can never inject an FTS5 operator). Empty token set ⇒ match-all (byte-parity with the mock /
#: folder adapters' "empty query = whole corpus").
_WORD_RE = re.compile(r"\w+", re.UNICODE)


class CacheError(RuntimeError):
    """A cache-store contract breach — a malformed digest/namespace, a same-digest/different-bytes
    seal (a SHA-256 collision or corruption), or a corrupt HEAD/slice. Loud, never silent."""

    code = "sources-cache-error"


class FtsUnavailableError(RuntimeError):
    """This SQLite build lacks the compile-time FTS5 option — the cache cannot query. Raised LOUD
    by `probe_fts5()`; the reader never silently degrades to a non-FTS scan."""

    code = "fts5-unavailable"


def probe_fts5() -> None:
    """Fail LOUD if this interpreter's SQLite has no FTS5 (a compile-time option).

    Run at every query (cheap — an in-memory create-and-drop) so a missing FTS5 surfaces as a
    typed `FtsUnavailableError` with a clear message, never a silent fallback to a lesser search.
    """
    try:
        conn = sqlite3.connect(":memory:")
    except sqlite3.Error as exc:  # pragma: no cover — sqlite3 import implies a usable connect
        raise FtsUnavailableError(f"fts5-unavailable: could not open SQLite: {exc}") from exc
    try:
        conn.execute("CREATE VIRTUAL TABLE _probe USING fts5(x)")
    except sqlite3.Error as exc:
        raise FtsUnavailableError(
            "fts5-unavailable: this SQLite build has no FTS5 (a compile-time option) — the "
            f"sources cache requires it for grounding queries ({exc})"
        ) from exc
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fact <-> record: the five §6.2 fields a slice stores (subject/claim/tier/anchors/as_of).
# ---------------------------------------------------------------------------


def fact_to_record(fact: Fact) -> dict[str, object]:
    """One `Fact` → its canonical sealed record: exactly the five §6.2 fields.

    reuse_rights / temporality / per-fact refinements are NOT stored (the reader emits none; those
    ride the source instance's content-kind via the resolver — P0/P2). Anchors keep their given
    order (a fact's anchor list is authored, not a set)."""
    return {
        "subject": fact.subject,
        "claim": fact.claim,
        "tier": fact.tier,
        "anchors": [[a.kind, a.value] for a in fact.anchors],
        "as_of": fact.as_of.isoformat() if fact.as_of is not None else None,
    }


def fact_from_record(record: Mapping[str, object]) -> Fact:
    """A sealed record → a `Fact` (the round-trip inverse of `fact_to_record`).

    `Fact.__post_init__` re-validates every field, so a corrupt record fails LOUD at the contract
    boundary (unknown tier/anchor kind, a non-date `as_of`) rather than grounding bad data."""
    raw_anchors = record.get("anchors", [])
    if not isinstance(raw_anchors, list):
        raise CacheError(f"sources-cache-error: slice anchors must be a list, got {raw_anchors!r}")
    anchors = tuple(Anchor(kind=str(pair[0]), value=str(pair[1])) for pair in raw_anchors)
    raw_as_of = record.get("as_of")
    as_of = datetime.date.fromisoformat(raw_as_of) if isinstance(raw_as_of, str) else None
    return Fact(
        subject=str(record.get("subject", "")),
        claim=str(record.get("claim", "")),
        tier=str(record.get("tier", "")),
        anchors=anchors,
        as_of=as_of,
    )


def stable_fact_id(record: Mapping[str, object]) -> str:
    """The exact-content stable id for dedup + the deterministic query tiebreak: the full SHA-256
    of the record's canonical bytes. Identical facts share it; a near-dup hook (MinHash/SimHash)
    is registered for a later increment — v1 exact-id dedup is fine (module docstring)."""
    return sha256_hex(canonical_json_bytes(dict(record)))


# ---------------------------------------------------------------------------
# Sealing: dedup + sort + content-address (the outline_store / ast_store discipline).
# ---------------------------------------------------------------------------


def _slice_object(facts: Sequence[Fact]) -> tuple[dict[str, object], bytes, str]:
    """Build the canonical sealed-slice object, its bytes, and its digest from `facts`.

    Facts are turned into records, DEDUPED by `stable_fact_id` (exact-id primary), and SORTED by
    that id, so identical fact SETS (any input order) collapse to identical bytes → identical
    digest (collision-proof), and different sets diverge. The digest is the FULL SHA-256 of the
    canonical bytes — never `None`."""
    deduped: dict[str, dict[str, object]] = {}
    for fact in facts:
        record = fact_to_record(fact)
        deduped.setdefault(stable_fact_id(record), record)
    ordered = [deduped[sid] for sid in sorted(deduped)]
    obj: dict[str, object] = {"version": CACHE_SLICE_VERSION, "facts": ordered}
    data = canonical_json_bytes(obj)
    return obj, data, sha256_hex(data)


def slice_digest(facts: Sequence[Fact]) -> str:
    """The sealed digest `facts` WOULD get (pure; no I/O) — the content address / `built_at_commit`
    a seal produces. The single source of the digest, so a caller can pin before/without sealing."""
    return _slice_object(facts)[2]


def require_digest(digest: str) -> str:
    """Validate a slice digest as a BARE 64-char lowercase-hex content address (never a §7.4 id),
    returning it unchanged. The keying-discipline teeth — a digest is never routed through
    `pipeline.ids` (a bare digest carries no `a-`/`f-`/`r-` family prefix)."""
    if not (isinstance(digest, str) and len(digest) == _DIGEST_LEN and set(digest) <= _DIGEST_HEX):
        raise CacheError(
            "sources-cache-error: a slice key is a BARE 64-char lowercase-hex content digest "
            f"(NOT a §7.4 id), got {digest!r}"
        )
    return digest


def _require_namespace(name: str) -> str:
    if not (isinstance(name, str) and _NAMESPACE_RE.match(name)):
        raise CacheError(
            "sources-cache-error: a cache namespace is a safe slug [a-z0-9._-], no leading dot / "
            f"separator / traversal, got {name!r}"
        )
    return name


def namespace_dir(store: WorkspaceStore, namespace: str) -> Path:
    """The per-namespace home under the workspace cache store: `sources/cache/<namespace>/`.

    Created on demand (via `store.sources_cache_dir`, a `store.py` STORE_SUBDIR). The reader binds
    a namespace by absolute PATH (the folder-adapter posture); this is the store-side bridge the
    FIXTURES + the future acquire use to seal into a workspace."""
    _require_namespace(namespace)
    path = store.sources_cache_dir / namespace
    path.mkdir(parents=True, exist_ok=True)
    return path


def slice_path(ns_dir: Path, digest: str) -> Path:
    """`<namespace>/slices/<digest>` — the immutable sealed slice's path. `digest` is validated as
    a bare content address (never `parse_id`-parsed); the filename IS the key IS the digest."""
    return Path(ns_dir) / SLICES_SUBDIR / require_digest(digest)


def seal_slice(ns_dir: Path, facts: Sequence[Fact]) -> str:
    """Seal `facts` into `ns_dir` as an immutable, content-addressed slice; return its digest.

    Content-addressed idempotency (§22.7, the `outline_store` pattern): the same fact set seals to
    the same digest → byte-identical bytes → the no-replace commit's `already-materialized` loser
    path, swallowed. A same-digest / DIFFERENT-bytes write is impossible without a SHA-256
    collision; were one to surface it is refused LOUDLY (a collision/corruption guard), never a
    silent overwrite. The write is atomic (`write_new`): a slice is wholly present or wholly
    absent, never partial. Sealing does NOT touch HEAD (see `publish_head`)."""
    _, data, digest = _slice_object(facts)
    path = slice_path(ns_dir, digest)
    try:
        write_new(path, data)
    except AlreadyMaterializedError:
        if path.read_bytes() != data:  # impossible without a SHA-256 collision — refuse
            raise CacheError(
                f"sources-cache-error: {digest} already stores DIFFERENT bytes — a slice is "
                "content-addressed by the SHA-256 of its canonical bytes, so a mismatch is a "
                "collision or corruption, never a silent overwrite (§22.7)"
            ) from None
    return digest


def read_slice(ns_dir: Path, digest: str) -> tuple[Fact, ...]:
    """Load the immutable slice at `digest` as its facts, or raise LOUD if it is absent/corrupt.

    A read of a SEALED slice is tear-proof by construction: the file was written atomically and is
    NEVER mutated (retain-all), so no lease is needed to read it safely. An absent pinned slice is
    a corrupt-pin / not-yet-acquired error — the caller (reader) decides loud-vs-empty."""
    path = slice_path(ns_dir, digest)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise CacheError(
            f"sources-cache-error: no sealed slice {digest} in {ns_dir} — a pinned slice must "
            "exist (it is immutable + retained once sealed)"
        ) from exc
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise CacheError(f"sources-cache-error: slice {digest} is not valid JSON: {exc}") from exc
    facts = obj.get("facts") if isinstance(obj, Mapping) else None
    if not isinstance(facts, list):
        raise CacheError(f"sources-cache-error: slice {digest} has no `facts` list")
    return tuple(fact_from_record(record) for record in facts)


# ---------------------------------------------------------------------------
# The namespace HEAD marker (published-view pointer) — atomic, lease-guarded advance.
# ---------------------------------------------------------------------------


def read_head(ns_dir: Path) -> str | None:
    """The digest a namespace's `HEAD` marker names, or `None` when nothing is published yet.

    A missing HEAD is the honest "nothing acquired yet" state (`None`), not an error. A PRESENT
    but malformed HEAD is corrupt → LOUD `CacheError`."""
    path = Path(ns_dir) / HEAD_MARKER
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    return require_digest(raw)


def publish_head(ns_dir: Path, digest: str) -> None:
    """Atomically advance the namespace `HEAD` marker to a sealed slice `digest` (§21.2 marker
    update via `write_replace`). The FUTURE acquire (P2/P3) calls this UNDER the acquire/ground
    lease so a concurrent HEAD-mode reader never observes a half-published pointer. The slice must
    already be sealed (the digest is validated; existence is the caller's ordering discipline)."""
    Path(ns_dir).mkdir(parents=True, exist_ok=True)
    write_replace(Path(ns_dir) / HEAD_MARKER, (require_digest(digest) + "\n").encode("utf-8"))


# ---------------------------------------------------------------------------
# The FTS5 queryable projection — rebuilt in-memory from the slice (the log is truth).
# ---------------------------------------------------------------------------


def _fts_match(query: str) -> str | None:
    """A safe FTS5 MATCH string from `query`: unicode word tokens, each QUOTED as a phrase and
    implicitly ANDed, so no query text can inject an FTS5 operator. `None` = match-all (an empty
    query, or one with no usable tokens) — parity with the mock/folder "empty = whole corpus"."""
    tokens = _WORD_RE.findall(query.lower())
    if not tokens:
        return None
    return " ".join(f'"{token}"' for token in tokens)


def query_facts(facts: Sequence[Fact], query: str, budget: int) -> tuple[Fact, ...]:
    """FTS5-query `facts` deterministically, returning at most `budget` facts.

    The projection is BUILT IN-MEMORY from `facts` (the sealed slice is the truth — this is the
    "rebuildable from the log" projection, always rebuilt). Non-empty query → an FTS5 term-AND
    MATCH ranked by `bm25(rank)`, ties broken by the stable fact id, LIMIT `budget`. Empty query →
    all facts by stable id, LIMIT `budget`. The explicit `ORDER BY … , sid` makes the same
    slice+query+budget return the same rows in the same order across runs (FTS5's default order is
    unstable) — resolver idempotency. Pure + read-only; no network, no LLM."""
    if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
        raise CacheError(
            f"sources-cache-error: query budget must be a positive integer, got {budget!r}"
        )
    probe_fts5()
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE facts "
            "USING fts5(subject, claim, sid UNINDEXED, payload UNINDEXED, tokenize='unicode61')"
        )
        for fact in facts:
            record = fact_to_record(fact)
            conn.execute(
                "INSERT INTO facts(subject, claim, sid, payload) VALUES (?, ?, ?, ?)",
                (fact.subject, fact.claim, stable_fact_id(record), canonical_json_str(record)),
            )
        match = _fts_match(query)
        if match is None:
            cur = conn.execute(
                "SELECT payload FROM facts ORDER BY sid LIMIT ?", (budget,)
            )
        else:
            cur = conn.execute(
                "SELECT payload FROM facts WHERE facts MATCH ? ORDER BY rank, sid LIMIT ?",
                (match, budget),
            )
        return tuple(fact_from_record(json.loads(payload)) for (payload,) in cur.fetchall())
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The acquire/ground mutex — a thin, reusable wrapper over the §22.3 lease (claims.py).
# ---------------------------------------------------------------------------


def namespace_lease_id(namespace: str) -> str:
    """The §22.3 claim key for a cache namespace's acquire/ground mutex: a `mint_run_id`
    `r-<hex16>` over a namespace-derived seed. A run-family id is a NON-artifact id, so it can
    NEVER route through `output_path`/`is_done` (§22.7) — the lease can never be mistaken for an
    output. Deterministic: one namespace ⇒ one stable lease id."""
    return mint_run_id({"sources-cache-namespace-lease": _require_namespace(namespace)})


@dataclass(frozen=True)
class CacheNamespaceLock:
    """Per-namespace-cache mutual exclusion (§22.3), so a future acquire (P2/P3) sealing+publishing
    a slice can't tear a concurrent HEAD-mode read. A THIN wrapper over `claims.ClaimRegistry` — it
    hand-rolls no locking; it only derives the namespace lease id and delegates acquire/release.

    P1 ships no acquire body, so nothing takes this lock in production yet; it is the primitive the
    acquire WILL take, built + unit-tested here (reads of an immutable sealed slice never need it —
    only the mutable HEAD advance does)."""

    registry: ClaimRegistry
    namespace: str

    def lease_id(self) -> str:
        """This namespace's stable §22.3 claim key (`namespace_lease_id`)."""
        return namespace_lease_id(self.namespace)

    def acquire(self) -> AcquireOutcome:
        """Take the namespace lease (§22.3 acquire) — never blocks; codes per §22.6."""
        return self.registry.acquire(self.lease_id())

    def release(self) -> ReleaseOutcome:
        """Holder-checked release of the namespace lease (§22.3; B4-4(b))."""
        return self.registry.release(self.lease_id())
