"""Authoring layer C5a: the new `selections/` registry root — dual-whitelist + B3 envelope proof.

C5a lands the `selections/` registry ROOT (a peer of `recipes`/`diagram-styles`) with its schema
only — it ships EMPTY (no entries; saved selections land at run in C5b/C5c). This test locks the
two invariants the root must hold from the moment it exists:

  - **Dual whitelist (the critical coupling):** `selections` is in BOTH
    `pipeline.lint.REGISTRY_ROOTS` (the source of truth the schema-lint scans) AND the hardcoded
    `REGISTRY_ROOTS` whitelist string in `scripts/check-no-content.sh` — else the GAP-4a coverage
    arm would fire `unknown-registry-root` (the guard mirror MUST move in the same commit as the
    lint mirror, or the public-boundary scan silently misses the new root).
  - **B3 envelope floor-rides:** the schema's two attributes (`base` text `""`, `variants` list
    `[]`) both floor-ride, so an envelope-only entry (id + provenance + schema_version, nothing
    set) lints clean AND loads — the property the parametrized §5.4 one-file-add probe depends on.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pipeline import lint
from pipeline.drift import iter_entry_files
from pipeline.entries import load_entry
from pipeline.layout import registry_dir
from pipeline.lint import lint_tree, render_report
from pipeline.schema import SCHEMA_FILENAME, load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SCRIPT = REPO_ROOT / "scripts" / "check-no-content.sh"

#: Injected clock (the lint library never reads ambient time; pipeline/lint.py).
NOW = date(2026, 7, 12)


def test_selections_root_in_both_whitelists() -> None:
    """The critical coupling: the new registry root is whitelisted in BOTH the lint source of
    truth and the content-guard mirror, so neither the schema-lint scan nor the GAP-4a coverage
    check can silently miss it. They must move together — this pins that they did."""
    assert "selections" in lint.REGISTRY_ROOTS

    guard_text = GUARD_SCRIPT.read_text(encoding="utf-8")
    # The hardcoded `REGISTRY_ROOTS="…"` whitelist line the GAP-4a coverage arm reads.
    roots_line = next(
        line for line in guard_text.splitlines() if line.startswith("REGISTRY_ROOTS=")
    )
    whitelisted = roots_line.split("=", 1)[1].strip().strip('"').split()
    assert "selections" in whitelisted, roots_line


def test_selections_schema_loads_at_v1_envelope_floor_rides(tmp_path: Path) -> None:
    """B3 proof: an envelope-only `selections` entry (no attribute set) lints clean AND loads —
    both attributes ride their empty floor (`base` `""`, `variants` `[]`), so §5.4 one-file-add
    holds for this root exactly as it does for every sibling. selections ships at v1 (nothing
    bumped, the chosen lint-improvement path), so version-equality holds with zero id churn."""
    coll = registry_dir(tmp_path, "selections")
    coll.mkdir(parents=True)
    (coll / SCHEMA_FILENAME).write_text(
        (registry_dir(REPO_ROOT, "selections") / SCHEMA_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    schema = load_schema(coll / SCHEMA_FILENAME)
    assert schema.schema_version == 1  # v1 — nothing bumped
    assert schema.defaults() == {"base": "", "variants": []}  # both attributes floor-ride (B3)

    entry_id = "selections-envelope-probe"
    (coll / f"{entry_id}.md").write_text(
        "---\n"
        f"id: {entry_id}\n"
        "provenance: framework\n"
        f"schema_version: {schema.schema_version}\n"
        "---\n"
        "\nEnvelope-only saved-selection probe (§5.4): every attribute rides its floor.\n",
        encoding="utf-8",
    )

    # Lints clean: the full SV11 walk accepts the envelope-only entry (no index, no code touch).
    report = lint_tree(tmp_path, now=NOW, baseline=None)
    assert report.ok, render_report(report)

    # Loads: the standard validating loader yields it; nothing is SET, so it rides the floors.
    entries = {load_entry(p, schema).id: load_entry(p, schema) for p in iter_entry_files(coll)}
    assert entry_id in entries
    assert entries[entry_id].attributes == {}  # envelope-only: consumers read floors via defaults()
