"""Key assignments + the workspace→zone→user→global cascade (plan G4, §21.10, M3/S3).

Proves the G4 gate WITHOUT any spend (no transport is selected, no secret is resolved into a
spawn, nothing meters — those are G6/G7). Every test writes only under a pytest `tmp_path`:

- **cascade precedence** — a workspace assignment beats a zone beats a user beats global
  (`cascade_key` returns the most-specific match up the chain, else `None`).
- **zone rung / user isolation** — the zone rung sits BETWEEN workspace and user; a same-named
  zone under a DIFFERENT user is a DISTINCT assignment (`dave/work` ≠ `erin/work`) because the
  scope-id carries the user.
- **fall-through** — an unassigned `(user, zone, workspace)` resolves to `None` (→ subscription).
- **S3 — no uncapped key** — `transport assign-key` WITHOUT `--weekly-cap` refuses (non-zero exit)
  and writes NOTHING.
- **CLI round-trip** — `assign-key … --weekly-cap 50` then `list-keys` shows scope + handle + cap
  (NEVER a secret, even when a secret is stored under that handle); `cascade_key` resolves it.
- **M3 — the scope-id is stored EXPLICITLY, never derived from a `users/` path** — a config
  round-trip proves the `(scope-level, scope-id)` keying; the cascade resolves purely from the
  identity triple with NO `users/` directory on disk.
- **home / gitignore** — the config lives at `instance/ops/transport/config.yaml` (gitignored;
  `check-no-content.sh` stays green because nothing there is tracked).
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_transport
from pipeline.spend import assignment as A
from pipeline.spend.assignment import (
    INSTALL_SCOPE_ID,
    TRANSPORT_CONFIG_RELPATH,
    Assignment,
    AssignmentError,
    AssignmentStore,
    ConfigError,
    InvalidCapError,
    ScopeKey,
    ScopeParseError,
    config_path,
    load_store,
    parse_handle,
    parse_scope,
)
from pipeline.spend.keystore import FileSecretBackend, SecretRef

# A recognizable, high-entropy sentinel: if it EVER surfaces in list-keys output or the config
# file, the "no secret" tests fail LOUDLY on the exact string.
SECRET_VALUE = "sk-ant-SUPER-SECRET-VALUE-do-not-log-0123456789abcdef"


def _assignment(level: str, scope_id: str, handle: str, cap: str) -> Assignment:
    return Assignment(ScopeKey(level, scope_id), parse_handle(handle), Decimal(cap))


# --- cascade precedence: workspace → zone → user → global --------------------------------------


def _four_level_store() -> AssignmentStore:
    """A store with ALL FOUR rungs assigned for dave/work/widgets, each a distinct handle."""
    return AssignmentStore(
        [
            _assignment("global", INSTALL_SCOPE_ID, "anthropic:glob", "10"),
            _assignment("user", "dave", "anthropic:user", "20"),
            _assignment("zone", "dave/work", "anthropic:zone", "30"),
            _assignment("workspace", "dave/work/widgets", "anthropic:ws", "40"),
        ]
    )


def test_workspace_beats_zone_beats_user_beats_global() -> None:
    store = _four_level_store()
    # Most-specific wins: the workspace assignment.
    assert store.cascade_key("dave", "work", "widgets").handle.handle == "anthropic:ws"


def test_zone_beats_user_beats_global_for_other_workspace() -> None:
    store = _four_level_store()
    # No workspace rung for "other" → the ZONE assignment (dave/work) wins.
    assert store.cascade_key("dave", "work", "other").handle.handle == "anthropic:zone"


def test_user_beats_global_for_other_zone() -> None:
    store = _four_level_store()
    # No workspace/zone rung for a different zone → the USER assignment wins.
    assert store.cascade_key("dave", "home", "anything").handle.handle == "anthropic:user"


def test_global_wins_for_other_user() -> None:
    store = _four_level_store()
    # A wholly different user matches only the install-wide GLOBAL assignment.
    assert store.cascade_key("erin", "work", "widgets").handle.handle == "anthropic:glob"


def test_zone_rung_sits_between_workspace_and_user() -> None:
    """The zone rung is consulted AFTER workspace and BEFORE user (the §23 zone fold-in)."""
    store = AssignmentStore(
        [
            _assignment("user", "dave", "anthropic:user", "20"),
            _assignment("zone", "dave/work", "anthropic:zone", "30"),
        ]
    )
    # A concrete workspace with no ws-rung: zone beats user.
    assert store.cascade_key("dave", "work", "widgets").handle.handle == "anthropic:zone"
    # A different zone under the same user: falls through zone → user.
    assert store.cascade_key("dave", "play", "widgets").handle.handle == "anthropic:user"


# --- same-named zone under different users = DISTINCT (user carried in the scope-id) ------------


def test_same_named_zone_under_different_users_is_distinct() -> None:
    store = AssignmentStore(
        [
            _assignment("zone", "dave/work", "anthropic:dave-work", "50"),
            _assignment("zone", "erin/work", "anthropic:erin-work", "60"),
        ]
    )
    # Same zone NAME ("work"), different owning user → DISTINCT assignments.
    assert store.cascade_key("dave", "work", None).handle.handle == "anthropic:dave-work"
    assert store.cascade_key("erin", "work", None).handle.handle == "anthropic:erin-work"
    # The two scope-ids are genuinely different keys.
    assert ScopeKey("zone", "dave/work") != ScopeKey("zone", "erin/work")


# --- fall-through: an unassigned (user, zone, workspace) → None (→ subscription at G7) ----------


def test_unassigned_resolves_to_none() -> None:
    assert AssignmentStore().cascade_key("nobody", "nozone", "nows") is None
    # A populated store WITHOUT a global rung still returns None for an unrelated identity
    # (nothing catches it → the subscription fallback resolved at G7).
    store = AssignmentStore(
        [
            _assignment("user", "dave", "anthropic:user", "20"),
            _assignment("zone", "dave/work", "anthropic:zone", "30"),
            _assignment("workspace", "dave/work/widgets", "anthropic:ws", "40"),
        ]
    )
    assert store.cascade_key("stranger", "elsewhere", "somewhere") is None


# --- M3: the scope-id is stored EXPLICITLY, NEVER derived from a users/ path --------------------


def test_cascade_keys_off_identity_not_filesystem(tmp_path: Path) -> None:
    """M3: resolution builds each candidate scope-id from the EXPLICIT identity triple — there is
    NO users/<u>/zones/<z>/… directory on disk, yet the cascade resolves the zone assignment."""
    store = AssignmentStore([_assignment("zone", "dave/work", "anthropic:acme", "50")])
    # Nothing exists under tmp_path/users — the scope-id was never split off a store path.
    assert not (tmp_path / "users").exists()
    assert store.cascade_key("dave", "work", "widgets").handle.handle == "anthropic:acme"


def test_config_round_trip_preserves_explicit_scope_keying(tmp_path: Path) -> None:
    """A save→load round-trip proves the (scope-level, scope-id) keying is stored EXPLICITLY."""
    store = AssignmentStore(
        [
            _assignment("global", INSTALL_SCOPE_ID, "anthropic:glob", "10"),
            _assignment("user", "dave", "anthropic:user", "20"),
            _assignment("zone", "dave/work", "anthropic:zone", "30"),
            _assignment("workspace", "dave/work/widgets", "anthropic:ws", "40.50"),
        ]
    )
    A.save_store(store, tmp_path)
    text = config_path(tmp_path).read_text(encoding="utf-8")
    # The scope-level AND the explicit scope-id are literally on disk (never a derived path).
    assert "scope_level: workspace" in text
    assert "scope_id: dave/work/widgets" in text
    assert "scope_level: zone" in text and "scope_id: dave/work" in text

    reloaded = load_store(tmp_path)
    ws = reloaded.get(ScopeKey("workspace", "dave/work/widgets"))
    assert ws is not None and ws.handle.handle == "anthropic:ws"
    assert ws.weekly_cap_usd == Decimal("40.50")  # exact Decimal round-trip
    # The whole set round-trips key-for-key.
    assert {a.scope for a in reloaded.assignments} == {a.scope for a in store.assignments}


# --- config home + gitignore-friendliness ------------------------------------------------------


def test_config_lives_under_instance_ops_transport(tmp_path: Path) -> None:
    assert TRANSPORT_CONFIG_RELPATH == Path("instance") / "ops" / "transport" / "config.yaml"
    assert config_path(tmp_path) == tmp_path / "instance" / "ops" / "transport" / "config.yaml"
    A.save_store(AssignmentStore([_assignment("user", "dave", "anthropic:x", "5")]), tmp_path)
    written = tmp_path / "instance" / "ops" / "transport" / "config.yaml"
    assert written.is_file()  # under instance/ops/ (gitignored in the real repo → guard green)


# --- the transport CLI: assign-key / list-keys / clear-key -------------------------------------


def test_assign_key_without_weekly_cap_refuses_and_writes_nothing(tmp_path, capsys) -> None:
    """S3: a missing --weekly-cap is a non-zero refusal with NOTHING written (no uncapped key)."""
    argv = [
        "assign-key",
        "--scope",
        "zone:dave/work",
        "--handle",
        "anthropic:acme",
        "--root",
        str(tmp_path),
    ]
    code = _cmd_transport(argv)
    assert code != 0  # non-zero exit (S3 refusal)
    err = capsys.readouterr().err
    assert "--weekly-cap is REQUIRED" in err and "S3" in err
    # NOTHING was written — the config file does not exist.
    assert not config_path(tmp_path).exists()


def test_assign_then_list_shows_scope_handle_cap_no_secret(tmp_path, capsys) -> None:
    """assign-key then list-keys shows scope + handle + cap; NEVER the secret, even though a secret
    IS stored under the handle in the keystore; cascade_key then resolves the assignment."""
    # Store a real secret under the handle in an out-of-repo keystore (proves list-keys is
    # secret-free even when the secret exists).
    backend = FileSecretBackend(tmp_path / "secrets")
    backend.store(SecretRef.parse("anthropic:acme"), SECRET_VALUE)

    code = _cmd_transport(
        [
            "assign-key",
            "--scope",
            "zone:dave/work",
            "--handle",
            "anthropic:acme",
            "--weekly-cap",
            "50",
            "--root",
            str(tmp_path),
        ]
    )
    assert code == 0
    capsys.readouterr()  # drain the assign confirmation

    assert _cmd_transport(["list-keys", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "zone:dave/work" in out
    assert "anthropic:acme" in out  # the HANDLE (a non-secret reference) is shown
    assert "50" in out  # the weekly cap is shown
    assert SECRET_VALUE not in out  # the secret VALUE never appears

    # The config file on disk is likewise secret-free.
    assert SECRET_VALUE not in config_path(tmp_path).read_text(encoding="utf-8")

    # The written assignment resolves through the cascade for ANY workspace in that zone.
    resolved = load_store(tmp_path).cascade_key("dave", "work", "widgets")
    assert resolved is not None and resolved.handle.handle == "anthropic:acme"
    assert resolved.weekly_cap_usd == Decimal("50")
    # A different user's same-named zone does NOT resolve to it.
    assert load_store(tmp_path).cascade_key("erin", "work", "widgets") is None


def test_list_keys_empty_is_clean(tmp_path, capsys) -> None:
    assert _cmd_transport(["list-keys", "--root", str(tmp_path)]) == 0
    assert "no key assignments" in capsys.readouterr().out


def test_clear_key_is_idempotent(tmp_path, capsys) -> None:
    _cmd_transport(
        [
            "assign-key",
            "--scope",
            "user:dave",
            "--handle",
            "anthropic:acme",
            "--weekly-cap",
            "25",
            "--root",
            str(tmp_path),
        ]
    )
    capsys.readouterr()
    # First clear removes it.
    assert _cmd_transport(["clear-key", "--scope", "user:dave", "--root", str(tmp_path)]) == 0
    assert "removed" in capsys.readouterr().out
    assert load_store(tmp_path).get(ScopeKey("user", "dave")) is None
    # Second clear is a clean no-op (idempotent, still exit 0).
    assert _cmd_transport(["clear-key", "--scope", "user:dave", "--root", str(tmp_path)]) == 0
    assert "no-op" in capsys.readouterr().out


def test_assign_key_global_falls_through_cascade(tmp_path, capsys) -> None:
    code = _cmd_transport(
        [
            "assign-key",
            "--scope",
            "global",
            "--handle",
            "anthropic:house",
            "--weekly-cap",
            "100",
            "--root",
            str(tmp_path),
        ]
    )
    assert code == 0
    # An install-wide global assignment resolves for an arbitrary identity.
    resolved = load_store(tmp_path).cascade_key("anyone", "anyzone", "anyws")
    assert resolved is not None and resolved.handle.handle == "anthropic:house"
    assert resolved.scope == ScopeKey("global", INSTALL_SCOPE_ID)


# --- refusals: bad scope / bad cap / bad handle / malformed config -----------------------------


@pytest.mark.parametrize(
    "scope",
    [
        "zone:dave",  # zone needs <u>/<z>
        "zone:dave/work/extra",  # too many segments
        "workspace:dave/work",  # workspace needs <u>/<z>/<ws>
        "user:Dave",  # uppercase segment refused (§23 lowercase rule)
        "bogus:x",  # unknown level
        "",  # empty
    ],
)
def test_parse_scope_refuses_malformed(scope: str, tmp_path: Path) -> None:
    with pytest.raises(ScopeParseError):
        parse_scope(scope, framework_root=tmp_path)


@pytest.mark.parametrize("cap", ["0", "-5", "abc", "$-1"])
def test_parse_weekly_cap_refuses_non_positive(cap: str) -> None:
    with pytest.raises(InvalidCapError):
        A.parse_weekly_cap(cap)


def test_parse_weekly_cap_accepts_dollar_and_commas() -> None:
    assert A.parse_weekly_cap("$1,000") == Decimal("1000")
    assert A.parse_weekly_cap("49.50") == Decimal("49.50")


def test_assign_key_bad_scope_refuses(tmp_path, capsys) -> None:
    code = _cmd_transport(
        [
            "assign-key",
            "--scope",
            "zone:dave",  # malformed
            "--handle",
            "anthropic:acme",
            "--weekly-cap",
            "50",
            "--root",
            str(tmp_path),
        ]
    )
    assert code == 1
    assert "assignment-bad-scope" in capsys.readouterr().err
    assert not config_path(tmp_path).exists()


def test_malformed_config_refuses_loudly(tmp_path: Path) -> None:
    path = config_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # An uncapped assignment on disk is a loud ConfigError (S3 holds on read, too).
    path.write_text(
        "format: transport-config/1\n"
        "assignments:\n"
        "  - scope_level: user\n"
        "    scope_id: dave\n"
        "    handle: anthropic:acme\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        load_store(tmp_path)


# --- the module stays paid-selection-free (G4 stores + resolves; it never spends) --------------


def test_assignment_module_imports_no_transport_or_generation() -> None:
    """assignment.py imports the keystore + the workspace-name guards + yamlio — never the
    transport chokepoint, the driver, or any generation/paid-selection machinery (G4 is config
    + cascade only; selection/metering are G6/G7)."""
    source = Path(A.__file__).read_text(encoding="utf-8")
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
    assert forbidden.isdisjoint(imported), f"assignment.py must not import {forbidden & imported}"
    # It DOES resolve handles via the shared keystore SecretRef and validates zone segments.
    assert "pipeline.spend.keystore" in imported
    assert "pipeline.workspace_name" in imported


def test_assignment_error_family_is_single_catchable_base() -> None:
    """Every typed assignment refusal is an AssignmentError — one family the CLI catches."""
    assert issubclass(ScopeParseError, AssignmentError)
    assert issubclass(InvalidCapError, AssignmentError)
    assert issubclass(ConfigError, AssignmentError)
