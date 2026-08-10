"""Handle ASSIGNMENTS + the workspace→zone→user→global cascade (plan G4, §21.10, M3/S3).

An ASSIGNMENT maps an EXPLICIT `(scope-level, scope-id)` to a keystore HANDLE (a non-secret
`SecretRef`, G3) plus a HARD weekly dollar cap. It selects no transport and spends nothing — G4
stores assignments + resolves the cascade ONLY; transport selection, secret resolution into a
spawn, and metering are G6/G7. The store lives in the gitignored
`instance/ops/transport/config.yaml` (mechanism framework, data instance — never tracked in the
public repo; the `check-no-content.sh` guard stays green because `instance/ops/` is `.gitignore`d).

Two invariants shape every line here:

- **M3 — the scope-id is stored EXPLICITLY, never derived from the `users/` path.** A `(scope-level,
  scope-id)` key is PARSED from the `--scope` STRING (or built from an explicit identity triple in
  the cascade), never by inspecting a `users/<u>/zones/<z>/…` store path. This keeps §23 addressing
  purity + I4: transport identity never leaks the store layout, and same-named zones under DIFFERENT
  users key DISTINCT assignments (`dave/work` ≠ `erin/work`) because the scope-id carries the user.
  The identity segments ARE validated with the SAME §23 workspace-name guards the rest of the
  addressing uses (`validate_user_segment` / `validate_zone_segment` / `validate_workspace_path`),
  but the scope-id records IDENTITY, not a path.

- **S3 — no uncapped key.** `assign-key` HARD-REFUSES a missing `--weekly-cap` (non-zero exit,
  nothing written); there is NO silent default cap — the operator must state the weekly budget.

The **cascade** is most-specific-wins **workspace → zone → user → global**: `cascade_key` returns
the first assignment up that chain, else `None` (→ the subscription fallback, resolved at G7). The
zone rung sits BETWEEN workspace and user (the §23 zone fold-in).
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from pipeline.spend.keystore import SecretHandleError, SecretRef
from pipeline.workspace_name import (
    WorkspaceNameError,
    validate_user_segment,
    validate_workspace_path,
    validate_zone_segment,
)
from pipeline.yamlio import YAMLLoadError, load_yaml, make_loader

__all__ = [
    "CONFIG_FORMAT",
    "INSTALL_SCOPE_ID",
    "SCOPE_GLOBAL",
    "SCOPE_LEVELS",
    "SCOPE_USER",
    "SCOPE_WORKSPACE",
    "SCOPE_ZONE",
    "TRANSPORT_CONFIG_RELPATH",
    "Assignment",
    "AssignmentError",
    "AssignmentStore",
    "ConfigError",
    "InvalidCapError",
    "InvalidHandleError",
    "ScopeKey",
    "ScopeParseError",
    "config_path",
    "format_cap",
    "load_store",
    "parse_handle",
    "parse_scope",
    "parse_weekly_cap",
    "save_store",
]

#: The four scope levels, BROADEST → NARROWEST. The cascade walks them narrowest-first.
SCOPE_GLOBAL = "global"
SCOPE_USER = "user"
SCOPE_ZONE = "zone"
SCOPE_WORKSPACE = "workspace"
SCOPE_LEVELS = (SCOPE_GLOBAL, SCOPE_USER, SCOPE_ZONE, SCOPE_WORKSPACE)

#: The global level covers the WHOLE install; its scope-id is this single fixed token, stored
#: EXPLICITLY like every other scope-id (M3 — never derived from a path).
INSTALL_SCOPE_ID = "install"

#: The gitignored home of the assignment config (mechanism framework, data instance; §23).
TRANSPORT_CONFIG_RELPATH = Path("instance") / "ops" / "transport" / "config.yaml"

#: The config document format marker (bumped only if the config shape changes).
CONFIG_FORMAT = "transport-config/1"

#: The separator between identity segments in a composite (zone / workspace) scope-id. It is a
#: LOGICAL join of the explicit identity triple `user[/zone[/workspace]]` — NOT a filesystem path:
#: a scope-id is built from identity, never split off a `users/<u>/zones/<z>/…` store path (M3).
_SCOPE_ID_SEP = "/"

#: Display / on-disk sort order (broadest first), so `list-keys` and the config are deterministic.
_LEVEL_ORDER = {SCOPE_GLOBAL: 0, SCOPE_USER: 1, SCOPE_ZONE: 2, SCOPE_WORKSPACE: 3}

_HEADER = (
    "# transport-config — key assignments (plan G4, §21.10). GITIGNORED instance ops state\n"
    "# (instance/ops/, mechanism framework / data instance — NEVER committed to the public repo).\n"
    "# Each row maps an EXPLICIT (scope_level, scope_id) to a keystore HANDLE (a NON-secret\n"
    "# reference — the secret lives in the keystore) + a HARD weekly dollar cap. No secret here.\n"
    "# Edited via `pipeline transport assign-key/clear-key`; read by the cascade resolver.\n"
)


class AssignmentError(RuntimeError):
    """Base: an assignment operation hit a state it must refuse LOUDLY, never guess through."""

    code = "assignment-error"


class ScopeParseError(AssignmentError):
    """A `--scope` string is not a well-formed `(scope-level, scope-id)` (bad level/arity/seg)."""

    code = "assignment-bad-scope"


class InvalidCapError(AssignmentError):
    """`--weekly-cap` is present but not a positive dollar amount (non-numeric/zero/negative)."""

    code = "assignment-bad-cap"


class InvalidHandleError(AssignmentError):
    """`--handle` is not a safe keystore `<namespace>:<name>` ref (wraps SecretHandleError)."""

    code = "assignment-bad-handle"


class ConfigError(AssignmentError):
    """The on-disk assignment config is malformed — refused loudly, never repaired silently."""

    code = "assignment-bad-config"


@dataclass(frozen=True)
class ScopeKey:
    """An EXPLICIT `(level, scope_id)` addressing key — the identity a handle is assigned to (M3).

    `level` is one of `SCOPE_LEVELS`; `scope_id` is the install token (`global`), a user segment
    (`user`), `<u>/<z>` (`zone`), or `<u>/<z>/<ws>` (`workspace`). The scope-id records IDENTITY,
    never a store path — two same-named zones under different users are DISTINCT keys.
    """

    level: str
    scope_id: str


@dataclass(frozen=True)
class Assignment:
    """One assignment: a `ScopeKey` → a keystore HANDLE (`SecretRef`, non-secret) + a weekly cap.

    `handle` is a reference, not a secret (its `repr`/`str` show the handle only; the secret lives
    in the keystore, G3). `weekly_cap_usd` is a positive `Decimal` — the HARD weekly dollar budget
    (S3: never absent). This record selects no transport and spends nothing (G6/G7).
    """

    scope: ScopeKey
    handle: SecretRef
    weekly_cap_usd: Decimal


# ---------------------------------------------------------------------------------------
# Parsing (explicit — the scope-id is NEVER split off a store path, M3)
# ---------------------------------------------------------------------------------------


def parse_scope(scope: str, *, framework_root: str | os.PathLike[str]) -> ScopeKey:
    """Parse a `--scope` STRING explicitly into a validated `(level, scope-id)` `ScopeKey` (M3).

    Accepted forms → resulting `ScopeKey`:

    - `global`                     → `(global, INSTALL_SCOPE_ID)`
    - `user:<u>`                   → `(user, "<u>")`
    - `zone:<u>/<z>`               → `(zone, "<u>/<z>")`
    - `workspace:<u>/<z>/<ws>`     → `(workspace, "<u>/<z>/<ws>")`

    The scope-id is PARSED FROM THIS STRING — never derived by inspecting a
    `users/<u>/zones/<z>/…` store path (M3, §23 addressing purity). Each identity segment is
    validated with the SAME §23 workspace-name guards the rest of the addressing uses, so a
    bad / uppercase / traversing segment is a loud refusal. `framework_root` is the containment
    anchor those validators require; the returned scope-id records IDENTITY, not a path.
    """
    if not isinstance(scope, str) or scope == "":
        raise ScopeParseError(
            "assignment-bad-scope: --scope must be a non-empty string "
            "(global | user:<u> | zone:<u>/<z> | workspace:<u>/<z>/<ws>)"
        )
    if scope == SCOPE_GLOBAL:
        return ScopeKey(SCOPE_GLOBAL, INSTALL_SCOPE_ID)
    level, sep, rest = scope.partition(":")
    if sep == "" or rest == "":
        raise ScopeParseError(
            f"assignment-bad-scope: --scope {scope!r} — expected 'global' or "
            "'<level>:<id>' (user:<u> | zone:<u>/<z> | workspace:<u>/<z>/<ws>)"
        )
    parts = rest.split(_SCOPE_ID_SEP)
    try:
        if level == SCOPE_USER:
            if len(parts) != 1:
                raise ScopeParseError(
                    f"assignment-bad-scope: user scope-id must be one segment '<u>', got {rest!r}"
                )
            validate_user_segment(framework_root, parts[0])
            return ScopeKey(SCOPE_USER, parts[0])
        if level == SCOPE_ZONE:
            if len(parts) != 2:
                raise ScopeParseError(
                    f"assignment-bad-scope: zone scope-id must be '<u>/<z>', got {rest!r}"
                )
            user, zone = parts
            validate_user_segment(framework_root, user)
            validate_zone_segment(framework_root, user, zone)
            return ScopeKey(SCOPE_ZONE, _SCOPE_ID_SEP.join((user, zone)))
        if level == SCOPE_WORKSPACE:
            if len(parts) != 3:
                raise ScopeParseError(
                    f"assignment-bad-scope: workspace scope-id must be '<u>/<z>/<ws>', got {rest!r}"
                )
            user, zone, workspace = parts
            validate_workspace_path(framework_root, user, workspace, zone=zone)
            return ScopeKey(SCOPE_WORKSPACE, _SCOPE_ID_SEP.join((user, zone, workspace)))
    except WorkspaceNameError as exc:
        raise ScopeParseError(f"assignment-bad-scope: {exc.detail} (§23)") from None
    raise ScopeParseError(
        f"assignment-bad-scope: unknown scope level {level!r} "
        f"(known: {SCOPE_USER}, {SCOPE_ZONE}, {SCOPE_WORKSPACE}, or bare 'global')"
    )


def parse_handle(raw: str) -> SecretRef:
    """Parse a `--handle` `<namespace>:<name>` string into a validated (non-secret) `SecretRef`.

    Wraps the keystore's `SecretRef.parse` so a malformed handle surfaces as an `AssignmentError`
    (one exception family for the CLI to catch), carrying the keystore's own detail. A handle is a
    reference to WHICH secret — never a secret; the value lives in the keystore (G3).
    """
    try:
        return SecretRef.parse(raw)
    except SecretHandleError as exc:
        raise InvalidHandleError(str(exc)) from None


def parse_weekly_cap(raw: str) -> Decimal:
    """Parse `--weekly-cap` into a POSITIVE `Decimal` dollar amount, or refuse loudly (S3).

    Accepts a plain number (`50`, `49.50`), tolerating a leading `$` and thousands separators. An
    ABSENT `--weekly-cap` is NOT this function's concern — the CLI refuses that up front (S3: no
    uncapped key). A non-numeric, non-finite, zero, or negative value is a loud `InvalidCapError`.
    """
    text = str(raw).strip().lstrip("$").replace(",", "").strip()
    try:
        cap = Decimal(text)
    except InvalidOperation:
        raise InvalidCapError(
            f"assignment-bad-cap: --weekly-cap {raw!r} is not a number — state a positive dollar "
            "amount, e.g. `--weekly-cap 50`"
        ) from None
    if not cap.is_finite() or cap <= 0:
        raise InvalidCapError(
            f"assignment-bad-cap: --weekly-cap must be a POSITIVE dollar amount, got {raw!r} "
            "(a zero / negative / infinite cap is not a real weekly budget, S3)"
        )
    return cap


def format_cap(cap: Decimal) -> str:
    """Render a weekly cap for display: `$50/week` for whole dollars, `$49.50/week` otherwise."""
    if cap == cap.to_integral_value():
        return f"${int(cap)}/week"
    return f"${cap.quantize(Decimal('0.01'))}/week"


# ---------------------------------------------------------------------------------------
# The store + the cascade
# ---------------------------------------------------------------------------------------


class AssignmentStore:
    """The in-memory set of assignments keyed by `ScopeKey`, plus the cascade resolver.

    Loaded from / saved to `instance/ops/transport/config.yaml`. `assign` adds or REPLACES the
    assignment for a scope; `clear` removes one (idempotent). `cascade_key` resolves the
    most-specific-wins chain. The store holds only non-secret handles + caps — never a secret.
    """

    def __init__(self, assignments: Iterable[Assignment] = ()) -> None:
        self._by_scope: dict[ScopeKey, Assignment] = {}
        for assignment in assignments:
            self._by_scope[assignment.scope] = assignment

    @property
    def assignments(self) -> list[Assignment]:
        """Every assignment, sorted broadest → narrowest then by scope-id (deterministic)."""
        return sorted(
            self._by_scope.values(),
            key=lambda a: (_LEVEL_ORDER[a.scope.level], a.scope.scope_id),
        )

    def get(self, scope: ScopeKey) -> Assignment | None:
        """The assignment stored EXACTLY at `scope` (no cascade), or `None`."""
        return self._by_scope.get(scope)

    def assign(self, assignment: Assignment) -> None:
        """Add or REPLACE the assignment at `assignment.scope`."""
        self._by_scope[assignment.scope] = assignment

    def clear(self, scope: ScopeKey) -> bool:
        """Remove the assignment at `scope`; return True iff one was present (idempotent)."""
        return self._by_scope.pop(scope, None) is not None

    def cascade_key(
        self, user: str, zone: str, workspace: str | None = None
    ) -> Assignment | None:
        """Resolve the cascade most-specific-wins: **workspace → zone → user → global** (M3).

        Builds each candidate `ScopeKey` from the EXPLICIT identity triple (never a store path) and
        returns the FIRST assignment found up the chain, else `None` (→ the subscription fallback,
        resolved at G7). `workspace=None` skips the workspace rung (resolve to the zone/user/global
        assignment for ANY workspace). Same-named zones under different users resolve DISTINCT
        assignments because the zone scope-id carries the user (`<u>/<z>`).
        """
        candidates: list[ScopeKey] = []
        if workspace is not None:
            candidates.append(
                ScopeKey(SCOPE_WORKSPACE, _SCOPE_ID_SEP.join((user, zone, workspace)))
            )
        candidates.append(ScopeKey(SCOPE_ZONE, _SCOPE_ID_SEP.join((user, zone))))
        candidates.append(ScopeKey(SCOPE_USER, user))
        candidates.append(ScopeKey(SCOPE_GLOBAL, INSTALL_SCOPE_ID))
        for key in candidates:
            found = self._by_scope.get(key)
            if found is not None:
                return found
        return None


def config_path(root: str | os.PathLike[str]) -> Path:
    """The assignment config path under `root`: `<root>/instance/ops/transport/config.yaml`."""
    return Path(root) / TRANSPORT_CONFIG_RELPATH


def load_store(root: str | os.PathLike[str]) -> AssignmentStore:
    """Load the assignment store from `<root>/instance/ops/transport/config.yaml`.

    A missing config → an EMPTY store (no assignments; the cascade falls through to subscription).
    A present-but-malformed config → a loud `ConfigError` (never a silent partial).
    """
    path = config_path(root)
    if not path.is_file():
        return AssignmentStore()
    return _parse_config(path.read_text(encoding="utf-8"), source=str(path))


def save_store(store: AssignmentStore, root: str | os.PathLike[str]) -> Path:
    """Write `store` to `<root>/instance/ops/transport/config.yaml` atomically; return the path.

    Creates the gitignored `instance/ops/transport/` parents on demand. The write is temp-then
    `os.replace` (never torn); the file holds only non-secret handles + caps.
    """
    path = config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, _render_config(store))
    return path


# ---------------------------------------------------------------------------------------
# YAML (de)serialization — the pinned safe loader/dumper (yamlio), scope-ids stored explicitly
# ---------------------------------------------------------------------------------------


def _parse_config(text: str, *, source: str) -> AssignmentStore:
    text = text.removeprefix("\ufeff")  # S-E12 parity with the other config loaders
    try:
        data = load_yaml(text)
    except YAMLLoadError as exc:
        raise ConfigError(f"assignment-bad-config: {source}: not valid YAML ({exc})") from None
    if data is None:
        return AssignmentStore()
    if not isinstance(data, dict):
        raise ConfigError(
            f"assignment-bad-config: {source}: the config must be a YAML mapping, got "
            f"{type(data).__name__}"
        )
    rows = data.get("assignments") or []
    if not isinstance(rows, list):
        raise ConfigError(
            f"assignment-bad-config: {source}: `assignments` must be a list, got "
            f"{type(rows).__name__}"
        )
    assignments: list[Assignment] = []
    seen: set[ScopeKey] = set()
    for index, raw in enumerate(rows):
        assignment = _parse_row(raw, index=index, source=source)
        if assignment.scope in seen:
            raise ConfigError(
                f"assignment-bad-config: {source}: duplicate assignment for "
                f"{assignment.scope.level}:{assignment.scope.scope_id!r} — one handle per scope"
            )
        seen.add(assignment.scope)
        assignments.append(assignment)
    return AssignmentStore(assignments)


def _parse_row(raw: Any, *, index: int, source: str) -> Assignment:
    where = f"{source}: assignments[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"assignment-bad-config: {where}: each assignment must be a mapping")
    level = raw.get("scope_level")
    scope_id = raw.get("scope_id")
    handle = raw.get("handle")
    if level not in SCOPE_LEVELS:
        raise ConfigError(
            f"assignment-bad-config: {where}: scope_level must be one of {SCOPE_LEVELS}, got "
            f"{level!r}"
        )
    if not isinstance(scope_id, str) or scope_id == "":
        raise ConfigError(
            f"assignment-bad-config: {where}: scope_id must be a non-empty string "
            "(stored EXPLICITLY, never derived from a path — M3)"
        )
    if level == SCOPE_GLOBAL and scope_id != INSTALL_SCOPE_ID:
        raise ConfigError(
            f"assignment-bad-config: {where}: a global scope_id must be {INSTALL_SCOPE_ID!r}, got "
            f"{scope_id!r}"
        )
    if not isinstance(handle, str):
        raise ConfigError(
            f"assignment-bad-config: {where}: handle must be a '<namespace>:<name>' string"
        )
    try:
        ref = SecretRef.parse(handle)
    except SecretHandleError as exc:
        raise ConfigError(f"assignment-bad-config: {where}: {exc}") from None
    return Assignment(ScopeKey(level, scope_id), ref, _coerce_cap(raw.get("weekly_cap_usd"), where))


def _coerce_cap(value: Any, where: str) -> Decimal:
    if value is None:
        raise ConfigError(
            f"assignment-bad-config: {where}: weekly_cap_usd is REQUIRED (no uncapped key, S3)"
        )
    try:
        cap = Decimal(str(value))
    except InvalidOperation:
        raise ConfigError(
            f"assignment-bad-config: {where}: weekly_cap_usd {value!r} is not a number"
        ) from None
    if not cap.is_finite() or cap <= 0:
        raise ConfigError(
            f"assignment-bad-config: {where}: weekly_cap_usd must be a positive dollar amount, "
            f"got {value!r} (S3)"
        )
    return cap


def _render_config(store: AssignmentStore) -> str:
    rows = [
        {
            "scope_level": a.scope.level,
            "scope_id": a.scope.scope_id,  # EXPLICIT — the (scope-level, scope-id) keying (M3)
            "handle": a.handle.handle,  # a non-secret reference; NEVER a secret value
            "weekly_cap_usd": str(a.weekly_cap_usd),  # string → exact Decimal round-trip
        }
        for a in store.assignments
    ]
    return _HEADER + _dump_yaml({"format": CONFIG_FORMAT, "assignments": rows})


def _dump_yaml(data: Any) -> str:
    """Serialize with the pinned safe library (mirrors migration._dump_yaml): block, ordered."""
    y = make_loader()
    y.default_flow_style = False
    y.width = 4096
    y.representer.sort_base_mapping_type_on_output = False
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


def _atomic_write_text(path: Path, text: str) -> None:
    """Temp-then-`os.replace` write (a config rewrite needs only not-torn, which replace gives)."""
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
