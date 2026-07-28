---
provenance: framework
---

# n8n example workflows — driving the pipeline over its HTTP shim

Two importable [n8n](https://n8n.io) workflows that drive the optiquity-content-pipeline **HTTP
shim** (the remote door started with `pipeline serve`; see
[`docs/guide/interfaces.md`](../../docs/guide/interfaces.md) → "HTTP access"). Both call the
token-free **`render`** verb and collect the result two different ways:

| File | Flow | Needs inbound reachability? | Use when |
|---|---|---|---|
| [`pipeline-poll.json`](./pipeline-poll.json) | **Poll** — submit, then ask "ready yet?" on a timer | **No** | Always works — the baseline. Localhost / LAN / self-hosted n8n. |
| [`pipeline-webhook.json`](./pipeline-webhook.json) | **Webhook** — submit with a `callback_url`, pause, resume on the pipeline's wake-up ping | **Yes** (public, allow-listed host) | Lower latency, but only when n8n is publicly reachable and allow-listed. |

These are **generic** examples: every deployment-specific value is a placeholder —
`http://127.0.0.1:8787` (the shim's loopback default), `<SHIM_SECRET>` (your bearer token),
`<WORKSPACE>`, `<ARTIFACT_ID>`. No client content.

> **Hand-authored to n8n's export convention.** n8n publishes **no formal schema** for its workflow
> export files, so this JSON is written to the well-known export shape by hand. **Import it into your
> own n8n to confirm it loads, then re-export** to let n8n normalize node `typeVersion`s and internal
> ids to whatever your instance runs. Grounded against the n8n **2.x** line (Task Runners / Canvas
> UI); node `typeVersion`s here (HTTP Request `4.2`, IF `2.2`, Wait `1.1`, Set `3.4`) must match a
> version your instance supports — re-exporting fixes any drift.

---

## 1. Import

Editor UI → three-dots menu (upper right) → **Import from File** → pick the `.json`. (You can also
paste the JSON onto the canvas with Cmd/Ctrl+V, or, self-hosted,
`n8n import:workflow --input=pipeline-poll.json`.)

## 2. Auth — one Header Auth credential, reused by every HTTP node

The shim is **fail-closed**: it refuses to start without a secret, and only a valid secret gets past
the door (a missing/wrong secret → **401**). Create **one** n8n credential and select it on every
HTTP Request node in the workflow:

- Credentials → New → **Header Auth**
- **Name:** `Authorization`  ·  **Value:** `Bearer <SHIM_SECRET>`
- (Alternatively **Name** `X-API-Key` · **Value** `<SHIM_SECRET>` — the shim accepts either.)

The imported nodes reference a credential named `Optiquity Shim Header Auth` with a placeholder id;
n8n will prompt you to pick your own on first open. Keeping the secret in a credential (not in a node
body) keeps it out of the exported JSON.

## 3. The `render` verb and its params

`render` is the recommended Tier-B call for a demo because it is **token-free and content-addressed**
— no `begin-session` handshake, and a retry collides on the same job key. The submit body (already
filled into the **Submit render** node) is:

```json
{
  "verb": "render",
  "workspace": "<WORKSPACE>",
  "params": {
    "item": "<ARTIFACT_ID>",
    "platform": "linkedin",
    "language": "en",
    "output_type": "docx",
    "presentation": "plain"
  }
}
```

All five `params` are required. `item` is the artifact id to render; `platform` / `language` /
`output_type` / `presentation` are registry slugs (the values shown are generic framework defaults —
swap in the coordinates you want). `output_type` also accepts the spelling `output-type`.

> To **generate** new content instead of re-rendering an existing artifact, the verb is
> `continue-session` with `params.action = "generate-next"`. That path needs a prior `begin-session`
> call (a quick verb that returns a `token`) plus a mandatory `idempotency_key` (n8n's own
> `{{ $execution.id }}` is the recommended value). These examples use `render` to stay to a single
> call.

## 4. What comes back — 200, 202, and the poll states

A `render` submit returns **one of two** shapes, so both workflows branch on the HTTP status code
(the nodes enable **"Include Response Headers and Status"** and **"Never Error"** so a 202/4xx does
not hard-fail the node):

- **200 done** — a cache-hit or a fast local serialize finished within the shim's sync wait. The
  result is already in `body.results`.
- **202 accepted** — a paid reshape is running. The body carries the **job handle** to poll with:
  `body.job.key` and `body.job.target_ids`.

`POST /poll` (body `{workspace, key, target_ids}`) then resolves to:

| Poll result | Meaning | Workflow does |
|---|---|---|
| **200** `done` | output ready | read `body.results` |
| **202** `running` | still working | wait, poll again |
| **409 / 429 / 504** `failed` / `re-drivable` | timeout-class, backpressure, or nothing-live | surface `body.code` + `body.redrivable`; re-drive with the same request |

Each `results[]` entry is a `ResultItem` — `{item, status, ids, output:{path?|bytes?}, ...}`.
Publishing/storing the output is outside the pipeline's scope; wire the **Surface result** node into
whatever downstream you like.

---

## 5. Poll vs. Webhook — and the webhook constraint you must know

**Poll (`pipeline-poll.json`) is the floor and always works.** n8n makes only *outbound* calls, so it
needs no inbound reachability and no extra shim config. Start here.

**Webhook (`pipeline-webhook.json`) is lower-latency but has one real, load-bearing constraint.** The
flow submits `render` with `callback_url = {{ $execution.resumeUrl }}` and pauses on a **Wait (On
Webhook Call)** node. When the job settles, the pipeline POSTs a **wake-up** (event `job.done` /
`job.failed`, plus the same `poll` pointer — a nudge, **never** the result, and it carries no auth
secret). n8n resumes and still fetches the finished output through the authenticated `/poll`.

The constraint is the shim's **callback guard**, which is **opt-in and fail-closed**:

1. **Callbacks are OFF by default.** With an empty allow-list, any `callback_url` submit is refused
   **400 `callbacks-disabled`**. The operator must populate `callbacks.allowed_hosts` in
   `instance/shim.yaml` (see [`instance/shim.template.yaml`](../../instance/shim.template.yaml)).
2. **The allow-list is by exact host (or `host:port`).**
3. **SSRF block (fail-closed).** The callback host must resolve **only to public, globally-routable
   addresses**. Loopback, link-local (incl. `169.254.169.254` cloud-metadata), private
   (`10/172.16/192.168`), unique-local, multicast, and reserved ranges are **always refused** — even
   if allow-listed — and re-checked at delivery time.

**Consequence:** a **localhost / LAN / behind-NAT** n8n **cannot** receive the callback — its resume
URL host resolves to a non-global address and the pipeline refuses it. For the webhook flow you need
either:

- **n8n Cloud** — its resume-URL host is a public HTTPS host; add that host to
  `callbacks.allowed_hosts` and it works.
- **Self-hosted n8n on a public domain / tunnel** — expose n8n publicly and set `WEBHOOK_URL` (or
  `N8N_HOST`/`N8N_PROTOCOL`/`N8N_PORT`) so the resume URL is a reachable public host; add that host to
  the allow-list.

If your n8n is not publicly reachable, **use the poll flow** — it needs none of this.

### Wait (On Webhook Call) node settings

- **HTTP Method:** `POST` (the pipeline POSTs the wake-up).
- **Authentication:** `None`. The wake-up carries no secret; the security boundary is the shim's
  *outbound* allow-list + SSRF guard, not this inbound node. (The follow-up `/poll` still presents
  your Header Auth credential.)
- The wake-up body arrives as `$json.body` — `{ event, job:{key,workspace,target_ids}, poll,
  [code, redrivable] }`.
- **100-second note:** a Wait-on-webhook resume request that doesn't respond within ~100 s fails
  (524). The pipeline's wake-up returns fast (the heavy work already happened server-side), so this
  is fine; the *overall* wait can still be long because the node pauses rather than holding a request
  open.

---

## Verify before trusting it

Because the export shape is hand-authored (§ note above), the first thing to do after import is open
each node and confirm: the credential is selected on every HTTP node; `typeVersion`s resolved; the
expressions (`$json.statusCode`, `$json.body.job.key`, `$execution.resumeUrl`, and the webhook
node's `$json.body.*`) show real values on a test run. Then **re-export** to capture your instance's
canonical form.
