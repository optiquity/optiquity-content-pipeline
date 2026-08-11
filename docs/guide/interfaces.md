# Interfaces

## User-facing surface

The surface has four parts: the selection inputs, the verbs, the store, and the run-layer overrides.

- **Inputs.** A run is described by a SelectionRequest. Its axes expand into content coordinates via content_combinations and into render coordinates via render_coordinates.
- **Verbs.** The API modules live in pipeline/api/ (discovery.py, fetch.py, folio_verbs.py, invoke.py, manifest.py, render.py, results.py, session.py, token.py). The compose verbs are begin-session and its continue-session{generate-next, only}; the render side is the token-free render verb. External hand-off is carried by emit-manifest for side: external targets.
- **Store.** Persistent state is a WorkspaceStore, threaded through the engine — for example, _persist(doc, request, *, store: WorkspaceStore,...) writes into it.
- **Run-layer overrides.** Overrides bound at session start enter through CascadeEnv.__init__, which accepts an OverrideSet; individual values are ValueBindings parsed by parse_value_bindings.

### Local operator CLI

Locally, the friendly way in is `scripts/pipeline` (also `uv run pipeline`) — English-ish flags onto the same verbs, built so nothing paid happens by accident (`generate` is a dry-run until you add `--go`, and spend is subscription-only, never an API key). The doors, one line each:

- **`pipeline workspace new` / `list` / `delete`** — the workspace lifecycle: scaffold a new workspace from the `templates/workspace/` blueprint, list existing workspaces (with a topic-count / has-output summary), or remove one. Each takes an optional `--zone` selector (default `default`; see [Zones](#zones-grouping-a-users-workspaces)). `delete` is safe-by-default — it needs confirmation (type-the-name or `--yes`) and refuses a workspace holding generated output unless you also pass `--force`. All local file ops; nothing paid.
- **`pipeline zone new` / `list` / `delete`** — the zone lifecycle: create a new zone (a per-zone workspace home), list a user's zones with a workspace count, or remove one. `zone delete` is the recursive two-tier form — it removes the zone AND every workspace under it, is stricter because recursive (a `--force` gate over any contained workspace holding output), and never deletes through a symlink. All local file ops; nothing paid.
- **`pipeline user new`** — create an empty per-user namespace (`users/<user>/zones/`) on its own.
- **`pipeline preview`** — plan-only: the effective settings, the plan, and the exact paid count. Spends nothing.
- **`pipeline generate`** — dry-run by default; `--go` drives the plan and is the only thing that spends.
- **`pipeline recipe new`** — author a reusable, *partial* recipe (a saved set of axis picks + tweaks).
- **`pipeline entry new`** — scaffold a new persona/format/voice/… entry from a self-documenting skeleton.
- **`pipeline outline emit` / `drive`** — realize an editable outline, then drive it (same as `generate --outline`).
- **`pipeline list` / `get`** — read-only discovery over a workspace.
- **`pipeline docs attributes`** — regenerate the [attribute reference](../reference/attributes.md).
- **`pipeline sources ingest`** — fetch + cache grounding **sources** into a workspace (feeds — RSS/Atom, SEC EDGAR, GDELT — and a Common Crawl web source, plus an agentic `research` loop). Feeds are **free** (out-of-band, no spend); the `research` kind **spends** and is therefore dry-run until `--go`, subscription-only. Acquired content is cached under the workspace (gitignored) as INFERRED leads or, for characterized primary sources like EDGAR, publishable facts.

Full walkthrough with runnable examples: the [Authoring and running guide](authoring.md).

### HTTP access (cloud orchestrators)

The verbs above are reached two ways. Locally you shell out to `scripts/pipeline` (the CLI door) or call `invoke()` in-process. The **HTTP shim** is the remote door: a small web server, started with `pipeline serve`, that lets a cloud automation tool — n8n Cloud, Make, Zapier, Google Workflows, and the like — drive the very same operations over the internet, behind a login. Those tools cannot run a command on your machine; they can only call a URL, so the shim gives them one. It is not a second implementation — every request is translated straight onto the same `invoke()` the CLI uses.

A caller sends `POST /invoke` with a small JSON body — `{verb, workspace, user, params}`, optionally a `zone`, a session `token`, and a `callback_url` — plus an auth header (`Authorization: Bearer <secret>` or `X-API-Key: <secret>`). The `user` field is the §23 isolation prefix and is required alongside `workspace` (a missing `user` is a `400 bad-request`); the optional `zone` field selects which of a user's zones the call runs in and defaults to `default` when omitted (see [Zones](#zones-grouping-a-users-workspaces) below). What comes back depends on how expensive the verb is:

- **Quick verbs answer instantly.** The cheap, model-free operations — listing and fetching, creating and adding to folios, emitting a manifest or an outline, opening a session — run then and there and return the same JSON envelope the CLI would. (These are the *Tier-A* verbs.)
- **Slow verbs return "working on it."** The paid, model-driven operations — generating the next artifact, and rendering — usually take longer than one web request allows, so the shim replies **202 Accepted** with a small *job handle* (a key plus the ids the job will produce) instead of the result. (These are the *Tier-B* verbs. A render whose output is already cached is the exception — it can come straight back with the result.) The tool then chooses how to collect the result:
  - **Poll** — ask "is it ready yet?" by sending `POST /poll` with the job handle. It answers 200 with the output when done, 202 while still running, or an error if the job failed. Polling always works; it is the floor.
  - **Webhook (callback)** — if the submit carried a `callback_url`, the pipeline sends that URL a short wake-up ping the moment the job settles. The ping is only a nudge, never the result — the tool still fetches the finished output through the authenticated poll. A tool that ignores callbacks simply polls.

So a typical remote generation is: open a session (a quick verb, returns a token) → submit `generate-next` with that token (202 + a job handle) → poll, or wait for the webhook, then fetch the artifact.

**Safety is fail-closed throughout.** `pipeline serve` refuses to start unless an auth secret is configured — it never accepts an anonymous caller. It binds to loopback (`127.0.0.1`) by default; exposing it to the network is a deliberate choice that expects a TLS/auth proxy in front. It serves only allow-listed workspaces (each entry a `user/zone/workspace` triple, a `user/zone/*` wildcard admitting every workspace under one zone, or a `user/*` wildcard admitting every zone+workspace under one user, §23 — this key changed from the pre-zone `user/workspace` form, a BREAKING config change for a deployed `instance/shim.yaml`), and only calls webhook addresses on a separate, opt-in allow-list — never internal or cloud-metadata addresses, and it re-checks the address again at delivery time. It also caps how many paid jobs run at once. Every knob lives in `instance/shim.template.yaml`; copy it to `instance/shim.yaml` and fill it in.

For the full wire contract — every endpoint, status code, and error/status token — plus the language-neutral client surface that the Python and C++ wrappers both implement, see the [Clients guide](clients.md).

## Zones (grouping a user's workspaces)

A **zone** groups one user's workspaces (for example a `work` zone and a `personal` zone), sitting between the user and the workspace in the store root `users/<user>/zones/<zone>/workspaces/<workspace>/`. It is a pure addressing prefix — it changes *where* a workspace lives, never the value cascade (design §10/§23). Zone selection rides the SAME rails as `--user`/`user` at every door, defaults to `default`, and the **resolved zone is echoed back** so a caller can confirm which zone the call ran in.

Per-door zone selection, with a concrete example each:

| Door | How you select the zone | Default when omitted | Example |
|---|---|---|---|
| **CLI** (`scripts/pipeline`) | the `--zone <zone>` flag | `default` (but a spend verb refuses — see S4) | `pipeline generate --user dave --zone work --workspace acme --topic launch --go` |
| **HTTP shim** (`POST /invoke`, `/poll`) | a `zone` field in the JSON body | `default` (the door materializes it) | `{"verb":"generate-next","user":"dave","zone":"work","workspace":"acme", ...}` |
| **Client library** (Python / C++) | a `zone` argument on every call | `default` (the arg's default) | `client.begin_session(workspace="acme", user="dave", zone="work", selection=…)` |
| **n8n / cloud orchestrator** | the `zone` field threaded on the HTTP body it POSTs | `default` | an n8n Set node adds `zone: "work"` alongside `user`/`workspace` on the `/invoke` body |
| **Admin / lifecycle** | `zone new` / `zone list` / `zone delete` (+ `--zone` on `workspace new`/`list`/`delete` and `entry`) | `default` | `pipeline zone new work --user dave` then `pipeline workspace new acme --user dave --zone work` |

**The S4 spend guard (CLI + served spend doors).** A **spend** verb — `preview`, `generate`, and `outline drive` (whose `--go` actually spends), plus the served `generate-next`/`render` — invoked by a user who owns **more than one zone** REFUSES if the zone is omitted: it lists the available zones, exits 1 (the CLI), and spends nothing, rather than silently pick `default` and spend in the wrong zone. A single-zone user, and every (non-spending) Tier-A verb, keep the friendly `default`; an explicit `zone` (even `default`) is always honored. As of the transport-selection build this guard fires **uniformly at the shared spend chokepoint** the CLI and the served HTTP doors both traverse, so a multi-zone caller on the programmatic spend doors (HTTP shim, client library, n8n) must pass the `zone` too — a missing `zone` still defaults to `default` only on a **non-spending** Tier-A call. The CLI keeps a friendly early refusal for nicer messaging. See [`docs/transport.md`](../transport.md).

**The echo.** Every door echoes the resolved zone back: the Tier-A result envelope carries a `zone` field, the 202/poll job block carries `zone`, the friendly CLI preview header prints `zone=<zone>`, and the client library exposes it via `echoed_zone(...)`.

**Same workspace name across zones is ALLOWED.** `users/dave/zones/work/workspaces/acme` and `users/dave/zones/personal/workspaces/acme` are two DISTINCT, store-isolated workspaces — there is no clash to reject. Workspace ids are **store-scoped**: they are resolved within a single `(user, zone, workspace)` store, never against a global name index, so the fully-qualifying key is the `(user, zone, workspace)` triple. This is safe because each store is a separate on-disk subtree behind the same resolve-and-contain isolation gate. What this restructure gives you is **store isolation**; per-zone *spend* isolation (same-named zones drawing on separate transport keys and weekly caps) is now **delivered** by the transport-selection build — assign a key + weekly cap per `zone:<u>/<z>` scope; see [`docs/transport.md`](../transport.md).

---
[← Manual home](../../README.md) · Previous: [Architecture](architecture.md) · Next: [Clients](clients.md)
