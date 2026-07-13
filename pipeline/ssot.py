"""The tracking SSOT v1: the two-row-kind schema + the local-CSV single-writer (§24).

Design authority: `docs/design.md` §24 (the SSOT tracks the status/progress domain ONLY,
one row per fanout item, monotonic advance-only status — the row/column schema is homed
and delivered HERE; the FR4/FR7.6 new-rows-only rule), §22.7/PC12 (the SSOT is a LAGGING
MONOTONIC PROJECTION that never gates correctness — write-only w.r.t. control flow: expose
`advance()`/`block()` + a human report, NEVER a per-id read predicate the pipeline can
branch on), §22.3/PC4 (per-item row discipline — one item's write never touches another
item's row; the local-CSV backend serializes writes through a SINGLE WRITER), §8 (the two
fanout levels — content fanout → artifacts, rendering fanout → deliverables), §13.3/§13.5
(tabular encoding class), §21.7 (block codes); plan step 22 (PA-4: two row kinds).

**Two row kinds (PA-4), one row per fanout item, each advanced ONLY by its own S5:**

- **artifact rows** — lifecycle ``planned → composed → artifact-reviewed`` (advanced by the
  compose-unit's S5, then the artifact-review outcome, §19).
- **deliverable rows** — lifecycle
  ``planned → fitted → rendered → deliverable-reviewed → ready`` (advanced by the
  render-unit's S5, then the deliverable-review outcome, §19).

A single row NEVER carries both compose-stage and render-stage statuses: the status
namespace is scoped to the row's kind, so an advance carrying the wrong kind's status is a
typed rejection (`wrong-kind`), never a silent cross-write (PC4). Revisions are NEW ROWS
ONLY (FR4/FR7.6) — a re-fit or auto-minted serialize revision is a fresh fanout item with a
fresh id and therefore a fresh row; this module never mutates a prior row into a revision.

**Monotonic-advance semantics (the lagging projection, §22.7):** each row's `status` moves
forward only, governed by a status-rank compare within the row's kind:

- target rank **>** current → the row advances (a forward write); any `block_reason` is
  cleared (a re-drive that makes progress un-blocks the item).
- target rank **==** current → an idempotent no-op (accepted; nothing written).
- target rank **<** current → a stale/regressing write: **rejected, logged, and NEVER
  raised into control flow** (a stale worker can never regress a row, §22.3/PC4).

`block` records a `block_reason` ANNOTATION beside the status (§21.7 codes). It is never a
value in the status ladder, so blocking NEVER regresses a row; a blocked item is terminal
until a re-drive's forward advance clears it. The wave-barrier's blocked set is the sweep's
own (materialized ∪ blocked = expected, §22.3/PC5) — it is NEVER read back from the SSOT
(§22.7): this module exposes no per-id predicate the pipeline could branch on.

**INV-CORRECTNESS direction (§22.7, CI-enforced by `tests/test_inv_correctness.py`):** the
correctness plane (`store`/`claims`/`spine`/the future `sweep`/`parallel`) must NEVER import
this module — the import lint fails the build if it does. This module is a LEAF w.r.t. that
plane: it imports the store's atomic replacing-rename PRIMITIVE for the CSV swap and the id
parser for row-key validation, but `store` never imports it (verify the direction). S5 plugs
in through the spine's opaque ``AdvanceHook = Callable[[str], None]`` (`advance_hook` below):
the spine discards the returned outcome, so no return value can reach control flow.

**The local-CSV single writer (PC4b):** every mutation runs inside a file-lock funnel
(`fcntl.flock` on a sidecar ``<csv>.lock``) around a read-modify-write, committing the whole
table through the store's atomic REPLACING rename (`write_replace`) so a concurrent reader
(`derive_state`) never tears. Rows are re-sorted on every write, so the CSV end-state is
deterministic regardless of the order concurrent advances land. Correctness never depends on
any of this: a slow, failing, or offline writer only lags the human view (§22.7).

**Byte-exact CSV round-trips:** Python 3.12's `Path.read_text` has NO `newline=` kwarg, so
every read is `read_bytes().decode("utf-8")` and every write pins `lineterminator="\n"` — the
derivation is byte-deterministic across runs for a fixed CSV.
"""

from __future__ import annotations

import csv
import fcntl
import io
import logging
import os
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from pipeline.ids import IdError, parse_id
from pipeline.store import write_replace

__all__ = [
    "ARTIFACT_LIFECYCLE",
    "COLUMNS",
    "DELIVERABLE_LIFECYCLE",
    "INITIAL_STATUS",
    "STATUS_LIFECYCLES",
    "AdvanceOutcome",
    "BlockOutcome",
    "RegisterOutcome",
    "Row",
    "RowKind",
    "Ssot",
    "SsotError",
    "derive_state",
]

_log = logging.getLogger("pipeline.ssot")

#: The two fanout levels (§8) become the two row kinds (PA-4).
RowKind = Literal["artifact", "deliverable"]

#: The status ladders (§24). Rank = index; `planned` is rank 0 in both — the shared entry
#: status every fanout item is registered at.
ARTIFACT_LIFECYCLE: tuple[str, ...] = ("planned", "composed", "artifact-reviewed")
DELIVERABLE_LIFECYCLE: tuple[str, ...] = (
    "planned",
    "fitted",
    "rendered",
    "deliverable-reviewed",
    "ready",
)
STATUS_LIFECYCLES: dict[str, tuple[str, ...]] = {
    "artifact": ARTIFACT_LIFECYCLE,
    "deliverable": DELIVERABLE_LIFECYCLE,
}
INITIAL_STATUS = "planned"

#: rank tables per kind: status → its monotonic rank.
_RANKS: dict[str, dict[str, int]] = {
    kind: {status: i for i, status in enumerate(seq)} for kind, seq in STATUS_LIFECYCLES.items()
}

#: The §24 column set (order fixed — it is the CSV header). `coordinates` is the human
#: fanout coordinate string; `source_commit` is the source commit or commit-map digest;
#: `output_path` is the workspace-relative output location; `block_reason` is the §21.7
#: block annotation (empty = not blocked). No timestamp column: currency is computed at
#: read time and never stored (§21.3 — a stored marker would be a mutable lie window).
COLUMNS: tuple[str, ...] = (
    "row_kind",
    "id",
    "coordinates",
    "source_commit",
    "status",
    "output_path",
    "block_reason",
)


class SsotError(ValueError):
    """A planning-time misuse the SSOT can never bookkeep coherently — refused loudly.

    Raised ONLY by `register` (a planning-time call, never on the spine's S5 path): an
    unknown row kind, or an id whose §7.4 level does not match its declared kind. Runtime
    status writes (`advance`/`block`) NEVER raise for business conditions — a stale or
    unknown-row write is a typed, logged rejection so it can never break control flow
    (§22.7).
    """

    code = "ssot-error"


@dataclass(frozen=True)
class Row:
    """One SSOT row — one fanout item (§24). Immutable; a mutation replaces the whole row."""

    row_kind: str
    id: str
    coordinates: str
    source_commit: str
    status: str
    output_path: str
    block_reason: str = ""


@dataclass(frozen=True)
class RegisterOutcome:
    """`register`'s result. `registered` = a fresh `planned` row was created; `exists` =
    the id already had a row (idempotent no-op — one item, one row)."""

    id: str
    code: Literal["registered", "exists"]


@dataclass(frozen=True)
class AdvanceOutcome:
    """One `advance`'s result — a WRITE outcome for logging/human report, never a control
    predicate (§22.7). `code`: `advanced` (forward write) · `idempotent` (equal status,
    no-op) · `regressed` (stale/lower rank — rejected) · `wrong-kind` (a status outside the
    row's kind ladder — rejected, PC4) · `unknown-row` (no such id — rejected). `from_status`
    is None only for `unknown-row`."""

    id: str
    code: Literal["advanced", "idempotent", "regressed", "wrong-kind", "unknown-row"]
    from_status: str | None
    to_status: str


@dataclass(frozen=True)
class BlockOutcome:
    """One `block`'s result. `blocked` = the annotation was set · `already-blocked` = the
    same reason was already recorded (idempotent) · `unknown-row` = no such id (rejected).
    Blocking never touches `status` — it can never be a regression (§24)."""

    id: str
    code: Literal["blocked", "already-blocked", "unknown-row"]
    reason: str


# ---------------------------------------------------------------------------
# The single-writer funnel (§22.3/PC4b) + byte-exact CSV round-trips.
# ---------------------------------------------------------------------------


@contextmanager
def _exclusive_writer(lock_path: Path):
    """Serialize every mutation through ONE writer (PC4b): `fcntl.flock` LOCK_EX on a
    sidecar lock file, blocking until this process owns the funnel. The lock is a SEPARATE
    file from the CSV (which is swapped by atomic rename, invalidating any lock on its
    inode). Advisory and cooperative — the design's named mechanism (§24)."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_rows(csv_path: Path) -> dict[str, Row]:
    """Read the CSV into an id→Row map. Missing file = empty table. Byte-exact:
    `read_bytes().decode()` (Python 3.12 `read_text` has no `newline=` kwarg)."""
    try:
        text = csv_path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return {}
    rows: dict[str, Row] = {}
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        return {}
    if tuple(header) != COLUMNS:
        raise SsotError(
            f"ssot-error: {csv_path} header {header!r} is not the §24 column set {COLUMNS!r} "
            "— the CSV is written atomically, so this is damage, not a race; refusing to guess"
        )
    for record in reader:
        if not record:
            continue
        try:
            fields = dict(zip(COLUMNS, record, strict=True))
        except ValueError as exc:
            # A data row whose field count != the §24 column set. Near-unreachable (writes are
            # atomic whole-table), but surface it as the typed SsotError like header damage —
            # never a raw zip ValueError leaking through the spine's S5.
            raise SsotError(
                f"ssot-error: {csv_path} data row {record!r} has {len(record)} field(s), not the "
                f"§24 column count {len(COLUMNS)} — the CSV is written atomically, so this is "
                "damage, not a race; refusing to guess"
            ) from exc
        rows[fields["id"]] = Row(**fields)
    return rows


def _serialize_rows(rows: dict[str, Row]) -> bytes:
    """Render the table to CSV bytes — rows sorted by (kind, id) for a deterministic
    end-state; `lineterminator="\\n"` for byte-stable output regardless of platform."""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in _sorted_rows(rows):
        writer.writerow([getattr(row, column) for column in COLUMNS])
    return buf.getvalue().encode("utf-8")


def _sorted_rows(rows: dict[str, Row]) -> list[Row]:
    #: kind first (artifacts before deliverables), then id — total and deterministic.
    kind_order = {kind: i for i, kind in enumerate(STATUS_LIFECYCLES)}
    return sorted(rows.values(), key=lambda r: (kind_order.get(r.row_kind, len(kind_order)), r.id))


def _write_rows(csv_path: Path, rows: dict[str, Row]) -> None:
    """Commit the whole table through the store's atomic REPLACING rename (§21.2/§13.3):
    a concurrent reader sees the old or the new file, never a tear (G1 P3)."""
    write_replace(csv_path, _serialize_rows(rows))


# ---------------------------------------------------------------------------
# The SSOT store: register / advance / block — write-only w.r.t. control flow.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ssot:
    """The tracking SSOT over one local CSV (§24). The CSV path is caller-supplied
    (workspace/instance data, gitignored — §10/§23); the lock path defaults to a sidecar
    ``<csv>.lock``. Every method mutates through the single-writer funnel.

    This surface is WRITE-ONLY w.r.t. control flow (§22.7): `register`/`advance`/`block`
    return WRITE outcomes for logging, and there is NO per-id read predicate (no `is_done`
    lookalike, no `status_of`). The only read surface is the module-level `derive_state`,
    which renders the WHOLE human report — never a branchable per-id fact.
    """

    csv_path: Path
    lock_path: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "csv_path", Path(self.csv_path))
        lock = (
            self.csv_path.with_name(self.csv_path.name + ".lock")
            if self.lock_path is None
            else Path(self.lock_path)
        )
        object.__setattr__(self, "lock_path", lock)

    # -- registration (planning-time; fanout emits one row per item) --------

    def register(
        self,
        id_str: str,
        kind: RowKind,
        *,
        coordinates: str = "",
        source_commit: str = "",
        output_path: str = "",
    ) -> RegisterOutcome:
        """Create this fanout item's `planned` row (idempotent — one item, one row, §24).

        Validates that `kind` is known and that the id's §7.4 level matches the kind
        (artifact-level ↔ artifact row; deliverable-level ↔ deliverable row) — a mismatched
        or malformed id is a planning bug and raises `SsotError`. A row already present is
        left untouched and reported `exists` (registration never mutates an existing row).
        """
        self._validate(kind, id_str)
        with _exclusive_writer(self.lock_path):
            rows = _read_rows(self.csv_path)
            if id_str in rows:
                return RegisterOutcome(id_str, "exists")
            rows[id_str] = Row(
                row_kind=kind,
                id=id_str,
                coordinates=coordinates,
                source_commit=source_commit,
                status=INITIAL_STATUS,
                output_path=output_path,
                block_reason="",
            )
            _write_rows(self.csv_path, rows)
        return RegisterOutcome(id_str, "registered")

    # -- the monotonic advance (the spine's S5 + review outcomes) -----------

    def advance(self, id_str: str, to_status: str) -> AdvanceOutcome:
        """Advance this row's status monotonically (§24). Forward → write (clears any
        block); equal → idempotent no-op; lower → a stale write REJECTED and logged; a
        status outside the row's kind ladder → `wrong-kind` REJECTED (PC4); no such id →
        `unknown-row` REJECTED. NEVER raises for these conditions — a failing SSOT can never
        alter control flow (§22.7)."""
        with _exclusive_writer(self.lock_path):
            rows = _read_rows(self.csv_path)
            row = rows.get(id_str)
            if row is None:
                return self._reject(AdvanceOutcome(id_str, "unknown-row", None, to_status))
            ranks = _RANKS.get(row.row_kind, {})
            if to_status not in ranks:
                return self._reject(AdvanceOutcome(id_str, "wrong-kind", row.status, to_status))
            current_rank = ranks[row.status]
            target_rank = ranks[to_status]
            if target_rank > current_rank:
                rows[id_str] = replace(row, status=to_status, block_reason="")
                _write_rows(self.csv_path, rows)
                return AdvanceOutcome(id_str, "advanced", row.status, to_status)
            if target_rank == current_rank:
                return AdvanceOutcome(id_str, "idempotent", row.status, to_status)
            return self._reject(AdvanceOutcome(id_str, "regressed", row.status, to_status))

    def advance_hook(self, to_status: str) -> Callable[[str], None]:
        """Bind `to_status` into the spine's S5 shape (``AdvanceHook = Callable[[str],
        None]``): the returned hook advances the given id's row and returns None — the
        outcome is discarded, keeping S5 side-effect-only (§22.7 guardrail 3)."""

        def _hook(id_str: str) -> None:
            self.advance(id_str, to_status)  # outcome DISCARDED — write-only w.r.t. control flow

        return _hook

    # -- the block annotation (§21.7; never a status regression) ------------

    def block(self, id_str: str, reason: str) -> BlockOutcome:
        """Record a `block_reason` annotation (§21.7) beside the status — never a status
        change, so never a regression (§24). Same reason already present → idempotent
        `already-blocked`; no such id → `unknown-row` (rejected, logged). A forward
        `advance` later clears it (terminal-until-redriven)."""
        if not reason:
            raise SsotError("ssot-error: a block reason must be a non-empty §21.7 code")
        with _exclusive_writer(self.lock_path):
            rows = _read_rows(self.csv_path)
            row = rows.get(id_str)
            if row is None:
                _log.warning("ssot: block on unknown row %r (reason=%r) — ignored", id_str, reason)
                return BlockOutcome(id_str, "unknown-row", reason)
            if row.block_reason == reason:
                return BlockOutcome(id_str, "already-blocked", reason)
            rows[id_str] = replace(row, block_reason=reason)
            _write_rows(self.csv_path, rows)
        return BlockOutcome(id_str, "blocked", reason)

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _reject(outcome: AdvanceOutcome) -> AdvanceOutcome:
        _log.warning(
            "ssot: rejected advance of %r to %r (%s; from %r) — the SSOT is a lagging "
            "monotonic projection, this write never touches control flow (§22.7)",
            outcome.id,
            outcome.to_status,
            outcome.code,
            outcome.from_status,
        )
        return outcome

    @staticmethod
    def _validate(kind: str, id_str: str) -> None:
        if kind not in STATUS_LIFECYCLES:
            raise SsotError(
                f"ssot-error: unknown row kind {kind!r} — the two fanout levels are "
                f"{tuple(STATUS_LIFECYCLES)} (§8/§24)"
            )
        try:
            parsed = parse_id(id_str)
        except IdError as exc:
            raise SsotError(f"ssot-error: {id_str!r} is not a valid pipeline id — {exc}") from exc
        if parsed.family != "artifact" or parsed.level != kind:
            raise SsotError(
                f"ssot-error: id {id_str!r} is {parsed.family}/{parsed.level}-level but was "
                f"registered as a {kind!r} row — one row per fanout item, kind ↔ level (§7.4/§24)"
            )


# ---------------------------------------------------------------------------
# The derived `state.md`-style projection (§24; CLAUDE.md rule 3): a human report,
# never a control predicate (§22.7). Read-only; byte-deterministic for a fixed CSV.
# ---------------------------------------------------------------------------


def derive_state(csv_path: Path | str) -> str:
    """Render the SSOT CSV as a derived, read-only `state.md`-style status section.

    A human report (§22.7): the WHOLE table, never a per-id predicate. Byte-deterministic
    for a fixed CSV — rows in a total (kind, id) order, no wall-clock, `read_bytes().decode()`
    (no `newline=` pitfall). This is a MIRROR of the SSOT, never an authority (CLAUDE.md
    rule 3; §24): on disagreement the SSOT wins and the mirror is refreshed to match.
    """
    rows = _read_rows(Path(csv_path))
    lines: list[str] = [
        "# SSOT status — derived projection (NOT the source of truth)",
        "",
        "> The tracking SSOT is the single source of truth for item status "
        "(CLAUDE.md rule 3; docs/design.md §24). This section is a derived, read-only mirror "
        "— never an authority. On disagreement the SSOT wins and this mirror is refreshed to "
        "match, never the reverse.",
        "",
    ]
    ordered = _sorted_rows(rows)
    for kind, lifecycle in STATUS_LIFECYCLES.items():
        kind_rows = [row for row in ordered if row.row_kind == kind]
        lines.append(f"## {kind.capitalize()} rows ({' → '.join(lifecycle)})")
        lines.append("")
        lines.append("| id | coordinates | status | block | source commit | output path |")
        lines.append("|----|-------------|--------|-------|---------------|-------------|")
        if kind_rows:
            for row in kind_rows:
                lines.append(
                    f"| {row.id} | {row.coordinates} | {row.status} | {row.block_reason} "
                    f"| {row.source_commit} | {row.output_path} |"
                )
        else:
            lines.append("| _(none)_ |  |  |  |  |  |")
        lines.append("")
        counts = _status_counts(kind_rows, lifecycle)
        lines.append("Status counts: " + counts)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _status_counts(rows: list[Row], lifecycle: tuple[str, ...]) -> str:
    tally = {status: 0 for status in lifecycle}
    blocked = 0
    for row in rows:
        tally[row.status] = tally.get(row.status, 0) + 1
        if row.block_reason:
            blocked += 1
    parts = [f"{status} {tally[status]}" for status in lifecycle]
    parts.append(f"blocked {blocked}")
    return " · ".join(parts)
