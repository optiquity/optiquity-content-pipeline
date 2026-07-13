# Profile — instance-specific context (template)

Copy to `instance/profile.md` in your **private** instance and fill it in. This holds the
instance-specific direction that does **not** belong in the public framework: your goals, your
default audiences, your machine roles. Gitignored/guarded out of the public repo.

This is prose seed material, not config — it informs the entries you author across the nine axes
(design §5.4). Instance-wide baseline *values* live in `instance/defaults.yaml`
(from `instance/defaults.template.yaml`), not here.

## Positioning goal

_What is this content for? (e.g. career positioning, product marketing, client deliverables.)_

## Default audiences (seed for `personas/`, `voices/`)

_List the audiences you write for; each becomes a `personas/<id>.md` file (with a `default_voice`)._

## Publishing targets (seed for `platforms/`, `output-types/`, `presentations/`)

_The platforms you publish to and their constraints; the output types + look you render to._

## Formats & objectives you produce (seed for `formats/`, `goals/`)

_The genres you need (each becomes a `formats/<id>.md`) and the outcomes they drive (`goals/`)._

## Machine roles (your environment)

| Machine | Role |
|---|---|
| _always-on host_ | graph host + MCP server + n8n orchestration |
| _workstation_ | interactive generation in Claude Code |

## Notes

Keep this in the private instance only. The public framework stays generic and content-free.
