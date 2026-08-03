"""CLI tests for `pipeline workspace new` + `pipeline user new` (W1) — the friendly LOCAL
workspace scaffolder.

`workspace new <workspace> --user <user> [--root DIR] [--force]` wires the thin
`pipeline.workspacescaffold` leaf (which REUSES the C2a `pipeline.authoring` overwrite guard + the
`pipeline.workspace_name` isolation gate — nothing re-implemented) into the operator CLI. These
tests exercise the SUBCOMMANDS end to end (through `cli.main` / `cli._cmd_workspace` /
`cli._cmd_user`): `workspace new` seeds the FULL `templates/workspace/` blueprint under
`users/<user>/workspaces/<workspace>/` (every file present + byte-identical to the blueprint); the
created workspace resolves via `validate_workspace_path`; refuse-if-exists fails FAST headless and
`--force` seeds only MISSING files (NEVER overwrites client data); a missing `--user` is a usage
error (exit 2); a bad/uppercase `--user` or `<workspace>` is a loud refusal (exit 1, never a crash);
the new-user-namespace note prints only when the user is new. `user new` creates the empty per-user
namespace, refuses-if-exists, and refuses a bad user. The §21.9 money-safety invariant holds
(neither verb registers an invoke handler / mutates the module-global handler map). Every write is
under a `tmp_path` `--root` — the real `users/` is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline.workspace_name import validate_workspace_path

REPO_ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT = REPO_ROOT / "templates" / "workspace"
USER = "acme"

#: The blueprint's relative file paths (the 8 shipped files, incl. the four `.gitkeep` markers).
BLUEPRINT_FILES = sorted(str(p.relative_to(BLUEPRINT)) for p in BLUEPRINT.rglob("*") if p.is_file())


# --- helpers ----------------------------------------------------------------------------------


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    return root


def _run_ws(*argv: str) -> int:
    """Drive `workspace` exactly as the shim does (`cli.main(["workspace", …])`)."""
    return cli.main(["workspace", *argv])


def _run_user(*argv: str) -> int:
    """Drive `user` exactly as the shim does (`cli.main(["user", …])`)."""
    return cli.main(["user", *argv])


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke dispatch registry so the money-safety negative
    assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


# --- the crux: seed the FULL blueprint tree under users/<user>/workspaces/<ws>/ ---------------


def test_workspace_new_seeds_full_tree(tmp_path, capsys):
    """`workspace new demo --user acme --root <root>` creates users/acme/workspaces/demo/ with
    ALL 8 blueprint files, each byte-identical to templates/workspace/, and prints the path."""
    root = _root(tmp_path)
    assert BLUEPRINT_FILES  # guard: the blueprint really ships files (not a vacuous assertion)
    code = _run_ws("new", "demo", "--user", USER, "--root", str(root))
    assert code == 0
    target = root / "users" / USER / "workspaces" / "demo"
    assert target.is_dir()

    # every blueprint file is present under the target and byte-identical to the blueprint copy
    for rel in BLUEPRINT_FILES:
        seeded = target / rel
        assert seeded.is_file(), f"missing seeded file {rel!r}"
        assert seeded.read_bytes() == (BLUEPRINT / rel).read_bytes(), f"content drift for {rel!r}"

    # exactly the blueprint's files were seeded — no more, no fewer (the §5.4 faithful copy)
    seeded_files = sorted(str(p.relative_to(target)) for p in target.rglob("*") if p.is_file())
    assert seeded_files == BLUEPRINT_FILES

    # the four empty-dir homes (assets/output/select/topics) carry their .gitkeep
    for d in ("assets", "output", "select", "topics"):
        assert (target / d / ".gitkeep").is_file()

    out = capsys.readouterr().out
    assert "demo" in out and str(target) in out  # prints the exact workspace + path


def test_created_workspace_resolves_via_validate_workspace_path(tmp_path):
    """The created target is EXACTLY the isolation gate's contained path for (root, user, ws)."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    resolved = validate_workspace_path(root, USER, "demo")
    assert resolved == root / "users" / USER / "workspaces" / "demo"
    assert resolved.is_dir()


# --- refuse-if-exists (D8): fail FAST headless; --force is non-destructive ---------------------


def test_refuse_if_exists_then_force(tmp_path, capsys):
    """A second `workspace new` on the same target fails FAST headless (never hangs) → exit 1;
    `--force` proceeds → exit 0."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    code = _run_ws("new", "demo", "--user", USER, "--root", str(root))
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root), "--force") == 0


def test_force_never_overwrites_existing_file_and_tops_up_missing(tmp_path):
    """`--force` is SAFE: an edited file survives (never clobbered) and a deleted blueprint file is
    topped up — the copy is non-destructive (rule 1/2; never deletes client data)."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    target = root / "users" / USER / "workspaces" / "demo"

    # the user has edited source.md and (say) removed readme.md
    edited = "EDITED BY CLIENT — do not clobber\n"
    (target / "source.md").write_text(edited, encoding="utf-8")
    (target / "readme.md").unlink()

    assert _run_ws("new", "demo", "--user", USER, "--root", str(root), "--force") == 0
    # the edited file is preserved verbatim (never overwritten)
    assert (target / "source.md").read_text(encoding="utf-8") == edited
    # the missing file is restored from the blueprint (topped up)
    assert (target / "readme.md").read_bytes() == (BLUEPRINT / "readme.md").read_bytes()


def test_force_dir_replaced_by_file_is_typed_refusal(tmp_path, capsys):
    """LOW-1: a client who replaced a seeded blueprint DIR (topics/) with a same-named regular FILE
    and re-runs with --force gets a CLEAN typed refusal (exit 1, `invalid-authoring`), NEVER a raw
    traceback — the collision is caught before any copy/delete, so the file stays untouched."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    target = root / "users" / USER / "workspaces" / "demo"

    import shutil as _shutil

    _shutil.rmtree(target / "topics")
    sentinel = "client turned this dir into a file\n"
    (target / "topics").write_text(sentinel, encoding="utf-8")

    code = _run_ws("new", "demo", "--user", USER, "--root", str(root), "--force")
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace new:")
    assert "invalid-authoring" in err
    assert "Traceback" not in err  # loud + typed, never a stack trace
    # non-destructive: the client's file is exactly as they left it (never crashed mid-copy)
    assert (target / "topics").read_text(encoding="utf-8") == sentinel


def test_force_file_replaced_by_dir_is_typed_refusal(tmp_path, capsys):
    """LOW-1 (reverse): a client who replaced a seeded blueprint FILE (source.md) with a same-named
    DIRECTORY and re-runs with --force also gets a clean typed refusal (exit 1), not a traceback."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    target = root / "users" / USER / "workspaces" / "demo"

    (target / "source.md").unlink()
    (target / "source.md").mkdir()

    code = _run_ws("new", "demo", "--user", USER, "--root", str(root), "--force")
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace new:")
    assert "invalid-authoring" in err
    assert "Traceback" not in err
    assert (target / "source.md").is_dir()  # the client's dir is untouched


# --- --user is MANDATORY: a missing --user is a usage error (exit 2) ---------------------------


def test_missing_user_is_usage_error(tmp_path):
    """`workspace new demo` WITHOUT --user is a usage error (argparse exit 2), never a silent
    write — --user is REQUIRED (§23)."""
    root = _root(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run_ws("new", "demo", "--root", str(root))
    assert exc.value.code == 2
    assert not (root / "users").exists()  # nothing written


# --- bad / uppercase names are loud refusals (exit 1, never a crash) ---------------------------


def test_uppercase_user_refused_no_crash(tmp_path, capsys):
    """An uppercase `--user` is refused loudly (§23 lowercase-only) → exit 1, no traceback, no
    directory."""
    root = _root(tmp_path)
    code = _run_ws("new", "demo", "--user", "Acme", "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace new:")
    assert "Traceback" not in err
    assert not (root / "users").exists()


def test_uppercase_workspace_refused_no_crash(tmp_path, capsys):
    """An uppercase `<workspace>` is refused loudly (§23 lowercase-only) → exit 1, no directory."""
    root = _root(tmp_path)
    code = _run_ws("new", "Demo", "--user", USER, "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace new:")
    assert "Traceback" not in err
    assert not (root / "users" / USER / "workspaces" / "Demo").exists()


def test_traversal_workspace_refused(tmp_path, capsys):
    """A `<workspace>` with a path separator (traversal attempt) is refused by the isolation gate
    (§21.1 resolve-and-contain) → exit 1, no escape."""
    root = _root(tmp_path)
    assert _run_ws("new", "../evil", "--user", USER, "--root", str(root)) == 1
    assert "Traceback" not in capsys.readouterr().err


# --- the new-user-namespace note (a mistyped --user must be visible, never silent) -------------


def test_new_user_namespace_note_prints_once(tmp_path, capsys):
    """The FIRST workspace under a brand-new user prints the 'created new user namespace' note; a
    SECOND workspace under the SAME user does NOT reprint it (the home already existed)."""
    root = _root(tmp_path)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    first = capsys.readouterr().out
    assert "created new user namespace" in first

    assert _run_ws("new", "second", "--user", USER, "--root", str(root)) == 0
    second = capsys.readouterr().out
    assert "created new user namespace" not in second


# --- usage: no subcommand is exit 2 -----------------------------------------------------------


def test_workspace_requires_subcommand_is_usage_error():
    """`pipeline workspace` with no subcommand is a usage error (exit 2), never a silent no-op."""
    assert cli.main(["workspace"]) == 2


# --- §21.9 money-safety: a LOCAL scaffold never touches the invoke door ------------------------


def test_workspace_new_never_registers_a_verb(tmp_path):
    """`workspace new` is a LOCAL file scaffold: it never registers a verb / mutates the
    module-global `_VERB_HANDLERS` (it cannot spend quota or mint a token; §21.9)."""
    root = _root(tmp_path)
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0
    assert invoke_mod._VERB_HANDLERS == before  # handler map untouched


def test_workspacescaffold_source_calls_no_register():
    """Structural: the `workspacescaffold` module + the `_cmd_workspace` / `_cmd_user` region
    contain no `register_` call and never dispatch through the invoke door — money-safety by
    construction (§21.9)."""
    scaffold_src = (REPO_ROOT / "pipeline" / "workspacescaffold.py").read_text(encoding="utf-8")
    assert "register_" not in scaffold_src
    assert "invoke_mod" not in scaffold_src

    main_src = (REPO_ROOT / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    start = main_src.index("def _workspace_error_types")
    end = main_src.index("_COMMANDS = {")
    region = main_src[start:end]
    assert "register_" not in region
    assert "invoke_mod" not in region and "main_cli(" not in region


# --- `pipeline user new`: the empty per-user namespace sibling ---------------------------------


def test_user_new_creates_namespace(tmp_path, capsys):
    """`user new bob --root <root>` creates the empty per-user namespace users/bob/workspaces/
    (no workspace) and prints the path."""
    root = _root(tmp_path)
    assert _run_user("new", "bob", "--root", str(root)) == 0
    ns = root / "users" / "bob" / "workspaces"
    assert ns.is_dir()
    # it is an EMPTY namespace — no workspace seeded
    assert list(ns.iterdir()) == []
    assert str(ns) in capsys.readouterr().out


def test_user_new_refuse_if_exists_then_force(tmp_path, capsys):
    """A second `user new` on the same namespace fails FAST headless → exit 1; `--force` is a safe
    no-op → exit 0 (deletes nothing)."""
    root = _root(tmp_path)
    assert _run_user("new", "bob", "--root", str(root)) == 0
    code = _run_user("new", "bob", "--root", str(root))
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert _run_user("new", "bob", "--root", str(root), "--force") == 0
    assert (root / "users" / "bob" / "workspaces").is_dir()  # still there, undeleted


def test_user_new_bad_user_refused_no_crash(tmp_path, capsys):
    """An uppercase user is refused loudly (§23 lowercase-only) → exit 1, no traceback, no dir."""
    root = _root(tmp_path)
    code = _run_user("new", "Bob", "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline user new:")
    assert "Traceback" not in err
    assert not (root / "users").exists()


def test_user_requires_subcommand_is_usage_error():
    """`pipeline user` with no subcommand is a usage error (exit 2), never a silent no-op."""
    assert cli.main(["user"]) == 2


def test_user_new_never_registers_a_verb(tmp_path):
    """`user new` is a LOCAL file op: never registers a verb / mutates `_VERB_HANDLERS` (§21.9)."""
    root = _root(tmp_path)
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run_user("new", "bob", "--root", str(root)) == 0
    assert invoke_mod._VERB_HANDLERS == before
