"""GAP-9 / §23: the workspace-path containment guard AT THE INVOKE DOOR — isolation at the ROOT.

Design authority: `docs/design.md` §21.1 (isolation is enforced BY THE API, not by trust) +
§10 (client isolation is structural) + CLAUDE.md rule 2. The invoke door builds a store root
as `<root>/users/<user>/workspaces/<workspace>` from caller-supplied segments; without validation
a `../other-client`, an absolute path, or a symlink escape would MOVE the store root the §21.1
per-id isolation gate validates against, so a referenced id would resolve in the WRONG
workspace and pass. These tests prove the invoke door validates the `(user, workspace)` pair with
the 3-level `pipeline.workspace_name.validate_workspace_path` and refuses a name-escape
whole-invocation-fatally BEFORE any id resolves — the gate now holds at the root. (The validator's
own unit coverage lives in `tests/test_workspace_path.py`.)

All fixtures are generic (`acme`/`wsA`, §7.4 literal ids); no instance content.
"""

from __future__ import annotations

import os

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline.api.invoke import HandlerNotWired, invoke
from pipeline.store import WorkspaceStore

ART_A = "a-9f3c07d21b44e8aa"

#: §23 (B5 door cutover): the invoke door threads a MANDATORY `user` (the isolation prefix) and
#: validates the `(user, workspace)` pair with the 3-level `validate_workspace_path` — which is
#: lowercase-only (W5). The door-integration classes below use a fixed owning user and a
#: LOWERCASE-only valid-name subset. (B9 removed the OLD single-level validator and its unit
#: tests; the new validator's unit coverage now lives in `tests/test_workspace_path.py`.)
USER = "acme"
DOOR_VALID_NAMES = (
    "mvp-demo",
    "optiquitytrader",
    "workspace.template",  # interior DOT allowed; only a bare `..` is traversal
    "testws",
    "self",
    "ws",
)

#: Names that MUST be refused — traversal, absolute, empty, bare dots, separators, flag-like.
REJECTED_NAMES = (
    "../other-client",
    "..",
    ".",
    "",
    "/etc",
    "a/b",
    "foo/../bar",  # normalizes back inside, but is not one safe segment (hygiene refuses it)
    "-lead",  # leading '-' looks like a CLI flag
    "..%2f",  # smuggled-separator shape — not a clean segment
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module dispatch registry so tests stay hermetic (empty seam)."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


def _materialize(store: WorkspaceStore, artifact_id: str) -> None:
    """Stand in an artifact record so the id resolves in that store (§22.7 existence)."""
    store.output_path(artifact_id).write_bytes(b"{}\n")


# ---------------------------------------------------------------------------
# Integration — the invoke door refuses a name-escape whole-invocation-fatally.
# ---------------------------------------------------------------------------


class TestInvokeDoorRejectsNameEscape:
    @pytest.mark.parametrize("name", REJECTED_NAMES)
    def test_bad_workspace_is_isolation_violation_fatal(self, tmp_path, name):
        # No store injected → the door builds it from the (user, name) pair → the 3-level guard
        # fires as a typed whole-invocation-fatal gate (`isolation-violation`, the root sibling of
        # the per-id gate). `render` is a known verb, so this is NOT an unknown-verb refusal.
        out = invoke("render", name, USER, {"item": ART_A}, root=tmp_path)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"
        assert out["results"][0]["code"] == "isolation-violation"
        assert out["results"][0]["status"] == "block"
        assert out["results"][0]["context"]["workspace"] == str(name)
        assert out["results"][0]["context"]["user"] == USER
        assert "reason" in out["results"][0]["context"]
        assert "token" not in out  # a fatal path never echoes a token (§21.7)

    def test_symlink_escape_through_the_door_is_fatal(self, tmp_path):
        # A `users/<user>/workspaces/evil` symlink pointing outside → the door refuses it before
        # any id resolves against the (relocated) store (§23 L3 leaf containment).
        base = tmp_path / "users" / USER / "workspaces"
        base.mkdir(parents=True)
        outside = tmp_path / "outside"
        outside.mkdir()
        os.symlink(outside, base / "evil")
        out = invoke("render", "evil", USER, {"item": ART_A}, root=tmp_path)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"
        assert out["results"][0]["context"]["reason"] == "escapes-workspaces-root"

    @pytest.mark.parametrize("name", DOOR_VALID_NAMES)
    def test_valid_name_clears_the_guard_and_reaches_dispatch(self, tmp_path, name):
        # A valid (lowercase) name + user (no injected store) clears Gate 1 + the 3-level guard +
        # token + isolation (no ids referenced), then hits the EMPTY registry — the honest unwired
        # seam. Reaching HandlerNotWired proves the pair was ACCEPTED.
        with pytest.raises(HandlerNotWired):
            invoke("render", name, USER, {}, root=tmp_path)

    def test_injected_store_is_never_name_validated(self, tmp_path):
        # The store-injection seam places nothing from the name, so the guard does not apply —
        # an injected store dispatches normally even though the label is not re-validated here.
        store = WorkspaceStore(tmp_path / "wsA")
        with pytest.raises(HandlerNotWired):
            invoke("render", "wsA", USER, {}, store=store)


class TestIsolationGateNowHoldsAtTheRoot:
    def test_traversal_no_longer_resolves_ids_in_the_wrong_workspace(self, tmp_path):
        # The exploit the guard closes: `workspace="../victim"` would relocate the store root from
        # `<root>/users/<user>/workspaces/../victim` to `<root>/users/<user>/victim`, where a victim
        # artifact IS materialized — so the per-id gate would resolve it and PASS (a cross-workspace
        # read). The victim lives one level up in the SAME user's tree.
        victim_store = WorkspaceStore(tmp_path / "users" / USER / "victim")
        _materialize(victim_store, ART_A)
        # Exploit target is real: the id genuinely resolves in the victim store.
        from pipeline.api.invoke import resolve_in_workspace

        assert resolve_in_workspace(victim_store, ART_A) is True

        # With the guard, the door refuses `../victim` BEFORE the store is built — the id never
        # gets the chance to resolve in the victim's store. The gate holds at the root.
        out = invoke("render", "../victim", USER, {"item": ART_A}, root=tmp_path)
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"
        assert out["results"][0]["context"]["reason"] == "not-a-safe-segment"
