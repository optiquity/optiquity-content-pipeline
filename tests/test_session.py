"""Step-33 tests: the session/generation half of the external API (`pipeline.api.session`).

Covers, against the REAL shipped registries (copied into `tmp_path` — the repo is read-only
toward this suite) plus tmp instance/workspace surfaces:

- **begin-session** (§20/§21.1/§21.6): plan resolved with `generate = none` (nothing
  materialized); the minted resumption token round-trips (plan_hash, inputs, an initial empty
  cursor, empty produced ids, the target folio ref); overrides are CAPTURED into the token
  inputs (fixed for the whole plan); the `target_folio = none|auto|<folio-id>` cases +
  `idempotency_key` reproducing an auto folio; supplied `[pins]` win over capture; an
  `invalid-override` and an unknown selection are typed blocks.
- **continue-session closed vocabulary** (§21.2, API2): the inline actions (`generate-next`,
  `status`) + an `unknown-action`; the WIRED actions (`render`/`fetch`/`add-to-folio`/`list`/`get`/
  `emit-manifest`) DELEGATE to their verb handlers (return results, never raise). After step 35 the
  vocabulary is FULLY wired — NO action is a `NotYetWired` stub (see `test_action_completeness.py`).
- **generate-next** (§21.6/§21.8): batch + cursor advance by coordinate; idempotent by
  artifact-id existence (a re-run is an `already-materialized` no-op, no second writer call);
  `plan-stale` on a mid-session config edit (never a silent skip/dup); SM1 — a per-item block
  leaves the envelope ok and siblings proceed; overrides are read ONLY from the token.
- **BINDING nested-id isolation**: every action-nested id is workspace-isolated by the invoke
  GATE (each action mapped to its mirror verb) — a cross-workspace `render.item`/`add-to-folio`
  id is refused `isolation-violation` WHOLE-INVOCATION-fatally (envelope ok=False), exactly like
  the standalone verb path; the delegate/stub is never reached.
- **CF-1 wiring**: the source commit-map is pinned through `adapter.pin_commit` (supplied pins
  win), the SAME provenance read grounding uses.
- the explicit `register_session_handlers` wiring point.

Fixtures are obviously generic (`testws`, `x-t-*` topics, framework recipes); no instance
content. No `live` marker: the per-item generation thread (`driver._run_artifact`) is injected
as a fake seam that materializes the artifact-id — never a real subscription call.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline.adapters.base import GroundingResult, SourceAdapter
from pipeline.api import invoke
from pipeline.api import token as token_mod
from pipeline.driver import DriverError
from pipeline.folios import create_folio
from pipeline.lint import REGISTRY_ROOTS
from pipeline.outline import outline_digest
from pipeline.outline_store import get_outline, put_outline
from pipeline.store import WorkspaceStore, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"

#: A cross-workspace artifact/folio id never materialized in `testws` (isolation fixtures).
FOREIGN_ART = "a-1234567890abcdef"
FOREIGN_FOLIO = "f-abcabcabcabc"


# --- fixtures ---------------------------------------------------------------------------------


def decode(wire) -> token_mod.Token:
    return token_mod.decode(wire, expected_workspace=WS)


def build_root(
    tmp_path: Path,
    *,
    l2: str = BASE_L2,
    topics: tuple[tuple[str, str], ...] = (("x-t-alpha", "First."),),
) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace (REC-3 read-only)."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = REPO_ROOT / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(l2, encoding="utf-8")
    topics_dir = root / "users" / USER / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    for tid, why in topics:
        (topics_dir / f"{tid}.md").write_text(TOPIC.format(tid=tid, why=why), encoding="utf-8")
    return root


def store_for(root: Path) -> WorkspaceStore:
    # `.at(...)` records identity so session/render recover the framework root loudly (§23).
    return WorkspaceStore.at(root, USER, WS)


class FakeRun:
    """The injected per-item generation seam (stands in for `driver._run_artifact`): it
    MATERIALIZES the artifact-id in the store (so `is_done` is true on re-run) and returns a
    minimal outcome carrying the deliverable ids — never a live compose/render call. `block`
    names an artifact-id to fail with a `DriverError` (the SM1 per-item-block probe)."""

    def __init__(self, *, block: str | None = None) -> None:
        self.calls: list[str] = []
        self._block = block

    def __call__(self, *, store: WorkspaceStore, item, **_kwargs):
        aid = item.artifact_id
        self.calls.append(aid)
        if aid == self._block:
            raise DriverError(f"driver-error: injected per-item block for {aid}")
        store.output_path(aid).write_bytes(b"{}\n")
        deliverables = tuple(
            SimpleNamespace(deliverable_id=d.deliverable_id) for d in item.deliverables
        )
        return SimpleNamespace(artifact_id=aid, deliverables=deliverables)


class FakePinAdapter(SourceAdapter):
    """A source adapter whose `pin_commit` returns a fixed commit (CF-1 wiring probe)."""

    name = "graphify"

    def __init__(self, commit: str | None) -> None:
        self._commit = commit

    def ground(self, *, connection, query) -> GroundingResult:  # pragma: no cover - unused
        raise AssertionError("grounding is bypassed by the injected run_artifact seam")

    def pin_commit(self, connection):
        return self._commit


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the invoke dispatch registry so the wiring test stays hermetic."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def handlers(run: FakeRun | None = None) -> dict:
    return {
        "begin-session": session.begin_session_handler(),
        "continue-session": session.continue_session_handler(run_artifact=run or FakeRun()),
    }


def begin(root: Path, store: WorkspaceStore, params: dict, *, hs: dict, **kw) -> dict:
    return invoke.invoke(
        "begin-session", WS, USER, params, store=store, root=str(root), handlers=hs, **kw
    )


def cont(root: Path, store: WorkspaceStore, params: dict, token, *, hs: dict) -> dict:
    return invoke.invoke(
        "continue-session", WS, USER, params, token=token, store=store, root=str(root), handlers=hs
    )


def base_params(**over) -> dict:
    params = {"recipe": "explainer-post", "topics": ["x-t-alpha"], "platforms": ["github"]}
    params.update(over)
    return params


# --- begin-session ----------------------------------------------------------------------------


class TestBeginSession:
    def test_resolves_plan_and_mints_a_round_tripping_token(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(), hs=handlers())
        assert out["envelope"]["ok"] is True
        assert "token" in out
        decoded = token_mod.decode(out["token"], expected_workspace=WS)
        # generate = none: the token starts empty (nothing produced, cursor at the start).
        assert decoded.produced_ids == ()
        assert decoded.cursor == {"consumed": []}
        assert decoded.folio_id is None
        # inputs carry everything a re-resolve needs (§21.6): the request + fixed pins.
        assert decoded.inputs["request"]["recipe"] == "explainer-post"
        assert decoded.inputs["source_subset"] == []
        assert decoded.inputs["overrides"] == {}
        # the summary names the plan cover.
        summary = out["results"][0]
        assert summary["context"]["generate"] == "none"
        assert summary["context"]["plan_hash"] == decoded.plan_hash
        assert summary["ids"]["artifact_ids"]

    def test_generate_none_materializes_nothing(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(), hs=handlers())
        for aid in out["results"][0]["ids"]["artifact_ids"]:
            assert is_done(store, aid) is False  # plan resolved, NOTHING generated

    def test_overrides_are_captured_and_change_identity(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        plain = begin(root, store, base_params(), hs=handlers())
        overridden = begin(
            root, store, base_params(overrides={"voice.formality": 2}), hs=handlers()
        )
        pt = token_mod.decode(plain["token"], expected_workspace=WS)
        ot = token_mod.decode(overridden["token"], expected_workspace=WS)
        assert ot.inputs["overrides"] == {"voice.formality": 2}  # captured (fixed for the plan)
        assert ot.plan_hash != pt.plan_hash  # the override rode L6 → M2 → identity (§7.2)

    def test_invalid_override_is_a_typed_block(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        # `voice` names a whole entry, not a declared attribute — the hard M1 guard (§21.4).
        out = begin(root, store, base_params(overrides={"voice": "some-other"}), hs=handlers())
        assert out["envelope"]["ok"] is True  # not a whole-invocation failure
        assert out["results"][0]["code"] == "invalid-override"
        assert "token" not in out  # no session begun

    def test_unknown_selection_is_not_found(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(topics=["x-missing-topic"]), hs=handlers())
        assert out["results"][0]["code"] == "not-found"
        assert "token" not in out

    def test_malformed_source_connection_is_a_typed_block(self, tmp_path):
        # begin-session is plan-only (no grounding pass), so a malformed source `connection:`
        # first surfaces at the §7.2 commit pin (`adapter.pin_commit` → `_validate_connection`,
        # which refuses a relative graphify path). It must be a TYPED result, not an uncaught
        # AdapterError — parity with the sibling FanoutError/FolioError/UnknownEntryError paths.
        root = build_root(tmp_path)
        store = store_for(root)
        sources_dir = root / "users" / USER / "workspaces" / WS / "sources"
        sources_dir.mkdir(parents=True)
        (sources_dir / "x-bad-src.md").write_text(
            "---\nid: x-bad-src\nprovenance: instance\nschema_version: 1\n"
            "adapter: graphify\nconnection:\n  path: relative/graph.json\n"
            "content_kind: general\n---\n\nMalformed: a relative graphify path.\n",
            encoding="utf-8",
        )
        out = begin(root, store, base_params(), hs=handlers())
        assert out["envelope"]["ok"] is True  # not a whole-invocation failure
        assert out["results"][0]["status"] == "block"
        assert "malformed" in out["results"][0]["remediation"]["hint"]
        assert "token" not in out  # no session begun

    def test_target_folio_auto_mints_and_records_a_folio(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(target_folio="auto"), hs=handlers())
        decoded = token_mod.decode(out["token"], expected_workspace=WS)
        assert decoded.folio_id is not None
        assert (store.folios_dir / decoded.folio_id).is_dir()  # the empty folio exists
        assert out["results"][0]["ids"]["folio_id"] == decoded.folio_id

    def test_idempotency_key_reproduces_the_auto_folio(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        p = base_params(target_folio="auto", idempotency_key="retry-7")
        first = decode(begin(root, store, p, hs=handlers())["token"])
        second = decode(begin(root, store, p, hs=handlers())["token"])
        assert first.folio_id == second.folio_id  # a retried begin-session, not a duplicate

    def test_target_folio_concrete_id_is_recorded(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        folio_id = create_folio(store, purpose="hand-made", nonce="n").folio_id
        out = begin(root, store, base_params(target_folio=folio_id), hs=handlers())
        assert token_mod.decode(out["token"], expected_workspace=WS).folio_id == folio_id

    def test_target_folio_cross_workspace_id_is_isolation_fatal(self, tmp_path):
        # The invoke gate isolates begin-session's `target_folio` id (a real, existing folio
        # only) — a foreign folio id is whole-invocation fatal before the handler runs.
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, base_params(target_folio=FOREIGN_FOLIO), hs=handlers())
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"

    def test_begin_session_explain_surfaces_plan_and_spend_scope(self, tmp_path):
        # C1: `explain=True` surfaces the effective settings + the spend estimate in the summary
        # context — and the minted token/plan_hash is UNCHANGED (explain is not an identity input).
        root = build_root(tmp_path)
        store = store_for(root)
        plain = begin(root, store, base_params(), hs=handlers())
        explained = begin(root, store, base_params(explain=True), hs=handlers())

        ctx = explained["results"][0]["context"]
        artifact_ids = explained["results"][0]["ids"]["artifact_ids"]
        assert ctx["effective_settings"]  # the per-artifact-id effective-settings view
        assert set(ctx["effective_settings"]) == set(artifact_ids)
        assert ctx["spend_scope"] == len(artifact_ids)  # spend_scope == len(plan.artifact_ids())

        # The plain (non-explain) run does NOT carry the projection.
        plain_ctx = plain["results"][0]["context"]
        assert "effective_settings" not in plain_ctx
        assert "spend_scope" not in plain_ctx

        # Identity: the explain run mints the SAME plan_hash, and `explain` never enters inputs.
        exp_tok = token_mod.decode(explained["token"], expected_workspace=WS)
        plain_tok = token_mod.decode(plain["token"], expected_workspace=WS)
        assert exp_tok.plan_hash == plain_tok.plan_hash
        assert "explain" not in exp_tok.inputs
        assert "explain" not in exp_tok.inputs.get("request", {})

    def test_explain_builds_no_continue_handler(self, tmp_path, monkeypatch):
        # C1 / S1: the preview path builds ONLY begin-session — never continue-session (whose
        # default `run_artifact` is the LIVE transport). Spy the factory to prove it is never
        # constructed on an `explain` begin-session (no live runner seam instantiated).
        root = build_root(tmp_path)
        store = store_for(root)
        constructed: list[str] = []
        real = session.continue_session_handler

        def spy(*args, **kwargs):
            constructed.append("continue")
            return real(*args, **kwargs)

        monkeypatch.setattr(session, "continue_session_handler", spy)
        # Only the begin-session handler is wired for the preview door.
        hs = {"begin-session": session.begin_session_handler()}
        out = begin(root, store, base_params(explain=True), hs=hs)
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["context"]["spend_scope"] == len(
            out["results"][0]["ids"]["artifact_ids"]
        )
        assert constructed == []  # NO continue-session handler / live runner constructed


# --- CF-1: commit-map pinned through the adapter provenance -----------------------------------


class TestCommitPinning:
    def test_commit_map_pinned_via_adapter_pin_commit(self):
        pool = [SimpleNamespace(id="x-src", adapter="graphify", connection={"path": "/g.json"})]
        adapters = {"graphify": FakePinAdapter("c0ffee123456")}
        # captured through the SAME provenance read grounding uses (pin_commit; CF-1).
        assert session._pin_source_commit_map(pool, adapters, None) == {"x-src": "c0ffee123456"}

    def test_supplied_pins_win_over_capture(self):
        pool = [SimpleNamespace(id="x-src", adapter="graphify", connection={"path": "/g.json"})]
        adapters = {"graphify": FakePinAdapter("captured")}
        pins = {"source_commit": {"x-src": "supplied-sha"}}
        assert session._pin_source_commit_map(pool, adapters, pins) == {"x-src": "supplied-sha"}

    def test_commitless_adapter_pins_nothing(self):
        pool = [SimpleNamespace(id="x-src", adapter="graphify", connection={})]
        assert session._pin_source_commit_map(pool, {"graphify": FakePinAdapter(None)}, None) == {}


# --- continue-session: the closed action vocabulary (§21.2) -----------------------------------


class TestClosedVocabulary:
    def _token(self, root, store):
        return begin(root, store, base_params(), hs=handlers())["token"]

    def test_unknown_action_returns_unknown_action_block(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = cont(root, store, {"action": "frobnicate"}, self._token(root, store), hs=handlers())
        assert out["envelope"]["ok"] is True  # a per-item block, never envelope-fatal (SM1)
        assert out["results"][0]["code"] == "unknown-action"
        assert out["results"][0]["status"] == "block"

    def test_missing_action_is_unknown_action(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = cont(root, store, {}, self._token(root, store), hs=handlers())
        assert out["results"][0]["code"] == "unknown-action"

    def test_status_is_a_real_read(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = cont(root, store, {"action": "status"}, self._token(root, store), hs=handlers())
        assert out["results"][0]["item"] == "status"
        assert out["results"][0]["status"] == "ok"
        ctx = out["results"][0]["context"]
        assert ctx["planned"] >= 1 and ctx["consumed"] == 0 and ctx["drift"] is False

    def test_emit_manifest_is_now_wired_not_a_stub(self, tmp_path):
        # The step-35 capstone: `emit-manifest` is WIRED — dispatching it returns a typed result
        # (an ok envelope carrying the work order), never the `NotYetWired` stub. A WORKSPACE-LOCAL
        # folio_id clears isolation so dispatch reaches the real delegate.
        root = build_root(tmp_path)
        store = store_for(root)
        token = self._token(root, store)
        folio = create_folio(store, purpose="p", nonce="n").folio_id
        params = {"action": "emit-manifest", "folio_id": folio}
        out = cont(root, store, params, token, hs=handlers())  # must NOT raise NotYetWired
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["ids"]["folio_id"] == folio  # the emitted work order
        assert "token" in out  # the cursor is echoed unchanged (a read/plan action, §21.5)

    @pytest.mark.parametrize(
        "action", ["render", "fetch", "add-to-folio", "list", "get", "emit-manifest"]
    )
    def test_wired_actions_delegate_and_never_raise_the_stub(self, tmp_path, action):
        # The step-34-wired actions delegate to their verb handlers and RETURN results (an ok
        # envelope) — never the `NotYetWired` stub, and never a live subscription call (default
        # engines are pure store/config reads for these shapes).
        root = build_root(tmp_path)
        store = store_for(root)
        token = self._token(root, store)
        art = "a-9f3c07d21b44e8aa"
        store.output_path(art).write_bytes(b"{}\n")
        folio = create_folio(store, purpose="p", nonce="n").folio_id
        params = {
            "render": {"action": "render", "item": art},  # missing coords → a block, not a stub
            "fetch": {"action": "fetch", "id": art, "return": "path"},
            "get": {"action": "get", "id": art, "type": "artifacts"},
            "list": {"action": "list", "type": "artifacts"},
            "add-to-folio": {"action": "add-to-folio", "folio_id": folio, "artifact_ids": [art]},
            "emit-manifest": {"action": "emit-manifest", "folio_id": folio},  # §21.5 work order
        }[action]
        out = cont(root, store, params, token, hs=handlers())  # must NOT raise NotYetWired
        assert out["envelope"]["ok"] is True
        assert "token" in out  # the cursor is echoed unchanged (a read/side-output action)


# --- BINDING: continue-session nested-id workspace isolation ----------------------------------


class TestNestedIdIsolation:
    def _token(self, root, store):
        return begin(root, store, base_params(), hs=handlers())["token"]

    def test_cross_workspace_render_item_is_isolation_fatal(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        # FOREIGN_ART is not materialized in testws → refused at the invoke gate; the render
        # delegate is NEVER reached (isolation runs before dispatch). The action path is
        # WHOLE-INVOCATION-fatal, exactly like the standalone verb path (§21.7/§21.1).
        params = {"action": "render", "item": FOREIGN_ART}
        out = cont(root, store, params, self._token(root, store), hs=handlers())
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"
        assert out["results"][0]["code"] == "isolation-violation"
        assert out["results"][0]["context"]["at"] == "render.item"
        assert "token" not in out  # a fatal invocation echoes no token"

    def test_add_to_folio_all_nested_ids_are_isolated(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = cont(
            root,
            store,
            {"action": "add-to-folio", "folio_id": FOREIGN_FOLIO, "artifact_ids": [FOREIGN_ART]},
            self._token(root, store),
            hs=handlers(),
        )
        assert out["envelope"]["ok"] is False  # whole-invocation fatal, like the verb path
        assert out["envelope"]["code"] == "isolation-violation"
        codes = {r["code"] for r in out["results"]}
        assert codes == {"isolation-violation"}
        assert len(out["results"]) == 2  # the folio ref AND the member are both refused

    def test_local_nested_id_passes_isolation_and_reaches_the_delegate(self, tmp_path):
        # A WORKSPACE-LOCAL nested `emit-manifest.folio_id` clears the isolation gate and reaches
        # the WIRED delegate (a typed ok result carrying the work order) — proving the gate passed
        # the id through, and the outcome is the ACTION handler's, not a masked isolation error.
        root = build_root(tmp_path)
        store = store_for(root)
        folio = create_folio(store, purpose="p", nonce="n").folio_id  # local → resolves
        params = {"action": "emit-manifest", "folio_id": folio}
        out = cont(root, store, params, self._token(root, store), hs=handlers())
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["ids"]["folio_id"] == folio

    def test_local_nested_render_id_passes_isolation_and_reaches_the_delegate(self, tmp_path):
        # A WORKSPACE-LOCAL `render.item` clears isolation and reaches the WIRED render delegate
        # (a typed result, not the stub) — the wired counterpart of the emit-manifest case above.
        root = build_root(tmp_path)
        store = store_for(root)
        art = "a-9f3c07d21b44e8aa"
        store.output_path(art).write_bytes(b"{}\n")  # local → resolves
        params = {"action": "render", "item": art}
        out = cont(root, store, params, self._token(root, store), hs=handlers())
        assert out["envelope"]["ok"] is True  # reached the delegate; missing coords → a block item
        assert out["results"][0]["status"] == "block"

    def test_action_path_mirrors_the_verb_path(self, tmp_path):
        # §21.1: the SAME cross-workspace id is refused envelope-fatally through BOTH the
        # standalone `render` VERB and `continue-session{action: render}` — the action path
        # and the verb path never diverge (the contract-parity property FIX 2 restored). Both
        # are stopped at the invoke gate before any handler dispatch.
        root = build_root(tmp_path)
        store = store_for(root)
        verb_out = invoke.invoke(
            "render", WS, USER, {"item": FOREIGN_ART}, store=store, root=str(root)
        )
        action_out = cont(
            root,
            store,
            {"action": "render", "item": FOREIGN_ART},
            self._token(root, store),
            hs=handlers(),
        )
        for out in (verb_out, action_out):
            assert out["envelope"]["ok"] is False
            assert out["envelope"]["code"] == "isolation-violation"
            assert out["results"][0]["code"] == "isolation-violation"
            assert "token" not in out


# --- generate-next (§21.6/§21.8) --------------------------------------------------------------


class TestGenerateNext:
    def test_composes_and_advances_the_cursor(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        token = begin(root, store, base_params(), hs=hs)["token"]
        out = cont(root, store, {"action": "generate-next"}, token, hs=hs)
        assert out["envelope"]["ok"] is True
        (result,) = out["results"]
        assert result["status"] == "ok"
        aid = result["ids"]["artifact_id"]
        assert run.calls == [aid]  # the writer ran once
        nxt = token_mod.decode(out["token"], expected_workspace=WS)
        assert nxt.cursor["consumed"] == [aid]  # advanced by COORDINATE (§21.6)
        assert aid in nxt.produced_ids

    def test_idempotent_by_artifact_id_existence(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        out0 = begin(root, store, base_params(), hs=hs)
        aid = out0["results"][0]["ids"]["artifact_ids"][0]
        store.output_path(aid).write_bytes(b"{}\n")  # PRE-materialized (a prior run)
        out = cont(root, store, {"action": "generate-next", "only": [aid]}, out0["token"], hs=hs)
        assert out["results"][0]["code"] == "already-materialized"
        assert out["results"][0]["status"] == "ok"
        assert run.calls == []  # no regeneration — correctness is id existence, not the cursor

    def test_rerun_is_a_noop_via_already_materialized(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        out0 = begin(root, store, base_params(), hs=hs)
        aid = out0["results"][0]["ids"]["artifact_ids"][0]
        first = cont(root, store, {"action": "generate-next", "only": [aid]}, out0["token"], hs=hs)
        assert first["results"][0]["status"] == "ok" and run.calls == [aid]
        # Re-run the SAME coordinate on the returned token → an idempotent no-op, no 2nd call.
        again = cont(root, store, {"action": "generate-next", "only": [aid]}, first["token"], hs=hs)
        assert again["results"][0]["code"] == "already-materialized"
        assert run.calls == [aid]  # still exactly one writer invocation

    def test_batch_size_controls_forward_progress(self, tmp_path):
        root = build_root(
            tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B."), ("x-t-gamma", "C."))
        )
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        params = base_params(topics=["x-t-alpha", "x-t-beta", "x-t-gamma"])
        token = begin(root, store, params, hs=hs)["token"]
        out1 = cont(root, store, {"action": "generate-next", "batch_size": 2}, token, hs=hs)
        assert len(out1["results"]) == 2
        t1 = token_mod.decode(out1["token"], expected_workspace=WS)
        assert len(t1.cursor["consumed"]) == 2
        out2 = cont(root, store, {"action": "generate-next", "batch_size": 2}, out1["token"], hs=hs)
        assert len(out2["results"]) == 1  # only the last item remained unconsumed
        assert len(run.calls) == 3  # all three composed exactly once across the two calls

    def test_plan_stale_on_a_midsession_config_edit(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        token = begin(root, store, base_params(), hs=hs)["token"]
        # A mid-session workspace edit that changes the resolved plan (the topic's `why`
        # rides identity §7.2) → the re-resolve's plan_hash ≠ the token's → plan-stale.
        (root / "users" / USER / "workspaces" / WS / "topics" / "x-t-alpha.md").write_text(
            TOPIC.format(tid="x-t-alpha", why="A completely rewritten rationale."), encoding="utf-8"
        )
        out = cont(root, store, {"action": "generate-next"}, token, hs=hs)
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["code"] == "plan-stale"
        assert out["results"][0]["status"] == "warn"
        assert run.calls == []  # NOTHING generated — never a silent skip or dup

    def test_status_reports_drift_after_a_config_edit(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        hs = handlers()
        token = begin(root, store, base_params(), hs=hs)["token"]
        (root / "users" / USER / "workspaces" / WS / "topics" / "x-t-alpha.md").write_text(
            TOPIC.format(tid="x-t-alpha", why="A drifted rationale."), encoding="utf-8"
        )
        out = cont(root, store, {"action": "status"}, token, hs=hs)
        assert out["results"][0]["code"] == "plan-stale"
        assert out["results"][0]["context"]["drift"] is True

    def test_sm1_a_per_item_block_leaves_the_envelope_ok(self, tmp_path):
        root = build_root(tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B.")))
        store = store_for(root)
        out0 = begin(root, store, base_params(topics=["x-t-alpha", "x-t-beta"]), hs=handlers())
        aids = out0["results"][0]["ids"]["artifact_ids"]
        run = FakeRun(block=aids[0])  # the first item blocks; the sibling must proceed
        hs = handlers(run)
        out = cont(root, store, {"action": "generate-next", "batch_size": 2}, out0["token"], hs=hs)
        assert out["envelope"]["ok"] is True  # SM1: a per-item block never fails the batch
        by_item = {r["item"]: r["status"] for r in out["results"]}
        assert by_item[aids[0]] == "block"
        assert by_item[aids[1]] == "ok"
        assert is_done(store, aids[1]) is True  # the sibling materialized

    def test_generate_next_requires_the_token(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        out = cont(root, store, {"action": "generate-next"}, None, hs=handlers())
        assert out["results"][0]["status"] == "block"  # no cursor → cannot resolve/advance

    def test_overrides_are_fixed_at_begin_session_only(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        token = begin(root, store, base_params(), hs=hs)["token"]
        # A run-layer override passed to continue-session is IGNORED — the plan re-resolves
        # from the TOKEN inputs (§21.2/§12.5). An override that would fail the M1 guard if
        # applied proves it is never read: generation proceeds cleanly, no invalid-override,
        # no plan-stale.
        out = cont(
            root,
            store,
            {"action": "generate-next", "overrides": {"voice": "would-be-invalid"}},
            token,
            hs=hs,
        )
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["status"] == "ok"  # neither invalid-override nor plan-stale


# --- the explicit wiring point (§21.1) --------------------------------------------------------


class TestRegistration:
    def test_import_has_no_registration_side_effect(self):
        # Importing the module never wires verbs (keeps the step-32 unwired-registry tests
        # valid); the registry is populated only by an explicit call.
        assert "begin-session" not in invoke_mod._VERB_HANDLERS
        assert "continue-session" not in invoke_mod._VERB_HANDLERS

    def test_register_session_handlers_wires_the_module_registry(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        session.register_session_handlers()
        # No injected handlers — the invoke uses the module registry the call wrote.
        out = invoke.invoke("begin-session", WS, USER, base_params(), store=store, root=str(root))
        assert out["envelope"]["ok"] is True and "token" in out


# --- DR-3 (horn (a) / B1): the outline INGEST + DRIVE legs, end-to-end via the existing verbs ---


def outline_params(md: str, **over) -> dict:
    """base_params + an `ingest_outlines` leg: hand-authored outline text for the x-t-alpha
    coordinate. begin-session PUTS it in the store and folds its digest into the drive map."""
    p = base_params(**over)
    p["ingest_outlines"] = [{"coordinate": {"topic": "x-t-alpha"}, "text": md}]
    return p


class TestOutlineDrive:
    """DR-3 Commit 6 end-to-end (iv): a hand-authored outline is PUT in the store (ingest leg,
    reusing begin-session — no new verb), DRIVES compose via the per-coordinate outlines map, and
    is identity-bearing via its digest. A COSMETIC edit does not churn the driven artifact-id; a
    SEMANTIC edit does. The drive map round-trips through the token so generate-next re-resolves
    the SAME driven plan (no `plan-stale`)."""

    MD_A = "# Outline A\n\n- alpha point\n- beta point\n"
    MD_B = "# Outline B\n\n- gamma point\n"

    def test_ingest_drives_a_distinct_artifact_id_and_stores_the_outline(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        plain = begin(root, store, base_params(), hs=handlers())
        driven = begin(root, store, outline_params(self.MD_A), hs=handlers())
        plain_ids = plain["results"][0]["ids"]["artifact_ids"]
        driven_ids = driven["results"][0]["ids"]["artifact_ids"]
        # the outline is identity-bearing via its digest -> a DIFFERENT driven artifact-id.
        assert plain_ids != driven_ids
        # the ingest leg PUT the outline (content-addressed by its bare digest).
        assert get_outline(store, outline_digest(self.MD_A)) is not None
        # the token carries the DIGEST drive-map (round-trips to generate-next; never raw text).
        decoded = token_mod.decode(driven["token"], expected_workspace=WS)
        assert decoded.inputs["request"]["outlines"] == [
            {
                "coordinate": {
                    "topic": "x-t-alpha",
                    "persona": None,
                    "format": None,
                    "voice": None,
                    "goals": None,
                },
                "outline_digest": outline_digest(self.MD_A),
            }
        ]

    def test_cosmetic_edit_does_not_churn_semantic_does(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        base_ids = begin(root, store, outline_params(self.MD_A), hs=handlers())[
            "results"
        ][0]["ids"]["artifact_ids"]
        cosmetic = "# Outline A\n\n\n- alpha point   \n- beta point\n\n"  # N-identical to MD_A
        cos_ids = begin(root, store, outline_params(cosmetic), hs=handlers())[
            "results"
        ][0]["ids"]["artifact_ids"]
        sem_ids = begin(root, store, outline_params(self.MD_B), hs=handlers())[
            "results"
        ][0]["ids"]["artifact_ids"]
        assert cos_ids == base_ids  # a cosmetic edit is N-invariant -> the SAME id
        assert sem_ids != base_ids  # a semantic edit churns the id (the accepted R2 cost)

    def test_outline_less_token_inputs_omit_the_drive_map(self, tmp_path):
        # zero-churn (iii): an outline-LESS begin-session's token inputs carry NO `outlines` key.
        root = build_root(tmp_path)
        store = store_for(root)
        decoded = decode(begin(root, store, base_params(), hs=handlers())["token"])
        assert "outlines" not in decoded.inputs["request"]

    def test_direct_digest_drive_map_works(self, tmp_path):
        # the B1 digest form: a pre-stored outline supplied by digest under `outlines` drives too.
        root = build_root(tmp_path)
        store = store_for(root)
        digest = put_outline(store, self.MD_A)
        params = base_params(
            outlines=[{"coordinate": {"topic": "x-t-alpha"}, "outline_digest": digest}]
        )
        driven = begin(root, store, params, hs=handlers())["results"][0]["ids"]["artifact_ids"]
        plain_out = begin(root, store, base_params(), hs=handlers())
        plain = plain_out["results"][0]["ids"]["artifact_ids"]
        assert driven != plain

    def test_generate_next_re_resolves_the_driven_plan_without_stale(self, tmp_path):
        root = build_root(tmp_path)
        store = store_for(root)
        run = FakeRun()
        hs = handlers(run)
        begun = begin(root, store, outline_params(self.MD_A), hs=hs)
        aid = begun["results"][0]["ids"]["artifact_ids"][0]
        out = cont(root, store, {"action": "generate-next"}, begun["token"], hs=hs)
        codes = [r.get("code") for r in out["results"]]
        assert "plan-stale" not in codes  # the re-resolved driven plan matches the token plan_hash
        assert run.calls == [aid]  # the DRIVEN item (its id carries the digest) materialized

    def test_empty_ingest_outline_is_a_typed_block(self, tmp_path):
        # §15 substance floor: an empty / no-substance ingested outline is a typed block.
        root = build_root(tmp_path)
        store = store_for(root)
        out = begin(root, store, outline_params("   \n\n\t\n"), hs=handlers())
        assert out["results"][0]["status"] == "block"
        assert "token" not in out


class TestPlanNextBatchIds:
    """The DR-1 anti-drift invariant (§22.2): `session.plan_next_batch_ids` — the async shim's
    predictable-target-id resolver — returns EXACTLY the batch `_generate_next` composes. Proven by
    CO-RESOLVING both against a REAL resolved plan and comparing (they share the one `_select_batch`
    source, so this holds by construction — not by a hand-synced fork). This is the coverage the
    reviewer flagged as the commit's untested crux."""

    def _batch_ids(self, out: dict) -> list[str]:
        """The batch `_generate_next` actually selected, in order — each `results[]` item is ONE
        selected batch item keyed by its artifact-id (ok / already-materialized / block alike)."""
        return [r["item"] for r in out["results"]]

    def test_fresh_multi_artifact_batch_matches_generate_next(self, tmp_path):
        # A real multi-artifact `batch_size` slice: the predicted ids == the batch generate-next
        # materializes, in plan order.
        root = build_root(
            tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B."), ("x-t-gamma", "C."))
        )
        store = store_for(root)
        hs = handlers(FakeRun())
        params = base_params(topics=["x-t-alpha", "x-t-beta", "x-t-gamma"])
        wire = begin(root, store, params, hs=hs)["token"]
        gn = {"action": "generate-next", "batch_size": 2}
        # BEFORE the paid call:
        predicted = session.plan_next_batch_ids(root, USER, WS, decode(wire), gn)
        out = cont(root, store, gn, wire, hs=hs)
        assert predicted == self._batch_ids(out)
        assert len(predicted) == 2  # a genuine multi-artifact slice, not a trivial single id

    def test_only_filter_matches_generate_next(self, tmp_path):
        # An `only=` request: the predicted set == the only-filtered batch (order = plan order).
        root = build_root(tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B.")))
        store = store_for(root)
        hs = handlers(FakeRun())
        begun = begin(root, store, base_params(topics=["x-t-alpha", "x-t-beta"]), hs=hs)
        wire = begun["token"]
        target = [begun["results"][0]["ids"]["artifact_ids"][1]]  # a specific id
        gn = {"action": "generate-next", "only": target}
        predicted = session.plan_next_batch_ids(root, USER, WS, decode(wire), gn)
        out = cont(root, store, gn, wire, hs=hs)
        assert predicted == self._batch_ids(out) == target

    def test_midcursor_complement_matches_generate_next(self, tmp_path):
        # A mid-cursor session (some `consumed`): the predicted set == the not-yet-consumed
        # complement generate-next composes next, and EXCLUDES the already-consumed id.
        root = build_root(
            tmp_path, topics=(("x-t-alpha", "A."), ("x-t-beta", "B."), ("x-t-gamma", "C."))
        )
        store = store_for(root)
        hs = handlers(FakeRun())
        params = base_params(topics=["x-t-alpha", "x-t-beta", "x-t-gamma"])
        wire0 = begin(root, store, params, hs=hs)["token"]
        out1 = cont(root, store, {"action": "generate-next", "batch_size": 1}, wire0, hs=hs)
        consumed_id = out1["results"][0]["item"]
        wire1 = out1["token"]  # the advanced cursor
        gn = {"action": "generate-next", "batch_size": 2}
        predicted = session.plan_next_batch_ids(root, USER, WS, decode(wire1), gn)
        out2 = cont(root, store, gn, wire1, hs=hs)
        assert predicted == self._batch_ids(out2)
        assert consumed_id not in predicted and len(predicted) == 2

    def test_plan_stale_returns_empty_like_generate_next(self, tmp_path):
        # A stale `plan_hash` (a mid-session config edit): the resolver returns [] (nothing to key),
        # exactly as generate-next composes nothing (plan-stale).
        root = build_root(tmp_path)
        store = store_for(root)
        hs = handlers(FakeRun())
        wire = begin(root, store, base_params(), hs=hs)["token"]
        (root / "users" / USER / "workspaces" / WS / "topics" / "x-t-alpha.md").write_text(
            TOPIC.format(tid="x-t-alpha", why="A completely rewritten rationale."), encoding="utf-8"
        )
        gn = {"action": "generate-next"}
        assert session.plan_next_batch_ids(root, USER, WS, decode(wire), gn) == []
        out = cont(root, store, gn, wire, hs=hs)
        assert out["results"][0]["code"] == "plan-stale"  # generate-next likewise composes nothing
