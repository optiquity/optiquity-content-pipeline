"""Drift machinery (§11.5): the comparison math, the MIG-6 block/warn/silent table, and
the SV7 update-time report.

Design authority: `docs/design.md`
  §11.5 — meaning vs wording: the prose `definition` is freely improvable; only a MEANING
          change bumps `definition_version`. The drift math is ONE integer comparison —
          `definition_version > entry.schema_version` AND the entry SETS that attribute
          (SV1/§11.2). Drift is checked at BOTH times (SV7 + MIG-6): update-time REPORTS
          (this module's `build_drift_report`, surfaced by `scripts/pipeline drift-report`
          — the PA-9c named entry point; step 40 hooks it into update-from-upstream);
          resolve-time ENFORCES (the table below — the enforcement WIRING lands at plan
          step 16; the machinery and the queryable table live here).
  §11.6 MIG-6 — the block/warn/silent table: BLOCK on meaning-change-affecting-set-attr
          (deterministic or ambiguous alike), removed-attribute-still-present, or a stamp
          outside the migration window (§11.6 MIG-2 — the window ORACLE is
          `pipeline/migration.StepRegistry`; injected here, never imported, so the
          dependency direction stays migration → drift); WARN on new-attribute-available;
          SILENT for wording-only changes.
  §21.7 — codes: `drift-block` and `out-of-window` are pinned here as constants on typed
          findings; the full code taxonomy lands at plan step 32.

Wiring, never duplication: stamps/manifests come from `pipeline/schema.py`
(`Schema.schema_version`, `Schema.definition_versions()` — the step-11 drift inputs) and
`pipeline/entries.py` (`Entry.schema_version`, `Entry.set_attributes`). The LENIENT config
view (`parse_entry_lenient`) reuses `entries.parse_entry` wholesale and relaxes ONLY the
final closed-schema payload check — a stale entry may legitimately hold values that are
invalid under the CURRENT schema (that is exactly what migration exists to fix, §11.6);
refusing to even look at it would make drift/migration unable to see their own inputs.

Clock discipline: every window-dependent function takes an explicit `now` — there is no
ambient `datetime.today()` anywhere in this module; the CLI (`pipeline/__main__.py`)
injects real time at the edge.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Protocol

from pipeline.attrtypes import ValueValidationError
from pipeline.entries import (
    ENTRY_SUFFIX,
    ENVELOPE_KEYS,
    PROVENANCE_INSTANCE,
    Entry,
    EntryError,
    parse_entry,
)
from pipeline.schema import (
    SCHEMA_FILENAME,
    Schema,
    SchemaValidationError,
    load_schema,
)
from pipeline.yamlio import load_frontmatter

__all__ = [
    "CODE_DRIFT_BLOCK",
    "CODE_OUT_OF_WINDOW",
    "CollectionDrift",
    "DriftError",
    "DriftFinding",
    "DriftKind",
    "DriftReport",
    "EntryNote",
    "RESOLVE_TIME_TABLE",
    "Severity",
    "WindowOracle",
    "blocking_findings",
    "blocking_kinds",
    "build_drift_report",
    "check_entry",
    "iter_collections",
    "iter_entry_files",
    "load_entry_lenient",
    "meaning_changed_attributes",
    "new_attributes_available",
    "parse_entry_lenient",
    "removed_attributes",
    "render_drift_report",
    "severity_for",
]

#: §21.7 pinned code: hard drift at resolve time (meaning change / removed attribute).
CODE_DRIFT_BLOCK = "drift-block"
#: §21.7 pinned code: entry stamp outside the 1-year migration window (MIG-2).
CODE_OUT_OF_WINDOW = "out-of-window"


class DriftError(ValueError):
    """Misuse of the drift machinery itself (never a drift *finding*)."""

    code = "drift-machinery-misuse"


class Severity(Enum):
    """The three MIG-6 behaviors. There is no fourth (§11.5)."""

    BLOCK = "block"
    WARN = "warn"
    SILENT = "silent"


class DriftKind(Enum):
    """The §11.5/MIG-6 drift classes, exactly as the design names them."""

    #: A meaning change (deterministic OR ambiguous — the table does not distinguish)
    #: affecting an attribute the object sets.
    MEANING_CHANGE = "meaning-change-affecting-set-attribute"
    #: The entry still sets an attribute the current schema no longer declares.
    REMOVED_ATTRIBUTE = "removed-attribute-still-present"
    #: The entry stamp is outside the 1-year migration window (MIG-2).
    OUT_OF_WINDOW = "stamp-outside-migration-window"
    #: A declared attribute is newer than the entry's stamp and the entry does not set
    #: it — the entry rides the CURRENT schema default (new-or-redefined-since-stamp;
    #: §11.5 "new attributes now on defaults").
    NEW_ATTRIBUTE = "new-attribute-available"
    #: A prose-only `definition` edit: `definition_version` does not move, so the integer
    #: math never fires — silent BY CONSTRUCTION. Present in the table so step 16 (and
    #: tests) can query all five rows; `check_entry` never emits it as a finding.
    WORDING_ONLY = "wording-only-change"


#: The MIG-6 resolve-time table (§11.5), encoded and queryable — plan step 16 imports this
#: to enforce; nothing here performs the enforcement itself.
RESOLVE_TIME_TABLE: dict[DriftKind, Severity] = {
    DriftKind.MEANING_CHANGE: Severity.BLOCK,
    DriftKind.REMOVED_ATTRIBUTE: Severity.BLOCK,
    DriftKind.OUT_OF_WINDOW: Severity.BLOCK,
    DriftKind.NEW_ATTRIBUTE: Severity.WARN,
    DriftKind.WORDING_ONLY: Severity.SILENT,
}

#: §21.7 code per drift kind (WARN/SILENT kinds carry no pinned code — step 32's taxonomy).
_KIND_CODES: dict[DriftKind, str | None] = {
    DriftKind.MEANING_CHANGE: CODE_DRIFT_BLOCK,
    DriftKind.REMOVED_ATTRIBUTE: CODE_DRIFT_BLOCK,
    DriftKind.OUT_OF_WINDOW: CODE_OUT_OF_WINDOW,
    DriftKind.NEW_ATTRIBUTE: None,
    DriftKind.WORDING_ONLY: None,
}


def severity_for(kind: DriftKind) -> Severity:
    """The queryable MIG-6 table lookup (step 16's enforcement input)."""
    return RESOLVE_TIME_TABLE[kind]


def blocking_kinds() -> frozenset[DriftKind]:
    """Every kind the MIG-6 table marks BLOCK."""
    return frozenset(k for k, s in RESOLVE_TIME_TABLE.items() if s is Severity.BLOCK)


@dataclass(frozen=True)
class DriftFinding:
    """One drift determination for one entry (comparison output, never enforcement)."""

    kind: DriftKind
    severity: Severity
    #: §21.7 pinned code (`drift-block` / `out-of-window`) or None for warn-tier findings.
    code: str | None
    collection: str
    entry_id: str
    #: The affected attribute (None for whole-object findings, e.g. out-of-window).
    attribute: str | None
    entry_stamp: int
    current_version: int
    #: The attribute's `definition_version` (None where not attribute-scoped).
    definition_version: int | None
    detail: str


class WindowOracle(Protocol):
    """The out-of-window determination (MIG-2) — implemented by
    `pipeline.migration.StepRegistry` and INJECTED here (dependency stays one-way).

    Returns a human-readable block detail when `entry`'s stamp is outside the migration
    window for its collection, else None.
    """

    def out_of_window(self, schema: Schema, entry: Entry, *, now: date) -> str | None: ...


def _require_same_collection(schema: Schema, entry: Entry) -> None:
    if entry.collection != schema.collection:
        raise DriftError(
            f"drift-machinery-misuse: entry {entry.id!r} belongs to collection "
            f"{entry.collection!r}, not {schema.collection!r} — drift compares an entry "
            "against ITS collection's current schema (§11.5)"
        )


def meaning_changed_attributes(schema: Schema, entry: Entry) -> dict[str, int]:
    """§11.5 drift math: attributes whose meaning changed after the entry's stamp AND
    which the entry sets. Returns {attribute: definition_version}."""
    _require_same_collection(schema, entry)
    return {
        name: dv
        for name, dv in schema.definition_versions().items()
        if dv > entry.schema_version and name in entry.set_attributes
    }


def removed_attributes(schema: Schema, entry: Entry) -> list[str]:
    """Attributes the entry sets that the CURRENT schema no longer declares (MIG-3:
    removal = the schema stops declaring X + a forward step handles configs that had X)."""
    _require_same_collection(schema, entry)
    return sorted(name for name in entry.set_attributes if name not in schema.attributes)


def new_attributes_available(schema: Schema, entry: Entry) -> dict[str, int]:
    """Declared attributes newer than the entry's stamp that the entry does NOT set —
    the entry rides the current schema default (L0 floor, §12.2): the WARN row.

    The single-integer math cannot distinguish "introduced after the stamp" from
    "redefined after the stamp, entry never set it" — both ride the current default and
    both are advisory-only, so one WARN kind covers them (§11.5 new-attribute-available).
    """
    _require_same_collection(schema, entry)
    return {
        name: dv
        for name, dv in schema.definition_versions().items()
        if dv > entry.schema_version and name not in entry.set_attributes
    }


def _finding(
    kind: DriftKind,
    schema: Schema,
    entry: Entry,
    *,
    attribute: str | None,
    definition_version: int | None,
    detail: str,
) -> DriftFinding:
    return DriftFinding(
        kind=kind,
        severity=severity_for(kind),
        code=_KIND_CODES[kind],
        collection=schema.collection,
        entry_id=entry.id,
        attribute=attribute,
        entry_stamp=entry.schema_version,
        current_version=schema.schema_version,
        definition_version=definition_version,
        detail=detail,
    )


def check_entry(
    schema: Schema,
    entry: Entry,
    *,
    window: WindowOracle | None = None,
    now: date | None = None,
) -> list[DriftFinding]:
    """The full §11.5/MIG-6 comparison for one entry — used at BOTH check times.

    Emits findings for the four kinds the integer math can fire; WORDING_ONLY is silent
    by construction (a prose edit moves no `definition_version`, so nothing compares
    unequal and no finding exists — the table still carries the row for step 16).

    The out-of-window check runs only when a `window` oracle (the migration step
    registry) is supplied; `now` is then REQUIRED — the clock is injected, never ambient.
    Enforcement (refusing a resolve) is plan step 16's wiring; this returns findings only.
    """
    _require_same_collection(schema, entry)
    if window is not None and now is None:
        raise DriftError(
            "drift-machinery-misuse: `now` is required when a window oracle is supplied "
            "(the clock is injected at the edge, never read ambiently)"
        )
    findings: list[DriftFinding] = []
    for name in removed_attributes(schema, entry):
        findings.append(
            _finding(
                DriftKind.REMOVED_ATTRIBUTE,
                schema,
                entry,
                attribute=name,
                definition_version=None,
                detail=(
                    f"entry sets {name!r} but the current {schema.collection!r} schema "
                    f"(v{schema.schema_version}) no longer declares it — hard drift; "
                    "migrate before use (§11.5/§11.6)"
                ),
            )
        )
    for name, dv in sorted(meaning_changed_attributes(schema, entry).items()):
        findings.append(
            _finding(
                DriftKind.MEANING_CHANGE,
                schema,
                entry,
                attribute=name,
                definition_version=dv,
                detail=(
                    f"{name!r} changed meaning at v{dv} > entry stamp "
                    f"v{entry.schema_version} and the entry sets it — hard drift, "
                    "deterministic or ambiguous alike; migrate before use (§11.5)"
                ),
            )
        )
    if window is not None:
        assert now is not None  # guarded above
        window_detail = window.out_of_window(schema, entry, now=now)
        if window_detail is not None:
            findings.append(
                _finding(
                    DriftKind.OUT_OF_WINDOW,
                    schema,
                    entry,
                    attribute=None,
                    definition_version=None,
                    detail=window_detail,
                )
            )
    for name, dv in sorted(new_attributes_available(schema, entry).items()):
        findings.append(
            _finding(
                DriftKind.NEW_ATTRIBUTE,
                schema,
                entry,
                attribute=name,
                definition_version=dv,
                detail=(
                    f"{name!r} (definition_version {dv}) is newer than the entry stamp "
                    f"v{entry.schema_version}; the entry rides the current schema "
                    "default (advisory only, §11.5)"
                ),
            )
        )
    return findings


def blocking_findings(findings: list[DriftFinding]) -> list[DriftFinding]:
    """The BLOCK-tier subset — step 16's resolve-time refusal input."""
    return [f for f in findings if f.severity is Severity.BLOCK]


# ---------------------------------------------------------------------------------------
# The lenient config view (drift/migration INPUT loading)
# ---------------------------------------------------------------------------------------


def parse_entry_lenient(
    text: str, *, filename_slug: str, schema: Schema, path: Path | None = None
) -> Entry:
    """Parse an entry, relaxing ONLY the closed-schema payload validation.

    A stale (drifted) entry may set values that are invalid under the CURRENT schema —
    that is migration's INPUT, not a refusal case (§11.6; the fold OUTPUT is what must
    validate). Mechanism: run the REAL `entries.parse_entry`; its check order (documented
    in `pipeline/entries.py`) puts the closed-schema payload check LAST, so if — and only
    if — the refusal is a payload-validation error, every envelope rule (identity match,
    provenance default-deny, `x-` namespacing, stamp shape) has already passed and we can
    rebuild the same `Entry` with the unvalidated payload. Envelope errors propagate
    untouched. No validation logic is duplicated here.
    """
    try:
        return parse_entry(text, filename_slug=filename_slug, schema=schema, path=path)
    except (SchemaValidationError, ValueValidationError):
        frontmatter, body = load_frontmatter(text)
        assert isinstance(frontmatter, dict)  # envelope checks already passed
        payload = {k: v for k, v in frontmatter.items() if k not in ENVELOPE_KEYS}
        return Entry(
            collection=schema.collection,
            id=frontmatter["id"],
            provenance=frontmatter["provenance"],
            schema_version=frontmatter["schema_version"],
            attributes=payload,
            body=body,
            path=path,
        )


def load_entry_lenient(path: str | Path, schema: Schema) -> Entry:
    """`entries.load_entry` semantics with the lenient payload posture (same path rules)."""
    path = Path(path)
    # Path-shape refusals are envelope-tier: reuse load_entry's checks by delegating the
    # strict path first would double-read; instead mirror its two guards via parse_entry's
    # own refusals — the filename slug check happens inside parse_entry.
    if path.suffix != ENTRY_SUFFIX or path.name == ENTRY_SUFFIX:
        # Same refusal load_entry raises (kept identical so callers see one behavior).
        raise EntryError(
            f"invalid-entry: {path.name!r}: registry entries are `<slug>{ENTRY_SUFFIX}` files"
        )
    filename_slug = path.name[: -len(ENTRY_SUFFIX)]
    text = path.read_text(encoding="utf-8")
    return parse_entry_lenient(text, filename_slug=filename_slug, schema=schema, path=path)


# ---------------------------------------------------------------------------------------
# Config-tree walking (shared by the drift report and the migration runner)
# ---------------------------------------------------------------------------------------

#: Directory names never descended into. The store names encode MIG-7's config-only scope
#: STRUCTURALLY for every walker consumer: artifact/deliverable/output/claim/folio/review
#: stores are immutable machine records (§11.6 MIG-7, §18, §22.3) and are never scanned,
#: on top of the primary guarantee that only directories carrying a co-located
#: `_schema.yaml` are config collections at all (SV4 §13.4).
PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".github",
        ".claude",
        ".venv",
        "__pycache__",
        "node_modules",
        "tests",
        "docs",
        "scripts",
        "artifacts",
        "deliverables",
        "output",
        "claims",
        "folios",
        "reviews",
        "select",
        "ops",
        "graphify-out",
    }
)


def iter_collections(root: str | Path) -> Iterator[Path]:
    """Yield every config-collection directory under `root` (deterministic order).

    A collection is any non-pruned directory containing `_schema.yaml` (SV4 co-location).
    Read-only; never follows symlinks.
    """
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(
            d for d in dirnames if d not in PRUNED_DIR_NAMES and not d.startswith(".")
        )
        if SCHEMA_FILENAME in filenames:
            yield Path(dirpath)


def iter_entry_files(collection_dir: str | Path) -> Iterator[Path]:
    """Yield the entry files of one collection (sorted; `*.template.*` scaffolding and
    the `_schema.yaml` manifest are never entries)."""
    for p in sorted(Path(collection_dir).glob(f"*{ENTRY_SUFFIX}")):
        if ".template." in p.name:
            continue
        yield p


# ---------------------------------------------------------------------------------------
# The SV7 update-time report (PA-9c: `scripts/pipeline drift-report`)
# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryNote:
    """A non-finding report line: an entry/schema that could not be assessed (loud,
    never fatal — the update-time report is non-destructive and total, §11.5)."""

    path: str
    message: str


@dataclass
class CollectionDrift:
    """One collection's slice of the update-time report."""

    collection: str
    path: str
    schema_version: int
    entries_scanned: int = 0
    framework_entries: int = 0
    instance_entries: int = 0
    findings: list[DriftFinding] = field(default_factory=list)
    notes: list[EntryNote] = field(default_factory=list)


@dataclass
class DriftReport:
    """The SV7 update-time report over a config tree ("an upstream merge is
    non-destructive and produces an upgrade notice", §11.5)."""

    root: str
    now: date
    collections: list[CollectionDrift] = field(default_factory=list)
    #: Tree-level notes (e.g. an unloadable `_schema.yaml`).
    notes: list[EntryNote] = field(default_factory=list)

    @property
    def blocking(self) -> list[DriftFinding]:
        return [f for c in self.collections for f in c.findings if f.severity is Severity.BLOCK]

    @property
    def warnings(self) -> list[DriftFinding]:
        return [f for c in self.collections for f in c.findings if f.severity is Severity.WARN]

    @property
    def has_blocks(self) -> bool:
        return bool(self.blocking)


def build_drift_report(
    root: str | Path, *, now: date, window: WindowOracle | None = None
) -> DriftReport:
    """Run the update-time drift check over every config collection under `root`.

    READ-ONLY by construction (nothing here writes). Scans ALL entries: instance config
    is the report's audience (MIG-7 migration scope), and a drifted framework-provenance
    entry is surfaced too — it indicates an upstream lockstep defect (SV11 clause 3),
    worth an upgrade-notice line even though migration never touches it.
    """
    root = Path(root)
    report = DriftReport(root=str(root), now=now)
    for coll_dir in iter_collections(root):
        try:
            schema = load_schema(coll_dir / SCHEMA_FILENAME)
        except ValueError as exc:
            report.notes.append(EntryNote(path=str(coll_dir / SCHEMA_FILENAME), message=str(exc)))
            continue
        coll = CollectionDrift(
            collection=schema.collection,
            path=str(coll_dir),
            schema_version=schema.schema_version,
        )
        for entry_path in iter_entry_files(coll_dir):
            try:
                entry = load_entry_lenient(entry_path, schema)
            except ValueError as exc:
                coll.notes.append(EntryNote(path=str(entry_path), message=str(exc)))
                continue
            coll.entries_scanned += 1
            if entry.provenance == PROVENANCE_INSTANCE:
                coll.instance_entries += 1
            else:
                coll.framework_entries += 1
            if entry.schema_version > schema.schema_version:
                coll.notes.append(
                    EntryNote(
                        path=str(entry_path),
                        message=(
                            f"entry stamp v{entry.schema_version} is AHEAD of the current "
                            f"schema v{schema.schema_version} — a mixed checkout or a "
                            "hand-edited stamp; not a drift state the math covers (§11.2)"
                        ),
                    )
                )
                continue
            coll.findings.extend(check_entry(schema, entry, window=window, now=now))
        report.collections.append(coll)
    return report


def render_drift_report(report: DriftReport) -> str:
    """Deterministic human-readable rendering (the `drift-report` CLI output)."""
    lines: list[str] = []
    lines.append(
        f"DRIFT REPORT (update-time, SV7/MIG-6) — root: {report.root} — as of {report.now}"
    )
    total_entries = sum(c.entries_scanned for c in report.collections)
    lines.append(
        f"collections scanned: {len(report.collections)} · entries: {total_entries} "
        f"(framework {sum(c.framework_entries for c in report.collections)} / "
        f"instance {sum(c.instance_entries for c in report.collections)})"
    )
    for note in report.notes:
        lines.append(f"  NOTE  {note.path}: {note.message}")
    for coll in report.collections:
        lines.append(f"== {coll.collection} (schema_version {coll.schema_version}) ==")
        if not coll.findings and not coll.notes:
            lines.append("  clean — no drift")
            continue
        for f in coll.findings:
            code = f" [{f.code}]" if f.code else ""
            attr = f" attribute {f.attribute!r}" if f.attribute else ""
            lines.append(
                f"  {f.severity.value.upper():6s}{code} {f.collection}/{f.entry_id}"
                f"{attr}: {f.detail}"
            )
        for note in coll.notes:
            lines.append(f"  NOTE   {note.path}: {note.message}")
    n_block = len(report.blocking)
    n_warn = len(report.warnings)
    lines.append(
        f"summary: {n_block} block / {n_warn} warn"
        + (
            " — blocked objects are refused at resolve time until migrated: run "
            "scripts/migrate.sh (user-triggered, never auto-run; §11.6)"
            if n_block
            else " — nothing blocks; wording-only changes are silent by design (§11.5)"
        )
    )
    return "\n".join(lines) + "\n"
