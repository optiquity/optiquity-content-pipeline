---
id: repo-docs
provenance: framework
schema_version: 1
roles:
  - role: readme
    skeleton:
      format: readme
      goals: [explain]
      topic_slot: the repository itself — what it is and why it matters
  - role: getting-started
    skeleton:
      format: long-form-essay
      goals: [explain, try-it]
      topic_slot: the shortest honest path from zero to a first result
  - role: architecture
    skeleton:
      format: long-form-essay
      goals: [explain]
      topic_slot: how the system is shaped and why
---

# repo-docs — folio-type entry (framework default)

The design's own example blueprint (§9.6: `repo-docs -> roles: [readme,
getting-started, architecture]`): a typed folio whose members document one repository.

Roles + per-role recipe skeletons, NEVER dimension values (the §9.6 DIRECTIVE): each
skeleton names the member's shape — a shipped Format genre, a goal-set, a prose
`topic_slot` the generating run fills with a concrete workspace topic. One typed-folio
generation run pins one source commit-map + one effective source-subset at
begin-session and fans out one recipe per role, so members share grounding BY
CONSTRUCTION — same pool + same pinned commits, never same facts (B4-2). Each member's
role slug is recorded on its member record at add-time (B4-3); structural order is
reconstructable from this declared role list + those records (§9.6).

Every id in the skeletons resolves to a shipped framework entry (formats `readme`,
`long-form-essay`; goals `explain`, `try-it`) — live blueprint, no dead keys.
