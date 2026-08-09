"""The 5-level `users/<user>/zones/<zone>/workspaces/<workspace>/` containment guard (§23 zones).

Design authority: `docs/design.md` §21.1 (isolation is enforced BY THE API, not by trust) +
§10 (client isolation is structural) + CLAUDE.md rule 2. Z2 landed `WorkspaceStore.at(..., zone=)`
(the path constructor); Z3 lands the ISOLATION/SECURITY gate — the zoned `validate_workspace_path`
and the extracted `validate_zone_segment`. Where the legacy 3-level validator contained TWO
caller-supplied segments (`<user>`, `<workspace>`), the zoned path nests a THIRD (`<zone>`) between
them under two more fixed joins (`zones/` per user, then `workspaces/` per zone), so a symlink or
`..` planted at ANY of the five levels cannot relocate the store root the §21.1 per-id gate
validates against.

This module is the CONTAINMENT MATRIX — the gate. Every case builds REAL symlinks inside
`tmp_path` (auto-cleaned) and asserts the guard REFUSES with the exact `(reason, segment)`; the
byte-identity cases pin that `zone=None` stays the legacy 3-level path unchanged and a `str` zone
agrees with `WorkspaceStore.at(..., zone=)` and `workspace_path(..., zone=)`.

**T1 (load-bearing security):** at both new FIXED joins the base is re-resolved FRESH from the
previous validated level — cases (a)/`test_L2_*` (a symlinked `zones/` planted in a user home) and
(d)/`test_L4_*` (a symlinked `workspaces/` planted in a zone home) prove a clean lowercase name is
still caught by the resolve step, not a lexical check.

All fixtures are generic (`optiquity`, `acme`, `self`, `default`, `zone-a`, `mvp-demo`, §7.4 literal
ids); no instance content.
"""

from __future__ import annotations

import os

import pytest

from pipeline.store import WorkspaceStore
from pipeline.workspace_name import (
    WorkspaceNameError,
    validate_workspace_path,
    validate_zone_segment,
    workspace_path,
)

#: Valid (user, zone, workspace) triples — the guard must accept every real lowercase id unchanged.
VALID_TRIPLES = (
    ("optiquity", "default", "mvp-demo"),
    ("acme", "staging", "ws"),
    ("self", "zone-a", "testws"),
    ("optiquity", "default", "workspace.template"),  # interior DOT allowed; only bare `..` is bad.
)

#: Not-a-safe-segment values — empty, traversal, absolute, embedded separator, bare dots, flag-like,
#: a smuggled-separator shape, and a string-form cross-tree traversal (refused by hygiene, NEVER
#: parsed as a path). Shared by the `zone` and `workspace` hygiene legs of the zoned path.
UNSAFE_SEGMENTS = (
    "",
    "..",
    ".",
    "/etc",
    "a/b",
    "foo/../bar",
    "-lead",
    "..%2f",
    "../../acme/zones/secret",
)


def _mkdirs(*paths) -> None:
    """Create every path as a directory (parents included) — the real-dir fixture builder."""
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# (h) + valid corpus — accepts every valid lowercase triple, existence-independent.
# ---------------------------------------------------------------------------


class TestValidateWorkspacePathZonedAccepts:
    @pytest.mark.parametrize(("user", "zone", "workspace"), VALID_TRIPLES)
    def test_returns_unresolved_five_level_path(self, tmp_path, user, zone, workspace):
        # Byte-identical to WorkspaceStore.at(root, user, workspace, zone=zone).root — the
        # UNRESOLVED users/<user>/zones/<zone>/workspaces/<workspace>.
        got = validate_workspace_path(tmp_path, user, workspace, zone=zone)
        assert got == tmp_path / "users" / user / "zones" / zone / "workspaces" / workspace

    def test_valid_zoned_path_with_real_dirs_returns_contained(self, tmp_path):
        # (h): a fully real (no-symlink) tree resolves and contains at every level.
        _mkdirs(tmp_path / "users" / "optiquity" / "zones" / "default" / "workspaces" / "mvp-demo")
        got = validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone="default")
        assert got == (
            tmp_path / "users" / "optiquity" / "zones" / "default" / "workspaces" / "mvp-demo"
        )

    @pytest.mark.parametrize(("user", "zone", "workspace"), VALID_TRIPLES)
    def test_validates_before_any_dir_exists(self, tmp_path, user, zone, workspace):
        # A brand-new home whose zoned path does not exist yet still validates (resolve is
        # existence-independent) — the store is created on demand later.
        assert not (tmp_path / "users").exists()
        assert validate_workspace_path(tmp_path, user, workspace, zone=zone) == (
            tmp_path / "users" / user / "zones" / zone / "workspaces" / workspace
        )


# ---------------------------------------------------------------------------
# (g) byte-identity — zone=None stays legacy 3-level; a str zone agrees with .at / workspace_path.
# ---------------------------------------------------------------------------


class TestZonedByteIdentity:
    @pytest.mark.parametrize(("user", "zone", "workspace"), VALID_TRIPLES)
    def test_agrees_with_store_at_and_workspace_path(self, tmp_path, user, zone, workspace):
        got = validate_workspace_path(tmp_path, user, workspace, zone=zone)
        assert got == WorkspaceStore.at(tmp_path, user, workspace, zone=zone).root
        assert got == workspace_path(tmp_path, user, workspace, zone=zone)

    @pytest.mark.parametrize(("user", "zone", "workspace"), VALID_TRIPLES)
    def test_zone_none_stays_legacy_three_level(self, tmp_path, user, zone, workspace):
        # zone=None MUST be byte-identical to the legacy 3-level path (no zones/ segment) and to
        # WorkspaceStore.at(...) with no zone — the compatibility scaffold every caller relies on.
        legacy = validate_workspace_path(tmp_path, user, workspace)
        assert legacy == tmp_path / "users" / user / "workspaces" / workspace
        assert legacy == WorkspaceStore.at(tmp_path, user, workspace).root
        assert legacy == workspace_path(tmp_path, user, workspace)

    def test_workspace_path_zoned_is_a_pure_join_with_parts(self, tmp_path):
        # workspace_path is a pure calculator: the zoned join threads zones/<zone>, appends parts.
        got = workspace_path(tmp_path, "optiquity", "mvp-demo", "sources", "cache", zone="default")
        assert got == (
            tmp_path / "users" / "optiquity" / "zones" / "default"
            / "workspaces" / "mvp-demo" / "sources" / "cache"
        )


# ---------------------------------------------------------------------------
# (c) + (f) hygiene — a malformed zone/workspace is refused before any containment resolve.
# ---------------------------------------------------------------------------


class TestZonedHygieneRejects:
    @pytest.mark.parametrize("zone", UNSAFE_SEGMENTS)
    def test_unsafe_zone_is_not_a_safe_segment(self, tmp_path, zone):
        # (c): `..`, absolute, embedded `/`, and friends — refused at the L3 zone hygiene gate.
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone=zone)
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "zone"

    @pytest.mark.parametrize("zone", ("Default", "ZONE", "Zone-A", "zoneUP"))
    def test_uppercase_zone_refused(self, tmp_path, zone):
        # (f): a non-lowercase zone is refused, never silently folded (W5).
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone=zone)
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "zone"

    @pytest.mark.parametrize("zone", ("", "  ", "a b", "\t"))
    def test_empty_or_whitespace_zone_refused(self, tmp_path, zone):
        # (f): the empty string and any whitespace-bearing zone are not a single safe segment.
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone=zone)
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "zone"

    def test_non_string_zone_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone=123)  # type: ignore[arg-type]
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "zone"

    @pytest.mark.parametrize("workspace", UNSAFE_SEGMENTS)
    def test_unsafe_workspace_still_refused_on_zoned_path(self, tmp_path, workspace):
        # L5 workspace hygiene still fires on the zoned path (a valid zone does not bypass it).
        _mkdirs(tmp_path / "users" / "optiquity" / "zones" / "default")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", workspace, zone="default")
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "workspace"

    def test_uppercase_workspace_refused_on_zoned_path(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "MVP", zone="default")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "workspace"


# ---------------------------------------------------------------------------
# The five resolve-and-contain levels — proven with REAL tmp symlinks (a)/(b)/(d)/(e) + L1.
# ---------------------------------------------------------------------------


class TestZonedContainment:
    def test_L1_symlinked_user_still_escapes_users_root(self, tmp_path):
        # L1 is shared with the legacy path: a symlinked `<user>` escaping users/ is caught first,
        # even on the zoned path (before any zone/workspace level is inspected).
        users = tmp_path / "users"
        outside = tmp_path / "outside"
        _mkdirs(users, outside)
        os.symlink(outside, users / "eviluser")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "eviluser", "mvp-demo", zone="default")
        assert exc.value.reason == "escapes-users-root"
        assert exc.value.segment == "user"

    def test_a_L2_symlinked_zones_escapes_user_root(self, tmp_path):
        # (a): the FIXED per-user zones/ dir is itself a symlink out of the user home. Only the L2
        # resolve-and-contain check catches it (T1: the zones/ base re-resolves the user home),
        # BEFORE any zone leaf is joined — a relocated zone BASE is fatal.
        owner = tmp_path / "users" / "optiquity"
        outside = tmp_path / "outside"
        _mkdirs(owner, outside)
        os.symlink(outside, owner / "zones")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone="default")
        assert exc.value.reason == "escapes-user-root"
        assert exc.value.segment == "zones"

    def test_b_L3_zone_symlink_into_other_users_zones_escapes_zones_root(self, tmp_path):
        # (b): a leaf zone symlink `optiquity/.../zones/evilzone` pointing into ANOTHER user's
        # zones/ (`acme/zones/secret`) would relocate the store into acme's tree, where the per-id
        # gate would then resolve acme's ids and PASS (a cross-user read). L3 refuses `evilzone`.
        _mkdirs(tmp_path / "users" / "optiquity" / "zones")
        acme_secret = tmp_path / "users" / "acme" / "zones" / "secret"
        _mkdirs(acme_secret)
        os.symlink(acme_secret, tmp_path / "users" / "optiquity" / "zones" / "evilzone")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone="evilzone")
        assert exc.value.reason == "escapes-zones-root"
        assert exc.value.segment == "zone"

    def test_c_zone_absolute_and_traversal_refused(self, tmp_path):
        # (c) at the whole-validator level: absolute and `..` zones never resolve into the tree.
        for zone in ("..", "/etc", "a/b"):
            with pytest.raises(WorkspaceNameError) as exc:
                validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone=zone)
            assert exc.value.reason == "not-a-safe-segment"
            assert exc.value.segment == "zone"

    def test_d_L4_symlinked_workspaces_escapes_zone_root(self, tmp_path):
        # (d): the FIXED per-zone workspaces/ dir under zones/<zone> is a symlink to a SIBLING
        # zone's workspaces/. Only L4 catches it (T1: the workspaces/ base re-resolves the
        # zones/<zone> home fresh), BEFORE any workspace leaf is joined — a relocated store BASE.
        za = tmp_path / "users" / "optiquity" / "zones" / "zone-a"
        zb_ws = tmp_path / "users" / "optiquity" / "zones" / "zone-b" / "workspaces"
        _mkdirs(za, zb_ws)
        os.symlink(zb_ws, za / "workspaces")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "mvp-demo", zone="zone-a")
        assert exc.value.reason == "escapes-zone-root"
        assert exc.value.segment == "workspaces"

    def test_e_L5_workspace_symlink_across_sibling_zones_escapes_workspaces_root(self, tmp_path):
        # (e): a leaf workspace symlink `zone-a/.../workspaces/evilws` pointing into a SIBLING
        # zone's workspaces/ (`zone-b/workspaces/secret`) would relocate the store into zone-b, a
        # cross-zone read. L5 refuses `evilws` BEFORE the store is built.
        za_ws = tmp_path / "users" / "optiquity" / "zones" / "zone-a" / "workspaces"
        zb_secret = tmp_path / "users" / "optiquity" / "zones" / "zone-b" / "workspaces" / "secret"
        _mkdirs(za_ws, zb_secret)
        os.symlink(zb_secret, za_ws / "evilws")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_workspace_path(tmp_path, "optiquity", "evilws", zone="zone-a")
        assert exc.value.reason == "escapes-workspaces-root"
        assert exc.value.segment == "workspace"


# ---------------------------------------------------------------------------
# validate_zone_segment — the extracted L3 zone hygiene + containment (reused per-zone).
# ---------------------------------------------------------------------------


class TestValidateZoneSegment:
    @pytest.mark.parametrize("zone", ("default", "staging", "zone-a", "z1", "workspace.template"))
    def test_returns_unresolved_zone_home(self, tmp_path, zone):
        # Byte-identical to the zones/<zone> prefix of WorkspaceStore.at(..., zone=zone).root.
        assert validate_zone_segment(tmp_path, "optiquity", zone) == (
            tmp_path / "users" / "optiquity" / "zones" / zone
        )

    def test_validates_before_zones_dir_exists(self, tmp_path):
        assert not (tmp_path / "users").exists()
        assert validate_zone_segment(tmp_path, "optiquity", "default") == (
            tmp_path / "users" / "optiquity" / "zones" / "default"
        )

    def test_uppercase_zone_refused(self, tmp_path):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_zone_segment(tmp_path, "optiquity", "Default")
        assert exc.value.reason == "not-lowercase"
        assert exc.value.segment == "zone"

    @pytest.mark.parametrize("zone", UNSAFE_SEGMENTS)
    def test_unsafe_zone_is_not_a_safe_segment(self, tmp_path, zone):
        with pytest.raises(WorkspaceNameError) as exc:
            validate_zone_segment(tmp_path, "optiquity", zone)
        assert exc.value.reason == "not-a-safe-segment"
        assert exc.value.segment == "zone"

    def test_symlinked_zone_escapes_zones_root(self, tmp_path):
        # (b) exercised directly on the extracted helper — a clean lowercase zone whose zones/
        # entry is a symlink OUT of zones/; only the resolve-and-contain step catches it.
        zones = tmp_path / "users" / "optiquity" / "zones"
        outside = tmp_path / "outside"
        _mkdirs(zones, outside)
        os.symlink(outside, zones / "evil")
        with pytest.raises(WorkspaceNameError) as exc:
            validate_zone_segment(tmp_path, "optiquity", "evil")
        assert exc.value.reason == "escapes-zones-root"
        assert exc.value.segment == "zone"
