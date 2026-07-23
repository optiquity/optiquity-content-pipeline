---
id: product-requirements-document
provenance: framework
schema_version: 1
---

# product-requirements-document — Format entry (framework default)

The PRD genre (design §5.2 — a platform-agnostic genre): a decision-enabling
specification of WHAT a product change must achieve and how success will be judged —
requirements as testable statements, never implementation prescriptions.

Rhetorical structure (authoring reference; §15):

1. **Problem & context** — the user problem, with grounded evidence that it exists
   (EXTRACTED-tier facts as stated fact, §6.5); who has it and how badly.
2. **Objectives & success metrics** — what changes if this works, stated so a metric
   could confirm or refute it.
3. **Scope** — what is in, and explicitly what is out (non-goals carry as much
   decision weight as goals).
4. **Requirements** — numbered, individually testable statements, each traceable to
   the problem, with priority made explicit.
5. **Constraints, risks & open questions** — known limits, what could invalidate the
   plan, and what is still undecided (INFERRED/AMBIGUOUS leads live here as flagged
   questions, never as requirements, §6.5).

Discipline: one product change per PRD — an unrelated second initiative is a second
artifact (§5.2). Single-part genre: `parts` rides the schema floor (Q14) — the
numbered sections are rhetorical structure inside one document, not sub-outputs
(contrast Q14's slide-deck → slides + presenter-notes). No platform data lives here
(Q4): whether this lands in a wiki, a repo, or a doc file is the selected Platform's
routing at render time (§12.3).

This body is human-authoring REFERENCE — NOT a compose input: the writer
receives only the bound attributes, the `parts`/`section_schema` structure,
the grounded facts, and (when set) the DR-3 outline drive brief; this body is
never threaded to the writer (§15).
