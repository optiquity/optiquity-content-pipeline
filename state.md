# State — derived convenience (NOT the source of truth)

> **The tracking spreadsheet is the single source of truth (SSOT)** for content-item status once the
> pipeline runs. This file is a derived, session-facing mirror for fast orientation. If this and the
> spreadsheet disagree, the spreadsheet wins.
> **Scope note:** no content pipeline is running yet, so there is no content SSOT to mirror. What this
> file currently tracks is the **framework build effort itself**, whose authoritative tracking lives in
> the build plan + the maintainer's tracker page (below).

## Current phase

**FRAMEWORK BUILD IN PROGRESS — Phase 5.** Steps 37 (Gate G2 closure) + 38 (G2 finals applied) done.

- **Step 37 — Gate G2 (§27.2) CLOSED, PASS, report-only (no commit; PA-2).** Per the maintainer's
  2026-07-13 "small bounded probe" ruling, a bounded LIVE telemetry probe (6 subscription calls, two
  waves of 3 through a `ThreadPoolExecutor(max_workers=3)` at the width-3 seed ceiling; each child spawned
  with `ANTHROPIC_API_KEY` stripped + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`; 1200 s per-call timeout)
  exercised the REAL subscription transport. Result: **peak_inflight=3 sustained with ZERO backpressure**,
  latency ~8–12 s (~150× under the TTL), $0.81 total. Both G2 numbers are **CONFIRMED UNCHANGED** from the
  step-4 conservative seeds — now telemetry-validated, not guessed: `MAX_PARALLEL_SESSIONS=3` (tested AT
  the cap, so no evidence to raise and none to lower), `LEASE_TTL_SECONDS=1800`. Report:
  `ops-handoff/build/step-37/report.md`; content-free telemetry residue under gitignored `instance/ops/`.
- **Step 38 — micro-CODER applying the G2 finals, reviewer CLEAN.** `pipeline/opdefaults.py`:
  **comment/docstring-only** rewrite relabeling the two numbers as G2-VALIDATED finals (citing step-37 /
  §27.2) — **NO constant VALUE changed** (all six byte-identical: `MAX_PARALLEL_SESSIONS=3`, per-workspace
  `=2`, `LEASE_TTL_SECONDS=1800`, `WRAPPER_HARD_TIMEOUT_SECONDS=1200 < TTL`, telemetry-on, width-window
  `=3600`; `__all__` unchanged). NEW `tests/test_opdefaults.py`: the **G2-equality lock** — asserts the
  loaded runtime defaults equal the step-37 numbers against HARD LITERALS (so any future drift genuinely
  fails CI, not a vacuous module-vs-module check). Reviewer **CLEAN** — 5 crux items all PASS with literal
  evidence (no value changed · test non-vacuous · comments faithful, no overclaim · no scope creep ·
  green+lint). Main session reconciled the reviewed worktree → main **byte-identical** (`cmp` clean) and
  **re-verified green under its own hand**. Review: `ops-handoff/build/step-38/review.md`.
- Progress = **38/41 + R1 done · 31/33 step-scoped commits** (+3 authorized extras). Baseline green:
  **1928 passed, 6 deselected** (zero live); ruff clean; INV-CORRECTNESS green (via `tests/test_inv_
  correctness.py`, part of the suite). **Next: ★ step 39 — the MVP demonstration (all nine axes; ★ checkpoint).**

**⚙ SPAWN-CHANNEL MITIGATION (maintainer directive 2026-07-13, CLI bug #73647; TEMPORARY, this session):**
the peer-message security boilerplate is channel-specific and fixed at SPAWN TIME — `isolation:"worktree"`
routes an agent onto the async-task channel (reports arrive in the task-notification, NO boilerplate);
no-isolation uses the mailbox channel (boilerplate on every delivery incl. idle pings). **From step 33 on,
spawn EVERY ops agent (coder/reviewer/fixer) with `isolation:"worktree"`.** The coder works in its own launch
worktree; reviewers/fixers IGNORE their launch worktree and `cd` to the coder's worktree (pass its path — it is
in the coder's task-notification `<worktree>` metadata, e.g. `.claude/worktrees/agent-<id>`); the main session
RECONCILES the coder's worktree → main at commit time (copy the reviewer-confirmed changed files by explicit
list, verify byte-identity, re-verify green under its own hand, commit from main, then `git worktree remove
--force <path>`). **CONFIRMED MECHANICS (step 33, empirical):** an isolation agent's **Edit/Write tools are
sandbox-confined to its OWN launch worktree** (cannot edit another worktree or main) — but **plain Bash writes
to a SIBLING worktree ARE permitted** (no sandbox override). So a fix-coder edits the coder's worktree via a
Bash-run exact-match replace helper (each replace asserted to match once), NOT Edit/Write; it then re-runs the
suite IN the coder's worktree to prove the edits landed. The main session independently greps/diffs the coder's
worktree before reconciling. Reviewers are read-only so they just `cd` + read. No CLAUDE.md/config edits, no
new branch/BD. Revert to no-isolation only when the maintainer says the bug is fixed. (Steps 24–32 used
no-isolation and wrote main directly — both channels are correctness-equivalent; only the boilerplate and the
reconcile step differ. `.claude/worktrees/` is git-excluded locally so it never dirties `git status`.)

**⚠ OPERATIONAL NOTE (spawn discipline) — SUPERSEDED 2026-07-13 by the ⚙ SPAWN-CHANNEL MITIGATION above.**
Historical: at step 23 the ops-coder's Edit/Write were hard-confined to its isolated launch worktree; steps
24–32 then ran WITHOUT isolation (writing main directly) but that put agents on the boilerplate mailbox
channel. The maintainer's #73647 directive reverses this from step 33 on: isolation IS used (for the clean
async channel) and the confinement is handled by the reconcile flow + the confirmed Bash-sibling-write
mechanic documented in the mitigation block. Follow the mitigation block, not this note.

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
   - **TOOL INSTALLS (maintainer directive 2026-07-12): NEVER performed by this session or its agents.**
     Any system-level install (Homebrew, npm/npx, pkg installers, anything touching the machine outside
     the repo's own uv venv) → report EXACTLY what is needed (tool, version, exact commands) to the
     maintainer, who runs it in another chat session. Claude-session-related tooling (MCP servers etc.)
     → raise with the maintainer for discussion first. Project-local Python deps declared in the repo's
     `pyproject.toml` and installed into its own uv venv by the build's scaffolding are part of the build
     itself, not tool installs — unless the maintainer says otherwise.
2. **The build plan is FINAL:** `/Users/david/Developer/_tmp/optiquity-content-pipeline/ops-handoff/build/plan-final.md`
   (41 steps; gates 1–6 first; ★ first end-to-end output = step 28; ★ MVP = step 39).
   Adversarial + reconciliation ledgers sit beside it.
3. **The maintainer's live tracker page (KEEP IT CURRENT — standing duty):**
   **https://claude.ai/code/artifact/3d7697a4-5d3a-487a-8f35-6f5242ed4994**
   Source file: session scratchpad `build-plan-tracker.html`; republish to the SAME URL (from another
   session: pass the URL as `url` to the Artifact tool). Update on: step start (in-progress), step green
   (done + progress/commit counters), every ★ milestone/checkpoint (steps 6, 28, 39, 41), any gate
   failure or re-plan, and when the pending authorizations resolve. Timestamp every publish.
4. **Working tree state:** clean at each step boundary — every green step is committed by explicit
   file list (never `git add -A`) before the next step starts; `state.md` rides on the step's primary
   (code) commit. CLAUDE.md remains untouched (maintainer-only).

## Maintainer authorizations (checkpoint resolved 2026-07-12)

- [x] **Proceed with the build** — GRANTED 2026-07-12 ("Proceed with implementation").
- [x] **Commit policy (rule 7):** OPTION 1 GRANTED — per-step main-session commits as the default,
      standing and revocable ("Do option 1 as the default. I will tell you if there are any changes.").
      33 pre-sequenced step-scoped commits; gates 1–6 + 37 report-only; anything outside the sequence
      needs fresh approval.

## Gate outcomes (running record)

- **G1 (step 1): PASS** — all 6 FS primitives proven on the real APFS volume; FS substrate OK, no DB
  fallback. Re-run G1 if `workspaces/` ever moves to iCloud/network storage. Commit primitive for step 20:
  stdlib `os.link`+unlink (renamex_np is Darwin-only).
- **G4 (step 2): PASS** — pin `ruamel.yaml==0.19.1`, `YAML(typ='safe', pure=True)`; splitter spec
  S-E1..S-E12 in step-02 report (incl. S-E8: refuse `%` directive lines in frontmatter).
- **G3+G6 (step 5): G3 PASS (query leg) / serve-MCP leg needs `graphifyy[mcp]` (maintainer install list,
  NOT build-blocking); G6 CLOSED — no per-symbol review metadata in graph.json → `review_status: unknown`
  designed degradation (§6.2).** Graphify 0.8.39 installed at `~/.local/bin/graphify` (uv tool `graphifyy`).
  Adapter I/O contract for step 18 in step-05 report.
- **G5 (step 4): PASS** — headless `claude -p --output-format json` works on subscription auth
  (`authMethod: claude.ai`, `subscriptionType: max`), claude 2.1.207. **Step-23 wrapper env contract
  (mandatory):** run under `env -u ANTHROPIC_API_KEY` + `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` (auto-memory
  otherwise leaks state across -p calls from one cwd — probe-proven); wrapper owns timeouts (no CLI
  timeout flag); never key success off `subtype` (use `is_error`/`terminal_reason`); `--bare` forbidden.
  **⚠ F10 HAZARD FLAG for the maintainer: `ANTHROPIC_API_KEY` is present in the ambient environment** —
  probes never used it, the wrapper will always unset it, but consider removing it from the shell env.
  **G2 preliminary defaults (step 4):** `max_parallel_sessions=3`, lease TTL 30 min, wrapper hard-timeout
  20 min (timeout < TTL ⇒ expired lease implies dead process). Usage-limit JSON shape UNVERIFIED (unsafe to
  trigger). Probe residue in ~/.claude/projects cleaned by main session.
- **G2 (§27.2; steps 37 report → 38 apply): CLOSED — PASS.** Bounded live telemetry probe validated the
  step-4 seeds against real data (peak_inflight=3, ZERO backpressure): finals `MAX_PARALLEL_SESSIONS=3` +
  `LEASE_TTL_SECONDS=1800`, both CONFIRMED UNCHANGED and now locked to CI by `tests/test_opdefaults.py`.
  The error-envelope raw shape remained unobserved (all 6 calls ok) → the step-06 §5.8 "UNVERIFIED
  backpressure JSON shape" note in `transport.py` stays open — nothing to tighten the classifier with; not
  a G2 blocker. Details: `ops-handoff/build/step-37/report.md`.
- **Designated demo graphs (read-only, never written):** e2e/MVP demo → `/Users/david/Developer/
  optiquity-site/graphify-out/graph.json` (3 weeks stale — fine for build verification; re-graph is a
  maintainer call, another session); tier-coverage tests → `/Users/david/Developer/
  optiquity-ai-agent-config-pack-v11-dev/graphify-out/graph.json` (24k nodes, all three tiers present).
- **Doc deviations found by step 5 (record per B2; sweep at step 40 must fix bootstrap.md):** bootstrap
  B3's `graphify . --wiki` is stale for 0.8.39 — graphing is `graphify extract <path>`; wiki is
  `graphify export wiki` (requires `.graphify_analysis.json`); `--graphml/--neo4j` moved under `export`;
  `query` default `--budget` = 2000; MCP entry point is `graphify-mcp`, not `graphify serve`.

## Maintainer install list (per the 2026-07-12 directive — maintainer executes in another session)

- [ ] **`graphifyy[mcp]` extra** — closes G3's serve-MCP leg (NOT build-blocking; feeds mission D4):
      `uv tool install --force "graphifyy[mcp]==0.8.39"` — or skip the install entirely and use the
      vendor's ephemeral shape when needed: `uv run --with "graphifyy==0.8.39" --with mcp -m graphify.serve <graph>`.
- [x] **Pandoc 3.10 — INSTALLED by maintainer 2026-07-12 + GATE 3 CLOSED.** RI7 round-trip proof PASS:
      `pandoc-api-version [1,23,1,2]` (exactly the pin), Div/Span Attrs byte-equal both cycles; extension
      snapshot saved at step-03/markdown-extensions-at-pin.txt. **Channel deviation noted:** maintainer
      installed via Homebrew (`/opt/homebrew/bin/pandoc`), not the recommended release binary — pinned
      VERSION matches so the gate closes; local exact-version re-install guarantees are weaker (brew),
      CI unaffected (step 27 uses the checksummed release asset). **typst 0.15.0 also installed** — the
      pre-identified future PDF engine is now available; `pdf` still ships `side: external` in v1 per the
      reconciled plan (the internalization flip stays a one-field §17 RI12 change, post-MVP).

## Step carry-forwards (reviewer notes binding on later steps)

- **→ Step 11 (from step-8 review RV-3):** the `_schema.yaml` loader must apply the same `%`-directive
  refusal as the frontmatter splitter (`load_yaml` alone honors an in-document `%YAML 1.1` directive —
  spec-conformant at step 8, but schema files must refuse it).
- **→ Step 21 (from step-7 review RV-2):** fold a `__pycache__/` line into step 21's `.gitignore` edit.
  Until then, all commits are by explicit file list, never `git add -A`.
- **→ Step 13 (from step-11 review RV-3):** SV11 schema-lint must assert CROSS-COLLECTION EQUALITY of the
  per-file `schema_version:` values (one global number copied across N `_schema.yaml` files — lint catches
  a skewed file).
- **→ Step 13 (from step-12 review RV-3):** SV11 clause-4 window-sanity lint must refuse future-dated and
  non-monotonic `released:` dates in `pipeline/migrations.yaml` (the registry loader accepts them silently).
- **→ whoever implements `extends:` partials (Q15ii; from step-12 review RV-4):** `_render_entry_text`
  hardcodes a three-key envelope; the partials case currently fails LOUDLY (never silently) and the
  renderer must be extended when partials land.
- **→ Step 15 (from step-14 review RV-2, BINDING):** platform projections key format ids
  (`short-opinion-post`, `long-form-essay`, `readme`) that do not exist until step 15 ships matching
  format entries — step 15 MUST create exactly these ids (or amend the projections in the same step);
  dangling keys currently load silently.
- **→ Step 16 (from step-14 review RV-2):** M1 resolution must make dangling projection/ref keys LOUD
  (the promised loud resolution); also handle the no-platform-selected reconcile-strategy floor edge.
- **→ Step 16 (from step-15 review, validated):** loud M1 for ALL now-load-silent refs (topic/persona/
  format/voice/goals/default_voice/content_kind/skeleton ids — reviewer probe transcripts in the step-15
  report); ratify the T10 defaults-template shapes incl. the dual `voice:` form.
- **→ Step 17 (from step-15 review, validated):** score→tier/scope mapping as code constants; freshness-
  expression validation; the `+2`→int-2 note.
- **✅ RESOLVED at step 36 — step-20 review RV-4 (collision-resistant holders).** Verified already discharged
  at step 21: `spine.mint_holder()` = `h<pid>-<os.urandom(16).hex()>` (128 random bits) at EVERY production
  claim-holder site (`registry_for(store)` is the sole constructor; no site derives a holder from a predictable
  value), and `claims.release`/steal is holder-checked (a non-holder can neither release nor steal a LIVE claim
  — only genuine lease EXPIRY yields `lease-expired-redrive`). The step-36 steal-interleaving + non-holder
  conformance tests exercise it non-vacuously. The step-36 presence-lease identity (`mint_presence_token` = 128
  random bits, distinct `p` namespace) is separate and gates only the never-auto-applied width advisory — off
  the correctness/claim-release path. No `claims.py`/`store.py` edit was needed.
- **→ Step 19/25 (from step-16 review RV-1):** configured `platform.*` values at L2/L3/L5 are silently
  inert on a no-platform item (falls to the L0 `adapt` floor with zero warnings) — decide warn-vs-inert
  where no-platform deliverable semantics are consumed.
- **→ next step touching cascade.py (from step-16 review RV-2, cosmetic):** add `AmbiguousSelectionError`
  to `cascade.__all__`.
- **→ Step 31 (from step-15 review RV-1, BINDING):** folio-type skeleton key WHITELIST (recipe slots +
  `topic_slot`) — a skeleton with `platform: linkedin` currently passes lint silently (untyped map
  interior); the reviewer's probe transcript is the acceptance seed.
- **→ Step 40 (from step-15 review):** stale `workspaces/workspace.template/readme.md` (omits
  defaults.yaml; mission-era wording) — already in the sweep's named scope.
- **→ Step 15 or 27 (from step-14 review RV-3):** add a permanent pin-bundle equality test across all 7
  carriers (schema default + 6 render-target entries).
- **→ Step 19 or 25 (from step-18 review RV-2):** `ParsedQuery.truncated` is parsed but dropped by
  `ground()` — partial grounding is invisible to the resolver; needs a warning channel through base.py/
  grounding.py where a step owns those files.
- **→ next pyproject-owning step (from step-18 review RV-3, one line):** amend the `live` marker
  description to cover machine-local tests, not just subscription transport.
- **Live-test env bindings (post step-18 RV-1):** the live adapter battery reads
  `PIPELINE_LIVE_DEMO_GRAPH` / `PIPELINE_LIVE_TIER_GRAPH` (skip when unset). This machine's values:
  optiquity-site + config-pack graphify-out paths (see "Designated demo graphs" above).
- **→ Step 19 (from step-17 review, validated):** recipe-layer M3 arrives via `resolve_selection(recipe=…)`
  (the shipped recipes schema carries no `source_selection` — ratified step-15 scope). Step 19 must either
  extend the recipe schema ADDITIVELY (§11.5 discipline) or confirm run-side supply as the mechanism.
- **→ Step 40 (from step-30 review nit, cosmetic):** `pipeline/review.py` `_ast_provenance_summary` labels
  `provenance_span_count = len(fact_ids)` — that is the DISTINCT-fact count, not the raw Span count (two
  spans citing one fact count as 1). Harmless (advisory LLM context) but the name over-promises; rename to
  `provenance_fact_count` or count spans separately in the sweep.
- **→ Step 40 (from step-29 review obs-1, cosmetic):** `pipeline/serialize.py:668` `except IdError` is dead
  code — `delta_vs_floor` raises `PreimageError`, not `IdError`, so the wrap-to-`SerializeError` never fires
  (a `PreimageError` propagates loudly regardless). Catch `PreimageError` or drop the try in the sweep
  (already annotated `# pragma: no cover`).
- **→ Step 40 (from step-29 review obs-3, doc trivia):** `docs/design.md` labels the serialize-resolution
  rule "FR7.4" at §21.8 (~line 2051) but "FR7.3" at ~line 1620 — code/plan use FR7.3 consistently; reconcile
  the pre-existing doc label in the sweep.
- **→ optional hardening (from step-29 review obs-2, defense-in-depth, NOT required by design):** an optional
  payload-side metadata re-scan in `payload.build_payload` would close the residual where a caller
  hand-builds a `fitted_ir` bypassing `ir.validate_ir`'s `_scan_no_secrets`. §11.3/§17 RI14 deliberately keep
  the metadata bag opaque/untouched, so this is defense-in-depth only.
- **✅ RESOLVED at step 33 — the step-32 continue-session isolation obligation.** FIX 2 (pass-1 review)
  moved enforcement to the INVOKE GATE, the cleanest single-path design: `invoke._extract_continue_session`
  maps each nested action to its mirror verb's id-extractor and registers `continue-session` in
  `_ID_EXTRACTORS`, so its action-nested ids (render.item, fetch/get.id, add-to-folio folio_id+members+pins,
  emit-manifest folio_id+member_targets) ride the SAME envelope-fatal Gate 3 as the standalone verbs. The
  handler's own isolation branch was removed → exactly one authoritative enforcement path. Pass-2 reviewer's
  id-position enumeration confirmed NO un-gated position. `unknown-action` (no mirror) stays a per-item block.
- **✅ RESOLVED at step 33 — CF-1 (id/ledger provenance divergence).** Collapsed the two provenance readers
  into ONE: new `SourceAdapter.pin_commit` (base default `None` = commitless posture); `GraphifyAdapter`/
  `MockAdapter` share their `ground()` commit source (`_graph_provenance` / `_commit_for`), so the §7.2
  commit-map and the §15 grounding ledger read byte-identical provenance — the commitless-but-git-checkout
  case can no longer omit a commit the ledger records. Rejected the "assert commit_map==source_commit" variant
  (it would false-fire in the legit §21.8 begin-session-frozen-pin vs generate-next-fresh-read case). Step-28
  demo id byte-for-byte unchanged (its source carries `built_at_commit`). (The `MockAdapter.pin_commit`
  override was FIX 1 — the pass-1 reviewer caught that the mock silently re-opened the divergence.)
- **✅ RESOLVED at step 33 — CF-2 (contained-hook consistency).** The fitted deliverable-row advance now
  rides the spine's S5 contained hook (`_persist_record(advance=_advance_fitted_row)`), consistent with
  composed/rendered per §22.7; behavior preserved on both fresh and already-materialized re-drive paths.
- **→ HARD GATE before `generate-next` is wired to the LIVE CLI (step-33 reviewer-ratified, BINDING):** a
  per-item GENERATION failure currently surfaces as a CODE-LESS block — `driver._run_artifact` collapses a
  stage block (empty-pool/hard-limit-exceeded/low-confidence-grounding/…) into an opaque `DriverError`, so
  `session._generate_next` emits `status=block` with a hint but NO §21.7 `code`/`remediation.action`. Accepted
  as a transitional gap for step 33 (no code FABRICATED — honest per §3.1; threading codes up is a driver-
  contract restructure that lands with the generation-tier/wiring step; generate-next is not CLI-wired yet).
  It is marked as a HARD GATE in `session.py` (the `_block` docstring + the `_generate_next` DriverError branch
  comment). **Before generate-next reaches a production caller, the driver MUST thread the real §21.7 stage
  codes up so the block carries its true code.** (NB: FIX 4's malformed-CALL block — bad recipe/folio/source
  connection — is legitimately code-less FOREVER; only the GENERATION block is gated.)
- **→ The API step that wires the production edge (from step-33 coder CF-1 + step-34, BINDING):**
  `register_api_handlers()` (step 34 renamed/extended the step-33 `register_session_handlers`) exists but is
  deliberately NOT called at import (calling it would wire the verbs and break step-32's
  `test_every_known_verb_passes_the_verb_gate`, which asserts the verb registry is empty). The production CLI
  edge MUST call it once at startup. Until then the CLI hits `HandlerNotWired` (honest).
- **⛔ HARD GATE before §21.9 wires ANY production currency resolver (from step-34 review, HIGH — BINDING):**
  `discovery.DefaultCurrencyResolver` is a PARTIAL detector — it recomputes the current fit/serialize digest by
  substituting only the current platform HARD-LIMITS (+ tool-pin bundle) into the stored preimage, keeping the
  stored `strategy`/`advisory`/`render-dims`. So it computes the NAMED blast radius (hard-limit tightening,
  the §21.3 example) CORRECTLY, but if any OTHER reconcile/serialize input changed it reports `fit_current=true`
  for an actually-STALE deliverable → `list deliverables {fit_current:false}` OMITS it → the force loop misses
  it. Its `except Exception → return stored_digest` fallbacks are the same unsafe direction (a config-read error
  reads as "no drift"). SAFE TODAY: dead code — never on a tested path (every test injects a precise fake
  resolver) and never reached in production (`register_api_handlers` uncalled; the transport edge is §21.9,
  gated). **§21.9 MUST NOT wire this default as-is** — first complete the reconcile-/serialize-input re-read
  (needs the recipe, which only §21.9 carries) OR flip the uncertainty direction to fail-safe (report
  NOT-current on any un-verifiable input / on error → over-force, safe because force/render is idempotent), and
  fail-safe the `except` branches. The docstring documents the limitation; §21.9 closes it.
- **→ Step 36 CORRECTNESS_ROOTS batch (from step-34 review, LOW):** add `api.discovery` (and, IF design-
  confirmed ssot-free, `api.render`/`api.fetch`/`api.folio_verbs`) to `tests/test_inv_correctness.py`
  `CORRECTNESS_ROOTS` so their ssot-freedom is enforced TRANSITIVELY (today only discovery's `TestSsotFree`
  shallow direct-import check guards it; these modules aren't in the roots so the transitive walker skips them).
  Determine per-module whether ssot-free is a DESIGN REQUIREMENT (discovery: yes §21.3/§22.7; render/fetch/
  folio_verbs: confirm — a standalone render may legitimately need to touch the derived SSOT). Batch with the
  already-scheduled fit_resolution/reconcile/compose/folios roots expansion.
- **→ Step 34 hardening (from step-34 review, LOW):** `discovery` `list actions` returns an EMPTY set silently
  when `action_vocab` is unwired (default `frozenset()` at the `list`/handler seams); no end-to-end test ties
  `list actions` to `session.CONTINUE_ACTIONS` through the real `register_api_handlers`. Give it a loud
  "unwired" sentinel default and/or add the round-trip assertion. Low: both shipped wirings inject the vocab.
- **→ Step 40 / manifest polish (from step-35 review2, LOW, design-underspecified):** `manifest._resolved_row`
  (~`:446-451`) — when a STALE-FIT choice (§21.8 rule 2) has NO serialize-current deliverable, the
  `render-needed` branch drops the rule-2 `render-input-mismatch` warn (sets `warn=None`). NET-SAFE and a strict
  improvement over pre-fix (serialize-stale bytes are no longer referenced), and the warn resurfaces at render
  time + on the next emit — but the manifest under-reports fit-staleness for one cycle in this compound corner.
  §21.5 (~L1906-1908) does not explicitly specify the warn on a render-needed-from-stale-fit row. Optional
  one-line follow-up: carry the rule-2 `warn` onto that branch (rule-1 keeps `warn=None`).
- **→ Step 40 / next `ir.py`-touching step (from step-27 review F3, dedup):** `serialize._match_bracket`
  duplicates `ir._match_bracket` byte-for-byte — promote to ONE shared public helper (importing the private
  `ir._match_bracket` was left out of scope). Until then, `tests/test_serialize.py::
  test_match_bracket_twins_agree_byte_for_byte` guards against drift.
- **→ Step 40 (from step-27 fix, §17 R-4 doc alignment):** `docs/design.md` §17 R-4 enumerates the strip
  targets as "html5/epub3"; the IMPLEMENTATION is now fail-CLOSED (strip UNLESS on `SAFE_WRITERS`), a
  strengthening beyond the literal enumeration that closes the one-file-add extensibility hole while
  preserving the §3.3 no-provenance-in-public intent. Align the §17 R-4 prose to document the fail-closed
  safe-set policy so the design doc stays the SSOT.
- **→ Step 31/folio or step 40 (from step-27 review, minor nit):** a part Div's `#id` = `part["role"]` slug
  is asserted doc-unique in the docstring but NOT enforced — duplicate roles in one combined multi-part doc
  would emit duplicate `#id` (HTML-validity nit only; addressing still rides `data-part-id`). Enforce or
  document when multi-part/folio assembly is exercised.
- **→ Step 26 (from step-25 review obs-3, BINDING):** `advisory`/`render_dims` must be "scoped to the
  attributes reconcile consumes" — a CALLER obligation. `reconcile.reconcile_inputs_preimage` puts ALL of
  `request.advisory`/`request.render_dims` (delta-vs-floor) into the fit preimage, so step 26 MUST pass only
  the consumed attributes or the fit-revision `_hex12` churns spuriously (spurious identity change).
- **→ Step 26 (from step-25 review obs-1, cheap hardening):** a non-numeric `hard_limit` raises
  `ReconcileError` only at the terminal gate — for a non-`pass` strategy that fires AFTER one LLM call
  (wasted spend). Add a pre-LLM numeric-limit type check in request assembly/`_validate_request`.
- **→ Step 36 sweep (from step-25/26/31 reviews, INV-CORRECTNESS roots expansion — batch all FOUR):**
  the import-lint `CORRECTNESS_ROOTS` (`tests/test_inv_correctness.py:45`) watches store/claims/spine/sweep/
  parallel. Add `fit_resolution` + `reconcile` + `compose` + `folios` TOGETHER (one small expanded-scope pass;
  editing that shared test file is out of a coder's per-step scope). Rationale: `fit_resolution` and `folios`
  are content-addressed marker/resolution stores (§22.7 PC12 names "both resolution rules" SSOT-independent);
  `reconcile`/`compose` are pure producers. The invariant HOLDS today (`ssot` doesn't exist yet) and each has
  a local AST no-ssot guard in its own test (own-imports only, weaker than the transitive-closure roots lint)
  — owed-soon defense-in-depth, not a live defect. Step-31 reviewer recommended the step-36 sweep landing.
- **→ §26 localization GA (post-MVP, from step-25 review obs-2/obs-4):** (a) the reconciler prompt/parse are
  built from `request.canonical_ir` while assembly uses `localized_ir` — identical in v1 (localize no-op);
  once localization is real the prompt must read the LOCALIZED IR. (b) a `pass` with language≠source is
  zero-LLM and would ship UNLOCALIZED content as an `ok` fit (unreachable under the v1 language==source
  contract; designed deferral).
- **→ Step 40 (from step-25 review obs-5, cosmetic):** `pipeline/prompts/__init__.py` `STUB_TEMPLATE_NAMES`
  still lists `reconciler` and `writer` even though both stubs are now filled — cosmetically stale; reconcile
  in the sweep.
- **→ Steps 24+ (from step-23 review A2, BINDING on transport callers):** the transport module accepts an
  optional `cwd=` but does NOT enforce a dedicated non-repo working dir or wire cwd/config-isolation flags
  (`--setting-sources`/`--settings`/`--strict-mcp-config`/`--tools ""`) — INFERRED/UNTESTED per step-04 §4.7,
  not a G5 mandate. Steps 24+ that invoke the wrapper should pass a dedicated non-repo `cwd` and, if they
  wire the isolation flags, verify with live calls. Also guards against an `apiKeyHelper`-via-`--settings`
  auth path.
- **→ Steps 37–38 / maintainer (from step-23 review A1, optional hardening):** the wrapper strips only the
  literal `ANTHROPIC_API_KEY` (the ratified G5 surface; no sibling auth var is present on the runner env, so
  no live bypass). Maintainer/telemetry-era MAY ratify also stripping `ANTHROPIC_AUTH_TOKEN` /
  `ANTHROPIC_BASE_URL` / `ANTHROPIC_API_URL` / `CLAUDE_CODE_USE_BEDROCK` / `CLAUDE_CODE_USE_VERTEX` as cheap
  defense-in-depth (no-op when absent). No code change needed for correctness today.
- **→ Step 40 (from step-23 review, wording nit):** `pipeline/transport.py:231` docstring says the seam
  "mirrors" the graphify Runner — it adapts, not mirrors (5-field ProcessRequest vs 2 positional args);
  reword in the doc sweep.
- **→ Step 40 (from step-22 review OBS-1, optional):** `pipeline/ssot.py` `_read_rows` leaks a raw
  `ValueError` from `zip(strict=True)` on a malformed DATA row vs the typed `SsotError` used for header
  damage — near-unreachable (writes are atomic whole-table) and contained by the spine on S5; optional
  symmetry hardening only.
- **→ Step 40 (from step-22 review OBS-2, doc hygiene):** `docs/design.md` cross-refs now read slightly
  stale after the §24 amendment — index line ~2608 ("future home §24") and §27.4 ~2497 ("lands at §24");
  left untouched on purpose (plan mandated "§24 amendment ONLY"); reconcile in the sweep.
- **→ Step 40 (maintainer, 2026-07-12, EXPANDED):** the swept docs must document ALL THREE entry-authoring
  modes the maintainer ratified: (1) FULLY MANUAL — the one-file contract walkthrough (template + schema +
  lint/CI verification); (2) INTERACTIVE/ASSISTED — how to have a Claude session author + review entries
  (the coder→reviewer chain pattern); (3) RESEARCHER-ASSISTED — the researcher→coder→reviewer chain for
  batch-proposing candidate entries. Documentation of process, not new machinery.

## QUEUED: registry expansion (maintainer-ordered 2026-07-12; runs immediately after step 18's chain)
13 new framework default entries, full coder→reviewer→fix chain + ONE step-scoped commit (fresh maintainer
authorization given in the ordering message; outside the 33-sequence):
- **Persona:** tech-journalist · product-reviewer · technical-documentation-writer · product-manager ·
  executive-coach
- **Format:** medium-review-post · how-to-documentation · product-requirements-document
- **Platform:** medium-post · substack-post · corporate-website · press-release
- **Output-type:** plain-text (+ its render-target twin; pandoc `plain` writer)
Sequenced AFTER step 18 closes so the new registry files don't contaminate step 18's review scope checks.
Also in flight: a researcher report proposing ≥10 candidate default entries per dimension (ideas only,
maintainer picks; report-only, no repo changes).
- **→ Step 40 (from step-13 review):** (a) unknown-registry-root residual — a NEW top-level dir (e.g.
  `voices2/`) is outside the PA-1 whitelist scope and passes the guard silently; sweep must reconcile the
  root list with the repo map. (b) SV11 diff clauses run against a PR-base baseline in CI only where the
  event provides one — verify the wiring covers the real workflow when the repo gains PRs.
- **Housekeeping (from step-9 review RV-5):** `pipeline/attrtypes.py` fails `ruff format --check`
  (cosmetic; enforced battery is `ruff check`, which is green) — normalize opportunistically in a later
  step that touches the file; never as a standalone out-of-sequence commit.
- **Adjudication of record (step-9 review RV-4):** TWO ALPHABETS confirmed — §7.4 strict slug governs
  registry ENTRY IDS/filenames; §13.2 operator paths name schema ATTRIBUTES where medial `_` is required
  (`word_limit`, §21.3's `fit_current` etc.); collision hunt negative (paths never reach filename
  carriers). Documented in docs/reference/operator-grammar.md §2.

## Build checklist (mirror of the tracker page)

- [x] P0 gates 1–6 (reports only) — COMPLETE 2026-07-12: G1 PASS · G4 PASS · G5 PASS · G3 PASS(query)/
      serve-leg→install-list · G6 closed-by-design · Pandoc gate PENDING-INSTALL (decisions made; closure
      = one mechanical ri7_roundtrip.sh run post-install; blocks step 27 only) · §27.3 review: ALL SEVEN
      items RE-REGISTERED with named triggers, zero scope growth · gate-exit report + BUILD PARAMETER
      SHEET at ops-handoff/build/step-06/report.md (coders' input of record)
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
