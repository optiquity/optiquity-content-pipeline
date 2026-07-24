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
- `JOB_LIFETIME_SECONDS = WRAPPER_HARD_TIMEOUT_SECONDS + NASCENT_RECORD_GRACE_SECONDS` (1320 s /
  22 min) — the DR-1 async job's "ASSUME-STILL-RUNNING" window: a job whose record was spawned
  less than this ago, with no output and no live claim, is presumed to be in a slow start or a
  brief no-claim gap (between artifacts / the commit tail), NOT dead — so a legitimately-running
  slow job is NEVER told to resend (the anti-double-charge line, `pipeline.jobs`). DERIVED so it
  sits ABOVE one full paid call (`WRAPPER_HARD_TIMEOUT_SECONDS`, 1200 s) and BELOW the lease TTL
  (`LEASE_TTL_SECONDS`, 1800 s): the live-claim check stays the authority for active work of ANY
  duration, so this window only ever governs the no-claim spans (with ~10× margin). A derived int;
  lossy-bookkeeping, not a §22.7 correctness authority (output existence + the S1 claim/lease
  remain the sole DONE / exactly-once authorities).
- `NASCENT_RECORD_GRACE_SECONDS = 120` (2 min) — the §22.3 TORN/NASCENT-RECORD grace, used ONLY by
  `JobStore.submit`: `create_exclusive` names the record file atomically but its content write
  lands a moment later, so a racing submit may read a torn record; within this SHORT mtime-anchored
  grace the incumbent submitter is presumed to be finishing the write — DO NOT steal (that would
  double-spawn a live job). It must stay SECONDS-scale (a torn record from a crashed submitter must
  become stealable in seconds, not the full job lifetime). This is NO LONGER a running-vs-dead
  boundary (that role is now `JOB_LIFETIME_SECONDS`); the old double-meaning was exactly the
  Commit-6 defect. Outside G2's two-number scope; lossy-bookkeeping, not a §22.7 authority.
- `CALLBACK_MAX_ATTEMPTS = 3` / `CALLBACK_BACKOFF_SECONDS = 1` / `CALLBACK_TIMEOUT_SECONDS = 10` —
  the DR-1 W3c webhook-callback DELIVERY budget (`pipeline.callback_delivery`): the bounded outbound
  completion-wakeup retry. Framework CONSTANTS, deliberately NOT config knobs (the only callback
  operator config is the host allow-list; the retry/backoff/timeout surface stays fixed and small).
  `MAX_ATTEMPTS` POSTs are tried before giving up (status `failed`; a 2xx → `delivered`), sleeping
  `BACKOFF·4**attempt` seconds between tries (1 s, 4 s, 16 s … — bounded, small), each issued with a
  `TIMEOUT`-second per-request socket timeout so a slow/black-hole endpoint never HANGS the detached
  runner. All INTs (the clean-constants surface, `tests/test_telemetry.py`). Lossy: a give-up just
  degrades the client to the always-available poll — never a §22.7 correctness authority.
"""

from __future__ import annotations

__all__ = [
    "CALLBACK_BACKOFF_SECONDS",
    "CALLBACK_MAX_ATTEMPTS",
    "CALLBACK_TIMEOUT_SECONDS",
    "JOB_LIFETIME_SECONDS",
    "LEASE_TTL_SECONDS",
    "MAX_PARALLEL_PER_WORKSPACE",
    "MAX_PARALLEL_SESSIONS",
    "NASCENT_RECORD_GRACE_SECONDS",
    "RECOMMENDED_WIDTH_WINDOW_SECONDS",
    "RENDER_SYNC_WAIT_SECONDS",
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

#: §22.3 torn/nascent-record grace, seconds — 2 min. The SHORT mtime-anchored window in which a
#: racing `JobStore.submit` treats a torn just-created record as an incumbent still being written —
#: DO NOT steal. Seconds-scale by design (a crashed submitter's torn record is stealable in
#: seconds). NO LONGER a running-vs-dead boundary (that is `JOB_LIFETIME_SECONDS`) — the old
#: double-meaning was the Commit-6 defect. Lossy-bookkeeping, never a §22.7 correctness authority.
NASCENT_RECORD_GRACE_SECONDS = 120

#: DR-1 async job "assume-still-running" window, seconds — 22 min. DERIVED: one full paid call
#: (WRAPPER_HARD_TIMEOUT_SECONDS) + one nascent-record grace, so it sits ABOVE a single in-flight
#: paid call and BELOW LEASE_TTL_SECONDS (1800 s). A job spawned less than this ago with no output
#: and no live claim is presumed still running (a slow start / a no-claim gap), so a legitimately-
#: running slow job is NEVER told to resend — the anti-double-charge line (`pipeline.jobs`). The
#: live-claim check remains the authority for active work of ANY duration; this window only ever
#: governs the no-claim spans. Lossy-bookkeeping, never a §22.7 correctness authority.
JOB_LIFETIME_SECONDS = WRAPPER_HARD_TIMEOUT_SECONDS + NASCENT_RECORD_GRACE_SECONDS

#: DR-1 render OPTIMISTIC-SYNC hold, seconds — 60 s. The BOUNDED window the HTTP shim holds a
#: `render` submit open, polling OUTPUT EXISTENCE (§22.7 `is_done`) on the predictable
#: deliverable-id BEFORE falling back to the async 202+poll: a cache-hit / local-pandoc serialize
#: usually materializes well within it → a synchronous 200 + the output; a fit that must run the
#: paid reshape exceeds it → 202 + the predictable deliverable-id (the detached runner continues,
#: the client polls / gets the webhook). Chosen WELL BELOW `WRAPPER_HARD_TIMEOUT_SECONDS` (1200 s):
#: the hold is a latency convenience, never a substitute for the async door. THREAD-EXHAUSTION
#: NOTE: the hold × `ThreadingHTTPServer` thread-per-request pins one thread per in-flight render
#: for up to this long — a burst of minting renders can saturate the pool. The advisory/backstop
#: concurrency cap (DR-1 Commit 10, `MAX_PARALLEL_SESSIONS`) is the mitigation; keeping this bound
#: small (and the wait a hard ceiling) is the interim guard. Lossy-latency knob, never a §22.7
#: correctness authority (the deliverable-id + poll are the authorities whether or not it fires).
RENDER_SYNC_WAIT_SECONDS = 60

#: DR-1 W3c webhook-callback DELIVERY budget — the bounded outbound completion-wakeup retry
#: (`pipeline.callback_delivery`). Framework constants, NOT config knobs (only the allow-list is
#: operator config). All INTs (the clean-constants surface). Lossy: a give-up degrades to the poll.
#:
#: Total POST attempts before giving up (status `failed`); a 2xx → `delivered`. Bounded — the
#: detached runner's only remaining task is this delivery, then exit.
CALLBACK_MAX_ATTEMPTS = 3

#: Exponential-backoff BASE, seconds: the runner sleeps `BASE * 4**attempt` between tries
#: (1 s, 4 s, 16 s …), so the total wait across the bounded attempts stays small.
CALLBACK_BACKOFF_SECONDS = 1

#: Per-request connect/read socket timeout, seconds: a callback POST never HANGS the runner (a
#: slow / black-hole endpoint fails fast → retry → give up, then exit).
CALLBACK_TIMEOUT_SECONDS = 10
