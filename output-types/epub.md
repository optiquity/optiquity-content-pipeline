---
id: epub
provenance: framework
schema_version: 1
---

# epub — Output-type entry (framework default)

EPUB output (design §5.3). Realized by the `epub` render target (§17 RI12; writer
`epub3`), shipping `side: external` (§14.2 — an esoteric type). The pinned
provenance-strip filter covers the epub3 writer exactly as it covers html5 (§17);
fixed-layout EPUB is a named capability ceiling absorbed by the external layer-4 path
(§14.2, PD8).
