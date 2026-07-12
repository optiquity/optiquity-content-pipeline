"""Fanout enumeration (design §8): a multi-select selection → concrete recipe-shaped items.

Design authority: `docs/design.md`
  §8    — **recipe → one artifact; selection → many recipes**: a selection multi-selects
          across dimensions and fans out into concrete items — content fanout (distinct
          artifacts) × rendering fanout (deliverables per artifact). Every fanout item is
          id-keyed, commit-pinned, idempotent (§7). **Pairing is user-driven; there is no
          hard compatibility filter** (Q4): no `valid_platforms`, no exclusion table, no
          final-moment veto — the effective allow-list is EMERGENT from configuration
          (§12). The one-time advisory lint (`nonsensical-pairing`, warn) flags
          strange/distant combinations; **its catalog contains no folio-based pairing
          triggers** (CA3: a folio has no platform or rendering value to diverge from,
          §9.1). Goal-set overload likewise warns, never blocks.
  §5.1  — cardinality: Goal is SET-valued (multi-select of goals STACKS into one
          artifact — the one fanout exception); for every other dimension multi-select =
          fanout. Goal VARIANTS as separate artifacts are a list of goal-sets (§5.2).
  §5.2  — the goal-set is a set: duplicates are loud, never silently deduped (the
          established cascade posture).
  §12.3 — the rendering coordinate sources: run selection > recipe pin > scope defaults;
          Platform has NO default rung (L5 pin, L6 run only — per-deliverable routing,
          CA8), so a platform-less request cannot name a deliverable coordinate.
  §7.4  — every selected value is a registry entry id in the slug alphabet (`x-` prefix
          included, §11.4); validated here at the request boundary, resolved loudly by
          M1 at plan resolution (§11.1).

This module is PURE ENUMERATION — no registry access, no cascade, no store, no SSOT
(§22.7 boundary; `pipeline/plan.py` wires the enumeration to the resolvers). Slug
validation rides `pipeline.attrtypes`' `ref` validator (the §7.4 slug alphabet's single
implementation), exactly as `pipeline/ids.py` does.

In-latitude decisions (step-19 coder; grounded in the report):

- **One recipe per request.** §8's "selection → many recipes" reads as: the concrete
  fanout items are recipe-shaped bindings (one artifact each), materialized from ONE
  selected recipe entry + the multi-selects. Cross-recipe fanout inside one selection is
  expressed as multiple requests; nothing in §8 requires it inside one.
- **Duplicate selection values are loud** (§5.2 posture: "loud, never silently deduped"):
  a duplicated axis value, a duplicated goal id inside one goal-set, and two goal-set
  VARIANTS that canonicalize (sorted) to the same set are all refused — the last would
  otherwise mint the same `artifact-id` twice and break the PC2 exactly-once cover.
- **A bare string is refused where a sequence of ids is expected** (the
  `ids.build_artifact_preimage` source-subset precedent): `topics="readme"` is an
  authoring mistake, not a one-element selection.
- **The nonsensical-pairing catalog is a code constant of (format × platform) rows.**
  §8 fixes the lint's shape (one-time, advisory, never runtime machinery) and its one
  example (README → LinkedIn); the shipped catalog carries exactly that grounded row.
  The `PairingTrigger` record has ONLY format/platform slots, so a folio-based trigger
  is structurally inexpressible (CA3; the §8 catalog constraint is enforced by shape,
  not by review).
- **Goal-set overload threshold = 3** (`GOAL_SET_OVERLOAD_THRESHOLD`): §8 mandates the
  warn and fixes no number; a piece serving 4+ goals at once is the smallest clearly
  "overloaded" reading. Advisory only — the warn never blocks (§8), so the constant is
  safe to tune.
- **An explicitly empty goal-set variant `()` is legal** (§12.3: the L0 baseline set is
  empty) — it selects the empty set over the recipe's goals, exactly as
  `RunSelection(goals=())` does.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, fields
from itertools import product

from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value

__all__ = [
    "CONTENT_AXES",
    "GOAL_SET_OVERLOAD_THRESHOLD",
    "NONSENSICAL_PAIRING_CATALOG",
    "PAIRING_TRIGGER_FIELDS",
    "RENDERING_AXES",
    "ContentCombination",
    "FanoutError",
    "PairingTrigger",
    "RenderCoordinate",
    "SelectionRequest",
    "content_combinations",
    "goal_set_overloaded",
    "pairing_advisory",
    "render_coordinates",
]

#: The single-valued content axes a request may multi-select (§5.1: multi-select =
#: fanout). Goal is deliberately absent: goals STACK per goal-set; variants are the
#: `goal_sets` list (§5.2).
CONTENT_AXES = ("topics", "personas", "formats", "voices")

#: The rendering axes (§5.3); multi-select = rendering fanout (§12.3).
RENDERING_AXES = ("platforms", "languages", "output_types", "presentations")

#: §8: goal-set overload warns, never blocks. The threshold is advisory-only (see the
#: module docstring); a goal-set with MORE members than this fires the one-time warn.
GOAL_SET_OVERLOAD_THRESHOLD = 3

#: Slug validation = the §7.4 slug alphabet's single implementation (attrtypes `ref`).
_REF_SPEC = AttrTypeSpec(kind="ref")


class FanoutError(ValueError):
    """An unusable fanout request — loud, typed, never repaired (§3.1)."""

    code = "invalid-selection"


def _require_slug(value: object, what: str) -> str:
    if not isinstance(value, str):
        raise FanoutError(
            f"invalid-selection: {what} must be an entry-id string, got "
            f"{type(value).__name__}: {value!r}"
        )
    try:
        validate_value(_REF_SPEC, value, path=what)
    except ValueValidationError as exc:
        raise FanoutError(
            f"invalid-selection: {what} {value!r} is not a §7.4 entry-id slug "
            "([a-z0-9-], 1-40 chars, no leading/trailing '-'; §11.4 `x-` prefix included)"
        ) from exc
    return value


def _normalize_axis(values: object, axis: str) -> tuple[str, ...]:
    """One multi-select axis: a sequence of distinct entry-id slugs (or empty)."""
    if values is None:
        return ()
    if isinstance(values, str | bytes):
        raise FanoutError(
            f"invalid-selection: {axis} is a multi-select sequence of entry ids, not a "
            f"single string — pass [{values!r}] for a one-element selection"
        )
    if not isinstance(values, Sequence):
        raise FanoutError(
            f"invalid-selection: {axis} must be a sequence of entry ids, got "
            f"{type(values).__name__}: {values!r}"
        )
    members = tuple(_require_slug(v, f"{axis} member") for v in values)
    if len(set(members)) != len(members):
        raise FanoutError(
            f"invalid-selection: duplicate entry id in {axis} {list(members)!r} — a "
            "multi-select is a set (§5.1); loud, never silently deduped (§5.2 posture)"
        )
    return members


def _normalize_goal_sets(values: object) -> tuple[tuple[str, ...], ...]:
    """The goal-set VARIANT list (§5.2): each member goal-set stacks; the list fans out.

    Duplicate goal ids inside one set are loud (§5.2); two variants canonicalizing to
    the same sorted set are loud too — they would mint one `artifact-id` twice (§7.2
    sorts the goal-set) and break the PC2 exactly-once cover.
    """
    if values is None:
        return ()
    if isinstance(values, str | bytes) or not isinstance(values, Sequence):
        raise FanoutError(
            "invalid-selection: goal_sets is a sequence of goal-sets (each a sequence "
            f"of goal entry ids — §5.2 variants), got {type(values).__name__}: {values!r}"
        )
    variants: list[tuple[str, ...]] = []
    seen_canonical: set[tuple[str, ...]] = set()
    for i, raw_set in enumerate(values):
        where = f"goal_sets[{i}]"
        if isinstance(raw_set, str | bytes) or not isinstance(raw_set, Sequence):
            raise FanoutError(
                f"invalid-selection: {where} must be a sequence of goal entry ids "
                f"(one goal-set — it STACKS into one artifact, §5.2), got {raw_set!r}"
            )
        members = tuple(_require_slug(v, f"{where} member") for v in raw_set)
        if len(set(members)) != len(members):
            raise FanoutError(
                f"invalid-selection: duplicate goal id in {where} {list(members)!r} — "
                "the goal-set is a set (§5.2); loud, never silently deduped"
            )
        canonical = tuple(sorted(members))
        if canonical in seen_canonical:
            raise FanoutError(
                f"invalid-selection: {where} {list(members)!r} duplicates an earlier "
                "goal-set variant (the §7.2 canonical goal-set is sorted — identical "
                "sets in any order are ONE designed item; the plan is an exactly-once "
                "cover, PC2)"
            )
        seen_canonical.add(canonical)
        variants.append(members)
    return tuple(variants)


@dataclass(frozen=True)
class SelectionRequest:
    """One fanout request: a recipe + per-axis multi-selects (§8).

    Empty axes mean "unselected — supplied by the cascade" (recipe slot, workspace/
    global defaults, or floors, §12.3). Construction normalizes sequences to tuples and
    refuses malformed input loudly; entry ids resolve via M1 at plan resolution (§11.1).
    """

    recipe: str
    topics: tuple[str, ...] = ()
    personas: tuple[str, ...] = ()
    formats: tuple[str, ...] = ()
    voices: tuple[str, ...] = ()
    #: Goal-set VARIANTS (§5.2): each member is one goal-set (stacks into one artifact);
    #: the list fans out — one artifact per goal-set.
    goal_sets: tuple[tuple[str, ...], ...] = ()
    platforms: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    output_types: tuple[str, ...] = ()
    presentations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_slug(self.recipe, "recipe")
        for axis in (*CONTENT_AXES, *RENDERING_AXES):
            object.__setattr__(self, axis, _normalize_axis(getattr(self, axis), axis))
        object.__setattr__(self, "goal_sets", _normalize_goal_sets(self.goal_sets))


@dataclass(frozen=True)
class ContentCombination:
    """One content-fanout item: the concrete per-dimension picks for ONE artifact (§8).

    `None` means "unselected — the cascade supplies it" (§12.3); `goals` is the one
    STACKED set-valued pick (§5.2), `None` when no variant list was given.
    """

    topic: str | None
    persona: str | None
    format: str | None
    voice: str | None
    goals: tuple[str, ...] | None


def _axis_or_unset(values: tuple[str, ...]) -> tuple[str | None, ...]:
    return values if values else (None,)


def content_combinations(request: SelectionRequest) -> tuple[ContentCombination, ...]:
    """The content fanout (§8): the cross product of the content multi-selects.

    Goal-sets ride as whole sets (the §5.2 stacking exception): the product runs over
    the VARIANT list, never over individual goals. Deterministic: the enumeration order
    is the request's authored order, axis-major left to right.
    """
    return tuple(
        ContentCombination(topic=topic, persona=persona, format=format_, voice=voice, goals=goals)
        for topic, persona, format_, voice, goals in product(
            _axis_or_unset(request.topics),
            _axis_or_unset(request.personas),
            _axis_or_unset(request.formats),
            _axis_or_unset(request.voices),
            request.goal_sets if request.goal_sets else (None,),
        )
    )


@dataclass(frozen=True)
class RenderCoordinate:
    """One rendering-fanout coordinate set for ONE deliverable (§8, §12.3).

    `platform` is always concrete — a deliverable-id has no platform-less spelling
    (§7.4: fitted coordinates are platform + language). The other slots may be `None`
    (unselected — resolved by the cascade's L3/L2/floor rungs, §12.3).
    """

    platform: str
    language: str | None
    output_type: str | None
    presentation: str | None


def render_coordinates(
    request: SelectionRequest,
    *,
    pinned_platforms: Sequence[str] = (),
    pinned_languages: Sequence[str] = (),
    pinned_output_types: Sequence[str] = (),
    pinned_presentations: Sequence[str] = (),
) -> tuple[RenderCoordinate, ...]:
    """The rendering fanout (§8): request selection > recipe pin, per axis (§12.3).

    Per rendering axis the coordinate source is the run request when it selects,
    else the recipe's pin set (§8 "may pin rendering targets (else they are supplied
    at run)"; a multi-pin IS a rendering fanout — the step-16 `_single_pin` refusal
    is resolved here by enumeration), else unselected (`None` → cascade defaults).

    Platform has no default rung (§12.3 CA8: per-deliverable routing) and the §7.4 id
    grammar has no platform-less deliverable spelling, so:

    - no platform anywhere AND no other rendering selection → `()` — a compose-only
      plan (wave 0 only; legitimate, §21.6 plan-only workflows);
    - no platform anywhere but OTHER rendering axes selected → a loud typed refusal:
      those selections name deliverable coordinates that cannot exist without routing.
      Dropping them would be a silent skip (§21.6 forbids it); this is a structural
      `invalid-selection`, NOT a pairing veto (Q4 governs resolved pairings only).
    """
    platforms = request.platforms or tuple(pinned_platforms)
    languages = request.languages or tuple(pinned_languages)
    output_types = request.output_types or tuple(pinned_output_types)
    presentations = request.presentations or tuple(pinned_presentations)
    if not platforms:
        selected = [
            axis
            for axis, values in (
                ("languages", languages),
                ("output_types", output_types),
                ("presentations", presentations),
            )
            if values
        ]
        if selected:
            raise FanoutError(
                f"invalid-selection: rendering selection(s) {selected} with no platform "
                "selected or pinned — a deliverable coordinate requires routing "
                "(§12.3: Platform has no default rung; §7.4: no platform-less "
                "deliverable-id exists); select a platform or drop the rendering "
                "selections for a compose-only plan"
            )
        return ()
    return tuple(
        RenderCoordinate(
            platform=platform, language=language, output_type=output_type, presentation=presentation
        )
        for platform, language, output_type, presentation in product(
            platforms,
            _axis_or_unset(languages),
            _axis_or_unset(output_types),
            _axis_or_unset(presentations),
        )
    )


# --- The advisory nonsensical-pairing lint catalog (§8; warn only, never a veto) -----------


@dataclass(frozen=True)
class PairingTrigger:
    """One advisory trigger: a strange/distant format × platform pairing (§8).

    The shape carries ONLY format/platform slots — a folio-based trigger is
    structurally inexpressible (§8: "the lint catalog contains no folio-based pairing
    triggers"; CA3: a folio has no platform or rendering value to diverge from, §9.1).
    """

    format: str
    platform: str
    rationale: str

    def __post_init__(self) -> None:
        _require_slug(self.format, "pairing-trigger format")
        _require_slug(self.platform, "pairing-trigger platform")


#: The shipped catalog: exactly the design's own grounded example class (§8: "e.g.
#: README → LinkedIn"). Advisory only — a hit warns once and NEVER blocks (Q4);
#: an uncataloged pairing resolves silently (the emergent allow-list honors it).
NONSENSICAL_PAIRING_CATALOG: tuple[PairingTrigger, ...] = (
    PairingTrigger(
        format="readme",
        platform="linkedin",
        rationale=(
            "a repository README routed to a social feed — the design's own example "
            "of a strange/distant pairing (§8); honored anyway, warned once"
        ),
    ),
)

#: The structural folio-exclusion proof surface (§8/CA3): the trigger record's exact
#: field set — no folio slot exists, so no folio trigger can be authored.
PAIRING_TRIGGER_FIELDS = tuple(f.name for f in fields(PairingTrigger))


def pairing_advisory(format_id: str, platform_id: str) -> PairingTrigger | None:
    """The catalog lookup: the matching trigger, or None (the normal case).

    Never a filter: the caller emits a one-time `nonsensical-pairing` WARNING on a hit
    (§8/§21.7) and proceeds identically either way.
    """
    for trigger in NONSENSICAL_PAIRING_CATALOG:
        if trigger.format == format_id and trigger.platform == platform_id:
            return trigger
    return None


def goal_set_overloaded(goals: Sequence[str]) -> bool:
    """True when a goal-set stacks more than the advisory threshold (§8: warns, never
    blocks — the caller emits the one-time warning and proceeds)."""
    return len(goals) > GOAL_SET_OVERLOAD_THRESHOLD
