# Agents & Skills — Sourcing & Build Manifest

> **Status:** Living document · **Last updated:** 2026-07-13
> Framework-owned. This is the actionable build sheet for the pipeline's agents and skills:
> what each is, why it exists, exactly where it comes from, and what action produces it.
> Companion to `docs/mission.md` §7 (which vets the sources) — this doc turns that vetting into
> a build plan. Verify every license before copying anything (see §6).

## 0. How to read this — action legend

Every agent and skill below has an **ACTION** that tells you precisely how to produce it:

| Action | Meaning |
|---|---|
| **INSTALL** | Install as an external dependency/tool. Not authored by us. |
| **AUTHOR** | Write from scratch as an original file in this repo (project-specific glue). May reference an external *approach* without copying text. |
| **DOWNLOAD-ADAPT** | Clone the source into a local, gitignored `reference/` dir, lift its architecture/prompt patterns, then **author our own retargeted file**. Keep attribution. |
| **COPY-VERBATIM** | Copy the source file near-as-is (minimal edits) — **only from a confirmed permissive license** — with attribution. |

**Why mostly AUTHOR / DOWNLOAD-ADAPT, not wholesale install:** the vetted packs are tuned for
SEO/marketing (schema, FAQ blocks, keyword scoring). We want thin, persona/positioning-targeted
files we can reason about and that stay MIT-clean. So we treat the OSS repos as **references to
learn from**, not dependencies to inherit. The one place near-verbatim reuse is sensible is
proofreading (a well-solved, generic task).

`reference/` is gitignored — external repos are never committed into this MIT framework (avoids
license contamination). We consult them there and author originals under `.claude/`.

---

## 1. Source repositories catalog

| # | Repo | URL | License | What it gives us |
|---|---|---|---|---|
| S1 | safishamsi/graphify | https://github.com/safishamsi/graphify | MIT (confirmed) | Read-only knowledge-graph grounding tool (the pipeline's grounding layer). |
| S2 | AgriciDaniel/claude-blog | https://github.com/AgriciDaniel/claude-blog | MIT (public repo) | Writer architecture: persona voice profiles, multi-pass QA, delivery contract, hero/hook ladder. |
| S3 | alirezarezvani/claude-skills | https://github.com/alirezarezvani/claude-skills | OSS — verify | `content-strategy`, `copy-editing`, customer-persona, `content-humanizer` skills. |
| S4 | brianrwagner ai-marketing skills (`content-idea-generator`) | listing: https://crossaitools.com/skills/brianrwagner/ai-marketing-claude-code-skills/content-idea-generator | OSS — verify + locate canonical repo | Idea "positioning gate" + 3-test filter (specific / hook-angle / persona-fit). |
| S5 | boraoztunc/skills | https://github.com/boraoztunc/skills | OSS — verify | `ogilvy` copywriting skill; adversarial multi-agent review pattern. |
| S6 | divar-ir/ai-doc-gen | https://github.com/divar-ir/ai-doc-gen | OSS — verify | 5-facet code-doc decomposition (Structure / Data-Flow / Request-Flow / Dependency / API). |
| S7 | LimHyungTae/awesome-claudecode-paper-proofreading | https://github.com/LimHyungTae/awesome-claudecode-paper-proofreading | OSS — verify | Detect-first-fix-later proofreading prompts (safe, gated editing). |
| S8 | VoltAgent/awesome-claude-code-subagents | https://github.com/VoltAgent/awesome-claude-code-subagents | OSS — verify | 150+ subagent definitions incl. documentation-generator; canonical agent-file structure. |
| S9 | wshobson/agents | https://github.com/wshobson/agents | OSS — verify | Agent scaffolds + `plugin-eval` (static / LLM-judge / Monte Carlo) for quality gating. |
| S10 | Anthropic Agent Skills + Claude Code docs | https://www.anthropic.com/engineering (Agent Skills) · https://code.claude.com/docs | Docs | The SKILL.md / agent frontmatter spec we author against. |

**Acquire the references once (local, gitignored):**

```bash
mkdir -p reference
git clone https://github.com/safishamsi/graphify                       reference/graphify
git clone https://github.com/AgriciDaniel/claude-blog                  reference/claude-blog
git clone https://github.com/alirezarezvani/claude-skills              reference/claude-skills
git clone https://github.com/boraoztunc/skills                         reference/boraoztunc-skills
git clone https://github.com/divar-ir/ai-doc-gen                       reference/ai-doc-gen
git clone https://github.com/LimHyungTae/awesome-claudecode-paper-proofreading reference/paper-proofreading
git clone https://github.com/VoltAgent/awesome-claude-code-subagents   reference/voltagent-subagents
git clone https://github.com/wshobson/agents                           reference/wshobson-agents
```

---

## 2. Agents

Each agent is a file under `.claude/agents/<name>.md`. **researcher** is a shared support agent —
the writing agents call it rather than touching client repos themselves (this is what makes the
read-only guarantee enforceable).

### researcher — `.claude/agents/researcher.md`
- **Why:** The single read-only choke-point into client repos. Queries Graphify graphs and returns
  a structured grounding brief (facts + confidence tiers + source locations). Keeps every writing
  agent out of raw source.
- **ACTION: AUTHOR.** Original glue (Graphify query wiring + read-only tool scoping: Read/Grep/Glob
  + `graphify query` only, no write tools).
- **Reference for structure:** S8 (agent frontmatter), S10 (spec).
- **Depends on:** S1 Graphify (INSTALL) + skill `ground-repo`.
- **MVP:** yes.

### ideation — `.claude/agents/ideation.md`
- **Why:** Stage 1 of the two-stage pipeline. Turns a repo's god-nodes/communities/questions +
  your personas into ranked content ideas → the queue. Pairing is user-driven — no filter vetoes a
  combination; the effective allow-list is emergent from configuration (design §8).
- **ACTION: DOWNLOAD-ADAPT** from S3 `content-strategy` (pillars/topic-clusters, impact-fit scoring)
  and S4 `content-idea-generator` (positioning gate + 3-test filter). Retarget scoring to your five
  personas; strip SEO/keyword bias.
- **Depends on:** skills `idea-generate`, `persona-voice`, `hook-craft`, `select-and-fanout`.
- **MVP:** yes.

### writer — `.claude/agents/writer.md`
- **Why:** Stage 2 core for marketing/general content (blog, LinkedIn, Medium, general). Persona /
  platform / format-aware composition from the researcher's brief.
- **ACTION: DOWNLOAD-ADAPT** from S2 claude-blog (persona voice + multi-pass QA + delivery-contract
  architecture) and S5 `ogilvy` (copy discipline). Retarget from SEO/AI-citation to thought-
  leadership/positioning.
- **Depends on:** skills `persona-voice`, `format-spec`, `platform-adapt`, `hook-craft`,
  `chart-figure` (optional).
- **MVP:** yes.

### docs-writer — `.claude/agents/docs-writer.md`
- **Why:** Code-grounded technical docs (how-to, explainer, README). Split from `writer` because the
  mode is accuracy-over-persuasion with deeper structural grounding.
- **ACTION: DOWNLOAD-ADAPT** the *approach* from S6 ai-doc-gen (5-facet decomposition) into an
  authored agent prompt. **Optional alternative:** INSTALL and run ai-doc-gen standalone (Python,
  GitLab-oriented) for very deep technical docs and feed its output in — heavier, only if the
  authored agent proves insufficient.
- **Depends on:** skills `persona-voice`, `format-spec`, `chart-figure`.
- **MVP:** no — see §4 (start merged into `writer`, split on evidence).

### reviewer — `.claude/agents/reviewer.md`
- **Why:** Quality gate: detect-first-fix-later editing, claim verification against EXTRACTED graph
  facts, hook/voice enforcement, anti-slop. Open-ended slot — more editors attach here later.
- **ACTION: COPY-VERBATIM/ADAPT** the detect-first-fix-later prompt from S7 paper-proofreading
  (confirm license first), plus DOWNLOAD-ADAPT from S3 `copy-editing` and `content-humanizer`.
- **Depends on:** skills `proofread-verify`, `persona-voice`, `format-spec`, `platform-adapt`.
- **MVP:** no — Phase 1b.

---

## 3. Skills

Each skill is `.claude/skills/<name>/SKILL.md`. Some double as `/slash` commands for you.

| Skill | Why it exists | ACTION + source | Used by |
|---|---|---|---|
| **ground-repo** | Read-only Graphify query discipline (access pattern, token budget, confidence-tier handling) + grounding-brief output schema. | **AUTHOR** (glue over S1). | researcher |
| **select-and-fanout** | The resolver: selection → fanout → concrete idempotent item list (no pairing veto — the allow-list is emergent from configuration, design §8). Core matrix mechanism + one-off/scheduled entry point. | **AUTHOR** (original). | ideation, orchestration, you (slash) |
| **idea-generate** | Ideation procedure + quality filter (specific / hook-angle / persona-fit) so ideas aren't generic. | **DOWNLOAD-ADAPT** from S4 (filter) + S3 (strategy). | ideation |
| **persona-voice** | Loads a persona file and applies tone / knowledge level / objections. "One skill per audience" so the writer never blends audiences. | **AUTHOR** from your persona registry; pattern from S3 customer-persona + Voice-DNA idea. | writer, docs-writer, reviewer, ideation |
| **format-spec** | Applies a format's constraints — word limit, structure, visual needs, hook requirement. | **AUTHOR** from your format registry. | writer, docs-writer, reviewer |
| **platform-adapt** | Shapes content to a platform's conventions (length norms, formatting, image support, publish path). | **AUTHOR** from your platform registry; patterns from S2 platform handling. | writer, reviewer |
| **hook-craft** | Hook/opening patterns for attention formats (LinkedIn/Medium) — the weakest LLM area, worth encoding good examples. | **DOWNLOAD-ADAPT** from S2 hero/hook ladder + S4 hook templates. | writer, ideation |
| **proofread-verify** | Detect-first-fix-later checklist + claim verification against graph facts + anti-slop pass. | **COPY-VERBATIM/ADAPT** from S7 + S3 `content-humanizer`. | reviewer |
| **chart-figure** *(optional)* | Deterministic charts/diagrams via code execution (matplotlib/Mermaid) for visual formats. | **AUTHOR** (code-exec glue). | writer, docs-writer |

---

## 4. Build order & MVP subset

Prove one thread before building the rest (mission §10 refinement).

**MVP (prove-one-thread):**
1. INSTALL S1 Graphify.
2. AUTHOR `ground-repo` skill + `researcher` agent.
3. AUTHOR `select-and-fanout` skill (+ your registries populated).
4. AUTHOR `persona-voice`, `format-spec` skills.
5. DOWNLOAD-ADAPT `writer` agent (from S2/S5) — run it in a single mode; **do not split
   docs-writer yet**.
6. DOWNLOAD-ADAPT `ideation` agent + `idea-generate` skill.
7. Run: one topic × one persona × one format → one grounded, reviewed-by-eye draft.

**Phase 1 completion:** add `platform-adapt`, `hook-craft`, `chart-figure`.

**Phase 1b:** add `reviewer` + `proofread-verify`; split `docs-writer` **only if** technical-doc
accuracy demands the ai-doc-gen decomposition.

**Optional dev tooling:** S9 `plugin-eval` to score/gate skill quality (fits your spreadsheet-
tracked, measurement-oriented style).

---

## 5. Dependency map (who uses what)

```
researcher ── ground-repo ──> Graphify(S1)   [read-only into client repos]
ideation   ── idea-generate, persona-voice, hook-craft, select-and-fanout ──> researcher
writer     ── persona-voice, format-spec, platform-adapt, hook-craft, chart-figure ──> researcher
docs-writer── persona-voice, format-spec, chart-figure ──> researcher     [Phase 1b]
reviewer   ── proofread-verify, persona-voice, format-spec, platform-adapt [Phase 1b]
```

---

## 6. License & attribution checklist (do before copying anything)

- [ ] Confirm the LICENSE in each cloned repo under `reference/` (S3–S9 marked "verify").
- [ ] **COPY-VERBATIM only from confirmed-permissive (MIT/BSD/Apache) sources** (currently S1, S2
      confirmed; S7 to confirm before verbatim copy).
- [ ] For DOWNLOAD-ADAPT, author original text — don't paste; retarget the approach. Retain a
      `SOURCES.md` note per adapted file crediting the origin.
- [ ] Never commit `reference/` into this MIT framework repo (it's gitignored).
- [ ] Locate S4's canonical GitHub repo before relying on it (currently only a listing URL).
- [ ] Keep an attribution list in the public README for any adapted/copied material.

---

## 7. Weaknesses, assumptions, refinements

- **`writer` vs `docs-writer` split may be premature** — start merged (one `writer` switching mode
  by format); split only if technical accuracy demands ai-doc-gen's decomposition. Reflected in §4.
- **Skill granularity risk** — `persona-voice` / `format-spec` / `platform-adapt` could collapse
  into one `apply-registries` skill. Kept separate to map 1:1 to the three independent axes and
  extend one-file-at-a-time; consolidate if it feels over-fragmented.
- **Retarget leakage** — seed repos carry SEO/AI-citation DNA. The persona files and a `CLAUDE.md`
  house-style rule must explicitly say "no SEO scaffolding (schema/FAQ/keyword blocks)" or the
  wrong intent leaks into thought-leadership content.
- **Unverified sources** — S3–S9 licenses and S4's canonical repo need confirmation before any
  copy. Patterns are safe to learn from; verbatim text is not until confirmed.
- **ai-doc-gen runtime mismatch** — it's a standalone Python/GitLab tool, not a Claude Code agent.
  Adapting its *approach* is recommended; running it standalone is a heavier optional path.
