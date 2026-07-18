# DR-1..DR-6 — FOUNDATION-COHERENCE / cross-DR INTEGRATION pass — Architect (mode: INITIAL)

**Pass:** ops-architect, cross-DR INTEGRATION / foundation-coherence. **Class:** read-only. No repo
edits, no commit. **INTEGRATE and AUDIT the six ratified DRs together; do NOT re-open ratified
decisions** — where integration surfaces a genuine conflict I FLAG it rather than redesign.
**Design/synthesis recommendation only — no code, no implementation plan.**

**Verified this pass against the LIVE SSOT + CODE, not only the reports:** `docs/known-issues.md`
(DR-1..DR-6 + GAP register); the four ratified reconciliations (DR-2 lexicon, DR-3 C3, DR-4/DR-5,
DR-6); `docs/design.md` §5.2/§5.3, §6.4/§6.5, §7.1–§7.4, §11–§13, §14–§19, §21.7/§21.8, §26,
§27.3/§27.4; and the code the DRs touch — `pipeline/ir.py`
(`TOP_LEVEL_KEYS` closed set L139-141; `LEDGER_FIELDS` closed L128-135, `validate_ir` requires
EXACTLY them L510; `_PART_OPTIONAL=("constraints",)` L574 reserved for T7; `IR_VERSION=1` L108 with
exact-equality pin L688-689), `pipeline/ids.py` (`build_artifact_preimage` returns exactly
`{dimensions, goals, source-subset, source-commit}` L667-672; `_require_artifact_preimage_shape`
hard-refuses any 5th top-level key L749-750; `IDENTITY_EXCLUSIONS` L110), and `pipeline/prompts/writer.md`
(the live 5-rule writer contract). (DR-1 is the deferred HTTP shim — not part of the design cluster;
noted only where the build order touches it.)

---

## 0. LEAD VERDICT

**YES — the six DRs form a complete-enough, orthogonal, composable, extensible, and (with two named
refinements) generalized foundation to build on. No residual scope duplication exists (criterion 1):
the DR deliverables own disjoint scopes; the surfaces they SHARE — the closed IR envelope, the
`artifact-id` preimage-shape guard, the §16 reconcile-fidelity list, `writer.md`, and Review-1 — are
COMPOSITION carriers each feature layers onto, not duplicated scopes. The composition is coherent,
not an awkward split (criterion 2): the two load-bearing consolidations (the writer contract and the
§16 fidelity contract) are non-contradictory SUPERSETS in which each layer governs a disjoint
property; their real risk is operational instruction-density on two single `claude -p` agents —
measurable and already mitigated by the design's discipline of pushing every HARD guarantee to
deterministic gates OUTSIDE the LLMs. Extensibility is real (criterion 3), conditional on ONE thing:
the F1 sentinel section-grammar and the shared section-constraint vocabulary must be built as a
SHARED, reusable primitive at DR-4 — not a DR-4-private one — because DR-3's deferred `constraint?`
and DR-4's deferred nested slots both re-consume it. Generalizability holds (criterion 4) with two
Oxford-comma-class refinements to confirm at build: the lexicon `mechanical` carrier and DR-4's
section-`type` must both be OPEN one-file-add carriers, not closed enums.** No integration surfaced a
genuine conflict that re-opens a ratified decision; what integration surfaced is five INTEGRATION
SPECIFICATIONS the cluster-by-cluster passes never had to state because no pass saw all six together.

**The five must-resolve-first integration items (none re-opens a ratified decision):**

1. **`ir_version` generation-tolerant validation is a FOUNDATION, not a DR-6 footnote.** THREE DRs
   edit the closed IR schema (DR-6 ledger `attestation`; DR-5 `references`; DR-4 the conformance
   field). DR-6's ratified bump-to-2 + relax-to-known-compatible-set (additive-optional only) must be
   established FIRST so DR-4/DR-5's later additive envelope edits do not strand old IRs from
   re-reconcile. This is the strongest single argument for DR-6 first.
2. **GAP-4's content-guard known-root fix must land before DR-2's `lexicons/`** — the only NEW
   top-level registry root in the set, and the only one that can hold `provenance: instance`
   (corporate) entries. (DR-3's `formats/outline.md` is a `provenance: framework` entry, not a root.)
3. **The F1 sentinel section-grammar + the shared section-constraint vocabulary must be built SHARED**
   (deliverables 4 + 6). This is the one condition on which DR-3/DR-4 non-divergence AND all their
   deferred extension points rest.
4. **The §16 RI5 reconcile-gate ORDERING must be extended** to place the new DR-4 hard structural
   gate + the DR-6 coverage re-check relative to localize / reshape / the terminal hard-limit gate,
   and to resolve the new joint hard-gate infeasibility case (a §16-required section vs a hard-limit
   truncate → block-and-report). An unspecified sequencing the consolidation surfaces (deliverable 3).
5. **Two writer-contract co-occurrence rules must be specified** (deliverable 2/5): the `[@key]` ×
   grounding-span grammar that classifies bibliographic-vs-grounding citations, AND the DR-6 exemption
   tail — plus the load-bearing rule that **the writer emits `[@key]` markers only and NEVER
   free-authors the `references` bibliography** (a free-authored bibliography is exactly the SF-3
   fabrication vector; `references` must be a projection of the grounding ledger).

Plus two boundary lines to draw precisely at build (criterion-1 residuals, flagged not conflicting):
the lexicon `mechanical` carrier must EXCLUDE structured citation/footnote FORMATTING (that is DR-5's
`csl`); and DR-4's section-conformance field must stay a distinct Format sub-kind, never a
re-description of the §5.2 body-prose skeleton.

---

## 1. THE ORTHOGONALITY MATRIX (criterion 1 — no scope duplication)

**DR deliverable surfaces audited:** DR-2 = `lexicons/` registry (terminology / banned+preferred
terms / casing / spelling / inline house-mechanics) + a `lexicon` selection ref. DR-3 = the editable
Markdown outline (`outline-digest`, `formats/outline.md` genre, emit bridge, drive facets). DR-4 =
the typed-section conformance field (own IR field) + a hard structural class on Platform's per-format
projection + base/reconcile structural gates. DR-5 = `references` (CSL-JSON) + `[@key]` + content-driven
citeproc enablement + a `csl` Presentation lever + a dispatch-layer compatibility check. DR-6 =
self-demarcation coverage gate + `.framing` span class + `attestation?` ledger field +
`grounding_posture` M3 policy + a Review-1 semantic audit.

Legend: **OWN** = sole owner · **CW** = composes-with (rides/extends, no ownership overlap) ·
**MND** = must-not-duplicate (a boundary that must be drawn so the two do not collide) · — = no
interaction.

| DR deliverable | Topic | Persona | Format | Voice | Goal | Platform | Language | Output-type | Presentation | Other DRs | IR / ledger | Reviews |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **DR-2 lexicon** | — | — | CW | **MND (vs Voice via §DR-2 A.1-A.3 firewall)** | — | — | CW (survive localize, §16) | — | **MND (vs Presentation/csl: lexicon excludes structured citation formatting)** | CW DR-5 (inline mechanics ⊂ lexicon); CW DR-6 (lexicon carries no facts, tier-transparent) | CW (+1 preimage component: lexicon entry-id, absent-by-default) | CW (Review-2 preserves applied lexicon) |
| **DR-3 outline** | CW (references topics as leads, asserts none) | — | **CW (per-artifact body skeleton vs Format's reusable default; MND vs `format.parts`, B2)** | — | CW (goals vs the editable content plan; M4 necessity) | — | CW | CW (emits to any output-type via bridge) | CW (renders as ordinary artifact) | **CW DR-4 (outline = section INSTANCE; DR-4 = the typed CONTRACT over it — the unification)** | CW (+1 preimage component: `outline-digest`; emit bridge builds an ordinary `Format=outline` IR) | CW (emitted outline takes normal reviews; no Review-1 for a drive-only scaffold) |
| **DR-4 typed-section conformance** | — | — | **OWN-adjacent (rides Format as a NEW sub-kind; MND vs §5.2 body-prose skeleton)** | — | — | **CW (new hard structural class on Platform per-format projection)** | CW | — | — | **CW DR-3 (contract over the outline instance); CW DR-6 (required-but-ungroundable section → `.framing`, X2)** | CW (OWN conformance field; MND vs reserved `constraints?`/T7, BLK-2) | **CW (new base structural gate @ compose/Review-1 + reconcile structural gate)** |
| **DR-5 citations/style** | — | — | — | — | — | CW (journal = Platform + Presentation, SF-5) | CW (`[@key]` survives localize) | CW (citeproc enablement is content-driven serialize behavior) | **CW (`csl` = Presentation lever; enablement ≠ style)** | **CW DR-6 (formatting vs grounding split; `[@key]` bridge, deliverable 5); CW DR-2 (inline mechanics stay lexicon)** | CW (+`references` top-level key; body-blind — ZERO preimage component) | CW (Review-2 preserves `references`+`[@key]`) |
| **DR-6 grounding** | — | — | — | — | CW (a goal may demand grounded substance; §6.5 floor wins, X2) | — | CW (attribution survives localize) | — | CW (attribution must survive §17 strip per writer) | **OWNS grounding CORRECTNESS channel-agnostically; ABSORBS the DR-2/DR-3/DR-4-5 per-feature grounding flags** | **CW (ledger `attestation?` via LEDGER_OPTIONAL; ZERO preimage component; `.framing` §17 strip decision)** | **CW (HARD coverage gate @ compose + semantic audit @ Review-1)** |

**Proof of no residual scope duplication.** Every cell is OWN, CW, or a drawn MND boundary — **no cell
is a silent scope overlap.** The DRs' deliverables partition cleanly:

- **Grounding is the strongest anti-duplication result in the set.** DR-6 explicitly ABSORBS the
  three per-feature grounding flags (DR-2's "no compose hard gate that fact-claims cite EXTRACTED",
  DR-3 B1, DR-4/5 SF-3) into ONE channel-agnostic property of every compose leaf, one chokepoint.
  Without DR-6 first, DR-2/3/4/5 would each re-grow a grounding flag — the exact duplication criterion
  1 forbids. DR-6 owning grounding correctness while DR-5 owns citation FORMATTING (`csl`) is the
  clean formatting-vs-correctness split.
- **Identity surface is disjoint.** Only DR-2 (lexicon entry-id) and DR-3 (`outline-digest`) add
  `artifact-id` preimage components — distinct components, each absent-by-default (zero churn,
  §7.2). DR-4/DR-5/DR-6 add ZERO preimage components (conformance rides Format delta + `outline-digest`;
  `references` is body-blind; `csl` rides the existing `presentation` coordinate; `attestation` is
  ledger, not preimage — verified: the preimage is `{dimensions, goals, source-subset, source-commit}`,
  ids.py L667-672, and the ledger is NOT in it).
- **The SHARED surfaces are composition carriers, not duplicated scopes** (this is the criterion-1 ⟂
  criterion-2 line): (a) the closed IR envelope — DR-5 adds `references`, DR-4 adds a conformance
  field, DR-6 changes the `grounding` sub-schema; the keys are DISJOINT (verified against
  `TOP_LEVEL_KEYS`), but all three co-edit `ir.py` — a build-coordination fact, not a scope overlap;
  (b) the frozen preimage-shape guard (ids.py L749-750) — DR-2 + DR-3 each extend it, disjoint
  components; (c) the §16 fidelity list (deliverable 3); (d) `writer.md` (deliverable 2); (e)
  Review-1 (DR-4 + DR-6). Multiple features layering onto one carrier is COMPOSITION; two features
  claiming one scope is DUPLICATION. There is none of the latter.

**Two MND boundaries to draw precisely at build (flagged, not conflicts):**

- **DR-2 lexicon `mechanical` vs DR-5 `csl` — the footnote-format boundary.** DR-2's original scope
  named "style-guide-adjacent rules like footnote format"; DR-5 homes structured citation/footnote
  FORMATTING in `csl` (render, per-venue). The lexicon `mechanical` carrier MUST exclude
  structured-citation/footnote formatting (DR-5's) and carry ONLY inline prose mechanics (Oxford comma,
  spelling, number/date style). If the lexicon schema lets an author encode footnote-format rules,
  it duplicates `csl`. Draw the line at structured-vs-inline: structured citation data → `csl`
  (render); inline prose mechanics → lexicon (compose). (This IS the DR-5 discovery, applied to the
  lexicon schema shape.)
- **DR-4 conformance field vs Format §5.2 body-prose ownership.** DR-4's conformance is DECLARED on
  Format but is a DISTINCT sub-kind (typed structural constraints) from Format's rhetorical body-prose
  description. Keep it a distinct Format attribute (one-file-add), never a second re-description of the
  §5.2 skeleton — else Format's "owns rhetorical structure" and DR-4's conformance blur.

**One integration RESULT worth stating (coherent, not a conflict): the unified precedence chain.**
The cluster passes each stated their side; together the chain is: **the outline (DR-3) outranks the
dimensions for content/structure CHOICE (B2), but the outline is the INSTANCE that must SATISFY the
resolved DR-4 conformance ENVELOPE, which is a hard GATE (not a cascade value the outline can
override) — the same way the outline cannot override the §16 hard-limit gate.** Conformance is
resolved by the cascade (Format base ∪ Platform tightening, most-local-wins on constraint values);
the outline fills it; the structural gate blocks on violation. Orthogonal and coherent: outline >
dimension-VALUES; gates > everything.

---

## 2. THE CONSOLIDATED WRITER CONTRACT (criterion 2 — the load-bearing "awkward split" risk)

Four DRs layer requirements onto the single `claude -p` writer (`writer.md`): DR-6 self-demarcation,
DR-3/DR-4 section structure/conformance, DR-2 lexicon adherence, DR-5 citation markers — on top of the
live 5-rule base contract. **Assessment: this is ONE coherent, non-contradictory contract — a
SUPERSET, not an awkward split — because each layer governs a DISJOINT property of the same prose.**
It is, however, operationally HEAVY, and the writer is empirically framing-sensitive (GAP-8: a static
header derailed 3/8 runs). The risk is density, not contradiction.

**The ONE consolidated contract, as an ordered layer stack (each governs a disjoint property):**

| # | Layer | Governs | Source | Nature |
|---|---|---|---|---|
| 0 | **Base** — emit JSON `{body}`/`{parts}`; only listed fact-ids; never promote tier; ground specifics; no secrets | tier-fidelity + shape | live `writer.md` | HARD (re-ask) |
| 1 | **DR-6 coverage** — every DECLARATIVE prose unit is a grounding span `[…]{.TIER data-fact}` OR an explicit `.framing`/`.rhetorical` span; nothing bare; exemption tail (headings/list-markers/table-cells/code/math + DR-4 non-text section kinds) | coverage FORM | DR-6 | HARD (deterministic compose gate → re-ask) |
| 2 | **DR-3/DR-4 structure** — produce the sections the readable outline BRIEF specifies (honoring drive facets `use-sections?`/`use-order?`/`intents-must-cover?`), delimited by the F1 sentinel grammar, satisfying the resolved typed-section conformance | the section PLAN | DR-3/DR-4 | structure advisory to writer; conformance HARD at the gate |
| 3 | **DR-2 lexicon** — apply preferred/banned terms, casing, spelling, inline mechanics to all prose WITHOUT altering any grounded claim's meaning | PHRASING | DR-2 | advisory (Review-2 preserves) |
| 4 | **DR-5 citations** — emit `[@key]` markers for bibliographic references, composing with layer-1's span grammar per the co-occurrence rule below | reference MARKERS | DR-5 | advisory |

**Why it is coherent (no contradiction).** Layer 1 governs coverage-form; layer 2 the section-plan;
layer 3 phrasing; layer 4 reference-markers; layer 0 tier-fidelity. These are orthogonal properties of
one prose body — a claim can be simultaneously grounded (0/1), in the right section (2), phrased per
the lexicon (3), and carry a citation (4) with no rule contradicting another. The one cross-layer
interaction — layer 3 must not change a grounded claim's MEANING (0/1) — is a priority order (meaning
> phrasing), not a contradiction. The required-section-with-no-facts case (2 × 1) resolves cleanly:
the writer fills it with honest `.framing` prose (X2). **The combined instruction set is
non-contradictory for one `claude -p` writer.**

**Three specifications the consolidation REQUIRES (else the split becomes awkward):**

1. **The `[@key]` × span co-occurrence grammar (ties to deliverable 5).** A grounding span
   `[text]{.TIER data-fact}` and a citation `[@key]` are BOTH bracketed constructs. The contract must
   define co-occurrence: **a `[@key]` bound to / inside a grounding span is a GROUNDING citation
   (resolved via the fact's ledger entry); a BARE `[@key]` is purely-bibliographic** (K1, deliverable
   5). This co-occurrence IS the classifier that sorts K1/K2/K3. Pandoc parses a Cite nested in a Span
   legally, but the writer must be told the exact form. Unspecified, this is a GAP-8-class
   framing-ambiguity risk.
2. **The writer emits `[@key]` markers ONLY; it NEVER free-authors the `references` bibliography.** A
   writer-authored CSL bibliography is precisely the SF-3 fabrication vector (an LLM-invented work
   shipped as authoritative). The `references` block must be a pipeline-built PROJECTION of the
   grounding ledger. State this in the contract explicitly — it is the point where SF-3's
   grounding-coupling is either honored or defeated at the writer.
3. **The DR-6 exemption tail must be reconciled with DR-4's non-text section kinds.** A whole-section
   figure/table (a DR-4 `type`) is non-declarative-prose → exempt from layer-1 demarcation. The
   exemption set is not a generic "headings/lists/code/tables/math"; it must cover DR-4's non-text
   section kinds by construction (ties deliverables 6/7).

**Verdict.** Coherent superset, NOT an awkward split. The real risk is operational: five layered
instruction sets on a known-framing-sensitive writer. Mitigation is already in the design's grain —
the ONLY HARD gate the writer must satisfy is deterministic (layer 1's coverage check + layer 0's
substance floor + fact-id validity), run OUTSIDE the writer via the existing bounded re-ask
(`compose.py`, "the ONLY re-ask point"); layers 2-4's structural/phrasing/citation quality are
advisory (Review-1/2). **Recommendation: build the writer-contract layers in the DR build order and
ABLATE after each addition** (the F4 / GAP-8 discipline), so density is measured, not assumed — do
not land all four layers unmeasured in one prompt.

---

## 3. THE CONSOLIDATED §16 RECONCILE-FIDELITY CONTRACT (criterion 2)

The reconcile LLM (a `claude -p` product agent) must, through reshape / split / localize / truncate,
simultaneously honor the accumulated obligations below. Enumerated as ONE set with enforcement class:

| # | Obligation | Source | Enforcement | Where |
|---|---|---|---|---|
| i | Preserve voice + content parameters | base §16 | advisory | Review-2 |
| ii | Preserve meaning | base §16 | advisory | Review-2 |
| iii | Preserve per-claim provenance/tier, re-anchored; never promote a tier | base §16 / §6.5 | tier floor HARD (§6.5 invariant); re-anchor advisory | §6.5 structural + Review-2 |
| iv | Preserve the applicable lexicon rules | DR-2 S4 | advisory | Review-2 |
| v | Preserve typed-section conformance AND ENFORCE the platform-specific hard structural class | DR-4 SF-1 | **HARD structural gate** (forbid/require section → BLOCK) | new reconcile structural gate |
| vi | Preserve the `references` block + inline `[@key]` markers (a split can shatter a citation; localize can mangle `[@key]`) | DR-5 SF-2 | advisory | Review-2 |
| vii | Preserve the scenario-2 `attestation` + a strip-surviving attribution that NAMES pool source S | DR-6 §5.2/5.3 | HARD@compose; advisory@reconcile WITHOUT self-demarcation; **deterministic@reconcile WITH self-demarcation** (the no-bare-declarative gate re-runs on the fitted body) | Review-2 or the DR-6 coverage re-check |
| — | The pre-existing terminal hard-LIMIT gate (fit-or-block on numeric/capacity limits) | §16 RI5 | HARD | terminal gate, last |

**Coherence + enforceability assessment.**

- **The obligations are NON-CONTRADICTORY.** The advisory-preserve obligations (i, ii, iv, vi, and the
  re-anchor half of iii) govern DISJOINT properties (voice, meaning, phrasing, citation data,
  provenance placement). The HARD gates (v structural, vii under self-demarcation, iii's tier floor,
  and the terminal limit gate) all resolve infeasibility to the SAME action — block-and-report — so
  they cannot deadlock. The DR-4×DR-6 apparent deadlock is false (X2: both → block; §6.5 floor
  precedence). The one lexicon-vs-meaning tension is a priority order (meaning > lexicon phrasing),
  not a contradiction.
- **A NEW joint-infeasibility case the consolidation surfaces (flag, not conflict): hard-STRUCTURAL ×
  hard-LIMIT.** A `truncate` needed to fit a hard word-limit may have to drop a section DR-4 requires.
  The two hard gates are then jointly unsatisfiable → **block-and-report naming BOTH constraints.**
  Both gates independently want block, so there is no contradiction — but the reconcile outcome must
  surface the combined reason (the §21.7 code set already supports per-item block; add a combined
  DR-4×§16 context).
- **The RI5 ORDERING must be extended (must-resolve-first item 4).** §16 RI5 today is
  localize → reshape → terminal hard-limit gate (last, because localize alters length). The
  consolidation inserts (v) a structural gate (after reshape, since reshape adds/drops sections) and,
  under self-demarcation, (vii) a coverage re-check. The ordering of {structural gate, coverage
  re-check, terminal limit gate} is UNSPECIFIED and matters (a structural-required section that the
  limit-truncate then drops). Extend RI5 to place them and to define the joint-infeasibility block.
  This is the concrete integration gap the fidelity consolidation exposes.

**Tractability verdict (the real risk).** The contract IS tractable, but it is an ACCUMULATING
product-plane agent burden (the §16 whole-picture item 4.1): a single `split` must now keep voice,
meaning, provenance, lexicon, section conformance, citations, and attestation coherent at once. The
design has the RIGHT shape for this: **every HARD guarantee lives in a DETERMINISTIC gate OUTSIDE the
reshape LLM** (the terminal limit gate; the new structural gate; and — the decisive reason to prefer
DR-6 Option C self-demarcation — the coverage re-check makes attribution-survival deterministic at
reconcile rather than resting on the advisory Review-2). The LLM's job stays "reshape + advisory-
preserve"; failures are caught by Review-2, never shipped. Register the full 7-item set at §27.4 and
flag the accumulation as a standing product-agent-reliability risk — no longer a per-pass footnote.

---

## 4. THE SHARED CONSTRAINT VOCABULARY — DR-3 ↔ DR-4 (criteria 1 + 3)

DR-3's outline `constraint?` (deferred v1) and DR-4's typed-slot constraints were flagged "one
vocabulary" but never specified as one. DR-4 un-defers DR-3's machine-section-parse (the F1 sentinel
grammar) — which is exactly the addressing DR-3's `constraint?` needs. **They MUST be ONE vocabulary,
built as a single shared schema fragment, consumed at three binding sites.** Specified now so they
cannot diverge:

**The ONE section-constraint vocabulary (v1 = whole-section granularity):**

- **Addressing:** sections are delimited by the **F1 sentinel grammar** — boundaries drawn only from
  sentinel lines content cannot forge (DR-3 §07 F1) + a structural fidelity check above any byte
  check (F5). A section carries a local `section-key` (slug/index). This ONE addressing mechanism is
  shared by the outline (DR-3) and the conformance schema (DR-4).
- **`type`** — section kind (`prose | abstract | methods | figure | table | callout | references | …`).
  **Must be an OPEN one-file-add carrier** (see deliverable 7), not a frozen enum. A whole-section
  non-text kind (whole-section figure/table) is v1; nested-in-prose slots deferred.
- **Cardinality:** `?` optional · (bare = required) · `*` zero-or-more · `{n,m}` bounded — presence/
  repetition of a section.
- **Constraint menu:** per-section predicates — `required | forbidden | ordered | min/max length
  (words/chars) | element-count | min/max count`. One-file-add extensible.
- **Severity:** `error | warning | info` — **error = BLOCK** (the maintainer's HARD structural class);
  warning/info = advisory. Shared semantics at every site.

**The three binding sites, ONE vocabulary:**

1. **Format base section-spec** (the genre's own required/typical sections) — DR-4, cascade-resolved.
2. **Platform per-format tightening** (per-venue hard structural class; "journal B forbids
   acknowledgements" = severity error) — DR-4, merges below L5 like advisory constraints but as the
   hard class, most-local-wins on the constraint values.
3. **Outline `constraint?`** (per-artifact, DEFERRED) — DR-3. When it lands it lets the OUTLINE carry
   per-section constraints, using the SAME fragment; the outline instance must SATISFY the resolved
   (1)∪(2) envelope (it may tighten within it, never violate it — the precedence chain of §1).

**Anti-divergence contract (the load-bearing specification):**

- Define the vocabulary ONCE as a shared schema fragment (a `section-constraint` type in the schema
  machinery), REFERENCED by the DR-4 conformance field (sites 1+2) and — when it lands — the DR-3
  outline `constraint?` (site 3). Never copy-paste.
- The F1 sentinel section-grammar is the ONE addressing mechanism all three use; sections are
  identified identically in the outline and in the conformance schema.
- Severity semantics (error=block) and the one-file-add extensibility of `type` + the constraint menu
  are shared across all sites.
- **The RISK if not done:** DR-4 ships the grammar now (un-deferring F1); a LATER pass for DR-3's
  `constraint?` could invent a parallel outline-constraint grammar → divergence + a second F1 solve.
  Mitigation = register the deferred `constraint?` as a CONSUMER of the DR-4 fragment (not a new
  grammar) at DR-4 build time. This is also condition 3 of the lead verdict.

---

## 5. THE DR-5 ↔ DR-6 `[@key]` BRIDGE INTERFACE (criteria 2 + 3)

Specify the contract NOW (build deferred to DR-5's resumption) so the two compose cleanly. The
verified collision (DR-6 X1): DR-5's CSL renders `[@smith2020]` as "(Smith 2020)" — a DIRECT cite to
the out-of-pool primary B — but DR-6 requires a strip-surviving attribution to the POOL secondary S.
DR-6 binds to the LEDGER (fact-ids, which exist today); the `[@key]`/`references` channel is DR-5's
and is paused — so DR-6 must not make its correctness gate depend on it. The bridge:

**Classify every `[@key]` at compose into three kinds (the classifier IS the writer co-occurrence
rule of deliverable 2):**

- **K1 — purely-bibliographic.** Cites the literature for rhetorical context; asserts nothing as
  pipeline fact. A BARE `[@key]` (no grounding-span binding). OUT of DR-6's scope entirely; styled by
  CSL (DR-5) as an ordinary cite. No attestation, no S-attribution.
- **K2 — scenario-1 grounding citation.** Backs a claim whose primary IS in the pool. The `[@key]` is
  bound to a grounding span → resolves to a ledger fact (EXTRACTED). CSL styles it; the pool source is
  the cited work. No attestation needed.
- **K3 — scenario-2 grounding citation (the load-bearing case).** Backs a claim whose primary (B) is
  NOT in the pool but is attested by pool source S. Requires (a) a ledger `attestation` entry
  (`primary`=B as a citation descriptor, `anchor`→held pool source S, `relation`=PROV-O `wasQuotedFrom`)
  AND (b) a published attribution that NAMES S and SURVIVES the §17 strip.

**The K3 contract (the interface both sides implement):**

- **Binding (DR-6 owns; DR-5 builds the map).** A grounding `[@key]` (K2/K3) MUST resolve to a ledger
  fact-id; a K3 one to a fact carrying an `attestation`. No CSL-key→ledger-fact-id map exists today —
  **DR-5, on resumption, builds it** (e.g. the `[@key]` span co-carries a `data-fact` binding, or the
  `references` entry records the fact-id). DR-6's gate binds to the ledger it already has; it does NOT
  gate on the paused CSL channel.
- **Surface (DR-5 owns HOW, subject to two DR-6 properties).** The published bytes for the target
  writer must carry an attribution that (a) NAMES/points to S — not merely cites B — and (b) SURVIVES
  the §17 fail-closed strip for that writer. **CSL-citing-B ALONE fails (a).** So a K3 surface must be
  an INDIRECT citation form (CSL "B, as cited in S") where S renders as surviving content. Note
  `data-cites` names the CSL key (B), not S, so it alone also fails (a) even though it survives (MN-2).
- **v1 realization (DR-5 paused, no `references` channel yet).** The only surface that satisfies BOTH
  properties today is PROSE ("According to S, B reports X") — **not because DR-6 mandates prose, but
  because prose is the only strip-surviving, S-naming channel that currently exists.** When DR-5 lands
  the CSL channel, it MAY add an indirect-citation surface that names S and survives; DR-6's
  obligation is unchanged (name-S + survive-strip).

**This is a genuine NEW coupling** (every K3 grounding-`[@key]` ⇒ a ledger attestation + a
non-CSL-alone attribution surface naming S), flagged here as a HARD constraint DR-5 must satisfy on
resumption — clean composition and a named extension point (criteria 2+3). It does not block the
DR-6-first build: DR-6 ships the ledger `attestation` + self-demarcation + the v1 prose realization
WITHOUT the `[@key]` bridge; DR-5 later adds the channel + the map + the indirect surface.

---

## 6. THE EXTENSION-POINT REGISTER (criterion 3 — less-designed but easily extensible = REAL)

| Deferred element | DR | NAMED extension hook | Rides already-designed machinery? |
|---|---|---|---|
| Nested-in-prose typed slots (figure-with-caption inside a section body) | DR-4 | "the nested tier" — slot-typing grammar inside a section's prose, over the same F1 sentinel/section grammar | YES (the shared vocabulary + F1) — **conditional** |
| Whole-part typed sub-output (the (a) fallback: a standalone typed table-part) | DR-4 | per-part typed constraints take their OWN part field, never the T7-reserved `constraints?`; MN-1 aliasing asterisk registered | YES (own part field) |
| Outline `constraint?` (per-section outline constraints) | DR-3 | additive fenced-block/sidecar consuming the DR-4 shared section-constraint vocabulary (deliverable 4) | YES (shared vocabulary + F1) — **conditional** |
| Multi-part / per-part outline scoping | DR-3 | per-part outline over `format.parts` roles + the section-grouping shape + F1 sentinel grammar | YES (the emit bridge is single-part; multi-part is additive) |
| The `references` (CSL-JSON) channel + `[@key]` binding | DR-5 | extend `TOP_LEVEL_KEYS` with `references` (a CSL-JSON validator) + thread into AST-`meta` + the CSL-key→ledger-fact-id map (deliverable 5) | YES (same loud closed-envelope change DR-3 made for `outline-digest`) |
| Option-B pre-persist per-leaf `claude -p` verifier | DR-6 | opt-in escalation, AFTER measuring `claude -p`-as-verifier reliability; the combined posture does not need it | YES (pure lever; no default path change) |
| The self-demarcation exemption tail (headings/lists/code/tables/math + DR-4 non-text kinds) | DR-6 | a named, versioned part of the `writer.md` contract + the compose block-parse | v1 item if Option C adopted; measurable |
| `grounding_posture: warn \| block` policy | DR-6 | recipe/workspace policy field on the M3 config cascade, provenance-aware, non-identity | YES (existing M3 cascade + provenance guard) |
| Language/localization GA | §26 | the reconcile localize slot + the §16 fidelity list (deliverable 3) — lexicon/references/attestation all must survive localize | YES (slot + fidelity designed) |
| One-shot journal-selectable sugar | DR-4 SF-5 | a thin rendering-only selectable pinning `{platform, presentation}`, registered like the brand pack (§26) | YES (binds no content; never collides with the content-side guide) |
| §12.6 lexicon-lock | DR-2 S3 | extend `authoritative` to a lexicon scope-default (category-safe: compose-only, no straddle); a §12.6 amendment | YES (existing §12.6 mechanism) |

**Verdict: extensibility is REAL, not hoped — with ONE load-bearing condition.** Almost every deferred
element rides ALREADY-DESIGNED machinery (F1 sentinel grammar, the shared constraint vocabulary, the
closed-IR-additive pattern, the M3 config cascade, the LEDGER_OPTIONAL pattern, the emit bridge). The
condition (rows marked "conditional"): the F1 sentinel section-grammar + the shared section-constraint
vocabulary must be built as a SHARED, reusable primitive at DR-4 — NOT a DR-4-private one — or the
later DR-3 `constraint?` and DR-4 nested-slot extensions re-open F1's byte-vs-meaning + whitespace/
nesting hard problems SEPARATELY. Build it shared once; the deferrals are then clean drop-ins.

---

## 7. THE GENERALIZABILITY AUDIT (criterion 4 — no over-specific landing)

Auditing each landing for the Oxford-comma-class over-specificity (an example that had to be
generalized to a carrier):

| Landing | Verdict | Reasoning |
|---|---|---|
| **DR-5 `csl` lever** | **GENERAL (the model generalization)** | Uses the CSL standard's own OPEN style space — one-file-add a new `.csl` asset → a new citation style, no schema break. This is the POSITIVE example: DR-5 correctly generalized "per-venue footnote format" to a `csl` asset carrier rather than hardcoding footnote-format rules. |
| **DR-3 `drive` facets** (`use-sections?`/`use-order?`/`intents-must-cover?`) | **GENERAL** | The DR-2×DR-3 reconciliation replaced a 3-value `drive` enum with orthogonal booleans (M3) — a generalization away from an either/or enum. |
| **DR-6 `attestation.relation` (PROV-O)** | **GENERAL** | PROV-O is a standard vocabulary (`wasQuotedFrom`, …), not a hardcoded one-relation enum. v1 is deliberately narrow (one relation) but the carrier is open. |
| **DR-4 severity `error\|warning\|info`** | **GENERAL enough** | Standard lint-severity triple; low extension pressure. |
| **Lexicon `mechanical` menu** | **FLAG — confirm OPEN carrier, not a closed enum** | If `mechanical` is a fixed enum `{oxford_comma, spelling, number_style, date_style}`, adding a new house rule needs a schema change — violating one-file-add, the EXACT Oxford-comma over-specificity DR-6 corrected. The lexicon schema must carry mechanical rules as a general, extensible structure. ALSO: draw the boundary so `mechanical` EXCLUDES structured citation/footnote formatting (DR-5's `csl`) — see §1. |
| **DR-4 section-`type` "enum"** | **FLAG — generalize to a one-file-add carrier** | An enum is closed by nature; a new journal's novel section kind (`data-availability-statement`, `structured-methods`) must be ADDABLE as one file, like the `on_conflict` strategy LIST (SM4: "selectable, extensible LIST … one-file-add") or the content-kinds registry — NOT a frozen framework enum. Otherwise DR-4 fails the one-file-add acceptance test (§5.4) the moment a venue needs an unlisted section kind. |
| **DR-6 `grounding_posture` two-value policy** | **LOW-RISK** | A `warn\|block` policy; a future third posture (`abstain`, `escalate`) is a one-value schema add. Keep the field extensible; not urgent. |

**Verdict: generalizability holds, with TWO Oxford-comma-class refinements to confirm at build** — the
lexicon `mechanical` carrier and DR-4's section-`type` must both be OPEN one-file-add carriers, not
closed enums. Both are specification refinements confirming criterion 4, not re-opened decisions. The
`csl` lever and the `drive` facets are the model of how it should be done.

---

## 8. THE FINALIZED BUILD ORDER + CROSS-CUTTING DEPENDENCIES (criterion 3)

**CONFIRMED order (the task's DR-6 → DR-3/DR-4 → DR-5 → DR-2, refined):**

```
FOUNDATION (before/with DR-6):
  F-a  ir_version bump-to-2 + generation-tolerant validation (additive-optional only)   [DR-6 owns]
  F-b  GAP-4 content-guard known-root fix                                                [gates DR-2]

DR-6   grounding: self-demarcation coverage gate + `.framing` span + writer.md layer-1
       + ledger `attestation?` (LEDGER_OPTIONAL) + `grounding_posture` M3 policy
       + Review-1 semantic audit                    [FIRST — owns the grounding invariant + F-a]
  │
DR-3   outline: holistic Markdown canonical + `outline-digest` (preimage guard extension #1)
       + `formats/outline.md` + emit bridge + drive facets                     [editable intermediate]
  │
DR-4   typed-section conformance: BUILD the F1 sentinel grammar + the SHARED section-constraint
       vocabulary (deliverable 4) + own IR conformance field + Platform hard structural class
       + base(compose/Review-1) & reconcile structural gates (extend RI5 ordering)   [un-defers DR-3 §07 F1]
  │
DR-5   citations/style: `references` (TOP_LEVEL_KEYS) + `[@key]` + content-driven citeproc
       enablement + `csl` Presentation lever + dispatch compatibility check
       + the DR-5↔DR-6 `[@key]` bridge (deliverable 5)                          [needs DR-6 ledger + DR-4 Platform]
  │
DR-2   lexicon: `lexicons/` registry (needs F-b) + `lexicon` ref (preimage guard extension #2)
       + writer.md layer-4 + §16 fidelity obligation                            [LAST — lightest writer layer]
```

**Dependency justifications (each pressure-tested):**

- **DR-6 FIRST — three independent reasons.** (1) It OWNS the grounding invariant DR-2/3/4/5 all defer
  to; building them first re-grows the three per-feature grounding flags DR-6 absorbs (criterion-1
  duplication). (2) It owns the `ir_version` generation-tolerant validation (F-a) that DR-4/DR-5's
  later additive envelope edits must ride — establish the multi-generation reader BEFORE the second
  and third envelope edits, or old IRs strand from re-reconcile (verified: `IR_VERSION=1` exact-equality
  pin, ir.py L688-689). (3) It lays writer-contract layer 1 (the HARD gate) FIRST, so the framing-
  sensitivity impact is measured before structure/lexicon/citations pile on. DR-6's scenario-2
  `[@key]` binding is deferred to DR-5 (deliverable 5) — order-compatible: DR-6 ships bound to the
  ledger it has.
- **DR-3 before DR-4, as a tight UNIT.** DR-4 un-defers DR-3's machine-section-parse — DR-3 ships the
  holistic outline + `outline-digest` + emit bridge (the editable intermediate); DR-4 then BUILDS the
  F1 sentinel grammar + the shared vocabulary ON TOP. Building DR-3 holistic and DR-4 much later would
  invent the outline's section-addressing twice. Verified additive: the `outline-digest` is over whole
  normalized Markdown; DR-4 parses sections from it via the sentinel grammar without changing the
  digest. DR-6 must precede DR-4 (a required-but-ungroundable section → `.framing`, X2; and the
  reconcile structural gate slots into RI5 alongside DR-6's coverage re-check).
- **DR-5 THIRD.** Needs DR-6's ledger `attestation` (the `[@key]` bridge resolves `[@key]`→ledger-fact-id
  →attestation, deliverable 5) AND DR-4's Platform hard structural class (journal = Platform + Presentation,
  SF-5). Its citation writer-layer is the last major `writer.md` addition.
- **DR-2 LAST.** Its `lexicons/` is gated on F-b (GAP-4). Its compose-vs-render placement was REOPENED
  by DR-5 and SETTLED by DR-5's ratified design (inline mechanics stay compose-baked) — so DR-5 first.
  Its lexicon entry-id is the SECOND preimage-guard extension (rides DR-3's guard change). It is the
  lightest writer layer. (DR-2 is dependency-light beyond F-b + the settled DR-5 placement; it COULD
  float earlier if F-b lands up front, but LAST is clean.)

**Cross-cutting dependencies confirmed:**

- **The shared preimage-shape guard is extended TWICE** (ids.py L749-750): DR-3 (`outline-digest`) then
  DR-2 (`lexicon` entry-id). Both absent-by-default → zero churn (§7.2). DR-3 first establishes the
  extension pattern; DR-2 rides it. Both are §7-authority changes needing the maintainer gate.
- **The closed IR envelope is co-edited by THREE DRs** (ir.py `TOP_LEVEL_KEYS`/ledger/part-shape):
  DR-6 (ledger schema → LEDGER_REQUIRED+OPTIONAL), DR-4 (conformance field), DR-5 (`references`).
  DISJOINT keys, each an additive-optional bump riding F-a. This is the single most co-edited file —
  a build-coordination note, sequenced by the order above.
- **The `writer.md` contract (deliverable 2) and the §16 fidelity contract (deliverable 3) accumulate
  across ALL DRs** — re-validate/ablate after each layer (GAP-8 discipline); do not finalize either
  until DR-2 lands.
- **The RI5 reconcile-gate ordering (must-resolve-first item 4) is settled at DR-4** — when the
  structural gate joins DR-6's coverage re-check and the terminal hard-limit gate.

---

## 9. Closing — no genuine conflict; five integration specifications

Integration surfaced **no genuine conflict that re-opens a ratified decision.** Every apparent
tension resolves coherently: the outline-vs-conformance precedence is a clean chain (outline >
dimension-values; gates > everything); the DR-4×DR-6 deadlock is false (both → block, §6.5 floor
wins); the hard-structural × hard-limit joint case is a new BLOCK case both gates already want; the
identity extensions are disjoint and zero-churn; the co-edited IR envelope carries disjoint keys. What
the cluster-by-cluster passes never had to state — because none saw all six together — is FIVE
integration specifications (lead verdict) + TWO boundary lines (lexicon-`mechanical` ⟂ `csl`;
DR-4-conformance ⟂ Format §5.2) + TWO generalizability refinements (open `mechanical` + open
section-`type`). All are INTEGRATION work within the ratified frame; none is a redesign.

**Recommendation to the maintainer gate:** the DR set is a sound foundation to build on in the
confirmed order, PROVIDED items 1-5 of the lead verdict are treated as build-entry conditions — most
critically (1) the `ir_version` generation-tolerant validation as a FOUNDATION before the second IR
envelope edit, and (3) the F1 sentinel grammar + shared section-constraint vocabulary built SHARED at
DR-4. With those, "less-designed but extensible" is real, the composition is coherent, and there is no
residual scope duplication across all six.

*End of foundation-coherence report. Read-only; no code, no implementation plan; INTEGRATION not
redesign. The maintainer gate runs next.*
