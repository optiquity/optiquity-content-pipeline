# Design record — Mixed-media documents (images + captions AND generated diagrams)

Archived load-bearing design records for the **mixed-media documents** capability (tracked in
`docs/known-issues.md` as **DR-7**). These records settle, across a base pass, an amendment pass, a
grouping pass, and a box pass, how a single document can carry **existing image assets with captions**
AND **pipeline-generated diagrams**, declared with one `{type=…}` section marker in the same outline the
author already writes prose in — under the one hard promise that **a generated diagram cannot lie by
adding, hiding, or grouping**.

The design is **RATIFIED but NOT built**. The settled build order is **A → B → C → D**, with **E
DEFERRED** (see DR-7 in [`../../../known-issues.md`](../../../known-issues.md) for the full scope
statement):

- **A** — content-asset store + intra-body path containment guard + the two framework/instance
  provenance homes.
- **B** — the deferred filesystem asset loader + `--resource-path` / `--embed-resources` lowering (images
  embed in HTML/docx, not just referenced-by-path on Markdown).
- **C** — flat honest generated diagrams: a grounded node/edge grammar + the HARD blocking fact-check
  gate + a Graphviz `dot`-pinned / `d2`-selectable / `auto`-opt-in auto-render compiled to a stored SVG +
  the `diagram-styles/` registry + the single honesty-safe `tool` knob.
- **D** — honest **badge** grouping (each node tagged with its cited subsystem: grounded name + grounded
  membership + a mandatory plain-text legend; no enclosing box).
- **E (DEFERRED)** — the enclosing subsystem **box** (a closed "these are all and only the members"
  boundary claim). Deferred because today's grounding layer cannot produce complete, EXTRACTED-tier
  membership to back it; on today's grounding an enforced box would fake "all members." See the two box
  records below and DR-7 for the plain reason.

## The records (role of each, and the final decision)

The records are the reconciliations (the settled outputs) plus the box pass's initial + adversarial
(kept in full because the box's *deferral* is the decision, and the adversarial is where it was made):

| File | Role | Final decision it carries |
|---|---|---|
| [`architect-reconciliation.md`](architect-reconciliation.md) | **BASE** reconciliation | A generated diagram = a grounded node/edge list; a HARD blocking fact-check gate before any picture; compile at compose-time to a stored SVG asset; the asset foundation; the A → B → C build sequence. Overturns the initial's native-Mermaid default and its "prompt + advisory" grounding. |
| [`architect-amendment-reconciliation.md`](architect-amendment-reconciliation.md) | **AMENDMENT** reconciliation (multi-tool + knobs) | Multi-tool `dot` (pinned default) / `d2` (selectable) / `auto` (opt-in only); the single `tool` knob survives; the masking knobs `detail` / `altitude` / `connectivity` are CUT; the `diagram-styles/` referenced-registry home. The honest promise stated in three parts: a diagram cannot lie by ADDING, HIDING, or GROUPING. |
| [`architect-grouping-reconciliation.md`](architect-grouping-reconciliation.md) | **GROUPING** reconciliation (box vs badge) | Honest **badge** grouping (each node tagged with its cited subsystem — grounded name + grounded membership + a mandatory legend) replaces the enclosing box; ship flat diagrams (C) first, badge grouping as fast-follow (D). |
| [`architect-box-initial.md`](architect-box-initial.md) | **BOX (E)** initial design | Designs the ONLY honest way to draw the enclosing box: ENFORCE completeness (a new grounding capability — enumerable structured membership + a set-equality gate + a cluster emitter + a mandatory reality-gap caption). Disclosure-without-enforcement is rejected. Recommends E is NOT ready to plan alongside A→D. |
| [`architect-box-adversarial.md`](architect-box-adversarial.md) | **BOX (E)** adversarial | Verdict: **stop at badges (D); do not build the box (E) now.** On today's grounding the enforced box only closes over a budget-truncated query window (not "known to the source"), the omission hole merely moves to the query layer, and no real adapter can produce EXTRACTED-tier enumerable membership — so an enforced box would fake completeness. E is deferred, to be re-derived from scratch if a real closed-world need is ever named. |

**The settled decision, in one line:** build A → B → C → D; **defer E** (the enclosing subsystem box)
until the grounding layer can extract complete, verified membership and a real closed-world need is
named.

## Historical note — scratch/spike paths cited by these records

These records were written against a working scratchpad and a since-removed diagram spike. They cite
paths that were **scratch/working artifacts and may no longer exist** — treat every such citation as
**historical**, not as a live path in this repo:

- The handoff/scratch home `ops-handoff/mixed-media/…` (where these records were produced before being
  archived here).
- The diagram spike (`harness.py` and its `gate()` / `to_dot` / `to_d2` helpers) referenced in the
  amendment and grouping records — a de-risking prototype that was **removed after the passes ran** (the
  grouping reconciliation §4.1 records "the spike is gone"). Its findings (both `dot` and `d2` compile
  the gated list to byte-deterministic SVG; the gate refuses uncited edges) are captured in the prose.

Live code citations (e.g. `pipeline/sections.py:102`, `pipeline/compose.py:653-694`,
`pipeline/ir.py:706-729`, `pipeline/dispatch.py:121`, `pipeline/graphify.py`, `pipeline/grounding.py:387`)
were re-verified at file:line during each pass against `main @ cc42c54`; the feature itself is unbuilt,
so these name the surfaces a future build touches, not existing mixed-media code.
