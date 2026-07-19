"""C9 tests: the dispatcher's SD-5 section-attr validity gate (§17 R-4 / RI12).

Coverage (DR-4 build COMMIT C9 acceptance):
- A TYPED AST → a PUBLIC writer (html5 internal, epub3 external) → the rendered bytes / hand-off
  AST carry NO raw `type=`/`role=` and DO keep the `{#id}` anchor (valid HTML5).
- The SAME typed AST → a SAFE writer (`markdown`/`json`) KEEPS the structural typing — the
  round-trippable internal record retains it (the delta vs. the public writer proves the gate
  fired, not that the AST never carried the attrs).
- `DispatchOutcome.section_attr_transformed` is True exactly when a public writer stripped a bare
  `type=`/`role=` heading kv, and False otherwise (safe writer, or a non-typed AST).

pandoc is required for the rendered-bytes assertions; the guard fails loudly under CI-absent.
"""

import json

import pytest

from pipeline import dispatch as D
from pipeline.filters.section_attr_validity import SECTION_ATTR_KEYS
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate, run_pandoc, serialize_fitted

_PANDOC_AVAILABLE = pandoc_available()


@pytest.fixture(autouse=True)
def _require_pandoc():
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize/dispatch pass MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the dispatch tests exercise the real serialize AST")


_TYPED_FITTED = {
    "grounding": {},
    "body": "## Figure One {#fig-1 type=figure role=abstract}\n\nSome body text here.",
}
_PLAIN_FITTED = {
    "grounding": {},
    "body": "## Plain Heading {#plain-1}\n\nNo structural typing here.",
}


def _typed_ast():
    return serialize_fitted(_TYPED_FITTED)[0].ast


def _plain_ast():
    return serialize_fitted(_PLAIN_FITTED)[0].ast


def _header_attrs(ast):
    out = []

    def _walk(node):
        if isinstance(node, dict):
            if node.get("t") == "Header":
                out.append(node["c"][1])
            for v in node.values():
                _walk(v)
        elif isinstance(node, list):
            for v in node:
                _walk(v)

    _walk(ast.get("blocks", []))
    return out


# ---------------------------------------------------------------------------
# The public writers strip → valid bytes; the transform flag is True.
# ---------------------------------------------------------------------------


def test_html5_bytes_carry_no_raw_type_or_role_but_keep_id():
    out = D.dispatch(D.RenderTarget(writer="html5", side="internal"), _typed_ast())
    assert out.section_attr_transformed is True
    assert b"type=" not in out.output_bytes  # the INVALID raw HTML5 attribute is gone
    assert b"role=" not in out.output_bytes
    assert b'id="fig-1"' in out.output_bytes  # the {#id} anchor SURVIVES (valid, published)


def test_epub3_external_payload_headers_lose_type_and_role():
    out = D.dispatch(D.RenderTarget(writer="epub3", side="external"), _typed_ast())
    assert out.code == D.EXTERNAL_DEFERRED and out.section_attr_transformed is True
    for _id, _classes, kvs in _header_attrs(out.payload_ast):
        keys = {k for k, _ in kvs}
        assert not (keys & SECTION_ATTR_KEYS)  # no type/role kv survives the hand-off AST
    assert _header_attrs(out.payload_ast)[0][0] == "fig-1"  # id kept


# ---------------------------------------------------------------------------
# The safe writers KEEP the structural typing (the internal record) — flag False.
# ---------------------------------------------------------------------------


def test_markdown_safe_writer_keeps_type_and_role():
    out = D.dispatch(D.RenderTarget(writer="markdown", side="internal"), _typed_ast())
    assert out.section_attr_transformed is False and out.stripped is False
    assert b"type=" in out.output_bytes  # the internal record retains the structural typing
    assert b"role=" in out.output_bytes


def test_json_passthrough_keeps_type_and_role():
    out = D.dispatch(D.RenderTarget(writer="json", side="internal"), _typed_ast())
    assert out.section_attr_transformed is False and out.stripped is False
    payload = json.loads(out.output_bytes)
    for _id, _classes, kvs in _header_attrs(payload):
        keys = {k for k, _ in kvs}
        assert SECTION_ATTR_KEYS <= keys  # both type AND role are retained in the raw AST record


# ---------------------------------------------------------------------------
# A NON-typed AST: the public-writer transform is a no-op → flag False.
# ---------------------------------------------------------------------------


def test_non_typed_ast_public_writer_transform_is_a_noop():
    out = D.dispatch(D.RenderTarget(writer="html5", side="internal"), _plain_ast())
    assert out.stripped is True  # provenance strip still runs (public writer)
    assert out.section_attr_transformed is False  # …but no heading carried a type/role kv
    assert b'id="plain-1"' in out.output_bytes  # the plain heading id is untouched


def test_flag_matrix_across_writers_and_typedness():
    typed, plain = _typed_ast(), _plain_ast()
    # public writers over a TYPED AST → transformed
    for w, side in (("html5", "internal"), ("epub3", "external")):
        assert D.dispatch(D.RenderTarget(writer=w, side=side), typed).section_attr_transformed
    # safe writers over a TYPED AST → NOT transformed (they keep the typing)
    for w in ("markdown", "json"):
        assert not D.dispatch(
            D.RenderTarget(writer=w, side="internal"), typed
        ).section_attr_transformed
    # any writer over a NON-typed AST → NOT transformed
    for w, side in (("html5", "internal"), ("epub3", "external"), ("markdown", "internal")):
        assert not D.dispatch(
            D.RenderTarget(writer=w, side=side), plain
        ).section_attr_transformed


def test_html5_delta_proves_the_gate_fired():
    # The typing genuinely reaches the AST: a SAFE writer emits `type=`, the PUBLIC writer does
    # not — the delta is the gate at work, never a silent no-op over an AST that lacked the attrs.
    typed = _typed_ast()
    md = D.dispatch(D.RenderTarget(writer="markdown", side="internal"), typed).output_bytes
    html = D.dispatch(D.RenderTarget(writer="html5", side="internal"), typed).output_bytes
    assert b"type=" in md and b"type=" not in html
    # and the raw rendered html5 of the UN-stripped AST WOULD be invalid (sanity on the writer)
    raw = run_pandoc(("-f", "json", "-t", "html5"), json.dumps(typed)).stdout
    assert 'type="figure"' in raw  # proves the un-gated bytes are the invalid ones C9 removes
