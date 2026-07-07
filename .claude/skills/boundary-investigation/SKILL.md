---
name: boundary-investigation
description: Use before editing any registry, template, workspace, or shipped-content surface. Ensures changes respect the framework-vs-instance boundary and the provenance/scope rules (durable rules 2, 4, 5).
allowed-tools: Read, Grep, Glob, Bash
---

# Boundary investigation

Two boundaries an edit in this repo can violate. Investigate both **before** editing.

## 1. Framework vs. instance (rule 5)

- **Framework-owned** (upstream edits these): `CLAUDE.md`, `docs/`, `*.template.*`, `.claude/`,
  `scripts/`, `.github/`, `.gitignore`, `LICENSE`, `README.md`, `quickstart.md`.
- **Instance-owned** (downstream adds these; upstream never touches): populated entries marked
  `provenance: instance`, `instance/profile.md`, `workspaces/<client>/**`, `state.md`.
- Downstream **extends by adding files** and **never edits framework files.** If a change wants to
  alter framework behavior, that's framework work (here), not an instance edit.

## 2. Provenance vs. scope (design-decisions.md §3.9)

- **Provenance** = `provenance: framework | instance` (metadata). Framework ships **generic default
  entries/recipes** marked `provenance: framework` — those are welcome in the public repo (rule 4,
  narrowed).
- **Scope** = location: shared `<dimension>/` = global; `workspaces/<client>/<dimension>/` =
  client-specific.

## STOP-and-report if an edit would…

- put `provenance: instance` or any **client-specific** content into a framework/public path (rule 4);
- reference a client workspace from a shared/global entry, or leak one workspace's content into
  another (rule 2);
- edit a framework file to encode instance-specific behavior (extend by adding a file instead — rule 5);
- touch a source/client repo in any way (rule 1 — those are read-only, always).

## Reference

CLAUDE.md durable rules 1/2/4/5 · `docs/design-decisions.md` §3.9.
