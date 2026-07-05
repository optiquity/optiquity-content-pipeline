# Template — Platform entry

Copy to `platforms/<id>.md`. One file per publishing platform. Carries its own constraints inline
so the compatibility filter/fanout extend automatically (mission §3.2 / §4.2). **Never edit this
template file downstream.** Serialization deferred (D1).

## Fields

- **id** — stable identifier.
- **name** — e.g. LinkedIn, Medium, Substack, GitHub, personal-site.
- **length_norms** — typical/expected length range or "no limit."
- **hook_required** — does the opening need an attention hook? (true/false)
- **formatting** — platform conventions (line breaks, headers, markdown/MDX, etc.).
- **image_support** — none / hero / inline / charts.
- **publish_path** — API-automatable, or "staged draft to copy" (mission §10: Medium API
  deprecated, LinkedIn restrictive, Substack no API).
- **notes**.
