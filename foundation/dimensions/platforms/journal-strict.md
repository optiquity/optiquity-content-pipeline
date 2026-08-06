---
id: journal-strict
provenance: framework
schema_version: 1
destination: A strict peer-reviewed research journal that publishes the accepted manuscript on its own article pages. Contributor thanks and funding notes are carried in separate front/back matter the production system supplies, never as an in-body section of the manuscript.
hard_limits:
  max_chars: 40000
format_structural:
  academic-paper:
    - rule: presence
      axis: role
      value: acknowledgements
      required: false
      severity: error
default_output_type: html
---

# journal-strict — Platform entry (framework default)

An illustrative venue-PROFILE (design §5.3/§12.7/§16): a generic, coherent example of a
journal that TIGHTENS the base `academic-paper` genre for its house style. It names no real
publication — venue profiles are framework mechanism, kept generic (no impersonation).

What this venue tightens (the DR-4 `format_structural` HARD class, keyed to `academic-paper`):

- **FORBIDS an in-body Acknowledgements section.** A `presence` rule on `role: acknowledgements`
  with `required: false` and `severity: error`. The base genre marks acknowledgements OPTIONAL
  (§5.2 — "whether a venue forbids or requires it is the Platform's tightening"); this venue
  moves it to FORBIDDEN. A manuscript carrying `## Acknowledgements {#acknowledgements}` BLOCKS
  at the reconcile structural gate (§16, DR-4 C8) with `section-conformance-violation`; the same
  manuscript WITHOUT that section fits. The reason is real editorial policy: this house collects
  thanks and funding disclosures in production-managed metadata (front/back matter) rather than
  the peer-reviewed body, so an in-body acknowledgements block is rejected before typesetting.

Whole-artifact limit (the CA9 hard class, whole-artifact scope, enforced at the §16 terminal
gate): `max_chars: 40000` — a firm ceiling on total manuscript length, disjoint by scope from the
per-section structural rules above (the S-3 partition: a `format_structural` section-limit name is
never also a `hard_limits` key; this venue declares no per-section numeric limit, so the partition
holds trivially).

Weak default output-type: `html` — a public writer, so the serialize-time provenance and
section-attr strips (§17 R-4 / DR-4 C9) run and the published bytes are valid; any explicit
output-type at L3/L5/L6 beats this (§12.3). Citation style (`csl`) is deliberately NOT declared
here — that is a DR-5 concern, out of this venue profile's scope.
