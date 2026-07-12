---
id: plain
provenance: framework
schema_version: 1
---

# plain — the Presentation schema floor (framework, mandatory)

The built-in framework floor entry (PD7, design §5.3). It sets **no** attributes: every
lever rides the schema default, which is Pandoc's built-in look per writer — the honest
fallback. Presentation is not in the mandatory-global set (§12.3); when nothing selects a
presentation, `plain` applies, and shipping the dimension causes zero id churn (PD5,
§7.2 — the delta vs the floor is empty).

Do not edit this entry to restyle output (extend-don't-edit, §10 rule 2): author a new
presentation entry (or an instance `x-*` entry) and select it.
