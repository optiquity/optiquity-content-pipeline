"""The SPEND-verb transport RESOLVER — the ONE place a transport MODE is chosen (plan G7, §21.10).

This is the entry-layer selector that turns "who is spending, in which zone/workspace, with what
override" into a concrete `TransportPlan` the chokepoint (`pipeline.transport`) consumes. It is the
FIRST PAID SURFACE's brain: no other module chooses subscription-vs-api-key. The precedence is a
closed cascade, applied EXACTLY once per spend run:

    override  →  cascade key (assignment.cascade_key)  →  subscription IFF entitled  →  LOUD refuse

- **override** (per-run, never identity, I3): `subscription` forces the flat-rate subscription
  (still walled, still entitled-only); `api` forces the scope's assigned key (refuse if none);
  `key:<handle>` forces a SPECIFIC assigned+capped handle. The override vocabulary is CLOSED and can
  NEVER name the entitled subscription user (there is no user token in it) — I3 is structural.
- **cascade key**: the `workspace → zone → user → global` most-specific-wins assignment (G4). A hit
  → the API-KEY path (resolve the secret via the keystore, admit against the meter, a FINITE $5
  per-call cap).
- **subscription IFF entitled**: only when the caller IS the single config-entitled subscription
  user (G5, ToS) — subscription is `per_call_cap=None` (flat-rate, S-1).
- else a LOUD typed refuse (`NoTransportError`) — never a silent guess.

**The money-safety crux lives here + at the chokepoint.** For an API-key result this module:
1. resolves the secret via the keystore `SecretResolver` (a redacting `ResolvedSecret`, never a
   value in argv/log/ledger — I5);
2. computes the worst-case `ConstructionBudget` ceiling at the FINITE per-call cap;
3. **admits** that ceiling against the assignment bucket AND the install umbrella under the G6
   inter-process lock (`meter.admit`) — a ceiling that would exceed EITHER cap raises
   `MeterRefusedError` PRE-SPEND (no hold, no plan, nothing spent);
4. carries the admitted hold's **embedded expiry** on the `TransportPlan` (the chokepoint's
   injected-clock disarm check — `transport.py` can't import the meter, so it checks the
   plan-embedded expiry, not the meter);
5. **meter-VERIFIES** the hold is live (expiry strictly ahead of the meter clock) immediately before
   returning the plan — defense-in-depth against a mis-resolved hold.

The caller (the run-admission tier) drives under the returned plan and `settle`s the accumulated
ACTUAL cost in a `finally` on EVERY exit path (`AdmittedTransport.settle`). A crash before settle
self-expires the hold at its full ceiling (the G6 TTL).

Import boundary (plan G7/G9): as the entry-layer selector this module MAY import
`pipeline.spend.{assignment,entitlement,keystore,meter,construction}` AND `pipeline.transport` (the
plan TYPE + `CostAccumulator`). It is NEVER imported by `pipeline.transport`, `compose`, `review`,
or `reconcile` (no cycle; the chokepoint consumes an opaque plan).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from pipeline.spend.assignment import (
    Assignment,
    AssignmentStore,
    ScopeKey,
    load_store,
)
from pipeline.spend.construction import ConstructionBudget
from pipeline.spend.disclose import MODE_APIKEY, MODE_SUBSCRIPTION, TransportDisclosure
from pipeline.spend.keystore import (
    FileSecretBackend,
    KeyStoreError,
    SecretHandleError,
    SecretRef,
    SecretResolver,
)
from pipeline.spend.meter import Hold, WeeklyMeter
from pipeline.transport import CostAccumulator, TransportPlan

__all__ = [
    "DEFAULT_API_PER_CALL_CAP_USD",
    "DEFAULT_UMBRELLA_CAP_USD",
    "OVERRIDE_API",
    "OVERRIDE_KEY_PREFIX",
    "OVERRIDE_SUBSCRIPTION",
    "AdmittedTransport",
    "NoTransportError",
    "NotEntitledError",
    "Override",
    "TransportOverrideError",
    "TransportResolutionError",
    "parse_override",
    "preview_transport",
    "resolve_transport",
]

#: The maintainer-set DEFAULT api-key per-call cap ($5.00, FINITE): every paid call spawns under
#: `--max-budget-usd = min(caller, this)`, so loop-caps × this is a true spend wall. Subscription
#: stays `per_call_cap=None` (flat-rate). A finite, exact `Decimal` — money is never float here.
DEFAULT_API_PER_CALL_CAP_USD = Decimal("5.00")

#: The maintainer-set DEFAULT install UMBRELLA weekly cap ($50.00) used at admit when the install
#: has set no explicit `set-umbrella-cap` (a real positive budget, never uncapped). A per-KEY weekly
#: cap stays HARD-required at assign-key (S3) — there is NO per-key default.
DEFAULT_UMBRELLA_CAP_USD = Decimal("50.00")

#: The CLOSED per-run override vocabulary (I3 — never names a user, only a MODE / a handle).
OVERRIDE_SUBSCRIPTION = "subscription"
OVERRIDE_API = "api"
OVERRIDE_KEY_PREFIX = "key:"


class TransportResolutionError(RuntimeError):
    """Base: the resolver hit a state it must refuse LOUDLY, never guess through (§3.1)."""

    code = "transport-resolution-error"


class TransportOverrideError(TransportResolutionError):
    """The per-run `--transport` override is not a member of the closed vocabulary
    (`subscription` | `api` | `key:<namespace>:<name>`) — refused, nothing resolved (I3)."""

    code = "bad-transport-override"


class NotEntitledError(TransportResolutionError):
    """Subscription was SELECTED (by override or fallback) for a user who is NOT the single
    config-entitled subscription user — refused (ToS: the subscription serves only that one user).
    NO secret, no spend, no plan."""

    code = "not-entitled"

    def __init__(self, user: object) -> None:
        super().__init__(
            f"not-entitled: user {user!r} is not the single entitled subscription user, so the "
            "subscription transport may not be used for them (ToS, G5) — assign an api key to this "
            "scope, or name the entitled user with `transport set-subscription-user`. Refusing "
            "(no spend)."
        )
        self.user = user


class NoTransportError(TransportResolutionError):
    """No transport could be selected: no cascade key is assigned to the scope, the caller is not
    the entitled subscription user, and no (satisfiable) override was given — a LOUD typed refuse,
    the money-safety-first default (never a silent guess). NO secret, no spend, no plan."""

    code = "no-transport"


# ---------------------------------------------------------------------------
# The per-run override (I3 — a MODE selector; it can never name the subscription USER)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Override:
    """A parsed per-run transport override. `mode` is `"subscription"` / `"api"` / `"key"`; `handle`
    is the specific assigned `SecretRef` for `mode == "key"` (else None). It selects a MODE (or a
    specific assigned handle) — NEVER a user (there is no user token in the vocabulary), so it can
    never re-point WHO is entitled to the subscription (I3, structural)."""

    mode: Literal["subscription", "api", "key"]
    handle: SecretRef | None = None


def parse_override(raw: object) -> Override | None:
    """Parse a per-run override string into an `Override`, or `None` when absent.

    Accepts `None`/empty (no override), `"subscription"`, `"api"`, or `"key:<namespace>:<name>"`
    (the handle is validated by the keystore). An already-parsed `Override` passes through. Anything
    else is a loud `TransportOverrideError` — the vocabulary is CLOSED, never names a user (I3)."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, Override):
        return raw
    if not isinstance(raw, str):
        raise TransportOverrideError(
            f"bad-transport-override: the transport override must be a string "
            f"(subscription | api | key:<namespace>:<name>), got {type(raw).__name__}"
        )
    if raw == OVERRIDE_SUBSCRIPTION:
        return Override("subscription")
    if raw == OVERRIDE_API:
        return Override("api")
    if raw.startswith(OVERRIDE_KEY_PREFIX):
        handle_str = raw[len(OVERRIDE_KEY_PREFIX) :]
        try:
            ref = SecretRef.parse(handle_str)
        except SecretHandleError as exc:
            raise TransportOverrideError(
                f"bad-transport-override: key override {raw!r} — {exc}"
            ) from None
        return Override("key", ref)
    raise TransportOverrideError(
        f"bad-transport-override: {raw!r} is not a valid transport override — use "
        f"{OVERRIDE_SUBSCRIPTION!r}, {OVERRIDE_API!r}, or 'key:<namespace>:<name>' (the override "
        "names a MODE or an assigned handle, NEVER a user — I3)"
    )


# ---------------------------------------------------------------------------
# The admitted result — the plan for the chokepoint + the hold/meter for settle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmittedTransport:
    """The resolver's result: the `TransportPlan` the chokepoint consumes, plus the admitted meter
    `hold` + `meter` the run-admission tier settles in a `finally`.

    - subscription: `plan.mode == "subscription"`, `hold is None`, `meter is None` — flat-rate, no
      metering, nothing to settle.
    - api-key: `plan.mode == "apikey"` carrying the FINITE per-call cap + the resolved secret + the
      admitted hold's embedded expiry; `hold`/`meter` are set so `settle(actual)` appends the
      settled ledger line and drops the hold. Call `settle` in a `finally` on EVERY exit path (a
      crash before settle self-expires the hold at its full ceiling, G6 TTL).

    It ALSO carries the READ-ONLY disclosure provenance (plan G8) — the worst-case `budget`, the
    charged `scope` + `handle`, and the bucket + umbrella caps — so `disclose()` reflects the REAL
    admitted plan (never a second, possibly-disagreeing store read) and reads the live headroom off
    the SAME meter it admitted against. The `handle` is a NON-secret `SecretRef` (I5)."""

    plan: TransportPlan
    hold: Hold | None
    meter: WeeklyMeter | None
    budget: ConstructionBudget | None = None
    scope: ScopeKey | None = None
    handle: SecretRef | None = None
    bucket_cap: Decimal | None = None
    umbrella_cap: Decimal | None = None

    def settle(self, actual_cost: object) -> None:
        """Settle the admitted hold with the ACTUAL accumulated cost (call in a `finally`). A no-op
        for the subscription path (no hold) — subscription is flat-rate, nothing is metered."""
        if self.hold is not None and self.meter is not None:
            self.meter.settle(self.hold, actual_cost)

    def disclose(self) -> TransportDisclosure:
        """The pre-spend COST DISCLOSURE for this admitted run (plan G8) — a READ-ONLY projection
        that admits NOTHING and spends NOTHING.

        For the api-key path it reads the LIVE week-to-date (settled + all live holds, incl. THIS
        run's just-written hold) off the SAME meter via the sanctioned `bucket_week_to_date` /
        `umbrella_week_to_date` reads, so the disclosed headroom (`cap − week-to-date`) reflects the
        real reservation. For the subscription path (no meter) it discloses the flat-rate mode + the
        call-count scope only (no `$` ceiling, no headroom). Emit it at the admission spot, BEFORE
        the first spawn."""
        budget = self.budget if self.budget is not None else ConstructionBudget(None, 1, 0)
        if self.plan.mode != MODE_APIKEY or self.meter is None:
            return TransportDisclosure(mode=MODE_SUBSCRIPTION, budget=budget)
        # api-key: the caps ride the result; the week-to-date is read live off the same meter.
        bucket_wtd = (
            self.meter.bucket_week_to_date(self.scope, self.handle)
            if self.scope is not None and self.handle is not None
            else None
        )
        umbrella_wtd = self.meter.umbrella_week_to_date()
        return TransportDisclosure(
            mode=MODE_APIKEY,
            budget=budget,
            scope=self.scope,
            handle=self.handle,
            bucket_cap=self.bucket_cap,
            bucket_week_to_date=bucket_wtd,
            umbrella_cap=self.umbrella_cap,
            umbrella_week_to_date=umbrella_wtd,
        )


# ---------------------------------------------------------------------------
# The resolver — the ONLY place a transport mode is chosen (plan G7)
# ---------------------------------------------------------------------------


def resolve_transport(
    framework_root: str | os.PathLike[str],
    user: str,
    zone: str,
    workspace: str | None = None,
    *,
    override: object = None,
    n_artifacts: int = 1,
    n_deliverables: int = 0,
    cost_accumulator: CostAccumulator | None = None,
    meter: WeeklyMeter | None = None,
    resolver: SecretResolver | None = None,
    run_id: str = "",
    per_call_cap: Decimal = DEFAULT_API_PER_CALL_CAP_USD,
    store: AssignmentStore | None = None,
) -> AdmittedTransport:
    """Select the transport MODE and build the admitted `TransportPlan` (G7 — the ONLY selector).

    Precedence: `override → cascade key → subscription IFF entitled → LOUD refuse`. For an api-key
    result the secret is resolved (redacting `ResolvedSecret`, never a value on argv/log), the
    worst-case ceiling (`ConstructionBudget` at the finite `per_call_cap`) is ADMITTED against the
    assignment bucket AND the umbrella under the G6 inter-process lock, and the admitted hold's
    expiry rides the plan (the chokepoint's injected-clock disarm). A cap-exceeding ceiling raises
    `MeterRefusedError` PRE-SPEND (no hold, no plan). The hold is meter-VERIFIED live immediately
    before the plan is returned.

    `n_artifacts`/`n_deliverables` size the ceiling (the run's fan-out); `cost_accumulator` is the
    ONE run-scoped total the chokepoint adds into; `meter`/`resolver`/`store` are injectable seams
    (production builds a `WeeklyMeter(root)`, a `FileSecretBackend`, and loads the shared config).
    `override` is a raw string, a parsed `Override`, or None."""
    resolved_store = load_store(framework_root) if store is None else store
    parsed = parse_override(override)
    accumulator = cost_accumulator if cost_accumulator is not None else CostAccumulator()
    entitled = _is_entitled(resolved_store, user)

    # The precedence (override → cascade → subscription-iff-entitled → refuse) is chosen ONCE, by
    # the shared `_decide` — the SAME closed cascade the dry-run `preview_transport` reads, so a
    # disclosure can never name a different mode than the spend that follows (one mode-chooser).
    decision = _decide(resolved_store, user, zone, workspace, parsed, entitled=entitled)
    if decision.mode == MODE_SUBSCRIPTION:
        return _subscription(
            user, accumulator, n_artifacts, n_deliverables, entitled=True
        )
    assert decision.assignment is not None  # _decide guarantees it for the api-key branch
    return _apikey(
        framework_root,
        resolved_store,
        decision.assignment,
        accumulator,
        meter=meter,
        resolver=resolver,
        run_id=run_id,
        per_call_cap=per_call_cap,
        n_artifacts=n_artifacts,
        n_deliverables=n_deliverables,
    )


def _is_entitled(store: AssignmentStore, user: object) -> bool:
    """The caller IS entitled to the subscription iff it is EXACTLY the single config-set
    subscription user (G5, ToS). Reads the SAME store the cascade uses (consistency — never a
    second disk read that could disagree). `None`/mismatch/empty → not entitled."""
    return isinstance(user, str) and user != "" and store.entitled_user == user


@dataclass(frozen=True)
class _Decision:
    """The transport MODE choice WITHOUT any admit/secret/spawn — the pure precedence result shared
    by `resolve_transport` (which then admits) and `preview_transport` (which discloses only).
    `assignment` is the charged bucket for `mode == MODE_APIKEY`; `None` for subscription."""

    mode: str
    assignment: Assignment | None


def _decide(
    store: AssignmentStore,
    user: str,
    zone: str,
    workspace: str | None,
    parsed: Override | None,
    *,
    entitled: bool,
) -> _Decision:
    """Apply the closed precedence `override → cascade key → subscription IFF entitled → refuse` and
    return the chosen `_Decision` — the ONLY place a transport mode is selected (G7). It admits
    nothing, resolves no secret, and spawns nothing; it raises the SAME typed refusals a spend would
    (`NotEntitledError` / `NoTransportError`), so a dry-run surfaces exactly the refusal a `--go`
    would hit."""
    # (1) OVERRIDE — the per-run selection wins (I3: a MODE / a handle, never a user).
    if parsed is not None:
        if parsed.mode == "subscription":
            if not entitled:
                raise NotEntitledError(user)
            return _Decision(MODE_SUBSCRIPTION, None)
        if parsed.mode == "api":
            assignment = store.cascade_key(user, zone, workspace)
            if assignment is None:
                raise NoTransportError(
                    f"no-transport: --transport api was forced but NO key is assigned to "
                    f"user={user!r} zone={zone!r} workspace={workspace!r} (the "
                    "workspace→zone→user→global cascade found none) — assign one with "
                    "`transport assign-key` or drop the override. Refusing (no spend)."
                )
            return _Decision(MODE_APIKEY, assignment)
        # mode == "key": a SPECIFIC assigned+capped handle (S3 — never an uncapped key).
        assert parsed.handle is not None  # parse_override guarantees it for mode == "key"
        assignment = _assignment_for_handle(store, parsed.handle)
        if assignment is None:
            raise NoTransportError(
                f"no-transport: --transport key:{parsed.handle.handle} was forced but that handle "
                "is not ASSIGNED with a weekly cap at any scope (S3 — no uncapped key). Assign it "
                "with `transport assign-key --handle … --weekly-cap …`, or drop the override. "
                "Refusing (no spend)."
            )
        return _Decision(MODE_APIKEY, assignment)

    # (2) CASCADE KEY — the most-specific-wins assignment (workspace→zone→user→global).
    assignment = store.cascade_key(user, zone, workspace)
    if assignment is not None:
        return _Decision(MODE_APIKEY, assignment)

    # (3) SUBSCRIPTION IFF entitled — the flat-rate fallback for the ONE entitled user (G5).
    if entitled:
        return _Decision(MODE_SUBSCRIPTION, None)

    # (4) else — a LOUD typed refuse (money-safety-first; never a silent guess, §3.1).
    raise NoTransportError(
        f"no-transport: user={user!r} zone={zone!r} workspace={workspace!r} has NO assigned key "
        "(the workspace→zone→user→global cascade found none) and is NOT the entitled subscription "
        "user — there is no transport to spend on. Assign a key (`transport assign-key`) or name "
        "the entitled user (`transport set-subscription-user`). Refusing (no spend)."
    )


def preview_transport(
    framework_root: str | os.PathLike[str],
    user: str,
    zone: str,
    workspace: str | None = None,
    *,
    override: object = None,
    n_artifacts: int = 1,
    n_deliverables: int = 0,
    meter: WeeklyMeter | None = None,
    per_call_cap: Decimal = DEFAULT_API_PER_CALL_CAP_USD,
    store: AssignmentStore | None = None,
) -> TransportDisclosure:
    """Build the DRY-RUN cost disclosure WITHOUT admitting or spending (plan G8).

    Runs the SAME closed precedence (`_decide`) `resolve_transport` runs — so the disclosed mode/
    bucket can never disagree with the spend a `--go` would make — but stops at the DECISION: it
    resolves NO secret, writes NO hold, spawns nothing. For an api-key decision it sizes the
    worst-case `ConstructionBudget` ceiling at the finite `per_call_cap` and reads the LIVE headroom
    (`cap − week-to-date`, settled + all live holds) off the meter via the sanctioned READ-ONLY
    `bucket_week_to_date` / `umbrella_week_to_date` (no admit). It raises the SAME typed refusals a
    spend would (`NotEntitledError` / `NoTransportError` / `TransportOverrideError`), so a dry-run
    surfaces exactly the refusal a `--go` would hit. A dry-run never touches the secret, so it takes
    no `SecretResolver`."""
    resolved_store = load_store(framework_root) if store is None else store
    parsed = parse_override(override)
    entitled = _is_entitled(resolved_store, user)
    decision = _decide(resolved_store, user, zone, workspace, parsed, entitled=entitled)
    if decision.mode == MODE_SUBSCRIPTION:
        budget = ConstructionBudget(
            per_call_usd=None, n_artifacts=n_artifacts, n_deliverables=n_deliverables
        )
        return TransportDisclosure(mode=MODE_SUBSCRIPTION, budget=budget)

    assignment = decision.assignment
    assert assignment is not None  # _decide guarantees it for the api-key branch
    the_meter = meter if meter is not None else WeeklyMeter(root=framework_root)
    umbrella = resolved_store.umbrella_cap_usd
    if umbrella is None:
        umbrella = DEFAULT_UMBRELLA_CAP_USD
    budget = ConstructionBudget(
        per_call_usd=float(per_call_cap),
        n_artifacts=n_artifacts,
        n_deliverables=n_deliverables,
    )
    # READ-ONLY headroom reads — NO admit, NO hold written, NO spawn (spends nothing).
    bucket_wtd = the_meter.bucket_week_to_date(assignment.scope, assignment.handle)
    umbrella_wtd = the_meter.umbrella_week_to_date()
    return TransportDisclosure(
        mode=MODE_APIKEY,
        budget=budget,
        scope=assignment.scope,
        handle=assignment.handle,
        bucket_cap=assignment.weekly_cap_usd,
        bucket_week_to_date=bucket_wtd,
        umbrella_cap=umbrella,
        umbrella_week_to_date=umbrella_wtd,
    )


def _subscription(
    user: str,
    accumulator: CostAccumulator,
    n_artifacts: int,
    n_deliverables: int,
    *,
    entitled: bool,
) -> AdmittedTransport:
    """Build the flat-rate SUBSCRIPTION result — IFF the caller is the single entitled user (ToS).

    A non-entitled subscription selection is a loud `NotEntitledError` (no spend). The subscription
    plan is `per_call_cap=None` (S-1: flat-rate, no finite cap → no artifact truncation); it carries
    NO hold + NO meter (nothing to admit or settle — subscription is not metered here). The
    `budget` rides for the G8 disclosure only — `per_call_usd=None` renders the flat-rate call-count
    scope, never a `$` ceiling."""
    if not entitled:
        raise NotEntitledError(user)
    plan = TransportPlan.subscription(cost_accumulator=accumulator)
    budget = ConstructionBudget(
        per_call_usd=None, n_artifacts=n_artifacts, n_deliverables=n_deliverables
    )
    return AdmittedTransport(plan=plan, hold=None, meter=None, budget=budget)


def _apikey(
    framework_root: str | os.PathLike[str],
    store: AssignmentStore,
    assignment: Assignment,
    accumulator: CostAccumulator,
    *,
    meter: WeeklyMeter | None,
    resolver: SecretResolver | None,
    run_id: str,
    per_call_cap: Decimal,
    n_artifacts: int,
    n_deliverables: int,
) -> AdmittedTransport:
    """Build the API-KEY result: resolve the secret, ADMIT the worst-case ceiling against the
    assignment bucket + the umbrella (G6 lock), and carry the admitted hold's expiry on the plan.

    Resolving the secret returns a redacting `ResolvedSecret` (I5 — never a value on argv/log/
    ledger); only its `.reveal` bound method rides the plan (the chokepoint calls it at the
    injection point). The ceiling is `per_call_cap × total_call_budget` (exact `Decimal`, the
    ×attempts-per-stage worst case, S-5), so the disclosed/admitted number never understates. A
    cap-exceeding ceiling raises `MeterRefusedError` PRE-SPEND (no hold, no plan). The hold is
    meter-VERIFIED live (expiry strictly ahead of the meter clock) before the plan is returned."""
    the_resolver = resolver if resolver is not None else FileSecretBackend()
    try:
        secret = the_resolver.resolve(assignment.handle)  # ResolvedSecret; redacts (I5)
    except KeyStoreError:
        raise  # a typed miss / perms refusal naming ONLY the handle — never a value (I5)

    the_meter = meter if meter is not None else WeeklyMeter(root=framework_root)
    umbrella = store.umbrella_cap_usd
    if umbrella is None:
        umbrella = DEFAULT_UMBRELLA_CAP_USD  # the install default ($50/week) when unset

    # The worst-case COUNT of per-call-capped calls (×attempts at every stage, Review-1 included),
    # times the FINITE per-call cap → the exact-Decimal money ceiling to admit.
    budget = ConstructionBudget(
        per_call_usd=float(per_call_cap),
        n_artifacts=n_artifacts,
        n_deliverables=n_deliverables,
    )
    ceiling = per_call_cap * budget.total_call_budget

    hold = the_meter.admit(
        scope=assignment.scope,
        handle=assignment.handle,
        bucket_cap=assignment.weekly_cap_usd,
        umbrella_cap=umbrella,
        ceiling=ceiling,
        run_id=run_id or _mint_run_id(),
    )
    # Meter-VERIFY the hold is live immediately before building the plan (defense-in-depth against a
    # mis-resolved / already-expired hold — the chokepoint disarms ONLY under a live hold).
    if not hold.expiry > the_meter.clock():
        raise TransportResolutionError(
            "transport-resolution-error: the meter admitted a hold whose expiry is not ahead of "
            "the meter clock — refusing to build a paid plan on a non-live hold (fail-closed)."
        )

    plan = TransportPlan.apikey(
        cost_accumulator=accumulator,
        per_call_cap=float(per_call_cap),
        api_key_reveal=secret.reveal,  # the ONLY seam that exposes the bytes, at injection (I5)
        hold_expiry=hold.expiry,
    )
    return AdmittedTransport(
        plan=plan,
        hold=hold,
        meter=the_meter,
        # The G8 disclosure provenance — the worst-case budget + the charged bucket/handle/caps, so
        # `disclose()` reflects the REAL admitted plan (the handle is a NON-secret SecretRef, I5).
        budget=budget,
        scope=assignment.scope,
        handle=assignment.handle,
        bucket_cap=assignment.weekly_cap_usd,
        umbrella_cap=umbrella,
    )


def _assignment_for_handle(store: AssignmentStore, ref: SecretRef) -> Assignment | None:
    """The assignment for a SPECIFIC handle (the `key:<handle>` override). Among all scopes that
    assign this handle, choose the SMALLEST weekly cap (most conservative — money-safety-first); its
    scope is the bucket charged. `None` when the handle is assigned nowhere (→ refuse, S3)."""
    matches = [a for a in store.assignments if a.handle == ref]
    if not matches:
        return None
    return min(matches, key=lambda a: a.weekly_cap_usd)


def _mint_run_id() -> str:
    """A collision-resistant opaque run id for the meter ledger/hold record (diagnostic only — never
    a workspace/client identifier, never entering an id preimage)."""
    return f"spend-{os.getpid()}-{os.urandom(8).hex()}"
