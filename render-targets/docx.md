---
id: docx
provenance: framework
schema_version: 1
writer: docx
side: internal
pandoc_version: "3.10"
pandoc_api_version: [1, 23, 1, 2]
reader: markdown+fenced_divs+bracketed_spans
---

# docx — render target (internal, framework default)

Realizes the `docx` output-type (design §17 RI12): in-system `pandoc -f json -t docx`
over the persisted layer-3 AST (§14.2 — internal per the gate-3 default set). The Office
writer drops unknown attributes — desirable: provenance is consumed at the IR/AST layers
only (RI8). Styling rides a reference doc: this target's `reference_doc` field or the
selected Presentation's per-writer map (PD2); none ships at the floor. Declares the
pandoc pin bundle of record (RI13).
