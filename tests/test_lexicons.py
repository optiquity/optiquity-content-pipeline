"""DR-2 C1 tests: the `lexicons/` registry stand-up (attributes-only house style).

Covers the C1 acceptance:

- the schema LOADS + validates (SV4 co-located manifest, `schema_version: 1`);
- every attribute is FLOOR-EMPTY (§12.2 L0) — a lexicon that sets nothing imposes no rule;
- `house-standard` RESOLVES via `Resolver.resolve("lexicons", ...)` with NO
  `DIMENSION_COLLECTIONS` edit (a co-located-schema collection resolves as any other, SV4);
- THE RATIFIED ATTRIBUTE-ONLY IDENTITY INVARIANT — every compose-consumable rule is a
  schema ATTRIBUTE and NO attribute is body-consuming (no `markdown`/prose attribute,
  contrast `voices.guidelines` / `topics.why`), so `delta_vs_floor` over the resolved
  lexicon captures every rule and NEVER the body (the body is inert to compose);
- `house-standard` content is GENERIC (framework provenance; universal editorial hygiene +
  public technology-name casing only — no client/real-org data, no impersonation);
- version-equality stays green: the 15th `_schema.yaml` on disk is at the global v1.

The registry is UNWIRED at C1 (no artifact reads it) — zero artifact-id churn; C2 threads
the resolved lexicon `{entry, delta}` into the artifact-id preimage.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.entries import PROVENANCE_FRAMEWORK, load_entry
from pipeline.ids import delta_vs_floor
from pipeline.m1 import (
    CONTENT_DIMENSION_TOKENS,
    DIMENSION_COLLECTIONS,
    RENDERING_DIMENSION_TOKENS,
    Resolver,
)
from pipeline.schema import load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
LEXICONS = REPO_ROOT / "lexicons"

#: The class-(ii) house-style attributes the C1 schema declares (all floor-empty).
LEXICON_ATTRIBUTES = {
    "preferred_terms",
    "banned_terms",
    "proper_names",
    "spelling",
    "mechanical",
}


# ---------------------------------------------------------------------------------------
# The schema loads + validates (SV4)
# ---------------------------------------------------------------------------------------


def test_schema_loads_and_validates():
    schema = load_schema(LEXICONS / "_schema.yaml")
    assert schema.collection == "lexicons"
    assert schema.schema_version == 1
    assert set(schema.attributes) == LEXICON_ATTRIBUTES


def test_every_attribute_is_floor_empty():
    """§12.2 L0: an unset lexicon imposes no rule — every floor is the empty value, so a
    newly shipped attribute at its default churns no id (§7.2)."""
    schema = load_schema(LEXICONS / "_schema.yaml")
    assert schema.defaults() == {
        "preferred_terms": {},
        "banned_terms": [],
        "proper_names": {},
        "spelling": "",
        "mechanical": {},
    }


def test_spelling_floor_is_the_no_rule_neutral_member():
    """The `spelling` enum is `us`/`uk` with a NEUTRAL `""` floor member: absent = no
    spelling normalization (the honest-unset `""` precedent, e.g.
    `platforms.default_output_type`)."""
    schema = load_schema(LEXICONS / "_schema.yaml")
    spelling = schema.attributes["spelling"]
    assert spelling.type.kind == "enum"
    assert spelling.type.values == ("", "us", "uk")
    assert spelling.default == ""  # the floor means "no spelling rule"


def test_mechanical_is_an_open_bare_map():
    """`mechanical` is an OPEN bare/untyped map (element is None), NOT a closed enum — a
    new mechanical rule is a one-file add on an ENTRY, never a schema edit."""
    schema = load_schema(LEXICONS / "_schema.yaml")
    mechanical = schema.attributes["mechanical"]
    assert mechanical.type.kind == "map"
    assert mechanical.type.element is None


# ---------------------------------------------------------------------------------------
# Resolves as a co-located-schema collection — NO DIMENSION_COLLECTIONS edit (SV4)
# ---------------------------------------------------------------------------------------


def test_house_standard_resolves_without_a_dimension_edit():
    """`lexicons` is NOT an identity dimension: it resolves via `Resolver.resolve` purely
    on its co-located `_schema.yaml` (SV4), with no entry in `DIMENSION_COLLECTIONS` and no
    dimension token — confirming the C1 claim that the map for identity dimensions is
    untouched."""
    assert "lexicon" not in DIMENSION_COLLECTIONS
    assert "lexicons" not in DIMENSION_COLLECTIONS.values()
    assert "lexicon" not in CONTENT_DIMENSION_TOKENS + RENDERING_DIMENSION_TOKENS

    resolved = Resolver(REPO_ROOT).resolve("lexicons", "house-standard")
    assert resolved.collection == "lexicons"
    assert resolved.id == "house-standard"
    assert resolved.effective["spelling"] == "us"
    assert resolved.effective["preferred_terms"] == {"utilize": "use", "leverage": "use"}
    assert resolved.effective["proper_names"]["github"] == "GitHub"
    assert resolved.effective["mechanical"] == {"oxford_comma": True}
    assert resolved.effective["banned_terms"] == ["irregardless"]


# ---------------------------------------------------------------------------------------
# THE ATTRIBUTE-ONLY IDENTITY INVARIANT
# ---------------------------------------------------------------------------------------


def test_no_body_consuming_attribute():
    """Every compose-consumable rule is a class-(ii) structured ATTRIBUTE (map/set/enum);
    NO attribute is body-consuming — there is no `markdown`/prose attribute (the vehicle by
    which `voices.guidelines` / `topics.why` DO carry prose into compose). So the entry body
    is inert to compose."""
    schema = load_schema(LEXICONS / "_schema.yaml")
    kinds = {spec.type.kind for spec in schema.attributes.values()}
    assert "markdown" not in kinds
    assert kinds <= {"map", "set", "enum"}


def test_delta_vs_floor_captures_the_rules_never_the_body():
    """The resolved lexicon's identity contribution is `delta_vs_floor` over its ATTRIBUTES
    (§7.2) — it captures every rule the entry set and never the body. The entry HAS
    documentation prose, and that prose is a separate field, never an attribute, never a
    delta key: rewriting it cannot move the delta (the C2 preimage component)."""
    resolved = Resolver(REPO_ROOT).resolve("lexicons", "house-standard")
    delta = delta_vs_floor(resolved.effective, resolved.defaults())
    # house-standard sets all five rules, each off its floor → the delta is total.
    assert set(delta) == LEXICON_ATTRIBUTES
    # Every delta key is a declared attribute — nothing body-derived can enter.
    assert all(key in resolved.schema.attributes for key in delta)
    # The body EXISTS (documentation prose) yet is not part of identity.
    assert resolved.body.strip()
    assert "house-standard" in resolved.body


# ---------------------------------------------------------------------------------------
# Generic framework content — no client/real-org data
# ---------------------------------------------------------------------------------------


def test_house_standard_is_generic_framework_content():
    """The shipped entry is framework provenance and carries only UNIVERSAL editorial
    hygiene + public technology-name casing — no private glossary, no client terminology, no
    real-organization impersonation."""
    schema = load_schema(LEXICONS / "_schema.yaml")
    entry = load_entry(LEXICONS / "house-standard.md", schema)
    assert entry.provenance == PROVENANCE_FRAMEWORK
    # proper_names cover only well-known public technology names, not a private glossary.
    assert set(entry.attributes["proper_names"]) <= {
        "github",
        "javascript",
        "typescript",
        "api",
    }
    # spelling is a standard (or the neutral floor), never a client policy.
    assert entry.attributes["spelling"] in {"", "us", "uk"}
    # mechanical carries only universal mechanical rules.
    assert set(entry.attributes["mechanical"]) <= {
        "oxford_comma",
        "number_style",
        "date_style",
        "unit_style",
    }


# ---------------------------------------------------------------------------------------
# Version-equality stays green — the 15th schema at the global v1
# ---------------------------------------------------------------------------------------


def test_all_registry_schemas_share_the_global_schema_version():
    """SV2 (§11.2): the ONE global `schema_version` is copied across every top-level
    `_schema.yaml`. `lexicons` + increment C's `diagram-styles` + authoring C5a's
    `selections` make SEVENTEEN files, and version-equality holds — all at v1 — so the skew
    lint stays green with zero id churn."""
    schema_files = sorted(REPO_ROOT.glob("*/_schema.yaml"))
    versions = {p.parent.name: load_schema(p).schema_version for p in schema_files}
    assert versions["lexicons"] == 1
    assert versions["diagram-styles"] == 1
    assert versions["selections"] == 1
    assert len(versions) == 17
    assert set(versions.values()) == {1}
