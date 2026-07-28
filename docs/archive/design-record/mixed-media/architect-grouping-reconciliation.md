# ops-architect — RECONCILIATION: honest grounded grouping (settles the form, the design, the cost)

Pipeline: optiquity-content-pipeline · main @ cc42c54 · read-only. Mode: RECONCILIATION (decision authority).
Settles `architect-grouping-initial.md` against `architect-grouping-adversarial.md`, on top of the DECIDED
base (`architect-reconciliation.md`) + amendment (`architect-amendment-reconciliation.md`). Base + amendment
are FIXED and not re-litigated. Every code claim re-verified at file:line THIS pass against the live tree
(paths are `pipeline/…`).

**Headline.** The adversary's blockers are accepted; they verified against code. But the fix is NOT to bolt
reach-back and disclosure machinery onto the bounding-box. **The box is the wrong shape.** The two blockers
(Q4 closed-world boundary, Q1 coupling Gestalt) are BOTH born of the *enclosure* — the hard edge around a
region. Drop the enclosure and keep the grounding, and both blockers dissolve *structurally* instead of being
papered over. I recommend the **lighter form: per-node badges keyed to the cited membership, with a mandatory
plain-text legend, and NO bounding box.** It delivers the honestly-deliverable part of grouping for a fraction
of the cost, needs no graph reach-back and no "N of M" disclosure, and shrinks the determinism unknown from a
new layout feature to a label-string confirmation. On sequencing I recommend **ship flat honest diagrams first
(increment C, already de-risked), badge grouping as a fast-follow increment D** — which is exactly what the
amendment originally recommended, now vindicated by the blocker findings.

---

## PART 1 — PLAIN ENGLISH (for the maintainer; read this at the gate)

### The lighter-vs-box recommendation, in everyday words

The proposal draws a **box** around the boxes that belong together — an "Auth subsystem" rectangle. The
adversary proved two ways that box lies while every citation checks out:

- **A box has an inside and an outside.** Drawing the "legacy" box around two old modules and leaving a third
  old module *outside* it makes the picture say "that third thing is modern" — a lie built purely by leaving a
  checked fact out. The box turned an *absence* into a *false statement*. (This is the exact "make it look
  cleaner than the source" distrust that killed the earlier `detail` dial, walking back one level down.)
- **A box says its contents cooperate.** Two things in one labeled rectangle read, to any human, as "these work
  together." But two modules in the same package need not talk to each other at all. The box invents a
  relationship the source never grounded — and it *erases* the honest signal that they're unconnected.

Here is the key realization: **both lies come from the rectangle itself — the enclosure — not from grouping.**
So drop the rectangle. Instead of boxing nodes, **tag each box with a small label chip** — a badge like
`[auth]` — that says "this one is a cited member of Auth." Same grounded information (every node shows its
checked group), but:

- **No inside/outside**, so there is no "the rest are NOT Auth" claim. A node with no badge just means "its
  group isn't shown here" — the same honest silence as an arrow you didn't draw. The boundary lie is gone
  because no boundary is ever drawn.
- **No enclosure**, so two same-badged things sitting apart and unconnected still read "unconnected" — the
  honest signal survives. The coupling lie is gone because nothing was wrapped together.

The badge form gets **almost all** the real reader value ("which subsystem is each thing in?") **honestly**,
and it skips the two most expensive pieces the honest box would have needed: reaching back into the source to
prove a box isn't missing a member, and a visible "showing 2 of 3 members" disclaimer. **My recommendation:
build the badge form; do not build the box.** The honest box is a genuinely bigger, later feature — build it
only if someone truly needs a *closed* "these are all and only the members" claim, and build it then with the
completeness machinery it actually requires.

### The settled honest promise for grouping (one sentence)

> **A node can show a subsystem badge only if "this node is a member of *Auth*, and *Auth* is a real named
> thing" is itself a checked fact — and the picture never draws a boundary, so it never claims who is left
> out or who cooperates with whom.** A plain caption states, in words, that a badge marks a cited group and is
> not a claim that badged things interact.

Two honest limits stated plainly, not hidden:

1. **The printed name rides the same trust as every other label.** "Auth" carries its own checked fact (a leaf
   label does not), so a *pure invention with no fact behind it is refused* — that much is a real gain. But the
   check confirms the fact *exists* at an honest confidence level; it does not read the fact's text, so it
   cannot mechanically prove the printed word "Auth" matches the source's word. That is the same trust the
   whole pipeline already places in every visible label. We do **not** claim a "higher bar" on the name's
   wording — that was an overclaim, and I drop it.
2. **The writer still chooses which attribute to badge by** (module? region? owner?). That choice shapes the
   reader's whole picture, so we make it **visible**: the diagram declares its one grouping axis, and the
   caption names it ("badges mark each node's cited **source module**"). We do not pretend this choice is
   removed — a mis-chosen (but individually true) axis can still bury an outlier, the same editorial residue
   that already exists when an author picks which arrows and sentences to include. We *acknowledge* that; we
   don't claim to close it.

### The two sequencing paths, and my recommendation (with honest cost)

**Path (i) — build grouping now, as one bigger diagram increment.** Flat diagrams and badge grouping ship
together as one release. Cost: the flat-diagram build (already de-risked) **plus** the badge build **plus** a
small-but-required prototype that must run *first* to confirm the writer reliably attaches the new membership
facts and that badges come out byte-identical every run. Risk: this ties the flat path — which is *ready to
plan today* — to the badge prototype. If the prototype turns up anything, the whole diagram capability waits,
including the flat part that had no reason to wait.

**Path (ii) — ship flat honest diagrams first, badge grouping as a fast-follow.** The flat diagram capability
(the base+amendment design: draw the checked list, one honest `tool` knob, no grouping) ships as increment C.
It is *already de-risked* — the amendment ran its spike and found no open questions. Badge grouping becomes a
separate increment D, planned right after, behind its own small required prototype. Because badges are purely
*additive* (a diagram with no badges is byte-identical to a flat one), sequencing D after C costs nothing in
rework — nothing is torn up or redone.

**My recommendation: Path (ii).** It is lower risk for the same total work, it keeps the ready-now flat
capability moving instead of holding it hostage to the badge prototype, and it *is the sequencing the amendment
already chose* — the amendment deferred grouping deliberately, and the blocker findings vindicate that call:
the box form the proposal reached for would have dragged back exactly the reach-back and disclosure machinery
the amendment cut. The badge form is the honest, cheap shape of that deferred grouping slot. **This is your
call** — if getting grouping into the very first diagram release matters enough to run the badge prototype up
front and accept a later first-diagram date, Path (i) is coherent and not dishonest, just slower to first
picture. On cost and risk, (ii) wins.

Honest bottom line: **badge grouping, not boxes; and ship it as increment D after the flat diagrams (C) that
are ready now.**

---

## PART 2 — LIGHTER FORM vs CONTAINER FORM, HEAD-TO-HEAD

Both blockers are properties of the **enclosure**. Q4 (closed-world boundary) needs a *hard edge* to have an
"outside"; Q1 (coupling Gestalt) needs a *common bounded region* to trigger the "these cooperate" reading
(the Gestalt "common-region" principle the adversary cited). Remove the enclosure — render each node's cited
membership as a **badge/annotation on the node itself** (a `[auth]` chip, or a fill tint) instead of a box
*around* nodes — and you keep the grounded claim (node ∈ Auth, cited) while making neither enclosure-born claim.

| axis | CONTAINER (bounding box) | LIGHTER (per-node badge) |
|---|---|---|
| **Q4 closed-world / boundary** | **Draws an affirmative false boundary** on omission: an omitted grounded membership puts the node visually *outside* a box it belongs in → "not a member" lie. A caption can't undo a perceptual enclosure. Needs graph reach-back OR "N of M" disclosure. | **No boundary drawn.** An omitted membership = no badge = "group not shown" — the *same* additive-absence posture an omitted edge already has (ratified: amendment §2.A(b) / initial §4b, verified: `_validate_refs` iterates refs that EXIST, ir.py:710). Dissolves to the accepted edge-omission residual. No reach-back, no disclosure. |
| **Q1 coupling** | **Strong** "these interact" Gestalt from the enclosed region; *erases* the honest "unconnected = no known interaction" signal (the adversary's PasswordHasher/OAuthProvider case: two non-interacting auth strategies read as cooperating once boxed). | **Weak-to-none.** Same-badged nodes sit apart, unenclosed; two unconnected `[auth]` nodes still read "unconnected." The honest missing-edge signal *survives*. Residual closed by the legend. |
| **Q3 name fidelity** | Same problem (name string unverified vs. fact — no value in ledger, ir.py:154-160). | Same problem. Form-independent — resolved once for both (Part 3). |
| **Q2 axis** | Same hidden-lever problem; a box *reframes the whole layout*, so a mis-chosen axis is more totalizing. | Same lever, but a badge *annotates* rather than reframes → a mis-chosen axis is a lighter visual commitment. Governed identically (declared axis + legend). |
| **Machinery** | `subgraph cluster_*` / `d2` containers (new layout topology) **+** reach-back OR "N of M" disclosure (Q4) **+** legend (Q1). The disclosure path is the deferred reduction machinery (amendment §2.H). | Per-node label/style decoration only (no new topology) **+** legend. Reuses the flat node/edge list unchanged; **no reach-back, no disclosure.** |
| **Determinism (identity-bearing)** | **New unknown:** cluster bounding-box + cross-cluster edge routing are where Graphviz non-determinism historically lives (adversary Q5 #2). A genuinely new layout feature the flat spike never exercised. | **Confirmation, not unknown:** a badge is a richer *label/fill* on the already-proven flat topology — no clusters, so none of the cluster-layout non-determinism surface. Shrinks the spike to "does a richer label perturb bytes?" |
| **Reader value** | Stronger "subsystem" visual — but that strength *is* the two lies (false boundary, false coupling). The extra value over badges is precisely the closed-world/cohesion claim the source doesn't ground. | Delivers the honestly-deliverable question ("which cited group is each node in?") in full. The value it lacks is value the pipeline can't honestly ship anyway. |

**RECOMMENDATION: the LIGHTER (badge) form.** It gets essentially all the *honest* grouping value for a
fraction of the machinery, and it dissolves both BLOCKERs structurally (no enclosure → no boundary claim, no
coupling claim) rather than buying them off with reach-back and disclosure. That is the maintainer's
simplest-honest north star exactly: **don't build the machinery to make an over-claiming shape honest — draw a
shape that doesn't over-claim.** The canonical rendering is a **badge/annotation chip** (additive per node); a
fill *tint* is an acceptable visual equivalent only when membership on the declared axis is *total* (every node
cited), because color-coding carries a mild "everything's colored, the rest are Other" pull that a badge does
not — when in doubt, badge.

Note this precisely fills the slot the amendment DEFERRED: amendment §2.C deferred "grounded-attribute
grouping," but reached only for the heavy *container/super-node/super-edge-quotient* member of that family. The
badge is the *lighter* member of the same family the amendment didn't separately weigh — same grounded value,
none of the container/quotient machinery. The reconciliation's contribution is to fill that deferred slot with
the badge, not the box.

**The honest bounded box is NOT cut forever — it is deferred with its true price.** A box makes one thing a
badge cannot: a *closed* "these are all and only the members" claim. That claim is only honest with graph
reach-back proving drawn-members == grounded-members (or a visible "N of M" disclosure). Build the box only if
a real closed-world-subsystem need appears, and build it *then* with that machinery — the same disposition the
amendment gave grouping originally (§2.C/§2.H).

---

## PART 3 — THE SETTLED HONEST DESIGN (badge form)

### 3.1 The membership + name model

Unchanged from the initial in its *grounding* shape; changed in its *rendering* (badge, not box):

- A **group** is a first-class cited entity. `groups: [{name, fact, tier, axis}]`. The NAME/existence claim
  ("there is a cited group *auth*") carries its own `fact`+`tier`. NEW vs the initial: the block declares a
  single `axis` (e.g. `axis: source-module`) — see Q2 (§3.5).
- A node's **membership** is a per-node cited claim: `group` + `membership_fact` + `membership_tier`.
- The **render** is a per-node **badge** (label chip / optional tint) keyed to the node's group — **never an
  enclosing `subgraph cluster_*` / container.** The node set, edge set, and layout are byte-for-byte the flat
  diagram; only each grounded node's rendered label/style gains the badge.

### 3.2 The exact gate additions (reusing `_validate_refs` ir.py:706-729 UNCHANGED)

Verified crown-jewel property still holds: `_validate_refs` (ir.py:706-729) reads only `ref.fact_id`,
`ref.tier`, `ref.where`, and `ledger[fact_id]["tier"]` — it is origin-agnostic (no notion of spans, edges,
nodes, badges, or boxes). `FactRef` (ir.py:361-372) carries exactly `(fact_id, tier, where)`; `where` is a pure
error-message label. So grouping needs **no new checker** — it needs new *sources of `FactRef`s* fed into the
existing one. (Grounding note: `FactRef`'s ONLY current construction site is ir.py:468 inside
`extract_fact_refs`; the badge gate adds NEW construction sites in the increment-D diagram-gate code and does
**not** edit ir.py's function or class. "Reuse the checker unchanged; add new call sites" is literal and
exact.)

The gate (runs at compose, over the structured node/edge/group list, BEFORE any compile — base §2.4):

```
# (unchanged) edges, as the flat spike proved
refs = [FactRef(e.fact, e.tier, where=f"edge {e.from}->{e.to}") for e in edges]

# (NEW) group NAMES — each declared group's name is a cited claim
for g in groups:
    require(g.fact is not None, f"group '{g.name}' has no citing fact")        # NAME coverage
    refs.append(FactRef(g.fact, g.tier, where=f"group '{g.name}' name"))

# (NEW) node MEMBERSHIPS — each badged node's membership is a cited claim
for n in nodes:
    if n.group is not None:
        require(n.membership_fact is not None,
                f"node {n.id} badged '{n.group}' with no citing fact")          # MEMBERSHIP coverage
        require(n.group in declared_group_ids, f"node {n.id} names undeclared group '{n.group}'")
        refs.append(FactRef(n.membership_fact, n.membership_tier, where=f"node {n.id} ∈ '{n.group}'"))

_validate_refs(refs, ledger)     # ONE call — the identical ir.py:706-729 check over ALL refs
# + name↔fact bijection (§3.4) ; + single declared axis (§3.5)
```

That is the whole gate change: **two new `FactRef` producers + two coverage `require`s + the bijection/axis
checks.** Deltas from the initial's §3.2, all *subtractive*:
- **No cluster-emission pass** (emitter does a per-node badge/style pass instead — §3.6).
- **No reach-back check** — Q4 is dissolved by the form (§3.3), so the gate acquires NO new graph read.
- **No "N of M" disclosure** — nothing is reduced (§3.3 property b).
- **Plus** the mandatory plain-text legend render (§3.5), verified backstop-safe.

### 3.3 Q4 — boundary-completeness, SECURED BY THE FORM (not by reach-back, not by disclosure)

The box's Q4 leak was: an omitted grounded membership draws the node *outside* a box → an affirmative false
"not a member" boundary. The badge form **draws no boundary**, so there is nothing to be outside of. An omitted
membership draws *no badge* — and an un-badged node reads "its group is not shown," exactly the additive-absence
posture an omitted edge already carries (verified: the gate's universe is the writer's cited refs, which EXIST —
ir.py:710; there is no "what grounded thing is missing" reach-back, and there never was for edges). So the
initial's "**no new completeness obligation**" claim — which was **FALSE for the box** (the adversary is
correct; I retract it for the box) — becomes **TRUE for the badge**, for the identical reason it is true for
edges. Completeness (property b) holds *unconditionally*: badging is strictly additive; no node/edge/badge is
dropped; nothing is reduced; the "unless reader-visibly disclosed" clause stays vacuous. The legend states the
convention explicitly ("an un-badged node's group is simply not shown"), converting even the residual reader-
inference to the same ratified class as inferring "no relationship" from an absent arrow. **Q4 dissolved — no
reach-back, no disclosure machinery.**

### 3.4 Q1 — coupling, SECURED BY THE FORM + a mandatory plain-text legend

No enclosure ⇒ no common-region Gestalt ⇒ the "these cooperate" reading is not manufactured by the drawing.
Decisively, the badge form **preserves the honest missing-edge signal** the box destroys: the adversary's
PasswordHasher/OAuthProvider pair (two non-interacting cited members of `auth`) sit apart and unconnected with
matching `[auth]` badges — reading "unconnected; both tagged auth," not "cooperating." The residual (a mild
"these go together" pull from a shared badge) is closed by a **mandatory, non-optional legend on every
badge-grouped diagram**: *"Badges mark each node's cited SOURCE MODULE; a badge is not a claim that badged nodes
interact, and an un-badged node's module is simply not shown."* One plain-text sentence discharges Q1
(coupling), Q4 (closed-world), and half of Q2 (axis) at once.

**Legend cannot trip the backstop — verified.** The raw-count backstop (ir.py:469-476) refuses when
`_DATA_FACT_RE.findall(body)` (the `data-fact=` substring count) exceeds captured span refs. The legend is
**plain descriptive text carrying no `data-fact` span**, so it adds 0 to the raw count and cannot false-trip.
Further, per base §2.4 the badge decorations and legend live in the **stored SVG asset** (or a plain caption
line), while the persisted IR body is `![alt](svg)` + normal grounded prose — so the legend is not even in the
data-fact scan's scope. The base §2.4 "no `data-fact` in the persisted body" moot is preserved. (This is the
ir.py:469-476 preservation the adversary required.)

### 3.5 Q2 — axis governance (visible + single + acknowledged residual); Q3 — name downgrade

**Q2 — the axis.** I retract/narrow the initial §2.4 "**derived, not authored freely**" claim: it proved
*structural* integrity (no dangling refs; name↔fact bijection; ≤1 group/node) and said nothing about the
*semantic* choice of *which* grounded attribute the writer badges by. Governance, three parts:
1. **Declared, single, per-diagram axis.** The `groups` block declares one `axis` value; every membership in
   the diagram is on that axis (mixed-axis badging is refused — deferred). This turns the hidden lever into a
   named, single-valued, reviewable declaration in the source. It is **not** a config knob (no dial added) —
   it is an authored, cited property of the one diagram.
2. **Reader-visible axis in the legend** (§3.4) — "badges mark each node's cited SOURCE MODULE" — so a
   module-badge can't be misread as ownership.
3. **Acknowledge, do not deny, the editorial residual.** A mis-chosen-but-individually-true axis can still bury
   an outlier (the adversary's `PaymentService`-as-region-peer case). The gate guarantees every badge is
   grounded; it does **not** guarantee the chosen axis is the most illuminating — the *same* editorial-selection
   residual that already exists for which arrows and which sentences an author includes. This design does **not**
   close it; it states it. (The initial's "identical bar, not a hole" lean was a rubber-stamp of the lever-class
   the amendment cut — corrected here to an explicit acknowledged residual.)

**Q3 — the name string: DOWNGRADE (drop the "higher bar"), do not derive.** Verified: `_validate_refs` never
reads a fact's value (ir.py:711-729), and `LEDGER_REQUIRED` (ir.py:154-160) has **no value field**; the only
source pointer, `traceability_anchor`, **may be `[]`** even for a valid EXTRACTED fact (ir.py:65). So there is
zero mechanical tie between the printed "Auth" and the fact's actual subject — "Authentication Subsystem" can
cite a prototype-module fact and pass. I pick **downgrade over derive**, tied to the north star:
- The dedicated citation is a *real* gain and is KEPT: a name must carry *some* fact at an honest tier, so a
  pure invention with no fact is refused (a leaf label carries none). We keep that TRUE claim.
- We DROP the "**higher bar**" / "**value the graph actually asserts**" language. The printed string rests on
  the **same visible-text-to-fact trust the pipeline places in every label everywhere** (node labels, edge
  endpoints, the visible text inside every `data-fact` span — amendment §2.A(c)). The group name is no
  different in KIND; claiming a higher bar on its wording while the mechanism is identical is the overclaim.
- **Name-from-anchor is NOT built now.** It requires a graph reach-back at compose to dereference the anchor to
  the source name, PLUS a fallback for empty anchors (ir.py:65) — heavier, not universally available, and it
  drags in the same reach-back class the badge form otherwise avoids entirely. Deferred as the "if subsystem-
  name spoofing proves a real problem" escalation, built *then* with the reach-back it needs.

Net: the badge increment acquires **zero new graph reads** — both Q4 (dissolved by form) and Q3 (downgrade)
avoid reach-back. That coherence is what makes it cheap *and* honest.

### 3.6 Q5 — uniform across tools + the REQUIRED spike

**Uniform, no per-tool flatten.** Badging is a per-node label/style attribute both `dot` (node `label`/
`fillcolor`/`xlabel`) and `d2` (node style) support natively — it does NOT depend on the cluster-layout engine.
Rule (fixing the initial §7 fork): if badge determinism ever fails for a *pooled* tool, badge grouping is CUT
**uniformly for all tools** until fixed — **never** silently flattened for one tool. A per-tool flatten would
make the `tool` knob change *whether badges appear*, the forbidden §5 blur (amendment §2.F: `tool` changes only
*how*, never *whether*). Grouping is emitted identically from the one gated list under either tool; a tool swap
cannot add, drop, or rename a badge.

**Spike is REQUIRED-before-plan (escalated from "recommend" to a hard gate — determinism is identity-bearing:
SVG bytes ARE identity, dispatch.py:121 / serialize.py:773-782).** But the badge spike is *materially smaller*
than the box spike would have been, because there are **no clusters** — so the cluster-bounding-box /
cross-cluster-edge-routing non-determinism surface (adversary Q5 #2) does not exist here. It must confirm only:
1. **Badge byte-determinism** under `dot` AND `d2` (render twice, byte-compare, WITH badges present) — a
   confirmation that a richer label/fill on the already-proven flat topology doesn't perturb bytes.
2. **New-field citation rate** — the writer attaches `group.fact` + `membership_fact` at the edge-citation
   reliability the flat spike measured (expected by shape; unmeasured for the new fields).
3. **Axis-selection behavior** (the adversary's Q6 ask) — does the writer pick a single sensible declared axis,
   or churn axes / mix them? Measured, not assumed.
Pass criteria: both tools byte-identical across runs with badges; gate REFUSES an uncited membership and an
uncited/synthesized name; writer emits a single declared axis. Fail on determinism ⇒ badge grouping does not
ship (uniformly) until fixed — an honest bounded outcome.

### 3.7 The three-property honesty proof, holding WITH badges

- **(a) SOUNDNESS — drawn ⊆ grounded.** Edges unchanged. Each badge is a per-node mark backed by
  `membership_fact` through `_validate_refs`; each group name backed by `group.fact` through `_validate_refs`
  (§3.2). An ungrounded badge/name is refused before compile. **Holds.**
- **(b) COMPLETENESS — grounded ⊆ drawn, unless reader-visibly disclosed.** Badging is strictly additive
  per-node decoration; every node the flat diagram draws is drawn, badges added to grounded ones; nothing is
  reduced; **no false boundary is drawn** (the box's leak). The "unless disclosed" clause stays vacuous;
  completeness is over the author's cited list, identical to the ratified edge posture (§3.3). **Holds
  unconditionally.**
- **(c) NO UNGROUNDED NON-EDGE CLAIM.** The non-edge claims a badge makes are exactly (i) membership (cited via
  `membership_fact`) and (ii) group name/existence (cited via `group.fact`) — both run through the existence+
  tier gate. The badge makes **neither** enclosure-born claim: no boundary (no closed-world), no common-region
  (no coupling). The legend neutralizes the residual axis/coupling reading. So the drawn non-edge marks assert
  exactly their citations and nothing more. **Holds** — and it holds *more cleanly* than the box, because the
  box's two extra claims (boundary, coupling) are simply never drawn.

The adversary's core thesis stands and is honored: the reused gate proves the OLD property (existence+tier) and
is blind to the box's FOUR new claims (name-fidelity, membership-correctness, boundary-completeness, coupling).
The badge form's resolution is not to make the gate see them — it is to **draw a shape that makes only the two
claims the existence+tier gate can actually verify** (membership existence, name existence), and to disclose
(not draw) the rest. Match the drawn claims to what the check can verify: that is the settlement.

---

## PART 4 — HONEST TRUE-COST + SEQUENCING

### 4.1 True cost of the settled badge increment (D) vs the flat increment (C)

Grounding for the cost claims (verified this pass): no emitter/gate/cluster code exists in the live tree
(`grep subgraph cluster|to_dot|to_d2|def gate` → nothing — the spike is gone); no `diagram` in `SECTION_TYPES`
(sections.py:102); no `diagram-styles/` registry yet. So C is genuinely unbuilt and D is genuinely additive to
it — neither rides on existing code.

**Increment C (flat diagrams) — already settled + de-risked (amendment §3):** pinned `dot` (+ optional `d2`) +
structured node/edge writer contract (extends compose.py:653-694) + the base hard gate UNCHANGED (§2.2) +
compile-to-stored-SVG with the `(tool, version)` pin + the `diagram-styles/` registry carrying the one `tool`
knob. Amendment §3: spike run, no open fork, plannable after A+B.

**Increment D (badge grouping) ADDS on top of C:**
- Grammar: optional `groups[]` block (with declared `axis`) + optional `group`/`membership_fact`/
  `membership_tier` node fields (extends the same compose.py:653-694 diagram path). All optional ⇒ an
  ungrouped diagram is byte-identical to flat C.
- Gate: 2 new `FactRef` producers into the existing `_validate_refs` (ir.py:706-729 UNCHANGED) + 2 coverage
  `require`s + name↔fact bijection + single-axis check (§3.2).
- Emitter: a per-node badge/style pass in both `dot` and `d2` (NOT cluster emission).
- Legend: one mandatory plain-text legend render, backstop-safe (§3.4).
- Q3: drop the "higher-bar" language — a claim/doc change, near-zero code.
- Spike (REQUIRED-before-plan, small): badge byte-determinism (both tools) + new-field citation rate +
  axis-selection behavior (§3.6).

**The honest re-price (resolving Q6).** The initial's "a few lines, strictly additive, no deferred machinery"
was FALSE **for the container** — closing the container's Q1/Q4 drags back the legend, the reach-back, and the
"N of M" disclosure the amendment deferred (the adversary is correct). It is **approximately true for the
badge**, honestly so — because the badge does not *make* the claims that required that machinery. Stated
without overclaim: **badge-D is a small, single-surface increment (grammar + gate extension + a badge emitter
pass + one legend line) that adds NO graph reach-back and NO reduction/disclosure machinery — but it is not
"free": it carries a required (small) determinism/citation spike, and its determinism is identity-bearing.**

**True-cost delta, badge-D vs a hypothetical honest container-D:** badge-D DROPS (relative to the honest box)
cluster/container emission, the cluster-determinism unknown incl. cross-cluster edge routing, graph reach-back,
and the "N of M" disclosure path. It KEEPS the gate extension, a (lighter) emitter pass, the legend, the Q3
downgrade, and a (smaller) spike. The honest box is a **separate, later, heavier** increment (call it E),
justified only by a real closed-world-subsystem need and built with reach-back or disclosure.

### 4.2 The two paths, priced (repeat of Part 1, with the technical hooks)

- **(i) Grouping now (one bigger increment).** Fold D into C. Cost = C + D + D's required spike, with the spike
  gating the *combined* release. Risk: couples the ready-now flat path to the unrun badge spike; any spike
  surprise delays the flat capability too.
- **(ii) Flat first (C), badge grouping fast-follow (D).** C ships as amendment §3 settled (no further spike).
  D is planned after, behind its own small spike. Because D's grammar is all-optional and additive (§4.1),
  sequencing D after C costs **zero rework**. This is the amendment's original recommendation (§2.C/§2.H
  deferred grouping), now vindicated: the blocker findings show the box form the proposal reached for would
  have re-opened the deferred machinery — deferring was right, and the badge is the honest cheap shape of the
  deferred slot.

**Recommendation: Path (ii)**, tied to cost/risk — lower risk for identical total work, keeps the ready-now
flat capability moving, honors "extend, don't edit" (D adds, never re-touches C), and matches the ratified
amendment sequencing. **Framed as the maintainer's choice:** Path (i) is coherent if first-release grouping is
worth running the badge spike up front and accepting a later first-diagram date.

### 4.3 Final build order for the WHOLE mixed-media design (base + amendment + grouping)

1. **A — Foundation** (base §2.6): content-asset store + intra-body path containment guard (blocking) + two
   provenance homes + `workspaces/workspace.template/assets/.gitkeep`. Needed by figures AND diagrams. *Plan now.*
2. **B — Figure/image embedding** (base §2.5): build the deferred asset loader (driver.py:100-119) + emit
   `--resource-path` / `--embed-resources --standalone`; image embed on html/docx/plain. Completes figure MVP.
   *Plan now.*
3. **C — Generated flat diagrams** (amendment §3): pinned `dot` (+ optional `d2`) + node/edge writer contract
   (extends compose.py:653-694) + base hard gate UNCHANGED (§2.2) + compile-to-stored-SVG with `(tool, version)`
   pin + `diagram-styles/` registry with the single `tool` knob. Rides on A (renders on md immediately; html/
   docx once B lands). De-risked; plan after A+B, **no further spike**.
4. **D — Honest BADGE grouping (fast-follow, behind its own small REQUIRED spike)**: grammar (`groups[]` +
   declared `axis` + per-node membership fields) + gate extension (2 `FactRef` producers into ir.py:706-729
   UNCHANGED + 2 coverage `require`s + name↔fact bijection + single-axis check) + per-node badge emitter (both
   tools, NOT clusters, uniform-cut rule) + mandatory plain-text legend (backstop-safe) + Q3 name downgrade.
   Spike: badge byte-determinism (both tools) + new-field citation rate + axis-selection behavior. Strictly
   additive to C (ungrouped = byte-identical to flat C).

**Deferred beyond D (with their true prices, so the doors aren't foreclosed):**
- **E — Honest BOUNDED-BOX / container grouping:** only if a real *closed-world* "all-and-only-members" need
  appears; built WITH graph reach-back (drawn-members == grounded-members per box) OR the "N of M" per-box
  disclosure (the deferred reduction machinery, amendment §2.H). This is the honest home of the initial's box.
- **Name-from-anchor mechanical derivation** (Q3 escalation): if subsystem-name spoofing proves real; built
  with the anchor-dereference graph reach-back + empty-anchor fallback (ir.py:65).
- **Multi-axis badging** (a node showing >1 axis): beyond the single-declared-axis MVP.
- Already-settled pipeline-wide deferrals (pdf/pptx/epub; live-mermaid on GitHub — dropped) unchanged.

### 4.4 Minor corrections carried from the adversarial pass
- The initial's "diagram is already the added type" (§6.1) is aspirational: `SECTION_TYPES` (sections.py:102)
  is `{prose, figure, table, callout}` — `diagram` is ADDED by increment C (a one-line change there, per the
  sections.py:101 comment), not present today. Grouping (D) sits on C. Corrected.
- The mandatory legend stays PLAIN, un-grounded text (no `data-fact` span) to preserve the ir.py:469-476
  backstop moot (§3.4). Enforced.
- `group_members_by_role` (folios.py:700) confirmed an unrelated folio function — no concept collision.

--- end of RECONCILIATION (grounded grouping) ---
