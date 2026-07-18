# DR-1..DR-6 — FOUNDATION-COHERENCE / cross-DR INTEGRATION — Architect (mode: ADVERSARIAL)

**Pass:** ops-architect, ADVERSARIAL attack on `01-architect-initial/report.md`. **Class:** read-only.
No repo edits, no commit. **Mandate: prove the "complete-enough, ORTHOGONAL, COMPOSABLE, EXTENSIBLE,
GENERALIZED foundation" verdict WRONG.** A surviving finding beats agreement; a miss in a foundation
audit compounds across every later build.

**Verified this pass against the LIVE SSOT + CODE, not the reports:** all four ratified reconciliations
(DR-2 stage-03 + DR-3 stage-07, DR-4/DR-5 stage-03, DR-6 stage-03); `docs/known-issues.md` DR-1..DR-6;
`docs/design.md` §6.5, §16/RI5 (L1516-1557 — the ordering + fidelity + reconcile-inputs preimage read
directly this pass), §17; `pipeline/prompts/writer.md` (the live 5-rule contract, read in full);
`pipeline/ir.py` (`TOP_LEVEL_KEYS`/`LEDGER_FIELDS`/`IR_VERSION` L108-141); `pipeline/ids.py`
(`_require_artifact_preimage_shape` L749-750, `build_artifact_preimage` L667-672). Where I attack a
claim I cite the source that falsifies it.

---

## 0. ADVERSARIAL VERDICT (up front)

**The SKELETON survives — but the report's three headline verdicts are each OVER-STATED, and the
"five must-resolve-first items" list is INCOMPLETE in ways a foundation audit exists to catch.** The
report's job was to be the first pass to see all six DRs together; on three of its four criteria it
asserted-away an interaction it should have surfaced:

- **Criterion 1 ("no residual scope duplication") is FALSE as written.** The matrix missed a live
  double-home — a **per-section length constraint is enforceable at BOTH the new DR-4 structural gate
  AND the pre-existing Platform hard-limit gate** — and the report's own §4 vocabulary contradicts its
  own §1 matrix and the DR-4/5 reconciliation on where "abstract ≤N words" is enforced (Finding A).
  And its strongest anti-duplication claim — "DR-6 absorbs the three grounding flags into ONE
  chokepoint" — is over-stated: SF-3's citation-to-ledger grounding is a SEPARATE DR-5 check DR-6
  explicitly declined to own (Finding E).
- **Criterion 2 ("the writer contract is coherent, non-contradictory, just operationally dense") is
  FALSE.** The DR-5 `[@key]` classifier ("bare `[@key]` = purely-bibliographic") keys on a surface
  DR-6 layer-1 FORBIDS (no bare declarative prose) — an unspecified CONTRADICTION between two ratified
  specs the report stated as independently-needed without noticing they collide (Finding B). And the
  DR-6 exemption tail does NOT "close": exempting headings/table-cells/DR-4-non-text-sections by
  construction leaves factual content (data cells, figure captions, claim-bearing headings) un-gated —
  the exact over-exemption hole DR-6's own reconciliation warned of (Finding C).
- **Criterion 3 ("extensibility is REAL... verified additive") is OVER-CLAIMED.** The report's
  "Verified additive: DR-4 parses sections from the outline-digest without changing it" presumes the
  DEFERRED F1 sentinel grammar is compatible with DR-3's ALREADY-PINNED normalizer N — which is the
  unsolved deferred problem, not a verified fact; if F1 needs structure N collapses, un-deferring forces
  a digest change = churn (Finding D). And the K3 "name-S + survive-strip" contract does not cleanly
  extend to `side: external`, where the pipeline emits no bytes and the external actor serializes on an
  unpinned toolchain (Finding F).

Criterion 4 (generalizability) mostly holds, but the report audited `attestation.relation` and skipped
`attestation.primary`'s shape, which gates the very DR-5 CSL-indirect surface K3 defers to (Finding G).

**Net: the foundation is buildable, but the verdict is too optimistic and the must-resolve list is
short by four items.** Details below, each with severity, evidence, and the fix or the question
reconciliation must answer.

---

## FINDING A — Residual duplication the matrix missed: a per-section length limit is BOTH a DR-4 structural constraint AND a Platform hard-limit. **Severity: should-fix (falsifies criterion 1 as written).**

**What is wrong.** The report's §1 matrix asserts DR-4 conformance is disjoint from Platform hard-limits
("proof of no residual scope duplication... no cell is a silent scope overlap"), and §3 assigns numeric
limits to "the pre-existing terminal hard-LIMIT gate." But the report's OWN §4 shared-vocabulary
constraint menu lists **"min/max length (words/chars)"** as a per-section constraint with **"severity:
error = BLOCK"** enforced at the DR-4 structural gate. A per-section word limit ("abstract ≤ 250 words")
is therefore homed in TWO deterministic gates at once, and the boundary is never drawn.

**Evidence (internal contradiction across the ratified set).**
- Integration report §4 constraint menu: per-section `min/max length (words/chars)` → severity
  `error = BLOCK` at the structural gate.
- Integration report §1 matrix: "DR-4... MND vs §5.2" but NO MND drawn vs Platform hard-limits — it is
  marked plain `CW`, i.e. asserted non-overlapping.
- DR-4/DR-5 reconciliation §2.2 (the (a) fallback) routes the SAME constraint the OTHER way: "abstract
  ≤N words (Platform **hard limit → §16 gate, already built**)."
- design.md §16 (L1520, L1537-1538): the terminal gate fits-or-blocks on "the platform entry's
  effective **hard-limit set**" — an artifact/capacity-level numeric set with **no per-section
  addressing today.** So "abstract ≤N words" is NOT actually served by the "already built" gate — it
  needs DR-4's section grammar to even address "the abstract."

So there are two live defects folded into one: (i) a **double-home** — per-section length is expressible
in the DR-4 structural class AND described as a Platform hard-limit; (ii) the DR-4/5 "already built"
claim is **false** for section-scoped limits (the existing gate has no section addressing). The
integration audit reproduced both instead of resolving them.

**The concrete fix / question reconciliation must answer.** Draw the third MND boundary the report
missed: **is a per-section numeric limit a DR-4 structural constraint (checked by the section grammar,
section-scoped) or a Platform hard-limit (the §16 terminal gate)?** They cannot be both without a
double-block-and an undefined precedence. Recommended: section-scoped limits belong to DR-4 (they
require section addressing the hard-limit set lacks); the terminal gate keeps only artifact/capacity
limits. Then retract the DR-4/5 "abstract ≤N words already built" claim — it is a DR-4 build item, not a
reuse.

---

## FINDING B — The `[@key]` classifier CONTRADICTS DR-6's no-bare-declarative rule. **Severity: should-fix (falsifies the "coherent, non-contradictory" writer-contract verdict — a new GAP-8 derail vector).**

**What is wrong.** The report calls the consolidated writer contract "coherent, non-contradictory, just
operationally dense" (§0, §2), and separately specifies TWO co-occurrence rules as independently needed
(deliverable 2 / §2 spec 1, §5). It never checks that they collide. They do. The `[@key]` classifier
(§2 spec 1; §5 K1) keys the purely-bibliographic case on a **BARE `[@key]`** ("no grounding-span
binding"). DR-6 layer-1 (§2 layer 1) requires that **every declarative prose unit be a grounding span OR
an explicit `.framing` span — nothing bare.** A sentence citing the literature for rhetorical context
("Prior work examined X `[@jones2019]`") is declarative prose → under DR-6 it CANNOT be bare → the
`[@key]` lives inside a `.framing` span. So the K1 "bare `[@key]`" surface **does not exist** under
DR-6 layer-1 for any declarative sentence.

**Evidence.**
- writer.md today has NO demarcation-of-all-prose (verified: grep for `framing`/`bare declarative`/
  `every prose` across writer.md, compose.py, ir.py, design.md returns nothing). DR-6 layer-1 is a
  BRAND-NEW discipline that changes the writer's per-sentence decision from binary (cite / leave-bare)
  to ternary (grounding-span / framing-span / [forbidden] bare).
- Integration report §2 spec 1: "a BARE `[@key]` is purely-bibliographic (K1)."
- Integration report §2 layer 1: "every DECLARATIVE prose unit is a grounding span... OR an explicit
  `.framing`... nothing bare."
- DR-6 reconciliation §2.2/§8.2 confirms `.framing` is mandatory on all non-grounded declarative prose;
  the gate rejects bare declarative text.

The two rules are jointly unsatisfiable as stated: the classifier NEEDS a bare form DR-6 ELIMINATES.
The report's claim that layers "govern DISJOINT properties" is wrong here — layer 4 (citations) and
layer 1 (coverage) both operate on the SAME per-sentence classification, and the classifier's key
(barenesss) is exactly what layer 1 outlaws. On a writer the report itself calls framing-sensitive
(GAP-8, 3/8 derail), a per-sentence THREE-way-plus-citation decision with an internally inconsistent
grammar is a feasibility risk, not "density."

**The concrete fix / question reconciliation must answer.** The classifier must be defined over THREE
span contexts, not two: (1) `[@key]` inside a grounding span → grounding citation (K2/K3); (2) `[@key]`
inside a `.framing` span → purely-bibliographic (the new K1 home — rhetorical-context citations live
here, NOT bare); (3) bare `[@key]` → **forbidden** by DR-6, not "purely-bibliographic." State whether a
`.framing`-span `[@key]` is stylable by CSL as an ordinary cite (it should be — it asserts no pipeline
fact). Until this is written, "the writer contract is non-contradictory" is unproven.

---

## FINDING C — The DR-6 exemption tail does NOT close; exempting by construct/section-kind opens coverage holes. **Severity: should-fix (the writer-contract "closes" claim is too optimistic).**

**What is wrong.** The report asserts the exemption tail (§0 item 5; §2 layer 1; §2 spec 3) "closes,"
and spec 3 makes it worse: "the exemption set... must cover DR-4's non-text section kinds by
construction." But exempting whole constructs/sections by KIND exempts the factual content INSIDE them.
A hallucinated factual assertion hidden in an exempt construct escapes the coverage gate entirely — the
exact over-exemption failure DR-6's own reconciliation flagged ("a hallucination hidden inside an
over-broad 'exempt' construct").

**Evidence — concrete holes in the report's own exemption set ("headings/list-markers/table-cells/code/
math + DR-4 non-text section kinds"):**
- **Table cells** are exempt wholesale — but a DATA table is precisely where grounded facts live; a cell
  reading "3.2x speedup" or "O(n)" is a factual claim the gate now never sees.
- **Headings** are exempt — but "## Results: a 3x speedup" carries a factual claim in the heading.
- **DR-4 non-text section kinds** (figure/table) are exempt "by construction" — but such sections carry
  **captions** ("Figure 1: throughput rose 40%"), which are factual assertions. Exempting the whole
  section kind exempts the caption's claim.

The exemptions are plausibly SYNTACTIC necessities (a Pandoc `[x]{.EXTRACTED data-fact}` span does not
compose cleanly inside a pipe-table cell or an ATX heading), which is exactly why they can't simply be
"closed" — they trade coverage completeness for markup feasibility, and the residual is a real
un-gated-factual-content hole. DR-6 reconciliation §8.2 already lists this as a live residual ("the
exemption tail... over-exempting opens a hole"); the integration report DOWNGRADES it to "closes."

**The concrete fix / question reconciliation must answer.** Do not claim the tail "closes." Either (i)
narrow exemptions to genuinely non-declarative constructs and require an alternative grounding channel
for factual captions/cells (e.g. a caption is a grounding-bearing paragraph, not an exempt figure part),
or (ii) FLAG the exempt-construct coverage hole as a standing residual (factual content in
headings/cells/captions is un-gated) so it is on the register, not asserted away. This is the coverage
half of Finding B — both stem from the report treating self-demarcation as tidier than it is.

---

## FINDING D — "Verified additive: DR-4 parses sections without changing the outline-digest" is an OVER-CLAIM; it depends on the DEFERRED F1 grammar being compatible with DR-3's ALREADY-PINNED normalizer N. **Severity: should-fix (dents criterion 3 "extensibility is real / verified additive" and the DR-3→DR-4 build order).**

**What is wrong.** The report's extensibility verdict rests on condition 3 ("build the F1 sentinel
grammar + shared vocabulary SHARED at DR-4 → the deferrals are clean drop-ins") and §8 asserts "Verified
additive: the `outline-digest` is over whole normalized Markdown; DR-4 parses sections from it via the
sentinel grammar without changing the digest." That "verified" is not verified — it presumes the
deferred, unsolved F1 grammar coexists with an N that was pinned BEFORE F1 exists.

**Evidence.**
- DR-3 stage-07 §3 F3 PINS the normalizer N at DR-3 build time: "strip trailing per-line whitespace;
  collapse blank-line runs; strip leading/trailing blank lines; ... preserves LEADING indentation as
  opaque content; v1 assigns NO semantics to nesting."
- DR-3 stage-07 §1.4 / §3 F1: the outline is HOLISTIC Markdown with **no machine section-parse in v1**;
  F1 (the sentinel grammar) is the DEFERRED hard problem — "boundaries drawn only from sentinel lines
  **content cannot forge**" (so NOT plain `##` headings, which an LLM body can forge).
- Build order (integration §8): DR-3 ships N; DR-4 (later) builds F1 "un-defers DR-3 §07 F1."
- So the sentinel grammar F1 must operate on the ALREADY-N-normalized bytes. If F1's unforgeable
  sentinels rely on whitespace/blank-line structure that N COLLAPSES, then either F1 is unbuildable on
  N's output, or N must change to preserve sentinel-significant structure — and **any change to N
  changes the `outline-digest` for every existing outline** (DR-3 stage-07 R2: "re-indentation churns
  identity... re-composes"). That is the opposite of "without changing the digest."

The report assumed away the exact coupling the F1 deferral exists to defer. "Build it shared once and
the deferrals are clean drop-ins" is only true if F1 was co-designed with N — but the ratified DR-3
build ships N first and explicitly defers F1.

**The concrete fix / question reconciliation must answer.** Retract "verified additive." State the
co-design constraint: **the F1 sentinel grammar must be expressible over DR-3's pinned N without an N
change**, or the un-defer at DR-4 is a digest-churning change, not a drop-in. Reconciliation must
either (i) constrain F1 now to sentinels N preserves (and prove N preserves them), or (ii) accept that
un-deferring F1 may re-pin N and churn existing outline digests, and price that. This is the load-bearing
condition-3 claim; it cannot rest on an unverified "verified."

---

## FINDING E — "DR-6 absorbs the three grounding flags into ONE chokepoint" is over-stated; SF-3's citation-to-ledger grounding is a SEPARATE DR-5 check DR-6 declined to own. **Severity: should-fix (weakens the strongest criterion-1 anti-duplication claim).**

**What is wrong.** The report's headline anti-duplication result (§0; §1 "the strongest anti-duplication
result in the set") is that DR-6 collapses the DR-2/DR-3/DR-4-5 grounding flags into "ONE
channel-agnostic property... one chokepoint." For the citation channel (SF-3) this is not true.

**Evidence.**
- DR-6 reconciliation §4.1 EXPLICITLY refuses to own the citation channel: "Do not couple DR-6 to a
  paused, elsewhere-pointing channel. DR-6's enforcement binds to the **ledger** (fact-ids)... The
  `[@key]`/`references` channel is DR-5's and is paused; DR-6 must NOT make its correctness gate depend
  on it." The `[@key]` binding is "deferred to DR-5's resumption."
- DR-4/DR-5 reconciliation SF-3 makes citation-grounding a DR-5 gate item with its OWN mechanism: "a
  `references` entry is publishable-as-citation only if its `[@key]` resolves to a source instance
  recorded in the... grounding ledger" — a references-resolution check, NOT DR-6's no-bare-declarative
  prose gate.

So grounding is enforced at TWO points by TWO mechanisms: DR-6's prose-coverage gate (compose,
ledger-bound) and DR-5's references-resolve-to-ledger check (deferred to DR-5). "One channel-agnostic
chokepoint" is the aspiration, not the built state. The report even lists SF-3 under "DR-6 ABSORBS"
(§1) while its own §5 correctly describes the bridge as a DR-5-resumption obligation — an internal
inconsistency.

**The concrete fix / question reconciliation must answer.** State the truth: DR-6 owns the PRINCIPLE
(grounding is one property) but there are TWO enforcement loci — the prose-coverage gate (DR-6) and the
citation-resolution check (DR-5 SF-3, deferred). This is clean composition (two disjoint channels), but
it is NOT "one chokepoint" and must not be sold as absorption. Confirm the two checks share the ledger
as their single ground-truth (they do), and register the citation-resolution check as DR-5-owned, not
DR-6-absorbed.

---

## FINDING F — The K3 "name-S + survive-strip" contract does not cleanly extend to `side: external`, where the pipeline emits no bytes. **Severity: should-fix (criterion-3 extensibility gap; the report's forward CSL claim glosses it).**

**What is wrong.** The report's K3 contract (§5) requires an attribution that "(a) NAMES S and (b)
SURVIVES the §17 fail-closed strip for that writer," and states v1 = prose, with the forward claim
"when DR-5 lands the CSL channel, it MAY add an indirect-citation surface that names S and survives."
For `side: external` the "survive the §17 strip" property is NECESSARY BUT NOT SUFFICIENT, and the CSL
forward path does not cleanly extend.

**Evidence.**
- GAP-1 (RESOLVED) ratified that external targets emit a zero-provenance RI14 payload with **no bytes**;
  `strip_provenance(ast)` runs at dispatch BEFORE handoff, and the external actor runs its OWN,
  **unpinned** serialization/citeproc (DR-4/5 reconciliation §4.2, the internal↔external determinism
  gate: "the external actor runs citeproc on its own, unpinned toolchain").
- So for external, an attribution realized by a render-time CSL projection ("B, as cited in S") is
  produced by the EXTERNAL actor's citeproc, OUTSIDE the pipeline's guarantee boundary — the pipeline
  cannot ensure S appears in the final external bytes. Only a **compose-time literal-prose** S-naming
  (which is body content, surviving both the pipeline strip AND any downstream serialization) is
  guaranteed.
- v1 (prose) satisfies this; but the report's forward statement implies the future CSL surface extends
  K3 to all writers uniformly. It does not for external.

**The concrete fix / question reconciliation must answer.** Sharpen the K3 property: for `side:
external`, the S-naming must be **strip-surviving BODY content fixed at compose** (not a render-time
CSL projection), because the pipeline's guarantee ends at the payload handoff. State that the DR-5 CSL
indirect surface extends K3 cleanly ONLY for `side: internal` (pinned pipeline citeproc); for external,
K3 stays prose-or-equivalent-literal. Otherwise a later DR-5 pass will "extend" K3 with a surface that
silently fails the external half.

---

## FINDING G — Generalizability audit missed `attestation.primary`'s shape, which gates the DR-5 CSL-indirect surface K3 defers to. **Severity: minor (should-confirm at build).**

**What is wrong.** The report's §7 audits `attestation.relation` (PROV-O, "general") but not
`attestation.primary`. DR-6 reconciliation §7 pins `primary` as "a **citation descriptor** (never a
`source_instance_id` — B is not in the pool)." Its SHAPE is unspecified. If v1 lands `primary` as a bare
descriptor string, the future K3 CSL-indirect surface ("B, as cited in S", Finding F / report §5) has
**no structured B-data (authors/title/DOI)** to render — the deferral is then NOT cleanly extensible,
the same over-specific-landing failure §7 flags for `mechanical` and section-`type`.

**The fix.** Add `attestation.primary` to the §7 generalizability audit: confirm it is a structured,
one-file-extensible citation-descriptor carrier (CSL-JSON-shaped, or explicitly upgradeable), not a
bare string — so the deferred CSL-indirect surface has structured data to project.

---

## FINDING H — DR-6-first is over-justified; F-a (ir_version) is a FOUNDATION three DRs need, not a DR-6-forcing reason. **Severity: minor (build-order framing).**

**What is wrong.** The report gives "DR-6 FIRST — three independent reasons," of which reason (2) is
that DR-6 "owns the `ir_version` generation-tolerant validation (F-a)." But the report's OWN
must-resolve item 1 says F-a is "a FOUNDATION, not a DR-6 footnote" — and THREE DRs (DR-4, DR-5, DR-6)
edit the envelope. So F-a is a standalone foundation step that must precede the SECOND envelope edit
regardless of which DR is first; it does not force DR-6 first. The genuine forcing is elsewhere and
weaker than "three independent reasons" implies: DR-6-before-DR-4 (the RI5 gate co-design + X2), and
avoiding interim grounding flags (a convenience, since DR-3/DR-4 could simply defer grounding to a
known-upcoming DR-6 rather than re-grow flags).

**The fix.** Present F-a as an independent FOUNDATION step (F-a before any second envelope edit), and
rest DR-6-first on the one hard reason (DR-6-before-DR-4 for the RI5 ordering + X2) plus the soft
measurement/anti-interim-flag preferences. Do not count F-a as a DR-6-forcing reason; it forces
F-a-first, which is order-agnostic among DR-4/5/6.

---

## VERDICT — is the foundation-readiness claim sound, or too optimistic?

**Too optimistic as written — though the underlying foundation is buildable.** No single finding
re-opens a ratified DECISION (the report is right that the DRs partition mostly cleanly and that nothing
demands redesign). But the report's specific verdicts overreach on THREE of four criteria, and its
"five must-resolve-first items" list is SHORT BY FOUR:

- **Criterion 1 is falsified** by the per-section-length double-home (A) and the over-stated DR-6
  absorption of SF-3 (E). "No residual scope duplication" is not true; one MND boundary is undrawn and
  the audit reproduced a cross-reconciliation inconsistency.
- **Criterion 2 is falsified** by the `[@key]`-classifier × no-bare-declarative CONTRADICTION (B) and
  the non-closing exemption tail (C). "Coherent, non-contradictory, just density" is wrong: there is an
  unspecified contradiction and an over-exemption coverage hole, both on the framing-sensitive writer.
- **Criterion 3 is over-claimed** by the unverified "verified additive" DR-4/N coupling (D) and the
  external-side K3 gap (F). Extensibility is real for MOST deferrals but not cleanly for these two.
- **Criterion 4 mostly holds**, with one missed landing (G).

The correct disposition: the foundation is a sound base to build on ONLY IF the must-resolve list is
extended to include A-D (should-fix, some blocker-adjacent to the verdict-as-written) and E-H are
registered. The report's own posture — "these are integration specs to state at build, none a redesign"
— is defensible for A, C, E, F, G, H. But B (a genuine contradiction the report asserted was absent) and
D (a "verified" that is not verified) are cases where the report's confidence itself is the defect a
foundation audit exists to catch. Reconciliation must down-grade the three headline verdicts to "sound
CONDITIONAL on resolving A-D" and answer the four questions above.

### What I could NOT break (honest list — these survive the attack)

- **The identity-surface disjointness is airtight.** Verified against code: the artifact preimage is
  EXACTLY `{dimensions, goals, source-subset, source-commit}` (ids.py L667-672), the frozen-shape guard
  hard-refuses any 5th key (L749-750), the ledger is NOT in the preimage. DR-2/DR-3's two new components
  are absent-by-default (zero churn); DR-4/DR-5/DR-6 add zero preimage components. No duplication here.
- **The precedence chain (outline > dimension-VALUES; gates > everything).** Coherent; the outline is a
  cascade non-participant (DR-3 B2), the conformance envelope is a gate the outline must satisfy — no
  circularity, no §3.1 breach. I could not find a case where the outline can override a hard gate.
- **The DR-4×DR-6 "deadlock is false" resolution.** Both gates → block-and-report; §6.5 floor precedence
  is a framework invariant (design.md §6.5, verified in DR-6 recon §4.2). No genuine deadlock.
- **The ir_version bump + generation-tolerant validation as a foundation.** Sound: additive-optional
  ledger evolution (`LEDGER_REQUIRED`+`LEDGER_OPTIONAL`) lets a v1 IR validate under v2, so old IRs
  re-reconcile. The `IR_VERSION == IR_VERSION` exact-pin (ir.py L108/L688) is the right thing to relax.
- **"No ratified decision is re-opened."** Correct — every finding above is an integration spec or a
  verdict-language correction WITHIN the ratified frame, not a redesign. The report's structural claim
  (integration surfaced specs, not conflicts) holds even though its confidence level does not.
- **The self-demarcation ceiling is honestly inherited.** The report did not hide the gaming-writer
  false-confidence residual; my Findings B/C sharpen it but do not contradict the ratified DR-6 posture.

*End of adversarial report. Read-only; no code, no plan; ATTACK within the ratified frame. The
reconciliation pass runs next and must (i) extend the must-resolve list with A-D, (ii) answer the four
boundary questions (per-section-limit home; the three-context `[@key]` classifier; F1-vs-N co-design;
external-side K3), and (iii) down-grade the three over-stated headline verdicts to conditional.*
