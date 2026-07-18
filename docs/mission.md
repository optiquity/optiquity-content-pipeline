# Repo-Grounded Content Generation Pipeline — Project & Technical Requirements

> **⚠ SUPERSESSION BANNER (2026-07-11, placement package A4-2).** The design content of this
> document is superseded by [`docs/design.md`](design.md) — the single design SSOT. On any
> conflict, `docs/design.md` wins. This document is retained as the product/PRD + sourcing/ops
> context. The sections below are **not rewritten**; use this banner to know what still stands.
> (Authoritative map: `docs/design.md` Appendix B, §B.3.)
>
> **DEAD — superseded by `docs/design.md`** (new homes in parentheses):
>
> - **§1's MVP definition + success criteria** (→ design §25). The rest of §1 stands as PRD context.
> - **§2 System architecture** (→ design §2, §14).
> - **§3 Content matrix + extensibility model** (→ design §5; the 4-axis matrix and the inline
>   compatibility text are obsolete — the matrix is nine axes, §5.4).
> - **§4 Selection / fanout / compatibility filter / identity / config** (→ design §7, §8, §12,
>   §13; the compatibility filter is **DELETED** per Q4 — the allow-list is emergent, design §8).
> - **§8 Configuration artifacts & how-to-extend procedures** (→ design §5.4, §23; §8.2 → design
>   §8/§12/§13; §8.3 agents/commands → design §27.4; §8.4/§8.5 → design §5.4 + §27.4).
> - **§10.4 open-decision rows D1** (→ design §13, closed) **and D2** (→ design §7.4, closed).
>
> **RETAINED (living, not design):** §0 document control · §5 phased plan (update against design
> §25 — maintainer call) · §6 dependencies/install · §7 component vetting · §9 security/read-only
> model (render-side additions live in design §15–§17) · §10 risks (minus the D1/D2 rows above) ·
> the appendices.

> **Status:** Living document · **Version:** 0.2.2 · **Last updated:** 2026-07-18
> **Owner:** David · **Methodology:** Waterfall / ad-hoc, spreadsheet-tracked
> **Nature:** This is a living document. Sections, tooling picks, personas, formats, and pipeline
> stages will change. Every axis and every pipeline stage is designed to be **additive** — new
> values and new stages (e.g. editor agents) slot in without redesign. See §12 Changelog.
>
> **Abstraction level (read first):** This is a **system-design overview**. It fixes *direction* —
> the decisions that shape architecture — and deliberately defers *implementation minutiae* to the
> downstream technical-requirements / design docs. Rule applied throughout: **if a detail changes
> the architecture, it is directional and stated here; if it only changes an implementation, it is
> named as an open decision (see §10.4), not decided here.** Appendix A is non-binding reference.

---

## 0. Document control

| Field | Value |
|---|---|
| Purpose | Define the product vision, architecture, extensible data model, selection/fanout mechanism, phased delivery plan, and the vetted set of public agents/skills/tools that form the pipeline. |
| Scope | Design + setup requirements through Phase 3. Authoring of persona/format/platform files and code are downstream deliverables, specified here as requirements + acceptance criteria. |
| Out of scope | The Dell/Windows machine (test-only, no coding). Final published content. Fine-tuned custom models (future). Full publishing automation (constrained in Phase 3). |
| Reader | Primary author (solo/small-team). |
| Tracking | The resolved work-item queue (§4) maps 1:1 to spreadsheet rows: coordinates, source commit, status, output path. |

**How to read this doc:** §1–§4 define *what the system is*. §5 sequences *how it's built*. §6 lists *what must be installed*. §7 identifies and vets *the public agents/skills that are the engine* (the heart of the pipeline). §8 lists *the files you author and how to extend the matrix*. §9–§11 cover security, risk, and reference.

---

## 1. Product overview (light PRD)

**Problem.** Turning private code/text repositories into a steady stream of high-quality, audience-targeted content (docs + marketing) is manual and slow. Summarization tools (NotebookLM) lack depth because they read summaries, not code. No single tool spans the required matrix of topics × audiences × platforms × formats.

**Outcome.** A repo-grounded, extensible, two-stage pipeline — **ideation** (repo + audience → ranked idea queue) and **generation** (idea → formatted artifact) — running on Claude Code CLI, grounded in read-only Graphify knowledge graphs of source repos, with a review/editing layer, and later orchestrated/scheduled via n8n.

**Positioning goal.** Content targets defined audiences and is tuned to the instance's positioning goal. *Instance-specific goals, audiences, and machine roles are not in this framework doc — they live in the private instance's `instance/profile.md` (see `docs/operating-model.md`).* Marketing formats (LinkedIn/Medium/Substack) must support hooks and attention structure; docs must be code-accurate.

**MVP definition (Phase 1 exit).** From a single source repo with a committed Graphify graph, select one or more topics/personas/platforms/formats, fan out to concrete items, and generate publishable-quality drafts for each — interactively, in Claude Code, with a review pass — tracked in a spreadsheet. No scheduling, no auto-publish.

**Success criteria.** (a) Docs are code-accurate (grounded in EXTRACTED graph facts). (b) Marketing pieces match persona + platform constraints (word limits, hooks). (c) Adding a new topic/persona/platform/format is a one-file change that expands the matrix on the next run. (d) Source repos are never modified.

---

## 2. System architecture

**Two stages, one engine.**

1. **Ideation** — Read a source repo's Graphify graph (god-nodes, communities, suggested questions) + audience personas → propose ranked content ideas → curate into a queue.
2. **Generation** — For each queued item, a read-only *researcher* pulls grounding from the graph; a *writer* composes per persona + platform + format; a *reviewer/editor* (Phase 1b+) polishes and verifies.

**Engine:** Claude Code CLI (already in use). **Grounding layer:** Graphify graphs, queried read-only. **Orchestration (Phase 2+):** n8n on the always-on Mac mini.

**Machine roles.**

| Machine | Role in pipeline |
|---|---|
| Always-on host (e.g. an always-on Mac/Linux box) | Graph host + Graphify MCP server(s) + n8n orchestration + queue. Source repos + built graphs can live here. |
| Workstation (laptop/desktop) | Interactive generation in Claude Code; can query the host's graphs over a private network (e.g. Tailscale). |
| Test-only machine | Out of scope. |

*(Concrete machine names/roles for a given instance belong in `instance/profile.md`.)*

**Data flow (read-only across Tailscale).**

```
Source repo(s)                     optiquity-content-pipeline repo (writable)
  ├─ code / docs / scripts           ├─ registries: topics / personas / platforms / formats
  └─ graphify-out/ (committed)       ├─ selection resolver + fanout
       ├─ graph.json  ──────query────┤   (read-only into source graphs)
       ├─ wiki/       ──────read─────┤
       └─ GRAPH_REPORT.md ──seed─────┤ ideation → queue (spreadsheet rows)
                                     └─ generation: researcher → writer → reviewer → output/
```

The pipeline reads source graphs (by file path, MCP query, or pre-exported wiki) and only ever writes inside `optiquity-content-pipeline/`. See §9 for the read-only enforcement model.

---

## 3. Content matrix + extensibility model

The core data model is four axes: **topics × personas × platforms × formats**. A *generated item* is one point in the compatibility-filtered cross-product (see §4).

### 3.1 The four axes (established here; authored as files in §8)

- **Topics** — subjects to write about. **Seeded** from each source repo's Graphify `GRAPH_REPORT.md` (god-nodes = central concepts; communities = natural topic clusters; suggested questions = ready-made angles). Extended by hand.
- **Personas** — the five target audiences: (1) potential/current **users**, (2) potential **clients**, (3) **AI-company hiring managers**, (4) **finance-company hiring managers**, (5) **general interest**. Each defines knowledge level, motivations, objections, tone, and what "credible" looks like to them.
- **Platforms** — LinkedIn, Medium, Substack, GitHub (README/wiki), personal site/docs. Each carries constraints: length norms, formatting, whether hooks matter, image support.
- **Formats** — how-to doc, explanatory doc, blog post, LinkedIn post, Medium/Substack post, README. Each carries: word-limit (or none), hook requirement, structure, image/chart needs, all-text vs. visual.

### 3.2 Extensibility model (first-class requirement)

**Principle: registry-driven discovery, not hardcoded lists.** Each axis is a **directory of self-describing entries**. Adding a value = dropping in **one** file. The resolver discovers it automatically and the matrix expands on the next run — no code change, no editing an enum or master list in a second place.

- Personas: one file per persona in `personas/`.
- Platforms and formats: one entry each, **carrying its own compatibility metadata inline** (which platforms a format is valid for; which personas exclude it). Add a format → declare its compatibility in that same file → the §4 filter stays correct automatically.
- Topics: append to the topic registry (seeded from Graphify, extended by hand).

**Anti-pattern (to avoid, tracked in §10):** if adding a value requires editing more than one place, that is a defect. Automations (§4) reference registry entries **by ID**, never by inlined copies, so schedules keep working as the matrix grows.

**Adding a whole new axis or pipeline stage** (e.g. a "language" axis, or an editor stage): the resolver iterates over a declared list of axes and the pipeline over a declared list of stages, each defined in config — so a new axis/stage is a config addition plus its own registry directory, not a rewrite. This is what keeps the doc's "living" promise real.

---

## 4. Selection & fanout mechanism

Defines the **generation request**: how you pick from the matrix and how a pick expands into concrete, tracked, idempotent work items. Same schema drives both one-off and scheduled runs.

### 4.1 Selection input

Choose **one or more** from each axis, plus global options:

- `topics: [...]`, `personas: [...]`, `platforms: [...]`, `formats: [...]` — each a list of registry IDs (or `all`).
- Globals: `include_images: true|false`, `word_limit_override`, `tone_override`, `source_repo`, `source_commit` (defaults to current HEAD of the source repo).

### 4.2 Compatibility filter (not a naive cross-product)

Each format declares valid platforms; each persona may exclude formats. The resolver computes the **filtered** cross-product, so invalid combinations (a README as a LinkedIn post; a hook-teaser as a formal how-to) never enter the queue. Compatibility lives in the format/platform/persona registry entries (§3.2), so it extends automatically.

### 4.3 Fanout expansion

The filtered selection resolves to **N concrete items**. Example: `2 topics × 3 personas × 2 platforms × 2 formats = 24 raw`, minus incompatible combos = the actual generated set. Each item becomes one queue entry / one spreadsheet row.

### 4.4 Deterministic item identity (idempotency) — directional requirement

**Requirement:** every resolved item has a **stable identity derived from its four coordinates + the source commit**, so runs are idempotent and dedupable (re-running the same selection at the same commit yields the same items → no double-generation) and every item is traceable to exactly what it was built from. This is directional because it shapes the queue/tracking model.

*Implementation detail deferred:* the exact identity scheme (slug template vs. hash, field ordering, collision handling) is a Phase 1 decision — see §10.4.

### 4.5 Two invocation modes (shared schema)

- **One-off:** selections passed as CLI flags or a small run-manifest file → resolve → generate now.
- **Scheduled:** a committed config file (same selection schema + `cadence` + queue-draining policy, e.g. "max N generations/day") → n8n (Phase 2) reads it, expands, and enqueues on schedule.

The only difference is inline vs. committed. You author/test a selection interactively, then promote the identical shape into an automation config.

### 4.6 Config format — directional principle (serialization deferred)

The only directional constraint at this level: config is **authored by a human and consumed by automation**, so the chosen approach must be **self-documenting on the authoring side** (comments / readable structure for a living registry) and present a **clean, deterministic contract on the machine side** (stable input for the resolver, queue, and n8n).

The specific serialization (YAML, JSON, TOML, split authoring-vs-machine formats, etc.) does **not** change the architecture — it changes an implementation. It is therefore an **open decision deferred to the technical-requirements doc (§10.4)**, to be settled with evidence during Phase 1, not fixed here.

---

## 5. Phased delivery plan (waterfall)

Each phase lists deliverables, entry/exit criteria, and what's tracked. Phases are sequential; later stages (editor agents, more tools) attach to Phase 1b+ slots without reworking earlier phases.

### Phase 0 — Foundations & prerequisites
- **Deliverables:** runtime prereqs installed (§6.1) on the always-on host + workstation; Graphify installed; each in-scope source repo has a current committed `graphify-out/` and a `--wiki` export; `optiquity-content-pipeline` repo created and chezmoi-managed.
- **Entry:** none. **Exit:** `graphify query --graph <repo>/graphify-out/graph.json "smoke test"` returns grounded results on each source repo; `optiquity-content-pipeline` repo builds/lints.
- **Tracked:** per-repo graph build date + commit.

### Phase 1 — Manual Claude Code pipeline (MVP)
- **Deliverables:** the four registries populated (§8); selection resolver + fanout (§4); read-only **researcher** subagent + **writer** subagent (§7 role 2/3); slash commands for ideation and generation; `CLAUDE.md` conciseness/house-style rules; content-matrix spreadsheet template.
- **Entry:** Phase 0 exit. **Exit:** MVP success criteria (§1) met on one source repo.
- **Tracked:** items generated, per-item coordinates + source commit + output path + status.

### Phase 1b — Review / editing layer
- **Deliverables:** **reviewer/editor** subagent(s) (§7 role 6): detect-first-fix-later proofreading, voice/persona enforcement, source/claim verification, AI-slop detection. Wired as a stage after `writer`.
- **Entry:** Phase 1 exit. **Exit:** every generated item passes an editor pass with a recorded diff/score before being marked ready.
- **Tracked:** editor pass result per item (issues found/fixed).

### Phase 2 — n8n orchestration & approval gates
- **Deliverables:** n8n on the always-on host owns the queue + schedule; reads the scheduled config (§4.5); triggers Claude Code headless per approved item; Telegram approval/notification gates (matches existing OpenClaw/n8n patterns); queue-draining policy (batch N/day to respect usage limits).
- **Entry:** Phase 1b exit + stable templates. **Exit:** a scheduled config produces reviewed drafts to an output dir with human approval, unattended.
- **Tracked:** run logs, approvals, generation counts vs. usage budget.

### Phase 3 — Publishing & scale
- **Deliverables:** staged-draft → platform handoff. Publishing automation only where APIs allow; otherwise "staged draft to copy" (see §10 constraints). Multi-repo scale-out.
- **Entry:** Phase 2 exit. **Exit:** end-to-end from selection to platform-ready output across ≥2 repos.
- **Tracked:** published/staged per platform.

---

## 6. Technical requirements & dependencies

Ordered by "what must exist before what." Each item: source, license, role, and where its exact install steps live (Appendix A).

### 6.1 Runtime prerequisites (both Macs)

| Dependency | Role | Source | Notes |
|---|---|---|---|
| Homebrew | Package manager | https://brew.sh | Base for the rest. |
| Node.js (current LTS) | Runs Claude Code CLI + some skill plugins | https://nodejs.org | Directional: "a current supported runtime." Exact minimum is Claude Code's requirement at install time — verify then, don't pin here. |
| Claude Code CLI | Pipeline engine | https://code.claude.com | Already in use; confirm current version. |
| Python (current supported 3.x) | Graphify + helper scripts | https://python.org | Directional: exact minor version is a Phase 0 install detail, not a design constraint. |
| uv or pipx | Isolated Python tool install | https://github.com/astral-sh/uv · https://pipx.pypa.io | `uv tool install` recommended for Graphify. |
| Tailscale (+ MagicDNS, HTTPS) | Cross-machine graph access | https://tailscale.com | Already configured. |
| n8n (Phase 2) | Orchestration/scheduling | https://n8n.io (self-host on the always-on host) | Already in use. |

> **Verify current Claude Code / Node requirements against official docs before installing** — these change. Consult `https://docs.claude.com` and `https://code.claude.com/docs`.

### 6.2 Graphify (grounding layer) — required, Phase 0

- **What:** `safishamsi/graphify` — turns any folder (code/docs/scripts/PDF/images) into a queryable knowledge graph; Claude Code skill + CLI. MIT-licensed; local/on-device (code via tree-sitter with no API calls; prose/PDF/image extraction uses *your* configured model). YC S26.
- **Source:** https://github.com/safishamsi/graphify · site https://graphify.net · **PyPI package name is `graphifyy` (two y's); CLI stays `graphify`.**
- **Role in pipeline:** read-only grounding for both ideation (`GRAPH_REPORT.md` seeds topics) and generation (`graphify query --graph <path>` supplies facts; confidence tags EXTRACTED/INFERRED/AMBIGUOUS).
- **Outputs per repo:** `graphify-out/` → `graph.json` (queryable), `graph.html` (interactive), `GRAPH_REPORT.md` (god-nodes/communities/questions), `cache/` (SHA256 incremental). Meant to be committed to git.
- **Access patterns (all read-only):**
  1. **Query by path:** `graphify query "…" --graph <repo>/graphify-out/graph.json --budget 3000` (also `--dfs`, `path`, `explain`).
  2. **MCP server:** `python -m graphify.serve <repo>/graphify-out/graph.json` → tools `query_graph`, `get_node`, `get_neighbors`, `shortest_path` (stdio or HTTP — **verify exact HTTP/port flags with `--help`**; HTTP enables workstation→host over Tailscale).
  3. **Wiki export:** `graphify <repo> --wiki` → `graphify-out/wiki/index.md` + one article per community/god-node; agent-crawlable, no running process.
- **Exports (optional):** `--graphml` (Gephi/yEd), `--neo4j` (Cypher), SVG.
- **Alternative (support/complementary):** `code-review-graph` (CRG) — SQLite-backed AST graph, ~25 MCP tools, sub-second incremental updates, blast-radius analysis. Consider if you want a live self-updating code graph alongside Graphify's multi-modal one. Source: see §7 role 1.

### 6.3 Skill/agent packs & supporting tools

Chosen components are identified and vetted in **§7**. Installation is per-pack (clone into `~/.claude/skills/` and `~/.claude/agents/`, or via each pack's installer). Supporting tools: charting (matplotlib/Mermaid via Claude Code code execution), image generation (optional, per format needs), and the eval/quality tooling in §7 role 7.

---

## 7. Pipeline components — sourcing & quality vetting (the engine)

**This is the heart of the pipeline.** Components are organized **by pipeline role**, not by abstract category, so every functional stage maps to a named, sourced, vetted option. Each entry gives source, license, role fit, quality evidence, and a **recommended vs. alternative** call. The list is deliberately open-ended — new roles/stages (e.g. more editors, translators) attach here without disturbing existing ones.

**Vetting method & bias:** primary signals weighted over hype — actual repo contents (SKILL.md/agent files), real example output, commit recency, license, and independent write-ups (builder blogs, Substack/Medium round-ups). Star counts on listicles are treated as weak signals and flagged where a source is thin. Verify licenses and read the actual files before adopting (see §10).

### Role 1 — Repo grounding / research layer

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **Graphify** | github.com/safishamsi/graphify | MIT | Multiple independent deep-dives (Augment Code, Analytics Vidhya, GoPenAI, MindStudio); documented MCP + wiki + `--graph` path query; on-device privacy model; rapid iteration. | **Recommended** (grounding for whole pipeline). |
| code-review-graph (CRG) | see dev.to guide "Graphify + code-review-graph" | OSS (verify) | Paired-tool guide with concrete MCP tool list; sub-second incremental updates. | **Alternative/complement** for live code graph. |

### Role 2 — Ideation engine (repo + audience → ranked ideas)

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **`content-strategy` skill** (alirezarezvani) | github.com/alirezarezvani/claude-skills (skills/marketing) | OSS (verify; MIT-style) | Structured pillars/topic-clusters, impact-fit-search scoring, "searchable vs shareable," explicit interplay with copywriting/copy-editing skills. Part of a 300+ skill library with broad coverage. | **Recommended** base; retarget scoring to your 5 personas. |
| `content-idea-generator` (brianrwagner ai-marketing skills) | crossaitools.com / mcpmarket listing | OSS (verify) | "Positioning gate," per-platform idea formats, 3-test filter (specific / hook angle / persona), contrarian-angle templates. Strong hook discipline. | **Alternative** — good hook/angle patterns to borrow. |
| Community "content idea sprint" / "Voice DNA" skills | round-ups: aiblewmymind.substack.com (39 skills), dkspeaks Medium (18 skills) | mixed (verify each) | Builder-reported workflows: 20 ideas grouped by theme; Voice-DNA extracts what you *avoid*, not just patterns. | **Pattern source** — mine for techniques, adopt selectively. |

### Role 3 — Writing engine (idea → drafted artifact)

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **claude-blog** (AgriciDaniel) | github.com/AgriciDaniel/claude-blog | MIT (public repo) | ~30 sub-skills + 5 agents; persona voice profiles; multi-pass QA; 5-gate "Blog Delivery Contract"; outputs .md/.html/.pdf/hero image; 160 tests, version-coherence enforcement; video walkthrough + live demo. Tier-4 reference implementation of the Agent Skills standard. | **Recommended** architecture to fork. **Retarget its SEO/AI-citation focus to persona thought-leadership** (drop schema/FAQ noise for LinkedIn/Medium). |
| **boraoztunc/skills** (incl. `ogilvy`) | github.com/boraoztunc/skills | OSS (verify) | Copywriting/SEO/design skills; single-file install; adversarial multi-agent review fan-out pattern. | **Alternative/complement** — strong copywriting + review pattern. |
| MindStudio 5-skill workflow (pattern, not a repo) | mindstudio.ai blog | tutorial | Explicit research→copy→repurpose→UGC→schedule chain; parameterized `format/tone/wordCount/audience` prompt. | **Reference pattern** for wiring format params. |
| Platform-specific writing skills (blog/LinkedIn/Substack notes) | round-ups above | mixed (verify) | Per-platform format/CTA logic; Substack-notes structural patterns. | **Optional** per-platform boosters. |

### Role 4 — Persona / audience layer

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **alirezarezvani/claude-skills** (marketing personas + C-level personas) | github.com/alirezarezvani/claude-skills | OSS (verify) | 300+ skills, 30+ agents; marketing "customer persona" skills; C-level founder-mode personas (CTO/CFO/etc.). Multi-harness. | **Recommended** seed for your 5 personas (esp. hiring-manager framing via C-level personas). |
| "Separate skill per audience" pattern | aiblewmymind.substack.com round-up | pattern | Builder finding: **one skill per audience** beats one giant voice skill — Claude stops confusing audiences. | **Adopt as design rule** — matches §3 registry (one file per persona). |
| Voice-DNA extraction | round-ups above | mixed (verify) | Extracts your avoids/absences into an override profile. | **Optional** — for your own authorial voice consistency. |

### Role 5 — Doc-from-code layer (technical / explanatory docs)

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **divar-ir/ai-doc-gen** | github.com/divar-ir/ai-doc-gen | OSS (verify) | 5 specialized agents (Structure, Data Flow, Request Flow, Dependency, API); builder Medium write-up reports use on **50+ projects**, weekly analysis, auto-MR. pydantic-ai; multi-LLM. **GitLab-oriented automation** (core analysis works locally on any repo). | **Recommended** for deep code-grounded docs. |
| AIGNE DocSmith | github (topic: ai-document-generator) | OSS (verify) | Structured, multi-language docs direct from source; Gemini/OpenAI. | **Alternative** — multi-language needs. |
| DocAgent (academic) | arxiv.org/html/2504.08725 | paper + code | Multi-agent docstring generation; evaluated on 9 repos from 164-repo corpus; hierarchical navigator/generator/verifier. | **Reference** — methodology, not turnkey. |
| connor-john/ai-docs · Wytamma/write-the | github | OSS (verify) | Minimal repo→README (Anthropic API) · Python docstrings/tests/mkdocs. | **Lightweight alternatives.** |

### Role 6 — Editor / review layer (Phase 1b; open-ended, more editors expected)

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **LimHyungTae/awesome-claudecode-paper-proofreading** | github.com/LimHyungTae/awesome-claudecode-paper-proofreading | OSS (verify) | **Detect-first-fix-later** two-phase workflow (lists numbered issues, waits for user selection before editing); distilled from real top-venue paper reviewing; works Claude Code + Codex. Safe-by-default (never edits until confirmed). | **Recommended** proofreading pattern (the detect-then-approve gate matches your workflow). |
| **`copy-editing` skill** (alirezarezvani) | claude-skills (marketing) | OSS (verify) | Purpose-built to review/improve existing marketing copy; explicitly sequenced after copywriting. | **Recommended** for marketing-copy polish. |
| Claude MPM | referenced in hyperdev.matsuoka.com write-up | OSS (verify) | Multi-agent orchestration layer for writing on Claude Code; the article documents style-extraction-from-git-diffs, cross-model proofreading, source verification, voice enforcement. | **Alternative/framework** if you want orchestrated multi-editor. |
| `content-humanizer` / AI-slop detection | claude-skills + round-ups | mixed (verify) | Flags AI patterns, passive voice, filler. | **Complement** — final anti-slop pass. |
| boraoztunc adversarial review fan-out | github.com/boraoztunc/skills | OSS (verify) | One skeptic per domain → adversarial verify → synthesis. | **Complement** — high-stakes pieces. |

### Role 7 — Support: subagent frameworks, eval/quality gating, orchestration

| Component | Source | License | Evidence | Call |
|---|---|---|---|---|
| **wshobson/agents** | github.com/wshobson/agents | OSS (verify) | Multi-harness plugin marketplace; ships **plugin-eval** (static + LLM-judge + Monte Carlo reliability). | **Recommended** for agent scaffolds + **quality gating** (fits your spreadsheet/measurement style). |
| VoltAgent/awesome-claude-code-subagents | github.com/VoltAgent/awesome-claude-code-subagents | OSS (verify) | 150+ vendor-neutral subagents across 10 categories incl. documentation-generator; installer script. | **Alternative** subagent source. |
| Anthropic Agent Skills standard | anthropic.com/engineering (Agent Skills) + code.claude.com/docs | standard/docs | Official SKILL.md spec, progressive disclosure, `context: fork`, skills-in-subagents. | **Foundation** — the format all the above share. |
| n8n | n8n.io (self-host) | fair-code | Already in use; queue/schedule/approval, Execute-Command → Claude Code headless. | **Recommended** orchestrator (Phase 2). |
| Charts/images | matplotlib / Mermaid via Claude Code code-exec; optional image-gen | OSS / varies | Deterministic charts from code; diagrams via Mermaid. | **As needed** per format. |

---

## 8. Config artifacts to author & how-to-extend procedures

Given §7's picks, these are the files Phase 1 produces (requirements + acceptance criteria; content is a downstream deliverable). All live in the chezmoi-managed `optiquity-content-pipeline` repo.

### 8.1 Registries (one directory per axis)

- `topics/` — topic entries (seeded from `GRAPH_REPORT.md`, extended by hand). **AC:** resolver lists a new topic after adding one file, no code change.
- `personas/` — one file per persona (the 5 audiences). **Design rule from §7 role 4: one file per audience.** **AC:** adding one new persona file makes it selectable next run (file format per §4.6, deferred).
- `platforms/` — one entry per platform, **with inline compatibility + constraints** (length, hooks, images). **AC:** compatibility filter honors a newly added platform automatically.
- `formats/` — one entry per format, **with inline compatibility (valid platforms, excluded personas) + word-limit/hook/image rules**. **AC:** adding a format with declared compatibility expands the filtered fanout correctly.

### 8.2 Selection & resolver

- one-off manifest / CLI flags, and a scheduled config — **same selection schema** (§4.1). **AC:** identical schema across both modes; resolver emits a **canonical machine-readable item list** with deterministic identity (§4.4). File format per §4.6 (deferred).

### 8.3 Agents & commands (from §7)

- `.claude/agents/researcher.md` — **read-only** (tools: Read, Grep, Glob, + `graphify query`); no write tools. **AC:** cannot modify source repos (see §9).
- `.claude/agents/writer.md` — composes per persona+platform+format.
- `.claude/agents/reviewer.md` (Phase 1b) — detect-first-fix-later editor.
- `ideate` + `generate` skills (SKILL.md) — slash commands.
- `CLAUDE.md` — house style + conciseness rules + "don't commit until approved."
- `.graphifyignore` — gitignore-syntax excludes for graph builds.

*(Exact filenames/extensions for registry entries and configs follow the §4.6 decision; agent/skill files use the SKILL.md/agent frontmatter the harness requires.)*

### 8.4 How to add a new axis value (procedure)

1. Copy the axis's template file into the axis directory; fill metadata (for platforms/formats, **declare compatibility inline**).
2. Run the resolver in dry-run: it should list the new value and show updated fanout counts.
3. **Acceptance test:** a selection including the new value resolves to the expected (filtered) item set with correct IDs. If any *second* file needed editing, that's a §10 defect.

### 8.5 How to add a new pipeline stage (e.g. another editor)

1. Add the agent file (`.claude/agents/<stage>.md`).
2. Register it in the pipeline stage list (config), positioned after `writer`.
3. **AC:** items flow through the new stage and record its result column in the spreadsheet.

---

## 9. Read-only & security model

- **Source repos are never written.** Enforced three ways: (a) `researcher` subagent tool permissions limited to Read/Grep/Glob + `graphify query` (no Write/Edit/Bash-write); (b) querying `graph.json` by path or via MCP is inherently read-only; (c) optionally mount/keep source repos read-only, or access them only over Tailscale from the host.
- **Graph serving exposure:** if serving graphs over HTTP from the host, bind to the Tailscale interface only (not public); prefer stdio locally. Verify serve flags before scripting (§6.2).
- **Secrets:** Graphify's scanner and your `.graphifyignore` should exclude secret-bearing files; the writer must not surface credentials from graph nodes into published content.
- **Provenance in output:** every generated item records source repo + commit + the graph confidence tier it relied on (prefer EXTRACTED facts; treat INFERRED/AMBIGUOUS as leads to verify — see §10).

---

## 10. Risks, assumptions & anti-patterns

**Assumptions.** Source repos benefit from Graphify grounding (true for code + text repos). Claude Code CLI remains the engine. You retarget an existing writing pack rather than authoring cold.

**Risks & mitigations.**
- *Graph grounding quality.* LLM-extracted prose edges are tagged INFERRED/AMBIGUOUS. **Mitigation:** writer prefers EXTRACTED; reviewer verifies claims (Phase 1b). Don't publish inferred facts unchecked.
- *Snapshot staleness.* Wiki/JSON drift after repo edits. **Mitigation:** pin each item to source commit; rebuild graph on meaningful changes (git post-commit hook supported).
- *Unverified tool details.* Graphify HTTP-serve flags, exact `.mcp.json` schema, and third-party licenses are **not fully verified here.** **Mitigation:** confirm with `--help`/repo before scripting; read actual SKILL.md/LICENSE before adopting any §7 pack (star counts on listicles are hype-prone).
- *Marketing hook quality.* LLM hooks trend generic. **Mitigation:** seed persona/format files with hooks you actually like; keep the editor/human gate on social formats.
- *Usage/cost.* Headless Claude Code consumes subscription usage; local LLMs (Ollama/LM Studio on the M-series) can draft/ideate for free but produce weaker long-form. **Mitigation:** batch N generations/day (§5 Phase 2); use local models for ideation/outlines only.
- *Publishing APIs.* Medium API deprecated; LinkedIn restrictive for personal posts; Substack has no official API. **Mitigation:** Phase 3 = "staged draft to copy" for those; automate only where APIs allow.

**Anti-patterns to avoid.**
- Hardcoded axis lists / editing >1 place to add a value (violates §3.2).
- Naive cross-product without the compatibility filter (§4.2).
- Running the writing pack (claude-blog) as-is with its SEO/schema focus intact for thought-leadership content.
- Live-querying a mutating graph during bulk generation (hurts reproducibility) — prefer committed wiki/snapshot + query-for-gaps.

**Refinement note (self-critique).** This doc optimizes for *depth + reproducibility* over *speed to first post*. If early feedback matters more than auditability, compress Phase 1 to a single hardcoded selection on one repo, prove output quality, then introduce the registry/fanout machinery. The registry design also assumes axes stay small enough that full fanout is manageable — if the matrix grows large, a per-entry active/draft flag and a max-items guard on the resolver address it (also deferred, §10.4).

### 10.4 Open decisions deferred to technical requirements

Named here so they're tracked, not buried. These are **implementation choices** that do not change the architecture and are deliberately **not decided** in this overview; each is settled in the downstream technical-requirements/design doc with evidence during the relevant phase.

| # | Deferred decision | Directional constraint it must satisfy | Decide in |
|---|---|---|---|
| D1 | Config/registry serialization (YAML / JSON / TOML / split) | Self-documenting authoring + deterministic machine contract (§4.6) | Phase 1 |
| D2 | Item identity scheme (slug template vs. hash, field order, collisions) | Stable, coordinate+commit-derived, idempotent (§4.4) | Phase 1 |
| D3 | Runtime version minimums (Node/Python) | "Current supported"; meets Claude Code + Graphify needs (§6.1) | Phase 0, at install |
| D4 | Graphify access mix per source (path query vs. MCP-over-Tailscale vs. wiki snapshot) | Read-only; reproducible bulk + live gap-fill (§6.2/§9) | Phase 0/1 |
| D5 | Writing base: fork claude-blog vs. lighter copywriting skills | Persona/format/hook support, retargetable from SEO focus (§7 role 3) | Phase 1 |
| D6 | Scheduled queue-draining policy (batch size, cadence) | Respect usage/cost budget (§5 Phase 2) | Phase 2 |
| D7 | Large-matrix guards (active/draft flag, max-items) | Only if fanout grows unmanageable (§10.3) | When needed |

Add rows as new deferrals surface; promote a row out when its decision is recorded in the technical-requirements doc.

---

## 11. Appendices

### Appendix A — Ordered install sequences (non-binding reference scaffolding)

> **Not a design decision.** This appendix is illustrative reference to show the *shape* of setup, not a fixed spec. Commands, versions, and flags will change — verify against each tool's current docs at install time. Nothing here constrains the architecture; it only informs Phase 0 execution.

**A.1 Base (both Macs)**
```bash
# Homebrew (if not present)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Node LTS + Python + uv/pipx
brew install node python pipx
pipx ensurepath
# uv (fast Python tool installer)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Claude Code CLI — confirm current install method + Node req at code.claude.com/docs
```

**A.2 Graphify (both Macs; PyPI name has two y's)**
```bash
uv tool install graphifyy      # or: pipx install graphifyy
graphify install               # registers the skill/hooks for your assistant
graphify --help | head -5      # verify
```

**A.3 Per source repo (Phase 0)**
```bash
cd /path/to/source-repo
graphify .                     # build graph → graphify-out/
graphify . --wiki              # agent-crawlable wiki export
# optional: keep fresh on commits
graphify . --update            # re-extract changed files only
```

**A.4 Read-only query smoke test**
```bash
graphify query "high level architecture and main components" \
  --graph /path/to/source-repo/graphify-out/graph.json --budget 3000
```

**A.5 Skill/agent packs (into optiquity-content-pipeline env)**
```bash
# examples — read each repo's LICENSE + SKILL.md before adopting
git clone https://github.com/AgriciDaniel/claude-blog.git
git clone https://github.com/alirezarezvani/claude-skills.git
git clone https://github.com/divar-ir/ai-doc-gen.git
git clone https://github.com/LimHyungTae/awesome-claudecode-paper-proofreading.git
git clone https://github.com/wshobson/agents.git
```

### Appendix B — Source & reference list

- Graphify: https://github.com/safishamsi/graphify · https://graphify.net
- claude-blog: https://github.com/AgriciDaniel/claude-blog
- alirezarezvani/claude-skills: https://github.com/alirezarezvani/claude-skills
- divar-ir/ai-doc-gen: https://github.com/divar-ir/ai-doc-gen (builder write-up: Milad Noroozi, Medium)
- paper-proofreading: https://github.com/LimHyungTae/awesome-claudecode-paper-proofreading
- boraoztunc/skills: https://github.com/boraoztunc/skills
- wshobson/agents: https://github.com/wshobson/agents
- VoltAgent subagents: https://github.com/VoltAgent/awesome-claude-code-subagents
- Anthropic Agent Skills: https://www.anthropic.com/engineering (Agent Skills) · https://code.claude.com/docs/en/skills
- Skill round-ups (pattern mining): aiblewmymind.substack.com (39 skills) · dkspeaks Medium (18 skills) · MindStudio Claude-Code content-marketing series
- code-review-graph pairing guide: dev.to "Graphify + code-review-graph"

### Appendix C — Glossary

- **God-node:** highest-degree/betweenness node in a Graphify graph — a central concept; good topic seed.
- **Community:** Leiden-clustered group of related nodes — a natural topic cluster.
- **EXTRACTED / INFERRED / AMBIGUOUS:** Graphify's provenance tags on edges — trust EXTRACTED for published facts.
- **Fanout:** expansion of a multi-select into concrete, compatibility-filtered work items.
- **Registry:** a directory of self-describing axis entries enabling one-file extensibility.

---

## 12. Changelog

| Version | Date | Change |
|---|---|---|
| 0.2.2 | 2026-07-18 | DR-3 (optional editable outline) BUILT — the identity-safe foundation (outline normalizer `N` + `outline_digest`) + the `outline-digest` preimage extension + the `Format=outline` emit bridge (`build_outline_ir`) + the pre-compose outline store (content-addressed, retain-all) + the outline drive path (horn (a) fixed posture, digest-fidelity guard) + the `emit-outline` verb; commits `48393f8`..`db7979a`. Design homes: design §5.2, §7.2, §12.1, §15, §21.1, §27.3. The LLM outline drafter + the R1 compose-input-brief live ablation are deferred (`docs/known-issues.md` DR-3). |
| 0.2.1 | 2026-07-18 | DR-6 increment 1 BUILT (Option A, advisory) — F-a (`ir_version`->2 + generation-tolerant validation `∈ {1,2}`) + the optional `attestation` ledger carrier + the Review-1 two-dimension advisory grounding audit (coverage + faithfulness) + the `grounding_posture` cascading policy & the opt-in fail-open item-level abstain (`grounding-uncovered`); commits `0f6d401`/`aeed34d`/`b92b443`/`7e935a1`. Design homes: design §15, §11.2, §6.3/§12.1, §6.5/§19, §21.7. The hard self-demarcation coverage gate / `.framing` / corpus migration are deferred (`docs/known-issues.md` DR-6). |
| 0.2.0 | 2026-07-05 | Abstraction pass: lifted over-specified minutiae to directional principles — config serialization (§4.6) and item-identity scheme (§4.4) changed from decisions-made to deferred; runtime version pins softened (§6.1); registry/config file extensions de-specified (§8); Appendix A marked non-binding reference; added §10.4 "Open decisions deferred to technical requirements" register. |
| 0.1.0 | 2026-07-05 | Initial draft: architecture, extensible matrix, selection/fanout, phased plan, §7 vetted components by role (incl. editor layer), install requirements. |
