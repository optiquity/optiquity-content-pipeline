# .claude/ — project-scoped agents & skills (framework)

Pipeline agents and skills live here (version-controlled, portable), **not** in your global
`~/.claude/`. Added in Phase 1:

- `agents/researcher.md` — read-only grounding (Read/Grep/Glob + `graphify query`); no write tools.
- `agents/writer.md` — composes per persona + platform + format.
- `agents/reviewer.md` — detect-first-fix-later editing + claim verification (Phase 1b).
- `skills/ideate/SKILL.md`, `skills/generate/SKILL.md` — slash-command entry points.

These are framework files: improve them in the public repo and pull downstream. Instances extend
behavior via registries and PROFILE, not by editing these.
