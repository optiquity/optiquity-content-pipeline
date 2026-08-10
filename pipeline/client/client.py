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

__all__ = ["DEFAULT_ZONE", "Client", "echoed_zone", "parse_callback"]

# --- The §23/Z4 isolation zone (design.md §23; the clients.md zone section lands in the Z9 sweep) -
# The zone segment between user and workspace in the store leaf
# ``users/<user>/zones/<zone>/workspaces/<workspace>/``. It rides EVERY request body next to
# ``user``/``workspace`` (the wire contract the shim reads); when omitted the door materializes this
# SAME literal default, so the client sends it explicitly and never diverges. Stdlib-only: the
# client owns its own copy of the wire default (like ``_INVOKE_PATH``), never a server constant.
DEFAULT_ZONE = "default"

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
    ``ValueError``. Extracts the ``job`` identity (workspace / zone / key / target_ids) and, on a
    failure wakeup, the ``code`` / ``redrivable`` fields. The ``zone`` (§23/Z4) is read off the
    ``job`` block next to ``workspace`` (the callback delivery names it there) so the woken client
    can fetch in the SAME zone the job ran in; it is ``None`` on a pre-zone wakeup that named none.
    It never fetches — the woken client calls :meth:`Client.fetch_after_callback` to retrieve the
    finished output through the poll."""
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
        zone=job.get("zone"),
    )


def echoed_zone(body: Any) -> str | None:
    """PURE: read the §23/Z4 zone the door ECHOED back in a result body (design.md §23), or
    ``None`` when it is absent.

    The zone rides the request body next to ``user``/``workspace`` and is ECHOED in the reply so a
    caller can confirm which zone served the call. This reader surfaces it from any result body the
    client returns — a raw :attr:`Response.json`, a :attr:`Result.json`, or a
    :attr:`SessionHandle.response`\\ ``.json`` — checking the Tier-A ``envelope.zone`` first, then a
    top-level ``zone`` (a 202/200 job body may echo it flat). It NEVER invents a value (§2.8): a
    body with no echoed zone reads ``None``, so a client can tell "the door did not echo a zone"
    from "the door echoed ``default``". A returned string is always non-empty."""
    if not isinstance(body, Mapping):
        return None
    envelope = body.get("envelope")
    if isinstance(envelope, Mapping):
        zone = envelope.get("zone")
        if isinstance(zone, str) and zone:
            return zone
    zone = body.get("zone")
    return zone if isinstance(zone, str) and zone else None


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
        user: str,
        params: Mapping[str, Any],
        token: Any = None,
        pins: Any = None,
        *,
        zone: str = DEFAULT_ZONE,
    ) -> Response:
        """``POST /invoke`` a verb (clients.md §1.2). The generic form forwards ANY verb, so the raw
        layer covers the whole startup-wired surface with no per-verb code.

        ``user`` is MANDATORY (the §23 isolation prefix, parallel to ``workspace``): the shim
        REQUIRES it on every ``/invoke`` body and 400s a missing/empty one, so it is a required
        positional here — never defaulted, never silently omitted. It rides the JSON body alongside
        ``workspace``, 1:1 with the wire contract the shim enforces.

        ``zone`` (§23/Z4) is the isolation zone between ``user`` and ``workspace``; it rides the
        SAME body next to ``user``/``workspace`` exactly as the shim reads it, and DEFAULTS to
        ``DEFAULT_ZONE`` (the door materializes the same literal when omitted). The door ECHOES it
        in the reply — read it back with :func:`echoed_zone`."""
        return self._request(
            _INVOKE_PATH,
            {
                "verb": verb,
                "workspace": workspace,
                "user": user,
                "zone": zone,
                "params": dict(params),
                "token": token,
                "pins": pins,
            },
        )

    def poll(
        self,
        workspace: str,
        user: str,
        key: str,
        target_ids: Sequence[str],
        *,
        zone: str = DEFAULT_ZONE,
    ) -> Response:
        """``POST /poll`` a submitted Tier-B job (clients.md §1.5). All four fields come from the
        202 ``job`` + ``poll.needs``.

        ``user`` is MANDATORY (the §23 isolation prefix, parallel to ``workspace``): the shim's poll
        handler REQUIRES it and 400s a missing/empty one, so it is a required positional here —
        never defaulted, never silently omitted.

        ``zone`` (§23/Z4) rides the body next to ``user``/``workspace`` exactly as on ``/invoke``,
        so a poll resolves in the SAME zone the submit ran in; it defaults to ``DEFAULT_ZONE``."""
        return self._request(
            _POLL_PATH,
            {
                "workspace": workspace,
                "user": user,
                "zone": zone,
                "key": key,
                "target_ids": list(target_ids),
            },
        )

    def list(  # noqa: A002
        self, type: str, workspace: str, user: str, filters: Any = None, *, zone: str = DEFAULT_ZONE
    ) -> Response:
        """Discovery ``list`` (a Tier-A verb): enumerate registry values of ``type``. ``user`` is
        the MANDATORY §23 isolation prefix (parallel to ``workspace``); ``zone`` (§23/Z4) rides the
        body alongside it (default ``DEFAULT_ZONE``)."""
        params: dict[str, Any] = {"type": type}
        if filters is not None:
            params["filters"] = filters
        return self.invoke("list", workspace, user, params, zone=zone)

    def get(  # noqa: A002
        self, type: str, id: str, workspace: str, user: str, *, zone: str = DEFAULT_ZONE
    ) -> Response:
        """Discovery ``get`` (a Tier-A verb): fetch one registry value of ``type`` by ``id``.
        ``user`` is the MANDATORY §23 isolation prefix (parallel to ``workspace``); ``zone``
        (§23/Z4) rides the body alongside it (default ``DEFAULT_ZONE``)."""
        return self.invoke("get", workspace, user, {"type": type, "id": id}, zone=zone)

    # --- The ergonomic async layer (clients.md §2.3) -----------------------------------------
    def begin_session(
        self,
        workspace: str,
        user: str,
        selection: Any,
        overrides: Any = None,
        pins: Any = None,
        generate: str = "none",  # noqa: ARG002 — accepted for surface parity; FORCED to "none"
        idempotency_key: str | None = None,
        *,
        zone: str = DEFAULT_ZONE,
    ) -> SessionHandle:
        """Begin a session and MINT the resumption token (clients.md §2.3). ``generate`` is FORCED
        to ``"none"`` client-side: the one-call ``begin-session{generate!=none}`` is a deferred
        ``501``, so the supported path is two calls (begin, then :meth:`generate_and_wait`). This is
        a Tier-A synchronous call; the returned :class:`SessionHandle` carries the session
        ``token``. ``user`` is the MANDATORY §23 isolation prefix (parallel to ``workspace``).

        ``zone`` (§23/Z4, default ``DEFAULT_ZONE``) selects the isolation zone; it rides the body
        and is ECHOED back on the returned :attr:`SessionHandle.zone` so the resume
        (:meth:`generate_and_wait`) carries the SAME zone the session began in — never a silent
        cross-zone resume."""
        params: dict[str, Any] = {"selection": selection, "generate": "none"}
        if overrides is not None:
            params["overrides"] = overrides
        if idempotency_key is not None:
            params["idempotency_key"] = idempotency_key
        response = self.invoke("begin-session", workspace, user, params, pins=pins, zone=zone)
        token = response.json.get("token") if isinstance(response.json, Mapping) else None
        return SessionHandle(workspace=workspace, token=token, response=response, zone=zone)

    def generate_and_wait(
        self,
        workspace: str,
        user: str,
        token: Any,
        idempotency_key: str,
        *,
        batch_size: int | None = None,
        only: Any = None,
        callback_url: str | None = None,
        zone: str = DEFAULT_ZONE,
        **extra: Any,
    ) -> Result:
        """Drive the served ``continue-session{generate-next}`` door to a terminal outcome (clients
        .md §2.3). ``idempotency_key`` is REQUIRED (the shim 400s otherwise, and a 409 re-drive
        reuses the SAME key so a retry is exactly-once) — a missing/empty key raises ``ValueError``
        fast, before any network. ``user`` is the MANDATORY §23 isolation prefix (parallel to
        ``workspace``).

        ``zone`` (§23/Z4, default ``DEFAULT_ZONE``) MUST be the SAME zone the session began in
        (:attr:`SessionHandle.zone`); it rides both the submit and every poll of the state machine,
        so a resume never silently crosses zones (a wrong zone refuses `isolation-violation` at the
        door — the session's ids do not resolve in the other zone's store)."""
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
            return self.invoke(
                "continue-session", workspace, user, dict(submit_params), token=token, zone=zone
            )

        return self._await_terminal(workspace, user, submit, zone=zone)

    def render_and_wait(
        self,
        workspace: str,
        user: str,
        item: str,
        platform: str,
        language: str,
        output_type: str,
        *,
        presentation: Any = None,
        force_reconcile: bool = False,
        idempotency_key: str | None = None,
        callback_url: str | None = None,
        zone: str = DEFAULT_ZONE,
    ) -> Result:
        """Render an item and resolve at the terminal outcome (clients.md §2.3). ``render`` is
        content-addressed + token-free, so ``idempotency_key`` is OPTIONAL. A cache hit returns a
        ``200`` at submit and collapses into the SAME :class:`Result` as the 202-then-poll path,
        with NO synthesized cache/cost field (§2.8). ``user`` is the MANDATORY §23 isolation prefix
        (parallel to ``workspace``); ``zone`` (§23/Z4, default ``DEFAULT_ZONE``) rides the submit
        and every poll so the whole traversal stays in one zone."""
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
            return self.invoke("render", workspace, user, dict(params), zone=zone)

        return self._await_terminal(workspace, user, submit, zone=zone)

    # --- The webhook fetch (clients.md §2.7) — no receiver server -----------------------------
    def fetch_after_callback(
        self, event: CallbackEvent, user: str, *, zone: str | None = None
    ) -> Result:
        """Authenticated "you've been woken, now FETCH" (clients.md §2.7). Given a parsed
        :class:`CallbackEvent`, poll the job through the same authenticated door and resolve at the
        terminal outcome. The payload is wakeup-only, so this explicit fetch is honest.

        ``user`` is the MANDATORY §23 isolation prefix (parallel to the ``workspace`` the event
        already carries): the poll REQUIRES it, so the woken client supplies its owning user
        explicitly — never defaulted, never silently omitted. (The wakeup payload does not yet
        carry ``user``, so it cannot be read off the event.)

        ``zone`` (§23/Z4) resolves to the SAME zone the job ran in: it defaults to the wakeup's own
        :attr:`CallbackEvent.zone` (the ``job`` block names it), so the fetch polls in the right
        zone with NO guess. An explicit ``zone`` argument overrides it; only a PRE-zone wakeup that
        named none falls back to :data:`DEFAULT_ZONE` — so the woken client fetches in the job's
        real zone, never silently crossing a zone boundary."""
        if not isinstance(event, CallbackEvent):
            raise TypeError("fetch_after_callback expects a CallbackEvent (from parse_callback)")
        # Prefer an explicit zone; else the wakeup's own zone; else the pre-zone default.
        eff = zone if zone is not None else (event.zone or DEFAULT_ZONE)

        def submit() -> Response:
            return self.poll(event.workspace, user, event.key, event.target_ids, zone=eff)

        return self._await_terminal(event.workspace, user, submit, zone=eff)

    # --- The poll state machine (clients.md §2.3) — identical in every language ---------------
    def _await_terminal(
        self, workspace: str, user: str, submit: Callable[[], Response], *, zone: str = DEFAULT_ZONE
    ) -> Result:
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
                # Prefer the stored terminal `code`; fall back to a bare `{error: <token>}` body's
                # token so a non-render-blocked 4xx surfaces its RAW token instead of dropping it to
                # None (still an OPEN string — the client reports the token, never switches on it).
                raise JobFailed(
                    code=(
                        (body.get("code") or body.get("error"))
                        if isinstance(body, Mapping)
                        else None
                    ),
                    redrivable=bool(body.get("redrivable")) if isinstance(body, Mapping) else False,
                    terminal=body.get("terminal") if isinstance(body, Mapping) else None,
                )

            time.sleep(delay)
            if time.monotonic() >= deadline:
                raise JobTimeout(redrivable=True)
            # With a captured job handle, POLL; a submit-time 429 (no handle yet) RE-SUBMITS. The
            # poll carries the SAME zone the submit ran in, so the machine never crosses zones.
            if key is not None and target_ids is not None:
                response = self.poll(workspace, user, key, target_ids, zone=zone)
            else:
                response = submit()
