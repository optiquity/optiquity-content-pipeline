# State — derived convenience (NOT the source of truth)

> **The tracking spreadsheet is the single source of truth (SSOT)** for content-item status once the
> pipeline runs. This file is a derived, session-facing mirror for fast orientation. If this and the
> spreadsheet disagree, the spreadsheet wins.
> **Scope note:** no content pipeline is running yet, so there is no content SSOT to mirror. What this
> file currently tracks is the **framework build effort itself**, whose authoritative tracking lives in
> the build plan + the maintainer's tracker page (below).

## Current phase

**FRAMEWORK BUILD — design complete, plan final, build NOT started.**
Holding at the maintainer checkpoint (two authorizations pending, below).

## Standing instructions to any session picking this up (read before acting)

1. **The design is ratified and FINAL:** `docs/design.md` (2,722 lines) is the single design SSOT.
   The full decision record behind it: `docs/archive/design-record/maintainer-rulings.md` — its
   **"STANDING EXECUTION MANDATE"** (end of file) governs how all work proceeds and REMAINS IN FORCE:
   - No design/plan decisions are brought to the maintainer; ALL agent recommendations are accepted.
   - The coordinator (main session) NEVER plans, designs, or recommends — agents do; it coordinates.
   - Build pipeline per step: fresh coder agent → fresh reviewer agent → fresh coder applies EVERY
     reviewer fix. Fresh agents every time.
   - Durable rules always binding: client repos read-only · client isolation · subscription transport,
     NEVER API keys · no secrets · agents never commit · `CLAUDE.md` is maintainer-only (its pending
     proposed edits live at `_tmp .../ops-handoff/definitive-design/claude-md-proposed.diff`).
2. **The build plan is FINAL:** `/Users/david/Developer/_tmp/optiquity-content-pipeline/ops-handoff/build/plan-final.md`
   (41 steps; gates 1–6 first; ★ first end-to-end output = step 28; ★ MVP = step 39).
   Adversarial + reconciliation ledgers sit beside it.
3. **The maintainer's live tracker page (KEEP IT CURRENT — standing duty):**
   **https://claude.ai/code/artifact/3d7697a4-5d3a-487a-8f35-6f5242ed4994**
   Source file: session scratchpad `build-plan-tracker.html`; republish to the SAME URL (from another
   session: pass the URL as `url` to the Artifact tool). Update on: step start (in-progress), step green
   (done + progress/commit counters), every ★ milestone/checkpoint (steps 6, 28, 39, 41), any gate
   failure or re-plan, and when the pending authorizations resolve. Timestamp every publish.
4. **Working tree state:** the A4-2 placement changes are applied but UNCOMMITTED (docs/design.md added;
   design-decisions.md tombstoned + archived; mission.md banner; operating-model.md amended;
   docs/archive/design-record/ imported; this file). CLAUDE.md untouched.

## Maintainer authorizations (checkpoint resolved 2026-07-12)

- [x] **Proceed with the build** — GRANTED 2026-07-12 ("Proceed with implementation").
- [x] **Commit policy (rule 7):** OPTION 1 GRANTED — per-step main-session commits as the default,
      standing and revocable ("Do option 1 as the default. I will tell you if there are any changes.").
      33 pre-sequenced step-scoped commits; gates 1–6 + 37 report-only; anything outside the sequence
      needs fresh approval.

## Build checklist (mirror of the tracker page)

- [ ] P0 gates 1–6 (reports only) — G1 FS atomicity · G4 YAML · Pandoc/RI7 · G5 transport · G3+G6
      Graphify/review-metadata · §27.3 review pass [CHECKPOINT]
- [ ] P1 foundations 7–13 — scaffolding/CI · serialization · operator grammar · id family · schemas ·
      drift+migration · CI guards
- [ ] P2 configuration 14–19 — registries (rendering, content, collections) · cascade M1+M2 ·
      M3+grounding · adapters · fanout+plan-hash
- [ ] P3 store & generation 20–29 — store+claims · S0–S6 spine+guardrails · SSOT v1 · transport wrapper ·
      compose · reconcile · fit resolution · serialize core · **★28 first end-to-end output** ·
      serialize completion
- [ ] P4 reviews/folios/API 30–35 — review gates · folios+types · API core I/II · discovery+retrieval ·
      emit-manifest
- [ ] P5 closeout 36–41 — parallelism · G2 closure+finals · **★39 MVP (all 9 axes)** · cleanup sweep ·
      final verification + delivery

## Audit trail

Design-phase artifacts (skeleton, adversarial reports, fix ledgers, FR reports):
`/Users/david/Developer/_tmp/optiquity-content-pipeline/ops-handoff/` — plus the in-repo copies under
`docs/archive/design-record/`.
