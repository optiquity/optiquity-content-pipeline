"""Step-10 tests: the §7 id family — preimage, minting, and the §7.4 string grammar.

Plan step-10 acceptance under test: every literal §7.4 example (baseline, fit-revision,
serialize-revision, both, +part) round-trips byte-exact; a qualifier on the wrong segment
is an invalid id; the length bound is proven at the 249-byte worst case; delta-vs-floor —
a new attribute at its default changes no id. Plus: level inference, case-sensitivity
refusals, `~pNN` ordinal widening, preimage determinism (any input order → same digest),
and the §7.3 exclusions provably absent from the preimage.

The id strings below are embedded VERBATIM from `docs/design.md` §7.4.
"""

import datetime
import json

import pytest

from pipeline.canonical import (
    canonical_json_bytes,
    canonical_json_str,
    digest_hex12,
    digest_hex16,
    sha256_hex,
)
from pipeline.ids import (
    CONTENT_DIMENSIONS,
    IDENTITY_EXCLUSIONS,
    EntryBinding,
    IdError,
    PipelineId,
    PreimageError,
    PreimageMismatchError,
    build_artifact_preimage,
    deliverable_id,
    delta_vs_floor,
    fitted_id,
    mint_artifact_id,
    mint_folio_id,
    mint_run_id,
    output_filename,
    parse_id,
    part_id,
    preimage_check,
    split_part_label,
)

# ---------------------------------------------------------------------------
# The §7.4 literal examples, verbatim.
# ---------------------------------------------------------------------------

ART = "a-9f3c07d21b44e8aa"
FIT = "a-9f3c07d21b44e8aa.linkedin.en"
DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain"
PART_SLIDES = "a-9f3c07d21b44e8aa~slides"
DEL_PART = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain~p03"
FIT_REV = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain"
SER_REV = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain_9c2e11ab34cd"
BOTH_REV = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd"
BOTH_REV_PART = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd~p03"
# Constructed per the §7.4 template (no literal example given for these shapes):
FITTED_ONLY_REV = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3"
FOLIO = "f-9c2e11ab34cd"
RUN = "r-9f3c07d21b44e8aa"

ALL_VALID = [
    ART,
    FIT,
    DEL,
    PART_SLIDES,
    DEL_PART,
    FIT_REV,
    SER_REV,
    BOTH_REV,
    BOTH_REV_PART,
    FITTED_ONLY_REV,
    FOLIO,
    RUN,
]


# ---------------------------------------------------------------------------
# Round-trip: parse ↔ render, byte-exact, every family and qualifier combination.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("id_str", ALL_VALID)
def test_every_id_round_trips_byte_exact(id_str: str) -> None:
    assert parse_id(id_str).render() == id_str


def test_baseline_fields_parse_exactly() -> None:
    parsed = parse_id(DEL)
    assert parsed.family == "artifact"
    assert parsed.root_hex == "9f3c07d21b44e8aa"
    assert parsed.platform == "linkedin"
    assert parsed.language == "en"
    assert parsed.fit_revision is None
    assert parsed.output_type == "docx"
    assert parsed.presentation == "plain"
    assert parsed.serialize_revision is None
    assert parsed.part is None


def test_fully_qualified_part_fields_parse_exactly() -> None:
    parsed = parse_id(BOTH_REV_PART)
    assert parsed.family == "artifact"
    assert parsed.level == "deliverable"
    assert parsed.platform == "linkedin"
    assert parsed.language == "en"
    assert parsed.fit_revision == "4b7a90ce12d3"
    assert parsed.output_type == "docx"
    assert parsed.presentation == "plain"
    assert parsed.serialize_revision == "9c2e11ab34cd"
    assert parsed.part == "p03"


def test_composite_part_parses_on_bare_artifact_root() -> None:
    parsed = parse_id(PART_SLIDES)
    assert parsed.level == "artifact"
    assert parsed.part == "slides"
    assert parsed.platform is None


def test_folio_and_run_parse_to_bare_roots() -> None:
    folio = parse_id(FOLIO)
    assert (folio.family, folio.level, folio.root_hex) == ("folio", "folio", "9c2e11ab34cd")
    run = parse_id(RUN)
    assert (run.family, run.level, run.root_hex) == ("run", "run", "9f3c07d21b44e8aa")


def test_parsed_id_equals_constructed_id() -> None:
    assert parse_id(BOTH_REV) == PipelineId(
        family="artifact",
        root_hex="9f3c07d21b44e8aa",
        platform="linkedin",
        language="en",
        fit_revision="4b7a90ce12d3",
        output_type="docx",
        presentation="plain",
        serialize_revision="9c2e11ab34cd",
    )


# ---------------------------------------------------------------------------
# Level inference by dot count (§7.4): 0 = artifact, 2 = fitted, 4 = deliverable.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("id_str", "level"),
    [
        (ART, "artifact"),
        (FIT, "fitted"),
        (FITTED_ONLY_REV, "fitted"),
        (DEL, "deliverable"),
        (BOTH_REV, "deliverable"),
        (PART_SLIDES, "artifact"),
        (DEL_PART, "deliverable"),
        (FOLIO, "folio"),
        (RUN, "run"),
    ],
)
def test_level_is_inferred_positionally(id_str: str, level: str) -> None:
    assert parse_id(id_str).level == level


@pytest.mark.parametrize(
    "id_str",
    [
        "a-9f3c07d21b44e8aa.linkedin",  # 1 coordinate segment — no level
        "a-9f3c07d21b44e8aa.linkedin.en.docx",  # 3 — no level
        "a-9f3c07d21b44e8aa.linkedin.en.docx.plain.extra",  # 5 — no level
        "a-9f3c07d21b44e8aa.",  # trailing dot = empty coordinate segment
    ],
)
def test_wrong_dot_counts_are_invalid(id_str: str) -> None:
    with pytest.raises(IdError, match="invalid-id"):
        parse_id(id_str)


def test_qualifiers_create_no_dot_segment() -> None:
    # FIT_REV has four dots yet stays a deliverable: the qualifier rides the language
    # segment, so positional level inference is untouched (§7.4).
    assert FIT_REV.count(".") == 4
    assert parse_id(FIT_REV).level == "deliverable"


@pytest.mark.parametrize(
    "id_str",
    ["f-9c2e11ab34cd.linkedin.en", "r-9f3c07d21b44e8aa.linkedin.en"],
)
def test_folio_and_run_ids_carry_no_coordinate_segments(id_str: str) -> None:
    with pytest.raises(IdError, match="no coordinate segments"):
        parse_id(id_str)


# ---------------------------------------------------------------------------
# `_` qualifier misplacement (§7.4: language and presentation segments ONLY).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_str",
    [
        "a-9f3c07d21b44e8aa_4b7a90ce12d3",  # root never carries a qualifier
        "a-9f3c07d21b44e8aa.linkedin_4b7a90ce12d3.en",  # platform (segment 2)
        "a-9f3c07d21b44e8aa.linkedin.en.docx_9c2e11ab34cd.plain",  # output-type (segment 4)
        "a-9f3c07d21b44e8aa~sli_des",  # part labels are slugs; `_` is not slug
        "a-9f3c07d21b44e8aa.linkedin.en.docx.plain~p03_9c2e11ab34cd",  # qualifier in part
        "f-9c2e11ab34cd_4b7a90ce12d3",  # folio roots never qualify
    ],
)
def test_qualifier_on_any_non_closing_segment_is_invalid(id_str: str) -> None:
    with pytest.raises(IdError, match="invalid-id"):
        parse_id(id_str)


@pytest.mark.parametrize(
    "id_str",
    [
        # Two qualifiers on one segment (> one per level):
        "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3_9c2e11ab34cd.docx.plain",
        # Wrong qualifier lengths:
        "a-9f3c07d21b44e8aa.linkedin.en_4b7a.docx.plain",
        "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3a.docx.plain",
        # Non-hex qualifier chars (inside the safe alphabet, outside hex):
        "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12dg.docx.plain",
        # Empty qualifier:
        "a-9f3c07d21b44e8aa.linkedin.en_.docx.plain",
    ],
)
def test_malformed_qualifiers_are_invalid(id_str: str) -> None:
    with pytest.raises(IdError, match="invalid-id"):
        parse_id(id_str)


def test_render_side_qualifier_misplacement_is_refused() -> None:
    with pytest.raises(IdError, match="fit revision"):
        PipelineId(family="artifact", root_hex="9f3c07d21b44e8aa", fit_revision="4b7a90ce12d3")
    with pytest.raises(IdError, match="serialize revision"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            platform="linkedin",
            language="en",
            serialize_revision="9c2e11ab34cd",
        )
    with pytest.raises(IdError, match="hex"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            platform="linkedin",
            language="en",
            fit_revision="4b7a",
        )


# ---------------------------------------------------------------------------
# Case sensitivity: lowercase-only, by refusal (§7.4 case-insensitive-FS safety).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_str",
    [
        "A-9F3C07D21B44E8AA",
        "a-9F3C07D21B44E8AA",
        "a-9f3c07d21b44e8aa.LinkedIn.en",
        "a-9f3c07d21b44e8aa.linkedin.en.docx.Plain",
        "a-9f3c07d21b44e8aa.linkedin.en_4B7A90CE12D3.docx.plain",
        "a-9f3c07d21b44e8aa~Slides",
        "F-9C2E11AB34CD",
    ],
)
def test_uppercase_anywhere_is_refused(id_str: str) -> None:
    with pytest.raises(IdError, match="uppercase"):
        parse_id(id_str)


def test_render_side_uppercase_is_refused() -> None:
    with pytest.raises(IdError, match="invalid-id"):
        PipelineId(
            family="artifact", root_hex="9f3c07d21b44e8aa", platform="LinkedIn", language="en"
        )
    with pytest.raises(IdError, match="invalid-id"):
        PipelineId(family="artifact", root_hex="9F3C07D21B44E8AA")


# ---------------------------------------------------------------------------
# Malformed roots, separators, alphabet.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "id_str",
    [
        "",
        "b-9f3c07d21b44e8aa",  # unknown family prefix
        "a-9f3c",  # short hex root
        "f-9f3c07d21b44e8aa",  # folio roots are hex12, not hex16
        "r-9c2e11ab34cd",  # run roots are hex16, not hex12
        "a-9f3c07d21b44e8az",  # non-hex root char
        ".a-9f3c07d21b44e8aa",  # leading dot
        "a-9f3c07d21b44e8aa..en",  # empty coordinate segment
        "a-9f3c07d21b44e8aa~",  # empty part
        "a-9f3c07d21b44e8aa~slides~p03",  # two part suffixes
        "~slides",  # no owner
        "a-9f3c07d21b44e8aa 2",  # space outside the alphabet
        "a-9f3c07d21b44e8aa/linkedin",  # slash outside the alphabet
        "a-9f3c07d21b44e8aa.linked!n.en",  # punctuation outside the alphabet
    ],
)
def test_malformed_ids_are_refused(id_str: str) -> None:
    with pytest.raises(IdError, match="invalid-id"):
        parse_id(id_str)


def test_non_string_ids_are_refused() -> None:
    with pytest.raises(IdError, match="non-empty string"):
        parse_id(None)  # type: ignore[arg-type]


def test_unknown_family_and_bad_root_are_refused_at_construction() -> None:
    with pytest.raises(IdError, match="unknown id family"):
        PipelineId(family="deliverable", root_hex="9f3c07d21b44e8aa")
    with pytest.raises(IdError, match="hex"):
        PipelineId(family="folio", root_hex="9f3c07d21b44e8aa")  # hex16 on a hex12 family


def test_partial_levels_are_refused_at_construction() -> None:
    with pytest.raises(IdError, match="BOTH platform and language"):
        PipelineId(family="artifact", root_hex="9f3c07d21b44e8aa", platform="linkedin")
    with pytest.raises(IdError, match="BOTH output-type and presentation"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            platform="linkedin",
            language="en",
            output_type="docx",
        )
    with pytest.raises(IdError, match="platform/language are missing"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            output_type="docx",
            presentation="plain",
        )
    with pytest.raises(IdError, match="no coordinate segments"):
        PipelineId(family="run", root_hex="9f3c07d21b44e8aa", platform="linkedin")


# ---------------------------------------------------------------------------
# Parts: owners are artifact- and deliverable-level ONLY (§7.1).
# ---------------------------------------------------------------------------


def test_part_on_fitted_id_is_refused_both_ways() -> None:
    with pytest.raises(IdError, match="never a fitted id"):
        parse_id("a-9f3c07d21b44e8aa.linkedin.en~p03")
    with pytest.raises(IdError, match="never a fitted id"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            platform="linkedin",
            language="en",
            part="p03",
        )
    with pytest.raises(IdError, match="artifacts and deliverables only"):
        part_id(FIT, "p03")


@pytest.mark.parametrize("id_str", ["f-9c2e11ab34cd~x", "r-9f3c07d21b44e8aa~x"])
def test_part_on_folio_or_run_is_refused(id_str: str) -> None:
    with pytest.raises(IdError, match="invalid-id"):
        parse_id(id_str)


def test_part_id_builds_the_literal_examples() -> None:
    assert part_id(ART, "slides") == PART_SLIDES
    assert part_id(DEL, "p03") == DEL_PART
    assert part_id(BOTH_REV, "p03") == BOTH_REV_PART


def test_double_part_is_refused() -> None:
    with pytest.raises(IdError, match="already carries a part"):
        part_id(PART_SLIDES, "notes")


# ---------------------------------------------------------------------------
# Structural extension: fitted_id / deliverable_id, qualifier prefix containment.
# ---------------------------------------------------------------------------


def test_fitted_and_deliverable_ids_extend_structurally() -> None:
    assert fitted_id(ART, "linkedin", "en") == FIT
    assert deliverable_id(FIT, "docx", "plain") == DEL


def test_qualifiers_flow_by_prefix_containment() -> None:
    fitted = fitted_id(ART, "linkedin", "en", fit_revision="4b7a90ce12d3")
    assert fitted == FITTED_ONLY_REV
    assert deliverable_id(fitted, "docx", "plain") == FIT_REV
    assert deliverable_id(fitted, "docx", "plain", serialize_revision="9c2e11ab34cd") == BOTH_REV
    assert deliverable_id(FIT, "docx", "plain", serialize_revision="9c2e11ab34cd") == SER_REV


def test_extension_from_the_wrong_level_is_refused() -> None:
    with pytest.raises(IdError, match="bare artifact root"):
        fitted_id(FIT, "linkedin", "en")
    with pytest.raises(IdError, match="bare artifact root"):
        fitted_id(PART_SLIDES, "linkedin", "en")
    with pytest.raises(IdError, match="extend a fitted id"):
        deliverable_id(ART, "docx", "plain")
    with pytest.raises(IdError, match="extend a fitted id"):
        deliverable_id(DEL, "docx", "plain")
    with pytest.raises(IdError, match="invalid-id"):
        fitted_id(ART, "LinkedIn", "en")  # render-side case refusal


# ---------------------------------------------------------------------------
# The length bound (§7.4): 18 + 4×41 + 2×13 + 41 = 249 ≤ 255; the 40-char slug cap.
# ---------------------------------------------------------------------------


def _worst_case_id() -> PipelineId:
    return PipelineId(
        family="artifact",
        root_hex="9f3c07d21b44e8aa",
        platform="p" * 40,
        language="l" * 40,
        fit_revision="4b7a90ce12d3",
        output_type="o" * 40,
        presentation="q" * 40,
        serialize_revision="9c2e11ab34cd",
        part="x" * 40,
    )


def test_the_249_byte_worst_case_renders_and_parses() -> None:
    rendered = _worst_case_id().render()
    assert len(rendered.encode("utf-8")) == 249  # the §7.4 arithmetic, literally
    assert parse_id(rendered) == _worst_case_id()


def test_the_40_char_slug_cap_is_enforced_on_render_and_parse() -> None:
    with pytest.raises(IdError, match="not a §7.4 slug"):
        PipelineId(
            family="artifact",
            root_hex="9f3c07d21b44e8aa",
            platform="p" * 41,
            language="en",
        )
    with pytest.raises(IdError, match="not a §7.4 slug"):
        parse_id(f"a-9f3c07d21b44e8aa.{'p' * 41}.en")
    with pytest.raises(IdError, match="not a §7.4 slug"):
        parse_id(f"a-9f3c07d21b44e8aa~{'x' * 41}")


# ---------------------------------------------------------------------------
# Filename exactness + the conditional extension append (§7.4).
# ---------------------------------------------------------------------------


def test_extension_appends_when_it_fits() -> None:
    assert output_filename(DEL, "docx") == DEL + ".docx"
    assert output_filename(BOTH_REV_PART, "md") == BOTH_REV_PART + ".md"


def test_extension_append_is_conditional_on_the_255_byte_bound() -> None:
    worst = _worst_case_id().render()  # 249 bytes — §7.4: pathological headroom is 6
    assert output_filename(worst, "docx") == worst + ".docx"  # 254 ≤ 255 → appended
    assert output_filename(worst, "abcde") == worst + ".abcde"  # 255 == 255 → appended
    assert output_filename(worst, "abcdef") == worst  # 256 > 255 → id stands alone


@pytest.mark.parametrize("extension", ["", "DOCX", "tar.gz", "a_b", ".md"])
def test_malformed_extensions_are_refused(extension: str) -> None:
    with pytest.raises(IdError, match="extension"):
        output_filename(DEL, extension)


def test_output_filename_validates_the_id_itself() -> None:
    with pytest.raises(IdError, match="invalid-id"):
        output_filename("a-9f3c07d21b44e8aa.linkedin", "docx")


# ---------------------------------------------------------------------------
# Split-part ordinals (§7.4): p01…p99, widening to the part count's natural width.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ordinal", "part_count", "label"),
    [
        (1, 7, "p01"),
        (3, 7, "p03"),
        (99, 99, "p99"),
        (3, 150, "p003"),
        (100, 150, "p100"),
        (7, 1000, "p0007"),
    ],
)
def test_split_part_ordinals_widen_with_the_part_count(
    ordinal: int, part_count: int, label: str
) -> None:
    assert split_part_label(ordinal, part_count) == label


@pytest.mark.parametrize(
    ("ordinal", "part_count"), [(0, 5), (-1, 5), (6, 5), (1, 0), (True, 5), ("3", 5)]
)
def test_invalid_split_part_ordinals_are_refused(ordinal: object, part_count: object) -> None:
    with pytest.raises(IdError, match="split-part"):
        split_part_label(ordinal, part_count)  # type: ignore[arg-type]


def test_widened_ordinals_ride_the_part_grammar() -> None:
    label = split_part_label(3, 150)
    assert part_id(DEL, label) == DEL + "~p003"
    assert parse_id(DEL + "~p003").part == "p003"


# ---------------------------------------------------------------------------
# The §7.2 preimage: shape, determinism, delta-vs-floor, goal-set semantics.
# ---------------------------------------------------------------------------


def _preimage(**overrides):
    kwargs = dict(
        topic=EntryBinding("graphify"),
        persona=EntryBinding("cto"),
        format=EntryBinding("linkedin-post"),
        voice=EntryBinding("crisp", effective={"formality": 4}, defaults={"formality": 3}),
        goals=[
            EntryBinding("explain"),
            EntryBinding("convince", effective={"cta": "book-a-demo"}, defaults={"cta": ""}),
        ],
        source_subset=["x-acme-repo", "x-acme-docs"],
        source_commit={"x-acme-repo": "0" * 40, "x-acme-docs": "1" * 40},
    )
    kwargs.update(overrides)
    return build_artifact_preimage(**kwargs)


def test_preimage_has_the_frozen_shape() -> None:
    preimage = _preimage()
    assert set(preimage) == {"dimensions", "goals", "source-subset", "source-commit"}
    assert set(preimage["dimensions"]) == set(CONTENT_DIMENSIONS)
    assert preimage["dimensions"]["voice"] == {"entry": "crisp", "delta": {"formality": 4}}
    assert preimage["dimensions"]["topic"] == {"entry": "graphify", "delta": {}}
    # The goal pair-list is sorted by entry id and carries per-entry deltas (§7.2):
    assert preimage["goals"] == [["convince", {"cta": "book-a-demo"}], ["explain", {}]]
    assert preimage["source-subset"] == ["x-acme-docs", "x-acme-repo"]
    assert preimage["source-commit"] == {"x-acme-docs": "1" * 40, "x-acme-repo": "0" * 40}


def test_preimage_is_a_pure_json_value() -> None:
    preimage = _preimage()
    assert preimage == json.loads(json.dumps(preimage))


def test_date_values_enter_the_preimage_as_iso_strings() -> None:
    preimage = _preimage(
        topic=EntryBinding("graphify", effective={"window": datetime.date(2026, 1, 15)})
    )
    assert preimage["dimensions"]["topic"]["delta"] == {"window": "2026-01-15"}


def test_same_inputs_in_any_order_yield_the_same_digest() -> None:
    base = _preimage()
    reordered = _preimage(
        goals=[
            EntryBinding("convince", effective={"cta": "book-a-demo"}, defaults={"cta": ""}),
            EntryBinding("explain"),
        ],
        source_subset=("x-acme-docs", "x-acme-repo"),
        source_commit={"x-acme-docs": "1" * 40, "x-acme-repo": "0" * 40},
    )
    assert canonical_json_bytes(base) == canonical_json_bytes(reordered)
    assert mint_artifact_id(base) == mint_artifact_id(reordered)


def test_source_subset_accepts_any_iterable_and_dedupes() -> None:
    base = _preimage()
    as_set = _preimage(source_subset={"x-acme-repo", "x-acme-docs"})
    duplicated = _preimage(source_subset=["x-acme-repo", "x-acme-repo", "x-acme-docs"])
    assert base == as_set == duplicated


def test_effective_value_key_order_never_matters() -> None:
    a = _preimage(
        voice=EntryBinding(
            "crisp", effective={"formality": 4, "warmth": 2}, defaults={"formality": 3}
        )
    )
    b = _preimage(
        voice=EntryBinding(
            "crisp", effective={"warmth": 2, "formality": 4}, defaults={"formality": 3}
        )
    )
    assert mint_artifact_id(a) == mint_artifact_id(b)


def test_goal_set_is_order_insensitive_and_dedupes_identical_pairs() -> None:
    base = _preimage()
    duplicated = _preimage(
        goals=[
            EntryBinding("explain"),
            EntryBinding("convince", effective={"cta": "book-a-demo"}, defaults={"cta": ""}),
            EntryBinding("explain"),
        ]
    )
    assert base == duplicated
    assert mint_artifact_id(base) == mint_artifact_id(duplicated)


def test_goal_entering_twice_with_different_deltas_is_refused() -> None:
    with pytest.raises(PreimageError, match="DIFFERENT deltas"):
        _preimage(
            goals=[
                EntryBinding("explain", effective={"depth": 2}, defaults={"depth": 1}),
                EntryBinding("explain", effective={"depth": 3}, defaults={"depth": 1}),
            ]
        )


def test_union_combined_sets_enter_canonically_in_any_form() -> None:
    for tags in ({"b", "a"}, {"a", "b"}, frozenset({"b", "a"}), ["a", "b"]):
        preimage = _preimage(
            voice=EntryBinding("crisp", effective={"tags": tags}, defaults={"tags": []})
        )
        assert preimage["dimensions"]["voice"]["delta"]["tags"] == ["a", "b"]


def test_a_set_at_its_default_floor_is_absent_in_any_order() -> None:
    preimage = _preimage(
        voice=EntryBinding(
            "crisp", effective={"tags": frozenset({"b", "a"})}, defaults={"tags": ["a", "b"]}
        )
    )
    assert "tags" not in preimage["dimensions"]["voice"]["delta"]


# ---------------------------------------------------------------------------
# Delta-vs-floor (§7.2): only deviations enter; type-exact comparison.
# ---------------------------------------------------------------------------


def test_delta_vs_floor_excludes_default_valued_attrs() -> None:
    assert delta_vs_floor({"tone": "warm"}, {"tone": "warm"}) == {}
    assert delta_vs_floor({"tone": "crisp"}, {"tone": "warm"}) == {"tone": "crisp"}
    assert delta_vs_floor({}, {"tone": "warm"}) == {}


def test_delta_vs_floor_includes_attrs_with_no_declared_default() -> None:
    assert delta_vs_floor({"new": 1}, {}) == {"new": 1}


def test_delta_vs_floor_comparison_is_type_exact() -> None:
    # bool is not int, 1 is not 1.0 — canonical renderings differ, so both deviate.
    assert delta_vs_floor({"flag": True}, {"flag": 1}) == {"flag": True}
    assert delta_vs_floor({"n": 1.0}, {"n": 1}) == {"n": 1.0}


def test_a_new_attribute_at_its_default_changes_no_id() -> None:
    # THE §7.2 stability property (plan step-10 acceptance): additive schema evolution
    # with the new attribute at its default mints the IDENTICAL artifact-id.
    before = mint_artifact_id(_preimage())
    after = mint_artifact_id(
        _preimage(topic=EntryBinding("graphify", effective={"depth": 3}, defaults={"depth": 3}))
    )
    assert before == after


def test_a_deviating_attribute_changes_the_id() -> None:
    before = mint_artifact_id(_preimage())
    after = mint_artifact_id(
        _preimage(topic=EntryBinding("graphify", effective={"depth": 4}, defaults={"depth": 3}))
    )
    assert before != after


def test_malformed_delta_inputs_are_refused() -> None:
    with pytest.raises(PreimageError, match="must be mappings"):
        delta_vs_floor(["not-a-mapping"], {})  # type: ignore[arg-type]
    with pytest.raises(PreimageError, match="attribute names"):
        delta_vs_floor({1: "x"}, {})
    with pytest.raises(PreimageError, match="attribute names"):
        delta_vs_floor({"": "x"}, {})


def test_uncanonicalizable_values_are_refused_loudly() -> None:
    with pytest.raises(PreimageError, match="invalid-preimage"):
        delta_vs_floor({"ts": datetime.datetime(2026, 1, 15, 12, 0)}, {})
    with pytest.raises(PreimageError, match="invalid-preimage"):
        delta_vs_floor({"m": {"inner": {1, 2}}}, {})  # nested raw set — no canonical form


# ---------------------------------------------------------------------------
# §7.3 exclusions: provably never id inputs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("excluded", sorted(IDENTITY_EXCLUSIONS))
def test_identity_exclusions_are_refused_at_the_constructor(excluded: str) -> None:
    with pytest.raises(PreimageError, match="never an identity input"):
        delta_vs_floor({excluded: "anything"}, {})
    with pytest.raises(PreimageError, match="never an identity input"):
        _preimage(goals=[EntryBinding("explain", effective={excluded: 1})])


def test_identity_exclusions_never_appear_in_a_built_preimage() -> None:
    rendered = canonical_json_str(_preimage())
    assert '"schema_version"' not in rendered
    assert '"metadata"' not in rendered


def test_mint_refuses_a_preimage_smuggling_extra_top_level_keys() -> None:
    preimage = _preimage()
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({**preimage, "metadata": {"note": "x"}})
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({**preimage, "schema_version": 3})
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({k: v for k, v in preimage.items() if k != "goals"})
    with pytest.raises(PreimageError, match="four"):
        mint_artifact_id(
            {**preimage, "dimensions": {**preimage["dimensions"], "goal": {"entry": "x"}}}
        )
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id("not-a-preimage")  # type: ignore[arg-type]


def test_mint_refuses_an_exclusion_smuggled_inside_a_delta_map() -> None:
    # RV-2: the shape guard checks attr-NAME positions one level down — a HAND-BUILT
    # preimage carrying a §7.3 exclusion as a delta-map key must fail loudly at mint.
    smuggled_dimension = _preimage()
    smuggled_dimension["dimensions"]["voice"]["delta"]["metadata"] = {"note": "x"}
    with pytest.raises(PreimageError, match="never an identity input"):
        mint_artifact_id(smuggled_dimension)
    smuggled_goal = _preimage()
    smuggled_goal["goals"] = [["explain", {"schema_version": 3}]]
    with pytest.raises(PreimageError, match="never an identity input"):
        mint_artifact_id(smuggled_goal)
    # An exclusion name nested inside an attribute VALUE is data, not the §7.3 bag —
    # attr-name positions only, so this still mints:
    value_keyed = _preimage(
        voice=EntryBinding("crisp", effective={"style": {"metadata": "a-data-value"}})
    )
    assert mint_artifact_id(value_keyed).startswith("a-")


def test_mint_refuses_junk_inner_values_one_level_down() -> None:
    # RV-2: the reviewer's probe — previously ACCEPTED (minted a-8529879a73ee23ee).
    with pytest.raises(PreimageError, match="invalid-preimage"):
        mint_artifact_id(
            {
                "dimensions": {"topic": 1, "persona": 2, "format": 3, "voice": 4},
                "goals": "junk",
                "source-subset": 7,
                "source-commit": None,
            }
        )
    # Each inner position refuses independently:
    with pytest.raises(PreimageError, match="'entry': ..., 'delta'"):
        mint_artifact_id({**_preimage(), "dimensions": dict.fromkeys(CONTENT_DIMENSIONS, 1)})
    doctored = _preimage()
    doctored["dimensions"]["topic"]["delta"] = "junk"
    with pytest.raises(PreimageError, match="delta-vs-floor map"):
        mint_artifact_id(doctored)
    with pytest.raises(PreimageError, match="pair-list"):
        mint_artifact_id({**_preimage(), "goals": "junk"})
    with pytest.raises(PreimageError, match="2-item"):
        mint_artifact_id({**_preimage(), "goals": [["explain", {}, "extra"]]})
    with pytest.raises(PreimageError, match="not a single string"):
        mint_artifact_id({**_preimage(), "source-subset": "x-acme-repo"})
    with pytest.raises(PreimageError, match="source-commit must be"):
        mint_artifact_id({**_preimage(), "source-commit": None})


# ---------------------------------------------------------------------------
# Preimage input validation: entry ids, bindings, the commit-map ↔ subset contract.
# ---------------------------------------------------------------------------


def test_entry_ids_must_be_slugs() -> None:
    with pytest.raises(PreimageError, match="not a §7.4 slug"):
        _preimage(topic=EntryBinding("Graphify"))
    with pytest.raises(PreimageError, match="not a §7.4 slug"):
        _preimage(source_subset=["Acme"], source_commit={"Acme": "0" * 40})


def test_a_bare_string_source_subset_is_refused_not_decomposed() -> None:
    # RV-1: a str is not a collection of instance ids — refuse, never iterate it
    # char-by-char (refuse-don't-coerce).
    with pytest.raises(PreimageError, match="not a single string"):
        _preimage(source_subset="x-acme-repo", source_commit={"x-acme-repo": "0" * 40})
    with pytest.raises(PreimageError, match="not a single string"):
        _preimage(source_subset=b"x-acme-repo", source_commit={"x-acme-repo": "0" * 40})


def test_non_entry_binding_inputs_are_refused() -> None:
    with pytest.raises(PreimageError, match="EntryBinding"):
        _preimage(topic="graphify")
    with pytest.raises(PreimageError, match="EntryBinding"):
        _preimage(goals=[("explain", {}, {})])


def test_commit_map_must_cover_exactly_the_source_subset() -> None:
    with pytest.raises(PreimageError, match="EXACTLY one commit"):
        _preimage(source_commit={"x-acme-repo": "0" * 40})  # missing x-acme-docs
    with pytest.raises(PreimageError, match="EXACTLY one commit"):
        _preimage(
            source_commit={
                "x-acme-repo": "0" * 40,
                "x-acme-docs": "1" * 40,
                "x-extra": "2" * 40,
            }
        )
    with pytest.raises(PreimageError, match="non-empty"):
        _preimage(source_commit={"x-acme-repo": "", "x-acme-docs": "1" * 40})
    with pytest.raises(PreimageError, match="source-commit must be"):
        _preimage(source_commit=[("x-acme-repo", "0" * 40)])


def test_empty_goal_set_and_empty_pool_are_representable() -> None:
    # Identity construction embeds no selection policy (that is M3/cascade scope):
    preimage = _preimage(goals=[], source_subset=[], source_commit={})
    assert preimage["goals"] == []
    assert preimage["source-subset"] == []
    assert mint_artifact_id(preimage).startswith("a-")


# ---------------------------------------------------------------------------
# Minting (§7.4): digest roots, determinism, the mint-time preimage check.
# ---------------------------------------------------------------------------


def test_mint_artifact_id_is_the_hex16_digest_of_the_preimage() -> None:
    preimage = _preimage()
    artifact = mint_artifact_id(preimage)
    assert artifact == f"a-{digest_hex16(preimage)}"
    parsed = parse_id(artifact)
    assert (parsed.family, parsed.level) == ("artifact", "artifact")
    assert mint_artifact_id(_preimage()) == artifact  # deterministic re-mint


def test_folio_and_run_ids_mint_with_their_ratified_encodings() -> None:
    seed = {"workspace": "acme", "n": 1}
    folio = mint_folio_id(seed)
    assert folio == f"f-{digest_hex12(seed)}"
    assert parse_id(folio).level == "folio"
    run = mint_run_id(seed)
    assert run == f"r-{digest_hex16(seed)}"
    assert parse_id(run).level == "run"


def test_uncanonicalizable_mint_seeds_are_refused() -> None:
    with pytest.raises(PreimageError, match="invalid-preimage"):
        mint_run_id({1: "non-string-key"})


def test_preimage_check_admits_unseen_and_identical_recorded_preimages() -> None:
    preimage = _preimage()
    calls: list[str] = []

    def lookup(id_str: str):
        calls.append(id_str)
        return None

    artifact = mint_artifact_id(preimage, recorded_preimage_lookup=lookup)
    assert calls == [artifact]  # the hook receives the minted id
    # A storage round-trip of the same preimage is the idempotent re-mint (§21.8):
    recorded = json.loads(json.dumps(preimage))
    assert mint_artifact_id(preimage, recorded_preimage_lookup=lambda _: recorded) == artifact


def test_preimage_check_fails_loudly_on_same_id_different_preimage() -> None:
    preimage = _preimage()
    planted = _preimage(voice=EntryBinding("warm"))  # a different preimage under this id
    with pytest.raises(PreimageMismatchError, match="preimage-mismatch"):
        mint_artifact_id(preimage, recorded_preimage_lookup=lambda _: planted)
    with pytest.raises(PreimageMismatchError, match="never silently reuses"):
        mint_folio_id({"n": 1}, recorded_preimage_lookup=lambda _: {"n": 2})


def test_preimage_check_is_usable_standalone_for_qualified_ids() -> None:
    # §7.4: the check applies to qualified ids identically — steps 25/29 call it against
    # the fit-/render-binding with their own level preimages.
    fit_inputs = {"strategy": "adapt", "hard-limits": {"chars": 3000}}
    assert preimage_check(FIT_REV, fit_inputs, None) is None
    assert preimage_check(FIT_REV, fit_inputs, json.loads(json.dumps(fit_inputs))) is None
    with pytest.raises(PreimageMismatchError, match=r"§7\.4"):
        preimage_check(FIT_REV, fit_inputs, {"strategy": "split"})
    with pytest.raises(PreimageError, match="invalid-preimage"):
        preimage_check(FIT_REV, fit_inputs, {1: "uncanonicalizable"})


# ---------------------------------------------------------------------------
# DR-3 §7.2 outline-digest preimage extension (zero-churn; PO-1/PO-2/PO-3).
# ---------------------------------------------------------------------------

#: Two valid `outline-digest` values — the full 64-char lowercase-hex SHA-256 form.
OUTLINE_DIGEST = sha256_hex(b"# Outline heading\n\n- point one\n- point two\n")
OTHER_DIGEST = sha256_hex(b"# A different outline\n")


def test_outline_digest_absent_is_byte_identical_and_mints_the_same_id() -> None:
    # PO-1 (the zero-churn thesis): outline_digest=None OMITS the key entirely, so the
    # preimage is byte-identical to the pre-DR-3 4-key object and re-mints the same id.
    base = _preimage()
    explicit_none = _preimage(outline_digest=None)
    assert set(base) == {"dimensions", "goals", "source-subset", "source-commit"}
    assert "outline-digest" not in base
    assert canonical_json_bytes(base) == canonical_json_bytes(explicit_none)
    assert mint_artifact_id(base) == mint_artifact_id(explicit_none)


def test_outline_digest_present_adds_one_key_and_changes_the_id() -> None:
    # PO-2: a supplied digest enters as a single top-level key and changes the id; a
    # DIFFERENT outline yields a DIFFERENT id; the SAME outline is deterministic.
    base = _preimage()
    driven = _preimage(outline_digest=OUTLINE_DIGEST)
    assert set(driven) == {
        "dimensions",
        "goals",
        "source-subset",
        "source-commit",
        "outline-digest",
    }
    assert driven["outline-digest"] == OUTLINE_DIGEST
    assert mint_artifact_id(driven) != mint_artifact_id(base)
    assert mint_artifact_id(_preimage(outline_digest=OTHER_DIGEST)) != mint_artifact_id(driven)
    assert mint_artifact_id(_preimage(outline_digest=OUTLINE_DIGEST)) == mint_artifact_id(driven)


def test_mint_accepts_both_preimage_shapes_and_refuses_missing_or_sixth_key() -> None:
    # PO-3: the shape guard admits the 4-key AND the 5-key (outline-digest) shape, and
    # still refuses a missing required key and a 6th unknown key under EITHER shape.
    four = _preimage()
    five = _preimage(outline_digest=OUTLINE_DIGEST)
    assert mint_artifact_id(four).startswith("a-")
    assert mint_artifact_id(five).startswith("a-")
    # A missing required key raises under both shapes:
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({k: v for k, v in four.items() if k != "goals"})
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({k: v for k, v in five.items() if k != "source-commit"})
    # A 6th unknown key raises under both shapes (drive-config is the horn-b future key —
    # today it is still refused, so landing this now needs no rework under either horn):
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({**four, "drive-config": ["x"]})
    with pytest.raises(PreimageError, match="EXACTLY"):
        mint_artifact_id({**five, "schema_version": 3})


def test_mint_refuses_a_non_string_outline_digest() -> None:
    # D-8: at mint time a hand-built preimage whose outline-digest is a nested mapping (or
    # any non-str) is refused, so it cannot smuggle a §7.3 exclusion past the attr-name scan.
    four = _preimage()
    with pytest.raises(PreimageError, match="must be a string"):
        mint_artifact_id({**four, "outline-digest": {"metadata": "x"}})
    with pytest.raises(PreimageError, match="must be a string"):
        mint_artifact_id({**four, "outline-digest": 123})


@pytest.mark.parametrize(
    "bad",
    [
        123,  # non-str
        b"a" * 64,  # bytes, not str
        "abc",  # too short
        OUTLINE_DIGEST[:-1],  # 63 chars
        OUTLINE_DIGEST + "0",  # 65 chars
        OUTLINE_DIGEST.upper(),  # uppercase hex — lowercase-only (§7.4)
        "g" * 64,  # non-hex chars
        "sk-live-abcdefghijklmnopqrstuvwxyz",  # secret-shaped (also non-64-hex)
    ],
)
def test_invalid_outline_digest_values_are_refused_at_construction(bad: object) -> None:
    with pytest.raises(PreimageError, match="outline-digest must be"):
        _preimage(outline_digest=bad)
