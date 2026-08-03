"""CLI tests for `pipeline workspace <new|list|delete>` + `pipeline user new` (W1/W2) — the
friendly LOCAL workspace lifecycle.

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
namespace, refuses-if-exists, and refuses a bad user.

W2 adds `workspace list` (READ-ONLY discovery — per-user + all-users `<user>/<workspace>` rows with
a TRUE topic-count/has-output summary; a missing users/ is a clean "no workspaces found"; a bad
--user refused) and `workspace delete` (DESTRUCTIVE, safe-by-default — refuse-by-default confirm,
Tier-2 has-output override needing --force, non-existent/symlink/bad-name refusals, sibling +
namespace survival). The §21.9 money-safety invariant holds for every verb (none registers an invoke
handler / mutates the module-global handler map). Every write is under a `tmp_path` `--root` — the
real `users/` is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline import workspacescaffold
from pipeline.authoring import AuthoringError
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


# ==============================================================================================
# W2: `pipeline workspace list` (READ-ONLY) + `pipeline workspace delete` (DESTRUCTIVE, SAFE).
# ==============================================================================================


def _seed(root: Path, workspace: str, *, user: str = USER) -> Path:
    """Seed ONE pristine workspace under `user` via the real CLI and return its target path."""
    assert _run_ws("new", workspace, "--user", user, "--root", str(root)) == 0
    return root / "users" / user / "workspaces" / workspace


# --- `workspace list`: per-user, all-users, empty, accurate summary, bad --user ---------------


def test_list_per_user_scoped(tmp_path, capsys):
    """`workspace list --user acme` lists ONLY acme's workspaces (bob's are excluded)."""
    root = _root(tmp_path)
    _seed(root, "alpha")
    _seed(root, "beta")
    _seed(root, "gamma", user="bob")
    capsys.readouterr()  # drop the seed output
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "acme/alpha" in out and "acme/beta" in out
    assert "bob/gamma" not in out  # scoped to --user acme


def test_list_all_users(tmp_path, capsys):
    """`workspace list` WITHOUT --user scans every user (users/*/workspaces/*), each row shown
    as <user>/<workspace>."""
    root = _root(tmp_path)
    _seed(root, "alpha")
    _seed(root, "gamma", user="bob")
    capsys.readouterr()
    assert _run_ws("list", "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "acme/alpha" in out
    assert "bob/gamma" in out


def test_list_empty_missing_users_is_clean_exit0(tmp_path, capsys):
    """A missing/empty users/ prints a clean 'no workspaces found' (exit 0), never a traceback."""
    root = _root(tmp_path)  # no users/ dir at all
    assert _run_ws("list", "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "no workspaces found" in out
    assert "Traceback" not in out


def test_list_summary_is_true(tmp_path, capsys):
    """The per-row summary is ACCURATE: a pristine workspace reports 0 topics + no output; after a
    real topic (topics/x-*.md) and a generated output file are added, it reports them."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    capsys.readouterr()
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    pristine = capsys.readouterr().out
    assert "acme/demo" in pristine
    assert "0 topic(s)" in pristine and "no output" in pristine

    (target / "topics" / "x-widgets.md").write_text("# widgets\n", encoding="utf-8")
    (target / "output" / "post.md").write_text("generated bytes\n", encoding="utf-8")
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    summary = capsys.readouterr().out
    assert "1 topic(s)" in summary and "has output" in summary


def test_list_gitkeep_only_output_is_not_generated(tmp_path, capsys):
    """A blueprint `output/.gitkeep` alone is NOT generated output — the summary stays 'no output'
    (the .gitkeep marker must never count as spent work)."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    assert (target / "output" / ".gitkeep").is_file()  # guard: blueprint really ships it
    capsys.readouterr()
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    assert "no output" in capsys.readouterr().out


def test_list_bad_user_refused(tmp_path, capsys):
    """A bad/uppercase --user is a loud refusal (exit 1), never a traceback."""
    root = _root(tmp_path)
    assert _run_ws("list", "--user", "Acme", "--root", str(root)) == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace list:")
    assert "Traceback" not in err


def test_workspace_list_never_registers_a_verb(tmp_path):
    """`workspace list` is a pure read: never registers a verb / mutates `_VERB_HANDLERS`."""
    root = _root(tmp_path)
    _seed(root, "demo")
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    assert invoke_mod._VERB_HANDLERS == before


# --- `workspace delete`: confirmation, has-output override, refusals, symlink, isolation -------


def test_delete_refuse_without_confirmation_headless(tmp_path, capsys):
    """Headless with NO --yes: refuse fast (exit 1, 'pass --yes'), nothing deleted (no TTY prompt
    to hang on)."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    capsys.readouterr()
    code = _run_ws("delete", "demo", "--user", USER, "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace delete:")
    assert "--yes" in err
    assert target.is_dir()  # untouched


def test_delete_yes_removes_pristine(tmp_path, capsys):
    """`--yes` deletes a pristine (no generated output) workspace → exit 0, dir gone."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    capsys.readouterr()
    assert _run_ws("delete", "demo", "--user", USER, "--root", str(root), "--yes") == 0
    assert not target.exists()
    assert "removed workspace 'demo'" in capsys.readouterr().out


def test_delete_hasoutput_refused_with_yes_then_deleted_with_force(tmp_path, capsys):
    """Tier-2 output guard: a workspace holding generated output is REFUSED with --yes alone
    (exit 1, 'generated output'), and DELETED only with --yes --force."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    (target / "output" / "post.md").write_text("spent work\n", encoding="utf-8")
    capsys.readouterr()

    assert _run_ws("delete", "demo", "--user", USER, "--root", str(root), "--yes") == 1
    err = capsys.readouterr().err
    assert "generated output" in err
    assert target.is_dir()  # NOT deleted — spent work protected

    assert _run_ws("delete", "demo", "--user", USER, "--root", str(root), "--yes", "--force") == 0
    assert not target.exists()


def test_delete_nonexistent_refused(tmp_path, capsys):
    """Deleting a workspace that does not exist is a loud exit-1 refusal (nothing to delete)."""
    root = _root(tmp_path)
    _seed(root, "demo")  # the user namespace exists; 'nope' does not
    capsys.readouterr()
    assert _run_ws("delete", "nope", "--user", USER, "--root", str(root), "--yes") == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline workspace delete:")
    assert "no workspace" in err


def test_delete_uppercase_workspace_refused(tmp_path, capsys):
    """A bad/uppercase <workspace> is refused by the isolation gate (exit 1), never a crash."""
    root = _root(tmp_path)
    assert _run_ws("delete", "Demo", "--user", USER, "--root", str(root), "--yes") == 1
    assert "Traceback" not in capsys.readouterr().err


def test_delete_uppercase_user_refused(tmp_path, capsys):
    """A bad/uppercase --user is refused by the isolation gate (exit 1), never a crash."""
    root = _root(tmp_path)
    assert _run_ws("delete", "demo", "--user", "Acme", "--root", str(root), "--yes") == 1
    assert "Traceback" not in capsys.readouterr().err


def test_delete_missing_user_is_usage_error(tmp_path):
    """`workspace delete demo` WITHOUT --user is a usage error (argparse exit 2) — --user is
    MANDATORY on delete."""
    root = _root(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run_ws("delete", "demo", "--root", str(root), "--yes")
    assert exc.value.code == 2


def test_delete_symlink_target_refused_link_target_intact(tmp_path, capsys):
    """A workspace dir that IS a symlink (pointing at a real sibling) is REFUSED (never delete
    through a link), even with --yes --force; the link target (and the link) stay intact."""
    root = _root(tmp_path)
    realws = _seed(root, "realws")
    (realws / "output" / "keep.md").write_text("real content\n", encoding="utf-8")
    ws_base = root / "users" / USER / "workspaces"
    linked = ws_base / "linked"
    linked.symlink_to(realws, target_is_directory=True)
    capsys.readouterr()

    code = _run_ws("delete", "linked", "--user", USER, "--root", str(root), "--yes", "--force")
    assert code == 1
    assert "symlink" in capsys.readouterr().err
    # the link target is untouched (never rmtree'd through the link), and the link itself remains
    assert realws.is_dir()
    assert (realws / "output" / "keep.md").read_text(encoding="utf-8") == "real content\n"
    assert linked.is_symlink()


def test_delete_preserves_namespace_and_sibling(tmp_path, capsys):
    """After a successful delete, users/<user>/ + its workspaces/ survive and a SIBLING workspace
    is UNTOUCHED (client isolation, rule 2)."""
    root = _root(tmp_path)
    keep = _seed(root, "keep")
    goner = _seed(root, "goner")
    (keep / "output" / "post.md").write_text("sibling work\n", encoding="utf-8")
    capsys.readouterr()

    assert _run_ws("delete", "goner", "--user", USER, "--root", str(root), "--yes") == 0
    assert not goner.exists()
    assert (root / "users" / USER / "workspaces").is_dir()  # namespace survives
    assert keep.is_dir()  # sibling untouched
    assert (keep / "output" / "post.md").read_text(encoding="utf-8") == "sibling work\n"


def test_delete_never_registers_a_verb(tmp_path):
    """`workspace delete` is a LOCAL file op: never registers a verb / mutates `_VERB_HANDLERS`
    (§21.9 — a delete cannot spend quota or mint a token)."""
    root = _root(tmp_path)
    _seed(root, "demo")
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run_ws("delete", "demo", "--user", USER, "--root", str(root), "--yes") == 0
    assert invoke_mod._VERB_HANDLERS == before


# --- the interactive type-the-name confirmation path (confirm_fn injection seam) ---------------


def test_delete_interactive_confirm_match_proceeds(tmp_path):
    """Interactive (confirm_fn injected): the operator TYPES the workspace name → the delete
    proceeds (the library seam, no --yes)."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    result = workspacescaffold.delete_workspace(
        root, USER, "demo", assume_yes=False, force=False, confirm_fn=lambda name: name
    )
    assert result.workspace == "demo"
    assert result.path == target
    assert not target.exists()


def test_delete_interactive_confirm_mismatch_aborts(tmp_path):
    """Interactive with a WRONG typed name → AuthoringError, nothing deleted."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    with pytest.raises(AuthoringError):
        workspacescaffold.delete_workspace(
            root, USER, "demo", assume_yes=False, force=False, confirm_fn=lambda name: "not-it"
        )
    assert target.is_dir()  # nothing deleted on a mismatch


def test_delete_hasoutput_refused_even_interactively_without_force(tmp_path):
    """The Tier-2 has-output guard fires BEFORE the prompt: a matching typed name still cannot
    delete a workspace holding generated output without --force (spent work is protected)."""
    root = _root(tmp_path)
    target = _seed(root, "demo")
    (target / "output" / "post.md").write_text("spent\n", encoding="utf-8")
    with pytest.raises(AuthoringError):
        workspacescaffold.delete_workspace(
            root, USER, "demo", assume_yes=False, force=False, confirm_fn=lambda name: name
        )
    assert target.is_dir()  # refused despite a matching confirmation
