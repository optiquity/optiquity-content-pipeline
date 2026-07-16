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

### GAP-1 — Cannot re-render an already-generated document into another format without re-running the whole pipeline
- **Status:** Open
- **Severity:** High (maintainer-flagged, 2026-07-13)
- **Symptom:** A document already composed and stored in the internal format cannot, on its own, be
  rendered into another supported external format (e.g. take the stored `markdown` deliverable and
  produce `html` or `plain-text`). Getting a new format requires re-running generation from compose —
  a fresh LLM call — even though the content already exists.
- **Expected behavior:** rendering a stored internal-format document into any supported external
  format should be a cheap, deterministic, **serialize-only** operation — no re-grounding, no
  re-compose, no LLM/subscription call.
- **Root cause (two independent blockers):**
  1. The standalone §21.8 `render` verb reads the stored artifact record as `{"ir": …}`, but
     `compose._persist` stores the **raw IR** (no `ir` wrapper). So `render.py::_render` (~line 152)
     returns `not-found` for any real composed artifact (compose re-reads it raw at `compose.py:461`).
     The re-render verb is therefore non-functional on real data.
  2. `driver.run_thread` / the `demo-thread` CLI **hard-block** when the artifact is
     already-materialized (they raise `DriverError`), so they cannot be used to render an existing
     artifact to additional formats either.
- **Impact / workaround:** You *can* get several formats by naming all desired `output_types` up front
  in ONE generation run (the fanout §8 renders one compose to many formats — this works). But you
  cannot come back later and render a stored doc to a new format cheaply; you must regenerate (extra
  subscription usage + a non-deterministic fresh compose).
- **Proposed fix:** Align `render.py::_render` to read the **raw** stored IR (matching compose's
  storage shape), and/or add a re-render path that loads the stored artifact IR and drives ONLY the
  serialize/dispatch stage for the requested `output_type(s)`. Add a test that renders a stored
  artifact to a new format and asserts **no transport/LLM call** is made.
- **Source:** flagged at step-39 review (#4), confirmed by the step-41 delivery audit; maintainer
  asked it be tracked here (2026-07-13).

### GAP-2 — No user-facing CLI for arbitrary generate / render / discovery requests
- **Status:** Open
- **Severity:** Medium
- **Symptom:** The CLI exposes only fixed demos — `demo-thread` (one hardcoded coordinate, one output
  format) and `mvp-demo` (the fixed §25 scenario over synthetic fixtures). There is no command to run
  an arbitrary selection (chosen topic × persona × platform × format × output-types) against a real
  workspace; doing so requires calling engine functions directly (e.g. `driver.run_thread(...)`).
- **Root cause:** `api.register_api_handlers()` exists but is deliberately not called at import
  (calling it would break the step-32 empty-verb-registry test); only the `mvp-demo` subcommand wires
  it, and it runs the fixed scenario. No production CLI edge calls it for arbitrary input.
- **Impact / workaround:** the full external API (`invoke` / begin-session / generate-next / render /
  discovery) is built and tested but not reachable from a clean CLI verb; arbitrary runs go through
  the engine functions.
- **Proposed fix:** add a production CLI edge (e.g. `pipeline invoke …`) that calls
  `register_api_handlers()` once at startup and forwards arbitrary requests, supplying a fail-safe
  currency resolver (see GAP-3).
- **Source:** step-33 / step-34 carry-forwards.

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

### GAP-6 — A degenerate / near-empty writer body passes the contract check and ships as an "ok" artifact
- **Status:** Open
- **Severity:** Medium–High (produces unusable output silently)
- **Symptom:** When the writer (LLM) returns a trivially-degenerate document — observed:
  `{"body": "..."}` (three dots) — the pipeline accepts it as a valid artifact and renders it to
  every requested format, yielding empty deliverables (`...` → `…` → `<p>…</p>`). The artifact is
  marked composed/reviewed/rendered with a VERIFIED binding, so nothing fails loudly.
- **Root cause:** the IR body contract uses `_nonempty_str(...)` (`pipeline/ir.py:632` for the flat
  body, `:533` for a part body), which returns `True` for ANY non-empty string — including `"..."`,
  a lone `…`, or punctuation/whitespace-only content. There is no "substance" floor. The §19
  deliverable review *does* flag it (`verdict=concerns`), but §19 gates are advisory (non-gating), so
  the content still ships.
- **Impact:** a bad/degenerate generation becomes a persisted "ok" artifact with empty deliverables;
  wasted subscription usage; no loud failure or re-ask. (The identity binding is content-addressed on
  the preimage, not the prose, so a degenerate body still VERIFIES.)
- **Proposed fix:** add a substance floor to the body contract (e.g. reject a body that is
  ellipsis-/punctuation-/whitespace-only or below a minimal alphabetic-character count) and raise it
  as a `compose-contract-violation` so the bounded re-ask fires and, failing that, the artifact fails
  LOUDLY (§3.1) rather than shipping empty. Optionally promote the §19 "empty content" concern to a
  gating condition for this specific case.
- **Source:** found 2026-07-13 during the maintainer's three-format render test (the compose returned
  a `"..."` body; all three formats rendered empty).

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

### GAP-8 — Compose reproducibly returns a degenerate `"..."` document body (empty deliverables in every format)
- **Status:** Open — needs diagnosis (root cause not yet isolated)
- **Severity:** High (reproducibly produces unusable, empty output)
- **Related:** GAP-6 is the *downstream* half (the `"..."` body is not caught and ships anyway). GAP-8 is
  the *upstream* symptom (why the body is `"..."` at all).
- **Symptom:** For one specific run path, the writer/compose stage produces a document whose IR `body`
  field is literally `"..."` (three ASCII dots). The pipeline reports `compose: OK`, the binding digest
  VERIFIES, both `§19` reviews return `verdict=concerns` (advisory, non-gating), and the three rendered
  deliverables are empty:
  - `…github.en.html.plain.md` → `<p>…</p>` (11 bytes), sha256 `231f8183c54a749d…`
  - `…github.en.md.plain.md` → `...` (4 bytes), sha256 `a00c3b59d5e9e2d8…`
  - `…github.en.plain-text.plain.md` → `…` (4 bytes), sha256 `8479db376196d74b…`
  (pandoc renders the source `...` to a unicode ellipsis `…` in the plain/html writers.)
- **Key evidence it is systematic, not random LLM noise:** two independent `run_thread` invocations
  produced **byte-identical** outputs (identical sha256s above). The artifact-id
  `a-5dc2cbd9676240e9` and its binding are identical to a *good* run (see contrast below), because the
  id is content-addressed on the **preimage**, not the prose — so a degenerate body still "VERIFIES."
- **The contrast that should drive diagnosis:** the SAME coordinates
  (`recipe=explainer-post`, `topic=x-architecture-overview`, `persona=technical-evaluator`,
  `format=short-opinion-post`, `platform=github`, `presentation=plain`, `language=en` → artifact
  `a-5dc2cbd9676240e9`) produced a **full 12,373-byte grounded document** earlier in the same session
  when driven through `scripts/pipeline demo-thread` (which uses `demo_selection()`, a SINGLE
  `output_types=("md",)`). The failing path differs only in the `SelectionRequest` — it requests THREE
  output types `("plain-text","md","html")`. **Trigger not yet confirmed:** it is either (a) something
  in the multi-output `SelectionRequest` / plan-build corrupting the compose prompt/inputs, or (b) a
  session-wide / usage-related compose degradation that would also affect `demo-thread` if re-run now.
  Isolating (a) vs (b) is the first diagnostic step.
- **Ruled out (read-only checks, 2026-07-13):** no content-addressed cache outside the workspace store
  (only `.pytest_cache` / `.ruff_cache` exist; the store reset clears the artifact record); no explicit
  temperature/determinism pin found in `pipeline/transport.py` or `pipeline/compose.py` (so the
  byte-identical repeat is unexplained — worth confirming what sampling the headless CLI uses).

- **Reproduction:**
  1. Prereq: `workspaces/mvp-demo/` has `topics/x-architecture-overview.md` and
     `sources/x-optiquity-site.md` pointing at the optiquity-site Graphify graph (read-only).
  2. Reset the (disposable) demo store:
     ```
     for d in artifacts deliverables reviews output folios claims; do rm -rf "workspaces/mvp-demo/$d"/* 2>/dev/null; done
     printf 'row_kind,id,coordinates,source_commit,status,output_path,block_reason\n' > workspaces/mvp-demo/ssot.csv
     ```
  3. Drive the multi-output render (fails):
     ```python
     from datetime import date
     from pipeline.driver import run_thread
     from pipeline.fanout import SelectionRequest
     req = SelectionRequest(
         recipe="explainer-post", topics=("x-architecture-overview",),
         platforms=("github",), languages=("en",),
         output_types=("plain-text", "md", "html"), presentations=("plain",),
     )
     run_thread(root=".", workspace="mvp-demo", request=req, now=date.today(), log=print)
     ```
  4. Observe the degenerate body:
     ```
     python -c "import json; print(repr(json.load(open('workspaces/mvp-demo/artifacts/a-5dc2cbd9676240e9'))['body']))"
     # -> '...'
     ```
  5. Control (single-output `demo-thread`) to isolate trigger (a) vs (b) — reset the store again, then:
     ```
     uv run python -m pipeline demo-thread --workspace mvp-demo
     ```
     If this yields a full multi-KB body, the multi-output path (trigger a) is implicated; if it also
     yields `"..."`, it is a session-wide/compose degradation (trigger b).
- **Diagnostic leads for later:** log/compare the exact writer PROMPT built for the multi-output request
  vs `demo_selection()` (instrument `compose.build_writer_prompt`); capture the RAW transport response
  (`TransportResult.text` / `.raw`) to see whether the model literally returned `{"body":"..."}` or
  whether `parse_writer_output` reduced a larger response to `"..."`; confirm the headless CLI's
  sampling settings. Fixing GAP-6 (a substance floor on the body) would make this fail LOUDLY instead of
  shipping empty, even before the root cause is found.
- **Source:** observed 2026-07-13 during the maintainer's three-format render test.

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

---

## Resolved

_(none yet — the build's HARD GATES were closed inline: gate G2 at steps 37–38, the §21.7
generation-code gate at step 39; those are recorded in `state.md` and the commit history.)_
