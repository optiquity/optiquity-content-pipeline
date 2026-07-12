"""Plan step-7 scaffolding smoke tests + the PA-5 live-marker sentinel.

The default run (`uv run pytest -q`) must deselect the `live`-marked test via the
pyproject `addopts = "-m 'not live'"`; an explicit CLI `-m live` is the only opt-in
(REC-1: pytest prepends addopts, so a later CLI `-m` wins).
"""

import subprocess
import sys

import pytest

import pipeline


def test_package_importable() -> None:
    """The `pipeline` package installs into the project venv and imports (T8)."""
    assert pipeline.__version__ == "0.1.0"


def test_ruamel_yaml_pin() -> None:
    """The G4 YAML pin (parameter sheet item 2) is the exact version, pure-importable.

    Full YAML 1.2 semantics coverage (Norway problem etc.) lands at step 8; this only
    guards the pin itself so a silent dependency drift fails loudly.
    """
    import ruamel.yaml

    assert ruamel.yaml.__version__ == "0.19.1"


def test_module_entrypoint_help() -> None:
    """`python -m pipeline --help` exits 0 and prints usage (the scripts/pipeline shim target)."""
    result = subprocess.run(
        [sys.executable, "-m", "pipeline", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "usage: pipeline" in result.stdout


def test_module_entrypoint_refuses_unknown_command() -> None:
    """The stub refuses unimplemented subcommands loudly (exit 2, message on stderr)."""
    result = subprocess.run(
        [sys.executable, "-m", "pipeline", "no-such-command"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "unknown command" in result.stderr


@pytest.mark.live
def test_live_marker_sentinel() -> None:
    """PA-5 sentinel: proves the live-marker plumbing end to end.

    Deselected by every default run (pyproject addopts); selected only by an explicit
    CLI `-m live`. It performs NO live transport call — real live smoke tests land at
    step 23 (`tests/test_transport.py`). If this test runs in CI, the PA-5 guarantee
    is broken: ci.yml must never pass the live-marker opt-in.
    """
    assert True
