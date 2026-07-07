---
name: dependency-intake
description: Use when evaluating whether to adopt a third-party tool, library, or skill/agent pack. Codifies necessity, maintenance health, license, security, fit, and exit-plan checks.
allowed-tools: Read, Grep, Glob, Bash, WebSearch, WebFetch
---

# Dependency intake

Evaluate a candidate dependency across all of:

- **Necessity** — what does it give us we can't cheaply author ourselves? Our bias is to **author
  thin** and adopt externally only when the burden is real (e.g. Pandoc for rendering, Graphify for
  grounding).
- **Maintenance health** — recent commits, release cadence, issue responsiveness, bus factor.
- **License** — confirm the actual `LICENSE` file. MIT/BSD/Apache = safe to depend on or adapt. GPL =
  fine to **invoke as an external CLI tool** (subprocess — e.g. Pandoc, Graphify) but **never vendor
  or copy** its code into this MIT framework.
- **Security** — supply-chain surface, secrets handling, network calls.
- **Technical fit** — does it match our architecture (read-only sources, IR + renderer, adapter
  registries) and runtime?
- **Exit plan** — how hard to replace? Is it behind an adapter (source/renderer) so it's swappable?

## Output — a recommendation

**INSTALL** (external tool) · **DOWNLOAD-ADAPT** (learn from it, author our own) · **AUTHOR** (build
ourselves) · **REJECT** — with the reasoning and an explicit license note.

## Reference

`docs/mission.md` §7 (component vetting) · `docs/agents-and-skills-sourcing.md`.
