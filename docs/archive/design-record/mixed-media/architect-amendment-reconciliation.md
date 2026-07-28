# ops-architect — RECONCILIATION of the AMENDMENT (multi-tool + diagram knobs)

Pipeline: optiquity-content-pipeline · main @ cc42c54 · read-only. Mode: RECONCILIATION (amendment).
Settles `architect-amendment-initial.md` (§2.10–§2.14) against `architect-amendment-adversarial.md`
(F1–F7) into ONE final design, on top of the DECIDED base (`architect-reconciliation.md`, §2.0–§2.9).
The base is not re-litigated. Every code + spike claim below was re-verified at file:line this pass.

**Headline outcome.** The adversary was right on all three blockers, and the honest fix is
*subtraction*, not more machinery. The amendment's headline knobs (`detail`, `altitude`,
`connectivity`) each smuggle a different honesty violation past an edge-only gate; cutting them
closes all three holes **by construction** and makes increment C *smaller*. What survives is the
multi-tool capability with a **pinned default** and **one** honesty-safe knob (`tool`). The diagram
is drawn as the author's gated list, 1:1 — the same honesty the base already guaranteed.

---

## PART 1 — PLAIN ENGLISH (for the maintainer; read this at the gate)

### The final, honest picture — in everyday words

A generated diagram is still what the base settled: the author writes a list of boxes and arrows,
**every arrow cites a checked source**, and the pipeline refuses to draw anything that fails the
check. This amendment was supposed to add two things on top — let the pipeline pick the best drawing
program, and add a few "dials" to make diagrams prettier. The prettiness dials turned out to be the
problem: **every one of them could make the diagram quietly lie in a way the fact-check never sees.**
So we cut them. What is left is honest, and simpler than what was proposed.

**How the drawing tool gets chosen — you don't choose, and it's the same everywhere.** The framework
pins **Graphviz (`dot`)** as the default drawing program: the lightest, most reproducible one, and
the one the spike proved gives byte-for-byte identical pictures every run. Same source in, same
picture out, on every machine. A genre that wants a more polished, grouped look can pin **`d2`**
instead (also proven identical-per-run). There is an opt-in "**auto** — you pick for me" setting, but
it is off by default and only for locked, known machines, because "auto" makes the picture depend on
which programs happen to be installed — and that is exactly the kind of hidden, machine-to-machine
difference we don't want in the default. If the pinned program isn't installed when diagrams are
turned on, the pipeline stops with a **loud "install `dot`" setup error** — it does not silently ship
a half-diagram.

**Which dials survive — one.** After cutting the dangerous ones, exactly **one** dial remains:

- **Tool** — which drawing program (`dot` default, `d2` for a grouped look, `auto` opt-in). It only
  changes *how the same checked boxes-and-arrows are drawn*; it cannot add, remove, or rename a
  single box or arrow. It is honesty-safe because it has nothing to do with which facts exist.

Everything else — "altitude," "detail," "grouping," "direction," "size" — is **cut or deferred**
(details below). The two rough edges the spike found (too many tiny boxes; disconnected islands) are
handled honestly *without* a masking dial: **too-many-boxes is fixed by asking the writer to describe
the system at the level it can actually cite** (component-level statements instead of one-per-function
— still every box cited), and **islands stay honestly separate** when no source connects them. A true
40-box diagram beats a tidy 8-box one that invented the tidiness.

### The one promise, stated correctly: a diagram cannot lie by ADDING, by HIDING, or by GROUPING

The base promised "no arrow you didn't check." The honest promise actually has **three** parts, and
this amendment secures all three — by *removing* the levers that broke them, not by adding trust:

1. **It can't lie by ADDING.** No dial takes an arrow or a fact as input; the only source of arrows is
   the author's checked list, and the pipeline refuses any arrow with no citation. (Base guarantee,
   unchanged.)
2. **It can't lie by HIDING.** There is **no "detail" dial** that drops boxes to look tidier. The
   diagram draws the *whole* checked list, 1:1 — what's true is what's drawn. (This is the honesty the
   base had and the amendment had quietly given up.)
3. **It can't lie by GROUPING.** There is **no dial that draws a labeled container** ("Auth
   subsystem") around boxes, and **no dial that merges boxes into a new named super-box** ("Auth").
   Those labels are claims — *these things belong together, and this is their name* — that no source
   fact was ever checked for. We cut them. The only names on the picture are the author's own names
   for the endpoints of checked arrows.

Bottom line: **the tool is the pipeline's job (pinned, identical everywhere); there is one honesty-safe
dial; and the picture is exactly the checked list — nothing added, nothing hidden, nothing renamed.**
The honest way to make a diagram cleaner is to *write it at a level you can cite*, not to turn a dial
that hides the mess.

---

## PART 2 — THE SETTLED AMENDMENT

### 2.A The corrected honesty model — THREE properties, each secured BY CONSTRUCTION

The adversary's unifying thesis is correct and verified against the gate itself. The reused gate is
**edge-shaped**: `extract_fact_refs` inspects only bracketed Spans carrying `data-fact`
(ir.py:445-477); the single tier check is per-reference (ir.py:59-62); the spike `gate()` checks each
*edge* for coverage/validity/tier and builds `node_ids` **only** for edge-endpoint integrity
(harness.py:44, used at 58-61) — it **never inspects a node label and has no representation of a
container**. So an edge-only gate proves ONE property and is blind to two others. The honest guarantee
is three properties, and the settled design secures each by *cutting* the lever that broke it:

- **(a) SOUNDNESS — every drawn edge is grounded (drawn ⊆ grounded).**
  Secured by the existing gate, unchanged: coverage (no uncited edge, base §2.2) + tier-honesty
  (ir.py:59-62). Spike-proven 6/6 and gate-bites REFUSED (harness.py:142-152).

- **(b) COMPLETENESS — every grounded element is drawn (grounded ⊆ drawn), unless a reduction is
  reader-visibly disclosed.**
  Secured by **drawing the gated list 1:1** (base §2.2: "compile the list → dot → SVG", no
  subtraction) and by the fact that **no reducing knob exists** (`detail` CUT — 2.B). With no prune
  step, the "unless disclosed" clause is vacuous at MVP-C: there is nothing to disclose because nothing
  is dropped. Completeness holds *unconditionally*. (If a reduction knob is ever added later, it MUST
  carry a reader-visible "showing N of M" caption line — the F1(b) floor; provenance-only is invisible
  and insufficient. Deferred, not MVP-C.)

- **(c) NO UNGROUNDED NON-EDGE CLAIMS — containers/super-node names assert nothing a fact didn't.**
  Secured by an **empty projection layer**: no altitude-rename, no super-node partition, no
  group-label container (all CUT — 2.C). The only nodes are the author's cited-edge endpoints (base
  §2.2); the only edges are cited. The projection synthesizes zero new names, partitions, or
  containers. (The base's node-label fidelity — a label faithfully names a cited-edge endpoint — is the
  same visible-text-to-fact posture the pipeline relies on everywhere, e.g. the visible text of a
  `data-fact` span; it is unchanged and out of this amendment's scope. What the amendment MUST NOT do —
  and now does not — is add a *machine-synthesized* name/partition/container the author never grounded.)

The elegant part: all three are secured by **subtraction**. The amendment tried to bolt on a
"gate → project → re-gate → compile" pipeline; cutting the projection collapses it back to the base's
"gate → compile," which is where soundness+completeness already lived. Closing the holes makes the
build *smaller* (F7).

### 2.B F1 (BLOCKER, honesty) — RESOLVED: `detail` is CUT entirely

**Verified:** the gate has no notion of "what grounded thing is missing" — `extract_fact_refs`
iterates spans that EXIST (ir.py:460-468); the spike `gate()` iterates `edges` that EXIST
(harness.py:45). Re-gating a *pruned* list passes trivially — omission is invisible to the gate by
construction. The amendment made `detail: medium` the framework **default** (initial §2.11a), so the
zero-touch author would ship a diagram that silently dropped grounded structure (the adversary's
`PaymentService → LegacyBillingGateway` case). That is the maintainer's primary distrust — a knob that
makes the system look cleaner than the source — realized at the default.

**Resolution (simplest honest):** **CUT `detail`.** No prune knob ships. Rationale over the "keep it
non-default + visible-disclosure-floor" alternative: (1) simplest-honest — a knob that can only ever
hide true structure earns its place only if there's a real need, and there is none demonstrated;
(2) it is redundant with authoring-altitude (below); (3) keeping it, even disclosed, adds machinery
(the "N of M" caption path + the pruned-node record) that fights F7. Over-granularity is instead fixed
where it honestly belongs — **at authoring**: the writer is prompted to ground the list at the altitude
the genre wants (component-level statements, each cited), exactly as F4 puts island-connection back
into authoring. A too-big diagram at the authored altitude is an **honest signal** that the source
really has that many relationships; hiding them is the dishonest move. Retires initial PART 5 Q1: it
was not "honest-but-worth-a-note"; defaulted omission is a promise violation.

### 2.C F2 (BLOCKER/SERIOUS, honesty) — RESOLVED: `altitude` and `connectivity` are CUT as knobs; the mechanical forms are DEFERRED

**Verified:** a container and a super-node are **structurally outside the gate's ontology** — the spike
`gate()` never reads a node label and has no cluster concept (harness.py:33-62). So an
`altitude=component` collapse invents a **partition + a new name** ("Auth"), and `connectivity=group`
invents a **labeled container** ("Observability subsystem") — both are membership/naming claims the
edge-only gate has **no citation slot for**. "Reuse the identical gate" (initial §2.11c) is insufficient
by construction, not merely under-specified.

**Resolution (airtight AND simplest):** for MVP-C, **CUT altitude and connectivity as knobs.** The
projection layer is **empty** — the gated list is drawn flat, 1:1. This secures property (c) trivially
(nothing is synthesized) and needs zero new machinery. Between the task's two options — restrict to
MECHANICAL-only, or extend the gate to ground membership/naming — **I pick mechanical-only, and defer
it**, because:

- The clean mechanical-and-grounded form of altitude/grouping is *group-by-a-grounded-node-attribute*
  (e.g., collapse/box nodes by the source module each came from — a real EXTRACTED graph attribute;
  super-node/container label = the grounded module name, not a synthesized "Auth"; super-edges = the
  quotient of grounded edges, inheriting citations; completeness preserved because every member is
  shown inside its group). This is honesty-safe — but it requires **extending the node contract to
  carry a grounded group attribute AND extending the gate to check that attribute's citation** (F2
  option a). That is *more* machinery, which fights F7 and the north star.
- The lighter "mechanical join of member labels" container (F2 option b) still needs an author-declared
  partition, and even a bracket carries a "these belong together" reading the adversary correctly
  refused to wave away. It asserts more than a flat draw does.

So MVP-C ships the flat 1:1 draw (no grouping); the grounded-attribute grouping is a **scoped future
increment** *if* real diagrams prove unusably granular after authoring-altitude is exhausted — built
then with the extended gate, never speculatively. **Islands stay honestly separate** (no source links
them → no link is drawn); that is the honest answer, not a defect.

### 2.D F3 (BLOCKER, determinism/identity) — RESOLVED: pinned `dot` default, `auto` opt-in, degrade path CUT

**Verified identity chain:** asset bytes enter deliverable identity **only** by content hash —
`RenderInputs.assets: tuple[(path, content-hash)]` (dispatch.py:121), folded into the serialize
preimage as "every asset by CONTENT hash" (serialize.py:773-782); `tool_bundle` pins pandoc and
nothing diagram-related (serialize.py:810-815). So the SVG's bytes ARE identity. `tool=auto`
(initial §2.10b/§2.11a) keys those bytes on the **ambient install-set** — different per machine → same
source, different identity. The amendment's "precisely base §2.4's version-bump" is false: a pinned
version is identical everywhere; an install-set is not.

**Resolution:**
- **Default `tool = dot`, pinned** (lightest + the deterministic hierarchical engine — researcher
  §2.1; spike-proven byte-identical, harness.py:88-95). Same gated list + same style (`tool=dot`) +
  pinned dot version → **same SVG bytes on every machine.** The `(tool, version)` pin enters the
  author-time compile provenance (extends base §2.4), NOT the serialize preimage — an env change
  re-mints on the next *re-compose*, identical in shape to base §2.4's version-bump.
- **`auto` is explicit opt-in only**, documented as "for locked/known environments; makes identity
  environment-dependent." It never fires by default, so the ambient install-set never leaks into the
  default identity.
- **CUT the degrade path (initial §2.10d).** A missing renderer for an enabled increment-C run is a
  **loud setup error** — the base already treats the diagram binary as a pinned build dependency of C
  (base §2.5). No silent "ship the source + note" body variant (it produced a *different composed body*
  per machine → divergent identity, worse than F3a). This deletes the note machinery, the source-block
  body variant, and the degrade-provenance record — a real simplification (F7). Resolves initial PART 5
  Q3.

### 2.E Fold-ins

- **F4 — RESOLVED: `connectivity=seek-grounding` is CUT.** It re-invokes the LLM writer mid-compile to
  hunt a new fact — a **generation step**, not a deterministic projection; it reintroduces LLM
  nondeterminism into the identity-bearing compose step (breaking base §2.4's "compile is a
  deterministic function of the gated list"). Genuinely connecting two islands is **authoring work** —
  it belongs in the writer's grounded list on the next authoring pass, through the normal gate. (Moot
  anyway once `connectivity` is cut wholesale — 2.C. Resolves initial PART 5 Q4.)
- **F5 — RESOLVED: the final knob set is ONE (`tool`).** See 2.F. Every candidate that isn't honesty-safe
  by construction *and* earns its place against a good default is cut or deferred.
- **F7 — RESOLVED: the honest fixes make increment C SMALLER.** See 2.J.

### 2.F The FINAL knob set (one knob; each honesty-safe by construction)

| knob | what it does | type | default | home | why honesty-safe BY CONSTRUCTION |
|---|---|---|---|---|---|
| **tool** | which program compiles the SAME gated list to SVG | enum `dot`\|`d2`\|`auto` | **`dot`** (pinned) | `diagram-styles/` referenced registry (2.K) | it is a **compile target**, not an edge source; `to_dot`/`to_d2` both emit from the identical node/edge list (harness.py:65-78) — a tool swap cannot add, drop, or rename an edge. `dot`/`d2` both spike-proven byte-deterministic per machine; pinning the *selection* (not `auto`) makes identity machine-independent (2.D). |

**CUT knobs** (each because it broke a honesty property, not merely for count): `detail` (F1 — hides,
property b); `altitude` (F2 — synthesizes partition+name, property c); `connectivity` incl. both
`group` (F2 — container label, property c) and `seek-grounding` (F4 — nondeterministic generation).

**DEFERRED knobs** (honesty-safe, pure layout/rendering, no demonstrated MVP-C need): `direction`
(ship `TB` baked in, per the spike's `rankdir=TB`, harness.py:66; add `LR` when a concrete genre needs
it); `size` (add `fit-width` when a target actually requires page-fit). Each is a one-line
`_schema.yaml` add later (2.I).

### 2.G Multi-tool selection (KEPT, with the selection pinned)

The multi-tool *capability* is sound and KEPT — the spike proved **both** `dot` and `d2` compile the
gated list to byte-deterministic SVG (harness.py:85-108; renders twice, compares bytes). The fix was
never to drop a tool; it was to **pin the selection**:

```
tool = style.tool                    # default 'dot' (pinned) — same bytes everywhere
  if style.tool == 'auto':           # explicit opt-in only, locked environments
      tool = probe-and-pick(kind, installed)   # env-dependent identity, accepted knowingly
  if the chosen tool is not installed (increment-C enabled) -> LOUD setup error   # no silent degrade
```

Simpler than the amendment's fallback chain (initial §2.10b): with a pinned default there is no
per-diagram fallback walk to reason about. Mermaid stays OUT of the grounded pool (base §2.3; initial
§2.10e) — conceded, not re-litigated.

### 2.H CUT vs KEPT vs DEFERRED (one glance)

- **KEPT:** the base hard gate (unchanged); the gated list drawn **1:1** (no projection); the
  multi-tool pool `{dot, d2}` (both deterministic); the `tool` knob (pinned `dot` default / `d2`
  selectable / `auto` opt-in); the `diagram-styles/` referenced-registry home (2.K); posture/caption on
  the section (initial §2.11d, conceded); mermaid out of the grounded pool.
- **CUT:** `detail` (F1); `altitude` as a knob (F2); `connectivity` incl. `group` and `seek-grounding`
  (F2/F4); the no-renderer **degrade path** + its note/source-block/provenance machinery (F3); the
  amendment's "project → re-gate" layer (nothing to project → nothing to re-gate).
- **DEFERRED:** grounded-attribute grouping (the honest mechanical altitude/grouping form, with the
  extended gate — 2.C), if authoring-altitude proves insufficient; `direction` beyond `TB`; `size`; the
  reduction-with-visible-disclosure knob (only if a real need appears, with the mandatory "N of M"
  floor).

### 2.I One-file-change check (extends base §2.9)

| change | files touched | verdict |
|---|---|---|
| Add a diagram tool (e.g. PlantUML later) | ONE — the diagram-compiler capability table (probe + emit-DSL fn); optionally +1 line in `diagram-styles/_schema.yaml` `tool` enum. Author side unchanged. | PASS |
| Add a diagram-style | ONE — `diagram-styles/<id>.md` (content-kinds precedent, m1.py:178) | PASS |
| Add a deferred honesty-safe knob (e.g. `direction=LR`) | ONE line in `_schema.yaml` enum (+ compiler consumes it, where the projection lives) | PASS (structural add = one line) |
| Wire the registry itself | ONE row in `REF_ATTRIBUTE_TARGETS` (m1.py:178-shaped, a framework file) | one-time capability cost, per base §2.9 |

Base §2.9's honesty carries: *values* are one file; the *capability* is the multi-file increment-C
build, paid once.

### 2.J Increment-C scope — SMALLER than the amendment (F7, restated)

Increment C now contains: the pinned `dot` binary (loud-missing) + the optional `d2` binary (loud only
when a style selects it) + the structured node/edge writer contract (extends compose.py:653-694) + the
**base hard gate, unchanged** (§2.2) + compile-to-stored-SVG (base §2.4, extended only to pin
`(tool, version)`) + a **trivial** tool selector (pinned default; `auto` opt-in probe) + the
`diagram-styles/` registry seeded with the one `tool` knob and a framework `default.md {tool: dot}`.

Dropped vs the amendment: the `detail` prune projection; the `altitude` quotient projection; the
`connectivity`/container logic; the `seek-grounding` LLM round-trip; the fallback chain (pinned default
replaces it); the degrade note/source-block/degrade-provenance; **and the entire "project → re-gate"
stage** (the list is drawn as authored, so the single gate on the author's list suffices). C is
materially smaller and strictly more honest.

### 2.K Home + orthogonality (KEPT — verified)

- **Home:** the `diagram-styles/` **referenced registry** (the `content-kinds` precedent, verified at
  **m1.py:178** `("sources","content_kind"): "content-kinds"`), NOT a 10th matrix dimension
  (DIMENSION_COLLECTIONS at m1.py:133 has nine; content-kinds is absent → it's a referenced registry).
  The amendment cited m1.py:169 (actually the `voices` row); the correct content-kinds row is 178 — a
  harmless slip, the precedent stands. The §12.5 override loss is real and correctly priced:
  `_override_from_bind` requires `dimension in DIMENSION_COLLECTIONS` (overrides.py:151); diagrams don't
  need per-run uniform tuning at MVP. **Fixed 3-source selection cascade** (section `diagram-style=`
  ref > Format `section_schema` default > framework `default.md`); **no 4th/inline override grammar** —
  refinement is selection-by-ref only (the correct fork-avoiding cut). Pragmatic planner note: with a
  single surviving knob, MVP-C MAY implement `tool` as a Format `section_schema` default first and
  promote to the full registry when the second honesty-safe knob lands — the registry is the ratified
  permanent home either way; this keeps MVP-C minimal without changing the design.
- **Orthogonality (KEPT, conceded):** `posture` (grounded/illustrative) and `caption` stay **on the
  section** (base §2.2 + the pandoc `implicit_figures` caption path), not in the style bundle. `posture`
  is the only gate-touching lever, lives on the section, and is monotone-toward-disclosure (can only
  make a diagram look *less* guaranteed). The style registry holds presentation only. No blur.

---

## PART 3 — RECOMMENDATION

**Yes — the whole mixed-media design (base + this settled amendment) is ready for the planner.** The
base figure MVP was already plannable; the diagram increment's spike has been run and de-risked (gate
holds; both tools deterministic), and the honesty holes that would have blocked it are now closed by
subtraction. There is no remaining open design fork — the three blockers are resolved, the knob set is
one honesty-safe dial, and the scope is smaller than proposed.

**Build order (foundation → figure/image → diagram-with-honest-knobs):**

1. **Foundation (A)** — content-asset store + intra-body containment guard (base §2.6b, blocking) +
   the two provenance homes (base §2.6a) + `workspaces/workspace.template/assets/.gitkeep`. Needed by
   figures AND diagrams. *Plan now.*
2. **Figure / image (B)** — build the deferred filesystem asset loader (driver.py:100-119) + emit
   `--resource-path` / `--embed-resources --standalone` in the Presentation lowering; image embed on
   html/docx/plain. This completes the figure MVP. *Plan now.*
3. **Diagram with the honest tool knob (C)** — pinned `dot` (+ optional `d2`) + the structured
   node/edge writer contract + the base hard gate (unchanged) + compile-to-stored-SVG with the
   `(tool, version)` pin + the `diagram-styles/` registry carrying the single `tool` knob and framework
   `default.md {tool: dot}`. Rides on A (renders on md immediately; on html/docx once B lands). The
   spike has de-risked it; **plan it right after A+B** — no further spike required.

Net: approve the settled model; plan A → B → C in order. C carries exactly one honesty-safe knob
(`tool`, default pinned `dot`), draws the gated list 1:1, and cannot lie by adding, hiding, or grouping.

--- end of RECONCILIATION (amendment) ---
