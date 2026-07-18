# DR-1..DR-6 — FOUNDATION-COHERENCE / cross-DR INTEGRATION — Architect (mode: RECONCILIATION)

**Pass:** ops-architect, stage 03 of the cross-DR INTEGRATION / foundation-coherence pass. Reconciles
the stage-01 INITIAL ("sound foundation") against the stage-02 ADVERSARIAL (findings A–H). **Class:
read-only. No repo edits, no commit. No code, no implementation plan.** Integration specs WITHIN the
ratified frame only — **no ratified DECISION is re-opened**; every item below is a spec or a
verdict-language correction, and where a boundary answer would require a ratified change I FLAG it
(none did).

**Verified this pass against the LIVE code + SSOT, not the reports** (the adversary can overreach too;
I re-verified each finding at source): `pipeline/ir.py` (`IR_VERSION = 1` L108, exact-equality pin
`doc["ir_version"] == IR_VERSION` L688; `LEDGER_FIELDS` closed 6-field tuple L128-135 with
exact-equality `keys == set(LEDGER_FIELDS)` L510; `TOP_LEVEL_KEYS` closed L139-141;
`_PART_OPTIONAL=("constraints",)` L574); `pipeline/ids.py` (`build_artifact_preimage` returns exactly
`{dimensions, goals, source-subset, source-commit}` L668-671; `_require_artifact_preimage_shape`
`expected = {…4 keys…}`, `set(preimage) != expected` refuses a 5th L749-750); `pipeline/reconcile.py`
(`default_measure` single key `DEFAULT_CHAR_LIMIT_KEY = "max_chars"` = **total leaf-body char length**
L163-165; the terminal gate blocks on `hard-limit-exceeded` L155-157); `pipeline/prompts/writer.md`
(the live 5-rule contract — NO all-prose demarcation, NO `.framing` construct today); `docs/design.md`
§6.5 (EXTRACTED floor a framework invariant "no run and no override can relax it" L465-468), §16/RI5
(localize → reshape → terminal hard-limit gate; the reconcile-inputs preimage's hard-limit set =
"the platform entry's effective hard-limit set" L1520/L1537-38 — **no section addressing**), §17
(RI12/RI14 external = "persist AST + emit the contract payload" L1596-99; `side` excluded from
identity L1638); `docs/known-issues.md` DR-2..DR-6 + GAP-4; and the four ratified reconciliations
(`dr2-style-guides/03`, `dr2-style-guides/07`, `dr4-dr5-templates-style/03`, `dr6-grounding/03`).

---

## 1. THE DEFINITIVE VERDICT

**The DR set is a SOUND FOUNDATION to build on — CONDITIONAL on resolving the complete must-resolve
list in §4.** The adversarial is upheld: the stage-01 "complete-enough, orthogonal, composable,
extensible, generalized" verdict was **too optimistic as written**, and its "five must-resolve-first
items" list was **short by four**. But the adversarial's own conclusion also holds and I confirm it at
source: **no single finding re-opens a ratified DECISION.** The DRs still partition cleanly; the
skeleton (identity disjointness, the precedence chain, the false-deadlock resolution, the `ir_version`
foundation, the self-demarcation ceiling) survives the attack intact (§5). What A–H prove is that
three of the four headline verdicts overreached and four integration specs were missing — all
**correctable within the ratified frame.**

**The three over-stated headline verdicts, DOWN-GRADED to conditional:**

| Criterion (stage-01 claim) | Down-graded verdict | Conditional on |
|---|---|---|
| **1 — "no residual scope duplication"** | **Sound CONDITIONAL on A + E.** One MND boundary (per-section length limit vs Platform artifact-limit) was undrawn (A); the "DR-6 absorbs three grounding flags into ONE chokepoint" claim over-states a two-locus composition (E). | A (§2.1), E (§3.2) |
| **2 — "writer contract coherent, non-contradictory, just dense"** | **Sound CONDITIONAL on B + C.** The `[@key]` classifier as written keys on a "bare" surface DR-6 layer-1 forbids — a genuine contradiction, not density (B); the exemption tail does not "close" (C). | B (§2.2), C (§3.1) |
| **3 — "extensibility REAL / verified additive"** | **Sound CONDITIONAL on D + F.** "DR-4 parses sections without changing the outline-digest" is an unverified assumption about the DEFERRED F1 grammar vs the ALREADY-PINNED normalizer N (D); the K3 "name-S + survive-strip" contract does not cleanly extend to `side: external` (F). | D (§2.3), F (§2.4) |

**Criterion 4 (generalizability) mostly holds**, with one missed landing added to the audit
(`attestation.primary` shape, G — §3.3).

**Honest framing:** A, C, E, F, G, H are integration specs / verdict-language corrections the
foundation audit exists to state (the stage-01 posture is defensible for these). **B and D are
different in kind** — they are places where the report's own CONFIDENCE was the defect (B asserted
non-contradiction where a contradiction exists; D asserted "verified" what is unverified). Both are
resolved below without redesign. The foundation is buildable; the go/no-go list in §4 is the honest
price of entry.

---

## 2. THE FOUR BOUNDARY ANSWERS (integration specs within the frame)

### 2.1 — Per-section length limit HOME (Finding A). The third MND boundary + precedence.

**Verified at source.** `reconcile.py`'s `default_measure` scores a single key `max_chars` = **total
leaf-body character length** (L163-165); §16's terminal gate fits-or-blocks on "the platform entry's
effective **hard-limit set**" (design.md L1520, L1537-38). This is an **artifact/capacity-scoped**
numeric gate with **no per-section addressing**. A section-scoped limit ("abstract ≤ 250 words")
cannot even *address* "the abstract" without DR-4's section grammar.

**THE RULE (the third MND boundary the matrix missed):**

> **A section-scoped numeric limit is a DR-4 STRUCTURAL CONSTRAINT** — section-addressed via the F1
> sentinel grammar, checked at the DR-4 structural gate (base @ compose/Review-1; platform-specific @
> reconcile), severity `error = BLOCK`. **The §16 terminal hard-limit gate keeps ONLY
> artifact/capacity limits** (total length, page/slide count, byte caps) — the `max_chars`-class
> whole-artifact measure it already implements. **The two are disjoint by SCOPE: DR-4 governs
> a named section; §16 governs the whole artifact.** This is the MND boundary DR-4-conformance ⟂
> Platform-artifact-limit, and it is the missing third boundary (alongside DR-2-`mechanical` ⟂ `csl`
> and DR-4-conformance ⟂ §5.2 body-prose).

This is **not** a re-opening: the ratified DR-4 (option b) already scopes "per-section numeric limits"
into DR-4's own conformance field (dr4-dr5 §2.2, "v1 serves WHOLE-SECTION conformance …, per-section
numeric limits, whole-section kinds"). The boundary answer merely *confirms* that home and draws the
line to §16.

**RETRACT the "abstract ≤N words already built" claim.** It appears in the dr4-dr5 §2.2 **(a)
fallback** description (NOT the ratified option-b path) as "abstract ≤N words (Platform hard limit →
§16 gate, already built)." Verified false: the §16 gate has no section addressing, so "abstract ≤N
words" is a DR-4 **build item** (it needs the section grammar), not a §16 reuse. Retracting a
description inside a rejected fallback re-opens nothing.

**Precedence when BOTH apply** (a section limit AND an artifact limit): **neither "wins" — both are
HARD gates whose infeasibility resolves to the SAME action, block-and-report** (there is no
double-block contradiction, exactly as the DR-4×DR-6 and hard-structural×hard-limit cases resolve).
Ordering is fixed by RI5 (see item 4 in §4): the DR-4 structural gate (which owns the section limit)
runs **after reshape**; the §16 terminal artifact gate runs **last**. If a `truncate` needed to fit
the artifact hard-limit would drive a required section below its section min-length (or drop a
required section), the two are **jointly unsatisfiable → block-and-report naming BOTH constraints**
(the joint hard-structural × hard-limit case the stage-01 §3 surfaced; §21.7 supports per-item block —
add the combined DR-4 × §16 context).

### 2.2 — The three-context `[@key]` classifier (Finding B). Redefined over SPAN CONTEXT.

**Verified contradiction.** `writer.md` today has no all-prose demarcation and no `.framing` construct
(read in full). DR-6 layer-1 (ratified) requires **every declarative prose unit** to be a grounding
span or an explicit `.framing` span — **nothing bare** (known-issues L320-322). The stage-01
classifier keys the purely-bibliographic case (K1) on a **bare `[@key]`** — a surface DR-6 layer-1
**eliminates** for any declarative sentence. As written the two ratified specs are jointly
unsatisfiable. The fix is to key the classifier on the **span the `[@key]` sits inside**, not on
bareness:

> **THE CLASSIFIER (three span contexts, not two):**
> 1. **`[@key]` inside a GROUNDING span** `[…]{.TIER data-fact="fN"}` → a **grounding citation
>    (K2/K3)**. It must resolve to a ledger fact (K2: primary in pool) or a ledger fact carrying an
>    `attestation` (K3: scenario-2). DR-6's domain.
> 2. **`[@key]` inside a `.framing` span** → **purely-bibliographic (K1's REAL home).** A
>    rhetorical-context citation ("Prior work examined X `[@jones2019]`") is declarative prose, so the
>    sentence is `.framing`-wrapped and the cite rides inside it. K1 lives HERE — not "bare." It
>    asserts nothing as a pipeline fact: no `data-fact`, no ledger binding, no attestation. Out of
>    DR-6's scope entirely (DR-6 gates published-as-fact claims, not every reference).
> 3. **A BARE `[@key]`** (cite whose enclosing declarative sentence is wrapped in NO span) →
>    **FORBIDDEN by DR-6 layer-1** — because the surrounding declarative sentence is bare declarative
>    prose, which the no-bare gate rejects into the bounded re-ask. ("Bare `[@key]` = forbidden," not
>    "= purely-bibliographic.")

**Confirmed: a `.framing`-span `[@key]` IS CSL-stylable as an ordinary cite.** Under DR-5's citeproc a
`[@key]` is a Pandoc `Cite` element; citeproc resolves it against the `references` bibliography
regardless of the enclosing `Span`'s class. The `.framing` class is compose-internal bookkeeping
stripped at §17 for publish-facing writers (a `.framing` strip decision is already a ratified DR-6
cost item), while the `Cite` resolves and renders normally. So K1 = a `.framing`-wrapped sentence
carrying a CSL cite that asserts no pipeline fact — exactly what DR-6 §4.1 already calls
"purely-bibliographic … out of DR-6's scope entirely, styled by CSL." **This is what makes the writer
contract genuinely non-contradictory**; it refines the stage-01 spec (the DR-5↔DR-6 bridge is
deferred to DR-5's resumption, so nothing ratified is re-opened).

### 2.3 — F1-vs-N co-design (Finding D). RECOMMEND (i): the N-invariance constraint.

**Verified.** DR-3 stage-07 §3 **pins the normalizer N at DR-3 build time** (F3: NFC-normalize;
line-endings→`\n`; strip trailing per-line whitespace; collapse blank-line runs; strip leading/
trailing blank lines; idempotent; **preserves LEADING indentation as opaque content**; **no semantics
to nesting**). It **defers F1**, the unforgeable sentinel section-grammar ("boundaries drawn only from
sentinel lines content cannot forge"). The build order ships N (DR-3) BEFORE F1 (DR-4). So the
stage-01 "**Verified additive**: DR-4 parses sections from the `outline-digest` without changing it"
is **not verified** — it presumes the deferred F1 coexists with an N pinned before F1 exists. If F1's
sentinels rely on structure N collapses, un-deferring F1 forces an N change, and **any N change churns
the `outline-digest` for every existing outline** (DR-3 R2: re-indentation re-composes) — the opposite
of additive.

**RETRACT "verified additive."** State the co-design constraint and **recommend horn (i)**:

> **THE N-INVARIANCE CONSTRAINT (a DR-3 build-time requirement, recorded NOW so DR-4 stays additive):**
> The F1 sentinel grammar MUST be expressible **using only structure N PRESERVES**, so that computing
> `N(markdown)` and then parsing sections from it is a pure read that **changes neither N nor the
> `outline-digest`.** Concretely, a sentinel must be a **full-line, forgery-resistant token that
> survives N** — i.e. it depends only on N-preserved content (full line text; leading indentation,
> which N keeps as opaque content) and **never on structure N destroys** (trailing whitespace,
> blank-line-run counts, or nesting semantics N assigns none to). Because N preserves line content and
> leading indentation, a viable N-invariant sentinel space EXISTS (e.g. a reserved full-line marker
> the writer contract forbids in body prose), so horn (i) is FEASIBLE — no flag needed. **DR-3, when
> pinning N, must reserve/preserve exactly the sentinel-significant structure F1 will consume**, and
> **DR-4's F1 must rely on nothing outside it.** Then un-deferring F1 at DR-4 is a genuine drop-in:
> zero digest churn, verified-additive earned rather than asserted.

Horn (ii) — accept that un-deferring may re-pin N and churn existing outline digests — is the priced
fallback (a deliberate re-indent-class churn, loud, re-composes). It is inferior: it makes the
DR-3→DR-4 build order digest-fragile for no gain. **Recommend (i).**

### 2.4 — External-side K3 (Finding F). Compose-fixed literal prose, not a render-time projection.

**Verified.** For `side: external`, §17 dispatch "persist[s] AST + emit[s] the contract payload"
(design.md L1596-99); the provenance strip runs at dispatch BEFORE handoff; `side` is excluded from
identity (L1638); and the external actor runs its OWN, **unpinned** serialization/citeproc (dr4-dr5
§4.2 determinism gate). The pipeline's guarantee **ends at the payload handoff.** So a K3 attribution
realized as a **render-time CSL projection** ("B, as cited in S") would be produced by the external
actor's citeproc, OUTSIDE the pipeline's boundary — the pipeline cannot ensure S appears in the final
external bytes. The stage-01 K3 "survive the §17 strip" property is **necessary but not sufficient**
for external.

> **THE K3 EXTERNAL RULE:** For `side: external`, the scenario-2 S-naming attribution MUST be
> **strip-surviving BODY content fixed at COMPOSE** — literal prose ("According to S, B reports X")
> that is part of the artifact body, and therefore survives BOTH the §17 strip AND any downstream
> unpinned serialization. It is **NOT** a render-time CSL projection. **The future DR-5 CSL
> indirect-citation surface extends K3 cleanly ONLY for `side: internal`** (the pinned pipeline
> citeproc, where the pipeline controls the rendered bytes). **For `side: external`, K3 stays
> compose-fixed prose** (or an equivalent literal body form). A later DR-5 pass must NOT "extend" K3
> with a CSL surface that silently fails the external half.

This sharpens the deferred K3 contract; it re-opens nothing (the `[@key]` bridge is DR-5's on
resumption).

---

## 3. FINDINGS C, E, G, H — RESOLVED

### 3.1 — Finding C (the exemption hole): do NOT claim it "closes." (Recommendation + honesty.)

**Verified.** DR-6's own reconciliation lists over-exemption as a live residual ("over-exempting opens
a hole … a hallucination hidden inside an over-broad 'exempt' construct"; dr6 §8.2). The stage-01
report DOWN-graded it to "closes" and made it worse ("the exemption set must cover DR-4's non-text
section kinds by construction"). Exempting whole constructs/section-kinds by KIND exempts the **factual
content inside them**: a data cell ("3.2x speedup"), a claim-bearing heading ("## Results: a 3x
speedup"), a figure/table caption ("Figure 1: throughput rose 40%").

**RECOMMENDED resolution (hybrid — narrow + honest residual):**
- **Narrow the exemptions to genuinely non-declarative constructs** — list-markers, code blocks, math,
  and pure structural whitespace — where a Pandoc `[…]{.TIER data-fact}` span genuinely cannot compose
  and no factual assertion lives.
- **Require a grounding channel for factual captions/cells.** A **caption is a grounding-bearing
  paragraph, not an exempt figure part**: it carries a claim and MUST be span-able and gated. A DR-4
  whole-section figure/table is exempt as a *container*, but its caption/label text is declarative
  prose subject to layer-1.
- **REGISTER the genuine residual honestly.** Some factual content must live where a Pandoc span
  cannot compose cleanly — an ATX heading's text, a pipe-table data cell. For these the coverage gate
  trades completeness for markup feasibility. **Register "factual content in headings and table cells
  is un-gated by the compose coverage gate (markup-feasibility residual)" as a standing residual** on
  the register (caught only by the advisory Review-1 semantic audit), NOT asserted away. This is the
  coverage half of Finding B: self-demarcation is a hard gate on *form* over *span-able prose*, not a
  universal factual-content gate — the honest ceiling DR-6 already ratified.

**Do not restate "the exemption tail closes."** It narrows the hole and registers the remainder.

### 3.2 — Finding E (two loci, not one chokepoint): clean composition, not absorption.

**Verified.** DR-6 §4.1 EXPLICITLY declines to own the citation channel ("DR-6's enforcement binds to
the **ledger** … the `[@key]`/`references` channel is DR-5's and is paused; DR-6 must NOT make its
correctness gate depend on it"; `[@key]` binding "deferred to DR-5's resumption"). dr4-dr5 SF-3 makes
citation-grounding a **DR-5** gate with its own mechanism ("a `references` entry is publishable-as-
citation only if its `[@key]` resolves to a source instance recorded in the grounding ledger"). The
known-issues DR-6 phrase "one channel-agnostic property … one chokepoint" is a **PRINCIPLE-level**
statement, correct as such — but stage-01 read it as one enforcement point and listed SF-3 under "DR-6
ABSORBS."

**CORRECTED verdict language (no ratified change — this is precisely what DR-6 §4.1 ratified):**

> **DR-6 owns the PRINCIPLE** — grounding is one property of every compose leaf. **Enforcement is at
> TWO loci sharing the LEDGER as their single ground-truth:** (1) the **DR-6 prose-coverage gate**
> (compose, ledger-bound, deterministic, built at DR-6); (2) the **DR-5 citation-resolution check**
> (SF-3: every `references` entry resolves to a ledger source-instance — deferred to DR-5's
> resumption). This is **clean composition of two disjoint channels over one ledger**, NOT one
> chokepoint and NOT DR-6 absorption of the citation channel. Register the citation-resolution check
> as **DR-5-owned**, not DR-6-absorbed. The anti-duplication result survives (both bind the same
> ledger; neither re-grows a private grounding flag) — it is just two loci, honestly named.

### 3.3 — Finding G (`attestation.primary` shape): add it to the generalizability audit.

**Verified.** `LEDGER_FIELDS` is a closed 6-field exact-equality schema (ir.py L128-135, L510);
`attestation` is a new optional sub-structure (LEDGER_REQUIRED + LEDGER_OPTIONAL). DR-6 §7 pins
`primary` as "a **citation descriptor** (never a `source_instance_id` — B is not in the pool)" but
leaves its SHAPE unspecified. Stage-01 §7 audited `attestation.relation` (PROV-O, general) and skipped
`primary`.

> **ADD to the generalizability audit (criterion 4):** `attestation.primary` MUST be a **structured,
> one-file-extensible citation-descriptor carrier — CSL-JSON-shaped (or explicitly upgradeable to
> it)**, NOT a bare descriptor string. Rationale: the deferred DR-5 CSL-indirect surface K3 defers to
> (Finding F / §2.4) must render "B, as cited in S" for `side: internal`; a bare string gives it no
> structured B-data (authors/title/DOI) to project. A bare string is the exact Oxford-comma-class
> over-specific landing §7 flags for `mechanical` and section-`type`. Confirm at DR-6 build:
> `primary` carries structured B-data so the deferred surface has something to project.

### 3.4 — Finding H (DR-6-first is over-justified): F-a is an INDEPENDENT foundation.

**Verified.** `IR_VERSION = 1` with an exact-equality pin (ir.py L688). Stage-01 counted the
`ir_version` generation-tolerant validation (F-a) as one of "three independent reasons DR-6 first,"
while its own must-resolve item 1 correctly calls F-a "a FOUNDATION, not a DR-6 footnote." THREE DRs
edit the envelope (DR-6 ledger; DR-4 conformance field; DR-5 `references`). So F-a forces **F-a-first**,
not **DR-6-first**.

> **CORRECTED build-order framing:** **F-a is an INDEPENDENT foundation step** — bump `ir_version` to 2
> + relax the exact-equality pin to a known-compatible-set check (additive-optional LEDGER_REQUIRED +
> LEDGER_OPTIONAL pattern), landing **before the FIRST closed-envelope edit** (a fortiori before the
> second and third), so no additive edit strands IRs minted under a prior generation. **Its ordering
> is order-agnostic among DR-4/DR-5/DR-6** and does NOT force DR-6 first. **DR-6-first rests on ONE
> HARD reason** — **DR-6-before-DR-4**: a required-but-ungroundable DR-4 section resolves to honest
> `.framing` (X2), and the DR-6 coverage re-check must co-design with the DR-4 reconcile structural
> gate in the RI5 ordering. Plus **two SOFT preferences**: measure the writer's framing-sensitivity
> with layer-1 alone before structure/lexicon/citations pile on (GAP-8 discipline); and avoid DR-3/
> DR-4 re-growing interim per-feature grounding flags. Do not present F-a as a DR-6-forcing reason.

---

## 4. THE COMPLETE BUILD-ENTRY CHECKLIST (the maintainer's GO / NO-GO list)

The DR set is **GO to build in the §6 order ONLY when every NO-GO item below is resolved.** Items are
grouped by what they gate. NO-GO = blocks build entry as written; REGISTER = must be on the standing
register before the owning DR builds.

**FOUNDATION — land before the edits they gate (order-agnostic among the envelope-editors):**

- [ ] **1. F-a — `ir_version` generation-tolerant validation.** Bump `IR_VERSION` to 2; relax the
  exact-equality pin (ir.py L688) to a known-compatible-set check; ledger moves to
  `LEDGER_REQUIRED` + `LEDGER_OPTIONAL` (additive-optional). Lands BEFORE the first closed-envelope
  edit. INDEPENDENT foundation (Finding H); order-agnostic among DR-4/5/6. **NO-GO for any envelope
  edit.**
- [ ] **2. F-b — GAP-4 content-guard known-root fix.** Tighten `scripts/check-no-content.sh` to fail
  on an unknown registry root; verify `x-` namespacing (§11.4) + the provenance guard cover
  `lexicons/`. **NO-GO for DR-2's `lexicons/` root** before any `provenance: instance` entry is
  authored (CLAUDE.md rule 4).

**INTEGRATION SPECS — state before the consolidated surface they touch:**

- [ ] **3. Shared F1 sentinel grammar + section-constraint vocabulary (built SHARED at DR-4).** One
  reusable primitive consumed by DR-4 conformance (Format base + Platform tightening) AND the deferred
  DR-3 outline `constraint?` — never DR-4-private. **NO-GO for DR-4** (else DR-3/DR-4 divergence + a
  second F1 solve).
  - [ ] **3a. (Finding D / §2.3) F1 sentinels constrained N-INVARIANT.** F1's grammar expressible over
    DR-3's pinned N with no N change → un-deferring F1 at DR-4 churns NO existing `outline-digest`.
    Recorded as a **DR-3 build-time requirement** (reserve the sentinel-significant structure when
    pinning N). Retract "verified additive." **NO-GO for DR-3's N pin** (must reserve the space) **and
    DR-4's F1** (must rely on nothing outside it).
- [ ] **4. Extend the §16 RI5 reconcile-gate ORDERING.** Place the DR-4 hard structural gate + the
  DR-6 coverage re-check relative to localize / reshape / the terminal hard-limit gate; define the
  joint hard-structural × hard-limit **block-and-report** (naming BOTH constraints). **NO-GO for DR-4**
  (settled when the structural gate joins DR-6's re-check + the terminal gate).
  - [ ] **4a. (Finding A / §2.1) Per-section length limit home + the third MND boundary.** Section-
    scoped numeric limits are DR-4 structural constraints (section-addressed, at the structural gate);
    the §16 terminal gate keeps ONLY artifact/capacity limits (`max_chars`-class). Draw MND
    DR-4-section-limit ⟂ Platform-artifact-limit; precedence = both HARD, joint infeasibility →
    block-and-report. **RETRACT "abstract ≤N words already built."** **NO-GO for DR-4.**
- [ ] **5. Two writer-contract co-occurrence rules + the anti-fabrication rule.** (a) the `[@key]` ×
  grounding-span grammar; (b) the DR-6 exemption tail; (c) the load-bearing rule **the writer emits
  `[@key]` markers ONLY and NEVER free-authors the `references` bibliography** (`references` is a
  pipeline PROJECTION of the grounding ledger — a free-authored bibliography is the SF-3 fabrication
  vector). Ablate after each writer layer (GAP-8 discipline). **NO-GO for the writer contract.**
  - [ ] **5a. (Finding B / §2.2) The three-context `[@key]` classifier.** Keyed on SPAN CONTEXT:
    grounding span → K2/K3; `.framing` span → K1 (its real home); bare `[@key]` → FORBIDDEN by DR-6
    layer-1. Confirm a `.framing`-span `[@key]` is CSL-stylable (asserts no pipeline fact). This is
    what makes the writer contract non-contradictory. **NO-GO for the writer contract (a genuine
    contradiction until specified).**
  - [ ] **5b. (Finding C / §3.1) The exemption tail is NOT "closed."** Narrow exemptions to
    genuinely non-declarative constructs; require a grounding channel for factual captions/cells (a
    caption is a grounding-bearing paragraph); REGISTER the un-spannable-factual-content residual
    (headings, table cells) as standing. **REGISTER (honesty condition on criterion 2).**

**REGISTER before the owning DR builds:**

- [ ] **6. (Finding E / §3.2) Two enforcement loci, not one chokepoint.** DR-6 owns the PRINCIPLE;
  the DR-6 prose-coverage gate and the DR-5 SF-3 citation-resolution check are two loci over one
  ledger. Register the citation-resolution check as DR-5-owned. **REGISTER.**
- [ ] **7. (Finding F / §2.4) External-side K3 = compose-fixed literal prose.** DR-5's CSL indirect
  surface extends K3 only for `side: internal`; `side: external` stays compose-fixed prose. **REGISTER
  as a hard constraint on DR-5's resumption.**
- [ ] **8. (Finding G / §3.3) `attestation.primary` is a structured citation-descriptor carrier**
  (CSL-JSON-shaped / upgradeable), not a bare string, so the deferred CSL-indirect surface has
  structured B-data. **NO-GO for the DR-6 ledger `attestation` build** (a bare string strands the
  deferral).

**Disposition:** items 1–5 (with 3a, 4a, 5a) are **should-fix NO-GO** — B (5a) and D (3a) are the
confidence defects the audit exists to catch; A (4a), C (5b), the shared vocabulary (3), the RI5
ordering (4), and the writer rules (5) are integration specs; F-a (1) and F-b (2) are foundations.
Items 5b, 6, 7 are REGISTER; 8 is NO-GO for the DR-6 ledger build. **None re-opens a ratified
DECISION** — verified per item against the four reconciliations.

---

## 5. WHAT IS KEPT (the adversarial could not break these — NOT re-opened)

1. **Identity-surface disjointness — airtight.** Verified: the artifact preimage is EXACTLY
   `{dimensions, goals, source-subset, source-commit}` (ids.py L668-671); `_require_artifact_preimage_shape`
   hard-refuses a 5th key (L749-750); the ledger is not in the preimage. DR-2/DR-3 add two
   absent-by-default components (zero churn); DR-4/DR-5/DR-6 add zero preimage components.
2. **The precedence chain** — outline > dimension-VALUES; gates > everything. The outline is a cascade
   non-participant (DR-3 B2); the conformance envelope is a gate the outline must satisfy; no
   circularity, no §3.1 breach.
3. **The DR-4×DR-6 false-deadlock resolution** — both gates → block-and-report; §6.5 floor precedence
   is a framework invariant (design.md L465-468, verified).
4. **`ir_version` bump + generation-tolerant validation as a FOUNDATION** — additive-optional ledger
   evolution lets a v1 IR validate under v2; old IRs re-reconcile. Relaxing the exact-equality pin
   (ir.py L688) is the right move. (Its FRAMING is corrected — F-a-first, not DR-6-forcing — §3.4 —
   but the mechanism is kept.)
5. **"No ratified decision is re-opened."** Confirmed at source: every A–H item is an integration spec
   or a verdict-language correction within the ratified frame.
6. **The self-demarcation ceiling, honestly inherited** — self-demarcation gates FORM, not
   grounding-honesty; a gaming writer can mislabel a hallucination as `.framing`. Findings B/C sharpen
   this residual; they do not contradict the ratified DR-6 posture.

---

## 6. THE FINALIZED BUILD ORDER

Unchanged in sequence from stage-01; the JUSTIFICATION for DR-6-first is corrected per Finding H
(F-a is a foundation, not a DR-6-forcing reason).

```
FOUNDATION (before the first envelope/registry edit; order-agnostic among the envelope-editors):
  F-a  ir_version bump-to-2 + generation-tolerant validation (additive-optional)   [INDEPENDENT foundation]
  F-b  GAP-4 content-guard known-root fix                                          [gates DR-2]

DR-6  grounding: self-demarcation coverage gate (layer-1) + `.framing` span + writer.md
      + ledger `attestation?` (structured `primary`, item 8) + `grounding_posture` M3 policy
      + Review-1 semantic audit
      [FIRST on ONE hard reason: DR-6-before-DR-4 (RI5 co-design + X2); + soft prefs (measure
       writer density first; avoid interim grounding flags). NOT forced by F-a.]
  │
DR-3  outline: Markdown canonical + `outline-digest` (preimage guard extension #1) + `formats/outline.md`
      + emit bridge + drive facets.  [N pinned so the F1 sentinel space is RESERVED N-invariant — item 3a]
  │
DR-4  typed-section conformance: BUILD the F1 sentinel grammar (N-invariant, item 3a) + the SHARED
      section-constraint vocabulary (item 3) + own IR conformance field + Platform hard structural
      class + base & reconcile structural gates (extend RI5 ordering, item 4; per-section limits home
      here, item 4a).  [un-defers DR-3 §07 F1]
  │
DR-5  citations/style: `references` (TOP_LEVEL_KEYS) + `[@key]` + content-driven citeproc + `csl`
      lever + dispatch compatibility check + the DR-5↔DR-6 `[@key]` bridge (three-context classifier
      item 5a; SF-3 citation-resolution locus item 6; external K3 = compose-fixed prose item 7).
      [needs DR-6 ledger + DR-4 Platform]
  │
DR-2  lexicon: `lexicons/` (needs F-b) + `lexicon` ref (preimage guard extension #2) + writer.md
      lexicon layer + §16 fidelity obligation.  [LAST — lightest writer layer]
```

**Cross-cutting (kept from stage-01, confirmed):** the preimage-shape guard is extended TWICE (DR-3
then DR-2, both absent-by-default, zero churn); the closed IR envelope is co-edited by THREE DRs
(disjoint keys, each additive-optional riding F-a); the `writer.md` contract (item 5) and the §16
fidelity list (item 4) accumulate across all DRs — re-validate/ablate after each layer, do not
finalize either until DR-2 lands; the RI5 ordering (item 4) settles at DR-4.

---

*End of reconciliation. Verdict: the DR set is a SOUND FOUNDATION to build on, CONDITIONAL on the
complete §4 checklist. The three over-stated headline verdicts are down-graded to conditional on A–D;
E–H are registered; the four boundary questions are answered as integration specs within the frame
(per-section limit → DR-4 with the third MND boundary; the `[@key]` classifier → three span contexts;
F1 → N-invariant by construction; external K3 → compose-fixed prose). No ratified decision is
re-opened; no boundary answer required a ratified change. Read-only; no code, no implementation plan.
The maintainer gate runs next.*
