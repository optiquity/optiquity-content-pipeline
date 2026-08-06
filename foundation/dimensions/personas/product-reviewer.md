---
id: product-reviewer
provenance: framework
schema_version: 1
role: >-
  A hands-on product reviewer deciding whether — and how favorably — to feature
  this in a published review; reads comparatively, with the rest of the market
  open in the next tab.
knowledge_level: >-
  Fluent in the product category, its competitive landscape, and its evaluation
  conventions; new to this specific product — explain what it does and where it
  sits, never the category basics.
motivation: >-
  Reach a fair, evidence-backed verdict quickly: what it claims, how those claims
  hold up in real use, and who should — and should not — choose it.
objections:
  - Spec-sheet recitation with no evidence from actual use.
  - Cherry-picked comparisons that dodge the obvious competitor.
  - Strengths listed without a single honest weakness or trade-off.
credibility_signals:
  - Concrete usage results they could reproduce on their own bench.
  - Like-for-like comparisons that name real alternatives.
  - Trade-offs and dealbreakers stated as plainly as the wins.
default_voice: clear-explainer
---

# product-reviewer — Persona entry (framework default)

A generic, client-agnostic reader shape for review-seeking content (design §5.2 —
audience facts only): the reviewer is the AUDIENCE — a professional evaluator whose
output is a published verdict. Every attribute is a fact about that audience; nothing
here is register/affect (that is Voice, via `default_voice` — Q6/CA2, §12.3) and
nothing is reading context (that is Platform, §5.2).

A coherent bundle (§5.2): category fluency, comparison-shaped objections, and
reproducibility-first credibility signals co-vary. `default_voice: clear-explainer` —
an audience professionally allergic to advocacy is best served by plain explanation.
Customize by `extends:` partial or a new `x-` entry (§10 rule 2, §11.4), never by
editing this file.
