"""The DR-1 async jobs subsystem: the LOSSY job record + TTL+steal lifecycle + poll resolver.

Design authority: `docs/design.md` §22.7 (the INVARIANT this module obeys: OUTPUT EXISTENCE
and the S1 claim/lease are the SOLE DONE / exactly-once authorities — everything here is a
lagging projection that gates NOTHING correctness-critical), §22.3 (the claim/lease steal this
lifecycle mirrors, and its nascent-write window), §23 (the `jobs/` store, keyed by a NON-artifact
run-family id — landed in DR-1 Commit 2), plus the DR-1 reconciliation resolutions H2 (create-
exclusive happy path + TTL+steal on a stale record) and H3 (the CORRECTED poll truth-table).

**Pure logic — NO sockets/HTTP/subprocess.** The transport (a persistent HTTP front) and the
detached runner are DR-1 Commits 4/6; this module is unit-testable with a fake clock (`now` is
always an explicit epoch-seconds argument) and injected `is_done`/`peek` callables — no live
substrate is ever required to drive any branch. Job records are §22.7-class LOSSY bookkeeping,
NOT identity: there is deliberately NO `schema_version`/`ir_version` bump for them.

## The job key (a run-family id — §7.1 F1 / Commit 2 boundary)

`job_key(target_ids, idempotency_key)` = `mint_run_id(preimage)` over a DETERMINISTIC
canonicalization of the sorted+deduped target-id set (`canonical_set`, §12.4) plus the
`idempotency_key`. The same logical request — the same target set in ANY order, the same key —
yields a BYTE-IDENTICAL preimage and therefore the SAME `r-<hex16>` key: the idempotency floor
(a retry collides on one key, N-2). A different target set OR a different `idempotency_key` yields
a different key. The key is a run-family id, so it can NEVER route through `output_path`/`is_done`
(they refuse every non-artifact family with `StorePathError`, §22.7 pin) — a job record can never
masquerade as an output.

## The lifecycle (H2): create-exclusive → TTL+steal

`JobStore.submit` writes the initial record with `store.create_exclusive` (the happy path: no
double-spawn — exactly one caller creates the record and is told to spawn). On `FileExistsError`
it reads the incumbent and resolves WITHOUT double-spawning, in THIS order: the whole job
materialized → DONE; a STORED terminal (the runner's `invoke` returned a failure and it EXITED) →
STEAL + re-spawn (the RETRY path — re-drive by the same key, above the window so a recorded failure
never wedges the retry for the full lifetime); within the JOB-LIFETIME window OR a live claim on
any target → the "still running" case (a slow start / a no-claim gap / active work), return the
existing job (NO re-spawn — the anti-double-charge guard); else STALE (past the window, no live
claim, output absent, no terminal) → STEAL the record via `store.write_replace` and signal a
re-spawn. A concurrent steal on an already-dead job is a bounded per-submitter cost leak (an N-way
race spawns up to N runners) — never a double OUTPUT, because the S1 claim admits one LLM run per
id and `commit_new` admits one output (§22.3).

The JOB-LIFETIME window (`JOB_LIFETIME_SECONDS`, 22 min) is ONE GENEROUS "assume still running"
line — above one full paid call, below the lease TTL. It REPLACES the old 120 s grace as the
running-vs-dead boundary: the live-claim check remains the authority for active work of any
duration, so the record window only ever governs the brief NO-CLAIM spans (startup / between
artifacts / the commit tail) — now with a ~10× margin, so a legitimately-running slow job is NEVER
told to resend (which had caused a double paid run).

The NASCENT-record window (`NASCENT_RECORD_GRACE_SECONDS`, seconds-scale) is a SEPARATE, short
grace mirroring §22.3: `create_exclusive` names the file atomically but the content write lands a
moment later, so a racing submit may read a torn record. Within an implicit grace anchored at the
file's mtime the incumbent submitter is presumed to be finishing the write — DO NOT steal (that
would double-spawn a live job); past it a torn record is stealable. It stays SECONDS-scale (a torn
record from a crashed submitter must become stealable in seconds, not 22 min). `submit` (the
spawn-decision authority) handles this conservatively; the read-only resolver simply treats an
unreadable record as absent (a transient wrong poll self-corrects — the same acquire/peek asymmetry
§22.3 already draws).

## The poll resolver (reshaped truth-table) — `resolve_job_state`

Evaluated in THIS order (the load-bearing state machine):

1. `is_done(target_id)` — OUTPUT existence, §22.7 authority #1. Record-INDEPENDENT: a deleted or
   missing record with the output present is DONE; a present record with the output absent is
   NEVER DONE. → **DONE**.
2. `peek(target_id) is not None AND now < peek(...).lease_expiry` — a LIVE claim/lease, §22.7
   authority #2 (the LLM window). `peek` returns a record EVEN FOR AN EXPIRED lease (no clock
   check — `claims.py`), so the resolver compares `lease_expiry` to `now` ITSELF; "peek returned
   something" is NOT "live". → **RUNNING**.
3. record present AND a STORED terminal envelope — a NONDETERMINISTIC failure was recorded (N-5).
   MOVED ABOVE the window: a stored terminal means the runner's `invoke` RETURNED, so it has
   EXITED — surface the reason PROMPTLY, never mask a real failure as RUNNING for the full job
   lifetime. → **FAILED** (the HTTP layer maps the code to a re-drivable 504 vs a terminal FAILED).
4. record present AND `now < spawn_time + JOB_LIFETIME_SECONDS` — the assume-still-running window
   (a slow start or a brief no-claim gap; peek still None). REPLACES the old 120 s grace →
   a legitimately-running slow job resolves RUNNING, never redrivable. → **RUNNING**.
5. else → **FAILED-re-drivable** — past the window, nothing live/done, no stored reason: safe to
   re-submit by the same key. A deterministic block (un-stored, N-5) and a deleted record both
   land here — the completeness sweep / a re-submit re-derive them. Never a wedge, never a false
   DONE.

## Terminal bookkeeping (N-5) — `record_terminal`

Stores `{envelope, results}` ONLY for NONDETERMINISTIC runtime failures (the runner's exception
synthesis / a transport-carried `timeout`/`rate-limit-backpressure`/`api-error`). DETERMINISTIC
blocks (`empty-pool`/`out-of-window`/`drift-block`/`hard-limit-exceeded`/`outline-config-drift`)
store NOTHING — the
§21.7 completeness sweep re-derives them, so persisting them would be redundant lossy state. In the
resolver a stored terminal is masked by authorities #1/#2 (output / a live claim), so a stale
terminal (e.g. from a stolen-from runner's late call) is never a correctness fault — it only ever
annotates a job that is ALREADY not-done and not-live. A steal writes a fresh record with
`terminal=None`, so a terminal present always belongs to the current, un-stolen runner.
"""

from __future__ import annotations

import json
import math
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pipeline.api.results import (
    CODE_DRIFT_BLOCK,
    CODE_EMPTY_POOL,
    CODE_HARD_LIMIT_EXCEEDED,
    CODE_OUT_OF_WINDOW,
    CODE_OUTLINE_CONFIG_DRIFT,
)
from pipeline.canonical import canonical_json_str, canonical_set
from pipeline.claims import ClaimRecord
from pipeline.ids import mint_run_id, parse_id
from pipeline.opdefaults import JOB_LIFETIME_SECONDS, NASCENT_RECORD_GRACE_SECONDS
from pipeline.store import create_exclusive, write_replace

__all__ = [
    "DETERMINISTIC_BLOCK_CODES",
    "IsDone",
    "JobError",
    "JobRecord",
    "JobState",
    "JobStore",
    "JobTerminal",
    "Peek",
    "SubmitOutcome",
    "is_deterministic_block",
    "job_key",
    "resolve_job_state",
]

#: The §21.7 generation-tier block codes that are DETERMINISTIC properties of the request + graph
#: state — the completeness sweep re-derives each one, so `record_terminal` never persists them
#: (N-5). Sourced from the `pipeline.api.results` code SSOT so this set can never drift from the
#: taxonomy. Deliberately CONSERVATIVE: any code NOT in this set is stored (under-classifying only
#: over-stores a redundant terminal; over-classifying would drop a real transient reason).
DETERMINISTIC_BLOCK_CODES = frozenset(
    {
        CODE_EMPTY_POOL,
        CODE_OUT_OF_WINDOW,
        CODE_DRIFT_BLOCK,
        CODE_HARD_LIMIT_EXCEEDED,
        CODE_OUTLINE_CONFIG_DRIFT,
    }
)

#: §22.7 authority seams, injected so every branch is drivable without a live transport:
#: `is_done(target_id)` reads OUTPUT existence; `peek(target_id)` reads the claim/lease table.
IsDone = Callable[[str], bool]
Peek = Callable[[str], "ClaimRecord | None"]

#: Bounded retry budget for the vanishing-record race in `submit` (an incumbent stolen/GC'd between
#: our create-fail and our read) — mirrors `claims.acquire`'s loop; then refuse loudly.
_SUBMIT_RETRIES = 64


class JobError(RuntimeError):
    """A job operation could not reach a defined outcome, or was handed a malformed key/input."""

    code = "job-store-error"


def is_deterministic_block(code: str) -> bool:
    """True iff `code` is a deterministic §21.7 block the completeness sweep re-derives (N-5)."""
    return code in DETERMINISTIC_BLOCK_CODES


# ---------------------------------------------------------------------------
# The job key (Commit 2 run-family boundary): the idempotency floor.
# ---------------------------------------------------------------------------


def job_key(target_ids: object, idempotency_key: str | None) -> str:
    """Mint the `r-<hex16>` job key from the sorted+deduped target-id set + `idempotency_key`.

    The preimage is a canonical map — `canonical_set` gives the order-independent, deduped
    target-id list (§12.4) and the `idempotency_key` rides alongside it. Same logical request →
    byte-identical preimage → same key (N-2 idempotency floor); a different set or key → a
    different key. Each target id must be a §7.4 id (refused loudly otherwise); the set must be
    non-empty; `idempotency_key` is a non-empty string or None.
    """
    ids = list(target_ids)  # type: ignore[arg-type]
    if not ids:
        raise JobError("job-store-error: a job needs at least one target id")
    for target in ids:
        parse_id(target)  # refuse a non-id (also a non-str) loudly — the key is over real ids
    if idempotency_key is not None and (
        not isinstance(idempotency_key, str) or not idempotency_key
    ):
        raise JobError("job-store-error: idempotency_key must be a non-empty string or None")
    preimage = {"idempotency-key": idempotency_key, "target-ids": canonical_set(ids)}
    return mint_run_id(preimage)


# ---------------------------------------------------------------------------
# The lossy record + the outcome/state value objects.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobTerminal:
    """A stored terminal envelope for a NONDETERMINISTIC failure (N-5): the surfaced reason."""

    code: str
    envelope: Any
    results: Any


@dataclass(frozen=True)
class JobRecord:
    """One §22.7-class LOSSY job record. Present-but-output-absent is NEVER DONE; a missing record
    still resolves safely (→ re-drivable). `spawn_time` anchors the job-lifetime window; `terminal`
    is set only by `record_terminal` for a nondeterministic failure.

    `callback_url` is the OPTIONAL webhook the submit ALREADY validated (allow-list + SSRF guard,
    W3b) and stored for the detached runner's completion WAKEUP (delivery is W3c). `callback_status`
    is the W3c DELIVERY OUTCOME the runner records after attempting that wakeup (`delivered` /
    `failed` / `rejected-at-delivery`, or None while pending / poll-only). Like every field it is
    LOSSY bookkeeping, not identity: a lost/absent value just means the client falls back to the
    always-available poll — no bump, no correctness authority. None ⇒ poll-only / not-yet."""

    target_ids: tuple[str, ...]
    idempotency_key: str | None
    spawn_time: float
    status: str
    terminal: JobTerminal | None = None
    callback_url: str | None = None
    callback_status: str | None = None


@dataclass(frozen=True)
class SubmitOutcome:
    """The result of `JobStore.submit`. `spawn` is the ONLY thing the caller acts on: spawn a
    detached runner iff True. `disposition` names the branch (diagnostics + tests)."""

    key: str
    disposition: Literal["spawned", "existing", "done", "stolen"]
    spawn: bool
    record: JobRecord | None


@dataclass(frozen=True)
class JobState:
    """One poll outcome. `kind` is the resolved state; `detail` names the truth-table branch that
    fired (diagnostics + the tests pin it); `terminal` carries the surfaced envelope for step 4."""

    kind: Literal["done", "running", "failed", "failed-redrivable"]
    detail: str
    terminal: JobTerminal | None = None


def _claim_is_live(claim: ClaimRecord | None, now: float) -> bool:
    """A claim is LIVE iff it exists AND `now < lease_expiry` — peek returns EXPIRED records too."""
    return claim is not None and now < claim.lease_expiry


# ---------------------------------------------------------------------------
# The poll resolver (H3) — the load-bearing state machine, PURE + fully injectable.
# ---------------------------------------------------------------------------


def resolve_job_state(
    record: JobRecord | None,
    target_id: str,
    *,
    now: float,
    is_done: IsDone,
    peek: Peek,
    job_lifetime: float = JOB_LIFETIME_SECONDS,
) -> JobState:
    """Resolve a poll for `target_id` against the (lossy) `record` — the reshaped truth-table, in
    order. `job_lifetime` is the ASSUME-STILL-RUNNING window (`JOB_LIFETIME_SECONDS`) — the
    running-vs-dead line the shim's poll call-site passes as a keyword.

    `record is None` covers a MISSING or unreadable record: it flows through steps 1/2 (the §22.7
    authorities are record-independent) and lands at step 5 (re-drivable) unless the output exists
    or a claim is live — never a false DONE, never a wedge.
    """
    # 1. OUTPUT existence — §22.7 authority #1. Record-independent.
    if is_done(target_id):
        return JobState("done", "output-exists")
    # 2. A LIVE claim/lease — §22.7 authority #2 (the LLM window). Compare lease_expiry OURSELVES.
    if _claim_is_live(peek(target_id), now):
        return JobState("running", "claim-live")
    # 3. A stored terminal (nondeterministic failure, N-5) → surface the reason PROMPTLY. MOVED
    #    ABOVE the window: `record_terminal` is written ONLY after `run_job`/`invoke` RETURNED, so
    #    the runner has EXITED — a real failure must not be masked as RUNNING for the full job
    #    lifetime. Not a stale-terminal hazard: a steal writes a fresh record with terminal=None, so
    #    any terminal present belongs to the current (un-stolen) runner, and steps 1/2 already mask
    #    it if output/claim reappeared.
    if record is not None and record.terminal is not None:
        return JobState("failed", "stored-terminal", terminal=record.terminal)
    # 4. Within the job-lifetime window — the runner is presumed STILL RUNNING (a slow start, or a
    #    brief no-claim gap between artifacts / the commit tail). REPLACES the old 120 s startup-
    #    grace boundary: the generous window governs only the no-claim spans (the live-claim check
    #    at step 2 covers active work of any duration), so a legitimately-running slow job is NEVER
    #    told to resend. This is the anti-double-charge guarantee on the poll side.
    if record is not None and now < record.spawn_time + job_lifetime:
        return JobState("running", "within-lifetime")
    # 5. Past the window, nothing live/done, no stored reason → safe to re-submit by the same key.
    return JobState("failed-redrivable", "no-live-work")


# ---------------------------------------------------------------------------
# Record (de)serialization — canonical JSON, lossy-tolerant reads.
# ---------------------------------------------------------------------------


def _record_bytes(record: JobRecord) -> bytes:
    terminal = (
        None
        if record.terminal is None
        else {
            "code": record.terminal.code,
            "envelope": record.terminal.envelope,
            "results": record.terminal.results,
        }
    )
    obj = {
        "callback_status": record.callback_status,
        "callback_url": record.callback_url,
        "idempotency_key": record.idempotency_key,
        "spawn_time": record.spawn_time,
        "status": record.status,
        "target_ids": list(record.target_ids),
        "terminal": terminal,
    }
    return (canonical_json_str(obj) + "\n").encode("utf-8")


def _parse_record(obj: object) -> JobRecord | Literal["unreadable"]:
    """Validate a decoded record; ANY invalidity → `unreadable` (lossy — never crash on a record).

    A torn/garbage/foreign record is treated as unreadable, not an error: §22.7 bookkeeping must
    degrade to "resolve safely", never to a raise that could wedge a poll.
    """
    if not isinstance(obj, dict):
        return "unreadable"
    target_ids = obj.get("target_ids")
    spawn_time = obj.get("spawn_time")
    status = obj.get("status")
    idempotency_key = obj.get("idempotency_key")
    callback_url = obj.get("callback_url")
    callback_status = obj.get("callback_status")
    terminal_raw = obj.get("terminal")
    if not isinstance(target_ids, list) or not all(isinstance(t, str) for t in target_ids):
        return "unreadable"
    if (
        isinstance(spawn_time, bool)
        or not isinstance(spawn_time, int | float)
        or not math.isfinite(spawn_time)
    ):
        return "unreadable"
    if not isinstance(status, str) or not status:
        return "unreadable"
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        return "unreadable"
    if callback_url is not None and not isinstance(callback_url, str):
        return "unreadable"
    if callback_status is not None and not isinstance(callback_status, str):
        return "unreadable"
    terminal: JobTerminal | None = None
    if terminal_raw is not None:
        if not isinstance(terminal_raw, dict):
            return "unreadable"
        code = terminal_raw.get("code")
        if not isinstance(code, str) or not code:
            return "unreadable"
        terminal = JobTerminal(
            code=code, envelope=terminal_raw.get("envelope"), results=terminal_raw.get("results")
        )
    return JobRecord(
        target_ids=tuple(target_ids),
        idempotency_key=idempotency_key,
        spawn_time=float(spawn_time),
        status=status,
        terminal=terminal,
        callback_url=callback_url,
        callback_status=callback_status,
    )


# ---------------------------------------------------------------------------
# The store: create-exclusive submit + TTL+steal + terminal bookkeeping + resolve.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobStore:
    """The workspace-scoped `jobs/` record store (§23). `jobs_dir` is the workspace's `jobs/`
    tree (a `WorkspaceStore.jobs_dir` in production; any tmp dir in tests) — the only handle it
    holds. Two DISTINCT windows (the Commit-6 double-meaning is now split):

    - `job_lifetime` — the ASSUME-STILL-RUNNING / job-lifetime window (`JOB_LIFETIME_SECONDS`,
      22 min): the running-vs-dead line for the resolver + submit's "already in progress" guard.
    - `nascent_grace` — the SHORT §22.3 torn/nascent-record grace (`NASCENT_RECORD_GRACE_SECONDS`,
      seconds-scale), used ONLY by `submit` for the just-created-but-torn-record race.

    Records key by the run-family `job_key`; the `is_done`/`peek` §22.7 authorities are passed per
    call (never held), so every branch is drivable in a unit test without a live transport."""

    jobs_dir: Path
    job_lifetime: float = JOB_LIFETIME_SECONDS
    nascent_grace: float = NASCENT_RECORD_GRACE_SECONDS

    def __post_init__(self) -> None:
        object.__setattr__(self, "jobs_dir", Path(self.jobs_dir))

    def path_for(self, key: str) -> Path:
        """`jobs/<key>` — the filename IS the run-family job key. A non-run key is refused (the
        §22.7 pin: a job record is never an artifact-family id)."""
        parsed = parse_id(key)
        if parsed.family != "run":
            raise JobError(
                f"job-store-error: a job key is a run-family id (r-<hex16>), got {key!r}"
            )
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        return self.jobs_dir / key

    def _read(self, path: Path) -> JobRecord | Literal["missing", "unreadable"]:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return "missing"
        try:
            obj = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return "unreadable"
        return _parse_record(obj)

    def load(self, key: str) -> JobRecord | None:
        """The readable record for `key`, or None (a missing OR unreadable record → None). Used by
        `resolve`: an unreadable record resolves as absent — a transient wrong poll self-corrects
        (the read-only side of the §22.3 acquire/peek asymmetry)."""
        record = self._read(self.path_for(key))
        return record if isinstance(record, JobRecord) else None

    def submit(
        self,
        target_ids: object,
        idempotency_key: str | None,
        *,
        now: float,
        is_done: IsDone,
        peek: Peek,
        callback_url: str | None = None,
    ) -> SubmitOutcome:
        """Submit a job (H2): create-exclusive the record, else resolve the incumbent WITHOUT
        double-spawning (DONE / existing / STEAL). Returns whether the caller should spawn a runner.

        `callback_url` (OPTIONAL) is the ALREADY-validated (allow-list + SSRF guard, done by the
        shim BEFORE this call, W3b) completion webhook, stored on the FRESH record so the detached
        runner can deliver a wakeup (W3c). It is lossy bookkeeping: it rides a `spawned`/`stolen`
        fresh record, is preserved as-is on the `existing`/`done` incumbent (no re-write), and is
        never a spawn-decision input. None ⇒ poll-only.
        """
        # Materialize the iterable EXACTLY ONCE — `target_ids` may be a one-shot iterator, and both
        # `job_key` and the record write below must consume the SAME targets (a second `list(...)`
        # of a spent generator would persist an EMPTY target set, defeating the submit-level
        # done/existing short-circuits and spuriously stealing a live/materialized job).
        targets = list(target_ids)  # type: ignore[call-overload]
        key = job_key(targets, idempotency_key)
        path = self.path_for(key)
        fresh = JobRecord(
            target_ids=tuple(canonical_set(targets)),
            idempotency_key=idempotency_key,
            spawn_time=now,
            status="running",
            terminal=None,
            callback_url=callback_url,
        )
        fresh_bytes = _record_bytes(fresh)
        for _ in range(_SUBMIT_RETRIES):
            try:
                create_exclusive(path, fresh_bytes)
            except FileExistsError:
                pass
            else:
                # Happy path: exactly one caller creates the record and is told to spawn (N-2).
                return SubmitOutcome(key=key, disposition="spawned", spawn=True, record=fresh)
            current = self._read(path)
            if current == "missing":
                continue  # stolen/GC'd between our create-fail and our read — retry the create
            if current == "unreadable":
                # Nascent concurrent create (§22.3 nascent window): within the SHORT mtime grace
                # the incumbent submitter is finishing the write — do NOT steal (would double-spawn
                # a live job); past this seconds-scale grace a torn record is stealable.
                try:
                    anchored = os.stat(path).st_mtime
                except FileNotFoundError:
                    continue  # vanished in the window — retry the create
                if now < anchored + self.nascent_grace:
                    return SubmitOutcome(
                        key=key, disposition="existing", spawn=False, record=None
                    )
                return self._steal(path, key, fresh, fresh_bytes)
            # A readable incumbent.
            # (1) The WHOLE job materialized → DONE (no spawn). §22.7 authority #1.
            if current.target_ids and all(is_done(t) for t in current.target_ids):
                return SubmitOutcome(key=key, disposition="done", spawn=False, record=current)
            # (2) A stored terminal → the runner's `run_job`/`invoke` RETURNED with a failure, so it
            #     has EXITED. This is the RETRY path: STEAL + re-spawn (re-drive by the same key).
            #     Placed ABOVE the within-window guard so a re-submit of a recorded failure inside
            #     the (22-min) lifetime window RE-DRIVES instead of being answered `existing` and
            #     wedging the retry. Double-charge-free: the S1 claim admits one LLM run per
            #     artifact-id and `commit_new` one output — a concurrent steal is a bounded cost
            #     leak, never a double output (§22.3).
            if current.terminal is not None:
                return self._steal(path, key, fresh, fresh_bytes)
            # (3) Within the job-lifetime window OR a live claim on any target → a slow start / a
            #     no-claim gap / an actively-running runner. EXISTING job, NO re-spawn — the core
            #     anti-double-charge guard: a legitimately-running slow job is never re-spawned.
            within_lifetime = now < current.spawn_time + self.job_lifetime
            if within_lifetime or any(_claim_is_live(peek(t), now) for t in current.target_ids):
                return SubmitOutcome(key=key, disposition="existing", spawn=False, record=current)
            # (4) STALE: past the window, no live claim, not done, no terminal → the runner died.
            #     STEAL + re-spawn.
            return self._steal(path, key, fresh, fresh_bytes)
        raise JobError(
            f"job-store-error: submit({key!r}) exhausted retries against a vanishing record"
        )

    def _steal(self, path: Path, key: str, fresh: JobRecord, fresh_bytes: bytes) -> SubmitOutcome:
        """Replace a stale/torn record with a fresh running one (grace reset, terminal cleared) and
        signal a re-spawn. Modeled on the §22.3 claim steal (`write_replace`, deliberately not
        atomic): a concurrent steal is a bounded per-submitter COST leak (an N-way race spawns up to
        N runners), never a double output — the S1 claim + the no-replace commit remain the
        exactly-once authorities."""
        write_replace(path, fresh_bytes)
        return SubmitOutcome(key=key, disposition="stolen", spawn=True, record=fresh)

    def record_terminal(
        self, key: str, *, code: str, envelope: Any, results: Any
    ) -> bool:
        """Store `{envelope, results}` as the job's terminal — ONLY for a NONDETERMINISTIC failure
        (N-5). A deterministic block (`is_deterministic_block`) stores NOTHING (the sweep re-derives
        it). Returns True iff stored. A no-op (returns False) when the record is gone/torn — lossy
        bookkeeping never fabricates a record, and the resolver still resolves safely."""
        if is_deterministic_block(code):
            return False
        path = self.path_for(key)
        current = self._read(path)
        if not isinstance(current, JobRecord):
            return False
        updated = replace(
            current,
            status="failed",
            terminal=JobTerminal(code=code, envelope=envelope, results=results),
        )
        write_replace(path, _record_bytes(updated))
        return True

    def record_callback_status(self, key: str, status: str) -> bool:
        """Record the W3c webhook DELIVERY outcome (`delivered`/`failed`/`rejected-at-delivery`) on
        the job record — §22.7-class LOSSY bookkeeping the detached runner writes AFTER attempting
        the completion wakeup. Returns True iff written.

        TOLERANT by construction: a missing/torn/STOLEN record (the runner was stolen-from between
        run and delivery) is a no-op (returns False), NEVER a raise — a lost callback status just
        degrades the client to the always-available poll, and this update gates nothing correctness-
        critical. It only annotates `callback_status`; it never resurrects a vanished record and
        never touches `terminal`/`status`/the output authorities."""
        path = self.path_for(key)
        current = self._read(path)
        if not isinstance(current, JobRecord):
            return False
        write_replace(path, _record_bytes(replace(current, callback_status=status)))
        return True

    def resolve(
        self, key: str, target_id: str, *, now: float, is_done: IsDone, peek: Peek
    ) -> JobState:
        """Load the record for `key` and resolve a poll for `target_id` (H3 truth-table). An
        unreadable/missing record resolves as absent (`load` → None) — safe by §22.7."""
        return resolve_job_state(
            self.load(key),
            target_id,
            now=now,
            is_done=is_done,
            peek=peek,
            job_lifetime=self.job_lifetime,
        )
