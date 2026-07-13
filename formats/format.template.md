# Template — Format entry

Copy this to `formats/<id>.md` and fill it in. One file per genre — adding a format is a one-file
change (design §5.4 / §3.2). **Never edit this template downstream** — copy it; to adjust a shipped
framework entry, add an `extends:` partial (design §10 rule 2).

The co-located **`formats/_schema.yaml` is the authoritative field list**; design **§5.2** defines
Format as a **platform-agnostic genre** — the rhetorical structure/genre that shapes the IR (§15).
Key consequences:

- Formats carry **no** platform-pairing or persona-exclusion data (Q4, §8): pairing is user-driven;
  the allow-list is emergent from configuration.
- Word limits are **Platform** `hard_limits`/`advisory_norms` (§5.3), not a Format field.
- The genre's rhetorical structure/outline is the **entry body prose** (consumed at compose, §15),
  not a config attribute.
- The only structural attribute is **`parts`** — an ordered list of named intra-genre sub-outputs
  (e.g. `slide-deck → [slides, presenter-notes]`), defined entirely inside this one entry (Q14).
  Composing two genres is **two artifacts** grouped by a folio, never a composite.

## The entry (YAML frontmatter + prose body)

```markdown
---
id: <slug>                       # stable id = filename stem (§7.4 slug)
provenance: framework            # framework default entry; private entries use `instance` + `x-` (§10, §11.4)
schema_version: 1
parts: []                        # optional ordered sub-outputs, e.g. [slides, presenter-notes]; [] = single-part
---

# <id> — Format entry

Prose body: describe the genre's rhetorical structure/outline, hook expectation, and grounding
depth. This body IS the format contract the writer composes against (§15).
```
