"""G2 tests: the subscription controlled-settings WALL (plan G2, §21.10, S-4).

The wall STRENGTHENS the env-only F10 strip, which is necessary-but-INSUFFICIENT: a
`settings.json` `apiKeyHelper` supplies an api key at auth time with NO env var involved. Every
subscription spawn — generation AND the research seam — is pinned under pipeline-controlled
settings that provably define NO `apiKeyHelper` (`--settings <controlled-file>` +
`--setting-sources ""`, NEVER `--bare`); any un-provable state (a managed/enterprise apiKeyHelper
`--setting-sources` cannot exclude — the S-4 hole; an unverifiable controlled file) is a LOUD typed
refusal, never an uncontrolled spawn.

The MANAGED case is DETECT-and-REFUSE (the maintainer's money-safety-first default): a simulated
managed `apiKeyHelper` → refuse. The residual (detection completeness + a TOCTOU window) is named
in `pipeline/transport.py`'s wall section.

All subprocess-MOCKED via a fake `Runner` (no real process spawned). The CLI settings mechanism was
verified out-of-band on the pinned CLI 2.1.223: a bogus `--setting-sources` value errors; the empty
list is accepted and loads no ambient source; a missing `--settings` file is eagerly rejected. NO
spend; NO api-key path is built at G2.
"""

from __future__ import annotations

import json

import pytest

import pipeline.transport as transport
from pipeline.__main__ import _transport_llm_call
from pipeline.spend.wall import (
    SETTING_SOURCES_NONE,
    ControlledSettingsError,
    ManagedApiKeyHelperError,
    SubscriptionWall,
    SubscriptionWallError,
    build_subscription_wall,
)
from pipeline.transport import (
    ANTHROPIC_API_KEY_ENV,
    ANTHROPIC_AUTH_TOKEN_ENV,
    CLAUDE_CODE_USE_BEDROCK_ENV,
    CLAUDE_CODE_USE_FOUNDRY_ENV,
    CLAUDE_CODE_USE_VERTEX_ENV,
    DISABLE_AUTO_MEMORY_ENV,
    F10_STRIPPED_ENV_VARS,
    ProcessOutcome,
    ProcessRequest,
    invoke_headless,
)

SUCCESS_JSON = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "OK",
        "total_cost_usd": 0.0,
        "terminal_reason": "completed",
    }
)


class FakeRunner:
    """A recording process seam: one scripted `ProcessOutcome`, zero subprocesses."""

    def __init__(self, outcome: ProcessOutcome) -> None:
        self.outcome = outcome
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        return self.outcome

    @property
    def call_count(self) -> int:
        return len(self.requests)


def _ok() -> ProcessOutcome:
    return ProcessOutcome(timed_out=False, returncode=0, stdout=SUCCESS_JSON, stderr="")


def _arg_after(argv: tuple[str, ...], flag: str) -> str:
    return argv[argv.index(flag) + 1]


@pytest.fixture
def safe_managed(monkeypatch):
    """Force the managed tier to 'known platform, no managed files' so wall tests are
    deterministic across dev/CI regardless of the host's real /Library or /etc contents."""
    monkeypatch.setattr(transport, "_managed_settings_paths", lambda: ())


# ---------------------------------------------------------------------------
# The wall lives in transport (no-cycle invariant) and is re-exported by spend.wall.
# ---------------------------------------------------------------------------


def test_wall_api_reaches_the_spend_package_but_the_primitive_lives_in_transport():
    # spend.wall re-exports the transport primitive: transport imports NOTHING from spend (the
    # no-cycle invariant pinned in pipeline/spend/__init__.py), so the wall — which must fire at
    # the transport chokepoint — lives in transport and spend.wall is the spend-facing home.
    assert build_subscription_wall.__module__ == "pipeline.transport"
    assert issubclass(ManagedApiKeyHelperError, SubscriptionWallError)
    assert issubclass(ControlledSettingsError, SubscriptionWallError)
    assert SETTING_SOURCES_NONE == ""


# ---------------------------------------------------------------------------
# The controlled-settings argv (no --bare; --setting-sources "" excludes ambient sources).
# ---------------------------------------------------------------------------


def test_wall_argv_carries_controlled_settings_and_empty_setting_sources():
    wall = build_subscription_wall(managed_settings_paths=[])
    assert isinstance(wall, SubscriptionWall)
    argv = wall.argv
    assert "--bare" not in argv  # NEVER the API-key-only mode (an F10 violation)
    assert _arg_after(argv, "--settings") == str(wall.settings_path)
    assert _arg_after(argv, "--setting-sources") == ""  # empty => load ZERO ambient sources


def test_wall_controlled_file_is_an_object_free_of_apikey_helper():
    wall = build_subscription_wall(managed_settings_paths=[])
    body = json.loads(wall.settings_path.read_text(encoding="utf-8"))
    assert isinstance(body, dict)
    assert "apiKeyHelper" not in body  # the whole point: the controlled file defines none


# ---------------------------------------------------------------------------
# The MANAGED case (S-4): detect-and-refuse.
# ---------------------------------------------------------------------------


def test_managed_apikey_helper_present_fails_closed(tmp_path):
    """A simulated MANAGED/ENTERPRISE apiKeyHelper (the tier --setting-sources cannot exclude)
    → the wall FAILS CLOSED with a typed refusal (never an uncontrolled spawn)."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"apiKeyHelper": "/usr/local/bin/get-key"}), encoding="utf-8")
    with pytest.raises(ManagedApiKeyHelperError) as excinfo:
        build_subscription_wall(managed_settings_paths=[managed])
    assert excinfo.value.code == "managed-apikey-helper"


def test_managed_env_block_reinjecting_a_stripped_var_fails_closed(tmp_path):
    """Defense: a managed `env` block re-injecting a stripped auth/provider var would survive the
    process-env strip (the CLI applies managed env) — so it is also a detect-and-refuse hazard."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"env": {CLAUDE_CODE_USE_BEDROCK_ENV: "1"}}), encoding="utf-8")
    with pytest.raises(ManagedApiKeyHelperError):
        build_subscription_wall(managed_settings_paths=[managed])


def test_managed_present_but_unparseable_fails_closed(tmp_path):
    """A managed file that exists but cannot be read/parsed is UN-PROVABLE → refuse (fail-closed);
    the wall never assumes an unreadable managed tier is safe."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text("{ this is not valid json", encoding="utf-8")
    with pytest.raises(ManagedApiKeyHelperError):
        build_subscription_wall(managed_settings_paths=[managed])


def test_managed_absent_is_provably_safe(tmp_path):
    """An ABSENT managed file is provably safe — the wall proceeds with the strongest exclusion."""
    wall = build_subscription_wall(managed_settings_paths=[tmp_path / "nonexistent.json"])
    assert "--settings" in wall.argv  # no refusal


def test_managed_present_without_a_hazard_is_safe(tmp_path):
    """A managed file with real policy but no api-key hazard does NOT trip the wall."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"permissions": {"allow": ["Read"]}}), encoding="utf-8")
    wall = build_subscription_wall(managed_settings_paths=[managed])
    assert _arg_after(wall.argv, "--setting-sources") == ""


def test_unknown_platform_fails_closed(monkeypatch):
    """On a platform whose managed-settings path is unknown, absence cannot be PROVEN → refuse."""
    monkeypatch.setattr(transport.sys, "platform", "plan9-exotic")
    with pytest.raises(ManagedApiKeyHelperError):
        build_subscription_wall()  # default managed resolution cannot locate the tier → refuse


# ---------------------------------------------------------------------------
# An AMBIENT (user/project/local) apiKeyHelper is excluded by --setting-sources "".
# ---------------------------------------------------------------------------


def test_ambient_apikey_helper_is_excluded_by_empty_setting_sources(tmp_path):
    """An ambient user/project/local apiKeyHelper never loads: the wall passes --setting-sources
    "" (empty => load ZERO ambient sources; verified on CLI 2.1.223) and --settings points ONLY
    at the controlled file — never the ambient one. The argv IS the proof of exclusion."""
    ambient = tmp_path / "user-settings.json"
    ambient.write_text(json.dumps({"apiKeyHelper": "/bin/echo AMBIENT-KEY"}), encoding="utf-8")
    wall = build_subscription_wall(managed_settings_paths=[])
    assert _arg_after(wall.argv, "--setting-sources") == ""  # ambient sources excluded wholesale
    assert str(ambient) not in wall.argv  # the ambient apiKeyHelper file is never referenced
    assert _arg_after(wall.argv, "--settings") == str(wall.settings_path)  # only the controlled one


# ---------------------------------------------------------------------------
# A missing/unverifiable controlled-settings file → loud fail-closed refuse.
# ---------------------------------------------------------------------------


def test_unwritable_controlled_file_fails_closed(tmp_path):
    """If the controlled file cannot be written/read/verified → a typed refuse, never a fallback
    to an uncontrolled spawn (plan G2 item 4)."""
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    doomed = blocker / "controlled.json"  # parent is a FILE => mkdir(parents=True) raises
    with pytest.raises(ControlledSettingsError) as excinfo:
        build_subscription_wall(managed_settings_paths=[], controlled_settings_path=doomed)
    assert excinfo.value.code == "controlled-settings"


# ---------------------------------------------------------------------------
# invoke_headless applies the wall on EVERY subscription spawn (generation path).
# ---------------------------------------------------------------------------


def test_invoke_headless_subscription_spawn_carries_the_wall(safe_managed):
    fake = FakeRunner(_ok())
    result = invoke_headless("hi", runner=fake)
    assert result.status == "ok"
    argv = fake.requests[0].argv
    assert "--bare" not in argv
    assert "--settings" in argv
    assert _arg_after(argv, "--setting-sources") == ""


def test_invoke_headless_fails_closed_on_managed_apikey_helper(tmp_path, monkeypatch):
    """A managed apiKeyHelper on the invoke path → invoke_headless refuses and NEVER spawns."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"apiKeyHelper": "/usr/local/bin/get-key"}), encoding="utf-8")
    monkeypatch.setattr(transport, "_managed_settings_paths", lambda: (managed,))
    fake = FakeRunner(_ok())
    with pytest.raises(ManagedApiKeyHelperError):
        invoke_headless("hi", runner=fake)
    assert fake.call_count == 0  # refused BEFORE any spawn — no unwalled/uncontrolled call


def test_widened_f10_strip_on_the_subscription_spawn(safe_managed):
    """The widened vars (ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_USE_*) are stripped from the child env
    of a real subscription spawn, alongside the auto-memory kill switch staying set."""
    base = {
        "PATH": "/usr/bin",
        ANTHROPIC_AUTH_TOKEN_ENV: "sk-auth-token",
        CLAUDE_CODE_USE_BEDROCK_ENV: "1",
        CLAUDE_CODE_USE_VERTEX_ENV: "1",
        CLAUDE_CODE_USE_FOUNDRY_ENV: "1",
    }
    fake = FakeRunner(_ok())
    invoke_headless("hi", runner=fake, base_env=base)
    env = fake.requests[0].env
    for var in (
        ANTHROPIC_AUTH_TOKEN_ENV,
        CLAUDE_CODE_USE_BEDROCK_ENV,
        CLAUDE_CODE_USE_VERTEX_ENV,
        CLAUDE_CODE_USE_FOUNDRY_ENV,
    ):
        assert var not in env
    assert env[DISABLE_AUTO_MEMORY_ENV] == "1"


def test_f10_stripped_env_vars_covers_the_widened_set():
    assert ANTHROPIC_API_KEY_ENV in F10_STRIPPED_ENV_VARS
    for var in (
        ANTHROPIC_AUTH_TOKEN_ENV,
        CLAUDE_CODE_USE_BEDROCK_ENV,
        CLAUDE_CODE_USE_VERTEX_ENV,
        CLAUDE_CODE_USE_FOUNDRY_ENV,
    ):
        assert var in F10_STRIPPED_ENV_VARS


# ---------------------------------------------------------------------------
# EVERY subscription spawn path — including the research seam — goes through the wall.
# ---------------------------------------------------------------------------


def test_research_seam_spawn_goes_through_the_wall(safe_managed):
    """The research seam (`__main__._transport_llm_call`) routes through invoke_headless, so its
    spawn carries the controlled-settings wall — no unwalled research spawn."""
    recorded: dict = {}

    def runner(request):
        recorded["argv"] = tuple(request.argv)
        return _ok()

    seam = _transport_llm_call(runner=runner)
    seam("hello", budget=0.5)
    argv = recorded["argv"]
    assert "--bare" not in argv
    assert "--settings" in argv
    assert _arg_after(argv, "--setting-sources") == ""


def test_research_seam_fails_closed_on_managed_apikey_helper(tmp_path, monkeypatch):
    """The research seam inherits the fail-closed wall: managed apiKeyHelper → refuse, no spawn."""
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"apiKeyHelper": "/usr/local/bin/get-key"}), encoding="utf-8")
    monkeypatch.setattr(transport, "_managed_settings_paths", lambda: (managed,))
    called = {"n": 0}

    def runner(request):
        called["n"] += 1
        return _ok()

    seam = _transport_llm_call(runner=runner)
    with pytest.raises(ManagedApiKeyHelperError):
        seam("hello", budget=0.5)
    assert called["n"] == 0  # the research seam never spawns past the wall


def test_injected_api_key_still_refuses_before_the_wall(safe_managed):
    """F10 order: an explicit ANTHROPIC_API_KEY override is refused by build_child_env BEFORE the
    wall (both are pre-spawn refusals) — the runner is never called either way."""
    fake = FakeRunner(_ok())
    with pytest.raises(transport.ApiKeyPresentError):
        invoke_headless("hi", runner=fake, env_overrides={ANTHROPIC_API_KEY_ENV: "sk-x"})
    assert fake.call_count == 0
