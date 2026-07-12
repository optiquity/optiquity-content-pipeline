<!-- TOMBSTONE — ARCHIVED DOCUMENT -->

> **SUPERSEDED ENTIRELY by [`docs/design.md`](../design.md) — archived 2026-07-11 (placement
> package A4-2).** This working document has **no authority**; on any conflict, `docs/design.md`
> wins. It is preserved verbatim below for history. The live stub at `docs/design-decisions.md`
> points here.
>
> **Section map (per `docs/design.md` Appendix B — gap-free):**
>
> | Old section (this doc) | Superseded by (`docs/design.md`) |
> |---|---|
> | §1 status & how to read | Appendix B history row (moot under archive) |
> | §2 lexicon | §4 |
> | §3.1–§3.3 dimensions | §5 |
> | §3.4 pipeline/IR | §14 (+§15, §17) |
> | §3.5 reconciliation | §16 — **supersession written there: fit-or-block replaces "never blocks"** (T4) |
> | §3.6 sources | §6 |
> | §3.7 folios | §9 — **DIRECTIVE + A4-4 replace shared-grounding/roster-as-folio-properties (T2 → §9.6) and ordering/schedule** |
> | §3.8 overrides/cascades | §12 — incl. the M3 widening (T8) and CA5 terminology |
> | §3.9 provenance/scope | §10 |
> | §3.10 schemas & versioning | §11 |
> | §4 decision log 1–9 | Appendix B history (the log's decisions are absorbed or superseded by the ruled design) |
> | §5 deferred hooks | §26 |
> | §6 open areas | §27.4 |
> | §7 changelog | Appendix B history row |
>
> **Stale claims that die with this archive** (each superseded at its flagged section of
> `docs/design.md`): folio `rendering_intent`/ordering/schedule and compat-adjacent folio text
> (§9); "reconciliation never blocks" (§16); "manifest = a slice of the SSOT" (§4/§21.5); the
> 4-kind dimension table (§5.1); `valid_platforms` on Format (§5.2/§8); "a part is a layer in the
> value cascade" as settled fact (→ open T7, §27.3).

---

# Design Decisions & Conceptual Model (working doc)

> **Status: living WORKING document — not the formal design, not yet authoritative.**
> This is the record of an in-progress redesign of the framework and the input to a later
> formal design pass. It is written from the **maintainer's** perspective (this is the public
> framework repo, kept empty of client-specific content).
>
> **Relationship to `docs/mission.md`:** where a decision here diverges from `mission.md`, it is
> flagged **"Changes vs. mission."** `mission.md` is **not rewritten yet** — reconciling it into a
> formal design (or a mission v2) is a later, separate pass. Until then, on any conflict about the
> *redesign*, this doc reflects current intent; on anything not yet covered here, `mission.md` still
> stands.
>
> **How to read:** §2 is the vocabulary. §3 is the conceptual model — the guts of the framework.
> §4 is the decision log (the "why"). §5 lists things designed-for but deliberately deferred. §6
> lists areas not yet worked. §7 is this doc's changelog.

---

## 1. Status & how to read

- **Nature:** working capture of design decisions 1–9 plus the conceptual model they produced.
- **Authority:** none yet. Feeds a formal design once agents/skills and the remaining open areas
  are worked. Do not treat as a spec.
- **Scope of the redesign so far:** the content/rendering model, the dimension inventory, the
  source abstraction, the override/precedence model, provenance/scope, reconciliation, the
  recipe/artifact/folio/IR architecture, and schema versioning.
- **Not yet worked (see §6):** agents & skills (both planes), the maintainer's remaining
  un-enumerated design points, and the concrete serialization/identity/resolver implementation.

---

## 2. Lexicon

The nesting `dimension ▸ entry ▸ attribute` is load-bearing; keep the three levels distinct.

| Term | Meaning |
|---|---|
| **dimension** | One of the orthogonal design axes. Replaces the old word "axis" (they are **not** uniform — see §3.2). Content: Topic, Persona, Format, Voice, Goal. Rendering: Platform, Language, Output-type. |
| **entry** | One whole populated value of a dimension (the "hiring-manager" persona; the "business" voice). One file. **This is what you select.** |
| **attribute** | One named field *inside* an entry (`persona.tone`; `source.authoritative`). **This is what you override at fine grain.** An entry *has* attributes. |
| **registry** | The collection (directory) of entries for a dimension. |
| **recipe** | A reusable binding of one value per *content* dimension + a goal-set + overrides → produces **one artifact**. May optionally pin rendering targets. (Formerly "doc profile" — dropped because "profile" is overloaded.) |
| **selection** | A multi-select input across dimensions that **fans out** into many recipes. |
| **fanout** | Expansion of a selection into concrete, tracked items. Two flavors: *content fanout* (matrix cross-product → different artifacts) and *rendering fanout* (one artifact → many packagings). |
| **artifact** | The composed piece in natural, pre-render form. **Physically it is the document IR.** One per recipe. |
| **IR** | Intermediate Representation — the canonical machine-readable document model that *is* the artifact (structured envelope + Markdown in the leaves). |
| **deliverable** | A rendered, output-type/platform/language-specific output. **One artifact → N deliverables.** |
| **renderer** | A pluggable `IR → deliverable` transformer. A registry, symmetric with source adapters. |
| **source** | A read-only grounding provider. Two layers: **adapter** (type) + **instance** (bound config). |
| **adapter** | A source *type* (`graphify`, `folder`, `url`, `pdf`…). Contributes **capabilities**. |
| **source instance** | A configured, bound source. Contributes **characterization** (scores) + connection + a content-kind tag. |
| **folio** | A **purpose-driven package**: a related set of artifacts + a manifest (see §3.7). |
| **manifest** | The CSV/spreadsheet a folio emits (a slice of the SSOT spreadsheet) for n8n to execute. |
| **override / cascade / layer** | The precedence machinery (§3.8). "Most local/specific/immediate wins." |
| **provenance** | Framework-shipped vs. instance-authored. Encoded as **metadata** (§3.9). |
| **scope** | Global vs. client-specific. Encoded as **location** (§3.9). |
| **folio type** | A reusable, framework-shippable blueprint for a purpose-driven package (repo-docs, curriculum, feature-drip). |

---

## 3. Conceptual model (the guts)

### 3.1 Two kinds of dimension: content vs. rendering

The single most important cut. Dimensions are one of two kinds:

- **Content dimensions** — shape the *substance*. Their cross-product yields **different artifacts**:
  **Topic**, **Persona**, **Format**, **Voice**, **Goal**.
- **Rendering dimensions** — *package and route* a finished piece. One artifact → **many renderings**,
  no new substance: **Platform**, **Language**, **Output-type**.

This cut resolves three things at once: Platform "isn't exactly an axis" (it's rendering), Language
"doesn't fit as an axis" (it's rendering), and naive fanout on either would be a maintenance
nightmare (you'd be cloning content entries to vary a rendering concern).

**Two kinds of fanout follow:**
- **Content fanout** — matrix cross-product of content dimensions → several distinct artifacts.
- **Rendering fanout** — one artifact rendered many ways (languages, platforms, output-types) → a folio.

### 3.2 Dimensions are NOT uniform — name the kinds

A second structural fact: even the content dimensions aren't the same *kind* of thing. Forcing
uniformity is what muddled the original "every axis is a directory of entries" model.

| Kind | Description | Dimensions |
|---|---|---|
| **Registry** | Discrete entries, one-file-add. | Topic, Persona, Format, Goal |
| **Parametric** | Presets **and** sliders; generatable from examples. | Voice |
| **Layer / constraint** | Not content; imposes overrides + routing. | Platform |
| **Rendering parameter** | Applied as a transform with a default. | Language, Output-type |

**Cardinality** is a second way they differ — single- vs. set-valued *within one artifact*:
- **Single-valued per artifact:** Topic, Persona, Format (strictest — one shape per piece), Voice.
- **Set-valued within one artifact:** **Goal** (an artifact carries a *set* of goals).

So a dimension is characterized by: content-or-rendering, its kind, and its cardinality.

### 3.3 The dimension inventory

Each dimension is defined by the one question it answers, what it **owns**, and what it **must not
touch** (the orthogonality guardrails).

#### Topic — *What is it about? (and why it matters)*
- **Owns:** the subject matter, grounded in a source; **plus `why`** — the editorial significance /
  angle (why this subject is worth covering).
- **Must not touch:** audience, structure, destination, or the persuasion objective.
- **Boundaries:** `why` ≠ **Goal** (`why` = subject significance; Goal = the outcome to drive).
- **Kind/cardinality:** registry, single-valued.
- **Notes:** topics span a spectrum from **universal archetypes** (architecture-overview,
  getting-started, troubleshooting — the shell recurs, only grounding changes) to **bespoke**
  (only meaningful for one repo). This is handled uniformly by **scope** (§3.9): shared/global vs.
  `workspaces/<client>/topics/` — *not* by a special archetype mechanism.
- **Decompose blurs:** "getting-started guide" = topic `onboarding` (subject) × format
  `step-by-step-tutorial` (shape). Keep topic about subject/intent, never structure.

#### Persona — *Who is it for?*
- **Owns:** a **coherent bundle** — role/relationship (prospective user, prospective client,
  AI-hiring-manager, finance-hiring-manager, peer, general reader), knowledge/expertise level,
  motivation/job-to-be-done, objections/skepticism, credibility signals, and **default register**.
- **Must not touch:** subject (Topic), structure (Format), channel (Platform), and — importantly —
  **reading context** ("skims on mobile"), which is the **Platform's** job.
- **Why a bundle, not decomposed:** the attributes co-vary; letting expertise and role vary
  independently produces incoherent audiences ("beginner AI hiring manager" = noise).
- **Kind/cardinality:** registry, single-valued.

#### Format — *What shape / genre is the artifact?*
- **Owns:** the rhetorical structure/genre — and it **shapes the IR's structure** (§3.4).
- **Platform-agnostic:** rename platform-bound formats to genres. `linkedin-post` →
  `short-opinion-post` (valid on linkedin, x); `medium-post` → `long-form-essay`;
  `readme` stays `readme` (genuinely fused → `valid_platforms: [github]`).
- **Composite formats:** a format may declare `parts` — an ordered list of named sub-outputs
  (`slide-deck → parts: [slides, presenter-notes]`; `podcast → parts: [script, show-notes]`).
  Single-part formats omit it. Each part may carry its own constraints and its own attribute
  overrides (a part is a layer in the value cascade). Composite structure lives **in the IR**.
- **Must not touch:** subject, audience, destination mechanics, serialization (output-type).
- **Kind/cardinality:** registry, single-valued (strict — two formats in one piece = two artifacts,
  or a composite).
- **Needs a large registry:** how-to, explainer, blog, short-opinion-post, long-form-essay, readme,
  podcast-script, study-guide, slide-deck, exam, answer-key, presenter-commentary, and more. Not
  authoritative — grows one file at a time.

#### Voice — *How does it sound?*
- **Distinct from Persona.** Persona = who you target; Voice = how the text sounds.
- **Owns:** register/affect/manner — formal↔casual, comedic↔serious, warm↔cold, plain↔ornate,
  energy, and narrator-persona (pirate, noir detective).
- **Must NOT touch:** reading level / how-much-to-explain (**Persona**), subject (**Topic**),
  structure (**Format**), destination (**Platform**). **Guardrail:** "education" and "technical"
  are **not** voices — didactic function is Persona + Format. Watch these specifically.
- **Kind:** **parametric** — a named voice ("business," "pirate") is a *saved slider configuration*
  plus **free-text guidelines**. Ships with standard voices; users add their own.
- **Generatable from examples:** feed sample text → extract a voice ("Voice-DNA"). Treat a
  generated voice as **INFERRED** until reviewed.
- **Sliders:** e.g. comedy, seriousness, warmth, formality — overridable per recipe/run (ride the
  value cascade).
- **Cardinality:** single-valued.

#### Goal — *What outcome should the artifact drive?*
- **A content dimension** (change the goal → the substance changes). **Set-valued within one
  artifact:** a recipe binds `goals: [...]` and the piece serves the whole set.
- **Spectrum, one registry, each entry tagged `kind: strategic | action`:**
  - **strategic** — inform about a POV, convince with evidence, compare options, reframe,
    establish authority, provoke discussion.
  - **action / CTA** — visit a site, download, subscribe, sign up, run a command, take a test,
    tell a colleague, or explicitly *no action*.
  - **A CTA is just a goal with `kind: action`** — not separate machinery. The tag tells the
    writer how to surface it (strategic → shapes argument/evidence; action → explicit ask line).
- **Boundaries:** Goal vs. `Topic.why` (author-want vs. subject-significance); Goal vs.
  `Persona.motivation` (what *you* want vs. what the *reader* wants — the tension is real content).
- **No cap; warn on overload** (never block).
- **Fanout exception:** for every other dimension, multi-select = fanout. For Goal, multi-select =
  *stacking into one artifact*. To produce goal **variants** as separate artifacts, express a
  **list of goal-sets** — each set → one artifact. (In scope now.)
- **Kind/cardinality:** registry, **set-valued**.

#### Platform — *Where does it get published?* (rendering)
- **Not a content axis** — a **destination + constraint/override layer**.
- **Owns:** mechanical constraints (char/word limits, rich-text vs. markdown, image support, link
  handling, publish path/API) and routing. Declares **per-format constraint overrides** (the same
  format has different limits per platform).
- **Ships default recipes/doc-profiles** for major platforms (LinkedIn, Medium, Substack…).
- **Constraints are advisory defaults** — overridable per recipe/run **with a warning** (§3.8 Fork A).

#### Language — *Which tongue?* (rendering)
- A **rendering parameter/transform** with an instance default. **Not** a Persona attribute and
  **not** a naive content axis — both would force cloning personas/topics per language.
- Producing N languages = **rendering fanout** (one artifact → N localized deliverables = a folio).
  The substance never forks, which is what avoids the maintenance nightmare.

#### Output-type — *How is it serialized?* (rendering)
- Plain text, Markdown, YAML, JSON, PDF, docx, etc. A **rendering lever, not Format.** Format shapes
  the IR's *structure*; output-type *serializes* the IR.
- A Platform may **default** an output-type (GitHub→md, print→pdf), but it's independently selectable.

### 3.4 The pipeline architecture (IR at the core, pluggable ends)

```
Source adapters ─► grounding ─► [compose: recipe + content dimensions] ─► ARTIFACT (document IR, saved)
   (pluggable IN)   (facts +                                                    │
                     provenance +                                               ▼
                     confidence)                             [render: renderer + output-type +
                                                              platform reconciliation]  (pluggable OUT)
                                                                                │
                                                                                ▼
                                                                    DELIVERABLE(s) (saved)
```

- **Pluggable ends, stable core.** Input side = source adapters; output side = renderer adapters;
  the **document IR** in the middle is the canonical artifact.
- **Symmetry:** source adapters ↔ renderer adapters — both pluggable registries around a stable core.
- **Cost isolation:** the `writer` produces the IR (LLM-expensive, done once). Rendering is
  **deterministic and free** — re-render to a new output-type, or after a renderer bugfix, with no
  regeneration. Save both the IR and the deliverables in the workspace.
- **IR representation:** a **structured envelope** (YAML/JSON — parts, sections, ordering, dimension
  metadata) with **Markdown in the leaves.** Single-part docs ≈ Markdown + frontmatter; composite
  docs = an envelope of labeled Markdown parts. Composite/multi-part structure lives here.
- **Don't invent the document model.** Use Markdown-envelope + **Pandoc-family renderers**, invoked
  as an **external tool** (subprocess — license-clean for MIT, not vendored, same posture as
  Graphify). v1 output-types: md, html, pdf, docx. Exotic (pptx slide decks, epub) = **deferred
  renderer plugins** via the registry.
- **Reconciliation happens at render** (§3.5 / Decision 5): a `split` is a render-time IR transform.

### 3.5 recipe ▸ artifact ▸ deliverable, and reconciliation

- **recipe → one artifact.** Binds content dimensions + goal-set + overrides; may optionally pin
  rendering targets (else supplied at run).
- **selection → many recipes → a folio** (content fanout).
- **artifact → N deliverables** (render step; rendering fanout across output-type × platform ×
  language).
- **Mechanical reconciliation** (when an artifact can't physically fit a rendering target):
  non-destructive **because it's a render-stage concern** — the artifact is preserved; only the
  per-target deliverable is reconciled. It is a **selectable strategy, always warned**, riding the
  value cascade (framework default per format×platform → recipe → run):
  - **`adapt`** — reshape/summarize to fit (default for most overflows).
  - **`split`** — native multi-part idiom (X thread, IG carousel). Touches folios (a sequence) and
    composite output.
  - **`pass`** — natural form + warn, no change.
  - **`truncate`** — available, rarely a sensible default.
  - **Default = auto-`adapt` / `split`, always warned, artifact preserved.** Covers length overflow
    **and** capability mismatch (format wants images/tables, platform has neither → adapt + warn).
  - A **warning always fires** and is recorded (trigger, strategy, change) — never a block.

### 3.6 Sources & grounding

- **Source = pluggable, read-only grounding provider.** Two layers:
  - **adapter** (type): how to query it; declares **capabilities** (graph traversal / full-text /
    retrieval). Graphify is one adapter; others: folder, url, pdf, db…
  - **instance** (bound config): connection + **characterization** + a categorical **content-kind**
    tag. **Multiple instances of one adapter are normal** (two `folder` instances: research papers
    vs. user surveys).
- **Characterization scores live on the instance** (numeric, e.g. 1–5), each defined once so they're
  comparable, split content-vs-source to stay orthogonal:
  - **authoritative** — nature of the *content*: evidentiary/factual vs. speculative.
  - **opinionated** — degree of *subjective stance* in the content (not the inverse of authoritative).
  - **trusted** — reliability/track-record of the *source itself*.
  - **freshness** — recency of the content; **derivable** and possibly a **range/window** (the others
    are human-*asserted*).
  - Score **vocabulary is framework-shipped + user-extensible** — each new dimension **defined once**.
- **Provenance/confidence** generalizes Graphify's EXTRACTED/INFERRED/AMBIGUOUS across all adapters.
- **Scope:** the **workspace declares the source pool**; a **recipe/run may select a subset**
  (default = all).
- **Combination/conflict:** **union** the grounding, keep each fact's originating source; on
  **conflict, downgrade to AMBIGUOUS and warn** (optionally honoring a declared priority).
- **Select by characteristic, not by identity:** goals/recipes express preferences over **scores/tags**
  (`prefer authoritative; freshness < 12mo`), never hardcoded source ids. Payoffs: drop in a new
  source with the right scores → automatically eligible; goals relate to sources through scores (a
  *convince* goal weights `authoritative` up; a *compare* goal can **span contrast** — pull from
  multiple content-kinds).
- **Boundary:** Source = **factual grounding only**. Voice exemplars inform *how it sounds* →
  they belong to **Voice**, not Source.

### 3.7 Folios — purpose-driven packages

- **A folio is a purpose-built package**, defined by:
  - a **purpose** (document this repo; teach this class; promote these features),
  - **member roles** — what the package contains and what each is *for* (README + getting-started +
    architecture; study-guide + exam + answer-key), each role a recipe-skeleton,
  - **shared grounding** (all members bound to the same source/commit/workspace → coherence),
  - optional **ordering** and **schedule** (drip over time — explicitly *not* "all at once").
- **Parallel to recipe, one level up:** recipe → one artifact; **folio type → a set of artifacts +
  a manifest.** Framework **ships default folio types** (repo-docs, curriculum, feature-drip).
- The old mechanical relationships (batch / variant / rendering / series / campaign) are demoted to
  a secondary **`relation`** tag.
- **Output = artifacts + a manifest** (CSV/spreadsheet, a slice of the SSOT). **n8n picks up the
  manifest and runs the timed workflow.** No publishing/platform-pushing in the pipeline.
- **Boundary with composite/split:** a folio = multiple **standalone** things; a **composite**
  artifact or a **split** deliverable = internal parts of **one** thing. Test: *independently
  publishable → folio; only meaningful together → composite/split.* (A 5-part LinkedIn series = a
  folio; a slide deck = one composite artifact.)
- **Consistency spectrum:**
  - **v1 (build):** folio as a first-class tracked object (id + purpose + `relation` + ordered
    member list); 2–3 shipped folio types; members generated with **shared grounding + roster
    awareness** (each member gets the list of sibling roles for light cross-linking); manifest emitted.
  - **Deferred hook (designed now, see §5):** **deep correspondence** — a member generated *from*
    another (answer-key from exam; part 3 citing part 1).

### 3.8 Overrides & the three cascades

**"Precedence" is three distinct mechanisms, not one stack.** Unifying principle: **the most
local / specific / immediate layer wins.** Collapsing them reintroduces blur.

| # | Mechanism | Orders *what* | Order | Stage |
|---|---|---|---|---|
| 1 | **Entry resolution** (shadowing) | which *definition* of an id you load | framework → instance-global → workspace | load-time |
| 2 | **Value binding** (override) | what *value* a field takes in one artifact | entry-default → platform-layer → recipe → run | compose + render |
| 3 | **Preference weighting** | how scored sources are *weighted* for conflict | workspace-default → goal-implied → explicit-recipe → run | ground-time |

- **Mechanism 1 — field-level MERGE** (Fork B): a redefining layer overrides only the fields it
  specifies and **inherits the rest** (so you never clone a whole entry to tweak one attribute).
  Cost: an upstream change to an unpinned field can reach you — made visible by provenance.
- **Mechanism 2:** voice sliders and format constraints ride this same cascade. Constraint fields
  additionally get a **feasibility check → reconciliation** (§3.5). **Fork A:** a recipe/run **can
  override a platform's mechanical constraint, with a warning** (sovereignty + warn-don't-block).
- **Mechanism 3:** **Fork C:** later layers **adjust** the weight vector (not replace) — a goal
  nudges the workspace baseline.
- **Schema-level default** (§3.10) is the **floor** beneath Mechanism 2 — the ultimate fallback for
  an attribute nobody set.
- **Free-text attributes override wholesale** (no partial-merge — you can't merge two prose blobs).

### 3.9 Provenance vs. scope

Two **independent** classifications, each encoded where it enforces best:

- **Provenance** (framework-shipped vs. instance-authored) → **metadata tag**
  (`provenance: framework | instance`). Required because the framework ships **real default entries**
  (standard voices, default platform profiles, default recipes) — not just templates — and those sit
  in the same shared dir as a user's global additions, so location can't tell them apart. Also what
  Mechanism 1 needs to order the cascade, and what lets CI distinguish defaults from leaks.
- **Scope** (global vs. client-specific) → **location**: shared `<dimension>/` = global;
  `workspaces/<client>/<dimension>/` = that client only. Makes client isolation **structural**
  (durable rule 2) rather than asserted; keeps CI simple. A workspace *is* a directory, so scope
  maps to location with no friction.
- **Uniform across everything:** the shared-dir + workspace-dir + override pattern applies to
  Topic, Persona, Format, Voice, Goal, **source instances, and shipped recipes** — not just topics.
- **Client overrides = partial entries** under `workspaces/<client>/<dimension>/` with
  `extends: <global-id>` + field-merge (Mechanism 1). Replaces the vaguer `overrides/` idea.
- **Framework version bump:** default offerings update; user content stays untouched; backward-compat
  keeps things working; an **upgrade notice** reports what changed (§3.10).

> **Changes vs. mission / durable rules:** Rule 4 **narrows** from "public repo stays empty of
> *content* (only `*.template.*`)" to **"public stays empty of client-*specific* content"** — generic
> framework defaults are welcome. `scripts/check-no-content.sh` must change from "reject any
> non-template registry file" to "reject any `provenance: instance` entry, and any non-template file
> under `workspaces/*`." **Action item — not yet applied.**

### 3.10 Schemas & versioning

- **Formal per-dimension schemas** (framework-owned): each declares its attributes with a **type**,
  a **default**, a prose **definition**, and a **`definition_version`**, plus a **schema version**.
  Several earlier mechanisms (Mechanism 1 merge, provenance defaults, backward-compat) assume this
  exists — so this makes the attribute sets formal.
- **Attribute types span a spectrum:** constrained (`enum`, `slider(1-5)`, `range`, `ref`, `number`)
  to free (`text`/`markdown`). A schema is a **typed field manifest, not a straitjacket.** Free-text
  attributes get weaker validation and **wholesale override**.
- **Closed, but instance-extensible.** Undeclared attributes are **rejected** (open schemas were
  rejected as a swamp — no meaning, nothing applies them, no default, future-collision risk). To add
  a custom attribute you **extend the schema** at the instance level (same provenance model), which
  forces a type + default + definition; **namespace** instance attributes to avoid future collision
  with a framework attribute; any collision is detected by the version-stamp/provenance machinery.
  Principle: **extend by declaring, never by smuggling undeclared data.**
- **Schema-level defaults = the cascade floor** — a brand-new framework attribute falls back to its
  default for every pre-existing user entry, so nothing breaks and no files move.
- **Additive-only evolution + deprecation lifecycle:** new attributes are optional-with-defaults;
  never rename/repurpose in place; genuine breaking changes go through *mark deprecated → keep
  working N releases → migration note / optional shipped migration script → remove*.
- **Meaning vs. wording (facet-3 nuance):** forbidding change is about **meaning**, not wording.
  - `definition` (prose) is **freely improvable** — clarifying/tightening is encouraged and
    non-breaking (optionally noted in the upgrade notice as "clarified — meaning unchanged").
  - `definition_version` is bumped **only on a meaning change**, which triggers drift detection +
    the deprecate/migrate path. Maintainer judges; if unsure, treat as a meaning change.
- **Semantic-drift safety net:** every **entry stamps the `schema_version` it was authored under**;
  every attribute carries a `definition_version`. On a bump, the resolver compares them and the
  **upgrade notice flags** entries whose attributes were redefined since — never a silent misread.
  Clean remaps (e.g. 1–5 → 1–10) ship as migration scripts. This is the teeth behind Decision 2's
  "each score defined once."
- **Upgrade notice** on `update-from-upstream`: added attributes (now on defaults), added default
  entries, deprecations (with removal target), redefinitions to review, new dimensions available.

---

## 4. Decision log (1–9)

Each: the decision, key rationale, v1-vs-deferred, and what it changes vs. `mission.md`.

### Decision 1 — Goal / CTA
- **Decision:** Goal is a **content dimension**, **set-valued within one artifact**; a CTA is a goal
  with `kind: action` (not separate machinery); multiple goal-sets → multiple artifacts (in scope).
- **Rationale:** change the goal and the substance changes (axis test #3). An artifact routinely
  serves several goals at once.
- **v1:** full. **Deferred:** none.
- **Changes vs. mission:** mission had no Goal axis; tone/CTA weren't modeled. New dimension.

### Decision 2 — Source abstraction
- **Decision:** pluggable **adapter (type) + instance (bound config)**; instances carry
  characterization scores + content-kind tags; select **by characteristic, not identity**; union +
  conflict→AMBIGUOUS+warn; workspace pool + recipe subset; Source = factual grounding only.
- **Rationale:** generalize beyond Graphify; make conflict principled; keep goals↔sources decoupled.
- **v1:** adapter/instance model, Graphify adapter, scores, union/conflict. **Deferred:** more
  adapters (url/pdf/db) as plugins.
- **Changes vs. mission:** mission assumed Graphify-over-a-repo as the only source. Generalized.

### Decision 3 — Override precedence
- **Decision:** **three** cascades (entry resolution / value binding / preference weighting), unified
  by "most local/specific/immediate wins." Fork A: recipe/run can override platform constraints with
  a warning. Fork B: field-level merge. Fork C: preference weights adjust, not replace.
- **Rationale:** these order different things at different stages; one linear stack would blur them.
- **v1:** full model. **Deferred:** none (weight-combination tuning could settle at build).
- **Changes vs. mission:** mission had no explicit precedence model.

### Decision 4 — Provenance & scope
- **Decision:** provenance → metadata tag; scope → location; uniform across all dimensions + sources
  + recipes; client overrides via `extends:` partial entries; framework ships real default entries.
- **Rationale:** each classification uses the representation that enforces it best; shipping defaults
  requires provenance ≠ location.
- **v1:** full (representation is provisional — maintainer had no strong preference).
- **Changes vs. mission:** **narrows durable rule 4**; changes the CI guard (see §3.9 action item).

### Decision 5 — Mechanical reconciliation
- **Decision:** render-stage, non-destructive; selectable strategy (`adapt`/`split`/`pass`/`truncate`),
  **default auto-`adapt`/`split`, always warned**; covers length + capability mismatch.
- **Rationale:** total freedom for *taste*, reconciliation (not prohibition) for *physics*; product
  goal is platform-ready drafts, and the artifact is never lost.
- **v1:** full. **Deferred:** none.
- **Changes vs. mission:** replaces mission's compatibility-filter/exclusions with freedom +
  reconciliation.

### Decision 6 — Naming / lexicon
- **Decision:** `dimension`, `entry`, `attribute`, `registry`, `recipe`, `artifact`, `deliverable`,
  `folio`, `selection`, `fanout` (see §2). Keep both artifact and deliverable.
- **Rationale:** precision; "axis" was imprecise; artifact vs. deliverable is a real split.
- **Changes vs. mission:** renames "axis" → "dimension"; introduces recipe/artifact/deliverable/folio.

### Decision 7 — Folios
- **Decision:** **purpose-driven package** with shipped default folio types; mechanical groupings
  demoted to a `relation` tag; output = artifacts + manifest for n8n (no in-pipeline publishing).
- **Rationale:** real-world folios are purpose/role-defined, not mechanically-defined.
- **v1:** shared grounding + roster awareness. **Deferred hook (designed now):** deep correspondence.
- **Changes vs. mission:** mission had no folio concept.

### Decision 8 — Composite formats (folded into the IR)
- **Decision:** compositeness is a **Format `parts` attribute**; the **artifact is a document IR**;
  **output-type is a rendering lever, not Format**; **renderers are a pluggable registry** (Pandoc
  family, external tool); IR = Markdown-envelope. Per-part overrides = per-part IR sub-trees riding
  the cascade.
- **Rationale:** the IR completes the content/rendering split, isolates rendering, enables free
  re-render, and subsumes composite formats.
- **v1:** IR + md/html/pdf/docx renderers. **Deferred:** exotic renderers (pptx/epub) as plugins;
  per-part override *implementation* to confirm at build (the model supports it).
- **Changes vs. mission:** introduces the IR + renderer architecture; output-type off the Format axis.

### Decision 9 — Schema versioning
- **Decision:** formal per-dimension schemas; **closed but instance-extensible** (namespaced);
  schema-level defaults as the cascade floor; additive-only + deprecation lifecycle; **meaning vs.
  wording** split (`definition` free to improve, `definition_version` bumps only on meaning change);
  per-entry `schema_version` stamp + attribute `definition_version` as the drift safety net; upgrade
  notice.
- **Rationale:** let the framework evolve without breaking instances; make drift detectable not silent.
- **v1:** schemas + defaults + stamps + notice. **Deferred:** migration-script tooling as needed.
- **Changes vs. mission:** formalizes schemas; extends mission's "additive/deprecate" rules.

---

## 5. Deferred-but-designed hooks

Designed for now so the later add is a simple, backward-compatible extension.

- **Deep folio correspondence** — a member generated *from* another. Reserves in v1: folio modeled as
  a **DAG of member roles** with optional `depends_on` edges; member-generation **context is a
  structured object with an (empty in v1) slot for upstream member artifacts**; the **manifest carries**
  dependency/order metadata; the **identity scheme reserves upstream-artifact provenance** so a
  derived member is reproducibly tied to the version it came from.
- **Sequenced folios** (`series`, `campaign`) — as `relation` kinds, needing cross-artifact context.
- **Exotic renderers** (pptx slide decks, epub) — added via the renderer registry.
- **Per-part dimension overrides** — the model supports it (a part is a layer in Mechanism 2); v1
  implementation to confirm at build.
- **Language / localization rendering-fanout** — one artifact → N localized deliverables.
- **n8n scheduling execution** — the pipeline emits the manifest; n8n runs the timed workflow (Phase 2).
- **More source adapters** (url/pdf/db) beyond Graphify.

---

## 6. Open areas not yet worked

- **Agents & skills — two planes** (next major area):
  - **Product plane** (the client deliverable): `researcher`, `writer` (now **emits the IR**),
    `editor/reviewer`, a deterministic **`render`** stage, and skills (`ground-repo`, `persona-voice`,
    `format-spec`, `select-and-fanout`, `voice-from-examples`, …). Symmetric **source adapters** and
    **renderer adapters**.
  - **Framework-ops plane** (build/maintain *this repo*): `architect`, `planner`, `coder`, `reviewer`.
    Different audience (maintainer vs. client) and subject (framework-self vs. client-content). Must
    be **visibly separated** from product agents in `.claude/` (subdir/naming) so they're never
    shipped/confused as client tools. **Bootstrapping angle:** stand up the ops plane first, then use
    it to design/implement the product plane and the rest of the framework.
  - **Open sub-questions:** organization/naming of the two planes under `.claude/`; how the IR /
    renderer / adapter reshaping changes each product agent's contract.
- **The maintainer's remaining un-enumerated design points** ("I have not gotten to everything").
- **Mission open decisions, now partly informed:**
  - **D1 serialization** → leaning YAML-frontmatter + Markdown for entries; envelope+Markdown for the IR.
  - **D2 item identity** → coordinate + source-commit slug; extends to deliverables
    (`artifact-id` → `{deliverable-id per output-type/platform/language}`); reserves upstream-artifact
    provenance for deep correspondence.
  - D3–D7 still open.
- **Resolver implementation, selection/config format, and the manifest/CSV ↔ n8n handoff specifics.**
- **Post-formal-design repo cleanup / reconciliation pass.** Once the formal design is done and
  **approved**, sweep the repo for **stale items** left by this redesign and reconcile them in one
  pass: `docs/mission.md`, the `*.template.*` files (to the new schema/lexicon), `.claude/readme.md`,
  `state.template.md`, `quickstart.md`, `README.md`, and the `docs/*` set — plus **apply the deferred
  `check-no-content.sh` guard change (§3.9).** Nothing should be edited to match the redesign until
  the formal design is approved, so the stale items are expected and tracked, not fixed piecemeal.

---

## 7. Changelog

| Date | Change |
|---|---|
| 2026-07-06 | Initial capture: lexicon (§2), full conceptual model (§3), decision log 1–9 (§4), deferred hooks (§5), open areas (§6). Working doc — not yet authoritative; `mission.md` not yet reconciled. |
| 2026-07-06 | Narrowed CLAUDE.md rule 4 (public repo now allows `provenance: framework` defaults); guard-script change deferred. Added §6 item: post-formal-design repo cleanup/reconciliation pass. |
