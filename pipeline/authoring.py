"""Shared authoring core (design §8; authoring layer D5–D10). PURE + REUSABLE.

`pipeline recipe new` (C2b), `entry new` (C3), and `--save-selection` (C5) all shape the
SAME small edit over a base binding: you PICK an entry (an axis flag replaces that slot's
set), you TWEAK a value (`--set` binds a `<dim>.<attr>` value), or you CLEAR a slot/binding
(`--unset`). This module owns that grammar, the `base ⊕ edits` merge it drives, the
conforming-recipe serializer, the all-slot provenance inference, and the overwrite guard —
ALL as pure functions the verb layers call. It registers NO invoke verb and touches NO
identity surface (a recipe name never enters `build_artifact_preimage`; a saved recipe run
resolves byte-identically to the same flags inlined, D10/W4): it only shapes and serializes
CONFIG.

The two operations map to the two design walls (§21.4). PICK an ENTRY (M1 selection: which
persona/format/platform) — mentioning an axis REPLACES the base's set for that axis, exactly
as the runtime cascade already replaces per axis (`request.X or pinned`, `fanout.py:451-454`;
combo-beats-recipe, `plan.py:300-308`). TWEAK a VALUE (an L5 configured value, never an
"override" on a persisted file, §12.5) via the existing `--set` compile
(`normalize.compile_overrides`), structurally re-validated through `overrides.collect_overrides`.
`--unset` spans both walls, disambiguated by SEGMENT COUNT (§2 of the ratified design): one
segment clears an axis SLOT, two segments clear a value BINDING. It reuses only the *idea*
`path.split(".")`, NEVER `overrides._override_from_bind` — that guard RAISES on a 1-segment
path ("names a whole dimension … `selection`, an M1 input", `overrides.py:139-144`), so it
cannot serve the axis-clear case (the S1 fix).

Wiring, never duplication: the §7.4 slug alphabet is `attrtypes.validate_value` (the single
implementation every sibling `_require_slug` wraps); the value-tweak grammar is
`normalize.compile_overrides` + `overrides.collect_overrides`; the dimension/reserved
vocabularies are `m1.DIMENSION_COLLECTIONS` + `schema.RESERVED_ATTRIBUTE_NAMES`; the workspace
isolation guard is `workspace_name.validate_workspace_path` (rule 2/§23); the pinned dumper is the
loader `yamlio.make_loader` runs in reverse. A LEAF module — it imports no identity/plan/
cascade code and nothing in `pipeline/` imports it yet (C2b is the first consumer).
"""

from __future__ import annotations

import copy
import io
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.api.normalize import compile_overrides
from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value
from pipeline.entries import (
    INSTANCE_ID_PREFIX,
    PROVENANCE_FRAMEWORK,
    PROVENANCE_INSTANCE,
    Entry,
    load_entry,
)
from pipeline.fanout import CONTENT_AXES, RENDERING_AXES
from pipeline.layout import registry_dir
from pipeline.m1 import DIMENSION_COLLECTIONS
from pipeline.overrides import collect_overrides
from pipeline.schema import (
    RESERVED_ATTRIBUTE_NAMES,
    SCHEMA_FILENAME,
    Schema,
    load_schema,
)
from pipeline.workspace_name import validate_workspace_path
from pipeline.yamlio import make_loader

__all__ = [
    "AXIS_TO_SLOT",
    "ENTRY_REFERENCING_SLOTS",
    "RECIPE_COLLECTION",
    "RENDER_COORDINATE_SLOTS",
    "SELECTION_COLLECTION",
    "SELECTION_CONTENT_SLOTS",
    "SET_VALUED_SLOTS",
    "SINGLE_VALUED_SLOTS",
    "VALUES_SLOT",
    "AuthoringError",
    "EditSet",
    "RecipeTarget",
    "SelectionTarget",
    "build_edit_set",
    "bundle_from_entry",
    "ensure_writable",
    "infer_provenance",
    "infer_selection_provenance",
    "load_recipe_schema",
    "load_selection",
    "load_selection_schema",
    "merge_bundle",
    "resolve_recipe_target",
    "resolve_selection_target",
    "serialize_recipe",
    "serialize_selection",
    "write_recipe",
    "write_selection",
]

# --- The recipe binding vocabulary (design §8; recipes/_schema.yaml) ----------------------

#: The registry root recipes live in (framework mechanism).
RECIPE_COLLECTION = "recipes"

#: The single-valued entry-referencing recipe slots (a recipe binds ONE per content
#: dimension, §8): text-ref (`topic`/`lexicon`/`diagram_style`) + ref (`persona`/`format`/
#: `voice`). A pick states one id; several is a loud error (a recipe is not a fan-out).
SINGLE_VALUED_SLOTS = ("topic", "lexicon", "diagram_style", "persona", "format", "voice")

#: The set-valued entry-referencing recipe slots (a recipe MAY pin several, §8): the goal-set
#: + the four rendering pins. A pick states the whole set (mention → REPLACE, §2).
SET_VALUED_SLOTS = ("goals", "platforms", "languages", "output_types", "presentations")

#: The entry-referencing PICK slots (design D9), in schema-declared order — the recipe slots
#: that name entry ids directly. The `values` map is NOT a pick slot (it binds attribute VALUES
#: over already-selected entries, the M1 wall §21.4) — but a values OPERAND can itself be an
#: entry id: `persona.default_voice` is `ref`-typed, so `--set persona.default_voice=x-...`
#: puts a client id in the map. So `infer_provenance` scans the values map TOO (it is a
#: provenance carrier); this list is only the direct-pick surface the merge replaces.
ENTRY_REFERENCING_SLOTS = SINGLE_VALUED_SLOTS + SET_VALUED_SLOTS

#: The recipe's L5 configured-values map (§8/§12.5) — the TWEAK target. NOT "overrides": a
#: persisted scope holds configuration, never the ephemeral L6 mechanism (§12.5 terminology).
VALUES_SLOT = "values"

_SINGLE = frozenset(SINGLE_VALUED_SLOTS)
_SET = frozenset(SET_VALUED_SLOTS)
_SLOTS = frozenset(ENTRY_REFERENCING_SLOTS)

#: A fan-out axis key (the `SelectionRequest`/normalizer surface) → its recipe slot. Content
#: axes are PLURAL at fan-out (`fanout.CONTENT_AXES`) but SINGULAR in a recipe; rendering axes
#: (`fanout.RENDERING_AXES`) and `goals` map to themselves. `lexicon`/`diagram_style` have no
#: fan-out axis (a recipe binds them; they are not run-multi-selected) — a caller names those
#: slots directly. Consumers (C2b/C5) translate their argparse dests through this map; the
#: router below also accepts a bare slot name.
AXIS_TO_SLOT: dict[str, str] = {
    # Content axes are the plural fan-out keys; a recipe binds ONE, so the slot is singular
    # (`topics` → `topic`, …) — derived from `CONTENT_AXES` so it tracks the SSOT.
    **{axis: axis[:-1] for axis in CONTENT_AXES},
    **{axis: axis for axis in RENDERING_AXES},
    "goals": "goals",
}

#: The §7.4 slug alphabet's single implementation (attrtypes' `ref`), exactly as every sibling
#: `_require_slug` (`entries`/`fanout`/`schema`) wraps it — the alphabet is never re-spelled.
_REF_SPEC = AttrTypeSpec(kind="ref")


class AuthoringError(ValueError):
    """A loud, typed authoring refusal — never a silent repair (§3.1)."""

    code = "invalid-authoring"


def _require_slug(value: object, what: str) -> str:
    """Refuse anything that is not a §7.4 entry-id slug (loud), via the ONE validator."""
    try:
        validate_value(_REF_SPEC, value)
    except ValueValidationError as exc:
        raise AuthoringError(
            f"invalid-authoring: {what} {value!r} is not a §7.4 entry-id slug "
            "([a-z0-9-], 1-40 chars, no leading/trailing '-'; §11.4 `x-` prefix included)"
        ) from exc
    assert isinstance(value, str)
    return value


# --- The edit-verb router: PICK / TWEAK / CLEAR (the unified grammar, §2) ------------------


@dataclass(frozen=True)
class EditSet:
    """One normalized edit over a base: what to PICK, TWEAK, and CLEAR.

    - `picks` — slot → the stated id set (mention → REPLACE that slot, §2).
    - `tweaks` — the compiled `--set` values map delta (`{"voice.formality": 2,
      "format.tags+": ["x"]}`), values-only (the M1 wall holds, §21.4).
    - `clears_axis` — slots to drop (one-segment `--unset`).
    - `clears_value` — value BINDING paths to drop from the values map (two-segment `--unset`).
    """

    picks: dict[str, tuple[str, ...]] = field(default_factory=dict)
    tweaks: dict[str, Any] = field(default_factory=dict)
    clears_axis: frozenset[str] = frozenset()
    clears_value: frozenset[str] = frozenset()


def _resolve_pick_slot(key: str) -> str:
    """A pick/clear key → its recipe slot. Accepts a bare slot name or a fan-out axis key."""
    if key in _SLOTS:
        return key
    if key in AXIS_TO_SLOT:
        return AXIS_TO_SLOT[key]
    raise AuthoringError(
        f"invalid-authoring: {key!r} is not a recipe slot — pickable/clearable slots are "
        f"{sorted(_SLOTS)} (or the fan-out axis keys {sorted(AXIS_TO_SLOT)})"
    )


def _base_value_path(key: str) -> str:
    """The bare `<dim>.<attr>` of a values-map key (strip the `+` union sugar, §13.2)."""
    return key[:-1] if key.endswith("+") else key


def _route_unset(unset: Sequence[str]) -> tuple[set[str], set[str]]:
    """`--unset` → (axis-slot clears, value-binding clears), by SEGMENT COUNT [S1 fix].

    One segment = an axis slot (`--unset voice`, `--unset platforms`); two = a value binding
    (`--unset voice.formality`). Reuses the `path.split(".")` IDEA and the SAME dimension/
    reserved vocabularies the override guard checks — but never CALLS `_override_from_bind`,
    which raises on the 1-segment axis-clear case (`overrides.py:139-144`). Accepts a comma
    list per token (`--unset a,b`, mirroring `compile_overrides` comma handling).
    """
    clears_axis: set[str] = set()
    clears_value: set[str] = set()
    for raw in unset:
        if not isinstance(raw, str):
            raise AuthoringError(f"invalid-authoring: each --unset is a string, got {raw!r}")
        for token in (t.strip() for t in raw.split(",")):
            if not token:
                raise AuthoringError(f"invalid-authoring: empty --unset path in {raw!r}")
            segments = token.split(".")
            if len(segments) == 1:
                clears_axis.add(_resolve_pick_slot(segments[0]))
            elif len(segments) == 2:
                dimension, attribute = segments
                if dimension not in DIMENSION_COLLECTIONS:
                    raise AuthoringError(
                        f"invalid-authoring: --unset {token!r}: {dimension!r} is not a "
                        f"dimension — a value binding is `<dimension>.<attribute>` (§13.2/§21.4); "
                        f"dimensions: {sorted(DIMENSION_COLLECTIONS)}"
                    )
                if not attribute or attribute in RESERVED_ATTRIBUTE_NAMES:
                    raise AuthoringError(
                        f"invalid-authoring: --unset {token!r}: {attribute!r} is not a bindable "
                        "attribute (envelope/mechanism vocabulary: "
                        f"{sorted(RESERVED_ATTRIBUTE_NAMES)})"
                    )
                clears_value.add(token)
            else:
                raise AuthoringError(
                    f"invalid-authoring: --unset {token!r} has {len(segments)} segments — an axis "
                    "clear is one segment, a value clear is two (§2)"
                )
    return clears_axis, clears_value


def build_edit_set(
    *,
    picks: Mapping[str, Sequence[str]] | None = None,
    set_entries: Sequence[str] = (),
    unset: Sequence[str] = (),
) -> EditSet:
    """Parse raw CLI-shaped inputs into a normalized `EditSet` (the router).

    `picks` maps a slot/axis key to the stated id list (repeated flags = the accumulated set).
    `set_entries` is the raw `--set` strings (compiled + structurally re-validated). `unset`
    is the raw `--unset` args (routed by segment count). Every id is slug-validated loud; a
    slot both picked and axis-cleared, or a path both tweaked and value-cleared, is refused.
    """
    resolved_picks: dict[str, tuple[str, ...]] = {}
    for key, ids in (picks or {}).items():
        slot = _resolve_pick_slot(key)
        seq = tuple(_require_slug(v, f"--{key} value") for v in ids)
        if not seq:
            continue
        if slot in resolved_picks:
            raise AuthoringError(
                f"invalid-authoring: slot {slot!r} is picked twice (via {key!r} and another "
                "axis key) — ambiguous, refused (never last-wins, §3.1)"
            )
        resolved_picks[slot] = seq

    # TWEAK: the existing `--set` compile → the values-map delta; then the STRUCTURAL M1 guard
    # (segment count, dimension, reserved names) via collect_overrides — loud early. The full
    # schema type-check is deferred to run (it needs the selected entries' schemas).
    tweaks = compile_overrides(list(set_entries))
    collect_overrides(tweaks)

    clears_axis, clears_value = _route_unset(unset)

    for slot in clears_axis:
        if slot in resolved_picks:
            raise AuthoringError(
                f"invalid-authoring: slot {slot!r} is both picked and --unset — contradictory "
                "(§3.1); state one intent"
            )
    tweak_paths = {_base_value_path(key) for key in tweaks}
    for path in clears_value:
        if path in tweak_paths:
            raise AuthoringError(
                f"invalid-authoring: value {path!r} is both --set and --unset — contradictory "
                "(§3.1); state one intent"
            )

    return EditSet(
        picks=resolved_picks,
        tweaks=tweaks,
        clears_axis=frozenset(clears_axis),
        clears_value=frozenset(clears_value),
    )


# --- The base ⊕ edits merge (THE primitive C2b derive AND C5c `base ⊕ deltaᵢ` reuse) -------


def _slot_binding(slot: str, ids: tuple[str, ...]) -> Any:
    """Coerce a picked id set to its slot's cardinality: a scalar (single) or a list (set)."""
    if slot in _SINGLE:
        if len(ids) != 1:
            raise AuthoringError(
                f"invalid-authoring: {slot!r} is a single-valued slot — a recipe binds ONE "
                f"{slot} (§8), got {len(ids)}: {list(ids)}; state one id"
            )
        return ids[0]
    if len(set(ids)) != len(ids):
        raise AuthoringError(
            f"invalid-authoring: duplicate id in {slot} {list(ids)} — a set is loud, never "
            "silently deduped (§5.2)"
        )
    return list(ids)


def _normalized_bundle(base: Mapping[str, Any]) -> dict[str, Any]:
    """A deep copy of a base bundle with unknown keys refused and set slots as lists."""
    result: dict[str, Any] = {}
    for key, value in base.items():
        if key == VALUES_SLOT:
            result[key] = copy.deepcopy(value)
        elif key in _SET:
            result[key] = list(value)
        elif key in _SINGLE:
            result[key] = value
        else:
            raise AuthoringError(
                f"invalid-authoring: {key!r} is not a recipe binding slot — a bundle holds only "
                f"{sorted(_SLOTS)} + {VALUES_SLOT!r}"
            )
    return result


def merge_bundle(base: Mapping[str, Any], edits: EditSet) -> dict[str, Any]:
    """Apply an `EditSet` over a base bundle → the effective bundle (design §2, §12.3).

    PICK replaces the whole slot (mirroring the runtime per-axis `request.X or pinned`,
    `fanout.py:451-454`, and combo-beats-recipe, `plan.py:300-308`); CLEAR drops the slot or
    the value binding (falls through to the cascade floor); TWEAK sets the value path in the
    values map. Reference-faithful: bindings are ids, never materialized floors — a base edit
    surfaces honestly. THIS is the exact merge C5c's `base ⊕ deltaᵢ` selection-load reuses.
    """
    result = _normalized_bundle(base)
    for slot, ids in edits.picks.items():
        result[slot] = _slot_binding(slot, ids)
    for slot in edits.clears_axis:
        result.pop(slot, None)

    values = dict(result.get(VALUES_SLOT) or {})
    for key, value in edits.tweaks.items():
        values[key] = copy.deepcopy(value)
    for path in edits.clears_value:
        values.pop(path, None)
        values.pop(f"{path}+", None)  # clear both the replace and the `+` union spellings
    if values:
        result[VALUES_SLOT] = values
    else:
        result.pop(VALUES_SLOT, None)
    return result


def bundle_from_entry(entry: Entry) -> dict[str, Any]:
    """The base bundle of a parsed recipe entry: its explicitly-SET slots (a partial, §8)."""
    return _normalized_bundle(entry.attributes)


# --- Provenance inference over all entry-referencing slots (design D9) --------------------


def _values_carry_instance_id(operand: Any) -> bool:
    """True if any operand inside a values map is an `x-` (reserved instance) string.

    A values binding CAN carry an entry id — `persona.default_voice` is `ref`-typed
    (`personas/_schema.yaml`), so `--set persona.default_voice=x-client-voice` lands a client
    id in the map. Conservatively, ANY `x-`-prefixed string operand marks the bundle
    instance-scoped: `x-` is the RESERVED instance namespace (§11.4) and must never appear in a
    framework recipe, whatever the attribute's type — this catches every present and future
    ref-typed (and text-ref) attribute without resolving schemas (the function stays a leaf).
    Over-flagging an odd `x-` free-text value routes it to the workspace, the safe direction
    (rule 4). Recurses through list/map operands (the §13.2 union/`{combine,add}` shapes).
    """
    if isinstance(operand, str):
        return operand.startswith(INSTANCE_ID_PREFIX)
    if isinstance(operand, Mapping):
        return any(_values_carry_instance_id(v) for v in operand.values())
    if isinstance(operand, (list, tuple)):
        return any(_values_carry_instance_id(v) for v in operand)
    return False


def infer_provenance(bundle: Mapping[str, Any]) -> str:
    """`framework` unless ANY binding is `x-`-scoped → `instance` (§11.4).

    Scans every direct-pick slot in `ENTRY_REFERENCING_SLOTS` (topic, lexicon, diagram_style,
    persona, format, voice + the goal-set and rendering pins) AND every operand in the `values`
    map (a values operand can be a ref-typed entry id — `persona.default_voice`). Any client/
    instance entry carries the reserved `x-` id prefix by construction (§11.4, enforced by
    `entries.parse_entry`), so the prefix IS the structural signal — no registry resolution
    needed (this stays a leaf). Closes the rule-4 leak of a client id reaching public via
    `values`.
    """
    for slot in ENTRY_REFERENCING_SLOTS:
        if slot not in bundle:
            continue
        value = bundle[slot]
        ids = value if isinstance(value, (list, tuple)) else (value,)
        for entry_id in ids:
            if isinstance(entry_id, str) and entry_id.startswith(INSTANCE_ID_PREFIX):
                return PROVENANCE_INSTANCE
    if _values_carry_instance_id(bundle.get(VALUES_SLOT)):
        return PROVENANCE_INSTANCE
    return PROVENANCE_FRAMEWORK


@dataclass(frozen=True)
class RecipeTarget:
    """Where a recipe writes: its id, inferred provenance, home path, and workspace (if any)."""

    recipe_id: str
    provenance: str
    path: Path
    workspace: str | None


def resolve_recipe_target(
    root: str | Path,
    recipe_id: str,
    bundle: Mapping[str, Any],
    *,
    user: str | None = None,
    workspace: str | None = None,
) -> RecipeTarget:
    """Infer provenance from the bindings and compute the home path — REFUSING a client
    binding into public (rule 4, §10).

    A client/`x-` binding forces `instance`: the id MUST carry `x-` and a workspace MUST be
    named — otherwise the write is refused (never leaks instance config into the public repo).
    A framework-only bundle homes public (`recipes/<id>.md`); an `x-` id homes under the
    workspace (`workspaces/<ws>/recipes/x-<id>.md`) via the isolation guard.
    """
    _require_slug(recipe_id, "recipe id")
    binding_provenance = infer_provenance(bundle)
    id_is_instance = recipe_id.startswith(INSTANCE_ID_PREFIX)

    if binding_provenance == PROVENANCE_INSTANCE and not id_is_instance:
        raise AuthoringError(
            f"invalid-authoring: recipe {recipe_id!r} binds a client/instance "
            f"('{INSTANCE_ID_PREFIX}') entry but is not an instance id — a client-binding recipe "
            f"takes an '{INSTANCE_ID_PREFIX}' id under a --workspace, never the public repo "
            "(rule 4, §10)"
        )

    provenance = (
        PROVENANCE_INSTANCE
        if (id_is_instance or binding_provenance == PROVENANCE_INSTANCE)
        else PROVENANCE_FRAMEWORK
    )
    root = Path(root)
    if provenance == PROVENANCE_INSTANCE:
        if not workspace or not user:
            raise AuthoringError(
                f"invalid-authoring: instance recipe {recipe_id!r} requires a --user + --workspace "
                "home (instance config lives under users/<user>/workspaces/<client>/, rule 2/§10)"
            )
        home = (
            validate_workspace_path(root, user, workspace)
            / RECIPE_COLLECTION
            / f"{recipe_id}.md"
        )
        return RecipeTarget(recipe_id, provenance, home, workspace)

    home = registry_dir(root, RECIPE_COLLECTION) / f"{recipe_id}.md"
    return RecipeTarget(recipe_id, provenance, home, None)


# --- The conforming-recipe serializer (envelope + SET slots only; §11.1/§13.4) ------------


def _framework_root() -> Path:
    """The framework repo root — derived from this module's location, cwd-independent."""
    return Path(__file__).resolve().parents[1]


def load_recipe_schema() -> Schema:
    """Load the framework recipe schema (`recipes/_schema.yaml`) — the serializer's SSOT."""
    return load_schema(registry_dir(_framework_root(), RECIPE_COLLECTION) / SCHEMA_FILENAME)


def _dump_yaml(data: Mapping[str, Any]) -> str:
    """Serialize frontmatter with the pinned G4 loader in reverse: block style, insertion
    order preserved, no line wrapping — the same `YAML(typ='safe', pure=True)` the loader
    pins (Norway-safe), never a second serializer (`migration.py:802-811` precedent)."""
    dumper = make_loader()
    dumper.default_flow_style = False
    dumper.width = 4096
    dumper.representer.sort_base_mapping_type_on_output = False
    buffer = io.StringIO()
    dumper.dump(dict(data), buffer)
    return buffer.getvalue()


def _default_body(recipe_id: str) -> str:
    return (
        f"# {recipe_id} — recipe entry\n\n"
        "Authored by `pipeline recipe new`. Binds only the slots it SETS; unset slots fall "
        "through the workspace/global/entry/schema cascade (§8, §12.2).\n"
    )


def _validate_namespace(recipe_id: str, provenance: str) -> None:
    """The §11.4 `x-` ⇔ provenance coupling, exactly as `entries.parse_entry` enforces it."""
    is_x = recipe_id.startswith(INSTANCE_ID_PREFIX)
    if provenance == PROVENANCE_INSTANCE and not is_x:
        raise AuthoringError(
            f"invalid-authoring: instance recipe {recipe_id!r} must carry the "
            f"'{INSTANCE_ID_PREFIX}' id prefix (§11.4)"
        )
    if provenance == PROVENANCE_FRAMEWORK and is_x:
        raise AuthoringError(
            f"invalid-authoring: framework recipe {recipe_id!r} must not carry the "
            f"'{INSTANCE_ID_PREFIX}' prefix — the framework owns the unprefixed namespace (§11.4)"
        )


def serialize_recipe(
    bundle: Mapping[str, Any],
    *,
    recipe_id: str,
    provenance: str,
    body: str | None = None,
    schema: Schema | None = None,
) -> str:
    """Render a schema-conforming `recipes/<id>.md`: envelope + only the SET slots.

    Unset slots are OMITTED so they fall through the cascade (a recipe binds only what it
    sets, `recipes/_schema.yaml:9-13`). The bundle is closed-schema validated (SV3) before
    serialization, so the emitted file lints green and re-parses to the same bindings.
    """
    schema = schema or load_recipe_schema()
    _require_slug(recipe_id, "recipe id")
    if provenance not in (PROVENANCE_FRAMEWORK, PROVENANCE_INSTANCE):
        raise AuthoringError(
            f"invalid-authoring: provenance must be {PROVENANCE_FRAMEWORK!r} or "
            f"{PROVENANCE_INSTANCE!r} (§10), got {provenance!r}"
        )
    _validate_namespace(recipe_id, provenance)

    normalized = _normalized_bundle(bundle)
    # Closed-schema validation (SV3, §11.3): reject any undeclared/typed-wrong binding here so
    # the written file is conforming by construction (the emitted set slots are lists, §11.1).
    schema.validate_attribute_values(normalized, where=f"{RECIPE_COLLECTION}/{recipe_id}")

    frontmatter: dict[str, Any] = {
        "id": recipe_id,
        "provenance": provenance,
        "schema_version": schema.schema_version,
    }
    for slot in schema.attributes:  # schema-declared order → deterministic frontmatter
        if slot in normalized:
            frontmatter[slot] = normalized[slot]

    body_text = _default_body(recipe_id) if body is None else body
    text = "---\n" + _dump_yaml(frontmatter) + "---\n"
    if body_text:
        text += body_text if body_text.endswith("\n") else body_text + "\n"
    return text


# --- The overwrite guard + writer (D8 — reused by C2b/C3/C5) -------------------------------


def _default_confirm(path: Path) -> bool:
    answer = input(f"{path} already exists — overwrite? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def ensure_writable(
    path: str | Path,
    *,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> None:
    """Overwrite protection (D8): refuse-if-exists; `--force` overrides; a TTY-gated prompt.

    A missing target or `force` passes silently. An existing target prompts ONLY when
    interactive (both stdin and stdout are TTYs, via the injectable `isatty` seam); when
    non-interactive it fails FAST — never hangs on a prompt no one can answer. Refusals name
    the path. `isatty`/`confirm` are injection seams for deterministic tests.
    """
    path = Path(path)
    if force or not path.exists():
        return
    interactive = isatty() if isatty is not None else (sys.stdin.isatty() and sys.stdout.isatty())
    if not interactive:
        raise AuthoringError(
            f"invalid-authoring: {path} already exists — pass --force to overwrite "
            "(non-interactive: never prompts, never hangs)"
        )
    if not (confirm or _default_confirm)(path):
        raise AuthoringError(f"invalid-authoring: {path} exists and overwrite was declined")


def write_recipe(
    root: str | Path,
    recipe_id: str,
    bundle: Mapping[str, Any],
    *,
    user: str | None = None,
    workspace: str | None = None,
    body: str | None = None,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
    schema: Schema | None = None,
) -> RecipeTarget:
    """Serialize + provenance-home + overwrite-guard + write one recipe file; return the target.

    The one composition the `recipe new` verb (C2b) drives; C5's selection writer reuses the
    same guard/provenance/serializer pieces. Writes exactly one file (§5.4 one-file-add).
    """
    schema = schema or load_recipe_schema()
    target = resolve_recipe_target(root, recipe_id, bundle, user=user, workspace=workspace)
    text = serialize_recipe(
        bundle, recipe_id=target.recipe_id, provenance=target.provenance, body=body, schema=schema
    )
    ensure_writable(target.path, force=force, isatty=isatty, confirm=confirm)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_text(text, encoding="utf-8")
    return target


# --- The saved-selection serializer (CLI-UX C5b; §8 / authoring D4) ------------------------
#
# `generate --save-selection ID` persists a run's OWN fan-out as a replayable selection:
# `{base, variants}` where `base` is the recipe REFERENCE the run used (kept as a reference so a
# later base edit surfaces honestly as a new id, D10) and `variants` is the EXPLICIT per-deliverable
# array (`plan.selection_variants` — the product ALREADY applied, driven 1:1 on reload, NEVER
# re-multiplied). This is the SAVE side; C5c loads + drives it. Reuses the SAME writer/provenance/
# overwrite-guard/dumper the recipe path uses — a saved selection is a small registry file like any
# other (§6.1), boundary-guarded exactly like a recipe (a client `x-` binding NEVER lands public).

#: The registry root saved selections live in (framework mechanism, C5a).
SELECTION_COLLECTION = "selections"

#: A variant's content-coordinate slots (§8 M2 content picks): a floor-faithful subset of the
#: run's single-valued content combination — each present slot is an explicit pick; an unselected
#: axis is OMITTED (it rides the base/cascade on reload). `goals` is the set-valued stacked pick.
SELECTION_CONTENT_SLOTS = ("topic", "persona", "format", "voice", "goals")

#: A variant's render-coordinate slots (§8 M3 rendering; §12.3). `platform` is MANDATORY (§7.4:
#: no platform-less deliverable); the other three are omitted when unselected (cascade defaults).
RENDER_COORDINATE_SLOTS = ("platform", "language", "output_type", "presentation")

_SELECTION_CONTENT = frozenset(SELECTION_CONTENT_SLOTS)
_RENDER = frozenset(RENDER_COORDINATE_SLOTS)
_VARIANT_KEYS = frozenset(("coordinate", "render", VALUES_SLOT))


def load_selection_schema() -> Schema:
    """Load the framework selections schema (`selections/_schema.yaml`) — the serializer's SSOT."""
    return load_schema(registry_dir(_framework_root(), SELECTION_COLLECTION) / SCHEMA_FILENAME)


def _validate_variant(variant: Any, index: int) -> dict[str, Any]:
    """Structurally validate ONE `{coordinate, render, values?}` variant (B3: the delta interior
    is UNTYPED in the registry manifest, so it is validated HERE at save, not by the schema).

    `coordinate` is a non-empty map of content-coordinate slots (each present slot a §7.4 slug, or
    a slug list for `goals`); `render` is a map carrying at least a concrete `platform` (§7.4) plus
    optional render slots; `values` (when present) is the run's shared value-tweak map. Every id is
    slug-validated loud; an unknown key or a missing `platform` is a typed refusal (never silent).
    """
    where = f"variant #{index}"
    if not isinstance(variant, Mapping):
        raise AuthoringError(
            f"invalid-authoring: {where} must be a {{coordinate, render, values?}} mapping, "
            f"got {type(variant).__name__}"
        )
    extra = set(variant) - _VARIANT_KEYS
    if extra:
        raise AuthoringError(
            f"invalid-authoring: {where} has unknown key(s) {sorted(extra)} — a variant holds only "
            f"{sorted(_VARIANT_KEYS)}"
        )
    coordinate = variant.get("coordinate")
    if not isinstance(coordinate, Mapping) or not coordinate:
        raise AuthoringError(
            f"invalid-authoring: {where} needs a non-empty `coordinate` (the content picks); "
            f"got {coordinate!r}"
        )
    result_coordinate: dict[str, Any] = {}
    for slot, value in coordinate.items():
        if slot not in _SELECTION_CONTENT:
            raise AuthoringError(
                f"invalid-authoring: {where} coordinate slot {slot!r} is not a content slot "
                f"{sorted(_SELECTION_CONTENT)}"
            )
        if slot == "goals":
            if not isinstance(value, (list, tuple)) or not value:
                raise AuthoringError(
                    f"invalid-authoring: {where} coordinate `goals` must be a non-empty id list, "
                    f"got {value!r}"
                )
            result_coordinate[slot] = [_require_slug(g, f"{where} goal") for g in value]
        else:
            result_coordinate[slot] = _require_slug(value, f"{where} {slot}")

    render = variant.get("render")
    if not isinstance(render, Mapping) or "platform" not in render:
        raise AuthoringError(
            f"invalid-authoring: {where} needs a `render` map with a concrete `platform` "
            f"(§7.4: a deliverable requires routing); got {render!r}"
        )
    result_render: dict[str, Any] = {}
    for slot in RENDER_COORDINATE_SLOTS:  # schema-slot order → deterministic frontmatter
        if slot in render:
            result_render[slot] = _require_slug(render[slot], f"{where} render {slot}")
    unknown_render = set(render) - _RENDER
    if unknown_render:
        raise AuthoringError(
            f"invalid-authoring: {where} render slot(s) {sorted(unknown_render)} — a render "
            f"coordinate holds only {sorted(_RENDER)}"
        )

    normalized: dict[str, Any] = {"coordinate": result_coordinate, "render": result_render}
    values = variant.get(VALUES_SLOT)
    if values is not None:
        if not isinstance(values, Mapping):
            raise AuthoringError(
                f"invalid-authoring: {where} `values` must be a value-tweak map (§12.5), "
                f"got {type(values).__name__}"
            )
        if values:  # omit an empty map (floor-faithful)
            normalized[VALUES_SLOT] = dict(values)
    return normalized


def _prepare_variants(
    variants: Sequence[Mapping[str, Any]], values: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Validate each variant and fold the run's SHARED value-tweak map onto every variant under
    the `values` key (§12.5 terminology — a persisted scope holds CONFIGURATION, never an
    "override"). The shared map is the same for the whole run; a variant that already carries its
    own `values` is refused (the caller supplies one or the other, never both)."""
    prepared: list[dict[str, Any]] = []
    shared = dict(values) if values else {}
    for index, variant in enumerate(variants):
        normalized = _validate_variant(variant, index)
        if shared:
            if VALUES_SLOT in normalized:
                raise AuthoringError(
                    f"invalid-authoring: variant #{index} already carries `values` while a shared "
                    "run value-tweak map was also supplied — pass one, never both"
                )
            normalized[VALUES_SLOT] = dict(shared)
        prepared.append(normalized)
    return prepared


def infer_selection_provenance(
    base: str, variants: Sequence[Mapping[str, Any]]
) -> str:
    """`framework` unless the base OR any variant binding is `x-`-scoped → `instance` (§11.4).

    Scans the `base` recipe reference, every variant's content-coordinate ids + render-coordinate
    ids, and every operand in a variant's `values` map (a values operand can be a ref-typed entry
    id). Any client/instance entry carries the reserved `x-` prefix by construction (§11.4), so the
    prefix IS the structural signal — no registry resolution needed (this stays a leaf), and it
    closes the rule-4 leak of a client id reaching the public `selections/` root via a saved run.
    """
    if isinstance(base, str) and base.startswith(INSTANCE_ID_PREFIX):
        return PROVENANCE_INSTANCE
    for variant in variants:
        coordinate = variant.get("coordinate") or {}
        for value in coordinate.values():
            ids = value if isinstance(value, (list, tuple)) else (value,)
            if any(isinstance(i, str) and i.startswith(INSTANCE_ID_PREFIX) for i in ids):
                return PROVENANCE_INSTANCE
        render = variant.get("render") or {}
        for value in render.values():
            if isinstance(value, str) and value.startswith(INSTANCE_ID_PREFIX):
                return PROVENANCE_INSTANCE
        if _values_carry_instance_id(variant.get(VALUES_SLOT)):
            return PROVENANCE_INSTANCE
    return PROVENANCE_FRAMEWORK


@dataclass(frozen=True)
class SelectionTarget:
    """Where a selection writes: its id, inferred provenance, home path, and workspace (if any)."""

    selection_id: str
    provenance: str
    path: Path
    workspace: str | None


def resolve_selection_target(
    root: str | Path,
    selection_id: str,
    base: str,
    variants: Sequence[Mapping[str, Any]],
    *,
    user: str | None = None,
    workspace: str | None = None,
) -> SelectionTarget:
    """Infer provenance from the base + variant bindings and compute the home path — REFUSING a
    client binding into the public `selections/` root (rule 4, §10), exactly like a recipe.

    A client/`x-` binding forces `instance`: the id MUST carry `x-` and a workspace MUST be named —
    otherwise the write is refused (a client-topic selection never leaks into the public repo). A
    framework-only selection homes public (`selections/<id>.md`); an instance selection homes under
    the workspace (`workspaces/<ws>/selections/x-<id>.md`) via the isolation guard.
    """
    _require_slug(selection_id, "selection id")
    binding_provenance = infer_selection_provenance(base, variants)
    id_is_instance = selection_id.startswith(INSTANCE_ID_PREFIX)

    if binding_provenance == PROVENANCE_INSTANCE and not id_is_instance:
        raise AuthoringError(
            f"invalid-authoring: selection {selection_id!r} binds a client/instance "
            f"('{INSTANCE_ID_PREFIX}') entry but is not an instance id — a client-binding "
            f"selection takes an '{INSTANCE_ID_PREFIX}' id under a --workspace, never the public "
            "repo (rule 4, §10)"
        )

    provenance = (
        PROVENANCE_INSTANCE
        if (id_is_instance or binding_provenance == PROVENANCE_INSTANCE)
        else PROVENANCE_FRAMEWORK
    )
    root = Path(root)
    if provenance == PROVENANCE_INSTANCE:
        if not workspace or not user:
            raise AuthoringError(
                f"invalid-authoring: instance selection {selection_id!r} requires a --user + "
                "--workspace home (instance config lives under users/<user>/workspaces/<client>/, "
                "rule 2/§10)"
            )
        ws_dir = validate_workspace_path(root, user, workspace)
        home = ws_dir / SELECTION_COLLECTION / f"{selection_id}.md"
        return SelectionTarget(selection_id, provenance, home, workspace)

    home = registry_dir(root, SELECTION_COLLECTION) / f"{selection_id}.md"
    return SelectionTarget(selection_id, provenance, home, None)


def _selection_body(selection_id: str) -> str:
    return (
        f"# {selection_id} — saved selection\n\n"
        "Saved by `pipeline generate --save-selection`. `base` is the recipe REFERENCE the run "
        "used; `variants` is the run's OWN fan-out (the product already applied) — reloaded 1:1, "
        "never re-multiplied (§8, authoring D4).\n"
    )


def serialize_selection(
    base: str,
    variants: Sequence[Mapping[str, Any]],
    *,
    selection_id: str,
    provenance: str,
    body: str | None = None,
    schema: Schema | None = None,
) -> str:
    """Render a schema-conforming `selections/<id>.md`: envelope + the `{base, variants}` fields.

    Floor-faithful: an empty `base` (`""`) and an empty `variants` (`[]`) are OMITTED so the file
    rides the C5a schema floors and round-trips (§5.4 one-file-add). The envelope is closed-schema
    validated (base is text, variants is a list) and each variant is structurally validated (B3:
    the untyped-list interior is checked here, not by the manifest), so the written file lints green
    and re-parses to the same bindings.
    """
    schema = schema or load_selection_schema()
    _require_slug(selection_id, "selection id")
    if provenance not in (PROVENANCE_FRAMEWORK, PROVENANCE_INSTANCE):
        raise AuthoringError(
            f"invalid-authoring: provenance must be {PROVENANCE_FRAMEWORK!r} or "
            f"{PROVENANCE_INSTANCE!r} (§10), got {provenance!r}"
        )
    _validate_namespace(selection_id, provenance)

    prepared = [_validate_variant(variant, index) for index, variant in enumerate(variants)]

    envelope: dict[str, Any] = {}
    if base:
        envelope["base"] = base
    if prepared:
        envelope["variants"] = prepared
    # Closed-schema validation (SV3): base is text, variants is an (untyped) list — reject a
    # mistyped envelope here so the written file is conforming by construction.
    schema.validate_attribute_values(
        envelope, where=f"{SELECTION_COLLECTION}/{selection_id}"
    )

    frontmatter: dict[str, Any] = {
        "id": selection_id,
        "provenance": provenance,
        "schema_version": schema.schema_version,
    }
    for slot in schema.attributes:  # schema-declared order (base, variants) → deterministic
        if slot in envelope:
            frontmatter[slot] = envelope[slot]

    body_text = _selection_body(selection_id) if body is None else body
    text = "---\n" + _dump_yaml(frontmatter) + "---\n"
    if body_text:
        text += body_text if body_text.endswith("\n") else body_text + "\n"
    return text


def write_selection(
    root: str | Path,
    selection_id: str,
    base: str,
    variants: Sequence[Mapping[str, Any]],
    *,
    values: Mapping[str, Any] | None = None,
    user: str | None = None,
    workspace: str | None = None,
    body: str | None = None,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
    schema: Schema | None = None,
) -> SelectionTarget:
    """Fold the shared `values` map, provenance-home, overwrite-guard, and write ONE selection file.

    The `generate --save-selection` verb (C5b) drives this: `variants` is `plan.selection_variants`
    (per-deliverable `{coordinate, render}` deltas), `values` the run's shared `--set` tweak map
    folded onto each variant under the `values` key. Reuses the recipe path's provenance/overwrite/
    dumper pieces; writes exactly one file (§5.4 one-file-add), homed public or under the workspace
    per the boundary (rule 4).
    """
    schema = schema or load_selection_schema()
    prepared = _prepare_variants(variants, values)
    target = resolve_selection_target(
        root, selection_id, base, prepared, user=user, workspace=workspace
    )
    text = serialize_selection(
        base,
        prepared,
        selection_id=target.selection_id,
        provenance=target.provenance,
        body=body,
        schema=schema,
    )
    ensure_writable(target.path, force=force, isatty=isatty, confirm=confirm)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_text(text, encoding="utf-8")
    return target


# --- The saved-selection LOADER (CLI-UX C5c; §8 / authoring D4/D10) ------------------------
#
# `generate --selection ID` reads a saved selection and DRIVES it 1:1. This is the LOAD side that
# reverses `write_selection`: it reads the file from its provenance home, re-validates every variant
# (a hand-edited file is refused loudly), and shapes each variant's content picks as the
# reference-faithful `base ⊕ deltaᵢ` — reusing the SAME `merge_bundle` the recipe path uses. `base`
# stays a REFERENCE (it drives `request.recipe`, resolved FRESH at plan time), so a later base
# recipe EDIT surfaces as a NEW id on reload — never a stale frozen copy (D10). The grouping of the
# flat variant list into the per-artifact render map happens downstream in `SelectionRequest`.


def _selection_home(
    root: str | Path, selection_id: str, user: str | None, workspace: str | None
) -> Path:
    """The provenance home a saved selection is READ from (rule 4), keyed by the id's `x-` prefix —
    the write path's homing in reverse. An `x-` instance id lives under
    `users/<user>/workspaces/<ws>/selections/`; a framework id lives in the public `selections/`
    root."""
    _require_slug(selection_id, "selection id")
    root = Path(root)
    if selection_id.startswith(INSTANCE_ID_PREFIX):
        if not workspace or not user:
            raise AuthoringError(
                f"invalid-authoring: instance selection {selection_id!r} requires a --user + "
                "--workspace home (instance config lives under users/<user>/workspaces/<client>/, "
                "rule 2/§10)"
            )
        ws_dir = validate_workspace_path(root, user, workspace)
        return ws_dir / SELECTION_COLLECTION / f"{selection_id}.md"
    return registry_dir(root, SELECTION_COLLECTION) / f"{selection_id}.md"


def _edit_set_from_coordinate(coordinate: Mapping[str, Any]) -> EditSet:
    """A validated content coordinate → the `EditSet` its picks drive over an EMPTY base."""
    picks: dict[str, list[str]] = {}
    for slot in ("topic", "persona", "format", "voice"):
        if slot in coordinate:
            picks[slot] = [coordinate[slot]]
    if "goals" in coordinate:
        picks["goals"] = list(coordinate["goals"])
    return build_edit_set(picks=picks)


def _coordinate_from_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Read a merged content bundle back into a content-coordinate dict (scalars + a goals list)."""
    coordinate: dict[str, Any] = {}
    for slot in ("topic", "persona", "format", "voice"):
        if slot in bundle:
            coordinate[slot] = bundle[slot]
    if "goals" in bundle:
        coordinate["goals"] = list(bundle["goals"])
    return coordinate


def load_selection(
    root: str | Path,
    selection_id: str,
    *,
    user: str | None = None,
    workspace: str | None = None,
    schema: Schema | None = None,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Load + validate a saved selection and shape it for the C5c DRIVE — returns
    `(base, variants, values)`.

    Reads `selections/<id>.md` (framework) or `workspaces/<ws>/selections/<id>.md` (instance) from
    the provenance home. `base` is the recipe REFERENCE the run used — it drives `request.recipe`
    and is resolved FRESH at plan time, so a base-recipe EDIT surfaces as a NEW id on reload
    (reference-faithful D10; never inlined). `variants` is the FLAT `[{coordinate, render}, …]`
    drive list: each variant is structurally re-validated (a hand-edited file is refused loudly),
    and its content `coordinate` is recomputed as the reference-faithful `base ⊕ deltaᵢ` via the
    C2a `merge_bundle` over an EMPTY base (the recipe's own pins ride the reference, never inlined).
    `values` is the run's shared value-tweak map (folded onto every variant at save), lifted back to
    the run OVERRIDE layer (§12.5), or `None`; variants that disagree on it are a loud refusal. The
    grouping of the flat list into the per-artifact render map happens in `SelectionRequest`."""
    schema = schema or load_selection_schema()
    path = _selection_home(root, selection_id, user, workspace)
    if not path.exists():
        raise AuthoringError(
            f"invalid-authoring: no saved selection {selection_id!r} at {path} — save one with "
            "`generate --save-selection` first (§8, authoring D4)"
        )
    entry = load_entry(path, schema)
    base = entry.attributes.get("base") or ""
    if not isinstance(base, str) or not base:
        raise AuthoringError(
            f"invalid-authoring: selection {selection_id!r} has no `base` recipe reference to "
            "drive (§8, authoring D4)"
        )
    raw_variants = entry.attributes.get("variants") or []
    if not raw_variants:
        raise AuthoringError(
            f"invalid-authoring: selection {selection_id!r} has no `variants` to drive — a saved "
            "selection replays a fan-out (§8, authoring D4)"
        )
    variants: list[dict[str, Any]] = []
    shared_values: dict[str, Any] | None = None
    for index, raw in enumerate(raw_variants):
        normalized = _validate_variant(raw, index)
        # Reference-faithful base ⊕ deltaᵢ (D10): merge the content picks over an EMPTY base — the
        # base recipe is a REFERENCE (request.recipe=base, resolved fresh), so its own pins are
        # NEVER inlined here; only the variant's explicit picks shape the combo. Reuses the SAME C2a
        # `merge_bundle` the recipe path uses (cardinality + slug re-validation; defense in depth).
        content_bundle = merge_bundle({}, _edit_set_from_coordinate(normalized["coordinate"]))
        variants.append(
            {"coordinate": _coordinate_from_bundle(content_bundle), "render": normalized["render"]}
        )
        values = normalized.get(VALUES_SLOT)
        if values:
            if shared_values is None:
                shared_values = dict(values)
            elif shared_values != dict(values):
                raise AuthoringError(
                    f"invalid-authoring: selection {selection_id!r} variants disagree on the "
                    "shared `values` tweak map — a saved run carries ONE run-shared value map "
                    "(§12.5); loud, never a silent merge"
                )
    return base, variants, shared_values
