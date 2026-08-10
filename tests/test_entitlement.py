"""The single entitled SUBSCRIPTION user — config + admin verb + the U==entitled check (plan G5).

Proves the G5 gate WITHOUT any spend (no transport is selected, no secret is resolved, nothing
meters — those are G6/G7). Every test writes only under a pytest `tmp_path` root:

- **single-valued + swappable** — setting a second user REPLACES the first; the config carries at
  most ONE `subscription_user` (never two entitled users).
- **the check API** — `set-subscription-user dave` → `is_entitled(root,'dave')` True,
  `is_entitled(root,'erin')` False, `entitled_user == 'dave'`; `clear-subscription-user` → `None`.
  `is_entitled` is a PURE equality (unset → False for everyone, incl. `None`).
- **typed refuse, nothing written** — a bad user segment (`../x`, uppercase, empty, slashed) is a
  loud `InvalidUserError` (API) / exit-1 refusal (CLI) and NOTHING is written.
- **I2/I3 — admin-only** — the entitled user is set ONLY via the two Tier-A admin verbs; no
  run-verb (`generate`/`invoke`/`begin-session`/spend-door) parser exposes a flag that names or
  changes it (an AST proof + a behavioral proof + the "no add_argument names it" proof).
- **G4 coexistence** — the entitlement and the key assignments live in the SAME `config.yaml`
  without clobbering each other on any set/clear of either block.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_transport
from pipeline.spend import entitlement as E
from pipeline.spend.assignment import ScopeKey, config_path, load_store

# A recognizable sentinel: an entitled user is a NON-secret id, but assert no credential-shaped
# string ever surfaces in any output regardless.
SECRET_VALUE = "sk-ant-SUPER-SECRET-VALUE-do-not-log-0123456789abcdef"


# --- the check API: set → get, single-valued, pure equality ------------------------------------


def test_set_get_is_entitled_single_valued(tmp_path: Path) -> None:
    E.set_entitled_user(tmp_path, "dave")
    assert E.entitled_user(tmp_path) == "dave"
    assert E.is_entitled(tmp_path, "dave") is True
    assert E.is_entitled(tmp_path, "erin") is False


def test_reassign_replaces_never_two_entitled_users(tmp_path: Path) -> None:
    """Setting a second user REPLACES the first — the config never carries two entitled users."""
    E.set_entitled_user(tmp_path, "dave")
    E.set_entitled_user(tmp_path, "erin")
    assert E.entitled_user(tmp_path) == "erin"
    assert E.is_entitled(tmp_path, "erin") is True
    assert E.is_entitled(tmp_path, "dave") is False  # the prior entitlement is GONE (not additive)

    # Exactly ONE top-level `subscription_user:` line on disk (single-valued — never a 2nd entry).
    text = config_path(tmp_path).read_text(encoding="utf-8")
    key_lines = [ln for ln in text.splitlines() if ln.startswith("subscription_user:")]
    assert len(key_lines) == 1
    assert key_lines[0].strip() == "subscription_user: erin"


def test_clear_removes_entitlement(tmp_path: Path) -> None:
    E.set_entitled_user(tmp_path, "dave")
    E.clear_entitled_user(tmp_path)
    assert E.entitled_user(tmp_path) is None
    assert E.is_entitled(tmp_path, "dave") is False


def test_is_entitled_is_pure_equality_and_never_entitles_when_unset(tmp_path: Path) -> None:
    """An UNSET entitlement entitles NOBODY — incl. the `None == None` and empty-string traps."""
    assert E.entitled_user(tmp_path) is None
    assert E.is_entitled(tmp_path, "dave") is False
    assert E.is_entitled(tmp_path, None) is False  # None must never equal an unset entitlement.
    assert E.is_entitled(tmp_path, "") is False
    assert E.is_entitled(tmp_path, 123) is False  # a non-string user is never entitled.


# --- typed refuse: an invalid user segment writes NOTHING (§23) --------------------------------


@pytest.mark.parametrize("bad_user", ["../x", "Dave", "", "a/b", "..", "/abs"])
def test_invalid_user_segment_refuses_and_writes_nothing_api(bad_user: str, tmp_path: Path) -> None:
    with pytest.raises(E.InvalidUserError):
        E.set_entitled_user(tmp_path, bad_user)
    # NOTHING was written — no config file exists.
    assert not config_path(tmp_path).exists()


def test_invalid_user_does_not_clobber_an_existing_config(tmp_path: Path) -> None:
    """A refused set leaves any prior entitlement (and the whole config) untouched."""
    E.set_entitled_user(tmp_path, "dave")
    before = config_path(tmp_path).read_text(encoding="utf-8")
    with pytest.raises(E.InvalidUserError):
        E.set_entitled_user(tmp_path, "../evil")
    assert E.entitled_user(tmp_path) == "dave"  # still dave — the bad set changed nothing.
    assert config_path(tmp_path).read_text(encoding="utf-8") == before


# --- the CLI admin verbs: set / clear / show / list-keys ---------------------------------------


def test_cli_set_then_reassign_then_clear(tmp_path: Path, capsys) -> None:
    # set dave → announced + entitled.
    assert _cmd_transport(["set-subscription-user", "dave", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "dave" in out and "entitled subscription user is now" in out
    assert E.is_entitled(tmp_path, "dave") is True
    assert E.is_entitled(tmp_path, "erin") is False
    assert E.entitled_user(tmp_path) == "dave"

    # set erin → REPLACES dave (single-valued, swappable).
    assert _cmd_transport(["set-subscription-user", "erin", "--root", str(tmp_path)]) == 0
    assert "replaced" in capsys.readouterr().out.lower()
    assert E.is_entitled(tmp_path, "dave") is False  # dave is no longer entitled.
    assert E.is_entitled(tmp_path, "erin") is True

    # clear → None.
    assert _cmd_transport(["clear-subscription-user", "--root", str(tmp_path)]) == 0
    assert "removed" in capsys.readouterr().out
    assert E.entitled_user(tmp_path) is None


def test_cli_clear_is_idempotent(tmp_path: Path, capsys) -> None:
    assert _cmd_transport(["clear-subscription-user", "--root", str(tmp_path)]) == 0
    assert "no-op" in capsys.readouterr().out  # clearing an unset entitlement is a clean no-op.
    assert E.entitled_user(tmp_path) is None


def test_cli_set_invalid_user_refuses_exit_1_nothing_written(tmp_path: Path, capsys) -> None:
    code = _cmd_transport(["set-subscription-user", "../x", "--root", str(tmp_path)])
    assert code == 1
    assert "entitlement-bad-user" in capsys.readouterr().err
    assert not config_path(tmp_path).exists()


def test_cli_set_empty_user_refuses(tmp_path: Path, capsys) -> None:
    code = _cmd_transport(["set-subscription-user", "", "--root", str(tmp_path)])
    assert code == 1
    assert "entitlement-bad-user" in capsys.readouterr().err
    assert not config_path(tmp_path).exists()


def test_list_keys_surfaces_the_entitled_user(tmp_path: Path, capsys) -> None:
    _cmd_transport(["set-subscription-user", "dave", "--root", str(tmp_path)])
    capsys.readouterr()  # drain the set confirmation
    assert _cmd_transport(["list-keys", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "subscription user: dave" in out
    assert SECRET_VALUE not in out


def test_show_combined_view(tmp_path: Path, capsys) -> None:
    _cmd_transport(["set-subscription-user", "dave", "--root", str(tmp_path)])
    _cmd_transport(
        ["assign-key", "--scope", "user:dave", "--handle", "anthropic:acme",
         "--weekly-cap", "50", "--root", str(tmp_path)]
    )
    capsys.readouterr()
    assert _cmd_transport(["show", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "subscription user: dave" in out
    assert "user:dave" in out and "anthropic:acme" in out  # the assignment, never a secret.
    assert SECRET_VALUE not in out


def test_show_empty_is_clean(tmp_path: Path, capsys) -> None:
    assert _cmd_transport(["show", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "subscription user: (none" in out
    assert "key assignments: (none" in out


# --- I2/I3: the entitled user is admin-only — no run parameter can set or name it ---------------


def test_only_the_two_admin_verbs_mutate_the_entitlement() -> None:
    """AST proof: in `pipeline/__main__`, the ONLY functions that CALL the entitlement mutators
    (`set_entitled_user`/`clear_entitled_user`) are the two Tier-A admin helpers — no run/spend
    verb handler mutates it (I2/I3)."""
    import pipeline.__main__ as M

    src = Path(M.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    mutators = {"set_entitled_user", "clear_entitled_user"}
    callers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    fn = inner.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                    if name in mutators:
                        callers.add(node.name)
    assert callers == {
        "_transport_set_subscription_user",
        "_transport_clear_subscription_user",
    }, f"only the two admin verbs may set/clear the entitlement; found callers: {callers}"


def test_no_add_argument_names_the_subscription_user_as_a_flag() -> None:
    """I2/I3: the entitled user is a SUBCOMMAND (`set-subscription-user`), never an argument FLAG —
    so NO parser (run-verb or otherwise) exposes a `--subscription-user` a run could set."""
    import pipeline.__main__ as M

    src = Path(M.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "add_argument":
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        assert "subscription" not in arg.value.lower(), (
                            f"no add_argument may name the subscription user as a flag "
                            f"(found {arg.value!r}); the entitlement is admin-only (I2/I3)"
                        )


def test_run_verbs_cannot_name_the_subscription_user_and_set_nothing(tmp_path: Path) -> None:
    """Behavioral proof: passing `--subscription-user` to a run/spend verb is REJECTED (never a
    silent accept), and NOTHING sets the entitlement — it stays admin-only (I2/I3)."""
    from pipeline.__main__ import main

    for verb in ("generate", "invoke", "render", "outline", "preview"):
        argv = [verb, "--subscription-user", "dave", "--root", str(tmp_path)]
        try:
            rc = main(argv)
        except SystemExit as exc:  # argparse rejects the unknown flag → nonzero SystemExit.
            rc = exc.code if isinstance(exc.code, int) else 2
        assert rc != 0, f"{verb!r} unexpectedly accepted --subscription-user"
    # No run verb wrote an entitlement — it remains unset (set ONLY via the admin verb).
    assert E.entitled_user(tmp_path) is None


# --- G4 coexistence: entitlement + assignments share one config, no clobber ---------------------


def test_entitlement_and_assignments_coexist_without_clobbering(tmp_path: Path) -> None:
    # 1) assign a key, 2) set the entitled user, 3) assign ANOTHER key — nothing is dropped.
    assert _cmd_transport(
        ["assign-key", "--scope", "user:dave", "--handle", "anthropic:acme",
         "--weekly-cap", "50", "--root", str(tmp_path)]
    ) == 0
    assert _cmd_transport(["set-subscription-user", "dave", "--root", str(tmp_path)]) == 0
    assert _cmd_transport(
        ["assign-key", "--scope", "zone:dave/work", "--handle", "anthropic:zk",
         "--weekly-cap", "25", "--root", str(tmp_path)]
    ) == 0

    store = load_store(tmp_path)
    assert store.entitled_user == "dave"  # the entitlement survived the second assign-key.
    assert store.get(ScopeKey("user", "dave")).handle.handle == "anthropic:acme"
    assert store.get(ScopeKey("zone", "dave/work")).handle.handle == "anthropic:zk"

    # Clearing the entitlement leaves BOTH assignments intact.
    assert _cmd_transport(["clear-subscription-user", "--root", str(tmp_path)]) == 0
    store2 = load_store(tmp_path)
    assert store2.entitled_user is None
    assert len(store2.assignments) == 2

    # Re-set the entitlement, then clear a KEY — the entitlement is untouched.
    assert _cmd_transport(["set-subscription-user", "erin", "--root", str(tmp_path)]) == 0
    assert _cmd_transport(["clear-key", "--scope", "user:dave", "--root", str(tmp_path)]) == 0
    store3 = load_store(tmp_path)
    assert store3.entitled_user == "erin"
    assert len(store3.assignments) == 1


def test_config_round_trip_carries_both_blocks(tmp_path: Path) -> None:
    """A save→load round-trip of a store carrying BOTH an entitlement and assignments preserves
    both (one store, one renderer — the same config document)."""
    from decimal import Decimal

    from pipeline.spend.assignment import Assignment, AssignmentStore, parse_handle, save_store

    store = AssignmentStore(
        [Assignment(ScopeKey("user", "dave"), parse_handle("anthropic:acme"), Decimal("50"))],
        entitled_user="dave",
    )
    save_store(store, tmp_path)
    text = config_path(tmp_path).read_text(encoding="utf-8")
    assert "subscription_user: dave" in text
    assert "scope_level: user" in text and "scope_id: dave" in text

    reloaded = load_store(tmp_path)
    assert reloaded.entitled_user == "dave"
    assert reloaded.get(ScopeKey("user", "dave")).handle.handle == "anthropic:acme"


def test_config_lives_under_instance_ops_transport(tmp_path: Path) -> None:
    E.set_entitled_user(tmp_path, "dave")
    written = tmp_path / "instance" / "ops" / "transport" / "config.yaml"
    assert written.is_file()  # gitignored home (instance/ops/) → guard stays green.
    assert config_path(tmp_path) == written


# --- the module stays paid-selection-free (G5 stores + checks; it never spends) ----------------


def test_entitlement_module_imports_no_transport_or_generation() -> None:
    """entitlement.py imports the shared config store + the workspace-name guards — never the
    transport chokepoint, the driver, or any generation/paid-selection machinery (G5 is config +
    the U==entitled check only; selection/metering are G6/G7)."""
    source = Path(E.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = {
        "pipeline.transport",
        "pipeline.driver",
        "pipeline.compose",
        "pipeline.review",
        "pipeline.reconcile",
    }
    assert forbidden.isdisjoint(imported), f"entitlement.py must not import {forbidden & imported}"
    assert "pipeline.spend.assignment" in imported  # reuses the SAME config store (not a 2nd one)
    assert "pipeline.workspace_name" in imported  # validates the user segment (§23)


def test_entitlement_error_family_is_single_catchable_base() -> None:
    """Every typed entitlement refusal is an EntitlementError — one family the CLI catches."""
    assert issubclass(E.InvalidUserError, E.EntitlementError)
    assert issubclass(E.EntitlementError, RuntimeError)
