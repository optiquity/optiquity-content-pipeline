# DR-4 (content templates) × DR-5 (compose-vs-render style) + style-file/compatibility/CSS — Architect ADVERSARIAL

**Pass:** COMBINED, maintainer-directed. Stage 02, mode **ADVERSARIAL** (initial → adversarial → reconciliation, maintainer-gated). **Class:** read-only. No repo edits, no commit. Critique only — no code, no plan. **Broadened mandate honored:** I attack the initial's four residual risks AND hunt system-wide across the accumulated DR-2..DR-5 design, identity, the IR/compose/reconcile/serialize split, the internal↔external split, and the review gates.

**Verified THIS pass against live code + SSOT (not the reports):**
`docs/design.md` §5.1–§5.3, §6.4/§6.5, §7.1–§7.4, §9.5, §12.3/§12.4/§12.7, §14.2, §15 (RI1–RI4 + substance floor), §16 (reconcile-inputs preimage/fidelity/gate), §17 (RI6–RI14, provenance-strip), §18 (RI10/RI11), §19, §26 (T7 per-part override), §27.3; live code `pipeline/ir.py` (`TOP_LEVEL_KEYS`, `_PART_REQUIRED/_PART_OPTIONAL`, `validate_ir` required-key set, part-`constraints` typed as a `Mapping` "per-part values; interpretation deferred, §26"), `pipeline/presentation.py` (`lower`, `CSS_WRITERS`/`REFERENCE_DOC_WRITERS`/`NO_TEMPLATE_WRITERS`/`PDF_OUTPUT_TYPES`, `delta_vs_floor`), `pipeline/dispatch.py` (`dispatch`, `capability_check`, strip-then-write ordering), `pipeline/filters/provenance_strip.py` (`should_strip`, `_walk_strip` Attr-only rewrite, `SAFE_WRITERS`), `tests/test_presentation.py:146-179`; schemas `formats/_schema.yaml` (`parts` = ordered `list<text>`, replace-combine), `presentations/_schema.yaml`, `render-targets/_schema.yaml`, `output-types/_schema.yaml`; prior rulings `dr2-style-guides/03` (lexicon/topic-less-recipe) and `.../07` (DR-3 C3 Markdown-canonical outline, holistic, no machine section-parse, `constraint?` deferred, multi-part deferred).

**Bottom line:** the initial's *narrow* identity claim ("no NEW top-level `artifact-id` preimage COMPONENT") is TRUE and survives — a real, verifiable win. But its headline framings ("REUSE-dominated," "homes the driving example," "the deferred IR field DR-4 was waiting for," "serialize needs no new machinery," "grounding vs citations orthogonal not blurred") do NOT survive. **The academic-paper driving example — the shared spine of DR-3/DR-4/DR-5 — is NOT served by this v1 design, and the initial claims it is.** Two blockers, six should-fixes, three minors, and a cross-DR coherence fault line follow.

---

## BLOCKERS

### BLK-1 — Typed slots on `format.parts` mis-categorize body structure as packaging sub-outputs; the academic-paper example is BLOCKED, and it collides with the ratified DR-3 B2 rule and the IR parts/body XOR

**The claim under attack (initial A.1/A.2, §0):** "a content template IS `format.parts` generalized from flat named parts to typed slots" and "Directly-selected Format+recipe artifacts get typed slots now" — presented as homing the DR-4 driving example.

**Why it is wrong — three independent, verified faults:**

1. **`parts` are PACKAGING sub-outputs, not rhetorical sections.** `docs/design.md` §9.5 defines composite `parts` as "one artifact whose Format declares intra-genre `parts` — addressed `(artifact-id, part-id)`, stable, living in the IR"; §17 RI9 makes the per-part `packaging_hint ∈ {in-document, standalone}` drive one-file-vs-N serialize fanout; `pipeline/ir.py` validates each part-id as `part_id(artifact_id, role)` with `role` a §7.4 slug — i.e. **every part is an independently addressable sub-output** (the design's own example is `slide-deck → [slides, presenter-notes]`). An academic paper's abstract/methods/results are NOT independently-addressable sub-outputs — they are the **rhetorical structure of ONE flowing body**, which §5.2 explicitly assigns to "the entry's body prose," NOT to `parts`. Homing paper sections on `parts` would make each section its own `(artifact-id, part-id)` unit eligible for `standalone` RI9 fanout — a category error.

2. **It contradicts the RATIFIED DR-3 B2 total rule.** The DR-2×DR-3 reconciliation (`03/report.md` §2, "THE TOTAL PRECEDENCE RULE") ruled: `format.parts` "are resolved SOLELY by the M2 cascade... The outline is never a rung and never overrides them. The outline governs ONLY... the rhetorical body skeleton (not an attribute)." The maintainer's DR-3 requirement is that the outline **drives structure** and **outranks the dimensions for what/how the artifact is written** — i.e. the outline owns section structure. If DR-4 now puts the paper's sections + per-section constraints on the cascade-bound `parts`, then section structure becomes cascade-owned and the outline can **never** drive it — flatly reversing B2. The initial cannot put paper sections on both the outline-governed body skeleton (DR-3) and the cascade-bound `parts` (DR-4); it silently chose `parts`, breaking DR-3.

3. **The IR parts/body XOR makes outline-driven + typed-template mutually exclusive in v1.** `pipeline/ir.py` `TOP_LEVEL_KEYS` + the validator enforce **`parts` XOR `body`** ("Single-part formats collapse to a flat body," §15). DR-3 C3 (ratified, `07/report.md` F6) restricts v1 outlines to **single-part flat-body formats only**. DR-4 typed slots are, in the initial's own words (Integration #1), "inherently multi-part." So an artifact can be **either** outline-driven (single-part flat `body`, no typed slots) **or** typed-template (multi-part `parts`, no outline) — never both. The academic paper needs BOTH (an editable section outline AND per-journal typed section constraints). **v1 as designed serves neither combination for the paper.**

**The tell in the initial's own text.** Integration notes #1–#3 concede: "an outline driving a typed multi-part template is deferred," "Nested-in-prose typed slots (a figure inside a section body) are deferred." A table/figure *inside* the results section — the literal DR-4 ask ("a table with specified columns, a figure with a caption") — is exactly the nested-in-body case the initial defers. So the ONLY thing typed-`parts` can express now is a **whole top-level sub-output that happens to be a table** (a standalone table-part, sibling to slides/notes) — which is NOT what an academic paper is. **The design defers the driving example while the executive verdict claims to home it.**

**Severity: blocker.** Not because typed slots are unbuildable, but because the initial's central positioning ("REUSE, home the driving example on enriched `parts`, zero footprint") is **false** and, if ratified, would (a) mis-model papers as fan-out-able parts, (b) reverse DR-3 B2, and (c) still not deliver the shared driving example.

**What reconciliation MUST answer / the concrete alternative.** Choose explicitly and honestly:
- **(a) Honest defer:** DR-4 v1 ships ONLY whole-part typed sub-outputs (e.g. a `standalone` typed table-part), and the report **states plainly that the academic-paper (typed sections + per-venue section constraints) is NOT served in v1** — deferred *jointly* with DR-3's machine-section-parse, because both need the same section grammar (§07 F1 sentinel-grammar). No pretense of homing the driving example.
- **(b) Design the section model now:** put DR-4's typed *section* skeleton on the **body-skeleton surface** (§5.2, DR-3's domain) as a single-part flat body with declared internal structure + constraints, enforced at compose/Review-1, refinable by the outline (DR-3 drive=structure) — which requires building the machine-section-parse DR-3 deferred. Bigger scope, but coherent, and it is the only path that actually serves the paper.

Either is defensible; the initial's implicit "(a)-but-claim-(b)" is not.

### BLK-2 — The IR `constraints?` field is RESERVED for the open T7 per-part *dimension-value* override; DR-4 repurposes it for *structural conformance* rules — a validated-shape conflict and a pre-emption of an open design

**The claim under attack (initial A.1 table, A.2 "The IR mirror," Integration #5):** the IR part `constraints?` is "a reserved but unimplemented per-part constraint slot... the deferred field DR-4 was implicitly waiting for," to be filled with "per-slot structural constraints (min/max length, min/max count, `columns`, `caption: required`)" each carrying an `error/warning/info` severity.

**Why it is wrong.** §15 RI2 and §26 pin the field's MEANING, and the code pins its SHAPE:
- §15: "`constraints?` carries **per-part attribute values** (the per-part override *implementation* is deferred, §26)."
- §26 "Per-part dimension overrides": "the IR carries per-part `constraints` (§15)... **T7 (open):** ... WHERE a part layer would sit [in the value cascade] is an open design question."
- `pipeline/ir.py` validates `part["constraints"]` as **a `Mapping`** with the literal note "**per-part values; interpretation deferred, §26**."

So `constraints?` is a **map of per-part dimension-attribute VALUES** awaiting the T7 cascade-placement ruling ("this part's voice=X"). DR-4's structural conformance menu is a **list of typed shape rules with severities** ("this table needs ≥2 columns; error"). These are different **concepts** (value-binding vs shape-conformance) AND different **shapes** (map-of-values vs list-of-typed-rules). Filling `constraints?` with DR-4 rules is not "making the reserved field real" — it is **overwriting a reserved meaning with an incompatible one**, then (Integration #5) asking the still-open T7 design to "account for the now-populated `constraints?`." That is precisely the dimension/attribute/cascade blur the architect discipline forbids (design.md §5, orthogonality-first; "fewer special cases").

**Severity: blocker (design-integrity).** It corrupts an open-design reservation and forces T7 to share a field already occupied by a different kind of data.

**What reconciliation MUST answer.** Either give DR-4 structural conformance its **own** part/slot field (leaving `constraints?` free for T7's per-part value overrides), or prove — against §26's "per-part *dimension* overrides" wording — that structural conformance and per-part value-binding are genuinely one concept (they are not). Do not "register the interaction" and proceed; resolve the ownership first.

---

## SHOULD-FIX

### SF-1 — Venue-specific HARD structural requirements have NO hard-enforcement home; the severity model only fits platform-NEUTRAL structure

**Claim under attack (initial A.3/A.4):** structural conformance runs at **compose/Review-1** (error → block there), and venue tightening ("journal A requires methods; journal B forbids acknowledgements") "rides Platform's existing per-format projection."

**The contradiction, verified:** compose/Review-1 is **platform-neutral** — §19 R1 runs "once per artifact, before rendering," and §15 says "IR-canonical is platform-agnostic: no platform... appears in it." It **cannot** enforce a per-journal rule; it does not know the journal. Meanwhile the Platform per-format projection is **ADVISORY**: §12.3 (line 1161) — "Platform's per-format **advisory** constraint projection merges below L5 (map-merge)"; §16's reconcile-inputs preimage lists "the effective **advisory** constraint values... the Platform per-format projection"; §12.7 — advisory norms "ride M2... a recipe/run may deviate, which fires a one-time warning." And the only HARD reconcile mechanism, the §16 terminal gate, is a **fit-or-block on hard LIMITS** ("content that cannot be made to **fit**") — a capacity/length semantics (abstract ≤N words), not a structural "forbid this section."

So "journal B **forbids** acknowledgements" (a hard rejection criterion) lands on the **advisory** projection = warn + user-may-deviate. There is **no** hard, platform-specific, structural block anywhere: compose/Review-1 (hard, but platform-neutral) and the reconcile gate (hard, but numeric-fit) both miss it. The initial's error-severity → compose-block mapping only works for platform-NEUTRAL structure; the driving example's requirements are platform-SPECIFIC.

**Severity: should-fix.** It defeats half the DR-4 driving example (per-journal required/forbidden sections) as a hard guarantee.

**Reconciliation must answer:** where does a **hard, platform-specific, structural** requirement enforce? Candidates to weigh: extend the §16 terminal gate to structural conformance (not just numeric fit) keyed on the per-format projection promoted to a hard class; or a new per-format hard-structural check at reconcile. Do not leave it advisory and call the example served.

### SF-2 — The `references` block is NOT "additive, no machinery"; it touches the closed IR envelope, the RI7 parse, and the reconcile fidelity contract

**Claim under attack (initial B.2a, §0):** "the IR envelope carries a `references` block... Pandoc round-trips both natively, so `serialize` needs no new machinery... additive... no new preimage component."

**Verified false at four points:**
1. **The IR envelope is a CLOSED shape.** `pipeline/ir.py`: `TOP_LEVEL_KEYS = frozenset({ir_version, pandoc_api_version, binding, grounding, parts, body, metadata})` and "an unknown top-level key is a smuggling/typo surface — refused"; `validate_ir` also requires the first four. Adding `references` **requires editing framework code** (the closed set + a new validator for CSL-JSON shape). This is the same class of change DR-3 had to make loud for `outline-digest` — it is not free.
2. **RI7 parses the Markdown LEAF, not the envelope.** §17 RI7 is a single `pandoc -f markdown -t json` over the IR-fitted Markdown; the `references` block lives in the **envelope**, not in the leaf body. For citeproc to resolve `[@key]` against `references`, the envelope block must be **threaded into the AST `meta`** (emitted as leaf YAML frontmatter before RI7, or injected post-parse) — new serialize wiring the initial does not name.
3. **Reconcile is an LLM rewrite that must preserve it.** §16 fidelity (iii) already forces re-anchoring provenance bindings; the `references` block AND the inline `[@key]` markers must survive reshape/split/localize (a `split` could shatter a citation; a `localize` could mangle `[@key]`). That is a **new fidelity-list obligation** (compounding DR-2's own §16 addition), unaddressed.
4. **Round-trip parity is unproven for `-f json` + `--citeproc`** (the initial's own R1) — but note it is worse than stated (see SF-4/whole-picture: the internal/external split).

**Severity: should-fix.** The design is probably still viable, but "no new machinery" is wrong and hides real build surface + a reconcile-contract change.

### SF-3 — Grounding hole: the published `references` block bypasses the §6.5 EXTRACTED floor and the grounding ledger; a hallucinated or claim-decoupled citation ships as fact

**Claim under attack (initial B.2a, Integration "Grounding ledger vs citations — orthogonal, not blurred"):** the ledger (internal, stripped, EXTRACTED-floor-gated) and the `references` block (published) are "different objects, different lifecycles," dual-populated by compose, kept as separate schemas — "register this... as a compose-agent contract detail (§27.4)."

**Why the separation is a hole, not orthogonality.** §3.3 and §6.5 are **durable invariants**: "Only EXTRACTED-tier facts are published as fact... No... configuration, no run, and no override can relax it." The grounding ledger is the mechanism that binds every published claim to a source/commit/tier and is re-checked by §19. The `references` block is **published content that is compose-OUTPUT, in NO preimage, in NO ledger, gated by NO floor, checked by NO traceability**. Two concrete leaks:
- **Fabricated citation:** the compose LLM can emit a `references` entry for a paper that does not exist, or misattribute one. It ships as an authoritative-looking published citation with zero grounding backing. Nothing in the initial requires a `references` entry to correspond to an actual pool source.
- **Claim/citation decoupling:** the initial deliberately keeps the citation schema separate from the claim's tier. So a citation can be attached to an INFERRED/AMBIGUOUS lead, dressing an ungrounded claim in the veneer of citation authority — while the EXTRACTED floor believes it has gated the claim. Orthogonality here **defeats** the floor rather than respecting it.

**Severity: should-fix, leaning blocker** (it touches §3.3, a CLAUDE.md rule-adjacent durable invariant). This is NOT a §27.4 contract detail; it is a grounding-guarantee design question.

**Reconciliation must answer:** what gates the `references` block? Options to weigh: (a) every `references` entry must resolve to a real pool source-instance recorded in the ledger (a hard cross-check); (b) a published citation may attach only to an EXTRACTED-tier claim (couple the two schemas the initial split); (c) accept `references` as ungrounded-but-attributed and document the explicit exception to §6.5 (and defend it against §3.3). Silence is not an option.

### SF-4 — The DEFAULT render of a citation-bearing artifact is BROKEN: citeproc is gated on `csl` presence, so the zero-churn `plain` floor never resolves `[@key]`

**Claim under attack (initial B.2b/B.2c):** citeproc runs "the per-deliverable writer step applies `--citeproc --csl=<presentation.csl>`," and `csl` "defaults empty (PD5 zero-churn preserved)."

**The consequence the initial missed.** If `--citeproc` is emitted **only when `csl` is set**, then the framework `plain` presentation (the PD7 floor, the most common render, and the one that "lowers to the EMPTY struct") **never runs citeproc**. A paper composed with `[@smith2020]` markers, rendered under `plain`, ships with **unresolved raw citation text** (Pandoc renders unresolved `Cite` inlines as their bracketed source form, and never emits a bibliography). So the *default* path for the very artifacts DR-5 targets is broken. The initial couples two independent things — "resolve the citations that exist" (a content-driven need) and "which citation STYLE" (a presentation choice) — onto one presentation lever that defaults OFF.

**Severity: should-fix.** It makes the common case wrong.

**Reconciliation must answer:** decouple enablement from style. `--citeproc` should be driven by **IR content** (the AST carries a `references` block / `Cite` elements) — mechanically like the provenance-strip is keyed on the writer, not a style lever — using Pandoc's default CSL when no presentation `csl` is set; `csl` then only *overrides the style*. Confirm this does not perturb PD5 (citeproc-enablement keyed on AST content is not a Presentation lever and need not enter the serialize preimage as a presentation input; verify against §17 FR7.1).

### SF-5 — Two "recipe-as-a-bundle" overloads collide: DR-4 journal-as-recipe vs DR-2 topic-less-recipe-as-style-guide cannot co-select

**Claim under attack (initial A.4):** a journal is "a **recipe** — pins `{format, platform, presentation+csl}`," explicitly "the same cross-axis-bundle insight the DR-2 reconciliation used for topic-less style-guide presets."

**The collision.** DR-2's reconciliation (`03/report.md` §3) made a **style guide** a *topic-less recipe* (voice+values+lexicon) and **deliberately forbade** layering "a second named bundle onto an existing content recipe (two named bundles → one artifact)... `recipe → one artifact`." DR-4 now makes a **journal** *another* recipe (format+platform+presentation+csl). Both want to bind at **L5** (recipe layer). Therefore a lab with a house **style-guide recipe** publishing to **journal X's recipe** **cannot select both** — recipes do not compose. Its only outs are (a) fold the house voice/lexicon into each of the three journal recipes (duplication across journals — the exact anti-pattern DR-2's shareable `lexicons/` was built to avoid), or (b) demote the house style to an L3 workspace-default (works only if it is a single workspace baseline, not the "apply my guide per-request" the maintainer asked for in DR-2). The two DR passes overloaded ONE mechanism (recipe-as-bundle) for two orthogonal user intents that the design says cannot coexist on one artifact.

**Severity: should-fix.** It is a real cross-DR ergonomic contradiction, not a naming nit (the initial's R3 undersells it as "recipe-naming/sugar").

**Reconciliation must answer:** state the precedence/layering explicitly — is the journal recipe expected to *subsume* the guide (carry its voice/lexicon), does the guide live at L3 beneath the journal at L5, or is the "two selectable bundles" case simply unsupported (and if so, is that acceptable given DR-2's "apply anywhere" requirement)?

### SF-6 — The Part-C compatibility check: "contributes nothing" is ill-defined, the error-vs-fall-to-default choice is an unresolved DESIGN question, and `lower()` must stay pure

**Claim under attack (initial C.2, R2):** block when "a non-`plain` Presentation... lowers to an all-inapplicable result... the lowered `RenderInputs` for this `(writer, output-type)` is empty," implemented by "replace the silent drop" in `lower()`.

**Three problems, verified against code:**
1. **`--variable` flags are emitted regardless of writer applicability.** `pipeline/presentation.py:234-237`: every non-floor scalar variable emits `--variable=k=v` unconditionally. So a real cross-target brand with `css` (html) + `variables` (fonts), rendered to **docx**, drops the css (docx ∉ `CSS_WRITERS`) but still emits inert `--variable` flags → the lowered struct is **non-empty** → the check does **NOT** fire → the "the whole look silently vanished for docx" case is **MISSED** (false negative). The initial's R2 half-sees this but frames it as a planner scoping detail; it is a soundness hole in the proposed signal.
2. **Error vs fall-to-default is a DESIGN decision the initial defers.** A Presentation is a *cross-target* brand (PD1); it legitimately skins some output-types and not others. "You asked this brand for an output-type it does not skin" could be **an error** (maintainer's "css-for-docx should error") OR **a graceful fall to the writer's default look**. Both produce an empty lowering; the check cannot distinguish them. This is the semantics that reconciliation must pin — not a planner scoping detail.
3. **The check does not belong in `lower()`.** `lower()` is a pure `(presentation, writer, output-type) → RenderInputs` and per PD3 the dispatcher "sees ONLY that flat struct"; the writer-family gates are the correct per-writer drop and must **stay**. The compatibility surfacing is a **separate dispatch-layer** result (a `capability_check` sibling in `pipeline/dispatch.py`, §21.7 typed), comparing "non-plain presentation" against "lowered-empty" — not a mutation of the pure gates. "Replace the silent drop" is the wrong locus.

**Severity: should-fix.** The maintainer explicitly wants this behavior; the design of it is under-specified in a way that will either false-negative or false-positive.

---

## MINOR

### MN-1 — string↔typed-slot-map identity aliasing
The initial says a bare-string part `methods` "≡" `{role: methods, type: prose, cardinality: 1}`. Enforcement treats them alike, but the `artifact-id` delta-map (§7.2) hashes the **effective value**, so the two forms hash **differently** → two semantically-identical templates mint **different** `artifact-id`s and do not dedup under idempotency (§21.8). No churn for *existing* string-parts (their value is unchanged), so "backward-compatible" holds narrowly — but "≡" is false at the identity layer. Note it; do not let the reconciliation restate "≡" without the asterisk.

### MN-2 — the C.5 provenance-strip check is mis-framed (and published `data-cites` dents the strip invariant)
The initial asks the planner to "confirm the strip never catches `.csl-*` citation spans." Verified: `pipeline/dispatch.py` runs `strip_provenance` **before** the writer, and citeproc runs **during** the writer (`--citeproc` flag) — so resolved citation spans **do not exist** at strip time; the strip cannot catch them regardless. The strip is a **pure Attr-rewriter** (`_walk_strip` only touches nodes whose `c[0]` is a Pandoc `Attr`), and CSL-JSON `references` meta is `MetaMap/MetaList/MetaInlines` (no Attr) → it survives. So the check that MATTERS is (a) references-META survives strip (it does) and (b) that post-citeproc HTML publishes `data-cites` — which is *fine* as published citation metadata but **contradicts the strip module's own invariant** ("nothing published needs a `data-` attribute," `provenance_strip.py` docstring). Any future post-write `data-`-leak audit would now trip on legitimate `data-cites`. Re-frame the check; note the invariant dent.

### MN-3 — the "same constraint vocabulary, DR-4 ↔ DR-3-deferred outline" unification is aspirational
Integration #2 claims DR-4 `constraints` and the DR-3-deferred outline `constraint?` are "the SAME concept in two places" sharing one vocabulary. But DR-3 C3 (ratified) is **holistic Markdown with NO machine section-parse** — there are **no** machine "outline sections" to attach a `constraint?` to in v1. DR-4 constraints attach to declared, typed, machine-structured slots. The two live in **incompatible representational regimes** (opaque-Markdown vs structured-YAML); the "shared vocabulary" is a future *maybe*, not a v1 coherence, and invoking it to claim "fewer special cases" papers over BLK-1's real conflict.

---

## WHOLE-PICTURE / CROSS-DR COHERENCE (DR-2 + DR-3 + DR-4 + DR-5)

**Do the four accumulated designs cohere? Partially — and the fracture is exactly on the shared driving example.**

- **The parts/body XOR is the fault line.** DR-3 (C3) lives on the **flat `body`** side (single-part, holistic, no section-parse). DR-4 (typed slots) lives on the **`parts`** side (multi-part, structured, addressable). `pipeline/ir.py` enforces these are **mutually exclusive**. The academic paper — the object DR-3, DR-4, and DR-5 all cite — needs an editable section plan (DR-3, `body` side) AND typed per-venue section constraints (DR-4, `parts` side) AND per-venue citation/inline style (DR-5) **on one artifact at once**. The accumulated design cannot place it. The initial's response is to defer the intersection (Integration #1–#3) while the executive verdict claims the example is homed. **This is the single most important thing reconciliation must confront:** DR-3 and DR-4 were supposed to be designed *together* (known-issues DR-3: "to be designed *jointly*"; DR-4 "linked to DR-3"), and the initial instead put them on opposite sides of an XOR and deferred the seam.

- **Identity — the initial's real, defensible win, honestly conceded.** Unlike DR-2 (+lexicon-id) and DR-3 (+outline-digest), which each added a top-level `artifact-id` preimage COMPONENT, DR-4/DR-5 add **none**: `parts` already rides the Format delta (§7.2); `references`/`body` are body-blind (correctly NOT in the preimage — verified against `_validate_binding`'s closed `{artifact_id, preimage, digest}` and the body-independent mint); `csl` rides `deliverable-id`'s existing `presentation` coordinate and defaults empty → the `plain` floor is byte-identical (verified against `delta_vs_floor` + `serialize_inputs_preimage` + `tests/test_presentation.py:81-96`). **I could not break the "no new preimage component" claim** — it is the pass's strongest result and should be kept. (Caveat MN-1: "no new component" ≠ "no aliasing.")

- **journal-as-recipe vs guide-as-recipe** (SF-5): two bundle-overloads on one non-composing mechanism — a genuine DR-2×DR-4 collision.

- **The reconcile fidelity contract is silently accumulating.** DR-2 added "preserve lexicon rules" to §16 (its S4). DR-4 needs "preserve typed-slot conformance through reshape/split." DR-5 needs "preserve `references` + `[@key]` through reshape/localize." Each pass bolts one more obligation onto the §16 LLM-rewrite fidelity list without anyone auditing the *total* — a `split` or `localize` now has to preserve provenance bindings, lexicon rules, typed structure, AND citation data simultaneously. Reconciliation should at least enumerate the accumulated §16 fidelity set as a single list and flag it as a growing product-plane agent-contract burden (§27.4).

- **The internal↔external split (GAP-1) fractures citeproc determinism.** For `side: external` (pdf/epub/pptx), `pipeline/dispatch.py` returns the stripped `payload_ast` and runs **no** Pandoc — the external actor runs citeproc with an **unpinned** toolchain, while internal targets resolve under the pinned `pandoc_version`/`pandoc_api_version` (`render-targets/_schema.yaml`). So the SAME paper + SAME `csl` can render citations **differently** as internal-html vs external-pdf. The initial's C.6 carries `csl` into the RI14 payload but does not confront that citeproc resolution is now split across a pinned/unpinned boundary — a determinism gap the "one AST serves all citation styles" framing hides. Extends the initial's R1.

---

## ATTACK ON THE INITIAL'S OWN RESIDUAL RISKS (R1–R4)

- **R1 (Pandoc citeproc parity) — understated.** It names only binary/api parity. It misses (a) the envelope→AST-meta threading (SF-2), (b) the reconcile-fidelity preservation of `[@key]`/`references` (SF-2), and (c) the internal/unpinned-external citeproc split (whole-picture). R1 should be three risks, not one.
- **R2 (compatibility scoping) — correct but mis-severity'd.** It is not a planner scoping detail; the "contributes nothing" signal is *unsound* while `--variable` flags emit unconditionally (SF-6.1), and the error-vs-fall-to-default *semantics* is a design decision (SF-6.2). Promote from residual-risk to a should-fix the reconciliation resolves.
- **R3 (journal-as-recipe ergonomics) — undersold.** Framed as "recipe-naming/sugar." It is a hard DR-2×DR-4 collision: two bundles cannot co-select on one artifact (SF-5).
- **R4 (DON'T-OVERDESIGN) — the wrong worry, inverted.** R4 warns against "a full nested typed-slot grammar." The actual risk is the **opposite**: the design is **UNDER-built** — the deferral of nested/section slots is not "holding the line," it is the hole that **blocks the driving example** (BLK-1) and the SF-1 hard-structure gap. Holding R4's line at the adversarial pass would ratify a design that does not do the job. The reconciliation should reframe R4 as "is v1 under-scoped for its own driving example?" — and answer yes.

---

## WHAT I COULD NOT BREAK (honest)

1. **DR-5 look → Presentation @ serialize (B.1).** Already in the model (§5.3 PD4/PD6), applied on the persisted AST, cheapest tier (§18). Zero work, correctly claimed.
2. **`csl` as a Presentation asset lever, zero-churn when empty (B.2b).** Verified against `delta_vs_floor` + `serialize_inputs_preimage` + `tests/test_presentation.py`: an unset `csl` lowers to nothing → the `plain` floor stays byte-identical → PD5 zero-churn holds. (The DEFAULT-render breakage is SF-4, a separate issue — the *identity* claim itself is sound.)
3. **citeproc at the writer step, NOT at RI7, to preserve PD5 (B.2c).** Architecturally correct: §17/§18 key the persisted AST by `fitted-id`, presentation-independent; running citeproc at the per-deliverable write keeps one AST serving every citation style. The PLACEMENT is right (even though it needs the SF-2 threading).
4. **Inline mechanics compose-baked; label the lexicon compose-only (B.3).** Matches the DR-2 reconciliation and the research's firm negative verdict; §14.1 forbids a non-deterministic render rewrite. Solid.
5. **The overridable style-file reference already exists on Presentation (C.1).** Verified against `presentations/_schema.yaml` (`css`/`reference_doc`/`template`) + `presentation.py` (`lower` emits flags, hashes assets). "Do not reinvent" is correct.
6. **No NEW top-level `artifact-id` preimage component across the pass.** The strongest result; verified end-to-end (see whole-picture). Keep it — but pair it with MN-1's aliasing caveat and stop restating "backward-compatible ≡" without qualification.
7. **provenance-strip is not disable-able by any Presentation lever (C.5 spirit).** Verified: `should_strip` is a pure function of the writer; `dispatch` strips unconditionally; `RenderInputs` has no field that reaches it. The security property holds; a `csl` lever cannot weaken it. (The strip's *interaction* with citeproc is MN-2, not a break of this property.)

---

*End of adversarial. The identity discipline of this pass is genuinely strong and survives. But the initial's positioning — "REUSE, home the driving example on enriched `parts`, no new machinery, grounding-clean citations" — does not: BLK-1 (the parts/body XOR blocks the academic paper and reverses DR-3 B2), BLK-2 (the `constraints?`/T7 field conflict), SF-1 (no hard venue-structure enforcement), SF-2 (`references` needs real machinery), SF-3 (the citation grounding hole), SF-4 (broken default citation render), SF-5 (the recipe-bundle collision), and SF-6 (the compatibility signal is unsound). The reconciliation's central task is to stop pretending DR-3 and DR-4 were designed together and actually reconcile them on the one object all four DRs share — the academic paper. No code, no plan; the reconciliation runs next.*
