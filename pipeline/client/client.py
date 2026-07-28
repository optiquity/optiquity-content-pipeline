"""The stdlib reference :class:`Client` for the optiquity content pipeline (provenance: framework).

Implements the canonical client surface of `docs/guide/clients.md` (Part 2) over ONE ``_request``
normalizer, using ONLY the standard library (``urllib`` + ``json`` + ``ssl``) — zero new
dependency. Every other language wrapper reads that same neutral page and implements the identical
method set / outcome set / poll state machine in its own idiom.

What this module gives you:

* the RAW layer (`clients.md` §2.2): :meth:`Client.invoke` / :meth:`Client.poll` /
  :meth:`Client.list` / :meth:`Client.get` — 1:1 with the wire;
* the ERGONOMIC async layer (§2.3): :meth:`Client.begin_session` (forces ``generate="none"``),
  :meth:`Client.generate_and_wait` (idempotency key REQUIRED), :meth:`Client.render_and_wait`
  (key optional) — each drives the shared poll state machine to a terminal outcome or the deadline;
* the WEBHOOK receipt (§2.7): :func:`parse_callback` (pure) + :meth:`Client.fetch_after_callback`
  (authenticated "you've been woken, now fetch") — NO receiver server;
* the OUTCOME set (§2.4): :class:`Result` returned, :class:`JobTimeout` / :class:`JobFailed` /
  :class:`RenderBlocked` raised (`pipeline.client.outcomes`).

THE NORMALIZED-RESPONSE RULE (§2.5). ``_request`` funnels every HTTP status into one
:class:`Response`: a ``urllib.error.HTTPError`` (a 4xx/5xx) is CAUGHT and returned as a Response;
the no-redirect opener surfaces a 3xx as a Response too (its handler raises an ``HTTPError``, which
``_request`` catches). Only a GENUINE connection failure / timeout — a ``URLError`` with no
``.status`` — propagates as an exception. HTTPS uses the platform's DEFAULT VERIFIED TLS context;
never an unverified one.
"""

from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pipeline.client.outcomes import (
    CallbackEvent,
    JobFailed,
    JobTimeout,
    MalformedResponse,
    RenderBlocked,
    Response,
    Result,
    SessionHandle,
)

__all__ = ["Client", "parse_callback"]

# --- HTTP statuses the poll state machine branches on (clients.md §2.3) -----------------------
_HTTP_OK = 200
_HTTP_ACCEPTED = 202
_HTTP_BAD_REQUEST = 400
_HTTP_CONFLICT = 409
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_GATEWAY_TIMEOUT = 504

# --- The two POST endpoints (clients.md §1.1) -------------------------------------------------
_INVOKE_PATH = "/invoke"
_POLL_PATH = "/poll"

# --- The two webhook event names (clients.md §1.7 / §2.7) -------------------------------------
_EVENT_DONE = "job.done"
_EVENT_FAILED = "job.failed"
_CALLBACK_EVENTS = frozenset({_EVENT_DONE, _EVENT_FAILED})

# --- Env config keys (clients.md §2.1) — identical across languages ---------------------------
_ENV_URL = "OPTIQUITY_SHIM_URL"
_ENV_SECRET = "OPTIQUITY_SHIM_SECRET"

# --- Construction defaults (clients.md §2.1) --------------------------------------------------
_DEFAULT_TIMEOUT = 30
_DEFAULT_POLL_INTERVAL = 1.0
_DEFAULT_MAX_POLL_SECONDS = 1320

# --- The poll backoff cadence (the §2.3 ``backoff = min(backoff * factor, cap)`` arm) ---------
_BACKOFF_FACTOR = 2.0
_BACKOFF_CAP = 30.0


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that REFUSES every 3xx so a redirect is surfaced as a Response, never
    followed (mirrors ``pipeline.callback_delivery._NoRedirectHandler``). ``build_opener`` dedupes
    handlers by type, so passing this subclass evicts the stdlib follower. It raises an
    ``HTTPError`` carrying the reply headers (incl. ``Location``); ``_request`` catches that and
    returns it as a :class:`Response` (clients.md §2.5)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"redirect {code} not followed (client no-follow guard)",
            headers,
            fp,
        )


def _build_opener(ssl_context: ssl.SSLContext | None) -> urllib.request.OpenerDirector:
    """The client's transport opener: a no-redirect handler + an HTTPS handler bound to a VERIFIED
    default TLS context (clients.md §2.5 — never an unverified one). ``build_opener`` prepends the
    stdlib default handlers, so plain HTTP works too."""
    context = ssl_context if ssl_context is not None else ssl.create_default_context()
    return urllib.request.build_opener(
        _NoRedirectHandler,
        urllib.request.HTTPSHandler(context=context),
    )


def _header_get(headers: Mapping[str, str], name: str) -> str | None:
    """Case-insensitive header lookup (HTTP header names are case-insensitive on the wire)."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return None


def _response_from(obj: Any) -> Response:
    """Normalize an opener response OR a caught ``HTTPError`` into one :class:`Response`. The JSON
    parse is GUARDED (clients.md §2.6): a non-JSON / empty body → ``json=None``, status preserved,
    never a ``json.loads`` crash."""
    status = getattr(obj, "status", None)
    if not isinstance(status, int):  # a caught HTTPError exposes ``.code``
        status = getattr(obj, "code", None)
    raw_headers = getattr(obj, "headers", None)
    headers: dict[str, str] = dict(raw_headers.items()) if raw_headers is not None else {}
    body = obj.read()
    try:
        parsed = json.loads(body) if body else None
    except (ValueError, UnicodeDecodeError):
        parsed = None
    return Response(status=int(status), headers=headers, json=parsed)


def parse_callback(payload: Any) -> CallbackEvent:
    """PURE (no network): validate + parse a webhook WAKEUP body into a :class:`CallbackEvent`
    (clients.md §2.7). Rejects any ``event`` outside ``{job.done, job.failed}`` with a
    ``ValueError``. Extracts the ``job`` identity (workspace / key / target_ids) and, on a failure
    wakeup, the ``code`` / ``redrivable`` fields. It never fetches — the woken client calls
    :meth:`Client.fetch_after_callback` to retrieve the finished output through the poll."""
    if not isinstance(payload, Mapping):
        raise ValueError("callback payload must be a JSON object")
    event = payload.get("event")
    if event not in _CALLBACK_EVENTS:
        raise ValueError(
            f"unknown callback event: {event!r} (expected one of {sorted(_CALLBACK_EVENTS)})"
        )
    job = payload.get("job")
    job = job if isinstance(job, Mapping) else {}
    target_ids = job.get("target_ids")
    return CallbackEvent(
        event=event,
        workspace=job.get("workspace"),
        key=job.get("key"),
        target_ids=list(target_ids) if isinstance(target_ids, list) else [],
        code=payload.get("code"),
        redrivable=payload.get("redrivable"),
    )


class Client:
    """The canonical pipeline client (clients.md Part 2), stdlib-only.

    Construction / configuration (§2.1). The auth secret rides ``Authorization: Bearer <secret>``
    by default, or ``X-API-Key: <secret>`` when ``api_key_header=True``. ``timeout`` is per-request
    seconds; ``poll_interval`` is the initial poll cadence; ``max_poll_seconds`` is the overall
    await deadline (~ the job lifetime). ``opener`` / ``ssl_context`` are test/advanced seams — the
    default opener is no-redirect + verified TLS."""

    def __init__(
        self,
        base_url: str,
        secret: str,
        *,
        api_key_header: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
        max_poll_seconds: float = _DEFAULT_MAX_POLL_SECONDS,
        opener: Any = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not secret:
            raise ValueError("secret is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.max_poll_seconds = max_poll_seconds
        self._auth_header: tuple[str, str] = (
            ("X-API-Key", secret) if api_key_header else ("Authorization", f"Bearer {secret}")
        )
        self._opener = opener if opener is not None else _build_opener(ssl_context)

    @classmethod
    def from_env(cls, **kwargs: Any) -> Client:
        """Build a client from the env config (clients.md §2.1): ``OPTIQUITY_SHIM_URL`` +
        ``OPTIQUITY_SHIM_SECRET`` — identical across languages. Raises ``ValueError`` if either is
        unset (the secret NEVER comes from argv)."""
        base_url = os.environ.get(_ENV_URL)
        secret = os.environ.get(_ENV_SECRET)
        if not base_url:
            raise ValueError(f"{_ENV_URL} is not set")
        if not secret:
            raise ValueError(f"{_ENV_SECRET} is not set")
        return cls(base_url, secret, **kwargs)

    # --- The transport primitive (clients.md §2.5) -------------------------------------------
    def _request(self, path: str, payload: Mapping[str, Any]) -> Response:
        """POST ``payload`` as JSON to ``path`` and NORMALIZE the reply into one :class:`Response`.

        A ``urllib.error.HTTPError`` (a 4xx/5xx, and the no-redirect handler's refused-3xx raise)
        is CAUGHT and returned as a Response. A genuine ``URLError`` / timeout (no ``.status``) is
        NOT caught — it propagates as the single exception channel (§2.5)."""
        name, value = self._auth_header
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", name: value},
        )
        try:
            raw = self._opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            return _response_from(exc)
        try:
            return _response_from(raw)
        finally:
            raw.close()

    def _retry_after_seconds(self, headers: Mapping[str, str], fallback: float) -> float:
        """Parse ``Retry-After`` as INTEGER delta-seconds (clients.md §2.3). Absent / blank /
        non-integer → fall back to the backoff cadence (§2.6); never crash on ``int(None)``."""
        raw = _header_get(headers, "Retry-After")
        if raw is None:
            return fallback
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return fallback

    # --- The raw layer, 1:1 with the wire (clients.md §2.2) ----------------------------------
    def invoke(
        self,
        verb: str,
        workspace: str,
        params: Mapping[str, Any],
        token: Any = None,
        pins: Any = None,
    ) -> Response:
        """``POST /invoke`` a verb (clients.md §1.2). The generic form forwards ANY verb, so the raw
        layer covers the whole startup-wired surface with no per-verb code."""
        return self._request(
            _INVOKE_PATH,
            {
                "verb": verb,
                "workspace": workspace,
                "params": dict(params),
                "token": token,
                "pins": pins,
            },
        )

    def poll(self, workspace: str, key: str, target_ids: Sequence[str]) -> Response:
        """``POST /poll`` a submitted Tier-B job (clients.md §1.5). All three fields come from the
        202 ``job`` + ``poll.needs``."""
        return self._request(
            _POLL_PATH,
            {"workspace": workspace, "key": key, "target_ids": list(target_ids)},
        )

    def list(self, type: str, workspace: str, filters: Any = None) -> Response:  # noqa: A002
        """Discovery ``list`` (a Tier-A verb): enumerate registry values of ``type``."""
        params: dict[str, Any] = {"type": type}
        if filters is not None:
            params["filters"] = filters
        return self.invoke("list", workspace, params)

    def get(self, type: str, id: str, workspace: str) -> Response:  # noqa: A002
        """Discovery ``get`` (a Tier-A verb): fetch one registry value of ``type`` by ``id``."""
        return self.invoke("get", workspace, {"type": type, "id": id})

    # --- The ergonomic async layer (clients.md §2.3) -----------------------------------------
    def begin_session(
        self,
        workspace: str,
        selection: Any,
        overrides: Any = None,
        pins: Any = None,
        generate: str = "none",  # noqa: ARG002 — accepted for surface parity; FORCED to "none"
        idempotency_key: str | None = None,
    ) -> SessionHandle:
        """Begin a session and MINT the resumption token (clients.md §2.3). ``generate`` is FORCED
        to ``"none"`` client-side: the one-call ``begin-session{generate!=none}`` is a deferred
        ``501``, so the supported path is two calls (begin, then :meth:`generate_and_wait`). This is
        a Tier-A synchronous call; the returned :class:`SessionHandle` carries the session
        ``token``."""
        params: dict[str, Any] = {"selection": selection, "generate": "none"}
        if overrides is not None:
            params["overrides"] = overrides
        if idempotency_key is not None:
            params["idempotency_key"] = idempotency_key
        response = self.invoke("begin-session", workspace, params, pins=pins)
        token = response.json.get("token") if isinstance(response.json, Mapping) else None
        return SessionHandle(workspace=workspace, token=token, response=response)

    def generate_and_wait(
        self,
        workspace: str,
        token: Any,
        idempotency_key: str,
        *,
        batch_size: int | None = None,
        only: Any = None,
        callback_url: str | None = None,
        **extra: Any,
    ) -> Result:
        """Drive the served ``continue-session{generate-next}`` door to a terminal outcome (clients
        .md §2.3). ``idempotency_key`` is REQUIRED (the shim 400s otherwise, and a 409 re-drive
        reuses the SAME key so a retry is exactly-once) — a missing/empty key raises ``ValueError``
        fast, before any network."""
        if not idempotency_key:
            raise ValueError(
                "generate_and_wait requires a non-empty idempotency_key (clients.md §2.3)"
            )
        submit_params: dict[str, Any] = {
            "action": "generate-next",
            "idempotency_key": idempotency_key,
        }
        if batch_size is not None:
            submit_params["batch_size"] = batch_size
        if only is not None:
            submit_params["only"] = only
        if callback_url is not None:
            submit_params["callback_url"] = callback_url
        submit_params.update(extra)

        def submit() -> Response:
            return self.invoke("continue-session", workspace, dict(submit_params), token=token)

        return self._await_terminal(workspace, submit)

    def render_and_wait(
        self,
        workspace: str,
        item: str,
        platform: str,
        language: str,
        output_type: str,
        *,
        presentation: Any = None,
        force_reconcile: bool = False,
        idempotency_key: str | None = None,
        callback_url: str | None = None,
    ) -> Result:
        """Render an item and resolve at the terminal outcome (clients.md §2.3). ``render`` is
        content-addressed + token-free, so ``idempotency_key`` is OPTIONAL. A cache hit returns a
        ``200`` at submit and collapses into the SAME :class:`Result` as the 202-then-poll path,
        with NO synthesized cache/cost field (§2.8)."""
        params: dict[str, Any] = {
            "item": item,
            "platform": platform,
            "language": language,
            "output_type": output_type,
        }
        if presentation is not None:
            params["presentation"] = presentation
        if force_reconcile:
            params["force_reconcile"] = True
        if idempotency_key is not None:
            params["idempotency_key"] = idempotency_key
        if callback_url is not None:
            params["callback_url"] = callback_url

        def submit() -> Response:
            return self.invoke("render", workspace, dict(params))

        return self._await_terminal(workspace, submit)

    # --- The webhook fetch (clients.md §2.7) — no receiver server -----------------------------
    def fetch_after_callback(self, event: CallbackEvent) -> Result:
        """Authenticated "you've been woken, now FETCH" (clients.md §2.7). Given a parsed
        :class:`CallbackEvent`, poll the job through the same authenticated door and resolve at the
        terminal outcome. The payload is wakeup-only, so this explicit fetch is honest."""
        if not isinstance(event, CallbackEvent):
            raise TypeError("fetch_after_callback expects a CallbackEvent (from parse_callback)")

        def submit() -> Response:
            return self.poll(event.workspace, event.key, event.target_ids)

        return self._await_terminal(event.workspace, submit)

    # --- The poll state machine (clients.md §2.3) — identical in every language ---------------
    def _await_terminal(self, workspace: str, submit: Callable[[], Response]) -> Result:
        """Run the canonical poll state machine to a terminal OUTCOME or the deadline.

        ``submit`` (re-)submits with the SAME idempotency_key and returns a :class:`Response`; the
        initial submit and a ``409`` re-drive both call it. The exact branch set (clients.md §2.3):

        * ``200`` & ``status == "done"``        → return :class:`Result`;
        * ``202`` (accepted/running)            → sleep(backoff), poll;
        * ``429`` (submit OR poll)              → sleep(integer ``Retry-After``), retry;
        * ``504``                               → raise :class:`JobTimeout` (redrivable);
        * ``409`` (re-drivable)                 → re-submit the SAME key, continue;
        * ``400 {error: render-blocked}``       → raise :class:`RenderBlocked`;
        * any other ``4xx/5xx`` (failed)        → raise :class:`JobFailed`;
        * on the await deadline                 → raise :class:`JobTimeout` (redrivable).

        A ``200`` that is NOT a well-formed ``{status: done, results: [...]}`` body → raise
        :class:`MalformedResponse` (§2.6). ``Retry-After`` is INTEGER delta-seconds; a blank/absent/
        non-integer value falls back to the backoff cadence (§2.6)."""
        deadline = time.monotonic() + self.max_poll_seconds
        backoff = self.poll_interval
        key: str | None = None
        target_ids: list[str] | None = None
        response = submit()

        while True:
            body = response.json if isinstance(response.json, Mapping) else None
            if isinstance(body, Mapping):
                job = body.get("job")
                if isinstance(job, Mapping):
                    job_key = job.get("key")
                    job_targets = job.get("target_ids")
                    if isinstance(job_key, str) and job_key:
                        key = job_key
                    if isinstance(job_targets, list) and job_targets:
                        target_ids = list(job_targets)

            status = response.status

            # 200 done → Result; any other 200 is a malformed/truncated done body (§2.6 / F-H).
            if status == _HTTP_OK:
                if (
                    isinstance(body, Mapping)
                    and body.get("status") == "done"
                    and isinstance(body.get("results"), list)
                ):
                    return Result(json=response.json)
                raise MalformedResponse(
                    "poll returned 200 without a well-formed {status: done, results: [...]} body",
                    response=response,
                )

            # 504 timeout-class terminal → JobTimeout (re-drivable).
            if status == _HTTP_GATEWAY_TIMEOUT:
                raise JobTimeout(redrivable=True)

            # 409 re-drivable → re-submit the SAME idempotency_key immediately (no sleep), continue.
            if status == _HTTP_CONFLICT:
                if time.monotonic() >= deadline:
                    raise JobTimeout(redrivable=True)
                response = submit()
                continue

            # 400 render-blocked → RenderBlocked (a refused render, surfaced with its block record).
            if (
                status == _HTTP_BAD_REQUEST
                and isinstance(body, Mapping)
                and body.get("error") == "render-blocked"
            ):
                raise RenderBlocked(block=body.get("block"))

            # 202 → sleep the backoff cadence; 429 → sleep the integer Retry-After.
            if status == _HTTP_ACCEPTED:
                delay: float = backoff
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)
            elif status == _HTTP_TOO_MANY_REQUESTS:
                delay = self._retry_after_seconds(response.headers, backoff)
                backoff = min(backoff * _BACKOFF_FACTOR, _BACKOFF_CAP)
            else:
                # any other 4xx/5xx is a stored terminal failure → JobFailed (raw open-string code).
                raise JobFailed(
                    code=body.get("code") if isinstance(body, Mapping) else None,
                    redrivable=bool(body.get("redrivable")) if isinstance(body, Mapping) else False,
                    terminal=body.get("terminal") if isinstance(body, Mapping) else None,
                )

            time.sleep(delay)
            if time.monotonic() >= deadline:
                raise JobTimeout(redrivable=True)
            # With a captured job handle, POLL; a submit-time 429 (no handle yet) RE-SUBMITS.
            if key is not None and target_ids is not None:
                response = self.poll(workspace, key, target_ids)
            else:
                response = submit()
