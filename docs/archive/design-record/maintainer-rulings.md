<!-- PROVENANCE HEADER — added at import, 2026-07-11 -->

> **Provenance:** This is the decision record behind `docs/design.md` — the full sequence of
> maintainer rulings (Q-, F-, SM-, RS-, CA-, BO-, CM-, SV-, MIG-, RI-, PD-, API-, PC-, D1-series,
> the folio DIRECTIVE, the Phase-A rulings A4-1..A4-4, the Phase-B rulings including B4-1..B4-5,
> and the force-re-reconcile package) produced by the ruled design process described in
> `docs/design.md` §1. It was imported verbatim from the design-pass handoff per the approved
> placement package (A4-2; `docs/design.md` Appendix B §B.1) as the provenance trail behind
> Appendix A. It is **history, not authority**: on any conflict with `docs/design.md`, the design
> document wins. Scanned at import for instance/client-specific content per durable rule 4 —
> framework-generic throughout; nothing redacted.

---

# Maintainer rulings — definitive-design decision-review

Input for the reconciliation architect. Each entry records the decision, the maintainer's ruling, and
any elaboration or constraint the maintainer added. **Maintainer elaborations are authoritative and
override the agent's framing where they differ.**

- Source of decisions: `ops-handoff/definitive-design/architect-adversarial/report.md`
- Process: `docs/ops-workflow.md` § "Maintainer decision-review protocol"

---

## Q1 — Platform: compose-time or render-time? → **A (render-only)**

The writer composes a maximal, platform-neutral artifact; a render-side step fits each platform.

**Maintainer elaboration (authoritative):** the render step contains **two distinct passes**, which
must be modeled as separate passes:
1. **Content edit/reshape pass** — an edit pass that *elegantly places the content in the right shape
   for the target platform* (the agent's "reconcile/adapt").
2. **Output-artifact rendering pass** — rendering to the actual output format (markdown, PDF, Word
   docx, or others). Distinct from pass 1.

## Q2 — Where does reshape run; retract "render is free"? → **A**

Split the render side into two stages: **reconcile/localize** (LLM, per-target, only when needed) +
**serialize** (deterministic/free). The blanket "render is free" is retracted — true for serialize
only. Consistent with the Q1 two-pass elaboration.

## Q3 — Hard mechanical limits: block/force-reconcile, or warn-and-pass? → **A**

Two constraint classes: **advisory norms** (warn, overridable) vs. **hard limits** (must reconcile to
fit or block; never silently pass).

**Maintainer elaboration (authoritative — CROSS-CUTTING, applies wherever the design has
warn/override/reconcile behavior):**
- The system **never oversteps on its own** — it never autonomously overrides or bends a setting.
- It **respects user-set limits/config as authoritative and fixed**; it **never interprets a
  configuration setting as flexible.**
- When the user's own configuration will cause a problem (norm violation, exceeding a limit), the
  system **warns the user about the consequence of their own decision** — it does not silently "fix"
  it by overstepping.
- Therefore "override with a warning" is always the **user's** act (the system surfaces the warning);
  it is never a decision the system makes unilaterally. Reshaping to fit a platform's *external* hard
  limit is respecting a constraint, not overstepping — but the system must never bend the *user's*
  configured settings on its own initiative.

## Q4 — Keep `valid_platforms`/exclusions, or delete per Decision 5? → **A (delete hard exclusions)**

No hard compatibility filter; the user may select any format→platform pairing they want.

**Maintainer elaboration (authoritative):**
- Pairings are **user-driven** via recipes, folios, and other configs. There is **no automatic/default
  mode** that generates nonsensical pairings on its own — a README must **never** auto-produce a
  LinkedIn post without the user explicitly selecting it.
- Achieved through the existing **cascade of defaults → inheritance → overrides**: standard defaults
  give ease-of-use; the user cherry-picks customizations. The cascade resolves to an effective
  **selection list / allow list** that drives generation — the allow list is **emergent from config**,
  not a separate hard compatibility filter.
- **No final-moment veto machinery.** The system must not, at the last step, refuse to respect the
  user's resolved selections because it judges a combination "silly." (Reinforces the Q3 cross-cutting
  principle.)
- **Warnings = a one-time, lint-style sanity check** that flags strange/distant combinations (inputs
  far from outputs, e.g., README → LinkedIn) so the user can catch a mistake — advisory only, not
  blocking, not runtime machinery.
- The maintainer does **not** consider removing exclusions a design gap, and rejects the premise
  behind the agent's B guardrail.

## Q5 — Refactor §3.2 dimension taxonomy into orthogonal facets? → **A**

Replace the four "kinds" with orthogonal facets: **role** (content vs. rendering) · **representation**
(discrete-registry / parametric / scalar-parameter) · **cardinality** (single vs. set) · plus an
explicit **override property** (does this dimension's entries participate in the value cascade as a
cross-dimension override — Platform does).

Old kind → new tuple (confirmed):
- Registry (Topic/Persona/Format) = content / discrete-registry / single
- Registry, set-valued (Goal) = content / discrete-registry / **set**
- Parametric (Voice) = content / parametric / single
- Layer/constraint (Platform) = rendering / discrete-registry / single / **override=yes**
- Rendering-parameter (Language, Output-type) = rendering / scalar-parameter (or small registry) /
  single (set → fanout)

Nothing dropped (Platform's override promoted to an explicit property); flexibility gained (adding a
dimension = pick a cell, not invent a kind).

## Q6 — Remove "register" from Persona; give it a `default_voice` ref? → **A**

Persona owns **audience facts only** (role, knowledge level, motivation, objections, credibility
signals) + a `default_voice: <id>` ref (via the §3.10 `ref` attribute type). Voice owns all
register/affect/manner.

**Where voice can be set (for the reconciliation architect):** explicit voice via **recipe** and
**run** (overrides, resolved by the value-binding cascade, most-local-wins); parametric sliders
tunable at recipe/run (refinement). **Persona.`default_voice` is the sole *default* provider** in the
current design.

**Q18 flag (authoritative — expanded):** the model needs **both** a **global default** level
(**mandatory — always present**) and a **workspace default** level (**all optional**), on top of
`Persona.default_voice` and recipe/run overrides. The cascade **must define precedence** across all
default levels so they never conflict. This applies to **voice specifically and to defaults
generally**. Q18 must specify the full precedence order (e.g. global → workspace → persona → recipe →
run; exact order TBD at Q18).

## Q7 (+ Q8) — Folios / batches / actors / sessions — **ROUTED to a dedicated design pass**

Not resolved by the agent's A/B (which only settled naming). The maintainer expanded the problem;
spawning a focused `ops-architect` **initial design pass** on the **actors + sessions + folios** model.
Requirements it must satisfy (authoritative):

- **Folios:** purpose-driven grouping is the folio signal; folios are **addressable containers with
  stable IDs**; the **system can auto-create** a folio and an **external actor (n8n) can create an
  EMPTY folio, get its ID, kick off a run, and target that folio**; items addable **at any time**; an
  artifact may belong to **multiple folios** (many-to-many); one-offs/orphans exist. Crux to resolve:
  **one concept** (folios disambiguated by metadata) vs. **two stages** (mechanical batch → sorted into
  purpose folios). Also resolve **Q8** (X-thread = `split` vs folio) within the model.
- **Actors:** internal vs external actors.
- **Sessions:** external actors kick off a **stateful session**, but the **system stays stateless**
  w.r.t. session state — session state is **passed back and forth** and the **external actor tracks its
  own session state**. This is **session state only, NOT workspace state** (defaults / registries /
  config / SSOT are persistent, system-side). The actor/session model informs **when/how documents are
  referenced and what it means to use a folio** — that must inform the folio design.

Output → `ops-handoff/definitive-design/actors-sessions-folios/report.md`; surfaces numbered decisions
(F1, F2, …) for the maintainer.

---

# Actors + Sessions + Folios — maintainer rulings on the design pass (F-decisions)

Source: `ops-handoff/definitive-design/actors-sessions-folios/report.md`. The design pass adopted the
spine: two actor classes (internal co-located / external stateless); the pipeline is a pure function
`run(workspace_state, session_state_in, request) → (results, session_state_out)` that persists **no**
session state; a folio is durable **workspace state** and the session carries only the folio-**id**.

## F1 — How is a "mechanical batch" modeled? → **C**

**One container (the folio); a batch is NOT a container.** It exists as (a) the session token's
produced-id list (ephemeral) + (b) the immutable **generating-run lineage** stamped on each artifact
(permanent). "What did run X produce?" = a lineage query (by run / commit / date). Fewest concepts;
dissolves the cardinality/mutability/provenance blur of Model 1 and the mandatory-stage problem of
Model 2.

## F2 — Authoritative membership edge direction? → **A**

The **folio owns the ordered member list** of artifact-id references (authoritative); the reverse
index (artifact → folios) is **derived**. Ordering is folio-local (an artifact in two folios has two
positions), and one-authority + derived-view mirrors `CLAUDE.md` rule 3.

## F3 — Membership granularity? → **A (with C as escape hatch)**

**Artifact-level** membership + a folio-level `rendering_intent`; an optional per-member deliverable
pin (C) is available as an escape hatch. Preserves compose-once/render-many and keeps membership
stable across re-renders. Leans on Q17's artifact/deliverable id split.

## F4 — Session-state token representation? → **C**

Documented, actor-inspectable structure **+ an integrity/version stamp** so a stale / malformed /
cross-version token is detected and rejected (Q3 "never misread a config") — while the system still
persists none of it.

## F5 — Are folios session state or workspace state? → **A**

**Workspace state** — durable, id-addressable; the session carries only the folio-id reference. This
is the hinge that makes create-empty → target-later → add-any-time work across stateless calls.

## F6 — What may the system mutate on an actor's behalf? → **Recommended boundary ratified**

The system persists workspace changes **only as the direct result of an explicit actor action** (save
artifact, append membership to a folio the actor targeted, `add-to-folio`, update SSOT status). It
**never** (a) auto-adds to a folio the actor didn't target, (b) auto-creates purpose folios without a
folio-type/selection, or (c) overrides a user-configured setting on its own. (Q3 applied.)

## F7 — Manifest emission & folio lifecycle? → **A** (→ also resolves **Q9 = A**)

`emit-manifest` = a **point-in-time work-order snapshot** (pinned to member artifact-ids + commits)
for n8n; the folio **stays open/mutable**; the SSOT is updated from run **results**, never from the
manifest. **Q9 resolved: the manifest is a generated downstream work-order, NOT a slice the pipeline
writes into the SSOT** — `CLAUDE.md` rule 3 preserved.

## F8 — Folio id scheme & scope? → **A**

Workspace-scoped stable id (slug or uuid), fully-qualified as `(workspace, folio-id)`; the **system
assigns** it on `create-folio` and returns it. Isolation-natural (rule 2), collision-free, matches
"create empty → get its id."

## F9 — X-thread = split, not folio? → **A + 3 refinements** (→ also closes **Q8 = A**)

X-thread = `split` (one artifact → one multi-part deliverable via the reconcile pass); a set of N
standalone posts = a folio; delete §3.5's "split touches folios." Refinements (from the architect
re-examination in response to the maintainer's challenge, maintainer-approved — recorded as Addendum A
in the design report):
1. **Discriminator is mechanical, not editorial.** *split* = **one** artifact-id reshaped into N parts;
   *folio* = **N distinct** artifact-ids grouped by reference. Replace §3.7's "independently
   publishable" test with **"count the underlying artifact-ids."** "Independently publishable" survives
   only as an informal *authoring* heuristic for the user's upstream choice; the **system holds no
   opinion.**
2. **Part-level identity.** Add a `part-id` level — composite/IR parts → `(artifact-id, part-id)`;
   reconcile-split parts → `(deliverable-id, part-id)` tracing to one artifact-id. Each part is emitted
   as its own identified unit (own id + own bytes) → a publisher addresses part 3/7 directly, no
   re-parse. **Reserve a `part-id` slot in Q17.** Caveat: reconcile-split `part-id`s are stable within a
   *saved* deliverable, not guaranteed reproducible on re-chunk.
3. **Ordering advisory-only in BOTH split and folio.** §4.2 folio `ordering`/`schedule` → advisory
   hints (`suggested_order`, `suggested_schedule`); the manifest carries them as **advisory columns**;
   the publisher's scheduler owns the actual decision. Split parts carry an advisory `sequence`, never
   an enforced posting order. Ordering is **decoupled from the split/folio decision**.

Downstream deltas: §5/§3.7 discriminator change; §4.2 advisory ordering; §4.5/Q17 gains a `part-id`
level (reserve the slot). No change to F1 or the session contract; **reinforces Q9.**

## F10 — External-actor contract surface? → **A** (small stable stateless verb set)

Verbs: `create-folio`, `begin-session`, `continue-session`, `add-to-folio`, `emit-manifest`,
`fetch-by-id` — decoupled from the interactive agent.

**HARD NON-NEGOTIABLE REQUIREMENT (maintainer):** the pipeline/transport MUST use the **Claude
subscription, NOT API keys.** This constrains the (still-UNVERIFIED) transport — it must authenticate
via the subscription (e.g. Claude Code headless using the logged-in subscription credentials, not
`ANTHROPIC_API_KEY`). **Must be verified by a docs-researcher pass before any build.**

**Open — spec to close (maintainer concern: verbs are too open-ended):** enumerate `continue-session`'s
full **action vocabulary** and **each verb's exact parameters** (what the actor passes alongside
`session_state_in` to initiate an action). To be produced as a **closed contract spec** (not left
open-ended).

**Maintainer direction on the API/contract spec (authoritative):**
- The external-actor **API (verbs, parameters, session state) is designed LAST, by a dedicated
  architect pass, only AFTER every open question is locked** — to prevent drift. Not now.
- The API must expose **all information to control the process** and to **access/reuse the rendered
  artifacts and folios later.**
- That architect must be handed the system-responsibility boundary below as decisive input.

## Cross-cutting — system-responsibility boundary (authoritative; must hold throughout the design)

- **IN scope (this system):** (1) **rendering** = the reshape/reconcile pass (fit the IR to a
  platform, Q1/Q2 pass 1); (2) **output-doc generation** = the serialize pass (IR → text, markdown,
  PDF, docx, and others; Q1/Q2 pass 2). The system produces the rendered **deliverables** and the
  **folios**, and makes them **accessible by id for later use.**
- **OUT of scope (external actor, e.g. n8n):** **publishing** — pushing/posting output docs to any
  destination, and the ordering/scheduling of that (per F9, the system's ordering is advisory-only).
- **The system's responsibility ends at the rendered output doc + the accessible folio; it never
  publishes.** This is consistent with the actors/sessions design ("run → convert → publish," where
  publish is external) and is now locked explicitly.

---

# Remaining adversarial Q-items (resumed after the folio design)

## Q10 — Where do source-characterization scores live? → **A**

Split: `trusted` (source track-record) per-**instance**; `authoritative`/`opinionated` (content
properties) per-**content-kind** (per-fact only where the adapter supports it); `freshness`
derived/range.

**Maintainer notes:** source-vs-instance can blur, but per-instance placement makes that moot for the
source-level score. The four scores (`authoritative`, `opinionated`, `trusted`, `freshness`) were
**examples, not exhaustive.**

**Follow-on (spawned):** an `ops-docs-researcher` pass to research **additional useful
source-characterization scores** (web search + reputable frameworks), reporting for each: what it
measures, human-asserted vs. machine-derived, type (scalar/range/categorical), and where it attaches
(instance / content-kind / fact). → `ops-handoff/definitive-design/source-characterization-research/report.md`.

**✓ Complete:** 7 candidate scores (C1–C7) + 7 rejected. Highest-leverage: `corroboration` (per-fact,
machine) & `traceability` (per-fact, boolean) for grounding; `independence` & `primariness` (instance)
for selection. Meta-finding: the **Admiralty/NATO code** (source-reliability vs. info-credibility) and
**Ad Fontes** (reliability ⟂ bias) independently validate the Q10 instance-vs-content-kind split.
Stashed for source design/reconciliation.

## Q11 — Schema-versioning in v1: full lifecycle or hooks-only? → **B (full, no defer)**

Full schema-versioning in v1 per Decision 9 (per-attribute `definition_version`, per-entry
`schema_version` stamps, drift detection, upgrade-notice generation, deprecation lifecycle). **No
defer** — "if needed it can be updated later," but it is **built now**.

**Design task registered (authoritative):** the schema-versioning system is designed by a **FRESH
`ops-architect`** — explicitly **NOT** `ops-architect-actors-sessions-folios`, whose defer
recommendation biases/contaminates it for this task. Spawn **after its dependencies lock** (Q15
provenance/scope + the §3.10 schema substrate) to avoid drift — same no-drift logic as the API —
unless the maintainer directs otherwise.

## Q12 — Deep-folio: reserve full DAG, or identity-provenance only? → **A**

Reserve **only** the identity-provenance slot + a manifest dependency column; the DAG + structured
context object are **not** reserved now (they'd be designed if/when the already-deferred deep-folio
feature is built). Consistent with the F9 `part-id`/identity reservations and Q17. (Maintainer note:
this is not deferring *needed* work — it's declining to reserve unused scaffolding for an
already-deferred feature.)

## Q13 — Reclassify Language as an LLM transform (not a free rendering param)? → **A**

Language/localization = a **reconcile/localize LLM transform** (non-free, non-deterministic),
producing a localized IR variant that then serializes; the feature stays deferred (§5) but is now
**classified correctly**, consistent with Q1/Q2.

**Maintainer elaboration (authoritative) — localization has side effects that must be handled:**
1. It can **alter length** and thus **breach platform hard limits** (word/char max). After localizing,
   platform constraints must be **re-validated**, and a breach must **reconcile-to-fit or block per
   Q3** — never silently pass. This creates an interaction/ordering between the **localize** transform
   and the **platform reshape** (both in the reconcile pass) — flag for the render-pass design.
2. It must **preserve voice and the other content parameters** (register/tone/goal/persona fit, etc.);
   the transform must **not inadvertently drift** them. Fidelity requirement on the localize pass.

## Q14 — Composite `parts`: intra-genre only, or reference other Format entries? → **A**

`parts` names **intra-genre sub-outputs only**, defined inside the single governing Format entry (e.g.
`slide-deck → [slides, presenter-notes]`). One format selected → one artifact with named parts. "Two
formats = a composite" is **retracted**: composing two genres = two artifacts, packaged via a
**folio**. Preserves one-file-add; dovetails with F9's `part-id` (intra-genre parts →
`(artifact-id, part-id)`).

## Q15 — Provenance/scope hardening bundle → **A (all five)**

Adopt all five interlocking fixes:
(i) rewrite `operating-model.md` ownership as **mixed-provenance** (shared dirs hold framework
defaults + instance-global additions);
(ii) extend `CLAUDE.md` rule 5 to include `provenance: framework` entries (instances customize via a
workspace `extends:` partial — never edit a shipped default in place);
(iii) **namespace instance-global entry ids** (reserved prefix) to prevent upstream/instance filename
collisions;
(iv) guard **default-denies** missing/ambiguous provenance + runs schema validation;
(v) state plainly the guard **runs on public only**.
→ Unblocks the schema-versioning design dependency (Q11 task).

## Q16 — Reviewer: artifact or deliverable? → **BOTH (two distinct review types)**

Not either/or — two complementary reviews:
1. **Artifact review — early substance gate.** The full content/quality review of the platform-neutral
   IR, run **once**, before rendering; catches substance issues early (cheap to fix pre-fanout).
2. **Deliverable review — final validation.** Validates each **final** rendered deliverable before
   hand-off.

**Scope of Review 2 (maintainer ruling): COMPLETE.** Review 2 is a **full** review of each final
deliverable — a partial/scoped review could miss something. It fully vets the actual shipped output
(substance **and** rendering fidelity + publishability: voice/content parameters preserved (Q13),
platform hard limits respected (Q3), correct format/splits). **Accepted tradeoff:** review runs fully
on **every** deliverable — it does **not** inherit the compose-once economy, because the deliverable is
what ships and must be fully vetted. Review 1 remains valuable as an **early fail-fast gate** that
catches substance issues *before* fanout, saving wasted rendering.

## Q17 — Item identity (D2) redesign → **A**

Two-level identity:
- `artifact-id = hash(topic, persona, format, voice, sorted(goal-set), source-subset,
  resolved-overrides, source-commit)`
- `deliverable-id = artifact-id + (platform, language, output-type)`
- Idempotency keys on `artifact-id`.

Absorbs the accumulated folio requirements:
- **`part-id` level** — parts addressable as `(artifact-id | deliverable-id, part-id)` (F9).
- **generating-run id** stamped on each artifact for lineage / "batch" queries (F1).
- `artifact-id` is the stable folio-membership key (F3).

## Q18 — Cascade interaction & combination semantics

### (a) Structural principle → **A**
Mechanism 1 **fully resolves the effective entry before** Mechanism 2 binds values on top; unify M1/M2
combination as **type-driven** (replace for free-text/scalars, merge for maps); only M3 remains
adjust/weight.

### (b) Concrete precedence order → **NEW architect design pass (registered)**
The agent gave only the principle, not the order. A **new `ops-architect` pass** proposes the complete
precedence order. Maintainer guidelines (authoritative):
- Order flows from **global scope → workspace → folio → artifact → run scope**, **plus overrides**.
  *(Maintainer note: this list is NOT complete — the architect must derive the full set of levels; do
  not treat the above as exhaustive.)*
- Produce the order **for every dimension** (dimensions differ — e.g. voice has a persona-default;
  rendering dims differ from content dims).
- Design **overrides** elegantly: **where** are overrides specified and **injected** (per-run? at which
  pipeline point?) — the architect works this out.
- **NEW architect pass with COMPLETE context** — all design docs + all maintainer rulings/discussion;
  **exclude nothing.** Spawn after the Q-walkthrough completes so every ruling is included.

## Q19 — Re-scope the MVP → **B (full 8-dimension MVP)**

The MVP must exercise **all dimensions** — a minimal subset would not be a valid proof because the
dimensions interact ("this will not be right if all the dimensions aren't there"). No minimal-subset
staging. (Mission's stale MVP/success-criteria section is rewritten to the new model regardless.)

---

# Walkthrough complete — remaining design work

**All adversarial decisions ruled:** Q1–Q19 (Q8 via F9, Q9 via F7) + F1–F10 + sub-items + cross-cutting
(system-responsibility boundary; Q3 no-overstep principle; API-last/no-drift).

**Queued design passes** (each a FRESH `ops-architect`; complete context; no drift; never reuse a
contaminated agent):
1. **Cascade precedence + override injection** (Q18b) — full precedence order per dimension + where/when
   overrides are specified and injected. Dependencies locked.
2. **Schema-versioning system** (Q11=B) — full lifecycle; fresh architect, **not** the
   actors/sessions/folios one. Dependency Q15 locked.
3. **Source model** — incorporate the 7 researched candidate scores (C1–C7) + resolve **G6 (hard vs.
   soft source selection** — filters vs. weights), on top of Q10's attach-point split.
4. **External-actor API / contract spec** (F10) — **LAST**, after all else locked and after the
   maintainer's API gaps/inconsistencies discussion. Must honor the Claude-subscription (not API-key)
   hard requirement and the system-responsibility boundary.

## Cross-cutting — render / IR boundary (authoritative; supersedes the earlier G9 framing)

E5 (de-formalize the IR to markdown+frontmatter) is **REJECTED** — a thin IR can't reliably feed
esoteric renderers. **Four layers**, all to be well-defined and to fit the system + API, boundaries
kept separate:
1. **IR** — the internal representation; **persisted**. Single source for all rendering; re-render any
   output type by going **back to the IR** (never re-compose). Rich/tagged enough to represent
   everything downstream renderers need.
2. **"Easy" internal output types** — md, PDF, docx, …; serialized in-house from the IR; **persisted**
   (IR → docx now, IR → PDF later, no recompose).
3. **Standard interchange doc type** — a **sibling to the easy types, derived from the IR**, in a
   **well-known standard** (candidates: TeX, PostScript, DocBook, DITA, JATS, Pandoc AST — TBD by
   research). The reliable bridge a library/external renderer consumes to produce esoteric formats,
   since the IR alone may not convert cleanly unless it is itself a standard.
4. **External "hard"/esoteric output types** — epub, pptx, …; generated **externally** from layer 3.

**Corrected G9:** the v1 story is NOT "degraded md/pdf." v1 emits the rich IR + easy types + the
standard interchange type; esoteric formats are produced **externally** from the interchange type.
Only the *internal* esoteric byte-generators are absent.

**Plan (maintainer-directed):** a **docs-researcher** finds the right standard interchange format
(easy + well-known + library-renderable to esoteric); then a **fresh `ops-architect`** designs the
render stage to that standard, defining all four layers + how they fit the system + API.
**Four-layer framing CONFIRMED by maintainer.** Render docs-researcher spawned →
`render-standard-research/report.md`; render/IR architect follows once the standard is chosen.

**Then:** a **reconciliation `ops-architect`** folds `design-decisions.md` + all rulings + the
design-pass outputs into the **definitive design doc** (new SSOT) → maintainer approval → tracked in
the repo → **archive the stale docs** (§7 catalog).

---

# Source model — maintainer rulings (SM-decisions)

Source: `ops-handoff/definitive-design/source-model/report.md`. Spine: three attach tiers (**instance**
/ **content-kind registry** / **per-fact**); core score set = 8; a two-clause selection grammar
(`require` hard / `prefer` soft) + `span` coverage + selectable `on_conflict`; a framework-invariant
**EXTRACTED publish floor**. (Cross-pass: source-model R1 = §3.8 **M3 must widen** to carry
`require`/`span`/`on_conflict` — reconciliation item vs. the cascade pass's weight-only M3.)

## SM1 — Empty-pool / hard-filter-failure behavior → **A (with C as a later convenience)**

When a `require`/`span` clause (or a no-sources config) empties the grounding pool for an item:
**block that item and report the offending clause.** Other fanout items continue; blocked items surface
in run `results`; the user relaxes the clause or adds a source and re-runs (idempotent). Only branch
that neither oversteps the user's hard config nor silently ships ungrounded content (Q3). **C** (the
system *suggests* a relaxation the user confirms) accepted as a **later** advisory add-on — never
auto-applied.

## SM2 — Hard-vs-soft: clause or fixed per score? → **A**

The **clause** chooses: any score may appear in `require` (hard) or `prefer` (soft); operators follow
from the score's type; only *scope* constrains (per-fact scores can't select instances). Orthogonal,
one definition per score.

## SM3 — May a more-local layer relax an upstream hard `require`? → **A**

Yes — **most-local-wins.** A relax is the user's explicit local act and fires a warning; the system
never relaxes on its own initiative (Q3, Fork A parallel). The optional `locked:` flag (C) was **not
adopted.**

## SM4 — Selectable `on_conflict` strategy? → **A**

Conflict handling is a **selectable, extensible LIST of strategies** — `downgrade-AMBIGUOUS` (default),
`preserve-and-attribute` (compare/contrast), `priority-wins`, and **more addable** (goal-driven,
one-file-add).

**Maintainer elaboration (authoritative):**
- **Factual outranks opinion in conflict.** A factual/`authoritative` source has higher priority than
  an `opinionated` one; `priority-wins` (and defaults) leverage the `authoritative`/`opinionated`
  scores so a factual claim beats a mere opinion in a conflict.
- **Detect "factually incorrect opinions."** A strategy can identify an opinion that **contradicts an
  authoritative fact** and surface it — valuable for goals like debunk / correct-the-record /
  fact-check, where the contradiction *is* the content. Include fact-vs-opinion-contradiction detection
  as an available strategy capability where it serves the goal.

## SM5 — Content-property scores: content-kind registry or per-instance? → **A**

Content-kind is a **registry** (framework-shipped default kinds, one-file-add, instance-extensible)
carrying default `authoritative`/`opinionated`/`freshness`-policy; an instance tags into a kind and MAY
override via `extends:` field-merge (M1). Reuses provenance/scope + M1; introduces a new small
`content-kinds/` registry (R2 — inherits the guard + schema-versioning lifecycle).

## SM6 — Include `review_status` (C5) in v1? → **A (include)**

Include at content-kind (→per-fact where the adapter exposes merge/peer-review state); legal value
`unknown` when unavailable. Refines `trusted` at content granularity (esp. merged-vs-draft code). (R3:
Graphify per-symbol merge/review metadata unverified — degrades gracefully to `unknown`.)

## SM7 — Include `volatility` (C6) in v1? → **A (defer)**

Deferred to a designed hook — added later as one score definition when a churn signal is confirmed
available. Speculative/novel and adapter-dependent; the score schema + attach model already accommodate
a later add. (Maintainer accepted the deferral on the merits — the signal source isn't yet confirmed.)

## SM8 — Include `coverage` (C7) in v1? → **C**

`coverage` is a **resolver-internal ranking metric** (an instance tie-breaker beyond
`trusted`+`primariness`), **not** a user-facing characterization score. Kept (not deferred), but
internal — avoids adding another user-facing axis to define and justify.

## SM9 — Keep `traceability` separate from the confidence tier? → **A**

Separate axes: tier (`EXTRACTED`/`INFERRED`/`AMBIGUOUS`) = *how sure*; `traceability` = *can you cite
it* (resolvable anchor). Orthogonal; the review/citation stage (Q16) needs citability independent of
confidence.

**→ Source-model decisions COMPLETE (SM1–SM9).**

## RS1 — Layer-3 interchange standard → **A (Pandoc AST only, de-facto) — B addable later**

Adopt the **Pandoc AST (JSON serialization)** as the layer-3 standard interchange, rendered by
**Pandoc** to every downstream target. Chosen because it is the **only** single format+tool reaching
*both* epub and pptx (research report §coverage-matrix), and it is the natural serialization of the
already-mandated Markdown-envelope + Pandoc-family render model (`design-decisions.md` §3.4) — so
IR → AST stays a deterministic, LLM-free transform (Q2 "serialize is free").

- **De-facto accepted for v1.** Pandoc AST is a de-facto (single-implementation, api-version-pinned)
  standard, not de-jure. Maintainer accepted this on the explicit condition that **B remains cheap to
  add later** — i.e., a de-jure formal interchange (**DocBook 5** or **TEI P5**) for the print/epub
  axis can be added as an additional Pandoc *output target* with no rework. The render architect must
  keep that door open (persisted-IR + AST make it additive).
- **The internal/external "side" is a SETTING, not a fixed format property (maintainer refinement).**
  The four-layer boundary is not a hard technical wall between "easy internal" and "esoteric external"
  formats. *Pandoc does the actual work*; the renderer is a thin **dispatcher that calls Pandoc based
  on platform/setting.** If Pandoc can turn an "esoteric" format into an easy one-call render, that
  format **can switch sides.** So layer-3→layer-4 is a **configurable line** (policy/setting), not a
  hardcoded split. The render architect designs the dispatcher + the setting that governs which
  targets are produced in-system vs. handed off to an external actor — the *mechanism* is uniform
  (emit AST; call Pandoc), the *boundary* is configuration.
- **Pin the Pandoc version + AST api-version** (CLAUDE.md rule 8) — a hard build requirement.
- Caveats for the render architect (from report §risks): pptx layout is template-limited; PDF needs an
  external engine (pin it); the AST is single-document — folio/part orchestration remains the
  pipeline's job, not Pandoc's.

**→ Render-standard decision COMPLETE (RS1). Feeds the render/IR architect pass.**

## CA1 — Resolved entry's place in the value ladder → **A**

The M1-resolved effective entry is the **`entry-default` base** (just above the schema floor). All M2
scope/binding rungs (global → workspace → folio → recipe → run) sit **above** it and override
**type-driven, only for the attributes they declare** — a one-field default cannot gut the rest of the
entry. Literal reading of Q18(a) ("M2 binds on top of the resolved entry"); type-driven merge already
prevents the feared gutting. (Rejected B "defaults only gap-fill" and C "authoritative-flag hybrid".)

## CA2 — `persona.default_voice` vs. explicit scope default voice → **A** (+ brand-override question raised)

`persona.default_voice` **beats** workspace/global default voice: cascade order
`global < workspace < persona.default_voice < recipe < run` (Q6 stated order). Technically correct —
forcing the workspace voice to win under any other model would require inelegant workarounds
(strip the recipe/persona voice, duplicate recipes, or manual per-run override).

**Maintainer follow-up (NOT yet ruled — routed to a fresh ops-architect):** the workspace rung stays
where it is (not an override). But there is a real **brand-consistency** use case ("a brand requires a
certain consistent style"). Proposal to evaluate: a **"brand override" collection of dimensions** used
as *true overrides* (a layer that wins over the normal most-local cascade), realized as **global,
reusable actors usable in ANY workspace**. Question posed to the architect: **good option, or
over-design here?** Must reconcile with: workspace-isolation (rule 2), CA5 (overrides = content carried
at each scope, no separate rung), the rejected CA1-C authoritative-flag, and *where* such an override
sits in precedence (beats recipe? run?). Report → `brand-override/report.md`; result feeds this ruling.

**→ Brand-override RESOLVED → BO2.** The brand need is a **precedence gap, not a packaging gap** — the
brand already lives at existing rungs (instance house voice = L2 global-default; client brand voice =
L3 workspace-default, both `provenance: instance`); the only defect is that they sat *below*
`persona.default_voice`. Fix: add an optional **`authoritative: true`** flag (default false) on the
global/workspace **voice** scope-default schema (additive per §3.10). A flagged value **elevates to
just-below-run** — beats `persona.default_voice`, folio, and recipe; only a **run** can deviate, with a
one-time warning. Unflagged values don't move (workspace rung stays put). Per-value strength:
`a` = beat persona-default only · **`b` = beat through recipe (DEFAULT for a bare flag)** · `c` = beat
run too (opt-in hard-lock; the `locked:` shape SM3 rejected — never the default).

- **Why this = "wins every time":** run state is ephemeral (F4/F5); brand holds across ALL persisted/
  reusable config, a run is only a warned, non-persisted one-off. Matches SM3 (most-local-wins + warn)
  and Q3 (config-vs-config surfaced, never silent). Orthogonal to CA1's rejected authoritative-flag
  (CA1 rejected it where *merge* made it redundant; here it arbitrates a genuine same-attribute conflict).
  CA5-faithful (no new rung).
- **Constrained to Voice** in v1 (Persona/Goal/Platform brand-locks are category errors; an open bundle
  would straddle the `artifact-id`/`deliverable-id` compose/render split, Q17/CA6).
- **Provenance split:** the flag + warn *mechanism* = `provenance: framework` (public); the *values* =
  `provenance: instance` — house brand at L2 (gitignored public), a client brand at that client's L3,
  **never global** (rule 2).
- **Deferred (clean additive later):** BO4 — a named **brand pack** (never "actor" — collides with the
  actors/sessions model) built as sugar over a set of flagged instance-global defaults. Not v1.
- **Rejected:** BO1 (do nothing — loses to any persona voice) and BO3 (global cross-workspace bundle —
  over-design + rule-2 leak hazard: a populated pack holding one client's voice, shared globally, leaks
  into others' generation).

## CA3 — Folio rendering default vs. a recipe's pinned target → **A, but NO warning** (+ folio↔platform coupling flagged as a defect)

**Recipe beats folio** (L4 folio < L5 recipe) — settled. **But the "one-time lint warning" is REJECTED.**
Maintainer ruling: a **folio is a purpose/topical grouping, NOT a publishing target.** A folio can span
**multiple platforms by design** (e.g. "content about topic X, fanned across many platforms"). Therefore
a member recipe pinning a platform that differs from any folio-level rendering default is **normal, not
a conflict** — no warning fires for platform divergence between a folio and its members.

**→ OPEN DEFECT (routed to an ops-architect): the folio↔platform coupling.** The only place a folio is
tied to a platform is the optional **`rendering_intent`** field (ASF §4.2), imported as the cascade L4
rung (§2.6–2.8). It is a *soft optional default, not a hard limit* (a multi-platform folio already works
by leaving it unset + per-recipe pins) — **but its framing as "the folio purpose's implied (single)
platform" is a category error** and is what produced the wrong CA3 warning. Functional dependency to
resolve: ASF §4.3 gives `rendering_intent` a real job — at `emit-manifest`, platform-agnostic
artifact-members resolve to concrete **deliverable-ids** via `rendering_intent` OR a per-member
deliverable pin. So the redesign question is not "delete the field" but: **should a folio carry any
rendering default at all, and how does a multi-platform folio's members resolve to deliverables at
manifest time** (per-member pins? recipe-time? a set-valued intent that fans out?). Touches ASF model +
cascade L4 + identity (Q17) + manifest (§6.3) together → **RESOLVED by maintainer DIRECTIVE (below):
a folio holds no dimensions and no rendering opinion, ever.** No architect pass needed.

## DIRECTIVE (pipeline-wide) — A folio holds NO dimensions and NO rendering opinion, EVER

Maintainer directive; supersedes the CA3 defect routing. **A folio is a collection with a purpose —
nothing more. It carries no dimension values and no rendering/platform intent, ever.** Not a
rendering-only fix — a pipeline-wide invariant: the folio is **orthogonal to every dimension** (the 5
content + 3 rendering axes). Coupling any dimension to a folio, even as a soft default, is a category
error that mis-frames the folio as a publishing target and breaks the "one topic fanned across many
platforms" case by design.

Required corrections (feed the reconciliation + API/manifest architects):
1. **Remove `rendering_intent` from the folio data model** (ASF §4.2) — no platform/output-type/language
   default; the "Medium series → Medium" framing is deleted.
2. **Delete the L4 folio rung from the M2 cascade for ALL dimensions** (cascade §2.6–2.8 had it active
   for the rendering dims; content dims were already inactive). The folio is **not a value-binding
   scope.** Spine collapses to: `L0 schema-default · L1 entry-default · L2 global-default ·
   L3 workspace-default · L5 recipe · L6 run` (renumber; no folio rung). Brand-override BO2's
   "beats … folio …" simply drops folio from the list.
3. **F3 reduces to artifact-level membership only** (the "folio-level rendering_intent" half is gone).
4. **A folio retains only collection-intrinsic metadata:** id · purpose · optional `folio_type`
   (declares member **roles/structure**, NOT dimension values) · members (ordered artifact-id refs) ·
   ordering/schedule (position + cadence are properties *of the collection*, meaningful only within it) ·
   sequencing relation · provenance/scope. A typed folio's auto-generation sources dimension values from
   the **generating recipe/run, never from the folio.**
5. **Member→deliverable resolution at `emit-manifest` (§6.3) now REQUIRES a non-folio mechanism**
   (it previously could fall back to `rendering_intent`). Platform-agnostic artifact-members resolve to
   concrete deliverable-ids via **per-member deliverable pins and/or targets supplied at emit-manifest
   time — never from folio state.** This is the one open mechanism the directive forces; it folds into
   the already-planned **API/manifest architect** scope (not a separate pass).

## CA4 — Set/list combine semantics → **C, CONDITIONAL** (else A) — routed to an ops-architect

Start with **C** (per-attribute `combine: replace|union`, default `replace`) **only if** two conditions
are met: (1) **clear, deterministic rules** for what causes replace vs. union — no per-case surprise;
and (2) an **ergonomic user override** — a user can flip an attribute's combine mode on/off *easily*
(if the default is replace and they want union, or vice-versa). Maintainer's explicit fallback: **if a
clean, deterministic, easily-overridable design is NOT achievable, then everything must replace and
A is the answer.** ("This can get very frustrating if they can't turn something on and off easily.")

**Trap the architect must confront:** if combine-mode is itself per-rung overridable, combine-mode
becomes a value that cascades → you need a rule for how combine-mode *itself* combines across rungs
(meta-cascade). That recursion is the "messy" risk; assess whether to keep combine-mode a
schema-level-only declaration (deterministic, not run-flippable) vs. per-scope overridable (ergonomic
but meta-cascade risk), and rule honestly on whether C survives. Report → `combine-mode/report.md`.

**→ CA4 RESOLVED → CM3 (C stands), on two terms.** Combine-mode is an **inline operator on a single
binding** (`=` replace default / `+` union), NOT a value that cascades — so the meta-cascade regress
**never begins** (an operator is syntax at one assignment at one rung, never inherited; standard
`=`/`+=` config-language discipline). Two non-cascading places only: (a) a per-set-attribute **schema
default operator** (default `replace`; author may set `union`), (b) an **inline per-binding operator**
at any rung for a one-off flip. Resolution = a fixed bottom-up fold over the 6-rung folio-free spine.

- **`union` semantics (deterministic):** value-union + dedupe-by-exact-value + **the same `sorted()`
  canonicalization already ruled for `sorted(goal-set)`** (Q17) → identical set + identical `artifact-id`
  every run; additive-schema-safe (CA6 delta-vs-floor: a new set attr at its default is absent from the
  id → no churn).
- **Default is well-defined (naive-user contract):** union NEVER fires by default; default is
  most-local-wins (scalars/text/ordered-`list`/`set` → replace; `map` → merge key-wise). Goal-set stays
  replace. A user who ignores combine-mode gets expected behavior.
- **Ergonomics:** turning union on/off = one token at the binding you're already editing; no schema edit.

**Two ACCEPTANCE TERMS the maintainer attached (both required):**
1. **§3.10 must split ordered `list` from unordered `set`.** `union` is valid **only on an unordered
   `set` of leaf elements** (enum/number/ref/bool/string). Union on an ordered `list` (e.g.
   `format.parts`) or a `set`-of-maps is a **schema-validation ERROR** (never silent). Additive §3.10 change.
2. **The config-format decision + docs MUST land a clear, discoverable, documented combine syntax.** The
   exact surface form (canonical `{combine: union, add: […]}` vs. terse `attr+:` sugar) is deferred to
   the config-format decision, but "well documented + easily findable" is a binding acceptance rider on
   this ruling (maintainer condition "the use is well documented").

Blast radius (feeds reconciliation): cascade §2.0 (six-row table), §3.10 (`set` type + default-operator
field + validation), §2.5 (goal-set replace-default note), §3.8 (record: combine-mode is inline syntax,
NEVER a cascading mechanism — guards against drift back to CM5), Q17/CA6 (union feeds existing
canonicalization). **Out of scope v1:** a set-subtract `-` operator (on/off only; clean additive later).
Rejected: CM2 (schema-only — fails use-time ergonomics), CM4 (per-run mode-map — recurses), CM5
(cascading combine-mode — IS the trap), CM1/A (fallback only if term 1 declined).

## CA5 — "Overrides": separate rung or content at every scope? → **B** (+ authoritative reframe of what an override IS)

**B — override is a distinct, ephemeral, top-layer mechanism, NOT an affordance replicated at every
scope.** Maintainer's governing principle (authoritative over the mechanism):

- **An override is temporary and limited-scope.** It must **never** be a band-aid over bad design. The
  decision to have an override is driven by **why** one is needed — not "make it complex because it's
  possible."
- **Purpose:** to *temporarily test something WITHOUT changing the configured or default behavior
  permanently.* Once an override has generated its artifact(s), it has done its job or is no longer
  needed — it is **not persisted.** Example: generate artifacts into a folio *with* an override, then
  remove it; the **next** folio generated uses the **configured + default** values.
- **Scope: overrides live ONLY at the ephemeral run/session layer (L6).** There is **no need to put
  overrides at every level** (this is the explicit rejection of A). Persistent scopes — global (L2),
  workspace (L3), recipe (L5) — hold **CONFIGURATION**, not overrides.

**Consistency (no contradictions):** matches cascade §3.1 (L6 run = ephemeral session state, never
persisted; run bindings bind values M2, never redefine entries M1) and F4/F5 (session state ephemeral).
The override's *effect* is captured in the generated artifact's **identity/lineage** (`resolved-overrides`
→ `artifact-id`, Q17/CA6) for reproducibility — **ephemeral as config, recorded in identity.** Orthogonal
to CM3 (a binding at any layer — configured or override — may carry the inline `+`/`=` combine operator).

**Terminology-reconciliation item (for the reconciliation architect):** CA1 and the M2 tables used
"override" loosely for *any* scope binding-on-top. Under CA5=B, **reserve the word "override" for the
ephemeral run/session layer**; rename persistent-scope bindings to "configured values / scope defaults."
The `resolved-overrides` field name in `artifact-id` (Q17) now denotes "effective delta from the
schema-floor" (captures run overrides AND configured deviations) — the CA6 delta-vs-floor formula is
unchanged; only the terminology needs a one-pass alignment so "override" isn't used two ways.
Rejected: **A** (overrides as content at every scope — the "override at every level" complexity the
maintainer explicitly rejected).

## CA6 — What enters `resolved-overrides` in `artifact-id`? → **B**

**Delta vs. the schema-default floor**, organized per dimension: an attribute enters the hash only when
its effective value ≠ schema-default. Only B satisfies BOTH determinism (same inputs → same id) AND
stability under additive schema evolution (a newly-shipped attribute at its default is *absent* from the
map → no `artifact-id` churn, no orphaned caches — honors §3.10 "nothing moves"), while still capturing
M1 field-merges + all scope/override bindings; canonical (sorted keys, sorted goal-set). Organizes
Q17's settled `resolved-overrides` — does not overturn it. Rejected: A (full map — new attr churns every
id) and C (delta vs. entry-default — under-captures; changed global/workspace defaults can collide).

## CA7 — Override/binding injection point → **A**

**Collect once pre-resolve; apply at M2 bind; never at M1; never at reconcile.** One collection point
gathers all scope config + the run override before entry resolution. M1 does ONLY entry resolution
(overrides never touch it — consistent with CA5). Values apply at M2 in two stages: M2-compose →
`artifact-id`, M2-render → `deliverable-id` (the Q17 identity split). The reconcile pass *consumes*
bound values + enforces hard limits but is **not** an override point. Rejected: B (lazy per-stage
application — reintroduces "who injected this and when," breaks reproducible identity).

## CA8 — "Mandatory" for `global-default` → **A**, set = **Voice + Language + Output-type**

**A:** "mandatory" has teeth — the instance **must populate** global-default for the always-present
dimensions; **validation errors** if absent (the instance declares its own baseline identity, not an
accidental framework fallback). The schema-default floor (§3.10) still sits beneath as a last-resort net.
Rejected: B (optional — contradicts Q6) and C ("rung exists but may be empty" — no teeth).

**Mandatory-global set = Voice + Language + Output-type** (the three that must resolve to a concrete
value for ANY generation). **Excluded: Topic / Persona / Format / Goal** (per-request content choices; a
workspace MAY set optional defaults, but a mandatory global default is meaningless for them). **Platform
EXCLUDED** (maintainer confirmed): platform is **per-deliverable routing, not an instance-wide baseline**
— consistent with the folio DIRECTIVE (a publishing target is not a default-able identity). Language &
Output-type differ: they have natural instance-wide baselines (always *some* language / output-type);
content isn't inherently "for" any platform until you choose to publish it.

## CA9 — Advisory vs. hard platform constraints in M2 → **A**

**Advisory** constraints ride M2 as rungs (recipe/run may override → one-time lint warning, Q3/Q4).
**Hard limits sit entirely OUTSIDE M2** — enforced at the **reconcile pass** (reshape-to-fit or block;
never silent-pass, Q3). Keeps value-binding (what you'd like) separate from physical feasibility (what's
possible); the reconcile pass enforces feasibility regardless of what M2 bound. Consistent with the
`locked:`-rejection reasoning (SM3, BO2-`c` caveat). Rejected: B (hard limits as a "locked" M2 rung —
conflates a soft ladder with a hard gate; invites "can a higher rung beat the lock?").

## CA10 — Does a goal-nudge move an explicit user weight? (M3 Fork-C × Q3) → **A**

A goal-implied nudge adjusts **only the workspace-baseline** source weights; an **explicit** user
source-weight at recipe/run is the most-local rung and **wins outright** — a goal never moves a weight
the user set by hand. Honors Fork C (goals still nudge, on the baseline) AND Q3 (no overstep on explicit
config). Rejected: B (nudges override explicit user weights — violates Q3). *Coordination (not this
ruling):* source-model **R1** — M3 may need to widen to carry `require`/`span`/`on_conflict` vs. the
cascade's weight-only M3; on the reconciliation-architect's list.

**→ Cascade/overrides decisions COMPLETE (CA1–CA10).** Only schema-versioning (SV1–SV11) remains before
reconciliation.

## SV1 — `schema_version` ↔ `definition_version` relationship → **A**

`definition_version` is **valued in the `schema_version` number-space** (= the schema_version at which
the attribute's meaning last changed). Drift = **one integer comparison** (`definition_version >
entry.schema_version` AND the entry set the attribute); **no history table, no per-attribute entry
stamps.** Most faithful to §3.10 ("the resolver compares them"). Rejected: B (independent counter +
schema_version→{attr} history table — the exact state §3.10 avoids) and C (A + human `revision` field —
fallback only if the "= schema_version" convention reads confusingly).

## SV2 — Scope of `schema_version`: per-dimension or global? → **B (global)** — OVERRIDES the agent's A rec

**Maintainer ruling B (global), and the agent's A recommendation is REJECTED as resting on a false
premise.** The agent's sole case for A was "B manufactures false drift everywhere." **That is not true
given SV1=A:** drift is computed **per-attribute via `definition_version`** (`definition_version >
entry.schema_version` AND the entry set that attribute), NOT by comparing an entry's stamp to the
top-level number. A Voice bump to global 7 leaves Persona attrs' `definition_version`s unchanged (≤6),
so a Persona entry stamped 6 shows **no** drift. **Drift-scoping comes from `definition_version` being
per-attribute — it does NOT require per-dimension `schema_version`.** So B keeps drift-scoping AND gains
what A cannot give:

- **Atomic revert to a state that actually existed.** One global number pins one released, coherent
  schema snapshot. Per-dimension counters invite reverting one dimension into a (persona:4, voice:5)
  combination no release ever shipped/tested.
- **One number per run, not a vector.** A run pins the single global `schema_version` to be
  reproducible, instead of recording every dimension's version.
- **Less bookkeeping.** One counter to bump per release, not N per-dimension counters.

B is also cleaner with SV3: the `{framework: N}` stamp is a single genuine framework version under B
(awkward under per-dimension — "whose N?").

**Cosmetic consequence (not a blocker):** under B an attribute's `definition_version` lives in the
global number-space, so a rarely-changed attribute can jump (e.g. `tone` 3 → 47) across unrelated
releases. Drift math unaffected; if the sparse numbers read confusingly, SV1-**C** (optional
human-readable `revision` counter) is the mitigation — not adopted now.

**Reconciliation items (for the reconciliation architect):** flip §2.1/§2.2 to a single global
`schema_version` (framework-release-scoped); `definition_version` number-space is now **global**; SV3
`{framework: N}` stamp semantics = the one global framework version (map still gains `{…, x: M}` for
instance-extension namespaces); confirm no other SV decision silently assumed per-dimension (SV1 drift
math unchanged — it never compared top-level numbers).

## SV3 — Entry-stamp shape → **B (single integer)** — because namespaced ATTRIBUTES are DROPPED

**Maintainer ruling: namespaced (instance-custom) *attributes* are removed entirely; the stamp is a
single `{framework: N}` integer (SV3-B).** SV3-A's compound map existed ONLY to version instance-added
schema fields — with those gone, a single integer is correct.

**Why namespaced attributes were cut (decisive maintainer argument, confirmed):** the framework has
**no mechanism to APPLY a custom attribute.** A framework attribute is "applied" because the generation
logic/prompts are written with specific knowledge of it; a schema attribute declares only
`type`/`default`/`definition_version`/`definition` — **no `handler`/`prompt_fragment`/application hook.**
So a custom `x_*` field is inert to generation — a sidecar for an external purpose. The only soft path
(inject value + prose `definition` into the LLM prompt and hope) is undefined/non-deterministic (against
the grounding/determinism discipline) AND achievable more simply via metadata + a prompt convention — so
it argues *for* removal, not against. In this model instances customize by authoring **data (entries)**,
never by adding **generation logic**, so a custom field can have no consumer.

**Replacement — artifact-level opaque metadata bag:**
- An opaque **`metadata: { … }` bag lives on the ARTIFACT** (folio-level metadata NOT adopted —
  artifact-level only). The framework **stores it and passes it through to publish, but NEVER interprets
  or applies it.**
- **Excluded from `artifact-id`** (annotation, not a content input — it doesn't change the generated
  substance, so it must not change identity). Consistent with CA6 (delta-vs-floor is over *schema
  attributes*; metadata isn't one).
- The **publisher (external actor) decides what to do with it at publish time** — that's where the
  meaning lives.
- Scope: workspace-scoped `provenance: instance` content (rule 4 satisfied); it is **not a dimension**,
  so the folio-holds-no-dimensions DIRECTIVE is untouched.

**Clean conceptual line this establishes:** framework attributes = **content inputs the framework knows
how to apply** → shape generation AND enter `artifact-id`. Custom instance data = **opaque metadata** →
framework never applies it, it stays OUT of framework identity, interpreted downstream at publish.

**Blast radius (feeds reconciliation):** drop `x_` attribute keys, `_schema.x.yaml` extension files, and
independent attribute version-counters (schema-versioning report §2.3/§2.4/§3); stamp is single integer
everywhere; add the artifact `metadata` bag as a small new element; **schemas are now closed AND
non-attribute-extensible by instances** (instances add entries + metadata, never new interpreted fields);
the Q15 CI guard simplifies (framework schemas only). **KEPT:** entry-ID/file namespacing (`x-our-cto.md`)
— a separate, still-real merge-safety need; only the *attribute* half of SV5 dies. **SV5 note:** its
attribute-namespacing question is now MOOT; its entry-ID namespacing convention (A single-prefix / B
org-slug / C subdir) remains to be walked at SV5.

## SV4 — Schema file location & serialization → **A**

**Co-located per dimension** (`personas/_schema.yaml` alongside persona entries, etc.) — mirrors the
"a dimension is a directory" layout; each schema sits with the entries it governs and its per-directory
validation. **Format is subordinate to the open D1 serialization decision** — if D1 lands on a non-YAML
envelope, schema files follow it (report risk R5). Post-SV3 simplification: only *framework* schemas
exist (no instance/workspace schema-extension files), so this governs framework schema placement only.
Rejected: B (central `schemas/` dir — breaks co-location, complicates the guard) and C (`.md` with
frontmatter — nicer prose diffs, harder to validate/diff structurally).

## SV5 — Instance entry namespacing → **A (required `x-`) + optional gentle org-slug**

Scoped to entry ids/files only (attribute namespacing died with SV3). **Required invariant: instance
entry files start with the reserved prefix `x-`** (`x-our-cto.md`) — framework owns the unprefixed space,
never ships `x-*`, so the only possible collision (framework↔instance) is fully prevented and upstream
merges stay conflict-free. This is what the **CI guard enforces**.

**Maintainer refinement:** instances MAY optionally add an org-slug segment after the prefix —
`x-acme-cto.md` — where the `acme-` part is a **gentle suggestion only: not documented, not tracked, not
CI-tested.** It stays within the `x-` reserved space so the collision guarantee is unweakened. **Promotion
path:** if instances ever need to share files with each other directly, the org-slug (B) can be **promoted
from optional to required** to prevent instance↔instance collisions — a clean later escalation, not v1.
Rejected as the default: B mandatory (verbose for no benefit while instances never cross-merge) and C
(subdirectory split — changes entry-path convention + every guard glob).

## SV8 — Migration application policy → **RESHAPED (not plain A); routed to a schema-migration architect**

The agent's SV8-A ("opt-in, never auto-run") is **too weak.** Maintainer + confirmed analysis: because
the framework carries only **one active interpretation logic** (old-version logic is gone), a stale
recipe/entry run against a newer framework is a genuine **misread** — so warn-and-proceed (SV7 resolve-
time behavior) is unsafe for real meaning changes. The model becomes **user-triggered but MANDATORY
before use** (block/abort, not warn), with framework-provided forced migration. This is *more* Q3-clean
than warn-and-proceed: the framework never silently rewrites (user triggers) AND never silently misreads
(it blocks). Blocking refuses to act — not an overstep. Deterministic intent-preserving remaps are NOT
a Q3 overstep (they keep the user's choice across a representation change).

**HARD CONSTRAINTS (maintainer-set; the architect honors, does not re-decide):**
1. **One active interpretation logic**; forward migration required for a stale object to be usable.
2. **Mandatory-before-use:** block ("upgrade or abort") on real meaning-change / unsupported-version
   drift — upgrades SV7's resolve-time behavior from *warn* → *block* (SV7 "run at both times" stands;
   soft/informational drift may still just warn).
3. **User-triggered, NEVER silent auto-run** (Q3); idempotent; re-stamps; instance-owned files only
   (rules 1/5).
4. **Deterministic remaps → auto-migrate (forced, intent-preserving).** **Ambiguous meaning changes →
   human-resolution gate; NEVER silently guess** (guessing = data loss + real overstep).
5. **Cumulative + SKIP-SAFE:** migrate from ANY supported version **directly** to current, correct even
   if versions were skipped (accidentally or on purpose). **NOT chained** (vN-1→vN links break when
   intermediate logic is lost). A skip-span migration must surface the **union** of all human decisions
   accrued across skipped versions — an ambiguous change in a skipped version cannot be auto-skipped.
6. **Support-window bounded** (tie to SV9): supported back to version X; **older than X → hard block +
   documented manual path** (not an infinitely-maintained script).
7. **Forward-only, NO REVERT:** once a migration runs the framework offers no undo — no down-migrations,
   no revert mechanism. Git is the user's own escape hatch, explicitly unsupported/unguaranteed.

**Architect sub-forks to design + recommend:** how cumulative from-any-version transforms are authored/
structured; support-window depth policy (vs SV9 major/minor); exactly how the ambiguous-change human
gate works (interactive vs a "decisions-needed" report the user fills in); the precise block-vs-warn
drift boundary; idempotency/re-stamp mechanics; reconciliation with SV6/SV7/SV9/Q3. Report →
`schema-migration/report.md`. Result finalizes SV8 (+ adjusts SV7 resolve-time behavior).

**→ SV8 FINALIZED (maintainer RATIFIED the full package).** Mechanism = **one fold over the half-open
interval `(stamp, current]`**, run by an owner-triggered `scripts/migrate.sh` — a **maintenance verb,
NOT part of the external-actor F10 API.**

- **Skip-safe transforms = a declarative migration-step registry the runner FOLDS** (per-attribute in
  the common case; object-level as an escape hatch). Each step is authored **once**, at the release that
  made the change; the runner selects steps whose trigger-version ∈ `(stamp, current]` and folds them →
  skip-safety **by construction**, no chaining, no lost interpretation logic, **no representable inverse**
  (enforces no-revert). (Rejected: per-version `from-vN` whole-object transforms — re-extends O(window)
  every release = the infinitely-maintained script constraint 6 forbids.)
- **Object-atomic** migration (re-stamp only when ALL an object's steps resolve; forced by SV3=B's
  single-integer stamp). **Idempotency is structural** — folding an empty `(stamp,current]` is a no-op.
- **Migratable = instance-owned, schema-stamped CONFIG only** (instance-global entries, workspace
  `extends:` partials, instance recipes/folio-types/source-instances/content-kinds). Framework defaults
  are lockstep-maintained upstream, **never migrated by the instance** (rule 5). **Artifact `metadata`
  bag untouched** (opaque). **Artifacts are IMMUTABLE — never rewritten; migrate config → REGENERATE**
  (new artifact-id; old artifact persists as lineage).

**(a) SV6 EXTENDED → THREE tags:** `wording` / `deterministic-meaning` / `ambiguous-meaning`.
Machine-checkable discriminator: **presence of a TOTAL, typed forward map = deterministic (auto-apply);
its absence = ambiguous (HALT for a human).** CI (schema-lint) fails a meaning-bump shipping neither.
SV6 default-to-meaning stands; *within* meaning, the safe default is **ambiguous** (never a silent
partial-map guess).

**(b) Human gate = a generated, RESUMABLE "decisions-needed" worklist file** (NOT interactive prompting)
— reviewable up-front, resumable, diffable/auditable, **grouped by change with a group-level default** so
one policy answer fans across every recipe sharing that ambiguous change (answers the many-recipes-scale
concern).

**(c) SV7 ADJUSTED (block-vs-warn):** **update-time REPORTS** (upstream merge stays non-destructive);
**resolve-time ENFORCES / BLOCKS before use.** BLOCK = any meaning-change (det or ambiguous) on a *set*
attribute · stamp below the support floor · removed-attr-still-present. WARN = new-attribute-available ·
deprecated-but-still-working. Silent = wording-only. **Closes report R6** (hard drift now blocks *before
any artifact exists*); Q16 Review-1 handles only residual soft advisories. (SV7=A "run at BOTH times"
stands — this refines the resolve-time *behavior* from warn→block.)

**(d) Support window (RATIFIED): floor X = the global `schema_version` at the START of the PREVIOUS
semver MAJOR** → support **current + previous major**. Aligned with SV9 major-boundary removals + ≥2-minor
runway. **Retention ≠ re-authoring:** below the floor the *executable* step is dropped but the
human-readable `history` entry is **retained permanently** = the documented manual path (hand-edit +
re-stamp to ≥X, then the tool resumes). Notice warns **one major ahead.** Git-revert remains the owner's
own unsupported escape hatch (SV2=B's single global number makes that land on a coherent tested snapshot).

**Build-time risks flagged (for reconciliation/build):** R-M1 SV6-discipline dependency · R-M2
multi-ambiguous-change-on-one-attribute ordering · R-M3 floor-advance stranding · R-M4 object-level step
trigger semantics · R-M5 auto-apply must report its writes · R-M6 D1 serialization dependency. **No SV
ruling silently contradicted.** → Resolves SV8; adjusts SV7; extends SV6.

## ⛔ RETRACTED — the entire schema-migration design above (SV8 finalization + SV9) is THROWN AWAY

Maintainer retracted the ratified schema-migration package. **Everything from "SV8 FINALIZED" through
the (d) support-window and the SV9 per-attribute model is VOID** and being redesigned by a brand-new
architect. Two fatal conflicts with maintainer requirements:

1. **The (d) support-window (current + previous major, hard-block below floor) VIOLATES the skip-safety
   requirement.** The maintainer requires users to skip **any number of versions, including several
   majors**, by accident or on purpose — no guarantee of upgrading every version. A hard-block floor is
   the *opposite* of that. (Author's note: I wrongly presented this window as reasonable and obtained a
   ratification that contradicted the earlier skip-safe requirement — retracted.)
2. **Per-attribute deprecation/removal (SV9-A `removal_target`) is REJECTED** as "a maintenance
   nightmare, unnecessary and confusing." Versioning must be **ALL-OR-NONE**: one global framework
   version bumps even if only one attribute changed (rest no-ops); deprecation/removal, if it exists at
   all, is framework-wide, never per-attribute.

**CORRECTED HARD REQUIREMENTS (maintainer, non-negotiable) → drive the redo:**
1. **All-or-none versioning.** One global framework version; NO per-attribute windows/removal-targets/
   lifecycles. A no-op-heavy patch release is fine.
2. **Skip-safe across ANY number of versions, including several majors.** Migrate directly from any prior
   version (however old) → current. **NO hard-block support floor.**
3. **Reconcile #2 with bounded maintenance WITHOUT a floor** — re-examine the "infinitely-maintained
   script" premise; declarative authored-once (append-only) steps retained forever are cheap, not
   "maintenance." Justify.
4. **Forward-only, NO revert** (unchanged). Git = user's own unsupported escape hatch.
5. **Deterministic → auto-migrate; ambiguous → human resolution, NEVER a silent guess**; skipping many
   versions accumulates ambiguous decisions → surface their union, but keep it SIMPLE.
6. **User-triggered, mandatory-before-use (block on stale), never silent auto-run** (Q3); idempotent;
   instance-owned files only (rules 1/5); artifacts immutable (migrate config → regenerate).
7. **SIMPLE.** All-or-none, minimal concepts. Prior design judged "overly complex" — bias hard to simple.

**Settled, not reopened:** SV1=A, SV2=B, SV3=B, SV4=A, SV5=A; SV6-base (meaning-vs-wording + CI,
default-to-meaning) & SV7-base (drift at BOTH update-time + resolve-time) stand as INPUTS. **Being
redesigned:** the migration/deprecation/skip model (old SV8 + SV9) AND the migration-derived refinements
(SV6 "third tag," SV7 "block-vs-warn") — all open. New report → `schema-migration-v2/report.md`.

## ✅ SV8/SV9 FINALIZED (v2) — maintainer RATIFIED, with a 1-YEAR time-window bound

Mechanism = **one fold over `(stamp, current]`** across a **declarative, append-only migration-step
registry**, run by owner-triggered `scripts/migrate.sh` (maintenance verb, NOT the F10 actor API).
Simpler than the thrown-away design — **five concepts deleted** (support floor, below-floor hard-block,
documented manual hand-edit path, per-attribute deprecation lifecycle, SV6 third tag).

- **CM1 authoring:** one **declarative step per meaning-change**, authored once, folded on demand.
  Skip-safety + no-revert are STRUCTURAL (no inverse representable), not policy-enforced.
- **CM2 growth bound → MAINTAINER RULING: a 1-YEAR TIME-WINDOW (replaces v2's "retain forever").**
  NOT the rejected version-floor — this is **time-based**, so a user may skip **any number of
  versions/majors *within a year*** and still migrate directly to current. Steps for changes **older
  than one year (by release date) are PRUNED** → registry bounded by calendar time regardless of
  release count. Rationale: "if a user fails to update within a year, they take responsibility."
- **CM2 out-of-window behavior (CONFIRMED):** a config whose stamp predates the 1-year horizon has its
  needed steps pruned → the tool **BLOCKS** (never silently generates from stale/misread config — that
  guarantee holds), message "past the 1-year support window — regenerate or hand-fix; unsupported," with
  **NO** elaborate documented hand-edit path (stays deleted; keep it simple). User takes responsibility.
  - **Not a permanent dead-end (maintainer note):** git preserves each past release's registry as it
    was, so a user CAN migrate a very stale config by checking out an intermediate release within a year
    of their stamp, migrating to it, then hopping forward in **≤1-year strides** to current. Tedious and
    entirely the user's own **unsupported** git-driven path — the framework neither provides nor
    guarantees it — but no config is ever *permanently* stranded. Consistent with "git = user's own
    escape hatch."

- **CM3 deprecation DIES entirely:** no per-attribute `deprecated`/`removal_target`/`replacement`, no
  window, no bookkeeping (all-or-none). "Removal" = current schema stops declaring X + a forward step
  drops/remaps configs that had X; a rename = a lossless total-remap step.
- **CM4 SV6 stays BINARY (third tag REVERSED OUT):** deterministic-vs-ambiguous is a property of the
  step's SHAPE (total map = deterministic/auto-apply; prompt = ambiguous/halt), not a maintained tag.
  One CI rule: a meaning-bump must ship a map or a prompt.
- **CM5 ambiguous gate = a resumable, group-defaulted "decisions-needed" worklist** (not interactive);
  the fold surfaces the **union** of ambiguous decisions across skipped versions; group-default fans one
  answer across many recipes; object-atomic re-stamp (forced by SV3=B).
- **CM6 block-vs-warn:** update-time **REPORTS** (merge non-destructive); resolve-time **BLOCKS** before
  use. BLOCK = meaning-change on a set attr (det or ambiguous) · removed-attr-still-present · **stamp
  out-of-window (new, from CM2 time-bound)**. WARN = new-attribute-available. Silent = wording-only.
- **CM7 scope:** migrate instance-owned schema-stamped **config only**; framework defaults lockstep
  upstream (never instance-migrated); **artifacts IMMUTABLE — migrate config → REGENERATE** (new
  artifact-id; old persists as lineage); `metadata` bag never touched; git-revert is the only "revert"
  (SV2=B makes it land on a coherent snapshot).

**Build risks:** deterministic-map totality/composition needs schema-lint validation; disguised rename →
silent data loss is review-only (not machine-detectable); D1 serialization is a dependency. **No settled
ruling contradicted** (SV1–SV5, SV6/SV7-base, Q3, Q16, Q17/CA6, rules 1/5, folio directive reconfirmed).
→ **Resolves SV8 + SV9; SV6 stays binary (base); SV7 refined to block-on-stale (base "both times" holds).**

## SV10 — Coverage: which collections get schema-versioning? → **A (uniform)**

**Every** collection: all dimensions PLUS source adapters, source instances, renderers, recipes, folio
types, content-kinds. Thin objects get thin schemas; one identical mechanism everywhere. Matches §3.9
"uniform across everything" and the Q5 facets model (no special cases). Rejected: B (content dims only —
resurrects the special-casing Q5 removed; leaves recipes/sources as unversioned silent-misread blind
spots). (Folio *types* = framework blueprints declaring member roles — untouched by the folio-holds-no-
dimensions directive, which governs folio *instances*.)

## SV11 — Additive-only CI enforcement (public) → **A (full, v2-adjusted)**

`schema-lint.sh` on public FAILS on: (1) schema changed without a `schema_version` bump (SV2=B); (2) a
**meaning-change** — incl. attribute **removal**, incompatible **type change**, or rename-as-remove+add —
shipped **without a migration step** (CM4 map-or-prompt); (3) **lockstep** violation (a framework default
entry stamped older than current `schema_version` for a redefined attribute it sets); (4) window sanity
(pruning an in-window <1yr step). Paired with the Q15 **default-deny** provenance guard + schema
validation. **v2 adjustment:** the report's original SV11-A referenced the now-deleted `removal_target`/
deprecation lifecycle — replaced by the migration-step-required rule (2). Rejected: B (subset — leaves
lockstep + missing-migration-step holes → silent misreads). **Known limit (R9):** a *disguised* rename
(remove-old + add-new-same-meaning) is NOT machine-detectable → relies on the "never rename, ship a remap
step" discipline + review.

**→ Schema-versioning decisions COMPLETE (SV1–SV11).**

---

# ✅ MAINTAINER DECISION WALKTHROUGH COMPLETE

All decision passes walked one-at-a-time per the maintainer protocol:
- Adversarial architect review **Q1–Q19** · Actors/sessions/folios **F1–F10** · Source-characterization
  **C1–C7** · Source-model **SM1–SM9** · Render-standard **RS1** · Cascade/overrides **CA1–CA10** ·
  Schema-versioning **SV1–SV11**.
- Spawned sub-passes ratified: **brand-override (BO2)**, **combine-mode (CM3)**, **schema-migration v2**
  (+ 1-year window). Plus the pipeline-wide **folio-holds-no-dimensions DIRECTIVE**.

**Remaining work is the BUILD phase:**
1. **Render/IR architect** — DONE (report in `render-ir/report.md`; RI walk in progress below).
2. **API/contract architect (LAST)** — closed contract: `continue-session` action vocabulary + verb
   params; HARD: Claude subscription, never API keys. *Maintainer wanted to discuss API gaps/
   inconsistencies BEFORE this runs.*
3. **Reconciliation architect → the definitive design doc** → maintainer approval → track in repo →
   archive stale docs.

**Reconciliation coordination items to hand the reconciliation architect:** widen M3 to carry
`require`/`span`/`on_conflict` (source-model R1) vs cascade weight-only M3 · **D1 serialization format**
(blocks SV4 schema format + config combine-syntax) · schema-default = cascade-floor placement (R8) ·
R3 Graphify metadata docs-researcher pass before build · terminology reconciliation: reserve "override"
for the ephemeral run/session layer (CA5) · remove folio `rendering_intent` + the cascade L4 rung
(folio directive) · fold the artifact `metadata` bag (SV3) into the identity/model spec · **add the new
PRESENTATION dimension to the matrix axes + identity** (below).

---

# RENDER/IR DECISION WALK (in progress)

## RI1 — IR envelope serialization → **A (JSON, decoupled from D1)**

IR envelope = **JSON**, Markdown in the leaves, **decoupled from D1**. The IR is machine-generated,
machine-consumed, immutable (CM7), and the input to a deterministic transform — JSON's requirements, not
YAML's; and the layer-3 AST is already Pandoc-JSON, so layers 1→3 stay in one serialization family
(IR→AST = JSON→JSON). **D1 is NOT a blocker for the IR** (only the IR-validation *schema file* follows
D1/SV4 — soft). Rejected B (follow D1) / C (YAML). **The envelope is NOT the typesetting-richness
bottleneck** (JSON holds any structure); sufficiency lives in the leaf/AST model + the renderer/template
layer → routed to a docs-researcher (below) + RI7 + the B-standard question.

## NEW DIMENSION accepted for design → **PRESENTATION dimension** (typesetting/style)

Maintainer-proposed and accepted: a **Presentation dimension** — a **rendering** dimension (registry of
style entries) carrying typesetting/style rules, orthogonal to **Format** (Format = content *structure*;
Presentation = visual *style*). **v1.0 = minimal schema + hooks/entry-points; grow the typesetting
vocabulary additively over versions** (the SV1–SV11 additive model). Raises the esoteric-output quality
ceiling; gives the visual "brand look" a home (design-side sibling of the voice-only BO2 brand-pack).

**Architect must nail (a dedicated pass, AFTER the docs-researcher):**
- Facets (Q5): role=**rendering**, representation=**discrete-registry**, cardinality=**single** (+override).
- Resolves to concrete render inputs (template/reference-doc, CSS, engine, layout hints, pins) consumed by
  the RI12 dispatcher + RI13 pin set.
- Applied at **serialize** (deterministic writer call), **reusing the persisted AST** → a new/changed
  presentation = one writer call, **no LLM, no re-serialize** (slots into RI11 regeneration tiers).
- Joins the deliverable-level rendering axes → **`deliverable-id` gains presentation** (additive to Q17,
  like output-type; coordinate with RI10 `fitted-id`).
- **Sharp delineations:** Presentation (deterministic style @ serialize) ≠ Format (content structure) ≠
  Platform (publishing target) ≠ Output-type (file format) ≠ **reshape** (LLM content-restructuring —
  "split into slides"/"cut to fit" stays in reshape, NOT Presentation; Presentation only styles what
  exists).
- Whether Presentation needs a mandatory-global default (like Output-type per CA8) or a minimal "plain"
  default entry. Inherits SV10 (schema-versioned registry) + the guard.
- **Caution:** raises the quality *ceiling*, not the v1 *floor* — floor is still bounded by Pandoc writer
  capability (same facts the docs-researcher resolves).

**Sequencing:** docs-researcher (typesetting sufficiency + presentation capability, spawned) → dedicated
presentation-dimension architect (builds on `render-ir/report.md`).

## RI3 — Per-fact confidence tiers + source/commit provenance → **A** (+ new fidelity constraint ratified)

**A — a grounding ledger** in the IR envelope: `grounding: { fact-id → { tier
(EXTRACTED|INFERRED|AMBIGUOUS), source_instance_id, source_repo, source_commit, traceability_anchor,
scores_snapshot } }`, with per-claim **inline `fact-id` references** in the Markdown leaves. Content
leaves stay pure Markdown; every grounded claim is addressable (Q16 review + SM9 citability both need
per-fact resolution); the ledger stores **ids/anchors/commits, never secret values**. Rejected: B
(section-level — too coarse) and C (inline provenance values — pollutes content + risks
provenance/tier LEAKING into published bytes, violating the grounding + no-secrets rules).

**→ NEW FIDELITY CONSTRAINT (ratified with A; extends Q13):** because pass-1 **reconcile is an LLM
rewrite**, it can silently break the claim↔fact binding OR upgrade an INFERRED lead into an asserted
fact. So **reconcile MUST preserve + re-anchor the per-claim provenance/tier bindings.** Stated with
Q13: **pass 1 preserves (i) voice + content params, (ii) meaning, (iii) provenance/tier bindings.**
Losing (iii) blinds Q16's grounding re-check on the fitted content. Binds the product-plane
writer/reconcile agent (a sibling of the Q13 voice-preservation rule).

## Typesetting docs-researcher — VERDICT + corrections (verified vs Pandoc 3.10 / pandoc-types 1.23.1.2)

**SUFFICIENCY VERDICT: YES — professional, non-"crippled" output is achievable.** Per-target floor/ceiling:
- **PDF — professional floor** (xelatex/lualatex/typst/context + tuned template); ceiling = bespoke
  magazine multi-column/floats → custom template or `{=latex}` raw.
- **DOCX — professional floor** (`--reference-doc` + custom-style hooks); `{=openxml}` raw beyond styles.
- **EPUB — professional floor, REFLOWABLE ONLY.** Hard gap (VERIFIED): **no fixed-layout EPUB** → needs
  DocBook/TEI path or external tool.
- **PPTX — good on-brand draft, NOT bespoke** (theme/fonts/7 layouts/notes; no custom template, no
  animations, weakest raw hatch). **Bespoke decks = the one place an external pro renderer is the answer.**
- Escape valves confirmed additive: specialist intermediates from the same AST (`-t
  latex/context/typst/icml(InDesign)/docbook5/tei`); DocBook5/TEI for formal/fixed print+EPUB; format-
  tagged raw passthrough (per-format, portability-breaking). The two honest ceilings (fixed-layout EPUB,
  bespoke PPTX) are exactly where the maintainer's EXTERNAL layer-4 boundary + additive DocBook5/TEI earn
  their keep.

**→ LOAD-BEARING CORRECTION to RI8 (provenance-leak):** RI8 claimed provenance `Attr` is dropped by all
non-HTML writers. **WRONG for HTML5 + EPUB3** — the HTML writer emits unknown kv-attrs as `data-*` and
tier classes as `class="…"`, so **provenance/tier tags WOULD leak into published HTML/EPUB3 bytes.**
FIX: a **pinned, deterministic pre-serialize filter (Lua/JSON, no LLM) that strips the provenance `Attr`
when the writer is html5/epub3.** Protects the grounding + no-secrets guarantee. (docx/pptx/pdf/EPUB2
still drop as RI8 assumed.) Reconciliation + build must include this filter.

**All 10 Rule-8 flags RESOLVED** (R-1/2/3/7 AST keys+`Attr`=`(id,[classes],[[k,v]])`+MetaValue+api-version
match; R-5 slide carving + `::: notes` + `--reference-doc` verified for **docx AND odt AND pptx**; R-6
extension names + lossless-to-json with a reader-pin caveat → **feeds RI7**; R-8 13-engine list; R-9
chunkedhtml; R-10 docbook5/tei writers). Report: `render-typesetting-research/report.md`.

**Presentation minimal-v1 schema (verified, Part C) — feeds the presentation-dimension architect:** two
cross-target catch-alls (`variables` via `-V`/`--variable-json`, `highlight_style`) + six target-specific
maps (`template` per-writer [pptx has none], `reference_doc` docx/pptx/odt, `css` html/epub, `pdf.engine`
+opts, `fonts`, `margins`). **`variables` is the deliberate grow-later hook** (no future need forces a
schema break). Applied at serialize on the persisted AST (one writer call, no LLM → RI11); Presentation
joins `deliverable-id` (additive); RI13 pin bundle must carry template/reference-doc/css/font hashes +
engine version + variable snapshot.

## RI9 — Composite artifact: one AST or N? → **RATIFIED (one AST per physical output doc)**

**One Pandoc AST per physical output document; the pipeline orchestrates N ASTs when the target is
inherently multi-file** — decided by the RI2 per-part packaging hint (`in-document` → one file/one AST,
e.g. slides+notes → one pptx; `standalone` → N files/N ASTs, e.g. podcast script + show-notes). The
AST stays single-document (RS1); part identity stays in the IR/identity scheme, `(artifact-id, part-id)`
(F9). The 1-vs-N call is `Format-part-role × target-writer-capability`, resolved by the dispatcher — not
encoded in the AST. (R-9 chunkedhtml verified; edge only, design unchanged.)

## RI7 — IR→AST production path → **A (annotated Pandoc-Markdown, single pinned parse)** — evidence-confirmed

Reconcile emits IR-fitted as **fully-annotated Pandoc-Markdown** (parts = fenced Divs `::: {#part-id
.role}`; provenance = bracketed Spans `[claim]{.tier data-fact=…}`); a **single pinned `pandoc -f
markdown -t json`** yields the AST with all `Attr` intact. Aligns with "don't invent the document model —
use Markdown-envelope + Pandoc-family renderers." **R-6 VERIFIED** (Pandoc 3.10): `fenced_divs` +
`bracketed_spans` round-trip losslessly to JSON **with the reader version + extension set pinned** (RI13
already pins them) → A is deterministic, so the C fallback is NOT triggered. (The R-4 provenance-leak fix
is a separate *writer*-side pre-serialize filter — unrelated to this reader-side path.) Rejected: B
(hand-build JSON — high-code/bug) and C (direct-JSON hybrid — unneeded now A is verified).

## RI10 — Persistence model + new `fitted-id` identity key → **RATIFIED** (additive to Q17)

Persist: **IR-canonical** keyed `artifact-id` (mandatory, immutable — the single re-render source);
**IR-fitted + Pandoc AST** keyed **`fitted-id = (artifact-id, platform, language)`**; **layer-2 bytes**
keyed `deliverable-id = fitted-id + output-type`; render-manifest/pins keyed `deliverable-id`.

**`fitted-id` = a CACHE KEY, additive to Q17 (a strict projection of `deliverable-id`, output-type
dropped).** Its sole purpose: name the **reusable reconcile output** (one AST) so it serves **every
output-type + presentation** for a platform/language **without re-running the LLM reconcile** — that IS
the "docx now, PDF later without re-composing" guarantee. Compose-once/render-many split: `artifact-id`
keys the compose-once IR · `fitted-id` keys the reconcile-once AST · `deliverable-id` keys the
serialize-many bytes.

**Maintainer clarification (publishing/platform boundary):** the "line" past which content is committed
to a platform is **reconcile** — and it's a **cost boundary, not a lock** (IR-canonical is persisted, so
platform re-targeting is ALWAYS possible via one re-reconcile, never re-compose). `fitted-id` does NOT
move that line — it's unrelated; it merely labels cache entries by platform. **Publishing the bytes to
any destination is external + unbounded** (the system never publishes; responsibility ends at the
id-accessible rendered output). Only a new `artifact-id` (source-commit/dimension change) is a genuinely
different artifact (old persists as lineage).

**→ RENDER/IR walk COMPLETE.** Walked/ratified: RI1, RI3 (+fidelity), RI5, RI7, RI9, RI10. Grounded
mechanism (ratified within the confirmed model): RI2, RI4, RI6, RI8 (**+ the R-4 html5/epub3
provenance-strip filter correction**), RI11, RI12, RI13, RI14, RI15. Feeds reconciliation.

## PRESENTATION dimension design (PD1–PD8) → **RATIFIED** (architect found NO challenge — maintainer's shape won)

Adversarial head-to-head confirmed the maintainer's shape: folding style into render-target entries
breaks encapsulation; into Voice violates orthogonality (Voice→`artifact-id`, Presentation→`deliverable-
id`); parametric sliders lose on ease/usefulness. A separate `rendering / discrete-registry / single`
axis wins on all five mandate axes.

- **PD1 facets:** role=**rendering**, representation=**discrete-registry**, cardinality=**single**;
  override-**projection = NO** (facet-twin of Output-type; cascade-bound, not a constraint-projector).
  One entry = one brand's complete cross-target look.
- **PD2 v1 schema (minimal + grow-hook):** keep only levers that are Pandoc *flags* / hashable *files* /
  per-writer dispatch → `variables`, `highlight_style`, `template`, `reference_doc`, `css`, `pdf`.
  **Defer `fonts` + `margins` INTO `variables`** as the day-one grow-later demo. `variables` = the
  guaranteed hook → **no future typesetting need ever forces a schema break.**
- **PD3 encapsulation (HARD, met):** one interface — `resolve → lower(presentation, writer, output-type)
  → RenderInputs{flags, variables, assets+hashes, engine}`. Dispatcher sees only that flat struct; the
  pin bundle IS its preimage; six-point leak audit passes. **The html5/epub3 provenance-strip filter is
  serialize-owned, NOT a Presentation lever** (a style unit must not disable a grounding guarantee).
- **PD4 application/cost:** serialize step 2b (writer call) on the persisted AST — **one call, no LLM, no
  re-serialize**; cheapest RI11 tier (parallel to output-type). RI12/RI13/RI14 wiring specified
  (pdf-engine resolves render-target default → Presentation override → pinned).
- **PD5 identity:** `deliverable-id` gains `presentation` (additive to Q17); does **NOT** touch
  `artifact-id` (look ≠ content) **nor `fitted-id`** (AST is presentation-INDEPENDENT → one AST serves
  all looks). With `plain` as the CA6 floor, shipping the dimension = **zero id-churn.**
- **PD6 delineations:** Format=structure@compose · Platform=routing/limits@reconcile · Output-type=writer
  selection · reshape=LLM content-restructuring@pass-1 · Presentation=deterministic style@serialize.
  "Split to slides" = reshape; "make slides corporate" = Presentation.
- **PD7 defaulting:** a built-in **`plain` framework entry as the schema floor — NOT mandatory-global**
  (mirrors CA8: Pandoc built-ins ARE the fallback, as Platform was excluded). Inherits SV10/SV4/SV5/
  Q15/SV11.
- **PD8 B-later/external:** Presentation does NOT own `writer`/`side` (those = render-target, RI12).
  RenderInputs rides the identical channel internal + external; for `side:external` it folds into the
  RI14 contract; DocBook5/TEI/ICML/pro-renderer style absorbed additively via `variables`/`template`
  keyed by writer → fixed-layout EPUB + bespoke PPTX with no special-casing.

Both HARD requirements (encapsulation via `lower→RenderInputs`; start-small-grow-later via minimal v1 +
`variables` + additive SV) met and load-bearing. **Reconciliation:** add Presentation to the matrix axes
+ `deliverable-id`; add the serialize-owned html5/epub3 provenance-strip filter.

**→ RENDER + PRESENTATION design COMPLETE.** Remaining: the API/contract architect (LAST, preceded by
the maintainer's API gaps/inconsistencies discussion), then reconciliation → definitive design doc.

---

# API / CONTRACT — maintainer brief (feeds the LAST architect; the architect designs the vocabulary)

Maintainer directive: **an architect designs the API vocabulary from these rulings + requirements — NOT
the main session.** This brief is the input.

**Grounding use cases (the design space):**
- **(a)** a wrapper website / native macOS app that **spawns headless Claude Code CLI sessions** for the
  pipeline as needed (interactive + discovery).
- **(b)** several **disconnected n8n workflows**, driven by a DB / Airtable / spreadsheet, running
  automated end-to-end publishing **autonomously + continuously** — NOT one big workflow but many small
  ones that each get the context they need and **pass or store it for pickup by another** workflow, some
  of which call the headless pipeline.

**Transport (HARD):** the pipeline **IS a headless Claude Code CLI session on the Claude SUBSCRIPTION —
NEVER API keys.** One invocation = `verb + params + (optional session-token) in → results +
session-token-out`. Not a long-running server; synchronous CLI contract.

**Statelessness (F-model):** the system persists **WORKSPACE** state (folios, artifacts) but **NEVER
session** state — the external actor holds the session token (in its DB/sheet) and hands it back.

**Verb/endpoint categories (starting point; architect finalizes):**
1. **Read / Discovery** *(the biggest gap — F-model was generation-only):* `list <type>` (+ simple
   filters) and `get <type> <id>` (detail), over: schemas, dimensions, dimension-entries, recipes,
   folios, folio-members, artifacts, deliverables, sources, presentations, folio-types, … .
2. **Generation / Session:** `begin-session`, `continue-session` (a **closed action vocabulary** — the
   maintainer's original open-endedness concern).
3. **Folio management:** `create-folio`, `add-to-folio`.
4. **Output / Retrieval:** `emit-manifest`, `fetch-by-id` → **bytes OR a workspace path/link** (so it's
   accessible later; path preferred for n8n/publisher).

**Four CROSS-CUTTING requirements (all verbs):**
- (i) **Transport** (headless CLI / subscription, above).
- (ii) **Workspace-scoped ISOLATION on every call** (rule 2 — an actor never sees another workspace's
  folios/artifacts; enforced by the API, not by trust).
- (iii) **Id-addressability + reproducibility pins:** artifact / fitted / deliverable(+presentation) /
  folio / part / session ids; each run pins `schema_version` (SV2=B global), source-commit, tool pins.
- (iv) **TYPED RESULT / WARNING / ERROR CONTRACT (maintainer requirement — for graceful divert/degrade):**
  per-item status `ok | warn | block | needs-input` (SM1 block-and-report: a per-item block NEVER fails
  the batch; other fanout continues); each non-ok result carries a **stable machine-readable `code`** +
  category + context (item/dimension/limit/id) + a **remediation hint** (so callers divert or degrade
  deterministically, not by parsing prose); a **discoverable code set** (`list codes`). Taxonomy is a
  CONSOLIDATION of existing rulings, not new invention: `hard-limit-exceeded`(block, CA9) ·
  `advisory-constraint-overridden`(warn, Q3/Q4) · `nonsensical-pairing`(warn, Q4 lint) ·
  `drift-block`(block, CM6) · `out-of-window`(block, CM2) · `empty-pool`(block, SM1) ·
  `low-confidence-grounding`(warn, RI3/INFERRED-AMBIGUOUS) · `capability-infeasible`(warn/block, RI12) ·
  `ambiguous-migration-decisions`(needs-input, CM5 worklist).

**NEW maintainer requirement — runtime per-ATTRIBUTE overrides:** a caller can supply **overrides for
SELECT dimension attributes (NOT entire entries)** via session params, to make **tests + one-off runs**
easy to customize. This is the **API face of CA5** (ephemeral, run/session-level, non-persisted override)
**+ CA7** (bind VALUES at M2; **never redefine entries** at M1). So: attribute-value overrides at the run
layer, ephemeral, captured in `artifact-id` lineage (Q17/CA6) but never persisted as config.

**Open sub-questions the architect resolves (options + recommendation each):** the closed
`continue-session` action vocabulary; **batching granularity** (one item / batch+cursor / whole plan —
the disconnected-workflow pattern leans batch+cursor); `fetch-by-id` **bytes-vs-path** default;
**self-describing discoverability** (`list actions` / `list types` / `list codes` so callers don't
hardcode); **member→deliverable resolution at `emit-manifest`** via per-member pins / emit-time targets
**NEVER folio state** (folio directive); how the **RI14 layer-3 contract** is emitted for `side:external`
targets; **publishing stays external** (system emits output + contract, never publishes).

---

# API / CONTRACT DECISION WALK (architect: api-contract/report.md)

**Governing principle (ratified via API1):** the session **token is a CURSOR, not a capability gate.**
Only **compose/generation** is session-bound (an artifact-id = hash of its resolved plan). **Everything
post-compose** (render, folio ops, retrieval, discovery) is **id-addressed + token-OPTIONAL** — each a
standalone verb AND mirrored as a `continue-session` action. This is what lets disconnected n8n workflow
2 render/fetch workflow 1's artifact by id with no token.

## API1 — verb/action line → **RATIFIED** (+ A1a keep both · A1b keep both)
- **A1a → keep BOTH `create-folio` AND `begin-session(target_folio=id|auto|none)`.** `create-folio` =
  the disconnected create-empty-first-store-id-target-later pattern (use case b); `auto` = one-shot
  inline convenience (use case a). Neither subsumes the other.
- **A1b → `render` is BOTH a standalone verb AND a `continue-session` action.** Workflow 2 renders
  workflow 1's artifact **token-free**, by artifact-id (post-compose is token-optional).

## API fixed policy (architect implemented from prior rulings; PACKAGE-RATIFICATION PENDING)
- **API2 closed `continue-session` action set:** `generate-next · render · add-to-folio · emit-manifest ·
  fetch · status · list/get`. Overrides are NOT an action (fixed at begin-session, CA7 collect-once);
  render coordinates (platform/language/output-type/presentation) are render-time selections, not
  content overrides.
- **API3 token contract:** F4=C inspectable + integrity/version/workspace/**plan-hash** stamp; carries
  inputs + cursor + produced-ids + pins + folio-id reference; never persisted; lost-token-survivable.
- **API4 discovery:** closed type list + meta-types; minimal `field op value` grammar; `provenance` +
  lineage filters (F1 "what did run X produce"); self-describing `list actions/types/codes`.
- **API5 per-attribute overrides:** `"<dim>.<attr>": value|op` at begin-session → L6 run rung → M2 bind
  (CA7), ephemeral (CA5), captured in `artifact-id` delta-vs-floor (CA6). **Hard M1 GUARD:** binds a
  value to a declared attr of an already-selected entry ONLY — can never add an attr, pick an entry, or
  touch schema (→ `invalid-override`).
- **API6 member→deliverable:** emit-time `member_targets` / per-member pins, **never folio state** (folio
  DIRECTIVE); RI14 layer-3 payload (AST + sidecar + part structure + metadata bag + language) rides
  `emit-manifest` for `side:external`; folio stays open; SSOT never written from the manifest (F7).
- **API8 typed result contract:** one `ResultItem` shape everywhere; **per-item block NEVER fails the
  batch** (SM1); consolidated codes + a contract-code tier (`invalid-override`/`isolation-violation`/
  `invalid-token`/`unknown-action`); a **machine `remediation.action`** (divert/degrade without parsing
  prose); discoverable via `list codes`.
- **API9 reproducibility:** pin `schema_version` (SV2=B global) + source-commit + RI13 render tool-bundle;
  idempotent on artifact-id/deliverable-id; optional `idempotency_key` for mint verbs (n8n retry safety).

## API10 — flags to reconciliation/build
Subscription-transport statelessness + n8n→headless / **Graphify serve-MCP + output-path flags are
UNVERIFIED** (largest open item → docs-researcher before build; contract shape is transport-agnostic).
Also: D1 blocks the literal override/param encoding; reserve `fitted-id` + `presentation`-on-
`deliverable-id` in the identity spec; **concurrent workspace-write locking** (same-folio / SSOT) is NOT
solved by session-statelessness (needs a lock design); `scripts/migrate.sh` stays OFF the external API.

## API7 — batching granularity → **RATIFIED (batch+cursor as the SEQUENTIAL mode)**
- **batch+cursor** is the sequential consumption mode: `begin-session` defaults to **plan-only**;
  `batch_size` default small; `all` = whole-plan one-shot; each returned token is a **resumable
  checkpoint** (F3/F4). This is ORTHOGONAL to parallelism — it does not foreclose it (see PC block).
- Rationale: fits the disconnected-workflow pattern (use case b) where each call advances a durable
  cursor; the one-item and whole-plan modes are the endpoints of the same knob.

## PARALLELISM + WRITE-SAFETY — commissioned (architect: parallelism-concurrency/report.md, pending)
**Maintainer requirement (verbatim intent):** *"the system will give the caller the exact work batches
the caller can safely parallelize, and make writes safe so there is no repeated work, missing work, or
collisions on write."* → the **SYSTEM computes and returns a parallelization plan** (the exact disjoint
safe-to-run-concurrently batches + dependency structure); the caller receives safe batches, it does not
reason about safety itself. Three guarantees, each to be MECHANIZED by the architect: **no repeated work**
(idempotent id-addressed items + claim/commit), **no missing work** (partition is a complete cover; every
item in exactly one batch; dropped/failed item detectable), **no write collisions** (concurrent batches
have disjoint write targets, or shared targets — same-folio append (F2), SSOT status rows — are serialized
via a named mechanism).

**Grounded shape (feasibility, not the design — architect owns the design):** parallelism is the intended
shape because the resolver fans out to *idempotent, commit-pinned, id-addressed* items (mission; Q17/CA6).
The **cursor is sequential** (one advancing position) — parallelism does NOT come from racing one token,
but from **partitioning the plan into disjoint id-keyed subsets** + **token-optional id-addressed calls**
(API1). Natural pattern = **serial plan gate → parallel fan-out**; within one item compose→reconcile→
serialize is serial, across items every stage is parallel. The unsolved piece = concurrent WRITES to shared
workspace state (folio membership / SSOT), i.e. the API10 lock item — now assigned to this architect.
Decisions will be numbered PC1, PC2, … and walked one at a time.

### PARALLELISM DECISION WALK (architect: parallelism-concurrency/report.md)

**Foundational insight (accepted, underpins all PC):** disjointness is ALREADY a property of the identity
scheme — the system exposes it, it does not manufacture it. Distinct artifact/fitted/deliverable ids ⇒
distinct output files ⇒ collision-free by construction; every shared *input* (IR-canonical, AST) is
immutable/read-only. The ONLY two genuinely-shared mutable write targets in the whole system are **folio
membership** and the **SSOT row** (the ASF §8 flag). Everything else needs zero coordination. Dependency
graph is an intrinsic 3-level forest (artifact-id → fitted-id → deliverable-id); serial within an item,
independent across items; **v1 has NO cross-item edges** (deep-folio member-from-member deferred, Q12).

## PC1 — parallel-plan shape → **RATIFIED (D: wave-structured DAG with shard tags)**
- Plan = ordered list of **waves** (wave = dependency depth); each wave = a set of id-keyed units that are
  mutually independent (fully parallel within the wave); each unit ALSO carries `prereqs` (ids that must
  exist first) + a `shard` tag (its root artifact-id) + the plan carries `suggested_width` (PC8).
- **Three readings from ONE structure:** simple caller reads wave-by-wave ("run these N, then these" — the
  maintainer's literal phrasing); sophisticated caller pipelines off `prereqs`; n8n groups by `shard` for
  row-per-item chains. Superset of options A (strict waves) and C (item-shards) without B's (full DAG)
  "caller must schedule" burden.
- **v1 exposes exactly two waves:** wave 0 = compose, units keyed by `artifact-id`, driven by
  `continue-session {generate-next, only:<artifact-id>}` (compose = the one session-only capability, API1);
  wave 1 = render, units keyed by `deliverable-id`, driven by the **token-free** `render` verb (API1),
  each doing reconcile (cached by `fitted-id`) + serialize. Obtained via `begin-session(want_parallel_plan
  =true)` — no new verb (API7 plan-only default).
- **Rejected:** A (loses per-item pipelining), B (pushes scheduling/safety onto caller — violates the
  requirement), C (hides stage structure). Accepted tradeoff: D's plan object is richer (`prereqs`+`shard`
  even though v1 barely needs them) — justified because those fields absorb the deep-folio cross-item edge
  later with ZERO structural change (a dependent compose lists its predecessor in `prereqs`, lands in a
  later wave).

## PC3 — no repeated work → **RATIFIED (Layer 1 + Layer 2)**
- **Layer 1 (always on) — idempotency floor:** re-running any unit by id is a no-op if its output exists
  (API9); each stage commits via **write-temp-then-atomic-rename** (wholly absent or wholly present, never
  partial/corrupt). Correctness floor; but alone it still burns LLM compute twice on the same id.
- **Layer 2 (ratified) — lease-based CLAIM REGISTRY:** before expensive work for an id, atomically claim
  `{id, holder, lease_expiry}` (atomic create-if-absent). Outcomes surfaced through the API8 envelope:
  claim-free→do+commit+release (`ok`); already-materialized→skip (`ok`/`already-materialized`);
  live-lease-held→skip (`warn`/`claim-held`, caller moves on / polls by id); expired-lease→steal+re-drive
  (safe: idempotent+atomic) (`ok`/`lease-expired-redrive`).
- **Why both (grounded):** the requirement was "no repeated **work**," not just "no corrupt output" —
  Layer 1 alone repeats the compute; subscription-metered transport (PC8) makes wasted compute expensive.
  Backstop: the **fitted-id is ALSO a claim key**, so many wave-1 render units sharing one fitted-id run
  the reconcile ONCE (first claims; rest serialize from cached AST) → even a naive fan-out-everything
  caller never runs the same reconcile twice.
- **Accepted tradeoff / boundary note:** Layer 2 adds a small PERSISTED workspace-side lease table. This
  does NOT violate statelessness — ASF §3.6 statelessness was about *session* state (pushed to the actor);
  ASF §8 explicitly left concurrent-write coordination to be designed, and this is it. The lease table is
  workspace-side, self-expiring (no unbounded GC), never carried in the token. Build must own it. On-disk
  encoding waits on D1 (PC10); atomic create-if-absent primitive → docs-researcher (PC10).

## PC8 — rate-limit backpressure / parallel width → **RATIFIED (as revised by PC11: INSTANCE-scoped cap)**
- Data-parallelism is effectively unbounded (all wave units independent); the TRUE ceiling is the
  **subscription account** — concurrency = multiple concurrent headless Claude Code CLI sessions on ONE
  account (F10). So the system returns `suggested_width = min(wave-unit-count, policy cap)` and the caller
  never needs to know the account's limit.
- **REVISION via PC11b:** the cap is **INSTANCE/account-scoped, NOT per-workspace** — per-workspace caps
  don't compose (2 workspaces × cap 5 = 10 sessions vs one account). `max_parallel_sessions` governs the
  shared account; a per-workspace cap survives only as an optional sub-limit beneath it, never a substitute.
- **Typed backpressure, never a crash:** a session that hits a rate/concurrency limit surfaces the unit as
  `warn`/`block` code `rate-limit-backpressure` + `remediation.action = retry-after(+retry_after)|reduce-
  width` (API8 divert/degrade policy). Data-parallel work is throttled by subscription POLICY, not by false
  data dependencies.
- **Honest caveat (why PC11 was required):** the account's ACTUAL simultaneous-session + rate limits are
  UNVERIFIED (published limits may be vague/absent for headless-CLI-on-subscription) → docs-researcher gate,
  now backed by the PC11 dataset rather than a guess.

## PC11 — backpressure CAPTURE / observability → **RATIFIED (B+ : capture + advisory `recommended_width`)**
Closes the PC8 "vibe" gap the maintainer caught: PC8 EMITS the signal (source) but never PERSISTED it (no
sink), so the cap stayed a guess. PC11 adds the sink + aggregation.
- **PC11a what to capture (all operational, ZERO content):** the load-bearing metric is `observed_inflight`
  — the concurrency actually SUSTAINED at the instant backpressure hit (read from the live presence-lease
  count) — plus interval rollups (sessions started/completed, peak_inflight, units_done=throughput,
  claims_stolen/redrives/already_materialized=PC3/PC7 health). A tuner derives the **knee** (max sustained
  concurrency before onset = the real cap). **No artifact/deliverable/fitted ids recorded** (unneeded for
  tuning; cleanest isolation posture).
- **PC11b scope — INSTANCE/account-scoped, spanning workspaces (answers the maintainer's subtlety):** two
  small instance-scoped structures, siblings to PC3/PC4 one scope up — (1) a **self-healing presence-lease
  registry** (reuses the PC3 lease primitive; count of live leases = account-wide in-flight concurrency;
  dead worker's lease self-expires → no drift/GC) — this is HOW account-wide concurrency is observable
  despite workspace isolation: sessions in workspace A and B register in the SAME registry, seeing only a
  COUNT, never each other's content; (2) an **append-only telemetry log** (collision-free like PC4 folio
  markers; local append, OFF the subscription critical path so capture never causes backpressure). Rejected
  a bare atomic counter (a crash never decrements → drifts high).
- **PC11c isolation compliance (rule 2/4 + never-surface-secrets — HELD):** operational rate/concurrency
  metrics are NOT client content, so instance-scoping does not violate rule 2 (which isolates client DATA).
  Record embeds: NO content, NO ids (even hashes — omitted as unnecessary), NO client/workspace identifier
  by default (optional slug-only diagnostic tag OFF by default → record is client-agnostic), NO secrets
  (presence `session_ref` = opaque random lease token). **Mechanism = `provenance: framework` (public); DATA
  = `provenance: instance` (gitignored)** — same split as `instance/profile.md` + BO2 brand values, keeps
  public framework empty of it (rule 4).
- **PC11d tuning loop → B+ (RATIFIED):** at `begin-session` the system computes a READ-TIME statistic over
  the recent telemetry window (max sustained `observed_inflight` below onset, minus margin) and returns an
  **advisory `recommended_width` alongside `suggested_width`**, with a `warn` when it's below the configured
  cap. **NEVER auto-applied** — `suggested_width` still = min(units, instance cap); the user's config stays
  authoritative. Q3-faithful (surface, don't bend config; mirrors SM1-C "suggest, user confirms" / SM3
  "warn, don't auto-relax"); PC8/PC9 runtime backoff remains the safety net. **Rejected C (AIMD auto-tune)**
  — reserve the hook only: CLI-per-invocation transport (F10) has no persistent controller (any AIMD =
  reconstruct-from-log each run, which IS B+), risks Q3 overstep (auto-overrides the user cap), can oscillate
  vs an opaque bursty limit; the B+ dataset is exactly what a later AIMD would consume → C stays cheaply
  additive. **Rejected A (NONE)** = the gap. B (pure capture) was the maintainer's floor; B+ chosen as the
  strictly-additive, still-advisory step up.
- **PC11e flags:** two NEW persisted instance-scoped structures (append-only telemetry log + presence-lease
  registry) inherit PC10's atomic-create/append/atomic-rename assumptions → docs-researcher (esp. synced/
  network FS); D1 fixes their on-disk encoding; needs a new instance-owned `instance/ops/`-style path in the
  repo map (gitignored public; no Q15-guard conflict — mechanism public, data instance/gitignored); the
  **subscription-limit docs-researcher item is UPGRADED** — it now VALIDATES published limits against the
  PC11 collected dataset rather than guessing (concrete closure of the PC8/API10 transport gap). Capture is
  default-on (cheap, content-free), disable-able via setting.

## PC12 — INV-CORRECTNESS (SSOT-Independence Invariant) → **RATIFIED**
Direct answer to the maintainer's question ("idempotency + lock must hold even with a CSV + serial writes —
is that what will happen?"): **YES**, now a NAMED, CI-enforced invariant so it cannot silently regress.
- **The invariant:** correctness — idempotency (no repeated work) + the mutual-exclusion lock (no two
  workers materialize one id) — is enforced **SOLELY** by (1) content-addressed OUTPUT EXISTENCE +
  atomic-rename commit and (2) the PC3 claim/lease registry, and **NEVER** by the SSOT. So the SSOT backend
  (CSV vs Sheets/Airtable) + its write-serialization affect **only** status bookkeeping; idempotency + lock
  hold IDENTICALLY under a local-CSV serialized SSOT, PROVIDED the FS supplies atomic create-if-absent +
  atomic rename (PC10 primitives, orthogonal to the SSOT choice). Build asserts the CONTRAPOSITIVE: no
  compose/render/claim/sweep control-flow decision reads the SSOT.
- **Four write targets (roles fixed):** content-addressed outputs = IDEMPOTENCY AUTHORITY (existence=done);
  claim/lease registry = LOCK AUTHORITY; folio append-set = membership record (NOT a generation gate); SSOT
  row = STATUS BOOKKEEPING ONLY, never consulted. Sweep (PC5) reads materialized ids, never SSOT rows.
- **Rule 3 reconciled by DOMAIN-SEPARATION:** SSOT stays sole authority for the status/progress domain
  (rule 3 unchanged); execution-correctness ("done?/claim?") is a DIFFERENT domain answered from work-product
  existence + claims, outside rule 3's scope. SSOT = a MONOTONIC PROJECTION of materialized state (one-way,
  never feeds a decision). "SSOT for status" (true) ≠ "SSOT decides idempotency" (false).
- **Crash-safety by ORDERING:** S0 idempotency pre-check → S1 acquire claim → S2 work→temp → **S3 atomic-
  rename = materialize/commit** → S4 folio append → **S5 advance SSOT (last, side-effect-only)** → S6 release
  claim. Critical section = S1..S3; SSOT write is last, outside it. Every crash point proven benign; the
  maintainer's worry case (crash after S3 before S5) = id exists + SSOT lagging → re-drive is `already-
  materialized` no-op (LLM skipped) then advances the row. Proven property: **the SSOT is a LAGGING MONOTONIC
  PROJECTION — trails reality, never contradicts it; any re-drive/sweep advances it forward.** No ordering
  yields double-work / missing-work / permanently-wrong SSOT; a slow/failing/offline CSV writer only lags the
  human view.
- **Build-enforceability (minimum guardrails):** (1) **signature scoping** — `is_done(id)`/`claim(id)` take
  ONLY output-store + claim-registry handles; SSOT handle never in scope; (2) **CI import lint (the teeth)** —
  correctness modules (`materialize`/`claim`/`idempotency-check`/`sweep`) must NOT import the SSOT module →
  build FAILS if they do; (3) **SSOT interface write-only w.r.t. control flow** — only monotonic `advance()`
  + human reports, no predicate to branch on. Plus a named conformance/property test simulating a crash at
  each S-point under a CSV-serialized SSOT + concurrent workers.
- **Precondition flag (the real gate):** FS atomic primitives (create-if-absent + rename) must hold on the
  ACTUAL workspace store — orthogonal to CSV. Verify (docs-researcher), esp. synced/network FS (iCloud/
  Tailscale) where rename atomicity may NOT hold; if unavailable → a DB commit substrate is required (do NOT
  assume). Robustness bonus: even a TOTAL SSOT outage leaves correctness intact (ids + claims are local; SSOT
  re-projects on recovery). D1 fixes on-disk encodings.

## PC fixed-mechanism package (PC2 · PC4 · PC5 · PC6 · PC7 · PC9 · PC10) → **RATIFIED (backstopped by PC12)**
Grounded implementations of prior rulings, ratified as a package:
- **PC2 complete-cover + disjointness:** plan = deterministic exactly-once cover keyed by settled ids;
  disjoint-by-construction; no-miss DETECTABLE via re-resolve+diff (expected vs materialized ids), not a
  tracker. (API9 idempotency lifted to the whole plan.)
- **PC4 no write collisions:** id-keyed writes disjoint; **folio = lock-free append-only marker set** (one
  marker per (folio,artifact-id); re-append = idempotent dedupe; ordering advisory F9); **SSOT = per-item row
  + MONOTONIC status** (advance-only; stale worker can't regress a row). Row-atomicity holds Sheets/Airtable;
  **local-CSV → serialize writes through a single writer** (accepted by maintainer; PC12 guarantees this is
  bookkeeping-only, never correctness).
- **PC5 no missing work:** completeness sweep = re-resolve plan ∖ materialized ids; exposed via extended
  `status`/`get plan-progress` (read-only, token-optional → disconnected sweeper works); doubles as the wave
  BARRIER (wave done when materialized ∪ blocked == expected); blocked ≠ missing (SM1 preserved).
- **PC6 serial→parallel handoff:** minimum new surface = `begin-session(want_parallel_plan=true)` + a
  `status` extension. Sequence: serial plan gate → fan out wave-0 (`generate-next{only}`) → barrier via
  status → fan out wave-1 (token-free `render`) → optional `emit-manifest` join. Load-bearing: under parallel
  mode the token is an IMMUTABLE plan-context; progress read from materialized ids (API9), NOT the cursor →
  parallel calls never race on `session_token_out`; keeps pure-function run(...) honest. API7 seq mode
  untouched.
- **PC7 failure/retry:** partial-batch = SM1 (per-item, siblings unaffected); worker-death → atomic-commit
  (no partial id) + lease-expiry → safe re-drive; whole-batch re-drive terminates + idempotent; lease-TTL a
  policy knob.
- **PC9 parallel-path codes:** extend API8 with `already-materialized`(ok) / `claim-held`(warn) / `lease-
  expired-redrive`(ok) / `plan-stale`(warn/refetch-plan) / `collision-averted`(warn) / `rate-limit-
  backpressure`(warn/block); same ResultItem shape + machine remediation.action; NEVER fail the batch (SM1);
  `list codes` discoverable. `plan-stale` = plan_hash mismatch on re-resolve → re-fetch plan, sweep
  reconciles → never a silent skip/dup (Q3).
- **PC10 reconciliation deps:** VERIFY (docs-researcher) atomic create-if-absent + atomic rename + SSOT
  row-atomicity (esp. synced/network FS); D1 fixes lease/marker/row/telemetry encodings; subscription real
  limits UNVERIFIED (→ PC11 dataset-validated); lease-TTL + `max_parallel_sessions` = conservative ops
  defaults; deep-folio cross-shard edge reserved (Q12); identity spec must carry `fitted-id` (RI10) as a
  first-class claimable key.

**PARALLELISM + CONCURRENCY DECISION WALK COMPLETE.** PC1–PC12 ratified. API7 ratified as the sequential
mode; parallelism is additive and keyed entirely on the settled identity scheme. **Reconciliation carries
forward:** (a) new persisted structures — the PC3 workspace-scoped claim/lease table, the PC11 instance-
scoped presence-lease registry + append-only telemetry log — need a home in the repo map (`instance/ops/`-
style, gitignored public; mechanism `provenance: framework`, data `provenance: instance`); (b) the docs-
researcher must verify FS atomic primitives on the real workspace store BEFORE build (the INV-CORRECTNESS
precondition; a DB substrate is the fallback); (c) the CSV single-writer SSOT serializer is the PC4b
backend item; (d) D1 blocks the on-disk encodings; (e) `suggested_width`/`max_parallel_sessions` is
INSTANCE-scoped (revises any per-workspace framing).

## API fixed-policy package (API2 · API3 · API4 · API5 · API6 · API8 · API9) → **RATIFIED**
Implemented by the architect as the direct consequence of prior rulings (CA5/CA7, folio DIRECTIVE, SM1,
SV2, the identity scheme); ratified as a package. Details already logged above under "API fixed policy."
Note API8's code taxonomy was extended by PC9 (parallel-path codes, ratified). **Sole live dependency: D1**
blocks the LITERAL encoding of API4's filter grammar + API5's override params (mechanism settled, encoding
waits on D1 — now commissioned).

## D1 — serialization/encoding → commissioned (architect: serialization-d1/report.md, pending)
Last open design item before reconciliation. The most cross-cutting flag — blocks the literal encoding of
SV4 (schema definition), CM3 (combine operators), API4 (filter grammar), API5 (override params), and the
PC10/PC11/PC12 machine records (leases, folio markers, SSOT rows, telemetry, IR).
- **Already fixed → D1 ratifies as a MAPPING, does not reinvent:** IR + render interchange = JSON (RI1/RS1);
  human-authored config/registries = Markdown + YAML frontmatter (repo live convention + `provenance:`);
  SSOT = the tracking spreadsheet (CSV/Sheets/Airtable); wire/API payloads = JSON.
- **Genuinely-open core the architect designs (D1.0–D1.4):** (D1.0) the surface→format governing principle
  (per-surface-class, not one-format-everywhere) + the rule for classifying a NEW surface; (D1.1 — THE HARD
  CORE) **one unified operator/expression mini-grammar** reused across CM3 combine-operators + API5 override
  `<dim>.<attr>:value|op` + API4 `field op value` filters — key fork: compact **string mini-DSL** (human-
  writable, needs a parser, error-prone) vs **structured object** (verbose, unambiguous, no parser), and
  whether config-surface + wire-surface share ONE encoding or the same SEMANTICS via two syntaxes over one
  canonical AST; (D1.2) machine-record encodings — JSON vs **JSONL** for the two append-only logs (PC4 folio
  markers, PC11 telemetry), content-free per PC11c; (D1.3) SV4 schema-definition format + how the single-
  integer `schema_version`/`definition_version` (SV2=B) stamps encode; (D1.4) reconciliation flags + the
  explicit list of items D1 UNBLOCKS.
- **Process ruling (maintainer chose A):** a dedicated D1 architect pass NOW, walked one-at-a-time like the
  rest, THEN reconciliation — so reconciliation FOLDS a ratified D1 rather than silently originating it.

### D1 DECISION WALK (architect: serialization-d1/report.md)

## D1.1 — unified operator/expression grammar → **RATIFIED (C: one canonical AST, two surface syntaxes)**
- **One canonical AST** — `Bind(path, bind_op, operand)` (CM3 combine + API5 override) and `Pred(path,
  pred_op, operand)` (API4 filter); `path = dotted ident(.ident)*`; `bind_op ∈ {replace, union}` (set-
  subtract `-` reserved, out of v1 per CM3); `pred_op ∈ {eq, in, prefix, ge, le, gt, lt, range}`; operand =
  §3.10 type literal.
- **Two surface syntaxes over that ONE AST:** human/frontmatter → **terse string** (`tags+: [c]`,
  `voice.formality: 2`, `field op value` for CLI — CM3's ratified ergonomic form); wire → **structured JSON
  object** (`{"path","op","value"}` — the exact API4/API5 shapes, now formalized as this AST's wire
  rendering). Same semantics, two renderings, **one validator + one operator vocabulary** → the three
  surfaces cannot drift.
- **Why C (grounded):** matches the D1.0 author/consumer split (humans author frontmatter, machines author
  wire — neither pays the other's cost); the **operand rides the host-native literal** (YAML seq / JSON
  array), so the ONLY custom parsing is the dotted-path + operator token (a tiny bounded grammar, not a
  general expression language); CM3 already committed to the inline `+`/`=` operator so the incremental
  parser cost is minimal. **Rejected A** (string-DSL everywhere — forces wire callers to build/escape DSL,
  injection/quoting bugs, bigger parser) and **B** (structured-objects everywhere — kills CM3's terse
  frontmatter ergonomics). **Accepted cost:** a small custom string parser for frontmatter path+op (D1.4
  bounded build item) — two thin syntaxes to keep in sync, but over one AST, largely pre-accepted at CM3.
- **`=` disambiguation:** `=` = replace in a `Bind`, = equals in a `Pred`; never co-occur (binding block vs
  filter arg) + the AST tags node-kind → no semantic ambiguity.

## D1 package (D1.0 · D1.2 · D1.3 · D1.4) → **RATIFIED**
- **D1.0 surface→format principle:** per-surface-CLASS mapping keyed on dominant author/consumer — human
  config/registries = MD+YAML-frontmatter · schema = YAML · machine records = JSON (streams → JSONL) · wire =
  JSON · SSOT/manifest = spreadsheet. Classify a NEW surface by author (human-prose → MD+frontmatter;
  structured-manifest → YAML; machine → next) then shape (tree → JSON; append-only stream → JSONL; row-per-
  item → spreadsheet). One-format-everywhere rejected (each breaks a surface on its merits). The mapping is
  the anti-drift guard.
- **D1.2 machine-record encodings:** JSON for IR (RI1), Pandoc AST (RS1), PC3 claim/lease (**filename = the
  claimed id = the lock**; content `{holder, lease_expiry}`); **JSONL for PC11 telemetry** (event stream;
  atomic one-line append = the collision-free write); **marker-per-file for PC4a folio membership** (filename
  = artifact-id; collision-proof + free dedupe; JSONL only if single-file preferred); SSOT = tabular rows;
  emit-manifest = tabular work-order rows REFERENCING JSON RI14 payloads for `side:external`. All content-
  free per PC11c/PC12; instance/workspace data gitignored (rule 4).
- **D1.3 schema + version stamps:** schema = standalone co-located `_schema.yaml` (all-frontmatter/no-body
  structured case; SV4=A, framework-only post-SV3); stamps = single global integers (SV2=B) — `definition_
  version` per attribute, `schema_version` per entry (frontmatter, bare int per SV3=B) + pinned per run/
  lineage (JSON token/manifest); NOT an `artifact-id` input (a version bump never churns identity).
- **D1.4 flags + unblocks:** **BUILD-CRITICAL — the "Norway problem":** pin **YAML 1.2 + typed/safe-load and
  validate every value against its §3.10 `type`** so `no`/`yes`/`on`/`off`/numeric coercion can't silently
  corrupt enum/ref tokens (docs-researcher confirms the runtime YAML lib + `---` frontmatter splitter, rule
  8). Other flags: same PC10/PC12 atomic FS primitives (append/create-if-absent/rename — verify on synced/
  network FS); the D1.1 string parser = a bounded build item (grammar spec + tests); the SSOT column schema =
  the PC4b/PC12f backend item; id string-encoding (safe as filename AND JSON key) = **D2's slug template**
  (flagged, not invented). **D1 UNBLOCKS:** SV4 schema format · CM3 combine syntax (satisfies its documented/
  discoverable rider) · API4 filters · API5 overrides · PC10/11/12 record encodings · the manifest↔n8n
  handoff · the entry/attribute/run version stamps.

---

# ===== MAINTAINER DECISION WALK COMPLETE (ALL PASSES) =====

Every open design decision surfaced by the architect passes has been walked one-at-a-time and ratified:
SM · RS1 · CA1–CA10 · the FOLIO DIRECTIVE · SV1–SV11 (+ schema-migration v2, 1-yr window) · BO2 · CM3 ·
RENDER/IR (RI1–RI15) · PRESENTATION (PD1–PD8) · API1–API10 (+ fetch, + the API2–API9 fixed-policy package) ·
PARALLELISM/CONCURRENCY (PC1–PC12) · D1 (D1.0–D1.4). **Next: the RECONCILIATION architect** folds this whole
rulings log + all pass reports into ONE definitive design doc, then maintainer approval → track in the repo →
archive the stale intermediate docs.

**Reconciliation MUST carry these cross-cutting coordination items (collected across the walk):**
1. **Identity spec** carries `fitted-id` (RI10) + `presentation` on `deliverable-id` (PD5) as first-class,
   and `fitted-id` is a claimable key (PC3); `schema_version` is NOT an `artifact-id` input (D1.3/Q17/CA6).
2. **M2 cascade spine** (folio L4 rung REMOVED per the DIRECTIVE): L0 schema-default · L1 entry-default · L2
   global-default(mandatory) · L3 workspace-default · L5 recipe · L6 run. Widen M3 for require/span/
   on_conflict (SM R1).
3. **Matrix axes** gain **Presentation** (rendering dim); remove folio `rendering_intent`.
4. **Terminology:** reserve "override" for the run/session layer (CA5); artifact metadata bag (SV3) folds
   into the identity/model spec.
5. **Render pipeline:** serialize-owned html5/epub3 provenance-strip filter (R-4); the D1.1 canonical AST
   (`Bind`/`Pred`) is the ONE grammar behind CM3/API4/API5.
6. **New persisted structures need a home in the repo map:** PC3 workspace-scoped claim/lease table; PC11
   instance-scoped presence-lease registry + JSONL telemetry log; an `instance/ops/`-style path (gitignored
   public; mechanism `provenance: framework`, data `provenance: instance`).
7. **Concurrency:** `suggested_width`/`max_parallel_sessions` is INSTANCE-scoped (governs the shared
   account); INV-CORRECTNESS (PC12) is a named, CI-enforced invariant (correctness ⊄ SSOT).
8. **BEFORE BUILD (docs-researcher gates):** verify FS atomic primitives on the real workspace store (the
   INV-CORRECTNESS precondition; DB substrate is the fallback); the subscription's real concurrency/rate
   limits (now dataset-validated via PC11, not guessed); Graphify serve-MCP + output-path flags (the
   original API10 transport gap); pin YAML 1.2 safe-load (D1.4). `scripts/migrate.sh` stays OFF the external
   API. Transport = Claude subscription, NEVER API keys.
9. **Open downstream design item flagged by D1:** **D2 — the id slug/string-encoding template** (ids must
   encode safely as both filenames and JSON keys) — not yet designed.

# RECONCILIATION + DETAIL-DESIGN PROCESS (maintainer directive, ruled)

- **D2 is DEFERRED but MANDATORY** — it must be designed before build; assigned to the detail-design pass.
- **Phase A — the definitive doc, skeleton-first:** (A1) a FRESH reconciliation architect produces the
  SKELETON (section tree + what-folds-where + placement proposal), no prose fill; (A2) a FRESH adversarial
  architect challenges the skeleton; (A3) a FRESH reconcile/fix architect reconciles the adversarial
  findings; (A4) maintainer walks/approves the reconciled skeleton.
- **Phase B — detail design, ALL PARTS AT ONCE** (maintainer ruled against part-by-part-as-we-implement):
  (B1) a FRESH architect fills the approved skeleton into the full detailed design in one pass (closing D2
  within it); (B2) a FRESH adversarial architect pass over the whole; (B3) a FRESH reconciliation architect
  pass for the fixes; (B4) maintainer approval → track in repo → archive stale docs (placement/supersession
  per the approved proposal; commit only with explicit approval, rule 7).
- **STANDING ADVERSARIAL CHARTER (applies to EVERY adversarial pass, scoped to what it reviews):** Is the
  design elegant with proper interfaces and entry/exit points? Does it fit with everything else? Does it use
  abstraction, encapsulation, and isolation properly? Is it easy to maintain and extend? Are there still
  gaps that need to be addressed? Is anything over-designed / too complex? Are there any conflicts or race
  conditions?
- **Freshness rule:** every pass above is a NEW architect (no resumed context) so each judges the artifact,
  not its own prior reasoning.

# PHASE A — SKELETON WALK (A4 maintainer approvals)

**Phase A record:** A1 skeleton (reconciliation/skeleton.md) → A2 adversarial (skeleton-adversarial.md:
FIXES-NEEDED, ADV-1..11, no reshape) → A3 reconcile (skeleton-v2.md + skeleton-fix-ledger.md: all 11
applied post-verification, none rejected, +REC-1/REC-2) → A4 walk below.

## A4-1 — the section tree → **APPROVED**
Six parts, 27 sections + 2 appendices, foundations → model → mechanisms → contracts → operations
(skeleton-v2.md part 1). Every ruling family exactly one primary home (coverage matrix, adversary-verified
then repaired); 11 tensions located in-tree, none resolved by the skeleton; one-authority-per-concern held
(identity §7; DIRECTIVE §9.1 with consequences at consuming sections; INV-CORRECTNESS §22.7; §24 = declared
future home of the SSOT row-schema). Migration package retagged MIG-1…7 (kills the CM3 tag collision, T6).

## A4-2 — placement & supersession package → **APPROVED (as recommended)**
No file touched until after Phase B; commits gate on rule 7.
- **Doc lives at `docs/design.md`** (single file; the `docs/design/` 6-file split stays a deferred option if
  Phase B shows the doc is unwieldy — call deferred to then).
- **`docs/mission.md` RETAINED + supersession banner** (dead: §2, §3, §4, §8, §1-MVP, §10.4 D1/D2 rows;
  retained: §0/§5/§6/§7/§9/§10 as living PRD/ops context). Rejected: archive-wholesale + mission-v2.
- **Decision record (maintainer-rulings.md) IMPORTED to `docs/archive/design-record/`** as the provenance
  trail behind Appendix A (framework-generic; maintainer verifies no instance specifics pre-import, rule 4).
  Rejected: external-path citation (untracked _tmp = fragile).
- **`docs/design-decisions.md` ARCHIVED ENTIRELY** (tombstone → new doc; gap-free section map in Appendix B;
  stale claims die with it, supersessions written at flagged sections T2/T4/T5).
- **`docs/operating-model.md` RETAINED + AMENDED** per Q15 (authority for provenance/scope moves to §10).
- **`CLAUDE.md` follow-ups = maintainer-only action list** (matrix paragraph → emergent allow-list + 9 axes;
  rule 3 xref to §22.7; rule 4 guard + §3.9 repoint AT ARCHIVE TIME; rule 5 Q15(ii) extension; repo-map
  refresh).
- **Stale files all dispositioned:** quickstart/README/templates/.claude-readme/state.template =
  retained-with-amendment via the post-approval sweep (§27.4); bootstrap + claude-code-usage retained+swept;
  agents-and-skills-sourcing retained-with-amendment (deleted compatibility filter at its lines 80/124).

## A4-3 — Tension T1 (MVP dimension count) → **RESOLVED: A — the MVP mandate extends to ALL 9 axes**
Q19's "8-dimension" text predates Presentation; the mandate's SPIRIT (every dimension exercised, no
minimal-subset staging) extends to the 9-axis matrix including Presentation. Grounded: PD7's mandatory
`plain` floor entry ships in v1 anyway, so exercising Presentation in the MVP costs ~zero; exempting it (B)
would recreate exactly the staged/partial axis Q19 rejected. Detail pass WRITES §25 accordingly (no flag).

## A4-4 — "folio state" definition ADOPTED + ordering/schedule REMOVED (**MAINTAINER AMENDMENT**)
**(a) Definition adopted (T11 closed):** "folio state" = **folio-LEVEL dimension or rendering intent —
banned, ever**. A **per-member-record deliverable pin is permitted** (member-scoped data that DIRECTIVE
item 5 itself sanctions; the member list is where member records live, not a folio-level opinion). Written
ONCE at §9.2 (xref §21.5).
**(b) AMENDMENT — advisory ordering AND schedule are REMOVED from the folio entirely (Option 2).** The
folio becomes a **pure purposeful set**: id, purpose, folio_type, provenance/scope, member refs + per-member
pins. This AMENDS (maintainer's explicit act, not reinterpretation): F9.3 (advisory order/schedule —
dropped), F2 ("ordered member list" → **unordered member set**; reverse index still derived), the
DIRECTIVE's permitted-metadata list (drops "ordered member refs, advisory ordering/schedule"; sequencing-
relation folio metadata likewise out), and D1.2's marker content (**`{added_ts, pin?}`** — `suggested_order`
dropped). **T9 dissolves.**
**Grounding:** the system never consumes order (generation/render are idempotent, parallel, id-addressed —
PC1; no verb reads it); the only order consumers are publication/consumption, which are OUT (RI15/F10).
Every useful order is externally reconstructable: date/attribute orders from tracked facts (`added_ts`,
coordinates, lineage, source-commit); insertion order from `added_ts`; intra-work sequence is a SPLIT
(part-ids in ONE artifact, F9/Q8, tracked in the IR per RI2); typed-folio structural order from member ROLE
+ the folio_type's declared structure. The sole non-derivable case — arbitrary hand-curated sequence — is
actor-state by nature (actor-holds-state philosophy; disconnected n8n actors share their own DB/spreadsheet
per use case b) and gets no system home.
**Two conditions WRITTEN at the detail pass (cheap, no new mechanisms):**
(i) member-listing/discovery surfaces MUST expose the sortable facts (`added_ts`, coordinates, lineage,
pins) so any derived ordering is computable client-side (§9.2/§21.5);
(ii) typed-folio member **roles** MUST be recorded in tracked data so structural order is reconstructable —
the recording locus (member record vs artifact lineage) is a small detail-pass decision, flagged for review.

**PHASE A COMPLETE — skeleton approved (A4-1..4). Phase B (detail fill, all parts at once, closes D2) may
proceed. The Phase B architect receives A4-3/A4-4 as rulings to WRITE, superseding the older logged text of
F2/F9.3/DIRECTIVE-metadata/D1.2 where amended.**

# PHASE B — B4 MAINTAINER WALK (over design-draft-v2.md)

**Phase B record:** B1 detail fill (detail/design-draft.md, 2,229 ln; 3 marked design calls; D2 closed at
§7.4) → B2 adversarial (detail/design-adversarial.md: FIXES-NEEDED, ADV-1 BLOCKER + 4 MAJOR + 9 MINOR +
ADV-15 open-item-candidate; all 3 design calls SURVIVE) → B3 reconcile (detail/design-draft-v2.md, 2,414 ln
+ design-fix-ledger.md: all 15 applied post-verification, none rejected, +REC-1..3) → B4 walk below.

## B4-ruling — ENTRY IDENTITY: **A — id in frontmatter + filename MUST equal id, schema-lint enforced**
Maintainer-caught gap (no prior ruling covered entry-identity mechanics; adversary couldn't flag it):
the doc never stated whether an entry's id lives in the filename, the frontmatter, or both.
- **The rule:** every registry entry carries `id:` in its YAML frontmatter; the filename slug MUST equal
  the in-file id; schema-lint (§11.7) enforces the match as part of the validation that already runs (no
  second edit — one-file-add preserved). `x-` prefix is part of the id, present in both carriers (§11.4
  composes). Entry id remains constrained to `[a-z0-9-]` ≤40 (§7.4).
- **What it buys:** duplication-for-editing becomes LOUD (copied file's filename ≠ internal id → CI error;
  kills the silent-new-entry failure); drift impossible (mismatch = error); rename = deliberate two-touch
  act (filename + in-file id), dangling refs still fail loudly at M1 (unknown entry id = error, never
  silent). History already rename-immune (content-addressed outputs + preimage recorded in IR binding).
- **Rejected:** B filename-only (duplication stays silent), C in-file-authoritative/filename-free
  (duplicate-id ambiguity at M1; breaks file-is-the-entry + the x- filename guard).
- **Rider:** `aliases:` graceful-rename field REGISTERED AS DEFERRED (§26), not built in v1.

**B4 AMENDMENT LIST (applied by the post-walk fix pass, with anything else B4 produces):**
1. Entry-identity rule A above (home: §7.4 or §11.1 + lint rule at §11.7; lexicon entry at §4).
2. One-line definition "an entry's id = its frontmatter `id` = its filename slug" stated ONCE (§4 lexicon),
   closing the definitional gap the maintainer's entries-have-ids question exposed.

## B4-1 — D2 id string encoding (§7.4) → **RATIFIED**
Hash root + structural coordinate suffixes (option 2 of 3): `artifact-id = a-<hex16(sha256 of §7.2
preimage)>`; `fitted-id = <artifact-id>.<platform>.<language>`; `deliverable-id = <fitted-id>.<output-type>
.<presentation>`; `part-id = <owner-id>~<part-slug|pNN>`; `f-<hex12>` folios; `r-<hex16>` runs. Lowercase
safe alphabet `[a-z0-9]`+`-`/`.`/`~` (case-insensitive-FS safe); entry ids schema-lint-constrained
`[a-z0-9-]`≤40 → 255-byte filename bound by construction (~223 worst case); mint-time PREIMAGE CHECK (id
exists w/ different preimage → loud failure, never silent reuse; reads only output-store state →
INV-CORRECTNESS-clean); prefix-typed positional grammar (family from root prefix, level from dot-segment
count, `~` never confusable) → type inferred from the bare string, no side table; claim/marker filenames =
id exactly (no extension), byte outputs may append a conventional extension AFTER the full id. Projection
relations (RI10/PD5) mechanically readable in filenames; prefix-listing free; no index store. Rejected:
opaque-hash-everywhere (needs an index store), full-human-slug artifact-id (255-byte/content-leak).
Survived B2 adversarial attack (case-folding, path length, parsing ambiguity, claim-key safety) + ADV-11
polish applied. D2 (deferred-but-mandatory) is CLOSED.

## B4-2 — T2 folio-type coherence binding (§9.6) → **RATIFIED (binds at the GENERATING RUN)**
- Folio type = framework-shippable blueprint declaring **roles + per-role recipe skeletons — never
  dimension values** (DIRECTIVE item 4); concrete values come from the generating recipe/run.
- **Shared grounding = a run property, by construction:** one typed-folio run = one session pinning ONE
  commit-map (`{source-instance-id → commit}`) + ONE source-subset at `begin-session`, fanning out one
  recipe per role → every member's artifact-id embeds the same pins because they share the run, not
  because the folio stored anything. Precision (ADV-5): shared grounding = **same pool + same pinned
  commits — never same facts** (per-role require/span clauses draw different facts; survivorship in each
  grounding ledger).
- **Regeneration honesty:** coherence reproduces only under SUPPLIED pins (begin-session accepts the
  original run's pins); pin-less later session = current pins = visibly different lineage, never silently
  shared. Regenerated member = NEW artifact-id → duplicate roles legal (append-only membership; consumers
  disambiguate by added_ts + lineage per condition i). Removal/supersede stays §27.3-registered.
- **Roster awareness = run-scoped compose context** — not folio state, NOT an identity input (identity =
  coordinate hash, never content hash; §7 promises coordinate reproducibility, not byte reproducibility).
- **Folio type consumed at generation time only** — post-generation it's declared structure for discovery
  + role-based ordering reconstruction; never touches rendering, manifests, or the cascade.
- Zero new machinery (reuses API9 run pins); the DIRECTIVE's strongest reading; survived B2 (ADV-2/ADV-5
  amendments applied).

## B4-3 — member-role recording locus (§9.6/§9.2, A4-4 condition ii) → **RATIFIED (member record)**
- `role?` joins the member marker: **`{added_ts, pin?, role?}`**. Grounding: the role is FOLIO-RELATIVE
  (same artifact, two folios, different roles) → artifact lineage/metadata bag are folio-agnostic and wrong
  BY TYPE; the member record is the one `(folio, artifact)`-scoped store — same sanctioned locus as the pin
  under the adopted "folio state" definition (A4-4a).
- **Write path (ADV-3, API2 untouched):** `add-to-folio` gains member PARAMS `members: [{artifact_id, pin?,
  role?}]`; identical re-append = dedupe; differing = atomic marker update, `added_ts` preserved, typed
  `member-updated` warn. Member REMOVAL/supersede stays §27.3-registered.
- **Staleness posture (ADV-12):** recorded roles = point-in-time slugs vs the folio type's schema version
  at add-time; member records are machine records, NEVER migrated (MIG-7 migrates config only); an unknown
  slug after a folio-type role rename is surfaced AS-IS — never dropped, never silently remapped.
- **Payoff:** structural order reconstructable from tracked data alone (type's declared structure + each
  member's recorded role, both on every listing surface per condition i); artifact lineage stays free of
  folio-relative data. Survived B2 ("correct folio-relative locus").

## B4-4 — ADV-1 BLOCKER repair (lease-steal race, §22.3/§22.7/G1) → **RATIFIED**
The hole: "expired" ≠ "dead" — a slow-but-alive holder resuming after a steal could plain-rename-OVERWRITE
the stealer's committed output (breaking PC12's "no two workers materialize one id") and S6-release a claim
it no longer held. The repair (threaded through §13.3/§22.3/§22.7/§22.8/G1):
- **(a) S3 commit = atomic NO-REPLACE (create-exclusive) rename** — a late commit LOSES
  (`already-materialized`); exactly one winner per id, mechanically.
- **(b) S6 release = HOLDER-CHECKED** — release only if `holder` = self; mismatch = no-op (`claim-held`).
- Consequences: double-steal / slow-holder resume = cost leak, NEVER correctness leak; new crash-table row
  (holder resumes through S3–S6 post-steal) benign at every point; conformance test gains that exact
  interleaving (REC-3) so the invariant ships TESTED; **G1 gains the no-replace primitive** (docs-researcher
  verifies all three: create-if-absent, no-replace commit, rename). INV-CORRECTNESS's statement now names
  both qualified primitives as its enforcers. Strengthens the ratified mechanism; re-litigates nothing.

## B4-5 — the four §27.3 flags → **1/3/4 REGISTERED + review trigger · #2 PULLED for design NOW**
- **Registered (decide later):** member removal/supersede (v1 append-only + in-place updates is coherent);
  M3-expression × preimage (documented-behavior note stands; adding to preimage = identity churn, needs
  strong motivation); M3 grammar × D1.1 AST (shared vocabulary discipline prevents drift; unification =
  additive polish).
- **B4 AMENDMENT LIST +3:** §27.3 gains a REVIEW TRIGGER — every registered item is re-examined at the
  pre-build gate phase (when G1–G6 run) by an architect pass that designs it or re-registers it with
  reasons. (Fixes the register's no-clock weakness the maintainer identified.)
- **#2 force-re-reconcile → PULLED, architect commissioned (force-re-reconcile/report.md).** Grounding for
  now-not-later: trigger events are rare (platform-constraint edits ~1–2×/yr/platform; tuning-phase strategy
  iteration) but **high blast radius** (one platform edit stales EVERY cached fitted output for that
  platform) and **v1 has NO content-preserving remedy** — regenerate-with-override mints a new artifact-id →
  compose re-runs → NEW TEXT (compose is non-deterministic), destroying the Q16-approved content the user
  wants to keep. "Approved content → re-fit under evolving platform reality" is the pipeline's core value
  path and is currently impossible. Designing now also lands while the invariants it must thread
  (no-replace, preimage, fitted caching) are freshly ratified.

### FORCE-RE-RECONCILE DECISION WALK (architect: force-re-reconcile/report.md)

## FR1 — caller affordance → **RATIFIED (1A: bare boolean `force_reconcile: true` on `render`)**
- On the standalone verb AND the mirrored session action (API1); params only, API2's closed set untouched.
  **The force carries NO values** — by Q3 the redo must use the user's CONFIGURED current effective inputs
  (workspace config; + session L5/L6 if in-session, CA7 collect-once). Want different inputs? Change config
  or pass an L6 override at begin-session — THEN force.
- **Deterministic, retry-safe behavior matrix:** no fit → ordinary first mint (baseline; force no-op on
  miss); matching fit exists → NO mint, `already-materialized` (idempotent re-issue, n8n-safe); fits exist
  none match → mint revision fit + requested deliverable, `re-reconciled`.
- **Remediation wiring:** `render-input-mismatch` gains machine `remediation.action: force-re-reconcile` +
  `current_inputs_digest` in context → caller can re-issue deterministically and predict the resulting
  fitted-id pre-call (API8 divert/degrade discipline).
- **Q3 preserved:** cached-hit-with-warn stays the default; system never auto-re-reconciles/sweeps.
- **Rejected:** 1B inline reconcile-inputs object (CA7 — reconcile is not an override point; second
  injection point + second grammar); 1C new verb (API2 closed).

## FR2 — identity of the redone fit → **RATIFIED (2B: inputs-digest fit-revision) + D2 `_` AMENDMENT**
- **Revision fitted-id = `<artifact-id>.<platform>.<language>_<hex12>`**, hex12 = SHA-256 of the canonical
  **reconcile-inputs preimage** (strategy + effective CA9 hard limits + reconcile-consumed advisory/
  rendering bindings; canonical sorted-keys, CA6 delta-vs-floor → additively-shipped defaults churn
  nothing). Deliverable/part ids inherit the qualifier by prefix → downstream no-replace never blocks.
- **The `fit-binding`** (new, on the IR-fitted envelope, sibling of RI4's artifact binding): preimage +
  digest + full fitted-id + minted_ts. ONE record read by the mismatch warn, the identity digest, AND the
  S0 preimage check → warn-basis and mint-basis can never drift. (Moves reconcile-input recording from the
  per-deliverable render manifest to the fitted level; serialize pins stay per-deliverable.)
- **Unqualified id = the FIRST fit ever minted for the triple, never rebound** → zero id churn on the
  never-forced path. **Unqualified-resolution rule:** (1) recorded digest == current-inputs digest → use it
  (true hit; CONFIG REVERT SELF-HEALS — baseline matches again, no warn no force); (2) none match →
  LATEST-MINTED fit + `render-input-mismatch` warn (Q3 cached-hit-with-warn default; latest-minted over
  always-baseline = respect the user's last explicit act; deterministic minted_ts + lexicographic tiebreak);
  (3) no fit → normal first mint. Reads config + output store ONLY → INV-CORRECTNESS-clean; is_done/claim
  operate on the resolved id, unchanged.
- **Properties by construction:** idempotent (same forced inputs → same digest → same id → S0 no-op); PC3
  claim disjointness (two forcers → same claim key → one LLM run; different-input forces → disjoint ids,
  both legit); prefix-listing intact; preimage check catches hex12 collision/canonicalization bugs loudly.
- **Honest weaknesses accepted:** revision ids don't encode order (minted_ts does — expose-facts
  philosophy); digest stability rests on the fit-binding canonicalization (load-bearing); same-inputs
  re-roll deliberately inexpressible (registered separately).
- **Rejected:** 2A generation counter (structural idempotency failure — same force re-issued mints again
  unless it smuggles in 2B's comparison; latest-generation rule wrong under config revert; needs the same
  D2 amendment anyway); 2C mutable latest-pointer (doesn't answer identity; adds a THIRD shared mutable
  write target to a system ratified on exactly two; 2B computes it statelessly).
- **D2 AMENDMENT RATIFIED (amends B4-1/§7.4, additive):** `_` = fourth separator; grammar `fit-revision :=
  "_" hex12` on the fitted level, at most one per id, flows by prefix. `_` ∉ slug alphabet ∉ hex →
  unambiguous; dot-count level grammar untouched; worst case ≈236 < 255; baseline ids byte-identical.
  Rejected encodings: `~g2` (part-namespace collision; `g2` is a legal role slug), bare dot segment
  (breaks level inference).

## FR3/FR4/FR5 → **RATIFIED (package)**
- **FR3 flow-through & retrieval:** revision-fit deliverables get distinct ids by prefix construction;
  forced render mints fit + ONLY the requested deliverables (RI11 economy preserved at the new revision);
  `fetch-by-id` on old ids = unchanged bytes forever, ZERO currency evaluation (dumb hot path);
  **currency = COMPUTED read-time fields** (`fit_revision`/`fit_current`/`minted_ts` on list/get shapes +
  filters — currency is NON-MONOTONIC (config revert un-stales) so any stored marker = mutable target + lie
  window; blast-radius remedy = `list deliverables {platform, fit_current:false}` + force loop);
  **member pin refined to ID-FORM, FROZEN** (exact deliverable-id string, never re-resolved; annotated
  stale; Q3 — a pin that drifts is not a pin; rejected coordinate-form re-resolving + both-flavors);
  emit-time `member_targets` stay coordinates, resolve via the FR2 rule, warn rides the manifest row;
  superseded outputs RETAINED indefinitely in v1, id-addressed (retention/GC policy registered).
- **FR4 codes & SSOT:** one new code `re-reconciled` (ok); `render-input-mismatch` extended;
  `already-materialized` reused; NO superseded-fit code (currency = field, fetch stays dumb). **SSOT: new
  rows only; old rows untouched** — "superseded" can flip back → never a monotonic-advance status (PC12/
  PC4); one item's commit never writes another's row; SSOT gates nothing. Optional content-free
  `forced_reconciles` rollup counter (PC11c).
- **FR5 review gates:** artifact review STANDS (same approved IR-canonical — the feature's point); every
  revision-fit deliverable takes the FULL Q16 deliverable review (fitted text = LLM rewrite); review
  outcomes attach to deliverable-ids, never transfer across revisions; old deliverables keep their status
  on their old ids; republishing = publisher's domain, external (§2.2).

## FR6 → **RATIFIED (register items) + FR7 COMMISSIONED (serialize-level revision — the contradiction)**
- **Closed:** the force-re-reconcile §27.3 flag. **Registered (pre-build review trigger applies):**
  same-inputs re-roll (nonce; deliberately inexpressible under digest identity); retention/GC policy (v1:
  retain all, id-addressed); stale-fit sweep (caller-composable via `list {fit_current:false}` + force
  loop; any system-side batch = explicit caller act per Q3).
- **DISCOVERED CONTRADICTION → pulled, not registered:** RI11 tier 2 ("writer bugfix → re-run writer" =
  different bytes for an EXISTING deliverable-id) is BLOCKED by the ratified B4-4 no-replace commit — two
  ratified texts that cannot both execute, with a ROUTINE trigger (every writer/tool-bundle/presentation-
  asset update that should propagate). Maintainer ruled: a definitive doc does not ship with a known
  internal contradiction. **FR7 commissioned** (same architect, live design extension): the FR2 mechanism
  one level down — a deliverable-level `_<hex>` serialize-revision qualifier whose preimage already exists
  (the per-deliverable render-manifest pin bundle) — incl. the serialize-level resolution rule, interaction
  with fit-revisions (two qualifiers per id → amends the "at most one `_` per id" grammar line), length
  bound re-check, and emit-manifest semantics.

## FR7 → **RATIFIED (by maintainer order, without walk)**
The maintainer ordered FR7 ratified as the architect recommended, in full: FR7.1 (serialize-inputs
preimage; render-binding as deliverable-level single authority; AST store key → reader-pin digest), FR7.2
(per-LEVEL qualifier grammar, ≤2 per id; 18+164+26+41 = 249 ≤ 255; conditional extension-append), FR7.3
(AUTO-mint serialize revisions, no force flag; `re-serialized` ok; `render-input-mismatch` re-scoped to
reconcile-only; asymmetry principle: consent where costly/content-changing, auto-correctness where free/
deterministic, both loud), FR7.4 (resolution mirrors FR2 w/ auto-mint branch; separate serialize_revision/
serialize_current computed fields; pins unaffected; emit never mints), FR7.5 (FULL Review 2 on every
serialize revision — Q16 completeness preserved), FR7.6 (SSOT new-rows-only; claims unchanged; RI11 tier-2
rewritten → contradiction resolved; GC register note strengthened).

# ===== STANDING EXECUTION MANDATE (maintainer, FINAL — supersedes the walk protocol) =====

1. **The definitive design doc is PRE-RATIFIED.** After the fix pass + verification pass (with ALL
   verification findings applied by a fix agent), the doc is FINAL. No maintainer walk, no ratification
   step. Repo placement proceeds per the approved A4-2 package — EXCEPT `CLAUDE.md`, which remains
   maintainer-only (its edits are prepared as a diff and delivered, never applied by an agent).
2. **NO further maintainer decisions are to be brought.** ALL agent recommendations are ACCEPTED
   wholesale. The coordinator provides NO recommendations, NO plans, NO designs — coordination only.
3. **Plan pipeline:** fresh planner agent → fresh adversarial planner agent → fresh reconciler agent.
   The reconciled plan is ACCEPTED as-is.
4. **Build pipeline, per plan step:** fresh coder agent → fresh reviewer agent → fresh coder agent
   implements EVERY reviewer-recommended fix. Fresh agents every step; no context reuse.
5. **Durable rules REMAIN BINDING on all agents:** source/client repos read-only, always; client
   isolation via workspaces; transport = Claude subscription, NEVER API keys; no secrets in outputs;
   agents never commit. Per rule 7 the final commit proposal is presented at delivery — the only item
   brought to the maintainer besides the finished product.
6. **Deliverable:** a finished, working product. Progress notices only until then.
7. **AMENDMENT (maintainer):** PAUSE after the planner phase completes (planner → adversarial →
   reconciler). The maintainer reviews the final design doc + the reconciled plan at that checkpoint and
   directs whether/how to proceed. NO build agents spawn before that direction.
