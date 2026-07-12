---
id: pdf
provenance: framework
schema_version: 1
writer: pdf
side: external
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# pdf — render target (external, framework default)

Realizes the `pdf` output-type (design §17 RI12). **Ships `side: external` with `engine`
unset — the gate-3 disposition of record (step-06 parameter sheet item 4):** serialize
persists the layer-3 AST and emits the contract payload (RI14); the external actor
produces the PDF bytes. Internalizing pdf later is a config edit with zero rework: pin an
engine here (typst was pre-identified), flip `side` to internal, and the engine pin joins
the RI13 bundle (§14.2 — internal vs external is a setting, not a format property).
Declares the pandoc pin bundle of record (RI13).
