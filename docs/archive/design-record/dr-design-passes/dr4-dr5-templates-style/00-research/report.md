# DR-4 & DR-5 — External grounding pass: single-source, multi-output publishing (templates + per-output style)

**Author:** docs-researcher (external-grounding pass)
**Date:** 2026-07-17
**Scope:** GROUND + MAP only. No design of the pipeline's template/style solution (a later architect pass owns that).
**Method:** primary specs/docs fetched or searched. Every claim tagged **[VERIFIED]** (primary page fetched via WebFetch), **[VERIFIED-snip]** (snippet returned from a primary/official domain in search, full page not fetched), or **[INFERRED]** (my synthesis / secondary source / logical extrapolation flagged for the architect).

The two problems share ONE external landscape — **single-source, multi-output publishing** — and one driving example: the SAME academic paper published in three journals differing in **template** (structure), **design** (fonts/colors), and **style** (footnote format, Oxford comma). DR-4 asks for a *structure* construct (typed slots + non-text + constraints) that must not blur Format/Platform/Presentations; DR-5 asks *where style falls* on the pipeline's content(compose)↔render split, given some style must vary per-output from one shared IR.

---

## 1. Sources

Fetched (primary page content read) — **[VERIFIED]**:
- Portable Text specification — https://www.portabletext.org/specification/
- DITA v1.0 Architectural Spec, "Information typing" — https://docs.oasis-open.org/dita/v1.0/archspec/infotypes.html
- ProseMirror Guide (Schema section) — https://prosemirror.net/docs/guide/
- Contentful, "Available validations" — https://www.contentful.com/help/fields/available-validations/
- CSL Primer ("An Introduction to CSL") — https://docs.citationstyles.org/en/stable/primer.html

Primary/official-domain snippets (search-returned, page not fully fetched) — **[VERIFIED-snip]**:
- DITA 1.3 Spec (OASIS) incl. "combining, extending, and **constraining** document types" — https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/... and https://docs.oasis-open.org/dita/dita/v1.3/cos01/part2-tech-content/...
- DITA "Conditional processing (profiling)" / DITAVAL — https://docs.oasis-open.org/dita/dita/v1.3/os/part1-base/archSpec/base/condproc.html ; https://docs.oasis-open.org/dita/v1.2/os/spec/common/about-ditaval.html
- Sanity "Validation" + "Block type" — https://www.sanity.io/docs/studio/validation ; https://www.sanity.io/docs/studio/block-type
- Contentful "Content types" (CMA) — https://www.contentful.com/developers/docs/references/content-management-api/content-types/
- Asciidoctor "Converters" + CLI man page (backends, ifdef) — https://docs.asciidoctor.org/asciidoctor/latest/convert/
- Vale prose linter — https://vale.sh/ ; https://github.com/errata-ai/vale
- CSL 1.0.2 Specification — https://docs.citationstyles.org/en/stable/specification.html
- Elsevier `elsarticle` / IEEEtran / PaperShell (LaTeX retargeting) — https://ctan.org/pkg/elsarticle ; arXiv IEEEtran HOWTO https://arxiv.org/html/2404.03595v1 ; https://github.com/sylvainhalle/PaperShell

Secondary / weak (used only for orientation, flagged) — **[INFERRED]**:
- DocBook "separation of content and presentation" (Wikipedia/grokipedia/nwalsh design article) — the *principle* is well-established but I did not fetch a DocBook TDG primary page; treat the specific wording as secondary.
- Markup AI "Content Guardian" blog (AI rewrite that inserts/removes Oxford commas) — vendor blog, weak; used only as an existence-proof of the "AI text-transform" class.

**Could-not-fully-verify** items are collected in §5.

---

## 2. DR-4 findings — the template / typed-slot / constraint vocabulary catalog, and the line each system draws

### 2.1 The vocabulary catalog (answers the maintainer's "I don't know the vocabulary")

Across the surveyed systems the reusable-template vocabulary converges on a small set of concepts. Consolidated catalog:

**(a) The container / skeleton unit**
- DITA: a **topic type** (`concept`, `task`, `reference`, generic `topic`) = a typed skeleton for one kind of information; **maps** assemble topics. **[VERIFIED]**
- ProseMirror: a **node type** with a **content expression** = a typed container declaring what children it may hold. **[VERIFIED]**
- Portable Text: the top-level **array** of **blocks**; each block has a `_type`. **[VERIFIED]**
- Contentful/Sanity: a **content type** / **document** = a named set of typed fields. **[VERIFIED / VERIFIED-snip]**

**(b) Typed slots / fields — the "slot type" vocabulary**
- Contentful **field types** (fetched): `Symbol` (short text), `Text` (long text), `RichText`, `Number`, `Decimal`, `Date`, `Boolean`, `Location`, `Asset` (media), `Entry` (reference/link), `Object` (JSON), and the *array* variants `Multiple symbols / Multiple entries / Multiple assets`. **[VERIFIED]**
- Sanity **schema types**: `string`, `text`, `number`, `boolean`, `date`/`datetime`, `image`, `file`, `reference`, `array`, `object`, `slug`, plus the rich-text `block` type; custom object types are first-class. **[VERIFIED-snip]**
- ProseMirror **attrs**: each node/mark declares an `attrs` object; each attribute is a named JSON-serializable value. **[VERIFIED]**
- Portable Text: a **block** carries `style`, `children` (spans), `markDefs`, `listItem`, `level`; a **span** carries `text` + `marks`. **Custom blocks can be any `_type` and carry any data.** **[VERIFIED]**

**(c) Inline / mark vocabulary (styling + annotation within prose)**
- Portable Text splits marks into **decorators** (simple flags: bold, italic) vs **annotations** (`markDefs` carrying data: links, references). Separating the definition (`markDefs`) from the reference (span `marks`) lets multiple spans share one annotation without duplication. **[VERIFIED]**
- ProseMirror: **mark types** (emphasis, code, link) with optional `attrs` (e.g. link target). **[VERIFIED]**

**(d) Non-text element kinds (tables, figures, callouts) — the DR-4 "non-text slots"**
- DITA: dedicated typed elements — `<table>` (CALS/simpletable), `<fig>` + `<image>` + `<title>` (figure with caption), `<note>` (callout/aside), `<step>`/`<cmd>` (procedure). These are *content* elements, not styling. **[VERIFIED-snip]**
- Portable Text: non-text elements are **custom blocks** — "An image block, a code block, an embedded video, or a call-to-action are all custom blocks," each `_type` + arbitrary data. **[VERIFIED]**
- ProseMirror: non-text elements are **nodes** (e.g. `image` node with `src`/`alt`/`title` attrs; table nodes via prosemirror-tables). **[VERIFIED]**
- Contentful/Sanity: non-text elements are **Media/Asset fields**, **references** to other entries, or (Sanity) custom objects embedded in the block array. **[VERIFIED / VERIFIED-snip]**
- (Cross-cutting) AsciiDoc/reST call these **admonitions** (NOTE/TIP/WARNING) and **figure/image macros** — same "callout + captioned figure" primitives. **[VERIFIED-snip / INFERRED]**

**(e) Constraint vocabulary — required/optional, cardinality, ordering, length, conditional**
- **Cardinality + ordering (ProseMirror content expressions)** — the most explicit grammar found: sequences like `"heading block+"`, with operators `+` (one-or-more), `*` (zero-or-more), `?` (zero-or-one), exact/range counts `{2}`, `{1,5}`, `{2,}`, and grouping via a node **`group`** name. This directly encodes "≥1 abstract, an ordered methods-then-results, ≤N figures." **[VERIFIED]**
- **Required vs optional (ProseMirror)** — an `attrs` entry **with a default is optional; without a default it is required** (creating the node without it raises an error). **[VERIFIED]**
- **Required / size / range / enum / regex / reference-type (Contentful)** — validations (fetched): **Size** (min/max on text/array), **Predefined values** (enum/`in`), **Regex** (pattern match, with built-in patterns for email/URL/date/phone/zip/time), **Date range**, **Number of items** (array min/max), **Number range**, **Asset file size**, **Image dimension**, **Type** ("accept only specified content type(s)" for a reference/media field). Field `required` and `unique` are standard field settings; field **ID must be unique** within the content type. **[VERIFIED]**
- **Required / length / pattern / cross-field / severity (Sanity)** — validation via `Rule`: `required()`, `min()`, `max()`, `length()`, `regex()`, `uppercase()/lowercase()`, `email()`, `custom()` (arbitrary logic), `valueOfField()` (rule depending on a **sibling** field). Crucially Sanity has **severity tiers**: `error()` (blocks publish) vs `warning()` vs `info()` (do not block) — a soft/advisory-constraint precedent. **[VERIFIED-snip]**
- **Constraint by specialization/constraint-modules (DITA 1.3)** — DITA 1.3 defines mechanisms for "combining, extending, and **constraining** document types": a **constraint module** can make an optional element **required**, **remove** (forbid) elements, or restrict attribute values — i.e. tighten a base template into a stricter variant while remaining processing-compatible. This is the closest external analog to "journal A requires a structured methods section; journal B forbids an acknowledgements section." **[VERIFIED-snip]**

**Consolidated constraint-kind list for the architect** (union of the above): `required | optional`, `min/max length`, `min/max count (cardinality: 0..1, 1, 1..N, N..M)`, `ordering (sequence)`, `enum / predefined-values`, `regex/pattern`, `numeric range`, `date range`, `reference-target-type`, `asset dimension/size`, `conditional (present-if / audience-scoped)`, and a **severity** axis (`error`=block vs `warning`/`info`=advisory).

### 2.2 Flexibility (optional / repeatable / conditional slots) — the "scaffold, not a mold" requirement

Every system provides flexibility along the same three levers, and they map cleanly to DR-4's "flex with content/outline length + added/removed elements":
- **Optional slots** — ProseMirror `?`; Contentful/Sanity `required` unset; DITA base elements that a constraint module has *not* made required. **[VERIFIED / VERIFIED-snip]**
- **Repeatable slots** — ProseMirror `+`/`*`/`{n,m}`; Contentful array + "Number of items" min/max; Sanity `array` + `min()/max()`. This is exactly "a variable number of figures/authors/sections." **[VERIFIED]**
- **Conditional slots** — DITA **profiling** (`@audience`/`@platform`/`@deliveryTarget`/`@props`) selected by a **DITAVAL** at build; AsciiDoc `ifdef::attr[]`; Contentful/Sanity conditional-field UI + `custom()`/`valueOfField()` logic. Conditional inclusion is the standard "add/remove an element per output" mechanism — but note (important for DR-5, §3) it toggles **whole elements**, never inline prose punctuation. **[VERIFIED-snip]**

Takeaway for DR-4: the "template must flex" requirement is a **solved shape** — it is `?`/`*`/`{n,m}` cardinality + optional + conditional-inclusion. None of these systems treats a template as a rigid mold; all are content-model grammars with cardinality operators.

### 2.3 Where each system draws the line: template/structure vs stylesheet/presentation vs content-model/schema

This is the DR-4 "where's the line" question. The strong, near-universal finding: **the reusable "template" in structured-content systems is a CONTENT-STRUCTURE/SCHEMA artifact, and it is deliberately kept SEPARATE from the presentation stylesheet.** The word "template" is overloaded across ecosystems and lands on different sides:

| System | "Template" = structure/schema side | "Stylesheet" = presentation side | Where the line sits |
|---|---|---|---|
| **DITA** | topic types + specialization + **constraint modules** (which elements, required/optional, order) — semantic structure | XSLT/XSL-FO/PDF plugin transforms + DITAVAL flagging styles | Structure/semantics in the DITA source; ALL visual formatting in the output transform. Content is presentation-agnostic. **[VERIFIED-snip]** |
| **DocBook** | the DocBook schema/DTD elements (`<chapter>`, `<sect1>`, `<table>`) — "meaning, not presentation" | DocBook **XSL stylesheets** → HTML/FO/PDF/EPUB | Explicit doctrine: semantic markup separated from visual representation via stylesheets. **[INFERRED — secondary sources]** |
| **Portable Text** | the block/span/custom-block **schema** (what types exist, their fields) | **serializers** (React/HTML/PDF/plain-text) chosen at render | "Separates content structure from presentation, making the same content renderable as React components, HTML strings, PDFs, or plain text." Line is at the serializer. **[VERIFIED]** |
| **ProseMirror** | the **schema** (nodes/marks/content-expressions/attrs) — allowed structure | CSS + the editor/DOM `toDOM` view | Schema is structure-only; styling is view-layer. **[VERIFIED]** |
| **Contentful / Sanity** | the **content model** (fields + types + validations) — pure data schema, presentation-agnostic by design | left entirely to the consuming front-end (React/etc.) | Headless CMS: the model has NO presentation; rendering is 100% downstream. **[VERIFIED / VERIFIED-snip]** |
| **LaTeX** | (the outlier) the **document class** bundles structure AND style | — same artifact — | LaTeX is the ONE system where "template" = class = structure + style TOGETHER (see §2.4). |

**Load-bearing conclusion for DR-4's "where is the line" (open question a):** In the structured-content world (DITA/DocBook/Portable Text/ProseMirror/headless CMS), a **content template is a SCHEMA / content-model artifact — it is NOT a stylesheet.** It declares *which typed slots exist, their kinds, their cardinality/constraints, and their order* — and it is deliberately separated from the presentation stylesheet, which is a *different* artifact applied at render. This is the direct external validation of DR-4's hard constraint that a *content* template must be disambiguated from Presentations' Pandoc `template`/`reference_doc` (a *visual* template): the whole structured-content field already draws exactly that line and keeps the two artifacts apart (DR-4 open question e). The naming collision DR-4 flags is a real, industry-wide overload of the word "template."

### 2.4 LaTeX document classes + journal submission templates (DR-4 open q5) — the concrete retargeting case

- A LaTeX **document class** (`\documentclass{...}`) specifies **BOTH structure and style**: available sectioning/`\maketitle`/abstract/keywords structure, page layout (columns, margins), fonts, and — via the companion BibTeX **`.bst` style** (or `natbib`/`biblatex` style) — the citation/reference format. Example: **`elsarticle.cls` is "based upon the standard `article.cls`" and adds Elsevier's `1p/3p/5p` layout models** and `natbib`; **IEEEtran** "can produce conference, journal and technical note papers by a suitable choice of class options" and needs "no font adjustment." **[VERIFIED-snip]**
- **Retargeting the SAME manuscript to a different journal** = swap the **document class** (and its `.bst`) while keeping the manuscript body (`\section{}`, `\cite{}`, prose, `\begin{figure}`) essentially constant. The **PaperShell** template exists precisely to "switch between LaTeX document classes (IEEEtran, acmart, llncs, elsarticle, lipics, …) **without rewriting the paper.**" **[VERIFIED-snip]**
- The catch, and why LaTeX is a good stress-test for DR-4/DR-5: because the document class bundles structure+style, a journal switch changes structure (required/forbidden sections, abstract length norms), design (fonts/columns), AND style (citation/footnote format from the `.bst`) **at once** — but the *author's structured inputs* (sectioning commands, `\cite{key}` keys pointing at a `.bib`) stay fixed. The citation/footnote variation is delivered by swapping the **`.bst` style over structured `\cite` keys** — the BibTeX analog of CSL (§3.2), a **render-time, structured-input** swap. The *inline prose* (whether the author wrote "a, b, and c") does **not** change when you swap the class. This is the same split DR-5 discovered (§3.4).

Answer to DR-4 open question (f) "is a journal a Platform, and are template requirements per-Platform/per-Format?": external systems do NOT settle this for you — LaTeX collapses journal = class = {structure + style + design}. The pipeline's model factors those apart (Format/Platform/Presentations/lexicon), so a single "journal" maps onto SEVERAL pipeline axes at once (see mapping table §4), not one. This is a modeling decision for the architect, not an externally-dictated fact — flagged **[INFERRED]**.

---

## 3. DR-5 findings — single-source multi-output, the CSL render-time answer, and the inline-mechanics verdict

### 3.1 How single-source multi-output systems produce venue-specific outputs, and which layer decides which style

Surveyed mechanisms, each classified by the layer at which venue variation is decided:

| System | Single-source → multi-output mechanism | Variation decided at… |
|---|---|---|
| **DITA / CCMS** | one topic set + **maps**; per-output **DITAVAL profiling** (include/exclude/flag whole elements by `@audience`/`@platform`/`@deliveryTarget`); output transforms (HTML/PDF/EPUB) | **CONTENT-selection** at build (which elements) + **RENDER** (transform = look). Inline prose is authored once. **[VERIFIED-snip]** |
| **Sphinx** | one reST/MyST source → many **builders** (html/latexpdf/epub/man); `.. only::` directives for conditional content; theme/CSS for look | RENDER (builder + theme) + content-selection (`only`). **[INFERRED — well-known, not fetched]** |
| **Asciidoctor** | one AsciiDoc → **backends** (`html5`, `docbook5`, `pdf`, `manpage`, epub); `ifdef::attr[]` conditional content; attributes overridable at CLI | RENDER (backend) + content-selection (`ifdef`). **[VERIFIED-snip]** |
| **Pandoc** | one Markdown/AST → any **writer**; per-output **template**/`reference-doc`/CSS/variables; **citeproc** for citations | RENDER (writer + template + CSL style). This is the pipeline's own model. **[VERIFIED-snip]** |
| **LaTeX** | one manuscript body → swap **document class** + `.bst` | RENDER (class/style) + structured citation-key resolution. Inline prose authored once. **[VERIFIED-snip]** |

**Cross-system finding:** venue variation is delivered at the **render/presentation layer** for everything whose input is **structured** (which elements appear = profiling; how citations look = CSL/`.bst`; fonts/columns/look = stylesheet/class/theme). The **content/authoring layer** owns everything expressed as **raw inline prose** — and that is authored ONCE. No surveyed single-source system re-writes inline prose per output as part of its deterministic build.

### 3.2 CSL / Pandoc citeproc / Zotero — the citations & footnotes answer (DR-5 open q7)

**[VERIFIED]** (CSL primer fetched). CSL cleanly separates two independent things:
1. **Structured item metadata** (CSL-JSON): authors, year, title, journal, volume, issue — format-agnostic, static.
2. **A swappable style file** (CSL XML): declares "author-date" vs "note/footnote" vs "numeric" formatting, plus locale files.

A CSL **processor** (Zotero, citeproc-js, Pandoc's built-in citeproc) consumes {metadata + style + locale} and generates the formatted citation **at processing/render time**. The SAME item renders as `(Smith, 1997)` under an author-date style, `[3]` under numeric, or a full footnote under a note style — **"solely" by which style is active. Formatting is explicitly a render-time operation, not baked into the source text.** Pandoc supports CSL and can render any style from the Zotero Style Repository. **[VERIFIED / VERIFIED-snip]**

**Confirmed for DR-5:** footnote/citation format IS render-time and per-style — **on the strict condition that the citation is carried as structured data (a `\cite`/`@key` + CSL-JSON), not as literal footnote prose in the body.** This validates DR-5's own diagnosis: the render-time path "works when the style's input is structured in the IR." The BibTeX `.bst` (LaTeX) is the same pattern (§2.4). The architect's render-time footnote/citation path (DR-5 open q b) has a direct, mature external template: **structured citations in the IR + a swappable per-venue style resolved at serialize/render** — sitting naturally at/near the Presentations/serialize layer, keyed per fitted-or-deliverable coordinate.

### 3.3 THE INLINE-MECHANICS VERDICT (DR-5 open q8) — does anyone vary the Oxford comma per output?

**Verdict: No established single-source publishing system varies inline prose mechanics — the serial/Oxford comma, US/UK punctuation, quotation style — per output from one source as part of a deterministic build. Inline mechanics are universally a CONTENT/AUTHORING-LAYER decision, baked once.** The evidence:

- **Style-guide consensus (multiple guides):** the Oxford comma is a **pick-one-and-be-consistent authoring decision**, conventionally tied to the target's *regional English* (serial comma standard in US English, usually omitted in UK/AP). The universal advice is "choose one style and apply it consistently" — i.e. decide once for the piece, not per rendered file. **[INFERRED — secondary style guides]**
- **DITA profiling / AsciiDoc ifdef / Sphinx only:** vary **which whole elements appear**, never the punctuation inside a retained sentence. Not an inline-mechanics mechanism. **[VERIFIED-snip]**
- **CSL / `.bst`:** vary only the **citation/footnote** rendering because it is structured; they do NOT touch body-prose punctuation. **[VERIFIED]**
- **Presentation stylesheets (DocBook XSL / LaTeX class / Pandoc template/CSS):** vary **typography/layout/visual** only; a stylesheet cannot insert or delete a comma inside a sentence — the comma is literal text in the content stream, invisible to a style transform. **[VERIFIED / INFERRED]**
- **Prose linters (Vale):** ENFORCE **one** consistent inline convention (Vale can flag missing Oxford commas and run word/phrase **substitution** rules) at **authoring/CI time**. Vale is syntax-aware and format-agnostic (Markdown/HTML/reST/AsciiDoc/DITA/XML) — but it standardizes toward a SINGLE style; it is not a per-output variant generator. It proves the convention is an author-time, bake-once concern. **[VERIFIED-snip]**

**Partial exceptions / edge cases the architect should know (each falls SHORT of a clean per-output inline-mechanics swap):**
- **US↔UK spelling** is the one inline mechanic with a *near-deterministic lexical* transform: dictionary-based substitution (color↔colour, -ize↔-ise) exists (spell-checker locale + substitution tables; Vale substitution rules). This is closer to render-swappable than punctuation is, because spelling is a per-word lexical map. BUT it is still imperfect (context-sensitive words) and is normally applied as an authoring/QA normalization, not a per-output build variant. **[INFERRED]**
- The **Oxford comma specifically requires parsing sentence structure** (identifying a serial list) to insert/remove correctly — a naive find/replace cannot do it safely. The only thing that can vary it reliably is an **AI/NLP rewrite pass** (e.g. Markup AI "Content Guardian" markets rewriting content to "insert or remove commas based on your rules"; equivalently, an LLM re-compose). That is a **re-write / re-generation**, not a deterministic structured-input style swap. **[INFERRED — vendor blog, weak; treat as existence-proof only]**

**Bottom line for the architect (DR-5 open q c):** the pipeline's own DR-5 diagnosis is externally corroborated. There is **no free lunch**: nobody varies the Oxford comma per output deterministically. Your three options remain the real design space, and external practice ranks them:
1. **Compose-baked, re-compose per venue** — matches universal practice (authoring-layer decision); costs an extra compose (new artifact-id) per venue variant. Safest, aligns with "inline mechanics are authored once."
2. **A render-time text-style-transform** — only feasible via an LLM/NLP rewrite pass; this is NEW capability the pipeline explicitly does not have, and it would be non-deterministic (violating serialize's "free/deterministic" property, §14.1). External world does this only via AI rewrite (Vale enforces, doesn't per-output-vary).
3. **Compose style-neutral + apply at render** — external systems achieve this ONLY for structured inputs (citations→CSL, look→stylesheet). For *inline prose* there is no structured intermediate, so "style-neutral inline prose" has no established mechanism — flagged as the hardest path.

### 3.4 The content↔presentation boundary as a principle (DR-5 open q9)

The surveyed systems articulate a consistent boundary, and — critically for the pipeline — they place different style *kinds* on different sides:

- **DITA / DocBook:** semantic **structure + content-selection** in the source; **all visual formatting** in the output transform/stylesheet. "Meaning, not presentation." **[VERIFIED-snip / INFERRED]**
- **Portable Text / ProseMirror / headless CMS:** **schema = structure**, **serializer/CSS/front-end = presentation**; content is presentation-agnostic. **[VERIFIED]**
- **CSL / BibTeX:** **structured citation data** on the content side; **citation FORMAT** on the render/style side. Footnote/citation format is a *presentation-side* concern **because** its input is structured. **[VERIFIED]**
- **LaTeX:** the outlier that *bundles* both in the document class, but even it keeps `\cite`-key + `.bib` (structured) separate from `.bst` (style), and keeps inline prose fixed.

**The generalizable principle the architect can lean on:** a style rule lands on the **render side** iff its input is carried **structured** (a citation key, a metadata field, a semantic element, a font variable). A style rule lands on the **content/compose side** iff it is expressed as **literal inline prose** with no structured handle (the Oxford comma, spelling, quotation marks *as typed characters*). This is the same line the pipeline already draws between IR-canonical (composed once) and Presentations (per-output at serialize) — the external world validates it and, importantly, tells you *how to move a rule across the line*: **give its input a structured representation** (as CSL does for citations). Anything you cannot structure stays compose-baked.

---

## 4. Mapping onto the pipeline's content(IR/compose) vs render(Presentations) split

Mapping only — NOT designing. "Lands at" = the pipeline stage/axis where the external concept's analog already lives per `docs/design.md`.

### 4.1 DR-4 concepts → pipeline

| External concept | Pipeline analog / where it lands | Notes for the architect |
|---|---|---|
| Content template = **schema/content-model** (DITA topic type, PT/ProseMirror schema, CMS content type) — NOT a stylesheet | **Content side, compose.** Closest existing homes: **Format** (§5.2 — "owns the rhetorical structure/genre; shapes the IR's structure"; may declare `parts`) and the **IR part shape** `{part-id, role, constraints?, packaging_hint, body}` (§15). | The universal finding (§2.3) says a content template is a *structure* artifact separate from presentation — this is squarely Format/IR territory, NOT Presentations. Confirms DR-4's disambiguation from Presentations' Pandoc `template`/`reference_doc`. |
| **Typed slots / fields** (Contentful field types; PT block types; ProseMirror nodes) | **Format `parts` (`role`)** + the **IR `parts` list** (each part has a `role`). Non-text slots have no first-class home today. | Today `parts` are named sub-outputs with a `role` + Markdown `body`; there is no *typed-slot* vocabulary (table-with-columns, figure-with-caption) below the part. DR-4's ask ≈ enrich the slot/part model with typed non-text kinds. Gap to note, not fill. |
| **Non-text elements** (table/figure/callout as typed nodes/blocks) | Currently only expressible as **Markdown inside a part `body`** (IR leaves are Markdown, §15). | Markdown can carry a table/image/callout as text, but not as a *constrained typed slot* ("a table with exactly these columns", "a figure that requires a caption"). This is the real DR-4 capability gap vs Format/IR today. |
| **Constraints** (required/optional, min/max, cardinality `+/*/?`, ordering, regex, enum, ref-type, severity) | Partial homes: **IR part `constraints?`** (per-part attribute values — "per-part override *implementation* is deferred", §15/§26); **Platform hard limits + advisory norms** (§12.7) for length-type limits; the **substance floor** (§15) is a hard shape gate. | The vocabulary catalog (§2.1e) is a ready-made menu for the deferred `constraints?` field and for DR-4's per-slot constraints. Note the **severity axis** (Sanity error/warning/info) mirrors the pipeline's own **hard-limit(block) vs advisory(warn)** split (§12.7, §16) — an external precedent for the same two-tier idea. |
| **Cardinality / repeatable / optional / conditional** (`?`, `*`, `{n,m}`, DITAVAL, `ifdef`) — the "flex, not a mold" requirement | Flex on the content side = compose/Format; conditional *element* inclusion resembles **reconcile reshape** (`adapt/split`, §16) more than a style toggle. | DR-4's "flex with content/outline length + add/remove elements" ≈ ProseMirror cardinality operators. This is a *content-structure* concern (compose/Format/IR), reinforcing that a template is compose-side. |
| **Constraint-by-specialization** (DITA constraint modules make sections required/forbidden per variant) | Closest analog: a per-Format or per-Platform **projection** of constraints (Platform already projects per-format advisory constraints + reconcile-strategy defaults into the cascade, §12.3). | The "journal A requires structured methods; journal B forbids acknowledgements" case ≈ DITA constraint modules. In the pipeline this could ride Platform's per-format projection OR a Format variant — a real "where's the line" call for the architect (DR-4 q a/f). |
| **LaTeX document class** (structure + style + citation-style bundled) | **Decomposes across FOUR pipeline axes:** structure→Format/IR; visual (fonts/columns)→**Presentation**; citation format→(proposed) CSL@render; required/forbidden sections→Format/Platform constraint. | External "one journal template" ≠ one pipeline axis. The pipeline's factoring is finer than LaTeX's bundle. A "journal" is a *cross-axis bundle*, not obviously a single Platform (DR-4 q f) — flag for architect. |

### 4.2 DR-5 concepts → pipeline

| External concept | Pipeline analog / where it lands | Notes |
|---|---|---|
| **Structured citations + swappable CSL style** → per-venue footnote/citation format at render | **Render side.** Natural home is **at/near Presentation / serialize** (§17), keyed per fitted-or-deliverable coordinate — because it varies per output from one composed source, exactly like Presentation variables do. Requires **structured citations carried in the IR** (a new structured handle in IR-canonical). | Directly answers DR-5 q b: the render-time footnote/citation path has a mature template (CSL/citeproc, which Pandoc — the pipeline's engine — already supports). The precondition is IR-level structured citations (today the IR grounding ledger carries fact provenance, §15, but not citation-style-renderable structured references — a gap to note). |
| **Fonts / colors / layout** per venue (stylesheet/class/theme) | **Render side — already solved:** **Presentation** (§5.3 — `variables`/`fonts`/`css`/`reference_doc`/`template`, applied deterministically at serialize on the persisted AST). | DR-5's own "font/color → Presentations, render-time, works" — confirmed and already in the model. No gap. |
| **Inline prose mechanics** (Oxford comma, US/UK spelling, quotation style) per venue | **Content side — compose-baked.** Today the DR-2 reconciled design homes these in **`lexicons/` at compose** (baked into the IR, one choice per artifact — see known-issues DR-2/DR-5). No render-time knob exists (serialize is deterministic + LLM-free, §14.1). | External world confirms there is NO deterministic render-time mechanism for this (§3.3). Varying it per venue ⇒ EITHER re-compose per venue (new artifact-id — matches universal practice) OR add a non-deterministic render-time LLM rewrite (breaks serialize's "free/deterministic" property, §14.1/§14.2). This is the genuine, externally-confirmed gap DR-5 names. |
| **Conditional content selection** (DITAVAL / ifdef / Sphinx only — include/exclude whole elements per output) | **Render side but LLM-grade:** resembles **reconcile reshape** (`adapt/split/pass/truncate`, §16), which is per-target and already produces per-`fitted-id` IR-fitted variants. | Whole-element inclusion/exclusion per venue is NOT inline mechanics; it maps to reconcile (pass 1), which already varies content per (platform, language). Distinguish this cleanly from the Oxford-comma case in the design. |
| **The boundary principle** ("render-side iff input is structured; content-side iff literal inline prose") | Matches the pipeline's **IR-canonical (composed once, platform-agnostic) vs Presentation/serialize (per-output)** split (§14–§17) exactly. | The external rule gives the architect a *test*: to move a style rule to render, give its input a structured IR handle (as CSL does). Anything unstructurable stays compose-baked. This is the cleanest external principle for DR-5 q a/d/f. |

### 4.3 The one-line summary of the mapping

- **DR-4:** a "content template" is externally a **schema/content-model** artifact = **compose/Format/IR-part** territory, explicitly separate from the visual stylesheet (= Presentations). The missing pieces vs today's model are **typed non-text slots** and a **per-slot constraint vocabulary** (which §2.1 supplies as a ready menu, incl. a hard/advisory severity split the pipeline already mirrors).
- **DR-5:** three style kinds, three homes, confirmed by external practice — **look → Presentation@render (solved)**; **citations/footnotes → structured-in-IR + CSL@render (mature external template, needs IR structured citations)**; **inline mechanics → compose-baked, no deterministic render path anywhere in the industry (the real gap; per-venue ⇒ re-compose or add non-deterministic rewrite)**.

---

## 5. What I could NOT verify (flagged for the architect)

- **DocBook primary spec not fetched.** The "semantic markup separated from presentation via XSL stylesheets" principle is well-established but my DocBook evidence is secondary (Wikipedia/grokipedia/nwalsh). The *principle* is safe; specific element/vocabulary claims should be confirmed against the DocBook TDG (https://tdg.docbook.org) if load-bearing. **[INFERRED]**
- **Sphinx** single-source claims (`only::`, builders, themes) are from general knowledge, not a fetched Sphinx doc page. Low-risk but unfetched. **[INFERRED]**
- **DITA constraint modules** (required/forbidden section per variant) confirmed only at snippet level from the DITA 1.3 OASIS spec ("combining, extending, and constraining document types"); I did not fetch the constraint-module chapter itself. The direction is solid; exact constraint-module mechanics unverified. **[VERIFIED-snip]**
- **The Oxford-comma-per-output "AI rewrite" existence proof** rests on a single vendor blog (Markup AI). Treat as weak — it establishes only that an *AI rewrite* class of tool markets comma insertion/deletion, NOT that any single-source *publishing* system does per-output inline-mechanics variation deterministically. The stronger, well-supported claim is the negative: no deterministic system does it. **[INFERRED / weak source]**
- **US↔UK spelling determinism.** I assert dictionary-substitution makes spelling *more* render-swappable than punctuation, but I did not fetch a primary tool spec proving reliable automated bidirectional conversion; context-sensitive cases (e.g., "program" vs "programme") are a known imperfection. **[INFERRED]**
- **Whether "a journal" = a Platform** in the pipeline is a modeling decision, NOT an externally-dictated fact. LaTeX bundles journal = class = {structure+style+design}; the pipeline factors these across ≥4 axes. External sources cannot resolve DR-4 q(f)/DR-5 q(f) for you — flagged as architect-owned. **[INFERRED]**
- I did not benchmark render-time cost/latency of CSL style-swapping vs re-compose; not needed for grounding, but noted as unquantified if the architect weighs option 1 vs 2 in §3.3.

