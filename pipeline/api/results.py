"""The typed result contract + the CONSOLIDATED §21.7/§22.6 code taxonomy — one place.

Design authority: `docs/design.md` §21.7 (the one `ResultItem` shape for every verb; the
stable machine-readable codes; the machine `remediation.action` token), §22.6 (the
parallel-path codes that extend the SAME taxonomy), §21.1 (the envelope's `ok` = whole-
invocation validity only), §21.8 (the `render-input-mismatch` → `force-re-reconcile`
remediation and the `re-reconciled`/`re-serialized` ok codes).

This module is THE single home for the API code vocabulary. Every §21.7 + §22.6 code lives
here as a named constant, grouped by tier, with its canonical status(es), the design section
that rules it, and (where the design fixes one) a machine `remediation.action` token. The
literal code-list test (`tests/test_results.py`) pins `ALL_CODES` to exactly this
enumeration — no extras, no omissions — and the discovery meta-type `codes` (§21.3, wired at
a later step) reads `CODES` to stay self-describing so callers never hardcode a vocabulary
that could drift.

**What is NOT here (deliberately):** `stale-token` (a token is never rejected for age, §20),
`superseded-fit`/`non-current-fit` (currency is a computed FIELD on read surfaces, never a
result code — §21.3), and any serialize-level mismatch warn (an unqualified render never
returns serialize-stale bytes — FR7.3, §21.8). Internal module codes that never reach the
wire (`invalid-id`, `canonicalization-refused`, `binary-not-found`, `already-released`, …)
are likewise absent — they are exceptions, not ResultItem codes.

The consolidation faithfully mirrors the strings the producing modules already emit
(`reconcile.CODE_HARD_LIMIT_EXCEEDED`, `drift.CODE_DRIFT_BLOCK`/`CODE_OUT_OF_WINDOW`,
`grounding.CODE_EMPTY_POOL`/`CODE_LOW_CONFIDENCE_GROUNDING`,
`fit_resolution.CODE_RENDER_INPUT_MISMATCH`/`CODE_RE_RECONCILED`,
`serialize.CODE_RE_SERIALIZED`, `migration.CODE_AMBIGUOUS_MIGRATION_DECISIONS`, the
`claims`/`transport`/`folios`/`overrides` literals); a `tests/test_results.py` drift check
proves those module constants are all members of `ALL_CODES`. This module imports none of
them — the taxonomy is dependency-free (and INV-CORRECTNESS-clean: no `ssot`, no store).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ALL_CODES",
    "CODES",
    "CONTRACT_CODES",
    "GENERATION_CODES",
    "PARALLEL_CODES",
    "REMEDIATION_ACTIONS",
    "STATUSES",
    "TIERS",
    "CodeSpec",
    "Envelope",
    "ResultContractError",
    "ResultItem",
    "make_result",
    # remediation action tokens (the design-ratified subset)
    "ACTION_ADD_SOURCE",
    "ACTION_FORCE_RE_RECONCILE",
    "ACTION_RELAX_CLAUSE",
    "ACTION_RETRY_AFTER",
    "ACTION_RUN_MIGRATE",
    # tiers
    "TIER_CONTRACT",
    "TIER_GENERATION",
    "TIER_PARALLEL",
    # generation-tier codes (§21.7)
    "CODE_ADVISORY_CONSTRAINT_OVERRIDDEN",
    "CODE_AMBIGUOUS_MIGRATION_DECISIONS",
    "CODE_CAPABILITY_INFEASIBLE",
    "CODE_DRIFT_BLOCK",
    "CODE_EMPTY_POOL",
    "CODE_GROUNDING_UNCOVERED",
    "CODE_HARD_LIMIT_EXCEEDED",
    "CODE_LOW_CONFIDENCE_GROUNDING",
    "CODE_MEMBER_UPDATED",
    "CODE_NONSENSICAL_PAIRING",
    "CODE_OUT_OF_WINDOW",
    "CODE_RE_RECONCILED",
    "CODE_RE_SERIALIZED",
    "CODE_RENDER_INPUT_MISMATCH",
    "CODE_SECTION_CONFORMANCE_VIOLATION",
    # contract-tier codes (§21.7)
    "CODE_INVALID_OVERRIDE",
    "CODE_INVALID_TOKEN",
    "CODE_ISOLATION_VIOLATION",
    "CODE_NOT_FOUND",
    "CODE_UNKNOWN_ACTION",
    "CODE_UNKNOWN_VERB",
    "CODE_UNRESOLVED_MEMBER",
    # parallel-path codes (§22.6)
    "CODE_ALREADY_MATERIALIZED",
    "CODE_CLAIM_HELD",
    "CODE_COLLISION_AVERTED",
    "CODE_LEASE_EXPIRED_REDRIVE",
    "CODE_PLAN_STALE",
    "CODE_RATE_LIMIT_BACKPRESSURE",
]


class ResultContractError(ValueError):
    """A ResultItem/Envelope built outside the §21.7 shape (bad status/code) — refused."""

    code = "result-contract-error"


#: §21.7: the four per-item statuses. `ok`/`warn`/`needs-input` never fail a batch; a
#: per-item `block` never fails the batch either (SM1) — only the envelope can be not-ok.
STATUSES = ("ok", "warn", "block", "needs-input")

#: The three code tiers of §21.7/§22.6. `category` on a ResultItem is the code's tier.
TIER_GENERATION = "generation"  # §21.7 generation tier
TIER_CONTRACT = "contract"  # §21.7 contract tier
TIER_PARALLEL = "parallel"  # §22.6 parallel-path tier
TIERS = (TIER_GENERATION, TIER_CONTRACT, TIER_PARALLEL)

# ---------------------------------------------------------------------------
# Machine remediation actions — the design-RATIFIED subset (§21.7 names
# `relax-clause`/`run-migrate`/`retry-after` by example; §21.8 assigns
# `force-re-reconcile`; grounding.py adds `add-source` as the no-clause sibling of
# `relax-clause`). Non-ok codes without a fixed token here get their per-instance
# `remediation.action` from the producing handler (steps 33-35); the FULL discoverable
# action vocabulary lands with those handlers — this step never asserts handler wiring.
# ---------------------------------------------------------------------------

ACTION_RELAX_CLAUSE = "relax-clause"  # §6.4 empty-pool with a clause to relax
ACTION_ADD_SOURCE = "add-source"  # §6.4 empty-pool with no clause — add a source
ACTION_RUN_MIGRATE = "run-migrate"  # §11.6 migration remedy (scripts/migrate.sh, §21.9)
ACTION_RETRY_AFTER = "retry-after"  # §22.5 backpressure — retry after the given delay
ACTION_FORCE_RE_RECONCILE = "force-re-reconcile"  # §21.8 render-input-mismatch remedy
REMEDIATION_ACTIONS = frozenset(
    {
        ACTION_RELAX_CLAUSE,
        ACTION_ADD_SOURCE,
        ACTION_RUN_MIGRATE,
        ACTION_RETRY_AFTER,
        ACTION_FORCE_RE_RECONCILE,
    }
)

# ---------------------------------------------------------------------------
# The consolidated code taxonomy (§21.7 + §22.6). One named constant per code.
# ---------------------------------------------------------------------------

# --- generation tier (§21.7) ------------------------------------------------
CODE_HARD_LIMIT_EXCEEDED = "hard-limit-exceeded"  # block, §16
CODE_ADVISORY_CONSTRAINT_OVERRIDDEN = "advisory-constraint-overridden"  # warn, §12.7
CODE_NONSENSICAL_PAIRING = "nonsensical-pairing"  # warn, §8
CODE_DRIFT_BLOCK = "drift-block"  # block, §11.5
CODE_OUT_OF_WINDOW = "out-of-window"  # block, §11.6
CODE_EMPTY_POOL = "empty-pool"  # block, §6.4
CODE_LOW_CONFIDENCE_GROUNDING = "low-confidence-grounding"  # warn, §6.5
CODE_CAPABILITY_INFEASIBLE = "capability-infeasible"  # warn|block, §17
CODE_RENDER_INPUT_MISMATCH = "render-input-mismatch"  # warn (reconcile-scoped), §21.8
CODE_RE_RECONCILED = "re-reconciled"  # ok, §21.8
CODE_RE_SERIALIZED = "re-serialized"  # ok, §17/§21.8
CODE_MEMBER_UPDATED = "member-updated"  # warn, §21.2
CODE_AMBIGUOUS_MIGRATION_DECISIONS = "ambiguous-migration-decisions"  # needs-input, §11.6
CODE_GROUNDING_UNCOVERED = "grounding-uncovered"  # block, §6.5/§19
CODE_SECTION_CONFORMANCE_VIOLATION = "section-conformance-violation"  # block, §15/§16 (DR-4)

# --- contract tier (§21.7) --------------------------------------------------
CODE_UNKNOWN_VERB = "unknown-verb"  # block (envelope-fatal), §21.1
CODE_UNKNOWN_ACTION = "unknown-action"  # block, §21.2
CODE_INVALID_OVERRIDE = "invalid-override"  # block, §21.4
CODE_ISOLATION_VIOLATION = "isolation-violation"  # block (envelope-fatal), §21.1/§10
CODE_INVALID_TOKEN = "invalid-token"  # block (envelope-fatal), §20 — NO stale-token
CODE_NOT_FOUND = "not-found"  # block, §21.7
CODE_UNRESOLVED_MEMBER = "unresolved-member"  # needs-input, §21.5

# --- parallel-path tier (§22.6) ---------------------------------------------
CODE_ALREADY_MATERIALIZED = "already-materialized"  # ok, §22.6/§22.3 (REUSED, not new)
CODE_CLAIM_HELD = "claim-held"  # warn, §22.3/§22.6
CODE_LEASE_EXPIRED_REDRIVE = "lease-expired-redrive"  # ok, §22.3/§22.6
CODE_PLAN_STALE = "plan-stale"  # warn, §21.6/§22.6
CODE_COLLISION_AVERTED = "collision-averted"  # warn, §22.6
CODE_RATE_LIMIT_BACKPRESSURE = "rate-limit-backpressure"  # warn|block, §22.5/§22.6


@dataclass(frozen=True)
class CodeSpec:
    """One code's self-describing record (the `list codes` payload, §21.3).

    `statuses` is the status(es) the code may legitimately carry — one for most codes, a
    2-tuple for the dual ones (`capability-infeasible`, `rate-limit-backpressure` are
    warn|block). `remediation_action` is the design-fixed machine action, or None when the
    producing handler sets it per instance. `section` is the ruling design section.
    """

    code: str
    tier: str
    statuses: tuple[str, ...]
    remediation_action: str | None
    section: str
    summary: str


def _spec(
    code: str,
    tier: str,
    statuses: tuple[str, ...],
    section: str,
    summary: str,
    remediation_action: str | None = None,
) -> CodeSpec:
    return CodeSpec(
        code=code,
        tier=tier,
        statuses=statuses,
        remediation_action=remediation_action,
        section=section,
        summary=summary,
    )


#: THE consolidated taxonomy: code string → its self-describing spec. `set(CODES)` is the
#: exact §21.7 + §22.6 enumeration (pinned by the literal-list test).
CODES: dict[str, CodeSpec] = {
    spec.code: spec
    for spec in (
        # generation tier (§21.7)
        _spec(
            CODE_HARD_LIMIT_EXCEEDED, TIER_GENERATION, ("block",), "§16",
            "Content cannot be fit under the platform hard limit; this deliverable blocks, "
            "siblings continue.",
        ),
        _spec(
            CODE_ADVISORY_CONSTRAINT_OVERRIDDEN, TIER_GENERATION, ("warn",), "§12.7",
            "A recipe/run deviated from an advisory norm — the user's act, recorded, not "
            "blocked.",
        ),
        _spec(
            CODE_NONSENSICAL_PAIRING, TIER_GENERATION, ("warn",), "§8",
            "A format×platform pairing the advisory lint flags as unusual; never a veto.",
        ),
        _spec(
            CODE_DRIFT_BLOCK, TIER_GENERATION, ("block",), "§11.5",
            "A config redefinition must be migrated before this run proceeds.",
            remediation_action=ACTION_RUN_MIGRATE,
        ),
        _spec(
            CODE_OUT_OF_WINDOW, TIER_GENERATION, ("block",), "§11.6",
            "A pinned schema_version is outside the migration window; run migration.",
            remediation_action=ACTION_RUN_MIGRATE,
        ),
        _spec(
            CODE_EMPTY_POOL, TIER_GENERATION, ("block",), "§6.4",
            "A selection clause left an empty source pool; relax the clause or add a source.",
            remediation_action=ACTION_RELAX_CLAUSE,
        ),
        _spec(
            CODE_LOW_CONFIDENCE_GROUNDING, TIER_GENERATION, ("warn",), "§6.5",
            "Grounding fell below the publish-confidence floor; verify before publishing.",
        ),
        _spec(
            CODE_CAPABILITY_INFEASIBLE, TIER_GENERATION, ("warn", "block"), "§17",
            "The platform×output-type pairing is infeasible for the render target.",
        ),
        _spec(
            CODE_RENDER_INPUT_MISMATCH, TIER_GENERATION, ("warn",), "§21.8",
            "An unqualified render returned a cached fit whose recorded inputs differ from "
            "current; force to re-reconcile (reconcile-scoped only).",
            remediation_action=ACTION_FORCE_RE_RECONCILE,
        ),
        _spec(
            CODE_RE_RECONCILED, TIER_GENERATION, ("ok",), "§21.8",
            "A forced render minted a revision fit; ids carry the new fitted-id + "
            "deliverable-id(s).",
        ),
        _spec(
            CODE_RE_SERIALIZED, TIER_GENERATION, ("ok",), "§17/§21.8",
            "An unqualified render auto-minted a serialize revision (the sibling of "
            "re-reconciled).",
        ),
        _spec(
            CODE_MEMBER_UPDATED, TIER_GENERATION, ("warn",), "§21.2",
            "A folio member's pin/role was atomically updated; the original added_ts is "
            "preserved.",
        ),
        _spec(
            CODE_AMBIGUOUS_MIGRATION_DECISIONS, TIER_GENERATION, ("needs-input",), "§11.6",
            "The migration worklist has decisions a human must resolve out-of-band.",
            remediation_action=ACTION_RUN_MIGRATE,
        ),
        _spec(
            CODE_GROUNDING_UNCOVERED, TIER_GENERATION, ("block",), "§6.5/§19",
            "An opt-in grounding_posture=block item abstained on an advisory Review-1 grounding "
            "concern.",
            remediation_action=None,
        ),
        _spec(
            CODE_SECTION_CONFORMANCE_VIOLATION, TIER_GENERATION, ("block",), "§15/§16",
            "A composed (or reconciled) body persistently violated its typed-section conformance "
            "contract (base required/forbidden/order) across the bounded re-ask; blocked, never "
            "persisted (DR-4).",
            remediation_action=None,
        ),
        # contract tier (§21.7)
        _spec(
            CODE_UNKNOWN_VERB, TIER_CONTRACT, ("block",), "§21.1",
            "The verb is not in the closed API verb set (whole-invocation invalid).",
        ),
        _spec(
            CODE_UNKNOWN_ACTION, TIER_CONTRACT, ("block",), "§21.2",
            "The continue-session action is not in the closed action set.",
        ),
        _spec(
            CODE_INVALID_OVERRIDE, TIER_CONTRACT, ("block",), "§21.4",
            "An override violated the hard M1 guard (a declared attribute of an "
            "already-selected entry only).",
        ),
        _spec(
            CODE_ISOLATION_VIOLATION, TIER_CONTRACT, ("block",), "§21.1/§10",
            "An id does not resolve inside the invoked workspace; workspaces never cross "
            "(whole-invocation invalid).",
        ),
        _spec(
            CODE_INVALID_TOKEN, TIER_CONTRACT, ("block",), "§20",
            "The token is malformed, tampered, cross-version, or bound to another workspace "
            "(there is no stale-token; whole-invocation invalid).",
        ),
        _spec(
            CODE_NOT_FOUND, TIER_CONTRACT, ("block",), "§21.7",
            "No record exists for the requested id in this workspace.",
        ),
        _spec(
            CODE_UNRESOLVED_MEMBER, TIER_CONTRACT, ("needs-input",), "§21.5",
            "A manifest member has no emit-time target and no pin; supply one — never "
            "guessed.",
        ),
        # parallel-path tier (§22.6)
        _spec(
            CODE_ALREADY_MATERIALIZED, TIER_PARALLEL, ("ok",), "§22.6/§22.3",
            "The id is already materialized; an idempotent no-op, the winner's bytes intact.",
        ),
        _spec(
            CODE_CLAIM_HELD, TIER_PARALLEL, ("warn",), "§22.3/§22.6",
            "Another worker holds a live claim; move on or poll by id.",
        ),
        _spec(
            CODE_LEASE_EXPIRED_REDRIVE, TIER_PARALLEL, ("ok",), "§22.3/§22.6",
            "An expired lease was stolen and the work re-driven.",
        ),
        _spec(
            CODE_PLAN_STALE, TIER_PARALLEL, ("warn",), "§21.6/§22.6",
            "The plan hash changed since the token was minted; re-fetch the plan, the sweep "
            "reconciles — never a silent skip/dup.",
        ),
        _spec(
            CODE_COLLISION_AVERTED, TIER_PARALLEL, ("warn",), "§22.6",
            "A write collision was averted; exactly one winner materialized.",
        ),
        _spec(
            CODE_RATE_LIMIT_BACKPRESSURE, TIER_PARALLEL, ("warn", "block"), "§22.5/§22.6",
            "The subscription applied backpressure; retry after the given delay or reduce "
            "width.",
            remediation_action=ACTION_RETRY_AFTER,
        ),
    )
}

#: The complete code set — the literal-list test pins this to the §21.7+§22.6 enumeration.
ALL_CODES = frozenset(CODES)
GENERATION_CODES = frozenset(c for c, s in CODES.items() if s.tier == TIER_GENERATION)
CONTRACT_CODES = frozenset(c for c, s in CODES.items() if s.tier == TIER_CONTRACT)
PARALLEL_CODES = frozenset(c for c, s in CODES.items() if s.tier == TIER_PARALLEL)


# ---------------------------------------------------------------------------
# The one ResultItem shape (§21.7) + the invocation envelope (§21.1).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResultItem:
    """The single §21.7 result shape for every verb.

    `item` names what the result is about (a coordinate/label/id). `status` is one of
    STATUSES. `ids` carries the relevant ids (`{}` when none). `code`/`category` are the
    taxonomy code and its tier; `category` auto-derives from `code` when omitted.
    `output` holds `{path?}`/`{bytes?}`; `context` is the open key bag (`dimension`,
    `attribute`, `limit`, `id`, `clause`, `current_inputs_digest`, …, §21.8);
    `remediation` is `{hint?, action?}` — every non-ok result carries a machine `action`
    so callers divert on the token, never on the human `hint` (§21.7).
    """

    item: str
    status: str
    ids: dict[str, Any] = field(default_factory=dict)
    code: str | None = None
    category: str | None = None
    output: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    remediation: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ResultContractError(
                f"result-contract-error: status {self.status!r} is not one of {STATUSES} "
                "(§21.7)"
            )
        if not isinstance(self.item, str):
            raise ResultContractError("result-contract-error: `item` must be a string (§21.7)")
        if self.code is not None:
            spec = CODES.get(self.code)
            if spec is None:
                raise ResultContractError(
                    f"result-contract-error: {self.code!r} is not a §21.7/§22.6 code — the "
                    "taxonomy is closed (list codes, §21.3)"
                )
            if self.status not in spec.statuses:
                raise ResultContractError(
                    f"result-contract-error: code {self.code!r} carries status {spec.statuses} "
                    f"(§{spec.section}), not {self.status!r}"
                )
            if self.category is None:
                object.__setattr__(self, "category", spec.tier)
            elif self.category != spec.tier:
                raise ResultContractError(
                    f"result-contract-error: code {self.code!r} is tier {spec.tier!r}, not "
                    f"category {self.category!r}"
                )
        if self.remediation is not None:
            extra = set(self.remediation) - {"hint", "action"}
            if extra:
                raise ResultContractError(
                    f"result-contract-error: remediation carries only hint/action (§21.7), "
                    f"got extra {sorted(extra)!r}"
                )
            action = self.remediation.get("action")
            if action is not None and (not isinstance(action, str) or not action):
                raise ResultContractError(
                    "result-contract-error: remediation.action is a non-empty machine token "
                    "(§21.7)"
                )

    def as_dict(self) -> dict[str, Any]:
        """The wire JSON (§13): required item/status/ids; optionals only when present."""
        out: dict[str, Any] = {
            "item": self.item,
            "status": self.status,
            "ids": dict(self.ids),
        }
        if self.code is not None:
            out["code"] = self.code
        if self.category is not None:
            out["category"] = self.category
        if self.output:
            out["output"] = dict(self.output)
        if self.context:
            out["context"] = dict(self.context)
        if self.remediation:
            out["remediation"] = dict(self.remediation)
        return out


@dataclass(frozen=True)
class Envelope:
    """The invocation envelope (§21.1/§21.7). `ok` reflects WHOLE-invocation validity only.

    `ok` is False for exactly the three whole-invocation failures — unknown verb, isolation
    breach, malformed/invalid token (§21.7) — and `code`/`message` name the failure. A
    per-item `block` never touches `ok` (SM1). On the fatal path there is no echoed token.
    """

    ok: bool
    verb: str
    workspace: str
    code: str | None = None
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "verb": self.verb, "workspace": self.workspace}
        if self.code is not None:
            out["code"] = self.code
        if self.message is not None:
            out["message"] = self.message
        return out


def make_result(
    code: str,
    *,
    item: str,
    status: str | None = None,
    ids: dict[str, Any] | None = None,
    output: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
    hint: str | None = None,
    action: str | None = None,
) -> ResultItem:
    """Build a taxonomy-driven ResultItem: category, default status, and default machine
    `remediation.action` all come from the code's `CodeSpec` (overridable).

    `status` defaults to the code's first canonical status; `action` defaults to the code's
    design-fixed `remediation_action` (None for codes whose handler sets it per instance).
    A `remediation` dict is attached whenever a `hint` or an `action` is present.
    """
    spec = CODES.get(code)
    if spec is None:
        raise ResultContractError(
            f"result-contract-error: {code!r} is not a §21.7/§22.6 code (list codes, §21.3)"
        )
    resolved_status = status if status is not None else spec.statuses[0]
    resolved_action = action if action is not None else spec.remediation_action
    remediation: dict[str, Any] | None = None
    if hint is not None or resolved_action is not None:
        remediation = {}
        if hint is not None:
            remediation["hint"] = hint
        if resolved_action is not None:
            remediation["action"] = resolved_action
    return ResultItem(
        item=item,
        status=resolved_status,
        ids=dict(ids) if ids else {},
        code=code,
        category=spec.tier,
        output=output,
        context=context,
        remediation=remediation,
    )
