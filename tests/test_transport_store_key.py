"""`pipeline transport store-key` — the operator-ergonomics verb that stores a secret in the 0600
keystore WITHOUT the value ever touching argv / `ps` / shell history (Tier-A, NO spend).

Every test writes only under a pytest `tmp_path` secrets dir (absolute, out-of-repo) set via
`$OPTIQUITY_SECRETS_DIR`; nothing spends and no real secret ever lands in the repo tree. The verb
reuses the reviewed 0600 `FileSecretBackend.store` — these tests prove the CLI seam around it:

- **piped stdin roundtrips + 0600** — the secret on stdin resolves back EXACTLY; the file is 0600.
- **no argv leak** — there is NO --value/--secret flag; the value is read from stdin/getpass only.
- **empty / whitespace refuse** — a typed refuse, NOTHING stored.
- **bad handle refuse** — `../x`, uppercase, empty → a typed refuse, NOTHING stored.
- **rotation** — storing a second value under the same handle updates it; the announce says
  `updated` (a first store says `created`).
- **announce never leaks the value** — stdout/stderr show the HANDLE + path, never the secret.
- **--from-file** reads the file bytes (never argv); the **getpass TTY** path is covered by
  monkeypatching `getpass.getpass`.
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_transport
from pipeline.spend.keystore import FileSecretBackend, SecretNotFoundError, SecretRef

# A recognizable, high-entropy sentinel: if these bytes ever surface in the announce, a leak test
# fails LOUDLY on the exact string.
SECRET_VALUE = "sk-ant-SUPER-SECRET-VALUE-do-not-print-0123456789abcdef"
HANDLE = "anthropic:mykey"


def _secrets_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point `$OPTIQUITY_SECRETS_DIR` at an ABSOLUTE, out-of-repo tmp dir and return it."""
    secrets = tmp_path / "secrets"
    monkeypatch.setenv("OPTIQUITY_SECRETS_DIR", str(secrets))
    return secrets


def _pipe_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    """Feed `text` on a NON-TTY stdin (a piped run: `isatty()` is False → the read path)."""
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def _resolve(secrets: Path, handle: str = HANDLE) -> str:
    """Read the stored secret back through the reviewed 0600 backend."""
    return FileSecretBackend(secrets).resolve(SecretRef.parse(handle)).reveal()


# --- piped stdin roundtrips + 0600 -------------------------------------------------------------


def test_store_key_piped_stdin_roundtrips_and_file_is_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    _pipe_stdin(monkeypatch, SECRET_VALUE)

    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    # The keystore resolves that EXACT value back.
    assert _resolve(secrets) == SECRET_VALUE
    # The store file is 0600 (owner rw only).
    mode = stat.S_IMODE(os.stat(secrets / HANDLE).st_mode)
    assert mode == 0o600, f"expected 0600, got {mode:04o}"


def test_store_key_strips_a_single_trailing_newline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    # A pipe/heredoc adds ONE trailing newline; it is the artifact, not part of the secret.
    _pipe_stdin(monkeypatch, SECRET_VALUE + "\n")
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    assert _resolve(secrets) == SECRET_VALUE


def test_store_key_strips_a_single_trailing_crlf_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    # Exactly one CRLF is stripped; a second (blank-line) newline is preserved verbatim.
    _pipe_stdin(monkeypatch, SECRET_VALUE + "\n\r\n")
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    assert _resolve(secrets) == SECRET_VALUE + "\n"


# --- no argv leak: there is NO --value / --secret flag -----------------------------------------


@pytest.mark.parametrize("flag", ["--value", "--secret"])
def test_store_key_has_no_secret_value_argv_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    """A secret-on-argv flag would land in `ps` + shell history — it must not exist. argparse
    rejects the unknown option (SystemExit) and NOTHING is stored."""
    secrets = _secrets_dir(tmp_path, monkeypatch)
    _pipe_stdin(monkeypatch, SECRET_VALUE)
    with pytest.raises(SystemExit):
        _cmd_transport(["store-key", "--handle", HANDLE, flag, SECRET_VALUE])
    assert not FileSecretBackend(secrets).has(SecretRef.parse(HANDLE))


# --- empty / whitespace-only refuse (nothing stored) -------------------------------------------


@pytest.mark.parametrize("piped", ["", "\n", "   ", "  \t \n"])
def test_store_key_refuses_empty_or_whitespace_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], piped: str
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    _pipe_stdin(monkeypatch, piped)
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 1
    assert "EMPTY" in capsys.readouterr().err
    # NOTHING was stored.
    assert not FileSecretBackend(secrets).has(SecretRef.parse(HANDLE))
    with pytest.raises(SecretNotFoundError):
        _resolve(secrets)


# --- bad handle refuse (nothing stored) --------------------------------------------------------


@pytest.mark.parametrize("bad", ["../x", "Anthropic:mykey", "", "a:b:c", "ANTHROPIC:KEY"])
def test_store_key_refuses_a_bad_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    """A malformed handle is refused BEFORE any secret is read or stored (a typed refuse)."""
    secrets = _secrets_dir(tmp_path, monkeypatch)
    # A valid secret waits on stdin — so the refusal is unambiguously the HANDLE, not the value.
    _pipe_stdin(monkeypatch, SECRET_VALUE)
    assert _cmd_transport(["store-key", "--handle", bad]) == 1
    # The secrets dir was never even created (nothing stored).
    assert not secrets.exists() or list(secrets.iterdir()) == []


# --- rotation: a second store updates the handle -----------------------------------------------


def test_store_key_overwrite_is_a_rotation_and_announces_updated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)

    _pipe_stdin(monkeypatch, "sk-ant-FIRST")
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    first = capsys.readouterr().out
    assert "created" in first
    assert _resolve(secrets) == "sk-ant-FIRST"

    _pipe_stdin(monkeypatch, "sk-ant-SECOND")
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    second = capsys.readouterr().out
    assert "updated" in second
    # Resolve returns the NEW value (rotation took effect).
    assert _resolve(secrets) == "sk-ant-SECOND"
    # Still 0600 after a rotation.
    assert stat.S_IMODE(os.stat(secrets / HANDLE).st_mode) == 0o600


# --- the announce never leaks the secret value -------------------------------------------------


def test_store_key_announce_shows_handle_never_the_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _secrets_dir(tmp_path, monkeypatch)
    _pipe_stdin(monkeypatch, SECRET_VALUE)
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    # The HANDLE is announced; the SECRET VALUE never appears on stdout or stderr.
    assert HANDLE in captured.out
    assert SECRET_VALUE not in combined


# --- --from-file reads the file bytes (never argv) ---------------------------------------------


def test_store_key_from_file_reads_the_file_never_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    key_file = tmp_path / "key.txt"
    key_file.write_text(SECRET_VALUE + "\n", encoding="utf-8")  # trailing newline is stripped
    # stdin is NOT consulted when --from-file is given: feed a decoy to prove it is ignored.
    _pipe_stdin(monkeypatch, "DECOY-NEVER-READ")

    assert _cmd_transport(["store-key", "--handle", HANDLE, "--from-file", str(key_file)]) == 0
    assert _resolve(secrets) == SECRET_VALUE
    # The announce still names the handle, never the value.
    captured = capsys.readouterr()
    assert HANDLE in captured.out
    assert SECRET_VALUE not in captured.out + captured.err


def test_store_key_from_file_missing_path_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secrets = _secrets_dir(tmp_path, monkeypatch)
    missing = tmp_path / "nope.txt"
    assert _cmd_transport(["store-key", "--handle", HANDLE, "--from-file", str(missing)]) == 1
    assert not FileSecretBackend(secrets).has(SecretRef.parse(HANDLE))


# --- getpass TTY path (hidden, no echo) --------------------------------------------------------


def test_store_key_tty_prompts_getpass_no_echo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a TTY the value is read via a HIDDEN getpass prompt — never argv, never echoed."""
    secrets = _secrets_dir(tmp_path, monkeypatch)

    # A TTY stdin: isatty() → True, so the getpass branch runs and stdin.read() is never used.
    tty = io.StringIO("STDIN-NEVER-READ-ON-A-TTY")
    monkeypatch.setattr(tty, "isatty", lambda: True)
    monkeypatch.setattr("sys.stdin", tty)

    prompts: list[str] = []

    def fake_getpass(prompt: str = "") -> str:
        prompts.append(prompt)
        return SECRET_VALUE

    monkeypatch.setattr("getpass.getpass", fake_getpass)

    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 0
    assert _resolve(secrets) == SECRET_VALUE
    # getpass was actually used (the hidden, no-echo path) and the prompt names the handle.
    assert prompts and HANDLE in prompts[0]
    # The secret never appears in the announce.
    captured = capsys.readouterr()
    assert SECRET_VALUE not in captured.out + captured.err


# --- fail-closed secrets dir (S-2) -------------------------------------------------------------


def test_store_key_refuses_a_relative_secrets_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative `$OPTIQUITY_SECRETS_DIR` is fail-closed (S-2) — refused before any read/write."""
    monkeypatch.setenv("OPTIQUITY_SECRETS_DIR", "relative/secrets")
    _pipe_stdin(monkeypatch, SECRET_VALUE)
    assert _cmd_transport(["store-key", "--handle", HANDLE]) == 1


# --- no-subcommand usage still names store-key -------------------------------------------------


def test_transport_usage_lists_store_key(capsys: pytest.CaptureFixture[str]) -> None:
    """A bare `transport` (no subcommand) names store-key in the known-subcommand list (exit 2)."""
    assert _cmd_transport([]) == 2
    assert "store-key" in capsys.readouterr().err
