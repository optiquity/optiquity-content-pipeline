---
id: web-article
provenance: framework
schema_version: 1
authoritative: 2
opinionated: 3
review_status: unreviewed
reuse_rights: lead-only
---

# web-article — content-kind entry (framework default)

The default score bundle for GENERIC WEB / RSS CONTENT (design §6.1 SM5; the sources-P2b-feeds
`rss` feed's characterization): an arbitrary blog post, news item, or Atom/RSS entry from an
UNCHARACTERIZED web source. Unlike a regulatory filing, nothing about a generic web page earns the
EXTRACTED tier — it is a LEAD to verify, never a published fact.

- **authoritative: 2** — uncharacterized web content: a credible-at-best, often casual account of
  its subject, not a definitive record (§6.2). Treat as a lead to corroborate (§6.5), never as
  settled fact. The `rss` feed stamps every entry INFERRED accordingly — EXTRACTED is reserved for
  a characterized primary + authoritative first-party source (EDGAR-class), never web content.
- **opinionated: 3** — the mixed middle (§6.2): a web article blends record and stance, and either
  can dominate. Independently useful from `authoritative`, not its inverse.
- **review_status: unreviewed** — generic web content ships without any formal review/acceptance
  gate; the feed exposes no per-entry review metadata, so per-fact refinement rides this default
  (the §6.2 G6 disposition).
- **freshness** — no kind-level policy (the floor): staleness is per-fact and derived. Timeliness
  is already carried at the SLICE level by the `live` temporality (§6.1) the cache reader surfaces
  — a web feed is a rolling window, superseded by the next pull — not a §6.2 score.
- **reuse_rights: lead-only** — the decisive gate: web content is a LEAD ONLY (§6.1). It may inform
  generation but is NEVER republished as content — even were a fact somehow EXTRACTED, `lead-only`
  sits BELOW the `attribution` publish threshold, so `republishable` stays false. Combined with the
  feed's INFERRED tier, a web-feed fact is DOUBLY a lead: neither true-enough (tier) nor
  allowed (rights) to publish. This is exactly the tier-honesty rule for uncharacterized content.

Instances tag in via `content_kind: web-article` on a source entry; deviations are `extends:`
field-merge partials (Mechanism 1, §12.1), never edits here (§10 rule 2).
