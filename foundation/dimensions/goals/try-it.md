---
id: try-it
provenance: framework
schema_version: 1
kind: action
---

# try-it — Goal entry (framework default)

`kind: action` — a CTA is simply a goal with `kind: action` (design §5.2; no separate
CTA mechanism exists). The artifact drives one concrete reader act: try the thing —
run the quickstart, clone the repo, open the demo.

Generic by design: WHAT to try and WHERE it lives come from the topic's grounding and
the instance's own configuration, never from this entry. No source-selection
contribution (the floor): the act rides whatever grounding the stacked strategic
goals assembled. Typically stacked (§5.2), e.g. `goals: [explain, try-it]` — goals
stack into ONE artifact; a goal-set is canonicalized into `artifact-id` (§7.1).
