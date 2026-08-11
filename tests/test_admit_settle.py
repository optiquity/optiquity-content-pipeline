"""The ADMIT → SETTLE path at the resolver (plan G7): admit-before-spend, settle-in-finally.

Proves run-admission accounting with a FAKE clock + FAKE costs — ZERO real spend. The resolver
ADMITS the ceiling against the bucket + umbrella (a live hold reserves it), and `AdmittedTransport
.settle(actual)` appends the settled ledger line + drops the hold so week-to-date collapses to the
REAL cost. The subscription path carries no hold (settle is a no-op). A crash before settle
self-expires the hold at its full ceiling (the G6 TTL) — never a leaked hold, never a lost cap.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.spend.assignment import (
    SCOPE_ZONE,
    Assignment,
    AssignmentStore,
    ScopeKey,
)
from pipeline.spend.keystore import FileSecretBackend, SecretRef
from pipeline.spend.meter import WeeklyMeter
from pipeline.spend.resolve import NotEntitledError, resolve_transport

WED_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _apikey_setup(tmp_path: Path):
    backend = FileSecretBackend(tmp_path / "secrets")
    ref = SecretRef.parse("anthropic:acme")
    backend.store(ref, "sk-ant-SECRET")
    scope = ScopeKey(SCOPE_ZONE, "dave/work")
    store = AssignmentStore(
        [Assignment(scope, ref, Decimal("500"))], umbrella_cap_usd=Decimal("1000")
    )
    clock = _Clock(WED_NOON)
    meter = WeeklyMeter(root=tmp_path, clock=clock)
    return backend, ref, scope, store, clock, meter


def _resolve(tmp_path, backend, store, meter, **kw):
    return resolve_transport(
        tmp_path, "dave", "work", "acme",
        n_artifacts=kw.get("n_artifacts", 1),
        n_deliverables=kw.get("n_deliverables", 1),
        meter=meter,
        resolver=backend,
        store=store,
        override=kw.get("override"),
    )


# ---------------------------------------------------------------------------------------
# admit reserves the ceiling; settle records the actual + drops the hold
# ---------------------------------------------------------------------------------------


def test_admit_reserves_ceiling_then_settle_records_actual(tmp_path: Path) -> None:
    backend, ref, scope, store, clock, meter = _apikey_setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)
    assert admission.hold is not None
    ceiling = admission.hold.ceiling
    assert ceiling == Decimal("60.00")  # $5 × 12 calls (1 artifact / 1 deliverable)
    # BEFORE settle: week-to-date = the reserved ceiling (settled 0 + one live hold).
    assert meter.bucket_week_to_date(scope, ref) == ceiling
    assert meter.umbrella_week_to_date() == ceiling

    admission.settle(Decimal("3.11"))  # the accumulated ACTUAL cost, far under the ceiling
    # AFTER settle: the hold drops; week-to-date collapses to the REAL spend (bucket + umbrella).
    assert meter.bucket_week_to_date(scope, ref) == Decimal("3.11")
    assert meter.umbrella_week_to_date() == Decimal("3.11")


def test_a_second_admit_sees_the_first_holds_reservation(tmp_path: Path) -> None:
    # settled + ALL LIVE HOLDS (S-3): a second admit sees the first's live hold, so two $60 ceilings
    # against a $500 bucket / $1000 umbrella both fit, and week-to-date = the SUM of the two holds.
    backend, ref, scope, store, clock, meter = _apikey_setup(tmp_path)
    a1 = _resolve(tmp_path, backend, store, meter)
    a2 = _resolve(tmp_path, backend, store, meter)
    assert a1.hold is not None and a2.hold is not None
    assert meter.bucket_week_to_date(scope, ref) == Decimal("120.00")  # 60 + 60 live holds
    a1.settle(Decimal("2"))
    a2.settle(Decimal("4"))
    assert meter.bucket_week_to_date(scope, ref) == Decimal("6")


# ---------------------------------------------------------------------------------------
# subscription: no hold, settle is a no-op (nothing metered)
# ---------------------------------------------------------------------------------------


def test_subscription_admission_has_no_hold_and_settle_is_a_noop(tmp_path: Path) -> None:
    # No key assigned; the entitled user IS dave → the flat-rate subscription (per_call_cap=None).
    store = AssignmentStore(entitled_user="dave")
    clock = _Clock(WED_NOON)
    meter = WeeklyMeter(root=tmp_path, clock=clock)
    admission = resolve_transport(
        tmp_path, "dave", "work", "acme", meter=meter, store=store
    )
    assert admission.plan.mode == "subscription"
    assert admission.plan.per_call_cap is None  # S-1: flat-rate, no truncation
    assert admission.hold is None and admission.meter is None
    admission.settle(Decimal("9.99"))  # a no-op — subscription is not metered here


def test_non_entitled_subscription_is_refused(tmp_path: Path) -> None:
    # A different entitled user → dave is NOT entitled → forced subscription is refused (ToS).
    store = AssignmentStore(entitled_user="erin")
    meter = WeeklyMeter(root=tmp_path, clock=_Clock(WED_NOON))
    with pytest.raises(NotEntitledError):
        resolve_transport(
            tmp_path, "dave", "work", "acme", override="subscription", meter=meter, store=store
        )


# ---------------------------------------------------------------------------------------
# crash before settle: the hold self-expires at its full ceiling (the G6 TTL) — cap re-opens
# ---------------------------------------------------------------------------------------


def test_crash_before_settle_self_expires_the_hold(tmp_path: Path) -> None:
    backend, ref, scope, store, clock, meter = _apikey_setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)  # admitted, then the process "crashes"
    assert admission.hold is not None
    assert meter.bucket_week_to_date(scope, ref) == Decimal("60.00")  # the live hold
    # Advance the clock PAST the hold TTL: the crashed run's hold self-expires + is reclaimed on the
    # next read, so the bucket frees back to zero (nothing was ever settled — no phantom spend).
    clock.now = WED_NOON + meter.hold_ttl_seconds + 1.0
    assert meter.bucket_week_to_date(scope, ref) == Decimal("0")
