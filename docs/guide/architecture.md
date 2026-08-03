# Architecture

## Repository layout

The repository root contains CLAUDE.md, LICENSE, README.md, content-kinds/, docs/, folio-types/, formats/, goals/, instance/, languages/, lexicons/, output-types/, personas/, pipeline/, platforms/, presentations/, pyproject.toml, quickstart.md, recipes/, render-targets/, scripts/, sources/, state.md, state.template.md, templates/, topics/, uv.lock, voices/. It splits into four regions.

- **Registries (one directory per axis or dimension).** The four core axes are topics/, personas/, platforms/, and formats/. Alongside them sit goals/, voices/, languages/, lexicons/, output-types/, render-targets/, presentations/, content-kinds/, folio-types/, and recipes/.
- **The engine.** pipeline/ holds the Python modules — compose, cascade, grounding, ir, dispatch, serialize, and driver among them — with pipeline/adapters/ for source readers, pipeline/api/ for the verbs, pipeline/filters/ for the serialize filters, and pipeline/prompts/ for the writer and reviewer prompts.
- **The design record.** docs/ carries the mission, the definitive design, design-decisions, and known-issues, with docs/reference/ holding the operator grammar.
- **Scripts, instance config, templates, and workspaces.** scripts/ holds the launcher and maintenance tools, instance/ holds instance defaults and profile, and templates/ holds the shared framework blueprints (templates/workspace/). Per-client work is isolated under users/<user>/workspaces/<workspace>/, created with pipeline workspace new <workspace> --user <user> — which stamps the shared templates/workspace/ blueprint (the users/<user>/ segment is an isolation/addressing prefix, §23).

A literal view of the current tree (excluding `tests/`, `archive/`, instance-owned `users/`, caches, and dot-directories — the same exclusions the grounding used; `pipeline/` and `docs/` expanded one level, deeper directories collapsed):

```
.
├── content-kinds/
├── docs/
│   ├── reference/
│   ├── agents-and-skills-sourcing.md
│   ├── bootstrap.md
│   ├── claude-code-usage.md
│   ├── design-decisions.md
│   ├── design.md
│   ├── known-issues.md
│   ├── mission.md
│   ├── operating-model.md
│   └── ops-workflow.md
├── folio-types/
├── formats/
├── goals/
├── instance/
├── languages/
├── lexicons/
├── output-types/
├── personas/
├── pipeline/
│   ├── adapters/
│   ├── api/
│   ├── filters/
│   ├── prompts/
│   ├── __init__.py
│   ├── __main__.py
│   ├── ast_store.py
│   ├── attrtypes.py
│   ├── callback_delivery.py
│   ├── callback_policy.py
│   ├── canonical.py
│   ├── cascade.py
│   ├── claims.py
│   ├── compose.py
│   ├── dispatch.py
│   ├── drift.py
│   ├── driver.py
│   ├── entries.py
│   ├── fanout.py
│   ├── fit_resolution.py
│   ├── folios.py
│   ├── grounding.py
│   ├── ids.py
│   ├── ir.py
│   ├── jobs.py
│   ├── lint.py
│   ├── m1.py
│   ├── m3.py
│   ├── migration.py
│   ├── mvpdemo.py
│   ├── opdefaults.py
│   ├── opgrammar.py
│   ├── outline.py
│   ├── outline_store.py
│   ├── overrides.py
│   ├── parallel.py
│   ├── payload.py
│   ├── plan.py
│   ├── presentation.py
│   ├── reconcile.py
│   ├── review.py
│   ├── schema.py
│   ├── sections.py
│   ├── serialize.py
│   ├── spine.py
│   ├── ssot.py
│   ├── store.py
│   ├── telemetry.py
│   ├── transport.py
│   └── yamlio.py
├── platforms/
├── presentations/
├── recipes/
├── render-targets/
├── scripts/
├── sources/
├── templates/
├── topics/
├── voices/
├── CLAUDE.md
├── LICENSE
├── README.md
├── pyproject.toml
├── quickstart.md
├── state.md
├── state.template.md
└── uv.lock
```

### File reference

Every description below is sourced deterministically — engine modules from their module docstring, registries from each directory's `_schema.yaml` header, and root files from their own headers; none are generated.

| File | Description |
| --- | --- |
| `CLAUDE.md` | Operating instructions for working inside the control plane — the durable rules and session workflow. |
| `README.md` | The repo's own README — framework overview and entry point. |
| `quickstart.md` | Fast-start guide — get running fast for both the framework trial and the maintainer's public/private model. |
| `pyproject.toml` | uv-managed project metadata and pinned Python dependencies (Python >=3.12, ruamel.yaml, pytest, ruff). |
| `uv.lock` | The uv lockfile pinning the exact resolved dependency versions. |
| `state.md` | Derived, session-facing mirror of the tracking spreadsheet (SSOT) — a status/orientation snapshot, never the authority. |
| `state.template.md` | The template downstream instances copy to seed their own derived state.md. |
| `LICENSE` | The project license. |
| `pipeline/` | The Python engine — compose/render stages, the cascade, grounding, IR, dispatch, serialize, driver, plus adapters/, api/, filters/, prompts/. |
| `docs/` | The design record — mission, definitive design (design.md), design-decisions, known-issues, plus docs/reference/ (the operator grammar). |
| `scripts/` | The launcher (scripts/pipeline shim — includes the `serve` HTTP door) plus maintenance tools: schema-lint, migrate, update-from-upstream, check-no-content. |
| `instance/` | Instance-owned config — instance-global scope defaults (defaults.yaml) and the profile; extends the framework, gitignored in public. |
| `instance/shim.template.yaml` | Template for the HTTP shim's per-deployment config — the auth secret, bind host, workspace allow-list, and callback host allow-list; copy to the gitignored instance/shim.yaml and fill in. |
| `topics/` | Topic content dimension — what it is about and why it matters; binds at compose and enters artifact-id. |
| `personas/` | Persona content dimension — who it is for; provides the default_voice ref consumed by the Voice dimension. |
| `platforms/` | Platform rendering dimension — destination + constraint layer selected per deliverable (routing, never an instance-wide baseline). |
| `formats/` | Format content dimension — what shape/genre (platform-agnostic); binds at compose and enters artifact-id. |
| `goals/` | Goal content dimension — what outcome the artifact drives; the one set-valued dimension (a goal-set stacks into one artifact). |
| `voices/` | Voice content dimension — how it sounds; a named voice is a saved slider configuration + guidelines (parametric). |
| `languages/` | Language rendering dimension — scalar registry whose entry id IS the language tag; mandatory-global and part of fitted-id. |
| `lexicons/` | House-style Lexicon registry — the mechanical, checkable half of house style (terminology, casing, spelling standard, punctuation). |
| `output-types/` | Output-type rendering dimension — a pure serialization coordinate ('how it is serialized'); part of deliverable-id. |
| `render-targets/` | Render-target registry the serialize dispatcher reads — realizes an output-type (by convention the entry id equals the output-type slug). |
| `presentations/` | Presentation rendering dimension — one entry = one brand's complete cross-target look. |
| `content-kinds/` | Content-kind registry: the middle characterization tier — properties of what a source's content IS (a source instance tags into it). Not a dimension. |
| `folio-types/` | Folio-type registry: framework-shippable blueprints declaring a typed folio's member roles and structure. Not a dimension. |
| `recipes/` | Recipe registry — the per-artifact binding unit (recipe → one artifact): binds one entry per content dimension + a goal-set. |
| `sources/` | Source registry — SOURCE INSTANCES (bound config + characterization scores + a content-kind tag) and the §6.2 score vocabulary of record. Not a dimension. |
| `pipeline/__init__.py` | optiquity-content-pipeline — framework mechanism package (provenance: framework). |
| `pipeline/__main__.py` | `python -m pipeline` — the module entry point behind the `scripts/pipeline` shim (T8). |
| `pipeline/ast_store.py` | The layer-3 AST store: keyed by (fitted-id, reader-pin digest) — plan step 27. |
| `pipeline/attrtypes.py` | The §11.1 attribute-type system: typed value validation that REFUSES coercions. |
| `pipeline/callback_delivery.py` | The webhook-callback delivery — the outbound completion wake-up ping the detached runner sends when a Tier-B job settles (DR-1). |
| `pipeline/callback_policy.py` | The webhook-callback safety guard — the SSRF block + the operator host allow-list, checked at submit and re-checked at delivery (DR-1). |
| `pipeline/canonical.py` | Canonical JSON (sorted keys, deterministic bytes) + SHA-256 digest helpers + canonical sets. |
| `pipeline/cascade.py` | M2 — value binding (Mechanism 2 of the §12 value cascade): the folio-free spine fold. |
| `pipeline/claims.py` | The claim/lease registry: §22.3 acquire → live-skip → steal → holder-checked release. |
| `pipeline/compose.py` | The compose (writer) stage: grounded facts → a persisted IR-canonical artifact (§15). |
| `pipeline/dispatch.py` | The serialize dispatcher (§17 RI12): route a layer-3 AST by its render-target — plan step 27. |
| `pipeline/drift.py` | Drift machinery (§11.5): the comparison math, the MIG-6 block/warn/silent table, and the SV7 update-time report. |
| `pipeline/driver.py` | The thin end-to-end thread driver (plan step 28 — the FIRST END-TO-END OUTPUT). |
| `pipeline/entries.py` | The registry ENTRY loader: MD + frontmatter, enforcing the §11.1 entry envelope. |
| `pipeline/fanout.py` | Fanout enumeration (design §8): a multi-select selection → concrete recipe-shaped items. |
| `pipeline/fit_resolution.py` | Fit resolution (step 26) — PURE plan/coordinate resolution over step-25's fit-bindings. |
| `pipeline/folios.py` | Folios: the pure purposeful set — create, add, discover, typed-run consumption (§9). |
| `pipeline/grounding.py` | The grounding resolver — the §6.3 resolver walk over the adapter contract. |
| `pipeline/ids.py` | The §7 id family: preimage canonicalization, id minting, and the §7.4 string grammar. |
| `pipeline/ir.py` | The IR-canonical model + its JSON validation schema (§15 RI1–RI4) — plan step 24. |
| `pipeline/jobs.py` | The DR-1 async jobs subsystem: the lossy job record + TTL/steal lifecycle + the poll resolver behind the HTTP shim's Tier-B door. |
| `pipeline/lint.py` | SV11 schema-lint (design §11.7) — the public repo's schema/registry CI gate. |
| `pipeline/m1.py` | M1 — entry resolution (Mechanism 1 of the §12 value cascade): shadowing + field-merge. |
| `pipeline/m3.py` | M3 — the source-selection grammar & its four-layer cascade (Mechanism 3, design §12.1). |
| `pipeline/migration.py` | The §11.6 migration system (MIG-1…MIG-7): declarative step registry, the one fold, the 1-year window, the decisions-needed worklist, and the owner-triggered runner. |
| `pipeline/mvpdemo.py` | The ★ MVP demonstration scenario (§25) — ONE scripted, reproducible §25 acceptance run. |
| `pipeline/opdefaults.py` | Framework ops-default constants (§22.5/§22.8/§27.4): the G2-validated concurrency finals. |
| `pipeline/opgrammar.py` | The D1.1 unified operator grammar (§13.2): one AST, two surfaces, one validator. |
| `pipeline/outline.py` | The outline normalizer `N` + `outline_digest` — the identity-safe FOUNDATION for DR-3 (horn (a) / B1 build). |
| `pipeline/outline_store.py` | The pre-compose outline store: authored-and-edited outline Markdown, content-addressed by its BARE `outline-digest` — DR-3 build, Commit 5 (horn (a) / B1). |
| `pipeline/overrides.py` | Run-layer attribute overrides (§12.5, §21.4): the ephemeral L6 mechanism. |
| `pipeline/parallel.py` | The parallelism machinery (§22): the wave plan, the completeness sweep, the §22.6 wiring. |
| `pipeline/payload.py` | The layer-3 contract payload (§17 RI14) — the external hand-off for a `side: external` target. |
| `pipeline/plan.py` | Plan resolution (design §8, §21.6, §22.2): the deterministic complete item set + `plan_hash`. |
| `pipeline/presentation.py` | Presentation lowering (§17 PD3/PD4) — the full `lower(presentation, writer, output-type)`. |
| `pipeline/reconcile.py` | The reconcile pass (pass 1) core — PURE fit machinery (§16) — plan step 25. |
| `pipeline/review.py` | The two review gates (§19) — PURE producers of immutable, id-addressed review records. |
| `pipeline/schema.py` | The §11 schema system: co-located `_schema.yaml` manifests + closed-schema validation. |
| `pipeline/sections.py` | F1 sentinel section grammar — a pure, pandoc-3.10-faithful section parser (DR-4 / C1). |
| `pipeline/serialize.py` | The serialize pass (§17): IR-fitted → annotated Pandoc-Markdown → pinned AST — plan step 27. |
| `pipeline/spine.py` | The S0–S6 execution spine (§22.3): one work unit, driven crash-safe end to end. |
| `pipeline/ssot.py` | The tracking SSOT v1: the two-row-kind schema + the local-CSV single-writer (§24). |
| `pipeline/store.py` | The workspace store: §23 layout + the G1 atomic-write primitives + `is_done`. |
| `pipeline/telemetry.py` | Presence-lease registry + append-only CONTENT-FREE telemetry (§22.5, §24) under instance/ops/. |
| `pipeline/transport.py` | The headless Claude Code transport wrapper (F10, §21.9) — plan step 23, decision T6. |
| `pipeline/yamlio.py` | Pinned YAML 1.2 typed safe-load + the bounded frontmatter splitter (framework mechanism). |
| `pipeline/adapters/__init__.py` | Source adapters — pluggable, READ-ONLY grounding providers (design §6.1; plan T11). |
| `pipeline/adapters/base.py` | The source-adapter CONTRACT (design §6.1; plan step 17) — step 18 builds the real ones. |
| `pipeline/adapters/folder.py` | The REAL `folder` adapter (plan step 18) — read-only local folder/doc grounding. |
| `pipeline/adapters/fsast.py` | The REAL `fsast` adapter — read-only FILESYSTEM + Python-AST source grounding. |
| `pipeline/adapters/graphify.py` | The REAL `graphify` adapter (plan step 18) — read-only query of a client graph by path. |
| `pipeline/adapters/mock.py` | The deterministic MOCK adapter (plan step 17): fixture facts behind the real contract. |
| `pipeline/api/__init__.py` | The external-actor API (design §20-§22): the stateless `invoke` contract and its parts. |
| `pipeline/api/discovery.py` | Discovery — `list <type> [filters]` / `get <type> <id>` (§21.3, §13.2), SSOT-FREE. |
| `pipeline/api/fetch.py` | `fetch-by-id` — the DUMB HOT PATH of the external-actor API (§21.5). |
| `pipeline/api/folio_verbs.py` | The standalone folio write verbs — `create-folio` + `add-to-folio` (§21.2, §9). |
| `pipeline/api/http_shim.py` | The DR-1 HTTP shim (`pipeline serve`) — the HTTP sibling of the CLI over `invoke()`: Tier-A synchronous dispatch + the Tier-B 202-Accepted poll/webhook async door, behind mandatory auth. |
| `pipeline/api/invoke.py` | The external-actor `invoke` contract (§21.1): one synchronous call, one JSON object out. |
| `pipeline/api/jobrunner.py` | The detached Tier-B job runner (DR-1) — re-enters `invoke()` out of band for a paid job, then delivers its completion callback. |
| `pipeline/api/manifest.py` | `emit-manifest` — the point-in-time WORK ORDER for a folio (§21.5), NO MINT, SSOT-FREE. |
| `pipeline/api/render.py` | The standalone, token-free `render` verb (§21.8, §21.1) — fit + serialize RESOLUTION. |
| `pipeline/api/results.py` | The typed result contract + the CONSOLIDATED §21.7/§22.6 code taxonomy — one place. |
| `pipeline/api/session.py` | The session/generation half of the external-actor API (§20, §21) — `begin-session` and `continue-session`, on top of step-32's already-complete contract (invoke, workspace isolation, the token, the result taxonomy). |
| `pipeline/api/token.py` | The resumption token (§20; the §21 wire contract): a documented, actor-held cursor. |
| `pipeline/filters/__init__.py` | Serialize-owned Pandoc-AST filters (framework mechanism, `provenance: framework`). |
| `pipeline/filters/citeproc_enablement.py` | The content-driven citeproc-enablement signal (§17 R-4 family) — DR-5 build, COMMIT C6. |
| `pipeline/filters/provenance_strip.py` | The pinned provenance-strip filter (§17 R-4) — plan step 27. |
| `pipeline/filters/section_attr_validity.py` | The pinned section-attr validity filter (§17 R-4 / SD-5) — DR-4 build, COMMIT C9. |

## Internal design

A generation thread runs a fixed spine. The entry point is run_thread, which returns a ThreadResult and drives the per-item stages.

- **Ground.** Facts are gathered first. ground_item grounds one item and ground_batch a batch; the result is a GroundingOutcome that separates publishable_facts from leads. The driver refuses to proceed on an empty grounding via _grounding_abstain_check.
- **Resolve and bind the cascade.** resolve_compose resolves compose-time configuration and resolve_render the render-time configuration; each dimension is bound by _bind_dimension, folding layered values through _apply_rungs inside a CascadeEnv.
- **Compose.** The artifact stage runs _run_artifact, which calls compose_artifact. Compose builds the writer prompt with build_writer_prompt, parses the reply with parse_writer_output, and assembles the intermediate representation with _assemble_ir.
- **Render — reconcile and serialize.** The deliverable stage runs _run_deliverable, resolves render targets through resolve_render, and emits output through dispatch; multi-part outputs are addressed by split_part_addresses.
- **Persist.** Records are written by _persist and _persist_record.
- **Two review gates.** An artifact review runs via _run_artifact_review and a deliverable review via review_deliverable; their instructions live in pipeline/prompts/ (artifact_reviewer.md, deliverable_reviewer.md).

Riding on top of that engine — never inside it — is the HTTP shim (`pipeline serve`). It is a thin, stateless transport front that adds no business logic of its own: it receives an HTTP request and re-enters the same `invoke()` a command-line caller would, holding no session or model state between calls, so all cross-request state stays on disk in the same content-addressed store. Cheap verbs (Tier-A) run synchronously and return inline. Paid verbs (Tier-B) are acknowledged with a 202 and handed to a small on-disk jobs subsystem: a detached job runner re-enters `invoke()` out of band, writes a lossy status record the poll endpoint reads, and — when the caller asked for one — delivers a webhook wake-up once the job settles.

One limit shapes how deep this section can go: the facts available to this manual reach top-level definitions and one level of class methods, so call chains below that depth are not shown here.

---
[← Manual home](../../README.md) · Previous: [Getting started](getting-started.md) · Next: [Interfaces](interfaces.md)
