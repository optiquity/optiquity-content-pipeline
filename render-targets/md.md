---
id: md
provenance: framework
schema_version: 1
writer: markdown
side: internal
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# md — render target (internal, framework default)

Realizes the `md` output-type (design §17 RI12): in-system `pandoc -f json -t markdown`
over the persisted layer-3 AST (§14.2 — an easy type, internal per the gate-3 default
set). Declares the pandoc pin bundle of record (RI13).
