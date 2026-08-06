---
id: news-metadata
provenance: framework
schema_version: 1
authoritative: 2
opinionated: 1
review_status: unreviewed
reuse_rights: attribution
---

# news-metadata — content-kind entry (framework default)

The default score bundle for NEWS-AGGREGATOR METADATA (design §6.1 SM5; the sources-P2b-feeds
`gdelt` feed's characterization): the metadata a global news aggregator (GDELT DOC 2.0) computes
ABOUT articles it indexed — the article URL, domain, source country, language, seen-date, and
GDELT's own tone/theme/entity tags. It is the aggregator's record of WHAT IT INDEXED, not a primary
account of the underlying events.

- **authoritative: 2** — aggregator metadata is a SECONDARY signal: a corroboration/lead about
  coverage and framing, not the definitive record of the events themselves (§6.2). The `gdelt` feed
  stamps every record INFERRED accordingly — a lead to verify, never a published primary.
- **opinionated: 1** — record, not stance (§6.2): the metadata (domain, seen-date, computed tone
  score) is machine-tabulated fact-of-index, not editorial argument.
- **review_status: unreviewed** — aggregator metadata carries no formal review gate; per-fact
  refinement rides this default (the §6.2 G6 disposition).
- **freshness** — no kind-level policy (the floor): staleness is per-fact and derived. Timeliness
  rides the SLICE-level `snapshot` temporality (§6.1) the cache reader surfaces — a DOC pull is a
  point-in-time capture, true AS OF the seen date — not a §6.2 score.
- **reuse_rights: attribution** — GDELT's metadata is redistributable WITH ATTRIBUTION (§6.1), so
  this clears the RIGHTS half of the publish gate (`republishable`). But the TRUTH half is
  independent: the feed stamps facts INFERRED, so the confidence tier keeps them LEADS /
  corroboration regardless — a fact publishes only when BOTH gates pass, and the INFERRED tier
  never clears the first. (The feed additionally enforces the license in code: a `claim` carries
  only GDELT's metadata assertion, NEVER scraped article prose.)

Instances tag in via `content_kind: news-metadata` on a source entry; deviations are `extends:`
field-merge partials (Mechanism 1, §12.1), never edits here (§10 rule 2).
