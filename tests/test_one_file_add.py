"""PA-13: THE permanent one-file-add acceptance test for the matrix invariant (§5.4).

Design authority: `docs/design.md` §5.4 — "Adding a value to any axis (or to any
registry: content-kind, render target, folio type, recipe) is exactly: create one file
in the right directory, conforming to the co-located schema. Nothing else changes — no
index to update, no code to touch, no second edit. A new entry participates
immediately … If any addition requires a second edit, that is a defect to fix in the
framework." §5.4 names this THE acceptance test, so this file is PERMANENT: it must
catch regressions forever, not once (plan step 15, PA-13).

Parameterized over EVERY registry — the nine axes (topics, personas, formats, voices,
goals, platforms, languages, output-types, presentations) plus content-kinds, sources,
render-targets, recipes, folio-types — via the `REGISTRY_ROOTS` constant itself
(pipeline/lint.py, the PA-1 scope boundary), so a future registry root joins this test
automatically and `test_registry_inventory_is_the_matrix` fails loudly if the
enumeration ever drifts from §5.4's.

Mechanics (REC-3 pattern): each test copies the lint scan scope to a scratch tree and
drops files THERE — the real repo is never written. Positive: one conforming file →
discovered by the schema-lint walk AND loadable/selectable via the same
`iter_entry_files`/`load_entry` machinery every consumer wires (§11.7), with zero
second edits (proven by a full-tree file snapshot). Negative: a NONCONFORMING file
fails lint loudly with its typed code (§10 Q15 default-deny; §11.1 B4 entry-identity;
§11.3 SV3 closed schemas).

This file also hosts the step-14 RV-3 permanent hardening (assigned to step 15 by
state.md): pin-bundle EQUALITY across the 7 carriers — the render-targets schema
defaults + every render-target entry's declared pins (RI13 pins ONE toolchain, so
equality is the invariant; a re-pin must touch every carrier or fail here).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

from pipeline.drift import iter_entry_files
from pipeline.entries import load_entry
from pipeline.lint import REGISTRY_ROOTS, lint_tree, render_report
from pipeline.migration import MIGRATION_REGISTRY_RELPATH
from pipeline.schema import SCHEMA_FILENAME, load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Injected clock (the lint library never reads ambient time; pipeline/lint.py).
NOW = date(2026, 7, 12)

#: §7.4 slug for the dropped probe entry (never shipped; exists only in scratch trees).
PROBE_ID = "one-file-add-probe"

#: §5.4's own enumeration: five content + four rendering axes (§5.1), plus the named
#: non-dimension registries. `test_registry_inventory_is_the_matrix` pins REGISTRY_ROOTS
#: to exactly this set so the parameterization can never silently narrow.
CONTENT_AXES = ("topics", "personas", "formats", "voices", "goals")
RENDERING_AXES = ("platforms", "languages", "output-types", "presentations")
OTHER_REGISTRIES = (
    "content-kinds",
    "sources",
    "render-targets",
    "recipes",
    "folio-types",
    "lexicons",  # DR-2 class-(ii) house-style registry (non-axis); deferral discharged 2026-07-29
    "diagram-styles",  # mixed-media increment C: the referenced diagram-style registry
)


def copy_scan_scope(dst: Path) -> None:
    """Copy the schema-lint scan scope (registry roots + the migration registry when it
    exists) into `dst`. Tests write probes into the COPY only — the repo is read-only
    toward this suite."""
    for name in REGISTRY_ROOTS:
        src = REPO_ROOT / name
        if src.is_dir():
            shutil.copytree(src, dst / name)
    registry = REPO_ROOT / MIGRATION_REGISTRY_RELPATH
    if registry.is_file():
        (dst / MIGRATION_REGISTRY_RELPATH).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(registry, dst / MIGRATION_REGISTRY_RELPATH)


def snapshot(root: Path) -> set[str]:
    """Every file under `root`, relative — the zero-second-edits witness."""
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def probe_text(schema_version: int, extra_frontmatter: str = "", entry_id: str = PROBE_ID) -> str:
    """A minimal CONFORMING entry: envelope only (§11.1 B4 id · §10 provenance · §11.2
    stamp) — every attribute rides the schema-default floor (§12.2 L0), which is itself
    part of the §5.4 guarantee: no attribute is required to participate."""
    return (
        "---\n"
        f"id: {entry_id}\n"
        "provenance: framework\n"
        f"schema_version: {schema_version}\n"
        f"{extra_frontmatter}"
        "---\n"
        "\n"
        "One-file-add probe entry (design §5.4): envelope-only; every attribute rides\n"
        "the schema-default floor (§12.2 L0).\n"
    )


def loaded_entry_ids(collection_dir: Path) -> set[str]:
    """The 'discovered/selectable' surface: the ids the standard registry machinery
    (co-located schema + entry walk + validating loader, §11.7) yields for a collection."""
    schema = load_schema(collection_dir / SCHEMA_FILENAME)
    return {load_entry(p, schema).id for p in iter_entry_files(collection_dir)}


# -------------------------------------------------------------------------------------
# The §5.4 enumeration + SV10 uniform coverage (the parameterization is never vacuous)
# -------------------------------------------------------------------------------------


def test_registry_inventory_is_the_matrix():
    """REGISTRY_ROOTS == the nine axes + the §5.4-named registries, exactly. If a
    registry is ever added/renamed, this fails and the new root provably joins the
    parameterized tests below (they iterate the same constant)."""
    assert set(REGISTRY_ROOTS) == set(CONTENT_AXES + RENDERING_AXES + OTHER_REGISTRIES)
    assert len(CONTENT_AXES + RENDERING_AXES) == 9  # §5.4: "The matrix is nine axes"


@pytest.mark.parametrize("root_name", REGISTRY_ROOTS)
def test_every_registry_exists_with_colocated_schema(root_name: str):
    """SV10 uniform coverage (§11.7): every named registry root exists in the repo and
    carries its co-located `_schema.yaml` (SV4) — one identical mechanism, no special
    cases. (Also guarantees the drop-a-file tests below exercise every registry.)"""
    coll = REPO_ROOT / root_name
    assert coll.is_dir(), f"registry root {root_name}/ missing (§5.4 one-file-add surface)"
    assert (coll / SCHEMA_FILENAME).is_file(), f"{root_name}/{SCHEMA_FILENAME} missing (SV4)"


# -------------------------------------------------------------------------------------
# THE acceptance test (§5.4): drop one conforming file → selectable, zero second edits
# -------------------------------------------------------------------------------------


@pytest.mark.parametrize("root_name", REGISTRY_ROOTS)
def test_one_file_add(root_name: str, tmp_path: Path):
    copy_scan_scope(tmp_path)
    coll = tmp_path / root_name

    before = lint_tree(tmp_path, now=NOW, baseline=None)
    assert before.ok, render_report(before)
    assert PROBE_ID not in loaded_entry_ids(coll)
    files_before = snapshot(tmp_path)

    # THE act under test (§5.4): create ONE file in the right directory, conforming to
    # the co-located schema. Nothing else.
    schema = load_schema(coll / SCHEMA_FILENAME)
    probe = coll / f"{PROBE_ID}.md"
    probe.write_text(probe_text(schema.schema_version), encoding="utf-8")

    # Discovered: the full SV11 lint walks it and stays clean — no index, no code touch.
    after = lint_tree(tmp_path, now=NOW, baseline=None)
    assert after.ok, render_report(after)
    assert after.entries_scanned == before.entries_scanned + 1
    assert after.collections_scanned == before.collections_scanned

    # Selectable: the standard registry machinery yields it, validated, immediately.
    assert PROBE_ID in loaded_entry_ids(coll)

    # ZERO second edits (§5.4: "no index to update, no code to touch, no second edit"):
    # the probe file is the ONLY change anywhere in the scan scope.
    assert snapshot(tmp_path) - files_before == {str(probe.relative_to(tmp_path))}


# -------------------------------------------------------------------------------------
# The negative (PA-13): a NONCONFORMING file fails lint, loudly and typed
# -------------------------------------------------------------------------------------

#: (case label, frontmatter mutator, expected typed finding code). Each case is
#: nonconforming for EVERY collection — schemas are closed (SV3), the envelope is
#: universal (§11.1/§10/§11.2) — so the parameterization stays registry-generic.
NONCONFORMING_CASES = [
    (
        "identity-mismatch",  # §11.1 B4: filename slug != frontmatter id (loud duplication)
        lambda v: probe_text(v, entry_id="some-other-id"),
        "entry-identity-mismatch",
    ),
    (
        "undeclared-attribute",  # §11.3 SV3: closed schemas reject undeclared payload
        lambda v: probe_text(v, extra_frontmatter="smuggled_attribute: 1\n"),
        "undeclared-attribute",
    ),
    (
        "missing-provenance",  # §10 Q15 rule 4: default-deny
        lambda v: probe_text(v).replace("provenance: framework\n", ""),
        "missing-or-ambiguous-provenance",
    ),
]


@pytest.mark.parametrize("root_name", REGISTRY_ROOTS)
@pytest.mark.parametrize(
    ("case", "make_text", "expected_code"),
    NONCONFORMING_CASES,
    ids=[c[0] for c in NONCONFORMING_CASES],
)
def test_nonconforming_file_fails_lint(
    root_name: str, case: str, make_text, expected_code: str, tmp_path: Path
):
    copy_scan_scope(tmp_path)
    coll = tmp_path / root_name
    schema = load_schema(coll / SCHEMA_FILENAME)

    probe = coll / f"{PROBE_ID}.md"
    probe.write_text(make_text(schema.schema_version), encoding="utf-8")

    report = lint_tree(tmp_path, now=NOW, baseline=None)
    assert not report.ok, f"{root_name}/{case}: a nonconforming file must fail lint (§11.7)"
    findings = [f for f in report.findings if f.path == f"{root_name}/{PROBE_ID}.md"]
    assert [f.code for f in findings] == [expected_code], render_report(report)


# -------------------------------------------------------------------------------------
# Step-14 RV-3 hardening (assigned to step 15): pin-bundle equality across the carriers
# -------------------------------------------------------------------------------------

#: The RI13 pin bundle: pinned by gate step 3 / step-06 sheet item 3, declared on every
#: render-target entry (RI12) AND mirrored as the render-targets schema defaults so the
#: L0 floor is never a stale pin (step-14 adjudication d).
PIN_ATTRIBUTES = ("pandoc_version", "pandoc_api_version", "reader")

RENDER_TARGETS_DIR = REPO_ROOT / "render-targets"
RENDER_TARGET_ENTRY_PATHS = sorted(iter_entry_files(RENDER_TARGETS_DIR))


def test_render_target_carriers_are_all_present():
    """The seven carriers of record (step-14 RV-3): the schema default + six shipped
    render-target entries. A new entry joins the equality test below automatically."""
    assert len(RENDER_TARGET_ENTRY_PATHS) >= 6
    schema = load_schema(RENDER_TARGETS_DIR / SCHEMA_FILENAME)
    assert set(PIN_ATTRIBUTES) <= set(schema.attributes)


@pytest.mark.parametrize(
    "entry_path", RENDER_TARGET_ENTRY_PATHS, ids=[p.stem for p in RENDER_TARGET_ENTRY_PATHS]
)
def test_render_target_pin_bundle_equality(entry_path: Path):
    """RI13 pins ONE toolchain, so equality is the invariant: every render-target entry
    DECLARES the pins explicitly (RI12) and each declared value equals the schema
    default byte-for-byte. A re-pin that misses any carrier fails here (RV-3)."""
    schema = load_schema(RENDER_TARGETS_DIR / SCHEMA_FILENAME)
    entry = load_entry(entry_path, schema)
    for attr in PIN_ATTRIBUTES:
        assert attr in entry.attributes, (
            f"{entry.id}: pin {attr!r} must be DECLARED on the entry (RI12), not floor-ridden"
        )
        assert entry.attributes[attr] == schema.attributes[attr].default, (
            f"{entry.id}: pin {attr!r} diverges from the schema-default carrier "
            f"({entry.attributes[attr]!r} != {schema.attributes[attr].default!r}) — RI13 "
            "pins one toolchain; a re-pin must move all carriers together (step-14 RV-3)"
        )
