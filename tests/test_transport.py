"""Step-23 tests: `pipeline/transport.py`, the headless subprocess wrapper (F10, §21.9).

Covers, all subprocess-MOCKED via a fake `Runner` (mirrors `pipeline.adapters.graphify`'s
seam — no real process spawned) unless marked `@pytest.mark.live`:

- **F10 refusal:** `build_child_env`/`invoke_headless` hard-refuse (typed
  `ApiKeyPresentError`) when `ANTHROPIC_API_KEY` would ride the child env via an explicit
  `env_overrides` entry, and never invoke the runner in that case; the AMBIENT-env strip
  (this dev machine's standing F10 hazard per gate G5/state.md) is silent, never an error.
- **Per-call statelessness by construction:** `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` always
  lands in the child env, even under an override attempting to unset it.
- **The result taxonomy** (step-06 BUILD PARAMETER SHEET item 5, transcripts in
  `ops-handoff/build/step-04/report.md`): success = the exact three-way conjunction
  (never `subtype` alone — the QUIRK a real transcript pins here); timeout (no JSON);
  malformed output (unparseable / non-dict / missing-envelope JSON); CLI-arg error
  (empty stdout, nonzero exit); the NAMED error shapes `api_error`/`budget_exhausted`;
  and typed `rate-limit-backpressure` — both via a recognized keyword hit UNDER an
  `api_error` terminal reason and via the "any other unrecognized `is_error:true` shape"
  fallback the sheet's item 5.8 mandates.
- **The timeout < lease-TTL invariant** (§22.3/§22.4): a cross-module inequality pin
  against `pipeline.claims.DEFAULT_LEASE_TTL_SECONDS`, so a change to either constant
  fails this test rather than silently drifting the "expired lease ⇒ dead process"
  guarantee.
- **Argv/stdin shape:** the mandatory flag set, prompt delivered via stdin only (never
  argv — the step-04 §3.3d hazard), optional flags appear in argv only when passed.

Plus exactly ONE live smoke test (`@pytest.mark.live`, deselected by default per PA-5/
pyproject `addopts`), which spawns the REAL `claude` binary on subscription auth and
asserts a structured, successful result.
"""

from __future__ import annotations

import json
import shutil

import pytest

import pipeline.claims as claims_module
from pipeline.transport import (
    ANTHROPIC_API_KEY_ENV,
    ANTHROPIC_AUTH_TOKEN_ENV,
    CLAUDE_CODE_USE_BEDROCK_ENV,
    CLAUDE_CODE_USE_FOUNDRY_ENV,
    CLAUDE_CODE_USE_VERTEX_ENV,
    DEFAULT_TIMEOUT_SECONDS,
    DISABLE_AUTO_MEMORY_ENV,
    F10_STRIPPED_ENV_VARS,
    ApiKeyPresentError,
    BinaryNotFoundError,
    CostAccumulator,
    ProcessOutcome,
    ProcessRequest,
    TransportError,
    TransportPlan,
    TransportResult,
    build_child_env,
    invoke_headless,
)

# --- verified transcripts (step-04 report §3, reproduced as fixed JSON strings) --------------

#: `claude -p 'reply with exactly: OK' --output-format json`, trimmed to the fields this
#: module reads (probe1.json).
SUCCESS_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "api_error_status": None,
        "duration_ms": 6579,
        "result": "OK",
        "session_id": "8b62be4e-21c4-4f5e-af6d-2ebbf7299a89",
        "total_cost_usd": 0.230628,
        "terminal_reason": "completed",
        "uuid": "9f0e2967-b7fa-4ff3-a961-79cf9aa9d266",
    }
)

#: `--model claude-nonexistent-99` (step-04 §3.3b) — the load-bearing QUIRK: `subtype`
#: stays `"success"` even though `is_error` is true.
API_ERROR_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "api_error_status": 404,
        "result": "There's an issue with the selected model (claude-nonexistent-99).",
        "terminal_reason": "api_error",
        "total_cost_usd": 0,
    }
)

#: `--max-budget-usd 0.0001` (step-04 §3.3c) — NOTE: no "result" key at all.
BUDGET_EXHAUSTED_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "error_max_budget_usd",
        "is_error": True,
        "terminal_reason": "budget_exhausted",
        "errors": ["Reached maximum budget ($0.0001)"],
        "total_cost_usd": 0.170785,
    }
)


class FakeRunner:
    """A recording process seam: one scripted `ProcessOutcome`, zero subprocesses."""

    def __init__(self, outcome: ProcessOutcome) -> None:
        self.outcome = outcome
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        return self.outcome

    @property
    def call_count(self) -> int:
        return len(self.requests)


def outcome_ok(stdout: str, *, returncode: int = 0) -> ProcessOutcome:
    return ProcessOutcome(timed_out=False, returncode=returncode, stdout=stdout, stderr="")


# ---------------------------------------------------------------------------
# build_child_env — the F10 belt-and-suspenders contract.
# ---------------------------------------------------------------------------


def test_build_child_env_strips_ambient_api_key_silently(monkeypatch):
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, "sk-ant-should-never-survive")
    env = build_child_env()
    assert ANTHROPIC_API_KEY_ENV not in env
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_build_child_env_strips_from_explicit_base_env():
    base = {ANTHROPIC_API_KEY_ENV: "sk-ant-explicit", "PATH": "/usr/bin"}
    env = build_child_env(base)
    assert ANTHROPIC_API_KEY_ENV not in env
    assert env["PATH"] == "/usr/bin"
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_build_child_env_no_key_anywhere_is_the_ordinary_clean_path(monkeypatch):
    monkeypatch.delenv(ANTHROPIC_API_KEY_ENV, raising=False)
    env = build_child_env({"PATH": "/usr/bin"})
    assert ANTHROPIC_API_KEY_ENV not in env
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_build_child_env_refuses_explicit_override_of_the_api_key():
    with pytest.raises(ApiKeyPresentError) as excinfo:
        build_child_env({"PATH": "/usr/bin"}, overrides={ANTHROPIC_API_KEY_ENV: "sk-ant-hi"})
    assert excinfo.value.code == "api-key-present"
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


def test_build_child_env_override_cannot_unset_auto_memory_kill_switch():
    """§21.9 per-call statelessness must survive any override attempt to unset it."""
    env = build_child_env({}, overrides={DISABLE_AUTO_MEMORY_ENV: "0"})
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_build_child_env_merges_other_overrides():
    env = build_child_env({"PATH": "/usr/bin"}, overrides={"EXTRA": "value"})
    assert env["EXTRA"] == "value"
    assert env["PATH"] == "/usr/bin"


def test_build_child_env_strips_the_widened_f10_siblings():
    """G2 (S-4): the strip is WIDENED beyond ANTHROPIC_API_KEY to the sibling auth/provider vars
    that outrank or divert the subscription — ANTHROPIC_AUTH_TOKEN + the CLAUDE_CODE_USE_* trio."""
    base = {
        "PATH": "/usr/bin",
        ANTHROPIC_AUTH_TOKEN_ENV: "sk-auth",
        CLAUDE_CODE_USE_BEDROCK_ENV: "1",
        CLAUDE_CODE_USE_VERTEX_ENV: "1",
        CLAUDE_CODE_USE_FOUNDRY_ENV: "1",
    }
    env = build_child_env(base)
    for var in (
        ANTHROPIC_AUTH_TOKEN_ENV,
        CLAUDE_CODE_USE_BEDROCK_ENV,
        CLAUDE_CODE_USE_VERTEX_ENV,
        CLAUDE_CODE_USE_FOUNDRY_ENV,
    ):
        assert var not in env
    assert env["PATH"] == "/usr/bin"  # unrelated vars pass through
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_build_child_env_re_strips_a_widened_sibling_smuggled_via_overrides():
    """An override cannot re-add a widened sibling: it is stripped again AFTER the merge (the
    hard-refused ANTHROPIC_API_KEY has its own refusal; the siblings are silently re-stripped)."""
    env = build_child_env({"PATH": "/usr/bin"}, overrides={CLAUDE_CODE_USE_BEDROCK_ENV: "1"})
    assert CLAUDE_CODE_USE_BEDROCK_ENV not in env
    assert ANTHROPIC_API_KEY_ENV in F10_STRIPPED_ENV_VARS  # the whole set is stripped in order


# ---------------------------------------------------------------------------
# invoke_headless — the F10 refusal path (integration: the runner is never called).
# ---------------------------------------------------------------------------


def test_invoke_headless_refuses_and_never_calls_the_runner_when_key_overridden():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    with pytest.raises(ApiKeyPresentError):
        invoke_headless(
            "hello",
            env_overrides={ANTHROPIC_API_KEY_ENV: "sk-ant-smuggled"},
            runner=fake,
        )
    assert fake.call_count == 0


def test_invoke_headless_strips_ambient_key_and_still_calls_the_runner(monkeypatch):
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, "sk-ant-ambient")
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    result = invoke_headless("hello", runner=fake)
    assert result.status == "ok"
    assert fake.call_count == 1
    assert ANTHROPIC_API_KEY_ENV not in fake.requests[0].env
    assert fake.requests[0].env[DISABLE_AUTO_MEMORY_ENV] == "1"


# ---------------------------------------------------------------------------
# argv / stdin shape.
# ---------------------------------------------------------------------------


def test_prompt_rides_stdin_never_argv():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("SECRET-PROMPT-TEXT", runner=fake)
    request = fake.requests[0]
    assert request.stdin_text == "SECRET-PROMPT-TEXT"
    assert "SECRET-PROMPT-TEXT" not in request.argv


def test_mandatory_flags_always_present():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake)
    argv = fake.requests[0].argv
    assert argv[0] == "claude"
    assert "-p" in argv
    assert "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json"
    assert "--no-session-persistence" in argv
    for forbidden in ("--bare", "--resume", "--continue", "--session-id", "--fork-session"):
        assert forbidden not in argv


def test_optional_flags_omitted_when_not_passed():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake)
    argv = fake.requests[0].argv
    assert "--model" not in argv
    assert "--max-budget-usd" not in argv
    assert "--fallback-model" not in argv


def test_optional_flags_present_when_passed():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless(
        "hi",
        model="claude-pinned-model",
        max_budget_usd=0.5,
        fallback_model="alt-model",
        runner=fake,
    )
    argv = fake.requests[0].argv
    assert argv[argv.index("--model") + 1] == "claude-pinned-model"
    assert argv[argv.index("--max-budget-usd") + 1] == "0.5"
    assert argv[argv.index("--fallback-model") + 1] == "alt-model"


def test_timeout_seconds_and_cwd_reach_the_request():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", timeout_seconds=42.0, cwd="/tmp", runner=fake)
    request = fake.requests[0]
    assert request.timeout_seconds == 42.0
    assert str(request.cwd) == "/tmp"


# ---------------------------------------------------------------------------
# The result taxonomy.
# ---------------------------------------------------------------------------


def test_success_three_way_conjunction():
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    result = invoke_headless("hi", runner=fake)
    assert isinstance(result, TransportResult)
    assert result.status == "ok"
    assert result.code == "ok"
    assert result.text == "OK"
    assert result.raw is not None and result.raw["is_error"] is False
    assert result.session_id == "8b62be4e-21c4-4f5e-af6d-2ebbf7299a89"


def test_subtype_success_quirk_never_alone_yields_success():
    """The step-04 §3.3b QUIRK: `subtype` stays "success" on a genuine API error —
    proving the classifier never keys off `subtype` alone."""
    fake = FakeRunner(outcome_ok(API_ERROR_JSON, returncode=1))
    result = invoke_headless("hi", runner=fake)
    payload = json.loads(API_ERROR_JSON)
    assert payload["subtype"] == "success"  # the quirk, restated as a guard
    assert result.status == "error"
    assert result.code == "api-error"
    assert result.api_error_status == 404
    assert result.remediation is None


def test_budget_exhausted_is_its_own_code_not_backpressure():
    fake = FakeRunner(outcome_ok(BUDGET_EXHAUSTED_JSON, returncode=1))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code == "budget-exhausted"
    assert result.text is None  # `.result` is documented OPTIONAL — absent here
    assert result.remediation is not None and result.remediation.action == "increase-budget"


def test_timeout_maps_to_the_timeout_code():
    fake = FakeRunner(ProcessOutcome(timed_out=True, returncode=None, stdout="", stderr=""))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code == "timeout"
    assert result.raw is None
    assert result.returncode is None


def test_malformed_output_unparseable_json():
    fake = FakeRunner(outcome_ok("not-json-at-all{", returncode=0))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code == "malformed-output"


def test_malformed_output_valid_json_but_not_an_object():
    fake = FakeRunner(outcome_ok("42", returncode=0))
    result = invoke_headless("hi", runner=fake)
    assert result.code == "malformed-output"


def test_malformed_output_missing_result_envelope_fields():
    fake = FakeRunner(outcome_ok(json.dumps({"hello": "world"}), returncode=0))
    result = invoke_headless("hi", runner=fake)
    assert result.code == "malformed-output"


def test_cli_arg_error_empty_stdout_nonzero_exit():
    fake = FakeRunner(
        ProcessOutcome(
            timed_out=False,
            returncode=1,
            stdout="",
            stderr="error: option '--output-format <format>' argument 'bogus' is invalid.",
        )
    )
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code == "cli-arg-error"
    assert result.raw is None
    assert "bogus" in (result.stderr or "")


def test_backpressure_via_unrecognized_is_error_shape():
    """Step-06 sheet item 5.8's literal directive: an unrecognized `is_error:true`
    shape (unknown `terminal_reason`) is treated as backpressure-eligible."""
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "usage_limit_exceeded_totally_unverified_shape",
    }
    fake = FakeRunner(outcome_ok(json.dumps(payload), returncode=1))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code == "rate-limit-backpressure"
    assert result.remediation is not None
    assert result.raw == payload  # raw JSON preserved for steps 37-38 telemetry


def test_backpressure_via_keyword_scan_overrides_api_error_terminal_reason():
    """Even under `terminal_reason: api_error`, a recognizable rate/usage keyword in
    `errors[]` routes to backpressure, not the generic `api-error` code."""
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "api_error",
        "errors": ["Rate limit exceeded, please retry later"],
    }
    fake = FakeRunner(outcome_ok(json.dumps(payload), returncode=1))
    result = invoke_headless("hi", runner=fake)
    assert result.code == "rate-limit-backpressure"
    assert result.remediation.action == "reduce-width"  # no retry_after field present
    assert result.remediation.retry_after_seconds is None


def test_backpressure_extracts_retry_after_when_present():
    payload = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "terminal_reason": "rate_limited",
        "retry_after": 30,
    }
    fake = FakeRunner(outcome_ok(json.dumps(payload), returncode=1))
    result = invoke_headless("hi", runner=fake)
    assert result.code == "rate-limit-backpressure"
    assert result.remediation.action == "retry-after"
    assert result.remediation.retry_after_seconds == 30.0


def test_returncode_mismatch_never_silently_reported_ok():
    """`is_error: false` + `subtype: success` but a nonzero exit is NOT success — the
    three-way conjunction requires all three; the anomaly still routes somewhere loud."""
    payload = {"type": "result", "subtype": "success", "is_error": False, "result": "weird"}
    fake = FakeRunner(outcome_ok(json.dumps(payload), returncode=1))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "error"
    assert result.code != "ok"


def test_binary_not_found_is_a_typed_error():
    def raising_runner(request: ProcessRequest) -> ProcessOutcome:
        raise BinaryNotFoundError("binary-not-found: executable not found: 'claude'")

    with pytest.raises(BinaryNotFoundError):
        invoke_headless("hi", runner=raising_runner)


# ---------------------------------------------------------------------------
# The timeout < lease-TTL invariant (§22.3/§22.4) — cross-module pin.
# ---------------------------------------------------------------------------


def test_default_timeout_is_strictly_less_than_the_claim_lease_ttl():
    assert DEFAULT_TIMEOUT_SECONDS < claims_module.DEFAULT_LEASE_TTL_SECONDS


# ---------------------------------------------------------------------------
# The chokepoint CONTRACT: TransportPlan + CostAccumulator (plan G1, B1 fix).
# ---------------------------------------------------------------------------


def outcome_ok_cost(cost: float, *, returncode: int = 0) -> ProcessOutcome:
    """A success outcome whose parsed envelope carries a specific `total_cost_usd`."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": "OK",
            "total_cost_usd": cost,
            "terminal_reason": "completed",
        }
    )
    return ProcessOutcome(timed_out=False, returncode=returncode, stdout=payload, stderr="")


class SequenceRunner:
    """A recording process seam that returns a SCRIPTED outcome per call, in order."""

    def __init__(self, outcomes: list[ProcessOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        return self._outcomes[len(self.requests) - 1]


class _FiniteCapPlan:
    """A duck-typed stand-in for a FUTURE finite-per-call-cap plan — the G7 api-key variant is
    NOT built at G1, and a `subscription` `TransportPlan` refuses a finite cap (S-1). This
    exercises invoke_headless's `min(caller, per_call_cap)` MECHANISM in isolation;
    invoke_headless reads only `.per_call_cap` and `.cost_accumulator`."""

    def __init__(self, per_call_cap: float, cost_accumulator: CostAccumulator) -> None:
        self.per_call_cap = per_call_cap
        self.cost_accumulator = cost_accumulator


# --- CostAccumulator ---------------------------------------------------------------------------


def test_cost_accumulator_sums_and_skips_none():
    acc = CostAccumulator()
    acc.add(1.25)
    acc.add(None)  # a costless outcome (timeout / cli-arg-error) — never fabricates a cost
    acc.add(2.75)
    assert acc.total == 4.0
    assert acc.calls == 2  # only the two real numeric contributions


def test_cost_accumulator_refuses_a_non_numeric_cost_loudly():
    acc = CostAccumulator()
    with pytest.raises(TransportError, match="cost contribution must be a number"):
        acc.add("0.50")  # type: ignore[arg-type]  # never silently coerce a malformed field
    with pytest.raises(TransportError):
        acc.add(True)  # type: ignore[arg-type]  # a bool is not a dollar amount


# --- TransportPlan (the subscription variant, S-1) ---------------------------------------------


def test_subscription_plan_carries_no_per_call_cap():
    plan = TransportPlan.subscription()
    assert plan.mode == "subscription"
    assert plan.per_call_cap is None  # S-1: flat-rate forces NO cap (no truncation)
    assert isinstance(plan.cost_accumulator, CostAccumulator)


def test_subscription_plan_refuses_a_finite_per_call_cap():
    """S-1: forcing a finite --max-budget-usd on the flat-rate subscription is a truncation
    regression + a design divergence — refused LOUDLY at construction."""
    with pytest.raises(TransportError, match="per_call_cap=None"):
        TransportPlan(mode="subscription", cost_accumulator=CostAccumulator(), per_call_cap=5.0)


# --- plan=None and plan=subscription are byte-identical to today (strip + F10) ------------------


def test_plan_none_and_subscription_plan_produce_identical_argv_and_env(monkeypatch):
    """`plan is None` and `plan.mode=="subscription"` (per_call_cap=None) are IDENTICAL TO EACH
    OTHER: the spawned argv + child env are byte-for-byte identical (no --max-budget-usd forced,
    the SAME G2 controlled-settings wall on both), and the returned result is the same. The plan
    only additionally ACCUMULATES. (Both are STRENGTHENED vs pre-G2 — see the wall asserts.)"""
    monkeypatch.setenv(ANTHROPIC_API_KEY_ENV, "sk-should-be-stripped")
    none_runner = FakeRunner(outcome_ok(SUCCESS_JSON))
    plan_runner = FakeRunner(outcome_ok(SUCCESS_JSON))
    plan = TransportPlan.subscription()

    r_none = invoke_headless("hi", runner=none_runner)
    r_plan = invoke_headless("hi", runner=plan_runner, plan=plan)

    req_none, req_plan = none_runner.requests[0], plan_runner.requests[0]
    assert req_plan.argv == req_none.argv
    assert "--max-budget-usd" not in req_plan.argv  # per_call_cap=None forces NOTHING
    assert dict(req_plan.env) == dict(req_none.env)
    # F10 strip fires on the subscription-plan path exactly as with plan=None.
    assert ANTHROPIC_API_KEY_ENV not in req_plan.env
    assert req_plan.env[DISABLE_AUTO_MEMORY_ENV] == "1"
    # G2: both paths carry the controlled-settings wall identically (strengthened vs pre-G2):
    # --settings <controlled-file> + --setting-sources "" (excludes ambient sources), no --bare.
    assert "--settings" in req_plan.argv and "--bare" not in req_plan.argv
    assert req_plan.argv[req_plan.argv.index("--setting-sources") + 1] == ""
    # The returned result is identical; the plan only additionally accumulates the cost.
    assert r_plan == r_none
    assert plan.cost_accumulator.total == r_plan.total_cost_usd


def test_subscription_plan_still_refuses_an_injected_api_key():
    """F10 is unchanged under a plan: an explicit ANTHROPIC_API_KEY override still refuses."""
    plan = TransportPlan.subscription()
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    with pytest.raises(ApiKeyPresentError):
        invoke_headless(
            "hi", runner=fake, plan=plan, env_overrides={ANTHROPIC_API_KEY_ENV: "sk-x"}
        )
    assert fake.call_count == 0  # refused BEFORE any spawn
    assert plan.cost_accumulator.total == 0.0  # and nothing accumulated


# --- accumulate on EVERY call — the run total, not the last call (the B1 fix) -------------------


def test_accumulator_captures_the_run_total_across_every_call_not_the_last():
    """The core B1 fix: threading ONE plan across many calls sums EVERY call's cost — the run
    total — never the last-call-only value the pre-fix driver read."""
    plan = TransportPlan.subscription()
    costs = [0.10, 0.20, 0.05, 0.40]  # writer, Review-1, reconcile, Review-2 (illustrative)
    runner = SequenceRunner([outcome_ok_cost(c) for c in costs])
    for _ in costs:
        invoke_headless("hi", runner=runner, plan=plan)
    assert plan.cost_accumulator.total == pytest.approx(sum(costs))
    assert plan.cost_accumulator.total != costs[-1]  # NOT the last call only
    assert plan.cost_accumulator.calls == len(costs)


def test_no_plan_means_no_accumulation_and_todays_behavior():
    """`plan=None` is untouched: no accumulator to feed, argv/env/result as before."""
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    result = invoke_headless("hi", runner=fake)
    assert result.status == "ok"
    assert "--max-budget-usd" not in fake.requests[0].argv


def test_a_costless_outcome_contributes_nothing_but_still_counts_the_call_as_zero():
    """A timeout / cli-arg-error carries total_cost_usd=None; the accumulator adds nothing and
    does not fabricate a cost."""
    plan = TransportPlan.subscription()
    timeout = ProcessOutcome(timed_out=True, returncode=None, stdout="", stderr="killed")
    runner = SequenceRunner([timeout, outcome_ok_cost(0.30)])
    invoke_headless("hi", runner=runner, plan=plan)  # timeout → cost None
    invoke_headless("hi", runner=runner, plan=plan)  # ok → 0.30
    assert plan.cost_accumulator.total == pytest.approx(0.30)
    assert plan.cost_accumulator.calls == 1  # only the real numeric contribution


# --- the min(caller, per_call_cap) mechanism (guarded so per_call_cap=None forces nothing) ------


def test_per_call_cap_none_forces_no_max_budget_flag():
    """The subscription path (per_call_cap=None) forces NO --max-budget-usd even when the caller
    also passes none — no artifact truncation (S-1)."""
    plan = TransportPlan.subscription()
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake, plan=plan)
    assert "--max-budget-usd" not in fake.requests[0].argv


def test_finite_cap_forces_the_flag_when_caller_passes_none():
    plan = _FiniteCapPlan(per_call_cap=5.0, cost_accumulator=CostAccumulator())
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake, plan=plan)
    argv = fake.requests[0].argv
    assert argv[argv.index("--max-budget-usd") + 1] == "5.0"


def test_finite_cap_takes_the_min_with_a_larger_caller_budget():
    plan = _FiniteCapPlan(per_call_cap=5.0, cost_accumulator=CostAccumulator())
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake, plan=plan, max_budget_usd=10.0)
    argv = fake.requests[0].argv
    assert argv[argv.index("--max-budget-usd") + 1] == "5.0"  # min(10.0, 5.0)


def test_finite_cap_keeps_a_smaller_caller_budget():
    plan = _FiniteCapPlan(per_call_cap=5.0, cost_accumulator=CostAccumulator())
    fake = FakeRunner(outcome_ok(SUCCESS_JSON))
    invoke_headless("hi", runner=fake, plan=plan, max_budget_usd=3.0)
    argv = fake.requests[0].argv
    assert argv[argv.index("--max-budget-usd") + 1] == "3.0"  # min(3.0, 5.0)


# ---------------------------------------------------------------------------
# The live smoke test — the ONLY place the real subscription transport runs
# (`@pytest.mark.live`, deselected by default per PA-5 / pyproject addopts).
# ---------------------------------------------------------------------------

needs_claude_binary = pytest.mark.skipif(
    shutil.which("claude") is None, reason="claude binary absent from PATH"
)


@pytest.mark.live
@needs_claude_binary
def test_live_invoke_headless_returns_structured_output_on_subscription_auth():
    """Real `claude -p --output-format json` call, subscription-authenticated (gate G5).

    No explicit env handling needed here: `invoke_headless`'s own F10 strip removes
    `ANTHROPIC_API_KEY` from the child env unconditionally, so this is equivalent to the
    gate probe's `env -u ANTHROPIC_API_KEY` invocation by construction.
    """
    result = invoke_headless("Reply with exactly: TRANSPORT-LIVE-OK", timeout_seconds=60.0)
    assert result.status == "ok"
    assert result.code == "ok"
    assert isinstance(result.text, str)
    assert "TRANSPORT-LIVE-OK" in result.text
    assert result.raw is not None
    assert result.raw.get("is_error") is False
    assert result.session_id
