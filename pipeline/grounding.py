"""The grounding resolver — the §6.3 resolver walk over the adapter contract.

Design authority: `docs/design.md`
  §6.3 — the walk, per item: assemble pool → resolve the effective `source_selection`
         across M3's layers (`pipeline.m3`) → instance-scope hard filter + span check →
         query survivors, union grounding, keep each fact's originating instance +
         commit → compute per-fact scores + tier → fact-scope hard filter + publish
         floor → rank via `prefer` + `trusted`/`primariness` (+ internal `coverage`
         tie-break, SM8) → resolve conflicts per `on_conflict` (SM4) → hand grounded
         facts (provenance + tier + traceability) to compose.
  §6.4 — empty pool → BLOCK AND REPORT (SM1): the item blocks and the report names the
         offending clause; other fanout items continue (`ground_batch`); the blocked
         item surfaces with code `empty-pool` (§21.7). Blocking is the mechanical
         consequence of the user's own clause — never a system veto, never a silent
         substitution (§3.1).
  §6.5 — the per-fact confidence pipeline: base tier from the adapter → corroboration
         upgrade (independent confirmation across GENUINELY independent instances) →
         conflict adjustment per `on_conflict` → traceability computed. Tier ⟂
         traceability (SM9). **The EXTRACTED publish floor is a framework invariant,
         outside user config** — `GroundedFact.publishable` is computed from the tier
         alone; no `require`/`prefer` configuration, no run, and no override can relax
         it (there is deliberately NO selectable "tier" characteristic in the grammar).
  §6.2 — a user MAY assert a value over a derived score; the assertion rides as
         authoritative config (§3.1), is STAMPED for provenance, and large divergence
         from the computed value fires a ONE-TIME advisory lint — warn, never block
         (PA-9a).
  §21.7 — codes carried here: `empty-pool` (block) · `low-confidence-grounding` (warn);
         every non-ok outcome carries a machine `remediation.action`.
  §3.3 / CLAUDE.md rule 1 — read-only grounding; every fact records instance + commit
         (+ workspace on the outcome) for the §15 ledger; no secret values ride facts
         (adapters supply ids, anchors, commits — never credentials).

The resolver consumes the `pipeline.adapters.base` INTERFACE only — never a concrete
adapter (the mock lives in tests' wiring; step 18's real adapters slot in unchanged).

In-latitude decisions (step-17 coder; grounded in the report):

- **The corroboration upgrade rule** (§6.5 "genuinely independent"): a fact's tier rises
  ONE level iff ≥2 distinct BOUND SOURCES (adapter + connection; two instances over one
  bound connection are ONE source, and agreement of a source with itself is zero
  confirmations) assert the same (subject, claim) AND at least one of the agreeing
  instances has `independence == independent`. Two first-party (or affiliated) sources
  agreeing raise `corroboration` but never the tier — the sources schema's own rationale
  ("an uncharacterized instance can never fake the independence that corroboration
  arithmetic rewards"). Residual limit: DISTINCT connections carrying mirrored content
  remain the user's characterization duty (§3.1) — the resolver dedupes only the
  mechanically detectable identical-binding case.
- **Kind-tier and per-fact effective values** resolve: user assertion (the instance
  entry's set value — authoritative config, §3.1/§6.2) → adapter per-fact refinement
  (§6.1) → content-kind default → schema floor. `citable` is always the COMPUTED anchor
  truth (§6.5 citability is "can you cite it" — an assertion can drive selection but
  cannot conjure an anchor).
- **Freshness policy as filter + weight** (§6.2, content-kinds schema): a non-empty kind
  `freshness` policy (or a more-specific instance assertion, which wins) applies as a
  per-fact hard window filter for that instance's facts; a fact with UNKNOWN `as_of`
  fails any freshness gate (a gate a value cannot be shown to pass is not passed).
- **Conflict = one subject, ≥2 distinct claims** (exact-match claim comparison — the
  agreement rule's complement). A side is FACTUAL when its max `authoritative` exceeds
  its max `opinionated`, an OPINION side the reverse; ties are neither. The §6.3
  factual-beats-opinion property holds in `downgrade-AMBIGUOUS` and `priority-wins`
  alike: with exactly one factual side, the factual side survives untouched.
- **Divergence thresholds** (PA-9a "large divergence"): |Δ| ≥ 2 for scalar scores;
  any mismatch for boolean/categorical; freshness assertions are policy, not values —
  stamped but never divergence-checked.
- **Blame for an emptied pool** is the FIRST clause (in evaluation order) whose
  application left zero survivors — deterministic, and always a clause the user can
  relax or a source they can add (§6.4 remediation).
"""

from __future__ import annotations

import datetime
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pipeline.adapters.base import (
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    AdapterError,
    Anchor,
    Fact,
    SourceAdapter,
    upgrade_tier,
)
from pipeline.m1 import ResolutionWarning, Resolver
from pipeline.m3 import (
    CATEGORICAL_MEMBERS,
    CONTENT_KIND,
    ORDINAL_MEMBERS,
    PER_FACT_REFINABLE_SCORES,
    SCOPE_FACT,
    SCOPE_INSTANCE,
    EffectiveSelection,
    SelectionClause,
    bare_score_contribution,
    evaluate_clause,
    render_clause,
    validate_window_expression,
)
from pipeline.opgrammar import PRED_LT

__all__ = [
    "ASSERTABLE_SCORES",
    "AssertionRecord",
    "CODE_EMPTY_POOL",
    "CODE_LOW_CONFIDENCE_GROUNDING",
    "ConflictContext",
    "ConflictGroup",
    "ConflictInfo",
    "ConflictStrategy",
    "Contradiction",
    "DIVERGENCE_SCALAR_THRESHOLD",
    "GroundedFact",
    "GroundingError",
    "GroundingOutcome",
    "GroundingRequest",
    "INSTANCE_SCORE_FLOORS",
    "KIND_SCORE_FLOORS",
    "RefinementError",
    "STATUS_BLOCK",
    "STATUS_OK",
    "STATUS_WARN",
    "SourceInstance",
    "UnknownConflictStrategyError",
    "build_instance",
    "build_pool",
    "conflict_strategies",
    "ground_batch",
    "ground_item",
    "register_conflict_strategy",
]

#: §21.7 codes owned by this module.
CODE_EMPTY_POOL = "empty-pool"
CODE_LOW_CONFIDENCE_GROUNDING = "low-confidence-grounding"

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_BLOCK = "block"

#: Kind-tier score floors (mirror of `sources/_schema.yaml`/`content-kinds/_schema.yaml`
#: defaults — the vocabulary of record; a test pins this mirror against the shipped
#: schemas so drift fails mechanically).
KIND_SCORE_FLOORS: dict[str, Any] = {
    "authoritative": 3,
    "opinionated": 3,
    "freshness": "",
    "review_status": "unknown",
}

#: Instance-tier score floors (same mirror, same pin test).
INSTANCE_SCORE_FLOORS: dict[str, Any] = {
    "trusted": 3,
    "independence": "first-party",
    "primariness": "secondary",
}

#: §6.2: the scores a source-instance entry may ASSERT over a kind default or a derived
#: per-fact computation (the sources-schema assertion path; PA-9a).
ASSERTABLE_SCORES = frozenset(
    {
        "authoritative",
        "opinionated",
        "review_status",
        "primariness",
        "freshness",
        "corroboration",
        "traceability",
    }
)

#: PA-9a "large divergence" for scalar scores (in-latitude; module docstring).
DIVERGENCE_SCALAR_THRESHOLD = 2


# --- Typed errors -----------------------------------------------------------------------


class GroundingError(ValueError):
    """A grounding-side refusal — loud, typed, never repaired."""

    code = "grounding-refused"


class RefinementError(GroundingError):
    """An adapter supplied a per-fact refinement outside the §6.1 refinable set (or a
    value outside the score's §6.2 scale)."""

    code = "invalid-fact-refinement"


class UnknownConflictStrategyError(GroundingError):
    """`on_conflict` names a strategy the registry does not know (SM4: strategies are
    selectable and extensible — register, never guess)."""

    code = "unknown-conflict-strategy"


# --- The source instance (config view the resolver consumes; §6.1) -------------------------


@dataclass(frozen=True)
class SourceInstance:
    """One source instance: bound config + characterization (§6.1), resolver-ready.

    `kind_defaults` is the resolved content-kind entry's score bundle; `assertions`
    holds the scores the INSTANCE ENTRY set itself — the §6.2 user-assertion path
    (authoritative config, stamped, divergence-linted; PA-9a).
    """

    id: str
    adapter: str
    connection: Mapping[str, Any] = field(default_factory=dict)
    content_kind: str = "general"
    trusted: int = INSTANCE_SCORE_FLOORS["trusted"]
    independence: str = INSTANCE_SCORE_FLOORS["independence"]
    primariness: str = INSTANCE_SCORE_FLOORS["primariness"]
    kind_defaults: Mapping[str, Any] = field(default_factory=dict)
    assertions: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise GroundingError(
                f"grounding-refused: instance id must be non-empty, got {self.id!r}"
            )
        if not isinstance(self.adapter, str) or not self.adapter:
            raise GroundingError(
                f"grounding-refused: source instance {self.id!r} has no adapter bound — "
                "empty means unbound, never usable (sources schema, §6.1)"
            )
        if not isinstance(self.trusted, int) or isinstance(self.trusted, bool) or not (
            1 <= self.trusted <= 5
        ):
            raise GroundingError(
                f"grounding-refused: {self.id!r}.trusted must be an integer 1-5 (§6.2), "
                f"got {self.trusted!r}"
            )
        for score, value in (
            ("independence", self.independence),
            ("primariness", self.primariness),
        ):
            members = ORDINAL_MEMBERS[score]
            if value not in members:
                raise GroundingError(
                    f"grounding-refused: {self.id!r}.{score} must be one of "
                    f"{', '.join(members)} (§6.2), got {value!r}"
                )
        unknown = sorted(set(self.assertions) - ASSERTABLE_SCORES)
        if unknown:
            raise GroundingError(
                f"grounding-refused: {self.id!r} asserts non-assertable score(s) "
                f"{unknown!r} (assertable: {', '.join(sorted(ASSERTABLE_SCORES))} — §6.2)"
            )
        # Freshness config carriers are date-window EXPRESSIONS — validated on load
        # (the step-15 carry-forward): kind policy and instance assertion alike.
        for where, carrier in (
            (f"content-kinds default via {self.id!r}", self.kind_defaults.get("freshness", "")),
            (f"sources/{self.id}.freshness assertion", self.assertions.get("freshness", "")),
        ):
            if carrier != "":
                validate_window_expression(carrier, where=where)

    def kind_value(self, score: str) -> Any:
        """The content-kind default for one kind-tier score, floored (§6.1 SM5)."""
        value = self.kind_defaults.get(score)
        if value is None or value == "":
            return KIND_SCORE_FLOORS[score]
        return value

    def instance_value(self, characteristic: str) -> Any:
        """The instance-scope value one hard clause/span member evaluates against."""
        if characteristic == CONTENT_KIND:
            return self.content_kind
        if characteristic == "trusted":
            return self.trusted
        if characteristic == "independence":
            return self.independence
        if characteristic == "primariness":
            return self.assertions.get("primariness", self.primariness)
        raise GroundingError(  # structurally unreachable: scope table gates callers
            f"grounding-refused: {characteristic!r} is not an instance-scope characteristic"
        )


def build_instance(resolver: Resolver, entry_id: str) -> SourceInstance:
    """Build one `SourceInstance` from a resolved `sources/` entry (M1 — loud refs).

    The content-kind ref resolves via M1 (`resolve_ref` — unknown kind = loud,
    §11.1); the kind's effective values become `kind_defaults`; the score attributes
    the ENTRY set become `assertions` (§6.2). Freshness expressions validate here.
    """
    entry = resolver.resolve("sources", entry_id)
    floors = entry.defaults()
    kind_id = entry.effective.get("content_kind", floors["content_kind"])
    kind = resolver.resolve_ref(
        "content-kinds", kind_id, referrer=f"sources/{entry_id}", attribute="content_kind"
    )
    kind_defaults = kind.defaults()
    kind_defaults.update(kind.effective)
    assertions = {
        score: value for score, value in entry.effective.items() if score in ASSERTABLE_SCORES
    }
    return SourceInstance(
        id=entry_id,
        adapter=entry.effective.get("adapter", floors["adapter"]),
        connection=entry.effective.get("connection", floors["connection"]),
        content_kind=kind_id,
        trusted=entry.effective.get("trusted", floors["trusted"]),
        independence=entry.effective.get("independence", floors["independence"]),
        primariness=entry.effective.get("primariness", floors["primariness"]),
        kind_defaults=kind_defaults,
        assertions=assertions,
    )


def build_pool(resolver: Resolver, entry_ids: Sequence[str]) -> tuple[SourceInstance, ...]:
    """The workspace's declared source pool (§6.1), in declaration order."""
    return tuple(build_instance(resolver, entry_id) for entry_id in entry_ids)


# --- Grounded output shapes -----------------------------------------------------------------


@dataclass(frozen=True)
class ConflictInfo:
    """One fact's participation in a resolved conflict (§6.3 on_conflict)."""

    subject: str
    claims: tuple[str, ...]
    strategy: str
    role: str  # "kept" | "downgraded" | "attributed"


@dataclass(frozen=True)
class Contradiction:
    """A surfaced fact-vs-opinion contradiction (§6.3: the disagreement IS the content
    for goals like debunk / correct-the-record / fact-check)."""

    subject: str
    factual_claim: str
    factual_instances: tuple[str, ...]
    opinion_claim: str
    opinion_instances: tuple[str, ...]


@dataclass(frozen=True)
class AssertionRecord:
    """PA-9a provenance stamp: one user-asserted score value on one instance, with the
    computed counterpart it rode over (None where no computation exists this run)."""

    instance: str
    score: str
    asserted: Any
    computed: Any
    divergent: bool


@dataclass(frozen=True)
class GroundedFact:
    """One grounded claim as handed to compose (§6.3 walk end): provenance + tier +
    traceability, plus the effective score view selection used."""

    subject: str
    claim: str
    instance_id: str
    adapter: str
    commit: str | None
    base_tier: str
    tier: str
    corroboration: int
    agreeing_instances: tuple[str, ...]
    anchors: tuple[Anchor, ...]
    citable: bool  # COMPUTED anchor truth (§6.5 citability; SM9: independent of tier)
    as_of: datetime.date | None
    scores: Mapping[str, Any]  # the effective per-fact characteristic view
    weight: float
    attributed: bool = False
    conflict: ConflictInfo | None = None
    #: DR-6 scenario-2 pool-relation carrier (§15 RI3), ABSENT-by-default: a PROV-O-shaped
    #: {primary, anchor, relation} attestation. Scenario-1 facts (in-pool primary) carry None; the
    #: resolver does not SET it yet (this is the CARRIER + pass-through commit — no scenario-2
    #: detection). Compose emits it into the ledger entry ONLY when present.
    attestation: Mapping[str, Any] | None = None

    @property
    def publishable(self) -> bool:
        """§6.5: only EXTRACTED-tier facts publish as fact — computed from the tier
        ALONE; a framework invariant no configuration input can relax."""
        return self.tier == TIER_EXTRACTED


@dataclass(frozen=True)
class GroundingOutcome:
    """One item's grounding result (§21.7-shaped: status/code/context/remediation)."""

    item: str
    status: str  # ok | warn | block
    selection: EffectiveSelection
    facts: tuple[GroundedFact, ...]
    instances: tuple[str, ...]  # surviving pool, ranked-input order
    commit_map: Mapping[str, str | None]
    assertions: tuple[AssertionRecord, ...] = ()
    contradictions: tuple[Contradiction, ...] = ()
    warnings: tuple[ResolutionWarning, ...] = ()
    code: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    remediation: Mapping[str, str] | None = None
    workspace: str | None = None

    @property
    def publishable_facts(self) -> tuple[GroundedFact, ...]:
        """The §6.5 publish-floor survivors (publish as fact)."""
        return tuple(f for f in self.facts if f.publishable)

    @property
    def leads(self) -> tuple[GroundedFact, ...]:
        """INFERRED/AMBIGUOUS material: leads to verify, never published fact (§6.5)."""
        return tuple(f for f in self.facts if not f.publishable)


@dataclass(frozen=True)
class GroundingRequest:
    """One batch item (`ground_batch`): a label, a query, and its effective selection."""

    item: str
    query: str
    selection: EffectiveSelection
    pool: tuple[SourceInstance, ...] | None = None  # None = the batch pool


# --- Conflict strategies (§6.3 SM4: selectable, extensible) ---------------------------------


@dataclass
class _WorkingFact:
    instance: SourceInstance
    fact: Fact
    commit: str | None
    tier: str
    corroboration: int
    agreeing: tuple[str, ...]
    scores: dict[str, Any]
    citable: bool
    weight: float = 0.0
    attributed: bool = False
    conflict: ConflictInfo | None = None


@dataclass
class ConflictGroup:
    """One subject with ≥2 distinct claims: the strategy's working unit."""

    subject: str
    sides: dict[str, list[_WorkingFact]]  # claim -> facts asserting it

    def claims(self) -> tuple[str, ...]:
        return tuple(self.sides)

    def side_class(self, claim: str) -> str:
        """'factual' | 'opinion' | 'neutral' — max authoritative vs max opinionated."""
        facts = self.sides[claim]
        max_auth = max(f.scores["authoritative"] for f in facts)
        max_opin = max(f.scores["opinionated"] for f in facts)
        if max_auth > max_opin:
            return "factual"
        if max_opin > max_auth:
            return "opinion"
        return "neutral"

    def factual_claims(self) -> tuple[str, ...]:
        return tuple(c for c in self.sides if self.side_class(c) == "factual")


@dataclass
class ConflictContext:
    strategy: str
    now: datetime.date
    contradictions: list[Contradiction]


ConflictStrategy = Callable[[ConflictGroup, ConflictContext], None]


def _mark(group: ConflictGroup, ctx: ConflictContext, wf: _WorkingFact, role: str) -> None:
    wf.conflict = ConflictInfo(
        subject=group.subject, claims=group.claims(), strategy=ctx.strategy, role=role
    )
    if role == "downgraded":
        wf.tier = TIER_AMBIGUOUS
    elif role == "attributed":
        wf.attributed = True


def _strategy_downgrade_ambiguous(group: ConflictGroup, ctx: ConflictContext) -> None:
    """The §6.3 DEFAULT: conflicting facts downgrade to AMBIGUOUS — except that a lone
    factual side beats mere opinion and keeps its tier (the SM4 required property)."""
    factual = group.factual_claims()
    for claim, facts in group.sides.items():
        keep = len(factual) == 1 and claim == factual[0]
        for wf in facts:
            _mark(group, ctx, wf, "kept" if keep else "downgraded")


def _strategy_preserve_and_attribute(group: ConflictGroup, ctx: ConflictContext) -> None:
    """Compare/contrast (§6.3): the disagreement IS the content — every side kept,
    attributed to its instance; tiers untouched."""
    for facts in group.sides.values():
        for wf in facts:
            _mark(group, ctx, wf, "attributed")


def _side_priority(group: ConflictGroup, claim: str) -> tuple[float, int, int, int]:
    facts = group.sides[claim]
    return (
        max(f.weight for f in facts),
        max(f.instance.trusted for f in facts),
        max(ORDINAL_MEMBERS["primariness"].index(f.scores["primariness"]) for f in facts),
        max(f.corroboration for f in facts),
    )


def _strategy_priority_wins(group: ConflictGroup, ctx: ConflictContext) -> None:
    """Weight-driven (§6.3): the highest-priority side keeps its tier, the rest
    downgrade — but factual ALWAYS outranks opinion first (the SM4 property)."""
    factual = group.factual_claims()
    if len(factual) == 1:
        winner = factual[0]
    else:
        candidates = factual if factual else group.claims()
        best = max(_side_priority(group, claim) for claim in candidates)
        # ties resolve to the lexicographically first claim — deterministic, documented
        winner = sorted(c for c in candidates if _side_priority(group, c) == best)[0]
    for claim, facts in group.sides.items():
        for wf in facts:
            _mark(group, ctx, wf, "kept" if claim == winner else "downgraded")


def _strategy_surface_contradictions(group: ConflictGroup, ctx: ConflictContext) -> None:
    """The §6.3 contradiction capability: an opinion contradicting an authoritative fact
    is SURFACED as first-class output (debunk / correct-the-record / fact-check); the
    factual side keeps its tier, the opinion side is kept-and-attributed as the subject
    of the contradiction. Without a lone factual side there is nothing to correct —
    fall back to the default downgrade."""
    factual = group.factual_claims()
    if len(factual) != 1:
        _strategy_downgrade_ambiguous(group, ctx)
        return
    factual_claim = factual[0]
    factual_ids = tuple(sorted({wf.instance.id for wf in group.sides[factual_claim]}))
    for claim, facts in group.sides.items():
        if claim == factual_claim:
            for wf in facts:
                _mark(group, ctx, wf, "kept")
            continue
        ctx.contradictions.append(
            Contradiction(
                subject=group.subject,
                factual_claim=factual_claim,
                factual_instances=factual_ids,
                opinion_claim=claim,
                opinion_instances=tuple(sorted({wf.instance.id for wf in facts})),
            )
        )
        for wf in facts:
            _mark(group, ctx, wf, "attributed")


#: The shipped strategy set (§6.3 SM4) — extensible via `register_conflict_strategy`.
_CONFLICT_STRATEGIES: dict[str, ConflictStrategy] = {
    "downgrade-AMBIGUOUS": _strategy_downgrade_ambiguous,
    "preserve-and-attribute": _strategy_preserve_and_attribute,
    "priority-wins": _strategy_priority_wins,
    "surface-contradictions": _strategy_surface_contradictions,
}


def register_conflict_strategy(name: str, strategy: ConflictStrategy) -> None:
    """SM4 extensibility: one registration call adds a selectable strategy. Duplicate
    names refuse loudly — shipped strategies are never silently replaced."""
    if not isinstance(name, str) or not name or any(ch.isspace() for ch in name):
        raise GroundingError(
            f"grounding-refused: a strategy name is a single non-empty token, got {name!r}"
        )
    if name in _CONFLICT_STRATEGIES:
        raise GroundingError(
            f"grounding-refused: on_conflict strategy {name!r} is already registered — "
            "extend, don't edit (§3.2)"
        )
    _CONFLICT_STRATEGIES[name] = strategy


def conflict_strategies() -> tuple[str, ...]:
    """The currently selectable strategy names (discovery surface)."""
    return tuple(_CONFLICT_STRATEGIES)


# --- The walk ------------------------------------------------------------------------------


def _blocked(
    *,
    item: str,
    selection: EffectiveSelection,
    clause: str | None,
    set_at: str | None,
    detail: str,
    warnings: list[ResolutionWarning],
    workspace: str | None,
    action: str | None = None,
    hint: str | None = None,
) -> GroundingOutcome:
    """The §6.4/SM1 `empty-pool` block shape: names the offending clause, carries a
    machine remediation, and NEVER raises — the batch continues around it. `action`
    overrides the default token when the block is NOT addressable by the relax
    surface (§21.7: callers divert on the machine token, never by parsing the
    hint — the token must name a mechanism that can actually address the block)."""
    context: dict[str, Any] = {"clause": clause, "detail": detail}
    if set_at is not None:
        context["set_at"] = set_at
    if action is None:
        action = "relax-clause" if clause is not None else "add-source"
    if hint is None:
        hint = (
            f"clause `{clause}` left no usable grounding — relax it or add a source "
            "(your acts, §6.4), then re-run; idempotent by artifact-id (§7.1)"
            if clause is not None
            else f"{detail} — add or select a source (§6.4), then re-run; idempotent by "
            "artifact-id (§7.1)"
        )
    return GroundingOutcome(
        item=item,
        status=STATUS_BLOCK,
        selection=selection,
        facts=(),
        instances=(),
        commit_map={},
        warnings=tuple(warnings),
        code=CODE_EMPTY_POOL,
        context=context,
        remediation={"action": action, "hint": hint},
        workspace=workspace,
    )


def _validate_refinements(instance: SourceInstance, fact: Fact) -> None:
    for score, value in fact.refinements.items():
        if score not in PER_FACT_REFINABLE_SCORES:
            raise RefinementError(
                f"invalid-fact-refinement: adapter {instance.adapter!r} (instance "
                f"{instance.id!r}) refined {score!r} — refinable per-fact scores are "
                f"{', '.join(sorted(PER_FACT_REFINABLE_SCORES))} (§6.1; corroboration/"
                "traceability are resolver-computed, freshness rides as_of)"
            )
        if score in {"authoritative", "opinionated"}:
            if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 5):
                raise RefinementError(
                    f"invalid-fact-refinement: {instance.id!r} fact {fact.subject!r}: "
                    f"{score} refinement must be an integer 1-5 (§6.2), got {value!r}"
                )
        elif score == "review_status":
            members = CATEGORICAL_MEMBERS["review_status"]
            if value not in members:
                raise RefinementError(
                    f"invalid-fact-refinement: {instance.id!r} fact {fact.subject!r}: "
                    f"review_status refinement must be one of {', '.join(members)}, "
                    f"got {value!r}"
                )
        elif score == "primariness":
            members = ORDINAL_MEMBERS["primariness"]
            if value not in members:
                raise RefinementError(
                    f"invalid-fact-refinement: {instance.id!r} fact {fact.subject!r}: "
                    f"primariness refinement must be one of {', '.join(members)}, "
                    f"got {value!r}"
                )


def _source_key(instance: SourceInstance) -> tuple[str, str]:
    """The BOUND-SOURCE identity for corroboration arithmetic: adapter + connection.
    Two instances over one bound connection are ONE source definitionally (§6.5;
    the sources schema's independence rationale) — commit equality is deliberately
    NOT the key, because commitless adapters (folder-style) ship
    `built_at_commit=None` and None==None would wrongly merge genuinely distinct
    folders."""
    return (instance.adapter, repr(sorted(instance.connection.items())))


def _effective_scores(wf: _WorkingFact) -> dict[str, Any]:
    """The per-fact effective characteristic view (assertion → refinement → kind
    default → floor; module docstring). `traceability` is the effective SELECTION value;
    `citable` (computed) rides the working fact separately (SM9)."""
    instance = wf.instance
    refinements = wf.fact.refinements
    scores: dict[str, Any] = {
        "trusted": instance.trusted,
        "independence": instance.independence,
        CONTENT_KIND: instance.content_kind,
    }
    for score in ("authoritative", "opinionated", "review_status"):
        if score in instance.assertions:
            scores[score] = instance.assertions[score]
        elif score in refinements:
            scores[score] = refinements[score]
        else:
            scores[score] = instance.kind_value(score)
    if "primariness" in instance.assertions:
        scores["primariness"] = instance.assertions["primariness"]
    elif "primariness" in refinements:
        scores["primariness"] = refinements["primariness"]
    else:
        scores["primariness"] = instance.primariness
    scores["freshness"] = wf.fact.as_of
    scores["corroboration"] = instance.assertions.get("corroboration", wf.corroboration)
    scores["traceability"] = instance.assertions.get("traceability", wf.citable)
    return scores


def _freshness_policy(instance: SourceInstance) -> tuple[str, str] | None:
    """The effective freshness POLICY for one instance's facts: the instance assertion
    (more specific) over the kind policy; None when neither is set (§6.2 filter+weight)."""
    asserted = instance.assertions.get("freshness", "")
    if asserted != "":
        return asserted, f"sources/{instance.id}.freshness < {asserted}"
    kind_policy = instance.kind_value("freshness")
    if kind_policy != "":
        return kind_policy, f"content-kinds/{instance.content_kind}.freshness < {kind_policy}"
    return None


def _assertion_records(
    working: list[_WorkingFact],
    pool: Sequence[SourceInstance],
    warnings: list[ResolutionWarning],
    seen_warning_keys: set[str],
) -> list[AssertionRecord]:
    """PA-9a: stamp every user assertion; large divergence from the computed value
    fires the ONE-TIME advisory (warn, never block; the assertion still WINS — §3.1)."""
    by_instance: dict[str, list[_WorkingFact]] = {}
    for wf in working:
        by_instance.setdefault(wf.instance.id, []).append(wf)
    records: list[AssertionRecord] = []
    for instance in pool:
        facts = by_instance.get(instance.id, [])
        for score in sorted(instance.assertions):
            asserted = instance.assertions[score]
            computed: Any = None
            divergent = False
            if score == "corroboration" and facts:
                computed = max(wf.corroboration for wf in facts)
                divergent = abs(asserted - computed) >= DIVERGENCE_SCALAR_THRESHOLD
            elif score == "traceability" and facts:
                computed = any(wf.citable for wf in facts)
                divergent = bool(asserted) != computed
            elif score in {"authoritative", "opinionated"}:
                refined = [
                    wf.fact.refinements[score] for wf in facts if score in wf.fact.refinements
                ]
                if refined:
                    computed = max(refined)
                    divergent = any(
                        abs(asserted - r) >= DIVERGENCE_SCALAR_THRESHOLD for r in refined
                    )
            elif score in {"review_status", "primariness"}:
                refined = [
                    wf.fact.refinements[score] for wf in facts if score in wf.fact.refinements
                ]
                if refined:
                    computed = refined[0]
                    divergent = any(asserted != r for r in refined)
            # freshness: a policy expression, not a value — stamped, never diverged.
            records.append(
                AssertionRecord(
                    instance=instance.id,
                    score=score,
                    asserted=asserted,
                    computed=computed,
                    divergent=divergent,
                )
            )
            if divergent:
                key = f"user-assertion-divergence:{instance.id}:{score}"
                if key not in seen_warning_keys:
                    seen_warning_keys.add(key)
                    warnings.append(
                        ResolutionWarning(
                            key=key,
                            message=(
                                f"sources/{instance.id} asserts {score} = {asserted!r} "
                                f"but the computed value is {computed!r} — the assertion "
                                "rides as your authoritative config (§3.1/§6.2, stamped "
                                "for provenance); advisory only, never a block (PA-9a)"
                            ),
                        )
                    )
    return records


def ground_item(
    *,
    item: str,
    query: str,
    pool: Sequence[SourceInstance],
    selection: EffectiveSelection,
    adapters: Mapping[str, SourceAdapter],
    now: datetime.date,
    workspace: str | None = None,
    seen_warning_keys: set[str] | None = None,
) -> GroundingOutcome:
    """The §6.3 resolver walk for ONE item. Returns an outcome, NEVER raises for an
    empty pool (SM1: block-and-report is a result; the batch continues). Adapter and
    config defects (unknown adapter/strategy, bad refinements) raise loudly — those
    are broken machinery, not user clauses. The clock (`now`) is injected, never
    ambient."""
    if seen_warning_keys is None:
        seen_warning_keys = set()
    warnings: list[ResolutionWarning] = []
    for warning in selection.warnings:  # SM3 relax warnings — one-time per shared scope
        if warning.key not in seen_warning_keys:
            seen_warning_keys.add(warning.key)
            warnings.append(warning)

    instance_clauses = [c for c in selection.require if c.scope == SCOPE_INSTANCE]
    fact_clauses = [c for c in selection.require if c.scope == SCOPE_FACT]

    # -- pool assembly + instance-scope hard filter (§6.3 walk) ------------------------
    survivors = list(pool)
    if not survivors:
        return _blocked(
            item=item,
            selection=selection,
            clause=None,
            set_at=None,
            detail="empty or missing source pool (§6.4)",
            warnings=warnings,
            workspace=workspace,
        )
    for clause in instance_clauses:
        survivors = [
            inst
            for inst in survivors
            if evaluate_clause(clause, inst.instance_value(clause.score), now=now)
        ]
        if not survivors:
            canonical = render_clause(clause)
            return _blocked(
                item=item,
                selection=selection,
                clause=canonical,
                set_at=selection.require_origins.get(canonical),
                detail="instance-scope require left an empty pool",
                warnings=warnings,
                workspace=workspace,
            )

    # -- span check (§6.3: ≥1 surviving instance per named member) ---------------------
    for axis, members in selection.span.items():
        for member in members:
            if not any(inst.instance_value(axis) == member for inst in survivors):
                return _blocked(
                    item=item,
                    selection=selection,
                    clause=f"span {axis}: {member}",
                    set_at=selection.span_origins.get(axis),
                    detail="span member has no surviving instance",
                    warnings=warnings,
                    workspace=workspace,
                )

    # -- query survivors; union keeps each fact's originating instance + commit --------
    commit_map: dict[str, str | None] = {}
    working: list[_WorkingFact] = []
    for instance in survivors:
        adapter = adapters.get(instance.adapter)
        if adapter is None:
            raise AdapterError(
                f"adapter-failure: source instance {instance.id!r} binds unknown adapter "
                f"{instance.adapter!r} — an unknown adapter name fails loudly at ground "
                f"time (§6.1; wired: {sorted(adapters)})"
            )
        result = adapter.ground(connection=instance.connection, query=query)
        commit_map[instance.id] = result.built_at_commit
        for fact in result.facts:
            _validate_refinements(instance, fact)
            working.append(
                _WorkingFact(
                    instance=instance,
                    fact=fact,
                    commit=result.built_at_commit,
                    tier=fact.tier,
                    corroboration=0,
                    agreeing=(instance.id,),
                    scores={},
                    citable=len(fact.anchors) > 0,
                )
            )

    if not working:
        return _blocked(
            item=item,
            selection=selection,
            clause=None,
            set_at=None,
            detail="the surviving pool returned no facts for this query",
            warnings=warnings,
            workspace=workspace,
        )

    # -- per-fact scores + tier (§6.5: corroboration upgrade before conflicts) ---------
    agreement: dict[tuple[str, str], list[_WorkingFact]] = {}
    for wf in working:
        agreement.setdefault((wf.fact.subject, wf.fact.claim), []).append(wf)
    for group in agreement.values():
        ids = sorted({wf.instance.id for wf in group})
        sources = {_source_key(wf.instance) for wf in group}
        genuinely_independent = len(sources) >= 2 and any(
            wf.instance.independence == "independent" for wf in group
        )
        for wf in group:
            wf.agreeing = tuple(ids)  # instance ids stay the provenance surface
            wf.corroboration = len(sources) - 1
            if genuinely_independent:
                wf.tier = upgrade_tier(wf.tier)
    for wf in working:
        wf.scores = _effective_scores(wf)

    # -- PA-9a assertion stamps + one-time divergence advisories -----------------------
    assertion_records = _assertion_records(working, survivors, warnings, seen_warning_keys)

    # -- fact-scope hard filter: freshness policies (config), then explicit clauses ----
    for instance in survivors:
        policy = _freshness_policy(instance)
        if policy is None:
            continue
        expression, policy_label = policy
        policy_clause = SelectionClause(score="freshness", op=PRED_LT, operand=expression)
        kept = [
            wf
            for wf in working
            if wf.instance.id != instance.id
            or evaluate_clause(policy_clause, wf.scores["freshness"], now=now)
        ]
        if not kept:
            # §21.7 machine-token honesty (RV-2): a freshness POLICY is config — the
            # M3 relax surface cannot name it, so `relax-clause` would divert callers
            # to a mechanism that cannot address the block.
            policy_home = policy_label.split(".freshness", 1)[0]
            return _blocked(
                item=item,
                selection=selection,
                clause=policy_label,
                set_at="config",
                detail="the configured freshness policy left no facts",
                warnings=warnings,
                workspace=workspace,
                action="adjust-freshness-policy",
                hint=(
                    f"freshness policy `{policy_label}` left no usable grounding — it "
                    f"is CONFIG, not a grammar clause, so `relax:` cannot address it; "
                    f"adjust the `{policy_home}` entry (or add a fresher source), then "
                    "re-run; idempotent by artifact-id (§7.1)"
                ),
            )
        working = kept
    for clause in fact_clauses:
        kept = [
            wf for wf in working if evaluate_clause(clause, wf.scores[clause.score], now=now)
        ]
        if not kept:
            canonical = render_clause(clause)
            return _blocked(
                item=item,
                selection=selection,
                clause=canonical,
                set_at=selection.require_origins.get(canonical),
                detail="fact-scope require left no facts",
                warnings=warnings,
                workspace=workspace,
            )
        working = kept

    # -- rank: prefer + trusted/primariness + internal coverage tie-break (§6.3, SM8) --
    coverage: dict[str, int] = {}
    for wf in working:
        coverage[wf.instance.id] = coverage.get(wf.instance.id, 0) + 1
    for wf in working:
        weight = 0.0
        for effective in selection.prefer:
            term = effective.term
            if term.clause is None:
                weight += effective.weight * bare_score_contribution(
                    term.score, wf.scores[term.score], now=now
                )
            elif evaluate_clause(term.clause, wf.scores[term.clause.score], now=now):
                weight += effective.weight
        wf.weight = weight
    primariness_order = ORDINAL_MEMBERS["primariness"]
    working.sort(
        key=lambda wf: (
            -wf.weight,
            -wf.instance.trusted,
            -primariness_order.index(wf.scores["primariness"]),
            -coverage[wf.instance.id],
            wf.instance.id,
            wf.fact.subject,
            wf.fact.claim,
        )
    )

    # -- resolve conflicts per on_conflict (§6.3 SM4) -----------------------------------
    strategy = _CONFLICT_STRATEGIES.get(selection.on_conflict)
    if strategy is None:
        raise UnknownConflictStrategyError(
            f"unknown-conflict-strategy: {selection.on_conflict!r} (set at "
            f"{selection.on_conflict_origin}) — selectable strategies: "
            f"{', '.join(conflict_strategies())} (SM4: register new ones, never guess)"
        )
    subjects: dict[str, dict[str, list[_WorkingFact]]] = {}
    for wf in working:
        subjects.setdefault(wf.fact.subject, {}).setdefault(wf.fact.claim, []).append(wf)
    ctx = ConflictContext(strategy=selection.on_conflict, now=now, contradictions=[])
    for subject, sides in subjects.items():
        if len(sides) >= 2:
            strategy(ConflictGroup(subject=subject, sides=sides), ctx)

    # -- the grounded-fact handoff (provenance + tier + traceability; §6.3) -------------
    facts = tuple(
        GroundedFact(
            subject=wf.fact.subject,
            claim=wf.fact.claim,
            instance_id=wf.instance.id,
            adapter=wf.instance.adapter,
            commit=wf.commit,
            base_tier=wf.fact.tier,
            tier=wf.tier,
            corroboration=wf.corroboration,
            agreeing_instances=wf.agreeing,
            anchors=wf.fact.anchors,
            citable=wf.citable,
            as_of=wf.fact.as_of,
            scores=dict(wf.scores),
            weight=wf.weight,
            attributed=wf.attributed,
            conflict=wf.conflict,
        )
        for wf in working
    )

    code: str | None = None
    remediation: Mapping[str, str] | None = None
    if not any(f.publishable for f in facts):
        code = CODE_LOW_CONFIDENCE_GROUNDING
        remediation = {
            "action": "add-source",
            "hint": (
                "no EXTRACTED-tier fact survived — everything here is a lead to verify "
                "(§6.5); add/upgrade a source or corroborate across independent "
                "instances; the publish floor itself is a framework invariant and "
                "never relaxes"
            ),
        }
        key = f"low-confidence-grounding:{item}"
        if key not in seen_warning_keys:
            seen_warning_keys.add(key)
            warnings.append(
                ResolutionWarning(
                    key=key,
                    message=(
                        f"item {item!r}: grounding survived but contains no EXTRACTED "
                        "fact — INFERRED/AMBIGUOUS material is leads to verify, never "
                        "published fact (§6.5)"
                    ),
                )
            )

    return GroundingOutcome(
        item=item,
        status=STATUS_WARN if code is not None else STATUS_OK,
        selection=selection,
        facts=facts,
        instances=tuple(inst.id for inst in survivors),
        commit_map=commit_map,
        assertions=tuple(assertion_records),
        contradictions=tuple(ctx.contradictions),
        warnings=tuple(warnings),
        code=code,
        context={},
        remediation=remediation,
        workspace=workspace,
    )


def ground_batch(
    requests: Sequence[GroundingRequest],
    *,
    pool: Sequence[SourceInstance],
    adapters: Mapping[str, SourceAdapter],
    now: datetime.date,
    workspace: str | None = None,
) -> tuple[GroundingOutcome, ...]:
    """Ground a fanout batch: per-item outcomes, in order. A blocked item NEVER fails
    the batch (SM1/§21.7) — its siblings proceed; one-time advisories (SM3 relax,
    PA-9a divergence) dedupe across the whole batch via a shared key set."""
    seen_warning_keys: set[str] = set()
    return tuple(
        ground_item(
            item=request.item,
            query=request.query,
            pool=request.pool if request.pool is not None else pool,
            selection=request.selection,
            adapters=adapters,
            now=now,
            workspace=workspace,
            seen_warning_keys=seen_warning_keys,
        )
        for request in requests
    )
