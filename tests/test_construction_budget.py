"""ConstructionBudget — the generation run's worst-case spend ceiling (plan G1, §21.10).

Proves the ceiling formula carries the ×attempts multiplier at EVERY stage (Review-1 INCLUDED,
never a bare ×1 — S-5), that the ceiling is always >= the true worst case (never an
understatement), and that the cross-module import-and-pin FAILS LOUD when any stage's
`DEFAULT_MAX_ATTEMPTS` drifts from the value the ceiling's derivation was reviewed against
(mirroring the transport.py:129-133 timeout↔lease-TTL inequality precedent). No spend anywhere —
pure ceiling MATH.
"""

from __future__ import annotations

import pytest

import pipeline.compose as compose
import pipeline.reconcile as reconcile
import pipeline.review as review
from pipeline.spend import construction
from pipeline.spend.construction import (
    COMPOSE_MAX_ATTEMPTS,
    RECONCILE_MAX_ATTEMPTS,
    REVIEW_MAX_ATTEMPTS,
    ConstructionBudget,
    ConstructionBudgetError,
    verify_stage_attempts_pin,
)

# --- the ceiling formula (S-5: ×attempts at EVERY stage, Review-1 included) -------------------


def test_the_imported_caps_are_the_live_stage_constants():
    """The ceiling uses the LIVE `DEFAULT_MAX_ATTEMPTS` of each stage (imported, not a re-declared
    literal) — so a cap change propagates into the math, never leaving a stale understatement."""
    assert COMPOSE_MAX_ATTEMPTS == compose.DEFAULT_MAX_ATTEMPTS
    assert REVIEW_MAX_ATTEMPTS == review.DEFAULT_MAX_ATTEMPTS
    assert RECONCILE_MAX_ATTEMPTS == reconcile.DEFAULT_MAX_ATTEMPTS


def test_single_artifact_no_deliverable_folds_review1_at_full_attempts_not_one():
    """One artifact, zero deliverables: the worst case is writer×A_c + Review-1×A_r. Review-1 is
    folded in at its FULL re-ask cap A_r — NOT a bare ×1 (S-5: a re-asking Review-1 spends up to
    A_r calls exactly like the writer)."""
    budget = ConstructionBudget(per_call_usd=1.0, n_artifacts=1, n_deliverables=0)
    assert budget.total_call_budget == COMPOSE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS
    # The bug S-5 guards against: folding Review-1 in as ×1 would undercount by (A_r − 1).
    assert budget.total_call_budget != COMPOSE_MAX_ATTEMPTS + 1
    assert REVIEW_MAX_ATTEMPTS > 1  # otherwise the ×1 vs ×A_r distinction is vacuous


def test_each_deliverable_adds_reconcile_and_review2_at_full_attempts():
    """Each deliverable adds reconcile×A_k + Review-2×A_r — both at their FULL re-ask caps."""
    base = ConstructionBudget(per_call_usd=1.0, n_artifacts=1, n_deliverables=0).total_call_budget
    one = ConstructionBudget(per_call_usd=1.0, n_artifacts=1, n_deliverables=1).total_call_budget
    assert one - base == RECONCILE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS


@pytest.mark.parametrize(
    ("n_artifacts", "n_deliverables"),
    [(1, 1), (1, 3), (2, 2), (4, 10), (3, 0)],
)
def test_total_call_budget_matches_the_closed_form(n_artifacts, n_deliverables):
    """`N×(A_c + A_r) + M×(A_k + A_r)` — the exact S-5 closed form."""
    expected = (
        n_artifacts * (COMPOSE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS)
        + n_deliverables * (RECONCILE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS)
    )
    budget = ConstructionBudget(
        per_call_usd=1.0, n_artifacts=n_artifacts, n_deliverables=n_deliverables
    )
    assert budget.total_call_budget == expected


def test_ceiling_usd_is_per_call_times_the_call_budget():
    budget = ConstructionBudget(per_call_usd=0.5, n_artifacts=2, n_deliverables=3)
    assert budget.ceiling_usd == 0.5 * budget.total_call_budget


def test_ceiling_never_understates_a_worst_case_run():
    """The disclosed ceiling >= the count of stages a run could touch even if EVERY stage re-asked
    its full cap — so the number a paid gate approves is never undershot (§ money-safety)."""
    per_call = 0.25
    n_artifacts, n_deliverables = 2, 4
    budget = ConstructionBudget(
        per_call_usd=per_call, n_artifacts=n_artifacts, n_deliverables=n_deliverables
    )
    # A run that spends per_call on EVERY worst-case call reaches exactly the ceiling; any real run
    # (fewer re-asks, a zero-LLM `pass` reconcile) spends strictly less.
    worst_case_actual = per_call * budget.total_call_budget
    assert budget.ceiling_usd == pytest.approx(worst_case_actual)
    assert budget.ceiling_usd >= worst_case_actual


# --- the subscription flat-rate path (S-1: no per-call $ cap) ---------------------------------


def test_subscription_flat_rate_has_no_finite_dollar_ceiling():
    budget = ConstructionBudget(per_call_usd=None, n_artifacts=1, n_deliverables=1)
    assert budget.ceiling_usd is None
    scope = budget.construction_scope()
    assert "subscription flat-rate" in scope
    assert "no per-call $ cap" in scope
    assert f"≤ {budget.total_call_budget} calls" in scope
    assert "≤ $" not in scope  # no dollar CEILING figure on the flat-rate path


def test_finite_cap_discloses_a_dollar_ceiling():
    budget = ConstructionBudget(per_call_usd=0.5, n_artifacts=2, n_deliverables=3)
    scope = budget.construction_scope()
    assert scope.startswith("construction-scope: ≤ $")
    assert f"${budget.ceiling_usd:.2f}" in scope
    assert f"≤ {budget.total_call_budget} calls" in scope


# --- the cross-module import-and-pin (S-5: fail LOUD on a stage-cap drift) ---------------------


def test_verify_pin_passes_with_the_live_constants():
    """No drift today: the live caps match the pinned assumption, so the pin is silent."""
    verify_stage_attempts_pin()  # must not raise
    assert construction._ASSUMED_ATTEMPTS == {
        "writer": compose.DEFAULT_MAX_ATTEMPTS,
        "review": review.DEFAULT_MAX_ATTEMPTS,
        "reconcile": reconcile.DEFAULT_MAX_ATTEMPTS,
    }


@pytest.mark.parametrize(
    ("attr", "stage"),
    [
        ("COMPOSE_MAX_ATTEMPTS", "writer"),
        ("REVIEW_MAX_ATTEMPTS", "review"),
        ("RECONCILE_MAX_ATTEMPTS", "reconcile"),
    ],
)
def test_verify_pin_fails_loud_when_a_stage_cap_drifts(monkeypatch, attr, stage):
    """Simulate ANY stage's `DEFAULT_MAX_ATTEMPTS` drifting past the ceiling's pinned assumption:
    the cross-module pin must FAIL LOUD (never silently widen the true worst case)."""
    live = getattr(construction, attr)
    monkeypatch.setattr(construction, attr, live + 5)
    with pytest.raises(ConstructionBudgetError, match="drifted from"):
        verify_stage_attempts_pin()
    # And a drift makes a ConstructionBudget refuse to build (so it can never DISCLOSE a stale,
    # understated ceiling): __post_init__ runs the same pin.
    with pytest.raises(ConstructionBudgetError, match="drifted from"):
        ConstructionBudget(per_call_usd=1.0, n_artifacts=1, n_deliverables=1)


def test_drift_message_names_the_stage_and_both_values(monkeypatch):
    monkeypatch.setattr(construction, "REVIEW_MAX_ATTEMPTS", 7)
    with pytest.raises(ConstructionBudgetError) as excinfo:
        verify_stage_attempts_pin()
    msg = str(excinfo.value)
    assert "review" in msg
    assert "7" in msg  # the drifted live value
    assert "construction-budget-error" in msg


# --- validation (mirrors ResearchBudget's typed range refusals) -------------------------------


def test_n_artifacts_must_be_at_least_one():
    with pytest.raises(ConstructionBudgetError, match="n_artifacts must be >= 1"):
        ConstructionBudget(per_call_usd=1.0, n_artifacts=0, n_deliverables=0)


def test_negative_deliverables_refused():
    with pytest.raises(ConstructionBudgetError, match="non-negative integer"):
        ConstructionBudget(per_call_usd=1.0, n_artifacts=1, n_deliverables=-1)


def test_zero_or_negative_per_call_refused():
    with pytest.raises(ConstructionBudgetError, match="per_call_usd"):
        ConstructionBudget(per_call_usd=0.0, n_artifacts=1, n_deliverables=1)


def test_boolean_counts_are_refused_not_coerced():
    # `True`/`False` are ints in Python — a budget must refuse them, never treat them as 1/0.
    with pytest.raises(ConstructionBudgetError):
        ConstructionBudget(per_call_usd=1.0, n_artifacts=True, n_deliverables=1)
    with pytest.raises(ConstructionBudgetError):
        ConstructionBudget(per_call_usd=True, n_artifacts=1, n_deliverables=1)
