# DR-3 outline — representation, editability round-trip & compose-input — Architect INITIAL (focused extension)

**Pass:** FOCUSED extension of the ratified DR-2×DR-3 reconciliation, stage 05, mode INITIAL. **Class:** read-only. No repo edits. Design recommendation only — **not** an implementation plan, **not** code. The planner runs after the maintainer gate.
**Extends (does not reopen):** `03-architect-reconciliation/report.md` — its B2 total precedence rule, B1 tier-immutability grounding rule, S1/S5/S6 identity rulings (outline's OWN shape `{section-key, heading, intent, constraint?}`, digest-addressed, no `o-` root), and M3 drive-facets all STAND. This pass only resolves what the reconciliation left open: **the outline's representation, its editability round-trip, and its compose-input format**, plus the fanout-granularity question.
**Verified this pass against live code**, not abstraction: `pipeline/ir.py`, `pipeline/compose.py` (`build_writer_prompt`, `parse_writer_output`, `_assemble_ir`), `pipeline/serialize.py` (`emit_fitted_markdown`, `parse_to_ast`), `pipeline/api/render.py` (`unwrap_ir`, internal/external mint), `pipeline/reconcile.py` (`parse_reconciler_output`), `render-targets/{md,html,plain-text}.md`, `pipeline/prompts/writer.md`; and the SSOT `docs/design.md` §7.1–§7.4, §13.1, §14.2, §15, §16, §17 (RI7/RI8/RI9/RI12/RI13/RI14), §18, §19, §21.5, §21.8.

---

## Verdict (one paragraph)

The four-facet path taxonomy is **complete and correct** — I enumerated all 16 (G,E,U,C) combinations under the two constraints and the useful set is exactly {D, B, C, A1, A2} plus one trivial null (no-request); nothing useful is missing and nothing listed is spurious. Fanout granularity resolves cleanly from the identity model: **one outline per `artifact-id`** (the compose-once unit), which for free covers that artifact's entire platform/language/output-type/presentation fanout, because all of that sits below compose; a single shared outline across a multi-*format*/multi-artifact fanout is rejected (the digest identifies one artifact and the outline's structure is format-specific). On representation: the outline's canonical form is **structured, machine-record JSON** (the §13.1 surface→format discipline — the same split the whole pipeline uses), an ordered list of `{heading, intent, constraint?}` with `section-key` a *derived* local handle; it is **not** markdown and **not** the §15 IR. The human never edits the canonical: a **light, pandoc-free, outline-specific round-trip** projects canonical → editable markdown → (human edits) → parse back to canonical, with a re-render **fidelity success test** (`render∘parse∘render = render`; any residual diff is surfaced, never silently dropped). **The existing full-IR↔pandoc-markdown machinery (the GAP-1 work) is the wrong tool and must NOT be reused on the edit round-trip** — it exists to preserve *provenance spans + fenced Divs + the grounding ledger*, none of which the outline has, and (verified) there is **no** markdown→IR reverse parser anywhere to reuse regardless; the outline's editable form is a heading list, for which a pure deterministic template+parser is simpler, dependency-free, and gives the designer direct control of the fidelity target. Compose ingests the **structured canonical** outline (injected into the writer's existing JSON context block), so the compose-input IS exactly what the `outline-digest` pinned — no input/identity divergence; a **whitespace-only edit does NOT churn identity** because the digest is over the normalized canonical, not the editable bytes, exactly as §7.2/§13.1/§21.8 already treat all identity. Grounding is untouched: the outline asserts no facts, so the unchanged `validate_ir` + §6.5 tier-immutability gate still bind every published-as-fact span.

---

## 1. Taxonomy verdict + fanout granularity

### 1.1 The path taxonomy is COMPLETE and CORRECT — verified by exhaustive enumeration

Facets: **G** generate outline · **E** emit outline as deliverable · **U** use outline as compose input · **C** compose a downstream prose artifact. Constraints: **(i) U⇒C** (an input must feed a downstream artifact); **(ii) G=0 ⇒ E=0 ∧ U=0** (can't emit or use what you didn't generate — this also gives E⇒G and U⇒G).

All 16 `(G,E,U,C)` rows, constraints applied:

| G | E | U | C | Disposition |
|---|---|---|---|---|
| 0 | 0 | 0 | 0 | **null request** — nothing generated/composed. Not an outline mode; the trivial empty request. (Acknowledge for completeness; not a behavior.) |
| 0 | 0 | 0 | 1 | **D — today's default.** Compose prose, no outline. ✓ |
| 0 | * | * | * | *(all other G=0 rows)* killed by **(ii)** (E or U set with no generation). 6 rows removed. |
| 1 | 0 | 0 | 0 | generate-and-discard — **ruled out (pointless)**. |
| 1 | 0 | 0 | 1 | outline generated but neither emitted nor used; prose composed without it ⇒ ≡ D + a wasted generation — **ruled out**; falls under the same "G=1,E=0,U=0 = pointless" rule (covers both C values). |
| 1 | 0 | 1 | 0 | **ruled out** — violates **(i)** U⇒C. |
| 1 | 0 | 1 | 1 | **A1 — scaffold, discarded.** Drives compose, not emitted. ✓ |
| 1 | 1 | 0 | 0 | **B — outline IS the product.** ✓ |
| 1 | 1 | 0 | 1 | **C — kept aside.** Emitted AND a prose artifact composed, but outline does not drive it (U=0). ✓ |
| 1 | 1 | 1 | 0 | **ruled out** — violates **(i)**. |
| 1 | 1 | 1 | 1 | **A2 — scaffold, also kept.** Drives compose AND emitted. ✓ |

**Result:** useful set = **{D, A1, A2, B, C}** (5), plus the trivial null. This is **exactly** the maintainer's list. The facets are clean and orthogonal: **G/E/U concern the OUTLINE** (generate / emit-the-outline / use-the-outline), **C concerns the downstream PROSE**; E is outline-emission only — the prose artifact from C rides the normal deliverable pipeline, so there is no hidden "is the prose emitted?" gap. **No refinement needed** beyond noting the null row for completeness. Confirmed.

### 1.2 Fanout granularity — ONE outline per `artifact-id` (the compose-once unit)

The question falls straight out of the identity model, and the answer is decisive:

- **Output-type and presentation are DELIVERABLE-level coordinates; platform/language are FITTED-level** (§7.1: `deliverable-id = fitted-id + output-type + presentation`; `fitted-id = artifact-id + platform + language`). All of these are **below compose**. One `artifact-id` (one composed IR-canonical) already fans out to N fitted × M deliverables. So an outline that seeds **one `artifact-id`** automatically covers that artifact's **entire** output-type/presentation/platform/language fanout for free — the outline is applied once, at compose, upstream of reconcile/serialize. **No per-deliverable or per-output-type outline is ever needed.**
- **Format, topic, persona, voice, goal-set are `artifact-id`-level content dimensions** (§7.1/§7.2 preimage). A request that fans out across *these* produces **different `artifact-id`s** — genuinely different artifacts, with different rhetorical skeletons (§5.2). An outline is a *per-artifact* content+structure plan whose whole justification is per-artifact specificity (reconciliation M4); its structure is format-shaped (a how-to-doc plan ≠ a LinkedIn-post plan). A **single shared outline across different formats/artifacts is rejected** on two grounds: (a) the `outline-digest` is a component of *one* driven `artifact-id` preimage — it identifies one artifact; (b) sharing one structure across formats would force each format's skeleton to be overridden by a *foreign* structure, the exact orthogonality break B2 forbade.

**RULING:** **the outline is scoped to exactly one `artifact-id`.** "One outline per fanout" is only true in the degenerate sense that all the *sub-`artifact-id`* fanout (output-type/presentation/platform/language) of a single artifact shares its one outline — which is automatic and requires nothing. Cross-*content-dimension* fanout gets one outline **per artifact** (authored/edited independently) or none. If a user ever wants to carry a *content brief* (the WHAT — intents only, structure-free) across multiple formats, that is a **distinct future construct**, not this outline (it would be the `intents-must-cover?` facet abstracted away from `use-sections?`/`use-order?`); **flag it, do not build it** — folding it in here would reopen the M4 "specificity engine" scope-creep the reconciliation closed.

**Identity/orthogonality implication:** clean. The outline lives at exactly the level whose identity it perturbs (the `artifact-id`), so the "absent-by-default new preimage component" (reconciliation §4/S1) stays a per-artifact statement with zero cross-artifact coupling and zero DAG-of-ids.

---

## 2. Canonical / persisted form

**RULING: the canonical outline is structured machine-record JSON — the §13.1 surface→format discipline — NOT markdown and NOT the §15 IR.**

Shape (refining, not changing, reconciliation S5): an **ordered list of section records**, each `{ heading, intent, constraint? }`:
- `heading` — the section's title (free text).
- `intent` — free text: *what this section covers* (which arguments/examples/facts to hit). A **lead**, never an asserted fact; carries no ledger (reconciliation B1).
- `constraint?` — an optional, **closed-vocabulary** per-section hint (v1: a length/emphasis hint only). See §5 for why this field must be schema-fenced.
- `section-key` — a **derived** local addressing handle (a slug of `heading` + an ordinal disambiguator on collision). It is a **pure function of the record**, carries no hidden state, and is **excluded from the digest** (it is redundant with `heading`). It exists only so a downstream reference ("expand section-3") has a stable within-outline name.

**Why structured JSON, not markdown or IR:**
1. **It mirrors the pipeline's own architecture.** §13.1 (surface→format) already splits *persisted machine form* (JSON/canonical) from *human surface* (a projection). The IR itself is "machine-generated, machine-consumed" JSON with markdown only in leaves (§15 RI1). The canonical outline follows the identical, already-ratified split — one authoritative structured form, projections off it. No new principle invented.
2. **The digest is trivial and stable.** Canonical JSON (§13.1 machine-record encoding) gives a deterministic byte form ⇒ a deterministic `outline-digest` (§4). Markdown as canonical would make the digest whitespace-fragile (the maintainer's explicit worry) and heading-syntax-ambiguous.
3. **Compose ingests it directly.** `build_writer_prompt` already assembles a JSON `context` dict (`effective_values`, `structure`, `grounded_facts`, `roster`) and `json.dumps`es it into the prompt. A structured outline slots in as one more context block (§4) with zero new prompt machinery.
4. **The maintainer's own premise requires it.** "A human really can't edit an artifact in IR format … so it needs to be rendered in something simple … for editing and then converted back to IR" — i.e. the canonical/persisted form is explicitly **distinct** from the editable form, with a projection between them. Structured canonical + markdown projection is that architecture.

**Delivery-form answer (the maintainer's head-on question — is the outline delivered in IR, in a specific editable type, or both?):** **the outline is persisted in its own structured canonical form; it is delivered to a human as a markdown projection; and, when emitted as a product (E=1), it is rendered to the requested output-type.** It is **not** delivered "in IR" (it is not the §15 IR) and **not** canonical-in-markdown (markdown is a projection, never the source of truth). One canonical, three deterministic projections (edit / compose-input / deliverable) + one digest — all pure functions of the canonical, so none can drift from another.

---

## 3. The round-trip design, the fidelity success test, the reuse ruling, and where fidelity breaks

### 3.1 The round-trip

Two pure, deterministic, **pandoc-free** functions over the outline only:

- `render_edit : Canonical → EditableMarkdown` — each section record → a markdown heading (`heading`) + its `intent` as body text + `constraint?` as a lightweight annotation (e.g. a trailing `(≤N words)` tag or a fenced note). A trivial template; no LLM, no subprocess.
- `parse_edit : EditableMarkdown → Canonical` — headings → section boundaries; text under a heading → that section's `intent`; the annotation → `constraint?`; order = document order; `section-key` re-derived. Insignificant whitespace is **normalized away** (see §3.4).

Flow per the maintainer's spec: `canonical → render_edit → human edits → parse_edit → canonical' → (re-render must ≈ the edited form)`.

### 3.2 The fidelity success test (the maintainer's "verification of success")

Define normalization `N` = the parser's whitespace/heading canonicalization. The design **requires** the projection to be a *retraction*:

- **Round-trip identity:** `parse_edit(render_edit(C)) = C` for every canonical `C` (rendering then parsing recovers the canonical exactly).
- **Normalization idempotence:** `render_edit(parse_edit(render_edit(C))) = render_edit(C)` — re-rendering a parsed edit reproduces the editable form.
- **The success test the maintainer described:** starting from `E = render_edit(C)`, a human edits to `E'`; compute `C' = parse_edit(E')` and `E'' = render_edit(C')`. **Success iff `E'' = N(E')`** — the new canonical renders back to (the normalized) edited original. The **residual `diff(N(E'), E'')` is exactly the information the parser could not capture**, and the design mandates it be **surfaced to the human** ("these edits were not represented in the outline"), **never silently dropped** (§3.1 no-overstep). This makes fidelity loss *observable and bounded*, and gives a concrete CI property test: over a corpus of edited outlines, assert `render_edit(parse_edit(E)) == N(E)` and report any residual.

### 3.3 The reuse ruling — do NOT reuse the full-IR↔pandoc-markdown machinery on the edit round-trip

I read the actual round-trip that exists today:

- **What GAP-1 built** (verified in `render.py`/`serialize.py`/`ir.py`): a **one-way IR→bytes RE-RENDER**. `render._render` loads the raw stored IR via `unwrap_ir`, serialize emits fully-annotated Pandoc-markdown (`emit_fitted_markdown` → fenced Divs `::: {#role .role …}` + enriched provenance spans `[claim]{.tier data-fact=… data-source-…}` driven by the grounding ledger), `parse_to_ast` parses it to the pinned AST, and the internal `md` writer (`render-targets/md.md`: `writer: markdown`, in `SAFE_WRITERS`) emits markdown bytes that **retain provenance**. Its entire raison d'être is **preserving provenance** (the `data-*` spans, the SAFE_WRITERS discipline, §17 RI8).
- **There is NO markdown→IR reverse parser anywhere.** Verified: compose's `parse_writer_output` and reconcile's `parse_reconciler_output` both parse the **LLM's JSON** envelope (`_extract_json_object`), not arbitrary human markdown; `ir.validate_ir` validates IR JSON; serialize is forward-only. The only IR *producer* is an LLM whose output code assembles. **So the "edit → parse back to canonical" leg has no existing machinery to reuse for the outline OR for the document IR — it is new work in every design.**

Therefore the reuse question has a clean, decisive answer:

**Build a light, outline-specific round-trip. Do NOT reuse the full-IR machinery on the edit path.** Grounds:
1. **The outline is not the §15 IR** — no grounding ledger, no fact-ids, no tiers, no part-ids, no provenance spans, no fenced Divs. Forcing it into IR shape to reuse `emit_fitted_markdown` reintroduces exactly the **S5 false economy** (RI2's `role`/`(artifact-id,part-id)` circularity) the reconciliation already rejected.
2. **The machinery's core value — provenance preservation — is irrelevant.** The outline carries no provenance to preserve (it asserts no facts; reconciliation B1). Running it through a provenance-preserving pipeline is pure overhead.
3. **No reverse parser exists to reuse anyway** (above), so "reuse" would only cover the forward leg — and that leg is the one that doesn't fit (point 1).
4. **The outline's editable form is a heading list.** A pure template + a small deterministic parser is simpler than a pinned-pandoc subprocess (a binary dependency, a version pin, a normalization the *human didn't ask for*) for what is structurally headings + text.

**The one place pandoc *should* be reused:** the **emit-to-rich-output-type** path (E=1 with output-type ∈ {html, pdf, docx, …}). There, `render_edit(canonical) → markdown → parse_to_ast → the internal writer` reuses the existing serialize polish appropriately — because that is a **RENDER**, not an edit round-trip, and getting genre-polished bytes is exactly what serialize is for. Pandoc stays **off the edit round-trip's critical path**, **on** the deliverable-polish path. (Plain-text/md emit needs only `render_edit` — no pandoc at all.)

### 3.4 Where fidelity breaks, and how it is bounded

The maintainer named the risks; each is bounded:

1. **Free-text prose under a heading:** *captured*, not lost — the parser maps all text under a heading to that section's `intent` (free text is legal intent). The genuinely-unmappable cases are (a) text **before the first heading** (a preamble) and (b) **nesting deeper than the modeled section level**. Bound: v1 models a **flat ordered section list** (one heading level; intent is free text). Pre-heading text → a designated section-0/preamble intent; deeper nesting → **surfaced as an uncaptured-diff**, never silently flattened.
2. **Reordering sections:** *faithfully captured* — order = document order; parse yields the new order → new canonical → re-render matches. It **does** change the `outline-digest` (a reordered plan is a different plan → new `artifact-id` → re-compose; correct per §18 RI11).
3. **Renaming a heading:** captured as a changed `heading` → new canonical → new digest. Faithful.
4. **A human writing actual prose (drafting the article, not planning it):** this is *below the outline's abstraction*. It is still captured as `intent` bytes, but it means the human is using the wrong tool. Bound: not a fidelity failure (the bytes round-trip), but the authoring-gate UI should frame the field as "what this section covers," and the compose stage treats intent as a lead, not as final prose (§4).
5. **`section-key` drift:** none — `section-key` is derived and non-digested (§2). Renames/reorders never "churn a hidden key"; there is no hidden key.
6. **Whitespace-only / cosmetic edits:** normalized away by `parse_edit` ⇒ **same canonical ⇒ same digest ⇒ no churn** (§3.4/§4). The normalizer must be **conservative** — it collapses only *provably* insignificant whitespace, never indentation a human might be using to mean nesting (that would silently drop a semantic edit; the adversary should probe this — see §6).

---

## 4. Compose-input format + digest stability

### 4.1 Compose ingests the STRUCTURED canonical outline

**RULING: when U=1, compose ingests the structured canonical outline, injected into the writer's existing JSON context block** — one new `outline` key alongside `effective_values` / `structure` / `grounded_facts` / `roster` in `build_writer_prompt`'s `context` dict. The `drive` facets (reconciliation M3: `use-sections?`, `use-order?`, `intents-must-cover?`) ride as flags in that block + corresponding instructions in `writer.md`, telling the writer how bindingly to follow structure vs. order vs. coverage.

Why the structured canonical, **not** a markdown projection injected into the prompt, and **not** something else:
1. **Identity/input must not diverge.** The `outline-digest` is over the canonical (§4.2). If compose consumed a *different* representation (a markdown projection), the writer would see something other than what the digest pinned — a subtle idempotency/cache bug (the same `artifact-id` could be composed from divergent inputs). Ingesting the canonical guarantees **the writer sees exactly what identity fixed**.
2. **The writer is already structured-JSON-driven.** It consumes `grounded_facts`, `effective_values`, `structure` as JSON today. A structured `outline` block is the minimal, orthogonal extension — no new parser, no new prompt architecture.
3. **A second representation is a drift surface.** A markdown-in-prompt outline alongside the structured canonical would be two representations that can disagree — the exact "which is authoritative" ambiguity to avoid.

**On generation quality (the maintainer's "best results" concern):** LLMs often follow a *readable* outline well. This is satisfiable **without** a persisted second representation: the writer prompt MAY render the structured outline into a readable form **at prompt-build time** — a pure function of the canonical, exactly as `_structure_context` already renders the format shape into a human-readable `note`. That rendering is a *prompt-presentation detail*, deterministic from the canonical, never persisted, never digested. So: **one authoritative structured canonical; a deterministic readable rendering for the model at prompt-build time.** Whether the readable rendering measurably helps is an empirical build question (§6), decided like GAP-8's ablation, not by adding a persisted format.

### 4.2 Digest stability — the `outline-digest` is over the normalized canonical

Refining reconciliation §4/S1 (which committed "outline-digest, computed over the outline's own shape"):

- **`outline-digest` = the digest over the canonical JSON of the ordered list `[(heading, intent, constraint?)]`, post-normalization** (`section-key` excluded — it is derived/redundant; order **included** — reorder is a semantic change). Same canonicalization family as every other preimage digest in the system (§13.1 / §7.2 delta-vs-floor discipline).
- **A whitespace-only edit does NOT churn identity.** `parse_edit` normalizes insignificant whitespace ⇒ identical canonical ⇒ identical `outline-digest` ⇒ no new `artifact-id` ⇒ no re-compose. **This is by design and is the correct choice**, justified three ways: (i) §7.2 already defines identity over *canonical content*, never incidental serialization; (ii) §13.1 surface→format already separates bytes from meaning; (iii) §21.8 idempotency = "same inputs → no re-materialize." A cosmetic edit is not a content change. The maintainer's alternative (churn on any byte edit) is explicitly **rejected** — it would re-compose (expensive LLM) on a spacebar press and contradict the whole content-addressed model.
- **A semantic edit DOES churn:** new/removed section, changed heading, changed intent, changed constraint, or reorder → different canonical → different digest → new `artifact-id` → re-compose (old persists as lineage, §18 RI11). Correct.
- **Placement (unchanged from reconciliation §4):** `outline-digest` is a **new, absent-by-default component of the `artifact-id` preimage** (§7.2 extension; zero churn for the ~all artifacts that have no outline; §27.3-justified). The IR `binding` (§15 RI4) additionally *records* the `outline-digest` for lineage — a record, not a second identity. The outline stage-product is persisted **content-addressed by `outline-digest` in a pre-compose store** — a store-keying digest, **not** a §7.4 id-family member, with **direct precedent in §18** (the AST store is keyed by its reader-pin digest and is explicitly "not an id-family member, so no grammar change"). **No `o-` root; §7.4 untouched.**

### 4.3 Emit identity (E=1) — recommendation + the one honest residual

The outline-as-OUTPUT needs a retrieval story (`fetch-by-id`/`emit-manifest` are §7.4 id-family only). Recommendation, lightest-first:

- **v1: the emitted outline is a DERIVED RENDERED VIEW of the `outline-digest`-addressed stage-product** — `render_edit` for plain/md, or the pandoc polish path for html/pdf/docx (§3.3). Retrievable by `outline-digest`; in A2, discoverable via the driven artifact's IR-binding lineage record. This honors DR-3's "you can render just the outline" and the reconciliation's §6.9 "derived view, not a distinct `artifact-id` in v1," with **zero new identity machinery**. In A2 (emit AND drive), the emitted view and the compose seed are **both deterministic projections of the ONE canonical outline**, so they **cannot drift**.
- **Named additive upgrade (flag for the gate):** if the maintainer wants the outline-as-product to be a **first-class deliverable** with full `fetch-by-id`/`emit-manifest`/deliverable parity, the additive path is to compose it as an **ordinary artifact with a one-file framework `outline` Format** — an ordinary `artifact-id` riding the entire existing pipeline, no new machinery, no rework (the canonical outline is the same input either way). This is a bounded upgrade, not a v1 requirement. It is the sharpest residual for the adversarial pass (§6).

---

## 5. Orthogonality / identity / grounding checks

**Orthogonality (B2 total rule holds; one new watch-item):** the representation design does not touch any cascade-bound attribute. The outline governs the non-cascade body skeleton + content emphasis/order (reconciliation B2); the canonical's `constraint?` field is a **per-section body-shaping hint (length/emphasis), compose-consumed** — it is **not** `format.parts`, not a platform hard-limit, not a voice value, not any M2 attribute. **Watch-item for the planner:** `constraint?` must be **schema-fenced to a closed, non-cascade vocabulary** so it cannot become a backdoor attribute-override rung (a human writing `constraint: platform.hard_limit=280` would be an orthogonality breach). This is the single new orthogonality guard this extension introduces.

**Identity (S1/S6 rulings hold and are sharpened):** one authoritative canonical → one `outline-digest` (over the normalized canonical) → one new absent-by-default `artifact-id` preimage component (§4.2). The editable markdown is a *projection*, **not** in identity (whitespace-immune, §4.2). The compose-input is the canonical (= what the digest pinned), so **input and identity never diverge**. Emit = digest-addressed derived view (§4.3). **No `o-` root, no §7.4 grammar change, no DAG-of-`artifact-id`s** — the outline-digest is computed over the outline's own shape, which never references the driven `artifact-id` (reconciliation S1/S6; re-verified: order + `(heading,intent,constraint?)` carry no artifact-id).

**Grounding (B1 tier-immutability holds; no new vector):** the outline asserts no facts, carries no ledger, is tier-transparent. The round-trip is a *structural* projection — it **cannot introduce a fact or a tier** (verified: `render_edit`/`parse_edit` move headings and free-text intents, never ledger entries). Compose is **unchanged** — `parse_writer_output` → `_assemble_ir` → `validate_ir` still fires the §6.5 tier-immutability gate + the bounded re-ask on every span, so a published-as-fact claim still requires an EXTRACTED fact-id, outline or not. A human `intent` that demands an ungrounded claim resolves the same way all compose does: written as an INFERRED/AMBIGUOUS lead or left uncovered — **never fabricated** (reconciliation B1). The residual (no compose-time hard gate that *every* fact-claim cite an EXTRACTED id) is **pre-existing to all compose**, not introduced here; it remains the maintainer's general grounding-hardening question (reconciliation §6.2), untouched by this extension.

**One-file / fewer-mechanisms check:** the round-trip adds **two pure functions** (`render_edit`/`parse_edit`) + **one structured canonical schema** + **one prompt-context block** + **one pre-compose content-addressed store** (§18-precedented). No pandoc on the edit path, no new id family, no new cascade rung, no reuse of the heavy IR machinery. This is the smallest representation that satisfies the maintainer's four requirements.

---

## 6. Residual risks for the adversarial pass + the maintainer gate

**For the adversarial pass to attack:**
1. **Emit identity (§4.3).** Pressure-test the A2 "two-projections-of-one-canonical cannot drift" claim, and whether the "ordinary artifact with Format=outline" upgrade reopens any Part-D parametric-Format concern. Is derived-view-by-digest genuinely adequate for "first-class final artifact format in its own right," or does mode B (outline IS the product) *demand* first-class `artifact-id`/manifest parity in v1?
2. **The conservative-normalizer boundary (§3.4 item 6).** Can `parse_edit`'s whitespace normalization ever silently erase a *semantic* edit (indentation-as-nesting, a human using blank lines meaningfully)? The whitespace-immune-digest ruling is only safe if normalization is provably conservative — attack the edge cases (nested lists, code fences in an intent, tables a human pastes).
3. **Structured-only compose-input (§4.1).** Attack whether structured-only truly yields best generation, or whether the prompt-time readable rendering is load-bearing (or, worse, whether the writer follows a JSON outline poorly and the "no persisted second representation" purity costs quality).
4. **Flat-section-list bound (§3.4 item 1).** Is one heading level enough for real outlines, or does the "deeper nesting → surfaced diff" bound push too much real structure into uncaptured residuals?

**For the maintainer gate (design decisions above the planner):**
- **G-a — representation:** ratify canonical = structured machine-record JSON (§13.1) + markdown editable projection; **not** IR, **not** canonical-in-markdown.
- **G-b — fanout granularity:** ratify **one outline per `artifact-id`**; a cross-format "content brief" is a distinct future construct, not built.
- **G-c — round-trip reuse:** ratify the **light outline-specific round-trip** (pandoc off the edit path; pandoc reused only for rich-output-type emit).
- **G-d — digest stability:** ratify the **whitespace-immune `outline-digest` over the normalized canonical** (cosmetic edit → no churn; semantic edit → re-compose).
- **G-e — emit identity:** ratify **v1 = digest-addressed derived view**; decide whether to also authorize the **first-class-`artifact-id` upgrade** (Format=outline) for outline-as-product.
- These fold into the reconciliation's standing gate items **#1** (the §7.2 `outline-digest` preimage extension — now specified as over the normalized canonical structured form) and **#4** (is the outline worth its cost — this pass adds the generate-outline LLM stage + human authoring gate (M5) + the round-trip functions + the pre-compose store; still the heavier of the two DR features, and still the one to pressure-test).

*End of focused initial. This pass verifies the taxonomy (complete), rules one-outline-per-`artifact-id`, fixes the canonical as structured JSON with a light pandoc-free editability round-trip (the full-IR machinery does not fit and there is no reverse parser to reuse anyway), a re-render fidelity success test with surfaced (never silent) residuals, structured-canonical compose-input, and a whitespace-immune digest. No `o-` root, no §7.4 change, no new cascade rung, no new grounding vector. No code, no implementation plan; the adversarial pass and the maintainer gate run next.*
