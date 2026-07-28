"""The stdlib reference client for the optiquity content pipeline (provenance: framework).

``from pipeline.client import Client`` gives the canonical client surface of
`docs/guide/clients.md` (Part 2), implemented over ``urllib`` + ``json`` with ZERO new
dependency. The raw layer (`invoke`/`poll`/`list`/`get`), the ergonomic async layer
(`begin_session`/`generate_and_wait`/`render_and_wait`), the poll state machine, the typed
outcomes (`Result` returned; `JobTimeout`/`JobFailed`/`RenderBlocked` raised), and the webhook
receipt (`parse_callback` + `Client.fetch_after_callback`) all live here.

Config is env-only, identical across languages (§2.1): ``OPTIQUITY_SHIM_URL`` +
``OPTIQUITY_SHIM_SECRET`` (see :meth:`Client.from_env`).
"""

from __future__ import annotations

from pipeline.client.client import Client, parse_callback
from pipeline.client.outcomes import (
    CallbackEvent,
    ClientError,
    JobFailed,
    JobTimeout,
    MalformedResponse,
    RenderBlocked,
    Response,
    Result,
    SessionHandle,
)

__all__ = [
    "CallbackEvent",
    "Client",
    "ClientError",
    "JobFailed",
    "JobTimeout",
    "MalformedResponse",
    "RenderBlocked",
    "Response",
    "Result",
    "SessionHandle",
    "parse_callback",
]
