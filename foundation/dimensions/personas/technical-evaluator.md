---
id: technical-evaluator
provenance: framework
schema_version: 1
role: >-
  A hands-on engineer or architect evaluating a tool, codebase, or approach for
  adoption — reads as a practitioner deciding, not a spectator browsing.
knowledge_level: >-
  Expert in the surrounding discipline (assumes fluency in general software concepts
  and tooling); new to this specific system — explain the system, never the field.
motivation: >-
  Decide quickly and defensibly whether this is worth their time: what it does, what
  it costs to adopt, where it breaks.
objections:
  - Marketing language where evidence should be.
  - Unclear effort-to-value — no honest path from zero to a first result.
  - Hidden operational costs, lock-in, or hand-waved failure modes.
credibility_signals:
  - Working examples and exact commands that match the source.
  - Precise technical claims with resolvable citations.
  - Limitations stated as plainly as strengths.
default_voice: clear-explainer
---

# technical-evaluator — Persona entry (framework default)

The framework's default audience: a generic, client-agnostic reader shape for
technical content (design §5.2 — audience facts only). Every attribute is a fact about
the AUDIENCE; nothing here is register/affect (that is Voice, via `default_voice` —
Q6/CA2, §12.3) and nothing is reading context (that is Platform, §5.2).

A coherent bundle (§5.2): expert-level assumptions, evidence-first objections, and
proof-shaped credibility signals co-vary — customize by `extends:` partial or a new
`x-` entry (§10 rule 2, §11.4), never by editing this file.
