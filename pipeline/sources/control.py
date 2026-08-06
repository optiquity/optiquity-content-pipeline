"""The acquisition CONTROL loop: the per-class cost meter + the θ (theta) stop rule (sources P2).

An ingest run has a BUDGET. This module DEDUPES a fetched fact stream and admits only its NOVEL
facts, STOPPING when the budget is spent or the marginal novel-fact yield falls below θ — the honest
"diminishing returns" gate. It is the acquisition analog of the §6.3 grounding budget: **θ changes
HOW MUCH is cached, NEVER the identity of a cached fact.** Each fact's identity is its
content-addressed stable id (`cache.stable_fact_id`); the stop rule only bounds how many novel ones
one run admits, so a re-ingest of unchanged content admits zero and re-seals the SAME digest.

Cost is PER CLASS. For a FEED the cost that matters is bytes + requests + latency — a free-HTTP
courtesy budget, $0 model spend (no model call runs in acquisition; the ingest command is
out-of-band Tier-A). A later research class (P3) meters a different cost against the SAME
`CostMeter` seam.

The near-dup collapse (MinHash/SimHash) is a REGISTERED future θ input, not built here — v1 is
exact-id dedup, byte-parity with the sealed slice's own `stable_fact_id` (cache module docstring).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_RESEARCH_FAN_OUT",
    "DEFAULT_RESEARCH_K",
    "DEFAULT_RESEARCH_MAX_ROUNDS",
    "DEFAULT_RESEARCH_PER_CALL_USD",
    "DEFAULT_RESEARCH_THETA",
    "RESEARCH_STOP_REASONS",
    "STOP_BUDGET",
    "STOP_CEILING",
    "STOP_DRAINED",
    "STOP_REASONS",
    "STOP_THETA",
    "Budget",
    "ControlError",
    "CostMeter",
    "NoveltyOutcome",
    "ResearchBudget",
    "ResearchControl",
    "select_novel",
]

#: The θ stop-rule outcomes (why the admit loop halted) — a CLOSED, named vocabulary.
STOP_DRAINED = "source-drained"  # the whole fetched stream was consumed under budget
STOP_BUDGET = "budget-exhausted"  # the θ cost budget (max novel facts) filled; more novelty left
STOP_THETA = "novelty-below-theta"  # marginal novel-fact yield fell below θ (diminishing returns)
STOP_REASONS = (STOP_DRAINED, STOP_BUDGET, STOP_THETA)

#: The PAID research loop's extra halt reason (sources P3b): the hard round/fan-out ceiling was
#: reached — the loop ran its full `max_rounds` without the θ stop-rule or a source-drain firing
#: first. `STOP_DRAINED` (the planner/gap-finder proposed no more sub-queries) and `STOP_THETA`
#: (marginal novel-fact yield per dollar fell below θ for k rounds) are reused verbatim; together
#: they close the research vocabulary.
STOP_CEILING = "ceiling-reached"
RESEARCH_STOP_REASONS = (STOP_DRAINED, STOP_THETA, STOP_CEILING)

#: The GLOBAL default research budget (used when a descriptor sets none / only some fields). A
#: conservative 4 rounds × 3 fan-out × $0.50/call = a $6.00 synthesis ceiling; θ disabled by
#: default (ceiling + source-drain only), so a descriptor opts INTO the diminishing-returns stop.
DEFAULT_RESEARCH_MAX_ROUNDS = 4
DEFAULT_RESEARCH_FAN_OUT = 3
DEFAULT_RESEARCH_PER_CALL_USD = 0.50
DEFAULT_RESEARCH_THETA = 0.0
DEFAULT_RESEARCH_K = 2


class ControlError(ValueError):
    """A malformed acquisition budget — loud, typed, never a silent clamp."""

    code = "sources-control-error"


@dataclass(frozen=True)
class Budget:
    """One ingest run's acquisition budget (the θ stop-rule inputs).

    FEED class: the cost that matters is NOVEL facts admitted (a deterministic proxy for the
    bytes/requests a larger pull would cost). `max_facts` is the hard cap. `theta` is the MINIMUM
    marginal novelty RATE (novel / total over the trailing `window` of fetched facts) required to
    keep admitting; `0.0` (the default) never stops early on novelty — only the hard `max_facts` cap
    and stream exhaustion apply. A run that keeps seeing already-cached facts (re-fetch, mirror)
    drops below θ and halts, rather than pull a whole drained source for zero new facts.
    """

    max_facts: int
    theta: float = 0.0
    window: int = 20

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_facts, bool)
            or not isinstance(self.max_facts, int)
            or self.max_facts < 1
        ):
            raise ControlError(
                f"sources-control-error: budget max_facts must be a positive integer, "
                f"got {self.max_facts!r}"
            )
        if isinstance(self.theta, bool) or not isinstance(self.theta, int | float) or not (
            0.0 <= float(self.theta) <= 1.0
        ):
            raise ControlError(
                f"sources-control-error: budget theta is a novelty RATE in [0.0, 1.0], "
                f"got {self.theta!r}"
            )
        if isinstance(self.window, bool) or not isinstance(self.window, int) or self.window < 1:
            raise ControlError(
                f"sources-control-error: budget window must be a positive integer, "
                f"got {self.window!r}"
            )


@dataclass
class CostMeter:
    """The FEED-class cost meter: bytes + requests, $0 model spend.

    Accrued as a feed fetches (`record_response` per HTTP body) and surfaced in the ingest summary
    — the operator's spend view. For a feed this is a free-HTTP courtesy cost, never paid quota; the
    seam is shared with a future research/model class that would meter a different cost.
    """

    bytes: int = 0
    requests: int = 0

    def record_response(self, payload: bytes) -> None:
        """Record one fetched HTTP response body against the run's cost."""
        self.requests += 1
        self.bytes += len(payload)


@dataclass(frozen=True)
class NoveltyOutcome:
    """The result of dedup + θ-gating one fetched fact stream."""

    kept: tuple[Any, ...]  # the NOVEL facts admitted this run, in input order
    duplicates: int  # fetched facts collapsed as already-seen (exact-id dedup)
    fetched: int  # total facts examined (kept + duplicates, up to the stop point)
    stop_reason: str


def select_novel(
    facts: Sequence[Any],
    *,
    budget: Budget,
    seen_ids: set[str],
    stable_id: Callable[[Any], str],
) -> NoveltyOutcome:
    """Dedup + θ-gate a fetched fact stream into the novel set to admit (pure; no I/O).

    - **dedup:** a fact whose `stable_id` is already in `seen_ids` (already cached from a prior
      ingest, or an earlier duplicate this run) is COLLAPSED — never admitted, counted a duplicate.
      This is what makes a re-ingest of unchanged content admit zero novel facts (idempotency).
    - **budget:** admit novel facts until `max_facts`; a further novel fact halts the loop with
      `STOP_BUDGET` (the remaining stream is NOT admitted — θ caps how much, never fact identity).
    - **θ:** over each trailing `window` of FETCHED facts, if the novelty rate drops below `theta`,
      halt with `STOP_THETA` (diminishing returns; `theta=0.0` disables this).
    - **drained:** the whole stream consumed under budget → `STOP_DRAINED`.

    `seen_ids` is MUTATED (admitted ids are added) so callers may thread one set across sources.
    """
    kept: list[Any] = []
    duplicates = 0
    fetched = 0
    window: deque[bool] = deque(maxlen=budget.window)
    stop_reason = STOP_DRAINED
    for fact in facts:
        sid = stable_id(fact)
        is_novel = sid not in seen_ids
        if is_novel:
            if len(kept) >= budget.max_facts:
                stop_reason = STOP_BUDGET  # a novel fact remained but the budget is full
                break
            kept.append(fact)
            seen_ids.add(sid)
        else:
            duplicates += 1
        fetched += 1
        window.append(is_novel)
        if len(window) == budget.window and (sum(window) / len(window)) < budget.theta:
            stop_reason = STOP_THETA
            break
    return NoveltyOutcome(
        kept=tuple(kept), duplicates=duplicates, fetched=fetched, stop_reason=stop_reason
    )


# ---------------------------------------------------------------------------
# The PAID research class (sources P3b): the spend envelope + the per-round θ stop-rule.
#
# The FEED class above meters bytes/requests ($0 model spend). The RESEARCH class meters a real
# cost — subscription LLM tokens spent planning + synthesizing + gap-finding — so its budget is a
# HARD money wall, not a courtesy cap. This module holds only the budget MATH (a pure dataclass) and
# the θ streak TRACKER; it issues no LLM call, imports no transport, and knows nothing about the
# paid CLI gate. The loop that spends is the research feed (`pipeline.sources.feeds.research`).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchBudget:
    """The PAID research loop's spend envelope + θ stop-rule inputs (sources P3b).

    The HARD CEILING (`ceiling_usd`) is the TRUE worst-case TOTAL call budget the loop can spend:
    `per_call_usd × (1 plan + max_rounds×fan_out syntheses + (max_rounds−1) gap-finds)`. EVERY LLM
    call — plan, synthesis, gap-find — is capped at `per_call_usd` (the transport `--max-budget-usd`
    cap), and the loop issues AT MOST `fan_out` syntheses per round across AT MOST `max_rounds`
    rounds with a gap-find only BETWEEN rounds, so its TOTAL spend can NEVER exceed the ceiling —
    the money wall is a construction property of the round/fan-out caps, not a convention. What the
    paid
    gate approves (the disclosed `≤ $C`) is therefore ≥ every possible actual spend, NOT an
    understatement. `synth_ceiling_usd` is the synthesis-only SUB-ceiling (`max_rounds × fan_out ×
    per_call_usd`) — the dominant cost, reported separately.

    `theta` is the MINIMUM marginal novel-fact yield PER DOLLAR required to keep paying: when a
    round's `novel_facts / round_cost_usd` stays below `theta` for `k` CONSECUTIVE rounds, the loop
    halts on diminishing returns (`STOP_THETA`) — usually well under the ceiling. `theta = 0.0` (the
    default) DISABLES the θ-stop, leaving only the hard ceiling and source-drain. θ changes HOW MUCH
    the loop spends, NEVER the identity or tier of a cached lead (open web stays INFERRED).
    """

    max_rounds: int = DEFAULT_RESEARCH_MAX_ROUNDS
    fan_out: int = DEFAULT_RESEARCH_FAN_OUT
    per_call_usd: float = DEFAULT_RESEARCH_PER_CALL_USD
    theta: float = DEFAULT_RESEARCH_THETA
    k: int = DEFAULT_RESEARCH_K

    def __post_init__(self) -> None:
        for label, value in (
            ("max_rounds", self.max_rounds),
            ("fan_out", self.fan_out),
            ("k", self.k),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ControlError(
                    f"sources-control-error: research budget {label} must be a positive integer, "
                    f"got {value!r}"
                )
        if (
            isinstance(self.per_call_usd, bool)
            or not isinstance(self.per_call_usd, int | float)
            or float(self.per_call_usd) <= 0.0
        ):
            raise ControlError(
                "sources-control-error: research budget per_call_usd must be a positive dollar "
                f"amount (the per-LLM-call --max-budget-usd cap), got {self.per_call_usd!r}"
            )
        if (
            isinstance(self.theta, bool)
            or not isinstance(self.theta, int | float)
            or float(self.theta) < 0.0
        ):
            raise ControlError(
                "sources-control-error: research budget theta is a novel-facts-per-dollar floor "
                f">= 0.0 (0.0 disables the θ-stop), got {self.theta!r}"
            )

    @property
    def total_call_budget(self) -> int:
        """The worst-case COUNT of `per_call_usd`-capped LLM calls a full run can make: 1 plan +
        `max_rounds × fan_out` syntheses + `max_rounds − 1` gap-finds (a gap-find fires only BETWEEN
        rounds, never after the final one). This is the exact upper bound the loop's structure
        guarantees — every actual run makes at most this many calls."""
        return 1 + self.max_rounds * self.fan_out + (self.max_rounds - 1)

    @property
    def ceiling_usd(self) -> float:
        """The HARD, TRUE worst-case TOTAL spend ceiling: `per_call_usd × total_call_budget` (plan +
        syntheses + gap-finds). The disclosed `≤ $C` the paid gate approves — always ≥ every
        possible actual spend, never an understatement (§ money-safety disclosure)."""
        return self.total_call_budget * float(self.per_call_usd)

    @property
    def synth_ceiling_usd(self) -> float:
        """The synthesis-only SUB-ceiling `max_rounds × fan_out × per_call_usd` — the dominant cost,
        bounding just the page-synthesis spend (reported alongside the total for transparency)."""
        return self.max_rounds * self.fan_out * float(self.per_call_usd)

    def acquire_scope(self) -> str:
        """The one-line dry-run cost disclosure — a bounded CEILING (plan + synthesis + gap-find),
        never an exact bill: `acquire-scope: ≤ $C over ≤ R rounds × ≤ F fan-out (θ-stop earlier)`.
        `$C` is the TRUE total ceiling, so the number the paid gate approves is never undershot."""
        return (
            f"acquire-scope: ≤ ${self.ceiling_usd:.2f} over "
            f"≤ {self.max_rounds} rounds × ≤ {self.fan_out} fan-out "
            "(θ-stop usually earlier)"
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ResearchBudget:
        """Build a validated `ResearchBudget` from a descriptor's `budget:` sub-map (under the
        research feed's `connection:`), taking the GLOBAL default for any absent field; `None` (no
        `budget:` at all) yields the full default. A non-mapping value is refused LOUDLY."""
        if data is None:
            return cls()
        if not isinstance(data, Mapping):
            raise ControlError(
                "sources-control-error: research budget must be a map "
                "{max_rounds, fan_out, per_call_usd, theta?, k?}, got "
                f"{type(data).__name__}"
            )
        # Only the numeric COERCIONS may raise a non-numeric TypeError/ValueError; the `cls(...)`
        # construction is OUTSIDE the try so `__post_init__`'s typed range `ControlError` (e.g.
        # per_call_usd=0 — numeric but non-positive) propagates with its ACCURATE message intact,
        # never relabeled "non-numeric".
        try:
            max_rounds = int(data.get("max_rounds", DEFAULT_RESEARCH_MAX_ROUNDS))
            fan_out = int(data.get("fan_out", DEFAULT_RESEARCH_FAN_OUT))
            per_call_usd = float(data.get("per_call_usd", DEFAULT_RESEARCH_PER_CALL_USD))
            theta = float(data.get("theta", DEFAULT_RESEARCH_THETA))
            k = int(data.get("k", DEFAULT_RESEARCH_K))
        except (TypeError, ValueError) as exc:
            raise ControlError(
                f"sources-control-error: research budget has a non-numeric field: {exc}"
            ) from exc
        return cls(
            max_rounds=max_rounds, fan_out=fan_out, per_call_usd=per_call_usd, theta=theta, k=k
        )


@dataclass
class ResearchControl:
    """The per-round θ (diminishing-returns) stop-rule tracker for the paid research loop.

    After each round the loop reports (novel facts admitted, dollar cost of the round). `round_stop`
    returns `STOP_THETA` once the marginal novel-fact yield PER DOLLAR has stayed below
    `budget.theta` for `budget.k` CONSECUTIVE rounds — the honest "stop paying for repeats" gate. It
    tracks ONLY the θ streak; the round/fan-out ceiling is enforced by the loop itself. `theta <=
    0.0` disables the rule (the loop then halts only on the ceiling or a source-drain). Stateful and
    single-use per loop (mirrors the trailing-window state in `select_novel`)."""

    budget: ResearchBudget
    below_streak: int = 0

    def round_stop(self, *, novel: int, round_cost_usd: float) -> str | None:
        """Record one round's (novel-fact count, dollar cost); return `STOP_THETA` if the θ streak
        has reached `k`, else `None`. A zero-cost barren round counts as zero yield (below any
        positive θ). θ ≤ 0 short-circuits to `None` (the rule is disabled)."""
        if self.budget.theta <= 0.0:
            return None
        yield_per_usd = (novel / round_cost_usd) if round_cost_usd > 0.0 else 0.0
        if yield_per_usd < self.budget.theta:
            self.below_streak += 1
        else:
            self.below_streak = 0
        return STOP_THETA if self.below_streak >= self.budget.k else None
