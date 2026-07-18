# DR-4 (content templates) × DR-5 (compose-vs-render style) + the folded-in style-file / compatibility / CSS questions — Architect INITIAL

**Pass:** COMBINED, maintainer-directed. Stage 01, mode **INITIAL** (initial → adversarial → reconciliation, maintainer-gated). **Class:** read-only. No repo edits, no commit. Design recommendation only — **no code, no implementation plan** (the planner runs after the maintainer gate).

**Grounded and verified this pass against live code + SSOT, not the reports:**
`docs/design.md` §5.1/§5.2/§5.3 (dimensions; Presentation PD1–PD8), §7.1–§7.4 (identity), §12.2–§12.7 (cascade; Platform per-format projection; brand-authoritative; constraints/weights), §14.2 (two passes / four layers / internal-vs-external), §15 (IR: `parts`, `constraints?`, grounding ledger, substance floor), §16 (reconcile; hard-limit gate; fit-binding), §17 (serialize; RI7/RI8/RI12–RI14; provenance-strip; Presentation lowering), §18 (regeneration tiers), §19 (review gates), §26/§27 (deferred + open register);
live schemas `formats/_schema.yaml` (`parts` = ordered `list<text>`), `presentations/_schema.yaml` (`variables`/`highlight_style`/`template`/`reference_doc`/`css`/`pdf`), `output-types/_schema.yaml` (empty manifest — pure coordinate), `render-targets/_schema.yaml` (`writer`/`side`/`engine`/`reference_doc`/pins), `platforms/_schema.yaml`;
live code `pipeline/presentation.py` (`lower(presentation, writer, output_type)`, `CSS_WRITERS`, `REFERENCE_DOC_WRITERS`, `NO_TEMPLATE_WRITERS`, `PDF_OUTPUT_TYPES`), `pipeline/dispatch.py` (`capability_check`, `dispatch`, `RenderInputs`, `INTERNAL_WRITERS`), `render-targets/{md,html,docx,plain-text}.md side:internal · {pdf,epub,pptx}.md side:external`, and `tests/test_presentation.py:146-162` (the load-bearing silent-drop assertion);
prior rulings held fixed: **DR-3 = C3 (Markdown-canonical outline, ratified)**, **DR-2 = `lexicons/` at compose + topic-less recipe (reconciled)**, and the research's **compose↔render boundary principle**.

---

## 0. Executive verdict (build-vs-reuse)

**This is overwhelmingly a REUSE pass, not a build pass — and it adds ZERO new identity surface** (in deliberate contrast to DR-2/DR-3, which each added two `artifact-id` components).

- **DR-4 content templates — REUSE + one small vocabulary.** A content template is, per the research and the whole structured-content field, a **content-model/schema** artifact (typed slots + cardinality + constraints + order), *not* a stylesheet. Its pipeline home already exists: it is **Format's `parts` structural surface, enriched from flat named parts to typed slots**, backed by the **IR part `constraints?` field that §15 already reserves for exactly this** (its implementation is deferred, §26/T7). Venue-specific tightening (journal A requires methods; journal B forbids acknowledgements) rides **Platform's existing per-format projection** (§12.3 — Platform is the one `override-projection: yes` dimension); a must-fit length limit (abstract ≤N words) rides **Platform hard limits → the §16 reconcile gate** — both already built. "Select journal-X's whole template at once" is a **recipe** (the cross-axis bundle). The *only* genuinely new thing is the small **typed-slot vocabulary** (a `type` enum, the research's cardinality operators `?`/`*`/`{n,m}`, a per-slot constraint menu, and an **error/warning/info** severity that maps 1:1 onto the pipeline's existing hard-block-vs-advisory split). **No new registry, no new axis, no new cascade rung, no new construct, no parallel subsystem.**
- **DR-5 style placement — one home already solved, one small new handle, one confirmed compose-bake.** Three kinds, three homes, exactly as the research's boundary principle predicts: **look (fonts/colors/layout) → Presentation @ serialize — ALREADY IN THE MODEL, no work.** **Citations/footnotes → a small, additive, Pandoc-native structured-citation handle in the IR (compose-side) + a swappable per-venue `.csl` style file carried as a Presentation lever (render-side) — REUSE Pandoc citeproc + the Presentation dimension.** **Inline mechanics (Oxford comma) → compose-baked in the DR-2 `lexicons/` registry — CONFIRMED: no deterministic render-time path exists anywhere; per-venue ⇒ re-compose (already correct, since the lexicon is in the `artifact-id` preimage). The lexicon must be explicitly labeled compose-only.**
- **Part C style-file reference / compatibility / CSS — mostly CONFIRM-AND-DON'T-REINVENT.** The **per-run/recipe/workspace overridable reference to a hand-crafted style file already exists** — `presentations/_schema.yaml` `css`/`reference_doc`/`template`, resolved over the M2 spine (L2/L3/L5/L6), applied at serialize, hashed as assets. The pipeline already **holds a reference** to a hand-crafted file (it does not generate it), precisely per the maintainer's DON'T-OVERDESIGN directive. The *one* genuinely-new Part-C mechanism: **presentation↔output-type compatibility validation does NOT exist today — a mismatch (css for docx) is silently dropped, verified in code and asserted in a test** — and the fix is small (turn the existing writer-family gate from a silent drop into a surfaced result). CSS packaging (inline vs external) is deferred as an implementation detail (currently external-linked). CSL and CSS compose (CSL structures the citation; CSS skins it). For `side: external` targets (pdf/epub), per-venue style flows via the RI14 layer-3 payload — design-complete, wiring is a planner item.

**Net:** the smallest possible footprint — one additive Format-`parts`/IR-`constraints?` typed-slot vocabulary, one additive Pandoc-native IR citation block, one additive Presentation `csl` field, and one small compatibility surface — all riding existing axes, existing cascade rungs, and existing identity coordinates. No external research required; the internal model plus the stage-0 grounding report are sufficient.

---

## Part A — DR-4 content templates

### A.1 Where the line is: a content template is a content-model, and it already has a home

The research's load-bearing finding (§2.3) is unambiguous and matches the pipeline's own factoring: across DITA, DocBook, Portable Text, ProseMirror, and headless CMS, the reusable **"template" is a CONTENT-STRUCTURE / SCHEMA artifact — typed slots, their kinds, their cardinality/constraints, their order — kept deliberately SEPARATE from the presentation stylesheet.** LaTeX is the lone outlier that bundles structure+style in the document class, and even it keeps `\cite`+`.bib` (structured) apart from `.bst` (style).

Mapped onto the pipeline, this lands squarely on the **content/compose side**, and the pipeline already carries two structural surfaces there:

| Structural surface | What it is today | Role for DR-4 |
|---|---|---|
| **Format entry body prose** (§5.2: "the genre's rhetorical structure is the entry's body prose") | a reusable **genre default**, consumed at compose, not a declared attribute | unchanged — the prose scaffold; the DR-3 outline is the per-artifact substitute |
| **`format.parts`** (`formats/_schema.yaml`: ordered `list<text>` of named sub-outputs) | the **one declared structural attribute**; binds at M2-compose; enters `artifact-id`; drives §17/RI9 serialize fanout and §7.1 `(artifact-id, part-id)` addressing | **the home for typed slots** — enrich flat named parts into typed slots |
| **IR part `constraints?`** (§15/RI2: `{part-id, role, constraints?, packaging_hint, body}`; "per-part override *implementation* is deferred, §26/T7") | a **reserved but unimplemented** per-part constraint slot | **the home for per-slot constraints** — the deferred field DR-4 was implicitly waiting for |

**Recommendation (the line, DR-4 open q a & e):** a content template **is not a new construct** and **is not a richer *anything-else***. It **is `format.parts` generalized from flat named parts to typed slots, plus the already-reserved IR `constraints?` field made real.** This is the tightest possible reuse: Format `parts` ↔ IR `parts` are already mirror surfaces; both gain a `type` and populate `constraints`. It honors the research's "content template = content-model, separate from stylesheet" and it **disambiguates the naming collision (open q e) by construction**: the DR-4 *content* template lives on **Format** (WHAT slots exist), and is a categorically different artifact from Presentation's `template`/`reference_doc` (HOW it looks — a Pandoc *visual* template applied at serialize). Do not name the DR-4 schema field "template"; it is `parts` (enriched). "Content template" stays as the user-facing informal name.

### A.2 The typed-slot + per-slot-constraint vocabulary (the one genuinely new thing)

Draw directly on the research's ready menu (§2.1), keeping it a **closed, one-file-add-extensible** vocabulary — no general grammar, no expression language.

**A `format.parts` element becomes either a bare string (today's behavior, backward-compatible) or a typed-slot map:**

- A **string** element `methods` ≡ `{role: methods, type: prose, cardinality: 1}` — every existing `parts: [slides, presenter-notes]` is untouched (no migration, additive; `parts` still combines by *replace* and `union` on it stays a schema error per §12.4).
- A **map** element `{role, type, cardinality?, constraints?}`:
  - **`type`** — a closed enum of slot kinds: `prose | table | figure | callout | …` (the research's non-text element kinds, §2.1d). Extensible one-file-add as a schema-enum value. This is the "typed non-text slot" the pipeline lacks today (§15: non-text is currently only expressible as untyped Markdown inside a `body`).
  - **`cardinality`** — `1` (required, default) | `?` (optional) | `*` (repeatable) | `{n,m}` (bounded) — the research's ProseMirror content-expression operators (§2.1e), which are the *solved shape* for the "scaffold, not a mold" flexibility requirement (§2.2, DR-4 open q c): optional slots = `?`, repeatable = `*`/`{n,m}`.
  - **`constraints`** — the per-slot constraint menu, each entry carrying a **`severity ∈ {error, warning, info}`**: `min/max length`, `min/max count`, and per-`type` constraints (`columns:[…]` for `table`, `caption: required` for `figure`, `label` for `callout`). **Ordering** is the `parts` list order itself (already ordered, already replace-combined) — no separate operator needed.

**The IR mirror:** the IR part shape gains `type` (default `prose`) alongside its existing `role` and `constraints?`. Compose fills the IR parts to satisfy the Format's typed slots; the effective per-slot constraints record into `constraints?`.

### A.3 Enforcement — the severity split maps 1:1 onto machinery that already exists

The research flags (§2.1e, §4.1) that the pipeline **already mirrors** the Sanity `error/warning/info` split with its own hard-limit-vs-advisory two-tier. Reuse it verbatim — invent no new gate:

| Slot-constraint severity | Existing pipeline mechanism it rides | Behavior |
|---|---|---|
| **error** | the §6.4 block-and-report pattern / §16 fit-or-block gate — a hard, loud block; other fanout items continue | a structurally non-conformant artifact **blocks** (a typed result, e.g. `template-slot-violation`, tier generation, block) — never silently ships |
| **warning** | §8 advisory lint / §12.7 advisory-deviation warn — the user's act, recorded, never auto-fixed (§3.1) | surfaced as a warn; the user deviates knowingly |
| **info** | the softest advisory rung (lint-info) | recorded, non-blocking |

**Placement:** the structural conformance check runs at **compose / Review 1** (§19 — the early, pre-fanout substance gate that already reads the IR). This is the correct, cheap point: structure is platform-neutral, so it is checked once per `artifact-id`, before rendering fanout — exactly Review 1's economy.

**Critical division of labor (so DR-4's new surface stays minimal):**

- **Structural conformance** (a required slot is present; a `table` has its columns; a `figure` has its caption; slots are in order) → the **new** typed-slot `constraints`, checked at compose/Review 1. *This is the whole of DR-4's new capability.*
- **Must-fit length/count limits** (abstract ≤N words) → **already built**: a Platform **hard limit** enforced at the §16 reconcile terminal gate (fit-or-block), OR a Platform **advisory** norm (§12.7). No new work — the driving example's "abstract ≤N words" is a Platform limit, not a new mechanism.

### A.4 Venue-specific tightening + "is a journal a Platform?" (DR-4 open q f)

The DITA constraint-module case (§2.1e: journal A *requires* a structured methods section; journal B *forbids* acknowledgements) is venue-specific structural tightening of a base template — and it must NOT be homed on Format, because Q4 deliberately deleted Format↔platform coupling (`formats/_schema.yaml`: "homing pair-keyed data here would re-couple Format to platforms").

**It rides Platform's existing per-format projection.** Platform is the single `override-projection: yes` dimension (§5.1); it already projects per-format advisory constraints and per-format reconcile-strategy defaults into the cascade below L5 (§12.3). A journal Platform entry projects **per-format typed-slot tightenings** through the identical mechanism (make an optional slot `required`; forbid a slot; tighten a `min/max`). This is the exact DITA-constraint-module analog and it reuses a built projection — no new mechanism.

**Is a journal a Platform? — No; a journal is a cross-axis bundle, and the pipeline models it as one (finer than LaTeX's class).** The research (§2.4, §4.1) confirms external systems cannot settle this — it is an architect decision. Decompose the LaTeX "one journal = document class = {structure+style+design+citation}" bundle across the pipeline's finer axes:

| Journal facet | Pipeline home |
|---|---|
| structure (which sections, order, slot types) | **Format** (research-paper genre + typed slots, §A.2) |
| required/forbidden sections, section tightening | **Platform** per-format projection (§A.4, §12.3) |
| abstract ≤N words and other must-fit limits | **Platform** hard limits → §16 reconcile gate |
| visual design (fonts/columns) | **Presentation** (§5.3 — already solved) |
| citation/footnote format | **Presentation** `csl` lever (Part B) |
| "select all of journal-X at once" | a **recipe** — pins `{format: research-paper, platform: journal-X, presentation: journal-X-look+csl}` (§8: a recipe binds one entry per content dimension and MAY pin rendering targets) |

So a "journal template" as a user-facing selectable is a **recipe** (the same cross-axis-bundle insight the DR-2 reconciliation used for topic-less style-guide presets). The three-journals-one-paper case is **three recipes over one shared IR-canonical**: font/design differences ride Presentation per-deliverable; citation-format differences ride the `csl` Presentation lever per-deliverable; required/forbidden-section differences ride Platform per-format projection at reconcile; the Oxford-comma difference is the one thing that forces a re-compose per journal (Part B / §3.3 research). No axis is re-owned.

---

## Part B — DR-5 style placement (three kinds, three homes)

Anchored on the research boundary principle (§3.4): **a style rule lives at render iff its input is carried structured; a rule expressed as literal inline prose with no structured handle stays compose-baked.** The pipeline's own IR-canonical(compose)↔serialize(render) split is that same line.

### B.1 Look (fonts / colors / layout) → Presentation @ serialize — ALREADY SOLVED

No design needed. §5.3 PD4/PD6 already home the visual look on Presentation, applied deterministically at serialize on the persisted AST (the cheapest regeneration tier, §18). The research confirms (§4.2) this is correct and complete. Zero work.

### B.2 Citations / footnotes → structured citations in the IR (compose) + a swappable CSL style (render) — the one small new handle

The research (§3.2) gives a mature, Pandoc-native template: **CSL cleanly separates (1) structured item metadata (CSL-JSON: authors/year/title/journal/volume) — format-agnostic, static — from (2) a swappable style file (CSL XML: author-date vs numeric vs note/footnote), resolved at processing/render time by a citeproc processor** — and **Pandoc (the pipeline's own engine) already supports CSL end-to-end.** This decomposes onto exactly the pipeline's compose↔render split:

**(a) The structured-citation DATA → an additive, Pandoc-native handle in the IR (compose-side).** Today the IR grounding ledger (§15/RI3) carries **internal fact provenance** (source repo, commit, tier, traceability anchor) — it is NOT bibliographic-citation-renderable structured references, and it is stripped from public output. That is the gap DR-5 names. The minimal fix reuses Pandoc's *native* citation model — invent no bespoke citation schema:

- the IR envelope carries a `references` block = **CSL-JSON** items (the same structure Pandoc reads);
- IR Markdown leaves carry Pandoc **`[@key]`** citation markers.

Pandoc round-trips both natively, so `serialize` needs no new machinery. The `references` block is **compose output content** (like the body), determined by the same compose inputs — so it **rides the existing content identity**: a source/content change already re-composes to a new `artifact-id` (body-blind identity holds; **no new preimage component**). This keeps the citation DATA on the compose side, exactly where the boundary principle puts a structured content input.

**(b) The per-venue citation STYLE → a swappable `.csl` file carried as a Presentation lever (render-side).** A `.csl` style file is a **hand-crafted style artifact referenced by the pipeline** — mechanically identical to `css`/`reference_doc`/`template`, applied at serialize via a Pandoc flag (`--csl=<file>` + `--citeproc`), hashable as an asset. It fits `presentations/_schema.yaml`'s own charter verbatim ("the levers that are Pandoc flags, hashable files, or per-writer dispatch") and PD6 ("Presentation = deterministic style @ serialize; Presentation only styles what exists"). **Recommendation: add one `csl` field to the Presentation schema** (a single style-file path, lowered to `--csl` + `--citeproc`, hashed into the serialize-inputs preimage like every other asset, PD5 zero-churn preserved since it defaults empty). Per-venue swap = per-Presentation-entry = the `presentation` coordinate already in `deliverable-id` — **no new axis, no new cascade rung, no new identity surface.** This directly answers DR-5 open q b (the render-time footnote/citation path) and confirms the research's placement "at/near Presentation/serialize, keyed per fitted-or-deliverable coordinate" (§4.2).

**(c) The load-bearing serialize-placement detail — citeproc runs at the FINAL writer step, not at the IR→AST parse — to preserve PD5.** PD5 requires the AST to be **presentation-independent** (one AST serves all looks; `fitted-id`/AST untouched by presentation). If citeproc resolved citations *into* the AST at the RI7 parse, the AST would depend on the CSL style and PD5 would break. Therefore: **RI7 (`pandoc -f markdown -t json`) must NOT run citeproc** — the AST carries unresolved Pandoc `Cite` elements + the `references` metadata; **the per-deliverable writer step applies `--citeproc --csl=<presentation.csl>`** to resolve citations per-venue. This keeps one AST serving every citation style, puts the CSL swap exactly at the per-deliverable serialize (Presentation lowering), and stays fully inside the existing deterministic, LLM-free serialize pass — no new pass, no LLM. (Flag: this is a serialize pin/ordering addition for the planner — `--citeproc` at write time, not read time.)

### B.3 Inline mechanics (Oxford comma) → compose-baked; CONFIRMED; label the lexicon compose-only

The research delivers a firm negative verdict (§3.3): **no established single-source publishing system varies inline prose mechanics — serial/Oxford comma, US/UK punctuation, quotation style — per output from one source as part of a deterministic build.** DITA profiling / AsciiDoc ifdef vary *whole elements*, never punctuation inside a retained sentence; CSL/`.bst` touch only structured citations; stylesheets cannot insert/delete a comma that is literal text in the content stream; Vale *enforces one* convention at author time. The only thing that varies the Oxford comma is an AI/NLP rewrite — a **re-composition**, not a deterministic structured-input swap.

**This closes DR-5's hard case exactly as the DR-2 reconciliation already positioned it:**
- Inline mechanics stay **compose-baked in the DR-2 `lexicons/` registry, applied at compose, baked into the IR** (one choice per artifact).
- There is **no render-time knob** — serialize is deterministic and LLM-free (§14.1); adding a non-deterministic render-time rewrite would break that property and is rejected.
- Per-venue variation ⇒ **re-compose per venue = a new `artifact-id`**. This is **already mechanically correct**: the DR-2 reconciliation put the resolved lexicon entry-id in the `artifact-id` preimage, so changing the lexicon per journal *already* yields a distinct `artifact-id` (a fresh compose over the same sources) — the safest option, matching universal practice ("authored once; per-venue ⇒ re-compose").

**Recommendation (DR-5 open q d):** the lexicon does **not** split into compose- and render-applied halves. **Explicitly label the lexicon compose-only** (a schema/docs annotation) — it has **no render side** (the DR-2 reconciliation §4 already established this, which is also why extending brand-lock `authoritative` to a lexicon scope-default is category-safe). Labeling it compose-only both (i) documents *why* per-venue inline-mechanic variation must re-compose, and (ii) forecloses any future attempt to give a lexicon a render knob that would reintroduce the exact non-determinism §14.1 forbids.

### B.4 The full per-venue-variable style/design set, each placed (DR-5 open q f)

| Style/design rule | Structured handle? | Home | Varies per venue at… |
|---|---|---|---|
| fonts / colors / margins / columns / layout | yes (Pandoc variables/template/reference-doc) | **Presentation** (existing) | serialize (deliverable-id) |
| syntax-highlight style | yes (`--highlight-style`) | **Presentation** (existing) | serialize (deliverable-id) |
| citation / footnote / bibliography format | yes (CSL-JSON + `.csl`) | citation DATA → **IR** (compose); STYLE → **Presentation `csl`** (new field) | serialize (deliverable-id) |
| required / forbidden sections; section tightening | yes (structural) | **Platform** per-format projection (existing) | reconcile (fitted-id) |
| must-fit length limits (abstract ≤N words) | yes (numeric) | **Platform** hard limit (existing) | reconcile gate (§16) |
| which whole elements appear per output | yes (structural) | **reconcile reshape** `adapt/split` (existing, §16) | reconcile (fitted-id) |
| Oxford comma / US-UK punctuation / quotation style | **no** (literal inline prose) | **lexicon @ compose** (DR-2, compose-only) | **compose only ⇒ re-compose** (artifact-id) |

Everything with a structured handle varies at render (Presentation or Platform/reconcile); the one thing with no structured handle (inline mechanics) stays compose-baked. This is the boundary principle applied end-to-end.

---

## Part C — style-file references + output-type compatibility + CSS mechanics

### C.1 The overridable reference to a hand-crafted style file ALREADY EXISTS — do NOT reinvent (CONFIRMED)

Verified against `presentations/_schema.yaml` + `pipeline/presentation.py` + §5.3:

- Presentation carries `css` (ordered `list<text>` of stylesheet paths), `reference_doc` (per-writer `map<text>`), `template` (per-writer `map<text>`), `variables` (`map` — fonts/margins + grow-hook), `highlight_style`, `pdf` (engine+opts).
- Presentation is a discrete-registry rendering dimension resolved over the M2 spine (§12.3: L2/L3/L5/L6) — i.e. **overridable per workspace / recipe / run** exactly as the maintainer asked.
- `lower(presentation, writer, output_type)` (`pipeline/presentation.py:186`) emits `--css=<path>` / `--reference-doc=<path>` / `--template=<path>` flags and hashes each file as a content-addressed asset (`PresentationAsset.content_hash`, folded into the §17/FR7.1 serialize-inputs preimage).

**The pipeline already holds a *reference* to a hand-crafted style file (path + content hash) and applies it at serialize — it does not generate or abstract it.** This is precisely the DON'T-OVERDESIGN target. **No new mechanism for the style-file reference itself.** The only additive field is `csl` (Part B), which is a *citation*-style file, categorically distinct from a visual skin.

### C.2 Output-type ↔ style-file compatibility — does NOT exist today; the one genuinely-new (small) Part-C mechanism

**Verified negative.** Today `lower()` gates each style lever by writer-family and **silently drops** an inapplicable one:

- `css` applied only `if writer in CSS_WRITERS` (the html/epub/html-slide family) — `pipeline/presentation.py:242`;
- `reference_doc` only `if writer in REFERENCE_DOC_WRITERS` (`{docx, pptx, odt}`) — `:253`;
- `template` per-writer, `if writer not in NO_TEMPLATE_WRITERS` (`{pptx}`) — `:248`;
- `pdf` only `if output_type in PDF_OUTPUT_TYPES` — `:258`.

A css supplied for a docx render is **silently inapplicable — explicitly NOT an error**, asserted in `tests/test_presentation.py:150-152`:
```
# a docx writer takes no css — the lever is silently inapplicable (not an error)
assert lower(pres, "docx", "docx").flags == ()
assert lower(pres, "docx", "docx").assets == ()
```
The only error path today, `dispatch.capability_check` (`pipeline/dispatch.py:137`), checks that an *internal* target names a runnable writer (`capability-infeasible`) — nothing about a Presentation-lever × output-type mismatch. **So the maintainer's wanted "error on css-for-docx" is genuinely new — but the compatibility TABLE already exists implicitly as those four writer-family constants; the fix is to turn the silent drop into a surfaced result.**

**The one subtlety that governs the design — PD1 cross-target brands.** A Presentation is "one brand's *complete cross-target* look" (PD1): a single entry legitimately carries `css` (for its html deliverable) **and** `reference_doc` (for its docx deliverable) **and** `template` (for pdf) simultaneously. So "presentation carries css, this deliverable is docx" is the *normal* case for a cross-target brand — it must **not** error (the docx deliverable correctly consumes the reference_doc; the css correctly serves the html sibling). A naive "css set + writer is docx ⇒ error" would false-positive on every brand pack.

**Recommendation — the minimal, correctly-scoped compatibility check.** Fire only on the case the maintainer actually wants to catch: **a non-`plain` Presentation that lowers to an all-inapplicable result for the requested output-type** — i.e., the user attached a non-plain look, and *none* of its levers can be consumed by this deliverable's output-type. Concretely: at (or just before) `lower()`, when `presentation_id != "plain"` yet the lowered `RenderInputs` for this `(writer, output_type)` is empty (no flags/assets/engine beyond the target's own), surface a typed result (e.g. `presentation-output-incompatible`, tier generation).
- This **precisely** catches css-only-Presentation → docx (the whole look silently vanishes) while a css+reference_doc brand pack → docx (reference_doc applies) never triggers.
- **Severity:** the maintainer asked for an **error**. Recommend **block** for this precisely-scoped case, consistent with the existing `capability-infeasible` (warn|block, §17). It is a §3.1-clean surfacing of the *consequence of the user's own config* (they paired a look with an output-type that cannot honor it), not a system override. **Flag block-vs-warn to the maintainer gate** — a case could be made for warn (advisory, user-deviates) to stay maximally non-overstepping; the scoping above makes either safe.
- **This is a few lines** — replace the silent drop with the "did the non-plain look contribute anything?" check. No new schema, no new registry.

### C.3 Per-format skinning map — the Presentation field set covers every family (CONFIRMED, one new field)

| Output family | Style knob | Presentation field | Status |
|---|---|---|---|
| HTML / HTML-slides / EPUB | stylesheet | `css` (→ `--css`, CSS_WRITERS) | exists |
| docx / pptx / odt (Office/ODT) | reference doc | `reference_doc` (→ `--reference-doc`, REFERENCE_DOC_WRITERS) | exists |
| PDF-via-LaTeX | LaTeX template + vars | `template[latex]` (→ `--template`) + `variables` (→ `-V`) + `pdf` (engine+opts) | exists |
| all template-based writers | fonts/margins/vars | `variables` (the PD2 grow-hook) | exists |
| **citations (all writers)** | **CSL style file** | **`csl` (→ `--csl --citeproc`)** | **new (Part B) — the only gap** |

The visual/skin field set has **no gap**. The one genuinely-new field is `csl`, which is a citation-style file (not a skin) — and it is additive, PD2-consistent, applied at serialize, hashed as an asset.

### C.4 CSS packaging (inline-in-HTML vs external file) — DEFER as an implementation detail; note current behavior

Current serialize behavior (verified): css rides as `--css=<path>` flags (`pipeline/presentation.py:244`) — Pandoc's default with `--css` is an **external `<link>` to the stylesheet**, not inlined (self-contained/embedded output requires `--embed-resources`/`--self-contained`, which the pipeline does not set today). So **today = external linked stylesheet.** Whether to inline (self-contained HTML) is a per-run choice expressible later via the PD2 `variables`/flag grow-hook with **no schema change** — recommend **defer** it as an implementation detail, noting the current external-link behavior so the planner does not assume inlining.

### C.5 CSS / CSL interaction in HTML — they compose; no conflict

Yes — **citeproc (CSL) emits citation/bibliography MARKUP** (Pandoc renders `.csl-entry` / citation spans+divs), and **CSS then styles that markup.** They are orthogonal and composable: CSL owns the *structure/content* of the citation (author-date vs numeric vs footnote), CSS owns its *visual styling*. Both are Presentation levers (`csl` + `css`), both applied at serialize, non-conflicting. **Resolve: no conflict — CSL structures, CSS skins.** One caveat to flag: the serialize-owned provenance-strip filter (§17, R-4) strips grounding provenance attrs (`data-fact`/tier classes) for public writers — it targets grounding provenance, **not** published CSL citation markup; confirm the strip logic keys on `data-fact`/tier and never catches `.csl-*` citation spans (it does not today, but it is a one-line planner check when `csl` lands, since citations are *published* content, unlike grounding).

### C.6 External-render caveat — per-venue style flows via the RI14 payload (design-complete; wiring is planner)

Verified: `pdf`, `epub`, `pptx` render-targets are `side: external` (they emit the layer-3 payload, not final bytes; GAP-1 resolved this internal↔external split). PD8 already rules: "RenderInputs ride the identical channel internally and, for `side: external`, fold into the **layer-3 contract payload** (§17)"; RI14 lists the payload's required "Pandoc version + writer + engine + reference-doc, all pins." So for external targets, per-venue style — **css (epub), reference-doc, template, pdf-engine, and the new `csl`** — must travel in the RI14 sidecar (with the asset content-hashes, and resolvable paths or bytes) so the external actor applies them.

**Verified gap-adjacent (flag for planner, not new design):** the current `dispatch()` external branch returns only `payload_ast` (`pipeline/dispatch.py:196-203`), not the lowered flags/assets — but external rendering is "deferred in v1 (gate step 3)" per the module docstring, and the *design* (PD8 + RI14) already specifies the flags+assets belong in the payload. So **per-venue style for external targets is design-complete; the RI14-payload-completeness wiring (carry the lowered RenderInputs + asset references, including `csl`, into the external payload) is a planner item.** No new design decision — just ensure the external actor receives what the internal path applies.

---

## Integration + orthogonality (whole-system fit)

### The nine axes, the cascade, identity — what each piece touches

| Piece | Axis / surface it uses | New axis? | New cascade rung? | New identity surface? |
|---|---|---|---|---|
| DR-4 typed slots | **Format** `parts` (enriched) + **IR** `constraints?`/`type` (already reserved) | no | no (rides Format's existing M2-compose binding) | **no** — `parts` already enters `artifact-id` via Format |
| DR-4 venue tightening | **Platform** per-format projection (existing) + Platform hard limits → §16 | no | no (merges below L5, like advisory constraints) | no |
| DR-4 journal bundle | a **recipe** (existing) | no | no | no |
| DR-5 look | **Presentation** (existing) | no | no | no |
| DR-5 citation DATA | **IR** `references` (Pandoc-native, additive) | no | no | **no** — compose content, rides body-blind content identity |
| DR-5 citation STYLE | **Presentation** `csl` (new field) | no | no | no — rides `deliverable-id`'s existing `presentation` coordinate; defaults empty (PD5 zero-churn) |
| DR-5 inline mechanics | **lexicon @ compose** (DR-2, compose-only) | no | no | no new (DR-2 already put the lexicon id in the preimage) |
| Part C compatibility check | pre-serialize validation over the existing writer-family table | no | no | no (not an identity input) |

**Net new identity surface across the entire pass: ZERO.** Everything rides existing coordinates — a strong orthogonality result and a deliberate contrast with DR-2/DR-3 (two new `artifact-id` components each).

### No axis is re-owned; no blur

- **Format** still owns genre structure — now *typed*; it gains no platform coupling (venue tightening stays on Platform, honoring Q4).
- **Platform** still owns venue/limits/routing — it now projects *structural* slot-tightenings through the *same* per-format projection it already uses for advisory constraints; no new kind of thing.
- **Presentation** still owns deterministic style @ serialize (PD6) — citation-style IS deterministic style @ serialize (citeproc is deterministic, LLM-free, §14.1), so `csl` sits inside PD6's charter, not outside it. Presentation styles what exists (the structured citations); it invents nothing.
- **Lexicon** (DR-2) stays compose-baked inline mechanics — now explicitly labeled compose-only.
- **Grounding ledger vs citations — orthogonal, not blurred.** The ledger is *internal fact provenance* (source repo/commit/tier, stripped from public output, EXTRACTED-floor-gated). The `references` block is *published bibliographic attribution* (CSL-JSON, formatted by CSL into visible citations). Different objects, different lifecycles, different output treatment (stripped vs published). They coexist: when a source is a citable external work (a `research-papers` content-kind, §6.1), the compose agent may populate *both* — a ledger entry for provenance and a references entry for the published citation. Keep them separate schemas; register this dual-population as a compose-agent contract detail (§27.4), not a schema merge.

### One-file-add preserved

A new typed Format (research-paper with slots) = one file; a new journal Platform (with per-format tightenings) = one file; a new journal Presentation (visual + `csl`) = one file; a new slot `type` or constraint kind = one schema-enum edit; a `.csl`/`.css`/`reference_doc` asset = a referenced file. Every extension is one file.

### Cascade order is correct

Structural conformance at compose/Review 1 (platform-neutral, once per artifact) → venue structural tightening via Platform per-format projection below L5 at M2-render → must-fit limits at the §16 reconcile terminal gate → visual + citation style at serialize (Presentation lowering, `--citeproc --csl` at the writer step). Compose-baked inline mechanics precede all of it (lexicon @ compose). No rung is added; nothing resolves out of order.

### Interactions to flag (with the outline and the lexicon)

1. **Outline (DR-3) × DR-4 typed slots — DEFERRED together, consistently.** DR-3 v1 is single-part, holistic Markdown, no machine section-parse, `constraint?` **deferred**. DR-4 typed slots are inherently multi-part. So **an outline driving a typed multi-part template is deferred** — consistent with DR-3 F6 (v1 outlines drive/emit single-part flat-body formats only). Directly-selected Format+recipe artifacts get typed slots now; the outline×typed-multi-part-template interaction lands later.
2. **The DR-3-deferred outline `constraint?` and DR-4's per-slot `constraints` are the SAME concept in two places** (outline sections vs Format parts). The typed-slot vocabulary designed here (type enum + constraint menu + `error/warning/info` severity) is the **shared vocabulary** both will use. DR-4 realizes it at the *declared, structured* Format-parts level (tractable now); the outline-section case remains deferred because it needs DR-3's sentinel-grammar + a section-grouping shape (DR-3 F1/F5). Do not let a later pass reintroduce free-text-under-`##`. This unifies the two deferrals under one vocabulary — fewer special cases.
3. **Nested-in-prose typed slots (a figure *inside* a section body) are deferred** with the same DR-3 machinery gap (machine section-parse). v1 DR-4 typed slots operate at the **part level** (a typed part: `{role: results-table, type: table, …}`), not arbitrarily nested inside a Markdown `body`. This keeps DR-4 and DR-3 on one consistent deferral boundary and avoids a parallel parsing subsystem — honoring DON'T-OVERDESIGN.
4. **Lexicon (DR-2) × DR-5** — confirmed compose-only; per-venue inline-mechanic variation ⇒ re-compose (already correct via the lexicon-in-preimage mechanism). Label it compose-only.
5. **Per-part override layer (§26/T7) × DR-4 `constraints?`** — DR-4 makes the IR `constraints?` field real (per-slot structural constraints), while T7's deferred per-part *value* override (where a part layer sits in the cascade) stays open. These are orthogonal (structural conformance vs value binding) but touch the same IR field — register the interaction so the T7 design accounts for the now-populated `constraints?`.

---

## Residual risks + maintainer-gate items

**Must reach the maintainer gate (design decisions above the planner):**

1. **Ratify the DR-4 home:** content template = enriched **Format `parts`** (string|typed-slot-map) + the now-real **IR `constraints?`/`type`**, with venue tightening on **Platform per-format projection** and the journal bundle as a **recipe**. Confirm NOT a new construct/registry/axis and NOT Presentation's `template`.
2. **Ratify the typed-slot vocabulary** (`type` enum; `?`/`*`/`{n,m}` cardinality; the constraint menu; the `error/warning/info` severity mapped onto §16-block / §8-advisory) and its enforcement at compose/Review 1. Confirm the additive `parts`-element string|map form (backward-compatible, no migration).
3. **Ratify the DR-5 citation split:** an additive **Pandoc-native `references` (CSL-JSON) block + `[@key]` in the IR** (compose, no new identity surface) and a new **Presentation `csl` lever** (render). Ratify the **citeproc-at-the-writer-step** placement (NOT at RI7) to preserve PD5's presentation-independent AST — this is the load-bearing serialize detail.
4. **Confirm the inline-mechanics posture:** compose-baked, per-venue ⇒ re-compose; **label the lexicon compose-only**. (Closes DR-5's hard case; no render knob.)
5. **The Part-C compatibility check — block vs warn.** The maintainer asked for an error; the recommendation is a **block** on the precisely-scoped "non-plain Presentation lowers to nothing for the requested output-type" (which protects PD1 cross-target brands from false positives). Confirm block, or downgrade to warn — either is safe under the scoping.

**Planner-facing (mechanism within the ratified frame):**

6. Enrich `formats/_schema.yaml` `parts` (string|typed-slot-map) + the IR part shape (`type`, real `constraints?`); wire the compose/Review-1 conformance check to the existing severity results. Verify `union`-on-`parts` stays a schema error (§12.4) after the element-type change.
7. Add `presentations/_schema.yaml` `csl` (single style-file path); lower to `--csl --citeproc` at the writer step; hash as an asset into the FR7.1 preimage. Verify the provenance-strip filter never catches `.csl-*` citation markup.
8. Turn the `lower()` silent-drop into the scoped compatibility surfacing (a typed result); reuse the existing writer-family constants as the authoritative compatibility table.
9. Carry the lowered RenderInputs + asset references (including `csl`) into the **RI14 external payload** (`dispatch` external branch) so `side: external` (pdf/epub/pptx) receives per-venue style. Reference GAP-1's internal↔external split.
10. Register in §27.3/§27.4: the unified `constraints`/`constraint?` vocabulary (DR-4 ↔ DR-3 deferred outline sections); the deferred nested/section-parse typed slots; the deferred outline×typed-multi-part-template interaction; the T7 per-part-override × now-populated `constraints?` interaction; and the compose-agent dual-population contract (grounding ledger + `references`).

**Honest residual risks:**

- **R1 — the `references`/`csl` path assumes Pandoc citeproc parity** at the pinned binary/api-version. Verify `Cite` elements + `references` metadata survive the pinned `-f markdown -t json` unresolved, and that `--citeproc --csl` at the writer step is lossless — a §27.2-style pin gate before build.
- **R2 — the compatibility check's scoping.** "Non-plain Presentation lowers to nothing" is the right signal for css-only→docx, but a Presentation that sets ONLY `variables` (which affect template-based writers unevenly) against docx could lower to a thin/empty result and trip the check; the planner must define "contributes nothing" against the actual per-writer lever applicability, not just non-emptiness of the flags list.
- **R3 — journal-as-recipe ergonomics.** Modeling a journal as a cross-axis recipe is orthogonally correct but pushes the "one journal = one selection" convenience onto recipe authoring; if the maintainer wants a single named "journal template" object, that is a recipe-naming/sugar question (like the deferred brand pack, §26), not a new axis — register it rather than inventing a construct.
- **R4 — DON'T-OVERDESIGN adherence.** The temptation is a full nested typed-slot grammar with machine parsing; this design deliberately caps v1 at part-level typed slots and defers the nested/section-parse case to DR-3's machinery. Hold that line at the adversarial pass.

*End of initial. Verdict: a REUSE-dominated pass with zero new identity surface — DR-4 templates ride enriched Format `parts` + the reserved IR `constraints?` + Platform projection + recipe (one small typed-slot vocabulary is the only new thing); DR-5 places look on the already-solved Presentation, adds a small Pandoc-native citation handle in the IR plus a `csl` Presentation lever, and confirms inline mechanics stay compose-baked (lexicon labeled compose-only); the overridable style-file reference already exists on Presentation (do not reinvent), and the only new Part-C mechanism is turning the existing silent-drop writer-family gate into a scoped compatibility error. No code, no plan; the adversarial pass runs next.*
