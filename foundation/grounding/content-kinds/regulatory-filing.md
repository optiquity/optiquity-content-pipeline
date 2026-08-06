---
id: regulatory-filing
provenance: framework
schema_version: 1
authoritative: 5
opinionated: 1
review_status: formally-vetted
reuse_rights: attribution
---

# regulatory-filing — content-kind entry (framework default)

The default score bundle for A PRIMARY REGULATORY FILING (design §6.1 SM5; the sources-P2
EDGAR feed's characterization): the authoritative first-party record a filer submits to a
regulator — a SEC EDGAR filing, a court docket entry, a licence register. The source of
record for what an entity FORMALLY stated to an authority.

- **authoritative: 5** — a filing IS the definitive record for its own subject: the
  filer's own words, submitted under legal obligation to the authority of record (§6.2).
  This is exactly the "definitive record / system of record" end of the scale — and it is
  what earns the EXTRACTED tier honestly (a characterized primary + authoritative
  first-party source), never granted to uncharacterized web content.
- **opinionated: 1** — record, not stance (§6.2: not the inverse of authoritative). A
  filing states facts of record; editorial framing (an analyst's read of a filing) is a
  DIFFERENT source with a different kind.
- **review_status: formally-vetted** — a filing has passed a formal submission/acceptance
  gate at the authority (the filer attests; the regulator accepts). Degrades per-fact to
  `unknown` only where an adapter exposes no per-item acceptance metadata (the §6.2 G6
  disposition); the feed stamps acceptance, so this default holds.
- **freshness** — no kind-level policy (the floor): a filing is ARCHIVAL (§6.1
  temporality) — an immutable, dated record that does not expire by calendar. Its
  `as_of` is the filing/acceptance date; staleness is per-fact and derived, never a
  kind-level expiry window (§6.2). (Temporality itself is grounding-ledger provenance the
  cache reader surfaces, NOT a §6.2 score — it never enters the selection grammar.)
- **reuse_rights: attribution** — EDGAR filings are U.S.-government public-domain records,
  but the FILER is attributed: the content is REPUBLISHABLE with attribution (§6.1). This
  is what clears the `attribution` publish threshold, so an EXTRACTED regulatory-filing
  fact both `publishable` (tier) AND `republishable` (rights) — it PUBLISHES as fact, not
  a mere lead. (Uncharacterized web content, by contrast, stays a lead: it is neither
  EXTRACTED nor cleared to republish.)

Instances tag in via `content_kind: regulatory-filing` on a source entry; deviations are
`extends:` field-merge partials (Mechanism 1, §12.1), never edits here (§10 rule 2).
