"""Z2 / §23: `WorkspaceStore` gains ZONE identity — additive, keyword-only, `zone=None` unchanged.

Design authority: the zone restructure (a zone groups a user's workspaces under
`users/<user>/zones/<zone>/workspaces/<workspace>`, so a zone sits BETWEEN user and workspace;
`ZONES_DIRNAME`/`DEFAULT_ZONE` land in `pipeline.workspace_name` in Z1). Z2 teaches the ONLY
layout-aware constructor — `WorkspaceStore.at(...)` — to record a zone, WITHOUT disturbing any
existing caller:

- **`zone is None` (the default)** builds the legacy 3-level root, BYTE-IDENTICAL to the pre-Z2
  `.at(...)` output — a compatibility scaffold every current caller relies on (none pass `zone`
  yet). Z4 later removes this branch once the zone becomes required.
- **`zone` is a `str`** builds the 4-level `users/<user>/zones/<zone>/workspaces/<workspace>` root
  and records it, exposed via a raise-loud `.zone` property mirroring `.user`/`.workspace`.

`zone` is KEYWORD-ONLY, so no positional caller can accidentally pass it. `.at` does NOT validate
`zone` (the `validate_zone_segment` hygiene/containment gate is Z3) — these tests pin path SHAPE
and identity recording only. All fixtures are generic (`u`/`w`/`z`, §7.4); no instance content.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline.store import WorkspaceStore, WorkspaceStoreIdentityError
from pipeline.workspace_name import USERS_DIRNAME, WORKSPACES_DIRNAME, ZONES_DIRNAME


def test_at_zone_none_root_is_byte_identical_to_the_legacy_three_level():
    # zone=None is the compatibility scaffold: the root MUST match the pre-Z2 `.at` output exactly.
    r = "/instance/fw"
    store = WorkspaceStore.at(r, "u", "w")
    assert store.root == Path(r) / "users" / "u" / "workspaces" / "w"
    # ...and via the layout literals, pinning the exact 3-level shape (no zone segment inserted):
    assert store.root == Path(r) / USERS_DIRNAME / "u" / WORKSPACES_DIRNAME / "w"


def test_at_with_zone_builds_the_four_level_root_and_records_the_zone():
    r = "/instance/fw"
    store = WorkspaceStore.at(r, "u", "w", zone="z")
    assert store.root == Path(r) / "users" / "u" / "zones" / "z" / "workspaces" / "w"
    # ...and via the layout literals (the zone segment sits BETWEEN user and workspaces):
    assert (
        store.root
        == Path(r) / USERS_DIRNAME / "u" / ZONES_DIRNAME / "z" / WORKSPACES_DIRNAME / "w"
    )
    assert store.zone == "z"


def test_zone_none_at_store_has_no_zone_recorded_so_accessor_raises_loud():
    # zone=None means "no zone recorded" → `.zone` raises exactly like `.workspace` on a bare
    # store (the raise-loud identity contract; never a silent None), even though `.workspace`
    # IS recorded on this same store.
    store = WorkspaceStore.at("/instance/fw", "u", "w")
    assert store.workspace == "w"  # identity IS recorded for a zone=None `.at` store...
    with pytest.raises(WorkspaceStoreIdentityError):
        _ = store.zone  # ...but the zone is not, so reading it is refused loudly.


def test_bare_store_zone_accessor_raises_workspace_store_identity_error():
    # A bare `WorkspaceStore(root)` (production's positional construction + the test-injection
    # seam) carries NO identity — `.zone` raises, never returns None, matching the other accessors.
    bare = WorkspaceStore(Path("/instance/fw/users/u/workspaces/w"))
    with pytest.raises(WorkspaceStoreIdentityError):
        _ = bare.zone


def test_zone_is_keyword_only_a_positional_fourth_arg_is_a_type_error():
    # KEYWORD-ONLY: no positional caller can pass zone by accident (the `*` in `.at`'s signature).
    with pytest.raises(TypeError):
        WorkspaceStore.at("/instance/fw", "u", "w", "z")  # type: ignore[misc]
