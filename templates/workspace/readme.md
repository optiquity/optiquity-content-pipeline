# workspace blueprint (templates/workspace/) — one workspace per client repo

Scaffold a workspace from this blueprint to onboard a client repo (your own repos are clients too,
e.g. `users/<user>/workspaces/self/`). Everything for that workspace lives there and never leaks into
another workspace (CLAUDE.md rule 2; design §10 — scope is encoded by location). This blueprint is
the framework-owned, owner-agnostic template that ships in the public framework; instantiated
`users/<user>/workspaces/<workspace>/` trees are instance-owned (gitignored in public). Full layout:
design §23.

```bash
pipeline workspace new <workspace> --user <user>   # the friendly path — stamps this blueprint
# equivalently, by hand:
cp -R templates/workspace users/<user>/workspaces/<workspace>
```

## What ships in the template (hand-authored inputs)

- `source.md` — read-only paths to this client's local repo checkout(s) and their `graphify-out/`
  graph paths. Graphs live in the client repo checkout (gitignored there), **not** here.
- `defaults.yaml` — this client's scope-default surface (L3, design §12.2): where this client's
  baseline differs from the instance globals. Everything in it is optional; see its header.
- `topics/` — client-scoped topic entries (seeded from the source graph's `GRAPH_REPORT.md`).
- `select/` — selection / schedule configs (one-off manifests and scheduled configs).
- `output/` — generated docs + `output/manifests/`, per item (tracked, for history).

## Client-scoped customization (design §10, §12)

Customize per client by **adding** files here, never by editing shipped framework entries:

- client-scoped registry entries under `users/<user>/workspaces/<workspace>/<dimension>/` (e.g. a
  client-only `personas/x-…md`), using the reserved `x-` prefix (§11.4);
- `extends:` partials that field-merge over a shipped `provenance: framework` entry (§10 rule 2);
- baseline values in `defaults.yaml` (§12.2).

There is no `overrides/` directory — run-layer overrides are the ephemeral L6 run layer only
(§12.5), not persisted here.

## Pipeline-created stores (design §23; appear at generation time)

The pipeline writes these under `users/<user>/workspaces/<workspace>/` as it runs; they are not
hand-authored and are not pre-created in the template:

- `artifacts/` · `deliverables/` — IR-canonical/fitted/AST/bytes + render-bindings (§18).
- `folios/<folio-id>/members/<artifact-id>` — marker-per-member folio records (§13.3).
- `claims/` — the claim/lease coordination table (§22.3). **Gitignored** — a lease is only
  meaningful on the machine and in the moment that wrote it (`.gitignore`:
  `users/*/workspaces/*/claims/`).

## Rule

The pipeline is **read-only** toward client repos: it only reads their graph by the path recorded in
`source.md`. It never writes to a client repo and stores no graphs of its own.
