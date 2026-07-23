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

**Scope of Commit 5a (deliberately narrow).** Skeleton + Tier-A synchronous dispatch ONLY.
Explicitly NOT here (later commits): auth (Commit 5b), the workspace allow-list + explicit
loopback bind policy (Commit 5c), and the Tier-B 202-Accepted submit+poll async jobs door
(Commit 6/7/8). A Tier-B (paid/async) verb returns a clear 501 placeholder here.

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

401 is RESERVED for the Commit-5b auth-secret failure and is NEVER emitted here — the two
"token" concepts (the §20 session cursor vs the auth secret) must not collapse.

**Boundary (rules 4/5).** This module is `provenance: framework` (the public deliverable). The
secret / bind / allow-list / caps land as `provenance: instance` config in later commits.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from pipeline.api import results
from pipeline.api.invoke import KNOWN_VERBS, HandlerNotWired, invoke
from pipeline.canonical import canonical_json_str

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "INVOKE_PATH",
    "TIER_A",
    "TIER_B",
    "TIER_UNKNOWN",
    "ShimServer",
    "classify_verb",
    "http_status_for",
    "main",
    "make_server",
    "serve",
]

#: Default bind. Loopback here already (safe); Commit 5c makes the bind POLICY explicit/config.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
#: The single POST endpoint.
INVOKE_PATH = "/invoke"

# --- HTTP statuses used by the N-4 mapping (see the module docstring table) ------------------
_HTTP_OK = 200
_HTTP_BAD_REQUEST = 400
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_METHOD_NOT_ALLOWED = 405
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
    """A `ThreadingHTTPServer` carrying the (stateless) dispatch config the handler reads.

    `invoke_fn` is the `invoke`-shaped callable the handler dispatches to (default the real
    `pipeline.api.invoke.invoke`; a test injects a stub). `root` is the framework repo root the
    workspace store is built under. Thread-per-request is safe: every request is one stateless
    `invoke()` call — no cross-request state lives on the server (§21.9 amended)."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        server_address: tuple[str, int],
        *,
        invoke_fn: Callable[..., Mapping[str, Any]],
        root: str = ".",
    ) -> None:
        super().__init__(server_address, _ShimRequestHandler)
        self.invoke_fn = invoke_fn
        self.root = root


class _ShimRequestHandler(BaseHTTPRequestHandler):
    """`POST /invoke` → `invoke()` → serialized envelope. No handler, no business logic here."""

    server_version = "optiquity-shim/DR-1"
    sys_version = ""  # do not leak the Python version in the Server header

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        """Silence the default per-request stderr log. Commit 5b adds redacted structured logging
        (the auth header + request bodies must NEVER be logged — §C-4 N-7)."""

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
        if self.path.split("?", 1)[0].rstrip("/") not in ("", INVOKE_PATH):
            self._respond(
                _HTTP_NOT_FOUND,
                {"error": "not-found", "detail": f"unknown path; POST {INVOKE_PATH}"},
            )
            return

        payload = self._read_json_object()
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

    def _read_json_object(self) -> dict[str, Any] | None:
        """Read + parse the request body as a JSON object, or send a 400 and return None.

        Commit 5b adds the DoS hardening (a `Content-Length` cap + a socket timeout, checked
        BEFORE the body read); here the body is read by its declared length."""
        import json

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            self._bad_request("invalid Content-Length header")
            return None
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
) -> ShimServer:
    """Build (but do not start) the shim server. `port=0` binds an ephemeral port (tests read
    `server.server_address`). The caller is responsible for wiring handlers (`serve()` does)."""
    return ShimServer((host, port), invoke_fn=invoke_fn, root=root)


def serve(
    *, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, root: str = "."
) -> None:
    """Wire the EXACT existing handlers, then serve `POST /invoke` until interrupted.

    `register_api_handlers()` is imported function-scoped (like `main_cli`) so importing this
    module never wires verbs the step-32 empty-registry tests expect empty, and to keep the
    module import light. The shim adds NO handler — it wires the same production surface."""
    from pipeline.api.session import register_api_handlers

    register_api_handlers()
    server = make_server(host, port, invoke_fn=invoke, root=root)
    bound_host, bound_port = server.server_address
    print(
        f"pipeline serve: listening on http://{bound_host}:{bound_port}{INVOKE_PATH} "
        "(Tier-A synchronous; Tier-B async door lands in a later DR-1 commit)",
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

    The bind defaults to loopback; Commit 5c makes the bind POLICY explicit + config-driven."""
    parser = argparse.ArgumentParser(
        prog="pipeline serve",
        description=(
            "The DR-1 HTTP shim (§21.9): a stateless persistent transport FRONT over invoke() — "
            "POST /invoke {verb, workspace, params, [token]} -> the JSON envelope. Tier-A "
            "(cheap) verbs are served synchronously; Tier-B (paid/async) verbs land in a later "
            "DR-1 commit."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default: 8787)")
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)
    serve(host=args.host, port=args.port, root=args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
