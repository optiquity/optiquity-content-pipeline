# Interfaces

## User-facing surface

The surface has four parts: the selection inputs, the verbs, the store, and the run-layer overrides.

- **Inputs.** A run is described by a SelectionRequest. Its axes expand into content coordinates via content_combinations and into render coordinates via render_coordinates.
- **Verbs.** The API modules live in pipeline/api/ (discovery.py, fetch.py, folio_verbs.py, invoke.py, manifest.py, render.py, results.py, session.py, token.py). The compose verbs are begin-session and its continue-session{generate-next, only}; the render side is the token-free render verb. External hand-off is carried by emit-manifest for side: external targets.
- **Store.** Persistent state is a WorkspaceStore, threaded through the engine — for example, _persist(doc, request, *, store: WorkspaceStore,...) writes into it.
- **Run-layer overrides.** Overrides bound at session start enter through CascadeEnv.__init__, which accepts an OverrideSet; individual values are ValueBindings parsed by parse_value_bindings.

### HTTP access (cloud orchestrators)

The verbs above are reached two ways. Locally you shell out to `scripts/pipeline` (the CLI door) or call `invoke()` in-process. The **HTTP shim** is the remote door: a small web server, started with `pipeline serve`, that lets a cloud automation tool — n8n Cloud, Make, Zapier, Google Workflows, and the like — drive the very same operations over the internet, behind a login. Those tools cannot run a command on your machine; they can only call a URL, so the shim gives them one. It is not a second implementation — every request is translated straight onto the same `invoke()` the CLI uses.

A caller sends `POST /invoke` with a small JSON body — `{verb, workspace, params}`, optionally a session `token` and a `callback_url` — plus an auth header (`Authorization: Bearer <secret>` or `X-API-Key: <secret>`). What comes back depends on how expensive the verb is:

- **Quick verbs answer instantly.** The cheap, model-free operations — listing and fetching, creating and adding to folios, emitting a manifest or an outline, opening a session — run then and there and return the same JSON envelope the CLI would. (These are the *Tier-A* verbs.)
- **Slow verbs return "working on it."** The paid, model-driven operations — generating the next artifact, and rendering — usually take longer than one web request allows, so the shim replies **202 Accepted** with a small *job handle* (a key plus the ids the job will produce) instead of the result. (These are the *Tier-B* verbs. A render whose output is already cached is the exception — it can come straight back with the result.) The tool then chooses how to collect the result:
  - **Poll** — ask "is it ready yet?" by sending `POST /poll` with the job handle. It answers 200 with the output when done, 202 while still running, or an error if the job failed. Polling always works; it is the floor.
  - **Webhook (callback)** — if the submit carried a `callback_url`, the pipeline sends that URL a short wake-up ping the moment the job settles. The ping is only a nudge, never the result — the tool still fetches the finished output through the authenticated poll. A tool that ignores callbacks simply polls.

So a typical remote generation is: open a session (a quick verb, returns a token) → submit `generate-next` with that token (202 + a job handle) → poll, or wait for the webhook, then fetch the artifact.

**Safety is fail-closed throughout.** `pipeline serve` refuses to start unless an auth secret is configured — it never accepts an anonymous caller. It binds to loopback (`127.0.0.1`) by default; exposing it to the network is a deliberate choice that expects a TLS/auth proxy in front. It serves only workspaces on an operator allow-list, and only calls webhook addresses on a separate, opt-in allow-list — never internal or cloud-metadata addresses, and it re-checks the address again at delivery time. It also caps how many paid jobs run at once. Every knob lives in `instance/shim.template.yaml`; copy it to `instance/shim.yaml` and fill it in.

For the full wire contract — every endpoint, status code, and error/status token — plus the language-neutral client surface that the Python and C++ wrappers both implement, see the [Clients guide](clients.md).

---
[← Manual home](../../README.md) · Previous: [Architecture](architecture.md) · Next: [Clients](clients.md)
