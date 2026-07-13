# optiquity-content-pipeline

An open-source **framework** for turning your own repositories into targeted content (docs +
marketing), grounded in **read-only** Graphify knowledge graphs of your source repos.

Run it on your own repos, or run it as a maintained framework with private instances that pull
your improvements non-destructively. It is content-free by design — you supply the audiences,
platforms, formats, and workspaces.

## What it does

1. Grounds on **read-only** Graphify graphs of source/client repos (source repos are never modified).
2. Selects from an extensible **nine-axis** matrix — five content dimensions (topic, persona,
   format, voice, goal) × four rendering dimensions (platform, language, output-type, presentation);
   each axis is a registry, and adding a value is a one-file change (design §5.4).
3. Fans a selection out into concrete, tracked, idempotent work items — pairing is user-driven and
   the allow-list is emergent from configuration, never vetoed by a filter (design §8).
4. Generates drafts via Claude Code agents (researcher → writer → reviewer).

## Two ways to run it (see `docs/operating-model.md`)

- **Solo:** clone, add a workspace, run it on your repos. Start with `quickstart.md` §A.
- **Framework + private instances:** you maintain this public repo; each user (including you)
  keeps a private instance that pulls framework updates via `scripts/update-from-upstream.sh`.
  The public repo stays empty of client content (enforced in CI). `quickstart.md` §B.

## Start here

- **Fast start:** `quickstart.md`
- **Operating rules for AI sessions:** `CLAUDE.md`
- **Public/private model + updates:** `docs/operating-model.md`
- **Design (the single SSOT):** `docs/design.md` — `docs/mission.md` is retained as product/PRD
  context, superseded on design specifics (see its banner + `docs/design.md` Appendix B).
- **Agents/skills sourcing & build manifest:** `docs/agents-and-skills-sourcing.md`
- **Setup runbook:** `docs/bootstrap.md`
- **Claude Code usage:** `docs/claude-code-usage.md`

## Durable rules (see CLAUDE.md)

1. Source/client repos are **read-only, always**.
2. Each client repo gets a **workspace** (`workspaces/<client>/`) — never a repo per client.
3. The **tracking spreadsheet is SSOT**; `state.md` is a derived convenience doc.
4. The public framework repo stays **empty of client content**.
5. Instances **extend by adding files**; never edit framework files.

## Layout

```
optiquity-content-pipeline/
├── CLAUDE.md · README.md · quickstart.md · LICENSE · .gitignore
├── state.md                      # derived from spreadsheet SSOT; tracked for history
├── docs/design.md                # THE design SSOT
├── docs/{mission,operating-model,bootstrap,claude-code-usage,ops-workflow}.md · docs/archive/
├── topics/ personas/ formats/ voices/ goals/          # content-dimension registries (§5)
├── platforms/ languages/ output-types/ presentations/ # rendering-dimension registries (§5)
├── content-kinds/ sources/ render-targets/ recipes/ folio-types/  # supporting registries
│   └── <each>/_schema.yaml + *.template.* (framework) + framework-default & instance entries
├── workspaces/
│   ├── workspace.template/          # the only workspace in public; copy to workspaces/<client>/
│   └── <client>/                    # instance-owned, per client (gitignored in public)
├── instance/{profile,defaults}.template.*   # copy to instance/*.md|*.yaml (private)
├── pipeline/                     # the pipeline package (framework mechanism)
├── scripts/{pipeline,update-from-upstream,check-no-content,schema-lint,migrate}.*
├── .claude/{agents,skills}/      # project-scoped framework-ops agents/skills
└── .github/workflows/{ci,guard}.yml   # tests + keeps public repo content-free
```

License: MIT.
