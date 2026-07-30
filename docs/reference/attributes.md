<!-- GENERATED — do not edit; run `pipeline docs attributes` -->

# Registry attribute reference

What every registry attribute MEANS and DOES. This page is generated from the framework registry schemas — the `REGISTRY_ROOTS` walked by `pipeline.lint` — so it carries framework mechanism only, never client or per-deployment content. Each attribute lists its type, its floor (the L0 cascade default, §12.2), its `definition_version`, and the schema's own `definition:` prose, verbatim.

Regenerate with `pipeline docs attributes`. A byte-equality CI test (`tests/test_attributes_doc_contract.py`) fails loudly if a schema `definition:` is edited without regenerating this file.

Documented: 17 collections, 77 attributes.

## `content-kinds` — schema_version 1

### `authoritative`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

§6.2 score `authoritative` (scalar 1-5; asserted default per kind; attach: content-kind -> per-fact refine). How definitive this kind of content is about its subject. Serves grounding weight and conflict priority (§6.3: factual outranks opinion). NOT the inverse of `opinionated` (§6.2).

### `freshness`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The kind-level FRESHNESS POLICY (§6.1 table: "freshness-policy"; §6.2 score `freshness`, type date-window/range, DERIVED per-fact from commit/mtime). The config-side carrier is a date-window expression in the §6.2/§6.3 predicate vocabulary (e.g. "12mo" = content of this kind is a stale-risk beyond 12 months); empty = no kind-level policy, freshness is purely per-fact derived. Consumed by the M3 resolver (step 17) as filter + weight input.

### `opinionated`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

§6.2 score `opinionated` (scalar 1-5; asserted default per kind; attach: content-kind -> per-fact refine). How much of this kind of content is stance/ judgment rather than record. Serves selection/weight; independently useful from `authoritative` — not its inverse (§6.2).

### `review_status`

- **type:** `enum ("unreviewed", "reviewed", "formally-vetted", "unknown")`
- **floor (default):** `"unknown"`
- **definition version:** 1

§6.2 marginal ruled IN for v1 (SM6): categorical review state at content-kind, refined per-fact where the adapter exposes merge/peer-review state. Degrades gracefully to `unknown` (the G6 gate closed exactly there: graphify exposes no per-symbol review metadata, so per-fact refinement rides this default) — the floor IS the designed degradation.

## `diagram-styles` — schema_version 1

### `tool`

- **type:** `enum ("dot", "d2", "auto")`
- **floor (default):** `"dot"`
- **definition version:** 1

Which deterministic compiler draws the SAME gated node/edge list to SVG (amendment §2.D/§2.F). `dot` (Graphviz, the PINNED default) is the lightest, byte-deterministic hierarchical engine — same source in, same picture out, on every machine. `d2` is the selectable alternative for a more polished/grouped look (also spike-proven byte-deterministic per machine). `auto` is an EXPLICIT opt-in probe that picks the first installed of (`dot`, `d2`) — it is NEVER the default because it keys the picture on the ambient install-set (environment-dependent identity), so it is for locked/known environments ONLY. A chosen-but-missing tool at compile time is a LOUD `DiagramToolUnavailableError` (never a silent half-diagram). It is a COMPILE TARGET, not an edge source: `to_dot`/`to_d2` both emit from the identical spec, so a tool swap can only change the SVG bytes/hash, never the grounded structure (honesty-safe, §2.F).

## `folio-types` — schema_version 1

### `roles`

- **type:** `list of map`
- **floor (default):** `[]`
- **definition version:** 1

The ORDERED declared role structure (§9.6 — order feeds role-based ordering reconstruction from tracked data). Each item is a map with `role` (the §7.4 role slug written into member records at add-time, B4-3) and optional `skeleton` — the per-role RECIPE SKELETON (§9.6): partial recipe slots in the recipes/_schema.yaml vocabulary (e.g. `format`, `goals`, a prose `topic_slot`) that the generating run instantiates into a concrete recipe. Skeleton slots are blueprint inputs to the run, never folio-held dimension values (the DIRECTIVE); unknown ids inside a skeleton fail loudly when the run resolves them (§11.1). Duplicate role slugs are legal on folio MEMBERSHIP (§9.6 regeneration) but this declared structure lists each role once. Ordered `list`: union is a schema error (§11.1); replace-only on cascade — a folio type is a coherent blueprint.

## `formats` — schema_version 1

### `diagram_disposition`

- **type:** `enum ("", "suppress", "resist", "prefer", "require")`
- **floor (default):** `""`
- **definition version:** 1

The genre's stance on whether a composed artifact carries a diagram (DR-9). The floor is the NEUTRAL member `""` — the writer decides, today's behavior; an unset Format rides `""`, which is omitted from the §7.2 identity delta, so every existing artifact-id re-mints byte-identical (neutral is the `""` floor, never a literal token). HARD guarantees: `suppress` = no diagram; `require` = a GROUNDED diagram that passes the base grounding gate or the compose refuses (an illustrative figure never satisfies `require`). SOFT prompt biases: `resist` / `prefer` nudge the writer against / toward a diagram without guaranteeing the outcome. Run-tunable via `--set format.diagram_disposition=…`; a non-member value is refused pre-spend by the closed-schema enum validation at plan resolution, before any writer call.

### `parts`

- **type:** `list of text`
- **floor (default):** `[]`
- **definition version:** 1

Optional ORDERED list of named intra-genre sub-outputs, defined entirely inside this one governing Format entry (Q14, §5.2; e.g. slide-deck -> [slides, presenter-notes]). One format selected -> one artifact with named parts; part names surface as part Div ids in the IR/AST (§15). Empty = a single-part genre. Ordered `list` by design: `union` on it is a schema-validation ERROR (§11.1 CM3 — format.parts is the design's own example) and cascade combination is replace.

### `section_schema`

- **type:** `list of map`
- **floor (default):** `[]`
- **definition version:** 1

The base genre's OWN typed-section conformance contract (DR-4, §5.2/§15): an ordered list of section-conformance rules in the `pipeline.sections` C2 vocabulary (presence/order/count/ length; each with a role- or type-axis selector and an error|warning|info severity). Author ROLE selectors (e.g. abstract/methods/results) HERE — roles are author-declared, never structural `type` kinds (the SECTION_TYPES carrier holds structural kinds only). Floor `[]` = no contract: an unset value rides the L0 floor, is omitted from the §7.2 identity delta, and every existing artifact-id re-mints unchanged. Meaningful ONLY on outline-shaped Formats; a non-outline Format that declares one is treated as EXEMPT by the base gate (no outline scaffold, no outline-digest identity coverage), never silently unconformant-by-absence.

## `goals` — schema_version 1

### `kind`

- **type:** `enum ("strategic", "action")`
- **floor (default):** `"strategic"`
- **definition version:** 1

The §5.2 goal tag: `strategic` = an outcome the piece advances (explain, convince); `action` = a concrete reader act — a CTA is simply a goal with `kind: action` (§5.2). No separate CTA mechanism exists.

### `source_selection`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Partial §6.3 source-selection contribution: any of `require` (hard predicates), `prefer` (soft weight nudges — the §12.7 CA10 lever), `span` (positive coverage), `on_conflict` (strategy). Clauses reference score CHARACTERISTICS only, never source ids (§6.3); they ride M3's goal-implied layer (§12.1) — later layers may add, tighten, or (most-local-wins, warned) relax them (§6.4 SM3). Example (§6.3): convince -> prefer authoritative +2; require traceability. The clause grammar is parsed by the M3 resolver (step 17); this map carries it as authored.

## `languages` — schema_version 1

### `name`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

Human-readable display name of the language (e.g. English). Documentation for humans and review surfaces; never a cascade value beyond itself.

## `lexicons` — schema_version 1

### `banned_terms`

- **type:** `set of text`
- **floor (default):** `[]`
- **definition version:** 1

Terms that must never appear — an unordered `set` of `text` (order is not meaningful; the set canonicalizes sorted+deduped into any identity delta, §7.1/ §12.4). Distinct from `preferred_terms` (which supplies a replacement); a banned term is simply disallowed. Default combine across rungs is REPLACE (§12.4 — no `combine:` override at C1; a `union` accumulation is a later wiring decision, not a registry-stand-up concern). Floor empty = no banned terms.

### `mechanical`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Mechanical house-style rules as an OPEN, bare/untyped `map` (keys like `oxford_comma`, `number_style`, `date_style`, `unit_style`). Deliberately NOT a closed enum: a new mechanical rule must be a ONE-FILE add on a lexicon ENTRY, never a schema edit (known-issues.md — the open-carrier posture). Values are opaque to the schema (a bare map is not element-typed); a consumer reads the keys it knows. Floor `{}` = no mechanical rules. Compose-consumed as an attribute; the body never carries these.

### `preferred_terms`

- **type:** `map of text`
- **floor (default):** `{}`
- **definition version:** 1

Terminology preferences as an avoid → use map: each key is a term to avoid and its value is the preferred replacement (e.g. `utilize: use`). A `map` of `text`, not a `set`, because the pairing (what to say INSTEAD) is the payload. Floor `{}` = no terminology preferences. Compose-consumed as an attribute (the identity invariant); the body never carries these.

### `proper_names`

- **type:** `map of text`
- **floor (default):** `{}`
- **definition version:** 1

Proper-name canonical casing as a token → canonical-casing map (e.g. `github: GitHub`, `javascript: JavaScript`): each key is a lowercased lookup token and its value is the one correct rendering. A `map` of `text` (the casing is the payload). Floor `{}` = no proper-name casing rules. Compose-consumed as an attribute; the body never carries these.

### `spelling`

- **type:** `enum ("", "us", "uk")`
- **floor (default):** `""`
- **definition version:** 1

The spelling standard to enforce: `us` or `uk`. The floor is the NEUTRAL member `""` — an unset lexicon imposes NO spelling rule (absent = no normalization), exactly the honest-unset precedent the `""` floor encodes elsewhere (e.g. `platforms.default_output_type`). `us`/`uk` select a standard; the empty member is never a spelling — it is the "no rule" floor, so shipping this attribute churns no id for a lexicon that omits it (§7.2).

## `output-types` — schema_version 1

_No attributes: a thin registry whose entry id and body prose are the whole object (`attributes: {}`, §11.7 SV10)._

## `personas` — schema_version 1

### `credibility_signals`

- **type:** `list of text`
- **floor (default):** `[]`
- **definition version:** 1

What "this author is credible" looks like TO THEM (§5.2 "credibility signals") — the evidence shapes that earn this audience's trust. Ordered prose items; replace-only on cascade (§12.4).

### `default_voice`

- **type:** `ref`
- **floor (default):** `"clear-explainer"`
- **definition version:** 1

The Voice entry id this persona's coherent bundle implies (Q6, §5.2) — the sole cross-dimension default provider for Voice. Cascade placement is CA2 (§12.3): it beats the L2/L3 scope-default voices (selecting a persona is a per-artifact editorial act) and yields to the L5 recipe voice, a §12.6 brand-authoritative flagged value (BO2), and the L6 run. The floor names the framework default voice `clear-explainer` (a shipped entry, so the floor always resolves); an unknown id fails loudly at M1 resolution (§11.1).

### `knowledge_level`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

What this audience already knows — what to assume vs. explain (§5.2 "knowledge level"; didactic calibration is Persona + Format, never Voice). Prose fact, e.g. "expert practitioner in the field, new to this specific system".

### `motivation`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

What this audience wants from the content (§5.2 "motivation") — the question they are trying to answer or the decision they are trying to make.

### `objections`

- **type:** `list of text`
- **floor (default):** `[]`
- **definition version:** 1

What makes this audience dismiss a piece (§5.2 "objections") — skepticisms the content must anticipate. Ordered prose items; replace-only on cascade (§12.4: list union is a schema error — a persona is a coherent bundle, §5.2).

### `role`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The audience's role/relationship to the content (§5.2 audience facts): who they are professionally and how they stand relative to the subject (evaluator, user, buyer, peer). Fact, not register — how the piece SOUNDS is Voice.

## `platforms` — schema_version 1

### `advisory_norms`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Platform-wide ADVISORY norms (CA9 advisory class, §12.7): named constraint values (e.g. preferred_char_count) that ride the M2 cascade; recipe/run may deviate with a one-time warning. Never hard feasibility — that is hard_limits.

### `default_output_type`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The platform-implied WEAK default output-type (§5.3, §12.3): when non-empty it names an output-types entry id (resolved at M1 — an unknown id fails loudly). It is a weak cross-dimension default: any explicit output-type at L3/L5/L6 beats it. Empty means the platform implies no output-type. Declared as text, not ref, because the schema requires a default for every attribute and the honest floor is "none" — the empty string — which the ref slug alphabet cannot express (§7.4).

### `destination`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

Prose description of where deliverables routed to this platform are published — the "destination" half of §5.3's destination + constraint layer. Routing documentation for humans and review; never a cascade value.

### `format_advisories`

- **type:** `map of map`
- **floor (default):** `{}`
- **definition version:** 1

Per-format ADVISORY constraint projections (§5.3, §12.3): format entry id -> map of advisory values refining advisory_norms for that format on this platform. Merges into the cascade below L5 (map-merge, §12.3); advisory class only (CA9).

### `format_structural`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Per-(format) HARD typed-section conformance (DR-4, §5.3/§12.7/§16): a map of Format entry id -> a section-conformance schema in the `pipeline.sections` C2 vocabulary (presence/ order/count/length; role- or type-axis selectors; error|warning|info severity) that TIGHTENS the Format's base `section_schema` for this venue (optional->required, forbid a section, tighten a per-section bound). A HARD class (CA9 §12.7): an error-severity violation BLOCKS at the reconcile structural gate (C8), the sibling of advisory `format_advisories` and numeric `hard_limits`. M2-EXCLUDED like `hard_limits` — M1-resolved from the platform entry's effective value, never bound as a cascade value and never overridable (an L3/L5/L6 override must not silently relax a hard structural guarantee, SF-1). #4a: per-section NUMERIC limits live HERE (section-addressed), NOT in `hard_limits` (whole-artifact only); a section-limit name is never also a `hard_limits` key (S-3 disjointness). Floor `{}` = no tightening: an unset value rides the L0 floor, is omitted from the §7.2 identity delta, and yields a byte-identical `fit_digest` once the preimage's omit-when-floor structural component lands (C8).

### `hard_limits`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Platform HARD limits (CA9 hard class, §12.7): named physical-feasibility values (e.g. post_char_limit) enforced ONLY at the reconcile pass's terminal gate (§16). Hard limits never enter M2: never bound as cascade values, never overridable.

### `reconcile_strategy`

- **type:** `enum ("adapt", "split", "pass", "truncate")`
- **floor (default):** `"adapt"`
- **definition version:** 1

The reconcile strategy consumed at §16 — an M2-bound render attribute, not a dimension (§12.3). This schema default IS the two-tier defaulting's L0 floor (`adapt`); shipped framework entries never set it (the per-format table below is the other tier). Recipe/run override it at L5/L6; the executed strategy is recorded in the fitted-level fit-binding (§16), and a strategy change against a cached fit is a reconcile-input change (FR2) — loud, never a silent stale reuse.

### `reconcile_strategy_defaults`

- **type:** `map of enum ("adapt", "split", "pass", "truncate")`
- **floor (default):** `{}`
- **definition version:** 1

The per-(format × platform) reconcile-strategy DEFAULT table (§12.3), homed on the Platform entry's per-format projection — Platform is the one dimension that already projects per-format values into the cascade; homing a pair-keyed table on Format would re-couple Format to platforms, which Q4 deleted. Keys are format entry ids; values default the strategy for that pairing, merging below L5.

## `presentations` — schema_version 1

### `csl`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

Per-venue citation-STYLE file — a `.csl` path handed to the writer as `--csl=<path>` so journals differ in citation style from ONE IR (DR-5 C7). A single `text` path, NOT the per-writer `map` of `template`/`reference_doc`: a CSL style is writer-AGNOSTIC. Empty means pandoc's default author-date style — the `plain` floor (PD7). `--citeproc` is CONTENT-driven (it fires whenever the AST cites, §17 R-4 family / C6) and is NEVER gated on this lever — `csl` only OVERRIDES the default style when citeproc is already enabled; a `csl` set on a citation-less render emits nothing (a standalone `--csl` pandoc ignores). The csl is a hashed asset: its content hash rides the serialize preimage ONLY when citeproc ran, so an edited style churns the render digest for citing renders only (§17 FR7.1).

### `css`

- **type:** `list of text`
- **floor (default):** `[]`
- **definition version:** 1

Ordered stylesheet file paths for the html/epub writers (PD2). Order is load-bearing (the CSS cascade), hence an ordered `list`, never a `set` (§11.1). Each file is an asset hashed into the render digest (§17 FR7.1).

### `highlight_style`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

Syntax-highlighting style name handed to the writer (the --highlight-style lever, PD2). Empty means the pinned Pandoc default — the `plain` floor look (PD7).

### `pdf`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

PDF engine + engine options (PD2) for pdf serialization, lowered into RenderInputs.engine (PD3). Empty rides the render target's own engine field; the engine pin joins the RI13 bundle when pdf serializes internally (§17; gate-3 disposition ships pdf external with engine unset).

### `reference_doc`

- **type:** `map of text`
- **floor (default):** `{}`
- **definition version:** 1

Per-writer --reference-doc file paths, keyed by writer name (PD2; the docx/pptx/ odt style carrier). Assets by content hash in the pin bundle (§17 RI13).

### `template`

- **type:** `map of text`
- **floor (default):** `{}`
- **definition version:** 1

Per-writer Pandoc template file paths, keyed by writer name (PD2 per-writer dispatch; pptx has no template — its lever is reference_doc). Templates are assets: cited by content hash in the pin bundle (§17 RI13/FR7.1).

### `variables`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Pandoc template variables applied at serialize (the -V key=value lever class). Fonts and margins ship inside this map (PD2). The guaranteed grow-later hook: bespoke per-writer needs (fixed-layout EPUB, bespoke PPTX) are absorbed additively via writer-keyed submaps (PD8), never a schema change. Snapshotted into the serialize-inputs preimage (§17 FR7.1).

## `recipes` — schema_version 1

### `diagram_style`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The diagram-style entry id this recipe binds (mixed-media increment C; amendment §2.K, Open Item O2) — HOW a `{type=diagram}` section's already-gated node/edge list is DRAWN, never WHICH boxes/arrows exist. Declared as text with an empty floor — not ref — exactly like `topic`/`lexicon`: the honest floor is "unset — draw with the framework `default` style (pinned `dot`)", which the ref slug alphabet cannot express (the `platforms.default_output_type` empty-floor precedent). A non-empty value resolves at M1 against the `diagram-styles` registry (loud on an unknown id, §11.1); its `tool` knob (`dot`/`d2`/`auto`) is threaded onto the compose transform. A diagram-style holds PRESENTATION only — it is honesty-safe by construction (the HARD grounding gate already ran on the author's list, amendment §2.F), rides NO artifact identity (a compile target, not an edge source), and the empty floor churns no artifact id (§7.2).

### `format`

- **type:** `ref`
- **floor (default):** `"short-opinion-post"`
- **definition version:** 1

The Format entry id this recipe binds (§8) — the platform-agnostic genre (§5.2). The floor names the shipped `short-opinion-post`, so the floor always resolves; unknown ids fail loudly at M1 (§11.1). No compatibility data rides this slot (Q4).

### `goals`

- **type:** `set of ref`
- **floor (default):** `[]`
- **definition version:** 1

The goal-set this artifact serves (§5.2: Goal is SET-valued within one artifact; goals STACK, the one fanout exception). Unordered set of goal entry ids, canonicalized (sorted, deduped) into `artifact-id` (§7.1/§12.4); default combine across rungs is REPLACE (§12.4 "the goal-set default is replace" — no `combine:` override here). Goal variants as separate artifacts are a list of goal-sets at selection (§5.2), not a recipe concern. Bound goals contribute their §6.3 clauses at M3's goal-implied layer (§12.1).

### `languages`

- **type:** `set of ref`
- **floor (default):** `[]`
- **definition version:** 1

Optional pinned Language entry ids (§8; §12.3: multiple languages = rendering fanout; Language is mandatory-global CA8, so empty = the L2/L3 default supplies it at run).

### `lexicon`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The house-style Lexicon entry id this recipe binds — the L5 rung of the DR-2 lexicon selection cascade (recipe > workspace default; L6 deferred). Declared as text with an empty floor — not ref — exactly like `topic`: a lexicon carries workspace/recipe-scoped house style (§10) and the framework ships only the generic `house-standard` worked example, so the honest floor is "unset — no lexicon" (the `platforms.default_output_type`/`topic` empty-floor precedent, which the ref slug alphabet cannot express). A non-empty value resolves at M2-compose against the `lexicons` registry (`Resolver.resolve`), loud on an unknown id (§11.1); the empty floor imposes NO lexicon and churns no artifact id (§7.2). A set lexicon enters the `artifact-id` as its resolved `{entry, delta}` over ATTRIBUTES (never the entry body) and supplies the prompt-only compose house-style block (DR-2 §2.2).

### `output_types`

- **type:** `set of ref`
- **floor (default):** `[]`
- **definition version:** 1

Optional pinned Output-type entry ids (§8; §12.3: Output-type is mandatory-global CA8 with a weak platform-implied default beneath explicit values; multiple pins = rendering fanout). Empty = supplied by the cascade at run.

### `persona`

- **type:** `ref`
- **floor (default):** `"technical-evaluator"`
- **definition version:** 1

The Persona entry id this recipe binds (§8) — who the artifact is for (§5.2). The floor names the shipped framework persona `technical-evaluator`, so the floor always resolves; unknown ids fail loudly at M1 (§11.1). The bound persona's `default_voice` enters the Voice chain at its CA2 slot (§12.3).

### `platforms`

- **type:** `set of ref`
- **floor (default):** `[]`
- **definition version:** 1

Optional PINNED Platform entry ids (§8 "may pin rendering targets (else they are supplied at run)"). Platform is per-deliverable routing (CA8); multiple pins = rendering fanout, one deliverable per platform (§5.1). Empty = supplied at run. Pinning here is L5 in the selection cascade (§12.1/§12.3).

### `presentations`

- **type:** `set of ref`
- **floor (default):** `[]`
- **definition version:** 1

Optional pinned Presentation entry ids (§8; PD7: Presentation is NOT mandatory-global — the framework `plain` entry is the schema floor, so empty costs nothing and causes zero id churn). Multiple pins = rendering fanout (§5.1).

### `topic`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The Topic entry id this recipe binds (§8). Declared as text with an empty floor — not ref — because topics are normally workspace-scoped editorial data (§5.2, §10) and the framework ships none: the honest floor is "unset — supplied by the workspace/selection/run", which the ref slug alphabet cannot express (§7.4; the platforms `default_output_type` precedent). Non-empty values resolve at M1 against the topic registries in scope; unknown or still-empty at generation time fails loudly (§11.1) — a recipe generates nothing without a topic.

### `values`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

CONFIGURED VALUES bound at L5 (§8 "configured values"; §12.5 terminology: persistent scopes hold configuration, never "overrides") — attribute bindings applied over the resolved entries at M2, e.g. voice slider tweaks (§5.2: sliders are tunable at recipe/run). Keys are §13.2 operator paths (inline combine operators legal per CM3, e.g. `tags+`); values combine type-driven (§12.4). Consumed by the cascade at step 16.

### `voice`

- **type:** `ref`
- **floor (default):** `"clear-explainer"`
- **definition version:** 1

The Voice entry id this recipe binds — the L5 rung of the §12.3 voice selection chain. A recipe that SETS this beats `persona.default_voice` and the L2/L3 scope defaults (and yields to a §12.6 brand-authoritative value and the L6 run); a recipe that leaves it UNSET lets the chain resolve naturally (CA2) — shipped framework recipes leave it unset for exactly that reason. The floor (`clear-explainer`, a shipped entry) is the L0 last-resort net only (§12.3), never an L5 binding.

## `render-targets` — schema_version 1

### `engine`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

Conversion engine for targets needing one beyond the writer (the PDF engine slot, §17 RI13). Empty = unset. v1 ships `pdf` with engine unset and side external (gate-3 disposition); internalizing pdf = pin an engine here + flip `side` — a config edit, zero rework, with the engine pin joining the RI13 bundle.

### `pandoc_api_version`

- **type:** `list of number`
- **floor (default):** `[1, 23, 1, 2]`
- **definition version:** 1

The pinned Pandoc AST api-version (RI13); the pin of record is the verbatim post-install RI7 printout (step-06 sheet item 3). A persisted AST whose reader-pin digest mismatches the pinned toolchain is re-derived from IR-fitted onto its new key — never misread, never overwritten (§17).

### `pandoc_version`

- **type:** `text`
- **floor (default):** `"3.10"`
- **definition version:** 1

The pinned Pandoc BINARY version this target is certified against (RI13; pin of record: gate step 3 / step-06 sheet item 3). Config-pure — never read from the installed environment — and read literally by the serialize-inputs preimage (§17 FR7.1).

### `reader`

- **type:** `text`
- **floor (default):** `"markdown+fenced_divs+bracketed_spans"`
- **definition version:** 1

The pinned reader + extension set for the single IR-fitted → AST parse (RI7): fenced_divs carries parts, bracketed_spans carries provenance spans. Kept explicit as drift armor even though both extensions are default-on at the pinned binary (step-06 sheet item 3).

### `reference_doc`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The target's own default --reference-doc asset path (RI12), cited by content hash in the render-binding (RI13). Empty = none. Presentation entries may also carry per-writer reference docs (PD2, §5.3); the lowered RenderInputs reconcile the two at dispatch (§17).

### `side`

- **type:** `enum ("internal", "external")`
- **floor (default):** `"external"`
- **definition version:** 1

The §14.2 dispatch setting. internal = call the pinned Pandoc writer in-system (layer-2 bytes). external = persist the AST + emit the layer-3 contract payload (RI14). The floor is external — the route that assumes no in-system toolchain. Excluded from the serialize-inputs preimage (§17 FR7.1): dispatch routing, not a byte-determining input.

### `writer`

- **type:** `text`
- **floor (default):** `"json"`
- **definition version:** 1

The Pandoc writer this target invokes, or `json` for raw-AST passthrough (RI12). The floor is `json`: layer 3 is always produced (RI6), so a target that names no writer hands off the AST itself. Writer names are validated against the pinned binary's writer list at dispatch, not here (capability checks are the dispatcher's, §17).

## `selections` — schema_version 1

### `base`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The base this saved selection's variants are deltas AGAINST (authoring D4) — a recipe (or entry) REFERENCE, kept as a reference and never an inlined copy, so a later edit to the base surfaces HONESTLY as a new artifact id rather than a stale snapshot (reference-faithful, D10). Declared as text with an empty floor — not ref — exactly like `recipes.topic`/`lexicon`: the base may be a workspace-scoped recipe/entry id the framework ships none of, so the honest floor is "unset" (the `platforms.default_output_type` empty-floor precedent, which the ref slug alphabet cannot express). A non-empty value resolves at load against the recipe/entry registries in scope, loud on an unknown id (§11.1); the empty floor imposes no base and churns no artifact id (§7.2). The base name/filename never enters any artifact preimage (D10/W4) — naming or saving a selection cannot change a piece's fingerprint.

### `variants`

- **type:** `list`
- **floor (default):** `[]`
- **definition version:** 1

The EXPLICIT per-artifact variant array (authoring D4) — one `{coordinate, render?, values?}` delta over `base` per resulting deliverable, in the order the saving fan-out produced them. An ORDERED, ALREADY-producted list: reloading drives it 1:1 (each variant resolves to one content combination × its own single render coordinate) and NEVER re-multiplies it, so a curated diagonal reloads to N deliverables, not N×M (the design's no-cartesian guarantee). Per-artifact value tweaks are persisted under the variant's `values` key (§12.5 terminology — persistent scopes hold CONFIGURATION, never "overrides"). The delta interior is UNTYPED in this manifest (an untyped `list`; §11.1 forbids a typed list interior) and is validated at save/load in `pipeline/authoring.py` / `pipeline/plan.py` (authoring C5b/C5c), not by this schema. Empty floor `[]` = a selection with no variants yet; an envelope-only entry rides it and lints + loads (§5.4 one-file-add).

## `sources` — schema_version 1

### `adapter`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The adapter TYPE this instance binds (§6.1: `graphify`, `folder`, `url`, `pdf`, … — an open list; v1 ships graphify + folder, T11). Adapters are framework code declaring query capabilities, not registry entries; an unknown adapter name fails loudly at ground time (step 18). Empty = unbound (never usable).

### `authoritative`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

§6.2 score `authoritative` (scalar 1-5; asserted default per kind; attach: CONTENT-KIND -> per-fact). Vocabulary of record for the kind-tier score whose default bundle lives on content-kinds/ entries (§6.1 SM5). A value set on a source entry is a per-instance user assertion over the kind default (§6.2 — stamped, divergence advisory-linted once, step 17 PA-9a).

### `connection`

- **type:** `map`
- **floor (default):** `{}`
- **definition version:** 1

Adapter-specific bound config (§6.1 "connection details") — e.g. graphify: `path: <client-checkout>/graphify-out/graph.json` (read by path, rule 1; graphs are never stored in this repo). READ-ONLY toward every source (§6.1); must never carry secrets/credentials (§3.3).

### `content_kind`

- **type:** `ref`
- **floor (default):** `"general"`
- **definition version:** 1

The content-kind tag (§6.1 SM5): the content-kinds/ entry whose default score bundle characterizes what this instance's content IS. The floor names the shipped neutral kind `general` (so the floor always resolves); an unknown id fails loudly at M1 resolution (§11.1). Instance-specific deviations from a kind's defaults are `extends:` field-merge partials over the KIND entry (Mechanism 1, §12.1), never edits to shipped entries (§10 rule 2).

### `corroboration`

- **type:** `number`
- **floor (default):** `0`
- **definition version:** 1

§6.2 score `corroboration` (scalar 0-n; DERIVED per-fact: independent-instance agreement after union — recomputed each run, never persisted, §6.1). Upgrades confidence (§6.5); the positive complement of conflict-downgrade. Declared as vocabulary of record and for the §6.2 assertion path; a config-set value is a stamped user assertion (step 17 PA-9a).

### `freshness`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

§6.2 score `freshness` (type of record: date-window/range; DERIVED per-fact from commit/mtime; attach: content-kind policy / per-fact). The config-side carrier is a date-window POLICY/ASSERTION expression in the §6.2/§6.3 predicate vocabulary (e.g. "12mo"); empty = derived only. Serves filter + weight (§6.2); kind-level policy lives on content-kinds/ entries.

### `independence`

- **type:** `enum ("first-party", "affiliated", "independent")`
- **floor (default):** `"first-party"`
- **definition version:** 1

§6.2 score `independence` (ordinal; ASSERTED, machine-hintable; attach: instance -> kind refine). Serves selection (compare, establish-authority) and gates the corroboration upgrade — confidence rises only on agreement across GENUINELY independent instances (§6.5). The floor is `first-party`: the conservative end, so an uncharacterized instance can never fake the independence that corroboration arithmetic rewards.

### `opinionated`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

§6.2 score `opinionated` (scalar 1-5; asserted default per kind; attach: CONTENT-KIND -> per-fact). Vocabulary of record — kind default bundles live on content-kinds/ entries; a value here is a per-instance assertion (§6.2). Not the inverse of `authoritative` (§6.2).

### `primariness`

- **type:** `enum ("primary", "secondary", "tertiary")`
- **floor (default):** `"secondary"`
- **definition version:** 1

§6.2 score `primariness` (ordinal; SEMI-DERIVED; attach: instance -> per-fact refine). Whether this source originates the facts it carries or relays them. Serves selection and conflict tie-break. Floor `secondary` = the uncharacterized middle; asserting `primary` is the user's explicit act.

### `traceability`

- **type:** `bool`
- **floor (default):** `false`
- **definition version:** 1

§6.2 score `traceability` (boolean, optional depth deferred; DERIVED per-fact: a resolvable anchor — file:line, SHA, URL fragment). The citability gate input (§6.5, §19), independent of the confidence tier (SM9: tier ⟂ traceability). Floor `false` = not citable until an anchor resolves; a config-set `true` is a stamped user assertion (§6.2; step 17 PA-9a).

### `trusted`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

§6.2 score `trusted` (scalar 1-5; ASSERTED; attach: instance). The user's standing trust in this source relationship/track record. Serves selection and conflict priority. Floor 3 = uncharacterized middle.

## `topics` — schema_version 1

### `why`

- **type:** `markdown`
- **floor (default):** `""`
- **definition version:** 1

The editorial significance — why this subject matters now, and to whom it is worth saying (§5.2 "plus `why`"). Free prose (wholesale replace on cascade — prose never merges, §12.4). The subject matter itself is the entry's body prose; factual grounding comes from sources at ground time (§6), never from config.

## `voices` — schema_version 1

### `energy`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

Manner slider (§5.2, 1-5): 1 = measured/calm, 5 = urgent/high-tempo.

### `formality`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

Register slider (§5.2, 1-5): 1 = casual/colloquial, 5 = formal/institutional. Slider values map-merge across cascade rungs (§12.3); tunable at recipe/run.

### `guidelines`

- **type:** `markdown`
- **floor (default):** `""`
- **definition version:** 1

Free-text voice guidelines (§5.2): diction, sentence rhythm, what to avoid. Prose never merges — wholesale replace across rungs (§12.4/§12.3).

### `humor`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

Affect slider (§5.2, 1-5): 1 = entirely straight, 5 = playful/witty. Never a didactic lever — reading level is Persona (+ Format), §5.2 guardrail.

### `narrator_persona`

- **type:** `text`
- **floor (default):** `""`
- **definition version:** 1

The narrator stance the writing speaks FROM (§5.2 "narrator-persona") — e.g. "a colleague walking you through it". Distinct from the Persona dimension (who it is FOR, §5.2). Prose; wholesale replace on cascade (§12.4).

### `warmth`

- **type:** `slider`
- **floor (default):** `3`
- **definition version:** 1

Affect slider (§5.2, 1-5): 1 = detached/clinical, 5 = personal/empathetic.
