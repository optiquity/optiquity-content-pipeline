"""The keystore core — SecretResolver + 0600-per-handle file backend (plan G3, §21.10, I5/S-2).

Proves the three data-safety invariants of the store, with NO spend and NO real secret ever
written into the repo tree (every test writes only under a pytest `tmp_path`):

- **roundtrip** — `store(handle, value)` then `resolve(handle)` returns EXACTLY the value.
- **0600 by construction, fail-closed on read** — a created secret file is 0600; a loosened
  (0644 / 0640 / 0604) file is REFUSED loudly (typed `SecretPermissionsError`) BEFORE any byte
  is read; a stricter 0400 file still reads.
- **no secret leakage (I5)** — the value never appears in `repr`/`str` of a `SecretRef` or a
  `ResolvedSecret`, in an exception message, or in a log line; the HANDLE always shows, the
  value never does.
- **typed miss** — a missing handle raises a typed `KeyStoreError` naming the HANDLE, not a value.
- **fail-closed path safety (S-2)** — a relative or in-repo `$OPTIQUITY_SECRETS_DIR` is a typed
  loud refuse; unset uses the home-anchored default; an absolute out-of-repo dir is accepted.
- **standalone boundary** — keystore.py imports NO transport/generation machinery.
"""

from __future__ import annotations

import ast
import copy
import logging
import os
import pickle
import stat
from pathlib import Path

import pytest

from pipeline.spend import keystore
from pipeline.spend.keystore import (
    DEFAULT_SECRETS_DIR,
    SECRETS_DIR_ENV,
    FileSecretBackend,
    KeyStoreError,
    ResolvedSecret,
    SecretDecodeError,
    SecretHandleError,
    SecretNotFoundError,
    SecretPermissionsError,
    SecretRef,
    SecretResolver,
    SecretsDirError,
    resolve_secrets_dir,
)

# A recognizable, high-entropy sentinel: if ANY of these bytes ever surface in a repr/str/log/
# exception, a leak test fails LOUDLY on the exact string.
SECRET_VALUE = "sk-ant-SUPER-SECRET-VALUE-do-not-log-0123456789abcdef"
HANDLE = "anthropic:acme-prod"


def _backend(tmp_path: Path) -> FileSecretBackend:
    """A backend rooted at an ABSOLUTE, out-of-repo tmp dir (never the repo tree)."""
    return FileSecretBackend(tmp_path / "secrets")


# --- roundtrip ---------------------------------------------------------------------------------


def test_store_then_resolve_roundtrips_the_exact_value(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    assert backend.resolve(ref).reveal() == SECRET_VALUE


def test_roundtrip_is_byte_exact_including_newlines_and_unicode(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse("fred:default")
    value = "line1\nline2\tüber-key-☃\n"  # trailing newline + tab + unicode
    backend.store(ref, value)
    assert backend.resolve(ref).reveal() == value


def test_store_overwrites_a_prior_value_for_the_same_handle(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, "first-value")
    backend.store(ref, SECRET_VALUE)
    assert backend.resolve(ref).reveal() == SECRET_VALUE


def test_has_and_delete_are_non_secret_and_idempotent(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    assert backend.has(ref) is False
    backend.store(ref, SECRET_VALUE)
    assert backend.has(ref) is True
    backend.delete(ref)
    assert backend.has(ref) is False
    backend.delete(ref)  # idempotent — a missing handle is a no-op, never raises


def test_list_handles_returns_stored_handle_names_only(tmp_path: Path):
    backend = _backend(tmp_path)
    backend.store(SecretRef.parse("anthropic:acme-prod"), SECRET_VALUE)
    backend.store(SecretRef.parse("fred:default"), "another")
    assert backend.list_handles() == ["anthropic:acme-prod", "fred:default"]


# --- 0600 on create; fail-closed on a loosened read ------------------------------------------


def test_created_secret_file_is_0600(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    mode = stat.S_IMODE(os.stat(backend.path_for(ref)).st_mode)
    assert mode == 0o600, f"expected 0600, got {mode:04o}"


def test_created_secrets_dir_is_0700(tmp_path: Path):
    backend = _backend(tmp_path)
    backend.store(SecretRef.parse(HANDLE), SECRET_VALUE)
    mode = stat.S_IMODE(os.stat(backend.secrets_dir).st_mode)
    assert mode == 0o700, f"expected 0700, got {mode:04o}"


@pytest.mark.parametrize("loose_mode", [0o644, 0o640, 0o604, 0o660, 0o606, 0o666])
def test_a_loosened_secret_file_is_refused_on_read(tmp_path: Path, loose_mode: int):
    """A secret whose perms are LOOSER than 0600 (any group/other bit) is REFUSED loudly on read
    — never handed back. The typed error names the handle + mode, NEVER the value."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    os.chmod(backend.path_for(ref), loose_mode)
    with pytest.raises(SecretPermissionsError) as excinfo:
        backend.resolve(ref)
    message = str(excinfo.value)
    assert HANDLE in message
    assert f"{loose_mode:04o}" in message
    assert SECRET_VALUE not in message  # the value is NEVER in the refusal (I5)


def test_a_stricter_than_0600_file_still_reads(tmp_path: Path):
    """0400 (owner read-only) is STRICTER than 0600, not looser — it must still resolve."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    os.chmod(backend.path_for(ref), 0o400)
    assert backend.resolve(ref).reveal() == SECRET_VALUE


# --- no secret leakage (I5) -------------------------------------------------------------------


def test_secret_ref_repr_and_str_show_the_handle_never_a_value():
    ref = SecretRef.parse(HANDLE)
    assert repr(ref) == f"SecretRef({HANDLE})"
    assert str(ref) == HANDLE
    assert ref.handle == HANDLE
    # A SecretRef holds no value at all — but be explicit that the sentinel never appears.
    assert SECRET_VALUE not in repr(ref)
    assert SECRET_VALUE not in str(ref)


def test_resolved_secret_repr_and_str_redact_the_value(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    resolved = backend.resolve(ref)
    # The value is reachable ONLY through the explicit reveal() seam.
    assert resolved.reveal() == SECRET_VALUE
    # ...and never through repr/str — those show the handle, redacted.
    assert SECRET_VALUE not in repr(resolved)
    assert SECRET_VALUE not in str(resolved)
    assert HANDLE in repr(resolved)
    assert HANDLE in str(resolved)
    assert "***" in repr(resolved)
    assert resolved.ref == ref


def test_resolving_a_secret_never_writes_the_value_to_a_log(tmp_path: Path, caplog):
    """The store emits no log record carrying the secret — resolving/storing is silent w.r.t.
    the value (I5: never in a log line)."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    with caplog.at_level(logging.DEBUG):
        backend.store(ref, SECRET_VALUE)
        backend.resolve(ref)
    for record in caplog.records:
        assert SECRET_VALUE not in record.getMessage()


def test_permissions_refusal_message_carries_no_value(tmp_path: Path):
    """Even the loud perms refusal — which fires AFTER the value is on disk — names only the
    handle + mode, never reads or prints the value (I5)."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    os.chmod(backend.path_for(ref), 0o644)
    with pytest.raises(SecretPermissionsError) as excinfo:
        backend.resolve(ref)
    assert SECRET_VALUE not in repr(excinfo.value)
    assert SECRET_VALUE not in str(excinfo.value)


# --- no leak via a non-UTF-8 decode (G3 review Fix 1) -----------------------------------------

# A recognizable sentinel embedded in an INVALID-UTF-8 body: the ASCII prefix is searchable, and
# the trailing continuation bytes make the whole body undecodable (so `decode` raises).
RAW_SENTINEL = b"sk-ant-RAW-CANARY-BYTES-fedcba9876543210"
NON_UTF8_BODY = RAW_SENTINEL + b"\xff\xfe\xfa\x80"


def test_a_non_utf8_secret_raises_a_typed_error_and_leaks_no_bytes(tmp_path: Path):
    """A non-UTF-8 stored secret (an out-of-band / future-backend write) must NOT surface a raw
    `UnicodeDecodeError` — whose `.args[1]`/`.object` carry the ENTIRE byte body. `resolve`
    translates it to a typed `SecretDecodeError` naming ONLY the handle, with the byte-bearing
    original chained into NEITHER `__cause__` NOR `__context__` NOR the traceback."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    # Simulate an out-of-band write of raw, non-UTF-8 bytes at a VALID 0600 (so we reach decode,
    # not the perms refusal). store() only accepts str, so write the bytes directly.
    path = backend.path_for(ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(NON_UTF8_BODY)
    os.chmod(path, 0o600)

    with pytest.raises(SecretDecodeError) as excinfo:
        backend.resolve(ref)
    err = excinfo.value
    assert isinstance(err, KeyStoreError)
    assert err.code == "keystore-decode-error"
    assert HANDLE in str(err)  # names the handle...

    # ...and the raw bytes appear in NONE of the error's surfaces (I5).
    sentinel_text = RAW_SENTINEL.decode("ascii")
    for surface in (str(err), repr(err), repr(err.args)):
        assert sentinel_text not in surface
    for arg in err.args:
        if isinstance(arg, str):
            assert sentinel_text not in arg
        if isinstance(arg, bytes | bytearray):
            assert RAW_SENTINEL not in bytes(arg)
    # The byte-bearing UnicodeDecodeError is not reachable through the chain, either.
    assert err.__cause__ is None
    assert err.__context__ is None


# --- no leak via pickle / deep-copy (G3 review Fix 2) -----------------------------------------


def test_resolved_secret_cannot_be_pickled(tmp_path: Path):
    """`pickle.dumps(rs)` would embed the value in the clear — refuse it (TypeError), leaking no
    bytes into the exception."""
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    resolved = backend.resolve(ref)
    with pytest.raises(TypeError) as excinfo:
        pickle.dumps(resolved)
    assert SECRET_VALUE not in str(excinfo.value)


def test_resolved_secret_cannot_be_deep_copied_or_copied(tmp_path: Path):
    """`copy.deepcopy`/`copy.copy` (the `multiprocessing` vector once G7 wires a child transport)
    would reconstruct a working secret — refuse both (TypeError), leaking no bytes."""
    resolved = ResolvedSecret(SecretRef.parse(HANDLE), SECRET_VALUE)
    with pytest.raises(TypeError) as deep:
        copy.deepcopy(resolved)
    with pytest.raises(TypeError) as shallow:
        copy.copy(resolved)
    assert SECRET_VALUE not in str(deep.value)
    assert SECRET_VALUE not in str(shallow.value)


def test_resolved_secret_reduce_hooks_all_refuse_without_a_value():
    """Every serialization hook refuses directly — no protocol/path reconstructs the value."""
    resolved = ResolvedSecret(SecretRef.parse(HANDLE), SECRET_VALUE)
    with pytest.raises(TypeError) as reduce_err:
        resolved.__reduce__()
    with pytest.raises(TypeError) as reduce_ex_err:
        resolved.__reduce_ex__(5)
    with pytest.raises(TypeError) as getstate_err:
        resolved.__getstate__()
    for excinfo in (reduce_err, reduce_ex_err, getstate_err):
        assert SECRET_VALUE not in str(excinfo.value)


# --- typed miss --------------------------------------------------------------------------------


def test_missing_handle_raises_typed_error_naming_the_handle(tmp_path: Path):
    backend = _backend(tmp_path)
    ref = SecretRef.parse(HANDLE)
    with pytest.raises(SecretNotFoundError) as excinfo:
        backend.resolve(ref)
    assert isinstance(excinfo.value, KeyStoreError)
    message = str(excinfo.value)
    assert HANDLE in message  # names the HANDLE...
    assert SECRET_VALUE not in message  # ...never a value (none exists, but be explicit)
    assert excinfo.value.code == "keystore-missing-handle"


# --- handle validation / path-traversal safety ------------------------------------------------


@pytest.mark.parametrize(
    "bad_handle",
    [
        "anthropic:acme:prod",  # two separators
        "anthropicacme-prod",  # no separator
        "a/b:c",  # slash in namespace → path escape
        "anthropic:../etc",  # traversal in name
        "anthropic:a/b",  # slash in name
        "..:x",  # dot-dot namespace
        ":name",  # empty namespace
        "ns:",  # empty name
        "NS:name",  # uppercase (not in the safe charset)
    ],
)
def test_a_malformed_or_unsafe_handle_is_refused(bad_handle: str):
    with pytest.raises(SecretHandleError):
        SecretRef.parse(bad_handle)


def test_secret_ref_direct_construction_validates_segments():
    with pytest.raises(SecretHandleError):
        SecretRef(namespace="ok", name="../escape")


# --- fail-closed path safety (S-2) ------------------------------------------------------------


def test_unset_env_uses_the_home_anchored_default():
    resolved = resolve_secrets_dir(env={})
    assert resolved.is_absolute()
    expected = Path(DEFAULT_SECRETS_DIR).expanduser().resolve()
    assert resolved == expected
    # The default is anchored under the user's home, never the repo checkout.
    assert resolved.is_relative_to(Path.home())


def test_empty_env_value_uses_the_home_anchored_default():
    resolved = resolve_secrets_dir(env={SECRETS_DIR_ENV: ""})
    assert resolved == Path(DEFAULT_SECRETS_DIR).expanduser().resolve()


@pytest.mark.parametrize(
    "relative_value",
    ["secrets", "./secrets", "../secrets", "instance/ops/secrets", "a/b/c"],
)
def test_a_relative_secrets_dir_is_refused(relative_value: str):
    with pytest.raises(SecretsDirError) as excinfo:
        resolve_secrets_dir(env={SECRETS_DIR_ENV: relative_value})
    assert excinfo.value.code == "keystore-secrets-dir-error"
    assert relative_value in str(excinfo.value)


def test_a_repo_relative_absolute_secrets_dir_is_refused():
    """An ABSOLUTE path that resolves INSIDE the repo tree is refused — secrets must never sit
    in-tree (an untracked blind spot for check-no-content.sh)."""
    repo_root = keystore._repo_root()
    in_repo = repo_root / "instance" / "ops" / "secrets-should-never-exist"
    with pytest.raises(SecretsDirError) as excinfo:
        resolve_secrets_dir(env={SECRETS_DIR_ENV: str(in_repo)})
    assert excinfo.value.code == "keystore-secrets-dir-error"
    # Refused BEFORE any directory is made — nothing was created in the repo tree.
    assert not in_repo.exists()


def test_the_repo_root_itself_is_refused():
    repo_root = keystore._repo_root()
    with pytest.raises(SecretsDirError):
        resolve_secrets_dir(env={SECRETS_DIR_ENV: str(repo_root)})


def test_an_absolute_out_of_repo_secrets_dir_is_accepted(tmp_path: Path):
    target = tmp_path / "secrets"
    resolved = resolve_secrets_dir(env={SECRETS_DIR_ENV: str(target)})
    assert resolved == target.resolve()
    # And a backend built on it constructs + roundtrips without touching the repo tree.
    backend = FileSecretBackend(env={SECRETS_DIR_ENV: str(target)})
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET_VALUE)
    assert backend.resolve(ref).reveal() == SECRET_VALUE
    assert not resolved.is_relative_to(keystore._repo_root())


def test_backend_construction_fails_closed_on_an_in_repo_dir():
    repo_root = keystore._repo_root()
    with pytest.raises(SecretsDirError):
        FileSecretBackend(repo_root / "instance" / "ops" / "secrets")


def test_backend_construction_fails_closed_on_a_relative_dir():
    with pytest.raises(SecretsDirError):
        FileSecretBackend("relative/secrets")


# --- pluggable backend contract ---------------------------------------------------------------


def test_file_backend_is_a_secret_resolver(tmp_path: Path):
    assert issubclass(FileSecretBackend, SecretResolver)
    assert isinstance(_backend(tmp_path), SecretResolver)


def test_secret_resolver_is_abstract():
    """The interface cannot be instantiated directly — a real backend must implement it."""
    with pytest.raises(TypeError):
        SecretResolver()  # type: ignore[abstract]


def test_resolved_secret_is_not_a_hashable_leaky_dataclass(tmp_path: Path):
    """ResolvedSecret is a hand-written class (no dataclass repr that would print the value)."""
    resolved = ResolvedSecret(SecretRef.parse(HANDLE), SECRET_VALUE)
    assert SECRET_VALUE not in repr(resolved)
    assert not hasattr(resolved, "__dict__")  # __slots__ — no stray attribute dict


# --- standalone boundary (imports no transport/generation machinery) --------------------------


def test_keystore_imports_no_pipeline_machinery():
    """G3 boundary: keystore.py is a STANDALONE store — it imports NOTHING from `pipeline`
    (no transport, compose, review, reconcile, driver, spend siblings). Parsed from source."""
    source = Path(keystore.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [a.name for a in node.names if a.name.split(".")[0] == "pipeline"]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] == "pipeline":
                offenders.append(module)
    assert offenders == [], f"keystore.py must import no pipeline machinery, found: {offenders}"
