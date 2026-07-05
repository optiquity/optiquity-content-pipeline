# optiquity-content-pipeline

An open-source **framework** for turning your own repositories into targeted content (docs +
marketing), grounded in **read-only** Graphify knowledge graphs of your source repos.

Run it on your own repos, or run it as a maintained framework with private instances that pull
your improvements non-destructively. It is content-free by design — you supply the audiences,
platforms, formats, and workspaces.

## What it does

1. Grounds on **read-only** Graphify graphs of source/client repos (source repos are never modified).
2. Selects from an extensible matrix of **topics × personas × platforms × formats**.
3. Fans a selection out into concrete, tracked, idempotent work items.
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
- **Design & requirements:** `docs/mission.md`
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
├── docs/{mission,operating-model,agents-and-skills-sourcing,bootstrap,claude-code-usage}.md
├── personas/  platforms/  formats/    # *.template.* (framework) + your entries (instance)
├── topics/topic.template.md           # topics are scoped to workspaces/<client>/topics/
├── workspaces/
│   ├── workspace.template/          # copy to workspaces/<client>/
│   └── <client>/{topics,select,output}/   # instance-owned, per client
├── instance/profile.template.md  # copy to instance/profile.md (private)
├── scripts/{update-from-upstream,check-no-content}.sh
├── .claude/{agents,skills}/      # project-scoped pipeline agents/skills
└── .github/workflows/guard.yml   # keeps public repo content-free
```

License: MIT.
