"""Deterministic attribute-reference generator (design §11; authoring layer D12).

`pipeline docs attributes` renders `docs/reference/attributes.md` — a user-facing reference
of what every framework registry attribute MEANS (its `_schema.yaml` `definition:` prose,
emitted verbatim) and its mechanical facts (type, floor default, `definition_version`).

Framework-only by construction (rule 4, §10). The walk is `pipeline.lint.REGISTRY_ROOTS`
(the named framework registry directories) — deliberately NOT `iter_lint_collections`, which
also visits `instance/` and `workspaces/` and would leak client/per-deployment schemas into a
public doc AND make the byte-equality drift test diverge by checkout. Nothing else is ever
visited.

Deterministic by construction: collections are walked in sorted order and attributes are
emitted in sorted order; the output is a pure function of the committed schema files — no
clock, no environment, no cwd. `render_attributes_doc()` returns the exact bytes the drift
test (`tests/test_attributes_doc_contract.py`) asserts are committed at
`docs/reference/attributes.md`.

This is a LOCAL operator generator (design D13): it writes a framework doc via the local CLI
and is never wired to an HTTP `_VERB_HANDLERS` verb (not a spend door, no identity surface).
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline import lint
from pipeline.attrtypes import AttrTypeSpec
from pipeline.layout import registry_dir
from pipeline.schema import SCHEMA_FILENAME, AttributeSpec, Schema, load_schema

__all__ = [
    "DOC_RELPATH",
    "GENERATED_HEADER",
    "framework_root",
    "iter_documented_schemas",
    "render_attributes_doc",
    "write_attributes_doc",
]

#: The committed artifact this generator owns (repo-relative).
DOC_RELPATH = "docs/reference/attributes.md"

#: The "do not edit — regenerate" banner (first line of the emitted doc).
GENERATED_HEADER = "<!-- GENERATED — do not edit; run `pipeline docs attributes` -->"


def framework_root() -> Path:
    """The framework repo root — derived from this module's own location, cwd-independent."""
    return Path(__file__).resolve().parents[1]


def iter_documented_schemas(root: str | Path | None = None) -> list[tuple[str, Schema]]:
    """Load every framework registry schema, in the sorted walk order the doc uses.

    Walks `lint.REGISTRY_ROOTS` ONLY (framework, §10) — never `iter_lint_collections` — so the
    documented collection set is exactly `set(lint.REGISTRY_ROOTS)`, checkout-invariant, with no
    `instance/`/`workspaces/` leak. A named root missing its co-located `_schema.yaml` is a
    framework invariant break and is refused loudly (SV4, §13.4)."""
    base = Path(root) if root is not None else framework_root()
    loaded: list[tuple[str, Schema]] = []
    for name in sorted(lint.REGISTRY_ROOTS):
        schema_path = registry_dir(base, name) / SCHEMA_FILENAME
        if not schema_path.is_file():
            raise FileNotFoundError(
                f"attrdoc: registry root {name!r} has no co-located {SCHEMA_FILENAME} at "
                f"{schema_path} — every REGISTRY_ROOTS collection carries one (SV4, §13.4)"
            )
        loaded.append((name, load_schema(schema_path)))
    return loaded


def _render_type(spec: AttrTypeSpec) -> str:
    """A stable, human-readable rendering of a §11.1 attribute type."""
    kind = spec.kind
    if kind == "enum":
        members = ", ".join(json.dumps(v, ensure_ascii=False) for v in (spec.values or ()))
        return f"enum ({members})"
    if kind in {"list", "set", "map"}:
        if spec.element is not None:
            return f"{kind} of {_render_type(spec.element)}"
        return kind
    return kind


def _render_default(value: object) -> str:
    """A stable, canonical rendering of a floor default (deterministic across runs)."""

    def _fallback(obj: object) -> str:
        # date/datetime floors (date-window) and any other non-JSON scalar → stable text.
        iso = getattr(obj, "isoformat", None)
        return iso() if callable(iso) else repr(obj)

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=_fallback)


def _render_attribute(spec: AttributeSpec) -> list[str]:
    lines = [
        f"### `{spec.name}`",
        "",
        f"- **type:** `{_render_type(spec.type)}`",
        f"- **floor (default):** `{_render_default(spec.default)}`",
        f"- **definition version:** {spec.definition_version}",
    ]
    if spec.combine != "replace":
        lines.append(f"- **combine:** `{spec.combine}`")
    lines += ["", spec.definition, ""]
    return lines


def render_attributes_doc(root: str | Path | None = None) -> str:
    """Render the full `attributes.md` document as a string (the drift-test ground truth)."""
    schemas = iter_documented_schemas(root)
    attr_count = sum(len(schema.attributes) for _, schema in schemas)

    lines: list[str] = [
        GENERATED_HEADER,
        "",
        "# Registry attribute reference",
        "",
        (
            "What every registry attribute MEANS and DOES. This page is generated from the "
            "framework registry schemas — the `REGISTRY_ROOTS` walked by `pipeline.lint` — so it "
            "carries framework mechanism only, never client or per-deployment content. Each "
            "attribute lists its type, its floor (the L0 cascade default, §12.2), its "
            "`definition_version`, and the schema's own `definition:` prose, verbatim."
        ),
        "",
        (
            "Regenerate with `pipeline docs attributes`. A byte-equality CI test "
            "(`tests/test_attributes_doc_contract.py`) fails loudly if a schema `definition:` is "
            "edited without regenerating this file."
        ),
        "",
        f"Documented: {len(schemas)} collections, {attr_count} attributes.",
        "",
    ]

    for name, schema in schemas:
        lines += [f"## `{name}` — schema_version {schema.schema_version}", ""]
        if not schema.attributes:
            lines += [
                (
                    "_No attributes: a thin registry whose entry id and body prose are the whole "
                    "object (`attributes: {}`, §11.7 SV10)._"
                ),
                "",
            ]
            continue
        for attr_name in sorted(schema.attributes):
            lines += _render_attribute(schema.attributes[attr_name])

    return "\n".join(lines).rstrip("\n") + "\n"


def write_attributes_doc(root: str | Path | None = None) -> Path:
    """Render and write `docs/reference/attributes.md`; return the written path."""
    base = Path(root) if root is not None else framework_root()
    out_path = base / DOC_RELPATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_attributes_doc(root), encoding="utf-8")
    return out_path
