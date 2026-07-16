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

from pipeline import driver
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
