# Template — Topic entry

Copy this to `workspaces/<client>/topics/<id>.md` and fill it in. Topics are **client-scoped**
(grounded in that client's source repo) — the framework ships **no** topic entries; they are
per-client editorial data. Adding a topic is a one-file change (design §5.4 / §3.2). **Never edit
this template downstream** — copy it.

The co-located **`topics/_schema.yaml` is the authoritative field list**; design **§5.2** defines
Topic as **what it is about, and why it matters**. Topic owns the subject matter (the entry body
prose names the subject; factual grounding comes from the graph at ground time, §6, never from
config) plus **`why`** — the editorial significance. It never touches audience (Persona), structure
(Format), destination (Platform), or objective (Goal). Scope, not a mechanism, separates
universal-archetype from bespoke: a shared `topics/` root vs. `workspaces/<client>/topics/` (§10).

## The entry (YAML frontmatter + prose body)

```markdown
---
id: <slug>                       # stable id = filename stem (§7.4 slug)
provenance: instance             # topics are per-client editorial data (never framework); private → `x-` prefix (§11.4)
schema_version: 1
why: >-                          # why this subject matters now, and to whom (editorial significance)
---

# <id> — Topic entry

Prose body: name the subject/angle and candidate hooks. The grounding (source repo, commit, graph
anchors) is recorded in the workspace's `source.md` and selection configs, not in this entry.
```

## Seeding procedure

1. Build the client repo's graph in its local checkout (`graphify extract .` → `graphify-out/`,
   gitignored there); the pipeline reads it by path.
2. Read the graph's `GRAPH_REPORT.md`; each god-node/community is a candidate topic, and the
   suggested questions are candidate angles.
3. Create one topic file per kept candidate under `workspaces/<client>/topics/`.
