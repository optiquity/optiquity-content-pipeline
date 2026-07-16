"""Step-32 tests: the `invoke` contract, the three whole-invocation gates, and the CLI.

Covers: unknown-verb / invalid-token / isolation-violation each envelope-fatal (§21.7); a
per-item block never fails the batch (SM1); workspace isolation on every referenced id — the
SAME id resolves in its own workspace but is refused as `isolation-violation` against another
(§21.1/§10); the token echo path; and the honest step-32 dispatch seam (a known-but-unwired
verb raises `HandlerNotWired`, never a fabricated success). The CLI emits one JSON object.

All fixtures are obviously generic (`wsA`/`wsB`, §7.4 literal ids); no instance content.
"""

from __future__ import annotations

import json

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.api.invoke import (
    KNOWN_VERBS,
    HandlerContext,
    HandlerNotWired,
    invoke,
    main_cli,
    referenced_ids,
    register_handler,
    resolve_in_workspace,
)
from pipeline.store import WorkspaceStore

ART_A = "a-9f3c07d21b44e8aa"
ART_B = "a-1234567890abcdef"
PLAN_HASH = "d3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33f0"


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module dispatch registry so tests stay hermetic."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


@pytest.fixture()
def store(tmp_path):
    return WorkspaceStore(tmp_path / "wsA")


def materialize(store: WorkspaceStore, artifact_id: str) -> None:
    """Stand in an artifact record so the id resolves in this workspace (§22.7 existence)."""
    store.output_path(artifact_id).write_bytes(b"{}\n")


def _ok_handler(items, next_token=None):
    def handler(ctx: HandlerContext):
        # Prove the handler receives the vetted context (verb/workspace/decoded token).
        handler.seen = ctx
        return items, next_token

    handler.seen = None
    return handler


class TestVerbGate:
    def test_unknown_verb_is_envelope_fatal(self, store):
        out = invoke("frobnicate", "wsA", {}, store=store)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "unknown-verb"
        assert out["results"][0]["code"] == "unknown-verb"
        assert "token" not in out

    def test_unknown_verb_returns_before_touching_the_store(self):
        # No store, no root dir needed — the verb gate is the first thing checked (§21.1).
        out = invoke("nope", "wsA", {})
        assert out["envelope"]["ok"] is False

    def test_every_known_verb_passes_the_verb_gate(self, store):
        # Each known verb clears gate 1; with no referenced ids it clears isolation too, then
        # hits the EMPTY registry — the honest unwired seam (never a fake success). Registration
        # is explicit, so the default registry stays empty until a `register_*` call.
        for verb in KNOWN_VERBS:
            with pytest.raises(HandlerNotWired):
                invoke(verb, "wsA", {}, store=store)

    def test_every_known_verb_is_wired_after_registration(self, store):
        # The step-35 capstone: after registering the whole API surface, EVERY known verb
        # dispatches to a REAL handler — nothing is unwired now (`emit-manifest` is no longer the
        # exception). No `HandlerNotWired` is reachable; the honest empty seam step 32 opened is
        # closed. (The full completeness assertion lives in `tests/test_action_completeness.py`.)
        from pipeline.api.session import register_api_handlers

        register_api_handlers()  # the _clean_registry fixture restores the registry after
        for verb in KNOWN_VERBS:
            assert verb in invoke_mod._VERB_HANDLERS  # wired: a real handler dispatches


class TestTokenGate:
    def test_wrong_workspace_token_is_invalid_token(self, store):
        wire = token_mod.encode(token_mod.mint("wsA", PLAN_HASH))
        store_b = WorkspaceStore(store.root.parent / "wsB")
        out = invoke("render", "wsB", {}, token=wire, store=store_b)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "invalid-token"
        assert out["results"][0]["code"] == "invalid-token"
        assert out["results"][0]["context"]["reason"] == "wrong-workspace"

    def test_tampered_token_is_invalid_token(self, store):
        wire = token_mod.encode(token_mod.mint("wsA", PLAN_HASH, produced_ids=[ART_A]))
        wire["plan_hash"] = "0" * 64  # break the digest
        out = invoke("render", "wsA", {}, token=wire, store=store)
        assert out["envelope"]["code"] == "invalid-token"

    def test_valid_token_reaches_the_handler_decoded(self, store):
        materialize(store, ART_A)
        wire = token_mod.encode(token_mod.mint("wsA", PLAN_HASH, produced_ids=[ART_A]))
        handler = _ok_handler([results.make_result(results.CODE_ALREADY_MATERIALIZED, item=ART_A)])
        out = invoke(
            "render", "wsA", {"item": ART_A}, token=wire, store=store, handlers={"render": handler}
        )
        assert out["envelope"]["ok"] is True
        assert handler.seen is not None
        assert handler.seen.token is not None
        assert handler.seen.token.workspace == "wsA"
        assert handler.seen.token.produced_ids == (ART_A,)


class TestIsolationGate:
    def test_cross_workspace_id_is_isolation_violation(self, tmp_path):
        # The id is materialized in wsA but NOT in wsB. Invoking against wsB refuses it —
        # workspaces never cross (§10). The refusal is whole-invocation-fatal (§21.7).
        store_a = WorkspaceStore(tmp_path / "wsA")
        store_b = WorkspaceStore(tmp_path / "wsB")
        materialize(store_a, ART_A)

        out = invoke("render", "wsB", {"item": ART_A}, store=store_b)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"
        assert out["results"][0]["code"] == "isolation-violation"
        assert out["results"][0]["context"]["workspace"] == "wsB"

    def test_same_id_resolves_in_its_own_workspace(self, store):
        # The mirror of the above: in wsA the id resolves, so isolation passes and dispatch
        # proceeds to the (injected) handler — no violation.
        materialize(store, ART_A)
        handler = _ok_handler([results.make_result(results.CODE_ALREADY_MATERIALIZED, item=ART_A)])
        out = invoke("render", "wsA", {"item": ART_A}, store=store, handlers={"render": handler})
        assert out["envelope"]["ok"] is True

    def test_resolve_in_workspace_by_output_existence(self, store):
        assert resolve_in_workspace(store, ART_A) is False
        materialize(store, ART_A)
        assert resolve_in_workspace(store, ART_A) is True

    def test_unparseable_id_does_not_resolve(self, store):
        assert resolve_in_workspace(store, "not an id") is False

    def test_add_to_folio_member_ids_are_all_checked(self, tmp_path):
        # A folio member from another workspace is refused (the §21.2 write-path isolation).
        store_b = WorkspaceStore(tmp_path / "wsB")
        out = invoke(
            "add-to-folio",
            "wsB",
            {"folio_id": "f-abcabcabcabc", "artifact_ids": [ART_A]},
            store=store_b,
        )
        assert out["envelope"]["code"] == "isolation-violation"
        # Both the folio ref AND the member artifact are unresolved here → two violations.
        assert len(out["results"]) == 2


class TestDispatchAndEnvelope:
    def test_known_verb_without_a_handler_is_honestly_unwired(self, store):
        with pytest.raises(HandlerNotWired):
            invoke("render", "wsA", {}, store=store)

    def test_wired_handler_happy_path_no_token(self, store):
        handler = _ok_handler([results.make_result(results.CODE_RE_RECONCILED, item="x")])
        out = invoke("list", "wsA", {}, store=store, handlers={"list": handler})
        assert out["envelope"] == {"ok": True, "verb": "list", "workspace": "wsA"}
        assert out["results"][0]["code"] == "re-reconciled"
        assert "token" not in out

    def test_wired_handler_echoes_a_next_token(self, store):
        next_tok = token_mod.mint("wsA", PLAN_HASH, cursor={"next": "item-2"})
        items = [results.make_result(results.CODE_ALREADY_MATERIALIZED, item="x")]
        handler = _ok_handler(items, next_tok)
        out = invoke("begin-session", "wsA", {}, store=store, handlers={"begin-session": handler})
        assert "token" in out
        # The echoed token round-trips.
        assert token_mod.decode(out["token"], expected_workspace="wsA") == next_tok

    def test_per_item_block_never_fails_the_envelope(self, store):
        # SM1: a per-item block rides `results`; the envelope stays ok=True.
        blocked = results.make_result(results.CODE_HARD_LIMIT_EXCEEDED, item="x")
        handler = _ok_handler([blocked])
        out = invoke("render", "wsA", {}, store=store, handlers={"render": handler})
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["status"] == "block"

    def test_register_handler_wires_the_module_registry(self, store):
        handler = _ok_handler([results.make_result(results.CODE_RE_RECONCILED, item="x")])
        register_handler("list", handler)
        # No injected handlers — the invoke uses the module registry register_handler wrote.
        out = invoke("list", "wsA", {}, store=store)
        assert out["envelope"]["ok"] is True

    def test_register_handler_rejects_unknown_verb(self):
        with pytest.raises(ValueError):
            register_handler("frob", lambda ctx: ([], None))


class TestReferencedIds:
    def test_render_references_item(self):
        assert referenced_ids("render", {"item": ART_A}) == [("item", ART_A)]

    def test_fetch_by_id_references_id(self):
        assert referenced_ids("fetch-by-id", {"id": ART_A}) == [("id", ART_A)]

    def test_add_to_folio_references_folio_and_members(self):
        refs = referenced_ids(
            "add-to-folio",
            {
                "folio_id": "f-abcabcabcabc",
                "members": [{"artifact_id": ART_A, "pin": ART_B + ".linkedin.en.docx.plain"}],
            },
        )
        located = {loc for loc, _ in refs}
        assert located >= {"folio_id", "members.artifact_id", "members.pin"}

    def test_begin_session_auto_target_is_not_an_id(self):
        assert referenced_ids("begin-session", {"target_folio": "auto"}) == []
        assert referenced_ids("begin-session", {"target_folio": "f-abcabcabcabc"}) == [
            ("target_folio", "f-abcabcabcabc")
        ]

    def test_list_and_create_folio_reference_nothing(self):
        assert referenced_ids("list", {"type": "artifacts"}) == []
        assert referenced_ids("create-folio", {"purpose": "launch"}) == []

    def test_continue_session_maps_action_to_its_mirror_verb(self):
        # continue-session's ACTION-nested ids ride the mirror verb's extractor, with the
        # location prefixed by the action, so Gate 3 isolates them uniformly (§21.1/§21.2).
        assert referenced_ids("continue-session", {"action": "render", "item": ART_A}) == [
            ("render.item", ART_A)
        ]
        assert referenced_ids("continue-session", {"action": "fetch", "id": ART_A}) == [
            ("fetch.id", ART_A)
        ]
        # An action with no id-bearing mirror (or an unknown/absent action) references nothing.
        assert referenced_ids("continue-session", {"action": "status"}) == []
        assert referenced_ids("continue-session", {"action": "frobnicate", "item": ART_A}) == []
        assert referenced_ids("continue-session", {}) == []


class TestCli:
    def test_unknown_verb_prints_a_fatal_json_envelope(self, capsys):
        rc = main_cli(["frobnicate", "--workspace", "wsA"])
        assert rc == 1  # a whole-invocation failure
        out = json.loads(capsys.readouterr().out)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "unknown-verb"

    def test_bad_params_json_is_a_usage_error(self, capsys):
        rc = main_cli(["render", "--workspace", "wsA", "--params-json", "{not json"])
        assert rc == 2
        assert "must be valid JSON" in capsys.readouterr().err

    def test_params_json_must_be_an_object(self, capsys):
        rc = main_cli(["render", "--workspace", "wsA", "--params-json", "[1,2,3]"])
        assert rc == 2
        assert "must be a JSON object" in capsys.readouterr().err

    def test_session_verb_stays_honestly_unwired_exits_three(self, tmp_path, capsys):
        # C7 wires render + fetch-by-id in the door, but the live-quota SESSION verbs stay
        # honestly unwired: begin-session (no referenced ids) clears both gates, then hits the
        # empty seam → HandlerNotWired → exit 3 (§21.9 — never a fabricated success on a
        # quota-spending verb). (Pre-C7 this used `render`, now a wired verb — see TestCliDoor.)
        argv = [
            "begin-session", "--workspace", "wsA", "--root", str(tmp_path), "--params-json", "{}"
        ]
        rc = main_cli(argv)
        assert rc == 3
        assert "not wired yet" in capsys.readouterr().err

    def test_cli_isolation_violation_prints_json_and_exits_one(self, tmp_path, capsys):
        # A referenced id absent from wsA's (empty) store → isolation-violation on stdout.
        rc = main_cli(
            [
                "render",
                "--workspace",
                "wsA",
                "--root",
                str(tmp_path),
                "--params-json",
                json.dumps({"item": ART_A}),
            ]
        )
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["envelope"]["code"] == "isolation-violation"


class TestCliDoor:
    """C7 (GAP-2): the CLI door (`main_cli`) wires the SAFE, STATELESS verbs — `render` (mint) +
    `fetch-by-id` (retrieve) — and NOTHING else. These prove the door is reachable for the two
    safe verbs and that an operator-only verb stays structurally out (the §21.9 separation the
    door must never widen). The autouse `_clean_registry` fixture restores the module registry
    `main_cli` mutates, so the wiring never leaks across tests."""

    def test_render_is_wired_through_the_door(self, tmp_path, capsys):
        # `render` DISPATCHES to the real handler through the door: a malformed render (no
        # coordinates) is a per-item block at envelope ok=True → exit 0, NOT the honest-unwired
        # exit 3. Reaching the handler at all is the proof the door registered `render`.
        argv = ["render", "--workspace", "wsA", "--root", str(tmp_path), "--params-json", "{}"]
        rc = main_cli(argv)
        assert rc == 0  # wired: exit 3 would mean not-wired
        out = json.loads(capsys.readouterr().out)
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["status"] == "block"  # the render handler ran

    def test_fetch_by_id_is_wired_through_the_door(self, tmp_path, capsys):
        # `fetch-by-id` is wired too: an id-less fetch DISPATCHES to the dumb path (a `not-found`
        # result at envelope ok=True → exit 0), proving the retrieve half of the loop is reachable.
        argv = ["fetch-by-id", "--workspace", "wsA", "--root", str(tmp_path), "--params-json", "{}"]
        rc = main_cli(argv)
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["envelope"]["ok"] is True
        assert out["results"][0]["code"] == "not-found"  # the fetch handler ran

    def test_operator_verb_is_not_reachable_through_the_door(self, tmp_path, capsys):
        # SECURITY (§21.9): an operator-only verb (`drift-report`) is NOT in KNOWN_VERBS, so the
        # door refuses it at Gate 1 (`unknown-verb`, exit 1) — wiring render/fetch NEVER widens the
        # external surface to the operator CLI. (A live-quota session verb would answer exit 3.)
        argv = [
            "drift-report", "--workspace", "wsA", "--root", str(tmp_path), "--params-json", "{}"
        ]
        rc = main_cli(argv)
        assert rc == 1
        out = json.loads(capsys.readouterr().out)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "unknown-verb"
