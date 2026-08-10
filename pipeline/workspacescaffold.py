"""Workspace lifecycle — scaffold / list / delete (design §23). PURE + REUSABLE, LOCAL.

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

W2 completes the workspace CRUD with two more LOCAL conveniences over the SAME self-contained
`users/<user>/workspaces/<workspace>/` layout: `list_workspaces` (READ-ONLY discovery — scans
`users/*/workspaces/*`, since workspaces are discovered by scanning, NOT via a global index) and
`delete_workspace` (the FIRST destructive verb — safe-by-default: it validates + resolves + contains
the target via the SAME isolation gate, REFUSES a non-existent target, NEVER deletes through a
symlink, requires a Tier-1 confirmation (typed name interactively / `--yes` headless), and REFUSES a
workspace holding generated output even under `--yes` unless `--force` is ALSO passed — generated
output is spent work/money). It `shutil.rmtree`s ONLY the validated contained real directory,
leaving `users/<user>/` and its `workspaces/` in place.

Wiring, never duplication (the authoring philosophy): the overwrite guard is C2a's `ensure_writable`
(refuse-if-exists / `--force` / TTY-gated / fail-fast headless), the isolation gate is
`workspace_name.validate_workspace_path` / `validate_user_segment`, the framework-root locator is
`authoring._framework_root`, and the typed refusal class is `authoring.AuthoringError`. A LEAF
module: it imports no identity / plan / cascade / invoke code; `__main__` (`workspace new` /
`workspace list` / `workspace delete` / `user new`) is the first and only consumer.

MONEY-SAFETY (§21.9): every verb here is a LOCAL Tier-A file op — `new` seeds files under a user's
namespace, `list` reads, `delete` removes ONE contained directory, and NOTHING else. None registers
an invoke verb, touches `_VERB_HANDLERS`, or dispatches through the invoke door, so none can spend
subscription quota or mint a token. A workspace name never enters the artifact preimage; a
scaffolded workspace is inert to identity until a run selects it.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.authoring import AuthoringError, _framework_root, ensure_writable
from pipeline.workspace_name import (
    DEFAULT_ZONE,
    USERS_DIRNAME,
    WORKSPACES_DIRNAME,
    ZONES_DIRNAME,
    validate_user_segment,
    validate_workspace_path,
    validate_zone_segment,
)

__all__ = [
    "WORKSPACE_BLUEPRINT_DIRS",
    "UserNamespace",
    "WorkspaceDeletion",
    "WorkspaceRow",
    "WorkspaceScaffold",
    "blueprint_dir",
    "delete_workspace",
    "list_workspaces",
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
    """The result of `workspace new`: the owning user, the zone, the workspace name, the created
    target path, the seeded (`copied`) + left-untouched (`skipped`) blueprint files, and whether the
    user namespace / the zone were NEWLY created (so a mistyped `--user` or `--zone` is visible,
    never silent)."""

    user: str
    zone: str
    workspace: str
    path: Path
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    created_user_namespace: bool
    created_zone: bool


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
    zone: str = DEFAULT_ZONE,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> WorkspaceScaffold:
    """Seed a new workspace `users/<user>/zones/<zone>/workspaces/<workspace>/` from
    `templates/workspace/`.

    Validates `<user>` + `<zone>` + `<workspace>` and computes the contained target via
    `validate_workspace_path` (the SOLE isolation gate — lowercase, single safe segment,
    resolve-and-contain). Refuses an existing target unless `force` (`ensure_writable`: TTY-gated
    interactive confirm, fail-fast headless); `force` NEVER overwrites an existing destination
    file — the blueprint is copied non-destructively, so a `--force` re-run only tops up MISSING
    files. The per-user namespace `users/<user>/` and the per-zone home `zones/<zone>/` are
    auto-created on demand; `created_user_namespace` / `created_zone` flag a brand-new user home /
    zone so a mistyped `--user` / `--zone` is visible (§23/Z4). `zone` defaults to `DEFAULT_ZONE`
    (the `--zone` CLI flag lands in Z7). The owner / zone dirs are derived from IDENTITY
    (`validate_user_segment` / `validate_zone_segment`), never fragile positional path math on the
    5-level target. Writes only under the user's namespace; registers NO invoke verb (§21.9)."""
    root = Path(root)
    target = validate_workspace_path(root, user, workspace, zone=zone)  # gate + contained path
    owner_dir = validate_user_segment(root, user)  # users/<user> — derived from IDENTITY, not depth
    zone_dir = validate_zone_segment(root, user, zone)  # users/<user>/zones/<zone> — from IDENTITY
    created_user_namespace = not owner_dir.exists()
    created_zone = not zone_dir.exists()

    ensure_writable(target, force=force, isatty=isatty, confirm=confirm)
    target.mkdir(parents=True, exist_ok=True)  # auto-creates users/<user>/zones/<zone>/workspaces/
    copied, skipped = _seed_blueprint(blueprint_dir(), target)
    return WorkspaceScaffold(
        user=user,
        zone=zone,
        workspace=workspace,
        path=target,
        copied=tuple(copied),
        skipped=tuple(skipped),
        created_user_namespace=created_user_namespace,
        created_zone=created_zone,
    )


def scaffold_user(
    root: str | Path,
    user: str,
    *,
    zone: str = DEFAULT_ZONE,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> UserNamespace:
    """Create JUST the empty per-zone namespace `users/<user>/zones/<zone>/workspaces/` (no
    workspace).

    Validates `<user>` (via `validate_user_segment`) then `<zone>` (via `validate_zone_segment` —
    the Z3 advisory: user is pre-validated first, so the zone gate never runs on an unvetted user),
    each the isolation gate (lowercase, single safe segment, resolve-and-contain). Refuses an
    existing `users/<user>/zones/<zone>/workspaces/` unless `force` (`ensure_writable`: TTY-gated,
    fail-fast headless); `force` is a SAFE no-op that deletes nothing. `created_user_namespace`
    flags a brand-new `users/<user>/` home. `zone` defaults to `DEFAULT_ZONE` (the `--zone` CLI flag
    lands in Z7). The explicit way to stand up a per-user/zone home before any workspace exists. A
    local file op; registers NO invoke verb (§21.9)."""
    root = Path(root)
    owner_dir = validate_user_segment(root, user)  # isolation gate + contained users/<user>
    zone_dir = validate_zone_segment(
        root, user, zone
    )  # users/<user>/zones/<zone> (user pre-vetted)
    ws_base = zone_dir / WORKSPACES_DIRNAME
    created_user_namespace = not owner_dir.exists()

    ensure_writable(ws_base, force=force, isatty=isatty, confirm=confirm)
    ws_base.mkdir(parents=True, exist_ok=True)
    return UserNamespace(user=user, path=ws_base, created_user_namespace=created_user_namespace)


# ===========================================================================
# W2: `workspace list` (READ-ONLY) + `workspace delete` (DESTRUCTIVE, SAFE-BY-DEFAULT).
#
# The encapsulation conveniences that complete the workspace CRUD over the SAME self-contained
# `users/<user>/workspaces/<workspace>/` layout. Workspaces are discovered by SCANNING (there is
# no global workspace index/registry/manifest anywhere in the codebase — verified — so a delete is
# self-contained: an `rmtree` of the workspace dir leaves no orphaned entry elsewhere). Both stay
# LEAF, LOCAL file ops — no invoke/session import, no `_VERB_HANDLERS`, no quota/token (§21.9).
# ===========================================================================

#: The workspace subdirs whose non-empty presence marks GENERATED work (spent compose/review calls,
#: rendered bytes, tracking) — the Tier-2 has-output guard's oracle. A pristine blueprint workspace
#: ships NONE of these (only `assets/`/`output/`/`select/`/`topics/` .gitkeep homes + the config
#: files), and a store a driver merely OPENED (`ensure_layout` mkdirs them EMPTY) does not count
#: — only REAL files inside do. `output/` is handled separately (it ships a `.gitkeep` that must not
#: count) and `ssot.csv` is a file, not a dir; both are checked in `_has_generated_output`.
_GENERATED_WORK_SUBDIRS = ("artifacts", "deliverables", "folios", "reviews")

#: The per-workspace tracking CSV a completed thread/MVP writes (`store.root / "ssot.csv"`,
#: driver.py / mvpdemo.py): its presence alone is generated (spent) work.
_SSOT_CSV_NAME = "ssot.csv"

#: The empty-home marker the blueprint stamps into `output/` (and the other empty dirs). An
#: `output/` holding ONLY this is still pristine — real generated output is any OTHER file.
_GITKEEP = ".gitkeep"


@dataclass(frozen=True)
class WorkspaceRow:
    """One `workspace list` row: the owning user, the zone, the workspace name, its directory path,
    and a light TRUE summary — the count of authored topic files (`topics/*.md`) and whether the
    workspace holds generated output (`has_output`, the same oracle the delete Tier-2 guard reads).
    A pure read projection; no field is fabricated."""

    user: str
    zone: str
    workspace: str
    path: Path
    topic_count: int
    has_output: bool


@dataclass(frozen=True)
class WorkspaceDeletion:
    """The result of a successful `workspace delete`: the owning user, the workspace name, the
    (now-removed) target path, the count of files that were under it, and whether it held generated
    output (only ever True when `--force` accompanied `--yes`). `users/<user>/` and its
    `workspaces/` are left in place — only the one contained workspace dir was removed."""

    user: str
    workspace: str
    path: Path
    file_count: int
    had_output: bool


def _count_topics(ws_dir: Path) -> int:
    """Count the authored topic files under `<ws>/topics/` (`*.md`, e.g. the `x-`-prefixed client
    topics `entry new topic` writes). The blueprint's `topics/.gitkeep` is not a `*.md` file, so a
    pristine workspace reports 0 — TRUE, never fabricated."""
    topics = ws_dir / "topics"
    if not topics.is_dir():
        return 0
    return sum(1 for p in topics.glob("*.md") if p.is_file())


def _has_generated_output(ws_dir: Path) -> bool:
    """True iff `ws_dir` holds GENERATED work — the Tier-2 delete guard's oracle + the list summary.

    Generated = spent work/money: any file under `output/` other than the blueprint `.gitkeep`; OR a
    non-empty `artifacts/`/`deliverables/`/`folios/`/`reviews/` store dir (real composed/rendered/
    reviewed records — a driver that merely `ensure_layout`-created these EMPTY does not count);
    OR a per-workspace `ssot.csv`. A pristine/scaffolded workspace has none → False. Pure read."""
    output = ws_dir / "output"
    if output.is_dir():
        for entry in output.rglob("*"):
            if entry.is_file() and entry.name != _GITKEEP:
                return True
    for sub in _GENERATED_WORK_SUBDIRS:
        d = ws_dir / sub
        if d.is_dir() and any(p.is_file() for p in d.rglob("*")):
            return True
    return (ws_dir / _SSOT_CSV_NAME).is_file()


def list_workspaces(
    root: str | Path, *, user: str | None = None, zone: str | None = None
) -> list[WorkspaceRow]:
    """List workspaces under `<root>/users/*/zones/*/workspaces/*`, sorted by `(user, zone,
    workspace)` — READ-ONLY (§23/Z4: the scan is now 3-deep — user → zone → workspace).

    With `user`: scope to that one user (`user` put through `validate_user_segment` for hygiene even
    though reading is safe). With `zone`: further scope to that one zone name across the selected
    user(s). Without either: scan EVERY user AND EVERY zone (`users/*/zones/*/workspaces/*`), each
    row identified as `<user>/<zone>/<workspace>`. A missing/empty `users/` (or a user/zone with no
    namespace) yields an EMPTY list — never a traceback; the caller prints a clean "no workspaces
    found". Each row carries a light TRUE summary (topic count + has-output). Pure read; mutates
    nothing. (The 2-deep pre-Z4 scan `users/*/workspaces/*` returns EMPTY post-flip — a workspace
    now lives one level deeper under `zones/<zone>/`.)"""
    root = Path(root)
    users_base = root / USERS_DIRNAME
    if user is not None:
        validate_user_segment(root, user)  # hygiene only; reading never mutates
        owners = [users_base / user]
    else:
        if not users_base.is_dir():
            return []
        owners = sorted(
            (p for p in users_base.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        )

    rows: list[WorkspaceRow] = []
    for owner in owners:
        zones_base = owner / ZONES_DIRNAME
        if not zones_base.is_dir():
            continue
        if zone is not None:
            zone_dirs = [zones_base / zone]
        else:
            zone_dirs = sorted(
                (p for p in zones_base.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name,
            )
        for zone_dir in zone_dirs:
            ws_base = zone_dir / WORKSPACES_DIRNAME
            if not ws_base.is_dir():
                continue
            for ws_dir in sorted(
                (p for p in ws_base.iterdir() if p.is_dir() and not p.name.startswith(".")),
                key=lambda p: p.name,
            ):
                rows.append(
                    WorkspaceRow(
                        user=owner.name,
                        zone=zone_dir.name,
                        workspace=ws_dir.name,
                        path=ws_dir,
                        topic_count=_count_topics(ws_dir),
                        has_output=_has_generated_output(ws_dir),
                    )
                )
    rows.sort(key=lambda r: (r.user, r.zone, r.workspace))
    return rows


def _default_delete_confirm(workspace: str) -> str:
    """The interactive Tier-1 prompt: ask the operator to TYPE the workspace name back. Returns the
    typed string (stripped) so the caller can compare it to the target name; a mismatch aborts."""
    return input(
        f"type the workspace name {workspace!r} to confirm deletion (anything else aborts): "
    ).strip()


def delete_workspace(
    root: str | Path,
    user: str,
    workspace: str,
    *,
    zone: str = DEFAULT_ZONE,
    assume_yes: bool = False,
    force: bool = False,
    confirm_fn: Callable[[str], str] | None = None,
    isatty: Callable[[], bool] | None = None,
) -> WorkspaceDeletion:
    """Remove ONE workspace `users/<user>/workspaces/<workspace>/` — DESTRUCTIVE, SAFE-BY-DEFAULT.

    The FIRST destructive verb in the toolset; it matches the refuse-rather-than-clobber bar of
    everything else with a layered contract, in order:

    1. **Validate + contain.** `validate_workspace_path` (the SOLE isolation gate: lowercase, single
       safe segment, resolve-and-contain) yields the contained target. A bad/uppercase/escaping
       `user` or `workspace` raises `WorkspaceNameError` here. `user` is MANDATORY.
    2. **Never delete through a symlink.** If the target itself is a symlink, REFUSE — an `rmtree`
       must never follow a link out. (`shutil.rmtree` also never recurses INTO symlinked children,
       so only the validated real tree is ever removed.)
    3. **Refuse a non-existent target** — nothing to delete.
    4. **Tier-2 has-output guard.** If the workspace holds GENERATED output (`_has_generated_output`
       — spent work/money), REFUSE even with `assume_yes`, unless `force` is ALSO passed. Checked
       BEFORE the prompt so spent work fails fast, never prompts-then-refuses.
    5. **Tier-1 confirmation (always).** With `assume_yes` the confirmation is supplied
       non-interactively (skip the prompt). Otherwise, mirroring `ensure_writable`'s TTY gate:
       interactive (a TTY, or an injected `confirm_fn`) prompts the operator to TYPE the workspace
       name — a mismatch ABORTS (nothing deleted); headless (no TTY, no `confirm_fn`) REFUSES
       fast ("pass --yes to confirm"), never hangs.
    6. **Remove.** `shutil.rmtree` the validated contained target ONLY; `users/<user>/` and its
       `workspaces/` are left in place.

    Every refusal is a typed `AuthoringError`/`WorkspaceNameError` (a clean exit-1 at the CLI, never
    a traceback) raised BEFORE any removal, so a refused delete touches nothing. LOCAL file op;
    registers NO invoke verb (§21.9)."""
    root = Path(root)
    target = validate_workspace_path(root, user, workspace, zone=zone)  # gate + contained path

    # (2) Never delete through a symlink — catches a workspace dir planted as a link (broken or
    # live). Checked before `exists()` so a broken link is refused as a symlink, not "not found".
    if target.is_symlink():
        raise AuthoringError(
            f"invalid-authoring: {target} is a symlink — refusing to delete through it (a delete "
            "never follows a link out of the contained workspace); nothing removed"
        )
    # (3) Refuse a non-existent (or non-directory) target — nothing to delete.
    if not target.is_dir():
        raise AuthoringError(
            f"invalid-authoring: no workspace directory at {target} to delete — name an existing "
            "workspace under users/<user>/workspaces/; nothing removed"
        )

    # (4) Tier-2: generated output is spent work/money — refuse even with --yes unless --force too.
    had_output = _has_generated_output(target)
    if had_output and not force:
        raise AuthoringError(
            f"invalid-authoring: {target} holds generated output (spent work) — refusing to "
            "delete; pass --force together with --yes to override; nothing removed"
        )

    # (5) Tier-1: confirmation is ALWAYS required. --yes supplies it non-interactively.
    if not assume_yes:
        interactive = confirm_fn is not None or (
            isatty() if isatty is not None else (sys.stdin.isatty() and sys.stdout.isatty())
        )
        if not interactive:
            raise AuthoringError(
                f"invalid-authoring: refusing to delete {target} without confirmation — pass "
                "--yes to confirm (non-interactive: never prompts, never hangs); nothing removed"
            )
        typed = (confirm_fn or _default_delete_confirm)(workspace)
        if typed != workspace:
            raise AuthoringError(
                f"invalid-authoring: confirmation {typed!r} did not match the workspace name "
                f"{workspace!r} — aborted, nothing deleted"
            )

    # (6) Remove ONLY the validated, contained, real directory. Count first (for the report).
    file_count = sum(1 for p in target.rglob("*") if p.is_file())
    shutil.rmtree(target)
    return WorkspaceDeletion(
        user=user,
        workspace=workspace,
        path=target,
        file_count=file_count,
        had_output=had_output,
    )
