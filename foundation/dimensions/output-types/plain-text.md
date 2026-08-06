---
id: plain-text
provenance: framework
schema_version: 1
---

# plain-text — Output-type entry (framework default)

Plain-text output (design §5.3). Realized by the `plain-text` render target (§17 RI12;
writer `plain`), which ships `side: internal` (§14.2 — an easy type: the pinned Pandoc
binary carries the writer, no external tooling). The natural output-type for
destinations that consume unformatted text (e.g. the `press-release` platform's weak
default — newsroom email and wire submission); part of `deliverable-id` (§7.1).
