"""DR-3 `emit-outline` verb: a HAND-AUTHORED outline + a target coordinate -> a byte-faithful
`Format=outline` artifact, minted + persisted and returned by artifact-id (horn (a) / B1).

This is the OUTPUT sibling of the outline-as-INPUT drive path. It wires the already-built
`build_outline_ir` (Commit 4) + `outline_store.put_outline` (Commit 5) + the `outline-digest`
preimage extension (Commit 2) through the dispatch, and proves the emitted artifact is ORDINARY:
it renders + fetches through the UNCHANGED `render`/`fetch-by-id` verbs.

Runs against the REAL shipped registries (copied into `tmp_path` — the repo is read-only toward
this suite), so `resolve_compose` (with `format` FIXED = `outline`) binds real entries. The
reconcile/serialize legs ride an INJECTED fake engine (the SAME pattern as `test_api_render.py` /
`test_render_verb.py`): NO live subscription call, NO network, NO pandoc.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline import ir, reconcile, serialize
from pipeline.api import fetch, render
from pipeline.api.invoke import KNOWN_VERBS, invoke
from pipeline.ids import parse_id
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.outline import normalize_outline, outline_digest
from pipeline.outline_store import get_outline, outline_path
from pipeline.store import WorkspaceStore
from pipeline.yamlio import load_frontmatter

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
RECIPE = "explainer-post"
TOPIC_ID = "x-t-alpha"
FIXED_TS = "2024-01-01T00:00:00+00:00"
PLATFORM, LANGUAGE, PRESENTATION = "github", "en", "plain"

OUTLINE_MD = "# Launch outline\n\n- Problem\n- Approach\n- Ship\n"
#: A COSMETIC edit (trailing whitespace, CRLF, extra blank runs) — N normalizes it away, so the
#: outline-digest (and hence the emitted id) is UNCHANGED.
OUTLINE_COSMETIC = "# Launch outline  \r\n\r\n\r\n- Problem   \r\n- Approach\r\n- Ship\r\n\r\n"
#: A SUBSTANTIVE edit — a different normalized body, a different digest, a different id.
OUTLINE_DIFFERENT = "# Different outline\n\n- Other\n- Beats\n"

#: The injected-engine preimages the resolution rules compare against (mirrors test_api_render):
RP = {"strategy": {}, "hard-limits": {"max_chars": 500}, "advisory": {}, "render-dims": {}}
SP = {"tool_bundle": {"pandoc_version": "3.1"}, "render_target": {}, "render_inputs": {}}
_EXTERNAL_PAYLOAD = {
    "ast": {"pandoc-api-version": [1, 23, 1, 2], "blocks": [], "meta": {}},
    "reproducibility": {"pins": {}},
    "parts": [],
    "metadata": {},
    "language": "en",
}


# --- fixtures ---------------------------------------------------------------------------------


def build_root(tmp_path: Path, *, l2: str = BASE_L2) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (REC-3 read-only)."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(l2, encoding="utf-8")
    topics_dir = root / "users" / USER / "zones" / "default" / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    (topics_dir / f"{TOPIC_ID}.md").write_text(
        TOPIC.format(tid=TOPIC_ID, why="First."), encoding="utf-8"
    )
    return root


def store_for(root: Path) -> WorkspaceStore:
    store = WorkspaceStore.at(root, USER, WS, zone="default")
    store.ensure_layout()
    return store


@pytest.fixture(autouse=True)
def _clean_registry():
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


@pytest.fixture()
def root(tmp_path):
    return build_root(tmp_path)


@pytest.fixture()
def store(root):
    return store_for(root)


def emit(root: Path, store: WorkspaceStore, **params) -> dict:
    return invoke(
        "emit-outline",
        WS,
        USER,
        params,
        store=store,
        root=str(root),
        handlers={"emit-outline": session.emit_outline_handler()},
    )


def coord(**over) -> dict:
    base = {"outline": OUTLINE_MD, "recipe": RECIPE, "topic": TOPIC_ID}
    base.update(over)
    return base


def _one(out: dict) -> dict:
    assert out["envelope"]["ok"] is True, out
    assert len(out["results"]) == 1, out
    return out["results"][0]


# --- the fake render engine (no live call) ----------------------------------------------------


def _registry_side(output_type: str) -> str:
    rt = registry_dir(REPO_ROOT, "render-targets") / f"{output_type}.md"
    text = rt.read_text(encoding="utf-8")
    frontmatter, _ = load_frontmatter(text)
    return frontmatter["side"]


class _FakeOutlineRenderEngine:
    """Mirrors `test_api_render._FakeOutlineRenderEngine`: returns configured preimages and mints
    REAL fit-/render-bindings — no transport, no pandoc. `side` selects internal (layer-2 bytes)
    or external (RI14 payload) mint."""

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
                binding=render_binding, side="external",
                payload=dict(_EXTERNAL_PAYLOAD), stripped=True,
            )
        return render.MintOutcome(
            binding=render_binding, side="internal",
            output_bytes=b"OUTLINE DELIVERABLE BYTES\n", extension="txt",
        )


def _render(store, artifact_id, engine, output_type) -> dict:
    params = {
        "item": artifact_id, "platform": PLATFORM, "language": LANGUAGE,
        "output_type": output_type, "presentation": PRESENTATION,
    }
    return invoke(
        "render", WS, USER, params, store=store,
        handlers={"render": render.render_handler(engine=engine)},
    )


# --- tests ------------------------------------------------------------------------------------


class TestVerbResolves:
    def test_emit_outline_is_a_known_verb_and_discoverable(self):
        from pipeline.api import discovery

        assert "emit-outline" in KNOWN_VERBS
        assert "emit-outline" in {v["verb"] for v in discovery._list_verbs()}

    def test_registered_by_register_api_handlers(self):
        session.register_api_handlers()
        assert "emit-outline" in invoke_mod._VERB_HANDLERS


class TestEmitProducesOrdinaryOutlineArtifact:
    def test_emit_returns_a_format_outline_artifact_id(self, root, store):
        item = _one(emit(root, store, **coord()))
        assert item["status"] == "ok" and item.get("code") is None
        aid = item["ids"]["artifact_id"]
        assert parse_id(aid).family == "artifact"

        # the persisted IR is an ORDINARY flat-body artifact; body == N(md) byte-for-byte.
        record = render._read_record(store, aid)
        doc = ir.unwrap_ir(record)
        assert doc["body"] == normalize_outline(OUTLINE_MD)
        assert doc["grounding"] == {} and "data-fact" not in doc["body"]
        # Format is fixed = outline; the id RIDES the outline-digest (R4 own-body, Commit-2).
        assert doc["binding"]["preimage"]["dimensions"]["format"]["entry"] == "outline"
        assert doc["binding"]["preimage"]["outline-digest"] == outline_digest(OUTLINE_MD)
        ir.validate_ir(record)  # accepts it with no special-casing

    def test_edited_bytes_are_stored_in_the_pre_compose_outline_store(self, root, store):
        _one(emit(root, store, **coord()))
        digest = outline_digest(OUTLINE_MD)
        assert outline_path(store, digest).exists()
        assert get_outline(store, digest) == normalize_outline(OUTLINE_MD)


class TestRendersAndFetchesThroughExistingVerbs:
    @pytest.mark.parametrize("output_type", ["plain-text", "html"])
    def test_outline_renders_to_internal_bytes(self, root, store, output_type):
        aid = _one(emit(root, store, **coord()))["ids"]["artifact_id"]
        assert _registry_side(output_type) == "internal"
        engine = _FakeOutlineRenderEngine("internal")
        item = _one(_render(store, aid, engine, output_type))
        assert item["status"] == "ok" and item.get("code") != "not-found"
        assert item["ids"]["fitted_id"] and item["ids"]["deliverable_id"]
        assert item.get("output") is not None
        assert engine.fit_mints == 1 and engine.deliverable_mints == 1

    def test_outline_renders_to_external_epub_payload(self, root, store):
        aid = _one(emit(root, store, **coord()))["ids"]["artifact_id"]
        assert _registry_side("epub") == "external"
        item = _one(_render(store, aid, _FakeOutlineRenderEngine("external"), "epub"))
        assert item["status"] != "block" and item.get("code") != "not-found"
        assert item.get("output") is None  # external -> no layer-2 bytes in the result
        record = render._read_record(store, item["ids"]["deliverable_id"])
        assert set(record) == {"binding", "side", "payload", "stripped"}
        assert record["side"] == "external"

    def test_fetch_by_id_returns_the_emitted_artifact(self, root, store):
        aid = _one(emit(root, store, **coord()))["ids"]["artifact_id"]
        out = invoke(
            "fetch-by-id", WS, USER, {"id": aid}, store=store,
            handlers={"fetch-by-id": fetch.fetch_handler()},
        )
        item = _one(out)
        assert item["status"] == "ok" and item["ids"]["id"] == aid
        assert item["output"]["path"]  # the stored IR record path (dumb retrieval, no mint)


class TestIdentityDiscipline:
    def test_two_different_outlines_same_coordinate_get_different_ids(self, root, store):
        a = _one(emit(root, store, **coord(outline=OUTLINE_MD)))["ids"]["artifact_id"]
        b = _one(emit(root, store, **coord(outline=OUTLINE_DIFFERENT)))["ids"]["artifact_id"]
        assert a != b  # the id rides the outline-digest -> a different body -> a different id

    def test_cosmetic_edit_same_coordinate_gets_the_same_id(self, root, store):
        a = _one(emit(root, store, **coord(outline=OUTLINE_MD)))["ids"]["artifact_id"]
        # a cosmetic edit N-normalizes to the same body -> same digest -> same id -> idempotent.
        item = _one(emit(root, store, **coord(outline=OUTLINE_COSMETIC)))
        assert item["ids"]["artifact_id"] == a
        assert item["code"] == "already-materialized"  # the no-op re-emit

    def test_re_emit_same_outline_is_already_materialized_no_op(self, root, store):
        first = _one(emit(root, store, **coord()))
        assert first.get("code") is None  # fresh mint -> plain ok
        aid = first["ids"]["artifact_id"]
        before = render._read_record(store, aid)
        second = _one(emit(root, store, **coord()))
        assert second["code"] == "already-materialized"
        assert second["ids"]["artifact_id"] == aid
        assert render._read_record(store, aid) == before  # winner's bytes untouched (§22.7)

    def test_a_different_coordinate_gets_a_different_id(self, root, store):
        a = _one(emit(root, store, **coord()))["ids"]["artifact_id"]
        b = _one(emit(root, store, **coord(persona="product-manager")))["ids"]["artifact_id"]
        assert a != b  # the coordinate is an identity input alongside the outline-digest


class TestRefusalsAreTypedNotCrashes:
    def test_empty_outline_is_a_typed_block_and_not_persisted(self, root, store):
        out = emit(root, store, **coord(outline="   \n\n  \n"))
        assert out["envelope"]["ok"] is True  # a per-item block never fails the batch (SM1)
        item = out["results"][0]
        assert item["status"] == "block" and item.get("code") is None
        assert "outline-empty-substance" in item["remediation"]["hint"]
        # nothing minted, nothing in the outline store.
        assert not any(store.artifacts_dir.iterdir())
        outlines = store.root / "outlines"
        assert not outlines.exists() or not any(outlines.iterdir())

    def test_secret_shaped_outline_is_a_typed_block_and_not_persisted(self, root, store):
        secret = "# Outline\n\n- token: sk-ABCDEFGHIJKLMNOPQRSTUVWX0123456789abcdef01\n"
        out = emit(root, store, **coord(outline=secret))
        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] == "block" and item.get("code") is None
        assert "outline-secret-shaped-value" in item["remediation"]["hint"]
        assert not any(store.artifacts_dir.iterdir())

    def test_missing_outline_is_a_typed_block(self, root, store):
        out = emit(root, store, recipe=RECIPE, topic=TOPIC_ID)
        item = out["results"][0]
        assert out["envelope"]["ok"] is True
        assert item["status"] == "block" and item["item"] == "emit-outline"

    def test_missing_recipe_is_a_typed_block(self, root, store):
        out = emit(root, store, outline=OUTLINE_MD, topic=TOPIC_ID)
        item = out["results"][0]
        assert item["status"] == "block" and "recipe" in item["remediation"]["hint"]
