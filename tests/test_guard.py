"""Tests for scripts/check-no-content.sh — plan step 13 (the PA-1 public-boundary rework).

Covers: the REC-3 test seam (`--root DIR --mode all` over copied fixture trees — no nested
git repo needed, CI green with the fixtures tracked); one negative fixture per leak class
(six classes, each firing its NAMED finding in isolation); the template exemptions BY NAME
(PA-1a) — SCOPED per class after the step-13 review: the `*.template.*` exemption applies
only in a registry root and to direct children of instance/, never under instance/ops/,
nested instance/ paths, or users/ (RV-1), an explicit `provenance: instance` line
leaks even under a template name (RV-2), and `--mode all` scans symlinks (RV-4); the
tracked-mode default on the real repo (which is simultaneously the PA-1b proof: the
violating fixtures ARE tracked under tests/fixtures/guard/ and do not self-flag, because
tests/ is structurally outside the scan scope); and the ordering invariant for step 14 —
a populated `provenance: framework` registry entry, which the pre-step-13 guard rejected
outright, now passes.

All violation-shaped content lives in tests/fixtures/guard/ and is obviously synthetic
(`fixture-*` / `x-fixture-*`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "check-no-content.sh"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "guard"

#: The six PA-1 leak classes, the four RV-1/RV-2 template-basename probes, the DR-1
#: async-`jobs/` record (a second workspace-content instance), and the [W8] templates/ scan
#: arm (a client `x-*` blueprint smuggled under templates/): (fixture tree, expected LEAK
#: label, offending path).
LEAK_CASES = [
    ("missing-provenance", "LEAK[missing-provenance]", "topics/fixture-missing-provenance.md"),
    ("provenance-instance", "LEAK[provenance-instance]", "personas/fixture-instance-tagged.md"),
    ("x-file", "LEAK[x-file]", "formats/x-fixture-format.md"),
    ("instance-defaults", "LEAK[instance-defaults]", "instance/defaults.yaml"),
    ("instance-ops", "LEAK[instance-ops]", "instance/ops/telemetry.jsonl"),
    (
        "workspace-content",
        "LEAK[workspace-content]",
        "users/acme/workspaces/proj/defaults.yaml",
    ),
    # DR-1 Commit 2: a tracked async job record under a client workspace is client data —
    # caught by the SAME workspace-content class (the path names the user/client; no exemption).
    (
        "workspace-jobs",
        "LEAK[workspace-content]",
        "users/acme/workspaces/proj/jobs/r-0123456789abcdef",
    ),
    # [W8] a client `x-*` blueprint smuggled under templates/ (outside templates/workspace/) is
    # caught by the templates/ scan arm — templates/ is framework mechanism, not a hiding place.
    (
        "templates-x-file",
        "LEAK[x-file]",
        "templates/x-fixture-blueprint.md",
    ),
    # BLOCKER close: the blueprint subtree is NOT exempt wholesale — an x-* file nested DEEP
    # inside templates/workspace/ still LEAKS (the whole subtree flows through the [W8] arm).
    (
        "templates-workspace-x-file",
        "LEAK[x-file]",
        "templates/workspace/sub/x-client.md",
    ),
    # RV-1: a *.template.* basename must NOT defeat the structural leak classes.
    (
        "template-name-workspace",
        "LEAK[workspace-content]",
        "users/acme/workspaces/proj/secret.template.md",
    ),
    (
        "template-name-instance-ops",
        "LEAK[instance-ops]",
        "instance/ops/telemetry.template.jsonl",
    ),
    ("template-name-x-file", "LEAK[x-file]", "topics/x-dir/notes.template.md"),
    # RV-2: an explicit instance tag leaks even under a template name.
    (
        "template-name-provenance-instance",
        "LEAK[provenance-instance]",
        "topics/fixture-instance-tagged.template.md",
    ),
    # RV-1 ORDERING LOCK (B-2): an `x-*` EXTENSION registry is registry-shaped and carries a
    # co-located `_schema.yaml`; the `x-*` PATH check must fire BEFORE the depth-agnostic
    # `_schema.yaml` basename exemption, else the reserved instance namespace ships UNFLAGGED
    # (design §11.4 SV5). Fires exactly one leak (x-file) — depth-2, so GAP-4a's `*/*/*` skips it.
    (
        "x-schema-registry",
        "LEAK[x-file]",
        "topics/x-acme/_schema.yaml",
    ),
]


def run_guard(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD), *args], capture_output=True, text=True, check=False
    )


def guard_on_fixture(tmp_path: Path, name: str) -> subprocess.CompletedProcess[str]:
    """The REC-3 seam: copy the fixture tree out of tests/ and scan the COPY with
    --mode all (fixture trees are not git checkouts)."""
    root = tmp_path / name
    shutil.copytree(FIXTURES / name, root)
    return run_guard("--root", str(root), "--mode", "all")


# -----------------------------------------------------------------------------------
# The leak classes — each fixture fires exactly its own named finding
# -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("fixture", "label", "path"), LEAK_CASES)
def test_leak_class_fires_named_finding(tmp_path, fixture, label, path):
    proc = guard_on_fixture(tmp_path, fixture)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert label in proc.stdout
    assert path in proc.stdout


@pytest.mark.parametrize(("fixture", "label", "path"), LEAK_CASES)
def test_leak_fixtures_fire_in_isolation(tmp_path, fixture, label, path):
    """One hole per fixture (PA-1): exactly ONE leak line, and it is the expected class."""
    proc = guard_on_fixture(tmp_path, fixture)
    leaks = [line for line in proc.stdout.splitlines() if line.startswith("LEAK[")]
    assert len(leaks) == 1, proc.stdout
    assert leaks[0].startswith(label)


# -----------------------------------------------------------------------------------
# The positive tree: the ratified §10 model (and the step-13→14 ordering invariant)
# -----------------------------------------------------------------------------------


def test_clean_framework_tree_passes(tmp_path):
    """A populated `provenance: framework` entry + every exempt surface → green."""
    proc = guard_on_fixture(tmp_path, "clean-framework")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout


def test_clean_fixture_is_the_old_guard_failure_shape():
    """Meta-assertion for the ordering invariant: the clean tree really does contain a
    POPULATED registry entry (a non-template .md in a registry root) — exactly what the
    pre-step-13 guard rejected. The new guard passing it (test above) is the proof that
    step 14's framework defaults will not break CI."""
    entry = FIXTURES / "clean-framework" / "topics" / "fixture-framework-topic.md"
    assert entry.is_file()
    assert ".template." not in entry.name
    assert "provenance: framework" in entry.read_text(encoding="utf-8")


def test_template_exemption_is_by_name(tmp_path):
    """PA-1a: `*.template.*` files carry NO provenance and stay green in a registry
    root; the same file without the template name is default-denied. (This is also the
    RV-2 green counterpart: a provenance-FREE template never leaks.)"""
    root = tmp_path / "templates"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "shape.template.md").write_text(
        "# synthetic template - no provenance line by design\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout

    (root / "topics" / "shape.md").write_text(
        "# synthetic non-template - no provenance line\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[missing-provenance] topics/shape.md" in proc.stdout


def test_template_name_does_not_hide_explicit_instance_tag(tmp_path):
    """RV-2: the registry-root template exemption skips only the missing-provenance
    default-deny — an EXPLICIT `provenance: instance` line still leaks (shipped
    templates carry no provenance frontmatter at all, so this cannot false-positive)."""
    root = tmp_path / "rv2"
    (root / "topics").mkdir(parents=True)
    tagged = root / "topics" / "evil.template.md"
    tagged.write_text(
        "---\nprovenance: instance\n---\n# synthetic instance-tagged template\n",
        encoding="utf-8",
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[provenance-instance] topics/evil.template.md" in proc.stdout

    tagged.write_text("# synthetic provenance-free template\n", encoding="utf-8")
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout


def test_instance_template_exemption_is_direct_children_only(tmp_path):
    """RV-1: the instance/ template allowlist covers DIRECT children only (the shipped
    instance/profile.template.md + instance/defaults.template.yaml shapes); a nested
    template-named file under instance/ leaks regardless of its name."""
    root = tmp_path / "instance-scope"
    (root / "instance" / "notes").mkdir(parents=True)
    (root / "instance" / "profile.template.md").write_text(
        "# synthetic shipped-template shape - no provenance by design\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout

    (root / "instance" / "notes" / "draft.template.md").write_text(
        "# synthetic nested instance file - template name must not exempt it\n",
        encoding="utf-8",
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[instance-file] instance/notes/draft.template.md" in proc.stdout


def test_workspace_blueprint_is_scanned_not_exempt_wholesale(tmp_path):
    """BLOCKER close (§23 re-home): the framework blueprint at templates/workspace/ is NOT
    exempt wholesale — its whole subtree flows through the [W8] templates/* arm. GENERIC
    framework files (no instance signal) PASS, and a co-located registry `_schema.yaml` is
    framework mechanism; but an x-* file or a `provenance: instance` file nested DEEP inside
    the blueprint still LEAKS (the subtree is no longer a blind spot)."""
    root = tmp_path / "exempt"
    (root / "templates" / "workspace" / "topics").mkdir(parents=True)
    (root / "templates" / "workspace" / "topics" / "note.md").write_text(
        "# synthetic workspace-blueprint content\n", encoding="utf-8"
    )
    (root / "recipes").mkdir(parents=True)
    (root / "recipes" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout

    # An x-* file nested DEEP inside the blueprint LEAKS (no wholesale exemption).
    (root / "templates" / "workspace" / "sub").mkdir(parents=True)
    (root / "templates" / "workspace" / "sub" / "x-client.md").write_text(
        "# synthetic client blueprint - never real\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout
    assert "LEAK[x-file] templates/workspace/sub/x-client.md" in proc.stdout
    (root / "templates" / "workspace" / "sub" / "x-client.md").unlink()

    # A `provenance: instance` file directly under the blueprint LEAKS too.
    (root / "templates" / "workspace" / "evil.md").write_text(
        "---\nprovenance: instance\n---\n# synthetic instance-tagged blueprint\n",
        encoding="utf-8",
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout
    assert "LEAK[provenance-instance] templates/workspace/evil.md" in proc.stdout


def test_templates_framework_files_pass_and_instance_content_leaks(tmp_path):
    """[W8]: templates/ is a SCANNED framework surface (owner-agnostic blueprints). The
    templates/workspace/ blueprint files PASS, and a generic framework template directly
    under templates/ PASSES — but an explicit `provenance: instance` line under templates/
    LEAKS (an x-* path under templates/ is the fixture-driven LEAK[x-file] case). Without
    the scan arm, templates/ would be an UNSCANNED client-content hiding place."""
    root = tmp_path / "templates-arm"
    # The re-homed blueprint (scanned by the [W8] arm; its generic files pass) + a generic
    # framework template alongside it.
    (root / "templates" / "workspace" / "topics").mkdir(parents=True)
    (root / "templates" / "workspace" / "defaults.yaml").write_text(
        "# synthetic blueprint defaults - all comments\n", encoding="utf-8"
    )
    (root / "templates" / "shape.template.md").write_text(
        "# synthetic framework template - no provenance by design\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout
    assert "OK:" in proc.stdout

    # An explicit instance tag under templates/ (outside the blueprint) LEAKS.
    tagged = root / "templates" / "evil.template.md"
    tagged.write_text(
        "---\nprovenance: instance\n---\n# synthetic instance-tagged template\n",
        encoding="utf-8",
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout
    assert "LEAK[provenance-instance] templates/evil.template.md" in proc.stdout


def test_instance_profile_md_is_a_leak(tmp_path):
    """The original rule-4 case survives the rework: tracked instance/profile.md leaks."""
    root = tmp_path / "profile"
    (root / "instance").mkdir(parents=True)
    (root / "instance" / "profile.md").write_text(
        "# synthetic populated profile - never real\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[instance-file] instance/profile.md" in proc.stdout


# -----------------------------------------------------------------------------------
# Scan scope (PA-1b) + the tracked default on the real repo
# -----------------------------------------------------------------------------------


def test_current_repo_passes_in_default_tracked_mode():
    """The repo-root run (CI's exact invocation). This is ALSO the PA-1b proof: the
    violating fixture trees are tracked under tests/fixtures/guard/ right now, and none
    self-flag — tests/ is structurally outside the scan scope."""
    proc = run_guard()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout
    assert "LEAK[" not in proc.stdout


def test_out_of_scope_directories_never_scanned(tmp_path):
    """Violation-shaped files under tests/ docs/ pipeline/ scripts/ .claude/ .github/
    are invisible to the guard even in --mode all."""
    root = tmp_path / "scope"
    for d in ("tests/fixtures", "docs", "pipeline", "scripts", ".claude", ".github"):
        (root / d).mkdir(parents=True)
        (root / d / "x-fixture-bait.md").write_text(
            "---\nprovenance: instance\n---\nsynthetic bait - must never be scanned\n",
            encoding="utf-8",
        )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout


def test_all_mode_scans_untracked_files(tmp_path):
    """--mode all sees plain files (the seam property REC-3 relies on): the fixture-tree
    copies are untracked, yet every leak test above fired — assert it directly too."""
    root = tmp_path / "untracked"
    (root / "users" / "acme" / "workspaces" / "proj").mkdir(parents=True)
    (root / "users" / "acme" / "workspaces" / "proj" / "note.md").write_text(
        "# synthetic client note - never real\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[workspace-content]" in proc.stdout


def test_public_clone_ignore_is_per_clone_not_shipped_in_gitignore(tmp_path):
    """The ignore for client content is PER-CLONE (`.git/info/exclude`), never the tracked
    `.gitignore` — because `.gitignore` ships downstream (rule 5) and a PRIVATE instance must
    VERSION that content (`docs/operating-model.md`, "Your content is tracked"). Shipping the
    pattern silently defeated quickstart.md §B: the instance it told you to build left client
    content untracked, which is the durability problem §B exists to solve.

    Both halves are asserted here because each alone is a plausible-looking regression: putting
    the pattern back in `.gitignore` re-breaks every private instance, and dropping the script
    leaves a public clone with only the CI guard."""
    # (a) the tracked file must NOT carry it — this is the half that ships downstream.
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "\nusers/*/workspaces/" not in gitignore
    assert "\nusers/*/zones/" not in gitignore

    # (b) the per-clone script must still produce the ignore, in a throwaway repo.
    repo = tmp_path / "clone"
    (repo / "users" / "acme" / "zones" / "default" / "workspaces" / "proj").mkdir(parents=True)
    topic = repo / "users/acme/zones/default/workspaces/proj/topic.md"
    topic.write_text("synthetic - never real client data\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)

    rel = "users/acme/zones/default/workspaces/proj/topic.md"
    before = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel])
    assert before.returncode != 0, "content must be TRACKED before the script runs (instance mode)"

    script = REPO_ROOT / "scripts" / "protect-public-clone.sh"
    subprocess.run(["bash", str(script), str(repo)], check=True, capture_output=True)
    after = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", rel])
    assert after.returncode == 0, "content must be IGNORED after the script runs (public mode)"

    # idempotent: a second run must not duplicate the block or change the outcome.
    subprocess.run(["bash", str(script), str(repo)], check=True, capture_output=True)
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert exclude.count("optiquity public-clone client-content ignore") == 1


def test_workspace_jobs_data_leak_is_flagged(tmp_path):
    """DR-1 Commit 2 — IF a job record under a client workspace were ever force-tracked, the
    guard's workspace-content class flags it. This is the enforcement half and it holds in EVERY
    clone, public or private, regardless of what any ignore file says (CLAUDE.md rules 2/4)."""
    # (2) the guard half: a planted job record under a client workspace is caught by PATH.
    root = tmp_path / "jobs-leak"
    (root / "users" / "acme" / "workspaces" / "proj" / "jobs").mkdir(parents=True)
    (root / "users" / "acme" / "workspaces" / "proj" / "jobs" / "r-0123456789abcdef").write_text(
        "synthetic job record - never real client data\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout
    assert (
        "LEAK[workspace-content] users/acme/workspaces/proj/jobs/r-0123456789abcdef"
        in proc.stdout
    )


def test_all_mode_scans_symlinks(tmp_path):
    """RV-4: --mode all must not silently skip symlinks. A registry-root symlink to an
    outside file default-denies like any other file — parity with tracked mode, where
    `git ls-files` lists the symlink and grep follows it."""
    root = tmp_path / "symlinks"
    (root / "topics").mkdir(parents=True)
    outside = tmp_path / "outside-secret.md"
    outside.write_text(
        "# synthetic outside content - no provenance line\n", encoding="utf-8"
    )
    (root / "topics" / "link.md").symlink_to(outside)
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1
    assert "LEAK[missing-provenance] topics/link.md" in proc.stdout


# -----------------------------------------------------------------------------------
# GAP-4a: unknown-registry-root coverage check (docs/known-issues.md GAP-4)
# -----------------------------------------------------------------------------------


def test_unwhitelisted_registry_root_fails_loudly(tmp_path):
    """GAP-4a: a brand-new top-level registry root (registry SHAPE = a co-located
    `_schema.yaml`, the SV4 marker) that is NOT in REGISTRY_ROOTS must FAIL the guard
    instead of passing UNSCANNED. This is exactly the leak surface DR-2's `lexicons/` root
    created BEFORE this commit whitelisted it (see the lexicons-coverage tests below) — the
    check is what forced the conscious REGISTRY_ROOTS line. It must still protect the NEXT
    unknown root: here a stand-in `glossaries/`, whose corporate entry would otherwise
    escape the content scan."""
    root = tmp_path / "new-root"
    (root / "glossaries").mkdir(parents=True)
    (root / "glossaries" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    # An entry with NO provenance + client-looking content: proof it escapes the content
    # scan (glossaries/ is outside $SCOPES, so the file loop never sees it) — only the
    # structural coverage check catches the dir.
    (root / "glossaries" / "acme-house-glossary.md").write_text(
        "# synthetic corporate glossary - never real\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[unknown-registry-root] glossaries" in proc.stdout
    # The message must name the dir AND instruct the maintainer to whitelist it.
    assert "REGISTRY_ROOTS" in proc.stdout
    # It is the ONLY finding — the un-scanned entry file itself never fires a content leak
    # (that is the whole GAP-4a hazard); the structural check is what makes it non-silent.
    leaks = [line for line in proc.stdout.splitlines() if line.startswith("LEAK[")]
    assert len(leaks) == 1, proc.stdout


# -----------------------------------------------------------------------------------
# DR-2 C1: the `lexicons/` root is whitelisted → scanned (the coverage counterpart)
# -----------------------------------------------------------------------------------


def test_lexicons_root_is_now_scanned(tmp_path):
    """DR-2 C1 added `lexicons` to REGISTRY_ROOTS, so the guard now SCANS it (SCOPES =
    REGISTRY_ROOTS + instance + workspaces). A planted instance-namespaced `x-*` lexicon
    (a client house lexicon) is caught by PATH — proof the root is INSIDE the content scan,
    not merely covered by the structural check; and the unknown-root check must NOT fire for
    a now-whitelisted root."""
    root = tmp_path / "lex-scanned"
    (root / "lexicons").mkdir(parents=True)
    (root / "lexicons" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "lexicons" / "x-acme-house.md").write_text(
        "# synthetic client lexicon - never real\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[x-file] lexicons/x-acme-house.md" in proc.stdout
    assert "unknown-registry-root" not in proc.stdout


def test_lexicons_non_framework_entry_is_default_denied(tmp_path):
    """A non-framework lexicon entry (no `provenance: framework`) in the now-scanned
    `lexicons/` root is default-denied by the content scan — the same missing-provenance
    class every registry root gets, now that the whitelist edit brought lexicons into
    scope."""
    root = tmp_path / "lex-deny"
    (root / "lexicons").mkdir(parents=True)
    (root / "lexicons" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "lexicons" / "house.md").write_text(
        "# synthetic lexicon with no provenance line\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[missing-provenance] lexicons/house.md" in proc.stdout


def test_lexicons_framework_entry_passes(tmp_path):
    """The shipped shape: a co-located `_schema.yaml` (exempt, framework mechanism) plus a
    `provenance: framework` lexicon entry stays green — mirrors the real
    `lexicons/house-standard.md` DR-2 C1 ships."""
    root = tmp_path / "lex-ok"
    (root / "lexicons").mkdir(parents=True)
    (root / "lexicons" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "lexicons" / "house-standard.md").write_text(
        "---\nprovenance: framework\n---\n# synthetic framework lexicon\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout
    assert "LEAK[" not in proc.stdout


def test_whitelisted_registry_root_with_schema_and_entry_passes(tmp_path):
    """Regression: a registry root that IS whitelisted scans normally — a co-located
    `_schema.yaml` (exempt, framework mechanism) plus a populated `provenance: framework`
    entry stays green. Proves the GAP-4a check does not disturb known roots, and mirrors
    what a future `lexicons/` looks like ONCE DR-2 adds it to REGISTRY_ROOTS."""
    root = tmp_path / "known-root"
    (root / "recipes").mkdir(parents=True)
    (root / "recipes" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "recipes" / "example.md").write_text(
        "---\nprovenance: framework\n---\n# synthetic framework recipe\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout
    assert "LEAK[" not in proc.stdout


def test_nested_schema_manifest_is_not_a_top_level_registry_root(tmp_path):
    """The coverage check keys on TOP-LEVEL registry shape only: a `_schema.yaml` nested
    DEEPER than `<dir>/_schema.yaml` (here under an unknown, non-registry-shaped top-level
    dir) is not a top-level registry root and must not trip the unknown-root check. The
    deeper file is also outside $SCOPES, so the content scan never touches it — the tree is
    clean. (Tracked-mode depth filtering, where git's `*` spans '/', is covered by the
    real-repo run in test_current_repo_passes_in_default_tracked_mode: the tracked
    tests/fixtures/**/_schema.yaml markers are filtered and never flagged.)"""
    root = tmp_path / "nested"
    (root / "vendor" / "data").mkdir(parents=True)
    # No `vendor/_schema.yaml` — vendor is NOT registry-shaped at the top level.
    (root / "vendor" / "data" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "LEAK[" not in proc.stdout


# -----------------------------------------------------------------------------------
# S3: the framework asset-home emptiness arm (mixed-media increment A1)
# -----------------------------------------------------------------------------------


def test_framework_asset_home_readme_only_passes(tmp_path):
    """S3: the top-level `assets/` framework example-image home admits ONLY its
    convention doc — a README-only home is clean (`--mode all`)."""
    root = tmp_path / "asset-home-clean"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "README.md").write_text(
        "---\nprovenance: framework\n---\n# synthetic asset-home convention doc\n",
        encoding="utf-8",
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout
    assert "LEAK[" not in proc.stdout


def test_framework_asset_home_stray_file_leaks(tmp_path):
    """S3: any tracked file under top-level `assets/` other than README.md would ship in
    the PUBLIC repo UNFLAGGED (it carries no provenance frontmatter and assets/ is outside
    the content SCOPES) — the emptiness arm flags it as framework-asset (CLAUDE.md rules
    2/4). This is the S3 mechanism that turns 'empty at MVP' from hope into a real guard."""
    root = tmp_path / "asset-home-leak"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "README.md").write_text(
        "---\nprovenance: framework\n---\n# synthetic asset-home convention doc\n",
        encoding="utf-8",
    )
    (root / "assets" / "logo.png").write_bytes(
        b"\x89PNG\r\n\x1a\n synthetic non-real image bytes - never a client asset"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[framework-asset] assets/logo.png" in proc.stdout
    # README.md is the ONLY permitted resident: the stray binary is the sole finding.
    leaks = [line for line in proc.stdout.splitlines() if line.startswith("LEAK[")]
    assert len(leaks) == 1, proc.stdout


# -----------------------------------------------------------------------------------
# B-2: the foundation/-anchored GAP-4a arm (dual-safe reorg prep)
# -----------------------------------------------------------------------------------


def test_foundation_clean_tree_passes(tmp_path):
    """B-2 (i): a clean `foundation/`-shaped registry tree (foundation/dimensions/topics/
    with a co-located _schema.yaml + a `provenance: framework` entry) is GREEN. Exercises the
    foundation arm end to end — the registry IS in FOUNDATION_REGISTRY_DIRS (the GAP-4a
    coverage check passes it), the DEEP _schema.yaml is exempt BY BASENAME (the B-2 fix; the
    old position-based check only exempted flat depth-1 `<root>/_schema.yaml` and would have
    flagged this one missing-provenance), and the framework entry passes the content scan."""
    proc = guard_on_fixture(tmp_path, "foundation-clean")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout
    assert "LEAK[" not in proc.stdout


def test_foundation_unknown_registry_root_fails_loudly(tmp_path):
    """B-2 (ii): a `foundation/`-shaped registry whose token is NOT in
    pipeline.layout.REGISTRY_BASE / FOUNDATION_REGISTRY_DIRS (here foundation/dimensions/gadgets/)
    must FAIL — an unlisted foundation registry would otherwise ship UNVETTED. This is the
    foundation-anchored counterpart of the flat `glossaries/` unknown-root case, and fires
    exactly one leak (the structural coverage check) just like it."""
    proc = guard_on_fixture(tmp_path, "foundation-unknown-root")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[unknown-registry-root] foundation/dimensions/gadgets" in proc.stdout
    # The message must name the dir AND instruct the maintainer to whitelist it.
    assert "FOUNDATION_REGISTRY_DIRS" in proc.stdout
    leaks = [line for line in proc.stdout.splitlines() if line.startswith("LEAK[")]
    assert len(leaks) == 1, proc.stdout


def test_x_namespaced_schema_registry_still_leaks_x_file(tmp_path):
    """RV-1 ORDERING LOCK (B-2 blocker fix): the depth-agnostic `_schema.yaml` basename exemption
    must run AFTER the `x-*` PATH check, never before. An `x-*` reserved-namespace (§11.4 SV5)
    EXTENSION registry is registry-shaped and carries a co-located `_schema.yaml`
    (`topics/x-acme/_schema.yaml`); if the basename exemption ran first it would silently ship that
    instance namespace. The `x-*` path must leak by PATH first — exactly the base guard's behavior
    for `formats/x-fixture-format.md`, now locked for the `_schema.yaml` basename too. Also asserts
    the B-3-shape (`foundation/**/x-*/_schema.yaml`) leaks."""
    # Flat root form (the exact regression the review reproduced).
    root = tmp_path / "x-schema"
    (root / "topics" / "x-acme").mkdir(parents=True)
    (root / "topics" / "x-acme" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[x-file] topics/x-acme/_schema.yaml" in proc.stdout
    # depth-2 → GAP-4a's `*/*/*` skips it; only the content-scan x-file fires (exactly one leak).
    leaks = [line for line in proc.stdout.splitlines() if line.startswith("LEAK[")]
    assert len(leaks) == 1, proc.stdout

    # B-3-shape: an `x-*` extension registry nested under a foundation dimension still leaks.
    froot = tmp_path / "x-schema-foundation"
    (froot / "foundation" / "dimensions" / "topics" / "x-acme").mkdir(parents=True)
    (froot / "foundation" / "dimensions" / "topics" / "x-acme" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(froot), "--mode", "all")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[x-file] foundation/dimensions/topics/x-acme/_schema.yaml" in proc.stdout


def test_foundation_schema_manifest_is_exempt_by_basename(tmp_path):
    """B-2 basename exemption, isolated: a deep `foundation/**/_schema.yaml` (which carries no
    `provenance:` line) is exempt like any co-located SV4 manifest — the reworked guard must not
    default-deny it `missing-provenance`. The OLD position-based exemption
    (`[ "$f" = "$top/_schema.yaml" ]`) only matched flat depth-1 and would false-positive here."""
    root = tmp_path / "found-schema"
    (root / "foundation" / "dimensions" / "topics").mkdir(parents=True)
    (root / "foundation" / "dimensions" / "topics" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "LEAK[" not in proc.stdout


def test_foundation_arm_is_inert_on_a_flat_tree(tmp_path):
    """DUAL-SAFE: with no `foundation/` dir present the foundation arm no-ops — a flat
    `provenance: framework` registry tree stays green exactly as before the B-2 rework (the union
    SCOPES still scans the flat registries; `git ls-files -- foundation` / `[ -d foundation ]`
    simply match nothing)."""
    root = tmp_path / "flat-tree"
    (root / "topics").mkdir(parents=True)
    (root / "topics" / "_schema.yaml").write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "topics" / "framework-topic.md").write_text(
        "---\nprovenance: framework\n---\n# synthetic framework topic\n", encoding="utf-8"
    )
    proc = run_guard("--root", str(root), "--mode", "all")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "OK:" in proc.stdout


# -----------------------------------------------------------------------------------
# CLI contract
# -----------------------------------------------------------------------------------


def test_tracked_mode_outside_a_git_checkout_is_a_usage_error(tmp_path):
    root = tmp_path / "no-repo"
    root.mkdir()
    proc = run_guard("--root", str(root), "--mode", "tracked")
    assert proc.returncode == 2
    assert "--mode all" in proc.stderr


def test_unknown_argument_is_a_usage_error():
    proc = run_guard("--bogus")
    assert proc.returncode == 2
    assert "unknown argument" in proc.stderr


def test_invalid_mode_is_a_usage_error():
    proc = run_guard("--mode", "everything")
    assert proc.returncode == 2
    assert "--mode must be" in proc.stderr


def test_help_exits_zero():
    proc = run_guard("--help")
    assert proc.returncode == 0
    assert "usage:" in proc.stdout
