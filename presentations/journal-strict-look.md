---
id: journal-strict-look
provenance: framework
schema_version: 1
variables:
  mainfont: Georgia
  fontsize: 11pt
  linestretch: 1.15
highlight_style: pygments
---

# journal-strict-look — Presentation entry (framework default)

A VISUAL-only look (design §5.3 PD2/PD3): a sober, print-like reading style suited to the
`journal-strict` venue profile. Presentation carries LOOK only — it never owns `writer` or `side`
(those are render-target fields, PD8/§17), and no Presentation lever can disable the serialize-owned
provenance/section-attr strips (PD3).

Levers set (all ride inside `variables` per PD2, plus the one dedicated highlight lever):

- **`mainfont: Georgia`, `fontsize: 11pt`, `linestretch: 1.15`** — a classic serif body at a
  comfortable reading size with modest line spacing: the conservative, print-journal feel this
  strict venue prefers. Fonts and margins ride inside `variables` (PD2); each scalar lowers to a
  `--variable=key=value` flag and is snapshotted into the serialize-inputs preimage (§17 FR7.1).
- **`highlight_style: pygments`** — Pandoc's default syntax-highlighting palette, a neutral
  choice for the occasional code or data listing.

Do not edit this entry to restyle output (extend-don't-edit, §10 rule 5): author a new
presentation entry (or an instance `x-*` entry) and select it.
