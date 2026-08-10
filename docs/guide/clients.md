# Clients

This page is the **single neutral source** every language client reads. It has two halves:

1. **The wire contract** — the endpoints, the auth header, the request/response shapes, and the
   exact sets of error/status tokens the HTTP shim can put on the wire.
2. **The canonical client surface** — the method set, the outcome semantics, the poll state
   machine, and the substrate rules that **every** language wrapper (Python, C++, and any future
   one) implements identically.

The wire contract is authoritative for the token vocabulary. No wrapper — Python included — is
allowed to be "more up to date" than another by peeking at an internal server constant; they all
read this page. An automated check (`tests/test_clients_doc_contract.py`) imports the server's own
constants and fails if the token blocks below drift from what the code can actually emit.

Each wrapper lives in its own language's natural distribution home — the Python reference wrapper
ships in-package at `pipeline/client/` (so `from pipeline.client import Client` and
`python -m pipeline.client` work), and the C++ proof-of-concept ships as a worked example at
`examples/cpp/`, beside `examples/n8n/`. Both are framework-provenance and carry no client content.

---

## Part 1 — The wire contract

### 1.1 Endpoints and auth

The shim exposes exactly two POST endpoints:

- `POST /invoke` — run a verb (Tier-A returns the result; Tier-B returns a job handle).
- `POST /poll` — ask whether a submitted Tier-B job is ready.

Every request carries an auth secret in one of two headers (the server checks `Authorization`
first, then `X-API-Key`, constant-time against a rotation set):

```text
Authorization: Bearer <secret>
X-API-Key: <secret>
```

`pipeline serve` is **fail-closed**: it refuses to start with no secret, binds to loopback by
default, and serves only allow-listed workspaces (§23 — each allow-list entry is a
`user/zone/workspace` triple, a `user/zone/*` wildcard admitting every workspace under one zone, or a
`user/*` wildcard admitting every zone+workspace under one user). **BREAKING (config format):** this
key changed from the pre-zone `user/workspace` form — a deployed `instance/shim.yaml` must migrate
its `workspaces.allowed` entries to the zoned form (or a `user/*` wildcard). A missing/invalid secret
is `401` (`unauthorized`).

### 1.2 The invoke request

`POST /invoke` takes a small JSON object:

```json
{
  "verb": "render",
  "workspace": "acme",
  "user": "acme-corp",
  "zone": "default",
  "params": { "item": "deck-intro", "platform": "linkedin",
              "language": "en", "output_type": "post" },
  "token": null,
  "pins": null
}
```

- `verb`, `workspace`, and `user` are top-level and required. `user` is the §23 isolation prefix
  (the triple addresses `users/<user>/zones/<zone>/workspaces/<workspace>/`) — a missing/empty `user`
  is a `400 bad-request`, exactly like a missing workspace, and is **never** defaulted.
- `zone` is the **optional** §23 zone segment between `user` and `workspace`. When present it MUST be
  a non-empty string; when omitted the door materializes `default`. It is ECHOED in the reply so a
  caller can confirm which zone the call ran in (read it back with `echoed_zone`, §2.2a). Same-named
  workspaces in different zones are DISTINCT, store-isolated workspaces.
- `params` carries the per-verb inputs. **`idempotency_key` and `callback_url`, when used, live
  inside `params`** (not at the top level) — `generate-next` requires a non-empty
  `params.idempotency_key`; `render` is content-addressed so its key is optional.
- `token` is a session cursor (for `continue-session{generate-next}`); `pins` carries commit pins.

### 1.3 Tier-A — the synchronous envelope

Cheap, model-free verbs (list/get, folio verbs, `emit-manifest`, `begin-session{generate=none}`)
run inline and return the same JSON **envelope** the CLI produces:

```json
{ "ok": true, "verb": "list", "workspace": "acme", "user": "acme-corp" }
```

`ok` reflects **whole-invocation** validity only (a per-item `block` in `results[]` never flips
`ok`). A whole-invocation failure is `ok: false` with a `code`/`message`, and the HTTP status comes
from the fatal-code map: `unknown-verb` → `400`, `invalid-token` → `422`,
`isolation-violation` → `403`; any other fatal envelope defaults to `400`.

A refused request that never reaches the envelope comes back as a small `{ "error": "<token>" }`
body with an appropriate 4xx/5xx status (for example `{ "error": "unauthorized" }` on a bad secret,
`{ "error": "render-blocked", "block": { ... } }` on a refused render). The complete set of these
sync error tokens is:

<!-- wire-tokens:sync-errors:begin -->
```text
bad-request
callback-url-rejected
concurrency-cap
handler-not-wired
idempotency-key-invalid
idempotency-key-required
internal-error
invalid-token
isolation-violation
method-not-allowed
not-found
payload-too-large
render-blocked
tier-b-not-served
token-required
unauthorized
workspace-not-served
```
<!-- wire-tokens:sync-errors:end -->

### 1.4 Tier-B — the 202 job handle

Paid, model-driven verbs (`continue-session{generate-next}`, `render`) usually take longer than one
web request allows, so the shim replies **`202 Accepted`** with a job handle instead of the result:

```json
{
  "status": "accepted",
  "job": { "key": "r-0123456789abcdef", "target_ids": ["<deliverable-id>"] },
  "poll": { "path": "/poll", "method": "POST", "needs": ["workspace", "user", "key", "target_ids"] }
}
```

The one exception: a `render` whose output is already materialized comes straight back `200` with
the result (a cache hit), skipping the job entirely. A client cannot tell from the request whether
it will get `200` or `202`, so it must handle both.

### 1.5 The poll states

`POST /poll` takes `{ "workspace", "user", "key", "target_ids" }` (the `user` prefix is required
here too, §23; the rest come from the 202 `job` + `poll.needs`). Pass the optional `zone` to poll in
the SAME zone the submit ran in — the 202 `job` block echoes it, so a client threads it straight
through. Its reply carries a `status` field; the full set of async status values is:

<!-- wire-tokens:async-status:begin -->
```text
accepted
done
empty
failed
re-drivable
running
```
<!-- wire-tokens:async-status:end -->

The states a client branches on:

| Reply | HTTP | Meaning | Client action |
|---|---|---|---|
| `status: done` | `200` | the whole job materialized (`results[]` present) | return the `Result` |
| `status: running` (or `accepted`) | `202` | a live claim/lease or the job-lifetime window | sleep, poll again |
| `status: failed` | `4xx`/`5xx` | a stored terminal failure (`code` + `redrivable` + `terminal`) | map to an outcome |
| `status: re-drivable` | `409` | not in flight, not done, no stored reason | re-submit the SAME key |
| `429` on submit **or** poll | `429` | concurrency cap / backpressure (`Retry-After` header) | sleep `Retry-After`, retry |

A `504` (a timeout-class terminal) is a re-drivable failure; a `429` carries a `Retry-After` and is
also re-drivable.

### 1.6 Terminal failure codes

A `status: failed` poll body carries a top-level `code`:

```json
{ "status": "failed", "code": "runner-failed", "redrivable": false,
  "job": { "key": "r-...", "target_ids": ["..."] },
  "terminal": { "envelope": { ... }, "results": [ ... ] } }
```

The **known, mapped** terminal `code` vocabulary — the codes a client may branch on — is the union
of the server's envelope-fatal codes, the runner's synthesized codes (`runner-failed`,
`re-drivable`), the transport `timeout`, `rate-limit-backpressure`, and every nondeterministic
block-capable generation code (any block-capable taxonomy code except the four deterministic blocks
the completeness sweep re-derives):

<!-- wire-tokens:terminal-codes:begin -->
```text
asset-ref-invalid
asset-ref-uncontained
body-raw-markup-forbidden
capability-infeasible
citation-unresolved
grounding-uncovered
invalid-override
invalid-token
isolation-violation
not-found
rate-limit-backpressure
re-drivable
runner-failed
section-conformance-violation
timeout
unknown-action
unknown-verb
```
<!-- wire-tokens:terminal-codes:end -->

**Open-string boundary (read this).** `code` is an **open string**, not a closed enum. The set above
is the known/mapped vocabulary the anti-drift check binds to, but the transport/session layer can
carry an unlisted structured code (for example `api-error`) that the server maps to a generic
terminal `500`. A wrapper therefore **surfaces the raw `code`** and branches on `redrivable` /
`terminal`, never on an exhaustive `code` switch — an unrecognized code is reported, never a crash.

### 1.7 The webhook (wakeup-only)

If a submit carried `params.callback_url`, the pipeline POSTs that URL a small **wakeup** the moment
the job settles — never the result itself. The payload carries an `event`, the `job` identity, and a
`poll` pointer; on failure it adds `code` + `redrivable`. The client is only nudged; it still fetches
the finished output through the authenticated poll. The two event names are:

<!-- wire-tokens:callback-events:begin -->
```text
job.done
job.failed
```
<!-- wire-tokens:callback-events:end -->

A tool that ignores callbacks simply polls — the poll is always the floor.

---

## Part 2 — The canonical client surface

This is what **every** language wrapper implements, in that language's own idiom. Naming/casing,
argument-passing, blocking-vs-async, and the error channel (Python `raise`, C++ `throw` on C++17
grounds, a Go/Rust `return` — all conformant) are per-language; the method **set**, the parameter
**set**, the **semantics**, the poll **state machine**, and the outcome **set** are canonical.

### 2.1 Construction / configuration

```text
Client(base_url, secret,
       api_key_header = false,   // false -> "Authorization: Bearer"; true -> "X-API-Key"
       timeout        = 30,      // per-request seconds
       poll_interval  = 1.0,     // initial poll cadence
       max_poll_seconds = 1320)  // overall await deadline (~ the job lifetime)
```

Config is env, identically across languages: `OPTIQUITY_SHIM_URL` + `OPTIQUITY_SHIM_SECRET`.

### 2.2 The raw layer (1:1 with the wire)

```text
invoke(verb, workspace, user, params, token = null, pins = null, zone = "default") -> Response
poll(workspace, user, key, target_ids, zone = "default")                           -> Response
list(type, workspace, user, filters = null, zone = "default")                      -> Response
get(type, id, workspace, user, zone = "default")                                   -> Response
```

The generic `invoke(verb, ...)` forwards any verb, so the raw layer covers the whole startup-wired
surface with no per-verb code. `user` is the §23 isolation prefix and is **required** on every call
(it rides in the request body beside `workspace`); `Response` is the normalized value type below.

### 2.2a The zone argument (§23)

Every method carries an optional **`zone`** argument — the §23 addressing segment between `user` and
`workspace` (`users/<user>/zones/<zone>/workspaces/<workspace>/`) that groups a user's workspaces. It
**defaults to `default`**, so a single-zone deployment never sets it; a multi-zone caller passes the
zone it wants (there is no client-side S4 refusal — the programmatic default is always `default`, so
a multi-zone caller MUST name the zone). It rides the request body next to `workspace` on every door
and is **echoed** back in the reply. Read the echoed zone with the pure helper:

```text
echoed_zone(body) -> string | null   // the zone the door resolved (envelope.zone, else a flat zone); null if none echoed
```

Same-named workspaces in different zones are DISTINCT, store-isolated workspaces — the fully-qualifying
key is the `(user, zone, workspace)` triple. (This is store isolation only; per-zone *spend* isolation
is a transport-build item, not delivered here.)

### 2.3 The ergonomic async layer + the poll state machine

```text
begin_session(workspace, user, selection, overrides=null, pins=null,
              generate="none", idempotency_key=null, zone="default")  -> SessionHandle
        // generate MUST be "none": the one-call begin-session{generate!=none} is a 501
        // deferred convenience. The supported path is two calls.

generate_and_wait(workspace, user, token, idempotency_key,   // idempotency_key REQUIRED
                  batch_size=null, only=null, callback_url=null, zone="default", ...)  -> Result
        // drives the served continue-session{generate-next} door.

render_and_wait(workspace, user, item, platform, language, output_type,
                presentation=null, force_reconcile=false,
                idempotency_key=null, callback_url=null, zone="default")  -> Result
        // render is content-addressed + token-free; idempotency_key OPTIONAL.
```

Each `zone` defaults to `default` and rides the body next to `workspace` (see §2.2a); a poll resolves
in the SAME zone the submit ran in, and the wakeup event carries the zone so a callback fetch lands in
the right zone.

The `_and_wait` methods **resolve at the terminal outcome or the deadline**. Every wrapper runs this
identical state machine:

```text
submit -> Response
loop until deadline (max_poll_seconds):
    200 & body.status == "done"   -> outcome: Result (job done)
    202 (accepted/running)        -> sleep(backoff); poll
    429                           -> sleep(Retry-After INTEGER seconds); poll   (submit OR poll)
    504                           -> outcome: JobTimeout(redrivable=true)
    409 (re-drivable)             -> re-submit with the SAME idempotency_key; continue
    4xx/5xx (failed)              -> outcome: JobFailed(code, redrivable, terminal)
    backoff = min(backoff * factor, cap)
on deadline -> outcome: JobTimeout(redrivable=true)
```

Two invariants every wrapper honors: `Retry-After` is **integer delta-seconds** (a plain int parse
is safe); a **`409` re-drive reuses the same `idempotency_key`** (so a retry is exactly-once by
construction — never charged twice).

### 2.4 The outcome set

| Outcome | Fields | Wire trigger |
|---|---|---|
| `Result` | `json` (the done body) | `200 {status: done, job, results}` |
| `JobTimeout` | `redrivable` | `504`, or the await deadline |
| `JobFailed` | `code, redrivable, terminal` | `4xx/5xx {status: failed, code, redrivable, terminal}` |
| `RenderBlocked` | `block` | `400 {error: render-blocked, block}` |

The four outcomes are identical everywhere; only the delivery channel is idiom (raise/throw/return).
`code` values come from the wire contract above (Part 1.6), not from any per-language constant.

### 2.5 The normalized-Response rule

Every wrapper's transport primitive funnels **all** HTTP statuses into one `Response` value type
`{ status: int, headers: map, json: object }`. **A 4xx/5xx is a `Response`, not a thrown transport
error.** Only a genuine connection failure / timeout is an error. (In C++ libcurl already returns the
status; in Python `urllib.error.HTTPError` is caught and returned as a `Response`, and a no-redirect
opener surfaces a `3xx` as a `Response` carrying its `Location` rather than following it.) HTTPS uses
the platform's default verified TLS context — never an unverified one.

### 2.6 The Retry-After / malformed-body fallback rule

Stated once here so every language implements it identically:

- **`Retry-After` absent / blank / non-integer on a `429`** → fall back to the backoff cadence;
  never crash on `int(None)`.
- **Non-JSON / empty body on any reply** → `Response.json = null` (a guarded parse), status
  preserved; never crash the JSON decode.
- **Truncated / malformed `done` body** → raise (or return) a defined client error, not an uncaught
  crash.

### 2.7 Webhook receipt

```text
parse_callback(payload) -> CallbackEvent      // pure/static; validates event in {job.done, job.failed}
client.fetch_after_callback(event) -> Result  // authenticated "you've been woken, now fetch"
```

Ship **parse + fetch only, no receiver server**. The payload is wakeup-only, so forcing the explicit
fetch is honest.

### 2.8 No-invent rule

`render_and_wait` collapses "200 at submit" (cache hit) and "202-then-poll" into one `Result`. The
wire carries **no** `from_cache` / `cost` fact. **No wrapper may synthesize a cache/cost field** —
omit even an observed-latency bool.

---

## Part 3 — A curl walkthrough (the render slice)

The load-bearing shared algorithm — submit → 202 → poll(Retry-After) → done — against a running
`pipeline serve`. Set `OPTIQUITY_SHIM_URL` and `OPTIQUITY_SHIM_SECRET` first.

**1. Submit a render.** A fresh (uncached) item returns a `202` job handle:

```sh
curl -sS -X POST "$OPTIQUITY_SHIM_URL/invoke" \
  -H "Authorization: Bearer $OPTIQUITY_SHIM_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"verb":"render","workspace":"acme","user":"acme-corp",
       "params":{"item":"deck-intro","platform":"linkedin",
                 "language":"en","output_type":"post"}}'
# -> 202 {"status":"accepted","job":{"key":"r-...","target_ids":["..."]},"poll":{...}}
```

**2. Poll with the job handle.** Repeat until the status leaves `running`, sleeping the backoff
cadence (or the integer `Retry-After` on a `429`):

```sh
curl -sS -X POST "$OPTIQUITY_SHIM_URL/poll" \
  -H "Authorization: Bearer $OPTIQUITY_SHIM_SECRET" \
  -H 'Content-Type: application/json' \
  -d '{"workspace":"acme","user":"acme-corp","key":"r-...","target_ids":["..."]}'
# -> 202 {"status":"running",...}      (keep polling)
# -> 429 + Retry-After: N              (sleep N seconds, then poll)
# -> 200 {"status":"done","results":[...]}   (done — this is the result)
# -> 504 {"status":"failed","code":"...","redrivable":true,...}   (re-submit same key)
```

A cache hit short-circuits step 1 straight to `200 {"status":"done",...}` — the same `Result` a
client returns, with no poll loop. The `generate-next`, webhook, and discovery slices follow the same
submit/poll shape and are verified by hand for the MVP.

---
[← Manual home](../../README.md) · Previous: [Interfaces](interfaces.md) · Next: [Extending it](extending.md)
