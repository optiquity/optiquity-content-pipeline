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

**Review 2 wiring (§19, PA-10).** `review_deliverable` runs the ADVISORY deliverable review
POST-bytes, on EVERY deliverable (including every fit/serialize revision). It is a thin wrapper
over `pipeline.review` (itself SSOT-free): produce an immutable id-addressed record, then
advance the deliverable SSOT row to `deliverable-reviewed` through the SAME write-only hook the
caller supplies. It NEVER mutates the deliverable bytes/AST/records; it only advances STATUS.
`dispatch()` itself is unchanged (pure routing) — the review is a sibling wiring function.

No SSOT import (INV-CORRECTNESS, §22.7): this module advances the SSOT only via the write-only
`review_advance` hook a caller supplies, and imports no SSOT module.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from pipeline import asset_ref, review
from pipeline.canonical import canonical_json_bytes
from pipeline.filters.citeproc_enablement import has_citations
from pipeline.filters.provenance_strip import should_strip, strip_provenance
from pipeline.filters.section_attr_validity import strip_section_attrs
from pipeline.review import ReviewOutcome
from pipeline.serialize import (
    PANDOC_BINARY_DEFAULT,
    PandocUnavailableError,
    SerializeError,
    rsvg_available,
    run_pandoc_bytes,
)
from pipeline.store import WorkspaceStore
from pipeline.transport import Runner

__all__ = [
    "EMBED_WRITERS",
    "EXTERNAL_DEFERRED",
    "INTERNAL_WRITERS",
    "PASSTHROUGH_WRITER",
    "CapabilityInfeasibleError",
    "DispatchOutcome",
    "RenderInputs",
    "RenderTarget",
    "capability_check",
    "dispatch",
    "embeddable_image_targets",
    "lower_plain",
    "render_target_from_entry",
    "review_deliverable",
]

#: The pinned in-system writer set (gate step 3: md→markdown, html→html5, docx→docx, plus the
#: plain-text→plain writer — all ship in the pinned binary). `json` is raw-AST passthrough.
INTERNAL_WRITERS = frozenset({"markdown", "html5", "docx", "plain"})

#: `json` = the raw-AST passthrough writer (RI12): layer 3 IS the output, no in-system render.
PASSTHROUGH_WRITER = "json"

#: v1 external targets (epub3/pptx/pdf) are dispatched but DEFERRED here — the AST (stripped for
#: public writers) is persisted + handed off; the external actor renders layer-4 (gate step 3).
EXTERNAL_DEFERRED = "deferred-external"

#: The internal writers that ACTIVELY embed a body figure — the ONLY writers that emit a pandoc
#: `--resource-path` and open+copy the referenced file (increment B). html5 inlines the image as a
#: data URI (`--embed-resources`); docx carries it as a native `word/media/` part (native embed via
#: `--resource-path` alone). `markdown` keeps the figure BY REFERENCE (`![](assets/…)` passthrough —
#: no embed, no file opened) and `plain` shows only the caption; neither is here, so neither ever
#: emits a resource-path or triggers the render-time embed gate
#: (`asset_loader.hash_embedded_assets`).
EMBED_WRITERS = frozenset({"html5", "docx"})


def embeddable_image_targets(ast: dict[str, Any], writer: str) -> tuple[str, ...]:
    """The SORTED, DEDUPED `assets/…` body-image targets an EMBED writer will inline (F7 dedup).

    Empty for a NON-embed writer (`markdown`/`plain`/`json`/external) — those open no file, so they
    never fold a body figure into identity. For an embed writer it is the `assets/`-prefixed subset
    of `asset_ref.iter_image_targets(ast)` (which may repeat a target), sorted+deduped so the
    serialize preimage shape is order-stable regardless of body order. Pure — no filesystem read;
    the read (and A's full containment re-gate) lives in `asset_loader.hash_embedded_assets`."""
    if writer not in EMBED_WRITERS:
        return ()
    prefix = f"{asset_ref.ASSETS_DIRNAME}/"
    return tuple(sorted({t for t in asset_ref.iter_image_targets(ast) if t.startswith(prefix)}))


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
    the empty struct — no flags, variables, assets, or csl. Full PD3 lowering is step 29.

    `csl` (DR-5 C7) is the α LABELED citation-style field — `(path, content-hash)` or None. It is
    NOT an unlabeled `assets` member and carries NO `--csl` in `flags`: dispatch content-gates
    `--csl` WITH `--citeproc` (never a standalone style toggle, since pandoc ignores a `--csl`
    without `--citeproc`), and its content hash enters the serialize preimage ONLY when citeproc
    ran. A cycle-safe `(path, content-hash)` tuple — NOT a `PresentationAsset` — because dispatch
    must not import `pipeline.presentation` (presentation → dispatch already, an import cycle)."""

    flags: tuple[str, ...] = ()
    variables: dict[str, Any] = field(default_factory=dict)
    assets: tuple[tuple[str, str], ...] = ()  # (path, content-hash)
    engine: str = ""
    csl: tuple[str, str] | None = None  # (path, content-hash); labeled, NOT an `assets` member


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
    provenance-strip filter ran for this render (§17 R-4); `section_attr_transformed` records
    whether the SD-5 section-attr validity strip actually removed a bare `type=`/`role=` heading
    kv on this render (True only on a public writer over a typed heading — the signal that keys
    the serialize preimage's transform-version record, §17 FR7.1). `citeproc_enabled` records
    whether the AST carried a citation (`Cite` node) so `--citeproc` was appended (C6, the
    CONTENT-driven twin of `section_attr_transformed`: True for ANY writer over a citing AST — the
    signal that keys the preimage's `citeproc_enablement_version` record, §17 R-4 family).
    `assets_embedded` (increment B) records whether this render actually EMBEDDED ≥1 body figure —
    True only for an html5/docx writer handed a non-empty `resource_paths` (an `assets/…` figure was
    inlined). It is the dispatch-level twin of the driver/render legs' `bool(embedded_assets)` and
    keys the serialize preimage's OMIT-WHEN-ABSENT `asset_embed_version`; False for md/plain, an
    image-less html/docx, the json passthrough, and every external target."""

    side: str
    writer: str
    code: str
    stripped: bool
    section_attr_transformed: bool
    citeproc_enabled: bool
    output_bytes: bytes | None = None
    payload_ast: dict[str, Any] | None = None
    assets_embedded: bool = False


def dispatch(
    target: RenderTarget,
    ast: dict[str, Any],
    *,
    render_inputs: RenderInputs | None = None,
    resource_paths: tuple[str, ...] = (),
    binary: str = PANDOC_BINARY_DEFAULT,
) -> DispatchOutcome:
    """Route one layer-3 `ast` by `target` (RI12).

    Applies the provenance-strip filter (on a COPY) whenever `should_strip(target.writer)` — a
    decision made purely on the writer, unreachable from `render_inputs` (the security property,
    §17 R-4) — then, on the SAME public-writer path, the SD-5 section-attr validity strip
    (`strip_section_attrs`) removes the bare `type=`/`role=` heading kv so the published bytes are
    valid HTML5. The safe (internal-record) writers run neither strip → they KEEP both provenance
    and the structural typing (the round-trippable internal record). Then: `side: internal` →
    `pandoc -f json -t <writer>` produces layer-2 bytes; `side: external` → the (possibly stripped)
    AST is returned for persistence + hand-off, deferred in v1 (gate step 3). `render_inputs` is
    the lowered Presentation struct (plain in step 27); its flags are appended to the invocation.

    C6 (§17 R-4 family): citeproc enablement is CONTENT-driven — `--citeproc` is appended to the
    internal-writer invocation whenever the AST carries a citation (`has_citations`), regardless of
    the writer or any `csl` lever, so a `[@key]`-bearing body resolves against `meta.references`
    under the writer's default author-date CSL (fixing the broken `plain` default). `--citeproc` is
    a dispatch-appended ARG, never a `RenderInputs.flags` member (a pinned behavior, not a
    presentation input → no double-count in the serialize preimage). The strip never touches `Cite`
    nodes, so post-strip == pre-strip — `has_citations(render_ast)` equals reading `ast`.

    C7 (§17 R-4 family): the `csl` Presentation STYLE override rides ON TOP of C6 — when
    `--citeproc` is appended AND `render_inputs.csl` is set, dispatch ALSO appends `--csl=<path>`
    (the labeled `csl[0]`), so the citation resolves under the venue's style instead of the default
    author-date. `--csl` is content-gated WITH `--citeproc` and NEVER emitted alone (a standalone
    `--csl` pandoc ignores, C0 leg e) — so a citation-LESS render under a csl-set presentation emits
    neither flag → byte-identical to `plain`. Like `--citeproc`, `--csl` is a dispatch-appended ARG,
    never a `flags`/`assets` member; the csl content hash enters the serialize preimage only when
    citeproc ran (`serialize_inputs_preimage(..., citeproc_enabled=True, csl=...)`, the S3×S4 gate).

    B (body-figure EMBED): a non-empty `resource_paths` (the caller passes it ONLY for an html5/docx
    render over a gated, contained `assets/…` figure — F5 base order `(store.root, repo_root)`,
    store-root FIRST) appends `--resource-path=<store>:<repo>` so pandoc opens the figure at the
    client's store root (a same-named framework asset can never shadow it), plus — for html5 only —
    `--embed-resources --standalone` so the figure inlines as a data URI in a standalone document
    (docx embeds natively as a `word/media/` part via `--resource-path` alone). Like `--citeproc`,
    these are dispatch-appended ARGS, never `RenderInputs.flags` members. The caller runs A's FULL
    compose gate (`asset_loader.hash_embedded_assets`) BEFORE handing a non-empty `resource_paths`,
    so a body about to be embedded is provably contained — an uncontained/raw-markup body refuses at
    the caller and never reaches here. An empty `resource_paths` (md/plain, image-less html/docx)
    appends nothing → byte-identical to pre-B.
    """
    capability_check(target)
    inputs = render_inputs if render_inputs is not None else RenderInputs()
    strip = should_strip(target.writer)
    if strip:
        render_ast = strip_provenance(ast)
        render_ast, section_attr_transformed = strip_section_attrs(render_ast)
    else:  # safe (internal-record) writer: keep provenance AND the structural section typing
        render_ast = ast
        section_attr_transformed = False

    # C6: CONTENT-driven citeproc enablement (§17 R-4 family) — the twin of the section-attr flag,
    # UNGATED by the writer. The strip leaves `Cite` nodes intact, so reading `render_ast` matches
    # reading `ast`. False for every non-citing render → no `--citeproc` appended → byte-identical.
    citeproc_enabled = has_citations(render_ast)

    if target.side == "external":
        return DispatchOutcome(
            side="external",
            writer=target.writer,
            code=EXTERNAL_DEFERRED,
            stripped=strip,
            section_attr_transformed=section_attr_transformed,
            citeproc_enabled=citeproc_enabled,
            payload_ast=render_ast,
        )

    if target.writer == PASSTHROUGH_WRITER:  # raw-AST passthrough as internal bytes (RI12)
        return DispatchOutcome(
            side="internal",
            writer=target.writer,
            code="ok",
            stripped=strip,
            section_attr_transformed=section_attr_transformed,
            citeproc_enabled=citeproc_enabled,
            output_bytes=canonical_json_bytes(render_ast),
        )

    args = ("-f", "json", "-t", target.writer, *inputs.flags)
    if citeproc_enabled:  # C6: content-driven — the resolution ARG rides here, not in inputs.flags
        args = (*args, "--citeproc")
        if inputs.csl is not None:  # C7: the STYLE override rides WITH --citeproc, never alone
            args = (*args, f"--csl={inputs.csl[0]}")
    # B (body-figure EMBED): the caller passes a non-empty `resource_paths` ONLY for an EMBED writer
    # over a gated `assets/…` figure (F5 order: store-root FIRST, repo-root SECOND). Append a single
    # os.pathsep-joined `--resource-path` (pandoc searches it in order → the client figure wins over
    # a same-named framework asset) and, for html5 ONLY, `--embed-resources --standalone` (data-URI
    # inline in a standalone document; docx embeds natively via `--resource-path` alone).
    assets_embedded = bool(resource_paths) and target.writer in EMBED_WRITERS
    if assets_embedded:
        args = (*args, f"--resource-path={os.pathsep.join(resource_paths)}")
        if target.writer == "html5":
            args = (*args, "--embed-resources", "--standalone")
    # C0 (increment C, BLOCKER-3): the docx SVG-embed CAPABILITY PRECHECK (the PA-12 mirror). pandoc
    # rasterizes an embedded SVG into a docx PNG fallback by shelling out to `rsvg-convert`; when it
    # is ABSENT pandoc STILL exits 0 and ships a docx carrying the raw SVG media part but NO PNG
    # (blank/broken in Word), warning only on the stderr the returncode check below never reads. So
    # when a docx render embeds an `.svg` and `rsvg-convert` is missing, REFUSE loudly up front —
    # never a silently-degraded document. Scoped to a docx writer over an `.svg` target: the `and`
    # short-circuits so a raster-only docx (png/jpg) never even probes rsvg → byte-identical; html5
    # (SVG data-URI, no rsvg) and markdown (SVG by-path, no embed) are untouched.
    if (
        target.writer == "docx"
        and any(t.endswith(".svg") for t in embeddable_image_targets(render_ast, target.writer))
        and not rsvg_available()
    ):
        raise CapabilityInfeasibleError(
            "capability-infeasible: a docx diagram embed requires rsvg-convert on the render host; "
            "install it or route the SVG to html5/markdown"
        )
    try:
        outcome = run_pandoc_bytes(args, canonical_json_bytes(render_ast), binary=binary)
    except PandocUnavailableError:
        raise  # loud, never a silent skip (§17 PA-12)
    if outcome.returncode != 0:
        raise SerializeError(
            f"serialize-error: internal writer {target.writer!r} exited {outcome.returncode} — "
            f"{outcome.stderr.strip()!r}"
        )
    # C0 backstop (increment C, BLOCKER-3): the precheck cannot see a PRESENT-but-FAILING rsvg. A
    # docx render whose conversion failed exits 0 yet warns `Could not convert image` on stderr and
    # ships a PNG-less docx. Read the stderr the exit code hides and fail loudly (never blank docx).
    if target.writer == "docx" and "Could not convert image" in outcome.stderr:
        raise SerializeError(
            "serialize-error: docx render could not convert an embedded image (rsvg-convert failed "
            f"or the SVG is unconvertible) — {outcome.stderr.strip()!r}"
        )
    return DispatchOutcome(
        side="internal",
        writer=target.writer,
        code="ok",
        stripped=strip,
        section_attr_transformed=section_attr_transformed,
        citeproc_enabled=citeproc_enabled,
        output_bytes=outcome.stdout,
        assets_embedded=assets_embedded,
    )


# ---------------------------------------------------------------------------
# Review 2 wiring (§19, PA-10): the deliverable review runs POST-bytes, on EVERY deliverable.
# ---------------------------------------------------------------------------


def review_deliverable(
    *,
    store: WorkspaceStore,
    deliverable_id: str,
    fitted_ir: Mapping[str, Any],
    ast: Mapping[str, Any],
    hard_limits: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    review_runner: Runner | None = None,
    review_advance: Callable[[str], None] | None = None,
    review_model: str | None = None,
    review_timeout_seconds: float | None = None,
) -> ReviewOutcome:
    """Run the §19 deliverable review (Review 2) for one deliverable, then advance the
    deliverable SSOT row to `deliverable-reviewed` via the write-only `review_advance` hook.

    Runs the FULL review on EVERY deliverable INCLUDING every fit/serialize revision (FR5,
    FR7.5): the review is keyed by `deliverable_id`, so a revision (a distinct id) always gets
    its OWN record — a record NEVER transfers across revisions (§19). Reads the fitted IR + the
    AST (§17: provenance lives at the IR/AST layer, never in the output bytes) + the effective
    `hard_limits`. It is ADVISORY (never blocks) and NEVER mutates the deliverable's
    bytes/AST/records — it only produces an immutable id-addressed record and advances STATUS.
    The advance runs only when a record now exists (`persisted`). `review_runner` is the review
    transport seam (injectable for tests; None = real transport)."""
    outcome = review.review_deliverable(
        store=store,
        deliverable_id=deliverable_id,
        fitted_ir=fitted_ir,
        ast=ast,
        hard_limits=hard_limits,
        context=context,
        runner=review_runner,
        model=review_model,
        timeout_seconds=review_timeout_seconds,
    )
    if outcome.persisted and review_advance is not None:
        review_advance(deliverable_id)  # SSOT advance is write-only w.r.t. control flow
    return outcome
