# Claude Code CLI — usage for this project

How to drive Claude Code against this repo. Keep sessions disposable; keep durable state in
`state.md` and `docs/`.

## Starting a session

- Open Claude Code in the `optiquity-content-pipeline` repo root so it loads `CLAUDE.md` automatically.
- First message pattern: "Read state.md and the relevant mission section, then propose a plan
  for <goal>." This enforces the plan-first gate.
- End a session by having it update `state.md` and propose (not make) a commit.

## Plan mode & approval gates

- Use plan mode for anything non-trivial (installs, multi-file edits, generation runs). The
  assistant should present the plan and stop for your approval before acting.
- `CLAUDE.md` already forbids committing without approval — reinforce verbally if needed.

## Read-only source access (the core safety pattern)

The pipeline reads client repos three ways; all read-only:

- **Targeted query:** `graphify query "…" --graph <repo>/graphify-out/graph.json --budget N`
- **MCP server** (agent traverses the graph itself): serve on the always-on host, point Claude Code's MCP
  config at it over Tailscale (verify flags first).
- **Wiki snapshot:** read `<repo>/graphify-out/wiki/` files — no running process.

Prefer graph queries over reading raw source files (cheaper, and keeps client repos untouched).

## Subagents (Phase 1+)

- Pipeline agents live project-scoped in `.claude/agents/` (version-controlled), not global.
- `researcher` — read-only tools (Read/Grep/Glob + graphify query), pulls grounding.
- `writer` — composes per persona + platform + format.
- `reviewer` (Phase 1b) — detect-first-fix-later editing, claim verification.
- Invoke explicitly ("use the researcher subagent to …") or let Claude delegate. Subagents run
  in isolated context — good for keeping the main session clean during long generation runs.

## Skills / slash commands

- `ideate` and `generate` skills live in `.claude/skills/`; each gets a `/slash` interface.
- Skill content loads on invocation; write standing guidance as persistent rules, not one-shot
  steps (skills aren't re-read every turn).

## Headless (Phase 2, for n8n)

- For scheduled/automated runs, n8n on the always-on host triggers Claude Code headless per approved item
  (e.g. an Execute-Command node running `claude -p "<generation prompt>"`), writing drafts to
  `output/`. Batch a limited number per day to respect subscription usage limits.
- Verify the exact headless invocation/flags against current Claude Code docs before scripting.

## Cost / usage notes

- Interactive and headless runs consume subscription usage. Ideation/outlines can use a local
  model (LM Studio/Ollama) to save budget; final long-form prefers the stronger model.
