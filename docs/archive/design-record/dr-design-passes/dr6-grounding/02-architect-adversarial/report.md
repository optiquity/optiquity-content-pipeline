# DR-6 — General grounding enforcement — ARCHITECT (mode: ADVERSARIAL)

**Pass:** ops-architect, adversarial attack on the stage-01 INITIAL design for DR-6.
**Posture:** assume the initial is wrong; a surviving finding beats agreement. Whole-picture mandate:
attack local DR-6 AND its fit with the tier model, §6.5, the compose contract + bounded re-ask,
Review 1/2, the ledger, the internal↔external split, and the ratified DR-2..DR-5 it claims to absorb.
**Method:** every load-bearing claim in the initial re-verified against `docs/design.md` and the code
(`pipeline/{ir,compose,review,reconcile,driver,transport,grounding,ids}.py`, `pipeline/prompts/writer.md`).
Read-only. No plan, no code.

---

## 0. What I verified before attacking (so the reconciliation can trust the base)

**Confirmed correct in the initial:**
- The gap is real and located exactly where the initial says. `_validate_refs` (`ir.py:543`) iterates
  only the refs `extract_fact_refs` (`ir.py:380`) *finds*; a zero-`data-fact` body yields `[]` and
  `_validate_refs([])` is a no-op. Unmarked assertion passes. (`ir.py:620`, `ir.py:714`.)
- **ZERO new identity surface — TRUE, could not break it.** Preimage = `{dimensions, goals,
  source-subset, source-commit}` (`ids.py` module doc L37-42; `build_artifact_preimage`); the RI4
  binding digest is `digest_full(preimage)` over that preimage only (`ir.py:_validate_binding`). The
  ledger is in neither. Adding `attestation` to the ledger touches neither the artifact-id nor the
  binding digest. This landing is solid.
- The closed-exact ledger schema is `keys == set(LEDGER_FIELDS)` (`ir.py:509-513`); parts already model
  `_PART_REQUIRED`+`_PART_OPTIONAL` (`ir.py:573-575`). The "copy the parts pattern" recommendation is
  mechanically sound.
- Review 1 is advisory: `VERDICTS = ("pass","concerns")`, `CHECK_STATUSES=("pass","concern")`
  (`review.py:161-164`), docstring "never *enforces* the floor" (`review.py:19`).

**One correction to the initial's OWN diagnosis (it matters for §8):** the initial says the `ir_version`
wrinkle lives on "the re-render/`unwrap_ir` read path." **It does not.** The GAP-1 re-render path
(`driver.py:753`) unwraps the stored IR and reads `binding` directly — **it never calls `validate_ir`**,
so it is immune to an `ir_version` bump. The path that DOES re-validate a stored canonical IR is
**reconcile** (`reconcile.py:713`, `ir.validate_ir(request.canonical_ir)`). The initial pointed at the
safe path and missed the exposed one (see Finding 7).

---

## 1. BLOCKER — The writer self-demarcation rejection is a retreat from the maintainer's explicit enforcement ask, and it was decided unilaterally in a footnote

This is the most important finding. The maintainer's DR-6 question (known-issues DR-6) is literally
"should compose **HARD-gate** this at compose time … or keep the current advisory §19-review posture?"
The initial's answer for the coverage direction is **advisory + bounded-repair, hard only by opt-in**
(§2.3/§2.4). That is *the current posture plus a repair loop* — a **retreat to advisory**, not the
enforcement the maintainer asked whether to adopt. The ONE design that answers "yes, hard-gate coverage"
— writer self-demarcation (every sentence in either a `data-fact` span or an explicit `.framing` span,
so compose can structurally reject bare declarative prose) — the initial itself calls "the maintainer's
likely mental model of 'structural'" and "the ONE path to a structural coverage hard gate," then buries
it in §7 "considered and rejected." **A fork this central to the maintainer's question cannot be closed
by the architect in a rejected-alternatives bullet.** It must go back to the maintainer. Below, argued
both ways so reconciliation can present the strongest case for each.

### The initial's three rejection grounds do not hold up as stated

**(a) "relocates the semantic judgment to a self-interested writer that can mark a hallucination
`.framing` to evade."** This cuts the *other* way on two counts:

- *The accepted design is evadable by the same writer, more silently.* The initial admits (§2.2) the
  writer "can satisfy utilization (cite `f0` once) and then emit ten unmarked hallucinated sentences" —
  Layer 1 cannot catch them. So the accepted design's evasion is a **silent omission** (no span), which
  forces the semantic verifier to first *segment prose and decide de novo which unmarked sentences are
  assertions* — the hard, open-ended problem. Self-demarcation's evasion requires an **affirmative
  mislabel** (`.framing` on a factual sentence), which is a **bounded, closed** check ("is this
  writer-declared framing span actually factual?") — strictly easier for the verifier. Self-demarcation
  makes the semantic layer's job *smaller*, not larger.
- *The threat model is wrong.* The writer here is not adversarial — it is Claude-via-subscription
  (`transport.py`), cooperative-but-fallible. A cooperative writer that hallucinates does one of three
  things, and self-demarcation gates **all three**: (i) wraps it in a `data-fact` span with a made-up
  id → caught HARD (`ir-unknown-fact`, `ir.py:549`); (ii) binds a real id that doesn't support it →
  Layer-2 entailment; (iii) leaves it as bare prose → **caught by the structural no-bare-declarative
  gate → re-ask.** Under the accepted design, mode (iii) hits only *advisory* Layer 2. Self-demarcation
  genuinely closes more of the hole against the *actual* writer. The "self-interested evader" that
  grounds the rejection is a strawman for this pipeline.

**(b) "high blast radius — fights §15's pure-Markdown leaves, complicates the substance floor and the
AST Span model."** Overstated, verified against the code:
- A `.framing` span is the *same* Pandoc bracketed-span construct already in use; `extract_fact_refs`
  already ignores spans with no `data-fact` (`ir.py:398-399`), and the substance floor already strips
  bracketed-span attr blocks and counts visible text (`ir.py` `_has_substance`, §15). Both surfaces
  **already support** a `.framing` span. Self-demarcation adds a *requirement* (no bare declarative text
  between spans), not a new *construct*. The real blast radius is the **writer contract** (`writer.md`)
  plus one new compose-time completeness check plus deciding how the §17 provenance-strip filter treats
  a `.framing` span on publish writers — **moderate and localized**, not the re-architecture the initial
  implies.

**(c) "certifies structure, not grounding."** True — and it is *exactly what the maintainer named as
"structural."* The initial concedes this in the same bullet. Rejecting the maintainer's own construction
of "structural" in favor of a weaker floor (the utilization floor, Finding 3) that the initial admits
"cannot close" the hole is the inversion this finding is about.

### The honest steelman FOR the initial's rejection (so the maintainer sees both edges)

- Self-demarcation does **not** escape the semantic-noise problem; it *relocates the structural half*
  and leaves the semantic half (did the writer label honestly?) exactly as noisy. So the initial's core
  thesis — coverage is half-structural, half-semantic — **survives**: self-demarcation buys a hard gate
  on *form*, not on *grounding*.
- A hard PASS carries authority. A self-labeling gate that a fallible writer games (a smuggled assertion
  dressed as `.framing`) yields **false confidence with a hard-gate badge** — arguably worse than an
  advisory that flags a good artifact, because the green light says "coverage enforced" over a body it
  did not truly enforce. This is the same critique the initial (correctly) makes of the utilization
  floor; it applies to self-demarcation's *semantic* half too.
- Grey zone: a writer wrapping "experts widely agree X" as `.framing` — is that a grounding violation or
  legitimate rhetorical framing? The line is itself semantic.

### What reconciliation must answer
Put the real fork to the maintainer, not the architect's pre-emption:
1. **Self-demarcation** = a HARD structural coverage gate (no bare declarative prose), moderate
   writer-contract blast radius, delivers the literal ask, residual semantic audit (framing honesty)
   wired as advisory/repair; **false-confidence risk on a gaming writer.**
2. **The initial's advisory-coverage + utilization floor** = no contract churn, no false-confidence
   claim, **admitted open hole** (unmarked hallucinations).
And note the option the initial never considered: **combine them** — self-demarcation as the structural
gate + the semantic verifier as the framing-honesty audit + Layer-3 abstain. That is strictly stronger
than the utilization floor and honors the maintainer's ask. The either/or framing was a false choice.

---

## 2. BLOCKER — Layer 2 as a pre-persist per-leaf semantic verifier is not viable on this transport, and imports reliability numbers from an engine the pipeline does not have

The initial (§2.3) commits the semantic verifier to run **pre-persist, over every compose leaf, feeding
the existing re-ask.** It waves engine/cost to §8 as "operational/planner." That wave hides a
design-viability blocker.

**There is no local model infrastructure.** `transport.py` (L1-5, 19-22) is unambiguous: "the pipeline
is a headless Claude Code CLI invocation authenticated on the Claude SUBSCRIPTION … one synchronous
invocation per verb," `DEFAULT_TIMEOUT_SECONDS = 20 min` (`transport.py:133`), subject to
`rate-limit-backpressure` (§22.5). **The only "model" available is another `claude -p` subprocess.**
Consequences the initial did not price:

- **The NLI reliability guarantee does not transfer.** The numbers the initial leans on — AutoAIS
  system-level r=0.96 (S2), FActScore <2% aggregate error (S7) — were measured on a **dedicated
  fine-tuned NLI model (TRUE / T5-11B**, research S11). This pipeline has no such model. Substituting a
  general `claude -p` subprocess judging *its own* pipeline's output is **SelfCheckGPT territory** (S6,
  which the research itself calls "weaker than source-NLI when a pool exists") and is reflexive-bias
  prone. The initial's entire "aggregate use is exactly the regime the verifiers are validated for"
  justification rests on an engine that is **not in the system**. The aggregate reliability of the
  available engine on this task is **unmeasured** — it cannot be assumed 0.96.
- **The compose hot path is doubled, or worse.** A per-leaf pre-persist verifier is a *second* `claude
  -p` per leaf. Wired into the bounded re-ask (`DEFAULT_MAX_ATTEMPTS=3`, `compose.py:113`), the loop
  becomes writer→verifier→(re-ask writer→verifier)… — up to **six subprocess invocations per leaf**,
  each with a 20-min timeout and each a rate-limit-backpressure surface. On a subscription this is a real
  throughput/backpressure hazard, not a footnote.
- **Review 1 is ALREADY an LLM call with a `grounding` check.** `run_artifact_review` rides
  `invoke_headless` (`review.py:627`) and `ARTIFACT_CHECKS` already includes `grounding` /
  `extracted_floor` / `citability` (`review.py:142-147`). So "an aggregate groundedness score on Review
  1" is **refining an existing advisory check for free** — no new call. The **only** new cost is the
  *compose-time pre-persist* placement, and that is precisely the part the initial under-justified.

**Why this is design, not planning:** *where* the semantic layer runs changes the design's cost, its
"no new re-ask source" claim, and the pre-persist-vs-post-persist boundary. The initial already
*committed* to the expensive placement (§2.3). Reconciliation must decide, as a design question:

- **Option A (cheap):** semantic groundedness is **Review-1-only** (fold into the existing grounding
  check; post-compose; advisory; one existing call). No compose hot-path doubling. Loses the
  detect→revise-before-persist behavior — but the "revise" then happens on the *next* run, or via
  Review-1-fed re-ask if any, which the design already supports as advisory.
- **Option B (expensive):** a new pre-persist per-leaf verifier, doubling compose cost — justified ONLY
  if repair-before-persist is worth the throughput/backpressure hit, and ONLY after measuring the
  `claude -p`-as-verifier aggregate reliability on this pipeline (it is currently unknown).

The initial chose B implicitly and defended it with A-inapplicable numbers. That is the blocker.

---

## 3. SHOULD-FIX — The utilization floor is both theater AND not false-reject-safe (a double standard)

Layer-1 item 3: "if the ledger holds ≥1 publishable EXTRACTED fact, the body must carry ≥1 grounding
reference." The initial admits (§2.2) the writer can "cite `f0` once and then emit ten unmarked
hallucinated sentences." So as a *coverage* gate it is near-vacuous: any artifact genuinely built from
grounding trivially cites one fact, so the gate almost never bites the actual hole — while giving the
maintainer a "coverage is hard-gated" signal that gates only "≥1 citation exists."

Worse, the "false-reject-safe in practice (an artifact built from grounding uses grounding)" defense is
**an empirical hand-wave — the exact move the initial (correctly) refuses for the sentence-coverage
gate in §7** ("not false-reject-safe → why coverage cannot be fully hard"). A legitimately framing-heavy
artifact — a reaction/hot-take goal for which the resolver *made facts available* but the piece
legitimately stays rhetorical — would be **false-rejected**, because the floor keys off "publishable
facts were *resolved* for this item," and facts being resolved does not oblige the artifact to assert
them. So the floor is simultaneously **teeth-less against the real hole** and **not-quite-false-reject-
safe against a legitimate framing piece**. That is the worst quadrant. The double standard (reject
sentence-coverage for not being false-reject-safe; accept the utilization floor on "safe in practice")
should be resolved: either drop the floor as advisory-only, or state honestly that it gates
"grounding was used at all," not "content is covered."

---

## 4. SHOULD-FIX — "Publish ONLY as attributed prose, never bare fact" over-constrains, over-reads AIS, and reaches into DR-5's surface domain

The §3.3 ruling makes a scenario-2 claim publishable **only** as in-prose "According to S, B says X,"
**never** a citation, **never** bare. Directionally the maintainer did distinguish scenario 2 from
scenario 1 ("publishable as fact"), so *some* differential treatment is warranted. But the ruling is
over-specified on three axes:

- **It over-reads AIS.** AIS's "a generic hearer would affirm 'According to P, s'" (research §3a) is a
  **hearer/attributability test**, not a mandate that the surface literally say "According to." ALCE
  (research §3b, S3) operationalizes attribution as a **citation** + entailment — i.e. a *citation is*
  the attribution mechanism. The initial's insistence on **prose, never citation** contradicts the
  research's own model where a marker satisfies attributability.
- **It reaches into DR-5.** The initial's own boundary is "DR-6 owns *whether* attributed; DR-5 owns
  *how* styled" (§6.2). Ruling that attribution must be **prose and not a citation** *is a surface-form
  ruling* — it dictates the *how*, invading DR-5's domain. The boundary the initial draws, it then
  crosses.
- **It ignores corroboration.** The design has a `corroboration` score (§6.2) that "upgrades confidence
  … across genuinely independent instances." A claim attested by many independent pool sources is
  exactly the case §6.5's confidence pipeline strengthens — yet the ruling still forces clunky per-claim
  "According to S…" attribution. Real writing states widely-attested secondary-sourced facts plainly.

**Reconciliation target:** soften to "scenario 2 requires **attributability** — a recorded, resolvable
attribution to the pool source S must exist and be surfaced *within the artifact's constraints*; the
**surface form (prose vs citation) is DR-5's**, and corroboration may license more direct statement."
That keeps the hard obligation (an attribution must exist) without the over-reach (it must be prose) —
and it removes the DR-5 boundary violation.

---

## 5. SHOULD-FIX/MINOR — The scenario presence/absence binary under-models a fact grounded BOTH in-pool and by attestation

Scenario is encoded as `attestation` present (=2) / absent (=1). But the §6.3 resolver walk **unions
grounding across instances** ("union grounding, keep each fact's originating instance"). A single unioned
fact can be corroborated by an **in-pool primary AND** a secondary pool source that quotes the same
out-of-pool primary. Under the binary, recording `attestation` forces it to read as scenario-2
(attributed-only) even though the primary IS in-pool (publishable as bare fact); omitting it drops a
real attestation. The binary cannot represent "primary-in-pool *and* also-attested." Reconciliation must
either define resolver precedence (in-pool primary wins → scenario 1, attestation is supplementary
provenance) or make attestation **per-contributing-source**, not per-fact. The initial's two-scenario
closure (§3.4) does not address multi-source union facts.

---

## 6. WHOLE-PICTURE / CROSS-DR

### X1 — BLOCKER — The `[@key]` absorption conflates two different stores; scenario-2 CSL rendering collides with the attributed-only ruling
The initial's load-bearing SF-3 absorption (§4, Layer-1 item 2): "`extract_fact_refs` must recognize
`[@key]` … and bind BOTH to the ledger by the same rule … one reference model, one binding check." This
does not hold:
- **`[@key]` and `data-fact` resolve into different stores.** Per ratified DR-5 (known-issues DR-5),
  `[@key]` binds to a **CSL-JSON `references` block** (a bibliography, threaded into AST-`meta`), not to
  the grounding **ledger** (RI3). A `[@smith2020]` names a bibliography entry; a `data-fact="f3"` names a
  ledger fact-id. **There is no specified mapping** between CSL keys and ledger fact-ids. "One binding
  check" presumes a unification that neither DR-5 nor the initial provides. (Verified: the `references`
  block is **not even in the live IR envelope** — `TOP_LEVEL_KEYS`, `ir.py:139-141`, has no
  `references`; DR-5 is designed-but-paused. DR-6 is absorbing a channel that does not yet exist and,
  when it does, points elsewhere.)
- **Scenario-2 breaks the DR-5/DR-6 boundary the initial claims is clean.** For an academic scenario-2
  cite, DR-5's CSL renders `[@smith2020]` as "(Smith 2020)" — a **direct** bibliographic citation to the
  out-of-pool primary B. But DR-6's ruling (§3.3) requires attribution to the **pool secondary S**
  ("According to S, Smith says X"). **CSL cannot express "according to pool source S" — it cites B.** So
  DR-5's surface for a scenario-2 `[@key]` *asserts a direct cite to a source the pool does not hold* —
  exactly the over-reach DR-6 exists to prevent. The "DR-6 owns whether attributed, DR-5 owns how styled"
  split **fails on scenario 2**: what must be attributed (S-attests-B) is not stylable by the mechanism
  that renders the cite (CSL cites B). Reconciliation must resolve: does a scenario-2 `[@key]` require a
  ledger attestation whose `primary` = B and whose surface is forced to name S? If so, that is a strong
  new DR-5↔DR-6 coupling (every scenario-2 CSL key ⇒ a ledger attestation + a non-CSL attribution
  surface) that neither design ratified.

### X2 — BLOCKER/SHOULD-FIX — DR-6's HARD grounding gate can deadlock with DR-4's ratified HARD section-conformance gate
The initial's DR-3 absorption (§4) treats outline-demanded claims as "ordinary compose leaves … zero
outline-specific logic." That is a **stale view of DR-3.** Per ratified DR-4 (known-issues DR-4), the
maintainer chose the **HARD structural guarantee**: "per-venue required/forbidden sections **BLOCK** …
un-defers DR-3's machine-section-parse (the F1 sentinel grammar + F5 hard gate) … a reconcile structural
gate; plus a base structural gate at compose/Review-1." So there is now a **hard gate that a required
section must exist.** Compose a required section whose topic has **no groundable facts** (empty/relaxed
pool for that section, §6.4): DR-4 says the section MUST exist (block if absent); DR-6 says its content
MUST be grounded (block/abstain if ungrounded). **The two hard gates are jointly unsatisfiable** — a
forced-but-ungroundable section. The initial never surfaces this because it reasoned from the pre-DR-4
"ordinary leaf" model. Reconciliation must define precedence: does DR-4's required-section survive as an
*empty/abstained* section (violating DR-4's "must exist" content expectation), or does DR-6's grounding
gate yield? This interaction is unhandled and is a direct consequence of the two ratified HARD gates the
whole-picture mandate names.

### X3 — SHOULD-FIX — Scenario-2 attribution is HARD at compose but SOFT at reconcile; the §16 fidelity list gains a semantic obligation with no hard gate
The initial (§6/§5) extends the §16 RI3-fidelity constraint to "preserve the `attestation` fields + the
attribution (re-anchored, never dropped to bare fact)." But reconcile is an **LLM rewrite** whose only
*hard* gate is the terminal hard-limit gate (§16 RI5). Fidelity (voice, meaning, provenance re-anchor)
is checked by **advisory Review 2** (§19). So "never dropped to bare fact" is a **semantic** obligation
with **no hard enforcement at reconcile**: a `truncate`/`adapt` to a tight platform limit that silently
drops "According to S" and ships bare "X" is caught only by advisory Review 2 — **reopening the exact
DR-6 hole at the reconcile layer.** Scenario-2's "attributed-or-dropped" is hard at compose (the ledger
flags it) but soft at reconcile. The initial's §5 "the item blocks if it can't carry the attribution"
names no mechanism that blocks it. Reconciliation must state where the scenario-2 attribution obligation
is *enforced* post-reconcile, or accept it is advisory there and say so.

### X4 — SHOULD-FIX — The internal↔external strip makes "attribution as prose" load-bearing, and couples X1 to a bare-fact leak
The RI14 external payload (§17) **excludes** provenance/tier tags as publishable content, and the §17
provenance-strip filter (fail-closed) strips provenance Attr for publish writers. The grounding ledger
does **not** cross to the external actor. Therefore a scenario-2 attribution that lives only in the
ledger, or only in a strippable citation Attr, **does not survive to external publish** — the external
actor would publish bare "X." The initial's "attribution must be prose" choice (§4/§5) is what saves
this: prose survives into the body/AST/bytes. **But this couples directly to X1:** if reconciliation
relaxes to allow DR-5 *citation-form* attribution for scenario 2 (to fix the over-constraint in Finding
4 / the collision in X1), it **reopens the external bare-fact leak**, because the strip filter may remove
the citation on a publish writer. So the two knots are one: you cannot simultaneously (a) let DR-5 CSL
style scenario-2 attribution and (b) guarantee the external actor never publishes a scenario-2 claim as
bare fact — unless the attribution is forced into un-strippable content (prose) OR the strip filter is
taught to preserve scenario-2 attribution surfaces. This is the central cross-DR design knot and the
initial only half-saw it.

### X5 — MINOR — Scenario-2 availability is gated by §6.3 source selection; a "primaries only" recipe eliminates it
A recipe with `require: primariness == primary` (§6.3 — a natural "cite only primaries" policy) filters
secondary sources out of the pool at instance-scope, so the pool sources that *carry* scenario-2
attestations never reach compose. The initial treats scenario 2 as always available; in a `primaries
only` pool it is structurally unreachable, and a goal like "cite the broader literature via secondary
attestation" (the academic case DR-6 invokes) is in direct tension with such a `require` clause. Not a
blocker — but reconciliation should note that scenario-2 enforcement presupposes the selection grammar
admits the secondary sources, and that `primariness`-the-score-in-`require` and scenario-2-the-axis
interact at the pool boundary even though they are orthogonal *fields*.

### X6 — MINOR — The Layer-3 policy lever has no specified home in the config/cascade/provenance model
The initial calls warn-vs-block "a workspace/recipe policy (framework default = warn)" but does not say
*what* it is: a schema attribute (one-file-add, §5.4/§11.7)? a recipe field? a build flag (§13.5)? a new
cascade rung? This bears on one-file-extensibility, the provenance guard (a framework default vs an
instance override), and whether it rides the M-cascade at all. Reconciliation should place it concretely,
or it becomes a floating special case.

---

## 7. SHOULD-FIX — The `ir_version` / immutability wrinkle is mislocated AND mislabeled as "planner domain"

The initial (§6.1/§8) flags the wrinkle but (a) points at the wrong path and (b) downgrades a genuine
design tension to a bump-policy detail.

- **Mislocated (verified):** the GAP-1 re-render path does **not** re-validate — `driver.py:753`
  unwraps and reads `binding` directly, no `validate_ir`. The path that re-validates a stored canonical
  IR is **reconcile** (`reconcile.py:713`). So the concrete break surface is **RI11's "New platform or
  language → re-reconcile" tier** (§18): re-targeting an artifact composed under `ir_version=1` calls
  `validate_ir`, which pins `doc["ir_version"] == IR_VERSION` by **exact equality** (`ir.py:688`;
  `IR_VERSION=1`, `ir.py:108`). Bump to 2 and every pre-DR-6 stored IR **fails re-reconcile** — breaking
  RI10's "platform commitment is a cost boundary, not a lock; re-targeting is always one re-reconcile
  away." The initial's "confirm the re-render/`unwrap_ir` path tolerates old versions" checks a path that
  never validates and misses the one that does.
- **Mislabeled:** this is not merely "which bump policy." The immutable-no-migration model is explicit —
  MIG-7: "Artifacts are IMMUTABLE — never rewritten: migrate config, then REGENERATE"; `ir_version` is
  "a provenance stamp, not a migration target" (`ir.py:105-108`). There is **no migration path for a
  stored IR.** So the two horns are:
  - **Do NOT bump** `ir_version`: additive-optional `attestation` reads cleanly under the parts-pattern
    schema, and old + new IRs both validate — but two *different* ledger schemas now share
    `ir_version=1`, so the stamp **stops identifying the schema generation** for a self-describing,
    reproducibility-first immutable artifact. The stamp lies.
  - **DO bump** to 2: the stamp stays honest, but exact-equality `validate_ir` **strands every old IR
    from re-reconcile** (above), with no migration path (MIG-7 forbids one for artifacts).
  Neither horn is free; the choice is whether the IR ledger schema **can evolve at all** under an
  immutable-no-migration + exact-equality-pin regime. That is a design constraint on DR-6, not a planner
  footnote. Reconciliation should pick a horn explicitly (most likely: relax the exact-equality pin to a
  `>=`/known-set check so an additive-optional field does not strand old IRs — but that is itself an IR-
  schema-governance change with its own blast radius, and belongs in the design, not deferred).

---

## 8. What I could NOT break (honest)

- **ZERO new identity surface.** Re-verified against `ids.py` and `ir._validate_binding`: the ledger is
  outside the preimage and the binding digest. Adding `attestation` cannot fork an artifact-id. Solid.
- **The core thesis that a *perfect* semantic coverage hard gate is unachievable.** It survives even
  self-demarcation (Finding 1's steelman): self-demarcation hard-gates *form*, not *grounding-honesty*;
  the semantic half stays noisy. The initial is right that no design removes the per-claim judgment;
  it is wrong only that this forces *advisory* rather than *a hard structural gate plus a narrowed
  semantic audit*.
- **Scenario as a THIRD axis, orthogonal to tier / `traceability` / the `primariness` score.** The
  separation (§3.1) is correct and matches §6.2/§6.5; the research (S10 PROV-O) backs it. I could not
  collapse the axes.
- **Channel-agnostic grounding as a *principle*.** "Grounding is one property of every compose leaf,
  checked at one chokepoint" is sound and desirable. Only its *`[@key]` instantiation* fails (X1) — the
  principle stands; the binding does not.
- **The single-chokepoint / single-re-ask-point discipline.** Feeding correction notes into the existing
  bounded re-ask (rather than a new gate/loop) respects `compose.py:11` ("the ONLY re-ask point") — a
  clean structural choice, independent of the Layer-2 feasibility problem in Finding 2.

---

## 9. Severity roll-up
- **BLOCKER:** Finding 1 (self-demarcation retreat / unilateral fork-closure), Finding 2 (semantic
  verifier feasibility + engine-transfer of reliability numbers), X1 (`[@key]` store conflation +
  scenario-2 CSL collision), X2 (DR-4 hard-section × DR-6 hard-grounding deadlock).
- **SHOULD-FIX:** Finding 3 (utilization floor theater + false-reject), Finding 4 (attributed-only
  over-constraint / DR-5 boundary invasion), X3 (soft reconcile attribution), X4 (external strip knot),
  Finding 7 (`ir_version` mislocated + mislabeled).
- **MINOR:** Finding 5 (scenario binary vs union), X5 (primariness-require vs scenario-2), X6 (policy
  lever home).

The single most consequential reconciliation obligation: **stop the architect closing the maintainer's
own hard-vs-advisory question in a rejected-alternatives bullet.** Findings 1 and 2 together mean the
initial's headline posture (advisory coverage + a pre-persist semantic verifier) is both a retreat from
the ask and infeasible-as-placed on this transport. The maintainer should choose among
self-demarcation-hard-gate, advisory-coverage, and the combination — with the semantic layer placed at
Review-1 unless a measured `claude -p`-verifier reliability justifies the compose-time cost.
