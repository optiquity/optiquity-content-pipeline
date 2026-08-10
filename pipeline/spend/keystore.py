"""SecretResolver + the 0600-per-handle keystore — spend-package home (plan G3, §21.10, I5/S-2).

The keystore is the ONE `pipeline.spend` module the sources subsystem may import (G9): a
STANDALONE secret store with NO transport, generation, or paid-selection coupling. G3 lands the
store ONLY — it resolves a namespaced HANDLE to a secret VALUE at USE time; it selects no
transport and spends nothing (assignment is G4, spend is G7).

Three data-safety invariants shape every line here:

- **I5 — no secret leakage.** A `SecretRef` is a NON-secret reference (a namespaced handle such
  as `anthropic:acme-prod` or `fred:default`); its `repr`/`str` show the HANDLE only. The
  resolved secret is returned inside a `ResolvedSecret` whose `repr`/`str` REDACT the value —
  the raw bytes are reachable ONLY via an explicit `.reveal()` call (the narrow seam G7 uses to
  inject `ANTHROPIC_API_KEY` into the child env). No code path serializes a value into a repr,
  a log line, an exception message, telemetry, or argv — every typed error names the HANDLE
  (and, for a perms refusal, the octal mode), NEVER the value.

- **0600 by construction, fail-closed on read.** Each handle is one file, created 0600 (owner
  rw only). On READ the file's mode is re-checked on the open fd: a secret whose perms are
  LOOSER than 0600 — any group/other bit set — is REFUSED loudly (a typed
  `SecretPermissionsError`) BEFORE its bytes are read. We never hand back a world/group-readable
  secret.

- **S-2 — fail-closed path safety.** `$OPTIQUITY_SECRETS_DIR` (default `~/.optiquity/secrets/`)
  MUST resolve to an ABSOLUTE directory OUTSIDE the repo tree. Unset → the home-anchored
  default. A RELATIVE value, or an absolute value that lands INSIDE the repo checkout, is a
  typed loud refuse (`SecretsDirError`) — secrets must never sit under the repo tree, where the
  `check-no-content.sh` guard scans only TRACKED files and an untracked-but-in-tree secret would
  be an unscanned blind spot.

**Pluggable backends.** `SecretResolver` is the abstract READ contract (`resolve`/`has`). The
0600 `FileSecretBackend` is the only backend G3 ships; an alternative (keyring, `apiKeyHelper`,
an external secret manager) slots behind the SAME interface later without touching callers.
"""

from __future__ import annotations

import os
import re
import stat
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "DEFAULT_SECRETS_DIR",
    "SECRETS_DIR_ENV",
    "FileSecretBackend",
    "KeyStoreError",
    "ResolvedSecret",
    "SecretHandleError",
    "SecretDecodeError",
    "SecretNotFoundError",
    "SecretPermissionsError",
    "SecretRef",
    "SecretResolver",
    "SecretsDirError",
    "resolve_secrets_dir",
]

#: The environment variable naming the secrets directory. Unset → the home-anchored default.
SECRETS_DIR_ENV = "OPTIQUITY_SECRETS_DIR"
#: The home-anchored default secrets directory (expanded/absolute at resolve time).
DEFAULT_SECRETS_DIR = "~/.optiquity/secrets"

#: A secret file is created at EXACTLY 0600 (owner rw, nothing for group/other); its containing
#: directory at 0700 (owner rwx, private).
_SECRET_FILE_MODE = 0o600
_SECRET_DIR_MODE = 0o700
#: The "looser than 0600" mask: ANY group/other permission bit (read, write, or execute). A
#: stored secret whose `mode & _LOOSE_MODE_MASK` is non-zero is world/group-reachable → refused
#: on read (never handed back).
_LOOSE_MODE_MASK = 0o077


class KeyStoreError(RuntimeError):
    """Base: a keystore operation hit a state it must refuse LOUDLY, never guess through (§3.1).

    Every subclass names the HANDLE (and, for a perms refusal, the octal mode) — NEVER the
    secret value (I5).
    """

    code = "keystore-error"


class SecretHandleError(KeyStoreError):
    """A handle string is malformed — not a safe `<namespace>:<name>` pair (I5 / path safety)."""

    code = "keystore-bad-handle"


class SecretsDirError(KeyStoreError):
    """`$OPTIQUITY_SECRETS_DIR` is unsafe — relative, or inside the repo tree (fail-closed, S-2)."""

    code = "keystore-secrets-dir-error"


class SecretNotFoundError(KeyStoreError):
    """No secret is stored under the handle — a typed miss naming the HANDLE, never a value."""

    code = "keystore-missing-handle"


class SecretPermissionsError(KeyStoreError):
    """A stored secret's perms are LOOSER than 0600 — refused on read, never handed back (I5)."""

    code = "keystore-permissions-error"


class SecretDecodeError(KeyStoreError):
    """A stored secret is not valid UTF-8 — refused with a typed error naming ONLY the handle.

    A raw stdlib `UnicodeDecodeError` would carry the ENTIRE offending byte sequence in
    `.args[1]`/`.object` — exactly what `logging.exception`/`repr(err)`/a crash reporter would
    capture (I5 leak). `resolve` translates it to THIS typed error via `raise … from None`, so
    the byte-bearing original is never chained into `__cause__` or the traceback.
    """

    code = "keystore-decode-error"


#: A handle segment: lowercase alnum start, then alnum / dot / underscore / hyphen, <= 64 chars.
#: Strict enough that `<namespace>:<name>` is always a SINGLE safe path component — no `/`, no
#: `.`/`..` traversal, no separator surprises — so a handle can never escape the secrets dir.
_SEGMENT_RE = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,63}\Z")
_HANDLE_SEP = ":"


@dataclass(frozen=True)
class SecretRef:
    """A NON-secret reference to a secret: the namespaced handle `<namespace>:<name>`.

    A `SecretRef` is safe to log, store in config, and put in a ledger — it names WHICH secret
    without being one. `repr`/`str` show the handle ONLY (I5). The resolver maps it to the
    secret VALUE at USE time (never at reference time).
    """

    namespace: str
    name: str

    def __post_init__(self) -> None:
        for label, value in (("namespace", self.namespace), ("name", self.name)):
            if not isinstance(value, str) or not _SEGMENT_RE.match(value):
                raise SecretHandleError(
                    f"keystore-bad-handle: {label} must match {_SEGMENT_RE.pattern} "
                    "(lowercase alnum + . _ - , <= 64 chars, no path separators) — a handle "
                    f"segment must be a safe single path component; got {value!r}"
                )

    @property
    def handle(self) -> str:
        """The `<namespace>:<name>` handle string — the file identity and the config token."""
        return f"{self.namespace}{_HANDLE_SEP}{self.name}"

    @classmethod
    def parse(cls, handle: str) -> SecretRef:
        """Parse a `<namespace>:<name>` handle string into a validated `SecretRef`."""
        if not isinstance(handle, str) or handle.count(_HANDLE_SEP) != 1:
            raise SecretHandleError(
                f"keystore-bad-handle: a handle must be exactly '<namespace>{_HANDLE_SEP}<name>' "
                f"(one '{_HANDLE_SEP}'), got {handle!r}"
            )
        namespace, name = handle.split(_HANDLE_SEP)
        return cls(namespace=namespace, name=name)

    def __repr__(self) -> str:  # I5: the HANDLE only (a SecretRef holds no value to leak)
        return f"SecretRef({self.handle})"

    def __str__(self) -> str:
        return self.handle


class ResolvedSecret:
    """A resolved secret VALUE, wrapped so it can NEVER leak by accident (I5).

    `repr`/`str` REDACT — they show the handle + `***`, never the bytes. The raw value is
    reachable ONLY through the explicit `.reveal()` seam (the narrow call G7 uses to inject the
    key into the child env). Deliberately NOT a dataclass: a dataclass-generated `repr` would
    print the value.
    """

    __slots__ = ("_ref", "_value")

    def __init__(self, ref: SecretRef, value: str) -> None:
        self._ref = ref
        self._value = value

    @property
    def ref(self) -> SecretRef:
        """The (non-secret) handle this value was resolved from."""
        return self._ref

    def reveal(self) -> str:
        """Return the raw secret value. The ONLY seam that exposes the bytes — call it exactly at
        the injection point (G7), never earlier, and never pass the result to a logger/argv."""
        return self._value

    def __repr__(self) -> str:  # I5: redacted — the handle, never the value
        return f"ResolvedSecret({self._ref.handle}=***)"

    def __str__(self) -> str:
        return f"{self._ref.handle}=***"

    #: The refusal every serialization/copy hook raises. A `ResolvedSecret` must NEVER be
    #: pickled, deep-copied, or shipped to another process (all of which would carry the value
    #: in the clear) — `deepcopy`/`multiprocessing` are the accidental vectors that go live once
    #: G7 wires spend into a child-process transport. Reveal the value ONLY at the injection
    #: point, via `.reveal()`. (Not in `__slots__`, so this class constant is legal.)
    _NOT_SERIALIZABLE = (
        "ResolvedSecret is not serializable; call reveal() only at the injection point "
        "(I5: the secret value must never be pickled, deep-copied, or sent to another process)"
    )

    def __reduce_ex__(self, protocol: int):  # the hook pickle calls directly, at any protocol
        raise TypeError(self._NOT_SERIALIZABLE)

    def __reduce__(self):
        raise TypeError(self._NOT_SERIALIZABLE)

    def __getstate__(self):
        raise TypeError(self._NOT_SERIALIZABLE)

    def __copy__(self):
        raise TypeError(self._NOT_SERIALIZABLE)

    def __deepcopy__(self, memo):
        raise TypeError(self._NOT_SERIALIZABLE)


def _repo_root() -> Path:
    """The repo checkout root — the directory CONTAINING the `pipeline` package.

    keystore.py lives at `<repo>/pipeline/spend/keystore.py`, so `parents[2]` is the checkout
    root. Any secrets dir at or under this path is IN-TREE (refused, S-2): the public-boundary
    guard scans only TRACKED files, so an untracked secret dropped in-tree would be an unscanned
    blind spot.
    """
    return Path(__file__).resolve().parents[2]


def resolve_secrets_dir(
    *,
    env: Mapping[str, str] | None = None,
    override: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve the secrets dir FAIL-CLOSED (S-2). Returns an absolute, out-of-repo `Path`.

    - `override` / `$OPTIQUITY_SECRETS_DIR` UNSET (or empty) → the home-anchored default
      `~/.optiquity/secrets/`.
    - a RELATIVE value (after `~` expansion) → typed loud refuse (`SecretsDirError`).
    - an ABSOLUTE value that resolves INSIDE the repo tree → typed loud refuse.
    - an absolute value OUTSIDE the repo tree → accepted (canonicalized).

    Touches the filesystem only to canonicalize the path — it creates nothing, so an unsafe
    value is refused BEFORE any directory is made.
    """
    if override is not None:
        raw: str | None = os.fspath(override)
    else:
        environ = os.environ if env is None else env
        raw = environ.get(SECRETS_DIR_ENV)

    if raw is None or raw == "":
        # Unset → the home-anchored default. `expanduser` makes it absolute; a home dir is never
        # the repo checkout, so it is outside the tree by construction.
        return Path(DEFAULT_SECRETS_DIR).expanduser().resolve()

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise SecretsDirError(
            f"keystore-secrets-dir-error: {SECRETS_DIR_ENV}={raw!r} is RELATIVE — secrets must "
            "live at an ABSOLUTE path OUTSIDE the repo tree (a relative/in-repo secrets dir is an "
            "untracked blind spot for the public-boundary guard). Set an absolute path such as "
            f"{DEFAULT_SECRETS_DIR!r}, or unset it to use that home-anchored default."
        )

    resolved = candidate.resolve()
    repo_root = _repo_root()
    if resolved == repo_root or resolved.is_relative_to(repo_root):
        raise SecretsDirError(
            f"keystore-secrets-dir-error: {SECRETS_DIR_ENV}={raw!r} resolves INSIDE the repo tree "
            f"({resolved} is under {repo_root}) — secrets must live OUTSIDE the checkout so no "
            "untracked secret can sit in-tree past the public-boundary guard. Use a path such as "
            f"{DEFAULT_SECRETS_DIR!r} (the home-anchored default), or unset it."
        )
    return resolved


class SecretResolver(ABC):
    """The pluggable READ contract: a namespaced HANDLE → the secret VALUE, at USE time only.

    G3 ships one implementation (`FileSecretBackend`, the 0600-per-handle store); a keyring /
    `apiKeyHelper` / external-secret-manager backend slots behind this SAME interface later
    without touching a single caller. A resolver NEVER selects a transport or spends — it only
    hands back an already-stored secret (assignment is G4, spend is G7).
    """

    @abstractmethod
    def resolve(self, ref: SecretRef) -> ResolvedSecret:
        """Return the secret VALUE for `ref`, wrapped in a redacting `ResolvedSecret`. Raise a
        typed `KeyStoreError` (naming the HANDLE, never a value) on a miss or an unsafe store."""

    @abstractmethod
    def has(self, ref: SecretRef) -> bool:
        """True iff a secret is stored under `ref` (a non-secret existence probe)."""


class FileSecretBackend(SecretResolver):
    """The 0600-per-handle file backend (G3's only backend).

    One file per handle at `<secrets_dir>/<namespace>:<name>`, created 0600 and re-checked
    fail-closed on every read. The secrets dir is resolved once, fail-closed (S-2), at
    construction — a relative or in-repo `$OPTIQUITY_SECRETS_DIR` refuses HERE, before any file
    is written.
    """

    def __init__(
        self,
        secrets_dir: str | os.PathLike[str] | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._dir = resolve_secrets_dir(env=env, override=secrets_dir)

    @property
    def secrets_dir(self) -> Path:
        """The resolved (absolute, out-of-repo) secrets directory."""
        return self._dir

    def path_for(self, ref: SecretRef) -> Path:
        """The (non-secret) FILE path a handle maps to — the filename IS the handle. A handle's
        segments are validated to a safe single path component, so this never escapes the dir."""
        return self._dir / ref.handle

    def store(self, ref: SecretRef, value: str) -> None:
        """Write `value` under `ref`, creating (or replacing) the file at EXACTLY 0600.

        Never logs or echoes the value. The directory is (re-)tightened to 0700 and the file
        `fchmod`-ed to 0600 on every write, so a stored secret is 0600 by construction —
        regardless of umask or any prior looser mode.
        """
        if not isinstance(value, str):
            raise KeyStoreError(
                f"keystore-error: the secret value for handle {ref.handle!r} must be a str "
                f"(got {type(value).__name__}) — the value itself is never logged"
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._dir, _SECRET_DIR_MODE)
        target = self.path_for(ref)
        fd = os.open(target, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, _SECRET_FILE_MODE)
        try:
            os.fchmod(fd, _SECRET_FILE_MODE)  # deterministic 0600 regardless of umask / prior mode
            view = memoryview(value.encode("utf-8"))
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
        finally:
            os.close(fd)

    def resolve(self, ref: SecretRef) -> ResolvedSecret:
        """Resolve `ref` → the secret value, FAIL-CLOSED on perms (I5).

        Opens the file, then checks the mode on the OPEN fd (no TOCTOU between the perm check and
        the read): a secret looser than 0600 is refused BEFORE any byte is read. A missing handle
        raises a typed miss naming the HANDLE, never a value.
        """
        target = self.path_for(ref)
        try:
            fd = os.open(target, os.O_RDONLY)
        except FileNotFoundError:
            raise SecretNotFoundError(
                f"keystore-missing-handle: no secret stored under handle {ref.handle!r} "
                f"(looked in {self._dir}) — store one first; the value is never inferred"
            ) from None
        try:
            mode = stat.S_IMODE(os.fstat(fd).st_mode)
            if mode & _LOOSE_MODE_MASK:
                raise SecretPermissionsError(
                    f"keystore-permissions-error: the secret file for handle {ref.handle!r} has "
                    f"mode {mode:04o}, LOOSER than 0600 (group/other bits set) — refusing to read "
                    "a world/group-readable secret. Run `chmod 600` on it, or re-store it. "
                    "(The handle and mode are named here; the value is NEVER read or logged.)"
                )
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            os.close(fd)
        # A raw UnicodeDecodeError holds the ENTIRE secret bytes in `.args[1]`/`.object` — exactly
        # what `logging.exception`/`repr(err)`/a crash reporter captures (I5 leak). Catch it, drop
        # its byte-bearing object, and raise the typed error OUTSIDE the `except` block: by then
        # the original is cleared from the frame, so it is chained into NEITHER `__cause__` NOR
        # `__context__` NOR the traceback. The typed error names ONLY the handle.
        decoded: str | None = None
        try:
            decoded = b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError:
            decoded = None
        if decoded is None:
            raise SecretDecodeError(
                f"keystore-decode-error: the secret stored under handle {ref.handle!r} is not "
                "valid UTF-8 — refusing to decode it. The raw bytes are never surfaced in this "
                "error, its args, or the traceback; re-store the secret as a UTF-8 string."
            )
        return ResolvedSecret(ref, decoded)

    def has(self, ref: SecretRef) -> bool:
        return self.path_for(ref).is_file()

    def delete(self, ref: SecretRef) -> None:
        """Remove the secret under `ref` if present (idempotent — a missing handle is a no-op)."""
        try:
            os.unlink(self.path_for(ref))
        except FileNotFoundError:
            pass

    def list_handles(self) -> list[str]:
        """The sorted handles currently stored (filename = handle). Non-secret: names only, never
        values. Files whose name is not a valid handle are ignored."""
        if not self._dir.is_dir():
            return []
        handles: list[str] = []
        for child in self._dir.iterdir():
            if not child.is_file() or _HANDLE_SEP not in child.name:
                continue
            try:
                SecretRef.parse(child.name)
            except SecretHandleError:
                continue
            handles.append(child.name)
        return sorted(handles)
