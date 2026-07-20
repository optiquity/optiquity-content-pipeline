---
id: journal-structured-look
provenance: framework
schema_version: 1
variables:
  mainfont: Source Serif Pro
  fontsize: 10pt
  linestretch: 1.4
highlight_style: kate
csl: presentations/assets/csl/author-date.csl
---

# journal-structured-look — Presentation entry (framework default)

A VISUAL-only look (design §5.3 PD2/PD3): an airy, section-forward reading style suited to the
`journal-structured` venue profile, whose articles are long and method-heavy. Presentation carries
LOOK only — it never owns `writer` or `side` (PD8/§17), and no lever can disable the serialize-owned
provenance/section-attr strips (PD3).

Levers set (all ride inside `variables` per PD2, plus the one dedicated highlight lever):

- **`mainfont: Source Serif Pro`, `fontsize: 10pt`, `linestretch: 1.4`** — a slightly smaller
  serif body with GENEROUS line spacing: long, structured articles read more easily with more air
  between lines, which is why this look leans open where the strict look leans compact. Fonts ride
  inside `variables` (PD2); each scalar lowers to a `--variable=key=value` flag and is snapshotted
  into the serialize-inputs preimage (§17 FR7.1).
- **`highlight_style: kate`** — a higher-contrast highlighting palette, legible in the dense
  method/results listings this venue's articles tend to carry.
- **`csl: presentations/assets/csl/author-date.csl`** — the per-venue citation STYLE (DR-5
  C7/C11): this structured, method-heavy venue cites in the scholarly AUTHOR-DATE convention (the
  source label parenthetically in-text, `(source)`, with an un-numbered bibliography). `csl` is a
  citation STYLE override, NOT a citeproc toggle: `--citeproc` is CONTENT-driven (it fires whenever
  the AST cites, §17 R-4 family / C6), so a non-citing render through this look emits no `--csl` and
  is byte-identical to the `plain` floor (C7 S4); a citing render resolves every `[@key]` under this
  author-date style. The `.csl` is a hashed Presentation asset whose content hash rides the
  serialize preimage only when citeproc ran (§17 FR7.1); production path-resolution of the declared
  path is the deferred §17/step-29 loader.

Do not edit this entry to restyle output (extend-don't-edit, §10 rule 5): author a new
presentation entry (or an instance `x-*` entry) and select it.
