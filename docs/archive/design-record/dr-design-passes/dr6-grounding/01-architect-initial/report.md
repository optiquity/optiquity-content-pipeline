# DR-6 — General grounding enforcement — ARCHITECT (mode: INITIAL)

**Pass:** ops-architect, initial design for DR-6 (general grounding enforcement).
**Grounded in:** the DR-6 research report (`00-research/report.md`), `docs/known-issues.md` DR-6 +
the absorbed DR-2/DR-3/DR-4-5 flags, `docs/design.md` §6/§15/§16/§17/§19, and the cited code
(`pipeline/{compose,ir,review,grounding}.py`). Gap re-verified in code (see §1). **Design only —
no code, no implementation plan.** Read-only pass.

---

## 0. Verdict (read this first)

**Enforcement posture — HONEST, not aspirational.** Split the invariant along the determinism line
the maintainer named, but correct one premise: *coverage is only HALF structural.* The
**spans→ledger** direction (every grounding marker resolves to a real, tier-honest, in-scope ledger
fact) is structural and is **promoted to a HARD compose-time gate** — it extends the existing
`validate_ir` consistency gate and adds a deterministic, false-reject-safe **grounding-utilization
floor** plus a **scenario well-formedness** check. The **assertions→spans** direction (does every
factual sentence *carry* a marker? — the actual "unmarked assertion" hole) requires deciding *which
sentences are factual assertions*, which is the **same semantic (NLI-class) judgment** the research
proves is aggregate-strong but **per-claim noisy** — so a *perfect* coverage hard gate is
**unachievable** for the same reason a faithfulness hard gate is. That semantic layer (unmarked-
assertion detection + span↔fact entailment) is therefore wired as an **advisory groundedness score
(Review 1) + a bounded-repair signal into compose's existing re-ask (the RARR detect→revise
posture)**, with escalation to an **item-level abstain (the §6.4 / GopherCite block-and-report
posture)** on persistent failure governed by a **policy lever (default: warn-and-ship; opt-in:
block)** — *never* a per-claim automatic reject (the research's explicit prohibition). **Scenario-2
ledger model:** add ONE **optional** ledger sub-structure `attestation?: {primary, anchor,
relation}` — a **THIRD axis** (pool-relation), distinct from the tier, from `traceability`, and from
the `primariness` *score* — where `relation` is PROV-O vocabulary (`wasQuotedFrom` / a
derived-from variant), `primary` is the out-of-pool primary's citation-identity (**never** a
`source_instance_id` — it is not in the pool), and `anchor` is a resolvable anchor **into the held
pool source** locating the quote/reference. Presence of `attestation` = scenario 2; absence =
scenario 1; both are structurally publishable, everything else is the hallucination = reject case.
**Publish-as-fact-vs-attributed ruling:** a **scenario-2 claim publishes ONLY as an attributed
statement** ("According to [pool source S], B says X"), **never as bare fact** — because the pool
grounds the *attestation* ("S reports B: X"), not the bare proposition "X"; the EXTRACTED-tier unit
is the attestation, and the attribution is a grounding-layer obligation (DR-6 owns whether it is
attributed; DR-5 owns how the citation is *styled*). **Blast radius: ZERO new identity surface** —
the ledger is not in the artifact-id preimage or the RI4 binding digest (verified), so the extension
changes neither; it changes only the IR envelope's closed ledger schema (an `ir_version` event),
made additive/optional to avoid churning existing scenario-1 ledgers.

---

## 1. The gap, re-verified in code (I did not take the research on faith)

`validate_ir` (`pipeline/ir.py:668`) is the single pre-persist chokepoint. It enforces, in order:
closed top-level key set; version stamps; the RI4 binding reproduces the artifact-id + digest; the
grounding ledger's closed schema + no-secrets scan; the metadata bag; `parts` XOR `body`; and — the
grounding part — `_validate_refs` (`ir.py:543`) over the refs `extract_fact_refs` finds.

- `_validate_refs` enforces **span↔ledger CONSISTENCY only**: every `data-fact` reference (a) exists
  in the ledger (`ir-unknown-fact`) and (b) carries the ledger's *exact* tier as its class, so no
  forged fact-id and no promoted tier (`ir-tier-violation`). It iterates the refs that **exist**.
- `extract_fact_refs` scans for `data-fact` spans. A `body` of pure prose with **zero** `data-fact`
  spans yields an empty ref list, and `_validate_refs([])` is a **no-op** → an **unmarked assertion
  passes**. Confirmed: coverage is not gated.
- `_require_substance` (`ir.py:614`, `713`) is a content-blind SHAPE floor (≥1 visible letter/digit)
  — it does not look at grounding.
- Review 1 (`pipeline/review.py`): `ARTIFACT_CHECKS = (grounding, extracted_floor, …, citability)`,
  but `VERDICTS = (pass, concerns)` and `CHECK_STATUSES = (pass, concern)` with the docstring "this
  gate never *enforces* the floor (that is compose's/reconcile's job)" (`review.py:19`). Advisory.

**Conclusion (VERIFIED):** the *coverage* invariant — every published-as-fact sentence traces to an
EXTRACTED (or scenario-2 attested) ledger fact — is enforced **NOWHERE as a hard block**. Compose
hard-gates *consistency*; Review 1 only *advises* coverage. That is precisely DR-6.

Two identity facts I verified (they set the blast-radius ceiling, §5):
- The artifact-id preimage is exactly `{dimensions, goals, source-subset, source-commit}`
  (`pipeline/ids.py:587`, `749`). The grounding **ledger is not in it.**
- The RI4 binding digest is `digest_full(preimage)` over that preimage only (`ir.py:_validate_binding`),
  so the ledger is not in the binding digest either. **The ledger is provenance, not identity.**
- `LEDGER_FIELDS` is a **closed exact-match** schema (`keys == set(LEDGER_FIELDS)`, `ir.py:510`),
  UNLIKE parts, which already model `_PART_REQUIRED` + `_PART_OPTIONAL` (`ir.py:573-575`). The
  scenario-2 extension should copy the parts pattern (required + optional), not the exact-match one.

---

## 2. Q1 — The enforcement posture (hard vs advisory, answered honestly)

### 2.1 The honest correction: coverage is only half structural

The maintainer's crux frames coverage as "structural → deterministically hard-gateable, like the
span↔ledger consistency gate." That is **half right and the half that matters is wrong**:

- **spans→ledger** ("does every marker resolve to a real, tier-honest, in-scope fact?") is
  structural — and already hard-gated; DR-6 strengthens it (§2.2).
- **assertions→spans** ("does every factual sentence *carry* a marker?") — the actual unmarked-
  assertion hole — requires first deciding **which sentences are factual assertions**. "The p95
  latency dropped to 40ms" needs a marker; "Let's look at three ways to think about this" does not.
  That classification is a **semantic judgment** — the very NLI/claim-decomposition judgment the
  research (AutoAIS S2, FActScore S7) proves is **aggregate-strong but per-claim noisy**, with both
  measuring papers explicitly warning against per-example use "as a system component."

Therefore: **a perfect coverage hard gate is unachievable for the identical reason a perfect
faithfulness hard gate is** — both bottom out in per-claim semantic classification. I will not
design an aspirational gate. I design the strongest *feasible* posture: a deterministic hard floor
of *necessary* structural conditions, plus a semantic layer wired as detection/repair/abstain that
tolerates per-claim noise by construction.

### 2.2 LAYER 1 — HARD, deterministic, compose-time (extends `validate_ir`)

All false-reject-safe, all at the existing chokepoint, all feeding the existing bounded re-ask on
violation (never a new gate location, never a new re-ask point):

1. **(exists) Span↔ledger consistency** — no forged fact-id, no promoted tier. Unchanged.
2. **(NEW) Channel-generalized consistency** — `extract_fact_refs` must recognize the DR-5 `[@key]`
   citation marker as a grounding reference *alongside* `data-fact`, and bind BOTH to the ledger by
   the same rule (this is the SF-3 absorption, §4). One reference model, one binding check.
3. **(NEW) Grounding-utilization floor** — if the ledger holds ≥1 publishable EXTRACTED fact, the
   body must carry ≥1 grounding reference binding a publishable fact. A body that references **zero**
   of its available grounding is an ungrounded body — exactly the DR-6 target — and this is
   false-reject-safe in practice (an artifact built *from* grounding uses grounding). The
   all-leads/empty-grounding case is already handled by the §6.4 empty-pool block + the §6.5 floor;
   the utilization floor keys strictly off "publishable facts were resolved for this item."
4. **(NEW) Scenario well-formedness** — every referenced ledger entry must be publishable under the
   pool-relation rule: EXTRACTED tier (existing floor) AND either scenario-1 (no `attestation`) or
   scenario-2 (`attestation` present and structurally complete — all three sub-fields, anchor
   resolvable-shaped, secret-scanned). A marker binding an entry that is neither is rejected. Once
   the ledger carries the scenario-2 fields (§3) this is fully deterministic. This is the structural
   half of the two-scenario acceptance model: every *marked* claim is provably scenario-1 or -2.

**What Layer 1 does NOT close, stated plainly:** the writer can satisfy utilization (cite `f0` once)
and then emit ten unmarked hallucinated sentences. Layer 1 cannot catch those without deciding they
are assertions — semantic. Hence Layer 2.

### 2.3 LAYER 2 — SEMANTIC, advisory + bounded-repair (the noise-tolerant core)

A single NLI/claim-decomposition verifier (AutoAIS/ALCE-style entailment; RAGAS/FActScore-style
supported-ratio — all *reference-free*, needing only the IR leaves + the ledger facts) produces two
signals over each compose leaf:

- **(a) Unmarked-assertion detection** (coverage forward-direction): decompose the prose into atomic
  claims; flag those that read as factual assertions but carry no marker.
- **(b) Span↔fact entailment** (faithfulness): for each *marked* claim, does the bound ledger fact
  actually SUPPORT it, or is the marker decorative/mis-bound?

This layer is **never a per-claim automatic reject** (the research's hard prohibition). It is wired
two ways, both of which are aggregate/whole-artifact decisions that tolerate per-claim noise:

- **Review 1 advisory score** — an aggregate groundedness ratio (supported-claims / total-claims)
  joins the existing advisory `grounding`/`extracted_floor`/`citability` checks. Aggregate use is
  exactly the regime the verifiers are validated for (S2 r=0.96 system-level; S7 <2% aggregate
  error). Verdict stays `pass|concerns`; this changes nothing about Review 1's advisory contract.
- **Compose-time bounded-repair (RARR detect→revise)** — the verifier runs pre-persist; on a flag it
  appends a *correction note* to the **existing** bounded re-ask (`DEFAULT_MAX_ATTEMPTS`,
  `compose.py`) and the writer re-composes ("mark this assertion or drop it"; "this marker's fact
  does not support the sentence"). This reuses the one re-ask point; it adds a *source* of
  correction notes, not a new loop.

### 2.4 LAYER 3 — item-level ABSTAIN (the §6.4 / GopherCite posture), policy-gated

On persistent Layer-2 failure after the bounded re-ask, the terminal behavior is a **policy lever**:

- **Default = warn-and-ship** — persist, record the groundedness concern on Review 1, do not block.
  Rationale: a per-claim-noisy signal must not *unconditionally* auto-reject a possibly-good
  artifact; the aggregate score is trustworthy enough to *warn*, not to *veto*.
- **Opt-in = block-and-report at the ITEM level** — the whole item blocks with a DR-6 grounding code
  (mirroring `empty-pool`/`hard-limit-exceeded`, §6.4/§16), surfaced in run `results`, other fanout
  items continue. This is the deployed **verify-and-abstain** posture (GopherCite S8) applied at
  *item* granularity — an abstain, never a per-claim gate. It is the strongest honest hard block:
  it blocks the *artifact*, not a *sentence*, so per-claim noise cannot false-reject a single claim.

The lever is a workspace/recipe policy (framework default = warn), letting a high-assurance instance
(e.g. regulated/medical content) choose abstain while the general case ships-with-advisory. This
directly answers the maintainer's hard-vs-advisory question: **Layer 1 is unconditionally hard;
Layer 2/3 is advisory-with-repair by default and hard-abstain by opt-in — because that is the
strongest posture a per-claim-noisy verifier can honestly support.**

### 2.5 The prevention lever (optional, orthogonal): writer-prompt strengthening

Independent of the gates: strengthen `writer.md` to instruct the writer to mark *every* factual
claim (the Context-Aware-Decoding S9 analogue — a *bias, not a gate*: reduces the unmarked-assertion
rate, cannot certify). Cheap, additive, reduces how often Layer 2 must repair. Not a guarantee and
not a substitute for the gates — listed for completeness as the third of the research's three
intervention points (prevent → detect → gate/abstain), all three now mapped.

---

## 3. Q2 — Scenario 2 (secondary attestation): the ledger extension + the policy ruling

### 3.1 The THIRD axis (do not conflate — the research is emphatic)

Scenario 2 = "a pool source references/quotes an out-of-pool primary" (PROV-O `wasQuotedFrom`). It
is a **pool-relation** axis, orthogonal to all three existing axes:

- **≠ the confidence tier** (EXTRACTED/INFERRED/AMBIGUOUS = *how sure*). A scenario-2 attestation is
  itself typically **EXTRACTED** — the pool source verifiably contains the quote. Tier measures
  confidence in the *attestation*; scenario measures the *pool-relation of the claim*.
- **≠ `traceability`** (the boolean *can-you-cite-it* anchor). The attestation has its OWN anchor
  (into the pool source's quote), separate from the primary's traceability.
- **≠ the `primariness` SCORE** (§6.2 ordinal `primary|secondary|tertiary`, which *types the
  source*). A source with `primariness=secondary` may carry a scenario-1 in-pool fact OR a
  scenario-2 attestation — different questions. The research flags this collision explicitly; the
  design must keep them separate fields.

### 3.2 The ledger extension — ONE optional sub-structure

Extend the RI3 ledger entry with a single OPTIONAL field, PROV-O-shaped:

    attestation?: {
      primary:  <the out-of-pool primary's citation-identity — a structured/string
                 descriptor; NOT a source_instance_id, because the primary is not in the pool>,
      anchor:   <a resolvable anchor INTO THE HELD POOL SOURCE locating the quote/reference
                 — reuses the traceability_anchor "<kind>:<value>" shape (file:line / URL-frag /
                 SHA); this is what makes the attestation itself verifiable/traceable>,
      relation: <PROV-O vocabulary: "wasQuotedFrom" (verbatim quote) | a derived-from variant
                 (looser reference)>
    }

- **Presence = scenario 2; absence = scenario 1.** Scenario-1 entries carry no `attestation` and
  **churn nothing** — this is why the field is optional. Model it as `LEDGER_REQUIRED` +
  `LEDGER_OPTIONAL` (copy the existing parts pattern `_PART_REQUIRED`+`_PART_OPTIONAL`), replacing
  the current exact-match `keys == set(LEDGER_FIELDS)`. This keeps every existing scenario-1 ledger
  byte-identical.
- **`primary` is NOT a `source_instance_id`.** Reusing the instance-id field would falsely imply
  pool membership — a category error. The out-of-pool primary is a *citation descriptor*, secret-
  scanned like every ledger string.
- **`anchor` points at the POOL source, not the primary.** We can only ever verify "S contains a
  quote/reference attributing X to B"; we cannot anchor into B (we do not hold it). This anchor is
  what upgrades a bare claim of secondary sourcing into a *checkable* one.
- **No new identity, no new AST/span surface required.** The scenario lives entirely in the ledger;
  a marker resolves its scenario via its fact-id. (Whether serialize surfaces it as an AST Span kv
  is a DR-5/§17 rendering question, deferred — not needed for enforcement.)

### 3.3 The policy ruling (the open item the research handed us): ATTRIBUTED, never bare fact

**Ruling: a scenario-2 claim publishes ONLY as an attributed statement — "According to [pool source
S], B says X" — never as the bare fact "X."** Grounds:

- **AIS attributable-vs-asserted (S1).** The pool does not hold evidence *for* X; it holds evidence
  that *S attests X-from-B*. The proposition the pool grounds is the **attestation** ("S reports B:
  X"), not "X." AIS licenses "According to S, B says X" — an attributed statement — and *withholds*
  the bare "X." Publishing bare "X" would assert something the identified sources cannot support:
  the definitional over-reach DR-6 exists to prevent.
- **§6.5 publish-floor spirit.** Only what the pool EXTRACTS is published as fact. What the pool
  extracts in scenario 2 is the *attestation*; therefore the **attestation (in attributed form) is
  the EXTRACTED-tier publishable unit**, and the attribution is mandatory, not stylistic.
- **The maintainer's own words** ("...makes that pool source a **secondary** source for the claim").
  A secondary source grounds an *attributed* claim; treating it as a primary would collapse the
  scenario distinction the maintainer drew.

**Enforcement of the ruling (consistent with §2's hard/semantic split):**
- **Structural/hard:** a marker binding a scenario-2 entry is *licensed only in attributed form* —
  the ledger entry's `attestation` presence flags that the claim MUST be attributed. This is
  deterministic at the ledger layer.
- **Semantic/advisory-repair:** whether the *prose actually says* "According to S" is the same
  NLI-class judgment — so it is Layer-2's job (detect a scenario-2 marker whose sentence lacks the
  attribution → correction note → re-ask; or advise on Review 1). The attribution *obligation* is
  hard; the *verification that prose satisfies it* is semantic, exactly like coverage.

### 3.4 The two-scenario acceptance model, closed

- **Scenario 1** (in-pool primary): EXTRACTED, traceable, no `attestation` → publishable as fact.
- **Scenario 2** (in-pool secondary attestation): the attestation is EXTRACTED/traceable *to the
  pool source*; `attestation` present → publishable **as an attributed statement only**.
- **Neither** (no pool source attests, primary absent): a hallucination. For a *marked* claim this
  cannot occur (every marked claim is scenario-1 or -2 by ledger construction — Layer-1 rejects a
  forged/promoted/ill-formed-scenario marker). For an *unmarked* assertion it is the semantic hole —
  Layer-2 detect→repair, Layer-3 abstain. So "neither = reject" is enforced *structurally for marked
  claims and semantically for unmarked ones* — the honest closure.

---

## 4. Q3 — Absorbing the three per-feature grounding flags

The per-feature flags were over-specific because each re-derived "couple THIS channel to the
ledger." DR-6's mechanism is **channel-agnostic**: one reference model, one consistency+coverage
gate, one semantic verifier, applied to **every compose leaf regardless of which feature produced
it.** Concretely:

- **DR-2 flag** ("no hard gate that every fact-claim cites an EXTRACTED source"): dissolves into
  Layer-1 consistency + utilization + Layer-2 coverage. There is no DR-2-specific grounding rule —
  house-style/lexicon leaves are ordinary compose leaves subject to the general gate.
- **DR-3 B1** (outline-demanded claims): DR-3 is ratified as an ordinary `Format=outline` artifact
  whose normalized Markdown compose ingests. Outline-demanded claims are therefore ordinary compose
  leaves — the general gate covers them with **zero outline-specific logic**. B1 dissolves.
- **DR-4/DR-5 SF-3** (the `references`/`[@key]` citation channel): the CSL-JSON `references` block +
  inline `[@key]` markers are just **another grounding surface**. The absorption is concrete and
  load-bearing: **`extract_fact_refs` must recognize `[@key]` as a grounding reference alongside
  `data-fact`**, and bind both to the ledger by the same scenario-1/-2 rule (Layer-1 item 2). DR-6
  owns *correctness* (does `[@key]` resolve to grounding?); **DR-5 owns only *formatting*** (the
  per-venue `csl` style, §17/Presentation). The academic-paper "cite the broader literature" case is
  exactly scenario 2: a `[@key]` to an out-of-pool primary is legal **iff** a pool source attests it
  (`attestation` populated) — and then it publishes attributed. Anything beyond that is
  hallucination = reject. This is the SF-3 pool-membership tension resolved by the scenario model.

Net: the flags **stop being per-feature** because grounding stops being per-channel — it becomes one
property of every leaf, checked at one chokepoint.

---

## 5. Q4 — Output-constraint decoupling (confirmed, existing capability)

Groundedness is verified at the **ledger/IR/AST layer, ALWAYS**, independent of whether the artifact
renders an inline citation. This already holds and needs no new construct:

- §15/§17: provenance is consumed at IR/AST only, Office/PDF writers drop unknown attributes, "never
  recovered from output bytes"; §19 reads IR/AST, not bytes. The verifier reads the IR leaves + the
  ledger — never the rendered surface.
- **AIS attributable-vs-cited:** the *obligation* is to be grounded (attributable); the *citation
  marker* is DR-5's surface. An artifact that cannot *show* a citation (a tweet, plain-text) is still
  obligated to *be* grounded — the obligation is checked one layer up.
- **The scenario-2 nuance on "within the output artifact's constraints":** read the maintainer's
  clause as a **license boundary, not a grounding waiver**. The attribution ("According to S") is
  **prose**, not a citation marker, so it renders in *any* artifact. If an artifact is so constrained
  it cannot even carry that prose attribution, the scenario-2 claim **cannot be grounded within that
  artifact and is dropped there / the item blocks** — you never publish a scenario-2 claim as bare
  fact just because the surface can't hold a citation. This obligation joins the §16 reconcile
  fidelity re-anchoring and Review 2's provenance re-check (§2.6 below).

---

## 6. Q5 — Orthogonality + blast radius (HIGH, kept coherent)

DR-6 touches **compose, the ledger, and both reviews** — high blast radius. Coherence with each
existing invariant:

- **Tier model (§6.5):** untouched. Scenario is the orthogonal THIRD axis; the EXTRACTED-only
  publish floor is unchanged; scenario-2 attestations are EXTRACTED-tier *attestations*.
- **§6.5 floor:** DR-6 generalizes the floor's **enforcement** (advisory Review-1 → hard structural
  floor at compose) without changing its **definition**. No tier promotion is introduced anywhere.
- **Existing compose contract gate:** DR-6 **extends** `validate_ir`/`_validate_refs` and
  `extract_fact_refs` at the **same chokepoint**; no new gate location.
- **Bounded re-ask (§21.9):** the semantic verifier feeds the **existing** re-ask as a new source of
  correction notes; **no new re-ask point** (the design.md invariant "the ONLY re-ask point" holds).
- **Review 1/2:** the aggregate groundedness score joins Review 1 (advisory contract unchanged); the
  scenario-2 attribution obligation + attestation-binding join Review 2's provenance re-check at the
  fitted/AST layer (§17), and the **§16 fidelity constraint (RI3-fidelity) extends** to require
  reconcile to preserve the `attestation` fields + the attribution (re-anchored, never dropped to
  bare fact). Additive to an existing obligation, not a new mechanism.

### 6.1 Identity / digest — the honest statement

**ZERO new identity surface.** Verified: the artifact-id preimage is `{dimensions, goals,
source-subset, source-commit}` (`ids.py:749`) and the RI4 binding digest is `digest_full(preimage)`
over that preimage only. **The grounding ledger is in neither.** Therefore the scenario-2 ledger
extension changes **neither the artifact-id nor the RI4 binding digest** — it is a provenance-layer
change, not an identity change (matching DR-4/DR-5's "ZERO new identity component" landings).

What it DOES change: the IR envelope's **closed ledger schema** (`LEDGER_FIELDS`) — an `ir_version`
concern, not an identity one. Flagged honestly for the planner: because the extension is **additive
and optional** (`LEDGER_REQUIRED` + `LEDGER_OPTIONAL`), scenario-1 ledgers are byte-unchanged; but
`validate_ir` pins `ir_version` by exact equality and the IR is immutable/never-migrated (§11.6), so
the planner must decide the `ir_version` bump policy and confirm the re-render/`unwrap_ir` read path
tolerates old-version stored IRs (an additive-optional field should not break old validation, but
the exact-equality `ir_version` check must be reconciled with immutability — a real wrinkle, planner
domain, not an identity risk).

### 6.2 Orthogonality watch-list (blur risks to police)

- **DR-6 (correctness) vs DR-5 (citation formatting):** the line is the `[@key]` marker — DR-6
  checks it *resolves to grounding*; DR-5 *styles* it per venue. Do not let DR-6 reach into CSL
  style; do not let DR-5 own resolution.
- **coverage (structural) vs faithfulness (semantic):** kept in separate layers (1 vs 2). Do not let
  the semantic verifier leak into Layer-1's deterministic gate (that would re-import per-claim noise
  into a hard block).
- **the scenario axis vs the `primariness` score:** separate ledger fields, separate meanings (§3.1).
- **the attestation `anchor` vs `traceability_anchor`:** same *shape*, different *referent* (the
  pool source's quote vs the fact's own anchor). Keep them distinct fields.

---

## 7. Considered and rejected

- **Full sentence-coverage as a deterministic hard gate ("every sentence carries a marker").**
  Rejected: requires a factual-assertion classifier = semantic/noisy; false-rejects connective,
  framing, headings, questions. Not false-reject-safe. This is *why* coverage cannot be fully hard.
- **Writer self-demarcation (every sentence wrapped in either a `data-fact` span or an explicit
  `.framing`/`.rhetorical` "non-grounded" span, so compose can structurally check "no bare
  declarative prose").** This is the ONE path to a structural coverage hard gate, and I flag it as
  the maintainer's likely mental model of "structural." Rejected **for v1**: (a) it relocates the
  semantic judgment to a *self-interested* writer that can mark a hallucination `.framing` to evade;
  (b) high blast radius — it re-architects the writer contract to wrap every sentence, fighting §15's
  "content leaves stay pure Markdown" and complicating the visible-text substance floor and the AST
  Span model; (c) it certifies *structure*, not *grounding*. Revisitable later; not the honest v1 win.
- **Per-claim automatic NLI hard reject at compose.** Rejected: the research's explicit prohibition
  (S2/S7 warn against per-example use as a system component). Per-claim noise → false-rejects of good
  claims. The item-level abstain (Layer 3) is the noise-tolerant substitute.
- **A new confidence tier or a `primariness`-score overload for scenario 2.** Rejected: conflates
  the orthogonal third axis with the tier / with the source-typing score (§3.1). Scenario 2 gets its
  OWN optional field.
- **A new AST span class / identity component for attributed claims.** Rejected as unnecessary: the
  scenario is a ledger property resolved via the fact-id; no new identity or AST surface is required
  for enforcement (surface exposure is DR-5/§17, deferred).

---

## 8. What I did NOT resolve (planner / adversarial-pass domain)

- **The `ir_version` bump vs immutable-no-migration wrinkle** (§6.1) — additive-optional field, but
  the exact-equality version pin and the re-render read path need the planner's ruling.
- **The exact `primary` descriptor schema** (free string vs structured citation object) — a
  representation sub-decision; PROV-O gives the *relation* vocabulary, not the descriptor shape.
- **The default of the Layer-3 policy lever** — I recommend `warn` as the framework default; the
  maintainer may prefer `block` as the safe default. This is a values call, flagged.
- **Whether the utilization floor (Layer-1 item 3) should be the weak form ("≥1 publishable fact
  referenced") or a stronger "every publishable fact referenced" completeness rule.** I recommend the
  weak form as HARD (false-reject-safe) and the completeness rule as ADVISORY (Review 1) — an
  adversarial pass should test whether the weak form is too weak to be worth a hard gate.
- **The verifier's engine choice + cost** (NLI model vs claim-decomposition; per-leaf LLM cost on the
  compose hot path) — an operational/planner concern; the research names the candidate families
  (AutoAIS/ALCE entailment; RAGAS/FActScore decomposition), all reference-free.
- **A targeted vendor-doc pass** (Vertex check-grounding / Azure groundedness / Bedrock) — the
  research deliberately skipped these (weak-source rule); only worth it if the maintainer wants a
  production-posture datapoint before ratifying the hard-vs-advisory default.

---

## 9. One-line summary

Promote the deterministic **spans→ledger** half of coverage to a HARD compose gate (consistency +
utilization + scenario well-formedness, channel-generalized to `[@key]`); keep the semantic
**assertions→spans** and **faithfulness** halves as an aggregate advisory score + a bounded-repair
re-ask signal + an opt-in item-level abstain — because a perfect semantic hard gate is unachievable;
represent scenario 2 as ONE optional PROV-O `attestation?` ledger field (a third, pool-relation
axis) that publishes **only as an attributed statement**; absorb DR-2/DR-3/DR-4-5 by making grounding
one channel-agnostic property of every compose leaf; verify at the IR/ledger layer always
(decoupled from DR-5's citation surface); ZERO new identity surface.
