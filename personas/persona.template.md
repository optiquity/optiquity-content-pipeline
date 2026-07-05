# Template — Persona entry

Copy this to `personas/<id>.md` and fill it in. One file per audience. Adding a persona = adding
one file (mission §3.2). **Never edit this template file downstream** — copy it. Serialization of
the populated entry is deferred (mission §10.4 D1); the fields below are the requirement.

## Fields

- **id** — stable identifier (used by selection/fanout; never rename casually).
- **name** — human label (e.g. "AI-company hiring manager").
- **knowledge_level** — what they already know; what to assume vs. explain.
- **motivations** — what they want from the content.
- **objections / skepticisms** — what makes them dismiss a piece; what earns trust.
- **credibility_signals** — what "this author is credible" looks like *to them*.
- **tone** — voice/register that lands with them.
- **excluded_formats** — format ids this persona should not receive (compatibility, mission §4.2).
- **notes** — positioning intent.

> Design rule: one file per audience beats one giant voice file — it stops the writer confusing
> audiences (mission §7 role 4). Instance-specific positioning goals live in `instance/profile.md`.
