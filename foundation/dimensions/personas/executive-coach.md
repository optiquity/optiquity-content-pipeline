---
id: executive-coach
provenance: framework
schema_version: 1
role: >-
  An executive coach or leadership advisor reading on behalf of the senior leaders
  they counsel — a trusted intermediary who will relay, reframe, or discard this
  for the boardroom.
knowledge_level: >-
  Deep in leadership practice, organizational dynamics, and decision-making under
  uncertainty; a non-specialist in this technical domain — translate technology
  into consequences for people, organizations, and judgment.
motivation: >-
  Find durable, defensible insight to carry into coaching conversations: what this
  changes about how leaders should decide, delegate, and communicate.
objections:
  - Jargon that cannot be restated to a chief executive in one sentence.
  - Tactical detail with no leadership consequence attached.
  - Sweeping claims about people and organizations with no grounding.
credibility_signals:
  - Implications drawn visibly and carefully from stated facts.
  - Respect for organizational complexity — no one-size-fits-all prescriptions.
  - Concrete scenarios a leader would recognize from their own week.
default_voice: confident-advocate
---

# executive-coach — Persona entry (framework default)

A generic, client-agnostic reader shape for leadership-facing content (design §5.2 —
audience facts only): the executive coach is the AUDIENCE — an advisor who reads so
that leaders don't have to, and whose trust must be earned twice (theirs, then their
clients'). Every attribute is a fact about that audience; nothing here is
register/affect (that is Voice, via `default_voice` — Q6/CA2, §12.3) and nothing is
reading context (that is Platform, §5.2).

A coherent bundle (§5.2): domain-outsider assumptions, translation-shaped objections,
and reasoning-visible credibility signals co-vary. `default_voice:
confident-advocate` — an audience that retells ideas needs them argument-shaped:
strongest grounded claim first, counterargument answered honestly (§5.2). Customize
by `extends:` partial or a new `x-` entry (§10 rule 2, §11.4), never by editing this
file.
