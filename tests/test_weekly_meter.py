"""The weekly spend METER core — admit / settle / holds / week-key / hash-chain (plan G6).

Proves the money-safety CORE with a FAKE clock + FAKE costs — NO real spend, no transport, no
secret, no model call (the meter is pure bookkeeping; the api-key path is G7). Every test writes
only under a pytest `tmp_path`. The concurrency (inter-process) crux lives in its own file
(`test_meter_concurrency.py`); the umbrella-specific cases in `test_umbrella_cap.py`.
"""

from __future__ import annotations

import ast
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline import opdefaults
from pipeline.spend import meter as M
from pipeline.spend.assignment import SCOPE_USER, SCOPE_ZONE, ScopeKey
from pipeline.spend.meter import (
    LedgerTamperError,
    MeterError,
    MeterRefusedError,
    WeeklyMeter,
)

# A recognizable epoch: 2024-08-07 12:00:00 UTC is a WEDNESDAY (mid-week — advancing the clock by a
# hold TTL stays inside the same calendar week, so an expiry test never accidentally rolls it).
WEDNESDAY_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()
MONDAY_MIDNIGHT = datetime(2024, 8, 5, 0, 0, 0, tzinfo=UTC).timestamp()


class _Clock:
    """A mutable injectable clock — no ambient now (telemetry's discipline)."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _meter(root: Path, clock: _Clock) -> WeeklyMeter:
    return WeeklyMeter(root=root, clock=clock)


def _zone(user_zone: str) -> ScopeKey:
    """A zone ScopeKey whose scope-id carries the user (`<u>/<z>`) — same-named zones under
    different users are DISTINCT (G4's M3), so the meter keys DISTINCT buckets."""
    return ScopeKey(SCOPE_ZONE, user_zone)


def _ledger_path(m: WeeklyMeter, scope: ScopeKey, handle: str) -> Path:
    return m._bucket_dir(M.bucket_key(scope, handle, m.current_week())) / "ledger.jsonl"


def _holds_dir(m: WeeklyMeter, scope: ScopeKey, handle: str) -> Path:
    return m._bucket_dir(M.bucket_key(scope, handle, m.current_week())) / "holds"


# ---------------------------------------------------------------------------------------
# admit — under cap passes; over cap REFUSES pre-spend (no hold)
# ---------------------------------------------------------------------------------------


def test_admit_under_cap_passes_and_counts_the_ceiling(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    hold = m.admit(
        scope=scope,
        handle="anthropic:acme",
        bucket_cap="50",
        umbrella_cap="200",
        ceiling="10",
        run_id="run-1",
    )
    assert hold.ceiling == Decimal("10")
    assert hold.run_id == "run-1"
    # Week-to-date = settled (0) + the one LIVE hold's ceiling (10) — S-3 admission math.
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("10")
    assert m.umbrella_week_to_date() == Decimal("10")
    # A hold file exists (the reservation); the settled ledger does not yet (nothing settled).
    assert list(_holds_dir(m, scope, "anthropic:acme").iterdir())
    assert not _ledger_path(m, scope, "anthropic:acme").exists()


def test_admit_over_bucket_cap_refuses_pre_spend_and_writes_no_hold(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    first = m.admit(
        scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
        ceiling="30", run_id="run-1",
    )
    assert first.ceiling == Decimal("30")
    holds_before = sorted(p.name for p in _holds_dir(m, scope, "anthropic:acme").iterdir())

    # 30 (live hold) + 25 = 55 > 50 → REFUSE, typed, PRE-SPEND, NO new hold.
    with pytest.raises(MeterRefusedError) as excinfo:
        m.admit(
            scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
            ceiling="25", run_id="run-2",
        )
    assert excinfo.value.which == "bucket"
    assert excinfo.value.projected == Decimal("55")
    # No hold was written; week-to-date is UNCHANGED (the refusal cost nothing).
    holds_after = sorted(p.name for p in _holds_dir(m, scope, "anthropic:acme").iterdir())
    assert holds_after == holds_before
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("30")


def test_admit_math_is_settled_plus_all_live_holds(tmp_path: Path) -> None:
    # Two concurrent-style admits (settled=0) must EACH see the other's live hold — settled-only
    # would let both pass. 20 + 20 = 40 ≤ 50 (both fit); a third 20 → 60 > 50 refuses.
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="500")
    m.admit(**kw, ceiling="20", run_id="a")
    m.admit(**kw, ceiling="20", run_id="b")
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("40")
    with pytest.raises(MeterRefusedError):
        m.admit(**kw, ceiling="20", run_id="c")


# ---------------------------------------------------------------------------------------
# settle — appends the hash-chained ledger + releases the hold
# ---------------------------------------------------------------------------------------


def test_settle_appends_ledger_and_releases_the_hold(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    hold = m.admit(
        scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
        ceiling="10", run_id="run-1",
    )
    m.settle(hold, "6.50")  # actual < ceiling
    # After settle: week-to-date is the SETTLED actual (6.50), the hold is gone.
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("6.50")
    assert m.umbrella_week_to_date() == Decimal("6.50")
    assert not list(_holds_dir(m, scope, "anthropic:acme").iterdir())
    # The ledger line records both the reserved ceiling and the actual cost (audit).
    line = json.loads(_ledger_path(m, scope, "anthropic:acme").read_text().splitlines()[0])
    assert line["reserved_ceiling"] == "10" and line["actual_cost"] == "6.50"
    assert line["run_id"] == "run-1" and line["seq"] == 0


def test_settle_in_finally_frees_headroom_for_the_next_run(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200")
    hold = m.admit(**kw, ceiling="40", run_id="r1")
    m.settle(hold, "5")  # spent only $5 of the $40 ceiling
    # settled 5 + next ceiling 40 = 45 ≤ 50 → the next run fits (the ceiling headroom was freed).
    m.admit(**kw, ceiling="40", run_id="r2")
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("45")


# ---------------------------------------------------------------------------------------
# week key — deterministic Monday 00:00 UTC, rolls at the reset boundary (injected clock)
# ---------------------------------------------------------------------------------------


def test_week_key_is_deterministic_monday_utc() -> None:
    assert M.week_key(MONDAY_MIDNIGHT) == "2024-08-05"  # the reset instant belongs to the new week
    assert M.week_key(MONDAY_MIDNIGHT - 1) == "2024-07-29"  # one second before → the prior week
    assert M.week_key(MONDAY_MIDNIGHT + 3600) == "2024-08-05"  # an hour later → same week


def test_week_key_reset_weekday_is_configurable() -> None:
    # A SUNDAY reset (weekday 6) shifts the boundary: at Monday 00:00 the current week started the
    # day before (Sunday 2024-08-04), not that Monday.
    assert M.week_key(MONDAY_MIDNIGHT, reset_weekday=6) == "2024-08-04"


def test_week_key_rolls_at_the_reset_boundary_via_injected_clock(tmp_path: Path) -> None:
    clock = _Clock(MONDAY_MIDNIGHT - 1)  # Sunday 23:59:59 UTC — the PRIOR week
    m = _meter(tmp_path, clock)
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200")
    m.admit(**kw, ceiling="40", run_id="last-week")
    assert m.current_week() == "2024-07-29"
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("40")

    clock.now = MONDAY_MIDNIGHT  # the week ROLLS — a fresh bucket, empty week-to-date
    assert m.current_week() == "2024-08-05"
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("0")
    # The full $50 cap is available again in the new week even though last week is near its cap.
    m.admit(**kw, ceiling="40", run_id="this-week")
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("40")


# ---------------------------------------------------------------------------------------
# crashed hold — self-expires at its full ceiling, then FREES it (TTL, no settle)
# ---------------------------------------------------------------------------------------


def test_crashed_hold_self_expires_then_frees_its_ceiling(tmp_path: Path) -> None:
    clock = _Clock(WEDNESDAY_NOON)
    m = _meter(tmp_path, clock)
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200")
    m.admit(**kw, ceiling="40", run_id="crashes")  # admitted, then the process "crashes", no settle

    # While the hold is LIVE it reserves the full ceiling — a second $40 (→ $80) refuses.
    with pytest.raises(MeterRefusedError):
        m.admit(**kw, ceiling="40", run_id="blocked")

    # Advance the clock PAST the hold TTL (still the same calendar week) — the crashed hold expires.
    clock.now = WEDNESDAY_NOON + M.DEFAULT_HOLD_TTL_SECONDS + 1.0
    assert m.current_week() == "2024-08-05"
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("0")  # ceiling freed
    # The freed headroom now admits — and the stale hold file was reclaimed (self-healing).
    m.admit(**kw, ceiling="40", run_id="after-expiry")
    assert len(list(_holds_dir(m, scope, "anthropic:acme").iterdir())) == 1


def test_refresh_extends_a_hold_past_its_original_expiry(tmp_path: Path) -> None:
    clock = _Clock(WEDNESDAY_NOON)
    m = _meter(tmp_path, clock)
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200")
    hold = m.admit(**kw, ceiling="40", run_id="long-run")

    # Just before the original expiry, the heartbeat refreshes the hold.
    clock.now = WEDNESDAY_NOON + M.DEFAULT_HOLD_TTL_SECONDS - 1.0
    refreshed = m.refresh(hold)
    assert refreshed.expiry > hold.expiry

    # Past the ORIGINAL expiry but within the refreshed TTL — the hold is STILL live (ceiling held).
    clock.now = WEDNESDAY_NOON + M.DEFAULT_HOLD_TTL_SECONDS + 1.0
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("40")


# ---------------------------------------------------------------------------------------
# hash chain — a TAMPERED settled line is DETECTED (edit-EVIDENT); an rm resets (honest R2)
# ---------------------------------------------------------------------------------------


def test_tampered_ledger_line_is_detected(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    hold = m.admit(
        scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
        ceiling="10", run_id="run-1",
    )
    m.settle(hold, "6.50")
    ledger = _ledger_path(m, scope, "anthropic:acme")

    # EDIT the recorded money on disk, keeping the (now stale) this_hash — the chain must break.
    record = json.loads(ledger.read_text().splitlines()[0])
    record["actual_cost"] = "0.01"  # a fraudulently lowered spend
    ledger.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperError):
        m.bucket_week_to_date(scope, "anthropic:acme")
    # Admission is fail-closed on a tampered ledger too (never spends off a forged total).
    with pytest.raises(LedgerTamperError):
        m.admit(
            scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
            ceiling="1", run_id="run-2",
        )


def test_dropped_middle_ledger_line_breaks_the_chain(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="500", umbrella_cap="900")
    for i in range(3):
        h = m.admit(**kw, ceiling="10", run_id=f"r{i}")
        m.settle(h, "10")
    ledger = _ledger_path(m, scope, "anthropic:acme")
    lines = ledger.read_text().splitlines()
    # Remove the MIDDLE settled line — the next line's prev_hash no longer chains (edit-EVIDENT).
    ledger.write_text(lines[0] + "\n" + lines[2] + "\n", encoding="utf-8")
    with pytest.raises(LedgerTamperError):
        m.bucket_week_to_date(scope, "anthropic:acme")


def test_a_full_ledger_rm_silently_resets_the_cap_documented_residual_r2(tmp_path: Path) -> None:
    # HONEST framing: the hash-chain is EDIT-evident, NOT reset-proof. A full `rm` of the ledger
    # reopens the cap with NO tamper error (operator-bounds-their-own-bill, R2).
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    hold = m.admit(
        scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200",
        ceiling="10", run_id="run-1",
    )
    m.settle(hold, "10")
    os.remove(_ledger_path(m, scope, "anthropic:acme"))
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("0")  # reset, no error (R2)


# ---------------------------------------------------------------------------------------
# same-named zones under DIFFERENT users never cross-charge (scope-id carries the user, M3)
# ---------------------------------------------------------------------------------------


def test_same_named_zones_under_different_users_never_cross_charge(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    dave = _zone("dave/work")
    erin = _zone("erin/work")  # SAME zone name "work", DIFFERENT user → a DISTINCT bucket
    kw = dict(handle="anthropic:acme", bucket_cap="50", umbrella_cap="500")

    m.admit(scope=dave, **kw, ceiling="45", run_id="dave-run")
    # erin/work has its OWN full $50 cap — dave's near-cap spend does not touch it.
    m.admit(scope=erin, **kw, ceiling="45", run_id="erin-run")
    assert m.bucket_week_to_date(dave, "anthropic:acme") == Decimal("45")
    assert m.bucket_week_to_date(erin, "anthropic:acme") == Decimal("45")
    # Dave's bucket is at its cap — a further $10 for DAVE refuses; ERIN is unaffected.
    with pytest.raises(MeterRefusedError):
        m.admit(scope=dave, **kw, ceiling="10", run_id="dave-over")


def test_user_and_zone_buckets_are_distinct(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    user = ScopeKey(SCOPE_USER, "dave")
    zone = ScopeKey(SCOPE_ZONE, "dave/work")
    kw = dict(handle="anthropic:acme", bucket_cap="50", umbrella_cap="500")
    m.admit(scope=user, **kw, ceiling="45", run_id="user-run")
    m.admit(scope=zone, **kw, ceiling="45", run_id="zone-run")
    assert m.bucket_week_to_date(user, "anthropic:acme") == Decimal("45")
    assert m.bucket_week_to_date(zone, "anthropic:acme") == Decimal("45")


# ---------------------------------------------------------------------------------------
# hold-TTL invariant (S-2) — pinned to STRICTLY EXCEED one paid call; fails LOUD if violated
# ---------------------------------------------------------------------------------------


def test_hold_ttl_pin_strictly_exceeds_one_paid_call() -> None:
    # The cross-module inequality pin (mirrors transport.py's DEFAULT_TIMEOUT_SECONDS < lease-TTL).
    assert M.DEFAULT_HOLD_TTL_SECONDS > opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS


def test_hold_ttl_invariant_fails_loud_when_violated(tmp_path: Path) -> None:
    # A hold TTL that does NOT strictly exceed one paid call is refused LOUDLY — both as a bare
    # check and at meter construction (so the invariant can never silently drift).
    with pytest.raises(MeterError):
        M.check_hold_ttl_invariant(opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS)  # equal is not >
    with pytest.raises(MeterError):
        WeeklyMeter(root=tmp_path, hold_ttl_seconds=60.0)  # 60s < one 1200s paid call


# ---------------------------------------------------------------------------------------
# money-safety / boundary — no transport, no secret, no spend; the meter is pure bookkeeping
# ---------------------------------------------------------------------------------------


def test_meter_imports_no_generation_or_transport_machinery() -> None:
    """meter.py imports the store atomics + the injectable Clock + the assignment/keystore config
    types — NEVER the generation/transport-selection machinery (compose/review/reconcile/driver/
    transport/resolve/wall/construction). It is pure bookkeeping; there is NO spend surface (G7)."""
    source = Path(M.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "pipeline.compose",
        "pipeline.review",
        "pipeline.reconcile",
        "pipeline.driver",
        "pipeline.transport",
        "pipeline.spend.resolve",
        "pipeline.spend.wall",
        "pipeline.spend.construction",
    }
    assert not (imported & forbidden), f"meter must not import {imported & forbidden}"
    # It MAY import the keystore/assignment types (the allowed spend-config surface).
    assert "pipeline.spend.assignment" in imported


def test_negative_amounts_and_bad_caps_refuse_loudly(tmp_path: Path) -> None:
    m = _meter(tmp_path, _Clock(WEDNESDAY_NOON))
    scope = _zone("dave/work")
    kw = dict(scope=scope, handle="h:x", umbrella_cap="9")
    with pytest.raises(MeterError):  # a zero/negative cap is not a budget
        m.admit(**kw, bucket_cap="0", ceiling="1", run_id="z")
    with pytest.raises(MeterError):  # a negative ceiling is nonsense
        m.admit(**kw, bucket_cap="9", ceiling="-1", run_id="n")
