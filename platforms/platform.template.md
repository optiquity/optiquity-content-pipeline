# Template — Platform entry

Copy this to `platforms/<id>.md` and fill it in. One file per publishing platform — adding a
platform is a one-file change (design §5.4 / §3.2). **Never edit this template downstream** — copy
it; to adjust a shipped framework entry, add an `extends:` partial (design §10 rule 2).

The co-located **`platforms/_schema.yaml` is the authoritative field list**; design **§5.3** defines
Platform as a **destination + constraint layer, selected per deliverable** (routing, never an
instance-wide baseline, never a folio property). It is the one dimension whose entries **project**
cross-dimension values into the cascade. Two ratified constraint classes (CA9, §12.7): **advisory
norms** ride the cascade (a recipe/run may deviate with a one-time warning); **hard limits** live
outside the cascade, enforced only at the reconcile gate (§16). A Platform entry carries **no**
format-pairing data — pairing is user-driven (design §8).

## The entry (YAML frontmatter + prose body)

```markdown
---
id: <slug>                       # stable id = filename stem (§7.4 slug)
provenance: framework            # framework default entry; private entries use `instance` + `x-` (§10, §11.4)
schema_version: 1
destination: >-                  # prose: where deliverables routed here are published (humans/review)
advisory_norms: {}               # named advisory values that RIDE the cascade (e.g. preferred_char_count)
hard_limits: {}                  # named hard-feasibility ceilings enforced at §16 only (e.g. post_char_limit)
format_advisories: {}            # per-format advisory refinements: {<format-id>: {<advisory>: <value>}}
reconcile_strategy_defaults: {}  # per-format strategy defaults: {<format-id>: adapt|split|pass|truncate}
default_output_type: ""          # weak platform-implied output-type id, or "" for none
---

# <id> — Platform entry

Prose notes: the platform's conventions, publish path, image support, any routing caveats.
```

`reconcile_strategy` (default `adapt`) is the schema's L0 floor and is normally set by recipe/run,
not on the entry — see `platforms/_schema.yaml` for the full attribute definitions.
