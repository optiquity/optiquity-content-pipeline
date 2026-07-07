---
name: review
description: Use when reviewing a change before commit — ordered priorities (boundary, correctness, consistency, regressions, architecture) plus deferral discipline.
allowed-tools: Read, Grep, Glob, Bash
---

# Review

Review in **priority order** — stop-ship issues first:

1. **Boundary discipline** — framework/instance + provenance/scope (rules 2/4/5). See
   `boundary-investigation`.
2. **Correctness** — does the change do what the plan/design specified? Verified, not "looks right."
3. **Cross-reference integrity** — grep every modified filename, heading, and symbol across the repo
   for stale references.
4. **Consistency** — with `docs/design-decisions.md`, `mission.md`, the lexicon, and existing
   conventions.
5. **Regressions** — templates, the guard, existing behavior.
6. **Architecture** — orthogonality, extensibility, cascade order.

## Deferral discipline

Default is **FIX NOW.** A carry-forward must clear a high bar — genuinely out of scope, blocked, or a
clear logical fit for later work. **Deferral is scope creep;** log any deferral explicitly with its
justification.

## Output

Concrete findings with file/line references, most-severe first, ending with a **CLEAN** or
**FIXES-NEEDED** verdict (and, if the latter, the ordered fix list).
