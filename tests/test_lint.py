"""Tests for pipeline/lint.py + scripts/schema-lint.sh — plan step 13 (SV11, design §11.7).

Covers every SV11 clause with a firing negative case, via the REC-3-style seam
(`lint_tree(root=<tmp tree>)` / `main(["--root", …])`): clause 1 (schema change without a
bump; version regression), clause 2 (meaning change without a shipped map-or-prompt —
definition_version bump AND removal forms; undeclared type change), clause 3 (lockstep),
clause 4 (window sanity: premature prune, plus the step-12 RV-3 carry-forwards —
future-dated and non-monotonic `released:` dates), the §27.4 deterministic-map
totality/composition rules, the step-11 RV-3 carry-forward (cross-collection
schema_version equality), and the wired per-entry validation (entry-identity match §11.1
B4, slug §7.4, Q15 default-deny provenance §10, closed schema SV3, `x-` namespacing SV5).

Scope proofs: the REAL repo root lints clean with ZERO collections scanned — the tracked
tests/fixtures/registries/gadgets tree (which contains entries and a trailing stamp) is
structurally outside the scan scope (PA-1b analogue for the lint), and
workspaces/workspace.template/ is exempt (PA-1a).

All fixture content is obviously generic and lives under pytest tmp_path.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

from pipeline.lint import (
    CODE_CHANGE_WITHOUT_BUMP,
    CODE_DEFINITION_VERSION_REGRESSION,
    CODE_FUTURE_RELEASE,
    CODE_LOCKSTEP,
    CODE_MAP_NOT_TOTAL,
    CODE_MEANING_WITHOUT_STEP,
    CODE_MISSING_SCHEMA,
    CODE_NON_MONOTONIC,
    CODE_PREMATURE_PRUNE,
    CODE_SCHEMA_VERSION_SKEW,
    CODE_STAMP_AHEAD,
    CODE_STEP_AHEAD,
    CODE_STEP_COMPOSITION,
    CODE_STEP_MUTATED,
    CODE_UNDECLARED_MEANING_CHANGE,
    CODE_VERSION_REGRESSION,
    REGISTRY_ROOTS,
    baseline_from_dir,
    baseline_from_git,
    iter_lint_collections,
    lint_tree,
    main,
    render_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_LINT = REPO_ROOT / "scripts" / "schema-lint.sh"
NOW = date(2026, 7, 12)

SCHEMA_V1 = """\
schema_version: 1
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 1
  size:
    type: number
    default: 1
    definition: The example size number.
    definition_version: 1
"""

#: v2 redefines `color` (meaning change at v2: new enum domain).
SCHEMA_V2_MEANING = """\
schema_version: 2
attributes:
  color:
    type:
      type: enum
      values: [crimson, lime, navy]
    default: crimson
    definition: The example color token, redefined.
    definition_version: 2
  size:
    type: number
    default: 1
    definition: The example size number.
    definition_version: 1
"""

#: A total, composing v2 map for the v1→v2 `color` redefinition.
REGISTRY_COLOR_MAP = """\
steps:
  - id: color-remap
    version: 2
    released: 2026-07-01
    collection: topics
    attribute: color
    map: {red: crimson, green: lime, blue: navy}
"""


def build_tree(base: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return base


def entry_text(
    entry_id: str, *, provenance: str = "framework", stamp: int = 1, extra: str = ""
) -> str:
    return (
        f"---\nid: {entry_id}\nprovenance: {provenance}\nschema_version: {stamp}\n"
        f"{extra}---\nobviously generic fixture body\n"
    )


def codes(report) -> list[str]:
    return report.codes()


# -----------------------------------------------------------------------------------
# Snapshot passes: wired per-entry validation (the Q15 guard half, §10 rule 4)
# -----------------------------------------------------------------------------------


def test_clean_tree_is_green(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/fixture-alpha.md": entry_text("fixture-alpha", extra="color: blue\n"),
            "topics/example.template.md": "# template scaffolding - never an entry\n",
        },
    )
    report = lint_tree(root, now=NOW)
    assert report.ok, render_report(report)
    assert report.collections_scanned == 1
    assert report.entries_scanned == 1  # the template file is not an entry (PA-1a)


def test_entry_identity_mismatch_fails(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/wrong-name.md": entry_text("fixture-alpha"),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == ["entry-identity-mismatch"]


def test_missing_provenance_is_default_denied(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/fixture-alpha.md": (
                "---\nid: fixture-alpha\nschema_version: 1\n---\nbody\n"
            ),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == ["missing-or-ambiguous-provenance"]


def test_undeclared_attribute_rejected_closed_schema(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/fixture-alpha.md": entry_text("fixture-alpha", extra="mystery: 1\n"),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == ["undeclared-attribute"]


def test_namespace_violation_rejected(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/x-fixture-alpha.md": entry_text("x-fixture-alpha", provenance="framework"),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == ["namespace-violation"]


def test_instance_entry_with_x_prefix_is_lint_clean(tmp_path):
    """Schema-lint runs on instance-side repos too (§10 rule 5): a well-formed
    `provenance: instance` + `x-` entry is legitimate config, not a lint finding —
    keeping it out of the PUBLIC repo is check-no-content.sh's job."""
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/x-fixture-ours.md": entry_text("x-fixture-ours", provenance="instance"),
        },
    )
    assert lint_tree(root, now=NOW).ok


def test_bad_filename_slug_rejected(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/Bad_Slug.md": entry_text("bad-slug"),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == ["invalid-entry"]


def test_registry_root_with_entries_but_no_schema_fails(tmp_path):
    root = build_tree(tmp_path, {"voices/fixture-calm.md": entry_text("fixture-calm")})
    report = lint_tree(root, now=NOW)
    assert codes(report) == [CODE_MISSING_SCHEMA]
    assert "voices" in report.findings[0].path


def test_stamp_ahead_of_schema_fails(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/fixture-alpha.md": entry_text("fixture-alpha", stamp=9),
        },
    )
    assert codes(lint_tree(root, now=NOW)) == [CODE_STAMP_AHEAD]


# -----------------------------------------------------------------------------------
# Carry-forward (step-11 RV-3): cross-collection schema_version EQUALITY
# -----------------------------------------------------------------------------------


def test_schema_version_skew_across_collections_fails(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "personas/_schema.yaml": SCHEMA_V1.replace("schema_version: 1", "schema_version: 2"),
        },
    )
    report = lint_tree(root, now=NOW)
    assert codes(report) == [CODE_SCHEMA_VERSION_SKEW]
    detail = report.findings[0].detail
    assert "topics/_schema.yaml=1" in detail and "personas/_schema.yaml=2" in detail


def test_equal_versions_across_collections_are_green(tmp_path):
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V1, "personas/_schema.yaml": SCHEMA_V1},
    )
    assert lint_tree(root, now=NOW).ok


# -----------------------------------------------------------------------------------
# SV11 clause 3: lockstep
# -----------------------------------------------------------------------------------


def test_lockstep_violation_framework_entry_stale_for_redefined_attr(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING,
            "topics/fixture-alpha.md": entry_text(
                "fixture-alpha", stamp=1, extra="color: crimson\n"
            ),
        },
    )
    report = lint_tree(root, now=NOW)
    assert codes(report) == [CODE_LOCKSTEP]
    assert "'color'" in report.findings[0].detail


def test_lockstep_ok_when_stale_entry_does_not_set_redefined_attr(tmp_path):
    """Clause 3 is scoped to attributes the entry SETS: a trailing stamp alone (riding
    the L0 floor, §12.2) is legal — the gadgets fixture's example-base pattern."""
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING,
            "topics/fixture-alpha.md": entry_text("fixture-alpha", stamp=1, extra="size: 2\n"),
        },
    )
    assert lint_tree(root, now=NOW).ok


def test_lockstep_does_not_apply_to_instance_entries(tmp_path):
    """A stale INSTANCE entry is drift/migration's business (§11.5/§11.6), not a
    framework lockstep defect."""
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING,
            "topics/x-fixture-ours.md": entry_text(
                "x-fixture-ours", provenance="instance", stamp=1, extra="color: crimson\n"
            ),
        },
    )
    assert lint_tree(root, now=NOW).ok


# -----------------------------------------------------------------------------------
# SV11 clauses 1–2: the baseline diff (schema change / meaning change discipline)
# -----------------------------------------------------------------------------------


def test_schema_change_without_version_bump_fails(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(
        tmp_path / "cur",
        {"topics/_schema.yaml": SCHEMA_V1.replace("default: red", "default: green")},
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_CHANGE_WITHOUT_BUMP]


def test_wording_only_change_with_bump_is_green(tmp_path):
    """MIG-3: no-op-heavy releases are fine — a prose definition edit + global bump
    needs no migration step (definition_version does not move)."""
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(
        tmp_path / "cur",
        {
            "topics/_schema.yaml": SCHEMA_V1.replace("schema_version: 1", "schema_version: 2")
            .replace("The example color token.", "The example color token (clearer prose).")
        },
    )
    assert lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)).ok


# -----------------------------------------------------------------------------------
# §11.2 additive-at-floor exemption to SV11 clause 1 (in-development schema evolution)
# -----------------------------------------------------------------------------------

#: NEW attributes each declared at its type's EMPTY L0 floor (text "", set [], map {}).
_ADD_FLOORS = """\
  note:
    type: text
    default: ""
    definition: An additive text attribute at its empty floor.
    definition_version: 1
  tags:
    type:
      type: set
      element: text
    default: []
    definition: An additive set attribute at its empty floor.
    definition_version: 1
  meta:
    type: map
    default: {}
    definition: An additive map attribute at its empty floor.
    definition_version: 1
"""

#: A NEW attribute with a NON-empty scalar default (a number floor of 5, not additive-at-floor).
_ADD_NONEMPTY = """\
  rank:
    type: number
    default: 5
    definition: An additive attribute with a NON-empty scalar default.
    definition_version: 1
"""

#: A NEW enum attribute defaulting to the empty string — a SCALAR, so NOT auto-empty (conservative
#: §11.2 rule: only container/text kinds get the auto-empty floor; an enum default must bump).
_ADD_ENUM_EMPTY = """\
  mode:
    type:
      type: enum
      values: ["", fast, slow]
    default: ""
    definition: A new enum attribute whose default is the empty member.
    definition_version: 1
"""

#: SCHEMA_V1 with the `size` attribute REMOVED (a removal is never additive-at-floor).
_REMOVE_SIZE = """\
schema_version: 1
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 1
"""


def test_additive_at_floor_new_attributes_need_no_bump(tmp_path):
    # §11.2 (SV2): NEW attributes each at their type's EMPTY L0 floor (text "", set [], map {})
    # are legal in-development with NO schema_version bump — every pre-existing entry rides the
    # floor and every id/digest is byte-identical (the recipe `lexicon: text ""` slot is exactly
    # this shape). The exemption is what keeps DR-2 C3 schema-lint clean without a global bump.
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1 + _ADD_FLOORS})
    assert lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)).ok


def test_additive_new_attribute_with_nonempty_default_still_needs_a_bump(tmp_path):
    # A NON-empty scalar default is NOT additive-at-floor (it could change output for a pre-existing
    # entry): clause 1 STILL fires. Enforcement is NOT weakened for the non-floor case.
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1 + _ADD_NONEMPTY})
    assert codes(lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))) == [
        CODE_CHANGE_WITHOUT_BUMP
    ]


def test_additive_new_enum_at_empty_member_still_needs_a_bump(tmp_path):
    # The conservative boundary: an enum default of "" is a SCALAR, NOT the container/text
    # auto-empty floor — so it is not exempt and clause 1 fires (only text/markdown/map/set/list).
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1 + _ADD_ENUM_EMPTY})
    assert codes(lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))) == [
        CODE_CHANGE_WITHOUT_BUMP
    ]


def test_removal_still_needs_a_bump_and_a_migration_step(tmp_path):
    # A removal is NOT additive-at-floor: clause 1 (version bump) AND clause 2 (the meaning step)
    # both fire — the exemption does not weaken removal enforcement.
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": _REMOVE_SIZE})
    found = codes(lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)))
    assert CODE_CHANGE_WITHOUT_BUMP in found
    assert CODE_MEANING_WITHOUT_STEP in found


def test_shared_attribute_change_is_not_masked_by_an_additive_attribute(tmp_path):
    # Narrowness proof: even ALONGSIDE a legal additive-at-floor attribute, a SHARED attribute's
    # spec change is not exempt — clause 1 still fires (the exemption covers ONLY pure additions).
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(
        tmp_path / "cur",
        {"topics/_schema.yaml": SCHEMA_V1.replace("default: red", "default: green") + _ADD_FLOORS},
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert CODE_CHANGE_WITHOUT_BUMP in codes(report)


def test_no_schema_change_is_clean(tmp_path):
    # The identity floor: an unchanged schema against its own baseline is clean (no clause fires).
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1})
    assert lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)).ok


def test_schema_version_regression_fails(tmp_path):
    base = build_tree(
        tmp_path / "base",
        {"topics/_schema.yaml": SCHEMA_V1.replace("schema_version: 1", "schema_version: 3")},
    )
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1})
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert CODE_VERSION_REGRESSION in codes(report)


def test_meaning_change_without_step_fails(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V2_MEANING})
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_MEANING_WITHOUT_STEP]
    assert "'color'" in report.findings[0].detail


def test_meaning_change_with_covering_map_is_green(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(
        tmp_path / "cur",
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING,
            "pipeline/migrations.yaml": REGISTRY_COLOR_MAP,
        },
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert report.ok, render_report(report)


def test_meaning_change_with_covering_prompt_is_green(tmp_path):
    """MIG-4's other shape: a prompt covers an ambiguous meaning change."""
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    registry = """\
steps:
  - id: color-decide
    version: 2
    released: 2026-07-01
    collection: topics
    attribute: color
    prompt: Pick the nearest redefined color for each entry.
"""
    cur = build_tree(
        tmp_path / "cur",
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    assert lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)).ok


def test_attribute_removal_without_step_fails(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    removed = """\
schema_version: 2
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 1
"""
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": removed})
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_MEANING_WITHOUT_STEP]
    assert "'size'" in report.findings[0].detail and "removed" in report.findings[0].detail


def test_attribute_removal_with_drop_step_is_green(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    removed = """\
schema_version: 2
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 1
"""
    registry = """\
steps:
  - id: size-removed
    version: 2
    released: 2026-07-01
    collection: topics
    attribute: size
    drop: true
"""
    cur = build_tree(
        tmp_path / "cur",
        {"topics/_schema.yaml": removed, "pipeline/migrations.yaml": registry},
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert report.ok, render_report(report)


def test_type_change_without_definition_bump_is_undeclared_meaning_change(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    retyped = SCHEMA_V1.replace("schema_version: 1", "schema_version: 2").replace(
        "    type: number\n    default: 1\n",
        "    type: text\n    default: ''\n",
    )
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": retyped})
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_UNDECLARED_MEANING_CHANGE]
    assert "'size'" in report.findings[0].detail


def test_definition_version_regression_fails(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V2_MEANING})
    cur = build_tree(
        tmp_path / "cur",
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING.replace(
                "definition_version: 2", "definition_version: 1"
            )
        },
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert CODE_DEFINITION_VERSION_REGRESSION in codes(report)


def test_new_collection_has_no_baseline_to_diff(tmp_path):
    """A collection absent from the baseline is NEW — clauses 1-2 have nothing to
    compare, and the snapshot passes still run."""
    base = build_tree(tmp_path / "base", {})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V1})
    assert lint_tree(cur, now=NOW, baseline=baseline_from_dir(base)).ok


# -----------------------------------------------------------------------------------
# SV11 clause 4: window sanity (incl. the step-12 RV-3 carry-forwards)
# -----------------------------------------------------------------------------------


def test_future_dated_release_fails(tmp_path):
    registry = REGISTRY_COLOR_MAP.replace("released: 2026-07-01", "released: 2027-01-01")
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    report = lint_tree(root, now=NOW)
    assert CODE_FUTURE_RELEASE in codes(report)
    assert "2027-01-01" in report.findings[0].detail


def test_non_monotonic_release_dates_fail(tmp_path):
    registry = """\
steps:
  - id: step-one
    version: 1
    released: 2026-06-01
    collection: topics
    attribute: color
    prompt: first question
  - id: step-two
    version: 1
    released: 2026-05-01
    collection: topics
    attribute: color
    prompt: second question
"""
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V1, "pipeline/migrations.yaml": registry},
    )
    report = lint_tree(root, now=NOW)
    assert codes(report) == [CODE_NON_MONOTONIC]


def test_step_version_ahead_of_global_schema_fails(tmp_path):
    registry = REGISTRY_COLOR_MAP.replace("version: 2", "version: 9")
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    assert CODE_STEP_AHEAD in codes(lint_tree(root, now=NOW))


def test_premature_prune_fails_and_legal_prune_passes(tmp_path):
    def registry_with(released: str) -> str:
        return f"""\
steps:
  - id: old-step
    version: 1
    released: {released}
    collection: topics
    attribute: color
    prompt: an old question
"""

    # Pruned while still in-window (released < 1 year before NOW) → clause-4 failure.
    base = build_tree(
        tmp_path / "base-young",
        {"topics/_schema.yaml": SCHEMA_V1, "pipeline/migrations.yaml": registry_with("2026-06-01")},
    )
    cur = build_tree(tmp_path / "cur-young", {"topics/_schema.yaml": SCHEMA_V1})
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_PREMATURE_PRUNE]

    # Pruned past the window (released > 1 year before NOW) → legal (MIG-2).
    base_old = build_tree(
        tmp_path / "base-old",
        {"topics/_schema.yaml": SCHEMA_V1, "pipeline/migrations.yaml": registry_with("2024-01-01")},
    )
    cur_old = build_tree(tmp_path / "cur-old", {"topics/_schema.yaml": SCHEMA_V1})
    assert lint_tree(cur_old, now=NOW, baseline=baseline_from_dir(base_old)).ok


def test_mutated_step_violates_append_only(tmp_path):
    base = build_tree(
        tmp_path / "base",
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": REGISTRY_COLOR_MAP},
    )
    cur = build_tree(
        tmp_path / "cur",
        {
            "topics/_schema.yaml": SCHEMA_V2_MEANING,
            "pipeline/migrations.yaml": REGISTRY_COLOR_MAP.replace("blue: navy", "blue: lime"),
        },
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert CODE_STEP_MUTATED in codes(report)


# -----------------------------------------------------------------------------------
# §27.4: deterministic-map totality + composition
# -----------------------------------------------------------------------------------


def test_map_not_total_over_baseline_enum_domain_fails(tmp_path):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    partial = REGISTRY_COLOR_MAP.replace(", blue: navy", "")
    cur = build_tree(
        tmp_path / "cur",
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": partial},
    )
    report = lint_tree(cur, now=NOW, baseline=baseline_from_dir(base))
    assert codes(report) == [CODE_MAP_NOT_TOTAL]
    assert "'blue'" in report.findings[0].detail


def test_map_value_that_does_not_compose_fails(tmp_path):
    """A mapped-to value must be valid under the CURRENT schema (needs no baseline)."""
    bad = REGISTRY_COLOR_MAP.replace("blue: navy", "blue: chartreuse")
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": bad},
    )
    report = lint_tree(root, now=NOW)
    assert codes(report) == [CODE_STEP_COMPOSITION]
    assert "chartreuse" in report.findings[0].detail


def test_map_on_undeclared_attribute_fails_composition(tmp_path):
    bad = REGISTRY_COLOR_MAP.replace("attribute: color", "attribute: shade").replace(
        "map: {red: crimson, green: lime, blue: navy}", "map: {a: crimson}"
    )
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": bad},
    )
    assert codes(lint_tree(root, now=NOW)) == [CODE_STEP_COMPOSITION]


def test_rename_target_must_be_declared_and_source_removed(tmp_path):
    registry = """\
steps:
  - id: color-renamed
    version: 2
    released: 2026-07-01
    collection: topics
    attribute: color
    rename_to: shade
"""
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    report = lint_tree(root, now=NOW)
    # Both composition halves fire: `shade` undeclared AND `color` still declared.
    assert codes(report) == [CODE_STEP_COMPOSITION, CODE_STEP_COMPOSITION]


def test_drop_of_still_declared_attribute_fails_composition(tmp_path):
    registry = """\
steps:
  - id: color-dropped
    version: 2
    released: 2026-07-01
    collection: topics
    attribute: color
    drop: true
"""
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    assert codes(lint_tree(root, now=NOW)) == [CODE_STEP_COMPOSITION]


def test_edit_set_of_undeclared_attribute_fails_composition(tmp_path):
    registry = """\
steps:
  - id: object-fixup
    version: 2
    released: 2026-07-01
    collection: topics
    scope: object
    edit:
      set: {mystery: 1}
"""
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": SCHEMA_V2_MEANING, "pipeline/migrations.yaml": registry},
    )
    assert codes(lint_tree(root, now=NOW)) == [CODE_STEP_COMPOSITION]


def test_older_steps_are_not_revalidated_against_the_current_schema(tmp_path):
    """Totality/composition apply to CURRENT-release steps only: a v2 map whose values
    were valid at v2 stays green after an unrelated v3 release moved the schema on."""
    v3 = SCHEMA_V2_MEANING.replace("schema_version: 2", "schema_version: 3").replace(
        "values: [crimson, lime, navy]", "values: [crimson, lime]"
    )
    registry = REGISTRY_COLOR_MAP  # v2 map; `navy` is no longer a v3 member
    root = build_tree(
        tmp_path,
        {"topics/_schema.yaml": v3, "pipeline/migrations.yaml": registry},
    )
    assert lint_tree(root, now=NOW).ok


# -----------------------------------------------------------------------------------
# Scan scope (PA-1 mirror) + the real repo
# -----------------------------------------------------------------------------------


def test_repo_root_lints_clean_and_fixtures_are_out_of_scope():
    """The Verify-command surface: the REAL repo is green, and the tracked gadgets
    fixture collection (tests/fixtures/registries/gadgets — populated entries, one with
    a trailing stamp) is NOT scanned. Since step 14, real registry collections ARE in
    scope (the five rendering-dimension registries landed first, §5.3/§17 RI12; step 15
    adds the rest), so the proof is scope-shaped rather than count-pinned: everything
    scanned sits in a named registry root (or instance/ or workspaces/), never under
    tests/."""
    report = lint_tree(REPO_ROOT, now=NOW)
    assert report.ok, render_report(report)
    scanned = list(iter_lint_collections(REPO_ROOT))
    assert report.collections_scanned == len(scanned) >= 5  # step 14's five registries
    assert report.entries_scanned > 0  # framework default entries are real now
    gadgets = REPO_ROOT / "tests" / "fixtures" / "registries" / "gadgets"
    assert (gadgets / "_schema.yaml").is_file()  # exists, yet out of scope
    assert gadgets not in scanned
    in_scope_tops = set(REGISTRY_ROOTS) | {"instance", "workspaces"}
    for coll in scanned:
        parts = coll.relative_to(REPO_ROOT).parts
        assert "tests" not in parts  # PA-1b: fixtures can never self-flag
        assert parts[0] in in_scope_tops


def test_scope_is_registry_roots_plus_instance_and_workspaces(tmp_path):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "workspaces/acme/topics/_schema.yaml": SCHEMA_V1,
            "instance/things/_schema.yaml": SCHEMA_V1,
            # all out of scope:
            "tests/fixtures/bait/_schema.yaml": "not yaml at all: [",
            "docs/bait/_schema.yaml": "not yaml at all: [",
            "pipeline/bait/_schema.yaml": "not yaml at all: [",
            "scripts/bait/_schema.yaml": "not yaml at all: [",
            ".claude/bait/_schema.yaml": "not yaml at all: [",
            ".github/bait/_schema.yaml": "not yaml at all: [",
            # exempt template workspace (PA-1a):
            "workspaces/workspace.template/topics/_schema.yaml": "broken: [",
        },
    )
    colls = {str(c.relative_to(root)) for c in iter_lint_collections(root)}
    assert colls == {"topics", "workspaces/acme/topics", "instance/things"}
    assert lint_tree(root, now=NOW).ok


# -----------------------------------------------------------------------------------
# CLI + entrypoint script
# -----------------------------------------------------------------------------------


def test_main_reports_findings_and_exits_nonzero(tmp_path, capsys):
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/wrong-name.md": entry_text("fixture-alpha"),
        },
    )
    rc = main(["--root", str(root), "--no-baseline", "--now", "2026-07-12"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL [entry-identity-mismatch]" in out


def test_main_clean_tree_exits_zero(tmp_path, capsys):
    root = build_tree(tmp_path, {"topics/_schema.yaml": SCHEMA_V1})
    rc = main(["--root", str(root), "--now", "2026-07-12"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK: schema-lint clean." in out
    assert "baseline: none" in out  # tmp trees are not git toplevels — no auto baseline


def test_main_baseline_dir_seam(tmp_path, capsys):
    base = build_tree(tmp_path / "base", {"topics/_schema.yaml": SCHEMA_V1})
    cur = build_tree(tmp_path / "cur", {"topics/_schema.yaml": SCHEMA_V2_MEANING})
    rc = main(["--root", str(cur), "--baseline", str(base), "--now", "2026-07-12"])
    out = capsys.readouterr().out
    assert rc == 1
    assert f"FAIL [{CODE_MEANING_WITHOUT_STEP}]" in out


def test_main_usage_errors(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "--now", "not-a-date"]) == 2
    assert main(["--root", str(tmp_path), "--baseline", str(tmp_path / "absent")]) == 2
    capsys.readouterr()


def test_git_baseline_reader_on_this_repo():
    """The default-baseline plumbing, on the one git checkout the suite runs in: a
    tracked file reads back from HEAD; an absent path reads None (read-only git use)."""
    read = baseline_from_git(REPO_ROOT, "HEAD")
    text = read("pyproject.toml")
    assert text is not None and "optiquity-content-pipeline" in text
    assert read("no/such/path.yaml") is None


def test_registry_roots_are_the_fourteen_named_dimensions():
    assert len(REGISTRY_ROOTS) == 14
    assert "recipes" in REGISTRY_ROOTS and "folio-types" in REGISTRY_ROOTS


def test_schema_lint_script_delegates(tmp_path):
    """`bash scripts/schema-lint.sh --root <tree>` surfaces lint findings (the T8 shim +
    the argparse last---root-wins passthrough)."""
    root = build_tree(
        tmp_path,
        {
            "topics/_schema.yaml": SCHEMA_V1,
            "topics/wrong-name.md": entry_text("fixture-alpha"),
        },
    )
    proc = subprocess.run(
        ["bash", str(SCHEMA_LINT), "--root", str(root), "--now", "2026-07-12"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FAIL [entry-identity-mismatch]" in proc.stdout
