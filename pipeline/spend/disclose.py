"""The pre-spend COST DISCLOSURE line (plan G8, §21.10) — a read-only money-safety projection.

Before every PAID run (and on a dry-run/preview, which admits + spends NOTHING) the operator sees
ONE clear line naming: the resolved transport MODE (subscription / api-key `<handle>`), the
bucket/SCOPE it charges (e.g. `zone:dave/work`), the worst-case CONSTRUCTION-SCOPE ceiling (the
`ConstructionBudget` `≤ $C` — per-call-cap × the ×attempts-per-stage call budget, S-5, ALWAYS ≥
every possible actual spend), and the HEADROOM (`cap − week-to-date`, where week-to-date = settled
ledger + all live holds, for BOTH the assignment bucket and the install umbrella). It mirrors the
sources `ResearchBudget.acquire_scope` one-liner (control.py:281): a bounded CEILING, never an exact
bill.

`TransportDisclosure` is a PURE value object — it holds the already-resolved decision + the meter's
already-read week-to-date totals and renders the line. It issues no LLM call, resolves no secret,
touches no meter, and admits nothing; the READ-ONLY producers live in `pipeline.spend.resolve`
(`AdmittedTransport.disclose` reflects a REAL admitted plan; `preview_transport` builds the same
line for a dry-run WITHOUT admitting). It shows the HANDLE only — a `SecretRef` carries no secret
value (I5), so a disclosure can never leak a key.

Import boundary: this module imports ONLY the pure spend value types (`assignment.ScopeKey`,
`keystore.SecretRef`, `construction.ConstructionBudget`). It imports NOTHING from `resolve`/`meter`/
`transport`, so `resolve` may import it with no cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pipeline.spend.assignment import ScopeKey
from pipeline.spend.construction import ConstructionBudget
from pipeline.spend.keystore import SecretRef

__all__ = [
    "MODE_APIKEY",
    "MODE_SUBSCRIPTION",
    "TransportDisclosure",
    "format_scope",
]

#: The disclosed transport modes — the SAME tokens `pipeline.transport.TransportMode` /
#: `TransportPlan.mode` carry (a subscription plan discloses no `$` ceiling; an api-key plan
#: discloses the finite ceiling + headroom).
MODE_SUBSCRIPTION = "subscription"
MODE_APIKEY = "apikey"

#: The single-line disclosure PREFIX (a stable, greppable money-safety marker).
_PREFIX = "cost-disclosure"


def format_scope(scope: ScopeKey) -> str:
    """Render a `ScopeKey` as the canonical `<level>:<scope_id>` bucket label (e.g.
    `zone:dave/work`, `global:install`) — the SAME shape `transport list-keys` / the meter bucket
    descriptor use, so the disclosed bucket reads identically to the assignment it charges."""
    return f"{scope.level}:{scope.scope_id}"


def _headroom(cap: Decimal, week_to_date: Decimal) -> Decimal:
    """`cap − week_to_date`, floored at 0 (a fully-consumed or over-held bucket discloses `$0.00`
    remaining, never a negative). `week_to_date` is settled + all live holds — so on a PAID run the
    headroom already reflects THIS run's reservation; on a dry-run it is the pre-run headroom."""
    remaining = cap - week_to_date
    return remaining if remaining > 0 else Decimal("0")


@dataclass(frozen=True)
class TransportDisclosure:
    """The resolved, pre-spend cost disclosure for ONE run — a pure value object (plan G8).

    - subscription: `mode=MODE_SUBSCRIPTION`, `budget.per_call_usd is None` (flat-rate). No bucket,
      no handle, no `$` ceiling, no headroom (subscription is not metered here) — the line discloses
      the flat-rate mode + the call-count scope only.
    - api-key: `mode=MODE_APIKEY` with the charged `scope` + `handle` (the NON-secret `SecretRef`),
      the finite-cap `budget` (its `ceiling_usd` is the disclosed `≤ $C`), and the bucket + umbrella
      `cap`/`week_to_date` pairs that yield the headroom clause.

    `line()` renders the single disclosure string (mirrors `ResearchBudget.acquire_scope`)."""

    mode: str
    budget: ConstructionBudget
    scope: ScopeKey | None = None
    handle: SecretRef | None = None
    bucket_cap: Decimal | None = None
    bucket_week_to_date: Decimal | None = None
    umbrella_cap: Decimal | None = None
    umbrella_week_to_date: Decimal | None = None

    def _headroom_clause(self) -> str | None:
        """The `headroom: bucket … / umbrella …` clause, or `None` when the caps/totals are absent
        (the subscription path — nothing is metered, so there is no dollar headroom to disclose)."""
        if (
            self.bucket_cap is None
            or self.bucket_week_to_date is None
            or self.umbrella_cap is None
            or self.umbrella_week_to_date is None
        ):
            return None
        bucket_left = _headroom(self.bucket_cap, self.bucket_week_to_date)
        umbrella_left = _headroom(self.umbrella_cap, self.umbrella_week_to_date)
        return (
            f"headroom: bucket ${bucket_left:.2f} of ${self.bucket_cap:.2f} / "
            f"umbrella ${umbrella_left:.2f} of ${self.umbrella_cap:.2f}"
        )

    def line(self) -> str:
        """The single pre-spend disclosure line (a bounded CEILING + headroom, never an exact bill).

        subscription → `cost-disclosure: mode=subscription (flat-rate — no per-call $ ceiling) · S`.
        api-key      → `cost-disclosure: mode=api-key <handle> · bucket=<bucket> · S · <headroom>`,
        where `S` is `ConstructionBudget.construction_scope()` (the `≤ $C` worst case, S-5)."""
        if self.mode == MODE_SUBSCRIPTION:
            return (
                f"{_PREFIX}: mode=subscription (flat-rate — no per-call $ ceiling) · "
                f"{self.budget.construction_scope()}"
            )
        # api-key: name the mode + the NON-secret handle, the charged bucket, the ceiling, headroom.
        handle_label = self.handle.handle if self.handle is not None else "(unresolved)"
        bucket_label = format_scope(self.scope) if self.scope is not None else "(unresolved)"
        parts = [
            f"{_PREFIX}: mode=api-key {handle_label}",
            f"bucket={bucket_label}",
            self.budget.construction_scope(),
        ]
        clause = self._headroom_clause()
        if clause is not None:
            parts.append(clause)
        return " · ".join(parts)
