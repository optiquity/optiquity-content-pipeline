---
name: root-cause-analysis
description: Use when root-causing a defect or misbehavior before a fix is designed. Requires a falsifiable hypothesis and a reproduction (or decisive static proof) per cause; correlation is not cause; stop at the cause, never design the fix.
allowed-tools: Read, Grep, Glob, Bash
---

# Root-cause analysis

**No cause without a reproduction or a decisive proof.** "Looks like the cause" is not a cause — the
same bar `verification-harness` sets for changes, pointed at *causes* instead.

## The loop

Observe → hypothesize (falsifiably) → name the experiment that would **refute** the hypothesis →
collect the evidence → confirm or kill it → rank the survivors → the confirmed cause. Iterate until
one cause explains **every** symptom, or you record what stays UNRESOLVED and what would settle it.

## Rules

- **Falsifiable or it doesn't count.** For every hypothesis, state the observation that would prove
  it *wrong*, then go get that observation. A hypothesis with no refuting test is a guess.
- **Correlation ≠ cause.** Two runs that differ in output *and* in three inputs prove nothing about
  which input mattered. Isolate: change **one** variable at a time until the symptom flips.
- **Reproduce minimally and deterministically.** Smallest input that still shows the symptom; reset
  disposable state first; pin whatever non-determinism you can. Capture **raw** evidence (exact
  command + verbatim output), never a paraphrase.
- **Defect vs. intended behavior.** Before calling something a bug, check the spec (`docs/design.md`)
  and the boundary rules (`boundary-investigation`) — a rule you dislike is not a defect.
- **Label confidence** on every cause: **VERIFIED** (reproduced / decisively proven) ·
  **INFERRED** (consistent with the evidence but not isolated) · **UNRESOLVED** (say what would settle it).

## Stop at the cause

Output the confirmed cause and, at most, a one-line fix **direction** — never the fix design.
Designing the remedy is the architect's job; mixing the two contaminates the diagnosis and pre-empts
the design pass. Diagnosing first only pays off if diagnosis stops at the cause.

## Running experiments

Cheap read-only probes (grep, read a stored record, a static `python -c` check) you run yourself. Any
run that **spends subscription quota or writes a store** is specified as an experiment and handed to
`ops-coder` — a read-only diagnostician never runs one. Portable macOS bash only (3.2 / BSD utils).
