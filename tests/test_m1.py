"""Step-16 tests — `pipeline/m1.py`: M1 entry resolution (design §12.1).

Covers: provenance-ordered shadowing + `extends:` field-merge with per-field provenance;
the §12.4 type-driven combination rules at M1; loud unknown-entry/dangling-ref resolution
for EVERY step-14/15 carry-forward class (§11.1); MIG-6 resolve-time enforcement
(block/warn/silent, §11.5); and the real shipped registries as live test data (every
entry from steps 14–15 resolves dangling-free).

Fixture trees are built in `tmp_path` (REC-3: the repo is read-only toward this suite);
real-registry tests run the resolver READ-ONLY against the repo root.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pipeline.attrtypes import CombineOperatorError, ValueValidationError
from pipeline.drift import iter_entry_files
from pipeline.entries import Entry
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m1 import (
    CODE_DRIFT_BLOCK,
    CODE_OUT_OF_WINDOW,
    DanglingRefError,
    ExtendsError,
    M1Error,
    ResolvedEntry,
    Resolver,
    StaleEntryError,
    UnknownCollectionError,
    UnknownEntryError,
)
from pipeline.schema import SCHEMA_FILENAME, Schema, UndeclaredAttributeError

REPO_ROOT = Path(__file__).resolve().parents[1]
#: §23: the owning user for the on-disk workspace shadow (users/<user>/workspaces/<ws>/).
USER = "acme"

# ------------------------------------------------------------------------------------
# Fixture builders (generic values only; instance entries carry the x- prefix, §11.4)
# ------------------------------------------------------------------------------------

VOICES_SCHEMA = """\
schema_version: 1
attributes:
  formality:
    type: slider
    default: 3
    definition: Test register slider.
    definition_version: 1
  guidelines:
    type: markdown
    default: ""
    definition: Test prose guidelines.
    definition_version: 1
  tags:
    type:
      type: set
      element: text
    default: []
    definition: Test replace-default set.
    definition_version: 1
  audience:
    type:
      type: set
      element: text
    default: [general]
    definition: Test union-default set (schema default combine operator, s12.4).
    definition_version: 1
    combine: union
  sliders:
    type: map
    default: {}
    definition: Test untyped map (key-wise merge, s12.4).
    definition_version: 1
  objections:
    type:
      type: list
      element: text
    default: []
    definition: Test ordered list (union is a schema error, s11.1).
    definition_version: 1
"""

PERSONAS_SCHEMA = """\
schema_version: 1
attributes:
  role:
    type: text
    default: ""
    definition: Test audience fact.
    definition_version: 1
  default_voice:
    type: ref
    default: base-voice
    definition: Test cross-dimension voice ref (Q6/CA2).
    definition_version: 1
"""

FORMATS_SCHEMA = """\
schema_version: 1
attributes:
  parts:
    type:
      type: list
      element: text
    default: []
    definition: Test ordered parts list.
    definition_version: 1
"""

GOALS_SCHEMA = """\
schema_version: 1
attributes:
  kind:
    type:
      type: enum
      values: [strategic, action]
    default: strategic
    definition: Test goal kind.
    definition_version: 1
  source_selection:
    type: map
    default: {}
    definition: Test M3 clause carrier.
    definition_version: 1
"""

TOPICS_SCHEMA = """\
schema_version: 1
attributes:
  why:
    type: markdown
    default: ""
    definition: Test editorial significance.
    definition_version: 1
"""

RECIPES_SCHEMA = """\
schema_version: 1
attributes:
  topic:
    type: text
    default: ""
    definition: Test topic slot (text-with-empty-floor).
    definition_version: 1
  persona:
    type: ref
    default: base-persona
    definition: Test persona slot.
    definition_version: 1
  format:
    type: ref
    default: essay
    definition: Test format slot.
    definition_version: 1
  voice:
    type: ref
    default: base-voice
    definition: Test voice slot (L5 of the s12.3 chain).
    definition_version: 1
  goals:
    type:
      type: set
      element: ref
    default: []
    definition: Test goal-set.
    definition_version: 1
  values:
    type: map
    default: {}
    definition: Test configured values.
    definition_version: 1
  platforms:
    type:
      type: set
      element: ref
    default: []
    definition: Test platform pins.
    definition_version: 1
  languages:
    type:
      type: set
      element: ref
    default: []
    definition: Test language pins.
    definition_version: 1
  output_types:
    type:
      type: set
      element: ref
    default: []
    definition: Test output-type pins.
    definition_version: 1
  presentations:
    type:
      type: set
      element: ref
    default: []
    definition: Test presentation pins.
    definition_version: 1
"""

PLATFORMS_SCHEMA = """\
schema_version: 1
attributes:
  destination:
    type: text
    default: ""
    definition: Test destination prose.
    definition_version: 1
  advisory_norms:
    type: map
    default: {}
    definition: Test advisory norms (CA9 advisory class).
    definition_version: 1
  hard_limits:
    type: map
    default: {}
    definition: Test hard limits (CA9 hard class).
    definition_version: 1
  format_advisories:
    type:
      type: map
      element: map
    default: {}
    definition: Test per-format advisory projection.
    definition_version: 1
  reconcile_strategy:
    type:
      type: enum
      values: [adapt, split, pass, truncate]
    default: adapt
    definition: Test strategy floor.
    definition_version: 1
  reconcile_strategy_defaults:
    type:
      type: map
      element:
        type: enum
        values: [adapt, split, pass, truncate]
    default: {}
    definition: Test per-format strategy table.
    definition_version: 1
  default_output_type:
    type: text
    default: ""
    definition: Test weak output-type default.
    definition_version: 1
"""

EMPTY_SCHEMA = """\
schema_version: 1
attributes: {}
"""

SOURCES_SCHEMA = """\
schema_version: 1
attributes:
  adapter:
    type: text
    default: ""
    definition: Test adapter name.
    definition_version: 1
  content_kind:
    type: ref
    default: general
    definition: Test content-kind tag (s6.1 SM5).
    definition_version: 1
"""

FOLIO_TYPES_SCHEMA = """\
schema_version: 1
attributes:
  roles:
    type:
      type: list
      element: map
    default: []
    definition: Test role skeletons (s9.6).
    definition_version: 1
"""


def write_schema(root: Path, collection: str, text: str) -> None:
    coll = registry_dir(root, collection)
    coll.mkdir(parents=True, exist_ok=True)
    (coll / SCHEMA_FILENAME).write_text(text, encoding="utf-8")


def write_entry(
    root: Path,
    collection: str,
    entry_id: str,
    frontmatter: str = "",
    *,
    provenance: str | None = None,
    stamp: int = 1,
    workspace: str | None = None,
    body: str = "Test fixture body.",
) -> Path:
    if provenance is None:
        provenance = "instance" if entry_id.startswith("x-") else "framework"
    if workspace is None:
        dirpath = registry_dir(root, collection)
    else:
        dirpath = root / "users" / USER / "workspaces" / workspace / collection
    dirpath.mkdir(parents=True, exist_ok=True)
    text = (
        f"---\nid: {entry_id}\nprovenance: {provenance}\nschema_version: {stamp}\n"
        f"{frontmatter}---\n\n{body}\n"
    )
    path = dirpath / f"{entry_id}.md"
    path.write_text(text, encoding="utf-8")
    return path


def build_mini_root(tmp_path: Path) -> Path:
    """A minimal multi-collection config tree exercising every M1 surface."""
    root = tmp_path / "root"
    root.mkdir()
    write_schema(root, "voices", VOICES_SCHEMA)
    write_schema(root, "personas", PERSONAS_SCHEMA)
    write_schema(root, "formats", FORMATS_SCHEMA)
    write_schema(root, "goals", GOALS_SCHEMA)
    write_schema(root, "topics", TOPICS_SCHEMA)
    write_schema(root, "recipes", RECIPES_SCHEMA)
    write_schema(root, "platforms", PLATFORMS_SCHEMA)
    write_schema(root, "languages", EMPTY_SCHEMA)
    write_schema(root, "output-types", EMPTY_SCHEMA)
    write_schema(root, "presentations", EMPTY_SCHEMA)
    write_schema(root, "content-kinds", EMPTY_SCHEMA)
    write_schema(root, "sources", SOURCES_SCHEMA)
    write_schema(root, "folio-types", FOLIO_TYPES_SCHEMA)
    write_entry(
        root,
        "voices",
        "base-voice",
        "formality: 2\nguidelines: Base guidelines prose.\nsliders:\n  pace: 1\n  depth: 2\n",
    )
    write_entry(root, "personas", "base-persona", "default_voice: base-voice\n")
    write_entry(root, "formats", "essay", "")
    write_entry(root, "goals", "explain", "")
    write_entry(root, "languages", "en", "")
    write_entry(root, "output-types", "md", "")
    write_entry(root, "presentations", "plain", "")
    write_entry(root, "content-kinds", "general", "")
    write_entry(
        root,
        "recipes",
        "demo",
        "persona: base-persona\nformat: essay\ngoals: [explain]\n",
    )
    return root


# ------------------------------------------------------------------------------------
# Real registry data (steps 14–15): every shipped entry resolves — dangling-free
# ------------------------------------------------------------------------------------


def test_every_shipped_registry_entry_resolves_dangling_free() -> None:
    resolver = Resolver(REPO_ROOT)
    resolved = 0
    for name in REGISTRY_ROOTS:
        coll = registry_dir(REPO_ROOT, name)
        if not (coll / SCHEMA_FILENAME).is_file():
            continue
        for path in iter_entry_files(coll):
            entry = resolver.resolve(name, path.stem)
            assert isinstance(entry, ResolvedEntry)
            assert entry.id == path.stem
            assert entry.layer_paths == (str(path),)
    resolved = len(resolver._cache)  # noqa: SLF001 - cache size = distinct resolutions
    assert resolved >= 30  # the step-14/15 shipped inventory


def test_real_recipe_resolution_carries_effective_slots() -> None:
    resolver = Resolver(REPO_ROOT)
    recipe = resolver.resolve("recipes", "explainer-post")
    assert recipe.effective["persona"] == "technical-evaluator"
    assert recipe.effective["format"] == "short-opinion-post"
    assert recipe.effective["goals"] == ["explain"]
    assert "voice" not in recipe.effective  # deliberately unset — the CA2 chain resolves
    persona = resolver.resolve("personas", "technical-evaluator")
    assert persona.effective["default_voice"] == "clear-explainer"


def test_real_platform_projection_keys_resolve() -> None:
    resolver = Resolver(REPO_ROOT)
    for platform_id in ("linkedin", "github"):
        platform = resolver.resolve("platforms", platform_id)
        for key in platform.effective.get("format_advisories", {}):
            assert resolver.resolve("formats", key).id == key
        for key in platform.effective.get("reconcile_strategy_defaults", {}):
            assert resolver.resolve("formats", key).id == key


def test_real_folio_type_skeleton_refs_resolve() -> None:
    resolver = Resolver(REPO_ROOT)
    folio_type = resolver.resolve("folio-types", "repo-docs")
    roles = [role["role"] for role in folio_type.effective["roles"]]
    assert roles == ["readme", "getting-started", "architecture"]


# ------------------------------------------------------------------------------------
# Loud unknowns (§11.1)
# ------------------------------------------------------------------------------------


def test_unknown_entry_is_loud(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    with pytest.raises(UnknownEntryError) as exc:
        Resolver(root).resolve("voices", "no-such-voice")
    assert exc.value.code == "unknown-entry"
    assert "no-such-voice" in str(exc.value)
    assert "voices" in str(exc.value)


def test_unknown_collection_is_loud(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    with pytest.raises(UnknownCollectionError):
        Resolver(root).resolve("gadgets", "anything")


def test_junk_entry_id_refused(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    with pytest.raises(M1Error):
        Resolver(root).resolve("voices", "Not A Slug")


# ------------------------------------------------------------------------------------
# extends: field-merge partials (§12.1) with per-field provenance
# ------------------------------------------------------------------------------------


def test_extends_partial_field_merges_with_per_field_provenance(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-house", "extends: base-voice\nformality: 5\n", body="")
    resolved = Resolver(root).resolve("voices", "x-house")
    # Declared field overrides; undeclared fields inherit (§12.1).
    assert resolved.effective["formality"] == 5
    assert resolved.effective["guidelines"] == "Base guidelines prose."
    # Per-field provenance records the setting layer.
    assert resolved.field_provenance["formality"].scope == "instance-global"
    assert resolved.field_provenance["formality"].entry_id == "x-house"
    assert resolved.field_provenance["guidelines"].scope == "framework"
    assert resolved.field_provenance["guidelines"].entry_id == "base-voice"
    assert len(resolved.layer_paths) == 2
    # The partial's blank body inherits the base's prose.
    assert resolved.body.strip() == "Test fixture body."


def test_extends_unknown_base_is_loud(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-orphan", "extends: no-such-base\n")
    with pytest.raises(UnknownEntryError):
        Resolver(root).resolve("voices", "x-orphan")


def test_extends_cycle_is_loud(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-a", "extends: x-b\n")
    write_entry(root, "voices", "x-b", "extends: x-a\n")
    with pytest.raises(ExtendsError) as exc:
        Resolver(root).resolve("voices", "x-a")
    assert exc.value.code == "invalid-extends"


def test_self_extends_without_outer_definition_is_loud(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-solo", "extends: x-solo\nformality: 4\n")
    with pytest.raises(ExtendsError):
        Resolver(root).resolve("voices", "x-solo")


def test_workspace_full_redefinition_shadows_wholesale(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-brand", "formality: 4\nguidelines: Global brand prose.\n")
    write_entry(root, "voices", "x-brand", "formality: 2\n", workspace="testws")
    resolved = Resolver(root, user=USER, workspace="testws").resolve("voices", "x-brand")
    # No extends → the workspace definition IS the definition that loads (§12.1).
    assert resolved.effective["formality"] == 2
    assert "guidelines" not in resolved.effective
    assert resolved.field_provenance["formality"].scope == "workspace"


def test_workspace_self_extends_field_merges_over_instance_global(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-brand", "formality: 4\nguidelines: Global brand prose.\n")
    write_entry(root, "voices", "x-brand", "extends: x-brand\nformality: 2\n", workspace="testws")
    resolved = Resolver(root, user=USER, workspace="testws").resolve("voices", "x-brand")
    assert resolved.effective["formality"] == 2
    assert resolved.effective["guidelines"] == "Global brand prose."
    assert resolved.field_provenance["formality"].scope == "workspace"
    assert resolved.field_provenance["guidelines"].scope == "instance-global"


def test_workspace_layer_ignored_without_workspace(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-brand", "formality: 4\n")
    write_entry(root, "voices", "x-brand", "formality: 2\n", workspace="testws")
    resolved = Resolver(root).resolve("voices", "x-brand")  # no workspace selected
    assert resolved.effective["formality"] == 4  # client isolation (rule 2, §10)


# ------------------------------------------------------------------------------------
# §12.4 combination semantics at M1 (one rule set)
# ------------------------------------------------------------------------------------


def test_partial_inline_union_suffix_on_set(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-tagged", "extends: base-voice\ntags: [zeta, alpha]\n")
    write_entry(root, "voices", "x-more", "extends: x-tagged\ntags+: [mid]\n")
    resolver = Resolver(root)
    # Replace on a set canonicalizes (sorted, deduped — §12.4 determinism).
    assert resolver.resolve("voices", "x-tagged").effective["tags"] == ["alpha", "zeta"]
    # Inline union (CM3 `+` suffix) unions with the base value.
    assert resolver.resolve("voices", "x-more").effective["tags"] == ["alpha", "mid", "zeta"]


def test_partial_wrapper_union_on_set(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-tagged", "extends: base-voice\ntags: [alpha]\n")
    write_entry(
        root,
        "voices",
        "x-wrapped",
        "extends: x-tagged\ntags:\n  combine: union\n  add: [beta]\n",
    )
    resolved = Resolver(root).resolve("voices", "x-wrapped")
    assert resolved.effective["tags"] == ["alpha", "beta"]


def test_schema_default_union_operator_fires_on_bare_binding(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    # `audience` declares `combine: union` with floor [general]: a bare value unions
    # with the value beneath (the L0 floor here) — §12.4 schema default operator.
    write_entry(root, "voices", "x-aud", "extends: base-voice\naudience: [experts]\n")
    resolved = Resolver(root).resolve("voices", "x-aud")
    assert resolved.effective["audience"] == ["experts", "general"]


def test_explicit_replace_wrapper_beats_schema_default_union(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(
        root,
        "voices",
        "x-only",
        "extends: base-voice\naudience:\n  combine: replace\n  add: [experts]\n",
    )
    resolved = Resolver(root).resolve("voices", "x-only")
    assert resolved.effective["audience"] == ["experts"]


def test_union_on_ordered_list_is_schema_error(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-bad", "extends: base-voice\nobjections+: [more]\n")
    with pytest.raises(CombineOperatorError):
        Resolver(root).resolve("voices", "x-bad")


def test_map_merges_key_wise_and_recurses(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(
        root,
        "voices",
        "x-deep",
        "extends: base-voice\nsliders:\n  depth: 5\n  extra:\n    nested: 1\n",
    )
    resolved = Resolver(root).resolve("voices", "x-deep")
    # Key-wise merge (§12.4): untouched keys survive, declared keys win.
    assert resolved.effective["sliders"] == {"pace": 1, "depth": 5, "extra": {"nested": 1}}


def test_typed_map_of_map_merges_per_key(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(
        root,
        "platforms",
        "site",
        "format_advisories:\n  essay:\n    chars: 5\n    words: 2\n",
    )
    write_entry(
        root,
        "platforms",
        "x-site",
        "extends: site\nformat_advisories:\n  essay:\n    chars: 10\n",
    )
    resolved = Resolver(root).resolve("platforms", "x-site")
    assert resolved.effective["format_advisories"] == {"essay": {"chars": 10, "words": 2}}


def test_scalar_and_prose_replace_wholesale(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-prose", "extends: base-voice\nguidelines: Replacement prose.\n")
    resolved = Resolver(root).resolve("voices", "x-prose")
    assert resolved.effective["guidelines"] == "Replacement prose."  # never merged (§12.4)


def test_partial_undeclared_attribute_refused(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-bad", "extends: base-voice\nnope: 1\n")
    with pytest.raises(UndeclaredAttributeError):
        Resolver(root).resolve("voices", "x-bad")


def test_partial_dotted_path_refused(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-bad", "extends: base-voice\nvoice.formality: 1\n")
    with pytest.raises(M1Error):
        Resolver(root).resolve("voices", "x-bad")


def test_base_definition_stays_strict(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-badval", "formality: 99\n")
    with pytest.raises(ValueValidationError):
        Resolver(root).resolve("voices", "x-badval")
    # Inline operators are PARTIAL-only: a base definition with a `+` key is refused
    # by the strict closed-schema path (the step-8 loader posture, unchanged).
    write_entry(root, "voices", "x-badop", "tags+: [a]\n")
    with pytest.raises(UndeclaredAttributeError):
        Resolver(root).resolve("voices", "x-badop")


def test_resolution_is_cached(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    resolver = Resolver(root)
    assert resolver.resolve("voices", "base-voice") is resolver.resolve("voices", "base-voice")


# ------------------------------------------------------------------------------------
# Dangling-ref loudness — EVERY carry-forward class (§11.1; steps 14/15 reviews)
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("collection", "entry_id", "frontmatter", "attribute"),
    [
        ("recipes", "x-r1", "voice: no-such-voice\n", "voice"),
        ("recipes", "x-r2", "persona: no-such-persona\n", "persona"),
        ("recipes", "x-r3", "format: no-such-format\n", "format"),
        ("recipes", "x-r4", "goals: [explain, no-such-goal]\n", "goals"),
        ("recipes", "x-r5", "topic: no-such-topic\n", "topic"),
        ("recipes", "x-r6", "platforms: [no-such-platform]\n", "platforms"),
        ("recipes", "x-r7", "languages: [no-such-language]\n", "languages"),
        ("recipes", "x-r8", "output_types: [no-such-ot]\n", "output_types"),
        ("recipes", "x-r9", "presentations: [no-such-p]\n", "presentations"),
        ("personas", "x-p1", "default_voice: no-such-voice\n", "default_voice"),
        ("sources", "x-s1", "content_kind: no-such-kind\n", "content_kind"),
        (
            "platforms",
            "x-pl1",
            "format_advisories:\n  no-such-format:\n    chars: 1\n",
            "format_advisories key",
        ),
        (
            "platforms",
            "x-pl2",
            "reconcile_strategy_defaults:\n  no-such-format: adapt\n",
            "reconcile_strategy_defaults key",
        ),
        ("platforms", "x-pl3", "default_output_type: no-such-ot\n", "default_output_type"),
        (
            "folio-types",
            "x-f1",
            "roles:\n  - role: readme\n    skeleton:\n      format: no-such-format\n",
            "skeleton.format",
        ),
        (
            "folio-types",
            "x-f2",
            "roles:\n  - role: readme\n    skeleton:\n      goals: [no-such-goal]\n",
            "skeleton.goals",
        ),
    ],
)
def test_dangling_refs_are_loud(
    tmp_path: Path, collection: str, entry_id: str, frontmatter: str, attribute: str
) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, collection, entry_id, frontmatter)
    with pytest.raises(DanglingRefError) as exc:
        Resolver(root).resolve(collection, entry_id)
    assert exc.value.code == "dangling-ref"
    assert attribute.split(".")[-1].split(" ")[0] in exc.value.attribute
    assert exc.value.ref.startswith("no-such")
    assert exc.value.referrer == f"{collection}/{entry_id}"


def test_empty_text_refs_are_honestly_unset(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "recipes", "x-empty", 'topic: ""\n')
    write_entry(root, "platforms", "x-none", 'default_output_type: ""\n')
    resolver = Resolver(root)
    assert resolver.resolve("recipes", "x-empty").effective["topic"] == ""
    assert resolver.resolve("platforms", "x-none").effective["default_output_type"] == ""


def test_valid_refs_resolve_transitively(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "topics", "x-subject", "", workspace="testws")
    write_entry(
        root,
        "recipes",
        "x-full",
        "topic: x-subject\npersona: base-persona\nformat: essay\ngoals: [explain]\n",
        workspace="testws",
    )
    resolver = Resolver(root, user=USER, workspace="testws")
    resolved = resolver.resolve("recipes", "x-full")
    assert resolved.effective["topic"] == "x-subject"
    # The transitively-referenced entries resolved (and cached) on the way.
    assert ("topics", "x-subject") in resolver._cache  # noqa: SLF001
    assert ("voices", "base-voice") in resolver._cache  # noqa: SLF001 (via persona)


# ------------------------------------------------------------------------------------
# MIG-6 resolve-time enforcement (§11.5): block / warn / silent
# ------------------------------------------------------------------------------------


def _bump_voices_schema(root: Path, *, formality_version: int = 1, drop_guidelines: bool = False):
    text = VOICES_SCHEMA.replace("schema_version: 1", "schema_version: 2")
    if formality_version != 1:
        text = text.replace(
            "    definition: Test register slider.\n    definition_version: 1",
            f"    definition: Test register slider (MEANING CHANGED).\n"
            f"    definition_version: {formality_version}",
        )
    if drop_guidelines:
        lines = text.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.startswith("  guidelines:"))
        end = next(i for i in range(start + 1, len(lines)) if not lines[i].startswith("    "))
        text = "".join(lines[:start] + lines[end:])
    write_schema(root, "voices", text)


def test_mig6_meaning_change_blocks_stale_entry(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    _bump_voices_schema(root, formality_version=2)
    # base-voice is stamped 1 and SETS formality, whose meaning changed at v2 → BLOCK.
    with pytest.raises(StaleEntryError) as exc:
        Resolver(root).resolve("voices", "base-voice")
    assert exc.value.code == CODE_DRIFT_BLOCK
    assert any(f.attribute == "formality" for f in exc.value.findings)


def test_mig6_new_attribute_warns_not_blocks(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    _bump_voices_schema(root, formality_version=2)
    write_entry(root, "voices", "x-quiet", "guidelines: Only prose.\n")  # never sets formality
    resolved = Resolver(root).resolve("voices", "x-quiet")
    assert any("formality" in w.key for w in resolved.warnings)


def test_mig6_wording_only_change_is_silent(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    # schema_version bumps, no definition_version moves: wording-only — silent (§11.5).
    _bump_voices_schema(root)
    resolved = Resolver(root).resolve("voices", "base-voice")
    assert resolved.warnings == ()


def test_mig6_removed_attribute_blocks(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    _bump_voices_schema(root, drop_guidelines=True)
    with pytest.raises(StaleEntryError) as exc:  # base-voice still sets guidelines
        Resolver(root).resolve("voices", "base-voice")
    assert exc.value.code == CODE_DRIFT_BLOCK
    assert any(f.attribute == "guidelines" for f in exc.value.findings)


class _AlwaysOutOfWindow:
    """A stub MIG-2 oracle (the real one is `pipeline/migration.StepRegistry`)."""

    def out_of_window(self, schema: Schema, entry: Entry, *, now: date) -> str | None:
        return f"past the 1-year support window as of {now} (stub)"


def test_mig6_out_of_window_blocks_with_injected_oracle(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    _bump_voices_schema(root)  # stale stamp, wording-only otherwise
    resolver = Resolver(root, now=date(2026, 7, 12), window=_AlwaysOutOfWindow())
    with pytest.raises(StaleEntryError) as exc:
        resolver.resolve("voices", "base-voice")
    assert exc.value.code == CODE_OUT_OF_WINDOW


def test_window_oracle_requires_injected_clock(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    with pytest.raises(M1Error):
        Resolver(root, window=_AlwaysOutOfWindow())


def test_stamp_ahead_of_schema_warns(tmp_path: Path) -> None:
    root = build_mini_root(tmp_path)
    write_entry(root, "voices", "x-ahead", "formality: 4\n", stamp=5)
    resolved = Resolver(root).resolve("voices", "x-ahead")
    assert any(w.key.startswith("stamp-ahead") for w in resolved.warnings)
