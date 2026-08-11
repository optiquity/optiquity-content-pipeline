# Getting started

## Requirements

Before a first run, put these in place:

- **The runtime toolchain.** The mission's dependency table names Homebrew... Node.js (current LTS)... Claude Code CLI... Python (current supported 3.x)... uv or pipx... Tailscale... n8n. The pinned Python dependencies live in the repo's pyproject.toml... uv.lock.
- **Pandoc for the render pass.** The serialize step is rendered by Pandoc, and Pandoc's binary version and AST api-version are pinned — a hard build requirement.
- **At least one bound source.** The pipeline reads client repos three ways; all read-only — a Graphify graph by path, an MCP query, or a wiki export. The matching readers live in pipeline/adapters/... folder.py, fsast.py, graphify.py, mock.py.
- **MCP servers: none required.** Of those three bound-source options, a graph by path is the default and needs no MCP server — the pipeline reads the graph straight from a file. Running `graphify-mcp` is optional: it serves a graph on an always-on host so a workstation can query it across machines over Tailscale (`code-review-graph` (CRG) is an optional alternative). See [Claude Code usage](../claude-code-usage.md#read-only-source-access-the-core-safety-pattern) for that optional setup.
- **The Claude subscription transport.** Composition runs through Claude Code: the pipeline is a headless Claude Code CLI invocation authenticated on the Claude SUBSCRIPTION — never API keys, never ANTHROPIC_API_KEY.

## Setup

These steps take you from an empty checkout to one grounded artifact.

1. **Initialize the control-plane repo.** The bootstrap guide's B5 — optiquity-content-pipeline repo init step runs git init... git commit -m... # only on approval — the commit waits for your approval.
2. **Declare instance-global defaults.** Instance config lives under instance/ (defaults.template.yaml, defaults.yaml, ops/, profile.template.md); copy the profile template into place, as in cp instance/profile.template.md instance/profile.md. Voice, language, and output-type defaults are read as scope defaults by load_scope_defaults into a ScopeDefaults record.
3. **Create a workspace.** Each client gets an isolated workspace under your user prefix. Scaffold it with `uv run pipeline workspace new self --user <user>` (§23) — that seeds the workspace from the shared `templates/workspace/` blueprint and creates the user namespace on first use (the equivalent by hand is `mkdir -p users/<user>/workspaces && cp -R templates/workspace users/<user>/workspaces/self`). List them with `pipeline workspace list` and remove one with the safe-by-default `pipeline workspace delete`. The workspace name — and its owning user — are required arguments throughout the engine: for example, CascadeEnv.__init__ takes user and workspace parameters, and every CLI command that names --workspace also requires --user.
4. **Register a source pool.** Source definitions live in sources/; the engine turns registered entries into a pool with build_pool.
5. **Verify read-only grounding.** From the pipeline repo, confirm read-only grounding works with a smoke query — graphify query --graph <repo>/graphify-out/graph.json 'smoke test' returns grounded results.
6. **Invoke a recipe.** Recipes bundle a genre's settings; the shipped ones are in recipes/ (explainer-post.md, project-manual.md). Invoking one produces the first grounded artifact.

## Usage

The command-line surface is the launcher `scripts/pipeline` (run it directly, or as `uv run
pipeline`). It is a set of **friendly doors** onto the engine's verbs — readable flags in, a plan and
a spend count out — built so nothing paid happens by accident. Every command and its exact flags are
catalogued in the generated [CLI reference](../reference/cli.md).

**The money-safety model.** `preview` spends nothing; `generate` is a **dry-run by default** (it
prints the plan and stops); only adding **`--go`** spends, and spend is your Claude **subscription**
quota, never an API key. Every dry-run ends with `spend-scope: N paid artifact(s)`, so you approve a
number before anything runs.

**The minimal first run.** With a workspace and one authored topic in place, preview the plan (free),
then drive it:

```bash
# 1. See the plan and the exact paid count — spends nothing (--user is required with --workspace):
uv run pipeline preview --topic <your-topic> --user <you> --workspace myrepo

# 2. Same plan as a free dry-run, then add --go to actually compose:
uv run pipeline generate --topic <your-topic> --user <you> --workspace myrepo          # dry-run, spends nothing
uv run pipeline generate --topic <your-topic> --user <you> --workspace myrepo --go     # the only path that spends
```

`preview`/`generate` default to the `explainer-post` recipe; name content axes explicitly with
`--persona/--format/--voice/--goals` and route the output with `--platform/--language/--output-type/
--presentation`. The rendered deliverable lands in your workspace; read it there.

**The rest of the authoring surface.** Saving a reusable recipe, saving and replaying an exact
selection, scaffolding a new entry, driving an editable outline, and discovery (`list`/`get`) all
live on this same friendly CLI — see the [Authoring and running guide](authoring.md) for the full
walkthrough, and the [attribute reference](../reference/attributes.md) for every tunable field.

- **Serve over HTTP.** `pipeline serve` starts the HTTP shim, which makes the same verbs reachable by a remote cloud orchestrator behind a login (see *HTTP access* in the [Interfaces guide](interfaces.md#http-access-cloud-orchestrators)). It refuses to start without an auth secret configured.
- **Operator subcommands.** A few round out the surface: an SSOT mirror (`pipeline ssot derive-state`), a read-only drift report (`pipeline drift-report`), and the attribute-reference generator (`pipeline docs attributes`).

---
[← Manual home](../../README.md) · Previous: [Concepts](concepts.md) · Next: [Architecture](architecture.md)
