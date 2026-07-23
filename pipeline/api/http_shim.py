"""The DR-1 HTTP shim (skeleton + Tier-A) — the HTTP SIBLING of `main_cli` over `invoke()`.

Design authority: `docs/design.md` §21.9 (as amended, DR-1 C-1: "An OPTIONAL transport FRONT …
MAY be a persistent process, provided it holds no LLM/session/correctness state"), §21.1 (the
closed `invoke(verb, workspace, params, [token], [pins]) -> {envelope, results, [token]}`
contract), §21.7 (the envelope's `ok` = whole-invocation validity only; a per-item `block`
never fails the batch). Reconciled plan: DR-1 **Commit 5a** — skeleton + `serve` + the Tier-A
(cheap-verb) SYNCHRONOUS dispatch + the N-4 status mapping. Architect §C-4 (status mapping) /
§C-9 (verb surface).

**What this is.** A stdlib `http.server.ThreadingHTTPServer` (NO new dependency) exposing a
single `POST /invoke` endpoint that takes `{verb, workspace, params, [token]}`, dispatches to
`invoke(...)`, and serializes the returned dict to an HTTP response. It wires the EXACT existing
handlers via `register_api_handlers()` at startup — it adds NO handler and NO business logic; it
is a transport translation over the same `invoke()` door the CLI uses. The shim carries no
LLM/session/correctness state; every call is one stateless per-verb `invoke()`.

**Scope (Commits 5a + 5b + 5c).** 5a: skeleton + Tier-A synchronous dispatch + N-4 status
mapping. 5b: the net-new AUTH surface + the DoS guard + the instance-config template. 5c (this
commit): the served-workspace ALLOW-LIST policy layer + the explicit loopback-bind knob.
Explicitly NOT here (later commits): the Tier-B 202-Accepted submit+poll async jobs door
(Commit 6/7/8). A Tier-B (paid/async) verb returns a clear 501 placeholder here.

**Auth + DoS (Commit 5b — §C-4 N-7 + the DoS hardening 5a deferred).** Every `POST /invoke`
carries a static bearer / `X-API-Key` secret, compared **constant-time** (`hmac.compare_digest`)
against a configured **SET** of secrets (so an old + new secret both work during rotation).
Auth is checked at the START of the request — BEFORE the path check, BEFORE any body read, and
BEFORE dispatch — so an unauthenticated request never causes a body read. The shim **fails
CLOSED**: if NO secret is configured it REFUSES TO START (never a default/empty accept-all
secret). The auth header + secret are NEVER logged or echoed in a response (redaction, N-7).
**DoS guard:** an over-cap declared `Content-Length` is refused (**413**) BEFORE the body is
read (a max-body cap); a socket timeout drops a stalled slow-loris connection. Config (the
secret set + body cap + socket timeout) is `provenance: instance`: an env var (preferred for
the secret) and/or a gitignored `instance/shim.yaml` (template: `instance/shim.template.yaml`).

**Workspace allow-list + bind (Commit 5c — §C-3 policy layer + loopback bind).** After auth +
body parse and BEFORE dispatch, an optional served-workspace ALLOW-LIST is a NAME-membership
POLICY sitting on TOP of the framework GAP-9 containment (do NOT confuse it with, or duplicate,
that guard):

- **Optional-but-enforced-when-set.** If `workspaces.allowed` is CONFIGURED (non-empty), ONLY a
  listed `workspace` is served — a non-member is refused **403** (`workspace-not-served`) BEFORE
  `invoke()` is called (a shim-level policy refusal). If UNSET (the DEFAULT), the shim serves any
  workspace that passes the GAP-9 resolve-and-contain gate inside `invoke()`; auth remains the
  primary door. The default is documented in `instance/shim.template.yaml` so the operator makes
  a conscious choice.
- **A policy REFINEMENT, never a re-implementation.** The allow-list checks the `workspace` NAME
  for set membership only — it does NOT re-validate the path. An ESCAPING name (`../x`, an
  absolute path, a symlink escape) is ALREADY refused inside `invoke()` (`pipeline.workspace_name`
  `validate_workspace_name`, the landed GAP-9 fix) and surfaces as `isolation-violation` → **403**;
  the shim SURFACES that, it does not re-check the path here. The two 403s stay DISTINCT: the
  allow-list body is `{"error": "workspace-not-served"}`, the GAP-9 body is the fatal
  `isolation-violation` envelope. Even a MISCONFIGURED allow-list that lists an escaping name
  cannot defeat GAP-9 — the containment gate still refuses it inside `invoke()`.

**Bind policy (Commit 5c).** The bind host is a config knob (`bind.host`, default loopback
`127.0.0.1`). A NON-loopback bind is a CONSCIOUS operator choice that REQUIRES an external
TLS/auth proxy — the shim's own auth is a bearer SECRET (application-layer), NOT transport
security. `serve` warns on a non-loopback bind; the default is NEVER moved off loopback.

**Tier-A verb surface (served synchronously — §C-9):**
`list`, `get`, `fetch-by-id`, `create-folio`, `add-to-folio`, `emit-manifest`, `emit-outline`,
`begin-session{generate=none}`, `continue-session{status|list}`. Operator verbs are already
STRUCTURALLY excluded (not in `KNOWN_VERBS`) → `invoke()` answers `unknown-verb`.

**N-4 status mapping (load-bearing — the ENVELOPE is the outcome authority):**

- `envelope.ok == True` (incl. a per-item `block` riding `results[]`) → **200**. The envelope,
  not the status, is the outcome authority; 200 != "all succeeded" (§21.7 SM1).
- `ok == False`, `code == unknown-verb` → **400** (a verb outside the closed set — bad request).
- `ok == False`, `code == invalid-token` → **422** (a §20 session CURSOR error — NEVER 401).
- `ok == False`, `code == isolation-violation` → **403** (cross-workspace / bad-name refusal, §10).
- `ok == False`, any other fatal code → **400** (conservative client-error default).
- A Tier-B verb (generate-next / minting render / begin-session generate!=none) → **501** (the
  async submit+poll door is not built in 5a; it lands in Commit 6/7/8).
- Malformed body / bad JSON / missing verb·workspace → **400** (a clean bad-request, never a crash).
- Unexpected server fault → **500** (never leaks internals).
- (RESERVED, Tier-B) a synthesized transport-timeout terminal → **504** (a timeout has no
  envelope → the jobrunner synthesizes a re-drivable terminal, Commit 4/6). Unreachable in 5a's
  synchronous Tier-A path; documented here for the full contract.

401 is emitted ONLY by the Commit-5b auth gate (a missing/wrong auth secret) and NOWHERE else —
the two "token" concepts (the §20 session cursor `invalid-token` → 422 vs the auth secret → 401)
must not collapse.

**Boundary (rules 4/5).** This module (incl. the auth gate + DoS guard + the allow-list/bind
policy layer + `instance/shim.template.yaml`) is `provenance: framework` (the public
deliverable). The populated `instance/shim.yaml` — the SECRET set + the caps + the
served-workspace ALLOW-LIST + the BIND host — is `provenance: instance` (gitignored,
per-deployment).
"""

from __future__ import annotations

import argparse
import hmac
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pipeline.api import results
from pipeline.api.invoke import KNOWN_VERBS, HandlerNotWired, invoke
from pipeline.canonical import canonical_json_str

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_PORT",
    "DEFAULT_SOCKET_TIMEOUT_SECONDS",
    "ENV_SECRET",
    "ENV_SECRETS",
    "INVOKE_PATH",
    "TIER_A",
    "TIER_B",
    "TIER_UNKNOWN",
    "ShimConfig",
    "ShimConfigError",
    "ShimServer",
    "classify_verb",
    "http_status_for",
    "load_shim_config",
    "main",
    "make_server",
    "serve",
]

#: Default bind: LOOPBACK. Commit 5c makes the bind POLICY explicit + config-driven (`bind.host`),
#: but the DEFAULT is never moved off loopback — a non-loopback bind is a conscious operator choice.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

#: Hosts treated as loopback for the Commit-5c bind advisory. A bind to anything else (an
#: all-interfaces `0.0.0.0`/`::`/`""` or a routable address) is a CONSCIOUS operator choice that
#: REQUIRES an external TLS/auth proxy — the shim's own auth is an application-layer bearer secret,
#: not transport security. `serve` prints a one-line warning on a non-loopback bind.
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
#: The single POST endpoint.
INVOKE_PATH = "/invoke"

#: DoS guard defaults (overridable in `instance/shim.yaml` → `limits:`). A shim request is small
#: JSON, so 1 MiB is generous; the socket timeout drops a stalled slow-loris connection.
DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB
DEFAULT_SOCKET_TIMEOUT_SECONDS = 30.0

#: Env vars carrying the auth secret (PREFERRED over the file so it never touches disk). A single
#: secret plus a comma-separated SET are UNIONED with any `instance/shim.yaml` `auth.secrets`.
ENV_SECRET = "OPTIQUITY_SHIM_SECRET"
ENV_SECRETS = "OPTIQUITY_SHIM_SECRETS"

# --- HTTP statuses used by the N-4 mapping (see the module docstring table) ------------------
_HTTP_OK = 200
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_METHOD_NOT_ALLOWED = 405
_HTTP_PAYLOAD_TOO_LARGE = 413
_HTTP_UNPROCESSABLE = 422
_HTTP_INTERNAL = 500
_HTTP_NOT_IMPLEMENTED = 501

#: A whole-invocation-FATAL envelope `code` → its HTTP status. `invalid-token` is a §20 cursor
#: error (422/never 401); `isolation-violation` is a cross-workspace refusal (403); an unmapped
#: fatal defaults to 400. `ok == True` never consults this table (it is always 200).
_FATAL_STATUS: dict[str, int] = {
    results.CODE_UNKNOWN_VERB: _HTTP_BAD_REQUEST,
    results.CODE_INVALID_TOKEN: _HTTP_UNPROCESSABLE,
    results.CODE_ISOLATION_VIOLATION: _HTTP_FORBIDDEN,
}


def http_status_for(payload: Mapping[str, Any]) -> int:
    """Map an `invoke()` return dict to its HTTP status (the N-4 table; envelope-is-authority).

    `envelope.ok == True` → 200 REGARDLESS of any per-item `block` riding `results[]` (§21.7
    SM1: 200 != "all succeeded"). A fatal envelope maps its `code` via `_FATAL_STATUS`, default
    400. A structurally malformed return (no envelope) → 500 (never expected from `invoke()`).
    """
    envelope = payload.get("envelope") if isinstance(payload, Mapping) else None
    if not isinstance(envelope, Mapping):
        return _HTTP_INTERNAL
    if envelope.get("ok"):
        return _HTTP_OK
    return _FATAL_STATUS.get(envelope.get("code"), _HTTP_BAD_REQUEST)


# --- Auth + DoS config (§C-4 N-7; `provenance: instance`) ------------------------------------


class ShimConfigError(RuntimeError):
    """The shim REFUSES TO START — fail-closed. Raised when no auth secret is configured (never
    fail-open: a missing/empty secret must NEVER become a default accept-all) or when
    `instance/shim.yaml` is malformed. Loud by construction: `serve`/`make_server` do not swallow
    it, so the process exits instead of binding a wide-open door."""


@dataclass(frozen=True)
class ShimConfig:
    """The per-deployment (`provenance: instance`) shim config the server reads.

    `secrets` is the ROTATION SET — a request authenticates if its bearer / `X-API-Key` header
    matches ANY member (constant-time). It is guaranteed non-empty (`load_shim_config` /
    `ShimServer` fail closed on an empty set). `max_body_bytes` + `socket_timeout_seconds` are the
    DoS caps.

    Commit-5c policy knobs (both OPTIONAL, both `provenance: instance`):
    `allowed_workspaces` is the served-workspace ALLOW-LIST — the NAME-membership POLICY on top of
    the framework GAP-9 containment. EMPTY (the default) means UNSET: the shim serves any workspace
    that passes the GAP-9 resolve-and-contain gate inside `invoke()`. Non-empty means only listed
    workspaces are served (a non-member → 403 `workspace-not-served`). `bind_host` is the bind
    address; it DEFAULTS TO LOOPBACK — a non-loopback bind is a conscious operator choice requiring
    an external TLS/auth proxy."""

    secrets: frozenset[str]
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS
    allowed_workspaces: frozenset[str] = frozenset()
    bind_host: str = DEFAULT_HOST


def load_shim_config(root: str = ".", *, env: Mapping[str, str] | None = None) -> ShimConfig:
    """Load the shim config from the environment (PREFERRED for the secret) UNIONED with an
    optional gitignored `<root>/instance/shim.yaml`. FAIL-CLOSED: raise `ShimConfigError` when no
    secret is configured anywhere (the shim never fails open on a paid-spend door).

    Precedence for the rotation SET is a UNION — env secret(s) + file `auth.secrets` all
    authenticate, so an operator can rotate via either surface. The DoS caps come from the file's
    `limits:` block (env-independent), defaulting to `DEFAULT_MAX_BODY_BYTES` /
    `DEFAULT_SOCKET_TIMEOUT_SECONDS`. The secret is NEVER echoed in the raised error.

    Commit-5c policy knobs (file-only, env-independent): `workspaces.allowed` → the served-
    workspace ALLOW-LIST (empty/absent = UNSET = serve any GAP-9-contained workspace); `bind.host`
    → the bind address (default loopback `DEFAULT_HOST`). Both are `provenance: instance`."""
    env = os.environ if env is None else env
    secrets: set[str] = set()
    max_body_bytes = DEFAULT_MAX_BODY_BYTES
    socket_timeout = DEFAULT_SOCKET_TIMEOUT_SECONDS
    allowed_workspaces: set[str] = set()
    bind_host = DEFAULT_HOST

    cfg_path = Path(root) / "instance" / "shim.yaml"
    if cfg_path.exists():
        # Function-scoped import: keep the module import light. `YAMLLoadError` re-exports
        # ruamel's `YAMLError` (a `ScannerError` on a syntax error subclasses it).
        from pipeline.yamlio import YAMLLoadError, load_yaml

        try:
            data = load_yaml(cfg_path.read_text(encoding="utf-8")) or {}
        except YAMLLoadError as exc:
            # Re-raise as the documented fail-closed error (main() → clean return 2). DEFENSIVE:
            # name the file + the error CLASS only — never embed str(exc) (a source snippet could
            # carry secret-adjacent text into the message/log).
            raise ShimConfigError(f"{cfg_path}: malformed YAML ({type(exc).__name__})") from exc
        if not isinstance(data, Mapping):
            raise ShimConfigError(f"{cfg_path}: the top-level YAML must be a mapping")
        auth = data.get("auth") or {}
        file_secrets = auth.get("secrets") if isinstance(auth, Mapping) else None
        if isinstance(file_secrets, str):
            file_secrets = [file_secrets]
        if isinstance(file_secrets, (list, tuple)):
            secrets.update(str(s).strip() for s in file_secrets if str(s).strip())
        limits = data.get("limits") or {}
        if isinstance(limits, Mapping):
            if limits.get("max_body_bytes") is not None:
                max_body_bytes = int(limits["max_body_bytes"])
            if limits.get("socket_timeout_seconds") is not None:
                socket_timeout = float(limits["socket_timeout_seconds"])
        # Commit 5c — the served-workspace ALLOW-LIST (a NAME set, NOT a path check). A single
        # string is accepted as a one-element list. Empty/absent leaves the set UNSET (serve any
        # GAP-9-contained workspace). This is policy only — no path validation happens here.
        ws_cfg = data.get("workspaces") or {}
        if isinstance(ws_cfg, Mapping):
            allow = ws_cfg.get("allowed")
            if isinstance(allow, str):
                allow = [allow]
            if isinstance(allow, (list, tuple)):
                allowed_workspaces.update(str(w).strip() for w in allow if str(w).strip())
        # Commit 5c — the explicit bind host (default loopback). A non-loopback value is a
        # conscious operator choice; `serve` warns on it. The default is never moved off loopback.
        bind_cfg = data.get("bind") or {}
        if isinstance(bind_cfg, Mapping):
            host_val = bind_cfg.get("host")
            if isinstance(host_val, str) and host_val.strip():
                bind_host = host_val.strip()

    single = (env.get(ENV_SECRET) or "").strip()
    if single:
        secrets.add(single)
    secrets.update(s.strip() for s in (env.get(ENV_SECRETS) or "").split(",") if s.strip())

    if not secrets:
        raise ShimConfigError(
            "refuse to start: no auth secret configured. Set the "
            f"{ENV_SECRET} env var (preferred) or auth.secrets in instance/shim.yaml "
            "(copy instance/shim.template.yaml). The shim NEVER fails open."
        )
    return ShimConfig(
        frozenset(secrets),
        max_body_bytes,
        socket_timeout,
        frozenset(allowed_workspaces),
        bind_host,
    )


# --- Tier classification (§C-9) --------------------------------------------------------------
TIER_A = "tier-a"
TIER_B = "tier-b"
TIER_UNKNOWN = "unknown"

#: Tier-A verbs whose id-free/param-free shape is always cheap+synchronous.
_TIER_A_SIMPLE = frozenset(
    {"list", "get", "fetch-by-id", "create-folio", "add-to-folio", "emit-manifest", "emit-outline"}
)
#: The only two `continue-session` actions Commit 5a serves synchronously (§C-9). Every other
#: action (the paid `generate-next`, a minting `render`, and — deferred in 5a — the cheap
#: `fetch`/`get`/`add-to-folio`/`emit-manifest` session actions + any unknown action) is Tier-B.
_TIER_A_SESSION_ACTIONS = frozenset({"status", "list"})


def classify_verb(verb: str, params: Mapping[str, Any]) -> str:
    """`TIER_A` (serve synchronously), `TIER_B` (defer → 501), or `TIER_UNKNOWN` (let `invoke()`
    answer `unknown-verb`). Tier-B = the paid/async surface Commit 5a does not serve: `render`
    (optimistic-sync lands in Commit 7), `begin-session{generate!=none}`, and any
    `continue-session` action outside `{status, list}`."""
    if verb not in KNOWN_VERBS:
        return TIER_UNKNOWN
    if verb in _TIER_A_SIMPLE:
        return TIER_A
    if verb == "begin-session":
        return TIER_A if params.get("generate") in (None, "none") else TIER_B
    if verb == "continue-session":
        return TIER_A if params.get("action") in _TIER_A_SESSION_ACTIONS else TIER_B
    return TIER_B  # `render` (and any future known verb not classified Tier-A) is deferred in 5a


def _tier_b_body(verb: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """The 501 placeholder for a deferred Tier-B verb (no async door in Commit 5a)."""
    detail = (
        f"verb {verb!r} is a Tier-B (paid/async) operation this synchronous Tier-A door does "
        "not serve; it is wired via the 202-Accepted submit+poll door in a later DR-1 commit "
        "(Commit 6/7/8). Tier-A = list/get/fetch-by-id/create-folio/add-to-folio/emit-manifest/"
        "emit-outline, begin-session{generate=none}, continue-session{status|list}."
    )
    body: dict[str, Any] = {"error": "tier-b-not-served", "verb": verb, "detail": detail}
    action = params.get("action")
    if isinstance(action, str):
        body["action"] = action
    return body


# --- The server ------------------------------------------------------------------------------


class ShimServer(ThreadingHTTPServer):
    """A `ThreadingHTTPServer` carrying the (stateless) dispatch config + the auth/DoS config.

    `invoke_fn` is the `invoke`-shaped callable the handler dispatches to (default the real
    `pipeline.api.invoke.invoke`; a test injects a stub). `root` is the framework repo root the
    workspace store is built under. `secrets` is the (non-empty) rotation set the handler
    constant-time compares against; `max_body_bytes` + `socket_timeout` are the DoS caps.
    `allowed_workspaces` is the Commit-5c served-workspace ALLOW-LIST (EMPTY = UNSET = serve any
    GAP-9-contained workspace; non-empty = only listed names, a non-member → 403). Thread-per-
    request is safe: every request is one stateless `invoke()` call — no cross-request state lives
    on the server (§21.9 amended).

    FAIL-CLOSED: an EMPTY `secrets` set raises `ShimConfigError` BEFORE `super().__init__` binds
    the socket — the server never comes up wide open (never a default/empty accept-all secret)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        invoke_fn: Callable[..., Mapping[str, Any]],
        root: str = ".",
        secrets: frozenset[str] = frozenset(),
        max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
        socket_timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
        allowed_workspaces: frozenset[str] = frozenset(),
    ) -> None:
        if not secrets:
            raise ShimConfigError(
                "refuse to start: no auth secret configured (fail-closed; the shim NEVER fails "
                f"open). Set {ENV_SECRET} or auth.secrets in instance/shim.yaml."
            )
        super().__init__(server_address, _ShimRequestHandler)
        self.invoke_fn = invoke_fn
        self.root = root
        self.secrets = frozenset(secrets)
        self.max_body_bytes = int(max_body_bytes)
        self.socket_timeout = float(socket_timeout)
        #: The served-workspace allow-list (NAME set). Empty = unset = serve any GAP-9-contained
        #: workspace; the per-request check lives in `_ShimRequestHandler._handle_post`.
        self.allowed_workspaces = frozenset(allowed_workspaces)


class _ShimRequestHandler(BaseHTTPRequestHandler):
    """`POST /invoke` → `invoke()` → serialized envelope. No handler, no business logic here."""

    server_version = "optiquity-shim/DR-1"
    sys_version = ""  # do not leak the Python version in the Server header

    def setup(self) -> None:
        """Apply the server's slow-loris SOCKET TIMEOUT to this request's socket before I/O.

        `StreamRequestHandler.setup()` reads `self.timeout` and `settimeout`s the connection, so a
        stalled client (partial headers, never-completed body) is dropped after the cap instead of
        pinning a thread forever (DoS guard, §C-4)."""
        self.timeout = getattr(self.server, "socket_timeout", None)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        """REDACTION (§C-4 N-7): the per-request stderr log stays SILENCED — the surest redaction
        is to log nothing. The auth header value + the configured secret are NEVER written to any
        log or echoed in a response body (the 401 body is a generic 'unauthorized', never the
        presented token)."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib dispatch name
        try:
            self._handle_post()
        except Exception:  # never let a request crash the server thread
            self._respond(_HTTP_INTERNAL, {"error": "internal-error"})

    def do_GET(self) -> None:  # noqa: N802 - stdlib dispatch name
        self._respond(
            _HTTP_METHOD_NOT_ALLOWED,
            {"error": "method-not-allowed", "detail": f"POST {INVOKE_PATH}"},
        )

    def _handle_post(self) -> None:
        server: ShimServer = self.server  # type: ignore[assignment]

        # (1) AUTH FIRST — before the path check, before ANY body read, before dispatch
        #     (§C-4 N-7 + the DoS ordering). 401 is emitted ONLY here. An unauthenticated
        #     request (incl. an oversized/garbage body) never reaches the body read or invoke().
        if not self._authorized(server):
            self._respond(
                _HTTP_UNAUTHORIZED,
                {"error": "unauthorized", "detail": "a valid bearer/X-API-Key secret is required"},
            )
            return

        if self.path.split("?", 1)[0].rstrip("/") not in ("", INVOKE_PATH):
            self._respond(
                _HTTP_NOT_FOUND,
                {"error": "not-found", "detail": f"unknown path; POST {INVOKE_PATH}"},
            )
            return

        # (2) DoS guard — reject an over-cap DECLARED Content-Length BEFORE reading the body (413).
        length = self._content_length()
        if length is None:
            return  # `_content_length` already sent a 400 (a malformed header)
        if length > server.max_body_bytes:
            self.close_connection = True  # do not keep-alive with an unread oversized body
            self._respond(
                _HTTP_PAYLOAD_TOO_LARGE,
                {
                    "error": "payload-too-large",
                    "detail": f"request body exceeds the {server.max_body_bytes}-byte cap",
                },
            )
            return

        # (3) The body is now bounded by the cap: read + parse it.
        payload = self._read_json_object(length)
        if payload is None:
            return  # `_read_json_object` already sent a 400

        verb = payload.get("verb")
        workspace = payload.get("workspace")
        params = payload.get("params", {})
        token = payload.get("token")
        if not isinstance(verb, str) or not verb:
            self._bad_request("'verb' is required (a non-empty string)")
            return
        if not isinstance(workspace, str) or not workspace:
            self._bad_request("'workspace' is required (a non-empty string)")
            return
        if not isinstance(params, Mapping):
            self._bad_request("'params' must be a JSON object")
            return

        # (4) Workspace ALLOW-LIST (Commit 5c) — a shim POLICY layer (NAME membership) on TOP of
        #     the framework GAP-9 containment. If an allow-list is CONFIGURED (non-empty), only a
        #     LISTED workspace is served: a non-member → 403 `workspace-not-served` BEFORE dispatch
        #     (invoke_fn is NEVER called). If UNSET, any workspace is served here and the GAP-9
        #     resolve-and-contain gate inside invoke() remains the containment authority (auth is
        #     the primary door). This is NAME membership ONLY — it does NOT re-validate the path,
        #     so an escaping name is still refused by invoke()'s `isolation-violation` gate (→ 403,
        #     a DISTINCT `isolation-violation` envelope body). A misconfigured allow-list that
        #     lists an escaping name cannot defeat GAP-9 — invoke() still refuses it.
        allowed = server.allowed_workspaces
        if allowed and workspace not in allowed:
            self._respond(
                _HTTP_FORBIDDEN,
                {
                    "error": "workspace-not-served",
                    "detail": (
                        f"workspace {workspace!r} is not in this shim's served-workspace "
                        "allow-list (workspaces.allowed in instance/shim.yaml)"
                    ),
                },
            )
            return

        if classify_verb(verb, params) == TIER_B:
            self._respond(_HTTP_NOT_IMPLEMENTED, _tier_b_body(verb, params))
            return

        # Tier-A or unknown-verb: `invoke()` is the authority (unknown-verb → its fatal envelope).
        try:
            result = server.invoke_fn(verb, workspace, params, token, root=server.root)
        except HandlerNotWired:
            # Post-`register_api_handlers()` this is unreachable; defensive only.
            self._respond(_HTTP_INTERNAL, {"error": "handler-not-wired", "verb": verb})
            return
        self._respond(http_status_for(result), result)

    def _presented_secret(self) -> str | None:
        """The bearer / `X-API-Key` secret the caller presented, or None. NEVER logged (N-7).

        `Authorization: Bearer <secret>` is checked first, then `X-API-Key: <secret>`."""
        auth = self.headers.get("Authorization")
        if auth:
            scheme, _, value = auth.partition(" ")
            if scheme.lower() == "bearer" and value.strip():
                return value.strip()
        api_key = self.headers.get("X-API-Key")
        if api_key and api_key.strip():
            return api_key.strip()
        return None

    def _authorized(self, server: ShimServer) -> bool:
        """CONSTANT-TIME compare (`hmac.compare_digest`) of the presented secret against EACH
        member of the rotation set — an old + a new secret both authenticate during rotation. No
        early-out on a match (iterate the whole set) so the comparison does not leak WHICH secret
        matched (or a length) via timing."""
        presented = self._presented_secret()
        if presented is None:
            return False
        presented_b = presented.encode("utf-8")
        authorized = False
        for secret in server.secrets:
            if hmac.compare_digest(presented_b, secret.encode("utf-8")):
                authorized = True
        return authorized

    def _content_length(self) -> int | None:
        """The declared `Content-Length` (0 if absent). On a malformed header send a 400 and
        return None. The DoS cap is applied to THIS declared length BEFORE any body read, so an
        attacker's huge declared length is refused (413) without allocating/reading the body."""
        raw = self.headers.get("Content-Length")
        if raw is None:
            return 0
        try:
            length = int(raw)
        except (TypeError, ValueError):
            self._bad_request("invalid Content-Length header")
            return None
        if length < 0:
            self._bad_request("invalid Content-Length header")
            return None
        return length

    def _read_json_object(self, length: int) -> dict[str, Any] | None:
        """Read `length` bytes (already ≤ the DoS cap) + parse a JSON object, or send a 400 and
        return None. The Content-Length is parsed + cap-checked by the caller BEFORE this read."""
        import json

        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            self._bad_request("request body is required: {verb, workspace, params, [token]}")
            return None
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._bad_request(f"request body must be valid JSON: {exc}")
            return None
        if not isinstance(parsed, dict):
            self._bad_request("request body must be a JSON object {verb, workspace, params, …}")
            return None
        return parsed

    def _bad_request(self, detail: str) -> None:
        self._respond(_HTTP_BAD_REQUEST, {"error": "bad-request", "detail": detail})

    def _respond(self, status: int, obj: Mapping[str, Any]) -> None:
        body = (canonical_json_str(obj) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_server(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    invoke_fn: Callable[..., Mapping[str, Any]] = invoke,
    root: str = ".",
    secrets: frozenset[str] = frozenset(),
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES,
    socket_timeout: float = DEFAULT_SOCKET_TIMEOUT_SECONDS,
    allowed_workspaces: frozenset[str] = frozenset(),
) -> ShimServer:
    """Build (but do not start) the shim server. `port=0` binds an ephemeral port (tests read
    `server.server_address`). The caller is responsible for wiring handlers (`serve()` does).
    `allowed_workspaces` is the Commit-5c served-workspace allow-list (empty = unset = serve any
    GAP-9-contained workspace).

    FAIL-CLOSED: an empty `secrets` set raises `ShimConfigError` (via `ShimServer`) — the server
    is never built wide open."""
    return ShimServer(
        (host, port),
        invoke_fn=invoke_fn,
        root=root,
        secrets=secrets,
        max_body_bytes=max_body_bytes,
        socket_timeout=socket_timeout,
        allowed_workspaces=allowed_workspaces,
    )


def serve(
    *, host: str | None = None, port: int = DEFAULT_PORT, root: str = "."
) -> None:
    """Load config (FAIL-CLOSED on a missing secret), wire the EXACT existing handlers, then serve
    `POST /invoke` until interrupted.

    `load_shim_config` runs FIRST and RAISES `ShimConfigError` before any side effect if no auth
    secret is configured — the process exits instead of binding a wide-open door.
    `register_api_handlers()` is imported function-scoped (like `main_cli`) so importing this
    module never wires verbs the step-32 empty-registry tests expect empty. The shim adds NO
    handler — it wires the same production surface. The listening banner NEVER prints the secret.

    Commit-5c bind policy: the bind host resolves to `host` if an EXPLICIT one is passed (a CLI
    `--host` override), else the config's `bind.host` (default loopback `DEFAULT_HOST`). A
    non-loopback bind emits a one-line ADVISORY — it is a conscious operator choice that requires
    an external TLS/auth proxy. The served-workspace allow-list (`config.allowed_workspaces`) is
    passed to the server as the Commit-5c policy layer."""
    from pipeline.api.session import register_api_handlers

    config = load_shim_config(root)  # fail-closed: raises ShimConfigError if no secret
    bind_host = host if host is not None else config.bind_host

    register_api_handlers()
    server = make_server(
        bind_host,
        port,
        invoke_fn=invoke,
        root=root,
        secrets=config.secrets,
        max_body_bytes=config.max_body_bytes,
        socket_timeout=config.socket_timeout_seconds,
        allowed_workspaces=config.allowed_workspaces,
    )
    bound_host, bound_port = server.server_address
    if bind_host not in _LOOPBACK_HOSTS:
        print(
            f"pipeline serve: WARNING — binding to a NON-loopback host {bind_host!r}. The shim's "
            "auth is an application-layer bearer secret, NOT transport security: put an external "
            "TLS/auth proxy in front of a network-exposed bind (§C-3). The default is loopback.",
            file=sys.stderr,
        )
    allow_note = (
        f"allow-list: {len(config.allowed_workspaces)} workspace(s)"
        if config.allowed_workspaces
        else "allow-list: unset (any GAP-9-contained workspace)"
    )
    print(
        f"pipeline serve: listening on http://{bound_host}:{bound_port}{INVOKE_PATH} "
        f"(auth: required, {len(config.secrets)} secret(s); {allow_note}; Tier-A synchronous; "
        "Tier-B async door lands in a later DR-1 commit)",
        file=sys.stderr,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - operator Ctrl-C
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    """`scripts/pipeline serve` → this entry: start the HTTP shim. `--help` dispatches (argparse).

    The bind defaults to loopback; Commit 5c makes the bind POLICY explicit + config-driven
    (`bind.host` in instance/shim.yaml). An EXPLICIT `--host` overrides the config; without it the
    config's `bind.host` (default loopback) is used. A missing auth secret is a clean fail-closed
    exit (a loud one-line error + non-zero), never a traceback and never a wide-open bind."""
    parser = argparse.ArgumentParser(
        prog="pipeline serve",
        description=(
            "The DR-1 HTTP shim (§21.9): a stateless persistent transport FRONT over invoke() — "
            "POST /invoke {verb, workspace, params, [token]} -> the JSON envelope. Requires an "
            "auth secret (env OPTIQUITY_SHIM_SECRET or instance/shim.yaml; fail-closed). Tier-A "
            "(cheap) verbs are served synchronously; Tier-B (paid/async) verbs land in a later "
            "DR-1 commit."
        ),
    )
    parser.add_argument(
        "--host",
        default=None,
        help=(
            "bind host; overrides bind.host in instance/shim.yaml (which defaults to loopback "
            "127.0.0.1). A non-loopback bind requires an external TLS/auth proxy."
        ),
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default: 8787)")
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)
    try:
        serve(host=args.host, port=args.port, root=args.root)
    except ShimConfigError as exc:
        print(f"pipeline serve: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
