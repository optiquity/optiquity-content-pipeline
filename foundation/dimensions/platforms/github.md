---
id: github
provenance: framework
schema_version: 1
destination: GitHub repository surfaces — READMEs, docs pages, releases, discussions.
advisory_norms:
  preferred_line_length: 120
hard_limits:
  markdown_body_char_limit: 65536
format_advisories:
  readme:
    preferred_word_count: 600
reconcile_strategy_defaults:
  readme: pass
  long-form-essay: pass
default_output_type: md
---

# github — Platform entry (framework default)

Routing + constraint profile for publishing to GitHub repository surfaces (design §5.3):
selected per deliverable, never an instance-wide baseline (CA8, §12.3).

Constraint classes (CA9, §12.7):

- **Advisory** — source-viewable markdown reads best soft-wrapped around 120 columns; a
  `readme` lands best near 600 words before it wants a docs page. Advisory values ride the
  cascade; a recipe/run may deviate with a one-time warning.
- **Hard** — an issue/discussion/comment markdown body caps at 65536 characters. Enforced
  only at the reconcile gate (§16); never bound in M2.

Reconcile-strategy defaults (§12.3): GitHub renders markdown natively, so `readme` and
`long-form-essay` default to `pass` — no reshape needed; the content's own structure is
the published structure. Recipe/run override at L5/L6.

Weak default output-type: `md` — GitHub's surfaces consume markdown directly; any explicit
output-type at L3/L5/L6 beats this (§12.3).
