# Known Issues & Gaps

The single running list of **bugs and capability gaps** in the optiquity-content-pipeline that
need to be addressed. This is the place to log anything found in use or review.

Most entries below were surfaced by the build's own coder→reviewer→audit process (they were
previously scattered across `state.md` carry-forwards and the step handoff reports, now
consolidated here). **None is a v1 acceptance blocker** — they are the honest backlog.

**Entry format:** `Status · Severity · Symptom · Root cause · Impact/workaround · Proposed fix · Source`.
When one is fixed, move it to **Resolved** with the commit that closed it.

---

## Open

### GAP-3 — §21.9 currency resolver is a partial detector (not production-safe)
- **Status:** Open (intentionally unwired / dead code today)
- **Severity:** Medium (latent hazard — must not be wired as-is)
- **Symptom:** `discovery.DefaultCurrencyResolver` can report a deliverable as `fit_current=true` when
  it is actually stale (it only re-checks platform hard-limits, and its `except → stored_digest`
  fallbacks fail in the unsafe direction). If wired to `list deliverables {fit_current:false}` /
  emit-manifest, a stale deliverable would be silently omitted from a force/refresh loop.
- **Root cause:** the default resolver is a partial re-computation by design (it lacks the recipe/all
  reconcile inputs, which only the §21.9 production wiring carries).
- **Impact / workaround:** safe today — it is never constructed on any production path (every caller
  injects an explicit resolver; the MVP uses a fail-safe one). The gate is honored/open.
- **Proposed fix:** before §21.9 wires any production currency resolver, either complete the
  reconcile-/serialize-input re-read or flip the uncertainty direction to fail-safe (report
  NOT-current on any un-verifiable input / on error → over-force, safe under render idempotency), and
  fail-safe the `except` branches.
- **Source:** step-34 review HARD GATE.

### GAP-4 — CI guards: two functional halves not yet wired
- **Status:** Open
- **Severity:** Low
- **Symptom:** (a) a brand-new top-level registry directory is outside the content-guard's known-root
  whitelist and passes silently; (b) the SV11 schema-lint PR-base diff clauses only activate on a PR
  event, and the repo has no PRs yet, so that wiring is unverified end-to-end.
- **Proposed fix:** tighten `scripts/check-no-content.sh` to fail on an unknown registry root; verify
  the SV11 PR-base wiring in `.github/workflows` once the repo gains PRs.
- **Source:** step-13 review, deferred through step 40.

### GAP-5 — Optional hardening (defense-in-depth, not required by design)
- **Status:** Open
- **Severity:** Low
- **Items:** (a) an optional payload-side metadata re-scan in `payload.build_payload` (closes a residual
  where a caller hand-builds a `fitted_ir` bypassing the IR secret-scan); (b)
  `manifest._resolved_row` could carry the §21.8 rule-2 `render-input-mismatch` warn onto the
  render-needed-from-stale-fit branch (under-reports fit-staleness for one cycle today); (c) a
  part-Div `#id` uniqueness check for multi-part/folio assembly (HTML-validity nit).
- **Source:** step-25/27/29/35 review observations, each marked optional.

### GAP-7 — The ideation phase (mission stage 1) is not built — topics must be hand-authored
- **Status:** Open (deliberate v1 scope boundary, tracked here as a missing capability)
- **Severity:** Medium–High (a whole missing pipeline stage — half of the mission's two-stage design)
- **Symptom:** The mission specifies a **two-stage** pipeline — **ideation** (source repo + audience →
  a ranked idea queue) then **generation** (idea → formatted artifact) — but v1 builds only
  *generation*. There is no ideation engine: nothing reads a repo's Graphify graph (god-nodes,
  communities, suggested questions) + audience personas to propose and rank content ideas. The nine-axis
  matrix starts from **topics** (§5.2, axis 1), which in v1 must be **hand-authored** as
  `workspaces/<client>/topics/<id>.md` entries (they may be manually seeded from Graphify's
  `GRAPH_REPORT.md`, but nothing generates them) before anything runs.
- **Root cause / rationale:** ideation internals were deliberately deferred from v1 — no ratified
  contract for how ideation should work; the ratified boundary is "hand-authored topic entries through
  the same interface." `docs/design.md:84` notes ideation/topic-sourcing "sits upstream of stage 1" and
  leaves it to the product plane; `docs/mission.md` §Role 2 describes the intended ideation engine.
- **Impact:** the system can generate content **for** a given topic across the full matrix, but cannot
  decide, discover, or rank **what** to write about — the operator supplies every topic manually. Half
  the intended product (repo → ranked idea queue) does not exist yet.
- **Proposed fix / when:** build the ideation engine as an upstream phase (repo graph + audience →
  ranked candidate topics) that emits the same `topics/` entries the generation pipeline already
  consumes, so it plugs into the existing interface with no downstream change. Requires a ratified
  ideation contract first. Post-v1.
- **Source:** `docs/mission.md` (the two-stage pipeline; §Role 2 "Ideation engine") + `docs/design.md:84`
  + the "Not in this build" register; maintainer asked it be tracked (2026-07-13).

---

## Deferred requirements

Intentional future scope — **recorded, not yet built**. Distinct from the bugs above: these are
capabilities we have deliberately deferred, kept here so the requirement is not lost.

### DR-1 — HTTP/webhook interface for cloud-hosted workflow orchestrators
- **Status:** Deferred (not in v1) — requirement recorded for a later build.
- **Need:** The v1 external-actor door (GAP-2) is the local `pipeline invoke render` CLI, invoked
  by an orchestrator that can shell out to the **same machine** (v1's named consumer: self-hosted n8n
  via its Execute Command node). **Cloud-hosted** orchestrators — Make, Zapier, n8n Cloud, Google
  (Workflows / Apps Script), and others — cannot execute a local CLI; they can only call an **HTTP
  endpoint** (typically a webhook). To serve those users the pipeline needs an HTTP interface.
- **Shape (design intent):** a thin, **transport-agnostic HTTP shim over the existing `invoke()` API**
  — one endpoint taking `{verb, workspace, params}` (or one per verb), returning the **same JSON
  envelope** the CLI emits (`ok`, `results[]`, a status mapping to the CLI exit codes 0/1/2/3). It adds
  **no business logic** — it reuses the exact handlers the CLI door wires. Because it is
  network-exposed, **authentication (token / API key) and rate limiting are part of this item**, as is
  restricting it to the safe external verb set (never the operator-only verbs, §21.9).
- **Why deferred:** v1's only named consumer is self-hosted n8n on the same host (maintainer,
  2026-07-13), for which the CLI door suffices. The HTTP shim was designed (see the `render-output-fix`
  GAP-2 design) as an **additive** component so it drops in later without disturbing the CLI/`invoke`
  door.
- **Depends on:** GAP-2 (the CLI/`invoke` door + `register_*_handler` wiring) lands first; the shim
  sits on top of the same `invoke()`.
- **Source:** maintainer requirement, 2026-07-13 — "needed eventually for other users who use any
  cloud based workflow orchestrator (Make, Zapier, n8n, Google, and others)."

### DR-2 — Selectable style guides (writing-rule presets) — design question, not yet a settled feature
- **Status:** Deferred (not in v1) — **requirement + open design questions recorded; to be designed by
  an architect before anything is built.**
- **Need:** a way to select, per request, a named **style guide** that nudges the *writing* of an
  output — prose rules, house conventions, structural preferences — without re-touching the existing
  axes one at a time. There should be **standard** framework guides (e.g. a generic tech-website blog
  post) and **platform-fitted** ones (e.g. LinkedIn, Medium), and instances should be able to add
  **corporate** guides (a company's PR / website / documentation / communications style). A guide could
  be applied anywhere at any time (even where it would be odd), but standard/specific ones exist so the
  common cases are one selection.
- **Hard constraint (orthogonality):** a style guide must **not overlap or duplicate any existing
  dimension**, and must **not absorb Format or Platform attributes**. It nudges a dimension's
  direction; it does not replace it. Where a dimension value genuinely needs to change, the guide may
  carry an explicit **per-dimension override** entry (voice, format, platform, …) *plus* its prose
  rules — overrides, not redefinitions.
- **The core design question the maintainer raised (answer FIRST, before inventing anything):** a
  style guide is *already* mostly a bundle of existing-dimension choices (voice + format + platform +
  others) plus prose rules — so **maybe no new axis is needed**. It could be:
  1. a named **preset / bundle** of existing dimension selections (+ a prose overlay), reusable in any
     workspace — composition, not a new construct; or
  2. a genuine new **style-guide construct** — only if (1) provably cannot express it cleanly; or
  3. actually a **templating feature** — the maintainer noted the *structural/formatting* need
     ("more easily and directly specify a desired structure") may be a separate, missing **template**
     capability rather than a style guide at all.
- **Open questions for the architect:** (a) can existing dimensions — or a **one-file additive
  extension** of one (per the matrix rule) — cover this, and is that better than a new thing? (b) if a
  guide *is* warranted, what structure lets it apply *wherever appropriate without conflicting*
  (overrides + prose, with a clear precedence vs the cascade)? (c) overlap specifically with the
  **VOICES** axis, which already carries tone/knowledge level — where is the line? (d) is the real gap
  a **template** feature (structure) distinct from a style guide (prose / house rules)? (e) provenance &
  scope: framework-**standard** guides (`provenance: framework`) vs instance/**corporate** guides
  (`provenance: instance`), and where they live (workspace-scoped, per the isolation rule); (f) how
  prose "writing rules" coexist with the **ground-in-EXTRACTED-facts** rule (style shapes *how* it
  reads, never *what* is claimed).
- **Recommended process (not yet run):** an **ops-architect**-led design pass (initial → adversarial →
  reconciliation, maintainer-gated) that answers (a)–(f) and recommends *bundle vs new construct vs
  templating* — optionally seeded by a light research pass on how real corporate/platform style guides
  are structured. This is design work; it is **not** to be improvised during a fix.
- **Depends on / relates to:** the nine-axis matrix + cascade (§3–§4); the VOICES axis; a possible
  **template feature** (may be split into its own item if the architect finds the structural need is
  separable).
- **Source:** maintainer requirement, 2026-07-16 — selectable, non-overlapping style guides
  (standard + platform + corporate), with the explicit instruction to first check whether existing
  dimensions (or better templating) already cover it before inventing a new construct.

### DR-3 — Optional artifact outline (pre-generation; dual output + input; outline-driven precedence) — design question
- **Status:** Deferred (not in v1) — **requirement + open design questions recorded; to be designed
  *jointly* with DR-2 by an architect (dimensions × style guide × outline seen together).**
- **Need:** let the user optionally generate a document/artifact **outline first**, review / **edit**
  it, and then generate the final artifact. The outline is **dual-natured**:
  - an **OUTPUT** — a first-class final artifact format in its own right (you can render just the
    outline); and
  - an **INPUT** — it directs the **content and/or structure** of the final prose artifact.
- **User control:** the user specifies whether the outline's **content**, its **structure**, or
  **both** drive the final artifact.
- **Precedence (the load-bearing architectural point):** when an outline drives generation it must have
  **far more influence than any other content- or dimension-related input** — it **outranks the
  dimensions** for what / how the artifact is written. The architect must place the outline in the M2
  cascade / precedence so it can dominate content + structure **without breaking orthogonality**.
- **Integration:** the outline must compose **elegantly with the nine dimensions AND the rendering
  system, as both an output and an input**, and coexist with DR-2 (style guide). How it enters as an
  input, how it is produced / edited as an output, and how it is fed back are all part of the design.
- **The core design question (answer FIRST, like DR-2):** is an outline **even necessary** if an
  artifact's **GOALS** are specified with the appropriate level of detail and precision? The architect
  must determine — (1) **is an outline needed at all?** (2) if **yes**: its **scope and design** (what
  it contains, how it is edited, how it is fed back as an input, its precedence, and its output-vs-input
  modes); (3) if **no**: what mechanism instead keeps an artifact's **focus / structure correct per
  artifact type** (e.g. more precise / structured **goals**, or a Format structure attribute — cf.
  DR-2 (d)).
- **Relationship:** **separate** from DR-2 (style guide) but **must be designed together** with it and
  the dimensions — the maintainer's instruction is that one architect sees **dimensions + style guide +
  outline** interacting, especially the precedence model (outline > dimensions when driving; style
  guide *nudges* a dimension).
- **Leads (not decisions — for the architect):** outline-as-output may resemble a new **output-type /
  format**; outline-as-input may resemble a new **pre-generation stage / input channel** that seeds
  compose; both must be tested against the one-file-add + orthogonality rules.
- **Source:** maintainer requirement, 2026-07-16 — optional editable outline that can be a final
  artifact and/or a high-influence input driving content and/or structure, to be assessed for
  necessity vs. sufficiently-precise goals.

---

## Resolved

The build's HARD GATES were closed inline during the build (gate G2 at steps 37–38, the §21.7
generation-code gate at step 39); those are recorded in `state.md` and the commit history. The
entries below are post-build defects closed by the **`render-output-fix`** series (2026-07-16).

### GAP-1 — Cannot re-render a stored document into another format without re-running the pipeline — RESOLVED
- **Closed by:** `558846c` (driver + `render.py::_render` read the **raw** stored IR via `unwrap_ir`;
  a re-render loads the stored artifact IR and drives serialize-only, no LLM) + `1f40f87`
  (external-side routing via a side-tagged `MintOutcome` → `payload.build_payload`).
- **What closed it:** `render`/`driver` now load the raw stored IR instead of expecting an
  `{"ir": …}` wrapper, and branch on `target.side`: **internal** targets serialize-only through the
  pinned pandoc writer (no re-grounding, no re-compose), **external** targets emit a zero-provenance
  RI14 contract payload (`{binding, side, payload, stripped}`, no bytes) for the external actor.
- **Verified (live):** stored artifact `a-5dc2cbd9676240e9` (real 13,208-byte body) re-rendered to
  `plain-text`/`html` (internal, clean readable prose) + `epub` (external payload, `side: external`,
  `stripped: true`, no bytes) with the transport tripwire NEVER firing — a hard-failing engine proved
  no recompose/LLM call. Deterministic. Confirms internal ≠ external.

### GAP-2 — No user-facing entry point for arbitrary render/generate requests — RESOLVED
- **Closed by:** `3a92f24` (the `pipeline invoke <verb>` machine door — registers render + fetch-by-id,
  JSON envelope on stdout, exit codes 0/1/2/3, §21.9 operator verbs structurally excluded via the
  `KNOWN_VERBS` gate) + `7ab9663` (the ergonomic `pipeline render` subcommand delegating to the same
  door).
- **Two doors, one seam:** a human runs `pipeline render --workspace W --item <id> --output-type <t>`;
  an external actor (v1: self-hosted n8n via its Execute Command node) runs
  `pipeline invoke render --workspace W --params-json '{…}'`. Cloud orchestrators still need the HTTP
  shim — see **DR-1**.
- **Verified:** both doors exercised by `tests/test_api_invoke.py` (`TestCliDoor`,
  `TestErgonomicRenderSubcommand`); the live re-render above went through the door.

### GAP-6 — A degenerate / near-empty writer body passed the contract and shipped as "ok" — RESOLVED
- **Closed by:** `558846c` (a **visible-text substance floor** on the body contract).
- **What closed it:** `ir._has_substance()` requires ≥1 Unicode letter/number over the NFC-normalized
  **visible** text (markup/attributes stripped); a body that is ellipsis-/punctuation-/whitespace-only
  now raises `ir-empty-substance`, which flows into the existing bounded re-ask and, on exhaustion,
  fails **LOUDLY** (§3.1) instead of shipping empty. Recovered re-asks are surfaced/logged, not silent.
  This is the *guardrail* behind GAP-8's *cure*.
- **Verified:** `tests/test_ir.py` + `tests/test_compose.py` (the floor rejects `"..."` / markup-wrapped
  placeholders, accepts real prose; the re-ask fires and is recorded in `violations`).

### GAP-8 — Compose returned a degenerate `"..."` body (empty deliverables in every format) — RESOLVED (fix landed; ablation directional)
- **Root cause (diagnosed, VERIFIED):** `pipeline/prompts/writer.md` opened with a
  `<!-- … STATIC contract … -->` developer-comment header; the writer model read it as *pasted file
  content* and, instead of composing, returned a meta-commentary refusal (or a `{"body":"..."}`
  placeholder). The valid-JSON placeholder passed the parse → no re-ask → shipped empty (the GAP-6
  hole); the non-JSON refusal tripped the bounded re-ask and recovered.
- **Closed by:** `a6d101b` (removed the leading dev-comment header from `writer.md`; the note moved to
  the loader docstring). GAP-6's floor backstops any residual case.
- **Verified (directional):** EXP-10 header ablation — V0 (header present) **3/8** runs derailed (each
  the exact diagnosed non-JSON refusal signature); V1 (shipped, header stripped) **0/8**. **Caveat:
  n=8, Fisher exact two-tailed p = 0.20 — not significant at α=0.05.** Directional evidence the fix
  removed the diagnosed trigger, not a significance-tested proof; the GAP-6 floor guarantees loud
  failure regardless.
