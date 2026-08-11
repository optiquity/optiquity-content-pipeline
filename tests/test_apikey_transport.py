"""The G7 API-KEY transport path — resolve → admit → spawn under the $5 cap → settle (plan G7).

The FIRST PAID SURFACE, proven with a STUBBED paid seam (a fake `Runner` + a fake `Clock` + fake
costs) — ZERO real spend, no real model call, no live network. Every test writes only under a pytest
`tmp_path`; the secret is stored in a tmp keystore OUTSIDE the repo tree (the S-2 guard). This file
proves: an api-key run ADMITS its ceiling, spawns under the FINITE $5 per-call cap (the stubbed seam
records the argv cap), injects the key into the child ENV (never argv/log), and SETTLES the
accumulated ACTUAL cost; a ceiling that would exceed the bucket OR the umbrella REFUSES pre-spend
(no hold, no spawn); the maintainer defaults ($5 per-call, $50 umbrella) apply.
"""

from __future__ import annotations

import json
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
from pipeline.spend.meter import MeterRefusedError, WeeklyMeter
from pipeline.spend.resolve import (
    DEFAULT_API_PER_CALL_CAP_USD,
    DEFAULT_UMBRELLA_CAP_USD,
    resolve_transport,
)
from pipeline.transport import ProcessOutcome, invoke_headless

#: A recognizable mid-week epoch (Wednesday noon UTC) — advancing by a hold TTL stays in-week.
WED_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()

#: The secret used across this file — a recognizable token so a leak into argv/repr is obvious.
SECRET = "sk-ant-SECRET-VALUE-do-not-leak"


class _Clock:
    """A mutable injectable clock — no ambient now (telemetry's discipline)."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _RecordingRunner:
    """A STUBBED paid seam: records the ProcessRequest + returns a fake ok result with a fake cost.
    NEVER spawns a real process, NEVER makes a model call — zero real spend."""

    def __init__(self, cost: float = 0.0) -> None:
        self.cost = cost
        self.requests: list = []

    def __call__(self, request) -> ProcessOutcome:
        self.requests.append(request)
        stdout = json.dumps(
            {
                "type": "result",
                "is_error": False,
                "subtype": "success",
                "result": "stubbed-output",
                "total_cost_usd": self.cost,
            }
        )
        return ProcessOutcome(timed_out=False, returncode=0, stdout=stdout, stderr="")


def _setup(
    tmp_path: Path,
    *,
    bucket_cap: str = "100",
    umbrella: str | None = "200",
    handle: str = "anthropic:acme",
):
    """Store a secret in a tmp keystore, assign the handle at zone `dave/work`, build a meter."""
    backend = FileSecretBackend(tmp_path / "secrets")
    ref = SecretRef.parse(handle)
    backend.store(ref, SECRET)
    scope = ScopeKey(SCOPE_ZONE, "dave/work")
    store = AssignmentStore(
        [Assignment(scope, ref, Decimal(bucket_cap))],
        umbrella_cap_usd=(Decimal(umbrella) if umbrella is not None else None),
    )
    clock = _Clock(WED_NOON)
    meter = WeeklyMeter(root=tmp_path, clock=clock)
    return backend, ref, scope, store, clock, meter


def _resolve(tmp_path, backend, store, meter, *, n_artifacts=1, n_deliverables=1, override=None):
    return resolve_transport(
        tmp_path,
        "dave",
        "work",
        "acme",
        override=override,
        n_artifacts=n_artifacts,
        n_deliverables=n_deliverables,
        meter=meter,
        resolver=backend,
        store=store,
    )


# ---------------------------------------------------------------------------------------
# The happy path: admit → spawn under $5 → settle
# ---------------------------------------------------------------------------------------


def test_apikey_run_admits_spawns_under_five_dollar_cap_and_settles(tmp_path: Path) -> None:
    backend, ref, scope, store, clock, meter = _setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)

    assert admission.plan.mode == "apikey"
    assert admission.plan.per_call_cap == 5.0  # the FINITE maintainer default ($5)
    assert admission.hold is not None
    # The hold reserved the ceiling in BOTH the bucket and the umbrella (S-3 admission math).
    assert meter.bucket_week_to_date(scope, ref) == admission.hold.ceiling
    assert meter.umbrella_week_to_date() == admission.hold.ceiling

    runner = _RecordingRunner(cost=0.42)  # a fake ACTUAL cost, well under the ceiling
    result = invoke_headless("the prompt", plan=admission.plan, runner=runner, clock=clock)
    assert result.status == "ok"
    argv = list(runner.requests[0].argv)
    env = dict(runner.requests[0].env)

    # (a) The FINITE $5 per-call cap is FORCED on argv (min(caller=None, 5.0) == 5.0).
    assert "--max-budget-usd" in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "5.0"
    # (b) The api key rides the child ENV, NEVER argv (I5); the subscription wall is NOT applied.
    assert env["ANTHROPIC_API_KEY"] == SECRET
    assert "--settings" not in argv and "--setting-sources" not in argv
    # (c) SETTLE the accumulated ACTUAL cost in a finally (here, explicitly): the hold drops, the
    #     settled ledger records 0.42, and week-to-date collapses to the real spend.
    admission.settle(admission.plan.cost_accumulator.total)
    assert meter.bucket_week_to_date(scope, ref) == Decimal("0.42")
    assert meter.umbrella_week_to_date() == Decimal("0.42")


def test_apikey_forces_the_min_of_caller_and_five(tmp_path: Path) -> None:
    backend, ref, scope, store, clock, meter = _setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)
    runner = _RecordingRunner()
    # A caller budget SMALLER than $5 is kept (min); a larger one is clamped to $5.
    invoke_headless("p", plan=admission.plan, runner=runner, max_budget_usd=2.0, clock=clock)
    argv = list(runner.requests[0].argv)
    assert argv[argv.index("--max-budget-usd") + 1] == "2.0"

    runner2 = _RecordingRunner()
    invoke_headless("p", plan=admission.plan, runner=runner2, max_budget_usd=9.0, clock=clock)
    argv2 = list(runner2.requests[0].argv)
    assert argv2[argv2.index("--max-budget-usd") + 1] == "5.0"


# ---------------------------------------------------------------------------------------
# Pre-spend refusals: a ceiling over the bucket OR the umbrella → REFUSE (no hold, no spawn)
# ---------------------------------------------------------------------------------------


def test_ceiling_over_bucket_cap_refuses_pre_spend_no_hold(tmp_path: Path) -> None:
    # ceiling = $5 × 12 calls = $60 (n_artifacts=1, n_deliverables=1) > a $10 bucket cap.
    backend, ref, scope, store, clock, meter = _setup(tmp_path, bucket_cap="10", umbrella="1000")
    with pytest.raises(MeterRefusedError) as exc:
        _resolve(tmp_path, backend, store, meter)
    assert exc.value.which == "bucket"
    # NOTHING was reserved — no hold in the bucket, week-to-date still zero (refusal cost nothing).
    assert meter.bucket_week_to_date(scope, ref) == Decimal("0")


def test_ceiling_over_umbrella_refuses_pre_spend_no_hold(tmp_path: Path) -> None:
    # A generous bucket ($1000) but a tiny umbrella ($1): the umbrella refuses ($60 > $1).
    backend, ref, scope, store, clock, meter = _setup(tmp_path, bucket_cap="1000", umbrella="1")
    with pytest.raises(MeterRefusedError) as exc:
        _resolve(tmp_path, backend, store, meter)
    assert exc.value.which == "umbrella"
    assert meter.umbrella_week_to_date() == Decimal("0")


# ---------------------------------------------------------------------------------------
# The maintainer defaults: per-call $5 (finite), umbrella $50 when unset
# ---------------------------------------------------------------------------------------


def test_per_call_cap_default_is_five(tmp_path: Path) -> None:
    assert DEFAULT_API_PER_CALL_CAP_USD == Decimal("5.00")
    backend, ref, scope, store, clock, meter = _setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)
    assert admission.plan.per_call_cap == 5.0


def test_umbrella_default_fifty_applies_when_unset(tmp_path: Path) -> None:
    assert DEFAULT_UMBRELLA_CAP_USD == Decimal("50.00")
    # No umbrella configured (umbrella=None) → the $50 default. ceiling $60 > $50 → refuse umbrella,
    # even though the bucket ($100) has headroom. Proves the $50 default is applied at admit.
    backend, ref, scope, store, clock, meter = _setup(tmp_path, bucket_cap="100", umbrella=None)
    with pytest.raises(MeterRefusedError) as exc:
        _resolve(tmp_path, backend, store, meter)
    assert exc.value.which == "umbrella"
    assert exc.value.cap == Decimal("50.00")


def test_umbrella_default_leaves_headroom_for_a_small_run(tmp_path: Path) -> None:
    # A single-artifact, zero-deliverable run: ceiling = $5 × 6 = $30 < the $50 default umbrella.
    backend, ref, scope, store, clock, meter = _setup(tmp_path, bucket_cap="100", umbrella=None)
    admission = _resolve(tmp_path, backend, store, meter, n_deliverables=0)
    assert admission.plan.mode == "apikey"
    assert admission.hold is not None
    assert admission.hold.ceiling == Decimal("30.00")


# ---------------------------------------------------------------------------------------
# Secret hygiene (I5): the resolved key is NEVER in argv or the plan's repr
# ---------------------------------------------------------------------------------------


def test_secret_never_in_argv_or_plan_repr(tmp_path: Path) -> None:
    backend, ref, scope, store, clock, meter = _setup(tmp_path)
    admission = _resolve(tmp_path, backend, store, meter)
    # The plan carries only a reveal CALLABLE + the hold expiry, never the value (redacted repr).
    assert SECRET not in repr(admission.plan)
    runner = _RecordingRunner()
    invoke_headless("p", plan=admission.plan, runner=runner, clock=clock)
    argv_text = " ".join(runner.requests[0].argv)
    assert SECRET not in argv_text  # the key rides the ENV only, never argv (I5)
