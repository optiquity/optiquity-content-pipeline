"""Step-11 tests: the `_schema.yaml` loader, closed-schema validation, the metadata bag.

Fixture provenance: `tests/fixtures/registries/gadgets/` — an obviously-generic fake
collection exercising every §11.1 attribute type once (framework-provenance test data,
never client content). Negative documents are authored inline/tmp_path.

Coverage map (plan step 11 accept + carry-forward):
  - schema load + typed validation against EVERY §11.1 type;
  - closed manifests: undeclared attribute (SV3), unknown manifest/top-level keys,
    missing required fields;
  - the load-bearing list/set split: union-on-list refused, combine on non-set refused,
    set-subtract reserved;
  - version stamps parsed as BARE ints; drift-comparison inputs exposed for step 12;
  - the RV-3 `%`-directive refusal in schema files (carry-forward from step-8 review);
  - the §11.3 metadata bag: pass-through uninterpreted, never identity.
"""

import datetime
from pathlib import Path

import pytest

from pipeline.attrtypes import (
    TYPE_KINDS,
    CombineOperatorError,
    SchemaTypeError,
    ValueValidationError,
    validate_value,
)
from pipeline.canonical import CanonicalizationError, canonical_json_str
from pipeline.ids import PreimageError, delta_vs_floor
from pipeline.schema import (
    RESERVED_ATTRIBUTE_NAMES,
    MetadataBag,
    MetadataBagError,
    SchemaDirectiveError,
    SchemaError,
    SchemaValidationError,
    UndeclaredAttributeError,
    VersionStampError,
    load_schema,
    load_schema_text,
)
from pipeline.yamlio import YAMLLoadError

FIXTURES = Path(__file__).parent / "fixtures" / "registries"
GADGETS_SCHEMA = FIXTURES / "gadgets" / "_schema.yaml"

# A minimal valid manifest body used to build inline negative documents.
_MINIMAL = """\
schema_version: 3
attributes:
  {name}:
    type: {type}
    default: {default}
    definition: An inline test attribute.
    definition_version: {dv}
{extra}"""


def _inline(name="sample", type_="number", default="1", dv="1", extra=""):
    text = _MINIMAL.format(name=name, type=type_, default=default, dv=dv, extra=extra)
    return load_schema_text(text, collection="gadgets")


@pytest.fixture(scope="module")
def gadgets():
    return load_schema(GADGETS_SCHEMA)


# ---------------------------------------------------------------------------
# Loading the co-located fixture schema (§11.1, §13.4 SV4)
# ---------------------------------------------------------------------------


class TestSchemaLoad:
    def test_fixture_loads_with_collection_from_directory(self, gadgets):
        assert gadgets.collection == "gadgets"
        assert gadgets.schema_version == 3

    def test_every_section_11_1_type_is_exercised(self, gadgets):
        # The fixture manifest covers the ENTIRE §11.1 type vocabulary — no kind untested.
        kinds = {spec.type.kind for spec in gadgets.attributes.values()}
        assert kinds == TYPE_KINDS

    def test_manifest_rows_carry_all_four_declarations(self, gadgets):
        # §11.1: per attribute: type · default · definition · definition_version.
        for spec in gadgets.attributes.values():
            assert spec.type.kind in TYPE_KINDS
            assert isinstance(spec.definition, str) and spec.definition.strip()
            assert isinstance(spec.definition_version, int)
            validate_value(spec.type, spec.default)  # every default IS its declared type

    def test_defaults_are_the_l0_floor_and_mutation_isolated(self, gadgets):
        floor = gadgets.defaults()
        assert floor["color"] == "red"
        assert floor["steps"] == ["first", "second"]
        floor["steps"].append("corrupted")
        assert gadgets.defaults()["steps"] == ["first", "second"]  # deep-copied per call

    def test_definition_versions_exposed_for_step_12(self, gadgets):
        # §11.5 drift math input: attribute → definition_version, bare ints in the
        # global number-space (SV1), never exceeding the file's schema_version.
        versions = gadgets.definition_versions()
        assert versions["intensity"] == 3
        assert versions["tags"] == 2
        assert versions["color"] == 1
        assert all(type(v) is int for v in versions.values())
        assert all(v <= gadgets.schema_version for v in versions.values())

    def test_set_default_combine_operator(self, gadgets):
        # §12.4: per-`set`-attribute schema default operator; replace everywhere else.
        assert gadgets.attributes["tags"].combine == "union"
        assert gadgets.attributes["steps"].combine == "replace"
        assert gadgets.attributes["color"].combine == "replace"

    def test_filename_must_be_schema_yaml(self, tmp_path, gadgets):
        renamed = tmp_path / "gadgets" / "schema.yaml"
        renamed.parent.mkdir()
        renamed.write_text(GADGETS_SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
        with pytest.raises(SchemaError, match="_schema.yaml"):
            load_schema(renamed)

    def test_collection_name_must_be_slug(self):
        with pytest.raises(SchemaError, match="slug"):
            load_schema_text("schema_version: 1\nattributes: {}\n", collection="Bad_Name")

    def test_thin_schema(self):
        # §11.7: thin objects get thin schemas — an explicitly-empty manifest is valid.
        schema = load_schema_text("schema_version: 1\nattributes: {}\n", collection="gadgets")
        assert schema.attributes == {}
        assert schema.defaults() == {}
        schema.validate_attribute_values({})
        with pytest.raises(UndeclaredAttributeError):
            schema.validate_attribute_values({"anything": 1})

    def test_non_mapping_and_empty_documents_refused(self):
        with pytest.raises(SchemaError, match="mapping"):
            load_schema_text("- a\n- b\n", collection="gadgets")
        with pytest.raises(SchemaError, match="empty"):
            load_schema_text("", collection="gadgets")

    def test_yaml_syntax_errors_propagate_loudly(self):
        with pytest.raises(YAMLLoadError):
            load_schema_text("schema_version: [unclosed\n", collection="gadgets")


# ---------------------------------------------------------------------------
# The RV-3 carry-forward: %-directive refusal in schema files (S-E8 parity)
# ---------------------------------------------------------------------------


class TestDirectiveRefusal:
    GOOD = "schema_version: 1\nattributes: {}\n"

    def test_yaml_11_directive_refused_never_honored(self):
        # Without the refusal, `%YAML 1.1` would be HONORED by the loader and re-enable
        # the Norway problem (verified hazard D3) — refused loudly instead.
        with pytest.raises(SchemaDirectiveError, match="%YAML 1.1"):
            load_schema_text("%YAML 1.1\n---\n" + self.GOOD, collection="gadgets")

    def test_any_directive_line_refused_mid_document(self):
        with pytest.raises(SchemaDirectiveError) as exc_info:
            load_schema_text(self.GOOD + "%TAG ! tag:example\n", collection="gadgets")
        assert exc_info.value.code == "schema-directive-refused"

    def test_same_document_without_directive_loads(self):
        assert load_schema_text(self.GOOD, collection="gadgets").schema_version == 1

    def test_bom_prefixed_directive_still_refused(self):
        # A UTF-8 BOM must not smuggle a directive past the scan: ruamel strips the BOM
        # and would honor `%YAML 1.1` (silent Norway corruption; e.g. 1:30 -> 90).
        with pytest.raises(SchemaDirectiveError):
            load_schema_text("\ufeff%YAML 1.1\n---\n" + self.GOOD, collection="gadgets")

    def test_bom_prefixed_clean_document_loads(self):
        # Parity with the splitter's tolerated leading BOM (S-E1): tolerate + neutralize.
        assert load_schema_text("\ufeff" + self.GOOD, collection="gadgets").schema_version == 1

    def test_norway_tokens_stay_strings_in_schema_files(self):
        # The pinned 1.2 loader end-to-end: `no`/`off` are STRING enum members + default.
        schema = load_schema_text(
            "schema_version: 1\n"
            "attributes:\n"
            "  toggle_word:\n"
            "    type:\n"
            "      type: enum\n"
            "      values: [no, off, maybe]\n"
            "    default: no\n"
            "    definition: Norway-problem regression via the schema loader.\n"
            "    definition_version: 1\n",
            collection="gadgets",
        )
        assert schema.attributes["toggle_word"].default == "no"
        assert schema.attributes["toggle_word"].type.values == ("no", "off", "maybe")


# ---------------------------------------------------------------------------
# Closed manifests (§11.3 SV3 posture applied to the manifest itself)
# ---------------------------------------------------------------------------


class TestClosedManifest:
    def test_unknown_top_level_key_refused(self):
        with pytest.raises(SchemaError, match="closed"):
            load_schema_text(
                "schema_version: 1\nattributes: {}\nnotes: nope\n", collection="gadgets"
            )

    def test_unknown_manifest_key_refused(self):
        with pytest.raises(SchemaError, match="renamed_from"):
            _inline(extra="    renamed_from: old\n")

    @pytest.mark.parametrize("omit", ["type", "default", "definition", "definition_version"])
    def test_each_required_manifest_field(self, omit):
        # §11.1: all four declarations are required — drop each in turn.
        lines = {
            "type": "    type: number\n",
            "default": "    default: 1\n",
            "definition": "    definition: An inline test attribute.\n",
            "definition_version": "    definition_version: 1\n",
        }
        body = "schema_version: 1\nattributes:\n  sample:\n" + "".join(
            v for k, v in lines.items() if k != omit
        )
        with pytest.raises(SchemaError, match=omit):
            load_schema_text(body, collection="gadgets")

    def test_default_must_be_a_value_of_the_declared_type(self):
        with pytest.raises(ValueValidationError, match="default"):
            _inline(type_="number", default="not-a-number")

    def test_empty_definition_refused(self):
        with pytest.raises(SchemaError, match="definition"):
            load_schema_text(
                "schema_version: 1\nattributes:\n  sample:\n    type: number\n"
                '    default: 1\n    definition: "  "\n    definition_version: 1\n',
                collection="gadgets",
            )

    def test_unknown_type_kind_refused(self):
        with pytest.raises(SchemaTypeError):
            _inline(type_="tuple")

    @pytest.mark.parametrize("name", sorted(RESERVED_ATTRIBUTE_NAMES))
    def test_reserved_attribute_names_refused(self, name):
        # id/provenance/schema_version = envelope; extends = M1; metadata = §11.3 bag;
        # aliases = deferred rider. None is declarable as a schema attribute.
        with pytest.raises(SchemaError, match="reserved"):
            _inline(name=name)

    @pytest.mark.parametrize("name", ["Word", "_x", "x_", "a.b", "9", "''"])
    def test_attribute_name_alphabet(self, name):
        # RV-4 adjudication: names are §13.2 single segments (lowercase, medial [-_]).
        # `9` loads as an int key (1.2 core) and `''` as an empty string — both refused
        # by the non-empty-string check; the rest fail the segment alphabet.
        with pytest.raises(SchemaError):
            _inline(name=name)

    def test_medial_underscore_and_hyphen_names_ok(self):
        assert "word_limit" in _inline(name="word_limit").attributes
        assert "word-limit" in _inline(name="word-limit").attributes


# ---------------------------------------------------------------------------
# Version stamps: bare ints in the ONE global number-space (§11.2 SV1/SV2)
# ---------------------------------------------------------------------------


class TestVersionStamps:
    @pytest.mark.parametrize("bad", ['"3"', "true", "0", "-1", "3.0"])
    def test_schema_version_must_be_bare_positive_int(self, bad):
        with pytest.raises(VersionStampError):
            load_schema_text(f"schema_version: {bad}\nattributes: {{}}\n", collection="gadgets")

    def test_schema_version_required(self):
        with pytest.raises(VersionStampError, match="schema_version"):
            load_schema_text("attributes: {}\n", collection="gadgets")

    @pytest.mark.parametrize("bad", ['"1"', "false", "0", "1.5"])
    def test_definition_version_must_be_bare_positive_int(self, bad):
        with pytest.raises(VersionStampError):
            _inline(dv=bad)

    def test_definition_version_bounded_by_schema_version(self):
        # SV1: definition_version is valued in the schema_version number-space — an
        # attribute cannot have changed meaning at a version later than the release.
        with pytest.raises(SchemaError, match="number-space"):
            _inline(dv="4")

    def test_stamps_parse_as_python_ints(self, gadgets):
        assert type(gadgets.schema_version) is int
        assert type(gadgets.attributes["tags"].definition_version) is int


# ---------------------------------------------------------------------------
# Typed validation wired through the schema — every §11.1 type (SV3 + attrtypes)
# ---------------------------------------------------------------------------

GOOD_AND_BAD = [
    ("color", "green", "purple"),  # enum: undeclared member refused
    ("weight", 2.25, "heavy"),  # number: string refused (D1 posture)
    ("intensity", 5, 6),  # slider: 1-5 bounds
    ("span", [2, 3], [3, 2]),  # range: lo <= hi
    ("parent", "example-widget", "Not-A-Slug"),  # ref: §7.4 slug alphabet
    ("enabled", False, "yes"),  # bool: 1.2 string "yes" refused, never coerced
    ("active_window", datetime.date(2026, 7, 1), "2026-07-01"),  # date-window: real dates
    ("steps", ["one"], "one"),  # list: sequence required
    ("tags", ["x", "y"], ["x", "x"]),  # set: exact-duplicate refused
    ("labels", {"k": "v"}, {"k": 3}),  # map of text: int value refused
    ("summary", "fine", 1000),  # text: int refused (D1)
    ("briefing", "## fine", ["not", "md"]),  # markdown: string required
]


class TestTypedValidation:
    @pytest.mark.parametrize("attr,good,bad", GOOD_AND_BAD, ids=[r[0] for r in GOOD_AND_BAD])
    def test_every_type_accepts_good_and_refuses_bad(self, gadgets, attr, good, bad):
        gadgets.validate_attribute_values({attr: good})
        with pytest.raises(ValueValidationError):
            gadgets.validate_attribute_values({attr: bad})

    def test_undeclared_attribute_refused_sv3(self, gadgets):
        with pytest.raises(UndeclaredAttributeError, match="sparkle") as exc_info:
            gadgets.validate_attribute_values({"sparkle": 1})
        assert exc_info.value.code == "undeclared-attribute"

    def test_missing_attributes_are_never_an_error(self, gadgets):
        gadgets.validate_attribute_values({})  # everything rides the L0 floor

    def test_payload_shape_refusals(self, gadgets):
        with pytest.raises(SchemaValidationError):
            gadgets.validate_attribute_values("color: red")
        with pytest.raises(SchemaValidationError):
            gadgets.validate_attribute_values({1: "x"})

    def test_datetime_refused_on_date_window(self, gadgets):
        with pytest.raises(ValueValidationError):
            gadgets.validate_attribute_values(
                {"active_window": datetime.datetime(2026, 7, 1, 12, 0)}
            )


# ---------------------------------------------------------------------------
# The load-bearing list/set split (§11.1 CM3) at the declaration site
# ---------------------------------------------------------------------------


class TestCombineDeclarations:
    def test_union_on_ordered_list_is_a_schema_error(self):
        with pytest.raises(CombineOperatorError, match="union"):
            _inline(
                name="steps",
                type_="{type: list, element: text}",
                default="[a]",
                extra="    combine: union\n",
            )

    def test_combine_on_non_set_refused_even_as_replace(self):
        # §12.4 grants the schema default operator to `set` attributes only.
        with pytest.raises(SchemaError, match="set"):
            _inline(extra="    combine: replace\n")

    def test_set_subtract_reserved(self):
        with pytest.raises(CombineOperatorError, match="reserved"):
            _inline(
                name="tags",
                type_="{type: set, element: text}",
                default="[]",
                extra="    combine: '-'\n",
            )

    def test_set_of_maps_undeclarable(self):
        with pytest.raises(SchemaTypeError, match="leaf"):
            _inline(name="tags", type_="{type: set, element: map}", default="[]")


# ---------------------------------------------------------------------------
# Schema defaults feed the §7.2 identity floor (wiring into pipeline/ids.py)
# ---------------------------------------------------------------------------


class TestFloorWiring:
    def test_delta_vs_floor_from_schema_defaults(self, gadgets):
        floor = gadgets.defaults()
        effective = dict(floor, color="blue")
        # Only the deviation enters the delta; every attribute at its default — including
        # a brand-new one — is ABSENT, so no id churns (§7.2).
        assert delta_vs_floor(effective, floor) == {"color": "blue"}
        assert delta_vs_floor(dict(floor), floor) == {}


# ---------------------------------------------------------------------------
# The §11.3 artifact metadata bag: opaque, passed through, NEVER identity
# ---------------------------------------------------------------------------


class TestMetadataBag:
    SAMPLE = {"campaign": "spring-example", "nested": {"k": [1, 2]}, "when": None}

    def test_pass_through_uninterpreted(self):
        bag = MetadataBag(self.SAMPLE)
        assert bag.as_dict() == self.SAMPLE  # content equal, never transformed

    def test_mutation_isolation_both_directions(self):
        source = {"keys": ["a"]}
        bag = MetadataBag(source)
        source["keys"].append("b")  # caller mutates the source after storing
        assert bag.as_dict() == {"keys": ["a"]}
        view = bag.as_dict()
        view["keys"].append("c")  # caller mutates the passed-through view
        assert bag.as_dict() == {"keys": ["a"]}

    def test_shape_refusals(self):
        with pytest.raises(MetadataBagError):
            MetadataBag(["not", "a", "mapping"])
        with pytest.raises(MetadataBagError):
            MetadataBag({1: "non-string key"})

    def test_never_identity_bag_is_not_canonicalizable(self):
        with pytest.raises(CanonicalizationError):
            canonical_json_str(MetadataBag(self.SAMPLE))

    def test_never_identity_ids_refuses_the_metadata_key(self):
        # §7.3: ids.py refuses `metadata` in preimages outright (IDENTITY_EXCLUSIONS).
        with pytest.raises(PreimageError, match="metadata"):
            delta_vs_floor({"metadata": {"k": "v"}}, {})

    def test_repr_is_content_free(self):
        bag = MetadataBag(self.SAMPLE)
        assert "spring-example" not in repr(bag)
        assert repr(bag) == "MetadataBag(<3 keys>)"

    def test_equality_and_unhashability(self):
        assert MetadataBag(self.SAMPLE) == MetadataBag(self.SAMPLE)
        assert MetadataBag(self.SAMPLE) != MetadataBag({})
        with pytest.raises(TypeError):
            hash(MetadataBag(self.SAMPLE))

    def test_empty_bag_ok(self):
        assert MetadataBag({}).as_dict() == {}
