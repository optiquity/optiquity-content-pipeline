"""The §11.1 attribute-type system: typed value validation that REFUSES coercions.

Design authority: `docs/design.md` §11.1 (the attribute type system; the load-bearing
ordered-`list` vs unordered-`set` split; union-on-list = schema ERROR), §12.4 (combine
operators: `replace`/`union` only; `union` valid only on unordered leaf-element sets;
set-subtract `-` reserved, not v1), §7.4 (the slug alphabet `[a-z0-9-]`, 1-40 chars, no
leading/trailing `-`, which `ref` values must satisfy).

Gate authority (step-2 G4 report §3): the two documented YAML-1.2-core deviations of the
pinned loader are covered HERE, by type-gating —
  D1: `1_000` loads as `int 1000` → a text-typed field receiving an int is REFUSED
      (no silent str() coercion);
  D2: a bare date loads as `datetime.date` → date values are valid ONLY for
      `date-window`-typed attributes; every other type refuses them.

The validator never transforms a value — `validate_value` returns None or raises. This is
the "type validation refuses coercions" acceptance criterion (plan step 8): a value either
IS its declared type or the load fails loudly.

Valid→preimageable scope: the validate-then-canonicalize guarantee holds for TYPED leaves
(and untyped set elements); untyped `map`/`list` interiors are not deep-checked here — any
non-preimageable value inside them (datetime, non-finite float) is refused LOUDLY at
canonicalization (`pipeline/canonical.py`), never silently coerced.

Scope note: this module is the type VOCABULARY + value validation. The `_schema.yaml` field
manifests (type/default/definition/definition_version, per-set default combine operator) are
plan step 11's scope; step 11 drives `parse_type_spec` from those files.
"""

from __future__ import annotations

import datetime
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AttrTypeSpec",
    "CombineOperatorError",
    "LEAF_KINDS",
    "SLIDER_MAX",
    "SLIDER_MIN",
    "SchemaTypeError",
    "TYPE_KINDS",
    "ValueValidationError",
    "parse_type_spec",
    "validate_combine_operator",
    "validate_value",
]

# The §11.1 type vocabulary, constrained → free.
TYPE_KINDS = frozenset(
    {
        "enum",
        "number",
        "slider",
        "range",
        "ref",
        "bool",
        "date-window",
        "list",
        "set",
        "map",
        "text",
        "markdown",
    }
)

# §11.1: a `set` holds unordered LEAF elements — enum/number/ref/bool/string.
LEAF_KINDS = frozenset({"enum", "number", "ref", "bool", "text"})

# §11.1: slider(1-5).
SLIDER_MIN = 1
SLIDER_MAX = 5

# §7.4: slug alphabet [a-z0-9-], 1-40 chars, no leading/trailing '-' (the `x-` instance
# prefix is part of the id and fits this alphabet, §11.4).
_SLUG_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?\Z")

# §12.4: the only combine operators. Set-subtract '-' is reserved, out of v1 (§13.2/§26).
_COMBINE_OPERATORS = frozenset({"replace", "union"})


class SchemaTypeError(ValueError):
    """A malformed attribute-type declaration (schema-side error)."""

    code = "invalid-attr-type-spec"


class CombineOperatorError(ValueError):
    """An invalid combine-operator declaration/use (§11.1/§12.4 schema-validation ERROR)."""

    code = "invalid-combine-operator"


class ValueValidationError(ValueError):
    """A value refused by its declared §11.1 type — coercion never happens instead."""

    code = "value-type-refused"


@dataclass(frozen=True)
class AttrTypeSpec:
    """A parsed §11.1 attribute type.

    `values` is the closed member list for `enum`; `element` is the element type for
    `list`/`set` and the optional uniform value type for `map`.
    """

    kind: str
    values: tuple[str, ...] | None = None
    element: AttrTypeSpec | None = None

    def __post_init__(self) -> None:
        if self.kind not in TYPE_KINDS:
            raise SchemaTypeError(
                f"invalid-attr-type-spec: unknown type kind {self.kind!r} "
                f"(§11.1 kinds: {', '.join(sorted(TYPE_KINDS))})"
            )
        if self.kind == "enum":
            if not self.values:
                raise SchemaTypeError(
                    "invalid-attr-type-spec: enum requires a non-empty `values` list"
                )
            if not all(isinstance(v, str) for v in self.values):
                raise SchemaTypeError("invalid-attr-type-spec: enum `values` must all be strings")
            if len(set(self.values)) != len(self.values):
                raise SchemaTypeError("invalid-attr-type-spec: enum `values` contains duplicates")
        elif self.values is not None:
            raise SchemaTypeError(
                f"invalid-attr-type-spec: `values` is only valid on enum, not {self.kind!r}"
            )
        if self.kind == "set":
            # §11.1: set elements are LEAF — a set-of-maps (or any non-leaf set) is
            # structurally undeclarable, which also closes the union-on-set-of-maps error
            # class at the declaration site.
            if self.element is not None and self.element.kind not in LEAF_KINDS:
                raise SchemaTypeError(
                    "invalid-attr-type-spec: set elements must be leaf-typed "
                    f"(enum/number/ref/bool/text — §11.1), got {self.element.kind!r}"
                )
        elif self.kind == "list":
            # Bounded v1 posture: no nested collections as list elements.
            if self.element is not None and self.element.kind in {"list", "set"}:
                raise SchemaTypeError(
                    "invalid-attr-type-spec: nested list/set element types are not v1 "
                    f"(got list of {self.element.kind!r})"
                )
        elif self.kind == "map":
            if self.element is not None and self.element.kind in {"list", "set"}:
                raise SchemaTypeError(
                    "invalid-attr-type-spec: nested list/set map-value types are not v1 "
                    f"(got map of {self.element.kind!r})"
                )
        elif self.element is not None:
            raise SchemaTypeError(
                "invalid-attr-type-spec: `element` is only valid on list/set/map, not "
                f"{self.kind!r}"
            )


def parse_type_spec(raw: str | Mapping[str, Any]) -> AttrTypeSpec:
    """Parse a type declaration: a bare kind string, or a mapping with `type` (+`values`/`element`).

    Examples: `"number"` · `{"type": "enum", "values": ["a", "b"]}` ·
    `{"type": "set", "element": "ref"}`. The `_schema.yaml` manifest around this (default,
    definition, definition_version, default combine operator) is step 11's loader.
    """
    if isinstance(raw, str):
        return AttrTypeSpec(kind=raw)
    if isinstance(raw, Mapping):
        unknown = set(raw) - {"type", "values", "element"}
        if unknown:
            raise SchemaTypeError(
                f"invalid-attr-type-spec: unknown key(s) {sorted(unknown)!r} in type declaration"
            )
        kind = raw.get("type")
        if not isinstance(kind, str):
            raise SchemaTypeError(
                "invalid-attr-type-spec: type declaration mapping requires `type`"
            )
        values = raw.get("values")
        if values is not None:
            if not isinstance(values, list):
                raise SchemaTypeError("invalid-attr-type-spec: `values` must be a list")
            values = tuple(values)
        element_raw = raw.get("element")
        element = parse_type_spec(element_raw) if element_raw is not None else None
        return AttrTypeSpec(kind=kind, values=values, element=element)
    raise SchemaTypeError(
        "invalid-attr-type-spec: a type declaration is a string or mapping, got "
        f"{type(raw).__name__}"
    )


def validate_combine_operator(spec: AttrTypeSpec, operator: str) -> None:
    """Validate a combine operator against a type (§11.1/§12.4) — declaration or inline use.

    `replace` is valid everywhere. `union` is valid ONLY on an unordered `set` of leaf
    elements; declaring or using it on an ordered `list` (or anything else) is a
    schema-validation ERROR, never a silent coercion. Anything else — including the reserved
    set-subtract `-` — is refused.
    """
    if operator not in _COMBINE_OPERATORS:
        if operator == "-":
            raise CombineOperatorError(
                "invalid-combine-operator: set-subtract '-' is reserved and not v1 (§13.2/§26)"
            )
        raise CombineOperatorError(
            f"invalid-combine-operator: unknown operator {operator!r} "
            "(§12.4 operators: replace, union)"
        )
    if operator == "union" and spec.kind != "set":
        raise CombineOperatorError(
            f"invalid-combine-operator: union on {spec.kind!r} is a schema ERROR — union is "
            "valid only on an unordered leaf-element set (§11.1)"
        )


def _refuse(spec: AttrTypeSpec, value: Any, path: str, detail: str) -> ValueValidationError:
    where = f" at {path!r}" if path else ""
    return ValueValidationError(
        f"value-type-refused{where}: {detail} (declared type {spec.kind!r}, "
        f"got {type(value).__name__}: {value!r})"
    )


def _is_number(value: Any) -> bool:
    """int or float — bool is NOT a number (bool subclasses int; coercion refused)."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _validate_leaf_scalar_class(spec: AttrTypeSpec, value: Any, path: str) -> None:
    """Refuse the value classes no leaf type may carry (dates outside date-window, etc.)."""
    if isinstance(value, datetime.datetime | datetime.date):
        raise _refuse(
            spec,
            value,
            path,
            "date/datetime values are valid only for date-window-typed attributes (D2)",
        )


def validate_value(spec: AttrTypeSpec, value: Any, *, path: str = "") -> None:
    """Validate `value` against `spec`; return None or raise `ValueValidationError`.

    Never transforms the value — refusal, not coercion (plan step-8 acceptance; step-2 D1/D2
    dispositions). `path` is an optional label used in error messages only.
    """
    kind = spec.kind

    if kind in {"text", "markdown"}:
        _validate_leaf_scalar_class(spec, value, path)
        if not isinstance(value, str):
            # D1: `1_000` loaded as int 1000 lands here and is refused, never str()-ed.
            raise _refuse(spec, value, path, "free-text field requires a string")
        return

    if kind == "enum":
        _validate_leaf_scalar_class(spec, value, path)
        if not isinstance(value, str):
            raise _refuse(spec, value, path, "enum member must be a string token")
        assert spec.values is not None  # enforced at spec construction
        if value not in spec.values:
            raise _refuse(
                spec, value, path, f"not a declared enum member (members: {list(spec.values)})"
            )
        return

    if kind == "ref":
        _validate_leaf_scalar_class(spec, value, path)
        if not isinstance(value, str):
            raise _refuse(spec, value, path, "ref must be an entry-id string")
        if not _SLUG_RE.match(value):
            raise _refuse(
                spec,
                value,
                path,
                "ref must match the §7.4 slug alphabet [a-z0-9-], 1-40 chars, "
                "no leading/trailing '-'",
            )
        return

    if kind == "bool":
        if not isinstance(value, bool):
            raise _refuse(spec, value, path, "bool requires true/false (YAML 1.2 core booleans)")
        return

    if kind == "number":
        _validate_leaf_scalar_class(spec, value, path)
        if not _is_number(value):
            raise _refuse(spec, value, path, "number requires an int or float (bool refused)")
        if isinstance(value, float) and not math.isfinite(value):
            raise _refuse(
                spec, value, path, "non-finite numbers (.inf/.NaN) are refused (not preimageable)"
            )
        return

    if kind == "slider":
        if not isinstance(value, int) or isinstance(value, bool):
            raise _refuse(spec, value, path, "slider requires an integer (no float coercion)")
        if not (SLIDER_MIN <= value <= SLIDER_MAX):
            raise _refuse(
                spec, value, path, f"slider value out of bounds {SLIDER_MIN}-{SLIDER_MAX} (§11.1)"
            )
        return

    if kind == "range":
        if not isinstance(value, list) or len(value) != 2:
            raise _refuse(spec, value, path, "range requires a two-element [lo, hi] sequence")
        lo, hi = value
        for bound in (lo, hi):
            if not _is_number(bound) or (isinstance(bound, float) and not math.isfinite(bound)):
                raise _refuse(spec, value, path, "range bounds must be finite numbers")
        if lo > hi:
            raise _refuse(spec, value, path, "range bounds must satisfy lo <= hi")
        return

    if kind == "date-window":
        # The ONLY type that admits dates (D2). Date-granular by design (§6.2 date-window
        # operators are calendar-level); datetime.datetime is refused — see canonical.py's
        # matching discipline. NOTE: datetime.datetime subclasses datetime.date, so the
        # refusal must be checked first.
        if isinstance(value, datetime.datetime):
            raise _refuse(spec, value, path, "date-window is date-granular; timestamps are refused")
        if isinstance(value, datetime.date):
            return
        if isinstance(value, list) and len(value) == 2:
            start, end = value
            for edge in (start, end):
                if isinstance(edge, datetime.datetime) or not isinstance(edge, datetime.date):
                    raise _refuse(spec, value, path, "date-window pair edges must be bare dates")
            if start > end:
                raise _refuse(spec, value, path, "date-window pair must satisfy start <= end")
            return
        raise _refuse(
            spec, value, path, "date-window requires a date or a two-element [start, end] pair"
        )

    if kind == "list":
        if not isinstance(value, list):
            raise _refuse(spec, value, path, "list requires a sequence")
        if spec.element is not None:
            for i, item in enumerate(value):
                validate_value(spec.element, item, path=f"{path}[{i}]" if path else f"[{i}]")
        return

    if kind == "set":
        if not isinstance(value, list):
            raise _refuse(spec, value, path, "set requires a sequence of leaf elements")
        seen: set[tuple[str, str]] = set()
        for i, item in enumerate(value):
            item_path = f"{path}[{i}]" if path else f"[{i}]"
            if spec.element is not None:
                validate_value(spec.element, item, path=item_path)
            else:
                _validate_leaf_scalar_class(spec, item, item_path)
                if not isinstance(item, str | bool | int | float):
                    raise _refuse(
                        spec, item, item_path, "set elements must be leaf scalars (§11.1)"
                    )
                if isinstance(item, float) and not math.isfinite(item):
                    raise _refuse(
                        spec,
                        item,
                        item_path,
                        "non-finite numbers are refused (not preimageable)",
                    )
            # Exact-value duplicate is an authoring error — loud refusal, not silent dedupe
            # (dedupe is §12.4 union semantics at combine time, canonical.canonical_set).
            # The key mirrors canonical_set's rendering-distinguishing key: the type name
            # separates 1/1.0/True, and repr distinguishes ==-equal values that render
            # differently (-0.0 vs 0.0) — so duplicate detection here agrees with
            # canonicalization about which members are distinct.
            key = (type(item).__name__, repr(item))
            if key in seen:
                raise _refuse(spec, item, item_path, "duplicate element in a set value")
            seen.add(key)
        return

    if kind == "map":
        if not isinstance(value, dict):
            raise _refuse(spec, value, path, "map requires a mapping")
        for k, v in value.items():
            if not isinstance(k, str):
                raise _refuse(
                    spec,
                    k,
                    path,
                    "map keys must be strings (a coerced YAML 1.1 key would "
                    "surface here as non-str and is refused)",
                )
            if spec.element is not None:
                validate_value(spec.element, v, path=f"{path}.{k}" if path else k)
        return

    raise SchemaTypeError(f"invalid-attr-type-spec: unhandled kind {kind!r}")  # pragma: no cover
