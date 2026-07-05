# Template — Topic entry

Copy to `workspaces/<client>/topics/<id>.md`. Topics are **client-scoped** (grounded in that
client's source repo). **Seeded from the source repo's Graphify `GRAPH_REPORT.md`** (god-nodes =
central concepts, communities = clusters, suggested questions = angles), then extended by hand.
**Never edit this template file downstream.** Serialization deferred (D1).

## Fields

- **id** — stable identifier.
- **title** — the subject/angle.
- **client** — the workspace this belongs to.
- **source_repo** — which source repo this is grounded in (read-only).
- **graph_anchors** — the god-node(s)/community/ies in that repo's graph this maps to.
- **summary** — 1–2 lines on what there is to say.
- **angles** — candidate angles/hooks (seed from GRAPH_REPORT suggested questions).
- **status** — active / draft (keeps fanout manageable — mission §10.4 D7).
- **notes**.

## Seeding procedure

1. Build the client repo's graph in its local checkout (`graphify-out/`, gitignored there); the
   pipeline reads it by path.
2. Read the graph's `GRAPH_REPORT.md`; each god-node/community is a candidate topic.
3. Create one topic file per kept candidate under `workspaces/<client>/topics/`.
