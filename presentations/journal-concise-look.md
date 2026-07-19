---
id: journal-concise-look
provenance: framework
schema_version: 1
variables:
  mainfont: Helvetica
  fontsize: 9.5pt
  linestretch: 1.1
highlight_style: tango
---

# journal-concise-look — Presentation entry (framework default)

A VISUAL-only look (design §5.3 PD2/PD3): a compact, scannable reading style suited to the
`journal-concise` venue profile, whose articles are short by policy. Presentation carries LOOK only
— it never owns `writer` or `side` (PD8/§17), and no lever can disable the serialize-owned
provenance/section-attr strips (PD3).

Levers set (all ride inside `variables` per PD2, plus the one dedicated highlight lever):

- **`mainfont: Helvetica`, `fontsize: 9.5pt`, `linestretch: 1.1`** — a sans-serif body at a small
  size with tight line spacing: a dense, screen-first look that matches the venue's short,
  quick-to-scan articles. Fonts ride inside `variables` (PD2); each scalar lowers to a
  `--variable=key=value` flag and is snapshotted into the serialize-inputs preimage (§17 FR7.1).
- **`highlight_style: tango`** — a light, low-contrast highlighting palette that stays quiet on a
  small, dense page.

Do not edit this entry to restyle output (extend-don't-edit, §10 rule 5): author a new
presentation entry (or an instance `x-*` entry) and select it.
