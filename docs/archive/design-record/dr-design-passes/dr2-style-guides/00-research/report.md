# DR-2 "Selectable style guides" — Stage 0 (Research) report

**Pass:** DR-2 DESIGN, stage 0 of the ops-architect design pass (research → architect).
**Scope of this report:** GROUND ONLY. How real, well-documented style guides are structured, and
a mapping of their element types onto the pipeline's existing nine axes. **This report does NOT
design the pipeline's style-guide solution** — bundle vs. new construct vs. templating is the
architect's call. It stops at "here is what real guides contain and where each piece would land."
**Read-only pass; no repo edits made.**

Every claim is tagged **[VERIFIED]** (primary source fetched, cited inline) or **[INFERRED]**
(reasoning over the sources / the repo, flagged for the architect to confirm).

Internal model verified against (repo, read directly this pass):
`docs/known-issues.md` (DR-2), `docs/design.md` §4–§5, §7.1–§7.4, §12.1–§12.7, `CLAUDE.md`
"The matrix", and the live registry schemas + entries:
`voices/_schema.yaml`, `voices/clear-explainer.md`, `formats/_schema.yaml`,
`formats/{medium-review-post,how-to-documentation}.md`, `platforms/_schema.yaml`,
`platforms/{linkedin,medium-post}.md`, `presentations/_schema.yaml`, `presentations/plain.md`,
`output-types/_schema.yaml`, `personas/_schema.yaml`, `personas/tech-journalist.md`,
`recipes/_schema.yaml`.

---

## 1. Sources consulted

### 1.1 Primary sources fetched and verified

| # | Source | URL | What it gave | Status |
|---|--------|-----|--------------|--------|
| S1 | Microsoft Writing Style Guide — full navigation TOC (`toc.json`) | https://learn.microsoft.com/en-us/style-guide/toc.json | Complete top-level category structure (25 top-level nodes + children) | [VERIFIED] fetched |
| S2 | Microsoft Writing Style Guide — welcome/landing | https://learn.microsoft.com/en-us/style-guide/welcome/ | Brand-voice framing ("warm and relaxed, crisp and clear"); pointers to Top-10 tips, Bias-free, Global | [VERIFIED] fetched |
| S3 | Google developer documentation style guide — TOC | https://developers.google.com/style | Complete left-nav category structure | [VERIFIED] fetched |
| S4 | Chicago Manual of Style, 18th ed. — front-matter contents | https://www.chicagomanualofstyle.org/book/ed18/frontmatter/toc.html | Part/chapter titles only (organizing structure) | [VERIFIED] fetched |
| S5 | LinkedIn Help — Newsletters best practices | https://www.linkedin.com/help/linkedin/answer/a517940 | Official soft recommendations + image specs; notable ABSENCE of prose rules | [VERIFIED] fetched |
| S6 | Medium Help Center — "Using the story editor" + Writing/editing section | https://help.medium.com/hc/en-us/articles/215194537-Using-the-story-editor · https://help.medium.com/hc/en-us/sections/115001484747-Writing-editing | Formatting affordances (headings, bold/italic, links, quotes/pull-quotes, drop caps, lists, code blocks, @-mentions) | [VERIFIED as primary-source content] — see caveat 1.3 |

### 1.2 Secondary sources (cross-check only, NOT treated as authority)

| # | Source | URL | Use |
|---|--------|-----|-----|
| S7 | AP Stylebook — Wikipedia summary of its structure | https://en.wikipedia.org/wiki/AP_Stylebook | Second general-editorial data point: A–Z main entries (3,000+) + subject chapters (Sports, Business, Media Law), grammar/punctuation/capitalization/spelling/numerals guidance, a recent "inclusive storytelling" chapter. Structural claim only. |

### 1.3 Could NOT verify from a primary source

- **AP Stylebook proper** — `https://www.apstylebook.com/` refused the fetch ("unable to fetch");
  the site is subscription-gated. AP's chapter structure above is from Wikipedia (S7), **secondary**.
  The required general-editorial guide (Chicago, S4) IS primary-verified, so this is a nice-to-have,
  not a gap. **[flagged]**
- **Medium "Using the story editor" page (S6)** returned **HTTP 403** on direct WebFetch. Its content
  (the formatting-affordance list) was captured from the Medium **Help Center's own indexed text**
  via search against `help.medium.com`. It is first-party content but was not fetched byte-for-byte
  this pass. Treat the affordance list as **VERIFIED-with-provenance-caveat**. **[flagged]**
- **Neither LinkedIn nor Medium publishes a prose/editorial "style guide"** in the Microsoft/Google
  sense. What exists first-party is (a) hard/most-limits + image specs and (b) editor formatting
  affordances and (c) soft engagement best-practice. Word-count "sweet spots" widely quoted for both
  platforms trace to **third-party blogs/SEO listicles**, which this pass does NOT treat as authority.
  This absence is itself a finding (see §3, §4). **[flagged]**

---

## 2. Element-type catalog (with the i / ii / iii classification)

**Classification key (as the architect requested):**
- **(i)** how the text *reads* — prose / voice / tone / rhetoric / mechanics of sentences
- **(ii)** *terminology* — word-level rules (preferred/banned terms, product names, casing of terms, numbers/dates/abbreviations)
- **(iii)** *structure / formatting / layout* — document skeleton, headings/lists/tables, typography, links, code blocks

A guide chapter often spans two of these; the table records the **primary** class and notes straddles.

| # | Element type | Present in (primary sources) | Primary class | Straddle / note |
|---|--------------|------------------------------|---------------|-----------------|
| E1 | **Brand voice & tone / personality** | MS "Brand voice: simple and human" [S2]; MS "Top 10 tips"; Google "Voice and tone" [S3] | **(i)** | Pure prose feel. |
| E2 | **Grammar & syntax rules** (active voice, second person, present tense, contractions, sentence structure, anthropomorphism) | MS "Grammar and parts of speech" [S1]; Google "Language and Grammar" [S3]; Chicago "Grammar and Usage" [S4]; AP grammar guidance [S7] | **(i)** | Rule-level prose mechanics. |
| E3 | **Punctuation rules** (commas, dashes, ellipses, quotation marks, semicolons, Oxford comma, slashes) | MS "Punctuation" [S1]; Google "Punctuation" [S3]; Chicago "Punctuation" [S4] | **(i)** | Sentence mechanics; house choice (e.g. serial comma) is a stable ruleset. |
| E4 | **Capitalization rules** | MS "Capitalization" [S1]; Google "Capitalization" [S3]; Chicago "Names, Terms…" [S4] | straddle **(ii)+(iii)** | Term casing = (ii); heading case (sentence vs. title case) = (iii). |
| E5 | **Spelling / distinctive treatment of words** (US vs. UK spelling, italics for terms, non-English words) | MS "Word choice → US spelling / avoid non-English" [S1]; Chicago "Spelling, Distinctive Treatment of Words, and Compounds" [S4] | straddle **(ii)+(i)** | House-wide mechanical default. |
| E6 | **Terminology / word lists / preferred & banned terms** (A–Z lists, term collections) | MS "A–Z word list and term collections (12 subcategories)" [S1]; Google "Word list" [S3]; AP "3,000+ A–Z entries" [S7]; Chicago "Names, Terms…" [S4] | **(ii)** | The single largest bulk of MS/Google/AP by volume. |
| E7 | **Product names, trademarks, proper-name treatment** | MS term collections + "Acronyms" [S1]; Google "Product names", "Trademarks", "Names and Naming" [S3] | **(ii)** | Casing/possessive rules tied to specific tokens. |
| E8 | **Numbers, dates, times, units, abbreviations/acronyms** | MS "Numbers", "Acronyms" [S1]; Google "Numbers", "Dates/times", "Units", "Abbreviations" [S3]; Chicago "Numbers", "Abbreviations" [S4]; AP "Numerals" [S7] | **(ii)** | Word-level formatting rules. |
| E9 | **Inclusivity / bias-free / global-audience / inclusive language** | MS "Bias-free communication" (+ "Militaristic language"), "Global communications" [S1][S2]; Google "Inclusive language", "Global audience" [S3]; AP "Inclusive storytelling" [S7] | straddle **(i)+(ii)** | Prose stance (i) + explicit avoid-terms lists (ii). |
| E10 | **Word choice / plain language / jargon / excessive claims / concision** | MS "Word choice" (simple words, concise sentences, avoid jargon) [S1]; Google "Jargon", "Excessive claims", "Prescriptive documentation" [S3] | straddle **(i)+(ii)** | Prose discipline expressed partly as banned/avoid words. |
| E11 | **Text formatting / typography** (type, bold, italic, formatting titles, common text elements) | MS "Text formatting" [S1]; Google "Text-formatting summary", "Italics" [S3] | **(iii)** | Visual/markup layer. |
| E12 | **Scannable / document structure** (headings, lists, tables, pull quotes, sidebars, paragraphs) | MS "Scannable content" (headings/lists/pull quotes/sidebars/tables) [S1]; Google "Formatting and Organization" (headings, lists, tables, notices, figures) [S3] | **(iii)** | Layout of the whole document. |
| E13 | **Procedures / step-by-step instruction structure** | MS "Procedures and instructions" [S1]; Google "Procedures" [S3] | **(iii)** | Genre-shaped skeleton (numbered steps, prerequisites). |
| E14 | **Linking / cross-references** | MS "URLs and web addresses" [S1]; Google "Cross-references and linking", "Headings as link targets" [S3] | **(iii)** | Structural. |
| E15 | **Code in text / UI elements / command-line / API reference / developer content** | MS "Developer content", "Formatting developer text elements" [S1]; Google "Computer Interfaces", "HTML and CSS", "Code in text" [S3] | straddle **(iii)+(ii)** | Formatting (iii) + code-term conventions (ii). |
| E16 | **Accessibility** (alt text, color/patterns, writing for all abilities) | MS "Accessibility guidelines and requirements" [S1]; Google "Accessibility" [S3] | straddle **(i)+(iii)** | Alt-text prose (i) + non-color-only formatting (iii). |
| E17 | **Examples / do-and-don't patterns** (worked correct/incorrect samples) | pervasive in MS [S1] and Google [S3] | cross-cutting | A presentation convention of guides, not a rule class. |
| E18 | **Content/design planning, responsive content, review checklists, publishing process** | MS "Content planning", "Design planning", "Responsive content", "Final publishing review", checklists [S1]; Chicago Part I "Publishing and Editing" [S4] | **(iii)** + process | Workflow, not per-artifact writing rules. |
| E19 | **Source citation / attribution formatting** | Chicago Part III "Source Citations and Indexes" [S4]; AP media-law/attribution [S7] | **(iii)** / mechanics | Largely outside pipeline scope (pipeline grounding is a separate machinery, design §6/§15). |

**Structural read of the catalog [VERIFIED from S1/S3/S4]:** a real style guide is **heterogeneous** —
it is not one kind of thing. By volume, the bulk of MS/Google/AP is class **(ii)** (word lists,
terminology, product names, numbers/dates). Class **(i)** (voice/grammar/punctuation) is a smaller
but foundational front section. Class **(iii)** (formatting, scannable structure, procedures, code
formatting) is a large third pillar. **No single existing pipeline axis owns all three** — they
split across different axes (see §3).

---

## 3. Mapping onto the existing dimensions (covered / overlap / no-home)

The pipeline's nine axes and what each **already owns** (verified from schemas this pass):

- **VOICES** (`voices/_schema.yaml`): `formality`, `humor`, `warmth`, `energy` sliders (1–5);
  `narrator_persona` (text); **`guidelines` (markdown, free text)**. Owns "all register/affect/manner"
  (design §5.2). Guardrail: didactic function + reading level are Persona (+ Format), never Voice.
- **FORMATS** (`formats/_schema.yaml`): the genre's **rhetorical structure is the entry BODY prose**
  (consumed at compose, §15); the one structured attribute is **`parts`** (ordered named sub-outputs).
  Platform-agnostic genre; no platform data (Q4).
- **PLATFORMS** (`platforms/_schema.yaml`): `destination`, `advisory_norms` (soft, ride cascade),
  `hard_limits` (physical caps, enforced only at reconcile gate), `format_advisories`,
  `reconcile_strategy(_defaults)`, `default_output_type`.
- **PRESENTATIONS** (`presentations/_schema.yaml`): `variables` (Pandoc `-V`, incl. fonts/margins),
  `highlight_style`, `template`, `reference_doc`, `css`, `pdf`. **Deterministic style at serialize**
  (Pandoc-level), never prose (§5.3 PD1–PD8).
- **OUTPUT-TYPES** (`output-types/_schema.yaml`): pure serialization coordinate (md/html/pdf/docx/…);
  writer selection. Empty attribute manifest — a coordinate, not a rule carrier.
- **PERSONAS**: audience facts + `default_voice` ref (who it is FOR; owns `knowledge_level`).
- **TOPICS / GOALS / LANGUAGES**: subject / outcome-set / tongue — not style carriers.

### 3.1 The mapping table

| Element type | Existing home | Coverage verdict | Blur / orthogonality risk |
|---|---|---|---|
| E1 Brand voice & tone | **VOICES** sliders + `narrator_persona` | **COVERED** | A style guide that re-declares tone **BLURS Voice** (DR-2 open-q (c)). This is the tightest overlap. |
| E2 Grammar/syntax; E3 Punctuation; E5 spelling; E10 word-choice/plain-language | **VOICES `guidelines`** free-text (informally) | **OVERLAP — partially covered, informally** | The live `voices/clear-explainer.md` `guidelines` ALREADY carries prose rules AND a **banned-words list** ("simply", "just", "revolutionary" are banned) [VERIFIED, repo]. So a style guide's prose+diction rules **already live inside Voice today**. Putting them in a new "style guide" duplicates/blurs Voice unless the line is drawn. **This is the sharpest DR-2 (c) finding.** |
| E4 Capitalization (heading case); E11 text formatting/typography | **PRESENTATIONS** (visual) + **FORMATS** (heading structure) | **COVERED (split)** | Typography → Presentation; heading *case as visual* → Presentation/Output-type; heading *structure* → Format. A guide carrying fonts/CSS **BLURS Presentation**. |
| E12 Scannable/document structure; E13 Procedures skeleton | **FORMATS** (rhetorical-structure body + `parts`) | **COVERED** | `how-to-documentation.md` already encodes Goal→Prerequisites→Steps→Verification→Troubleshooting; `medium-review-post.md` encodes Subject→Criteria→Findings→Verdict [VERIFIED, repo]. A guide carrying a section skeleton **BLURS Format**. This is the "template" overlap — see §4. |
| E14 Linking; E15 code/UI formatting | **OUTPUT-TYPES / render-targets / FORMATS** | **COVERED (split)** | Link + code rendering is a serialize/format concern; code *terminology* leans (ii). |
| Platform char-limits / word-count norms (LinkedIn 3000 hard / ~1300 pref; Medium ~1500 pref) | **PLATFORMS** `hard_limits` / `advisory_norms` / `format_advisories` | **COVERED** | `platforms/linkedin.md` already carries `post_char_limit: 3000`, `preferred_char_count: 1300`; `platforms/medium-post.md` carries `preferred_word_count: 1500` [VERIFIED, repo]. **DR-2's hard constraint** forbids a style guide absorbing these — doing so **BLURS Platform**. |
| E16 Accessibility (formatting half) | **PRESENTATIONS / OUTPUT-TYPES** + serialize (html/epub strip filter) | **PARTIALLY COVERED** | Alt-text *prose* has no clean home (see below). |
| **E6 Terminology / word lists / preferred & banned terms** | **— none —** (only informally squeezable into Voice `guidelines`) | **NO HOME** | The single largest style-guide element class (by volume) has **no first-class carrier**. Voice `guidelines` can hold a *handful* of banned words (it does today), but a real term collection (hundreds of preferred/avoid pairs, product-name casing) does not belong in a tone entry and **BLURS Voice** if stuffed there. **Strongest candidate for the genuine gap.** |
| **E7 Product names / trademarks; E8 numbers/dates/units/abbrev; E5 US-vs-UK spelling (as a house default)** | **— none clean —** | **NO HOME** | House-wide *mechanical* rules (spelling variant, number/date style, Oxford comma, term casing) are not tone (Voice), not genre (Format), not platform limits (Platform), not Pandoc styling (Presentation). Today they can only be smuggled into Voice `guidelines`. **Second no-home cluster.** |
| **E9 Inclusivity / bias-free / global-audience** | partial: Voice `guidelines` (prose) | **NO CLEAN HOME** | Cross-cutting house policy; overlaps Voice for the prose half and needs a term-avoid list (ii) it has nowhere to put. |
| E17 examples; E18 planning/checklists/workflow; E19 citations | out of per-artifact scope | **N/A** | Guide-authoring/process concerns, or (E19) the separate grounding machinery (§6/§15), not a request-time style selection. |

### 3.2 What the mapping shows [INFERRED, for the architect to confirm]

1. **A "style guide" is already ~mostly a bundle of existing-axis choices.** The maintainer's option-1
   hypothesis is well-supported: E1→Voice, E12/E13→Format, typography→Presentation, platform
   limits→Platform, serialization→Output-type. The pipeline **already has a bundling construct**: the
   **recipe** (`recipes/_schema.yaml`) binds one entry per content dimension + goal-set + configured
   `values` + optional pinned platforms/languages/output-types/presentations [VERIFIED, repo]. A named,
   reusable preset (recipe-like, or a light overlay) could express the *composition* half with **no new
   axis**.
2. **The prose-overlay half already has a home too — Voice `guidelines`** — which is exactly why the
   overlap/blur risk (DR-2 (c)) is real and not hypothetical: it is happening in the shipped
   `clear-explainer` entry today.
3. **The only element type with genuinely NO existing home is class (ii): terminology / word-level
   rules** (E6, and the mechanical-house-rule cluster E7/E8/E5, plus the term-list half of E9). This
   is the crisp gap the architect must weigh: is it a **one-file additive extension** of an existing
   axis (per the matrix rule) — e.g. a terminology/word-list attribute or a small sibling registry —
   or a new construct? Everything else risks **duplicating** an axis rather than filling a gap.
4. **Every blur the DR-2 hard constraint warns about is confirmed concretely:** tone→Voice,
   limits→Platform, typography→Presentation, skeleton→Format. A style-guide construct that carries any
   of those **overlaps an axis**; the design-decisions §12.1 "collapsing them reintroduces blur" rule
   and §3.2 one-file-add rule both bite here.

---

## 4. Style-guide vs. template finding (DR-2 open-question (d))

**Question:** in industry usage, is a "style guide" (writing rules) consistently distinct from a
"template" (fixed structure / skeleton)?

**[VERIFIED] Evidence from the primary sources:**
- All three verified rule-guides — Microsoft [S1], Google [S3], Chicago [S4] — are organized as
  **RULES grouped by category** (voice, grammar, punctuation, word list, formatting conventions).
  **None of them ships a fill-in document skeleton / boilerplate template.** Microsoft's closest
  structural material is *conventions* ("Scannable content": how to write headings/lists/tables;
  "Procedures and instructions": how to structure steps) — these are **rules about structure, not a
  reusable empty skeleton**. Google's "Formatting and Organization" is likewise conventions, not a
  template file.
- Chicago's own top-level split reinforces the line: **Part II "Style and Usage"** (the rules) is a
  different part from **Part I "Publishing and Editing"** (process/manuscript prep) [S4] — neither is a
  document template.

**[VERIFIED] The pipeline already owns the skeleton role separately from the prose role:**
- **Document structure / skeleton is FORMAT's job.** `how-to-documentation.md` and
  `medium-review-post.md` each encode a concrete section skeleton in the entry body, plus the `parts`
  attribute for named sub-outputs [VERIFIED, repo]. That IS the "template-like" capability.
- **Prose/voice is VOICE's job** (sliders + `guidelines`).
- So the pipeline **already mirrors the industry split**: skeleton (Format) is a different axis from
  prose rules (Voice).

**[INFERRED] Conclusion for the architect:**
- Industry treats **style guide (rules for how to write/format)** and **template (a reusable document
  skeleton to fill in)** as **distinct, complementary artifacts**. The surveyed guides contain the
  former and *not* the latter. This supports DR-2's option-3 read: the maintainer's *structural* need
  ("more easily and directly specify a desired structure") is a **template concern that is separable**
  from a style guide.
- **BUT** in this pipeline the template/skeleton concern is **already substantially served by FORMAT**
  (rhetorical-structure body + `parts`). So the architect's real DR-2 (d) question is narrower than
  "do we need a template feature?" — it is: **does FORMAT need a more explicit / parametric structure
  attribute** (a declarable skeleton with slots) than today's free-prose body + `parts` list, or is the
  free-prose body already enough? That is a Format-extension question, not a new-style-guide question.
  **[flag for architect]**

---

## 5. What I could NOT confirm, and what would settle it

| # | Open item | Why unresolved | What would settle it |
|---|-----------|----------------|----------------------|
| U1 | AP Stylebook's exact chapter structure | `apstylebook.com` refused fetch (subscription-gated); only a Wikipedia summary (S7) obtained | A subscriber fetch of the AP TOC, or accept Chicago [S4] as the verified general-editorial reference (already sufficient for this pass). |
| U2 | Medium "story editor" affordance list, byte-verified | The page 403'd on direct WebFetch; content came from the Help Center's indexed text via search | An authenticated/rendered fetch of `help.medium.com/.../215194537`; low value — Medium clearly ships **no prose style guide**, only editor affordances + soft best-practice. |
| U3 | Whether LinkedIn/Medium have any *first-party prose* style guidance beyond limits + affordances | Confirmed **absent** in the first-party sources fetched [S5, S6]; widely-quoted word-count "sweet spots" are third-party (weak) only | Nothing further first-party appears to exist; the architect should treat platform "style" as **limits (Platform) + formatting affordances (Output-type/Presentation)**, not a prose guide. |
| U4 | Whether E6 (terminology/word lists) is best served by a one-file additive extension of an existing axis vs. a new construct | This is a **design decision**, explicitly out of scope for this research pass | The architect's overlap analysis + the matrix one-file-add test (§3.2/§5.4). This report only establishes that E6 is the one element type with **no existing home**. |
| U5 | Exact precedence a style-guide overlay would need vs. the M2 cascade / brand-authoritative flag | Design decision (DR-2 (b)); not researched here | Architect design over §12.2–§12.6 (note the existing `authoritative: true` Voice flag §12.6 is a precedent for "config that wins over the cascade"). |

---

## 6. One-paragraph handoff to the architect

A real style guide is **three different things at once**: (i) prose/voice rules, (ii) terminology /
word-level rules, and (iii) structure/formatting rules — verified across Microsoft [S1], Google [S3],
and Chicago [S4]. In this pipeline those three map to **different existing axes**: (i)→**Voice**
(sliders + the free-text `guidelines`, which already carries prose rules and even a banned-words list
today), (iii-structure)→**Format** (rhetorical body + `parts`), (iii-visual)→**Presentation/Output-type**,
and platform limits→**Platform** (already modeled, e.g. LinkedIn's 3000-char cap). The maintainer's
suspicion holds: a style guide is **largely a bundle of existing-axis choices plus a prose overlay** —
and the pipeline already has the bundler (**recipe**) and the prose-overlay home (**Voice guidelines**).
The **one element type with no existing home is class (ii): terminology / word lists / banned & preferred
terms / product-name casing / house mechanical rules** — that is the crisp gap and the strongest
candidate for a **one-file additive extension** (vs. a new construct). Everything else a "style guide"
would carry **overlaps** an existing axis and would **blur** it (tone→Voice, limits→Platform,
typography→Presentation, skeleton→Format) — exactly the orthogonality risks DR-2 names. On (d): industry
treats style guide (rules) and template (skeleton) as distinct artifacts; here the skeleton concern is
already served by **Format**, so the "template" question reduces to whether Format needs a more explicit
structure attribute — not whether a new style-guide construct needs one.

