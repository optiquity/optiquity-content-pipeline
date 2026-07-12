---
id: substack-post
provenance: framework
schema_version: 1
destination: Substack newsletter posts — delivered by email and mirrored on the publication's web archive.
advisory_norms:
  preferred_word_count: 1200
hard_limits: {}
format_advisories:
  long-form-essay:
    preferred_word_count: 2000
  short-opinion-post:
    preferred_word_count: 800
reconcile_strategy_defaults:
  long-form-essay: pass
  short-opinion-post: adapt
default_output_type: md
---

# substack-post — Platform entry (framework default)

Routing + constraint profile for publishing to a Substack newsletter (design §5.3):
selected per deliverable, never an instance-wide baseline (CA8, §12.3).

Constraint classes (CA9, §12.7):

- **Advisory** — the email-first reading context favors restraint: around 1200 words
  platform-wide (conservative — very long emails risk client-side clipping, e.g.
  Gmail's rendered-size cutoff, before the web archive ever matters); a
  `long-form-essay` may stretch to ~2000, a `short-opinion-post` sits near 800.
  Generic values — instances tune; recipe/run may deviate with a one-time warning.
- **Hard** — none declared: Substack documents no post-length cap, and the real
  ceiling (email-client clipping) is a rendered-size effect of the client, not a
  character cap of the platform — encoding a guessed number would block feasible
  content at the reconcile gate (§16) without ground. `hard_limits` deliberately rides
  empty; instances add one via an `x-` extension if their audience's clients demand it
  (§11.4).

Reconcile-strategy defaults (§12.3): Substack is a long-form newsletter home, so a
`long-form-essay` defaults to `pass`; a `short-opinion-post` `adapt`s into the
newsletter shape (a dispatch with a greeting-to-signoff arc). Recipe/run override at
L5/L6.

Weak default output-type: `md` — Substack posts are drafted as markdown and pasted
into its editor; any explicit output-type at L3/L5/L6 beats this (§12.3).
