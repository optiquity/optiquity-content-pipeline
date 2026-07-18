"""Step-33 driver tests — the CF-1/CF-2 carry-forward fixes in `pipeline/driver.py`.

The end-to-end thread (`run_thread`) drives a LIVE subscription compose (§25) and is
exercised by the `demo-thread` subcommand, not the default suite. These tests cover the two
surgical, non-live changes step 33 made:

- **CF-1** (id/ledger provenance divergence): `_pin_source_commit` now delegates to
  `adapter.pin_commit` — the SAME provenance read grounding uses — so the §7.2 identity
  commit-map and the §15 grounding ledger can never disagree (the git-fallback commit is no
  longer omitted from identity). The adapter-level agreement is proven in
  `tests/test_adapter_graphify.py`/`test_adapter_folder.py`; here we pin the DRIVER wiring.
- **CF-2** (§22.7 consistency): the fitted deliverable-row `fitted` advance is routed through
  the spine's S5 CONTAINED hook (`_persist_record(advance=…)`), never a raw `ssot.advance`
  outside the S5 exception containment — a source-level pin so the raw call cannot creep back.
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import driver, review
from pipeline.api import results
from pipeline.m3 import resolve_selection
from pipeline.store import WorkspaceStore


class _PinStub:
    """A minimal adapter exposing only `pin_commit` (the CF-1 delegation surface)."""

    def __init__(self, commit: str | None) -> None:
        self._commit = commit
        self.seen: dict | None = None

    def pin_commit(self, connection):
        self.seen = dict(connection)
        return self._commit


class TestPinSourceCommitDelegation:
    def test_delegates_to_the_adapter_pin_commit(self):
        # CF-1: the driver reads the commit through the adapter (one provenance reader), so
        # identity's commit-map cannot diverge from what grounding reports.
        stub = _PinStub("deadbeefcafe")
        assert driver._pin_source_commit(stub, {"path": "/g.json"}) == "deadbeefcafe"
        assert stub.seen == {"path": "/g.json"}

    def test_unbound_adapter_pins_nothing(self):
        assert driver._pin_source_commit(None, {"path": "/g.json"}) is None

    def test_commitless_adapter_pins_none(self):
        assert driver._pin_source_commit(_PinStub(None), {}) is None


class TestFittedAdvanceIsContained:
    def test_run_deliverable_never_calls_ssot_advance_outside_a_hook(self):
        # CF-2 source pin: `_run_deliverable` must not carry a bare `ssot.advance(...)` call
        # (the raw, uncontained advance). The `fitted` advance now rides the spine's S5 hook
        # via `_persist_record(advance=…)`; the only `ssot.advance` reference lives inside the
        # `_advance_fitted_row` hook closure, invoked by the spine's contained `_run_advance_hook`.
        source = Path(driver.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        run_deliverable = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_run_deliverable"
        )
        # Collect every `ssot.advance(...)` call and the nested function that encloses it.
        advance_calls = [
            node
            for node in ast.walk(run_deliverable)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "advance"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "ssot"
        ]
        assert advance_calls, "the fitted advance must still happen"
        hook_bodies = [
            n
            for n in ast.walk(run_deliverable)
            if isinstance(n, ast.FunctionDef) and n.name == "_advance_fitted_row"
        ]
        assert hook_bodies, "the fitted advance must be wrapped in the S5 hook closure"
        contained = {
            id(c) for hook in hook_bodies for c in ast.walk(hook) if isinstance(c, ast.Call)
        }
        for call in advance_calls:
            assert id(call) in contained, "an `ssot.advance` escapes the contained S5 hook (§22.7)"


class TestReadStoredRecord:
    """C5 NEW-F (GAP-1d): the idempotent re-drive's record loader returns None (never raises) on a
    missing or corrupt record, so `_run_artifact` raises a clear `DriverError` instead of
    `ir.unwrap_ir(None)` → TypeError. A pure unit — no grounding, no compose, no pandoc."""

    AID = "a-0000000000000000"

    def _store(self, tmp_path) -> WorkspaceStore:
        store = WorkspaceStore(tmp_path / "ws")
        store.ensure_layout()
        return store

    def test_missing_record_returns_none(self, tmp_path):
        assert driver._read_stored_record(self._store(tmp_path), self.AID) is None

    def test_corrupt_record_returns_none(self, tmp_path):
        store = self._store(tmp_path)
        store.output_path(self.AID).write_bytes(b"{ not valid json")
        assert driver._read_stored_record(store, self.AID) is None

    def test_valid_record_returns_the_mapping(self, tmp_path):
        store = self._store(tmp_path)
        store.output_path(self.AID).write_bytes(b'{"body": "x", "binding": {}}')
        assert driver._read_stored_record(store, self.AID) == {"body": "x", "binding": {}}


class TestGroundingAbstain:
    """DR-6 (§6.5/§19; D1, §2.4): the opt-in item-level abstain. Under grounding_posture=block
    ONLY, a PERSISTED Review-1 record with an advisory `grounding` concern makes THIS item abstain
    with the §6.5/§19 `grounding-uncovered` GENERATION block; every other case FAILS OPEN (ships).
    A pure unit on the seam — no grounding, no compose, no pandoc (mirrors TestReadStoredRecord)."""

    AID = "a-0000000000000000"

    def _store(self, tmp_path) -> WorkspaceStore:
        store = WorkspaceStore(tmp_path / "ws")
        store.ensure_layout()
        return store

    def _item(self, posture: str | None):
        # A real folded EffectiveSelection carries grounding_posture; the seam reads item.m3 + id.
        run = {"grounding_posture": posture} if posture is not None else None
        return SimpleNamespace(m3=resolve_selection(run=run), artifact_id=self.AID)

    def _persist_grounding_concern(self, store: WorkspaceStore) -> None:
        # A faithful §19 Review-1 record whose advisory `grounding` check reads `concern`.
        checks = {name: {"status": "pass", "note": ""} for name in review.ARTIFACT_CHECKS}
        checks["grounding"] = {"status": "concern", "note": "advisory coverage gap"}
        record = review.build_review_record(
            review_type="artifact",
            reviewed_id=self.AID,
            reviewed_digest="0" * 64,
            assessment={"verdict": "concerns", "checks": checks, "summary": "advisory review"},
        )
        assert review.persist_review_record(store, record)

    def test_block_with_persisted_grounding_concern_abstains(self, tmp_path):
        # (e) block + a persisted grounding concern → the item surfaces `grounding-uncovered`.
        store = self._store(tmp_path)
        self._persist_grounding_concern(store)
        with pytest.raises(driver.DriverError) as excinfo:
            driver._grounding_abstain_check(store, self._item("block"))
        assert excinfo.value.stage_code == results.CODE_GROUNDING_UNCOVERED
        spec = results.CODES[results.CODE_GROUNDING_UNCOVERED]
        assert spec.tier == results.TIER_GENERATION and spec.statuses == ("block",)

    def test_block_with_no_record_ships_and_is_redrive_stable(self, tmp_path):
        # (g) S2 fail-open: block + NO persisted record → SHIPS, identically on a second (re-drive)
        # call. Record-absent is deterministically SHIP (fail-OPEN) — the reviewer-pinned invariant.
        store = self._store(tmp_path)
        assert not store.review_path(self.AID).exists()
        assert driver._grounding_abstain_check(store, self._item("block")) is None
        assert driver._grounding_abstain_check(store, self._item("block")) is None

    def test_default_warn_never_abstains_even_with_a_concern(self, tmp_path):
        # control: default `warn` (today's behavior) NEVER abstains, even with a concern present.
        store = self._store(tmp_path)
        self._persist_grounding_concern(store)
        assert driver._grounding_abstain_check(store, self._item(None)) is None

    def test_block_with_a_pass_grounding_check_ships(self, tmp_path):
        # fail-CLOSED only on `concern`: a persisted record whose grounding is `pass` SHIPS.
        store = self._store(tmp_path)
        checks = {name: {"status": "pass", "note": ""} for name in review.ARTIFACT_CHECKS}
        record = review.build_review_record(
            review_type="artifact",
            reviewed_id=self.AID,
            reviewed_digest="0" * 64,
            assessment={"verdict": "pass", "checks": checks, "summary": "clean"},
        )
        assert review.persist_review_record(store, record)
        assert driver._grounding_abstain_check(store, self._item("block")) is None

    def test_block_with_a_malformed_record_fails_open(self, tmp_path):
        # a partial/corrupt record fails OPEN (ships) — `.get(...)` never raises on a bad shape.
        store = self._store(tmp_path)
        store.review_path(self.AID).write_bytes(b"{ not valid json")
        assert driver._grounding_abstain_check(store, self._item("block")) is None

    def test_block_with_a_valid_json_non_object_record_ships(self, tmp_path):
        # N2 fail-open control: a valid-JSON NON-object record (the isinstance Mapping guard)
        # SHIPS — the seam returns None.
        store = self._store(tmp_path)
        store.review_path(self.AID).write_bytes(b"[]")
        assert driver._grounding_abstain_check(store, self._item("block")) is None

    def test_block_with_a_partial_dict_record_ships(self, tmp_path):
        # N2 fail-open control: a partial dict (grounding status missing) SHIPS — the nested
        # `.get(...)` guards never raise on an incomplete shape.
        store = self._store(tmp_path)
        store.review_path(self.AID).write_bytes(b'{"checks":{"grounding":{}}}')
        assert driver._grounding_abstain_check(store, self._item("block")) is None
