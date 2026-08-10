"""CLI tests for `pipeline zone <new|list|delete>` + `--zone` on `workspace new|list|delete`
and `entry new` (Z7) — the per-zone CRUD surface, one level UP from the workspace lifecycle.

A zone groups a user's workspaces (§23): they live under `users/<user>/zones/<zone>/workspaces/`, so
a zone sits BETWEEN user and workspace. These tests exercise the SUBCOMMANDS end to end (through
`cli.main` / `cli._cmd_zone` / `cli._cmd_workspace` / `cli._cmd_entry`), REUSING the isolation gate
+ overwrite guard + typed refusals + has-output oracle (`pipeline.workspacescaffold`) — nothing
re-implemented:

- `zone new <zone> --user <u>` creates `users/<u>/zones/<zone>/workspaces/`; a brand-new zone (and a
  brand-new user namespace) is announced (a mistyped --user/--zone is visible), refuse-if-exists.
- `zone list [--user <u>]` is READ-ONLY: `<user>/<zone>` rows with a workspace count; a missing
  users/ is a clean "no zones found".
- `zone delete <zone> --user <u>` is DESTRUCTIVE + RECURSIVE + safe-by-default: Tier-1 typed-name
  confirmation (headless needs --yes), Tier-2 refuses if ANY contained workspace holds generated
  output (unless --force too), never deletes through a symlink, and leaves users/<u>/ in place.
- `workspace new/delete --zone Z` target one concrete zone; `workspace list --zone Z` FILTERS to one
  zone (no --zone → all zones). `entry new … --zone Z` homes a client entry in a non-default zone.

The §21.9 money-safety invariant holds for every verb (none registers an invoke handler / mutates
the module-global handler map). Every write is under a `tmp_path` `--root` — the real `users/` is
never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline import workspacescaffold
from pipeline.authoring import AuthoringError
from pipeline.layout import registry_dir
from pipeline.m1 import DIMENSION_COLLECTIONS
from pipeline.schema import SCHEMA_FILENAME
from pipeline.workspace_name import WorkspaceNameError

REPO_ROOT = Path(__file__).resolve().parents[1]
USER = "dave"


# --- helpers ----------------------------------------------------------------------------------


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir(parents=True)
    return root


def _run_zone(*argv: str) -> int:
    """Drive `zone` exactly as the shim does (`cli.main(["zone", …])`)."""
    return cli.main(["zone", *argv])


def _run_ws(*argv: str) -> int:
    """Drive `workspace` exactly as the shim does (`cli.main(["workspace", …])`)."""
    return cli.main(["workspace", *argv])


def _run_entry(*argv: str) -> int:
    """Drive `entry` exactly as the shim does (`cli.main(["entry", …])`)."""
    return cli.main(["entry", *argv])


def _zone_dir(root: Path, zone: str, *, user: str = USER) -> Path:
    return root / "users" / user / "zones" / zone


def _ws_dir(root: Path, zone: str, workspace: str, *, user: str = USER) -> Path:
    return _zone_dir(root, zone, user=user) / "workspaces" / workspace


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


# ==============================================================================================
# `zone new`: create the per-zone workspace home; announce a brand-new zone / user namespace.
# ==============================================================================================


def test_zone_new_creates_workspaces_base_and_announces(tmp_path, capsys):
    """`zone new work --user dave` creates users/dave/zones/work/workspaces/ and ANNOUNCES the new
    zone (created_zone) + the new user namespace (a mistyped --user/--zone is visible)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    ws_base = _zone_dir(root, "work") / "workspaces"
    assert ws_base.is_dir()
    assert list(ws_base.iterdir()) == []  # an EMPTY per-zone home — no workspace seeded

    out = capsys.readouterr().out
    assert "created zone 'work'" in out
    assert "created new user namespace" in out  # brand-new user announced


def test_zone_new_refuse_if_exists_then_force(tmp_path, capsys):
    """A second `zone new` on the same zone fails FAST headless (never hangs) → exit 1; `--force`
    is a safe no-op → exit 0 (deletes nothing, the zone survives)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    capsys.readouterr()
    code = _run_zone("new", "work", "--user", USER, "--root", str(root))
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert _run_zone("new", "work", "--user", USER, "--root", str(root), "--force") == 0
    # --force over an existing zone is honest: it announces a no-op, not a fresh create.
    assert "already existed (--force: no-op)" in capsys.readouterr().out
    assert (_zone_dir(root, "work") / "workspaces").is_dir()  # still there, undeleted


def test_zone_new_missing_user_is_usage_error(tmp_path):
    """`zone new work` WITHOUT --user is a usage error (argparse exit 2), never a silent write."""
    root = _root(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run_zone("new", "work", "--root", str(root))
    assert exc.value.code == 2
    assert not (root / "users").exists()


def test_zone_new_uppercase_zone_refused_no_crash(tmp_path, capsys):
    """An uppercase <zone> is refused loudly (§23 lowercase-only) → exit 1, no traceback, no dir."""
    root = _root(tmp_path)
    code = _run_zone("new", "Work", "--user", USER, "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone new:")
    assert "Traceback" not in err
    assert not (root / "users" / USER / "zones" / "Work").exists()


def test_zone_new_uppercase_user_refused_no_crash(tmp_path, capsys):
    """An uppercase --user is refused loudly (§23 lowercase-only) → exit 1, no directory."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", "Dave", "--root", str(root)) == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone new:")
    assert "Traceback" not in err
    assert not (root / "users").exists()


def test_zone_requires_subcommand_is_usage_error():
    """`pipeline zone` with no subcommand is a usage error (exit 2), never a silent no-op."""
    assert cli.main(["zone"]) == 2


# ==============================================================================================
# `zone list`: READ-ONLY <user>/<zone> rows with a TRUE workspace count.
# ==============================================================================================


def test_zone_list_shows_zone_and_count_updates(tmp_path, capsys):
    """`zone list --user dave` shows `work` with 0 workspaces; after a `workspace new` in that zone,
    the count updates to 1 (the summary is TRUE, never fabricated)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    capsys.readouterr()

    assert _run_zone("list", "--user", USER, "--root", str(root)) == 0
    zero = capsys.readouterr().out
    assert "dave/work" in zero and "0 workspace(s)" in zero

    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    capsys.readouterr()
    assert _run_zone("list", "--user", USER, "--root", str(root)) == 0
    one = capsys.readouterr().out
    assert "dave/work" in one and "1 workspace(s)" in one


def test_zone_list_all_users(tmp_path, capsys):
    """`zone list` WITHOUT --user scans every user (users/*/zones/*), rows shown <user>/<zone>."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    assert _run_zone("new", "team", "--user", "bob", "--root", str(root)) == 0
    capsys.readouterr()
    assert _run_zone("list", "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "dave/work" in out and "bob/team" in out


def test_zone_list_empty_missing_users_is_clean_exit0(tmp_path, capsys):
    """A missing/empty users/ prints a clean 'no zones found' (exit 0), never a traceback."""
    root = _root(tmp_path)  # no users/ dir at all
    assert _run_zone("list", "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "no zones found" in out
    assert "Traceback" not in out


def test_zone_list_bad_user_refused(tmp_path, capsys):
    """A bad/uppercase --user is a loud refusal (exit 1), never a traceback."""
    root = _root(tmp_path)
    assert _run_zone("list", "--user", "Dave", "--root", str(root)) == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone list:")
    assert "Traceback" not in err


# ==============================================================================================
# `workspace new/list/delete --zone`: target / filter one concrete zone.
# ==============================================================================================


def test_workspace_new_zone_and_default_are_distinct_rows(tmp_path, capsys):
    """`workspace new acme --zone work` homes under `work` zone; `workspace new demo` (no --zone)
    homes under `default`. `workspace list` shows both distinct <user>/<zone>/<workspace> rows."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    assert _ws_dir(root, "work", "acme").is_dir()
    assert _run_ws("new", "demo", "--user", USER, "--root", str(root)) == 0  # no --zone → default
    assert _ws_dir(root, "default", "demo").is_dir()
    capsys.readouterr()

    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "dave/work/acme" in out
    assert "dave/default/demo" in out


def test_workspace_new_zone_announces_new_zone(tmp_path, capsys):
    """MINOR 5: a `workspace new --zone` into a brand-new zone CREATES + ANNOUNCES the zone (a
    mistyped --zone is visible, never silent)."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "typbooo", "--root", str(root)) == 0
    out = capsys.readouterr().out
    assert "created new zone 'typbooo'" in out


def test_workspace_list_zone_filter(tmp_path, capsys):
    """`workspace list --zone work` FILTERS to that one zone; without --zone ALL zones show."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    assert _run_ws("new", "demo", "--user", USER, "--zone", "personal", "--root", str(root)) == 0
    capsys.readouterr()

    assert _run_ws("list", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    filtered = capsys.readouterr().out
    assert "dave/work/acme" in filtered
    assert "dave/personal/demo" not in filtered  # scoped to --zone work

    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    every = capsys.readouterr().out
    assert "dave/work/acme" in every and "dave/personal/demo" in every  # no --zone → all zones


def test_workspace_delete_zone_scoped(tmp_path, capsys):
    """`workspace delete acme --zone work` removes ONLY the `work`-zone acme; a same-named acme in
    another zone is untouched (client isolation across zones, rule 2)."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    assert _run_ws("new", "acme", "--user", USER, "--zone", "personal", "--root", str(root)) == 0
    capsys.readouterr()

    assert (
        _run_ws("delete", "acme", "--user", USER, "--zone", "work", "--root", str(root), "--yes")
        == 0
    )
    assert not _ws_dir(root, "work", "acme").exists()
    assert _ws_dir(root, "personal", "acme").is_dir()  # the other-zone twin survives


# ==============================================================================================
# `zone delete`: two-tier safety, RECURSIVE, never-through-symlink, namespace survival.
# ==============================================================================================


def test_zone_delete_headless_without_yes_aborts(tmp_path, capsys):
    """Tier-1 headless with NO --yes: refuse fast (exit 1, 'pass --yes'), the zone stays intact."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    capsys.readouterr()
    code = _run_zone("delete", "work", "--user", USER, "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone delete:")
    assert "--yes" in err
    assert _zone_dir(root, "work").is_dir()  # untouched


def test_zone_delete_wrong_name_aborts(tmp_path):
    """Tier-1 interactive with a WRONG typed zone name → AuthoringError, the zone stays intact
    (the library confirm_fn seam)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    with pytest.raises(AuthoringError):
        workspacescaffold.delete_zone(
            root, USER, "work", assume_yes=False, force=False, confirm_fn=lambda name: "not-it"
        )
    assert _zone_dir(root, "work").is_dir()  # nothing deleted on a mismatch


def test_zone_delete_interactive_confirm_match_proceeds(tmp_path):
    """Tier-1 interactive with a MATCHING typed zone name → the delete proceeds (no --yes)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    zone_dir = _zone_dir(root, "work")
    result = workspacescaffold.delete_zone(
        root, USER, "work", assume_yes=False, force=False, confirm_fn=lambda name: name
    )
    assert result.zone == "work"
    assert result.path == zone_dir
    assert not zone_dir.exists()


def test_zone_delete_yes_removes_pristine_zone(tmp_path, capsys):
    """`--yes` deletes a zone whose workspaces hold NO generated output → exit 0, zone gone,
    users/<user>/ survives."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    capsys.readouterr()
    assert _run_zone("delete", "work", "--user", USER, "--root", str(root), "--yes") == 0
    assert not _zone_dir(root, "work").exists()
    assert (root / "users" / USER).is_dir()  # the user namespace survives
    out = capsys.readouterr().out
    assert "removed zone 'work'" in out and "1 workspace(s)" in out


def test_zone_delete_hasoutput_refused_with_yes_then_force(tmp_path, capsys):
    """Tier-2 (RECURSIVE): a zone with ANY contained workspace holding generated output is REFUSED
    under --yes alone (exit 1), and DELETED only with --yes --force."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    # spent work in a contained workspace
    (_ws_dir(root, "work", "acme") / "output" / "post.md").write_text("spent\n", encoding="utf-8")
    capsys.readouterr()

    assert _run_zone("delete", "work", "--user", USER, "--root", str(root), "--yes") == 1
    err = capsys.readouterr().err
    assert "generated output" in err
    assert _zone_dir(root, "work").is_dir()  # NOT deleted — spent work protected

    assert _run_zone("delete", "work", "--user", USER, "--root", str(root), "--yes", "--force") == 0
    assert not _zone_dir(root, "work").exists()
    assert (root / "users" / USER).is_dir()  # user namespace still survives


def test_zone_delete_nonexistent_refused(tmp_path, capsys):
    """Deleting a zone that does not exist is a loud exit-1 refusal (nothing to delete)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0  # user ns exists
    capsys.readouterr()
    assert _run_zone("delete", "nope", "--user", USER, "--root", str(root), "--yes") == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone delete:")
    assert "no zone" in err


def test_zone_delete_symlink_target_refused_intact(tmp_path, capsys):
    """A zone dir that IS a symlink (pointing at a real sibling zone) is REFUSED (never delete
    through a link), even with --yes --force; the link target (and the link) stay intact."""
    root = _root(tmp_path)
    assert _run_ws("new", "acme", "--user", USER, "--zone", "realzone", "--root", str(root)) == 0
    realzone = _zone_dir(root, "realzone")
    (_ws_dir(root, "realzone", "acme") / "output" / "keep.md").write_text(
        "real\n", encoding="utf-8"
    )
    zones_base = root / "users" / USER / "zones"
    linked = zones_base / "linked"
    linked.symlink_to(realzone, target_is_directory=True)
    capsys.readouterr()

    code = _run_zone("delete", "linked", "--user", USER, "--root", str(root), "--yes", "--force")
    assert code == 1
    assert "symlink" in capsys.readouterr().err
    # the link target is untouched (never rmtree'd through the link), and the link itself remains
    assert realzone.is_dir()
    assert (_ws_dir(root, "realzone", "acme") / "output" / "keep.md").read_text(
        encoding="utf-8"
    ) == "real\n"
    assert linked.is_symlink()


def test_zone_delete_missing_user_is_usage_error(tmp_path):
    """`zone delete work` WITHOUT --user is a usage error (exit 2) — --user is MANDATORY."""
    root = _root(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run_zone("delete", "work", "--root", str(root), "--yes")
    assert exc.value.code == 2


# --- BLOCKER regressions: the recursive rmtree must NEVER escape the repo root -----------------
# `delete_zone` runs the FULL L1+L2+L3 isolation gate (like `validate_workspace_path`), not
# `validate_zone_segment` alone — so neither a crafted `--user` nor a symlinked intermediate
# `zones/` can steer the rmtree outside `<root>`.


def test_zone_delete_crafted_user_escape_refused(tmp_path, capsys):
    """BLOCKER 1: a crafted `--user "../../<victim>"` must be REFUSED at L1 (user hygiene +
    resolve-and-contain), NOT rmtree'd. The out-of-tree victim `<tmp>/vh/zones/secret/` survives —
    proven through BOTH the library `delete_zone` and the CLI path — never exit 0."""
    root = _root(tmp_path)  # the "repo" is <tmp>/root
    # the victim lives OUTSIDE the repo, exactly where `root/users/../../vh/zones/secret` resolves
    victim = tmp_path / "vh" / "zones" / "secret"
    victim.mkdir(parents=True)
    (victim / "keep.md").write_text("out-of-tree data\n", encoding="utf-8")

    # (library) the crafted user is refused by the L1 gate — nothing removed
    with pytest.raises((AuthoringError, WorkspaceNameError)):
        workspacescaffold.delete_zone(
            root, "../../vh", "secret", assume_yes=True, force=True
        )
    assert victim.is_dir() and (victim / "keep.md").is_file()  # untouched

    # (CLI) the same vector exits non-zero (typed refusal), never exit 0, victim intact
    code = _run_zone(
        "delete", "secret", "--user", "../../vh", "--root", str(root), "--yes", "--force"
    )
    assert code != 0
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone delete:")
    assert "Traceback" not in err
    assert victim.is_dir()
    assert (victim / "keep.md").read_text(encoding="utf-8") == "out-of-tree data\n"


def test_zone_delete_symlinked_intermediate_zones_refused(tmp_path, capsys):
    """BLOCKER 2: a symlinked intermediate `users/<u>/zones` → an EXTERNAL tree must be REFUSED at
    L2 (the fixed `zones/` join must resolve to a direct child of the user home). The rmtree never
    follows the prefix symlink, so the external target survives — the leaf `is_symlink()` guard
    alone does NOT catch this (the leaf reached THROUGH the link is a real dir)."""
    root = _root(tmp_path)
    # an external tree the symlinked zones/ points at; the "zone" leaf is a REAL dir inside it
    external = tmp_path / "external"
    (external / "secret").mkdir(parents=True)
    (external / "secret" / "keep.md").write_text("external data\n", encoding="utf-8")
    # plant users/<u>/zones as a symlink to the external tree
    owner = root / "users" / USER
    owner.mkdir(parents=True)
    (owner / "zones").symlink_to(external, target_is_directory=True)

    # (library) refused at L2 — the prefix symlink is never followed through
    with pytest.raises((AuthoringError, WorkspaceNameError)):
        workspacescaffold.delete_zone(root, USER, "secret", assume_yes=True, force=True)
    assert (external / "secret" / "keep.md").is_file()  # external target untouched

    # (CLI) same vector exits non-zero, external target intact
    code = _run_zone(
        "delete", "secret", "--user", USER, "--root", str(root), "--yes", "--force"
    )
    assert code != 0
    err = capsys.readouterr().err
    assert err.startswith("pipeline zone delete:")
    assert "Traceback" not in err
    assert (external / "secret" / "keep.md").read_text(encoding="utf-8") == "external data\n"


# ==============================================================================================
# Q2 CRUD lifecycle: two zones, same-named workspaces, delete one leaves the other intact.
# ==============================================================================================


def test_q2_zone_crud_lifecycle(tmp_path, capsys):
    """The Q2 lifecycle: `zone new work` + `zone new personal`; `workspace new acme --zone work`
    + `workspace new acme --zone personal` → both listed distinctly; `zone delete work --force`
    leaves dave/personal/acme intact (users/dave/ survives)."""
    root = _root(tmp_path)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    assert _run_zone("new", "personal", "--user", USER, "--root", str(root)) == 0
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    assert _run_ws("new", "acme", "--user", USER, "--zone", "personal", "--root", str(root)) == 0
    capsys.readouterr()

    # both same-named workspaces are listed as DISTINCT rows (isolated by zone)
    assert _run_ws("list", "--user", USER, "--root", str(root)) == 0
    listed = capsys.readouterr().out
    assert "dave/work/acme" in listed and "dave/personal/acme" in listed

    # delete the whole `work` zone (recursive) — personal is untouched
    assert _run_zone("delete", "work", "--user", USER, "--root", str(root), "--yes", "--force") == 0
    assert not _zone_dir(root, "work").exists()
    assert _ws_dir(root, "personal", "acme").is_dir()  # the personal-zone twin survives
    assert (root / "users" / USER).is_dir()  # users/dave/ survives every delete


# ==============================================================================================
# `entry new --zone`: author a client (x-) entry into a non-default zone.
# ==============================================================================================


def _copy_schema(root: Path, collection: str) -> None:
    """Copy the real framework `<collection>/_schema.yaml` into `root` so `entry new` (which loads
    the co-located dimension schema from --root) can scaffold — mirrors test_cmd_entry."""
    dst = registry_dir(root, collection) / SCHEMA_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (registry_dir(REPO_ROOT, collection) / SCHEMA_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )


def test_entry_new_zone_homes_under_zone(tmp_path, capsys):
    """`entry new topic x-widgets --user dave --workspace acme --zone work` homes the client topic
    under users/dave/zones/work/workspaces/acme/topics/x-widgets.md (a non-default zone)."""
    root = _root(tmp_path)
    _copy_schema(root, DIMENSION_COLLECTIONS["topic"])  # entry new loads the co-located schema
    assert _run_ws("new", "acme", "--user", USER, "--zone", "work", "--root", str(root)) == 0
    capsys.readouterr()
    code = _run_entry(
        "new", "topic", "x-widgets",
        "--user", USER, "--workspace", "acme", "--zone", "work", "--root", str(root),
    )
    assert code == 0
    homed = _ws_dir(root, "work", "acme") / "topics" / "x-widgets.md"
    assert homed.is_file()
    # the DEFAULT zone did NOT get the entry (the --zone actually routed it)
    assert not (_ws_dir(root, "default", "acme") / "topics" / "x-widgets.md").exists()


# ==============================================================================================
# §21.9 money-safety: every zone verb is a LOCAL scaffold — never the invoke door.
# ==============================================================================================


def test_zone_verbs_never_register_a_verb(tmp_path):
    """`zone new` / `zone list` / `zone delete` are LOCAL file ops: none registers a verb / mutates
    the module-global `_VERB_HANDLERS` (they cannot spend quota or mint a token; §21.9)."""
    root = _root(tmp_path)
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run_zone("new", "work", "--user", USER, "--root", str(root)) == 0
    assert _run_zone("list", "--user", USER, "--root", str(root)) == 0
    assert _run_zone("delete", "work", "--user", USER, "--root", str(root), "--yes") == 0
    assert invoke_mod._VERB_HANDLERS == before  # handler map untouched across all three verbs
