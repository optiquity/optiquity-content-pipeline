"""The weekly spend METER: per-bucket caps + install UMBRELLA + INTER-PROCESS admission lock.

Plan G6 (§21.10, §23, S-2/S-3, R2). This gate is PURE BOOKKEEPING — it admits/settles over FAKE
ceilings + FAKE costs. It resolves no secret, selects no transport, and makes NO model call: there
is NO spend surface here (the api-key path is G7). The meter is the money-safety CORE the G7 paid
door will admit against; built conservatively.

Four data-safety invariants shape every line:

- **INTER-PROCESS admission lock (S-3, the crux).** The real race is SEPARATE `pipeline` processes
  + detached `jobrunner` subprocesses re-entering `invoke()` — NOT threads (the driver is
  sequential). So the admission lock is an OS `flock` on a single install-wide lockfile
  (`instance/ops/spend/.admit.lock`), held across the WHOLE read-cap → compute-week-to-date →
  write-hold critical section for the assignment bucket AND the umbrella IN ONE section. A
  `threading.Lock` would NOT serialize separate processes (`test_meter_concurrency.py` proves it
  with N real subprocesses). `flock` releases automatically on process exit/crash — no stale-lock
  deadlock.

- **Admission math = settled + ALL LIVE HOLDS (S-3).** Week-to-date for a bucket is the SETTLED
  ledger total PLUS the sum of every unexpired hold's ceiling — never settled-only. Settled-only
  would let two concurrent admits read the same total and both pass; counting live holds under the
  lock makes each admit see the other's reservation. `admit` REFUSES pre-spend (typed, no hold
  written) if `settled + live_holds + ceiling` exceeds the bucket cap OR the umbrella cap.

- **TTL holds, self-healing (PresenceRegistry model, telemetry.py:243).** A hold is one file named
  by an opaque token, content `{run_id, ceiling, hold_expiry}`. A crashed run's hold SELF-EXPIRES
  at its FULL ceiling (conservative: never lost, never permanent) and is reclaimed on the next
  admit that touches its bucket/umbrella. `settle(hold, actual)` (called in a `finally`) appends the
  settled ledger line then drops the hold. The clock is INJECTABLE (telemetry's `Clock` discipline —
  no ambient `now()`), so week boundaries + expiry are deterministic + auditable.

- **Hash-chained SETTLED ledger — edit-EVIDENT, not reset-proof (R2).** Each settled line carries
  `prev_hash → this_hash`; a verify recomputes the chain, so an EDITED / reordered / dropped-middle
  line is DETECTED (a typed `LedgerTamperError`, fail-closed at admit). Framed HONESTLY: this is
  TAMPER-EVIDENCE, not tamper-proofing — a local `rm` of `instance/ops/spend/` reopens the cap
  (operator-bounds-their-own-bill; a documented residual, R2). No live network, no reset-proofing.

Hold-TTL invariant (S-2): the meter pins `DEFAULT_HOLD_TTL_SECONDS > WRAPPER_HARD_TIMEOUT_SECONDS`
(a cross-module inequality test, mirroring transport's `DEFAULT_TIMEOUT_SECONDS < lease-TTL`) AND
ships `refresh()` (the heartbeat, PresenceRegistry model). The two together mean a run can never
outlive its hold: the driver (G7) refreshes BETWEEN calls, so the longest gap without a refresh is
ONE paid call (`WRAPPER_HARD_TIMEOUT_SECONDS`), which is strictly less than the hold TTL — even a
missed heartbeat cannot let the hold lapse mid-call while (later) still authorized.

Boundary (module grep, plan): this module imports the store atomics, the injectable `Clock`, and
the `pipeline.spend.assignment` config/scope types — NEVER the generation/transport-selection
machinery (compose/review/reconcile/driver/transport/resolve). Data homes under the gitignored
`instance/ops/spend/` (mechanism framework, data instance — the `check-no-content.sh` guard stays
green because nothing there is tracked).
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pipeline import opdefaults
from pipeline.canonical import canonical_json_str, sha256_hex
from pipeline.spend.assignment import (
    INSTALL_SCOPE_ID,
    SCOPE_LEVELS,
    ScopeKey,
    load_store,
    save_store,
)
from pipeline.store import append_jsonl_line, create_exclusive, write_replace
from pipeline.telemetry import Clock

__all__ = [
    "DEFAULT_HOLD_TTL_SECONDS",
    "GENESIS_HASH",
    "MONDAY",
    "SPEND_RELPATH",
    "UMBRELLA_HANDLE",
    "UMBRELLA_LEVEL",
    "UMBRELLA_SCOPE_ID",
    "BucketKey",
    "Hold",
    "LedgerTamperError",
    "MeterError",
    "MeterRefusedError",
    "UmbrellaCapError",
    "WeeklyMeter",
    "bucket_key",
    "check_hold_ttl_invariant",
    "clear_umbrella_cap",
    "set_umbrella_cap",
    "umbrella_bucket_key",
    "umbrella_cap",
    "week_key",
]

#: The gitignored home of the meter's ledgers + holds (mechanism framework, data instance; §23).
SPEND_RELPATH = Path("instance") / "ops" / "spend"

#: The per-bucket SETTLED ledger filename (hash-chained, append-only), the holds subdir, and the
#: single install-wide admission lockfile (the S-3 inter-process critical section).
_LEDGER_NAME = "ledger.jsonl"
_HOLDS_DIRNAME = "holds"
_LOCK_NAME = ".admit.lock"

#: The hash-chain genesis: the first settled line's `prev_hash` (64 hex zeros, an obvious anchor).
GENESIS_HASH = "0" * 64

#: The default calendar-week reset weekday: Monday (Python `weekday()` Monday=0). Install policy.
MONDAY = 0

#: The hold TTL (30 min). PINNED strictly GREATER than `opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS`
#: (one paid call, 20 min) by the cross-module inequality test in `tests/test_weekly_meter.py`
#: (S-2). The driver (G7) refreshes the hold between calls, so the longest un-refreshed gap is one
#: paid call — strictly under this TTL. A crashed hold self-expires ~10 min after its last call.
DEFAULT_HOLD_TTL_SECONDS = 30.0 * 60.0

#: The single install-wide UMBRELLA bucket's sentinel key parts. `UMBRELLA_LEVEL` is deliberately
#: NOT a real `SCOPE_LEVELS` value, so the umbrella can never collide with any assignment bucket.
UMBRELLA_LEVEL = "umbrella"
UMBRELLA_SCOPE_ID = INSTALL_SCOPE_ID  # "install" — the whole-install token, stored explicitly
UMBRELLA_HANDLE = "*"


class MeterError(RuntimeError):
    """Base: a meter operation hit a state it must refuse LOUDLY, never guess through (§3.1)."""

    code = "meter-error"


class MeterRefusedError(MeterError):
    """Admission would exceed a cap — REFUSED PRE-SPEND, typed, with NO hold written (S-3).

    Names the bucket by its NON-secret identity (level / scope-id / handle-ref / week) — never a
    secret. `which` is `"bucket"` or `"umbrella"`; `cap` / `projected` / `ceiling` are the money
    figures (Decimals). This fires BEFORE any hold or spend, so a refusal costs nothing."""

    code = "meter-refused"

    def __init__(
        self,
        *,
        which: str,
        cap: Decimal,
        projected: Decimal,
        ceiling: Decimal,
        bucket_desc: str,
    ) -> None:
        self.which = which
        self.cap = cap
        self.projected = projected
        self.ceiling = ceiling
        super().__init__(
            f"meter-refused: admitting a ${ceiling} ceiling would put the {which} week-to-date at "
            f"${projected} > cap ${cap} for {bucket_desc} — refusing PRE-SPEND (no hold written, "
            f"nothing spent, S-3)"
        )


class LedgerTamperError(MeterError):
    """A settled ledger's hash-chain broke — an EDITED / reordered / dropped-middle line is
    DETECTED (edit-EVIDENT). Fail-closed: admission refuses on a tampered ledger. HONEST framing:
    this detects EDITS, not a full `rm` — deleting `instance/ops/spend/` silently resets the cap
    (operator-bounds-their-own-bill; a documented residual, R2)."""

    code = "meter-ledger-tampered"

    def __init__(self, path: Path, index: int, reason: str) -> None:
        self.path = path
        self.index = index
        super().__init__(
            f"meter-ledger-tampered: {path} line {index}: {reason} — the hash-chain does not "
            f"verify (edit-EVIDENT; NOTE a full `rm` of the ledger resets the cap, a documented "
            f"residual R2, NOT a reset-proof guarantee)"
        )


class UmbrellaCapError(MeterError):
    """`set-umbrella-cap` was given a non-positive / non-numeric amount — a loud refuse, nothing
    written (an install-wide weekly umbrella must be a real positive dollar budget)."""

    code = "meter-bad-umbrella-cap"


# ---------------------------------------------------------------------------------------
# Small helpers: numeric guard, safe path components, canonical Decimal coercion
# ---------------------------------------------------------------------------------------


def _is_finite_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and value == value  # not NaN
        and value not in (float("inf"), float("-inf"))
    )


def _q(component: str) -> str:
    """Percent-encode ONE bucket-key field into a single safe path component (no `/`, no `:`)."""
    return quote(component, safe="")


def _as_decimal(value: Any, *, what: str) -> Decimal:
    """Coerce to a finite `Decimal`, or raise a loud `MeterError` (money is exact, never float)."""
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise MeterError(f"meter-error: {what} {value!r} is not a number") from None
    if not dec.is_finite():
        raise MeterError(f"meter-error: {what} must be finite, got {value!r}")
    return dec


# ---------------------------------------------------------------------------------------
# The calendar week key — deterministic, auditable, INJECTABLE clock (no ambient now)
# ---------------------------------------------------------------------------------------


def check_hold_ttl_invariant(hold_ttl_seconds: float) -> None:
    """The S-2 hold-TTL pin (cross-module inequality, mirroring transport's
    `DEFAULT_TIMEOUT_SECONDS < lease-TTL`): the hold TTL MUST be STRICTLY GREATER than one paid
    call's worst-case wall time (`opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS`). The driver (G7)
    refreshes a hold BETWEEN calls, so the longest un-refreshed gap is one call — if that were
    ever ≥ the TTL, a live run could outlive its hold (freeing its ceiling) while still authorized.
    A too-short TTL is refused LOUDLY here (enforced at meter construction), so the invariant can
    never silently drift; `tests/test_weekly_meter.py` also pins it directly."""
    if not float(hold_ttl_seconds) > float(opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS):
        raise MeterError(
            f"meter-error: hold TTL {hold_ttl_seconds}s must be STRICTLY GREATER than one paid "
            f"call's worst-case wall time ({opdefaults.WRAPPER_HARD_TIMEOUT_SECONDS}s, "
            f"WRAPPER_HARD_TIMEOUT_SECONDS) — otherwise a run can outlive its hold between refresh "
            f"heartbeats and keep a (later) disarm live while its ceiling has been freed (S-2)"
        )


def week_key(
    now: float,
    *,
    reset_weekday: int = MONDAY,
    tz: tzinfo = UTC,
) -> str:
    """The calendar-week key for `now` (epoch seconds): the DATE of the most recent `reset_weekday`
    at 00:00 in `tz`, at or before `now`. Default Monday 00:00 UTC (install policy — the reset
    weekday + tz are configurable). DETERMINISTIC + AUDITABLE: a pure function of `now`, so the key
    literally names the week-start date (`YYYY-MM-DD`), and the boundary is inclusive of the reset
    instant (a new week begins AT 00:00). `now` comes from the INJECTABLE clock — never ambient."""
    if not 0 <= int(reset_weekday) <= 6:
        raise MeterError(
            f"meter-error: reset_weekday must be 0..6 (Mon..Sun), got {reset_weekday!r}"
        )
    moment = datetime.fromtimestamp(float(now), tz=tz)
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    days_since_reset = (moment.weekday() - int(reset_weekday)) % 7
    week_start = midnight - timedelta(days=days_since_reset)
    return week_start.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------------------
# Bucket keys — (scope-level, scope-id, handle, week). Same-named zones under different users
# key DISTINCT buckets because the scope-id carries the user (G4's M3). Plus the ONE umbrella.
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class BucketKey:
    """A spend bucket's identity: `(level, scope_id, handle, week)` (plan G6, §23).

    `level` ∈ `SCOPE_LEVELS` (or `UMBRELLA_LEVEL` for the install umbrella); `scope_id` records
    IDENTITY (never a store path — M3), so `dave/work` ≠ `erin/work`; `handle` is a NON-secret
    keystore reference; `week` is a `week_key`. Two same-named zones under different users are
    DISTINCT buckets. Every field is a single safe path component once percent-encoded."""

    level: str
    scope_id: str
    handle: str
    week: str


def bucket_key(scope: ScopeKey, handle: object, week: str) -> BucketKey:
    """Build a `BucketKey` from a G4 `ScopeKey` + a keystore handle (a `SecretRef` or its string) +
    a week. `str(handle)` yields the NON-secret handle string for both a `SecretRef` and a `str`."""
    if scope.level not in SCOPE_LEVELS:
        raise MeterError(
            f"meter-error: scope level {scope.level!r} is not a known scope level {SCOPE_LEVELS}"
        )
    return BucketKey(scope.level, scope.scope_id, str(handle), week)


def umbrella_bucket_key(week: str) -> BucketKey:
    """The single install-wide UMBRELLA bucket for `week` (sentinel parts, never a real bucket)."""
    return BucketKey(UMBRELLA_LEVEL, UMBRELLA_SCOPE_ID, UMBRELLA_HANDLE, week)


# ---------------------------------------------------------------------------------------
# Holds — TTL-bounded reservations (one per admitted run), PresenceRegistry model
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hold:
    """One admitted run's live reservation: the opaque `token`, the `run_id`, the reserved
    `ceiling` (Decimal), the embedded `expiry`, and the `bucket` it was admitted against. The same
    token names a hold file in BOTH the bucket's and the umbrella's holds dir (charged together)."""

    token: str
    run_id: str
    ceiling: Decimal
    expiry: float
    bucket: BucketKey


def _mint_hold_token() -> str:
    """A collision-resistant, opaque hold token (128 random bits; a pid prefix as diagnostic
    garnish). Never a workspace/client identifier — just a coordination handle (telemetry model)."""
    return f"h{os.getpid()}-{os.urandom(16).hex()}"


def _hold_bytes(token: str, run_id: str, ceiling: Decimal, expiry: float) -> bytes:
    """Serialize a hold record to one canonical-JSON line (ceiling as a string → exact Decimal)."""
    record = {
        "token": token,
        "run_id": run_id,
        "ceiling": str(ceiling),
        "hold_expiry": float(expiry),
    }
    return (canonical_json_str(record) + "\n").encode("utf-8")


def _live_holds_total(holds_dir: Path, now: float) -> Decimal:
    """Sum the ceilings of every LIVE (unexpired) hold in `holds_dir`, reclaiming the expired ones.

    A hold whose `hold_expiry` is at or before `now` is EXPIRED — its ceiling frees and its file is
    unlinked (self-healing a crashed run's hold). An unreadable/torn hold is conservatively skipped
    (never counted, never fatal). Called ONLY under the admission lock, so reclaim is race-free."""
    if not holds_dir.is_dir():
        return Decimal("0")
    total = Decimal("0")
    for entry in holds_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            record = json.loads(entry.read_bytes())
        except (ValueError, OSError):
            continue  # a torn/unreadable hold — conservatively skip (telemetry live_count model)
        if not isinstance(record, dict):
            continue
        expiry = record.get("hold_expiry")
        ceiling = record.get("ceiling")
        if not _is_finite_number(expiry):
            continue
        if now < float(expiry):
            try:
                total += Decimal(str(ceiling))
            except (InvalidOperation, TypeError):
                continue  # an unparseable ceiling — skip (never over-count off a corrupt hold)
        else:
            try:
                os.unlink(entry)  # EXPIRED → reclaim; the ceiling frees (crash self-heals)
            except OSError:
                pass
    return total


# ---------------------------------------------------------------------------------------
# The hash-chained SETTLED ledger — append-only, edit-EVIDENT (verify recomputes the chain)
# ---------------------------------------------------------------------------------------

_LEDGER_PAYLOAD_KEYS = ("seq", "run_id", "ts", "reserved_ceiling", "actual_cost", "prev_hash")


def _chain_hash(payload: dict[str, Any]) -> str:
    """`this_hash` = SHA-256 over the canonical (sorted) JSON of the line WITHOUT `this_hash`."""
    return sha256_hex(canonical_json_str(payload).encode("utf-8"))


def _read_ledger_lines(path: Path) -> list[dict[str, Any]]:
    """Read + VERIFY a bucket's settled ledger; return its lines in order (empty if none).

    Verifies the hash-chain: line 0's `prev_hash` is `GENESIS_HASH`; each line's `this_hash`
    recomputes from its payload; each line links to the prior line's `this_hash`; `seq` increments
    0,1,2,…. Any break → a loud `LedgerTamperError` (edit-EVIDENT, fail-closed). A single TORN FINAL
    line (a crash mid-append, §13.3) is discarded — never treated as tampering; an unparseable
    NON-final line IS tampering (a middle line cannot be torn under the single-write append)."""
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return []
    raw = [ln for ln in text.splitlines() if ln.strip()]
    parsed: list[dict[str, Any]] = []
    for index, line in enumerate(raw):
        try:
            obj = json.loads(line)
        except ValueError:
            if index == len(raw) - 1:
                break  # torn FINAL line (crash mid-append, §13.3) — discard, not tamper
            raise LedgerTamperError(path, index, "unparseable non-final ledger line") from None
        if not isinstance(obj, dict):
            raise LedgerTamperError(path, index, "ledger line is not a JSON object")
        parsed.append(obj)
    _verify_chain(path, parsed)
    return parsed


def _verify_chain(path: Path, lines: list[dict[str, Any]]) -> None:
    prev = GENESIS_HASH
    for index, record in enumerate(lines):
        try:
            payload = {key: record[key] for key in _LEDGER_PAYLOAD_KEYS}
            stored = record["this_hash"]
        except KeyError as exc:
            raise LedgerTamperError(path, index, f"ledger line missing field {exc}") from None
        if record.get("seq") != index:
            raise LedgerTamperError(path, index, f"seq {record.get('seq')!r} out of order")
        if payload["prev_hash"] != prev:
            raise LedgerTamperError(path, index, "prev_hash does not chain to the prior line")
        expected = _chain_hash(payload)
        if stored != expected:
            raise LedgerTamperError(path, index, "this_hash mismatch (line edited)")
        prev = expected


def _settled_total(path: Path) -> Decimal:
    """The week-to-date SETTLED total for a bucket = Σ `actual_cost` over its verified ledger."""
    total = Decimal("0")
    for record in _read_ledger_lines(path):
        total += _as_decimal(record.get("actual_cost"), what="settled actual_cost")
    return total


def _append_settled(
    path: Path, *, run_id: str, ts: float, reserved_ceiling: Decimal, actual_cost: Decimal
) -> None:
    """Append ONE hash-chained settled line (verifies the existing chain first — fail-closed)."""
    existing = _read_ledger_lines(path)
    seq = len(existing)
    prev_hash = existing[-1]["this_hash"] if existing else GENESIS_HASH
    payload = {
        "seq": seq,
        "run_id": run_id,
        "ts": float(ts),
        "reserved_ceiling": str(reserved_ceiling),
        "actual_cost": str(actual_cost),
        "prev_hash": prev_hash,
    }
    record = dict(payload)
    record["this_hash"] = _chain_hash(payload)
    append_jsonl_line(path, record)


# ---------------------------------------------------------------------------------------
# The meter — admit / settle / refresh under the INTER-PROCESS admission lock
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WeeklyMeter:
    """The enforcing per-bucket weekly spend meter + the install UMBRELLA, safe across PROCESSES.

    `root` is the framework root (the meter data homes under `root/instance/ops/spend/`). `clock`
    is the INJECTABLE epoch-seconds source (telemetry's discipline — no ambient now). `hold_ttl_
    seconds` / `reset_weekday` / `tz` are install policy. Every `admit`/`settle`/`refresh` runs
    under the single install-wide `flock` (S-3), so separate processes serialize on the FULL
    read-cap → compute → write-hold section for the bucket AND the umbrella in ONE critical
    section. Nothing here spends — the money-safety CORE the G7 paid door will admit against."""

    root: Path
    clock: Clock = time.time
    hold_ttl_seconds: float = DEFAULT_HOLD_TTL_SECONDS
    reset_weekday: int = MONDAY
    tz: tzinfo = UTC
    #: An INJECTABLE probe invoked INSIDE the admission critical section, AFTER week-to-date is read
    #: and BEFORE the hold is written. `None` in production (zero behavior) — it exists ONLY to make
    #: the INTER-PROCESS lock deterministically testable: injecting a small sleep widens the
    #: read→write window so `test_meter_concurrency.py` can prove that WITHOUT the flock the meter
    #: over-admits (a threading.Lock would), and WITH it exactly the headroom admits. Same "no
    #: ambient behavior — everything injectable" discipline as the clock.
    after_read_probe: Callable[[], None] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        # S-2: refuse a hold TTL that does not strictly exceed one paid call's worst-case wall time.
        check_hold_ttl_invariant(self.hold_ttl_seconds)

    @property
    def spend_dir(self) -> Path:
        return self.root / SPEND_RELPATH

    def current_week(self) -> str:
        """The current `week_key` from the injected clock (deterministic + auditable)."""
        return week_key(self.clock(), reset_weekday=self.reset_weekday, tz=self.tz)

    def _bucket_dir(self, key: BucketKey) -> Path:
        return (
            self.spend_dir
            / _q(key.level)
            / _q(key.scope_id)
            / _q(key.handle)
            / _q(key.week)
        )

    @contextmanager
    def _admission_lock(self) -> Iterator[None]:
        """The INTER-PROCESS admission lock (S-3): an exclusive `flock` on ONE install-wide
        lockfile, held across the whole admit/settle critical section. `flock` serializes SEPARATE
        processes (a `threading.Lock` would not) and releases on process exit/crash (no stale
        deadlock)."""
        lock_path = self.spend_dir / _LOCK_NAME
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    # -- the admission-math read (settled + all live holds), used by admit + status ------------

    def _week_to_date(self, bucket_dir: Path, now: float) -> Decimal:
        """Week-to-date for a bucket = SETTLED ledger total + Σ ALL LIVE holds (S-3). Reclaims
        expired holds as a side effect. MUST be called under the admission lock."""
        settled = _settled_total(bucket_dir / _LEDGER_NAME)
        holds = _live_holds_total(bucket_dir / _HOLDS_DIRNAME, now)
        return settled + holds

    def bucket_week_to_date(self, scope: ScopeKey, handle: object) -> Decimal:
        """READ-ONLY: a bucket's current week-to-date (settled + live holds). Verifies the ledger
        chain (raises `LedgerTamperError` on tamper). Used by tests + the G8 disclosure headroom."""
        week = self.current_week()
        bdir = self._bucket_dir(bucket_key(scope, handle, week))
        with self._admission_lock():
            return self._week_to_date(bdir, self.clock())

    def umbrella_week_to_date(self) -> Decimal:
        """READ-ONLY: the install umbrella's current week-to-date (settled + live holds)."""
        week = self.current_week()
        udir = self._bucket_dir(umbrella_bucket_key(week))
        with self._admission_lock():
            return self._week_to_date(udir, self.clock())

    # -- admit / settle / refresh --------------------------------------------------------------

    def admit(
        self,
        *,
        scope: ScopeKey,
        handle: object,
        bucket_cap: object,
        umbrella_cap: object,
        ceiling: object,
        run_id: str,
    ) -> Hold:
        """Admit a run against its bucket cap AND the umbrella, ATOMICALLY (S-3). Returns a live
        `Hold` token, or raises `MeterRefusedError` PRE-SPEND (typed, NO hold written) if either cap
        would be exceeded. The FULL read-cap → compute-week-to-date → write-hold section runs under
        the single inter-process lock for the bucket AND the umbrella (two locks would leave a
        TOCTOU past the umbrella). Week-to-date = settled + all live holds; expired holds are
        reclaimed first, so a crashed run's ceiling frees. Nothing spends — bookkeeping only."""
        bucket_cap = _as_decimal(bucket_cap, what="bucket_cap")
        umbrella_cap = _as_decimal(umbrella_cap, what="umbrella_cap")
        ceiling = _as_decimal(ceiling, what="ceiling")
        if bucket_cap <= 0 or umbrella_cap <= 0:
            raise MeterError(
                "meter-error: caps must be POSITIVE dollar amounts (no uncapped admit)"
            )
        if ceiling < 0:
            raise MeterError(f"meter-error: ceiling must be non-negative, got ${ceiling}")

        week = self.current_week()
        bkey = bucket_key(scope, handle, week)
        ukey = umbrella_bucket_key(week)
        bdir = self._bucket_dir(bkey)
        udir = self._bucket_dir(ukey)
        now = self.clock()
        expiry = now + float(self.hold_ttl_seconds)

        with self._admission_lock():
            # Reclaim-then-read for BOTH buckets, then decide, then write — one atomic section.
            bucket_wtd = self._week_to_date(bdir, now)
            umbrella_wtd = self._week_to_date(udir, now)

            # The injectable in-section probe (None in production): widens the read→write window so
            # the inter-process lock is deterministically testable. Under the flock this still
            # serializes; WITHOUT the flock, concurrent probes overlap and over-admit.
            if self.after_read_probe is not None:
                self.after_read_probe()

            bucket_projected = bucket_wtd + ceiling
            if bucket_projected > bucket_cap:
                raise MeterRefusedError(
                    which="bucket",
                    cap=bucket_cap,
                    projected=bucket_projected,
                    ceiling=ceiling,
                    bucket_desc=f"{bkey.level}:{bkey.scope_id} handle={bkey.handle} week={week}",
                )
            umbrella_projected = umbrella_wtd + ceiling
            if umbrella_projected > umbrella_cap:
                raise MeterRefusedError(
                    which="umbrella",
                    cap=umbrella_cap,
                    projected=umbrella_projected,
                    ceiling=ceiling,
                    bucket_desc=f"umbrella week={week}",
                )

            token = _mint_hold_token()
            line = _hold_bytes(token, run_id, ceiling, expiry)
            # Charge BOTH atomically under the one lock: the assignment bucket AND the umbrella.
            create_exclusive(bdir / _HOLDS_DIRNAME / token, line)
            create_exclusive(udir / _HOLDS_DIRNAME / token, line)

        return Hold(token=token, run_id=run_id, ceiling=ceiling, expiry=expiry, bucket=bkey)

    def settle(self, hold: Hold, actual_cost: object) -> None:
        """Settle an admitted run (call in a `finally`): append the hash-chained settled line to the
        bucket AND the umbrella ledger, then drop the hold in both. Under the admission lock, the
        line is appended BEFORE the hold is dropped — so a concurrent admit (serialized by the same
        lock) never sees NEITHER (an under-count); it sees the hold OR the settled line, both
        conservative. A crash BEFORE settle leaves the hold to self-expire at its full ceiling."""
        actual = _as_decimal(actual_cost, what="actual_cost")
        if actual < 0:
            raise MeterError(f"meter-error: actual_cost must be non-negative, got ${actual}")
        week = hold.bucket.week
        bdir = self._bucket_dir(hold.bucket)
        udir = self._bucket_dir(umbrella_bucket_key(week))
        ts = self.clock()
        with self._admission_lock():
            _append_settled(
                bdir / _LEDGER_NAME,
                run_id=hold.run_id,
                ts=ts,
                reserved_ceiling=hold.ceiling,
                actual_cost=actual,
            )
            _append_settled(
                udir / _LEDGER_NAME,
                run_id=hold.run_id,
                ts=ts,
                reserved_ceiling=hold.ceiling,
                actual_cost=actual,
            )
            _drop_hold(bdir / _HOLDS_DIRNAME / hold.token)
            _drop_hold(udir / _HOLDS_DIRNAME / hold.token)

    def refresh(self, hold: Hold) -> Hold:
        """The hold heartbeat (S-2, PresenceRegistry model): extend the hold's expiry by one TTL in
        BOTH the bucket and the umbrella. The driver (G7) calls this BETWEEN calls of a long run, so
        the run never outlives its hold. Returns the refreshed `Hold`. Under the lock (so a
        concurrent admit's reclaim never races the rewrite)."""
        week = hold.bucket.week
        bdir = self._bucket_dir(hold.bucket)
        udir = self._bucket_dir(umbrella_bucket_key(week))
        now = self.clock()
        expiry = now + float(self.hold_ttl_seconds)
        line = _hold_bytes(hold.token, hold.run_id, hold.ceiling, expiry)
        with self._admission_lock():
            write_replace(bdir / _HOLDS_DIRNAME / hold.token, line)
            write_replace(udir / _HOLDS_DIRNAME / hold.token, line)
        return Hold(
            token=hold.token,
            run_id=hold.run_id,
            ceiling=hold.ceiling,
            expiry=expiry,
            bucket=hold.bucket,
        )


def _drop_hold(path: Path) -> None:
    """Remove a hold file; a missing hold is a no-op (already expired-and-reclaimed / settled)."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------------------
# The `transport set-umbrella-cap` admin API — persisted in the SHARED transport config (G4/G5),
# one store, one renderer. Tier-A admin, NO spend (mirrors entitlement.py's set/clear pattern).
# ---------------------------------------------------------------------------------------


def umbrella_cap(framework_root: str | os.PathLike[str]) -> Decimal | None:
    """The install-wide UMBRELLA weekly cap under `framework_root`, or `None` if unset.

    Reads the shared transport config (`instance/ops/transport/config.yaml`). A missing config → no
    umbrella (`None`). A malformed config raises the G4 `ConfigError` (never a silent guess)."""
    return load_store(framework_root).umbrella_cap_usd


def set_umbrella_cap(framework_root: str | os.PathLike[str], cap: Decimal) -> Path:
    """Set (REPLACE) the install-wide umbrella weekly cap; return the written config path.

    HARD-REFUSES a non-positive / non-finite amount (`UmbrellaCapError`, nothing written) — an
    umbrella must be a real positive weekly dollar budget. Single-valued + swappable; preserves the
    key assignments + entitlement (one store, one renderer). Tier-A admin: selects no transport,
    spends nothing."""
    amount = _as_decimal(cap, what="umbrella cap")
    if not amount.is_finite() or amount <= 0:
        raise UmbrellaCapError(
            f"meter-bad-umbrella-cap: the umbrella cap must be a POSITIVE dollar amount, got "
            f"{cap!r} (a zero/negative/infinite umbrella is not an install-wide weekly budget)"
        )
    store = load_store(framework_root)
    store.set_umbrella_cap(amount)  # REPLACES any prior — single-valued, never a second entry.
    return save_store(store, framework_root)


def clear_umbrella_cap(framework_root: str | os.PathLike[str]) -> Path:
    """Remove the umbrella weekly cap (idempotent); return the written config path. Preserves the
    key assignments + entitlement (one shared config). Tier-A admin, NO spend."""
    store = load_store(framework_root)
    store.clear_umbrella_cap()
    return save_store(store, framework_root)
