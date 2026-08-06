---
id: explainer-post
provenance: framework
schema_version: 1
persona: technical-evaluator
format: short-opinion-post
goals: [explain]
---

# explainer-post — recipe entry (framework default)

The framework's default recipe (design §10: default recipes are framework-shipped):
one short, grounded explainer for a technical evaluator. **recipe -> one artifact**
(§8) — this binds the content side; rendering is routed at run.

What it sets (every ref resolves to a shipped framework entry — live config):

- `persona: technical-evaluator` · `format: short-opinion-post` · `goals: [explain]`.

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
