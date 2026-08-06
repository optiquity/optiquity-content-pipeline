---
id: how-to-documentation
provenance: framework
schema_version: 1
---

# how-to-documentation — Format entry (framework default)

Task-oriented procedural documentation (design §5.2 — a platform-agnostic genre): one
task, taken from a known starting state to a verified end state. The reader is doing,
not browsing.

Rhetorical structure (authoring reference; §15):

1. **Goal** — the task in the reader's terms, and what "done" looks like.
2. **Prerequisites** — required setup, versions, and permissions, stated before the
   first step so nobody fails at step four for a step-zero reason.
3. **Steps** — ordered, one action per step, each with its exact command or action
   grounded in the source (EXTRACTED-tier facts only, §6.5; never invented flags) and
   the expected result where it isn't obvious.
4. **Verification** — how the reader confirms the task actually succeeded.
5. **Troubleshooting** — the likeliest failures and their recovery paths.

Discipline: one task per piece — a second task is a second artifact (§5.2); heavily
grounded — every command, flag, path, and output must trace to the source repo (§3.3,
§6.5). Single-part genre: `parts` rides the schema floor (Q14) — the numbered sections
are rhetorical structure, not named sub-outputs. No platform data lives here (Q4):
where this lands (a docs site, a repo, a knowledge base) is the selected Platform's
business at render time (§12.3).

This body is human-authoring REFERENCE — NOT a compose input: the writer
receives only the bound attributes, the `parts`/`section_schema` structure,
the grounded facts, and (when set) the DR-3 outline drive brief; this body is
never threaded to the writer (§15).
