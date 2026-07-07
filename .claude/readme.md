# .claude/ — project-scoped agents & skills (framework)

Agents and skills live here (version-controlled, portable), **not** in your global `~/.claude/`.
There are **two planes** (see `docs/design-decisions.md` §6).

## Framework-ops plane (present) — builds and maintains THIS repo

Maintainer tooling for designing and implementing the framework. Orchestrated by the main session
per `docs/ops-workflow.md`; agent-common rules are in `CLAUDE.md`.

- `agents/ops-docs-researcher.md` — RO; verifies external tool facts + internal census before design.
- `agents/ops-architect.md` — RO; design decisions (modes: initial / adversarial / reconciliation).
- `agents/ops-planner.md` — RO; implementation planning (same three modes).
- `agents/ops-coder.md` — RW; executes an approved plan in the main checkout; never commits.
- `agents/ops-reviewer.md` — RO; pre-commit review, CLEAN / FIXES-NEEDED verdict.
- `skills/` — `architecture-review`, `planning`, `documentation`, `review`, `verification-harness`,
  `commit-discipline`, `implementation-report`, `boundary-investigation`, `dependency-intake`.

## Product plane (deferred) — the client deliverable

The content-generation agents/skills clients run: `researcher`, `writer` (emits the IR),
`editor/reviewer`, a `render` stage, and skills (`ground-repo`, `persona-voice`, `format-spec`,
`select-and-fanout`, `voice-from-examples`, …). **Designed but not yet built** — see
`docs/design-decisions.md` §6. These will be visibly separated from the `ops-*` plane.

These are framework files: improve them in the public repo and pull downstream. Instances extend
behavior via registries and PROFILE, not by editing these.
