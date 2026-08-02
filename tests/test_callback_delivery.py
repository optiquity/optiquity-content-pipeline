"""DR-1 W3c tests: the webhook-callback DELIVERY — the outbound completion WAKEUP ping.

HERMETIC — NO real outbound network. The opener, the DNS resolver, and `sleep` are INJECTED into
`deliver_callback` everywhere, so every branch (delivery, the DNS-rebinding re-check, the
no-redirect refusal, the bounded retry, the timeout) drives with fakes and never touches real DNS or
a remote host. The ONE real socket is a LOCAL `http.server` on 127.0.0.1:0 used to prove the REAL
no-redirect opener refuses to FOLLOW a 3xx (injection can't exercise the opener's own follow logic);
it is loopback-only and never egresses.

The load-bearing invariants proven here (`pipeline.callback_delivery`):
- **Wakeup-only payload** — a `job.done` posts `event`/`job`/`poll` ONLY (no artifact content); a
  `job.failed` adds `code`/`redrivable`. The client is woken and fetches via the poll door.
- **Re-validate at delivery (DNS-rebinding defense)** — a URL that passed submit but now resolves to
  a private/metadata IP is REFUSED (`rejected-at-delivery`); the opener is never touched.
- **No redirects** — a 3xx is a delivery FAILURE, never a bounce to the redirect target.
- **Bounded retry + timeout** — exactly `CALLBACK_MAX_ATTEMPTS` tries with injected backoff, each
  issued with the per-request socket timeout; then give up (`failed`).
- **Never raises** — any failure is caught and turned into a recorded status.
"""

from __future__ import annotations

import http.server
import json
import threading
import urllib.error
import urllib.request

import pytest

from pipeline import callback_policy
from pipeline.api.jobrunner import JobSpec, RunOutcome
from pipeline.callback_delivery import (
    _REDRIVABLE_TERMINAL_CODES,
    CALLBACK_STATUS_DELIVERED,
    CALLBACK_STATUS_FAILED,
    CALLBACK_STATUS_REJECTED_AT_DELIVERY,
    CALLBACK_STATUS_SKIPPED,
    EVENT_DONE,
    EVENT_FAILED,
    _code_is_redrivable,
    build_callback_payload,
    build_no_redirect_opener,
    deliver_callback,
)
from pipeline.opdefaults import (
    CALLBACK_BACKOFF_SECONDS,
    CALLBACK_MAX_ATTEMPTS,
    CALLBACK_TIMEOUT_SECONDS,
)

# §7.4 literal artifact ids (the predictable target set) + generic fixtures — no instance content.
A = "a-9f3c07d21b44e8aa"
B = "a-1111111111111111"
KEY = "r-0123456789abcdef"
CB = "https://hooks.example.com/exec-1"
ALLOWED = frozenset({"hooks.example.com"})
GLOBAL_V4 = "93.184.216.34"  # a genuinely global unicast IPv4 (documentation corpus)
METADATA = "169.254.169.254"  # the link-local cloud-metadata address the SSRF guard always refuses


def _no_sleep(_seconds: float) -> None:
    """A sleep seam that never waits — tests are instant."""


def _resolve_to(*ips: str):
    """A fake resolver returning a FIXED IP list — the DNS seam, no real resolution."""

    def _resolve(_host: str) -> list[str]:
        return list(ips)

    return _resolve


class _FakeResponse:
    """A minimal opener response exposing `.status` + `.close()` (the shape delivery reads)."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _RecordingOpener:
    """A fake opener that RECORDS each (request, timeout) and RETURNS a `_FakeResponse(status)`."""

    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float | None] = []

    def open(self, request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append(request)
        self.timeouts.append(timeout)
        return _FakeResponse(self.status)


class _RaisingOpener:
    """A fake opener whose `.open` RAISES a fresh exc each call (network error / HTTPError) — drives
    the retry path and proves a raise never escapes `deliver_callback`."""

    def __init__(self, exc_factory) -> None:  # noqa: ANN001
        self.exc_factory = exc_factory
        self.requests: list[urllib.request.Request] = []

    def open(self, request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append(request)
        raise self.exc_factory()


class _NeverOpener:
    """A fake opener that FAILS the test if ever opened (the reject-before-POST assertions)."""

    def open(self, request, timeout=None):  # noqa: ANN001, ANN201
        raise AssertionError("opener.open must NOT be called — nothing should be POSTed")


class _RecordingSleep:
    """Records each backoff duration slept (injected so the bounded retry is instant + asserted)."""

    def __init__(self) -> None:
        self.durations: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.durations.append(seconds)


def _spec(callback_url: str | None = CB, target_ids=(A, B)) -> JobSpec:
    return JobSpec(
        key=KEY,
        verb="continue-session",
        workspace="wsA",
        user="acme",
        params={"action": "generate-next"},
        idempotency_key="exec-1",
        root="/repo-root",
        callback_url=callback_url,
        target_ids=tuple(target_ids),
        allowed_callback_hosts=ALLOWED,
    )


def _deliver(spec, outcome, *, resolve=None, opener=None, sleep=_no_sleep, allowed_hosts=ALLOWED):  # noqa: ANN001, ANN201
    return deliver_callback(
        spec,
        outcome,
        allowed_hosts=allowed_hosts,
        resolve=resolve if resolve is not None else _resolve_to(GLOBAL_V4),
        opener=opener,
        sleep=sleep,
    )


# ---------------------------------------------------------------------------
# Delivery + the WAKEUP-ONLY payload.
# ---------------------------------------------------------------------------


class TestDoneDelivery:
    def test_done_posts_wakeup_only_and_reports_delivered(self) -> None:
        opener = _RecordingOpener(status=200)
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert status == CALLBACK_STATUS_DELIVERED
        assert len(opener.requests) == 1  # a 2xx on the first attempt — no retry
        req = opener.requests[0]
        assert req.get_method() == "POST"
        assert req.full_url == CB
        assert req.get_header("Content-type") == "application/json"
        payload = json.loads(req.data)
        # WAKEUP-ONLY: event + job identity + poll pointer — and NOTHING else on a done event (no
        # artifact/result content, no failure fields).
        assert set(payload) == {"event", "job", "poll"}
        assert payload["event"] == EVENT_DONE  # "job.done"
        assert payload["job"] == {"key": KEY, "workspace": "wsA", "target_ids": [A, B]}
        assert payload["poll"] == {
            "path": "/poll",
            "method": "POST",
            "needs": ["workspace", "user", "key", "target_ids"],
        }

    def test_a_deterministic_skip_is_also_a_job_done(self) -> None:
        opener = _RecordingOpener(200)
        _deliver(_spec(), RunOutcome("skip-deterministic", None, False), opener=opener)
        assert json.loads(opener.requests[0].data)["event"] == EVENT_DONE


class TestFailedDelivery:
    def test_failed_posts_job_failed_with_code_and_redrivable_true(self) -> None:
        opener = _RecordingOpener(200)
        status = _deliver(_spec(), RunOutcome("terminal-returned", "timeout", True), opener=opener)
        assert status == CALLBACK_STATUS_DELIVERED
        payload = json.loads(opener.requests[0].data)
        assert payload["event"] == EVENT_FAILED  # "job.failed"
        assert payload["code"] == "timeout"
        assert payload["redrivable"] is True  # a timeout is re-drivable by the same key

    def test_a_wiring_terminal_is_reported_not_redrivable(self) -> None:
        opener = _RecordingOpener(200)
        _deliver(_spec(), RunOutcome("terminal-raised", "runner-failed", True), opener=opener)
        payload = json.loads(opener.requests[0].data)
        assert payload["event"] == EVENT_FAILED
        assert payload["code"] == "runner-failed"
        assert payload["redrivable"] is False  # a wiring/env failure a re-drive cannot fix


# ---------------------------------------------------------------------------
# SECURITY — re-validate at delivery (DNS-rebinding) + no redirects.
# ---------------------------------------------------------------------------


class TestReValidateAtDelivery:
    def test_rebind_to_a_metadata_ip_is_rejected_and_never_posts(self) -> None:
        # A URL that passed at SUBMIT (host was global) but whose delivery-time resolution now
        # returns the cloud-metadata address → REFUSED here; the opener is NEVER opened.
        status = _deliver(
            _spec(),
            RunOutcome("clean", None, False),
            resolve=_resolve_to(METADATA),
            opener=_NeverOpener(),
        )
        assert status == CALLBACK_STATUS_REJECTED_AT_DELIVERY

    def test_an_empty_allow_list_at_delivery_is_rejected(self) -> None:
        # Defense in depth: even if a URL slipped past submit, an empty delivery-time allow-list
        # (callbacks-disabled) refuses it — nothing is POSTed.
        status = _deliver(
            _spec(),
            RunOutcome("clean", None, False),
            allowed_hosts=frozenset(),
            opener=_NeverOpener(),
        )
        assert status == CALLBACK_STATUS_REJECTED_AT_DELIVERY

    def test_a_resolver_failure_at_delivery_is_rejected_not_crashed(self) -> None:
        def _boom(_host: str) -> list[str]:
            raise OSError("dns down")

        status = _deliver(
            _spec(), RunOutcome("clean", None, False), resolve=_boom, opener=_NeverOpener()
        )
        assert status == CALLBACK_STATUS_REJECTED_AT_DELIVERY


class TestNoRedirects:
    def test_a_3xx_is_treated_as_a_failure_never_followed(self) -> None:
        # deliver_callback sees the no-redirect opener's refusal (a raised HTTPError with the 3xx
        # code) as a non-delivery → retried, then `failed`; it never bounces to the redirect target.
        opener = _RaisingOpener(lambda: urllib.error.HTTPError(CB, 302, "Found", {}, None))  # type: ignore[arg-type]
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert status == CALLBACK_STATUS_FAILED
        assert len(opener.requests) == CALLBACK_MAX_ATTEMPTS

    def test_the_real_opener_refuses_to_follow_and_never_reaches_the_target(self) -> None:
        # The REAL no-redirect opener against a LOCAL (loopback) server that 302s to /internal:
        # opener.open RAISES the 302 and /internal is NEVER reached (the SSRF no-follow guard).
        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", 0))
                if length:
                    self.rfile.read(length)
                if self.path == "/start":
                    self.send_response(302)
                    self.send_header("Location", "/internal")
                    self.end_headers()
                elif self.path == "/internal":
                    self.server.internal_hit = True  # type: ignore[attr-defined]
                    self.send_response(200)
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *_a) -> None:  # silence the test log
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        server.internal_hit = False  # type: ignore[attr-defined]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            _host, port = server.server_address
            opener = build_no_redirect_opener()
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/start", data=b"{}", method="POST"
            )
            with pytest.raises(urllib.error.HTTPError) as excinfo:
                opener.open(req, timeout=5)
            assert excinfo.value.code == 302  # refused, not followed
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        assert server.internal_hit is False  # the redirect TARGET was never reached


# ---------------------------------------------------------------------------
# Bounded retry + timeout + never-crashes.
# ---------------------------------------------------------------------------


class TestRetryAndTimeout:
    def test_a_network_error_retries_exactly_max_attempts_then_fails(self) -> None:
        opener = _RaisingOpener(lambda: urllib.error.URLError("no route"))
        sleep = _RecordingSleep()
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener, sleep=sleep)
        assert status == CALLBACK_STATUS_FAILED
        assert len(opener.requests) == CALLBACK_MAX_ATTEMPTS  # exactly the bounded attempts
        # sleep only BETWEEN tries (MAX-1 gaps), exponential base * 4**i (1 s, 4 s, …).
        assert sleep.durations == [
            CALLBACK_BACKOFF_SECONDS * (4**i) for i in range(CALLBACK_MAX_ATTEMPTS - 1)
        ]

    def test_a_500_http_error_retries_then_fails(self) -> None:
        opener = _RaisingOpener(lambda: urllib.error.HTTPError(CB, 500, "err", {}, None))  # type: ignore[arg-type]
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert status == CALLBACK_STATUS_FAILED
        assert len(opener.requests) == CALLBACK_MAX_ATTEMPTS

    def test_a_non_2xx_response_is_a_failure_and_is_retried(self) -> None:
        # A fake opener that RETURNS a 503 response (rather than raising) is still a non-delivery.
        opener = _RecordingOpener(status=503)
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert status == CALLBACK_STATUS_FAILED
        assert len(opener.requests) == CALLBACK_MAX_ATTEMPTS

    def test_each_post_is_issued_with_the_socket_timeout(self) -> None:
        opener = _RecordingOpener(200)
        _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert opener.timeouts == [CALLBACK_TIMEOUT_SECONDS]  # the per-request timeout is passed

    def test_an_arbitrary_opener_error_is_caught_never_raised(self) -> None:
        # A bug-shaped exception (not a URLError) is still caught → failed, never a runner crash.
        opener = _RaisingOpener(lambda: ValueError("boom"))
        status = _deliver(_spec(), RunOutcome("clean", None, False), opener=opener)
        assert status == CALLBACK_STATUS_FAILED


class TestNoCallbackUrl:
    def test_no_callback_url_posts_nothing_and_reports_skipped(self) -> None:
        status = _deliver(
            _spec(callback_url=None), RunOutcome("clean", None, False), opener=_NeverOpener()
        )
        assert status == CALLBACK_STATUS_SKIPPED


# ---------------------------------------------------------------------------
# Payload builder + drift guards + production defaults.
# ---------------------------------------------------------------------------


class TestPayloadAndDefaults:
    def test_build_payload_done_is_wakeup_only(self) -> None:
        payload = build_callback_payload(_spec(target_ids=[A]), RunOutcome("clean", None, False))
        assert set(payload) == {"event", "job", "poll"}
        assert payload["event"] == EVENT_DONE
        assert payload["job"]["target_ids"] == [A]

    def test_build_payload_failed_carries_code_and_redrivable(self) -> None:
        payload = build_callback_payload(
            _spec(), RunOutcome("terminal-returned", "rate-limit-backpressure", True)
        )
        assert payload["event"] == EVENT_FAILED
        assert payload["code"] == "rate-limit-backpressure"
        assert payload["redrivable"] is True

    def test_poll_block_matches_the_shim_accepted_body(self) -> None:
        # DRIFT GUARD: the wakeup's poll pointer must equal the shim's 202-ack poll block, so the
        # two poll contracts never diverge (no shim import in production — a test-only cross-check).
        from pipeline.api import http_shim

        payload = build_callback_payload(_spec(target_ids=[A]), RunOutcome("clean", None, False))
        assert payload["poll"] == http_shim._accepted_body(KEY, [A])["poll"]

    def test_redrivable_codes_agree_with_the_shim_terminal_status_map(self) -> None:
        # DRIFT GUARD: every code the wakeup marks `redrivable` maps to a re-drivable poll status
        # (504/429) in the shim; a wiring/envelope code does not.
        from pipeline.api import http_shim

        redrivable_statuses = {
            http_shim._HTTP_GATEWAY_TIMEOUT,
            http_shim._HTTP_TOO_MANY_REQUESTS,
        }
        for code in _REDRIVABLE_TERMINAL_CODES:
            assert http_shim._terminal_status_for(code) in redrivable_statuses
        for code in ("runner-failed", "unknown-verb"):
            assert not _code_is_redrivable(code)
            assert http_shim._terminal_status_for(code) not in redrivable_statuses

    def test_production_defaults_are_the_real_resolver_and_time_sleep(self) -> None:
        import inspect
        import time

        sig = inspect.signature(deliver_callback)
        # The default DNS resolver IS callback_policy's live getaddrinfo resolver (re-used here).
        assert sig.parameters["resolve"].default is callback_policy._default_resolve
        assert sig.parameters["sleep"].default is time.sleep
        assert sig.parameters["opener"].default is None  # built lazily via build_no_redirect_opener

    def test_the_default_opener_has_no_redirect_follower(self) -> None:
        opener = build_no_redirect_opener()
        type_names = {type(h).__name__ for h in opener.handlers}
        assert "HTTPRedirectHandler" not in type_names  # the built-in follower was evicted
        assert any("NoRedirect" in name for name in type_names)
