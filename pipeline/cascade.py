"""M2 — value binding (Mechanism 2 of the §12 value cascade): the folio-free spine fold.

Design authority: `docs/design.md`
  §12.2 — the six-rung spine: L0 schema-default · L1 entry-default (the M1-resolved
          effective entry, CA1) · L2 global-default (MANDATORY for the CA8 set) ·
          L3 workspace-default · L5 recipe · L6 run. Higher rung wins, type-driven,
          only for the attributes it declares. **No folio rung exists** (DIRECTIVE);
          L4 is retired and rungs are deliberately not renumbered. L0–L5 are persistent
          workspace state; L6 is ephemeral session state, never persisted.
  §12.3 — rung semantics per dimension: bind stages (content dimensions at M2-compose →
          `artifact-id`; rendering dimensions at M2-render → `deliverable-id`); the
          CA8 mandatory-global set (Voice + Language + Output-type — validation errors
          if absent; Platform excluded — per-deliverable routing; Presentation excluded
          — the `plain` floor, PD7); the voice selection chain (CA2 + §12.6 BO2);
          Platform's per-format advisory projection + the two-tier reconcile-strategy
          defaulting (L0 single-attribute schema floor `adapt`; the per-(format ×
          platform) table on the Platform entry's projection, merging below L5);
          the platform-implied WEAK default output-type (explicit L3/L5/L6 beats it).
  §12.4 — type-driven combination: ONE rule set, imported from `pipeline/m1.py`
          (`combine_values`/`default_combine_op`), never re-implemented. Inline
          combine operators ride the step-9 §13.2 AST (CM3: one token at the binding
          being edited; never a cascading value).
  §12.5 — overrides are the ephemeral run layer ONLY (CA5): collected once at
          begin-session (`pipeline/overrides.collect_overrides`, CA7), applied at M2
          bind in two stages (compose/render), never at M1, never re-injected. Their
          effect enters identity as effective-value deviations (CA6, §7.2).
  §12.6 — brand-authoritative scope defaults (BO2): the `authoritative: a|b|c` flag on
          the global/workspace VOICE scope-default value elevates it in the chain;
          a run deviation from an a/b flag fires a one-time warning; `c` beats the run
          (surfaced, never silent — §3.1). Voice-only in v1.
  §12.7 — two constraint classes, two homes (CA9): advisory norms ride M2 as configured
          values (recipe/run deviation → one-time warning); HARD LIMITS never enter M2 —
          never bound, never overridable, enforced only at the reconcile gate (§16,
          plan step 25). Goal source-weight nudges ride M3's goal-implied lane and
          never move recipe/run weights (CA10) — `M3Inputs` keeps the lanes separate;
          **M3 stays separate** (§12.1: M2 never touches source selection).
  §7.2  — identity: `resolved-overrides` = the canonical per-dimension delta of
          effective values vs the schema-default floor; the compose resolution feeds
          `pipeline/ids.build_artifact_preimage` directly.
  §13.1/T10 — the scope-default surfaces: `instance/defaults.yaml` (L2) and
          `workspaces/<client>/defaults.yaml` (L3), human-maintained pure value
          manifests, schema-validated here (both templates defer their populated-shape
          validation to this module by name).

In-latitude decisions (step-16 coder; grounded in the report):

- **The T10 defaults-file shape is ratified as the templates document it** (the step-15
  carry-forward): closed key vocabulary per scope — global: `voice` · `language` ·
  `output_type` · `goals` · `presentation` · `values`; workspace adds `topic` ·
  `persona` · `format` · `source_selection`. `voice:` accepts the dual form — a bare
  entry id, or `{entry: <id>, authoritative: true|a|b|c}` (bare `true` = strength `b`,
  §12.6). `values:` keys are §13.2 `<dimension>.<attribute>` paths (inline operators
  legal, CM3). The rungs each dimension normally populates follow the §12.3 table.
- **`persona.default_voice` inserts into the chain only when the persona SETS it**
  (directly or via an M1 partial): CA2's rationale is the persona's *bundled* editorial
  voice; a floor-riding persona bundles none, and letting the L0 net outrank the CA8
  mandatory L2 baseline would invert §12.2. This mirrors the ratified recipes.voice
  posture ("the floor is the L0 last-resort net only, never an L5 binding").
- **The most local brand flag arbitrates** (§12.6): a flagged workspace (L3) voice
  shadows a flagged global (L2) voice for that workspace — the client brand beats the
  house brand inside the client's own scope (isolation, §10).
- **The no-platform reconcile-strategy floor** (step-14 carry-forward): with no platform
  selected there is no platform entry in the resolution set, so the strategy is read
  from the platforms COLLECTION MANIFEST's L0 floor (`adapt`) — the schema exists
  independent of any entry (§12.2 L0 = schema defaults). Recipe/run strategy binds ride
  `platform.reconcile_strategy` and therefore require a selected platform (§21.4).
- **Never-M2 platform attributes**: `hard_limits` (CA9), the projection tables
  (`format_advisories`, `reconcile_strategy_defaults` — consumed BY the projection),
  `default_output_type` (consumed by output-type selection), and `destination` (its own
  definition: "never a cascade value") are refused as binding targets at every rung and
  stripped from the bound-value output. `goal.source_selection` is likewise refused as
  an M2 binding target (§12.1: M2 never touches source selection) — the goal ENTRY's
  own value still rides identity per §7.2.
- **One-time warnings are per-session**: the env deduplicates by stable warning key
  (the session is the natural "once" scope — L6 is session state, §12.5/§20).
- **Rendering coordinates resolve ONE deliverable**: multiple recipe pins with no
  explicit coordinate are an `ambiguous-rendering-selection` refusal — fanout
  (enumerating coordinates) is plan step 19's scope, not a silent pick here.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from pipeline.attrtypes import validate_combine_operator, validate_value
from pipeline.drift import WindowOracle
from pipeline.ids import EntryBinding, build_artifact_preimage, delta_vs_floor
from pipeline.m1 import (
    DIMENSION_COLLECTIONS,
    ResolutionWarning,
    ResolvedEntry,
    Resolver,
    combine_values,
    default_combine_op,
)
from pipeline.opgrammar import OperatorGrammarError, parse_frontmatter_binding
from pipeline.overrides import (
    Override,
    OverrideError,
    OverrideSet,
    collect_overrides,
    validate_override_against_schema,
)
from pipeline.schema import RESERVED_ATTRIBUTE_NAMES, UndeclaredAttributeError
from pipeline.yamlio import load_yaml

__all__ = [
    "BoundDimension",
    "CascadeEnv",
    "CascadeError",
    "ComposeResolution",
    "GLOBAL_SCOPE",
    "HardLimitBindingError",
    "INSTANCE_DEFAULTS_RELPATH",
    "M3Inputs",
    "MANDATORY_GLOBAL_KEYS",
    "MandatoryGlobalError",
    "PLATFORM_UNBOUND_ATTRIBUTES",
    "PRESENTATION_FLOOR_ENTRY",
    "RUNG_L0",
    "RUNG_L1",
    "RUNG_L2",
    "RUNG_L3",
    "RUNG_L5",
    "RUNG_L6",
    "RUNG_PROJECTION",
    "RenderResolution",
    "RunSelection",
    "ScopeDefaults",
    "ScopeDefaultsError",
    "SelectionError",
    "UnbindableAttributeError",
    "ValueBinding",
    "VoiceDefault",
    "WORKSPACE_DEFAULTS_FILENAME",
    "WORKSPACE_SCOPE",
    "load_scope_defaults",
    "parse_scope_defaults",
    "parse_value_bindings",
    "resolve_compose",
    "resolve_render",
]

#: §12.2 rung labels (per-attribute provenance in the bound output). L4 is retired with
#: the deleted folio rung — the labels keep the design's numbering, uncompacted.
RUNG_L0 = "L0-schema-default"
RUNG_L1 = "L1-entry-default"
RUNG_L2 = "L2-global-default"
RUNG_L3 = "L3-workspace-default"
RUNG_PROJECTION = "platform-projection"  # merges below L5 (§12.3)
RUNG_L5 = "L5-recipe"
RUNG_L6 = "L6-run"

#: T10 (plan §1): the two scope-default surfaces.
INSTANCE_DEFAULTS_RELPATH = Path("instance") / "defaults.yaml"
WORKSPACE_DEFAULTS_FILENAME = "defaults.yaml"

GLOBAL_SCOPE = "global"
WORKSPACE_SCOPE = "workspace"

#: CA8 (§12.3): the mandatory-global set — the instance MUST set all three at L2.
MANDATORY_GLOBAL_KEYS = ("voice", "language", "output_type")

#: PD7 (§12.3): Presentation's L0 selection floor is the framework `plain` entry.
PRESENTATION_FLOOR_ENTRY = "plain"

#: §12.6: brand-flag strengths; a bare `true` means `b` (the default).
_VOICE_FLAG_STRENGTHS = ("a", "b", "c")

#: T10 closed key vocabularies (the ratified template shapes; §12.3 rung table).
_GLOBAL_KEYS = frozenset({"voice", "language", "output_type", "goals", "presentation", "values"})
_WORKSPACE_KEYS = _GLOBAL_KEYS | {"topic", "persona", "format", "source_selection"}

#: (dimension, attribute) pairs that are NEVER M2 binding targets, with the design
#: grounding per row (see the module docstring). `platform.hard_limits` carries its own
#: CA9 error class; the rest refuse as `unbindable-attribute`.
UNBINDABLE_VALUE_BINDINGS: dict[tuple[str, str], str] = {
    ("platform", "hard_limits"): (
        "hard limits never enter M2 — never bound, never overridable; enforced only at "
        "the reconcile gate (CA9, §12.7/§16)"
    ),
    ("platform", "format_structural"): (
        "a per-format HARD structural class never enters M2 — never bound, never overridable; "
        "enforced only at the reconcile structural gate (the sibling of hard_limits; §12.7/§16 "
        "DR-4)"
    ),
    ("platform", "format_advisories"): (
        "a projection TABLE consumed by the per-format advisory projection below L5 "
        "(§12.3) — deviate via `platform.advisory_norms` instead"
    ),
    ("platform", "reconcile_strategy_defaults"): (
        "a projection TABLE consumed by the per-format strategy defaulting below L5 "
        "(§12.3) — bind `platform.reconcile_strategy` instead"
    ),
    ("platform", "default_output_type"): (
        "the platform-implied WEAK output-type default is consumed by output-type "
        "selection (§12.3) — select an explicit output-type instead"
    ),
    ("platform", "destination"): (
        "routing documentation for humans; never a cascade value (its own §5.3 definition)"
    ),
    ("goal", "source_selection"): (
        "M2 never touches source selection (§12.1) — goal clauses ride M3's "
        "goal-implied lane (§6.3, step 17)"
    ),
}

#: Platform attributes stripped from the M2 bound-value output (same rows; CA9 proof:
#: a platform hard limit is provably absent from bound values).
PLATFORM_UNBOUND_ATTRIBUTES = frozenset(
    attr for (dim, attr) in UNBINDABLE_VALUE_BINDINGS if dim == "platform"
)


# --- Typed errors -----------------------------------------------------------------------


class CascadeError(ValueError):
    """An M2 cascade refusal — loud, typed, never repaired."""

    code = "cascade-refused"


class ScopeDefaultsError(CascadeError):
    """A malformed T10 scope-default file (closed vocabulary; the ratified shapes)."""

    code = "invalid-scope-defaults"


class MandatoryGlobalError(CascadeError):
    """CA8 (§12.3): a missing mandatory global — Voice/Language/Output-type at L2."""

    code = "missing-mandatory-global"


class SelectionError(CascadeError):
    """An unusable run/recipe selection (e.g. no topic anywhere — §12.3: Topic's L5
    selection is required; a recipe generates nothing without a topic)."""

    code = "invalid-selection"


class AmbiguousSelectionError(CascadeError):
    """Multiple pinned rendering targets with no explicit coordinate — enumerating the
    fanout is plan step 19's job; a silent pick is never made."""

    code = "ambiguous-rendering-selection"


class HardLimitBindingError(CascadeError):
    """CA9 (§12.7): a hard limit offered as an M2 binding at any persistent rung."""

    code = "hard-limit-not-bindable"


class UnbindableAttributeError(CascadeError):
    """A never-M2 attribute offered as a binding target (see the table above)."""

    code = "unbindable-attribute"


# --- Value bindings (the §13.2 `<dimension>.<attribute>` surface) ------------------------


@dataclass(frozen=True)
class ValueBinding:
    """One configured value binding at a persistent rung (L2/L3/L5)."""

    dimension: str
    attribute: str
    op: str
    value: Any
    explicit: bool
    where: str


def _refuse_unbindable(dimension: str, attribute: str, where: str) -> None:
    reason = UNBINDABLE_VALUE_BINDINGS.get((dimension, attribute))
    if reason is None:
        return
    message = f"{where}: {dimension}.{attribute}: {reason}"
    if attribute == "hard_limits":
        raise HardLimitBindingError(f"hard-limit-not-bindable: {message}")
    raise UnbindableAttributeError(f"unbindable-attribute: {message}")


def parse_value_bindings(raw: Any, *, where: str) -> tuple[ValueBinding, ...]:
    """Parse a `values:` map (T10 scope defaults, recipe `values` — §8) into bindings.

    Keys are §13.2 paths `<dimension>.<attribute>` with the CM3 inline-operator
    spellings (`+` suffix, `{combine:…, add:…}` wrapper); operands are host-native
    values. Shape-level validation only — attribute declaredness and operand typing
    are validated against the dimension schemas by the env (apply-at-bind, CA7).
    """
    if raw is None:
        return ()
    if not isinstance(raw, Mapping):
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: {where}: `values` must be a mapping of "
            f"`<dimension>.<attribute>` bindings (§13.2), got {type(raw).__name__}"
        )
    bindings: list[ValueBinding] = []
    for key, value in raw.items():
        label = f"{where}.values[{key!r}]"
        try:
            bind = parse_frontmatter_binding(key, value)
        except OperatorGrammarError as exc:
            raise ScopeDefaultsError(f"invalid-scope-defaults: {label}: {exc}") from exc
        segments = bind.path.split(".")
        if len(segments) != 2:
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {label}: value-binding keys are exactly "
                "`<dimension>.<attribute>` (§21.4/§13.2)"
            )
        dimension, attribute = segments
        if dimension not in DIMENSION_COLLECTIONS:
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {label}: {dimension!r} is not a dimension "
                f"(§5.1); dimensions: {sorted(DIMENSION_COLLECTIONS)}"
            )
        if attribute in RESERVED_ATTRIBUTE_NAMES:
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {label}: {attribute!r} is envelope/mechanism "
                "vocabulary, never a bindable attribute (§11.1)"
            )
        _refuse_unbindable(dimension, attribute, label)
        explicit = (isinstance(key, str) and key.endswith("+")) or (
            isinstance(value, Mapping) and "combine" in value
        )
        bindings.append(
            ValueBinding(
                dimension=dimension,
                attribute=attribute,
                op=bind.op,
                value=copy.deepcopy(bind.value),
                explicit=explicit,
                where=label,
            )
        )
    return tuple(bindings)


# --- T10 scope-default surfaces (L2/L3) ---------------------------------------------------


@dataclass(frozen=True)
class VoiceDefault:
    """A scope-default voice selection — the dual `voice:` form (T10; §12.6)."""

    entry: str
    #: §12.6 strength `a`/`b`/`c`, or None when unflagged.
    authoritative: str | None = None


@dataclass(frozen=True)
class ScopeDefaults:
    """One parsed scope-default surface: L2 (`scope=global`) or L3 (`scope=workspace`)."""

    scope: str
    where: str
    voice: VoiceDefault | None = None
    language: str | None = None
    output_type: str | None = None
    presentation: str | None = None
    topic: str | None = None
    persona: str | None = None
    format: str | None = None
    goals: tuple[str, ...] | None = None
    values: tuple[ValueBinding, ...] = ()
    #: M3's workspace-default layer, carried AS AUTHORED (§12.1: M2 never touches
    #: source selection; the §6.3 grammar is step 17's).
    source_selection: Mapping[str, Any] | None = None

    @classmethod
    def empty(cls, scope: str, where: str) -> ScopeDefaults:
        return cls(scope=scope, where=where)


def _require_id(value: Any, what: str, where: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: {where}: {what} must be an entry-id string, got {value!r}"
        )
    return value


def _parse_voice_default(value: Any, where: str) -> VoiceDefault:
    if isinstance(value, str):
        return VoiceDefault(entry=_require_id(value, "voice", where))
    if isinstance(value, Mapping):
        unknown = set(value) - {"entry", "authoritative"}
        if unknown:
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {where}: the voice mapping form is exactly "
                f"{{entry, authoritative}} (T10/§12.6), got extra {sorted(unknown)!r}"
            )
        entry = _require_id(value.get("entry"), "voice.entry", where)
        raw_flag = value.get("authoritative", False)
        if raw_flag is False:
            return VoiceDefault(entry=entry)
        if raw_flag is True:
            return VoiceDefault(entry=entry, authoritative="b")  # bare flag = b (§12.6)
        if raw_flag in _VOICE_FLAG_STRENGTHS:
            return VoiceDefault(entry=entry, authoritative=raw_flag)
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: {where}: voice.authoritative must be true, false, "
            f"or a strength 'a'|'b'|'c' (§12.6), got {raw_flag!r}"
        )
    raise ScopeDefaultsError(
        f"invalid-scope-defaults: {where}: `voice` is an entry id or the "
        "{entry, authoritative} mapping (T10 dual form), got "
        f"{type(value).__name__}"
    )


def parse_scope_defaults(text: str, *, scope: str, where: str) -> ScopeDefaults:
    """Parse one T10 scope-default document (the ratified template shapes).

    Applies the same `%`-directive refusal as every standalone config surface
    (S-E8 parity — `pipeline/yamlio` splitter, `pipeline/schema` loader precedent):
    an in-document `%YAML 1.1` directive would re-open the Norway problem.
    """
    if scope not in (GLOBAL_SCOPE, WORKSPACE_SCOPE):
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: unknown scope {scope!r} (global | workspace)"
        )
    text = text.removeprefix("\ufeff")
    for line in text.splitlines():
        if line.startswith("%"):
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {where}: a %-directive line is refused "
                f"(S-E8 parity; refused line: {line!r})"
            )
    data = load_yaml(text)
    if data is None:
        return ScopeDefaults.empty(scope, where)
    if not isinstance(data, Mapping):
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: {where}: a scope-default file is a YAML mapping, "
            f"got {type(data).__name__}"
        )
    allowed = _GLOBAL_KEYS if scope == GLOBAL_SCOPE else _WORKSPACE_KEYS
    unknown = {k for k in data if not isinstance(k, str)} | (set(data) - allowed)
    if unknown:
        raise ScopeDefaultsError(
            f"invalid-scope-defaults: {where}: unknown key(s) "
            f"{sorted(repr(k) for k in unknown)} — the {scope} surface vocabulary is "
            f"closed (T10): {sorted(allowed)}"
        )

    voice = _parse_voice_default(data["voice"], where) if "voice" in data else None

    simple: dict[str, str | None] = {}
    simple_keys = ("language", "output_type", "presentation", "topic", "persona", "format")
    for key in simple_keys:
        simple[key] = _require_id(data[key], key, where) if key in data else None

    goals: tuple[str, ...] | None = None
    if "goals" in data:
        raw_goals = data["goals"]
        if not isinstance(raw_goals, list):
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {where}: `goals` must be a list of goal entry "
                f"ids (§12.3), got {type(raw_goals).__name__}"
            )
        members = [_require_id(g, "goals member", where) for g in raw_goals]
        if len(set(members)) != len(members):
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {where}: duplicate goal id in `goals` — the "
                "goal-set is a set (§5.2); loud, never silently deduped"
            )
        goals = tuple(members)

    source_selection: Mapping[str, Any] | None = None
    if "source_selection" in data:
        raw_selection = data["source_selection"]
        if not isinstance(raw_selection, Mapping):
            raise ScopeDefaultsError(
                f"invalid-scope-defaults: {where}: `source_selection` must be a mapping "
                f"(§6.3 clauses; parsed by the M3 resolver, step 17)"
            )
        source_selection = copy.deepcopy(dict(raw_selection))

    return ScopeDefaults(
        scope=scope,
        where=where,
        voice=voice,
        language=simple["language"],
        output_type=simple["output_type"],
        presentation=simple["presentation"],
        topic=simple["topic"],
        persona=simple["persona"],
        format=simple["format"],
        goals=goals,
        values=parse_value_bindings(data.get("values"), where=where),
        source_selection=source_selection,
    )


def load_scope_defaults(path: str | Path, *, scope: str) -> ScopeDefaults:
    """Load one scope-default file (strict UTF-8; decode errors propagate loudly)."""
    path = Path(path)
    return parse_scope_defaults(path.read_text(encoding="utf-8"), scope=scope, where=str(path))


# --- The run selection (M1 inputs — never overrides; §21.4) --------------------------------


@dataclass(frozen=True)
class RunSelection:
    """One item's selection: which entries, per dimension (§12.1 'read pre-M1').

    Selection PICKS entries — the legitimate run-time counterpart of the override
    guard's refusal (§21.4: picking an entry "is `selection`, an M1 input"). Content
    picks feed `resolve_compose`; rendering coordinates feed `resolve_render` (one
    deliverable per call — fanout enumeration is plan step 19).
    """

    recipe: str
    topic: str | None = None
    persona: str | None = None
    format: str | None = None
    voice: str | None = None
    goals: tuple[str, ...] | None = None
    platform: str | None = None
    language: str | None = None
    output_type: str | None = None
    presentation: str | None = None


# --- Bound output shapes -------------------------------------------------------------------


@dataclass(frozen=True)
class BoundDimension:
    """One dimension's M2 result: the selected entry + its bound attribute values.

    `values` is TOTAL over the schema (floor-riding attributes included);
    `provenance` labels the winning rung per attribute. `binding()`/`delta()` feed
    the §7.2 identity math unchanged.
    """

    dimension: str
    entry: ResolvedEntry
    values: dict[str, Any]
    provenance: dict[str, str]

    @property
    def entry_id(self) -> str:
        return self.entry.id

    def binding(self) -> EntryBinding:
        return EntryBinding(
            entry_id=self.entry.id, effective=self.values, defaults=self.entry.defaults()
        )

    def delta(self) -> dict[str, Any]:
        """The §7.2 delta-vs-floor map (CA6: configured deviations and run overrides
        alike enter here)."""
        return delta_vs_floor(self.values, self.entry.defaults(), where=self.dimension)


@dataclass(frozen=True)
class M3Inputs:
    """The M3 layers this resolution CARRIES (never merges — §12.1: M3 is separate).

    `workspace_baseline` is the L3 `source_selection` map as authored; `goal_implied`
    is one `(goal-id, source_selection)` pair per selected goal that sets clauses.
    CA10 lane discipline: a goal-implied nudge adjusts only the workspace BASELINE at
    M3 (step 17); it is never folded into the baseline here and never appears among
    M2 bound values of any other dimension.
    """

    workspace_baseline: Mapping[str, Any] | None = None
    goal_implied: tuple[tuple[str, Mapping[str, Any]], ...] = ()


@dataclass(frozen=True)
class ComposeResolution:
    """M2-compose output: everything `artifact-id` needs (§7.2), plus the M3 hand-off."""

    recipe: ResolvedEntry
    recipe_values: tuple[ValueBinding, ...]
    topic: BoundDimension
    persona: BoundDimension
    format: BoundDimension
    voice: BoundDimension
    goals: tuple[BoundDimension, ...]
    #: Which §12.3 chain slot selected the voice (test/report surface).
    voice_selected_by: str
    m3_inputs: M3Inputs
    warnings: tuple[ResolutionWarning, ...] = ()

    def deltas(self) -> dict[str, Any]:
        """The CA6 effective-delta view: per single-valued dimension the §7.2 delta
        map; goals as the `[[goal-id, delta], …]` pair-list."""
        return {
            "topic": self.topic.delta(),
            "persona": self.persona.delta(),
            "format": self.format.delta(),
            "voice": self.voice.delta(),
            "goals": [[g.entry_id, g.delta()] for g in self.goals],
        }

    def artifact_preimage(
        self,
        *,
        source_subset: Any,
        source_commit: Mapping[str, str],
        outline_digest: str | None = None,
    ) -> dict[str, Any]:
        """The canonical §7.2 artifact preimage — `ids.build_artifact_preimage`
        verbatim; mint with `ids.mint_artifact_id`.

        `outline_digest` defaults to `None` → the pre-DR-3 4-key preimage, byte-identical
        (the omit-when-absent zero-churn guarantee); a digest is threaded through only on
        the (later) outline drive/emit paths so the default resolution stays unchanged.
        """
        return build_artifact_preimage(
            topic=self.topic.binding(),
            persona=self.persona.binding(),
            format=self.format.binding(),
            voice=self.voice.binding(),
            goals=[g.binding() for g in self.goals],
            source_subset=source_subset,
            source_commit=source_commit,
            outline_digest=outline_digest,
        )


@dataclass(frozen=True)
class RenderResolution:
    """M2-render output for ONE deliverable coordinate set (§12.3 render bind stage)."""

    #: None when no platform is selected (Platform has no mandatory global — CA8).
    platform: BoundDimension | None
    language: BoundDimension
    output_type: BoundDimension
    presentation: BoundDimension
    #: The §12.3 two-tier-defaulted, M2-bound render attribute (consumed at §16).
    reconcile_strategy: str
    reconcile_strategy_provenance: str
    #: The projected, merged advisory map (CA9 advisory class — rides M2).
    advisories: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[ResolutionWarning, ...] = ()


# --- The cascade environment (one session's collected configuration; CA7) ------------------


class CascadeEnv:
    """One session's collected scope configuration + run overrides (collect-once, CA7).

    Construction is the single collection point: L2/L3 scope defaults load and
    validate (CA8 mandatory globals; entry selections resolve via M1 — loud; value
    bindings validate against their dimension schemas), and the override set passes
    the §21.4 schema-side guard. Per-item selections then bind at M2 via
    `resolve_compose`/`resolve_render`; nothing re-injects values later.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        workspace: str,
        overrides: OverrideSet | Any = None,
        now: date | None = None,
        window: WindowOracle | None = None,
    ) -> None:
        self.root = Path(root)
        self.workspace = workspace
        self.resolver = Resolver(self.root, workspace=workspace, now=now, window=window)
        self.overrides = (
            overrides if isinstance(overrides, OverrideSet) else collect_overrides(overrides)
        )

        global_path = self.root / INSTANCE_DEFAULTS_RELPATH
        if not global_path.is_file():
            raise MandatoryGlobalError(
                f"missing-mandatory-global: {global_path} does not exist — the instance "
                "MUST declare its global defaults (CA8, §12.3): voice, language, "
                "output_type (T10: copy instance/defaults.template.yaml)"
            )
        self.global_defaults = load_scope_defaults(global_path, scope=GLOBAL_SCOPE)
        missing = [
            key for key in MANDATORY_GLOBAL_KEYS if getattr(self.global_defaults, key) is None
        ]
        if missing:
            raise MandatoryGlobalError(
                f"missing-mandatory-global: {global_path}: missing {missing} — the "
                "mandatory-global set is Voice + Language + Output-type (CA8, §12.3): "
                "the baseline identity is declared, never an accidental fallback"
            )

        workspace_path = self.root / "workspaces" / workspace / WORKSPACE_DEFAULTS_FILENAME
        if workspace_path.is_file():
            self.workspace_defaults = load_scope_defaults(workspace_path, scope=WORKSPACE_SCOPE)
        else:  # L3 is an optional rung for every dimension (§12.3)
            self.workspace_defaults = ScopeDefaults.empty(WORKSPACE_SCOPE, str(workspace_path))

        self._seen_warning_keys: set[str] = set()
        self._validate_scope_defaults(self.global_defaults)
        self._validate_scope_defaults(self.workspace_defaults)
        self._validate_overrides()

    # -- warnings (one-time per session; §8/§12.6/§12.7) --------------------------------

    def warn(self, key: str, message: str) -> ResolutionWarning | None:
        """Emit a warning once per session per stable key; None when already fired."""
        if key in self._seen_warning_keys:
            return None
        self._seen_warning_keys.add(key)
        return ResolutionWarning(key=key, message=message)

    # -- collected-config validation -----------------------------------------------------

    def _validate_scope_defaults(self, defaults: ScopeDefaults) -> None:
        selections: list[tuple[str, str | None]] = [
            ("voices", defaults.voice.entry if defaults.voice else None),
            ("languages", defaults.language),
            ("output-types", defaults.output_type),
            ("presentations", defaults.presentation),
            ("topics", defaults.topic),
            ("personas", defaults.persona),
            ("formats", defaults.format),
        ]
        for collection, entry_id in selections:
            if entry_id is not None:
                self.resolver.resolve(collection, entry_id)
        for goal_id in defaults.goals or ():
            self.resolver.resolve("goals", goal_id)
        for binding in defaults.values:
            self.validate_value_binding(binding)

    def validate_value_binding(self, binding: ValueBinding) -> None:
        """Schema-side validation of one configured value binding (apply-at-bind
        counterpart of the parse-time shape checks)."""
        schema = self.resolver.schema(DIMENSION_COLLECTIONS[binding.dimension])
        spec = schema.attributes.get(binding.attribute)
        if spec is None:
            raise UndeclaredAttributeError(
                f"undeclared-attribute: {binding.where}: {binding.attribute!r} is not "
                f"declared by the {schema.collection!r} schema — schemas are closed "
                f"(SV3, §11.3); declared: {sorted(schema.attributes)}"
            )
        # Operator×type legality + operand typing — the single implementations.
        validate_combine_operator(spec.type, binding.op)
        validate_value(spec.type, binding.value, path=f"{binding.where}")

    def _validate_overrides(self) -> None:
        for override in self.overrides.items:
            schema = self.resolver.schema(DIMENSION_COLLECTIONS[override.dimension])
            validate_override_against_schema(override, schema)
            reason = UNBINDABLE_VALUE_BINDINGS.get((override.dimension, override.attribute))
            if reason is not None:
                raise OverrideError(f"invalid-override: {override.path}: {reason}")


# --- The fold ------------------------------------------------------------------------------

_BindTuple = tuple[str, str, Any, bool]  # (attribute, op, operand, explicit)


def _as_bind_tuples(bindings: tuple[ValueBinding, ...], dimension: str) -> list[_BindTuple]:
    return [(b.attribute, b.op, b.value, b.explicit) for b in bindings if b.dimension == dimension]


def _override_bind_tuples(overrides: tuple[Override, ...]) -> list[_BindTuple]:
    return [(o.attribute, o.op, o.value, o.explicit) for o in overrides]


def _fold_start(entry: ResolvedEntry) -> tuple[dict[str, Any], dict[str, str]]:
    """L0 (the canonicalized schema floor) + L1 (the M1-resolved effective entry, CA1)."""
    values = entry.defaults()
    provenance = {attr: RUNG_L0 for attr in values}
    for attr, value in entry.effective.items():
        spec = entry.schema.attributes[attr]
        values[attr] = combine_values(spec, values[attr], value, default_combine_op(spec))
        provenance[attr] = RUNG_L1
    return values, provenance


def _apply_rungs(
    entry: ResolvedEntry,
    values: dict[str, Any],
    provenance: dict[str, str],
    rungs: list[tuple[str, list[_BindTuple]]],
) -> None:
    """Fold rung bindings bottom-up (§12.2): higher rung wins, type-driven (§12.4),
    only for the attributes it declares. A fixed fold — no meta-cascade (CM3)."""
    for rung_label, binds in rungs:
        for attr, op, operand, explicit in binds:
            spec = entry.schema.attributes[attr]
            effective_op = op if explicit else default_combine_op(spec)
            values[attr] = combine_values(spec, values[attr], operand, effective_op)
            provenance[attr] = rung_label


def _bind_dimension(
    env: CascadeEnv,
    dimension: str,
    entry: ResolvedEntry,
    recipe_values: tuple[ValueBinding, ...],
) -> BoundDimension:
    """The standard six-rung fold for one dimension (platform adds the projection)."""
    values, provenance = _fold_start(entry)
    _apply_rungs(
        entry,
        values,
        provenance,
        [
            (RUNG_L2, _as_bind_tuples(env.global_defaults.values, dimension)),
            (RUNG_L3, _as_bind_tuples(env.workspace_defaults.values, dimension)),
            (RUNG_L5, _as_bind_tuples(recipe_values, dimension)),
            (RUNG_L6, _override_bind_tuples(env.overrides.for_dimension(dimension))),
        ],
    )
    return BoundDimension(dimension=dimension, entry=entry, values=values, provenance=provenance)


def _collect_entry_warnings(
    env: CascadeEnv, warnings: list[ResolutionWarning], *entries: ResolvedEntry | None
) -> None:
    for entry in entries:
        if entry is None:
            continue
        for note in entry.warnings:
            fired = env.warn(note.key, note.message)
            if fired is not None:
                warnings.append(fired)


def _nonempty(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


# --- Voice selection (the §12.3 chain; CA2 + §12.6 BO2) -------------------------------------


def _select_voice(
    env: CascadeEnv,
    persona: ResolvedEntry,
    recipe: ResolvedEntry,
    selection: RunSelection,
    warnings: list[ResolutionWarning],
) -> tuple[str, str]:
    """Resolve WHICH voice entry applies — the §12.3 chain, lowest to highest:

    L2 global (mandatory) < L3 workspace < persona.default_voice (CA2) <
    [flag strength a] < L5 recipe < [flag strength b — the bare-flag default] <
    L6 run < [flag strength c — opt-in hard-lock] (§12.6 BO2).
    """
    global_voice = env.global_defaults.voice
    assert global_voice is not None  # CA8-validated at env construction
    workspace_voice = env.workspace_defaults.voice

    # The most local flagged value arbitrates (§12.6; isolation §10).
    flagged: VoiceDefault | None = None
    if workspace_voice is not None and workspace_voice.authoritative:
        flagged = workspace_voice
    elif global_voice.authoritative:
        flagged = global_voice

    chain: list[tuple[str, str]] = [(RUNG_L2, global_voice.entry)]
    if workspace_voice is not None:
        chain.append((RUNG_L3, workspace_voice.entry))
    persona_voice = persona.effective.get("default_voice")
    if persona_voice:  # only a persona that SETS it inserts (module docstring)
        chain.append(("persona-default-voice", persona_voice))
    if flagged is not None and flagged.authoritative == "a":
        chain.append(("brand-authoritative-a", flagged.entry))
    recipe_voice = recipe.effective.get("voice")
    if recipe_voice:
        chain.append((RUNG_L5, recipe_voice))
    if flagged is not None and flagged.authoritative == "b":
        chain.append(("brand-authoritative-b", flagged.entry))
    if selection.voice:
        chain.append((RUNG_L6, selection.voice))
    if flagged is not None and flagged.authoritative == "c":
        chain.append(("brand-authoritative-c", flagged.entry))

    selected_by, voice_id = chain[-1]

    if flagged is not None and selection.voice and selection.voice != flagged.entry:
        strength = flagged.authoritative
        if strength in ("a", "b"):
            fired = env.warn(
                f"brand-voice-deviation:{env.workspace}:{flagged.entry}",
                (
                    f"run voice {selection.voice!r} deviates from the "
                    f"brand-authoritative voice {flagged.entry!r} (strength "
                    f"{strength}) — a warned, non-persisted one-off (§12.6)"
                ),
            )
        else:  # 'c': the hard-lock beats the run — surfaced, never silent (§3.1)
            fired = env.warn(
                f"brand-voice-hard-lock:{env.workspace}:{flagged.entry}",
                (
                    f"run voice {selection.voice!r} is beaten by the "
                    f"brand-authoritative hard-lock (strength c) voice "
                    f"{flagged.entry!r} (§12.6)"
                ),
            )
        if fired is not None:
            warnings.append(fired)

    return voice_id, selected_by


# --- M2-compose (content dimensions → artifact identity; §12.3) -----------------------------


def resolve_compose(env: CascadeEnv, selection: RunSelection) -> ComposeResolution:
    """Bind the content dimensions for one item (M2-compose → `artifact-id`).

    Selection cascade per dimension (most local wins): run pick > recipe slot >
    workspace default (> the recipe-schema L0 floor for persona/format). Topic has no
    floor — a recipe generates nothing without a topic (§12.3), so an unresolvable
    topic is a typed `SelectionError`. Every id resolves via M1 — loud (§11.1).
    """
    warnings: list[ResolutionWarning] = []
    recipe = env.resolver.resolve("recipes", selection.recipe)
    recipe_values = parse_value_bindings(
        recipe.effective.get("values"), where=f"recipes/{recipe.id}"
    )
    for binding in recipe_values:
        env.validate_value_binding(binding)

    recipes_schema = env.resolver.schema("recipes")

    topic_id = (
        _nonempty(selection.topic)
        or _nonempty(recipe.effective.get("topic"))
        or env.workspace_defaults.topic
    )
    if topic_id is None:
        raise SelectionError(
            "invalid-selection: no topic anywhere in the selection cascade (run, "
            f"recipe {recipe.id!r}, workspace default) — Topic's selection is required "
            "(§12.3); a recipe generates nothing without a topic"
        )
    persona_id = (
        selection.persona
        or recipe.effective.get("persona")
        or env.workspace_defaults.persona
        or recipes_schema.attributes["persona"].default
    )
    format_id = (
        selection.format
        or recipe.effective.get("format")
        or env.workspace_defaults.format
        or recipes_schema.attributes["format"].default
    )
    if selection.goals is not None:
        goal_ids = selection.goals
        if len(set(goal_ids)) != len(goal_ids):
            raise SelectionError(
                f"invalid-selection: duplicate goal id in run goal-set {goal_ids!r} — "
                "the goal-set is a set (§5.2); loud, never silently deduped"
            )
    elif "goals" in recipe.effective:
        goal_ids = tuple(recipe.effective["goals"])
    elif env.workspace_defaults.goals is not None:
        goal_ids = env.workspace_defaults.goals
    elif env.global_defaults.goals is not None:
        goal_ids = env.global_defaults.goals
    else:
        goal_ids = ()  # the L0 baseline set (§12.3): empty

    topic = env.resolver.resolve("topics", topic_id)
    persona = env.resolver.resolve("personas", persona_id)
    format_entry = env.resolver.resolve("formats", format_id)
    goal_entries = tuple(env.resolver.resolve("goals", goal_id) for goal_id in goal_ids)

    voice_id, voice_selected_by = _select_voice(env, persona, recipe, selection, warnings)
    voice = env.resolver.resolve("voices", voice_id)

    if env.overrides.for_dimension("goal") and not goal_entries:
        raise OverrideError(
            "invalid-override: goal.* overrides with an empty goal-set — an override "
            "binds a declared attribute of an already-selected entry only (§21.4 API5)"
        )

    _collect_entry_warnings(
        env, warnings, recipe, topic, persona, format_entry, voice, *goal_entries
    )

    bound = {
        "topic": _bind_dimension(env, "topic", topic, recipe_values),
        "persona": _bind_dimension(env, "persona", persona, recipe_values),
        "format": _bind_dimension(env, "format", format_entry, recipe_values),
        "voice": _bind_dimension(env, "voice", voice, recipe_values),
    }
    goals_bound = tuple(_bind_dimension(env, "goal", goal, recipe_values) for goal in goal_entries)

    m3_inputs = M3Inputs(
        workspace_baseline=copy.deepcopy(env.workspace_defaults.source_selection),
        goal_implied=tuple(
            (goal.id, copy.deepcopy(goal.effective["source_selection"]))
            for goal in goal_entries
            if goal.effective.get("source_selection")
        ),
    )

    return ComposeResolution(
        recipe=recipe,
        recipe_values=recipe_values,
        topic=bound["topic"],
        persona=bound["persona"],
        format=bound["format"],
        voice=bound["voice"],
        goals=goals_bound,
        voice_selected_by=voice_selected_by,
        m3_inputs=m3_inputs,
        warnings=tuple(warnings),
    )


# --- M2-render (rendering dimensions → deliverable coordinates; §12.3) ----------------------


def _single_pin(recipe: ResolvedEntry, attribute: str) -> str | None:
    pins = recipe.effective.get(attribute) or []
    if len(pins) > 1:
        raise AmbiguousSelectionError(
            f"ambiguous-rendering-selection: recipe {recipe.id!r} pins "
            f"{sorted(pins)!r} for {attribute!r} — multiple pins are a rendering "
            "fanout (§5.1); pass ONE explicit coordinate per resolution (fanout "
            "enumeration is plan step 19)"
        )
    return pins[0] if pins else None


def resolve_render(
    env: CascadeEnv, compose: ComposeResolution, selection: RunSelection
) -> RenderResolution:
    """Bind the rendering dimensions for ONE deliverable coordinate set (M2-render).

    Coordinate resolution per §12.3: platform = run pick > recipe pin > none (no
    mandatory global — CA8); language = run > pin > L3 > L2 (mandatory); output-type =
    run > pin > L3 > platform-implied WEAK default > L2 (mandatory beneath the weak
    default; any explicit L3/L5/L6 value beats it); presentation = run > pin > L3 >
    L2 > the `plain` floor (PD7).
    """
    warnings: list[ResolutionWarning] = []
    recipe = compose.recipe

    platform_id = selection.platform or _single_pin(recipe, "platforms")
    platform_entry = (
        env.resolver.resolve("platforms", platform_id) if platform_id is not None else None
    )

    language_id = (
        selection.language
        or _single_pin(recipe, "languages")
        or env.workspace_defaults.language
        or env.global_defaults.language
    )
    assert language_id is not None  # CA8-validated at env construction

    explicit_output_type = (
        selection.output_type
        or _single_pin(recipe, "output_types")
        or env.workspace_defaults.output_type
    )
    if explicit_output_type is not None:
        output_type_id = explicit_output_type
    else:
        weak = (
            _nonempty(platform_entry.effective.get("default_output_type"))
            if platform_entry is not None
            else None
        )
        output_type_id = weak or env.global_defaults.output_type
    assert output_type_id is not None  # CA8-validated at env construction

    presentation_id = (
        selection.presentation
        or _single_pin(recipe, "presentations")
        or env.workspace_defaults.presentation
        or env.global_defaults.presentation
        or PRESENTATION_FLOOR_ENTRY  # PD7: the honest floor (§12.3)
    )

    language = env.resolver.resolve("languages", language_id)
    output_type = env.resolver.resolve("output-types", output_type_id)
    presentation = env.resolver.resolve("presentations", presentation_id)

    if platform_entry is None and env.overrides.for_dimension("platform"):
        paths = [o.path for o in env.overrides.for_dimension("platform")]
        raise OverrideError(
            f"invalid-override: {paths} with no platform selected — an override binds "
            "a declared attribute of an ALREADY-SELECTED entry only (§21.4 API5)"
        )

    _collect_entry_warnings(env, warnings, platform_entry, language, output_type, presentation)

    platform_bound: BoundDimension | None = None
    if platform_entry is not None:
        platform_bound = _bind_platform(
            env, platform_entry, compose.format.entry_id, compose.recipe_values, warnings
        )
        strategy = platform_bound.values["reconcile_strategy"]
        strategy_provenance = platform_bound.provenance["reconcile_strategy"]
        advisories = copy.deepcopy(platform_bound.values.get("advisory_norms") or {})
    else:
        # The no-platform edge (step-14 carry-forward): the L0 floor is the platforms
        # COLLECTION MANIFEST's schema default — it exists independent of any entry.
        spec = env.resolver.schema("platforms").attributes["reconcile_strategy"]
        strategy = spec.default
        strategy_provenance = RUNG_L0
        advisories = {}

    return RenderResolution(
        platform=platform_bound,
        language=_bind_dimension(env, "language", language, compose.recipe_values),
        output_type=_bind_dimension(env, "output-type", output_type, compose.recipe_values),
        presentation=_bind_dimension(env, "presentation", presentation, compose.recipe_values),
        reconcile_strategy=strategy,
        reconcile_strategy_provenance=strategy_provenance,
        advisories=advisories,
        warnings=tuple(warnings),
    )


def _bind_platform(
    env: CascadeEnv,
    entry: ResolvedEntry,
    format_id: str,
    recipe_values: tuple[ValueBinding, ...],
    warnings: list[ResolutionWarning],
) -> BoundDimension:
    """The platform fold: the standard rungs + the per-format projection below L5
    (§12.3), advisory-deviation detection (CA9), and the never-M2 attribute strip."""
    values, provenance = _fold_start(entry)
    _apply_rungs(
        entry,
        values,
        provenance,
        [
            (RUNG_L2, _as_bind_tuples(env.global_defaults.values, "platform")),
            (RUNG_L3, _as_bind_tuples(env.workspace_defaults.values, "platform")),
            (RUNG_PROJECTION, _projection_binds(entry, format_id)),
        ],
    )
    # CA9 deviation baseline: the platform's projected advisory values, pre-L5.
    projected_advisories = copy.deepcopy(values.get("advisory_norms") or {})
    _apply_rungs(
        entry,
        values,
        provenance,
        [
            (RUNG_L5, _as_bind_tuples(recipe_values, "platform")),
            (RUNG_L6, _override_bind_tuples(env.overrides.for_dimension("platform"))),
        ],
    )
    final_advisories = values.get("advisory_norms") or {}
    for key, value in final_advisories.items():
        if key in projected_advisories and projected_advisories[key] != value:
            fired = env.warn(
                f"advisory-deviation:{entry.id}:{key}",
                (
                    f"recipe/run deviates from the {entry.id!r} advisory norm "
                    f"{key!r} (projected {projected_advisories[key]!r} → {value!r}) — "
                    "advisory values ride M2 and may be deviated from, warned once "
                    "(CA9, §12.7)"
                ),
            )
            if fired is not None:
                warnings.append(fired)
    # Hard limits and projection/doc attributes never enter M2's bound values (CA9).
    for attr in PLATFORM_UNBOUND_ATTRIBUTES:
        values.pop(attr, None)
        provenance.pop(attr, None)
    return BoundDimension(dimension="platform", entry=entry, values=values, provenance=provenance)


def _projection_binds(entry: ResolvedEntry, format_id: str) -> list[_BindTuple]:
    """Platform's per-format cross-dimension projection (§12.3): the advisory
    refinement map-merges into `advisory_norms`; the per-(format × platform) strategy
    default binds `reconcile_strategy` — both below L5, exactly like configured
    values (never operators, never new attributes)."""
    binds: list[_BindTuple] = []
    advisories = entry.effective.get("format_advisories") or {}
    projected = advisories.get(format_id)
    if isinstance(projected, Mapping) and projected:
        binds.append(("advisory_norms", "replace", projected, False))  # map ⇒ key-wise
    strategy_defaults = entry.effective.get("reconcile_strategy_defaults") or {}
    strategy = strategy_defaults.get(format_id)
    if strategy is not None:
        binds.append(("reconcile_strategy", "replace", strategy, False))
    return binds
