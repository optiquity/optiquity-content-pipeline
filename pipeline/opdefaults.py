"""Framework ops-default constants (§22.5/§22.8/§27.4): the G2-validated concurrency finals.

Design authority: `docs/design.md` §22.5 (`max_parallel_sessions` is INSTANCE/account-scoped;
an optional per-workspace sub-limit may sit BENEATH it, never replace it), §22.8 (lease TTL +
`max_parallel_sessions` are validated against the §22.5 telemetry dataset — gate G2, not
guessed), §27.2 (gate G2, CLOSED), §27.4 (the registered "Lease-TTL + `max_parallel_sessions`
conservative defaults" build item); plan steps 36–38.

**This module is a CLEAN, ISOLATED constants surface — no logic, no imports.** It is a
named constant per line so the two G2 numbers stay a flat, auditable value table with nothing
else to disturb. The invariants BETWEEN the constants (e.g. wrapper timeout < lease TTL) are
asserted in the tests (`tests/test_telemetry.py`), and the G2-equality lock — the loaded runtime
defaults equal the telemetry-measured numbers — in `tests/test_opdefaults.py`; never wired into
this module, keeping the edit surface a flat value table.

**The two G2-VALIDATED finals (gate G2 CLOSED — step-37 report, §27.2 — measured against the
§22.5 telemetry dataset, NOT guessed). Both equal the step-4 seeds, now confirmed by real data:**

- `MAX_PARALLEL_SESSIONS = 3` — the account-wide in-flight ceiling (§22.5 PC8). G2 sustained 3
  concurrent inflight subscription calls with ZERO backpressure (observed peak_inflight=3, 0
  onsets); the bounded probe tested AT the cap, so there is no evidence to raise it and none to
  lower it. This, not the data, is the true concurrency ceiling: wave units are independent, so
  the subscription is the constraint. Per-workspace caps do not compose across shared accounts.
- `LEASE_TTL_SECONDS = 1800` (30 min) — the claim/presence lease TTL (§22.3/§22.8), G2-validated:
  anchored ABOVE the 1200 s wrapper timeout, with observed call latency (~8-12 s) sitting ~150×
  under the TTL — a large downward safety margin, and lowering it below the timeout would break
  the dead-process invariant. Mirrors `claims.DEFAULT_LEASE_TTL_SECONDS` (this module is the ops
  source of record that wires it).

**Companion constants — OUTSIDE G2's two-number scope, unchanged:**

- `MAX_PARALLEL_PER_WORKSPACE = 2` — the OPTIONAL per-workspace sub-limit that sits BENEATH the
  instance cap (§22.5). It never replaces the account cap; the effective width a single
  workspace's plan suggests is `min(MAX_PARALLEL_SESSIONS, MAX_PARALLEL_PER_WORKSPACE)`.
- `WRAPPER_HARD_TIMEOUT_SECONDS = 1200` (20 min) — the per-invocation wrapper hard timeout.
  STRICTLY LESS THAN `LEASE_TTL_SECONDS` (invariant still satisfied post-G2): timeout < TTL means
  an EXPIRED lease implies a DEAD process (a live process would have been killed by its own
  timeout before its lease lapsed), so a lease-expired steal is safe against a merely-slow holder
  by policy as well as by the §22.3 primitives.
- `TELEMETRY_ENABLED_DEFAULT = True` — capture is default-on and disable-able (§22.5 PC11).
- `RECOMMENDED_WIDTH_WINDOW_SECONDS = 3600` (1 h) — the recent telemetry window the advisory
  `recommended_width` reads (§22.5); never auto-applied.
- `STARTUP_GRACE_SECONDS = 120` (2 min) — the DR-1 async job's 202→S1 SPAWN WINDOW: the time a
  freshly-submitted job record is treated as RUNNING BEFORE its detached runner acquires its
  first S1 claim (`pipeline.jobs`). It must EXCEED the observed spawn→first-claim latency (spawn
  + handler entry + grounding/resolution + `claims.acquire`) so a legitimately-starting runner is
  never re-driven, and sit FAR BELOW `WRAPPER_HARD_TIMEOUT_SECONDS` (1200 s) so a genuinely dead
  pre-claim runner becomes stealable long before its own hard timeout would matter. Outside G2's
  two-number scope; a lossy-bookkeeping grace, not a correctness authority (§22.7 — output
  existence + the S1 claim/lease remain the sole DONE / exactly-once authorities).
"""

from __future__ import annotations

__all__ = [
    "LEASE_TTL_SECONDS",
    "MAX_PARALLEL_PER_WORKSPACE",
    "MAX_PARALLEL_SESSIONS",
    "RECOMMENDED_WIDTH_WINDOW_SECONDS",
    "STARTUP_GRACE_SECONDS",
    "TELEMETRY_ENABLED_DEFAULT",
    "WRAPPER_HARD_TIMEOUT_SECONDS",
]

#: Account-wide in-flight session ceiling (§22.5 PC8). G2-VALIDATED final (step-37; §27.2).
MAX_PARALLEL_SESSIONS = 3

#: Optional per-workspace sub-limit BENEATH the instance cap (§22.5); never replaces it.
MAX_PARALLEL_PER_WORKSPACE = 2

#: Claim/presence lease TTL, seconds (§22.3/§22.8) — 30 min. G2-VALIDATED final (step-37; §27.2).
LEASE_TTL_SECONDS = 1800

#: Per-invocation wrapper hard timeout, seconds (§22.8) — 20 min; STRICTLY < LEASE_TTL_SECONDS
#: (out of G2's two-number scope; the timeout < TTL dead-process invariant still holds post-G2).
WRAPPER_HARD_TIMEOUT_SECONDS = 1200

#: Telemetry capture default-on, disable-able (§22.5 PC11).
TELEMETRY_ENABLED_DEFAULT = True

#: The recent telemetry window the advisory `recommended_width` reads, seconds (§22.5) — 1 h.
RECOMMENDED_WIDTH_WINDOW_SECONDS = 3600

#: DR-1 async job 202→S1 spawn window, seconds — 2 min. The grace during which a just-submitted
#: job record counts as RUNNING before its detached runner acquires its first S1 claim
#: (`pipeline.jobs`). EXCEEDS the observed spawn→first-claim latency (so a starting runner is not
#: re-driven) and STRICTLY < WRAPPER_HARD_TIMEOUT_SECONDS (so a dead pre-claim runner is stealable
#: well before its own timeout). Lossy-bookkeeping grace, never a §22.7 correctness authority.
STARTUP_GRACE_SECONDS = 120
