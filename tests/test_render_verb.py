"""Step-34 tests: `pipeline.api.render` — the standalone token-free `render` verb (§21.8).

Covers, per the acceptance list (the reconcile/serialize LLM/pandoc legs are an INJECTED fake
engine — NEVER a live subscription call, no `live` marker):

- a fresh baseline render mints the baseline fit + deliverable (`ok`);
- **idempotent re-run**: a same-inputs re-render mints NOTHING (`already-materialized`), the
  store inventory unchanged;
- an UNQUALIFIED render over a none-matching cached fit serves the latest-minted fit +
  `render-input-mismatch` (warn) with the `force-re-reconcile` remedy (§21.8);
- **`force_reconcile` mints a NEW revision fit** (`re-reconciled`), a DISTINCT `_<hex12>` id —
  the OLD baseline fit + its bytes are UNTOUCHED (immutability);
- a re-run of `force_reconcile` with the same inputs resolves the revision as a match
  (`already-materialized`) — no second mint;
- a serialize-input drift over a stable fit AUTO-MINTS a serialize revision (`re-serialized`);
- the resolution decisions ride `pipeline.fit_resolution`/`pipeline.serialize` (orchestrated,
  not reimplemented); the handler owns id/persistence/codes only.
"""

from __future__ import annotations

import pytest

from pipeline import reconcile, serialize
from pipeline.api import render
from pipeline.api.invoke import invoke
from pipeline.ids import parse_id
from pipeline.store import WorkspaceStore

WS = "wsA"
ART = "a-9f3c07d21b44e8aa"
PLATFORM, LANGUAGE, OUTPUT_TYPE, PRESENTATION = "github", "en", "md", "plain"

FIXED_TS = "2024-01-01T00:00:00+00:00"


@pytest.fixture()
def store(tmp_path):
    s = WorkspaceStore(tmp_path / WS)
    s.ensure_layout()
    s.output_path(ART).write_bytes(
        b'{"ir": {"body": "canonical"}, "binding": {"artifact_id": "x"}}\n'
    )
    return s


class FakeRenderEngine:
    """An injected reconcile/serialize seam (stands in for the LLM/pandoc legs): it returns the
    CONFIGURED preimages the resolution rules compare against, and mints REAL fit-/render-bindings
    via `reconcile.build_fit_binding`/`serialize.build_render_binding` (the same builders the
    stage code uses) — no transport, no `claude`, no pandoc."""

    def __init__(self, reconcile_preimage: dict, serialize_preimage: dict, body: bytes = b"BODY\n"):
        self._rp = reconcile_preimage
        self._sp = serialize_preimage
        self._body = body
        self.fit_mints = 0
        self.deliverable_mints = 0

    def reconcile_preimage(self, leg):
        return self._rp

    def mint_fit(self, leg, *, preimage, revision):
        self.fit_mints += 1
        fb = reconcile.build_fit_binding(
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
        return {"body": "fitted"}, fb

    def serialize_preimage(self, leg):
        return self._sp

    def mint_deliverable(self, leg, *, preimage, serialize_revision):
        self.deliverable_mints += 1
        rb = serialize.build_render_binding(
            fitted_id=leg.fitted_id,
            output_type=leg.output_type,
            presentation=leg.presentation,
            preimage=preimage,
            fit_binding_ref={"fitted_id": leg.fitted_id, "digest": "0" * 12},
            serialize_revision=serialize_revision,
            minted_ts=FIXED_TS,
        )
        return self._body, rb, "md"


def _render(store, engine, *, force=False):
    params = {
        "item": ART,
        "platform": PLATFORM,
        "language": LANGUAGE,
        "output_type": OUTPUT_TYPE,
        "presentation": PRESENTATION,
    }
    if force:
        params["force_reconcile"] = True
    handler = render.render_handler(engine=engine)
    return invoke("render", WS, params, store=store, handlers={"render": handler})


def _inventory(store):
    arts = {p.name for p in store.artifacts_dir.iterdir()}
    dels = {p.name for p in store.deliverables_dir.iterdir()}
    return arts | dels


RP_A = {"strategy": {}, "hard-limits": {"max_chars": 500}, "advisory": {}, "render-dims": {}}
RP_B = {"strategy": {}, "hard-limits": {"max_chars": 200}, "advisory": {}, "render-dims": {}}
SP_A = {"tool_bundle": {"pandoc_version": "3.1"}, "render_target": {}, "render_inputs": {}}
SP_B = {"tool_bundle": {"pandoc_version": "3.2"}, "render_target": {}, "render_inputs": {}}


class TestBaselineAndIdempotency:
    def test_fresh_baseline_render_mints_fit_and_deliverable(self, store):
        engine = FakeRenderEngine(RP_A, SP_A)
        out = _render(store, engine)
        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] == "ok"
        assert item["ids"]["fitted_id"] and item["ids"]["deliverable_id"]
        assert parse_id(item["ids"]["fitted_id"]).fit_revision is None  # the baseline fit
        assert engine.fit_mints == 1 and engine.deliverable_mints == 1

    def test_idempotent_rerun_mints_nothing(self, store):
        engine = FakeRenderEngine(RP_A, SP_A)
        _render(store, engine)
        inv = _inventory(store)
        engine2 = FakeRenderEngine(RP_A, SP_A)  # same inputs
        out = _render(store, engine2)
        assert out["results"][0]["code"] == "already-materialized"
        assert engine2.fit_mints == 0 and engine2.deliverable_mints == 0  # no re-mint
        assert _inventory(store) == inv  # the store is byte-for-byte unchanged


class TestUnqualifiedMismatchAndForce:
    def test_unqualified_stale_fit_warns_render_input_mismatch(self, store):
        _render(store, FakeRenderEngine(RP_A, SP_A))  # baseline fit under RP_A
        # Config drifts to RP_B; an UNQUALIFIED render serves the cached fit + the warn (§21.8).
        out = _render(store, FakeRenderEngine(RP_B, SP_A))
        item = out["results"][0]
        assert item["status"] == "warn" and item["code"] == "render-input-mismatch"
        assert item["remediation"]["action"] == "force-re-reconcile"
        assert item["context"]["differing_components"] or item["context"]["current_inputs_digest"]

    def test_force_reconcile_mints_a_new_revision_leaving_the_old_untouched(self, store):
        _render(store, FakeRenderEngine(RP_A, SP_A))  # baseline fit
        baseline_fitted = next(
            p for p in store.artifacts_dir.iterdir() if parse_id(p.name).level == "fitted"
        )
        baseline_bytes = baseline_fitted.read_bytes()

        engine = FakeRenderEngine(RP_B, SP_A)
        out = _render(store, engine, force=True)  # force under the drifted RP_B
        item = out["results"][0]
        assert item["code"] == "re-reconciled" and item["status"] == "ok"
        new_fitted = item["ids"]["fitted_id"]
        assert parse_id(new_fitted).fit_revision is not None  # a REVISION id (…_<hex12>)
        assert new_fitted != baseline_fitted.name  # a DISTINCT id
        assert baseline_fitted.read_bytes() == baseline_bytes  # the OLD fit is byte-identical
        assert engine.fit_mints == 1  # exactly one new revision fit minted

    def test_force_reconcile_rerun_is_already_materialized(self, store):
        _render(store, FakeRenderEngine(RP_A, SP_A))
        _render(store, FakeRenderEngine(RP_B, SP_A), force=True)  # mints the revision
        engine = FakeRenderEngine(RP_B, SP_A)
        out = _render(store, engine, force=True)  # the revision now MATCHES current → no mint
        assert out["results"][0]["code"] == "already-materialized"
        assert engine.fit_mints == 0


class TestSerializeRevision:
    def test_serialize_drift_over_stable_fit_auto_mints_re_serialized(self, store):
        _render(store, FakeRenderEngine(RP_A, SP_A))  # baseline fit + deliverable
        # The fit is stable (RP_A) but the serialize inputs drift (SP_A → SP_B): the render
        # auto-mints a serialize revision — the free, deterministic sibling of re-reconciled.
        engine = FakeRenderEngine(RP_A, SP_B)
        out = _render(store, engine)
        item = out["results"][0]
        assert item["code"] == "re-serialized" and item["status"] == "ok"
        assert parse_id(item["ids"]["deliverable_id"]).serialize_revision is not None
        assert engine.fit_mints == 0  # the fit was a HIT — only the serialize revision minted
        assert engine.deliverable_mints == 1
