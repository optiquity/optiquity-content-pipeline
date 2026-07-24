"""The webhook-callback SAFETY GUARD — the SSRF block + the operator allow-list.

Design authority: the DR-1 result-delivery reshape design record §2.3 "SECURITY"
(`docs/archive/design-record/dr-design-passes/dr1-webhook-poll/architect-01/report.md`) — the
allow-list + SSRF guard, validated at BOTH submit-time and delivery-time — plus CLAUDE.md's
posture that outbound egress is the higher-risk surface and must fail closed. This is the
security crux of the additive webhook callback: before the pipeline makes ANY outbound HTTP
request to a client-supplied URL, that URL must clear this guard.

**Pure logic — NO sockets in the hot path, NO HTTP, NO I/O of its own.** DNS resolution is the
ONE substrate touch, and it is INJECTED (`resolve`) so the whole attack battery drives every
branch with a fake resolver and never touches real DNS. The default resolver is the only place
`socket` is used, and it runs solely when a caller passes no `resolve`. The module imports
nothing from `pipeline` (no cycle risk) and keeps no state, so it is safe to call at submit-time
AND re-call at delivery-time (the DNS-rebinding re-check; wiring is W3b, not here).

**The two independent gates (defense in depth) — a URL must clear BOTH:**

1. **Operator ALLOW-LIST (`allowed_hosts`).** Callbacks are OPT-IN / off-by-default: an EMPTY
   allow-list rejects EVERYTHING (`callbacks-disabled`). This is deliberately stricter than the
   workspace allow-list's unset=serve-any default, because outbound egress is a higher-risk
   surface — the operator must consciously name the host(s) their orchestrator listens on. A
   non-empty allow-list matches EXACT HOST, case-insensitively (`host-not-allowed` otherwise).

2. **SSRF block (`is_global` + belt-and-suspenders).** Every IP the host resolves to must be a
   globally-routable UNICAST address. The allow-list is NOT sufficient on its own — an
   allow-listed host that (still, or via DNS rebinding) resolves to an internal address is
   REJECTED (`non-global-address`). A host given as a literal IP is classified the same way and
   never resolved. A MIX (any single non-global among the resolved set) is rejected. An empty or
   failed resolution is rejected (`unresolvable`) — fail closed.

**Why `is_global` ALONE is a HOLE (the load-bearing subtlety).** stdlib
`ipaddress.ip_address(ip).is_global` correctly returns False for loopback (127/8, ::1),
link-local incl. the 169.254.169.254 cloud-metadata address (169.254/16, fe80::/10), private
(10/8, 172.16/12, 192.168/16), unique-local (fc00::/7), unspecified (0.0.0.0, ::), and the
reserved v4 ranges (240/4, TEST-NET, CGNAT 100.64/10, benchmarking). BUT it returns **True** for
MULTICAST (224/4, ff00::/8) and for the NAT64 translation prefix (64:ff9b::/96) — both of which
the design's reject list names. So `is_global` is necessary but NOT sufficient.
`_ip_is_globally_safe` therefore ANDs `is_global` with `not is_multicast and not is_reserved`
(closing the multicast and NAT64 holes) plus redundant explicit negatives for loopback/link-local
(belt-and-suspenders: those are already False under `is_global`, but stating them documents the
intent and survives any future `is_global` change).

**No secret / topology leakage.** `CallbackPolicyError` names only the reason CLASS and a fixed
human rule — it NEVER interpolates the URL, the host, any credentials, or the resolved IP(s). An
SSRF guard whose error echoed "10.0.0.5 is private" would itself leak the internal topology it
exists to protect, so the detail strings are constant per class.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

__all__ = [
    "ALLOWED_SCHEMES",
    "CallbackPolicyError",
    "Resolver",
    "validate_callback_url",
]

#: The ONLY outbound schemes a callback may use. Everything else (file:, gopher:, ftp:, data:,
#: ssh:, and a missing/malformed scheme) is refused — a non-HTTP scheme is never a webhook.
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: A hostname → list of IP strings. INJECTED so the attack battery needs no real DNS; the default
#: (`_default_resolve`) is the ONLY place this module touches the network, and only when a caller
#: passes no `resolve`.
Resolver = Callable[[str], list[str]]


class CallbackPolicyError(ValueError):
    """A client-supplied callback URL was REJECTED by the safety guard (subclass of ValueError,
    mirroring `pipeline.workspace_name.WorkspaceNameError`). `reason` is the machine-readable
    class a door surfaces in a result's `context`; `detail` is the fixed human rule.

    SECURITY: neither field ever echoes the URL, host, credentials, or resolved IP(s) — the guard
    must not become a data-leak of the internal topology it protects. `reason` is one of:
    `malformed-url`, `callbacks-disabled` (empty allow-list / opt-in off), `bad-scheme`,
    `has-credentials`, `no-host`, `host-not-allowed`, `unresolvable`, `non-global-address`.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"callback-url-rejected: {detail}")
        self.reason = reason
        self.detail = detail


def _default_resolve(host: str) -> list[str]:
    """The default DNS resolver: every A/AAAA address the host resolves to, as IP strings. Used
    ONLY when a caller passes no `resolve` (tests always inject a fake). `getaddrinfo` raising —
    an unknown host (gaierror, an OSError subclass) OR an IDNA-hostile host (UnicodeError, a
    ValueError subclass) — is caught by the caller and turned into a fail-closed `unresolvable`
    rejection."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


def _ip_is_globally_safe(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True iff `ip` is a globally-routable UNICAST address safe to connect out to.

    `is_global` is necessary but NOT sufficient: it returns True for multicast (224/4, ff00::/8)
    and the NAT64 prefix (64:ff9b::/96), which the SSRF reject list names. `not is_multicast`
    closes multicast; `not is_reserved` closes NAT64. The remaining negatives are redundant with
    `is_global` today (loopback/link-local/private/unspecified are already non-global) but are
    stated explicitly as belt-and-suspenders so the guard survives any future `is_global` change.
    """
    return (
        ip.is_global
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_private
        and not ip.is_unspecified
    )


def _resolved_ips(host: str, resolve: Resolver) -> list[ipaddress._BaseAddress]:
    """Return the IPs to SSRF-check for `host`. A literal-IP host is classified DIRECTLY (never
    resolved — the injected resolver stays untouched for literals). A DNS name is resolved via the
    injected `resolve`; a resolver that raises `OSError`/`UnicodeError`, returns nothing, or
    returns an unparseable address is a fail-closed `unresolvable` rejection."""
    try:
        return [ipaddress.ip_address(host)]  # a literal IPv4/IPv6 host — no DNS needed
    except ValueError:
        pass  # not a literal — a DNS name; fall through to resolution
    try:
        raw = resolve(host)
    except (OSError, UnicodeError) as exc:  # unresolvable — fail closed (see below)
        # gaierror (unknown host) is an OSError subclass; an IDNA-hostile host (a DNS label >63
        # chars or a name >255 total) makes `getaddrinfo` raise UnicodeError — a ValueError
        # subclass, NOT an OSError. Catching BOTH keeps this helper (and thus
        # `validate_callback_url`) raising ONLY `CallbackPolicyError`, never a bare UnicodeError
        # that would break the module's contract (and, at delivery-time, escape the runner's
        # caught set).
        raise CallbackPolicyError(
            "unresolvable",
            "callback host could not be resolved — a callback target must resolve to at least "
            "one globally-routable address",
        ) from exc
    if not raw:
        raise CallbackPolicyError(
            "unresolvable",
            "callback host resolved to no addresses — a callback target must resolve to at least "
            "one globally-routable address",
        )
    ips: list[ipaddress._BaseAddress] = []
    for item in raw:
        try:
            ips.append(ipaddress.ip_address(item))
        except ValueError as exc:  # a resolver returning a non-address is broken input
            raise CallbackPolicyError(
                "unresolvable",
                "callback host resolved to a value that is not an IP address",
            ) from exc
    return ips


def validate_callback_url(
    url: object,
    *,
    allowed_hosts: frozenset[str],
    resolve: Resolver = _default_resolve,
) -> None:
    """Raise `CallbackPolicyError` unless `url` is a safe outbound callback target; return None
    (side-effect-free) when it clears every gate. Pure and fast — safe to call at submit-time AND
    re-call at delivery-time (the DNS-rebinding re-check). `resolve` maps a hostname → list of IP
    strings and is injected so tests never touch real DNS.

    The gates, IN ORDER (each rejection names only its reason CLASS — never the URL/host/creds/IP):
      1. `url` is a string                          -> `malformed-url`
      2. `allowed_hosts` is empty (opt-in / OFF)    -> `callbacks-disabled` (rejects EVERYTHING)
      3. URL parses (incl. a castable port)         -> `malformed-url`
      4. scheme in {http, https}                    -> `bad-scheme`
      5. no `user[:pass]@` credentials in the URL   -> `has-credentials`
      6. a host is present                          -> `no-host`
      7. host (case-insensitive) in `allowed_hosts` -> `host-not-allowed`
      8. EVERY resolved IP is globally-safe         -> `unresolvable` / `non-global-address`
    """
    # 1. A non-string (or None) is never a URL — refuse before any parsing.
    if not isinstance(url, str):
        raise CallbackPolicyError(
            "malformed-url",
            "callback url must be a string",
        )

    # 2. OPT-IN / fail-closed: with no operator-approved hosts, callbacks are DISABLED — reject
    #    everything before doing any parsing or resolution work.
    if not allowed_hosts:
        raise CallbackPolicyError(
            "callbacks-disabled",
            "outbound callbacks are disabled — the operator has approved no callback hosts "
            "(the allow-list is empty; callbacks are opt-in / off by default)",
        )

    # 3. Parse. `urlsplit` raises on a few malformed inputs (e.g. an unclosed IPv6 bracket), and
    #    accessing `.port` raises on a non-integer port — both are malformed URLs.
    try:
        parts = urlsplit(url)
        _ = parts.port  # force the port cast; a garbage port raises ValueError here
    except ValueError as exc:
        raise CallbackPolicyError(
            "malformed-url",
            "callback url could not be parsed",
        ) from exc

    # 4. Scheme allow-list. `urlsplit` lower-cases the scheme; a schemeless/relative URL has ''.
    if parts.scheme not in ALLOWED_SCHEMES:
        raise CallbackPolicyError(
            "bad-scheme",
            "callback url scheme must be http or https (no file/gopher/ftp/data/ssh/... and no "
            "missing scheme)",
        )

    # 5. No embedded credentials — a `user[:pass]@host` in an outbound URL is refused outright
    #    (and never echoed).
    if parts.username is not None or parts.password is not None:
        raise CallbackPolicyError(
            "has-credentials",
            "callback url must not embed credentials (no 'user:pass@host')",
        )

    # 6. A host must be present. `urlsplit` lower-cases the hostname and strips IPv6 brackets.
    host = parts.hostname
    if not host:
        raise CallbackPolicyError(
            "no-host",
            "callback url must name a host",
        )

    # 7. Operator allow-list — EXACT HOST, case-insensitive. Normalize both sides (the hostname is
    #    already lower-cased by urlsplit; lower-case the operator entries defensively).
    if host not in {entry.lower() for entry in allowed_hosts}:
        raise CallbackPolicyError(
            "host-not-allowed",
            "callback host is not in the operator's approved allow-list",
        )

    # 8. SSRF block — EVERY resolved (or literal) IP must be globally-safe. The allow-list alone is
    #    NOT enough: an approved host resolving to an internal address (or a literal internal IP) is
    #    refused here; a MIX rejects on its first non-global member.
    for ip in _resolved_ips(host, resolve):
        if not _ip_is_globally_safe(ip):
            raise CallbackPolicyError(
                "non-global-address",
                "callback host resolves to a non-global address — loopback, link-local (incl. "
                "cloud-metadata), private, unique-local, unspecified, multicast, and reserved "
                "targets are refused (SSRF block)",
            )
