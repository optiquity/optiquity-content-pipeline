"""Step-11 tests: the registry ENTRY loader — envelope, identity, namespacing, stamps.

Fixture provenance: the tracked fixtures under `tests/fixtures/registries/gadgets/` are
framework-provenance, obviously-generic files; instance-provenance and every negative
document are authored under pytest `tmp_path` (never tracked), keeping the tracked tree
framework-only per the plan's step-11 fixture note.

Coverage map (plan step 11 accept + spawn mandate):
  - entry-identity mismatch refusal, BOTH carriers exposed on the typed error (B4);
  - missing/ambiguous provenance default-deny (Q15 rule 4);
  - `x-` discipline in both directions → framework↔instance collision structurally
    impossible (§11.4 SV5);
  - `schema_version` stamps parsed as bare ints; drift-comparison inputs for step 12;
  - closed-schema payload (undeclared attribute refused, `metadata` never entry-level);
  - `%`-directive refusal inside entry frontmatter (yamlio S-E8, shared machinery);
  - verbatim body pass-through.
"""

from pathlib import Path

import pytest

from pipeline.attrtypes import ValueValidationError
from pipeline.entries import (
    ENVELOPE_KEYS,
    INSTANCE_ID_PREFIX,
    Entry,
    EntryError,
    EntryIdentityError,
    NamespaceError,
    ProvenanceError,
    load_entry,
    parse_entry,
)
from pipeline.schema import (
    UndeclaredAttributeError,
    VersionStampError,
    load_schema,
)
from pipeline.yamlio import FrontmatterDirectiveError

FIXTURES = Path(__file__).parent / "fixtures" / "registries"
GADGETS_DIR = FIXTURES / "gadgets"


@pytest.fixture(scope="module")
def gadgets():
    return load_schema(GADGETS_DIR / "_schema.yaml")


def write_entry(tmp_path: Path, filename: str, text: str, collection: str = "gadgets") -> Path:
    registry = tmp_path / collection
    registry.mkdir(exist_ok=True)
    path = registry / filename
    path.write_text(text, encoding="utf-8")
    return path


def entry_text(
    *,
    id_line="id: x-sample-widget",
    provenance_line="provenance: instance",
    stamp_line="schema_version: 3",
    extra="",
    body="\nGeneric body.\n",
):
    lines = [line for line in (id_line, provenance_line, stamp_line) if line is not None]
    return "---\n" + "\n".join(lines) + ("\n" + extra if extra else "") + "\n---" + body


# ---------------------------------------------------------------------------
# Loading the tracked framework fixtures (happy path)
# ---------------------------------------------------------------------------


class TestFrameworkFixtures:
    def test_example_widget_loads(self, gadgets):
        entry = load_entry(GADGETS_DIR / "example-widget.md", gadgets)
        assert entry.id == "example-widget"
        assert entry.collection == "gadgets"
        assert entry.provenance == "framework"
        assert entry.schema_version == 3 and type(entry.schema_version) is int
        assert entry.attributes == {
            "color": "blue",
            "intensity": 4,
            "tags": ["alpha", "beta"],
            "labels": {"tier": "sample"},
            "summary": "An obviously-generic example widget.",
        }
        assert entry.set_attributes == frozenset(
            {"color", "intensity", "tags", "labels", "summary"}
        )
        assert not entry.is_instance
        assert entry.path == GADGETS_DIR / "example-widget.md"

    def test_body_is_verbatim(self, gadgets):
        entry = load_entry(GADGETS_DIR / "example-widget.md", gadgets)
        raw = (GADGETS_DIR / "example-widget.md").read_text(encoding="utf-8")
        # The body is byte-identical to the post-fence remainder — no normalization.
        _, _, expected = raw.partition("\n---\n")
        assert entry.body == expected
        assert "# Example widget" in entry.body

    def test_floor_entry_sets_nothing(self, gadgets):
        entry = load_entry(GADGETS_DIR / "example-base.md", gadgets)
        assert entry.attributes == {}
        assert entry.set_attributes == frozenset()
        assert entry.schema_version == 2  # stamped BEHIND current (3) on purpose

    def test_envelope_keys_never_reach_the_payload(self, gadgets):
        entry = load_entry(GADGETS_DIR / "example-widget.md", gadgets)
        assert not (set(entry.attributes) & ENVELOPE_KEYS)


# ---------------------------------------------------------------------------
# THE ENTRY-IDENTITY RULE (§11.1 B4): filename slug == frontmatter id
# ---------------------------------------------------------------------------


class TestEntryIdentity:
    def test_copied_file_is_loud(self, tmp_path, gadgets):
        # The exact silent-new-entry failure B4 kills: copy a file to edit it, forget
        # the in-file id — the mismatch is a typed refusal exposing BOTH carriers.
        original = (GADGETS_DIR / "example-widget.md").read_text(encoding="utf-8")
        copied = write_entry(tmp_path, "copied-widget.md", original)
        with pytest.raises(EntryIdentityError) as exc_info:
            load_entry(copied, gadgets)
        err = exc_info.value
        assert err.code == "entry-identity-mismatch"
        assert err.filename_slug == "copied-widget"
        assert err.frontmatter_id == "example-widget"
        assert "copied-widget" in str(err) and "example-widget" in str(err)

    def test_missing_id_refused(self, tmp_path, gadgets):
        path = write_entry(
            tmp_path,
            "x-sample-widget.md",
            entry_text(id_line=None),
        )
        with pytest.raises(EntryError, match="id"):
            load_entry(path, gadgets)

    @pytest.mark.parametrize("bad_id", ["Ok-Entry", "x-", "-x", "a" * 41, 7])
    def test_in_file_id_must_be_slug(self, tmp_path, gadgets, bad_id):
        path = write_entry(tmp_path, "ok-entry.md", entry_text(id_line=f"id: {bad_id!r}"))
        with pytest.raises(EntryError, match="slug"):
            load_entry(path, gadgets)

    def test_filename_slug_must_be_slug(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "Bad_Name.md", entry_text())
        with pytest.raises(EntryError, match="slug"):
            load_entry(path, gadgets)

    def test_template_files_are_never_entries(self, tmp_path, gadgets):
        # `gadget.template.md` has stem `gadget.template` — outside the slug alphabet.
        path = write_entry(tmp_path, "gadget.template.md", entry_text())
        with pytest.raises(EntryError, match="slug"):
            load_entry(path, gadgets)

    def test_non_md_suffix_refused(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.yaml", entry_text())
        with pytest.raises(EntryError, match=".md"):
            load_entry(path, gadgets)

    def test_missing_frontmatter_refused(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.md", "Just prose, no fences.\n")
        with pytest.raises(EntryError, match="frontmatter"):
            load_entry(path, gadgets)

    def test_collection_mismatch_refused(self, tmp_path, gadgets):
        # An entry loaded against another collection's schema violates SV4 co-location.
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(), collection="doodads")
        with pytest.raises(EntryError, match="co-located"):
            load_entry(path, gadgets)

    def test_non_string_frontmatter_key_refused(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(extra="7: numeric-key"))
        with pytest.raises(EntryError, match="strings"):
            load_entry(path, gadgets)


# ---------------------------------------------------------------------------
# Provenance: required, default-deny (§10 Q15 rule 4)
# ---------------------------------------------------------------------------


class TestProvenance:
    @pytest.mark.parametrize(
        "line",
        [
            None,  # missing entirely
            "provenance: client",  # unknown value
            "provenance: Framework",  # case-variant is AMBIGUOUS, not framework
            "provenance: true",  # non-string
            "provenance: [framework]",  # wrong shape
        ],
    )
    def test_missing_or_ambiguous_provenance_refused(self, tmp_path, gadgets, line):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(provenance_line=line))
        with pytest.raises(ProvenanceError) as exc_info:
            load_entry(path, gadgets)
        assert exc_info.value.code == "missing-or-ambiguous-provenance"


# ---------------------------------------------------------------------------
# `x-` namespacing (§11.4 SV5): prefix is part of the id, in BOTH carriers
# ---------------------------------------------------------------------------


class TestNamespacing:
    def test_valid_instance_entry_carries_prefix_in_both_carriers(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text())
        entry = load_entry(path, gadgets)
        assert entry.is_instance
        assert entry.id.startswith(INSTANCE_ID_PREFIX)  # carrier 1: frontmatter id
        assert path.name.startswith(INSTANCE_ID_PREFIX)  # carrier 2: filename
        assert entry.id == path.stem  # and they are the SAME id (B4)

    def test_unprefixed_instance_entry_refused(self, tmp_path, gadgets):
        path = write_entry(
            tmp_path,
            "sample-widget.md",
            entry_text(id_line="id: sample-widget"),
        )
        with pytest.raises(NamespaceError, match="x-"):
            load_entry(path, gadgets)

    def test_prefixed_framework_entry_refused(self, tmp_path, gadgets):
        path = write_entry(
            tmp_path,
            "x-sample-widget.md",
            entry_text(provenance_line="provenance: framework"),
        )
        with pytest.raises(NamespaceError, match="unprefixed"):
            load_entry(path, gadgets)

    def test_collision_structurally_impossible(self, tmp_path, gadgets):
        # Every loadable instance id starts with `x-`; no loadable framework id does
        # (both refusals above). Therefore the id sets are disjoint and a
        # framework↔instance filename collision cannot exist (§11.4).
        framework = load_entry(GADGETS_DIR / "example-widget.md", gadgets)
        shadow = write_entry(
            tmp_path, "x-example-widget.md", entry_text(id_line="id: x-example-widget")
        )
        instance = load_entry(shadow, gadgets)
        assert instance.id.startswith(INSTANCE_ID_PREFIX)
        assert not framework.id.startswith(INSTANCE_ID_PREFIX)
        assert framework.id != instance.id


# ---------------------------------------------------------------------------
# Version stamps (§11.2): single bare integer per entry; drift inputs for step 12
# ---------------------------------------------------------------------------


class TestStamps:
    @pytest.mark.parametrize(
        "line",
        [
            None,  # missing
            'schema_version: "3"',  # string
            "schema_version: true",  # bool
            "schema_version: 0",  # below 1
            "schema_version: 2.0",  # float
        ],
    )
    def test_stamp_must_be_bare_positive_int(self, tmp_path, gadgets, line):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(stamp_line=line))
        with pytest.raises(VersionStampError):
            load_entry(path, gadgets)

    def test_drift_comparison_inputs_exposed(self, tmp_path, gadgets):
        # Step 12's math is `definition_version > entry.schema_version` AND the entry
        # SETS the attribute (§11.5). Both operands come from this step's loaders.
        path = write_entry(
            tmp_path,
            "x-old-widget.md",
            entry_text(
                id_line="id: x-old-widget",
                stamp_line="schema_version: 1",
                extra="tags: [gamma]",
            ),
        )
        entry = load_entry(path, gadgets)
        versions = gadgets.definition_versions()
        # tags redefined at v2 > stamp 1 and SET by the entry → step 12 will flag it...
        assert versions["tags"] > entry.schema_version
        assert "tags" in entry.set_attributes
        # ...intensity redefined at v3 but NOT set → outside the drift predicate.
        assert versions["intensity"] > entry.schema_version
        assert "intensity" not in entry.set_attributes

    def test_stamp_is_exposed_as_python_int(self, tmp_path, gadgets):
        entry = load_entry(write_entry(tmp_path, "x-sample-widget.md", entry_text()), gadgets)
        assert type(entry.schema_version) is int and entry.schema_version == 3


# ---------------------------------------------------------------------------
# Closed-schema payload on entries (§11.3 SV3) + typed values
# ---------------------------------------------------------------------------


class TestPayload:
    def test_undeclared_attribute_refused(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(extra="sparkle: lots"))
        with pytest.raises(UndeclaredAttributeError, match="sparkle"):
            load_entry(path, gadgets)

    def test_metadata_bag_is_never_entry_frontmatter(self, tmp_path, gadgets):
        # §11.3: the bag is ARTIFACT-level instance data; schemas cannot declare it
        # (reserved name), so on an entry it is exactly an undeclared attribute.
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(extra="metadata: {k: v}"))
        with pytest.raises(UndeclaredAttributeError, match="metadata"):
            load_entry(path, gadgets)

    def test_typed_value_refused(self, tmp_path, gadgets):
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(extra="color: purple"))
        with pytest.raises(ValueValidationError, match="color"):
            load_entry(path, gadgets)

    def test_norway_problem_stays_dead_at_entry_level(self, tmp_path, gadgets):
        # `enabled: no` loads as the STRING "no" under the pinned 1.2 loader and is then
        # REFUSED by the bool type — never coerced to False (the §13.5 guard, end-to-end).
        path = write_entry(tmp_path, "x-sample-widget.md", entry_text(extra="enabled: no"))
        with pytest.raises(ValueValidationError, match="enabled"):
            load_entry(path, gadgets)
        # ...while the same token on a text attribute is a perfectly good string.
        path2 = write_entry(
            tmp_path,
            "x-plain-widget.md",
            entry_text(id_line="id: x-plain-widget", extra="summary: no"),
        )
        assert load_entry(path2, gadgets).attributes["summary"] == "no"

    def test_directive_in_entry_frontmatter_refused(self, tmp_path, gadgets):
        # Same machinery as the schema loader's RV-3 refusal: yamlio S-E8.
        text = "---\n%YAML 1.1\nid: x-sample-widget\n---\nbody\n"
        path = write_entry(tmp_path, "x-sample-widget.md", text)
        with pytest.raises(FrontmatterDirectiveError):
            load_entry(path, gadgets)


# ---------------------------------------------------------------------------
# parse_entry text-level API
# ---------------------------------------------------------------------------


class TestParseEntry:
    def test_parse_entry_without_a_file(self, gadgets):
        entry = parse_entry(
            entry_text(body="\nverbatim body\n"),
            filename_slug="x-sample-widget",
            schema=gadgets,
        )
        assert isinstance(entry, Entry)
        assert entry.path is None
        # The close-fence line consumes its own terminator; the remainder is verbatim.
        assert entry.body == "verbatim body\n"

    def test_empty_frontmatter_block_fails_on_missing_id(self, gadgets):
        with pytest.raises(EntryError, match="id"):
            parse_entry("---\n---\nbody\n", filename_slug="x-sample-widget", schema=gadgets)
