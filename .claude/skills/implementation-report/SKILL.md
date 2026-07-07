---
name: implementation-report
description: Use when an ops-coder run completes. Defines the structured implementation report the coder writes to the handoff dir.
allowed-tools: Read, Bash
---

# Implementation report

Write your report to the **handoff path given in your spawn prompt**, with these sections:

1. **Feature / scope** — the feature slug and the caller-scoped file set you were allowed to touch.
2. **Pre-flight evidence** — verbatim `pwd` / `git rev-parse HEAD` / branch / `git status` / `ls`
   (proof you started from the correct state, in the main checkout — per `commit-discipline`).
3. **Changes made** — file-by-file summary of the edits.
4. **Deviations / open questions** — any gap between the plan and reality. You follow the plan's
   default and **log** the gap; you do **not** re-architect.
5. **Verification** — the literal command(s) run + result tail (per `verification-harness`).
6. **Deferred work** — anything not done, and why (per the review skill's deferral bar).
7. **Status** — **DONE** (verification passed) or **BLOCKED** (what failed).

Chunk writes over ~300 lines. You **never** stage or commit; a patch is emitted only if the
orchestrator asks (`git diff > <handoff>/changes.patch`).
