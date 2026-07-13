"""Step-36 tests: the content-free telemetry + presence-lease registry + ops defaults.

Covers:
- **opdefaults (§22.8/§27.4):** the conservative G2 seed VALUES + the invariants BETWEEN them
  (wrapper timeout STRICTLY < lease TTL; the per-workspace sub-limit sits BENEATH the instance
  cap; the lease TTL agrees with `claims.DEFAULT_LEASE_TTL_SECONDS`), and the one-constant-per-
  line micro-edit surface step 38 finalizes.
- **telemetry content-free BY CONSTRUCTION, proven by grep (§22.5/§24):** the emitted JSONL
  carries ZERO ids (`a-`/`f-`), ZERO workspace identifiers, ZERO content — only counts/timings
  and the `forced_reconciles` rollup; a field/value that could carry content is REFUSED, not
  silently dropped; a DISABLED log writes nothing.
- **the presence-lease registry (§22.5):** live-count = in-flight concurrency; SELF-HEALING (a
  dead worker's lease self-expires); content-free (random token filenames, timing-only bodies).
- **recommended_width (§22.5, PC11):** an ADVISORY from the recent window, never above the cap,
  never auto-applied.

No `live` marker: pure in-process filesystem + clock injection.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pipeline import opdefaults, telemetry
from pipeline.claims import DEFAULT_LEASE_TTL_SECONDS

#: An id/workspace-shaped string must NEVER appear in the emitted telemetry (the grep proof).
_ID_SHAPE = re.compile(r"\b[af]-[0-9a-f]{12,16}\b")


class ManualClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# opdefaults: the conservative G2 seeds + the between-constant invariants.
# ---------------------------------------------------------------------------


class TestOpDefaults:
    def test_the_g2_preliminary_seed_values(self):
        assert opdefaults.MAX_PARALLEL_SESSIONS == 3
        assert opdefaults.MAX_PARALLEL_PER_WORKSPACE == 2
        assert opdefaults.LEASE_TTL_SECONDS == 30 * 60
        assert opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS == 20 * 60
        assert opdefaults.TELEMETRY_ENABLED_DEFAULT is True

    def test_wrapper_timeout_is_strictly_below_the_lease_ttl(self):
        # timeout < TTL ⇒ an expired lease implies a DEAD process (§22.8): a live process would
        # have been killed by its own hard timeout before its lease could lapse.
        assert opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS < opdefaults.LEASE_TTL_SECONDS

    def test_per_workspace_sub_limit_sits_beneath_the_instance_cap(self):
        assert opdefaults.MAX_PARALLEL_PER_WORKSPACE <= opdefaults.MAX_PARALLEL_SESSIONS

    def test_lease_ttl_agrees_with_the_claims_default(self):
        # opdefaults is the ops source of record that WIRES the claims lease TTL (§22.3).
        assert opdefaults.LEASE_TTL_SECONDS == DEFAULT_LEASE_TTL_SECONDS

    def test_module_is_a_clean_constants_surface_no_logic(self):
        # A one-constant-per-line micro-edit surface for step 38: every public name is a plain
        # int/bool, no callables, no classes.
        for name in opdefaults.__all__:
            value = getattr(opdefaults, name)
            assert isinstance(value, int | bool), name


# ---------------------------------------------------------------------------
# Telemetry: content-free BY CONSTRUCTION, proven by grep (§22.5/§24).
# ---------------------------------------------------------------------------


class TestTelemetryContentFree:
    def _log(self, tmp_path: Path, **kw) -> telemetry.TelemetryLog:
        return telemetry.TelemetryLog(tmp_path / "ops" / "telemetry.jsonl", **kw)

    def test_emitted_jsonl_carries_zero_ids_workspace_or_content(self, tmp_path):
        log = self._log(tmp_path, clock=ManualClock())
        log.record_interval(
            interval_seconds=60, started=5, completed=4, peak_inflight=3,
            claims_ok=4, claims_held=1, leases_expired_redriven=1, collisions_averted=2,
            forced_reconciles=7,
        )
        log.record_backpressure(observed_inflight=3)
        text = log.path.read_bytes().decode("utf-8")
        # THE GREP PROOF: no artifact/folio/deliverable id anywhere in the emitted bytes.
        assert not _ID_SHAPE.search(text)
        # Every record: only closed content-free fields, event ∈ the enum, values numeric.
        for line in text.splitlines():
            record = json.loads(line)
            assert set(record) <= telemetry.TELEMETRY_FIELDS
            assert record["event"] in telemetry.TELEMETRY_EVENTS
            for key, value in record.items():
                if key == "event":
                    continue
                assert isinstance(value, int | float) and not isinstance(value, bool), key

    def test_forced_reconciles_counter_is_recorded_as_a_count_only(self, tmp_path):
        log = self._log(tmp_path, clock=ManualClock())
        log.record_interval(
            interval_seconds=60, started=0, completed=0, peak_inflight=0, forced_reconciles=42
        )
        (record,) = log.read_records()
        assert record["forced_reconciles"] == 42  # §24 PC11c: count only, no ids

    def test_a_field_that_could_carry_content_is_refused(self, tmp_path):
        log = self._log(tmp_path)
        # An unknown field (a workspace/id name) — structurally impossible to emit.
        with pytest.raises(telemetry.TelemetryError):
            log.record("interval", workspace="testws")
        with pytest.raises(telemetry.TelemetryError):
            log.record("interval", artifact_id="a-9f3c07d21b44e8aa")
        # A KNOWN field with a non-numeric (id-shaped) value — likewise refused.
        with pytest.raises(telemetry.TelemetryError):
            log.record("interval", started="a-9f3c07d21b44e8aa")
        # An unknown event label — refused.
        with pytest.raises(telemetry.TelemetryError):
            log.record("secrets")
        assert not log.path.exists()  # nothing leaked to disk on any refusal

    def test_a_disabled_log_writes_nothing(self, tmp_path):
        log = self._log(tmp_path, enabled=False)
        assert log.record_interval(
            interval_seconds=1, started=1, completed=1, peak_inflight=1
        ) is False
        assert log.record_backpressure(observed_inflight=2) is False
        assert not log.path.exists()  # disable-able (§22.5): capture off ⇒ zero bytes

    def test_default_enabled_is_the_ops_default(self, tmp_path):
        log = telemetry.TelemetryLog(tmp_path / "t.jsonl")
        assert log.enabled is opdefaults.TELEMETRY_ENABLED_DEFAULT


# ---------------------------------------------------------------------------
# The presence-lease registry (§22.5): self-healing live-count, content-free.
# ---------------------------------------------------------------------------


class TestPresenceRegistry:
    def _reg(self, tmp_path, clock) -> telemetry.PresenceRegistry:
        return telemetry.PresenceRegistry(
            tmp_path / "ops" / "presence", ttl_seconds=60.0, clock=clock
        )

    def test_live_count_tracks_in_flight_sessions(self, tmp_path):
        clock = ManualClock()
        reg = self._reg(tmp_path, clock)
        assert reg.live_count() == 0
        a = reg.register()
        b = reg.register()
        assert a.token != b.token  # distinct opaque tokens (content-free)
        assert reg.live_count() == 2
        reg.release(a.token)
        assert reg.live_count() == 1

    def test_a_dead_workers_lease_self_expires_from_the_count(self, tmp_path):
        clock = ManualClock()
        reg = self._reg(tmp_path, clock)
        reg.register()  # a worker that then dies without releasing
        assert reg.live_count() == 1
        clock.advance(61.0)  # past the TTL
        assert reg.live_count() == 0  # self-healing: the lease is simply not counted
        # a heartbeat/refresh brings a live worker back into the count.
        lease = reg.register()
        assert reg.live_count() == 1
        clock.advance(30.0)
        reg.refresh(lease.token)
        clock.advance(40.0)  # 70s since register, but only 40s since refresh (< TTL)
        assert reg.live_count() == 1

    def test_presence_data_is_content_free(self, tmp_path):
        clock = ManualClock()
        reg = self._reg(tmp_path, clock)
        reg.register()
        presence_dir = tmp_path / "ops" / "presence"
        for entry in presence_dir.iterdir():
            # filename: an opaque random token, never a workspace name or an id.
            assert not _ID_SHAPE.search(entry.name)
            assert re.fullmatch(r"p\d+-[0-9a-f]{32}", entry.name)
            # body: a single lease_expiry timing, nothing else.
            body = json.loads(entry.read_bytes())
            assert set(body) == {"lease_expiry"}
            assert isinstance(body["lease_expiry"], int | float)


# ---------------------------------------------------------------------------
# recommended_width (§22.5, PC11): ADVISORY, never above the cap, never auto-applied.
# ---------------------------------------------------------------------------


class TestRecommendedWidth:
    def _log(self, tmp_path, clock) -> telemetry.TelemetryLog:
        return telemetry.TelemetryLog(tmp_path / "ops" / "telemetry.jsonl", clock=clock)

    def test_no_backpressure_recommends_the_full_cap(self, tmp_path):
        advisory = telemetry.recommend_width(self._log(tmp_path, ManualClock()), cap=5)
        assert advisory.recommended_width == 5
        assert advisory.below_cap is False

    def test_backpressure_recommends_below_the_triggering_inflight(self, tmp_path):
        clock = ManualClock()
        log = self._log(tmp_path, clock)
        log.record_backpressure(observed_inflight=3)
        advisory = telemetry.recommend_width(log, cap=5, now=clock.now)
        assert advisory.recommended_width == 2  # strictly below the inflight that pushed back
        assert advisory.below_cap is True

    def test_recommendation_never_exceeds_the_cap(self, tmp_path):
        clock = ManualClock()
        log = self._log(tmp_path, clock)
        log.record_backpressure(observed_inflight=10)  # backpressure ABOVE our cap
        advisory = telemetry.recommend_width(log, cap=3, now=clock.now)
        assert advisory.recommended_width == 3  # our cap is fine; recommend it, not above
        assert advisory.below_cap is False

    def test_backpressure_outside_the_window_is_ignored(self, tmp_path):
        clock = ManualClock(start=1000.0)
        log = self._log(tmp_path, clock)
        log.record_backpressure(observed_inflight=2)  # stamped ts=1000
        advisory = telemetry.recommend_width(log, cap=5, window_seconds=100, now=2000.0)
        assert advisory.recommended_width == 5  # the old onset fell outside the window
        assert advisory.below_cap is False
