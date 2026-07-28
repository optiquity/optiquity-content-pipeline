# ops-architect — ADVERSARIAL: attacking the honest enclosing subsystem BOX (increment E)

Pipeline: optiquity-content-pipeline · main @ cc42c54 · read-only. Mode: ADVERSARIAL.
Target: `architect-box-initial.md` ONLY (increment E — the completeness/closed-world machinery).
Base + amendment + badges (A→D) are SETTLED and NOT re-litigated. Every code claim below re-verified
at file:line THIS pass against the live tree (paths are `pipeline/…`).

Bottom line up front: **the box design's own reasoning is largely correct — and it leads to "do not
build E." I push harder than the initial did and find the enforcement mechanism does not even deliver
what it claims ("drawn == known to the source"); it delivers "drawn == whatever a budget-bounded query
happened to surface," dressed in a REFUSING gate + commit stamp + official caption that signal more
rigor than the substrate can support.** On the one axis where E differs from D, E is a regression, and
its new claim is the least verifiable construct in the whole feature. Recommendation: stop at badges (D).

---

## PART 0 — PLAIN ENGLISH FOR THE MAINTAINER (biggest problems first; read this at the gate)

**Straight answer to "is the box honest and worth building, or should we stop at badges?"
Stop at badges (D). Do not build the box (E) now.** Not "defer it pending its own pass" (the initial's
soft landing) — actively do not build it until a *named* closed-world need exists AND the enforcement
mechanism is re-derived, because as designed it does three dishonest things at once and buys almost
nothing the badge doesn't already buy honestly.

Here are the biggest problems, in plain words, worst first:

1. **The box's promise is weaker than even its own honest caption admits — and the caption is the ONLY
   thing making it honest.** The box captions itself "all members Auth's *source* knows, as of commit
   X." But the machinery cannot ask the source "list *everyone* in Auth." It can only run a *query*, and
   our real source tool (graphify) **truncates that query at a budget (default 2000) and ranks it** —
   returning a `... (truncated` marker when it cuts. So the box is actually closed only over "the
   members that fit inside the query's budget/rank window," which is *narrower* than "known to the
   source." The caption over-promises by one whole level. A large Auth (or a narrowly-scoped query)
   silently drops real, source-known members and the box still passes and still prints "all members
   known to the source." **This is the exact "make it look cleaner than the source" masking you cut the
   `detail` dial to kill — now re-manufactured by the enforcement machinery itself, under normal
   operation, not even under attack.** The whole point of the box was to close this hole; it doesn't.

2. **A writer can still hide a member — the hole just moves one layer down, out of sight.** The new gate
   checks "drawn == the enumerated known set." But the writer controls the enumeration query. Scope the
   query to exclude PaymentGateway, and PaymentGateway never enters the "known" set, so the box passes
   while omitting a real member — exactly the F1 omission the box claims to close "by construction." The
   enforcement doesn't close the hole; it relocates it from the diagram layer (visible in the source
   block) to the grounding-query layer (invisible, buried in query wording). That is arguably *worse*
   than the badge's honest silence, because now a REFUSING gate certifies the omission as complete.

3. **The box literally cannot be built for whole classes of source without faking data.** The new
   "structured member-of" contract fans out to every adapter, but our adapters mostly can't produce it:
   the **folder** adapter grounds paragraphs of text — it has no notion of a group at all; the
   **graphify** adapter grounds *edges*, not node-memberships, and its ONLY grouping datum is an
   algorithmic "community" cluster that is an *inference*, not an extracted fact — so grounding it
   produces below-the-publish-floor facts that can't ship as fact anyway. So the box either silently
   doesn't work for those sources, or forces an adapter to synthesize a membership it didn't really
   find — the one thing the pipeline forbids.

4. **On the "do these cooperate?" axis, the box is strictly LESS honest than the badge — and the design
   admits it.** The badge structurally avoided the "boxed-together = coupled" misread. The box re-incurs
   it and defends only with a caption the design *itself concedes* "fights a stronger Gestalt." So E pays
   a real, admitted honesty cost (a coupling regression) to buy a completeness claim that problems 1–3
   show is weak, gameable, and half-unbuildable. That is a bad trade dressed as a feature.

5. **Is it net more honest than D, or just more official-looking?** More official-looking. D makes only
   claims the existing check can verify. E makes a set-completeness claim the check *cannot* verify over
   reality, wraps it in a hard REFUSING gate + a commit SHA + a formal caption — all signals of rigor —
   over a substrate (budget-truncated queries, non-enumerable adapters, inferred clusters) that does not
   support the rigor those signals imply. You distrust exactly this: machinery that *looks* like a
   guarantee sitting on top of a guess. **A badge invites no completeness over-reading; an enforced,
   stamped box invites maximum completeness over-reading while delivering the least verifiable claim in
   the feature.**

None of this is a knock on the design's *reasoning*, which is careful and mostly right (it correctly
kills disclosure-only, correctly identifies the ledger-has-no-value blocker, correctly makes determinism
a hard gate). The knock is that the reasoning, followed all the way, says **don't build it** — and the
initial stops one step short of saying so plainly. This pass says it plainly.

---

## THE ATTACKS

### A1 — "Enforced completeness over extraction" is a dressed-up guess; the caption cannot carry the weight. SEVERITY: SERIOUS (honesty-floor).

**The design's claim (§2.3, §5b, §6.1):** enforcement makes "drawn == all *known* members" TRUE, and the
mandatory caption ("known to the source as of commit X; the source may not record every real member")
discharges the residual reality gap, so a REFUSING box is honest.

**Why the caption is doing more work than it can bear.** The design frames a two-level honesty ladder:
(reality) ⊇ (known-to-source), with the caption caveating the gap. But there is a THIRD level the design
collapses into the second and never captions: **(known-to-source) ⊋ (surfaced-by-the-enumeration-query)**.
Verified at code: the source is a *query* interface, not an enumeration interface — `SourceAdapter.ground
(connection, query) -> GroundingResult` (adapters/base.py:213-220) answers ONE query; `ground_item`
(grounding.py:799-1090) returns only the survivors of that query. Our real source adapter truncates and
ranks: graphify passes `--budget` (default `DEFAULT_BUDGET = 2000`, graphify.py:156), and the tool emits a
`... (truncated` marker (`TRUNCATION_PREFIX`, graphify.py:214) that sets `truncated=True`
(graphify.py:319,326). So the "known set" the gate computes is **the budget-and-rank-bounded query window,
not the source's actual member knowledge.** The caption says "known to the source"; the truth is "surfaced
by a bounded query." The caption over-promises by a full level — and this happens under *normal* operation
(a large group, a default budget), not only under attack.

**Construct the misled reader.** An engineer sees an "Auth" rectangle, a green REFUSING-gate provenance,
and a caption "All members of Auth known to the source as of commit `abc123`." Auth has 40 members; the
enumeration query, ranked and budgeted, surfaced 38; two fell outside the window; `truncated=True` but
nothing propagated that to a refusal. The box drew 38, the gate checked drawn==surfaced-38, passed, and
printed "all members known to the source." The reader — reasonably, because the machinery *signals*
completeness harder than any badge — treats it as the authoritative member roster and concludes the two
missing services are *not* part of Auth. **The box manufactured a false negative that the badge never
could,** because the badge never claimed a roster. The caption's "known to the source" caveat is not
load-bearing here — it is *false*, because the set isn't "known to the source," it's "surfaced by the
query."

**Is the box net MORE honest than D? No.** D makes only claims the existence+tier gate verifies. E adds a
set-completeness claim the gate cannot verify even over *extraction* (only over the query window), and
surrounds it with rigor-signals (REFUSE, commit pin, formal caption) that raise reader trust above what
the substrate earns. That is the "official-looking mask" pattern the maintainer distrusts.

**Fix or cut.** If E is ever built: the enumeration MUST propagate truncation as a hard REFUSE (if
`truncated=True`, the box cannot be drawn — a bounded honest outcome), AND the caption must drop "known
to the source" in favor of the literal "members within the enumeration window," which is not a boundary
claim at all — which is the tell that the honest box collapses toward the badge. **Recommended: cut.**
The badge (D) makes no roster claim, so it has no level-3 gap to caption; that is the honest shape.

---

### A2 — The set-equality gate is gameable at the grounding-query layer (the omission hole moves, it does not close). SEVERITY: SERIOUS (bordering BLOCKER for the "closes Q4 by construction" claim).

**The design's claim (§3.4 E-4, §6.1):** the set-equality check `drawn_and_boxed(G) == known(G)`
REFUSES on any undrawn known member, closing Q4 "by construction" — a fully-cited-but-incomplete box can
no longer ship.

**Why it does not close by construction.** `known(G)` is not a source-intrinsic set; it is the output of
an author-controlled query (§3.4 E-2 is "a dedicated per-boxed-group enumeration query issued at compose
… through `ground()`"). The writer authors that query the same way they author every item query. Because
`ground()` is query-bounded (adapters/base.py:213-220) and the walk unions only that query's survivors
(grounding.py:799-1090), **whatever the writer's enumeration query fails to name is simply absent from
`known(G)`** — and drawn==known holds vacuously over the shrunken set. The gate never sees the omitted
member, exactly as `_validate_refs` (ir.py:706-729) never sees a fact that was never grounded (it
iterates refs that EXIST, ir.py:710). So E does not remove the F1 omission hole; it moves it from the
diagram layer (a missing membership fact, at least co-located with the drawn block a reviewer reads) to
the grounding-query layer (a scoped query string), where it is *less* visible, not more.

**Concrete gameable case.** Source module `legacy` grounds `AuthV1 ∈ legacy`, `AuthV2 ∈ legacy`,
`PaymentGateway ∈ legacy`. Writer wants PaymentGateway to look modern. Under E they author the
enumeration query so it returns only AuthV1/AuthV2 (scope by name prefix, by sub-path, by a `--context`
that excludes it, or simply by a narrower positional question — graphify's query is positional,
graphify.py:6). `known(legacy) = {AuthV1, AuthV2}`; drawn == known; the box REFUSES nothing; the enforced,
commit-stamped "legacy" boundary ships asserting PaymentGateway is not legacy. **The exact adversary Q4
case (grouping-adversarial §Q4), reproduced through an enforced box** — with the enforcement now
*certifying* the lie.

**Two variants, both real:**
- *Adversarial (above):* deliberate query scoping.
- *Benign-but-still-false (A1):* honest writer, default budget, large group → `truncated=True` → known is
  a proper subset → box passes omitting a source-known member. **The machinery mints a false-complete box
  with no ill intent.** This is the more damning variant: enforcement fails in ordinary use.

**Fix or cut.** A genuine fix requires the enumeration to be *provably* the source's complete member set —
which the design itself admits is "unverifiable-complete" (§2.2 E-2, §2.3). You cannot prove a query is
complete against an interface that only answers queries and truncates them. At minimum: forbid a
free-authored enumeration query (derive it mechanically from the group id, no author scope surface) AND
refuse on `truncated`. Even then variant-1 residual (which axis/scope defines the group) remains an
editorial lever. **Recommended: cut** — the honest closure of Q4 was already achieved by the badge form
(no boundary → nothing to be outside of; grouping-reconciliation §3.3), for free, without a gate to game.

---

### A3 — Cross-adapter contract blast radius: E-1 is refused by live code, and most adapters cannot produce structured membership without faking. SEVERITY: BLOCKER (as designed).

**The design's claim (§3 E-1):** add a structured `member-of(G)` carrier to `Fact`; "Refinements already
have a validated pass-through path (`_validate_refinements`, grounding.py:646-676;
`PER_FACT_REFINABLE_SCORES`), so a membership refinement is the lowest-disturbance carrier if it fits that
shape."

**It does not fit that shape — verified, it is refused.** `PER_FACT_REFINABLE_SCORES` (m3.py:268-270) is a
CLOSED confidence-score vocabulary: `{authoritative, opinionated, review_status, primariness}`.
`_validate_refinements` (grounding.py:646-676) raises `RefinementError` on any key outside it
(grounding.py:648-654). A `member-of` refinement is **not a confidence score** — it is a structural
relation — so it would be REFUSED, and widening the closed set to admit it is an **orthogonality violation
(design.md §5): it blurs the per-fact *confidence-scoring* attribute channel with a *structural-relation*
channel.** The refinements path is therefore not "the lowest-disturbance carrier"; it is the wrong axis.
That forces the fallback the design names — a new `Fact` field (adapters/base.py:120-166) — which is a
hard contract change fanning out to every adapter, and which sits next to the resolver's agreement/conflict
keying on `(subject, claim)` (grounding.py:910-912) that E-1 must be careful not to perturb.

**Which adapters can even produce it (all five checked this pass):**
- **folder** (folder.py) — grounds paragraph blocks: `subject = <relpath>#p<n>`, `claim = verbatim
  paragraph text` (folder.py:246-258). No relations, no groups, no structure. **Structurally cannot
  produce membership.** The box silently does not work for folder-backed sources, or forces a fabricated
  membership.
- **graphify** (graphify.py) — the richest source, and it grounds **EDGES, not node-memberships**:
  `subject == claim == "<src> --<relation>--> <dst>"` (graphify.py:54, 552-554). NODE lines carry a
  `community=<n>` field (graphify.py:206) — latent grouping — but the adapter deliberately does not ground
  nodes as facts. Worse, `community` is an *algorithmic community-detection cluster* — an INFERENCE, not
  an extracted structural fact. If grounded it would be INFERRED-tier, and only EXTRACTED-tier publishes
  (`publishable`, grounding.py:387-390) — so the box's members would be **below the publish floor**.
  Producing member-of from graphify is a whole new fact-production mode plus an unresolved tier question,
  not "populate a field."
- **fsast** (fsast.py) — grounds AST flags (`subject=<relpath>::<flag>@L<lineno>`, fsast.py:406) and a
  directory-listing fact (`claim = "<dir>/ contains: <entries>"`, fsast.py:502-503). It has a *containment*
  notion but only as opaque free-text `claim` — a new structured relation, same fuzzy-parse problem base
  §2.2 rejected wholesale.
- **mock** (mock.py) — test fixture; can fake anything (which is the point of the attack: only the fake
  adapter can cleanly satisfy E-1).

**Consequence.** E-1 as specified (a) does not fit the carrier it names, (b) fans out as a hard `Fact`
contract change, and (c) has no honest producer among the real adapters — folder can't, fsast would fuzz,
graphify would emit inference-tier below the publish floor. The box "silently does not work for whole
adapter classes," and the only class it works cleanly for is the mock. That is a **blocker for E as a
generalized, reusable capability** (the maintainer's HARD requirement: generalized+reusable, no one-offs
— a feature that works only for the test adapter is a one-off).

**Fix or cut.** There is no cheap fix: honest structured membership requires each adapter to have a real,
extracted grouping relation, which folder/fsast do not have and graphify has only as inference. **Cut E**
until a source exists whose grouping is genuinely EXTRACTED and enumerable; only then is E-1 buildable
without faking. The badge (D) does not need E-1 at all (membership rides the existing `(subject, claim)`
fact through the unchanged gate), so D is unaffected by this blocker — another reason D is the honest stop.

---

### A4 — The enclosure re-exerts the coupling Gestalt the badge removed; the box is strictly LESS honest than D on the coupling axis. SEVERITY: SERIOUS.

**The design's own concession (§5c, §6.5):** the box re-incurs the common-region Gestalt ("these
cooperate") that the badge structurally avoided; the inherited "grouping ≠ coupling" legend "fights a
**stronger** Gestalt for an enclosure than for a shared chip"; the residual is "downgraded-and-disclosed,
not fully closed."

**The attack: this concession is decisive against E, not a footnote.** The badge form was chosen (D,
grouping-reconciliation §3.4) precisely because removing the enclosure makes the coupling misread go away
*structurally* — two unconnected `[auth]` nodes still read "unconnected." The box brings the misread back
and defends it only with a legend the design admits is perceptually overpowered. So on the coupling axis
**E is a regression from D**: it re-manufactures a false "these interact" reading (the adversary's
PasswordHasher/OAuthProvider case, grouping-adversarial §Q1) that D had eliminated, and pays a legend that
is weaker here than it was for badges. The three-property proof (§5c) marks (c) "HOLDS with legend" but the
design's own text downgrades that to "not fully closed." **You cannot both claim property (c) holds and
concede the legend doesn't fully close it.** Honestly scored, (c) *leaks* for the box exactly as much as
the initial box leaked before badges — the legend is the same instrument the reconciliation already ruled
sufficient only for the *badge*, where no enclosure fights it.

So E's ledger is: it **loses** honesty on the coupling axis (regression vs D) to **buy** a completeness
claim that A1–A3 show is weak, gameable, and half-unbuildable. Net honesty change vs D: negative.

**Fix or cut.** A plain caption is not sufficient against a common-region enclosure — the design says as
much. There is no fix that keeps the enclosure and removes the Gestalt (the Gestalt *is* the enclosure).
**Cut** — the badge already delivers the honest grouping value (which subsystem is each node in) without
the coupling regression.

---

### A5 — Determinism: cluster/container SVG is an unrun identity-bearing gate; the honest fallback is to cut E, not to normalize. SEVERITY: SERIOUS (posture right; outcome likely a cut).

**The design's posture (§4, §7.3.4):** the box re-introduces `dot subgraph cluster_*` / d2 containers —
new layout topology the badge dropped — and makes byte-identical SVG (run-to-run AND cross-machine, WITH
cross-cluster edges) a HARD gate before any E plan; fail → E does not ship, uniformly for all tools. This
posture is **correct and I do not attack it** — SVG bytes are identity (RenderInputs.assets by content
hash, dispatch.py:121; serialize.py:773-782), and cluster bounding-box + cross-cluster edge routing are
where Graphviz non-determinism historically lives.

**What I assess (the task's question): if clusters are non-deterministic, is "normalize the SVG" an honest
fallback, or is "cut E" the likely outcome?** Normalizing is NOT an honest fallback. Cluster
non-determinism lives in computed *geometry* (bounding boxes, edge spline control points); "normalizing"
that means canonicalizing coordinates — i.e., discarding or rounding the very bytes that differ, which
either (a) destroys layout fidelity, or (b) is a brittle post-processor that must itself be proven
deterministic and byte-stable cross-machine, recreating the original problem one layer up. It also inserts
a transform between `dot` and the content-addressed asset, widening the identity surface the pipeline works
hard to keep minimal. **The honest fallback is to cut the cluster topology (i.e., fall back to badges),
not to launder its bytes.** And note the amendment/badge rule (§2.F, box §4): a per-tool flatten is
forbidden because it makes `tool` decide *whether* the boundary claim is made — the §5 blur. So a partial
"clusters work under dot, normalize under d2" is doubly barred.

**Likely outcome:** given that the spike is unrun, that cross-cluster routing is the realistic hard case,
and that the only honest fallback is a uniform cut — **"cut E if non-deterministic" is the probable
result.** Combined with A1–A4, this makes E a large speculative build gated behind an unrun spike whose
most likely failure mode deletes it. That is a strong reason not to open the build.

**Fix or cut.** Keep the hard gate exactly as designed; do not add SVG normalization. Recognize that the
gate's likely failure → cut reinforces the top-line recommendation.

---

### A6 — Is E worth it? No named closed-world need; the honest recommendation is stop at D. SEVERITY: the governing verdict.

**Synthesis of A1–A5 against the maintainer's north stars (simplest honest deliverable; generalized +
reusable + permanent, no one-offs; distrust knobs/machinery that mask):**

- E's *only* new claim over D is completeness/boundary. A1 shows the delivered claim is narrower than its
  own caption ("query window," not "known to source") and its rigor-signals inflate reader trust above the
  substrate. A2 shows the enforcing gate is gameable/degradable at the query layer, so it does not close
  the omission hole "by construction." A3 shows E-1 is refused by live code as specified and has no honest
  producer among the real adapters (works cleanly only for the mock — a one-off). A4 shows E is a coupling
  regression vs D, conceded by the design. A5 shows the enabling topology is an unrun identity gate whose
  likely failure is a cut.
- **No named closed-world need exists** anywhere in the settled record. The box's own §7.2 and the
  grouping reconciliation §4.3-E both condition E on "*if* a real closed-world-subsystem need appears." It
  has not appeared. Building E now is building speculative, heavyweight machinery (a new grounding
  capability + a re-introduced layout topology + a new gate + an every-adapter contract change) against no
  demand — the one-off / masking pattern the maintainer's memory explicitly forbids.

**Verdict.** E does NOT clear the honesty floor as designed, and even if the code issues were fixed it
would not be *worth* it absent a named need. **The badge (D) is the correct stopping point.** This is not
a rubber-stamp deferral of the maintainer's "build it" — it is the honest finding that the box, followed
to the code, is less honest than the badge on the axis it regresses and no more honest on the axis it
claims. Do not build E now.

**If a real closed-world need is later named**, E must be *re-derived*, not resumed from this design,
resolving at minimum: (1) mechanically-derived (not author-scoped) enumeration + refuse-on-truncated
(A1/A2); (2) a source whose grouping is genuinely EXTRACTED and enumerable, with defined behavior for
non-enumerable adapters like folder (A3); (3) the graphify community-is-INFERRED tier question (A3);
(4) an honest disposition of the conceded coupling regression (A4); (5) the passed cluster-determinism
gate with no SVG-normalization fallback (A5).

---

## WHERE E IS RIGHT (not attacked)

- **Disclosure-only is correctly killed.** §2.2's rejection of 2a (affirmative caption without proof =
  false certification) and 2b (disclaiming caption = worse-than-badge rectangle) is sound and verified
  against the ledger/gate. If one insisted on a box, enforce-or-don't-draw is the right binary.
- **The ledger-has-no-value blocker is real and correctly diagnosed.** `LEDGER_REQUIRED` (ir.py:154-161)
  has no subject/claim/value field; `_validate_refs` (ir.py:706-729) is pure existence+tier; `FactRef`
  (ir.py:361-372) is `(fact_id, tier, where)`. The persisted ledger genuinely cannot enumerate memberships
  by group. Verified exact.
- **The "not a `_validate_refs` reuse" honesty is correct.** Set-equality is a different check the
  origin-agnostic gate structurally cannot perform. The design is right that the badge's crown-jewel
  cheapness does not transfer — which is itself an argument against building E.
- **Determinism as a HARD gate (not "expected") and the uniform-cut (no per-tool flatten) rule are
  correct.** §4 is honest.
- **Soundness by inheritance (§5a) holds** — the box draws no member D didn't already draw as a grounded
  badge node.

The design's reasoning is good enough that it nearly reaches the right answer itself (§7.3: "E is NOT
ready … D remains the honest stopping point"). My disagreement is only that it soft-lands on "defer pending
its own pass" when the code evidence supports the harder "do not build; stop at D."

---

## WHAT RECONCILIATION MUST RESOLVE (ranked, honesty-first)

1. **A6 / GOVERNING (blocker-level verdict) — E is not honest-and-worthwhile as designed; recommend
   STOP AT D.** Reconciliation must either (a) accept the cut and record D as the honest terminus absent a
   named closed-world need, or (b) if it insists on keeping E alive, it must down-scope E to a *deferred,
   unbuilt, re-derive-from-scratch* slot and resolve items 2–5 before any plan — not carry this design
   forward as-is.

2. **A3 (BLOCKER) — E-1 is refused by live code and has no honest producer.** The refinement carrier is
   rejected (`PER_FACT_REFINABLE_SCORES` closed, m3.py:268; `_validate_refinements` refuses,
   grounding.py:648) and using it is a §5 orthogonality blur; the `Fact`-field fallback fans out to
   adapters that cannot honestly populate it (folder can't; graphify's grouping is INFERRED/below the
   publish floor; fsast is free-text). Reconciliation must either name a genuinely enumerable EXTRACTED
   grouping source or accept that E is unbuildable-without-faking today.

3. **A1 + A2 (SERIOUS, together the crux) — the enforcement does not deliver "known to the source."** The
   enumeration is a budget-truncated (`DEFAULT_BUDGET`, `TRUNCATION_PREFIX`, graphify.py:156/214/319),
   author-scoped query (`ground(connection, query)`, adapters/base.py:213). Reconciliation must, if E
   survives at all: forbid author-scoped enumeration, refuse-on-truncated, and correct the caption from
   "known to the source" to the literal "query-window members" — at which point the box stops being a
   boundary claim, i.e. collapses toward the badge. This is the finding the initial missed entirely.

4. **A4 (SERIOUS) — coupling regression.** The design concedes the legend "fights a stronger Gestalt" yet
   marks property (c) as holding. Reconciliation must not claim (c) holds for the box while conceding the
   legend under-closes it; the honest scoring is that E *loses* honesty on the coupling axis relative to D.

5. **A5 (SERIOUS) — determinism.** Keep the hard gate; explicitly bar SVG normalization as a fallback;
   record that the honest failure path is a uniform cut to badges. Note the likely outcome is a cut.

6. **Minor — carry the verified corrections:** E-1's "lowest-disturbance refinement carrier" claim is
   false (must be struck); the caption's scope word must change from "known to the source" to the honest
   query-window scope; the §6.1 "enumerates known(G) ⊇ {A,B,C}" assumption ignores truncation and must be
   qualified.

**Bottom line for the maintainer.** The box does three dishonest things the badge does not: it promises
"all members known to the source" while delivering only a budget-bounded query window (A1); it lets a
member be hidden one layer down where no reviewer sees it (A2); and it re-invents the "these cooperate"
misread the badge removed (A4) — all while being unbuildable without faking on our real sources (A3) and
gated behind an unrun determinism spike whose likely failure deletes it (A5). It is the most
official-looking construct in the feature wrapped around its least verifiable claim. **Stop at badges (D).
Build the box only if a real closed-world need is named, and re-derive its enforcement from scratch when
that day comes.**

--- end of ADVERSARIAL (honest enclosing subsystem box, increment E) ---
