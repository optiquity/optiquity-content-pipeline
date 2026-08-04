"""The sources subsystem P1: the sealed slice store + the cache-reader adapter + the mutex.

Fixtures-only (P1 has NO acquisition body): every slice is sealed by a TEST FIXTURE, never a
fetcher. Content is SYNTHETIC-GENERIC (CLAUDE.md rule 4 — invented widget/gadget claims,
example.test anchors, no client content). Everything runs under `tmp_path`; the real
`users/` tree is never touched.

Coverage map (the P1 acceptance set):
  - CF-1        pin_commit(conn) == ground(conn, q).built_at_commit, stable across calls (both
                the pinned-digest form and the HEAD form).
  - N2         a pinned ground() is immune to a mid-session seal AND publish of a NEW slice.
  - collision  different fact-sets → different digests; identical content (any order) → identical.
  - FTS5       the availability probe fails LOUD when FTS5 is absent (simulated).
  - determinism  same slice+query+budget → same rows, same order, across runs/instances.
  - dedup      duplicate stable-ids collapse to one.
  - mutex      the §22.3 lease primitive the future acquire will take (mutual exclusion).
  - wiring     the adapter registers in default_adapters() + the resolver binds an instance.
"""

from __future__ import annotations

import datetime

import pytest

from pipeline.adapters import default_adapters
from pipeline.adapters.base import (
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    TIER_INFERRED,
    Anchor,
    Fact,
)
from pipeline.claims import ClaimRegistry
from pipeline.grounding import SourceInstance, ground_item
from pipeline.ids import parse_id
from pipeline.m3 import resolve_selection
from pipeline.sources import cache
from pipeline.sources.cache import (
    CacheError,
    CacheNamespaceLock,
    FtsUnavailableError,
    namespace_dir,
    namespace_lease_id,
    probe_fts5,
    publish_head,
    read_head,
    read_slice,
    seal_slice,
    slice_digest,
    slice_path,
)
from pipeline.sources.reader import CacheReaderAdapter
from pipeline.store import WorkspaceStore

NOW = datetime.date(2026, 7, 12)


def sample_facts() -> list[Fact]:
    """A synthetic-generic fact set (rule 4): two 'widget' facts + one 'gadget' fact."""
    return [
        Fact(
            subject="widget-service.timeout",
            claim="The widget service default timeout is 30 seconds.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("file-line", "src/widget/config.py:42"),),
            as_of=datetime.date(2026, 5, 1),
        ),
        Fact(
            subject="gadget-cache.capacity",
            claim="The gadget cache holds 512 entries.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("sha", "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"),),
            as_of=datetime.date(2026, 4, 20),
        ),
        Fact(
            subject="widget-service.retries",
            claim="The widget client retries failed calls three times.",
            tier=TIER_INFERRED,
            anchors=(),  # EXTRACTED-vs-anchorless independence rides through the store intact
            as_of=None,
        ),
    ]


def other_facts() -> list[Fact]:
    """A DIFFERENT fact set (for the N2 mid-session slice + collision cases)."""
    return [
        Fact(
            subject="widget-service.protocol",
            claim="The widget service speaks the example wire protocol v2.",
            tier=TIER_AMBIGUOUS,
            anchors=(Anchor("url-fragment", "https://example.test/spec#protocol"),),
            as_of=datetime.date(2026, 6, 1),
        ),
    ]


def make_ns(tmp_path, name: str = "x-widget") -> object:
    """A bare namespace directory under tmp_path (the reader binds a namespace by path)."""
    ns_dir = tmp_path / name
    ns_dir.mkdir(parents=True, exist_ok=True)
    return ns_dir


# ---------------------------------------------------------------------------
# CF-1: pin_commit == ground().built_at_commit, stable across calls (both selector forms).
# ---------------------------------------------------------------------------


class TestCF1:
    def test_pinned_form_pin_equals_ground_and_stable(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        conn = {"path": str(ns_dir), "slice": digest}
        adapter = CacheReaderAdapter()

        pin = adapter.pin_commit(conn)
        result = adapter.ground(connection=conn, query="widget")
        assert pin == digest
        assert result.built_at_commit == digest
        # stable across repeated calls (compute/seal once, read many)
        assert adapter.pin_commit(conn) == pin
        assert adapter.ground(connection=conn, query="widget").built_at_commit == digest

    def test_head_form_pin_equals_ground(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest)
        conn = {"path": str(ns_dir)}  # no `slice` -> resolve the published HEAD
        adapter = CacheReaderAdapter()

        assert adapter.pin_commit(conn) == digest
        assert adapter.ground(connection=conn, query="widget").built_at_commit == digest

    def test_empty_namespace_pins_and_grounds_commitless(self, tmp_path):
        # Nothing sealed/published: pin_commit and ground BOTH report None (CF-1 holds for the
        # commitless posture) and ground is empty — the resolver's SM1 owns the empty outcome.
        ns_dir = make_ns(tmp_path, "x-empty")
        conn = {"path": str(ns_dir)}
        adapter = CacheReaderAdapter()
        assert adapter.pin_commit(conn) is None
        result = adapter.ground(connection=conn, query="widget")
        assert result.built_at_commit is None
        assert result.facts == ()


# ---------------------------------------------------------------------------
# N2: a pinned ground() is immune to a mid-session seal AND publish of a NEW slice.
# ---------------------------------------------------------------------------


class TestN2:
    def test_pinned_ground_immune_to_midsession_seal_and_publish(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        adapter = CacheReaderAdapter()

        digest_a = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest_a)
        conn = {"path": str(ns_dir), "slice": digest_a}  # PIN the plan-time slice
        pin_before = adapter.pin_commit(conn)
        ground_before = adapter.ground(connection=conn, query="widget")

        # An OUT-OF-BAND mid-session acquire: seal a NEW slice AND advance HEAD to it.
        digest_b = seal_slice(ns_dir, other_facts())
        assert digest_b != digest_a
        publish_head(ns_dir, digest_b)
        assert read_head(ns_dir) == digest_b  # HEAD really moved

        pin_after = adapter.pin_commit(conn)
        ground_after = adapter.ground(connection=conn, query="widget")

        # The pinned selection is UNSHIFTED: same digest, same rows — mechanism (c) + immutability.
        assert pin_after == pin_before == digest_a
        assert ground_after.built_at_commit == ground_before.built_at_commit == digest_a
        assert ground_after.facts == ground_before.facts

    def test_head_form_tracks_the_latest_publish_documented_boundary(self, tmp_path):
        # The convenience HEAD form is NOT N2-immune to a publish (documented): it follows the
        # latest published slice. This pins the boundary so the pinned form's guarantee is explicit.
        ns_dir = make_ns(tmp_path)
        adapter = CacheReaderAdapter()
        digest_a = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest_a)
        conn = {"path": str(ns_dir)}  # HEAD form
        assert adapter.pin_commit(conn) == digest_a

        digest_b = seal_slice(ns_dir, other_facts())
        publish_head(ns_dir, digest_b)
        assert adapter.pin_commit(conn) == digest_b  # HEAD form followed the publish


# ---------------------------------------------------------------------------
# Collision-proofness: content-addressing is the identity.
# ---------------------------------------------------------------------------


class TestCollisionProof:
    def test_different_sets_differ_identical_content_matches(self):
        d_sample = slice_digest(sample_facts())
        d_other = slice_digest(other_facts())
        assert d_sample != d_other  # different fact-sets → different digests

        # identical content in ANY order → the identical digest (dedup + sort before sealing)
        assert slice_digest(list(reversed(sample_facts()))) == d_sample

    def test_digest_is_a_bare_64_hex_never_none(self):
        digest = slice_digest(sample_facts())
        assert digest is not None
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_reseal_identical_bytes_is_idempotent(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        d1 = seal_slice(ns_dir, sample_facts())
        d2 = seal_slice(ns_dir, list(reversed(sample_facts())))  # same set, reordered
        assert d1 == d2  # idempotent no-op (already-materialized, byte-identical)
        assert slice_path(ns_dir, d1).exists()

    def test_same_digest_different_bytes_refused_loud(self, tmp_path):
        # A forged collision (same digest name, different bytes) is refused, never overwritten.
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        forged = slice_path(ns_dir, digest)
        forged.write_bytes(b'{"version":1,"facts":[]}')  # corrupt the sealed file in place
        with pytest.raises(CacheError):
            seal_slice(ns_dir, sample_facts())


# ---------------------------------------------------------------------------
# FTS5 availability probe: fail LOUD when absent (simulated).
# ---------------------------------------------------------------------------


class _NoFtsConnection:
    """A SQLite connection whose FTS5 virtual-table create fails, as a build without FTS5 would."""

    def execute(self, sql, *args):
        import sqlite3

        if "fts5" in sql.lower():
            raise sqlite3.OperationalError("no such module: fts5")
        return self

    def close(self):
        pass


class TestFts5Probe:
    def test_probe_passes_on_this_build(self):
        probe_fts5()  # this interpreter's SQLite has FTS5 (verified in the P1 env probe)

    def test_probe_fails_loud_when_fts5_absent(self, monkeypatch):
        monkeypatch.setattr(cache.sqlite3, "connect", lambda *a, **k: _NoFtsConnection())
        with pytest.raises(FtsUnavailableError):
            probe_fts5()

    def test_query_fails_loud_when_fts5_absent(self, monkeypatch):
        monkeypatch.setattr(cache.sqlite3, "connect", lambda *a, **k: _NoFtsConnection())
        with pytest.raises(FtsUnavailableError):
            cache.query_facts(sample_facts(), "widget", budget=10)


# ---------------------------------------------------------------------------
# Determinism: same slice+query+budget → same rows, same order.
# ---------------------------------------------------------------------------


class TestDeterminism:
    def test_query_is_repeatable_across_calls_and_instances(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        conn = {"path": str(ns_dir), "slice": digest}
        r1 = CacheReaderAdapter().ground(connection=conn, query="widget")
        r2 = CacheReaderAdapter().ground(connection=conn, query="widget")
        assert r1.facts == r2.facts
        # the 'widget' query excludes the gadget-only fact (FTS5 term match)
        subjects = {f.subject for f in r1.facts}
        assert subjects == {"widget-service.timeout", "widget-service.retries"}

    def test_budget_caps_deterministically(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        conn = {"path": str(ns_dir), "slice": digest, "budget": 1}
        first = CacheReaderAdapter().ground(connection=conn, query="widget").facts
        second = CacheReaderAdapter().ground(connection=conn, query="widget").facts
        assert len(first) == 1
        assert first == second  # same single row on every run (ORDER BY rank, sid)

    def test_empty_query_returns_all_in_stable_order(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        conn = {"path": str(ns_dir), "slice": digest}
        r1 = CacheReaderAdapter().ground(connection=conn, query="").facts
        r2 = CacheReaderAdapter().ground(connection=conn, query="").facts
        assert len(r1) == 3  # empty query = whole slice
        assert r1 == r2


# ---------------------------------------------------------------------------
# Dedup: duplicate stable-ids collapse.
# ---------------------------------------------------------------------------


class TestDedup:
    def test_duplicate_facts_collapse(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        dup = sample_facts()[0]
        other = sample_facts()[1]
        digest = seal_slice(ns_dir, [dup, dup, other, dup])
        facts = read_slice(ns_dir, digest)
        assert len(facts) == 2  # the three duplicate copies collapsed to one
        # the deduped set is exactly what a two-fact seal would produce
        assert slice_digest([dup, other]) == digest


# ---------------------------------------------------------------------------
# The store round-trip + the read_slice contract.
# ---------------------------------------------------------------------------


class TestStoreRoundTrip:
    def test_seal_then_read_round_trips_every_field(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        loaded = read_slice(ns_dir, digest)
        # a slice is a SET (sorted, deduped): compare as sets of the five preserved fields
        assert {(f.subject, f.claim, f.tier, f.anchors, f.as_of) for f in loaded} == {
            (f.subject, f.claim, f.tier, f.anchors, f.as_of) for f in sample_facts()
        }

    def test_missing_pinned_slice_fails_loud(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        with pytest.raises(CacheError):
            read_slice(ns_dir, "0" * 64)

    def test_bad_digest_refused(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        with pytest.raises(CacheError):
            slice_path(ns_dir, "not-a-digest")

    def test_workspace_store_sources_cache_dir(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        cache_dir = store.sources_cache_dir
        assert cache_dir == store.root / "sources" / "cache"
        assert cache_dir.is_dir()
        # the namespace bridge lands beneath it
        ns_dir = namespace_dir(store, "x-widget")
        assert ns_dir == cache_dir / "x-widget"
        assert ns_dir.is_dir()


# ---------------------------------------------------------------------------
# The acquire/ground mutex — the §22.3 lease primitive the future acquire will take.
# ---------------------------------------------------------------------------


class TestNamespaceMutex:
    def test_mutual_exclusion_and_release(self, tmp_path):
        clock = lambda: 1000.0  # noqa: E731 — a fixed injected clock keeps the lease deterministic
        r1 = ClaimRegistry(tmp_path / "claims", holder="worker-1", clock=clock)
        r2 = ClaimRegistry(tmp_path / "claims", holder="worker-2", clock=clock)
        lock1 = CacheNamespaceLock(r1, "x-widget")
        lock2 = CacheNamespaceLock(r2, "x-widget")

        first = lock1.acquire()
        assert first.acquired and first.code == "ok"
        contended = lock2.acquire()  # same namespace, live lease held by worker-1
        assert not contended.acquired and contended.code == "claim-held"

        released = lock1.release()
        assert released.released and released.code == "ok"
        after = lock2.acquire()  # now free
        assert after.acquired

    def test_distinct_namespaces_do_not_collide(self):
        assert namespace_lease_id("x-widget") != namespace_lease_id("x-gadget")

    def test_lease_id_is_a_run_family_id(self):
        # A run-family id (r-<hex16>) can NEVER route through output_path/is_done (§22.7) — the
        # lease can never masquerade as an output.
        parsed = parse_id(namespace_lease_id("x-widget"))
        assert parsed.family == "run"

    def test_bad_namespace_refused(self):
        with pytest.raises(CacheError):
            namespace_lease_id("../escape")


# ---------------------------------------------------------------------------
# Wiring: the adapter registers + the resolver binds a cache instance.
# ---------------------------------------------------------------------------


class TestWiring:
    def test_cache_adapter_registered_in_default_set(self):
        adapters = default_adapters()
        assert "cache" in adapters
        assert isinstance(adapters["cache"], CacheReaderAdapter)
        assert adapters["cache"].name == "cache"
        assert all(k == v.name for k, v in adapters.items())  # no mislabeling

    def test_resolver_binds_and_grounds_a_cache_instance(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        inst = SourceInstance(
            id="x-cache",
            adapter="cache",
            connection={"path": str(ns_dir), "slice": digest},
        )
        outcome = ground_item(
            item="item-1",
            query="widget",
            pool=[inst],
            selection=resolve_selection(),
            adapters=default_adapters(),
            now=NOW,
        )
        assert outcome.status == "ok"
        assert outcome.facts, "the cache slice must ground through the default adapter set"
        # CF-1 at the resolver seam: the ledger commit is the sealed slice digest.
        assert dict(outcome.commit_map) == {"x-cache": digest}
