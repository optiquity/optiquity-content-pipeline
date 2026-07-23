"""DR-1 Commit 5a tests: the HTTP shim skeleton + `serve` + Tier-A dispatch + N-4 mapping.

The server is driven in-process on `127.0.0.1:0` (an ephemeral port, real socket) so every test
is hermetic + fast — no live subscription, no network. Two dispatch seams are exercised:

* the REAL `invoke()` (with `register_api_handlers()` wiring the exact production surface) — used
  to prove the HTTP door truly reaches the wired handlers (`emit-outline`, the fatal gates);
* an INJECTED `invoke_fn` stub — used to pin the pure serialization / status-mapping / Tier-gating
  behavior crisply and to prove the shim adds no business logic.

All fixtures are obviously generic (`wsA`, §7.4 literal ids); no instance content.
"""

from __future__ import annotations

import http.client
import json
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
def running_server(*, invoke_fn=invoke, root: str = ".") -> Iterator[tuple[str, int]]:
    """Start the shim on an ephemeral loopback port in a daemon thread; yield (host, port)."""
    server = http_shim.make_server("127.0.0.1", 0, invoke_fn=invoke_fn, root=root)
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
    host: str, port: int, body: object, *, path: str = http_shim.INVOKE_PATH, method: str = "POST"
) -> tuple[int, dict]:
    """POST a body (a dict → JSON, or raw bytes/str passed through) and return (status, json)."""
    conn = http.client.HTTPConnection(host, port, timeout=5)
    if isinstance(body, (bytes, bytearray)):
        raw: bytes = bytes(body)
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body).encode("utf-8")
    try:
        conn.request(method, path, body=raw, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        status = resp.status
        data = resp.read()
    finally:
        conn.close()
    parsed = json.loads(data) if data else {}
    return status, parsed


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
