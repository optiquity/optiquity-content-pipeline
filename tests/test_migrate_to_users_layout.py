"""Tests for scripts/migrate-to-users-layout.sh — the §23 on-disk re-home migration (B8).

Mirrors the test_guard.py seam: build a synthetic workspaces/ tree under a pytest `tmp_path`
`--root` and drive the shell script via subprocess, so the REAL (gitignored, irreplaceable)
instance workspaces are never touched. Covers the safety contract: idempotent, dry-run mutates
nothing, refuse-don't-overwrite on a target collision, NEVER-DELETE-DATA under --force, the
lowercase name hygiene (owner + workspace), and the self-reference WARNING (fires on a path into
the OLD flat store, silent on an EXTERNAL client/graph path).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "migrate-to-users-layout.sh"

# An EXTERNAL absolute path (a client graph, read read-only by path) — must NEVER warn.
_EXTERNAL_SOURCE = (
    "---\nadapter: graphify\nconnection:\n"
    "  path: /Users/someone/Developer/optiquity-site/graphify-out/graph.json\n---\nbody\n"
)


def seed(root: Path, names: tuple[str, ...] = ("mvp-demo", "optiquitytrader")) -> None:
    """Build a synthetic flat-layout workspaces/ tree with two config surfaces per workspace."""
    for name in names:
        ws = root / "workspaces" / name
        (ws / "sources").mkdir(parents=True)
        (ws / "topics").mkdir(parents=True)
        (ws / "defaults.yaml").write_text(
            "values:\n  platform.reconcile_strategy: pass\n", encoding="utf-8"
        )
        (ws / "sources" / "src.md").write_text(_EXTERNAL_SOURCE, encoding="utf-8")
        (ws / "topics" / "t.md").write_text("topic body\n", encoding="utf-8")


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def tree(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*")}


def test_help_exits_zero() -> None:
    proc = subprocess.run(
        ["bash", str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "usage:" in proc.stdout


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root)
    before = tree(root)
    proc = run(root, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "DRY-RUN would: mv" in proc.stdout
    assert proc.stdout.count("DRY-RUN would: mv") == 2
    assert tree(root) == before  # nothing moved


def test_real_run_rehomes_and_removes_flat_dir(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root)
    proc = run(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (root / "users/optiquity/workspaces/mvp-demo/defaults.yaml").is_file()
    assert (root / "users/optiquity/workspaces/optiquitytrader/defaults.yaml").is_file()
    assert not (root / "workspaces").exists()  # empty flat dir removed


def test_custom_owner(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("proj",))
    proc = run(root, "--owner", "acme")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (root / "users/acme/workspaces/proj/defaults.yaml").is_file()


def test_idempotent_rerun_is_noop(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root)
    assert run(root).returncode == 0
    after_first = tree(root)
    proc = run(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing to migrate" in proc.stdout
    assert tree(root) == after_first  # second run changed nothing


def test_target_exists_refused_without_force(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    (root / "users/optiquity/workspaces/mvp-demo").mkdir(parents=True)
    proc = run(root)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REFUSING 'mvp-demo'" in proc.stderr
    assert (root / "workspaces/mvp-demo").is_dir()  # source untouched


def test_force_absorbs_empty_target(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    (root / "users/optiquity/workspaces/mvp-demo").mkdir(parents=True)  # empty target
    proc = run(root, "--force")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert (root / "users/optiquity/workspaces/mvp-demo/defaults.yaml").is_file()
    assert not (root / "workspaces").exists()


def test_force_never_overwrites_a_colliding_target(tmp_path: Path) -> None:
    """The never-delete-data contract: --force merges only non-colliding entries; a colliding
    target file is preserved verbatim and the source copy is left in place (never discarded)."""
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    target = root / "users/optiquity/workspaces/mvp-demo"
    target.mkdir(parents=True)
    (target / "defaults.yaml").write_text("PRE-EXISTING\n", encoding="utf-8")  # collision
    proc = run(root, "--force")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "REFUSING to overwrite" in proc.stderr
    # target preserved, source retained — no data destroyed on either side.
    assert (target / "defaults.yaml").read_text(encoding="utf-8") == "PRE-EXISTING\n"
    assert (root / "workspaces/mvp-demo/defaults.yaml").is_file()


def test_self_ref_path_warns_but_external_does_not(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    # A self-referential absolute path INTO the workspace's own OLD flat store.
    (root / "workspaces/mvp-demo/sources/selfref.md").write_text(
        "---\nnote: /some/checkout/workspaces/mvp-demo/sources/old.md\n---\n",
        encoding="utf-8",
    )
    proc = run(root, "--dry-run")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SELF-REF[mvp-demo]" in proc.stdout
    assert "selfref.md" in proc.stdout
    # The external graph path seeded by seed() must NOT trip the scan.
    assert "src.md" not in proc.stdout


def test_bad_owner_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    for bad in ("../evil", "Optiquity", "a/b"):
        proc = run(root, "--owner", bad)
        assert proc.returncode == 2, (bad, proc.stdout + proc.stderr)
        assert "invalid --owner" in proc.stderr
    assert (root / "workspaces/mvp-demo").is_dir()  # never moved on a bad owner


def test_bad_workspace_name_refuses_whole_run(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    seed(root, names=("mvp-demo",))
    (root / "workspaces/BadName/sources").mkdir(parents=True)  # uppercase = not lowercase-safe
    proc = run(root)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "BadName" in proc.stderr
    assert not (root / "users").exists()  # pre-flight refusal: nothing moved


def test_no_workspaces_dir_is_clean_noop(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    proc = run(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing to migrate" in proc.stdout
