---
id: corporate-website
provenance: framework
schema_version: 1
destination: Company-owned website pages — blog, documentation, and newsroom sections under the organization's own domain.
advisory_norms:
  preferred_word_count: 1000
hard_limits: {}
format_advisories:
  how-to-documentation:
    preferred_word_count: 1200
  long-form-essay:
    preferred_word_count: 2000
reconcile_strategy_defaults:
  how-to-documentation: pass
  long-form-essay: pass
  short-opinion-post: adapt
default_output_type: html
---

# corporate-website — Platform entry (framework default)

Routing + constraint profile for publishing to an organization's own website (design
§5.3): selected per deliverable, never an instance-wide baseline (CA8, §12.3). The one
destination the publisher controls end-to-end — the constraint layer is therefore
thin and advisory by nature.

Constraint classes (CA9, §12.7):

- **Advisory** — a general web page reads best around 1000 words before it wants to
  become two pages; `how-to-documentation` earns more room (~1200 — completeness beats
  brevity in a procedure) and a `long-form-essay` on the blog runs to ~2000.
  Conservative, generic web-attention values — instances tune to their CMS and house
  style; recipe/run may deviate with a one-time warning.
- **Hard** — none declared: a self-hosted site imposes no platform-side physical cap
  (any real limit belongs to the instance's own CMS, an instance fact, not a framework
  one). `hard_limits` deliberately rides empty; instances add theirs via an `x-`
  extension (§11.4).

Reconcile-strategy defaults (§12.3): the owned site renders full documents natively,
so `how-to-documentation` and `long-form-essay` default to `pass`; a
`short-opinion-post` `adapt`s into the house blog shape. Recipe/run override at L5/L6.

Weak default output-type: `html` — websites serve HTML; any explicit output-type at
L3/L5/L6 beats this (§12.3).
