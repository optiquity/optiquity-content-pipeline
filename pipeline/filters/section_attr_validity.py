"""The pinned section-attr validity filter (§17 R-4 / SD-5) — DR-4 build, COMMIT C9.

Design authority: `docs/design.md`
  §17 R-4 — the public-writer AST-strip family (the provenance-strip precedent). This is a
         SIBLING strip on the SAME serialize-owned, public-writer path: a pinned, deterministic
         pre-serialize transform that removes bytes a published writer would otherwise emit.
  SD-5 (strip-invalid-keep-valid) — DR-4 section typing authors headings as
         `## H {#id type=figure}`. The pinned pandoc reader parses that into a `Header` whose
         `Attr = [id, [classes], [["type","figure"], …]]`. Rendered to html5/epub, that surfaces
         as `<h2 … type="figure">` / `<section … type="figure" role="…">` — the bare `type=`/`role=`
         kv are INVALID as raw HTML5 attributes. C9 STRIPS those bare kv from HEADING nodes on the
         PUBLIC-writer render copy, keeping the valid `{#id}` anchor + the classes, so published
         bytes are valid. The safe (internal-record) writers KEEP the attrs — the round-trippable
         internal record retains the structural typing.

**Disjoint from `provenance_strip` (the sibling public-writer strip).** `provenance_strip` removes
the `data-*` provenance kv, the tier classes, and fact-anchor ids from EVERY attributed node. THIS
filter removes only the bare `type`/`role` kv, and only from HEADER nodes, and KEEPS the id + the
classes. The two key sets never intersect (`type`/`role` are bare keys, never `data-`), so the two
filters compose cleanly on the same render copy without either touching the other's surface.

**Header-scoped by design.** The section-typing carrier is the heading (`Header`), not a generic
attributed node — a `type=`/`role=` kv on some OTHER node is out of this filter's remit (a test
pins that a non-Header `type=` kv is left untouched). A `Header`'s Attr lives in the SECOND `c`
slot (`c = [level, Attr, inlines]`), unlike a `Div`/`Span` whose Attr is `c[0]`.

**Non-mutating, deterministic, stdlib-only.** Returns a DEEP COPY of the AST with the header attrs
stripped; the caller's AST (the full layer-3 record `pipeline.ast_store` persists) is untouched —
the strip is a per-render transform for public writers only. Imports only the stdlib.
"""

from __future__ import annotations

import copy
from typing import Any

__all__ = [
    "SECTION_ATTR_KEYS",
    "SECTION_ATTR_TRANSFORM_VERSION",
    "strip_section_attrs",
]

#: SD-5 transform version — a pinned, byte-altering render input for any writer that would publish
#: a typed heading (it joins the serialize preimage ONLY when the transform actually fired, §17
#: FR7.1 / see `pipeline.serialize.serialize_inputs_preimage`). Bump ONLY in a future coordinated
#: release when a rule change alters the PUBLISHED BYTES of a currently-producible typed render —
#: never here. C9 ships version 1.
SECTION_ATTR_TRANSFORM_VERSION = 1

#: The bare structural-typing keys that are INVALID as raw HTML5 attributes on a heading (SD-5).
#: These are plain keys, never `data-` — disjoint from `provenance_strip`'s `data-*` domain.
SECTION_ATTR_KEYS = frozenset({"type", "role"})


def _is_attr(value: Any) -> bool:
    """A Pandoc `Attr`: `[str id, [str classes], [[str key, str value], …]]` (mirrors
    `provenance_strip._is_attr` — the two filters share the shape, never the keys)."""
    return (
        isinstance(value, list)
        and len(value) == 3
        and isinstance(value[0], str)
        and isinstance(value[1], list)
        and isinstance(value[2], list)
        and all(isinstance(c, str) for c in value[1])
        and all(isinstance(kv, list) and len(kv) == 2 for kv in value[2])
    )


def _strip_header_attr(attr: list[Any]) -> tuple[list[Any], bool]:
    """Strip the bare `type`/`role` kv from ONE heading `Attr = [id, [classes], [[k, v], …]]`.

    Returns `(new_attr, changed)`. Removes every kv whose key ∈ `SECTION_ATTR_KEYS`; KEEPS the id
    and the classes verbatim (the `{#id}` anchor is a valid, published heading id). `changed` is
    True iff a kv was removed.
    """
    if not _is_attr(attr):
        return attr, False  # not an Attr shape — leave untouched (defensive)
    node_id, classes, kvs = attr
    new_kvs = [kv for kv in kvs if str(kv[0]) not in SECTION_ATTR_KEYS]
    changed = new_kvs != kvs
    return [node_id, classes, new_kvs], changed


def _walk_strip(node: Any) -> bool:
    """Recursively strip the bare `type`/`role` kv from every `Header` node, IN PLACE on `node`.

    A Pandoc `Header` is `{"t": "Header", "c": [level, Attr, inlines]}` — the Attr is the SECOND
    `c` element (unlike `Div`/`Span`, whose Attr is `c[0]`). Only `Header` nodes are touched; a
    `type=`/`role=` kv anywhere else is out of remit. Returns whether any header was altered.
    """
    changed = False
    if isinstance(node, dict):
        if node.get("t") == "Header":
            c = node.get("c")
            if isinstance(c, list) and len(c) == 3 and _is_attr(c[1]):
                new_attr, header_changed = _strip_header_attr(c[1])
                if header_changed:
                    c[1] = new_attr
                    changed = True
        for value in node.values():
            changed = _walk_strip(value) or changed
    elif isinstance(node, list):
        for item in node:
            changed = _walk_strip(item) or changed
    return changed


def strip_section_attrs(ast: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Return `(deep-copied stripped AST, changed)` — the SD-5 heading-validity strip (§17 R-4).

    Pure, deterministic, and non-mutating: the caller's `ast` is untouched. Removes the bare
    `type`/`role` kv from every `Header` node (keeping the id + classes), so a public writer emits
    valid HTML5. `changed` is True iff at least one heading actually lost a kv — the signal the
    dispatcher threads into the serialize preimage so the transform version is recorded ONLY when
    it altered bytes (zero churn for the non-typed corpus, §17 FR7.1).
    """
    stripped = copy.deepcopy(ast)
    changed = _walk_strip(stripped.get("blocks", []))
    changed = _walk_strip(stripped.get("meta", {})) or changed
    return stripped, changed
