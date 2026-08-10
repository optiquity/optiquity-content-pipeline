"""The DR-1 HTTP shim (skeleton + Tier-A) — the HTTP SIBLING of `main_cli` over `invoke()`.

Design authority: `docs/design.md` §21.9 (as amended, DR-1 C-1: "An OPTIONAL transport FRONT …
MAY be a persistent process, provided it holds no LLM/session/correctness state"), §21.1 (the
closed `invoke(verb, workspace, params, [token], [pins]) -> {envelope, results, [token]}`
contract), §21.7 (the envelope's `ok` = whole-invocation validity only; a per-item `block`
never fails the batch). Reconciled plan: DR-1 **Commit 5a** — skeleton + `serve` + the Tier-A
(cheap-verb) SYNCHRONOUS dispatch + the N-4 status mapping. Architect §C-4 (status mapping) /
§C-9 (verb surface).

**Archived design records (repo-relative — the `§C-`/`N-` labels below resolve here).** The
`§C-1`/`§C-3`/`§C-4`/`§C-9` conclusion labels are decided in
`docs/archive/design-record/dr-design-passes/dr1-http-shim/architect-03-reconciliation/report.md`;
the `N-3`/`N-4`/`N-6`/`N-7` findings it folds in are stated in
`docs/archive/design-record/dr-design-passes/dr1-http-shim/architect-02-adversarial/report.md`;
the build plan is
`docs/archive/design-record/dr-design-passes/dr1-http-shim/planner-03-reconciliation/report.md`.
The poll/webhook rework is
`docs/archive/design-record/dr-design-passes/dr1-webhook-poll/architect-01/report.md` (see
`pipeline/callback_policy.py`).

**What this is.** A stdlib `http.server.ThreadingHTTPServer` (NO new dependency) exposing a
single `POST /invoke` endpoint that takes `{verb, workspace, params, [token]}`, dispatches to
`invoke(...)`, and serializes the returned dict to an HTTP response. It wires the EXACT existing
handlers via `register_api_handlers()` at startup — it adds NO handler and NO business logic; it
is a transport translation over the same `invoke()` door the CLI uses. The shim carries no
LLM/session/correctness state; every call is one stateless per-verb `invoke()`.

**Scope (Commits 5a + 5b + 5c + 6 + 8).** 5a: skeleton + Tier-A synchronous dispatch + N-4 status
mapping. 5b: the net-new AUTH surface + the DoS guard + the instance-config template. 5c: the
served-workspace ALLOW-LIST policy layer + the explicit loopback-bind knob. 6: the Tier-B
202-Accepted submit + poll async jobs door for `continue-session{generate-next}` — the shim
resolves the PREDICTABLE target artifact-ids LLM-free (re-resolving the session plan from the
token cursor, `pipeline.api.session`), `pipeline.jobs.JobStore.submit`s a lossy idempotency record
(create-exclusive + H2 steal), detaches a `pipeline.api.jobrunner` runner, and returns **202 + the
predictable ids**; a `POST /poll` resolves the job by target-id
(`pipeline.jobs.resolve_job_state`). **8 (this commit): the minting `render` Tier-B door with an
OPTIMISTIC-SYNC-then-202 fast path** — the shim resolves the PREDICTABLE render deliverable-id
LLM-free (`pipeline.api.render.resolve_render_target`, the SAME primitives the render handler
materializes through — no fork), submits + detaches a runner over the SAME jobs machinery, then
HOLDS the request up to `RENDER_SYNC_WAIT_SECONDS` polling OUTPUT existence: a cache-hit / fast
serialize → **200 + output** (sync); a paid reshape exceeding the wait → **202 + the predictable
deliverable-id** (poll / webhook from there). GAP-10 already claims render's mints, so a concurrent
render is `claim-held` (never a double-spend). Still a 501 placeholder (later commit):
`begin-session{generate!=none}` (Commit 9).

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
  `validate_workspace_path`, the landed GAP-9 fix) and surfaces as `isolation-violation` → **403**;
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
`begin-session{generate=none}`, and the CHEAP `continue-session` actions
`{status|list|fetch|get|add-to-folio|emit-manifest}` (Commit 6 promoted the cheap session
actions from Tier-B to Tier-A — they are read/side-output, LLM-free, so they belong on the
synchronous door). Operator verbs are already STRUCTURALLY excluded (not in `KNOWN_VERBS`) →
`invoke()` answers `unknown-verb`.

**Tier-B async door (Commit 6 — the 202 + poll wire shape, N-3):** ONLY
`continue-session{generate-next}` in this commit. A submit resolves the predictable target
artifact-id set (§22.2 — the id the paid call will materialize, computed LLM-free from the plan
+ cursor) and returns a **202 acknowledgement** whose body is NOT an `invoke()` envelope:
`{"status": "accepted", "job": {"key": <r-id>, "target_ids": [...]}, "poll": {...}}` — the
"same-envelope" invariant of §21.7 is AMENDED to admit this async ack (documented in Commit 11 /
`known-issues.md`). The Tier-B submit REQUIRES an `idempotency_key` in `params` (a retry must
collide on one job, N-2; n8n supplies `$execution.id`) → a missing key is a **400**. The poll
door `POST /poll {workspace, key, target_ids}` carries the SAME auth + allow-list + isolation
gates as the submit (N-6) and maps the resolved job state to a status (see below).

**N-4 status mapping (load-bearing — the ENVELOPE is the outcome authority):**

- `envelope.ok == True` (incl. a per-item `block` riding `results[]`) → **200**. The envelope,
  not the status, is the outcome authority; 200 != "all succeeded" (§21.7 SM1).
- `ok == False`, `code == unknown-verb` → **400** (a verb outside the closed set — bad request).
- `ok == False`, `code == invalid-token` → **422** (a §20 session CURSOR error — NEVER 401).
- `ok == False`, `code == isolation-violation` → **403** (cross-workspace / bad-name refusal, §10).
- `ok == False`, any other fatal code → **400** (conservative client-error default).
- The STILL-DEFERRED Tier-B verb `begin-session{generate!=none}` → **501** (its async door lands
  in Commit 9). A minting `render` is now SERVED (Commit 8, `_submit_render`), not 501.
- Malformed body / bad JSON / missing verb·workspace → **400** (a clean bad-request, never a crash).
- Unexpected server fault → **500** (never leaks internals).

**Tier-B submit dispositions (Commit 6) → HTTP:** `JobStore.submit` returns one of —
`done` (the whole job already materialized) → **200** + the fetched output (via the `fetch-by-id`
handler); `existing` (a legitimate in-flight 202→S1 window) → **202** ack (no re-spawn);
`spawned`/`stolen` (`.spawn is True`) → detach the runner, then **202** ack.

**Tier-B poll states (Commit 6, `pipeline.jobs.resolve_job_state`) → HTTP:** `done` (OUTPUT
existence, §22.7) → **200** + fetched output; `running` (a live claim/lease OR the job-lifetime
window) → **202**; a stored `failed` terminal → the terminal envelope + its MAPPED status
(timeout-class / `re-drivable` → **504** re-drivable; `rate-limit-backpressure` → **429**;
an envelope code maps via the fatal table; any other terminal → **500**); `failed-redrivable`
(nothing live, nothing done, no stored reason) → **409** telling the caller to re-submit with
the SAME `idempotency_key` (§22.7 — never a false DONE, never a wedge).

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
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.api.invoke import KNOWN_VERBS, HandlerNotWired, invoke
from pipeline.callback_policy import CallbackPolicyError, validate_callback_url
from pipeline.canonical import canonical_json_str
from pipeline.opdefaults import (
    MAX_PARALLEL_SESSIONS,
    RENDER_SYNC_WAIT_SECONDS,
    SHIM_CAP_RETRY_AFTER_SECONDS,
)

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MAX_BODY_BYTES",
    "DEFAULT_PORT",
    "DEFAULT_SOCKET_TIMEOUT_SECONDS",
    "ENV_SECRET",
    "ENV_SECRETS",
    "INVOKE_PATH",
    "POLL_PATH",
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
#: The synchronous dispatch endpoint (Tier-A + the Tier-B submit).
INVOKE_PATH = "/invoke"
#: The Tier-B async poll endpoint (Commit 6): `POST /poll {workspace, key, target_ids}` — carries
#: the SAME auth + allow-list + isolation gates as `/invoke` (N-6).
POLL_PATH = "/poll"

#: DoS guard defaults (overridable in `instance/shim.yaml` → `limits:`). A shim request is small
#: JSON, so 1 MiB is generous; the socket timeout drops a stalled slow-loris connection.
DEFAULT_MAX_BODY_BYTES = 1_048_576  # 1 MiB
DEFAULT_SOCKET_TIMEOUT_SECONDS = 30.0

#: The render OPTIMISTIC-SYNC poll cadence (Commit 8): the shim re-checks OUTPUT existence
#: (`is_done`) at this interval while it holds a `render` submit open, up to
#: `RENDER_SYNC_WAIT_SECONDS` (`pipeline.opdefaults`). Small so a fast render returns 200 promptly;
#: the loop NEVER busy-spins (it sleeps between checks) and NEVER exceeds the hard wait ceiling.
RENDER_POLL_INTERVAL_SECONDS = 0.25

#: Env vars carrying the auth secret (PREFERRED over the file so it never touches disk). A single
#: secret plus a comma-separated SET are UNIONED with any `instance/shim.yaml` `auth.secrets`.
ENV_SECRET = "OPTIQUITY_SHIM_SECRET"
ENV_SECRETS = "OPTIQUITY_SHIM_SECRETS"

# --- HTTP statuses used by the N-4 mapping (see the module docstring table) ------------------
_HTTP_OK = 200
_HTTP_ACCEPTED = 202
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_NOT_FOUND = 404
_HTTP_METHOD_NOT_ALLOWED = 405
_HTTP_CONFLICT = 409
_HTTP_PAYLOAD_TOO_LARGE = 413
_HTTP_UNPROCESSABLE = 422
_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_INTERNAL = 500
_HTTP_NOT_IMPLEMENTED = 501
_HTTP_GATEWAY_TIMEOUT = 504

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
    an external TLS/auth proxy.

    `allowed_callback_hosts` (W3b, OPTIONAL, `provenance: instance`) is the operator-approved set of
    webhook callback hosts. Unlike the workspace allow-list, it is OPT-IN / FAIL-CLOSED: EMPTY (the
    default) DISABLES callbacks — a submit carrying `callback_url` is refused 400
    `callbacks-disabled` (per `callback_policy.validate_callback_url`). Outbound egress is a
    higher-risk surface, so the operator must consciously name their orchestrator host(s) to enable
    callbacks at all."""

    secrets: frozenset[str]
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    socket_timeout_seconds: float = DEFAULT_SOCKET_TIMEOUT_SECONDS
    allowed_workspaces: frozenset[str] = frozenset()
    bind_host: str = DEFAULT_HOST
    allowed_callback_hosts: frozenset[str] = frozenset()


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
    → the bind address (default loopback `DEFAULT_HOST`). W3b: `callbacks.allowed_hosts` → the
    webhook callback host allow-list (empty/absent = OPT-IN OFF = callbacks DISABLED). All are
    `provenance: instance`."""
    env = os.environ if env is None else env
    secrets: set[str] = set()
    max_body_bytes = DEFAULT_MAX_BODY_BYTES
    socket_timeout = DEFAULT_SOCKET_TIMEOUT_SECONDS
    allowed_workspaces: set[str] = set()
    bind_host = DEFAULT_HOST
    allowed_callback_hosts: set[str] = set()

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
        # W3b — the webhook callback host ALLOW-LIST (a NAME/`host[:port]` set, mirrors
        # workspaces.allowed). A single string is accepted as a one-element list. Empty/absent
        # leaves the set EMPTY → callbacks OPT-IN OFF (a submit with callback_url → 400
        # `callbacks-disabled`, per callback_policy). This is policy only — the SSRF guard +
        # per-request validation live in `callback_policy.validate_callback_url`, not here.
        cb_cfg = data.get("callbacks") or {}
        if isinstance(cb_cfg, Mapping):
            hosts = cb_cfg.get("allowed_hosts")
            if isinstance(hosts, str):
                hosts = [hosts]
            if isinstance(hosts, (list, tuple)):
                allowed_callback_hosts.update(str(h).strip() for h in hosts if str(h).strip())

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
        frozenset(allowed_callback_hosts),
    )


# --- Tier classification (§C-9) --------------------------------------------------------------
TIER_A = "tier-a"
TIER_B = "tier-b"
TIER_UNKNOWN = "unknown"

#: Tier-A verbs whose id-free/param-free shape is always cheap+synchronous.
_TIER_A_SIMPLE = frozenset(
    {"list", "get", "fetch-by-id", "create-folio", "add-to-folio", "emit-manifest", "emit-outline"}
)
#: The CHEAP (read/side-output, LLM-free) `continue-session` actions served synchronously (§C-9).
#: Commit 6 PROMOTED `fetch`/`get`/`add-to-folio`/`emit-manifest` from Tier-B to Tier-A (they mint
#: nothing / make no live call, so they belong on the synchronous door alongside `status`/`list`).
#: The ONLY Tier-B session action now is the paid `generate-next` (the async submit+poll door).
#: (`render` as a continue-session action is a minting reshape → Tier-B, still a 501 in Commit 6.)
_TIER_A_SESSION_ACTIONS = frozenset(
    {"status", "list", "fetch", "get", "add-to-folio", "emit-manifest"}
)


def classify_verb(verb: str, params: Mapping[str, Any]) -> str:
    """`TIER_A` (serve synchronously), `TIER_B` (async submit+poll — a served door or a 501
    placeholder), or `TIER_UNKNOWN` (let `invoke()` answer `unknown-verb`). Tier-B = the paid/async
    surface: the minting `render` (the Commit-8 optimistic-sync-then-202 door), the
    `continue-session` paid action `generate-next` (the Commit-6 submit door), and
    `begin-session{generate!=none}` (still a 501 placeholder — Commit 9). Every cheap
    `continue-session` action (`status|list|fetch|get|add-to-folio|emit-manifest`) is Tier-A."""
    if verb not in KNOWN_VERBS:
        return TIER_UNKNOWN
    if verb in _TIER_A_SIMPLE:
        return TIER_A
    if verb == "begin-session":
        return TIER_A if params.get("generate") in (None, "none") else TIER_B
    if verb == "continue-session":
        return TIER_A if params.get("action") in _TIER_A_SESSION_ACTIONS else TIER_B
    return TIER_B  # `render` (and any future known verb not classified Tier-A) is a Tier-B verb


def _is_generate_next_submit(verb: str, params: Mapping[str, Any]) -> bool:
    """True iff this is the `continue-session{action: generate-next}` async submit door
    (Commit 6). `render` has its OWN Tier-B door (Commit 8, `_submit_render`); the only STILL-
    DEFERRED Tier-B verb is `begin-session{generate!=none}` (Commit 9)."""
    return verb == "continue-session" and params.get("action") == "generate-next"


def _tier_b_body(verb: str, params: Mapping[str, Any]) -> dict[str, Any]:
    """The 501 placeholder for the STILL-DEFERRED Tier-B verb `begin-session{generate!=none}`
    (Commit 9). `generate-next` (`_submit_generate_next`, Commit 6) and the minting `render`
    (`_submit_render`, Commit 8) are SERVED async doors — never routed here."""
    detail = (
        f"verb {verb!r} is a Tier-B (paid/async) operation whose async submit+poll door lands in "
        "a later DR-1 commit (begin-session{generate!=none}: Commit 9). The Tier-B operations "
        "served today are continue-session{generate-next} and render (202 + poll)."
    )
    body: dict[str, Any] = {"error": "tier-b-not-served", "verb": verb, "detail": detail}
    action = params.get("action")
    if isinstance(action, str):
        body["action"] = action
    return body


# --- Tier-B jobs door (Commit 6): predictable ids · contained store · spawn · poll ----------
#
# CONTAINMENT DISCIPLINE (Commit 5c guard). The shim NEVER re-implements the GAP-9 workspace-path
# resolve-and-contain (no `pipeline.workspace_name` import, no `validate_workspace_path`, no
# `Path.resolve()` here — the static guard `test_shim_does_not_reimplement_gap9_path_validation`
# asserts it). Instead it DELEGATES the containment to the framework's own job-subsystem primitive
# `pipeline.api.jobrunner._store_for`, which applies the SAME landed GAP-9 gate `invoke()` applies
# and RAISES on an escaping name (a `ValueError` subclass) — the shim catches that and surfaces a
# 403, never guessing a path itself.


def _open_workspace(
    root: str, user: str, workspace: str, zone: str
) -> tuple[Any, Any, Any, Callable[[str], bool]]:
    """The CONTAINED (store, job_store, claims, is_done) bundle for a Tier-B submit/poll.

    Delegates the §23 resolve-and-contain to `jobrunner._store_for` (the job subsystem's
    containment authority — NOT re-implemented here); it raises a `ValueError` (WorkspaceName
    error) on an escaping `(user, zone, workspace)` tuple, which the caller maps to 403. Returns the
    full identity-bearing `WorkspaceStore` (built via `.at(root, user, workspace, zone=zone)` — the
    SAME contained leaf, so downstream `store.user`/`store.zone`/`framework_root` read loudly), the
    `JobStore`, a fresh claim registry (for `peek`), and an `is_done(target_id)` closure over the
    §22.7 authority."""
    from pipeline.api import jobrunner
    from pipeline.spine import registry_for
    from pipeline.store import WorkspaceStore, is_done

    # A minimal probe carrying only what `_store_for` reads (`.user`, `.zone`, `.workspace`,
    # `.root`) — the containment delegate. On an escaping tuple this RAISES before any store dir is
    # created.
    probe = SimpleNamespace(user=user, zone=zone, workspace=workspace, root=str(root))
    job_store = jobrunner._store_for(probe)
    store = WorkspaceStore.at(root, user, workspace, zone=zone)
    claims = registry_for(store)
    return store, job_store, claims, (lambda target_id: is_done(store, target_id))


def _default_plan_targets(
    root: str,
    user: str,
    workspace: str,
    zone: str,
    decoded: token_mod.Token,
    params: Mapping[str, Any],
) -> list[str]:
    """The PREDICTABLE target artifact-id set a `generate-next` call will materialize — resolved
    LLM-FREE (§22.2), so the job can be keyed + polled BEFORE the paid call.

    DELEGATES to the SINGLE source `session.plan_next_batch_ids` — the SAME pure selector
    `session._generate_next` uses to pick the batch it composes. There is NO forked/hand-synced
    copy of the selection here: the job key == the composed set holds BY CONSTRUCTION (returns `[]`
    on plan-stale / an empty batch, which the submit short-circuits — a job is never keyed on an
    empty target set)."""
    from pipeline.api import session

    return list(session.plan_next_batch_ids(Path(root), user, workspace, zone, decoded, params))


def _default_render_targets(store: Any, workspace: str, params: Mapping[str, Any]) -> Any:
    """The PREDICTABLE render deliverable-id (§22.2) resolved LLM-FREE — the id the paid `render`
    call will materialize, so the job can be keyed + polled BEFORE the reshape.

    DELEGATES to the SINGLE source `render.resolve_render_target` — the SAME `_resolve_fit`/
    `_resolve_deliverable` primitives the `render` handler (`_render`) materializes through, so the
    keyed/polled deliverable-id == the id the handler materializes BY CONSTRUCTION (no forked
    resolution — the render analogue of `_default_plan_targets` → `session.plan_next_batch_ids`).
    Returns the `RenderResolution` (its `.block` short-circuits a validation/not-found error; its
    `.deliverable_id` keys the job). The import is function-scoped to keep the shim module import
    light (render.py pulls in reconcile/serialize)."""
    from pipeline.api.render import resolve_render_target

    return resolve_render_target(store, params, workspace=workspace)


def _default_spawn(spec: Any, *, spawn_dir: Path) -> Any:
    """Detach the runner via `jobrunner.spawn_runner` (the default spawn seam; tests inject one)."""
    from pipeline.api.jobrunner import spawn_runner

    return spawn_runner(spec, spawn_dir=spawn_dir)


def _accepted_body(
    key: str, target_ids: Sequence[str], *, callback_registered: bool = False
) -> dict[str, Any]:
    """The N-3 202 ACK — a NEW wire shape, deliberately NOT an `invoke()` envelope (the
    "same-envelope" §21.7 invariant is amended in Commit 11). Carries everything the caller needs
    to poll: the run-family job `key` + the predictable `target_ids`, and the poll endpoint.

    W3c: when a webhook `callback_url` was accepted, a small `"callback": {"registered": true}` note
    tells the client to EXPECT a completion POST — but the `poll` block still ships, so the poll
    stays the always-available floor (a client can ignore the note and just poll)."""
    body: dict[str, Any] = {
        "status": "accepted",
        "job": {"key": key, "target_ids": list(target_ids)},
        "poll": {
            "path": POLL_PATH,
            "method": "POST",
            # §23: `user` is MANDATORY on the poll body (the isolation prefix) — the poll HANDLER
            # (`_handle_poll`) requires it exactly like `workspace`, so the advertised `needs` MUST
            # list it too, or a client polling straight from this ack would 400 `bad-request`
            # (missing `user`). The advertisement is 1:1 with what the handler enforces.
            "needs": ["workspace", "user", "key", "target_ids"],
        },
    }
    if callback_registered:
        body["callback"] = {"registered": True}
    return body


def _terminal_status_for(code: str) -> int:
    """Map a STORED terminal `code` (`pipeline.api.jobrunner` synthesis / a transport-carried code /
    an envelope code) to its poll HTTP status. Timeout-class (`re-drivable`/`timeout`) → 504
    (re-drivable, N-4); backpressure → 429; an envelope code rides the fatal table
    (unknown-verb→400, invalid-token→422, isolation-violation→403); any other terminal (a
    wiring/env `runner-failed`) → 500 (a non-re-drivable server-side failure).

    The `rate-limit-backpressure` → 429 arm is the ALWAYS-CORRECT concurrency bound (DR-1 Commit
    10 — the backstop): the subscription's OWN pushback, surfaced whenever a Tier-B call RETURNS
    the backpressure code (via the poll, and via any sync path that routes a returned code through
    this ONE mapper). It bounds real overspend regardless of the advisory pre-spawn cap's raciness
    (`_deny_over_capacity`). Any NEW inline-sync Tier-B surface MUST route its returned code through
    here so the 429 backstop keeps holding."""
    from pipeline.api.jobrunner import RE_DRIVABLE_CODE

    if code in (RE_DRIVABLE_CODE, "timeout"):
        return _HTTP_GATEWAY_TIMEOUT
    if code == "rate-limit-backpressure":
        return _HTTP_TOO_MANY_REQUESTS
    if code in _FATAL_STATUS:
        return _FATAL_STATUS[code]
    return _HTTP_INTERNAL


# --- The ADVISORY concurrency cap (DR-1 Commit 10 — Path A) ----------------------------------
#
# Path A (the advisory pre-spawn check + the always-correct 429 backstop). Before detaching a NEW
# Tier-B runner, the shim reads the account-wide in-flight PRESENCE count (`live_count()`, seeded
# by the runners' own leases — `jobrunner.run_job`) and refuses 429 + Retry-After at the cap
# (`_deny_over_capacity`). This SHEDS an obvious burst early but is BEST-EFFORT / RACY (N submits
# can all pass before any registers). The ALWAYS-CORRECT bound is the RETURNED
# `rate-limit-backpressure` → 429 backstop (`_terminal_status_for`), catching real overspend anyway.
#
# PATH B (DEFERRED — the fidelity follow-up). `live_count()` presently reflects ONLY DR-1 runners
# (they alone register a lease), so a CLI / interactive session spending against the SAME
# subscription is NOT counted and the advisory cap can pass while the account is busy. Registering
# the lease at the shared transport CHOKEPOINT (`transport.invoke_headless`) would count EVERY paid
# session — HTTP, CLI, interactive — in the same registry. Intentionally not done here (see the
# matching note in `jobrunner`); Path A + the backstop is the reconciled Commit-10 scope.


def _default_live_count(root: str) -> int:
    """The account-wide in-flight PRESENCE count from the real `PresenceRegistry` (§22.5) under
    `<root>/instance/ops/presence` — the same registry the runners' leases populate.

    ADVISORY input only. Reflects DR-1 runners (Path A); CLI/interactive sessions are not yet
    counted (Path B, deferred). FAIL-OPEN (returns 0) on any registry-read error: the cap is
    advisory and the returned-backpressure 429 is the real bound, so a telemetry I/O hiccup must
    NEVER block a submit. An absent registry dir also reads 0 (`live_count`'s own guard) — the
    default before any runner has registered."""
    from pipeline.telemetry import PresenceRegistry

    try:
        return PresenceRegistry(Path(root) / "instance" / "ops" / "presence").live_count()
    except OSError:
        return 0


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
        allowed_callback_hosts: frozenset[str] = frozenset(),
        spawn_fn: Callable[..., Any] | None = None,
        plan_targets_fn: Callable[..., Sequence[str]] | None = None,
        render_target_fn: Callable[..., Any] | None = None,
        clock_fn: Callable[[], float] | None = None,
        render_sync_wait_seconds: float | None = None,
        live_count_fn: Callable[[str], int] | None = None,
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
        #: workspace; the per-request check lives in `_ShimRequestHandler._deny_unserved_workspace`.
        self.allowed_workspaces = frozenset(allowed_workspaces)
        #: The webhook callback host allow-list (W3b). Empty = OPT-IN OFF = callbacks disabled (a
        #: submit with callback_url → 400 `callbacks-disabled`). Passed to
        #: `callback_policy.validate_callback_url` at submit-time; never a spawn-decision input.
        self.allowed_callback_hosts = frozenset(allowed_callback_hosts)
        #: Commit-6/8 Tier-B seams (all `None` → the real defaults; tests inject light stubs so the
        #: unit suite never spawns a real subprocess or resolves a live plan/render — the REAL
        #: detached spawn + real resolution are the integration harness). `spawn_fn` detaches the
        #: runner (`jobrunner.spawn_runner`); `plan_targets_fn` resolves the predictable
        #: generate-next target-id set LLM-free (`_default_plan_targets`); `render_target_fn`
        #: resolves the predictable render deliverable-id LLM-free (`_default_render_targets`);
        #: `clock_fn` is the poll/submit/render-wait clock (`time.time`) — injectable so a test can
        #: drive the job-lifetime / re-drivable windows AND the render optimistic-sync deadline.
        self.spawn_fn = spawn_fn
        self.plan_targets_fn = plan_targets_fn
        self.render_target_fn = render_target_fn
        self.clock_fn = clock_fn
        #: Commit-8 render OPTIMISTIC-SYNC hold ceiling, seconds (None → RENDER_SYNC_WAIT_SECONDS).
        #: Injectable so a test can drive the wait to 0 (a minting render → an INSTANT 202, never a
        #: real 60 s sleep in the suite). The wait is a HARD ceiling; the loop sleeps
        #: `RENDER_POLL_INTERVAL_SECONDS` between `is_done` checks and never exceeds it.
        self.render_sync_wait_seconds = (
            RENDER_SYNC_WAIT_SECONDS
            if render_sync_wait_seconds is None
            else float(render_sync_wait_seconds)
        )
        #: DR-1 Commit 10 ADVISORY concurrency-cap seam: `live_count_fn(root) -> int` reads the
        #: account-wide in-flight PRESENCE count (None → the real `_default_live_count`, backed by
        #: `PresenceRegistry`). A test seeds it AT/OVER `MAX_PARALLEL_SESSIONS` to drive the 429
        #: refusal without spawning real runners; the default reads 0 until a runner registers a
        #: lease, so the cap is transparent below-cap.
        self.live_count_fn = live_count_fn

    def live_count(self) -> int:
        """The account-wide in-flight presence count for the ADVISORY cap — the seam or the real
        `PresenceRegistry`-backed default (`_default_live_count`), against this server's root."""
        count = self.live_count_fn if self.live_count_fn is not None else _default_live_count
        return count(self.root)


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
            {"error": "method-not-allowed", "detail": f"POST {INVOKE_PATH} or POST {POLL_PATH}"},
        )

    def _handle_post(self) -> None:
        server: ShimServer = self.server  # type: ignore[assignment]

        # (1) AUTH FIRST — before the path check, before ANY body read, before dispatch, for EVERY
        #     endpoint (§C-4 N-7 + the DoS ordering; N-6: the poll carries the SAME auth gate as the
        #     submit). 401 is emitted ONLY here. An unauthenticated request (incl. an oversized/
        #     garbage body, and any /poll read) never reaches the body read or the store.
        if not self._authorized(server):
            self._respond(
                _HTTP_UNAUTHORIZED,
                {"error": "unauthorized", "detail": "a valid bearer/X-API-Key secret is required"},
            )
            return

        # (2) PATH ROUTING — /invoke (Tier-A synchronous + the Tier-B generate-next submit) and
        #     /poll (the Tier-B async poll) SHARE the auth + DoS + body gates; only the per-endpoint
        #     body handling differs.
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == POLL_PATH:
            endpoint = self._handle_poll
        elif path in ("", INVOKE_PATH):
            endpoint = self._handle_invoke
        else:
            self._respond(
                _HTTP_NOT_FOUND,
                {
                    "error": "not-found",
                    "detail": f"unknown path; POST {INVOKE_PATH} or POST {POLL_PATH}",
                },
            )
            return

        # (3) DoS guard — reject an over-cap DECLARED Content-Length BEFORE reading the body (413).
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

        # (4) The body is now bounded by the cap: read + parse it, then hand to the endpoint.
        payload = self._read_json_object(length)
        if payload is None:
            return  # `_read_json_object` already sent a 400
        endpoint(server, payload)

    def _zone_of(self, payload: Mapping[str, Any]) -> str | None:
        """The §23/Z4 zone from the request body — `payload['zone']` if present, else the
        materialized default `'default'` (the ONE chokepoint that materializes the default for this
        door). A present `zone` MUST be a non-empty string, else a 400 is sent and this returns
        `None` (the caller aborts). A returned string is the zone threaded into every store build /
        `invoke()` / `JobSpec` / allow-list check for this request."""
        if "zone" not in payload:
            return "default"
        zone = payload.get("zone")
        if not isinstance(zone, str) or not zone:
            self._bad_request(
                "'zone', when supplied, must be a non-empty string (§23; the zone segment "
                "users/<user>/zones/<zone>/workspaces/<workspace>/)"
            )
            return None
        return zone

    def _deny_unserved_workspace(
        self, server: ShimServer, user: str, workspace: str, zone: str
    ) -> bool:
        """Served-workspace ALLOW-LIST (Commit 5c, applied to BOTH /invoke and /poll — N-6). Now a
        `(user, zone, workspace)` POLICY-TRIPLE membership (§23/Z4): each allow-list entry is a
        `user/zone/workspace` string, a `user/zone/*` wildcard admitting every workspace under one
        zone, or a `user/*` wildcard admitting every zone+workspace under one user. If the list
        is CONFIGURED (non-empty), only a matching triple is served: a non-member → 403
        `workspace-not-served` BEFORE any dispatch/store access, and this returns True. If UNSET
        (default), returns False (serve any triple; the §23 resolve-and-contain gate remains the
        containment authority). TRIPLE membership ONLY — never a path re-check (an escaping
        user/zone/workspace is still refused by the delegated GAP-9/§23 gate inside `invoke()`).
        The zone is LOAD-BEARING for isolation: without it, `dave/work/acme` and
        `dave/personal/acme` would collide on the same allow-list key (the planner's Blocker 2)."""
        allowed = server.allowed_workspaces
        if (
            allowed
            and f"{user}/{zone}/{workspace}" not in allowed
            and f"{user}/{zone}/*" not in allowed
            and f"{user}/*" not in allowed
        ):
            self._respond(
                _HTTP_FORBIDDEN,
                {
                    "error": "workspace-not-served",
                    "detail": (
                        f"user/zone/workspace {user!r}/{zone!r}/{workspace!r} is not in this "
                        "shim's served allow-list (workspaces.allowed = 'user/zone/workspace', "
                        "'user/zone/*', or 'user/*' entries in instance/shim.yaml)"
                    ),
                },
            )
            return True
        return False

    def _deny_over_capacity(self, server: ShimServer) -> bool:
        """ADVISORY concurrency cap (DR-1 Commit 10 — Path A). BEFORE detaching a NEW Tier-B runner,
        read the account-wide in-flight PRESENCE count; AT/OVER `MAX_PARALLEL_SESSIONS` (§22.5) →
        refuse **429 + Retry-After**, do NOT spawn, and return True. Below the cap → return False
        (proceed). Applied only where a NEW spawn WOULD happen (`outcome.spawn`), so it never
        rejects an already-`done` idempotent re-submit or an `existing` in-flight job (no new
        spend there).

        BEST-EFFORT / RACY BY CONSTRUCTION — NOT a hard gate. N simultaneous submits can all read a
        below-cap count BEFORE any runner registers its lease (a thundering herd), so a burst may
        briefly EXCEED the cap; this only SHEDS an obvious burst early. The ALWAYS-CORRECT bound is
        the returned `rate-limit-backpressure` → 429 backstop (`_terminal_status_for`) — the
        subscription's own pushback — which catches real overspend regardless of this raciness. On a
        refusal the just-written job record is simply left un-spawned: the SAME H2 self-heal as a
        spawn failure (the record lapses with no live claim / no output → the next same-key submit
        re-drives once a slot frees). Path A counts only DR-1 runners; Path B (the transport
        chokepoint) is DEFERRED (see the module note)."""
        if server.live_count() >= MAX_PARALLEL_SESSIONS:
            self._respond(
                _HTTP_TOO_MANY_REQUESTS,
                {
                    "error": "concurrency-cap",
                    "detail": (
                        f"the account-wide in-flight session count is at the cap "
                        f"({MAX_PARALLEL_SESSIONS}, §22.5 max_parallel_sessions) — retry after the "
                        "hinted delay. This pre-spawn check is ADVISORY / best-effort (a burst may "
                        "briefly exceed it); the subscription's own rate-limit-backpressure (429) "
                        "is the always-correct bound."
                    ),
                    "retry_after_seconds": SHIM_CAP_RETRY_AFTER_SECONDS,
                },
                extra_headers={"Retry-After": str(SHIM_CAP_RETRY_AFTER_SECONDS)},
            )
            return True
        return False

    def _handle_invoke(self, server: ShimServer, payload: Mapping[str, Any]) -> None:
        """`POST /invoke`: Tier-A synchronous dispatch + the Tier-B `generate-next` submit."""
        verb = payload.get("verb")
        workspace = payload.get("workspace")
        user = payload.get("user")
        params = payload.get("params", {})
        token = payload.get("token")
        pins = payload.get("pins")
        if not isinstance(verb, str) or not verb:
            self._bad_request("'verb' is required (a non-empty string)")
            return
        if not isinstance(workspace, str) or not workspace:
            self._bad_request("'workspace' is required (a non-empty string)")
            return
        if not isinstance(user, str) or not user:
            # §23: `user` is MANDATORY (the isolation prefix) — the SAME bad-request class as a
            # missing workspace; a missing user must NEVER default (never `users/None/…`).
            self._bad_request("'user' is required (a non-empty string; the §23 isolation prefix)")
            return
        zone = self._zone_of(payload)
        if zone is None:  # a present-but-invalid `zone` (already 400'd by `_zone_of`)
            return
        if not isinstance(params, Mapping):
            self._bad_request("'params' must be a JSON object")
            return

        if self._deny_unserved_workspace(server, user, workspace, zone):
            return

        if classify_verb(verb, params) == TIER_B:
            if _is_generate_next_submit(verb, params):
                self._submit_generate_next(server, workspace, user, zone, params, token, pins)
                return
            if verb == "render":
                self._submit_render(server, workspace, user, zone, params, token, pins)
                return
            # The STILL-DEFERRED Tier-B verb `begin-session{generate!=none}` (Commit 9).
            self._respond(_HTTP_NOT_IMPLEMENTED, _tier_b_body(verb, params))
            return

        # Tier-A or unknown-verb: `invoke()` is the authority (unknown-verb → its fatal envelope).
        try:
            result = server.invoke_fn(
                verb, workspace, user, params, token, root=server.root, zone=zone
            )
        except HandlerNotWired:
            # Post-`register_api_handlers()` this is unreachable; defensive only.
            self._respond(_HTTP_INTERNAL, {"error": "handler-not-wired", "verb": verb})
            return
        self._respond(http_status_for(result), result)

    def _submit_generate_next(
        self,
        server: ShimServer,
        workspace: str,
        user: str,
        zone: str,
        params: Mapping[str, Any],
        token: Any,
        pins: Any,
    ) -> None:
        """The Tier-B `continue-session{generate-next}` SUBMIT (Commit 6): resolve the predictable
        target-ids LLM-free, `JobStore.submit` a lossy idempotency record, detach a runner, and
        return a 202 ack (or 200 on an already-done idempotent re-submit).

        W3b: an OPTIONAL `callback_url` in params is VALIDATED (operator allow-list + SSRF guard,
        `callback_policy.validate_callback_url`) BEFORE any store access or spawn — a rejection is a
        400 naming only the reason CLASS (never the URL). On accept it is threaded into BOTH the
        job record (`JobStore.submit`) and the spawn `JobSpec` so it reaches the detached runner for
        the completion wakeup (delivery is W3c). Absent ⇒ poll-only (unchanged)."""
        # (a) The idempotency_key is REQUIRED so a retry collides on ONE job (N-2; n8n: $execution
        #     .id). Missing → 400 BEFORE any store access.
        idempotency_key = params.get("idempotency_key")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            self._respond(
                _HTTP_BAD_REQUEST,
                {
                    "error": "idempotency-key-required",
                    "detail": (
                        "a Tier-B generate-next submit requires a non-empty 'idempotency_key' in "
                        "params so a retry collides on one job (§21.8/N-2; n8n supplies "
                        "$execution.id)"
                    ),
                },
            )
            return
        if token is None:
            self._respond(
                _HTTP_BAD_REQUEST,
                {
                    "error": "token-required",
                    "detail": (
                        "generate-next requires the resumption token from begin-session (§21.1)"
                    ),
                },
            )
            return

        # (a2) OPTIONAL webhook callback (W3b). VALIDATE it — operator allow-list + SSRF guard — at
        #      SUBMIT time, BEFORE any store access / plan resolution / spawn, so a bad or
        #      not-enabled callback is a 400 before any paid run. The guard is the W3a
        #      `callback_policy` (never re-implemented here); with an EMPTY allow-list callbacks are
        #      OPT-IN OFF → `callbacks-disabled`. A rejection names only the reason CLASS + the
        #      fixed rule (neither echoes the URL/host/IP — no topology/secret leak). Absent ⇒
        #      poll-only.
        callback_url = params.get("callback_url")
        if callback_url is not None:
            try:
                validate_callback_url(callback_url, allowed_hosts=server.allowed_callback_hosts)
            except CallbackPolicyError as exc:
                self._respond(
                    _HTTP_BAD_REQUEST,
                    {
                        "error": "callback-url-rejected",
                        "reason": exc.reason,
                        "detail": exc.detail,
                    },
                )
                return

        # (b) Build the CONTAINED store (delegated §23 gate — an escaping user/workspace RAISES →
        #     403).
        try:
            store, job_store, claims, is_done_fn = _open_workspace(
                server.root, user, workspace, zone
            )
        except ValueError:
            self._respond(
                _HTTP_FORBIDDEN,
                {
                    "error": "isolation-violation",
                    "detail": (
                        "user/zone/workspace does not resolve to a contained store root — "
                        "workspaces never cross (§10/§21.1/§23)"
                    ),
                },
            )
            return

        # (c) Decode the session cursor (a §20 CURSOR error is 422, NEVER 401).
        try:
            decoded = token_mod.decode(token, expected_workspace=workspace)
        except token_mod.InvalidTokenError as exc:
            self._respond(_HTTP_UNPROCESSABLE, {"error": "invalid-token", "detail": exc.detail})
            return

        # (d) Resolve the PREDICTABLE target artifact-id set LLM-free (§22.2). An empty set (all
        #     consumed / plan-stale) is nothing to generate → a 200 no-op (a job is never keyed on
        #     an empty target set).
        plan_targets = (
            server.plan_targets_fn if server.plan_targets_fn is not None else _default_plan_targets
        )
        target_ids = list(plan_targets(server.root, user, workspace, zone, decoded, params))
        if not target_ids:
            self._respond(
                _HTTP_OK,
                {
                    "status": "empty",
                    "detail": (
                        "no pending plan targets for this cursor — nothing to generate (all "
                        "consumed or plan-stale, §21.6)"
                    ),
                    "job": {"target_ids": []},
                },
            )
            return

        # (e) Submit (create-exclusive + H2 steal) → disposition → HTTP.
        now = (server.clock_fn if server.clock_fn is not None else time.time)()
        outcome = job_store.submit(
            target_ids,
            idempotency_key,
            now=now,
            is_done=is_done_fn,
            peek=claims.peek,
            callback_url=callback_url,
        )
        if outcome.disposition == "done":
            # The whole job already materialized (an idempotent re-submit after completion) → 200 +
            # the fetched output (via the existing fetch-by-id handler).
            record_targets = (
                list(outcome.record.target_ids) if outcome.record is not None else target_ids
            )
            self._respond(
                _HTTP_OK,
                self._done_body(server, workspace, user, zone, outcome.key, record_targets),
            )
            return
        if outcome.spawn:  # `spawned` or `stolen` — detach the runner (record already written).
            # ADVISORY concurrency cap (DR-1 Commit 10, Path A): at MAX_PARALLEL_SESSIONS → 429 +
            # Retry-After, do NOT spawn. Best-effort/racy; the just-written record self-heals via
            # the H2 re-drive (same as a spawn failure). The 429 backstop is the real bound.
            if self._deny_over_capacity(server):
                return
            from pipeline.api import jobrunner

            spec = jobrunner.JobSpec(
                key=outcome.key,
                verb="continue-session",
                workspace=workspace,
                user=user,
                zone=zone,
                params=dict(params),
                idempotency_key=idempotency_key,
                root=str(server.root),
                token=token,
                pins=pins,
                callback_url=callback_url,
                # W3c: the predictable target-id set (for the delivery wakeup's payload) + a FROZEN
                # snapshot of the operator allow-list, so the detached runner RE-VALIDATES the
                # callback URL at delivery (the DNS-rebinding re-check) against that list without
                # re-reading instance config.
                target_ids=tuple(target_ids),
                allowed_callback_hosts=server.allowed_callback_hosts,
            )
            spawn = server.spawn_fn if server.spawn_fn is not None else _default_spawn
            spawn(spec, spawn_dir=store.jobs_dir)
        # `spawned` / `stolen` / `existing` → the N-3 202 ack (existing = a live in-flight job). A
        # registered callback adds the W3c `callback: {registered: true}` note; poll floor stays.
        self._respond(
            _HTTP_ACCEPTED,
            _accepted_body(outcome.key, target_ids, callback_registered=callback_url is not None),
        )

    def _submit_render(
        self,
        server: ShimServer,
        workspace: str,
        user: str,
        zone: str,
        params: Mapping[str, Any],
        token: Any,
        pins: Any,
    ) -> None:
        """The Tier-B `render` SUBMIT with the OPTIMISTIC-SYNC-then-202 fast path (Commit 8):
        resolve the predictable deliverable-id LLM-free, `JobStore.submit` a lossy idempotency
        record, detach a runner, then HOLD the request up to `RENDER_SYNC_WAIT_SECONDS` polling
        OUTPUT existence — a cache-hit / fast local-pandoc serialize materializes within the wait →
        a synchronous **200 + the fetched output**; a fit that must run the paid reshape exceeds it
        → **202 + the predictable deliverable-id** (the detached runner continues; the client polls
        or gets the W3c webhook).

        `render` is token-free (§21.8) and CONTENT-ADDRESSED: the deliverable-id is a pure function
        of the request, so a retry collides on the SAME `job_key` even WITHOUT an `idempotency_key`
        (unlike generate-next, which requires one). `idempotency_key` is therefore OPTIONAL here;
        when supplied it further scopes the key and must be a non-empty string.

        GAP-10 already claims render's fit/deliverable mints, so a concurrent render is `claim-held`
        (one mints, the other re-drives by id) — never a double-spend. The optional `callback_url`
        rides the SAME W3b submit-time guard and the SAME poll door as generate-next (reuse, no
        duplication).

        THREAD-EXHAUSTION NOTE (Decision #5): the ≤`RENDER_SYNC_WAIT_SECONDS` synchronous hold ×
        `ThreadingHTTPServer` thread-per-request pins one thread per in-flight render for the wait,
        so a burst of minting renders can saturate the pool. The advisory/backstop concurrency cap
        (DR-1 Commit 10) is the mitigation — deliberately NOT added here; the bounded wait is the
        interim guard, documented on `RENDER_SYNC_WAIT_SECONDS`."""
        # (a) OPTIONAL webhook callback (W3b) — VALIDATE at SUBMIT, BEFORE any store access / spawn.
        #     Same guard as generate-next; a rejection names only the reason CLASS (never the URL).
        callback_url = params.get("callback_url")
        if callback_url is not None:
            try:
                validate_callback_url(callback_url, allowed_hosts=server.allowed_callback_hosts)
            except CallbackPolicyError as exc:
                self._respond(
                    _HTTP_BAD_REQUEST,
                    {"error": "callback-url-rejected", "reason": exc.reason, "detail": exc.detail},
                )
                return

        # (b) OPTIONAL idempotency_key — content-addressed render needs none (a retry collides on
        #     the deliverable-id); when supplied it must be a non-empty string.
        idempotency_key = params.get("idempotency_key")
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not idempotency_key
        ):
            self._respond(
                _HTTP_BAD_REQUEST,
                {
                    "error": "idempotency-key-invalid",
                    "detail": (
                        "'idempotency_key' is OPTIONAL for render (the deliverable-id is content-"
                        "addressed) but, when supplied, must be a non-empty string"
                    ),
                },
            )
            return

        # (c) Build the CONTAINED store (delegated §23 gate — an escaping user/workspace RAISES →
        #     403).
        try:
            store, job_store, claims, is_done_fn = _open_workspace(
                server.root, user, workspace, zone
            )
        except ValueError:
            self._respond(
                _HTTP_FORBIDDEN,
                {
                    "error": "isolation-violation",
                    "detail": (
                        "user/zone/workspace does not resolve to a contained store root — "
                        "workspaces never cross (§10/§21.1/§23)"
                    ),
                },
            )
            return

        # (d) Resolve the PREDICTABLE deliverable-id LLM-FREE (§22.2) via the SHARED render resolver
        #     (`render.resolve_render_target` — the SAME `_resolve_fit`/`_resolve_deliverable`
        #     primitives `_render` materializes through, no fork). A validation / not-found /
        #     coordinate short-circuit rides `.block` → 400 naming the render block (no job keyed,
        #     no spawn — nothing to run).
        render_targets = (
            server.render_target_fn
            if server.render_target_fn is not None
            else _default_render_targets
        )
        resolution = render_targets(store, workspace, params)
        if resolution.block is not None:
            self._respond(
                _HTTP_BAD_REQUEST,
                {"error": "render-blocked", "block": resolution.block.as_dict()},
            )
            return
        deliverable_id = resolution.deliverable_id
        target_ids = [deliverable_id]

        # (d2) CACHE-HIT fast path (§22.7 existence): the deliverable ALREADY materialized → serve
        #      it synchronously (200 + output) WITHOUT keying a job or spawning a runner. render is
        #      idempotent by id existence, so there is nothing to run; the key is still the
        #      deterministic `job_key` for a coherent done body / a subsequent poll.
        if is_done_fn(deliverable_id):
            from pipeline.jobs import job_key

            self._respond(
                _HTTP_OK,
                self._done_body(
                    server, workspace, user, zone, job_key(target_ids, idempotency_key), target_ids
                ),
            )
            return

        # (e) Submit (create-exclusive + H2 steal) → disposition.
        now = (server.clock_fn if server.clock_fn is not None else time.time)()
        outcome = job_store.submit(
            target_ids,
            idempotency_key,
            now=now,
            is_done=is_done_fn,
            peek=claims.peek,
            callback_url=callback_url,
        )
        # A `done` disposition SHORT-CIRCUITS: the whole deliverable already materialized (a
        # cache-hit / an idempotent re-submit after completion) → 200 + the fetched output.
        if outcome.disposition == "done":
            self._respond(
                _HTTP_OK, self._done_body(server, workspace, user, zone, outcome.key, target_ids)
            )
            return
        if outcome.spawn:  # `spawned` or `stolen` — detach the runner (record already written).
            # ADVISORY concurrency cap (DR-1 Commit 10, Path A): at MAX_PARALLEL_SESSIONS → 429 +
            # Retry-After, do NOT spawn (and never enter the optimistic-sync hold — one fewer pinned
            # thread under a burst, the §RENDER_SYNC_WAIT thread-exhaustion note). Best-effort/racy;
            # the record self-heals via the H2 re-drive. The 429 backstop is the real bound.
            if self._deny_over_capacity(server):
                return
            from pipeline.api import jobrunner

            spec = jobrunner.JobSpec(
                key=outcome.key,
                verb="render",
                workspace=workspace,
                user=user,
                zone=zone,
                params=dict(params),
                idempotency_key=idempotency_key,
                root=str(server.root),
                token=token,
                pins=pins,
                callback_url=callback_url,
                target_ids=tuple(target_ids),
                allowed_callback_hosts=server.allowed_callback_hosts,
            )
            spawn = server.spawn_fn if server.spawn_fn is not None else _default_spawn
            spawn(spec, spawn_dir=store.jobs_dir)
            # OPTIMISTIC-SYNC: hold up to RENDER_SYNC_WAIT_SECONDS polling OUTPUT existence. A fast
            # render (cache-hit fit + local pandoc serialize) materializes within the wait → 200 +
            # output; a paid reshape exceeds it → the 202 ack below.
            if self._render_wait_for_done(server, is_done_fn, deliverable_id):
                self._respond(
                    _HTTP_OK,
                    self._done_body(server, workspace, user, zone, outcome.key, target_ids),
                )
                return
        elif is_done_fn(deliverable_id):
            # `existing` — a prior submit owns the spawn/wait; SHORT-CIRCUIT (never a second wait):
            # if it has since materialized → 200 + output, else the 202 ack below.
            self._respond(
                _HTTP_OK, self._done_body(server, workspace, user, zone, outcome.key, target_ids)
            )
            return
        # `spawned`/`stolen` exceeding the wait, or an `existing` not-yet-done → the N-3 202 ack
        # with the predictable deliverable-id (the detached runner continues; the client polls or
        # gets the webhook). A registered callback adds the W3c note; the poll floor always ships.
        self._respond(
            _HTTP_ACCEPTED,
            _accepted_body(outcome.key, target_ids, callback_registered=callback_url is not None),
        )

    def _render_wait_for_done(
        self, server: ShimServer, is_done_fn: Callable[[str], bool], deliverable_id: str
    ) -> bool:
        """The render OPTIMISTIC-SYNC bounded poll (Commit 8): return True the instant the
        deliverable materializes (OUTPUT existence, §22.7), else False once the HARD ceiling
        `server.render_sync_wait_seconds` elapses. The clock is `server.clock_fn` (injectable), so a
        test drives the deadline WITHOUT a real sleep — with the wait set to 0 the first `is_done`
        miss returns False INSTANTLY (a minting render → 202), and a fast-materializing seam returns
        True on the first check (→ 200). Between checks it sleeps `RENDER_POLL_INTERVAL_SECONDS`
        (never a busy-spin) and never overruns the ceiling."""
        clock = server.clock_fn if server.clock_fn is not None else time.time
        deadline = clock() + server.render_sync_wait_seconds
        while True:
            if is_done_fn(deliverable_id):
                return True
            remaining = deadline - clock()
            if remaining <= 0:
                return False
            time.sleep(min(RENDER_POLL_INTERVAL_SECONDS, remaining))

    def _handle_poll(self, server: ShimServer, payload: Mapping[str, Any]) -> None:
        """`POST /poll {workspace, key, target_ids}` (Commit 6): resolve the job by target-id and
        map the state to HTTP. Carries the SAME auth (already applied) + allow-list + isolation
        gates as the submit (N-6) — a poll reads client job/deliverable data, so it is refused
        (401/403) exactly like the submit."""
        workspace = payload.get("workspace")
        user = payload.get("user")
        key = payload.get("key")
        target_ids = payload.get("target_ids")
        if not isinstance(workspace, str) or not workspace:
            self._bad_request("'workspace' is required (a non-empty string)")
            return
        if not isinstance(user, str) or not user:
            self._bad_request("'user' is required (a non-empty string; the §23 isolation prefix)")
            return
        zone = self._zone_of(payload)
        if zone is None:  # a present-but-invalid `zone` (already 400'd by `_zone_of`)
            return
        if self._deny_unserved_workspace(
            server, user, workspace, zone
        ):  # N-6 allow-list, same as submit
            return
        if not isinstance(key, str) or not key:
            self._bad_request("'key' is required (the run-family job key from the 202 ack)")
            return
        if not (
            isinstance(target_ids, list)
            and target_ids
            and all(isinstance(t, str) and t for t in target_ids)
        ):
            self._bad_request(
                "'target_ids' is required (the non-empty predictable-id list from the 202 ack)"
            )
            return

        # Build the CONTAINED store (delegated §23 gate — an escaping user/zone/workspace → 403).
        try:
            _store, job_store, claims, is_done_fn = _open_workspace(
                server.root, user, workspace, zone
            )
        except ValueError:
            self._respond(
                _HTTP_FORBIDDEN,
                {
                    "error": "isolation-violation",
                    "detail": (
                        "user/zone/workspace does not resolve to a contained store root — "
                        "workspaces never cross (§10/§21.1/§23)"
                    ),
                },
            )
            return

        from pipeline.jobs import JobError, resolve_job_state

        try:
            record = job_store.load(key)  # a non-run key RAISES JobError (the §22.7 keying pin)
        except JobError:
            self._bad_request("'key' is not a valid run-family job key (r-<hex16>)")
            return

        now = (server.clock_fn if server.clock_fn is not None else time.time)()
        states = [
            resolve_job_state(
                record,
                tid,
                now=now,
                is_done=is_done_fn,
                peek=claims.peek,
                job_lifetime=job_store.job_lifetime,
            )
            for tid in target_ids
        ]
        job_ref = {"key": key, "target_ids": list(target_ids)}

        # Aggregate (priority): the WHOLE job done → 200; any target still working → 202; a stored
        # terminal → the mapped failure; else re-drivable (§22.7 — no false DONE, no wedge).
        if all(state.kind == "done" for state in states):
            self._respond(
                _HTTP_OK,
                {
                    "status": "done",
                    "job": job_ref,
                    "results": self._fetch_outputs(server, workspace, user, zone, target_ids),
                },
            )
            return
        if any(state.kind == "running" for state in states):
            self._respond(
                _HTTP_ACCEPTED,
                {
                    "status": "running",
                    "job": job_ref,
                    "detail": (
                        "the job is still working (a live claim/lease or the job-lifetime window)"
                    ),
                },
            )
            return
        terminal_state = next(
            (state for state in states if state.kind == "failed" and state.terminal is not None),
            None,
        )
        if terminal_state is not None and terminal_state.terminal is not None:
            terminal = terminal_state.terminal
            status = _terminal_status_for(terminal.code)
            redrivable = status in (_HTTP_GATEWAY_TIMEOUT, _HTTP_TOO_MANY_REQUESTS)
            # The 429 BACKSTOP (DR-1 Commit 10): a surfaced `rate-limit-backpressure` — the
            # subscription's own pushback — carries a Retry-After hint so the client backs off
            # before re-driving. (A 504 timeout-class re-drive gets no hint; it re-drives at once.)
            extra_headers = (
                {"Retry-After": str(SHIM_CAP_RETRY_AFTER_SECONDS)}
                if status == _HTTP_TOO_MANY_REQUESTS
                else None
            )
            self._respond(
                status,
                {
                    "status": "failed",
                    "code": terminal.code,
                    "redrivable": redrivable,
                    "job": job_ref,
                    "terminal": {"envelope": terminal.envelope, "results": terminal.results},
                    "detail": (
                        "re-submit with the SAME idempotency_key (§22.7)"
                        if redrivable
                        else "the job failed for a non-re-drivable reason (wiring/env)"
                    ),
                },
                extra_headers=extra_headers,
            )
            return
        self._respond(
            _HTTP_CONFLICT,
            {
                "status": "re-drivable",
                "redrivable": True,
                "job": job_ref,
                "detail": (
                    "the job is not in flight and not done, with no stored reason — re-submit "
                    "with the SAME idempotency_key (§22.7)"
                ),
            },
        )

    def _done_body(
        self,
        server: ShimServer,
        workspace: str,
        user: str,
        zone: str,
        key: str,
        target_ids: Sequence[str],
    ) -> dict[str, Any]:
        """The 200 DONE body — the job's key/target-ids + the fetched output items."""
        return {
            "status": "done",
            "job": {"key": key, "target_ids": list(target_ids)},
            "results": self._fetch_outputs(server, workspace, user, zone, target_ids),
        }

    def _fetch_outputs(
        self, server: ShimServer, workspace: str, user: str, zone: str, target_ids: Sequence[str]
    ) -> list[Any]:
        """Fetch each materialized target via the EXISTING `fetch-by-id` handler (dumb hot path,
        §21.5) and merge the returned result items — the shim adds no retrieval logic of its own."""
        merged: list[Any] = []
        for target_id in target_ids:
            result = server.invoke_fn(
                "fetch-by-id",
                workspace,
                user,
                {"id": target_id},
                None,
                root=server.root,
                zone=zone,
            )
            items = result.get("results") if isinstance(result, Mapping) else None
            if isinstance(items, list):
                merged.extend(items)
        return merged

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

    def _respond(
        self,
        status: int,
        obj: Mapping[str, Any],
        *,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        body = (canonical_json_str(obj) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Optional extra headers (e.g. `Retry-After` on a 429 — the advisory cap + the backpressure
        # backstop, DR-1 Commit 10). Emitted BEFORE end_headers; never carries a secret (N-7).
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
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
    allowed_callback_hosts: frozenset[str] = frozenset(),
    spawn_fn: Callable[..., Any] | None = None,
    plan_targets_fn: Callable[..., Sequence[str]] | None = None,
    render_target_fn: Callable[..., Any] | None = None,
    clock_fn: Callable[[], float] | None = None,
    render_sync_wait_seconds: float | None = None,
    live_count_fn: Callable[[str], int] | None = None,
) -> ShimServer:
    """Build (but do not start) the shim server. `port=0` binds an ephemeral port (tests read
    `server.server_address`). The caller is responsible for wiring handlers (`serve()` does).
    `allowed_workspaces` is the Commit-5c served-workspace allow-list (empty = unset = serve any
    GAP-9-contained workspace); `allowed_callback_hosts` is the W3b webhook callback allow-list
    (empty = opt-in OFF = callbacks disabled). `spawn_fn`/`plan_targets_fn`/`render_target_fn`/
    `clock_fn`/`render_sync_wait_seconds` are the Commit-6/8 Tier-B seams (None = the real
    defaults; tests inject light stubs, and set `render_sync_wait_seconds=0` to keep the render
    optimistic-sync tests instant). `live_count_fn` is the DR-1 Commit-10 ADVISORY-cap seam (None =
    the real `PresenceRegistry`-backed `_default_live_count`; a test seeds it at/over the cap).

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
        allowed_callback_hosts=allowed_callback_hosts,
        spawn_fn=spawn_fn,
        plan_targets_fn=plan_targets_fn,
        render_target_fn=render_target_fn,
        clock_fn=clock_fn,
        render_sync_wait_seconds=render_sync_wait_seconds,
        live_count_fn=live_count_fn,
    )


def serve(*, host: str | None = None, port: int = DEFAULT_PORT, root: str = ".") -> None:
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
        allowed_callback_hosts=config.allowed_callback_hosts,
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
    callback_note = (
        f"callbacks: {len(config.allowed_callback_hosts)} approved host(s)"
        if config.allowed_callback_hosts
        else "callbacks: disabled (opt-in; no approved hosts)"
    )
    print(
        f"pipeline serve: listening on http://{bound_host}:{bound_port} "
        f"(POST {INVOKE_PATH} + POST {POLL_PATH}; auth: required, {len(config.secrets)} secret(s); "
        f"{allow_note}; {callback_note}; Tier-A synchronous; Tier-B generate-next 202+poll + "
        "render optimistic-sync-then-202; begin-session async door lands in a later DR-1 commit)",
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
