"""The pinned provenance-strip filter (§17 R-4) — plan step 27.

Design authority: `docs/design.md`
  §17 R-4 — **The provenance-strip filter (serialize-owned).** The html5/epub3 writers — and the
         whole HTML/EPUB/slide writer family — WOULD emit provenance attributes into published
         bytes (`data-*` kv, tier classes). A **pinned, deterministic pre-serialize filter strips
         the provenance Attr for every writer that publishes**, realized as a FAIL-CLOSED rule:
         strip UNLESS the writer is on the explicit `SAFE_WRITERS` allowlist. It is owned by
         SERIALIZE, is **not a Presentation lever**, and **cannot be disabled by any style
         configuration (PD3)** — it protects the grounding + no-secrets guarantee (§3.3).
  §17 RI8 — the Attr the emitter materialized: a grounded claim → a `Span` carrying the tier
         as a class and the provenance as `data-*` kv (`data-fact`, `data-source-instance`,
         `data-source-commit`, `data-traceability`). Those are exactly what this filter
         removes for the public writers.
  §17 RI14 — the layer-3 contract payload EXCLUDES "provenance/tier tags as publishable
         content" — so the same strip covers the epub3 external hand-off.

**The security property (why this is a module, not a config flag).** The decision *whether*
to strip is `should_strip(writer)` — a **pure function of the writer string ALONE**. It takes
no Presentation dict, no RenderInputs, no style/variable map: there is no parameter, anywhere
in this module's surface, that a client or a Presentation entry could set to skip the strip.
The dispatcher (`pipeline.dispatch`) calls `strip_provenance` UNCONDITIONALLY whenever
`should_strip(writer)` is true. This is the mechanical form of "serialize-owned, not a
Presentation lever" — the strip is keyed off the render target's writer, which is a
one-file-add registry value (§17 RI12), never a per-run style choice (PD3).

**Fail-closed by construction (§3.3).** `should_strip` STRIPS BY DEFAULT and exempts only the
explicit `SAFE_WRITERS` allowlist — the internal-record writers that intentionally BEAR
provenance (`markdown`, `json`) and the attr-dropping writers that CANNOT carry a `data-` kv
into published bytes (`docx`, `pptx`, `pdf`, `plain`). Every OTHER writer — the entire
HTML/EPUB/slide family (present or future), and any public writer a later one-file render-target
adds — strips by default. The rule therefore cannot be out-flanked by a writer we forgot to
enumerate: a new render target leaks nothing unless someone makes an explicit, reviewed edit to
the SAFE allowlist. (This inverts an earlier html5/epub3 ALLOWLIST, which fail-OPEN silently
published provenance for any un-listed public writer, e.g. `revealjs` or bare `epub`.)

**What is removed** (the provenance signature the emitter writes onto claim Spans, RI8):
  - every attribute-key beginning `data-` (the provenance kv: `data-fact`, `data-source-*`,
    `data-tier`, `data-traceability`, and any future `data-` provenance key) — INCLUDING the
    structural `data-part-id`, which is routing metadata, never published content;
  - every class that names a confidence tier (`EXTRACTED` / `INFERRED` / `AMBIGUOUS`, §6.5);
  - the node `id` **iff that node carried a TRUE provenance marker** — a `data-` kv OTHER than
    the structural `data-part-id`. So a fact-anchor id can never surface as a published
    `id="…"`, while a part Div's structural role-slug id (a public section anchor RI8 keeps) is
    left intact even though its `data-part-id` kv is stripped alongside the rest of the `data-` kv.
The `data-` kv strip is deliberately BROAD: nothing published needs a `data-` attribute, and a
broad rule cannot be out-flanked by a provenance key we forgot to enumerate (fail-closed, §3.3).
The `sequence` / `packaging-hint` kv are plain (non-`data-`) keys and survive; they carry no
provenance.

This module is a PURE transform: it imports only the tier vocabulary and the stdlib. It never
mutates its input — it returns a deep-copied AST, so the FULL provenance-bearing AST that
`pipeline.ast_store` persists for the internal record (md/docx) is never disturbed by a public
render (§17: provenance is retained in the internal record, stripped only for public bytes).
"""

from __future__ import annotations

import copy
from typing import Any

from pipeline.adapters.base import TIERS

__all__ = [
    "PROVENANCE_KV_PREFIX",
    "SAFE_WRITERS",
    "STRIP_FILTER_VERSION",
    "has_provenance",
    "should_strip",
    "strip_provenance",
]

#: §17 RI13: the strip filter is a pinned, byte-altering render input — its version joins the
#: render-binding (`pipeline.serialize.serialize_inputs_preimage`). Bump when a rule change
#: alters the PUBLISHED BYTES of any currently-producible writer (it re-mints serialize revisions
#: loudly, never silently — FR7.3). The fail-closed inversion below did NOT bump: it changes the
#: output of NO producible writer (html5/epub3 strip identically; every SAFE writer is unchanged),
#: so a bump would be spurious churn — re-minting every existing serialize binding for zero byte
#: difference. It only flips the DEFAULT for writers no current render-target produces.
STRIP_FILTER_VERSION = 1

#: The provenance kv prefix (RI8). Every provenance attribute the emitter writes is a `data-`
#: kv; stripping the whole prefix is fail-closed (an un-enumerated provenance key cannot leak).
PROVENANCE_KV_PREFIX = "data-"

#: The ONLY writers whose bytes are NOT stripped (§17 R-4) — a fail-closed allowlist; the strip
#: default is ON for everything else. Keyed on the WRITER, never the `side` setting. Two reasons
#: a writer is safe, both verified empirically against pandoc 3.10:
#:   - INTERNAL RECORD that intentionally BEARS provenance — `markdown` and `json` (the raw-AST
#:     passthrough) ARE the layer-3 internal record (§17 RI8); provenance is their whole point.
#:   - ATTR-DROPPING writer that CANNOT carry a `data-` kv into published bytes — `docx`/`pptx`
#:     (OOXML has no slot for HTML `data-` attributes; the emitted zip members carry none),
#:     `plain` (drops all formatting/attrs), `pdf` (a binary page format via LaTeX/…, no
#:     HTML-attribute concept). These retain provenance in the AST harmlessly — the writer eats it.
#: EVERY OTHER writer — the whole HTML/EPUB/slide family (html5/html/html4/revealjs/s5/slidy/
#: slideous/dzslides/chunkedhtml/epub/epub3), present or future — strips by DEFAULT, so a
#: one-file-add render-target on any un-enumerated public writer cannot silently publish
#: provenance: opt-out is an explicit, reviewed edit to this set (fail-closed, §3.3).
SAFE_WRITERS = frozenset({"markdown", "json", "docx", "pptx", "pdf", "plain"})

_TIER_CLASSES = frozenset(TIERS)

#: The ONE `data-` kv that is STRUCTURAL ROUTING, not provenance (§17 RI8): a part Div's full
#: part-id. It is still stripped from published bytes with the rest of the `data-` kv, but —
#: unlike a true provenance marker — it must NOT trigger blanking of the node's structural `#id`
#: (the role slug is a public section anchor RI8 keeps). Every OTHER `data-` key is provenance.
_STRUCTURAL_ROUTING_KV = frozenset({"data-part-id"})


def should_strip(writer: str) -> bool:
    """Whether provenance must be stripped before this writer runs (§17 R-4).

    FAIL-CLOSED: strips for EVERY writer except the explicit `SAFE_WRITERS` allowlist (the
    internal-record writers that bear provenance + the attr-dropping writers that cannot carry
    it into published bytes). A new public writer added via a one-file render-target therefore
    strips by DEFAULT — a forgotten writer can never silently publish provenance (§3.3).

    A PURE function of the writer string — the whole point (module docstring): no Presentation
    argument exists, so no style configuration can flip this decision. The dispatcher consults
    it and strips unconditionally when it is true.
    """
    return writer not in SAFE_WRITERS


def _is_provenance_kv(kv: Any) -> bool:
    """True iff `kv` is a TRUE provenance marker — a `data-` kv that is NOT the structural
    `data-part-id` routing key.

    This is the predicate that decides ID-BLANKING: a fact-anchor node (carrying `data-fact` &
    the source kv) blanks its id; a part Div (carrying only the structural `data-part-id`)
    keeps its role-slug id. The kv-STRIP is broader — it removes ALL `data-` kv, `data-part-id`
    included — but that removal must not, on `data-part-id`'s account, blank the structural id.
    """
    return (
        isinstance(kv, list)
        and len(kv) == 2
        and str(kv[0]).startswith(PROVENANCE_KV_PREFIX)
        and str(kv[0]) not in _STRUCTURAL_ROUTING_KV
    )


def _strip_attr(attr: list[Any]) -> tuple[list[Any], bool]:
    """Strip provenance from one Pandoc `Attr = [id, [classes], [[k, v], …]]`.

    Returns `(new_attr, changed)`. Removes every `data-` kv (the structural `data-part-id`
    included) and every tier class; blanks the id ONLY when the node carried a TRUE provenance
    marker — a `data-` kv OTHER than `data-part-id` (see `_is_provenance_kv`). So a fact-anchor
    id is blanked while a part Div's structural role-slug id survives even though its
    `data-part-id` kv is removed.
    """
    if not (isinstance(attr, list) and len(attr) == 3):
        return attr, False  # not an Attr shape — leave untouched (defensive)
    node_id, classes, kvs = attr
    kv_list = kvs if isinstance(kvs, list) else []
    carried_provenance = any(_is_provenance_kv(kv) for kv in kv_list)
    class_list = classes if isinstance(classes, list) else []
    new_classes = [c for c in class_list if c not in _TIER_CLASSES]
    new_kvs = [
        kv
        for kv in kv_list
        if not (
            isinstance(kv, list) and len(kv) == 2 and str(kv[0]).startswith(PROVENANCE_KV_PREFIX)
        )
    ]
    new_id = "" if carried_provenance else node_id
    changed = new_id != node_id or new_classes != classes or new_kvs != kvs
    return [new_id, new_classes, new_kvs], changed


def _walk_strip(node: Any) -> None:
    """Recursively strip provenance from every attributed node, IN PLACE on `node`.

    A Pandoc `Div`/`Span` is `{"t": "Div"|"Span", "c": [Attr, content]}`; other attributed
    nodes (`Header`, `CodeBlock`, `Code`, `Link`, `Image`, `Table`) carry an Attr in a known
    slot. Rather than enumerate every carrier, this walks generically: any list of exactly
    `[id, [..], [[k,v],..]]` shape reachable in the tree is normalized. That is conservative
    and fail-closed — it can only ever REMOVE provenance, never invent content.
    """
    if isinstance(node, dict):
        c = node.get("c")
        # Div/Span (and any node) whose content begins with an Attr: strip that Attr.
        if isinstance(c, list) and c and _is_attr(c[0]):
            new_attr, _ = _strip_attr(c[0])
            c[0] = new_attr
        for value in node.values():
            _walk_strip(value)
    elif isinstance(node, list):
        for item in node:
            _walk_strip(item)


def _is_attr(value: Any) -> bool:
    """A Pandoc `Attr`: `[str id, [str classes], [[str key, str value], …]]`."""
    return (
        isinstance(value, list)
        and len(value) == 3
        and isinstance(value[0], str)
        and isinstance(value[1], list)
        and isinstance(value[2], list)
        and all(isinstance(c, str) for c in value[1])
        and all(isinstance(kv, list) and len(kv) == 2 for kv in value[2])
    )


def strip_provenance(ast: dict[str, Any]) -> dict[str, Any]:
    """Return a DEEP COPY of `ast` with all provenance removed (§17 R-4).

    Pure, deterministic, and non-mutating: the caller's `ast` (the full provenance-bearing
    layer-3 record `pipeline.ast_store` persists) is untouched — the strip is a per-render
    transform for public writers only (§17: provenance retained in the internal record,
    stripped for published bytes). Removes every `data-` kv, every tier class, and any
    fact-anchor id, from every attributed node in the document.
    """
    stripped = copy.deepcopy(ast)
    _walk_strip(stripped.get("blocks", []))
    _walk_strip(stripped.get("meta", {}))
    return stripped


def has_provenance(ast: dict[str, Any]) -> bool:
    """True iff any attributed node still carries a provenance marker (test/assert helper).

    A provenance marker is a `data-` kv OR a tier class. Used by the strip tests to PROVE the
    removal — `has_provenance(full) is True` and `has_provenance(strip_provenance(full)) is
    False` for a public writer.
    """
    found = False

    def _scan(node: Any) -> None:
        nonlocal found
        if found:
            return
        if isinstance(node, dict):
            c = node.get("c")
            if isinstance(c, list) and c and _is_attr(c[0]):
                _, classes, kvs = c[0]
                if any(cls in _TIER_CLASSES for cls in classes) or any(
                    str(kv[0]).startswith(PROVENANCE_KV_PREFIX) for kv in kvs
                ):
                    found = True
                    return
            for value in node.values():
                _scan(value)
        elif isinstance(node, list):
            for item in node:
                _scan(item)

    _scan(ast.get("blocks", []))
    _scan(ast.get("meta", {}))
    return found
