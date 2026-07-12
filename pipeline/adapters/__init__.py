"""Source adapters — pluggable, READ-ONLY grounding providers (design §6.1; plan T11).

The contract lives in `pipeline.adapters.base` (plan step 17); the deterministic mock
adapter (`pipeline.adapters.mock`) implements it for full-branch resolver coverage. The
real v1 adapters — `graphify` + `folder` — land at plan step 18 against the same contract.

Durable rule 1 rides every adapter: source/client repos are READ-ONLY, always. The
contract exposes no write primitive, structurally.
"""
