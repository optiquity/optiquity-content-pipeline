---
id: x-fixture-format
provenance: framework
schema_version: 1
---

Obviously-synthetic negative guard fixture (tests/fixtures/guard): an `x-*` file in a
registry root — the reserved instance namespace the framework never ships
(LEAK[x-file], design §11.4 SV5). The `provenance: framework` line is deliberate, so this
tree fires ONLY the x-file class. Never real content.
