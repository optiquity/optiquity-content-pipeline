# DR-2 (style guides) × DR-3 (outline) × the nine dimensions — Architect INITIAL design

**Pass:** COMBINED design, stage 01, mode INITIAL (initial → adversarial → reconciliation, maintainer-gated).
**Class:** read-only. No repo edits. This is a design recommendation — **not** an implementation plan and **not** code.
**Grounded in:** `docs/design.md` (the live SSOT; `docs/design-decisions.md` is a tombstone → design.md), `docs/known-issues.md` (DR-2, DR-3), the stage-0 research report, `CLAUDE.md`, and the live schemas (`voices/`, `formats/`, `goals/`, `platforms/`, `output-types/`, `recipes/`, `presentations/`), read directly this pass.

---

## Executive verdict (one paragraph)

**Style guide (DR-2):** build almost nothing new. A "style guide" is already ~90% composition over existing axes (tone→Voice, limits→Platform, typography→Presentation, skeleton→Format, serialization→Output-type); the research's central finding holds — the **only homeless element is class (ii): terminology / word-lists / preferred+banned terms / product-name casing / house mechanical rules**. So: **(1) one required new carrier — a minimal content-side `lexicons/` registry for class (ii);** **(2) the "selectable named style guide" itself is a thin content-side OVERLAY (`style-guides/`) that carries only per-dimension attribute _overrides_ + a lexicon ref + an optional prose overlay — never a new dimension, never a rendering pin.** **Outline (DR-3): yes, it is needed — but only for the one capability no reusable-registry dimension can provide:** a per-artifact, user-editable content+structure *plan* (Format gives per-*type* structure; Goals/Topic give focus; neither gives per-*artifact* specificity or an editable intermediate). The outline is **the IR's own skeleton, pre-compose** (§15 is already "an ordered `parts` list") — a new optional pre-compose stage-product, dual-natured (serialize it = OUTPUT; seed compose = INPUT), with a `drive: structure|content|both` control. **Precedence, in one line:** two orthogonal decision planes — the **value plane** (M1/M2/M3 cascade; the style guide is a *low nudge rung* below recipe, brand-lockable via the existing §12.6 `authoritative` flag) and the **content plane** (the outline is the *dominant compose seed*: outline-structure > Format-skeleton, outline-content > topic/goal emphasis) — with the **EXTRACTED publish floor (§6.5) invariant beneath both**, so style and outline shape *how it reads and how it is structured* but never *what is claimed*.

**External research:** not required. The stage-0 research already covered how real style guides are structured; the outline-necessity analysis is answerable from the internal model (below), and outline-first authoring is a well-understood pattern. I attempted and completed the necessity analysis internally; no external pass is requested.

---

## Part A — DR-2 style guide verdict

### A.0 Verdict: a two-part hybrid — one required carrier + one thin overlay

| # | Build | What | Why it is the minimum |
|---|-------|------|------------------------|
| **1 (required)** | `lexicons/` registry (content-side, one-file-add) | The homeless **class (ii)**: `preferred_terms`, `banned_terms`, `proper_names` (casing), `spelling: us\|uk`, `mechanical` (Oxford comma, number/date style, unit style) | Research §3.2(3): class (ii) is the **only** element type with no existing home. Everything else duplicates an axis. This is the genuine gap. |
| **2 (ergonomic)** | `style-guides/` overlay registry (content-side, one-file-add) | The **selectable "named style guide"** = per-dimension attribute **overrides** (voice sliders/guidelines) + a **lexicon ref** + optional prose overlay. Standard/platform-fitted (`provenance: framework`) and corporate (`provenance: instance`). | Existing constructs miss the exact ergonomic: recipes are per-artifact (topic-bound, not cross-topic), scope-defaults are workspace-wide (not per-request-selectable), the §12.6 flag is Voice-only + workspace-wide. A thin overlay is the smallest thing that delivers "select one named writing overlay per request." |

**What is deliberately NOT built:** no new **axis/dimension** (a 10th axis would fan out — wrong — and would re-own attributes other axes already own — blur); no rendering pins on the guide; no Format change (Part D); no new identity surface (reuse §7.2 delta-vs-floor).

**Considered and rejected — "build literally nothing" (express style guides purely as recipe/scope-default bundles):** viable for the *bundle* half, but (a) fails the "per-request-selectable, cross-topic overlay" requirement and (b) leaves class (ii) homeless. Rejected as insufficient. **Leaner variant worth the adversarial pass's attention:** build only `lexicons/` (item 1, required) and let recipes/scope-defaults carry the voice-overrides, dropping `style-guides/` (item 2) as mere sugar. My primary recommendation keeps item 2 because the maintainer explicitly asked for a *named selectable* guide with standard/platform/corporate flavors — but the reconciliation should weigh dropping it.

### A.1 The orthogonality firewall (what a style guide MUST NOT carry)

The guide carries **only content-side writing overrides + a lexicon ref**. Everything below is banned in the guide and stays where it lives:

| Concern | Owner axis | Why banned from the guide |
|---|---|---|
| Tone / register / affect / manner | **Voice** (§5.2) | The guide may *override* Voice's declared attributes (M2), never *be* a second tone carrier. |
| Char/word limits, platform norms | **Platform** (`hard_limits` outside M2 §12.7; `advisory_norms` ride M2) | Absorbing these blurs Platform (research §3.1). Hard limits are never bound anywhere. |
| Typography / fonts / CSS / margins | **Presentation** (§5.3 PD3) | Deterministic style @ serialize; a style unit must not disable grounding (PD3). |
| Section skeleton / genre structure | **Format** (rhetorical body + `parts`) / **the outline** | This is the load-bearing firewall for Part C: the guide carries **no structure**, so no three-way structure conflict can arise. |
| Serialization (md/html/pdf/docx) | **Output-type** (§5.3) | A coordinate, not a rule. |
| Rendering routing (platform/language/output-type/presentation *selection*) | recipe / run / scope (per-deliverable routing, CA8) | The guide is content-side only; pinning render targets would straddle the compose/render identity split — the exact reason §12.6 restricts brand-lock to **Voice-only in v1**. The guide follows that ratified precedent. |

**The one genuinely-new payload the guide introduces is the lexicon (class ii); every other field is a passthrough override of an existing axis attribute.**

### A.2 Override vs re-declaring an axis (the precise line — already machine-enforced)

DR-2's constraint ("nudges a dimension, never replaces it") is **already a wall in the design** — §21.4 (API5): an override binds a **value to a declared attribute of an already-selected entry**; it can **never** pick or replace *which entry* is used (that is `selection`, an M1 input). Applied to the guide:

- **Allowed (M2 override):** `voice.formality: 4`, `voice.guidelines: <prose overlay>`, `voice.warmth: 2`. These are value bindings on the already-resolved Voice entry.
- **Forbidden (M1 selection):** "use voice entry `business`." The guide never selects entries. A LinkedIn guide is "the writing overrides appropriate for LinkedIn," not "use voice X / publish to LinkedIn." Entry selection and platform routing stay with recipe/run/scope.

This is exactly the M1/M2 boundary the design already enforces — the firewall needs no new mechanism.

### A.3 The Voice-vs-terminology line (DR-2 open-question (c) — the sharpest blur)

Research §3.1 flags that `voices/clear-explainer.md` **already** carries a banned-words list (`"simply"`, `"just"`, `"revolutionary"`). The line:

- **Stays in Voice `guidelines`:** bans/diction that are **tone discipline** — they *co-vary with the voice*. `clear-explainer`'s "no hype" ban is part of what makes that register; pick a punchier voice and it changes. Test: **does the rule change if you pick a different voice?** If yes → Voice.
- **Goes in the `lexicon`:** **house mechanical policy** that holds *across every voice* — product-name casing ("Optiquity", capital O), US/UK spelling, a house banned-terms list, number/date style, Oxford comma. Test: does it hold regardless of tone? If yes → lexicon. A company's formal-PR voice and casual-blog voice share one term-list; that shared, tone-independent list is precisely why it must **not** live on Voice (it would force re-declaration per voice, or drag the list along when you change tone).

This resolves the blur: the shipped `clear-explainer` bans are legitimately Voice (tone); a *house term collection* is the lexicon.

### A.4 Schema / where-it-lives / provenance / selection / composition with M2

**`lexicons/` (content-side registry, one-file-add):** attributes ~ `preferred_terms` (map `avoid→use`), `banned_terms` (set), `proper_names` (map `token→canonical-casing`), `spelling` (enum `us|uk`), `mechanical` (map: `oxford_comma` bool, `number_style`, `date_style`, `unit_style`). Selectable independently (a request may pick a lexicon with or without a style guide). Applied at **compose** (writer honors it) and **preserved at reconcile** (§16 fidelity constraint (i) already requires the LLM rewrite to preserve content parameters — the lexicon rides that rail; no new reconcile identity surface). Enters **`artifact-id`** as a content input via the existing §7.2 delta-vs-floor (no lexicon = absent = **zero id churn**).

**`style-guides/` (content-side overlay registry, one-file-add):** attributes ~ `lexicon` (ref, optional), `voice_overrides` (map of `voice.<attr>` bindings, applied at the guide's rung), `guidelines_overlay` (markdown, appended to / replacing voice guidelines per §12.4 prose-replace), `authoritative` (bool + strength `a|b|c`, reusing §12.6). **No rendering fields.**

**Provenance / scope (DR-2 (e)):** framework-standard guides + platform-fitted guides + generic lexicons → `provenance: framework` (public — they are the deliverable, CLAUDE.md rule 4). Corporate guides + corporate lexicons → `provenance: instance`, workspace-scoped (a company's brand — never public; isolation §10). The `x-` namespacing (§11.4) and the CI content-guard already keep instance content out of the public repo. No new provenance machinery.

**Composition with M2 / cascade placement (DR-2 (b)):** the guide expands, at resolution, into M2 value bindings at a **new low overlay rung positioned below L5-recipe and above L3-workspace** (the slot vacated by the retired folio L4 is the natural label; the exact number is a planner detail). Consequences:

- **Nudge by default:** an explicit recipe (L5) or run (L6) value **beats** the guide → the guide nudges, never dictates.
- **Beats scope/entry defaults:** the guide beats L3/L2/L1 → selecting a named guide is more specific than a workspace baseline.
- **Brand-lock via the existing flag (DR-2 (f)/(b)):** a corporate guide flagged `authoritative: true` (§12.6, cited by the research U5 as the "config that wins over the cascade" precedent) **elevates to just-below-run** — beats recipe; only a warned run deviates. This is the ratified BO2 mechanism, generalized from Voice-scope-default to the guide overlay; strengths `a|b|c` carry over unchanged.

**Grounding coexistence (DR-2 (f)):** the guide/lexicon shape *how it reads* (diction, term choice, casing) but never *what is claimed*. The EXTRACTED publish floor (§6.5) is a framework invariant outside all user config; a lexicon can rename how a fact is *phrased*, never invent, promote, or assert one. Same firewall as Voice `guidelines` today; §16's fidelity constraint already forbids tier promotion in the reconcile rewrite.

---

## Part B — DR-3 outline: necessity FIRST

### B.1 The gating question, answered from the internal model

**"Is an outline necessary if an artifact's GOALS are specified with appropriate detail and precision?"**

What keeps an artifact focused and correctly structured **today**:

- **Format** owns the **per-type rhetorical skeleton** (`how-to-documentation.md` → Goal / Prerequisites / Steps / Verification / Troubleshooting; `medium-review-post.md` → Subject / Criteria / Findings / Verdict). This **already delivers "correctly structured per artifact type."**
- **Topic** owns subject + `why`; **Goal-set** owns the outcome(s); **Persona** owns audience/knowledge-level. Together these **already deliver "focused."**

So for **per-type** correctness the maintainer's hypothesis holds: **Format already owns structure-per-type; Topic+Goals+Persona own focus.** An outline is **not** needed to keep an artifact *correctly structured for its type*.

**But precise GOALS cannot substitute for what the outline actually provides**, and the reason is structural, not a matter of "more precision":

1. **Goals are abstract, reusable outcome-TYPES, not a per-request brief.** The live `goals/_schema.yaml` carries exactly two attributes — `kind` (strategic|action) and `source_selection` (M3 clauses). There is **no free-text content-plan field**, and adding one is wrong: goals are *reusable registry entries* selected and **set-valued/stacked** (§5.2); a per-article "cover these 7 points" would (a) require a new goal entry per article (registry explosion + one-file-add abuse), (b) not stack, and (c) is not source-selection. Making goals "precise" hits the ceiling of what a reusable outcome-type can be.
2. **Format is per-genre, reused across every artifact of that genre** — it cannot carry *this* article's specific points/order without becoming a per-article Format (same registry-explosion / reusability break).
3. **Topic is reusable across the matrix** (the same topic → a LinkedIn post AND a how-to doc, which need *different* structures). Pushing a per-article section plan into Topic breaks that reusability and blurs Topic with structure (Format's) and content-plan.

Therefore precise goals + Format give **per-type** correctness but can **never** give **per-artifact specificity** — a bespoke "for THIS piece, cover exactly these points, make these arguments, in this order" plan — **because goals, formats, and topics are all reusable abstractions, and the outline is the per-request instantiation.** Add the maintainer's explicit requirement that the outline be a **dual output+input, human-editable intermediate** — axes are inputs, never editable intermediate artifacts — and the conclusion is firm.

### B.2 Necessity verdict: YES — for one narrowly-defined capability

**The outline is needed — but only for the capability no reusable-registry dimension can provide: a per-artifact, user-authored/editable content+structure PLAN.** It is **not** needed for structure-per-type (Format), focus (Topic/Goals/Persona), or outcome (Goals). If the maintainer's real need were only "focused + structured per type," the answer would be "Format already owns it; make goals/topic precise" — but the stated dual-output/input/editable requirement is satisfiable *only* by the outline. The outline earns its keep on **per-artifact specificity + an editable human-in-the-loop intermediate**, nothing more.

### B.3 Scope and design of the outline

**Core insight (fewest mechanisms):** the IR is **already** "an ordered `parts` list" where each part = `{part-id, role, constraints?, packaging_hint, body(markdown)}` (§15 RI2). **An outline is that same shape, pre-compose** — the IR skeleton with *content-intent* in place of composed prose. So the outline is not a new data model; it is a **pre-compose IR state**. Call it the **plan / outline-IR**.

**What it contains:** an ordered list of sections; per section `{role/heading, intent (what this section covers — which arguments/examples/facts to hit), constraints? (length hint)}`. Scoped to **one** artifact. Grounded like everything else: its intents *reference* topics/facts but assert nothing as published fact.

**Where it sits (additive stage):** a new **optional pre-compose stage** in §2.1's life-of-an-item — Ground → Resolve&bind → **[Plan/outline (optional; editable gate)]** → Compose → Reconcile → Serialize. **When no outline is requested the stage is skipped** (a no-op path exactly like reconcile's, §16) → the default path is byte-unchanged and zero-cost.

**Two modes:**

- **OUTPUT (a first-class renderable artifact):** because the outline-IR is IR-shaped, rendering it = running it through the **existing serialize pass** (§17) to any output-type (md/html/pdf/docx). **No new output-type is needed** (serialization is orthogonal to being-an-outline). Optionally a one-file framework **`outline` Format** entry gives the rendered outline genre polish — one-file-add, not new machinery. The outline-IR is **persisted and id-addressable** (an `outline-id`) via the existing `fetch-by-id` retrieval (§21.5).
- **INPUT (a high-influence pre-generation seed):** the outline-IR is fed to **compose** as the dominant content+structure seed (precedence in Part C). Produced by the plan stage (drafted from the same content selection: topic, persona, format, goals, sources), **edited by the human** (the review/edit gate — its whole point), then **fed back** as the compose seed.

**User control — content / structure / both (the DR-3 requirement):** a mode flag on the outline-as-input, `drive: structure | content | both`:
- `structure` — compose takes the outline's section order/roles as the skeleton (overriding Format's default skeleton) but writes grounded content freely within it.
- `content` — compose treats the outline's intents/points as must-cover content but arranges them per Format's skeleton (or its judgment).
- `both` — the outline is the near-complete blueprint; compose fills grounded prose into the given structure and points.

**Identity (additive, zero churn):** when an outline drives compose, its canonical digest joins the **`artifact-id` preimage** as a new component (delta-vs-absent: **no outline = absent = every existing id unchanged**, §7.2 discipline). Same outline → same `artifact-id` (idempotent); edit the outline → new digest → new artifact (correct: a different plan is a different artifact). The artifact's IR binding records the driving `outline-id` + digest (the fit-binding/render-binding pattern of "record the input at the level that consumes it," §16/§17).

---

## Part C — the integration + PRECEDENCE model (load-bearing)

### C.1 The key move: two orthogonal decision planes, not one stacked order

The elegant resolution is to see that **the style guide and the outline operate on different questions at different mechanisms** — collapsing them into one precedence list is the blur to avoid (§12.1: "collapsing them reintroduces blur"):

- **Value plane** — *how it sounds / looks / is limited.* Resolved by the M1/M2/M3 cascade. The **style guide** is a member of this plane: a **low nudge rung** of M2 (Part A).
- **Content plane** — *what it says, in what order.* Resolved at **compose**. The **outline** is the dominant seed of this plane.

The outline "**outranks the dimensions**" (the DR-3 load-bearing constraint) **not by sitting atop the value cascade, but because content-plan is a decision the value cascade does not own** — the only dimensions that even touch it are Format (structure) and Topic/Goals (content focus), and **where they touch, the outline wins for this artifact.** This is why the outline can dominate content+structure *without breaking orthogonality*: it is not competing for the same rungs as the dimensions; it governs an orthogonal decision and overrides only at the two narrow seams below.

### C.2 The unified precedence, placed explicitly in M1/M2/M3

**VALUE plane (attribute values):**

```
M1 entry resolution:  framework → instance-global → workspace        (which definition loads)
M2 value cascade:     L0 schema < L1 entry < L2 global < L3 workspace
                      < [NEW: style-guide overlay rung]               (nudge — content-side only)
                      < L5 recipe < L6 run
                      + authoritative-flagged guide/brand → just-below-run   (§12.6 BO2)
M3 source selection:  workspace-default < goal-implied < recipe < run (which facts ground it)
Hard limits:          outside M2 entirely — the §16 terminal gate (§12.7)
```

**CONTENT plane (content + structure):**

```
When an outline drives generation (drive ∈ {structure, content, both}):
   outline STRUCTURE  >  Format skeleton        (for drive=structure|both)
   outline CONTENT    >  topic/goal emphasis     (for drive=content|both)
Absent an outline:
   Format supplies structure; Topic/Goals/Persona supply focus   (standard path, unchanged)
```

**INVARIANT beneath both planes:**

```
EXTRACTED publish floor (§6.5)  >  every construct, always — outside all user config.
```

### C.3 The three concrete conflicts, resolved

1. **Outline structure vs Format skeleton.** When the outline drives `structure`/`both`, **outline structure wins**; Format remains the fallback skeleton for any section the outline leaves unspecified and still governs `parts` (named sub-outputs) unless the outline overrides them. Format = the *reusable genre* skeleton; outline = *this artifact's* skeleton.
2. **Outline structure vs a style-guide structural preference.** **Cannot arise by construction.** The Part A firewall bans the style guide from carrying any section skeleton (structure is Format's/the outline's). The guide has no structural payload to conflict — this is precisely why the firewall is load-bearing for Part C. If a guide wants a different genre, that is a Format *selection* (recipe/run), resolved on the value plane, and the outline still wins the specific structure.
3. **Outline content vs Topic/Goals.** The outline's intents govern *what this artifact covers and in what order* — **but within** (a) Topic's subject bound (the outline refines within the topic, never wanders off it), (b) the grounded fact pool assembled by M3 (Goals' source-selection still selects the facts), and (c) the EXTRACTED floor. The outline dominates content **selection/emphasis/order**; it rides on top of the same grounded facts the dimensions assembled and **cannot conjure facts outside grounding.**

### C.4 Style guide vs outline (they never collide)

The style guide (value plane, content-side M2 nudge: tone overrides + lexicon) and the outline (content plane, compose seed: what/order) touch different surfaces. A LinkedIn style guide sets *how it reads* (punchier voice overrides, house terms); the outline sets *what it says and in what order*. Both can be present on one request with no contest: the guide colors the prose, the outline shapes the plan, Format/Topic/Goals/Persona resolve normally, and the EXTRACTED floor holds beneath.

### C.5 Grounding-safety (explicit)

Outline + style/lexicon rules shape **how it reads and how it is structured**; **published claims still ground in EXTRACTED facts** (§6.5, §15, §16 fidelity). Neither invents, promotes, nor asserts a fact. An outline that demands a claim with no EXTRACTED grounding triggers the existing **§6.4 block-and-report** (the deliverable blocks, the offending demand is named) — the outline **never** forces a fabricated or tier-promoted claim into published output. A lexicon renames *phrasing*, never facts. **The EXTRACTED floor outranks the outline, the style guide, the dimensions, and the run — always.**

---

## Part D — the template question + scope split (DR-2 (d))

### D.1 Does FORMAT need a parametric structure attribute (a declarable skeleton with slots)? — NO.

There are three candidate structure mechanisms; leaving them overlapping is the failure the maintainer named. Resolve to a **two-mechanism division of labor**:

| Mechanism | Owns | Scope | Status |
|---|---|---|---|
| **Format** (rhetorical body + `parts`) | the **per-GENRE** skeleton | reusable, abstract, per-type | **keep as-is — no change** |
| **Outline** (Part B) | the **per-ARTIFACT** content+structure plan | specific, per-request, editable | **new (DR-3)** |
| ~~Parametric Format skeleton with slots~~ | — | — | **do NOT build** |

**Why no parametric Format skeleton:**

1. The per-artifact specificity need is served by the **outline**, not by parameterizing Format.
2. A slot-per-artifact Format would smuggle **per-artifact data into a reusable genre entry** — the inverse of the Topic-absorbs-structure blur — breaking Format's one-entry-per-genre reusability.
3. The "declarable skeleton with slots" **already exists as the outline-IR** (§15's ordered parts). A parametric Format skeleton would be a **third** structure representation duplicating the outline — exactly the overlap to avoid.

The research's narrow DR-2(d) question ("is Format's free-prose body enough, or does it need a more explicit attribute?") resolves to: **the free-prose body is enough at the genre level; any need for more explicit structure is a per-artifact need = the outline.**

### D.2 Scope split: own DR, folded, or absorbed?

**The template/structure concern needs no new DR and no Format extension — it is fully absorbed:** genre structure → **Format** (exists, unchanged); artifact structure → **Outline** (DR-3). This collapses the three overlapping structure mechanisms into **two orthogonal ones (genre vs artifact)**, eliminating the overlap. Industry backs this split (research §4: style guide = rules, template = skeleton, distinct); here the skeleton role is Format's, and the *bespoke* skeleton role is the outline's. **No separate "template" DR should be opened.**

---

## Cross-cutting: one-file-add and identity preservation (checks)

- `lexicons/` entry = one conforming file (§5.4). ✓ `style-guides/` entry = one conforming file. ✓ Optional `outline` Format = one file. ✓
- The outline stage, the style-guide overlay rung, and the lexicon compose/reconcile wiring are **framework mechanism changes** (one-time build + design ratification), not registry edits — the same class of change as reconcile-strategy or the §12.6 flag. This is the honest cost; flag it for the planner.
- **Zero new identity surface:** lexicon + voice-overrides enter `artifact-id` via existing §7.2 delta-vs-floor; the outline digest is an additive `artifact-id` component (absent = zero churn); the style guide adds nothing to `fitted-id`/`deliverable-id` (content-side only). No existing id churns.

---

## Open questions handed to the ADVERSARIAL pass (mode 02)

1. **Is `style-guides/` (item 2) worth its weight, or should the pass push the leaner "lexicon-only" variant** (recipes/scope-defaults carry voice-overrides; drop the overlay construct)? Attack the ergonomic-necessity claim.
2. **The overlay rung placement.** Reusing the vacated L4 label vs a fresh sub-rung below recipe — and whether a *content-side-only* overlay rung is clean, given content dims bind at compose. Attack for cascade blur.
3. **Terminology home:** folded into the guide vs an independent `lexicons/` registry. I chose independent (real sharing case: multiple corporate guides share one house term-list; applies at compose AND reconcile). Attack the YAGNI/blur tradeoff either way.
4. **Outline as a new STAGE vs a sub-step of compose.** I placed it as an optional pre-compose stage with a no-op skip. Attack for whether it belongs inside compose (§15) instead, and whether the outline-IR reuse of §15's part shape hides a coupling.
5. **Outline identity as an `artifact-id` component.** Attack: does a full-plan digest belong in the artifact preimage, or does it over-couple identity to an editable object? (Cf. §27.3's registered caution about adding the M3-expression digest to the preimage.)
6. **`drive: structure|content|both`** — is three modes the right cut, or does it hide a fourth (e.g. content-order-only)? And does `drive=structure` overriding Format's skeleton quietly re-open the Format-vs-outline structure seam under load?
7. **Grounding-safety under `drive=both`:** when the outline is a near-complete blueprint, is the §6.4 block-and-report on an ungrounded demanded point strong enough, or does a near-complete outline pressure compose toward tier-promotion? Attack the boundary.
