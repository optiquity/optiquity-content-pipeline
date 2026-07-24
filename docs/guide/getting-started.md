# Getting started

## Requirements

Before a first run, put these in place:

- **The runtime toolchain.** The mission's dependency table names Homebrew... Node.js (current LTS)... Claude Code CLI... Python (current supported 3.x)... uv or pipx... Tailscale... n8n. The pinned Python dependencies live in the repo's pyproject.toml... uv.lock.
- **Pandoc for the render pass.** The serialize step is rendered by Pandoc, and Pandoc's binary version and AST api-version are pinned — a hard build requirement.
- **At least one bound source.** The pipeline reads client repos three ways; all read-only — a Graphify graph by path, an MCP query, or a wiki export. The matching readers live in pipeline/adapters/... folder.py, fsast.py, graphify.py, mock.py.
- **The Claude subscription transport.** Composition runs through Claude Code: the pipeline is a headless Claude Code CLI invocation authenticated on the Claude SUBSCRIPTION — never API keys, never ANTHROPIC_API_KEY.

## Setup

These steps take you from an empty checkout to one grounded artifact.

1. **Initialize the control-plane repo.** The bootstrap guide's B5 — optiquity-content-pipeline repo init step runs git init... git commit -m... # only on approval — the commit waits for your approval.
2. **Declare instance-global defaults.** Instance config lives under instance/ (defaults.template.yaml, defaults.yaml, ops/, profile.template.md); copy the profile template into place, as in cp instance/profile.template.md instance/profile.md. Voice, language, and output-type defaults are read as scope defaults by load_scope_defaults into a ScopeDefaults record.
3. **Create a workspace.** Each client gets an isolated workspace, made by copying the template: cp -R workspaces/workspace.template workspaces/self. The workspace name is a required argument throughout the engine — for example, CascadeEnv.__init__ takes a workspace parameter.
4. **Register a source pool.** Source definitions live in sources/; the engine turns registered entries into a pool with build_pool.
5. **Verify read-only grounding.** From the pipeline repo, confirm read-only grounding works with a smoke query — graphify query --graph <repo>/graphify-out/graph.json 'smoke test' returns grounded results.
6. **Invoke a recipe.** Recipes bundle a genre's settings; the shipped ones are in recipes/ (explainer-post.md, project-manual.md). Invoking one produces the first grounded artifact.

## Usage

The command-line surface is the launcher in scripts/... pipeline, dispatched by main. Its subcommands map to the tasks below.

- **Resolve a plan.** Ask for the parallel plan when you open a session: it is obtained via begin-session(want_parallel_plan = true) — no new verb. The plan lays out the two waves so you can see every work item before running any.
- **Generate an artifact.** Composition is wave 0, keyed by artifact-id, driven by continue-session{generate-next, only}: open the session, then call continue-session generate-next per item. Under the hood a thread runs run_thread, starting from a SelectionRequest; a ready-made one is available from demo_selection for a first run. The demo thread and MVP demo are wired as the subcommands _cmd_demo_thread and _cmd_mvp_demo.
- **Drive a genre with an authored outline.** To shape one artifact, attach an outline through the selection's outlines map; the request resolves it with outline_for, and the map is normalized by _normalize_outlines. The outline drives structure and emphasis without adding any new publishable fact.
- **Render and read the deliverable.** Rendering is the token-free wave 1, run by the _cmd_render subcommand (with _cmd_invoke for external hand-off). Output files are named by output_filename.
- **Serve over HTTP.** `pipeline serve` starts the HTTP shim, which makes the same verbs reachable by a remote cloud orchestrator behind a login (see *HTTP access* in the [Interfaces guide](interfaces.md#http-access-cloud-orchestrators)). It refuses to start without an auth secret configured.
- **Operator subcommands.** Two round out the surface: an SSOT command _cmd_ssot and a drift-report command _cmd_drift_report.

---
[← Manual home](../../README.md) · Previous: [Concepts](concepts.md) · Next: [Architecture](architecture.md)
