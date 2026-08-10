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
    "ZoneDeletion",
    "ZoneRow",
    "ZoneScaffold",
    "blueprint_dir",
    "delete_workspace",
    "delete_zone",
    "list_workspaces",
    "list_zones",
    "scaffold_user",
    "scaffold_workspace",
    "scaffold_zone",
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


def _default_delete_confirm(name: str, kind: str = "workspace") -> str:
    """The interactive Tier-1 prompt: ask the operator to TYPE the target name back. `kind` labels
    the target (`"workspace"` for `delete_workspace`, `"zone"` for `delete_zone`), so ONE prompt
    serves both destructive verbs. Returns the typed string (stripped) so the caller can compare it
    to the target name; a mismatch aborts."""
    return input(
        f"type the {kind} name {name!r} to confirm deletion (anything else aborts): "
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


# ===========================================================================
# Z7: `zone new` (scaffold) + `zone list` (READ-ONLY) + `zone delete` (DESTRUCTIVE, RECURSIVE,
# SAFE-BY-DEFAULT) — the per-zone lifecycle, one level UP from the workspace CRUD.
#
# A zone groups a user's workspaces (§23): they live under `users/<user>/zones/<zone>/workspaces/`,
# so a zone sits BETWEEN user and workspace. These three verbs mirror the `scaffold_workspace` /
# `list_workspaces` / `delete_workspace` trio exactly, over the zone dir instead of the workspace
# dir, REUSING the isolation gate (`validate_user_segment` / `validate_zone_segment`), overwrite
# guard (`ensure_writable`), typed refusals (`AuthoringError`), and Tier-2 output oracle
# (`_has_generated_output`) — nothing re-implemented. `zone delete` is STRICTER than the workspace
# delete because it is RECURSIVE: it removes EVERY workspace the zone holds at once, so its Tier-2
# guard AGGREGATES the has-output oracle across all of them. All three stay LEAF, LOCAL file ops —
# no invoke/session import, no `_VERB_HANDLERS`, no quota/token (§21.9).
# ===========================================================================


@dataclass(frozen=True)
class ZoneScaffold:
    """The result of `zone new`: the owning user, the created zone name, the created
    `users/<user>/zones/<zone>/workspaces/` base path, and two visibility flags — whether the user
    namespace was NEWLY created (so a mistyped `--user` is visible) and whether the zone itself was
    newly created (`created_zone` is True on a fresh create, False on a `--force` no-op over an
    existing zone; a mistyped `--zone` shows up as a brand-new zone)."""

    user: str
    zone: str
    path: Path
    created_user_namespace: bool
    created_zone: bool


def scaffold_zone(
    root: str | Path,
    zone: str,
    *,
    user: str,
    force: bool = False,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> ZoneScaffold:
    """Create a new zone `users/<user>/zones/<zone>/workspaces/` — the per-zone home (§23).

    The sibling of `scaffold_user` one level down: it validates `<user>` (`validate_user_segment`)
    then `<zone>` (`validate_zone_segment` — the Z3 advisory: the user is pre-vetted FIRST, so the
    zone gate never runs on an unvetted user), each the SOLE isolation gate (lowercase, single safe
    segment, resolve-and-contain). Refuses an EXISTING zone unless `force` (`ensure_writable` on the
    zone dir: TTY-gated interactive confirm, fail-fast headless); `force` is a SAFE no-op deleting
    nothing. The per-user namespace `users/<user>/` is auto-created on demand;
    `created_user_namespace` flags a brand-new user home and `created_zone` a brand-new zone so a
    mistyped `--user`/`--zone` is visible, never silent. Writes only under the user's namespace;
    registers NO invoke verb (§21.9)."""
    root = Path(root)
    # FULL L1+L2+L3 gate (parity with `delete_zone` / `validate_workspace_path`): L1 contains
    # `<user>` under `users/`, L2 refuses a symlinked/relocated per-user `zones/`, L3 contains
    # `<zone>` under that `zones/`. Non-destructive here, but the containment story must match.
    owner_dir = validate_user_segment(root, user)  # L1: isolation gate + contained users/<user>
    owner_r = owner_dir.resolve(strict=False)
    zones_base = owner_dir / ZONES_DIRNAME  # FIXED literal join — not caller-supplied
    if zones_base.resolve(strict=False).parent != owner_r:  # L2: symlinked/relocated zones/
        raise AuthoringError(
            f"invalid-authoring: the zones/ dir under {owner_dir} resolves outside the user home — "
            "a symlinked zones/ can never relocate a user's zone base (§10/§21.1/§23); "
            "nothing created"
        )
    zone_dir = validate_zone_segment(root, user, zone)  # L3: users/<user>/zones/<zone>
    created_user_namespace = not owner_dir.exists()
    created_zone = not zone_dir.exists()

    ensure_writable(zone_dir, force=force, isatty=isatty, confirm=confirm)  # refuse-if-exists
    ws_base = zone_dir / WORKSPACES_DIRNAME
    ws_base.mkdir(parents=True, exist_ok=True)  # creates users/<user>/zones/<zone>/workspaces/
    return ZoneScaffold(
        user=user,
        zone=zone,
        path=ws_base,
        created_user_namespace=created_user_namespace,
        created_zone=created_zone,
    )


@dataclass(frozen=True)
class ZoneRow:
    """One `zone list` row: the owning user, the zone name, the zone path, and the count of
    workspaces the zone contains (`users/<user>/zones/<zone>/workspaces/*`). A pure read projection;
    no field is fabricated (an empty/absent `workspaces/` reports 0)."""

    user: str
    zone: str
    path: Path
    workspace_count: int


def _count_workspaces(zone_dir: Path) -> int:
    """Count the workspaces under `<zone>/workspaces/` (real subdirs, no dotfiles). A zone with
    no `workspaces/` base (or an empty one) reports 0 — TRUE, never fabricated."""
    ws_base = zone_dir / WORKSPACES_DIRNAME
    if not ws_base.is_dir():
        return 0
    return sum(1 for p in ws_base.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_zones(root: str | Path, *, user: str | None = None) -> list[ZoneRow]:
    """List zones under `<root>/users/*/zones/*`, sorted by `(user, zone)` — READ-ONLY (§23).

    With `user`: scope to that one user (`user` put through `validate_user_segment` for hygiene even
    though reading is safe). Without it: scan EVERY user (`users/*/zones/*`), each row identified as
    `<user>/<zone>`. A missing/empty `users/` (or a user with no `zones/`) yields an EMPTY list —
    never a traceback; the caller prints a clean "no zones found". Each row carries a TRUE workspace
    count. Pure read; mutates nothing."""
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

    rows: list[ZoneRow] = []
    for owner in owners:
        zones_base = owner / ZONES_DIRNAME
        if not zones_base.is_dir():
            continue
        for zone_dir in sorted(
            (p for p in zones_base.iterdir() if p.is_dir() and not p.name.startswith(".")),
            key=lambda p: p.name,
        ):
            rows.append(
                ZoneRow(
                    user=owner.name,
                    zone=zone_dir.name,
                    path=zone_dir,
                    workspace_count=_count_workspaces(zone_dir),
                )
            )
    rows.sort(key=lambda r: (r.user, r.zone))
    return rows


@dataclass(frozen=True)
class ZoneDeletion:
    """The result of a successful `zone delete`: the user, the (now-removed) zone name + path,
    the count of workspaces the zone contained, the count of files that were under it, and whether
    ANY contained workspace held generated output (only ever True when `--force` accompanied
    `--yes`). `users/<user>/` is left in place — only the one contained zone dir was removed."""

    user: str
    zone: str
    path: Path
    workspace_count: int
    file_count: int
    had_output: bool


def _zone_has_generated_output(zone_dir: Path) -> bool:
    """True iff ANY workspace under `<zone>/workspaces/` holds generated output — the RECURSIVE
    Tier-2 guard for `zone delete`. A zone delete removes every contained workspace at once, so its
    output guard AGGREGATES the SAME `_has_generated_output` oracle across all of them (spent
    work/money anywhere in the zone protects the whole zone). A zone with no workspaces (or only
    pristine ones) → False. Pure read."""
    ws_base = zone_dir / WORKSPACES_DIRNAME
    if not ws_base.is_dir():
        return False
    return any(
        _has_generated_output(p)
        for p in ws_base.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )


def delete_zone(
    root: str | Path,
    user: str,
    zone: str,
    *,
    assume_yes: bool = False,
    force: bool = False,
    confirm_fn: Callable[[str], str] | None = None,
    isatty: Callable[[], bool] | None = None,
) -> ZoneDeletion:
    """Remove ONE zone `users/<user>/zones/<zone>/` and EVERY workspace it contains — DESTRUCTIVE,
    SAFE-BY-DEFAULT, and STRICTER than `delete_workspace` because it is RECURSIVE.

    The SAME layered contract as `delete_workspace`, but the Tier-2 output guard AGGREGATES across
    every contained workspace (a zone delete removes them all at once), in order:

    1. **Validate + contain (the FULL L1+L2+L3 gate).** MIRRORS `validate_workspace_path`, NEVER
       `validate_zone_segment` ALONE — that Z3 function hygiene-checks only the ZONE leg (L3) and
       PRESUMES the user + per-user `zones/` were vetted upstream. Because the rmtree is RECURSIVE,
       `delete_zone` re-runs those levels itself: `validate_user_segment` contains `<user>` under
       `users/` (L1 — a crafted `--user` like `"../../victim"` can never relocate the base), a fresh
       resolve refuses a symlinked/relocated per-user `zones/` (L2 — the prefix symlink is never
       followed through), then `validate_zone_segment` contains `<zone>` under that `zones/` (L3). A
       bad/uppercase/escaping `user` or `zone` raises `WorkspaceNameError`/`AuthoringError` here;
       `user` is MANDATORY. The rmtree can therefore never escape the repo root.
    2. **Never delete through a LEAF symlink.** If the zone dir itself is a symlink, REFUSE — an
       `rmtree` must never follow a link out. (L1/L2 already caught a crafted `--user` and a
       symlinked intermediate `zones/`; `shutil.rmtree` also never recurses INTO symlinked children,
       so only the validated real tree is ever removed.)
    3. **Refuse a non-existent zone** — nothing to delete.
    4. **Tier-2 aggregate has-output guard.** If ANY contained workspace holds GENERATED output
       (`_zone_has_generated_output` across `zones/<zone>/workspaces/*` — spent work/money), REFUSE
       even with `assume_yes`, unless `force` too. Checked BEFORE the prompt so spent work
       fails fast, never prompts-then-refuses.
    5. **Tier-1 confirmation (always).** With `assume_yes` the confirmation is supplied
       non-interactively. Otherwise interactive (a TTY, or an injected `confirm_fn`) prompts the
       operator to TYPE the ZONE name — a mismatch ABORTS (nothing deleted); headless (no TTY, no
       `confirm_fn`) REFUSES fast ("pass --yes to confirm"), never hangs.
    6. **Remove.** `shutil.rmtree` the validated contained ZONE dir ONLY; `users/<user>/` is left in
       place.

    Every refusal is a typed `AuthoringError`/`WorkspaceNameError` (a clean exit-1 at the CLI, never
    a traceback) raised BEFORE any removal, so a refused delete touches nothing. LOCAL file op;
    registers NO invoke verb (§21.9)."""
    root = Path(root)
    # (1) FULL L1+L2+L3 isolation gate — MIRRORING `validate_workspace_path`, never
    # `validate_zone_segment` ALONE (which hygiene-checks only the zone leg and PRESUMES the user +
    # per-user `zones/` were vetted upstream at L1/L2). A recursive rmtree must never escape, so we
    # re-run those two levels here BEFORE resolving the leaf:
    #   L1 — `<user>` hygiene + resolve-and-contain under `users/` (a crafted `--user` like
    #        `"../../victim"` can never relocate the base — closes B1).
    #   L2 — the FIXED per-user `zones/` join must resolve to a direct child of the re-resolved user
    #        home (a symlinked/relocated `zones/` can never be followed through — closes B2).
    #   L3 — `<zone>` hygiene + resolve-and-contain under that `zones/` (as before).
    owner_dir = validate_user_segment(root, user)  # L1
    owner_r = owner_dir.resolve(strict=False)
    zones_base = owner_dir / ZONES_DIRNAME  # FIXED literal join — not caller-supplied
    if zones_base.resolve(strict=False).parent != owner_r:  # L2
        raise AuthoringError(
            f"invalid-authoring: the zones/ dir under {owner_dir} resolves outside the user home — "
            "a symlinked zones/ can never relocate a user's zone base (§10/§21.1/§23); "
            "nothing removed"
        )
    zone_dir = validate_zone_segment(root, user, zone)  # L3: gate + contained leaf path

    # (2) Never delete through a LEAF symlink — before `exists()` so a broken link is refused as a
    # symlink, not "not found". (L2 above already caught a symlinked intermediate `zones/`; this
    # catches the zone dir itself being a link.)
    if zone_dir.is_symlink():
        raise AuthoringError(
            f"invalid-authoring: {zone_dir} is a symlink — refusing to delete through it (a delete "
            "never follows a link out of the contained zone); nothing removed"
        )
    # (3) Refuse a non-existent (or non-directory) zone — nothing to delete.
    if not zone_dir.is_dir():
        raise AuthoringError(
            f"invalid-authoring: no zone directory at {zone_dir} to delete — name an existing zone "
            "under users/<user>/zones/; nothing removed"
        )

    # (4) Tier-2 (RECURSIVE): output ANYWHERE in the zone is spent work/money — refuse even
    # with --yes unless --force too.
    had_output = _zone_has_generated_output(zone_dir)
    if had_output and not force:
        raise AuthoringError(
            f"invalid-authoring: {zone_dir} contains a workspace holding generated output (spent "
            "work) — refusing to delete the whole zone; pass --force together with --yes to "
            "override; nothing removed"
        )

    # (5) Tier-1: confirmation is ALWAYS required. --yes supplies it non-interactively.
    if not assume_yes:
        interactive = confirm_fn is not None or (
            isatty() if isatty is not None else (sys.stdin.isatty() and sys.stdout.isatty())
        )
        if not interactive:
            raise AuthoringError(
                f"invalid-authoring: refusing to delete {zone_dir} without confirmation — pass "
                "--yes to confirm (non-interactive: never prompts, never hangs); nothing removed"
            )
        typed = confirm_fn(zone) if confirm_fn else _default_delete_confirm(zone, "zone")
        if typed != zone:
            raise AuthoringError(
                f"invalid-authoring: confirmation {typed!r} did not match the zone name {zone!r} — "
                "aborted, nothing deleted"
            )

    # (6) Remove ONLY the validated, contained, real zone dir. Count first (for the report).
    ws_base = zone_dir / WORKSPACES_DIRNAME
    workspace_count = (
        sum(1 for p in ws_base.iterdir() if p.is_dir() and not p.name.startswith("."))
        if ws_base.is_dir()
        else 0
    )
    file_count = sum(1 for p in zone_dir.rglob("*") if p.is_file())
    shutil.rmtree(zone_dir)
    return ZoneDeletion(
        user=user,
        zone=zone,
        path=zone_dir,
        workspace_count=workspace_count,
        file_count=file_count,
        had_output=had_output,
    )
