"""Step-27 tests: the serialize core (§17 RI6–RI9, RI13) — pandoc required, NOT live-marked.

Coverage (plan step-27 acceptance):
- **Determinism** (RI6): same IR-fitted + same pins ⇒ byte-identical emitted Markdown AND
  byte-identical AST (run twice, diff).
- **RI7 round-trip**: emit → parse → the claim/part attributes survive the
  markdown→json→markdown→json cycle at the JSON/AST level (attribute equality, not a text diff).
- **Emit/extract symmetry** with step 24: `ir.extract_fact_refs` recovers exactly the claims
  the emitter wrote, including visible text that nests/escapes brackets (the INVERSE property).
- **RI8 Attr mapping**: parts → fenced Divs (role class, part-id kv, sequence, packaging hint);
  claims → Spans (tier class, `data-fact` + provenance kv).
- **RI9 one-AST-vs-N**: `packaging_hint` drives whether serialize yields one AST or N.
- **render-binding** (RI13/FR7.1): `minted_ts`/wall-clock excluded from the identity digest and
  the deliverable-id; `side` excluded from the preimage; the id is minted via `ids.deliverable_id`.
- **The pandoc gate** (PA-12): absent + CI=true ⇒ FAIL (not skip); absent local ⇒ skip;
  present ⇒ run — proven by the pure `pandoc_gate` function + the loud `PandocUnavailableError`.
- **INV-CORRECTNESS**: the serialize modules import no SSOT.

All stores/paths in these tests live under pytest tmp_path; nothing touches the repo tree.
"""

import ast as ast_mod
import json
from pathlib import Path

import pytest

from pipeline import dispatch as D
from pipeline.filters.provenance_strip import STRIP_FILTER_VERSION, strip_provenance
from pipeline.filters.section_attr_validity import (
    SECTION_ATTR_TRANSFORM_VERSION,
    strip_section_attrs,
)
from pipeline.ir import PANDOC_API_VERSION, extract_fact_refs
from pipeline.serialize import (
    READER_PIN,
    PandocOutcome,
    PandocParseError,
    PandocUnavailableError,
    SerializeError,
    build_render_binding,
    emit_claim_span,
    emit_fitted_markdown,
    enrich_leaf,
    escape_span_text,
    extension_for,
    is_ci,
    pandoc_available,
    pandoc_gate,
    parse_to_ast,
    plan_documents,
    run_pandoc,
    serialize_digest,
    serialize_fitted,
    serialize_inputs_preimage,
)

_PANDOC_AVAILABLE = pandoc_available()


@pytest.fixture(autouse=True)
def _require_pandoc():
    """PA-12 guard: absent + CI ⇒ FAIL loudly (a silent skip cannot make CI green); absent
    locally ⇒ skip; present ⇒ run. The CI job installs the pinned binary, so CI lands on run."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize pass MUST run in CI (PA-12); a silent "
            "skip cannot make CI green",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the serialize tests require the pinned binary")


# ---------------------------------------------------------------------------
# Fixtures: IR-fitted envelopes (only the grounding + leaves the emitter reads).
# ---------------------------------------------------------------------------

ART = "a-0123456789abcdef"
FIT = "a-0123456789abcdef.linkedin.en"

_LEDGER = {
    "f0": {
        "tier": "EXTRACTED",
        "source_instance_id": "repo-a",
        "source_repo": "github.com/x/a",
        "source_commit": "abc123def456",
        "traceability_anchor": ["src/limits.py:42"],
        "scores_snapshot": {},
    },
    "f1": {
        "tier": "INFERRED",
        "source_instance_id": "repo-b",
        "source_repo": "github.com/x/b",
        "source_commit": None,
        "traceability_anchor": [],
        "scores_snapshot": {},
    },
}


def _flat_fitted():
    return {
        "grounding": _LEDGER,
        "body": 'The limit is [100 req/s]{.EXTRACTED data-fact="f0"} and [items\\[0\\] '
        'apply]{.INFERRED data-fact="f1"}.',
    }


def _parts_fitted(hint_intro="in-document", hint_appendix="in-document"):
    return {
        "grounding": _LEDGER,
        "parts": [
            {
                "part-id": f"{ART}~intro",
                "role": "intro",
                "packaging_hint": hint_intro,
                "body": 'Rate [100 req/s]{.EXTRACTED data-fact="f0"} holds.',
            },
            {
                "part-id": f"{ART}~appendix",
                "role": "appendix",
                "packaging_hint": hint_appendix,
                "body": 'See [the note]{.INFERRED data-fact="f1"}.',
            },
        ],
    }


# ---------------------------------------------------------------------------
# Determinism (RI6).
# ---------------------------------------------------------------------------


def test_emit_is_byte_deterministic():
    fitted = _parts_fitted()
    assert emit_fitted_markdown(fitted) == emit_fitted_markdown(fitted)


def test_serialize_ast_is_byte_deterministic():
    fitted = _parts_fitted()
    a = serialize_fitted(fitted)
    b = serialize_fitted(fitted)
    assert [u.ast for u in a] == [u.ast for u in b]
    # Byte-identical when canonicalized — the "run twice, diff" acceptance.
    assert [json.dumps(u.ast, sort_keys=True) for u in a] == [
        json.dumps(u.ast, sort_keys=True) for u in b
    ]


# ---------------------------------------------------------------------------
# RI7 round-trip: attribute survival across md→json→md→json (JSON/AST equality).
# ---------------------------------------------------------------------------


def _collect_attrs(node, out):
    if isinstance(node, dict):
        if node.get("t") in ("Div", "Span") and isinstance(node.get("c"), list) and node["c"]:
            out.append((node["t"], node["c"][0]))
        for v in node.values():
            _collect_attrs(v, out)
    elif isinstance(node, list):
        for v in node:
            _collect_attrs(v, out)
    return out


def test_ri7_attribute_round_trip():
    fitted = _parts_fitted()
    md = emit_fitted_markdown(fitted)
    r1 = parse_to_ast(md)
    # The re-emission uses --wrap=none: RI7 is ATTRIBUTE survival, NOT a text diff (PA-8b —
    # pandoc's markdown writer re-wraps long lines, a presentation choice orthogonal to the
    # attributes). The emitter never wraps, so with wrap controlled the round trip is byte-exact.
    back = run_pandoc(("-f", "json", "-t", "markdown", "--wrap=none"), json.dumps(r1)).stdout
    r2 = parse_to_ast(back)

    a1 = _collect_attrs(r1["blocks"], [])
    a2 = _collect_attrs(r2["blocks"], [])
    assert a1, "no Div/Span attrs found — extensions not effective?"
    assert a1 == a2, "RI7 attribute loss across the round trip"
    assert r1["pandoc-api-version"] == r2["pandoc-api-version"] == list(PANDOC_API_VERSION)
    # whole-document canonical byte-equality (the gate-3 assertion D, wrap controlled)
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


def test_ri7_attribute_survival_is_wrap_independent():
    # RI7 is attribute equality, NOT a text diff: even under pandoc's DEFAULT re-wrapping (which
    # changes the whole-doc bytes), every Div/Span Attr survives the round trip identically.
    r1 = parse_to_ast(emit_fitted_markdown(_parts_fitted()))
    back = run_pandoc(("-f", "json", "-t", "markdown"), json.dumps(r1)).stdout  # default wrap
    r2 = parse_to_ast(back)
    assert _collect_attrs(r1["blocks"], []) == _collect_attrs(r2["blocks"], [])


def test_ri8_attr_mapping_parts_and_claims():
    r1 = parse_to_ast(emit_fitted_markdown(_parts_fitted()))
    attrs = _collect_attrs(r1["blocks"], [])
    divs = [a for t, a in attrs if t == "Div"]
    spans = [a for t, a in attrs if t == "Span"]
    # a part Div: class = role; kv carries the full part-id, sequence, packaging hint (RI8)
    intro = next(a for a in divs if a[1] == ["intro"])
    kv = dict(intro[2])
    assert kv["data-part-id"] == f"{ART}~intro"
    assert kv["sequence"] == "1"
    assert kv["packaging-hint"] == "in-document"
    # a claim Span: tier class + data-fact + provenance kv (RI8)
    f0 = next(a for a in spans if dict(a[2]).get("data-fact") == "f0")
    assert f0[1] == ["EXTRACTED"]
    assert dict(f0[2])["data-source-instance"] == "repo-a"
    assert dict(f0[2])["data-source-commit"] == "abc123def456"
    assert dict(f0[2])["data-traceability"] == "src/limits.py:42"


# ---------------------------------------------------------------------------
# Emit/extract symmetry with step 24 (the INVERSE property).
# ---------------------------------------------------------------------------


def test_emitter_output_is_extractable_by_step24_reader():
    md = emit_fitted_markdown(_parts_fitted())
    refs = extract_fact_refs(md, where="emitted")
    assert sorted((r.fact_id, r.tier) for r in refs) == [
        ("f0", "EXTRACTED"),
        ("f1", "INFERRED"),
    ]


def test_escape_and_emit_claim_span_round_trip_with_brackets():
    # A claim whose visible text contains UNBALANCED brackets must still round-trip.
    span = emit_claim_span("array items[0", "f0", "EXTRACTED", _LEDGER["f0"])
    refs = extract_fact_refs(span, where="scratch")
    assert len(refs) == 1 and refs[0].fact_id == "f0" and refs[0].tier == "EXTRACTED"
    # and pandoc parses it into exactly one Span with the fact-id kv
    r = parse_to_ast(span)
    spans = [a for t, a in _collect_attrs(r["blocks"], []) if t == "Span"]
    assert len(spans) == 1 and dict(spans[0][2])["data-fact"] == "f0"


def test_escape_span_text_escapes_brackets_and_backslash():
    assert escape_span_text(r"a[b]\c") == r"a\[b\]\\c"


def test_match_bracket_twins_agree_byte_for_byte():
    # After the step-27 F3 dedup the emit path (serialize) and the extract path (ir) share ONE
    # balanced-bracket scanner: `ir.match_bracket`. This test guards that invariant two ways so
    # a future re-divergence (someone re-adds a separate hand-maintained copy) fails LOUDLY.
    from pipeline import ir, serialize

    # (1) IDENTITY — the "twins" are literally the SAME object. If a separate copy is ever
    #     reintroduced these break, catching the drift the old self-comparison could not.
    assert serialize.match_bracket is ir.match_bracket
    assert serialize._match_bracket is ir.match_bracket
    assert ir._match_bracket is ir.match_bracket

    # (2) BEHAVIOR — pin the shared scanner against EXPECTED-LITERAL outputs (never against
    #     itself), over nested / escaped / unbalanced / offset / empty / no-bracket inputs, so a
    #     change to the shared helper's contract is also caught here.
    expected = [
        ("[]", 0, 1),  # empty pair
        ("[abc]", 0, 4),  # simple
        ("[a[b]c]", 0, 6),  # nested
        ("[[nested]]", 0, 9),  # nested at the head
        ("[a\\]b]", 0, 5),  # escaped close bracket inside → real close is later
        ("[a\\[b]", 0, 5),  # escaped open bracket inside
        ("[esc\\\\]", 0, 6),  # escaped backslash, then a real close
        ("[unbalanced", 0, None),  # never closes
        ("[a[b]", 0, None),  # unbalanced nested
        ("[a]b]c", 0, 2),  # closes early, trailing junk ignored
        ("prefix[x]y", 6, 8),  # the bracket is not at index 0
        ("no brackets here", 0, None),  # text[start] != '['
        ("", 0, None),  # empty string
        ("[\\[\\]]", 0, 5),  # both inner brackets escaped → outer closes at 5
        ("[\\]", 0, None),  # a lone escaped close → never balances
    ]
    for text, start, want in expected:
        assert ir.match_bracket(text, start) == want, (text, start)
        # the emit-side attribute is that same pinned behavior (belt-and-suspenders on identity)
        assert serialize._match_bracket(text, start) == want, (text, start)


def test_enrich_leaf_is_idempotent():
    body = _flat_fitted()["body"]
    once = enrich_leaf(body, _LEDGER)
    twice = enrich_leaf(once, _LEDGER)
    assert once == twice  # provenance kv appended exactly once


# ---------------------------------------------------------------------------
# RI9: packaging_hint drives one-AST-vs-N.
# ---------------------------------------------------------------------------


def test_all_in_document_parts_yield_one_ast():
    units = serialize_fitted(_parts_fitted("in-document", "in-document"))
    assert len(units) == 1
    assert units[0].label is None
    assert units[0].part_ids == (f"{ART}~intro", f"{ART}~appendix")


def test_standalone_part_yields_its_own_ast():
    units = serialize_fitted(_parts_fitted("in-document", "standalone"))
    # one combined (the in-document part) + one standalone
    assert len(units) == 2
    labels = {u.label for u in units}
    assert labels == {None, "appendix"}
    standalone = next(u for u in units if u.label == "appendix")
    assert standalone.part_ids == (f"{ART}~appendix",)


def test_flat_body_is_one_document():
    units = serialize_fitted(_flat_fitted())
    assert len(units) == 1 and units[0].label is None and units[0].part_ids == ()
    plans = plan_documents(_flat_fitted())
    assert len(plans) == 1


# ---------------------------------------------------------------------------
# The render-binding (RI13/FR7.1): identity excludes minted_ts/wall-clock and side.
# ---------------------------------------------------------------------------

_RENDER_TARGET = {
    "id": "html",
    "writer": "html5",
    "side": "internal",
    "engine": "",
    "reference_doc": "",
    "pandoc_version": "3.10",
    "pandoc_api_version": [1, 23, 1, 2],
    "reader": READER_PIN,
    "schema_version": 1,
}
_RENDER_INPUTS = {"flags": [], "variables": {}, "assets": [], "engine": ""}
_FIT_REF = {"fitted_id": FIT, "digest": "4b7a90ce12d3"}


def test_render_binding_identity_excludes_minted_ts():
    pre = serialize_inputs_preimage(render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS)
    rb1 = build_render_binding(
        fitted_id=FIT,
        output_type="html",
        presentation="plain",
        preimage=pre,
        fit_binding_ref=_FIT_REF,
        minted_ts="2020-01-01T00:00:00+00:00",
    )
    rb2 = build_render_binding(
        fitted_id=FIT,
        output_type="html",
        presentation="plain",
        preimage=pre,
        fit_binding_ref=_FIT_REF,
        minted_ts="2099-12-31T23:59:59+00:00",
    )
    assert rb1["digest"] == rb2["digest"]
    assert rb1["deliverable_id"] == rb2["deliverable_id"]
    assert rb1["deliverable_id"] == "a-0123456789abcdef.linkedin.en.html.plain"
    assert rb1["minted_ts"] != rb2["minted_ts"]  # the record field DOES differ


def test_serialize_preimage_excludes_side_and_coordinate_slugs():
    pre = serialize_inputs_preimage(render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS)
    blob = json.dumps(pre)
    assert "internal" not in blob  # `side` value absent (§17 FR7.1)
    assert '"side"' not in blob
    assert '"schema_version"' not in blob and '"id"' not in blob
    # a side flip does not change the digest (dispatch routing, not a byte-determining input)
    flipped = dict(_RENDER_TARGET, side="external")
    pre2 = serialize_inputs_preimage(render_target=flipped, render_inputs=_RENDER_INPUTS)
    assert serialize_digest(pre) == serialize_digest(pre2)


def test_render_binding_rejects_missing_fit_reference():
    from pipeline.serialize import SerializeError

    pre = serialize_inputs_preimage(render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS)
    with pytest.raises(SerializeError):
        build_render_binding(
            fitted_id=FIT,
            output_type="html",
            presentation="plain",
            preimage=pre,
            fit_binding_ref={},  # no fitted_id
        )


def test_serialize_revision_qualifier_mints_on_the_presentation_segment():
    pre = serialize_inputs_preimage(render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS)
    rb = build_render_binding(
        fitted_id=FIT,
        output_type="html",
        presentation="plain",
        preimage=pre,
        fit_binding_ref=_FIT_REF,
        serialize_revision=True,
    )
    assert rb["deliverable_id"] == f"a-0123456789abcdef.linkedin.en.html.plain_{rb['digest']}"


# ---------------------------------------------------------------------------
# SD-5 (C9): the section-attr transform version rides the preimage OMIT-WHEN-ABSENT.
# ---------------------------------------------------------------------------


def test_serialize_preimage_omits_transform_version_when_absent():
    # OMIT-WHEN-ABSENT: the default (and every non-typed / SAFE-writer render) leaves the key
    # ABSENT → the preimage is byte-identical to the pre-SD-5 form → the golden corpus is unchanged.
    pre_default = serialize_inputs_preimage(
        render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS
    )
    pre_false = serialize_inputs_preimage(
        render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS, section_attr_transformed=False
    )
    assert "section_attr_transform_version" not in pre_default["tool_bundle"]
    assert pre_default == pre_false  # the new kwarg's default reproduces the pre-SD-5 preimage
    assert serialize_digest(pre_default) == serialize_digest(pre_false)


def test_serialize_preimage_records_transform_version_when_typed():
    # Obligation 3: a TRANSFORMED render carries the version AND mints a DIFFERENT digest (a loud
    # re-mint the moment SD-5 alters bytes, never a silent one — §17 FR7.1).
    pre_false = serialize_inputs_preimage(
        render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS, section_attr_transformed=False
    )
    pre_true = serialize_inputs_preimage(
        render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS, section_attr_transformed=True
    )
    assert (
        pre_true["tool_bundle"]["section_attr_transform_version"] == SECTION_ATTR_TRANSFORM_VERSION
    )
    assert "section_attr_transform_version" not in pre_false["tool_bundle"]
    assert serialize_digest(pre_true) != serialize_digest(pre_false)


def test_strip_filter_version_unchanged_and_disjoint_from_sd5():
    # Obligation 4: adding the SD-5 key leaves the disjoint provenance-strip pin untouched.
    assert STRIP_FILTER_VERSION == 1
    pre = serialize_inputs_preimage(
        render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS, section_attr_transformed=True
    )
    assert pre["tool_bundle"]["strip_filter_version"] == 1


def test_non_typed_render_is_byte_identical_on_both_axes():
    # Obligation 2: a non-typed render is byte-identical to pre-SD-5 on BOTH axes —
    #   (a) the render AST fed to the writer (strip_section_attrs is a no-op atop the provenance
    #       strip, so the pandoc input bytes do not move), and
    #   (b) the serialize preimage (the transform key is absent → the digest is unchanged).
    ast = serialize_fitted(_flat_fitted())[0].ast  # claim spans, NO typed headings
    prov = strip_provenance(ast)
    render_ast, changed = strip_section_attrs(prov)
    assert changed is False and render_ast == prov  # (a) byte-identical render input
    dout = D.dispatch(D.RenderTarget(writer="html5", side="internal"), ast)
    assert dout.section_attr_transformed is False
    pre = serialize_inputs_preimage(
        render_target=_RENDER_TARGET,
        render_inputs=_RENDER_INPUTS,
        section_attr_transformed=dout.section_attr_transformed,
    )
    baseline = serialize_inputs_preimage(render_target=_RENDER_TARGET, render_inputs=_RENDER_INPUTS)
    assert "section_attr_transform_version" not in pre["tool_bundle"]  # (b)
    assert pre == baseline and serialize_digest(pre) == serialize_digest(baseline)


# ---------------------------------------------------------------------------
# The pinned parse: api-version verification (RI13).
# ---------------------------------------------------------------------------


def test_parse_to_ast_rejects_off_pin_api_version():
    def _fake(args, stdin_text):
        off_pin = {"pandoc-api-version": [9, 9, 9], "blocks": [], "meta": {}}
        return PandocOutcome(0, json.dumps(off_pin), "")

    with pytest.raises(PandocParseError):
        parse_to_ast("anything", runner=_fake)


def test_parse_to_ast_rejects_nonzero_exit():
    def _fake(args, stdin_text):
        return PandocOutcome(1, "", "boom")

    with pytest.raises(PandocParseError):
        parse_to_ast("anything", runner=_fake)


# ---------------------------------------------------------------------------
# The pandoc gate (PA-12): the pure decision + the loud unavailable path.
# ---------------------------------------------------------------------------


def test_pandoc_gate_fails_when_absent_under_ci():
    # THE PA-12 property: absent + CI=true ⇒ FAIL, never skip.
    assert pandoc_gate(available=False, ci=True) == "fail"
    assert pandoc_gate(available=False, ci=False) == "skip"
    assert pandoc_gate(available=True, ci=True) == "run"
    assert pandoc_gate(available=True, ci=False) == "run"


def test_is_ci_parses_truthy_values():
    assert is_ci({"CI": "true"}) and is_ci({"CI": "1"}) and is_ci({"CI": "TRUE"})
    assert not is_ci({"CI": ""}) and not is_ci({}) and not is_ci({"CI": "false"})


def test_missing_binary_raises_loudly_not_silently():
    # A bad binary path is a loud PandocUnavailableError, never a silent no-op.
    assert pandoc_available(binary="/nonexistent/pandoc-xyz") is False
    with pytest.raises(PandocUnavailableError):
        run_pandoc(("--version",), "", binary="/nonexistent/pandoc-xyz")


# ---------------------------------------------------------------------------
# The dispatcher (RI12): internal writer, external deferred, capability-infeasible, plain.
# ---------------------------------------------------------------------------


def test_dispatch_internal_writer_produces_bytes():
    ast = serialize_fitted(_flat_fitted())[0].ast
    out = D.dispatch(D.RenderTarget(writer="markdown", side="internal"), ast)
    assert out.side == "internal" and out.code == "ok"
    assert b"data-fact" in out.output_bytes  # md is an internal record — provenance retained


def test_dispatch_external_is_deferred():
    ast = serialize_fitted(_flat_fitted())[0].ast
    out = D.dispatch(D.RenderTarget(writer="epub3", side="external"), ast)
    assert out.code == D.EXTERNAL_DEFERRED and out.output_bytes is None
    assert out.payload_ast is not None


def test_dispatch_capability_infeasible_internal_bad_writer():
    ast = serialize_fitted(_flat_fitted())[0].ast
    with pytest.raises(D.CapabilityInfeasibleError):
        D.dispatch(D.RenderTarget(writer="epub3", side="internal"), ast)


def test_render_target_from_entry_and_plain_lowering():
    target = D.render_target_from_entry(_RENDER_TARGET)
    assert target.writer == "html5" and target.side == "internal"
    lowered = D.lower_plain(target)
    assert lowered.flags == () and lowered.variables == {} and lowered.assets == ()


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: the serialize plane imports no SSOT.
# ---------------------------------------------------------------------------


def test_serialize_plane_imports_no_ssot():
    root = Path(__file__).resolve().parents[1] / "pipeline"
    files = [
        root / "serialize.py",
        root / "ast_store.py",
        root / "dispatch.py",
        root / "filters" / "provenance_strip.py",
        root / "filters" / "section_attr_validity.py",
    ]
    for path in files:
        tree = ast_mod.parse(path.read_text(encoding="utf-8"))
        for node in ast_mod.walk(tree):
            if isinstance(node, ast_mod.Import):
                assert all("ssot" not in a.name for a in node.names), path.name
            elif isinstance(node, ast_mod.ImportFrom):
                assert node.module is None or "ssot" not in node.module, path.name


# --- extension_for (§7.4, GAP-1c): the layer-2 file extension per output-type ---------------------


class TestExtensionFor:
    """`extension_for` maps an output-type to its conventional layer-2 file extension (NEVER part of
    the id). `md → md` is a no-op for every existing path; an internal html/docx re-render — now
    reachable after GAP-1a — labels its bytes correctly instead of a mislabeled `.md`."""

    @pytest.mark.parametrize(
        "output_type,expected",
        [
            ("md", "md"),
            ("html", "html"),
            ("docx", "docx"),
            ("plain-text", "txt"),
            ("epub", "epub"),
            ("pptx", "pptx"),
            ("pdf", "pdf"),
        ],
    )
    def test_known_output_types_map_to_their_extension(self, output_type, expected):
        assert extension_for(output_type) == expected

    def test_unmapped_valid_slug_defaults_to_itself(self):
        # A new single-run output-type slug labels its bytes with the slug — no second edit.
        assert extension_for("rtf") == "rtf"

    def test_dotted_or_hyphenated_unmapped_slug_fails_loud(self):
        with pytest.raises(SerializeError):
            extension_for("no-such-type")
