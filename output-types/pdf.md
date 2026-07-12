---
id: pdf
provenance: framework
schema_version: 1
---

# pdf — Output-type entry (framework default)

PDF output (design §5.3). Realized by the `pdf` render target (§17 RI12), which ships
`side: external` with the engine unset in v1 (gate-3 disposition; step-06 parameter
sheet item 4): the external actor produces the PDF bytes from the layer-3 contract
payload. Internalizing later = pin an engine on the render target and flip its `side` —
a config edit, zero rework (§14.2).
