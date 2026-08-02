"""DR-3 Commit 4 render-through: the emitted `Format=outline` IR is an ORDINARY artifact.

The emit bridge (`pipeline.compose.build_outline_ir`) persists an outline as a plain flat-body
`Format=outline` IR (empty grounding ledger, NO `data-fact` spans). This module proves the
standalone `render` verb (`pipeline.api.render`) READS that envelope, FITS it, and SERIALIZES it
with NO special-casing (S5 / Part-D: a flat body has no part circularity; `outline` is
non-parametric) — i.e. it renders exactly like any other artifact.

`pipeline/api/render.py` is UNCHANGED by DR-3 Commit 4 (verify-only): the outline reuses the exact
render path. The reconcile/serialize legs ride an INJECTED fake engine — the SAME injection pattern
as `tests/test_render_verb.py` (the render-verb test module the plan names `test_api_render.py`):
it returns configured preimages and mints REAL fit-/render-bindings, so NO live subscription call,
NO network, and NO pandoc runs here. The internal/external SIDE is the render-target's, read from
the REAL framework registry (`_registry_side`) so the "plain-text/html -> internal bytes, epub ->
external RI14 payload" assertions are NOT vacuous, and is mirrored by the injected engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import ir, reconcile, serialize
from pipeline.api import render
from pipeline.api.invoke import invoke
from pipeline.compose import build_outline_ir
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.outline import normalize_outline, outline_digest
from pipeline.store import WorkspaceStore
from pipeline.yamlio import load_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "ws-outline"
USER = "acme"
COMMIT_SHA = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"
PLATFORM, LANGUAGE, PRESENTATION = "github", "en", "plain"
FIXED_TS = "2024-01-01T00:00:00+00:00"
OUTLINE_MD = "# Launch outline\n\n- Problem\n- Approach\n- Ship\n"

#: The injected-engine preimages the resolution rules compare against (mirrors `test_render_verb`):
#: a fresh render sees no prior binding, so both legs mint once.
RP = {"strategy": {}, "hard-limits": {"max_chars": 500}, "advisory": {}, "render-dims": {}}
SP = {"tool_bundle": {"pandoc_version": "3.1"}, "render_target": {}, "render_inputs": {}}

#: A well-formed external RI14 contract payload (the five components §17 RI14 requires) — what an
#: external render-target's serialize leg hands off; here returned by the injected engine.
_EXTERNAL_PAYLOAD = {
    "ast": {"pandoc-api-version": [1, 23, 1, 2], "blocks": [], "meta": {}},
    "reproducibility": {"pins": {}},
    "parts": [],
    "metadata": {},
    "language": "en",
}


def _outline_preimage(md: str) -> dict:
    """The §7.2 preimage for a `Format=outline` artifact carrying the R4 own-body outline-digest —
    exactly what Commit 6 constructs and hands the emit bridge."""
    return build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("outline"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
        outline_digest=outline_digest(md),
    )


def _registry_side(output_type: str) -> str:
    """The `side:` the REAL framework render-target registry declares for `output_type` — the
    ground truth the injected engine mirrors (keeps the internal/external assertions honest)."""
    text = (REPO_ROOT / "render-targets" / f"{output_type}.md").read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(text)
    return frontmatter["side"]


@pytest.fixture()
def outline_store(tmp_path):
    """A workspace store carrying ONE emitted `Format=outline` artifact — the `item` a render
    resolves. Returns (store, artifact_id)."""
    store = WorkspaceStore.at(tmp_path, USER, WS)
    store.ensure_layout()
    preimage = _outline_preimage(OUTLINE_MD)
    artifact_id = mint_artifact_id(preimage)
    build_outline_ir(OUTLINE_MD, artifact_id=artifact_id, preimage=preimage, store=store)
    return store, artifact_id


class _FakeOutlineRenderEngine:
    """The injected reconcile/serialize seam (mirrors `test_render_verb.FakeRenderEngine`): it
    returns the configured preimages and mints REAL fit-/render-bindings via the SAME builders the
    stage code uses (`reconcile.build_fit_binding` / `serialize.build_render_binding`) — no
    transport, no `claude`, no pandoc. `side` selects an internal (layer-2 bytes) or external (RI14
    payload) deliverable mint, mirroring the render-target the coordinate names."""

    def __init__(self, side: str):
        self._side = side
        self.fit_mints = 0
        self.deliverable_mints = 0

    def reconcile_preimage(self, leg):
        return RP

    def mint_fit(self, leg, *, preimage, revision):
        self.fit_mints += 1
        fit_binding = reconcile.build_fit_binding(
            artifact_id=leg.item,
            platform=leg.platform,
            language=leg.language,
            preimage=preimage,
            strategy="pass",
            localize_languages=[],
            gate_outcome="ok",
            revision=revision,
            minted_ts=FIXED_TS,
        )
        # the fitted IR is the outline body, still a flat single-part envelope (no reshape).
        return {"body": normalize_outline(OUTLINE_MD)}, fit_binding

    def serialize_preimage(self, leg):
        return SP

    def mint_deliverable(self, leg, *, preimage, serialize_revision):
        self.deliverable_mints += 1
        render_binding = serialize.build_render_binding(
            fitted_id=leg.fitted_id,
            output_type=leg.output_type,
            presentation=leg.presentation,
            preimage=preimage,
            fit_binding_ref={"fitted_id": leg.fitted_id, "digest": "0" * 12},
            serialize_revision=serialize_revision,
            minted_ts=FIXED_TS,
        )
        if self._side == "external":
            return render.MintOutcome(
                binding=render_binding,
                side="external",
                payload=dict(_EXTERNAL_PAYLOAD),
                stripped=True,
            )
        return render.MintOutcome(
            binding=render_binding,
            side="internal",
            output_bytes=b"OUTLINE DELIVERABLE BYTES\n",
            extension="txt",
        )


def _render(store, artifact_id, engine, output_type):
    handler = render.render_handler(engine=engine)
    params = {
        "item": artifact_id,
        "platform": PLATFORM,
        "language": LANGUAGE,
        "output_type": output_type,
        "presentation": PRESENTATION,
    }
    return invoke("render", WS, USER, params, store=store, handlers={"render": handler})


class TestOutlineRendersAsOrdinaryArtifact:
    """The emitted outline flows through the UNCHANGED render path (`api/render.py` verify-only)."""

    def test_render_reads_the_emitted_outline_envelope(self, outline_store):
        # The emit persisted a RAW IR envelope (flat body, no `ir` wrapper); the render reader
        # unwraps it via `ir.unwrap_ir` exactly like any composed artifact — NOT a 404.
        store, artifact_id = outline_store
        record = render._read_record(store, artifact_id)
        assert record is not None
        unwrapped = ir.unwrap_ir(record)
        assert unwrapped["body"] == normalize_outline(OUTLINE_MD)
        assert unwrapped["grounding"] == {} and "data-fact" not in unwrapped["body"]

    @pytest.mark.parametrize("output_type", ["plain-text", "html"])
    def test_outline_renders_to_internal_bytes(self, outline_store, output_type):
        # An INTERNAL render-target (plain-text/html) yields layer-2 bytes — the outline fits and
        # serializes as an ordinary artifact.
        store, artifact_id = outline_store
        assert _registry_side(output_type) == "internal"  # the real registry declares internal
        engine = _FakeOutlineRenderEngine("internal")
        out = _render(store, artifact_id, engine, output_type)

        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] == "ok"
        assert item.get("code") != "not-found"
        assert item["ids"]["fitted_id"] and item["ids"]["deliverable_id"]
        assert item.get("output") is not None  # a layer-2 bytes path (internal side)
        assert engine.fit_mints == 1 and engine.deliverable_mints == 1
        deliverable_id = item["ids"]["deliverable_id"]
        record = render._read_record(store, deliverable_id)
        assert record is not None and "layer2" in record  # bytes + render-binding record

    def test_outline_renders_to_external_epub_payload(self, outline_store):
        # An EXTERNAL render-target (epub) yields a `side:external` RI14 contract payload and NO
        # layer-2 bytes — the same external handoff any artifact takes (§17 RI14 / GAP-1b).
        store, artifact_id = outline_store
        assert _registry_side("epub") == "external"  # the real registry declares external
        engine = _FakeOutlineRenderEngine("external")
        out = _render(store, artifact_id, engine, "epub")

        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] != "block" and item.get("code") != "not-found"
        assert item.get("output") is None  # external -> no layer-2 bytes in the result
        deliverable_id = item["ids"]["deliverable_id"]
        record = render._read_record(store, deliverable_id)
        assert record is not None
        assert set(record) == {"binding", "side", "payload", "stripped"}
        assert record["side"] == "external"
        assert set(record["payload"]) == {"ast", "reproducibility", "parts", "metadata", "language"}
        # no layer-2 bytes sibling — an external deliverable is retrieved via fetch-by-id.
        assert not list(store.deliverables_dir.glob(f"{deliverable_id}.*"))
