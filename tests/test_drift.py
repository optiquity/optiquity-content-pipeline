"""Tests for pipeline/drift.py — plan step 12 (design §11.5 SV7 + §11.6 MIG-6).

Covers: the drift math (one integer comparison: definition_version > entry stamp AND the
entry sets the attribute); the MIG-6 block/warn/silent table encoded and QUERYABLE (the
step-16 enforcement input); meaning-vs-wording (§11.5 — a prose-only definition edit is
SILENT by construction); the lenient config view; the SV7 update-time report and its
PA-9c named entry point `scripts/pipeline drift-report` (read-only, exit 1 on blocks).

All fixture content is obviously generic (`gadgets`/`x-thing`); every document is built
under pytest tmp_path — nothing instance-flavored is tracked.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from pipeline.drift import (
    CODE_DRIFT_BLOCK,
    CODE_OUT_OF_WINDOW,
    RESOLVE_TIME_TABLE,
    DriftError,
    DriftKind,
    Severity,
    blocking_findings,
    blocking_kinds,
    build_drift_report,
    check_entry,
    iter_collections,
    iter_entry_files,
    load_entry_lenient,
    meaning_changed_attributes,
    new_attributes_available,
    parse_entry_lenient,
    removed_attributes,
    render_drift_report,
    severity_for,
)
from pipeline.entries import EntryError, EntryIdentityError, ProvenanceError, parse_entry
from pipeline.schema import SCHEMA_FILENAME, load_schema_text

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = date(2026, 7, 12)

# A generic test collection: color redefined at v4, mood redefined at v5, size unchanged
# since v1; current global schema_version 5.
GADGETS_SCHEMA = """\
schema_version: 5
attributes:
  color:
    type:
      type: enum
      values: [red, green, blue]
    default: red
    definition: The example color token.
    definition_version: 4
  mood:
    type:
      type: enum
      values: [calm, bold]
    default: calm
    definition: The example mood token.
    definition_version: 5
  size:
    type: number
    default: 1
    definition: The example size number.
    definition_version: 1
"""


def make_schema(text: str = GADGETS_SCHEMA, collection: str = "gadgets"):
    return load_schema_text(text, collection=collection)


def entry_text(
    entry_id: str,
    stamp: int,
    attrs: str = "",
    provenance: str = "instance",
    body: str = "\nBody prose.\n",
) -> str:
    fm = f"id: {entry_id}\nprovenance: {provenance}\nschema_version: {stamp}\n"
    if attrs:
        fm += attrs.rstrip("\n") + "\n"
    return f"---\n{fm}---{body}"


def make_entry(schema, entry_id: str, stamp: int, attrs: str = "", provenance: str = "instance"):
    return parse_entry_lenient(
        entry_text(entry_id, stamp, attrs, provenance), filename_slug=entry_id, schema=schema
    )


def write_schema(root: Path, text: str = GADGETS_SCHEMA, collection: str = "gadgets") -> Path:
    d = root / collection
    d.mkdir(parents=True, exist_ok=True)
    (d / SCHEMA_FILENAME).write_text(text, encoding="utf-8")
    return d


def write_entry(
    root: Path,
    collection: str,
    entry_id: str,
    stamp: int,
    attrs: str = "",
    provenance: str = "instance",
) -> Path:
    d = root / collection
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{entry_id}.md"
    p.write_text(entry_text(entry_id, stamp, attrs, provenance), encoding="utf-8")
    return p


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------------------------------
# The MIG-6 table: encoded, queryable, exactly the design's rows (step-16 input)
# ---------------------------------------------------------------------------------------


class TestResolveTimeTable:
    def test_exactly_the_five_design_rows(self):
        assert RESOLVE_TIME_TABLE == {
            DriftKind.MEANING_CHANGE: Severity.BLOCK,
            DriftKind.REMOVED_ATTRIBUTE: Severity.BLOCK,
            DriftKind.OUT_OF_WINDOW: Severity.BLOCK,
            DriftKind.NEW_ATTRIBUTE: Severity.WARN,
            DriftKind.WORDING_ONLY: Severity.SILENT,
        }

    def test_severity_for_is_the_table(self):
        for kind in DriftKind:
            assert severity_for(kind) is RESOLVE_TIME_TABLE[kind]

    def test_blocking_kinds(self):
        assert blocking_kinds() == frozenset(
            {DriftKind.MEANING_CHANGE, DriftKind.REMOVED_ATTRIBUTE, DriftKind.OUT_OF_WINDOW}
        )

    def test_pinned_codes(self):
        # §21.7: the two pinned drift codes (full taxonomy = plan step 32).
        assert CODE_DRIFT_BLOCK == "drift-block"
        assert CODE_OUT_OF_WINDOW == "out-of-window"


# ---------------------------------------------------------------------------------------
# The §11.5 drift math
# ---------------------------------------------------------------------------------------


class TestDriftMath:
    def test_meaning_change_requires_both_operands(self):
        schema = make_schema()
        # Sets color (dv4) and mood (dv5), stamped 3 -> both drifted.
        e = make_entry(schema, "x-a", 3, "color: red\nmood: calm")
        assert meaning_changed_attributes(schema, e) == {"color": 4, "mood": 5}

    def test_not_set_means_no_meaning_drift(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 3, "size: 2")
        assert meaning_changed_attributes(schema, e) == {}

    def test_stamp_at_or_after_definition_version_is_clean(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 4, "color: red")  # dv4 == stamp 4 -> not drifted
        assert meaning_changed_attributes(schema, e) == {}
        e5 = make_entry(schema, "x-a", 5, "color: red\nmood: calm")
        assert meaning_changed_attributes(schema, e5) == {}

    def test_removed_attribute_detection(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 3, "legacy: 7\nolder: 1")
        assert removed_attributes(schema, e) == ["legacy", "older"]

    def test_new_attribute_available(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 3, "size: 2")  # color(4), mood(5) unset & newer
        assert new_attributes_available(schema, e) == {"color": 4, "mood": 5}

    def test_collection_mismatch_is_machinery_misuse(self):
        schema = make_schema()
        other = make_schema(GADGETS_SCHEMA, collection="widgets")
        e = make_entry(other, "x-a", 3)
        with pytest.raises(DriftError):
            meaning_changed_attributes(schema, e)


# ---------------------------------------------------------------------------------------
# check_entry: findings, codes, ordering of concerns
# ---------------------------------------------------------------------------------------


class _FakeWindow:
    """A stub oracle (the real one is migration.StepRegistry — tested there)."""

    def __init__(self, detail):
        self.detail = detail

    def out_of_window(self, schema, entry, *, now):
        return self.detail


class TestCheckEntry:
    def test_meaning_change_blocks_with_drift_block_code(self):
        schema = make_schema()
        # Stamp 4: mood (dv5) drifted and set; color (dv4) is exactly at the stamp and
        # size (dv1) is older — exactly ONE finding, the meaning-change block.
        e = make_entry(schema, "x-a", 4, "mood: calm\ncolor: red\nsize: 2")
        [f] = check_entry(schema, e)
        assert f.kind is DriftKind.MEANING_CHANGE
        assert f.severity is Severity.BLOCK
        assert f.code == CODE_DRIFT_BLOCK
        assert f.attribute == "mood"
        assert f.definition_version == 5
        assert f.entry_stamp == 4 and f.current_version == 5
        assert "migrate before use" in f.detail

    def test_removed_attribute_blocks_with_drift_block_code(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 5, "legacy: 7")
        [f] = check_entry(schema, e)
        assert f.kind is DriftKind.REMOVED_ATTRIBUTE
        assert f.code == CODE_DRIFT_BLOCK
        assert f.attribute == "legacy"
        assert "no longer declares" in f.detail

    def test_deterministic_and_ambiguous_meaning_changes_block_alike(self):
        # §11.5: BLOCK "on any meaning change affecting an attribute the object sets
        # (deterministic or ambiguous)" — the table has ONE row for both; nothing in the
        # finding depends on the shipped step's shape.
        schema = make_schema()
        e = make_entry(schema, "x-a", 3, "color: red\nmood: calm")
        kinds = {f.kind for f in check_entry(schema, e)}
        assert kinds == {DriftKind.MEANING_CHANGE}
        assert all(f.severity is Severity.BLOCK for f in check_entry(schema, e))

    def test_new_attribute_warns_without_pinned_code(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 3, "size: 2")
        findings = check_entry(schema, e)
        assert {f.kind for f in findings} == {DriftKind.NEW_ATTRIBUTE}
        assert all(f.severity is Severity.WARN and f.code is None for f in findings)
        assert blocking_findings(findings) == []

    def test_wording_only_change_is_silent_by_construction(self):
        # §11.5 meaning-vs-wording: same shape, but ONLY the prose definition changed
        # across the release (schema_version bumped 5->6, definition_version stays 4) —
        # the entry sets the attribute and NOTHING fires.
        reworded = GADGETS_SCHEMA.replace("schema_version: 5", "schema_version: 6").replace(
            "The example color token.", "The exemplary colour token, better worded."
        )
        schema = make_schema(reworded)
        e = make_entry(schema, "x-a", 5, "color: red\nmood: calm\nsize: 2")
        assert check_entry(schema, e) == []
        # ...and the SAME entry against a MEANING bump (dv 4->6) blocks: the pair proves
        # the math distinguishes meaning from wording by definition_version alone.
        meaning = reworded.replace("definition_version: 4", "definition_version: 6")
        schema2 = make_schema(meaning)
        assert [f.kind for f in check_entry(schema2, e)] == [DriftKind.MEANING_CHANGE]

    def test_window_oracle_injection(self):
        schema = make_schema()
        e = make_entry(schema, "x-a", 5, "size: 2")  # otherwise clean
        [f] = check_entry(schema, e, window=_FakeWindow("past the window"), now=NOW)
        assert f.kind is DriftKind.OUT_OF_WINDOW
        assert f.severity is Severity.BLOCK
        assert f.code == CODE_OUT_OF_WINDOW
        assert f.detail == "past the window"
        # A within-window oracle adds nothing.
        assert check_entry(schema, e, window=_FakeWindow(None), now=NOW) == []

    def test_window_without_clock_is_refused(self):
        # The clock is injected, never ambient: an oracle without `now` is misuse.
        schema = make_schema()
        e = make_entry(schema, "x-a", 5)
        with pytest.raises(DriftError, match="now"):
            check_entry(schema, e, window=_FakeWindow(None))


# ---------------------------------------------------------------------------------------
# The lenient config view (drift/migration INPUT loading)
# ---------------------------------------------------------------------------------------


class TestLenientView:
    def test_valid_entry_matches_strict_parse(self):
        schema = make_schema()
        text = entry_text("x-a", 5, "color: red")
        strict = parse_entry(text, filename_slug="x-a", schema=schema)
        lenient = parse_entry_lenient(text, filename_slug="x-a", schema=schema)
        assert lenient == strict

    def test_stale_invalid_payload_is_visible_not_refused(self):
        schema = make_schema()
        # `teal` is not in the CURRENT enum and `legacy` is undeclared — exactly the
        # states migration exists to fix (§11.6); the view must expose them.
        e = make_entry(schema, "x-a", 2, "color: teal\nlegacy: 7")
        assert e.attributes == {"color": "teal", "legacy": 7}
        assert e.schema_version == 2
        assert e.body == "Body prose.\n"  # body still verbatim (post-fence remainder)

    def test_envelope_discipline_is_never_relaxed(self):
        schema = make_schema()
        with pytest.raises(EntryIdentityError):
            parse_entry_lenient(entry_text("x-b", 2), filename_slug="x-a", schema=schema)
        no_provenance = "---\nid: x-a\nschema_version: 2\n---\n"
        with pytest.raises(ProvenanceError):
            parse_entry_lenient(no_provenance, filename_slug="x-a", schema=schema)
        no_frontmatter = "just prose\n"
        with pytest.raises(EntryError):
            parse_entry_lenient(no_frontmatter, filename_slug="x-a", schema=schema)

    def test_load_entry_lenient_path_rules(self, tmp_path):
        schema = make_schema()
        p = write_entry(tmp_path, "gadgets", "x-a", 2, "color: teal")
        e = load_entry_lenient(p, schema)
        assert e.attributes == {"color": "teal"} and e.path == p
        bad = tmp_path / "gadgets" / "x-b.txt"
        bad.write_text("x", encoding="utf-8")
        with pytest.raises(EntryError):
            load_entry_lenient(bad, schema)


# ---------------------------------------------------------------------------------------
# Config-tree walking
# ---------------------------------------------------------------------------------------


class TestWalking:
    def test_iter_collections_finds_config_and_prunes_stores(self, tmp_path):
        write_schema(tmp_path)  # gadgets/
        write_schema(tmp_path / "workspaces" / "acme", collection="topics")
        # Store/never-config dirs — even if a _schema.yaml is dropped inside, they are
        # pruned by name (MIG-7 structural scope on top of the SV4 rule).
        for store in ("workspaces/acme/artifacts", "instance/ops", "tests", ".hidden"):
            d = tmp_path / store
            d.mkdir(parents=True)
            (d / SCHEMA_FILENAME).write_text("schema_version: 1\nattributes: {}\n")
        found = {str(p.relative_to(tmp_path)) for p in iter_collections(tmp_path)}
        assert found == {"gadgets", "workspaces/acme/topics"}

    def test_iter_entry_files_skips_templates_and_schema(self, tmp_path):
        d = write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-a", 5)
        (d / "gadget.template.md").write_text("template scaffolding\n", encoding="utf-8")
        names = [p.name for p in iter_entry_files(d)]
        assert names == ["x-a.md"]


# ---------------------------------------------------------------------------------------
# The SV7 update-time report (§11.5) + rendering
# ---------------------------------------------------------------------------------------


class TestDriftReport:
    def _drifted_tree(self, tmp_path) -> Path:
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-old", 3, "color: red")  # meaning drift
        write_entry(tmp_path, "gadgets", "x-removed", 5, "legacy: 7")  # removed attr
        write_entry(tmp_path, "gadgets", "x-rides", 3, "size: 2")  # warns only
        write_entry(tmp_path, "gadgets", "example-fw", 5, "color: red", provenance="framework")
        return tmp_path

    def test_report_content_on_drifted_fixture(self, tmp_path):
        report = build_drift_report(self._drifted_tree(tmp_path), now=NOW)
        [coll] = report.collections
        assert coll.collection == "gadgets" and coll.schema_version == 5
        assert coll.entries_scanned == 4
        assert coll.framework_entries == 1 and coll.instance_entries == 3
        blocks = {(f.entry_id, f.kind) for f in report.blocking}
        assert blocks == {
            ("x-old", DriftKind.MEANING_CHANGE),
            ("x-removed", DriftKind.REMOVED_ATTRIBUTE),
        }
        warn_ids = {f.entry_id for f in report.warnings}
        assert "x-rides" in warn_ids
        assert report.has_blocks

    def test_report_is_read_only(self, tmp_path):
        tree = self._drifted_tree(tmp_path)
        before = snapshot(tree)
        build_drift_report(tree, now=NOW)
        assert snapshot(tree) == before

    def test_wording_only_release_reports_clean(self, tmp_path):
        # Meaning-vs-wording at report level: a release that only rewrote prose (and
        # bumped the global version) produces NO lines for an entry setting everything.
        reworded = GADGETS_SCHEMA.replace("schema_version: 5", "schema_version: 6").replace(
            "The example color token.", "The example color token, reworded for clarity."
        )
        write_schema(tmp_path, reworded)
        write_entry(tmp_path, "gadgets", "x-set", 5, "color: red\nmood: calm\nsize: 2")
        report = build_drift_report(tmp_path, now=NOW)
        assert report.blocking == [] and report.warnings == []
        rendered = render_drift_report(report)
        assert "wording-only changes are silent by design" in rendered

    def test_unloadable_entry_is_a_note_not_a_crash(self, tmp_path):
        write_schema(tmp_path)
        p = tmp_path / "gadgets" / "x-broken.md"
        p.write_text("---\nid: x-other\nprovenance: instance\nschema_version: 1\n---\n")
        report = build_drift_report(tmp_path, now=NOW)
        [coll] = report.collections
        assert coll.entries_scanned == 0
        [note] = coll.notes
        assert "x-broken" in note.path and "entry-identity-mismatch" in note.message

    def test_ahead_of_current_stamp_is_a_note(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-future", 9, "size: 2")
        report = build_drift_report(tmp_path, now=NOW)
        [coll] = report.collections
        assert any("AHEAD" in n.message for n in coll.notes)
        assert report.blocking == []

    def test_render_contains_codes_and_summary(self, tmp_path):
        report = build_drift_report(self._drifted_tree(tmp_path), now=NOW)
        rendered = render_drift_report(report)
        assert "DRIFT REPORT (update-time, SV7/MIG-6)" in rendered
        assert "[drift-block]" in rendered
        assert "WARN" in rendered
        assert "scripts/migrate.sh" in rendered  # remediation points at the tool (§21.7)
        assert "2 block" in rendered


# ---------------------------------------------------------------------------------------
# PA-9c: the named entry point `scripts/pipeline drift-report` (via `python -m pipeline`)
# ---------------------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pipeline", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestDriftReportCLI:
    def test_drifted_tree_exits_1_with_report(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-old", 3, "color: red")
        proc = _run_cli("drift-report", "--root", str(tmp_path), "--now", "2026-07-12")
        assert proc.returncode == 1
        assert "DRIFT REPORT" in proc.stdout
        assert "[drift-block]" in proc.stdout
        assert "as of 2026-07-12" in proc.stdout  # the injected clock, not today's

    def test_clean_tree_exits_0(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-new", 5, "color: red")
        proc = _run_cli("drift-report", "--root", str(tmp_path), "--now", "2026-07-12")
        assert proc.returncode == 0
        assert "0 block" in proc.stdout

    def test_out_of_window_via_registry_oracle(self, tmp_path):
        write_schema(tmp_path)
        write_entry(tmp_path, "gadgets", "x-ancient", 3, "color: red")
        registry = tmp_path / "registry.yaml"
        registry.write_text(
            "steps:\n"
            "  - id: 4-gadgets-color-map\n"
            "    version: 4\n"
            "    released: 2025-01-01\n"  # far past the 1-year window at --now
            "    collection: gadgets\n"
            "    attribute: color\n"
            "    map:\n"
            "      red: blue\n",
            encoding="utf-8",
        )
        proc = _run_cli(
            "drift-report",
            "--root",
            str(tmp_path),
            "--registry",
            str(registry),
            "--now",
            "2026-07-12",
        )
        assert proc.returncode == 1
        assert "[out-of-window]" in proc.stdout
        assert "past the 1-year support window" in proc.stdout

    def test_bad_now_and_unknown_command_are_usage_errors(self, tmp_path):
        proc = _run_cli("drift-report", "--root", str(tmp_path), "--now", "yesterday")
        assert proc.returncode == 2
        proc = _run_cli("no-such-command")
        assert proc.returncode == 2
        assert "unknown command" in proc.stderr

    def test_usage_names_drift_report(self):
        proc = _run_cli("--help")
        assert proc.returncode == 0
        assert "drift-report" in proc.stdout
        # migrate is NOT a `pipeline` subcommand (maintenance verb, §11.6/§21.9).
        assert "scripts/migrate.sh" in proc.stdout
