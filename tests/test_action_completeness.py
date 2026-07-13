"""Step-35 CAPSTONE: the closed-vocabulary COMPLETENESS assertion (PA-11 / REC-6).

This closes the honest empty seam step 32 opened. After `register_api_handlers()`:

(a) **EVERY verb** in `invoke.KNOWN_VERBS` has a REAL handler in the dispatch registry — so no
    `invoke.HandlerNotWired` is reachable for any known verb (it is raised ONLY when a known verb's
    registry slot is empty; a full registry makes it provably unreachable).
(b) **EVERY action** in the closed continue-session vocabulary (`session.CONTINUE_ACTIONS`)
    dispatches to a REAL handler — `generate-next`/`status` inline, the rest delegate — so no
    `session.NotYetWired` stub remains anywhere.

Both halves enumerate the FULL surface (non-vacuous), and both prove the honest seams they retire
still BITE on a genuinely-unwired slot (an unregistered verb raises `HandlerNotWired`; a
hypothetical action absent from the inline+delegate cover would trip `NotYetWired`).

Hermetic: the invoke dispatch registry is snapshot/restored; dispatches use empty/minimal params
that reach each REAL handler's early return (a block/needs-input/not-found) — never a live call.
"""

from __future__ import annotations

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline.api.invoke import KNOWN_VERBS, HandlerNotWired, invoke
from pipeline.api.session import CONTINUE_ACTIONS, register_api_handlers
from pipeline.store import WorkspaceStore

WS = "wsA"

#: The two continue-session actions handled INLINE (not via a delegate verb handler).
INLINE_ACTIONS = frozenset({"generate-next", "status"})


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module dispatch registry so the wiring assertion stays hermetic."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


@pytest.fixture()
def store(tmp_path):
    return WorkspaceStore(tmp_path / WS)


# ---------------------------------------------------------------------------
# (a) Verb completeness — no HandlerNotWired reachable after registration.
# ---------------------------------------------------------------------------


class TestVerbCompleteness:
    def test_every_known_verb_has_a_real_handler_after_registration(self):
        register_api_handlers()  # the single production startup wiring call
        for verb in KNOWN_VERBS:
            handler = invoke_mod._VERB_HANDLERS.get(verb)
            assert handler is not None, f"verb {verb!r} has no real handler (HandlerNotWired live)"
            assert callable(handler), verb
        # Non-vacuous: the FULL closed verb set is covered, nothing left unwired.
        assert set(KNOWN_VERBS) <= set(invoke_mod._VERB_HANDLERS)
        assert len(KNOWN_VERBS) >= 9  # the §21.1 verb map is not accidentally empty

    def test_no_known_verb_raises_handler_not_wired(self, store, tmp_path):
        register_api_handlers()
        for verb in KNOWN_VERBS:
            # Empty params clear the gates (no referenced ids); dispatch reaches the REAL handler.
            # The handler may return a block/not-found — that is fine; it must NOT be
            # HandlerNotWired (proving the verb dispatched to a real handler, not the empty seam).
            try:
                invoke(verb, WS, {}, store=store, root=str(tmp_path))
            except HandlerNotWired:  # the ONE outcome this test forbids
                pytest.fail(f"verb {verb!r} still raises HandlerNotWired after registration")
            except Exception:  # noqa: BLE001 — any OTHER error means the handler DID dispatch
                pass

    def test_the_handler_not_wired_seam_still_bites_on_an_unregistered_verb(self, store):
        # The retired seam is real: with the registry EMPTY (pre-registration), invoking a known
        # verb raises HandlerNotWired — so the completeness pass above is a genuine change, not a
        # vacuous always-true assertion.
        assert "emit-manifest" not in invoke_mod._VERB_HANDLERS
        with pytest.raises(HandlerNotWired):
            invoke("emit-manifest", WS, {}, store=store)


# ---------------------------------------------------------------------------
# (b) Action completeness — zero NotYetWired stubs in the closed vocabulary.
# ---------------------------------------------------------------------------


class TestActionCompleteness:
    def test_every_continue_action_is_inline_or_delegated(self):
        # Structural cover: every closed-vocabulary action is handled INLINE (generate-next/status)
        # or DELEGATES to a real verb handler — so the `NotYetWired` tail in `_continue_session` is
        # provably unreachable. A future action added to CONTINUE_ACTIONS with no handler fails it.
        delegates = session._continue_session_delegates(render_engine=None, currency_resolver=None)
        covered = INLINE_ACTIONS | set(delegates)
        missing = set(CONTINUE_ACTIONS) - covered
        assert missing == set(), f"un-wired continue-session actions (NotYetWired stubs): {missing}"
        assert set(CONTINUE_ACTIONS) <= covered
        assert len(CONTINUE_ACTIONS) >= 8  # the §21.2 action map is not accidentally empty

    def test_no_continue_action_raises_not_yet_wired(self, store):
        # Behavioral cover: dispatch EVERY closed-vocabulary action through the real
        # continue-session handler; NONE raises the `NotYetWired` stub. Each reaches its real
        # handler's early return (a block/needs-input/not-found) with token=None + minimal params —
        # no token, no registries, no live call needed.
        handler = session.continue_session_handler()
        for action in CONTINUE_ACTIONS:
            try:
                out = invoke(
                    "continue-session",
                    WS,
                    {"action": action},
                    store=store,
                    handlers={"continue-session": handler},
                )
            except session.NotYetWired:  # the ONE outcome this test forbids
                pytest.fail(f"continue-session action {action!r} still raises NotYetWired")
            assert out["envelope"]["ok"] is True  # a per-item block never fails the batch (SM1)
            assert out["results"], action  # a REAL handler produced a typed result

    def test_the_not_yet_wired_seam_still_bites_on_an_unwired_action(self, store):
        # The retired stub is real: a HANDMADE dispatch whose delegates/inline set OMITS an action
        # trips `NotYetWired` — so "zero stubs remain" is a genuine property, not vacuous. We drive
        # `_continue_session` directly with an empty delegate map for a non-inline action.
        from pipeline.api.invoke import HandlerContext

        ctx = HandlerContext(
            verb="continue-session",
            workspace=WS,
            params={"action": "emit-manifest"},  # a real action, but no handler supplied
            token=None,
            pins=None,
            store=store,
        )
        with pytest.raises(session.NotYetWired):
            session._continue_session(
                ctx,
                adapters={},
                run_artifact=lambda **_kw: None,
                now=None,
                model=None,
                delegates={},  # emptied → the defensive seam must bite
            )
