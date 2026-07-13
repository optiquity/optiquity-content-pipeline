"""The parallelism machinery (§22): the wave plan, the completeness sweep, the §22.6 wiring.

Design authority: `docs/design.md`
  §22.1 — disjointness by identity: distinct ids ⇒ distinct output files ⇒ collision-free by
          construction; the only shared mutable write targets are folio membership and the
          SSOT row (both bookkeeping, never a generation gate).
  §22.2 — the plan is a WAVE-STRUCTURED DAG WITH SHARD TAGS (PC1): an ordered list of waves
          (wave = dependency depth); each wave a set of mutually independent id-keyed units;
          each unit carries `prereqs` (ids that must exist first) + a `shard` tag (its root
          artifact-id); the plan carries `suggested_width` (§22.5). **v1 exposes exactly two
          waves:** wave 0 = compose (keyed by artifact-id), wave 1 = render (keyed by
          deliverable-id). The `prereqs`/`shard` fields absorb future cross-item edges with
          zero structural change. Obtained via `begin-session(want_parallel_plan=true)` — no
          new verb. **PC2:** a deterministic, exactly-once cover — a missed item is detectable
          by re-resolve + diff (expected ids ∖ materialized ids), NOT by a tracker.
  §22.3 — the completeness SWEEP re-resolves the plan and diffs against MATERIALIZED ids;
          it doubles as the WAVE BARRIER (a wave is done when `materialized ∪ blocked =
          expected`). Blocked ≠ missing (§6.4 items are visible, not lost).
  §22.5 — `suggested_width = min(wave-unit-count, instance cap)` (PC8); the account cap is the
          true ceiling, with an optional per-workspace sub-limit BENEATH it.
  §22.6 — the parallel-path codes (PC9): `already-materialized` · `claim-held` ·
          `lease-expired-redrive` · `plan-stale` · `collision-averted` ·
          `rate-limit-backpressure`. This module WIRES them from spine/claim outcomes using
          the EXISTING `results.CODE_*` constants — it NEVER adds a code (the taxonomy is
          CLOSED).
  §22.7 — **INV-CORRECTNESS (PC12): this module is a CORRECTNESS ROOT and is strictly
          SSOT-FREE.** Correctness rides the content-addressed store + claims + spine ONLY;
          the SSOT is a derived convenience and never gates control flow. The sweep computes
          `expected`/`materialized`/`blocked` from the STORE (`is_done` = output existence),
          NEVER from the SSOT. The `tests/test_inv_correctness.py` import lint reserves
          `"parallel"` as a root and BITES the instant this file imports any `*ssot*` module,
          transitively — so every import below is deliberately ssot-clean (plan/store/claims/
          spine/results/opdefaults are all leaves w.r.t. the SSOT plane).

The blocked set is the SWEEP'S OWN (§24): it is SUPPLIED by the caller (from the run's block
ResultItems), never READ BACK from the SSOT (§22.7). `materialized` and `expected` are the
only things the sweep computes, and both come from the store + the re-resolved plan.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from pipeline import opdefaults
from pipeline.api import results
from pipeline.plan import Plan
from pipeline.spine import SpineResult
from pipeline.store import WorkspaceStore, is_done

__all__ = [
    "SweepResult",
    "Wave",
    "WavePlan",
    "WaveProgress",
    "WaveUnit",
    "backpressure_result",
    "build_wave_plan",
    "default_cap",
    "plan_stale_result",
    "result_for_spine",
    "sweep",
    "wave_plan_payload",
]

#: The two v1 wave kinds (§22.2). Wave 0 composes (keyed by artifact-id); wave 1 renders
#: (keyed by deliverable-id).
WAVE_COMPOSE = "compose"
WAVE_RENDER = "render"


# ---------------------------------------------------------------------------
# The wave-structured plan (§22.2) — one structure, three readings.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaveUnit:
    """One id-keyed unit of a wave (§22.2). `id` is the settled work-unit id (claim key =
    output key, §22.1). `prereqs` are ids that must EXIST first (v1: a render unit's compose
    artifact; wave 0 units have none — no cross-item edges in v1, §22.1). `shard` is the unit's
    ROOT artifact-id — the tag that groups an item's compose + renders into one row-per-item
    n8n chain (§22.2)."""

    id: str
    prereqs: tuple[str, ...]
    shard: str


@dataclass(frozen=True)
class Wave:
    """One dependency-depth wave (§22.2): a set of mutually independent id-keyed units, plus
    the wave's `suggested_width = min(len(units), cap)` (§22.5)."""

    index: int
    kind: str
    key: str  # the human name of the id kind these units are keyed by
    units: tuple[WaveUnit, ...]
    suggested_width: int


@dataclass(frozen=True)
class WavePlan:
    """The §22.2 wave-structured DAG. `plan_hash` ties it to the immutable plan-context (the
    token carries the same hash; under parallel mode workers coordinate through the store/
    claims, NEVER by mutating the token — §22.4). `suggested_width` is the plan-level advice:
    `min(widest wave's unit count, instance cap)` (§22.5). `instance_cap` is the effective cap
    used (`min(account cap, per-workspace sub-limit)`)."""

    plan_hash: str
    waves: tuple[Wave, ...]
    suggested_width: int
    instance_cap: int


def default_cap() -> int:
    """The effective per-workspace concurrency cap (§22.5): the account ceiling, tightened by
    the optional per-workspace sub-limit beneath it (`min` — the sub-limit never RAISES the
    account cap). Reads the ops-default constants (`pipeline.opdefaults`)."""
    return min(opdefaults.MAX_PARALLEL_SESSIONS, opdefaults.MAX_PARALLEL_PER_WORKSPACE)


def _suggested(unit_count: int, cap: int) -> int:
    """`suggested_width = min(unit-count, cap)` (§22.5 PC8), floored at 0 for an empty wave."""
    return max(0, min(unit_count, cap))


def build_wave_plan(plan: Plan, *, cap: int | None = None) -> WavePlan:
    """Derive the §22.2 wave plan from a resolved `Plan` (PC1). Pure and deterministic —
    keyed by the plan's already-settled ids, so it is itself an exactly-once cover (PC2).

    Wave 0 = compose, one unit per artifact-id (`prereqs=()`, `shard=`the artifact-id itself).
    Wave 1 = render, one unit per deliverable-id (`prereqs=(the compose artifact-id,)`,
    `shard=`that artifact-id). `cap` defaults to the effective ops cap (`default_cap`)."""
    resolved_cap = default_cap() if cap is None else cap

    compose_units = tuple(
        WaveUnit(id=item.artifact_id, prereqs=(), shard=item.artifact_id) for item in plan.items
    )
    render_units = tuple(
        WaveUnit(id=d.deliverable_id, prereqs=(item.artifact_id,), shard=item.artifact_id)
        for item in plan.items
        for d in item.deliverables
    )
    waves = (
        Wave(
            index=0,
            kind=WAVE_COMPOSE,
            key="artifact-id",
            units=compose_units,
            suggested_width=_suggested(len(compose_units), resolved_cap),
        ),
        Wave(
            index=1,
            kind=WAVE_RENDER,
            key="deliverable-id",
            units=render_units,
            suggested_width=_suggested(len(render_units), resolved_cap),
        ),
    )
    widest = max((len(w.units) for w in waves), default=0)
    return WavePlan(
        plan_hash=plan.plan_hash,
        waves=waves,
        suggested_width=_suggested(widest, resolved_cap),
        instance_cap=resolved_cap,
    )


def wave_plan_payload(wave_plan: WavePlan) -> dict[str, Any]:
    """The canonical (JSON-native) wave-plan projection for the wire (§13/§22.2) — the shape
    `begin-session(want_parallel_plan=true)` returns."""
    return {
        "plan_hash": wave_plan.plan_hash,
        "suggested_width": wave_plan.suggested_width,
        "instance_cap": wave_plan.instance_cap,
        "waves": [
            {
                "index": wave.index,
                "kind": wave.kind,
                "key": wave.key,
                "suggested_width": wave.suggested_width,
                "units": [
                    {"id": unit.id, "prereqs": list(unit.prereqs), "shard": unit.shard}
                    for unit in wave.units
                ],
            }
            for wave in wave_plan.waves
        ],
    }


# ---------------------------------------------------------------------------
# The completeness sweep + wave barrier (§22.3/PC5) — STORE-ONLY, ssot-free.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WaveProgress:
    """One wave's completeness view (§22.3). `expected` = the wave's unit ids; `materialized`
    = those whose OUTPUT EXISTS (`is_done`, store-only, §22.7); `blocked` = expected ids the
    CALLER declared blocked (the sweep's own set, never the SSOT); `missing` = expected ∖
    materialized ∖ blocked — a unit neither materialized nor blocked (the deliberately-missed
    unit, surfaced, never silently 'done'). `complete` = the WAVE BARRIER: `missing == ()`
    ⇔ `materialized ∪ blocked = expected`."""

    index: int
    kind: str
    expected: tuple[str, ...]
    materialized: tuple[str, ...]
    blocked: tuple[str, ...]
    missing: tuple[str, ...]
    complete: bool


@dataclass(frozen=True)
class SweepResult:
    """The whole-plan sweep (§22.3/PC5): the union across waves plus the per-wave barrier.
    `complete` iff EVERY wave's barrier is satisfied. `missing` is the anti-silent-gap surface
    — any expected unit neither materialized nor blocked appears here, never silently done."""

    expected: tuple[str, ...]
    materialized: tuple[str, ...]
    blocked: tuple[str, ...]
    missing: tuple[str, ...]
    complete: bool
    waves: tuple[WaveProgress, ...]


def _sweep_wave(
    wave: Wave, store: WorkspaceStore, blocked: frozenset[str]
) -> WaveProgress:
    materialized: list[str] = []
    blocked_here: list[str] = []
    missing: list[str] = []
    for unit in wave.units:
        if is_done(store, unit.id):  # output existence ONLY — §22.7 (never the SSOT)
            materialized.append(unit.id)
        elif unit.id in blocked:
            blocked_here.append(unit.id)
        else:
            missing.append(unit.id)  # neither materialized nor blocked → the surfaced gap
    return WaveProgress(
        index=wave.index,
        kind=wave.kind,
        expected=tuple(unit.id for unit in wave.units),
        materialized=tuple(materialized),
        blocked=tuple(blocked_here),
        missing=tuple(missing),
        complete=not missing,
    )


def sweep(
    wave_plan: WavePlan,
    store: WorkspaceStore,
    *,
    blocked: Iterable[str] = (),
) -> SweepResult:
    """Run the completeness sweep over a wave plan (§22.3/PC5) — the anti-silent-gap guarantee.

    Reads `materialized` from OUTPUT EXISTENCE (`is_done`, store-only) and `expected` from the
    wave plan (a re-resolved plan, upstream); `blocked` is the CALLER'S set (from the run's
    block ResultItems — the sweep's own, never the SSOT, §22.7/§24). A unit that is neither
    materialized nor in `blocked` lands in `missing` and is SURFACED — never silently counted
    done. `complete` (the wave barrier) holds iff every wave's `materialized ∪ blocked =
    expected`."""
    blocked_set = frozenset(blocked)
    waves = tuple(_sweep_wave(wave, store, blocked_set) for wave in wave_plan.waves)
    expected = tuple(uid for w in waves for uid in w.expected)
    materialized = tuple(uid for w in waves for uid in w.materialized)
    blocked_all = tuple(uid for w in waves for uid in w.blocked)
    missing = tuple(uid for w in waves for uid in w.missing)
    return SweepResult(
        expected=expected,
        materialized=materialized,
        blocked=blocked_all,
        missing=missing,
        complete=all(w.complete for w in waves),
        waves=waves,
    )


# ---------------------------------------------------------------------------
# §22.6 parallel-path code wiring — from spine/claim outcomes to ResultItems.
# The taxonomy is CLOSED: this only USES the existing `results.CODE_*` constants.
# ---------------------------------------------------------------------------


def result_for_spine(
    spine_result: SpineResult, *, item: str | None = None
) -> results.ResultItem:
    """Map one `SpineResult` to its §22.6 ResultItem, using the EXISTING codes (never a new one).

    - `claim-held` (warn) — a live lease skipped the unit (`SpineResult.code == "claim-held"`).
    - `already-materialized` (ok) — the S0 short-circuit: the id was already done.
    - `collision-averted` (warn) — our S3 no-replace commit LOST to another committer
      (`materialized is False`, not a short-circuit): a write collision averted, exactly one
      winner (§22.3/B4-4).
    - `lease-expired-redrive` (ok) — we STOLE an expired lease and materialized the id
      (`claim.code == lease-expired-redrive`).
    - a plain `ok` (no §22.6 code) — we materialized under a fresh claim (the common win).
    """
    label = item if item is not None else spine_result.id
    ids = {"id": spine_result.id}
    stolen = (
        spine_result.claim is not None
        and spine_result.claim.code == results.CODE_LEASE_EXPIRED_REDRIVE
    )
    if spine_result.code == "claim-held":
        holder = spine_result.claim.holder if spine_result.claim is not None else None
        return results.make_result(
            results.CODE_CLAIM_HELD,
            item=label,
            ids=ids,
            context={"holder": holder} if holder is not None else None,
            hint="another worker holds a live claim on this id — move on or poll by id (§22.3)",
        )
    if spine_result.short_circuit:
        return results.make_result(
            results.CODE_ALREADY_MATERIALIZED, item=label, ids=ids
        )
    if not spine_result.materialized:
        return results.make_result(
            results.CODE_COLLISION_AVERTED,
            item=label,
            ids=ids,
            hint="a concurrent no-replace commit won this id — exactly one winner (§22.3)",
        )
    if stolen:
        return results.make_result(
            results.CODE_LEASE_EXPIRED_REDRIVE, item=label, ids=ids
        )
    return results.ResultItem(item=label, status="ok", ids=ids)


def backpressure_result(
    *,
    item: str,
    observed_inflight: int,
    retry_after: float | None = None,
    status: str = "warn",
) -> results.ResultItem:
    """The §22.5/§22.6 `rate-limit-backpressure` ResultItem — a subscription limit surfaced as
    TYPED backpressure (never a crash, PC8). `remediation.action = retry-after`; the delay
    rides `context.retry_after`. `status` may be `block` when the unit cannot proceed at all."""
    context: dict[str, Any] = {"observed_inflight": observed_inflight}
    if retry_after is not None:
        context["retry_after"] = retry_after
    return results.make_result(
        results.CODE_RATE_LIMIT_BACKPRESSURE,
        item=item,
        status=status,
        context=context,
        hint="the subscription applied backpressure — retry after the delay or reduce width",
    )


def plan_stale_result(
    *, item: str, plan_hash_token: str, plan_hash_current: str
) -> results.ResultItem:
    """The §22.6 `plan-stale` ResultItem — a plan-hash mismatch on re-resolve (warn). The sweep
    reconciles; never a silent skip/dup. Re-fetch the plan / re-begin the session (§21.6)."""
    return results.make_result(
        results.CODE_PLAN_STALE,
        item=item,
        context={
            "plan_hash_token": plan_hash_token,
            "plan_hash_current": plan_hash_current,
        },
        hint="the plan changed since the token was minted — re-fetch the plan (§21.6/§22.6)",
    )
