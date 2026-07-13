"""Presentation lowering (§17 PD3/PD4) — the full `lower(presentation, writer, output-type)`.

Design authority: `docs/design.md`
  §5.3 PD2 — the v1 Presentation schema (minimal + grow-hook): exactly the levers that are
        Pandoc flags, hashable files, or per-writer dispatch — `variables`, `highlight_style`,
        `template` (per-writer; pptx has none), `reference_doc` (docx/pptx/odt), `css`
        (html/epub, ORDER load-bearing), `pdf` (engine + options). `fonts`/`margins` ride
        INSIDE `variables`; `variables` is the guaranteed grow-later hook.
  §5.3 PD3 (hard) — **one interface:** `lower(presentation, writer, output-type) →
        RenderInputs{flags, variables, assets+hashes, engine}` — one flat struct, applied as
        one writer call on the persisted AST (PD4). The dispatcher (§17) sees ONLY that struct.
        The html5/epub3 provenance-strip filter is serialize-owned, NEVER a Presentation lever
        (`pipeline.filters.provenance_strip`): nothing in this module's surface can disable it.
  §5.3 PD5 — **zero-churn identity:** the `deliverable-id` gains the presentation slug; the
        `plain` floor (every lever at its schema default) lowers to the EMPTY struct, so
        shipping the dimension moves no id (delta-vs-floor over the variable/attribute values,
        §7.2). This module reuses `ids.delta_vs_floor` (CA6) for exactly that pledge.
  §17 FR7.1 — **"the pin bundle IS its preimage", taken literally:** the lowered RenderInputs —
        flags, the variables snapshot, and **every asset by CONTENT hash** — folds into the
        serialize-inputs preimage. An edited css file churns the render digest even when no
        schema version moved, because its content hash is part of the preimage (§17). Asset
        content hashes are LITERAL (no schema floor), so they churn only when the bytes change.
  §5.3 PD8 — Presentation does not own `writer`/`side` (render-target fields, §17). RenderInputs
        ride the identical channel internally and, for `side: external`, fold into the layer-3
        contract payload (`pipeline.payload`).

**The asset content hash is the whole point of PD5's honesty at this level.** A `PresentationAsset`
carries its declared `path` (the reference the pandoc flag names) AND its `content` bytes; its
`content_hash` is `sha256_hex(content)`. Two presentations that name the same css PATH but ship
DIFFERENT bytes lower to DIFFERENT assets → different preimage → different serialize digest → an
auto-minted serialize revision (§17 FR7.3). This is what makes "an edited css file churns the
digest" (the step-29 acceptance) true by construction, with no schema version moved.

**Purity.** `lower` is a deterministic function of `(presentation, writer, output-type,
target_engine)` — no filesystem read, no wall-clock, no ambient state. Asset bytes are resolved
into `PresentationAsset` BEFORE `lower` (the I/O is `presentation_from_entry`'s job, injected via
an `AssetLoader`), so the lowering stays testable and byte-reproducible.

**No SSOT import (INV-CORRECTNESS, §22.7):** correctness rides content-addressed output, never
the SSOT. This module imports none of it — only `pipeline.dispatch` (the `RenderInputs` vocabulary
it produces), `pipeline.ids` (`delta_vs_floor`), and `pipeline.canonical` (the content digest).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pipeline.canonical import sha256_hex
from pipeline.dispatch import RenderInputs
from pipeline.ids import PreimageError, delta_vs_floor

__all__ = [
    "CSS_WRITERS",
    "NO_TEMPLATE_WRITERS",
    "PDF_OUTPUT_TYPES",
    "REFERENCE_DOC_WRITERS",
    "AssetLoader",
    "Presentation",
    "PresentationAsset",
    "PresentationError",
    "lower",
    "plain_presentation",
    "presentation_from_entry",
    "render_inputs_to_mapping",
]

#: §5.3 PD2 writer families. `css` applies to the html/epub writer family ONLY (order is
#: load-bearing — the CSS cascade — so the css FLAGS preserve list order); a `--css` on a
#: docx/pptx writer is meaningless. Kept explicit so a per-writer lever is never mis-applied.
CSS_WRITERS = frozenset(
    {
        "html",
        "html4",
        "html5",
        "chunkedhtml",
        "revealjs",
        "s5",
        "slidy",
        "slideous",
        "dzslides",
        "epub",
        "epub2",
        "epub3",
    }
)

#: §5.3 PD2: `--reference-doc` is the docx/pptx/odt style carrier (the Office/ODT family).
REFERENCE_DOC_WRITERS = frozenset({"docx", "pptx", "odt"})

#: §5.3 PD2: "pptx has no template — its lever is reference_doc." A `template[pptx]` entry is a
#: no-op flag we must never emit; every other writer takes `--template`.
NO_TEMPLATE_WRITERS = frozenset({"pptx"})

#: §5.3 PD2 / §17 RI13: the `pdf` lever (engine + options) applies when the output-type is pdf
#: (or the writer is the raw `pdf` writer). The engine lowers into `RenderInputs.engine`.
PDF_OUTPUT_TYPES = frozenset({"pdf"})


class PresentationError(ValueError):
    """A malformed Presentation input — a non-mapping variable set, a bad asset, a variable that
    smuggles a §7.3 identity-exclusion key. Loud and typed (§3.1), never silently repaired."""

    code = "presentation-error"


# ---------------------------------------------------------------------------
# The resolved Presentation view (§5.3 PD2) — assets carry CONTENT for per-asset hashing.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresentationAsset:
    """One hashable Presentation asset (§5.3 PD2 / §17 FR7.1): a css/template/reference-doc file.

    `role` names the lever (`css` | `template` | `reference-doc`); `path` is the reference the
    pandoc flag names (`--css=<path>`); `content` are the asset BYTES. `content_hash` is the
    per-asset content digest that rides the serialize-inputs preimage — so an edit to the file's
    bytes churns the render digest even when its path and no schema version moved (§17 FR7.1).
    """

    role: str
    path: str
    content: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise PresentationError(
                f"presentation-error: asset {self.role!r} needs a non-empty path, got {self.path!r}"
            )
        if not isinstance(self.content, bytes | bytearray):
            raise PresentationError(
                f"presentation-error: asset {self.path!r} content must be bytes (the hash preimage,"
                f" §17 FR7.1), got {type(self.content).__name__}"
            )

    @property
    def content_hash(self) -> str:
        """The per-asset content digest (full SHA-256 hex) — LITERAL in the preimage (§17 FR7.1:
        asset hashes have no schema floor and churn only when the bytes actually change)."""
        return sha256_hex(bytes(self.content))


@dataclass(frozen=True)
class Presentation:
    """A resolved Presentation entry (§5.3 PD2) — the effective values `lower` consumes.

    `presentation_id` is the entry slug, a `deliverable-id` COORDINATE (PD5) — it is NOT a
    byte-determining input and never enters the serialize-inputs preimage (the coordinate lives
    in the id, §17 FR7.1). `variables`/`variable_defaults` drive the delta-vs-floor snapshot
    (PD5 zero-churn); `highlight_style` is the `--highlight-style` lever; `templates` and
    `reference_docs` are per-writer asset maps (keyed by writer); `css` is the ORDERED html/epub
    stylesheet list; `pdf` is `{engine?, options?}`.
    """

    presentation_id: str = "plain"
    variables: Mapping[str, Any] = field(default_factory=dict)
    variable_defaults: Mapping[str, Any] = field(default_factory=dict)
    highlight_style: str = ""
    templates: Mapping[str, PresentationAsset] = field(default_factory=dict)
    reference_docs: Mapping[str, PresentationAsset] = field(default_factory=dict)
    css: Sequence[PresentationAsset] = ()
    pdf: Mapping[str, Any] = field(default_factory=dict)


def plain_presentation() -> Presentation:
    """The framework `plain` floor (PD7): sets NO lever, so `lower` returns the empty RenderInputs
    (bar the render-target's own engine) — the zero-id-churn schema floor (PD5, §7.2)."""
    return Presentation(presentation_id="plain")


# ---------------------------------------------------------------------------
# The one interface (PD3): lower(presentation, writer, output-type) → RenderInputs.
# ---------------------------------------------------------------------------


def _flag_value(value: Any) -> str:
    """Render one scalar variable value for a `--variable=key=value` flag (bool as the pandoc
    truthy tokens; other scalars via `str`). Non-scalar values never reach here (see `lower`)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def lower(
    presentation: Presentation,
    writer: str,
    output_type: str,
    *,
    target_engine: str = "",
) -> RenderInputs:
    """The PD3 lowering: one Presentation + the target's `writer`/`output-type` → RenderInputs.

    Deterministic and side-effect-free (§5.3 PD3/PD4). The mapping:
      - **variables** → the delta-vs-floor snapshot (PD5 zero-churn; `ids.delta_vs_floor`, CA6)
        rides `RenderInputs.variables`; each SCALAR delta also emits a `--variable=key=value`
        flag (a non-scalar variable rides the snapshot for IDENTITY only — pandoc `-V` is a
        scalar lever, so v1 emits no flag for it, PD2 grow-hook);
      - **highlight_style** (if set) → a `--highlight-style=<style>` flag;
      - **css** (html/epub writers) → `--css=<path>` flags IN LIST ORDER (the cascade is
        load-bearing) + each file as a content-hashed asset;
      - **template** (`templates[writer]`, never pptx) → `--template=<path>` flag + asset;
      - **reference_doc** (`reference_docs[writer]`, docx/pptx/odt) → `--reference-doc=<path>`
        flag + asset;
      - **pdf** (output-type pdf or the `pdf` writer) → `engine` (presentation engine over the
        target's, PD2) + `--pdf-engine-opt=<opt>` flags.

    Assets fold into `RenderInputs.assets` as `(path, content-hash)` in SORTED order (a stable
    preimage digest; the render-order semantics live in the ordered `flags`). The `plain` floor
    (no lever set) returns `RenderInputs(engine=target_engine)` — byte-identical to step 27's
    minimal lowering, so the floor causes ZERO id churn (PD5).
    """
    if not isinstance(writer, str) or not writer:
        raise PresentationError(
            f"presentation-error: writer must be a non-empty string, got {writer!r}"
        )
    if not isinstance(output_type, str) or not output_type:
        raise PresentationError(
            f"presentation-error: output-type must be a non-empty string, got {output_type!r}"
        )

    flags: list[str] = []
    assets: list[tuple[str, str]] = []

    # variables — delta-vs-floor (PD5). delta_vs_floor refuses the §7.3 identity-exclusion keys
    # (schema_version/metadata) at attr-NAME positions, so a variable can never smuggle one.
    try:
        var_delta = delta_vs_floor(
            presentation.variables, presentation.variable_defaults, where="presentation.variables"
        )
    except PreimageError as exc:
        raise PresentationError(f"presentation-error: {exc}") from exc
    for key in sorted(var_delta):
        value = var_delta[key]
        if isinstance(value, str | int | float):  # scalar (bool ⊂ int) — a pandoc -V lever
            flags.append(f"--variable={key}={_flag_value(value)}")

    if presentation.highlight_style:
        flags.append(f"--highlight-style={presentation.highlight_style}")

    if writer in CSS_WRITERS:
        for asset in presentation.css:  # ORDER preserved — the CSS cascade is load-bearing (PD2)
            flags.append(f"--css={asset.path}")
            assets.append((asset.path, asset.content_hash))

    template = presentation.templates.get(writer)
    if template is not None and writer not in NO_TEMPLATE_WRITERS:
        flags.append(f"--template={template.path}")
        assets.append((template.path, template.content_hash))

    reference = presentation.reference_docs.get(writer)
    if reference is not None and writer in REFERENCE_DOC_WRITERS:
        flags.append(f"--reference-doc={reference.path}")
        assets.append((reference.path, reference.content_hash))

    engine = target_engine
    if output_type in PDF_OUTPUT_TYPES or writer == "pdf":
        if presentation.pdf:
            engine = str(presentation.pdf.get("engine") or target_engine)
            for opt in presentation.pdf.get("options", ()):
                flags.append(f"--pdf-engine-opt={opt}")

    return RenderInputs(
        flags=tuple(flags),
        variables=dict(var_delta),
        assets=tuple(sorted(assets)),
        engine=engine,
    )


def render_inputs_to_mapping(render_inputs: RenderInputs) -> dict[str, Any]:
    """The canonical pure-JSON mapping of a lowered RenderInputs — the `render_inputs` component
    of the serialize-inputs preimage (§17 FR7.1). Tuples become lists so the value is JSON-pure
    and byte-stable under a canonical round-trip (`serialize.serialize_inputs_preimage` reads it).
    The `plain` floor maps to `{flags: [], variables: {}, assets: [], engine: ""}` — exactly the
    step-27 skeleton input, so the deliverable-id is byte-identical (zero id churn, PD5)."""
    return {
        "flags": list(render_inputs.flags),
        "variables": dict(render_inputs.variables),
        "assets": [[path, digest] for path, digest in render_inputs.assets],
        "engine": render_inputs.engine,
    }


# ---------------------------------------------------------------------------
# Building a resolved Presentation from a registry entry (§5.3 PD2 schema) + an asset loader.
# ---------------------------------------------------------------------------

#: Resolve an asset PATH (a css/template/reference-doc file reference) to its BYTES. Injected so
#: `presentation_from_entry` stays testable and `lower` stays pure (the I/O is here, not there).
AssetLoader = Callable[[str], bytes]


def _asset(role: str, path: Any, load: AssetLoader) -> PresentationAsset:
    if not isinstance(path, str) or not path:
        raise PresentationError(
            f"presentation-error: {role!r} asset path must be a non-empty string, got {path!r}"
        )
    content = load(path)
    if not isinstance(content, bytes | bytearray):
        raise PresentationError(
            f"presentation-error: the asset loader returned {type(content).__name__} for "
            f"{path!r}; it must return the file bytes (§17 FR7.1 hash preimage)"
        )
    return PresentationAsset(role=role, path=path, content=bytes(content))


def presentation_from_entry(
    entry: Mapping[str, Any],
    *,
    load_asset: AssetLoader,
    defaults: Mapping[str, Any] | None = None,
) -> Presentation:
    """Build a resolved `Presentation` from a §5.3 PD2 registry entry's effective values.

    `entry` carries the PD2 attributes (`variables`, `highlight_style`, `template`,
    `reference_doc`, `css`, `pdf`); `defaults` is the schema-default floor for the variables
    delta (PD5); `load_asset` reads each css/template/reference-doc PATH into its bytes (the
    only I/O). The `template`/`reference_doc` maps are per-writer (keyed by writer name, PD2);
    `css` is an ORDERED path list. `presentation_id` rides `entry['id']` (a coordinate, not an
    identity input). Absent levers stay at their floor — so a `plain`-shaped entry yields the
    empty lowering (zero id churn, PD5)."""
    if not isinstance(entry, Mapping):
        raise PresentationError(
            f"presentation-error: a presentation entry must be a mapping, got "
            f"{type(entry).__name__}"
        )
    variables = entry.get("variables", {})
    if not isinstance(variables, Mapping):
        raise PresentationError("presentation-error: `variables` must be a map (§5.3 PD2)")
    variable_defaults = {}
    if defaults is not None:
        variable_defaults = defaults.get("variables", {})
        if not isinstance(variable_defaults, Mapping):
            raise PresentationError("presentation-error: the `variables` default must be a map")

    templates = {
        writer: _asset("template", path, load_asset)
        for writer, path in dict(entry.get("template", {})).items()
    }
    reference_docs = {
        writer: _asset("reference-doc", path, load_asset)
        for writer, path in dict(entry.get("reference_doc", {})).items()
    }
    css_paths = entry.get("css", [])
    if isinstance(css_paths, str | bytes):
        raise PresentationError("presentation-error: `css` must be an ordered list of paths (PD2)")
    css = tuple(_asset("css", path, load_asset) for path in css_paths)
    pdf = entry.get("pdf", {})
    if not isinstance(pdf, Mapping):
        raise PresentationError("presentation-error: `pdf` must be a map {engine?, options?} (PD2)")

    return Presentation(
        presentation_id=str(entry.get("id", "plain")),
        variables=dict(variables),
        variable_defaults=dict(variable_defaults),
        highlight_style=str(entry.get("highlight_style", "")),
        templates=templates,
        reference_docs=reference_docs,
        css=css,
        pdf=dict(pdf),
    )
