"""Framework ops-default constants (§22.5/§22.8/§27.4): the conservative G2 seeds.

Design authority: `docs/design.md` §22.5 (`max_parallel_sessions` is INSTANCE/account-scoped;
an optional per-workspace sub-limit may sit BENEATH it, never replace it), §22.8 (lease TTL +
`max_parallel_sessions` ship as conservative ops defaults; the subscription's real
concurrency/rate limits are validated against the §22.5 telemetry dataset — gate G2, not
guessed), §27.4 (the registered "Lease-TTL + `max_parallel_sessions` conservative defaults"
build item); plan step 36.

**This module is a CLEAN, ISOLATED constants surface — no logic, no imports.** It is a
named constant per line so that **step 38 can micro-edit exactly these values** with the G2
telemetry-validated finals as a one-line-per-constant diff, with nothing else to disturb.
The invariants BETWEEN the constants (e.g. wrapper timeout < lease TTL) are asserted in the
tests (`tests/test_telemetry.py`), never wired into this module — keeping the edit surface a
flat value table.

**The G2 PRELIMINARY seed values (gate-4 conservative — deliberately low; step 38 finalizes):**

- `MAX_PARALLEL_SESSIONS = 3` — the account-wide in-flight ceiling (§22.5 PC8). This, not the
  data, is the true concurrency ceiling: wave units are independent, so the subscription is
  the constraint. Per-workspace caps do not compose across workspaces sharing one account.
- `MAX_PARALLEL_PER_WORKSPACE = 2` — the OPTIONAL per-workspace sub-limit that sits BENEATH the
  instance cap (§22.5). It never replaces the account cap; the effective width a single
  workspace's plan suggests is `min(MAX_PARALLEL_SESSIONS, MAX_PARALLEL_PER_WORKSPACE)`.
- `LEASE_TTL_SECONDS = 1800` (30 min) — the claim/presence lease TTL (§22.3/§22.8); mirrors
  `claims.DEFAULT_LEASE_TTL_SECONDS` (this module is the ops source of record that wires it).
- `WRAPPER_HARD_TIMEOUT_SECONDS = 1200` (20 min) — the per-invocation wrapper hard timeout.
  STRICTLY LESS THAN `LEASE_TTL_SECONDS`: timeout < TTL means an EXPIRED lease implies a DEAD
  process (a live process would have been killed by its own timeout before its lease lapsed),
  so a lease-expired steal is safe against a merely-slow holder by policy as well as by the
  §22.3 primitives.
- `TELEMETRY_ENABLED_DEFAULT = True` — capture is default-on and disable-able (§22.5 PC11).
- `RECOMMENDED_WIDTH_WINDOW_SECONDS = 3600` (1 h) — the recent telemetry window the advisory
  `recommended_width` reads (§22.5); never auto-applied.
"""

from __future__ import annotations

__all__ = [
    "LEASE_TTL_SECONDS",
    "MAX_PARALLEL_PER_WORKSPACE",
    "MAX_PARALLEL_SESSIONS",
    "RECOMMENDED_WIDTH_WINDOW_SECONDS",
    "TELEMETRY_ENABLED_DEFAULT",
    "WRAPPER_HARD_TIMEOUT_SECONDS",
]

#: Account-wide in-flight session ceiling (§22.5 PC8). G2 PRELIMINARY seed.
MAX_PARALLEL_SESSIONS = 3

#: Optional per-workspace sub-limit BENEATH the instance cap (§22.5); never replaces it.
MAX_PARALLEL_PER_WORKSPACE = 2

#: Claim/presence lease TTL, seconds (§22.3/§22.8) — 30 min. G2 PRELIMINARY seed.
LEASE_TTL_SECONDS = 1800

#: Per-invocation wrapper hard timeout, seconds (§22.8) — 20 min; STRICTLY < LEASE_TTL_SECONDS.
WRAPPER_HARD_TIMEOUT_SECONDS = 1200

#: Telemetry capture default-on, disable-able (§22.5 PC11).
TELEMETRY_ENABLED_DEFAULT = True

#: The recent telemetry window the advisory `recommended_width` reads, seconds (§22.5) — 1 h.
RECOMMENDED_WIDTH_WINDOW_SECONDS = 3600
