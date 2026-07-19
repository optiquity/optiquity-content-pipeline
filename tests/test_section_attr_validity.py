"""C9 tests: the SD-5 section-attr validity filter (§17 R-4) — the heading-validity strip.

Coverage (DR-4 build COMMIT C9 acceptance):
- A typed `Header` loses its bare `type=`/`role=` kv but KEEPS the `{#id}` anchor + classes —
  so a public writer emits valid HTML5 (`<h2 id="…">`, never `<h2 … type="figure">`).
- A `type=`/`role=` kv on a NON-Header node is untouched (Header-scoped by design).
- `data-*` kv are untouched — DISJOINT from `provenance_strip`'s domain (the two filters share
  the AST but never the same keys).
- `changed` is True on a typed AST, False on a plain one (the omit-when-absent signal).
- Non-mutation: the caller's input AST is untouched (a deep-copied result).
- The filter also fires on a REAL pandoc AST (a typed heading round-tripped through the pinned
  reader) — pandoc-gated, mirroring the serialize/strip suites.
"""

import copy

import pytest

from pipeline.filters.provenance_strip import strip_provenance
from pipeline.filters.section_attr_validity import (
    SECTION_ATTR_KEYS,
    SECTION_ATTR_TRANSFORM_VERSION,
    strip_section_attrs,
)
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate, serialize_fitted

_PANDOC_AVAILABLE = pandoc_available()


def _requires_pandoc():
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize/strip pass MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the real-AST assertions need the pinned reader")


def _header(node_id, classes, kvs, level=2):
    return {"t": "Header", "c": [level, [node_id, classes, kvs], [{"t": "Str", "c": "H"}]]}


def _doc(*blocks):
    return {"pandoc-api-version": [1, 23, 1, 2], "meta": {}, "blocks": list(blocks)}


# ---------------------------------------------------------------------------
# The removal property (a typed heading) — keeps id + classes.
# ---------------------------------------------------------------------------


def test_typed_header_loses_type_and_role_but_keeps_id_and_classes():
    ast = _doc(_header("fig-1", ["callout"], [["type", "figure"], ["role", "abstract"]]))
    stripped, changed = strip_section_attrs(ast)
    assert changed is True
    _level, attr, _inlines = stripped["blocks"][0]["c"]
    node_id, classes, kvs = attr
    assert node_id == "fig-1"  # the {#id} anchor SURVIVES (a valid, published heading id)
    assert classes == ["callout"]  # classes untouched
    assert kvs == []  # both bare structural-typing kv removed


def test_partial_typed_header_removes_only_the_structural_keys():
    # A heading carrying a mix: only `type`/`role` go; a plain non-structural kv stays.
    ast = _doc(_header("h", [], [["type", "figure"], ["data-x", "1"], ["lang", "en"]]))
    stripped, changed = strip_section_attrs(ast)
    assert changed is True
    _l, (_id, _c, kvs), _i = stripped["blocks"][0]["c"]
    keys = [k for k, _ in kvs]
    assert "type" not in keys and "role" not in keys
    assert "data-x" in keys and "lang" in keys  # non-structural kv survive this filter


# ---------------------------------------------------------------------------
# Header-scoped by design: a `type=` kv on a non-Header node is left alone.
# ---------------------------------------------------------------------------


def test_type_kv_on_non_header_node_is_untouched():
    span = {"t": "Span", "c": [["s1", [], [["type", "figure"], ["role", "x"]]], []]}
    div = {"t": "Div", "c": [["d1", [], [["type", "figure"]]], []]}
    ast = _doc({"t": "Para", "c": [span]}, div)
    stripped, changed = strip_section_attrs(ast)
    assert changed is False  # nothing removed — no Header carried the structural kv
    assert stripped == ast  # a non-Header `type=`/`role=` kv is out of remit, left verbatim


# ---------------------------------------------------------------------------
# Disjoint from provenance_strip: `data-*` is never this filter's concern.
# ---------------------------------------------------------------------------


def test_data_star_kv_on_a_header_is_left_untouched():
    ast = _doc(_header("h", ["EXTRACTED"], [["data-fact", "f0"], ["type", "figure"]]))
    stripped, changed = strip_section_attrs(ast)
    assert changed is True
    _l, (_id, classes, kvs), _i = stripped["blocks"][0]["c"]
    keys = [k for k, _ in kvs]
    assert "type" not in keys  # this filter removed the structural kv
    assert "data-fact" in keys  # …but left data-* to provenance_strip (disjoint)
    assert classes == ["EXTRACTED"]  # …and left the tier class to provenance_strip too


def test_composes_with_provenance_strip_without_overlap():
    # On the public-writer path the two strips run in sequence (provenance first, then section-
    # attr) over the SAME AST but DIFFERENT node types: provenance_strip cleans the claim Span
    # (data-* kv + tier class), this filter cleans the Header (type/role kv). Neither touches the
    # other's node, so composition leaves both clean.
    span = {
        "t": "Span",
        "c": [["fact-1", ["EXTRACTED"], [["data-fact", "f0"]]], [{"t": "Str", "c": "x"}]],
    }
    ast = _doc(
        _header("h", ["callout"], [["type", "figure"], ["role", "abstract"]]),
        {"t": "Para", "c": [span]},
    )
    final, changed = strip_section_attrs(strip_provenance(ast))
    assert changed is True
    _l, (_hid, hclasses, hkvs), _i = final["blocks"][0]["c"]
    assert hkvs == [] and hclasses == ["callout"]  # header: type/role gone (this filter)
    stripped_span = final["blocks"][1]["c"][0]["c"][0]
    assert stripped_span[1] == [] and stripped_span[2] == []  # span: tier + data-* gone (prov)
    assert stripped_span[0] == ""  # the fact-anchor id blanked by provenance_strip


# ---------------------------------------------------------------------------
# The `changed` signal + non-mutation.
# ---------------------------------------------------------------------------


def test_changed_is_false_on_a_plain_heading():
    ast = _doc(_header("h", ["callout"], []))
    stripped, changed = strip_section_attrs(ast)
    assert changed is False
    assert stripped == ast  # nothing to remove — byte-identical structure


def test_changed_is_false_on_an_ast_with_no_headings():
    ast = _doc({"t": "Para", "c": [{"t": "Str", "c": "plain"}]})
    stripped, changed = strip_section_attrs(ast)
    assert changed is False
    assert stripped == ast


def test_strip_is_non_mutating():
    ast = _doc(_header("fig-1", ["callout"], [["type", "figure"], ["role", "abstract"]]))
    before = copy.deepcopy(ast)
    stripped, _changed = strip_section_attrs(ast)
    assert ast == before  # the caller's AST (the persisted layer-3 record) is untouched
    assert stripped is not ast  # a distinct, deep-copied result


# ---------------------------------------------------------------------------
# Module constants + the SECTION_ATTR_KEYS vocabulary.
# ---------------------------------------------------------------------------


def test_module_constants():
    # C9 ships v1; a bump is a future coordinated release, never here.
    assert SECTION_ATTR_TRANSFORM_VERSION == 1
    assert SECTION_ATTR_KEYS == frozenset({"type", "role"})


# ---------------------------------------------------------------------------
# The filter fires on a REAL pandoc AST (a typed heading through the pinned reader).
# ---------------------------------------------------------------------------


def test_strip_on_real_serialized_typed_heading():
    _requires_pandoc()
    fitted = {
        "grounding": {},
        "body": "## Figure One {#fig-1 type=figure role=abstract}\n\nSome body text.",
    }
    ast = serialize_fitted(fitted)[0].ast

    def _headers(node, out):
        if isinstance(node, dict):
            if node.get("t") == "Header":
                out.append(node["c"][1])
            for v in node.values():
                _headers(v, out)
        elif isinstance(node, list):
            for v in node:
                _headers(v, out)
        return out

    # the real AST DOES carry the invalid structural kv (the gate is not a no-op)
    before = _headers(ast["blocks"], [])
    assert before and any(k in dict(kvs) for _id, _c, kvs in before for k in ("type", "role"))
    stripped, changed = strip_section_attrs(ast)
    assert changed is True
    after = _headers(stripped["blocks"], [])
    for _id, _classes, kvs in after:
        keys = [k for k, _ in kvs]
        assert "type" not in keys and "role" not in keys
    assert after[0][0] == "fig-1"  # the {#id} anchor survived on the real AST
