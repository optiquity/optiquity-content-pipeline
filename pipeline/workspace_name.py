"""The workspace-name containment guard — isolation enforced at the store ROOT.

Design authority: `docs/design.md` §21.1 (isolation is enforced BY THE API, not by trust —
"every call carries `workspace` and … every id must resolve inside that workspace") and §10
(client isolation is structural), plus CLAUDE.md rule 2 (client isolation via workspaces).

**Why this exists.** A door builds a workspace store root as `<root>/workspaces/<workspace>`
from a CALLER-SUPPLIED name. The §21.1 isolation gate then validates every referenced id
against THAT store root. But a raw name is not automatically a single, contained path
segment: `workspace="../other-client"`, an absolute path (`"/etc"`), or a symlink escape
(`workspaces/evil` → outside) would MOVE the store root itself — so a referenced id would
resolve inside the WRONG workspace and pass the per-id gate. The invariant "isolation is
enforced by the API, not by trust" is therefore FALSE for the workspace root until the name
is validated. This module is the single **resolve-and-contain** guard every door calls
BEFORE constructing the store, so the guarantee holds at the root as well as per-id.

**Two complementary checks:**

1. **PRIMARY — resolve-and-contain (the real protection).** The resolved candidate store
   root must be a DIRECT CHILD of the resolved `<root>/workspaces/`
   (`candidate.resolve().parent == base.resolve()`). Resolving both sides catches `..`,
   absolute paths, AND symlink escapes deterministically, and is existence-independent
   (a not-yet-created workspace still validates — `Path.resolve(strict=False)` resolves the
   existing prefix and normalizes the rest).
2. **SECONDARY — hygiene shape check.** The name must be a single safe path segment. This
   refuses malformed-but-contained names a clean-segment attacker could smuggle (a name with
   a separator that normalizes back inside, a leading `-` that looks like a CLI flag, other
   unsafe characters). The charset is derived from EVERY existing workspace name so no valid
   name breaks — see `_SAFE_SEGMENT`.

The module imports nothing from `pipeline` (no cycle risk) and touches no filesystem state:
it only inspects and resolves paths. It never creates or names a workspace — placement stays
the caller's (see `pipeline.store.WorkspaceStore`).
"""

from __future__ import annotations

import re
from pathlib import Path

__all__ = [
    "DEFAULT_ZONE",
    "USERS_DIRNAME",
    "WORKSPACES_DIRNAME",
    "WorkspaceNameError",
    "ZONES_DIRNAME",
    "validate_user_segment",
    "validate_workspace_path",
    "workspace_path",
]

#: The single directory every client workspace lives under (CLAUDE.md rule 2; §23). This module
#: is the ONE home for the layout directory-name literals: `pipeline.m1` and
#: `pipeline.adapters.fsast` import these rather than redefining them (it imports only
#: `re`/`pathlib`, so no import cycle).
WORKSPACES_DIRNAME = "workspaces"

#: The per-user home directory workspaces are being re-homed under
#: (`users/<user>/workspaces/<workspace>/`). Defined here alongside `WORKSPACES_DIRNAME` as the
#: single source for the layout literals; consumed by the later re-home increments (it is NOT
#: yet referenced by any path-building code — B1/B2 are behavior-neutral prep).
USERS_DIRNAME = "users"

#: The zone directory literals. A zone groups a user's workspaces — they live under
#: `users/<user>/zones/<zone>/workspaces/` — so a zone sits BETWEEN user and workspace.
#: `ZONES_DIRNAME` is the directory the zones live under and `DEFAULT_ZONE` is the zone used when
#: a request names none. Defined here alongside `USERS_DIRNAME` / `WORKSPACES_DIRNAME` as the
#: single source for the layout literals; consumed by the later zone-restructure increments (they
#: are NOT yet referenced by any path-building code — Z1 is behavior-neutral prep).
ZONES_DIRNAME = "zones"
DEFAULT_ZONE = "default"

#: A valid workspace name is one safe path segment. The charset is DERIVED from the existing
#: corpus so nothing legitimate breaks: every real workspace dir (`mvp-demo`,
#: `optiquitytrader`, `workspace.template` — note the INTERIOR dot) and every generic test
#: label (`wsA`/`wsB`/`testws`/`self`/`acme`) matches. The first character is a letter, digit,
#: or underscore — which rejects a bare `.`/`..` (traversal) and a leading `-` (flag-like);
#: the remainder additionally allows the interior `.`/`-`. No `/` or other separator can
#: appear, and the empty string does not match. `\Z` anchors the whole string (no embedded
#: newline). This is HYGIENE — the resolve-and-contain check below is the real protection.
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*\Z")

#: A path segment cannot exceed 255 bytes on the target filesystems (§7.4 filename discipline
#: applies equally to the workspace directory name).
_MAX_SEGMENT_BYTES = 255


class WorkspaceNameError(ValueError):
    """The invoked workspace name is not a safe, contained store-root segment (§10/§21.1).

    Mirrors `pipeline.api.token.InvalidTokenError`'s `reason`/`detail` shape so a door can
    surface the machine `reason` in a result's `context` and the human `detail` as its
    `hint`.

    `reason` is one of:

    - `not-a-safe-segment` — hygiene: not a single safe path segment (`_check_segment_ci`).
    - `not-lowercase` — hygiene: a segment carrying an uppercase letter, refused by the
      case-insensitive-id rule (W5; `_check_segment_ci`, on both the `user` and `workspace` legs).
    - `escapes-workspaces-root` — resolve-and-contain: the leaf `workspace` escapes its owner's
      `workspaces/` (`validate_workspace_path` L3).
    - `escapes-users-root` — the owner dir escapes `users/` (`validate_workspace_path` L1).
    - `escapes-owner-root` — the fixed `workspaces/` dir escapes the owner
      (`validate_workspace_path` L2).

    `segment` names which segment was rejected (`"user"`, `"workspace"`, or `"workspaces"` for
    the fixed literal). The 3-level validators always set it; it defaults to `None` only for a
    caller that constructs the error directly.
    """

    def __init__(
        self, workspace: object, reason: str, detail: str, segment: str | None = None
    ) -> None:
        super().__init__(f"invalid-workspace-name: {detail}")
        self.workspace = workspace
        self.reason = reason
        self.detail = detail
        self.segment = segment


# ===========================================================================
# The 3-level `users/<user>/workspaces/<workspace>/` validator (§23 re-home) — the SOLE
# workspace-path containment guard every door calls before constructing a store.
#
# The re-home nests TWO caller-supplied segments — `<user>` and `<workspace>` — under two fixed
# joins (`users/` then, per owner, `workspaces/`). Each of the three levels gets its OWN
# resolve-and-contain check so a symlink or `..` planted at ANY level (a symlinked `<user>`, a
# symlinked per-owner `workspaces/`, or a leaf symlink into a sibling user's tree) is caught —
# the adversarially-vetted "resolve BOTH sides, compare `.parent`" discipline applied at every
# join. `user` and `workspace` always arrive as SEPARATE arguments; this module never parses a
# slashed string into segments.
# ===========================================================================


def _check_segment_ci(seg: object, kind: str) -> None:
    """Hygiene for one CASE-INSENSITIVE id segment (`kind` = `"user"`/`"workspace"`); raise or pass.

    The shared `_SAFE_SEGMENT` grammar + `_MAX_SEGMENT_BYTES` cap (the single hygiene grammar/cap
    for every workspace-layout segment, so the charset is single-sourced), PLUS the ratified
    case-insensitive-id rule (W5): a segment must equal its own ASCII-lowercase form. Because the
    grammar already restricts `seg` to the ASCII set `[A-Za-z0-9._-]`, `seg.lower()` is a pure
    ASCII fold, so `seg != seg.lower()` is true exactly when an ASCII `A-Z` is present — ids are
    case-insensitive, so a non-lowercase spelling is refused rather than silently folded (which
    would let `Optiquity` and `optiquity` name the same home two ways). The grammar/cap check runs
    FIRST so the lowercase test only sees a known-ASCII string and a non-`str` never reaches it.

    Raised errors carry `segment=kind` so a door can report which leg (`"user"`/`"workspace"`) was
    rejected.
    """
    if not isinstance(seg, str):
        raise WorkspaceNameError(
            seg,
            "not-a-safe-segment",
            f"{kind} must be a string naming one path segment, got {type(seg).__name__}",
            segment=kind,
        )
    if not _SAFE_SEGMENT.match(seg) or len(seg.encode("utf-8")) > _MAX_SEGMENT_BYTES:
        raise WorkspaceNameError(
            seg,
            "not-a-safe-segment",
            f"{kind} {seg!r} is not a single safe path segment — one directory name "
            "(letters/digits/'_' then '.'/'-'/'_'; no separator, no leading '-', never a bare "
            "'.'/'..'; §10, CLAUDE.md rule 2)",
            segment=kind,
        )
    if seg != seg.lower():
        raise WorkspaceNameError(
            seg,
            "not-lowercase",
            f"{kind} {seg!r} must be lowercase — ids are case-insensitive, so a non-lowercase "
            f"spelling is refused (use {seg.lower()!r}); §23, W5",
            segment=kind,
        )


def validate_user_segment(framework_root: str | Path, user: str) -> Path:
    """Return the CONTAINED per-user home `<framework_root>/users/<user>`, or raise.

    LEVEL 1 of the re-home containment, extracted so a future per-user collection (siblings of
    `workspaces/` under the same owner) reuses the SAME user hygiene + containment rather than
    re-deriving it. Applies `_check_segment_ci` to `user` (safe segment + lowercase), then the
    resolve-and-contain check: the resolved `users/<user>` must be a DIRECT CHILD of the resolved
    `users/` base — catching a `<user>` that is a symlink escaping `users/`, an absolute path, or
    a `..` (the last two also refused by hygiene). Existence-independent (`resolve(strict=False)`):
    a not-yet-created owner dir still validates. The returned path is UNRESOLVED
    `Path(framework_root) / USERS_DIRNAME / user` — byte-identical to `WorkspaceStore.user_root`.
    """
    users_base = Path(framework_root) / USERS_DIRNAME
    _check_segment_ci(user, "user")

    users_r = users_base.resolve(strict=False)
    owner_dir = users_base / user
    if owner_dir.resolve(strict=False).parent != users_r:
        raise WorkspaceNameError(
            user,
            "escapes-users-root",
            f"user {user!r} does not resolve to a direct child of {str(users_base)!r} — a per-user "
            "home can never escape users/ (via '..', an absolute path, or a symlink); isolation is "
            "enforced at the root, not by trust (§10/§21.1/§23)",
            segment="user",
        )
    return owner_dir


def validate_workspace_path(
    framework_root: str | Path, user: str, workspace: str
) -> Path:
    """Return the CONTAINED `<framework_root>/users/<user>/workspaces/<workspace>` root, or raise.

    The 3-level isolation core of the re-home (§23). `user` and `workspace` arrive as SEPARATE
    caller-supplied arguments — never a slashed string — and each is contained at its own level:

    - **L1 (user):** `validate_user_segment` — `user` hygiene + lowercase, and `users/<user>`
      resolves to a direct child of `users/` (`reason="escapes-users-root"`, `segment="user"`).
    - **L2 (workspaces):** the FIXED per-owner `workspaces/` join must resolve to a direct child
      of the owner dir — catching a symlinked `workspaces/` planted in an owner's tree
      (`reason="escapes-owner-root"`, `segment="workspaces"`).
    - **L3 (workspace):** `workspace` hygiene + lowercase, and `workspaces/<workspace>` resolves
      to a direct child of that `workspaces/` — catching a leaf symlink into a sibling user's
      tree, a `..`, or an absolute path (`reason="escapes-workspaces-root"`, `segment="workspace"`).

    Resolving BOTH sides at each level (with `resolve(strict=False)`, so a not-yet-created path
    still validates) is what defeats `..`, absolute paths, AND symlink escapes at that level. The
    returned path is the UNRESOLVED `framework_root / USERS_DIRNAME / user / WORKSPACES_DIRNAME /
    workspace` — byte-identical to `WorkspaceStore.at(framework_root, user, workspace).root`.
    """
    owner_dir = validate_user_segment(framework_root, user)  # L1: user hygiene + containment.
    _check_segment_ci(workspace, "workspace")

    owner_r = owner_dir.resolve(strict=False)
    ws_base = owner_dir / WORKSPACES_DIRNAME  # FIXED literal join — not caller-supplied.
    ws_base_r = ws_base.resolve(strict=False)
    if ws_base_r.parent != owner_r:
        raise WorkspaceNameError(
            workspace,
            "escapes-owner-root",
            f"the workspaces/ dir under {str(owner_dir)!r} resolves outside the owner home — a "
            "symlinked workspaces/ can never relocate an owner's store base (§10/§21.1/§23)",
            segment="workspaces",
        )

    candidate = ws_base / workspace  # L3: the caller-supplied leaf segment.
    if candidate.resolve(strict=False).parent != ws_base_r:
        raise WorkspaceNameError(
            workspace,
            "escapes-workspaces-root",
            f"workspace {workspace!r} does not resolve to a direct child of {str(ws_base)!r} — a "
            "workspace store root can never escape its owner's workspaces/ (via '..', an absolute "
            "path, or a symlink into a sibling user); isolation holds at the root (§10/§21.1/§23)",
            segment="workspace",
        )
    return candidate


def workspace_path(
    framework_root: str | Path, user: str, workspace: str, *parts: str
) -> Path:
    """The PURE `<framework_root>/users/<user>/workspaces/<workspace>[/<parts…>]` join — NO resolve.

    The hot-path companion to `validate_workspace_path` (§23 re-home): once a door has VALIDATED
    the `(framework_root, user, workspace)` triple ONCE (the resolve-and-contain gate), every
    downstream path under that workspace — a per-collection M1 shadow dir, a `sources/` scan root,
    a save-home — is a plain `Path` join off the SAME two layout literals
    (`USERS_DIRNAME`/`WORKSPACES_DIRNAME`), never a second resolve on the hot cascade/M1 path (the
    "validate once at the door, pure-join downstream" discipline). Byte-identical to
    `WorkspaceStore.at(framework_root, user, workspace).root` when `parts` is empty, and to that
    root joined with `parts` otherwise.

    This is a pure calculator: it touches no filesystem and does NOT re-validate `user`/`workspace`
    (a `None`/non-`str` segment surfaces LOUDLY as a `TypeError` from `Path.joinpath` — never a
    silent `users/None/…` — so a caller that skipped the door still fails fast, never escapes).
    """
    return Path(framework_root).joinpath(USERS_DIRNAME, user, WORKSPACES_DIRNAME, workspace, *parts)
