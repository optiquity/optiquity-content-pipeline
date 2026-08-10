# State — derived convenience (NOT the source of truth)

> **The tracking spreadsheet is the single source of truth (SSOT)** for content-item status once the
> pipeline runs. This file is a derived, session-facing mirror for fast orientation. If this and the
> spreadsheet disagree, the spreadsheet wins.
> **Scope note:** no content pipeline is running yet, so there is no content SSOT to mirror. What this
> file currently tracks is the **framework build effort itself**, whose authoritative tracking lives in
> the build plan + the maintainer's tracker page (below).

## Current phase

**✅ CORE BUILD COMPLETE (41/41 + R1) — and POST-BUILD EXTENSIONS shipped on top.** The core 41-step
build delivered at `5f58d63` (final verification PASSED; cross-reference audit **DELIVERABLE**; Gate G2
CLOSED, the §21.7-code HARD GATE CLOSED at step 39, the §21.9 gate correctly OPEN/honored). The prepared
CLAUDE.md diff was applied post-delivery (`5b1c584`). Since then a series of ratified design-record
increments + the friendly CLI surface + the authoring layer + the users/-namespace restructure + the
**sources subsystem**, the **foundation/ reorg**, the **diagram-tools-optional** change, and the **zone restructure** landed. **Current HEAD `9b13e61`.** Detailed per-increment records live in the
commit history + `ops-handoff/`;
the summary below is orientation only.

**Post-build increments (each planned + coder→reviewer→commit):**
- **DR-1 … DR-9** — the HTTP shim (poll/webhook); mixed-media assets + `{type=diagram}` (grounded
  node/edge diagrams with a HARD grounding gate + a diagram-styles registry); content templates (§ section
  conformance / academic-paper); style compose-vs-render (per-venue csl); general grounding (advisory
  Review-1 audit); citations (`[@key]` → references); optional editable outlines (emit/drive); the
  `lexicons/` house-style registry; and DR-9 — the `format.diagram_disposition` diagram-nudge knob.
- **CLI-UX (friendly invocation surface)** — `pipeline generate` / `preview` / `outline emit|drive` /
  `list` / `get`, dry-run by default; `--go` is the ONLY spending path (subscription-only, §21.9
  money-safety preserved — `invoke begin-session` stays exit 3); the C1 explain projection + spend estimate.
- **Authoring layer (C1–C5c)** — `pipeline docs attributes` reference generator (+ drift test); the shared
  authoring core; `recipe new` / `--from` derive; `entry new` scaffolder; the diagram-disposition gate
  (require = grounded-diagram-or-refuse, suppress, resist/prefer, both D3 pre-writer contradiction
  directions); and the saved-selection layer — new `selections/` registry root → `generate
  --save-selection` (save a fan-out as base + variant deltas) → `generate --selection ID` (load + drive
  1:1), round-trip proven byte-identical at both `artifact_ids` and `deliverable_ids` with no cartesian
  re-expansion.
- **C6 — slider-legend ablation (measure-gated):** a real subscription A/B showed NO output gain from
  routing the voice-slider legend into the writer prompt (a capable model already reads the bare numbers)
  → **NOT shipped**. The legend content instead enriched the human-facing slider docs (`e8a7963`): all 9
  slider definitions now describe the 1–5 gradient.
- **Version-lint fix (`330fc6d`):** the SV11 schema-version lint was baselining the last COMMIT (per-commit
  bump demands); now RELEASE-relative — baselines the last release via a committed marker
  (`pipeline/released_baseline`, absent pre-release), so pre-release schema evolution is free and only the
  first change AFTER a release bumps. Aligns the code with the documented §11.2 / `5b1c584` release-only
  policy. Verified not-weakened (fires with an explicit baseline) and not-toothless (all within-tree
  invariants still fire pre-release).
- **Guide/docs (`51750b4`) + tracker sync (`7c902f8`):** documented the friendly CLI + authoring surface
  under `docs/guide/` (new `authoring.md`) and the release-relative versioning; discharged GAP-4; brought
  this file current.
- **★ users/-namespace restructure — the REST resource hierarchy (`686541f`..`2284517`; 10 increments
  B1–B10, each coder→reviewer→commit; an adversarial security-design pass + a data-safety-reviewed
  migration).** Workspace addressing moved from flat `workspaces/<ws>/` to
  `users/<user>/workspaces/<workspace>/` (maps 1:1 to a future `/users/{owner}/workspaces/{workspace}`
  REST route). **`--user` is now MANDATORY** on every command / API / shim / client call (never defaulted;
  a missing user is a loud usage/validation error, never a `users/None/…` path). Highlights: a 3-level
  resolve-and-contain validator (`validate_workspace_path`, isolation proven at the users/owner/workspace
  levels); `WorkspaceStore` gains explicit identity (`framework_root`/`user`/`workspace` via `.at()`),
  curing the silent-wrong-root positional recovery; the shared template moved
  `workspaces/workspace.template/` → `templates/workspace/`; the public-boundary guards + lint scopes moved
  to `users/` + a new `templates/` scan arm (which also **closed a pre-existing template-exemption leak**);
  the 3 self-grounding refusals follow client content to `users/`; lowercase-only ids (APFS cross-user
  aliasing closed); the DR-8 Python + C++ clients and the n8n example flows all thread `user`. Net:
  isolation is **STRICTER** (6 latent trust-the-name path builders + the shim callers now all validated).
  §10/§23 clarified: `users/<user>/` is an isolation/ADDRESSING PREFIX, NOT a new cascade rung (the value
  cascade stays framework→instance→workspace). On-disk instance data migrated locally
  (`mvp-demo`/`optiquitytrader` → `users/optiquity/workspaces/…` via `scripts/migrate-to-users-layout.sh`,
  idempotent, ZERO data loss). GAP-9 marked SUPERSEDED; GAP-11 records the accepted marker-less `templates/`
  guard residual. **Current HEAD (restructure) `2284517`.**
- **★ Workspace CRUD conveniences — W1 + W2 (`4ec8ae6`, `783b57d`; each coder→reviewer→commit; W1 carried
  one LOW review fix, W2 reviewed CLEAN first pass).** The friendly local lifecycle on top of the
  users/-namespace: **W1** — `pipeline workspace new <ws> --user <u>` (seeds from the `templates/workspace/`
  blueprint; `--user` mandatory; auto-creates a new user namespace, announced; refuse-if-exists; **`--force`
  is non-destructive** — tops up only missing files, never overwrites/deletes) + `pipeline user new <u>`
  (the empty per-user namespace). **W2** — `pipeline workspace list [--user U]` (read-only; per-user or all;
  topic-count + has-output summary) + `pipeline workspace delete <ws> --user U [--yes] [--force]` (the FIRST
  destructive command, SAFE-BY-DEFAULT two-tier: Tier-1 always needs confirmation — type-the-name or `--yes`,
  headless-without-yes refuses; Tier-2 refuses a workspace holding generated output even with `--yes` unless
  `--force`; never rmtrees through a symlink or outside the validated target). All FOUR are LOCAL Tier-A file
  ops — never an invoke/HTTP verb, no spend (§21.9 money-safety held: `begin-session` stays exit 3). Logic in
  the pure leaf `pipeline/workspacescaffold.py`; reuses the validator + typed refusals (nothing
  re-implemented). **Encapsulation (maintainer's explicit question): delete is SELF-CONTAINED — there is NO
  global workspace index; workspaces are discovered by scanning `users/*/workspaces/*` and all workspace
  state lives under the workspace dir, so a delete orphans nothing (reviewer-confirmed independently).** This
  CLOSES the original W1/W2/W3 trio. Docs swept to point the onboarding flow at `workspace new` as the
  friendly path (quickstart, getting-started, bootstrap, operating-model, architecture, design §23 repo-map,
  the blueprint readme) + the new commands added to the `interfaces.md` CLI door list; the manual `cp -R`
  is kept only as an "equivalent by hand" note. **Current HEAD `783b57d`.**
- **★ SOURCES SUBSYSTEM — pluggable acquire→cache→ground grounding sources (`d9cf98f`..`6f016f2`;
  7 increments P0–P3b, each research→design→adversarial→reconciliation up front, then
  coder→reviewer→commit).** Extends the source-adapter layer with new grounding-source CLASSES behind
  the stable `Fact` contract (the narrow waist), governed by a benefit/cost θ + a publish-vs-lead gate.
  - **P0 (`d9cf98f`)** the `reuse_rights`/`republishable` publish-vs-lead gate: `publishable`(=tier,
    §6.5 invariant, UNTOUCHED) AND a NEW `republishable` (a 5-value content-kind ordinal
    forbidden<internal-only<lead-only<attribution<full, floor `full` ⇒ byte-identical backward-compat)
    ANDed at `driver.py`. Orthogonal to confidence (a license-restricted quote stays certain, just not
    publishable). NOT selectable (no dimension blur).
  - **P1 (`df844af`)** a sealed, content-addressed, append-only slice CACHE + read-only
    `CacheReaderAdapter` (`"cache"`); the slice digest is the §7.2 commit-pin (never None); CF-1 +
    N2 by content-addressed immutability. + the CLAUDE.md rule-1 CARVE-OUT (may cache acquired
    third-party content under the workspace, gitignored, never committed).
  - **P2a (`dc2d18c`)** the HEAD-freeze (full N2 for HEAD-mode cache configs) at BOTH the driver AND
    the production `session._generate_next` seam; GAP-12 fixed→Resolved.
  - **P2b-core (`41bb01f`)** the acquisition skeleton + `pipeline sources ingest` (out-of-band Tier-A)
    + **SEC EDGAR** — the FIRST non-code source that PUBLISHES (characterized primary → EXTRACTED +
    attribution). temporality (archival|snapshot|live) as an identity-neutral §15-ledger provenance
    label. Host-pinned so EXTRACTED is self-verifying by code.
  - **P2b-feeds (`7eda83d`)** `feedparser` (2nd dep, BSD-2) + generic RSS/Atom + GDELT — INFERRED leads
    only (EXTRACTED stays EDGAR-class).
  - **P3a (`104b977`)** `trafilatura` (3rd dep, Apache-2.0) + Common Crawl lead-source + the pluggable
    SearchBackend interface (SearXNG stubbed/deferred). + `THIRD_PARTY-LICENSES.md` (tld/certifi
    weak-copyleft accepted, never vendored).
  - **P3b (`6f016f2`)** the agentic RESEARCH loop — the FIRST paid acquisition: plan→search→extract→
    synthesize→corroborate→gap→θ-stop, INFERRED page-anchored leads. Money-safe by construction: the
    paid LLM seam is injected ONLY from the CLI on the `--go` branch (sources/ imports no paid
    machinery); dry-run spends nothing; subscription-only (F10 key-strip); the disclosed `acquire-scope`
    is the true worst-case ceiling; θ-bounded.
  Deps grew 1→3 (ruamel.yaml, feedparser, trafilatura; all permissive/MIT-compatible, recorded in
  THIRD_PARTY-LICENSES.md). **Current HEAD `6f016f2`.** Follow-ons open: SearXNG live backend; the
  keystore for paid sources (FRED key, paid APIs) — shared with the deferred transport-selection design;
  design.md §sources canonical writeup (design-of-record captured off-repo).

- **★ foundation/ reorg + CI hardening + diagram-tools-OPTIONAL (`1bdd4a2`..`51a8735`; 2026-08-06 → 08-08;
  each coder→reviewer→commit).** Two arcs on top of sources:
  - **foundation/ reorg (B-1 `1bdd4a2` / B-2 `89a268c` / B-3 `bd18f86`)** — the 17 framework registries
    regrouped under one `foundation/` parent (`dimensions/`, `grounding/`, `composition/`, `render-config/`,
    `lexicons/`) via a physical base-path MAP (`pipeline/layout.py` `REGISTRY_BASE` + `registry_dir`). A
    RELOCATION, not a cascade/identity change: the collection token stays bare; only framework path-builders
    reroute; the instance/per-user layer stays flat. Identity-preserving (no artifact-id churn; only the 3
    journal `csl:` values re-mint their deliverable-id). Guard `check-no-content.sh` re-anchored to
    `foundation/`; tracked `git mv` migration (`scripts/migrate-to-foundation-layout.sh`, run once downstream).
  - **diagram tools OPTIONAL + tool-less CI (`51a8735`; 2026-08-08).** A requested `{type=diagram}` whose tool
    (`dot`/`d2`/`rsvg-convert`) is ABSENT now degrades GRACEFULLY — the diagram is dropped, its text alt
    substituted, and a warning RECORDED (`ComposeOutcome.warnings` / `DispatchOutcome.warnings`), never a
    silent drop. This REVERSES the PA-12 loud-fail for the MISSING-TOOL case ONLY; the HARD grounding gate and
    malformed-source errors still refuse loudly. Identity stays honest (compose stores no SVG; the docx fold is
    made rsvg-aware ⇒ no same-id/different-bytes collision, FR7.3). CI now runs **TOOL-LESS** (mirrors the
    common user who never installs graphviz) so a missing tool can never set it red; also pins
    `.python-version` 3.12.13 (fixes 3 unrelated `ipaddress` CI failures). Verified 3853 tool-full /
    3819+34-skipped tool-less; **CI green** on GitHub's runner. Supersession note in `docs/known-issues.md`;
    `diagram-styles` schema `tool` definition + generated `attributes.md` + `concepts.md` swept. **Current
    HEAD `51a8735`.**

- **★ ZONE restructure — a `zone` rung between user and workspace (`395516d`..`9b13e61`; 2026-08-09 → 08-10;
  9 gates Z1–Z9 + the S4 spend guard, each coder→reviewer→commit; research→design→adversarial→reconciliation
  then plan→adversarial→reconciliation up front).** Moves `users/<user>/workspaces/<ws>/` →
  `users/<user>/zones/<zone>/workspaces/<ws>/` — a zone GROUPS a user's workspaces (personal/work) under one
  subscription-holder (the ToS single-user-subscription constraint drove it). Mirrors the users/ restructure.
  - **Z1–Z3** literals + `WorkspaceStore.at(zone=)` + the 5-level resolve-and-contain validator (both new
    fixed joins RE-RESOLVE their base; 69-case containment matrix). Identity-NEUTRAL: zone ∉ any id preimage —
    a relocated workspace keeps every id (proven).
  - **Z4** atomic cutover — zone threaded through every caller of the 3 path functions, flipped to REQUIRED
    (a forgotten zone is loud, never a silent path); the http-shim ACL keyed `user/zone/workspace` (isolation
    fix); 3 positional-math bugs fixed; id-neutrality + same-name store-isolation + ACL proofs.
  - **Z5** additive `.gitignore` (`users/*/workspaces/` KEPT + `users/*/zones/` ADDED — no un-ignore window).
  - **Z6** `migrate-to-zones-layout.sh` (all-users, idempotent, never-delete-`users/<u>/`; **3 data-safety
    review cycles** found + closed 2 HIGH + a deeper HIGH out-of-root move, via a generic `pwd -P` containment
    guard). **RUN on the local demo data:** the 2 optiquity workspaces relocated to `zones/default/`, all 24
    files byte-identical, verified.
  - **Z7** `zone new/list/delete` (delete safe-by-default, recursive, never-through-symlink; a review found +
    fixed 2 delete BLOCKERs — `zone delete` now runs the full L1+L2+L3 containment) + `--zone` on
    workspace/entry. GAP-13: `recipe`/`select` still default-zone only (a tracked follow-up).
  - **Z8** client lib + C++/n8n examples + callback zone-aware; the resolved zone now ECHOED end-to-end
    (`results.Envelope.zone` + the preview header) — honoring the Q1 promise.
  - **S4 guard** a multi-zone user must pass explicit `--zone` on SPEND verbs (refuse-and-list; single-zone +
    Tier-A keep the friendly default) — **CLI door only** (the programmatic shim/client doors still default an
    omitted zone; uniform chokepoint enforcement is a transport-build item).
  - **Z9** docs sweep (design §10/§12/§23 + the guides + the pull→migrate→use runbook + the shim allow-list
    config-format BREAKING change + mission §12 `0.3.2`) + a PREPARED-not-applied CLAUDE.md rule-2 diff
    (`docs/zone-claude-md-rule2.patch`; the maintainer applies it).
  DEFERRED to the transport build: the transport-credential zone RUNG (per-zone keys/weekly-caps + spend-bucket
  isolation between same-named zones) — the restructure gives STORE isolation only. Suite 3853→3994.
  **Current HEAD `9b13e61`.**

- **Steps 37–38 (prior):** G2 closed by a bounded live probe (peak_inflight=3, ZERO backpressure) →
  `MAX_PARALLEL_SESSIONS=3`, `LEASE_TTL_SECONDS=1800` (both CONFIRMED UNCHANGED, now telemetry-validated;
  step 38 applied them comment-only + a CI equality-lock test). Reports: `ops-handoff/build/step-{37,38}/`.
- **Step 39 — ★ MVP demonstration (§25), code committed; reviewer CLEAN.** Planned in 3 passes
  (initial→adversarial→reconciliation; the adversarial pass caught a BLOCKER — the Presentation axis
  would have been demonstrated OFF the real pipeline — and dropped an unneeded public-framework entry).
  Deliverable: **ADD** `pipeline/mvpdemo.py` (the ONE shared scenario callable — injectable writer-runner +
  adapter + currency_resolver + clock, driven via `invoke(handlers=…)` from injected seams, NO
  register-handlers/global mutation; includes the MVP fail-safe currency resolver) + `tests/test_mvp_
  scenario.py` (hermetic mock-transport CI variant, 4 tests, exercising EVERY §25 clause — all nine axes;
  full selection grammar incl. a real ≥2-instance on_conflict; a real L6 override; internal AND external
  targets; both review gates; typed+untyped folio members; emit-manifest w/ member_targets; sequential
  batch+cursor AND a NON-VACUOUS parallel wave+sweep; both SSOT kinds + derive-state). **MODIFY**
  `driver.py` + `api/session.py` (GATE-1: thread the real `("block",)` codes `empty-pool`/`hard-limit-
  exceeded`, status derived from the CodeSpec, NO fabrication — all 9 raise-sites audited, 7 correctly
  stay code-less), `api/render.py` + `driver.py` (**B1**: wire the real `presentation.lower` into BOTH
  production minting paths — proven byte-identical to the retired `lower_plain` for the `plain` floor →
  ZERO deliverable-id churn; a styled entry now genuinely lowers on the real pipeline), `__main__.py`
  (the `mvp-demo` subcommand — AUTHORED, never run in the build). GATE-2 honored (the unsafe
  `DefaultCurrencyResolver` is never constructed on the mvp path). Reviewer **CLEAN** — no must-fix; all
  4 coder deviations ruled SOUND; the standalone §21.8 render-verb gap ruled a pre-existing carry-forward.
  Hermetic + zero spend (in-process fakes). Reconciled byte-identical → main, re-verified green under my
  own hand. Reports: `ops-handoff/build/step-39/{plan-final-step39,plan-adversarial,review}.md`.
- **Step 40 — post-approval cleanup sweep (§27.4/B.6); reviewer FIXES-NEEDED → fix-coder → CLEAN.** A
  25-file sweep to the ratified 9-axis model: docs (quickstart/README/.claude-readme/bootstrap/agents-
  sourcing/claude-code-usage), the 5 registry `*.template.*` + `state.template.md` + `workspace.template/*`
  (aligned to the real `_schema.yaml`, dead fields dropped), the `update-from-upstream.sh`→drift-report
  hook (PA-9c), and the ~14 `→ Step 40` cosmetic carry-forwards (review.py rename, serialize.py dead-except
  fix + the `_match_bracket`→public `ir.match_bracket` dedup, prompts list, transport/ssot/attrtypes,
  design.md FR7.3/§24/§17-R4). The maintainer-only **CLAUDE.md diff is PREPARED (`git apply --check`-clean)
  and DELIVERED, NEVER applied** (`ops-handoff/build/step-40/claude-md-proposed.diff`); `CLAUDE.md` +
  `docs/mission.md` untouched (PA-3 verified). Reviewer caught 2 (a stray `quickstart.md` fence; a
  tautological `_match_bracket` twins test) → fix-coder fixed both (identity + expected-literal asserts) →
  re-verified. Reconciled byte-identical → main, re-verified green under my own hand.
- Progress = **40/41 + R1 done · 33/33 step-scoped commits** (+3 authorized extras). Baseline green:
  **1932 passed, 6 deselected** (zero live); ruff (whole repo) + content + schema + INV-CORRECTNESS green.
- **Deferred past step 40 (backlog for step 41 / post-delivery, re-tagged out of "→ Step 40"):** item-13's
  functional halves (a new-registry-root guard tightening + the SV11 PR-base CI wiring, both needing
  `check-no-content.sh`/`.github/workflows` edits); the 3 optional-hardening items (payload metadata
  re-scan, `manifest._resolved_row` rule-2 warn, part-Div `#id` uniqueness); and the §21.8 render-verb
  `{"ir":…}`-vs-raw-IR fix (step-39 #4).
- **Step 41 — final verification + delivery: DONE.** Delivery proof green under my own hand: `pytest -q`
  **1932 passed** + `pytest -m live` **6 passed** (real graphify grounding on the real optiquity-site graph
  + a real subscription-transport smoke) + ruff/content/schema/shell all clean. **Live demonstration:** a
  full end-to-end `demo-thread` produced a REAL 12,373-byte grounded, provenance-tracked deliverable via a
  live subscription writer call (cost $0.476; binding digest VERIFIED) — subscription-only, no API credits
  (`ANTHROPIC_API_KEY` absent + stripped by the transport). The full nine-axis §25 matrix is proven by the
  hermetic `tests/test_mvp_scenario.py`; a full LIVE nine-axis `mvp-demo` needs a purpose-built fixture
  graph (the real client graph lacks the crafted multi-source conflict by design) and is offered as an
  optional maintainer-run demo. Cross-reference audit **DELIVERABLE** (33 step commits reconcile; 10/10
  citation spot-checks faithful; CLAUDE.md untouched by the build). Delivery report + audit:
  `ops-handoff/build/step-41/{delivery-report,delivery-audit}.md`.
- **MAINTAINER ACTIONS:** (1) apply the prepared, `git apply --check`-clean, maintainer-only CLAUDE.md diff
  (`ops-handoff/build/step-40/claude-md-proposed.diff`); (2) optional — run a full live nine-axis
  `mvp-demo` against a purpose-built demo instance; (3) optional — `graphifyy[mcp]` install (closes G3's
  serve-MCP leg, non-blocking). **Backlog (no v1 MUST):** the §21.8 render-verb `{"ir":…}`-vs-raw-IR read
  fix; item-13's CI halves — guard tightening (`6b196a6`) and the schema-lint version-discipline, now
  RELEASE-relative (`330fc6d`) — both DONE; the 3 optional-hardening items.

### POST-DELIVERY design + build (2026-07-16 → 07-18)

A maintainer-driven design program ran after delivery (each via research → architect initial →
whole-picture adversarial → reconciliation, all RATIFIED; cross-DR integration + planner pipeline before
build): **DR-2** style guides · **DR-3** editable outline (Markdown-canonical) · **DR-4** content
templates · **DR-5** style-placement · **DR-6** general grounding. All tracked in `docs/known-issues.md`;
22 design records archived under `docs/archive/design-record/dr-design-passes/` (18 from this program +
4 DR-1 records added 2026-07-24 — see the DR-1 subsection below).

- **Most recent post-delivery arc (2026-07-24 → 07-29) — tracked in `docs/known-issues.md`, not yet fully
  narrated here:** the README front-door split; **DR-1** HTTP shim (poll/webhook — BUILT, narrated below);
  **DR-7** mixed-media documents (increments **A** asset foundation + **B** binary-target image embedding +
  **C** flat honest generated diagrams — all BUILT; **D** badge grouping designed-not-built; E deferred);
  **DR-8** general multi-language API client (CLI + stdlib library + language-neutral wire contract + C++
  POC — BUILT); and the `lexicons`→schema-lint discharge (this commit). `docs/known-issues.md`
  (DR-1/DR-7/DR-8) is the CURRENT authority for these; a full state.md narration + the user-facing
  `docs/guide/*` sync ride the end-of-arc documentation pass (after increment D is decided and runnable
  end-to-end examples verify the feature), per the maintainer's "update the guide only when it is done and
  tested and works correctly."

- **DR-6 increment 1 — BUILT (Option A, advisory).** Four gated commits, each coder → reviewer → (fix →
  re-review) to CLEAN, commits under the maintainer's standing approval:
  - `0f6d401` **F-a** — `ir_version`→2 + generation-tolerant validation (old IRs re-reconcile; coverage
    gate is nowhere in `validate_ir`).
  - `aeed34d` **attestation carrier** — optional `attestation {primary CSL-JSON, anchor, relation}` ledger
    field; scenario-1 byte-identical → artifact-id unchanged. Carrier + pass-through only.
  - `b92b443` **Review-1 advisory audit** — prompt-only `grounding` coverage + faithfulness sub-dimensions,
    never-block; `ARTIFACT_CHECKS`/`REVIEW_VERSION` unchanged.
  - `7e935a1` **`grounding_posture` + item-level abstain** — cascading M3 policy (`warn`|`block`, default
    `warn`); under `block` the driver abstains an item with a persisted Review-1 `grounding` concern
    (`grounding-uncovered`), **fail-OPEN** on record-absent + re-drive-stable; policy rides `plan_hash`,
    never the artifact-id preimage; `review.py` unchanged.
  - Gate at each commit: `2014 passed, 6 deselected`, ruff + content-guard clean. Reports:
    `ops-handoff/dr6-build/{coder,reviewer}-0{1..4}*`. **NOT built** (deferred/reconsiderable): the Option-C
    hard self-demarcation coverage gate, `.framing`, the corpus migration — or a future fact-checking
    docs-researcher agent instead.
  - **Design-authority doc-sync LANDED** (`5814901`): `docs/design.md` §15 attestation/`ir_version`,
    §6.3/§12.1 `grounding_posture`, §6.5/§19/§21.7 the advisory audit + abstain, + the `ir.py` docstring
    note + mission `0.2.1` changelog. Reviewer CLEAN. **DR-6 increment 1 fully closed.**

- **DR-3 (optional editable outline) — BUILT (horn (a) fixed posture + B1 usable product).** The reconciled
  foundation+feature plan, each commit coder → reviewer → (fix) → commit under the standing cadence:
  - Foundation (identity-safe): `48393f8` outline normalizer N + `outline_digest` + #3a N-invariance reservation ·
    `f81d7a4` the `outline-digest` preimage extension (zero-churn, omit-when-absent) · `6d7273d` `formats/outline.md`.
  - Feature: `6f327c6` emit bridge `build_outline_ir` · `c562ec1` pre-compose outline store (`outlines/`,
    bare-digest, retain-all) · `90e5f1a` drive path (high-salience brief, horn (a) content+structure,
    digest-fidelity guard) · `db7979a` `emit-outline` verb (the maintainer-chosen explicit output trigger).
  - **Decisions (ratified at the plan gate):** horn (a) fixed posture (per-request facet choice RETIRED —
    hand-editing covers it, horn (b) could mask bad goals/unavailable content); B1 usable product; emit surface
    = an explicit `emit-outline` verb. **Identity:** non-outline artifact-ids byte-unchanged; the driven/emitted
    id rides the single `outline-digest` component (no `drive-config`/facet key).
  - Doc-sync `81a58a1` (design.md §5.2/§7.2/§12.1/§15/§21.1/§27.3 + known-issues DR-3 build-status + mission `0.2.2`).
  - Gate: `2135 passed, 6 deselected`, ruff + guard clean. Reports: `ops-handoff/dr3-build/`.
  - **R1 ablation BUILT + RUN** (`2ea1270`, directional n=1): live on `mvp-demo`/optiquity-site graph, two
    outlines. Grounded outline: V0 struct 0.17 / content 0.83 vs V1 struct 1.00 (6/6 in order) / content 0.91
    (Δ +0.83 / +0.08). **Honest read:** the brief's effect is STRUCTURAL (imposes the skeleton + order); content
    steering is small once the outline is faithful (V0 already covers the facts — the outline organizes grounded
    facts, can't inject them). Identity sanity held live. **DEFERRED:** only the LLM outline drafter (GAP-7 mirror).
  - **DR-4 was NEXT and is now BUILT** — see the DR-4 bullet below.

- **DR-4 (content templates: typed-section conformance) — BUILT (horn (a) section-typing SD-1..SD-5;
  three venues, one paper; D-8b = RECORD-NOW).** 11 gated commits C1–C11, each coder → reviewer → (fix)
  → commit under the standing cadence; realized as a **typed-section conformance envelope over the
  outline's sections** (DR-3 × DR-4 unified) — NOT `format.parts`, NOT the IR `constraints?` field:
  DR-4 got its OWN `section_conformance` field.
  - `b0ee351` **C1** F1 sentinel section grammar (`pipeline/sections.py`; `parse_sections`; the OPEN
    one-file-add `SECTION_TYPES` frozenset `{prose,figure,table,callout}`; ATX-only, fail-closed). ·
    `d005ae4` **C2** the conformance vocabulary (`Presence|Order|Count|Length`, role/type `Selector`,
    error/warning/info, the pure `check_conformance`).
  - `cdce299` **C3** the Format `section_schema` attribute (floor `[]`) + the `academic-paper` genre. ·
    `3c158b8` **C4** the `section_conformance` IR field (additive-optional, omit-when-absent, NOT in the
    binding preimage → identity-neutral).
  - `661ba5d` **C5** the HARD platform-neutral base structural gate at compose (error → bounded re-ask →
    `section-conformance-violation`; non-outline body EXEMPT; advisory deferred to Review-1, D-4). ·
    `92cb3ef` **C6** the Platform `format_structural` per-format HARD class (floor `{}`, sibling of
    `hard_limits`, M2-EXCLUDED).
  - `b8a7436` **C7** the preserve-through + no-mint role backstop (the section-typing role-forgeability
    backstop; `structure-not-preserved`, rides the bounded fidelity re-ask). · `4cea5fa` **C8** the
    reconcile STRUCTURAL gate + the **5th OMIT-WHEN-FLOOR `structural` preimage component** + the
    early-return joint block-and-report + #4a per-section limits RE-HOMED here + the `format_structural`
    M2-exclusion.
  - `1fc0d0f` **C9** the SD-5 STRIP validity transform (public writers strip bare `type`/`role`, keep
    `{#id}`) + the omit-when-absent `section_attr_transform_version`. · `23e06a2` **C10** the
    three-venues-one-paper driving example (journal-strict FORBIDS acknowledgements; journal-structured
    REQUIRES discussion; journal-concise #4a `abstract ≤ 800`) — block/fit diagonal proven hermetically. ·
    **C11** (this) docs + SSOT sync + the R2 accuracy comment + the N-3 docstring fix.
  - **Identity discipline:** additive-at-floor everywhere; **no `schema_version` bump, no `ir_version`
    bump**; the reconcile OMIT-WHEN-FLOOR `structural` component (floor `{}` → no key → byte-identical
    fit-digest) + the serialize OMIT-WHEN-ABSENT SD-5 version (fires only on a typed public render) keep
    every existing artifact-id / fit-digest / render-digest byte-identical (golden corpora unperturbed);
    **ZERO new `artifact-id` preimage component.**
  - **#3/#3a/#4/#4a resolution (precise):** #3 the section grammar + vocabulary BUILT (C1/C2; the DR-3
    `constraint?` consumer + the F1 broadening stay deferred); #3a the N-invariance reservation HONORED
    (not un-deferred); #4 the DR-4 structural gate + terminal gate + joint block-and-report BUILT (C8;
    the DR-6 coverage re-check leg stays deferred); #4a per-section limits genuinely BUILT at the
    structural gate (`abstract ≤ 800` on journal-concise; "already built" claim RETRACTED). See
    `docs/known-issues.md` DR-4 build status.
  - **Follow-ups — BUILT (both, maintainer-approved post-build):** **R1** (`35b4238`) hoist
    `reconstruct_rule` `compose`→`pipeline.sections` — behavior-neutral; reconcile now imports neither
    `compose` nor `api.results` (purity restored, comment corrected). **RT** (`aaa4d44`) render-site
    version threading — `mvpdemo.py` (dispatch-first) + `api/render.py::serialize_preimage` (two-phase;
    computes the flag via `strip_section_attrs` on the fitted AST as dispatch does); non-typed corpus
    byte-identical. The double pandoc-reader read is now ELIMINATED — `DefaultRenderEngine` memoizes
    `serialize_fitted` by fitted-id (frozen-dataclass cache field).
  - **Gate:** final `uv run pytest -q` = **2380 passed** (post R1+RT+AST-cache); ruff + content guard
    clean. Reports: `ops-handoff/dr4-build/`.
  - **Build order — ALL DONE:** DR-5 DONE (see the DR-5 bullet below) → **DR-2 DONE** — BUILT as the
    compose-time `lexicons/` registry (the `lexicons/` root took the required **F-b / GAP-4
    content-guard** known-root fix in C1); see the DR-2 bullet below.

- **DR-5 (style placement: per-output citation style from one IR) — BUILT (D1 = (b)-PROJECTED;
  three-journals-one-paper; gate green).** 11 gated commits **C1–C8, C10–C12** (**C9/SF-6 deferred**;
  the plan-number is intentionally skipped), each coder → reviewer → (fix) → commit under the standing
  cadence; the **C0** citeproc round-trip parity proof at pinned pandoc 3.10 gated the build.
  - `0f9be37` **C1** `ir.py` — the `references` CSL-JSON block on the IR envelope (additive-optional,
    omit-when-absent, body-blind / OUT of `binding.preimage`). · `1bbf4c1` **C2** `compose.py` —
    `project_references(ledger)`: `references` MACHINERY-projected from the ledger's distinct pool
    sources (deterministic `s0`/`s1` ids), gated on a citing body.
  - `fdc0817` **C3** `compose.py`+`writer.md` — the writer emits `[@key]` ONLY (never authors
    `references`, #5). · `15b6a44` **C4** `compose.py`+`results.py` — HARD `[@key]`→projected-
    `references` resolution at COMPOSE via the pandoc `Cite` AST; new block code `citation-unresolved`.
  - `61fb1de` **C5** `serialize.py` — `references`→AST-`meta` frontmatter (D2; RI7 stays citeproc-free).
    · `a2fdbc5` **C6** `dispatch.py`+`filters/citeproc_enablement.py` — CONTENT-driven citeproc
    enablement (the SD-5 identity twin) fixing the broken `plain` default.
  - `3c0776e` **C7** `presentations/_schema.yaml`+`presentation.py`+`dispatch.py` — the `csl`
    Presentation lever (α labeled field; content-gated `--csl`; csl-hash in the preimage gated on
    `citeproc_enabled`). · `467e5d9` **C8** `reconcile.py`+`reconciler.md` — inline-`[@key]` preservation
    on the fidelity re-ask (SUBSET/S5; `citation-not-preserved`).
  - `915ec07` **C10** `payload.py` — the RI14 external payload carries the citeproc requirement + `csl`
    (omit-when-absent). · `73155bf` **C11** `presentations/journal-*-look.md` + 3 `.csl` + the e2e —
    three journals differ ONLY in citation style from one IR (proven via an injected loader). ·
    **C12** (this) — docs + SSOT sync + the MN-2 strip-invariant docstring.
  - **Ratified decisions:** D1 = **(b)-projected** · D-cite-locus = **compose** · D-csl-seam = **α**
    (labeled field) · D-citeproc-version = **record-now** (omit-when-absent) · D2 = **frontmatter** ·
    D7 = **SUBSET-only** citation preservation.
  - **Identity discipline:** `references` body-blind; the `csl` asset-hash + `citeproc_enablement_version`
    BOTH omit-when-absent (present only when citeproc ran/fired); **ZERO new `artifact-id` preimage
    component**; **no `schema_version` bump, no `ir_version` bump** — a non-citing render (even under a
    csl-set look) is byte-identical to pre-DR-5 (== `plain`).
  - **Driving example:** three journals (`journal-strict`/`structured`/`concise`), three citation styles
    (numeric / author-date / footnote) from ONE IR.
  - **Deferrals (registered, not blanket-resolved — see `docs/known-issues.md` DR-5):** C9/SF-6
    output-type↔style WARN; the lone-bare-`@key` escape (accepted v1); out-of-pool external literature →
    DR-6 scenario-2; the production Presentation asset loader → §17/step-29 (both `_deferred_asset_loader`s
    still raise); plus the json-passthrough note, GAP-1 determinism gate, non-`.md` provenance convention,
    `pin_bundle`-csl, and #5a(N1)/#6/#7(N2)/N3.
  - **Gate:** final `uv run pytest -q` = **2497 passed**; ruff + content guard clean. Reports:
    `ops-handoff/dr5-build/`.

- **DR-2 (selectable style guides → the compose-time `lexicons/` house-style registry) — BUILT
  (attributes-only; prompt-applied at compose; artifact-id-only identity; gate green).** 5 gated
  commits + this docs closeout (C5), each coder → reviewer → (fix) → commit under the standing cadence.
  The `lexicons/` registry is a **class-(ii) content-side registry** — NOT a §5.4 axis, NOT a content
  dimension; entries are **attributes-only** and applied **prompt-only at compose**; the entry BODY is
  documentation only, never compose-consumed. HEAD `6148c64` (C4) + this C5 docs commit.
  - `13dd6e6` **C1** — stood up `lexicons/` (the 15th registry, `schema_version: 1`): attributes-only
    schema (`preferred_terms`/`banned_terms`/`proper_names`/`spelling` enum `""|us|uk`/`mechanical`
    open bare map; all floor-empty) with the load-bearing invariant (body is doc-only, never
    compose-consumed); generic `house-standard` entry (`provenance: framework`); `check-no-content.sh`
    `REGISTRY_ROOTS` 14→15 (mandatory — else F-b/GAP-4a hard-fails). No `DIMENSION_COLLECTIONS` edit;
    `lint.py`'s matrix `REGISTRY_ROOTS` UNCHANGED (class-(ii)).
  - `b06bfaa` **C2** — threaded the lexicon `{entry, delta}` into the §7.2 artifact preimage
    (top-level, omit-when-absent; dimension-shaped, F7-guarded; delta over ATTRIBUTES, never the body).
    Identity: **artifact-id ONLY**; omit-when-absent → byte-identical corpus; **RI11** (rule edit → new
    id). No `schema_version`/`ir_version` bump.
  - `1603288` **C3a** (`fix(lint)`) — the **§11.2 additive-at-floor exemption** in SV11 clause 1 (a new
    attribute at its empty L0 floor needs NO bump — enforcement now matches the ratified policy);
    removals / meaning-changes / non-empty-default adds still fire.
  - `9380913` **C3b** — wired `lexicon` selection at **L3 (workspace) + L5 (recipe)**, **L6 DEFERRED**
    (F4a: `_WORKSPACE_KEYS` only, never global/L2); recipe `lexicon: {type: text, default: ""}`; ONE
    resolution → TWO consumers (preimage binding + writer block); attribute-only byte-stable prompt
    block; `folios` `RECIPE_SLOTS += "lexicon"`.
  - `6148c64` **C4** — the §16 reconcile **ADVISORY** preserve clause (reads
    `binding.preimage.lexicon`, prompt-only, NOT a machine gate; inert on lexicon-less IRs + the `pass`
    strategy; the §3.3 language-invariant vs language-specific split for `localize`;
    `reconcile_inputs_preimage` UNTOUCHED → `fit-digest` byte-identical).
  - **C5** (this) — docs + SSOT sync (design.md §4/§5.2/§6.5/§7.2/§11.2/§12.6/§16/§27.4 + known-issues
    DR-2 build status + state.md). No code/test change; no `schema_version`/`ir_version` bump.
  - **Identity discipline:** the lexicon `{entry, delta}` is the ONLY new preimage component, moving
    the **artifact-id ONLY**; **no `schema_version` bump** (all 15 registry `_schema.yaml` at 1; the
    version-equality lint green over the 14 collections it scans) and **no `ir_version` bump**;
    `CONTENT_DIMENSIONS` stays 4; no new cascade rung; no `style-guides/` dir.
  - **Honest deferrals (registered):** schema-lint does NOT scan `lexicons/` entries (validated by
    `tests/test_lexicons.py`, not the CI schema-lint matrix scan — C1-review N1); L6 selection-level
    deferred; §12.6(b) lexicon-scope-default + brand-lock(b) deferred (brand-lock is Voice-only in v1).
  - **Gate:** final `uv run pytest -q` = **2546 passed** (C4); ruff + content guard + schema-lint clean
    (schema-lint's 14-collection matrix; `lexicons/` via `tests/test_lexicons.py`). Reports:
    `ops-handoff/dr2-build/`. See `docs/known-issues.md` DR-2.

- **Folder adapter — compose-capable + registered (2026-07-18).** Discovered while standing up
  `~/Developer/OptiquityTrader` (a non-Graphify Swift repo, READ-ONLY) as a folder-adapter source for the
  outline work: a folder source could ground but not compose (commitless + unregistered). Fixed — `0d2cc45`
  (git-HEAD `pin_commit` + a `budget` connection key) + `c4f481d` (single `default_adapters()` factory
  registers `{graphify, folder}`). Demonstrated live (artifact `a-1ebf747e75ccc422`, grounded in OT's
  `ARCHITECTURE.md`). See `docs/known-issues.md` Resolved. Reports: `ops-handoff/folder-fix/`, `folder-register/`.

### Quick-wins batch (2026-07-23)

Four small, independently-reviewed-CLEAN items, each committed to `main` under the standing cadence.
Current HEAD `551fc42`. Backlog impact: **GAP-5 → Resolved** and **#3 → documented ATX-only limit**
(no longer a deferral) in `docs/known-issues.md`.

- `bb51367` **item 1** — corrected the false "consumed at compose" annotation in 8 format entry bodies
  (§15 accuracy; docs-only, no tracked GAP).
- `37bd75c` **item 4** — retired the F1-sentinel BROADENING (#3) as a documented **ATX-only limit** (not
  a deferral): known-issues #3/#3a + `docs/design.md` §5.2 + the `sections.py` docstring.
- `ddcf593` **item 3** — added the `fsast` opt-in `cli` scope mode (argparse / CLI-flag grounding, MG-2;
  not tracked in `known-issues.md`).
- `551fc42` **item 2** — GAP-5 defense-in-depth hardening (all three sub-items, +5 load-bearing tests):
  (a) payload metadata secret re-scan, (b) `manifest._resolved_row` render-input-mismatch warn on the
  stale-fit branch, (c) serialize part-Div `#id` uniqueness check → **GAP-5 moved Open → Resolved**.

### DR-1 — HTTP shim + poll/webhook (BUILT, 2026-07-24)

The deferred DR-1 (HTTP interface for cloud-hosted orchestrators — Make / Zapier / n8n Cloud / Google)
is **BUILT** as an additive, transport-agnostic HTTP shim over the existing `invoke()` door
(`pipeline/api/http_shim.py`, `scripts/pipeline serve`; stdlib `http.server`, no new dependency, no
business logic). Commit range `2f29e88`, `3e8d5b6`, `6f58881`, `444f046`..`b0c7088` (HEAD `b0c7088`);
each coder → reviewer → (fix) → re-review CLEAN under the standing cadence.

- **Shipped shape:** **Tier-A** cheap / LLM-free verbs served synchronously (the same `invoke()` JSON
  envelope + the N-4 HTTP-status mapping); **Tier-B** paid verbs (`generate-next`, `render`) as
  **202-Accepted** with a client CHOICE of delivery — **poll** (always-available floor; a
  legitimately-running job is never told to resend, so no double-charge — the job-lifetime window +
  "already-running ⇒ don't re-spawn") OR an optional **webhook** wakeup ping (approved-host allow-list
  + SSRF block, validated at submit AND re-validated at delivery, no redirects, bounded retry, never
  crashes the runner). Mandatory fail-closed bearer auth, loopback-default bind, workspace allow-list,
  DoS guards; an advisory concurrency cap + the `rate-limit-backpressure`→429 backstop bound spend.
- **Prerequisites (standalone framework fixes, now Resolved):** `2f29e88` GAP-9 (workspace-root
  isolation) + `3e8d5b6` GAP-10 (render mint-claim double-spend) — an HTTP front makes both hotter, so
  they landed upstream first.
- **`begin-session{generate!=none}` (compose-in-one-call) DEFERRED (maintainer, 2026-07-24):** the
  TWO-CALL path is the supported approach — `begin-session{generate=none}` (Tier-A, instant, returns
  the session token) then `generate-next` (Tier-B, poll/webhook). The one-call 202-door is a 501
  placeholder.
- **Docs closeout (this):** `docs/known-issues.md` DR-1 → BUILT; the design.md §21.7 "same JSON
  envelope" amendment (admits the 202-ack + the poll status mapping as sanctioned additive wire shapes)
  + the "Not in this build" register row; mission `0.2.6`; the 4 load-bearing design records archived
  under `docs/archive/design-record/dr-design-passes/dr1-http-shim/` (+ `dr1-webhook-poll/`) so the
  code's `§C-`/`N-` citations resolve. Deferrals (Path B transport-chokepoint concurrency, webhook
  per-caller API keys, connection-IP-pinning for the DNS-rebinding residual, begin-session one-call)
  registered in `docs/known-issues.md` DR-1.
- **Gate:** `uv run pytest -q` = **3001 passed, 6 deselected**; ruff + content-guard + schema-lint
  clean. Reports: `ops-handoff/dr1-http-shim/`, `ops-handoff/dr1-webhook-poll/`.

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
- **✅ RESOLVED at step 39 — the step-33 §21.7-code HARD GATE (BINDING).** Step 39 threaded the real
  `("block",)` §21.7 codes (`empty-pool` from grounding, `hard-limit-exceeded` from reconcile) through
  `DriverError.stage_code`/`remediation_action` → `session._generate_next` (block status derived from the
  code's CodeSpec, class attr `code` untouched; NO fabrication — all 9 `_run_artifact`/`_run_deliverable`
  raise-sites were audited, the other 7 correctly stay code-less because their codes aren't in `ALL_CODES`),
  proven by a hermetic hard-limit block reaching generate-next with `code=="hard-limit-exceeded"`, zero
  subscription spend. The reviewer confirmed the closure is total, not partial. Historical gap (retained):
- **→ (historical, now resolved above) HARD GATE before `generate-next` is wired to the LIVE CLI (step-33 reviewer-ratified, BINDING):** a
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
  (Step 39 HONORED this gate: it never constructs `DefaultCurrencyResolver` on the mvp path — it passes an
  explicit fail-safe resolver at every edge — so the gate remains correctly OPEN, not crossed.)
- **→ future step (from step-39 review #4, BINDING carry-forward):** the standalone §21.8 `render` verb
  `not-found`s on any REAL composed artifact — `render.py::_render` (~L152) reads the canonical record as
  `{"ir": …}` but `compose._persist` stores the RAW IR (re-read raw at `compose.py:461`). A PRE-EXISTING
  step-34 integration gap (`_render`/`render_handler` untouched by step 39; step 39's render.py B1 change is
  the lowering path only, validated by the byte-identity test). §25 does not enumerate this verb so it did
  not block the MVP. Fix the artifact-record read (`{"ir":…}` vs raw IR) so standalone re-render/force works
  end-to-end. Also fold the 4 step-39 review MINORs (parallel `sweep_partial` could assert `missing` strictly
  shrinks; L6 evidence via stored effective view; live `ssot derive-state` CLI vs the library call).
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
- **→ Step 40 (from step-13 review) — RESOLVED (GAP-4):** (a) unknown-registry-root residual — a NEW
  top-level dir outside the whitelist passed the guard silently → hardened to a HARD-FAIL by F-b
  (`6b196a6`). (b) the SV11 diff clauses ran against a PR-base baseline in CI (per-commit) → superseded by
  the RELEASE-relative version-lint (`330fc6d`): baselines the last release via a committed marker, inert
  pre-release, so there is no PR-event-dependent wiring left to verify. See known-issues GAP-4 (Resolved).
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
- [x] P1 foundations 7–13 — scaffolding/CI · serialization · operator grammar · id family · schemas ·
      drift+migration · CI guards
- [x] P2 configuration 14–19 — registries (rendering, content, collections) · cascade M1+M2 ·
      M3+grounding · adapters · fanout+plan-hash
- [x] P3 store & generation 20–29 — store+claims · S0–S6 spine+guardrails · SSOT v1 · transport wrapper ·
      compose · reconcile · fit resolution · serialize core · **★28 first end-to-end output** ·
      serialize completion
- [x] P4 reviews/folios/API 30–35 — review gates · folios+types · API core I/II · discovery+retrieval ·
      emit-manifest
- [x] P5 closeout 36–41 — parallelism · G2 closure+finals · **★39 MVP (all 9 axes)** · cleanup sweep ·
      final verification + delivery

## Audit trail

Design-phase artifacts (skeleton, adversarial reports, fix ledgers, FR reports):
`/Users/david/Developer/_tmp/optiquity-content-pipeline/ops-handoff/` — plus the in-repo copies under
`docs/archive/design-record/`.
