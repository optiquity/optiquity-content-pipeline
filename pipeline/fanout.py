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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from itertools import product
from typing import Any

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
    "coordinate_from_payload",
    "coordinate_payload",
    "goal_set_overloaded",
    "pairing_advisory",
    "render_coordinate_from_payload",
    "render_coordinate_payload",
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
    #: DR-3 (horn (a) / B1): the per-COORDINATE outline DRIVE map. Each key is a
    #: `ContentCombination` coordinate (goals canonicalized to sorted order — the §7.2
    #: goal-set is a set); each value the BARE 64-char lowercase-hex `outline-digest` of an
    #: ALREADY-STORED outline (never raw text — ingest happens upstream). Normalized to a
    #: deterministic tuple of `(coordinate, digest)` pairs, consumed per-combo by
    #: `resolve_plan` (`outline_for`). Absent/empty -> today's behavior, byte-identical.
    outlines: Mapping[ContentCombination, str] | tuple[tuple[ContentCombination, str], ...] = ()
    #: CLI-UX C5c (saved-selection DRIVE): the per-artifact render map — a saved fan-out replayed
    #: 1:1 (§8, authoring D4). It is the FLAT `(ContentCombination, RenderCoordinate)` variant list
    #: (one saved variant = one content coord × one render coord — the product ALREADY applied at
    #: save, C5b); `__post_init__` GROUPS it by the §7.2-canonical content coordinate into a
    #: deterministic `((combo, (render-coord, …)), …)` tuple, so `resolve_plan` drives each artifact
    #: with ITS OWN render coordinates — NEVER the global cartesian product (B4). Two variants that
    #: name the same (content, render) coordinate are a loud refusal (PC2 exactly-once). Empty -> a
    #: normal cartesian request, byte-identical to pre-C5c. Set ONLY on a selection load; it is
    #: mutually exclusive with every content/render axis multi-select and the `outlines` drive map.
    render_map: (
        Mapping[ContentCombination, Sequence[RenderCoordinate]]
        | Sequence[tuple[ContentCombination, RenderCoordinate]]
    ) = ()

    def __post_init__(self) -> None:
        _require_slug(self.recipe, "recipe")
        for axis in (*CONTENT_AXES, *RENDERING_AXES):
            object.__setattr__(self, axis, _normalize_axis(getattr(self, axis), axis))
        object.__setattr__(self, "goal_sets", _normalize_goal_sets(self.goal_sets))
        object.__setattr__(self, "outlines", _normalize_outlines(self.outlines))
        object.__setattr__(self, "render_map", _normalize_render_map(self.render_map))
        if self.render_map:
            self._refuse_driven_conflicts()

    def _refuse_driven_conflicts(self) -> None:
        """A DRIVEN request (a loaded saved selection) replays its EXPLICIT grouped variant list;
        an axis multi-select, a goal-set variant, or an outline drive map alongside it would re-open
        the cartesian fan-out the drive exists to avoid — refuse loudly (§3.1), never silently drop
        one. `recipe` (the base reference) is the ONLY other field a driven request carries."""
        conflicts = [axis for axis in (*CONTENT_AXES, *RENDERING_AXES) if getattr(self, axis)]
        if self.goal_sets:
            conflicts.append("goal_sets")
        if self.outlines:
            conflicts.append("outlines")
        if conflicts:
            raise FanoutError(
                "invalid-selection: a saved-selection DRIVE (`render_map`) replays an explicit "
                f"fan-out 1:1 — it cannot combine with {sorted(conflicts)} (that would re-expand "
                "the curated set); drive the selection alone (§8, authoring D4)"
            )

    def outline_for(self, combo: ContentCombination) -> str | None:
        """The DRIVE `outline-digest` for one content coordinate, or None (§8 / DR-3).

        Goals canonicalize to sorted order before the lookup (the §7.2 goal-set is a set),
        so the map matches artifact identity regardless of authored goal order. `resolve_plan`
        calls this per `ContentCombination` to thread the digest into the preimage; an absent
        coordinate resolves outline-less — the byte-identical 4-key id (horn (a) adds no key)."""
        key = _canonical_coordinate(combo)
        for stored, digest in self.outlines:
            if stored == key:
                return digest
        return None


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


# --- DR-3 outline DRIVE coordinates (the per-item outline map; §8 / horn (a)) ---------------

_OUTLINE_DIGEST_LEN = 64
_OUTLINE_DIGEST_ALPHABET = frozenset("0123456789abcdef")


def _require_outline_digest_ref(value: object, where: str) -> str:
    """A BARE 64-char lowercase-hex `outline-digest` (a content address, NEVER a §7.4 id).

    Validated DIRECTLY here (pure enumeration — no `pipeline.ids` / `pipeline.outline` import):
    exactly 64 lowercase-hex chars. `pipeline.ids._require_outline_digest` re-checks it at the
    mint boundary, so this is the request-boundary teeth (mirrors `_require_slug`)."""
    if not (
        isinstance(value, str)
        and len(value) == _OUTLINE_DIGEST_LEN
        and set(value) <= _OUTLINE_DIGEST_ALPHABET
    ):
        raise FanoutError(
            f"invalid-selection: {where} must be a BARE 64-char lowercase-hex outline-digest "
            f"(a content address from pipeline.outline.outline_digest, NOT a §7.4 id), got "
            f"{value!r}"
        )
    return value


def _canonical_coordinate(combo: ContentCombination) -> ContentCombination:
    """The §7.2-canonical coordinate: goals SORTED (the goal-set is a set), everything else
    as-is. Two coordinates differing only in authored goal ORDER canonicalize equal — they
    name ONE artifact (the preimage sorts goals), so the outline map keys on the sorted form."""
    goals = tuple(sorted(combo.goals)) if combo.goals is not None else None
    return ContentCombination(
        topic=combo.topic,
        persona=combo.persona,
        format=combo.format,
        voice=combo.voice,
        goals=goals,
    )


def _coordinate_sort_key(combo: ContentCombination) -> tuple[Any, ...]:
    return (
        combo.topic or "",
        combo.persona or "",
        combo.format or "",
        combo.voice or "",
        combo.goals if combo.goals is not None else (),
    )


def _normalize_outlines(raw: object) -> tuple[tuple[ContentCombination, str], ...]:
    """Normalize `SelectionRequest.outlines` to a deterministic tuple of
    `(canonical-coordinate, digest)` pairs. Accepts a `Mapping[ContentCombination, str]` (or
    an already-normalized sequence of pairs). Each coordinate's axis slugs validate via the
    §7.4 slug alphabet; each digest is a bare 64-hex content address; a duplicate canonical
    coordinate is loud (never a silent last-wins). Empty -> `()` (outline-less, byte-neutral)."""
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        pairs = list(raw.items())
    elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        pairs = list(raw)
    else:
        raise FanoutError(
            "invalid-selection: outlines must be a mapping of ContentCombination coordinate "
            f"-> outline-digest (DR-3 drive map), got {type(raw).__name__}: {raw!r}"
        )
    normalized: dict[ContentCombination, str] = {}
    for pair in pairs:
        try:
            combo, digest = pair
        except (TypeError, ValueError) as exc:
            raise FanoutError(
                "invalid-selection: an outlines entry must be a (coordinate, digest) pair, "
                f"got {pair!r}"
            ) from exc
        if not isinstance(combo, ContentCombination):
            raise FanoutError(
                "invalid-selection: an outline map key must be a ContentCombination coordinate "
                f"(topic/persona/format/voice/goals), got {type(combo).__name__}: {combo!r}"
            )
        for name, value in (
            ("topic", combo.topic),
            ("persona", combo.persona),
            ("format", combo.format),
            ("voice", combo.voice),
        ):
            if value is not None:
                _require_slug(value, f"outline coordinate {name}")
        if combo.goals is not None:
            for goal in combo.goals:
                _require_slug(goal, "outline coordinate goal")
        canonical = _canonical_coordinate(combo)
        if canonical in normalized:
            raise FanoutError(
                "invalid-selection: two outline entries name the same coordinate "
                f"{_coordinate_sort_key(canonical)!r} — one outline drives one artifact "
                "(DR-3); loud, never a silent last-wins"
            )
        normalized[canonical] = _require_outline_digest_ref(digest, "outline-digest")
    return tuple(sorted(normalized.items(), key=lambda kv: _coordinate_sort_key(kv[0])))


def coordinate_payload(combo: ContentCombination) -> dict[str, Any]:
    """The JSON-native projection of one content coordinate (the token/wire form; §20).

    Round-trips with `coordinate_from_payload`; `None` axes stay `None`, goals as a list or
    `None`. The single source of the coordinate shape the session layer serializes."""
    return {
        "topic": combo.topic,
        "persona": combo.persona,
        "format": combo.format,
        "voice": combo.voice,
        "goals": list(combo.goals) if combo.goals is not None else None,
    }


def coordinate_from_payload(payload: Mapping[str, Any]) -> ContentCombination:
    """Reconstruct a `ContentCombination` coordinate from its JSON projection (§20 round-trip)."""
    if not isinstance(payload, Mapping):
        raise FanoutError(
            f"invalid-selection: an outline coordinate must be a mapping, got "
            f"{type(payload).__name__}"
        )
    goals = payload.get("goals")
    return ContentCombination(
        topic=payload.get("topic"),
        persona=payload.get("persona"),
        format=payload.get("format"),
        voice=payload.get("voice"),
        goals=tuple(goals) if goals is not None else None,
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


# --- The saved-selection DRIVE map (CLI-UX C5c: the explicit fan-out replayed 1:1; §8) ------


def render_coordinate_payload(coordinate: RenderCoordinate) -> dict[str, Any]:
    """The JSON-native projection of one render coordinate (the token/wire form; §20).

    Round-trips with `render_coordinate_from_payload`; `platform` is always present (§7.4: a
    deliverable requires routing), the other three slots OMIT when `None` (floor-faithful — they
    ride the cascade on reload). The single source of the render-coordinate shape the session layer
    serializes into the token inputs so `continue-session` re-resolves the driven plan 1:1."""
    payload: dict[str, Any] = {"platform": coordinate.platform}
    if coordinate.language is not None:
        payload["language"] = coordinate.language
    if coordinate.output_type is not None:
        payload["output_type"] = coordinate.output_type
    if coordinate.presentation is not None:
        payload["presentation"] = coordinate.presentation
    return payload


def render_coordinate_from_payload(payload: Mapping[str, Any]) -> RenderCoordinate:
    """Reconstruct a `RenderCoordinate` from its JSON projection (§20 round-trip). A concrete
    `platform` is MANDATORY (§7.4: no platform-less deliverable); the other slots default to
    `None` (unselected — the cascade supplies them)."""
    if not isinstance(payload, Mapping) or "platform" not in payload:
        raise FanoutError(
            "invalid-selection: a render coordinate must be a mapping with a concrete `platform` "
            f"(§7.4: a deliverable requires routing), got {payload!r}"
        )
    return RenderCoordinate(
        platform=payload["platform"],
        language=payload.get("language"),
        output_type=payload.get("output_type"),
        presentation=payload.get("presentation"),
    )


def _render_sort_key(coordinate: RenderCoordinate) -> tuple[str, str, str, str]:
    return (
        coordinate.platform,
        coordinate.language or "",
        coordinate.output_type or "",
        coordinate.presentation or "",
    )


def _validate_render_coordinate(coordinate: RenderCoordinate, where: str) -> None:
    _require_slug(coordinate.platform, f"{where} platform")
    for name, value in (
        ("language", coordinate.language),
        ("output_type", coordinate.output_type),
        ("presentation", coordinate.presentation),
    ):
        if value is not None:
            _require_slug(value, f"{where} {name}")


def _validate_content_coordinate(combo: ContentCombination, where: str) -> None:
    for name, value in (
        ("topic", combo.topic),
        ("persona", combo.persona),
        ("format", combo.format),
        ("voice", combo.voice),
    ):
        if value is not None:
            _require_slug(value, f"{where} {name}")
    if combo.goals is not None:
        for goal in combo.goals:
            _require_slug(goal, f"{where} goal")


def _normalize_render_map(
    raw: object,
) -> tuple[tuple[ContentCombination, tuple[RenderCoordinate, ...]], ...]:
    """Group the FLAT saved-selection variant list into the deterministic canonical-coordinate-keyed
    DRIVE map C5c replays 1:1 (§8, authoring D4).

    Each saved variant is ONE content coordinate × ONE render coordinate (the run's product ALREADY
    applied at save, C5b). Grouping by the §7.2-canonical content coordinate collapses the variants
    that SHARE one artifact (e.g. two platforms of one topic) back into ONE item carrying BOTH the
    coordinates — so `resolve_plan` feeds `_resolve_deliverables` one group at a time and
    `artifact_ids()` gains NO duplicate (PC2 exactly-once cover; the C5c-flagged grouping point).
    Two variants naming the SAME (content, render) coordinate are a LOUD typed refusal (never a
    silent last-wins) — mirroring the DR-3 outline dedupe. Accepts either the flat
    `(ContentCombination, RenderCoordinate)` pair sequence or a `{coordinate: [render, …]}` mapping.
    Empty -> `()` (not driven; byte-identical to a normal cartesian request). NO `product` is used —
    the fan-out is the EXPLICIT saved array, never re-expanded."""
    if not raw:
        return ()
    pairs: list[tuple[Any, Any]] = []
    if isinstance(raw, Mapping):
        for combo, coords in raw.items():
            if isinstance(coords, RenderCoordinate):
                pairs.append((combo, coords))
            elif isinstance(coords, Sequence) and not isinstance(coords, str | bytes):
                for coord in coords:
                    pairs.append((combo, coord))
            else:
                raise FanoutError(
                    "invalid-selection: a render_map mapping value must be a RenderCoordinate or "
                    f"a sequence of them, got {type(coords).__name__}: {coords!r}"
                )
    elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes):
        pairs = list(raw)
    else:
        raise FanoutError(
            "invalid-selection: render_map must be a sequence of (content-coordinate, "
            f"render-coordinate) pairs (the saved-selection DRIVE), got {type(raw).__name__}"
        )
    grouped: dict[ContentCombination, dict[RenderCoordinate, None]] = {}
    for pair in pairs:
        try:
            combo, coordinate = pair
        except (TypeError, ValueError) as exc:
            raise FanoutError(
                "invalid-selection: a render_map entry must be a (content-coordinate, "
                f"render-coordinate) pair, got {pair!r}"
            ) from exc
        if not isinstance(combo, ContentCombination):
            raise FanoutError(
                "invalid-selection: a render_map content key must be a ContentCombination "
                f"coordinate, got {type(combo).__name__}: {combo!r}"
            )
        if not isinstance(coordinate, RenderCoordinate):
            raise FanoutError(
                "invalid-selection: a render_map render value must be a RenderCoordinate, "
                f"got {type(coordinate).__name__}: {coordinate!r}"
            )
        _validate_content_coordinate(combo, "render_map coordinate")
        _validate_render_coordinate(coordinate, "render_map render")
        canonical = _canonical_coordinate(combo)
        bucket = grouped.setdefault(canonical, {})
        if coordinate in bucket:
            raise FanoutError(
                "invalid-selection: two saved variants name the same (content, render) coordinate "
                f"({_coordinate_sort_key(canonical)!r}, {_render_sort_key(coordinate)!r}) — the "
                "plan is an exactly-once cover (PC2, §22.2); loud, never a silent last-wins"
            )
        bucket[coordinate] = None
    return tuple(
        (combo, tuple(sorted(bucket, key=_render_sort_key)))
        for combo, bucket in sorted(grouped.items(), key=lambda kv: _coordinate_sort_key(kv[0]))
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
