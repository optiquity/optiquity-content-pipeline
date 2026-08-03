"""Workspace scaffolder (design §23; authoring layer). PURE + REUSABLE, LOCAL.

`pipeline workspace new <workspace> --user <user>` seeds a new client workspace under a user's
namespace (`users/<user>/workspaces/<workspace>/`) by copying the shared framework blueprint
`templates/workspace/` — the friendly, LOCAL form of the documented
`cp -R templates/workspace users/<user>/workspaces/<workspace>` onboarding flow (design §23;
CLAUDE.md rule 2). `pipeline user new <user>` is the sibling that creates JUST the empty per-user
namespace `users/<user>/workspaces/` (the extensible per-user home) without a workspace.

Home + containment follow §23 BY LOCATION: `validate_workspace_path` / `validate_user_segment`
(`pipeline.workspace_name`) are the SOLE isolation gate — they enforce the lowercase-only,
single-safe-segment, resolve-and-contain hygiene on `<user>` and `<workspace>` AND return the
contained target path. The blueprint SOURCE is the framework-owned `templates/workspace/` under the
package root (`authoring._framework_root()`), so it is found cwd-independently and is identical for
every instance (never the caller's `--root` data tree). The blueprint is copied NON-DESTRUCTIVELY —
an existing destination file is NEVER overwritten (client data is irreplaceable, rule 1/2),
mirroring the migrate-to-users-layout never-delete-data discipline.

Wiring, never duplication (the authoring philosophy): the overwrite guard is C2a's `ensure_writable`
(refuse-if-exists / `--force` / TTY-gated / fail-fast headless), the isolation gate is
`workspace_name.validate_workspace_path` / `validate_user_segment`, the framework-root locator is
`authoring._framework_root`, and the typed refusal class is `authoring.AuthoringError`. A LEAF
module: it imports no identity / plan / cascade / invoke code; `__main__` (`workspace new` /
`user new`) is the first and only consumer.

MONEY-SAFETY (§21.9): a LOCAL Tier-A directory scaffold — it seeds files under a user's namespace
and NOTHING else. It registers NO invoke verb, touches NO `_VERB_HANDLERS`, and never dispatches
through the invoke door, so it cannot spend subscription quota or mint a token. A workspace name
never enters the artifact preimage; a scaffolded workspace is inert to identity until a run selects
it.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.authoring import AuthoringError, _framework_root, ensure_writable
from pipeline.workspace_name import (
    WORKSPACES_DIRNAME,
    validate_user_segment,
    validate_workspace_path,
)

__all__ = [
    "WORKSPACE_BLUEPRINT_DIRS",
    "UserNamespace",
    "WorkspaceScaffold",
    "blueprint_dir",
    "scaffold_user",
    "scaffold_workspace",
]

#: The blueprint tree the scaffolder stamps a new workspace from (design §23): the framework-owned,
#: owner-agnostic template that ships in the public repo. Located under the PACKAGE root so it is
#: found cwd-independently and is the SAME copy for every instance (never the caller's `--root` data
#: tree). The manual onboarding flow copies exactly this: `cp -R templates/workspace
#: users/<user>/workspaces/<ws>`.
WORKSPACE_BLUEPRINT_DIRS = ("templates", "workspace")


def blueprint_dir() -> Path:
    """The absolute path of the shared `templates/workspace/` blueprint (framework-owned, §23)."""
    return _framework_root().joinpath(*WORKSPACE_BLUEPRINT_DIRS)


def _seed_conflict(rel: Path, dest: Path) -> str:
    """The typed-refusal message for a blueprint entry that collides with an incompatible existing
    path (a client dir↔file swap): a blueprint DIR whose dest is a client FILE, a blueprint FILE
    whose dest (or an ancestor) is a client DIR, etc."""
    return (
        f"invalid-authoring: cannot seed {rel} — {dest} exists as a conflicting file/dir; "
        "remove or rename it, or scaffold into a clean path"
    )


def _seed_blueprint(source: Path, target: Path) -> tuple[list[str], list[str]]:
    """Copy the blueprint tree `source` into `target`, NEVER overwriting an existing destination
    file (client data is irreplaceable — rule 1/2; the migrate-to-users-layout never-delete-data
    discipline). Returns `(copied, skipped)` as sorted relative-path strings: `copied` are the newly
    seeded files, `skipped` the pre-existing files left untouched. Directory structure is preserved,
    including the `.gitkeep` markers that carry the empty `assets/` / `output/` / `select/` /
    `topics/` homes.

    A client dir↔file SWAP — a seeded blueprint directory replaced by a same-named regular file
    (or a blueprint file's path occupied by a directory) — is mapped to a typed `AuthoringError`
    (a clean exit-1 refusal via `_workspace_error_types`), NEVER a raw `FileExistsError` / `OSError`
    traceback ("loud + typed, never a stack trace"). The collision is caught BEFORE any copy or
    delete, so no client data is touched."""
    if not source.is_dir():
        raise AuthoringError(
            f"invalid-authoring: no workspace blueprint at {source} — `workspace new` seeds from "
            "the framework `templates/workspace/` tree; run from a framework checkout"
        )
    copied: list[str] = []
    skipped: list[str] = []
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source)
        dest = target / rel
        if path.is_dir():
            # A blueprint DIRECTORY: ensure a directory here. A client FILE occupying the path
            # (dir→file swap) makes mkdir raise — map the OS collision (FileExistsError, a subclass
            # of OSError) to a typed refusal; never a raw traceback.
            try:
                dest.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise AuthoringError(_seed_conflict(rel, dest)) from exc
            continue
        if dest.exists():  # NEVER clobber client data (rule 1/2) — leave it, report it
            # a client DIR sitting where a blueprint FILE goes is a conflict, not a top-up skip
            if dest.is_dir():
                raise AuthoringError(_seed_conflict(rel, dest))
            skipped.append(str(rel))
            continue
        # A new blueprint FILE: create its parent then copy. A client FILE occupying an ancestor
        # path (file→dir swap) makes mkdir/copy raise (NotADirectoryError/FileExistsError — OSError
        # subclasses) — again a typed refusal, never a traceback.
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        except OSError as exc:
            raise AuthoringError(_seed_conflict(rel, dest)) from exc
        copied.append(str(rel))
    return copied, skipped


@dataclass(frozen=True)
class WorkspaceScaffold:
    """The result of `workspace new`: the owning user, the workspace name, the created target path,
    the seeded (`copied`) + left-untouched (`skipped`) blueprint files, and whether the user
    namespace was NEWLY created (so a mistyped `--user` is visible, never silent)."""

    user: str
    workspace: str
    path: Path
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    created_user_namespace: bool


@dataclass(frozen=True)
class UserNamespace:
    """The result of `user new`: the user, the created empty namespace path
    (`users/<user>/workspaces/`), and whether the user home was newly created."""

    user: str
    path: Path
    created_user_namespace: bool


def scaffold_workspace(
    root: str | Path,
    workspace: str,
    *,
    user: str,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> WorkspaceScaffold:
    """Seed a new workspace `users/<user>/workspaces/<workspace>/` from `templates/workspace/`.

    Validates `<user>` + `<workspace>` and computes the contained target via
    `validate_workspace_path` (the SOLE isolation gate — lowercase, single safe segment,
    resolve-and-contain). Refuses an existing target unless `force` (`ensure_writable`: TTY-gated
    interactive confirm, fail-fast headless); `force` NEVER overwrites an existing destination
    file — the blueprint is copied non-destructively, so a `--force` re-run only tops up MISSING
    files. The per-user namespace `users/<user>/workspaces/` is auto-created on demand;
    `created_user_namespace` flags a brand-new `users/<user>/` home so a mistyped `--user` is
    visible. Writes only under the user's namespace; registers NO invoke verb (§21.9)."""
    root = Path(root)
    target = validate_workspace_path(root, user, workspace)  # isolation gate + contained path
    owner_dir = target.parent.parent  # users/<user> — derived from the validated path
    created_user_namespace = not owner_dir.exists()

    ensure_writable(target, force=force, isatty=isatty, confirm=confirm)
    target.mkdir(parents=True, exist_ok=True)  # auto-creates users/<user>/workspaces/ on demand
    copied, skipped = _seed_blueprint(blueprint_dir(), target)
    return WorkspaceScaffold(
        user=user,
        workspace=workspace,
        path=target,
        copied=tuple(copied),
        skipped=tuple(skipped),
        created_user_namespace=created_user_namespace,
    )


def scaffold_user(
    root: str | Path,
    user: str,
    *,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> UserNamespace:
    """Create JUST the empty per-user namespace `users/<user>/workspaces/` (no workspace).

    Validates `<user>` and returns the contained `users/<user>` home via `validate_user_segment`
    (the isolation gate — lowercase, single safe segment, resolve-and-contain). Refuses an existing
    `users/<user>/workspaces/` unless `force` (`ensure_writable`: TTY-gated, fail-fast headless);
    `force` is a SAFE no-op that deletes nothing. `created_user_namespace` flags a brand-new
    `users/<user>/` home. The explicit way to stand up a per-user home (the extensible per-user
    root) before any workspace exists. Local file op; registers NO invoke verb (§21.9)."""
    root = Path(root)
    owner_dir = validate_user_segment(root, user)  # isolation gate + contained users/<user>
    ws_base = owner_dir / WORKSPACES_DIRNAME
    created_user_namespace = not owner_dir.exists()

    ensure_writable(ws_base, force=force, isatty=isatty, confirm=confirm)
    ws_base.mkdir(parents=True, exist_ok=True)
    return UserNamespace(user=user, path=ws_base, created_user_namespace=created_user_namespace)
