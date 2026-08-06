---
id: pptx
provenance: framework
schema_version: 1
writer: pptx
side: external
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# pptx — render target (external, framework default)

Realizes the `pptx` output-type (design §17 RI12), `side: external` per the gate-3
default set (§14.2 — an esoteric type): serialize persists the layer-3 AST and emits the
contract payload (RI14 — AST + reproducibility sidecar + part structure + metadata bag +
language); the external actor renders the layer-4 bytes with the declared writer + pins.
Bespoke PPTX styling is a named capability ceiling the external path absorbs (§14.2,
PD8). Slides/presenter-notes are Format parts: packaging hints decide 1-vs-N files at
dispatch, never inside the AST (RI9). Declares the pandoc pin bundle of record (RI13).
