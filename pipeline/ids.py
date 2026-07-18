"""The §7 id family: preimage canonicalization, id minting, and the §7.4 string grammar.

Design authority: `docs/design.md` §7 — "the single authority for the id family":

- §7.1 the family: `artifact-id` (compose key, folio-membership key), `fitted-id` (reconcile
  cache + claim key = artifact + platform + language), `deliverable-id` (serialized-bytes key
  = fitted + output-type + presentation), part addressing (`(artifact-id, part-id)` for
  composite-format parts, `(deliverable-id, part-id)` for reconcile-split parts — §7.1 names
  exactly these two owners), `f-<hex12>` folios, `r-<hex16>` runs.
- §7.2 the canonical artifact preimage: per single-valued content dimension
  `(resolved-entry-id, delta-vs-floor map)`; Goal as the sorted, deduped
  `(goal-entry-id, delta map)` pair-list, entering exactly once; `source-subset` (the
  resolved pool selection) + `source-commit` (the canonical `{source-instance-id → commit}`
  map over that subset, one commit per instance).
- §7.3 identity exclusions: `schema_version` and the artifact `metadata` bag are NEVER id
  inputs — refused at the constructor boundary AND re-checked at every attr-NAME position
  (dimension/goal delta-map keys) by the mint-time shape guard, so they provably cannot
  reach a mintable preimage. Nested attribute VALUES are data, never scanned: a value map
  legitimately keyed `metadata` inside an attribute value is not the §7.3 metadata bag.
- §7.4 the string grammar: the safe alphabet, structural coordinate segments, `~` part
  suffixes, per-level `_hex12` revision qualifiers (≤ 2 per id; language segment = fit
  revision, presentation segment = serialize revision; `_` anywhere else = invalid id),
  prefix-typed POSITIONAL parsing (family from the root prefix, level from the dot-segment
  count, `~` split first — never a general matcher), the 40-char slug cap giving the
  249 ≤ 255 worst-case filename bound, filename exactness (claim/marker filename = the id,
  no extension; byte outputs MAY append an extension only when the result still fits 255
  bytes), and the mint-time preimage check (same id + different recorded preimage = loud
  failure, never silent reuse — the §22.3 S0 hook).

Canonicalization and digests are IMPORTED from `pipeline.canonical` (§7.4 digest form:
SHA-256; hex16 roots for artifact/run, hex12 for folios and revision qualifiers), never
reimplemented. Slug validation rides `pipeline.attrtypes`' public `ref` validator (the §7.4
slug alphabet's single implementation).

In-latitude decisions (step-10 coder; grounded in the report):

- **The preimage JSON shape is FROZEN** (changing any key would churn every artifact-id):
  top-level keys exactly `dimensions` / `goals` / `source-subset` / `source-commit`;
  `dimensions` maps each of the four single-valued content dimensions (§7.2: topic, persona,
  format, voice) to `{"entry": <entry-id>, "delta": <canonical delta map>}`; `goals` is the
  sorted deduped `[[goal-entry-id, delta-map], …]` pair-list.
- `build_artifact_preimage` returns the canonical **pure-JSON value** (a
  `canonical_json_str` → `json.loads` round-trip): dates are already ISO strings, so the
  returned object is byte-stable under storage round-trips and equals what a recorded
  preimage looks like when read back from the IR binding (§15).
- Top-level Python `set`/`frozenset` attribute values canonicalize via
  `canonical.canonical_set` (§12.4: union-combined sets feed the same canonicalization);
  raw sets nested deeper have no canonical form and refuse loudly.
- A goal entry appearing twice with the SAME delta dedupes (§7.2 "sorted, deduped");
  twice with DIFFERENT deltas is ambiguous and refused.
- The commit-map keys must equal the source-subset exactly (§7.2: "one commit per
  instance" over the resolved subset); commits are opaque non-empty strings (the folder
  adapter's pin need not be a git sha — §6.1).
- Folio/run mint preimages are consumer-defined (§7 fixes only their encodings; the seeds
  belong to plan steps 20/31); `mint_folio_id`/`mint_run_id` digest whatever canonical
  object the consumer passes and honor the same preimage-check hook.
- Parts attach to artifact-level and deliverable-level owners ONLY (§7.1 names exactly
  those two); a `~` on a fitted, folio, or run id is refused. Split ordinals render via
  `split_part_label` (width = max(2, len(str(part_count))) — `p01`…`p99`, widening past 99,
  §7.4); parse keeps part labels as opaque slugs (a Format role slug may look like `p03` —
  §7.4's own namespace note).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value
from pipeline.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    canonical_json_str,
    canonical_set,
    digest_hex12,
    digest_hex16,
)

__all__ = [
    "CONTENT_DIMENSIONS",
    "FILENAME_BYTE_LIMIT",
    "IDENTITY_EXCLUSIONS",
    "EntryBinding",
    "IdError",
    "PipelineId",
    "PreimageError",
    "PreimageMismatchError",
    "build_artifact_preimage",
    "delta_vs_floor",
    "deliverable_id",
    "fitted_id",
    "mint_artifact_id",
    "mint_folio_id",
    "mint_run_id",
    "output_filename",
    "parse_id",
    "part_id",
    "preimage_check",
    "split_part_label",
]

#: §7.2: the four SINGLE-valued content dimensions — `resolved-entry-id(D)` is defined for
#: exactly these; Goal (set-valued) never enters the per-dimension loop.
CONTENT_DIMENSIONS = ("topic", "persona", "format", "voice")

#: §7.3: never id inputs — refused at the constructor boundary, provably absent downstream.
IDENTITY_EXCLUSIONS = frozenset({"schema_version", "metadata"})

#: §7.4: the 255-byte filename limit the length arithmetic is proven against.
FILENAME_BYTE_LIMIT = 255

# §7.4 grammar tables: root prefix ↔ family, and each family's root digest width.
_FAMILY_PREFIX = {"artifact": "a", "folio": "f", "run": "r"}
_PREFIX_FAMILY = {prefix: family for family, prefix in _FAMILY_PREFIX.items()}
_ROOT_HEX_LEN = {"artifact": 16, "folio": 12, "run": 16}

_ROOT_RE = re.compile(r"\A([a-z])-([0-9a-f]+)\Z")
_HEX12_RE = re.compile(r"\A[0-9a-f]{12}\Z")
#: §7.2 (DR-3, D-7): an `outline-digest` is the FULL 64-char lowercase-hex SHA-256 from
#: `pipeline.outline.outline_digest` — a bare content hash, NEVER a §7.4 id root (no `o-`).
_OUTLINE_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
#: §7.4 safe alphabet: [a-z0-9] + the three separators + the qualifier mark. Nothing else.
_SAFE_ALPHABET_RE = re.compile(r"\A[a-z0-9.\-~_]+\Z")
#: §7.4: "a conventional format extension" — one lowercase alphanumeric run, never dotted.
_EXTENSION_RE = re.compile(r"\A[a-z0-9]+\Z")

#: Slug validation = the §7.4 slug alphabet's single implementation (attrtypes' `ref` type).
_REF_SPEC = AttrTypeSpec(kind="ref")


class IdError(ValueError):
    """An id string or component violating the §7.4 grammar — refused, never repaired."""

    code = "invalid-id"


class PreimageError(ValueError):
    """A §7.2 preimage input with no canonical form, or a §7.3 exclusion — refused."""

    code = "invalid-preimage"


class PreimageMismatchError(ValueError):
    """§7.4 mint-time preimage check: the id exists with a DIFFERENT recorded preimage."""

    code = "preimage-mismatch"


def _slug_ok(value: object) -> bool:
    """True iff `value` is a §7.4 slug ([a-z0-9-], 1-40, no edge '-') — via the ref validator."""
    try:
        validate_value(_REF_SPEC, value)
    except ValueValidationError:
        return False
    return True


def _require_slug(value: object, what: str) -> None:
    if not _slug_ok(value):
        raise IdError(
            f"invalid-id: {what} {value!r} is not a §7.4 slug ([a-z0-9-], 1-40 chars, "
            "no leading/trailing '-')"
        )


def _require_hex12(value: object, what: str) -> None:
    if not isinstance(value, str) or not _HEX12_RE.match(value):
        raise IdError(
            f"invalid-id: a {what} qualifier is exactly 12 lowercase hex chars (§7.4), "
            f"got {value!r}"
        )


# ---------------------------------------------------------------------------
# The id value object (§7.1/§7.4): one shape, five levels, one renderer.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineId:
    """A parsed/parseable id: family + root digest + optional coordinates/qualifiers/part.

    Construction validates every §7.4 structural invariant, so any `PipelineId` instance
    renders to a valid id string and `parse_id(x.render()) == x` (round-trip by
    construction). Levels are positional: bare root = artifact; +platform/language =
    fitted; +output-type/presentation = deliverable.
    """

    family: str
    root_hex: str
    platform: str | None = None
    language: str | None = None
    fit_revision: str | None = None
    output_type: str | None = None
    presentation: str | None = None
    serialize_revision: str | None = None
    part: str | None = None

    def __post_init__(self) -> None:
        if self.family not in _FAMILY_PREFIX:
            raise IdError(
                f"invalid-id: unknown id family {self.family!r} "
                "(§7.4 families: artifact, folio, run)"
            )
        want = _ROOT_HEX_LEN[self.family]
        if not isinstance(self.root_hex, str) or not re.fullmatch(
            rf"[0-9a-f]{{{want}}}", self.root_hex
        ):
            raise IdError(
                f"invalid-id: a {self.family} root is exactly {want} lowercase hex chars "
                f"(§7.4), got {self.root_hex!r}"
            )
        if self.family != "artifact":
            extras = (
                self.platform,
                self.language,
                self.fit_revision,
                self.output_type,
                self.presentation,
                self.serialize_revision,
                self.part,
            )
            if any(v is not None for v in extras):
                raise IdError(
                    f"invalid-id: {self.family} ids carry no coordinate segments, "
                    "qualifiers, or parts (§7.4)"
                )
            return
        # Artifact family: levels are all-or-nothing coordinate pairs (§7.4 template).
        if (self.platform is None) != (self.language is None):
            raise IdError("invalid-id: the fitted level requires BOTH platform and language (§7.1)")
        if (self.output_type is None) != (self.presentation is None):
            raise IdError(
                "invalid-id: the deliverable level requires BOTH output-type and "
                "presentation (§7.1)"
            )
        if self.output_type is not None and self.platform is None:
            raise IdError(
                "invalid-id: deliverable coordinates extend the fitted coordinates — "
                "platform/language are missing (§7.1)"
            )
        for value, what in (
            (self.platform, "platform"),
            (self.language, "language"),
            (self.output_type, "output-type"),
            (self.presentation, "presentation"),
            (self.part, "part"),
        ):
            if value is not None:
                _require_slug(value, what)
        if self.fit_revision is not None:
            if self.language is None:
                raise IdError(
                    "invalid-id: a fit revision attaches to the language segment and "
                    "there is none (§7.4)"
                )
            _require_hex12(self.fit_revision, "fit-revision")
        if self.serialize_revision is not None:
            if self.presentation is None:
                raise IdError(
                    "invalid-id: a serialize revision attaches to the presentation "
                    "segment and there is none (§7.4)"
                )
            _require_hex12(self.serialize_revision, "serialize-revision")
        if self.part is not None and self.level == "fitted":
            raise IdError(
                "invalid-id: parts address artifacts and deliverables only, never a "
                "fitted id (§7.1)"
            )

    @property
    def level(self) -> str:
        """The id's level: artifact/fitted/deliverable (a-family), or folio/run."""
        if self.family != "artifact":
            return self.family
        if self.presentation is not None:
            return "deliverable"
        if self.platform is not None:
            return "fitted"
        return "artifact"

    def render(self) -> str:
        """The exact §7.4 string. Byte-stable: `parse_id(x.render()) == x`."""
        pieces = [f"{_FAMILY_PREFIX[self.family]}-{self.root_hex}"]
        if self.platform is not None:
            pieces.append(f".{self.platform}.{self.language}")
            if self.fit_revision is not None:
                pieces.append(f"_{self.fit_revision}")
        if self.output_type is not None:
            pieces.append(f".{self.output_type}.{self.presentation}")
            if self.serialize_revision is not None:
                pieces.append(f"_{self.serialize_revision}")
        if self.part is not None:
            pieces.append(f"~{self.part}")
        return "".join(pieces)


# ---------------------------------------------------------------------------
# Parsing (§7.4): prefix-typed and POSITIONAL — family from the root prefix, level
# from the dot-segment count, `~` split first. Never a general matcher.
# ---------------------------------------------------------------------------


def _plain_segment(segment: str, what: str) -> str:
    """A coordinate segment that never carries a qualifier (§7.4: segments 2 and 4)."""
    if "_" in segment:
        raise IdError(
            "invalid-id: a _ qualifier may attach only to the segment that closes its "
            f"level (language or presentation) — never {what} (§7.4)"
        )
    _require_slug(segment, what)
    return segment


def _qualified_segment(segment: str, what: str, qualifier_what: str) -> tuple[str, str | None]:
    """A level-closing segment (§7.4: 3 = language, 5 = presentation): slug [+ _hex12]."""
    base, sep, qualifier = segment.partition("_")
    if not sep:
        _require_slug(base, what)
        return base, None
    if "_" in qualifier:
        raise IdError(
            f"invalid-id: at most one qualifier per level — {segment!r} carries more (§7.4)"
        )
    _require_hex12(qualifier, qualifier_what)
    _require_slug(base, what)
    return base, qualifier


def parse_id(id_str: str) -> PipelineId:
    """Parse a §7.4 id string. Prefix-typed, positional, byte-exact round-trip.

    Parse order per §7.4: split the `~` part suffix FIRST, then dots, then strip a
    `_hex12` qualifier from segments 3 and 5 only. Family = root prefix; level =
    dot-segment count (0 = root, 2 = fitted, 4 = deliverable). Anything else is refused
    with a typed `IdError` — never repaired.
    """
    if not isinstance(id_str, str) or not id_str:
        raise IdError("invalid-id: an id is a non-empty string")
    if not _SAFE_ALPHABET_RE.match(id_str):
        if any(c.isupper() for c in id_str):
            raise IdError(
                "invalid-id: uppercase is refused — ids are lowercase-only for "
                f"case-insensitive-filesystem safety (§7.4): {id_str!r}"
            )
        raise IdError(
            f"invalid-id: character outside the §7.4 safe alphabet [a-z0-9.-~_] in {id_str!r}"
        )
    # 1. Split the `~` part suffix first (§7.4 parse order).
    owner, tilde, part_label = id_str.partition("~")
    part: str | None = None
    if tilde:
        if "~" in part_label:
            raise IdError(f"invalid-id: at most one ~ part suffix (§7.4): {id_str!r}")
        _require_slug(part_label, "part")
        part = part_label
    # 2. Split coordinate segments on dots.
    segments = owner.split(".")
    root = segments[0]
    # 3. The root never carries a qualifier and names the family by prefix.
    if "_" in root:
        raise IdError(
            "invalid-id: the root segment never carries a _ qualifier — a qualifier "
            "attaches only to the segment that closes its level (§7.4)"
        )
    match = _ROOT_RE.match(root)
    if not match or match.group(1) not in _PREFIX_FAMILY:
        raise IdError(
            f"invalid-id: malformed root segment {root!r} — expected a-<hex16>, "
            "f-<hex12>, or r-<hex16> (§7.4)"
        )
    family = _PREFIX_FAMILY[match.group(1)]
    root_hex = match.group(2)
    if len(root_hex) != _ROOT_HEX_LEN[family]:
        raise IdError(
            f"invalid-id: a {family} root is exactly {_ROOT_HEX_LEN[family]} lowercase "
            f"hex chars (§7.4), got {len(root_hex)} in {root!r}"
        )
    coordinate_count = len(segments) - 1
    if family != "artifact":
        if coordinate_count:
            raise IdError(
                f"invalid-id: {family} ids carry no coordinate segments (§7.4): {id_str!r}"
            )
        if part is not None:
            raise IdError(
                "invalid-id: parts address artifacts and deliverables only (§7.1), "
                f"never a {family} id"
            )
        return PipelineId(family=family, root_hex=root_hex)
    # 4. Level inference by dot count (§7.4): 0 = artifact, 2 = fitted, 4 = deliverable.
    if coordinate_count not in (0, 2, 4):
        raise IdError(
            f"invalid-id: {coordinate_count} coordinate segment(s) name no level — bare "
            f"root = artifact, +2 = fitted, +4 = deliverable (§7.4): {id_str!r}"
        )
    platform = language = fit_revision = output_type = presentation = serialize_revision = None
    if coordinate_count >= 2:
        platform = _plain_segment(segments[1], "platform")
        language, fit_revision = _qualified_segment(segments[2], "language", "fit-revision")
    if coordinate_count == 4:
        output_type = _plain_segment(segments[3], "output-type")
        presentation, serialize_revision = _qualified_segment(
            segments[4], "presentation", "serialize-revision"
        )
    if part is not None and coordinate_count == 2:
        raise IdError(
            "invalid-id: parts address artifacts and deliverables only, never a fitted "
            f"id (§7.1): {id_str!r}"
        )
    return PipelineId(
        family="artifact",
        root_hex=root_hex,
        platform=platform,
        language=language,
        fit_revision=fit_revision,
        output_type=output_type,
        presentation=presentation,
        serialize_revision=serialize_revision,
        part=part,
    )


# ---------------------------------------------------------------------------
# Structural extension (§7.1/§7.4): coordinates append as literal slug segments;
# qualifiers flow into deeper ids by prefix containment.
# ---------------------------------------------------------------------------


def fitted_id(
    artifact_id: str, platform: str, language: str, *, fit_revision: str | None = None
) -> str:
    """`<artifact-id>.<platform>.<language>[_hex12]` — extends a BARE artifact root (§7.1)."""
    owner = parse_id(artifact_id)
    if owner.level != "artifact" or owner.part is not None:
        raise IdError(
            "invalid-id: fitted coordinates extend a bare artifact root (§7.1), got "
            f"level {owner.level!r}{' with a part suffix' if owner.part is not None else ''}"
        )
    return replace(owner, platform=platform, language=language, fit_revision=fit_revision).render()


def deliverable_id(
    fitted: str, output_type: str, presentation: str, *, serialize_revision: str | None = None
) -> str:
    """`<fitted-id>.<output-type>.<presentation>[_hex12]` — a fit revision carries through."""
    owner = parse_id(fitted)
    if owner.level != "fitted":
        raise IdError(
            "invalid-id: deliverable coordinates extend a fitted id (§7.1), got level "
            f"{owner.level!r}"
        )
    return replace(
        owner,
        output_type=output_type,
        presentation=presentation,
        serialize_revision=serialize_revision,
    ).render()


def part_id(owner_id: str, part: str) -> str:
    """`<owner-id>~<part>` — owners are artifact- or deliverable-level ONLY (§7.1)."""
    owner = parse_id(owner_id)
    if owner.part is not None:
        raise IdError(f"invalid-id: {owner_id!r} already carries a part suffix (§7.4)")
    if owner.level not in ("artifact", "deliverable"):
        raise IdError(
            "invalid-id: parts address artifacts and deliverables only (§7.1), got "
            f"level {owner.level!r}"
        )
    return replace(owner, part=part).render()


def split_part_label(ordinal: int, part_count: int) -> str:
    """A reconcile-split part label (§7.4): `p01`…`p99`, widening past 99 parts.

    Width = the natural width of the part count, floored at two digits, fixed per saved
    deliverable — consistent with split part-ids being save-stable but not
    re-chunk-reproducible (§9.5).
    """
    for name, value in (("ordinal", ordinal), ("part_count", part_count)):
        if not isinstance(value, int) or isinstance(value, bool):
            raise IdError(f"invalid-id: split-part {name} must be an int, got {value!r}")
    if part_count < 1 or not 1 <= ordinal <= part_count:
        raise IdError(
            f"invalid-id: split-part ordinal must satisfy 1 <= ordinal <= part_count, "
            f"got ordinal {ordinal} of {part_count}"
        )
    width = max(2, len(str(part_count)))
    return f"p{ordinal:0{width}d}"


def output_filename(id_str: str, extension: str) -> str:
    """A Layer-2 byte-output filename: the id, plus `.{extension}` ONLY when it fits (§7.4).

    Claim files and folio member markers never call this — their filename is the id
    EXACTLY, no extension (§13.3, §22.3). The extension is never part of the id; when
    appending would exceed the 255-byte filename bound, the extension-free name (always
    valid) is returned instead.
    """
    parse_id(id_str)  # the id is authoritative and must stand alone (§7.4)
    if not isinstance(extension, str) or not _EXTENSION_RE.match(extension):
        raise IdError(
            "invalid-id: a filename extension is one lowercase [a-z0-9]+ run (§7.4 — "
            f"it is never part of the id), got {extension!r}"
        )
    candidate = f"{id_str}.{extension}"
    if len(candidate.encode("utf-8")) <= FILENAME_BYTE_LIMIT:
        return candidate
    return id_str


# ---------------------------------------------------------------------------
# The §7.2 canonical artifact preimage: delta-vs-floor, per-dimension maps, the
# sorted deduped goal pair-list, source-subset + commit-map.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EntryBinding:
    """One resolved entry: its id, its effective values, and its schema-default floor.

    `effective` holds the dimension's effective attribute values after the cascade
    (§12); `defaults` holds the schema-default floor (§11.1). Only deviations
    (effective ≠ default, by canonical rendering) enter the identity preimage (§7.2).
    """

    entry_id: str
    effective: Mapping[str, Any] = field(default_factory=dict)
    defaults: Mapping[str, Any] = field(default_factory=dict)


def _canonical_value(value: Any, where: str) -> Any:
    """Vet one attribute value for the preimage; canonicalize top-level sets (§12.4)."""
    try:
        if isinstance(value, set | frozenset):
            return canonical_set(value)
        canonical_json_str(value)  # validation only — refuses non-canonical values loudly
        return value
    except CanonicalizationError as exc:
        raise PreimageError(f"invalid-preimage: {where}: {exc}") from exc


def delta_vs_floor(
    effective: Mapping[str, Any], defaults: Mapping[str, Any], *, where: str = "entry"
) -> dict[str, Any]:
    """The §7.2 canonical delta map: attrs whose effective value ≠ schema default.

    An attribute at its floor is ABSENT from the map — a newly shipped attribute at its
    default churns no id (§7.2). Equality is canonical-rendering equality (type-exact:
    `True` never equals `1`). An attribute with no declared default always enters when
    set. The §7.3 exclusions (`schema_version`, `metadata`) are refused outright.
    """
    if not isinstance(effective, Mapping) or not isinstance(defaults, Mapping):
        raise PreimageError(
            f"invalid-preimage: {where}: effective values and defaults must be mappings"
        )
    delta: dict[str, Any] = {}
    for attr, raw in effective.items():
        if not isinstance(attr, str) or not attr:
            raise PreimageError(
                f"invalid-preimage: {where}: attribute names must be non-empty strings, "
                f"got {attr!r}"
            )
        if attr in IDENTITY_EXCLUSIONS:
            raise PreimageError(
                f"invalid-preimage: {where}: {attr!r} is never an identity input (§7.3) "
                "and must not reach the preimage constructor"
            )
        value = _canonical_value(raw, f"{where}.{attr}")
        if attr in defaults:
            floor = _canonical_value(defaults[attr], f"{where}.{attr} (default)")
            if canonical_json_str(floor) == canonical_json_str(value):
                continue  # at the schema-default floor — absent from the map (§7.2)
        delta[attr] = value
    return delta


def _require_entry_id(value: object, what: str) -> None:
    if not _slug_ok(value):
        raise PreimageError(
            f"invalid-preimage: {what} id {value!r} is not a §7.4 slug "
            "([a-z0-9-], 1-40 chars, no leading/trailing '-'; §11.4 `x-` prefix included)"
        )


def _require_outline_digest(value: object) -> str:
    """Validate an OPTIONAL §7.2 `outline-digest`: a 64-char lowercase-hex SHA-256 (DR-3 D-7).

    The digest is a `pipeline.outline.outline_digest` output. The strict lowercase-hex
    WHITELIST is a stronger gate than any blacklist: a `[0-9a-f]{64}` string can be
    NEITHER a §7.3 exclusion (`schema_version`/`metadata` are not 64-hex) NOR a secret
    shape (every `ir.looks_secret_shaped` pattern needs a character outside the hex
    alphabet — a `-`, `:`, `@`, `_`, or an uppercase letter), so this one form check
    provably excludes both WITHOUT importing `pipeline.ir` (which imports `pipeline.ids`
    — a cycle). Any non-str / non-64 / non-lowercase-hex value is refused loudly.
    """
    if not isinstance(value, str) or not _OUTLINE_DIGEST_RE.fullmatch(value):
        raise PreimageError(
            "invalid-preimage: outline-digest must be the 64-char lowercase-hex SHA-256 "
            "from pipeline.outline.outline_digest (a bare content hash, never a §7.4 id "
            f"root, never a §7.3 exclusion or secret shape), got {value!r}"
        )
    return value


def build_artifact_preimage(
    *,
    topic: EntryBinding,
    persona: EntryBinding,
    format: EntryBinding,
    voice: EntryBinding,
    goals: Iterable[EntryBinding],
    source_subset: Iterable[str],
    source_commit: Mapping[str, str],
    outline_digest: str | None = None,
) -> dict[str, Any]:
    """Construct the canonical §7.2 artifact preimage (the FROZEN shape — see module doc).

    Deterministic by construction: input order never matters (goal pairs sort by entry
    id and dedupe; the subset sorts; maps canonicalize by sorted keys), identical logical
    inputs yield identical canonical bytes and identical ids. The returned object is the
    pure-JSON canonical value — exactly what the IR binding records (§15) and what the
    §22.3 S0 preimage check reads back.

    `outline_digest` is the OPTIONAL DR-3 §7.2 outline extension, OMIT-WHEN-ABSENT: when
    `None` (the default, and the only value any caller passes today) nothing is added, so
    the returned object is the byte-IDENTICAL 4-key preimage and every existing artifact-id
    re-mints unchanged — the zero-churn guarantee. When supplied it must be a 64-char
    lowercase-hex SHA-256 (a `pipeline.outline.outline_digest`) and enters as a single
    top-level `outline-digest` key.

    R4 — the digest has TWO distinct homes; do NOT conflate them (this constructor is
    agnostic to which — it validates the hex form and adds the key; the caller owns the
    distinction):
      (a) EMIT path — on a `Format=outline` artifact the digest is of the artifact's OWN
          normalized body. This IS the ratified R4 exception to "the body is never in the
          preimage": an outline's identity legitimately depends on its own bytes.
      (b) DRIVE path — on a NON-outline artifact (e.g. a blog post the outline steers) the
          digest is of a SEPARATE input, an ordinary content-address input in the SAME
          category as `source-commit` — NOT an R4 exception. A drive-path digest on a
          non-outline artifact must therefore never be misread as a body-in-preimage breach.
    """
    dimensions: dict[str, Any] = {}
    for name, binding in (
        ("topic", topic),
        ("persona", persona),
        ("format", format),
        ("voice", voice),
    ):
        if not isinstance(binding, EntryBinding):
            raise PreimageError(
                f"invalid-preimage: {name} must be an EntryBinding, got {type(binding).__name__}"
            )
        _require_entry_id(binding.entry_id, name)
        dimensions[name] = {
            "entry": binding.entry_id,
            "delta": delta_vs_floor(binding.effective, binding.defaults, where=name),
        }
    goal_deltas: dict[str, dict[str, Any]] = {}
    for binding in goals:
        if not isinstance(binding, EntryBinding):
            raise PreimageError(
                f"invalid-preimage: goals must be EntryBindings, got {type(binding).__name__}"
            )
        _require_entry_id(binding.entry_id, "goal")
        delta = delta_vs_floor(
            binding.effective, binding.defaults, where=f"goal {binding.entry_id}"
        )
        if binding.entry_id in goal_deltas:
            if canonical_json_str(goal_deltas[binding.entry_id]) != canonical_json_str(delta):
                raise PreimageError(
                    f"invalid-preimage: goal {binding.entry_id!r} appears twice with "
                    "DIFFERENT deltas — ambiguous, refused (§7.2 dedupes identical "
                    "pairs only)"
                )
            continue  # exact duplicate — deduped (§7.2: sorted, deduped goal-set)
        goal_deltas[binding.entry_id] = delta
    if isinstance(source_subset, str | bytes):
        raise PreimageError(
            "invalid-preimage: source-subset must be an iterable of instance ids, "
            "not a single string (§7.2)"
        )
    subset: set[str] = set()
    for instance_id in source_subset:
        _require_entry_id(instance_id, "source-subset instance")
        subset.add(instance_id)
    if not isinstance(source_commit, Mapping):
        raise PreimageError(
            "invalid-preimage: source-commit must be the {source-instance-id: commit} map (§7.2)"
        )
    commit_map: dict[str, str] = {}
    for instance_id, commit in source_commit.items():
        _require_entry_id(instance_id, "source-commit instance")
        if not isinstance(commit, str) or not commit:
            raise PreimageError(
                f"invalid-preimage: the commit for {instance_id!r} must be a non-empty string"
            )
        commit_map[instance_id] = commit
    if set(commit_map) != subset:
        raise PreimageError(
            "invalid-preimage: the commit-map must carry EXACTLY one commit per "
            f"source-subset instance (§7.2) — subset {sorted(subset)!r} vs commit keys "
            f"{sorted(commit_map)!r}"
        )
    preimage: dict[str, Any] = {
        "dimensions": dimensions,
        "goals": [[goal_id, goal_deltas[goal_id]] for goal_id in sorted(goal_deltas)],
        "source-subset": sorted(subset),
        "source-commit": commit_map,
    }
    # DR-3 §7.2 outline extension, OMIT-WHEN-ABSENT: `None` adds nothing, so the object
    # stays the byte-identical 4-key preimage and every existing artifact-id is unchanged.
    if outline_digest is not None:
        preimage["outline-digest"] = _require_outline_digest(outline_digest)
    # Total-construction guarantee: every input above was vetted, so this cannot fail;
    # the round-trip makes the returned preimage its own canonical pure-JSON value.
    return json.loads(canonical_json_str(preimage))


# ---------------------------------------------------------------------------
# Minting (§7.4): digest roots + the mint-time preimage check (the §22.3 S0 hook).
# ---------------------------------------------------------------------------

#: The S0-facing lookup shape: given an id string, return the RECORDED preimage from the
#: output store (the IR binding, §15 — or the fit-/render-binding for qualified ids,
#: §16/§17), or None if the id is unseen. Reads output-store state ONLY (§22.7).
PreimageLookup = Callable[[str], Any]


def preimage_check(id_str: str, candidate_preimage: Any, recorded_preimage: Any) -> None:
    """The §7.4 mint-time preimage check: same id + different preimage = loud failure.

    `recorded_preimage is None` means the id is unseen — minting proceeds. Equal
    canonical bytes = the idempotent re-mint (§21.8) — fine. Different bytes = a hex
    collision or a canonicalization bug: `PreimageMismatchError`, never silent reuse.
    Idempotency compares preimages, not just names (§7.4).
    """
    if recorded_preimage is None:
        return
    try:
        recorded_bytes = canonical_json_bytes(recorded_preimage)
        candidate_bytes = canonical_json_bytes(candidate_preimage)
    except CanonicalizationError as exc:
        raise PreimageError(f"invalid-preimage: preimage check for {id_str!r}: {exc}") from exc
    if recorded_bytes != candidate_bytes:
        raise PreimageMismatchError(
            f"preimage-mismatch: {id_str!r} already exists with a DIFFERENT recorded "
            "preimage — minting fails loudly, never silently reuses (§7.4)"
        )


def _mint(
    family: str, preimage: Any, lookup: PreimageLookup | None, digest: Callable[[Any], str]
) -> str:
    try:
        root_hex = digest(preimage)
    except CanonicalizationError as exc:
        raise PreimageError(f"invalid-preimage: {family} preimage: {exc}") from exc
    id_str = PipelineId(family=family, root_hex=root_hex).render()
    if lookup is not None:
        preimage_check(id_str, preimage, lookup(id_str))
    return id_str


def _require_delta_map_shape(delta: Any, where: str) -> None:
    """One delta-vs-floor map at mint time: a Mapping, no §7.3 exclusion at any key.

    Keys are attr-NAME positions — the only place a §7.3 exclusion could smuggle into
    identity. Nested attribute VALUES are data and are never scanned.
    """
    if not isinstance(delta, Mapping):
        raise PreimageError(
            f"invalid-preimage: {where}: the delta must be the delta-vs-floor map (§7.2) "
            "— construct the preimage with build_artifact_preimage"
        )
    for attr in delta:
        if attr in IDENTITY_EXCLUSIONS:
            raise PreimageError(
                f"invalid-preimage: {where}: {attr!r} is never an identity input (§7.3) "
                "and must not reach a mintable preimage"
            )


def _require_artifact_preimage_shape(preimage: Any) -> None:
    """Refuse anything that is not the FROZEN §7.2 shape (mint-misuse guard, §7.3).

    Depth: the top level plus one level down — dimension `{entry, delta}` maps, goal
    `[goal-entry-id, delta]` pairs, the subset list, the commit map — with delta-map
    KEYS checked against the §7.3 exclusions (attr-name positions only; values are data).
    The OPTIONAL top-level `outline-digest` (DR-3 §7.2) is accepted in ADDITION to the four
    required keys — still refusing a missing required key or a 6th unknown key — and, when
    present, asserted to be a `str` (D-8) so a nested mapping cannot smuggle a §7.3 key.
    """
    expected = {"dimensions", "goals", "source-subset", "source-commit"}
    if not isinstance(preimage, Mapping) or set(preimage) - {"outline-digest"} != expected:
        raise PreimageError(
            "invalid-preimage: an artifact preimage carries EXACTLY "
            "dimensions/goals/source-subset/source-commit — plus an OPTIONAL top-level "
            "outline-digest (§7.2/§7.3, DR-3) — construct it with build_artifact_preimage"
        )
    if "outline-digest" in preimage and not isinstance(preimage["outline-digest"], str):
        raise PreimageError(
            "invalid-preimage: outline-digest must be a string (§7.2 D-8) — a nested "
            "mapping must not smuggle a §7.3 exclusion past the attr-name-position scan"
        )
    dimensions = preimage["dimensions"]
    if not isinstance(dimensions, Mapping) or set(dimensions) != set(CONTENT_DIMENSIONS):
        raise PreimageError(
            "invalid-preimage: preimage dimensions must be exactly the four "
            f"single-valued content dimensions {sorted(CONTENT_DIMENSIONS)!r} (§7.2)"
        )
    for name in CONTENT_DIMENSIONS:
        dimension = dimensions[name]
        if not isinstance(dimension, Mapping) or set(dimension) != {"entry", "delta"}:
            raise PreimageError(
                f"invalid-preimage: dimension {name!r} must be the "
                "{'entry': ..., 'delta': ...} map (§7.2) — construct it with "
                "build_artifact_preimage"
            )
        _require_delta_map_shape(dimension["delta"], f"dimension {name!r}")
    goals = preimage["goals"]
    if isinstance(goals, str | bytes) or not isinstance(goals, Sequence):
        raise PreimageError(
            "invalid-preimage: preimage goals must be the sorted "
            "[[goal-entry-id, delta], ...] pair-list (§7.2)"
        )
    for pair in goals:
        if isinstance(pair, str | bytes) or not isinstance(pair, Sequence) or len(pair) != 2:
            raise PreimageError(
                "invalid-preimage: each preimage goal must be a 2-item "
                "[goal-entry-id, delta] pair (§7.2)"
            )
        _require_delta_map_shape(pair[1], f"goal {pair[0]!r}")
    subset = preimage["source-subset"]
    if isinstance(subset, str | bytes) or not isinstance(subset, Sequence):
        raise PreimageError(
            "invalid-preimage: preimage source-subset must be the sorted list of "
            "instance ids (§7.2), not a single string"
        )
    if not isinstance(preimage["source-commit"], Mapping):
        raise PreimageError(
            "invalid-preimage: preimage source-commit must be the "
            "{source-instance-id: commit} map (§7.2)"
        )


def mint_artifact_id(
    preimage: Mapping[str, Any], *, recorded_preimage_lookup: PreimageLookup | None = None
) -> str:
    """Mint `a-<hex16>` from the canonical §7.2 preimage (build_artifact_preimage output).

    The FULL digest is recorded in the IR binding (§15) — record `digest_full(preimage)`
    there; the id carries the hex16 truncation of that same digest (§7.4). When
    `recorded_preimage_lookup` is supplied (the S0 wiring, §22.3), the mint-time
    preimage check runs against the recorded preimage for this id.
    """
    _require_artifact_preimage_shape(preimage)
    return _mint("artifact", preimage, recorded_preimage_lookup, digest_hex16)


def mint_folio_id(preimage: Any, *, recorded_preimage_lookup: PreimageLookup | None = None) -> str:
    """Mint `f-<hex12>` — system-assigned, workspace-scoped, stable (§7.1 F8).

    The seed object is the consuming step's design (§7 fixes only the encoding); it must
    canonicalize (`pipeline.canonical`), and the same preimage-check hook applies.
    """
    return _mint("folio", preimage, recorded_preimage_lookup, digest_hex12)


def mint_run_id(preimage: Any, *, recorded_preimage_lookup: PreimageLookup | None = None) -> str:
    """Mint `r-<hex16>` — the generating-run lineage handle (§7.1 F1).

    The seed object is the consuming step's design (§7 fixes only the encoding); it must
    canonicalize (`pipeline.canonical`), and the same preimage-check hook applies.
    """
    return _mint("run", preimage, recorded_preimage_lookup, digest_hex16)
