"""ConstructionBudget — the generation run's worst-case spend CEILING (plan G1, §21.10).

The paid analog of `pipeline.sources.control.ResearchBudget` (control.py:203-289): a pure
dataclass holding only ceiling MATH. It issues no LLM call, imports no transport, and knows
nothing about the paid CLI gate — it computes the TRUE worst-case total-call budget a full
generation run can spend, so a paid gate's disclosed `≤ $C` is ALWAYS ≥ every possible
actual spend (never an understatement, § money-safety disclosure).

**The ceiling formula (S-5).** Over a resolved plan of `N` artifacts fanning out to `M`
deliverables total:

    ceiling = per_call × [ Σ_artifacts( writer×A_c + Review1×A_r )
                         + Σ_deliverables( reconcile×A_k + Review2×A_r ) ]
            = per_call × [ N×(A_c + A_r) + M×(A_k + A_r) ]

where `A_c`/`A_r`/`A_k` are the per-stage bounded-re-ask caps — the live `DEFAULT_MAX_ATTEMPTS`
IMPORTED from `pipeline.compose` / `pipeline.review` / `pipeline.reconcile`. **EVERY stage
carries its ×attempts multiplier — Review-1 INCLUDED, never a bare ×1** (a re-asking Review-1
spends up to `A_r` calls exactly like the writer and Review-2 do; folding it in as ×1 would
UNDERSTATE the ceiling). Because the loop caps bound every stage's call count, the total spend
can NEVER exceed the ceiling — the money wall is a construction property of the caps, not a
convention.

**The cross-module pin (S-5, mirrors the transport.py:129-133 timeout↔lease-TTL precedent).**
The ceiling math uses the LIVE stage constants, so it can never understate because of a stale
literal. In addition `verify_stage_attempts_pin()` pins the caps against `_ASSUMED_ATTEMPTS`
and fails LOUD if any stage's `DEFAULT_MAX_ATTEMPTS` has drifted from the value this ceiling's
derivation was reviewed against — a change to any stage cap is forced to be an explicit,
re-reviewed edit here, never a silent drift that quietly widens the true worst case.
"""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.compose import DEFAULT_MAX_ATTEMPTS as COMPOSE_MAX_ATTEMPTS
from pipeline.reconcile import DEFAULT_MAX_ATTEMPTS as RECONCILE_MAX_ATTEMPTS
from pipeline.review import DEFAULT_MAX_ATTEMPTS as REVIEW_MAX_ATTEMPTS

__all__ = [
    "COMPOSE_MAX_ATTEMPTS",
    "RECONCILE_MAX_ATTEMPTS",
    "REVIEW_MAX_ATTEMPTS",
    "ConstructionBudget",
    "ConstructionBudgetError",
    "verify_stage_attempts_pin",
]


class ConstructionBudgetError(RuntimeError):
    """A ConstructionBudget met a state it must refuse loudly, never guess through (§3.1)."""

    code = "construction-budget-error"


#: The per-stage re-ask caps the ceiling formula was DERIVED and REVIEWED against (S-5).
#: `writer` = compose.DEFAULT_MAX_ATTEMPTS (A_c); `review` = review.DEFAULT_MAX_ATTEMPTS (A_r,
#: covering BOTH Review-1 and Review-2); `reconcile` = reconcile.DEFAULT_MAX_ATTEMPTS (A_k).
#: The live constants are IMPORTED (not re-declared) so the ceiling MATH always uses the
#: current caps; this pinned copy exists so `verify_stage_attempts_pin` can fail LOUD when a
#: stage cap drifts, forcing an explicit re-derivation + re-review rather than a silent widen.
_ASSUMED_ATTEMPTS: dict[str, int] = {
    "writer": 3,
    "review": 3,
    "reconcile": 3,
}


def verify_stage_attempts_pin() -> None:
    """Fail LOUD if any stage's live `DEFAULT_MAX_ATTEMPTS` has drifted from `_ASSUMED_ATTEMPTS`.

    The cross-module inequality pin (mirrors transport.py:129-133): a change to compose's,
    review's, or reconcile's re-ask cap widens the true worst-case spend, so it MUST be
    acknowledged here (update `_ASSUMED_ATTEMPTS` + re-review the ceiling derivation) rather
    than silently drifting the disclosed ceiling away from reality. Reads the module globals at
    CALL time, so a test can simulate a drift by patching one of the `*_MAX_ATTEMPTS` names.
    """
    live = {
        "writer": COMPOSE_MAX_ATTEMPTS,
        "review": REVIEW_MAX_ATTEMPTS,
        "reconcile": RECONCILE_MAX_ATTEMPTS,
    }
    drift = {
        stage: (assumed, live[stage])
        for stage, assumed in _ASSUMED_ATTEMPTS.items()
        if live[stage] != assumed
    }
    if drift:
        raise ConstructionBudgetError(
            "construction-budget-error: a stage's DEFAULT_MAX_ATTEMPTS drifted from the "
            f"ceiling's pinned assumption {drift!r} (stage -> (assumed, live)) — the "
            "ConstructionBudget ceiling would MIS-STATE the worst-case spend. Update "
            "`_ASSUMED_ATTEMPTS` to the new caps AND re-derive/re-review the ceiling "
            "(never a silent drift; the disclosed ceiling must never understate, S-5)."
        )


@dataclass(frozen=True)
class ConstructionBudget:
    """One generation run's worst-case spend envelope (plan G1) — the paid gate's `≤ $C`.

    `per_call_usd` is the per-LLM-call `--max-budget-usd` cap. It is **None** on the flat-rate
    SUBSCRIPTION path (S-1: the subscription forces no finite per-call cap, so there is no
    finite dollar ceiling — the call-count scope is disclosed instead); it is a FINITE dollar
    amount only on the G7 api-key path, where `per_call × total_call_budget` becomes the true
    money wall. `n_artifacts`/`n_deliverables` come straight from the resolved plan
    (`len(plan.items)` / `len(plan.deliverable_ids())`).
    """

    per_call_usd: float | None
    n_artifacts: int
    n_deliverables: int

    def __post_init__(self) -> None:
        # A drift in any stage cap would make this ceiling understate — refuse to build one
        # (and thus to disclose one) until the pin is acknowledged (S-5).
        verify_stage_attempts_pin()
        for label, value in (
            ("n_artifacts", self.n_artifacts),
            ("n_deliverables", self.n_deliverables),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConstructionBudgetError(
                    f"construction-budget-error: {label} must be a non-negative integer, "
                    f"got {value!r}"
                )
        if self.n_artifacts < 1:
            raise ConstructionBudgetError(
                "construction-budget-error: n_artifacts must be >= 1 (a run with no artifacts "
                f"spends nothing and needs no ceiling), got {self.n_artifacts!r}"
            )
        if self.per_call_usd is not None and (
            isinstance(self.per_call_usd, bool)
            or not isinstance(self.per_call_usd, int | float)
            or float(self.per_call_usd) <= 0.0
        ):
            raise ConstructionBudgetError(
                "construction-budget-error: per_call_usd must be None (the subscription "
                "flat-rate path, no per-call $ cap) or a positive dollar amount (the "
                f"per-LLM-call --max-budget-usd cap), got {self.per_call_usd!r}"
            )

    @property
    def total_call_budget(self) -> int:
        """The worst-case COUNT of per-call-capped LLM calls a full run can make (S-5):
        `N×(A_c + A_r) + M×(A_k + A_r)` — writer×A_c + Review-1×A_r per artifact, plus
        reconcile×A_k + Review-2×A_r per deliverable. EVERY stage carries its ×attempts
        multiplier; Review-1 is folded in at ×A_r, never a bare ×1."""
        per_artifact = COMPOSE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS
        per_deliverable = RECONCILE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS
        return self.n_artifacts * per_artifact + self.n_deliverables * per_deliverable

    @property
    def ceiling_usd(self) -> float | None:
        """The HARD worst-case TOTAL $ ceiling `per_call_usd × total_call_budget` — the paid
        gate's disclosed `≤ $C`, always >= every possible actual spend. **None** when
        `per_call_usd` is None (the subscription flat-rate path — no per-call $ cap, so there
        is no finite dollar ceiling; the call-count scope stands in). Finite only on the G7
        api-key path."""
        if self.per_call_usd is None:
            return None
        return self.total_call_budget * float(self.per_call_usd)

    def construction_scope(self) -> str:
        """The one-line run-start disclosure — a bounded worst-case CEILING, never an exact bill.

        Finite per-call cap (api-key, G7): `construction-scope: ≤ $C over N artifacts / M
        deliverables (≤ K calls)`. Flat-rate subscription (`per_call_usd is None`, S-1):
        `construction-scope: subscription flat-rate — no per-call $ cap; ≤ K calls over N
        artifacts / M deliverables`. Either way `$C`/`K` is the TRUE worst case (×attempts at
        every stage), so the number a paid gate approves is never undershot."""
        calls = self.total_call_budget
        if self.per_call_usd is None:
            return (
                "construction-scope: subscription flat-rate — no per-call $ cap; "
                f"≤ {calls} calls over {self.n_artifacts} artifacts / "
                f"{self.n_deliverables} deliverables"
            )
        ceiling = self.ceiling_usd
        assert ceiling is not None  # per_call_usd is not None here
        return (
            f"construction-scope: ≤ ${ceiling:.2f} over {self.n_artifacts} artifacts "
            f"/ {self.n_deliverables} deliverables (≤ {calls} calls)"
        )
