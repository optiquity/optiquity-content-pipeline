---
id: product-manager
provenance: framework
schema_version: 1
role: >-
  A product manager weighing this against a live roadmap — accountable for the
  outcome of adopting or ignoring it; reads as a decision-maker triaging, not an
  implementer.
knowledge_level: >-
  Fluent in product strategy, user problems, and trade-off language; technically
  conversant but not hands-on — explain what it enables and what it costs, not how
  to operate it.
motivation: >-
  Decide whether this moves their users and their metrics: the problem it solves,
  for whom, at what cost and risk, and what they would have to displace to get it.
objections:
  - Features described without the user problem they solve.
  - No honest account of cost, effort, or opportunity cost.
  - Benefits that no metric could ever confirm or refute.
credibility_signals:
  - Claims framed in user outcomes tied to observable behavior.
  - Effort and cost estimates with their assumptions shown.
  - Evidence of real-world usage, not just demonstrated capability.
default_voice: confident-advocate
---

# product-manager — Persona entry (framework default)

A generic, client-agnostic reader shape for adoption-decision content (design §5.2 —
audience facts only): the product manager is the AUDIENCE — a prioritizer deciding
whether this earns roadmap space. Every attribute is a fact about that audience;
nothing here is register/affect (that is Voice, via `default_voice` — Q6/CA2, §12.3)
and nothing is reading context (that is Platform, §5.2).

A coherent bundle (§5.2): outcome-framed assumptions, cost-shaped objections, and
metric-first credibility signals co-vary. `default_voice: confident-advocate` — a
decision-maker triaging a case is best served by an argument-shaped voice that leads
with the strongest grounded claim (§5.2; the voice's evidence discipline is a
framework invariant, §6.5). Customize by `extends:` partial or a new `x-` entry (§10
rule 2, §11.4), never by editing this file.
