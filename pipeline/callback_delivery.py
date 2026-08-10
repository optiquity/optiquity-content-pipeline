"""The webhook-callback DELIVERY — the outbound completion WAKEUP ping (DR-1 W3c).

Design authority: the DR-1 result-delivery reshape design record §2 (the additive webhook callback:
who delivers, the wakeup-only payload, re-validate-at-delivery, no redirects, bounded retry) and
§2.3/§5 (outbound egress is the load-bearing security surface). This is the LAST webhook piece: the
detached runner, after a job settles, POSTs a small self-describing notification so a client (e.g.
n8n's Wait "On Webhook Call") knows to FETCH the result through the same authenticated poll door.

**A WAKEUP, never the result (ratified, D-2).** The payload carries `event` + `job` identity + a
`poll` pointer (and, on failure, `code`/`redrivable`) — NO artifact content. The client is woken and
then fetches via poll/`fetch-by-id`. This keeps ONE result-delivery contract, pushes no possibly-
large/secret client data to an outbound URL, and minimizes the egress surface.

**Injectable, testable in isolation (mirrors `callback_policy`'s purity).** DNS resolution, the HTTP
opener, and `sleep` are all INJECTED, so the whole battery — delivery, the DNS-rebinding re-check,
the no-redirect refusal, the bounded retry, the timeout — drives every branch with fakes and NEVER
touches real DNS or the real network. The default resolver/opener are the ONLY places the network is
touched, and only when a caller passes none.

**Security, load-bearing (the reason the webhook was originally deferred):**

1. **RE-VALIDATE at delivery (DNS-rebinding / TOCTOU defense).** The submit-time allow-list + SSRF
   check is NOT enough on its own: a host that was globally-routable at submit can be re-pointed to
   an internal/metadata IP by delivery time. So `deliver_callback` RE-CALLS `validate_callback_url`
   (never re-implements it) with a LIVE resolver against the SAME frozen allow-list snapshot the
   submit used — the host is RE-RESOLVED NOW; a now-internal target is REFUSED (status
   `rejected-at-delivery`) and nothing is POSTed.
2. **NO redirects.** A 3xx could bounce the POST to an internal address, bypassing the SSRF re-check
   (which validated only the ORIGINAL host). The production opener REPLACES stdlib's redirect
   follower with one that RAISES on any 3xx, so a redirect is a delivery FAILURE, never a follow.
3. **Per-request socket TIMEOUT.** Every POST carries a timeout, so a slow / black-hole endpoint
   never HANGS the detached runner.

**Never crashes the runner (the poll is always the floor).** Every failure — network error, non-2xx,
a refused redirect, a timeout, a rebind rejection — is caught and turned into a recorded
`callback_status`; the job's output already materialized and the always-available poll is the
fallback. `callback_status` is §22.7-class LOSSY bookkeeping — no schema/ir version bump.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

from pipeline.api.jobrunner import RE_DRIVABLE_CODE
from pipeline.api.results import CODE_RATE_LIMIT_BACKPRESSURE
from pipeline.callback_policy import (
    CallbackPolicyError,
    Resolver,
    _default_resolve,
    validate_callback_url,
)
from pipeline.canonical import canonical_json_str
from pipeline.opdefaults import (
    CALLBACK_BACKOFF_SECONDS,
    CALLBACK_MAX_ATTEMPTS,
    CALLBACK_TIMEOUT_SECONDS,
)

if TYPE_CHECKING:  # spec/outcome are jobrunner value objects — annotate-only, no runtime need.
    from collections.abc import Callable

    from pipeline.api.jobrunner import JobSpec, RunOutcome

__all__ = [
    "CALLBACK_STATUS_DELIVERED",
    "CALLBACK_STATUS_FAILED",
    "CALLBACK_STATUS_REJECTED_AT_DELIVERY",
    "CALLBACK_STATUS_SKIPPED",
    "EVENT_DONE",
    "EVENT_FAILED",
    "build_callback_payload",
    "build_no_redirect_opener",
    "deliver_callback",
]

#: The two wakeup EVENT names (design §2.1). `job.done` for a clean/deterministic-skip outcome;
#: `job.failed` for a returned/raised terminal (carries `code`/`redrivable`).
EVENT_DONE = "job.done"
EVENT_FAILED = "job.failed"

#: The recorded `callback_status` values (§22.7-class lossy bookkeeping):
CALLBACK_STATUS_DELIVERED = "delivered"  #: a 2xx landed
CALLBACK_STATUS_FAILED = "failed"  #: MAX_ATTEMPTS exhausted (network/non-2xx/redirect/timeout)
CALLBACK_STATUS_REJECTED_AT_DELIVERY = "rejected-at-delivery"  #: the delivery-time re-check refused
CALLBACK_STATUS_SKIPPED = "skipped"  #: no callback_url (defensive — the caller already guards)

#: `RunOutcome.disposition` values that map to a `job.done` wakeup (design §2.2). Everything else
#: (`terminal-returned`/`terminal-raised`) is a `job.failed`.
_DONE_DISPOSITIONS = frozenset({"clean", "skip-deterministic"})

#: The transport `timeout` code (a `TransportCode` Literal, no named constant — mirrors the literal
#: `http_shim._terminal_status_for` uses). Kept beside the imported SSOT codes below.
_TRANSPORT_TIMEOUT_CODE = "timeout"

#: Terminal codes a client CAN re-drive by re-submitting the same key — the wakeup's `redrivable`
#: flag. Sourced from the SSOTs (jobrunner's synthesized re-drivable code + the transport
#: backpressure code) so it cannot drift; a `tests/test_callback_delivery.py` drift-guard cross-
#: checks this against `http_shim._terminal_status_for` (which maps these to a re-drivable 504/429).
_REDRIVABLE_TERMINAL_CODES = frozenset(
    {RE_DRIVABLE_CODE, _TRANSPORT_TIMEOUT_CODE, CODE_RATE_LIMIT_BACKPRESSURE}
)

#: The poll POINTER embedded in every wakeup — how the woken client fetches the result. Mirrors
#: `http_shim._accepted_body`'s `poll` block (design §2.1); a drift-guard test pins the equality so
#: a change to the poll contract there is caught here without a production import of the shim.
#: `user` (the §23 isolation prefix) is advertised alongside `workspace` because the poll HANDLER
#: requires it; the woken client sources `user` from its OWN identity (like the auth secret), not
#: from the wakeup's `job` block — so the two advertisements stay identical.
_POLL_PATH = "/poll"
_POLL_NEEDS = ("workspace", "user", "key", "target_ids")


def _code_is_redrivable(code: object) -> bool:
    """True iff a client should re-submit the same key on this terminal `code` (the wakeup's
    `redrivable`). A timeout/backpressure failure is re-drivable; a wiring/env `runner-failed`
    or an envelope 4xx (unknown-verb / invalid-token / isolation-violation) is NOT."""
    return isinstance(code, str) and code in _REDRIVABLE_TERMINAL_CODES


def build_callback_payload(spec: JobSpec, outcome: RunOutcome) -> dict[str, Any]:
    """The WAKEUP-ONLY JSON body (design §2.1) — NO artifact content, ever. Carries the `event`, the
    `job` identity (key/workspace/zone/predictable target-ids — §23/Z4: the zone rides next to the
    workspace so the woken client fetches in the SAME zone), and the `poll` pointer the woken client
    uses to FETCH the result; on failure it adds the terminal `code` + whether it is `redrivable`.
    Pure — a unit test asserts the exact shape with no network."""
    done = outcome.disposition in _DONE_DISPOSITIONS
    payload: dict[str, Any] = {
        "event": EVENT_DONE if done else EVENT_FAILED,
        "job": {
            "key": spec.key,
            "workspace": spec.workspace,
            # §23/Z4: the wakeup NAMES the zone next to `workspace` (they are the isolation pair),
            # so a woken client fetches in the SAME zone the job ran in. `zone` is a MANDATORY
            # JobSpec field (jobrunner), so this is always a concrete value, never None.
            "zone": spec.zone,
            "target_ids": list(spec.target_ids),
        },
        "poll": {"path": _POLL_PATH, "method": "POST", "needs": list(_POLL_NEEDS)},
    }
    if not done:
        payload["code"] = outcome.code
        payload["redrivable"] = _code_is_redrivable(outcome.code)
    return payload


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that REFUSES every 3xx (SSRF no-follow guard). A redirect could bounce the
    POST to an internal address, bypassing the delivery-time SSRF re-check (which validated only the
    ORIGINAL host), so a 3xx is NEVER followed. It raises `HTTPError` instead of returning a new
    request; `deliver_callback` treats that as a non-2xx delivery FAILURE, never a follow to
    `newurl`."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001, ANN201
        raise urllib.error.HTTPError(
            req.full_url,
            code,
            f"callback refused a {code} redirect (no-follow SSRF guard)",
            headers,
            fp,
        )


def build_no_redirect_opener() -> urllib.request.OpenerDirector:
    """The production opener: a stdlib `OpenerDirector` whose default redirect follower is REPLACED
    by `_NoRedirectHandler` (a 3xx raises, never followed). `build_opener` dedupes handlers
    by type, so passing a `HTTPRedirectHandler` SUBCLASS evicts the built-in follower. Injectable —
    tests pass a fake opener; this is what production uses when none is injected."""
    return urllib.request.build_opener(_NoRedirectHandler)


def _status_of(response: Any) -> int | None:
    """The HTTP status of an opener response — `.status` (http.client) or `.getcode()`; None if the
    object exposes neither (a defensive fake)."""
    status = getattr(response, "status", None)
    if isinstance(status, int):
        return status
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        code = getcode()
        if isinstance(code, int):
            return code
    return None


def _safe_close(response: Any) -> None:
    """Close a response if closeable; a close failure is irrelevant to delivery, so swallow it."""
    close = getattr(response, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _post_once(opener: Any, request: urllib.request.Request) -> bool:
    """ONE POST attempt. Returns True iff a 2xx landed (delivered). Any failure — a network error, a
    non-2xx (incl. a REFUSED 3xx redirect, which the no-redirect opener raises), a socket timeout —
    is swallowed and returns False so the caller retries / gives up. NEVER raises: the detached
    runner must not crash on a bad endpoint. Each POST carries the per-request socket TIMEOUT."""
    try:
        response = opener.open(request, timeout=CALLBACK_TIMEOUT_SECONDS)
    except Exception:
        # urllib URLError/HTTPError (incl. the refused-3xx raise), socket.timeout/OSError, or a fake
        # opener's raise — every one is a non-delivery this attempt; the caller retries or gives up.
        return False
    try:
        status = _status_of(response)
    finally:
        _safe_close(response)
    return status is not None and 200 <= status < 300


def deliver_callback(
    spec: JobSpec,
    outcome: RunOutcome,
    *,
    allowed_hosts: frozenset[str],
    resolve: Resolver = _default_resolve,
    opener: Any = None,
    sleep: Callable[[float], Any] = time.sleep,
) -> str:
    """Deliver the completion WAKEUP callback for a settled job and RETURN the recorded
    `callback_status`. NEVER raises: every failure is caught and turned into a status (the job's
    output already materialized; the poll is the floor).

    Order:
      1. RE-VALIDATE `spec.callback_url` at delivery via `validate_callback_url` (the DNS-rebinding
         re-check — the host is RE-RESOLVED NOW against the frozen `allowed_hosts` snapshot). A
         rejection → `rejected-at-delivery`, NOTHING is POSTed.
      2. Build the WAKEUP payload (no result content) and POST it as JSON with a NO-REDIRECT opener
         and a per-request TIMEOUT.
      3. Bounded retry: `CALLBACK_MAX_ATTEMPTS` attempts with exponential backoff between tries
         (injected `sleep`), a 2xx → `delivered`, exhaustion → `failed`.

    `resolve`/`opener`/`sleep` are injected for hermetic tests (no real DNS/network, instant
    backoff); production uses the stdlib defaults."""
    callback_url = spec.callback_url
    if not callback_url:
        # Defensive: the runner caller already guards on callback_url, so this is unreachable in
        # production — but a direct caller with no URL posts nothing and records `skipped`.
        return CALLBACK_STATUS_SKIPPED

    # (1) The DNS-rebinding / TOCTOU defense: RE-RESOLVE + RE-CHECK now, against the SAME frozen
    #     allow-list the submit used. Re-calls the W3a guard; never re-implements the guard's
    #     logic. A host now resolving to an internal/metadata IP (or otherwise failing the gate) is
    #     REFUSED here — the opener is never touched.
    try:
        validate_callback_url(callback_url, allowed_hosts=allowed_hosts, resolve=resolve)
    except CallbackPolicyError:
        return CALLBACK_STATUS_REJECTED_AT_DELIVERY

    # (2) Build the wakeup-only body + the POST request (JSON, no redirects, per-request timeout).
    body = canonical_json_str(build_callback_payload(spec, outcome)).encode("utf-8")
    request = urllib.request.Request(
        callback_url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    op = opener if opener is not None else build_no_redirect_opener()

    # (3) Bounded retry with exponential backoff (BASE * 4**attempt: 1 s, 4 s, 16 s …). A 2xx →
    #     delivered; anything else retries, then we GIVE UP → failed (the poll floor recovers it).
    for attempt in range(CALLBACK_MAX_ATTEMPTS):
        if _post_once(op, request):
            return CALLBACK_STATUS_DELIVERED
        if attempt < CALLBACK_MAX_ATTEMPTS - 1:
            sleep(CALLBACK_BACKOFF_SECONDS * (4**attempt))
    return CALLBACK_STATUS_FAILED
