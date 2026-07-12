"""Run-layer attribute overrides (§12.5, §21.4): the ephemeral L6 mechanism.

Design authority: `docs/design.md`
  §12.5 (CA5) — an override is temporary and limited-scope: it lives ONLY at L6
          (run/session), is supplied at `begin-session`, and is never persisted.
          Persistent scopes hold CONFIGURATION, never "overrides" — the word is
          reserved for this mechanism (§4). Injection is **collect-once,
          apply-at-bind** (CA7): `collect_overrides` below is the ONE collection
          point; values apply at M2 (compose-stage content dimensions, render-stage
          rendering dimensions — `pipeline/cascade.py`), never at M1, and no stage
          re-injects later. An override's effect enters `resolved-overrides` (§7.2)
          as an effective-value deviation — captured in identity (CA6) by the
          delta-vs-floor math, while no configuration anywhere changed.
  §21.4 (API5) — **the hard M1 guard**: an override binds a value to a DECLARED schema
          attribute of an ALREADY-SELECTED entry, and nothing else. It can never
          (a) add an attribute — undeclared names are refused; (b) pick or replace
          which entry is used — that is `selection`, an M1 input (a one-segment path
          is exactly that attempt); (c) touch schema/envelope vocabulary — reserved
          names (`id`, `provenance`, `schema_version`, `extends`, `metadata`,
          `aliases`) are refused. `union` on an ordered list or any non-set is
          likewise refused (§11.1). Every refusal is the ONE typed code:
          `invalid-override`. Keys are `<dimension>.<attribute>`; values are plain
          (replace) or carry the §13.2 operator (`union` on sets; the
          `{combine:…, add:…}` wrapper; the wire `{path, op, value}` object).
  §12.7 (CA9) — hard limits live entirely OUTSIDE M2: `platform.hard_limits` is never
          bound and never overridable — refused here at collect time.

Wiring, never duplication: both override surfaces parse through the §13.2 grammar
(`pipeline/opgrammar` — the frontmatter pair surface and the wire object surface);
operator legality and operand typing ride `attrtypes.validate_combine_operator` /
`validate_value` (the single implementations). The API face (`begin-session` transport
shape) lands at plan step 33; this module is the MECHANISM it will call.

In-latitude decisions (step-16 coder; grounded in the report):

- **Grammar refusals are wrapped as `invalid-override`** (with the original typed error
  as `__cause__`): §21.4 names ONE refusal code for the override surface, and the
  underlying `CombineOperatorError`/`SurfaceSyntaxError` detail rides the message.
- **Duplicate paths are refused** at collect: two bindings for one attribute in one
  override set are ambiguous — loud, never last-wins (§3.1 surfaced-never-silent).
- **Values are deep-copied at collect**: the set is immutable session state (§12.5
  L6 is ephemeral session state); a caller mutating its input after collection can
  never change what binds.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pipeline.attrtypes import (
    CombineOperatorError,
    validate_combine_operator,
    validate_value,
)
from pipeline.m1 import (
    CONTENT_DIMENSION_TOKENS,
    DIMENSION_COLLECTIONS,
    RENDERING_DIMENSION_TOKENS,
)
from pipeline.opgrammar import (
    Bind,
    OperatorGrammarError,
    parse_frontmatter_binding,
    parse_wire_bind,
)
from pipeline.schema import RESERVED_ATTRIBUTE_NAMES, Schema

__all__ = [
    "Override",
    "OverrideError",
    "OverrideSet",
    "collect_overrides",
    "validate_override_against_schema",
]

#: CA9 (§12.7): the one attribute class that is never bound and never overridable.
_HARD_LIMIT_ATTRIBUTE = ("platform", "hard_limits")


class OverrideError(ValueError):
    """§21.4: every override refusal — the ONE typed code `invalid-override`."""

    code = "invalid-override"


@dataclass(frozen=True)
class Override:
    """One collected L6 binding: `<dimension>.<attribute>` + operator + operand."""

    dimension: str
    attribute: str
    op: str
    value: Any
    #: True when the operator was spelled inline (`+` suffix, wrapper, or the wire
    #: `op` field) — an explicit operator beats a set's schema default operator; a
    #: bare binding takes the type-driven default (§12.4).
    explicit: bool

    @property
    def path(self) -> str:
        return f"{self.dimension}.{self.attribute}"


@dataclass(frozen=True)
class OverrideSet:
    """The collect-once product (CA7): immutable session state, applied at M2 bind.

    `compose_items`/`render_items` are the CA7 staging split: content-dimension
    overrides bind at M2-compose (→ `artifact-id`), rendering-dimension overrides at
    M2-render (→ `deliverable-id`) — §12.3 bind stages.
    """

    items: tuple[Override, ...] = ()

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def for_dimension(self, dimension: str) -> tuple[Override, ...]:
        return tuple(o for o in self.items if o.dimension == dimension)

    @property
    def compose_items(self) -> tuple[Override, ...]:
        return tuple(o for o in self.items if o.dimension in CONTENT_DIMENSION_TOKENS)

    @property
    def render_items(self) -> tuple[Override, ...]:
        return tuple(o for o in self.items if o.dimension in RENDERING_DIMENSION_TOKENS)


def _override_from_bind(bind: Bind, *, explicit: bool, where: str) -> Override:
    """The structural half of the hard M1 guard (§21.4 API5) — schema-independent."""
    segments = bind.path.split(".")
    if len(segments) == 1:
        raise OverrideError(
            f"invalid-override: {where}: path {bind.path!r} names a whole dimension — "
            "an override never picks or replaces which entry is used; that is "
            "`selection`, an M1 input (§21.4 API5, §12.5)"
        )
    if len(segments) != 2:
        raise OverrideError(
            f"invalid-override: {where}: path {bind.path!r} — override keys are exactly "
            "`<dimension>.<attribute>` (§21.4)"
        )
    dimension, attribute = segments
    if dimension not in DIMENSION_COLLECTIONS:
        raise OverrideError(
            f"invalid-override: {where}: {dimension!r} is not a dimension — overrides "
            f"bind dimension attributes only (§21.4); dimensions: "
            f"{sorted(DIMENSION_COLLECTIONS)}"
        )
    if attribute in RESERVED_ATTRIBUTE_NAMES:
        raise OverrideError(
            f"invalid-override: {where}: {attribute!r} is envelope/mechanism vocabulary "
            "— an override never touches schema, identity, or M1 syntax (§21.4 API5); "
            f"reserved: {sorted(RESERVED_ATTRIBUTE_NAMES)}"
        )
    if (dimension, attribute) == _HARD_LIMIT_ATTRIBUTE:
        raise OverrideError(
            f"invalid-override: {where}: hard limits never enter M2 — never bound, "
            "never overridable; they are enforced only at the reconcile gate "
            "(CA9, §12.7/§16)"
        )
    return Override(
        dimension=dimension,
        attribute=attribute,
        op=bind.op,
        value=copy.deepcopy(bind.value),
        explicit=explicit,
    )


def collect_overrides(raw: Any) -> OverrideSet:
    """THE collection point (CA7: collect-once at `begin-session`, §12.5/§21.4).

    Accepts either surface of the §13.2 grammar:

    - a MAPPING of `<dimension>.<attribute>` keys to operand values — the frontmatter
      pair surface (`voice.formality: 2`, `format.tags+: [x]`,
      `format.tags: {combine: union, add: [x]}`);
    - a SEQUENCE of wire objects `{"path", "op", "value"}` (§13.2's single wire shape).

    `None` collects the empty set. Every refusal — grammar, shape, or guard — is the
    typed `invalid-override` (§21.4). Schema-level validation (declared attribute,
    operator×type, operand typing) runs against the selected entries' schemas via
    `validate_override_against_schema` (the cascade env calls it — apply-at-bind).
    """
    if raw is None:
        return OverrideSet()
    collected: list[Override] = []
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            where = f"override {key!r}"
            try:
                bind = parse_frontmatter_binding(key, value)
            except (OperatorGrammarError, CombineOperatorError) as exc:
                raise OverrideError(f"invalid-override: {where}: {exc}") from exc
            explicit = (isinstance(key, str) and key.endswith("+")) or (
                isinstance(value, Mapping) and "combine" in value
            )
            collected.append(_override_from_bind(bind, explicit=explicit, where=where))
    elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        for obj in raw:
            where = f"override {obj!r}"
            try:
                bind = parse_wire_bind(obj)
            except (OperatorGrammarError, CombineOperatorError) as exc:
                raise OverrideError(f"invalid-override: {where}: {exc}") from exc
            # The wire form always names its operator — explicit by construction.
            collected.append(_override_from_bind(bind, explicit=True, where=where))
    else:
        raise OverrideError(
            "invalid-override: overrides are a mapping of `<dimension>.<attribute>` "
            "keys or a sequence of wire objects (§13.2/§21.4), got "
            f"{type(raw).__name__}"
        )
    seen: set[str] = set()
    for override in collected:
        if override.path in seen:
            raise OverrideError(
                f"invalid-override: {override.path!r} is bound twice in one override "
                "set — ambiguous, refused (loud, never last-wins; §3.1)"
            )
        seen.add(override.path)
    return OverrideSet(items=tuple(collected))


def validate_override_against_schema(override: Override, schema: Schema) -> None:
    """The schema half of the hard M1 guard (§21.4 API5), applied at bind time.

    Refuses (as `invalid-override`, with the underlying typed error as the cause):
    an UNDECLARED attribute (never add an attr); an illegal operator×type pairing —
    `union` on an ordered list or any non-set (§11.1); an operand refused by the
    attribute's §11.1 type.
    """
    spec = schema.attributes.get(override.attribute)
    if spec is None:
        raise OverrideError(
            f"invalid-override: {override.path}: {override.attribute!r} is not declared "
            f"by the {schema.collection!r} schema — an override never ADDS an attribute "
            f"(§21.4 API5); declared: {sorted(schema.attributes)}"
        )
    try:
        validate_combine_operator(spec.type, override.op)
        validate_value(spec.type, override.value, path=override.path)
    except ValueError as exc:
        raise OverrideError(f"invalid-override: {override.path}: {exc}") from exc
