"""Folios: the pure purposeful set — create, add, discover, typed-run consumption (§9).

Design authority: `docs/design.md` §9.1–§9.6 (the folio; the member record; identity &
state class; batches-are-not-containers; split-vs-folio; folio types), §13.3 (the
marker-per-member encoding + the atomic replacing-rename update), §21.2 (the `add-to-folio`
member-record write path and its re-append/update semantics), §20 (F6 — the system persists
workspace changes ONLY as the direct result of an explicit actor action; never auto-creates a
purpose folio, never auto-adds to a folio the actor didn't target), B4-2/B4-3 (the folio type
binds roles + per-role recipe skeletons — never dimension values; the role is recorded on the
MEMBER RECORD, a point-in-time slug never migrated with the type), A4-4 (the ratified
closure).

**A4-4, THE LOAD-BEARING PROPERTY (a folio is a PURE PURPOSEFUL SET — ZERO folio-level
state).** A folio holds NO dimension value, NO rendering intent, NO ordering, NO schedule —
ever. The folio record persisted here carries EXACTLY `{id, purpose, folio_type?, provenance}`
(§9.1: "collection-intrinsic data"). Any sort order an external actor wants is reconstructed
CLIENT-SIDE from ARTIFACT-level facts a member exposes (`added_ts`, the member's id-family
coordinates, its recorded `role`), never from folio state (§9.2 A4-4 condition i). Grep this
module for a folio-level dimension/ordering/schedule field and you will find none: that is a
binding acceptance criterion, enforced by construction here and by the tests.

**Why this module holds no SSOT handle (INV-CORRECTNESS, §22.7).** A folio is a
content-addressed membership store: correctness rides the §13.3 markers and the §22.8 atomic
primitives (create-if-absent, replacing-rename), never the tracking spreadsheet. This module
imports no status-authority code and takes no status-authority handle in any signature —
membership is durable workspace state (§9.3 F5), never the human progress view.

**What builds on what.** The atomic marker write with §21.2 semantics already lives in
`pipeline.spine.append_folio_member` (the S4 stage — dedupe no-op / atomic replacing-rename
update preserving `added_ts` / last-writer-wins / `member-updated`); this module REUSES it for
the standalone `add-to-folio` verb rather than hand-rolling a second copy of the atomic
replacing-rename. What this module adds around it is the VERB-LEVEL policy the spine's inner
S4 does not: the folio must already EXIST (F6 — no auto-create), each member must live in THIS
workspace (intra-workspace isolation, §9.2/§10), and each `pin`/`role` is shape-validated
before the write (a `pin` is a FROZEN deliverable-id in id-form, B4-2/FR3). Folio-record
placement is `folios/<folio-id>/folio.json`; the per-member markers are the store's own
`folios/<folio-id>/members/<artifact-id>` (§13.3, `pipeline.store.folio_member_path`).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value
from pipeline.canonical import canonical_json_str
from pipeline.ids import IdError, mint_folio_id, parse_id
from pipeline.spine import FolioAppendOutcome, FolioMembership, append_folio_member
from pipeline.store import (
    AlreadyMaterializedError,
    WorkspaceStore,
    is_done,
    is_temp_name,
    write_new,
)

__all__ = [
    "RECIPE_SLOTS",
    "SKELETON_KEY_WHITELIST",
    "CreateFolioOutcome",
    "CrossWorkspaceMemberError",
    "FolioError",
    "FolioExistsError",
    "FolioNotFoundError",
    "FolioTypeError",
    "FolioView",
    "MemberFact",
    "MemberShapeError",
    "MemberSpec",
    "RoleGrouping",
    "RolePlan",
    "SkeletonKeyError",
    "TypedRunPlan",
    "add_to_folio",
    "create_folio",
    "folio_exists",
    "folios_for_artifact",
    "get_folio",
    "group_members_by_role",
    "list_folio_members",
    "plan_typed_run",
    "validate_skeleton",
]

#: The recipe-slot vocabulary — the attribute names of `recipes/_schema.yaml` (§8). Sourced
#: verbatim here (the `pipeline.ids.CONTENT_DIMENSIONS` / `pipeline.m1._SKELETON_REF_SLOTS`
#: hardcode precedent); `tests/test_folio_types.py` asserts this set equals the live recipe
#: schema's attributes, so a slot added upstream fails the build rather than drifting silently.
RECIPE_SLOTS = frozenset(
    {
        "topic",
        "persona",
        "format",
        "voice",
        "goals",
        "values",
        "platforms",
        "languages",
        "output_types",
        "presentations",
    }
)

#: The folio-type skeleton key WHITELIST (§9.6 DIRECTIVE; step-15 review RV-1 carry-forward):
#: a skeleton may name ONLY a recipe slot or the prose `topic_slot`. A key outside this set —
#: notably a rendering-dimension key such as `platform` (singular; NOT the recipe's `platforms`
#: pin slot) — is the category error the DIRECTIVE forbids and is refused LOUDLY. The `roles`
#: list-of-maps interior is untyped in the schema (RV-1: `skeleton: {platform: linkedin}` lints
#: clean today), so this run-time whitelist is the mechanical guard the schema cannot express.
SKELETON_KEY_WHITELIST = RECIPE_SLOTS | {"topic_slot"}

#: §9.1: folio *instances* are client content, workspace-scoped, `provenance: instance`.
_PROVENANCE = "instance"

#: The folio-record filename inside `folios/<folio-id>/` — a metadata file, NOT a member
#: marker (markers are the store's `members/<artifact-id>`, §13.3), so an extension is fine
#: and cannot collide with any bare artifact-id (which must start `a-` and never carry a dot).
_FOLIO_RECORD_NAME = "folio.json"

#: §7.4 slug validation for `role`/`folio_type` slugs — the same `ref` alphabet ids uses.
_REF_SPEC = AttrTypeSpec(kind="ref")

#: A time source for `add-to-folio` (`added_ts` stamping rides `pipeline.spine`); injectable
#: for tests, epoch-seconds like the claim registry's clock.
Clock = Callable[[], float]


# ---------------------------------------------------------------------------
# Typed errors — each carries a stable `code` the API layer (steps 32/34) maps to a
# §21.7 ResultItem code; refusals are loud, never repaired.
# ---------------------------------------------------------------------------


class FolioError(RuntimeError):
    """A folio operation reached state it can never repair silently — refused loudly."""

    code = "folio-error"


class FolioNotFoundError(FolioError):
    """The target folio does not exist (§9.3). F6: `add-to-folio` never auto-creates it."""

    code = "not-found"


class FolioExistsError(FolioError):
    """A `create-folio` mint hit an existing folio-id whose record DIFFERS (a collision).

    A re-create with the SAME seed (the idempotent case) is not this error — it returns the
    existing id with `created=False`. This fires only when the id already names a folio with a
    different purpose/type, mirroring the §7.4 preimage-mismatch discipline (never silent).
    """

    code = "folio-exists"


class CrossWorkspaceMemberError(FolioError):
    """§9.2/§10: a folio may hold only artifacts materialized in its OWN workspace.

    Membership is by reference to an EXISTING artifact; an artifact-id absent from this
    workspace's store is either from another client (isolation is structural, §10) or unminted
    — either way it is refused, never added.
    """

    code = "isolation-violation"


class MemberShapeError(FolioError):
    """A member parameter violates §9.2: not a bare artifact-id, or a malformed `pin`/`role`."""

    code = "invalid-member"


class SkeletonKeyError(FolioError):
    """§9.6 DIRECTIVE: a folio-type skeleton carries a non-whitelisted (dimension) key."""

    code = "invalid-folio-type-skeleton"


class FolioTypeError(FolioError):
    """A folio type's declared `roles` structure is malformed (§9.6)."""

    code = "invalid-folio-type"


# ---------------------------------------------------------------------------
# Value objects.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemberSpec:
    """One `add-to-folio` member parameter (§21.2): an artifact reference + optional record.

    `pin`, when present, is a per-member deliverable pin in FROZEN id-form (§9.2/B4-2/FR3): the
    exact deliverable-id string (with any revision qualifiers, §7.4), stored verbatim and never
    re-resolved. `role` is the member's declared role slug in a typed folio (§9.6/B4-3).
    """

    artifact_id: str
    pin: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class MemberFact:
    """One member as exposed by the discovery surfaces — the marker record + its artifact-id.

    The A4-4 sortable facts are ARTIFACT-level and consumer-computed: `added_ts` and the
    `artifact_id` (whose id-family coordinates parse client-side) travel here; the lineage join
    (generating-run, source-commit) is the step-34 discovery layer reading each artifact's IR
    binding. `role` is surfaced AS-IS — a slug unknown to the current folio type is never
    dropped or remapped (§9.6/B4-3).
    """

    artifact_id: str
    added_ts: float
    pin: str | None
    role: str | None


@dataclass(frozen=True)
class FolioView:
    """`get folio` (§21.3): the folio's collection-intrinsic data + its member set.

    Exactly `{folio_id, purpose, folio_type?, provenance}` plus the unordered member set — NO
    dimension, ordering, or schedule field, ever (A4-4). Members arrive in a deterministic
    artifact-id order for reproducibility; every USEFUL ordering is the consumer's, computed
    from the per-member facts (§9.2).
    """

    folio_id: str
    purpose: str
    folio_type: str | None
    provenance: str
    members: tuple[MemberFact, ...]


@dataclass(frozen=True)
class CreateFolioOutcome:
    """A `create-folio` result: the system-assigned `f-<hex12>` id and whether it was created.

    `created` is False only on the idempotent re-create (same seed → same id, matching record).
    """

    folio_id: str
    created: bool


@dataclass(frozen=True)
class RolePlan:
    """One role of a typed generation run (§9.6): the role slug + its recipe skeleton + roster.

    `roster` is this writer's SIBLING role list (the other declared roles, in declared order) —
    generating-run compose CONTEXT for light cross-linking, fed to `ComposeRequest.roster`. It
    is NEVER an identity input (§9.6): compose is LLM-non-deterministic and the roster never
    enters the artifact preimage.
    """

    role: str
    skeleton: Mapping[str, Any]
    roster: tuple[str, ...]


@dataclass(frozen=True)
class TypedRunPlan:
    """A folio type consumed for one generation run (§9.6): one recipe skeleton per role.

    `roster` is the full declared role order (each role's `RolePlan.roster` is this minus self).
    Concrete dimension values come from the generating recipe/run, never from this plan
    (DIRECTIVE item 4): the skeletons here are blueprint slots, key-validated against the
    whitelist.
    """

    folio_type: str | None
    roles: tuple[RolePlan, ...]
    roster: tuple[str, ...]


@dataclass(frozen=True)
class RoleGrouping:
    """Structural order reconstructed from a folio type's declared roles + recorded roles.

    `declared` lists (role, members) for each CURRENT declared role, in declared order —
    structural order rebuilt from tracked data alone (§9.2/§9.6). `unknown` holds recorded role
    slugs NOT in the current declared set, surfaced AS-IS (never dropped, never remapped —
    B4-3: member records are machine records, never migrated with the type). `unroled` holds
    members with no recorded role (one-offs in an otherwise typed folio). Every member appears
    exactly once across the three buckets.
    """

    declared: tuple[tuple[str, tuple[MemberFact, ...]], ...]
    unknown: tuple[tuple[str, tuple[MemberFact, ...]], ...]
    unroled: tuple[MemberFact, ...]


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _record_bytes(record: Mapping[str, Any]) -> bytes:
    return (canonical_json_str(record) + "\n").encode("utf-8")


def _require_slug(value: object, what: str) -> str:
    try:
        validate_value(_REF_SPEC, value)
    except ValueValidationError as exc:
        raise MemberShapeError(
            f"invalid-member: {what} {value!r} is not a §7.4 slug: {exc}"
        ) from exc
    assert isinstance(value, str)
    return value


def _require_folio_id(folio_id: str) -> str:
    """Refuse anything that is not a `f-<hex12>` folio id (§7.4)."""
    try:
        parsed = parse_id(folio_id)
    except IdError as exc:
        raise FolioError(f"folio-error: {folio_id!r} is not a valid id: {exc}") from exc
    if parsed.family != "folio":
        raise FolioError(f"folio-error: {folio_id!r} is not a folio id (§7.4: f-<hex12>)")
    return folio_id


def _require_bare_artifact(artifact_id: str) -> str:
    """§9.2 F3: membership is artifact-level — a bare artifact-id, no fitted/deliverable coords
    and no part suffix."""
    try:
        parsed = parse_id(artifact_id)
    except IdError as exc:
        raise MemberShapeError(
            f"invalid-member: {artifact_id!r} is not a valid id: {exc}"
        ) from exc
    if parsed.family != "artifact" or parsed.level != "artifact" or parsed.part is not None:
        raise MemberShapeError(
            f"invalid-member: folio membership is artifact-level (§9.2 F3) — a bare "
            f"artifact-id is required, got {artifact_id!r}"
        )
    return artifact_id


def _folio_record_path(store: WorkspaceStore, folio_id: str) -> Path:
    """`folios/<folio-id>/folio.json` — the folio's collection-intrinsic record (§9.1)."""
    return store.folios_dir / folio_id / _FOLIO_RECORD_NAME


def _members_dir(store: WorkspaceStore, folio_id: str) -> Path:
    return store.folios_dir / folio_id / "members"


def _read_folio_record(path: Path) -> dict[str, Any]:
    """Load and validate a folio record; missing → not-found, corrupt → refuse (damage)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise FolioNotFoundError(
            f"not-found: no folio at {path.parent.name!r} — the system never auto-creates a "
            "folio (§20 F6); use create-folio first"
        ) from exc
    try:
        obj: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        obj = None
    if not isinstance(obj, dict) or not isinstance(obj.get("purpose"), str) or not obj["purpose"]:
        raise FolioError(
            f"folio-error: corrupt folio record {path} — records are written atomically "
            "(§13.3/§22.8), so this is damage, not a race; refusing to guess"
        )
    return obj


def _read_member(path: Path) -> dict[str, Any]:
    """Load and validate one member marker `{added_ts, pin?, role?}` (§13.3, A4-4)."""
    try:
        obj: Any = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError):
        obj = None
    added = obj.get("added_ts") if isinstance(obj, dict) else None
    if isinstance(added, bool) or not isinstance(added, int | float):
        raise FolioError(
            f"folio-error: corrupt folio member marker {path} — markers are written "
            "atomically (§13.3/§21.2), so this is damage, not a race; refusing to guess"
        )
    return obj


# ---------------------------------------------------------------------------
# create-folio (§9.3, §20 F6): system-assigned f-<hex12>, workspace-scoped, EXPLICIT.
# ---------------------------------------------------------------------------


def create_folio(
    store: WorkspaceStore,
    *,
    purpose: str,
    folio_type: str | None = None,
    nonce: str | None = None,
) -> CreateFolioOutcome:
    """Create an EMPTY folio (§9.1/§9.3): mint its id, persist its record, return the id.

    Explicit only — the system never auto-creates a purpose folio (§20 F6). The id is
    system-assigned (`f-<hex12>`, §7.1 F8) and workspace-scoped; two calls yield DISTINCT
    folios (an actor may hold many empty folios) because the mint seed carries a random `nonce`
    by default. Supplying the SAME `nonce` (an idempotency handle) reproduces the same id: a
    matching re-create is the idempotent no-op (`created=False`); a differing one is a loud
    `FolioExistsError` (never silent reuse, §7.4 discipline). The record is exactly
    `{id, purpose, folio_type?, provenance}` — NO dimension/ordering/schedule field (A4-4).
    `folio_type`, when set, is shape-validated as a slug here; its EXISTENCE resolves loudly at
    the generating run (§9.6), the only place the registry root is in scope.
    """
    if not isinstance(purpose, str) or not purpose:
        raise FolioError("folio-error: a folio purpose must be a non-empty string (§9.1)")
    if folio_type is not None:
        _require_slug(folio_type, "folio_type")
    if nonce is None:
        nonce = os.urandom(16).hex()
    # The mint seed is consumer-defined (§7): purpose + type + nonce. The nonce is NOT stored
    # on the record — it is a mint input only, so it never becomes folio state.
    seed = {"purpose": purpose, "folio_type": folio_type, "nonce": nonce}
    folio_id = mint_folio_id(seed)
    record: dict[str, Any] = {"id": folio_id, "purpose": purpose, "provenance": _PROVENANCE}
    if folio_type is not None:
        record["folio_type"] = folio_type
    path = _folio_record_path(store, folio_id)
    try:
        write_new(path, _record_bytes(record))  # atomic no-replace (§22.8)
    except AlreadyMaterializedError:
        existing = _read_folio_record(path)
        if existing.get("purpose") != purpose or existing.get("folio_type") != folio_type:
            raise FolioExistsError(
                f"folio-exists: {folio_id!r} already names a folio with a different "
                "purpose/type — a mint collision, refused (never silent reuse, §7.4)"
            ) from None
        return CreateFolioOutcome(folio_id=folio_id, created=False)
    return CreateFolioOutcome(folio_id=folio_id, created=True)


def folio_exists(store: WorkspaceStore, folio_id: str) -> bool:
    """True iff `folio_id` names a created folio in this workspace (its record exists)."""
    _require_folio_id(folio_id)
    return _folio_record_path(store, folio_id).is_file()


# ---------------------------------------------------------------------------
# add-to-folio (§21.2): the verb-level policy around the spine's atomic S4 append.
# ---------------------------------------------------------------------------


def _coerce_member(item: Any) -> MemberSpec:
    """Accept a `MemberSpec`, a `{artifact_id, pin?, role?}` mapping, or a bare artifact-id
    string (the §21.2 `artifact_ids` sugar for pin-less, role-less members)."""
    if isinstance(item, MemberSpec):
        return item
    if isinstance(item, str):
        return MemberSpec(artifact_id=item)
    if isinstance(item, Mapping):
        artifact_id = item.get("artifact_id")
        if not isinstance(artifact_id, str):
            raise MemberShapeError(
                f"invalid-member: a member mapping needs a string `artifact_id`, got {item!r}"
            )
        return MemberSpec(
            artifact_id=artifact_id, pin=item.get("pin"), role=item.get("role")
        )
    raise MemberShapeError(
        f"invalid-member: a member is a MemberSpec, a mapping, or an artifact-id string, "
        f"got {type(item).__name__}"
    )


def _validate_member(store: WorkspaceStore, spec: MemberSpec) -> None:
    """§9.2/§21.2 member validation, BEFORE any write: shape, isolation, pin/role forms."""
    _require_bare_artifact(spec.artifact_id)
    if not is_done(store, spec.artifact_id):  # intra-workspace: the artifact must live HERE
        raise CrossWorkspaceMemberError(
            f"isolation-violation: artifact {spec.artifact_id!r} is not materialized in this "
            "workspace — a folio may hold only its own workspace's artifacts (§9.2/§10)"
        )
    if spec.pin is not None:
        try:
            pin = parse_id(spec.pin)
        except IdError as exc:
            raise MemberShapeError(
                f"invalid-member: pin {spec.pin!r} is not a valid id: {exc}"
            ) from exc
        if pin.level != "deliverable":
            raise MemberShapeError(
                f"invalid-member: a member pin is a FROZEN deliverable-id in id-form "
                f"(§9.2/B4-2/FR3), got a {pin.level} id {spec.pin!r}"
            )
        # The pin is stored VERBATIM (below) and never re-resolved — that is the freeze.
    if spec.role is not None:
        _require_slug(spec.role, "role")


def add_to_folio(
    store: WorkspaceStore,
    folio_id: str,
    members: Sequence[Any],
    *,
    clock: Clock = time.time,
) -> tuple[FolioAppendOutcome, ...]:
    """`add-to-folio` (§21.2): append members to an EXISTING folio, explicit and never silent.

    The folio must already exist (F6 — no auto-create) and every member must be an artifact of
    THIS workspace (intra-workspace isolation, §9.2/§10); both are validated for ALL members
    before ANY marker is written. Each append then rides the proven §21.2 S4 primitive
    (`pipeline.spine.append_folio_member`): a fresh member → `ok`; an identical re-append (same
    `pin`/`role`) → the idempotent dedupe no-op `ok`; a DIFFERING `pin`/`role` → an atomic
    replacing-rename update that PRESERVES the original `added_ts`, surfaced `member-updated`
    (warn), last-writer-wins. Concurrent differing updates resolve to exactly one atomic winner
    and BOTH callers receive `member-updated`, never silence. Membership is APPEND-ONLY in v1 —
    this module exposes no removal (§9.2/§27.3). Pins freeze the id-form (B4-2/FR3): the exact
    deliverable-id string is stored and never re-resolved.
    """
    _require_folio_id(folio_id)
    if not folio_exists(store, folio_id):
        raise FolioNotFoundError(
            f"not-found: folio {folio_id!r} does not exist — the system never auto-creates a "
            "folio on add (§20 F6); create-folio first"
        )
    specs = [_coerce_member(item) for item in members]
    for spec in specs:  # validate ALL before writing ANY (no partial-batch surprise)
        _validate_member(store, spec)
    outcomes = tuple(
        append_folio_member(
            store,
            FolioMembership(folio_id=folio_id, pin=spec.pin, role=spec.role),
            spec.artifact_id,
            clock=clock,
        )
        for spec in specs
    )
    return outcomes


# ---------------------------------------------------------------------------
# Discovery: get folio / list folio-members, and the DERIVED reverse index.
# ---------------------------------------------------------------------------


def list_folio_members(store: WorkspaceStore, folio_id: str) -> tuple[MemberFact, ...]:
    """The folio's member set (§9.2): every marker's `{added_ts, pin?, role?}` + its artifact-id.

    Returned in a deterministic artifact-id order for reproducibility — an UNORDERED set
    surfaced stably, not a folio-held sequence (A4-4). The consumer computes any useful ordering
    (insertion via `added_ts`, structural via `role`) from the exposed facts.
    """
    _require_folio_id(folio_id)
    if not folio_exists(store, folio_id):
        raise FolioNotFoundError(f"not-found: folio {folio_id!r} does not exist (§9.3)")
    members_dir = _members_dir(store, folio_id)
    facts: list[MemberFact] = []
    if members_dir.is_dir():
        for entry in members_dir.iterdir():
            if is_temp_name(entry.name) or not entry.is_file():
                continue  # a crash-dropped stage-temp is inert, never a member (§13.3/A4)
            record = _read_member(entry)
            facts.append(
                MemberFact(
                    artifact_id=entry.name,
                    added_ts=float(record["added_ts"]),
                    pin=record.get("pin"),
                    role=record.get("role"),
                )
            )
    return tuple(sorted(facts, key=lambda m: m.artifact_id))


def get_folio(store: WorkspaceStore, folio_id: str) -> FolioView:
    """`get folio` (§21.3): the collection-intrinsic record + the member set with facts.

    Surfaces each member's recorded `role` AS-IS — verbatim from its marker, never reconciled
    against the current folio type — so a slug the type has since renamed/removed is preserved
    (§9.6/B4-3: member records are machine records, never migrated).
    """
    _require_folio_id(folio_id)
    record = _read_folio_record(_folio_record_path(store, folio_id))
    return FolioView(
        folio_id=folio_id,
        purpose=record["purpose"],
        folio_type=record.get("folio_type"),
        provenance=record.get("provenance", _PROVENANCE),
        members=list_folio_members(store, folio_id),
    )


def folios_for_artifact(store: WorkspaceStore, artifact_id: str) -> tuple[str, ...]:
    """The DERIVED reverse index (§9.2): the folios an artifact belongs to, computed on demand.

    Never stored as folio state — the same one-authority-plus-derived-view discipline as the
    tracking spreadsheet (§24). Each call scans the workspace's folios for a member marker named
    `artifact_id`; the folio member set stays the sole authority, this the recomputable view.
    """
    _require_bare_artifact(artifact_id)
    folios_root = store.folios_dir
    hits: list[str] = []
    for folio_dir in folios_root.iterdir():
        if not folio_dir.is_dir():
            continue
        try:
            _require_folio_id(folio_dir.name)
        except FolioError:
            continue  # not a folio-id-named directory — skip
        if (folio_dir / "members" / artifact_id).is_file():
            hits.append(folio_dir.name)
    return tuple(sorted(hits))


# ---------------------------------------------------------------------------
# Folio-type consumption at generation (§9.5/§9.6): roles → skeletons + roster.
# ---------------------------------------------------------------------------


def validate_skeleton(
    skeleton: Any, *, role: str, recipe_slots: frozenset[str] | set[str] = RECIPE_SLOTS
) -> None:
    """§9.6 DIRECTIVE: a role skeleton may carry ONLY recipe slots + `topic_slot` — else refuse.

    The whitelist is the recipe-slot vocabulary plus `topic_slot` (step-15 RV-1 ruling). A key
    outside it — a rendering-dimension value like `platform: linkedin`, or any other
    folio-held dimension — is the category error the DIRECTIVE forbids and is rejected loudly.
    This is the mechanical guard the schema's untyped map interior cannot provide (RV-1).
    """
    if not isinstance(skeleton, Mapping):
        raise SkeletonKeyError(
            f"invalid-folio-type-skeleton: role {role!r} skeleton must be a map, got "
            f"{type(skeleton).__name__}"
        )
    allowed = set(recipe_slots) | {"topic_slot"}
    for key in skeleton:
        if key not in allowed:
            raise SkeletonKeyError(
                f"invalid-folio-type-skeleton: role {role!r} skeleton key {key!r} is neither a "
                f"recipe slot nor `topic_slot` — a folio type declares roles + per-role recipe "
                f"skeletons, NEVER a dimension value (§9.6 DIRECTIVE; e.g. a `platform` key is "
                f"refused). Allowed keys: {sorted(allowed)}"
            )


def plan_typed_run(
    roles: Sequence[Any],
    *,
    folio_type: str | None = None,
    recipe_slots: frozenset[str] | set[str] = RECIPE_SLOTS,
) -> TypedRunPlan:
    """Consume a folio type's declared `roles` for one generation run (§9.6): one skeleton/role.

    `roles` is the folio-type entry's `roles` attribute — an ordered list of
    `{role, skeleton?}` maps (§9.6). Each role slug is validated; the declared structure lists
    each role once (a duplicate DECLARED role is a config error, refused — distinct from the
    LEGAL duplicate roles that recur across regenerations on MEMBERSHIP, §9.6). Each skeleton's
    keys are whitelist-validated. Every writer's `roster` is the sibling roles in declared
    order (self excluded) — run-scoped compose context, never an identity input.
    """
    if not isinstance(roles, Sequence) or isinstance(roles, str | bytes):
        raise FolioTypeError(
            "invalid-folio-type: `roles` must be the ordered list of role maps (§9.6)"
        )
    parsed: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for item in roles:
        if not isinstance(item, Mapping) or "role" not in item:
            raise FolioTypeError(
                f"invalid-folio-type: each role is a map with a `role` slug (§9.6), got {item!r}"
            )
        try:
            validate_value(_REF_SPEC, item["role"])
        except ValueValidationError as exc:
            raise FolioTypeError(
                f"invalid-folio-type: role {item['role']!r} is not a §7.4 slug: {exc}"
            ) from exc
        role = item["role"]
        if role in seen:
            raise FolioTypeError(
                f"invalid-folio-type: role {role!r} is declared twice — the declared structure "
                "lists each role once (§9.6; duplicate roles are legal on MEMBERSHIP, not here)"
            )
        seen.add(role)
        skeleton = item.get("skeleton", {})
        validate_skeleton(skeleton, role=role, recipe_slots=recipe_slots)
        parsed.append((role, dict(skeleton)))
    order = tuple(role for role, _ in parsed)
    role_plans = tuple(
        RolePlan(role=role, skeleton=skeleton, roster=tuple(r for r in order if r != role))
        for role, skeleton in parsed
    )
    return TypedRunPlan(folio_type=folio_type, roles=role_plans, roster=order)


def group_members_by_role(
    declared_roles: Sequence[str], members: Sequence[MemberFact]
) -> RoleGrouping:
    """Reconstruct structural order from a folio type's CURRENT declared roles + recorded roles.

    Structural order is rebuilt from tracked data alone (§9.2/§9.6): the type's declared role
    order + each member's recorded `role`. A recorded slug NOT among `declared_roles` — e.g.
    after a folio-type role rename — is surfaced AS-IS in `unknown`, never dropped or remapped
    (B4-3). Members within each role keep the deterministic artifact-id order. Every member
    lands in exactly one bucket (`declared`, `unknown`, or `unroled`).
    """
    ordered = list(dict.fromkeys(declared_roles))  # de-dup, preserve first-seen order
    declared_set = set(ordered)
    by_role: dict[str, list[MemberFact]] = {role: [] for role in ordered}
    unknown: dict[str, list[MemberFact]] = {}
    unroled: list[MemberFact] = []
    for member in sorted(members, key=lambda m: m.artifact_id):
        if member.role is None:
            unroled.append(member)
        elif member.role in declared_set:
            by_role[member.role].append(member)
        else:
            unknown.setdefault(member.role, []).append(member)
    return RoleGrouping(
        declared=tuple((role, tuple(by_role[role])) for role in ordered),
        unknown=tuple((role, tuple(members)) for role, members in unknown.items()),
        unroled=tuple(unroled),
    )
