"""Step-20 tests: the §22.3 claim/lease registry — acquire → skip → steal → release.

Plan step-20 acceptance under test here: claim steal only AFTER lease expiry, with
holder-compare semantics; the stolen-from worker's release is a NO-OP (`claim-held`,
B4-4(b)); filename = the claimed id = the lock, no extension (§13.3); the 8-process claim
race mirrors the gate-1 probe (one winner, seven clean losers); the clock is injectable —
lease decisions follow the INJECTED clock even when it contradicts wall time; `claim(id)`
takes only claim-registry handles (§22.7 — asserted by API shape and import lint).
"""

import ast
import inspect
import json
import multiprocessing
import os
import time
from pathlib import Path

import pytest

import pipeline.claims as claims_module
from pipeline.claims import (
    DEFAULT_LEASE_TTL_SECONDS,
    AcquireOutcome,
    ClaimError,
    ClaimRecord,
    ClaimRegistry,
    ReleaseOutcome,
)
from pipeline.ids import IdError
from pipeline.store import WorkspaceStore

# The §7.4 literal examples, verbatim. §22.3: fitted-id is ALSO a claim key — exercised
# throughout as the primary claimed id.
ART = "a-9f3c07d21b44e8aa"
FIT = "a-9f3c07d21b44e8aa.linkedin.en"
DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain"

_SPAWN = multiprocessing.get_context("spawn")


class ManualClock:
    """An injected epoch-seconds clock — the test owns time (no ambient now())."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def claims_dir(tmp_path):
    return tmp_path / "ws" / "claims"


@pytest.fixture()
def clock():
    return ManualClock()


def registry(claims_dir, holder, clock, ttl=DEFAULT_LEASE_TTL_SECONDS):
    return ClaimRegistry(claims_dir, holder=holder, ttl_seconds=ttl, clock=clock)


# ---------------------------------------------------------------------------
# Acquisition (§22.3): free → ok; live → claim-held; expired → steal.
# ---------------------------------------------------------------------------


class TestAcquire:
    def test_free_id_acquires_with_ok(self, claims_dir, clock):
        reg = registry(claims_dir, "worker-a", clock)
        out = reg.acquire(FIT)
        assert out == AcquireOutcome(
            code="ok", acquired=True, holder="worker-a", lease_expiry=clock.now + 1800.0
        )

    def test_claim_file_is_one_json_object_filename_is_the_id(self, claims_dir, clock):
        # §13.3: one JSON object per file; filename = the claimed id = the lock.
        reg = registry(claims_dir, "worker-a", clock)
        reg.acquire(FIT)
        claim_file = claims_dir / FIT
        assert claim_file.is_file()
        assert claim_file.name == FIT  # exactly, no extension (§7.4 filename scope)
        record = json.loads(claim_file.read_bytes())
        assert record == {"holder": "worker-a", "lease_expiry": clock.now + 1800.0}

    def test_live_lease_skips_with_claim_held(self, claims_dir, clock):
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        clock.advance(1799.0)  # still inside the lease
        out = registry(claims_dir, "worker-b", clock).acquire(FIT)
        assert out == AcquireOutcome(
            code="claim-held",
            acquired=False,
            holder="worker-a",
            lease_expiry=1_000_000.0 + 1800.0,
        )

    def test_same_holder_reacquire_is_also_claim_held(self, claims_dir, clock):
        # §22.3 has no re-entrancy: a live lease is a live lease, whoever asks.
        reg = registry(claims_dir, "worker-a", clock)
        reg.acquire(FIT)
        out = reg.acquire(FIT)
        assert out.code == "claim-held"
        assert out.acquired is False
        assert out.holder == "worker-a"

    def test_expired_lease_is_stolen_with_redrive(self, claims_dir, clock):
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        clock.advance(1800.0)  # clock() == lease_expiry → no longer live
        out = registry(claims_dir, "worker-b", clock).acquire(FIT)
        assert out.code == "lease-expired-redrive"
        assert out.acquired is True
        assert out.holder == "worker-b"
        assert out.lease_expiry == clock.now + 1800.0
        # The steal is read-check-replace: the claim file now carries the stealer.
        record = json.loads((claims_dir / FIT).read_bytes())
        assert record["holder"] == "worker-b"

    def test_steal_only_after_expiry_never_before(self, claims_dir, clock):
        # Plan acceptance: claim steal only after lease expiry.
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        reg_b = registry(claims_dir, "worker-b", clock)
        clock.advance(1799.0)
        assert reg_b.acquire(FIT).code == "claim-held"
        clock.advance(1.0)  # exactly at lease_expiry: no longer live
        assert reg_b.acquire(FIT).code == "lease-expired-redrive"

    def test_distinct_ids_are_independent_locks(self, claims_dir, clock):
        reg = registry(claims_dir, "worker-a", clock)
        assert reg.acquire(ART).code == "ok"
        assert reg.acquire(FIT).code == "ok"
        assert reg.acquire(DEL).code == "ok"

    def test_ttl_is_injectable(self, claims_dir, clock):
        reg = registry(claims_dir, "worker-a", clock, ttl=60.0)
        out = reg.acquire(FIT)
        assert out.lease_expiry == clock.now + 60.0

    def test_invalid_id_is_refused(self, claims_dir, clock):
        with pytest.raises(IdError):
            registry(claims_dir, "worker-a", clock).acquire("not-an-id")


# ---------------------------------------------------------------------------
# Holder-checked release (§22.3 S6; B4-4(b); G1 P4 transcript).
# ---------------------------------------------------------------------------


class TestRelease:
    def test_holder_releases_own_claim(self, claims_dir, clock):
        reg = registry(claims_dir, "worker-a", clock)
        reg.acquire(FIT)
        out = reg.release(FIT)
        assert out == ReleaseOutcome(code="ok", released=True, holder="worker-a")
        assert not (claims_dir / FIT).exists()

    def test_non_holder_release_is_a_noop(self, claims_dir, clock):
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        out = registry(claims_dir, "worker-b", clock).release(FIT)
        assert out == ReleaseOutcome(code="claim-held", released=False, holder="worker-a")
        assert (claims_dir / FIT).exists()  # the live critical section stays locked

    def test_release_with_no_claim_is_already_released(self, claims_dir, clock):
        out = registry(claims_dir, "worker-a", clock).release(FIT)
        assert out == ReleaseOutcome(code="already-released", released=False, holder=None)


# ---------------------------------------------------------------------------
# The full B4-4 lifecycle: acquire → live-skip → expire → steal → releases.
# ---------------------------------------------------------------------------


class TestStealLifecycle:
    def test_full_lifecycle_including_stolen_holder_noop(self, claims_dir, clock):
        reg_a = registry(claims_dir, "worker-a", clock)
        reg_b = registry(claims_dir, "worker-b", clock)

        # 1. A acquires.
        assert reg_a.acquire(FIT).code == "ok"
        # 2. B skips while the lease is live.
        clock.advance(100.0)
        assert reg_b.acquire(FIT).code == "claim-held"
        # 3. The lease expires (A is slow, not dead — the classic hazard).
        clock.advance(1800.0)
        # 4. B steals via read-check-replace.
        assert reg_b.acquire(FIT).code == "lease-expired-redrive"
        # 5. A's late release re-reads at release time, sees B, and NO-OPS (B4-4(b)):
        #    the stolen-from worker can never unlock the stealer's live critical section.
        late = reg_a.release(FIT)
        assert late == ReleaseOutcome(code="claim-held", released=False, holder="worker-b")
        assert json.loads((claims_dir / FIT).read_bytes())["holder"] == "worker-b"
        # 6. The stealer's own holder-checked release succeeds.
        assert reg_b.release(FIT) == ReleaseOutcome(code="ok", released=True, holder="worker-b")
        assert not (claims_dir / FIT).exists()
        # 7. A's even-later release finds nothing — benign no-op.
        assert reg_a.release(FIT).code == "already-released"

    def test_double_steal_is_a_cost_leak_never_a_wedge(self, claims_dir, clock):
        # §22.3: the steal is deliberately not atomic — two stealers may both redrive;
        # the no-replace COMMIT (store plane) admits exactly one winner per id.
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        clock.advance(3600.0)
        out_b = registry(claims_dir, "worker-b", clock).acquire(FIT)
        # worker-c reads a FRESH lease from b — held; only after b's lease could c steal.
        out_c = registry(claims_dir, "worker-c", clock).acquire(FIT)
        assert out_b.code == "lease-expired-redrive"
        assert out_c.code == "claim-held"
        assert out_c.holder == "worker-b"


# ---------------------------------------------------------------------------
# The injectable clock: lease logic follows the INJECTED time, never wall time.
# ---------------------------------------------------------------------------


class TestInjectableClock:
    def test_lease_decisions_ignore_wall_time_entirely(self, claims_dir):
        # The injected clock says the lease is LIVE even though its epoch values are
        # decades before real wall time — if any ambient now() leaked into the lease
        # logic, this claim would read as long-expired and be stolen.
        clock = ManualClock(start=1_000.0)
        registry(claims_dir, "worker-a", clock).acquire(FIT)
        assert time.time() > 1_000.0 + 1800.0  # wall time would call this expired
        out = registry(claims_dir, "worker-b", clock).acquire(FIT)
        assert out.code == "claim-held"  # the injected clock rules: still live

    def test_default_ttl_is_the_g2_seed(self):
        assert DEFAULT_LEASE_TTL_SECONDS == 1800.0  # 30 min (step-06 sheet item 6)

    def test_registry_validates_holder_and_ttl(self, claims_dir, clock):
        with pytest.raises(ClaimError):
            ClaimRegistry(claims_dir, holder="", clock=clock)
        with pytest.raises(ClaimError):
            ClaimRegistry(claims_dir, holder="w", ttl_seconds=0.0, clock=clock)
        with pytest.raises(ClaimError):
            ClaimRegistry(claims_dir, holder="w", ttl_seconds=float("inf"), clock=clock)


# ---------------------------------------------------------------------------
# The nascent/unreadable-claim posture (implicit mtime-anchored lease: held for
# one TTL, then stealable — §22.4 PC7; release stays conservative, B4-4(b)).
# ---------------------------------------------------------------------------


class TestUnreadableClaims:
    @pytest.mark.parametrize("raw", [b"", b'{"holder": ', b"[]", b'{"holder": "w"}'])
    def test_unreadable_claim_younger_than_ttl_is_held(self, claims_dir, clock, raw):
        # (a) Inside the implicit mtime-anchored TTL: held, bytes untouched. mtime is
        # set via os.utime to keep the injected manual clock coherent (module-doc seam).
        claims_dir.mkdir(parents=True)
        path = claims_dir / FIT
        path.write_bytes(raw)
        os.utime(path, (clock.now, clock.now))  # implicit lease anchored "now"
        clock.advance(DEFAULT_LEASE_TTL_SECONDS - 1.0)  # still inside the implicit TTL
        out = registry(claims_dir, "worker-b", clock).acquire(FIT)
        assert out == AcquireOutcome(
            code="claim-held", acquired=False, holder=None, lease_expiry=None
        )
        assert path.read_bytes() == raw  # untouched

    @pytest.mark.parametrize("raw", [b"", b'{"holder": ', b"[]", b'{"holder": "w"}'])
    def test_unreadable_claim_aged_past_ttl_is_stolen(self, claims_dir, clock, raw):
        # (b) Past the implicit expiry (mtime + ttl): the normal read-check-replace
        # steal applies — §22.4 PC7's "dead worker's lease expires → safe re-drive"
        # now holds at the create→record-write crash point too (reviewer probe B6).
        claims_dir.mkdir(parents=True)
        path = claims_dir / FIT
        path.write_bytes(raw)
        aged = clock.now - DEFAULT_LEASE_TTL_SECONDS - 1.0
        os.utime(path, (aged, aged))  # implicit lease anchored one TTL + 1s ago
        out = registry(claims_dir, "worker-b", clock).acquire(FIT)
        assert out == AcquireOutcome(
            code="lease-expired-redrive",
            acquired=True,
            holder="worker-b",
            lease_expiry=clock.now + DEFAULT_LEASE_TTL_SECONDS,
        )
        record = json.loads(path.read_bytes())  # now a valid claim record
        assert record == {"holder": "worker-b", "lease_expiry": clock.now + 1800.0}

    def test_unreadable_claim_is_never_released_before_or_after_expiry(self, claims_dir, clock):
        # (c) Only acquire widens past the implicit expiry; release stays conservative
        # (B4-4(b)): an unreadable claim can never be proven ours → never unlinked.
        claims_dir.mkdir(parents=True)
        path = claims_dir / FIT
        path.write_bytes(b"")
        os.utime(path, (clock.now, clock.now))
        reg = registry(claims_dir, "worker-a", clock)
        assert reg.release(FIT).code == "claim-held"  # before the implicit expiry
        clock.advance(DEFAULT_LEASE_TTL_SECONDS + 10.0)
        assert reg.release(FIT).code == "claim-held"  # after it — release never widens
        assert path.exists()

    def test_peek_returns_none_for_unreadable(self, claims_dir, clock):
        # (d) peek stays conservative: unreadable → None, no side effects.
        claims_dir.mkdir(parents=True)
        (claims_dir / FIT).write_bytes(b"")
        assert registry(claims_dir, "worker-a", clock).peek(FIT) is None
        assert (claims_dir / FIT).read_bytes() == b""  # untouched

    def test_peek_reads_without_side_effects(self, claims_dir, clock):
        reg = registry(claims_dir, "worker-a", clock)
        assert reg.peek(FIT) is None
        reg.acquire(FIT)
        record = reg.peek(FIT)
        assert record == ClaimRecord(holder="worker-a", lease_expiry=clock.now + 1800.0)
        assert (claims_dir / FIT).exists()  # peek changed nothing


# ---------------------------------------------------------------------------
# §22.7 scoping: claim(id) takes only claim-registry handles; no SSOT anywhere.
# ---------------------------------------------------------------------------


class TestInvCorrectnessScoping:
    def test_acquire_and_release_signatures_have_no_ssot_handle(self):
        for method in (ClaimRegistry.acquire, ClaimRegistry.release):
            params = list(inspect.signature(method).parameters)
            assert params == ["self", "id_str"]
            assert not any("ssot" in p.lower() for p in params)

    def test_registry_holds_only_the_claims_dir_handle(self):
        fields = set(ClaimRegistry.__dataclass_fields__)
        assert fields == {"claims_dir", "holder", "ttl_seconds", "clock"}
        assert not any("ssot" in f.lower() for f in fields)

    def test_claims_module_imports_no_ssot_code(self):
        tree = ast.parse(Path(claims_module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            assert not any("ssot" in name.lower() for name in names), names


# ---------------------------------------------------------------------------
# Integration with the WorkspaceStore claims home (§23).
# ---------------------------------------------------------------------------


class TestStoreIntegration:
    def test_registry_over_the_workspace_claims_dir(self, tmp_path, clock):
        ws = WorkspaceStore(tmp_path / "ws")
        reg = ClaimRegistry(ws.claims_dir, holder="worker-a", clock=clock)
        out = reg.acquire(FIT)
        assert out.code == "ok"
        assert ws.claim_path(FIT).is_file()  # same file the store's path API names
        assert reg.release(FIT).code == "ok"


# ---------------------------------------------------------------------------
# The 8-process claim race on ONE id (G1 P6 claim round as a test).
# ---------------------------------------------------------------------------


def _claim_racer(claims_dir_str: str, wid: int, barrier, queue) -> None:
    from pipeline.claims import ClaimRegistry

    try:
        reg = ClaimRegistry(Path(claims_dir_str), holder=f"w{wid}")  # live-lease race
        barrier.wait(timeout=60)
        out = reg.acquire("a-9f3c07d21b44e8aa.linkedin.en")
        queue.put((wid, out.code))
    except Exception as exc:  # noqa: BLE001 — any other outcome is a dirty failure
        queue.put((wid, f"ERROR:{type(exc).__name__}:{exc}"))


class TestClaimRace:
    def test_eight_process_race_one_winner_seven_clean_losers(self, claims_dir):
        n_procs = 8
        barrier = _SPAWN.Barrier(n_procs)
        queue = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(target=_claim_racer, args=(str(claims_dir), wid, barrier, queue))
            for wid in range(n_procs)
        ]
        for p in procs:
            p.start()
        results = [queue.get(timeout=120) for _ in range(n_procs)]
        for p in procs:
            p.join(timeout=60)
        winners = [wid for wid, code in results if code == "ok"]
        losers = [wid for wid, code in results if code == "claim-held"]
        errors = [(wid, code) for wid, code in results if str(code).startswith("ERROR")]
        assert errors == []
        assert len(winners) == 1  # §22.3: create-if-absent admits exactly one
        assert len(losers) == n_procs - 1
        record = json.loads((claims_dir / FIT).read_bytes())
        assert record["holder"] == f"w{winners[0]}"  # the winner's record, intact
