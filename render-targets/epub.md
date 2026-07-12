---
id: epub
provenance: framework
schema_version: 1
writer: epub3
side: external
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# epub — render target (external, framework default)

Realizes the `epub` output-type via the `epub3` writer (design §17 RI12), `side:
external` per the gate-3 default set (§14.2 — an esoteric type): serialize persists the
layer-3 AST and emits the contract payload (RI14); the external actor renders the
layer-4 bytes. The pinned provenance-strip filter covers epub3 exactly as html5 —
provenance/tier tags are explicitly excluded from publishable content (§17, RI14).
Fixed-layout EPUB is a named capability ceiling absorbed by this external path plus
writer-keyed Presentation variables (§14.2, PD8). Declares the pandoc pin bundle of
record (RI13).
