"""Tests for the stdlib reference client (`pipeline.client`), Commit 2 of the API-client build.

Three CI-safe layers, NO live network / subscription (design Part 6 of the API-client plan):

* **Layer 1 — the ``_request`` substrate** (a mocked ``urllib`` opener): the normalized-Response
  rule (`clients.md` §2.5) + the three F-D fallbacks (§2.6): an ``HTTPError`` is CAUGHT and returned
  as a Response; a genuine ``URLError``/timeout (no ``.status``) PROPAGATES; a non-JSON/empty body →
  ``json=None``; a blank/absent/non-integer ``Retry-After`` → the backoff cadence; the auth header;
  verified default TLS.
* **Layer 2 — the poll state machine** (a scripted in-process ``http.server`` on ``127.0.0.1:0``,
  with ``time.sleep`` monkeypatched to RECORD durations): every §2.3 branch — 202→200-done,
  429+Retry-After (submit AND poll), 504, 409-re-drive-with-the-same-key, the cache-hit 200
  collapse, render-blocked, JobFailed, the await deadline, and the malformed ``done`` body (F-H).
* **Layer 3 — a real-wire smoke** against ``http_shim.make_server`` (no real spawn): a wrong secret
  is a ``401`` *Response* (not a raised error), and a valid secret gets past auth — grounding the
  client's auth header + the HTTPError-as-Response funnel against the REAL server object.

All fixtures are obviously generic (``wsA``, literal ids); no instance/client content.
"""

from __future__ import annotations

import email.message
import http.server
import inspect
import io
import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager

import pytest

import pipeline.client.client as client_mod
from pipeline.client import (
    CallbackEvent,
    Client,
    JobFailed,
    JobTimeout,
    MalformedResponse,
    RenderBlocked,
    Response,
    Result,
    parse_callback,
)

# =============================================================================================
# Layer-1 fakes: a mocked urllib opener + response/HTTPError builders (no socket).
# =============================================================================================


class _FakeHTTPResponse:
    """A minimal stand-in for an ``http.client.HTTPResponse`` (``.status``/``.headers``/``.read``/
    ``.close``) so ``_request`` can normalize it with no socket."""

    def __init__(self, status: int = 200, headers: dict | None = None, body: bytes = b"{}") -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body if isinstance(body, bytes) else body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:
        pass


class _RecordingOpener:
    """A fake opener capturing every outgoing ``Request``. ``script`` is a single response, a list
    popped in order, or a ``callable(request) -> response``; a ``BaseException`` in the list/return
    is RAISED (to drive the HTTPError / URLError paths)."""

    def __init__(self, script) -> None:  # noqa: ANN001
        self._script = script
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append(request)
        if callable(self._script):
            result = self._script(request)
        elif isinstance(self._script, list):
            result = self._script.pop(0)
        else:
            result = self._script
        if isinstance(result, BaseException):
            raise result
        return result


def _make_http_error(
    status: int, body: bytes = b"", headers: dict | None = None, url: str = "http://shim.test/x"
) -> urllib.error.HTTPError:
    hdrs = email.message.Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    fp = io.BytesIO(body if isinstance(body, bytes) else body.encode("utf-8"))
    return urllib.error.HTTPError(url, status, "err", hdrs, fp)


def _fake_client(**kwargs) -> Client:  # noqa: ANN003
    kwargs.setdefault("opener", _RecordingOpener(_FakeHTTPResponse()))
    return Client("http://shim.test", "sek", **kwargs)


# =============================================================================================
# Layer 1 — the _request substrate (normalized Response + the F-D fallbacks + auth + TLS).
# =============================================================================================


@pytest.mark.parametrize("status", [400, 404, 409, 429, 500, 504])
def test_httperror_is_caught_and_returned_as_response(status: int) -> None:
    """(a) An HTTPError (any 4xx/5xx) is CAUGHT and returned as a Response, never raised (§2.5)."""
    err = _make_http_error(status, body=b'{"error": "x"}')
    client = Client("http://shim.test", "sek", opener=_RecordingOpener([err]))
    resp = client.invoke("render", "wsA", "userA", {})
    assert isinstance(resp, Response)
    assert resp.status == status
    assert resp.json == {"error": "x"}


def test_integer_retry_after_is_parsed_as_int() -> None:
    """(b) Retry-After is integer delta-seconds."""
    client = _fake_client()
    value = client._retry_after_seconds({"Retry-After": "7"}, 2.0)
    assert value == 7
    assert isinstance(value, int)


def test_auth_header_is_bearer_by_default() -> None:
    """(d) Default auth is ``Authorization: Bearer <secret>``; no ``X-API-Key``."""
    opener = _RecordingOpener(_FakeHTTPResponse())
    Client("http://shim.test", "sek", opener=opener).invoke("list", "wsA", "userA", {})
    req = opener.requests[0]
    assert req.headers.get("Authorization") == "Bearer sek"
    assert req.headers.get("X-api-key") is None  # urllib capitalizes header keys


def test_auth_header_uses_x_api_key_when_selected() -> None:
    """(d) ``api_key_header=True`` sends ``X-API-Key: <secret>`` and no Authorization."""
    opener = _RecordingOpener(_FakeHTTPResponse())
    Client("http://shim.test", "sek", api_key_header=True, opener=opener).invoke(
        "list", "wsA", "userA", {}
    )
    req = opener.requests[0]
    assert req.headers.get("X-api-key") == "sek"
    assert req.headers.get("Authorization") is None


def test_default_tls_context_is_verified(monkeypatch: pytest.MonkeyPatch) -> None:
    """(e) An https client builds a VERIFIED default TLS context (never an unverified one)."""
    calls: list[bool] = []
    real = client_mod.ssl.create_default_context

    def spy(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(client_mod.ssl, "create_default_context", spy)
    Client("https://shim.test", "sek")
    assert calls, "the client must build a verified default TLS context"


def test_client_source_never_disables_tls_verification() -> None:
    """(e) No unverified-context path exists anywhere in the client module."""
    src = inspect.getsource(client_mod)
    assert "create_unverified" not in src
    assert "CERT_NONE" not in src
    assert "check_hostname" not in src


def test_urlerror_without_status_propagates() -> None:
    """(f) A genuine URLError (no ``.status``) is the single exception channel — NOT a Response."""
    opener = _RecordingOpener([urllib.error.URLError("refused")])
    client = Client("http://shim.test", "sek", opener=opener)
    with pytest.raises(urllib.error.URLError):
        client.invoke("render", "wsA", "userA", {})


def test_timeout_error_without_status_propagates() -> None:
    """(f) A bare TimeoutError (no ``.status``, not an HTTPError) also propagates."""
    client = Client("http://shim.test", "sek", opener=_RecordingOpener([TimeoutError("timed out")]))
    with pytest.raises(TimeoutError):
        client.invoke("render", "wsA", "userA", {})


def test_non_json_error_body_yields_json_none() -> None:
    """(g) A non-JSON error body → ``Response.json = None`` (guarded parse), status preserved."""
    err = _make_http_error(500, body=b"<html>internal error</html>")
    client = Client("http://shim.test", "sek", opener=_RecordingOpener([err]))
    resp = client.invoke("render", "wsA", "userA", {})
    assert resp.status == 500
    assert resp.json is None


def test_empty_body_yields_json_none() -> None:
    """(g) An empty body → ``json = None``, never a ``json.loads`` crash."""
    opener = _RecordingOpener([_FakeHTTPResponse(200, body=b"")])
    resp = Client("http://shim.test", "sek", opener=opener).invoke("list", "wsA", "userA", {})
    assert resp.status == 200
    assert resp.json is None


def test_retry_after_fallback_variants() -> None:
    """(h) Absent/blank/whitespace/non-integer Retry-After → the backoff fallback; integer wins;
    the lookup is case-insensitive."""
    client = _fake_client()
    assert client._retry_after_seconds({}, 3.0) == 3.0
    assert client._retry_after_seconds({"Retry-After": ""}, 3.0) == 3.0
    assert client._retry_after_seconds({"Retry-After": "   "}, 3.0) == 3.0
    assert client._retry_after_seconds({"Retry-After": "soon"}, 3.0) == 3.0
    assert client._retry_after_seconds({"Retry-After": "5"}, 3.0) == 5
    assert client._retry_after_seconds({"retry-after": "9"}, 3.0) == 9


def test_construction_rejects_empty_url_or_secret() -> None:
    with pytest.raises(ValueError):
        Client("", "sek")
    with pytest.raises(ValueError):
        Client("http://shim.test", "")


# =============================================================================================
# B10 — the client SENDS a mandatory `user` on every wire body (§23 isolation prefix). The shim
# REQUIRES `user` on `/invoke` and `/poll` (parallel to `workspace`) and 400s a missing/empty one;
# these pin that the client library actually puts `user` ON THE WIRE, so a future refactor cannot
# silently drop it and re-open the B5 400 gap (a real client→shim call would break).
# =============================================================================================


def _sent_body(opener: _RecordingOpener, index: int = 0) -> dict:
    """Decode the JSON body of the ``index``-th outgoing request the recording opener captured."""
    return json.loads(opener.requests[index].data)


def test_invoke_body_carries_mandatory_user() -> None:
    """The built ``/invoke`` body includes ``user`` alongside ``workspace`` — 1:1 with the wire the
    shim enforces. This is the direct-construction probe the B5 cutover was missing."""
    opener = _RecordingOpener(_FakeHTTPResponse())
    Client("http://shim.test", "sek", opener=opener).invoke("render", "wsA", "userA", {"item": "x"})
    body = _sent_body(opener)
    assert body["user"] == "userA"
    assert body["workspace"] == "wsA"


def test_poll_body_carries_mandatory_user() -> None:
    """The built ``/poll`` body includes ``user`` alongside ``workspace`` (matching the poll
    handler's requirement AND the advertised ``poll.needs``)."""
    opener = _RecordingOpener(_FakeHTTPResponse())
    Client("http://shim.test", "sek", opener=opener).poll("wsA", "userA", "r-1", ["t-1"])
    body = _sent_body(opener)
    assert body["user"] == "userA"
    assert body["workspace"] == "wsA"
    assert body["key"] == "r-1"
    assert body["target_ids"] == ["t-1"]


def test_ergonomic_render_submit_body_carries_mandatory_user() -> None:
    """The ergonomic ``render_and_wait`` submit body also carries ``user`` (threaded through the raw
    layer), so the whole surface — not just the raw door — is 400-safe."""
    done = json.dumps({"status": "done", "results": []}).encode()
    opener = _RecordingOpener(_FakeHTTPResponse(200, body=done))
    Client("http://shim.test", "sek", opener=opener).render_and_wait(
        "wsA", "userA", "i", "p", "en", "post"
    )
    body = _sent_body(opener)
    assert body["verb"] == "render"
    assert body["user"] == "userA"
    assert body["workspace"] == "wsA"


def test_user_is_required_never_defaulted() -> None:
    """``user`` is a REQUIRED positional (parallel to ``workspace``): omitting it is a loud
    ``TypeError`` client-side, never a silently-omitted field. Fail-loud is the whole point — an
    omitted ``user`` must NEVER be silently accepted onto the wire."""
    client = _fake_client()
    with pytest.raises(TypeError):
        client.invoke("render", "wsA")  # no user, no params → loud failure, not a silent send
    with pytest.raises(TypeError):
        client.poll("wsA", "r-1")  # no user → loud failure


# =============================================================================================
# Layer-2 scripted shim: an in-process http.server replaying per-path response specs.
# =============================================================================================


class _ScriptedShim:
    """Replays ``invoke_script`` for ``POST /invoke`` and ``poll_script`` for ``POST /poll`` (each
    a list of ``{status, json|raw, headers?}`` specs), recording every received ``(path, body,
    headers)``. An exhausted script hard-fails (500) so an unexpected extra request never hangs."""

    def __init__(self) -> None:
        self.invoke_script: list[dict] = []
        self.poll_script: list[dict] = []
        self.received: list[tuple] = []
        self.default: dict = {
            "status": 500,
            "json": {
                "status": "failed",
                "code": "test-script-exhausted",
                "redrivable": False,
                "job": {"key": "r-x", "target_ids": ["t-x"]},
                "terminal": {"envelope": {}, "results": []},
            },
        }

    def next_spec(self, path: str) -> dict:
        script = self.invoke_script if path.endswith("/invoke") else self.poll_script
        return script.pop(0) if script else self.default


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — stdlib dispatch name
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        shim: _ScriptedShim = self.server.shim  # type: ignore[attr-defined]
        shim.received.append((self.path, body, dict(self.headers)))
        spec = shim.next_spec(self.path)
        payload = spec.get("raw")
        if payload is None:
            payload = json.dumps(spec.get("json", {})).encode("utf-8")
        elif not isinstance(payload, bytes):
            payload = payload.encode("utf-8")
        self.send_response(spec["status"])
        self.send_header("Content-Type", "application/json")
        for name, value in spec.get("headers", {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:  # noqa: ANN002 — silence the test server
        pass


@contextmanager
def _scripted_server(shim: _ScriptedShim) -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.shim = shim  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Monkeypatch the client's ``time.sleep`` to RECORD durations (no real delay)."""
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", lambda d: sleeps.append(d))
    return sleeps


def _accepted(key: str, target_ids: list[str]) -> dict:
    return {
        "status": 202,
        "json": {"status": "accepted", "job": {"key": key, "target_ids": target_ids}},
    }


def _running(key: str, target_ids: list[str]) -> dict:
    return {
        "status": 202,
        "json": {"status": "running", "job": {"key": key, "target_ids": target_ids}},
    }


def _done(key: str, target_ids: list[str], results: list) -> dict:
    return {
        "status": 200,
        "json": {
            "status": "done",
            "job": {"key": key, "target_ids": target_ids},
            "results": results,
        },
    }


def _failed(
    status: int, code: str, redrivable: bool, key: str = "r-1", headers: dict | None = None
) -> dict:
    spec: dict = {
        "status": status,
        "json": {
            "status": "failed",
            "code": code,
            "redrivable": redrivable,
            "job": {"key": key, "target_ids": ["t-1"]},
            "terminal": {"envelope": {"ok": False, "code": code}, "results": []},
        },
    }
    if headers:
        spec["headers"] = headers
    return spec


# =============================================================================================
# Layer 2 — the poll state machine (clients.md §2.3), every branch.
# =============================================================================================


def test_poll_202_then_done_returns_result(recorded_sleeps: list[float]) -> None:
    """(a) 202 accepted → 202 running → 200 done ⇒ Result; sleeps follow the doubling backoff."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [_running("r-1", ["t-1"]), _done("r-1", ["t-1"], [{"item": "x"}])]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", poll_interval=0.1, timeout=5).render_and_wait(
            "wsA", "userA", "deck-intro", "linkedin", "en", "post"
        )
    assert isinstance(result, Result)
    assert result.json["results"] == [{"item": "x"}]
    assert recorded_sleeps == [0.1, 0.2]


def test_poll_429_retry_after_overrides_backoff(recorded_sleeps: list[float]) -> None:
    """(b) 202 → 429 Retry-After:5 (a rate-limit-backpressure body) → 200 done ⇒ the integer
    Retry-After (5) overrides the backoff cadence; the backpressure code is handled as a retry."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [
        _failed(429, "rate-limit-backpressure", True, headers={"Retry-After": "5"}),
        _done("r-1", ["t-1"], []),
    ]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", poll_interval=0.1, timeout=5).render_and_wait(
            "wsA", "userA", "i", "p", "en", "post"
        )
    assert isinstance(result, Result)
    assert recorded_sleeps == [0.1, 5]


def test_submit_429_concurrency_cap_retries_by_resubmitting(recorded_sleeps: list[float]) -> None:
    """(i) A submit-time 429 (concurrency-cap, no job handle yet) → sleep the integer Retry-After,
    then RE-SUBMIT (never poll)."""
    shim = _ScriptedShim()
    shim.invoke_script = [
        {"status": 429, "headers": {"Retry-After": "7"}, "json": {"error": "concurrency-cap"}},
        _done("r-1", ["t-1"], []),
    ]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", poll_interval=0.1, timeout=5).render_and_wait(
            "wsA", "userA", "i", "p", "en", "post"
        )
    assert isinstance(result, Result)
    assert recorded_sleeps == [7]
    paths = [path for (path, _b, _h) in shim.received]
    assert paths == ["/invoke", "/invoke"]  # re-submitted, no /poll (no handle yet)


def test_poll_504_yields_jobtimeout(recorded_sleeps: list[float]) -> None:
    """(c) 202 → 504 ⇒ JobTimeout(redrivable=True)."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [_failed(504, "timeout", True)]
    with _scripted_server(shim) as url:
        client = Client(url, "sek", poll_interval=0.1, timeout=5)
        with pytest.raises(JobTimeout) as exc:
            client.render_and_wait("wsA", "userA", "i", "p", "en", "post")
    assert exc.value.redrivable is True
    assert recorded_sleeps == [0.1]


def test_poll_409_redrives_with_same_idempotency_key(recorded_sleeps: list[float]) -> None:
    """(d) 202 → 409 re-drivable → 200 done ⇒ the stub saw TWO submits with the SAME key."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"]), _accepted("r-1", ["t-1"])]
    shim.poll_script = [
        {
            "status": 409,
            "json": {
                "status": "re-drivable",
                "redrivable": True,
                "job": {"key": "r-1", "target_ids": ["t-1"]},
            },
        },
        _done("r-1", ["t-1"], []),
    ]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", poll_interval=0.1, timeout=5).generate_and_wait(
            "wsA", "userA", token="tok", idempotency_key="idem-xyz"
        )
    assert isinstance(result, Result)
    invoke_bodies = [body for (path, body, _h) in shim.received if path == "/invoke"]
    assert len(invoke_bodies) == 2
    assert {b["params"]["idempotency_key"] for b in invoke_bodies} == {"idem-xyz"}


def test_render_cache_hit_200_collapses_without_poll(recorded_sleeps: list[float]) -> None:
    """(f) 200-at-submit (cache hit) ⇒ Result with NO poll (the render collapse)."""
    shim = _ScriptedShim()
    shim.invoke_script = [_done("r-1", ["t-1"], [{"item": "cached"}])]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", timeout=5).render_and_wait(
            "wsA", "userA", "i", "p", "en", "post"
        )
    assert isinstance(result, Result)
    assert result.json["results"] == [{"item": "cached"}]
    assert recorded_sleeps == []
    assert [path for (path, _b, _h) in shim.received] == ["/invoke"]


def test_result_synthesizes_no_cache_or_cost_field(recorded_sleeps: list[float]) -> None:
    """(§2.8) The Result carries EXACTLY the server body — no from_cache/cost invented."""
    body = {
        "status": "done",
        "job": {"key": "r-1", "target_ids": ["t-1"]},
        "results": [{"item": "x"}],
    }
    shim = _ScriptedShim()
    shim.invoke_script = [{"status": 200, "json": body}]
    with _scripted_server(shim) as url:
        result = Client(url, "sek", timeout=5).render_and_wait(
            "wsA", "userA", "i", "p", "en", "post"
        )
    assert result.json == body
    assert "from_cache" not in result.json
    assert "cost" not in result.json
    assert not hasattr(result, "from_cache")
    assert not hasattr(result, "cost")
    assert set(Result.__dataclass_fields__) == {"json"}


def test_submit_render_blocked_raises_render_blocked(recorded_sleeps: list[float]) -> None:
    """(g) 400 render-blocked body ⇒ RenderBlocked(block=...)."""
    block = {"code": "grounding-uncovered", "detail": "a claim is not covered by an extracted fact"}
    shim = _ScriptedShim()
    shim.invoke_script = [{"status": 400, "json": {"error": "render-blocked", "block": block}}]
    with _scripted_server(shim) as url:
        with pytest.raises(RenderBlocked) as exc:
            Client(url, "sek", timeout=5).render_and_wait("wsA", "userA", "i", "p", "en", "post")
    assert exc.value.block == block
    assert recorded_sleeps == []


def test_poll_failed_runner_failed_raises_jobfailed(recorded_sleeps: list[float]) -> None:
    """(h) A 500 {status: failed, code: runner-failed} ⇒ JobFailed(code, redrivable, terminal)."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [_failed(500, "runner-failed", False)]
    with _scripted_server(shim) as url:
        with pytest.raises(JobFailed) as exc:
            Client(url, "sek", poll_interval=0.1, timeout=5).generate_and_wait(
                "wsA", "userA", token="tok", idempotency_key="k"
            )
    assert exc.value.code == "runner-failed"
    assert exc.value.redrivable is False
    assert exc.value.terminal == {"envelope": {"ok": False, "code": "runner-failed"}, "results": []}


def test_poll_failed_open_string_code_surfaced_raw(recorded_sleeps: list[float]) -> None:
    """(§1.6) An unlisted transport code (``api-error``) is surfaced RAW, never a crash on an
    exhaustive switch (the open-string boundary)."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [_failed(500, "api-error", False)]
    with _scripted_server(shim) as url:
        with pytest.raises(JobFailed) as exc:
            Client(url, "sek", poll_interval=0.1, timeout=5).generate_and_wait(
                "wsA", "userA", token="tok", idempotency_key="k"
            )
    assert exc.value.code == "api-error"


def test_poll_failed_bare_error_token_surfaced_as_code(recorded_sleeps: list[float]) -> None:
    """(N1) A bare non-render-blocked 4xx ``{error: <token>}`` body — no top-level ``code`` —
    surfaces the RAW error token as ``JobFailed.code`` (never ``None``), still within the
    open-string contract (§1.6). Without the fallback the raw token would be silently dropped."""
    shim = _ScriptedShim()
    # A refused 4xx with ONLY an `error` token (no `code`), and it is NOT render-blocked.
    shim.invoke_script = [{"status": 400, "json": {"error": "handler-not-wired"}}]
    with _scripted_server(shim) as url:
        with pytest.raises(JobFailed) as exc:
            Client(url, "sek", poll_interval=0.1, timeout=5).render_and_wait(
                "wsA", "userA", "i", "p", "en", "post"
            )
    assert exc.value.code == "handler-not-wired"  # the raw token is surfaced, not None


def test_await_deadline_yields_jobtimeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """(e) A tiny ``max_poll_seconds`` with an always-202 wire ⇒ JobTimeout(redrivable=True); the
    fake clock advances only via the recorded sleeps (fully deterministic, no real server)."""
    state = {"t": 0.0}
    sleeps: list[float] = []

    def fake_sleep(d: float) -> None:
        sleeps.append(d)
        state["t"] += d

    monkeypatch.setattr(client_mod.time, "sleep", fake_sleep)
    monkeypatch.setattr(client_mod.time, "monotonic", lambda: state["t"])

    running = json.dumps(
        {"status": "running", "job": {"key": "r-1", "target_ids": ["t-1"]}}
    ).encode()
    opener = _RecordingOpener(lambda req: _FakeHTTPResponse(202, body=running))
    client = Client(
        "http://shim.test", "sek", opener=opener, poll_interval=1.0, max_poll_seconds=2.5
    )
    with pytest.raises(JobTimeout) as exc:
        client.render_and_wait("wsA", "userA", "i", "p", "en", "post")
    assert exc.value.redrivable is True
    assert sleeps == [1.0, 2.0]  # doubling backoff until the 2.5s deadline


def test_blank_retry_after_in_poll_falls_back_to_backoff(recorded_sleeps: list[float]) -> None:
    """(F-D#3, loop) A 429 with NO Retry-After header falls back to the backoff cadence (no
    ``int(None)`` crash)."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [
        {
            "status": 429,
            "json": {
                "status": "failed",
                "code": "rate-limit-backpressure",
                "redrivable": True,
                "job": {"key": "r-1", "target_ids": ["t-1"]},
            },
        },
        _done("r-1", ["t-1"], []),
    ]
    with _scripted_server(shim) as url:
        client = Client(url, "sek", poll_interval=0.1, timeout=5)
        result = client.render_and_wait("wsA", "userA", "i", "p", "en", "post")
    assert isinstance(result, Result)
    assert recorded_sleeps == [0.1, 0.2]  # backoff fallback, not a crash


def test_truncated_done_body_raises_malformed(recorded_sleeps: list[float]) -> None:
    """(j / F-H) A truncated ``done`` body (invalid JSON → json=None) raises a DEFINED error."""
    shim = _ScriptedShim()
    shim.invoke_script = [_accepted("r-1", ["t-1"])]
    shim.poll_script = [{"status": 200, "raw": b'{"status": "done", "results": ['}]  # truncated
    with _scripted_server(shim) as url:
        client = Client(url, "sek", poll_interval=0.1, timeout=5)
        with pytest.raises(MalformedResponse):
            client.render_and_wait("wsA", "userA", "i", "p", "en", "post")


def test_done_missing_results_raises_malformed(recorded_sleeps: list[float]) -> None:
    """(F-H) A 200 ``done`` body missing ``results[]`` is malformed, not a false success."""
    shim = _ScriptedShim()
    shim.invoke_script = [
        {"status": 200, "json": {"status": "done", "job": {"key": "r-1", "target_ids": ["t-1"]}}}
    ]
    with _scripted_server(shim) as url:
        with pytest.raises(MalformedResponse):
            Client(url, "sek", timeout=5).render_and_wait("wsA", "userA", "i", "p", "en", "post")


def test_generate_and_wait_requires_idempotency_key() -> None:
    """(§2.3) generate_and_wait raises fast (no network) on a missing/empty idempotency_key."""
    client = _fake_client()
    with pytest.raises(ValueError):
        client.generate_and_wait("wsA", "userA", token="tok", idempotency_key="")


def test_generate_and_wait_sends_generate_next_action(recorded_sleeps: list[float]) -> None:
    """generate_and_wait drives ``continue-session{action: generate-next}`` with the token."""
    shim = _ScriptedShim()
    shim.invoke_script = [_done("r-1", ["t-1"], [])]
    with _scripted_server(shim) as url:
        Client(url, "sek", timeout=5).generate_and_wait(
            "wsA", "userA", token="tok", idempotency_key="k", batch_size=3
        )
    path, body, _headers = shim.received[0]
    assert path == "/invoke"
    assert body["verb"] == "continue-session"
    assert body["token"] == "tok"
    assert body["params"]["action"] == "generate-next"
    assert body["params"]["batch_size"] == 3


def test_begin_session_forces_generate_none_and_returns_token(recorded_sleeps: list[float]) -> None:
    """(§2.3) begin_session FORCES ``generate="none"`` and returns the minted session token."""
    shim = _ScriptedShim()
    shim.invoke_script = [
        {"status": 200, "json": {"envelope": {"ok": True}, "results": [], "token": "tok-abc"}}
    ]
    with _scripted_server(shim) as url:
        handle = Client(url, "sek", timeout=5).begin_session(
            "wsA", "userA", selection={"topic": "t"}, generate="all"
        )
    assert handle.token == "tok-abc"
    _path, body, _headers = shim.received[0]
    assert body["verb"] == "begin-session"
    assert body["params"]["generate"] == "none"  # forced regardless of the caller's argument


# =============================================================================================
# Webhook receipt (clients.md §2.7) — parse_callback (pure) + fetch_after_callback (polls).
# =============================================================================================


def test_parse_callback_done_and_failed() -> None:
    ev_done = parse_callback(
        {"event": "job.done", "job": {"key": "r-1", "workspace": "wsA", "target_ids": ["t-1"]}}
    )
    assert isinstance(ev_done, CallbackEvent)
    assert (ev_done.event, ev_done.workspace, ev_done.key, ev_done.target_ids) == (
        "job.done",
        "wsA",
        "r-1",
        ["t-1"],
    )
    assert ev_done.code is None
    ev_failed = parse_callback(
        {
            "event": "job.failed",
            "job": {"key": "r-2", "workspace": "wsA", "target_ids": ["t-2"]},
            "code": "runner-failed",
            "redrivable": False,
        }
    )
    assert ev_failed.event == "job.failed"
    assert ev_failed.code == "runner-failed"
    assert ev_failed.redrivable is False


def test_parse_callback_rejects_unknown_event_or_non_object() -> None:
    with pytest.raises(ValueError):
        parse_callback({"event": "job.exploded", "job": {}})
    with pytest.raises(ValueError):
        parse_callback("not a mapping")


def test_client_callback_events_match_server_constants() -> None:
    """Anti-drift: the client's accepted event set == the server's SSOT event constants."""
    from pipeline import callback_delivery

    assert client_mod._CALLBACK_EVENTS == {
        callback_delivery.EVENT_DONE,
        callback_delivery.EVENT_FAILED,
    }


def test_fetch_after_callback_polls_to_result(recorded_sleeps: list[float]) -> None:
    """(§2.7) A woken client FETCHES the finished output through the authenticated poll door."""
    shim = _ScriptedShim()
    shim.poll_script = [_done("r-1", ["t-1"], [{"item": "woken"}])]
    with _scripted_server(shim) as url:
        client = Client(url, "sek", timeout=5)
        event = parse_callback(
            {"event": "job.done", "job": {"key": "r-1", "workspace": "wsA", "target_ids": ["t-1"]}}
        )
        result = client.fetch_after_callback(event, "userA")
    assert isinstance(result, Result)
    assert result.json["results"] == [{"item": "woken"}]
    assert [path for (path, _b, _h) in shim.received] == ["/poll"]


def test_3xx_surfaces_as_response_and_is_not_followed() -> None:
    """(§2.5) The real no-redirect opener surfaces a 3xx as a Response carrying its Location,
    and NEVER follows it (exactly one request received)."""
    shim = _ScriptedShim()
    shim.invoke_script = [
        {"status": 302, "headers": {"Location": "http://example.internal/evil"}, "json": {}}
    ]
    with _scripted_server(shim) as url:
        resp = Client(url, "sek", timeout=5).invoke("render", "wsA", "userA", {})
    assert resp.status == 302
    assert client_mod._header_get(resp.headers, "Location") == "http://example.internal/evil"
    assert len(shim.received) == 1  # the redirect was not followed


# =============================================================================================
# Layer 3 — real-wire smoke against http_shim.make_server (no real spawn).
# =============================================================================================


@contextmanager
def _real_shim(secret: str = "right-secret") -> Iterator[str]:
    from pipeline.api import http_shim

    server = http_shim.make_server("127.0.0.1", 0, secrets=frozenset({secret}))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_shim_wrong_secret_is_401_response() -> None:
    """A wrong secret against the REAL server is a 401 *Response* (not a raised error) — the auth
    header reaches the server and the HTTPError-as-Response funnel holds end-to-end (§2.5)."""
    with _real_shim() as url:
        resp = Client(url, "wrong-secret", timeout=5).invoke(
            "render", "wsA", "userA", {"item": "x"}
        )
    assert isinstance(resp, Response)
    assert resp.status == 401
    assert resp.json.get("error") == "unauthorized"


def test_real_shim_valid_secret_gets_past_auth() -> None:
    """A VALID secret gets past the auth gate on the real server (an unknown verb then 4xx's on its
    own merits — the point is auth accepted the ``Authorization: Bearer`` header)."""
    with _real_shim() as url:
        resp = Client(url, "right-secret", timeout=5).invoke("no-such-verb", "wsA", "userA", {})
    assert resp.status != 401
    assert resp.json is not None


def test_real_shim_empty_user_is_400_bad_request() -> None:
    """An EMPTY ``user`` (past auth) is refused 400 by the REAL shim — the client SENT the field, so
    the shim can enforce it (never a silently-omitted user). This is the wire-level proof that the
    B5 400 gap is closed: a real client→shim call with a bad user fails loud with a clear reason."""
    with _real_shim() as url:
        resp = Client(url, "right-secret", timeout=5).invoke("render", "wsA", "", {"item": "x"})
    assert resp.status == 400
    assert resp.json.get("error") == "bad-request"
    assert "user" in resp.json.get("detail", "")
