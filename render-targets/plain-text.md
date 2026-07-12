---
id: plain-text
provenance: framework
schema_version: 1
writer: plain
side: internal
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# plain-text — render target (internal, framework default)

Realizes the `plain-text` output-type via the `plain` writer (design §17 RI12):
in-system `pandoc -f json -t plain` over the persisted layer-3 AST (§14.2 — an easy
type, internal: the writer ships in the pinned binary; no engine, no external
tooling). The plain writer emits no markup at all, so provenance attributes cannot
survive into published bytes without any filter — provenance is consumed at the
IR/AST layers (RI8). Declares the pandoc pin bundle of record (RI13).
