---
id: academic-paper
provenance: framework
schema_version: 1
section_schema:
  - rule: presence
    axis: role
    value: abstract
    required: true
    severity: error
  - rule: presence
    axis: role
    value: methods
    required: true
    severity: error
  - rule: presence
    axis: role
    value: results
    required: true
    severity: error
  - rule: order
    selectors:
      - axis: role
        value: abstract
      - axis: role
        value: methods
      - axis: role
        value: results
    severity: warning
  - rule: length
    axis: role
    value: abstract
    min_len: 0
    max_len: 2500
    severity: warning
---

# academic-paper — Format entry (framework default)

The scholarly research-paper genre (design §5.2 — a platform-agnostic genre): a single,
self-contained report of one investigation, structured so a reader can locate the claim, the
evidence, and the method that produced it without reading linearly. Outline-shaped: the body IS
a sectioned skeleton (DR-3), and its sections carry declared ROLES that the typed-section
conformance contract in this entry's frontmatter checks (DR-4).

Rhetorical structure (authoring reference; §15; the section ROLES the `section_schema` references):

1. **Abstract** (`#abstract`) — a self-contained precis: the question, what was done, and the
   headline finding, in a few sentences; no citations, no undefined abbreviations.
2. **Introduction** (`#introduction`) — the problem, why it matters, and the specific claim this
   paper defends; grounded context first (EXTRACTED-tier facts as stated fact, §6.5).
3. **Methods** (`#methods`) — what was done, in enough detail to be reproduced: materials,
   procedure, and analysis, described so the results below are traceable to them.
4. **Results** (`#results`) — what was observed, reported neutrally and kept separate from
   interpretation; figures and tables carry the data, the prose carries the reading.
5. **Discussion** (`#discussion`) — what the results mean for the claim, the limits of the
   evidence, and the threats that could invalidate it (INFERRED/AMBIGUOUS leads live here as
   flagged questions, never as findings, §6.5).
6. **Conclusion** (`#conclusion`) — the claim restated with what the reader now knows; no new
   evidence introduced here.
7. **Acknowledgements** (`#acknowledgements`) — optional contributions and support. Whether a
   venue forbids or requires it is the selected Platform's tightening (`format_structural`,
   §12.7), never the genre's.

Discipline: one investigation per paper — a second, separable study is a second artifact (§5.2).
Single-part genre: `parts` rides the schema floor (Q14); the sections above are the rhetorical
skeleton of one document, not sub-outputs. No platform data lives here (Q4): which journal or
venue this is fitted to — and any per-venue section tightening — arrives from the selected
Platform's projections at render time (§12.3, §12.7).

The typed-section conformance contract (`section_schema`, DR-4) declared above requires an
`abstract`, `methods`, and `results` section (role selectors, error severity), asks for the
canonical abstract → methods → results order (warning), and caps the abstract's length (warning).
The roles are author-declared here; they are never structural `type` kinds (which name genre-
neutral STRUCTURAL shapes only: prose, figure, table, callout).

This body is human-authoring REFERENCE — it is NOT a compose input: the writer receives only the
bound attributes, the `parts`/`section_schema` structure, the grounded facts, and (when set) the
DR-3 outline drive brief; this body is never threaded to the writer (§15).
