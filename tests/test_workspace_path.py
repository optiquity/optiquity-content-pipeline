"""The 3-level `users/<user>/workspaces/<workspace>/` containment guard (§23 re-home).

Design authority: `docs/design.md` §21.1 (isolation is enforced BY THE API, not by trust) +
§10 (client isolation is structural) + CLAUDE.md rule 2, extended to the per-user re-home:
where the legacy `validate_workspace_name` contains ONE segment under a fixed `workspaces/`,
`validate_workspace_path` contains TWO caller-supplied segments — `<user>` then `<workspace>` —
each at its OWN resolve-and-contain level, so a symlink or `..` planted at any of the three
joins cannot relocate the store root the §21.1 per-id gate validates against. `user` and
`workspace` always arrive as SEPARATE arguments (never a slashed string), and every id is
case-insensitive (a non-lowercase spelling is refused, not silently folded — W5).

These tests pin the three containment levels with REAL tmp symlinks (mirroring the existing
`test_workspace_name.py` symlink cases) plus the lowercase rule. ADDITIVE: the legacy validator
and its tests stay green; no call site is converted here. All fixtures are generic (`optiquity`,
`acme`, `mvp-demo`, §7.4 literal ids); no instance content.
"""

from __future__ import annotations

import os

import pytest

from pipeline.workspace_name import (
    WorkspaceNameError,
    validate_user_segment,
    validate_workspace_path,
)

#: Valid (user, workspace) pairs — the guard must accept every real lowercase id unchanged.
VALID_PAIRS = (
    ("optiquity", "mvp-demo"),
    ("optiquity", "optiquitytrader"),
    ("acme", "ws"),
    ("self", "testws"),
    ("optiquity", "workspace.template"),  # interior DOT allowed; only bare `..` is traversal.
)

#: Not-a-safe-segment values — traversal, absolute, embedded separator, bare dots, flag-like,
#: and the string-form cross-user traversal (refused by hygiene, NEVER parsed as a path).
UNSAFE_SEGMENTS = (
    "..",
    ".",
    "/etc",
    "a/b",
    "foo/../bar",
    "-lead",
    "../../acme/workspaces/secret",
)


# ---------------------------------------------------------------------------
# validate_workspace_path — accepts every valid lowercase pair, existence-independent.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathAccepts:
    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_returns_unresolved_three_level_path(self, tmp_path, user, workspace):
        # Byte-identical to WorkspaceStore.at(framework_root, user, workspace).root — the
        # UNRESOLVED users/<user>/workspaces/<workspace> (behavior-neutral for the corpus).
        got = validate_workspace_path(tmp_path, user, workspace)
        assert got == tmp_path / "users" / user / "workspaces" / workspace

    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_validates_before_any_dir_exists(self, tmp_path, user, workspace):
        # A brand-new home whose users/<user>/workspaces/<workspace> does not exist yet still
        # validates (resolve is existence-independent) — the store is created on demand later.
        assert not (tmp_path / "users").exists()
        assert validate_workspace_path(tmp_path, user, workspace) == (
            tmp_path / "users" / user / "workspaces" / workspace
        )


# ---------------------------------------------------------------------------
# The case-insensitive-id rule (W5) — refuse any non-lowercase segment.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathLowercase:
    def test_uppercase_user_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "Optiquity", "mvp-demo")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "user"

    @pytest.mark.parametrize("workspace", ("WS", "Mvp-Demo"))
    def test_uppercase_workspace_refused(self, tmp_path, workspace):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", workspace)
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "workspace"

    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_lowercase_accepted(self, tmp_path, user, workspace):
        # The valid corpus is already lowercase — the rule accepts it unchanged.
        assert validate_workspace_path(tmp_path, user, workspace) == (
            tmp_path / "users" / user / "workspaces" / workspace
        )


# ---------------------------------------------------------------------------
# Hygiene — a malformed segment is refused before any containment resolve.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathHygieneRejects:
    @pytest.mark.parametrize("workspace", UNSAFE_SEGMENTS)
    def test_unsafe_workspace_is_not_a_safe_segment(self, tmp_path, workspace):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", workspace)
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "workspace"

    @pytest.mark.parametrize("user", UNSAFE_SEGMENTS)
    def test_unsafe_user_is_not_a_safe_segment(self, tmp_path, user):
        # The user segment is refused at L1 hygiene (before the workspace is even inspected).
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, user, "mvp-demo")
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "user"

    def test_non_string_workspace_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", 123)  # type: ignore[arg-type]
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "workspace"


# ---------------------------------------------------------------------------
# The three resolve-and-contain levels — proven with REAL tmp symlinks (L1/L2/L3).
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathContainment:
    def test_L1_symlinked_user_escapes_users_root(self, tmp_path):
        # `eviluser` is a CLEAN lowercase segment whose users/ entry is a symlink pointing
        # OUTSIDE users/. Only the L1 resolve-and-contain check catches it — proving the resolve
        # step (not a lexical check) is the real protection at the user level.
        users = tmp_path / "users"
        users.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(outside, users / "eviluser")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "eviluser", "mvp-demo")
        assert exc.value.reason == "escapes-users-root"
        assert exc.value.segment == "user"

    def test_L2_symlinked_workspaces_escapes_owner_root(self, tmp_path):
        # The FIXED per-owner workspaces/ dir is itself a symlink out of the owner home. L2
        # catches it before any workspace leaf is joined (a relocated store BASE is fatal).
        owner = tmp_path / "users" / "optiquity"
        owner.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(outside, owner / "workspaces")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo")
        assert exc.value.reason == "escapes-owner-root"
        assert exc.value.segment == "workspaces"

    def test_L3_leaf_symlink_into_sibling_user_escapes_workspaces_root(self, tmp_path):
        # The exploit L3 closes: a leaf symlink `optiquity/.../evilws` pointing into a SIBLING
        # user's tree (`acme/workspaces/secret`) would relocate the store root into acme's home,
        # where the per-id gate would then resolve acme's ids and PASS (a cross-user read). The
        # guard refuses `evilws` BEFORE the store is built — the door-level `../victim` proof, at
        # the re-home depth and across users.
        opt_ws = tmp_path / "users" / "optiquity" / "workspaces"
        opt_ws.mkdir(parents=True)
        acme_secret = tmp_path / "users" / "acme" / "workspaces" / "secret"
        acme_secret.mkdir(parents=True)
        os.symlink(acme_secret, opt_ws / "evilws")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "evilws")
        assert exc.value.reason == "escapes-workspaces-root"
        assert exc.value.segment == "workspace"


# ---------------------------------------------------------------------------
# validate_user_segment — the extracted L1 user hygiene + containment (reused per-user).
# ---------------------------------------------------------------------------


class TestValidateUserSegment:
    @pytest.mark.parametrize("user", ("optiquity", "acme", "self", "optiquitytrader"))
    def test_returns_unresolved_user_home(self, tmp_path, user):
        # Byte-identical to WorkspaceStore.user_root — the UNRESOLVED users/<user>.
        assert validate_user_segment(tmp_path, user) == tmp_path / "users" / user

    def test_validates_before_users_dir_exists(self, tmp_path):
        assert not (tmp_path / "users").exists()
        assert validate_user_segment(tmp_path, "optiquity") == tmp_path / "users" / "optiquity"

    def test_uppercase_user_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_user_segment(tmp_path, "Optiquity")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "user"

    @pytest.mark.parametrize("user", UNSAFE_SEGMENTS)
    def test_unsafe_user_is_not_a_safe_segment(self, tmp_path, user):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_user_segment(tmp_path, user)
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "user"

    def test_symlinked_user_escapes_users_root(self, tmp_path):
        # The L1 symlink escape, exercised directly on the extracted helper.
        users = tmp_path / "users"
        users.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(outside, users / "evil")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_user_segment(tmp_path, "evil")
        assert exc.value.reason == "escapes-users-root"
        assert exc.value.segment == "user"
