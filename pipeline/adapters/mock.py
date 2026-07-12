"""The deterministic MOCK adapter (plan step 17): fixture facts behind the real contract.

Purpose (plan step 17): the M3 grounding resolver is built and branch-covered against
this adapter; step 18's real adapters (`graphify`, `folder`) implement the SAME
`pipeline.adapters.base` contract and must show fixture-driven parity with it.

Determinism guarantees (everything the resolver's reproducibility tests lean on):

- Facts are returned in authored dataset order, always.
- The query filter is a pure case-insensitive substring match over `subject` + `claim`
  (empty query = the whole dataset). No ambient state, no randomness, no clock.
- `built_at_commit` is a synthetic, content-derived hex digest per dataset — stable
  across runs, obviously fake (never a real repo's commit).

Fixture content is SYNTHETIC-GENERIC (CLAUDE.md rule 4: no client content anywhere in
the public framework): invented "widget/gadget service" claims, example.test URLs.
`default_datasets()` is the shared fixture seed — tests here and the step-18 parity
tests draw from one authored place.

Rule 1 posture: this adapter reads nothing at all (its data is constructor-supplied),
so the read-only contract holds vacuously — and structurally, like the contract itself.
"""

from __future__ import annotations

import datetime
import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from pipeline.adapters.base import (
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    TIER_INFERRED,
    AdapterError,
    Anchor,
    Fact,
    GroundingResult,
    SourceAdapter,
)

__all__ = ["MockAdapter", "default_datasets", "synthetic_commit"]


def synthetic_commit(dataset: str) -> str:
    """A deterministic, obviously-synthetic 40-hex 'commit' for one dataset name."""
    return hashlib.sha256(f"mock-dataset:{dataset}".encode()).hexdigest()[:40]


class MockAdapter(SourceAdapter):
    """`adapter: mock` — constructor-supplied datasets, selected by `connection.dataset`."""

    name = "mock"

    def __init__(
        self,
        datasets: Mapping[str, Sequence[Fact]] | None = None,
        *,
        commits: Mapping[str, str | None] | None = None,
    ) -> None:
        """`datasets` maps a dataset name → authored fact sequence (default: the shared
        `default_datasets()` fixtures). `commits` overrides the synthetic per-dataset
        commit (an explicit `None` value models an adapter kind with no commit notion)."""
        raw = default_datasets() if datasets is None else datasets
        self._datasets: dict[str, tuple[Fact, ...]] = {
            name: tuple(facts) for name, facts in raw.items()
        }
        self._commits = dict(commits) if commits is not None else {}

    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        if not isinstance(connection, Mapping):
            raise AdapterError(
                f"adapter-failure: mock connection must be a mapping, "
                f"got {type(connection).__name__}"
            )
        dataset = connection.get("dataset")
        if not isinstance(dataset, str) or not dataset:
            raise AdapterError(
                "adapter-failure: mock connection requires a non-empty `dataset` key "
                f"(got {dataset!r})"
            )
        facts = self._datasets.get(dataset)
        if facts is None:
            raise AdapterError(
                f"adapter-failure: unknown mock dataset {dataset!r} "
                f"(datasets: {sorted(self._datasets)})"
            )
        if not isinstance(query, str):
            raise AdapterError(
                f"adapter-failure: query must be a string, got {type(query).__name__}"
            )
        needle = query.strip().lower()
        if needle:
            facts = tuple(
                fact for fact in facts if needle in f"{fact.subject} {fact.claim}".lower()
            )
        if dataset in self._commits:
            commit = self._commits[dataset]
        else:
            commit = synthetic_commit(dataset)
        return GroundingResult(facts=facts, built_at_commit=commit)


def default_datasets() -> dict[str, tuple[Fact, ...]]:
    """The shared synthetic-generic fixture datasets (see the module docstring).

    Authored to exercise every resolver branch the plan names: agreement across
    datasets (corroboration §6.5), a factual-vs-opinion conflict and a factual-vs-
    factual conflict (§6.3 on_conflict), an EXTRACTED-but-anchorless fact (SM9
    tier ⟂ traceability), an INFERRED-but-anchored fact, an AMBIGUOUS fact, a stale
    fact (freshness §6.2), and a per-fact `review_status` refinement (G6).
    """
    return {
        # A first-party-style record of the invented "widget service".
        "alpha-docs": (
            Fact(
                subject="widget-service.timeout",
                claim="The widget service default timeout is 30 seconds.",
                tier=TIER_EXTRACTED,
                anchors=(Anchor("file-line", "src/widget/config.py:42"),),
                as_of=datetime.date(2026, 5, 1),
            ),
            Fact(
                subject="gadget-cache.capacity",
                claim="The gadget cache holds 512 entries.",
                tier=TIER_EXTRACTED,
                anchors=(Anchor("sha", "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"),),
                as_of=datetime.date(2026, 4, 20),
            ),
            Fact(
                subject="widget-service.retries",
                claim="The widget client retries failed calls three times.",
                tier=TIER_EXTRACTED,
                anchors=(),  # EXTRACTED yet anchor-less: SM9's canonical case
                as_of=datetime.date(2026, 4, 20),
            ),
        ),
        # An independent-review-style corpus: corroborates the timeout, refines review
        # state per fact, and carries an INFERRED-but-anchored fact.
        "gamma-review": (
            Fact(
                subject="widget-service.timeout",
                claim="The widget service default timeout is 30 seconds.",
                tier=TIER_INFERRED,
                anchors=(Anchor("url-fragment", "https://example.test/review#timeout"),),
                as_of=datetime.date(2026, 4, 15),
                refinements={"review_status": "formally-vetted"},
            ),
            Fact(
                subject="widget-service.protocol",
                claim="The widget service speaks the example wire protocol v2.",
                tier=TIER_INFERRED,
                anchors=(Anchor("url-fragment", "https://example.test/review#protocol"),),
                as_of=datetime.date(2026, 4, 15),
            ),
        ),
        # A research-notes-style corpus: opinionated, stale, and in conflict with the
        # record (gadget cache capacity) — plus an AMBIGUOUS lead.
        "delta-notes": (
            Fact(
                subject="gadget-cache.capacity",
                claim="The gadget cache holds 1024 entries.",
                tier=TIER_INFERRED,
                anchors=(Anchor("file-line", "notes/gadget-sizing.md:7"),),
                as_of=datetime.date(2024, 11, 3),
            ),
            Fact(
                subject="widget-service.roadmap",
                claim="The widget service may drop protocol v1 next quarter.",
                tier=TIER_AMBIGUOUS,
                anchors=(),
                as_of=datetime.date(2024, 11, 3),
            ),
        ),
        # A second record-style corpus that DISAGREES factually on the timeout — the
        # factual-vs-factual conflict seed.
        "beta-mirror": (
            Fact(
                subject="widget-service.timeout",
                claim="The widget service default timeout is 60 seconds.",
                tier=TIER_EXTRACTED,
                anchors=(Anchor("file-line", "mirror/widget/config.py:42"),),
                as_of=datetime.date(2026, 3, 1),
            ),
        ),
    }
