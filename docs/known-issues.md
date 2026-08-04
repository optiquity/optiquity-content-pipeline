# Known Issues & Gaps

The single running list of **bugs and capability gaps** in the optiquity-content-pipeline that
need to be addressed. This is the place to log anything found in use or review.

Most entries below were surfaced by the build's own coder→reviewer→audit process (they were
previously scattered across `state.md` carry-forwards and the step handoff reports, now
consolidated here). **None is a v1 acceptance blocker** — they are the honest backlog.

**Entry format:** `Status · Severity · Symptom · Root cause · Impact/workaround · Proposed fix · Source`.
When one is fixed, move it to **Resolved** with the commit that closed it.

---

## Open

### GAP-3 — §21.9 currency resolver is a partial detector (not production-safe)
- **Status:** Open (intentionally unwired / dead code today)
- **Severity:** Medium (latent hazard — must not be wired as-is)
- **Symptom:** `discovery.DefaultCurrencyResolver` can report a deliverable as `fit_current=true` when
  it is actually stale (it only re-checks platform hard-limits, and its `except → stored_digest`
  fallbacks fail in the unsafe direction). If wired to `list deliverables {fit_current:false}` /
  emit-manifest, a stale deliverable would be silently omitted from a force/refresh loop.
- **Root cause:** the default resolver is a partial re-computation by design (it lacks the recipe/all
  reconcile inputs, which only the §21.9 production wiring carries).
- **Impact / workaround:** safe today — it is never constructed on any production path (every caller
  injects an explicit resolver; the MVP uses a fail-safe one). The gate is honored/open.
- **Proposed fix:** before §21.9 wires any production currency resolver, either complete the
  reconcile-/serialize-input re-read or flip the uncertainty direction to fail-safe (report
  NOT-current on any un-verifiable input / on error → over-force, safe under render idempotency), and
  fail-safe the `except` branches.
- **Source:** step-34 review HARD GATE.

### GAP-7 — The ideation phase (mission stage 1) is not built — topics must be hand-authored
- **Status:** Open (deliberate v1 scope boundary, tracked here as a missing capability)
- **Severity:** Medium–High (a whole missing pipeline stage — half of the mission's two-stage design)
- **Symptom:** The mission specifies a **two-stage** pipeline — **ideation** (source repo + audience →
  a ranked idea queue) then **generation** (idea → formatted artifact) — but v1 builds only
  *generation*. There is no ideation engine: nothing reads a repo's Graphify graph (god-nodes,
  communities, suggested questions) + audience personas to propose and rank content ideas. The nine-axis
  matrix starts from **topics** (§5.2, axis 1), which in v1 must be **hand-authored** as
  `users/<user>/workspaces/<workspace>/topics/<id>.md` entries (they may be manually seeded from Graphify's
  `GRAPH_REPORT.md`, but nothing generates them) before anything runs.
- **Root cause / rationale:** ideation internals were deliberately deferred from v1 — no ratified
  contract for how ideation should work; the ratified boundary is "hand-authored topic entries through
  the same interface." `docs/design.md:84` notes ideation/topic-sourcing "sits upstream of stage 1" and
  leaves it to the product plane; `docs/mission.md` §Role 2 describes the intended ideation engine.
- **Impact:** the system can generate content **for** a given topic across the full matrix, but cannot
  decide, discover, or rank **what** to write about — the operator supplies every topic manually. Half
  the intended product (repo → ranked idea queue) does not exist yet.
- **Proposed fix / when:** build the ideation engine as an upstream phase (repo graph + audience →
  ranked candidate topics) that emits the same `topics/` entries the generation pipeline already
  consumes, so it plugs into the existing interface with no downstream change. Requires a ratified
  ideation contract first. Post-v1.
- **Source:** `docs/mission.md` (the two-stage pipeline; §Role 2 "Ideation engine") + `docs/design.md:84`
  + the "Not in this build" register; maintainer asked it be tracked (2026-07-13).

### GAP-11 — The content guard's `templates/*` arm cannot default-deny a marker-less generic file
- **Status:** Open (accepted residual — documented, not a defect to fix; same class as the GAP-4a limit)
- **Severity:** Low (needs an actively mislabeled, marker-less client file dropped into a framework
  blueprint dir — no live path produces one; the two real instance signals are already caught).
- **Symptom:** `scripts/check-no-content.sh`'s `[W8] templates/*` arm scans the WHOLE `templates/`
  subtree (including `templates/workspace/**`) and LEAKS the two instance signals — an `x-*` path
  segment (SV5, §11.4) or an explicit `provenance: instance` line. But a **generic-named file carrying
  no `provenance:` line at all PASSES**: templates legitimately ship without provenance frontmatter, so
  this arm cannot default-deny on its absence the way the registry-root arm does. A marker-less
  client-authored file smuggled under `templates/` would therefore slip the guard.
- **Root cause:** `templates/` is FRAMEWORK MECHANISM (owner-agnostic blueprints, provenance framework
  by home, never tagged) and is deliberately **extensible** — so no allowlist/emptiness backstop is
  imposed. Absence-of-marker cannot be a leak signal where markers are legitimately absent.
- **Impact / workaround:** the guard is inline-documented as an accepted residual
  (`scripts/check-no-content.sh` `[W8]`); this is the **same class** as the GAP-4a marker-less-dir
  limit. The 8 shipped `templates/workspace/**` files are generic framework files (none `x-`-named or
  `provenance: instance`), so they pass legitimately. Provenance/schema PARSING is `schema-lint.sh`'s
  job, not this script's.
- **Proposed fix / when:** none planned — accepted. If ever tightened, it would key on a co-located
  marker (as the GAP-4a additive-registry-root coverage check does), never on an allowlist.
- **Source:** B7 template-home move (`a55febd`) + this §23 docs sweep (B9); the guard arm records the
  same reasoning inline.

---

## Deferred requirements

Intentional future scope — **recorded, not yet built**. Distinct from the bugs above: these are
capabilities we have deliberately deferred, kept here so the requirement is not lost.

### Foundation-coherence pass (2026-07-18) — the DR set is BUILD-READY, conditional on the build-entry checklist
A cross-DR integration / foundation-coherence architect pass (initial → whole-picture adversarial →
reconciliation) audited all six DRs **together** against the maintainer's four criteria (no scope
duplication · composition not awkward splits · extensible · generalizable). **Verdict: a sound
foundation to build on — no ratified decision re-opened, no redesign — CONDITIONAL on the build-entry
checklist below.** Full design records (every DR pass + this integration pass) are archived at
`docs/archive/design-record/dr-design-passes/`.

**Build order:** `F-a (ir_version generation-tolerant validation) → F-b (GAP-4 content-guard fix, gates
DR-2) → DR-6 → DR-3 → DR-4 → DR-5 → DR-2`.

**Build-entry checklist (GO only when every NO-GO is resolved; all integration specs, no redesigns):**
- **F-a** — `ir_version` bump-to-2 + generation-tolerant (known-compatible-set) validation; ledger →
  `LEDGER_REQUIRED` + `LEDGER_OPTIONAL`. **NO-GO for any IR-envelope edit** (independent foundation).
- **F-b** — GAP-4 content-guard known-root fix. **NO-GO for DR-2's `lexicons/` root.** → RESOLVED at DR-2 C1 (F-b guard-hardening `6b196a6`, consumed by C1 `13dd6e6` adding `lexicons` to `REGISTRY_ROOTS`).
- **#3** — the F1 sentinel section-grammar + section-constraint vocabulary, built **SHARED** at DR-4
  (consumed by DR-4 conformance AND the deferred DR-3 `constraint?`). **NO-GO for DR-4.**
  **→ RESOLVED at DR-4 (C1/C2, `pipeline/sections.py`; 2026-07-19):** the F1 sentinel section grammar
  (C1) + the C2 conformance vocabulary are BUILT and shared. **STILL DEFERRED (precise):** the DR-3
  `constraint?` consumer (DR-3 cut `constraint?` from v1, so #3's "consumed by the deferred DR-3
  `constraint?`" half awaits DR-3's resumption).
  **→ ATX-ONLY BY DESIGN — WON'T-BROADEN (documented, deliberate limit; ratified 2026-07-23):** the
  F1-sentinel BROADENING (recognize SETEXT `===`/`---` and blockquoted `> ##` headings) is **retired as
  a deliberate limit, not a deferral.** Section sentinels are **ATX-only** (`#`…`######`) **BY DESIGN**;
  SETEXT/blockquoted headings fail **closed** to body — never a mis-parse / mistyped section. Rationale
  (focused architect design pass, 2026-07-23 —
  `ops-handoff/sentinel-broadening/architect-01/report.md`):
  the F1 grammar feeds **only the conformance GATES** (block/pass), never any digest (`outline_digest` /
  `artifact-id` / `fit_digest` derive from other inputs) — so no grammar change can churn identity and
  broadening carries **no identity motivation**; the `---` form **cannot be disambiguated** in F1's
  line-scanner without a **fail-open** mis-parse (a frontmatter closing `---` read as an h2; a `---` rule
  after prose), which would break the fail-closed never-mis-parse contract (a faithful rule needs a
  block/frontmatter parser — an architecture change); blockquoted `> ##` is semantically wrong as a
  top-level section; and the value is **fully substitutable by writing `##`** (already fully supported).
  **#3a** — F1 sentinels **N-invariant** (a DR-3 build-time requirement: reserve the sentinel-significant
  structure when pinning N, so un-deferring F1 churns no `outline-digest`). **NO-GO for DR-3 + DR-4.**
  **→ HONORED — SATISFIED, now MOOT for the broadening (2026-07-19 reservation; 2026-07-23 close):** the
  N-invariance RESERVATION was made in DR-3 (`pipeline/outline.py`) and C1 respects it (section
  boundaries derive only from N-preserved structure — full-line content + leading indentation, never
  trailing whitespace / blank-run counts / nesting depth), so any future F1 grammar change churns no
  `outline-digest`. With the broadening retired as an ATX-only limit (above), this reservation is
  **satisfied and moot for the broadening**; it remains **honored** for the grammar as built.
- **#4** — extend the §16 RI5 reconcile-gate ordering (DR-4 structural gate + DR-6 coverage re-check +
  terminal hard-limit gate; joint hard-structural × hard-limit → block-and-report). **NO-GO for DR-4.**
  **→ RESOLVED at DR-4 (C8; 2026-07-19):** the DR-4 structural gate + the terminal hard-limit gate + the
  joint hard-structural × hard-limit **block-and-report** (the early-return refactor — both
  `structural_violations` and `blocked_limits` populate before any block-return) are BUILT. **STILL
  DEFERRED (precise):** the **DR-6 coverage re-check** leg of the ordering (DR-6 increment 1 built the
  Option-A advisory subset, NOT the reconcile coverage re-check — see the DR-6 build status below).
  **#4a** — per-section numeric limits are **DR-4 structural constraints** (section-addressed); the §16
  terminal gate keeps ONLY artifact/capacity limits. **Retract "abstract ≤N words already built."**
  **NO-GO for DR-4.**
  **→ RESOLVED at DR-4 (C8; 2026-07-19):** per-section numeric limits are now genuinely enforced at the
  reconcile STRUCTURAL gate (riding the venue's C2 schema); the §16 terminal gate keeps ONLY
  whole-artifact / capacity limits. `journal-concise` ships `abstract ≤ 800`. The stale "abstract ≤N
  words already built" claim is **RETRACTED** — it is built NOW, at the structural gate, not before.
- **#5** — the writer-contract co-occurrence rules + **"the writer emits `[@key]` markers ONLY and NEVER
  free-authors the `references` bibliography"** (a free bibliography is the SF-3 fabrication vector;
  `references` is a projection of the ledger). Ablate after each writer layer (GAP-8). **NO-GO for the
  writer contract.**
  **#5a** — the **three-context `[@key]` classifier** (grounding-span → grounding cite; `.framing`-span →
  bibliographic; **bare → forbidden**). **NO-GO for the writer contract.**
  **#5b** — narrow the DR-6 exemptions to genuinely non-declarative constructs + require a grounding
  channel for factual captions/cells; **REGISTER** the un-spannable-factual-content residual
  (headings, table cells — caught only by the advisory Review-1 audit).
- **#6** — grounding is enforced at **TWO loci over one ledger** (the DR-5 citation-resolution check is
  DR-5-owned), not "one chokepoint." **REGISTER.**
- **#7** — external-side (`side: external`) scenario-2 attribution = **compose-fixed literal prose**; the
  future DR-5 CSL indirect-citation surface extends it only for `side: internal`. **REGISTER for DR-5.**
- **#8** — `attestation.primary` is a **structured, one-file-extensible citation-descriptor carrier**
  (CSL-JSON-shaped/upgradeable), not a bare string. **NO-GO for the DR-6 ledger build.**

**Generalizability refinements (criterion 4):** the lexicon `mechanical` menu and DR-4 section-`type`
must be **open one-file-add carriers, not closed enums** (DR-5's `csl` and DR-3's `drive` facets are the
model). **Kept, unbreakable:** zero new `artifact-id` identity surface; the precedence chain (outline >
dimension-values; gates > everything); the §6.5 floor precedence (the DR-4×DR-6 "deadlock" is false);
`ir_version` as an evolvable foundation.

### DR-1 — HTTP shim + poll/webhook async door for cloud-hosted workflow orchestrators — BUILT
- **Status:** BUILT (2026-07-24) — **shipped as an additive HTTP shim over the existing `invoke()`
  door (`pipeline/api/http_shim.py`, `scripts/pipeline serve`): 2 standalone framework prerequisites
  (GAP-9, GAP-10, now Resolved) + a §21.9 design amendment + a 17-commit shim build, each reviewed →
  gate-green. The design questions are resolved; deferrals are registered below.** (The original
  design-era Deferred status is preserved in the design-status note near the end.)
- **Need:** The v1 external-actor door (GAP-2) is the local `pipeline invoke render` CLI, invoked by
  an orchestrator that can shell out to the **same machine** (v1's named consumer: self-hosted n8n via
  its Execute Command node). **Cloud-hosted** orchestrators — Make, Zapier, n8n Cloud, Google
  (Workflows / Apps Script), and others — cannot execute a local CLI; they can only call an **HTTP
  endpoint** (typically a webhook). To serve those users the pipeline needs an HTTP interface — added
  WITHOUT disturbing the CLI/`invoke` door (additive, transport-agnostic).
- **The shipped shape (BUILT).** A stdlib `http.server` front (NO new dependency) exposing `POST
  /invoke` (+ `POST /poll`) over the EXACT existing handlers — no business logic, a transport
  translation over the same stateless per-verb `invoke()` (§21.9: an OPTIONAL transport FRONT holding
  no LLM/session/correctness state; all cross-request state is on disk):
  - **Tier-A (synchronous).** The CHEAP, LLM-free verbs (`list`/`get`/`fetch-by-id`/`create-folio`/
    `add-to-folio`/`emit-manifest`/`emit-outline`/`begin-session{generate=none}` + the cheap
    `continue-session` actions) dispatch synchronously and return the SAME `invoke()` JSON envelope the
    CLI emits, with the N-4 HTTP-status mapping (200 = whole-invocation ok incl. a per-item block; 400
    unknown-verb; 422 invalid-token; 403 isolation-violation).
  - **Tier-B (202-Accepted, paid).** The PAID verbs `continue-session{generate-next}` and `render`
    answer a submit with **202-Accepted** — a NEW wire shape (`{status: accepted, job:{key,
    target_ids}, poll, [callback]}`, NOT an `invoke()` envelope) carrying the PREDICTABLE target ids
    (resolved LLM-free from the plan + cursor / the render primitives), then detach a `jobrunner`.
    `render` additionally runs an OPTIMISTIC-SYNC-then-202 fast path (a cache-hit / fast serialize
    returns 200 + output inline; a paid reshape exceeding the wait → 202 + the predictable
    deliverable-id).
  - **Delivery is a CLIENT CHOICE — poll OR webhook:**
    - **Poll (always available, the floor).** `POST /poll {workspace, key, target_ids}` resolves the
      job by target-id and maps its state to a status (200 done+output · 202 still-running · 429
      backpressure · 504 re-drivable-timeout · 4xx fatal). A legitimately-running job is **never told
      to resend** — the job-lifetime window + the "already-running → don't re-spawn" rule keep a slow
      paid job from being double-charged.
    - **Webhook (optional).** A submit MAY carry `callback_url`; on done/failed the pipeline POSTs a
      small WAKEUP ping (the client then FETCHES via the authenticated poll — the callback is NEVER the
      result payload). The `poll` block still ships, so poll stays the floor.
  - **Anti-double-charge (the load-bearing safety).** A paid submit is idempotent on an
    `idempotency_key` (n8n `$execution.id`; a missing key is a 400): a retry collides on ONE job
    (create-exclusive + H2 lease-steal). GAP-10 (Resolved) makes `render` CLAIM its mints, so a
    concurrent identical render is `claim-held`, never a double-spend. Jobs are §22.7-class LOSSY
    bookkeeping (no `artifact-id` preimage; a lost status just falls back to poll).
  - **Security posture (fail-closed throughout).** MANDATORY bearer/`X-API-Key` auth (constant-time
    compare, a configured SET for rotation), checked BEFORE path/body/dispatch; NO secret configured →
    `serve` REFUSES TO START (never accept-all). **DoS guards:** an over-cap declared Content-Length →
    413 before the body is read; a socket timeout drops a slow-loris. **Bind:** loopback (`127.0.0.1`)
    by default, never moved off; a non-loopback bind is a conscious choice REQUIRING an external
    TLS/auth proxy (the shim's auth is application-layer). **Workspace ALLOW-LIST** (a name-membership
    policy on TOP of the GAP-9 containment — 403 `workspace-not-served`; unset = serve-any behind
    auth), applied to BOTH /invoke and /poll (N-6). **Webhook SSRF + host allow-list**
    (`pipeline/callback_policy.py`): callbacks are OPT-IN / off-by-default (an empty list rejects
    everything); an approved host must ALSO clear an SSRF block (loopback / link-local incl.
    169.254.169.254 metadata / private / unique-local / unspecified / multicast / NAT64 / reserved /
    mapped-IPv6 all refused), validated at SUBMIT and RE-validated at DELIVERY (the DNS-rebinding
    re-check), NO redirect-following, bounded retry, and it NEVER crashes the runner; IDNA-hostile
    hosts are caught (UnicodeError → refuse).
  - **Spend bound.** An advisory pre-spawn concurrency cap (`_deny_over_capacity`) + the
    always-correct `rate-limit-backpressure` → 429 backstop (the subscription's OWN pushback, routed
    through the ONE terminal-status mapper) bound real overspend regardless of the advisory cap's
    raciness.
  - **`begin-session{generate!=none}` (compose-in-one-call) DEFERRED (maintainer, 2026-07-24).** The
    202-door for that one-call verb is a 501 placeholder. The supported path is TWO calls:
    `begin-session{generate=none}` (Tier-A, instant, returns the session token) then `generate-next`
    (Tier-B, poll/webhook) — which already covers the use case, so the one-call form is deferred, not
    a gap.
- **Commit chain (build order).** Standalone framework prerequisites first (both now in Resolved):
  `2f29e88` **GAP-9** workspace-name resolve-and-contain · `3e8d5b6` **GAP-10** render mint-claim
  (double-spend close). Then the design amendment `6f58881` **§21.9 C-1** (a persistent transport FRONT
  is allowed if stateless). Then the shim: `444f046` `jobs/` store subdir · `ab1efe8` `jobs.py` lossy
  record + TTL-steal lifecycle + poll resolver · `c3ffc50` detached `jobrunner` + verb-aware outcome
  router · `60f1db1` shim skeleton + `serve` + Tier-A dispatch + N-4 status mapping · `164dd39`
  fail-closed auth + DoS guard + config template · `9cc45a7` workspace allow-list + explicit loopback
  bind · `92b70b6` Tier-B `generate-next` submit + poll-by-id. Then the ratified poll+webhook rework:
  `42228b8` reshape the poll/submit window (a slow job is never told to resend) · `056e943` register
  the API handlers in the detached runner (Tier-B was inert) · `772afca` SSRF + allow-list callback
  guard · `b475409` accept + validate a callback URL at submit · `d7e7ad1` deliver the webhook wakeup
  ping (retry + re-validate + no redirects) · `82648dd` non-injected Tier-B integration harness (real
  spawn, fake claude) · `2dcc3fe` `render` as a Tier-B verb (optimistic-sync-then-202) · `270a4f1`
  advisory concurrency cap + 429 backstop · `b0c7088` IDNA hardening.
- **Decisions & corrections (RECORDED):**
  - **Poll-OR-webhook is a client CHOICE; poll is the floor.** The webhook is a convenience wakeup, not
    a delivery channel; a client that ignores `callback_url` just polls. Both read the SAME job record
    + the SAME §22.7 authorities.
  - **§21.9 amendment (C-1).** "The pipeline is not a long-running server" is AMENDED (not
    reinterpreted): an OPTIONAL transport FRONT MAY be persistent provided it holds no
    LLM/session/correctness state (commit `6f58881`).
  - **§21.7 "same JSON envelope" amendment (N-3).** The "same-envelope" invariant is AMENDED to admit
    the Tier-B 202-Accepted ack + the poll HTTP-status mapping as sanctioned ADDITIVE wire shapes
    (Tier-A + the terminal poll still carry the canonical `invoke()` envelope). See `docs/design.md`
    §21.7 (the DR-1 amendment bullet) and the "Not in this build" register row.
  - **The compose-in-one-call verb is DEFERRED, covered by the two-call path** (above).
  - **The two prerequisites (GAP-9, GAP-10) were fixed in the framework, not the shim** — an HTTP front
    makes both hotter (untrusted names; concurrent identical requests), so they belong upstream. See
    the Resolved entries.
- **Honest DEFERRALS (registered, not hidden):**
  - **Path B concurrency (transport-chokepoint presence wiring) DEFERRED.** v1 bounds spend with the
    advisory pre-spawn cap + the 429 backstop; a hard transport-level chokepoint that wires job
    presence into admission (Path B) is not built.
  - **Webhook per-caller API keys DEFERRED.** The outbound wakeup carries no per-caller credential; the
    client authenticates the subsequent FETCH via the shim's bearer auth. A per-caller callback secret
    is a later additive change.
  - **Connection-IP-pinning for the DNS-rebinding residual DEFERRED.** v1 re-validates the host at
    DELIVERY (re-resolve + re-check) — the v1 mitigation for DNS rebinding; pinning the exact connected
    IP to the validated one (closing the resolve→connect TOCTOU fully) is deferred.
  - **`begin-session{generate!=none}` (compose-in-one-call) DEFERRED** (above) — the two-call path is
    the supported approach; the one-call 202-door is a 501 placeholder.
- **Cross-refs:** the standalone prerequisites **GAP-9** (workspace-root isolation) and **GAP-10**
  (render mint-claim double-spend) are in **Resolved** below.
- **Design status (2026-07-13 → 07-24):** designed via an architect pass (initial → adversarial →
  reconciliation) + a planner pass + a focused poll/webhook reshape design; the load-bearing records
  are archived under `docs/archive/design-record/dr-design-passes/dr1-http-shim/` (+
  `dr1-webhook-poll/`), and the code's `§C-`/`N-` citations resolve there.
- **Source:** maintainer requirement, 2026-07-13 — "needed eventually for other users who use any
  cloud based workflow orchestrator (Make, Zapier, n8n, Google, and others)."
- **Gate:** final `uv run pytest -q` = **3001 passed, 6 deselected**; `ruff check .` clean;
  `scripts/check-no-content.sh` OK; `scripts/schema-lint.sh` clean. Coder/reviewer reports under
  `ops-handoff/dr1-http-shim/` + `ops-handoff/dr1-webhook-poll/`.

### DR-2 — Selectable style guides (writing-rule presets) → the compose-time `lexicons/` house-style registry — BUILT
- **Status:** BUILT (2026-07-21) — **shipped as the compose-time `lexicons/` registry (attributes-only
  house style, prompt-applied at compose): 5 gated commits + this docs closeout (C5). The design
  questions are resolved; the compose-only placement is SETTLED (DR-5 ratified it); deferrals are
  registered below.** (The original design-era status is preserved in the design-status note below.)
- **Need:** a way to select, per request, a named **style guide** that nudges the *writing* of an
  output — prose rules, house conventions, structural preferences — without re-touching the existing
  axes one at a time. There should be **standard** framework guides (e.g. a generic tech-website blog
  post) and **platform-fitted** ones (e.g. LinkedIn, Medium), and instances should be able to add
  **corporate** guides (a company's PR / website / documentation / communications style). A guide could
  be applied anywhere at any time (even where it would be odd), but standard/specific ones exist so the
  common cases are one selection.
- **Hard constraint (orthogonality):** a style guide must **not overlap or duplicate any existing
  dimension**, and must **not absorb Format or Platform attributes**. It nudges a dimension's
  direction; it does not replace it. Where a dimension value genuinely needs to change, the guide may
  carry an explicit **per-dimension override** entry (voice, format, platform, …) *plus* its prose
  rules — overrides, not redefinitions.
- **The core design question the maintainer raised (answer FIRST, before inventing anything):** a
  style guide is *already* mostly a bundle of existing-dimension choices (voice + format + platform +
  others) plus prose rules — so **maybe no new axis is needed**. It could be:
  1. a named **preset / bundle** of existing dimension selections (+ a prose overlay), reusable in any
     workspace — composition, not a new construct; or
  2. a genuine new **style-guide construct** — only if (1) provably cannot express it cleanly; or
  3. actually a **templating feature** — the maintainer noted the *structural/formatting* need
     ("more easily and directly specify a desired structure") may be a separate, missing **template**
     capability rather than a style guide at all.
- **Open questions for the architect:** (a) can existing dimensions — or a **one-file additive
  extension** of one (per the matrix rule) — cover this, and is that better than a new thing? (b) if a
  guide *is* warranted, what structure lets it apply *wherever appropriate without conflicting*
  (overrides + prose, with a clear precedence vs the cascade)? (c) overlap specifically with the
  **VOICES** axis, which already carries tone/knowledge level — where is the line? (d) is the real gap
  a **template** feature (structure) distinct from a style guide (prose / house rules)? (e) provenance &
  scope: framework-**standard** guides (`provenance: framework`) vs instance/**corporate** guides
  (`provenance: instance`), and where they live (workspace-scoped, per the isolation rule); (f) how
  prose "writing rules" coexist with the **ground-in-EXTRACTED-facts** rule (style shapes *how* it
  reads, never *what* is claimed).
- **Recommended process (not yet run):** an **ops-architect**-led design pass (initial → adversarial →
  reconciliation, maintainer-gated) that answers (a)–(f) and recommends *bundle vs new construct vs
  templating* — optionally seeded by a light research pass on how real corporate/platform style guides
  are structured. This is design work; it is **not** to be improvised during a fix.
- **Depends on / relates to:** the nine-axis matrix + cascade (§3–§4); the VOICES axis; a possible
  **template feature** (may be split into its own item if the architect finds the structural need is
  separable).
- **Source:** maintainer requirement, 2026-07-16 — selectable, non-overlapping style guides
  (standard + platform + corporate), with the explicit instruction to first check whether existing
  dimensions (or better templating) already cover it before inventing a new construct.
- **Design status (2026-07-16):** designed via an architect pass and reconciled to **`lexicons/`
  (compose-time) + a topic-less recipe** (the standalone `style-guides/` overlay + a new cascade rung
  were dropped as redundant). It was briefly **partially reopened by DR-5** (whether some house style
  must apply at **render** for per-venue variation) — **now SETTLED:** DR-5 ratified the inline
  mechanics as **compose-baked lexicon, labeled compose-only** (`docs/known-issues.md` DR-5 design
  status, "no deterministic render path exists; per-venue ⇒ re-compose"; the render-time path DR-5
  built is the CSL/`csl`-Presentation citation lever, not the lexicon). So the compose-only placement
  is confirmed and DR-2 shipped compose-only — the "build paused pending DR-4 / DR-5" hold is
  DISCHARGED.
- **Build status (2026-07-21) — DR-2 BUILT (compose-time `lexicons/` house-style registry; gate
  green).** The reconciled design shipped as **5 gated commits** (each: coder → reviewer →, where
  needed, fix-coder → re-review to CLEAN), under the standing commit approval. The `lexicons/` registry
  is a **class-(ii) content-side registry** (NOT a §5.4 axis, NOT a content dimension): its entries are
  **attributes-only** and are applied **prompt-only at compose**; the entry BODY is documentation only
  and is NEVER compose-consumed. Commits:
  - `13dd6e6` **C1** — stood up `lexicons/` (the 15th registry, `schema_version: 1`): attributes-only
    schema — `preferred_terms` / `banned_terms` / `proper_names` / `spelling` (enum `""|us|uk`) /
    `mechanical` (an OPEN bare map); all floor-empty. The doc-comment states the load-bearing
    invariant: every compose-consumed rule is an ATTRIBUTE — the entry body is doc-only, never
    compose-consumed (no `markdown` attribute). Generic `house-standard.md` entry (`provenance:
    framework`; editorial hygiene + public tech-name casing only, no client content).
    `scripts/check-no-content.sh` `REGISTRY_ROOTS` 14→15 (+`lexicons`) — **mandatory**, else the F-b /
    GAP-4a additive-registry-root guard hard-fails on `lexicons/_schema.yaml`. Resolver works off the
    co-located SV4 schema with **no `DIMENSION_COLLECTIONS` edit**; `lint.py`'s matrix `REGISTRY_ROOTS`
    is UNCHANGED (class-(ii), not a §5.4 axis).
  - `b06bfaa` **C2** — threaded the resolved lexicon `{entry, delta}` into the §7.2 artifact preimage
    as a **top-level, omit-when-absent** component (the DR-3 `outline-digest` twin, but
    **dimension-shaped**: built with `_require_entry_id` + `delta_vs_floor` over ATTRIBUTES, shape-
    guarded by the **F7 dimension machinery**, never the body). `_require_artifact_preimage_shape`
    top-level set extended to `{"outline-digest","lexicon"}`. Identity: **`artifact-id` ONLY** (never
    `fitted_id`/`deliverable_id`); omit-when-absent → byte-identical corpus; **RI11** (same
    `(entry, delta)` → same id; a rule edit → a new id). No `schema_version` / `ir_version` bump.
  - `1603288` **C3a** (`fix(lint)`) — implemented the **§11.2 additive-at-floor exemption** in SV11
    clause 1: a new attribute riding its type's empty L0 floor needs **NO version bump** (the
    enforcement now MATCHES the ratified §11.2 policy — the exemption was described but never
    implemented). `_is_empty_floor_default` + `_is_additive_at_floor` (exempt ONLY when every shared
    spec is byte-identical AND every new attribute rides its empty floor). Removals, meaning/type/
    default changes, and non-empty-default adds **still fire**; adversarially reviewed for holes.
  - `9380913` **C3b** — wired the `lexicon` selection at **L3 (workspace) + L5 (recipe)** (recipe
    beats workspace), **L6 DEFERRED** (F4a: `lexicon` in `_WORKSPACE_KEYS` ONLY, **never global/L2**;
    zero L6 surface — no `SelectionRequest`/`RunSelection`/fanout field). Recipe schema:
    `lexicon: {type: text, default: ""}` (topic-mirror, additive-at-floor — legal without a bump per
    C3a). **ONE resolution, TWO consumers:** the `EntryBinding` → the artifact preimage (`plan.py`),
    the resolved attributes → the writer block (`driver.py`); the compose-context lexicon provably
    equals the preimage `lexicon.entry`. `compose.py` + `writer.md`: an attribute-only, **byte-stable**
    lexicon context block, **prompt-only** application. `folios` `RECIPE_SLOTS += "lexicon"`.
  - `6148c64` **C4** — the §16 reconcile **ADVISORY preserve** clause: `build_reconciler_prompt`
    surfaces `binding.preimage.lexicon`'s `{entry, delta}` into the prompt context, read-only +
    omit-when-absent (inert on lexicon-less IRs and on the `pass` strategy). `reconciler.md` advisory
    clause 9 is **loudly marked NOT machine-checked**, with the §3.3 language split (language-invariant
    rules — proper-name casing, `banned_terms`, `mechanical` — hold under `localize`; language-specific
    — `spelling`, English `preferred_terms` — may not transfer). `reconcile_inputs_preimage` is
    **UNTOUCHED** (the lexicon never enters it — already covered by the `artifact-id`, §16-excluded —
    so every `fit-digest` is byte-identical). No new IR field; no `FidelityViolation`/re-ask.
  - **C5** (this) — docs + SSOT sync (design.md §4/§5.2/§6.5/§7.2/§11.2/§12.6/§16/§27.4; this entry;
    state.md). No code / test change; no `schema_version` / `ir_version` bump.
- **Decisions & corrections (RECORDED):**
  - **Identity correction — entry-id → `{entry, delta}`.** The preimage carries the FULL `{entry,
    delta}` pair (dimension-shaped), not just the entry id — so an M1 attribute deviation over a
    shipped lexicon entry churns the id, closing the same-id/different-bytes hole a bare entry-id would
    leave open.
  - **The attributes-only / no-body identity invariant.** Only the schema-declared ATTRIBUTES are
    compose-consumed and identity-bearing; the entry BODY is documentation and moves no id.
  - **Prompt-only application (byte-stable block).** House style enters the writer prompt as an
    attribute-only context block; default-`""` → the plan/compose bytes AND `artifact-id` are
    byte-identical (every existing recipe rides the floor); a selected lexicon changes bytes AND id
    together.
  - **Cascade — L3 (workspace) + L5 (recipe), L6 DEFERRED, never-global (F4a).** No new dimension, no
    new cascade rung; `CONTENT_DIMENSIONS` stays 4.
  - **Reconcile-from-binding (advisory).** §16 preservation reads the applied rules from the binding
    preimage and is a prompt recommendation, NOT a machine gate — contrast the C7/C8 HARD gates.
  - **The §11.2 additive-at-floor lint exemption (C3a)** — the policy prose now has matching
    enforcement in SV11 clause 1.
- **Identity discipline (DR-2):** the lexicon `{entry, delta}` is the ONLY new preimage component and
  it moves the **`artifact-id` ONLY** (omit-when-absent → every lexicon-less artifact-id byte-
  unchanged; a selected lexicon re-mints loudly); **no `schema_version` bump** (all 15 registry
  `_schema.yaml` files stay at 1; the version-equality lint stays green over the 14 collections it
  scans) and **no `ir_version` bump**; `fit-digest` / `render-digest` corpora unperturbed (the lexicon
  never enters the reconcile-inputs or serialize preimage).
- **Honest DEFERRALS (registered, not hidden):**
  - **Schema-lint does NOT scan `lexicons/` entries** (C1-review N1). `lint.py`'s matrix
    `REGISTRY_ROOTS` is the 9-axis + 5-named MATRIX (a §5.4 axis surface); the class-(ii) `lexicons/`
    entries are validated by `tests/test_lexicons.py`, NOT by the CI schema-lint scan. (The CONTENT
    guard `scripts/check-no-content.sh` DOES scan `lexicons/` — its `REGISTRY_ROOTS` is 14→15 — this
    deferral is about the SCHEMA lint only.)
    **✅ DISCHARGED 2026-07-29 (increment-C closeout):** `lexicons` was added to `lint.py::REGISTRY_ROOTS`,
    so schema-lint now scans `lexicons/` too (collections 15→16; the schema-lint and content-guard
    `REGISTRY_ROOTS` are now the identical 16-member set). A fresh ops-architect pass found the original
    "class-(ii), not a §5.4 axis" rationale insufficient: the `diagram-styles` registry added in DR-7/C is
    equally non-axis yet IS linted, and — unlike diagram-styles — a lexicon's `{entry, delta}` RIDES the
    artifact-id preimage, so it needs SV11 schema-evolution discipline (bump-on-meaning-change + a migration
    step) MORE, not less. Verified green (schema-lint clean at 16 collections; the `tests/test_lexicons.py`
    all-schemas version-equality test still passes). See `ops-handoff/lexicon-analysis/architect-initial.md`.
  - **L6 (run) selection-level DEFERRED** — the lexicon has no run-override surface in v1 (F4a keeps it
    workspace/recipe-scoped); adding L6 is a later additive change.
  - **§12.6(b) lexicon-scope-default + brand-lock(b) DEFERRED** — brand-lock is Voice-only in v1; the
    `authoritative`-style lexicon-scope-default (elevate a house lexicon above the recipe/run) is a
    flagged §12.6 extension, not built.
- **Gate:** final `uv run pytest -q` = **2546 passed** (C4); `ruff check .` clean;
  `scripts/check-no-content.sh` OK; `scripts/schema-lint.sh` clean (its 14-collection matrix **at the DR-2
  gate**; the class-(ii) `lexicons/` was then validated by `tests/test_lexicons.py`, not this scan —
  **`lexicons` was later brought under schema-lint on 2026-07-29; see the ✅ DISCHARGED note above**).
  Coder/reviewer reports under `ops-handoff/dr2-build/`.

### DR-3 — Optional artifact outline (pre-generation; dual output + input; outline-driven precedence) — design question
- **Status:** Deferred (not in v1) — **requirement + open design questions recorded; to be designed
  *jointly* with DR-2 by an architect (dimensions × style guide × outline seen together).**
- **Need:** let the user optionally generate a document/artifact **outline first**, review / **edit**
  it, and then generate the final artifact. The outline is **dual-natured**:
  - an **OUTPUT** — a first-class final artifact format in its own right (you can render just the
    outline); and
  - an **INPUT** — it directs the **content and/or structure** of the final prose artifact.
- **User control:** the user specifies whether the outline's **content**, its **structure**, or
  **both** drive the final artifact.
- **Precedence (the load-bearing architectural point):** when an outline drives generation it must have
  **far more influence than any other content- or dimension-related input** — it **outranks the
  dimensions** for what / how the artifact is written. The architect must place the outline in the M2
  cascade / precedence so it can dominate content + structure **without breaking orthogonality**.
- **Integration:** the outline must compose **elegantly with the nine dimensions AND the rendering
  system, as both an output and an input**, and coexist with DR-2 (style guide). How it enters as an
  input, how it is produced / edited as an output, and how it is fed back are all part of the design.
- **The core design question (answer FIRST, like DR-2):** is an outline **even necessary** if an
  artifact's **GOALS** are specified with the appropriate level of detail and precision? The architect
  must determine — (1) **is an outline needed at all?** (2) if **yes**: its **scope and design** (what
  it contains, how it is edited, how it is fed back as an input, its precedence, and its output-vs-input
  modes); (3) if **no**: what mechanism instead keeps an artifact's **focus / structure correct per
  artifact type** (e.g. more precise / structured **goals**, or a Format structure attribute — cf.
  DR-2 (d)).
- **Relationship:** **separate** from DR-2 (style guide) but **must be designed together** with it and
  the dimensions — the maintainer's instruction is that one architect sees **dimensions + style guide +
  outline** interacting, especially the precedence model (outline > dimensions when driving; style
  guide *nudges* a dimension).
- **Leads (not decisions — for the architect):** outline-as-output may resemble a new **output-type /
  format**; outline-as-input may resemble a new **pre-generation stage / input channel** that seeds
  compose; both must be tested against the one-file-add + orthogonality rules.
- **Source:** maintainer requirement, 2026-07-16 — optional editable outline that can be a final
  artifact and/or a high-influence input driving content and/or structure, to be assessed for
  necessity vs. sufficiently-precise goals.
- **Design status (2026-07-17) — RATIFIED (representation):** designed via an architect pass
  (initial→adversarial→reconciliation) plus a focused representation sub-pass; **necessity confirmed**
  (the editable dual output+input intermediate no reusable axis can provide). **Representation ratified:
  C3 — the canonical outline is plain Markdown** (no new internal format), content-addressed by an
  `outline-digest`; it becomes an IR **only at emit**, via a thin bridge realizing it as an ordinary
  **`Format=outline` artifact** (so it renders to any output type — md/plain/pdf/epub — through the
  existing serialize/payload machinery, and is fetchable). Compose ingests the same normalized Markdown.
  **Ratified v1 scope cuts:** holistic Markdown (no machine section-parse), `constraint?` deferred,
  multi-part formats deferred; the `outline-digest`-in-own-preimage exception ratified. **Open:** the
  compose-input-brief quality **ablation** (build-time). **Build paused** behind DR-4 / DR-5 (templates
  and per-output style interact with the outline).
- **Build decision (2026-07-18) — RATIFIED at the plan gate (planner initial → adversarial → reconciliation;
  reports `ops-handoff/dr3-build/0{1,2,3}-*`).** The whole-picture adversarial exposed that the drive facets
  (`use-sections?/use-order?/intents-must-cover?`) **change the composed bytes**, so leaving them off the
  artifact-id preimage (the initial plan's `grounding_posture` analogy) reintroduces the same-id/different-
  bytes collision the `outline-digest` closes. Two horns were surfaced; the maintainer chose:
  - **Decision A — horn (a): fixed byte-neutral drive posture.** v1 pins ONE posture — **the outline drives
    both content AND structure** (the usual want) — baked as a compose constant, so the `outline-digest`
    alone is byte-determining and DR-3 keeps **exactly one** preimage component (no §7 re-ratification). The
    per-request "content / structure / both" facet choice is **RETIRED, not merely deferred:** hand-editing
    the outline covers the "I want only structure/content" case (small edits are easier), and an unwieldy
    outline can simply be **abandoned in favor of fixing the recipe's goals** — which is the real lever. Horn
    (b) (a second `drive-config` preimage component delivering per-request facets) was **rejected on design
    grounds, not just cost:** a facet knob can **mask badly-constructed goals or unavailable source content**
    behind an outline override, hiding the real problem. This supersedes the original "user specifies
    content/structure/both" requirement.
  - **Decision B — B1 (usable product).** Build the full dual output+input feature end-to-end (emit bridge +
    pre-compose store + drive path + a minimal ingest/emit/drive trigger) so it is invokable with
    **hand-authored** outlines; **defer only the LLM drafter** (a named DR-3 backlog, GAP-7 mirror).
  - **Verb surface — REVISED at the C6 gate (2026-07-18):** ingest + drive ride the existing session verbs,
    but the maintainer chose an **explicit new `emit-outline` `KNOWN_VERBS` verb** for the outline-as-OUTPUT
    trigger (over the no-new-verb driver-branch or deferral) — so a user can realize a hand-edited outline as
    a byte-faithful `Format=outline` artifact (renderable/fetchable). This supersedes the reconciliation
    plan's provisional "no new verb" assumption; the emit verb wires the already-built `build_outline_ir`
    (Commit 4) through the dispatch, completing B1's dual output+input capability.
  - **Plan:** the reconciled foundation+feature plan (`03-planner-reconciliation`) — Commits 1-3 identity-safe
    foundation (landed), 4-6 the emit bridge / store / drive path (landed), the **emit verb** (this decision),
    then the R1 ablation + design-authority doc-sync. Built under the standing coder/reviewer/fix cadence.
- **Build status (2026-07-18) — DR-3 BUILT (horn (a) / B1); usable product, gate green.** The full
  dual output+input feature shipped as **seven** gated commits (each: coder → reviewer →, where
  needed, fix-coder → re-review to CLEAN), invokable with **hand-authored** outlines:
  - `48393f8` **outline foundation** — `pipeline/outline.py`: the identity-safe normalizer `N`
    (`normalize_outline`, idempotent) + `outline_digest` = `sha256_hex(N(md))` (a bare 64-hex
    content address, never a §7.4 id root) + `accept_outline` (substance floor + secret scan);
    reserves the #3a F1-sentinel N-invariance forward-contract. Touches no identity/preimage/
    registry surface.
  - `f81d7a4` **`outline-digest` preimage extension** — an OPTIONAL top-level `outline-digest` key
    on the §7.2 artifact preimage, **omit-when-absent** so every existing `artifact-id` re-mints
    byte-identical (the zero-churn guarantee); a 64-hex whitelist (stronger than the §7.3/secret
    blacklists, and sidesteps the `ir`→`ids` import cycle); the R4 two-home docstring separates
    the emit own-body digest from the drive-path content-address input. Horn (a): no `drive-config`
    key.
  - `6d7273d` **`formats/outline.md`** — the one-file framework `Format=outline` entry: provenance
    framework, single-part / non-parametric (`parts` rides the `[]` floor, like `readme`), a
    platform-agnostic planning scaffold. Pure one-file add (no second edit; guard green).
  - `6f327c6` **emit bridge `build_outline_ir`** — wraps `N(md)` as an ORDINARY `Format=outline` IR
    (empty ledger, no `data-fact` spans) via the real `build_ir`, persisted through the existing
    no-replace `write_new` (idempotent). No new IR type / schema / registry root; `api/render.py`
    untouched, so the outline renders to any output-type through the existing path.
  - `c562ec1` **pre-compose outline store** — `pipeline/outline_store.py`: `put_outline`/
    `get_outline` keyed by the BARE `outline-digest` (a dedicated `outlines/` dir, created
    on-demand, NOT in `STORE_SUBDIRS`); **retain-all** in v1 (byte-compared idempotency; a
    same-key/different-bytes collision raises loudly). Zero `pipeline.ids`/`parse_id` coupling
    (import-lint enforced).
  - `90e5f1a` **outline drive path** (horn (a), fixed posture) — `plan.py`/`compose.py`/
    `driver.py`/`fanout.py`/`api/session.py`/`writer.md`: the outline enters the writer prompt as
    a **high-salience FIXED-posture brief** (drives content AND structure, outranking the
    dimensions for skeleton/emphasis/order); a **digest-fidelity guard** raises `ComposeError` on
    any brief↔pinned-digest mismatch before any LLM/persist (never silent). The driven id rides
    `outline-digest` only (no new preimage key); the B2/grounding total rules hold — the brief is
    prompt-only, sets no cascade attribute, adds no ledger fact. Rides the existing session verbs
    (no new `KNOWN_VERBS` verb).
  - `db7979a` **`emit-outline` verb** — the maintainer-chosen explicit output trigger: a
    hand-authored outline + a target coordinate → a byte-faithful `Format=outline` artifact (via
    `resolve_compose` + `artifact_preimage(outline_digest=)` + `build_outline_ir`); the id rides
    the `outline-digest` only; re-emit is an `already-materialized` no-op; empty/secret → a typed
    block, nothing persisted. Reachable via programmatic `invoke()`, deliberately NOT CLI-wired
    (render + fetch only) and NOT a `continue-session` action. Completes B1's dual output+input
    capability. (The C6-gate ruling behind this verb was recorded at `3936fc6`.)
- **Identity guarantee:** non-outline `artifact-id`s are **byte-unchanged** (the omit-when-absent
  preimage); the driven/emitted id rides the SINGLE `outline-digest` component — horn (a) adds no
  `drive-config`/facet key, so no §7 re-ratification.
- **R1 compose-input-brief ablation — BUILT + RUN (directional, n=1; 2026-07-18).** Harness
  `scripts/dr3_outline_ablation.py` (+ hermetic `tests/test_dr3_ablation.py`) grounds ONE coordinate
  once, then composes twice over identical facts — V0 (no outline) vs V1 (outline brief) — and scores
  outline-fidelity. **LIVE** on `mvp-demo` / the real optiquity-site graph (28 EXTRACTED facts, topic
  `x-architecture-overview`), TWO outlines:
  - *generic scaffold* (topic-agnostic section intents): V0 struct 0.40 / content 0.23 vs V1 struct 1.00
    / content 0.50 — Δ **+0.60 struct, +0.27 content**.
  - *grounded outline* (every point traced to a real EXTRACTED fact): V0 struct 0.17 (1/6) / content 0.83
    vs V1 struct 1.00 (6/6, in order) / content 0.91 — Δ **+0.83 struct, +0.08 content** (V1 also −445
    bytes: more focused).
  **Interpretation (honest):** the brief's effect is **structural** — it decisively imposes the section
  skeleton + order (V1 realizes ALL headings in order; V0 alone realizes ~1/6–2/5). **Content** steering
  is SMALL once the outline is faithful to the grounding (V0 already covered 84/101 keywords because the
  outline and the writer draw from the same facts); the generic run's larger content Δ was largely an
  artifact of the scaffold's arbitrary vocabulary, not real steering. This matches the design intent — the
  outline ORGANIZES grounded facts, it cannot inject new ones (no fabrication vector; §6.5 floor). Identity
  sanity held live both runs (V0 4-key/outline-less, V1 rides the digest, distinct ids). Directional, NOT
  statistical — the design was safe regardless; this confirms the precedence works on the real pipeline.
- **DEFERRED (not built):** the **LLM outline drafter** (a named DR-3 backlog, GAP-7 mirror).
- **Gate:** final `uv run pytest -q` = **2135 passed, 6 deselected**; `ruff check .` clean;
  `scripts/check-no-content.sh` OK. The design-authority doc-sync (design §5.2/§7.2/§12.1/§15/
  §21.1/§27.3) landed alongside. Coder/reviewer reports under `ops-handoff/dr3-build/`.

### DR-4 — Content templates: typed non-text slots + structure + constraints (Format-adjacent) — design problem
- **Status:** Deferred (not in v1) — **open design problem; to be specifically scoped by an architect
  before anything is built** (the line and the vocabulary are not yet known).
- **Need:** a Format-related construct providing a reusable **skeleton with typed slots** — including
  **non-text elements** (a table with specified columns, a figure/image with a caption, a chart, a
  callout/aside, form-like fields) — plus **per-slot constraints** (required/optional, length limits,
  element counts, ordering). This is beyond Format's prose rhetorical body and beyond the text-only
  outline (DR-3): it adds **structure and design *details*** the current axes have no home for.
- **Flexibility requirement:** a template must **flex with the content and the outline** — length
  differences, and added/removed elements — rather than being a rigid mold. A scaffold, not a fixed form.
- **Driving example:** the same academic paper published in **three journals**, each with different
  **template requirements** (abstract ≤N words, a structured methods section, figure/caption rules,
  required/forbidden sections) — all from **one recipe / one IR**.
- **Hard constraint (orthogonality — maintainer's):** scope it so it **does not encroach on the
  established dimensions** — Format (genre), Platform (venue/limits), Presentations (visual/design),
  Outline (per-artifact text plan), Voice/lexicon (style). It adds structure + design *details*; it does
  not re-own those axes.
- **Open questions for the architect:** (a) **where is the line** between a template and Format /
  Platform / Presentations / Outline? (some journal template requirements may legitimately BE Format or
  Platform fields — decide which). (b) **what vocabulary** (slot types, element kinds, constraint kinds)?
  (c) how does it stay **flexible** for length/element differences? (d) relation to the **deferred outline
  `constraint?`** field (DR-3) and to `format.parts`. (e) **naming collision:** Presentations already has
  a Pandoc `template`/`reference_doc` field for *visual rendering* — a *content* template is a different
  thing; disambiguate. (f) is **"a journal" a Platform**, and are template requirements per-Platform /
  per-Format?
- **Relationship:** Format-adjacent; linked to DR-5 (per-venue variation) and DR-3 (outline); shares the
  academic-paper driving example.
- **Source:** maintainer requirement, 2026-07-16 — a template adding structure + non-text details +
  constraints, scoped not to encroach on the dimensions, flexible to content/outline length and element
  changes.
- **Design status (2026-07-17) — RATIFIED (design; build paused):** designed via research → architect
  initial → **whole-picture adversarial** → reconciliation. The initial's "enrich `format.parts`" home
  was **overturned** (parts are packaging sub-outputs, not rhetorical sections; it reversed the DR-3 B2
  rule and hit the IR `parts` XOR `body`). **Ratified shape:** a content template is a **typed-section
  conformance envelope over the outline's sections** — DR-3 and DR-4 **unify** (the outline IS the
  section skeleton; DR-4 is the typed constraint contract over it), on the **body-skeleton surface**,
  NOT `format.parts`, NOT the T7-reserved IR `constraints?` field (DR-4 gets its OWN conformance field).
  Vocabulary: `type` enum + `?`/`*`/`{n,m}` cardinality + a constraint menu + error/warning/info
  severity. **Maintainer chose the HARD structural guarantee** (2026-07-17): per-venue required/forbidden
  sections **BLOCK** — which **un-defers DR-3's machine-section-parse** (the F1 sentinel grammar + F5
  hard gate). Venue tightening = a new **hard structural class** on Platform's per-format projection + a
  **reconcile structural gate**; plus a base structural gate at compose/Review-1. A **journal = Platform
  + Presentation coordinates, NOT a recipe** (dissolves the DR-2 recipe-bundle collision; house style =
  an L3 baseline). **v1 = whole-section conformance; nested-in-prose slots deferred.** ZERO new
  `artifact-id` preimage component. Full design pass: `ops-handoff/dr4-dr5-templates-style/`.
- **Build status (2026-07-19) — DR-4 BUILT (typed-section conformance; three-venues-one-paper; gate
  green).** The ratified template shipped as **11 gated commits** C1–C11 (each: coder → reviewer →,
  where needed, fix-coder → re-review to CLEAN), under the standing commit approval. DR-4 is realized
  as a **typed-section conformance envelope over the outline's sections** (DR-3 × DR-4 unified) — NOT
  `format.parts`, NOT the T7-reserved IR `constraints?` field: DR-4 got its OWN `section_conformance`
  field. **Horn-a section-typing SD-1..SD-5; D-8b = RECORD-NOW.** Commits:
  - `b0ee351` **C1** `pipeline/sections.py` — the F1 sentinel section grammar
    (`parse_sections(normalize_outline(md))`; `Section=(level,role,type,heading,body,span)`;
    role=`{#id}` else auto-slug; the OPEN one-file-add `SECTION_TYPES` frozenset
    `{prose,figure,table,callout}` — extend the set, NOT a closed enum). ATX-only (SETEXT/blockquote
    fail-closed); honors the #3a N-invariance reservation.
  - `d005ae4` **C2** `pipeline/sections.py` — the conformance vocabulary: `Rule = Presence|Order|Count|
    Length`, role/type-axis `Selector`, `{error,warning,info}` severity, `check_conformance(sections,
    schema)` — a PURE, side-effect-free checker.
  - `cdce299` **C3** `formats/_schema.yaml` + `formats/academic-paper.md` — the Format `section_schema`
    attribute (floor `[]`); academic-paper requires abstract/methods/results (role selectors, error),
    asks the canonical order (warning), caps the abstract (warning).
  - `3c158b8` **C4** `pipeline/ir.py` — the `section_conformance` IR field (additive-optional via `keys
    ⊆ TOP_LEVEL_KEYS`, OMIT-WHEN-ABSENT, NOT in `binding.preimage` → identity-neutral, no `ir_version`
    bump).
  - `661ba5d` **C5** `pipeline/compose.py` + `pipeline/api/results.py` — the HARD platform-neutral base
    structural gate at compose (error → bounded re-ask → `section-conformance-violation` block); EXEMPT
    for a non-outline body; advisory (warning/info) deferred to Review-1 (D-4). `ALL_CODES` 27→28.
  - `92cb3ef` **C6** `platforms/_schema.yaml` — the Platform `format_structural` per-format HARD class
    (floor `{}`), sibling of `hard_limits`, M2-EXCLUDED; the S-3 disjointness lint (no section-limit
    name double-homed with a `hard_limits` key).
  - `b8a7436` **C7** `pipeline/reconcile.py` — the preserve-through + no-mint role backstop (**the
    section-typing role-forgeability backstop**; `structure-not-preserved`, rides the bounded fidelity
    re-ask), scoped to schema-referenced keys (FOLDED SHOULD-FIX #2 — a non-schema reshape is NOT
    blocked); the `format_structural` request fields (INERT here).
  - `4cea5fa` **C8** `pipeline/reconcile.py` + `driver.py` + `cascade.py` — the reconcile STRUCTURAL
    gate (per-venue, C2 `check_conformance`), the **5th OMIT-WHEN-FLOOR `structural` preimage
    component**, the early-return refactor (joint structural + limit → both concern-sets), #4a
    per-section limits RE-HOMED here, the M2-exclusion of `format_structural`.
  - `1fc0d0f` **C9** `pipeline/filters/section_attr_validity.py` + `dispatch.py` + `serialize.py` — the
    **SD-5 STRIP validity transform** (public writers strip bare `type`/`role`, keep `{#id}`) + the
    omit-when-absent `section_attr_transform_version` in the serialize preimage.
  - `23e06a2` **C10** `platforms/journal-*.md` + `presentations/journal-*-look.md` + the integration
    test — the three-venues-one-paper driving example (journal-strict FORBIDS acknowledgements;
    journal-structured REQUIRES discussion; journal-concise #4a `abstract ≤ 800` + tight `max_chars`);
    proves the block/fit diagonal (each paper variant blocks exactly one venue, siblings continue §6.4).
  - **C11** (this) — docs + SSOT sync (design.md §5.2/§12.7/§15/§16/§17/§27.4; this entry; state.md) +
    the R2 accuracy comment (`reconcile.py`) + the N-3 docstring fix (`ids.py`). No production logic
    change; no `schema_version`/`ir_version` bump.
- **Identity discipline (DR-4):** additive-at-floor everywhere; **no `schema_version` bump** (all 14
  registry schemas stay at 1; the global version-equality lint stays green) and **no `ir_version`
  bump**; the reconcile **OMIT-WHEN-FLOOR `structural`** component (floor `{}` → no `structural` key →
  byte-identical `fit-digest`) and the serialize **OMIT-WHEN-ABSENT** `section_attr_transform_version`
  (fires only on a typed public render) keep every existing artifact-id / fit-digest / render-digest
  byte-identical (golden corpora unperturbed). **ZERO new `artifact-id` preimage component.**
- **Section-typing settled design SD-1..SD-5 (RECORDED):**
  - **SD-1** — `type=` OVER `.class`: a section's structural KIND is declared as a pandoc heading
    key-value attribute `## H {#id type=figure}` (not a `.class`); a single bare interior word voids
    the block → literal heading, so `type=` is the ratified carrier.
  - **SD-2** — `{#id}` OVER `{role=}`: the section ROLE is keyed by the explicit `{#id}` anchor (else the
    pandoc auto-slug of the heading text) — NOT an explicit `role=` attribute; a BARE key, never a §7.4
    id, never `parse_id`-parsed.
  - **SD-3** — DROP the content-KIND check for v1: v1 does NOT validate that a `type=figure` section
    actually contains a figure (no content-KIND validator); `type` is a DECLARED structural kind trusted
    at the author layer (the content-KIND validator is registered deferred, below).
  - **SD-4** — HYBRID role default + RENAME-STABLE binding: the role defaults to the heading's auto-slug
    (explicit `{#id}` wins) and is the STABLE section key across edit/reshape — C7's preserve-through
    rides it.
  - **SD-5** — STRIP-INVALID-KEEP-VALID at public render (bare `type`/`role` stripped, `{#id}` kept) —
    **BUILT in C9.**
- **FOLDED SHOULD-FIX #3 — the SD-5 DR-5→DR-4 reassignment (RECORDED).** SD-5 was originally handed to
  DR-5 by the section-typing reconciliation; it is now BUILT in DR-4 (C9) under the ratified **HARD
  validity requirement + FULL option-(b)** (strip on the public-writer copy, keep the SAFE internal
  record). **D-3 correction (RECORDED):** `format_structural`'s fit-identity contribution was
  reassigned from **"item-3 (advisory)"** (folding it into the reconcile preimage's advisory
  constraint-values component) to a **distinct 5th OMIT-WHEN-FLOOR `structural` preimage component**
  (C8) — so a floor-`{}` venue churns no fit-digest and a HARD structural class is never conflated with
  advisory norms.
- **Still-deferred DR-4-adjacent items (REGISTERED, not built):**
  - **nested-in-prose slots** — v1 is WHOLE-SECTION conformance (the contract is pinned to the outline
    section skeleton); typed slots nested inside prose (a table with specified columns mid-section, an
    inline figure slot) are deferred.
  - **whole-part sub-output conformance** — the `format.parts` packaging surface is untouched by DR-4;
    a conformance contract over multi-part / folio sub-outputs is deferred.
  - **content-KIND validators** — the section `type` carrier names STRUCTURAL kinds only; validators
    that check a figure/table section's CONTENT shape (columns present, a caption exists) are deferred.
- **NEW DR-4 build carry-forwards — BUILT (both closed after the 11-commit build, maintainer-approved):**
  - **R1 — hoist `reconstruct_rule`** from `pipeline/compose.py` to `pipeline/sections.py` (the shared
    C2-vocabulary home) so `reconcile.py` stops transitively importing the compose subsystem (and, via
    it, the §21.7 taxonomy module `pipeline.api.results`). **DONE `35b4238`** — behavior-neutral
    relocation; a fresh `import pipeline.reconcile` now reaches neither `compose` nor `api.results`; the
    `reconcile.py` purity comment is restored to accurate.
  - **Render-site version threading** — the SD-5 `section_attr_transform_version` is now threaded into
    the serialize preimage at both remaining sites. **DONE `aaa4d44`**: `pipeline/mvpdemo.py` threads
    `dout.section_attr_transformed` (dispatch-first); `pipeline/api/render.py` `serialize_preimage`
    (two-phase) computes the flag the SAME way dispatch does — `strip_section_attrs` on the fitted AST
    gated by `should_strip` — so a TYPED standalone-API render mints an id matching its bytes.
    Behavior-neutral (non-typed corpus byte-identical). The RT double pandoc-reader read is now
    **ELIMINATED**: `DefaultRenderEngine` memoizes `serialize_fitted` by fitted-id (a frozen-dataclass
    `field(init=False, compare=False)` cache), so the two-phase seam shells the reader once, not twice.
- **Gate:** final `uv run pytest -q` = **2380 passed** (post R1+RT+AST-cache); `ruff check .` clean;
  `scripts/check-no-content.sh` OK. Coder/reviewer reports under `ops-handoff/dr4-build/`.

### DR-5 — Compose-vs-render placement of style; per-output style variation from one IR (reopens DR-2) — design problem
- **Status:** Deferred (not in v1) — **open design problem; reopens part of the reconciled DR-2 design.**
- **The gap:** the reconciled DR-2 design homes house-mechanical style (Oxford comma, spelling variant,
  number/date style, and style-guide-adjacent rules like footnote format) in the **`lexicons/`** registry
  applied at **compose** — i.e. **baked into the IR**, one choice per artifact. But some style must
  **vary per output from a single shared IR**: the same paper → different journals differing in footnote
  format, Oxford comma, etc. The pipeline varies things per-output only at **render** (Presentations);
  compose-baked style is **frozen** across every output of one IR.
- **The principle discovered (the line):** per-venue variation at **render** works when the style's input
  is **structured** in the IR — citations → **CSL** → per-journal footnote/citation format; fonts/colors
  → **Presentation** variables. It **fails** when the style is baked as **inline prose** — the Oxford
  comma is literally `a, b, and c` vs `a, b and c` in the text, with no render-time knob short of
  re-composing per venue or adding a text-style-transform capability the pipeline does not have.
- **Where the journal example lands today:** font/color (design) → **Presentations, render-time, varies
  per journal — works**; footnote/citation format (style) → **should be render-time via CSL** (structured
  citations + per-venue style) — natural home, **not yet designed**; Oxford comma (inline style) →
  **lexicon `mechanical`, compose-time, cannot vary per journal** — the genuine gap.
- **Design questions for the architect:** (a) classify each style rule by its home on the
  **compose→render** axis. (b) design the **render-time footnote/citation path** (CSL / structured
  citations + per-venue style) so it varies per journal from one IR — likely in/near Presentations.
  (c) decide the **inline-prose case** (Oxford comma): accept compose-baked (per-venue ⇒ re-compose), OR
  add a **render-time text-style-transform**, OR compose style-neutral + apply at render (hard for inline
  text). (d) does the **lexicon split** into compose-applied vs render-applied rules? (e) reconcile with
  the reduced style-guide model (footnotes are traditionally style-guide territory). (f) enumerate the
  **full set of per-venue-variable style/design** and place each.
- **Relationship:** reopens DR-2 (the lexicon's compose-only placement); linked to DR-4 (templates) and
  the Presentations axis; shares the academic-paper driving example. DR-2 build is paused pending this.
  (→ discharged 2026-07-21 — DR-2 is BUILT compose-only; see the DR-2 entry above.)
- **Source:** maintainer requirement, 2026-07-16 — the three-journals-one-paper case: same IR, different
  output per journal; fonts = design, footnotes/Oxford comma = style; the reduced style guide
  (lexicon-at-compose) cannot produce per-venue style.
- **Design status (2026-07-17) — RATIFIED (design; build paused):** same architect pass as DR-4. Look →
  **Presentation @ serialize** (kept, no work). Citations = a Pandoc-native **`references` (CSL-JSON)
  block + `[@key]` in the IR** (compose; real machinery — extends the closed IR envelope, threads into
  AST-`meta`, adds a §16 fidelity obligation) + **content-driven citeproc enablement** (fixes the broken
  default `plain` render) + a per-venue **`csl` Presentation lever** (style only). Inline mechanics →
  **compose-baked lexicon, labeled compose-only** (confirmed: no deterministic render path exists;
  per-venue ⇒ re-compose). The overridable style-file reference (`css`/`reference_doc`/`template`)
  **already exists** on Presentation — not reinvented. Output-type↔style **compatibility check** moves to
  the **dispatch layer** with a sound skin-lever signal → **WARN + fall-to-writer-default** (maintainer
  chose warn over error, 2026-07-17). ZERO new identity component. **The citation *grounding* concern is
  NOT citation-specific — generalized to DR-6**; only the citation *formatting* per venue is DR-5 (the
  `csl` / Presentation path above).
- **Build status (2026-07-20) — DR-5 BUILT (per-output citation style from one IR; three-journals
  driving example; gate green).** The ratified DR-5 shipped as **11 gated commits (C1–C8, C10–C12)**,
  each coder → reviewer → (where needed) fix-coder → re-review to CLEAN, under the standing commit
  approval. **C9 is intentionally skipped** (SF-6, DEFERRED — below). **C0** is the gate — a
  citeproc round-trip parity proof at the pinned pandoc 3.10 (`ops-handoff/dr5-build/C0-parity-finding.md`),
  verified before any code. **D1 = (b)-PROJECTED** (the citation is a projection of the grounding
  ledger, honoring NO-GO **#5** — the writer emits `[@key]` markers ONLY, never a free bibliography —
  and NO-GO **#8** — a CSL-JSON-shaped descriptor). Commits:
  - `0f9be37` **C1** `pipeline/ir.py` — the top-level `references` CSL-JSON block on the IR envelope
    (additive-optional via `keys ⊆ TOP_LEVEL_KEYS`, OMIT-WHEN-ABSENT, body-blind / recorded OUTSIDE
    `binding.preimage` → identity-neutral, no `ir_version` bump; a NEW top-level key so it gets its
    own §3.3 recursive no-secrets scan).
  - `1bbf4c1` **C2** `pipeline/compose.py` — `project_references(ledger)`: `references` is
    MACHINERY-projected from the grounding ledger's DISTINCT pool sources — one CSL-JSON item per
    `source_instance_id` under a deterministic `s0`/`s1`… key (single-sourced, `_source_citation_keys`),
    gated on a body that actually cites (`_body_has_citation`) — so a citation is grounded by
    construction, closing the §6.5 fabrication leak.
  - `fdc0817` **C3** `pipeline/compose.py` + `pipeline/prompts/writer.md` — the writer emits `[@key]`
    markers ONLY and is FORBIDDEN to self-author a `references`/bibliography (#5); it cites solely the
    projected `available_citations` keys handed to it (single-sourced with C2's `s{n}` derivation).
  - `15b6a44` **C4** `pipeline/compose.py` + `pipeline/api/results.py` — the HARD
    `[@key]`→projected-`references` resolution at the COMPOSE locus (ratified D-cite-locus = COMPOSE):
    a citing body is parsed through the SINGLE pinned pandoc reader and every `Cite` id checked ⊆ the
    projected set (robust across multi-key / locator / prefix / suppressed-author, NO regex); an
    unresolved key or invalid bare/braced form re-asks, then blocks as the never-persisted new code
    `citation-unresolved` (`ALL_CODES` +1). A non-citing body is never parsed → non-citing corpus
    byte-identical.
  - `61fb1de` **C5** `pipeline/serialize.py` — thread `references` into the AST `meta` as canonical
    YAML frontmatter (D2 = frontmatter), so the same single pinned parse lands it at
    `ast["meta"]["references"]`; RI7 stays `--citeproc`-free (citeproc runs at the writer, C6). Scoped
    to the FLAT single-document render (the N3 gap, registered below).
  - `a2fdbc5` **C6** `pipeline/dispatch.py` + `pipeline/filters/citeproc_enablement.py` (+ discovery /
    render / driver / serialize / mvpdemo) — CONTENT-driven citeproc enablement: `--citeproc` fires
    whenever the AST carries a `Cite` node (the SD-5 identity twin), keyed off neither the writer nor
    any `csl` lever, fixing the broken default `plain` render; the OMIT-WHEN-ABSENT
    `CITEPROC_ENABLEMENT_VERSION` joins the serialize preimage ONLY when citeproc fired.
  - `3c0776e` **C7** `presentations/_schema.yaml` + `pipeline/presentation.py` + `pipeline/dispatch.py`
    — the `csl` Presentation lever (the α seam: a LABELED `RenderInputs.csl` field, NOT an unlabeled
    asset; dispatch content-gates `--csl` WITH `--citeproc`, never a standalone toggle; the csl content
    hash enters the serialize preimage only when `citeproc_enabled` — the S3×S4 identity gate).
  - `467e5d9` **C8** `pipeline/reconcile.py` + `pipeline/prompts/reconciler.md` — the preserve-inline-
    `[@key]` obligation on the bounded fidelity re-ask (D7 = SUBSET-only, S5): a citation DROP is
    permitted, a MINT/MANGLE blocks as `citation-not-preserved` (the citation analog of C7's
    `structure-not-preserved`); the anti-fabrication resolution stays C4's compose-locus check.
  - **C9 — DEFERRED** (the SF-6 output-type↔style compatibility WARN; the maintainer chose to defer it
    as separable pre-existing work — see the deferral register below). The C9 plan-number is
    intentionally skipped.
  - `915ec07` **C10** `pipeline/payload.py` — the RI14 external payload carries, for a CITING AST only,
    a `citeproc` REQUIREMENT block (`enabled` + per-venue `csl` + pinned `pandoc_version`) the external
    actor honors; OMIT-WHEN-ABSENT (non-citing / citation-less csl-set → byte-identical to pre-C10).
  - `73155bf` **C11** `presentations/journal-{strict,structured,concise}-look.md` + 3 `.csl` assets
    (`presentations/assets/csl/{numeric,author-date,note}.csl`) + the e2e — three journals that differ
    ONLY in citation style (numeric / author-date / footnote) from ONE IR; proven via an INJECTED asset
    loader (production path-resolution is the deferred §17/step-29 loader).
  - **C12** (this) — docs + SSOT sync (design.md §5.3/§6.5/§15/§16/§17/§19/§27.4; this entry; state.md)
    + the MN-2 strip-invariant docstring in `pipeline/filters/provenance_strip.py`. No production logic
    change; no `schema_version`/`ir_version` bump.
- **Identity discipline (DR-5):** `references` is body-blind (out of `binding.preimage`); the
  `csl` asset-hash and the `citeproc_enablement_version` are BOTH omit-when-absent (present only when
  citeproc actually ran / fired); **ZERO new `artifact-id` preimage component**; **no `schema_version`
  bump, no `ir_version` bump**. A non-citing render — even under a csl-set look — is byte-identical to
  pre-DR-5 (== `plain`), so the golden compose / fit / render-digest corpora are unperturbed; only a
  CITING render adds the components and re-mints its deliverable loudly (§17 FR7.3).
- **DR-5 tracked follow-ups / deferrals (REGISTERED — each with its status + why; NOT blanket-resolved):**
  - **C9 / SF-6 output-type↔style compatibility WARN — DEFERRED as separable** (maintainer decision,
    2026-07-17): a css-only brand → docx should WARN + fall-to-writer-default, with `csl` EXCLUDED from
    the skin set (S2). Independent of the citation work; pick up as its own item.
  - **The lone-bare-`@key` escape (C4) — ACCEPTED for v1.** A lone bare `@key` (no bracketed `[@`)
    escapes the marker-gated resolution — an output BLEMISH, not a fabrication (only a writer.md-non-
    compliant writer emits it; the braced/bare INVALID forms inside a `[@` body ARE caught). Closing it
    would force a pandoc parse across the whole non-citing corpus; revisit if/when the `[@` marker gate
    is widened.
  - **The `json`-passthrough `citeproc_enabled=True` note (C6) — semantically loose, tighten later.**
    The raw-AST passthrough writer reports `citeproc_enabled=True` for a citing AST even though citeproc
    never touches the passthrough bytes; ZERO identity impact. Cosmetic; tighten later.
  - **GAP-1 citeproc determinism gate (C10, §4.2) — REGISTERED.** Internal (pinned pandoc) vs external
    (actor toolchain) citation rendering may differ, OUTSIDE the pin boundary. The RI14 payload carries
    the pandoc version + csl as pins the actor MUST honor; the payload STATES the requirement, it cannot
    enforce the actor's toolchain.
  - **Production Presentation asset loader — DEFERRED to §17/step-29 (C11).** The journal looks now
    DECLARE a `csl` asset, so `driver._deferred_asset_loader` AND `render._deferred_asset_loader` (both
    still raise) are reachable for a citing journal deliverable on the production path; production
    asset-lowering (css / reference_doc / csl — one filesystem path-resolution) is §17/step-29. The e2e
    is proven via an INJECTED loader.
  - **The non-`.md` asset provenance convention (C11) — RECORDED.** A `provenance: framework` line
    inside a `.csl` XML comment satisfies the content guard's per-file default-deny for a non-Markdown
    framework asset; record the convention.
  - **`pin_bundle` does not surface `csl` (C7) — record-only.** The RI13 pin-bundle MANIFEST projects
    `assets`/`variables`/`engine`/`reference_doc` but has no dedicated `csl` key; identity /
    reproducibility is complete via the serialize preimage (which carries the csl hash when citeproc
    ran). Optional to surface later.
  - **#5a — the three-context bare-`[@key]` classifier → DR-6 migration (N1). REGISTERED.** The full
    grounding-span → grounding-cite / `.framing`-span → bibliographic / bare → forbidden classifier is
    a DR-6 concern (it depends on the `.framing` construct DR-6 did not build); DR-5 ships the HARD
    in-`[@` invalid-form catch only.
  - **#6 — grounding at TWO loci over one ledger. REGISTERED.** The DR-5 citation-resolution check (C4,
    compose-locus) is DR-5-owned; it plus the DR-6 advisory Review-1 audit are two loci over one ledger,
    not "one chokepoint."
  - **#7 — the external CSL boundary → scenario-2 for `side: internal` only (N2). REGISTERED for DR-6.**
    External-side (`side: external`) scenario-2 attribution is compose-fixed literal prose; the DR-5
    CSL indirect-citation surface extends it only for `side: internal`.
  - **The multi-document frontmatter gap (N3) — REGISTERED, not built.** C5 scoped the
    `references`→meta threading to the FLAT / single-document render; per-document meta partitioning for
    a multi-document deliverable is registered, not built.
  - **The out-of-pool external-literature citation → DR-6 scenario-2 — DEFERRED.** DR-5 cites IN-POOL
    works only (the (b)-projected coupling); citing the broader literature via a pool source's secondary
    attestation is the ratified home of the named scope-limit — DR-6 scenario-2 (the §15 `attestation`
    carrier is the foundation, its detection/production deferred).
- **Gate:** final `uv run pytest -q` = **2497 passed**; `ruff check .` clean;
  `scripts/check-no-content.sh` OK. Coder/reviewer reports under `ops-handoff/dr5-build/`.

### DR-6 — General grounding enforcement: all published content grounded in source (not just citations) — design problem
- **Status:** Deferred (not in v1) — **open design problem; generalizes and ABSORBS three per-feature
  grounding flags** each deferred separately: the DR-2 reconciliation's "no compose-time hard gate that
  every fact-claim cites an EXTRACTED source," the DR-3 outline reconciliation's B1 (same, for
  outline-demanded claims), and the DR-4/DR-5 SF-3 (same, for the `references` / citation channel).
- **The invariant (already stated in §6.5, to be enforced GENERALLY):** **ALL published content must be
  grounded in the source material — not just citations.** The per-feature framings (especially "couple
  *citations* to the ledger") were **over-specific**; grounding is one general rule and every published
  channel (prose claims, outline-demanded points, the `references` block) is subject to it identically.
- **Acceptable grounding — TWO scenarios (maintainer, 2026-07-17), neither a hallucination:**
  1. **Direct / primary** — the claim's **primary source is IN the scanned source material** (the pool).
  2. **Secondary attestation** — the primary source is **NOT in the pool, but is referenced or quoted by
     a pool source**, which makes that pool source a **secondary source** for the claim.
  Either is acceptable **as long as it works within the constraints of the output artifact.** A claim
  that is neither (primary absent AND no pool source attests to it) is a **hallucination — rejected.**
  (This resolves the DR-4/DR-5 SF-3 pool-membership tension: an academic paper MAY cite the broader
  literature — but only via a pool source's secondary attestation; anything beyond that is hallucination.)
- **The open design question:** should compose **HARD-gate** this at compose time (every published-as-fact
  claim must trace to scenario 1 or 2), or keep the current **advisory §19-review** posture? And how does
  the primary/secondary distinction map onto the existing grounding ledger + EXTRACTED / INFERRED /
  AMBIGUOUS tiers?
- **Relationship:** a general invariant beneath DR-2 / DR-3 / DR-4 / DR-5 and all compose; the citation
  *formatting* per venue stays in DR-5 (`csl` / Presentation) — DR-6 owns only *correctness / grounding*.
- **Source:** maintainer, 2026-07-17 — grounding is general, not citation-specific ("over-specific and
  must be generalized"), with the two-scenario acceptance model above.
- **Design status (2026-07-17) — RATIFIED (design; build paused):** designed via research → architect
  initial → **whole-picture adversarial** → reconciliation. **Enforcement posture (maintainer chose the
  Combination):** writer **self-demarcation** = a HARD, deterministic **structural coverage gate** at
  compose (the writer marks every prose unit as a grounding span or an explicit `.framing` span;
  compose rejects bare unmarked declarative prose into the existing bounded re-ask) **+** a semantic
  **framing-honesty + faithfulness audit at Review-1** (advisory, free — Review 1 is already an LLM
  call; the NLI reliability numbers do NOT transfer to a `claude -p` self-check, so it cannot be a hard
  per-claim reject) **+** an opt-in **item-level abstain**, framework default **warn-and-ship** (an
  instance may override to `block` via a recipe/workspace `grounding_posture` policy on the M3 cascade).
  **Honest ceiling:** self-demarcation gates *form, not grounding-honesty* — a gaming writer could dress
  a hallucination as `.framing`; the semantic half stays noisy. **Cost:** a `writer.md` contract change
  (+ an exemption tail for headings/lists/code/tables/math), a new block-level parse at compose, and a
  §17 `.framing` strip decision. **Scenario 2:** ONE optional PROV-O `attestation? {primary, anchor,
  relation}` ledger field — a third **pool-relation** axis (distinct from the tier / `traceability` /
  the `primariness` score), modeled `LEDGER_REQUIRED` + `LEDGER_OPTIONAL` (scenario-1 byte-unchanged),
  per-(fact, instance); it publishes as **attributability + survivability** (an attribution to pool
  source S must exist and survive the §17 external strip; the *surface form* is DR-5's — in v1 = prose
  by necessity); an in-pool primary wins for publish-as-fact. **Absorbs** the DR-2/DR-3/DR-4-5 grounding
  flags (grounding = one channel-agnostic property of every compose leaf, one chokepoint); the DR-5
  `[@key]` binding is **deferred to DR-5's resumption** with a named constraint. The DR-4×DR-6
  "deadlock" is false (both → block-and-report; the §6.5 framework floor outranks a venue's
  grounded-content demand). **`ir_version` evolves** by bump + generation-tolerant validation
  (additive-optional) so old IRs still re-reconcile. Utilization floor dropped. **ZERO new identity
  surface.** Full design pass: `ops-handoff/dr6-grounding/` (archived at `docs/archive/design-record/dr-design-passes/dr6-grounding/`).
- **Build status (2026-07-18) — increment 1 builds OPTION A (advisory), NOT the Option-C hard gate.** At
  the plan-review gate, once Option C's true cost was concrete (a per-sentence writer self-demarcation
  discipline + a whole-test-corpus migration), the maintainer chose to build the **advisory subset
  (Option A)** for v1: **F-a** (`ir_version` foundation) + the **`attestation` ledger carrier** + the
  **advisory Review-1 framing-honesty/faithfulness audit** + the **`grounding_posture` opt-in item-level
  abstain** (fail-open on a missing review record). **NOT built:** the hard self-demarcation coverage
  gate, the `writer.md` all-prose contract, the `.framing` construct + §17 strip, the corpus migration,
  the reconcile coverage re-check. The hard-enforcement question (Option C) is **reconsiderable later**,
  or could be delivered differently via a **fact-checking docs-researcher agent that verifies the
  composed IR against the input source contents** — recorded as a future option, **NOT to be designed or
  built now.**
- **Increment 1 BUILT (2026-07-18) — Option A landed; all four commits reviewed CLEAN, gate green.** The
  advisory subset shipped as four gated commits (each: coder → reviewer →, where needed, fix-coder →
  re-review to CLEAN; the commit-4 reviewer's 3 should-fix + 2 nits were all fixed and re-reviewed CLEAN
  in pass 2):
  - `0f6d401` **F-a** — `ir_version`→2 + generation-tolerant validation (the single re-validation pin
    relaxed from exact-equality to `∈ KNOWN_IR_VERSIONS`; ledger split into `LEDGER_REQUIRED` +
    `LEDGER_OPTIONAL`) so a v1-stamped canonical IR still re-reconciles. The coverage gate is NOWHERE in
    `validate_ir` (the #1 correctness thesis).
  - `aeed34d` **attestation carrier** — optional `attestation {primary (structured CSL-JSON), anchor,
    relation ∈ {wasQuotedFrom}}` on the ledger; validated only when present; scenario-1 ledgers stay
    byte-identical → artifact-id unchanged. Carrier + pass-through ONLY (no scenario-2 detection/
    production, no attributability/survivability enforcement).
  - `b92b443` **Review-1 advisory audit** — prompt-only refinement of the existing `grounding` check into
    explicit **coverage** + **faithfulness** sub-dimensions, `concern`-level / never-block;
    `ARTIFACT_CHECKS` (closed 5-key set) and `REVIEW_VERSION` unchanged; no `.framing` / hard gate.
  - `7e935a1` **`grounding_posture` policy + opt-in item-level abstain** — cascading M3 policy
    (`warn`|`block`, default `warn`, most-local-wins like `on_conflict`); under `block` ONLY the driver
    abstains an item whose **PERSISTED** Review-1 record shows a `grounding` concern (code
    `grounding-uncovered`, GENERATION block), **fail-OPEN** on record absent/corrupt/partial and
    re-drive-stable. Policy rides `plan_hash` (via `selection_payload`, like `on_conflict`) but NEVER the
    artifact-id preimage; `review.py` unchanged (the audit stays advisory).
  - Verification at every commit: final gate `2014 passed, 6 deselected`, ruff clean, content-guard OK.
    Full coder/reviewer reports under `ops-handoff/dr6-build/{coder,reviewer}-0{1..4}*`.
  - **PENDING maintainer go-ahead:** the design-authority doc-sync (`docs/design.md` §15 attestation +
    `ir_version`, §6.3/§12.1 `grounding_posture` cascade, §6.5/§19/§21.7 the advisory audit + abstain) and
    a small `ir.py` module-docstring note — proposed, not yet landed (edits the ratified design SSOT).

### DR-7 — Mixed-media documents: existing images + captions AND generated diagrams in one document — design ratified; increments A+B+C BUILT (asset foundation + binary-target image embedding + flat honest generated diagrams), D not built
- **Status:** Partially built — **design RATIFIED across ~15 architect passes (base → amendment →
  grouping → box initial/adversarial); increments A (the asset foundation), B (binary-target image
  embedding), AND C (flat honest generated diagrams) are now BUILT; D remains designed-not-built.**
  Build scope **A→D** is plannable (D, honest badge grouping, is the last flat-model increment); the
  enclosing-subsystem box (E) is **DEFERRED** behind a grounding-layer rebuild.
- **The capability (plain English):** put an **existing picture** (a client image asset + its caption)
  AND a **pipeline-generated diagram** side by side inside **one** document, each declared with a single
  `{type=…}` section marker (`type=figure` = a brought image; `type=diagram` = a generated one) in the
  **same outline** the author already writes prose in. One template, one marker vocabulary — no second
  "diagram file," no "which do I use?" fork.
- **The honest promise (the whole point): a diagram cannot lie by ADDING, HIDING, or GROUPING.** A
  generated diagram is not a picture an AI draws freehand — it is a grounded **node/edge list**, and it
  passes a **HARD, blocking fact-check gate BEFORE any picture is drawn**: every edge must cite a checked
  source at an honest tier or the document is refused (not warned). It cannot lie by **adding** (no arrow
  exists that wasn't checked), by **hiding** (the whole checked list is drawn 1:1 — there is no "tidy it
  up" knob that drops boxes), or by **grouping** (no label or box asserts a membership/name a source fact
  didn't ground). After the gate passes, deterministic code compiles the list to a **stored SVG asset**
  at compose-time (content-addressed, so "same input → same bytes" holds; render is pure embedding). A
  genuinely non-source-claiming sketch is allowed only if it renders with a visible, non-optional
  "illustrative — not source-checked" stamp.
- **Build scope A→D (paid once for the capability; adding a value stays one file after):**
  - **A — Content-asset foundation (MVP; needed by BOTH brought figures and generated diagrams) — BUILT:**
    (commits `c5f8918` A1 homes + framework-assets guard, `d836b41` A2 content-addressed store,
    `7b5b338` A3 containment-guard library, `86bf4e8` A4 wired blocking gate + raw-markup ban) a
    compose-time content-asset store; an **intra-body path containment guard** (a `![alt](path)` cannot
    reach across into another client's files — blocking at compose, closes a live cross-client read;
    reuses GAP-9's resolve-and-contain *shape* at path granularity, but is a NEW check); and the two
    **framework/instance provenance homes** (framework example assets in a public `assets/…`; client
    assets in `users/<user>/workspaces/<workspace>/assets/…`, gitignored + isolated) + a shipped
    `templates/workspace/assets/.gitkeep`. **Delivered:** the two asset homes + the
    content-addressed store + the compose-time client-isolation containment guard (refuses any body image
    reference escaping the client's own `assets/`, incl. `..`/absolute/`%2e%2e`/backslash/NUL/raw-`<img>`/symlink)
    + the raw-markup ban; suite 3001→3055; adversarially reviewed. **B is now BUILT (below); C/D remain designed-not-built.**
  - **B — Binary-target image embedding (MVP) — BUILT:** (commits `17a8e8e` C1 real filesystem asset
    loader fenced to `presentations/` + `--resource-path` plumbing (replaces both deferred RAISEs),
    `6db2ec1` C2 figure embedding + render-time isolation re-gate + embed-gated content-hash identity
    fold + discovery carry-forward, `8469980` C3 the A↔B base-equality contract drift-catcher, + this C4
    docs/SSOT sync) the once-deferred filesystem asset loader is now real (was a loud RAISE, deferred to
    §17/step-29) and **fenced to `presentations/`** (rule-2 client isolation — a styling file can never
    reach into another client's `users/…/workspaces/…`); the Presentation lowering emits `--embed-resources
    --standalone` for html5 and native `--resource-path` embedding for docx, so a client figure now
    **embeds in HTML/docx** (a `data:` image in a self-contained HTML document, a real `word/media/` part
    in the .docx) rather than surviving only as a path — Markdown keeps referencing by path (all it
    needs), plain text keeps showing the caption only. **Delivered:** the two deferred asset loaders
    replaced by one `presentations/`-fenced filesystem loader; the `--resource-path`/`--embed-resources
    --standalone` (html5) + native-embed (docx) lowering so images embed in html/docx; a **render-time
    FULL A-gate re-check** on the persisted AST before any embed flag is emitted (every image target +
    the raw-markup refusal — a tampered `../other-client` document fails loudly at render and its bytes
    are never copied); and an **embed-gated content-hash identity fold** (`asset_embed_version`
    OMIT-WHEN-ABSENT, mirroring the C7 `csl` pattern exactly) so an edited figure re-mints the html/docx
    deliverable while the by-path Markdown id is byte-identical (image-less and md renders unperturbed —
    zero churn). Suite 3055→3102; adversarially reviewed (F1–F7 + FWD reconciled).
    **Carry-forward to C (F4/FWD) — RESOLVED in C:** SVG-in-docx embedding (UNVERIFIED by B, PNG proven
    only) is now handled by C0's LOUD `rsvg-convert` capability gate — a docx that embeds an SVG diagram
    requires `rsvg-convert` on the render host; absent it the render REFUSES loudly (never silently ships a
    blank/broken docx). The EXTERNAL hand-off still does not fold body-figure content (`assets_embedded` is
    internal html5/docx only) — extend the fold when external rendering lands. **D remains
    designed-not-built; E deferred.**
  - **C — Flat honest generated diagrams — BUILT:** (commits `3f0b369` C0 the LOUD `rsvg-convert`
    docx-SVG capability gate, `96710bc` C1 the node/edge writer grammar + parser, `a1d2edf` C2 the HARD
    grounding gate [reviewed CLEAN], `2ed5b33` C3 the multi-tool compiler → content-addressed stored SVG +
    label escaping, `b79d7da` C4 the atomic `{type=diagram}` flip [parse → gate → compile → embed],
    `93eb4a9` C5 the `diagram-styles/` referenced registry + the selectable `tool` knob) a structured
    node/edge writer grammar (extends the compose envelope) + the **HARD grounding gate** (every edge must
    resolve to ≥1 real honest-tier source fact BEFORE any SVG byte is drawn, or the whole document is
    REFUSED — coverage is by fact-COUNT, not merely a green-looking tag) + a multi-tool auto-render —
    **Graphviz `dot` (pinned default) / `d2` (selectable) / `auto` (opt-in ONLY, for locked
    environments)** — compiled to a **content-addressed stored SVG** (reuses A/B's asset machinery) + the
    `diagram-styles/` **referenced registry** + exactly **one** honesty-safe knob, `tool` (it changes only
    HOW the same checked boxes/arrows are drawn, never WHICH exist; a dangling `diagram_style` ref or a
    chosen-but-missing tool REFUSES loudly, never a silent fallback). The masking knobs `detail` /
    `altitude` / `connectivity` were **CUT** — each could make a diagram quietly lie past an edge-only gate;
    over-granularity is fixed honestly at authoring (write at a citable altitude), not by a hiding dial.
    Mermaid is dropped (renders as raw code in 3 of 4 outputs; not groundable; non-deterministic).
    **Delivered:** the `{type=diagram}` section grammar + the HARD compose-time fact-check gate (fail-closed;
    only a literal `illustrative` posture opts out, and only behind a visible "illustrative — not
    source-checked" stamp) + label escaping (a box label can no longer inject an unchecked arrow) + the
    `dot`/`d2`/`auto` compiler to a stored SVG + the `diagram-styles/` registry (a one-file-add style entry,
    whitelisted in the content guard the same commit) + C0's loud rsvg-convert docx gate. Suite 3102→3310;
    each commit coder → reviewer → (fix) → CLEAN. **`rsvg-convert` is a docx-SVG render prerequisite**
    (loudly enforced). **D remains designed-not-built; E deferred.**
  - **D — Honest BADGE grouping (fast-follow, behind its own small spike):** each node carries a small
    **badge** naming its cited subsystem — a **grounded group name + grounded membership**, both run
    through the existing existence+tier gate — plus a **mandatory plain-text legend** ("a badge marks a
    cited group; it is not a claim that badged nodes interact; an un-badged node's group is simply not
    shown"). **No enclosing box.** Strictly additive: an ungrouped diagram is byte-identical to a flat
    one, so sequencing D after C costs zero rework.
- **DEFERRED — E (the enclosing subsystem box):** the one thing a badge cannot do — a **closed "these are
  ALL and ONLY the members" boundary claim.** DEFERRED (plain reason): **today's grounding layer cannot
  produce complete, EXTRACTED-tier membership to back a box, so enforcing one would fake "all members."**
  Verified: source queries are **budget-truncated and ranked** (`graphify.py:156`, default budget 2000 +
  a `truncated` marker), so an "enumerate all members" answer is really a bounded query window, not "all
  the source knows"; the honesty ledger records only **that** a fact exists (not what it says) and facts
  are **edges, not node-memberships** (`graphify.py:50-54`); and the only grouping datum, `community=`,
  is an **algorithmic inference below the EXTRACTED publish floor** (`grounding.py:387`). An enforced box
  on this substrate certifies a completeness nobody checked — the exact masking the maintainer distrusts,
  and the adversarial pass's verdict was **stop at badges (D).** E needs a **grounding-layer rebuild**
  (structured enumerable membership across every adapter + a set-equality gate + a cluster-determinism
  spike) AND a real, named closed-world need; build it THEN, re-derived from scratch. The badge (D) is
  the honest place to stop.
- **Identity / boundary posture (design-level, for the future build):** a generated SVG is a
  **content-addressed stored asset** folded into render identity by content hash (the existing asset
  mechanism); the `(tool, version)` pin rides the author-time compile provenance (an env change re-mints
  on the next re-compose, like the existing asset-version posture), NOT the serialize preimage — so no
  new `artifact-id` component is introduced by the design. `auto` is opt-in precisely because keying SVG
  bytes on the ambient install-set would make identity machine-dependent.
- **Design status (2026-07-24 → 07-27) — RATIFIED; increments A+B+C BUILT (C landed 2026-07-28/29):**
  designed via a base architect pass (initial → adversarial → reconciliation), an amendment pass
  (multi-tool + diagram knobs), a grouping pass (box vs badge), and a box pass (initial → adversarial),
  all read-only against `main @ cc42c54`. The load-bearing records (3 reconciliations + the 2 box records)
  are archived at `docs/archive/design-record/mixed-media/` with a `README.md` index naming each record's
  role and the final decision; the code citations resolve there. **Full build order:** `A → B → C → D`,
  **E deferred** — A, B, and C are BUILT; **D (honest badge grouping) is next if the maintainer proceeds.**
- **Not built:** D and E — a recorded design decision, not code (increments A+B+C are now BUILT, above).
  Both the figure/image half (A+B) and the generated-diagram half (C) are now COMPLETE — brought figures
  embed in html/docx, and generated diagrams are fact-check-gated then compiled to stored SVGs through the
  same asset machinery. D (honest badge grouping) carries its own small required determinism/citation spike
  and is strictly additive (an ungrouped diagram is byte-identical to a flat one, so D costs zero rework).
- **Docs status (increment-C closeout, 2026-07-29):** this tracker (DR-7) is current. The comprehensive
  `docs/design.md` design-authority integration for the whole mixed-media feature (A+B+C) and the
  user-facing `docs/guide/*` walkthrough are DEFERRED to the end-of-arc documentation sync — per the
  maintainer's instruction to update the guide "only when it is done and tested and works correctly" (i.e.
  after increment D is decided and runnable end-to-end examples verify the feature). The load-bearing
  design records remain archived under `docs/archive/design-record/mixed-media/`.
- **Source:** maintainer requirement — mixed-media documents (existing images + captions plus generated
  diagrams in one document), with the explicit north star that a generated diagram must never be able to
  lie (no invented arrow may ship dressed as a checked fact).

### DR-8 — General multi-language API client (CLI + library + language-neutral contract + C++ POC) — BUILT
- **Status:** BUILT (2026-07-28) — **shipped as a language-neutral canonical-surface + wire contract
  (`docs/guide/clients.md`) that every wrapper implements identically, a stdlib-only Python library +
  CLI, and a C++ proof-of-concept: 4 gated commits, zero new dependency, suite 3001→3158. The one
  deferral (a formal OpenAPI spec) is registered below.**
- **The capability (plain English):** a friendly, consistent way to call the pipeline's HTTP shim
  (the DR-1 door) from **any** language. `docs/guide/clients.md` is the **single neutral source** — a
  canonical client-surface spec **plus** the wire contract — that every wrapper reads and implements
  identically. Shipped wrappers: a stdlib-only **Python library** (`from pipeline.client import
  Client`) + **CLI** (`python -m pipeline.client`), and a **C++ proof-of-concept** (`examples/cpp/`,
  libcurl + nlohmann/json). **No language is privileged:** the method set, the outcome semantics, the
  poll state machine, and the error taxonomy are **canonical** (identical everywhere); only the
  transport substrate and the error channel are per-language idiom — Python `raise`, C++ `throw`, and
  a return-based channel are all conformant.
- **The anti-drift guarantee:** `tests/test_clients_doc_contract.py` **imports the server's own
  constants**, so the documented wire-code set can never silently omit a code that a wrapper needs —
  the doc contract cannot fall behind the code.
- **Zero new dependency:** the Python library + CLI are **stdlib-only**, preserving the framework's
  no-new-dependency posture (the C++ POC's libcurl / nlohmann-json are example-only, never pipeline
  deps).
- **Commits:** `1b2d3bf` (the neutral contract + the import-derived anti-drift test) · `315267a` (the
  stdlib Python library) · `4e309b5` (the CLI + a raw-error-token fix) · `f05d2c7` (the C++ POC).
  Suite **3001→3158**.
- **Related:** the `examples/n8n/` workflows (poll + webhook) are a **third** worked shim-consumer,
  beside the Python and C++ wrappers.
- **Honest DEFERRAL (registered, not hidden) — a formal OpenAPI spec:** OpenAPI describes only the
  **wire**, not the **client-side surface** that makes the languages consistent (the method set /
  outcome semantics / poll state machine); it would have to be **hand-authored** (the response shapes
  are not reflectable from the code); and **no machine-codegen consumer exists yet**. Add it when one
  does — until then it is a second hand-maintained contract with nothing to generate.
- **Cross-ref:** `docs/guide/clients.md` (the single neutral client source — wire contract + canonical
  surface); the **DR-1** HTTP shim (the door these wrappers call) above.
- **Gate:** `uv run pytest -q` = **3158 passed** (docs-only entry — unchanged from the build);
  `uv run ruff check .` clean; `scripts/check-no-content.sh` OK. Client build reports under
  `ops-handoff/api-client/`.
- **Source:** maintainer requirement — a general, multi-language-friendly way to call the pipeline's
  HTTP API from any language, with one neutral contract every wrapper obeys.

### DR-9 — Friendly invocation surface + recipe/entry authoring + attribute documentation — CLI-UX increments 1–4 BUILT (increment 5 deferred); per-entry "skill" layer CONSIDERED and DECLINED; authoring tools + attribute reference QUEUED
- **Status:** Increments 1–4 BUILT. The **friendly invocation surface** (a CLI `generate`/`preview`/`outline`
  door, a door-class-aware request normalizer, a zero-spend dry-run, and the two-phase outline
  continuation-handle) is design-RATIFIED (architect initial→adversarial→reconciliation) and plan-SETTLED
  (planner initial→adversarial→reconciliation), and is BUILT as 7 gated commits C1–C7 (increments 1–4);
  increment 5 (HTTP + language-wrapper parity) is deferred to its own later pass. Records:
  `ops-handoff/cli-ux-design/` + `ops-handoff/cli-ux-plan/`.
- **The capability (plain English):** `pipeline generate --recipe … --topic … --set …` that reads like
  English, fills sensible defaults, shows the whole plan + the exact paid-piece count for FREE, and spends
  nothing until `--go`; a `preview` showing every resolved setting and WHICH cascade layer decided it; and
  a two-phase outline (draft → hand-edit → drive) that refuses BEFORE spend if the settings drift from the
  draft. One door-class-aware normalizer maps the same friendly surface to every door
  (CLI/library/HTTP/webhook/wrappers) so they cannot diverge.
- **Build status (2026-07-30) — increments 1–4 BUILT + pushed:** `e926c5c` C1 (explain/preview projection
  + spend-estimate) · `5846c82` C2 (door-class normalizer) · `87a3538` C3a (generate/preview subcommands,
  §21.9 wiring) · `fd40cb5` C3b (outline emit/drive) · `4139ddd` C3c (discovery types + `list`/`get` CLI
  door) · `3b1d4bf` C6 (the two outline-config codes) · `6f5927c` C7 (the outline drift guard). Each
  coder → reviewer → (fix) → CLEAN → committed under the standing cadence; suite 3320→3412; every commit
  money-safe (`invoke begin-session` → exit 3, live generation off the shared door), zero artifact-id/
  `plan_hash` churn. Ratified forks: preview is a flag not a verb; spend verbs require an explicit
  `--workspace`; `--set` infers scalar types; language wrappers deferred to increment 5. **Closeout done:**
  the two `outline-config-*` codes registered in `design.md` §21.7 + the enumeration docstrings reconciled.
  **Minor follow-up:** a `--from` passed with no driven outline is silently ignored (benign — nothing
  mis-spends; a lost "your `--from` is meaningless here" usage-warn nicety). **Deferred (increment 5):** the
  HTTP-shim server-side normalize + drift guard, the DR-8 language-wrapper friendly flags, and the
  cross-language conformance suite (`normalize_spec.json` is shipped as its seed).
- **Entry-semantics finding (2026-07-30) — the per-entry "SKILL" layer was CONSIDERED and DECLINED; a
  slider-legend ablation is QUEUED.** (`ops-handoff/entry-semantics/architect-initial.md`.)
  - **How an entry conveys meaning today:** the writer LLM receives the resolved attribute VALUES (mostly
    natural-language prose — persona role/knowledge/objections, voice narrator/guidelines, topic why)
    injected verbatim into the compose context, plus the static ~9KB `writer.md` behavioral contract + the
    lexicon apply-block + DR-4 section conformance. The schema `definition:` text and every entry BODY are
    maintainer/lint documentation ONLY — **never sent to the model** (`definition` appears zero times in
    `compose.py`/`driver.py`).
  - **Verdict — do NOT build a per-entry/attribute skill layer.** It would mostly duplicate the prose
    attributes + `writer.md` the model already sees; a pre-built skill makes adding a value a two-file
    change (breaks the §5.4 one-file rule) and drifts from the entry; a run-time LLM-built skill is
    non-deterministic and churns artifact identity (§7). Decisive on OVERRIDES: a plain `guidance`
    attribute cascades so overrides "just work"; a skill forces a SECOND override channel parallel to the
    cascade (hidden coupling) or a bake-in-then-rebuild churn. Token/time cost is inverted from the signal.
  - **The three genuine thin spots:** (1) voice sliders `formality/humor/warmth/energy` arrive as bare 1–5
    ints (the legend lives in the un-sent `definition:`) — the one clear gap; (2) format rhetorical
    structure (what belongs in each section) is body-only; (3) goal intent (`explain` vs `convince`) is
    body-only, inferred from the id-word.
  - **QUEUED — slider-legend ablation:** route the ALREADY-WRITTEN schema slider-legend text (e.g.
    `voices/_schema.yaml` "1 = casual … 5 = formal") into the prompt and MEASURE the quality delta before
    committing (the voice `guidelines` prose may already carry most of the character, so the realistic gain
    is "remove an ambiguity"). Highest quality-per-byte; reuses an existing asset. If a real gap remains, an
    OPTIONAL verbatim `guidance`/`intent` attribute (cascades + composes with overrides for free) — never a
    skill file, never a run-time constructor.
- **QUEUED — recipe + entry AUTHORING tools + attribute documentation (2026-07-30, maintainer ask; to be
  DESIGNED):** mechanisms/tools to (a) CREATE recipes — composing existing dimension entries into a named,
  saved recipe (building on the friendly by-name-axis surface above) — and (b) CREATE NEW entries from
  scratch (persona/voice/format/…) to be composed, conforming to each registry schema + the §5.4
  one-file-add rule + the three ratified authoring modes (fully-manual / interactive-assisted /
  researcher-assisted; see `state.md`). PLUS a comprehensive, user-facing **ATTRIBUTE REFERENCE**
  documenting what every attribute MEANS and DOES (surfacing the schema `definition:` text that today is
  maintainer-only) so a user knows exactly what to author and set. Ties directly to the entry-semantics
  finding (the meaning is written but not user-facing). PLUS (c) a **DIAGRAM-NUDGE** knob (maintainer ask
  2026-07-30): a way to DETERMINISTICALLY request or suppress `{type=diagram}` sections, with the DEFAULT
  unchanged (the WRITER decides — see the live-demo finding that the writer emitted a fact-checked diagram
  on its own, unrequested). Maintainer's sketch: a −5…+5 slider (−5 guarantee suppress · 0 neutral/current ·
  +5 guarantee request) — but **an architect designs the HONEST semantics**: "+5 request" cannot mean
  *fabricate* a diagram (the HARD grounding gate still binds — a diagram may only depict grounded facts), so
  "request" must mean "strongly require IF the content supports a grounded diagram"; "−5 suppress" can be a
  hard drop. Open: where it lives (recipe vs format attribute, cascading), its true shape (slider vs a
  small enum), how it maps to the writer prompt vs the compose gate, and its identity impact. **DESIGN PASS
  IN FLIGHT** (architect→plan, kicked off 2026-07-30 after the CLI-UX build landed; extends the just-built
  normalizer/friendly-flag surface). Records: `ops-handoff/authoring-ux/`.
- **Source:** maintainer requirements — user-friendly invocation + recipe/entry authoring + "the user has
  to be able to set everything, and the documentation must specify what each attribute means and does" +
  a deterministic diagram request/suppress nudge over the writer-decides default.

---

## Resolved

The build's HARD GATES were closed inline during the build (gate G2 at steps 37–38, the §21.7
generation-code gate at step 39); those are recorded in `state.md` and the commit history. The
entries below are post-build defects, starting with the **`render-output-fix`** series (2026-07-16).

### GAP-12 — The "no publishable facts" driver error was imprecise when facts are held purely by rights — RESOLVED (sources P2a)
- **Severity:** Low (behaviour was already CORRECT — the facts are rightly withheld; only the
  operator-facing message could mislead. Dormant under backward-compat: the schema floor `full` ⇒
  every existing source is `republishable` ⇒ `published == publishable_facts`; it first bites when a
  source declares restricted rights (`reuse_rights < attribution`), which sources P2 introduces).
- **Symptom:** `pipeline/driver.py::_run_artifact` raised the single message "grounding returned no
  publishable (EXTRACTED) facts" whenever `published` was empty. Post-P0, `published =
  publishable_facts filtered by republishable`, so that path also fires when there ARE EXTRACTED facts
  merely held back by `reuse_rights` — the "no EXTRACTED facts" framing points an operator at the
  wrong axis (tiers/anchoring) instead of the rights config.
- **Fix (P2a):** the empty-`published` block now SPLITS on the outcome — `outcome.publishable_facts`
  non-empty ⇒ EXTRACTED facts EXIST but were ALL withheld by `reuse_rights` (leads only) ⇒ a distinct
  loud typed `DriverError` naming the `reuse_rights` (§6.1) axis and stating the facts are correctly
  held as leads; `outcome.publishable_facts` empty ⇒ the ORIGINAL "no publishable (EXTRACTED) facts"
  message (unchanged, so the genuine no-EXTRACTED path is byte-identical). Both stay `DriverError`
  (loud + typed, no traceback); no §21.7 taxonomy code was invented (the raise was and stays a WIRING
  failure, code-less per §3.1). No `schema_version` / `ir_version` bump; no identity surface touched.
- **Source:** sources subsystem P0 (`reuse_rights`/`republishable` gate) coder + reviewer flag;
  closed at sources P2a (this commit) alongside the driver HEAD-freeze. Test:
  `tests/test_sources_driver_freeze.py::TestGap12PublishedSplit`.

### GAP-4 — CI guards: two functional halves not yet wired — RESOLVED (a: `6b196a6`; b: `330fc6d`)
- **Severity:** Low
- **(a) unknown-registry-root** — a brand-new top-level registry dir could pass the content-guard
  silently. RESOLVED by F-b (`6b196a6`): `check-no-content.sh` HARD-FAILS (`LEAK[unknown-registry-root]`,
  exit 1) on any top-level dir carrying an `_schema.yaml` that is not in `REGISTRY_ROOTS`, so a new
  registry root can no longer ship unscanned (fully closed once `lexicons/` shipped and joined
  `REGISTRY_ROOTS` at DR-2 C1).
- **(b) SV11 PR-base wiring** — the schema-lint version-diff clauses were wired to a PR-base baseline
  (per-commit), flagged as unverified end-to-end. RESOLVED by superseding that wiring entirely
  (`330fc6d`): the version-lint is now RELEASE-relative — it baselines the last release via a committed
  marker (`pipeline/released_baseline`, absent pre-release), so the version-bump clauses are inert during
  development and enforce only from the first change after a release (aligning the code with the §11.2 /
  `5b1c584` release-only bump policy). There is no PR-event-dependent path left to verify; CI now runs
  `schema-lint.sh` unconditionally on push and PR.
- **Source:** step-13 review; (a) F-b `6b196a6`; (b) release-relative lint `330fc6d`.

### GAP-10 — The `render` verb minted under a bare check-then-mint with NO claim (double-spend race) — RESOLVED (2026-07-23)
- **Severity:** Medium (a COST leak, never corruption — the no-replace `commit_new` still admits exactly
  one output per id, so two contenders never produce a double OUTPUT; but both would run the PAID LLM
  reshape / pandoc serialize). A latent framework defect DR-1's persistent HTTP front would make hotter
  (concurrent identical requests), which is why it is fixed upstream in the framework, standalone.
- **Symptom:** `pipeline/api/render.py::_render` minted the fit (`should_mint and not is_done(...)` →
  `mint_fit`) and the deliverable (same guard → `mint_deliverable`) under a bare **check-then-mint with
  no claim**. Two concurrent identical renders BOTH pass `not is_done` (neither has committed yet) and
  BOTH run the expensive paid mint — a double-spend. `generate-next` never had this: it claims at S1
  (`spine.py` `claims.acquire(unit.id)`) before the paid work.
- **Root cause:** the built claim wrappers `fit_resolution.claim_fit` (`:471`) and
  `serialize.claim_deliverable` (`:1209`) — thin, tested wrappers over the §22.3 `ClaimRegistry.acquire`,
  DESIGNED for the live render path — were called **only from `tests/`**, i.e. dead on the live mint path.
  The primitives existed; the render handler simply never wired them.
- **Fix (Option A — wire the existing claim primitives):** `_render` now builds one workspace-scoped
  `ClaimRegistry` (`spine.registry_for`, fresh RV-4 holder) and brackets EACH paid mint in the SAME
  acquire→work→release the generate-next spine runs (S1→S6): `claim_fit`/`claim_deliverable` acquire the
  content-addressed fitted-/deliverable-id BEFORE the mint; the no-replace commit stands; `registry.release`
  runs in a `finally` (holder-checked — even an `_EngineError` or any exception leaves NO dangling claim).
  A **held** claim (another contender minting) surfaces as the EXISTING re-drivable coded block
  `claim-held` (`results.CODE_CLAIM_HELD`, warn) — the same outcome `parallel.result_for_spine` maps a held
  work unit to; the caller re-drives by id, exactly one contender mints. No new taxonomy code, no
  `ALL_CODES` change, no `schema_version`/`ir_version` bump. Behaviour-neutral for the single-render happy
  path: the mint is bracketed by acquire+release (the claim file is created then unlinked), so the output
  bytes + ids are byte-identical; and the **cache-hit / `is_done` path acquires NO claim** (the guard is
  `should_mint and not is_done`). The acquire-then-`is_done`-became-true race is handled: after acquiring,
  `_render` re-checks `is_done` under the claim and falls through to fetch instead of re-spending the mint.
  This also gives render the same `peek`-based liveness as generate-next (the DR-1 Commit-7 prerequisite).
- **Verified:** new `tests/test_render_verb.py::TestGap10RenderClaimDoubleSpend` (5 tests) — two concurrent
  identical renders (fired deterministically via re-entrancy, no threads) run EXACTLY ONE `mint_fit` (and,
  separately, one `mint_deliverable`), the other gets `claim-held` and spends nothing; `peek(fitted-id)`
  from an independent registry is LIVE during the mint; a `mint_fit` that raises `_EngineError` releases in
  the `finally` (claims dir empty, id immediately re-drivable); the cache-hit render acquires ZERO claims
  and leaves a byte-identical store snapshot. Full suite green (all pre-existing render tests unchanged);
  `ruff check .`, `scripts/check-no-content.sh`, and `scripts/schema-lint.sh` clean.
- **Source:** surfaced by the DR-1 (HTTP-shim) planner adversarial pass (`planner-03-reconciliation` §D /
  §(A)-H1) and ratified by the maintainer as a **standalone** framework fix — the same posture as GAP-9,
  a prerequisite that lands before the DR-1 sequence.

### GAP-9 — Cross-client isolation was enforced per-id but NOT at the workspace store ROOT — RESOLVED (2026-07-23)
- **Severity:** High (isolation is the framework's core security invariant — CLAUDE.md rule 2, §10).
- **Symptom:** the §21.1 isolation gate validates every referenced id against a workspace store built
  as `WorkspaceStore(<root>/workspaces/<workspace>)` — but `<workspace>` came straight from the caller
  with **no validation**. A name like `workspace="../other-client"`, an absolute path (`"/etc"`), or a
  `workspaces/<name>` symlink pointing outside would **move the store root itself**, so a referenced id
  would resolve inside the WRONG workspace and **pass** the per-id gate. The invariant "isolation is
  enforced by the API, not by trust" (§21.1) was therefore FALSE for the workspace root. (Not
  exploitable in v1 — both live doors, the CLI and programmatic `invoke()`, are driven with trusted
  names — which is exactly why the fix belongs in the framework, not in a caller.)
- **Root cause:** `pipeline/api/invoke.py` built the store root directly from the raw `workspace` string
  and `pipeline/store.py` trusts the caller for placement (it validates id-derived FILENAMES via
  `parse_id`, never the workspace directory NAME); no workspace-name validator existed anywhere in
  `pipeline/` or `scripts/`. The per-id gate is only as strong as the store root it checks against.
- **Fix (resolve-and-contain):** a new shared, reusable guard `pipeline/workspace_name.py`
  (`validate_workspace_name`) is called at the store-root construction site in `invoke.py` (the sole
  untrusted door) BEFORE any store access, and raises the whole-invocation-fatal `isolation-violation`
  gate (`envelope.ok=False`) on a breach — the root sibling of the existing per-id gate. Two
  complementary checks: **(1) PRIMARY resolve-and-contain** — the resolved candidate root must be a
  DIRECT CHILD of the resolved `workspaces/` (`candidate.resolve().parent == base.resolve()`), which
  deterministically catches `..`, absolute paths, AND symlink escapes and is existence-independent (a
  not-yet-created workspace still validates); **(2) SECONDARY hygiene** — the name must be a single safe
  path segment (charset DERIVED from the whole existing corpus so `mvp-demo` / `optiquitytrader` /
  `workspace.template` — interior dot — and every generic test label still pass; empty, `/`, a bare
  `.`/`..`, and a leading `-` are refused). Behavior-neutral: a valid name yields the byte-identical
  store root, so the corpus and the full suite are unbroken; the store-injection test seam (which places
  nothing from the name) is untouched. **Not in scope (correctly excluded):** the DR-1 instance
  ALLOW-LIST — that is the deferred DR-1 shim's POLICY layer, distinct from this framework containment.
- **Verified:** new `tests/test_workspace_name.py` — the guard accepts every existing valid name
  (unit + through the door), refuses `../other-client` / `/etc` / `""` / `.` / `..` / `a/b` / `-lead`
  (typed fatal `isolation-violation`, `envelope.ok=False`), catches a **symlink escape**
  (`workspaces/evil` → outside) via the resolve step, and an isolation-proof test shows `../victim` (a
  traversal to a store that genuinely holds the artifact) is now refused at the door before the id can
  resolve in the wrong workspace. Full suite green (proves no valid workspace broke); `ruff check .`,
  `scripts/check-no-content.sh`, and `scripts/schema-lint.sh` clean.
- **Source:** surfaced + verified by the DR-1 architect design pass and ratified by the maintainer as a
  **standalone** framework fix, independent of DR-1 (2026-07-23).
- **Superseded / extended by (§23 users/-layout re-home, B4→B5):** workspace addressing moved to
  `users/<user>/workspaces/<workspace>/`, and the single-level `validate_workspace_name` was replaced
  by a **3-level `validate_workspace_path(root, user, workspace)`** (`3b7984d` B4, added beside the old
  one; cut over in `ff41a30` B5). It applies the SAME resolve-and-contain + hygiene checks at ALL THREE
  levels (`users/` → `<user>` → `workspaces/` → `<workspace>`) and refuses a missing/None `user` at the
  door (never a `users/None/…` path). GAP-9's invariant ("isolation enforced by the API, not by trust")
  holds unchanged and is now enforced one level deeper.

### Folder adapter could ground but not compose (commitless + unregistered) — RESOLVED (2026-07-18)
- **Symptom:** a `folder` source grounded fine but couldn't mint an artifact-id — the folder adapter was
  commitless (`pin_commit → None`) while §7.2 requires exactly one commit per source, so
  `build_artifact_preimage` failed; and `FolderAdapter` was not in the production adapter set, so a folder
  source wasn't reachable through `begin-session`/`invoke`/`run_thread`.
- **Closed by:** `0d2cc45` — the folder adapter pins a git-checkout's HEAD via a READ-ONLY
  `git rev-parse HEAD` (`ground().built_at_commit` and `pin_commit()` agree, CF-1), so a git repo is
  compose-capable; a plain non-git folder stays commitless as designed; plus a `budget` connection key
  bounding grounded facts (folder's analogue of graphify's `--budget`). Then `c4f481d` — a single
  `pipeline.adapters.default_adapters()` factory registers `{graphify, folder}`, delegated to by session +
  driver (cycle-free; a future third adapter is a one-place change).
- **Demonstrated:** a LIVE run over `~/Developer/OptiquityTrader` (a non-Graphify Swift repo, READ-ONLY
  throughout) — pinned HEAD `3a79a92`, grounded 40 facts from `docs/project/ARCHITECTURE.md`
  (budget-capped), composed a grounded artifact `a-1ebf747e75ccc422` (~$0.69).
- **Source:** discovered 2026-07-18 while standing up OptiquityTrader as a folder-adapter source for the
  outline (DR-3) work.

### GAP-1 — Cannot re-render a stored document into another format without re-running the pipeline — RESOLVED
- **Closed by:** `558846c` (driver + `render.py::_render` read the **raw** stored IR via `unwrap_ir`;
  a re-render loads the stored artifact IR and drives serialize-only, no LLM) + `1f40f87`
  (external-side routing via a side-tagged `MintOutcome` → `payload.build_payload`).
- **What closed it:** `render`/`driver` now load the raw stored IR instead of expecting an
  `{"ir": …}` wrapper, and branch on `target.side`: **internal** targets serialize-only through the
  pinned pandoc writer (no re-grounding, no re-compose), **external** targets emit a zero-provenance
  RI14 contract payload (`{binding, side, payload, stripped}`, no bytes) for the external actor.
- **Verified (live):** stored artifact `a-5dc2cbd9676240e9` (real 13,208-byte body) re-rendered to
  `plain-text`/`html` (internal, clean readable prose) + `epub` (external payload, `side: external`,
  `stripped: true`, no bytes) with the transport tripwire NEVER firing — a hard-failing engine proved
  no recompose/LLM call. Deterministic. Confirms internal ≠ external.

### GAP-2 — No user-facing entry point for arbitrary render/generate requests — RESOLVED
- **Closed by:** `3a92f24` (the `pipeline invoke <verb>` machine door — registers render + fetch-by-id,
  JSON envelope on stdout, exit codes 0/1/2/3, §21.9 operator verbs structurally excluded via the
  `KNOWN_VERBS` gate) + `7ab9663` (the ergonomic `pipeline render` subcommand delegating to the same
  door).
- **Two doors, one seam:** a human runs `pipeline render --user U --workspace W --item <id> --output-type <t>`;
  an external actor (v1: self-hosted n8n via its Execute Command node) runs
  `pipeline invoke render --user U --workspace W --params-json '{…}'` (`--user` is mandatory wherever
  `--workspace` appears, §23). Cloud orchestrators still need the HTTP
  shim — see **DR-1**.
- **Verified:** both doors exercised by `tests/test_api_invoke.py` (`TestCliDoor`,
  `TestErgonomicRenderSubcommand`); the live re-render above went through the door.

### GAP-6 — A degenerate / near-empty writer body passed the contract and shipped as "ok" — RESOLVED
- **Closed by:** `558846c` (a **visible-text substance floor** on the body contract).
- **What closed it:** `ir._has_substance()` requires ≥1 Unicode letter/number over the NFC-normalized
  **visible** text (markup/attributes stripped); a body that is ellipsis-/punctuation-/whitespace-only
  now raises `ir-empty-substance`, which flows into the existing bounded re-ask and, on exhaustion,
  fails **LOUDLY** (§3.1) instead of shipping empty. Recovered re-asks are surfaced/logged, not silent.
  This is the *guardrail* behind GAP-8's *cure*.
- **Verified:** `tests/test_ir.py` + `tests/test_compose.py` (the floor rejects `"..."` / markup-wrapped
  placeholders, accepts real prose; the re-ask fires and is recorded in `violations`).

### GAP-8 — Compose returned a degenerate `"..."` body (empty deliverables in every format) — RESOLVED (fix landed; ablation directional)
- **Root cause (diagnosed, VERIFIED):** `pipeline/prompts/writer.md` opened with a
  `<!-- … STATIC contract … -->` developer-comment header; the writer model read it as *pasted file
  content* and, instead of composing, returned a meta-commentary refusal (or a `{"body":"..."}`
  placeholder). The valid-JSON placeholder passed the parse → no re-ask → shipped empty (the GAP-6
  hole); the non-JSON refusal tripped the bounded re-ask and recovered.
- **Closed by:** `a6d101b` (removed the leading dev-comment header from `writer.md`; the note moved to
  the loader docstring). GAP-6's floor backstops any residual case.
- **Verified (directional):** EXP-10 header ablation — V0 (header present) **3/8** runs derailed (each
  the exact diagnosed non-JSON refusal signature); V1 (shipped, header stripped) **0/8**. **Caveat:
  n=8, Fisher exact two-tailed p = 0.20 — not significant at α=0.05.** Directional evidence the fix
  removed the diagnosed trigger, not a significance-tested proof; the GAP-6 floor guarantees loud
  failure regardless.

### GAP-5 — Optional hardening (defense-in-depth, not required by design) — RESOLVED (2026-07-23)
- **Closed by:** `551fc42` — all three optional items landed together as happy-path-neutral hardening
  (each adds only a raise path or surfaces a previously-dropped warn; clean inputs stay byte-identical):
  **(a)** `payload.build_payload` now re-scans the `fitted_ir` metadata for secrets (reuses
  `ir._scan_no_secrets` + `SecretShapedValueError`), so a hand-built `fitted_ir` that bypassed the
  IR-level secret-scan is still caught; **(b)** `api/manifest._resolved_row` now carries the §21.8
  rule-2 `render-input-mismatch` warn onto the render-needed-from-stale-fit branch (it was dropped,
  under-reporting fit-staleness for one cycle; the fit-current path is unchanged, `warn=None` no-op);
  **(c)** `serialize` adds a per-document part-Div `#id` uniqueness check (`DuplicatePartIdError`,
  raised before any bytes; unique slugs render unchanged).
- **Verified:** +5 load-bearing tests (`tests/test_payload.py`, `tests/test_manifest.py`,
  `tests/test_serialize.py`); reviewed CLEAN (neutrality + no-import-cycle proven at runtime, not
  asserted); full suite **2651 passed** with ruff + content-guard + schema-lint green.
- **Source:** step-25/27/29/35 review observations, each marked optional (was GAP-5 under **Open**).
