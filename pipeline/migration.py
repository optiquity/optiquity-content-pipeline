"""The §11.6 migration system (MIG-1…MIG-7): declarative step registry, the one fold,
the 1-year window, the decisions-needed worklist, and the owner-triggered runner.

Design authority: `docs/design.md`
  MIG-1 — declarative, APPEND-ONLY step registry (per-attribute common case; object-level
          escape hatch); migration = ONE fold over the half-open interval
          `(entry-stamp, current]`. Skip-safety is structural (any span folds directly to
          current; no chaining); NO INVERSE IS REPRESENTABLE (the action vocabulary has no
          revert — forward-only is structural); an empty interval folds to a no-op, so
          idempotency is structural too.
  MIG-2 — a 1-year time window by RELEASE DATE bounds the registry; a config needing
          steps past the window BLOCKS loudly ("past the 1-year support window —
          regenerate or hand-fix; unsupported"). Walking an ancient config forward via
          git-preserved registries is a user-owned, unsupported path.
  MIG-3 — no deprecation lifecycle: removal = current schema stops declaring X + a
          forward step drops/remaps configs that had X; a rename = a lossless remap step.
  MIG-4 — BINARY BY SHAPE (§11.5 SV6): a step ships either a total, typed forward
          transform (deterministic → auto-applied) or a `prompt` (ambiguous → halts for a
          human). The SHAPE is the classification; there is no third tag.
  MIG-5 — the human gate is a RESUMABLE worklist file (never interactive prompting):
          grouped by change with a group-level decision slot that fans across every
          config sharing the change; a skip-span run surfaces the UNION of pending
          decisions; re-stamping is OBJECT-ATOMIC (an object re-stamps only when all its
          steps resolve — forced by the single-integer stamp).
  MIG-6 — block/warn/silent behavior: the table lives in `pipeline/drift.py`; this module
          implements the window ORACLE (`StepRegistry.out_of_window`) drift injects.
  MIG-7 — SCOPE: instance-owned, schema-stamped CONFIG only. Framework defaults are
          lockstep-maintained upstream and never instance-migrated (skipped here);
          ARTIFACTS ARE IMMUTABLE — never rewritten (migrate config, then REGENERATE);
          the `metadata` bag is never touched (structural: `metadata` is a reserved name
          no schema declares and no step may target).
  §21.7 — codes surfaced as typed exceptions/results here: `out-of-window` and
          `ambiguous-migration-decisions` (`drift-block` lives in drift.py); the full
          taxonomy lands at plan step 32.

Entry point: `scripts/migrate.sh` → `python -m pipeline.migration` — user-triggered,
mandatory before use, idempotent, and NOT on the external-actor API (§21.9; step-6
parameter sheet). Clock discipline: every window computation takes an explicit `now`;
`main()` injects real time at the CLI edge (the only ambient clock read).
"""

from __future__ import annotations

import argparse
import copy
import io
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, validate_value
from pipeline.drift import (
    CODE_OUT_OF_WINDOW,
    iter_collections,
    iter_entry_files,
    load_entry_lenient,
    meaning_changed_attributes,
    removed_attributes,
)
from pipeline.entries import PROVENANCE_INSTANCE, Entry
from pipeline.opgrammar import PathSyntaxError, validate_path
from pipeline.schema import (
    RESERVED_ATTRIBUTE_NAMES,
    SCHEMA_FILENAME,
    Schema,
    load_schema,
    require_bare_int,
)
from pipeline.yamlio import load_yaml, make_loader

__all__ = [
    "CODE_AMBIGUOUS_MIGRATION_DECISIONS",
    "CODE_OUT_OF_WINDOW",
    "DecisionError",
    "DecisionSet",
    "FoldOutcome",
    "ForwardOnlyError",
    "MIGRATION_REGISTRY_RELPATH",
    "MigrationError",
    "MigrationStep",
    "ObjectOutcome",
    "OutOfWindowError",
    "RegistryError",
    "RunResult",
    "StepRegistry",
    "TotalityError",
    "WINDOW_DAYS",
    "WorklistError",
    "WORKLIST_RELPATH",
    "fold_entry",
    "load_step_registry",
    "load_step_registry_text",
    "load_worklist_decisions",
    "main",
    "require_in_window",
    "run_migration",
]

#: §21.7 pinned code: a run paused on the MIG-5 human worklist (needs-input tier).
CODE_AMBIGUOUS_MIGRATION_DECISIONS = "ambiguous-migration-decisions"

#: MIG-2: the support window — "one year by release date".
WINDOW_DAYS = 365

#: The framework-shipped registry's canonical home (data file inside the framework
#: package, the T9 precedent). v1 ships NO meaning changes, so no file exists yet;
#: a missing registry loads as EMPTY (an empty fold is a structural no-op, MIG-1).
MIGRATION_REGISTRY_RELPATH = "pipeline/migrations.yaml"

#: The decisions-needed worklist's default home: instance-scoped ops state (§23
#: `instance/ops/` — mechanism framework, data instance; never tracked in public).
WORKLIST_RELPATH = "instance/ops/migration-worklist.yaml"

#: The worklist document format marker (bumped only if the worklist shape changes).
WORKLIST_FORMAT = "migration-worklist/1"

#: Step action vocabulary (MIG-4): the deterministic shapes are total, typed, forward
#: transforms; `prompt` is the single ambiguous shape. NO inverse action exists —
#: no-revert is structural (MIG-1).
DETERMINISTIC_ACTIONS = frozenset({"map", "rename", "drop", "edit"})
AMBIGUOUS_ACTION = "prompt"

_SCOPE_ATTRIBUTE = "attribute"
_SCOPE_OBJECT = "object"

#: Slug validation = the §7.4 alphabet's single implementation (attrtypes' `ref` type) —
#: the same local-spec pattern `schema.py`/`entries.py` use.
_REF_SPEC = AttrTypeSpec(kind="ref")

#: Closed per-step key vocabulary in the registry file.
_STEP_KEYS = frozenset(
    {
        "id",
        "version",
        "released",
        "collection",
        "scope",
        "attribute",
        "map",
        "rename_to",
        "drop",
        "edit",
        "prompt",
        "suggested",
    }
)
_ACTION_KEYS = frozenset({"map", "rename_to", "drop", "edit", "prompt"})


class MigrationError(ValueError):
    """A migration failure — refused loudly, never repaired silently."""

    code = "migration-error"


class RegistryError(MigrationError):
    """A malformed migration step registry (MIG-1 discipline violated)."""

    code = "invalid-migration-registry"


class ForwardOnlyError(RegistryError):
    """MIG-1: the registry is append-only and forward-only — a lower-target entry
    appended after a higher one is refused (no inverse is representable)."""

    code = "forward-only-violation"


class OutOfWindowError(MigrationError):
    """MIG-2: the config's stamp needs steps past the 1-year support window."""

    code = CODE_OUT_OF_WINDOW


class TotalityError(MigrationError):
    """A shipped deterministic map is not total over an encountered value (SV6/§27.4 —
    schema-lint validates totality per release; hitting this at fold time is loud)."""

    code = "migration-map-not-total"


class DecisionError(MigrationError):
    """A worklist decision that cannot be applied (wrong shape/type for the target)."""

    code = "invalid-migration-decision"


class WorklistError(MigrationError):
    """A malformed decisions-needed worklist file (MIG-5)."""

    code = "invalid-migration-worklist"


def _refuse_directives(text: str, *, where: str) -> None:
    """The same S-E8 `%`-directive refusal the frontmatter splitter and `_schema.yaml`
    loader apply (yamlio S-E8; schema.py RV-3 carry-forward): an in-document `%YAML 1.1`
    would re-enable the Norway problem. BOM handled by the caller (S-E12 parity)."""
    for line in text.splitlines():
        if line.startswith("%"):
            raise RegistryError(
                f"invalid-migration-registry: a %-directive line in {where} (S-E8; "
                f"refused line: {line!r})"
            )


def _require_slug(value: object, what: str) -> str:
    try:
        validate_value(_REF_SPEC, value)
    except ValueError as exc:
        raise RegistryError(
            f"invalid-migration-registry: {what} {value!r} is not a §7.4 slug "
            "([a-z0-9-], 1-40 chars)"
        ) from exc
    assert isinstance(value, str)
    return value


def _require_attribute_name(value: object, what: str) -> str:
    """Attribute names in steps live in the same §13.2 single-segment alphabet schemas
    use, and may NEVER be a reserved envelope/bag name — which makes the `metadata` bag
    (and the stamp itself) structurally untouchable by migration (MIG-7, §11.3)."""
    if not isinstance(value, str) or not value or "." in value:
        raise RegistryError(
            f"invalid-migration-registry: {what} must be a single-segment attribute "
            f"name, got {value!r}"
        )
    try:
        validate_path(value)
    except PathSyntaxError as exc:
        raise RegistryError(
            f"invalid-migration-registry: {what} {value!r} is not a §13.2 identifier"
        ) from exc
    if value in RESERVED_ATTRIBUTE_NAMES:
        raise RegistryError(
            f"invalid-migration-registry: {what} {value!r} is a reserved envelope/bag "
            f"name — migration never touches {sorted(RESERVED_ATTRIBUTE_NAMES)} "
            "(MIG-7: the metadata bag is never migrated; stamps are the runner's own)"
        )
    return value


def _require_date(value: object, what: str) -> date:
    # The pinned YAML 1.2 loader yields datetime.date for bare dates (G4 deviation D2) —
    # exactly the type the window math needs. datetime (with time) is refused: release
    # dates are dates.
    if isinstance(value, datetime) or not isinstance(value, date):
        raise RegistryError(
            f"invalid-migration-registry: {what} must be a bare YAML date "
            f"(YYYY-MM-DD), got {type(value).__name__}: {value!r}"
        )
    return value


@dataclass(frozen=True)
class MigrationStep:
    """One declarative MIG-1 step, authored once at the release that made the change.

    `scope` is `attribute` (the common case) or `object` (the escape hatch). The action
    SHAPE is the MIG-4 classification: `map`/`rename`/`drop`/`edit` are deterministic
    (total, typed, forward); `prompt` is ambiguous and halts for a human (MIG-5).
    """

    id: str
    #: The trigger: the global schema_version whose release shipped this change (§11.2).
    version: int
    #: Release date — the MIG-2 window operand.
    released: date
    collection: str
    scope: str  # _SCOPE_ATTRIBUTE | _SCOPE_OBJECT
    action: str  # map | rename | drop | edit | prompt
    attribute: str | None = None
    #: `map`: old value → new value (must be total over shipped/instance values — SV6).
    value_map: dict[Any, Any] | None = None
    #: `rename`: the new attribute name (lossless total remap, MIG-3).
    rename_to: str | None = None
    #: `edit` (object-level deterministic escape hatch): assignments + removals.
    edit_set: dict[str, Any] | None = None
    edit_drop: tuple[str, ...] = ()
    #: `prompt` (ambiguous): the question a human answers via the worklist.
    prompt: str | None = None
    #: Optional authored suggestion, DISPLAYED in the worklist — never auto-applied
    #: (§11.5: "never a silent partial-map guess").
    suggested: Any = None

    @property
    def is_deterministic(self) -> bool:
        """MIG-4: the shape IS the classification — binary, machine-checkable."""
        return self.action != AMBIGUOUS_ACTION

    def affects(self, entry: Entry) -> bool:
        """Whether this step touches `entry` (static, against the entry's own set
        attributes; object-scope steps touch every object of the collection)."""
        if self.scope == _SCOPE_OBJECT:
            return True
        return self.attribute in entry.set_attributes

    def describe(self) -> str:
        target = "object-level" if self.scope == _SCOPE_OBJECT else f"attribute {self.attribute!r}"
        return f"step {self.id!r} (v{self.version}, {self.collection}, {target}, {self.action})"


def _parse_step(raw: Any, *, index: int, where: str) -> MigrationStep:
    label = f"{where}: steps[{index}]"
    if not isinstance(raw, Mapping):
        raise RegistryError(f"invalid-migration-registry: {label} must be a mapping")
    unknown = {k for k in raw if not isinstance(k, str)} | (set(raw) - _STEP_KEYS)
    if unknown:
        raise RegistryError(
            f"invalid-migration-registry: {label}: unknown key(s) "
            f"{sorted(repr(k) for k in unknown)} — the step vocabulary is closed "
            f"({sorted(_STEP_KEYS)}); in particular there is NO inverse/revert shape "
            "(forward-only is structural, MIG-1)"
        )
    for required in ("id", "version", "released", "collection"):
        if required not in raw:
            raise RegistryError(f"invalid-migration-registry: {label}: missing {required!r}")
    step_id = _require_slug(raw["id"], f"{label}.id")
    version = require_bare_int(raw["version"], f"{label}.version")
    released = _require_date(raw["released"], f"{label}.released")
    collection = _require_slug(raw["collection"], f"{label}.collection")

    actions = sorted(_ACTION_KEYS & set(raw))
    if len(actions) != 1:
        raise RegistryError(
            f"invalid-migration-registry: {label} ({step_id!r}): a step ships EXACTLY ONE "
            f"shape — a total forward transform (map/rename_to/drop/edit) OR a prompt "
            f"(MIG-4 binary discipline; there is no third tag), got {actions or 'none'}"
        )
    action_key = actions[0]

    scope = raw.get("scope", _SCOPE_ATTRIBUTE)
    if scope not in (_SCOPE_ATTRIBUTE, _SCOPE_OBJECT):
        raise RegistryError(
            f"invalid-migration-registry: {label}: scope must be "
            f"'{_SCOPE_ATTRIBUTE}' (default) or '{_SCOPE_OBJECT}', got {scope!r}"
        )
    if scope == _SCOPE_OBJECT:
        if action_key not in ("edit", "prompt"):
            raise RegistryError(
                f"invalid-migration-registry: {label}: object-scope steps (the MIG-1 "
                f"escape hatch) ship `edit` or `prompt`, not {action_key!r}"
            )
        if "attribute" in raw:
            raise RegistryError(
                f"invalid-migration-registry: {label}: object-scope steps take no `attribute`"
            )
        attribute = None
    else:
        if action_key == "edit":
            raise RegistryError(
                f"invalid-migration-registry: {label}: `edit` is the object-scope shape; "
                "attribute-scope steps ship map/rename_to/drop/prompt"
            )
        if "attribute" not in raw:
            raise RegistryError(
                f"invalid-migration-registry: {label}: attribute-scope steps require `attribute`"
            )
        attribute = _require_attribute_name(raw["attribute"], f"{label}.attribute")

    if "suggested" in raw and action_key != "prompt":
        raise RegistryError(
            f"invalid-migration-registry: {label}: `suggested` accompanies `prompt` only "
            "(a deterministic step needs no suggestion — it IS the answer, MIG-4)"
        )

    value_map: dict[Any, Any] | None = None
    rename_to: str | None = None
    edit_set: dict[str, Any] | None = None
    edit_drop: tuple[str, ...] = ()
    prompt: str | None = None
    if action_key == "map":
        m = raw["map"]
        if not isinstance(m, Mapping) or not m:
            raise RegistryError(
                f"invalid-migration-registry: {label}: `map` must be a non-empty "
                "old-value -> new-value mapping (a TOTAL typed forward map, MIG-4)"
            )
        value_map = dict(m)
        action = "map"
    elif action_key == "rename_to":
        rename_to = _require_attribute_name(raw["rename_to"], f"{label}.rename_to")
        action = "rename"
    elif action_key == "drop":
        if raw["drop"] is not True:
            raise RegistryError(
                f"invalid-migration-registry: {label}: `drop` must be exactly `true` "
                f"(got {raw['drop']!r}) — removal carries no other payload (MIG-3)"
            )
        action = "drop"
    elif action_key == "edit":
        e = raw["edit"]
        if not isinstance(e, Mapping) or not (set(e) <= {"set", "drop"}) or not e:
            raise RegistryError(
                f"invalid-migration-registry: {label}: `edit` must be a mapping with "
                "`set:` (attribute -> value) and/or `drop:` (attribute list)"
            )
        if "set" in e:
            if not isinstance(e["set"], Mapping) or not e["set"]:
                raise RegistryError(
                    f"invalid-migration-registry: {label}: edit.set must be a non-empty mapping"
                )
            edit_set = {
                _require_attribute_name(k, f"{label}.edit.set key"): v for k, v in e["set"].items()
            }
        if "drop" in e:
            if not isinstance(e["drop"], list) or not e["drop"]:
                raise RegistryError(
                    f"invalid-migration-registry: {label}: edit.drop must be a non-empty "
                    "list of attribute names"
                )
            edit_drop = tuple(
                _require_attribute_name(a, f"{label}.edit.drop entry") for a in e["drop"]
            )
        action = "edit"
    else:  # prompt
        p = raw["prompt"]
        if not isinstance(p, str) or not p.strip():
            raise RegistryError(
                f"invalid-migration-registry: {label}: `prompt` must be non-empty prose "
                "(the question the worklist puts to a human, MIG-5)"
            )
        prompt = p
        action = AMBIGUOUS_ACTION

    return MigrationStep(
        id=step_id,
        version=version,
        released=released,
        collection=collection,
        scope=scope,
        action=action,
        attribute=attribute,
        value_map=value_map,
        rename_to=rename_to,
        edit_set=edit_set,
        edit_drop=edit_drop,
        prompt=prompt,
        suggested=raw.get("suggested"),
    )


def _out_of_window_message(
    collection: str, entry_id: str, stamp: int, current: int, reason: str
) -> str:
    """The MIG-2 block message — the design's own words plus the take-responsibility
    escape route (user-owned, unsupported)."""
    return (
        f"out-of-window: {collection}/{entry_id} (stamp v{stamp} -> current v{current}) is "
        f"past the 1-year support window — regenerate or hand-fix; unsupported (MIG-2). "
        f"{reason} There is no version floor and no maintained manual path. Git preserves "
        "each release's registry, so you MAY check out older framework releases and walk "
        "the config forward in <=1-year strides — a tedious, user-owned, UNSUPPORTED path "
        "the framework guarantees nothing about; nothing is ever permanently stranded."
    )


@dataclass(frozen=True)
class StepRegistry:
    """The loaded MIG-1 step registry. Implements drift's `WindowOracle` protocol."""

    steps: tuple[MigrationStep, ...] = ()
    source: str = "<empty>"

    def steps_for(self, collection: str, *, after: int, up_to: int) -> list[MigrationStep]:
        """The ONE fold's selection: steps for `collection` with trigger version in the
        half-open interval `(after, up_to]`, in registry (= version) order (MIG-1)."""
        return [s for s in self.steps if s.collection == collection and after < s.version <= up_to]

    def out_of_window(self, schema: Schema, entry: Entry, *, now: date) -> str | None:
        """The MIG-2 window oracle (drift injects this as `WindowOracle`).

        Blocks (returns a detail message) when:
        (a) any step this entry needs was released more than WINDOW_DAYS before `now` —
            the window is enforced BY DATE, so behavior does not depend on when the
            registry maintainer physically pruned the step body; or
        (b) a meaning change / removed attribute the entry is affected by has NO shipped
            step in the interval — the step was pruned past the window (or an upstream
            SV11 clause-2 defect; both are the same unsupported state here).
        Returns None when the entry is current or fully migratable.
        """
        stamp, current = entry.schema_version, schema.schema_version
        if stamp >= current:
            return None
        affecting = [
            s
            for s in self.steps_for(schema.collection, after=stamp, up_to=current)
            if s.affects(entry)
        ]
        horizon = now - timedelta(days=WINDOW_DAYS)
        stale = [s for s in affecting if s.released < horizon]
        if stale:
            listing = ", ".join(f"{s.id!r} (released {s.released})" for s in stale)
            return _out_of_window_message(
                schema.collection,
                entry.id,
                stamp,
                current,
                f"Needed step(s) {listing} were released more than {WINDOW_DAYS} days "
                f"before {now}.",
            )
        needed = sorted(
            set(meaning_changed_attributes(schema, entry)) | set(removed_attributes(schema, entry))
        )
        object_covered = any(s.scope == _SCOPE_OBJECT for s in affecting)
        covered = {s.attribute for s in affecting if s.attribute is not None}
        uncovered = [a for a in needed if a not in covered and not object_covered]
        if uncovered:
            return _out_of_window_message(
                schema.collection,
                entry.id,
                stamp,
                current,
                f"Meaning changes affecting {uncovered} have no shipped migration step in "
                "the current registry — pruned past the window (or missing upstream, an "
                "SV11 clause-2 lint defect).",
            )
        return None


def load_step_registry_text(text: str, *, source: str) -> StepRegistry:
    """Load and validate one registry document (MIG-1 discipline enforced)."""
    text = text.removeprefix("\ufeff")  # S-E12 parity with schema.load_schema_text
    _refuse_directives(text, where=source)
    data = load_yaml(text)
    if data is None:
        data = {"steps": []}
    if not isinstance(data, Mapping):
        raise RegistryError(
            f"invalid-migration-registry: {source}: the registry is a YAML mapping, got "
            f"{type(data).__name__}"
        )
    unknown = {k for k in data if not isinstance(k, str)} | (set(data) - {"steps"})
    if unknown:
        raise RegistryError(
            f"invalid-migration-registry: {source}: unknown top-level key(s) "
            f"{sorted(repr(k) for k in unknown)} — the registry vocabulary is closed "
            "({'steps'})"
        )
    raw_steps = data.get("steps", [])
    if raw_steps is None:
        raw_steps = []
    if not isinstance(raw_steps, list):
        raise RegistryError(
            f"invalid-migration-registry: {source}: `steps` must be a list "
            "(declare an empty registry explicitly as `steps: []`)"
        )
    steps: list[MigrationStep] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_steps):
        step = _parse_step(raw, index=index, where=source)
        if step.id in seen_ids:
            raise RegistryError(
                f"invalid-migration-registry: {source}: duplicate step id {step.id!r} — "
                "the registry is append-only; steps are never re-authored (MIG-1)"
            )
        seen_ids.add(step.id)
        if steps and step.version < steps[-1].version:
            raise ForwardOnlyError(
                f"forward-only-violation: {source}: steps[{index}] ({step.id!r}) targets "
                f"v{step.version} after {steps[-1].id!r} targeting v{steps[-1].version} — "
                "the registry is APPEND-ONLY and FORWARD-ONLY (MIG-1): entries are "
                "appended in release order and no inverse/downgrade is representable"
            )
        steps.append(step)
    return StepRegistry(steps=tuple(steps), source=source)


def load_step_registry(path: str | Path, *, missing_ok: bool = True) -> StepRegistry:
    """Load the registry file; a MISSING file is the EMPTY registry (v1 ships no meaning
    changes; an empty fold is a structural no-op, MIG-1). Set `missing_ok=False` to
    refuse instead."""
    path = Path(path)
    if not path.exists():
        if missing_ok:
            return StepRegistry(steps=(), source=str(path))
        raise RegistryError(f"invalid-migration-registry: {path} does not exist")
    return load_step_registry_text(path.read_text(encoding="utf-8"), source=str(path))


def require_in_window(schema: Schema, entry: Entry, registry: StepRegistry, *, now: date) -> None:
    """Raise `OutOfWindowError` (code `out-of-window`, §21.7) when the entry's stamp is
    outside the migration window — the typed-exception form of the oracle, for callers
    that enforce rather than report (plan step 16 wires resolve-time enforcement)."""
    detail = registry.out_of_window(schema, entry, now=now)
    if detail is not None:
        raise OutOfWindowError(detail)


# ---------------------------------------------------------------------------------------
# Decisions (MIG-5) and the fold (MIG-1/MIG-4)
# ---------------------------------------------------------------------------------------


@dataclass
class DecisionSet:
    """Human answers loaded from the worklist. `None`/absent = UNDECIDED (attribute
    values are typed and never null, so null cannot be a legal answer). Resolution
    order: per-object decision overrides the group-level decision (MIG-5)."""

    group: dict[str, Any] = field(default_factory=dict)
    per_object: dict[tuple[str, str], Any] = field(default_factory=dict)

    def resolve(self, step_id: str, entry_id: str) -> Any:
        value = self.per_object.get((step_id, entry_id))
        if value is not None:
            return value
        return self.group.get(step_id)


@dataclass
class FoldOutcome:
    """One object's fold result: the folded attributes, the pending (undecided)
    ambiguous steps, and any decision-application errors."""

    attributes: dict[str, Any]
    pending: list[MigrationStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)  # step ids actually applied

    @property
    def resolved(self) -> bool:
        """Object-atomic gate (MIG-5): the object re-stamps only when EVERY step
        resolved — no pending decisions, no decision errors."""
        return not self.pending and not self.errors


def _apply_deterministic(step: MigrationStep, attrs: dict[str, Any], label: str) -> bool:
    """Apply one deterministic step in place. Returns True if it changed anything."""
    if step.action == "map":
        assert step.attribute is not None and step.value_map is not None
        if step.attribute not in attrs:
            return False
        value = attrs[step.attribute]
        try:
            hit = value in step.value_map
        except TypeError:  # unhashable (list/map values) — maps remap scalar values
            hit = False
        if not hit:
            raise TotalityError(
                f"migration-map-not-total: {label}: {step.describe()} does not map the "
                f"encountered value {value!r} — a deterministic step ships a TOTAL typed "
                "forward map (MIG-4/SV6; schema-lint validates totality per release, §27.4)"
            )
        attrs[step.attribute] = copy.deepcopy(step.value_map[value])
        return True
    if step.action == "rename":
        assert step.attribute is not None and step.rename_to is not None
        if step.attribute not in attrs:
            return False
        if step.rename_to in attrs:
            raise MigrationError(
                f"migration-error: {label}: {step.describe()} would overwrite existing "
                f"attribute {step.rename_to!r} — a rename is lossless (MIG-3); refused"
            )
        attrs[step.rename_to] = attrs.pop(step.attribute)
        return True
    if step.action == "drop":
        assert step.attribute is not None
        if step.attribute in attrs:
            del attrs[step.attribute]
            return True
        return False
    if step.action == "edit":
        for name in step.edit_drop:
            attrs.pop(name, None)
        for name, value in (step.edit_set or {}).items():
            attrs[name] = copy.deepcopy(value)
        return True
    raise MigrationError(f"migration-error: {label}: unknown action {step.action!r}")


def _apply_decision(
    schema: Schema, step: MigrationStep, attrs: dict[str, Any], decision: Any, label: str
) -> None:
    """Apply a human decision (MIG-5). Early-validated where the target attribute is
    declared; the post-fold closed-schema validation is the final gate either way."""
    if step.scope == _SCOPE_OBJECT:
        if not isinstance(decision, Mapping):
            raise DecisionError(
                f"invalid-migration-decision: {label}: the decision for object-scope "
                f"{step.describe()} must be an attribute->value mapping, got "
                f"{type(decision).__name__}"
            )
        for name in decision:
            if not isinstance(name, str) or name in RESERVED_ATTRIBUTE_NAMES:
                raise DecisionError(
                    f"invalid-migration-decision: {label}: decision key {name!r} is not a "
                    "settable attribute (envelope/bag names are never migration targets, "
                    "MIG-7)"
                )
        attrs.update(copy.deepcopy(dict(decision)))
        return
    assert step.attribute is not None
    spec = schema.attributes.get(step.attribute)
    if spec is not None:
        try:
            validate_value(spec.type, decision, path=f"{label}.{step.attribute} (decision)")
        except ValueError as exc:
            raise DecisionError(
                f"invalid-migration-decision: {label}: the decision {decision!r} for "
                f"{step.describe()} is not a valid current-schema value: {exc}"
            ) from exc
    attrs[step.attribute] = copy.deepcopy(decision)


def fold_entry(
    schema: Schema,
    entry: Entry,
    steps: list[MigrationStep],
    decisions: DecisionSet,
) -> FoldOutcome:
    """The ONE fold (MIG-1): apply every selected step, in registry order, onto a copy
    of the entry's attributes.

    Deterministic steps auto-apply (MIG-4). Ambiguous steps consume their worklist
    decision; an undecided step goes to `pending` and the fold CONTINUES so a skip-span
    run surfaces the UNION of pending decisions in one pass (MIG-5). While decisions are
    pending, a downstream totality miss is suppressed (it may depend on the undecided
    value); with nothing pending, a totality miss is a loud refusal. The caller writes
    NOTHING unless `outcome.resolved` (object-atomic re-stamp)."""
    label = f"{schema.collection}/{entry.id}"
    attrs = copy.deepcopy(dict(entry.attributes))
    outcome = FoldOutcome(attributes=attrs)
    for step in steps:
        if step.action == AMBIGUOUS_ACTION:
            if not (step.scope == _SCOPE_OBJECT or step.attribute in attrs):
                continue  # does not affect this object
            decision = decisions.resolve(step.id, entry.id)
            if decision is None:
                outcome.pending.append(step)
                continue
            try:
                _apply_decision(schema, step, attrs, decision, label)
                outcome.applied.append(step.id)
            except DecisionError as exc:
                outcome.pending.append(step)
                outcome.errors.append(str(exc))
        else:
            try:
                if _apply_deterministic(step, attrs, label):
                    outcome.applied.append(step.id)
            except TotalityError:
                if outcome.pending:
                    continue  # downstream of an undecided value; the real gate re-runs
                raise
    return outcome


# ---------------------------------------------------------------------------------------
# Worklist file I/O (MIG-5: reviewable up front, resumable, diffable)
# ---------------------------------------------------------------------------------------

_WORKLIST_HEADER = """\
# decisions-needed migration worklist (MIG-5, docs/design.md §11.6) — GENERATED by
# scripts/migrate.sh; regenerated on every run while decisions are pending.
# EDIT ONLY the `decision:` slots, then re-run scripts/migrate.sh:
#   - a group-level `decision:` fans across every object listed under the group;
#   - a per-object `decision:` overrides its group;
#   - `suggested:` is the authored suggestion — it is NEVER auto-applied (§11.5).
# Objects re-stamp only when ALL their steps resolve (object-atomic, MIG-5).
"""


def load_worklist_decisions(path: str | Path) -> DecisionSet:
    """Read the human decisions out of an existing worklist (missing file = none)."""
    path = Path(path)
    if not path.exists():
        return DecisionSet()
    text = path.read_text(encoding="utf-8")
    _refuse_directives(text, where=str(path))
    data = load_yaml(text)
    if not isinstance(data, Mapping) or "groups" not in data:
        raise WorklistError(
            f"invalid-migration-worklist: {path}: expected a mapping with `groups:`"
        )
    decisions = DecisionSet()
    groups = data["groups"] or []
    if not isinstance(groups, list):
        raise WorklistError(f"invalid-migration-worklist: {path}: `groups` must be a list")
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("step"), str):
            raise WorklistError(
                f"invalid-migration-worklist: {path}: each group is a mapping with a `step:` id"
            )
        step_id = group["step"]
        if group.get("decision") is not None:
            decisions.group[step_id] = group["decision"]
        for obj in group.get("objects") or []:
            if not isinstance(obj, Mapping) or not isinstance(obj.get("id"), str):
                raise WorklistError(
                    f"invalid-migration-worklist: {path}: each object is a mapping with an `id:`"
                )
            if obj.get("decision") is not None:
                decisions.per_object[(step_id, obj["id"])] = obj["decision"]
    return decisions


def _dump_yaml(data: Any) -> str:
    """Serialize with the pinned G4 library (same `YAML(typ='safe', pure=True)` the
    loader pins), insertion order preserved, block style, no line wrapping."""
    y = make_loader()
    y.default_flow_style = False
    y.width = 4096
    y.representer.sort_base_mapping_type_on_output = False
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _write_worklist(
    path: Path,
    pending: dict[str, tuple[MigrationStep, list[tuple[Entry, Any]]]],
    decisions: DecisionSet,
    *,
    registry_source: str,
    now: date,
) -> None:
    """Write the regenerated worklist, carrying forward decisions already entered for
    still-pending items (resumable + diffable, MIG-5)."""
    groups: list[dict[str, Any]] = []
    for step_id in sorted(pending):
        step, objects = pending[step_id]
        row: dict[str, Any] = {
            "step": step.id,
            "version": step.version,
            "collection": step.collection,
        }
        if step.scope == _SCOPE_OBJECT:
            row["scope"] = _SCOPE_OBJECT
        else:
            row["attribute"] = step.attribute
        row["prompt"] = step.prompt
        if step.suggested is not None:
            row["suggested"] = step.suggested
        row["decision"] = decisions.group.get(step.id)
        row["objects"] = [
            {
                "id": entry.id,
                ("current_attributes" if step.scope == _SCOPE_OBJECT else "current_value"): current,
                "decision": decisions.per_object.get((step.id, entry.id)),
            }
            for entry, current in objects
        ]
        groups.append(row)
    document = {
        "format": WORKLIST_FORMAT,
        "generated": {"now": now, "registry": registry_source},
        "groups": groups,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _replace_file(path, _WORKLIST_HEADER + _dump_yaml(document))


# ---------------------------------------------------------------------------------------
# The runner (scripts/migrate.sh): config-only, object-atomic, resumable
# ---------------------------------------------------------------------------------------

STATUS_UP_TO_DATE = "up-to-date"
STATUS_MIGRATED = "migrated"
STATUS_NEEDS_INPUT = "needs-input"
STATUS_BLOCKED = "blocked"
STATUS_SKIPPED_FRAMEWORK = "skipped-framework"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class ObjectOutcome:
    """One config object's migration result (the per-item result row; a blocked item
    never fails the batch — SM1 posture)."""

    collection: str
    entry_id: str
    path: str
    status: str
    detail: str = ""
    #: §21.7 code where one is pinned (`out-of-window` / `ambiguous-migration-decisions`).
    code: str | None = None
    old_stamp: int | None = None
    new_stamp: int | None = None


@dataclass
class RunResult:
    """One `scripts/migrate.sh` run over a config tree."""

    root: str
    now: date
    outcomes: list[ObjectOutcome] = field(default_factory=list)
    worklist_path: str | None = None  # set when a worklist was (re)written
    worklist_removed: bool = False

    def _count(self, status: str) -> int:
        return sum(1 for o in self.outcomes if o.status == status)

    @property
    def migrated(self) -> int:
        return self._count(STATUS_MIGRATED)

    @property
    def blocked(self) -> int:
        return self._count(STATUS_BLOCKED)

    @property
    def pending(self) -> int:
        return self._count(STATUS_NEEDS_INPUT)

    @property
    def errors(self) -> int:
        return self._count(STATUS_ERROR)

    def exit_code(self) -> int:
        """0 clean · 1 blocked/error · 3 decisions needed (2 is usage, at the CLI)."""
        if self.blocked or self.errors:
            return 1
        if self.pending:
            return 3
        return 0


def _replace_file(path: Path, text: str) -> None:
    """Same-directory temp + atomic rename (the full G1 no-replace/fsync module is plan
    step 20; config rewrite needs only not-torn, which os.replace gives). The temp name
    is per-process: a concurrent double-run (an operator error — real locking is the
    step-20 G1 module) then converges benignly on the identical deterministic fold
    instead of one racer unlinking the other's temp mid-replace."""
    tmp = path.with_name(f"{path.name}.migrate-tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _render_entry_text(entry: Entry, new_attrs: dict[str, Any], new_stamp: int) -> str:
    """Re-emit the entry: envelope first, payload in original order, BODY VERBATIM
    (migration rewrites CONFIG only — prose is untouched; frontmatter comments do not
    survive a rewrite, which is the cost of a config migration, not content loss)."""
    frontmatter: dict[str, Any] = {
        "id": entry.id,
        "provenance": entry.provenance,
        "schema_version": new_stamp,
    }
    frontmatter.update(new_attrs)
    return "---\n" + _dump_yaml(frontmatter) + "---\n" + entry.body


def run_migration(
    root: str | Path,
    *,
    registry: StepRegistry,
    now: date,
    worklist_path: str | Path,
) -> RunResult:
    """One user-triggered migration pass over every config collection under `root`.

    MIG-7 scope, enforced structurally three ways: only directories with a co-located
    `_schema.yaml` are visited (artifact/output stores have none and are pruned by name
    too — `drift.iter_collections`); framework-provenance entries are never rewritten
    (lockstep-maintained upstream); and no step can target the envelope or the `metadata`
    bag (registry validation). Artifacts are IMMUTABLE: migrate config, then REGENERATE.

    Idempotent: a second run over a migrated tree folds empty intervals — no-ops.
    Resumable: decisions are read from `worklist_path`; unresolved objects are left
    untouched and the worklist is regenerated with the remaining union (MIG-5)."""
    root = Path(root)
    worklist_path = Path(worklist_path)
    decisions = load_worklist_decisions(worklist_path)
    result = RunResult(root=str(root), now=now)
    pending_map: dict[str, tuple[MigrationStep, list[tuple[Entry, Any]]]] = {}

    for coll_dir in iter_collections(root):
        schema_path = coll_dir / SCHEMA_FILENAME
        try:
            schema = load_schema(schema_path)
        except ValueError as exc:
            result.outcomes.append(
                ObjectOutcome(
                    collection=coll_dir.name,
                    entry_id=SCHEMA_FILENAME,
                    path=str(schema_path),
                    status=STATUS_ERROR,
                    detail=f"unloadable schema: {exc}",
                )
            )
            continue
        for entry_path in iter_entry_files(coll_dir):
            result.outcomes.append(
                _migrate_one(schema, entry_path, registry, decisions, pending_map, now=now)
            )

    if pending_map:
        _write_worklist(
            worklist_path, pending_map, decisions, registry_source=registry.source, now=now
        )
        result.worklist_path = str(worklist_path)
    elif worklist_path.exists():
        os.remove(worklist_path)  # every decision consumed; the worklist is derived state
        result.worklist_removed = True
    return result


def _migrate_one(
    schema: Schema,
    entry_path: Path,
    registry: StepRegistry,
    decisions: DecisionSet,
    pending_map: dict[str, tuple[MigrationStep, list[tuple[Entry, Any]]]],
    *,
    now: date,
) -> ObjectOutcome:
    collection = schema.collection

    def outcome(
        status: str,
        entry_id: str,
        detail: str = "",
        code: str | None = None,
        old_stamp: int | None = None,
        new_stamp: int | None = None,
    ) -> ObjectOutcome:
        return ObjectOutcome(
            collection=collection,
            entry_id=entry_id,
            path=str(entry_path),
            status=status,
            detail=detail,
            code=code,
            old_stamp=old_stamp,
            new_stamp=new_stamp,
        )

    try:
        entry = load_entry_lenient(entry_path, schema)
    except ValueError as exc:
        return outcome(STATUS_ERROR, entry_path.stem, f"unloadable entry: {exc}")

    stamp, current = entry.schema_version, schema.schema_version
    if entry.provenance != PROVENANCE_INSTANCE:
        if stamp == current:
            return outcome(STATUS_UP_TO_DATE, entry.id, old_stamp=stamp)
        return outcome(
            STATUS_SKIPPED_FRAMEWORK,
            entry.id,
            detail=(
                f"framework default stamped v{stamp} != current v{current}: framework "
                "entries are lockstep-maintained UPSTREAM and never instance-migrated "
                "(MIG-7); a stale framework stamp is an upstream SV11 clause-3 defect — "
                "report it, do not hand-fix"
            ),
            old_stamp=stamp,
        )
    if stamp > current:
        return outcome(
            STATUS_ERROR,
            entry.id,
            detail=(
                f"entry stamp v{stamp} is AHEAD of the current schema v{current} — a "
                "mixed checkout or hand-edited stamp; migration is forward-only (MIG-1) "
                "and never downgrades"
            ),
            old_stamp=stamp,
        )
    if stamp == current:
        return outcome(STATUS_UP_TO_DATE, entry.id, old_stamp=stamp)

    window_detail = registry.out_of_window(schema, entry, now=now)
    if window_detail is not None:
        return outcome(
            STATUS_BLOCKED,
            entry.id,
            detail=window_detail,
            code=CODE_OUT_OF_WINDOW,
            old_stamp=stamp,
        )

    steps = registry.steps_for(collection, after=stamp, up_to=current)
    try:
        fold = fold_entry(schema, entry, steps, decisions)
    except MigrationError as exc:
        return outcome(STATUS_ERROR, entry.id, detail=str(exc), old_stamp=stamp)

    if not fold.resolved:
        for step in fold.pending:
            if step.scope == _SCOPE_OBJECT:
                current_value: Any = dict(entry.attributes)
            else:
                current_value = entry.attributes.get(step.attribute)
            pending_map.setdefault(step.id, (step, []))[1].append((entry, current_value))
        detail = (
            f"{len(fold.pending)} decision(s) needed: "
            + ", ".join(s.id for s in fold.pending)
            + " — edit the worklist and re-run scripts/migrate.sh (MIG-5)"
        )
        if fold.errors:
            detail += " | decision errors: " + " | ".join(fold.errors)
        return outcome(
            STATUS_NEEDS_INPUT,
            entry.id,
            detail=detail,
            code=CODE_AMBIGUOUS_MIGRATION_DECISIONS,
            old_stamp=stamp,
        )

    try:
        schema.validate_attribute_values(fold.attributes, where=f"{collection}/{entry.id}")
    except ValueError as exc:
        return outcome(
            STATUS_ERROR,
            entry.id,
            detail=(
                f"post-fold validation failed — NOT rewritten (the fold output must be "
                f"valid under the current schema): {exc}"
            ),
            old_stamp=stamp,
        )
    _replace_file(entry_path, _render_entry_text(entry, fold.attributes, current))
    applied = ", ".join(fold.applied) if fold.applied else "none (re-stamp only)"
    return outcome(
        STATUS_MIGRATED,
        entry.id,
        detail=f"folded ({stamp}, {current}]; steps applied: {applied}",
        old_stamp=stamp,
        new_stamp=current,
    )


# ---------------------------------------------------------------------------------------
# CLI (`scripts/migrate.sh` → `python -m pipeline.migration`)
# ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """The owner-triggered migration verb (§11.6): user-triggered, mandatory before use,
    idempotent, NOT on the external-actor API (§21.9)."""
    parser = argparse.ArgumentParser(
        prog="migrate.sh",
        description=(
            "Migrate instance-owned, schema-stamped config to the current schema "
            "(docs/design.md §11.6, MIG-1…MIG-7). One fold over (entry-stamp, current]; "
            "ambiguous changes halt into a decisions-needed worklist. Exit codes: "
            "0 clean · 1 blocked/error · 2 usage · 3 decisions needed."
        ),
    )
    parser.add_argument("--root", default=".", help="config tree root (default: cwd)")
    parser.add_argument(
        "--registry",
        default=None,
        help=f"migration step registry (default: <root>/{MIGRATION_REGISTRY_RELPATH}; "
        "missing = empty registry)",
    )
    parser.add_argument(
        "--worklist",
        default=None,
        help=f"decisions-needed worklist path (default: <root>/{WORKLIST_RELPATH})",
    )
    parser.add_argument(
        "--now",
        default=None,
        metavar="YYYY-MM-DD",
        help="override the migration clock (ops/testing; default: today). The clock is "
        "injected here at the edge — nothing inside the library reads ambient time.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    registry_path = Path(args.registry) if args.registry else root / MIGRATION_REGISTRY_RELPATH
    worklist_path = Path(args.worklist) if args.worklist else root / WORKLIST_RELPATH
    try:
        now = date.fromisoformat(args.now) if args.now else date.today()  # the clock edge
    except ValueError:
        print(f"migrate.sh: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2
    try:
        registry = load_step_registry(registry_path)
    except RegistryError as exc:
        print(f"migrate.sh: {exc}", file=sys.stderr)
        return 2

    result = run_migration(root, registry=registry, now=now, worklist_path=worklist_path)
    for o in result.outcomes:
        code = f" [{o.code}]" if o.code else ""
        stamp = ""
        if o.old_stamp is not None:
            stamp = f" v{o.old_stamp}" + (f"->v{o.new_stamp}" if o.new_stamp else "")
        line = f"{o.status:18s}{code} {o.collection}/{o.entry_id}{stamp}"
        if o.detail:
            line += f": {o.detail}"
        print(line)
    print(
        f"migrate: {result.migrated} migrated · {result.pending} need decisions · "
        f"{result.blocked} blocked · {result.errors} errors "
        f"(root {result.root}, as of {result.now})"
    )
    if result.worklist_path:
        print(
            f"decisions-needed worklist written: {result.worklist_path} — edit the "
            "`decision:` slots and re-run (MIG-5; resolve-time use stays blocked until "
            "migrated, §11.5)"
        )
    if result.worklist_removed:
        print("worklist fully consumed and removed")
    return result.exit_code()


if __name__ == "__main__":  # `python -m pipeline.migration` (via scripts/migrate.sh)
    raise SystemExit(main())
