---
id: project-manual
provenance: framework
schema_version: 1
persona: technical-documentation-writer
format: project-manual
goals: [explain, try-it]
---

# project-manual — recipe entry (framework default)

A framework-shipped starter recipe for the project-manual genre (design §10: default
recipes are framework-shipped): one grounded, hands-on project manual for a technical
documentation writer — understand the system, then try it. **recipe -> one artifact**
(§8) — this binds the content side; the genre's section structure binds at run, and
rendering is routed there too.

What it sets (every ref resolves to a shipped framework entry — live config):

- `persona: technical-documentation-writer` · `format: project-manual` ·
  `goals: [explain, try-it]`.

What it deliberately leaves unset:

- **topic** — supplied by the workspace/selection/run (§5.2: topics are client
  editorial data; a recipe generates nothing until a topic binds, loudly, §11.1).
- **voice** — so the §12.3 chain resolves naturally: the persona's `default_voice`
  (CA2) over the instance's L2/L3 scope defaults; setting a voice here would pin L5
  over both (see recipes/_schema.yaml).
- **platforms / languages / output_types / presentations** — targets supplied at run
  (§8); Language and Output-type then come from the CA8 mandatory globals,
  Presentation from the `plain` floor (PD7).

Customize by `extends:` partial or a new `x-` recipe file (§10 rule 2, §11.4, §5.4) —
never by editing this entry.
