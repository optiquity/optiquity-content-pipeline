---
id: journal-concise
provenance: framework
schema_version: 1
destination: A concise-format research journal that publishes short, scannable articles on its own pages, with a hard abstract-length ceiling well below the genre's default so every summary stays brief.
hard_limits:
  max_chars: 20000
format_structural:
  academic-paper:
    - rule: length
      axis: role
      value: abstract
      min_len: 0
      max_len: 800
      severity: error
default_output_type: html
---

# journal-concise — Platform entry (framework default)

An illustrative venue-PROFILE (design §5.3/§12.7/§16): a generic, coherent example of a
journal that TIGHTENS the base `academic-paper` genre with a per-section NUMERIC bound. It names
no real publication — venue profiles stay generic (no impersonation).

What this venue tightens (the DR-4 `format_structural` HARD class, keyed to `academic-paper`):

- **Caps the Abstract length at 800 characters.** A `length` rule on `role: abstract` with
  `min_len: 0`, `max_len: 800`, and `severity: error`. The base genre only ADVISES an abstract
  ceiling (2500 characters at `warning` severity); this concise venue makes a much tighter bound
  HARD. A manuscript whose abstract runs past 800 characters BLOCKS at the reconcile structural
  gate (§16, DR-4 C8) with `section-conformance-violation`; a short abstract fits. This is the
  #4a per-section case: a per-section numeric limit is section-addressed HERE (in
  `format_structural`, keyed to the named `abstract` section) and is enforced by the STRUCTURAL
  gate — NEVER by the whole-artifact `max_chars` gate, which governs the whole manuscript.

Whole-artifact limit (the CA9 hard class, whole-artifact scope, enforced at the §16 terminal
gate): `max_chars: 20000` — the tightest total-length ceiling of the three example venues (this
house publishes short articles). Note the S-3 disjointness invariant: the per-section limit above
is a `length` rule NAMED on the `abstract` section, and the whole-artifact key is `max_chars` —
the two names are disjoint (a `format_structural` section-limit name is NEVER also a `hard_limits`
key), so the section/artifact partition holds.

Weak default output-type: `html` — a public writer, so the serialize-time provenance and
section-attr strips (§17 R-4 / DR-4 C9) run and the published bytes are valid; any explicit
output-type at L3/L5/L6 beats this (§12.3). Citation style (`csl`) is deliberately NOT declared
here — a DR-5 concern, out of this venue profile's scope.
