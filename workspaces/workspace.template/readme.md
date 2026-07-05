# workspace.template — one workspace per client repo

Copy this directory to `workspaces/<client>/` to onboard a client repo (your own repos are clients
too, e.g. `workspaces/self/`). Everything for that client lives here and never leaks into another
workspace (CLAUDE.md durable rule 2).

```bash
cp -R workspaces/workspace.template workspaces/<client>
```

## Layout

- `source.md` — read-only paths to this client's local repo checkout(s) and their `graphify-out/`
  graph paths. Graphs live in the client repo checkout (gitignored there), **not** here.
- `topics/` — topic entries for this client (seeded from the source graph's `GRAPH_REPORT.md`).
- `select/` — selection / schedule configs (one-off manifests and scheduled configs).
- `output/` — generated docs, per item (tracked, for history).
- `overrides/` (optional) — client-specific persona/platform/format variants; the resolver
  prefers these over the shared defaults for this workspace.

## Rule

The pipeline is **read-only** toward client repos: it only reads their graph by the path recorded in
`source.md`. It never writes to a client repo and stores no graphs of its own.
