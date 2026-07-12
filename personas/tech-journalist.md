---
id: tech-journalist
provenance: framework
schema_version: 1
role: >-
  A technology journalist or industry reporter assessing the piece as source
  material for coverage — reads as a professional skeptic hunting for the story,
  not a spectator browsing.
knowledge_level: >-
  Broadly literate across the technology landscape, its history, and its hype
  cycles; not a hands-on practitioner of this system — explain mechanisms in plain
  terms and never assume they will run the code.
motivation: >-
  Find the defensible story fast: what is genuinely new here, who it affects, and
  which claims would survive an editor's fact-check and a rival expert's scrutiny.
objections:
  - Press-release superlatives where independently checkable facts should be.
  - Claims with no named, attributable source or linkable primary artifact.
  - Novelty that evaporates under one comparison to prior art.
credibility_signals:
  - Specific, checkable facts — dates, versions, numbers — verifiable without the author's help.
  - On-the-record attribution and primary artifacts they can link.
  - Candor about limitations and about who credibly disagrees.
default_voice: clear-explainer
---

# tech-journalist — Persona entry (framework default)

A generic, client-agnostic reader shape for content aimed at the press (design §5.2 —
audience facts only): the journalist is the AUDIENCE here — the reader deciding whether
this becomes coverage. Every attribute is a fact about that audience; nothing here is
register/affect (that is Voice, via `default_voice` — Q6/CA2, §12.3) and nothing is
reading context (that is Platform, §5.2).

A coherent bundle (§5.2): field-literate-but-not-hands-on assumptions, attribution-first
objections, and check-it-yourself credibility signals co-vary. `default_voice:
clear-explainer` — a fact-forward audience trusts explanation over advocacy. Customize
by `extends:` partial or a new `x-` entry (§10 rule 2, §11.4), never by editing this
file.
