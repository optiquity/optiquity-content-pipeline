"""Step-31 tests: folio-type consumption at generation (§9.5/§9.6, B4-2/B4-3).

Acceptance under test here (plan step-31): the folio-type skeleton key WHITELIST is
recipe-slots + `topic_slot` (step-15 review RV-1 carry-forward) — a rendering-dimension key
such as `platform: linkedin` passes lint silently today and MUST be refused loudly here (the
reviewer's `smuggler` probe transcript is the acceptance seed); one typed run yields one recipe
skeleton per role with the sibling roster as compose context (never identity); a role may
legally recur across regenerations on MEMBERSHIP; and a role slug recorded on a member is
surfaced AS-IS after a folio-type rename, never dropped or remapped (B4-3).
"""

from pathlib import Path

import pytest

from pipeline.folios import (
    RECIPE_SLOTS,
    SKELETON_KEY_WHITELIST,
    FolioTypeError,
    MemberFact,
    MemberSpec,
    SkeletonKeyError,
    add_to_folio,
    create_folio,
    get_folio,
    group_members_by_role,
    plan_typed_run,
    validate_skeleton,
)
from pipeline.layout import registry_dir
from pipeline.schema import load_schema
from pipeline.store import WorkspaceStore
from pipeline.yamlio import load_frontmatter

_REPO_ROOT = Path(__file__).resolve().parents[1]
_FIXED = 1000.0


@pytest.fixture()
def store(tmp_path):
    return WorkspaceStore(tmp_path / "ws")


def materialize(store: WorkspaceStore, artifact_id: str) -> None:
    store.output_path(artifact_id).write_bytes(b"{}\n")


# ---------------------------------------------------------------------------
# The whitelist is the LIVE recipe-slot vocabulary + `topic_slot` (drift guard).
# ---------------------------------------------------------------------------


class TestWhitelistSource:
    def test_recipe_slots_equal_the_live_recipe_schema_attributes(self):
        # The hardcoded RECIPE_SLOTS must not drift from recipes/_schema.yaml — a slot added
        # upstream fails HERE rather than silently widening/narrowing the skeleton whitelist.
        schema = load_schema(registry_dir(_REPO_ROOT, "recipes") / "_schema.yaml")
        assert RECIPE_SLOTS == set(schema.attributes)

    def test_whitelist_is_recipe_slots_plus_topic_slot(self):
        assert SKELETON_KEY_WHITELIST == RECIPE_SLOTS | {"topic_slot"}
        assert "topic_slot" not in RECIPE_SLOTS  # topic_slot is not itself a recipe slot (RV-1)


# ---------------------------------------------------------------------------
# validate_skeleton (§9.6 DIRECTIVE): recipe slots + topic_slot pass; dimensions refused.
# ---------------------------------------------------------------------------


class TestSkeletonWhitelist:
    def test_whitelisted_keys_pass(self):
        validate_skeleton(
            {"format": "readme", "goals": ["explain"], "topic_slot": "the repo itself",
             "voice": "clear-explainer", "platforms": ["linkedin"]},
            role="readme",
        )  # every key is a recipe slot or topic_slot — no raise

    def test_smuggler_probe_platform_key_is_refused(self):
        # The step-15 RV-1 probe verbatim: `skeleton: {platform: linkedin, voice: ...}` lints
        # clean but must be refused here — `platform` (singular) is a rendering DIMENSION, not
        # the recipe's `platforms` pin slot, and a folio type never holds a dimension value.
        with pytest.raises(SkeletonKeyError) as exc:
            validate_skeleton(
                {"platform": "linkedin", "voice": "confident-advocate"}, role="smuggler"
            )
        assert "platform" in str(exc.value)

    def test_arbitrary_non_recipe_key_is_refused(self):
        with pytest.raises(SkeletonKeyError):
            validate_skeleton({"rendering_intent": "carousel"}, role="x")

    def test_non_map_skeleton_is_refused(self):
        with pytest.raises(SkeletonKeyError):
            validate_skeleton(["format", "goals"], role="x")


# ---------------------------------------------------------------------------
# plan_typed_run (§9.6): one skeleton per role + the sibling roster (context, not identity).
# ---------------------------------------------------------------------------


class TestPlanTypedRun:
    def test_roster_is_the_sibling_roles_in_declared_order(self):
        roles = [
            {"role": "readme", "skeleton": {"format": "readme"}},
            {"role": "getting-started", "skeleton": {"topic_slot": "zero to first result"}},
            {"role": "architecture"},
        ]
        plan = plan_typed_run(roles, folio_type="repo-docs")
        assert plan.roster == ("readme", "getting-started", "architecture")
        by_role = {rp.role: rp.roster for rp in plan.roles}
        assert by_role["readme"] == ("getting-started", "architecture")  # self excluded
        assert by_role["getting-started"] == ("readme", "architecture")

    def test_shipped_repo_docs_entry_plans_clean(self):
        repo_docs = registry_dir(_REPO_ROOT, "folio-types") / "repo-docs.md"
        meta, _ = load_frontmatter(repo_docs.read_text())
        plan = plan_typed_run(meta["roles"], folio_type="repo-docs")
        assert plan.roster == ("readme", "getting-started", "architecture")

    def test_a_skeleton_dimension_key_fails_the_whole_plan(self):
        roles = [{"role": "smuggler", "skeleton": {"platform": "linkedin"}}]
        with pytest.raises(SkeletonKeyError):
            plan_typed_run(roles)

    def test_duplicate_declared_role_is_refused(self):
        # §9.6: the DECLARED structure lists each role once (duplicates are legal on MEMBERSHIP,
        # not in the type). Distinct from the regeneration case tested below.
        roles = [{"role": "readme"}, {"role": "readme"}]
        with pytest.raises(FolioTypeError):
            plan_typed_run(roles)

    def test_malformed_roles_are_refused(self):
        with pytest.raises(FolioTypeError):
            plan_typed_run("readme")
        with pytest.raises(FolioTypeError):
            plan_typed_run([{"skeleton": {"format": "readme"}}])  # no `role`


# ---------------------------------------------------------------------------
# Regeneration duplicate-role legality on MEMBERSHIP (§9.6): two members, one role.
# ---------------------------------------------------------------------------


class TestRegenerationDuplicateRole:
    def test_two_members_may_share_a_role(self, store):
        old = "a-9f3c07d21b44e8aa"  # the original member
        new = "a-1234567890abcdef"  # a regenerated member — a NEW artifact-id, same role
        for art in (old, new):
            materialize(store, art)
        folio = create_folio(store, purpose="docs", folio_type="repo-docs").folio_id
        add_to_folio(store, folio, [MemberSpec(old, role="readme")], clock=lambda: _FIXED)
        add_to_folio(store, folio, [MemberSpec(new, role="readme")], clock=lambda: _FIXED + 5)
        roles = [m.role for m in get_folio(store, folio).members]
        assert roles == ["readme", "readme"]  # append-only; duplicate roles permitted (§9.6)


# ---------------------------------------------------------------------------
# Unknown recorded role surfaced AS-IS after a folio-type rename (B4-3 acceptance).
# ---------------------------------------------------------------------------


class TestRecordedRoleIsPointInTime:
    def test_get_folio_surfaces_the_recorded_role_verbatim_after_a_rename(self, store):
        art = "a-9f3c07d21b44e8aa"
        materialize(store, art)
        folio = create_folio(store, purpose="docs", folio_type="repo-docs").folio_id
        add_to_folio(store, folio, [MemberSpec(art, role="readme")], clock=lambda: _FIXED)
        # The folio type later renames readme -> overview (config migrates, MIG-7); the member
        # record is a machine record and is NEVER migrated — get folio still shows `readme`.
        assert get_folio(store, folio).members[0].role == "readme"

    def test_group_members_by_role_surfaces_unknown_recorded_role_as_is(self):
        # Current (post-rename) declared roles no longer contain `readme`; the member's recorded
        # `readme` is surfaced AS-IS in `unknown`, never dropped and never remapped to `overview`.
        members = (
            MemberFact("a-9f3c07d21b44e8aa", _FIXED, None, "readme"),
            MemberFact("a-1234567890abcdef", _FIXED, None, "getting-started"),
            MemberFact("a-aaaaaaaaaaaaaaaa", _FIXED, None, None),  # a one-off, no role
        )
        grouping = group_members_by_role(
            ["overview", "getting-started", "architecture"], members
        )
        declared = {role: [m.artifact_id for m in ms] for role, ms in grouping.declared}
        unknown = {role: [m.artifact_id for m in ms] for role, ms in grouping.unknown}
        assert declared["getting-started"] == ["a-1234567890abcdef"]
        assert declared["overview"] == [] and declared["architecture"] == []
        assert unknown == {"readme": ["a-9f3c07d21b44e8aa"]}  # AS-IS, never remapped (B4-3)
        assert [m.artifact_id for m in grouping.unroled] == ["a-aaaaaaaaaaaaaaaa"]

    def test_every_member_lands_in_exactly_one_bucket(self):
        members = (
            MemberFact("a-9f3c07d21b44e8aa", _FIXED, None, "readme"),
            MemberFact("a-1234567890abcdef", _FIXED, None, "ghost"),
            MemberFact("a-aaaaaaaaaaaaaaaa", _FIXED, None, None),
        )
        grouping = group_members_by_role(["readme"], members)
        counted = (
            sum(len(ms) for _, ms in grouping.declared)
            + sum(len(ms) for _, ms in grouping.unknown)
            + len(grouping.unroled)
        )
        assert counted == len(members)
