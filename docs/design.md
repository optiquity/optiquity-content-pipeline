# Optiquity Content Pipeline — Definitive Design

> **Status: FINAL — post-B4 amendments and verification-pass fixes applied.** The B1 detail fill
> of the approved skeleton (skeleton-v2, A4-approved), repaired against the B2 adversarial
> findings (B3; dispositions in `design-fix-ledger.md`), then amended per the ratified B4 walk —
> the entry-identity ruling, B4-1 (D2 id encoding), B4-2 (folio-type coherence binding), B4-3
> (member-role locus), B4-4 (lease-steal repair), B4-5 (register dispositions) — and the ratified
> force-re-reconcile package FR1–FR6 with its FR7 serialize-level extension. This document lands
> at `docs/design.md` and is the single design SSOT (see §1).

---

# PART I — FOUNDATIONS

## §1 Status, authority & how to read

**What this document is.** The single, authoritative design specification for the
optiquity-content-pipeline framework. Every design statement in it is normative. It supersedes all
prior design documents; the supersession map — which old document (and which section of it) each
part of this document replaces — is Appendix B. **On any conflict between this document and any
prior design doc (`docs/design-decisions.md`, the design sections of `docs/mission.md`, any pass
report), this document wins.**

**Provenance chain.** Every statement here traces to a maintainer-ratified ruling. The design was
produced by a ruled process: an adversarial decision walk over the working conceptual model, a
series of focused architect passes, maintainer rulings on every surfaced decision (Q-, F-, SM-,
RS-, CA-, BO-, CM-, SV-, MIG-, RI-, PD-, API-, PC-, D1-series, plus the folio DIRECTIVE, the
Phase-A rulings A4-1..A4-4, the Phase-B rulings — the entry-identity ruling and B4-1..B4-5 — and
the force-re-reconcile package FR1–FR7), then a skeleton-first reconciliation (Phase A), this
all-parts detail fill (Phase B), and the post-B4 fix pass that applied the ratified amendments. The full decision record is imported to `docs/archive/design-record/`
(Appendix B); the process itself lives in `docs/ops-workflow.md`, not here.

**Ruling tags.** Statements cite their ruling inline in parentheses — e.g. `(Q17)`, `(CA6)`,
`(DIRECTIVE)`, `(A4-4)`. Appendix A is the full tag → section cross-index. Tags are traceability,
not authority: the authority is this document's text.

**Notation.** The schema-migration package's components are written **MIG-1…MIG-7** throughout
(they were logged under labels that collided with the combine-mode ruling tag CM3; Appendix A
records the disambiguation). A retracted first migration design exists only as a rejected-record in
Appendix B and has no design home.

**How to read.** Part I states the invariants. Part II is the content model (what things are).
Part III is the configuration model (how values are declared, versioned, and resolved). Part IV is
the generation pipeline (how an item is produced). Part V is the external contract (how actors
drive the system). Part VI is operations and evolution. Terms are defined once, in §4, and used
consistently everywhere. §27 is the document's own open-items register: everything not designed
here is named there — nothing is silently open.

## §2 System overview & the responsibility boundary

### §2.1 The life of one item

The framework turns grounded facts about a client's repositories into publishable content items
across a matrix of editorial and rendering choices. One item's life, end to end — each stage's full
specification is in the referenced section:

1. **Ground** (§6). The resolver assembles the workspace's source pool, applies the effective
   source-selection expression (hard `require`/`span` clauses, soft `prefer` weights, an
   `on_conflict` strategy), queries the surviving source instances, unions the grounding, and
   computes per-fact confidence tiers and scores. Only EXTRACTED-tier facts may be asserted as
   published fact — a framework invariant beneath all user configuration (§6.5).
2. **Resolve & bind** (§12). The value cascade resolves one effective entry per dimension
   (Mechanism 1), then binds attribute values across the scope spine (Mechanism 2), type-driven.
   Content-dimension bindings feed `artifact-id`; rendering-dimension bindings feed
   `deliverable-id` (§7).
3. **Compose** (§15). The writer produces the artifact — a persisted, platform-agnostic
   **IR-canonical** document (JSON envelope, Markdown leaves, a per-fact grounding ledger). This is
   the expensive LLM step, done once per `artifact-id`.
4. **Reconcile** (§16). Per rendering target `(platform, language)`, an LLM pass reshapes the
   content to fit — localize, then reshape, then a terminal hard-limit gate that fits or blocks,
   never silently passes. Output: a persisted **IR-fitted** variant keyed by `fitted-id`. Skipped
   entirely when no fitting is needed.
5. **Serialize & dispatch** (§17). A deterministic, LLM-free transform produces the layer-3
   **Pandoc AST** (always persisted), then either renders bytes in-system (`side: internal`) or
   emits the layer-3 contract payload for an external renderer (`side: external`). A new
   output-type or presentation on an existing AST is one writer call — no LLM.
6. **Review** (§19). Two gates: an artifact review on the IR (early, once, pre-fanout) and a
   complete deliverable review on every shipped deliverable.
7. **Retrieve** (§21). Every durable product — artifact, fitted AST, deliverable, part, folio — is
   addressable by a stable id through the external-actor API. Folios group artifacts by purpose;
   `emit-manifest` produces a point-in-time work order for an external publisher. **Publishing is
   not a stage of this system** (§2.2).

**Upstream of stage 1 sits ideation/topic-sourcing** — the product-plane activity that turns a repo
plus an audience into a ranked queue of content ideas. It precedes "ground", is product-plane, and
has **no ratified contract**: nothing about it is designed in this document. It is registered as an
open area at §27.4.

### §2.2 The responsibility boundary

The system's responsibility is fixed (F10 cross-cutting boundary; RI15):

- **In scope:** (1) **rendering** — the reshape/reconcile pass that fits the IR to a platform
  (§16); (2) **output-doc generation** — the deterministic serialize pass that produces output
  documents (Markdown, PDF, docx, and others) from the IR (§17). The system produces the rendered
  **deliverables** and the **folios**, persists them, and makes them **accessible by id for later
  use** (§18, §21).
- **Out of scope, always:** **publishing.** Pushing or posting any output to any destination, and
  the ordering/scheduling of publication, belong to an external actor (e.g. n8n). The system holds
  no publication order at all: a folio carries no ordering or schedule (§9.1, A4-4), and the only
  sequence the system tracks is intra-work part sequence inside a single split deliverable (§9.5).
- **The system's responsibility ends at the rendered output document plus the id-accessible
  folio.** It never publishes (RI15).

The commitment line to a platform is the **reconcile pass**, and it is a **cost boundary, not a
lock** (RI10): IR-canonical is persisted, so re-targeting content to a new platform is always
possible by one re-reconcile — never a re-compose. See §18.

## §3 Governing principles (framework-wide invariants)

Each invariant is stated once here; its enforcing mechanism is homed at exactly one later section.
This section is an index of invariants, not a second authority.

### §3.1 No-overstep

The system **never bends user configuration on its own initiative** (Q3):

- It treats user-set limits and configuration as **authoritative and fixed**; it never interprets a
  configured setting as flexible.
- When the user's own configuration will cause a problem, the system **warns about the consequence
  of the user's own decision** — it does not silently "fix" it.
- "Override with a warning" is therefore always the **user's** act; the system surfaces the
  warning, it never overrides unilaterally.
- Respecting an **external** physical constraint (a platform's hard character limit) by reshaping
  content to fit is honoring a constraint, not overstepping (§16). Refusing to act — blocking — is
  likewise never an overstep (§6.4, §11.5).
- Advisory outputs (lint warnings §8, `recommended_width` §22.5, relaxation suggestions §26) are
  **never auto-applied**.

Enforcement homes: §6.4 (grounding blocks), §8 (advisory lint), §12.7 (advisory-vs-hard
constraints), §11.5–§11.6 (drift/migration blocking), §16 (fit-or-block gate), §20 (mutation
boundary), §22.5 (advisory width).

### §3.2 Extend, don't edit — and one-file extensibility

Instances **add** files; they never edit framework-shipped files, including shipped
`provenance: framework` registry entries — customization happens through workspace `extends:`
partials (Q15). Adding a value to any dimension, registry, or collection is a **one-file change**;
if it requires a second edit, that is a defect. Mechanisms: §10 (provenance/scope and the public
boundary), §5.4 (the one-file-add acceptance test), §11 (schemas that make additive evolution
safe).

### §3.3 Grounding & no-secrets discipline

Factual and technical claims ground in EXTRACTED facts; INFERRED/AMBIGUOUS material is a lead to
verify, never published fact (§6.5). Every item records its workspace, source repo, source commit,
and confidence tiers (§15). **No secrets or credentials from graph nodes ever surface into any
output, any persisted record, or any telemetry** (RI3, PC11c): the grounding ledger stores ids,
anchors, and commits — never secret values (§15); the serialize pass strips provenance attributes
from writer targets that would otherwise emit them (§17); operational telemetry is content-free
(§22.5).

The **transport keystore** (§21.10) applies the same discipline as a **two-layer split**: a
NON-secret **handle** (`<namespace>:<name>`) is what lives in config, argv, and the ledger; the
**secret value** lives only in the 0600-per-handle store under `$OPTIQUITY_SECRETS_DIR`, is resolved
at use time, and NEVER enters argv, a log line, the spend ledger, or telemetry (I5). The **weekly
spend meter** ledger obeys the same **no-secret rule** — it records the non-secret handle, the
scope-id, the week-key, and dollar amounts only; a secret value never appears in a settled ledger
line or a hold.

---

# PART II — THE CONTENT MODEL

## §4 Lexicon

The nesting `dimension ▸ entry ▸ attribute` is load-bearing; keep the three levels distinct.
Definitions here are normative; where a term's old meaning is superseded, the new meaning is stated
and the old one is dead (Appendix B archives it).

> **Naming note (DR-2, C1-review N2).** This section — "§4 Lexicon", the design's terminology
> glossary — is DISTINCT from the DR-2 content-side **`lexicons/`** registry (the house-style
> entries applied at compose, §5.2/§7.2/§12.6). Same word, unrelated constructs; the collision is
> flagged here, not resolved by a rename.

| Term | Meaning |
|---|---|
| **dimension** | One of the nine orthogonal design axes (§5). Content: Topic, Persona, Format, Voice, Goal. Rendering: Platform, Language, Output-type, Presentation. Characterized by facets (§5.1), not by ad-hoc kinds. |
| **entry** | One whole populated value of a dimension (the `hiring-manager` persona; the `business` voice). One file. **An entry's id = its frontmatter `id` = its filename slug** (the entry-identity rule, §11.1). This is what you **select**. |
| **attribute** | One named, schema-declared field inside an entry (`persona.knowledge_level`). This is what you **bind or override** at fine grain. |
| **registry** | The collection (directory) of entries for a dimension or other collection (content-kinds, render targets, folio types, recipes). |
| **schema** | The co-located `_schema.yaml` declaring a collection's typed attributes, defaults, definitions, and versions (§11). |
| **recipe** | A reusable binding of one entry per content dimension + a goal-set + configured values → **one artifact**. May pin rendering targets. |
| **selection** | A multi-select input across dimensions that **fans out** into many recipes/items (§8). |
| **fanout** | Expansion of a selection into concrete, id-keyed, idempotent items. Content fanout → distinct artifacts; rendering fanout → many deliverables of one artifact. |
| **artifact** | The composed, platform-neutral piece. Physically it **is** the IR-canonical document, keyed by `artifact-id` (§7, §15). |
| **IR** | The intermediate representation: JSON envelope, Markdown leaves, grounding ledger (§15). Two persisted states: **IR-canonical** (platform-agnostic, per artifact) and **IR-fitted** (per platform/language, output of reconcile). |
| **AST** | The layer-3 Pandoc AST (JSON): the deterministic serialization pivot every output passes through (§17). |
| **deliverable** | One rendered output: `deliverable-id = fitted-id + (output-type, presentation)` (§7). One artifact → N deliverables. |
| **part** | An addressable sub-unit of one artifact or deliverable: composite-format parts `(artifact-id, part-id)`; reconcile-split parts `(deliverable-id, part-id)` (§9.5). |
| **render target** | An entry in the render-target registry: a Pandoc writer + `side` setting + pins (§17). The renderer is a thin dispatcher over these. |
| **source / adapter / source instance** | A read-only grounding provider. Adapter = the type (capabilities); instance = bound config (connection + characterization scores + content-kind tag) (§6). |
| **content-kind** | A registry classifying what a source's content *is* (merged code, research papers, marketing copy…), carrying default content-property scores (§6.1). |
| **grounding ledger** | The IR's per-fact map: tier, source instance, repo, commit, traceability anchor, scores snapshot (§15). |
| **confidence tier** | Per-fact EXTRACTED / INFERRED / AMBIGUOUS — *how sure*. Orthogonal to `traceability` — *can you cite it* (§6.5). |
| **folio** | A **pure purposeful set**: an addressable, durable collection of artifact references with a purpose — and nothing more. No dimension values, no rendering intent, no ordering, no schedule, ever (§9.1; DIRECTIVE, A4-4). |
| **folio type** | A framework-shippable blueprint declaring a typed folio's member **roles/structure** — never dimension values (§9.6). |
| **member record** | The per-member data a folio holds for one artifact reference: `{added_ts, pin?, role?}` (§9.2). |
| **manifest** | The output of `emit-manifest`: a **generated, point-in-time downstream work order** for an external publisher, pinned to member ids and commits. It is **not** a slice of the SSOT, is never written into the SSOT, and is deterministically regenerable (§21.5; F7/Q9 — this supersedes the archived "slice of the SSOT" definition). |
| **override** | Reserved term: an **ephemeral, run/session-layer (L6) value binding** — collected at `begin-session`, applied at M2 bind, captured in identity, never persisted (§12.5; CA5). Persistent-scope bindings are **configured values / scope defaults**, not overrides. |
| **configured value / scope default** | An attribute value carried at a persistent scope (global L2, workspace L3, recipe L5) (§12). |
| **claim / lease** | The concurrency lock unit: an atomically-created claim file (filename = the claimed id) with `{holder, lease_expiry}` (§22.3). |
| **plan / wave / shard** | The parallelization plan: waves = dependency depths of mutually independent id-keyed units; shard = a unit's root `artifact-id` grouping tag (§22.2). |
| **actor** | Who drives the system. Internal: the co-located interactive session. External: a stateless caller (n8n, wrapper app) holding its own session state (§20). |
| **session / token** | One generation run's ephemeral state, carried entirely in an actor-held token; the system persists none of it (§20). |
| **run / generating run** | One execution; its id is stamped on every artifact it produces as immutable lineage (§7.1, §9.4). |
| **workspace state** | Durable, system-side, per-client state: registries, config, folios, artifacts, deliverables, claims (§20). |
| **pins** | The reproducibility set a run stamps: global `schema_version`, the source commit-map (§7.2), render tool bundle (§21.8); suppliable explicitly at `begin-session` (§21.8). |
| **SSOT** | The tracking spreadsheet — sole authority for the status/progress domain, and only that domain (§24, §22.7). |
| **provenance / scope** | Provenance = who authored it (`framework|instance`), a metadata tag. Scope = where it applies (global vs `users/<user>/workspaces/<workspace>/`), encoded by location (§10). |

## §5 Dimensions

### §5.1 The faceted model

A dimension is characterized by four orthogonal facets (Q5) — adding a dimension means picking a
cell in each facet, never inventing a new kind:

| Facet | Values | Meaning |
|---|---|---|
| **role** | `content` \| `rendering` | Content dimensions shape substance (cross-product → distinct artifacts). Rendering dimensions package/route one finished artifact (→ many deliverables). |
| **representation** | `discrete-registry` \| `parametric` \| `scalar-parameter` | Directory of entries; presets+sliders; or a plain parameter (possibly a small registry). |
| **cardinality** | `single` \| `set` | Per artifact. Set-valued means one artifact carries a set (Goal); for every other dimension multi-select = fanout. |
| **override-projection** | `yes` \| `no` | Whether the dimension's entries project cross-dimension values into the cascade (Platform does: advisory constraints, per-format reconcile-strategy defaults, + a default output-type; §12.3). |

The dimension inventory as tuples:

| Dimension | role | representation | cardinality | override-projection |
|---|---|---|---|---|
| Topic | content | discrete-registry | single | no |
| Persona | content | discrete-registry | single | no (provides `default_voice` ref, consumed by Voice; §12.3) |
| Format | content | discrete-registry | single | no |
| Voice | content | parametric | single | no |
| Goal | content | discrete-registry | **set** | no |
| Platform | rendering | discrete-registry | single | **yes** |
| Language | rendering | scalar-parameter | single (set → fanout) | no |
| Output-type | rendering | scalar-parameter / small registry | single (set → fanout) | no |
| Presentation | rendering | discrete-registry | single | no (PD1) |

### §5.2 Content dimensions

**Topic — what is it about, and why it matters.** Owns the subject matter (grounded in sources)
plus `why` — the editorial significance. Never touches audience, structure, destination, or the
persuasion objective. Universal-archetype vs bespoke topics are handled purely by **scope** (§10):
shared registry vs `users/<user>/workspaces/<workspace>/topics/` — no special archetype mechanism.

**Persona — who is it for.** Owns **audience facts only**: role/relationship, knowledge level,
motivation, objections, credibility signals — plus a **`default_voice: <ref>`** to a Voice entry
(Q6). Persona owns **no** register/affect: all of that is Voice. A persona is a coherent bundle
(its attributes co-vary); reading context ("skims on mobile") is Platform's, not Persona's.
`persona.default_voice` is the sole cross-dimension *default* provider for Voice; its cascade
placement is §12.3.

**Format — what shape/genre.** Owns the rhetorical structure/genre; it shapes the IR's structure
(§15). Formats are **platform-agnostic genres** (`short-opinion-post`, `long-form-essay`,
`readme`); there is **no `valid_platforms` attribute and no hard compatibility data on any Format
entry** (Q4 — pairing is user-driven, §8). A format may declare **`parts`** — an ordered list of
named **intra-genre** sub-outputs (`slide-deck → [slides, presenter-notes]`), defined entirely
inside the one governing Format entry (Q14). One format selected → one artifact with named parts.
Composing two genres = **two artifacts**, grouped by a folio — never a composite. The framework
ships an **`outline`** Format (DR-3) — a single-part, non-parametric, platform-agnostic planning
scaffold (`parts` rides the `[]` floor, like `readme`) — the genre an editable outline realizes as
when emitted (§15).

A Format may ALSO declare a **`section_schema`** (DR-4) — its **base genre section contract**: an
ordered list of typed-section conformance rules in the C2 vocabulary
(`presence` / `order` / `count` / `length`, each keyed by a `role`- or `type`-axis selector, with
`error` / `warning` / `info` severity; floor `[]` = no contract, so every existing Format is
byte-safe). It records what a structurally well-formed instance of the genre looks like — the
framework **`academic-paper`** requires `abstract`/`methods`/`results` **role** sections, asks for
that order, and caps the abstract's length — and is enforced by the platform-neutral base
structural gate at compose (§15); a venue may tighten it per-format (`format_structural`, §12.7).
Distinct from `parts` (which packages intra-genre **sub-outputs**), `section_schema` constrains the
rhetorical body's own **heading skeleton**, so it is meaningful only on an **outline-shaped** body:
a `section_schema`-bearing Format that composes a NON-outline body is **EXEMPT** — never counted as
silently unconformant (a section contract has nothing to enforce against a bodyless/non-sectioned
artifact; the base gate no-ops rather than blocking). The section **`type`** carrier (`prose`,
`figure`, `table`, `callout`) is an OPEN one-file-add frozenset, not a closed enum; author-declared
**roles** (`abstract`, …) are open and are never `type` kinds. The section sentinels that mark that
heading skeleton are **ATX-only by design** (`#`…`######`) — SETEXT (`===`/`---`) and blockquoted
(`> ##`) headings fail **closed** to body (never a mistyped section), a deliberate, ratified limit (the
F1 grammar feeds only the conformance gates, never any digest, so broadening carries no identity
motivation; `---` cannot be disambiguated in F1's line-scanner without a fail-open mis-parse; and the
value is fully substitutable by writing `##`), not an open gap (see `known-issues.md` #3).

**Voice — how it sounds.** Owns all register/affect/manner: formality, humor, warmth, energy,
narrator-persona, plus free-text guidelines. Parametric: a named voice is a saved slider
configuration + guidelines; sliders are tunable at recipe/run. Voices are generatable from example
text ("Voice-DNA") and are INFERRED until reviewed. Guardrail: didactic function and reading level
are Persona (+ Format), never Voice sliders.

**Goal — what outcome the artifact drives.** A content dimension, **set-valued within one
artifact**: a recipe binds `goals: [...]` and the piece serves the whole set. Each entry is tagged
`kind: strategic | action`; a CTA is simply a goal with `kind: action`. Multi-select of goals
**stacks** into one artifact (the one fanout exception); goal *variants* as separate artifacts are
expressed as a list of goal-sets. The goal-set is canonicalized (`sorted`, deduped) into
`artifact-id` (§7.1). Goal entries may contribute source-selection clauses (§6.3) and weight
nudges (§12.7).

**The `lexicon` is NOT a content dimension** (DR-2). House-style — preferred/banned terms,
proper-name casing, spelling variant, and open `mechanical` rules — is carried by the **`lexicons/`**
registry (§7.2/§12.6) as a **class-(ii) SELECTION input**, resolved over the *existing* cascade at
**L3 (workspace) + L5 (recipe)** — recipe beats workspace — and applied prompt-only at compose. It
adds **no new dimension and no new cascade rung**: `CONTENT_DIMENSIONS` stays **4** (topic, persona,
format, voice) and lexicon rides `_WORKSPACE_KEYS` ONLY — **never global/L2 (F4a)** — with **L6
(run) DEFERRED**. It nudges *how* prose reads, never *what* it claims (§6.5); its sole identity home
is the §7.2 `artifact-id` preimage.

### §5.3 Rendering dimensions

**Platform — where it gets published.** A destination + constraint layer, selected
**per deliverable**: platform is routing, never an instance-wide baseline (CA8), and never a folio
property (§9.1). A Platform entry owns mechanical constraints in two ratified classes (§12.7):
**advisory norms** (ride the cascade; recipe/run may deviate with a one-time warning) and **hard
limits** (enforced only at the reconcile gate, §16 — never bound as cascade values). It may
declare per-format advisory constraint projections, per-format reconcile-strategy defaults
(§12.3), and a weak default output-type (§12.3).

**Language — which tongue.** A rendering dimension classified as a **reconcile-time LLM
transform** (Q13): localization is non-free and non-deterministic, produces a localized IR-fitted
variant, must preserve voice/content parameters and provenance bindings, and can alter length —
so hard limits re-validate after it (§16). The multi-language feature itself remains deferred
(§26); the classification is fixed now so the deferred feature drops into the reconcile pass
without redesign. Language is part of `fitted-id` (§7.1).

**Output-type — how it is serialized.** Selects the Pandoc writer (md, html, pdf, docx, …). A
Platform may default it; it is independently selectable; part of `deliverable-id`.

**Presentation — how it looks.** A new rendering dimension (PD1–PD8): a discrete registry of
typesetting/style entries; one entry = one brand's complete cross-target look. Facets:
rendering / discrete-registry / single / override-projection **no** (PD1).

- **v1 schema (minimal + grow-hook, PD2):** exactly the levers that are Pandoc flags, hashable
  files, or per-writer dispatch — `variables`, `highlight_style`, `template` (per-writer; pptx has
  none), `reference_doc` (docx/pptx/odt), `css` (html/epub), `pdf` (engine + options). `fonts` and
  `margins` ship *inside* `variables`. **`variables` is the guaranteed grow-later hook: no future
  typesetting need forces a schema break.**
- **Encapsulation (PD3, hard):** one interface — `resolve → lower(presentation, writer,
  output-type) → RenderInputs{flags, variables, assets+hashes, engine}`. The dispatcher (§17) sees
  only that flat struct; the pin bundle is its preimage. The html5/epub3 provenance-strip filter is
  **serialize-owned, never a Presentation lever** (a style unit must not be able to disable a
  grounding guarantee; §17).
- **Application & cost (PD4):** applied at serialize on the persisted AST — one writer call, no
  LLM, no re-serialize; the cheapest regeneration tier (§18).
- **Identity (PD5):** `deliverable-id` gains `presentation`; `artifact-id` and `fitted-id` are
  untouched (the AST is presentation-independent — one AST serves all looks). With the `plain`
  floor, shipping the dimension causes zero id churn (§7.2).
- **Delineations (PD6):** Format = content structure @ compose · Platform = routing/limits @
  reconcile · Output-type = writer selection · reshape = LLM content-restructuring @ pass 1 ·
  **Presentation = deterministic style @ serialize.** "Split into slides" is reshape; "make the
  slides corporate" is Presentation. Presentation only styles what exists.
- **Defaulting (PD7):** a built-in framework **`plain`** entry is the schema floor — Presentation
  is **not** in the mandatory-global set (§12.3); Pandoc's built-in look is the honest fallback,
  exactly as Platform is excluded.
- **External path (PD8):** Presentation does not own `writer` or `side` (those are render-target
  fields, §17). RenderInputs ride the identical channel internally and, for `side: external`, fold
  into the layer-3 contract payload (§17). Fixed-layout EPUB and bespoke PPTX styling are absorbed
  additively via `variables`/`template` keyed by writer — no special-casing.
- **The DR-5 `csl` citation-style lever (C7).** A per-venue **citation STYLE** file — a single
  writer-agnostic `.csl` path (NOT the per-writer `template`/`reference_doc` map, because a CSL
  style is writer-agnostic) that lets journals differ in citation / footnote style from ONE shared
  IR. It lowers to a **LABELED `RenderInputs.csl`** field (the ratified α seam), never an unlabeled
  asset: the dispatcher content-gates `--csl` **with** `--citeproc` and never emits it alone (pandoc
  ignores a standalone `--csl`), so `csl` is a STYLE override riding ON TOP of the content-driven
  citeproc enablement (§17), **never a toggle for it**. Empty = pandoc's default author-date style
  (the `plain` floor, PD7). Identity (PD5): the style choice rides the `presentation` coordinate,
  and the csl asset's content hash joins the serialize-inputs preimage **only when citeproc actually
  ran** — so a citation-less render under a csl-set look is byte-identical to `plain` (zero id
  churn), while an edited style churns the digest for citing renders only (§17 FR7.1).

Presentation inherits the standard registry machinery: schema-versioning (SV10), co-located schema
(SV4), `x-` instance namespacing (SV5), the provenance guard (Q15), schema-lint (SV11).

### §5.4 The matrix & one-file extensibility

The matrix is **nine axes**: five content dimensions (Topic, Persona, Format, Voice, Goal) × four
rendering dimensions (Platform, Language, Output-type, Presentation). A request selects entries;
the cascade resolves the effective selection (the emergent allow-list, §8); content fanout
produces artifacts; rendering fanout produces deliverables.

**No axis surface carries a folio value and no folio carries an axis value** (DIRECTIVE): the folio
is orthogonal to all nine axes; the former folio `rendering_intent` field does not exist anywhere
in the model.

**The one-file-add acceptance test.** Adding a value to any axis (or to any registry: content-kind,
render target, folio type, recipe) is exactly: create one file in the right directory, conforming
to the co-located schema. Nothing else changes — no index to update, no code to touch, no second
edit. A new entry participates immediately: it is selectable, cascades normally, and (for source
instances) becomes eligible for selection purely through its scores (§6.1). If any addition
requires a second edit, that is a defect to fix in the framework, not a convention to document.

## §6 Sources & grounding

### §6.1 Adapters, instances & attach tiers

A **source** is a pluggable, read-only grounding provider in two layers: the **adapter** (type —
`graphify`, `folder`, `url`, `pdf`, …) declaring query **capabilities**, and the **source
instance** (bound config) carrying connection details, **characterization scores**, and a
**content-kind** tag. Multiple instances of one adapter are normal and first-class. The workspace
declares the source pool; a recipe/run may select a subset (default: all).

Characterization attaches at **three tiers** (Q10):

| Tier | What lives here | Home | Mechanics |
|---|---|---|---|
| **Instance** | properties of the source's relationship/track-record: `trusted`, `independence`, `primariness` | attributes on the source-instance entry | provenance/scope (§10); no per-content variation |
| **Content-kind** | properties of what the content *is*: `authoritative`, `opinionated`, `freshness`-policy, `review_status` | a **content-kind registry** entry the instance tags into (SM5) | framework-shipped default kinds, one-file-add; an instance MAY override its kind's defaults via an `extends:` field-merge partial (Mechanism 1, §12.1) |
| **Per-fact** | properties computed on each retrieved claim: `corroboration`, `traceability`; the content-kind scores refined per-fact where the adapter classifies facts | attached at ground-time | recomputed each run, never persisted as config |

The `content-kinds/` registry is a small collection like any other: it inherits the provenance
guard (§10), schema-versioning (§11.7), and one-file extensibility (§5.4).

The `folder` adapter pins the git **HEAD** of a **git-checkout** folder — via the same read-only
`git rev-parse HEAD` fallback the `graphify` adapter uses — so it is **compose-capable** and its
§7.2 identity commit-map agrees with the §15 grounding ledger (`ground()` and `pin_commit()` report
the same commit; the CF-1 invariant). A **plain** (non-git) folder has no HEAD and stays commitless,
its mtime the freshness basis (§6.2). The adapter also takes a `budget` connection key bounding
grounded output to the first *N* query-matching paragraph-facts in its deterministic walk order — the
folder analogue of graphify's `--budget`; the cap is a deterministic, in-band truncation, not an
error.

### §6.2 The score set

The core score vocabulary is **eight scores**, each defined once in the source schema (§11.1) with
one fixed type and scale, so any two values of one score are comparable. Predicate operators
follow from the type (scalar → `>= <= > < ==`; categorical/ordinal → `== in` plus order
comparisons; boolean → `is`; date-window → `< Nmo`, `contains`, `overlaps`).

| Score | Attach | Type | Asserted/derived | Serves |
|---|---|---|---|---|
| `trusted` | instance | scalar 1–5 | asserted | selection; conflict priority |
| `independence` | instance (→ kind refine) | ordinal `first-party \| affiliated \| independent` | asserted (machine-hintable) | selection (compare, establish-authority) |
| `primariness` | instance (→ per-fact) | ordinal `primary \| secondary \| tertiary` | semi-derived | selection; conflict tie-break |
| `authoritative` | content-kind (→ per-fact) | scalar 1–5 | asserted default per kind | grounding weight; conflict priority (§6.3) |
| `opinionated` | content-kind (→ per-fact) | scalar 1–5 | asserted default per kind | selection/weight (not the inverse of authoritative) |
| `freshness` | content-kind policy / per-fact | date-window/range | derived (commit/mtime) | filter + weight |
| `corroboration` | per-fact | scalar 0–n | derived (independent-instance agreement after union) | upgrades confidence; complement of conflict-downgrade |
| `traceability` | per-fact | boolean (+ optional depth) | derived (resolvable anchor: file:line, SHA, URL fragment) | citability gate (§6.5, §19) |

Rulings on the marginals: **`review_status` is in v1** (SM6) — categorical
`unreviewed | reviewed | formally-vetted | unknown` at content-kind, refined per-fact where the
adapter exposes merge/peer-review state; it degrades gracefully to `unknown` (adapter availability
is verification gate G6, §27.2). **`volatility` is deferred to a designed hook** (SM7) — added
later as one score definition when a churn signal is confirmed (§26). **`coverage` is a
resolver-internal ranking metric** (SM8) — an instance tie-breaker beyond `trusted` +
`primariness`, not a user-facing characterization score.

Each score's schema declaration carries: `type` · scale/enum · `default` · prose `definition` ·
`definition_version` · asserted/derived/semi · attach tier. A user MAY assert a value over a
derived score; the assertion rides the cascade as the user's authoritative config (§3.1) and is
stamped for provenance; large divergence from the computed value fires a one-time advisory lint,
never a block or autonomous correction.

### §6.3 Selection grammar

Source selection is expressed by a **two-clause grammar plus coverage and conflict clauses**,
carried by Mechanism 3 of the cascade (§12.1 — M3 carries `require`, `span`, and `on_conflict`
alongside the weight vector):

```
source_selection:
  require:                        # HARD predicates — exclude; typed by the score
    - primariness == primary            # instance-scope: narrows the pool
    - freshness < 12mo                  # content-kind/fact-scope
    - corroboration >= 2                # fact-scope: drops facts after union
  prefer:                         # SOFT weights — rank, never exclude
    - authoritative: +2
    - independence == independent: +1
  span:                           # POSITIVE coverage requirement (a hard clause)
    content-kind: [first-party, independent]
  on_conflict: downgrade-AMBIGUOUS      # selectable strategy (default shown)
  grounding_posture: warn               # POLICY: warn (default) | block — advisory vs opt-in abstain
```

- **Hard vs soft is a property of the clause, not the score** (SM2): any score may appear in
  `require` (hard) or `prefer` (soft); only *scope* constrains (per-fact scores cannot select
  instances). `freshness < 12mo` and `prefer fresh` are both legal.
- **`prefer` never excludes.** Worst case it ranks the best available in-pool source first; every
  in-pool source already passed the hard gates, and the publish floor (§6.5) holds beneath
  everything.
- **`span`** requires ≥1 surviving instance per named member — the compare/contrast mechanism. A
  missing member blocks-and-reports like any unmet hard clause (§6.4).
- **`on_conflict` is a selectable, extensible LIST of strategies** (SM4): `downgrade-AMBIGUOUS`
  (default) · `preserve-and-attribute` (compare/contrast: the disagreement *is* the content, both
  facts kept and attributed) · `priority-wins` (weight-driven) · more addable, goal-driven,
  one-file-add. Two required strategy properties: **factual outranks opinion** — `priority-wins`
  and defaults leverage `authoritative`/`opinionated` so a factual claim beats a mere opinion in
  conflict; and **fact-vs-opinion-contradiction detection is an available capability** — a
  strategy can identify an opinion contradicting an authoritative fact and surface the
  contradiction itself, for goals like debunk / correct-the-record / fact-check.
- **`grounding_posture` is a cascading POLICY key** (DR-6, §6.5/§19): `warn` (default) | `block`,
  the closed set `GROUNDING_POSTURES`. It joins the authored layer keys as a 6th (beside
  `require`/`prefer`/`span`/`on_conflict`/`relax`) and resolves most-local-wins in M3's four-layer
  fold EXACTLY like `on_conflict` (run/recipe beats workspace; absent → `warn`). It is POLICY, not
  identity: it rides `plan_hash` via `selection_payload` (like `on_conflict`) but NEVER the
  `artifact-id` preimage. Its effect is §19's advisory-vs-abstain switch, never source selection.
- Goal entries contribute partial `source_selection` clauses over scores (never over ids) — e.g.
  `convince → prefer authoritative +2; require traceability`; `compare → span + preserve-and-attribute`.

Selection references **characteristics, never identity**: scores and content-kind tags only, never
source ids. Instance ids exist for provenance and addressing. A new instance with the right scores
is automatically eligible with zero recipe changes.

**Resolver walk (ground-time, per item):** assemble pool → resolve the effective
`source_selection` across M3's layers (§12.1) → instance-scope hard filter + span check → query
survivors, union grounding, keep each fact's originating instance + commit → compute per-fact
scores + tier → fact-scope hard filter + publish floor → rank via `prefer` + `trusted`/
`primariness` (+ internal `coverage` tie-break) → resolve conflicts per `on_conflict` → hand
grounded facts (provenance + tier + traceability) to compose.

### §6.4 Locality, relaxation & the empty pool

`require`/`span` clauses cascade with the rest of M3: later layers may add, tighten, or —
most-local-wins — **relax** an upstream hard clause (SM3). A relax is the **user's explicit local
act** and fires a warning ("run relaxed `require: X` set at workspace scope"); the system never
relaxes anything on its own initiative (§3.1). There is no `locked:` flag.

**Empty pool → block and report** (SM1). When a `require`/`span` clause — or an empty/missing
source pool — leaves an item with no usable grounding: **that item blocks, and the report names the
offending clause.** Other fanout items continue; blocked items surface in run `results` with code
`empty-pool` (§21.7). The user relaxes the clause or adds a source (their acts) and re-runs —
idempotent by `artifact-id` (§7.1). Blocking is the only behavior that neither oversteps the
user's hard config (substituting excluded sources) nor silently grounds badly (composing from
nothing); it is not a system veto — it is the mechanical consequence of the user's own clause.
A future advisory convenience — the system *suggests* a relaxation the user must confirm — is
deferred (§26) and is never auto-applied.

### §6.5 Confidence & citability

- **Tier ⟂ traceability** (SM9). The confidence tier (EXTRACTED/INFERRED/AMBIGUOUS) answers *how
  sure*; `traceability` answers *can you cite it*. They are independent axes: a fact can be
  EXTRACTED yet anchor-less, or INFERRED with a clean anchor. The review stage (§19) consumes
  citability independently of confidence.
- **The per-fact confidence pipeline:** base tier from the adapter → `corroboration` upgrade
  (independent confirmation across genuinely independent instances raises confidence — the
  positive complement of conflict-downgrade) → conflict adjustment per `on_conflict` →
  traceability computed.
- **The EXTRACTED publish floor is a framework invariant, outside user config.** Only
  EXTRACTED-tier facts are published as fact; INFERRED/AMBIGUOUS are leads to verify. No
  `require`/`prefer` configuration, no run, and no override can relax it. Reconcile and serialize
  never promote a tier (§16, §17). Enforcing this floor is a framework quality guarantee, never an
  overstep of user configuration.
- Every published claim's grounding — workspace, source repo, source commit, tier — is recorded in
  the artifact's grounding ledger (§15) and re-checked by the deliverable review (§19).
- **Review 1 audits grounding on two advisory dimensions** (DR-6, §19): **coverage** (a
  fact-asserting sentence carrying no grounding span) and **faithfulness** (a span whose bound
  ledger fact does not support the sentence). Both are `concern`-level, never a block — the
  EXTRACTED floor and tier-honesty stay hard at the IR gate (§15).
- **DR-5 citations are grounded by construction — the (b)-PROJECTED coupling** (C2/C4). A published
  `[@key]` citation is publishable only if it resolves to a **ledger-projected pool source**:
  compose PROJECTS the `references` bibliography from the grounding ledger's distinct pool sources
  (never author-written — a free bibliography is the fabrication vector, §15) and then HARD-resolves
  every composed `[@key]` against exactly that projected key set at the compose locus (an unresolved
  key blocks as `citation-unresolved` into the bounded re-ask, §15/§16). A citation therefore cannot
  name a source the pipeline did not ground — closing the fabrication leak with teeth, the analog of
  the `data-fact`→ledger structural check. **Accepted scope-limit (v1):** DR-5 cites **in-pool**
  works only; citing the broader out-of-pool literature (via a pool source's secondary attestation,
  the DR-6 two-scenario model + the §15 `attestation` carrier) is DEFERRED to **DR-6 scenario-2**,
  its ratified home (`docs/known-issues.md`).
- **The DR-2 lexicon shapes WORDING only — it mints NO fact** (C1/C3b). House style
  (preferred/banned terms, proper-name casing, spelling, `mechanical`) is a *style* transform
  applied **prompt-only** at compose; it never promotes an INFERRED/AMBIGUOUS lead to published
  fact and never adds a grounding-ledger entry. The EXTRACTED publish floor and the total-grounding
  rule (§3.3) hold unchanged — a lexicon changes only *how* a grounded claim is phrased, never
  *whether* it is grounded.

## §7 Identity & lineage

This section is the **single authority for the id family**. Every other section references these
definitions; none redefines them.

### §7.1 The id family

```
artifact-id     = hash( topic, persona, format, voice, sorted(goal-set),
                        source-subset, resolved-overrides, source-commit )        (Q17, CA6)
fitted-id       = (artifact-id, platform, language)                               (RI10)
deliverable-id  = fitted-id + (output-type, presentation)                         (Q17, PD5)
part addressing = (artifact-id, part-id)      — composite-format parts           (F9)
                  (deliverable-id, part-id)   — reconcile-split parts
generating-run  = run id, stamped on every artifact the run produced (lineage)   (F1)
```

- **`artifact-id`** keys the compose-once IR-canonical. It is the stable folio-membership key (F3)
  and the idempotency key for compose: re-running any item whose `artifact-id` already exists is a
  no-op (§21.8, §22.3).
- **`fitted-id`** is a **cache key, additive to the family** — a strict projection of
  `deliverable-id` with output-type and presentation dropped. It names the reusable reconcile
  output (IR-fitted + AST) so one LLM reconcile serves every output-type and presentation for a
  platform/language. It is also a **first-class claim key** in parallel execution (§22.3), so
  concurrent render units sharing one `fitted-id` run the reconcile exactly once.
  A fitted-id may additionally carry a **fit-revision qualifier** — `_<hex12>`, the digest of
  the reconcile-inputs preimage a forced re-reconcile was minted under (grammar §7.4; preimage
  §16). The unqualified fitted-id names the FIRST fit ever minted for the triple and is never
  rebound; which fit an unqualified render resolves to is the fit-resolution rule (§21.8).
- **`deliverable-id`** keys the serialized bytes and the render-binding (§17); idempotency key
  for render. Presentation is a `deliverable-id` coordinate only — never `artifact-id` (look ≠
  content) and never `fitted-id` (the AST is presentation-independent). A deliverable-id inherits
  any fit-revision qualifier through its fitted prefix and may carry its own **serialize-revision
  qualifier** — `_<hex12>` on the presentation segment, auto-minted when its serialize inputs
  evolve (grammar §7.4; preimage §17; resolution §21.8). Both qualifiers are digests of recorded
  input preimages, never counters.
- **`part-id`** makes every part its own addressable unit (own id, own bytes): a publisher
  addresses part 3/7 directly, no re-parse. Composite `part-id`s are stable and reproducible (they
  live in the IR); reconcile-split `part-id`s are stable within a *saved* deliverable but not
  guaranteed reproducible on re-chunk (§9.5).
- **`generating-run`** lineage is immutable and answers every "batch" question ("what did run X
  produce?") as a query by run / commit / date (§9.4). Overrides' effects are captured in identity
  and lineage (§12.5) — ephemeral as config, recorded in identity.
- **Folio ids** are workspace-scoped, system-assigned, stable (F8); fully qualified as
  `(workspace, folio-id)`. **Session ids** are ephemeral run handles carried only in the token
  (§20).

### §7.2 `resolved-overrides` = delta vs the schema-default floor

The `resolved-overrides` component of `artifact-id` is the **canonical per-dimension delta of
effective values vs the schema-default floor** (CA6): an attribute enters the hash only when its
effective value ≠ its schema default, organized per dimension, with sorted keys and the sorted,
deduped goal-set.

```
artifact-id = hash(
  { for each SINGLE-valued content dimension D in {topic, persona, format, voice}:
      ( resolved-entry-id(D),
        canonical-map{ D.attr : effective-value  |  effective-value ≠ schema-default(D.attr) } ) },
  [ for each g in sorted(goal-set):
      ( g, canonical-map{ g.attr : effective-value  |  effective-value ≠ schema-default(g.attr) } ) ],
  source-subset, source-commit )
```

The per-dimension loop covers exactly the four SINGLE-valued content dimensions —
`resolved-entry-id(D)` is undefined for a set-valued dimension, so Goal never enters it. Goal
contributes the sorted, deduped goal-set exactly once, as the ordered pair-list above: one
`(goal-entry-id, per-entry canonical delta map)` pair per selected goal entry, so a goal entry's
attribute deviations (e.g. an M1 `extends:` field-merge over a shipped goal entry) enter the hash
keyed by that entry's id — and the goal-set enters the hash exactly once, never twice.

Why delta-vs-floor: it is deterministic (same inputs → same id) **and** stable under additive
schema evolution — a newly shipped attribute at its default is absent from the map, so no
`artifact-id` churns and no cached artifact is orphaned. It captures Mechanism-1 field-merges and
every scope binding and run override as effective-value deviations. Despite the field's name,
it denotes the *effective delta from the schema floor* — configured deviations and run-layer
overrides alike (the word "override" alone remains reserved for the run layer, §4/§12.5). Union-
combined set attributes feed this same canonicalization (§12.4), so identical sets always yield
identical ids.

**The grounding components, defined for multi-instance pools.** A workspace pool holds N source
instances, each bound to its own repo and commit (§6.1) — so the two grounding preimage
components are defined once, here:

- **`source-commit` = the canonical commit-MAP** `{source-instance-id → commit}` over the
  resolved source-subset — sorted keys, one commit per instance — snapshotted once at
  `begin-session` (§21.8). It enters the preimage as that canonical map (equivalently, its
  digest). Q17 names the component in the singular; for a multi-instance pool the pinned map IS
  the commit value.
- **`source-subset` = the resolved, configured pool selection** — the workspace pool narrowed by
  any recipe/run subset selection (§6.1), resolved and fixed at `begin-session`, **before** M3's
  hard filter runs. Which facts survive `require`/`span` varies per item (goal/role-implied
  clauses differ, §6.3) and is grounding-ledger data (§15), never an identity input: identity
  carries the pool and its pinned commit-map; per-fact survivorship and per-fact commits live in
  the ledger.

**The optional `outline-digest` component (DR-3).** The preimage carries a **fifth** top-level key
(the FIRST of two OPTIONAL components; the DR-2 `lexicon` below is the sixth) — the 64-char
lowercase-hex SHA-256 of a normalized outline
(`pipeline.outline.outline_digest`; a bare content hash, never a §7.4 id root). It is
**omit-when-absent**: no outline → the key is absent, the preimage is the byte-identical four-key
shape above, and every non-outline `artifact-id` re-mints unchanged (the zero-churn guarantee).
Horn (a)'s fixed drive posture (§12.1) keeps DR-3 at **exactly one** new identity component —
there is no `drive-config`/facet key. The digest has **two distinct homes (R4)**: on the **emit**
path it is the digest of a `Format=outline` artifact's OWN normalized body — the ratified **R4
exception** to the rule that an artifact's body is never in its identity preimage (an outline's
identity legitimately depends on its own bytes); on the **drive** path it is the digest of a
SEPARATE input on a NON-outline artifact — an ordinary content-address in the same category as
`source-commit`, **not** an R4 exception and never a body-in-preimage breach. See
`docs/known-issues.md` DR-3.

**The optional `lexicon` component (DR-2).** The preimage carries a **sixth, OPTIONAL** top-level
key — the resolved house-style `lexicon` as an `{entry, delta}` pair (the DR-3 `outline-digest`
twin, but **dimension-shaped** rather than a bare content hash: it is canonicalized and shape-guarded
by the SAME F7 dimension machinery that covers a content dimension, not the `outline-digest` string
check). The `delta` ranges over the lexicon entry's **ATTRIBUTES only** — `preferred_terms` /
`banned_terms` / `proper_names` / `spelling` / `mechanical`, delta-vs-floor exactly as a content
dimension is — and **never** the entry BODY, which is documentation only and is never
compose-consumed (the attributes-only identity invariant: the body cannot move an id because nothing
reads it). It is **omit-when-absent**: no selected lexicon → the key is absent, the preimage is the
byte-identical five-or-fewer-key shape above, and every lexicon-less `artifact-id` re-mints unchanged
(the zero-churn additive posture). The lexicon moves the **`artifact-id` ONLY** — never
`fitted-id` / `deliverable-id`, and never an `ir_version` bump; the compose-applied wording is a
*style* transform, so nothing else churns. **RI11:** the same `(entry, delta)` yields the same id,
and a rule edit (a changed attribute) mints a NEW id — closing the same-id/different-bytes hole a
silent house-style change would otherwise open. See `docs/known-issues.md` DR-2.

### §7.3 Identity exclusions

Two things are **never** id inputs:

- **The artifact `metadata` bag** (§11.3): opaque instance annotation, not a content input — it
  must not change identity.
- **The `schema_version` stamp** (§13.4): reproducibility lineage, pinned per run — a version bump
  alone never churns any id.

### §7.4 Id string encoding — **[D2 — closed by B1; ratified B4-1]**

D2 (deferred-but-mandatory) is closed here and **ratified (B4-1)**: the concrete string-encoding
template for `artifact-id` / `fitted-id` / `deliverable-id` / `part-id`, with the options
considered and the grounds for the choice recorded below. The revision-qualifier grammar is the
ratified FR2 `_` amendment as generalized per level by FR7.2 — additive: baseline ids are
byte-identical to the ratified template.

**Requirements.** One id must serve, unmodified, as: a cross-platform **filename** — including
case-insensitive filesystems (macOS/Windows) and the claim-file mechanics where **the filename IS
the id IS the lock** (§13.3, §22.3) and the folio member-marker filename is the member's
`artifact-id` (§13.3); a **JSON key** (wire payloads, ledgers, tokens); and a **prefix-queryable**
handle (list a workspace's deliverables of one artifact by name prefix).

**The safe alphabet (all id families).** Id strings use only `[a-z0-9]` plus the separators `-`
(within a segment), `.` (between coordinate segments), `~` (before a part segment), and `_`
(before a revision qualifier; FR2/FR7.2). No
uppercase (case-insensitive-FS safety), no `/ \ : * ? " < > |`, no spaces, no leading dot. To make
coordinate segments safe by construction, **every registry entry id (platform, language,
output-type, presentation, format-part role, …) is constrained to the slug alphabet
`[a-z0-9-]`, 1–40 chars, no leading/trailing `-`** — enforced by schema-lint (§11.7), which also
enforces the entry-identity match: the filename slug MUST equal the entry's frontmatter `id:`,
and the `x-` instance prefix is part of the id in both carriers (§11.1, §11.4). This also
formalizes the existing one-file-add filename convention.

**The template (recommended and adopted — option 2 below):**

```
artifact-id      a-<hex16>                          e.g.  a-9f3c07d21b44e8aa
fitted-id        <artifact-id>.<platform>.<language>      a-9f3c07d21b44e8aa.linkedin.en
deliverable-id   <fitted-id>.<output-type>.<presentation> a-9f3c07d21b44e8aa.linkedin.en.docx.plain
part-id suffix   <owner-id>~<part-slug>                   a-9f3c07d21b44e8aa~slides
                                                          …docx.plain~p03   (reconcile-split part)
folio-id         f-<hex12>   (system-assigned, F8)
generating-run   r-<hex16>
```

- `<hex16>` = the first 16 lowercase hex chars (64 bits) of the SHA-256 over the canonical
  `artifact-id` preimage (§7.2). The **full digest** is recorded in the IR `binding` (§15) and in
  lineage.
- **Collision posture:** 64 bits gives a vanishing birthday probability at any plausible workspace
  scale (« 2⁻²⁰ even at millions of artifacts); belt-and-braces, the mint path performs a
  **preimage check** — if the id exists with a different recorded preimage, minting fails loudly
  (never silently reuses). Idempotency compares preimages, not just names: the check is wired into
  the execution spine as part of S0's idempotency pre-check (§22.3, §22.7), and it reads only
  output-store state — the preimage lives in the output store's IR `binding` (§15) — so it is
  INV-CORRECTNESS-clean (§22.7).
- **Structural coordinates, not hashed coordinates:** `fitted-id`/`deliverable-id` append their
  coordinates as literal slug segments. This makes the ratified projection relationships
  (`fitted-id` = `deliverable-id` minus output-type/presentation) mechanically visible, makes
  claim/marker/output filenames self-describing, and gives prefix-listing for free.
- **Part segments** use `~` so a part boundary can never be confused with a coordinate boundary.
  Composite parts use the Format-declared role slug (`~slides`); reconcile-split parts use a
  zero-padded ordinal — two digits (`~p01`…`~p99`), widening to the natural width of the part
  count for a split of more than 99 parts, fixed per saved deliverable — consistent with split
  part-ids being save-stable but not re-chunk-reproducible (§9.5).
- **Length bound:** worst case 18 (artifact) + 4×41 (coordinate segments) + 2×13 (both revision
  qualifiers, below) + 41 (part suffix) = **18 + 164 + 26 + 41 = 249 ≤ 255** — under the 255-byte
  filename limit on all mainstream filesystems by construction, guaranteed by the 40-char slug
  cap.
- **Filename scope:** for claim files and folio member markers the filename is the id **exactly**
  — no extension (§13.3, §22.3). Layer-2 byte outputs MAY append a conventional format extension
  after the full id (`….docx.plain.docx`) for tooling ergonomics: the extension is never part of
  the id, a trailing extension cannot break prefix queries, and **the extension is appended only
  when the result still fits 255 bytes** (with both revision qualifiers and a 40-char part slug
  the pathological headroom is 6 bytes) — the id is authoritative and extension-free names are
  always valid (FR7.2).
- **The grammar is prefix-typed and positional:** the root prefix names the family (`a-` artifact
  · `f-` folio · `r-` run) and the dot-segment count names the level (bare root = artifact;
  +2 coordinate segments = fitted; +4 = deliverable; a `~` suffix = a part of whichever id
  precedes it). `fetch-by-id` and `list` therefore infer an id's type from the bare string — no
  side table; the slug alphabet excludes `.`, `~`, and `_`, so segment parsing is unambiguous.
  Parse order: split the `~` part suffix first, then dots, then strip a `_hex12` qualifier from
  segments 3 and 5 only — a qualifier creates no dot segment, so dot-count level inference is
  untouched, and a `~` after a qualifier (`…plain_9c2e11ab34cd~p03`) splits cleanly before any
  qualifier handling.

**Revision qualifiers (FR2, as generalized per level by FR7.2).** A per-level `_` qualifier names
a redone fit or a redone serialization without rebinding any baseline id:

```
qualifier          := "_" hex12
fit-revision       := qualifier attached to the LANGUAGE segment       (closes the fitted level)
serialize-revision := qualifier attached to the PRESENTATION segment   (closes the deliverable level)
```

**At most one qualifier per level (≤ 2 per id); a qualifier may attach only to the segment that
closes its level; a `_` on any other segment is an invalid id.** `hex12` = the first 12 lowercase
hex chars (48 bits — the folio-id precedent) of the SHA-256 over the level's canonical input
preimage: the reconcile-inputs preimage for a fit revision (§16), the serialize-inputs preimage
for a serialize revision (§17). The mint-time preimage check above applies to qualified ids
identically — it reads the fit-binding / render-binding (§16, §17) — so a hex12 collision or a
canonicalization bug fails loudly, never silently. `_` is not in the slug alphabet and not hex,
so it can never occur inside a coordinate segment or a digest; qualifiers flow into deliverable-
and part-ids by prefix containment; baseline ids — the entire never-forced path — are
byte-identical to the unqualified template (zero id churn).

```
a-9f3c07d21b44e8aa.linkedin.en.docx.plain                                 baseline everywhere
a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain                    fit revision only
a-9f3c07d21b44e8aa.linkedin.en.docx.plain_9c2e11ab34cd                    serialize revision only
a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd       both
a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd~p03   + split part
```

(Qualifier encodings considered and rejected: `~g2`/`~<hex>` — collides with the part namespace,
where `g2` is a legal Format role slug; a bare dot segment — breaks the positional level-count
grammar. Claim files and markers use the qualified id exactly, no extension, as above.)

**Options considered.**
1. *Opaque hash at every level* (`d-<hex>` for deliverables): uniform and shortest, but hides the
   projection structure — listing an artifact's deliverables or checking "does this fitted-id
   already exist" needs an index file, adding a store the design otherwise doesn't need. Rejected.
2. *Hash root + structural coordinate suffixes* — **adopted** (above): the id family's ratified
   structure is literally readable in the string; filenames are self-describing; no index needed.
3. *Full human slug for `artifact-id` too* (topic/persona/… coordinates spelled out): readable but
   unbounded length (seven+ coordinates incl. a goal-set and an overrides delta cannot fit 255
   bytes), and it would put content coordinates in every filename. Rejected — the hash root with
   the preimage recorded in the IR gives reproducibility without the length hazard.

## §8 Recipes, selection & fanout

- **recipe → one artifact.** A recipe binds one entry per content dimension + a goal-set +
  configured values, and may pin rendering targets (else they are supplied at run).
- **selection → many recipes.** A selection multi-selects across dimensions and fans out into
  concrete items: content fanout (distinct artifacts) × rendering fanout (deliverables per
  artifact). Every fanout item is id-keyed, commit-pinned, and idempotent (§7).

**Pairing is user-driven; there is no hard compatibility filter** (Q4). Any format→platform
pairing the user selects is honored. There is no `valid_platforms`, no exclusion table, and no
final-moment veto: the system never refuses a resolved selection because it judges the combination
silly. The effective **allow-list is emergent from configuration** — the cascade of defaults →
inheritance → overrides resolves to the selection list that drives generation (§12). There is
also no automatic mode that invents pairings: nothing is generated without the user (or the
user's configuration) selecting it.

**Advisory lint, once.** A one-time, lint-style sanity check flags strange/distant combinations
(e.g. README → LinkedIn) so a mistake is catchable — advisory only, never blocking, never runtime
machinery, surfaced as `nonsensical-pairing` (warn) in results (§21.7). **The lint catalog
contains no folio-based pairing triggers**: a folio has no platform or rendering value to diverge
from (§9.1), and platform divergence among a folio's members is normal by design, not a conflict
(CA3). Goal-set overload likewise warns, never blocks.

## §9 Folios

### §9.1 What a folio is — and is not

**A folio is a pure purposeful set: an addressable, durable collection of artifact references with
a purpose — nothing more** (DIRECTIVE; A4-4). This is a pipeline-wide invariant, not a rendering
rule:

- **A folio holds no dimension values and no rendering/platform intent, ever.** It is orthogonal
  to all nine axes. Coupling any dimension to a folio, even as a soft default, is a category error
  that mis-frames the folio as a publishing target and breaks the core case — one topic fanned
  across many platforms — by design. There is no `rendering_intent` field; there is no folio rung
  in the value cascade (§12.2).
- **A folio holds no ordering and no schedule** (A4-4). The system never consumes publication
  order (generation and render are idempotent, parallel, id-addressed); the only order consumers
  are publication and consumption, which are external (§2.2). Every useful ordering is derivable
  from tracked facts by the consumer (§9.2); the one non-derivable case — an arbitrary
  hand-curated sequence — is actor state by nature and lives in the actor's own store, not here.
- **A folio carries only collection-intrinsic data:** `id` · `purpose` · optional `folio_type`
  (declaring member roles/structure, §9.6) · the member reference set with per-member records
  (§9.2) · provenance/scope (`provenance: instance`, workspace-scoped — folio *instances* are
  client content and never public; folio *types* are framework-shippable).

A folio may span platforms, languages, formats, topics — deliberately. Membership is by reference
and many-to-many: one artifact may belong to multiple folios; one-offs/orphans (no folio) are
normal. The system can create a folio; an external actor can create an **empty** folio, store its
id, kick off runs that target it, and add members at any time (§20, §21).

### §9.2 Membership & the member record

- **The folio owns the authoritative member set** — an **unordered set** of `artifact-id`
  references (F2 as amended by A4-4). The reverse index (artifact → folios) is derived, never
  authoritative — the same one-authority-plus-derived-view discipline as the SSOT (§24).
- **Membership is artifact-level** (F3): membership stays stable across re-renders and preserves
  compose-once/render-many. Membership is intra-workspace only — an artifact from client A can
  never join a folio of client B (isolation is structural, §10).
- **The member record.** Each member carries `{added_ts, pin?, role?}` (D1.2 as amended by A4-4;
  `role` per §9.6): `added_ts` = when the reference was added; `pin` = an optional per-member
  **deliverable pin** — **id-form and FROZEN** (FR3): the exact deliverable-id string (including
  any revision qualifiers, §7.4), consumed by manifest resolution (§21.5), never re-resolved by
  the system (Q3: a pin that drifts is not a pin), and annotated with the computed currency
  fields on read surfaces when non-current (§21.3, §21.5); `role` =
  the member's declared role in a typed folio (§9.6). On disk each member record is one marker
  file named by the member's `artifact-id` (§13.3). The API write path for `pin` and `role` is
  `add-to-folio`'s member parameters, where the re-append/update semantics are defined (§21.2);
  membership is append-only in v1 — member REMOVAL/supersede is a registered open item (§27.3).

**"Folio state", defined once** (A4-4 closes T11): **"folio state" means folio-LEVEL dimension or
rendering intent — and it is banned, always.** A **per-member-record deliverable pin is
permitted**: it is member-scoped data inside the member record, precisely what manifest resolution
consumes (§21.5) — it is not a folio-level opinion and does not make the folio a publishing
target. The pin's storage locus is the member record, authoritative on the folio side (this
sentence is the single definition; §21.5 references it and adds nothing).

**Ordering is the consumer's, computed from exposed facts.** The folio stores no order (A4-4;
the former advisory `ordering`/`schedule`/`suggested_order` fields do not exist). Normative
requirement (A4-4 condition i): **every member-listing/discovery surface — `list folio-members`,
`get folio`, and the manifest (§21.5) — MUST expose the sortable facts per member: `added_ts`,
the member's id-family coordinates, lineage (`generating-run`, `source-commit`, creation time),
its `pin`, and its `role`** — so any derived ordering (insertion order, date order, attribute
order, structural order via roles) is computable client-side. Intra-work sequence is not a folio
concern at all: it belongs to a split's part structure inside one artifact (§9.5).

### §9.3 Identity & state class

- **Folio ids are workspace-scoped, stable, and system-assigned** on `create-folio`, returned to
  the caller; the fully-qualified reference is `(workspace, folio-id)` (F8; string form §7.4).
- **Folios are durable WORKSPACE state, never session state** (F5). A session carries only the
  folio-**id** reference. This is the hinge that makes create-empty → target-later → add-any-time
  work across stateless calls (§20).
- A folio never auto-closes: it stays open and mutable; emitting a manifest snapshots it without
  freezing it (§21.5).

### §9.4 Batches are not containers

There is **one** container concept — the folio. A "batch" is not a container (F1): what a run
produced exists as (a) the session token's produced-id list (ephemeral, actor-held) and (b) the
immutable **generating-run lineage** stamped on each artifact (permanent). "What did run X
produce?" is a **lineage query** — by run id, source commit, or date range (§21.3) — never a
membership lookup. The system never auto-creates a purpose folio and never auto-adds to a folio
the actor didn't target (§20).

### §9.5 Split vs folio; parts

The discriminator is **mechanical — count the underlying artifact-ids** (F9, closing Q8):

- **Split:** ONE artifact reshaped by the reconcile pass into a multi-part deliverable
  (X-thread, IG carousel). Parts are `(deliverable-id, part-id)`, each emitted as its own
  identified unit with its own bytes, carrying an advisory intra-work `sequence` in the part
  structure (§15, §17). Split part-ids are stable within a saved deliverable, not guaranteed
  reproducible on re-chunk.
- **Folio:** N distinct artifact-ids grouped by reference. A set of N standalone posts is a folio,
  never a split.
- **Composite formats** (Q14) are the third, compose-time shape: one artifact whose Format
  declares intra-genre `parts` — addressed `(artifact-id, part-id)`, stable, living in the IR.

"Independently publishable" survives only as an informal authoring heuristic for the user's
upstream choice; **the system holds no opinion** and enforces only the artifact-id count. The
system's part `sequence` is advisory; actual posting order belongs to the external publisher
(§2.2).

### §9.6 Folio types

A **folio type** is a framework-shippable blueprint (`provenance: framework`, one-file-add,
schema-versioned per §11.7) that declares a typed folio's **member roles and structure** — e.g.
`repo-docs → roles: [readme, getting-started, architecture]`, `curriculum → roles: [study-guide,
exam, answer-key]`. **A folio type declares roles and per-role recipe skeletons — never dimension
values.** Each role names the shape of a member (a recipe skeleton: which Format genre, which
topic archetype slot, …) that the generating machinery instantiates; concrete dimension values
come from the generating recipe/run, never from the folio or its type (DIRECTIVE item 4).

**Where shared-grounding and roster coherence bind — the generating run.**

**Ratified (B4-2; the DIRECTIVE wins over the archived folio-type text).** The legacy model gave
the folio type "shared grounding" (all members bound to one source/commit) and "roster awareness"
as folio-held properties. Source-subset and source-commit are `artifact-id` inputs —
dimension-adjacent values a folio must not hold. The binding point is therefore the **generating
run**, as follows.

- **Shared grounding is a property of the generating run, guaranteed by run mechanics.** One
  typed-folio generation run is one session: it pins **one source commit-map**
  (`{source-instance-id → commit}`, §7.2) and resolves **one effective source-subset** (the
  configured pool selection, pre-hard-filter, §7.2) at `begin-session` (§21.8), then fans out one
  recipe per role. All members therefore share grounding **by construction** — every member's
  `artifact-id` embeds the same commit-map and source-subset because they came from the same
  run's pins, not because the folio stored anything. Shared grounding means **same pool + same
  pinned commits — never same facts**: goal/role-implied `require`/`span` clauses differ per role
  (§6.3), so the facts each member draws differ by design; per-member survivorship lives in each
  artifact's grounding ledger (§15).
- **Cross-session regeneration reproduces coherence only under SUPPLIED pins.** Pins are captured
  at `begin-session`; a later session regenerating one member passes the original run's pins
  explicitly (`begin-session` accepts them, §21.8) to reproduce its grounding — a pin-less later
  session pins current source state and produces a new, visibly different lineage (§7.1), never
  silently-shared grounding.
- **Regeneration × membership.** A regenerated member is a NEW `artifact-id`; the folio still
  holds the old one, and adding the new one yields TWO members recorded with the same `role`.
  That is legal: membership is append-only in v1 (§9.2, §21.2), duplicate roles are permitted,
  and consumers disambiguate by `added_ts` and lineage — both exposed on every listing surface
  (A4-4 condition i, §9.2). Member removal/supersede is the registered open item at §27.3.
- **Roster awareness is generating-run compose context — and not an identity input.** The run
  passes each member's writer the sibling role list (for light cross-linking) as part of the
  compose request. It is run-scoped context, not folio state; nothing about it persists on the
  folio. Like all run-scoped compose context (the roster, the grounded fact set), it is NOT an
  `artifact-id` input: identity is a coordinate hash, never a content hash (§7.1) — compose is
  LLM-non-deterministic, so the same id composed inside vs outside a typed run may read
  differently while being the same designed item. §7 promises coordinate reproducibility, never
  byte-level reproducibility of composed content.
- **The folio type is consumed at generation time only.** Post-generation, the type remains on the
  folio as declared structure (`folio_type` field) for discovery and for role-based ordering
  reconstruction — it never influences rendering, manifest resolution, or the cascade.

**Member roles are recorded on the member record** (A4-4 condition ii).

**Ratified (B4-3; the recording locus).** The role is folio-relative — the same artifact can sit
in two folios with a role in one and none in the other — so the correct locus is the **member
record** (`role` in `{added_ts, pin?, role?}`, §9.2/§13.3), not artifact lineage or the metadata
bag, which are folio-agnostic and wrong by type. When a typed-folio run generates (or an actor
adds) a member for a role, the role slug is written into that member's record — the API write
path is `add-to-folio`'s member parameters (§21.2). Structural order is then reconstructable from
tracked data alone: the folio type's declared role structure + each member's recorded `role`
(both exposed by every listing surface, §9.2). Artifact lineage remains free of folio-relative
data. Recorded roles are **point-in-time slugs** relative to the folio type's schema version at
add-time: folio-type CONFIG migrates (MIG-7, §11.6), but member records are machine records and
are never migrated — after a role rename in a folio-type release, `get folio` still exposes the
`folio_type` and its current schema stamp, and a recorded role slug unknown to the current type
is surfaced AS-IS, never dropped, never silently remapped.

Deep-folio correspondence (a member generated *from* another member) stays deferred; only the
identity-provenance slot and a manifest dependency column are reserved (Q12; §26).

---

# PART III — THE CONFIGURATION MODEL

## §10 Provenance, scope & the public boundary

Two independent classifications, each encoded where it enforces best (Q15; this section is the
authority for provenance/scope — `docs/operating-model.md` is the two-repo how-to that conforms to
it, Appendix B):

- **Provenance** — who authored it: `provenance: framework | instance`, a required **metadata
  tag** (YAML frontmatter field). The framework ships *real default entries* (standard voices,
  platform profiles, default recipes, content-kinds, folio types, the `plain` presentation), so
  shared directories are **mixed-provenance**: framework defaults and instance-global additions
  live side by side, distinguished by the tag, never by location.
- **Scope** — where it applies: encoded by **location**. Shared `<dimension>/` directories =
  global; `users/<user>/zones/<zone>/workspaces/<workspace>/<dimension>/` = that client only. Client
  isolation is structural. The `users/<user>/` **and** the `zones/<zone>/` segments are both
  isolation/addressing **prefixes**, orthogonal to the value cascade (§12/§23): they change *where* a
  workspace lives, not which rung a value binds to — the cascade stays framework → instance-global →
  workspace (L1/L2/L3), never a `user` rung and **never a `zone` rung**. A zone GROUPS a user's
  workspaces (§23) and gives them store isolation; the separate **transport-credential zone rung**
  (per-zone keys/weekly-caps, and therefore spend-bucket isolation between same-named zones) is
  **now DELIVERED** by the transport-selection build (§21.10, `docs/transport.md`) — a credential
  cascade orthogonal to this value cascade, so "never a `zone` rung in the value cascade" stands.

The five interlocking rules (Q15, all normative):

1. **Ownership is mixed-provenance.** Shared dirs hold framework defaults + instance-global
   additions; the operating model describes them so.
2. **Extend-don't-edit covers shipped entries.** A `provenance: framework` entry is never edited
   in place by an instance; customization is a workspace (or instance-global) **`extends:`
   partial** that field-merges over it (Mechanism 1, §12.1). This extends the repo's durable
   rule 5 to entry granularity (the CLAUDE.md wording update is a maintainer action, Appendix B).
3. **Instance entry ids are namespaced** with the reserved **`x-`** filename prefix (§11.4), so
   framework↔instance filename collisions are impossible and upstream merges stay conflict-free.
4. **The CI guard default-denies.** Any registry file with missing or ambiguous `provenance` is
   rejected; the guard also runs schema validation (§11.7).
5. **The guard runs on the public repo only.** Its job is keeping the public framework empty of
   instance/client content (`provenance: instance` entries, `instance/profile.md`, client
   workspaces); instance-side repos are not gated by it.

The mechanism/data split recurs throughout the design: **mechanisms are
`provenance: framework` (public); populated values/data are `provenance: instance` (gitignored in
public)** — brand voice values (§12.6), telemetry and lease stores (§22.5, §23), folio instances
(§9.1), the metadata bag (§11.3).

## §11 Schemas & versioning

Full schema-versioning ships in v1 — no deferral (Q11). One identical mechanism covers every
collection (§11.7).

### §11.1 Schema files & attribute types

Each collection has a **co-located schema**: `personas/_schema.yaml` beside the persona entries,
and so on (SV4; encoding §13.4). A schema is a typed field manifest, not a straitjacket: per
attribute it declares `type` · `default` · prose `definition` · `definition_version`.

**The entry-identity rule (B4).** Every registry entry carries **`id:` in its YAML frontmatter**,
and **the filename slug MUST equal the in-file id** (the §4 definition). Schema-lint enforces the
match as part of the validation that already runs (§11.7) — one-file-add is preserved; no second
edit exists. The `x-` instance prefix is **part of the id**, present in both carriers (§11.4);
entry ids remain constrained to the slug alphabet `[a-z0-9-]`, 1–40 chars (§7.4). What the rule
buys: duplication-for-editing is LOUD — a copied file whose filename ≠ its internal id is a CI
error, killing the silent-new-entry failure; carrier drift is impossible (a mismatch is an
error); a rename is a deliberate two-touch act (filename + in-file id), and a dangling reference
still fails loudly at M1 resolution (an unknown entry id is an error, never silent). History is
already rename-immune: outputs are content-addressed and the id preimage is recorded in the IR
binding (§15). A graceful-rename `aliases:` field is registered as deferred (§26) — not built in
v1.

**The attribute type system** spans constrained → free:
`enum` · `number` · `slider(1–5)` · `range` · `ref` · `bool` · `date-window` · **`list`
(ordered)** · **`set` (unordered, leaf elements)** · `map` · `text`/`markdown` (free text; weaker
validation; wholesale replace — prose never merges).

The **ordered-`list` vs unordered-`set` split is load-bearing** (CM3 acceptance term 1): the
`union` combine operator (§12.4) is valid **only on an unordered `set` of leaf elements**
(enum/number/ref/bool/string). Declaring or using `union` on an ordered `list` (e.g.
`format.parts`) or a set-of-maps is a **schema-validation ERROR** — never silently coerced. A
`set`-typed attribute may declare a schema-level default combine operator (§12.4).

**Schema-level defaults are the cascade floor** (L0, §12.2): a brand-new framework attribute falls
back to its default for every pre-existing entry — nothing breaks, no files move, and (per §7.2)
no id churns.

### §11.2 Versions & stamps

- **One global `schema_version`** (SV2) — a single integer, bumped ONLY at a deliberate framework
  RELEASE that changes a schema, **never mid-development**. In-development schema evolution (a new
  registry attribute, a widened type) is shipped **additive-at-floor** — a new attribute rides its L0
  floor so every existing entry stays valid and every id/digest is byte-identical — which needs NO
  bump (the version-equality lint keeps all co-located `_schema.yaml` at one number; a per-schema bump
  mid-stream would fail it). **This exemption is now ENFORCED in the lint** (SV11 clause 1, DR-2 C3a):
  a new attribute riding its type's empty L0 floor no longer trips
  `schema-change-without-version-bump`, so the §11.2 policy prose finally has matching enforcement —
  while removals, meaning/type/default changes, and non-empty-default adds still fire. The bump is a
  coordinated, all-at-once release step, deferred until then.
  One number pins one released, coherent schema snapshot: atomic revert lands on a state that actually
  existed; a run pins one number, not a vector (§21.8).
- **`definition_version` is valued in the `schema_version` number-space** (SV1): it records the
  global version at which that attribute's *meaning* last changed. Drift detection is one integer
  comparison — `definition_version > entry.schema_version` AND the entry sets that attribute — so
  drift is per-attribute-scoped without per-dimension counters or history tables. (An attribute's
  `definition_version` may jump across unrelated releases; the drift math is unaffected.)
- **Every entry stamps a single integer `schema_version`** — the version it was authored/last
  migrated under (SV3 stamp shape; encoding §13.4).
- **The IR envelope's `ir_version` is distinct from `schema_version`** (DR-6 F-a): it names the
  IR-envelope generation, now **2** (was 1) — a §15/§7 render-reproducibility stamp, not a
  migration target. It is validated GENERATION-TOLERANTLY: accept any `∈ KNOWN_IR_VERSIONS = {1,2}`,
  not exact-equality, so an IR stamped at an older additive-optional generation still re-reconciles;
  a breaking IR change would instead have to gate, never silently read.

### §11.3 Closed schemas & the artifact metadata bag

Schemas are **closed and not attribute-extensible by instances** (SV3). Undeclared attributes are
rejected. The framework has no mechanism to *apply* a custom attribute — an attribute is applied
only because generation logic knows it — so instance-added schema fields would be inert; they do
not exist in this model. **Instances customize by authoring data (entries, `extends:` partials),
never by adding interpreted fields.**

The replacement for custom needs is the **artifact-level opaque `metadata` bag**: an
instance-authored map on the artifact that the framework **stores and passes through to the
external hand-off, but never interprets or applies**. It is excluded from `artifact-id` (§7.3),
never routed into AST content (§15), carried in the layer-3 contract payload (§17) and on
`get artifact`/`fetch` (§21) untouched; its meaning lives with the downstream publisher. It is
workspace-scoped `provenance: instance` content, is never migrated (§11.6), and must not carry
secrets (§3.3). It is not a dimension; the folio invariant (§9.1) is untouched by it.

The clean line: **framework attributes are content inputs the framework knows how to apply** —
they shape generation and enter identity. **Custom instance data is opaque metadata** — never
applied, never identity, interpreted downstream.

### §11.4 Instance entry namespacing

Instance-authored entry **files** carry the reserved prefix **`x-`** (`x-our-cto.md`) — required,
CI-enforced (SV5); the prefix is part of the entry's **id**, present in both carriers — the
frontmatter `id:` and the filename (the entry-identity rule, §11.1). The framework owns the
unprefixed namespace and never ships `x-*`, so
framework↔instance collision is structurally impossible. Instances MAY add an org-slug segment
(`x-acme-cto.md`) — a gentle, undocumented, untested convention entirely inside the reserved
space; if instances ever share files directly, the org-slug can be promoted from optional to
required as a clean later escalation.

### §11.5 Change discipline & drift

- **Meaning vs wording.** The prose `definition` is freely improvable; `definition_version` bumps
  **only on a meaning change**. When unsure, treat it as a meaning change.
- **Deterministic vs ambiguous is BINARY and machine-checkable by step SHAPE** (SV6 + MIG-4): a
  meaning change ships either a **total, typed forward map** (deterministic → auto-applied at
  migration) or a **prompt** (ambiguous → halts for a human, §11.6). There is no third tag and no
  maintained classification: the shape of the shipped migration step *is* the classification.
  Schema-lint fails a meaning bump that ships neither (§11.7). Within "meaning", the safe default
  is ambiguous — never a silent partial-map guess.
- **Drift is checked at both times** (SV7 + MIG-6): **update-time REPORTS** (an upstream merge is
  non-destructive and produces an upgrade notice: new attributes now on defaults, redefinitions to
  review, new entries/dimensions available); **resolve-time ENFORCES** — before any stale object
  is used: **BLOCK** on any meaning change affecting an attribute the object sets (deterministic
  or ambiguous), on a removed-attribute-still-present, or on a stamp outside the migration window
  (§11.6); **WARN** on new-attribute-available; **silent** for wording-only changes. Hard drift
  therefore blocks *before any artifact exists*; the review gates (§19) handle only residual soft
  advisories. Blocking is refusal, not overstep (§3.1).

### §11.6 Migration

The migration system (MIG-1…MIG-7; the retracted first design is recorded only in Appendix B):

- **MIG-1 — Declarative, append-only step registry; one fold.** Each meaning change ships **one
  declarative migration step** (per-attribute in the common case; object-level as an escape
  hatch), authored once at the release that made the change. Migration = **one fold over the
  half-open interval `(entry-stamp, current]`**: the runner selects every step whose trigger
  version lies in the interval and folds them onto the object. Skip-safety is **structural** — a
  user may skip any number of versions (including majors) and still migrate directly to current;
  there is no chaining and no lost interpretation logic. No inverse is representable — no-revert
  is structural too. Folding an empty interval is a no-op, so idempotency is structural as well.
- **MIG-2 — A 1-year time window bounds the registry.** Steps for changes older than **one year
  by release date** are pruned; within the year a user may skip any number of versions/majors and
  migrate directly. A config whose stamp predates the horizon has pruned steps → the tool
  **BLOCKS** ("past the 1-year support window — regenerate or hand-fix; unsupported"). There is no
  version floor and no maintained manual path. Git preserves each release's registry, so a very
  stale config *can* be walked forward in ≤1-year strides — a tedious, user-owned, **unsupported**
  path; nothing is ever permanently stranded, and the framework guarantees none of it.
- **MIG-3 — No deprecation lifecycle.** There is no per-attribute `deprecated`/`removal_target`/
  `replacement` bookkeeping. Versioning is **all-or-none**: one global version bumps even if one
  attribute changed (no-op-heavy releases are fine). "Removal" = the current schema stops
  declaring X + a forward step drops/remaps configs that had X; a rename = a lossless total-remap
  step.
- **MIG-4 — Binary discipline by shape** (stated in §11.5): total map → auto-apply; prompt →
  halt. One CI rule: a meaning bump ships a map or a prompt.
- **MIG-5 — The human gate is a resumable worklist.** Ambiguous changes generate a
  **"decisions-needed" worklist file** (not interactive prompting): reviewable up front,
  resumable, diffable, **grouped by change with a group-level default** so one policy answer fans
  across every config sharing the change. A skip-span migration surfaces the **union** of
  ambiguous decisions accrued across skipped versions. Re-stamping is **object-atomic**: an object
  re-stamps only when all its steps resolve (forced by the single-integer stamp).
- **MIG-6 — Block-vs-warn behavior** (stated in §11.5, including the out-of-window block).
- **MIG-7 — Scope.** Migration touches **instance-owned, schema-stamped CONFIG only**
  (instance-global entries, workspace `extends:` partials, instance recipes, folio types, source
  instances, content-kinds). Framework defaults are lockstep-maintained upstream and never
  instance-migrated. **Artifacts are IMMUTABLE — never rewritten: migrate config, then
  REGENERATE** (a new `artifact-id`; the old artifact persists as lineage). The `metadata` bag is
  never touched. Git revert is the only "revert", user-owned and unsupported (the single global
  version makes it land on a coherent snapshot).

Migration runs via an owner-triggered **`scripts/migrate.sh`** — **user-triggered, mandatory
before use** (resolve-time blocks until run), never silent auto-run, idempotent. It is a
**maintenance verb and is NOT on the external-actor API** (§21.9): the API only surfaces
`drift-block` / `out-of-window` / `ambiguous-migration-decisions` and points remediation at the
tool (§21.7).

### §11.7 Coverage & CI

- **Uniform coverage** (SV10): every collection is schema-versioned by the one identical
  mechanism — all nine dimensions, source adapters, source instances, content-kinds, render
  targets, recipes, folio types. Thin objects get thin schemas; no special cases. (Folio *types*
  are framework blueprints and are versioned; folio *instances* are workspace data, §9.1.)
- **`schema-lint.sh`** (SV11) fails the public repo on: (1) a schema change without a
  `schema_version` bump; (2) a **meaning change** — including attribute removal, incompatible
  type change, or rename-as-remove+add — shipped **without a migration step** (map or prompt,
  MIG-4); (3) a **lockstep violation** — a framework default entry stamped older than current for
  a redefined attribute it sets; (4) **window sanity** — pruning a step younger than the 1-year
  window. It additionally validates the deterministic-map totality/composition rules (§27.4), the id
  slug constraints (§7.4), and the **entry-identity match** — every entry's filename slug MUST
  equal its frontmatter `id:` (§11.1); a mismatch fails CI (the loud-duplication guard). Known limit: a *disguised* rename (remove-old + add-new,
  same meaning) is not machine-detectable — the discipline is "never rename in place; ship a remap
  step", enforced by review.
- Schema-lint pairs with the **Q15 default-deny provenance guard + schema validation** (§10) as
  the public repo's CI gate. This section is the mandate home for v1's full lifecycle (Q11): no
  part of §11 is deferred.

## §12 The value cascade

### §12.1 Three mechanisms, one principle

"Precedence" is **three distinct mechanisms**, unified by *most local / specific / immediate
wins* — collapsing them reintroduces blur:

| # | Mechanism | Orders what | Order | Stage |
|---|---|---|---|---|
| **M1** | Entry resolution (shadowing + field-merge) | which *definition* of an entry id loads | framework → instance-global → workspace | load-time |
| **M2** | Value binding | what *value* each attribute takes for one item | the scope spine (§12.2) | compose + render |
| **M3** | Source selection & weighting | which sources/facts ground the item and how conflict resolves | workspace-default → goal-implied → recipe → run | ground-time |

- **M1 fully resolves the effective entry BEFORE M2 binds values on top** (Q18a). M1 is
  provenance-ordered field-merge: a redefining layer (`extends:` partial) overrides only the
  fields it declares and inherits the rest, with per-field provenance recorded. Its output is
  exactly one effective entry per dimension — and that entry **is** M2's `entry-default` rung
  (CA1).
- **M1 and M2 combine type-driven, by one rule set** (§12.4): replace for scalars/free text,
  key-wise merge for maps, §12.4's operator rules for sets.
- **M3 is separate and stays separate.** It runs earlier (ground-time), on a different object
  (the source pool and facts, not attribute values), with different combination semantics
  (weights *adjust*, Fork-C style; clauses union/tighten/relax per §6.4). **M3 carries the full
  selection expression — the `prefer` weight vector AND `require` predicates, `span` coverage, and
  the `on_conflict` strategy, plus the DR-6 `grounding_posture` policy** (§6.3) — all riding its
  four-layer cascade, most-local-wins. M3
  never binds attribute values; M2 never touches source selection. Their only coupling: M3's
  output (grounded facts + tiers) is an input to compose.
- The same scope spine, read pre-M1, resolves **which entry** is selected per dimension (the
  selection cascade — the mechanism behind §8's emergent allow-list); read at M2, it resolves
  **which value** each attribute takes. One ordering discipline, two questions.
- **The DR-3 outline drive brief is a compose-prompt input, NOT a cascade mechanism** (B2 total
  rule). When an outline drives generation its normalized text enters the writer prompt as a
  **high-salience brief** that OUTRANKS the dimensions for the rhetorical body skeleton and for
  content emphasis/order — the fixed **horn (a)** posture (content AND structure; the per-request
  content/structure/both facet choice is RETIRED, §27.3). The brief is prompt-only: it **never
  becomes a cascade rung** and **never sets `format.parts` or any cascade-bound attribute**, so
  M2/M3 and orthogonality are untouched. A **digest-fidelity guard** binds the shown brief to the
  item's pinned `outline-digest` on every path before any LLM/persist — a mismatch is a loud
  `ComposeError`, never silent. **Grounding total rule:** the outline asserts no facts and adds no
  ledger rows (§15), so DR-3 opens **no new fabrication vector** and the §6.5 EXTRACTED tier floor
  binds every span exactly as before.

### §12.2 The folio-free M2 spine

```
L0  schema-default      (framework floor — §11.1)
L1  entry-default       (the M1-resolved effective entry)
L2  global-default      (instance-wide; MANDATORY for the §12.3 set)
L3  workspace-default   (per client; optional)
L5  recipe              (per artifact)
L6  run                 (ephemeral session; the override layer — §12.5)
```

Higher rung wins, type-driven, only for the attributes it declares. **There is no folio rung for
any dimension** (DIRECTIVE): a folio is not a value-binding scope. The label L4 is retired with
the deleted rung — remaining rungs are deliberately **not** renumbered, so rung citations stay
stable; no other section may reintroduce a folio scope. **A zone is likewise NOT a content cascade
rung** (§10/§23): it is an addressing prefix that groups a user's workspaces, so it changes *where* a
value binds, never *which value* binds — this spine has no `zone` rung.

L0–L5 are persistent workspace state; **L6 is ephemeral session state the system never persists**
(§20). This is why run bindings can only bind values (M2) and can never redefine entries (M1) —
redefinition is a persistent authoring act (§12.5, §21.4).

### §12.3 Rung semantics per dimension

**The uniform rule.** Every dimension resolves over the §12.2 spine; rungs differ per dimension
only in (a) which are normally populated, (b) cross-dimension inserts, and (c) bind stage:
content dimensions bind at **M2-compose** (→ `artifact-id`), rendering dimensions at
**M2-render** (→ `deliverable-id`).

| Dimension | Bind stage | Populated rungs (beyond L0/L1) | Cross-dimension inserts / notes |
|---|---|---|---|
| Topic | compose | L3 optional, L5 (selection required), L6 | — |
| Persona | compose | L3 optional, L5, L6 | provides `default_voice` ref, consumed by Voice |
| Format | compose | L3 optional, L5, L6 | Platform's per-format **advisory** constraint projection merges below L5 (map-merge); hard limits never enter M2 (§12.7); per-part refinement is a deferred slot (§26) |
| Voice | compose | **L2 MANDATORY**, L3, L5, L6 | selection chain below; sliders map-merge across rungs |
| Goal | compose | L0 baseline set, L2/L3 optional, L5 (primary binding), L6 | set-valued; default combine = replace (§12.4); canonicalized into `artifact-id` |
| Platform | render | L5 (pin), L6 | **no mandatory global** — platform is per-deliverable routing, not an instance baseline (CA8); contributes advisory constraints + a weak default output-type |
| Language | render | **L2 MANDATORY**, L3, L5, L6 | multiple languages = rendering fanout; transform mechanics §16 |
| Output-type | render | **L2 MANDATORY**, L3, L5, L6 | the platform-implied default is a weak cross-dimension default: any explicit output-type at L3/L5/L6 beats it |
| Presentation | render | L0 = the `plain` framework entry (PD7), L2/L3 optional, L5, L6 | **not** mandatory-global; zero id churn at the floor (§7.2) |

**The mandatory-global set is Voice + Language + Output-type** (CA8): the instance MUST populate
a global default for each — validation errors if absent — because any generation must resolve
them to a concrete value and the instance's baseline identity should be declared, not an
accidental fallback. The schema floor (L0) still sits beneath as the last-resort net. Topic,
Persona, Format, Goal are per-request content choices (optional workspace defaults allowed;
mandatory globals meaningless). Platform is excluded — content isn't inherently "for" a platform
until the user routes it. Presentation is excluded — `plain` is the honest floor (PD7).

**Voice selection chain** (which voice entry applies), lowest to highest:

```
L2 global-default voice (mandatory)  <  L3 workspace-default voice
   <  persona.default_voice (cross-dimension insert)                (CA2)
   <  L5 recipe voice
   <  brand-authoritative flagged L2/L3 voice value (§12.6)         (BO2)
   <  L6 run voice
```

`persona.default_voice` beats the scope defaults (CA2): selecting a persona is a per-artifact
editorial act more specific than a workspace-wide baseline, and the persona's coherent voice is
the point of the bundle. The brand-authoritative flag (§12.6) is the arbitration for the genuine
brand-consistency case. The resolved voice entry's *values* (sliders, guidelines) then cascade
normally (slider maps merge; guideline prose replaces wholesale).

**Platform divergence never warns per folio** (CA3 surviving content): a folio is a purpose
grouping, not a publishing target (§9.1); members pinning different platforms is normal by
design. (The rest of CA3's original scope is absorbed by the folio invariant.)

**Reconcile-strategy** is an M2-bound render attribute, not a dimension
(`adapt | split | pass | truncate`; consumed at §16). Its defaulting is two-tier: **L0 is the
single-attribute schema floor** (`adapt`); the **per-(format × platform) default table lives on
the Platform entry's per-format projection** — Platform is the one dimension that already
projects per-format values into the cascade (§5.1, §5.3), and the strategy default merges below
L5 exactly like the advisory constraints do. (Homing a pair-keyed table on Format entries would
re-couple Format to platforms, which Q4 deleted.) Recipe/run override it at L5/L6. The strategy
is user config: the system executes it and records it in the fitted-level fit-binding (§16); it
never switches strategy on its own. A strategy change is a **reconcile-input change** (FR2):
against an already-cached fit, a plain render surfaces `render-input-mismatch` with machine
remediation `force-re-reconcile`, and the user re-fits the same approved content with an explicit
`render(force_reconcile: true)` (§21.8) — never a silent stale reuse, never a re-compose.

### §12.4 Combination semantics & combine operators

**Type-driven defaults (the naive-user contract).** When two active rungs both set an attribute:

| Attribute type | Default combination |
|---|---|
| `enum` `number` `slider` `range` `ref` `bool` `date-window` | **replace** (most local wins) |
| `text` / `markdown` | **replace wholesale** (prose never merges) |
| `map` | **merge key-wise**, recursing per value type |
| `list` (ordered) | **replace** (union is a schema error, §11.1) |
| `set` (unordered) | **replace** by default; union only by explicit operator or schema default operator |

**Union never fires by default** — a user who ignores combine-mode gets most-local-wins
everywhere. The goal-set default is replace.

**The combine operator is inline syntax on a single binding — never a value that cascades**
(CM3). Two non-cascading places only:

1. A per-`set`-attribute **schema default operator** (default `replace`; the schema author may
   set `union`).
2. An **inline per-binding operator** at any rung for a one-off flip — one token at the binding
   being edited, no schema change (surface syntax §13.2: `tags+: [c]` or
   `{combine: union, add: […]}`; wire form `{"path","op","value"}`).

Because an operator is syntax at one assignment at one rung — never inherited, never itself a
cascading value — the meta-cascade regress cannot begin. Resolution is a fixed bottom-up fold over
the §12.2 spine.

**`union` semantics are deterministic:** value union + dedupe by exact value + the same `sorted()`
canonicalization already used for the goal-set (§7.2) — identical inputs give an identical set and
an identical `artifact-id` every run, and a new set attribute at its default is absent from the id
(no churn). `union` is valid only on unordered leaf-element sets (§11.1). Set-subtract (`-`) is
reserved, out of v1 (§26).

The discoverable, documented combine syntax lives at §13.2 (CM3's binding acceptance rider is
satisfied there); this section defines the semantics it renders.

### §12.5 Overrides: the ephemeral run layer only

**An override is temporary and limited-scope** (CA5). Its purpose is to test or one-off something
**without changing configured or default behavior**: it lives **only at L6** (run/session), is
supplied at `begin-session` (§21.4), does its job, and is **never persisted**. The next run
without it resolves configured + default values. Persistent scopes — global L2, workspace L3,
recipe L5 — hold **configuration**, not overrides; there is no override affordance replicated
per scope, and an override is never a band-aid over bad configuration design.

**Injection is collect-once, apply-at-bind** (CA7): one collection point gathers all scope config
plus the run override **before** entry resolution; M1 does entry resolution only (overrides never
touch it); values apply at M2 in two stages — M2-compose → `artifact-id`, M2-render →
`deliverable-id`. The reconcile pass *consumes* bound values and enforces hard limits; it is
**not** an override point. No stage re-injects values later, so "who injected this and when" can
never arise and identity stays reproducible.

**Ephemeral as config, recorded in identity:** an override's effect enters
`resolved-overrides` (§7.2) and lineage, so the artifact it produced is reproducible and
attributable — while no configuration anywhere changed.

**Terminology is enforced doc-wide** (CA5): "override" = this L6 mechanism only. Values carried at
persistent scopes are "configured values / scope defaults".

### §12.6 Brand-authoritative scope defaults

The brand-consistency need ("this brand requires one consistent style") is a **precedence gap,
not a packaging gap** (BO2): the brand already lives at existing rungs — an instance house voice
at L2, a client brand voice at that client's L3, both `provenance: instance` values — the defect
was only that they sat below `persona.default_voice`.

**Mechanism:** an optional **`authoritative: true`** flag (default false) on the global/workspace
**Voice** scope-default schema (an additive §11 change). A flagged value **elevates to
just-below-run**: it beats `persona.default_voice` and the recipe; only a run can deviate, and a
run that does fires a one-time warning. Unflagged values do not move. Per-value strength:

- `a` — beat `persona.default_voice` only;
- **`b` — beat through recipe (the DEFAULT for a bare flag);**
- `c` — beat the run too (opt-in hard-lock; never the default).

Why this is "wins every time": run state is ephemeral (§20) — the brand holds across **all
persisted, reusable** configuration; a run is a warned, non-persisted one-off. Config-vs-config
conflict is surfaced, never silent (§3.1).

**Constraints:** Voice-only in v1 (persona/goal/platform brand-locks are category errors; an open
bundle would straddle the compose/render identity split). The flag + warning **mechanism** is
`provenance: framework` (public); the **values** are `provenance: instance` — the house brand at
L2 (gitignored in public), a client brand at that client's L3, **never global** (isolation, §10).
A named "brand pack" (sugar over a set of flagged instance defaults — never called an "actor") is
deferred (§26).

**Lexicon brand-lock (DR-2, D-lexicon-brand-lock) — FLAGGED extension, NOT built.** Brand-lock is
**Voice-only in v1**. The DR-2 `lexicon` ships selectable at **L3/L5** by convention (a): a client's
house style lives at its workspace L3, which already matches brand-lock's L3-baseline posture — no
new mechanism. An **`authoritative`-style lexicon-scope-default** (b) — the §12.6 Voice elevation
generalized so a house lexicon can beat the recipe/run — is a **flagged §12.6 extension, deferred**
(not built): it would need the same `authoritative` flag + one-time warning on the lexicon
scope-default schema, which v1 does not ship.

### §12.7 Constraints & weights

- **Three constraint classes** (CA9; the third added by DR-4). **Advisory norms ride M2** as
  configured values: a recipe/run may deviate, which fires a one-time lint warning (§8) — the
  user's act, recorded (a Platform carries its per-format advisory refinements in
  `format_advisories`). **Numeric hard limits live entirely OUTSIDE M2**: whole-artifact / capacity
  ceilings (`hard_limits`) that are never bound, never overridable, and are enforced at exactly one
  place — the reconcile pass's terminal gate (§16), which fits or blocks and never silently passes.
  Value binding is what you'd like; the gate is what's physically possible; the gate enforces
  feasibility regardless of what M2 bound.
- **`format_structural` — the THIRD class: per-format HARD typed-section conformance** (CA9; DR-4
  C6/C8). A Platform entry may carry a per-format **`format_structural`** map (`{<format-id>: <C2
  section-schema>}`; floor `{}`) that **tightens** the base genre `section_schema` (§5.2) for one
  format at this venue — a required/forbidden/ordered/count/length section rule enforced at
  `error` severity. Like the numeric hard limits it is **M2-EXCLUDED** (never a bound cascade value)
  and enforced outside M2 — but at the reconcile **structural** gate rather than the numeric terminal
  gate (§16), because it constrains the fitted body's **heading skeleton**, not a whole-artifact
  count. It is the venue sibling of the advisory `format_advisories` and the numeric whole-artifact
  `hard_limits`; a section-limit name may not be double-homed across `format_structural` and
  `hard_limits` (a schema-lint disjointness check). A floor `{}` venue rides the base contract
  unchanged and churns no fit identity (§16).
- **Goal nudges never move an explicit user weight** (CA10). A goal-implied source-weight nudge
  adjusts only the **workspace baseline** in M3; an explicit user weight at recipe/run is the
  most-local rung and wins outright. Goals still nudge (on the baseline); the system never bends a
  weight the user set by hand (§3.1).

## §13 Serialization & encoding

### §13.1 The surface→format principle

**Format follows the dominant author/consumer of the surface** — a per-surface-class mapping,
never one-format-everywhere (D1.0):

| Surface class | Author / consumer | Format |
|---|---|---|
| Human config / registries (entries, recipes, folio types, source instances, content-kinds) | human-authored prose + structured fields | **Markdown body + YAML frontmatter** |
| Schema definitions | human-authored, machine-validated field manifests | **YAML**, standalone co-located file (§13.4) |
| Machine records (IR, AST, claims, folio markers, telemetry) | machine-written, machine-read | **JSON** (append-only streams → **JSONL**) |
| Wire / API payloads (params, results, token) | machine ↔ machine | **JSON** |
| SSOT tracking + manifest | human + automation, row-per-item | **spreadsheet / CSV** (tabular) |

**Classifying a NEW surface** — two questions in order: (1) who authors it? Human with prose →
MD + frontmatter; human-maintained pure manifest → YAML; machine → (2) what shape? Tree/record →
JSON; append-only stream → JSONL; row-per-item shared status → spreadsheet. The mapping is the
anti-drift guard: class first, then read the format off the table — never ad hoc.

### §13.2 The unified operator grammar

One canonical expression AST serves all three operator surfaces — combine-mode bindings (§12.4),
run-override params (§21.4), and discovery filters (§21.3) — so they cannot drift (D1.1):

```
Expr    := Bind(path, bind_op, operand)      # a binding (combine-mode, overrides)
         | Pred(path, pred_op, operand)      # a predicate (discovery filters)
path    := ident ("." ident)*                # dimension.attribute, or bare field
bind_op := replace | union                   # set-subtract '-' reserved, not v1
pred_op := eq | in | prefix | ge | le | gt | lt | range
operand := scalar | seq | map                # §11.1 type literals, in the HOST format's native literal
```

**Two surface syntaxes over the one AST:**

| AST node | Frontmatter / human (terse string) | Wire (JSON object) |
|---|---|---|
| `Bind(tags, replace, [a,b])` | `tags: [a, b]` | `{"path":"tags","op":"replace","value":["a","b"]}` |
| `Bind(tags, union, [c])` | `tags+: [c]` *or* `tags: {combine: union, add: [c]}` | `{"path":"tags","op":"union","value":["c"]}` |
| `Bind(voice.formality, replace, 2)` | `voice.formality: 2` | `{"path":"voice.formality","op":"replace","value":2}` |
| `Pred(provenance, eq, instance)` | `provenance = instance` | `{"path":"provenance","op":"eq","value":"instance"}` |
| `Pred(word_limit, ge, 400)` | `word_limit >= 400` | `{"path":"word_limit","op":"ge","value":400}` |

One validator and one operator vocabulary implement both renderings. Operands always ride the host
format's native literal (YAML seq, JSON array) — the only custom parsing is the dotted path + the
operator token, a tiny bounded grammar (a registered build item, §27.4), never a general
expression language. **`=` disambiguation:** `=` means replace in a `Bind` and equals in a `Pred`;
the contexts never co-occur and the AST tags the node kind, so no ambiguity exists at the semantic
layer.

**One wire key.** `Bind` and `Pred` share the single wire key **`path`** — there is no `field`
key; the interactive string form is still *described* as `field op value` (§21.3), but its wire
rendering is `{"path","op","value"}` for both node kinds. **Source-selection clauses are not
carried by this AST:** they ride M3's own grammar (§6.3), sharing the operator-vocabulary
discipline and §11.1's typed-operand rules, but their date-window operators (`contains`,
`overlaps`; §6.2) are not `pred_op` members. Whether the M3 clause grammar should fold into this
AST (extending the ratified `pred_op` vocabulary) is a registered maintainer question (§27.3).

**This section is the documented, discoverable home of the combine syntax** (CM3 acceptance
term 2): §12.4 defines the semantics; the surface forms above are the canonical documentation,
and the wire form is discoverable at runtime (§21.3).

### §13.3 Machine-record encodings

| Record | Encoding |
|---|---|
| IR envelope (§15) | JSON |
| Pandoc AST (§17) | JSON (it *is* Pandoc-JSON) |
| Claim / lease (§22.3) | one JSON object per file; **filename = the claimed id = the lock** (atomic create-if-absent on the name is the mutual exclusion); content `{holder, lease_expiry}`; release is holder-checked (§22.3) |
| Folio membership (§9.2) | **marker-per-member file**: filename = the member's `artifact-id`; content = the member record **`{added_ts, pin?, role?}`** (A4-4; §9.2/§9.6). Distinct filenames never contend; identical re-append is idempotent dedupe; a differing `pin`/`role` re-append is an atomic in-place update of that one marker, surfaced `member-updated` (§21.2). JSONL is the fallback only if a single-file representation is ever preferred |
| Telemetry (§22.5) | **JSONL** — one content-free record per line; atomic single-line append is the collision-free write; a torn final line is discardable |
| SSOT status row (§24) | tabular (CSV / Sheets / Airtable), per-item row, monotonic advance |
| emit-manifest work order (§21.5) | tabular rows that **reference** JSON layer-3 payloads for `side: external` deliverables |

All machine records are content-free where §22 requires (no client content, no secrets); claim,
marker, telemetry, and SSOT data are instance/workspace data — gitignored, never public (§10).

### §13.4 Schema & stamp encoding

- Schema files: standalone co-located **`<collection>/_schema.yaml`** (SV4; the
  all-frontmatter/no-body degenerate case of the config class). Post-§11.3 only framework schemas
  exist.
- Stamps are **bare global integers** (§11.2): `definition_version: <int>` per attribute in the
  schema file; `schema_version: <int>` per entry in its frontmatter; `schema_version` pinned per
  run in the token and recorded in the per-deliverable render-binding (§17; JSON). **Never an
  `artifact-id` input** (§7.3).

### §13.5 Build flags

- **YAML 1.2 + typed safe-load, pinned** — the "Norway problem" guard: a YAML 1.1 loader coerces
  `no`/`yes`/`on`/`off` and bare numerics, silently corrupting enum/ref tokens. Every loaded value
  validates against its §11.1 `type`; the runtime YAML library and the `---` frontmatter splitter
  are pinned (verification gate G4, §27.2).
- The §13.2 string parser is a bounded build item (grammar spec + tests; §27.4).
- Claim/marker/JSONL writes assume the atomic FS primitives of §22.8 (gate G1).
- The SSOT is fixed here as **tabular** (encoding class); the row/column schema itself is a
  tracking-domain artifact homed at §24 (registered build item, §27.4).

---

# PART IV — THE GENERATION PIPELINE

## §14 Render architecture: two passes, four layers

### §14.1 The two render passes

Rendering is **two distinct passes** (Q1, Q2):

1. **Reconcile / reshape (pass 1)** — an LLM edit pass that places the content elegantly in the
   right shape for the target platform (and language). Per-target, non-free, non-deterministic —
   and **run only when needed** (§16 no-op path).
2. **Serialize (pass 2)** — deterministic, LLM-free rendering to the output document (markdown,
   PDF, docx, …). This pass — and only this pass — is "free": same inputs + same pins ⇒ identical
   output. The old blanket "render is free" is dead; it is true of serialize only.

### §14.2 The four layers & the configurable line

```
LAYER 1  IR-canonical (persisted, platform-agnostic)          — the single re-render source
   │  pass 1: reconcile (LLM, per platform/language)
LAYER 1' IR-fitted (persisted, per fitted-id)
   │  pass 2a: serialize (deterministic)
LAYER 3  Pandoc AST JSON (persisted, ALWAYS produced)         — the standard interchange
   │  pass 2b: dispatch by the render-target's `side` setting
   ├─ side: internal  → in-system Pandoc writer → LAYER 2 bytes (md, html, pdf, docx, …)
   └─ side: external  → emit the layer-3 contract payload     → external actor renders LAYER 4
                                                                 bytes (epub, pptx, …)
```

- **The standard interchange (layer 3) is the Pandoc AST, JSON serialization, rendered by Pandoc**
  (RS1) — the one format+tool pair reaching both epub and pptx, and the natural serialization of
  the Markdown-envelope model, keeping IR→AST a deterministic JSON→JSON transform. It is a
  de-facto (single-implementation, api-version-pinned) standard, accepted on the condition that a
  de-jure formal interchange — **DocBook 5 or TEI P5** — remains addable later as one more Pandoc
  output target with zero rework (§26): the persisted IR + AST make it purely additive.
- **Internal vs external is a SETTING, not a format property.** Pandoc does the actual work; the
  renderer is a thin dispatcher that calls Pandoc per the render-target's `side` field (§17). A
  format switches sides by a config edit — the mechanism (emit AST; call Pandoc) is uniform; the
  boundary is configuration. Defaults: easy types (md/html/pdf/docx) internal; esoteric
  (epub/pptx) external.
- **The v1 story is not degraded output:** v1 emits the rich IR + the easy internal types + the
  standard interchange; esoteric formats are produced externally *from* the interchange. Only
  internal esoteric byte-generators are absent. The two honest capability ceilings — fixed-layout
  EPUB and bespoke PPTX — are exactly where the external layer-4 path and the additive
  DocBook5/TEI target earn their keep.
- **Pandoc's binary version and AST api-version are pinned** — a hard build requirement (§17,
  §21.8). The AST is single-document: folio/part orchestration is the pipeline's job, never
  Pandoc's (§17).

## §15 The IR

- **Envelope: JSON, Markdown in the leaves — decoupled from §13's config formats** (RI1). The IR
  is machine-generated, machine-consumed, immutable, and the input to a deterministic transform;
  JSON keeps layers 1→3 in one serialization family. Only the IR-*validation schema file* follows
  §13.4 — a soft, format-only dependency.
- **Structure: an ordered `parts` list** (RI2). Each part =
  `{part-id, role, constraints?, packaging_hint, body(markdown)}`: `role` is the Format-declared
  part name; `part-id` is the composite-part handle `(artifact-id, part-id)` — stable,
  reproducible, IR-resident; `constraints?` carries per-part attribute values (the per-part
  override *implementation* is deferred, §26); `packaging_hint ∈ {in-document, standalone}` drives
  one-AST-vs-N at serialize (§17). A part's advisory intra-work `sequence` (§9.5, §17) is its
  ordinal position in this ordered `parts` list — implicit here, materialized as an explicit
  attribute at AST/payload time (RI8, RI14); the IR part shape carries no separate `sequence`
  field. Single-part formats collapse to a flat body. Composite
  structure lives only in the IR — never in the AST as a multi-document construct.
- **The grounding ledger** (RI3): `grounding: { fact-id → { tier, source_instance_id, source_repo,
  source_commit, traceability_anchor, scores_snapshot } }`, with inline `fact-id` references on
  claims in the Markdown leaves. Content leaves stay pure Markdown; every grounded claim is
  addressable (the reviews §19 and citability §6.5 both need per-fact resolution). The ledger
  stores **ids, anchors, commits — never secret values** (§3.3).
- **The optional `attestation` ledger carrier** (RI3, DR-6 v1). A ledger entry MAY carry one
  extra `attestation` field — the scenario-2 pool-relation record `{primary, anchor, relation}`:
  `primary` a STRUCTURED CSL-JSON descriptor (OPEN key set, one-file-upgradeable), `anchor` a
  non-empty held-pool anchor string, `relation` a named PROV-O token (`wasQuotedFrom`; the
  one-file-extensible closed set `ATTESTATION_RELATIONS`). The ledger key set is modeled
  `LEDGER_REQUIRED` (the original 6 fields) + `LEDGER_OPTIONAL = (attestation,)` and checked by the
  bounds idiom `LEDGER_REQUIRED ⊆ keys ⊆ LEDGER_REQUIRED ∪ LEDGER_OPTIONAL`; it is validated ONLY
  when present. A scenario-1 fact OMITS it and its entry is BYTE-IDENTICAL to pre-DR-6 → the
  `artifact-id` is unchanged (the ledger is not in the identity preimage, §7). This is the v1
  CARRIER only: scenario-2 detection/production + attributability/survivability enforcement are NOT
  built (deferred — `docs/known-issues.md` DR-6).
- **The optional `references` CSL-JSON block** (RI3, DR-5 C1–C4). When an artifact CITES, the IR
  envelope carries a top-level **`references`** — a list of CSL-JSON citation items, one per cited
  pool source. It is **additive-optional** (the same `keys ⊆ TOP_LEVEL_KEYS` bound as
  `section_conformance`), **OMIT-WHEN-ABSENT** (a non-citing artifact carries no key → the golden
  compose corpus is byte-identical), and **body-blind** — recorded OUTSIDE `binding.preimage`, so it
  moves NO `artifact-id` (no `ir_version` bump). As a NEW top-level key it gains its own §3.3
  recursive no-secrets scan. **It is MACHINERY-projected, never authored (C2):** compose derives
  `references` from the grounding ledger's DISTINCT pool sources — one CSL-JSON item per
  `source_instance_id` under a deterministic `s0`/`s1`… key (single-sourced, mirroring the ledger's
  `f0`/`f1` idiom), gated on a body that actually cites (`_body_has_citation`). **The writer emits
  `[@key]` markers ONLY (C3):** `writer.md` forbids a self-authored `references`/bibliography (§6.5)
  and cites solely the projected `available_citations` keys handed to it. **Compose HARD-resolves
  every `[@key]` (C4) — the ratified D-cite-locus = COMPOSE:** post-mint, inside the existing bounded
  re-ask, a body carrying the `[@` marker is parsed through the SINGLE pinned pandoc reader and every
  `Cite` id is checked ⊆ the projected key set (robust across every citation form — multi-key,
  locator, prefix, suppressed-author — with NO regex); an unresolved key (or an invalid bare/braced
  form) feeds a correction note and, on exhaustion, **blocks** with the never-persisted
  `citation-unresolved` (a GENERATION-tier §21.7 block code, sibling of `compose-contract-violation`).
  A non-citing body is never parsed, so the non-citing corpus runs byte-identical to pre-DR-5.
- **Composition binding** (RI4): the envelope records the resolved `artifact-id` preimage — topic,
  persona, format, voice, sorted goal-set, source-subset, resolved-overrides delta, and the
  source commit-map (§7.2) — plus the computed `artifact-id` (full digest, §7.4). The IR is self-describing and
  reproducible.
- **The DR-3 outline emit bridge** (`build_outline_ir`, RI4). An editable outline enters the IR
  **only at emit**, through a thin bridge: it sets the leaf `body` to the normalized outline
  `N(md)` and builds an **ordinary `Format=outline` artifact** via the real `build_ir` — an EMPTY
  grounding ledger, no `data-fact` spans (the outline asserts no facts, §6.5). This is **no new IR
  type, schema, or registry root**: the outline renders and fetches through the EXISTING
  serialize/payload path (§17), to any output-type the coordinate selects. Its `artifact-id` rides
  the `outline-digest` (the §7.2 emit own-body home) and a re-emit is an idempotent no-op (§22.7).
- **The DR-4 `section_conformance` IR field + the base structural gate** (RI4, DR-4 C4/C5). Compose
  records the RESOLVED base Format `section_schema` (§5.2) on the IR as an optional top-level
  **`section_conformance`** key — additive-optional (the unchanged `keys ⊆ TOP_LEVEL_KEYS` bound,
  mirroring the `attestation` LEDGER_OPTIONAL pattern), **OMIT-WHEN-ABSENT** (a floor `[]` / no
  contract records no key), and **NOT in the artifact-id preimage** — so it is identity-neutral
  (the same preimage ± the field mints the same `artifact-id` and binding digest; no `ir_version`
  bump). When present it is validated by reconstructing each rule through the real C2 constructors
  (single-sourced vocabulary; a malformed schema is refused loudly as `ir-schema-invalid`). It is
  enforced by the **HARD base structural gate at compose** — **platform-neutral** (genre base
  sections only; per-venue tightening is the reconcile structural gate, §16): post-mint, inside the
  existing bounded re-ask, the composed flat body is parsed (the F1 section grammar) and checked
  against the base schema (C2 `check_conformance`). **Error-severity** base violations
  (required/forbidden/order) feed the re-ask a correction note and, on exhaustion, **block** with
  the never-persisted `section-conformance-violation` (a GENERATION-tier §21.7 block code, sibling
  of `compose-contract-violation`). **Advisory** (warning/info) violations never block here — their
  surfacing is the DEFERRED Review-1 advisory check (D-4), re-derivable from the persisted IR. A
  Format with no `section_schema` is a no-op (compose bytes byte-identical to pre-DR-4); a
  `section_schema`-bearing Format composing a NON-outline body is EXEMPT (§5.2).
- **The opaque `metadata` bag rides the envelope** (§11.3): stored, passed through, never
  interpreted, never routed into AST content — carried as a side channel to the layer-3 contract.
- **Version stamps** (RI4; DR-6 F-a): `ir_version` (now **2**, validated GENERATION-TOLERANTLY —
  `∈ KNOWN_IR_VERSIONS = {1,2}`, not exact-equality, so an IR stamped at an older additive-optional
  generation still re-reconciles) + the `pandoc-api-version` pin — render-reproducibility pins, not
  migration targets (the IR is immutable and never schema-migrated; §11.6).
- **The substance floor** (RI1; the GAP-6 guardrail). Every leaf `body` (flat) and every part
  `body` must carry ≥1 Unicode letter or digit in its VISIBLE text — the reader-visible characters
  after Pandoc bracketed-span attr blocks (`[…]{.CLASS data-…}`) are stripped. A substance-free
  body — `"..."`, `"…"`, `"###"`, whitespace-only, or a markup-wrapped placeholder
  `[...]{.EXTRACTED data-fact="f0"}` whose visible text is just `...` — PARSES and validates as
  non-empty under bare truthiness yet ships an EMPTY artifact; this floor (`validate_ir`, one
  chokepoint for every IR-building path) makes it fail loud (`EmptySubstanceError` /
  `ir-empty-substance`) into the §21.9 bounded re-ask, NEVER persisted. It is a pure, content-blind
  SHAPE gate (no Markdown parse, no §21.9 boundary crossing) and a MONOTONE strengthening of the
  old non-empty check (zero regression). **FIX vs GUARDRAIL (GAP-8 / GAP-6).** Stripping the
  leading `<!-- … -->` developer comment from `writer.md` (the model quoted it when it refused, so
  it produced no artifact at all) is the FIX for the pre-parse refusal derail; this substance floor
  is the loud-fail GUARDRAIL that closes the post-parse valid-JSON-empty hole. They sit on opposite
  sides of the parser gate and converge into the SAME bounded re-ask. Scope-honest: a placeholder
  whose visible text carries a stray letter/digit still passes the floor and is Review-1's domain
  (§19) — the floor is a hard shape gate, never a quality judgment.
- **IR-canonical is platform-agnostic:** no platform, language, output-type, or presentation
  appears in it. Those enter at reconcile (IR-fitted) and serialize.

## §16 The reconcile pass (pass 1)

**Consumes:** IR-canonical + one target `(platform, language)` + the effective constraints
(advisory values from M2; the hard limits from the platform entry) + the reconcile-strategy
selection (`adapt | split | pass | truncate`, §12.3) + the voice/content parameters to preserve.
**Produces:** a persisted IR-fitted variant per `fitted-id` — reshaped leaves, possibly split into
reconcile-parts `(deliverable-id, part-id)`, localized, with provenance bindings intact.

**Internal ordering is fixed** (RI5; the Q13 side-effect ordering, extended by DR-4 C8):

1. **Localize** (when `language` ≠ source language; feature deferred, slot designed — §5.3, §26).
2. **Reshape** per the selected strategy toward the platform's capabilities and limits.
3. **The DR-4 structural gate** (C8) — the fitted body is checked against the selected venue's
   per-format `format_structural` contract (§12.7), evaluated with the SAME C2 `check_conformance`
   used by the base gate (§15; the venue schema reconstructed through compose's single-sourced
   rule decoder, never a fork). An `error`-severity structural breach — a required / forbidden /
   ordered / count / **per-section length** (the #4a limits below) rule — **blocks that
   deliverable** with `section-conformance-violation` (§21.7), while sibling fanout items continue
   (the §6.4 block-and-report pattern).
4. **The TERMINAL hard-limit gate** — last, **after** localize (localization alters length and can
   breach a limit step 2 had satisfied), and scoped now to **whole-artifact / capacity** numeric
   limits ONLY (`hard-limit-exceeded`, §21.7): the **#4a per-section numeric limits are RE-HOMED to
   the structural gate above** (they are section-addressed, so they ride the venue's C2 schema, not
   this whole-artifact gate). The gate is **fit-or-block, never silent-pass** (CA9). Advisory norms
   only warn and are the user's to deviate from (§3.1).

**Joint block-and-report — the early-return refactor** (C8). The structural gate (3) and the
numeric hard-limit gate (4) both evaluate BEFORE any block-return, so a fit that breaches both
surfaces BOTH concern-sets on the reconcile outcome (`structural_violations` AND `blocked_limits`,
the structural `section-conformance-violation` the primary block code) — never a single early return
that hides the other. `format_structural` is **M2-EXCLUDED** and read straight from the selected
platform entry's effective values; only the pinned format's tightening threads in, so an unrelated
format's tightening never churns this fit (the C7→C8 identity obligation).

**The pass-1 fidelity constraint** (RI3-fidelity, extending Q13): because reconcile is an LLM
rewrite, it MUST preserve **(i) voice and content parameters, (ii) meaning, (iii) the
per-claim provenance/tier bindings — re-anchored onto the fitted text, (iv) the outline's
declared section keys, and (v) the inline `[@key]` citation markers (both preserved below).** It
must never upgrade an INFERRED lead into asserted fact (tier
promotion is impossible anywhere downstream of ground, §6.5). Losing (iii) would blind the
deliverable review's grounding re-check (§19). This constraint binds the product-plane reconcile
agent's contract (§27.4).

**The DR-4 preserve-section-keys foundation** (C7). Reconcile is now section-key aware. Scoped to
the keys the IR's resolved `section_conformance` base schema names (a plain reshape that adds
or renames a NON-schema heading is **not** blocked — a global fitted ⊆ composed would regress every
reshape), the fit MUST **preserve through** every schema-referenced heading the outline declared,
and MUST **NEVER MINT** a new schema-satisfying role/type from content absent at compose — **the
section-typing role-forgeability backstop** (a fit cannot forge a section the writer never produced
merely to satisfy a venue's contract). A venue that legitimately makes a section optional/forbidden
(a `presence` / `required:false` rule in this format's `format_structural`) lets it be dropped. A
preserve/no-mint breach (`structure-not-preserved`, a DISTINCT code) first-remediates via the SAME
bounded fidelity re-ask; a persistent breach exhausts the bound and is NEVER fitted (surfacing as
`fit-fidelity-violation`). This preserve-through is the foundation over which the C8 terminal
structural gate's block-and-report verdict layers.

**The DR-5 preserve-citation-keys obligation** (C8). Reconcile is likewise citation-key aware:
because the reshape swaps whole leaf bodies, an inline Pandoc `[@key]` the composed body carried can
be MINTED anew or MANGLED into a different (unresolvable) key by the rewrite. Per **D7 = SUBSET-only
(S5)** the fit's inline citation set must be a SUBSET of the composed body's: a citation DROP is
PERMITTED (an orphaned reference is benign — a silently-lost whole FACT still surfaces as
`fit-fidelity-violation`), but a MINT or MANGLE — an inline `[@key]` absent from the composed set —
is BLOCKED as `citation-not-preserved` (a DISTINCT code) via the SAME bounded fidelity re-ask. This
is the citation analog of C7's `structure-not-preserved` role backstop; the anti-FABRICATION
resolution (cited ⊆ the PROJECTED reference set) is C4's compose-locus check (§15), not this
reshape-preserve check — so grounding is enforced at TWO loci over one ledger, never one chokepoint.

**The DR-2 lexicon fidelity-preserve obligation — ADVISORY, read from the binding** (C4). Reconcile
is likewise TOLD to carry the already-applied house style through an `adapt` / `split` / `localize`
reshape. Recorded HONESTLY: unlike the C7 `structure-not-preserved` and C8 `citation-not-preserved`
HARD gates, this is a **recommendation in the reconciler prompt, NOT a machine gate** — no
conformance check, no distinct block code, no re-ask. It reads the applied rules from the ONE record
that already carries them — `binding.preimage.lexicon.delta` (the §7.2 `{entry, delta}` component) —
so the reconciler is told exactly what compose applied and nothing is re-derived. It is
**omit-when-absent** (a lexicon-less IR → no key → a byte-identical prompt) and inert on the `pass`
strategy (the reconciler is never invoked). It rides the §3.3 **language split**: under `localize`,
language-invariant rules (proper-name casing, `banned_terms`, `mechanical`) hold, while
language-specific rules (`spelling`, English-only `preferred_terms`) may not transfer. This advisory
ceiling is honest about the reshape-undo residual (§2.2/§3.3): a lexicon *change* already re-composes
via the §7.2 `artifact-id` component, so §16 only preserves what compose applied — the
`reconcile-inputs preimage` is **UNTOUCHED** (the lexicon never enters it; already covered by the
`artifact-id`, so every `fit-digest` is byte-identical).

**The reconcile-inputs preimage & the fit-binding (FR2).** Reconcile consumes NON-coordinate
inputs, and they are recorded once, at the level that consumes them. The **canonical
reconcile-inputs preimage** (sorted keys; delta-vs-floor per CA6 — an attribute enters only when
its effective value ≠ its schema default, so an additively shipped constraint attribute at its
default churns nothing) comprises: (1) the effective reconcile-strategy (§12.3); (2) the platform
entry's effective hard-limit set (CA9; M1-resolved entry values); (3) the effective advisory
constraint values bound at M2-render (the Platform per-format projection + any L3/L5/L6
deviations), scoped to attributes the reconcile pass consumes; (4) any other reconcile-consumed
rendering-dimension attribute binding; (5) **this artifact's pinned-format `format_structural`
venue tightening** (DR-4 C8; the HARD structural class, §12.7), **OMIT-WHEN-FLOOR** — a floor `{}`
value produces NO `structural` key, so every floor platform's `fit-digest` is byte-identical to the
pre-DR-4 four-component preimage (the golden fit-digest corpus is unperturbed) and only a non-floor
venue tightening adds the component and churns the fit identity — exactly the recording set, no
more. **Excluded** (each already identity-covered or identity-irrelevant): the voice/content
parameters to preserve (fixed
by `artifact-id`, §7.2); platform and language themselves (coordinates); serialize-side pins and
Presentation inputs (deliverable-level, §17); `schema_version` and the `metadata` bag (§7.3).
When localization GA lands (§26), its non-coordinate knobs join this preimage additively.

**One record, one authority — the `fit-binding`.** The IR-fitted envelope carries a `fit-binding`
(sibling of RI4's artifact binding): the canonical reconcile-inputs preimage, its `hex12` digest,
the full fitted-id, and `minted_ts` — plus the reconcile outcome record (strategy used, localize
languages, gate outcome). The mismatch warn, the fit-revision identity digest, and the S0
preimage check all read this ONE record (§21.8, §7.4, §22.3), so what the system warns on and
what it mints on can never drift. Serialize-side pins stay in the per-deliverable render-binding
(§17): inputs are recorded at the level they are consumed.

**No-op path:** when language matches, nothing breaches, capabilities match, and no reshape is
requested, pass 1 is skipped and IR-fitted ≡ IR-canonical — determinism and zero LLM cost where
fitting isn't needed.

**Supersession (T4).** The archived model stated reconciliation "never blocks" and always warned.
That clause is dead: hard limits **block when unfittable** (Q3/CA9/RI5). The strategy set
(`adapt`/`split`/`pass`/`truncate`), the default of auto-adapt/split, the always-recorded warning
on advisory deviation, and the artifact's preservation (non-destructive, render-stage) all
survive. The old never-block text must not re-enter from any archived source.

## §17 The serialize pass & dispatch

- **Serialize is deterministic and always produces + persists the layer-3 AST** (RI6) — even for
  internal targets: internal writers consume it (`pandoc -f json -t docx`), it is the output-type
  fanout pivot, and it is the external hand-off substrate.
- **IR→AST path** (RI7): reconcile emits IR-fitted as fully-annotated Pandoc-Markdown — parts as
  fenced Divs `::: {#part-id .role}`, provenance as bracketed Spans `[claim]{.tier data-fact=…}` —
  and a **single pinned `pandoc -f markdown -t json`** parse yields the AST with all attributes
  intact. The reader version + extension set are pinned (verified lossless round-trip for
  `fenced_divs` + `bracketed_spans` at the pinned version).
- **Attr mapping** (RI8): a composite part → a `Div` (`id` = part-id, `class` = role, kv =
  advisory `sequence`, packaging hint). A grounded claim → a `Span` (`id` = fact anchor, `class` =
  tier, kv = source instance, commit, traceability). Office/PDF writers drop unknown attributes —
  desirable — with the hard consequence that **provenance is consumed at the IR/AST layers only,
  never recovered from output bytes** (§19 reads IR/AST).
- **The provenance-strip filter (serialize-owned):** publish-facing writers — the html5/epub3
  and the whole HTML/EPUB/slide family — WOULD emit provenance attributes into published bytes
  (`data-*`, tier classes). A **pinned, deterministic pre-serialize filter strips the provenance
  Attr for EVERY writer UNLESS it is on an explicit safe-set** (`SAFE_WRITERS` — the
  internal-record writers that intentionally BEAR provenance: markdown/json/docx/pptx/pdf/plain)
  (R-4). The policy is **fail-CLOSED**: a new or unknown writer strips by DEFAULT, so a future
  publish target can never silently leak provenance — closing the one-file-add extensibility hole
  an html5/epub3-only *allowlist* would leave open (add a writer, forget the enumeration, leak).
  It is owned by serialize, is not a Presentation lever, and cannot be disabled by any style
  configuration (PD3) — it protects the grounding + no-secrets guarantee (§3.3).
- **The SD-5 section-attribute validity transform (serialize-owned, DR-4 C9):** DR-4 authors typed
  sections as `## H {#id type=figure}` headings; on a public writer Pandoc would emit those bare
  `type`/`role` kv as **illegal HTML5** (`<h2 id=… type="figure">`). A **pinned, deterministic**
  pre-serialize transform strips the bare `type`/`role` kv from heading nodes on the SAME
  `should_strip`-gated public-writer copy the provenance-strip filter runs on — **keeping** the
  valid `{#id}` anchor — so v1 ships no illegal syntax. It is DISJOINT from the provenance strip by
  NODE (Header vs Div/Span) AND by key set (`type`/`role` vs `data-*`); the internal SAFE writers
  (markdown/json) keep the attrs (the round-trippable internal record). Its identity is captured
  **OMIT-WHEN-ABSENT**: a `section_attr_transform_version` joins the serialize-inputs preimage's
  tool bundle ONLY when the transform actually fired (a typed public render), so every existing /
  non-typed / SAFE render is byte-identical (the golden render-digest corpus is unperturbed); a
  typed render records the version and **re-mints its deliverable loudly** (§7.4; FR7.3). No
  `schema_version` bump; the provenance strip's own pinned version is untouched.
- **Content-driven citeproc enablement + the `references`→meta threading (DR-5 C5/C6).** When an
  artifact cites, the fit's CSL-JSON `references` block (§15) is threaded into the AST as
  **frontmatter**: serialize PREPENDS a canonical `references:` YAML block so the SAME single pinned
  `pandoc -f markdown -t json` parse lands it at `ast["meta"]["references"]` (C5, D2 = frontmatter) —
  **RI7 stays `--citeproc`-free and presentation-independent** (the AST keeps its UNRESOLVED `Cite`
  nodes; one AST still serves every look, PD5). (C5 scopes the frontmatter to the FLAT single-document
  render; per-document meta for a multi-document deliverable is registered, not built —
  `docs/known-issues.md`.) The citation is RESOLVED one step later, AT THE WRITER: a **pinned,
  deterministic serialize-filter enables pandoc's `--citeproc`** — the CONTENT-driven twin of the
  SD-5 strip — whenever the AST carries a `Cite` node (a pure function of CONTENT, keyed off neither
  the writer nor any `csl` lever; it is UNGATED and, like the strips, never a Presentation lever), so
  a `[@key]` body resolves against `meta.references` under the writer's default author-date style
  (fixing the broken `plain` default), and the C7 `csl` lever, when set, appends `--csl` ON TOP to
  override the style. Its identity is captured **OMIT-WHEN-ABSENT**: a `citeproc_enablement_version`
  (the twin of `section_attr_transform_version`) joins the serialize-inputs preimage's tool bundle
  ONLY when citeproc actually fired, so every non-citing render is byte-identical to pre-DR-5 (zero
  render-digest churn) and a citing render re-mints its deliverable loudly (FR7.3). The two version
  keys are DISJOINT and INDEPENDENT (section-attr is writer-gated, citeproc content-driven). No
  `schema_version` bump.
- **DR-7 increment B — binary-target image embedding + the render-time isolation re-gate + the
  embed-gated content-hash fold (BUILT; `docs/known-issues.md`).** Increment B makes a client body
  figure carry its actual bytes into the two BINARY internal outputs. The Presentation lowering emits
  **`--embed-resources --standalone`** for html5 (the image inlines as a `data:` URI in a self-contained
  document) and native **`--resource-path`** embedding for docx (a real `word/media/` part); `markdown`
  keeps the figure BY REFERENCE (`![](assets/…)` passthrough) and `plain` shows the caption only — so a
  `--resource-path` is emitted ONLY for an EMBED writer (html5/docx). The once-deferred filesystem asset
  loader is now real and **FENCED to `presentations/`** (rule-2 client isolation — a styling `.csl`/CSS
  file resolves against the repo root but is refused unless it lands inside `<root>/presentations`, so a
  tampered/legacy entry can never pull another client's `users/…/workspaces/…` file). Because embedding OPENS and
  COPIES whatever a figure points at, before ANY embed flag is emitted the render leg **re-runs A's FULL
  compose-time containment gate** on the persisted AST — every image target (not just the tidy `assets/…`
  subset) plus the raw-markup refusal — and REFUSES the whole render if anything is off, so a tampered
  `../other-client` document fails loudly at render (`asset-ref-uncontained` / `body-raw-markup-forbidden`)
  and its bytes are never copied; the file pandoc opens is provably the file A proved safe. The two-base
  `--resource-path` is order-pinned `(store.root, repo_root)` (client figure FIRST, so a same-named
  framework asset can never shadow it; the repo-root base preserves a co-occurring `--csl` resolution).
  Identity is honest and captured **OMIT-WHEN-ABSENT** (the C7 `csl` pattern exactly): an
  `asset_embed_version` tool-bundle key plus the embedded figures' content hashes join the
  serialize-inputs preimage ONLY for an embedding html5/docx render, so an edited figure re-mints the
  html/docx deliverable loudly (FR7.3) while the by-path `markdown` id is byte-identical (image-less and
  md/plain renders unperturbed — zero churn), and `discovery.py` re-derives `assets_embedded` from the
  stored bundle so an embedded deliverable never phantom-drifts. No `schema_version`/`ir_version` bump.
  (C — generated diagrams — reuses this loader/resource-path/embed/identity-fold machinery UNCHANGED; two
  carry-forwards remain: SVG-in-docx embedding is a C-spike unproven by B, and the external hand-off's
  body-figure fold is deferred — `docs/known-issues.md` DR-7 F4/FWD.)
- **One AST per physical output document; the pipeline orchestrates N** (RI9): the per-part
  `packaging_hint` decides — `in-document` parts co-render into one file/one AST (slides + notes →
  one pptx); `standalone` parts are N files/N ASTs, each `(artifact-id, part-id)`-addressable. The
  1-vs-N call is Format-part-role × writer capability, resolved by the dispatcher — never encoded
  in the AST.
- **The dispatcher** (RI12): the render-target registry (one-file-add, schema-versioned §11.7)
  entries declare `writer` (or `json` for raw-AST passthrough), **`side: internal | external`**
  (the setting; defaults per §14.2), `engine?`, `reference_doc?`, and pins. Dispatch = look up
  target → produce AST → internal: call Pandoc in-system; external: persist AST + emit the
  contract payload. Switching sides is a config edit. A capability-infeasible
  platform × output-type pairing is a dispatcher feasibility check (`capability-infeasible`
  warn/block, §21.7) — never a reconcile reshape.
- **Presentation lowering** (PD3/PD4): the dispatcher consumes
  `lower(presentation, writer, output-type) → RenderInputs{flags, variables, assets+hashes,
  engine}` — one flat struct, applied as one writer call on the persisted AST. The pin bundle is
  its preimage.
- **The pin set & the render-binding** (RI13; FR7.1): Pandoc binary version · AST api-version ·
  PDF engine + version · `reference_doc` id + hash · the provenance-strip filter's pinned
  version/hash (html5/epub3 — it deterministically alters bytes) · the consumed AST, cited by its
  reader-pin digest (§18) · Presentation asset hashes + variable snapshot. Home: the
  per-deliverable **render-binding** — the render manifest, formalized as the deliverable-level
  analogue of the fit-binding (§16): the canonical **serialize-inputs preimage** (below), its
  `hex12` digest, the full deliverable-id, and `minted_ts`, referencing the fitted level's
  fit-binding. Reconcile-consumed inputs and reconcile outcomes (strategy used, localize
  languages, gate outcome) are recorded at the fitted level (§16) — inputs live at the level that
  consumes them; serialize pins stay per-deliverable. The identity digest, the S0 preimage check,
  and the currency computation all read this ONE record (§7.4, §21.3, §22.3), so what the system
  keys on and what it compares can never drift. Same IR-fitted + same pins ⇒ byte-identical
  output. Drift check: a persisted AST whose reader-pin digest mismatches the pinned toolchain is
  re-derived from IR-fitted onto its new key (free, §18) — never misread, never overwritten.
- **The serialize-inputs preimage** (FR7.1) — everything that determines the output bytes given
  the fitted AST and the coordinates. Canonical form: sorted keys; delta-vs-floor (CA6) for
  schema-attribute values; **literal** for tool versions and asset content hashes (they have no
  schema floor and are always present — they churn only when they actually change, which is
  exactly when bytes change). Included: (1) the pinned tool bundle above — **config-pure, never
  ambient**: the preimage reads the *pinned* bundle (instance config), never the installed
  environment (an installed-vs-pinned mismatch is a pre-existing ops error the pin discipline
  already surfaces, not a new identity fork), keeping the digest deterministic per (config,
  workspace store) and machine-independent; (2) the render-target entry's effective values,
  delta-vs-floor (`writer`, `engine?`, `reference_doc?` + content hash, writer options — the
  output-type *slug* is a coordinate and excluded; the entry's *values* are inputs, the same
  coordinate-vs-content line FR2 drew for the platform entry, §16); (3) the lowered Presentation
  `RenderInputs` (PD3 — "the pin bundle IS its preimage", taken literally): flags, the variables
  snapshot, `highlight_style`, pdf opts, and **every asset by content hash** (an edited css file
  churns the digest even when no schema version moved; delta-vs-floor on the variable/attribute
  values preserves PD5's zero-churn pledge at this level too). **Excluded:** everything
  fitted-level — reconcile inputs live in the fit-binding and are covered by the deliverable-id's
  fitted **prefix**, including any fit-revision qualifier · the four coordinate slugs themselves ·
  **`side: internal | external`** (dispatch routing, not a byte-determining input — flipping side
  neither invalidates existing bytes nor changes what identical inputs would produce) ·
  `schema_version` and the `metadata` bag (§7.3).
- **Serialize-input evolution auto-mints a revision — loud, never silent, never in-place**
  (FR7.3): when an unqualified render's current serialize digest matches no persisted
  render-binding, the system **auto-mints the matching serialize-revision deliverable**
  (`…_<hex12>`, §7.4) and returns it `ok` / **`re-serialized`** (§21.7; resolution rule §21.8) —
  the B4-4 no-replace commit abolishes in-place re-runs. **The asymmetry principle:** consent is
  required where re-running is costly or content-changing — reconcile warns and waits for an
  explicit force (§21.8); auto-correctness applies where re-running is free and deterministic —
  serialize, and the AST re-derive above. Both are loud; no user setting is bent in either case
  (executing the user's current config IS respecting it — Q3). Minting happens in `render` only —
  never in `fetch-by-id`, never at `emit-manifest` (§21.5).
- **The layer-3 contract payload** (RI14; carried by `emit-manifest` for `side: external`, §21.5):
  (1) the Pandoc AST JSON (embedding its api-version); (2) a reproducibility sidecar —
  `deliverable-id`/`artifact-id`/`fitted-id`, requested output-types, required Pandoc version +
  writer + engine + reference-doc, all pins; (3) the part structure — ordered `part-id`, `role`,
  advisory intra-work `sequence`, packaging hint — so the actor knows how many files to emit and
  can address part 3/7 directly; (4) the opaque `metadata` bag, untouched; (5) the `language`
  (already localized — the actor never re-localizes). **DR-5 C10 — the citeproc requirement (citing
  AST only).** The handed-off AST carries UNRESOLVED `Cite` nodes (RI7 is citeproc-free) plus the
  `meta.references` MetaMap; since the EXTERNAL actor renders with ITS OWN pandoc/citeproc, the
  sidecar (2) gains a `citeproc` REQUIREMENT block for a citing AST — `enabled`, the per-venue `csl`
  STYLE (the C7 `(path, content-hash)`, or None for the writer default), and the pinned
  `pandoc_version` — so the actor runs `--citeproc` (+ `--csl` when set) under the pins. It is
  OMIT-WHEN-ABSENT (a non-citing payload gains no `citeproc` key → byte-identical to pre-C10; a
  citation-less csl-set render carries no csl requirement, mirroring dispatch's content-gating of
  `--csl` WITH `--citeproc`). **GAP-1 determinism gate:** internal targets resolve under the PINNED
  pandoc, but an external actor's OWN toolchain may render the same paper + csl differently — OUTSIDE
  the pin boundary. The block carries the pandoc version + csl as pins the actor MUST honor; the
  payload can STATE the requirement, never enforce the actor's toolchain (registered,
  `docs/known-issues.md`). Explicitly excluded: provenance/tier tags as publishable content; any
  secret.

## §18 Persistence & regeneration

**What persists, keyed how** (RI10):

| Object | Key | Persisted |
|---|---|---|
| IR-canonical | `artifact-id` | yes — mandatory, immutable; the single re-render source |
| IR-fitted (carrying the fit-binding, §16) | `fitted-id` (incl. any fit-revision qualifier) | yes — the expensive reconcile output; holds split part-ids |
| Pandoc AST | `fitted-id` (+ reader-pin digest) | yes — the interchange + fanout pivot |
| Layer-2 bytes | `deliverable-id` (incl. any revision qualifiers) | yes (those produced) |
| Layer-4 bytes | `deliverable-id` | produced externally; the system persists the handed-off AST |
| Render-binding (manifest + serialize preimage/digest, §17) | `deliverable-id` | yes |

**The AST store key's disambiguator is the reader-pin digest** (FR7.1): api-version + the
Markdown-reader extension set + the Pandoc version — api-version remains its dominant component.
The AST's bytes depend on all three, so a reader-pin drift at an unchanged api-version lands the
re-derived AST on a **fresh key**, never an in-place rewrite. This is internal store keying, not
a D2 id — the AST is not an id-family member, so no grammar change (§7.4); the serialize preimage
cites the consumed AST by this digest (§17). The fit-binding rides the IR-fitted JSON and the
render-binding rides the deliverable record — no new store, no new G1 primitive (§22.8, §27.2).

**Regeneration tiers** (RI11) — always the cheapest correct path, never a re-compose:

| Change | Path | LLM |
|---|---|---|
| New output-type or presentation, same platform/language | persisted AST → one writer call | none |
| Pandoc/api-version bump · writer bugfix · presentation-asset or render-target value edit | re-derive AST under its new reader-pin key + **auto-mint a serialize-revision deliverable** (§17, §21.8; FR7) — never an in-place re-run or overwrite | none |
| New platform or language | IR-canonical → re-reconcile → new fitted-id | reconcile only |
| Reconcile inputs changed (strategy, hard limits, advisory bindings) | explicit `force_reconcile` → **revision fitted-id** `…_<hex12>` from the same approved IR-canonical (§21.8; FR2) | reconcile only |
| Source commit advanced / any content-dimension change | new `artifact-id` → re-compose (old persists as lineage) | compose |

The platform commitment line is reconcile, and it is a **cost boundary, not a lock** (RI10):
IR-canonical persists, so re-targeting is always one re-reconcile away. `fitted-id` does not move
that line — it only names cache entries. Publishing the bytes anywhere is external and unbounded
(§2.2). Reconcile-split parts are computed at the `fitted-id` level and project identically into
every `deliverable-id` sharing it (§9.5 stability caveat holds).

## §19 Review gates

Two distinct, complementary reviews (Q16):

1. **Artifact review — the early substance gate.** A full content/quality review of the
   platform-neutral IR, run **once per artifact, before rendering**. Catches substance problems
   while they are cheap (pre-fanout, one review amortized over all deliverables). Reads the IR +
   grounding ledger; verifies grounding (EXTRACTED floor, §6.5), goal fit, persona fit,
   citability (§6.5).
2. **Deliverable review — the complete final validation.** A **full** review of **every** final
   deliverable before hand-off — substance AND rendering fidelity AND publishability: voice and
   content parameters preserved (§16 fidelity), meaning intact, provenance bindings intact
   (checked at the IR-fitted/AST layer, §17), platform hard limits respected, correct format and
   splits. **Accepted cost:** it runs fully on every deliverable and does not inherit the
   compose-once economy — the deliverable is what ships and must be fully vetted. Review 1 remains
   the fail-fast gate that saves wasted rendering.

**Review 1's `grounding` check is a two-dimension ADVISORY audit (DR-6).** The artifact review runs
it in BOTH directions and raises a `concern` — NEVER a block: **coverage** (a declarative sentence
asserting a specific external fact yet carrying no grounding span / `data-fact` — an unmarked
assertion) and **faithfulness** (a grounding span whose bound ledger fact does not support the
sentence). A `claude -p` self-check is not a hard per-claim reject, so both stay advisory;
`ARTIFACT_CHECKS` and `REVIEW_VERSION` are unchanged. The hard tier-promotion / EXTRACTED-floor
rejects stay upstream at the IR gate (§15) — this audit surfaces only the residual soft cases.

**Honest scope — DR-6 v1 is Option A (advisory).** Increment 1 ships the ADVISORY path only: this
two-dimension Review-1 audit, the `attestation` ledger carrier (§15), the `grounding_posture`
policy (§6.3/§12.1), and the opt-in item-level abstain (`grounding-uncovered`, §21.7). The HARD
self-demarcation coverage gate, the `.framing` mechanism, and the whole-corpus migration are NOT
built — reconsiderable, or a future fact-checking docs-researcher agent's domain. See
`docs/known-issues.md` DR-6.

**Fit and serialize revisions × the gates (FR5, FR7.5).** A forced re-reconcile reuses the SAME
approved IR-canonical — the `artifact-id` is unchanged, so Review 1 is not re-run; preserving
that approval is the feature's entire point. Every deliverable of a revision fit is a **new
deliverable** and takes the **full** Review 2 (the fitted text is an LLM rewrite — substance,
rendering fidelity with the §16 fidelity constraint, provenance bindings re-anchored,
publishability, hard limits). Review outcomes attach to deliverable-ids and **never transfer
across revisions**; old deliverables keep their review status on their old ids (their bytes are
unchanged and were valid under the config they were fitted to); whether previously published
copies are re-published from a new fit is the publisher's domain — external, always (§2.2).
**Every serialize-revision deliverable likewise takes the full Review 2** (FR7.5): Q16 is
explicit that Review 2 is a COMPLETE review of EVERY final deliverable — a scoped
rendering-fidelity-only re-check would contradict the ruling and scope away exactly the risk
class a serialize change carries (rendering fidelity and publishability as rendered). The
economy exists without weakening the ruling: the substance portion re-verifies text the reviewer
has seen (same fitted text, same provenance bindings, unchanged IR-fitted/AST layer), so it is
fast in practice; the ruling's letter stays intact. Artifact review (Review 1) is untouched at
both levels.

Hard drift and hard limits never reach review — they block earlier (§11.5, §16). The reviews
handle residual soft advisories (warn-level results, INFERRED-lead checks) and full-content
quality.

**The §15 substance floor vs Review 1 (GAP-6 reconciliation).** Read the "early substance gate"
above as two complementary mechanisms, not one: the §15 substance floor is a HARD, content-blind
SHAPE gate (≥1 visible letter/digit) enforced PRE-PERSIST at `validate_ir`, so a bare
substance-free body (`"..."`, a markup-wrapped placeholder) is rejected into the §21.9 bounded
re-ask and NEVER mints; Review 1 is the SOFT, advisory content/quality review of a body that DID
compose (goal/persona fit, citability, INFERRED-lead honesty, a thin-but-letter-bearing
placeholder). The floor is the loud-fail GUARDRAIL closing the valid-JSON-empty hole — GAP-8's
`writer.md` header strip is the FIX for the refusal derail that produced such bodies. The floor
sits in `validate_ir` (one chokepoint), NOT in post-mint Review 1, which would fight the
immutable-id / no-replace model (§22.3).

---

# PART V — EXTERNAL CONTRACTS

## §20 Actors & sessions

**Two actor classes.** **Internal** — the co-located interactive session (the maintainer or a
user driving the pipeline directly). **External** — a stateless caller (n8n workflows, a wrapper
website, a native app) that spawns headless pipeline invocations and holds its own state between
them.

**The pure-function run contract.** The pipeline is
`run(workspace_state, session_state_in, request) → (results, session_state_out)`:

- **Workspace state is persistent and system-side** — registries, config, folios, artifacts,
  deliverables, claims, the SSOT. It is never round-tripped through the token.
- **Session state is ephemeral and actor-held** — the system persists **none** of it. The external
  actor stores the token in its own DB/sheet and hands it back on the next call. Session state is
  session state only — never workspace state.

**The token** (F4; wire contract §21):

- A **documented, actor-inspectable structure** — never an opaque blob the actor must trust.
- Carries an **integrity/version stamp**: `token_schema_version`, an `integrity_hash`, the bound
  `workspace`, and a `plan_hash`. A malformed, tampered, cross-version, or wrong-workspace token
  is **detected and rejected** (`invalid-token`), never misread (§3.1). An out-of-date but
  well-formed token is not a rejection case: re-use is idempotent (§21.8), and a plan that
  drifted since the token was minted surfaces as `plan-stale` (§21.6, §22.6) — there is no
  separate `stale-token` code.
- Carries the run's **inputs** (selection, overrides, pins), the **cursor**, the **produced ids**,
  and the target **folio-id reference** — ids only, never document contents.
- **Lost-token-survivable:** every durable output is id-addressable, so a lost token loses nothing
  durable; the actor re-addresses everything via discovery and fetch (§21.3, §21.5).

**The system-mutation boundary** (F6). The system persists workspace changes **only as the direct
result of an explicit actor action** — save an artifact the actor requested, append membership to
a folio the actor targeted, `add-to-folio`, advance an SSOT row from run results. It **never**:
(a) auto-adds to a folio the actor didn't target; (b) auto-creates purpose folios absent a
folio-type/selection the actor invoked; (c) overrides a user-configured setting on its own
initiative (§3.1). Folios never auto-close (§9.3).

## §21 The external-actor API

### §21.1 Governing principle & verb map

**The token is a cursor, not a capability gate** (API1). Compose/generation is the only
session-bound capability — composing requires the resolved plan the session carries. **Everything
post-compose is id-addressed and token-optional**: render, folio operations, retrieval, and
discovery each exist as a standalone verb AND are mirrored as `continue-session` actions. This is
what lets disconnected workflow 2 render or fetch what workflow 1 produced, token-free, by id.

| Category | Verb | Token | Writes |
|---|---|---|---|
| Read/Discovery | `list <type> [filters]` · `get <type> <id>` | optional | none |
| Generation/Session | `begin-session` | mints | plan resolve; optional first batch |
| | `continue-session` | consumes + returns | durable outputs per action |
| Folio | `create-folio` | optional | an empty folio; returns its id |
| | `add-to-folio` | optional | member append/update (params §21.2; semantics §9.2) |
| Output/Retrieval | `emit-manifest` | optional | persists the manifest (§21.5); none to the SSOT |
| | `emit-outline` | optional | a `Format=outline` artifact (DR-3); idempotent by `artifact-id` |
| | `fetch-by-id` | optional | none |
| | `render` | optional | IR-fitted/AST/bytes; returns deliverable-ids |

- **Both `create-folio` and `begin-session(target_folio = id | auto | none)` exist** (A1a):
  `create-folio` serves the disconnected create-empty-first pattern; `auto` is the one-shot inline
  convenience; `none` produces orphan one-offs. Neither subsumes the other.
- **`render` is both a standalone verb and an action** (A1b): render is deterministic given an
  id + render coordinate, so it is fundamentally id-addressed and token-free for automation, while
  the in-session action keeps interactive ergonomics.
- **`emit-outline` is a producer verb, standalone-only** (DR-3 horn (a) / B1): a hand-authored
  outline + a target coordinate → a byte-faithful `Format=outline` artifact, minted by the
  coordinate cascade + the outline's OWN normalized bytes (the §7.2 R4 own-body digest) and wired
  through `build_outline_ir` (§15). It is reachable via programmatic `invoke()`, idempotent by
  `artifact-id`, and deliberately **NOT CLI-wired** (the `main_cli` door stays render + fetch only,
  §21.9) and **NOT a `continue-session` action** — the emitted artifact renders and fetches through
  the existing token-optional verbs.

Every call carries `user` + `workspace` (the `user` isolation prefix is MANDATORY, never defaulted
— a missing/None `user` fails loud at the door rather than building a `users/None/…` path, §23);
**isolation is enforced by the API, not by trust**: every id must resolve inside that workspace or
the item is refused (`isolation-violation`). One invocation is synchronous:
`invoke(verb, workspace, user, params, [token], [pins]) → {envelope, results, [token']}`.

### §21.2 The closed action vocabulary

`continue-session` accepts exactly (API2): **`generate-next`** (`batch_size?`, `only?`) — the one
session-only action; composes the next missing items, idempotent by `artifact-id` ·
**`render`** (`item`, platform, language, output-type, presentation, `force_reconcile?`) · **`add-to-folio`**
(`folio_id`, `members?`/`artifact_ids?` — parameter contract below; default = produced ids) ·
**`emit-manifest`** (`folio_id`,
`member_targets`) · **`fetch`** (`id`, `return = path|bytes`) · **`status`** (progress + drift +
plan-hash check) · **`list`/`get`** (in-session discovery). Unknown actions return
`unknown-action`; the set is discoverable (`list actions`).

Two structural rules: **overrides are not an action** — they are fixed at `begin-session` for the
whole plan (§12.5; changing overrides = a new session, keeping identity lineage unambiguous), and
**render coordinates are render-time selections, not content overrides** — they bind at M2-render
below the immutable `artifact-id` and are chosen freely per render call.

**The `force_reconcile` parameter (FR1).** `render` — the standalone verb and the mirrored
action alike — accepts an optional boolean **`force_reconcile: true`**: an explicit request to
redo the fit from the user's CURRENT configured effective inputs instead of accepting a stale
cached fit. The force carries NO values (CA7: the reconcile pass is not an override point — want
different inputs? change config, or pass an L6 override at `begin-session`, then force). This
extends the verb's PARAMETERS only; the API2 closed action set is untouched. Semantics + the
deterministic behavior matrix: §21.8.

**The `add-to-folio` parameter contract (the member-record write path).** The verb — standalone
and in-session alike — takes `members: [{artifact_id, pin?, role?}]`; `artifact_ids: […]` remains
as sugar for pin-less, role-less member records. This is the API surface that writes the member
record's `pin` and `role` (§9.2, §9.6); it extends the verb's PARAMETERS only — the API2 closed
action set is untouched. Re-append semantics are explicit, never silent (§3.1): re-adding a
member with an identical record → the idempotent dedupe no-op (`ok`); re-adding with a differing
`pin` or `role` → an atomic update of that one marker file (write-temp + replacing rename, §13.3)
that preserves the original `added_ts`, surfaced as a typed **`member-updated`** (warn) result.
Concurrent differing updates of one member resolve last-writer-wins atomically — never a torn
record, and every writer receives `member-updated`, never silence. Member REMOVAL (and role
supersede on regeneration) is deliberately undefined in v1: it interacts with PC4's append-only
write-safety posture and is registered for the maintainer (§27.3).

### §21.3 Discovery

`list <type>` / `get <type> <id>` over a closed type list: `schemas` · `dimensions` ·
`dimension-entries` · `recipes` · `folios` · `folio-members` · `folio-types` · `artifacts` ·
`deliverables` · `sources` · `content-kinds` · `render-targets` · `plan-progress` (the §22.3
completeness sweep — read-only, token-optional); meta-types `verbs` · `actions` ·
`types` · `codes` (self-describing — callers never hardcode a vocabulary that could drift).

Filters use the §13.2 `Pred` grammar (wire rendering; `field op value` string form for
interactive use), AND-combined. Reserved filters every type honors: `provenance =
framework|instance`; lineage filters on `artifacts` — `generating_run = <id>` ·
`source_commit = <sha>` (matches an artifact whose pinned commit-map contains that commit for any
instance, §7.2) · `created .. <range>` — the "what did run X produce" query (§9.4).

**Computed currency fields (FR3, FR7.4).** Fitted/deliverable detail and listing shapes carry
`fit_revision` (`baseline` | hex12) · `fit_current` (bool) · `serialize_revision` (`baseline` |
hex12) · `serialize_current` (bool) · `minted_ts` — currency is **computed at read time** (the
fit-binding digest vs the digest of current effective reconcile inputs, §16; the render-binding
digest vs current pinned serialize inputs, §17) and **never stored**: currency is non-monotonic —
a config or tool-pin revert un-stales old outputs — so any stored marker would be a mutable write
target and a lie window (§24). All five are `list deliverables` filters; the platform-tightened
blast-radius remedy is one query + one loop: `list deliverables {platform, fit_current: false}` →
for each, `render(…, force_reconcile: true)` (§21.8). The two level flags are deliberately NOT
folded into one `current`: they demand different remedies (stale fit → explicit force, consent +
LLM spend; stale serialize → just render, free + auto), and the conjunction is trivially
client-computable (A4-4 expose-facts philosophy). No new discovery type is added — the fitted
layer is fully visible through deliverables + `get artifact` (every fit has ≥1 deliverable since
mints go through `render`).

Representative detail shapes: `get artifact` → binding (the id preimage) + `metadata` bag +
grounding-ledger summary + `generating_run` + deliverable-ids + part-ids. `get deliverable` →
coordinates (incl. any revision qualifiers), path, render-binding/pins (§17), the computed
currency fields above, part-ids, `side`. `get folio` → id, purpose,
`folio_type`, provenance, and the member set with **full member records + sortable facts per
member** (§21.5).

### §21.4 Run-layer attribute overrides

At `begin-session`, `overrides` binds values for **select declared attributes — never entire
entries**: keys are `<dimension>.<attribute>`; values are plain (replace) or carry the §13.2
operator (`union` on sets). They ride L6 → M2 bind (§12.5), are ephemeral, and are captured in
identity (§7.2).

**The hard M1 guard** (API5): an override may only bind a value to a **declared schema attribute**
of an **already-selected** entry. It can never add an attribute, pick or replace which entry is
used (that is `selection`, an M1 input), or touch schema — each refused as `invalid-override`.
`union` on an ordered list or set-of-maps is likewise refused (§11.1). The M1/M2 boundary is a
machine-checked wall.

### §21.5 Retrieval & the manifest

**`fetch-by-id(id, return = path | bytes)` — default `path`** (API6): a workspace path/link is
stable and lets the external publisher stream bytes itself; `bytes` is opt-in for small payloads
(e.g. the AST JSON). Works on any id type; the response names the id and pins, self-describing.

**`emit-manifest` is a point-in-time work order** (F7, closing Q9): a snapshot pinned to member
`artifact-id`s + commits, handed to the external actor. **The folio stays open and mutable; the
SSOT is updated from run results, never from the manifest; the manifest is never written into the
SSOT and is not a slice of it** — it is a generated, deterministically regenerable derived output
(same membership + same targets ⇒ same work order). This supersedes the archived
"manifest = a slice of the SSOT" definition (§4). **Where an emitted manifest lives:** the work
order is returned in-band in the invocation `results` AND persisted under
`users/<user>/workspaces/<workspace>/output/manifests/`, keyed by folio-id + emission timestamp (a machine
record, §13.3; workspace data, never public, §10). Deterministic regenerability makes retention
policy free — a pruned manifest is re-emittable at will; the SSOT is never touched (§24).

**Member→deliverable resolution — never from folio state** (DIRECTIVE item 5; the definition of
"folio state" is §9.2 and is not restated here). Each platform-agnostic artifact-member resolves
to concrete deliverable-ids via **emit-time `member_targets` and/or the member record's
per-member `pin`**:

```
"member_targets": { "<artifact-id>": [ {platform, language, output-type, presentation}, … ], … }
```

A member with no emit-time target and no pin is reported **`needs-input`** — never silently
guessed (§3.1).

**Resolution semantics — two levels, no minting at emit** (FR3, FR7.4). Emit-time
`member_targets` are coordinates and resolve through the SAME resolution rules as `render`
(§21.8) — but `emit-manifest` is a snapshot, never a mint verb: at the **fit level**, a
current-matching fit's deliverable resolves if one exists, else the latest-minted fit's, with the
`render-input-mismatch` warn riding that manifest row (the caller can force and re-emit; the
manifest is deterministically regenerable); at the **serialize level**, when the current-matching
deliverable-id is resolvable but not yet materialized, the row surfaces it as render-needed — the
caller renders (which auto-mints, §17) and re-emits. **The per-member `pin` is id-form and
FROZEN** (§9.2): the row references exactly those bytes — including any revision qualifiers —
annotated with the computed currency fields when non-current (§21.3), and is never re-resolved by
the system (Q3: the pin is the user's configured choice; the system surfaces staleness, never
bends the pin).

**Exposed sortable facts** (A4-4 condition i, normative here as at §9.2): the manifest rows and
the `folio-members` discovery surface expose, per member, `added_ts`, the resolved id
coordinates, lineage (`generating_run`, `source_commit`, created), the `pin`, and the `role` — so
the consumer computes any ordering it wants client-side. The manifest carries **no folio-level
ordering or schedule columns** (the folio has none, §9.1); intra-work part `sequence` rides the
part structure inside the layer-3 payload (§17).

For each resolved `side: external` deliverable, the manifest row references its **layer-3 contract
payload** (§17 RI14). For `side: internal`, the row points at the persisted bytes (path) + pins.
Publishing remains external, always (§2.2).

### §21.6 Batching

**Batch + cursor is the sequential consumption mode** (API7): `generate-next` composes
`batch_size` items per call (default small; `all` = whole-plan one-shot for small plans);
`begin-session` defaults to **plan-only** (`generate = none`), so a cheap planning workflow just
stores the token; every returned token is a **resumable checkpoint**. The plan is **re-resolved
each call from the token's inputs** (a pure, deterministic, LLM-free function), not stored in the
token; `plan_hash` guards it — a mid-session workspace edit that changes the plan surfaces a
**`plan-stale`** warning (the one ratified name for the one condition: a plan-hash mismatch on
re-resolve, §22.6), never a silent skip or repeat (the cursor keys on item coordinates, not
indexes). Batching is orthogonal to parallelism (§22.4) and does not foreclose it.

### §21.7 The typed result contract

One `ResultItem` shape for every verb (API8):

```
ResultItem = { item, status: ok|warn|block|needs-input, ids{...}, output{path?|bytes?},
               code?, category?, context{dimension?,attribute?,limit?,id?,clause?},
               remediation{hint, action} }
```

- The envelope's `ok` reflects only whole-invocation validity (unknown verb, isolation breach,
  malformed token). **A per-item `block` never fails the batch** (SM1): the blocked item carries
  its code; every other item proceeds; the caller remediates and re-runs idempotently.
- **Codes are stable, machine-readable, and consolidated from the rulings** — generation tier:
  `hard-limit-exceeded` (block, §16) · `advisory-constraint-overridden` (warn, §12.7) ·
  `nonsensical-pairing` (warn, §8) · `drift-block` (block, §11.5) · `out-of-window` (block,
  §11.6) · `empty-pool` (block, §6.4) · `low-confidence-grounding` (warn, §6.5) ·
  `capability-infeasible` (warn/block, §17) · `render-input-mismatch` (warn — **reconcile-scoped
  only**; extended with machine remediation `force-re-reconcile` + `current_inputs_digest` in
  context, §21.8) · **`re-reconciled`** (ok — a forced render minted a revision fit; `ids{}`
  carries the new fitted-id + deliverable-id(s), §21.8) · **`re-serialized`** (ok — an
  unqualified render auto-minted a serialize revision, the exact sibling of `re-reconciled`,
  §17/§21.8) · `member-updated` (warn, §21.2) · `ambiguous-migration-decisions` (needs-input,
  §11.6) · **`grounding-uncovered`** (block, §6.5/§19) · **`outline-config-drift`** (block/warn, DR-9 — a driven
  outline's resolved config differs from the config it was emitted under; a hard PRE-SPEND block by
  default, or a recorded warn under `--allow-drift`) · **`outline-config-unverified`** (warn, DR-9 — a
  driven outline carries no continuation handle, or one that cannot be resolved to compare; proceeds).
  `already-materialized` (§22.6) is REUSED, not new, for a force resolving to an existing
  matching fit (idempotent re-issue or force-after-revert; context names the matched fit) and for
  serialize-resolution hits; there is deliberately NO `superseded-fit`/`non-current-fit` code —
  currency is a computed FIELD on read surfaces (§21.3), never a ResultItem code, so fetch stays
  dumb and the code set stays small (FR4); and there is NO serialize-level mismatch warn — an
  unqualified render never returns serialize-stale bytes (FR7.3, §21.8). Contract tier: `unknown-verb`/`unknown-action` · `invalid-override` ·
  `isolation-violation` · `invalid-token` (there is no `stale-token`; §20) · `not-found` ·
  `needs-input: unresolved-member` (§21.5). Parallel-path codes extend the same taxonomy (§22.6).
- **`grounding-uncovered`** (generation tier, DR-6) is the opt-in item-level abstain: under
  `grounding_posture == "block"` ONLY, the driver abstains an item whose PERSISTED Review-1 record
  shows a `grounding` concern (statuses `("block",)`, remediation `None`; siblings continue). It is
  FAIL-OPEN — an absent / corrupt / partial record, or a non-`concern` grounding status, SHIPS
  (deterministically identical on re-drive); default `grounding_posture = "warn"` is
  behavior-identical to before. `review.py` is unchanged — the abstain lives in the driver, the
  sole seam where an advisory concern can gate a ship.
- Every non-ok result carries a **machine `remediation.action`** token (e.g. `relax-clause`,
  `run-migrate`, `retry-after`) so callers divert or degrade deterministically — never by parsing
  the human `hint`. The full set is discoverable via `list codes`.
- `needs-input` marks a run paused on a human decision the system will never guess (§3.1); v1
  producers: the migration worklist (§11.6, resolved out-of-band) and an unresolved manifest
  member (§21.5).
- **DR-1 amendment — the async transport MAY add sanctioned wire shapes (BUILT 2026-07-24).** The
  original DR-1 design intent had the HTTP shim return "the same JSON envelope the CLI emits." That
  holds for every **Tier-A** (synchronous) verb and for a **terminal poll** — both carry the exact
  `invoke()` envelope above. But a **paid Tier-B** verb (`generate-next`, `render`) answers a submit
  with a **202-Accepted acknowledgement** — a deliberately DIFFERENT wire shape, `{status:
  "accepted", job:{key, target_ids}, poll:{…}, [callback]}`, NOT a `ResultItem` envelope — and a
  poll maps a job's resolved state onto an HTTP status (200 done · 202 still-running · 429
  backpressure · 504 re-drivable-timeout · 4xx fatal). These are **sanctioned ADDITIVE wire shapes,
  not a violation** of the one-`ResultItem`-shape-per-verb rule: the 202 ack is an async submit
  receipt (no verb result exists yet), and the terminal delivery — poll body or webhook-woken fetch
  — is still the canonical envelope. Content identity is untouched (jobs are §22.7-class lossy
  bookkeeping, no `artifact-id` preimage). See `docs/known-issues.md` **DR-1** and
  `pipeline/api/http_shim.py`.

### §21.8 Reproducibility & idempotency

Every run pins (API9): the **global `schema_version`** (§11.2; a pinned value now outside the
migration window blocks with `out-of-window` on resume — never a silent misread), the
**source commit-map** (`{source-instance-id → commit}` over the resolved source-subset, §7.2 —
fixed at `begin-session`, so a later resume reproduces identical artifact-ids even if a source
advanced), and the **render tool bundle** (§17 pin set). **Pins may be supplied, not only
captured:** `begin-session` accepts optional explicit pins (the `[pins]` slot of the invocation,
§21.1) — an actor regenerating or extending earlier work passes that run's commit-map (and its
`schema_version`, migration window permitting, §11.6) to reproduce its grounding; with no
explicit pins, the default is the current state of each source instance. This is what makes
cross-session typed-folio coherence reproducible (§9.6).

Idempotency by construction: `generate-next` is idempotent on `artifact-id` (existing ids are
skipped; correctness comes from id existence, not the cursor); `render` on `deliverable-id` (existing coordinates reuse the persisted AST —
no LLM; which persisted fit/deliverable a call resolves to is governed by the resolution rules
below); `add-to-folio` is a dedup set-append
(update semantics §21.2); `emit-manifest` is deterministically regenerable. **Mint verbs**
(`create-folio`, `begin-session`) are not naturally idempotent — the optional
**`idempotency_key`** makes a retried call return the same folio/session instead of duplicating
(n8n retry safety).

**Cached-hit validation & the resolution rules — never a silent reuse (FR1–FR3, FR7).** Ids
carry coordinates only (§7.1), but reconcile and serialize also consume NON-coordinate inputs,
recorded at the level that consumes them: the reconcile-inputs preimage in the fitted-level
**fit-binding** (§16), the serialize-inputs preimage in the per-deliverable **render-binding**
(§17).

**The fit-resolution rule (FR2).** Which fit does an unqualified render use?

```
resolve_fit(artifact, platform, language):
  d    := hex12( sha256( canonical(current effective reconcile inputs) ) )   # config read
  fits := fit-bindings under prefix artifact.platform.language               # output-store read
  1. some fit.digest == d      → use it (ok — a true cache hit, baseline or revision alike)
  2. fits nonempty, none match → use the LATEST-MINTED fit (fit-binding minted_ts; deterministic
        lexicographic-id tiebreak) + `render-input-mismatch` (warn) — context names the differing
        inputs and the stale fit returned, plus `current_inputs_digest: d`;
        `remediation.action: force-re-reconcile`
  3. no fit                    → miss → normal first mint (the unqualified baseline)
```

Rule 1 makes config revert **self-healing**: revert the platform limit and the baseline matches
again — plain renders hit it, no warn, no force. Rule 2 keeps Q3's cached-hit-with-warn default —
the cached output is returned unchanged and the mismatch is never silent (§3.1); latest-minted
respects the user's most recent explicit fit intent and is equally deterministic. The unqualified
fitted-id names the FIRST fit ever minted for the triple and is never rebound — zero id churn on
the never-forced path. The machine remediation lets a caller re-issue deterministically and
predict the resulting fitted-id before the call (API8).

**`force_reconcile: true` — the explicit remedy (FR1).** The force carries NO values: the redo
uses the user's CONFIGURED current effective inputs (workspace config for token-free calls; + the
session's L5/L6 for in-session calls, CA7 collect-once). Deterministic, retry-safe behavior
matrix:

| State at call time | Result |
|---|---|
| No fit exists for the triple | Ordinary first mint → the **unqualified baseline** fitted-id (force is a no-op qualifier on a miss) |
| A fit exists whose recorded inputs match current effective inputs (baseline or revision) | **No mint** — return it, `ok` / `already-materialized` (idempotent re-issue; n8n-retry-safe) |
| Fits exist, none matches | Mint the **revision fit** `…_<hex12>` (§7.4) + the requested deliverable(s), `ok` / **`re-reconciled`** |

Same forced inputs → same digest → same id → S0 no-ops: idempotent **by construction**, and PC3
claim disjointness follows — two forcers compute the same claim key → exactly one LLM run;
different-input forces yield disjoint ids, both legitimate (§22.3). A forced render mints the fit
plus ONLY the requested deliverable(s); the revision's other output-types/presentations render on
demand from its persisted AST — the RI11 economy preserved at the new revision (§18). The system
never auto-re-reconciles and never sweeps (Q3); the caller-composable blast-radius remedy is
`list deliverables {platform, fit_current: false}` + a force loop (§21.3). Superseded fits and
deliverables are RETAINED indefinitely in v1, id-addressed — `fetch-by-id` on any old id returns
unchanged bytes forever, with zero currency evaluation (the dumb hot path; retention/GC policy
registered, §27.3). Revision ids do not encode order — order lives in `minted_ts` (the A4-4
expose-facts philosophy); a same-inputs re-roll is deliberately inexpressible under digest
identity (§26, §27.3).

**The serialize-resolution rule (FR7.3)** — mirrors the fit rule with the stale branch replaced
by AUTO-MINT (free + deterministic ⇒ no consent needed; the asymmetry principle, §17):

```
resolve_deliverable(fitted-id, output-type, presentation):
  s    := hex12( sha256( canonical(current serialize inputs) ) )            # pinned-config read
  dels := render-bindings under prefix fitted-id.output-type.presentation   # output-store read
  1. some binding.digest == s  → that deliverable (ok — a true cache hit; a tool-pin or asset
        revert self-heals exactly as fit rule 1)
  2. dels nonempty, none match → AUTO-MINT the serialize revision `…_<hex12>` (claim on the id;
        S0 preimage check; no-replace commit) → `ok` / `re-serialized`
  3. none exist                → first mint → the unqualified baseline deliverable-id
```

There is no latest-minted stale branch at this level — returning current-correct bytes costs
nothing, so the question the fit rule had to arbitrate dissolves; an unqualified render never
returns serialize-stale bytes, so **`render-input-mismatch` is reconcile-scoped only** and no
serialize force flag exists (a deterministic pass has no re-roll concept: matching inputs mean
the byte-identical output already exists; differing inputs already auto-mint). Minting happens in
`render` only — never in `fetch-by-id`, never at `emit-manifest` (§21.5).

**INV-CORRECTNESS placement (PC12):** both resolution rules are plan/coordinate resolution — the
same class of step as the cascade resolve — reading config + output store, **never the SSOT**;
`is_done(id)`/`claim(id)` operate on the already-resolved id against output store + claim
registry only, exactly as §22.7 scopes them (§22.3).

**Documented behavior — the M3 selection expression is not an identity input (Q17).** The
grounding identity inputs are the source-subset and the pinned commit-map only (§7.2). Two runs
differing only in selection clauses (`require`/`span`/`prefer`/`on_conflict`) resolve the same
`artifact-id`s, so tightening a clause and re-running does NOT re-materialize already-existing
items — idempotency-by-existence skips them (§22.3). Re-grounding under changed clauses requires
a content-input change or explicit regeneration; whether the effective M3-expression digest
should join the identity preimage is a registered maintainer question (§27.3), not decided here.

### §21.9 Transport & flags

- **F10 — STRENGTHENED, NOT REMOVED (was "never API keys").** The pipeline authenticates a
  headless Claude Code CLI invocation on the Claude **SUBSCRIPTION by default**, and the
  subscription path is now used **only for the single config-entitled user** (ToS), behind a
  fail-closed **wall**: the widened env-strip (`ANTHROPIC_API_KEY` PLUS `ANTHROPIC_AUTH_TOKEN` +
  the `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY` provider switches) AND a pipeline-controlled
  settings file proven to define no `apiKeyHelper` — refusing to spawn (loud, fail-closed) when the
  wall cannot be proven, INCLUDING an enterprise/managed `apiKeyHelper` `--setting-sources` cannot
  exclude. Alongside it, an **API-KEY transport** now runs, opt-in by **explicit per-scope key
  assignment** and bounded by a HARD **weekly dollar cap** + an install **umbrella** cap, with the
  key injected into the child env **only under a live spend reservation** (hold-gated disarm). So
  `ANTHROPIC_API_KEY` still never rides a subscription spawn, and an api-key spawn is money-safe by
  construction — F10 is tightened on both sides, not relaxed. The full mechanism (resolver,
  entitlement, keystore, the explicit-scope cascade, the weekly meter + umbrella, the shared
  chokepoint, the `$5`/`$50` defaults, identity-neutrality, and residual risks R1–R6) is **§21.10**;
  the operator guide is `docs/transport.md`.
- The pipeline CORE is not a long-running server: one synchronous invocation per verb (params +
  optional token in → results + token out), no persistent process carrying LLM/session state across
  calls. An OPTIONAL transport FRONT (the CLI door, or the DR-1 HTTP shim — `docs/known-issues.md`
  DR-1) MAY be a persistent process, provided it holds no LLM/session/correctness state — all
  cross-request correctness state lives on disk (the content-addressed output store + the
  claim/presence-lease registries), and the front dispatches only to stateless per-verb invocations.
- Subscription auth headless + per-call statelessness (no hidden conversation carry-over) are
  **verified and DELIVERED** by the transport-selection build (§21.10, gate G0 on the pinned CLI).
  The exact n8n→headless mechanism and the Graphify serve-MCP/output-path flags stay transport-
  agnostic contract-shape items; only those literal invocation details still wait on verification.
- The literal wire encodings are fixed by §13 (JSON payloads; the §13.2 operator wire forms).
- **`scripts/migrate.sh` is NOT on this API** (§11.6): the API surfaces migration-related codes
  and points remediation at the out-of-band maintenance tool.

### §21.10 Transport selection, the keystore & the weekly meter

The single home for the AS-BUILT transport-selection system (the operator guide is
`docs/transport.md`). Two transports run side by side, both enforced at ONE shared chokepoint so the
money-safety rules fire identically for the CLI door and the served HTTP doors.

**The two transports.** (1) **SUBSCRIPTION** — a headless subscription (OAuth) spawn, used ONLY for
the single config-entitled user (§21.9 F10, ToS), behind the widened env-strip + controlled-settings
**wall** that fails closed (including on an enterprise/managed `apiKeyHelper`). (2) **API-KEY** —
single- or multi-tenant, opt-in by **explicit per-scope key assignment**, metered by a HARD weekly
cap + an install umbrella, with the key injected only under a live spend reservation.

**Resolution order (the resolver is the ONLY mode-selector).** For a spend verb: an explicit
per-run **override** → else the **cascade** key → else **subscription IFF** the run's user is the
entitled one → else a LOUD refusal (no key + not entitled = nothing spent). The override vocabulary
is CLOSED — `subscription` | `api` | `key:<namespace>:<name>` — it names a *mode* or an *assigned
handle*, **never a user** (so a run can never re-point who is subscription-entitled).

**The keystore (two-layer, shared with sources).** Non-secret **handle assignments**
(`<namespace>:<name>`) live in gitignored `instance/ops/transport/config.yaml`; the **secret value**
lives in a 0600-per-handle store under `$OPTIQUITY_SECRETS_DIR` (default `~/.optiquity/secrets/`)
behind a pluggable `SecretResolver`. The store **fails closed** on a relative or repo-relative
secrets dir, and refuses any secret whose file perms are looser than 0600. The secret value is
resolved only at use time and NEVER placed in argv, logs, the ledger, or telemetry (§3.3, I5).
There is ONE keystore with two consumers — transport and the sources paid keys (FRED etc.).

**Assignments + the explicit-scope cascade.** `transport assign-key --scope <global | user:<u> |
zone:<u>/<z> | workspace:<u>/<z>/<w>> --handle <ns:name> --weekly-cap $C` — the weekly cap is
HARD-REQUIRED (no silent default, no uncapped key). The cascade is **most-specific-wins:
workspace → zone → user → global**; same-named zones under different users are DISTINCT scopes. The
scope-id is parsed from `--scope`, **never derived from a `users/…` path** (M3, orthogonal to the
§23 addressing/value cascade). `transport list-keys` / `clear-key` / `show` administer it.

**Entitlement.** `transport set-subscription-user <u>` names exactly ONE entitled user (single-
valued, swappable, config-only) — never a run parameter (I2/I3).

**The weekly meter + umbrella.** An enforcing per-bucket weekly cap plus one install **umbrella**
(default **$50/week** when unset, via `transport set-umbrella-cap`). A bucket is `(scope-level,
scope-id, handle, week-key)`; the week-key is a calendar week (**Monday 00:00 UTC**, install-
anchored, injectable clock). A **hash-chained, edit-EVIDENT** append-only settled ledger (detected
tampering refuses admission — but a local `rm` reopens the cap, R2: edit-evident, not reset-proof)
plus TTL holds, all under gitignored `instance/ops/spend/`. Admission is **admit-before-spend**:
under an **inter-process lock** it reads (settled ledger + all live holds), reserves the worst-case
**ConstructionBudget** ceiling for the bucket AND the umbrella in ONE critical section, and REFUSES
pre-spend if either would be exceeded; the reservation is **settled to the real cost in a `finally`**
and self-expires at full ceiling on a crash (never a leaked reservation).

**The chokepoint (covers CLI + served HTTP doors).** Enforcement lives at the shared tiers both the
CLI and the detached `jobrunner → invoke()` re-entry traverse — NOT the CLI handler. At the
**run-admission tier** (`invoke()`/the session handler): resolve → admit → drive → settle. At the
**per-call tier** (`build_child_env`, the lowest un-bypassable node): the api key injects and the
widened strip disarms **only** under a live hold whose plan-embedded expiry passes an injected-clock
check — absent/expired → fail-closed, no spawn; every api-key call is forced under
`--max-budget-usd = min(caller, $5)` (the **$5 default per-call cap**; subscription stays
`per_call_cap=None`, flat-rate, never truncated). The **multi-zone "name a zone or refuse"** guard
(S4) now fires uniformly at this chokepoint, closing the zone restructure's CLI-only gap.

**Disclosure.** A pre-spend line (mode + charged bucket + `≤ $C` worst-case ceiling + `cap −
week-to-date` headroom for bucket AND umbrella) prints to stderr on a live run before the first
spawn (off the stdout JSON envelope); a CLI dry-run/preview prints the same line to stdout and
spends nothing.

**Identity-neutrality.** Transport, mode, handle, and zone enter **no id preimage** (§7.2) — they
are recorded as provenance only, so a run's ids are identical whether it spends on subscription or
an api key, and across zones.

**Residual risks v1 does NOT solve (honest).** **R1** `--user` is addressing, not authentication —
the guarantee is a bounded blast radius via caps, not authenticated identity. **R2** a local `rm` of
`instance/ops/spend/` reopens the cap (operator-bounds-own-bill; edit-evident, not reset-proof).
**R3** single-writer-host — shared-host clock skew / non-locking NFS is out of scope. **R4** a
hand-forged in-process `TransportPlan` is outside the trust boundary. **R5** the injected
`ANTHROPIC_API_KEY` is visible via `/proc` to the same UID (an `apiKeyHelper`-resolver backend is
deferred hardening). **R6** an assigned OAuth token on a metered plan would under-count (v1 states
the flat-rate assumption). The **managed/enterprise-`apiKeyHelper`** host is an operator note, not a
solved case: every subscription spawn there is refused (correct, loud, fail-closed) — run on an api
key instead (`docs/transport.md`).

## §22 Parallelism & write-safety

The system computes and returns the exact work batches a caller can safely parallelize, and makes
writes safe: **no repeated work, no missing work, no write collisions** — the caller receives safe
batches; it never reasons about safety itself.

### §22.1 Disjointness by identity

Disjointness is already a property of the identity scheme (§7); the system exposes it rather than
manufacturing it. Distinct artifact/fitted/deliverable ids ⇒ distinct output files ⇒
collision-free by construction; every shared *input* (IR-canonical, AST) is immutable. The **only
two genuinely shared mutable write targets in the whole system are folio membership and the SSOT
row** — everything else needs zero coordination. The dependency graph is an intrinsic three-level
forest (artifact → fitted → deliverable): serial within an item, independent across items; **v1
has no cross-item edges** (deep-folio dependencies are deferred, §26).

### §22.2 The plan

The parallel plan is a **wave-structured DAG with shard tags** (PC1): an ordered list of waves
(wave = dependency depth); each wave a set of mutually independent id-keyed units; each unit also
carries `prereqs` (ids that must exist first) and a `shard` tag (its root artifact-id); the plan
carries `suggested_width` (§22.5). One structure, three readings: run wave-by-wave (simple);
pipeline off `prereqs` (sophisticated); group by `shard` (row-per-item n8n chains). **v1 exposes
exactly two waves:** wave 0 = compose, keyed by `artifact-id`, driven by
`continue-session{generate-next, only}`; wave 1 = render, keyed by `deliverable-id`, driven by the
token-free `render` verb (reconcile cached by `fitted-id` + serialize). Obtained via
`begin-session(want_parallel_plan = true)` — no new verb. The `prereqs`/`shard` fields absorb
future cross-item edges with zero structural change.

**The plan is a deterministic, exactly-once cover** (PC2): keyed by settled ids, disjoint by
construction; a missed item is detectable by re-resolve + diff (expected ids ∖ materialized ids),
not by a tracker.

### §22.3 Claims, writes & the sweep

**No repeated work — two layers** (PC3):

1. **Idempotency floor (always on):** re-running any unit whose output exists is a no-op; every
   stage commits via **write-temp-then-atomic-NO-REPLACE-commit** — a create-exclusive primitive
   (`link`+`unlink`, or a `RENAME_NOREPLACE`-class rename; never a plain replacing rename, which
   silently overwrites an existing target) — so an output is wholly absent or wholly present,
   never partial, **and never overwritten once present**: a committer that finds the target
   already present discards its temp and reports `already-materialized`. This is what makes
   output existence the true idempotency authority (§22.7).
2. **Lease-based claim registry:** before expensive (LLM) work on an id, atomically claim it —
   create-if-absent of a claim file whose **filename is the id** (§13.3), content
   `{holder, lease_expiry}`. Outcomes ride the result contract: free → do + commit +
   holder-checked release (`ok`); already materialized → skip (`already-materialized`); live
   lease → skip (`claim-held`, caller moves on or polls by id); expired lease → steal + re-drive
   (`lease-expired-redrive`). The steal is safe against a holder that is merely SLOW, not dead —
   the classic lease hazard — because of two qualified primitives: **(a) commit is no-replace**,
   so if the stolen-from worker reaches its own commit after the stealer has committed, its late
   commit LOSES (`already-materialized`; its temp is discarded) — it can never overwrite the
   stealer's output; **(b) release is holder-checked** — a worker releases the claim only if the
   claim file's `holder` is itself; on mismatch the release is a no-op (`claim-held`), so a
   stolen-from worker can never unlock the stealer's live critical section for a third worker.
   The steal itself is read-check-replace, not atomic: a double steal is a duplicate-LLM **cost**
   leak, never a correctness leak — the no-replace commit admits exactly one winner per id.
   **`fitted-id` is also a claim key**, so many
   render units sharing one reconcile run it exactly once — even a naive fan-out-everything caller
   never repeats an LLM pass.

**Revision-qualified ids ride the same spine** (FR2/FR7): a qualified fitted- or deliverable-id
is an ordinary claim key and an ordinary no-replace mint — S0's preimage check reads the
fit-binding / render-binding (§16, §17), so a hex12 collision fails loudly; the resolution of
WHICH id a plain render targets is plan-side coordinate resolution (§21.8), never inside
`is_done`/`claim`; a serialize auto-mint rides the ordinary S0–S6 spine like any unit.

The claim table is a small persisted **workspace-side** store (§23) — self-expiring, never in the
token; session-statelessness is about session state, and concurrent-write coordination is
precisely this designed mechanism.

**No write collisions** (PC4): id-keyed writes are disjoint; **folio membership is a lock-free
marker set, append-only in membership** (one marker per (folio, artifact-id); members are never
removed in v1 — removal is registered at §27.3; identical re-append = idempotent dedupe; an
explicit differing re-append atomically updates that one marker, last-writer-wins, surfaced
`member-updated` — §21.2, §13.3); **SSOT = one row per item with monotonic, advance-only status** (a stale worker can never
regress a row). Row atomicity holds on Sheets/Airtable; a **local-CSV backend serializes writes
through a single writer** (a registered backend build item, §27.4) — acceptable because the SSOT
is bookkeeping-only, never correctness (§22.7).

**No missing work** (PC5): the **completeness sweep** re-resolves the plan and diffs against
materialized ids; exposed via `status`/`get plan-progress` (read-only, token-optional — a
disconnected sweeper works); it doubles as the **wave barrier** (a wave is done when
materialized ∪ blocked = expected). Blocked ≠ missing (§6.4 items are visible, not lost).

### §22.4 Handoff, failure & retry

Serial→parallel handoff is minimal surface (PC6): `begin-session(want_parallel_plan = true)` + the
`status` extension. Sequence: serial plan gate → fan out wave 0 → barrier via status → fan out
wave 1 (token-free `render`) → optional `emit-manifest` join. **Under parallel mode the token is
an immutable plan-context**: progress is read from materialized ids, not the cursor, so parallel
calls never race on `session_token_out` and the pure-function contract stays honest. Sequential
batching (§21.6) is untouched.

Failure/retry (PC7): a partial batch is per-item (§21.7 — siblings unaffected); worker death
leaves no partial output (atomic commit) and its lease expires → safe re-drive; whole-batch
re-drive terminates and is idempotent; the lease TTL is an ops policy knob (§27.4).

### §22.5 Width, backpressure & telemetry

- The true concurrency ceiling is the **subscription account**, not the data (wave units are
  independent). **`max_parallel_sessions` is INSTANCE/account-scoped** — per-workspace caps do not
  compose across workspaces sharing one account (an optional per-workspace sub-limit may sit
  beneath it, never replace it). The plan returns
  `suggested_width = min(wave-unit-count, instance cap)` (PC8).
- A session hitting a rate/concurrency limit surfaces the unit as **typed backpressure** —
  `rate-limit-backpressure` with `remediation.action = retry-after(+retry_after) | reduce-width` —
  never a crash (PC8).
- **Capture + advisory tuning** (PC11): two small instance-scoped persisted structures — a
  **self-healing presence-lease registry** (live-lease count = account-wide in-flight concurrency;
  a dead worker's lease self-expires) and an **append-only JSONL telemetry log** (off the critical
  path). Captured: `observed_inflight` at backpressure onset, interval rollups (started/completed,
  peak, throughput, claim-health counters). **Zero content: no artifact ids, no client/workspace
  identifiers by default, no secrets** — sessions across workspaces register in the same registry
  seeing only a count (rule-2-clean: operational metrics are not client data). Mechanism =
  `provenance: framework`; the data = `provenance: instance`, gitignored (§10, §23).
- At `begin-session` the system computes an advisory **`recommended_width`** from the recent
  telemetry window and returns it alongside `suggested_width`, warning when it is below the
  configured cap — **never auto-applied**: the user's cap stays authoritative (§3.1). An AIMD
  auto-tuner is deliberately not built; the telemetry dataset keeps it cheaply addable (§26).
  Capture is default-on and disable-able.

### §22.6 Parallel-path codes

The §21.7 taxonomy extends with (PC9): `already-materialized` (ok) · `claim-held` (warn) ·
`lease-expired-redrive` (ok) · `plan-stale` (warn — plan-hash mismatch on re-resolve; re-fetch the
plan; the sweep reconciles; never a silent skip/dup) · `collision-averted` (warn) ·
`rate-limit-backpressure` (warn/block). Same ResultItem shape, same machine remediation, never
fail-the-batch, discoverable.

### §22.7 INV-CORRECTNESS — the SSOT-independence invariant

**The named, CI-enforced invariant (PC12):** execution correctness — idempotency (no repeated
work) and mutual exclusion (no two workers materialize one id) — is enforced **solely** by
(1) content-addressed **output existence** with atomic **no-replace** commit (§22.3 — a plain
rename REPLACES an existing target; the commit primitive must be create-exclusive or the
existence authority does not hold under a lease steal) and (2) the **claim/lease registry** with
holder-checked release — and **never by the SSOT**. The SSOT backend (CSV vs Sheets vs Airtable) and its write
serialization affect status bookkeeping only; correctness holds identically under a local-CSV,
single-writer SSOT, provided the filesystem supplies the §22.8 primitives.

- **Four write targets, roles fixed:** content-addressed outputs = idempotency authority
  (existence = done) · claim registry = lock authority · folio marker set = membership record
  (never a generation gate) · SSOT row = status bookkeeping only, never consulted by control flow.
  The sweep reads materialized ids, never SSOT rows.
- **Crash-safety by ordering:** S0 idempotency pre-check (output existence + the §7.4 preimage
  check — both read only the output store) → S1 acquire claim → S2 work → temp → **S3 atomic
  NO-REPLACE commit** (a commit finding the target present discards its temp →
  `already-materialized`) → S4 folio append → **S5 advance SSOT (last, side-effect-only)** →
  **S6 holder-checked claim release** (release only if `holder` = self; mismatch → no-op,
  `claim-held`). The critical section is S1–S3; every crash point is benign — e.g. a crash
  between S3 and S5 leaves the id materialized and the SSOT lagging; the re-drive is an
  `already-materialized` no-op that then advances the row. The SLOW-holder (lease-steal) case is
  benign precisely because of the two qualified primitives: after a steal, the original holder's
  late S3 loses to the no-replace commit and its S6 is a holder-mismatch no-op — it can neither
  overwrite the stealer's committed output nor release the stealer's live claim. **The SSOT is a lagging monotonic
  projection: it trails reality and never contradicts it**; any re-drive or sweep only advances
  it. A slow, failing, or offline SSOT writer only lags the human view — even a total SSOT outage
  leaves correctness intact.
- **Build guardrails (CI teeth):** (1) signature scoping — `is_done(id)`/`claim(id)` take only
  output-store + claim-registry handles, no SSOT handle in scope; (2) an import lint — correctness
  modules (materialize/claim/idempotency-check/sweep) must not import the SSOT module, or the
  build fails; (3) the SSOT interface is write-only w.r.t. control flow — monotonic `advance()` +
  human reports, no branchable predicate; (4) a conformance test simulating a crash at every
  S-point under a CSV-serialized SSOT with concurrent workers, including the slow-holder/steal
  interleaving (steal during S2; the original holder resumes through S3–S6).

**Domain separation (T3, reconciled).** The repo's durable rule — "the tracking spreadsheet is the
SSOT" — is unchanged and untouched: the SSOT remains the **sole authority for the status/progress
domain** (§24). Execution correctness ("is this id done? who holds the claim?") is a **different
domain**, answered from work-product existence + claims, outside that rule's scope. "SSOT for
status" (true) and "SSOT decides idempotency" (false) are different claims; this section is where
the distinction lives. The corresponding one-line clarification in `CLAUDE.md` rule 3 is a
**maintainer action** (Appendix B) — not an edit this document makes.

### §22.8 Preconditions

The whole of §22 (and §13.3's claim/marker/JSONL encodings) rests on **filesystem atomic
primitives on the REAL workspace store**: atomic create-if-absent, atomic **no-replace commit**
(create-exclusive rename/link — a commit against an existing target must FAIL, not replace;
§22.3), atomic replacing rename (folio-marker updates, §21.2), **compare-holder claim release**
(§22.3), and atomic single-line append. These are **verified before build** (gate G1, §27.2), especially on
synced/network filesystems (iCloud, network mounts) where rename atomicity may not hold; **if
unavailable, a DB commit substrate replaces the FS mechanics** — the design above is unchanged,
only the substrate swaps. Lease TTL and `max_parallel_sessions` ship as conservative ops defaults
(§27.4); the subscription's real concurrency/rate limits are validated against the §22.5
telemetry dataset (gate G2), not guessed.

---

# PART VI — OPERATIONS & EVOLUTION

## §23 Repo & workspace layout

The repo map under this design (structure only — the public framework never names instance data,
§10). Indicative layout; per-collection details are governed by their homing sections:

```
CLAUDE.md · README.md · quickstart.md · state.md (derived from the SSOT; §24)
docs/design.md                          # THIS DOCUMENT (the design SSOT)
docs/{mission,operating-model,bootstrap,claude-code-usage,ops-workflow}.md
docs/archive/                           # superseded docs + the imported decision record (Appendix B)
topics/ personas/ formats/ voices/ goals/
platforms/ languages/ output-types/ presentations/     # dimension registries (§5)
<each registry>/_schema.yaml            # co-located schemas (§11.1)
content-kinds/                          # §6.1
sources/                               # adapters + source-instance entries (§6.1)
render-targets/                         # writer + side + pins entries (§17)
recipes/ folio-types/                   # §8, §9.6
templates/workspace/                    # the shared workspace scaffold in public (framework; §23)
users/<user>/zones/<zone>/workspaces/<workspace>/   # instance-side only (gitignored in public)
  topics/ <dimension>/ …                #   client-scoped entries + extends: partials (§10)
  folios/<folio-id>/members/<artifact-id>   # marker-per-member records (§13.3)
  artifacts/ deliverables/              #   IR-canonical/fitted/AST/bytes + render-bindings (§18)
  claims/                               #   the claim/lease table (§22.3)
  jobs/                                 #   DR-1 async job/idempotency records — §22.7-class
                                        #     lossy bookkeeping, run-id keys, gitignored (§27.3)
  select/ output/                       #   selection inputs + outputs (output/manifests/, §21.5)
instance/profile.md                     # instance goals/audiences (gitignored in public)
instance/ops/                           # instance-scoped stores (§22.5): presence-lease registry,
                                        #   telemetry JSONL — mechanism framework, data instance
  ops/transport/config.yaml             #   transport key assignments + entitlement + umbrella cap (§21.10)
  ops/spend/                            #   weekly spend ledgers + holds, per bucket (§21.10)
scripts/                                # incl. migrate.sh (§11.6), guards (§10, §11.7)
.claude/{agents,skills}/                # framework-ops plane (product plane open, §27.4)
```

**The 5-level zoned store root.** A workspace store root is `users/<user>/zones/<zone>/workspaces/
<workspace>/`: a **zone** sits BETWEEN user and workspace and **groups a user's workspaces** (e.g.
`work` vs. `personal`). Both the **`users/<user>/`** and the **`zones/<zone>/`** levels are
isolation/addressing **prefixes, not new scope rungs** (§10): they change only *where* a workspace
lives, leaving the value cascade framework → instance-global → workspace (L1/L2/L3, §12) untouched —
there is no `user` rung and **no `zone` rung** in the cascade. `users/`, `zones/`, and `workspaces/`
are plural REST collection nouns, so the on-disk tree maps 1:1 to a future
`/users/{user}/zones/{zone}/workspaces/{workspace}` REST path; the shared scaffold at
`templates/workspace/` is the framework copy every new workspace is stamped from by `pipeline
workspace new <workspace> --user <user> [--zone <zone>]` (equivalently `cp -R templates/workspace
users/<user>/zones/<zone>/workspaces/<workspace>`). **Zone selection** rides the same rails as
`--user` at every door, defaults to `default` (a single-zone user never types it), and the RESOLVED
zone is ECHOED back (the result envelope's `zone` field + the friendly preview header). The
per-door zone-selection map and the same-name policy below are enumerated for operators in the
[Interfaces guide → Zones](guide/interfaces.md#zones-grouping-a-users-workspaces).

Both the workspace and the zone lifecycles are CRUD-complete on the friendly CLI —
`workspace new` / `list` / `delete` (with a `--zone` selector) and `zone new` / `list` / `delete`,
plus `user new`, all local Tier-A file ops that never spend (§21.9). `delete` is safe-by-default
(confirmation, plus a `--force` gate over any workspace holding generated output) and self-contained
(no global index to orphan); `zone delete` is the recursive two-tier form (it removes the zone AND
every workspace under it, stricter because recursive, and NEVER through a symlink). One **spend
guard** (S4, §21.9) rides the spend verbs only: a user who owns MORE THAN ONE zone must name one
explicitly on a spend verb (`preview`/`generate`/`outline drive`) — the door refuses-and-lists
rather than silently pick `default` and spend in the wrong zone; a single-zone user and every
(non-spending) Tier-A verb keep the friendly default, and an explicit `--zone` (even `default`) is
always honored.

**Same workspace name across zones is ALLOWED.** `users/dave/zones/work/workspaces/acme` and
`users/dave/zones/personal/workspaces/acme` are two DISTINCT, store-isolated workspaces. Workspace
ids are **store-scoped** — resolved within one `(user, zone, workspace)` store, never against a
global name index — so there is no collision to reject; the fully-qualifying key is the
`(user, zone, workspace)` triple. The zone is **identity-neutral**: it is in no id preimage (§7.2),
so relocating a workspace into a zone keeps every artifact/deliverable id (the migration is a pure
relocation). The restructure itself buys **STORE isolation**; per-zone **spend/key isolation**
(same-named zones drawing on distinct transport keys and weekly caps) is **now DELIVERED** by the
transport-selection build — assign a key + weekly cap per `zone:<u>/<z>` scope, and same-named zones
under different users key DISTINCT spend buckets (§21.10, `docs/transport.md`).

The **mechanism-public / data-instance split** (§10) governs every new store: the claim table,
presence-lease registry, telemetry log, the DR-1 `jobs/` record store, and the transport-selection
stores — `instance/ops/transport/` (key assignments + entitlement + umbrella cap) and
`instance/ops/spend/` (weekly spend ledgers + holds) — are framework *mechanisms* whose *data* lives
instance-side, gitignored in public (§21.10). The transport **credential cascade is explicit-scope**:
an assignment is keyed by a `(scope-level, scope-id)` parsed from `--scope`, **never derived from the
`users/…` store path** (M3), and it is **orthogonal to the value cascade** (§12) — it decides *which
key/cap a run draws on*, not which rung a configured value binds to. Registry directories are
mixed-provenance (§10); instance entries carry the `x-` prefix (§11.4).

## §24 Tracking & the SSOT

- **The tracking spreadsheet is the SSOT for the status/progress domain** — the sole authority for
  item status. `state.md` is always a derived convenience mirror; on disagreement the spreadsheet
  wins and `state.md` is refreshed to match, never the reverse.
- **What the SSOT tracks:** one row per fanout item — coordinates/ids, source commit, status
  (monotonic, advance-only, §22.3), output path. **What it never does:** gate correctness — no
  compose/render/claim/sweep decision ever reads it (§22.7). **What the manifest is not:** part of
  the SSOT — the manifest is a generated downstream work order, never written into the SSOT
  (§21.5).
- **Fit and serialize revisions: NEW ROWS ONLY** (FR4, FR7.6). A revision-fit or auto-minted
  serialize-revision deliverable is a new fanout item with a new id → one new row, advanced by
  its own render's S5 like any item. **Old rows are untouched:** currency is non-monotonic (a
  config or tool-pin revert un-stales an old output), so "superseded" can flip back — it can
  never be a monotonic-advance status nor an SSOT fact; currency lives as computed read-time
  fields (§21.3). One item's commit never writes another item's row (PC4); the SSOT gates none
  of it (§22.7). Telemetry: optionally one content-free interval-rollup counter,
  `forced_reconciles` (count only — no ids, no workspace identifiers; PC11c, §22.5).
- **The SSOT row/column schema & status lifecycle (this section's designated home —
  DELIVERED, build step 22).** One row per fanout item, keyed by the item's id, in **two
  row kinds** (PA-4; the two fanout levels, §8):
  - **Columns** (tabular, §13.3/§13.5): `row_kind` · `id` · `coordinates` · `source_commit`
    (source commit or commit-map digest) · `status` · `output_path` · `block_reason`. No
    stored timestamp/currency field — currency is computed at read time, never stored (§21.3).
  - **Two status lifecycles, one per kind** (a row carries ONLY its own kind's statuses; the
    status namespace is kind-scoped, so a wrong-kind advance is a typed rejection, never a
    silent cross-write, PC4):
    - **artifact rows** — `planned → composed → artifact-reviewed`.
    - **deliverable rows** — `planned → fitted → rendered → deliverable-reviewed → ready`.
  - **Advanced only by its own item's S5** (§22.3/§22.7): an artifact row by its compose-unit's
    S5, a deliverable row by its render-unit's S5, then each by its own review outcome (§19).
    One item's advance never writes another item's row (PC4).
  - **Monotonic-advance semantics** — `status` moves forward ONLY, by a status-rank compare
    within the row's kind: a higher rank advances (a forward write); an equal rank is an
    idempotent no-op; a lower rank (a stale/regressing write) is a typed rejection, logged, and
    NEVER raised into control flow (§22.7) — a stale worker can never regress a row.
  - **`blocked` is an annotation, not a status** (`block_reason`, §21.7 codes): recorded beside
    the status, it never regresses the ladder and is terminal until a re-drive's forward advance
    clears it. The wave-barrier's blocked set is the sweep's own (materialized ∪ blocked,
    §22.3/PC5), never read back from the SSOT (§22.7).
  - **Encoding & interface:** §13.5 fixes the encoding class (tabular); the local-CSV backend
    serializes writes through a single-writer file-lock funnel (§22.3/PC4b). The interface is
    write-only w.r.t. control flow — `advance()` + the block annotation + a derived `state.md`
    projection, and NO per-id read predicate the pipeline can branch on (§22.7 guardrail 3).
    This is the sole home of the schema; nothing else in the doc grows SSOT schema content.

## §25 MVP & build sequencing

**The MVP exercises all NINE dimensions — including Presentation** (Q19 as extended by A4-3). The
mandate's substance is that the dimensions interact, so a minimal-subset MVP proves nothing:
no staged or partial axis set is acceptable. Presentation's inclusion costs ~zero: the
framework-shipped `plain` floor entry (§5.3) ships in v1 regardless, and exercising it in the MVP
is exactly the same one-writer-call path as any styled entry (§18). Exempting it would recreate
the staged-axis pattern the mandate rejects.

The MVP therefore demonstrates, end to end: grounding with the full selection grammar (§6);
resolution over the full cascade including a run override (§12); compose → reconcile → serialize
across at least one internal and one external-side target (§14–§17); both review gates (§19); a
folio with a typed and an untyped member path, manifest emission with member targets (§9, §21.5);
the sequential and parallel consumption modes (§21.6, §22); and the SSOT projection (§24).

**Build gates precede build:** the docs-researcher gates G1–G6 and the registered build items are
enumerated once, at §27.2/§27.4 — the build phase starts only when the gates it depends on have
closed. D2 is closed at §7.4 and ratified (B4-1; revision-qualifier grammar per FR2/FR7.2); no build
item may invent an id encoding elsewhere.

## §26 Deferred-but-designed features

Each deferred feature, its ratified reservation, and its re-entry point — deferral is a decision
not to build yet, with the hook designed so the later add is purely additive:

| Feature | Reservation / re-entry |
|---|---|
| **Deep-folio correspondence** (a member generated *from* another) | ONLY the identity-provenance slot (upstream-artifact provenance in the id scheme) + a manifest dependency column are reserved (Q12). The plan's `prereqs`/`shard` fields absorb the cross-item edge later with zero structural change (§22.2). The DAG/context-object machinery is NOT reserved. |
| **`volatility` score** | added later as one score definition at content-kind/per-fact when a churn signal is confirmed (SM7; §6.2). |
| **Brand pack** | sugar bundling a set of flagged instance-global voice defaults (§12.6); never called an "actor". |
| **De-jure interchange (DocBook 5 / TEI P5)** | one additional render-target entry over the same AST; zero rework (§14.2, §17). |
| **Set-subtract `-` operator** | reserved in the §13.2 grammar; out of v1 (§12.4). |
| **Language/localization fanout GA** | the reconcile slot, ordering, and fidelity constraints are designed (§16); the multi-language feature ships later as a drop-in. |
| **Empty-pool relaxation suggester** | an advisory UX layer on §6.4's block — suggests, user confirms, never auto-applies. |
| **AIMD width auto-tune** | consumes the §22.5 telemetry dataset; advisory `recommended_width` is the v1 step (PC11). |
| **Per-part dimension overrides** | the IR carries per-part `constraints` (§15); the resolver leaves the part-scoped slot (§12.3). **T7 (open):** the archived model said "a part is a layer in the value cascade", but the ratified spine has no part rung — WHERE a part layer would sit is an open design question, registered at §27.3, resolved only when this feature is built. |
| **Entry `aliases:` graceful rename** | registered as deferred at B4 (entry-identity rider): an optional frontmatter field letting a renamed entry carry its old ids; not built in v1 — a rename is a deliberate two-touch act whose dangling references fail loudly at M1 (§11.1). |
| **Same-inputs fit re-roll** | deliberately inexpressible under FR2's digest identity ("roll again under identical config" needs a nonce); a nonce segment is grammar-compatible with the `_` qualifier (§7.4); needs its own ruling — registered (§27.3). |
| **Stale-fit sweep** | caller-composable today: `list deliverables {platform, fit_current: false}` + a force loop (§21.3, §21.8); any system-side batch convenience would still be an explicit caller act (Q3) — registered (§27.3). |
| **HTTP shim for cloud orchestrators (GAP-2)** | ~~Deferred~~ **BUILT (DR-1, 2026-07-24).** The v1 external-actor door is the local `pipeline invoke render` CLI (the n8n Execute Command door); a **cloud-hosted** orchestrator (Make/Zapier/n8n Cloud/Google) cannot shell a local CLI and needs an HTTP endpoint. Shipped as an **additive, transport-agnostic HTTP shim over the same `invoke()`** (`pipeline/api/http_shim.py`, `scripts/pipeline serve`) — the same safe verb set (never operator verbs, §21.9), auth + rate-limiting owned by the shim. The "same JSON envelope" holds for Tier-A + the terminal poll; **paid Tier-B verbs add the sanctioned 202-Accepted ack + poll/webhook status mapping** (§21.7 DR-1 amendment above — an additive wire shape, not a violation). See `docs/known-issues.md` **DR-1**. |

## §27 Open-items register

Everything not designed in this document is named here. Nothing below is decided here.

### §27.1 Deferred-but-mandatory design

- **D2 — id string encoding: CLOSED at §7.4 and RATIFIED (B4-1)**, additively amended by the
  ratified per-level revision-qualifier grammar (FR2, FR7.2). No deferred-but-mandatory design
  items remain.

### §27.2 Docs-researcher gates (before build)

- **G1** — FS atomic primitives (create-if-absent; **no-replace commit** — create-exclusive
  rename/link, the §22.3/§22.7 commit primitive; replacing rename; single-line append) on the
  REAL workspace store, esp. synced/network filesystems; DB commit substrate is the fallback
  (§22.8).
- **G2** — the subscription's real concurrency/rate limits, VALIDATED against the §22.5 telemetry
  dataset.
- **G3** — Graphify serve-MCP + output-path flags (the original transport gap; feeds mission D4).
- **G4** — YAML 1.2 + typed safe-load library + frontmatter splitter pin (§13.5).
- **G5** — headless Claude Code subscription-auth transport (F10 HARD: subscription, never API
  keys — verified before any build; §21.9).
- **G6** — Graphify per-symbol merge/review metadata availability (`review_status` degrades to
  `unknown`; §6.2).

### §27.3 Registered design flags

**The review trigger (B4-5):** every registered item below is re-examined at the pre-build gate
phase — when the §27.2 gates G1–G6 run — by an architect pass that either designs it or
re-registers it with reasons. The register never sits without a clock.

- **T7** — cascade placement of a future per-part override layer (§26) — open; decided if/when
  the deferred feature is built.
- **Folio member REMOVAL / role supersede** (registered at B4-5) — v1 membership is append-only
  with typed in-place `pin`/`role` updates (§21.2), a coherent v1 posture; whether members can be
  removed or superseded — and how that composes with PC4's append-only write-safety posture and
  with typed-folio regeneration (§9.6) — is registered.
- **Same-inputs fit re-roll** (registered at FR6) — deliberately inexpressible under digest
  identity (§21.8, §26); a nonce segment is grammar-compatible with the `_` qualifier (§7.4) but
  needs its own ruling if wanted.
- **Retention/GC policy for non-current fits and deliverables** (registered at FR6; strengthened
  at FR7.6) — the v1 disposition is fixed: retain all, id-addressed, computed currency (§21.8).
  Any future GC design must honor id-addressed retrieval for referenced ids, and should treat
  superseded *serialize* generations as its primary case — a tool upgrade re-mints broadly on
  next render.
- **DR-1 `jobs/` retention/GC** (registered at the DR-1 build) — the async subsystem's
  workspace-scoped `jobs/` store (§23) holds §22.7-class LOSSY job/idempotency records, keyed by
  a NON-artifact run-family id (a digest of the sorted target-id set + `idempotency_key`) and
  NEVER an output route (`output_path`/`is_done` refuse every non-artifact family with
  `StorePathError`). v1 is **retain-all**, like the claim table and the non-current-fit stores
  above; time-based GC of terminal/abandoned records is registered and deferred. Any future
  policy must honor the lossy discipline — a missing record resolves re-drivable, never DONE
  (§22.7). The subdir + this keying convention land at DR-1 Commit 2; the `JobStore` record
  logic and steal lifecycle at Commit 3.
- **Stale-fit sweep** (registered at FR6) — auto/batch re-reconcile ("re-fit everything stale on
  platform P") is caller-composable via `list deliverables {platform, fit_current: false}` + a
  force loop (§21.3); a system-side batch convenience would still have to be an explicit caller
  act (Q3) — registered, not designed.
- **M3 selection expression × identity preimage** (registered at B4-5) — the Q17 preimage carries
  source-subset + commit-map only; changed `require`/`span`/`on_conflict` clauses do not
  re-materialize existing ids (documented behavior, §21.8). Adding the effective M3-expression
  digest to the preimage would be identity churn and needs strong motivation.
- **M3 clause grammar × the D1.1 AST** (registered at B4-5) — source-selection clauses share the
  operator-vocabulary discipline but ride M3's own grammar (§6.3, §13.2); folding them into the
  `Pred` AST (extending the ratified `pred_op` vocabulary with the date-window
  `contains`/`overlaps`, §6.2) would be additive polish; the shared-vocabulary discipline
  prevents drift meanwhile.
- **DR-3 pre-compose outline store** (registered at the DR-3 build) — editable outlines persist in
  a dedicated **`outlines/`** directory, content-addressed by the **bare `outline-digest`** (a
  content address, not a §7.4 id root), created on-demand and deliberately NOT in `STORE_SUBDIRS`
  (outlines are pre-compose sources, not §18 records). v1 is **retain-all**: abandoned scaffolds
  and every intermediate edit are kept, byte-compared for idempotency (a same-key/different-bytes
  collision raises loudly, never a silent overwrite). GC is registered and deferred (as with the
  non-current-fit retention posture above).
- **DR-3 v1 honest scope** (registered at the DR-3 build) — v1 ships **horn (a)'s fixed drive
  posture** (§7.2, §12.1) with **hand-authored** outlines. **DEFERRED:** the **LLM outline
  drafter** (a named DR-3 backlog, GAP-7 mirror) and the **R1 compose-input-brief live ablation** —
  an offered, deferred **maintainer-run** measurement (à la the MVP-demo live run / GAP-8 EXP-10).
  The design is safe regardless of the ablation: the outline enters as **identity** (an
  `outline-digest` preimage input, not a grounding assertion) and the §6.5 EXTRACTED tier floor
  binds every span, so the brief's precedence **degree** is empirical, never a correctness gate.
  See `docs/known-issues.md` DR-3.
- Notation — the migration package is MIG-1…MIG-7 in this document; the CM-tag collision is
  resolved in Appendix A.

(Closed and therefore absent from this register: T1 — the MVP covers all 9 axes (A4-3, §25);
T11 + the "folio state" definition (A4-4, §9.2); folio ordering/schedule (A4-4, §9.1); the three
B1-stage recommendations — the D2 template, the folio-type coherence binding, and the
member-role locus — ratified at B4-1/B4-2/B4-3 (§7.4, §9.6, §9.2/§9.6); the force-re-reconcile affordance — designed
and ratified as FR1–FR6 (§21.8, §7.4, §16); and serialize-level input evolution — the discovered
RI11-tier-2 × no-replace contradiction — designed and ratified as FR7 (§17, §18, §21.8).)

### §27.4 Inherited open areas & registered build items

**Open areas (carried from superseded docs, not dropped):**

- **Product-plane agents & skills organization.** The generation-stage *contracts* are fixed
  (writer emits the IR §15; reconcile agent honors §16's fidelity constraint — grown by DR-4 so the
  **preserve-section-keys** contract joins the voice/content, provenance/tier, and typed-section
  obligations, and by DR-5 so the **preserve-citation-keys** obligation (inline `[@key]`, SUBSET-only,
  C8) joins them too, and by DR-2 so the **advisory lexicon-fidelity** preserve (house style carried
  through a reshape — a recommendation READ FROM THE BINDING, NOT a machine gate, C4) rides alongside
  as the honest advisory ceiling; two reviews §19; deterministic render §17) — but the agent/skill
  packaging for the product plane is open. The
  **IDEATION stage** (repo + audience → ranked idea queue; §2.1) has **no ratified contract at
  all**: fully open, product-plane. Nothing in this document designs either.
- Mission §10.4 remainders: **D3** (runtime minimums — decide at install), **D5** (writing-base
  fork), **D6** (queue-draining cadence policy — distinct from §22.5 width), **D7** (large-matrix
  guards).

**Registered build items (design fixed here; implementation artifacts to produce):**

- The §13.2 string parser (bounded grammar spec + tests).
- The SSOT row/column schema + status lifecycle (delivered at §24; build step 22).
- The local-CSV single-writer SSOT serializer (§22.3).
- Lease-TTL + `max_parallel_sessions` conservative defaults (§22.8).
- The render pin-bundle assembly (§17).
- Migration build risks: (1) deterministic-map totality/composition validation is absorbed by
  schema-lint (§11.7); (2) disguised-rename silent data loss is review-only, not
  machine-detectable (§11.7 known limit); (3) the serialization dependency is bound by §13.4.
- **Post-adoption repo cleanup sweep** (per the approved A4-2 placement package): sweep
  `quickstart.md`, `README.md`, the `*.template.*` files, `.claude/readme.md`,
  `state.template.md`, and `docs/*` to this model, and apply the deferred `check-no-content.sh`
  guard change (pairs with §10). Commits gate on explicit maintainer approval; `CLAUDE.md` edits
  remain maintainer-only — prepared as a diff, delivered, never applied by an agent (Appendix B).

---

## Appendix A — Ruling cross-index

Traceability only — no authority. Every ratified ruling family and its primary home in this
document (xref homes in parentheses). **Notation:** the schema-migration package's components are
cited as **MIG-1…MIG-7** in this document; they were logged under "CM1…CM7" labels that collide
with the combine-mode ruling CM3 — MIG-n is the definitive tag. The full decision record behind
these tags is imported at `docs/archive/design-record/`.

| Ruling | Primary home | Note |
|---|---|---|
| Q1, Q2 | §14.1 | two render passes; "free" scoped to serialize |
| Q3 | §3.1 | no-overstep (cross-cutting) |
| Q4 | §8 | pairing freedom; emergent allow-list; advisory lint |
| Q5 | §5.1 | faceted dimension model |
| Q6 | §5.2 | persona/voice split; `default_voice` (chain §12.3) |
| Q7 | — | routed; resolved by F1–F10 |
| Q8 | §9.5 | via F9 (X-thread = split) |
| Q9 | §21.5 | via F7 (manifest ≠ SSOT slice) |
| Q10 | §6.1 | attach tiers |
| Q11 | §11.7 | full lifecycle in v1 (mandate over all of §11) |
| Q12 | §26 | deep-folio reservations only |
| Q13 | §5.3 | classification (mechanics §16) |
| Q14 | §5.2 | Format `parts` intra-genre only |
| Q15 | §10 | provenance/scope bundle ((iii) implemented by SV5 §11.4) |
| Q16 | §19 | two reviews |
| Q17 | §7.1 | identity core |
| Q18a | §12.1 | M1-before-M2; type-driven |
| Q18b | — | routed; resolved by CA1–CA10 |
| Q19 | §25 | MVP mandate (extended by A4-3) |
| F1 | §9.4 | batch = lineage query |
| F2 | §9.2 | folio owns membership (amended unordered by A4-4) |
| F3 | §9.2 | artifact-level membership + per-member pin |
| F4 | §20 | token contract (wire form §21) |
| F5 | §9.3 | folios = workspace state |
| F6 | §20 | system-mutation boundary |
| F7 | §21.5 | manifest lifecycle (closes Q9) |
| F8 | §9.3 | folio id scheme (string form §7.4) |
| F9 | §9.5 | split vs folio; part identity (§7.1); ordering half amended by A4-4 |
| F10 | §21.1 + §21.9 | verb set; subscription transport HARD (boundary §2.2) |
| C1–C7 | §6.2 | score research absorbed via SM5–SM8 |
| SM1 | §6.4 | empty pool blocks + reports |
| SM2 | §6.3 | clause chooses hard/soft |
| SM3 | §6.4 | most-local relax + warn; no `locked:` |
| SM4 | §6.3 | selectable `on_conflict`; factual-beats-opinion |
| SM5 | §6.1 | content-kind registry |
| SM6 | §6.2 | `review_status` in v1 |
| SM7 | §6.2 (§26) | `volatility` deferred to hook |
| SM8 | §6.2 | `coverage` resolver-internal |
| SM9 | §6.5 | tier ⟂ traceability |
| SM-R1 | §12.1 | M3 widened to carry require/span/on_conflict |
| RS1 | §14.2 | Pandoc AST layer 3; side = a setting; B addable later (§26) |
| CA1 | §12.3 | entry-default = the M2 base |
| CA2 | §12.3 | voice selection chain |
| CA3 | §12.3 | surviving content: no folio-divergence warning (rest absorbed by DIRECTIVE) |
| CA4 | — | routed; resolved by CM3 |
| CA5 | §12.5 | override = run layer only (terminology §4) |
| CA6 | §7.2 | delta-vs-floor identity |
| CA7 | §12.5 | collect-once; bind at M2 |
| CA8 | §12.3 | mandatory-global = Voice+Language+Output-type; Platform excluded |
| CA9 | §12.7 | advisory-in-M2 / hard-at-gate (gate §16) |
| CA10 | §12.7 | nudges never move explicit weights |
| DIRECTIVE | §9.1 | folio holds no dimensions/rendering opinion (consequences §12.2, §21.5, §5.4) |
| BO2 | §12.6 | brand-authoritative voice flag (BO4 pack → §26) |
| CM3 | §12.4 | combine operators (syntax home §13.2; list/set split §11.1) |
| SV1, SV2 | §11.2 | definition_version number-space; ONE global schema_version |
| SV3 | §11.3 | closed schemas + metadata bag (stamp shape §11.2) |
| SV4 | §11.1 | co-located `_schema.yaml` (encoding §13.4) |
| SV5 | §11.4 | `x-` entry namespacing |
| SV6, SV7 | §11.5 | binary meaning discipline; drift at both times (refined by MIG-4/MIG-6) |
| SV8/SV9 = MIG-1…MIG-7 | §11.6 | ratified migration v2 (+1-year window); migration v1 RETRACTED → Appendix B only |
| SV10, SV11 | §11.7 | uniform coverage; schema-lint |
| MIG-1…MIG-7 | §11.6 | step registry & fold · 1-yr window · no deprecation lifecycle · binary-by-shape · worklist gate · block/warn table · config-only scope |
| RI1–RI4 | §15 | IR (RI3 fidelity constraint homed §16) |
| RI5 | §16 | reconcile ordering + terminal gate |
| RI6–RI9 (+R-4) | §17 | serialize; AST path; Attr mapping + strip filter; one-AST-per-doc |
| RI10, RI11 | §18 | persistence keys; regeneration tiers (`fitted-id` defined §7.1) |
| RI12, RI13, RI14 | §17 | dispatcher + side; pin set; layer-3 contract (rides §21.5) |
| RI15 | §2.2 | responsibility boundary statement |
| PD1–PD8 | §5.3 | Presentation (lowering §17; identity §7.1; floor §12.3) |
| API1 | §21.1 | token = cursor; verb/action line |
| API2 | §21.2 | closed action vocabulary |
| API3 | §20 | token contract (wire §21) |
| API4 | §21.3 | discovery + meta-types |
| API5 | §21.4 | run overrides + M1 guard (semantics §12.5) |
| API6 (+fetch) | §21.5 | retrieval; manifest; member targets |
| API7 | §21.6 | batch+cursor sequential mode |
| API8 | §21.7 | typed result contract |
| API9 | §21.8 | pins + idempotency |
| API10 | §21.9 | transport + flags (gates §27.2) |
| PC1, PC2 | §22.2 | wave plan; exactly-once cover |
| PC3, PC4, PC5 | §22.3 | claims; write rules; sweep |
| PC6, PC7 | §22.4 | handoff; failure/retry |
| PC8, PC11 | §22.5 | instance-scoped width; telemetry + advisory tuning |
| PC9 | §22.6 | parallel-path codes |
| PC10 | §22.8 | preconditions (gate G1) |
| PC12 | §22.7 | INV-CORRECTNESS (T3 reconciliation written there) |
| D1.0–D1.4 | §13.1–§13.5 | serialization (SSOT row schema homed at §24) |
| D2 | §7.4 | id string encoding — closed by B1, ratified B4-1; revision-qualifier grammar per FR2/FR7.2 |
| Capstone-1 (identity) | §7 | section-wide |
| Capstone-2 (spine + M3) | §12.2 / §12.1 | |
| Capstone-3 (matrix + Presentation) | §5.4 | |
| Capstone-4 (terminology + metadata bag) | §4 / §11.3 | two halves |
| Capstone-5 (strip filter + one grammar) | §17 / §13.2 | two halves |
| Capstone-6 (new stores' home) | §23 | |
| Capstone-7 (instance width + INV-CI) | §22.5 / §22.7 | two halves |
| Capstone-8 (docs-researcher gates) | §27.2 | |
| Capstone-9 (D2) | §7.4 (§27.1) | closed by B1; ratified B4-1 |
| A4-1, A4-2 | §1, Appendix B | skeleton + placement approvals (process record) |
| A4-3 | §25 | MVP = all 9 axes |
| A4-4 | §9.2 | "folio state" defined; ordering/schedule removed (§9.1); marker = `{added_ts, pin?, role?}` (§13.3); conditions (i) §9.2/§21.5, (ii) §9.6 |
| B4 entry-identity | §11.1 | id in frontmatter = filename slug; lint §11.7; lexicon §4; pointer §7.4; `aliases:` deferred §26 |
| B4-1 | §7.4 | D2 id-encoding template ratified (revision-qualifier grammar added by FR2/FR7.2) |
| B4-2 | §9.6 | folio-type coherence binds at the generating run |
| B4-3 | §9.2 / §9.6 | member-role locus = the member record |
| B4-4 | §22.3 / §22.7 | no-replace commit + holder-checked release (lease-steal repair; gate G1) |
| B4-5 | §27.3 | register dispositions + the pre-build review trigger; FR commission |
| FR1–FR6 | §21.8 | force-re-reconcile: `force_reconcile` param (§21.2) · fit-revision identity (§7.4) · fit-binding (§16) · currency fields (§21.3) · manifest/pin semantics (§21.5, §9.2) · codes (§21.7) · SSOT rows (§24) · reviews (§19) · regeneration tier (§18) |
| FR7 | §17 / §21.8 | serialize-revision: serialize-inputs preimage + render-binding (§17) · reader-pin AST key + tier-2 rewrite (§18) · per-level qualifier grammar (§7.4) · auto-mint resolution + code re-scope (§21.7, §21.8) · full Review 2 (§19) |
| Migration v1 (RETRACTED) | Appendix B | rejected record only; no design home |

Rejected-option records (the "why not" behind each ruling) live in the imported decision record,
not in this document.

## Appendix B — Supersession map

History only — no authority. This appendix records what this document replaces, where the old
text goes, and the maintainer-action list that accompanies adoption (per the approved placement
package, A4-2). Commits gate on explicit maintainer approval (durable rule 7); `CLAUDE.md`
edits are maintainer-only — prepared as a diff, delivered, never applied by an agent.

### B.1 Placement

- **This document lands at `docs/design.md`** — one file, short stable path, framework-owned. A
  `docs/design/` six-file split remains a deferred option if this document proves unwieldy in
  review — the call remains the maintainer's.
- **The decision record** (`maintainer-rulings.md`, at minimum) is imported to
  `docs/archive/design-record/` as the provenance trail behind Appendix A; the maintainer
  verifies no instance specifics before import. Pass reports optionally join it.

### B.2 `docs/design-decisions.md` — superseded ENTIRELY → archived

Archive to `docs/archive/design-decisions.md` with a tombstone header pointing here. Gap-free
section map:

| Old section | Superseded by |
|---|---|
| §1 status & how to read | Appendix B history row (moot under archive) |
| §2 lexicon | §4 |
| §3.1–§3.3 dimensions | §5 |
| §3.4 pipeline/IR | §14 (+§15, §17) |
| §3.5 reconciliation | §16 — **supersession written there: fit-or-block replaces "never blocks"** (T4) |
| §3.6 sources | §6 |
| §3.7 folios | §9 — **DIRECTIVE + A4-4 replace shared-grounding/roster-as-folio-properties (T2 → §9.6) and ordering/schedule** |
| §3.8 overrides/cascades | §12 — incl. the M3 widening (T8) and CA5 terminology |
| §3.9 provenance/scope | §10 |
| §3.10 schemas & versioning | §11 |
| §4 decision log 1–9 | Appendix B history (the log's decisions are absorbed or superseded by the ruled design) |
| §5 deferred hooks | §26 |
| §6 open areas | §27.4 |
| §7 changelog | Appendix B history row |

Stale claims that die with the archive (each superseded at its flagged section): folio
`rendering_intent`/ordering/schedule and compat-adjacent folio text (§9); "reconciliation never
blocks" (§16); "manifest = a slice of the SSOT" (§4/§21.5); the 4-kind dimension table (§5.1);
`valid_platforms` on Format (§5.2/§8); "a part is a layer in the value cascade" as settled fact
(→ open T7, §27.3).

### B.3 `docs/mission.md` — partially superseded; retained + banner

Retained as the product/PRD + sourcing/ops context, with a supersession banner enumerating the
dead sections and pointing to `docs/design.md`.

- **Dead (superseded here):** mission §2 architecture (→ §2/§14); §3 axes + extensibility (→ §5;
  the 4-axis matrix and inline-compatibility text are obsolete); §4 selection / fanout /
  compatibility-filter / identity / config (→ §7/§8/§12/§13; the compatibility filter is DELETED
  per Q4); §8 config artifacts & how-to-extend procedures (→ §5.4/§23; its §8.2 → §8/§12/§13;
  its §8.3 agents/commands → §27.4; its §8.4/§8.5 → §5.4 + §27.4); §1's MVP/success criteria
  (→ §25); §10.4 rows D1 (→ §13) and D2 (→ §7.4).
- **Retained (living, not design):** §0 doc control, §5 phased plan (update against §25 —
  maintainer call), §6 dependencies/install, §7 component vetting, §9 security/read-only model
  (render-side additions live in §15–§17), §10 risks, appendices.

### B.4 `docs/operating-model.md` — retained + amended

Q15(i) rewrites its ownership section as mixed-provenance; the instance-owned list gains
`content-kinds/` additions, `x-` prefixed entries, `instance/ops/` stores, and the
`extends:`-partial customization path (Q15 ii). **Authority for provenance/scope moves to §10**;
operating-model remains the two-repo how-to conforming to it.

### B.5 `CLAUDE.md` — maintainer-only action list

Proposed follow-ups; no agent edits these — the maintainer does, on adoption:

1. "The matrix" paragraph: replace "the resolver applies the compatibility filter" + 4 axes with
   the emergent-allow-list + 9-axis model (§8, §5.4); repoint the heading's "(mission §3–§4)" and
   the Pointers line "Design: `docs/mission.md`" to `docs/design.md`.
2. Rule 3: add a one-line cross-reference to §22.7's domain separation (clarification, not a
   change of authority) — the T3 action.
3. Rule 4: repoint the citation "see `docs/design-decisions.md` §3.9" to §10 **at archive time**;
   update the guard reference to the Q15 default-deny guard once implemented.
4. Rule 5: add the ratified Q15(ii) extension — shipped `provenance: framework` entries join the
   never-edit list; instances customize via workspace `extends:` partials.
5. Refresh the repo-map block per §23 (`_schema.yaml` files, `content-kinds/`, `render-targets/`,
   `recipes/`, `folio-types/`, `instance/ops/`).

### B.6 Remaining stale files — dispositions

`quickstart.md`, `README.md`, the `*.template.*` templates, `.claude/readme.md`,
`state.template.md`: **retained-with-amendment** via the post-approval cleanup sweep (§27.4).
`docs/bootstrap.md`, `docs/claude-code-usage.md`: **retained** (how-tos), swept for stale design
references. `docs/agents-and-skills-sourcing.md`: **retained-with-amendment** — its lines teaching
the deleted compatibility-filter model are superseded by §8 and amended at sweep time.

### B.7 The retracted migration-v1 record (sole home)

The first ratified schema-migration package — a version-floor support window ("current + previous
major") with a below-floor hard block, a documented manual hand-edit path, a per-attribute
deprecation/removal lifecycle (`removal_target`), and an SV6 third tag — was **RETRACTED in
full** by the maintainer before Phase A. Fatal defects: the version-floor hard block contradicted
the skip-safety requirement (users may skip any number of versions, including majors), and
per-attribute deprecation was rejected as a maintenance nightmare (versioning is all-or-none).
Its build-risk list (the R-M series) is confined to this record; the ratified replacements are
§11.5–§11.7 (MIG-1…MIG-7) and the migration build risks registered at §27.4. Nothing from the
retracted package may be cited as design.

---

*End of the definitive design document (FINAL — post-B4 amendments and verification-pass fixes
applied). The B4 walk ratified the entry-identity rule (§4, §11.1, §11.7) and the
three B1-stage recommendations — B4-1 (§7.4), B4-2 (§9.6), B4-3 (§9.2/§9.6) — ratified the ADV-1
lease-steal repair (B4-4, §22.3/§22.7), and disposed the registered flags (B4-5, §27.3). The
commissioned force-re-reconcile package (FR1–FR6) and its serialize-level extension (FR7) are
ratified and applied at §7.4, §9.2, §12.3, §16–§19, §21.2–§21.8, §22.3, §24, §26, and §27.3.*
