"""The content-driven citeproc-enablement signal (§17 R-4 family) — DR-5 build, COMMIT C6.

Design authority: `docs/design.md`
  §17 R-4 — the serialize-owned, public-writer AST-filter family. This is the CONTENT-driven
         SIBLING of the SD-5 section-attr strip (`section_attr_validity`): a pinned, deterministic
         serialize-filter whose version joins the serialize preimage ONLY when it actually fires.
         Where SD-5 STRIPS bytes on public writers, C6 ENABLES pandoc's `--citeproc` citation
         resolution — but keyed on the CONTENT (the AST carries a `Cite` node), never on the writer.
  DR-5 C3–C5 — the writer emits `[@key]` only, compose resolves `[@key]`->`references`, and C5
         threads `references` into `ast.meta` (D2 frontmatter). C5 left the body's `Cite` nodes
         UNRESOLVED (RI7 is `--citeproc`-free). C6 closes the loop: whenever the AST carries a
         `Cite`, dispatch appends `--citeproc`, so the citation resolves against `meta.references`
         under the writer's default author-date CSL (fixing the broken `plain` default) and a real
         resolved bibliography `Div` is emitted.

**Content-driven, NOT a Presentation lever, NOT `csl`-gated.** `--citeproc` fires purely on the AST
carrying a `Cite` node — a pure function of CONTENT, unreachable from `RenderInputs` (the
Presentation lowering). This is UNLIKE the SD-5 flag (writer-gated by `should_strip`). A `csl` style
is a C7 Presentation lever that OVERRIDES the default style only when citeproc is already enabled;
it never toggles enablement.

**Identity: an OMIT-WHEN-ABSENT pinned serialize-filter version — the EXACT twin of
`SECTION_ATTR_TRANSFORM_VERSION`/`STRIP_FILTER_VERSION`.** A non-citing render → `has_citations`
False → `--citeproc` never appended → the version key is ABSENT from the serialize preimage →
byte-identical to pre-C6 → zero render-digest churn across the whole existing corpus. A citing
render records it and mints a DIFFERENT digest.

**Non-mutating, deterministic, stdlib-only.** `has_citations` is a pure read of the AST; it never
copies or mutates the caller's AST (mirrors `section_attr_validity`'s recursive walk, read-only).
Imports only the stdlib.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "CITEPROC_ENABLEMENT_VERSION",
    "has_citations",
]

#: C6 citeproc-enablement version — a pinned, byte-altering render input for any render whose AST
#: carries a citation (`--citeproc` resolves it against `meta.references`, §17 R-4 family). It joins
#: the serialize preimage ONLY when citeproc actually fired (OMIT-WHEN-ABSENT — see
#: `pipeline.serialize.serialize_inputs_preimage`). Bump ONLY in a future coordinated release when a
#: rule change alters the RESOLVED BYTES of a currently-producible citing render — never here. C6
#: ships version 1 (the twin of `SECTION_ATTR_TRANSFORM_VERSION`).
CITEPROC_ENABLEMENT_VERSION = 1


def _walk_has_cite(node: Any) -> bool:
    """True iff a Pandoc `Cite` node (`{"t": "Cite", …}`) exists anywhere in `node`, at any depth
    (mirrors `section_attr_validity._walk_strip`'s recursion, read-only). A `Cite` is the CONTENT
    signal that the render must resolve under `--citeproc`."""
    if isinstance(node, dict):
        if node.get("t") == "Cite":
            return True
        return any(_walk_has_cite(value) for value in node.values())
    if isinstance(node, list):
        return any(_walk_has_cite(item) for item in node)
    return False


def has_citations(ast: dict[str, Any]) -> bool:
    """Whether the layer-3 `ast` carries any citation (`Cite`) node — the CONTENT signal that keys
    C6 citeproc enablement (§17 R-4 family).

    Pure and non-mutating: reads the AST, copies nothing. Walks the body `blocks` AND `meta`
    (a citation can ride an abstract in frontmatter), mirroring the SD-5 strip's two-surface walk.
    True → dispatch appends `--citeproc` and the OMIT-WHEN-ABSENT `citeproc_enablement_version`
    rides the preimage; False → the key is absent, so the render is byte-identical to pre-C6.
    """
    if _walk_has_cite(ast.get("blocks", [])):
        return True
    return _walk_has_cite(ast.get("meta", {}))
