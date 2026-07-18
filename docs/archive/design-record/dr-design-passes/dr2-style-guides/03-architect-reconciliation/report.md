# DR-2 (style guides) × DR-3 (outline) — Architect RECONCILIATION

**Pass:** COMBINED design, stage 03, mode RECONCILIATION (initial → adversarial → **reconciliation**, maintainer-gated).
**Class:** read-only. No repo edits. This is the reconciled design recommendation — **not** an implementation plan and **not** code. The planner is a later stage, after the maintainer gate.
**Adjudicated against the live SSOT** `docs/design.md` (§3.1, §5.2, §6.4/§6.5, §7.1/§7.2/§7.3/§7.4, §12.1–§12.7, §15/RI2, §16, §17/RI8/RI9, §19, §21.4/§21.5, §27.3), the live schemas `formats/_schema.yaml` (`parts`) and `recipes/_schema.yaml` (`topic` optional), and `docs/known-issues.md` (DR-2, DR-3, GAP-4) — every disputed section re-read directly this pass. Where the adversary and the initial disagree, I ruled on the SSOT text, not on either report; the adversary is corrected where it overreached (B1, S1-alternative, S8-framing).

---

## 1. Reconciled executive verdict

The initial's **DR-2 orthogonality firewall (A.1–A.3)**, the **override-vs-redeclare wall (A.2 / §21.4 API5)**, the **DR-2(d) no-parametric-Format ruling (Part D)**, and **outline necessity on the editable-intermediate ground (Part B)** all survive verification and are the sound core. Everything the adversary attacked as load-bearing failed against the SSOT and is **reconciled by simplifying the initial**, not by defending it:

1. **`style-guides/` (initial item 2) is DROPPED.** A recipe is not topic-bound (`recipes/_schema.yaml`: `topic` is `text, default: ""`, "shipped framework recipes leave it unset"), so a **topic-less recipe already IS the named, selectable, reusable writing overlay** the maintainer asked for. Item 2 met no real requirement a topic-less recipe cannot. This deletes a registry **and** the new M2 rung.
2. **The new M2 "overlay rung" (S2) is DROPPED with it.** DR-2's "nudge" means *override-vs-redeclare* (§21.4), which is already machine-enforced — it never meant "lose to the recipe." No 7th spine rung is minted.
3. **The one genuine gap survives: `lexicons/`** (class (ii): terminology / banned+preferred terms / proper-name casing / spelling / house mechanical rules) — the only homeless element. Selected by a content-side `lexicon` ref resolved over the existing selection cascade (default none).
4. **The outline (DR-3) survives**, narrowly, on the editable-intermediate ground only — but its identity, shape, grounding, and precedence claims are all re-derived honestly: it has its **own** shape (not §15/RI2's parts), its **own** digest home (no new §7.4 id root), a **new absent-by-default `artifact-id` component** (not "zero new surface"), and it **never touches `format.parts`** (the B2 fix).
5. **"Zero new identity surface" is retracted.** The lexicon ref and the outline digest are **two new `artifact-id` preimage components**, honestly justified against §27.3 on the absent-by-default / zero-churn ground.
6. **Brand-lock stays on the scope-default VALUE (§12.6), Voice-only in v1** — never on an entry. A corporate guide = a `provenance: instance` topic-less recipe (the preset) + `authoritative` Voice scope-defaults (the lock).

Net: **one required new carrier (`lexicons/`), the outline stage, zero new registries beyond that, zero new cascade rungs, two honest new identity components, two flagged one-line §16/§12.6 changes.** Simpler than the initial by one registry and one spine rung.

**External research:** not required; the internal model and the stage-0 research are sufficient.

---

## 2. The two blockers — one total rule each

### B2 — precedence: partition Format's structure; the outline is a cascade NON-participant

**Verified collision.** `format.parts` is a **declared, cascade-bound Format attribute** (`formats/_schema.yaml`: `parts`, `type: list element: text`); it binds at M2-compose and enters `artifact-id` (§12.3 Format row + §7.2's `format` loop); §12.4 makes an ordered list **replace** (union is a schema error); §21.4 API5 permits a **replace** on a declared attribute of the selected entry, so a recipe (L5) or run (L6) **can** bind `format.parts = [slides, notes]`; and `packaging_hint` per part drives the §17/RI9 one-vs-N serialize decision plus §7.1 `(artifact-id, part-id)` addressing. The initial's C.3.1 has the outline **override `parts`** — which, when `parts` was set at L5/L6, is the outline topping the cascade for an explicit user act, flatly contradicting its own C.1 and §3.1. The adversary is **correct**.

**The error is a category confusion.** Format carries *two* structural surfaces, and only one is a cascade attribute:

| Format structural surface | Is it an M2/cascade attribute? | In `artifact-id`? | Drives serialize fanout / part identity? | Who owns it |
|---|---|---|---|---|
| **Rhetorical body skeleton** (the entry BODY prose — §5.2: "the genre's rhetorical structure is the entry's body prose") | **No** — not declared in `formats/_schema.yaml`; consumed at compose | No | No | reusable **genre default**; the **outline** supplies the per-artifact substitute |
| **`format.parts`** (ordered named sub-outputs) | **Yes** — the one declared Format attribute | **Yes** | **Yes** (RI9 `packaging_hint`; §7.1 `(artifact-id, part-id)`) | the **M2 cascade**, most-local-wins |

**THE TOTAL PRECEDENCE RULE (outline vs. cascade-bound structure):**

> **Cascade-bound structural attributes (`format.parts`, and any future declared structural attribute) are resolved SOLELY by the M2 cascade, most-local-wins (§12.5 / §3.1). The outline is never a rung and never overrides them. The outline governs ONLY non-cascade surfaces: the rhetorical body skeleton (not an attribute) and content emphasis/order within the grounded pool. Because neither surface is an M2 attribute, the outline touches no cascade rung — so "the two planes never contend for the same rung" is now literally true, and §3.1 is never breached because the outline operates on a surface the cascade does not bind.**

This is the honest resolution **(b) — restrict where the outline may override** (the task's option b), and it also makes the outline's structural influence a genuine cascade non-participant (option a). Concretely:

- **`drive=structure`**: the outline replaces the **Format body skeleton** (an entry default; the user's explicit outline beating a *default* is not a §3.1 override — no warning). Within any part declared by `format.parts`, the outline structures **that part's body**. The parts split itself is untouched.
- **The outline NEVER sets or overrides `format.parts`.** Drop the initial's C.3.1 "unless the outline overrides them." A per-artifact parts change is a value-plane M2 binding at L5/L6 that the outline **honors** — parts (outer packaging split, cascade-owned) and outline (inner body structure, compose-owned) compose without contest.
- **DR-3's "outline outranks the dimensions" is reconciled, not asserted over the cascade.** The outline dominates *what/how the artifact is written* — the body skeleton + content plan, which **no cascade rung binds as a value**. It does **not** dominate *how the artifact is packaged into sub-outputs* (`parts`) — a rendering-adjacent attribute that is not "how it is written." This is the orthogonal line DR-3 asked for. The maintainer's lead "place the outline in the M2 cascade" is honestly departed from here, for the stated §3.1 reason: a literal cascade rung atop `parts` is exactly the collision B2 proved fatal.

**Retire the "two orthogonal planes" rhetoric (S8).** Replace it with the precise statement above: the outline is a **high-precedence compose seed operating entirely off the cascade** (on the non-attribute body skeleton + content emphasis/order), yielding to every cascade-bound attribute.

### B1 — grounding: the real enforcement is tier-immutability (§6.5), not §6.4; the outline opens no new hole

**Verified mis-citation.** §6.4 fires on an **empty/missing pool at ground-time** (stage 1) — "when a `require`/`span` clause — or an empty/missing source pool — leaves an item with no usable grounding." It says nothing about a compose-time (stage 3) outline point lacking a specific fact; if the pool is non-empty, §6.4 never fires. The §15 substance floor is a content-blind SHAPE gate ("≥1 visible letter/digit ... never a quality judgment"). §19 Review 1 is explicitly **SOFT / advisory** ("Review 1 is the SOFT, advisory content/quality review"). So "outline never fabricates, enforced by §6.4" is unenforced as cited. The adversary is **correct on the mis-citation.**

**Where the adversary overreaches, and the honest fix.** The adversary's implied remedy — "design a genuine hard gate (new machinery)" — would be an **unwarranted special case**, because the outline introduces **no fabrication vector the base design does not already have.** The real enforcement already exists and is HARD at the only point it can be:

> **THE TOTAL GROUNDING RULE (outline/lexicon never fabricate):** Confidence tiers are set once, at ground-time, in the per-fact grounding ledger (§15), and are **immutable downstream — tier promotion is impossible anywhere after ground (§6.5: "Reconcile and serialize never promote a tier"; "No ... run, and no override can relax [the EXTRACTED publish floor]").** The outline and the lexicon are **compose-time inputs that assert no facts and carry no ledger** (the outline's per-section `intent` *references* topics/facts as leads; the lexicon renames *phrasing*). Therefore neither can mint an EXTRACTED fact or promote a tier. A demanded-but-ungrounded outline point can only be (a) written as an INFERRED/AMBIGUOUS **lead — never published as fact** — or (b) left uncovered. This is the identical discipline that governs ALL compose; the outline changes nothing about it.**

So the enforcement is named honestly: **§6.5 tier-immutability is the HARD floor** (a claim with no EXTRACTED fact-id *cannot* be published as fact, outline or not); **Review 1 (advisory) + Review 2 (full, §19)** are the residual catch for wholesale invention. The design is **constrained so the hole cannot open**: the outline is *defined* to carry no facts and to be tier-transparent, so `drive=both` grants it no power to promote a tier — the near-complete-blueprint pressure the initial worried about hits an immovable per-fact tier wall.

**The residual — flagged, not papered over.** The base design has **no compose-time hard gate that every published-as-fact sentence cite an EXTRACTED fact-id**; wholesale invention of a fact-id-less claim is caught only by the advisory/full reviews. This is a **pre-existing property of ALL compose**, not an outline defect. If the maintainer wants a harder guarantee, it is a **general grounding-hardening item** ("compose must not emit a fact-claim without an EXTRACTED ledger reference"), applying to every compose path — **not** an outline-specific gate (which would violate "fewer special cases"). Handed to the maintainer gate as such (see §6).

---

## 3. S9 ruling — `style-guides/` (item 2) COLLAPSES; `lexicons/` survives

**Schema-verified.** `recipes/_schema.yaml` declares `topic: {type: text, default: ""}`, definition: *"the honest floor is 'unset — supplied by the workspace/selection/run' ... shipped framework recipes leave it unset."* A recipe is **not** topic-bound as a definition: it can bind `voice` + `values` (slider/guideline tweaks) + `goals` + (with the new `lexicon` slot) a lexicon ref, and leave `topic`/`format` unset. Combined with `provenance: framework|instance` (recipes already carry it), **a topic-less recipe already delivers the maintainer's DR-2 ask**: a named, selectable, reusable, standard/platform/corporate-flavored writing preset, applied by selecting it and supplying the topic.

**The exact requirement item 2 claimed but cannot justify.** The initial kept item 2 on the premise "recipes are topic-bound (not cross-topic)" — **falsified by the schema.** The only capabilities a topic-less recipe genuinely lacks are:
- **Sit below recipe in precedence** — but "below-recipe nudge" was never a maintainer requirement; DR-2's "nudge" = override-vs-redeclare (§21.4). And a genuine *below-recipe baseline* is already expressible as an **L3 workspace-default** (voice values + a lexicon ref that a recipe at L5 beats). No new construct needed.
- **Layer a second named bundle onto an existing content recipe** (two named bundles → one artifact) — which the design deliberately forbids (`recipe → one artifact`) and DR-2 does not ask for. Introducing it would be new composition machinery with real blast radius.

**RULING: DROP `style-guides/` and the new M2 rung. Ship:**

| Need | Mechanism | New surface |
|---|---|---|
| Class (ii) terminology / house mechanical rules (the genuine gap) | **`lexicons/`** — new content-side registry (one-file-add), selected by a `lexicon` ref resolved over the existing selection cascade (L3/L5/L6 selection input, default none) | 1 registry + 1 ref slot |
| Named selectable "style guide" (standard / platform / corporate) | **Topic-less recipe** binding `voice` + `values` + `lexicon` ref; `provenance: framework` (standard/platform) or `instance` (corporate) | **none** (existing recipe) |
| Below-recipe baseline "house style" | **L3 workspace-default** (voice values + lexicon ref) | **none** (existing scope default) |
| Brand LOCK (beats recipe/run) | **§12.6 `authoritative` Voice scope-default** (existing, unchanged); optional flagged lexicon-scope-default extension (see S3) | none in v1 / 1 flag-locus extension if wanted |

`lexicons/` survives because the term-list is genuinely shareable across recipes/voices/formats (multiple corporate guides share one house list — a real reuse case) and must be applied at compose and preserved at reconcile independently; folding it into each recipe's `values` would duplicate it and break one-file-add reuse. This is the smallest carrier for the one homeless element.

---

## 4. Identity home (S1) + brand-lock fix (S3)

### S1 — commit to ONE identity home each; "zero new surface" retracted

**Verified.** §7.2's preimage is closed to `{ for D in {topic,persona,format,voice}: (entry-id, delta-map) } + [sorted goal-set] + source-subset + source-commit`. A **lexicon ref** and an **outline digest** are neither a dimension attribute nor the goal-set, so neither can "ride the existing §7.2 delta-vs-floor." Including either is a **new top-level preimage component = new identity surface** (§7 is "the single authority ... none redefines them"). The initial's "zero new identity surface" is false, and it self-contradicts A.3 (which proves the lexicon is *not* a Voice attribute, hence cannot ride Voice's delta). The adversary is **correct**; its "or model them so they don't enter identity" alternative is **rejected** — idempotency (RI11: any content change → new `artifact-id`; same inputs → no re-compose) *requires* both in the preimage.

**Committed identity homes (one each):**

- **Lexicon → a new, absent-by-default component of the `artifact-id` preimage (§7.2 extension).** The *resolved lexicon entry-id* (not the lexicon's contents) enters the per-artifact hash. It is content-side (compose-time) → `artifact-id`, never `fitted-id`/`deliverable-id`.
- **Outline → a new, absent-by-default component of the `artifact-id` preimage (§7.2 extension): the `outline-digest`.** The outline is persisted as a pre-compose stage-product **addressed by that digest — NOT a new `§7.4` id-family root** (no `o-`; the ratified a-/f-/r- grammar is untouched — this resolves S6). The digest is computed over the outline's **own** shape (see S5), which does not reference the driven `artifact-id`, so there is **no circularity and no DAG-of-artifact-ids**. The IR `binding` (RI4) *records* the `outline-digest` for lineage — a record, not a second identity.

**§27.3 justification (the "strong motivation" bar, met honestly).** §27.3 registers that adding the M3-expression digest to the preimage "would be identity churn and needs strong motivation." The decisive distinction: the M3 expression exists on **every** artifact, so adding it churns **all** existing ids; the lexicon and the outline are **absent by default** (most artifacts have neither), so adding them churns **zero** existing ids — this is exactly the additive-with-zero-churn evolution §7.2 is *designed* to accommodate ("a newly shipped attribute at its default is absent from the map, so no `artifact-id` churns"). Motivation: both genuinely determine published bytes (required for idempotency/cache-correctness). So these are principled §7.2 extensions within its own stated evolution model — **new surface, honestly named, zero churn** — not a redefinition of the id family and not "zero new surface."

### S3 — brand-lock: never on an entry; scope-default VALUE only, Voice-only in v1

**Verified.** §12.6's `authoritative` flag lives on the **global/workspace Voice SCOPE-DEFAULT schema**; `voices/_schema.yaml` states brand arbitration "is a property of the scope-default VALUE, never of a voice entry." §12.6 is **Voice-only in v1** because "an open bundle would straddle the compose/render identity split." The initial put `authoritative` on the (now-dropped) `style-guides/` entry and called it a bundle — twice wrong (an entry declaring its own rung; a bundle re-opening the straddle §12.6 refused). The adversary is **correct**.

**The fix (and the collapse makes it clean):** with item 2 gone, there is no entry to carry `authoritative`, so the entry-self-precedence error cannot arise. Brand-lock decomposes cleanly:

- **The corporate "guide" as a selectable preset** = a `provenance: instance` **topic-less recipe** (voice + values + lexicon ref). A recipe is L5 and is *not* a lock — most-local-wins can beat it. That is correct: a preset is a starting point, not a lock.
- **The actual LOCK** = existing **§12.6 `authoritative` Voice scope-defaults** at L2 (house) / L3 (client), unchanged. This already delivers "the brand voice wins across all persisted, reusable config; only a warned run deviates." No bundle is made authoritative — only the Voice value, exactly as §12.6 ratified.
- **Locking the LEXICON too (if wanted):** a lexicon is **compose-only** (like Voice) — it has **no render side**, so the "open bundle straddles the compose/render split" reasoning that restricted §12.6 to Voice **does not apply to it**. Extending the `authoritative` flag to a **lexicon scope-default** is therefore *category-safe* — but it is still a §12.6 **extension that must be explicitly ratified**, not "carried over unchanged." **v1 default: lock the lexicon by L3 workspace-default convention** (the client's baseline lexicon; a run deviating is the user's warned act); **the §12.6 lexicon extension is flagged for the maintainer gate** (§6) as a bounded, category-safe additive option.

---

## 5. Adjudication of every remaining finding

| # | Finding | Ruling | Reason (SSOT-grounded) |
|---|---|---|---|
| **B2** | Outline tops the cascade for `format.parts` | **ACCEPT** | Verified: `parts` is a declared, cascade-bound, `artifact-id`-entering, RI9-driving attribute bindable at L5/L6. Resolved by the total rule in §2 — outline never touches `parts`. |
| **B1** | §6.4 does not enforce outline grounding-safety | **ACCEPT (mis-citation) / REJECT (new-gate remedy)** | §6.4 fires on empty-pool at ground-time; §19 R1 is advisory — verified. But a new outline-specific hard gate is an unwarranted special case: the outline opens no new vector; §6.5 tier-immutability is the real HARD floor. See §2. |
| **S1** | "Zero new identity surface" false | **ACCEPT (new components) / REJECT (don't-enter-identity)** | §7.2 preimage is closed; lexicon+outline are new components. Idempotency requires them in — so committed as absent-by-default §7.2 extensions, §27.3-justified. See §4. |
| **S2** | New M2 rung = spine change, all-dimension blast radius, unrequested "below-recipe" sense | **ACCEPT** | §12.2 spine is ratified/not-renumbered; §12.3 "every dimension resolves over the spine" → a 7th rung touches all nine axes. DR-2 "nudge" = §21.4 override-vs-redeclare, not precedence. **Rung dropped** with item 2 (S9). |
| **S3** | `authoritative` on entry contradicts §12.6 twice | **ACCEPT** | Verified §12.6 + `voices/_schema.yaml`: flag lives on the scope-default VALUE, Voice-only. Fixed in §4 (no entry flag; scope-default lock; flagged lexicon extension). |
| **S4** | Lexicon preservation "rides §16 fidelity" — rail absent | **ACCEPT** | §16 fidelity (i) preserves "voice and content parameters"; the reconcile-inputs preimage lists strategy/hard-limits/advisory only — the lexicon is a compose-side input, not enumerated. **Fix:** add the applicable lexicon rules to §16's fidelity-preserve set (one §16 edit; binds the reconcile agent contract §27.4). Not free — flagged for planner. The lexicon is already in `artifact-id` (S1), so a lexicon *change* already re-composes; §16 only needs to *preserve* the already-applied rules through the rewrite. |
| **S5** | "Reuse §15 RI2 part shape" is false economy | **ACCEPT** | Verified: RI2 part = `{part-id, role, constraints?, packaging_hint, body}`, `role` = Format-declared name, `part-id = (artifact-id, part-id)` — arbitrary user headings/intents are none of these, and the `(artifact-id, part-id)` circularity bites input mode. **Fix:** the outline has its OWN shape — an ordered list of `{section-key, heading, intent, constraint?}`, section-key a local index/slug, NOT `(artifact-id, part-id)`. Not "the same shape." (Clean digest input for S1.) |
| **S6** | "outline-id" has no `o-` root; identity muddled | **ACCEPT** | §7.4 grammar is closed/ratified (a-/f-/r- only). **Fix (§4):** outline addressed by its `outline-digest` (no grammar change); contributes to exactly ONE identity (the driven `artifact-id`); no `o-` root, no two-identities-one-object, no DAG. |
| **S7** | Two new instance registries collide with GAP-4 content-guard hole | **ACCEPT (reduced to one)** | GAP-4 (Open) verified: "a brand-new top-level registry directory ... passes silently." The collapse leaves **one** new root (`lexicons/`), but its `provenance: instance` corporate entries still need the `check-no-content.sh` known-root fix (per §27.4's deferred guard change) + `x-` namespacing (§11.4) verified **before** any instance entry is authored. Interacts with CLAUDE.md rule 4 — hard dependency, flagged for planner + gate (§6). |
| **S8** | "Two orthogonal planes" is rhetorical; Format/Topic/Goals sit in both | **ACCEPT (reframe) / REJECT (obey-or-warned-break binary)** | Verified: Format is a content dimension, cascade-bound, in `artifact-id`, "shapes the IR's structure." Reframed in §2: drop "planes"; the outline is a compose seed on non-cascade surfaces only. The adversary's binary (obey the cascade OR warned-break it) is a false dichotomy once `parts` is excluded — the outline operates OFF the cascade entirely (third option). |
| **S9** | Leaner lexicon-only build is stronger; recipe not topic-bound | **ACCEPT** | Verified `recipes/_schema.yaml`. **Item 2 collapsed** (§3). |
| **M1** | `guidelines_overlay` "appended to / replacing" violates §12.4 | **ACCEPT** | §12.4: text/markdown → **replace wholesale (prose never merges)**. "Appended" is not a combine mode. Moot under the collapse (guidelines are a `voice.guidelines` value in the recipe's `values`, which replaces wholesale) — but the principle holds: no prose append. |
| **M2** | Reusing retired L4 label undermines §12.2 citation stability | **ACCEPT (moot)** | §12.2 retired L4 and "deliberately did not renumber." With the rung dropped there is no new label; the never-reuse-L4 principle is affirmed. |
| **M3** | Three-way `drive` cut hides an ordered-content mode | **ACCEPT** | An outline is inherently ordered (B.3); `structure` vs `content` forces an either/or that strands "cover these points in this order, restructure headings freely." **Fix:** model `drive` as orthogonal facets — `use-sections?`, `use-order?`, `intents-must-cover?` — not a 3-value enum (fewer special cases). Exact surface = planner. |
| **M4** | Necessity rests on editable-intermediate, not per-artifact specificity | **ACCEPT** | Verified `goals/_schema.yaml` has only `kind` + `source_selection` — no content-plan field; adding one = registry explosion. Bound the outline's justification to the **editable dual output+input intermediate** (no axis is an editable intermediate); drop "specificity engine" scope-creep. |
| **M5** | Plan stage under-described as "the IR's own skeleton" | **ACCEPT (clarified)** | It is a genuine **new pre-compose stage**: a new LLM drafting step + new persistence + a new **human AUTHORING gate** (produce → edit → consume). This does NOT contradict §19's "two REVIEW gates" (those are post-compose quality/publishability reviews; the outline gate is an authoring touchpoint, a different kind) — but it IS a new human step and real cost. Honestly flagged for the planner. |

**Adversary concessions confirmed (survive intact):** the DR-2 firewall (A.1–A.3) incl. the "does the rule change if you pick a different voice?" Voice-vs-lexicon test; the override-vs-redeclare wall (A.2 / §21.4); `voice_overrides` genuinely riding §7.2 (real `voice.<attr>` deltas); Part D (no parametric Format skeleton — verified against `formats/_schema.yaml`, contingent on the outline shape/identity fixes S5/S6, now made); outline necessity (Part B, on the M4 ground); the no-op-skip default-path-unchanged posture.

---

## 6. Residual risks & open questions for the planner and the maintainer gate

**Must reach the maintainer gate (design decisions above the planner's pay grade):**

1. **§7.2 preimage extension (two new absent-by-default components).** Adding the lexicon entry-id and the `outline-digest` to the `artifact-id` preimage is a §7-authority change. It is zero-churn and within §7.2's additive-evolution model, but §7 is "the single authority for the id family" — this needs explicit maintainer ratification, not a planner edit. (§4)
2. **The general grounding-hardening question (from B1).** Does the maintainer want a *compose-time hard gate* that no published-as-fact claim ships without an EXTRACTED ledger reference? If yes, it is a **general** gate on all compose (new machinery, GAP-adjacent), **not** an outline special case. If no, `drive=both` grounding-safety rests on §6.5 tier-immutability (hard) + the two reviews (advisory) — the same posture as all base compose. Decide the posture explicitly. (§2)
3. **§12.6 lexicon-lock extension.** v1 locks a corporate lexicon by L3 convention. Extending `authoritative` to a lexicon scope-default is category-safe (compose-only, no straddle) but is a §12.6 amendment. Ratify or defer. (§4)
4. **Is the outline worth its cost?** It is the heavier of the two features: a new optional pre-compose stage + LLM draft step + human authoring gate + new persistence + a new `artifact-id` component + a §16 fidelity-list touch. Necessity is established only on the editable-intermediate ground (M4). The maintainer should confirm that editable-intermediate need is worth this footprint before the planner builds it. `lexicons/` (DR-2) is cheap and clearly justified; the outline (DR-3) is the one to pressure-test at the gate.

**Planner-facing (mechanism design within the ratified frame):**

5. **GAP-4 hard dependency (S7).** `lexicons/` standup is gated on tightening `scripts/check-no-content.sh` to fail on an unknown registry root, and on verifying `x-` namespacing (§11.4) + the provenance guard cover the `lexicons/` root, **before** any `provenance: instance` lexicon is authored. Sequence this first; CLAUDE.md rule 4 is the maintainer's hardest boundary.
6. **§16 fidelity-list edit (S4).** Add "the applicable lexicon rules" to §16's preserve set and to the reconcile agent's contract (§27.4). Small, but a §16 change with a real reconcile-agent contract implication.
7. **The `lexicon` selection surface.** A lexicon is a **selection** (a ref to an entry), not an M2 value binding — so it resolves through the selection cascade / begin-session selection input (L3/L5/L6), never through `overrides` (§21.4 forbids overrides from picking entries). Confirm this routing; default none (zero churn at the floor, §7.2).
8. **`drive` facet decomposition (M3).** Prefer orthogonal facets (`use-sections?`, `use-order?`, `intents-must-cover?`) over a 3-value enum.
9. **Outline shape spec (S5).** Define the outline's own shape `{section-key, heading, intent, constraint?}` and its digest canonicalization; do not reuse RI2. Re-verify serialize (rendering the plan as a human-readable OUTPUT is a derived view, not a distinct `artifact-id` in v1).
10. **Deferred per-part override × outline (§27.3 T7).** When the deferred per-part override layer (§26) lands, its interaction with the outline (outline shapes body-within-part; per-part override binds part attributes — likely orthogonal) must be designed. Register it; it does not block v1.

---

*End of reconciliation. This report resolves B1 and B2 with one total rule each, collapses `style-guides/` and the new rung, commits one identity home per construct, and fixes brand-lock to honor §12.6 — simplifying the initial by one registry and one spine rung. No code, no implementation plan; the planner runs after the maintainer gate.*
