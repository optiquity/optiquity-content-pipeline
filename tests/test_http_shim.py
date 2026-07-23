"""DR-1 Commit 5a+5b tests: the HTTP shim skeleton + Tier-A dispatch + N-4 mapping, PLUS the
Commit-5b security battery (auth gate + rotation set + redaction + the DoS guard).

The server is driven in-process on `127.0.0.1:0` (an ephemeral port, real socket) so every test
is hermetic + fast — no live subscription, no network. Two dispatch seams are exercised:

* the REAL `invoke()` (with `register_api_handlers()` wiring the exact production surface) — used
  to prove the HTTP door truly reaches the wired handlers (`emit-outline`, the fatal gates);
* an INJECTED `invoke_fn` stub — used to pin the pure serialization / status-mapping / Tier-gating
  behavior crisply and to prove the shim adds no business logic.

Auth is MANDATORY as of Commit 5b (fail-closed), so the harness (`running_server` + `post`) carries
a default test secret + `Authorization: Bearer` header; the security tests override `secrets`/`auth`
to drive the failure paths. All fixtures are obviously generic (`wsA`, §7.4 literal ids); no
instance content.
"""

from __future__ import annotations

import ast
import http.client
import json
import socket
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline.api import http_shim
from pipeline.api import token as token_mod
from pipeline.api.invoke import invoke

PLAN_HASH = "d3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33f0"

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The default auth secret the harness configures + presents (Commit 5b: auth is mandatory). An
#: obvious non-real placeholder; the security tests below drive the wrong/absent/rotation paths.
TEST_SECRET = "shim-test-secret-do-not-ship"


# --------------------------------------------------------------------------- fixtures/harness


@pytest.fixture(autouse=True)
def _clean_registry() -> Iterator[None]:
    """Snapshot/restore the invoke dispatch registry so `register_api_handlers()` never leaks."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


@contextmanager
def running_server(
    *,
    invoke_fn=invoke,
    root: str = ".",
    secrets: frozenset[str] = frozenset({TEST_SECRET}),
    max_body_bytes: int = http_shim.DEFAULT_MAX_BODY_BYTES,
    socket_timeout: float = http_shim.DEFAULT_SOCKET_TIMEOUT_SECONDS,
    allowed_workspaces: frozenset[str] = frozenset(),
) -> Iterator[tuple[str, int]]:
    """Start the shim on an ephemeral loopback port in a daemon thread; yield (host, port). A
    non-empty `secrets` set is required (fail-closed); the harness defaults it to a test secret.
    `allowed_workspaces` drives the Commit-5c served-workspace allow-list (default: unset)."""
    server = http_shim.make_server(
        "127.0.0.1",
        0,
        invoke_fn=invoke_fn,
        root=root,
        secrets=secrets,
        max_body_bytes=max_body_bytes,
        socket_timeout=socket_timeout,
        allowed_workspaces=allowed_workspaces,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield host, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(
    host: str,
    port: int,
    body: object,
    *,
    path: str = http_shim.INVOKE_PATH,
    method: str = "POST",
    auth: str | None = TEST_SECRET,
) -> tuple[int, dict]:
    """POST a body (a dict → JSON, or raw bytes/str passed through) and return (status, json).

    `auth` is sent as `Authorization: Bearer <auth>` (the default is a valid secret); pass
    `auth=None` for the no-auth path or a wrong string for the bad-auth path."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    if isinstance(body, (bytes, bytearray)):
        raw: bytes = bytes(body)
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth is not None:
        headers["Authorization"] = f"Bearer {auth}"
    try:
        conn.request(method, path, body=raw, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        data = resp.read()
    finally:
        conn.close()
    parsed = json.loads(data) if data else {}
    return status, parsed


def post_with_declared_length(
    host: str,
    port: int,
    *,
    declared_length: int,
    actual_body: bytes = b"",
    auth: str | None = TEST_SECRET,
) -> int:
    """POST with a Content-Length header that DECLARES `declared_length` while sending only
    `actual_body` (default: none). Proves the DoS cap acts on the DECLARED length BEFORE reading
    the body — an attacker who claims a huge length is refused without the body being read. Returns
    the HTTP status."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    try:
        conn.putrequest("POST", http_shim.INVOKE_PATH, skip_host=False, skip_accept_encoding=True)
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(declared_length))
        if auth is not None:
            conn.putheader("Authorization", f"Bearer {auth}")
        conn.endheaders()
        if actual_body:
            conn.send(actual_body)
        resp = conn.getresponse()
        status = resp.status
        resp.read()
    finally:
        conn.close()
    return status


@pytest.fixture()
def root(tmp_path: Path) -> str:
    """A framework root with an empty `workspaces/wsA/` so `invoke(root=…)` resolves the store."""
    (tmp_path / "workspaces" / "wsA").mkdir(parents=True)
    return str(tmp_path)


# --------------------------------------------------------------------------- Tier-A round-trip


class TestTierARoundTrip:
    def test_list_round_trips_to_200_matching_direct_invoke(self, root: str) -> None:
        # request -> invoke() -> serialized envelope -> 200; the body is EXACTLY invoke()'s dict
        # (proves the shim only serializes — no business logic).
        from pipeline.api.session import register_api_handlers

        register_api_handlers()
        with running_server(root=root) as (host, port):
            status, body = post(host, port, {"verb": "list", "workspace": "wsA", "params": {}})
        assert status == 200
        assert body["envelope"]["ok"] is True
        assert body["envelope"]["verb"] == "list"
        assert body == invoke("list", "wsA", {}, root=root)

    def test_emit_outline_reaches_the_registered_handler_200(self, root: str) -> None:
        # `emit-outline` is wired by `register_api_handlers()` (session.py:996) but DELIBERATELY
        # left un-CLI-wired in `main_cli`. Prove the HTTP door reaches it: a minimal request
        # returns a per-item block at envelope.ok=True → 200 (NOT HandlerNotWired → 500).
        from pipeline.api.session import register_api_handlers

        register_api_handlers()
        with running_server(root=root) as (host, port):
            status, body = post(
                host, port, {"verb": "emit-outline", "workspace": "wsA", "params": {}}
            )
        assert status == 200
        assert body["envelope"]["ok"] is True
        assert body["envelope"]["verb"] == "emit-outline"
        assert body["results"][0]["status"] == "block"  # the real handler's minimal-input block


# --------------------------------------------------------------------------- N-4 status mapping


class TestStatusMapping:
    def test_pure_mapper_table(self) -> None:
        # The N-4 table, unit-pinned: envelope-is-authority; the two "token" concepts never
        # collapse to 401; cross-workspace is 403.
        def env(ok: bool, code: str | None = None) -> dict:
            e: dict = {"ok": ok, "verb": "v", "workspace": "wsA"}
            if code is not None:
                e["code"] = code
            return {"envelope": e, "results": []}

        assert http_shim.http_status_for(env(True)) == 200
        assert http_shim.http_status_for(env(False, "unknown-verb")) == 400
        assert http_shim.http_status_for(env(False, "invalid-token")) == 422
        assert http_shim.http_status_for(env(False, "isolation-violation")) == 403
        assert http_shim.http_status_for(env(False, "not-found")) == 400  # default fatal
        # 401 is NEVER produced by the mapper (reserved for the Commit-5b auth secret).
        for probe in (env(True), env(False, "invalid-token"), env(False, "unknown-verb")):
            assert http_shim.http_status_for(probe) != 401

    def test_per_item_block_is_200_envelope_is_authority(self) -> None:
        # A per-item BLOCK rides results[] at ok=True → 200 (200 != "all succeeded"). Injected so
        # the block is unambiguous regardless of any handler's business logic.
        def stub(verb, workspace, params, token, *, root):  # noqa: ANN001, ANN202
            return {
                "envelope": {"ok": True, "verb": verb, "workspace": workspace},
                "results": [{"item": "x", "status": "block", "ids": {}}],
            }

        with running_server(invoke_fn=stub) as (host, port):
            status, body = post(host, port, {"verb": "list", "workspace": "wsA"})
        assert status == 200
        assert body["results"][0]["status"] == "block"

    def test_invalid_token_cursor_maps_to_422_not_401(self, root: str) -> None:
        # A §20 session CURSOR failure (a tampered token) is a domain error → 422, NEVER 401.
        from pipeline.api.session import register_api_handlers

        register_api_handlers()
        wire = token_mod.encode(token_mod.mint("wsA", PLAN_HASH))
        wire["plan_hash"] = "0" * 64  # break the digest → invalid-token
        with running_server(root=root) as (host, port):
            status, body = post(
                host, port, {"verb": "list", "workspace": "wsA", "params": {}, "token": wire}
            )
        assert status == 422
        assert status != 401
        assert body["envelope"]["code"] == "invalid-token"

    def test_unknown_operator_verb_maps_to_fatal_400(self, root: str) -> None:
        # An operator verb is structurally excluded from KNOWN_VERBS → invoke() answers
        # `unknown-verb` (whole-invocation fatal) → the mapped 400 (never treated as Tier-B).
        from pipeline.api.session import register_api_handlers

        register_api_handlers()
        with running_server(root=root) as (host, port):
            status, body = post(
                host, port, {"verb": "drift-report", "workspace": "wsA", "params": {}}
            )
        assert status == 400
        assert body["envelope"]["ok"] is False
        assert body["envelope"]["code"] == "unknown-verb"


# --------------------------------------------------------------------------- Tier gating


class TestTierGating:
    def test_classify_verb(self) -> None:
        assert http_shim.classify_verb("list", {}) == http_shim.TIER_A
        assert http_shim.classify_verb("emit-outline", {}) == http_shim.TIER_A
        assert http_shim.classify_verb("begin-session", {}) == http_shim.TIER_A
        assert http_shim.classify_verb("begin-session", {"generate": "none"}) == http_shim.TIER_A
        assert http_shim.classify_verb("continue-session", {"action": "status"}) == http_shim.TIER_A
        assert http_shim.classify_verb("continue-session", {"action": "list"}) == http_shim.TIER_A
        # Tier-B (deferred → 501):
        assert http_shim.classify_verb("render", {}) == http_shim.TIER_B
        assert http_shim.classify_verb("begin-session", {"generate": "full"}) == http_shim.TIER_B
        assert (
            http_shim.classify_verb("continue-session", {"action": "generate-next"})
            == http_shim.TIER_B
        )
        # Unknown → let invoke() answer unknown-verb:
        assert http_shim.classify_verb("drift-report", {}) == http_shim.TIER_UNKNOWN

    def test_tier_b_verb_returns_501_before_touching_invoke(self) -> None:
        # A Tier-B verb is intercepted BEFORE invoke() (the injected stub must never be called).
        def stub(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("invoke() must not be called for a Tier-B verb")

        gen_next = {"action": "generate-next"}
        with running_server(invoke_fn=stub) as (host, port):
            for body in (
                {"verb": "continue-session", "workspace": "wsA", "params": gen_next},
                {"verb": "render", "workspace": "wsA", "params": {"item": "a-0000000000000000"}},
                {"verb": "begin-session", "workspace": "wsA", "params": {"generate": "full"}},
            ):
                status, payload = post(host, port, body)
                assert status == 501, body
                assert payload["error"] == "tier-b-not-served"
                assert payload["verb"] == body["verb"]


# --------------------------------------------------------------------------- robustness


class TestRobustness:
    def test_malformed_body_is_clean_400_not_a_crash(self) -> None:
        with running_server() as (host, port):
            # Invalid JSON → 400; the server survives and answers a following request.
            status, body = post(host, port, b"{not valid json")
            assert status == 400
            assert body["error"] == "bad-request"
            # A JSON array (not an object) → 400.
            status2, _ = post(host, port, b"[1, 2, 3]")
            assert status2 == 400
            # An empty body → 400 (verb/workspace required).
            status3, _ = post(host, port, b"")
            assert status3 == 400
            # The server is still alive (proves the 400s did not crash the thread/socket).
            status4, _ = post(host, port, {"verb": "list"})  # missing workspace → 400
            assert status4 == 400

    def test_missing_verb_or_workspace_is_400(self) -> None:
        with running_server() as (host, port):
            s1, _ = post(host, port, {"workspace": "wsA", "params": {}})
            s2, _ = post(host, port, {"verb": "list", "params": {}})
            s3, _ = post(host, port, {"verb": "list", "workspace": "wsA", "params": []})
        assert (s1, s2, s3) == (400, 400, 400)

    def test_unknown_path_is_404_and_get_is_405(self) -> None:
        with running_server() as (host, port):
            s_path, _ = post(host, port, {"verb": "list", "workspace": "wsA"}, path="/nope")
            s_get, _ = post(host, port, {}, method="GET")
        assert s_path == 404
        assert s_get == 405


# --------------------------------------------------------------------------- `serve` wiring


class TestServeWiring:
    def test_main_help_dispatches(self) -> None:
        # `serve --help` dispatches through argparse (SystemExit(0)) — the entry is wired.
        with pytest.raises(SystemExit) as exc:
            http_shim.main(["--help"])
        assert exc.value.code == 0

    def test_scripts_pipeline_serve_subcommand_resolves(self) -> None:
        # The bash entrypoint routes `serve` to the shim module; `--help` proves the subcommand
        # resolves and argparse is wired (fast: no server starts on --help).
        result = subprocess.run(
            [str(REPO_ROOT / "scripts" / "pipeline"), "serve", "--help"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "pipeline serve" in result.stdout
        assert "--host" in result.stdout and "--port" in result.stdout


# --------------------------------------------------------------------------- Commit 5b: auth


def _ok_stub(verb, workspace, params, token, *, root):  # noqa: ANN001, ANN202
    """A minimal injected `invoke` that returns a valid ok envelope → 200 on a served request."""
    return {"envelope": {"ok": True, "verb": verb, "workspace": workspace}, "results": []}


def _never_invoked(*a, **k):  # noqa: ANN002, ANN003, ANN202
    """An injected `invoke` that MUST NOT be reached (proves a request was refused pre-dispatch)."""
    raise AssertionError("invoke() must not be called: the request should have been refused first")


class TestAuthFailClosed:
    def test_missing_secret_refuses_to_start(self, tmp_path: Path) -> None:
        # (a) The server REFUSES TO START (loud error) with no secret — never fail-open.
        # Via make_server (the server-construction guard, before the socket binds):
        with pytest.raises(http_shim.ShimConfigError):
            http_shim.make_server("127.0.0.1", 0, invoke_fn=invoke, secrets=frozenset())
        # Via the config loader (no env, no instance/shim.yaml) — the loud fail-closed message:
        with pytest.raises(http_shim.ShimConfigError):
            http_shim.load_shim_config(str(tmp_path), env={})

    def test_malformed_yaml_shim_config_fails_closed_no_traceback(self, tmp_path: Path) -> None:
        # A YAML SYNTAX error in instance/shim.yaml (distinct from the non-mapping case) is caught
        # and re-raised as the documented ShimConfigError — never an uncaught ruamel traceback.
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            'auth:\n  secrets:\n    - "unterminated\n', encoding="utf-8"  # unterminated quote
        )
        with pytest.raises(http_shim.ShimConfigError):
            http_shim.load_shim_config(str(tmp_path), env={})
        # main() surfaces it as a clean fail-closed exit (non-zero) with NO traceback escaping.
        rc = http_shim.main(["--root", str(tmp_path), "--port", "0"])
        assert rc == 2

    def test_config_loader_reads_env_and_file_union(self, tmp_path: Path) -> None:
        # The rotation set is a UNION of the env secret(s) and instance/shim.yaml auth.secrets;
        # the DoS caps come from the file. Proves the config source + precedence (no real secret).
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret-a\n    - file-secret-b\n"
            "limits:\n  max_body_bytes: 2048\n  socket_timeout_seconds: 7\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(
            str(tmp_path),
            env={"OPTIQUITY_SHIM_SECRET": "env-secret", "OPTIQUITY_SHIM_SECRETS": "rot-1,rot-2"},
        )
        assert cfg.secrets == frozenset(
            {"file-secret-a", "file-secret-b", "env-secret", "rot-1", "rot-2"}
        )
        assert cfg.max_body_bytes == 2048
        assert cfg.socket_timeout_seconds == 7.0


class TestAuthGate:
    def test_absent_and_wrong_auth_401_correct_auth_200(self) -> None:
        # Absent auth → 401; wrong auth → 401; correct auth + a Tier-A verb → 200.
        with running_server(invoke_fn=_ok_stub) as (host, port):
            s_absent, b_absent = post(host, port, {"verb": "list", "workspace": "wsA"}, auth=None)
            s_wrong, _ = post(host, port, {"verb": "list", "workspace": "wsA"}, auth="wrong-secret")
            s_ok, b_ok = post(host, port, {"verb": "list", "workspace": "wsA"}, auth=TEST_SECRET)
        assert s_absent == 401 and b_absent["error"] == "unauthorized"
        assert s_wrong == 401
        assert s_ok == 200 and b_ok["envelope"]["ok"] is True

    def test_x_api_key_header_also_authenticates(self) -> None:
        # The X-API-Key header is accepted as an alternative to Authorization: Bearer.
        with running_server(invoke_fn=_ok_stub) as (host, port):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            try:
                conn.request(
                    "POST",
                    http_shim.INVOKE_PATH,
                    body=json.dumps({"verb": "list", "workspace": "wsA"}).encode(),
                    headers={"Content-Type": "application/json", "X-API-Key": TEST_SECRET},
                )
                resp = conn.getresponse()
                status = resp.status
                resp.read()
            finally:
                conn.close()
        assert status == 200

    def test_rotation_set_accepts_old_and_new(self) -> None:
        # With a 2-secret set, BOTH the old and the new secret authenticate (seamless rotation);
        # any other secret is refused.
        secrets = frozenset({"old-secret", "new-secret"})
        with running_server(invoke_fn=_ok_stub, secrets=secrets) as (host, port):
            s_old, _ = post(host, port, {"verb": "list", "workspace": "wsA"}, auth="old-secret")
            s_new, _ = post(host, port, {"verb": "list", "workspace": "wsA"}, auth="new-secret")
            s_other, _ = post(host, port, {"verb": "list", "workspace": "wsA"}, auth="third-secret")
        assert s_old == 200
        assert s_new == 200
        assert s_other == 401

    def test_auth_uses_hmac_compare_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The comparison is constant-time: assert hmac.compare_digest is what the gate calls (a
        # timing test is not required). Spy delegates to the real compare_digest.
        calls: list[tuple[object, object]] = []
        real = http_shim.hmac.compare_digest

        def spy(a: object, b: object) -> bool:
            calls.append((a, b))
            return real(a, b)

        monkeypatch.setattr(http_shim.hmac, "compare_digest", spy)
        with running_server(invoke_fn=_ok_stub) as (host, port):
            post(host, port, {"verb": "list", "workspace": "wsA"}, auth=TEST_SECRET)
        assert calls, "the auth gate must compare via hmac.compare_digest (constant-time)"


class TestRedaction:
    def test_secret_and_auth_header_never_logged_or_echoed(
        self, capfd: pytest.CaptureFixture[str]
    ) -> None:
        # N-7: neither the configured secret nor the presented header value appears in any captured
        # log output OR in a response body — on the failure path (401) or the success path (200).
        configured = "CONFIGUREDSECRETMARKER-never-log-9f3a"
        presented_bad = "PRESENTEDBADTOKEN-never-log-7c21"
        req = {"verb": "list", "workspace": "wsA"}
        with running_server(invoke_fn=_ok_stub, secrets=frozenset({configured})) as (host, port):
            s_bad, b_bad = post(host, port, req, auth=presented_bad)
            s_ok, b_ok = post(host, port, req, auth=configured)
        assert s_bad == 401 and s_ok == 200
        out, err = capfd.readouterr()
        haystack = out + err + json.dumps(b_bad) + json.dumps(b_ok)
        assert configured not in haystack
        assert presented_bad not in haystack


class TestDoSGuard:
    def test_oversized_declared_length_413_before_body_read(self) -> None:
        # An over-cap DECLARED Content-Length is refused (413) BEFORE the body is read: invoke() is
        # never reached (the stub would raise → 500) and no body is even sent. 413, not 400/500.
        with running_server(invoke_fn=_never_invoked, max_body_bytes=256) as (host, port):
            status = post_with_declared_length(
                host, port, declared_length=10_000_000, actual_body=b"", auth=TEST_SECRET
            )
        assert status == 413

    def test_auth_is_checked_before_the_body_is_consumed(self) -> None:
        # Auth precedes BOTH the DoS cap and the body read. An unauthenticated oversized request →
        # 401 (not 413); an unauthenticated garbage body → 401 (not a 400 parse error). invoke()
        # is never reached in either case.
        with running_server(invoke_fn=_never_invoked, max_body_bytes=256) as (host, port):
            s_oversized_noauth = post_with_declared_length(
                host, port, declared_length=10_000_000, actual_body=b"", auth=None
            )
            s_garbage_badauth, b_garbage = post(host, port, b"{ not json", auth="wrong-secret")
        assert s_oversized_noauth == 401  # auth before the 413 cap and before any body read
        assert s_garbage_badauth == 401  # auth before the JSON parse path
        assert b_garbage["error"] == "unauthorized"

    def test_authenticated_malformed_body_is_clean_400(self) -> None:
        # 5a behaviour preserved: an AUTHENTICATED but malformed body still gets a clean 400.
        with running_server(invoke_fn=_never_invoked) as (host, port):
            status, body = post(host, port, b"{ not json", auth=TEST_SECRET)
        assert status == 400
        assert body["error"] == "bad-request"

    def test_socket_timeout_drops_a_stalled_client(self) -> None:
        # Slow-loris guard: a client that sends partial headers and then stalls is dropped by the
        # server's socket timeout (the connection closes → recv returns b'').
        with running_server(invoke_fn=_ok_stub, socket_timeout=0.5) as (host, port):
            sock = socket.create_connection((host, port), timeout=5)
            try:
                sock.sendall(b"POST /invoke HTTP/1.1\r\nHost: x\r\n")  # partial: no blank line
                sock.settimeout(5)
                data = sock.recv(1024)  # server closes after ~0.5s → EOF
            finally:
                sock.close()
        assert data == b""


# ---------------------------------------------------------- Commit 5c: workspace allow-list


def _seen_stub(seen: list[str]):  # noqa: ANN202
    """An injected `invoke` that records each dispatched workspace and returns an ok envelope.
    Used to PROVE a non-served workspace never reaches dispatch (its name never lands in `seen`)."""

    def stub(verb, workspace, params, token, *, root):  # noqa: ANN001, ANN202
        seen.append(workspace)
        return {"envelope": {"ok": True, "verb": verb, "workspace": workspace}, "results": []}

    return stub


class TestWorkspaceAllowList:
    def test_configured_dispatches_listed_refuses_non_listed(self) -> None:
        # Allow-list CONFIGURED: a LISTED workspace passes to dispatch (200); a NON-listed one is
        # refused 403 `workspace-not-served` BEFORE dispatch — invoke_fn is NOT called for it
        # (proved by the recorded `seen` list containing only the listed workspace).
        seen: list[str] = []
        with running_server(
            invoke_fn=_seen_stub(seen), allowed_workspaces=frozenset({"wsA"})
        ) as (host, port):
            s_listed, b_listed = post(host, port, {"verb": "list", "workspace": "wsA"})
            s_denied, b_denied = post(host, port, {"verb": "list", "workspace": "wsB"})
        assert s_listed == 200 and b_listed["envelope"]["ok"] is True
        assert s_denied == 403 and b_denied["error"] == "workspace-not-served"
        assert seen == ["wsA"]  # the non-listed request NEVER reached invoke()

    def test_unset_serves_any_contained_workspace(self) -> None:
        # Allow-list UNSET (the default): a request for ANY workspace passes to dispatch (200),
        # proving the optional-when-unset semantics (containment stays invoke()'s GAP-9 gate).
        seen: list[str] = []
        with running_server(invoke_fn=_seen_stub(seen)) as (host, port):  # unset
            for ws in ("wsA", "wsB", "another-ws"):
                status, body = post(host, port, {"verb": "list", "workspace": ws})
                assert status == 200, ws
                assert body["envelope"]["ok"] is True
        assert seen == ["wsA", "wsB", "another-ws"]

    def test_allow_list_precedes_tier_gating(self) -> None:
        # A non-listed workspace is refused 403 BEFORE tier classification — even a Tier-B verb
        # gets `workspace-not-served` (403), NOT 501. Policy (is this workspace served?) precedes
        # tier routing; `_never_invoked` proves dispatch is never reached.
        with running_server(
            invoke_fn=_never_invoked, allowed_workspaces=frozenset({"wsA"})
        ) as (host, port):
            status, body = post(
                host,
                port,
                {"verb": "render", "workspace": "wsB", "params": {"item": "a-0000000000000000"}},
            )
        assert status == 403
        assert body["error"] == "workspace-not-served"

    def test_escaping_name_surfaced_from_invoke_gap9_when_unset(self, root: str) -> None:
        # Allow-list UNSET → an ESCAPING workspace name (`../victim`) flows to the REAL invoke(),
        # whose LANDED GAP-9 resolve-and-contain gate refuses it as `isolation-violation` → 403.
        # The shim SURFACES that refusal; it does NOT re-implement the path check. The 403 body is
        # the fatal `isolation-violation` envelope — DISTINCT from the allow-list's
        # `workspace-not-served` shape.
        from pipeline.api.session import register_api_handlers

        register_api_handlers()
        with running_server(root=root) as (host, port):  # real invoke(), allow-list unset
            status, body = post(
                host, port, {"verb": "list", "workspace": "../victim", "params": {}}
            )
        assert status == 403
        assert body["envelope"]["ok"] is False
        assert body["envelope"]["code"] == "isolation-violation"
        assert body.get("error") != "workspace-not-served"  # NOT the shim policy shape

    def test_escaping_name_refused_by_allow_list_when_configured(self) -> None:
        # The OTHER branch: with a CONFIGURED allow-list that does not list the escaping name, the
        # shim's NAME-membership policy refuses it 403 `workspace-not-served` BEFORE invoke()
        # (still 403). Proves the allow-list does not need to — and does not — re-validate the
        # path; a misconfig cannot defeat GAP-9 because invoke() is the containment authority.
        with running_server(
            invoke_fn=_never_invoked, allowed_workspaces=frozenset({"wsA"})
        ) as (host, port):
            status, body = post(host, port, {"verb": "list", "workspace": "../victim"})
        assert status == 403
        assert body["error"] == "workspace-not-served"

    def test_shim_does_not_reimplement_gap9_path_validation(self) -> None:
        # STATIC guard: http_shim.py must not IMPORT the GAP-9 containment module nor CALL its
        # resolve-and-contain names in code (docstrings/comments referencing them are fine — they
        # are not Name/Attribute nodes). Proves the allow-list is NAME membership ONLY, never a
        # duplicated path check.
        src = (REPO_ROOT / "pipeline" / "api" / "http_shim.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "pipeline.workspace_name", "shim must not import GAP-9 guard"
            if isinstance(node, ast.Import):
                assert all("workspace_name" not in n.name for n in node.names)
        code_names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
        }
        assert "validate_workspace_name" not in code_names
        assert "WorkspaceNameError" not in code_names
        # no Path.resolve() → no resolve-and-contain re-implementation in the shim:
        assert "resolve" not in code_names


# ------------------------------------------------------------- Commit 5c: config (allow-list/bind)


class TestAllowListAndBindConfig:
    def test_allow_list_loads_from_shim_yaml(self, tmp_path: Path) -> None:
        # workspaces.allowed loads from instance/shim.yaml as a SET (env-independent).
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret\n"
            "workspaces:\n  allowed:\n    - wsA\n    - wsB\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        assert cfg.allowed_workspaces == frozenset({"wsA", "wsB"})

    def test_allow_list_single_string_is_one_element(self, tmp_path: Path) -> None:
        # A single string under workspaces.allowed is accepted as a one-element allow-list.
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret\nworkspaces:\n  allowed: soloworkspace\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        assert cfg.allowed_workspaces == frozenset({"soloworkspace"})

    def test_allow_list_unset_is_empty(self, tmp_path: Path) -> None:
        # No workspaces block → the allow-list is UNSET (empty) → serve any contained workspace.
        cfg = http_shim.load_shim_config(str(tmp_path), env={"OPTIQUITY_SHIM_SECRET": "s"})
        assert cfg.allowed_workspaces == frozenset()

    def test_default_bind_is_loopback(self, tmp_path: Path) -> None:
        # The default bind is 127.0.0.1 (the module constant AND an unset-config load).
        assert http_shim.DEFAULT_HOST == "127.0.0.1"
        cfg = http_shim.load_shim_config(str(tmp_path), env={"OPTIQUITY_SHIM_SECRET": "s"})
        assert cfg.bind_host == "127.0.0.1"

    def test_bind_host_knob_read_from_config(self, tmp_path: Path) -> None:
        # bind.host is read from instance/shim.yaml (a non-loopback value is honored but is the
        # operator's conscious choice; serve() warns on it — see the module docstring).
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret\nbind:\n  host: 0.0.0.0\n", encoding="utf-8"
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        assert cfg.bind_host == "0.0.0.0"

    def test_config_allow_list_drives_server_enforcement(self, tmp_path: Path) -> None:
        # END-TO-END: the allow-list loaded from instance/shim.yaml DRIVES the server — a listed
        # workspace dispatches (200), a non-listed one is refused 403 without reaching invoke().
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            f"auth:\n  secrets:\n    - {TEST_SECRET}\nworkspaces:\n  allowed:\n    - wsA\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        seen: list[str] = []
        with running_server(
            invoke_fn=_seen_stub(seen),
            secrets=cfg.secrets,
            allowed_workspaces=cfg.allowed_workspaces,
        ) as (host, port):
            s_ok, _ = post(host, port, {"verb": "list", "workspace": "wsA"})
            s_no, b_no = post(host, port, {"verb": "list", "workspace": "wsB"})
        assert s_ok == 200
        assert s_no == 403 and b_no["error"] == "workspace-not-served"
        assert seen == ["wsA"]
