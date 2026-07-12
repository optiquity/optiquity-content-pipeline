---
id: general
provenance: framework
schema_version: 1
---

# general — content-kind entry (framework default)

The NEUTRAL kind: the default score bundle for a source not yet characterized more
specifically. This entry deliberately sets nothing — every score rides the schema
floor (design §11.1/§12.2 L0): `authoritative: 3`, `opinionated: 3`,
`review_status: unknown`, no freshness policy — the honest middle, claiming neither
authority nor stance.

It exists so the source schema's `content_kind` floor always resolves
(`sources/_schema.yaml` defaults to `general`): an instance that has not chosen a kind
is still valid config with honest scores, and choosing a real kind (`merged-code`,
`research-notes`, or a new one-file-add kind, §5.4) is the user's explicit
characterization act (§3.1).
