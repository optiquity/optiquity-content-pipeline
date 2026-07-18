# DR-6 — General grounding enforcement — ARCHITECT (mode: RECONCILIATION)

**Pass:** ops-architect, stage 03 of the DR-6 combined pass. Reconciles the stage-01 INITIAL against
the stage-02 ADVERSARIAL, re-verifying BOTH against `docs/design.md` and the code
(`pipeline/{ir,compose,review,reconcile,driver,transport,grounding,ids}.py`,
`pipeline/prompts/writer.md`). **Design only — no code, no implementation plan** (the planner runs
after the maintainer gate). Read-only.

I re-verified the disputed facts myself rather than trusting either prior report; the verifications
are inlined where they change a ruling.

---

## 1. Reconciled executive verdict

The initial's skeleton is sound and three of its landings survive untouched (zero new identity
surface; scenario as an orthogonal THIRD pool-relation axis; a *perfect* semantic coverage hard gate
is unachievable). But its **headline posture is wrong in the one way that matters most**: it answered
the maintainer's literal question — "should compose HARD-gate coverage, or keep the advisory
posture?" — by retreating to *advisory + repair, hard only by opt-in*, and it closed the one design
that answers "yes" (writer self-demarcation) in a rejected-alternatives bullet. That is the
architect pre-empting the maintainer's own decision. **This reconciliation re-opens it and puts it to
the maintainer as the lead gate item**, argued fairly, with a recommended posture — but the adoption
call is the maintainer's, not mine.

The adversarial's central insight is correct and I adopt it: the options are **not either/or**.
Writer self-demarcation (a HARD, deterministic *structural coverage* gate) **combines** with the
semantic verifier (a *framing-honesty + faithfulness* audit) and a Layer-3 item-level abstain. The
combination is strictly stronger than the initial's utilization floor and it honors the enforcement
ask, while leaving intact the true residual (a fallible/gaming writer can mislabel a hallucination as
`.framing`; the semantic half stays noisy). **I recommend the combined posture** — with two honest
caveats the maintainer must weigh (cost + false-confidence risk), below.

The second blocker is also upheld and fixed: the semantic layer as an initial-implied **pre-persist
per-leaf `claude -p` verifier** is not viable-as-placed (transport is subscription `claude -p` only;
the AutoAIS/FActScore reliability numbers were measured on a dedicated NLI model, not a Claude
self-check). **Default placement is Review-1** (already an LLM call carrying a `grounding` check — so
the semantic score is free there); a pre-persist verifier is a measured, opt-in escalation only.

Every should-fix is accepted and fixed except where noted; the two cross-DR blockers (X1 `[@key]`
conflation, X2 hard-section × hard-grounding) are resolved below; the `ir_version` governance wrinkle
is owned here (relocated + a horn picked), not deferred.

---

## 2. THE LEAD MAINTAINER GATE — the self-demarcation fork (BLK-1), with the recommended combined posture

### 2.1 Why this is the maintainer's call, not the architect's

The maintainer's DR-6 question (`known-issues.md` DR-6) is literally: *"should compose **HARD-gate**
this at compose time … or keep the current **advisory §19-review** posture?"* The initial answered
"advisory + bounded-repair, hard only by opt-in" (§2.3/§2.4) — which is *the current posture plus a
repair loop*. It then named the one design that answers "yes, hard-gate coverage" — writer
self-demarcation — called it "the maintainer's likely mental model of 'structural'," and rejected it
in §7. **A fork this central to the maintainer's own question cannot be closed by the architect in a
rejected-alternatives bullet.** I re-open it and present it fairly.

**The self-demarcation mechanism.** The writer marks *every* unit of prose as either a grounding span
(`[claim]{.TIER data-fact="fN"}`, as today) or an explicit non-grounded span (`.framing` /
`.rhetorical`). Compose then runs a **deterministic completeness check**: no bare declarative prose
may exist outside a span. A body with unmarked declarative text is rejected into the existing bounded
re-ask — a genuine HARD, false-reject-safe (modulo the contract), no-LLM structural coverage gate.
This is the direct "yes" to the maintainer's question.

### 2.2 The adversarial's key correction I adopt: it is NOT either/or — it COMBINES

The initial framed the choice as *self-demarcation (rejected) vs. advisory-coverage + utilization
floor (chosen)*. That was a false binary. The strongest posture is the **combination**:

- **Structural half (HARD, compose, deterministic):** self-demarcation's no-bare-declarative gate.
- **Semantic half (ADVISORY, Review-1 + Layer-3 abstain):** a framing-honesty audit ("is this
  writer-declared `.framing` span actually a factual assertion in disguise?") plus the existing
  span↔fact entailment (faithfulness) check.

The combination makes the semantic layer's job *smaller and closed*, which is the crux. Under the
initial's design the writer's evasion is a **silent omission** (emit an unmarked hallucinated
sentence), which forces the verifier to first *segment prose and decide de novo which unmarked
sentences are assertions* — the open-ended, noisiest problem. Under self-demarcation the evasion must
be an **affirmative mislabel** (`.framing` on a factual sentence), which is a **bounded, closed**
check ("is this declared-framing span factual?"). Self-demarcation shrinks the semantic surface; it
does not remove it. **Verified in code that the construct is cheap to add:** `extract_fact_refs`
already ignores spans with no `data-fact` (`ir.py:398-399`), and `_visible_text`/`_has_substance`
already strip bracketed-span attr blocks and count only visible text (`ir.py:429-476`) — so a
`.framing` span is the *same* Pandoc bracketed-span construct both surfaces already handle. It adds a
*requirement*, not a new *construct*.

### 2.3 My recommendation: adopt the combined posture — with two honest caveats priced

**I recommend the combination** (self-demarcation HARD structural gate + semantic Review-1 audit +
Layer-3 abstain) as the strongest posture that *honestly answers the maintainer's ask*. It is the
only option that delivers a real hard coverage gate without asserting a grounding guarantee a
per-claim-noisy verifier cannot support. But the maintainer must price two costs the initial
understated and the adversarial correctly surfaced:

**Cost (three concrete, moderate, localized changes):**
1. **A `writer.md` contract change** — the writer must wrap *all* prose (not just factual claims,
   which today's contract already asks for at `writer.md:27`, but also framing/connective/heading
   text) in either a grounding or a `.framing` span. This is a bigger prompt-contract change than
   "mark every claim," and it has a **structural long tail**: headings, list markers, table cells,
   code blocks, and math are not "declarative prose" and must be *exempted* by the contract. Each
   exemption is a rule; getting the set wrong either false-rejects legitimate content or opens a hole
   (a hallucination hidden inside an over-broad "exempt" construct). The gate is deterministic, but
   its "what counts as bare declarative prose" boundary is a real design surface, not a one-liner.
2. **One compose-time completeness check.** Honestly priced, this is **more than a regex**: deciding
   "declarative prose outside a span" is a block-level notion (a heading's text vs. a paragraph's
   text), and compose today does *no* Pandoc parse — it uses regex bracket scanning
   (`extract_fact_refs`, `_visible_text`). The check needs block-awareness (a Pandoc-reader parse at
   compose, or a block-aware extension of the existing scanner). Deterministic and local (no LLM),
   but a new compose-time parsing dependency — moderate, not free.
3. **A §17 provenance-strip decision for `.framing` spans.** The `.framing` class is compose-internal
   structural bookkeeping (like the tier class and `data-fact`), and like them it must be consumed at
   IR/AST and **not** leak to publish bytes. The fail-closed strip filter (`design.md:1580-1589`)
   today strips provenance Attr (`data-*`, tier classes) for non-`SAFE_WRITERS`; the `.framing` class
   is neither, so its treatment must be decided explicitly (add it to the strip-set). One-line policy
   decision, flagged so it is not forgotten.

**Residual risk (the honest ceiling — this is why I do not oversell it):**
- **A hard PASS carries authority a self-labeling gate cannot fully earn.** A fallible/gaming writer
  that dresses a hallucination as `.framing` produces **false confidence with a hard-gate badge** —
  arguably worse than an advisory flag over a good artifact, because the green light says "coverage
  enforced" over a body it did not truly enforce. The semantic half (framing-honesty) is exactly as
  noisy as coverage was; self-demarcation buys a hard gate on *form*, not on *grounding-honesty*.
  **The core thesis survives:** no design removes the per-claim semantic judgment. Self-demarcation
  relocates the *structural* half to a deterministic gate and *narrows* the semantic half to a closed
  audit — it does not eliminate it.

### 2.4 The fork, stated for the maintainer to decide

| Option | Coverage gate | Contract blast radius | Delivers the literal ask? | Residual |
|---|---|---|---|---|
| **A — Advisory coverage** (initial, minus the utilization floor per §4.1) | none hard | zero | **No** — admitted open hole (unmarked hallucinations) | honest; no false-confidence claim |
| **B — Self-demarcation HARD gate, alone** | hard structural | `writer.md` + compose parse + §17 strip decision | **Yes** (on form) | gaming-writer false-confidence; framing-honesty unaudited |
| **C — The combination (RECOMMENDED)** | hard structural + semantic Review-1 audit + Layer-3 abstain | same as B | **Yes**, and narrows the residual | gaming-writer false-confidence, but the framing-honesty audit + abstain catch the aggregate case |

**The decision the maintainer must make:** adopt self-demarcation (Option C, my recommendation), or
stay advisory (Option A). I recommend **C**. I will not close it here.

### 2.5 If self-demarcation is NOT adopted

Option A stands as the honest fallback: the semantic layer at Review-1 (advisory) + Layer-3 abstain,
with **no** hard coverage gate and the open hole stated plainly. In that world the utilization floor
is *not* resurrected as a hard gate (§4.1) — it is advisory-only or dropped. The maintainer should
know that Option A is a real retreat from the enforcement ask, chosen deliberately, not the strongest
feasible posture.

---

## 3. BLK-2 — Semantic-verifier feasibility + placement (fixing the initial's implicit Option-B)

**Verified:** `transport.py` is unambiguous — the only "model" available is a headless `claude -p`
subprocess on the Claude **subscription** (module doc L1-5; `DEFAULT_TIMEOUT_SECONDS = 20 min`,
L133). There is **no local NLI infrastructure.** Two consequences the initial did not price:

- **The reliability numbers do not transfer.** AutoAIS system-level r=0.96 (research S2) and
  FActScore <2% aggregate error (S7) were measured on a **dedicated fine-tuned NLI model (TRUE /
  T5-11B, S11)**. A general `claude -p` subprocess judging *this pipeline's own* output is
  SelfCheckGPT-adjacent (S6, which the research itself calls weaker than source-NLI when a pool
  exists) and reflexive-bias-prone. **The aggregate reliability of the available engine on this task
  is UNMEASURED and must not be assumed 0.96.** The initial's "aggregate use is exactly the regime
  the verifiers are validated for" rests on an engine not in the system.
- **A pre-persist per-leaf verifier doubles-to-sextuples the compose hot path.** Wired into the
  bounded re-ask (`DEFAULT_MAX_ATTEMPTS=3`, `compose.py:113`), writer→verifier→(re-ask→verifier)… is
  up to six `claude -p` invocations per leaf, each a 20-min-timeout, rate-limit-backpressure surface.

**Verified free alternative:** Review 1 is **already** an LLM call (`run_artifact_review` on
`invoke_headless`) whose `ARTIFACT_CHECKS` already includes `grounding` / `extracted_floor` /
`citability` (`review.py:142-148`). So an aggregate groundedness / framing-honesty score is a
**refinement of an existing advisory check — no new call.**

**Ruling (fixing the initial's implicit Option-B choice):**
- **Default = Option A: place the semantic layer at Review-1.** Advisory, post-compose, one existing
  call, no hot-path doubling. Advisory tolerates the unmeasured engine reliability by construction.
  The framing-honesty audit (§2.2) and span↔fact entailment both live here; the aggregate score feeds
  the Layer-3 abstain lever (§7). This is where the combined posture's *semantic half* lives.
- **Option B (a new pre-persist per-leaf `claude -p` verifier) is an opt-in escalation only** —
  justified *only if* repair-before-persist proves worth the throughput/backpressure hit *and only
  after* the `claude -p`-as-verifier aggregate reliability is measured on this pipeline. It is not the
  v1 default. Note the combined posture does **not** need Option B: the *hard* coverage gate is
  self-demarcation's deterministic compose check (no LLM); the semantic work is advisory at Review-1.

This keeps the design's "single re-ask point" (`compose.py:11`) intact for the deterministic gate and
does not import an unmeasured per-claim signal into any hard block.

---

## 4. The two cross-DR blockers, resolved

### 4.1 X1 — the `[@key]` store conflation + the scenario-2 CSL collision

**Verified:** the initial's load-bearing SF-3 absorption ("`extract_fact_refs` must recognize `[@key]`
and bind BOTH to the ledger by the same rule … one binding check") does not hold as written.
- `[@key]` binds to **DR-5's CSL-JSON `references` bibliography** (a bibliography threaded into
  AST-`meta`), not to the RI3 grounding **ledger** (fact-ids). `TOP_LEVEL_KEYS` (`ir.py:139-141`)
  has **no `references`** — the channel is designed-but-**paused** (DR-5). No mapping between CSL keys
  and ledger fact-ids exists in either design. "One binding check" presumes a unification nobody
  specified, over a channel not yet in the envelope.
- **The scenario-2 collision is real.** DR-5's CSL renders `[@smith2020]` as "(Smith 2020)" — a
  **direct** bibliographic cite to the out-of-pool primary B. But DR-6 requires attribution to the
  **pool secondary S**. CSL cites B; it cannot say "according to pool source S." So a scenario-2
  `[@key]` styled by CSL would assert a direct cite to a source the pool does not hold — the exact
  over-reach DR-6 exists to prevent.

**Resolution — decouple the binding; keep the channel-agnostic *principle*; defer the `[@key]`
absorption until DR-5 lands:**
1. **Keep the surviving principle:** grounding is one property of every compose leaf, checked at one
   chokepoint, regardless of which feature produced the leaf. That principle stands (the adversarial
   could not break it). **Only its `[@key]` *binding* fails.**
2. **Do not couple DR-6 to a paused, elsewhere-pointing channel.** DR-6's enforcement binds to the
   **ledger** (fact-ids), which exists today. The `[@key]`/`references` channel is DR-5's and is
   paused; DR-6 must **not** make its correctness gate depend on it.
3. **When DR-5 lands, the bridge is a DR-5↔DR-6 contract, specified then, not now:** a `[@key]` that
   is a *grounding* citation must resolve to a ledger fact (scenario 1 or 2); a scenario-2 `[@key]`
   requires a **ledger attestation** (whose `primary` = B) **and** an attribution surface that names
   **S** (per §5.2's survivability rule) — which CSL-citing-B alone does not provide. That is a
   genuine new coupling (every scenario-2 grounding-`[@key]` ⇒ a ledger attestation + a non-CSL-alone
   attribution surface). It is **DR-5's design surface to ratify when DR-5 resumes**, flagged here as
   a hard constraint DR-5 must satisfy, not a binding DR-6 asserts now. Purely-bibliographic `[@key]`
   (citing the literature for *rhetorical* context, asserting nothing as pipeline fact) is out of
   DR-6's scope entirely — DR-6 gates *published-as-fact* claims, not every reference.

Net: the principle survives; the `[@key]` binding is deferred to DR-5's resumption with a named
constraint; DR-6 ships bound to the ledger it already has.

### 4.2 X2 — the DR-4 hard-section × DR-6 hard-grounding "deadlock"

**Verified:** DR-4 is ratified with the maintainer's **HARD structural guarantee** (`known-issues.md`
DR-4, 2026-07-17): per-venue required/forbidden sections **BLOCK** at a reconcile structural gate + a
base structural gate at compose/Review-1. DR-6 wants required content grounded. A required section
whose topic has no groundable facts appears jointly unsatisfiable.

**Resolution — it is a *false* deadlock; both gates' failure resolves to the SAME action, and
precedence is already fixed by the framework-invariant hierarchy:**
1. **DR-4 section-existence is satisfiable by legitimate framing.** DR-4 conformance is *structural*
   (the section exists and is well-typed), not "the section contains N grounded assertions." A
   required section with no available facts can be satisfied by legitimate *framing* prose (which,
   under self-demarcation, is honestly `.framing`-marked and grounds nothing — and is *fine*: framing
   is not a grounding violation). So in the common case there is **no** deadlock: DR-4 is satisfied by
   framing, DR-6 has nothing to gate (no factual assertions), and the artifact ships.
2. **The narrow true conflict** is only when a DR-4 constraint *additionally demands grounded
   substance* in a section for which no grounding exists. Here the precedence is unambiguous:
   **the §6.5 EXTRACTED publish floor is a framework invariant "outside user config … no run and no
   override can relax it"** (`design.md:465-468`), whereas a DR-4 required-section-with-grounded-
   substance constraint is user/venue config. **The grounding floor wins: the item blocks-and-reports**
   — it is never satisfied by ungrounded fabrication. This is exactly the §6.4 empty-pool posture
   ("block and report … names the offending clause," `design.md:445-451`) extended to name *both*
   constraints ("required section X demands grounded substance but has no groundable facts").
3. **Surface it at the earliest gate, not as a two-gate ping-pong.** A required-and-ungroundable
   section is detectable at resolve/compose time (the section's span/pool is empty). Block there with
   a combined DR-4×DR-6 code, so the maintainer sees "required section X has no groundable facts"
   rather than a confusing double-block. Neither hard gate "yields"; the honest outcome — the item
   does not ship — is what *both* gates independently want, so there is no contradiction to resolve.

### 4.3 A note on the resolver (Finding 5) that also lands X2/X1 cleanly

The ledger is already **per-(fact, instance)**: "Corroborated facts from two instances are two ledger
entries (each separately citable, per its own commit) — the ledger is per (fact, instance)"
(`compose.py:59-63`), and the resolver "union[s] grounding, keep[s] each fact's originating instance"
(`design.md:433`). This is the key that dissolves several apparent problems — see §5.4.

---

## 5. The should-fixes, resolved

### 5.1 Finding 3 — the utilization floor: DROP as a hard gate (accepted)

**Accepted in full.** The initial's Layer-1 utilization floor ("if the ledger holds ≥1 publishable
fact, the body must carry ≥1 grounding reference") is both **theater against the real hole** (the
initial itself admits the writer can "cite `f0` once and emit ten unmarked hallucinated sentences")
**and not false-reject-safe** — the exact "safe in practice" hand-wave the initial (correctly)
refuses for the sentence-coverage gate. A legitimately framing-heavy artifact (a reaction/hot-take
goal for which the resolver *made* facts available but the piece stays rhetorical) is false-rejected,
because facts being *resolved* does not oblige the artifact to *assert* them. That is the worst
quadrant: teeth-less against the hole, not-quite-safe against legitimate framing.

**Ruling:**
- **If self-demarcation is adopted (Option C):** the utilization floor is **superseded and dropped** —
  the structural no-bare-declarative gate is strictly stronger and does the real work.
- **If not (Option A):** the utilization floor is **advisory-only** (a Review-1 signal), and honestly
  labeled as gating **"grounding was used at all," not "content is covered."** It is never a hard gate
  under any option. This removes the double standard the adversarial identified.

### 5.2 Finding 4 + X4 — the attributed-only ruling: SOFTEN to attributability, with a survivability constraint (accepted)

**Accepted, and reconciled with X4 (which the initial only half-saw).**

The initial's "scenario-2 publishes ONLY as attributed prose, never a citation, never bare fact"
over-reads AIS (AIS's "According to P, s" is a *hearer/attributability test*, not a mandate that the
surface literally say "According to"), reaches into DR-5's surface domain (ruling *prose, not
citation* is a *how*, which the initial's own boundary assigns to DR-5), and ignores corroboration
(`design.md:461-462`: independent confirmation upgrades confidence — a widely-attested secondary fact
need not carry clunky per-instance "According to S").

**But X4 is also correct and load-bearing, and I verified it:** the §17 strip filter is **fail-closed**
and strips provenance Attr (`data-*`, tier classes) for every non-`SAFE_WRITERS` writer
(`design.md:1580-1589`; the publish-web / HTML/EPUB/slide family). So a scenario-2 attribution that
lives **only** in the ledger or **only** in a strippable provenance Attr **does not survive to
external publish** on those writers — the actor would publish bare "X." Prose survives; a provenance-
Attr citation does not. This is why the initial forced prose. If we naively relax to "let DR-5 style
it as a citation," we can reopen the bare-fact leak.

**The reconciled ruling — separate the *obligation* (DR-6) from the *surface* (DR-5), and add a
channel-agnostic survivability constraint that dictates a property, not a style:**
- **DR-6 owns the obligation (HARD):** a scenario-2 claim requires **attributability** — a recorded,
  resolvable attribution to the pool secondary **S** must exist (the ledger `attestation`, §6) **and
  be surfaced within the artifact's constraints** such that the published bytes for the target writer
  carry an attribution that (a) **names/points to S** (not merely cites the out-of-pool B) and (b)
  **survives the §17 strip for that writer.**
- **DR-5 owns the surface (style):** *how* that attribution is realized — prose ("According to S…"), a
  CSL "as cited in S" indirect-citation form, an author-in-text + citation, etc. — is DR-5's, subject
  to the two properties above. DR-6 does **not** mandate prose; it mandates *a surviving attribution to
  S*. Prose is the trivial satisfier; a bare provenance-Attr citation fails (b) on publish-web; a CSL
  cite of B alone fails (a).
- **v1 realization (DR-5 paused):** with no `references` channel in the envelope yet, the only surface
  that satisfies both properties today is **prose**. So *in v1* the attribution is prose — **not
  because DR-6 dictates prose**, but because it is the only channel that exists and survives. When
  DR-5 lands, it may add a surviving citation surface that names S; DR-6's constraint is unchanged.
- **Corroboration (§6.5) relaxes the *floor*, not the *obligation*:** a claim with an in-pool primary
  entry is scenario 1 and publishes plainly (§5.4). Corroboration across secondary attestations
  strengthens confidence but does not turn a scenario-2 attestation into an in-pool primary — the
  attribution obligation stands for a claim grounded *only* by attestation.

This keeps the hard obligation (an attribution to S must exist and survive), removes the DR-5 boundary
invasion (surface is DR-5's), resolves X4 (the survivability property is explicit and channel-agnostic),
and does not reopen the leak (any DR-5 surface must satisfy survive-and-name-S).

### 5.3 X3 — scenario-2 attribution is HARD at compose but SOFT at reconcile (resolved: honest split)

**Verified:** reconcile is an LLM rewrite whose only *hard* gate on its output is the terminal
hard-limit gate (RI5); fidelity (voice, meaning, provenance re-anchor) is checked by **advisory
Review 2** (`review.py:22-26`, §19). So "never dropped to bare fact" at reconcile has **no hard
enforcement**: a `truncate`/`adapt` to a tight platform limit that silently drops "According to S"
while keeping the claim ships bare "X," caught only advisorily. The initial's §5 "the item blocks if
it can't carry the attribution" named no reconcile mechanism.

**Why this cannot be cleanly hard-gated at reconcile without self-demarcation:** the hazard is
specifically *drop the attribution while keeping the claim*. A reference-preservation hard check ("the
attestation fact-id must survive reconcile") would **false-reject** a legitimate `truncate` that drops
the whole claim (which is fine — a dropped claim needs no attribution). So the conditional "IF the
claim survives, its attribution must survive" is itself the semantic coverage problem, one layer down.

**Ruling (honest, and it further motivates self-demarcation):**
- **Without self-demarcation:** the scenario-2 attribution obligation is **HARD at compose** (the
  ledger flags it; the attribution must be present pre-persist) and **ADVISORY at reconcile**
  (Review 2 flags a `truncate` that stripped it). **I state this plainly rather than pretend
  otherwise:** the reconcile layer re-opens the hole advisorily, exactly as the adversarial charged.
  The §16 RI3-fidelity constraint is *extended* to require reconcile to preserve the `attestation`
  fields + the attribution, but its *enforcement* at reconcile is advisory Review-2, not a hard gate.
- **With self-demarcation (Option C):** the attribution rides a structural span, so the **same
  deterministic no-bare-declarative completeness check re-runs on the fitted body at reconcile** — a
  `truncate` that strips the attribution span but keeps the claim span leaves a bare declarative claim
  (or a claim span whose required attribution span is gone), which the structural re-check catches
  **HARD**. This closes the reconcile hole deterministically. It is a further, concrete reason the
  combination is stronger — the same gate does double duty at compose and reconcile.

### 5.4 Finding 5 — the scenario binary under-models a union fact (resolved via the existing per-(fact,instance) ledger)

**Accepted, and it resolves more cleanly than the adversarial proposed — no new construct.** The
adversarial's two offered fixes were "resolver precedence" or "attestation per-contributing-source."
**The ledger is already per-(fact, instance)** (`compose.py:59-63`): a claim corroborated by two
instances is *two ledger entries*. So attestation is **per ledger entry (per contributing source) by
construction**, not per conceptual claim:
- An **in-pool primary** contributing source → a scenario-1 entry (no `attestation`) → publishable as
  bare fact.
- A **secondary pool source that quotes the out-of-pool primary** → a scenario-2 entry (`attestation`
  present) → publishable only as attributed-to-S (§5.2).
- The same conceptual claim grounded **both** ways is simply **two entries**; the binary is per-entry
  and never ambiguous.

**Resolver precedence:** when both entries exist for one conceptual claim, the **in-pool primary entry
wins for publish-as-fact** (the claim may be stated plainly via the scenario-1 entry; the scenario-2
entry is supplementary corroboration, feeding `corroboration`, `design.md:461`). The writer binds the
scenario-1 entry and states the claim plainly; the attestation is provenance, not an attribution
obligation, because an in-pool primary grounds the bare proposition. This matches the existing
"union grounding, keep each fact's originating instance" resolver walk (`design.md:433`) with zero new
representation. The initial's §3.4 two-scenario closure was stated at the wrong granularity (per
conceptual claim); at the ledger's real granularity (per fact-instance entry) it is already closed.

### 5.5 Finding 7 — the `ir_version` / immutability wrinkle (relocated, horn picked, owned here)

**Verified both of the adversarial's corrections:**
- **Mislocated:** the GAP-1 re-render path (`driver.py:753`) unwraps the stored IR via
  `ir.unwrap_ir(stored)` and reads `binding` **directly — it never calls `validate_ir`**, so it is
  immune to an `ir_version` bump. The path that DOES re-validate a stored canonical IR is
  **reconcile** (`reconcile.py:713`, `ir.validate_ir(request.canonical_ir)`) — the RI11
  "new platform/language → re-reconcile" tier. The initial pointed at the safe path and missed the
  exposed one.
- **The pin is exact-equality:** `validate_ir` requires `doc["ir_version"] == IR_VERSION`
  (`ir.py:687-690`; `IR_VERSION = 1`, `ir.py:108`). Bump to 2 and every pre-DR-6 stored IR **fails
  re-reconcile**, breaking RI10's "re-targeting is always one re-reconcile away," with **no migration
  path** (MIG-7: artifacts are immutable, never rewritten; `ir_version` is "a provenance stamp, not a
  migration target").

The two horns: **don't-bump** (two different ledger schemas share `ir_version=1` → the stamp stops
identifying the schema generation for a reproducibility-first immutable artifact — *the stamp lies*)
vs **bump** (the stamp stays honest but exact-equality strands every old IR from re-reconcile).

**Ruling (owned here — this is an IR-schema-governance design change, not a planner footnote):**
**Bump `ir_version` to 2 AND relax the exact-equality pin to a known-compatible-set check** at the
re-validation sites. The build path continues to *stamp* the current `IR_VERSION` (honest stamp); the
*validate* path accepts any `ir_version` in a declared set of schema generations this code understands
and can read. This is sound precisely because the DR-6 extension is **additive-optional** (the ledger
moves from the exact-match `keys == set(LEDGER_FIELDS)`, `ir.py:508-513`, to the parts-pattern
`LEDGER_REQUIRED` + `LEDGER_OPTIONAL`, copying `_PART_REQUIRED`+`_PART_OPTIONAL`, `ir.py:573-575`): a
v1 IR (no `attestation`) validates cleanly under the v2 schema (attestation optional), and a v2 IR
validates too. So an old IR re-reconciles, and the stamp still tells the truth about which generation
minted it.

**Blast radius of the governance change (stated honestly):** relaxing the pin means `validate_ir`
becomes a *multi-generation reader* rather than a single-generation equality check. That is the
*correct* posture for an immutable-no-migration store that must still re-reconcile old artifacts — but
it does mean the exact membership of the "known-compatible set," and the rule that only
*additive-optional* changes may share read-compatibility (a breaking change must gate, not silently
read), become a small standing governance contract. The **direction** is decided here (bump + relax to
a known-compatible set, additive-optional only); the *enumeration mechanics* (the set constant, the
compatibility predicate) are the planner's to implement against this ruling. This is the answer to
"can the IR ledger schema evolve at all under immutability + exact-pin?" — **yes, additively, by
making validation generation-tolerant.**

---

## 6. The minors

### 6.1 X5 — `require: primariness == primary` eliminates scenario 2 at the pool boundary

**Noted as a real interaction, not a defect.** A recipe clause `require: primariness == primary`
(`design.md:397`) filters secondary sources out of the pool at instance-scope, so the pool sources
that *carry* scenario-2 attestations never reach compose — scenario-2 enforcement is then structurally
unreachable. `primariness`-the-score (in `require`) and scenario-the-axis are orthogonal *fields* but
they **interact at the pool boundary**: scenario-2 enforcement presupposes the selection grammar
admits the secondary sources. **Consequence for the maintainer/recipe author:** a goal like "cite the
broader literature via secondary attestation" (the academic case DR-6 invokes) is in direct tension
with a `primaries only` require clause — the two must not be combined. This is a natural property of
orthogonal-but-interacting selection, worth documenting in the recipe guidance, not a design flaw. No
change to the DR-6 mechanism.

### 6.2 X6 — the Layer-3 warn-vs-block lever needs a concrete home

**Placed concretely.** The warn-vs-block abstain lever is a **policy** (an enforcement-posture choice),
not a byte-determining input — like `on_conflict` (an existing recipe-level resolver policy,
`design.md:397-399`) and unlike an identity component. Home it as a **recipe/workspace-scoped policy
field** (e.g. `grounding_posture: warn | block`, framework default `warn`), resolved through the
existing **M3 config cascade** — *not* a new cascade rung (that would be over-engineering), *not* a
schema attribute on any registry entry, *not* an identity input. It is **provenance-aware** (a
`provenance: framework` default of `warn`; an instance may override to `block` for high-assurance
content), which the existing config-cascade + provenance guard already support. This keeps
one-file-extensibility and leaves identity untouched (the lever changes *whether an item blocks*, not
*what bytes identical inputs produce* — exactly the `side`-like exclusion, `design.md:1638`). The
block, when it fires, surfaces as a DR-6 grounding code in run `results`, mirroring
`empty-pool`/`hard-limit-exceeded` (§21.7).

---

## 7. What is kept (the adversarial could not break these — not re-opened)

- **ZERO new identity surface.** Re-verified: the artifact-id preimage is
  `{dimensions, goals, source-subset, source-commit}` (`ids.py` / `build_artifact_preimage`) and the
  RI4 binding digest is `digest_full(preimage)` over that preimage only
  (`ir.py:_validate_binding`, L656-665). **The grounding ledger is in neither**, so the scenario-2
  `attestation` extension changes neither the artifact-id nor the binding digest — it is a
  provenance-layer change, matching DR-4/DR-5's zero-identity landings.
- **The core thesis: a *perfect* semantic coverage hard gate is unachievable.** It survives even
  self-demarcation — which hard-gates *form*, not *grounding-honesty*; the semantic half (did the
  writer label honestly?) stays noisy. The initial was right that no design removes the per-claim
  judgment; it was wrong only that this forces *advisory* rather than *a hard structural gate plus a
  narrowed semantic audit* (§2).
- **Scenario as the THIRD axis** — a pool-relation axis orthogonal to the confidence tier, to
  `traceability`, and to the `primariness` *score*. PROV-O-backed (`wasQuotedFrom`, research S10). The
  ONE optional PROV-O-shaped `attestation? {primary, anchor, relation}` ledger sub-structure stands,
  modeled as `LEDGER_REQUIRED` + `LEDGER_OPTIONAL` so scenario-1 ledgers are byte-unchanged. `primary`
  is a citation descriptor (never a `source_instance_id` — B is not in the pool); `anchor` points into
  the **held pool source** (what makes the attestation itself checkable); `relation` is PROV-O
  vocabulary.
- **Channel-agnostic grounding as a PRINCIPLE** — "grounding is one property of every compose leaf,
  checked at one chokepoint." Only the `[@key]` *binding* failed (X1, §4.1); the principle is kept and
  DR-6 binds to the ledger it already has.
- **The single-re-ask-point discipline** — feeding correction notes into the existing bounded re-ask
  (`compose.py:11`, "the ONLY re-ask point") rather than a new gate/loop. The deterministic
  self-demarcation gate rides this existing re-ask; the semantic layer rides Review-1 (§3), not a new
  loop.

---

## 8. Residual risks + the maintainer-gate items

### 8.1 The gate items, in decision order

1. **LEAD — adopt self-demarcation? (BLK-1, §2).** Option C (self-demarcation HARD structural coverage
   gate + semantic Review-1 audit + Layer-3 abstain) is **my recommendation** — it is the only posture
   that honestly answers the maintainer's "hard-gate coverage?" with "yes." Cost: a `writer.md`
   contract change (wrap all prose, with a structural-exemption tail for headings/lists/code/tables/
   math), one compose-time completeness check (needs block-level parsing — a new compose-time parse),
   and a §17 strip decision for `.framing` spans. Residual: a gaming/fallible writer can dress a
   hallucination as `.framing` → **false confidence with a hard-gate badge**, and the framing-honesty
   audit stays semantically noisy. **If the maintainer declines, the honest fallback is Option A
   (advisory coverage), which is a deliberate retreat from the ask — stated as such, not disguised.**
   *This decision is the maintainer's; I have not closed it.*

2. **SECOND LEAD — the Layer-3 warn-vs-block default (§6.2).** The abstain lever's *home* is settled (a
   recipe/workspace policy field on the M3 cascade, provenance-aware, non-identity). Its **default
   value is a values call**: framework default `warn-and-ship` (a per-claim-noisy aggregate signal
   should not unconditionally veto a possibly-good artifact) vs `block` (safe-by-default for
   high-assurance instances). **I recommend `warn` as the framework default with a documented
   `block` override** — but the maintainer may prefer `block` as the safe default. Flagged, not closed.

3. **X1 bridge, when DR-5 resumes (§4.1).** Ratify the scenario-2 `[@key]` contract *inside DR-5*:
   a grounding `[@key]` must resolve to a ledger fact; a scenario-2 one requires a ledger attestation
   + an attribution surface that names S and survives the strip. Deferred to DR-5, named as a hard
   constraint DR-5 must satisfy.

4. **`ir_version` governance enumeration (§5.5).** The direction is decided (bump to 2 + relax
   validate to a known-compatible set, additive-optional only). The planner implements the set
   constant + the compatibility predicate against this ruling; the maintainer should acknowledge that
   `validate_ir` becoming a multi-generation reader is an intentional governance shift.

5. **Option B measurement, if ever pursued (§3).** A pre-persist per-leaf `claude -p` verifier is
   off-by-default; pursuing it requires first measuring `claude -p`-as-verifier aggregate reliability
   on this pipeline. Not a v1 item.

### 8.2 Residual risks carried, stated honestly

- **The framing-honesty hole (Option C):** self-demarcation's hard PASS certifies form, not
  grounding-honesty. A `.framing`-dressed hallucination passes the hard gate and is caught only by the
  advisory semantic audit + Layer-3 abstain (aggregate, noisy). The green light over-claims.
- **The reconcile advisory gap (Option A only, §5.3):** without self-demarcation, a reconcile
  `truncate` that strips "According to S" while keeping the claim is caught only by advisory Review 2.
  Option C closes this deterministically; Option A leaves it advisory — stated, not hidden.
- **The self-demarcation exemption tail (Option C, §2.3):** the "what is bare declarative prose"
  boundary (headings, lists, code, tables, math) is a real design surface; over-exempting opens a
  hole, under-exempting false-rejects. Deterministic but not trivial.
- **The unmeasured verifier engine (§3):** the semantic layer's aggregate reliability on `claude -p`
  is unknown; it is used only advisorily, which tolerates that — but no hard block may lean on it.
- **The X5 pool-boundary tension (§6.1):** a `primaries only` recipe silently makes scenario-2
  enforcement unreachable; a documentation/guidance risk, not a mechanism defect.

### 8.3 Blast radius, restated

DR-6 touches **compose, the ledger, and both reviews** — high, as the initial said, and coherent with
each existing invariant: the tier model and §6.5 floor are untouched (scenario is the orthogonal third
axis; the floor's *definition* is unchanged, only its *enforcement* is generalized); the compose
contract gate is *extended* at the same chokepoint (`validate_ir`/`_validate_refs`/`extract_fact_refs`)
with a new deterministic coverage check under Option C; the bounded re-ask is reused (no new re-ask
point); Review 1 gains the semantic score (an existing check refined, no new call); Review 2 + the §16
fidelity constraint gain the attestation/attribution obligation (advisory at reconcile under Option A,
deterministic-at-reconcile under Option C). **Zero new identity surface** throughout.

---

## 9. One-line summary

Re-open the maintainer's own hard-vs-advisory fork as the lead gate and **recommend the combination**
— writer self-demarcation as a HARD deterministic *structural coverage* gate at compose (answering
"yes, hard-gate coverage") **combined** with the semantic *framing-honesty + faithfulness* audit
placed at **Review-1** (free — Review 1 is already an LLM call; the reliability numbers do not
transfer to `claude -p`, so it stays advisory) and a policy-gated Layer-3 item-level abstain — while
being honest that self-demarcation certifies *form, not grounding-honesty* and the adoption is the
maintainer's call; drop the utilization floor; soften scenario-2 to **attributability** with a
channel-agnostic *survivability* constraint (attribution to pool source S must exist and survive the
§17 strip; surface form is DR-5's); model attestation **per-(fact,instance) ledger entry** (already
the ledger's granularity), in-pool primary winning for publish-as-fact; defer the `[@key]` binding to
DR-5's resumption (keep only the principle); resolve the DR-4×DR-6 "deadlock" as a block-and-report
where the §6.5 framework floor takes precedence; and evolve `ir_version` by **bump + generation-
tolerant validation** (additive-optional) so old IRs still re-reconcile — ZERO new identity surface.
