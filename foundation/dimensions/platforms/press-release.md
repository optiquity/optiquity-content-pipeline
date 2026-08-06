---
id: press-release
provenance: framework
schema_version: 1
destination: Press distribution — releases sent to newsrooms, journalists, and wire services for pickup.
advisory_norms:
  preferred_word_count: 500
  headline_char_count_max: 80
hard_limits: {}
format_advisories:
  short-opinion-post:
    preferred_word_count: 450
  long-form-essay:
    preferred_word_count: 600
reconcile_strategy_defaults:
  short-opinion-post: adapt
  long-form-essay: adapt
default_output_type: plain-text
---

# press-release — Platform entry (framework default)

Routing + constraint profile for press distribution (design §5.3): selected per
deliverable, never an instance-wide baseline (CA8, §12.3). The destination is the
press-distribution CHANNEL (newsroom inboxes, wire services); what genre travels down
it is the Format's business (Q4) — this entry only projects the channel's norms onto
whatever is routed here.

Constraint classes (CA9, §12.7):

- **Advisory** — industry convention holds a release to roughly one page: about 500
  words platform-wide, headline within ~80 characters (short enough for email subject
  lines and wire headers). Conservative, generic values from long-standing practice —
  instances tune; recipe/run may deviate with a one-time warning. Content routed here
  compresses hard: even a `long-form-essay` projects down to ~600 words, a
  `short-opinion-post` to ~450.
- **Hard** — none declared: physical caps (headline and body limits) vary per wire
  vendor and are a vendor contract fact, not a universal one — encoding one vendor's
  cap would wrongly block or wrongly pass others at the reconcile gate (§16).
  `hard_limits` deliberately rides empty; instances pin their vendor's caps via an
  `x-` extension (§11.4).

Reconcile-strategy defaults (§12.3): everything routed to the press channel `adapt`s —
inverted-pyramid lead, attribution-ready facts, quotable lines; nothing passes through
unreshaped. Recipe/run override at L5/L6.

Weak default output-type: `plain-text` — newsroom email and wire submission
conventionally consume unformatted text; any explicit output-type at L3/L5/L6 beats
this (§12.3).
