"""The layer-3 contract payload (§17 RI14) — the external hand-off for a `side: external` target.

Design authority: `docs/design.md`
  §17 RI14 — the layer-3 contract payload (carried by `emit-manifest` for `side: external`,
        §21.5) has EXACTLY five components:
          (1) the **Pandoc AST JSON** (embedding its api-version);
          (2) a **reproducibility sidecar** — `deliverable-id`/`artifact-id`/`fitted-id`,
              requested output-types, required Pandoc version + writer + engine + reference-doc,
              all pins (the RI13 pin bundle);
          (3) the **part structure** — ordered `part-id`, `role`, advisory intra-work
              **`sequence`**, packaging hint — so the actor knows how many files to emit and can
              address part 3/7 directly;
          (4) the opaque **`metadata` bag**, untouched;
          (5) the **`language`** (already localized — the actor never re-localizes).
        **Explicitly excluded: provenance/tier tags as publishable content; any secret.**
  §17 R-4 — the provenance-strip filter removes the provenance Attr (`data-*` kv, tier classes,
        fact-anchor ids). RI14 excludes provenance UNCONDITIONALLY, so this builder strips the
        payload AST regardless of writer (`pipeline.filters.provenance_strip.strip_provenance`,
        which is fail-closed) and re-verifies zero provenance remains — the external actor
        receives ZERO provenance. This is the same no-provenance-in-external-output guarantee as
        the step-27 dispatch byte path, applied to the FULL payload.
  §7.4 — **conditional extension-append naming.** A byte-output filename is the id plus a
        conventional format extension, appended ONLY when the result still fits the 255-byte
        filename bound (`pipeline.ids.output_filename`); the id is authoritative and the
        extension-free name is always valid. The payload names the deliverable file and each
        addressable part file this way so the external actor emits correctly-named outputs.

**Why the part structure carries an EXPLICIT `sequence` (unlike the internal path).** Internally
the ordered `parts` list IS the order — position is implicit and never serialized. The external
actor reassembles from a hand-off it did not build, so it needs the order stated explicitly: each
part's advisory intra-work `sequence` (§15/§9.5) is its 1-based ordinal position in the fitted
IR's immutable ordered parts list, written into the payload as a literal integer.

**The security property (why provenance/secrets cannot leak).** (a) The AST is run through the
fail-closed `strip_provenance` UNCONDITIONALLY and re-checked with `has_provenance` — no `data-*`
kv, no tier class, no fact-anchor id survives. (b) The grounding ledger is NOT a payload component
— it never leaves the IR/AST layers (§17: provenance consumed at IR/AST only). (c) The `metadata`
bag was secret-scanned at IR build (`pipeline.ir`, §3.3) and rides through opaque and untouched.

**No SSOT import (INV-CORRECTNESS, §22.7):** the payload is a pure projection of already-resolved,
content-addressed inputs; it reads no SSOT.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from pipeline import ids
from pipeline.dispatch import RenderTarget
from pipeline.filters.provenance_strip import has_provenance, strip_provenance
from pipeline.ids import IdError

__all__ = [
    "PayloadError",
    "build_payload",
    "part_structure",
]


class PayloadError(RuntimeError):
    """A layer-3 payload contract breach — a non-external target, an unparseable deliverable-id,
    or (the fail-closed guard) provenance surviving the strip. Loud and typed (§3.1)."""

    code = "payload-error"


# ---------------------------------------------------------------------------
# Id projection: the deliverable-id names its own fitted-id, artifact-id, and language coordinate.
# ---------------------------------------------------------------------------


def _project(deliverable_id: str) -> tuple[str, str, str]:
    """`(artifact_id, fitted_id, language)` for a deliverable-id (§7.4 projection: the fitted-id is
    the deliverable-id minus output-type/presentation; the artifact-id is the bare root)."""
    try:
        parsed = ids.parse_id(deliverable_id)
    except IdError as exc:
        raise PayloadError(
            f"payload-error: {deliverable_id!r} is not a valid id ({exc})"
        ) from exc
    if parsed.family != "artifact" or parsed.level != "deliverable" or parsed.part is not None:
        raise PayloadError(
            f"payload-error: the payload names a DELIVERABLE-level id (§7.1), got level "
            f"{parsed.level!r} in {deliverable_id!r}"
        )
    artifact_id = ids.PipelineId(family="artifact", root_hex=parsed.root_hex).render()
    fitted_id = replace(
        parsed, output_type=None, presentation=None, serialize_revision=None, part=None
    ).render()
    return artifact_id, fitted_id, parsed.language


# ---------------------------------------------------------------------------
# The part structure (component 3): ordered part-id · role · EXPLICIT sequence · packaging hint.
# ---------------------------------------------------------------------------


def part_structure(fitted_ir: Mapping[str, Any], *, extension: str) -> list[dict[str, Any]]:
    """The RI14 part structure over the fitted IR's ORDERED parts (§17 RI14 component 3).

    Each entry carries the part-id, role, the EXPLICIT `sequence` (its 1-based ordinal in the
    immutable parts list — stated literally so the external actor can reassemble, §9.5), the
    packaging hint, and the §7.4 conditional-extension filename for that addressable part. A flat
    (single-body) fitted IR has no parts → an empty list (one file, named at the deliverable)."""
    if "parts" not in fitted_ir:
        return []
    structure: list[dict[str, Any]] = []
    for ordinal, part in enumerate(fitted_ir["parts"], start=1):
        part_id = str(part["part-id"])
        structure.append(
            {
                "part_id": part_id,
                "role": part.get("role"),
                "sequence": ordinal,  # EXPLICIT — the external order is stated, never implicit
                "packaging_hint": part.get("packaging_hint"),
                "filename": ids.output_filename(part_id, extension),
            }
        )
    return structure


# ---------------------------------------------------------------------------
# The five-component RI14 payload.
# ---------------------------------------------------------------------------


def build_payload(
    *,
    ast: dict[str, Any],
    deliverable_id: str,
    render_target: RenderTarget,
    pin_bundle: Mapping[str, Any],
    fitted_ir: Mapping[str, Any],
    requested_output_types: Sequence[str],
    extension: str,
) -> dict[str, Any]:
    """Assemble the five-component RI14 layer-3 contract payload for a `side: external` target.

    `ast` is the persisted layer-3 AST; `render_target` supplies writer/engine/reference-doc/side;
    `pin_bundle` is the RI13 manifest (`serialize.pin_bundle`); `fitted_ir` supplies the part
    structure + the opaque `metadata` bag; `requested_output_types` are the actor's targets;
    `extension` is the conventional format extension for §7.4 filename naming.

    SECURITY (RI14): the AST is stripped of ALL provenance UNCONDITIONALLY (`strip_provenance`,
    fail-closed) and re-verified with `has_provenance` — provenance/tier tags and any fact-anchor
    id are EXCLUDED; the grounding ledger is not a component; the `metadata` bag rides through
    opaque (secret-scanned upstream at IR build). Raises `PayloadError` on a non-external target,
    a non-deliverable id, or (the fail-closed guard) surviving provenance."""
    if not isinstance(render_target, RenderTarget):
        raise PayloadError(
            f"payload-error: render_target must be a dispatch.RenderTarget, got "
            f"{type(render_target).__name__}"
        )
    if render_target.side != "external":
        raise PayloadError(
            "payload-error: the layer-3 contract payload is emitted for `side: external` targets "
            f"only (§17 RI14/§21.5), got side {render_target.side!r}"
        )
    if isinstance(requested_output_types, str | bytes):
        raise PayloadError(
            "payload-error: requested_output_types must be a sequence of output-type slugs, "
            "not a single string"
        )

    artifact_id, fitted_id, language = _project(deliverable_id)

    # Component 1: the Pandoc AST JSON (api-version embedded), stripped of ALL provenance. The
    # strip is fail-closed and UNCONDITIONAL here — RI14 excludes provenance regardless of writer.
    payload_ast = strip_provenance(ast)
    if has_provenance(payload_ast):  # the fail-closed guard — must never trigger (§3.3)
        raise PayloadError(
            "payload-error: provenance survived the strip — the external payload must carry ZERO "
            "provenance (§17 RI14); refusing to hand off a leaking AST"
        )

    return {
        # (1) the AST JSON, embedding its api-version.
        "ast": payload_ast,
        # (2) the reproducibility sidecar — ids, requested output-types, tool requirements, pins.
        "reproducibility": {
            "deliverable_id": deliverable_id,
            "artifact_id": artifact_id,
            "fitted_id": fitted_id,
            "requested_output_types": list(requested_output_types),
            "pandoc_version": pin_bundle.get("pandoc_version"),
            "writer": render_target.writer,
            "engine": render_target.engine or pin_bundle.get("engine", ""),
            "reference_doc": render_target.reference_doc or pin_bundle.get("reference_doc", ""),
            "pins": dict(pin_bundle),
            "filename": ids.output_filename(deliverable_id, extension),
        },
        # (3) the part structure with EXPLICIT sequence.
        "parts": part_structure(fitted_ir, extension=extension),
        # (4) the opaque metadata bag, untouched (secret-scanned upstream at IR build).
        "metadata": dict(fitted_ir.get("metadata", {})),
        # (5) the language (already localized — the actor never re-localizes).
        "language": language,
    }
