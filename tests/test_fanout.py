"""Step-19 tests — `pipeline/fanout.py`: fanout enumeration (design §8, §5.1/§5.2, §12.3).

Pure-enumeration coverage (no cascade, no registries — the wiring is
`tests/test_plan.py`): request normalization and loud refusals; the content cross
product with the goal-set stacking exception; rendering coordinates (request > pin,
multi-pin enumeration, the platform-less rules); the ADVISORY nonsensical-pairing
catalog (warn-only shape; structurally no folio triggers — §8/CA3); the goal-set
overload threshold. The one repo read (folio-types ids) is read-only.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from pipeline.fanout import (
    CONTENT_AXES,
    GOAL_SET_OVERLOAD_THRESHOLD,
    NONSENSICAL_PAIRING_CATALOG,
    PAIRING_TRIGGER_FIELDS,
    RENDERING_AXES,
    ContentCombination,
    FanoutError,
    PairingTrigger,
    RenderCoordinate,
    SelectionRequest,
    content_combinations,
    coordinate_from_payload,
    coordinate_payload,
    goal_set_overloaded,
    pairing_advisory,
    render_coordinates,
)
from pipeline.layout import registry_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


# ------------------------------------------------------------------------------------
# Request normalization & loud refusals (§5.1/§5.2 posture)
# ------------------------------------------------------------------------------------


def test_request_normalizes_sequences_to_tuples() -> None:
    request = SelectionRequest(
        recipe="explainer-post",
        topics=["x-t-one", "x-t-two"],
        platforms=["github"],
        goal_sets=[["explain", "convince"]],
    )
    assert request.topics == ("x-t-one", "x-t-two")
    assert request.platforms == ("github",)
    assert request.goal_sets == (("explain", "convince"),)


def test_request_is_frozen() -> None:
    request = SelectionRequest(recipe="explainer-post")
    with pytest.raises(FrozenInstanceError):
        request.topics = ("x-t",)  # type: ignore[misc]


def test_axes_vocabulary_is_the_nine_axis_split() -> None:
    # §5.1: Goal is set-valued (goal_sets, not an axis); the other eight axes fan out.
    assert CONTENT_AXES == ("topics", "personas", "formats", "voices")
    assert RENDERING_AXES == ("platforms", "languages", "output_types", "presentations")


def test_bare_string_axis_is_refused() -> None:
    with pytest.raises(FanoutError, match="not a single string"):
        SelectionRequest(recipe="explainer-post", topics="x-topic")
    with pytest.raises(FanoutError, match="not a single string"):
        SelectionRequest(recipe="explainer-post", platforms="github")


def test_non_sequence_axis_is_refused() -> None:
    with pytest.raises(FanoutError, match="sequence of entry ids"):
        SelectionRequest(recipe="explainer-post", topics=42)


def test_duplicate_axis_value_is_loud_never_silently_deduped() -> None:
    with pytest.raises(FanoutError, match="duplicate entry id"):
        SelectionRequest(recipe="explainer-post", topics=["x-t", "x-t"])


@pytest.mark.parametrize("bad", ["Bad-Case", "has space", "-edge", "a" * 41, "", 7])
def test_non_slug_member_is_refused(bad: object) -> None:
    with pytest.raises(FanoutError):
        SelectionRequest(recipe="explainer-post", personas=[bad])


def test_recipe_id_is_slug_validated() -> None:
    with pytest.raises(FanoutError, match="recipe"):
        SelectionRequest(recipe="Not A Slug")


def test_duplicate_goal_id_inside_one_goal_set_is_loud() -> None:
    with pytest.raises(FanoutError, match="duplicate goal id"):
        SelectionRequest(recipe="explainer-post", goal_sets=[["explain", "explain"]])


def test_permuted_duplicate_goal_set_variants_are_refused() -> None:
    # PC2: identical canonical sets in any order are ONE designed item — two variants
    # canonicalizing equal would mint one artifact-id twice.
    with pytest.raises(FanoutError, match="exactly-once cover"):
        SelectionRequest(
            recipe="explainer-post",
            goal_sets=[["explain", "convince"], ["convince", "explain"]],
        )


def test_goal_sets_malformed_shapes_are_refused() -> None:
    with pytest.raises(FanoutError, match="sequence of goal-sets"):
        SelectionRequest(recipe="explainer-post", goal_sets="explain")
    with pytest.raises(FanoutError, match="one goal-set"):
        SelectionRequest(recipe="explainer-post", goal_sets=["explain"])


def test_empty_goal_set_variant_is_legal() -> None:
    # §12.3: the L0 baseline goal-set is empty — an explicit empty variant selects it.
    request = SelectionRequest(recipe="explainer-post", goal_sets=[[]])
    assert request.goal_sets == ((),)
    (combo,) = content_combinations(request)
    assert combo.goals == ()


# ------------------------------------------------------------------------------------
# Content fanout (§8): cross product; goal-set stacking exception (§5.2)
# ------------------------------------------------------------------------------------


def test_empty_request_is_one_combination_all_unset() -> None:
    (combo,) = content_combinations(SelectionRequest(recipe="explainer-post"))
    assert combo == ContentCombination(
        topic=None, persona=None, format=None, voice=None, goals=None
    )


def test_single_selection_yields_single_combination() -> None:
    (combo,) = content_combinations(
        SelectionRequest(recipe="explainer-post", topics=["x-t"], personas=["tech-journalist"])
    )
    assert combo.topic == "x-t"
    assert combo.persona == "tech-journalist"
    assert combo.format is None and combo.voice is None and combo.goals is None


def test_multi_select_is_the_full_cross_product() -> None:
    combos = content_combinations(
        SelectionRequest(
            recipe="explainer-post",
            topics=["x-a", "x-b"],
            personas=["tech-journalist", "product-reviewer"],
            formats=["readme", "long-form-essay", "how-to-documentation"],
        )
    )
    assert len(combos) == 2 * 2 * 3
    assert len(set(combos)) == len(combos)  # id-distinct coordinates, no repeats
    assert {c.topic for c in combos} == {"x-a", "x-b"}
    assert {c.format for c in combos} == {"readme", "long-form-essay", "how-to-documentation"}


def test_goal_set_stacks_into_one_combination_variants_fan_out() -> None:
    # §5.2: multi-select of goals STACKS (one artifact); goal VARIANTS are a list of
    # goal-sets — one combination per set, never per goal.
    stacked = content_combinations(
        SelectionRequest(recipe="explainer-post", goal_sets=[["explain", "convince"]])
    )
    assert len(stacked) == 1
    assert stacked[0].goals == ("explain", "convince")
    variants = content_combinations(
        SelectionRequest(recipe="explainer-post", goal_sets=[["explain"], ["convince"]])
    )
    assert [c.goals for c in variants] == [("explain",), ("convince",)]


def test_enumeration_order_is_deterministic() -> None:
    request = SelectionRequest(
        recipe="explainer-post", topics=["x-b", "x-a"], personas=["tech-journalist"]
    )
    assert content_combinations(request) == content_combinations(request)
    # Authored order, axis-major: topics vary outermost, exactly as given.
    assert [c.topic for c in content_combinations(request)] == ["x-b", "x-a"]


# ------------------------------------------------------------------------------------
# Rendering fanout (§8/§12.3): request > pin; the platform-less rules
# ------------------------------------------------------------------------------------


def test_rendering_cross_product() -> None:
    coords = render_coordinates(
        SelectionRequest(
            recipe="explainer-post",
            platforms=["github", "linkedin"],
            languages=["en"],
            output_types=["md", "html"],
            presentations=["plain"],
        )
    )
    assert len(coords) == 2 * 1 * 2 * 1
    assert len(set(coords)) == 4
    assert coords[0] == RenderCoordinate(
        platform="github", language="en", output_type="md", presentation="plain"
    )


def test_unselected_rendering_axes_stay_unset_for_the_cascade() -> None:
    (coord,) = render_coordinates(SelectionRequest(recipe="explainer-post", platforms=["github"]))
    assert coord.platform == "github"
    assert coord.language is None and coord.output_type is None and coord.presentation is None


def test_multi_pin_enumerates_instead_of_ambiguity() -> None:
    # The step-16 `_single_pin` AmbiguousSelectionError counterpart: fanout ENUMERATES
    # multiple recipe pins (§8: pins are rendering targets; multi-pin = fanout).
    coords = render_coordinates(
        SelectionRequest(recipe="x-r"),
        pinned_platforms=("github", "linkedin"),
        pinned_output_types=("md",),
    )
    assert {(c.platform, c.output_type) for c in coords} == {
        ("github", "md"),
        ("linkedin", "md"),
    }


def test_request_selection_replaces_recipe_pins_per_axis() -> None:
    # §12.3: run > pin, most-local-wins REPLACE (§12.4) — never a union.
    coords = render_coordinates(
        SelectionRequest(recipe="x-r", platforms=["corporate-website"]),
        pinned_platforms=("github", "linkedin"),
        pinned_languages=("en",),
    )
    assert {c.platform for c in coords} == {"corporate-website"}
    assert {c.language for c in coords} == {"en"}  # unselected axis: the pin holds


def test_no_platform_and_no_rendering_selection_is_compose_only() -> None:
    assert render_coordinates(SelectionRequest(recipe="explainer-post")) == ()


def test_rendering_selection_without_platform_is_a_loud_refusal() -> None:
    # §12.3: Platform has no default rung; §7.4: no platform-less deliverable-id —
    # dropping the selections would be a silent skip (§21.6). NOT a pairing veto (Q4).
    with pytest.raises(FanoutError, match="no platform"):
        render_coordinates(SelectionRequest(recipe="explainer-post", output_types=["plain-text"]))
    with pytest.raises(FanoutError, match="no platform"):
        render_coordinates(SelectionRequest(recipe="explainer-post"), pinned_languages=("en",))


# ------------------------------------------------------------------------------------
# The advisory pairing catalog (§8): warn-only; structurally no folio triggers (CA3)
# ------------------------------------------------------------------------------------


def test_the_design_example_pairing_is_cataloged() -> None:
    trigger = pairing_advisory("readme", "linkedin")
    assert trigger is not None
    assert "README" in trigger.rationale or "readme" in trigger.rationale


def test_uncataloged_pairings_are_silent() -> None:
    # The emergent allow-list (Q4): a weird-but-uncataloged pairing draws nothing.
    assert pairing_advisory("product-requirements-document", "linkedin") is None
    assert pairing_advisory("readme", "github") is None


def test_catalog_shape_cannot_express_a_folio_trigger() -> None:
    # §8: "the lint catalog contains no folio-based pairing triggers" — enforced by
    # SHAPE: the trigger record has exactly format/platform/rationale slots (CA3).
    assert PAIRING_TRIGGER_FIELDS == ("format", "platform", "rationale")
    for trigger in NONSENSICAL_PAIRING_CATALOG:
        assert not hasattr(trigger, "folio_type")
        assert not hasattr(trigger, "folio")


def test_catalog_rows_never_key_a_folio_type_id() -> None:
    # Belt-and-braces on top of the shape proof: no row names a shipped folio-type id
    # in either slot (read-only scan of the real registry).
    folio_type_ids = {
        path.stem
        for path in registry_dir(REPO_ROOT, "folio-types").glob("*.md")
        if not path.name.startswith("_")
    }
    assert folio_type_ids  # the registry ships at least repo-docs
    for trigger in NONSENSICAL_PAIRING_CATALOG:
        assert trigger.format not in folio_type_ids
        assert trigger.platform not in folio_type_ids


def test_catalog_rows_are_slug_valid() -> None:
    for trigger in NONSENSICAL_PAIRING_CATALOG:
        assert isinstance(trigger, PairingTrigger)
        assert trigger.rationale
    with pytest.raises(FanoutError):
        PairingTrigger(format="Not A Slug", platform="linkedin", rationale="x")


# ------------------------------------------------------------------------------------
# Goal-set overload (§8: warns, never blocks)
# ------------------------------------------------------------------------------------


def test_goal_set_overload_threshold() -> None:
    assert GOAL_SET_OVERLOAD_THRESHOLD == 3
    assert not goal_set_overloaded(("a", "b", "c"))
    assert goal_set_overloaded(("a", "b", "c", "d"))
    assert not goal_set_overloaded(())


# ------------------------------------------------------------------------------------
# DR-3 (horn (a) / B1): the per-coordinate outline DRIVE map (SelectionRequest.outlines)
# ------------------------------------------------------------------------------------


class TestOutlineDriveMap:
    """The `outlines` drive map: coordinate -> bare 64-hex outline-digest. Normalized to a
    deterministic tuple of `(canonical-coordinate, digest)` pairs (goals SORTED — the §7.2
    goal-set is a set); a bad digest / non-coordinate key / duplicate coordinate is LOUD; absent
    -> `()` (outline-less, byte-neutral). `coordinate_payload`/`coordinate_from_payload` round-trip
    (the §20 token/wire form)."""

    D1 = "a" * 64
    D2 = "b" * 64

    def test_absent_outlines_is_empty(self):
        assert SelectionRequest(recipe="explainer-post").outlines == ()

    def test_mapping_is_normalized_to_sorted_pairs(self):
        c = ContentCombination(topic="x-t", persona=None, format=None, voice=None, goals=None)
        req = SelectionRequest(recipe="explainer-post", topics=["x-t"], outlines={c: self.D1})
        assert req.outlines == ((c, self.D1),)

    def test_outline_for_is_goal_order_independent(self):
        # canonical: the map keys on the SORTED goal-set, so authored goal order does not matter.
        key = ContentCombination("x-t", None, None, None, ("b", "a"))
        req = SelectionRequest(recipe="explainer-post", topics=["x-t"], outlines={key: self.D1})
        lookup = ContentCombination("x-t", None, None, None, ("a", "b"))
        assert req.outline_for(lookup) == self.D1
        assert req.outline_for(ContentCombination("x-t", None, None, None, None)) is None

    def test_coordinate_payload_round_trips(self):
        c = ContentCombination(topic="x-t", persona="p", format=None, voice="v", goals=("a", "b"))
        assert coordinate_from_payload(coordinate_payload(c)) == c

    def test_bad_digest_is_refused(self):
        c = ContentCombination("x-t", None, None, None, None)
        with pytest.raises(FanoutError):
            SelectionRequest(recipe="explainer-post", outlines={c: "not-a-64-hex-digest"})

    def test_non_coordinate_key_is_refused(self):
        with pytest.raises(FanoutError):
            SelectionRequest(recipe="explainer-post", outlines={"x-t": self.D1})

    def test_duplicate_canonical_coordinate_is_loud(self):
        a = ContentCombination("x-t", None, None, None, ("a", "b"))
        b = ContentCombination("x-t", None, None, None, ("b", "a"))  # same sorted set
        with pytest.raises(FanoutError, match="same coordinate"):
            SelectionRequest(recipe="explainer-post", outlines=[(a, self.D1), (b, self.D2)])
