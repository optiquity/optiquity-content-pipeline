---
id: medium-post
provenance: framework
schema_version: 1
destination: Medium stories, on medium.com or a Medium publication.
advisory_norms:
  preferred_word_count: 1500
hard_limits: {}
format_advisories:
  medium-review-post:
    preferred_word_count: 1200
  long-form-essay:
    preferred_word_count: 2500
reconcile_strategy_defaults:
  medium-review-post: adapt
  long-form-essay: pass
  short-opinion-post: adapt
default_output_type: md
---

# medium-post — Platform entry (framework default)

Routing + constraint profile for publishing to Medium (design §5.3): selected per
deliverable, never an instance-wide baseline (CA8, §12.3).

Constraint classes (CA9, §12.7):

- **Advisory** — Medium's read-time culture favors mid-length pieces: around 1500 words
  as the platform-wide norm; a `medium-review-post` lands tighter (~1200) and a
  `long-form-essay` may stretch (~2500). Conservative, generic values (the widely cited
  "~7-minute read" sweet spot, rounded down) — instances tune; recipe/run may deviate
  with a one-time warning.
- **Hard** — none declared: Medium documents no practical post-length cap, and an
  invented cap would block feasible content at the reconcile gate (§16) without ground.
  `hard_limits` deliberately rides empty; instances that hit a real ceiling add one via
  an `x-` extension (§11.4).

Reconcile-strategy defaults (§12.3): Medium is a native long-form home, so a
`long-form-essay` defaults to `pass`; a `medium-review-post` and a `short-opinion-post`
`adapt` into the story shape (hook-first, subheaded). Recipe/run override at L5/L6.

Weak default output-type: `md` — Medium stories are drafted as markdown and imported or
pasted; any explicit output-type at L3/L5/L6 beats this (§12.3).
