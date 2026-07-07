---
name: verification-harness
description: Use when verifying an implementation change. Requires a literal verification command plus its result for every change; "looks right" is not verification.
allowed-tools: Read, Grep, Glob, Bash
---

# Verification harness

**Every change is accompanied by a literal verification command AND its output.** "Looks right" is
not verification.

## What to run

- Run the affected script/skill/agent; run the guard (`scripts/check-no-content.sh`) if you touched a
  guarded surface; run any relevant tests; render/parse the affected file; grep to prove a
  cross-reference is now consistent.

## Conventions

- **Portability:** macOS bash is 3.2 with BSD utils — write portable commands (no bash-4 features, no
  GNU-only flags).
- **Deterministic summary:** if you use a test runner, print a line the orchestrator can grep, e.g.
  `=== Results: N passed, M failed ===`. Do not vary the format.

## Reporting

Paste the command + the tail of its output **verbatim** into your report's Verification section. Claim
**DONE** only after verification passes; on any failure, report **what went wrong** instead of a
partial success.
