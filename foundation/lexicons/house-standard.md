---
id: house-standard
provenance: framework
schema_version: 1
spelling: us
preferred_terms:
  utilize: use
  leverage: use
banned_terms:
  - irregardless
proper_names:
  github: GitHub
  javascript: JavaScript
  typescript: TypeScript
  api: API
mechanical:
  oxford_comma: true
---

# house-standard — a generic framework house-style Lexicon (framework default)

An illustrative, non-client house-style lexicon shipped as the framework's worked example
of the DR-2 class-(ii) style carrier. It encodes only UNIVERSAL editorial hygiene and
public technology-name casing — deliberately no real organization's private glossary, no
client terminology, no impersonation. Extend, don't edit (§10 rule 5): author a new lexicon
entry (or an instance `x-*` lexicon) rather than editing this one.

Every rule this lexicon imposes lives in the frontmatter ATTRIBUTES above — this is the
ratified identity invariant (see `lexicons/_schema.yaml`): the attributes are the only
compose-consumed surface, and this BODY is documentation only, never read by compose. What
the attributes say:

- **spelling: us** — enforce US spelling. (The floor `""` would mean "no spelling rule".)
- **preferred_terms** — prefer plain verbs: `utilize → use`, `leverage → use`.
- **banned_terms** — `irregardless` is non-standard; never publish it.
- **proper_names** — canonical casing for common technology names: `GitHub`, `JavaScript`,
  `TypeScript`, `API`.
- **mechanical.oxford_comma: true** — use the serial (Oxford) comma.

Because the lexicon is attribute-only, its contribution to identity is the `delta_vs_floor`
over these attributes (§7.2); this prose can be rewritten freely without changing a single
composed byte. At C1 the registry is UNWIRED — no artifact consumes a lexicon yet; C2
threads the resolved lexicon into the artifact-id preimage.
