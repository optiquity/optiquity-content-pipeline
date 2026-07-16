---
name: architecture-review
description: Use when assessing a design or change for architectural soundness — orthogonality, layer discipline, state ownership, abstraction quality, extensibility, and blast radius.
allowed-tools: Read, Grep, Glob, Bash
---

# Architecture review

Assess along these axes (grounded in `docs/design.md`):

- **Orthogonality (north star)** — does each element do exactly one job, with no crossover?
  Dimensions/attributes must not blur; content vs. rendering stays clean; the three cascades order
  different things.
- **Extensibility** — is adding a value a **one-file** change? If a second edit is required, that's a
  defect (mission §3.2).
- **Layer discipline** — framework vs. instance; content vs. rendering; the override cascades (§3.8)
  in the correct order (entry resolution / value binding / preference weighting).
- **State ownership / SSOT** — is there a single source of truth? (tracking spreadsheet = SSOT;
  `state.md` derived; `design.md` the design record.)
- **Abstraction quality** — pluggable at the ends (source/renderer adapters), stable core (the IR).
- **Backward compatibility** — additive-only, schema-level defaults, no in-place meaning changes
  (§3.10).
- **Blast radius** — grep for every cross-reference before recommending a change; name what else is
  affected.
- **Elegance bias** — prefer fewer files, fewer conventions, fewer special cases.

## Output

Findings with file/line references. **Describe the constraint or design problem before proposing a
solution**, and only propose within your assigned remit/mode.
