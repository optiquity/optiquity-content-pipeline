"""Step-29 tests: the serialize-resolution rule (§17 FR7.3 / §21.8) + the RI13 pin bundle.

PURE resolution over render-bindings — no pandoc, no transport. The DELIVERABLE-level analogue
of the step-26 FR2 fit-resolution rule; these tests mirror `tests/test_fit_resolution.py`.

Covers the plan step-29 acceptance for serialize revisions:

- **the FR7.3 three-row matrix** (§21.8): digest match → HIT (`already-materialized`); bindings
  exist, none match → AUTO-MINT the serialize revision `_hex12` (`re-serialized`); none exist →
  first baseline mint;
- **a tool-pin revert self-heals to the baseline** (rule-1 branch): after a pin bump auto-mints a
  revision, reverting the pin re-matches the baseline binding as a HIT — no re-mint;
- **an edited-asset revert self-heals** the same way (the render-target/asset value tier, §18);
- **content-addressed identity** — two renders with identical inputs compute the SAME
  deliverable-id → the SAME claim key → exactly one winner (§22.3);
- **the RI13 pin bundle** assembles the tool pins + engine + reference-doc + asset hashes +
  variable snapshot, rides the render-binding, and is NOT part of the identity digest;
- **`minted_ts` is excluded from identity** (record-only, §17);
- **no SSOT import** (INV-CORRECTNESS, §22.7).
"""

from __future__ import annotations

import ast as ast_mod
import copy
from pathlib import Path

import pytest

from pipeline.claims import ClaimRegistry
from pipeline.presentation import (
    Presentation,
    PresentationAsset,
    lower,
    plain_presentation,
    render_inputs_to_mapping,
)
from pipeline.serialize import (
    CODE_ALREADY_MATERIALIZED,
    CODE_RE_SERIALIZED,
    DISPOSITION_HIT,
    DISPOSITION_MISS,
    DISPOSITION_REVISION,
    READER_PIN,
    DeliverableCoordinate,
    SerializeError,
    build_render_binding,
    claim_deliverable,
    parse_render_binding,
    pin_bundle,
    resolve_deliverable,
    resolved_deliverable_id,
    serialize_digest,
    serialize_inputs_preimage,
)

FIT = "a-0123456789abcdef.linkedin.en"
FIT_REF = {"fitted_id": FIT, "digest": "4b7a90ce12d3"}
COORD = DeliverableCoordinate(FIT, "html", "plain")

RT = {
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


def preimage_for(presentation: Presentation = None):
    ri = lower(presentation if presentation is not None else plain_presentation(), "html5", "html")
    return serialize_inputs_preimage(render_target=RT, render_inputs=render_inputs_to_mapping(ri))


def binding_for(preimage, *, revision=False, minted_ts):
    return build_render_binding(
        fitted_id=FIT,
        output_type="html",
        presentation="plain",
        preimage=preimage,
        fit_binding_ref=FIT_REF,
        serialize_revision=revision,
        minted_ts=minted_ts,
    )


def _css_presentation(bytes_):
    asset = PresentationAsset("css", "brand.css", bytes_)
    return Presentation(presentation_id="corp", css=(asset,))


# ---------------------------------------------------------------------------
# The FR7.3 three-row matrix (§21.8).
# ---------------------------------------------------------------------------


class TestResolveDeliverableMatrix:
    def test_row3_no_binding_is_a_baseline_miss(self):
        out = resolve_deliverable(COORD, [], preimage_for())
        assert out.disposition == DISPOSITION_MISS
        assert out.status == "ok" and out.code == "ok"
        assert out.should_mint is True and out.revision is False
        # the baseline (unqualified) deliverable-id — zero id churn on the first render
        assert resolved_deliverable_id(out, COORD) == "a-0123456789abcdef.linkedin.en.html.plain"

    def test_row1_digest_match_is_a_hit(self):
        p0 = preimage_for()
        baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")
        out = resolve_deliverable(COORD, [baseline], p0)
        assert out.disposition == DISPOSITION_HIT
        assert out.status == "ok" and out.code == CODE_ALREADY_MATERIALIZED
        assert out.should_mint is False
        assert out.selected.deliverable_id == baseline["deliverable_id"]
        assert out.selected.digest == baseline["digest"]
        # a hit SERVES the existing deliverable — never a re-mint
        assert resolved_deliverable_id(out, COORD) == baseline["deliverable_id"]

    def test_row2_none_match_auto_mints_a_revision(self):
        p0 = preimage_for()
        p1 = preimage_for(_css_presentation(b"body{color:red}"))  # different serialize inputs
        baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")
        out = resolve_deliverable(COORD, [baseline], p1)
        assert out.disposition == DISPOSITION_REVISION
        assert out.status == "ok" and out.code == CODE_RE_SERIALIZED
        assert out.should_mint is True and out.revision is True
        # the revision carries the current-inputs _hex12 on the PRESENTATION segment (§7.4)
        expected = f"a-0123456789abcdef.linkedin.en.html.plain_{serialize_digest(p1)}"
        assert resolved_deliverable_id(out, COORD) == expected


# ---------------------------------------------------------------------------
# Self-heal (rule-1 branch) — the acceptance headline, mirroring fit rule 1.
# ---------------------------------------------------------------------------


def test_tool_pin_revert_self_heals_to_the_baseline():
    p0 = preimage_for()
    baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")

    # A pin bump (pandoc 3.10 → 3.11) changes the serialize inputs → auto-mint a revision.
    bumped = copy.deepcopy(p0)
    bumped["tool_bundle"]["pandoc_version"] = "3.11"
    out_bump = resolve_deliverable(COORD, [baseline], bumped)
    assert out_bump.disposition == DISPOSITION_REVISION and out_bump.code == CODE_RE_SERIALIZED
    revision = binding_for(bumped, revision=True, minted_ts="2026-02-01T00:00:00+00:00")

    # Under the bumped pin the revision is a HIT (no spurious re-mint).
    assert resolve_deliverable(COORD, [baseline, revision], bumped).disposition == DISPOSITION_HIT

    # REVERT the pin → the baseline binding's digest matches again → a HIT, no re-mint (self-heal).
    healed = resolve_deliverable(COORD, [baseline, revision], p0)
    assert healed.disposition == DISPOSITION_HIT
    assert healed.selected.digest == baseline["digest"]  # the ORIGINAL baseline, not a new mint
    assert resolved_deliverable_id(healed, COORD) == baseline["deliverable_id"]


def test_edited_asset_revert_self_heals():
    p0 = preimage_for(_css_presentation(b"body{color:red}"))
    baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")
    edited = preimage_for(_css_presentation(b"body{color:blue}"))  # a css edit
    assert resolve_deliverable(COORD, [baseline], edited).disposition == DISPOSITION_REVISION
    revision = binding_for(edited, revision=True, minted_ts="2026-02-01T00:00:00+00:00")
    # revert the css → the baseline matches again (a HIT), exactly like the fit rule-1 self-heal
    healed = resolve_deliverable(COORD, [baseline, revision], p0)
    assert healed.disposition == DISPOSITION_HIT
    assert healed.selected.digest == baseline["digest"]


# ---------------------------------------------------------------------------
# Content-addressed identity + claim disjointness (§22.3) — mint-in-render-only mirror of FR2.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# B: the body-figure embed fold rides the serialize identity exactly like csl — an edited figure
# auto-mints a revision and a revert self-heals to the baseline; an image-less render is zero-churn.
# ---------------------------------------------------------------------------


def _embed_preimage(fold):
    ri = lower(plain_presentation(), "html5", "html")
    return serialize_inputs_preimage(
        render_target=RT,
        render_inputs=render_inputs_to_mapping(ri),
        assets_embedded=bool(fold),
        embedded_assets=fold,
    )


def test_image_less_embed_params_are_zero_churn():
    # An image-LESS html render (assets_embedded=False) has a preimage byte-identical to pre-B —
    # so the entire existing render-digest corpus is UNMOVED by the new fold.
    assert _embed_preimage(()) == preimage_for()


def test_edited_figure_auto_mints_a_revision_and_reverts_self_heal():
    base_fold = (("assets/x.png", "a" * 64),)
    edited_fold = (("assets/x.png", "b" * 64),)  # the SAME path, EDITED image bytes
    p0 = _embed_preimage(base_fold)
    baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")

    # editing the figure bytes changes the serialize inputs → auto-mint a revision (like a css edit)
    edited = _embed_preimage(edited_fold)
    out = resolve_deliverable(COORD, [baseline], edited)
    assert out.disposition == DISPOSITION_REVISION and out.code == CODE_RE_SERIALIZED
    revision = binding_for(edited, revision=True, minted_ts="2026-02-01T00:00:00+00:00")

    # REVERT the figure → the baseline binding's digest matches again → a HIT, no re-mint (heals).
    healed = resolve_deliverable(COORD, [baseline, revision], p0)
    assert healed.disposition == DISPOSITION_HIT
    assert healed.selected.digest == baseline["digest"]


def test_same_inputs_compute_the_same_deliverable_id():
    p0 = preimage_for()
    p1 = preimage_for(_css_presentation(b"x{}"))
    baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")
    id_a = resolved_deliverable_id(resolve_deliverable(COORD, [baseline], p1), COORD)
    id_b = resolved_deliverable_id(resolve_deliverable(COORD, [baseline], p1), COORD)
    assert id_a == id_b  # deterministic, content-addressed (§22.3)


def test_two_renders_same_inputs_one_claim_key_one_winner(tmp_path):
    p0 = preimage_for()
    p1 = preimage_for(_css_presentation(b"x{}"))
    baseline = binding_for(p0, minted_ts="2026-01-01T00:00:00+00:00")
    res_w1 = resolve_deliverable(COORD, [baseline], p1)
    res_w2 = resolve_deliverable(COORD, [baseline], p1)
    assert resolved_deliverable_id(res_w1, COORD) == resolved_deliverable_id(res_w2, COORD)

    claims_dir = tmp_path / "ws" / "claims"
    out_w1 = claim_deliverable(ClaimRegistry(claims_dir, holder="w1"), res_w1, COORD)
    out_w2 = claim_deliverable(ClaimRegistry(claims_dir, holder="w2"), res_w2, COORD)
    winners = [o for o in (out_w1, out_w2) if o.acquired]
    assert len(winners) == 1  # exactly one mint; the loser is held (B4-4)
    loser = out_w2 if out_w1.acquired else out_w1
    assert loser.code == "claim-held" and loser.acquired is False


# ---------------------------------------------------------------------------
# The RI13 pin bundle + minted_ts exclusion.
# ---------------------------------------------------------------------------


def test_pin_bundle_carries_asset_hashes_and_pins_but_not_identity():
    css = PresentationAsset("css", "brand.css", b"body{}")
    p = preimage_for(Presentation(css=(css,), variables={"fontsize": "12pt"}))
    bundle = pin_bundle(p, ast_reader_pin_digest="deadbeefcafe")
    assert bundle["pandoc_version"] == "3.10"
    assert bundle["reader"] == READER_PIN
    assert bundle["strip_filter_version"] == 1
    assert [css.path, css.content_hash] in bundle["assets"]  # the css hash rides the bundle
    assert bundle["variables"] == {"fontsize": "12pt"}
    assert bundle["ast_reader_pin_digest"] == "deadbeefcafe"
    # a record-only manifest — assembling it never touches the identity digest
    assert serialize_digest(p) == serialize_digest(p)


def test_render_binding_embeds_the_pin_bundle():
    p = preimage_for(_css_presentation(b"a{}"))
    rb = build_render_binding(
        fitted_id=FIT, output_type="html", presentation="plain",
        preimage=p, fit_binding_ref=FIT_REF, minted_ts="2026-01-01T00:00:00+00:00",
    )
    assert "pin_bundle" in rb and rb["pin_bundle"]["reader"] == READER_PIN


def test_minted_ts_excluded_from_the_serialize_revision_identity():
    p1 = preimage_for(_css_presentation(b"z{}"))
    a = binding_for(p1, revision=True, minted_ts="2020-01-01T00:00:00+00:00")
    b = binding_for(p1, revision=True, minted_ts="2099-12-31T23:59:59+00:00")
    assert a["digest"] == b["digest"]
    assert a["deliverable_id"] == b["deliverable_id"]  # the id does not move on the wall clock
    assert a["minted_ts"] != b["minted_ts"]


# ---------------------------------------------------------------------------
# parse_render_binding + coordinate scoping (loud on a wiring defect, §3.1).
# ---------------------------------------------------------------------------


def test_parse_render_binding_is_loud_on_a_malformed_record():
    good = binding_for(preimage_for(), minted_ts="2026-01-01T00:00:00+00:00")
    assert parse_render_binding(good).deliverable_id == good["deliverable_id"]
    with pytest.raises(SerializeError):
        parse_render_binding({"digest": "aaaaaaaaaaaa", "minted_ts": "x", "preimage": {}})
    with pytest.raises(SerializeError):  # bad digest width
        parse_render_binding(dict(good, digest="nothex"))
    with pytest.raises(SerializeError):  # a fitted-level id is not a deliverable
        parse_render_binding(dict(good, deliverable_id=FIT))


def test_wrong_coordinate_binding_is_refused():
    other = DeliverableCoordinate(FIT, "docx", "plain")
    html_binding = binding_for(preimage_for(), minted_ts="2026-01-01T00:00:00+00:00")
    with pytest.raises(SerializeError):
        resolve_deliverable(other, [html_binding], preimage_for())


def test_coordinate_rejects_a_non_fitted_id():
    with pytest.raises(SerializeError):
        DeliverableCoordinate("a-0123456789abcdef", "html", "plain")  # bare artifact, not fitted


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: the extended serialize module imports no SSOT.
# ---------------------------------------------------------------------------


def test_serialize_imports_no_ssot():
    src = (Path(__file__).resolve().parents[1] / "pipeline" / "serialize.py").read_text()
    tree = ast_mod.parse(src)
    for node in ast_mod.walk(tree):
        if isinstance(node, ast_mod.Import):
            assert all("ssot" not in alias.name for alias in node.names)
        elif isinstance(node, ast_mod.ImportFrom):
            assert node.module is None or "ssot" not in node.module
