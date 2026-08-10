"""The paid-transport machinery — quarantined from generation (plan G1–G9, §21.10).

This package holds the API-key/spend machinery that the transport-selection build lands
gate by gate. It mirrors `pipeline/sources/` in spirit: the money surface lives OFF the
generation hot path. Import rules (enforced by the module-boundary grep test at G9):

- `pipeline/compose.py`, `pipeline/review.py`, `pipeline/reconcile.py` import **NOTHING**
  from `pipeline.spend` (generation stays paid-path-free).
- `pipeline/transport.py` imports **NOTHING** from `pipeline.spend` — the chokepoint plan
  TYPE (`TransportPlan`) lives in `pipeline.transport` itself, so the lowest shared node
  pulls in no spend package and there is no import cycle.
- `pipeline/sources/**` (from G9) may import ONLY `pipeline.spend.keystore`.

G1 lands only `construction.py` (the `ConstructionBudget` ceiling math, the generation
analog of `pipeline.sources.control.ResearchBudget`). Every other module named in the plan
(`wall`, `keystore`, `assignment`, `entitlement`, `meter`, `resolve`) arrives at its own
gate; NO paid surface ships until those walls exist (the money-safety ordering guarantee).
"""

from __future__ import annotations
