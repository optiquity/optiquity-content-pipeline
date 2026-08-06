---
id: pptx
provenance: framework
schema_version: 1
---

# pptx — Output-type entry (framework default)

PowerPoint output (design §5.3). Realized by the `pptx` render target (§17 RI12),
shipping `side: external` (§14.2 — an esoteric type: the external actor renders layer-4
bytes from the layer-3 contract payload). Bespoke PPTX styling is one of the two honest
capability ceilings the external path exists for (§14.2); slides + presenter notes are
Format `parts` (§5.2 Q14), orchestrated by the pipeline, never by the AST (§17 RI9).
