# DR-6 — External grounding research + mapping onto the pipeline

**Pass:** docs-researcher, external-grounding for DR-6 (general grounding enforcement).
**Scope:** GROUND external primary sources on grounded/attributed generation enforcement, and MAP
each mechanism onto the pipeline's compose ↔ ledger ↔ review model. **No design.** Read-only.
**Date:** 2026-07-17. **Repo:** /Users/david/Developer/optiquity-content-pipeline

Every claim is tagged **[VERIFIED]** (I fetched the primary source and read the quoted text) or
**[INFERRED]** (my synthesis / cross-source reasoning, flagged for the architect to confirm). Vendor
blogs were treated as weak and not relied on.

---

## 1. Sources

Primary sources fetched (arXiv abstract, ar5iv HTML full-text, or PDF; W3C recommendation):

| # | Source | ID / URL | What it grounds | Fetch quality |
|---|---|---|---|---|
| S1 | Rashkin et al., *Measuring Attribution in NLG Models* (AIS), Computational Linguistics 2023 | arXiv 2112.12870 — https://ar5iv.labs.arxiv.org/html/2112.12870 | The AIS definition; human 2-stage interpretability→attribution pipeline | ar5iv full-text, strong |
| S2 | Bohnet et al., *Attributed Question Answering* (AutoAIS) 2022 | arXiv 2212.08037 — https://ar5iv.labs.arxiv.org/html/2212.08037 | Automatic NLI approximation of AIS; correlation numbers | ar5iv full-text, strong |
| S3 | Gao, Yen, Yu, Chen, *Enabling LLMs to Generate Text with Citations* (ALCE) 2023 | arXiv 2305.14627 — https://ar5iv.labs.arxiv.org/html/2305.14627 | Citation recall/precision via NLI entailment | ar5iv full-text, strong |
| S4 | Es, James, Espinosa-Anke, Schockaert, *RAGAS* 2023 | arXiv 2309.15217 — https://arxiv.org/pdf/2309.15217 | Reference-free Faithfulness metric (claim decomposition + support-check) | PDF, moderate (see caveat) |
| S5 | Gao et al., *RARR* (Research-and-Revise), ACL 2023 | arXiv 2210.08726 | Post-hoc attribution + revision of already-generated text | abstract only |
| S6 | Manakul, Liusie, Gales, *SelfCheckGPT*, EMNLP 2023 | arXiv 2303.08896 | Zero-resource sampling/consistency hallucination detection | abstract, strong |
| S7 | Min et al., *FActScore* 2023 | arXiv 2305.14251 — https://ar5iv.labs.arxiv.org/html/2305.14251 | % atomic facts supported by a knowledge source; automatic estimator error rate | ar5iv full-text, strong |
| S8 | Menick et al., *GopherCite: Teaching LMs to support answers with verified quotes* 2022 | arXiv 2203.11147 | Cite-with-quotes + **abstain-when-unsure** (deployed pattern) | abstract, strong |
| S9 | Shi et al., *Context-Aware Decoding* (CAD) 2023 | arXiv 2305.14739 | Decoding-time (inference-time) faithfulness steering | abstract, strong |
| S10 | W3C, *PROV-O: The PROV Ontology* (W3C Recommendation) | https://www.w3.org/TR/prov-o/ | Encoding primary/secondary provenance: `hadPrimarySource`, `wasQuotedFrom`, `wasDerivedFrom` | W3C REC, strong |
| S11 | Honovich et al., *TRUE: Re-evaluating Factual Consistency Evaluation* 2022 | arXiv 2204.04991 (referenced via S3) | The NLI model ALCE/AutoAIS use as the entailment verifier | not directly fetched (cited through S3) |

**Fetch caveats / author-attribution corrections (the small-model summarizer erred, corrected here):**
- **S4 (RAGAS)** — the WebFetch summarizer attributed the paper to "Gunjal et al." That is **wrong**;
  RAGAS is **Es, James, Espinosa-Anke & Schockaert (2023)**. The *faithfulness definition and
  3-step computation* were extracted from the fetched PDF and are reliable; only the byline was
  mis-summarized. Treat the definition as [VERIFIED-from-PDF], the algorithm's precise sub-steps as
  moderate confidence.
- **S11 (TRUE)** not fetched directly — its identity as "a T5-11B fine-tuned on NLI datasets" comes
  through S2/S3. [INFERRED] where it rests only on that.
- No vendor grounding-gate docs (Google Vertex "check-grounding", Azure "groundedness detection",
  OpenAI) were fetched — deliberately, per the weak-source rule. Their existence/behavior is
  therefore **NOT verified** here (see §5).

---

## 2. Enforcement findings — HARD gate vs ADVISORY (DR-6's core question)

The single most load-bearing external finding for DR-6:

> **[INFERRED — cross-source synthesis]** No mature system enforces groundedness as a *generation-time
> hard guarantee*. Every reliable enforcement mechanism in the literature is a **verifier applied to
> already-produced text** (post-hoc), which a system may then wire into a **gate** (accept / reject /
> revise / abstain). "Hard-gating" groundedness in practice = *verify-then-act*, not *guarantee-at-decode*.

The evidence, laid on a gen-time → review-time axis:

### 2a. Generation-time / decoding-time interventions — REDUCE, do not GUARANTEE
- **Context-Aware Decoding (CAD, S9)** [VERIFIED]: a *decoding-time* intervention — a contrastive
  output distribution "that amplifies the difference between the output probabilities when a model is
  used with and without context," steering generation toward the provided context and "overriding a
  model's prior knowledge when it contradicts the provided context." It *significantly improves*
  faithfulness with no retraining. **It is a bias, not a gate** — it lowers hallucination probability
  at decode; it does not certify any given sentence is grounded. [INFERRED] There is no hard guarantee.
- **GopherCite (S8)** [VERIFIED]: an RL-trained 280B model that produces answers "with high quality
  supporting evidence and **abstain[s] from answering when unsure**." Abstaining on the lowest-confidence
  third of questions raised accuracy from 80%→90% on Natural Questions. This is the closest deployed
  thing to a *gen-time grounding posture* — but its guarantee is delivered by **verify-and-abstain**
  (produce a verbatim quote or decline), i.e. a self-check + refusal, **not** a decode-time proof.

### 2b. Post-hoc verification — the reliable, deployable core (all of these are what actually "works")
- **NLI/entailment verification** (ALCE citation recall/precision, S3; AutoAIS, S2) [VERIFIED]: check
  whether the cited/retrieved passage *entails* the statement, using an NLI model (TRUE / T5-11B). This
  is the workhorse verifier — deployable today, automatic, per-claim.
- **Claim-decomposition + support-check** (RAGAS Faithfulness, S4; FActScore, S7) [VERIFIED]: break the
  generation into atomic claims/statements, verify each against the source, report the supported ratio.
  Reference-free (needs only answer + source), so it runs without gold answers.
- **Post-hoc attribution + revision** (RARR, S5) [VERIFIED]: "automatically finds attribution for the
  output of any text generation model and post-edits the output to fix unsupported content while
  preserving the original output as much as possible." A *repair* loop, not a gate — but it shows the
  detect→revise pattern rather than detect→reject.
- **Zero-resource self-consistency** (SelfCheckGPT, S6) [VERIFIED]: sample the model N times; "for
  hallucinated facts, stochastically sampled responses are likely to diverge and contradict one
  another," whereas grounded facts stay consistent. Black-box, **no external database** — a detector
  usable where you lack the source pool, but weaker than source-grounded NLI when a pool exists.

### 2c. Human judgment — the gold, the ceiling on the verifiers
- **AIS (S1)** [VERIFIED] is a **human annotation** framework (2-stage pipeline), not an automatic
  metric. It is the definition the automatic verifiers *approximate*.

### 2d. How reliable is the automatic verification? (the honest ceiling)
- **AutoAIS vs human AIS (S2)** [VERIFIED]: **system-level Pearson r = 0.96** (excellent in aggregate),
  but "**Correlation was much lower and more variable**" at the **example level**, with the explicit
  warning that AutoAIS is "fit-for-purpose as a development metric at the aggregate level (**provided it
  is not used as a system component**)" and "care should be taken against reading individual AutoAIS
  scores too closely."
- **FActScore automatic estimator (S7)** [VERIFIED]: estimates the human FActScore with "**less than a
  2% error rate**" *in aggregate*, but "is not perfect in individual judgments." (Human eval cost the
  paper $4/generation — the reason automation matters.)

> **[INFERRED — the DR-6 takeaway]** The automatic grounding verifiers are **statistically excellent in
> aggregate but noisy per-claim**. That is precisely the profile that makes a **per-claim automatic HARD
> gate risky** (false-rejects/false-accepts on individual claims) while making an **aggregate advisory
> signal trustworthy**. The two papers that measured it (S2, S7) both explicitly warn against using the
> automatic metric *as a system component / per-example*. This is the empirical crux the architect must
> weigh for DR-6's hard-vs-advisory decision — it does not settle it, but it names the cost of each side.

---

## 3. Attribution/groundedness frameworks + the primary/secondary source model

### 3a. AIS — the canonical definition of "grounded in source" [VERIFIED, S1]
AIS = **Attributable to Identified Sources**. A system output `s` (with context `c`) is AIS w.r.t. a
provided source set `P` iff, roughly, a **generic hearer would affirm "According to `P`, `s`."** The
formal conditions (S1): (1) `P` is provided with `s`; (2) `s` in context `c` is **interpretable**;
(3) its **explicature** `E(c,s)` is a standalone proposition; (4) `(E(c,s), P)` is **attributable to `P`**.
Two decoupled stages in the human pipeline: **interpretability** (is the claim a clear standalone
proposition?) then **attribution** (is that proposition supported by the source?).

Two properties of AIS that matter enormously for DR-6:
1. **Attribution is judged against the *provided/identified* sources — not against ground truth.**
   [VERIFIED] A claim is "grounded" if the *held* sources support it, regardless of whether they are the
   ultimate origin. This is *exactly* the pipeline's "scanned pool" framing — grounding is
   relative-to-pool, not relative-to-all-truth.
2. **"Attributable" is a property of the claim↔source relation, separate from whether a citation is
   shown.** [INFERRED, from S1's explicature/standalone-proposition construction] AIS scores the
   *proposition*, not the surface citation marker — which is what lets grounding be enforced even when
   the output artifact carries no inline citation (§5 below).

### 3b. Operationalizing AIS automatically — AutoAIS / ALCE / RAGAS / FActScore
- **AutoAIS (S2)** [VERIFIED]: recast AIS as **NLI** — does the source entail the (question, answer)?
  Aggregate-faithful, per-example noisy (§2d).
- **ALCE (S3)** [VERIFIED]: **Citation recall** = for statement `s_i`, `1` iff it has ≥1 citation AND the
  concatenated cited set entails `s_i` (`φ(concat(C_i), s_i)=1`, `φ` = NLI/TRUE model). **Citation
  precision** = a citation `c_{i,j}` is *irrelevant* iff it alone does not entail (`φ(c_{i,j},s_i)=0`)
  AND the statement is still entailed without it; precision credits non-irrelevant citations on
  recall-satisfied statements. Triad of automatic metrics: **fluency + correctness + citation quality**.
- **RAGAS Faithfulness (S4)** [VERIFIED-from-PDF]: "the answer is faithful if **all claims made in the
  answer can be inferred from the given retrieved context**"; computed as (supported claims)/(total
  claims) after statement extraction. **Reference-free.**
- **FActScore (S7)** [VERIFIED]: `f(y) = (1/|A_y|) Σ 1[a is supported by C]` — the fraction of **atomic
  facts** supported by a **reliable knowledge source** `C`. Fine-grained, per-atomic-fact.

**[INFERRED] Common shape across all four:** *decompose the generation into atomic claims → verify each
claim's entailment against the identified source → aggregate.* This is the same shape the pipeline's
per-fact ledger already imposes at ground-time (one ledger entry per (fact, instance)) — the external
verifiers add the missing *coverage* check the pipeline does not do (does **every** prose claim map to a
ledger fact?). See §4.

### 3c. The primary/secondary source model — a RECOGNIZED, STANDARDIZED pattern [VERIFIED, S10]
The maintainer's two-scenario model (primary-in-pool vs secondary-attestation) is a first-class,
**W3C-standardized** provenance pattern. In **PROV-O (S10)**, `prov:wasDerivedFrom` has three
sub-properties, two of which encode the maintainer's model exactly:
- **`prov:hadPrimarySource`** [VERIFIED]: "cites a preceding Entity produced by some agent with **direct
  experience and knowledge about the topic** (such as a reading from a sensor, or a journal written
  during an historical event)." → the maintainer's **primary source**.
- **`prov:wasQuotedFrom`** [VERIFIED]: "cites a potentially larger Entity ... from which a new Entity was
  created by **repeating some or all of the original**." → the mechanism of a **secondary attestation**
  (a pool source quoting/referencing a primary).
- **`prov:wasRevisionOf`** [VERIFIED]: derived entity "contains substantial content from the original."
- All three are **sub-properties of `prov:wasDerivedFrom`** [VERIFIED] — provenance is a *chain*, and
  "citation-of-a-citation" is representable as a derivation chain `claim → wasQuotedFrom → poolSource`
  and `poolSource → (attests to) → primarySource(not held)`.

**[INFERRED] Mapping the two scenarios to standard vocabulary:**
- Scenario 1 (**Direct/primary — primary IS in the pool**) ≈ the claim is *attributable to `P`* in AIS
  terms, with the pool source being the primary (`prov:hadPrimarySource` in-pool). Fully covered by
  today's ledger.
- Scenario 2 (**Secondary attestation — primary NOT in pool, a pool source references/quotes it**) ≈ the
  claim is *attributable to `P`* **only as an attributed statement**: AIS would license "According to
  [pool source], primary B says X," i.e. the *held* proposition is "pool-source attests X-from-B," not
  the bare "X." PROV encodes this as the pool source `prov:wasQuotedFrom`/attesting the out-of-pool
  primary. **This is citation-of-a-citation / secondary sourcing — a recognized pattern in both
  library-science source typing (primary/secondary/tertiary) and PROV.**

**[INFERRED — a vocabulary-collision the architect must not conflate]** The pipeline **already has a
score named `primariness`** (§6.2: ordinal `primary | secondary | tertiary`, attached at the source
*instance*, semi-derived). That score describes **the nature of a source** (is this source a primary,
secondary, or tertiary source?). The maintainer's scenario axis is a **different question**: is the
claim's primary origin **inside the pool**, or only **attested by** a pool source? The two are related
(a scenario-2 attestation is typically carried by a source whose `primariness` = secondary/tertiary) but
they are **not the same field**. Today's ledger records the *held* source's identity + its `primariness`
score; it has **no field for the out-of-pool primary's identity nor for the attestation link** — so
scenario 2 is not representable in the current ledger without extension (§4, §5).

---

## 4. Mapping table — where each external mechanism lands on the pipeline (NO design)

Anchored to the pipeline model: **Ground (§6)** → **grounding ledger (§15/RI3)** → **compose (§15,
`pipeline/compose.py`)** → **reconcile (§16)** → **serialize/AST (§17)** → **Review 1/2 (§19,
`pipeline/review.py`)**. The **EXTRACTED publish floor (§6.5)** is the invariant DR-6 wants enforced
generally.

**First, the verified state of enforcement in the pipeline TODAY (so the architect sees the real gap):**
- **[VERIFIED — code]** Compose (`pipeline/compose.py`) HAS a compose-time **hard contract gate**, but a
  *specific* one: the writer returns only leaf Markdown; compose stamps ids/ledger/tiers; a writer output
  is re-asked (bounded, `DEFAULT_MAX_ATTEMPTS=3`) and, on persistent failure, returned as
  `compose-contract-violation` and **NEVER persisted** if a provenance Span (a) references an **unknown
  fact-id** or (b) carries a **tier class that contradicts the ledger** ("even a valid [output] cannot
  carry a forged id or a **promoted tier**"). Plus the §15 **substance floor** (`validate_ir`, ≥1 visible
  letter/digit) — a content-blind SHAPE gate.
- **[VERIFIED — code + §19]** What compose does **NOT** hard-gate: that **every** published-as-fact
  sentence actually *carries* a grounding Span tracing to an EXTRACTED (or scenario-2) ledger fact. An
  **unmarked assertion** (a factual sentence with no `data-fact` span) is not caught by the compose
  contract gate — the gate enforces *span↔ledger consistency for spans that exist*, not *coverage*.
- **[VERIFIED — `pipeline/review.py`]** Review 1 (artifact review) checks `grounding` / `extracted_floor`
  / `citability` but is **ADVISORY**: verdict `pass | concerns`, per-check `concern` is "an advisory
  flag, **never a block**," and its docstring states it "**never *enforces* the floor (that is
  compose's/reconcile's job)**." Review 2 re-checks provenance bindings at the IR-fitted/AST layer,
  advisory.

→ **[VERIFIED] This is exactly DR-6's gap:** the *coverage* invariant ("every fact-claim traces to an
EXTRACTED/attested source") is enforced **nowhere as a hard block** — compose enforces span *consistency*
(no forgery/promotion), Review 1 only *advises* on grounding *coverage*.

| External mechanism (source) | What it does | Nearest pipeline home | Notes for the architect (NOT a recommendation) |
|---|---|---|---|
| **AIS definition** (S1) | "According to `P`, `s`" — attributable-to-identified-sources | The **§6.5 invariant** itself + §3.3 | AIS is the *formal name* for what §6.5 already asserts; the pipeline's "scanned pool" = AIS's "identified sources `P`." Pool-relative, not truth-relative. |
| **AutoAIS / NLI entailment** (S2) | Automatic per-claim source-entailment check | A **verifier** callable at compose (pre-persist) OR Review 1 | This is the concrete engine for a *coverage* check. Aggregate-strong, per-example noisy (§2d) — bears directly on hard-vs-advisory. |
| **ALCE citation recall/precision** (S3) | NLI: does the cited set entail the statement (recall); is each citation non-irrelevant (precision) | Ledger↔claim binding check; **Review 1 citability**, and the `references`/`[@key]` channel (DR-5) | The pipeline's `[claim]{.TIER data-fact="fN"}` span *is* a citation binding; recall/precision is the automatic way to score whether the bound fact actually supports the sentence. |
| **RAGAS Faithfulness** (S4) | Reference-free: fraction of answer claims inferable from context | An **aggregate advisory score** on the IR at Review 1 | Reference-free ⇒ needs only IR + ledger facts; a natural advisory groundedness score. |
| **FActScore** (S7) | % atomic facts supported by a reliable source | Per-fact **coverage metric** over the ledger | Its atomic-fact decomposition mirrors the pipeline's per-fact ledger; the missing piece is verifying *prose* claims map onto those facts. |
| **RARR** (S5) | Post-hoc detect → **revise** unsupported content | The **bounded re-ask** loop in compose (`pipeline/compose.py`) | The pipeline's re-ask is already a detect→repair loop; RARR is the same posture (revise, not reject) — a precedent for repair-over-block if the architect leans advisory-with-repair. |
| **GopherCite abstain-when-unsure** (S8) | Cite-with-quote OR **abstain** | §6.4 **empty-pool block-and-report** (`empty-pool` code) | The pipeline already *blocks* an item that cannot be grounded (empty pool). "Abstain/decline" is the deployed analogue of block-and-report — a precedent for hard-blocking the *whole item*, distinct from per-claim gating. |
| **Context-Aware Decoding** (S9) | Decoding-time steering toward context | Would sit *inside* the writer invocation (transport/prompt), pre-ledger | A *prevention* lever, not a gate; reduces ungrounded generation but cannot certify it. Orthogonal to the enforcement question. |
| **SelfCheckGPT** (S6) | Zero-resource sampling/consistency detection | A fallback detector where the pool is thin/absent | Weaker than source-NLI when a pool exists; possibly relevant only as defense-in-depth. |
| **PROV `hadPrimarySource` / `wasQuotedFrom`** (S10) | Standard encoding of primary vs secondary/quoted provenance chains | The **grounding ledger (§15/RI3)** record shape | The ledger records the *held* source + `primariness` score, but **no out-of-pool-primary field and no attestation link** — scenario 2 (secondary attestation) is **not representable today** without a ledger extension. PROV shows the *standard* fields to add if the architect chooses to represent it. |

**Two-scenario ↔ tiers/floor mapping [INFERRED, for architect confirmation]:**
- The **EXTRACTED / INFERRED / AMBIGUOUS** tier axis answers *how sure* (§6.5, orthogonal to
  `traceability` = *can you cite it*). The maintainer's **primary-in-pool vs secondary-attestation** axis
  is a **third, currently-unmodeled dimension**: *what is the claim's relation to the pool* (direct origin
  vs attested-via). It is **not** the same as the tier and **not** the same as `traceability`.
- Scenario 1 (primary in pool) maps cleanly to today's model: an EXTRACTED, traceable fact whose ledger
  `source_instance_id` is a pool source. **Publishable-as-fact under §6.5.**
- Scenario 2 (secondary attestation) is the *new* case: the *held* attestation may itself be EXTRACTED and
  traceable **to the pool source**, but the underlying claim's primary is out-of-pool. Whether it is
  "published as fact" or "published as attributed statement" ("According to B…") is the AIS distinction
  (§3a.1) and interacts with the §6.5 floor — **this is the open mapping the architect must resolve**;
  the research shows it is a real, standard pattern, not an ad-hoc one.
- A claim that is **neither** (no pool source attests, primary absent) = the maintainer's **hallucination
  = reject**, which aligns with §6.4 **block-and-report** at the item level and with a would-be
  coverage-gate at compose.

**Output-constraint interaction (task item 5) [VERIFIED framing + INFERRED mapping]:**
- AIS decouples *attributable* (the property) from *cited* (the surface marker) [S1, §3a.2]. Groundedness
  is verified against the **identified sources**, not against whatever the rendered artifact displays.
- The pipeline **already implements this decoupling**: **[VERIFIED — §15/§17]** per-fact provenance lives
  in the IR grounding ledger and on AST Spans (`[claim]{.TIER data-fact=…}`); **§17 states Office/PDF
  writers drop unknown attributes** so "**provenance is consumed at the IR/AST layers only, never
  recovered from output bytes**," and §19 reads the IR/AST, not the bytes. **[INFERRED]** Therefore
  "ground everything, but *within the output artifact's constraints*" maps onto: **verify groundedness at
  the ledger/IR/AST layer (always), and render inline citations only where the artifact permits.** The
  DR-5 `references`/CSL/`[@key]` channel is the surface-citation path; DR-6 groundedness is the
  ledger-layer property — the artifact's inability to *show* a citation does not remove the *obligation to
  be grounded*, because the obligation is checked one layer up. This is an existing capability, not a new
  construct.

---

## 5. What I could NOT verify

- **Production vendor hard-gates.** I did not fetch Google Vertex "check-grounding," Azure AI Content
  Safety "groundedness detection," OpenAI, or Bedrock grounding docs (weak-source rule). So the claim
  "**no** production system hard-gates groundedness at gen-time" is **[INFERRED]** from the research
  literature only; a vendor may ship a verify-then-block API. Recommend a targeted vendor-doc pass **only
  if** the architect wants a production-posture datapoint — flagged, not done.
- **TRUE (S11)** was not fetched directly; its description ("T5-11B fine-tuned on NLI") is [INFERRED] from
  S2/S3's citations of it.
- **RAGAS exact algorithm (S4)** — the *definition* is [VERIFIED-from-PDF]; the precise 3-step sub-routine
  (statement extraction prompt, per-statement verdict aggregation) is a moderate-confidence summary, not a
  line-by-line read. The byline was mis-summarized by the fetch tool and is corrected in §1.
- **Whether scenario-2 secondary attestation is *safe* to publish as bare fact vs only as attributed
  statement** — this is a *policy/design* question (AIS gives the vocabulary, §3a.2, but not the ruling).
  Out of scope for this pass by instruction (ground + map only); flagged as the central open item for the
  architect.
- **The pipeline's writer prompt coverage behavior** — I confirmed the compose *contract gate* does not
  require every sentence to be span-covered, but I did not exhaustively read `pipeline/prompts/writer.md`
  to see how strongly the prompt *asks* for full coverage (a soft nudge, not a hard gate, either way). If
  the architect needs the exact prompt language, that file is the place.
- **No numeric claim beyond S2 (Pearson 0.96 system-level; example-level "much lower") and S7 (<2%
  aggregate error) was independently reproduced** — both are as reported by their own authors [VERIFIED
  as *reported*], not third-party replications.

---

## Bottom line for the architect (grounding + mapping only — no design)

1. **The invariant already exists (§6.5) and has a formal name: AIS** [S1]. The pipeline's "scanned
   pool" is AIS's "identified sources"; grounding is pool-relative, exactly as DR-6 frames it.
2. **The enforcement gap is real and precisely located** [VERIFIED, code]: compose hard-gates span↔ledger
   *consistency* (no forged fact-id, no promoted tier) + substance shape; it does **not** gate *coverage*
   (every claim traces to an EXTRACTED/attested fact); Review 1 only *advises* coverage. That is DR-6.
3. **The state of the art offers no gen-time hard guarantee** [INFERRED synthesis]; the deployable,
   reliable mechanisms are **post-hoc NLI/claim-decomposition verifiers** (S2/S3/S4/S7) that a system
   *wires into* a gate — and they are **aggregate-strong but per-claim noisy** (S2, S7 both warn against
   per-example use as a system component). The two honest deployed *postures* are **verify-and-abstain /
   block** (GopherCite S8 ↔ the pipeline's §6.4 block-and-report) and **detect-and-revise** (RARR S5 ↔ the
   pipeline's bounded re-ask).
4. **The primary/secondary model is a standard pattern** [VERIFIED, S10]: PROV `hadPrimarySource`
   (scenario 1) and `wasQuotedFrom` (scenario 2's mechanism), both sub-properties of `wasDerivedFrom` —
   citation-of-a-citation. It is a **third axis** distinct from tier and from `traceability`, and
   **not** the same as the pipeline's existing `primariness` *score* (which types the source, not the
   pool-relation). **Scenario 2 is not representable in today's ledger** (no out-of-pool-primary field,
   no attestation link) — a gap the architect must confront if scenario 2 is to be enforced.
5. **The "within output constraints" clause is already satisfiable** [VERIFIED, §15/§17]: groundedness is
   a ledger/IR-layer property, decoupled from whether the artifact renders an inline citation (AIS
   attributable-vs-cited distinction) — the pipeline already consumes provenance at IR/AST and strips it
   from writer bytes. DR-6 is about the *property*, DR-5/CSL is about the *surface*.
