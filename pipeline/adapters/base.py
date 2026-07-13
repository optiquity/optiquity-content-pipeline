"""The source-adapter CONTRACT (design §6.1; plan step 17) — step 18 builds the real ones.

Design authority: `docs/design.md`
  §6.1 — a source is a pluggable, READ-ONLY grounding provider in two layers: the ADAPTER
         (type — `graphify`, `folder`, `url`, `pdf`, …) declaring query capabilities, and
         the SOURCE INSTANCE (bound config + characterization scores + a content-kind tag).
         The instance shape is config (`sources/_schema.yaml`); the adapter is CODE — this
         module is its contract.
  §6.2 — per-fact material the adapter supplies: the confidence TIER
         (EXTRACTED/INFERRED/AMBIGUOUS), traceability ANCHORS (file:line, SHA, URL
         fragment), the freshness basis (commit/mtime date), and optional per-fact
         REFINEMENTS of kind-tier scores "where the adapter classifies facts" (§6.1) —
         e.g. `review_status` refinement, degrading to `unknown` where the adapter exposes
         none (gate G6 disposition).
  §6.5 — tier ⟂ traceability (SM9): a fact can be EXTRACTED yet anchor-less, or INFERRED
         with a clean anchor. The contract therefore carries them independently.

Shape of record: the step-05 report §6 adapter-facing I/O contract (graphify v0.8.39, as
observed) — invocation = one query against one bound connection; output = facts, each with
a tier token and an optional source anchor; the graph's top-level `built_at_commit` (the
git SHA of the graphed checkout) feeds the §15 grounding ledger's source-commit field.
`GroundingResult.built_at_commit` is that field's carrier.

Durable rule 1 (CLAUDE.md): source/client repos are READ-ONLY, always. This contract
exposes no write primitive; step 18's adapters additionally assert their paths sit outside
this repo's workspaces and call only the read-only whitelist (step-05 report §6).

In-latitude decisions (step-17 coder; grounded in the report):

- **Refinement keys are validated by the RESOLVER, not here.** The per-fact-refinable
  score set is machine truth in `pipeline.m3` (the step-15 carry-forward's code-constant
  home); this contract stays below the grammar module in the import graph, so it checks
  shape only (a string-keyed mapping) and `pipeline.grounding` refuses unknown or
  non-refinable keys loudly at consume time.
- **Anchor kinds are the §6.2 closed v1 set** (`file-line`, `sha`, `url-fragment`) —
  exactly the resolvable-anchor examples the traceability score names. New kinds are a
  one-constant change here when a new adapter needs one.
- **`as_of` is a bare date** — freshness is date-granular by design (§6.2 date-window
  operators are calendar-level; cf. `pipeline/attrtypes.py` D2 discipline). Timestamps
  are refused, `None` = the adapter cannot derive a freshness basis.
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

__all__ = [
    "ANCHOR_KINDS",
    "AdapterError",
    "Anchor",
    "Fact",
    "GroundingResult",
    "SourceAdapter",
    "TIERS",
    "TIER_AMBIGUOUS",
    "TIER_EXTRACTED",
    "TIER_INFERRED",
    "tier_rank",
    "upgrade_tier",
]

#: The §6.2/§6.5 confidence tiers, ordered LOW → HIGH confidence. EXTRACTED is the
#: publish floor (§6.5 — a framework invariant, outside user config).
TIER_AMBIGUOUS = "AMBIGUOUS"
TIER_INFERRED = "INFERRED"
TIER_EXTRACTED = "EXTRACTED"
TIERS = (TIER_AMBIGUOUS, TIER_INFERRED, TIER_EXTRACTED)
_TIER_RANK = {tier: rank for rank, tier in enumerate(TIERS)}

#: §6.2 `traceability`: "a resolvable anchor — file:line, SHA, URL fragment". Closed v1 set.
ANCHOR_KINDS = ("file-line", "sha", "url-fragment")


class AdapterError(ValueError):
    """An adapter-side failure (step-05 report §6: any non-ok adapter outcome is
    `adapter-failure` with the adapter's first error line as the message)."""

    code = "adapter-failure"


def tier_rank(tier: str) -> int:
    """The tier's confidence rank (0 = AMBIGUOUS … 2 = EXTRACTED); unknown tiers refuse."""
    rank = _TIER_RANK.get(tier)
    if rank is None:
        raise AdapterError(
            f"adapter-failure: unknown confidence tier {tier!r} (§6.2 tiers: {', '.join(TIERS)})"
        )
    return rank


def upgrade_tier(tier: str) -> str:
    """One confidence level up (§6.5 corroboration upgrade); EXTRACTED stays EXTRACTED."""
    return TIERS[min(tier_rank(tier) + 1, len(TIERS) - 1)]


@dataclass(frozen=True)
class Anchor:
    """One resolvable traceability anchor (§6.2): kind + locator string."""

    kind: str
    value: str

    def __post_init__(self) -> None:
        if self.kind not in ANCHOR_KINDS:
            raise AdapterError(
                f"adapter-failure: unknown anchor kind {self.kind!r} "
                f"(§6.2 anchor kinds: {', '.join(ANCHOR_KINDS)})"
            )
        if not isinstance(self.value, str) or not self.value.strip():
            raise AdapterError(
                f"adapter-failure: anchor value must be a non-empty locator string, "
                f"got {self.value!r}"
            )


@dataclass(frozen=True)
class Fact:
    """One retrieved claim, as the adapter hands it to the resolver (§6.1 per-fact tier).

    `subject` is what the claim addresses — the resolver's conflict/agreement grouping
    key (§6.3/§6.5: two facts on one subject agree when their `claim` matches exactly and
    conflict when it differs). `refinements` carries per-fact refinements of kind-tier
    scores where the adapter classifies facts (§6.1); the resolver validates the keys
    against the `pipeline.m3` refinable set.
    """

    subject: str
    claim: str
    tier: str
    anchors: tuple[Anchor, ...] = ()
    as_of: datetime.date | None = None
    refinements: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (("subject", self.subject), ("claim", self.claim)):
            if not isinstance(value, str) or not value.strip():
                raise AdapterError(
                    f"adapter-failure: fact {label} must be a non-empty string, got {value!r}"
                )
        tier_rank(self.tier)  # refuses unknown tiers
        if not isinstance(self.anchors, tuple) or not all(
            isinstance(a, Anchor) for a in self.anchors
        ):
            raise AdapterError(
                "adapter-failure: fact anchors must be a tuple of Anchor values "
                f"(got {self.anchors!r})"
            )
        if self.as_of is not None:
            if isinstance(self.as_of, datetime.datetime) or not isinstance(
                self.as_of, datetime.date
            ):
                raise AdapterError(
                    "adapter-failure: fact as_of must be a bare date or None — freshness "
                    f"is date-granular (§6.2/D2), got {self.as_of!r}"
                )
        if not isinstance(self.refinements, Mapping) or not all(
            isinstance(k, str) for k in self.refinements
        ):
            raise AdapterError(
                "adapter-failure: fact refinements must be a string-keyed mapping "
                f"(got {self.refinements!r})"
            )


@dataclass(frozen=True)
class GroundingResult:
    """One adapter invocation's output: the facts + the source-commit ledger field.

    `built_at_commit` is the commit identifier of the grounded checkout (graphify:
    graph.json's top-level `built_at_commit`; step-05 report §6) — `None` when the
    adapter kind has no commit notion (e.g. a plain folder). It feeds each fact's
    per-fact instance+commit stamp in the §6.3 union step and the §15 grounding ledger.
    """

    facts: tuple[Fact, ...]
    built_at_commit: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.facts, tuple) or not all(isinstance(f, Fact) for f in self.facts):
            raise AdapterError(
                f"adapter-failure: GroundingResult.facts must be a tuple of Fact "
                f"(got {type(self.facts).__name__})"
            )
        if self.built_at_commit is not None and (
            not isinstance(self.built_at_commit, str) or not self.built_at_commit.strip()
        ):
            raise AdapterError(
                "adapter-failure: built_at_commit must be a non-empty string or None, "
                f"got {self.built_at_commit!r}"
            )


class SourceAdapter(ABC):
    """The adapter contract (§6.1): a named, READ-ONLY grounding query capability.

    Subclasses set `name` (the `adapter:` token source instances bind — sources schema)
    and implement `ground()`. The resolver (`pipeline.grounding`) consumes THIS interface
    only; it never imports a concrete adapter. Rule 1 is structural here: the contract
    has no write primitive, and step 18's implementations must keep it that way.
    """

    #: The adapter-type token (`sources/_schema.yaml` `adapter:`); e.g. "graphify".
    name: ClassVar[str] = ""

    #: §6.1: the query capabilities this adapter type declares. v1 needs only "query";
    #: richer capability negotiation is a later-step concern.
    capabilities: ClassVar[frozenset[str]] = frozenset({"query"})

    @abstractmethod
    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        """Run one read-only grounding query against one bound connection.

        `connection` is the source instance's `connection:` map (sources schema);
        `query` is the item's grounding question. Failures raise `AdapterError`
        (loud, typed) — the resolver never guesses around a broken source.
        """

    def pin_commit(self, connection: Mapping[str, Any]) -> str | None:
        """The §7.2 identity commit-map value for a source bound to this adapter.

        This MUST be the SAME commit `ground()` reports for the same connection
        (`GroundingResult.built_at_commit`), read by the SAME provenance path — so the
        artifact-id commit-map (identity, §7.2) and the §15 grounding ledger never
        disagree about provenance. The default is `None` — the commitless folder-style
        posture (`GroundingResult.built_at_commit=None`); a commit-bearing adapter
        (graphify) overrides this to read exactly what its `ground()` reports. Read-only,
        never a write (rule 1)."""
        return None
