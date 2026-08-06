---
id: project-manual
provenance: framework
schema_version: 1
parts: []
section_schema:
  - rule: presence
    axis: role
    value: what-it-is
    required: true
    severity: error
  - rule: presence
    axis: role
    value: setup
    required: true
    severity: error
  - rule: presence
    axis: role
    value: usage
    required: true
    severity: warning
  - rule: order
    selectors:
      - axis: role
        value: what-it-is
      - axis: role
        value: setup
      - axis: role
        value: usage
    severity: warning
---

# project-manual — Format entry (framework default)

The repository operator's-manual genre (design §5.2 — a platform-agnostic genre): a README-PLUS
reference a reader consults to stand a project up and keep it running — broader and more complete
than the terse `readme` front-door. Where `readme` answers "what is this and how do I get a first
result", the project manual is the fuller manual: the same orientation, but with setup and everyday
operation carried in enough depth to be worked from, not skimmed.

Outline-shaped: `parts: []` is a single flat body (Q14; §15 flat-body collapse — 0 declared parts →
one flat body), so when a DR-3 outline drives it the composed body IS a sectioned skeleton and the
base typed-section gate checks it (DR-4).

Rhetorical structure (the section ROLES the `section_schema` references; the kinds of sections a
repo manual carries):

1. **What it is** (role `what-it-is`) — what the project does and who it is for, in the reader's
   terms; the paragraph that lets a reader decide whether to keep reading.
2. **Setup** (role `setup`) — the path from nothing to a working install: prerequisites, install
   steps, and the first configuration — every command grounded in the source repo (EXTRACTED-tier
   facts only, §6.5; never invented flags or paths).
3. **Usage** (role `usage`) — how the project is actually operated day to day: the most-wanted
   tasks, each with a worked example traced to real behavior.
4. **Reference / operations** (optional) — deeper material a manual carries but a readme omits:
   configuration surface, common failure modes, and where to go next. Optional sections ride no
   `section_schema` rule; a venue may tighten them via the selected Platform (`format_structural`,
   §12.7), never the genre.

Discipline: heavily grounded — every command, flag, path, and behavior traces to the source repo
(§3.3, §6.5). Single-part genre: `parts` rides the schema floor as `[]` (Q14); the sections above
are one document's heading skeleton, not sub-outputs. No platform data lives here (Q4): which
destination this manual is fitted to arrives from the selected Platform at render time (§12.3).

The typed-section conformance contract (`section_schema`, DR-4) declared above requires a
`what-it-is` and a `setup` section (role selectors, error severity), asks for a `usage` section and
the canonical what-it-is → setup → usage order (both warning), and is enforced at the compose base
structural gate against the composed body's sections. The roles are author-declared here as
role-axis selectors; they are never structural `type` kinds (which name genre-neutral STRUCTURAL
shapes only: prose, figure, table, callout).

This body is human-authoring REFERENCE — it is NOT a compose input: the writer receives only the
bound attributes, the `parts`/`section_schema` structure, the grounded facts, and (when set) the
DR-3 outline drive brief; this body is never threaded to the writer (§15). The REUSABLE per-section
authoring INTENT for this genre lives on its starter outline (the DR-3 outline drive), not in this
entry.
