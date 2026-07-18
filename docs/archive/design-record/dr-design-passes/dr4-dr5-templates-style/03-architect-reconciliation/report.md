# DR-4 (content templates) × DR-5 (compose-vs-render style) + style-file / compatibility / CSS — Architect RECONCILIATION

**Pass:** COMBINED, maintainer-directed. Stage 03, mode **RECONCILIATION** (initial → adversarial → **reconciliation**, maintainer-gated). **Class:** read-only. No repo edits, no commit. Reconciled design recommendation only — **no code, no implementation plan** (the planner runs after the maintainer gate).

**Adjudicated this pass against the LIVE SSOT + CODE, not the reports** (the adversary can overreach too, so both prior reports were re-verified against source):
`docs/design.md` §5.2 (Format owns the rhetorical structure; `parts` = named intra-genre sub-outputs), §5.3 (Presentation PD1–PD8), §6.5 (EXTRACTED floor; every published claim's grounding recorded in the ledger + re-checked §19), §9.5 (composite `parts` addressed `(artifact-id, part-id)`; `packaging_hint` drives RI9 fanout), §12.3 (Platform per-format **advisory** projection merges below L5; hard limits never enter M2), §15 RI2 (`constraints?` = per-part attribute VALUES, override deferred §26), §16 (reconcile fidelity i/ii/iii; the TERMINAL gate is fit-or-block on hard **LIMITS** = numeric/capacity), §17 (RI7/RI8/RI9/RI12–RI14, provenance-strip, serialize-inputs preimage), §19 (Review 1 platform-neutral; the §15 substance floor is the HARD shape gate), §26 (**T7 open** — per-part override cascade placement, IR carries per-part `constraints`), §27.3/§27.4;
live code `pipeline/ir.py` (`TOP_LEVEL_KEYS` closed set, `_PART_OPTIONAL=("constraints",)`, `part["constraints"]` typed `Mapping` "per-part values; interpretation deferred, §26" at :615-619, `_validate_binding` closed `{artifact_id, preimage, digest}`), `pipeline/presentation.py` (`lower` pure; `--variable` flags emit UNCONDITIONALLY per writer at :234-237; `CSS_WRITERS`/`REFERENCE_DOC_WRITERS`/`NO_TEMPLATE_WRITERS`/`PDF_OUTPUT_TYPES`; `delta_vs_floor`), `pipeline/dispatch.py` (`capability_check` at the dispatch layer keyed on `side`+writer; `strip_provenance(ast)` runs at :194 BEFORE the writer; external branch returns only `payload_ast`), `pipeline/filters/provenance_strip.py` (`should_strip` pure fn of writer; `_walk_strip` Attr-only rewrite over blocks+meta; `SAFE_WRITERS`; docstring invariant "nothing published needs a `data-` attribute");
prior RATIFIED reconciliations held fixed: **DR-2** = `lexicons/` at compose + topic-less recipe; **DR-3** = C3 Markdown-canonical outline (holistic, **no machine section-parse in v1**, `constraint?` deferred, multi-part deferred, `outline-digest` in the preimage); the DR-2×DR-3 **B2 total rule** (the outline governs the body skeleton; the cascade owns `parts`).

---

## 1. Reconciled executive verdict

**The initial's central positioning is OVERTURNED.** The initial framed this as an "overwhelmingly REUSE pass, zero new footprint, homes the driving example on enriched `format.parts`." The adversary proved that false, and re-verification confirms the adversary: **serving the shared driving example — one academic paper, three journals, from one IR — is NOT a reuse job. It requires BUILDING the machine-section-parse that DR-3 deliberately deferred.** R4 (the initial's DON'T-OVERDESIGN worry) was inverted: the v1 design is **under-built, not over-built.** The honest verdict is a **mixed pass** — a genuinely small, clean REUSE core (DR-5 look, `csl` lever, compose-baked lexicon, the existing style-file reference) sitting beside **one real build decision** (the typed-section model) that the maintainer must consciously authorize.

The **strongest result survives and is kept**: across the whole pass there is **no NEW top-level `artifact-id` preimage COMPONENT** — a real, verified win (a deliberate contrast with DR-2 and DR-3, which each added one). It holds even under the bigger option below, because the section model rides DR-3's *already-paid* `outline-digest` and the Format delta; `references` is body-blind; `csl` rides the existing `presentation` coordinate. **But "no new identity component" is NOT "no machinery"** — the initial conflated the two. The `references` block edits the closed IR envelope and threads into AST-`meta`; the section model builds a sentinel grammar; citeproc adds a serialize step. Those are separable from identity, and they are real (SF-2).

The reconciled shape:
- **DR-4 templates** = a **typed-section conformance model on the body-skeleton surface** (§5.2/DR-3's domain), **NOT** on `format.parts`, **NOT** on the reserved IR `constraints?` field. It unifies with DR-3: the outline IS the section skeleton; DR-4 is the typed constraint envelope over it. This is **option (b)** and it is what serves the paper (§2).
- **DR-5 look** → Presentation @ serialize (kept, no work). **citations** → a `references` block + `[@key]` in the IR (real machinery, SF-2) coupled to the grounding ledger (SF-3), with **content-driven citeproc enablement** (SF-4) and a per-venue `csl` style lever (kept). **inline mechanics** → compose-baked lexicon, labeled compose-only (kept).
- **Part C** → the style-file reference already exists (kept, do not reinvent); the compatibility check moves to the **dispatch layer** with a **sound signal** and **pinned warn-vs-error semantics** (SF-6).

**Net:** one real build (the typed-section grammar, un-deferring DR-3's F1), plus a small additive citation path with named machinery and a grounding-coupling ruling, plus a small dispatch-layer compatibility check — all riding existing identity coordinates. This is honest about cost and honest about the driving example.

---

## 2. BLK-1 — the parts/body/outline/typed-slots fault line (THE central decision)

### 2.1 The fault, re-verified (the adversary is right on all three counts)

1. **`parts` are packaging sub-outputs, not rhetorical sections — verified.** §5.2: Format "owns the rhetorical structure/genre; it **shapes the IR's structure**," and `parts` is "an ordered list of named **intra-genre sub-outputs** (`slide-deck → [slides, presenter-notes]`)." §9.5: composite parts are "addressed `(artifact-id, part-id)`, stable, living in the IR," with `packaging_hint ∈ {in-document, standalone}` driving RI9 one-file-vs-N fanout (`ir.py` validates each `part-id = part_id(artifact_id, role)`). An academic paper's abstract/methods/results are the **rhetorical structure of one flowing body** — §5.2 assigns that to the entry's **body prose**, not to `parts`. Homing paper sections on `parts` makes each section a `standalone`-eligible independently-addressable output: a category error.
2. **It reverses the ratified DR-3 B2 rule — verified.** B2's TOTAL PRECEDENCE RULE: "Cascade-bound structural attributes (`format.parts`…) are resolved SOLELY by the M2 cascade… The outline is never a rung and never overrides them. The outline governs ONLY … the rhetorical body skeleton (not an attribute)." Putting paper sections + per-section constraints on cascade-bound `parts` makes section structure cascade-owned, so the outline can never drive it — flatly reversing B2.
3. **The IR `parts` XOR `body` makes outline-driven + typed-template mutually exclusive — verified.** `ir.py` `TOP_LEVEL_KEYS` + `validate_ir` enforce `parts` XOR `body`; DR-3 C3 restricts v1 outlines to single-part flat-body; the initial itself calls typed slots "inherently multi-part." So an artifact is EITHER outline-driven flat-body OR typed multi-part `parts`, never both — and the paper needs both.

The initial's own Integration notes #1–#3 concede the intersection is deferred, while the executive verdict claims the example is homed. That is the "(a)-but-claim-(b)" the adversary named. It cannot stand.

### 2.2 The resolution: a THIRD option, which is a scoped (b) — **RECOMMENDED**

The a/b framing is a real fork, but the honest resolution is a **precisely-scoped (b)** that unifies DR-3 and DR-4 on the one surface they share. Lead insight, and the thing both prior passes missed:

> **The academic paper is a SINGLE-PART, FLAT-BODY artifact whose sections live in the body (§5.2). Its section STRUCTURE is the DR-3 outline. DR-4 is not a second structural surface — it is the TYPED CONSTRAINT ENVELOPE over the outline's sections. DR-3 and DR-4 are two aspects of ONE object: the editable, typed, constrained section plan of a flat-body artifact.**

Under this unification the three faults dissolve by construction:
- DR-4 **never touches `format.parts`** (no packaging surface, no `(artifact-id, part-id)`, no RI9 fanout) — fault #1 gone.
- The **outline governs the section skeleton** (DR-3 B2 preserved); DR-4 constraints are a **conformance schema** the skeleton must satisfy, not a cascade attribute that outranks it — fault #2 gone.
- The paper stays **single-part flat-body** — no XOR collision — fault #3 gone.

**The mechanism (design-level, not planner-level):**
- **Section STRUCTURE (which sections, order, what each covers)** = the body skeleton = **outline-governed (DR-3)**, refinable per-artifact. Not cascade-bound.
- **Section CONSTRAINTS (required / optional / forbidden section; ordered; min/max length/count; section kind incl. a whole-section non-text kind)** = a **conformance schema**, declared on **Format** (the base genre's section spec) and **tightened per-venue by Platform** (the DITA constraint-module analog: make optional→required, forbid, tighten a bound). The outline is the instance; the DR-4 schema is the contract; conformance is CHECKED (not merged into the cascade).
- Constraints attach to the outline's Markdown sections via the **F1 sentinel grammar DR-3 already registered as a forward requirement** (§07 F1: "boundaries drawn only from sentinel lines content cannot forge," plus "a **structural** fidelity check above any byte check"). DR-4 does not invent a new hard problem — it **builds the one DR-3 already spec'd** and supplies the motivation to build it now.

**Honest scope cut (holds the DON'T-OVERDESIGN line at the right boundary):** v1 serves **WHOLE-SECTION conformance** (required/forbidden/ordered sections, per-section numeric limits, whole-section kinds). It **DEFERS the nested-in-prose typed slot** (a figure-with-caption or a table-with-columns embedded *inside* a section's running body). The driving example's "required/forbidden sections, structured methods section, abstract ≤N words" is served by whole-section conformance; the fine-grained "every embedded figure has a caption" is the deferred nested tier (BLK-1's own tell, Integration #3). The distinction is crisp: **typing a whole section (v1) vs typing a slot inside a section's prose (deferred).**

**Why (b)-scoped over (a):** the maintainer commissioned DR-3 + DR-4 + DR-5 **together** precisely for the three-journals-one-paper case. Option (a) — DR-4 ships only a standalone typed table-part sibling to slides/notes — delivers a capability the paper cannot use (BLK-1: "NOT what an academic paper is"), and leaves SF-1 (hard per-venue section requirements) unsolved. The prompt's own steer is explicit: under-scoping fails the driving example. Option (b)-scoped is the **minimum that serves it**, and it un-defers exactly one already-scoped feature rather than inventing a subsystem.

**The honest cost, stated plainly (route to the gate):** option (b)-scoped **un-defers DR-3's machine-section-parse.** DR-3's reconciliation was *relieved* to defer it (it dissolved F1's byte-vs-meaning fault and F3's whitespace/nesting churn by staying holistic). Building the sentinel grammar re-enters those problems — now with F1's ratified escapable-grammar shape and F5's ratified HARD structural gate as the guardrails. This is a **real build**, not a reuse. That is THE decision for the maintainer.

**The (a) fallback, presented fairly:** if the maintainer judges the section-grammar build too large for this pass, ship (a) — whole-part typed sub-outputs only — and **state plainly that the academic paper (typed sections + per-venue section constraints) is NOT served in v1**, deferred *jointly* with DR-3's machine-section-parse. Under (a), the paper still gets: an editable section plan (DR-3 outline, already ratified), abstract ≤N words (Platform hard limit → §16 gate, already built), per-venue look + citation style (DR-5). What (a) does NOT get: the **hard per-venue required/forbidden-section guarantee** (SF-1) and typed section conformance. The a/b decision therefore reduces cleanly to one question:

> **Does the maintainer require a HARD, per-venue structural guarantee ("journal B forbids acknowledgements" must BLOCK), or is an advisory compose-instruction + Review-2 check acceptable?** HARD ⇒ build the grammar (b). Advisory ⇒ (a) suffices and is honest-minimal.

**Recommendation: (b)-scoped.** The driving example needs the hard guarantee (SF-1), and DR-3 §07 F5 already signaled the maintainer's preference for hard structural gates over advisory ("advisory is too weak" for structural residuals). But this is a scope-increase decision above the planner — routed as THE gate item.

---

## 3. BLK-2 and the should-fixes

### BLK-2 — do NOT repurpose the reserved `constraints?` field. ACCEPT.

**Verified:** §15 RI2, §26 T7, and `ir.py:615-619` all pin `constraints?` as a **`Mapping` of per-part attribute VALUES** ("interpretation deferred, §26"), reserved for the **open T7 per-part dimension-value override** ("this part's voice=X"; cascade placement unresolved). DR-4's structural conformance is a **list of typed shape rules** ("this section is required; ≤N words"). Different concept (value-binding vs shape-conformance), different shape (map-of-values vs typed-rule-set). Filling `constraints?` with DR-4 rules overwrites a reserved meaning and forces the still-open T7 to share an occupied field — the dimension/attribute/cascade blur the discipline forbids.

**Fix:** DR-4's section-conformance schema gets its **OWN field/shape** (an envelope-level section-conformance spec on the flat-body IR; planner names it), distinct from `constraints?`. **`constraints?` stays reserved for T7, untouched.** Under the recommended option (b) the collision cannot even arise: the paper is single-part flat-body, so there are **no `parts` and no `constraints?` in play** for it — the DR-4 spec is a new flat-body field. (If the deferred whole-part typed-sub-output capability is ever built, its per-part typed constraints likewise take their own part field, never `constraints?`.) No pre-emption of T7.

### SF-1 — hard, platform-specific, structural enforcement. ACCEPT.

**Verified contradiction:** compose/Review-1 is **platform-neutral** (§19; §15 "IR-canonical is platform-agnostic") — it cannot enforce a per-journal rule. The Platform per-format projection is **advisory** (§12.3 "advisory constraint projection merges below L5"; §16 preimage item 3 = "the effective **advisory** constraint values"). The only HARD reconcile mechanism, the §16 terminal gate, is **fit-or-block on hard LIMITS** (numeric/capacity — "content that cannot be made to **fit**"), not "forbid this section." So "journal B forbids acknowledgements" currently lands on the advisory rail = warn + user-may-deviate. No hard structural home exists.

**Fix (two-point enforcement, both need option (b)'s section grammar):**
1. **Platform-NEUTRAL base conformance** (the genre's own required sections, from Format) → a **new HARD structural gate at compose/Review-1**, a sibling to the §15 substance floor (a content-blind-ish SHAPE gate: are the base-required sections present/ordered?). Checked once per artifact, pre-fanout.
2. **Platform-SPECIFIC conformance** (journal B forbids acknowledgements) → this **cannot** run at platform-neutral compose. It runs at **reconcile**, where platform enters (§16). Give the Platform per-format projection a **new HARD structural class** (alongside its advisory class), consumed by a **new structural gate at reconcile** — a sibling to §16's numeric terminal gate. Reconcile's existing reshape (`adapt`/`split`) can DROP a forbidden section or fail-to-block a missing-and-unsynthesizable required one, exactly matching §16's reshape-then-gate model. This is a real, honest §12.7/§16 extension (a hard structural class + a structural terminal gate), named — not left advisory and called served.

Identity note: the hard structural class rides the **existing** §16 reconcile-inputs preimage (item 3, delta-vs-floor) — no new fitted-id component.

### SF-2 — the `references` block needs REAL machinery. ACCEPT (retract "no machinery").

**Verified at four points:**
1. **Closed IR envelope.** `ir.py` `TOP_LEVEL_KEYS = frozenset({ir_version, pandoc_api_version, binding, grounding, parts, body, metadata})`; `validate_ir` refuses any unknown top-level key. Adding `references` is a **framework code change** + a new CSL-JSON shape validator — the same loud class of change DR-3 made for `outline-digest`, not free.
2. **RI7 parses the leaf, not the envelope.** §17 RI7 is one `pandoc -f markdown -t json` over the fitted Markdown; `references` lives in the envelope. For citeproc to resolve `[@key]`, the block must be **threaded into the AST `meta`** (emitted as leaf frontmatter pre-RI7, or injected post-parse) — new serialize wiring the initial did not name.
3. **New §16 fidelity obligation.** Reconcile (LLM reshape) must preserve the `references` block AND the inline `[@key]` markers through reshape/split/localize (a `split` can shatter a citation; `localize` can mangle `[@key]`). This joins the accumulating fidelity list (§4).
4. **Round-trip parity** for `-f json … --citeproc` at the pinned binary is unproven (a §27.2-style pre-build gate).

The design remains viable; it is **honestly costed**, not "additive, no machinery."

### SF-3 — the citation grounding hole. ACCEPT (leaning blocker); resolve by COUPLING, not orthogonality.

**Verified:** §6.5 is a durable invariant — "Only EXTRACTED-tier facts are published as fact… no override can relax it," and "**Every published claim's grounding … is recorded in the artifact's grounding ledger (§15) and re-checked by the deliverable review (§19).**" The initial's `references` block is published content in **no ledger, no floor, no traceability**. Two real leaks: a **fabricated citation** (an LLM-invented work ships as authoritative), and **claim/citation decoupling** (a citation dressing an INFERRED lead as cited fact while the EXTRACTED floor believes the claim is gated). The initial's "grounding vs citations orthogonal, not blurred" is the hole; **orthogonality here defeats the floor.**

**The honest fix OVERTURNS the initial: citations must be COUPLED to the grounding ledger, not orthogonal to it.** A published citation IS a published grounding claim ("this work exists and says X"), so §6.5 requires it be grounded. Design: **a `references` entry is publishable-as-citation only if its `[@key]` resolves to a source instance recorded in the artifact's grounding ledger** — the citation becomes a **projection of a real, tiered pool source**, not a parallel free-text channel. This forecloses both leaks by construction (no ledger source ⇒ refused; the citation's authority derives from the ledger source's tier).

**The genuine tension, routed to the gate:** the pipeline grounds in the **client's pool** (repo graph / PDFs / URLs), but an academic paper cites the **broader literature**. Coupling (i) is correct grounding discipline — *a paper should cite works in its own evidence pool; citing works you never grounded in is precisely the fabrication §6.5 guards against* — but it requires the cited works to be present as pool sources (a PDF/URL adapter over the bibliography). This is a **§6.5-adjacent design decision, NOT a §27.4 contract detail**, and it MUST reach the maintainer:
- **(i) RECOMMENDED — couple:** every `references` entry resolves to a ledger source-instance; citations are grounded by construction. Requires cited works in the pool.
- **(iii) fallback — explicit exception:** allow un-pooled `references` as ungrounded-but-attributed, with a **documented, defended §6.5 exception** and a visible "un-grounded citation" marking. Only if the maintainer accepts the risk.
Silence is not an option; recommend (i).

### SF-4 — the DEFAULT (`plain`) citation render is broken. ACCEPT.

**Verified consequence:** if `--citeproc` is emitted only when the presentation `csl` is set (and `csl` defaults empty), the framework `plain` floor — the most common render — **never runs citeproc.** A paper composed with `[@smith2020]` rendered under `plain` ships **raw unresolved bracket text and no bibliography.** The initial coupled two independent things onto one lever that defaults OFF.

**Fix — decouple ENABLEMENT from STYLE:**
- **Enablement is CONTENT-driven:** emit `--citeproc` whenever the AST carries a `references` block / `Cite` elements — **exactly like the provenance-strip is keyed on the writer, not a style lever.** Use Pandoc's default CSL (author-date) when no `csl` is set.
- **`csl` only OVERRIDES the style** (kept as the Presentation asset lever).

**PD5 verified preserved:** enablement is a **deterministic function of AST content**, which is already fully fixed by `fitted-id` — so it is **not a new presentation preimage input.** It is a **pinned serialize behavior**, precisely the pattern the provenance-strip already uses (`STRIP_FILTER_VERSION` rides the §17 serialize-inputs preimage as a versioned byte-altering rule, not a per-deliverable input). A citeproc-enablement rule joins that same class (a pinned serialize-filter version), NOT the presentation delta. The `plain` floor with NO citations lowers byte-identically (zero churn); the `plain` floor WITH citations correctly resolves them (the right default, not churn — the citations are real content). The `csl` STYLE override remains a presentation asset in the preimage, as the initial correctly had it.

### SF-5 — journal-as-recipe vs guide-as-recipe collision. ACCEPT; re-home the journal OFF recipes.

**Verified:** DR-2's reconciliation made a style guide a **topic-less recipe** and **forbade layering two named bundles onto one artifact** (`recipe → one artifact`). The initial's journal-as-recipe would also bind at L5, so a house style-guide recipe + a journal recipe **cannot co-select** — recipes don't compose.

**Fix — a journal is NOT a recipe; its facets are Platform + Presentation coordinates** (this is finer than LaTeX's bundle and matches §5.3: Platform = "a destination + constraint layer … owns mechanical constraints … may declare per-format … projections"):
- structure / required-forbidden sections / abstract ≤N words → **Platform** (the journal Platform entry: per-format hard structural class (SF-1) + hard limits).
- visual look + citation style → **Presentation** (`journal-X-look` + `csl`).
The collision **dissolves** because journal facets are rendering coordinates selected per-deliverable, while the house style-guide is content-side. **And DR-5 forces the clean layering anyway:** the lexicon is compose-baked and **one-choice-per-IR** (§3.3-research / B.3), so the house style **cannot** vary per-journal-deliverable regardless — for the three-journals-one-paper case it MUST be the shared compose-side baseline (an **L3 workspace default**, DR-2's own "below-recipe baseline" option), producing **one IR** that three deliverables render per-venue. Two selectable L5 recipe-bundles on one artifact stays **unsupported** (DR-2's ruling stands), and the driving example **does not need it.** A one-shot "select journal-X" convenience, if wanted, is a thin rendering-only selectable pinning `{platform, presentation}` (optional sugar, registered like the brand pack §26) — it binds no content, so it never collides with the content-side guide. This **overturns the initial's journal-as-recipe framing.**

### SF-6 — the Part-C compatibility check. ACCEPT all three points.

**Verified against code:**
1. **The "lowers to nothing" signal is unsound.** `presentation.py:234-237` emits `--variable=k=v` for every scalar delta **regardless of writer**. A real cross-target brand with `css` (html) + `variables` (fonts) rendered to **docx** drops the css but still emits inert `--variable` flags → the lowering is **non-empty** → the check does **NOT** fire → the "the whole look vanished for docx" case is **MISSED** (false negative).
2. **error-vs-fall-to-default is a design decision, not scoping.** A Presentation is a cross-target brand (PD1); it legitimately skins some output-types and not others. Both "error" and "graceful default" produce an empty lowering; the signal cannot distinguish them.
3. **The check does not belong in pure `lower()`.** `lower()` is a pure `(presentation, writer, output-type) → RenderInputs`; the writer-family gates are the correct per-writer drop and must STAY. `capability_check` already lives at the dispatch layer (`dispatch.py:137`).

**Fix:**
- **Sound signal:** compare the Presentation's declared **SKIN levers** (`css` / `reference_doc` / `template` / `pdf` — the visual-skin carriers) against the requested writer's applicable families; **exclude `variables`** from the "contributes" test (they are cross-writer and emit unconditionally — item 1's fix). Fire only when a non-`plain` Presentation declares skin levers of which **NONE** applies to this `(writer, output-type)`. This correctly ignores a css+reference_doc brand → docx (reference_doc applies) and catches a css-only brand → docx.
- **Pinned semantics — RECOMMEND WARN + fall-to-writer-default,** NOT block: asking a css-only html brand for a docx is a legitimate cross-target act, and a hard block false-positives on it; §3.1 says surface the consequence of the user's config, don't override it. The maintainer explicitly asked for an **error**, so **route block-vs-warn to the gate** — the scoping above makes either safe; I recommend WARN.
- **Locus:** a **new dispatch-layer function** (a `capability_check` sibling in `pipeline/dispatch.py`, §21.7-typed result), comparing the non-plain presentation against the skin-applicability signal. **Do not mutate `lower()`.**

---

## 4. Whole-picture items

### 4.1 The ACCUMULATED §16 reconcile-fidelity list — enumerate as ONE set; flag the burden

The §16 fidelity constraint has been growing one obligation per DR pass without anyone auditing the total. The reconcile agent (an LLM reshape) must now **simultaneously** preserve/enforce, through `reshape`/`split`/`localize`:
- (i) voice + content parameters (base §16);
- (ii) meaning (base §16);
- (iii) per-claim provenance / tier bindings, re-anchored (base §16);
- (DR-2) the applicable **lexicon rules** (DR-2 S4);
- (DR-4, option b) **typed-section conformance** — AND reconcile now also ENFORCES the platform-specific hard structural class (SF-1), not just preserves it: a new structural gate, not merely a preservation clause;
- (DR-5) the **`references` block + inline `[@key]` markers** (a `split` can shatter a citation; `localize` can mangle `[@key]`).

**Flag for the maintainer (§27.4):** this is a **growing product-plane agent-contract burden.** A single `split` must now keep provenance bindings, lexicon rules, section structure, and citation data coherent at once. Register the full set as one list at §27.4 and flag the accumulating contract-complexity as a risk to product-agent reliability — it is no longer a per-pass footnote.

### 4.2 The internal↔external citeproc determinism split — flag as a determinism gate

**Verified:** for `side: external` (pdf/epub/pptx), `dispatch()` returns the stripped `payload_ast` and runs **no** Pandoc — the external actor runs citeproc on its **own, unpinned** toolchain (RI14 carries pins as *requirements*, not enforcement), while internal targets resolve citations under the pinned `pandoc_api_version`/`pandoc_version`. So the SAME paper + SAME `csl` can render citations **differently** internal-html vs external-pdf. The "one AST serves all citation styles" framing hides this.

**Reconcile-or-flag → FLAG as a determinism gate.** It is not resolvable *inside* the pipeline (the external actor is outside the pin boundary by GAP-1's ratified design). The honest disposition: (a) the RI14 payload must carry the **citeproc requirement** — pandoc version + the enablement rule + the `csl` asset (or bytes) — as a pin the external actor MUST honor; (b) it joins the pre-build determinism gate alongside R1 (Pandoc citeproc parity). Extends the initial's R1 from one risk to three (parity, AST-meta threading, internal/unpinned-external split).

### 4.3 Minors

- **MN-1 (string↔typed-slot identity aliasing) — largely MOOTED by option (b), registered for the deferral.** Because the recommended path re-homes DR-4 OFF `format.parts`, the string-vs-map aliasing on `parts` (the two forms hash differently under the §7.2 effective-value delta) does not arise for the paper. It returns only if the deferred **whole-part typed-sub-output** capability is built. Registered there; do not restate any "≡" without the identity asterisk.
- **MN-2 (published `data-cites` vs the strip invariant) — verified; re-frame the C.5 check + note the invariant dent.** `strip_provenance` runs at `dispatch.py:194` **before** the writer; `--citeproc` runs **during** the writer — so resolved citation spans do not exist at strip time (the strip cannot catch `.csl-*` regardless). `_walk_strip` is a pure **Attr-rewriter** over blocks+meta; the CSL-JSON `references` meta is `MetaMap/MetaList/MetaInlines` (no Attr) → it **survives** (correct). BUT post-citeproc HTML publishes `data-cites` attributes, which **contradicts the strip module's own docstring invariant** ("nothing published needs a `data-` attribute"). This is legitimate published citation metadata, not a provenance leak — but a future post-write `data-`-leak audit would trip on it. **Fix:** amend the invariant to except citeproc's `data-cites`; re-frame the planner check as "(a) references-meta survives strip; (b) `data-cites` is sanctioned published metadata," not "confirm the strip never catches `.csl-*`."
- **MN-3 (the DR-4↔DR-3 "shared vocabulary" is aspirational) — RESOLVED by option (b), not papered over.** The adversary was right that under the initial's framing the "shared vocabulary" was a future maybe (DR-3 v1 holistic Markdown has no machine sections to attach a `constraint?` to). Option (b) **makes it real**: it un-defers the section grammar, so DR-3's sections and DR-4's constraints live in **one** representational regime. Under (a) it stays aspirational and MN-3 stands — another reason the a/b choice is load-bearing.

---

## 5. What is KEPT (the adversary could not break these — not re-opened)

1. **No NEW top-level `artifact-id` preimage COMPONENT across the pass** — the strongest result, kept, and it survives even option (b): the section CONSTRAINTS ride the existing Format delta; the section STRUCTURE rides DR-3's already-paid `outline-digest`; the SF-1 hard structural class rides the existing §16 reconcile-inputs preimage; `references` is body-blind; `csl` rides the existing `presentation` coordinate; citeproc-enablement is a pinned serialize-filter version already in the serialize preimage. (Paired with MN-1's aliasing asterisk and SF-2's "no new component ≠ no machinery.")
2. **DR-5 look → Presentation @ serialize** (§5.3 PD4/PD6) — already in the model, zero work.
3. **citeproc at the WRITER step, not at RI7** — preserves PD5's presentation-independent AST (one AST serves every citation style). Architecturally correct (needs SF-2's threading + SF-4's content-driven enablement, which do not disturb the placement).
4. **Inline mechanics compose-baked; lexicon labeled compose-only** — matches DR-2 + the research's firm negative; §14.1 forbids a non-deterministic render rewrite.
5. **The overridable style-file reference already exists on Presentation** (`css`/`reference_doc`/`template`, hashed as assets) — do NOT reinvent.
6. **The provenance-strip is not disable-able by any Presentation lever** — `should_strip` is a pure function of the writer; `dispatch` strips unconditionally; `RenderInputs` has no field that reaches it. A `csl` lever cannot weaken it.

---

## 6. Residual risks + maintainer-gate items

**Must reach the maintainer gate (design decisions above the planner):**

1. **THE DECISION — BLK-1 scope: option (b)-scoped vs (a).** Recommend **(b)-scoped** (typed-section conformance on the body-skeleton surface, whole-section granularity, nested-in-prose slots deferred), which **un-defers DR-3's machine-section-parse** (F1 sentinel grammar + F5 hard structural gate). The clean decision question: **does the maintainer require a HARD per-venue structural guarantee (⇒ b) or accept advisory + Review-2 (⇒ a)?** This is a conscious scope increase — the honest counter to the initial's "zero-footprint reuse" framing.
2. **BLK-2 / SF-1 — the DR-4 field + the hard structural home.** Ratify DR-4's OWN section-conformance field (NOT `constraints?`, which stays reserved for T7) and the new HARD structural class on Platform's per-format projection enforced at a **reconcile structural gate** (a §12.7/§16 extension) + a base structural gate at compose/Review-1.
3. **SF-3 — the citation grounding ruling (§6.5-adjacent, a durable-invariant decision).** Recommend **(i) couple** — every `references` entry resolves to a grounding-ledger source-instance (grounded by construction; requires cited works in the pool). Fallback **(iii)** — an explicit, defended §6.5 exception for un-pooled citations. Decide explicitly; silence forbidden.
4. **SF-5 — journal layering.** Ratify **journal = Platform + Presentation coordinates** (not a recipe); house style = **L3 baseline** for the multi-journal case (forced by the compose-baked lexicon); two selectable L5 bundles on one artifact remains unsupported; a one-shot journal selectable is optional rendering-only sugar (registered).
5. **SF-6 — compatibility check semantics.** Ratify the **skin-lever signal** (exclude `variables`) at the **dispatch layer** (not `lower()`); recommend **WARN + fall-to-default**; the maintainer asked for **error**, so confirm block-vs-warn (scoping makes either safe).
6. **SF-4 — content-driven citeproc enablement.** Ratify enablement keyed on AST content (a pinned serialize behavior, PD5-safe), `csl` as style-override only.

**Planner-facing (mechanism within the ratified frame):**

7. Build the **F1 sentinel section grammar** + the base (compose/Review-1) and platform-specific (reconcile) structural gates; wire the Format section-schema + Platform per-format hard structural class into the §16 reconcile-inputs preimage (delta-vs-floor). Honor DR-3 F5 (structural fidelity check above byte-check).
8. Add the IR `references` block: extend `TOP_LEVEL_KEYS` + a CSL-JSON validator (loud, like `outline-digest`); thread the block into AST-`meta` (SF-2); add `[@key]`/`references` preservation to the §16 fidelity list.
9. Add `presentations/_schema.yaml` `csl` (style-override asset); emit `--citeproc` on content (a pinned serialize-filter version), `--csl` on override; amend the strip invariant to sanction `data-cites` (MN-2).
10. Carry the citeproc requirement (pandoc version + enablement rule + `csl`) into the **RI14 external payload**; register the internal/external citeproc determinism gate (4.2).
11. Register at §27.3/§27.4: the accumulated §16 fidelity set (4.1); the deferred nested-in-prose typed slot + the deferred whole-part typed sub-output (with MN-1's aliasing); the SF-3 grounding-coupling contract; the one-shot journal-selectable sugar.

**Honest residual risks:**

- **R1 (three-part, was one) — the citeproc path:** (a) Pandoc `-f json … --citeproc` round-trip parity at the pin; (b) the envelope→AST-`meta` threading (SF-2); (c) the internal/unpinned-external split (4.2). A §27.2-style pre-build determinism gate covering all three.
- **R2 — option (b) re-enters DR-3's F1/F3 hard problems.** The sentinel grammar + structural fidelity check are the guardrails DR-3 already spec'd, but the build re-opens the byte-vs-meaning and whitespace/nesting churn DR-3 was relieved to defer. Real cost; do not underestimate it at the planner.
- **R3 — the SF-3 pool-membership requirement.** Coupling citations to ledger sources is correct discipline but demands the cited literature be in the grounding pool (a PDF/URL adapter over the bibliography). If the maintainer wants free bibliographies, that is exception (iii) and its risk must be owned.
- **R4 — reframed from the initial (inverted).** The risk is NOT over-design (a nested-slot grammar); it is **under-scope**: (a) does not serve the driving example, and holding R4's original "defer everything nested" line at this pass would ratify a DR-4 that cannot do its commissioned job. The reconciled answer: build the whole-section tier now (b), hold the line at the nested-in-prose boundary.

*End of reconciliation. The initial's "REUSE, zero footprint, homes the example on enriched parts, no machinery, grounding-clean citations" is overturned: BLK-1 is resolved by unifying DR-3 + DR-4 on the body-skeleton surface as one typed-section model (option (b)-scoped, un-deferring DR-3's section grammar — the real build decision routed to the gate); BLK-2 gives DR-4 its own field and leaves `constraints?` to T7; SF-1 adds a hard structural class + reconcile structural gate; SF-2 names the real `references` machinery; SF-3 couples citations to the grounding ledger (overturning the orthogonality framing); SF-4 makes citeproc content-driven; SF-5 re-homes the journal off recipes; SF-6 moves a sound compatibility check to the dispatch layer. The no-new-identity-component result and the five other unbreakable findings are kept. No code, no plan; the maintainer gate runs next.*
