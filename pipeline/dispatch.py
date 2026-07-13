"""The serialize dispatcher (§17 RI12): route a layer-3 AST by its render-target — plan step 27.

Design authority: `docs/design.md`
  §17 RI12 — **The dispatcher.** The render-target registry entries declare `writer` (or
        `json` for raw-AST passthrough), **`side: internal | external`**, `engine?`,
        `reference_doc?`, and pins. Dispatch = look up target → produce AST → internal: call
        Pandoc in-system; external: persist AST + emit the contract payload. A
        capability-infeasible platform × output-type pairing is a dispatcher feasibility check
        (`capability-infeasible` warn/block, §21.7) — never a reconcile reshape.
  §17 R-4 — the provenance-strip filter runs pre-serialize for html5/epub3. It is applied HERE,
        keyed on the writer, on a COPY of the AST — the persisted layer-3 record keeps its full
        provenance for the internal record (md/docx); only the published bytes are stripped.
  §14.2 — internal = call the pinned Pandoc writer in-system (layer-2 bytes); external = persist
        the AST + emit the layer-3 contract payload (RI14) for an external actor. In v1 the
        external side is DISPATCHED/DEFERRED here (pptx/epub/pdf), not rendered (gate step 3).
  §17 PD3/PD4 — the dispatcher consumes `lower(presentation, writer, output-type) →
        RenderInputs{flags, variables, assets+hashes, engine}` as one flat struct. Step 27
        ships the minimal `plain`-presentation lowering; full PD3 lowering is step 29.

**Security note (the strip is not a Presentation lever).** Whether to strip is
`provenance_strip.should_strip(writer)` — a pure function of the WRITER. `RenderInputs`
(the Presentation lowering) has no field that reaches it; `dispatch` applies the strip
UNCONDITIONALLY when `should_strip` is true, before the writer runs. A client/Presentation
config therefore cannot disable it (§17, PD3).

No SSOT import (INV-CORRECTNESS, §22.7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pipeline.canonical import canonical_json_bytes
from pipeline.filters.provenance_strip import should_strip, strip_provenance
from pipeline.serialize import (
    PANDOC_BINARY_DEFAULT,
    PandocUnavailableError,
    SerializeError,
    run_pandoc_bytes,
)

__all__ = [
    "EXTERNAL_DEFERRED",
    "INTERNAL_WRITERS",
    "PASSTHROUGH_WRITER",
    "CapabilityInfeasibleError",
    "DispatchOutcome",
    "RenderInputs",
    "RenderTarget",
    "capability_check",
    "dispatch",
    "lower_plain",
    "render_target_from_entry",
]

#: The pinned in-system writer set (gate step 3: md→markdown, html→html5, docx→docx, plus the
#: plain-text→plain writer — all ship in the pinned binary). `json` is raw-AST passthrough.
INTERNAL_WRITERS = frozenset({"markdown", "html5", "docx", "plain"})

#: `json` = the raw-AST passthrough writer (RI12): layer 3 IS the output, no in-system render.
PASSTHROUGH_WRITER = "json"

#: v1 external targets (epub3/pptx/pdf) are dispatched but DEFERRED here — the AST (stripped for
#: public writers) is persisted + handed off; the external actor renders layer-4 (gate step 3).
EXTERNAL_DEFERRED = "deferred-external"


class CapabilityInfeasibleError(SerializeError):
    """A target cannot express what the deliverable needs (§21.7) — block, never reshape."""

    code = "capability-infeasible"


# ---------------------------------------------------------------------------
# The render-target view (§17 RI12) + the lowered Presentation RenderInputs (PD3).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RenderTarget:
    """One render-target's dispatch-relevant effective values (RI12). Built from a registry
    entry's resolved frontmatter; `side` routes, `writer`/`engine`/`reference_doc` render."""

    writer: str
    side: Literal["internal", "external"]
    engine: str = ""
    reference_doc: str = ""


@dataclass(frozen=True)
class RenderInputs:
    """The lowered Presentation struct (PD3): one flat set of writer inputs. `plain` lowers to
    the empty struct — no flags, variables, or assets. Full PD3 lowering is step 29."""

    flags: tuple[str, ...] = ()
    variables: dict[str, Any] = field(default_factory=dict)
    assets: tuple[tuple[str, str], ...] = ()  # (path, content-hash)
    engine: str = ""


def render_target_from_entry(entry: dict[str, Any]) -> RenderTarget:
    """Build a `RenderTarget` from a resolved render-target registry entry's values (RI12)."""
    side = entry.get("side", "external")
    if side not in ("internal", "external"):
        raise CapabilityInfeasibleError(
            f"capability-infeasible: render-target `side` must be internal|external, got {side!r}"
        )
    return RenderTarget(
        writer=str(entry.get("writer", PASSTHROUGH_WRITER)),
        side=side,
        engine=str(entry.get("engine", "")),
        reference_doc=str(entry.get("reference_doc", "")),
    )


def lower_plain(target: RenderTarget) -> RenderInputs:
    """The minimal `plain`-presentation lowering (PD3): no flags/variables/assets; the target's
    engine carried through. Full `lower(presentation, writer, output-type)` is step 29."""
    return RenderInputs(engine=target.engine)


def capability_check(target: RenderTarget) -> None:
    """Feasibility check (§21.7): an INTERNAL target must name a writer the pinned binary can run
    in-system (`INTERNAL_WRITERS` or the `json` passthrough). An internal target naming an
    unknown/external-only writer is `capability-infeasible` — a block, never a reconcile reshape.
    External targets impose no in-system-writer constraint (an external actor renders them)."""
    if (
        target.side == "internal"
        and target.writer not in INTERNAL_WRITERS
        and target.writer != PASSTHROUGH_WRITER
    ):
        raise CapabilityInfeasibleError(
            f"capability-infeasible: writer {target.writer!r} is not an in-system internal writer "
            f"({sorted(INTERNAL_WRITERS)} or {PASSTHROUGH_WRITER!r}); flip `side` to external or "
            "pick a supported writer (§17 RI12)"
        )


# ---------------------------------------------------------------------------
# Dispatch (RI12): internal → in-system writer; external → deferred hand-off.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispatchOutcome:
    """One dispatch result. `code` ∈ {`ok` (internal bytes produced), `deferred-external`
    (AST persisted + handed off, rendered elsewhere)}. `output_bytes` holds layer-2 bytes for
    an internal render (None external); `payload_ast` holds the hand-off AST for an external
    target (None internal) — stripped for a public writer. `stripped` records whether the
    provenance-strip filter ran for this render (§17 R-4)."""

    side: str
    writer: str
    code: str
    stripped: bool
    output_bytes: bytes | None = None
    payload_ast: dict[str, Any] | None = None


def dispatch(
    target: RenderTarget,
    ast: dict[str, Any],
    *,
    render_inputs: RenderInputs | None = None,
    binary: str = PANDOC_BINARY_DEFAULT,
) -> DispatchOutcome:
    """Route one layer-3 `ast` by `target` (RI12).

    Applies the provenance-strip filter (on a COPY) whenever `should_strip(target.writer)` — a
    decision made purely on the writer, unreachable from `render_inputs` (the security property,
    §17 R-4). Then: `side: internal` → `pandoc -f json -t <writer>` produces layer-2 bytes;
    `side: external` → the (possibly stripped) AST is returned for persistence + hand-off,
    deferred in v1 (gate step 3). `render_inputs` is the lowered Presentation struct (plain in
    step 27); its flags are appended to the writer invocation.
    """
    capability_check(target)
    inputs = render_inputs if render_inputs is not None else RenderInputs()
    strip = should_strip(target.writer)
    render_ast = strip_provenance(ast) if strip else ast

    if target.side == "external":
        return DispatchOutcome(
            side="external",
            writer=target.writer,
            code=EXTERNAL_DEFERRED,
            stripped=strip,
            payload_ast=render_ast,
        )

    if target.writer == PASSTHROUGH_WRITER:  # raw-AST passthrough as internal bytes (RI12)
        return DispatchOutcome(
            side="internal",
            writer=target.writer,
            code="ok",
            stripped=strip,
            output_bytes=canonical_json_bytes(render_ast),
        )

    args = ("-f", "json", "-t", target.writer, *inputs.flags)
    try:
        outcome = run_pandoc_bytes(args, canonical_json_bytes(render_ast), binary=binary)
    except PandocUnavailableError:
        raise  # loud, never a silent skip (§17 PA-12)
    if outcome.returncode != 0:
        raise SerializeError(
            f"serialize-error: internal writer {target.writer!r} exited {outcome.returncode} — "
            f"{outcome.stderr.strip()!r}"
        )
    return DispatchOutcome(
        side="internal",
        writer=target.writer,
        code="ok",
        stripped=strip,
        output_bytes=outcome.stdout,
    )
