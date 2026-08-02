"""Entry scaffolder (design D11/D8/D9; authoring layer C3). PURE + REUSABLE.

`pipeline entry new DIMENSION ID [--workspace W]` authors ONE new dimension entry from a
schema-conforming, self-documenting skeleton: the envelope (`id`/`provenance`/
`schema_version`) + EVERY attribute at its declared floor (`AttributeSpec.default`, the L0
cascade floor `Schema.defaults()`, §12.2) + each attribute's `definition:` prose emitted as
`#`-comment lines (the same authoring guidance the C1 `docs attributes` reference surfaces).
A floor-only entry is valid BY CONSTRUCTION — every default is a type-valid value the schema
loader already validated (`schema.py`), and a missing attribute rides the floor — so the
scaffold **lints green UNEDITED** (D11/W5). The `#`-comments cannot derail the frontmatter
parse: YAML comments are stripped by the safe loader, so the file still re-parses to exactly
`Schema.defaults()`.

Home + provenance follow §10 by LOCATION, with NO bindings to infer from (a fresh floor
entry references no other entries), so the switch is `--workspace`:
- `--workspace W` → an INSTANCE entry: `x-`-prefixed id, `provenance: instance`, homed at
  `workspaces/<W>/<collection>/x-<id>.md` via the isolation guard (rule 2/§10).
- no `--workspace` → a framework-default *candidate*: `<collection>/<id>.md`,
  `provenance: framework`. It is authored, never auto-committed — the human commit gate is the
  framework/instance boundary (D11). A framework id must NOT carry the `x-` prefix (§11.4).
- `entry new topic …` REQUIRES `--workspace`: topics are workspace editorial data (rule 2/§10),
  never a framework default — refused loudly without one.

Wiring, never duplication (the C2a philosophy): the §7.4 slug alphabet is C2a's `_require_slug`
(the single `attrtypes.validate_value` ref wrapper), the overwrite guard is C2a's
`ensure_writable` (D8: refuse-if-exists / `--force` / TTY-gated / fail-fast headless), the
pinned frontmatter dumper is C2a's `_dump_yaml` (the G4 loader in reverse — one serializer, never
a second), the dimension vocabulary is `m1.DIMENSION_COLLECTIONS`, the workspace isolation guard
is `workspace_name.validate_workspace_path` (§23), and the schema is the co-located `_schema.yaml`
loaded from the root (`schema.load_schema`). The typed refusal class is C2a's `AuthoringError`.

MONEY-SAFETY (§21.9): a LOCAL Tier-A file write — the ONE composition writes exactly one file
(the §5.4 one-file-add). It registers NO invoke verb, touches NO `_VERB_HANDLERS`, and never
dispatches through the invoke door. An entry NAME never enters `build_artifact_preimage`; a
scaffolded entry is inert to identity until a run selects it (D10). A LEAF module: it imports no
identity/plan/cascade code; `__main__` (`entry new`) is the first and only consumer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pipeline.authoring import (
    AuthoringError,
    _dump_yaml,
    _require_slug,
    ensure_writable,
)
from pipeline.entries import (
    ENTRY_SUFFIX,
    INSTANCE_ID_PREFIX,
    PROVENANCE_FRAMEWORK,
    PROVENANCE_INSTANCE,
)
from pipeline.m1 import DIMENSION_COLLECTIONS
from pipeline.schema import SCHEMA_FILENAME, Schema, load_schema
from pipeline.workspace_name import validate_workspace_path

__all__ = [
    "TOPIC_DIMENSION",
    "EntryTarget",
    "load_dimension_schema",
    "resolve_entry_target",
    "scaffold_frontmatter",
    "serialize_entry_scaffold",
    "write_entry",
]

#: The dimension whose entries are workspace editorial data (rule 2/§10) — `entry new topic`
#: REFUSES without a `--workspace`, unlike every other dimension whose framework defaults are the
#: public deliverable. The token is a key of `m1.DIMENSION_COLLECTIONS`.
TOPIC_DIMENSION = "topic"


def _require_dimension(dimension: object) -> str:
    """Refuse anything that is not a real scaffoldable dimension token (loud, never a crash).

    The dimension SET is `m1.DIMENSION_COLLECTIONS` — the nine content/rendering dimensions
    (topic, persona, format, voice, goal, platform, language, output-type, presentation), the
    registry roots that are dimensions. A recipe/selection/lexicon/diagram-style is NOT a
    dimension (those are mechanism registries, authored by their own verbs), so they are refused
    here with the exact allowed set.
    """
    if not isinstance(dimension, str) or dimension not in DIMENSION_COLLECTIONS:
        raise AuthoringError(
            f"invalid-authoring: {dimension!r} is not a scaffoldable dimension — `entry new` "
            f"takes a dimension token: {sorted(DIMENSION_COLLECTIONS)}"
        )
    return dimension


@dataclass(frozen=True)
class EntryTarget:
    """Where a scaffolded entry writes: its dimension, collection, final id, provenance, home
    path, and workspace (if instance-scoped)."""

    dimension: str
    collection: str
    entry_id: str
    provenance: str
    path: Path
    workspace: str | None


def resolve_entry_target(
    root: str | Path,
    dimension: str,
    entry_id: str,
    *,
    user: str | None = None,
    workspace: str | None = None,
) -> EntryTarget:
    """Validate the dimension + id and compute the provenance-homed target path (§10/§11.4).

    `--workspace` decides provenance by LOCATION (there are no bindings to infer from): with a
    workspace the entry is an INSTANCE `x-` entry (the prefix is auto-applied if absent) homed
    under `workspaces/<W>/<collection>/`; without one it is a framework-default candidate under
    the public `<collection>/`. `entry new topic` without a workspace is refused (topics are
    workspace editorial data, rule 2/§10); a framework id carrying the `x-` prefix is refused
    (§11.4). Every final id is §7.4-slug-validated (loud) via C2a's `_require_slug`.
    """
    dimension = _require_dimension(dimension)
    collection = DIMENSION_COLLECTIONS[dimension]
    root = Path(root)

    if workspace is not None:
        if user is None:
            raise AuthoringError(
                "invalid-authoring: an instance (x-) entry requires --user — the home is "
                "users/<user>/workspaces/<W>/<collection>/ (§23, rule 2/§10); a missing user "
                "would build a users/None/ path (never silent)"
            )
        wanted = (
            entry_id
            if isinstance(entry_id, str) and entry_id.startswith(INSTANCE_ID_PREFIX)
            else f"{INSTANCE_ID_PREFIX}{entry_id}"
        )
        _require_slug(wanted, "entry id")
        home = (
            validate_workspace_path(root, user, workspace)
            / collection
            / f"{wanted}{ENTRY_SUFFIX}"
        )
        return EntryTarget(dimension, collection, wanted, PROVENANCE_INSTANCE, home, workspace)

    if dimension == TOPIC_DIMENSION:
        raise AuthoringError(
            "invalid-authoring: `entry new topic` requires --workspace — topics are workspace "
            "editorial data (rule 2/§10), never a framework default; author one under a client "
            "workspace (workspaces/<W>/topics/x-<id>.md)"
        )
    if isinstance(entry_id, str) and entry_id.startswith(INSTANCE_ID_PREFIX):
        raise AuthoringError(
            f"invalid-authoring: a framework entry id must not carry the {INSTANCE_ID_PREFIX!r} "
            f"prefix (§11.4) — pass --workspace to author a client ({INSTANCE_ID_PREFIX}) entry, "
            "or drop the prefix for a framework default candidate"
        )
    _require_slug(entry_id, "entry id")
    home = root / collection / f"{entry_id}{ENTRY_SUFFIX}"
    return EntryTarget(dimension, collection, entry_id, PROVENANCE_FRAMEWORK, home, None)


def load_dimension_schema(root: str | Path, collection: str) -> Schema:
    """Load a dimension's co-located `_schema.yaml` from the root — the scaffold's SSOT.

    The floor + `definition:` prose come from the SAME schema lint validates against at this
    root, so the scaffold conforms by construction (lints green UNEDITED). A root missing the
    schema is a loud refusal (never a bare traceback) — the caller is not a framework checkout.
    """
    schema_path = Path(root) / collection / SCHEMA_FILENAME
    try:
        return load_schema(schema_path)
    except FileNotFoundError as exc:
        raise AuthoringError(
            f"invalid-authoring: no {collection}/{SCHEMA_FILENAME} under {root!s} — `entry new` "
            "scaffolds from the co-located dimension schema; run from a framework checkout root "
            "(or pass --root DIR)"
        ) from exc


def _comment_block(definition: str) -> list[str]:
    """A `definition:` string → `#`-comment lines (multi-line-safe; a blank line → a bare `#`).

    The comments carry the authoring guidance INTO the scaffold (the same `definition:` the C1
    reference surfaces) without ever entering the frontmatter values — the safe YAML loader
    strips `#` comments, so the file still re-parses to exactly `Schema.defaults()`.
    """
    lines: list[str] = []
    for raw in definition.split("\n"):
        text = raw.rstrip()
        lines.append(f"# {text}" if text else "#")
    return lines


def _default_body(dimension: str, entry_id: str) -> str:
    return (
        f"# {entry_id} — {dimension} entry\n\n"
        "Scaffolded by `pipeline entry new`: every attribute above sits at its schema floor, "
        "annotated with its `definition:` guidance. Edit the values in place; the entry lints "
        "green as-is (floor-only is valid) and each attribute you leave at its floor rides the "
        "cascade default (§12.2).\n"
    )


def scaffold_frontmatter(
    schema: Schema,
    *,
    entry_id: str,
    provenance: str,
) -> str:
    """Render the schema-conforming frontmatter: envelope + every attribute at its floor, each
    prefaced by its `definition:` as `#`-comments (a zero-attribute dimension gets a documented
    'no attributes' line, never a crash)."""
    parts: list[str] = [
        _dump_yaml(
            {
                "id": entry_id,
                "provenance": provenance,
                "schema_version": schema.schema_version,
            }
        )
    ]
    if schema.attributes:
        for name, spec in schema.attributes.items():  # schema-declared order → deterministic
            parts.extend(f"{line}\n" for line in _comment_block(spec.definition))
            parts.append(_dump_yaml({name: spec.default}))
    else:
        parts.append(
            "# This dimension declares no attributes (attributes: {}); the envelope IS the "
            "whole entry (§11.1).\n"
        )
    return "".join(parts)


def serialize_entry_scaffold(
    schema: Schema,
    *,
    dimension: str,
    entry_id: str,
    provenance: str,
    body: str | None = None,
) -> str:
    """The full scaffold text: `---` frontmatter (envelope + floors + `definition:` comments)
    `---` + a self-documenting body. Valid + green by construction (D11/W5)."""
    body_text = _default_body(dimension, entry_id) if body is None else body
    frontmatter = scaffold_frontmatter(schema, entry_id=entry_id, provenance=provenance)
    text = "---\n" + frontmatter + "---\n"
    if body_text:
        text += body_text if body_text.endswith("\n") else body_text + "\n"
    return text


def write_entry(
    root: str | Path,
    dimension: str,
    entry_id: str,
    *,
    user: str | None = None,
    workspace: str | None = None,
    force: bool = False,
    body: str | None = None,
    isatty: Callable[[], bool] | None = None,
    confirm: Callable[[Path], bool] | None = None,
) -> EntryTarget:
    """Resolve the target + load the dimension schema + serialize the floor scaffold + overwrite-
    guard + write ONE file; return the target.

    The ONE composition the `entry new` verb (C3) drives — every hard part (slug validation,
    overwrite guard, the pinned dumper) is REUSED from C2a (`pipeline.authoring`), never
    re-implemented. Writes exactly one file (§5.4 one-file-add). NEVER registers an invoke verb /
    hits the invoke door (§21.9).
    """
    target = resolve_entry_target(root, dimension, entry_id, user=user, workspace=workspace)
    schema = load_dimension_schema(root, target.collection)
    text = serialize_entry_scaffold(
        schema,
        dimension=target.dimension,
        entry_id=target.entry_id,
        provenance=target.provenance,
        body=body,
    )
    ensure_writable(target.path, force=force, isatty=isatty, confirm=confirm)
    target.path.parent.mkdir(parents=True, exist_ok=True)
    target.path.write_text(text, encoding="utf-8")
    return target
