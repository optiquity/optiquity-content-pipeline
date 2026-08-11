"""The sources paid-key SEAM (plan G9, §21.10) — converged on the SHARED keystore.

The sources subsystem's PAID keyed sources (a FRED API key, a paid search/news API token) were
DEFERRED at the sources build (mission changelog 0.3.0: "the paid-source keystore, shared with the
transport-selection design"). G9 lands that seam: a keyed source resolves its secret through the
SAME `pipeline.spend.keystore.SecretResolver` the transport-selection machinery uses. There is ONE
keystore — ONE 0600-per-handle store under `$OPTIQUITY_SECRETS_DIR` — serving BOTH the transport
keys (`anthropic:*`) AND the sources keys (`fred:*`, `newsapi:*`, ...). Design once, serve both.

A keyed source descriptor names a NON-secret HANDLE (`api_key_handle: fred:default`) in its
`connection:` config; this seam resolves that handle to the secret VALUE at USE time (never at
descriptor-load time), handing back a redacting `ResolvedSecret` whose bytes are reachable only via
`.reveal()` at the request-injection point. The handle is the reference; the value lives in the
keystore and is surfaced nowhere else (I5 — no secret in config, argv, log, ledger, or telemetry).

**Convergence, not just re-use.** `default_source_resolver()` builds `FileSecretBackend()` with the
SAME zero-arg construction `pipeline.spend.resolve` uses for the transport path, so both resolve
against the identical default store (`$OPTIQUITY_SECRETS_DIR`, home-anchored default). Same class,
same store, same 0600 + fail-closed guarantees — the two key paths cannot drift apart.

**Boundary (the G9 MINOR).** `pipeline/sources/**` may import ONLY `pipeline.spend.keystore` — never
any other `pipeline.spend` module (resolve/meter/wall/entitlement/assignment/construction). Sources
RESOLVES a secret; it does NOT select a transport, admit against a meter, or spend. Paid research
spend still rides the existing gated CLI research path (`ResearchBudget`) unchanged — G9 converges
only the KEY resolution, adding NO new spend surface. (`pipeline.spend.keystore` is itself
standalone — it imports nothing from `pipeline` — so this seam pulls in no transport, generation, or
paid-selection machinery.)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pipeline.spend.keystore import (
    FileSecretBackend,
    KeyStoreError,
    ResolvedSecret,
    SecretHandleError,
    SecretNotFoundError,
    SecretPermissionsError,
    SecretRef,
    SecretResolver,
)

__all__ = [
    "SOURCE_KEY_FIELD",
    "KeyStoreError",
    "ResolvedSecret",
    "SecretHandleError",
    "SecretNotFoundError",
    "SecretPermissionsError",
    "SecretRef",
    "SecretResolver",
    "SourceKeyError",
    "default_source_resolver",
    "resolve_source_key",
    "resolve_source_secret",
    "source_secret_ref",
]

#: The `connection:` field a keyed source names its keystore HANDLE under. A NON-secret reference
#: (`api_key_handle: fred:default`), never the value — the value lives in the keystore. One field
#: name across every keyed source (a FRED feed, a paid search/news backend) so the seam is uniform.
SOURCE_KEY_FIELD = "api_key_handle"


class SourceKeyError(RuntimeError):
    """A keyed-source CONFIG error: a `connection` names its paid-key handle wrong, or a required
    handle is absent. Loud, typed, never a silent keyless fall-through. Names the FIELD/HANDLE,
    NEVER the secret value (I5). Resolution failures (missing secret, loose perms, malformed handle)
    surface as the keystore's own typed `KeyStoreError` subclasses — already handle-named, never a
    value."""

    code = "sources-key-error"


def default_source_resolver(*, env: Mapping[str, str] | None = None) -> SecretResolver:
    """The SHARED keystore resolver for sources — `FileSecretBackend()`, the SAME zero-arg
    construction the transport-selection resolver uses (`pipeline.spend.resolve`). Both resolve
    against the identical default 0600 store (`$OPTIQUITY_SECRETS_DIR`, home-anchored default), so
    a `fred:*` sources key and an `anthropic:*` transport key live in ONE store. `env` overrides the
    environment lookup (tests point it at a `tmp_path` store); production passes nothing."""
    return FileSecretBackend(env=env)


def source_secret_ref(
    connection: Mapping[str, Any], *, field: str = SOURCE_KEY_FIELD
) -> SecretRef | None:
    """The NON-secret keystore handle a keyed source declares under `connection[field]`, parsed to
    a validated `SecretRef` — or `None` when the source names none (a keyless source, common case).

    A present-but-non-string handle is a loud `SourceKeyError` (config typo). A malformed handle
    string surfaces the keystore's own typed `SecretHandleError` (naming the handle, never a value).
    Reads only the reference — it NEVER touches the store or a secret value."""
    if not isinstance(connection, Mapping):
        raise SourceKeyError(
            f"sources-key-error: a keyed source `connection` must be a mapping, got "
            f"{type(connection).__name__}"
        )
    raw = connection.get(field)
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise SourceKeyError(
            f"sources-key-error: connection {field!r} must be a keystore handle string "
            f"'<namespace>:<name>' (e.g. 'fred:default') — a NON-secret reference, never the key "
            f"itself; got {type(raw).__name__}"
        )
    return SecretRef.parse(raw.strip())


def resolve_source_secret(
    handle: str | SecretRef,
    *,
    resolver: SecretResolver | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedSecret:
    """Resolve a keystore `handle` (a `'<namespace>:<name>'` string or a `SecretRef`) to its secret
    VALUE via the SHARED resolver, AT USE TIME. Returns a redacting `ResolvedSecret` — the value is
    reachable only through `.reveal()`, called exactly at the request-injection point, never logged
    or put on argv. `resolver` defaults to `default_source_resolver(env=env)` (the shared store).

    A miss / loose perms / bad handle raise the keystore's typed `KeyStoreError` subclasses, each
    naming the HANDLE and never the value (I5). This selects no transport and spends nothing."""
    ref = handle if isinstance(handle, SecretRef) else SecretRef.parse(handle)
    the_resolver = resolver if resolver is not None else default_source_resolver(env=env)
    return the_resolver.resolve(ref)


def resolve_source_key(
    connection: Mapping[str, Any],
    *,
    resolver: SecretResolver | None = None,
    env: Mapping[str, str] | None = None,
    required: bool = False,
    field: str = SOURCE_KEY_FIELD,
) -> ResolvedSecret | None:
    """The one-call seam a keyed source's `fetch` uses: read the declared handle from `connection`
    and resolve it via the SHARED keystore, or return `None` when the source is keyless.

    `required=True` turns an absent handle into a loud `SourceKeyError` (a paid source with no key
    configured), instead of a silent keyless fall-through. The returned `ResolvedSecret` redacts —
    reveal the value ONLY at the HTTP request point. Selects no transport, admits nothing, spends
    nothing: G9 converges the KEY resolution; paid research spend rides its existing gated path."""
    ref = source_secret_ref(connection, field=field)
    if ref is None:
        if required:
            raise SourceKeyError(
                "sources-key-error: this paid source requires a keystore handle under connection "
                f"{field!r} (a NON-secret '<namespace>:<name>' reference such as 'fred:default'); "
                "none is configured. Store the secret via the keystore, then reference it here."
            )
        return None
    return resolve_source_secret(ref, resolver=resolver, env=env)
