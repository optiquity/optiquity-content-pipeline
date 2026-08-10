"""The install-wide UMBRELLA cap — binds on top of per-bucket caps; charged atomically (plan G6).

FAKE clock + FAKE costs — NO real spend, no transport, no secret. Covers the meter's umbrella
admission math (the umbrella refuses when the install-wide total would exceed it EVEN WHEN a
per-bucket has headroom; every admit charges BOTH the bucket and the umbrella) and the
`transport set-umbrella-cap` / `clear-umbrella-cap` Tier-A admin verbs (persisted in the shared
transport config; hard-refuses an absent amount; single-valued; preserves the other config blocks).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_transport
from pipeline.spend import meter as M
from pipeline.spend.assignment import (
    SCOPE_ZONE,
    Assignment,
    ScopeKey,
    load_store,
    save_store,
)
from pipeline.spend.keystore import SecretRef
from pipeline.spend.meter import MeterRefusedError, UmbrellaCapError, WeeklyMeter, umbrella_cap

WEDNESDAY_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _umbrella_holds(m: WeeklyMeter) -> list[str]:
    holds = m._bucket_dir(M.umbrella_bucket_key(m.current_week())) / "holds"
    return sorted(p.name for p in holds.iterdir()) if holds.is_dir() else []


def _bucket_holds(m: WeeklyMeter, scope: ScopeKey, handle: str) -> list[str]:
    holds = m._bucket_dir(M.bucket_key(scope, handle, m.current_week())) / "holds"
    return sorted(p.name for p in holds.iterdir()) if holds.is_dir() else []


# ---------------------------------------------------------------------------------------
# the umbrella binds ACROSS buckets — refuses even when a per-bucket has headroom
# ---------------------------------------------------------------------------------------


def test_umbrella_refuses_when_install_total_exceeds_even_with_per_bucket_headroom(
    tmp_path: Path,
) -> None:
    m = WeeklyMeter(root=tmp_path, clock=_Clock(WEDNESDAY_NOON))
    bucket_a = ScopeKey(SCOPE_ZONE, "dave/work")
    bucket_b = ScopeKey(SCOPE_ZONE, "erin/work")
    # Each bucket has a HUGE $100 cap; the install umbrella is only $15.
    kw = dict(handle="anthropic:acme", bucket_cap="100", umbrella_cap="15")

    m.admit(scope=bucket_a, **kw, ceiling="10", run_id="a")  # umbrella now 10 (≤ 15)
    # Bucket B has $90 of its own headroom, but 10 + 10 = 20 > 15 umbrella → REFUSE (umbrella).
    with pytest.raises(MeterRefusedError) as excinfo:
        m.admit(scope=bucket_b, **kw, ceiling="10", run_id="b")
    assert excinfo.value.which == "umbrella"
    assert excinfo.value.projected == Decimal("20")
    # The refusal charged NEITHER bucket B NOR the umbrella (both-or-neither atomicity).
    assert _bucket_holds(m, bucket_b, "anthropic:acme") == []
    assert m.umbrella_week_to_date() == Decimal("10")
    assert len(_umbrella_holds(m)) == 1  # only bucket A's charge


def test_every_admit_charges_both_bucket_and_umbrella_atomically(tmp_path: Path) -> None:
    m = WeeklyMeter(root=tmp_path, clock=_Clock(WEDNESDAY_NOON))
    scope = ScopeKey(SCOPE_ZONE, "dave/work")
    kw = dict(scope=scope, handle="anthropic:acme", bucket_cap="50", umbrella_cap="200")

    hold = m.admit(**kw, ceiling="12", run_id="run-1")
    # BOTH the bucket and the umbrella carry the hold, under ONE token.
    assert _bucket_holds(m, scope, "anthropic:acme") == [hold.token]
    assert _umbrella_holds(m) == [hold.token]
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("12")
    assert m.umbrella_week_to_date() == Decimal("12")

    m.settle(hold, "7")
    # settle moves BOTH ledgers together and drops BOTH holds.
    assert m.bucket_week_to_date(scope, "anthropic:acme") == Decimal("7")
    assert m.umbrella_week_to_date() == Decimal("7")
    assert _bucket_holds(m, scope, "anthropic:acme") == []
    assert _umbrella_holds(m) == []


def test_umbrella_headroom_admits_exactly_what_fits(tmp_path: Path) -> None:
    m = WeeklyMeter(root=tmp_path, clock=_Clock(WEDNESDAY_NOON))
    kw = dict(handle="anthropic:acme", bucket_cap="1000", umbrella_cap="10")
    admitted = 0
    for i in range(8):
        try:
            m.admit(scope=ScopeKey(SCOPE_ZONE, f"u{i}/work"), **kw, ceiling="3", run_id=f"r{i}")
            admitted += 1
        except MeterRefusedError:
            pass
    # floor(10 / 3) = 3 admits (3×3=9 ≤ 10; a 4th → 12 > 10 refuses); the rest refuse pre-spend.
    assert admitted == 3
    assert m.umbrella_week_to_date() == Decimal("9")


# ---------------------------------------------------------------------------------------
# the `transport set-umbrella-cap` admin verb (Tier-A, Decimal, hard-refuses absent)
# ---------------------------------------------------------------------------------------


def test_set_umbrella_cap_persists_a_positive_decimal(tmp_path: Path, capsys) -> None:
    code = _cmd_transport(["set-umbrella-cap", "200", "--root", str(tmp_path)])
    assert code == 0
    assert umbrella_cap(tmp_path) == Decimal("200")
    assert "200" in capsys.readouterr().out
    # Fractional dollars round-trip exactly (Decimal, not float).
    assert _cmd_transport(["set-umbrella-cap", "49.50", "--root", str(tmp_path)]) == 0
    assert umbrella_cap(tmp_path) == Decimal("49.50")


def test_set_umbrella_cap_hard_refuses_an_absent_amount(tmp_path: Path, capsys) -> None:
    code = _cmd_transport(["set-umbrella-cap", "--root", str(tmp_path)])
    assert code == 2  # usage refusal — no uncapped umbrella
    assert "REQUIRED" in capsys.readouterr().err
    assert umbrella_cap(tmp_path) is None  # nothing written


def test_set_umbrella_cap_refuses_a_non_positive_amount(tmp_path: Path, capsys) -> None:
    assert _cmd_transport(["set-umbrella-cap", "0", "--root", str(tmp_path)]) == 1
    assert _cmd_transport(["set-umbrella-cap", "-5", "--root", str(tmp_path)]) == 1
    assert umbrella_cap(tmp_path) is None


def test_set_umbrella_cap_is_single_valued_and_swappable(tmp_path: Path) -> None:
    _cmd_transport(["set-umbrella-cap", "200", "--root", str(tmp_path)])
    _cmd_transport(["set-umbrella-cap", "300", "--root", str(tmp_path)])
    assert umbrella_cap(tmp_path) == Decimal("300")  # REPLACED, never a second entry


def test_clear_umbrella_cap_is_idempotent(tmp_path: Path, capsys) -> None:
    _cmd_transport(["set-umbrella-cap", "200", "--root", str(tmp_path)])
    assert _cmd_transport(["clear-umbrella-cap", "--root", str(tmp_path)]) == 0
    assert umbrella_cap(tmp_path) is None
    # A second clear is a clean no-op (exit 0).
    assert _cmd_transport(["clear-umbrella-cap", "--root", str(tmp_path)]) == 0
    assert "no-op" in capsys.readouterr().out


def test_umbrella_cap_coexists_with_assignments_and_entitlement(tmp_path: Path) -> None:
    # One store, one renderer: an assignment + an entitled user + an umbrella cap all coexist and a
    # set/clear of ANY block never clobbers the others.
    store = load_store(tmp_path)
    ref = SecretRef.parse("anthropic:acme")
    store.assign(Assignment(ScopeKey("user", "dave"), ref, Decimal("50")))
    store.set_entitled_user("dave")
    save_store(store, tmp_path)

    _cmd_transport(["set-umbrella-cap", "200", "--root", str(tmp_path)])

    reloaded = load_store(tmp_path)
    assert reloaded.umbrella_cap_usd == Decimal("200")
    assert reloaded.entitled_user == "dave"
    assert reloaded.get(ScopeKey("user", "dave")) is not None


def test_show_surfaces_the_umbrella_cap(tmp_path: Path, capsys) -> None:
    _cmd_transport(["set-umbrella-cap", "200", "--root", str(tmp_path)])
    assert _cmd_transport(["show", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "umbrella cap:" in out and "$200/week" in out


def test_meter_set_umbrella_cap_validates_positivity(tmp_path: Path) -> None:
    with pytest.raises(UmbrellaCapError):
        M.set_umbrella_cap(tmp_path, Decimal("0"))
    with pytest.raises(UmbrellaCapError):
        M.set_umbrella_cap(tmp_path, Decimal("-1"))
    assert umbrella_cap(tmp_path) is None
