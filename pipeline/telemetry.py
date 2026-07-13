"""Presence-lease registry + append-only CONTENT-FREE telemetry (§22.5, §24) under instance/ops/.

Design authority: `docs/design.md`
  §22.5 (PC11) — two small instance-scoped persisted structures: a SELF-HEALING
        presence-lease registry (live-lease count = account-wide in-flight concurrency; a
        dead worker's lease self-expires) and an APPEND-ONLY JSONL telemetry log off the
        critical path. Captured: `observed_inflight` at backpressure onset, interval rollups
        (started/completed, peak, throughput, claim-health counters). **ZERO CONTENT: no
        artifact ids, no client/workspace identifiers, no secrets** — sessions across
        workspaces register in the same registry seeing only a COUNT (rule-2-clean:
        operational metrics are not client data). Mechanism = `provenance: framework`; the
        data = `provenance: instance`, gitignored (§10, §23). At `begin-session` the system
        computes an advisory `recommended_width` from the recent window and returns it
        alongside `suggested_width` — warning when below the configured cap, NEVER auto-applied.
        Capture is default-on and disable-able.
  §24 (PC11c / PA-9b) — the OPTIONAL content-free interval-rollup counter `forced_reconciles`
        (COUNT ONLY — no ids, no workspace identifiers).
  §23 — instance/ops/ homes the presence-lease registry + telemetry JSONL: framework
        MECHANISM, instance DATA (gitignored-in-public; the `.gitignore` gains `instance/ops/`).

**CONTENT-FREE BY CONSTRUCTION (proven by grep — `tests/test_telemetry.py`).** A telemetry
record's only string is `event`, constrained to the closed `TELEMETRY_EVENTS` enum; EVERY
other field is a finite number (a count or a timing). The writer REFUSES any key outside the
closed `TELEMETRY_FIELDS` set and any non-numeric value — so an artifact id (`a-…`), a folio
id (`f-…`), a workspace name, or any content is structurally impossible to emit, not merely
omitted by convention. The presence-lease registry is likewise content-free: a lease FILENAME
is a random opaque token (never a workspace name), its CONTENT is a single `lease_expiry`
timing.

This module is NOT an INV-CORRECTNESS root (it is operational telemetry, off the critical
path); it reuses the store's G1 atomic primitives (`append_jsonl_line`, `create_exclusive`,
`write_replace`) and imports no SSOT.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline import opdefaults
from pipeline.store import append_jsonl_line, create_exclusive, write_replace

__all__ = [
    "TELEMETRY_EVENTS",
    "TELEMETRY_FIELDS",
    "Clock",
    "PresenceLease",
    "PresenceRegistry",
    "TelemetryError",
    "TelemetryLog",
    "WidthAdvisory",
    "mint_presence_token",
    "recommend_width",
]

#: Epoch-seconds time source (UTC). Injectable — no ambient `now()` in the lease/telemetry
#: logic; the module default is applied only at the constructor boundary.
Clock = Callable[[], float]

#: The closed telemetry EVENT enum — the ONLY string a record may carry (a category label,
#: never content). `interval` = a rollup window; `backpressure` = an onset observation.
TELEMETRY_EVENTS = frozenset({"interval", "backpressure"})

#: The closed telemetry FIELD set (§22.5/§24). EVERY field but `event` is a finite NUMBER —
#: a count or a timing. There is deliberately no id/workspace/content field: content-free by
#: construction (the grep test proves it). `forced_reconciles` is the §24 PC11c counter.
TELEMETRY_FIELDS = frozenset(
    {
        "event",  # the fixed enum label (the sole string)
        "ts",  # emission timing (epoch seconds)
        "interval_seconds",  # rollup window length
        "started",  # units started in the interval
        "completed",  # units completed in the interval
        "peak_inflight",  # peak concurrency in the interval
        "throughput",  # completed / interval_seconds
        "observed_inflight",  # concurrency at a backpressure onset
        "claims_ok",  # claim-health: fresh claims won
        "claims_held",  # claim-health: live-lease skips
        "leases_expired_redriven",  # claim-health: expired-lease steals
        "collisions_averted",  # claim-health: no-replace commit losses
        "forced_reconciles",  # §24 PC11c: forced-reconcile count (COUNT ONLY)
    }
)


class TelemetryError(ValueError):
    """A telemetry record that would not be content-free (unknown event/field, or a
    non-numeric value) — REFUSED, so no id/workspace/content can ever be smuggled in."""

    code = "telemetry-not-content-free"


def _is_number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, int | float)
        and math.isfinite(value)
    )


# ---------------------------------------------------------------------------
# The append-only, content-free telemetry log (§22.5). Off the critical path.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TelemetryLog:
    """An append-only JSONL telemetry log (§22.5) — content-free by construction, disable-able.

    `path` is an instance/ops/ JSONL file (workspace/instance data, gitignored — §10/§23).
    `enabled` default-on (§22.5 PC11); a DISABLED log writes NOTHING (`record` is a no-op) —
    so a privacy-conscious operator can turn capture off entirely. `clock` stamps each `ts`.
    """

    path: Path
    enabled: bool = opdefaults.TELEMETRY_ENABLED_DEFAULT
    clock: Clock = time.time

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))

    def _validate(self, record: dict[str, Any]) -> None:
        """Refuse any record that is not content-free (the structural guarantee, §22.5)."""
        event = record.get("event")
        if event not in TELEMETRY_EVENTS:
            raise TelemetryError(
                f"telemetry-not-content-free: event {event!r} is not in the closed set "
                f"{sorted(TELEMETRY_EVENTS)!r} (§22.5)"
            )
        for key, value in record.items():
            if key not in TELEMETRY_FIELDS:
                raise TelemetryError(
                    f"telemetry-not-content-free: field {key!r} is outside the closed "
                    f"content-free field set (§22.5/§24) — no id/workspace/content may be emitted"
                )
            if key == "event":
                continue
            if not _is_number(value):
                raise TelemetryError(
                    f"telemetry-not-content-free: field {key!r} carries a non-numeric value "
                    f"{value!r} — every telemetry field but `event` is a finite count/timing"
                )

    def record(self, event: str, **fields: Any) -> bool:
        """Append ONE content-free JSONL line (§22.5). Returns True iff a line was written
        (False when disabled). Stamps `ts` from the clock when absent. Validates content-free
        BEFORE writing — a disallowed field/value is refused loudly, never silently dropped."""
        if not self.enabled:
            return False
        record: dict[str, Any] = {"event": event}
        if "ts" not in fields:
            record["ts"] = float(self.clock())
        record.update(fields)
        self._validate(record)
        append_jsonl_line(self.path, record)
        return True

    def record_interval(
        self,
        *,
        interval_seconds: float,
        started: int,
        completed: int,
        peak_inflight: int,
        claims_ok: int = 0,
        claims_held: int = 0,
        leases_expired_redriven: int = 0,
        collisions_averted: int = 0,
        forced_reconciles: int = 0,
    ) -> bool:
        """An interval rollup (§22.5): started/completed, peak, throughput, the claim-health
        counters, and the §24 `forced_reconciles` count. Throughput is derived here (still a
        number). Content-free by construction — no ids, no workspace identifiers."""
        throughput = completed / interval_seconds if interval_seconds > 0 else 0.0
        return self.record(
            "interval",
            interval_seconds=float(interval_seconds),
            started=started,
            completed=completed,
            peak_inflight=peak_inflight,
            throughput=throughput,
            claims_ok=claims_ok,
            claims_held=claims_held,
            leases_expired_redriven=leases_expired_redriven,
            collisions_averted=collisions_averted,
            forced_reconciles=forced_reconciles,
        )

    def record_backpressure(self, *, observed_inflight: int) -> bool:
        """A backpressure onset (§22.5): only the `observed_inflight` count — the concurrency
        level at which the subscription pushed back. Content-free."""
        return self.record("backpressure", observed_inflight=observed_inflight)

    def read_records(self) -> list[dict[str, Any]]:
        """Read the JSONL back (for `recommend_width` + tests). A torn FINAL line (crash
        mid-append) is discarded per §13.3 — never a hard read failure."""
        try:
            text = self.path.read_bytes().decode("utf-8")
        except FileNotFoundError:
            return []
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue  # a torn final line (§13.3) — discardable, never fatal
            if isinstance(obj, dict):
                records.append(obj)
        return records


# ---------------------------------------------------------------------------
# The self-healing presence-lease registry (§22.5): live count = in-flight concurrency.
# ---------------------------------------------------------------------------


def mint_presence_token() -> str:
    """A collision-resistant, CONTENT-FREE presence token (128 random bits).

    Never a workspace name or any client identifier — an opaque coordination handle. The pid
    prefix is diagnostic garnish; the entropy is the identity. Two sessions across DIFFERENT
    workspaces mint distinct tokens and register in the SAME registry seeing only a COUNT
    (rule-2-clean: operational metrics are not client data, §22.5)."""
    return f"p{os.getpid()}-{os.urandom(16).hex()}"


@dataclass(frozen=True)
class PresenceLease:
    """One registered presence-lease handle: the opaque `token` + this lease's `expiry`."""

    token: str
    expiry: float


@dataclass(frozen=True)
class PresenceRegistry:
    """The instance-scoped presence-lease registry (§22.5): self-healing, content-free.

    `ops_dir` is instance/ops/presence (framework mechanism, instance data — gitignored).
    Each lease is a file NAMED by a random opaque `token` (never a workspace), CONTENT a
    single `lease_expiry` timing. `live_count()` = the account-wide in-flight concurrency
    (leases whose expiry is still in the future); a dead worker's lease self-expires and
    simply stops being counted (§22.5). `ttl_seconds`/`clock` are injectable (no ambient now).
    """

    ops_dir: Path
    ttl_seconds: float = opdefaults.LEASE_TTL_SECONDS
    clock: Clock = time.time

    def __post_init__(self) -> None:
        object.__setattr__(self, "ops_dir", Path(self.ops_dir))

    def _path(self, token: str) -> Path:
        return self.ops_dir / token

    def _line(self, expiry: float) -> bytes:
        return (json.dumps({"lease_expiry": expiry}, sort_keys=True) + "\n").encode("utf-8")

    def register(self) -> PresenceLease:
        """Mint a fresh presence lease (content-free): a random token + `{lease_expiry}`."""
        self.ops_dir.mkdir(parents=True, exist_ok=True)
        for _ in range(8):
            token = mint_presence_token()
            expiry = self.clock() + self.ttl_seconds
            try:
                create_exclusive(self._path(token), self._line(expiry))
            except FileExistsError:
                continue  # astronomically unlikely token collision — remint
            return PresenceLease(token=token, expiry=expiry)
        raise TelemetryError(
            "telemetry-not-content-free: could not mint a unique presence token"
        )

    def refresh(self, token: str) -> PresenceLease:
        """Extend a held lease by one TTL (heartbeat). Content-free replacing-rename update."""
        expiry = self.clock() + self.ttl_seconds
        write_replace(self._path(token), self._line(expiry))
        return PresenceLease(token=token, expiry=expiry)

    def release(self, token: str) -> None:
        """Drop a presence lease (clean exit). A missing lease is a no-op (already released)."""
        try:
            os.unlink(self._path(token))
        except FileNotFoundError:
            pass

    def live_count(self) -> int:
        """The account-wide in-flight concurrency (§22.5): the count of NON-EXPIRED leases.

        A dead worker's lease is simply not counted (self-healing); an unreadable/torn lease
        is conservatively excluded. Reads only timings — never any id or workspace identifier.
        """
        if not self.ops_dir.is_dir():
            return 0
        now = self.clock()
        live = 0
        for entry in self.ops_dir.iterdir():
            if not entry.is_file():
                continue
            try:
                record = json.loads(entry.read_bytes())
            except (ValueError, OSError):
                continue
            expiry = record.get("lease_expiry") if isinstance(record, dict) else None
            if _is_number(expiry) and now < float(expiry):
                live += 1
        return live


# ---------------------------------------------------------------------------
# The advisory recommended_width (§22.5, PC11) — ADVICE ONLY, never auto-applied.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WidthAdvisory:
    """The §22.5 `recommended_width` advisory. `recommended_width` is ADVICE the caller may
    heed or ignore — NEVER auto-applied; the user's `cap` stays authoritative (§3.1).
    `below_cap` flags a recommendation under the configured cap (the design's warn trigger);
    `basis` names why (human-readable, not a control token)."""

    recommended_width: int
    below_cap: bool
    basis: str


def recommend_width(
    log: TelemetryLog,
    *,
    cap: int,
    window_seconds: float = opdefaults.RECOMMENDED_WIDTH_WINDOW_SECONDS,
    now: float | None = None,
) -> WidthAdvisory:
    """Compute an advisory width from the recent telemetry window (§22.5) — ADVICE ONLY.

    With NO backpressure observed in the window, recommend the full `cap` (nothing suggests
    the account can't sustain it). If backpressure WAS observed, recommend staying strictly
    below the LOWEST concurrency that triggered it (`min observed_inflight − 1`), clamped to
    `[1, cap]`. The result is NEVER auto-applied — `begin-session` returns it alongside
    `suggested_width` and warns when it is below the cap; the user's cap remains authoritative.
    """
    now = log.clock() if now is None else now
    horizon = now - window_seconds
    backpressures = [
        r["observed_inflight"]
        for r in log.read_records()
        if r.get("event") == "backpressure"
        and _is_number(r.get("observed_inflight"))
        and _is_number(r.get("ts"))
        and r["ts"] >= horizon
    ]
    if not backpressures:
        return WidthAdvisory(
            recommended_width=cap, below_cap=False, basis="no backpressure in the window"
        )
    floor = min(int(v) for v in backpressures)
    recommended = max(1, min(cap, floor - 1))
    return WidthAdvisory(
        recommended_width=recommended,
        below_cap=recommended < cap,
        basis=f"backpressure observed at inflight ≥ {floor} in the window",
    )
