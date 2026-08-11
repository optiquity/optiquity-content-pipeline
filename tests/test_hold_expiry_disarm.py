"""The DISARM CRUX (plan G7): the F10-strip disarm fires ONLY under a LIVE, unexpired hold.

The money-safety heart of the first paid surface. `transport.py` cannot import the meter (no cycle —
the plan TYPE lives in transport), so the chokepoint checks the plan-EMBEDDED `hold_expiry` against
an INJECTED clock. This proves — with a STUBBED seam, ZERO real spend — that:

- `mode=="apikey"` with NO hold (`hold_expiry=None`, a forgotten thread) → FAIL-CLOSED refuse, no
  spawn (the runner is NEVER called);
- an apikey plan whose embedded expiry is AT or PAST the injected clock (an expired hold whose
  ceiling has been freed) → FAIL-CLOSED refuse, no spawn;
- ONLY a LIVE (strictly-future) hold disarms the widened F10 strip → the api key is injected and the
  process spawns.

No meter is involved here on purpose: the chokepoint trusts the plan-embedded expiry, so a
mis-resolved / stale hold can NEVER silently spend even if the meter said otherwise.
"""

from __future__ import annotations

import json

import pytest

from pipeline.transport import (
    NoLiveHoldError,
    ProcessOutcome,
    TransportPlan,
    invoke_headless,
)

_OK_JSON = json.dumps(
    {"type": "result", "is_error": False, "subtype": "success", "result": "ok",
     "total_cost_usd": 0.1}
)


class _SpyRunner:
    """Records whether it was called — a refusal must NEVER reach the runner (no spawn)."""

    def __init__(self) -> None:
        self.called = False
        self.request = None

    def __call__(self, request) -> ProcessOutcome:
        self.called = True
        self.request = request
        return ProcessOutcome(timed_out=False, returncode=0, stdout=_OK_JSON, stderr="")


def _apikey_plan(hold_expiry: float | None) -> TransportPlan:
    """An apikey plan with a controllable embedded hold expiry (no meter — the chokepoint trusts
    the plan-embedded expiry vs the injected clock)."""
    return TransportPlan.apikey(
        per_call_cap=5.0,
        api_key_reveal=lambda: "sk-ant-INJECTED",
        hold_expiry=hold_expiry,
    )


def test_apikey_with_no_hold_refuses_fail_closed_no_spawn() -> None:
    runner = _SpyRunner()
    with pytest.raises(NoLiveHoldError) as exc:
        invoke_headless("p", plan=_apikey_plan(None), runner=runner, clock=lambda: 1000.0)
    assert exc.value.hold_expiry is None
    assert "absent" in str(exc.value)
    assert not runner.called  # NO spawn — the runner was never reached


def test_apikey_with_expired_hold_refuses_fail_closed_no_spawn() -> None:
    runner = _SpyRunner()
    # hold_expiry 900 is PAST the injected clock 1000 → the ceiling has been freed → refuse.
    with pytest.raises(NoLiveHoldError) as exc:
        invoke_headless("p", plan=_apikey_plan(900.0), runner=runner, clock=lambda: 1000.0)
    assert exc.value.hold_expiry == 900.0
    assert "expired" in str(exc.value)
    assert not runner.called


def test_apikey_hold_expiry_equal_to_clock_refuses_strictly() -> None:
    runner = _SpyRunner()
    # Boundary: expiry == now is NOT live (the disarm requires STRICTLY ahead of the clock).
    with pytest.raises(NoLiveHoldError):
        invoke_headless("p", plan=_apikey_plan(1000.0), runner=runner, clock=lambda: 1000.0)
    assert not runner.called


def test_apikey_with_live_hold_disarms_and_spawns() -> None:
    runner = _SpyRunner()
    # hold_expiry 2000 is strictly AHEAD of the injected clock 1000 → LIVE → disarm + spawn.
    result = invoke_headless("p", plan=_apikey_plan(2000.0), runner=runner, clock=lambda: 1000.0)
    assert result.status == "ok"
    assert runner.called  # the ONLY case that spawns
    # The disarm injected the key into the child ENV (never argv).
    env = dict(runner.request.env)
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-INJECTED"
    assert "sk-ant-INJECTED" not in " ".join(runner.request.argv)


def test_subscription_plan_never_reaches_the_hold_check() -> None:
    # A subscription plan has no hold and no key — it must spawn under the subscription wall with NO
    # NoLiveHoldError (the disarm check is apikey-only). The stubbed runner records the argv.
    runner = _SpyRunner()
    plan = TransportPlan.subscription()
    result = invoke_headless("p", plan=plan, runner=runner, clock=lambda: 1000.0)
    assert result.status == "ok"
    assert runner.called
    env = dict(runner.request.env)
    assert "ANTHROPIC_API_KEY" not in env  # subscription never injects a key (F10)
    assert "--settings" in runner.request.argv  # the subscription wall IS applied
