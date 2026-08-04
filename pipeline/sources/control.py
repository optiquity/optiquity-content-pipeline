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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "STOP_BUDGET",
    "STOP_DRAINED",
    "STOP_REASONS",
    "STOP_THETA",
    "Budget",
    "ControlError",
    "CostMeter",
    "NoveltyOutcome",
    "select_novel",
]

#: The θ stop-rule outcomes (why the admit loop halted) — a CLOSED, named vocabulary.
STOP_DRAINED = "source-drained"  # the whole fetched stream was consumed under budget
STOP_BUDGET = "budget-exhausted"  # the θ cost budget (max novel facts) filled; more novelty left
STOP_THETA = "novelty-below-theta"  # marginal novel-fact yield fell below θ (diminishing returns)
STOP_REASONS = (STOP_DRAINED, STOP_BUDGET, STOP_THETA)


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
