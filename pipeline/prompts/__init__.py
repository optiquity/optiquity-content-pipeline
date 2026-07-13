"""The prompt-template loader (`pipeline/prompts/`) — plan step 23, decision T9.

Design authority: plan decision T9 ("Product-plane LLM stages (writer/reconciler/two
reviewers) packaged as versioned prompt-template files inside the framework package
(`pipeline/prompts/*.md`), invoked headless. Their contracts are ratified [IR §15,
fidelity §16, reviews §19]; their agent/skill packaging is an open area [§27.4] — prompt
templates satisfy the contracts without inventing the open packaging design.");
`docs/design.md` §21.9 ("No LLM/correctness logic here — transport only" — this loader is
equally CONTENT-BLIND: locate a named template's text and return it, nothing more).

**All four contracts are now filled** (each landed in its own step, replacing the step-23
stub in place): `writer.md` (§15 compose, step 24), `reconciler.md` (§16 fit/fidelity, step
25), `artifact_reviewer.md` and `deliverable_reviewer.md` (§19 review gates, step 30). The
loader never assumed, validated, or interpreted a template's interior shape while they were
stubs, and does not now that they are filled (that would be inventing the very packaging
design T9 defers to `§27.4`) — each consuming step edited ITS OWN template file's body in
place when it landed its contract, and this loader never changed at those points.

The loader takes template NAMES only, never caller-supplied paths — there is no path-
traversal surface to defend because there is no path input at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "TEMPLATE_NAMES",
    "TEMPLATES_DIR",
    "PromptTemplate",
    "PromptTemplateError",
    "list_templates",
    "load_template",
]

#: The directory this package's `.md` template files live in — always this package's own
#: directory, never caller-configurable (no instance ever supplies its own prompt files
#: in v1; product-plane prompts are framework mechanism, §10).
TEMPLATES_DIR = Path(__file__).resolve().parent

#: The four framework product-plane prompt-template names (plan Files list across steps
#: 23/24/25/30). Originally shipped as stubs at step 23 and filled in place by their owning
#: steps; all four are now filled contracts. `list_templates()` discovers them dynamically —
#: this constant records the expected framework set.
TEMPLATE_NAMES = ("writer", "reconciler", "artifact_reviewer", "deliverable_reviewer")

#: Template names are a closed, simple identifier shape — lowercase ascii + digits +
#: underscore, starting with a letter. This is a NAME, never a path: no `/`, no `..`,
#: no extension (the loader appends `.md` itself).
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptTemplateError(ValueError):
    """A template name could not be resolved to a file — refused loudly, never guessed."""

    code = "prompt-template-error"


@dataclass(frozen=True)
class PromptTemplate:
    """One loaded template: its name, source path, and raw text.

    `text` is returned EXACTLY as stored on disk — this loader performs no templating,
    substitution, or validation of any kind (content-blind, module docstring); a stub's
    placeholder text loads through this exact same path as a filled contract.
    """

    name: str
    path: Path
    text: str


def list_templates() -> tuple[str, ...]:
    """Every discoverable template name — the `.md` stem of each file directly under
    `pipeline/prompts/` (sorted, so callers get a deterministic listing)."""
    return tuple(sorted(p.stem for p in TEMPLATES_DIR.glob("*.md")))


def load_template(name: str) -> PromptTemplate:
    """Load one named template by NAME (never a path — module docstring).

    A stub (a near-empty placeholder marked as such in its own header) loads exactly
    like a filled contract would — this loader never fails on empty or placeholder
    content; it only fails when `name` is not a legal identifier or names no file.
    """
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise PromptTemplateError(
            f"prompt-template-error: {name!r} is not a valid template name (lowercase "
            "ascii letters/digits/underscore, must start with a letter — never a path)"
        )
    path = TEMPLATES_DIR / f"{name}.md"
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        raise PromptTemplateError(
            f"prompt-template-error: no template named {name!r} under {TEMPLATES_DIR} "
            f"(known: {', '.join(list_templates()) or '<none>'})"
        ) from None
    return PromptTemplate(name=name, path=path, text=text)
