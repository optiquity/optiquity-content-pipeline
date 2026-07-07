---
name: documentation
description: Use when verifying external tool/library/CLI behavior against primary sources, or auditing docs for drift. Codifies primary-source verification and fact-vs-inference labeling.
allowed-tools: Read, Grep, Glob, Bash, WebSearch, WebFetch
---

# Documentation research

## Verify against primary sources

- Official docs, the tool's own `--help`, and the source repo — **not** training data or memory.
- Never extrapolate one tool's behavior to another (Claude Code ≠ Codex ≠ Gemini; Graphify flags are
  Graphify's, not a generic assumption). Check the specific tool **and version** (CLAUDE.md rule 8).

## Label every claim

- **VERIFIED** — backed by a cited primary source (with the source).
- **INFERRED / ASSUMED** — plausible but unconfirmed; flag it for the reader to verify.

Keep the two clearly separated in your report. Note the version you verified against and flag
behavior that may differ across versions.

## Targets for this repo

Claude Code agent/skill spec (`code.claude.com/docs`), Graphify CLI + flags
(`github.com/safishamsi/graphify` + `--help`), Pandoc capabilities/output types, MCP schemas.

## Internal recall

For repo-internal recall, use the knowledge graph **first** (`graphify query` against the injected
`--graph` path, when available), then `grep`/`Read` to verify. Doing the whole recall in grep is a
recall defect.

## Output

A research report that separates **VERIFIED** facts (with sources) from **INFERRED** leads.
