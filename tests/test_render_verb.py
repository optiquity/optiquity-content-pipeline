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

import ast as ast_mod
import json
import shutil
from pathlib import Path

import pytest

from pipeline import ids, mvpdemo, reconcile, serialize
from pipeline.api import render
from pipeline.api.invoke import invoke
from pipeline.claims import ClaimRegistry
from pipeline.filters.provenance_strip import has_provenance
from pipeline.ids import parse_id
from pipeline.lint import REGISTRY_ROOTS
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate
from pipeline.store import WorkspaceStore

WS = "wsA"
USER = "acme"
ART = "a-9f3c07d21b44e8aa"
PLATFORM, LANGUAGE, OUTPUT_TYPE, PRESENTATION = "github", "en", "md", "plain"

FIXED_TS = "2024-01-01T00:00:00+00:00"


@pytest.fixture()
def store(tmp_path):
    # `.at(...)` records identity so the render resolver recovers the framework root loudly (§23).
    s = WorkspaceStore.at(tmp_path, USER, WS)
    s.ensure_layout()
    # GAP-1a: the RAW compose envelope shape (top-level `body`/`binding`, NO `ir` wrapper) — exactly
    # what `compose.py` persists. The read now unwraps this via `ir.unwrap_ir`; the old wrapped
    # `{"ir": …}` fixture masked the bug where `render` 404'd every real composed artifact.
    s.output_path(ART).write_bytes(
        b'{"body": "canonical", "binding": {"artifact_id": "x"}}\n'
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
        # C6: the seam returns a side-tagged `MintOutcome` (the fake is INTERNAL — layer-2 bytes).
        return render.MintOutcome(
            binding=rb, side="internal", output_bytes=self._body, extension="md"
        )


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
    return invoke("render", WS, USER, params, store=store, handlers={"render": handler})


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


class TestRawEnvelopeBaselineRead:
    """GAP-1a: a RAW compose envelope baseline (no `ir` wrapper — the real persisted shape) is READ,
    not 404'd. Before the fix the `"ir" not in record` gate rejected every real composed
    artifact."""

    def test_raw_envelope_baseline_is_read_not_not_found(self, store):
        out = _render(store, FakeRenderEngine(RP_A, SP_A))
        item = out["results"][0]
        assert item["status"] != "block"
        assert item.get("code") != "not-found"
        assert item["ids"]["fitted_id"] and item["ids"]["deliverable_id"]


class FakeExternalRenderEngine(FakeRenderEngine):
    """A fake seam whose deliverable mint is EXTERNAL — it returns a 5-key contract `payload` and
    NO layer-2 bytes, so `_render`'s external glue (`_persist_external_payload`, `output=None`) is
    driven END TO END (Cleanup #1). It routes on the OUTCOME's `side`, not the output-type, so the
    default `md` coordinate still exercises the external branch — this locks the ROUTING/persist
    glue, while the C6 real-engine tests below lock the real `payload.build_payload`."""

    _PAYLOAD = {
        "ast": {"pandoc-api-version": [1, 23, 1, 2], "blocks": [], "meta": {}},
        "reproducibility": {"pins": {}},
        "parts": [],
        "metadata": {},
        "language": "en",
    }

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
        return render.MintOutcome(
            binding=rb, side="external", payload=dict(self._PAYLOAD), stripped=True
        )


class TestExternalGlueEndToEnd:
    """Cleanup #1 (reviewB coverage gap): drive `_render`'s EXTERNAL branch END TO END through
    `invoke` → the render handler, closing the ~3-line external glue (render.py:252-253) the C6
    unit tests exercised only by calling `mint_deliverable`/`_persist_external_payload` directly."""

    def test_external_mint_persists_contract_record_and_emits_no_output(self, store):
        engine = FakeExternalRenderEngine(RP_A, SP_A)
        out = _render(store, engine)

        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] != "block"
        assert item.get("output") is None  # external → NO layer-2 bytes path in the result
        assert engine.deliverable_mints == 1
        deliverable_id = item["ids"]["deliverable_id"]

        # The `_persist_external_payload` glue ran: the persisted record is EXACTLY the
        # {binding, side, payload, stripped} shape (mvpdemo._mint_external's hard invariant).
        record = render._read_record(store, deliverable_id)
        assert record is not None
        assert set(record) == {"binding", "side", "payload", "stripped"}
        assert record["side"] == "external"
        assert record["stripped"] is True
        assert record["binding"]["deliverable_id"] == deliverable_id
        assert set(record["payload"]) == {"ast", "reproducibility", "parts", "metadata", "language"}
        # No layer-2 bytes sibling was written — an external deliverable is retrieved via
        # fetch-by-id (the record), never a bytes file (§21.5/§21.8).
        assert not list(store.deliverables_dir.glob(f"{deliverable_id}.*"))


# ---------------------------------------------------------------------------
# C6 (GAP-1b): REAL-engine external routing + `MintOutcome` — the highest-blast edit.
#
# The three tests below drive the REAL `DefaultRenderEngine` (NOT the fake), exercising the
# external branch (`dispatch` → `payload.build_payload`) and the internal branch that every
# fake-injected test above BYPASSES. All ride the repo pandoc skip-guard (F2): `serialize_fitted`
# shells the pinned pandoc READER both sides, so absent pandoc ⇒ skip locally / FAIL in CI. The
# external dispatch itself is pure-Python (persist AST + hand off) — the pandoc dependency is the
# reader, not an epub/pptx binary.
# ---------------------------------------------------------------------------

_PANDOC_AVAILABLE = pandoc_available()

#: A flat single-body fitted IR → exactly ONE serialized document (the standalone-render
#: contract), carrying provenance on its one claim so the zero-provenance guarantee is a REAL
#: strip, never vacuous.
_C6_LEDGER = {
    "f0": {
        "tier": "EXTRACTED",
        "source_instance_id": "repo-a",
        "source_commit": "abc123def456",
        "traceability_anchor": ["src/limits.py:42"],
    }
}
_C6_FITTED_IR = {
    "grounding": _C6_LEDGER,
    "metadata": {"campaign": "q3", "client": "acme"},
    "body": 'Rate [100 req/s]{.EXTRACTED data-fact="f0"} holds.',
}
_C6_PLATFORM, _C6_LANGUAGE, _C6_PRESENTATION = "github", "en", "plain"
#: A §7.4-valid workspace slug ([a-z0-9-]) — the REAL `CascadeEnv`/`Resolver` validate it (the
#: fake-engine tests reuse the uppercase `WS` only because they never build a `CascadeEnv`).
_C6_WS = "ws-a"


@pytest.fixture
def require_pandoc():
    """PA-12 guard (only the real-engine C6 tests request it — the fake-engine tests above run
    pandoc-free): absent + CI ⇒ FAIL loudly; absent locally ⇒ skip; present ⇒ run."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the real-engine render tests serialize real bytes and "
            "MUST run in CI (PA-12); a silent skip cannot make CI green",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the real-engine render tests require the pinned binary")


def _mvpdemo_external_record_keys() -> set[str]:
    """The top-level key set `mvpdemo._mint_external` persists to disk (via `_persist_record`,
    which writes the record dict verbatim), extracted from its SOURCE by AST so the shape-equality
    test is genuinely coupled to the OTHER external-record producer — a mvpdemo drift fails it (the
    GAP-1b hard invariant), never a hand-copied literal that silently rots."""
    src = Path(mvpdemo.__file__).read_text()
    tree = ast_mod.parse(src)
    fn = next(
        node
        for node in ast_mod.walk(tree)
        if isinstance(node, ast_mod.FunctionDef) and node.name == "_mint_external"
    )
    wanted = {"binding", "side", "payload", "stripped"}
    matches = [
        {k.value for k in node.keys if isinstance(k, ast_mod.Constant)}
        for node in ast_mod.walk(fn)
        if isinstance(node, ast_mod.Dict)
        and wanted <= {k.value for k in node.keys if isinstance(k, ast_mod.Constant)}
    ]
    assert len(matches) == 1, (
        "mvpdemo._mint_external must persist exactly one {binding,side,payload,stripped} record"
    )
    return matches[0]


def _c6_world(tmp_path):
    """R-C6-SCAFFOLD: a framework root (real registries) + a tmp workspace store + a stored fitted
    IR + its fit-record binding — the minimum the REAL `DefaultRenderEngine` reads to mint one
    deliverable. Mirrors `mvpdemo`/`test_mvp_scenario.build_world` (REC-3: all under tmp_path)."""
    repo_root = Path(__file__).resolve().parents[1]
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = repo_root / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(
        "voice: clear-explainer\nlanguage: en\noutput_type: md\n", encoding="utf-8"
    )
    store = WorkspaceStore.at(root, USER, _C6_WS)
    store.ensure_layout()
    fitted_id = ids.fitted_id(ART, _C6_PLATFORM, _C6_LANGUAGE)
    # The fit record the engine reads for the fit-binding ref (`_read_record(store, fitted_id)`).
    store.output_path(fitted_id).write_bytes(
        json.dumps(
            {"ir": _C6_FITTED_IR, "binding": {"fitted_id": fitted_id, "digest": "0" * 12}}
        ).encode()
        + b"\n"
    )
    return root, store, fitted_id


def _c6_leg(root, store, fitted_id, output_type):
    return render.SerializeLeg(
        root=root,
        user=USER,
        workspace=_C6_WS,
        store=store,
        fitted_id=fitted_id,
        fitted_ir=_C6_FITTED_IR,
        output_type=output_type,
        presentation=_C6_PRESENTATION,
    )


class TestC6ExternalRoutingAndMintOutcome:
    """C6: the REAL engine routes an external output-type to a zero-provenance contract payload
    and an internal one to layer-2 bytes; the persisted external record matches
    `mvpdemo._mint_external`. These lock the one Protocol change others implement (R-SEQ)."""

    def test_real_external_branch_produces_zero_provenance_payload(self, tmp_path, require_pandoc):
        root, store, fitted_id = _c6_world(tmp_path)
        engine = render.DefaultRenderEngine()
        leg = _c6_leg(root, store, fitted_id, "epub")  # the epub render-target is side: external
        preimage = engine.serialize_preimage(leg)
        mint = engine.mint_deliverable(leg, preimage=preimage, serialize_revision=False)

        assert isinstance(mint, render.MintOutcome)
        assert mint.side == "external"
        assert mint.output_bytes is None and mint.extension is None  # external has NO layer-2 bytes
        assert mint.payload is not None
        # The zero-provenance layer-3 contract payload (§17 RI14) with all five components.
        assert set(mint.payload) == {"ast", "reproducibility", "parts", "metadata", "language"}
        assert has_provenance(mint.payload["ast"]) is False
        blob = json.dumps(mint.payload)
        for token in ("data-fact", "data-source", "EXTRACTED", "data-"):
            assert token not in blob, f"provenance token {token!r} leaked into the external payload"
        # The binding fixes the resolved deliverable-id for this coordinate.
        assert mint.binding["deliverable_id"] == ids.deliverable_id(
            fitted_id, "epub", _C6_PRESENTATION
        )

    def test_real_internal_branch_produces_layer2_bytes(self, tmp_path, require_pandoc):
        root, store, fitted_id = _c6_world(tmp_path)
        engine = render.DefaultRenderEngine()
        leg = _c6_leg(root, store, fitted_id, "md")  # the md render-target is side: internal
        preimage = engine.serialize_preimage(leg)
        mint = engine.mint_deliverable(leg, preimage=preimage, serialize_revision=False)

        assert mint.side == "internal"
        assert mint.payload is None
        assert isinstance(mint.output_bytes, bytes) and mint.output_bytes  # real pandoc bytes
        assert mint.extension == "md"  # locks the C4 extension_for on the internal path
        assert mint.binding["deliverable_id"] == ids.deliverable_id(
            fitted_id, "md", _C6_PRESENTATION
        )

    def test_persist_external_payload_matches_mvpdemo_shape(self, tmp_path, require_pandoc):
        root, store, fitted_id = _c6_world(tmp_path)
        engine = render.DefaultRenderEngine()
        leg = _c6_leg(root, store, fitted_id, "epub")
        preimage = engine.serialize_preimage(leg)
        mint = engine.mint_deliverable(leg, preimage=preimage, serialize_revision=False)
        deliverable_id = mint.binding["deliverable_id"]

        render._persist_external_payload(store, deliverable_id, mint)
        record = render._read_record(store, deliverable_id)
        assert record is not None
        # HARD INVARIANT: the persisted external record's top-level shape EQUALS the shape
        # `mvpdemo._mint_external` writes — so the ONE fetch-by-id/emit-manifest reader handles
        # both producers identically.
        assert (
            set(record)
            == _mvpdemo_external_record_keys()
            == {"binding", "side", "payload", "stripped"}
        )
        assert record["side"] == "external"
        assert isinstance(record["stripped"], bool)
        assert record["binding"]["deliverable_id"] == deliverable_id
        assert set(record["payload"]) == {"ast", "reproducibility", "parts", "metadata", "language"}


# ---------------------------------------------------------------------------
# GAP-10: the render check-then-mint double-spend race is closed by wiring the §22.3 claim
# primitives (`fit_resolution.claim_fit`/`serialize.claim_deliverable`) around the two paid
# mints — the SAME acquire→work→release the generate-next spine runs. These lock: (1) two
# concurrent identical renders → EXACTLY ONE runs the paid mint, the other gets the re-drivable
# `claim-held`; (2) the claim is `peek`-live DURING the mint; (3) a mint that raises `_EngineError`
# releases in the `finally` (no dangling claim); (4) the cache-hit path acquires NO claim and is
# byte-identical (behaviour-neutral happy path).
#
# Concurrency is driven DETERMINISTICALLY via re-entrancy: a fake engine fires a SECOND `render`
# from INSIDE the first render's `mint_*` — i.e. while the first render provably holds the live
# claim — so the second contender must observe the claim held. No threads, fully hermetic.
# ---------------------------------------------------------------------------


def _snapshot(store):
    """Every file under the store root → bytes (output artifacts, bindings, claims). A released
    claim leaves NO file, so a behaviour-neutral render round-trips to an identical snapshot."""
    return {
        str(p.relative_to(store.root)): p.read_bytes()
        for p in sorted(store.root.rglob("*"))
        if p.is_file()
    }


class _CountingRegistry:
    """A thin spy over a real `ClaimRegistry` that counts `acquire` calls — proves the cache-hit
    path acquires NO claim. Delegates `release`/`peek` to the wrapped registry unchanged."""

    def __init__(self, inner: ClaimRegistry):
        self.inner = inner
        self.acquires = 0

    def acquire(self, id_str):
        self.acquires += 1
        return self.inner.acquire(id_str)

    def release(self, id_str):
        return self.inner.release(id_str)

    def peek(self, id_str):
        return self.inner.peek(id_str)


class TestGap10RenderClaimDoubleSpend:
    def test_two_concurrent_fit_mints_only_one_runs_the_other_claim_held(self, store):
        """A SECOND identical render fired while the FIRST holds the live fit claim must get
        `claim-held` and spend NOTHING — exactly one `mint_fit` runs (no double-spend)."""
        inner = FakeRenderEngine(RP_A, SP_A)

        class ReentrantFitEngine(FakeRenderEngine):
            def mint_fit(self, leg, *, preimage, revision):
                # We are INSIDE the outer render's live fit claim; fire the concurrent render now.
                self.inner_out = _render(store, inner)
                return super().mint_fit(leg, preimage=preimage, revision=revision)

        outer = ReentrantFitEngine(RP_A, SP_A)
        out = _render(store, outer)

        assert out["envelope"]["ok"] is True
        assert out["results"][0]["status"] == "ok"  # the outer WON — it minted
        assert outer.fit_mints == 1  # exactly ONE paid fit mint ran
        assert inner.fit_mints == 0  # the loser spent nothing — the double-spend is closed
        inner_item = outer.inner_out["results"][0]
        assert inner_item["code"] == "claim-held" and inner_item["status"] == "warn"
        # The re-drivable block names the id the caller re-drives by (§22.3/§21.8).
        assert inner_item["ids"]["fitted_id"] == out["results"][0]["ids"]["fitted_id"]

    def test_two_concurrent_deliverable_mints_only_one_runs_the_other_claim_held(self, store):
        """The SAME guarantee for the paid DELIVERABLE mint: a stable fit HIT + a drifted serialize
        revision, with a concurrent render fired from inside `mint_deliverable`."""
        _render(store, FakeRenderEngine(RP_A, SP_A))  # materialize the baseline fit + deliverable
        inner = FakeRenderEngine(RP_A, SP_B)  # fit HIT, deliverable serialize-revision MISS

        class ReentrantDeliverableEngine(FakeRenderEngine):
            def mint_deliverable(self, leg, *, preimage, serialize_revision):
                self.inner_out = _render(store, inner)  # inside the outer's live deliverable claim
                return super().mint_deliverable(
                    leg, preimage=preimage, serialize_revision=serialize_revision
                )

        outer = ReentrantDeliverableEngine(RP_A, SP_B)
        out = _render(store, outer)

        assert out["results"][0]["code"] == "re-serialized"  # the outer minted the revision
        assert outer.fit_mints == 0 and outer.deliverable_mints == 1  # one paid deliverable mint
        assert inner.deliverable_mints == 0  # the loser spent nothing
        inner_item = outer.inner_out["results"][0]
        assert inner_item["code"] == "claim-held" and inner_item["status"] == "warn"
        assert inner_item["ids"]["deliverable_id"] == out["results"][0]["ids"]["deliverable_id"]

    def test_peek_is_live_during_the_fit_mint(self, store):
        """`peek(fitted-id)` from an INDEPENDENT registry (any holder) returns a live record while
        the mint runs — the render holds the claim across the whole paid leg (§22.3)."""
        seen = {}

        class PeekingEngine(FakeRenderEngine):
            def mint_fit(self, leg, *, preimage, revision):
                probe = ClaimRegistry(store.claims_dir, holder="probe")
                fid = ids.fitted_id(leg.item, leg.platform, leg.language)
                seen["record"] = probe.peek(fid)
                return super().mint_fit(leg, preimage=preimage, revision=revision)

        _render(store, PeekingEngine(RP_A, SP_A))
        assert seen["record"] is not None  # the claim was LIVE during the mint
        assert seen["record"].holder  # a real holder was recorded on the claim

    def test_release_on_engine_error_leaves_no_dangling_claim(self, store):
        """A `mint_fit` that raises `_EngineError` still releases the fit claim in the `finally`,
        so the id is immediately re-drivable — no wedged claim, no lost mint."""

        class RaisingEngine(FakeRenderEngine):
            def mint_fit(self, leg, *, preimage, revision):
                raise render._EngineError("boom")

        with pytest.raises(render._EngineError):
            _render(store, RaisingEngine(RP_A, SP_A))
        assert list(store.claims_dir.iterdir()) == []  # the finally released the claim

        # Re-drivable: a fresh render acquires cleanly and mints exactly once.
        engine2 = FakeRenderEngine(RP_A, SP_A)
        out = _render(store, engine2)
        assert out["results"][0]["status"] == "ok" and engine2.fit_mints == 1

    def test_cache_hit_acquires_no_claim_and_is_byte_identical(self, store, monkeypatch):
        """The cache-hit / `is_done` path acquires NO claim and mints nothing — the store is
        byte-identical (same output bytes, same ids): the happy path is behaviour-neutral."""
        _render(store, FakeRenderEngine(RP_A, SP_A))  # first render mints fit + deliverable
        before = _snapshot(store)

        registries = []
        real_registry_for = render.registry_for

        def spy_registry_for(s):
            reg = _CountingRegistry(real_registry_for(s))
            registries.append(reg)
            return reg

        monkeypatch.setattr(render, "registry_for", spy_registry_for)
        out = _render(store, FakeRenderEngine(RP_A, SP_A))  # identical inputs → pure cache hit

        assert out["results"][0]["code"] == "already-materialized"
        assert registries and all(r.acquires == 0 for r in registries)  # NO claim acquired
        assert _snapshot(store) == before  # byte-identical store — behaviour-neutral
