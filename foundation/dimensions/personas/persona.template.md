# Template — Persona entry

Copy this to `personas/<id>.md` and fill it in. One file per audience — adding a persona is a
one-file change (design §5.4 / §3.2). **Never edit this template downstream** — copy it; to adjust
a shipped framework entry, add an `extends:` partial instead of editing it (design §10 rule 2).

The co-located **`personas/_schema.yaml` is the authoritative field list**; design **§5.2** defines
what Persona owns: **AUDIENCE FACTS ONLY** — role/relationship, knowledge level, motivation,
objections, credibility signals. Register/affect is **Voice** (supplied via `default_voice`);
reading context ("skims on mobile") is **Platform** — never Persona. A persona is a coherent
bundle: its facts co-vary, so they replace wholesale on the cascade (never piecewise blends).

There is **no** format-exclusion field — pairing is user-driven and the allow-list is emergent from
configuration (design §8).

## The entry (YAML frontmatter + prose body)

```markdown
---
id: <slug>                       # stable id = filename stem (§7.4 slug); never rename casually
provenance: framework            # framework default entry. Your own private entries use
                                 #   `provenance: instance` + an `x-` filename prefix (§10, §11.4)
schema_version: 1
role: >-                         # who they are professionally, relative to the subject (a fact)
knowledge_level: >-              # what to assume vs. explain (didactic calibration: Persona + Format)
motivation: >-                   # the question they answer / the decision they make
objections:                      # ordered prose items — what makes them dismiss a piece
  - ...
credibility_signals:             # ordered prose items — what earns their trust
  - ...
default_voice: clear-explainer   # the Voice entry id this bundle implies (Q6 / CA2, §12.3)
---

# <id> — Persona entry

Prose notes: positioning intent; why this audience is a coherent bundle. Instance-specific
positioning goals live in `instance/profile.md`, not here.
```
