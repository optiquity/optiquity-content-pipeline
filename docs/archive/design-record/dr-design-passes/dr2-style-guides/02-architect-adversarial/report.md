# DR-2 (style guides) × DR-3 (outline) — Architect ADVERSARIAL critique

**Pass:** COMBINED design, stage 02, mode ADVERSARIAL (initial → **adversarial** → reconciliation, maintainer-gated).
**Class:** read-only. No repo edits. This is an attack on the stage-01 INITIAL design — not a plan, not code.
**Target:** `01-architect-initial/report.md`. **Verified against** the live SSOT `docs/design.md` (§2.1, §5, §6.4/§6.5, §7.1/§7.2/§7.3/§7.4, §11.4, §12.1–§12.7, §14.2, §15, §16, §17, §18, §19, §21.4/§21.5/§21.8, §27.3), the live schemas (`voices/`, `formats/`, `goals/`, `recipes/`, `platforms/`, `presentations/`, `output-types/`), `docs/known-issues.md` (DR-2/DR-3, GAP-4), and the stage-0 research report — all read directly this pass.

**Verdict in one line.** The DR-2 *firewall* (Part A.1–A.3) and the DR-2(d) *no-parametric-Format* ruling (Part D) largely survive and are the strongest parts of the initial. But the load-bearing claims — "two orthogonal planes," "zero new identity surface," "the §6.4 block enforces grounding-safety," "BO2 carries over unchanged," "reuse §15 parts," "one required carrier + one thin overlay" — do **not** survive scrutiny. Two are outright **mis-citations of the SSOT** (the §6.4 grounding-safety enforcement, and the "zero new identity surface" claim vs the closed §7.2 preimage). The precedence model fails on a concrete run/recipe-level structural conflict. Details below, severity-tagged, each with the question reconciliation must answer.

---

## BLOCKERS

### B1 — Grounding-safety under `drive=both` is enforced by a section that does not do what the initial says (§6.4 mis-citation)

**Claim attacked.** C.5 / open-q 7: *"An outline that demands a claim with no EXTRACTED grounding triggers the existing §6.4 block-and-report … the outline never forces a fabricated or tier-promoted claim into published output."*

**Evidence it is wrong.** Read §6.4 literally: *"Empty pool → block and report (SM1). When a `require`/`span` clause — or an empty/missing source pool — leaves an item with no usable grounding: that item blocks."* §6.4 fires on an **empty pool** at **ground-time** (stage 1, §2.1) — before the outline is even consulted. It says nothing about a *specific demanded point* lacking a fact. If the topic grounds *at all* (pool non-empty) but the outline demands section-7's claim for which no EXTRACTED fact exists, **§6.4 never fires** — the pool is not empty. The outline is consumed at **compose** (stage 3), long after §6.4's gate has passed. There is **no compose-time "outline demanded X, no fact for X → block"** anywhere in the design.

The *actual* backstops are: the §15 substance floor (shape only — "≥1 visible letter/digit", explicitly *"never a quality judgment"*), the §6.5 EXTRACTED publish floor (governs which grounded facts publish, applied at ground/reconcile — not a check that compose covered every outline point from EXTRACTED facts), and **Review 1 (§19)** — a *soft, advisory* content review that runs *after* compose has already produced the (possibly fabricated) IR. So under `drive=both` a near-complete outline that demands ungrounded points is caught, if at all, by an advisory post-hoc review — exactly the tier-promotion pressure the target flagged, and the opposite of the *hard block-and-report* the initial promises.

**Severity: blocker.** The maintainer's DR-2(f)/DR-3 grounding invariant is *asserted* (C.5) but the cited enforcement is fictional.

**Question reconciliation must answer.** Where is the *real* compose-time enforcement that an outline point with no EXTRACTED grounding cannot ship as fact? Either (a) name it honestly (compose leaves it an INFERRED/AMBIGUOUS lead + Review 1 advisory, and accept that `drive=both` weakens to advisory), or (b) design a genuine hard gate ("outline point references no EXTRACTED fact → `block`/`needs-input`"), which is *new machinery*, not "the existing §6.4."

---

### B2 — The precedence model fails on a real conflict: the outline DOES top the cascade for the `format.parts` attribute

**Claim attacked.** C.1: the outline *"outranks the dimensions **not by sitting atop the value cascade**"*; C.2 shows the content plane as, unconditionally, *"outline STRUCTURE > Format skeleton (for drive=structure|both)."* C.3.1 explicitly says the outline may **override Format's `parts`**.

**Evidence it collides.** `format.parts` is not free-prose skeleton — it is a **declared, cascade-bound Format attribute** (`formats/_schema.yaml`: `parts`, ordered list). It binds through the M2 spine at L5-recipe / L6-run (§12.3 Format row), enters `artifact-id` via §7.2, and drives real rendering mechanics: `packaging_hint` → the **1-vs-N serialize decision** (§17 RI9) and `part-id` = `(artifact-id, part-id)` addressing (§7.1). A recipe (L5) or run (L6) can bind `format.parts` — a run override on a declared attribute of the selected entry is legal (§21.4 refuses only *entry selection*, schema edits, and `union`-on-ordered-lists; a **replace** on `format.parts` is permitted, §12.4 "list (ordered) → replace").

So construct the case the target demanded: recipe binds `format.parts = [slides, notes]` (or a run does at L6, the most-local rung); the outline drives `structure` with a different sectioning. The initial's content plane says **outline wins** (C.3.1). But `format.parts` was set at L5/L6 — the top of the value cascade, an explicit user act. The outline beating it **is** the outline sitting atop the cascade for that attribute — a flat contradiction of C.1, and of §3.1 (never bend the user's explicit config without a warning) and §12.5 most-local-wins. The "two planes never touch the same rungs" story is exactly what breaks: `format.parts` lives on *both* the value plane (cascade-bound, in `artifact-id`) and the content plane (structure the outline claims to own).

**Severity: blocker.** The single load-bearing DR-3 constraint — "outline outranks dimensions **without breaking orthogonality**" — does not survive its first genuine collision with a cascade-bound structural attribute.

**Question reconciliation must answer.** When `format.parts` is bound at L5/L6 *and* an outline drives structure, which wins, and by what rule? If the outline wins, (a) that IS topping the cascade — restate C.1 honestly; and (b) where is the §3.1 warning for silently overriding an explicit L6 structural act? If the recipe/run wins, then the outline does **not** dominate structure and DR-3's "far more influence than any dimension input" fails. There is no third option in the current model.

---

## SHOULD-FIX

### S1 — "Zero new identity surface" is false for both the lexicon and the outline; and it internally contradicts A.3

**Claim attacked.** A.4 and the cross-cutting checks: the lexicon *"enters `artifact-id` … via the existing §7.2 delta-vs-floor (no lexicon = absent = zero id churn)"*; the outline digest *"joins the `artifact-id` preimage"* with *"Zero new identity surface."*

**Evidence.** §7.2 is a **closed** preimage. Read the canonical form: it is `{ for each SINGLE-valued content dimension D in {topic, persona, format, voice}: (entry-id, delta-map) } + [sorted goal-set pairs] + source-subset + source-commit`. The delta-vs-floor mechanism operates *per dimension attribute*. A **lexicon reference** and an **outline digest** are neither one of the four dimensions' attributes nor the goal-set — so they cannot "enter via existing §7.2 delta-vs-floor." Including either requires **adding a new top-level preimage component**, i.e. new identity surface, and §7 is explicitly *"the single authority for the id family … none redefines them."*

Worse, this is an **internal contradiction**: A.3 spends its whole argument proving the lexicon is *tone-independent* and therefore must **not** be a Voice attribute (*"it would force re-declaration per voice"*). If it is not a Voice attribute, it cannot ride §7.2's Voice delta — so A.3 and A.4 cannot both be true. (The `voice_overrides` map genuinely *does* ride §7.2 — those are real `voice.<attr>` deltas — but the initial lumps the lexicon and outline in with it under the same false "zero new surface" banner.)

Cross-check §27.3: the design carries a **registered caution** — *"Adding the effective M3-expression digest to the preimage would be identity churn and needs strong motivation."* The principle generalises: preimage additions are guarded. The outline/lexicon *may* survive it (they are **absent-by-default**, so existing ids don't churn — a genuine distinction from the M3 case, where every artifact already has an expression), but that must be **argued against §27.3's "strong motivation" bar**, not waved away as "zero new surface."

**Severity: should-fix.** The claim as written is false and self-contradictory; the underlying design may be salvageable but must be re-derived honestly.

**Question reconciliation must answer.** State plainly that the lexicon selection and the outline are **new `artifact-id` preimage components** (new identity surface), and justify each against §27.3 on the absent-by-default / zero-churn ground — or model them so they genuinely don't enter identity (see S6).

---

### S2 — The new M2 cascade rung is a spine change with all-dimension blast radius, minted to serve a "nudge" precedence DR-2 never asked for

**Claim attacked.** A.4 / open-q 2: a *"new low overlay rung positioned below L5-recipe and above L3-workspace"*; open-q 1 treats the overlay as "ergonomic."

**Evidence.** §12.2's spine is a **ratified, deliberately-not-renumbered** ladder — L0,L1,L2,L3,L5,L6 — and §12.3 states *"Every dimension resolves over the §12.2 spine."* Inserting a 7th rung is not a content-side-local edit; it changes the **uniform fold** every dimension's resolver runs (§12.1 "a fixed bottom-up fold over the §12.2 spine"), and it must be reasoned about for `artifact-id` preimage stability (§7.2), for the mandatory-global set (§12.3), and for the brand-authoritative elevation (§12.6). That is framework-mechanism blast radius touching all nine axes, to carry a payload that A.1 restricts to **voice.\* overrides + a lexicon ref only** — effectively a "voice-override rung."

And the *reason* for making it a **low** rung (below recipe) is imported, not required. DR-2's constraint is: a guide *"nudges a dimension's direction; it does not replace it … overrides, not redefinitions."* That is precisely the **override-vs-redeclare** wall — M2 value-binding vs M1 entry-selection — already machine-enforced at §21.4 (API5), and the initial correctly identifies this in A.2. "Nudge" in DR-2 means *bind a value on the already-selected entry, never pick the entry.* It does **not** mean "lose to the recipe." The initial silently promotes a second, unrequested sense of "nudge" (low cascade precedence) and builds a whole spine rung for it.

**Severity: should-fix.**

**Question reconciliation must answer.** Is a *new spine rung* required at all, or can a selected style-guide expand into value bindings at an **existing** rung (the injection-at-bind model of §12.5 CA7)? And is "below recipe" a real maintainer requirement or an artifact of conflating the two senses of "nudge"? If the only genuine constraint is override-not-redeclare (§21.4), the rung is unmotivated.

---

### S3 — `authoritative` on the style-guide entry contradicts §12.6 twice: it is an entry declaring its own precedence, and BO2 does not "carry over unchanged"

**Claim attacked.** A.4 / A.0: the guide carries an `authoritative (bool + strength a|b|c)` field *"reusing §12.6"*; brand-lock *"is the ratified BO2 mechanism, generalized … unchanged."*

**Evidence.** Two problems, both from the SSOT and the live schema.

1. **Locus.** §12.6's flag lives on the **scope-default schema** (`instance/defaults.yaml` / `workspaces/<client>/defaults.yaml`), and `voices/_schema.yaml` states this explicitly: *"The §12.6 `authoritative` flag (BO2) lives on the global/workspace Voice SCOPE-DEFAULT schema … deliberately NOT declared here: brand arbitration is a property of the scope-default VALUE, never of a voice entry."* The initial puts `authoritative` **on the `style-guides/` entry**. A registry entry carrying its own precedence-elevation flag means the entry can promote **itself** from below-recipe to just-below-run — an entry declaring its own rung, which no dimension entry may do (rung position is structural, not an entry property).

2. **"Unchanged" is false.** §12.6 restricts the flag to **Voice-only in v1** for stated reasons: *"persona/goal/platform brand-locks are category errors; an open bundle would straddle the compose/render identity split."* A style guide is, by A.0's own description, a **bundle** (voice_overrides + lexicon ref + guidelines_overlay). Making a *bundle* authoritative is the exact shape §12.6 refused. The initial asserts it "carries over unchanged" without rebutting the bundle-straddle reasoning.

**Severity: should-fix.**

**Question reconciliation must answer.** If brand-lock is wanted for a guide, does the `authoritative` value live on a **scope default** (honoring §12.6's locus) that references the guide, rather than on the guide entry? And does elevating a *bundle* (lexicon + guidelines, not just voice) reintroduce the straddle §12.6 named — or is a content-only bundle genuinely exempt (argue it, don't assert it)?

---

### S4 — Lexicon preservation at reconcile is asserted on a rail (§16 fidelity) that does not carry it

**Claim attacked.** A.4: the lexicon is *"preserved at reconcile (§16 fidelity constraint (i) already requires the LLM rewrite to preserve content parameters — the lexicon rides that rail; no new reconcile identity surface)."*

**Evidence.** §16's fidelity constraint (i) preserves *"voice and content parameters."* The lexicon (banned/preferred terms, product-name casing, US/UK spelling, Oxford comma) is applied at **compose** (the writer honors it, per A.4). Reconcile is an **LLM rewrite toward platform limits** that *"can alter length"* and reshapes leaves — precisely the step most likely to re-word a banned term back in or drop a casing rule while shortening. Nothing in §16 *enumerates* the lexicon as a preserved parameter, and the **reconcile-inputs preimage** (§16) deliberately lists only strategy, hard limits, advisory constraints, and other *reconcile-consumed rendering* attributes — the lexicon is a **compose-side content input**, not in that set. So there is neither a preservation guarantee nor a re-application mechanism; the reconcile agent's contract (§27.4) would have to be *extended* to honor it. "Rides that rail" overstates a rail that isn't there.

**Severity: should-fix.**

**Question reconciliation must answer.** Is the lexicon added to §16's fidelity-preserve list (a §16 change), or to the reconcile-inputs preimage (making a lexicon change a fit-input change → `render-input-mismatch` + force-re-reconcile)? Pick one; both are §16 edits, neither is free.

---

### S5 — "Reuse §15 RI2's part shape for the outline-IR" is a false economy: `role` and `part-id` semantics don't transfer, and the coupling bites at serialize

**Claim attacked.** B.3 / open-q 4: *"the IR is already an ordered `parts` list … an outline is that same shape, pre-compose … not a new data model."* Rendering it is *"the existing serialize pass (§17)."*

**Evidence.** §15 RI2's part is `{part-id, role, constraints?, packaging_hint, body}` where **`role` is the Format-declared part name** and **`part-id = (artifact-id, part-id)` — "stable, reproducible, IR-resident."** §7.4 constrains the part-role slug to `[a-z0-9-]` and §17 RI8 maps a part → a `Div` with `class = role` (the Format role) and `id = part-id`. The outline's sections are **arbitrary user headings with per-section intents**, not Format-declared roles and not slug-safe. So:

- The outline-IR's sections cannot be RI2 `role`s without inventing a different role semantics (free user heading vs Format-declared part). 
- `part-id = (artifact-id, part-id)` is circular for the *input* mode: the driven `artifact-id` (per the initial, S1/S6) depends on the outline digest, which is computed over an outline-IR whose part-ids would need that artifact-id.
- Rendering the outline through §17 "for free" only works if the outline-**output** collapses to a **single flat body** (§15: "Single-part formats collapse to a flat body") — a rendered bulleted plan. That is fine for OUTPUT. But the INPUT mode needs *structured, identity-bearing sections with intents* — which is exactly **not** the flat body and **not** RI2's Format-role parts. The initial's "same shape" conflates the two modes.

**Severity: should-fix.**

**Question reconciliation must answer.** Define the outline-IR's **own** shape — its section identity (not `(artifact-id, part-id)`), its heading semantics (not Format `role`), and how per-section `intent` is carried — rather than claiming RI2 reuse. Then re-verify serialize (output = flat body is fine; structured render needs its own mapping) and reconcile.

---

### S6 — "outline-id" is presented as free reuse of `fetch-by-id`, but there is no `o-` root in the ratified §7.4 id grammar; the outline's identity model is muddled

**Claim attacked.** B.3: the outline-IR is *"persisted and id-addressable (an `outline-id`) via the existing `fetch-by-id` retrieval (§21.5)."* Separately, its digest *"joins the `artifact-id` preimage."*

**Evidence.** §7.4 is the **ratified, closed** id grammar (D2, ratified B4-1). Its family roots are exactly `a-` (artifact), `f-` (folio), `r-` (run); level is inferred positionally from that grammar. There is **no `o-`/outline root**. `fetch-by-id` (§21.5) "works on any id type" — meaning any member of *that* family. So "outline-id" is either (a) an **ordinary `artifact-id`** (the outline-output *is* an artifact — IR-shaped, renderable through reconcile/serialize), in which case call it that and drop the "outline-id" coinage; or (b) a **new id-family member**, i.e. a change to the ratified §7.4 grammar. The initial wants (a)'s free reuse and (b)'s distinct addressability at once.

This compounds S1/S5: if the outline-output is its own `artifact-id`, and its digest also feeds the *driven* artifact's `artifact-id`, then one editable object participates in **two** artifact identities, and the driven `artifact-id` **transitively depends on another `artifact-id`** — a new identity topology (§7's self-contained preimage becomes a DAG). The cleaner model (see below) is to treat the outline as a content input that either mints a fresh driven `artifact-id` wholesale (RI11's "any content-dimension change → new `artifact-id`, old persists as lineage") or is recorded in a compose-level binding — **not** both an `outline-id` and a preimage component and an IR-binding record.

**Severity: should-fix.**

**Question reconciliation must answer.** Place the outline in the id family explicitly: is the outline-output an ordinary `artifact-id` (no grammar change), and does the driven artifact reference that id or a separate digest? Reconcile the "two identities for one editable object" coupling — pick one home, not three.

---

### S7 — Two new instance-content-bearing registries collide with the open GAP-4 content-guard hole (provenance-leak hazard, unflagged)

**Claim attacked.** Cross-cutting checks: *"`lexicons/` entry = one conforming file ✓ `style-guides/` entry = one conforming file ✓"*; A.4 says corporate guides/lexicons are `provenance: instance`, kept public-clean by *"the CI content-guard."*

**Evidence.** `docs/known-issues.md` GAP-4 (Open): *"a brand-new top-level registry directory is outside the content-guard's known-root whitelist and **passes silently**."* The initial adds **two** brand-new top-level registries (`lexicons/`, `style-guides/`) whose **corporate** entries are `provenance: instance` — precisely the content CLAUDE.md rule 4 forbids in the public repo. Standing up these registries therefore requires tightening `scripts/check-no-content.sh` (the whitelist) *before* they can safely host instance-provenance entries — a **second edit** beyond the entry file, and until it lands, a corporate lexicon/guide could **leak to the public framework silently**. The initial's "the CI content-guard already keeps instance content out" is the opposite of GAP-4's actual status.

**Severity: should-fix.** (Interacts directly with CLAUDE.md rule 4 — the maintainer's hardest boundary.)

**Question reconciliation must answer.** Flag the GAP-4 dependency for the planner: `lexicons/` and `style-guides/` standup is gated on the content-guard known-root fix, and the `x-` namespacing (§11.4) + provenance guard must be verified to cover these roots before any `provenance: instance` entry is authored.

---

### S8 — "Two orthogonal decision planes" is a rhetorical device: Format/Topic/Goals sit in BOTH planes, so the outline competes on the same axes it claims to be orthogonal to

**Claim attacked.** C.1: *"two orthogonal decision planes, not one stacked order"*; C.1 again: the outline *"is not competing for the same rungs as the dimensions; it governs an orthogonal decision and overrides only at the two narrow seams."*

**Evidence.** Format is a **content dimension**: cascade-bound, in `artifact-id`, and it *"shapes the IR's structure (§15)"* (§5.2). Topic and Goals are content dimensions that own subject/focus. The initial then places *structure* and *content-focus* on the "content plane" the outline dominates. So Format/Topic/Goals are **simultaneously** value-plane members (selected via the cascade, in `artifact-id`) **and** the very things the outline overrides on the "content plane." The two planes are not disjoint decision spaces — they **share three dimensions**. C.3's three "conflicts" (outline-vs-Format-skeleton, outline-vs-Format-parts, outline-vs-Topic/Goals) are the admission: the outline is a **targeted, high-precedence override of specific dimension payloads**, which is exactly "competing on the same axes." The "plane" framing does rhetorical work to make a precedence override sound like an orthogonality. (B2 is the sharp corner of this same defect.)

**Severity: should-fix.** The honest framing changes the reconciliation: if the outline is an override of dimension payloads, it must obey — or explicitly, warned-ly, break — the cascade's most-local-wins (§3.1), not be exempted by relabeling.

**Question reconciliation must answer.** Drop or heavily qualify "orthogonal planes." State the outline as a high-precedence override at named seams (Format skeleton, Format `parts`, Topic/Goal emphasis) and specify its interaction with the cascade rung that *also* binds those attributes (per B2).

---

### S9 — The leaner "lexicon-only" build is stronger than the initial admits: a recipe is NOT topic-bound, so it already IS the "named, selectable, reusable writing overlay"

**Claim attacked.** A.0 / open-q 1: the overlay is justified because *"recipes are per-artifact (topic-bound, not cross-topic)."*

**Evidence (schema-level).** `recipes/_schema.yaml`, `topic` attribute: `type: text, default: ""`, with the definition *"the honest floor is 'unset — supplied by the workspace/selection/run' … shipped framework recipes leave it unset."* A recipe is **not** topic-bound — it can bind `voice` + `values` (slider tweaks) + (with `lexicons/`) a lexicon ref and leave `topic`, `format`, etc. unset. Combined with `provenance: framework|instance` (which recipes already carry, §10), a topic-less recipe **already delivers** the maintainer's ask: a **named, selectable, reusable, standard/platform/corporate-flavored writing preset**. The stage-0 research said exactly this (§3.2(1): "the pipeline already has a bundling construct: the recipe").

The *one* thing a recipe cannot do is **layer onto an existing non-recipe selection** (a recipe *is* the selection) or sit **below-recipe** in precedence — which is the same unrequested "below-recipe nudge" precedence attacked in S2. So the honest case for item 2 (`style-guides/`) reduces to: *is layering-a-named-overlay-onto-an-existing-request, below recipe, a real maintainer requirement?* If not, item 2 collapses entirely to **`lexicons/` + a recipe convention**, deleting a registry *and* the S2 spine rung.

**Severity: should-fix.** The initial's own recommended-primary keeps item 2 on a premise (`recipes are topic-bound`) that the schema falsifies.

**Question reconciliation must answer.** Is "layer a named writing overlay onto an arbitrary in-flight request, below recipe precedence" a stated maintainer need, or is "start from a named writing recipe" sufficient? If the latter, ship `lexicons/` only; express named guides as topic-less recipes; drop `style-guides/` and the new rung.

---

## MINOR

### M1 — `guidelines_overlay` "appended to / replacing" voice guidelines violates §12.4
A.4 describes `guidelines_overlay (markdown, appended to / replacing voice guidelines)`. §12.4 is unambiguous: `text`/`markdown` → **"replace wholesale (prose never merges)."** "Appended" is not an available combine mode for prose. Reconciliation: drop "appended to"; the overlay wholesale-replaces `voice.guidelines` at its rung (which weakens the overlay's value — you lose the underlying voice guidelines, not augment them — a point that further pressures S2/S9).

### M2 — Reusing the retired L4 label undermines §12.2's stated citation-stability rationale
A.4 offers "the vacated L4 label" for the new rung. §12.2 retired L4 (the folio rung) and *"deliberately did not renumber remaining rungs so rung citations stay stable."* Reusing `L4` for a new meaning re-collides the very label the design froze for stability (every historical `L4` meant folio). The initial hedges ("the exact number is a planner detail") — fine, but do not reuse `L4`.

### M3 — The three-way `drive` cut hides an ordered-content mode; order is a facet both `structure` and `content` share
`drive ∈ {structure, content, both}` forces an either/or on an outline that is *inherently ordered* (B.3: "an ordered list of sections"). `structure` fixes headings/roles but discards intents; `content` keeps intents but lets Format reorder (discarding the authored order). A user wanting "cover these points **in this order**, but restructure headings freely" has no mode — a real fourth cut (ordered-content). Reconciliation: either justify the 3-cut or acknowledge **order** as an orthogonal facet the flag must address.

### M4 — Outline necessity rests solely on the editable-intermediate requirement; "per-artifact specificity" is a weaker, partly-redundant second justification
Part B concedes Format owns per-type structure and Topic+Goals+Persona own focus (B.1), so the outline's necessity is **entirely** the maintainer's explicit *editable dual output+input intermediate* — which no axis provides (axes are inputs, never editable intermediates). That survives (see below). But B.2 also leans on "per-artifact specificity," which a sufficiently precise topic-less recipe + run overrides + a detailed Topic `why` can substantially deliver. Bounding the outline's justification to the editable-plan need keeps its scope minimal and blocks scope-creep into a "specificity engine."

### M5 — The plan stage is under-described as "the IR's own skeleton"
B.3 frames the plan stage as "the IR skeleton, pre-compose," but it is a **new LLM step** (drafting the outline-IR from selections), a **third human gate** (pre-compose edit — §19 ratifies exactly *two* reviews, both post-compose), and **new persistence + identity**. The honest cost matters for the planner; §19's "two gates" framing is not reconciled.

---

## What survived the attack (honest concessions)

1. **The DR-2 orthogonality firewall (A.1–A.3) is sound.** The banned-in-guide table maps correctly to the axes (tone→Voice §5.2, limits→Platform §12.7, typography→Presentation PD3, skeleton→Format/outline, serialization→Output-type, routing→recipe/run CA8). The Voice-vs-lexicon line (A.3: "does the rule change if you pick a different voice?" → Voice; "does it hold across every voice?" → lexicon) is a genuinely useful, correct test, verified against the live `voices/clear-explainer.md` banned-words case. I could not break the firewall itself — only the identity (S1), reconcile-preservation (S4), and standup (S7) claims built around the lexicon.

2. **The override-vs-redeclare wall (A.2) is correctly grounded.** §21.4 (API5) is exactly the M1/M2 boundary the initial cites; a guide binding `voice.formality: 4` is a legal M2 override and "use voice `business`" is a forbidden M1 selection. This part is verified and correct.

3. **`voice_overrides` genuinely ride §7.2** (unlike the lexicon/outline). Those are real `voice.<attr>` deltas; delta-vs-floor covers them with zero churn. The initial was right here — it just over-extended the same claim to constructs §7.2 does not cover.

4. **DR-2(d) — no parametric Format skeleton (Part D) — holds.** Verified against `formats/_schema.yaml` (rhetorical body + the single ordered `parts` list) and the research (§4: guides ship rules, not skeletons). A slot-per-artifact Format would smuggle per-artifact data into a reusable genre entry (the §5.4 one-file/reusability rule) and duplicate the outline as a third structure representation. The two-mechanism split (Format = per-genre, outline = per-artifact) is the right call. *Caveat:* this survives *only if* the outline's structure/identity model is fixed per S5/S6 — a broken outline-IR would reopen it.

5. **Outline necessity (Part B) is genuinely established** — narrowly, on the editable-intermediate requirement (M4). Precise goals cannot substitute because goals are reusable set-valued outcome-types (`goals/_schema.yaml`: only `kind` + `source_selection` — no content-plan field), and adding one would be registry explosion / one-file-add abuse. Verified against the live schema. I could not kill necessity; I only bounded its justification.

6. **The default-path-unchanged / no-op-skip posture** (outline absent → byte-unchanged, mirroring §16's no-op reconcile) is a correct and cheap discipline, consistent with the design's existing skip paths.

---

## The two questions that matter most for reconciliation

- **Precedence (B2 + S8):** Give a single, total rule for what happens when a cascade-bound structural attribute (`format.parts`, and Format skeleton via L5/L6) conflicts with an outline that drives structure — including the §3.1 warning when the outline overrides an explicit user rung. "Two orthogonal planes" is not that rule.
- **Identity + safety (B1 + S1 + S6):** Commit to ONE identity home for the outline and the lexicon (new preimage component, justified against §27.3 on absent-by-default; or a compose-level binding), place the outline-output in the §7.4 id family explicitly, and name the *real* compose-time grounding enforcement (not §6.4). The initial's "zero new identity surface" + "§6.4 blocks it" pairing is the design's weakest seam and cannot ship as written.
