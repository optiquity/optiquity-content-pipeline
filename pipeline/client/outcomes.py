"""Typed outcomes + value types for the stdlib pipeline client (provenance: framework).

The canonical outcome set (`docs/guide/clients.md` §2.4) is IDENTICAL across every language
wrapper; only the delivery channel is idiom. Python's channel is:

* ``return`` for the success value :class:`Result`;
* ``raise`` for the three failure outcomes :class:`JobTimeout`, :class:`JobFailed`,
  :class:`RenderBlocked` (all subclass :class:`ClientError`);
* a genuine transport failure (a ``urllib`` ``URLError`` / timeout with no ``.status``) is NOT a
  :class:`ClientError` — it propagates unchanged (§2.5). Only the *deliberate* client-raised
  conditions above (plus a malformed ``done`` body, :class:`MalformedResponse`) are ClientErrors.

:class:`Response` is the normalized transport value (§2.5): every HTTP status funnels into one
Response, and ``json`` is ``None`` on a non-JSON / empty body (the guarded parse, §2.6).
:class:`CallbackEvent` is the parsed webhook wakeup (§2.7); :class:`SessionHandle` is the Tier-A
``begin-session`` handle (§2.3).

This module is STDLIB-ONLY (dataclasses + typing) and imports nothing from the server package —
the wrapper reads the neutral contract page, never a server constant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Response:
    """The normalized transport value (`clients.md` §2.5).

    Every HTTP status funnels into ONE Response — a 4xx/5xx is a Response, never a raised
    transport error. ``json`` is ``None`` on a non-JSON / empty body (the guarded parse, §2.6);
    ``headers`` preserves the reply headers (case as received)."""

    status: int
    headers: Mapping[str, str]
    json: Any


@dataclass(frozen=True)
class Result:
    """A materialized job (`clients.md` §2.4). ``json`` is the whole ``200 {status: done, job,
    results}`` body. Returned (not raised) — the Python success channel.

    NO-INVENT RULE (§2.8): the SOLE field is the raw ``done`` body. The wrapper synthesizes NO
    ``from_cache`` / ``cost`` fact — a cache-hit 200 and a 202-then-poll collapse into the same
    Result with no observable difference."""

    json: Any


@dataclass(frozen=True)
class SessionHandle:
    """The Tier-A ``begin-session`` handle (`clients.md` §2.3). ``token`` is the session cursor the
    next :meth:`Client.generate_and_wait` consumes; ``response`` is the raw envelope (plan ids /
    context / warnings).

    ``zone`` is the §23/Z4 isolation zone the session was begun IN, ECHOED back on the handle just
    as ``workspace`` is — so a caller resuming the session (`generate_and_wait`) carries the SAME
    zone it began with and can never silently cross zones. It defaults to the wire default
    ``"default"`` (mirrors ``client.DEFAULT_ZONE``; the value-types module imports nothing from the
    client, so the literal is repeated here with this note rather than creating an import cycle)."""

    workspace: Any
    token: Any
    response: Response
    zone: Any = "default"


@dataclass(frozen=True)
class CallbackEvent:
    """A parsed webhook WAKEUP (`clients.md` §2.7) — wakeup-only, never the result itself. The two
    event names are ``job.done`` / ``job.failed``; ``code`` / ``redrivable`` are present only on a
    failure wakeup. A woken client still FETCHES the finished output through the authenticated poll
    (:meth:`Client.fetch_after_callback`).

    ``zone`` is the §23/Z4 isolation zone the job ran in, read off the wakeup's ``job`` block next
    to ``workspace`` (the callback delivery names it there). It lets the woken client fetch in the
    SAME zone the job ran in without guessing; ``None`` when a (pre-zone) wakeup carried no zone, so
    :meth:`Client.fetch_after_callback` falls back to the default only then."""

    event: str
    workspace: Any
    key: Any
    target_ids: list[Any] = field(default_factory=list)
    code: Any = None
    redrivable: Any = None
    zone: Any = None


class ClientError(Exception):
    """Base for every condition the client DELIBERATELY raises (the Python outcome channel plus the
    malformed-body guard). A genuine transport failure (``urllib`` ``URLError`` / timeout, no
    ``.status``) is NOT a ClientError — it propagates as its native ``urllib`` error (§2.5)."""


class JobTimeout(ClientError):
    """The await deadline elapsed, or the wire returned a ``504`` timeout-class terminal
    (`clients.md` §2.4). Always re-drivable (re-submit the same idempotency key)."""

    def __init__(self, *, redrivable: bool = True) -> None:
        self.redrivable = redrivable
        super().__init__(f"job timed out (redrivable={redrivable})")


class JobFailed(ClientError):
    """A stored terminal failure (`clients.md` §2.4): a ``4xx/5xx {status: failed, code,
    redrivable, terminal}`` poll body.

    ``code`` is surfaced RAW (an OPEN string, §1.6): the client branches on ``redrivable`` /
    ``terminal`` and reports an unrecognized ``code`` rather than crashing on an exhaustive
    switch."""

    def __init__(self, *, code: Any, redrivable: Any, terminal: Any) -> None:
        self.code = code
        self.redrivable = redrivable
        self.terminal = terminal
        super().__init__(f"job failed: code={code!r} redrivable={redrivable}")


class RenderBlocked(ClientError):
    """A refused render (`clients.md` §2.4): a ``400 {error: render-blocked, block}`` body.
    ``block`` is the server's structured refusal record (surfaced raw)."""

    def __init__(self, *, block: Any) -> None:
        self.block = block
        super().__init__("render blocked")


class MalformedResponse(ClientError):
    """A ``200`` that is not a well-formed ``{status: done, results: [...]}`` body — a truncated /
    malformed ``done`` reply (`clients.md` §2.6). Raised as a DEFINED client error, never an
    uncaught JSON/attribute crash. ``response`` carries the offending :class:`Response`."""

    def __init__(self, message: str, *, response: Response | None = None) -> None:
        self.response = response
        super().__init__(message)
