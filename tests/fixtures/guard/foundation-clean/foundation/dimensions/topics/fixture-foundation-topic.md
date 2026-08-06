---
id: fixture-foundation-topic
provenance: framework
schema_version: 1
---

# Fixture foundation topic

Obviously-synthetic guard fixture (tests/fixtures/guard/foundation-clean): a POPULATED
registry entry with `provenance: framework`, living under the `foundation/`-reorg layout
(foundation/dimensions/topics/). It exercises the B-2 foundation arm end to end — the
`foundation/dimensions/topics` registry IS in FOUNDATION_REGISTRY_DIRS, so the GAP-4a
coverage check passes it, and the content scan welcomes a framework-provenance entry. The
whole tree must be green (exit 0).
