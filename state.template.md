# State — derived convenience (NOT the source of truth)

> **The tracking spreadsheet is the single source of truth (SSOT).** This file is a derived,
> session-facing mirror for fast orientation and cross-machine handoff. If this and the
> spreadsheet disagree, the spreadsheet wins — update this file to match, never the reverse.
> `state.md` **is tracked in your instance** (for history and durability); being derived does not
> mean untracked. The spreadsheet simply remains authoritative.
>
> In a private instance: copy this to `state.md` and keep it in sync with your spreadsheet.

## Current phase

**Phase 0 — Foundations & prerequisites** (not yet started)

## Next action

Run `docs/bootstrap.md` step B1 (install prerequisites), plan-gated, on the target machine.

## Onboarding checklist (mirror of spreadsheet)

- [ ] **P0.1** Prereqs installed + Claude Code verified — always-on host
- [ ] **P0.2** Prereqs installed — workstation
- [ ] **P0.3** Graphify installed + `graphify --help` verified (`extract` / `export wiki` / `query` / `graphify-mcp`)
- [ ] **P0.4** First workspace created: `workspaces/________`
- [ ] **P0.5** Client repo graphed in its checkout (`graphify extract .` → graphify-out/, gitignored); path in source.md
- [ ] **P0.6** Read-only query smoke test passes
- [ ] **P0.7** Instance repo initialized (upstream remote set), chezmoi-managed
- [ ] **P1.0** Prove-one-thread: 1 topic × 1 persona × 1 format → 1 grounded draft
- [ ] **P1.1** Content axes populated: personas / formats / voices / goals (+ topics per client)
- [ ] **P1.2** Rendering axes populated: platforms / languages / output-types / presentations
- [ ] **P1.3** Recipes + selection → fanout producing concrete items
- [ ] **P1.4** researcher + writer product-plane agents wired
- [ ] **P1.5** First ideation run → curated queue
- [ ] **P1.6** Review gates (artifact + deliverable) exercised end to end

## Per-item status lifecycle (SSOT checkpoints, design §24)

The SSOT tracks one row per fanout item in two kinds, each advancing forward-only by its own item's
render/review (never cross-written):

- **artifact rows:** `planned → composed → artifact-reviewed`
- **deliverable rows:** `planned → fitted → rendered → deliverable-reviewed → ready`

`blocked` is an annotation (a `block_reason` §21.7 code), never a status; currency is computed at
read time, never stored. See design §24 for the row/column schema.

## Session log

| Date | Session did | Next |
|---|---|---|
| — | Instance bootstrapped from framework | Begin Phase 0 |
