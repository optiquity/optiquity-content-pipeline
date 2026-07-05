# CLAUDE.md — operating instructions

You are working inside the **optiquity-content-pipeline** control plane (framework). Read `state.md`
(if present) and `docs/mission.md` before acting. These rules apply for the whole session.

## Durable rules (never violated)

1. **SOURCE / CLIENT REPOS ARE READ-ONLY — ALWAYS.** Never write, edit, commit, move, or run
   any write/destructive command in any source or client repo. The pipeline only **reads the
   Graphify graph by path**. Each client repo is checked out locally and graphed there; its
   `graphify-out/` is gitignored inside the client repo and read by path. **No graphs are stored
   in this pipeline repo.**
2. **CLIENT ISOLATION VIA WORKSPACES.** Every client repo gets a workspace: `workspaces/<client>/`.
   A client's docs, topics, metadata, and output live only under its workspace and must never
   leak into another. There is **one** repo with many workspaces — never a separate repo per
   client. (This instance's own repos are clients too, e.g. `workspaces/self/`.)
3. **SINGLE SOURCE OF TRUTH.** The **tracking spreadsheet is the SSOT** for status/progress.
   `state.md` is **always a derived convenience document** — a session-facing mirror of the
   spreadsheet, never an authority. If they disagree, the spreadsheet wins; update `state.md`
   to match, never the reverse.
4. **PUBLIC FRAMEWORK STAYS EMPTY OF CLIENT CONTENT.** If this checkout is the public framework
   repo, never add populated registries, `instance/profile.md`, or anything under
   `workspaces/*/` other than `workspace.template/`. (A CI guard enforces this; don't rely on it alone.)
5. **EXTEND, DON'T EDIT (framework vs. instance).** Downstream instances **add** files
   (populated registries, workspaces, PROFILE) and **never edit framework files**
   (`CLAUDE.md`, `docs/`, `*.template.*`, `.claude/`, `scripts/`). Framework improvements come from
   upstream via `scripts/update-from-upstream.sh`. This keeps updates conflict-free.

## Additional working rules

6. **Plan before executing.** For any install, config change, multi-file edit, or generation
   run: present a short plan and wait for approval. Use plan mode for non-trivial work.
7. **No commit without explicit approval.** Propose the commit + message; commit only when told.
8. **Verify external tool details.** Confirm tool flags/versions with `--help`/docs before
   scripting (esp. Graphify serve/MCP + output-path flags — mission §10.4 open items).

## Session workflow

1. Read `state.md` (derived; for orientation) and the relevant part of `docs/mission.md`.
2. Restate the goal + a short plan. Get approval.
3. Work in gated steps.
4. On completion: update the **spreadsheet (SSOT)** first, then refresh `state.md` to match;
   append to the mission changelog if design changed; propose (don't make) a commit.

## Repo map

```
CLAUDE.md · README.md · quickstart.md · state.md (derived from spreadsheet SSOT; tracked for history)
docs/{mission,operating-model,bootstrap,claude-code-usage}.md
personas/ platforms/ formats/     # *.template.* (framework) + populated entries (instance)
topics/topic.template.md          # topics live under workspaces/<client>/topics/
workspaces/<client>/{topics,select,output}/            # instance-owned, per client repo
instance/profile.md               # instance-owned goals/audiences (gitignored in public)
scripts/ .claude/{agents,skills}/ # framework
```

## The matrix (mission §3–§4)

Axes: **topics × personas × platforms × formats**, each a registry (one file per value).
Adding a value must be a **one-file** change; if it needs a second edit, that's a defect — flag it.
A request selects one+ from each axis; the resolver applies the compatibility filter and fans out
to concrete, commit-pinned, idempotent items.

## Generation quality rules

- Ground factual/technical claims in **EXTRACTED** graph facts; treat INFERRED/AMBIGUOUS as leads
  to verify, never as published fact.
- Honor each format's constraints and each persona's tone/knowledge level (details in registries).
- Record each item's workspace + source repo + commit + graph confidence tier.
- Never surface secrets/credentials from graph nodes into output.

## Pointers

Design: `docs/mission.md` · Two-repo model + updates: `docs/operating-model.md` ·
Agents/skills sourcing & build: `docs/agents-and-skills-sourcing.md` ·
Setup: `docs/bootstrap.md` · CLI usage: `docs/claude-code-usage.md` · Fast start: `quickstart.md`
