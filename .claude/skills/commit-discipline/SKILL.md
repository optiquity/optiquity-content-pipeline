---
name: commit-discipline
description: Use at the start of every framework-ops agent run. Codifies the agents-never-commit rule, the read-only git-verb whitelist, the absolute state-changing-git ban, and the isolated-launch-worktree rule.
allowed-tools: Read, Bash
---

# Commit discipline (all ops agents)

**Only the main session commits, and only with the maintainer's approval (CLAUDE.md rule 7).**
Agents do the work, write a report, and never touch git state.

## Pre-flight (run before any work)

Paste the verbatim output of these into your report as evidence you started from the right state:

```
pwd
git rev-parse HEAD
git rev-parse --abbrev-ref HEAD
git status
ls
```

You are spawned with an **isolated launch worktree** (the channel workaround for CLI bug #73647).
A **read-only** agent ignores it: `cd` to the main checkout and do all reads there — the unused
launch worktree auto-cleans. A **read-write** agent (coder) does all edits *and* verification
**inside its launch worktree**, never the main checkout, and reports the worktree path + branch so
the main session can transfer the diff back (`docs/ops-workflow.md`, "Coder diff-transfer").

## Absolute ban — state-changing git verbs

Never run: `add`, `commit`, `push`, `tag`, `rebase`, `merge`, `reset`, `stash`, `checkout`,
`switch`, `restore`, `apply`, `worktree`, `cherry-pick`, `revert`, `gc`, `prune`, `reflog expire`,
`update-ref`, `branch -d/-D/-m`, `remote add/remove/set-url`, or any `git config` write.

**Catch-all:** any git verb that changes repository, index, working-tree, ref, or config state is
forbidden — including anything not enumerated above.

## Allowed — read-only git

`status`, `diff`, `log`, `show <ref>:<path>`, `rev-parse`, `ls-files`, `blame`, `cat-file`.

## RW coder exception

`ops-coder` may edit files in the working tree **within its caller-scoped file set** (Write/Edit),
but **never stages or commits**. `git diff > <handoff>/changes.patch` is allowed only if the
orchestrator asks for a patch; `git apply` is forbidden (only the main session applies/commits).

If a task seems to require a git state change, **STOP and report it as an open question** — an agent
that stages or commits has bypassed the maintainer-approval gate, which is the entire reason for this
ban.
