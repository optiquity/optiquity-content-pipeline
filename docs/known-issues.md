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

### GAP-4 — CI guards: two functional halves not yet wired
- **Status:** Open
- **Severity:** Low
- **Symptom:** (a) a brand-new top-level registry directory is outside the content-guard's known-root
  whitelist and passes silently; (b) the SV11 schema-lint PR-base diff clauses only activate on a PR
  event, and the repo has no PRs yet, so that wiring is unverified end-to-end.
- **Proposed fix:** tighten `scripts/check-no-content.sh` to fail on an unknown registry root; verify
  the SV11 PR-base wiring in `.github/workflows` once the repo gains PRs.
- **Source:** step-13 review, deferred through step 40.

### GAP-5 — Optional hardening (defense-in-depth, not required by design)
- **Status:** Open
- **Severity:** Low
- **Items:** (a) an optional payload-side metadata re-scan in `payload.build_payload` (closes a residual
  where a caller hand-builds a `fitted_ir` bypassing the IR secret-scan); (b)
  `manifest._resolved_row` could carry the §21.8 rule-2 `render-input-mismatch` warn onto the
  render-needed-from-stale-fit branch (under-reports fit-staleness for one cycle today); (c) a
  part-Div `#id` uniqueness check for multi-part/folio assembly (HTML-validity nit).
- **Source:** step-25/27/29/35 review observations, each marked optional.

### GAP-7 — The ideation phase (mission stage 1) is not built — topics must be hand-authored
- **Status:** Open (deliberate v1 scope boundary, tracked here as a missing capability)
- **Severity:** Medium–High (a whole missing pipeline stage — half of the mission's two-stage design)
- **Symptom:** The mission specifies a **two-stage** pipeline — **ideation** (source repo + audience →
  a ranked idea queue) then **generation** (idea → formatted artifact) — but v1 builds only
  *generation*. There is no ideation engine: nothing reads a repo's Graphify graph (god-nodes,
  communities, suggested questions) + audience personas to propose and rank content ideas. The nine-axis
  matrix starts from **topics** (§5.2, axis 1), which in v1 must be **hand-authored** as
  `workspaces/<client>/topics/<id>.md` entries (they may be manually seeded from Graphify's
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
- **F-b** — GAP-4 content-guard known-root fix. **NO-GO for DR-2's `lexicons/` root.**
- **#3** — the F1 sentinel section-grammar + section-constraint vocabulary, built **SHARED** at DR-4
  (consumed by DR-4 conformance AND the deferred DR-3 `constraint?`). **NO-GO for DR-4.**
  **#3a** — F1 sentinels **N-invariant** (a DR-3 build-time requirement: reserve the sentinel-significant
  structure when pinning N, so un-deferring F1 churns no `outline-digest`). **NO-GO for DR-3 + DR-4.**
- **#4** — extend the §16 RI5 reconcile-gate ordering (DR-4 structural gate + DR-6 coverage re-check +
  terminal hard-limit gate; joint hard-structural × hard-limit → block-and-report). **NO-GO for DR-4.**
  **#4a** — per-section numeric limits are **DR-4 structural constraints** (section-addressed); the §16
  terminal gate keeps ONLY artifact/capacity limits. **Retract "abstract ≤N words already built."**
  **NO-GO for DR-4.**
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

### DR-1 — HTTP/webhook interface for cloud-hosted workflow orchestrators
- **Status:** Deferred (not in v1) — requirement recorded for a later build.
- **Need:** The v1 external-actor door (GAP-2) is the local `pipeline invoke render` CLI, invoked
  by an orchestrator that can shell out to the **same machine** (v1's named consumer: self-hosted n8n
  via its Execute Command node). **Cloud-hosted** orchestrators — Make, Zapier, n8n Cloud, Google
  (Workflows / Apps Script), and others — cannot execute a local CLI; they can only call an **HTTP
  endpoint** (typically a webhook). To serve those users the pipeline needs an HTTP interface.
- **Shape (design intent):** a thin, **transport-agnostic HTTP shim over the existing `invoke()` API**
  — one endpoint taking `{verb, workspace, params}` (or one per verb), returning the **same JSON
  envelope** the CLI emits (`ok`, `results[]`, a status mapping to the CLI exit codes 0/1/2/3). It adds
  **no business logic** — it reuses the exact handlers the CLI door wires. Because it is
  network-exposed, **authentication (token / API key) and rate limiting are part of this item**, as is
  restricting it to the safe external verb set (never the operator-only verbs, §21.9).
- **Why deferred:** v1's only named consumer is self-hosted n8n on the same host (maintainer,
  2026-07-13), for which the CLI door suffices. The HTTP shim was designed (see the `render-output-fix`
  GAP-2 design) as an **additive** component so it drops in later without disturbing the CLI/`invoke`
  door.
- **Depends on:** GAP-2 (the CLI/`invoke` door + `register_*_handler` wiring) lands first; the shim
  sits on top of the same `invoke()`.
- **Source:** maintainer requirement, 2026-07-13 — "needed eventually for other users who use any
  cloud based workflow orchestrator (Make, Zapier, n8n, Google, and others)."

### DR-2 — Selectable style guides (writing-rule presets) — design question, not yet a settled feature
- **Status:** Deferred (not in v1) — **requirement + open design questions recorded; to be designed by
  an architect before anything is built.**
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
  were dropped as redundant). **Partially reopened by DR-5:** that design places all house-mechanical
  style at **compose** (baked into the IR), but per-venue style variation from a single shared IR needs
  some style applied at **render** — so the compose-only placement is now an open question. **Build
  paused** pending DR-4 / DR-5 scoping.

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
    **hand-authored** outlines; **defer only the LLM drafter** (a named DR-3 backlog, GAP-7 mirror). Verb
    surface: reuse the existing session/render verbs (no new `KNOWN_VERBS` verb).
  - **Plan:** the reconciled 7-commit plan (`03-planner-reconciliation`) — Commits 1-3 identity-safe
    foundation, 4-7 + trigger the usable feature at horn (a). Building now under the standing coder/reviewer/
    fix cadence.

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

---

## Resolved

The build's HARD GATES were closed inline during the build (gate G2 at steps 37–38, the §21.7
generation-code gate at step 39); those are recorded in `state.md` and the commit history. The
entries below are post-build defects closed by the **`render-output-fix`** series (2026-07-16).

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
- **Two doors, one seam:** a human runs `pipeline render --workspace W --item <id> --output-type <t>`;
  an external actor (v1: self-hosted n8n via its Execute Command node) runs
  `pipeline invoke render --workspace W --params-json '{…}'`. Cloud orchestrators still need the HTTP
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
