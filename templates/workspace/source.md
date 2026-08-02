# Source repos for this client (READ-ONLY)

Each client repo is checked out locally. You run Graphify on that checkout; its `graphify-out/` is
gitignored inside the client repo, so it never dirties that repo. This pipeline **never writes** to
these paths — it only **reads the graph by path**. No graphs are stored in this pipeline repo.

## Repos

| Client repo (read-only local checkout) | Graph path (read by the pipeline) | Last graphed (commit / date) |
|---|---|---|
| `/path/to/client-repo-a` | `/path/to/client-repo-a/graphify-out/graph.json` | — |
| `/path/to/client-repo-b` | `/path/to/client-repo-b/graphify-out/graph.json` | — |

## Notes

- Prefer graph queries over reading raw source files (design §6).
- Rebuild a graph in the client-repo checkout when its source changes (`graphify extract .`, run in
  that checkout); record the commit here.
