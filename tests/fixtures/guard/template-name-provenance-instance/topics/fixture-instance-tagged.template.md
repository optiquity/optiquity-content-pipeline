---
id: fixture-instance-tagged
provenance: instance
schema_version: 1
---

Obviously-synthetic negative guard fixture (tests/fixtures/guard): a template-NAMED
registry file carrying an explicit `provenance: instance` line. The PA-1a basename
exemption skips only the missing-provenance default-deny; an explicit instance tag still
leaks (step-13 review RV-2 — shipped templates carry no provenance frontmatter at all) —
must be flagged as LEAK[provenance-instance]. Never real content.
