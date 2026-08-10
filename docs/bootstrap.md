# Bootstrap runbook — Phase 0

Authored setup sequence. Claude Code executes this **plan-gated**: present a plan for each
lettered block, get approval, run it, verify, update `state.md`, then continue. Do not batch
blocks without approval. All commands are reference — **verify current flags/versions against
each tool's docs before running** (mission §10.4 D3).

Tool sources, licenses, and roles are in `docs/mission.md` §6–§7.

---

## B1 — Prerequisites (per machine: always-on host first, then workstation)

Goal: a working runtime for Claude Code CLI + Graphify.

```bash
# Homebrew (if absent)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Runtimes + tooling (current supported versions; verify Claude Code's Node requirement)
brew install node python pipx
pipx ensurepath
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv (fast python tool installer)
```

Verify: `node --version`, `python3 --version`, and Claude Code CLI launches. Record in `state.md` (P0.1/P0.2).

---

## B2 — Graphify install

```bash
uv tool install graphifyy        # PyPI name has two y's; CLI stays `graphify`
graphify install                 # registers skill/hooks for the assistant
graphify --help                  # verify + learn current subcommands/flags
```

Confirm the actual `extract` (build the graph), `export wiki` (wiki snapshot), `query`, and the
MCP entry point (`graphify-mcp`, not a `serve` subcommand) from `--help` output; note any
deviations from mission §6.2 in `state.md` (feeds decision D4). (P0.3)

---

## B3 — First workspace + graph (source repo stays read-only)

Create a workspace (your own repos are clients too):

```bash
uv run pipeline workspace new self --user <user>   # scaffolds users/<user>/zones/default/workspaces/self (use any <workspace-name>)
```

(`workspace new` creates the user namespace on first use and seeds the workspace from
`templates/workspace/`; the equivalent by hand is `mkdir -p users/<user>/zones/default/workspaces &&
cp -R templates/workspace users/<user>/zones/default/workspaces/self`.)

**Zones (grouping a user's workspaces).** A workspace lives at
`users/<user>/zones/<zone>/workspaces/<workspace>/` — a **zone** sits between the user and the
workspace and groups a user's workspaces (e.g. `work` vs. `personal`). It defaults to `default`, so a
single-zone setup never types it; when you want a second grouping, add `--zone <zone>` to
`workspace new`/`list`/`delete` (a brand-new zone is auto-created and announced), or create it
first with `pipeline zone new <zone> --user <user>`. Zones give **store isolation** (same-named
workspaces in different zones are distinct); per-zone spend/key isolation is a later transport-build
feature. Full per-door detail: the [Interfaces guide → Zones](guide/interfaces.md#zones-grouping-a-users-workspaces).

> **Upgrading an EXISTING instance to the zoned layout — pull → migrate → use.** A pre-zone instance
> (`users/<user>/workspaces/<workspace>/`) migrates in a fixed order: **(1) pull** the framework
> (`scripts/update-from-upstream.sh`) — this brings the zoned code and the additive `.gitignore`
> BEFORE any data moves; **(2) migrate** by running `scripts/migrate-to-zones-layout.sh` ONCE (it
> re-homes every user's workspaces under `zones/default/`, is idempotent, and never deletes data);
> **(3) use** — post-migration commands resolve zone `default` and land on the moved homes. Neither
> half is destructive alone. A deployed HTTP shim also needs its `instance/shim.yaml` allow-list keys
> migrated from `user/workspace` to `user/zone/workspace` (a BREAKING config change — see the
> [Operating model → Zone migration](operating-model.md#migrating-the-on-disk-layout-users-then-zones)).
> A brand-new Phase-0 install skips all of this — `workspace new` writes the zoned layout directly.

Each client repo is checked out locally. Build its Graphify graph **in that checkout** — the
`graphify-out/` is gitignored inside the client repo, so it never dirties it. The pipeline stores
no graphs; it just reads the graph by path.

```bash
cd /path/to/client-repo-checkout
graphify extract .                # produces graphify-out/ here (gitignored in the client repo)
graphify export wiki              # optional agent-crawlable wiki snapshot (needs the extract first)
# add 'graphify-out/' to that repo's .gitignore if it isn't already
```

Record the client-repo checkout path + its `graphify-out/graph.json` path in
`users/<user>/zones/default/workspaces/self/source.md`. (P0.4/P0.5)

---

## B4 — Read-only smoke test

From the optiquity-content-pipeline repo (or any location), confirm read-only grounding works:

```bash
graphify query "high-level architecture and main components" \
  --graph /path/to/your-checked-out-client-repo/graphify-out/graph.json --budget 3000
```

Pass criterion: returns grounded nodes/edges with source locations and confidence tags. (P0.6)

Optional cross-machine check (workstation → host over Tailscale) once the `graphify-mcp` flags are
confirmed from B2:

```bash
# On the always-on host (bind to Tailscale/private interface only — see mission §9):
graphify-mcp /path/to/first-client-repo/graphify-out/graph.json   # MCP entry point (needs graphifyy[mcp])
# Then point the workstation's Claude Code MCP config at it. Verify exact flags first.
```

---

## B5 — optiquity-content-pipeline repo init

```bash
cd /path/to/optiquity-content-pipeline
git init
git add -A
git commit -m "chore: bootstrap optiquity-content-pipeline control plane"   # only on approval
```

Confirm chezmoi management per your standard workflow. (P0.7)

---

## Exit criteria (Phase 0 done)

- Prereqs + Graphify verified on at least the always-on host.
- One client repo has a committed graph + wiki, and the read-only smoke test passes.
- optiquity-content-pipeline repo initialized and chezmoi-managed.

Next: **prove one thread** (STATE P1.0) before building the full registry/fanout machinery.
