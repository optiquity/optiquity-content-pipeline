"""The registry ENTRY loader: MD + frontmatter, enforcing the §11.1 entry envelope.

Design authority: `docs/design.md`
  §11.1 (B4) — THE ENTRY-IDENTITY RULE: every entry carries `id:` in frontmatter and the
          filename slug MUST equal the in-file id. A mismatch is a TYPED refusal here
          (`EntryIdentityError`, exposing BOTH carriers) — duplication-for-editing is LOUD,
          carrier drift is impossible; the CI-lint enforcement over whole registries lands
          at step 13 on top of this loader.
  §7.4  — entry ids/filename slugs live in the strict slug alphabet `[a-z0-9-]`, 1-40
          chars (validated via attrtypes' `ref` type — the single implementation).
  §10 (Q15) — `provenance: framework | instance` is a REQUIRED frontmatter tag;
          missing/ambiguous is default-deny (rule 4).
  §11.4 (SV5) — instance entries carry the reserved `x-` prefix AS PART OF THE ID, present
          in both carriers; the framework owns the unprefixed namespace and never ships
          `x-*`. Both directions are enforced here, so framework↔instance collision is
          structurally impossible.
  §11.2/§13.4 — every entry stamps `schema_version: <bare int>` in frontmatter (the
          version it was authored/last migrated under). The stamp is PARSED here and
          exposed for step 12's drift math; comparisons (drift/window) are step 12's scope.
  §11.3 — closed schemas: undeclared frontmatter attributes are rejected (via
          `Schema.validate_attribute_values`); the `metadata` bag is ARTIFACT-level and is
          therefore an undeclared attribute on any entry (schemas cannot declare it —
          reserved name).

The frontmatter split + `%`-directive refusal + pinned YAML 1.2 load all come from
`pipeline/yamlio.load_frontmatter` (S-E1..S-E12 semantics; never duplicated here). The
markdown body is carried VERBATIM — never parsed, never normalized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, validate_value
from pipeline.schema import Schema, VersionStampError, require_bare_int
from pipeline.yamlio import load_frontmatter

__all__ = [
    "ENTRY_SUFFIX",
    "ENVELOPE_KEYS",
    "Entry",
    "EntryError",
    "EntryIdentityError",
    "INSTANCE_ID_PREFIX",
    "NamespaceError",
    "PROVENANCES",
    "PROVENANCE_FRAMEWORK",
    "PROVENANCE_INSTANCE",
    "ProvenanceError",
    "load_entry",
    "parse_entry",
]

#: Registry entries are markdown files (frontmatter + prose body).
ENTRY_SUFFIX = ".md"

#: The entry ENVELOPE: frontmatter keys owned by the framework mechanism, never schema
#: attributes (§11.1 id · §10 provenance · §11.2 stamp). Everything else in frontmatter is
#: attribute payload and must be schema-declared (SV3).
ENVELOPE_KEYS = frozenset({"id", "provenance", "schema_version"})

#: §10 (Q15): the only two provenance values; anything else is ambiguous → default-deny.
PROVENANCE_FRAMEWORK = "framework"
PROVENANCE_INSTANCE = "instance"
PROVENANCES = frozenset({PROVENANCE_FRAMEWORK, PROVENANCE_INSTANCE})

#: §11.4 (SV5): the reserved instance namespace prefix — part of the id, both carriers.
INSTANCE_ID_PREFIX = "x-"

#: Slug validation = the §7.4 alphabet's single implementation (attrtypes' `ref` type).
_REF_SPEC = AttrTypeSpec(kind="ref")


class EntryError(ValueError):
    """A malformed registry entry — refused, never repaired."""

    code = "invalid-entry"


class EntryIdentityError(EntryError):
    """§11.1 (B4): the two id carriers disagree — filename slug != frontmatter `id`.

    Exposes BOTH carriers (`filename_slug`, `frontmatter_id`) so the step-13 lint can
    report the loud-duplication case verbatim.
    """

    code = "entry-identity-mismatch"

    def __init__(self, message: str, *, filename_slug: str, frontmatter_id: str) -> None:
        super().__init__(message)
        self.filename_slug = filename_slug
        self.frontmatter_id = frontmatter_id


class ProvenanceError(EntryError):
    """§10 (Q15 rule 4): missing or ambiguous `provenance` — default-deny."""

    code = "missing-or-ambiguous-provenance"


class NamespaceError(EntryError):
    """§11.4 (SV5): the `x-` discipline violated in either direction."""

    code = "namespace-violation"


@dataclass(frozen=True)
class Entry:
    """One loaded, validated registry entry (envelope + typed payload + verbatim body)."""

    collection: str
    id: str
    #: `framework` or `instance` (§10).
    provenance: str
    #: The §11.2 single-integer stamp — a step-12 drift-comparison input.
    schema_version: int
    #: The attributes this entry SETS (validated against the closed schema). Missing
    #: attributes ride the schema-default floor (§12.2 L0) — resolution is M1/M2's job.
    attributes: dict[str, Any] = field(default_factory=dict)
    #: The markdown body, verbatim (byte-identical to the post-fence remainder).
    body: str = ""
    path: Path | None = None

    @property
    def set_attributes(self) -> frozenset[str]:
        """The 'entry sets that attribute' operand of the §11.5 drift math (step 12)."""
        return frozenset(self.attributes)

    @property
    def is_instance(self) -> bool:
        return self.provenance == PROVENANCE_INSTANCE


def _require_slug(value: object, what: str) -> str:
    try:
        validate_value(_REF_SPEC, value)
    except ValueError as exc:
        raise EntryError(
            f"invalid-entry: {what} {value!r} is not a §7.4 slug ([a-z0-9-], 1-40 chars, "
            "no leading/trailing '-')"
        ) from exc
    assert isinstance(value, str)
    return value


def parse_entry(
    text: str, *, filename_slug: str, schema: Schema, path: Path | None = None
) -> Entry:
    """Parse one entry document against its collection `schema`; refuse, never repair.

    `filename_slug` is the filename-side identity carrier (the stem of `<slug>.md`).
    Check order: frontmatter presence → key shape → id (present/slug/IDENTITY MATCH) →
    provenance (default-deny) → `x-` namespace discipline → stamp → closed-schema payload.
    """
    where = f"{schema.collection}/{filename_slug}{ENTRY_SUFFIX}"
    _require_slug(filename_slug, f"{where}: filename slug")

    # yamlio owns the split, the %-directive refusal (S-E8) and the pinned 1.2 load.
    frontmatter, body = load_frontmatter(text)
    if frontmatter is None:
        raise EntryError(
            f"invalid-entry: {where}: a registry entry requires YAML frontmatter "
            "(id/provenance/schema_version envelope, §11.1/§10/§11.2)"
        )
    for key in frontmatter:
        if not isinstance(key, str):
            raise EntryError(
                f"invalid-entry: {where}: frontmatter keys must be strings, got {key!r}"
            )

    # §11.1 (B4): the in-file carrier, then the identity match against the filename.
    if "id" not in frontmatter:
        raise EntryError(
            f"invalid-entry: {where}: missing `id:` in frontmatter — every entry carries "
            "its id in BOTH carriers (§11.1 entry-identity rule)"
        )
    entry_id = _require_slug(frontmatter["id"], f"{where}: frontmatter id")
    if entry_id != filename_slug:
        raise EntryIdentityError(
            f"entry-identity-mismatch: {where}: filename slug {filename_slug!r} != "
            f"frontmatter id {entry_id!r} — the filename slug MUST equal the in-file id "
            "(§11.1 B4; a copied-for-editing file must take a new id in both carriers)",
            filename_slug=filename_slug,
            frontmatter_id=entry_id,
        )

    # §10 (Q15 rule 4): default-deny provenance. The isinstance guard keeps non-string
    # (possibly unhashable) values on the typed-refusal path.
    provenance = frontmatter.get("provenance")
    if not isinstance(provenance, str) or provenance not in PROVENANCES:
        raise ProvenanceError(
            f"missing-or-ambiguous-provenance: {where}: `provenance:` must be exactly "
            f"'framework' or 'instance' (§10 Q15, default-deny), got {provenance!r}"
        )

    # §11.4 (SV5): the x- discipline, both directions — collision structurally impossible.
    if provenance == PROVENANCE_INSTANCE and not entry_id.startswith(INSTANCE_ID_PREFIX):
        raise NamespaceError(
            f"namespace-violation: {where}: instance entries must carry the reserved "
            f"'{INSTANCE_ID_PREFIX}' id prefix in both carriers (§11.4 SV5), got {entry_id!r}"
        )
    if provenance == PROVENANCE_FRAMEWORK and entry_id.startswith(INSTANCE_ID_PREFIX):
        raise NamespaceError(
            f"namespace-violation: {where}: the framework owns the unprefixed namespace "
            f"and never ships '{INSTANCE_ID_PREFIX}*' (§11.4), got {entry_id!r}"
        )

    # §11.2: the single-integer stamp. Parsed and exposed here; drift/window COMPARISONS
    # against schema.schema_version / definition_versions() are step 12's scope.
    if "schema_version" not in frontmatter:
        raise VersionStampError(
            f"invalid-version-stamp: {where}: missing `schema_version:` stamp — every entry "
            "stamps the single global integer it was authored/migrated under (§11.2)"
        )
    stamp = require_bare_int(frontmatter["schema_version"], f"{where}.schema_version")

    # §11.3 (SV3): everything beyond the envelope is payload against the CLOSED schema.
    payload = {k: v for k, v in frontmatter.items() if k not in ENVELOPE_KEYS}
    schema.validate_attribute_values(payload, where=where)

    return Entry(
        collection=schema.collection,
        id=entry_id,
        provenance=provenance,
        schema_version=stamp,
        attributes=payload,
        body=body,
        path=path,
    )


def load_entry(path: str | Path, schema: Schema) -> Entry:
    """Load `<collection>/<id>.md` against its co-located collection schema.

    Refusals: non-`.md` filename; a stem outside the slug alphabet (which also excludes
    `*.template.*` scaffolding — templates are never loadable entries); a file not sitting
    in its schema's collection directory (SV4 co-location, §10 scope-by-location). Reads
    strict UTF-8 (decode errors propagate loudly).
    """
    path = Path(path)
    if path.suffix != ENTRY_SUFFIX or path.name == ENTRY_SUFFIX:
        raise EntryError(
            f"invalid-entry: {path.name!r}: registry entries are `<slug>{ENTRY_SUFFIX}` files"
        )
    if path.parent.name != schema.collection:
        raise EntryError(
            f"invalid-entry: {path} does not sit in its schema's collection directory "
            f"{schema.collection!r} — entries are co-located with their `_schema.yaml` "
            "(SV4 §13.4; scope is encoded by location, §10)"
        )
    filename_slug = path.name[: -len(ENTRY_SUFFIX)]
    text = path.read_text(encoding="utf-8")
    return parse_entry(text, filename_slug=filename_slug, schema=schema, path=path)
