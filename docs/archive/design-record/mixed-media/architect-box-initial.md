# ops-architect — INITIAL: the honest enclosing subsystem BOX (increment E)

Pipeline: optiquity-content-pipeline · main @ cc42c54 · read-only. Mode: INITIAL (design the ONE
remaining piece: the completeness/boundary claim of the box). On top of the FIXED, DECIDED stack:
base (`architect-reconciliation.md`) + amendment (`architect-amendment-reconciliation.md`) + badge
grouping D (`architect-grouping-reconciliation.md`). The box INHERITS D's grounded name, "grouping ≠
coupling" legend, and visible single grouping axis. This report designs ONLY the box's extra claim —
**completeness (the boundary)** — and does NOT re-litigate base / amendment / badges. Every code claim
re-verified at file:line this pass against the live tree (paths are `pipeline/…`).

---

## PART 1 — PLAIN ENGLISH (for the maintainer; read this at the gate)

### Can we honestly promise "these are ALL the members"? Yes — but only one way, and it is not cheap.

The badge (increment D, already settled) tags each box with a chip: "this one is a cited member of
Auth." It never draws a line around anything, so it never says who is *left out*. The **box** adds
exactly one thing on top: it draws a line, and a line has an inside and an outside. That line is a new
promise — **"these are all of Auth, and everyone outside is not Auth."** That promise is the entire
point of the box, and it is the only thing this report is about.

Here is the one honest limit, stated up front, in plain words: **the strongest thing the pipeline can
ever truthfully draw is "these are all the members Auth's *source* knows about, as of the commit we
read" — never "all the members that exist in the real world."** The source graph is built by reading a
repo; it can be missing a real member the same way any map can be missing a real street. So even in the
best case, the box's promise is "complete as far as the source knows," and that qualifier has to be
printed **on the picture**, in a caption — not buried in a provenance file — because a reader who sees a
tidy "Auth" rectangle will otherwise assume it means "all of Auth, period." You distrust hidden masking;
this is exactly the place a hidden qualifier would mask a real gap.

Now, the two ways to keep the promise honest:

- **ENFORCE (prove it).** For the pipeline to *prove* the box left nobody out, it has to be able to ask
  the source "list every member of Auth" and then refuse to draw the box unless every one of those
  members is inside it. Today it **cannot ask that question.** The source hands us facts one query at a
  time; there is no "give me the whole member list" button, and the place we store facts for the honesty
  check keeps only *that a fact exists*, never *what it says* — so we literally cannot count "all Auth
  members" the way the check would need to. Building that ability is real work spread across the whole
  grounding stack (the source-adapter contract, every adapter, the resolver, and a brand-new kind of
  check the pipeline has never had). It is **not** "the badge plus a rectangle."

- **DISCLOSE (just say it).** The tempting cheap path: draw the writer's declared members, skip the
  proof, and print a caption "all members of Auth known to the source." **This one does not work, and it
  is important to see why, because it looks reasonable.** If the writer quietly leaves out a member the
  source *does* know about, that caption is now a flat lie the pipeline printed in words — worse than the
  silent box, because now the diagram *affirmatively certifies* a completeness nobody checked. That is
  the exact "make it look cleaner than the source" hole you cut the `detail` dial to close, walking back
  in one level down — only now stated out loud. The only *honest* caption you could print without the
  proof is "these are *some* members; this is **not** a complete list" — but that caption **cancels the
  box's whole promise.** A rectangle whose own caption says "this isn't really a boundary" is strictly
  worse than a badge: it still makes two boxes look like they cooperate (the coupling problem), and it
  buys you nothing in return.

**So the honest answer is binary: if you want the box's "all members" promise at all, you must ENFORCE
it (and *also* caption the source-vs-reality limit). If enforcing is too much machinery to justify, then
you should NOT draw the box — ship the badge (D) and stop there.** Disclosure is a mandatory *addition*
to enforcement (for the reality gap); it is never a *substitute* for it. There is no honest cheap box.

### What it costs, honestly

The badge (D) was cheap because it reused the check the pipeline already has and just added new things
to check. The box's completeness promise **cannot** reuse that check — the existing check answers "does
this fact exist?" and the box needs "is this the *complete set*?", which is a different question the
current machinery was never built to ask. Enforcing it means teaching the source layer to enumerate
members, teaching the pipeline a new completeness check, and — separately — going back to the drawing
engine's "cluster" feature that the badge deliberately avoided, whose reproducibility is an open,
identity-bearing question we have not tested. **E is a genuine new increment, materially bigger than D,
and it should be sequenced strictly after D and only built if a real "closed-world subsystem" need shows
up.** My recommendation (Part 7): E is **not** ready to plan alongside A→D; the enforcement mechanism
should take its own adversarial pass first.

---

## PART 2 — WHAT MAKES A BOUNDARY HONEST (the one hard problem, resolved)

Orthogonality first (design.md §5): the box stacks **three distinct claims**, and they must not blur.
- **Membership** — "X is in Auth." (D grounds this: `membership_fact` through the existing gate.)
- **Coupling** — "the members interact." (D neutralizes this: the "grouping ≠ coupling" legend.)
- **Completeness / boundary** — "these are ALL and ONLY the members." **This is E's whole and only new
  claim.** It is NOT membership (that is per-node); it is NOT coupling (that is the legend's job). It is
  a *set-level* claim about the whole group, and it is the first claim in the entire diagram feature
  that is about a set rather than about an element. Keeping it orthogonal is the design discipline here:
  E must add exactly the machinery that proves *the set*, and nothing that re-touches membership or
  coupling.

### 2.1 The verified blocker: the pipeline cannot enumerate a group's members today

For the boundary to be *provably* honest, "X ∈ Auth" must be an **enumerable** fact — the gate must be
able to ask "what are ALL the members of Auth?" and get a complete answer. Verified against code, it
cannot, at three layers:

1. **The honesty ledger has no value.** `LEDGER_REQUIRED` (ir.py:154-160) = `tier, source_instance_id,
   source_repo, source_commit, traceability_anchor, scores_snapshot` — **no subject/claim/value field.**
   `_validate_refs` (ir.py:706-729) reads only `ref.fact_id`, `ref.tier`, `ref.where`, and
   `ledger[fact_id]["tier"]` — a pure **existence + tier** check, origin-agnostic. `FactRef`
   (ir.py:361-372) is `(fact_id, tier, where)` — no relation, no object. So from the persisted ledger
   the gate **cannot enumerate "all membership facts whose group is Auth"** — there is nothing to filter
   on. (This is the blocker the task flagged, and it verifies exactly.)

2. **Membership is not a structured relation at the source.** The adapter contract's `Fact`
   (adapters/base.py:120-166) is `(subject, claim, tier, anchors, as_of, refinements)` where `claim` is
   **opaque free text**. Nothing carries a structured `(member, relation=member-of, group)` triple. To
   enumerate "members of Auth" you would either parse membership out of the free-text `claim` (fuzzy
   matching — rejected wholesale by base §2.2) or make membership a first-class structured fact — a
   **contract change** (adapters/base.py) that then **fans out to every adapter** (the step-18 graphify
   adapter and all others must populate it).

3. **The source is a query interface, not an enumeration interface.** `SourceAdapter.ground(connection,
   query) -> GroundingResult(facts)` (adapters/base.py:213-220) answers *one query* and returns the
   facts matching it. There is **no "list all members of G" primitive**, and the facts that actually
   reach compose are query-bounded: `ground_item` (grounding.py:799-1090) unions the survivors of the
   *item's* query + selection filters. `GroundedFact` (grounding.py:359-390) does carry `subject`/`claim`
   through to compose — and `build_grounding_ledger` (compose.py:244-298) has them in hand at ledger
   build time (compose.py:256, 272) even though they never enter the persisted ledger (compose.py:268
   comment) — but that set is **whatever the writer's queries surfaced, never a guaranteed-complete
   member set of G.** Completeness is not available anywhere without a dedicated per-group enumeration.

**Consequence:** enforceable completeness is a NEW grounding capability, not a reuse. The badge's
crown-jewel cheapness ("reuse `_validate_refs`, add new `FactRef` producers", grouping-reconciliation
§3.2) **does not carry to the box**, because `_validate_refs` proves *existence of drawn things* and the
boundary needs *equality of a drawn set with a known set* — a different check the origin-agnostic gate
structurally cannot perform.

### 2.2 Enforce vs disclose, resolved: DISCLOSURE CANNOT SUBSTITUTE FOR ENFORCEMENT

I evaluated the task's option 2 (disclosure-without-enumerable-enforcement) rigorously and reject it as
a substitute. It splits into two variants, both dominated:

- **2a — affirmative caption ("all members known to the source"), no proof.** If the writer omits a
  member the source knows (the adversary's `legacy`/`PaymentGateway` case, grouping-adversarial Q4), the
  caption is now an **explicit false certification** — the pipeline printed, in words, a completeness the
  gate never checked. This does not close the F1 omission hole; it **re-opens it and makes it worse**,
  because the lie is now affirmative rather than a silent boundary. Fails the honesty floor outright.

- **2b — disclaiming caption ("some members; not a complete list").** This is honest, but it **cancels
  the box's only reason to exist**: the box no longer makes a closed-world claim, so it is not increment
  E — it is a badge with a rectangle drawn around it. And the rectangle is not free: it still triggers
  the common-region Gestalt (closed-world + "these cooperate"), which the caption must now verbally
  un-draw. That is **strictly worse than the badge**: same coupling residual the badge structurally
  avoided, plus a boundary the caption fights, for **zero added honest claim.** Dominated by D.

**Therefore: the box's completeness claim is honest ONLY with enforcement.** And enforcement alone is
also not enough — even a proven "drawn == all *known* members" is only closed over extraction, never
over reality (§2.3). So the honest box needs **BOTH**: enforcement (to make "all known members" TRUE) +
a mandatory disclosure caption (to keep the reader from reading "known" as "real"). Enforce and disclose
are **not either/or for the box** — they are both required. Disclosure is the reality-gap caption *on
top of* enforcement, never a cheaper path *instead of* it.

### 2.3 The honest floor, stated plainly and made reader-visible

**What "complete" CAN mean here:** closed over the source's EXTRACTED knowledge, as of the pinned
commit. "Every member Auth's source graph records at commit X is inside this box."

**What it CANNOT mean:** closed over reality. The adapter may not surface every real member; the source
graph may itself be missing one (an un-graphed file, an INFERRED-only member below the publish floor at
ir.py `publishable`/grounding.py:386-390). No machinery in this pipeline can close that gap, because the
pipeline only ever reads a source — it never sees the world.

**Making the limit reader-visible (not buried):** the box carries a **mandatory, non-optional caption**
naming the closed scope AND the commit basis: *"All members of Auth known to the source as of commit
`<sha>`; the source may not record every real member."* This is plain descriptive text carrying **no
`data-fact` span**, so it adds 0 to the raw-count backstop (`_DATA_FACT_RE.findall`, ir.py:469-476) and
cannot false-trip it — the same backstop-safety D established for its legend (grouping-reconciliation
§3.4), inherited unchanged. The caption lives in the stored SVG / a plain caption line, not the
persisted `data-fact` body — base §2.4 moot preserved. The commit `<sha>` is already carried:
`GroundedFact.commit` (grounding.py:368) and the ledger `source_commit` (ir.py:157).

---

## PART 3 — THE ENFORCEMENT MECHANISM (exact grounding / ledger / gate changes, scoped)

E's completeness enforcement is a stack change, from source to gate. Scoped precisely, smallest-first:

**(E-1) Structured membership fact — adapter contract.** Add a structured membership carrier so
"member-of(G)" is enumerable rather than buried in free-text `claim`. Cleanest shape that does not
disturb the existing `(subject, claim)` agreement/conflict machinery (grounding.py:910-1024, which keys
on `(subject, claim)`): a **per-fact refinement-style structured field** or a dedicated `Fact` subtype
carrying `group_ref` (the group id) + `relation="member-of"`. Touch point: `Fact` (adapters/base.py:120)
and its `__post_init__` validation (adapters/base.py:138). **Fan-out cost:** every real adapter (step-18
graphify + any others) must populate it — this is a **contract change across all adapters**, not a
one-file change. Refinements already have a validated pass-through path (`_validate_refinements`,
grounding.py:646-676; `PER_FACT_REFINABLE_SCORES`), so a membership refinement is the lowest-disturbance
carrier if it fits that shape; otherwise a new `Fact` field is required.

**(E-2) Enumeration reach-back — resolver / compose.** To know "all known members of G," compose must
obtain the complete set, not the query-bounded survivors. Two honest options, both new:
- a **dedicated per-boxed-group enumeration query** issued at compose ("enumerate members of G") through
  `ground()` (adapters/base.py:213) — this is a **new compose-time graph reach-back**, exactly the
  reach-back the badge form proudly avoided (grouping-reconciliation §3.3, §3.5); or
- the resolver surfaces the group's full membership on `GroundedFact` (grounding.py:359) so compose can
  assemble it without a second query.
Either way it is a **new grounding capability**, and its answer is **unverifiable-complete** — the
pipeline cannot prove the adapter did not omit a member (§2.3 honest floor). This is the irreducible
limit, and it is why the caption (§2.3) is mandatory even with enforcement.

**(E-3) Carry the enumeration to the gate — ledger or compose structure.** The persisted ledger has no
value field (ir.py:154-160); it cannot index memberships by group as shipped. Two options:
- a **new additive-optional ledger carrier** — a per-group membership index — via `LEDGER_OPTIONAL`
  (ir.py:168, which is explicitly extensible; an additive-optional generation keeps older envelopes
  valid, ir.py:126-131); or
- a **compose-time-only structure** built from the E-2 enumeration + the drawn member list, never
  persisted (lighter; keeps the ledger schema untouched).
The compose-time-only structure is preferable (smaller identity/schema surface), because the enumeration
is only needed to *gate the draw*, not to persist.

**(E-4) The NEW gate check — set equality, NOT `_validate_refs`.** The boundary check is: for each boxed
group G, `drawn_and_boxed_members(G) == known_members(G)`. This is a **set-equality** check the existing
origin-agnostic existence+tier gate (`_validate_refs`, ir.py:706-729) structurally cannot perform — it
iterates refs that EXIST and never computes a set complement. So E adds the **first diagram gate that is
NOT a reuse of `_validate_refs`**: a new checker that (a) reuses D's per-member `_validate_refs` pass for
soundness (each drawn member cited), then (b) computes the known-set (E-2/E-3) and **REFUSES** (a typed
`SchemaViolation`-class error) if any known member is not drawn-and-boxed. Omission → REFUSE, closing Q4
**by construction** — a fully-cited-but-incomplete box can no longer ship.

**(E-5) Cluster/container emitter.** The box IS a `dot subgraph cluster_*` / `d2` container — new layout
topology the badge form explicitly dropped (grouping-reconciliation §3.1: "never an enclosing
`subgraph cluster_*` / container"). New emitter pass in both pooled tools, gated behind the
determinism spike (Part 4).

**(E-6) The mandatory disclosure caption** (§2.3) — always, even with E-1..E-5.

Net: E = **E-1 (contract + every adapter) + E-2 (new reach-back / resolver carry) + E-3 (ledger or
compose index) + E-4 (new set-equality checker) + E-5 (cluster emitter) + E-6 (caption)**. This is a new
grounding capability plus a re-introduced layout topology — not a decoration pass on D.

---

## PART 4 — DETERMINISM (the box-specific gate)

The badge (D) shrank the determinism unknown to "does a richer *label/fill* perturb bytes?" precisely
because it added **no clusters** (grouping-reconciliation §3.6). The box **re-introduces clusters**, and
with them the identity-bearing unknown the grouping-adversarial pass flagged as the required spike
surface (Q5 #2): **`dot subgraph cluster_*` bounding-box computation and cross-cluster edge routing are
where Graphviz non-determinism historically lives**, and can depend on cluster/node declaration order
and engine version. SVG bytes ARE identity (RenderInputs.assets by content hash, dispatch.py:121; "every
asset by CONTENT hash", serialize.py:773-782).

**Box-specific determinism gate (HARD, before any E plan):** *Adding a `subgraph cluster_*` (dot) /
container (d2) around a node subset must keep the compiled SVG byte-identical (a) run-to-run and (b)
cross-machine under the pinned tool version, WITH cross-cluster edges present* — not isolated clusters
(the realistic case, per grouping-adversarial Q5 #2). This is a genuinely new surface that neither the
flat (C) nor badge (D) spike exercised. **Fail → E does not ship, uniformly for all tools** until fixed
— never silently flattened for one tool (amendment §2.F: `tool` changes only *how*, never *whether* a
box appears; a per-tool flatten would make `tool` decide whether the boundary claim is made — the
forbidden §5 blur). An unverified layout feature cannot enter a content-addressed pipeline on "expected."

---

## PART 5 — THE THREE-PROPERTY HONESTY PROOF, WITH THE BOX

- **(a) SOUNDNESS — drawn ⊆ grounded.** Each drawn member is cited via `membership_fact` and each group
  name via `group.fact`, through D's existing `_validate_refs` pass (ir.py:706-729), **inherited
  unchanged**. The box draws no member it did not already draw as a badge-grounded node; the enclosure
  adds no new *drawn element*, only a set-level assertion about existing ones. **HOLDS by inheritance.**

- **(b) COMPLETENESS — grounded ⊆ drawn, unless reader-visibly disclosed.** For the badge this held
  *unconditionally and vacuously* (additive absence — no boundary, nothing to omit,
  grouping-reconciliation §3.3). **For the box it is NOT vacuous — it is the box's whole point.** It
  holds **iff enforcement (E-2..E-4) is present**: the set-equality check proves `drawn == known(G)`, so
  an omitted known member REFUSES (closing Q4 by construction). The residual `known ≠ reality` (§2.3) is
  the "unless reader-visibly disclosed" clause, discharged by the mandatory caption (E-6). **Without
  enforcement, (b) FAILS** — a fully-cited box can omit a known member (§2.2). This is the crux finding:
  **completeness for the box requires enforcement + disclosure; disclosure alone cannot secure it.**

- **(c) NO UNGROUNDED NON-EDGE CLAIM.** The box asserts THREE non-edge claims: (i) membership — cited
  (inherited D); (ii) name/existence — cited at label-trust (inherited D's Q3 downgrade,
  grouping-reconciliation §3.5; the box neither raises nor lowers this bar); (iii) **boundary /
  completeness — the NEW claim**, grounded ONLY by the E-4 set-equality check and scoped by the E-6
  caption. The coupling reading is neutralized by D's inherited "grouping ≠ coupling" legend — **with one
  honest caveat the box must own: the enclosure re-introduces the common-region Gestalt the badge
  structurally avoided, so the legend fights a stronger perceptual pull for a box than for a badge**
  (§6.5). **HOLDS with enforcement + legend + caption**; the coupling residual is heavier than D's and is
  disclosed, not denied.

**All three by construction — but (b) and the boundary half of (c) are secured by the NEW enforcement
machinery, not by the reused gate.** That is the precise, honest difference between E and D: D matched
its drawn claims to what the existence+tier gate can verify; the box makes a set-completeness claim the
existence+tier gate cannot verify, so E must *add the check that can* — or not draw the box.

---

## PART 6 — RIGOROUS SELF-ADVERSARIAL: try to make the honest box lie

**6.1 False "all members" via unenumerable grounding (the primary attack).** Writer declares members
{A, B}, silently omits a source-known member C. *Closed by enforcement:* the E-4 set-equality check
enumerates `known(G) ⊇ {A, B, C}`, finds C undrawn, **REFUSES**. *NOT closed by disclosure alone:* a 2a
caption would affirmatively certify a false completeness (§2.2) — worse than silence. **This attack is
the whole reason enforcement is mandatory.** Verified against the blocker: without E-1..E-4 the gate
cannot even *see* C (ledger has no value, ir.py:154-160; `ground()` is query-bounded, adapters/base.py:213).

**6.2 Stale ledger / stale enumeration.** The enumeration was computed at commit X; the source added
member D at commit Y > X; a box drawn from the stale set omits D. *Closed by commit-pinning + disclosure:*
the enumeration (E-2) and the drawn set both ride the SAME commit — `GroundedFact.commit`
(grounding.py:368), ledger `source_commit` (ir.py:157) — so `drawn == known-at-X` genuinely holds, and
the E-6 caption states "known to the source **as of commit X**." `known-at-X ≠ known-at-Y` is disclosed
by the commit stamp on the face of the picture, not hidden. Re-composing at Y mints a new artifact (new
content hash → new identity), so a refresh is a new honest diagram, not a silent mutation. **Closed
(disclosed, commit-scoped).**

**6.3 Overlap / a node in two boxes.** A node cited as a member of both Auth and Billing → two
overlapping clusters. Clusters *partition*; they cannot *cover*. *Closed by the inherited single-axis
rule* (D §3.5: one declared axis per diagram, mixed-axis refused) — on the drawn axis a node has ≤1
membership, so no overlap. If the source genuinely grounds ≥2 memberships **on one axis** (a true cover,
e.g. a file in two modules), a cluster cannot render it honestly. *Honest disposition:* **REFUSE the box
for that diagram** (uniform bounded outcome) or fall back to badges for that node — **never silently pick
one membership** (that would be a `detail`-class omission). This is a box-only constraint the badge did
not have (badges show multiple chips freely; boxes cannot overlap). **Closed (refuse-or-badge-fallback,
loud).**

**6.4 Singleton box.** A box around one node reads "this one node is the whole subsystem." *Honest iff
enforcement proves the source knows exactly one member* — then "Auth has one known member" is TRUE.
Without enforcement a singleton could hide known siblings (= attack 6.1). With E-4 + the E-6 caption it
is honest. **Closed (reduces to 6.1 + disclosure).**

**6.5 Co-containment coupling, resurrected by the enclosure.** Two non-interacting cited members
(`PasswordHasher`/`OAuthProvider`, grouping-adversarial Q1) boxed together read "these cooperate." The
badge structurally avoided this; **the box re-incurs it.** *Neutralized by D's inherited "grouping ≠
coupling" legend* — but I will not overclaim: the legend fights a **stronger** Gestalt for an enclosure
than for a shared chip (common-region is a more totalizing perceptual cue than a matching label). The
residual is genuinely heavier for the box, and it is **disclosed as the price of the enclosure form**,
not denied. This is precisely the cost the badge avoided and the box pays to buy the closed-world claim.
**Downgraded-and-disclosed, not fully closed** — honest, and the honest reason to prefer D unless a real
closed-world need exists.

**6.6 Name spoofing (inherited Q3).** "Authentication Subsystem" box around a prototype-module fact. The
name rides label-trust (D's Q3 downgrade; no ledger value to check, ir.py:154-160; anchor may be `[]`,
ir.py:65). The box neither raises nor lowers this bar — **same residual as D**, not re-litigated, and
correctly *not* claimed closed.

**Net:** every attack is either closed by construction (6.1 enforcement, 6.3 refuse/fallback), closed by
disclosure+commit-pinning (6.2, 6.4), or honestly downgraded-and-disclosed as the enclosure's price
(6.5, 6.6). Critically, **6.1 is closed ONLY by enforcement** — the disclosure-only box fails its
primary adversarial case, which is the whole argument of Part 2.

---

## PART 7 — HONEST E-OVER-D COST, SEQUENCING, AND RECOMMENDATION

### 7.1 E is a real increment, not a small add on D

D (badges), priced honestly (grouping-reconciliation §4.1): reuse `_validate_refs` unchanged + 2 new
`FactRef` producers + 2 coverage `require`s + a per-node badge/style pass + one legend line + Q3 doc
change + a small determinism/citation spike. No reach-back, no reduction, no new checker, no clusters.

**E ADDS, on top of D:**
- **E-1** structured-membership carrier — an **adapter-contract change that fans out to every adapter**;
- **E-2** an enumeration reach-back (new compose-time graph read) or resolver carry — a **new grounding
  capability**, whose answer is **unverifiable-complete** (the honest floor);
- **E-3** a per-group membership index (ledger additive-optional carrier or compose-time structure);
- **E-4** the **first diagram gate that is NOT a `_validate_refs` reuse** — a new set-equality checker;
- **E-5** the **cluster/container emitter** the badge form deliberately dropped;
- **the cluster determinism spike** — a **fresh identity-bearing unknown** the D spike shrank away;
- **E-6** the mandatory reality-gap caption (backstop-safe, inherited shape).

So E is **a new grounding capability + a re-introduced layout topology + a new checker**, materially
bigger than D. The badge's "approximately free, single-surface" honesty (grouping-reconciliation §4.1)
**does not transfer**: it held for D because D made only claims the existence+tier gate can verify; the
box makes a set-completeness claim it cannot, so E must build the check that can.

### 7.2 Sequencing

**E strictly after D**, and only if a real *closed-world subsystem* need appears — exactly the
disposition the grouping reconciliation already recorded (§4.3-E: "the honest home of the initial's
box … built WITH graph reach-back proving drawn-members == grounded-members"). D's membership/name gate
is a **prerequisite** (E's soundness reuses it, §5a); E adds enforcement + enclosure + caption on top.
Build order is unchanged through D:

`A (asset foundation) → B (image embedding) → C (flat diagrams) → D (badges, behind its small spike)` —
then, separately and later, **E (honest box)** gated behind: (1) a demonstrated closed-world need,
(2) the cluster-determinism spike (Part 4), and (3) its OWN adversarial pass on the enforcement
mechanism (7.3). D remains the honest stopping point absent that need.

### 7.3 RECOMMENDATION: E is NOT ready to plan alongside A→D — it needs its own adversarial pass first

**Plan A→D as the grouping reconciliation settled. Do NOT fold E into that plan.** E's completeness
mechanism should take a dedicated adversarial pass **before** it is planned, for four grounded reasons:

1. **It changes the adapter contract and fans out to every adapter** (E-1) — a design fork with its own
   blast radius (every step-18 adapter, the resolver's `(subject, claim)` agreement/conflict keys at
   grounding.py:910-1024), not a diagram-local decoration. That surface deserves attack.
2. **Its central promise rests on an unverifiable adapter-completeness assumption** (§2.3) — the box's
   "all members" is really "all members the enumeration query surfaced," which is fundamentally weaker
   than it sounds. Whether that weaker promise is worth the machinery is exactly the question an
   adversarial pass exists to stress (and the honest answer may be "no — ship D").
3. **It introduces the first non-`_validate_refs` diagram gate** (E-4, set equality) — a new checker
   with new failure modes (stale enumeration, cover-not-partition, empty enumeration) that should be
   attacked before it is trusted, the same way the base gate and D's extension were.
4. **It re-introduces cluster determinism** (Part 4) — a fresh identity-bearing unknown that must clear a
   hard spike gate; planning E before that spike would repeat the very "unverified layout on expected"
   mistake the grouping-adversarial pass escalated to REQUIRED-before-plan.

**Bottom line for the maintainer:** the box's honest promise ("all the members the *source* knows, as of
commit X") is buildable, but only by ENFORCING it — a new grounding capability plus the cluster topology
the badge deliberately avoided — and it must ALSO caption the source-vs-reality limit on the face of the
picture. There is no honest cheap box: disclosure-without-enforcement either lies out loud or degenerates
to a worse-than-badge rectangle. So build A→D now; treat E as a separate, later, heavier increment,
justified only by a real closed-world need and gated behind its own adversarial pass and the
cluster-determinism spike. If that need never appears, **the badge (D) is the honest place to stop.**

--- end of INITIAL (honest enclosing subsystem box, increment E) ---
