"""The zoned `users/<user>/zones/<zone>/workspaces/<workspace>/` containment guard (§23 re-home).

Design authority: `docs/design.md` §21.1 (isolation is enforced BY THE API, not by trust) +
§10 (client isolation is structural) + CLAUDE.md rule 2. Z4 (the atomic cutover) made `zone`
REQUIRED on `validate_workspace_path` / `workspace_path` / `WorkspaceStore.at`, so the validator is
now ALWAYS the 5-level zoned path — there is no legacy 3-level branch.

This module is the UNIT home for the `<user>` + `<workspace>` hygiene/lowercase rules and the L1
user containment level (a symlinked `<user>` escaping `users/`), plus the reusable
`validate_user_segment`. The COMPLETE five-level containment matrix (L1-L5, the zoned `zones/` and
per-zone `workspaces/` joins, and the leaf zone/workspace symlink escapes) lives in
`test_workspace_name_zone.py`. All fixtures are generic (`optiquity`, `acme`, `mvp-demo`, §7.4
literal ids); no instance content.
"""

from __future__ import annotations

import os

import pytest

from pipeline.workspace_name import (
    WorkspaceNameError,
    validate_user_segment,
    validate_workspace_path,
)

#: Valid (user, workspace) pairs — the guard must accept every real lowercase id unchanged (all
#: exercised under the default zone; the zoned matrix in test_workspace_name_zone.py sweeps zones).
VALID_PAIRS = (
    ("optiquity", "mvp-demo"),
    ("optiquity", "optiquitytrader"),
    ("acme", "ws"),
    ("self", "testws"),
    ("optiquity", "workspace.template"),  # interior DOT allowed; only bare `..` is traversal.
)

#: Not-a-safe-segment values — the empty string, traversal, absolute, embedded separator, bare
#: dots, flag-like, and the string-form cross-user traversal (refused by hygiene, NEVER parsed as a
#: path). The empty string is the ONE unit case ported from the removed legacy validator's reject
#: set (B9): `_SAFE_SEGMENT` requires >=1 char, so a blank segment can never name a directory.
UNSAFE_SEGMENTS = (
    "",  # ported from the removed legacy validator's reject set (B9) — a blank is not a segment.
    "..",
    ".",
    "/etc",
    "a/b",
    "foo/../bar",
    "-lead",
    "../../acme/workspaces/secret",
)


# ---------------------------------------------------------------------------
# Z4: `zone` is REQUIRED — a forgotten zone is a LOUD TypeError (never a silent 3-level path).
# ---------------------------------------------------------------------------


class TestZoneIsRequired:
    def test_missing_zone_is_a_loud_type_error(self, tmp_path):
        with pytest.raises(TypeError):
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# validate_workspace_path — accepts every valid lowercase pair, existence-independent.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathAccepts:
    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_returns_unresolved_five_level_path(self, tmp_path, user, workspace):
        # Byte-identical to WorkspaceStore.at(root, user, workspace, zone=zone).root — the
        # UNRESOLVED users/<user>/zones/<zone>/workspaces/<workspace>.
        got = validate_workspace_path(tmp_path, user, workspace, zone="default")
        assert got == tmp_path / "users" / user / "zones" / "default" / "workspaces" / workspace

    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_validates_before_any_dir_exists(self, tmp_path, user, workspace):
        # A brand-new home whose zoned path does not exist yet still validates (resolve is
        # existence-independent) — the store is created on demand later.
        assert not (tmp_path / "users").exists()
        assert validate_workspace_path(tmp_path, user, workspace, zone="default") == (
            tmp_path / "users" / user / "zones" / "default" / "workspaces" / workspace
        )


# ---------------------------------------------------------------------------
# The case-insensitive-id rule (W5) — refuse any non-lowercase segment.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathLowercase:
    def test_uppercase_user_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "Optiquity", "mvp-demo", zone="default")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "user"

    @pytest.mark.parametrize("workspace", ("WS", "Mvp-Demo"))
    def test_uppercase_workspace_refused(self, tmp_path, workspace):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", workspace, zone="default")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "workspace"

    @pytest.mark.parametrize(("user", "workspace"), VALID_PAIRS)
    def test_lowercase_accepted(self, tmp_path, user, workspace):
        # The valid corpus is already lowercase — the rule accepts it unchanged.
        assert validate_workspace_path(tmp_path, user, workspace, zone="default") == (
            tmp_path / "users" / user / "zones" / "default" / "workspaces" / workspace
        )


# ---------------------------------------------------------------------------
# Hygiene — a malformed segment is refused before any containment resolve.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathHygieneRejects:
    @pytest.mark.parametrize("workspace", UNSAFE_SEGMENTS)
    def test_unsafe_workspace_is_not_a_safe_segment(self, tmp_path, workspace):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", workspace, zone="default")
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "workspace"

    @pytest.mark.parametrize("user", UNSAFE_SEGMENTS)
    def test_unsafe_user_is_not_a_safe_segment(self, tmp_path, user):
        # The user segment is refused at L1 hygiene (before the workspace is even inspected).
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, user, "mvp-demo", zone="default")
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "user"

    def test_non_string_workspace_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", 123, zone="default")  # type: ignore[arg-type]
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "workspace"


# ---------------------------------------------------------------------------
# L1 containment — the user level, shared with the zoned path (proven with a REAL tmp symlink).
# The zoned L2-L5 levels (zones/, per-zone workspaces/, leaf zone/workspace) live in
# test_workspace_name_zone.py.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathContainment:
    def test_L1_symlinked_user_escapes_users_root(self, tmp_path):
        # `eviluser` is a CLEAN lowercase segment whose users/ entry is a symlink pointing
        # OUTSIDE users/. Only the L1 resolve-and-contain check catches it (before any zone or
        # workspace level is inspected) — proving the resolve step (not a lexical check) protects.
        users = tmp_path / "users"
        users.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(outside, users / "eviluser")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "eviluser", "mvp-demo", zone="default")
        assert exc.value.reason == "escapes-users-root"
        assert exc.value.segment == "user"


# ---------------------------------------------------------------------------
# validate_user_segment — the extracted L1 user hygiene + containment (reused per-user; zone-free).
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
