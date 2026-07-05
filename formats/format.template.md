# Template — Format entry

Copy to `formats/<id>.md`. One file per content format. Carries its compatibility inline (valid
platforms, excluded personas) so the filtered fanout stays correct as you add formats (mission
§3.2 / §4.2). **Never edit this template file downstream.** Serialization deferred (D1).

## Fields

- **id** — stable identifier.
- **name** — e.g. how-to-doc, explainer-doc, blog-post, linkedin-post, medium-post, readme.
- **word_limit** — number or "none."
- **hook_required** — true/false (and hook style if true).
- **structure** — expected section shape / outline.
- **visual_needs** — all-text / optional images / charts-required.
- **valid_platforms** — list of platform ids this format may publish to (compatibility).
- **excluded_personas** — persona ids this format should not target (optional).
- **grounding_depth** — how heavily code-grounded (how-to/readme = high; general blog = medium).
- **notes**.
