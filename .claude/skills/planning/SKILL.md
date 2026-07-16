---
name: planning
description: Use when breaking an approved design into an ordered, verifiable implementation plan — task breakdown, file dependencies, commit sequencing, risk identification.
allowed-tools: Read, Grep, Glob, Bash
---

# Planning

Turn an approved design into an ordered, verifiable plan.

- **Scope** from the approved design (`docs/design.md` and/or the architect's report).
  Address **every** in-scope item.
- **Ordered steps** with explicit file dependencies.
- **Complete affected-files list**, including cross-reference updates — grep for every filename,
  heading, and symbol you touch.
- **Commit sequencing** — plan commits that leave the repo in a working state after each one; the
  guard (`scripts/check-no-content.sh`) must pass at every intermediate step.
- **Verification plan** — every step names how it will be verified.
- **Risks** — stale refs, boundary violations (rules 2/4/5), CI/guard breakage, backward-compat
  regressions, steps that leave the repo broken mid-sequence.
- **State-verifiable questions are NOT escalations** — run Read/Grep/Glob/Bash and answer them now.
  Escalate only genuine judgment calls to the maintainer.

## Output shape

Goal + scope items · complete affected-files list · ordered steps **with approval gates** · commit
plan · verification plan · open risks.
