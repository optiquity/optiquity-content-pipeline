"""The webhook-callback SAFETY GUARD attack battery — the SSRF block + the allow-list.

Design authority: the DR-1 result-delivery reshape design record §2.3 "SECURITY". This is the
security crux of the additive webhook callback (DR-1 W3a), so the battery is exhaustive: every
SSRF category and every allow-list / scheme / credential / parse failure gets its OWN assertion
that names the reason CLASS. No test touches real DNS — a fake resolver is injected everywhere a
DNS name is used; literal-IP tests never call it at all.

`validate_callback_url` RETURNS None on accept and RAISES `CallbackPolicyError` on any rejection.
All fixtures are generic (`allowed.host`, RFC-5737 / documentation IPs, well-known literals); no
instance content.
"""

from __future__ import annotations

import ipaddress

import pytest

from pipeline.callback_policy import (
    ALLOWED_SCHEMES,
    CallbackPolicyError,
    _ip_is_globally_safe,
    validate_callback_url,
)

#: A single operator-approved host used across the accept + SSRF tests.
ALLOWED = frozenset({"allowed.host"})

#: A genuinely global unicast IPv4 (documentation-corpus address used the same way elsewhere).
GLOBAL_V4 = "93.184.216.34"
#: A genuinely global unicast IPv6.
GLOBAL_V6 = "2606:2800:220:1:248:1893:25c8:1946"


def _resolve_to(*ips: str):
    """Build a fake resolver returning a FIXED IP list for any host — the DNS seam, no real DNS."""

    def _resolve(host: str) -> list[str]:
        return list(ips)

    return _resolve


def _resolver_must_not_be_called(host: str) -> list[str]:
    """A resolver that FAILS the test if a literal-IP path ever calls it (literals skip DNS)."""
    raise AssertionError(f"resolver must not be called for a literal-IP host (got {host!r})")


# ---------------------------------------------------------------------------
# ACCEPT — the one happy path (and its variants).
# ---------------------------------------------------------------------------


class TestAccept:
    def test_allowed_host_resolving_to_a_single_global_ipv4_is_ok(self):
        # The canonical accept: an allow-listed host that resolves to ONE global IPv4 → None.
        assert (
            validate_callback_url(
                "https://allowed.host/webhook/exec-123",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
            is None
        )

    def test_http_scheme_is_also_accepted(self):
        assert (
            validate_callback_url(
                "http://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
            is None
        )

    def test_allowed_host_resolving_to_a_global_ipv6_is_ok(self):
        assert (
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V6),
            )
            is None
        )

    def test_host_case_insensitive_match_still_accepts(self):
        # The URL host is cased differently from the allow-list entry — exact-host match is
        # case-insensitive, so it still clears the allow-list (then the global IP clears SSRF).
        assert (
            validate_callback_url(
                "https://ALLOWED.HOST/hook",
                allowed_hosts=frozenset({"allowed.host"}),
                resolve=_resolve_to(GLOBAL_V4),
            )
            is None
        )

    def test_allow_list_entry_cased_differently_still_matches(self):
        # The other direction: the OPERATOR entry is upper-cased; the lower-cased URL host matches.
        assert (
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=frozenset({"Allowed.Host"}),
                resolve=_resolve_to(GLOBAL_V4),
            )
            is None
        )

    def test_all_resolved_ips_global_is_ok(self):
        # A host resolving to MULTIPLE addresses, all global, clears the SSRF block.
        assert (
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4, GLOBAL_V6),
            )
            is None
        )


# ---------------------------------------------------------------------------
# ALLOW-LIST — opt-in / off-by-default (the fail-closed gate).
# ---------------------------------------------------------------------------


class TestAllowList:
    def test_empty_allow_list_rejects_everything(self):
        # OPT-IN default: no approved hosts ⇒ callbacks disabled ⇒ reject even a perfect URL.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=frozenset(),
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "callbacks-disabled"

    def test_empty_allow_list_rejects_before_resolution(self):
        # The empty-allow-list gate short-circuits BEFORE any DNS work — inject a resolver that
        # would explode if reached.
        def _boom(host: str) -> list[str]:
            raise AssertionError("must not resolve when callbacks are disabled")

        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook", allowed_hosts=frozenset(), resolve=_boom
            )
        assert exc.value.reason == "callbacks-disabled"

    def test_non_allow_listed_host_is_rejected(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://evil.example/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "host-not-allowed"

    def test_allow_list_is_exact_host_not_suffix(self):
        # A subdomain of an allowed host is NOT allow-listed (exact-host, not suffix match).
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://sub.allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "host-not-allowed"


# ---------------------------------------------------------------------------
# SCHEME — http/https only.
# ---------------------------------------------------------------------------


class TestScheme:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "gopher://allowed.host/_",
            "ftp://allowed.host/f",
            "data:text/plain,hello",
            "ssh://allowed.host",
            "jar:https://allowed.host!/",
            "allowed.host/relative-no-scheme",
            "//allowed.host/scheme-relative",
        ],
    )
    def test_non_http_scheme_is_rejected(self, url):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                url, allowed_hosts=ALLOWED, resolve=_resolve_to(GLOBAL_V4)
            )
        # A scheme-relative / schemeless URL has no host either; both map to a structural reject
        # (bad-scheme fires first in gate order for a present-but-wrong or empty scheme).
        assert exc.value.reason == "bad-scheme"

    def test_allowed_schemes_are_exactly_http_https(self):
        assert ALLOWED_SCHEMES == frozenset({"http", "https"})


# ---------------------------------------------------------------------------
# CREDENTIALS — no user[:pass]@host.
# ---------------------------------------------------------------------------


class TestCredentials:
    def test_user_and_password_in_url_is_rejected(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://user:pass@allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "has-credentials"

    def test_username_only_in_url_is_rejected(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://user@allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "has-credentials"

    def test_credentials_reason_does_not_echo_the_secret(self):
        # The guard must never surface the embedded credential material.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://alice:s3cr3t@allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert "s3cr3t" not in str(exc.value)
        assert "alice" not in str(exc.value)


# ---------------------------------------------------------------------------
# SSRF BLOCK — every resolved IP must be globally-safe.
# ---------------------------------------------------------------------------


class TestSsrfLoopback:
    @pytest.mark.parametrize("ip", ["127.0.0.1", "127.5.5.5", "::1"])
    def test_loopback_is_rejected(self, ip):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"

    def test_localhost_name_resolving_to_loopback_is_rejected(self):
        # `localhost` is not special to the guard — its RESOLUTION (127.0.0.1) is what fails SSRF.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("127.0.0.1"),
            )
        assert exc.value.reason == "non-global-address"


class TestSsrfLinkLocalAndMetadata:
    def test_cloud_metadata_169_254_169_254_is_rejected(self):
        # THE canonical SSRF target — the cloud instance-metadata endpoint.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "http://allowed.host/latest/meta-data/",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("169.254.169.254"),
            )
        assert exc.value.reason == "non-global-address"

    @pytest.mark.parametrize("ip", ["169.254.1.1", "fe80::1"])
    def test_other_link_local_is_rejected(self, ip):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"


class TestSsrfPrivate:
    @pytest.mark.parametrize("ip", ["10.0.0.5", "172.16.0.1", "192.168.1.1"])
    def test_rfc1918_private_is_rejected(self, ip):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"

    @pytest.mark.parametrize("ip", ["fc00::1", "fd00::1"])
    def test_ipv6_unique_local_is_rejected(self, ip):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"


class TestSsrfUnspecifiedMulticastReserved:
    @pytest.mark.parametrize("ip", ["0.0.0.0", "::"])
    def test_unspecified_is_rejected(self, ip):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"

    @pytest.mark.parametrize("ip", ["224.0.0.1", "239.255.255.250", "ff00::1", "ff02::1"])
    def test_multicast_is_rejected_even_though_is_global_is_true(self, ip):
        # THE is_global HOLE: ipaddress marks multicast is_global=True. The guard's extra
        # `not is_multicast` clause is what rejects it — proving the guard is not is_global-only.
        assert ipaddress.ip_address(ip).is_global is True  # documents the hole
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"

    @pytest.mark.parametrize("ip", ["240.0.0.1", "255.255.255.255", "64:ff9b::1"])
    def test_reserved_ranges_are_rejected(self, ip):
        # 64:ff9b::/96 (NAT64) is the second is_global hole — closed by `not is_reserved`.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(ip),
            )
        assert exc.value.reason == "non-global-address"


class TestSsrfAllowListIsNotEnough:
    def test_allowed_host_resolving_to_private_is_still_rejected(self):
        # The load-bearing defense-in-depth assertion: the host IS allow-listed, but the SSRF
        # block still fires because it resolves to a private address (DNS-rebinding shape).
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("10.0.0.5"),
            )
        assert exc.value.reason == "non-global-address"

    def test_mix_of_global_and_loopback_is_rejected(self):
        # A host resolving to a MIX (one global + one loopback) is rejected defensively — a single
        # non-global member fails the whole set.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4, "127.0.0.1"),
            )
        assert exc.value.reason == "non-global-address"

    def test_mix_order_independent_global_last(self):
        # Order must not matter: loopback first, global second — still rejected.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("127.0.0.1", GLOBAL_V4),
            )
        assert exc.value.reason == "non-global-address"


class TestSsrfLiteralIpHosts:
    @pytest.mark.parametrize(
        "url,ip",
        [
            ("https://127.0.0.1/hook", "127.0.0.1"),
            ("https://10.0.0.5/hook", "10.0.0.5"),
            ("https://169.254.169.254/hook", "169.254.169.254"),
            ("https://[::1]/hook", "::1"),
            ("https://[fc00::1]/hook", "fc00::1"),
            # IPv4-MAPPED IPv6 literals — the classic SSRF bypass in literal form. urlsplit strips
            # the brackets, so `::ffff:127.0.0.1` / `::ffff:169.254.169.254` (cloud-metadata) take
            # the literal path (resolver NEVER called) and are rejected on the embedded v4.
            ("https://[::ffff:127.0.0.1]/hook", "::ffff:127.0.0.1"),
            ("https://[::ffff:169.254.169.254]/hook", "::ffff:169.254.169.254"),
        ],
    )
    def test_literal_private_ip_host_is_rejected_and_never_resolved(self, url, ip):
        # A literal-IP host is classified DIRECTLY (the injected resolver must NOT be called). The
        # allow-list here contains the literal IP string — proving allow-listing a literal cannot
        # bypass the SSRF block.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                url,
                allowed_hosts=frozenset({ip}),
                resolve=_resolver_must_not_be_called,
            )
        assert exc.value.reason == "non-global-address"

    def test_literal_global_ip_host_is_accepted_without_resolving(self):
        # A literal GLOBAL IP host, allow-listed, is accepted — and the resolver is never called.
        assert (
            validate_callback_url(
                f"https://{GLOBAL_V4}/hook",
                allowed_hosts=frozenset({GLOBAL_V4}),
                resolve=_resolver_must_not_be_called,
            )
            is None
        )


class TestIpv4MappedIpv6Bypass:
    """IPv4-mapped IPv6 (`::ffff:a.b.c.d`) — the single most-classic SSRF bypass. The guard's
    correctness for it rests on stdlib `ipaddress` unwrapping the embedded v4 (the CVE-2024-4032
    fix). These lock the highest-risk regression path: a stdlib regression / interpreter downgrade
    that reopened the bypass would turn these RED instead of leaving the suite silently green."""

    @pytest.mark.parametrize(
        "mapped",
        ["::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1", "::ffff:192.168.1.1"],
    )
    def test_resolved_mapped_private_is_rejected(self, mapped):
        # RESOLVED path: an allow-listed host that resolves to a mapped-private/-metadata address
        # is rejected by the SSRF block (the allow-list alone is not enough).
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(mapped),
            )
        assert exc.value.reason == "non-global-address"

    def test_resolved_mapped_public_is_accepted(self):
        # NOT TAUTOLOGICAL: a mapped-PUBLIC address on the resolved path must be ACCEPTED, so a
        # change that blanket-rejects every mapped address would flip this test RED.
        assert (
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("::ffff:8.8.8.8"),
            )
            is None
        )

    def test_predicate_mapped_public_stays_safe(self):
        # The predicate-level positive lock (guards against a future blanket over-block).
        assert _ip_is_globally_safe(ipaddress.ip_address("::ffff:8.8.8.8")) is True


class TestResolutionFailures:
    def test_empty_resolution_is_rejected(self):
        # Fail closed: a host resolving to NO addresses is not a valid target.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(),
            )
        assert exc.value.reason == "unresolvable"

    def test_resolver_raising_oserror_is_rejected(self):
        # A DNS failure (gaierror is an OSError subclass) fails closed as `unresolvable`.
        def _gaierror(host: str) -> list[str]:
            raise OSError("Name or service not known")

        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook", allowed_hosts=ALLOWED, resolve=_gaierror
            )
        assert exc.value.reason == "unresolvable"

    def test_resolver_returning_a_non_ip_is_rejected(self):
        # A broken resolver returning garbage is refused, not crashed-through.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("not-an-ip"),
            )
        assert exc.value.reason == "unresolvable"


# ---------------------------------------------------------------------------
# MALFORMED — empty / garbage / non-string / bad port / no host.
# ---------------------------------------------------------------------------


class TestMalformed:
    @pytest.mark.parametrize("url", ["", "   ", "not a url at all"])
    def test_empty_or_garbage_url_is_rejected(self, url):
        # Empty / whitespace / free-text has no scheme → refused (bad-scheme is the structural
        # reject for a schemeless string; the point is it never reaches resolution).
        with pytest.raises(CallbackPolicyError):
            validate_callback_url(
                url, allowed_hosts=ALLOWED, resolve=_resolve_to(GLOBAL_V4)
            )

    def test_non_string_url_is_rejected(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                None, allowed_hosts=ALLOWED, resolve=_resolve_to(GLOBAL_V4)
            )
        assert exc.value.reason == "malformed-url"

    def test_bytes_url_is_rejected(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                b"https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "malformed-url"

    def test_garbage_port_is_rejected(self):
        # A non-integer port makes urlsplit's `.port` raise → malformed-url.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host:notaport/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "malformed-url"

    def test_http_url_with_no_host_is_rejected(self):
        # A valid scheme but no authority/host (e.g. `https:///path`) → no-host.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https:///just/a/path",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert exc.value.reason == "no-host"


# ---------------------------------------------------------------------------
# NO-LEAK — the guard never surfaces the URL / host / resolved IP in its message.
# ---------------------------------------------------------------------------


class TestNoTopologyLeak:
    def test_ssrf_rejection_never_echoes_the_internal_ip(self):
        # The rejection message must not leak the internal address the host resolved to.
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://allowed.host/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to("10.11.12.13"),
            )
        assert "10.11.12.13" not in str(exc.value)
        assert exc.value.reason == "non-global-address"

    def test_host_not_allowed_never_echoes_the_host(self):
        with pytest.raises(CallbackPolicyError) as exc:
            validate_callback_url(
                "https://secret-internal-name.example/hook",
                allowed_hosts=ALLOWED,
                resolve=_resolve_to(GLOBAL_V4),
            )
        assert "secret-internal-name" not in str(exc.value)


# ---------------------------------------------------------------------------
# UNIT — the SSRF predicate itself (documents the is_global holes it closes).
# ---------------------------------------------------------------------------


class TestIpPredicate:
    @pytest.mark.parametrize(
        "ip",
        [
            GLOBAL_V4, GLOBAL_V6, "8.8.8.8", "1.1.1.1",
            # POSITIVE LOCK: an IPv4-mapped IPv6 of a PUBLIC address must stay SAFE, so a future
            # change that blanket-drops ALL mapped addresses is caught here too (not tautological
            # with the reject corpus below, which asserts mapped-PRIVATE is unsafe).
            "::ffff:8.8.8.8",
        ],
    )
    def test_genuine_global_unicast_is_safe(self, ip):
        assert _ip_is_globally_safe(ipaddress.ip_address(ip)) is True

    @pytest.mark.parametrize(
        "ip",
        [
            "127.0.0.1", "::1", "169.254.169.254", "169.254.1.1", "fe80::1",
            "10.0.0.5", "172.16.0.1", "192.168.1.1", "fc00::1", "fd00::1",
            "0.0.0.0", "::", "224.0.0.1", "ff00::1", "240.0.0.1", "64:ff9b::1",
            "100.64.0.1", "192.0.2.1", "198.18.0.1",
            # IPv4-MAPPED IPv6 — the single most-classic SSRF bypass. `ipaddress` unwraps the
            # embedded v4 (the CVE-2024-4032 fix, present in this interpreter) so `is_global` is
            # False for a mapped-private address; these lock that the predicate rejects them.
            "::ffff:127.0.0.1", "::ffff:169.254.169.254", "::ffff:10.0.0.1", "::ffff:192.168.1.1",
        ],
    )
    def test_non_global_is_unsafe(self, ip):
        assert _ip_is_globally_safe(ipaddress.ip_address(ip)) is False

    @pytest.mark.parametrize("ip", ["224.0.0.1", "ff00::1", "64:ff9b::1"])
    def test_the_is_global_holes_are_closed(self, ip):
        # These are the addresses stdlib `is_global` treats as global; the predicate must still
        # reject them (multicast via not-is-multicast, NAT64 via not-is-reserved).
        assert ipaddress.ip_address(ip).is_global is True
        assert _ip_is_globally_safe(ipaddress.ip_address(ip)) is False
