---
id: journal-strict-look
provenance: framework
schema_version: 1
variables:
  mainfont: Georgia
  fontsize: 11pt
  linestretch: 1.15
highlight_style: pygments
csl: foundation/dimensions/presentations/assets/csl/numeric.csl
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
- **`csl: foundation/dimensions/presentations/assets/csl/numeric.csl`** — the per-venue citation STYLE (DR-5 C7/C11):
  this strict, print-journal venue numbers its references (`[1]`, `[2]`, …) with a numbered
  bibliography — the compact, rigid Vancouver/IEEE convention that suits it. `csl` is a citation
  STYLE override, NOT a citeproc toggle: `--citeproc` is CONTENT-driven (it fires whenever the AST
  cites, §17 R-4 family / C6), so a non-citing render through this look emits no `--csl` and is
  byte-identical to the `plain` floor (C7 S4); a citing render resolves every `[@key]` under this
  numbered style instead of pandoc's default author-date. The `.csl` is a hashed Presentation asset
  whose content hash rides the serialize preimage only when citeproc ran (§17 FR7.1); production
  path-resolution of the declared path is the deferred §17/step-29 loader.

Do not edit this entry to restyle output (extend-don't-edit, §10 rule 5): author a new
presentation entry (or an instance `x-*` entry) and select it.
