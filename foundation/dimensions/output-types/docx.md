---
id: docx
provenance: framework
schema_version: 1
---

# docx — Output-type entry (framework default)

Word document output (design §5.3). Realized by the `docx` render target (§17 RI12),
shipping `side: internal` (§14.2 — an easy type). The Office writer drops unknown
attributes, so provenance is consumed at the IR/AST layers only, never recovered from
output bytes (§17 RI8).
