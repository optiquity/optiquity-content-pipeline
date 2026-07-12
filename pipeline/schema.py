"""The §11 schema system: co-located `_schema.yaml` manifests + closed-schema validation.

Design authority: `docs/design.md`
  §11.1 — a schema is a typed field manifest: per attribute `type` · `default` · prose
          `definition` · `definition_version`; a `set`-typed attribute may declare a
          schema-level default combine operator (§12.4); schema defaults are the L0 cascade
          floor (§12.2);
  §11.2 — version stamps are BARE global integers: `definition_version` per attribute is
          valued in the ONE global `schema_version` number-space (SV1/SV2);
  §11.3 — schemas are CLOSED (SV3): undeclared attributes are rejected, instances never add
          interpreted fields; the artifact-level opaque `metadata` bag (`MetadataBag` here)
          is stored and passed through, NEVER interpreted and NEVER identity (§7.3);
  §13.4 — encoding: standalone co-located `<collection>/_schema.yaml`.

Carry-forward (step-8 review RV-3, binding on this step): this loader applies the SAME
`%`-directive refusal as the frontmatter splitter (`pipeline/yamlio.py` S-E8) — a bare
`load_yaml` would HONOR an in-document `%YAML 1.1` directive and re-open the Norway problem
the G4 pin exists to kill. A schema file containing any `%`-directive line is refused loudly
(`SchemaDirectiveError`), never honored. The YAML load itself is `yamlio.load_yaml` — the
pinned loader; no second loader is hand-rolled here.

Wiring, never duplication: the §11.1 type system is `pipeline/attrtypes.py`
(`parse_type_spec` / `validate_value` / `validate_combine_operator`); the attribute-NAME
alphabet is the §13.2 path-segment identifier (`pipeline/opgrammar.validate_path` — the
RV-4 adjudication of record: operator paths name schema attributes, medial `_`/`-` allowed);
the slug alphabet is attrtypes' `ref` validator (same single implementation `pipeline/ids.py`
uses).

Drift-comparison inputs for step 12 (`definition_version > entry.schema_version` AND the
entry sets the attribute — §11.5) are EXPOSED here (`Schema.schema_version`,
`Schema.definition_versions()`) and on the entry loader (`pipeline/entries.py`); the drift
math itself is step 12's scope.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.attrtypes import (
    AttrTypeSpec,
    parse_type_spec,
    validate_combine_operator,
    validate_value,
)
from pipeline.opgrammar import PathSyntaxError, validate_path
from pipeline.yamlio import load_yaml

__all__ = [
    "AttributeSpec",
    "MetadataBag",
    "MetadataBagError",
    "RESERVED_ATTRIBUTE_NAMES",
    "SCHEMA_FILENAME",
    "Schema",
    "SchemaDirectiveError",
    "SchemaError",
    "SchemaValidationError",
    "UndeclaredAttributeError",
    "VersionStampError",
    "load_schema",
    "load_schema_text",
    "require_bare_int",
]

#: §13.4 (SV4): the standalone co-located schema file, one per collection directory.
SCHEMA_FILENAME = "_schema.yaml"

#: Names a schema may NEVER declare as attributes — they belong to other layers:
#: `id`/`provenance`/`schema_version` are the entry ENVELOPE (§11.1 B4, §10 Q15, §11.2);
#: `extends` is Mechanism-1 partial syntax (§12.1); `metadata` is the artifact-level opaque
#: bag (§11.3 — never a schema attribute, never interpreted); `aliases` is the registered
#: deferred rename rider (§26). Declaring one would collide envelope with payload.
RESERVED_ATTRIBUTE_NAMES = frozenset(
    {"id", "provenance", "schema_version", "extends", "metadata", "aliases"}
)

#: The closed per-attribute manifest vocabulary (§11.1 + the §12.4 set default operator).
_MANIFEST_KEYS = frozenset({"type", "default", "definition", "definition_version", "combine"})
#: §11.1: "per attribute it declares `type` · `default` · prose `definition` ·
#: `definition_version`" — all four are REQUIRED; `combine` alone is optional (set-only).
_REQUIRED_MANIFEST_KEYS = ("type", "default", "definition", "definition_version")

#: The closed top-level vocabulary of a `_schema.yaml` file.
_TOP_LEVEL_KEYS = frozenset({"schema_version", "attributes"})

#: Slug validation = the §7.4 alphabet's single implementation (attrtypes' `ref` type),
#: exactly as `pipeline/ids.py` consumes it.
_REF_SPEC = AttrTypeSpec(kind="ref")


class SchemaError(ValueError):
    """A malformed `_schema.yaml` manifest — refused, never repaired."""

    code = "invalid-schema"


class SchemaDirectiveError(SchemaError):
    """RV-3: a `%`-directive line in a schema file — refused loudly, never honored (S-E8)."""

    code = "schema-directive-refused"


class VersionStampError(ValueError):
    """A version stamp that is not a bare int in the global number-space (§11.2/§13.4)."""

    code = "invalid-version-stamp"


class SchemaValidationError(ValueError):
    """A value payload refused by closed-schema validation (shape-level, SV3)."""

    code = "schema-validation-refused"


class UndeclaredAttributeError(SchemaValidationError):
    """SV3 (§11.3): schemas are closed — an undeclared attribute is rejected outright."""

    code = "undeclared-attribute"


class MetadataBagError(ValueError):
    """A malformed §11.3 metadata bag (must be a mapping with string keys)."""

    code = "invalid-metadata-bag"


def require_bare_int(value: Any, what: str, *, minimum: int = 1) -> int:
    """§11.2/§13.4: stamps are BARE global integers — bool/str/float forms are refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise VersionStampError(
            f"invalid-version-stamp: {what} must be a bare integer (§11.2/§13.4), "
            f"got {type(value).__name__}: {value!r}"
        )
    if value < minimum:
        raise VersionStampError(f"invalid-version-stamp: {what} must be >= {minimum}, got {value}")
    return value


def _slug_ok(value: object) -> bool:
    """True iff `value` is a §7.4 slug — via the single ref-validator implementation."""
    try:
        validate_value(_REF_SPEC, value)
    except ValueError:
        return False
    return True


def _refuse_directives(text: str, *, where: str) -> None:
    """The RV-3 carry-forward: the SAME `%`-directive refusal as the splitter (S-E8).

    Scans every line of the standalone document, exactly as `yamlio.load_frontmatter`
    scans the frontmatter block: any line starting with `%` at column 0 is refused —
    an in-document `%YAML 1.1` would otherwise be HONORED by the load and re-enable the
    Norway problem (verified hazard D3). Same documented false-positive class as S-E8
    (a column-0 `%` continuation line inside a multi-line flow scalar): refusal is loud,
    never silent corruption.
    """
    for line in text.splitlines():
        if line.startswith("%"):
            raise SchemaDirectiveError(
                f"schema-directive-refused: a %-directive line in {where} (RV-3/S-E8; "
                f"refused line: {line!r})"
            )


def _require_attribute_name(name: object, *, where: str) -> str:
    """Attribute names live in the §13.2 path-segment alphabet (RV-4 adjudication).

    One-segment only (no dots — a dotted name would collide with §13.2 path syntax);
    the segment rule itself is `opgrammar.validate_path`, never re-implemented here.
    """
    if not isinstance(name, str) or not name:
        raise SchemaError(
            f"invalid-schema: {where}: attribute names must be non-empty strings, got {name!r}"
        )
    if "." in name:
        raise SchemaError(
            f"invalid-schema: {where}: attribute name {name!r} contains '.' — names are "
            "single path segments (§13.2)"
        )
    try:
        validate_path(name)
    except PathSyntaxError as exc:
        raise SchemaError(
            f"invalid-schema: {where}: attribute name {name!r} is not a §13.2 identifier "
            "(lowercase [a-z0-9] with medial [-_], 1-40 chars)"
        ) from exc
    if name in RESERVED_ATTRIBUTE_NAMES:
        raise SchemaError(
            f"invalid-schema: {where}: attribute name {name!r} is reserved "
            f"(envelope/bag/M1 vocabulary: {sorted(RESERVED_ATTRIBUTE_NAMES)})"
        )
    return name


@dataclass(frozen=True)
class AttributeSpec:
    """One §11.1 manifest row: type · default · definition · definition_version (+combine)."""

    name: str
    type: AttrTypeSpec
    default: Any
    definition: str
    definition_version: int
    #: §12.4: the per-`set`-attribute schema default operator; `replace` everywhere else.
    combine: str = "replace"


@dataclass(frozen=True)
class Schema:
    """One collection's loaded, validated schema (SV4 co-located manifest)."""

    collection: str
    #: §11.2 (SV2): the ONE global schema version this manifest was released under.
    schema_version: int
    attributes: dict[str, AttributeSpec] = field(default_factory=dict)

    def defaults(self) -> dict[str, Any]:
        """The L0 cascade floor (§12.2): attribute → schema default. Deep-copied per call
        so no caller can mutate the floor; feeds `ids.delta_vs_floor` (§7.2) unchanged."""
        return {name: copy.deepcopy(spec.default) for name, spec in self.attributes.items()}

    def definition_versions(self) -> dict[str, int]:
        """Step-12 drift input (§11.5): attribute → `definition_version` (bare ints, SV1)."""
        return {name: spec.definition_version for name, spec in self.attributes.items()}

    def validate_attribute_values(self, values: Any, *, where: str = "") -> None:
        """Closed-schema validation (SV3): reject undeclared attributes, type-check the rest.

        MISSING attributes are never an error — they ride the schema-default floor
        (§11.1/§12.2). Returns None or raises; values are never transformed.
        """
        label = where or self.collection
        if not isinstance(values, Mapping):
            raise SchemaValidationError(
                f"schema-validation-refused: {label}: attribute values must be a mapping, "
                f"got {type(values).__name__}"
            )
        for name, value in values.items():
            if not isinstance(name, str):
                raise SchemaValidationError(
                    f"schema-validation-refused: {label}: attribute names must be strings, "
                    f"got {name!r}"
                )
            spec = self.attributes.get(name)
            if spec is None:
                raise UndeclaredAttributeError(
                    f"undeclared-attribute: {label}: {name!r} is not declared by the "
                    f"{self.collection!r} schema — schemas are closed (SV3, §11.3); "
                    f"declared: {sorted(self.attributes)}"
                )
            validate_value(spec.type, value, path=f"{label}.{name}")


def _parse_attribute(name: str, manifest: Any, *, schema_version: int, where: str) -> AttributeSpec:
    if not isinstance(manifest, Mapping):
        raise SchemaError(
            f"invalid-schema: {where}: attribute {name!r} must map to a manifest mapping, "
            f"got {type(manifest).__name__}"
        )
    unknown = {k for k in manifest if not isinstance(k, str)} | (set(manifest) - _MANIFEST_KEYS)
    if unknown:
        raise SchemaError(
            f"invalid-schema: {where}.{name}: unknown manifest key(s) "
            f"{sorted(repr(k) for k in unknown)} — the manifest vocabulary is closed "
            f"({sorted(_MANIFEST_KEYS)})"
        )
    missing = [k for k in _REQUIRED_MANIFEST_KEYS if k not in manifest]
    if missing:
        raise SchemaError(
            f"invalid-schema: {where}.{name}: missing required manifest field(s) {missing} "
            "(§11.1: every attribute declares type, default, definition, definition_version)"
        )

    spec = parse_type_spec(manifest["type"])  # SchemaTypeError propagates, already typed

    definition = manifest["definition"]
    if not isinstance(definition, str) or not definition.strip():
        raise SchemaError(
            f"invalid-schema: {where}.{name}: `definition` must be non-empty prose (§11.1), "
            f"got {definition!r}"
        )

    definition_version = require_bare_int(
        manifest["definition_version"], f"{where}.{name}.definition_version"
    )
    if definition_version > schema_version:
        raise SchemaError(
            f"invalid-schema: {where}.{name}: definition_version {definition_version} exceeds "
            f"the file's schema_version {schema_version} — definition_version is valued in "
            "the global schema_version number-space (SV1, §11.2)"
        )

    combine = "replace"
    if "combine" in manifest:
        declared = manifest["combine"]
        if not isinstance(declared, str):
            raise SchemaError(
                f"invalid-schema: {where}.{name}: `combine` must be an operator string, "
                f"got {type(declared).__name__}"
            )
        # attrtypes owns the operator rules: union-on-list / set-subtract / unknown
        # operators raise CombineOperatorError there (§11.1/§12.4) — checked FIRST so the
        # load-bearing list/set split surfaces its own error class.
        validate_combine_operator(spec, declared)
        if spec.kind != "set":
            raise SchemaError(
                f"invalid-schema: {where}.{name}: a schema default combine operator is "
                f"declarable only on a `set` attribute (§12.4), not {spec.kind!r}"
            )
        combine = declared

    default = manifest["default"]
    # The default is a VALUE of the declared type (L0 floor, §12.2) — validated, never
    # coerced; ValueValidationError propagates typed.
    validate_value(spec, default, path=f"{where}.{name} (default)")

    return AttributeSpec(
        name=name,
        type=spec,
        default=default,
        definition=definition,
        definition_version=definition_version,
        combine=combine,
    )


def load_schema_text(text: str, *, collection: str) -> Schema:
    """Load one `_schema.yaml` document from `text` for `collection`.

    Applies (in order): the RV-3 `%`-directive refusal; the pinned YAML 1.2 typed
    safe-load (`yamlio.load_yaml` — YAML syntax errors propagate as `YAMLLoadError`);
    top-level shape checks; per-attribute manifest validation wiring `attrtypes`.
    """
    if not _slug_ok(collection):
        raise SchemaError(
            f"invalid-schema: collection name {collection!r} is not a §7.4 slug "
            "(collections are registry directory names)"
        )
    where = f"{collection}/{SCHEMA_FILENAME}"
    # S-E8 parity: the frontmatter splitter's fence regex consumes one optional leading
    # U+FEFF BEFORE the scanned block (yamlio S-E1/S-E12); a standalone document must do
    # the same before the directive scan — ruamel strips a leading BOM and would then
    # HONOR a %-directive the raw-text scan missed (verified: BOM + `%YAML 1.1` silently
    # re-enables YAML 1.1 coercions, e.g. `1:30` -> 90 on a number attribute).
    text = text.removeprefix("\ufeff")
    _refuse_directives(text, where=where)
    data = load_yaml(text)
    if not isinstance(data, Mapping):
        raise SchemaError(
            f"invalid-schema: {where}: a schema file is a YAML mapping, got "
            f"{'empty document' if data is None else type(data).__name__}"
        )
    unknown = {k for k in data if not isinstance(k, str)} | (set(data) - _TOP_LEVEL_KEYS)
    if unknown:
        raise SchemaError(
            f"invalid-schema: {where}: unknown top-level key(s) "
            f"{sorted(repr(k) for k in unknown)} — the schema file vocabulary is closed "
            f"({sorted(_TOP_LEVEL_KEYS)})"
        )
    if "schema_version" not in data:
        raise VersionStampError(
            f"invalid-version-stamp: {where}: missing `schema_version` (§11.2 SV2 — the one "
            "global released version this manifest snapshot belongs to)"
        )
    schema_version = require_bare_int(data["schema_version"], f"{where}.schema_version")
    if "attributes" not in data or not isinstance(data["attributes"], Mapping):
        raise SchemaError(
            f"invalid-schema: {where}: `attributes` must be a mapping (declare an empty "
            "manifest explicitly as `attributes: {}` — thin objects get thin schemas, §11.7)"
        )
    attributes: dict[str, AttributeSpec] = {}
    for raw_name, manifest in data["attributes"].items():
        name = _require_attribute_name(raw_name, where=where)
        attributes[name] = _parse_attribute(
            name, manifest, schema_version=schema_version, where=where
        )
    return Schema(collection=collection, schema_version=schema_version, attributes=attributes)


def load_schema(path: str | Path) -> Schema:
    """Load a co-located schema file: `<collection>/_schema.yaml` (SV4, §13.4).

    The filename must be exactly `_schema.yaml`; the collection is the parent directory's
    basename. Reads strict UTF-8 (decode errors propagate loudly).
    """
    path = Path(path)
    if path.name != SCHEMA_FILENAME:
        raise SchemaError(
            f"invalid-schema: {path.name!r} is not the co-located schema filename "
            f"{SCHEMA_FILENAME!r} (SV4, §13.4)"
        )
    return load_schema_text(path.read_text(encoding="utf-8"), collection=path.parent.name)


class MetadataBag:
    """The §11.3 artifact-level opaque `metadata` bag: stored + passed through, NEVER
    interpreted.

    Contract (§11.3, §7.3): an instance-authored mapping the framework carries to the
    external hand-off untouched. Structural guarantees here:

    - **Opaque pass-through:** values are deep-copied in and deep-copied out
      (`as_dict()`), equal in content, never inspected beyond the mapping shape and
      string keys — the framework has no mechanism to APPLY custom fields (§11.3).
    - **Never identity:** `pipeline/ids.py` refuses the `metadata` key in every preimage
      (§7.3 IDENTITY_EXCLUSIONS), and the wrapper itself is not canonicalizable
      (`pipeline/canonical.py` refuses arbitrary objects) — a bag cannot slip into a
      digest even by accident.
    - **Content-free repr:** the repr never surfaces values (instance data must not leak
      into logs/machine records, §22 discipline; secrets must never ride the bag, §3.3).
    - **Never migrated** (§11.6 MIG-7) and never routed into AST content (§15) — those
      stages simply carry the object.
    """

    __slots__ = ("_data",)

    def __init__(self, mapping: Any) -> None:
        if not isinstance(mapping, Mapping):
            raise MetadataBagError(
                f"invalid-metadata-bag: the §11.3 metadata bag is a mapping, got "
                f"{type(mapping).__name__}"
            )
        for key in mapping:
            if not isinstance(key, str):
                raise MetadataBagError(
                    f"invalid-metadata-bag: bag keys must be strings, got {key!r}"
                )
        self._data: dict[str, Any] = copy.deepcopy(dict(mapping))

    def as_dict(self) -> dict[str, Any]:
        """The pass-through view: a deep copy — callers can never mutate the stored bag."""
        return copy.deepcopy(self._data)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, MetadataBag):
            return NotImplemented
        return self._data == other._data

    # Defining __eq__ suppresses __hash__ → bags are unhashable; they can never be used
    # as keys or set members, which keeps them out of anything order- or identity-bearing.

    def __repr__(self) -> str:  # content-free by design (§22; §3.3)
        return f"MetadataBag(<{len(self._data)} keys>)"
