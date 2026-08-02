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
    "USERS_DIRNAME",
    "WORKSPACES_DIRNAME",
    "WorkspaceNameError",
    "validate_workspace_name",
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
    `hint`. `reason` is one of `not-a-safe-segment` (secondary/hygiene) or
    `escapes-workspaces-root` (primary/resolve-and-contain).
    """

    def __init__(self, workspace: object, reason: str, detail: str) -> None:
        super().__init__(f"invalid-workspace-name: {detail}")
        self.workspace = workspace
        self.reason = reason
        self.detail = detail


def validate_workspace_name(workspace: object, root: str | Path) -> Path:
    """Return the CONTAINED `<root>/workspaces/<workspace>` store-root path, or raise.

    The returned path is the UNRESOLVED `Path(root) / "workspaces" / workspace` — byte-
    identical to what a door built before this guard existed, so a valid name yields the
    exact same store root (behavior-neutral). Raises `WorkspaceNameError` on any violation,
    BEFORE any store is constructed or touched.
    """
    base = Path(root) / WORKSPACES_DIRNAME

    # SECONDARY (hygiene): a single safe path segment. Runs first so a malformed name gives a
    # precise reason and a non-`str` never reaches `Path` / `resolve`. A clean segment that is
    # actually a symlink escape still PASSES here — the primary check below is what catches it.
    if not isinstance(workspace, str):
        raise WorkspaceNameError(
            workspace,
            "not-a-safe-segment",
            f"workspace must be a string naming one path segment, got {type(workspace).__name__}",
        )
    if not _SAFE_SEGMENT.match(workspace) or len(workspace.encode("utf-8")) > _MAX_SEGMENT_BYTES:
        raise WorkspaceNameError(
            workspace,
            "not-a-safe-segment",
            f"workspace {workspace!r} is not a single safe path segment — a workspace name is "
            "one directory under workspaces/ (letters/digits/'_' then '.'/'-'/'_'; no separator, "
            "no leading '-', never a bare '.'/'..'; §10, CLAUDE.md rule 2)",
        )

    # PRIMARY (the real protection): the resolved store root must be a DIRECT CHILD of the
    # resolved workspaces/ dir. Resolving BOTH sides is what defeats `..`, absolute paths, and
    # symlink escapes, and shares any symlinked prefix (e.g. macOS /var→/private/var) so a valid
    # name in a tmpdir still validates. Existence-independent (`resolve(strict=False)`).
    candidate = base / workspace
    if candidate.resolve().parent != base.resolve():
        raise WorkspaceNameError(
            workspace,
            "escapes-workspaces-root",
            f"workspace {workspace!r} does not resolve to a direct child of {str(base)!r} — a "
            "workspace store root can never escape workspaces/ (via '..', an absolute path, or a "
            "symlink); isolation is enforced at the root, not by trust (§10/§21.1)",
        )
    return candidate
