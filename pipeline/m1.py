"""M1 — entry resolution (Mechanism 1 of the §12 value cascade): shadowing + field-merge.

Design authority: `docs/design.md`
  §12.1 — M1 orders **which definition of an entry id loads**: framework → instance-global →
          workspace, at load time. It is provenance-ordered field-merge: a redefining layer
          (an `extends:` partial) overrides only the fields it declares and inherits the
          rest, **with per-field provenance recorded**. Its output is exactly one effective
          entry per dimension — and that entry IS M2's `entry-default` rung (CA1). M1 fully
          resolves BEFORE M2 binds values on top (Q18a); overrides never touch M1 (§12.5
          CA7 — this module has no override input, structurally).
  §12.4 — M1 and M2 combine **type-driven, by one rule set**: replace for scalars/free
          text, key-wise merge for maps, operator rules for sets (union never fires by
          default; the schema-level default operator and the CM3 inline per-binding
          operator are the only union sources). `combine_values` below is that ONE rule
          set — `pipeline/cascade.py` imports it for M2, never re-implements it.
  §10 (Q15 rule 2) — extend-don't-edit at entry granularity: a `provenance: framework`
          entry is never edited in place; customization is a workspace (or instance-global)
          `extends:` partial that field-merges over it.
  §11.1 — **an unknown entry id is an error, never silent** (the loud dangling-reference
          promise). This module makes every currently-load-silent reference loud (the
          step-14/15 review carry-forwards): recipe topic/persona/format/voice/goals ids,
          `personas.default_voice`, `sources.content_kind`, platform projection keys +
          `default_output_type`, folio-type skeleton `format`/`goals` ids.
  §11.5/§11.6 (MIG-6) — resolve-time drift ENFORCEMENT wires here: before any stale entry
          is used, the queryable `pipeline/drift.RESOLVE_TIME_TABLE` is applied — BLOCK
          (meaning change affecting a set attribute · removed-attribute-still-present ·
          stamp outside the migration window when a window oracle is injected) refuses
          resolution with a typed `StaleEntryError`; WARN (new-attribute-available)
          surfaces as a resolution warning; wording-only changes are silent by
          construction.

Wiring, never duplication: envelope parsing is `pipeline/entries.py` via the drift module's
lenient loader (a stale entry may hold values invalid under the CURRENT schema — drift must
see its own input, §11.6); schemas are `pipeline/schema.py`; the §12.4 operator legality and
§11.1 operand typing ride `pipeline/opgrammar.validate_bind_against_spec` (the ONE validator,
CM3); set canonicalization is `pipeline/canonical.canonical_set` (§12.4: identical logical
sets yield identical ids).

In-latitude decisions (step-16 coder; grounded in the report):

- **`extends:` shape.** `extends: <entry-id>` in frontmatter marks a PARTIAL. Naming a
  DIFFERENT id in the same collection field-merges over that id's full resolution (the Q15
  rule-2 customization path: `voices/x-house-voice.md` + `extends: clear-explainer`).
  Naming its OWN id field-merges over the next-outer scope's definition of the same id
  (workspace over instance-global) — SV5 namespacing (§11.4) makes framework-id shadowing
  structurally impossible, so same-id shadowing exists only inside the `x-` namespace.
  A same-id redefinition WITHOUT `extends:` is a full replacement (it is "the definition
  that loads", §12.1). Cycles and a self-extends with no outer definition are typed errors.
- **Inline combine operators in entry frontmatter are partial-only.** A partial's payload
  keys ride the §13.2 frontmatter binding surface (`tags+:` / the `{combine:…, add:…}`
  wrapper — CM3); a base definition's payload is plain closed-schema values (the strict
  step-8 loader path, unchanged).
- **Set values canonicalize at combine time** (`canonical_set`, sorted + deduped) for both
  replace and union, so an authored member order never leaks into `artifact-id` (§12.4
  "identical inputs give an identical set and an identical artifact-id").
- **Cross-collection ref targets are a code table** (`REF_ATTRIBUTE_TARGETS` etc.): the
  §11.1 type system deliberately does not carry a ref's target collection, and the closed
  manifest vocabulary (§11.1) cannot; machine truth for "which registry does this ref name"
  lives here, per attribute, each with its design grounding.
- **Workspace collections validate against the ROOT collection manifest**: SV2 pins ONE
  global schema snapshot; per-file `schema_version` equality across copies is schema-lint's
  clause (step-11 RV-3) — resolution reads the single root manifest (SV4 co-location names
  the collection; `workspaces/<client>/<collection>/` is the same collection at workspace
  scope, §10).
- **Body prose inherits like a field**: the most-local layer's markdown body applies when
  non-blank, else the base's (a partial that says nothing keeps the base's prose).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import date
from pathlib import Path
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, validate_value
from pipeline.canonical import canonical_set
from pipeline.drift import (
    CODE_DRIFT_BLOCK,
    CODE_OUT_OF_WINDOW,
    DriftFinding,
    Severity,
    WindowOracle,
    blocking_findings,
    check_entry,
    load_entry_lenient,
)
from pipeline.entries import ENTRY_SUFFIX, PROVENANCE_FRAMEWORK, Entry
from pipeline.layout import registry_dir
from pipeline.opgrammar import (
    OperatorGrammarError,
    parse_frontmatter_binding,
    validate_bind_against_spec,
)
from pipeline.schema import (
    SCHEMA_FILENAME,
    AttributeSpec,
    Schema,
    UndeclaredAttributeError,
    load_schema,
)
from pipeline.workspace_name import DEFAULT_ZONE, WORKSPACES_DIRNAME, workspace_path

__all__ = [
    "CONTENT_DIMENSION_TOKENS",
    "DIMENSION_COLLECTIONS",
    "DanglingRefError",
    "EXTENDS_KEY",
    "ExtendsError",
    "FORMAT_KEYED_MAP_ATTRIBUTES",
    "FieldProvenance",
    "M1Error",
    "REF_ATTRIBUTE_TARGETS",
    "RENDERING_DIMENSION_TOKENS",
    "ResolutionWarning",
    "ResolvedEntry",
    "Resolver",
    "SCOPE_FRAMEWORK",
    "SCOPE_INSTANCE_GLOBAL",
    "SCOPE_WORKSPACE",
    "StaleEntryError",
    "TEXT_REF_ATTRIBUTE_TARGETS",
    "UnknownCollectionError",
    "UnknownEntryError",
    "WORKSPACES_DIRNAME",
    "combine_values",
    "default_combine_op",
]

#: §5.1 dimension tokens → registry collection directories. Value-binding paths
#: (`<dimension>.<attribute>`, §21.4/§13.2) name dimensions by these tokens.
DIMENSION_COLLECTIONS: dict[str, str] = {
    "topic": "topics",
    "persona": "personas",
    "format": "formats",
    "voice": "voices",
    "goal": "goals",
    "platform": "platforms",
    "language": "languages",
    "output-type": "output-types",
    "presentation": "presentations",
}

#: §5.1 role facet: content dimensions bind at M2-compose (→ artifact-id), rendering
#: dimensions at M2-render (→ deliverable-id) — §12.3 "bind stage".
CONTENT_DIMENSION_TOKENS = ("topic", "persona", "format", "voice", "goal")
RENDERING_DIMENSION_TOKENS = ("platform", "language", "output-type", "presentation")

#: The M1 partial marker (§12.1) — a RESERVED frontmatter key (never a schema attribute,
#: `pipeline/schema.RESERVED_ATTRIBUTE_NAMES`).
EXTENDS_KEY = "extends"

# §10: scope is encoded by location; workspace scope lives under WORKSPACES_DIRNAME —
# imported from `pipeline.workspace_name` (the single home for the layout directory-name
# literals) and re-exported in `__all__` for callers that read `m1.WORKSPACES_DIRNAME`.

#: The three M1 scopes, in resolution order (§12.1). Framework vs instance-global is the
#: provenance TAG inside the shared directory (§10: mixed-provenance dirs); workspace is
#: the location layer.
SCOPE_FRAMEWORK = "framework"
SCOPE_INSTANCE_GLOBAL = "instance-global"
SCOPE_WORKSPACE = "workspace"

#: Cross-collection `ref`-typed attributes → target collection (design grounding per row).
#: The §11.1 loud-resolution promise is enforced for every row when an entry SETS the
#: attribute (floors are the L0 last-resort net and name shipped entries by construction —
#: consumers resolve the value they actually use).
REF_ATTRIBUTE_TARGETS: dict[tuple[str, str], str] = {
    ("personas", "default_voice"): "voices",  # Q6/CA2 (§5.2, §12.3)
    ("recipes", "persona"): "personas",  # §8: a recipe binds one entry per content dim
    ("recipes", "format"): "formats",
    ("recipes", "voice"): "voices",  # the L5 rung of the §12.3 voice chain
    ("recipes", "goals"): "goals",  # the set-valued goal-set (§5.2)
    ("recipes", "platforms"): "platforms",  # §8 optional rendering pins
    ("recipes", "languages"): "languages",
    ("recipes", "output_types"): "output-types",
    ("recipes", "presentations"): "presentations",
    ("sources", "content_kind"): "content-kinds",  # §6.1 SM5
}

#: text-typed attributes that carry an entry id when non-empty ("" = the honest unset
#: floor the ref alphabet cannot express — the step-14(c) reviewer-ratified precedent).
TEXT_REF_ATTRIBUTE_TARGETS: dict[tuple[str, str], str] = {
    ("recipes", "topic"): "topics",  # §8; topics are workspace editorial data (§5.2)
    ("platforms", "default_output_type"): "output-types",  # §5.3/§12.3 weak default
    # increment C (amendment §2.K, Open Item O2): the diagram-style ref SOURCE is a recipe
    # attribute — the ratified `(collection, attribute) -> diagram-styles` row shape, mirroring
    # the `("recipes","topic"):"topics"` recipe→referenced-registry precedent right above. It
    # rides the TEXT table (empty "" floor) rather than the ref table for the same reason `topic`
    # does: an unset diagram-style is the honest floor ("no explicit style — draw with the
    # framework default"), which the ref slug alphabet cannot express, and a text/"" add is
    # additive-at-floor (§11.2) so it needs no global schema_version bump. A NON-empty value
    # resolves loudly at M1 against the diagram-styles registry (§11.1); "" resolves nothing.
    ("recipes", "diagram_style"): "diagram-styles",
}

#: map attributes whose KEYS are format entry ids (§12.3: Platform's per-format
#: projections) — dangling keys were load-silent (step-14 review RV-2, break-it 3).
FORMAT_KEYED_MAP_ATTRIBUTES = frozenset(
    {("platforms", "format_advisories"), ("platforms", "reconcile_strategy_defaults")}
)

#: folio-type skeleton slots that carry entry ids (§9.6: skeletons name a Format genre and
#: a goal-set; unknown ids inside a skeleton fail loudly when resolved — the folio-types
#: schema's own definition text). The slot-key WHITELIST is step 31's scope (step-15
#: review RV-1).
_SKELETON_REF_SLOTS: dict[str, str] = {"format": "formats", "goals": "goals"}

_REF_SPEC = AttrTypeSpec(kind="ref")
_UNSET = object()


# --- Typed errors -----------------------------------------------------------------------


class M1Error(ValueError):
    """An entry-resolution refusal — loud, typed, never repaired."""

    code = "entry-resolution-refused"


class UnknownCollectionError(M1Error):
    """No co-located `_schema.yaml` for the named collection (SV4, §13.4)."""

    code = "unknown-collection"


class UnknownEntryError(M1Error):
    """§11.1: an unknown entry id is an error — never a silent skip."""

    code = "unknown-entry"


class ExtendsError(M1Error):
    """A malformed `extends:` partial: cycle, self-extends with no outer definition,
    or a non-string/non-slug target (§12.1)."""

    code = "invalid-extends"


class DanglingRefError(M1Error):
    """A resolved entry references an entry id that does not resolve (§11.1 loud
    resolution; the step-14/15 carry-forward classes). Exposes the referrer."""

    code = "dangling-ref"

    def __init__(
        self, message: str, *, referrer: str, attribute: str, target_collection: str, ref: str
    ) -> None:
        super().__init__(message)
        self.referrer = referrer
        self.attribute = attribute
        self.target_collection = target_collection
        self.ref = ref


class StaleEntryError(M1Error):
    """MIG-6 resolve-time BLOCK (§11.5): the entry drifted hard — migrate before use.

    `code` is the §21.7 pinned code of the findings (`drift-block`, or `out-of-window`
    when only the window blocks); `findings` carries the full typed determination.
    """

    code = CODE_DRIFT_BLOCK

    def __init__(self, message: str, *, findings: tuple[DriftFinding, ...]) -> None:
        super().__init__(message)
        self.findings = findings
        if findings and all(f.code == CODE_OUT_OF_WINDOW for f in findings):
            self.code = CODE_OUT_OF_WINDOW


# --- Result shapes ----------------------------------------------------------------------


@dataclass(frozen=True)
class ResolutionWarning:
    """A surfaced, non-blocking resolution note. `key` is stable so 'one-time' warning
    semantics (§8, §12.6, §12.7) can dedupe per session (the cascade env does)."""

    key: str
    message: str


@dataclass(frozen=True)
class FieldProvenance:
    """§12.1: per-field provenance of one effective attribute value."""

    #: `framework` | `instance-global` | `workspace` (M1 scope of the setting layer).
    scope: str
    #: The setting layer's `provenance:` tag (§10).
    provenance: str
    #: The setting layer's entry id (an extends chain may cross ids).
    entry_id: str
    #: The setting layer's file path.
    path: str


@dataclass(frozen=True)
class ResolvedEntry:
    """M1's output: exactly one effective entry (CA1 — M2's `entry-default` rung).

    `effective` holds the attributes some layer SET (post field-merge); attributes no
    layer set ride the schema-default floor (§12.2 L0) and are absent here — exactly the
    `Entry.attributes` contract the step-8 loader documents.
    """

    collection: str
    id: str
    schema: Schema
    effective: dict[str, Any]
    field_provenance: dict[str, FieldProvenance]
    #: Contributing layer file paths, outermost → innermost.
    layer_paths: tuple[str, ...]
    #: The effective markdown body (most-local non-blank layer's prose).
    body: str
    #: WARN-tier drift findings and other surfaced notes (never blocking).
    warnings: tuple[ResolutionWarning, ...]

    def defaults(self) -> dict[str, Any]:
        """The L0 floor for this entry's collection, set attributes canonicalized
        (§12.4) so floor-vs-effective comparison (§7.2 delta) is order-stable."""
        floor: dict[str, Any] = {}
        for name, spec in self.schema.attributes.items():
            if spec.type.kind == "set":
                floor[name] = canonical_set(spec.default)
            else:
                floor[name] = copy.deepcopy(spec.default)
        return floor


# --- The §12.4 combination rule set (ONE implementation for M1 and M2) -------------------


def default_combine_op(attr_spec: AttributeSpec) -> str:
    """The type-driven DEFAULT combination operator (§12.4): the per-`set`-attribute
    schema default operator (`replace` unless the schema author set `union`); `replace`
    for every other kind (map merging is structural, not an operator)."""
    return attr_spec.combine if attr_spec.type.kind == "set" else "replace"


def _merge_untyped_map(current: Mapping[str, Any], operand: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = copy.deepcopy(dict(current))
    for key, value in operand.items():
        prev = merged.get(key)
        if isinstance(prev, Mapping) and isinstance(value, Mapping):
            merged[key] = _merge_untyped_map(prev, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _merge_map(spec: AttrTypeSpec, current: Any, operand: Mapping[str, Any]) -> dict[str, Any]:
    """§12.4 `map`: merge key-wise, recursing per value type (typed `map` elements and
    untyped nested mappings recurse; every other element kind replaces per key)."""
    if not isinstance(current, Mapping):
        return copy.deepcopy(dict(operand))
    merged: dict[str, Any] = copy.deepcopy(dict(current))
    element = spec.element
    for key, value in operand.items():
        prev = merged.get(key)
        if (
            isinstance(prev, Mapping)
            and isinstance(value, Mapping)
            and (element is None or element.kind == "map")
        ):
            if element is not None and element.kind == "map":
                merged[key] = _merge_map(element, prev, value)
            else:
                merged[key] = _merge_untyped_map(prev, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def combine_values(attr_spec: AttributeSpec, current: Any, operand: Any, op: str) -> Any:
    """Combine one attribute value onto `current` — the §12.4 type-driven rule set.

    `current` is the value beneath (the floor, or a lower layer's effective value);
    `op` is the EFFECTIVE operator (the caller resolves explicit-vs-default via
    `default_combine_op`; operator×type legality was validated at parse via
    `opgrammar.validate_bind_against_spec` — the one validator). Set results are
    canonical (`canonical_set`): sorted + deduped, so identical logical sets yield
    identical values and identical ids (§12.4/§7.2).
    """
    kind = attr_spec.type.kind
    if op == "union":
        base = list(current) if isinstance(current, list) else []
        return canonical_set(base + list(operand))
    if kind == "set":
        return canonical_set(operand)
    if kind == "map" and isinstance(operand, Mapping):
        return _merge_map(attr_spec.type, current, operand)
    return copy.deepcopy(operand)


# --- Layer loading ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Layer:
    """One loaded definition layer of one entry id."""

    path: Path
    scope: str
    entry: Entry
    extends: str | None
    #: Parsed payload bindings: (attribute, op, operand, explicit).
    binds: tuple[tuple[str, str, Any, bool], ...]
    warnings: tuple[ResolutionWarning, ...]


def _require_slug(value: object, what: str) -> str:
    try:
        validate_value(_REF_SPEC, value)
    except ValueError as exc:
        raise M1Error(
            f"entry-resolution-refused: {what} {value!r} is not a §7.4 slug "
            "([a-z0-9-], 1-40 chars, no leading/trailing '-')"
        ) from exc
    assert isinstance(value, str)
    return value


def _stripped_attr_name(key: str) -> str:
    """The attribute name a payload key addresses, ignoring the CM3 `+` suffix — used
    ONLY for the pre-validation drift math (§11.5 needs set-attribute NAMES)."""
    return key[:-1] if key.endswith("+") else key


class Resolver:
    """The M1 resolver: load-time entry resolution over one config tree.

    `root` is the config tree (registry roots at the top level; workspace scope under
    `workspaces/<workspace>/<collection>/`). `workspace` selects the workspace layer
    (client isolation is structural — rule 2/§10: only that workspace's directory is
    ever read). `window`/`now` inject the MIG-2 window oracle and the clock for the
    MIG-6 out-of-window block (`pipeline/migration.StepRegistry` implements the oracle;
    the clock is injected at the edge, never ambient).

    Resolution is cached per (collection, id): one effective entry per id per session
    (§12.1), and drift warnings surface once. READ-ONLY toward the tree.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        user: str | None = None,
        workspace: str | None = None,
        zone: str = DEFAULT_ZONE,
        now: date | None = None,
        window: WindowOracle | None = None,
    ) -> None:
        self._root = Path(root)
        if workspace is not None:
            _require_slug(workspace, "workspace")
            # §23 re-home: the workspace SHADOW lives at users/<user>/zones/<zone>/workspaces/<ws>/,
            # so a workspace-scoped resolver MUST carry its owning user — a missing one would make a
            # `users/None/…` shadow path. Fail LOUD here rather than silently miss the shadow (the
            # owner was validated at the door; this only enforces the pair is complete). `zone`
            # defaults to `DEFAULT_ZONE` (Z4), exactly as its sole real constructor `CascadeEnv`
            # does — the workspace-root gate already vetted a non-default zone at the door.
            if user is None:
                raise M1Error(
                    "entry-resolution-refused: a workspace-scoped Resolver requires `user` — the "
                    "workspace shadow lives at users/<user>/zones/<zone>/workspaces/<workspace>/ "
                    "(§23); a missing user would build a users/None/ path (never silent)"
                )
            _require_slug(user, "user")
        self._user = user
        self._workspace = workspace
        self._zone = zone
        if window is not None and now is None:
            raise M1Error(
                "entry-resolution-refused: `now` is required when a window oracle is "
                "supplied (the clock is injected at the edge, never read ambiently)"
            )
        self._now = now
        self._window = window
        self._schemas: dict[str, Schema] = {}
        self._cache: dict[tuple[str, str], ResolvedEntry] = {}
        self._in_progress: set[tuple[str, str]] = set()

    @property
    def root(self) -> Path:
        return self._root

    @property
    def user(self) -> str | None:
        return self._user

    @property
    def workspace(self) -> str | None:
        return self._workspace

    # -- schemas ---------------------------------------------------------------------

    def schema(self, collection: str) -> Schema:
        """The collection's ROOT co-located manifest (SV4; workspace copies are the
        lint's lockstep concern — see the module docstring)."""
        cached = self._schemas.get(collection)
        if cached is not None:
            return cached
        _require_slug(collection, "collection")
        path = registry_dir(self._root, collection) / SCHEMA_FILENAME
        if not path.is_file():
            raise UnknownCollectionError(
                f"unknown-collection: no {collection}/{SCHEMA_FILENAME} under {self._root} "
                "— a collection is its co-located schema (SV4, §13.4)"
            )
        schema = load_schema(path)
        self._schemas[collection] = schema
        return schema

    # -- resolution ------------------------------------------------------------------

    def resolve(self, collection: str, entry_id: str) -> ResolvedEntry:
        """Resolve one effective entry (§12.1). Typed refusals: `UnknownEntryError`,
        `StaleEntryError` (MIG-6), `ExtendsError`, `DanglingRefError`, plus the loader's
        own envelope/payload refusals (entries/schema/attrtypes error classes)."""
        key = (collection, entry_id)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        _require_slug(entry_id, f"{collection} entry id")
        schema = self.schema(collection)
        if key in self._in_progress:
            chain = " -> ".join(f"{c}/{e}" for c, e in [*self._in_progress, key])
            raise ExtendsError(
                f"invalid-extends: resolution cycle at {collection}/{entry_id} "
                f"(in progress: {chain}) — an extends/ref chain may never revisit an id"
            )
        self._in_progress.add(key)
        try:
            layers = self._load_layers(collection, entry_id, schema)
            resolved = self._fold_layers(collection, entry_id, schema, layers)
            self._check_refs(resolved)
        finally:
            self._in_progress.discard(key)
        self._cache[key] = resolved
        return resolved

    def resolve_ref(
        self, target_collection: str, ref: str, *, referrer: str, attribute: str
    ) -> ResolvedEntry:
        """Resolve a cross-collection reference; an unknown target becomes a typed
        `DanglingRefError` naming the referrer (§11.1 loud resolution)."""
        try:
            return self.resolve(target_collection, ref)
        except UnknownEntryError as exc:
            raise DanglingRefError(
                f"dangling-ref: {referrer}.{attribute} references "
                f"{target_collection}/{ref!r}, which does not resolve — an unknown entry "
                "id is an error, never silent (§11.1)",
                referrer=referrer,
                attribute=attribute,
                target_collection=target_collection,
                ref=ref,
            ) from exc

    # -- internals ---------------------------------------------------------------------

    def _layer_candidates(self, collection: str, entry_id: str) -> list[tuple[Path, str]]:
        """Candidate definition files, outermost first (§12.1 scope order). The shared
        directory holds ONE file per id (mixed provenance by tag, §10); the workspace
        directory may shadow it (structurally only inside the `x-` namespace, §11.4)."""
        filename = f"{entry_id}{ENTRY_SUFFIX}"
        candidates: list[tuple[Path, str]] = []
        shared = registry_dir(self._root, collection) / filename
        if shared.is_file():
            candidates.append((shared, "shared"))
        if self._workspace is not None:
            # §23 re-home: the shadow is a PURE join off the door-validated (user, workspace) pair —
            # no re-resolve on the hot M1 path (`workspace_path`, the "validate once, pure-join
            # downstream" discipline).
            local = workspace_path(
                self._root, self._user, self._workspace, collection, filename, zone=self._zone
            )
            if local.is_file():
                candidates.append((local, SCOPE_WORKSPACE))
        return candidates

    def _load_layers(self, collection: str, entry_id: str, schema: Schema) -> list[_Layer]:
        candidates = self._layer_candidates(collection, entry_id)
        if not candidates:
            looked = [str(registry_dir(self._root, collection) / f"{entry_id}{ENTRY_SUFFIX}")]
            if self._workspace is not None:
                looked.append(
                    str(
                        workspace_path(
                            self._root,
                            self._user,
                            self._workspace,
                            collection,
                            f"{entry_id}{ENTRY_SUFFIX}",
                            zone=self._zone,
                        )
                    )
                )
            raise UnknownEntryError(
                f"unknown-entry: {collection}/{entry_id!r} does not resolve — an unknown "
                f"entry id is an error, never silent (§11.1); looked at: {looked}"
            )
        return [self._load_layer(path, scope, schema) for path, scope in candidates]

    def _load_layer(self, path: Path, scope: str, schema: Schema) -> _Layer:
        # The lenient loader: envelope rules strict, payload raw — a STALE entry may hold
        # values invalid under the current schema; drift must see it (§11.6), and the
        # honest refusal for it is the MIG-6 block below, not a value-type error.
        entry = load_entry_lenient(path, schema)
        if scope == "shared":
            scope = (
                SCOPE_FRAMEWORK
                if entry.provenance == PROVENANCE_FRAMEWORK
                else SCOPE_INSTANCE_GLOBAL
            )
        where = f"{schema.collection}/{entry.id}"

        payload = dict(entry.attributes)
        extends: str | None = None
        if EXTENDS_KEY in payload:
            raw = payload.pop(EXTENDS_KEY)
            if not isinstance(raw, str):
                raise ExtendsError(
                    f"invalid-extends: {where}: `extends:` must be an entry-id string "
                    f"(§12.1), got {type(raw).__name__}"
                )
            extends = _require_slug(raw, f"{where}.extends target")

        warnings: list[ResolutionWarning] = []
        # MIG-6 resolve-time enforcement (§11.5): the drift math runs on the STRIPPED
        # attribute names (`extends`/the CM3 `+` suffix are M1 syntax, never set attrs).
        if entry.schema_version < schema.schema_version:
            names = {_stripped_attr_name(k): v for k, v in payload.items()}
            findings = check_entry(
                schema,
                dc_replace(entry, attributes=names),
                window=self._window,
                now=self._now,
            )
            blocking = blocking_findings(findings)
            if blocking:
                details = "; ".join(f"[{f.code}] {f.detail}" for f in blocking)
                raise StaleEntryError(
                    f"stale-entry: {where} (stamp v{entry.schema_version} < schema "
                    f"v{schema.schema_version}) is refused at resolve time (MIG-6, "
                    f"§11.5): {details}",
                    findings=tuple(blocking),
                )
            for finding in findings:
                if finding.severity is Severity.WARN:
                    warnings.append(
                        ResolutionWarning(
                            key=f"drift:{where}:{finding.attribute}",
                            message=finding.detail,
                        )
                    )
        elif entry.schema_version > schema.schema_version:
            warnings.append(
                ResolutionWarning(
                    key=f"stamp-ahead:{where}",
                    message=(
                        f"entry stamp v{entry.schema_version} is AHEAD of the current "
                        f"schema v{schema.schema_version} — a mixed checkout or a "
                        "hand-edited stamp (§11.2); resolution proceeds on the current "
                        "schema"
                    ),
                )
            )

        binds: list[tuple[str, str, Any, bool]] = []
        if extends is not None:
            # A PARTIAL: payload keys ride the §13.2 frontmatter binding surface (CM3).
            for key, value in payload.items():
                if not isinstance(key, str):
                    raise M1Error(
                        f"entry-resolution-refused: {where}: frontmatter keys must be "
                        f"strings, got {key!r}"
                    )
                try:
                    bind = parse_frontmatter_binding(key, value)
                except OperatorGrammarError as exc:
                    raise M1Error(f"entry-resolution-refused: {where}.{key}: {exc}") from exc
                if "." in bind.path:
                    raise M1Error(
                        f"entry-resolution-refused: {where}.{key}: entry frontmatter "
                        "binds the entry's OWN attributes — dotted dimension paths "
                        "belong to scope-default/recipe `values:` maps and overrides "
                        "(§13.2/§21.4)"
                    )
                spec = schema.attributes.get(bind.path)
                if spec is None:
                    raise UndeclaredAttributeError(
                        f"undeclared-attribute: {where}.{key}: {bind.path!r} is not "
                        f"declared by the {schema.collection!r} schema — schemas are "
                        f"closed (SV3, §11.3); declared: {sorted(schema.attributes)}"
                    )
                # Operator×type legality + operand typing: the ONE validator (CM3).
                validate_bind_against_spec(bind, spec.type)
                explicit = key.endswith("+") or (isinstance(value, Mapping) and "combine" in value)
                binds.append((bind.path, bind.op, bind.value, explicit))
        else:
            # A BASE definition: plain closed-schema payload (strict, as at step 8).
            schema.validate_attribute_values(payload, where=str(path))
            binds = [(name, "replace", value, False) for name, value in payload.items()]

        return _Layer(
            path=path,
            scope=scope,
            entry=entry,
            extends=extends,
            binds=tuple(binds),
            warnings=tuple(warnings),
        )

    def _fold_layers(
        self, collection: str, entry_id: str, schema: Schema, layers: list[_Layer]
    ) -> ResolvedEntry:
        layer = layers[-1]
        base_effective: dict[str, Any] = {}
        base_provenance: dict[str, FieldProvenance] = {}
        base_paths: tuple[str, ...] = ()
        base_body = ""
        base_warnings: tuple[ResolutionWarning, ...] = ()

        if layer.extends is not None:
            if layer.extends == entry_id:
                if len(layers) == 1:
                    raise ExtendsError(
                        f"invalid-extends: {collection}/{entry_id}: a self-extends "
                        "partial field-merges over the next-outer scope's definition "
                        "of the same id (§12.1) — and no outer definition exists"
                    )
                base = self._fold_layers(collection, entry_id, schema, layers[:-1])
            else:
                base = self.resolve(collection, layer.extends)
            base_effective = dict(base.effective)
            base_provenance = dict(base.field_provenance)
            base_paths = base.layer_paths
            base_body = base.body
            base_warnings = base.warnings

        effective = base_effective
        provenance = base_provenance
        floor: dict[str, Any] | None = None
        for attr, op, operand, explicit in layer.binds:
            spec = schema.attributes[attr]
            effective_op = op if explicit else default_combine_op(spec)
            current = effective.get(attr, _UNSET)
            if current is _UNSET:
                # The L0 floor sits beneath every layer (§12.2): union/map-merge onto
                # an unset attribute combines with the schema default.
                if floor is None:
                    floor = schema.defaults()
                current = floor[attr]
            effective[attr] = combine_values(spec, current, operand, effective_op)
            provenance[attr] = FieldProvenance(
                scope=layer.scope,
                provenance=layer.entry.provenance,
                entry_id=layer.entry.id,
                path=str(layer.path),
            )

        body = layer.entry.body if layer.entry.body.strip() else base_body
        return ResolvedEntry(
            collection=collection,
            id=entry_id,
            schema=schema,
            effective=effective,
            field_provenance=provenance,
            layer_paths=(*base_paths, str(layer.path)),
            body=body,
            warnings=(*base_warnings, *layer.warnings),
        )

    def _check_refs(self, resolved: ResolvedEntry) -> None:
        """The §11.1 loud-resolution pass over every cross-collection reference the
        effective entry SETS (the step-14/15 carry-forward classes; see the tables)."""
        collection = resolved.collection
        referrer = f"{collection}/{resolved.id}"
        for attr, value in resolved.effective.items():
            target = REF_ATTRIBUTE_TARGETS.get((collection, attr))
            if target is not None:
                spec = resolved.schema.attributes[attr]
                if spec.type.kind == "ref":
                    self.resolve_ref(target, value, referrer=referrer, attribute=attr)
                else:  # set-of-ref — each member resolves
                    for member in value:
                        self.resolve_ref(target, member, referrer=referrer, attribute=attr)
            text_target = TEXT_REF_ATTRIBUTE_TARGETS.get((collection, attr))
            if text_target is not None and isinstance(value, str) and value:
                self.resolve_ref(text_target, value, referrer=referrer, attribute=attr)
            if (collection, attr) in FORMAT_KEYED_MAP_ATTRIBUTES and isinstance(value, Mapping):
                for key in value:
                    self.resolve_ref("formats", key, referrer=referrer, attribute=f"{attr} key")
        if collection == "folio-types":
            self._check_skeleton_refs(resolved, referrer)

    def _check_skeleton_refs(self, resolved: ResolvedEntry, referrer: str) -> None:
        roles = resolved.effective.get("roles")
        if not isinstance(roles, list):
            return
        for role in roles:
            if not isinstance(role, Mapping):
                continue
            skeleton = role.get("skeleton")
            if not isinstance(skeleton, Mapping):
                continue
            role_label = role.get("role", "?")
            for slot, target in _SKELETON_REF_SLOTS.items():
                value = skeleton.get(slot)
                if value is None:
                    continue
                attribute = f"roles[{role_label}].skeleton.{slot}"
                members = value if isinstance(value, list) else [value]
                for member in members:
                    if isinstance(member, str) and member:
                        self.resolve_ref(target, member, referrer=referrer, attribute=attribute)
