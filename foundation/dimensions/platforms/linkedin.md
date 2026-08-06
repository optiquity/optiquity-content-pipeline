---
id: linkedin
provenance: framework
schema_version: 1
destination: LinkedIn feed posts and long-form articles.
advisory_norms:
  preferred_char_count: 1300
  hashtag_count_max: 5
hard_limits:
  post_char_limit: 3000
format_advisories:
  short-opinion-post:
    preferred_char_count: 1200
  long-form-essay:
    preferred_char_count: 2600
reconcile_strategy_defaults:
  short-opinion-post: adapt
  long-form-essay: split
default_output_type: md
---

# linkedin — Platform entry (framework default)

Routing + constraint profile for publishing to LinkedIn (design §5.3): selected per
deliverable, never an instance-wide baseline (CA8, §12.3).

Constraint classes (CA9, §12.7):

- **Advisory** — a feed post reads best around 1300 characters with at most a handful of
  hashtags; the per-format projections tighten that for a `short-opinion-post` and stretch
  it for a `long-form-essay`. Advisory values ride the cascade; a recipe/run may deviate
  with a one-time warning.
- **Hard** — a feed post physically caps at 3000 characters. Enforced only at the
  reconcile gate (§16); never bound in M2.

Reconcile-strategy defaults (§12.3): a `short-opinion-post` `adapt`s into the post shape;
a `long-form-essay` defaults to `split` (a post series) rather than truncation. Recipe/run
override at L5/L6.

Weak default output-type: `md` — LinkedIn post text is authored as markdown and pasted;
any explicit output-type at L3/L5/L6 beats this (§12.3).
