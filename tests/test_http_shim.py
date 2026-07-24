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
from types import SimpleNamespace

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline.api import http_shim
from pipeline.api import token as token_mod
from pipeline.api.invoke import invoke
from pipeline.store import WorkspaceStore

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
    allowed_callback_hosts: frozenset[str] = frozenset(),
    spawn_fn=None,
    plan_targets_fn=None,
    render_target_fn=None,
    clock_fn=None,
    render_sync_wait_seconds=None,
    live_count_fn=None,
) -> Iterator[tuple[str, int]]:
    """Start the shim on an ephemeral loopback port in a daemon thread; yield (host, port). A
    non-empty `secrets` set is required (fail-closed); the harness defaults it to a test secret.
    `allowed_workspaces` drives the Commit-5c served-workspace allow-list (default: unset);
    `allowed_callback_hosts` drives the W3b webhook callback allow-list (default: unset = callbacks
    off). `spawn_fn`/`plan_targets_fn`/`render_target_fn`/`clock_fn`/`render_sync_wait_seconds` are
    the Commit-6/8 Tier-B seams (default: the real ones; set `render_sync_wait_seconds=0` to make a
    minting render's optimistic-sync return an INSTANT 202 with no real sleep). `live_count_fn` is
    the DR-1 Commit-10 ADVISORY-cap seam (default: the real PresenceRegistry-backed count; seed it
    at/over MAX_PARALLEL_SESSIONS to drive the 429 refusal without spawning real runners)."""
    server = http_shim.make_server(
        "127.0.0.1",
        0,
        invoke_fn=invoke_fn,
        root=root,
        secrets=secrets,
        max_body_bytes=max_body_bytes,
        socket_timeout=socket_timeout,
        allowed_workspaces=allowed_workspaces,
        allowed_callback_hosts=allowed_callback_hosts,
        spawn_fn=spawn_fn,
        plan_targets_fn=plan_targets_fn,
        render_target_fn=render_target_fn,
        clock_fn=clock_fn,
        render_sync_wait_seconds=render_sync_wait_seconds,
        live_count_fn=live_count_fn,
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
        # Commit 6 PROMOTED the cheap continue-session actions from Tier-B to Tier-A (read/
        # side-output, LLM-free) — no longer a 501:
        for cheap in ("fetch", "get", "add-to-folio", "emit-manifest"):
            assert (
                http_shim.classify_verb("continue-session", {"action": cheap}) == http_shim.TIER_A
            ), cheap
        # Tier-B: the minting render (SERVED, Commit 8), begin-session{generate!=none} (still
        # deferred, Commit 9), and the paid generate-next (the Commit-6 submit door):
        assert http_shim.classify_verb("render", {}) == http_shim.TIER_B
        assert http_shim.classify_verb("begin-session", {"generate": "full"}) == http_shim.TIER_B
        assert (
            http_shim.classify_verb("continue-session", {"action": "generate-next"})
            == http_shim.TIER_B
        )
        # Unknown → let invoke() answer unknown-verb:
        assert http_shim.classify_verb("drift-report", {}) == http_shim.TIER_UNKNOWN

    def test_still_deferred_tier_b_verb_returns_501_before_touching_invoke(self) -> None:
        # The STILL-DEFERRED Tier-B verb `begin-session{generate!=none}` (Commit 9) is intercepted
        # BEFORE invoke() (the injected stub must never be called). Commit 6 (generate-next) and
        # Commit 8 (the minting render) are SERVED async doors, no longer 501 (covered below).
        def stub(*a, **k):  # noqa: ANN002, ANN003, ANN202
            raise AssertionError("invoke() must not be called for a deferred Tier-B verb")

        with running_server(invoke_fn=stub) as (host, port):
            body = {"verb": "begin-session", "workspace": "wsA", "params": {"generate": "full"}}
            status, payload = post(host, port, body)
            assert status == 501, body
            assert payload["error"] == "tier-b-not-served"
            assert payload["verb"] == body["verb"]

    def test_cheap_continue_session_fetch_is_tier_a_200_not_501(self) -> None:
        # Commit 6: continue-session{fetch} is now Tier-A → it reaches invoke() (200), NOT a 501.
        with running_server(invoke_fn=_ok_stub) as (host, port):
            status, body = post(
                host,
                port,
                {"verb": "continue-session", "workspace": "wsA", "params": {"action": "fetch"}},
            )
        assert status == 200
        assert body["envelope"]["ok"] is True


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

    def test_callback_hosts_load_from_shim_yaml(self, tmp_path: Path) -> None:
        # W3b: callbacks.allowed_hosts loads from instance/shim.yaml as a SET (env-independent),
        # mirroring workspaces.allowed. Placeholder hosts only.
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret\n"
            "callbacks:\n  allowed_hosts:\n    - hooks.example.com\n    - other.example.com:5678\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        assert cfg.allowed_callback_hosts == frozenset(
            {"hooks.example.com", "other.example.com:5678"}
        )

    def test_callback_hosts_single_string_is_one_element(self, tmp_path: Path) -> None:
        # A single string under callbacks.allowed_hosts is accepted as a one-element allow-list.
        (tmp_path / "instance").mkdir()
        (tmp_path / "instance" / "shim.yaml").write_text(
            "auth:\n  secrets:\n    - file-secret\n"
            "callbacks:\n  allowed_hosts: hooks.example.com\n",
            encoding="utf-8",
        )
        cfg = http_shim.load_shim_config(str(tmp_path), env={})
        assert cfg.allowed_callback_hosts == frozenset({"hooks.example.com"})

    def test_callback_hosts_unset_is_empty_opt_in_off(self, tmp_path: Path) -> None:
        # No callbacks block → the allow-list is UNSET (empty) → callbacks are OPT-IN OFF (a submit
        # carrying callback_url is later refused 400 `callbacks-disabled`).
        cfg = http_shim.load_shim_config(str(tmp_path), env={"OPTIQUITY_SHIM_SECRET": "s"})
        assert cfg.allowed_callback_hosts == frozenset()

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


# --------------------------------------------------- Commit 6: Tier-B generate-next submit + poll
#
# These drive the REAL contained store (a tmp `workspaces/wsA/`) but inject the LIGHT seams the task
# sanctions — the SPAWNER (no real subprocess) and the PLAN-TARGETS resolver (no heavy plan setup) —
# plus a settable clock to drive the job-lifetime / re-drivable windows. The REAL detached spawn +
# real plan resolution are the Commit-I integration harness.

#: A generic §7.4 artifact id the plan-targets stub hands back as the predictable target.
ART_ID = "a-0000000000000001"


def _valid_token(workspace: str = "wsA") -> dict:
    """A minimal VALID wire token (decodes against `workspace`); the injected plan-targets stub
    ignores its inputs, so an empty-input token is enough for the submit tests."""
    return token_mod.encode(token_mod.mint(workspace, PLAN_HASH))


def _fixed_targets(ids: list[str]):  # noqa: ANN202
    """A `plan_targets_fn` seam stub returning FIXED predictable ids (no live plan resolution)."""

    def resolver(root, workspace, decoded, params):  # noqa: ANN001, ANN202
        return list(ids)

    return resolver


def _spawn_recorder(calls: list):  # noqa: ANN202
    """A `spawn_fn` seam stub recording each (spec, spawn_dir) — proves the detach happened once."""

    def spawn(spec, *, spawn_dir):  # noqa: ANN001, ANN202
        calls.append((spec, spawn_dir))
        return None

    return spawn


def _fetch_stub(verb, workspace, params, token, *, root):  # noqa: ANN001, ANN202
    """An injected invoke() that SERVES fetch-by-id — the DONE path fetches the materialized
    output via the existing handler; anything else is a trivial ok envelope."""
    if verb == "fetch-by-id":
        return {
            "envelope": {"ok": True, "verb": verb, "workspace": workspace},
            "results": [
                {
                    "item": params.get("id"),
                    "status": "ok",
                    "context": {"path": f"output/{params.get('id')}"},
                }
            ],
        }
    return {"envelope": {"ok": True, "verb": verb, "workspace": workspace}, "results": []}


class _FakeClock:
    """A settable clock for driving the job-lifetime / re-drivable windows deterministically."""

    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def poll(host, port, *, workspace, key, target_ids, auth=TEST_SECRET):  # noqa: ANN001, ANN201
    """POST /poll {workspace, key, target_ids} → (status, json)."""
    return post(
        host,
        port,
        {"workspace": workspace, "key": key, "target_ids": target_ids},
        path=http_shim.POLL_PATH,
        auth=auth,
    )


def _submit_gen_next(  # noqa: ANN201
    host, port, *, workspace="wsA", idem="exec-1", token=None, callback_url=None
):  # noqa: ANN001
    """POST a generate-next submit (a valid token by default). `callback_url`, when given, rides in
    params (W3b) — omitted entirely when None so the poll-only path is exercised unchanged."""
    params = {"action": "generate-next", "idempotency_key": idem}
    if callback_url is not None:
        params["callback_url"] = callback_url
    return post(
        host,
        port,
        {
            "verb": "continue-session",
            "workspace": workspace,
            "params": params,
            "token": token if token is not None else _valid_token(workspace),
        },
    )


class TestTierBSubmit:
    def test_submit_202_key_derivation_and_single_spawn_injected_targets(self, root: str) -> None:
        # KEY-DERIVATION + spawn wiring (uses the INJECTED `_fixed_targets` seam — NOT a selection
        # proof; the EXACT batch selection is proven by
        # `test_session.py::test_plan_next_batch_ids_equals_generate_next_batch`). A generate-next
        # submit → 202 + the target-ids the ack echoes; JobStore.submit wrote the run-family record;
        # the injected spawner detached exactly once with the key derived from the target set.
        from pipeline.jobs import job_key

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_gen_next(host, port)
        assert status == 202
        assert body["status"] == "accepted"  # N-3: NOT an invoke() envelope
        assert body["job"]["target_ids"] == [ART_ID]
        expected_key = job_key([ART_ID], "exec-1")
        assert body["job"]["key"] == expected_key
        assert len(calls) == 1  # the runner was detached exactly once
        spec, spawn_dir = calls[0]
        assert spec.key == expected_key and spec.verb == "continue-session"
        assert Path(spawn_dir) == Path(root) / "workspaces" / "wsA" / "jobs"
        # JobStore.submit wrote the lossy record keyed by the run-family id.
        assert (Path(root) / "workspaces" / "wsA" / "jobs" / expected_key).exists()

    def test_double_submit_same_key_spawns_once(self, root: str) -> None:
        # Two identical submits (same idempotency_key) collide on ONE job: both 202 with the SAME
        # key; the SECOND sees the in-flight record → NO second spawn (N-2).
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
        ) as (host, port):
            s1, b1 = _submit_gen_next(host, port)
            s2, b2 = _submit_gen_next(host, port)
        assert s1 == 202 and s2 == 202
        assert b1["job"]["key"] == b2["job"]["key"]
        assert len(calls) == 1  # exactly one detach across both submits

    def test_missing_idempotency_key_is_400(self, root: str) -> None:
        # A Tier-B generate-next submit REQUIRES an idempotency_key — missing → 400 (before any
        # store access / spawn); the injected invoke()/spawner are never reached.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
        ) as (host, port):
            status, body = post(
                host,
                port,
                {
                    "verb": "continue-session",
                    "workspace": "wsA",
                    "params": {"action": "generate-next"},
                    "token": _valid_token(),
                },
            )
        assert status == 400
        assert body["error"] == "idempotency-key-required"
        assert not calls

    def test_empty_batch_is_200_no_spawn(self, root: str) -> None:
        # When the predictable-id set is EMPTY (all consumed / plan-stale) there is nothing to
        # generate — a 200 no-op, never a job keyed on an empty set, never a spawn.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([]),
        ) as (host, port):
            status, body = _submit_gen_next(host, port)
        assert status == 200 and body["status"] == "empty"
        assert not calls

    def test_invalid_token_submit_is_422(self, root: str) -> None:
        # A tampered session cursor is a §20 domain error → 422 (NEVER 401).
        calls: list = []
        wire = _valid_token()
        wire["plan_hash"] = "0" * 64  # break the digest → invalid-token
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
        ) as (host, port):
            status, body = _submit_gen_next(host, port, token=wire)
        assert status == 422 and body["error"] == "invalid-token"
        assert not calls

    def test_escaping_workspace_is_403_via_delegated_gap9(self, root: str) -> None:
        # A Tier-B submit for an ESCAPING workspace name (allow-list unset) is refused 403 — the
        # shim DELEGATES the GAP-9 resolve-and-contain (never re-implements it) and never spawns.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
        ) as (host, port):
            status, body = _submit_gen_next(
                host, port, workspace="../victim", token=_valid_token("../victim")
            )
        assert status == 403 and body["error"] == "isolation-violation"
        assert not calls


# Literal global / SSRF IPs → the W3a guard classifies a literal IP DIRECTLY (no DNS), so these
# callback tests are fully hermetic (they never touch real resolution). 8.8.8.8 is globally
# routable; 169.254.169.254 is the link-local cloud-metadata address the SSRF guard always refuses.
_GLOBAL_CB_HOST = "8.8.8.8"
_METADATA_CB_HOST = "169.254.169.254"


class TestTierBCallbackSubmit:
    """W3b: the OPTIONAL webhook `callback_url` is VALIDATED at submit (allow-list + SSRF guard,
    BEFORE any run) and, on accept, STORED on both the job record and the spawn spec. No delivery
    here (that is W3c) — these prove accept/reject + storage only."""

    def test_allowed_callback_url_rides_to_record_and_spec(self, root: str) -> None:
        # An allowed callback_url (host in the allow-list, resolves global) → 202, and the URL is
        # STORED on BOTH the spawn spec (→ W3c's detached runner) and the lossy job record.
        from pipeline.jobs import job_key

        calls: list = []
        cb = f"http://{_GLOBAL_CB_HOST}/hooks/exec-1"
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
            allowed_callback_hosts=frozenset({_GLOBAL_CB_HOST}),
        ) as (host, port):
            status, body = _submit_gen_next(host, port, callback_url=cb)
        assert status == 202 and body["status"] == "accepted"
        assert len(calls) == 1
        spec, _spawn_dir = calls[0]
        assert spec.callback_url == cb  # rides the spawn spec
        # W3c: the predictable target_ids + the FROZEN operator allow-list snapshot also ride the
        # spec, so the detached runner delivers the wakeup + RE-VALIDATES against the same list.
        assert spec.target_ids == (ART_ID,)
        assert spec.allowed_callback_hosts == frozenset({_GLOBAL_CB_HOST})
        # W3c: the 202 ack tells the client to EXPECT a callback POST — the poll floor still ships.
        assert body["callback"] == {"registered": True}
        assert body["poll"]["path"] == http_shim.POLL_PATH
        key = job_key([ART_ID], "exec-1")
        record = json.loads((Path(root) / "workspaces" / "wsA" / "jobs" / key).read_bytes())
        assert record["callback_url"] == cb  # rides the stored record

    def test_no_callback_url_omits_the_registered_note(self, root: str) -> None:
        # The poll-only path is unchanged: a submit with no callback_url gets no `callback` note in
        # the 202 ack (and the spec carries no allow-list / a None callback_url).
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_gen_next(host, port)
        assert status == 202 and body["status"] == "accepted"
        assert "callback" not in body  # no note when no callback was registered
        spec, _spawn_dir = calls[0]
        assert spec.callback_url is None and spec.target_ids == (ART_ID,)

    def test_callback_url_when_disabled_is_400_before_any_run(self, root: str) -> None:
        # The allow-list is UNSET (default) → callbacks OPT-IN OFF: a submit with callback_url is
        # refused 400 `callbacks-disabled` BEFORE any store access / plan / spawn — the injected
        # invoke()/spawner are NEVER reached.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
        ) as (host, port):
            status, body = _submit_gen_next(
                host, port, callback_url=f"http://{_GLOBAL_CB_HOST}/h"
            )
        assert status == 400
        assert body["error"] == "callback-url-rejected"
        assert body["reason"] == "callbacks-disabled"
        assert not calls  # no spawn

    def test_callback_url_ssrf_metadata_address_is_400_no_spawn(self, root: str) -> None:
        # Defense in depth: an ALLOW-LISTED host that is an SSRF target (the 169.254.169.254
        # cloud-metadata IP) still fails the INDEPENDENT SSRF guard → 400 `non-global-address`, no
        # spawn (the allow-list is never sufficient on its own).
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            allowed_callback_hosts=frozenset({_METADATA_CB_HOST}),
        ) as (host, port):
            status, body = _submit_gen_next(
                host, port, callback_url=f"http://{_METADATA_CB_HOST}/latest/meta-data/"
            )
        assert status == 400
        assert body["error"] == "callback-url-rejected"
        assert body["reason"] == "non-global-address"
        assert not calls

    def test_callback_url_non_allowed_host_is_400_no_spawn(self, root: str) -> None:
        # A callback host NOT in the allow-list → 400 `host-not-allowed` (rejected before any DNS),
        # no spawn.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            allowed_callback_hosts=frozenset({_GLOBAL_CB_HOST}),
        ) as (host, port):
            status, body = _submit_gen_next(
                host, port, callback_url="http://not-approved.example.com/h"
            )
        assert status == 400
        assert body["error"] == "callback-url-rejected"
        assert body["reason"] == "host-not-allowed"
        assert not calls

    def test_no_callback_url_is_202_poll_only_and_record_url_is_none(self, root: str) -> None:
        # NO callback_url → the unchanged 202 poll-only path; the stored record's callback_url is
        # None (poll-only, no webhook registered).
        from pipeline.jobs import job_key

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_gen_next(host, port)  # no callback_url
        assert status == 202 and body["status"] == "accepted"
        spec, _spawn_dir = calls[0]
        assert spec.callback_url is None
        key = job_key([ART_ID], "exec-1")
        record = json.loads((Path(root) / "workspaces" / "wsA" / "jobs" / key).read_bytes())
        assert record["callback_url"] is None

    def test_rejection_body_does_not_echo_the_callback_url(self, root: str) -> None:
        # SECURITY: the 400 rejection names only the reason CLASS + a fixed rule — it NEVER echoes
        # the URL, host, or credentials (an SSRF guard that leaked "10.0.0.5 is private" would leak
        # the very topology it protects). Probe with a credential-bearing URL and assert none of its
        # distinctive substrings appear anywhere in the response body.
        secret_host = "secret-internal.example.com"
        cb = f"http://user:pa55w0rd@{secret_host}/private/path"
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            allowed_callback_hosts=frozenset({_GLOBAL_CB_HOST}),
        ) as (host, port):
            status, body = _submit_gen_next(host, port, callback_url=cb)
        assert status == 400 and body["error"] == "callback-url-rejected"
        blob = json.dumps(body)
        for leak in (cb, secret_host, "pa55w0rd", "user:pa55w0rd", "/private/path"):
            assert leak not in blob
        assert not calls


class TestTierBPoll:
    def _submit(self, host, port, clock):  # noqa: ANN001, ANN202
        _s, ack = _submit_gen_next(host, port)
        return ack["job"]["key"]

    def test_poll_running_before_then_done_with_fetch(self, root: str) -> None:
        # Poll BEFORE materialization (within the job-lifetime window) → 202 running; after output
        # exists → 200 done + the fetched output (via the existing fetch-by-id handler).
        from pipeline.store import WorkspaceStore

        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=clock,
        ) as (host, port):
            key = self._submit(host, port, clock)
            s_run, b_run = poll(host, port, workspace="wsA", key=key, target_ids=[ART_ID])
            assert s_run == 202 and b_run["status"] == "running"
            # materialize the output → the §22.7 DONE authority flips
            store = WorkspaceStore(Path(root) / "workspaces" / "wsA")
            store.output_path(ART_ID).write_text("done-bytes", encoding="utf-8")
            s_done, b_done = poll(host, port, workspace="wsA", key=key, target_ids=[ART_ID])
        assert s_done == 200 and b_done["status"] == "done"
        assert b_done["results"] and b_done["results"][0]["item"] == ART_ID

    def test_poll_stored_terminal_is_failed_with_reason(self, root: str) -> None:
        # A stored (nondeterministic, timeout-class) terminal → the FAILED status + reason; the
        # timeout-class `re-drivable` code maps to 504 (N-4) and is re-drivable.
        from pipeline.jobs import JobStore
        from pipeline.opdefaults import NASCENT_RECORD_GRACE_SECONDS

        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=clock,
        ) as (host, port):
            key = self._submit(host, port, clock)
            JobStore(Path(root) / "workspaces" / "wsA" / "jobs").record_terminal(
                key,
                code="re-drivable",
                envelope={"ok": False, "code": "re-drivable", "message": "transport timeout"},
                results=[],
            )
            # A stored terminal surfaces PROMPTLY (resolver step 3, above the window): even a small
            # advance — within the lifetime window — is enough; it is never masked for 22 min.
            clock.now += NASCENT_RECORD_GRACE_SECONDS + 5
            status, body = poll(host, port, workspace="wsA", key=key, target_ids=[ART_ID])
        assert status == 504  # timeout-class → re-drivable 504 (N-4)
        assert body["status"] == "failed" and body["code"] == "re-drivable"
        assert body["redrivable"] is True
        assert body["terminal"]["envelope"]["message"] == "transport timeout"

    def test_poll_redrivable_when_the_lifetime_window_expired_and_no_work(self, root: str) -> None:
        # Past the JOB-LIFETIME window with no output, no live claim, and no stored terminal → 409
        # re-drivable (re-submit with the same idempotency_key) — never a false DONE, never a wedge.
        # NB: past the OLD 120 s line but WITHIN the window the poll is 202 running (the core fix);
        # 409 only fires past the full lifetime window.
        from pipeline.opdefaults import JOB_LIFETIME_SECONDS

        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=clock,
        ) as (host, port):
            key = self._submit(host, port, clock)
            clock.now += JOB_LIFETIME_SECONDS + 5
            status, body = poll(host, port, workspace="wsA", key=key, target_ids=[ART_ID])
        assert status == 409
        assert body["status"] == "re-drivable" and body["redrivable"] is True

    def test_poll_past_120s_but_within_lifetime_is_202_not_resend(self, root: str) -> None:
        # THE ANTI-DOUBLE-CHARGE FIX, end-to-end through the HTTP layer: a poll landing PAST the
        # old 120 s line but WITHIN the 22-min job-lifetime window — with no output and no live
        # claim (a no-claim gap) — must be 202 "still running", NOT 409 "resend". Under the
        # Commit-6 120 s boundary this exact poll returned 409, and a retry then double-charged.
        from pipeline.opdefaults import NASCENT_RECORD_GRACE_SECONDS

        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=clock,
        ) as (host, port):
            key = self._submit(host, port, clock)
            clock.now += NASCENT_RECORD_GRACE_SECONDS + 5  # past 120 s, still within the window
            status, body = poll(host, port, workspace="wsA", key=key, target_ids=[ART_ID])
        assert status == 202
        assert body["status"] == "running"

    def test_poll_invalid_key_is_400(self, root: str) -> None:
        # A poll `key` that is not a run-family id is a clean 400 (the §22.7 keying pin).
        with running_server(root=root, invoke_fn=_never_invoked) as (host, port):
            status, _ = poll(
                host, port, workspace="wsA", key="a-0000000000000000", target_ids=[ART_ID]
            )
        assert status == 400

    def test_poll_unauthenticated_is_401(self, root: str) -> None:
        # N-6: a poll carries the SAME auth gate as the submit — no secret → 401 (a poll reads
        # client job/deliverable data).
        with running_server(root=root, invoke_fn=_never_invoked) as (host, port):
            status, body = poll(
                host,
                port,
                workspace="wsA",
                key="r-0000000000000000",
                target_ids=[ART_ID],
                auth=None,
            )
        assert status == 401 and body["error"] == "unauthorized"

    def test_poll_non_allowlisted_workspace_is_403(self, root: str) -> None:
        # N-6: a cross-workspace / non-allow-listed poll is refused 403 — the SAME allow-list gate
        # as the submit, BEFORE any store access (invoke()/store never reached).
        with running_server(
            root=root, invoke_fn=_never_invoked, allowed_workspaces=frozenset({"wsA"})
        ) as (host, port):
            status, body = poll(
                host, port, workspace="wsB", key="r-0000000000000000", target_ids=[ART_ID]
            )
        assert status == 403 and body["error"] == "workspace-not-served"

    def test_poll_escaping_workspace_is_403_via_delegated_gap9(self, root: str) -> None:
        # N-6: an ESCAPING workspace name on the POLL door (allow-list unset) is refused 403 — the
        # SAME delegated GAP-9 resolve-and-contain the submit uses (`_open_workspace`), exercising
        # the poll's containment catch (the submit path has its own 403 test).
        with running_server(root=root, invoke_fn=_never_invoked) as (host, port):
            status, body = poll(
                host, port, workspace="../victim", key="r-0000000000000000", target_ids=[ART_ID]
            )
        assert status == 403 and body["error"] == "isolation-violation"


# ------------------------------------------ Commit 8: render Tier-B (optimistic-sync-then-202)
#
# render is a SERVED Tier-B door now (no longer 501). The shim resolves the PREDICTABLE render
# deliverable-id LLM-free (the SHARED `render.resolve_render_target` — the SAME primitives the
# handler materializes through), submits + detaches over the SAME jobs machinery, then holds the
# request up to the (injectable) optimistic-sync wait polling OUTPUT existence: a fast render
# materializes → 200; a paid reshape exceeds the wait → 202 + the predictable deliverable-id. The
# spawner is injected (no real subprocess); the wait is driven to 0 for the minting case so the
# suite NEVER sleeps for real, and a fast-materializing spawn seam drives the 200 case instantly.

#: The predictable deliverable-id a fresh baseline render of `a-0000000000000001` under
#: github/en/md/plain resolves to (§7.4) — the value `render.resolve_render_target` computes for the
#: same request (asserted exactly in `test_predictable_deliverable_id_keying_is_exact`).
RENDER_ART = "a-0000000000000001"
DELIV_ID = "a-0000000000000001.github.en.md.plain"


def _render_params(*, item=RENDER_ART, callback_url=None, idem=None):  # noqa: ANN202
    params = {
        "item": item,
        "platform": "github",
        "language": "en",
        "output_type": "md",
        "presentation": "plain",
    }
    if callback_url is not None:
        params["callback_url"] = callback_url
    if idem is not None:
        params["idempotency_key"] = idem
    return params


def _submit_render(host, port, *, workspace="wsA", **kw):  # noqa: ANN001, ANN201
    """POST a token-free render submit (§21.8). `callback_url`/`idem`/`item` ride params via
    `_render_params`."""
    return post(
        host, port, {"verb": "render", "workspace": workspace, "params": _render_params(**kw)}
    )


def _fixed_render_target(deliverable_id: str):  # noqa: ANN202
    """A `render_target_fn` seam returning the FIXED predictable deliverable-id (no live resolution
    — the exact real-resolver derivation is proven separately). `.block` None = a served target."""

    def resolver(store, workspace, params):  # noqa: ANN001, ANN202
        return SimpleNamespace(block=None, deliverable_id=deliverable_id)

    return resolver


def _render_spawn_materializer(calls: list):  # noqa: ANN202
    """A `spawn_fn` seam that records the detach AND (standing in for a FAST runner) materializes
    the deliverable output synchronously — so the shim's optimistic-sync wait finds it on the first
    `is_done` check → 200, INSTANTLY, with no real sleep. It writes to the SAME contained store the
    shim reads (`spawn_dir.parent`)."""

    def spawn(spec, *, spawn_dir):  # noqa: ANN001, ANN202
        calls.append((spec, spawn_dir))
        store = WorkspaceStore(Path(spawn_dir).parent)
        out = store.output_path(spec.target_ids[0])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("rendered-bytes", encoding="utf-8")
        return None

    return spawn


class _MiniRenderEngine:
    """A minimal reconcile/serialize seam for `resolve_render_target`: it returns fixed preimages
    and NEVER mints — the resolution is LLM-FREE, so a mint call is a test failure."""

    def __init__(self) -> None:
        self.mints = 0

    def reconcile_preimage(self, leg):  # noqa: ANN001, ANN202
        return {"strategy": {}, "hard-limits": {}, "advisory": {}, "render-dims": {}}

    def mint_fit(self, leg, *, preimage, revision):  # noqa: ANN001, ANN202
        self.mints += 1
        raise AssertionError("resolve_render_target must not mint (§22.2 LLM-free)")

    def serialize_preimage(self, leg):  # noqa: ANN001, ANN202
        return {"tool_bundle": {}, "render_target": {}, "render_inputs": {}}

    def mint_deliverable(self, leg, *, preimage, serialize_revision):  # noqa: ANN001, ANN202
        self.mints += 1
        raise AssertionError("resolve_render_target must not mint (§22.2 LLM-free)")


class TestRenderTierBSubmit:
    def test_render_is_served_tier_b_not_501(self, root: str) -> None:
        # render is a SERVED Tier-B door (Commit 8): a submit returns 202/200, never 501.
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
            render_sync_wait_seconds=0,
        ) as (host, port):
            status, body = _submit_render(host, port)
        assert status == 202  # NOT 501
        assert body["status"] == "accepted"

    def test_cache_hit_render_materializes_within_wait_is_200(self, root: str) -> None:
        # A cache-hit / fast render: the (injected) runner materializes the deliverable within the
        # optimistic-sync wait → a synchronous 200 + the fetched output. Instant: the fast-
        # materializing spawn seam makes the FIRST is_done check true (no real sleep).
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_render_spawn_materializer(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_render(host, port)
        assert status == 200 and body["status"] == "done"
        assert body["results"] and body["results"][0]["item"] == DELIV_ID
        assert len(calls) == 1  # spawned once; the wait then found the fast output

    def test_already_materialized_render_short_circuits_200_no_spawn(self, root: str) -> None:
        # The deliverable already exists at SUBMIT → JobStore.submit disposition `done` short-
        # circuits to 200 + output WITHOUT spawning a runner (anti-double-charge on the door).
        store = WorkspaceStore(Path(root) / "workspaces" / "wsA")
        out = store.output_path(DELIV_ID)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("already", encoding="utf-8")
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_render(host, port)
        assert status == 200 and body["status"] == "done"
        assert not calls  # done disposition → no runner spawned

    def test_minting_render_exceeds_wait_is_202_then_poll(self, root: str) -> None:
        # A minting render: the (injected) runner does NOT materialize within the wait (driven to 0)
        # → 202 + the predictable deliverable-id; a later poll is running (within the job-lifetime
        # window), then done once the output materializes. No real sleep (wait=0).
        from pipeline.jobs import job_key

        calls: list = []
        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=clock,
            render_sync_wait_seconds=0,
        ) as (host, port):
            status, body = _submit_render(host, port)
            assert status == 202 and body["status"] == "accepted"
            assert body["job"]["target_ids"] == [DELIV_ID]
            expected_key = job_key([DELIV_ID], None)  # render keys WITHOUT an idempotency_key
            assert body["job"]["key"] == expected_key
            assert len(calls) == 1  # detached exactly once
            # poll BEFORE materialization → 202 running (within the job-lifetime window)
            s_run, b_run = poll(
                host, port, workspace="wsA", key=expected_key, target_ids=[DELIV_ID]
            )
            assert s_run == 202 and b_run["status"] == "running"
            # materialize the deliverable → the §22.7 DONE authority flips
            store = WorkspaceStore(Path(root) / "workspaces" / "wsA")
            out = store.output_path(DELIV_ID)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("rendered", encoding="utf-8")
            s_done, b_done = poll(
                host, port, workspace="wsA", key=expected_key, target_ids=[DELIV_ID]
            )
        assert s_done == 200 and b_done["status"] == "done"
        assert b_done["results"] and b_done["results"][0]["item"] == DELIV_ID

    def test_double_submit_render_same_key_spawns_once(self, root: str) -> None:
        # Two identical renders (content-addressed, no idempotency_key) collide on ONE job: both
        # 202 with the SAME key; the SECOND sees the in-flight record → NO second spawn (the anti-
        # double-charge holds for render — GAP-10 would `claim-held` even a raced mint).
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
            render_sync_wait_seconds=0,
        ) as (host, port):
            s1, b1 = _submit_render(host, port)
            s2, b2 = _submit_render(host, port)
        assert s1 == 202 and s2 == 202
        assert b1["job"]["key"] == b2["job"]["key"]
        assert len(calls) == 1  # exactly one detach across both submits (second → existing)

    def test_render_callback_url_accepted_rides_to_spec(self, root: str) -> None:
        # An allowed callback_url → 202 + the W3c registered note, and the URL + frozen allow-list
        # snapshot + predictable target_ids ride the render spawn spec (delivery is W3c). Reuses the
        # SAME W3b guard as generate-next.
        calls: list = []
        cb = f"http://{_GLOBAL_CB_HOST}/hooks/render-1"
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
            render_sync_wait_seconds=0,
            allowed_callback_hosts=frozenset({_GLOBAL_CB_HOST}),
        ) as (host, port):
            status, body = _submit_render(host, port, callback_url=cb)
        assert status == 202 and body["status"] == "accepted"
        assert body["callback"] == {"registered": True}
        assert body["poll"]["path"] == http_shim.POLL_PATH  # the poll floor still ships
        assert len(calls) == 1
        spec, _spawn_dir = calls[0]
        assert spec.verb == "render" and spec.callback_url == cb
        assert spec.target_ids == (DELIV_ID,)
        assert spec.allowed_callback_hosts == frozenset({_GLOBAL_CB_HOST})

    def test_render_bad_callback_url_is_400_before_submit(self, root: str) -> None:
        # A callback_url with the allow-list UNSET (callbacks opt-in OFF) → 400 `callbacks-disabled`
        # BEFORE any store access / resolution / spawn — the injected spawner is never reached.
        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
        ) as (host, port):
            status, body = _submit_render(host, port, callback_url=f"http://{_GLOBAL_CB_HOST}/h")
        assert status == 400 and body["error"] == "callback-url-rejected"
        assert body["reason"] == "callbacks-disabled"
        assert not calls  # rejected before any submit/spawn

    def test_predictable_deliverable_id_keying_is_exact(self, tmp_path: Path) -> None:
        # The REAL shared resolver `render.resolve_render_target` derives the SAME deliverable-id
        # for the same request (content-addressed, LLM-FREE) — the id the shim keys/polls on == the
        # id the handler materializes (anti-fork), and the job key over it is exact/stable.
        from pipeline.api import render as render_mod
        from pipeline.jobs import job_key

        store = WorkspaceStore(tmp_path / "wsA")
        store.ensure_layout()
        store.output_path(RENDER_ART).write_bytes(
            b'{"body": "canonical", "binding": {"artifact_id": "x"}}\n'
        )
        params = _render_params()
        engine = _MiniRenderEngine()
        r1 = render_mod.resolve_render_target(store, params, engine=engine, workspace="wsA")
        r2 = render_mod.resolve_render_target(store, params, engine=engine, workspace="wsA")
        assert r1.block is None and r2.block is None
        assert r1.deliverable_id == r2.deliverable_id == DELIV_ID  # exact, matches the shim fixture
        assert job_key([r1.deliverable_id], None) == job_key([r2.deliverable_id], None)
        # a fresh fit is not yet materialized → the baseline deliverable, resolved WITHOUT any mint
        assert r1.fit_materialized is False
        assert engine.mints == 0


# --------------------------------------------------------------------------- DR-1 Commit 10:
# the ADVISORY concurrency cap (Path A) + the always-correct rate-limit-backpressure 429 backstop.
# `live_count_fn` seeds the account-wide in-flight PRESENCE count without spawning real runners.


def post_full(host, port, body, *, path=http_shim.INVOKE_PATH, auth=TEST_SECRET):  # noqa: ANN001, ANN201
    """Like `post` but ALSO returns the response HEADERS — for the `Retry-After` assertion on a 429
    (the advisory cap + the backpressure backstop, DR-1 Commit 10)."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    raw = body if isinstance(body, (bytes, bytearray)) else json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth is not None:
        headers["Authorization"] = f"Bearer {auth}"
    try:
        conn.request("POST", path, body=raw, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = dict(resp.getheaders())
        data = resp.read()
    finally:
        conn.close()
    return status, (json.loads(data) if data else {}), resp_headers


def poll_full(host, port, *, workspace, key, target_ids, auth=TEST_SECRET):  # noqa: ANN001, ANN201
    """`POST /poll` returning (status, json, headers) — the header-capturing poll (for the
    backstop's Retry-After assertion)."""
    return post_full(
        host,
        port,
        {"workspace": workspace, "key": key, "target_ids": target_ids},
        path=http_shim.POLL_PATH,
        auth=auth,
    )


class TestConcurrencyCap:
    """DR-1 Commit 10 — the ADVISORY pre-spawn cap (Path A). Seed `live_count()` AT/OVER
    MAX_PARALLEL_SESSIONS → a Tier-B submit is refused 429 + Retry-After with NO spawn; below the
    cap → the normal 202. The pre-check is BEST-EFFORT / racy (proven below); the 429 backstop
    (`TestConcurrencyBackstop`) is the always-correct bound."""

    def test_gen_next_at_cap_is_429_retry_after_no_spawn(self, root: str) -> None:
        from pipeline.opdefaults import MAX_PARALLEL_SESSIONS, SHIM_CAP_RETRY_AFTER_SECONDS

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
            live_count_fn=lambda _root: MAX_PARALLEL_SESSIONS,  # seeded AT the cap
        ) as (host, port):
            status, body, headers = post_full(
                host,
                port,
                {
                    "verb": "continue-session",
                    "workspace": "wsA",
                    "params": {"action": "generate-next", "idempotency_key": "exec-1"},
                    "token": _valid_token(),
                },
            )
        assert status == 429
        assert body["error"] == "concurrency-cap"
        assert body["retry_after_seconds"] == SHIM_CAP_RETRY_AFTER_SECONDS
        assert headers.get("Retry-After") == str(SHIM_CAP_RETRY_AFTER_SECONDS)
        assert not calls  # ADVISORY cap → do NOT spawn (the record self-heals via the H2 re-drive)

    def test_gen_next_below_cap_is_normal_202(self, root: str) -> None:
        from pipeline.opdefaults import MAX_PARALLEL_SESSIONS

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
            live_count_fn=lambda _root: MAX_PARALLEL_SESSIONS - 1,  # one BELOW the cap
        ) as (host, port):
            status, body = _submit_gen_next(host, port)
        assert status == 202 and body["status"] == "accepted"
        assert len(calls) == 1  # below the cap → spawns normally

    def test_render_at_cap_is_429_retry_after_no_spawn(self, root: str) -> None:
        from pipeline.opdefaults import MAX_PARALLEL_SESSIONS, SHIM_CAP_RETRY_AFTER_SECONDS

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            render_target_fn=_fixed_render_target(DELIV_ID),
            clock_fn=_FakeClock(),
            render_sync_wait_seconds=0,
            live_count_fn=lambda _root: MAX_PARALLEL_SESSIONS,  # seeded AT the cap
        ) as (host, port):
            status, body, headers = post_full(
                host, port, {"verb": "render", "workspace": "wsA", "params": _render_params()}
            )
        assert status == 429 and body["error"] == "concurrency-cap"
        assert headers.get("Retry-After") == str(SHIM_CAP_RETRY_AFTER_SECONDS)
        # do NOT spawn — and thus never enter the optimistic-sync hold (one fewer pinned thread).
        assert not calls

    def test_default_live_count_reads_the_real_registry(self, root: str) -> None:
        # The default (non-injected) seam reads the REAL PresenceRegistry: seed 3 live leases under
        # <root>/instance/ops/presence and a submit is refused 429 — proving the shim consults the
        # SAME registry the runners populate (integration, no stub).
        from pipeline.opdefaults import MAX_PARALLEL_SESSIONS
        from pipeline.telemetry import PresenceRegistry

        registry = PresenceRegistry(Path(root) / "instance" / "ops" / "presence")
        for _ in range(MAX_PARALLEL_SESSIONS):
            registry.register()
        assert registry.live_count() == MAX_PARALLEL_SESSIONS
        calls: list = []
        with running_server(  # NO live_count_fn → the real _default_live_count reads the registry
            root=root,
            invoke_fn=_never_invoked,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
        ) as (host, port):
            status, body = _submit_gen_next(host, port)
        assert status == 429 and body["error"] == "concurrency-cap"
        assert not calls

    def test_pre_spawn_check_is_best_effort_a_burst_can_exceed(self, root: str) -> None:
        # RACY-BUT-BOUNDED HONESTY: the pre-spawn check reads live_count BEFORE the detached runners
        # register their leases, so within that racy window a BURST of distinct submits ALL pass
        # (none 429) — the check can briefly EXCEED the cap. It is best-effort, NOT a hard gate; the
        # returned rate-limit-backpressure 429 (TestConcurrencyBackstop) is the real bound. Here
        # live_count() reads 0 (the pre-registration window), so cap+1 distinct submits all spawn.
        from pipeline.opdefaults import MAX_PARALLEL_SESSIONS

        calls: list = []
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder(calls),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=_FakeClock(),
            live_count_fn=lambda _root: 0,  # the racy pre-registration window
        ) as (host, port):
            statuses = [
                _submit_gen_next(host, port, idem=f"exec-{i}")[0]
                for i in range(MAX_PARALLEL_SESSIONS + 1)
            ]
        assert statuses == [202] * (MAX_PARALLEL_SESSIONS + 1)  # ALL pass — the burst exceeded
        assert len(calls) == MAX_PARALLEL_SESSIONS + 1  # all spawned (best-effort, not a hard gate)


class TestConcurrencyBackstop:
    """DR-1 Commit 10 — the ALWAYS-CORRECT bound: the RETURNED `rate-limit-backpressure` → 429. It
    catches real overspend regardless of the advisory pre-check's raciness (the subscription's own
    pushback), and is the ONE mapping (`_terminal_status_for`) every surface routes through."""

    def test_terminal_status_mapper_backpressure_is_429(self) -> None:
        from pipeline.api.jobrunner import RE_DRIVABLE_CODE

        assert http_shim._terminal_status_for("rate-limit-backpressure") == 429  # the backstop arm
        assert http_shim._terminal_status_for(RE_DRIVABLE_CODE) == 504  # timeout-class, not 429

    def test_poll_backpressure_terminal_is_429_with_retry_after(self, root: str) -> None:
        # THE BACKSTOP end-to-end: a job whose stored terminal is the subscription's own
        # rate-limit-backpressure → the poll maps it to 429 + Retry-After (re-drivable). This is the
        # real bound the racy advisory pre-check backs onto.
        from pipeline.jobs import JobStore
        from pipeline.opdefaults import NASCENT_RECORD_GRACE_SECONDS, SHIM_CAP_RETRY_AFTER_SECONDS

        clock = _FakeClock()
        with running_server(
            root=root,
            invoke_fn=_fetch_stub,
            spawn_fn=_spawn_recorder([]),
            plan_targets_fn=_fixed_targets([ART_ID]),
            clock_fn=clock,
        ) as (host, port):
            _s, ack = _submit_gen_next(host, port)
            key = ack["job"]["key"]
            JobStore(Path(root) / "workspaces" / "wsA" / "jobs").record_terminal(
                key,
                code="rate-limit-backpressure",
                envelope={
                    "ok": False,
                    "code": "rate-limit-backpressure",
                    "message": "usage limit reached",
                },
                results=[],
            )
            clock.now += NASCENT_RECORD_GRACE_SECONDS + 5  # surface the stored terminal promptly
            status, body, headers = poll_full(
                host, port, workspace="wsA", key=key, target_ids=[ART_ID]
            )
        assert status == 429
        assert body["status"] == "failed" and body["code"] == "rate-limit-backpressure"
        assert body["redrivable"] is True
        assert headers.get("Retry-After") == str(SHIM_CAP_RETRY_AFTER_SECONDS)
