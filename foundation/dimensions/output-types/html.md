---
id: html
provenance: framework
schema_version: 1
---

# html — Output-type entry (framework default)

HTML output (design §5.3). Realized by the `html` render target (§17 RI12; writer
`html5`), shipping `side: internal` (§14.2 — an easy type). The pinned provenance-strip
filter runs pre-serialize for this writer — provenance attributes never reach published
bytes (§17, serialize-owned, never a Presentation lever).
