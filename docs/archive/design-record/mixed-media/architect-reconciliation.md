# ops-architect — RECONCILIATION: mixed-media documents (diagrams + image assets + captions)

Pipeline: optiquity-content-pipeline · main @ cc42c54 · read-only. Mode: RECONCILIATION. Resolves the
INITIAL proposal against the ADVERSARIAL critique into ONE settled design. Every code claim below was
re-verified at file:line this pass. Where I overturn the initial, I say so in plain words.

Headline: I **overturn the initial's two central choices** — native-mermaid as the default, and
"prompt+advisory" grounding — and adopt the adversary's compiled-image + mechanical-grounding model.
I **keep** the initial's placement decision (a `{type=…}` heading in the one outline) and its lane
analysis (parts/folios). The result is smaller in *concepts* than either pass, and honest about cost.

---

## PART 1 — PLAIN ENGLISH (for the maintainer; read this at the gate)

### What a user actually does

To put an **existing picture** in a document, the user writes one heading in the same outline they
already write prose in, and drops the image on the line under it:

```
## Throughput on the v2 path {type=figure}

![Throughput doubled after the v2 cutover](assets/throughput.png)

The v2 path sustains [twice the throughput]{.EXTRACTED data-fact="f4"} of v1 [@s2].
```

To put a **generated diagram** in a document (a later increment — see MVP below), the user writes a
heading and lists the boxes and arrows as grounded statements; the pipeline *draws* it:

```
## System architecture {type=diagram}

- Gateway routes to Auth   [because the gateway forwards auth]{.EXTRACTED data-fact="f1"}
- Auth calls Billing       [billing is checked on auth]{.EXTRACTED data-fact="f2"}
```

There is still **one template** — the same outline, the same `{type=…}` marker the framework already
uses for prose/figure/table/callout. No second kind of template, no "diagram file," no "which do I
use?" fork. That part of the initial proposal was right and I keep it.

### How we guarantee a diagram cannot lie (this is the whole ballgame)

The product's one promise is: *a fact only looks like a fact if it was checked against the source.*
The initial proposal broke that promise for diagrams. It drew diagrams as a `mermaid` code block, and
the pipeline **never looks inside a code block** — so an AI could draw an arrow between two boxes that
no source supports, and it would ship looking exactly as authoritative as the checked sentence next to
it. The initial's answer was "we'll tell the AI not to, and a reviewer might catch it." That is exactly
the honor-system the pipeline was built to *not* rely on for facts. **I reject it.**

The settled rule: **a generated diagram is not a picture the AI draws freehand — it is a list of boxes
and arrows, and every arrow must cite a checked source before the diagram is drawn at all.** The
pipeline reads that list, runs each arrow through the *same* source-check it already runs on every
sentence, and only then draws the picture (as a normal image). An arrow with no citation, or a citation
to a source that doesn't say that, is **refused** — the document does not ship. This is a hard stop,
not a warning. A diagram that genuinely isn't making source-claims (a conceptual sketch) is allowed too,
but it must be **visibly stamped "illustrative — not source-checked"** so no reader mistakes it for
verified fact. Either way, an invented arrow can never ship dressed as a fact.

### Which tool we add, and why

We add **Graphviz** (`dot`) — one small, standard program. Why Graphviz and not Mermaid (which the
initial centered):

- **It renders everywhere.** Mermaid only shows up as a live diagram on GitHub; in **Word, HTML, and
  PDF — three of your four outputs — it comes out as raw code**, which is broken-looking. Graphviz
  turns the diagram into a normal image (`.svg`) that embeds in *every* output.
- **It's cheap.** Graphviz is a single program with no hidden weight. Making Mermaid render in Word
  would drag in a headless web browser (Chromium) — a heavy, network-fetching dependency.
- **It can't lie undetected.** Because we drive Graphviz from the checked box/arrow list, the drawing
  is exactly the checked list — nothing more. Mermaid is freehand text we'd have to *guess* the meaning
  of.
- **It's reproducible.** The same input yields the same image (with the version pinned), so the
  pipeline's "same input, same bytes" guarantee holds. Mermaid randomizes its output by default.

This also honors the mission, which already asked for **"deterministic charts from code"** produced
**"via code execution"** (mission.md:232, 301) — i.e. *draw it by running a program*, not paste a live
code block. The initial quietly departed from that; I put it back. Mermaid is **dropped entirely** —
keeping both a "mermaid" path and an "image" path would recreate the very "two kinds, which do I use?"
confusion you rejected, just one layer down.

### What renders where (honest)

| Output | Existing image (figure) | Generated diagram | Caption |
|---|---|---|---|
| **Markdown → GitHub / artifacts** | renders (served by path) | renders (image by path) | shown as a line/alt text |
| **HTML** | renders once the asset loader is built | renders (embedded image) | real caption, free |
| **Word (docx)** | renders once the asset loader is built | renders (embedded image) | real caption, free |
| **Plain text** | shows the caption/alt text only (by nature) | caption/alt text only | text only |
| **PDF / PowerPoint / EPUB** | deferred (pipeline renders none of these yet) | deferred | deferred |

The one honest catch: **images in Word/HTML need a piece of plumbing that isn't built yet** — a
file-loader that today deliberately crashes (it was postponed to "step 29"). Word/HTML image support
means **building that loader**. It is not "free," and the initial oversold it as near-free. On plain
Markdown/GitHub, images work by simple file reference with no new plumbing.

### The honest first version (MVP) vs. what's deferred

- **MVP = existing images + captions, on all four internal outputs (Markdown, HTML, Word, plain).**
  This is the "existing image assets + captions" three-quarters of the feature. It needs: real image
  support on the `figure` slot, a small **asset store** for the picture files, a **safety check** that a
  document can't reach across into another client's files, and the postponed **file-loader** so images
  embed in Word/HTML. No new diagram program, no grounding-gate risk (an existing image the client
  brought is honest as "an included illustration; the facts are in the cited prose next to it").

- **Deferred one step: generated diagrams.** This is the headline but the risky part — it needs the
  Graphviz program, the box/arrow authoring format, and the hard grounding-gate. Before we plan it, I
  recommend a **small prototype** ("does the AI reliably produce a checkable box/arrow list, and does it
  compile to a clean image?") to de-risk it. Shipping generated diagrams *without* the grounding-gate is
  the one thing the pipeline's charter forbids, so we build the gate first or we don't ship diagrams.

- **Deferred further:** rendering diagrams natively on GitHub as live Mermaid (dropped — we use images
  instead); PDF/PowerPoint/EPUB (already deferred pipeline-wide).

Plain bottom line: **the existing-images half is ready to plan now; the generated-diagram half needs a
one-off prototype spike first.**

---

## PART 2 — THE SETTLED TECHNICAL MODEL

### 2.0 What I keep from each pass

- **Keep (initial):** `{type=…}` on a heading is the single declaration site, in the one outline
  (verified-clean by the adversary; not re-litigated). The reusable "this genre has a diagram/figure
  slot" = a Format `section_schema` **type-axis** rule; the per-doc "here, about X" = the authored
  heading. Same vocabulary, two ends of machinery that already exists. Parts/folio lane analysis
  (initial §6) stands.
- **Overturn (initial):** native-mermaid default → **compiled image (Graphviz)**; "prompt+advisory"
  grounding → **mechanical, blocking** grounding; "one line + free" framing → **stated multi-file,
  partly-deferred capability cost, up front**.
- **Adopt (adversary):** compiled-image model; structured node/edge grounding; the two unbuilt gaps
  (containment guard, asset loader) priced honestly; the degradation advisory **deleted** (compiled
  image makes it evaporate).

### 2.1 The section-type / figure model — `diagram` STAYS a distinct type (decision 3)

`SECTION_TYPES` today = `frozenset({"prose","figure","table","callout"})` (sections.py:102) — no
`diagram` yet; the initial's snippet was a proposal. Resolution:

- **`figure`** = an image slot whose bytes are **BROUGHT** (an existing client asset). Body = native
  `![caption](assets/…)`.
- **`diagram`** = an image slot whose bytes are **GENERATED** by the pipeline from a **grounded box/arrow
  source**. Body-in = the structured node/edge list; body-out (post-compose) = `![caption](assets/…svg)`.

**Why keep `diagram` distinct rather than collapse it into `figure` (overruling the adversary's
strongest simplification, on the merits).** The adversary argued a compiled diagram is "just a figure
with a generated image — provenance, not type — so the sections.py:102 add is unnecessary surface." The
render output *does* converge (both are embedded images), and that convergence is exactly what buys us
one rendering mechanism and zero "inert on binary" gap. But the **authoring contract and the grounding
mechanism genuinely differ**, and *that* is a content-KIND distinction, not mere provenance:

- `figure`'s writer/author supplies a **path**; the bytes already exist; grounding is the adjacent
  cited-prose convention (academic-paper.md:54, "figures carry the data, prose carries the reading").
- `diagram`'s writer supplies a **grounded node/edge list**; the pipeline **generates** the bytes; the
  grounding is a **mechanical pre-compile gate** over that list.

Collapsing them would force ONE section type to carry TWO writer contracts ("give me a path *or* a
node/edge list") — a hidden mode switch inside one type, which is *less* orthogonal, not more. Two clean
types (one contract each) beat one type with a mode flag. So the one-line add at sections.py:102 **earns
its place**: it selects a distinct writer contract + a distinct grounding path, not just a different
image origin. `role` and `type` remain orthogonal (parsed independently, sections.py:255-270; a section
can be `{#architecture type=diagram}`).

Free properties confirmed this pass: the `type` set is fail-closed (an unknown `type=` raises
`UnknownSectionTypeError`, sections.py:261-266 — a `{type=diagram}` composed before the add is refused,
never a silent mistype); the compose envelope check (`parse_writer_output`, compose.py:653-694) only
asserts non-empty Markdown, so a rewritten `![alt](svg)` body passes untouched.

### 2.2 The grounding mechanism (decision 1 — the BLOCKER, resolved to a HARD gate)

**Verified failure the initial left open:** the tier-honesty gate (`extract_fact_refs`, ir.py:445-477)
inspects **only bracketed Spans carrying `data-fact`**; the single tier check (ir.py:59-62) subsumes
"unknown fact-id" and "lead asserted as fact." Nothing in ir.py is fence/CodeBlock-aware. A mermaid
fence (or any opaque image) is therefore never grounded. `parse_writer_output` (compose.py:653-694)
passes it through; Review-2 is advisory and never blocks (dispatch.py:316-317). So the initial's "the
prose cites; the fence restates" is hope, not enforcement. **Rejected.**

**Settled mechanism — "constrain, then compile-check," as a BLOCKING gate (not advisory):**

1. A `type=diagram` section's writer output is a **structured node/edge list** (a strict, parseable
   grammar — NOT free-text DSL), where **every edge carries a `data-fact` id** (and nodes may).
2. Before any picture is produced, compose runs a **hard gate** over that list:
   - **(a) tier-honesty**, reusing the EXISTING check (ir.py:59-62 / the `extract_fact_refs` tier
     logic): each edge's `data-fact` must be a known fact-id at the ledger-honest tier. This is the same
     mechanical check the IR gate already is — **no new "parallel machinery," no fuzzy label matching.**
     The adversary's own point: fuzzy matching was an artifact of choosing free-text mermaid; a
     structured list makes it an exact check.
   - **(b) coverage**: every edge in the list must carry a citation — **no uncited edge may exist.**
   - **Failure = refusal** (a typed `SchemaViolation`-class error, the pipeline's existing loud-refuse
     posture), not a warning.
3. Only after the gate passes does deterministic code compile the list → `dot` → SVG.

An invented arrow therefore cannot ship as fact: it either carries no citation (refused by coverage), a
fabricated fact-id (refused by tier-honesty), or a real id at a dishonest tier (refused by tier-honesty).

**The honest escape hatch (kept, minimal):** a diagram that is genuinely *not* making source-claims may
be authored as **illustrative** — but then it MUST render with a visible, non-optional "illustrative —
not source-checked" stamp (the adversary's option (b), and the maintainer's "if you can't guarantee it,
don't let it look guaranteed"). This is **one section type with a declared posture** (grounded vs
illustrative), both compiled and rendered identically — NOT a second machinery fork. MVP-C default is
**grounded + blocking**; whether uncited edges hard-refuse or auto-downgrade to illustrative is a detail
for the spike to settle.

**Why this is DEFERRABLE (not MVP-blocking for the whole feature) but BLOCKING for diagrams:** brought
`figure` bytes are author-supplied, not LLM-fabricated relationship-claims, so figures ship honestly on
the cited-prose convention with no new gate. Generated diagrams are the only surface that needs this
gate — so they wait behind it. The gate MUST block; advisory-only is rejected.

### 2.3 Rendering mechanism + tool (decision 2 — Graphviz, mermaid dropped)

**Default and ONLY diagram mechanism: pre-rendered image via Graphviz `dot`.** Overturns the initial's
native-mermaid default. Grounded in the verified tradeoff:

| | native mermaid fence | compiled image (Graphviz `dot` → `![alt](x.svg)`) |
|---|---|---|
| md → GitHub/artifact | renders | renders (path served) |
| html5 (prod) | inert `<pre class="mermaid">` | renders (embed) |
| docx (prod) | inert code paragraph | renders (container embed) |
| plain (prod) | literal text | alt text |
| cheap compile-gate | **none** (needs Chromium) | **`dot -Tcanon`/`nop`** (no browser) |
| deterministic | render: no (random IDs) | `dot` yes (pin version) |
| groundable | no (opaque) | yes (structured source) |
| new binary weight | none for md; **Chromium** for binary targets | **one light native binary** (no browser/JVM/Node) |

Native mermaid works on **1 of 4** production writers and is inert on `docx`/`html5` (first-class
internal writers, not deferred). Graphviz renders on all four and converges with the figure path.
Graphviz is the lightest option (researcher-diagram-tools §2.1/§5): single native binary, SVG/PNG/PDF
with no browser/JVM/Node; D2 pulls Chromium for PNG/PDF, PlantUML needs a JVM, mmdc needs Chromium.

**Mermaid is dropped entirely (going past the adversary's "demote it").** Keeping a GitHub-only mermaid
"convenience" beside the image path re-creates the "two kinds — which do I use?" fork the maintainer
rejected, now at the render layer, with different target coverage, grounding, and determinism. Cutting
it loses nothing on GitHub: a committed `![alt](x.svg)` still renders there (researcher §B.1). One
mechanism, fewer concepts. If a live-mermaid GitHub convenience is ever wanted, it is a separate future
proposal that must carry the illustrative stamp.

**Mission alignment:** mission.md:232/301 ask for "deterministic charts from code … via code execution"
— a pre-render/run-a-program model, and it names Mermaid only as one example DSL alongside matplotlib.
The driving *principle* is deterministic-from-code; Graphviz satisfies it strictly better than Mermaid
(no Chromium, cheap compile-gate, deterministic `dot`). Selecting Graphviz honors the mission's intent
while updating the example tool on the grounded evidence. (Recommend the main session note this in the
mission changelog when this lands — I am read-only and only flag it.)

### 2.4 Determinism / content-addressing — compile at COMPOSE time to a STORED asset (decision 4)

Verified identity surfaces: asset bytes enter identity **only** by content hash
(`RenderInputs.assets: tuple[(path, content-hash)]`, dispatch.py:121; "every asset by CONTENT hash,"
serialize.py:773-782); the `tool_bundle` pins pandoc but nothing diagram-related (serialize.py:810-815);
dispatch appends only `inputs.flags` (+ content-gated `--citeproc`/`--csl`), no `--resource-path`/
`--embed-resources` (dispatch.py:266-270).

Settled: **the SVG is minted at COMPOSE/author time and STORED as a workspace asset; render time is pure
embedding.** Rationale, matching the adversary's determinism analysis:

- **Reject render-time generation** (a pandoc lua-filter/`pandoc-ext/diagram` or shelling to `dot` in
  dispatch): the SVG bytes would be minted at render, **outside every preimage** → idempotency breaks;
  and `pandoc-ext/diagram` "should not be used with untrusted documents" (researcher-diagram-tools §3) —
  this pipeline renders LLM content. Both fatal.
- **Adopt author-time stored SVG** (clean): the SVG is a fixed committed file whose **content hash
  already carries render identity** via the existing asset mechanism (dispatch.py:121,
  serialize.py:773-782). Same body → same reference → same bytes. On md this even round-trips as a plain
  path reference (researcher §B.1); on html/docx it embeds (needs the loader, §2.5).
- **Pin the graphviz version** and record it in the **author-time compile provenance** (the artifact
  record), NOT the serialize preimage — because the SVG is committed, not recompiled at render, a
  version bump changes bytes only on a *re-compose*, which mints a new artifact (new content hash → new
  identity) anyway. Use `dot -Tcanon` as the pre-store compile-gate; use `dot` (hierarchical, the
  deterministic engine — researcher-diagram-tools §2.1) not the seed-sensitive force-directed engines.

Note this **moots the backstop false-trip** (adversary §8): with no mermaid fence in the body, no leaf
carries a stray `data-fact=` substring, so the raw-count backstop (ir.py:469-476) cannot false-refuse.
The grounded node/edge list is consumed at compose and is NOT persisted into the IR body; the persisted
body is the `![alt](svg)` reference plus normal grounded prose spans (counted correctly). No
fence-aware scoping fix needed — resolved by construction.

### 2.5 Build SEQUENCE (prerequisites first) — decision 5

The asset subsystem is the true foundation; diagrams sit on top of it.

- **A — Asset storage + containment + provenance homes (foundation; MVP).** A compose-time content-asset
  store; the intra-body path **containment guard** (§2.6b); the two provenance homes (§2.6a). Needed by
  BOTH brought figures and generated diagrams, on ALL targets (md references by path; the file must exist
  and be contained). *Even the "cheap" md figure needs A — it is not free.*
- **B — Binary-target embedding (MVP).** Build the deferred filesystem asset loader
  (`_deferred_asset_loader`, driver.py:100-119 — today a loud RAISE, "deferred to §17/step-29") + emit
  `--resource-path` (and `--embed-resources --standalone` for self-contained html) in the Presentation
  lowering. Unlocks `figure`/image embed on html5/docx/plain. **md needs only A**, not B (it references
  by path). State plainly: **html/docx images cannot ship until this deferred loader is built** — it is
  the true first step for binary targets, not a "near-term free" add.
- **C — Generated diagrams (deferred, behind a spike).** Graphviz binary + the structured node/edge
  writer contract (extends the compose envelope, compose.py:653-694) + the hard grounding gate (§2.2) +
  compile-to-stored-SVG (§2.4). Built ON TOP of A (renders on md immediately; on html/docx once B lands).

So: **A → B (binary targets) and A → C (diagrams); C is gated behind a prototype spike.** The asset
loader (B) and the asset store (A) are the honest prerequisites the initial underplayed.

### 2.6 Asset boundary + provenance (decision 6)

**6a. Two provenance homes (fixes the "framework has no home" gap).** The initial declared assets
"always instance," foreclosing framework example images (rule 4: framework defaults ARE the public
deliverable). Fix — assets follow the SAME provenance/scope split registries already use:
- **Framework assets** (`provenance: framework`): a framework-owned public path (recommend a top-level
  `assets/…`; exact path a planner detail). Home for a framework genre's/doc's example image. May be
  empty at MVP — the *convention* must exist so the door isn't foreclosed. (Framework diagrams are
  generic/illustrative, so they carry the illustrative stamp, §2.2.)
- **Instance/client assets** (`provenance: instance`): `workspaces/<client>/assets/…`, gitignored
  (rule 4), client-isolated (rule 2). Ship `workspaces/workspace.template/assets/.gitkeep`.

**6b. Intra-body path containment guard (NEW — not GAP-9, but reuse its SHAPE).** Verified: GAP-9's
`validate_workspace_name` (workspace_name.py) validates a single workspace **name segment** via
resolve-and-contain (`candidate.resolve().parent == base.resolve()`). An intra-body `![alt](path)` is a
**different granularity** — a traversal *inside* a body string — so GAP-9 does NOT cover it; "mirror the
guard" is a NEW check, as the adversary correctly held. Build it: parse Image nodes from the composed
body, resolve each path against the section's asset root, and require **containment** within that root
(the resolve-and-contain SHAPE from workspace_name.py, at path-containment granularity). Runs at compose,
**blocking**. `![x](../../workspaces/other/secret.png)` is a loud rule-2 refusal — closing the live
cross-client render-time read the adversary flagged (pandoc resolves relative paths against cwd/
`--resource-path`, researcher §B.2). This guard is part of foundation **A**; figures cannot ship without
it. (The resolve-and-contain primitive in workspace_name.py imports nothing from `pipeline`; factor a
shared helper or co-locate — planner's call.)

**6c. A generated-diagram SVG is a STORED ASSET, not render-time output** (follows from §2.4). It lives
under the same asset home as brought figures — `workspaces/<client>/assets/diagrams/<content-addressed>.svg`
(instance) or the framework `assets/diagrams/…` (framework) — content-addressed for idempotency, folded
into render identity by content hash (dispatch.py:121). The *deliverable output* is the rendered
md/html/docx that references/embeds the SVG; the SVG itself is a compose-time-generated **asset**.
Brought and generated images share ONE lifecycle: same tree, same containment guard, same content-hash
identity.

### 2.7 Per-target degradation (decision 7 — the advisory is CUT)

The initial proposed a `capability-degraded` advisory reusing the dispatcher capability check. Verified
wrong seam: `capability_check` (dispatch.py:147-161) only checks writer membership (no AST inspection);
`CapabilityInfeasibleError` is a RAISE not a warn; `DispatchOutcome` (dispatch.py:169-191) has **no
warnings field**; the `nonsensical-pairing` advisory lives at the resolve layer, not dispatch.

**Under compiled-image, the whole seam evaporates — so I delete it.** A diagram is now an embedded
image; it renders on every target (md by reference, html/docx by embed once B lands). There is no "inert
mermaid on a binary target," hence nothing to warn about. We do **NOT** build a `DispatchOutcome.warnings`
channel. The only honest per-target statements are capability/scope facts, not per-deliverable runtime
advisories:

| target (writer) | figure / diagram | caption |
|---|---|---|
| md (markdown) → GitHub/artifact | renders (path served) | line / alt text (no free visible caption on GitHub) |
| html5 (prod) | renders once loader B built (embed) | `<figcaption>` free via `implicit_figures` |
| docx (prod) | renders once loader B built (container embed) | pandoc figure caption |
| plain (prod) | alt/caption text only (by nature; not a bug) | text only |
| pdf/pptx/epub (deferred) | pipeline renders none in v1 | — |

Deleting the advisory is a real simplification the compiled-image decision earns (the adversary noted:
"if §2 is adopted, this whole seam disappears").

### 2.8 Type-axis expressiveness — ratified WON'T-FIX (adversary §4)

A genre rule `{rule: count, axis: type, value: diagram, cardinality: '+'}` says "≥1 diagram exists
SOMEWHERE"; it cannot bind a `type` to a specific `role` ("the architecture section must contain a
diagram"). **Do NOT add a role×type co-constraint rule** — that is exactly where role and type blur and
the forbidden second surface grows. Ratified: the genre layer is coarse ("a diagram belongs somewhere in
this genre"); per-doc placement is the outline's job. The initial landed here; I make it an explicit
WON'T-FIX so it can't invite menu-creep.

### 2.9 The one-file-change test (stated with the true cost up front)

Per the maintainer's "explain in plain English / lead with the real cost," stated ONCE: **the STRUCTURAL
adds are one file; the RENDERING CAPABILITY is a multi-file, partly-deferred build paid once for the
capability, not per value.**

- Add `diagram` to `SECTION_TYPES`: one line, sections.py:102. PASS (structural).
- Add a mixed-media GENRE (a Format requiring a figure/diagram): one new `formats/<id>.md` with a
  type-axis `section_schema` rule. PASS.
- Add a brought image to a doc (once A/B exist): drop one file in `workspaces/<client>/assets/` +
  reference it in one heading body. PASS (instance-side, one file).
- Add a generated diagram to a doc (once C exists): author one `{type=diagram}` heading with a grounded
  node/edge block. PASS (instance-side, one authored block).
- **The capability itself** (asset store + containment guard + asset loader + embed lowering + graphviz
  compile + grounding gate) is multi-file and partly deferred — paid once, not per value. After it
  lands, adding a value stays one file.

---

## PART 3 — MVP BOUNDARY & DEFERRALS

### MVP (ready to plan)
**Existing images + captions, on all four internal writers (md/html/docx/plain).** Includes:
1. `figure` gains real image support: native `![caption](assets/…)`; captions free via pandoc
   `implicit_figures` (researcher §B.0) on html/docx.
2. **A** — the content-asset store + the intra-body **containment guard** (§2.6b, blocking) + the two
   **provenance homes** (§2.6a) + `workspaces/workspace.template/assets/.gitkeep`.
3. **B** — build the deferred filesystem asset loader (driver.py:100-119) + emit `--resource-path`
   (+ `--embed-resources --standalone` for self-contained html) in the lowering; fold image bytes into
   identity by content hash (already the mechanism, dispatch.py:121).

Honest, non-demo, multi-target; no new binary; no grounding-gate risk (brought images are author-
supplied, grounded by cited prose). I set the MVP line at A+B (not md-only) deliberately: a figure that
survives only on md contradicts the pipeline's "author once, fan out" identity and is the "demo not
feature" trap — overruling the initial's implicit md-only-is-enough framing.

### Deferred — next increment, BEHIND A SPIKE
**Generated diagrams (C):** Graphviz binary (pinned) + structured node/edge writer contract (extends
compose.py:653-694) + the hard grounding gate (§2.2) + compile-to-stored-SVG (§2.4). This is the
"generated diagrams" quarter of the charter. It is gated because the grounding gate MUST exist before a
diagram can ship, and the node/edge contract + LLM reliability + compile determinism are the least-
specified surfaces.

### Deferred — further / dropped
- Native live-Mermaid on GitHub: **dropped** (we render committed images instead; keeping it re-opens
  the "two kinds" fork).
- pdf/pptx/epub: already deferred pipeline-wide (render nothing in v1).
- A `DispatchOutcome` warnings channel: **cut** (compiled-image removes the need).
- Role×type co-constraint conformance rule: **WON'T-FIX** (§2.8).

---

## PART 4 — RECOMMENDATION: planner vs. spike

**Split verdict:**
- **The figure/image half (MVP: A + B) is READY FOR THE PLANNER now.** It is fully specified above,
  the tooling is verified pandoc-only (no new binary), and every touchpoint carries a file:line. The
  only genuinely new build is the deferred asset loader + containment guard — both well-bounded.
- **The generated-diagram half (C) needs ONE research spike before planning.** Prototype the
  end-to-end **grounded node/edge → hard gate → `dot` → stored SVG** path. The spike must answer: (1)
  can the writer reliably emit a strict, checkable node/edge list (researcher-diagram-tools §4 says the
  compile-gate primitive exists but LLM reliability is a hypothesis, PART 4/SOFT); (2) the exact
  extension to the compose envelope (compose.py:653-694) for the node/edge channel; (3) `dot -Tcanon`
  compile-gate + version-pin byte-stability; (4) grounded-vs-illustrative posture handling. Keep the
  spike small — it is a de-risking prototype, not a build.

Net: approve the settled MODEL now; plan the figure MVP; spike the diagram path before planning it.

--- end of RECONCILIATION ---
