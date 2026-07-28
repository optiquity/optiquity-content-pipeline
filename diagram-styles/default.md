---
id: default
provenance: framework
schema_version: 1
tool: dot
---

# default — diagram-style entry (framework default)

The PINNED default style for a generated `{type=diagram}` section (mixed-media increment
C; amendment §2.D/§2.F). It sets the one surviving knob to the honest, reproducible floor:

- **tool: dot** — Graphviz `dot`, the lightest and byte-deterministic hierarchical engine
  (spike-proven identical-per-run). The zero-touch author who selects no style draws every
  diagram with `dot`, so the SAME gated node/edge list yields the SAME SVG bytes on every
  machine. The `(tool, version)` pin is author-time compile provenance, never part of the
  render identity — a tool upgrade re-mints a new content hash on the next compose, exactly
  as the design wants.

This entry exists so the `diagram_style` ref floor always resolves: a recipe that selects
no style still draws honest, reproducible diagrams. Choosing a real style — `d2` for a
grouped look, or an `auto` opt-in for locked environments — is the user's explicit act via
a one-file style add (§5.4) and a recipe's `diagram_style` slot. A style NEVER touches
which boxes/arrows exist (the HARD grounding gate already ran); it only chooses HOW the
checked list is drawn (honesty-safe by construction, amendment §2.F).

Deviations are `extends:` field-merge partials (Mechanism 1, §12.1) or a new `x-` style
file (§11.4/§5.4), never edits to this shipped entry (§10 rule 2).
