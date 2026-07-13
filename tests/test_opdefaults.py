"""Step-38 test: the loaded runtime ops-defaults EQUAL the numbers gate G2 measured (step-37).

Gate G2 (§27.2) CLOSED by running a bounded live telemetry probe (step-37 report) against the
§22.5 telemetry dataset. It CONFIRMED — did not change — the two concurrency numbers that
`pipeline/opdefaults.py` ships:

    MAX_PARALLEL_SESSIONS = 3     (3 concurrent inflight subscription calls, ZERO backpressure)
    LEASE_TTL_SECONDS     = 1800  (30 min; anchored above the 1200 s wrapper timeout)

This module LOCKS THE LOOP: it asserts the loaded runtime defaults are *exactly* what G2
measured, so any future drift from the telemetry-validated finals fails CI. The between-constant
invariants (wrapper timeout < lease TTL; the per-workspace sub-limit ≤ the instance cap; the TTL
mirrors `claims.DEFAULT_LEASE_TTL_SECONDS`) live in `tests/test_telemetry.py` and are NOT
duplicated here — this file adds only the G2-equality lock.

No `live` marker: this reads already-loaded module constants only.
"""

from __future__ import annotations

from pipeline import opdefaults

#: The two numbers gate G2 measured and finalized (step-37 report, §27.2), named as the report's
#: tuple so a drift in `opdefaults` cannot silently drag this expectation along with it.
G2_MEASURED_MAX_PARALLEL_SESSIONS = 3
G2_MEASURED_LEASE_TTL_SECONDS = 1800


class TestG2ValidatedFinals:
    """The loaded runtime defaults are EXACTLY the numbers gate G2 measured (step-37)."""

    def test_max_parallel_sessions_equals_the_g2_measured_ceiling(self):
        # step-37 / §27.2 (G2): 3 concurrent inflight subscription calls sustained with ZERO
        # backpressure (observed peak_inflight=3) ⇒ the telemetry-validated ceiling.
        assert opdefaults.MAX_PARALLEL_SESSIONS == 3

    def test_lease_ttl_equals_the_g2_measured_ttl(self):
        # step-37 / §27.2 (G2): 1800 s (30 min), anchored above the 1200 s wrapper timeout;
        # observed call latency (~8-12 s) sat ~150× under the TTL ⇒ validated, unchanged.
        assert opdefaults.LEASE_TTL_SECONDS == 1800

    def test_the_finals_lock_the_g2_report_dataset(self):
        # Both G2 numbers as a single report tuple: a drift in EITHER value fails CI, keeping the
        # runtime defaults pinned to what step-37 actually measured.
        assert (opdefaults.MAX_PARALLEL_SESSIONS, opdefaults.LEASE_TTL_SECONDS) == (
            G2_MEASURED_MAX_PARALLEL_SESSIONS,
            G2_MEASURED_LEASE_TTL_SECONDS,
        )
