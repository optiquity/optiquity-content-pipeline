---
id: technical-documentation-writer
provenance: framework
schema_version: 1
role: >-
  A technical writer preparing to document this system for its end users — reads
  as an accuracy auditor who will restate every claim in their own words and be
  held to it.
knowledge_level: >-
  Expert in documentation craft and information architecture; comfortable reading
  code and running commands, but new to this system's concepts and vocabulary —
  define each term once, precisely, and use it consistently thereafter.
motivation: >-
  Extract a correct, complete mental model fast: the canonical names, exact
  behaviors, edge cases, and which statements are stable enough to republish
  downstream under their own byline.
objections:
  - Inconsistent terminology — the same thing under two names, or one name for two things.
  - Steps that silently "just work" over undocumented assumptions.
  - Behavior described as aspiration rather than as shipped.
credibility_signals:
  - Exact commands, flags, and outputs that match the shipped software.
  - One consistent term per concept, used throughout.
  - Explicit statements of which version or configuration each claim applies to.
default_voice: clear-explainer
---

# technical-documentation-writer — Persona entry (framework default)

A generic, client-agnostic reader shape for docs-enabling content (design §5.2 —
audience facts only): the documentation writer is the AUDIENCE — a reader who will
transform this material into user-facing documentation. Every attribute is a fact
about that audience; nothing here is register/affect (that is Voice, via
`default_voice` — Q6/CA2, §12.3) and nothing is reading context (that is Platform,
§5.2).

A coherent bundle (§5.2): craft-expert/system-novice assumptions, consistency-shaped
objections, and exactness-first credibility signals co-vary. `default_voice:
clear-explainer` — the one audience for whom precision IS the product. Customize by
`extends:` partial or a new `x-` entry (§10 rule 2, §11.4), never by editing this
file.
