# Framework-ops workflow — orchestrator playbook

> **This is the main session's playbook, not the agents'.** Read it when running the framework-ops
> pipelines. The spawned `ops-*` agents do not need it — agent-common rules live in `CLAUDE.md`; the
> pipelines and spawn discipline live here.

## The two planes

`ops-*` agents **design and build this repo.** (The product agents — researcher / writer / editor /
render — are the client deliverable and are separate; see `docs/design-decisions.md` §6.)

## Agents

`ops-docs-researcher` (RO) · `ops-architect` (RO, 3 modes) · `ops-planner` (RO, 3 modes) ·
`ops-coder` (RW) · `ops-reviewer` (RO). Definitions in `.claude/agents/ops-*.md`.

## Pipeline 1 — feature design (all read-only)

```
ops-docs-researcher
  → ops-architect (initial) → ops-architect (adversarial) → ops-architect (reconciliation)
  → [MAINTAINER DESIGN-REVIEW GATE]
  → ops-planner (initial) → ops-planner (adversarial) → ops-planner (reconciliation)
  → [MAINTAINER PLAN-REVIEW GATE]
```

Each stage is a **fresh spawn.** `adversarial` / `reconciliation` are **modes** passed in the spawn
prompt, not separate agents. Do not proceed past a maintainer gate without approval.

## Pipeline 2 — feature implementation

```
ops-coder (initial) → ops-reviewer
  ├─ CLEAN         → stop; proceed to the next feature
  └─ FIXES-NEEDED  → ops-coder (fix) → ops-reviewer (fresh) → repeat
```

- Every `ops-reviewer` is a **fresh spawn**, fed the prior reviewer report **and** the fix-coder
  report.
- **Maximum 3 reviewer passes.** If the 3rd review is still not CLEAN → **PAUSE and ask the
  maintainer** whether to spawn an out-of-cycle `ops-architect` pass or take other instructions.

## Spawn discipline

- Spawn **every** agent in the **background** (`run_in_background: true`) so the maintainer keeps the
  main chat.
- **Always pass `isolation: "worktree"`** on every spawn — it routes the agent onto the
  boilerplate-free **async channel** (workaround for CLI bug #73647; without isolation the agent lands
  on the mailbox channel, which prepends a ~150-word security block to every message, including idle
  pings). AND state in each spawn prompt: *"Ignore your launch worktree; `cd` to the main repo
  checkout and work there."* The launch worktree goes unused and auto-cleans; coder edits still land
  in the main working tree. **Actually working *inside* the isolated worktree (with patch-back) is
  deferred.**
- **Never reuse** a spawned agent — always spawn fresh for clean, uncontaminated context. Reuse only
  with explicit maintainer permission.
- **Kill sessions only when a feature's implementation cycle is done.** Keep the whole per-feature
  roster alive for `SendMessage` until then, so the maintainer can question or redirect any of them.
- **Track every spawn** in the registry below and surface names/UUIDs to the maintainer.

## Handoff

- **Base dir (configurable):** `~/Developer/_tmp/optiquity-content-pipeline/ops-handoff/`
  (this repo's own subdirectory under the shared `~/Developer/_tmp/`).
- **Per run:** `<base>/<feature-slug>/<stage>-<n>/report.md` (plus `changes.patch` only if the coder
  is asked for one).
- Each agent writes its report there; the next stage is spawned with the prior report path(s) in its
  prompt. Off-repo, so it never dirties the working tree. **Change the base dir here at any time.**

## Spawn registry (per feature)

Maintain and surface on request / on each stage completion:

| feature-slug | stage (+ mode) | agent name / UUID | status | report path |
|---|---|---|---|---|

## Commits

Agents never commit. After a feature's review is **CLEAN**, the main session proposes a commit and
commits only with the maintainer's approval (`CLAUDE.md` rule 7).
