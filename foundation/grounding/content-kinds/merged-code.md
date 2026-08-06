---
id: merged-code
provenance: framework
schema_version: 1
authoritative: 4
opinionated: 1
review_status: reviewed
---

# merged-code — content-kind entry (framework default)

The default score bundle for MERGED MAINLINE CODE (design §6.1 SM5; the plan's own
named example kind): the source of record for what a system actually does.

- **authoritative: 4** — code is definitive about its own behavior; short of 5 because
  code states WHAT, rarely WHY (intent still needs corroboration).
- **opinionated: 1** — record, not stance (§6.2: not the inverse of authoritative).
- **review_status: reviewed** — merged code has passed the merge gate by definition;
  per-fact refinement degrades to `unknown` where the adapter exposes no per-symbol
  review metadata (the G6 disposition, §6.2).
- **freshness** — no kind-level policy (the floor): code does not expire by calendar;
  staleness is per-fact, derived from commits (§6.2).

Instances tag in via `content_kind: merged-code` on a source entry; deviations are
`extends:` field-merge partials (Mechanism 1, §12.1), never edits here (§10 rule 2).
