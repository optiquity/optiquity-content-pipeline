---
id: journal-structured
provenance: framework
schema_version: 1
destination: A structured-manuscript research journal that publishes accepted articles on its own pages and requires every manuscript to carry an explicit Discussion section separating interpretation from the neutrally-reported results.
hard_limits:
  max_chars: 60000
format_structural:
  academic-paper:
    - rule: presence
      axis: role
      value: discussion
      required: true
      severity: error
default_output_type: html
---

# journal-structured — Platform entry (framework default)

An illustrative venue-PROFILE (design §5.3/§12.7/§16): a generic, coherent example of a
journal that TIGHTENS the base `academic-paper` genre by REQUIRING a section the genre leaves
optional. It names no real publication — venue profiles stay generic (no impersonation).

What this venue tightens (the DR-4 `format_structural` HARD class, keyed to `academic-paper`):

- **REQUIRES an explicit Discussion section.** A `presence` rule on `role: discussion` with
  `required: true` and `severity: error`. The base genre requires only `abstract`, `methods`, and
  `results` (§5.2); `discussion` is optional there. This venue makes it MANDATORY: its house
  structure insists that every article separate what was OBSERVED (Results, reported neutrally)
  from what it MEANS and the limits of the evidence (Discussion). A manuscript MISSING a
  `## Discussion {#discussion}` section BLOCKS at the reconcile structural gate (§16, DR-4 C8)
  with `section-conformance-violation`; a manuscript that carries one fits. The tightening is a
  genuine addition, not a restatement of a base requirement — `abstract`/`methods`/`results` are
  already base-required, so requiring one of them would be inert; `discussion` is the role this
  venue actually adds.

Whole-artifact limit (the CA9 hard class, whole-artifact scope, enforced at the §16 terminal
gate): `max_chars: 60000` — this house runs long-form, method-heavy articles, so its total-length
ceiling is the most generous of the three example venues. Disjoint by scope from the per-section
structural rule above (S-3 partition: this venue declares no per-section numeric limit, so a
`format_structural` name can never collide with the `hard_limits` key).

Weak default output-type: `html` — a public writer, so the serialize-time provenance and
section-attr strips (§17 R-4 / DR-4 C9) run and the published bytes are valid; any explicit
output-type at L3/L5/L6 beats this (§12.3). Citation style (`csl`) is deliberately NOT declared
here — a DR-5 concern, out of this venue profile's scope.
