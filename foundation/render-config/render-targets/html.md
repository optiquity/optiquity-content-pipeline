---
id: html
provenance: framework
schema_version: 1
writer: html5
side: internal
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# html — render target (internal, framework default)

Realizes the `html` output-type via the `html5` writer (design §17 RI12): in-system
`pandoc -f json -t html5` over the persisted layer-3 AST (§14.2 — internal per the gate-3
default set). The pinned provenance-strip filter runs pre-serialize for this writer —
html5 would otherwise emit provenance attributes into published bytes; the filter is
serialize-owned and no style configuration can disable it (§17, PD3). Declares the pandoc
pin bundle of record (RI13); the filter's own version/hash joins the render-binding at
the serialize step.
