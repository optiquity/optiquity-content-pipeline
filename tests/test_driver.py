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
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import driver, review
from pipeline.api import results
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.m3 import resolve_selection
from pipeline.outline import normalize_outline, outline_digest
from pipeline.outline_store import put_outline
from pipeline.plan import Plan, PlanItem
from pipeline.spine import registry_for
from pipeline.ssot import Ssot
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


class TestOutlineBriefLoad:
    """DR-3 Commit 6 (horn (a)): `_run_artifact` loads the DRIVING outline brief from the
    pre-compose outline store by `item.outline_digest` and sets it on the `ComposeRequest`. A unit
    on the driver WIRING — grounding + compose are monkeypatched (no live call, no pandoc); the
    real `compose_artifact` digest-fidelity guard is covered in `tests/test_compose.py`."""

    MD = "# Drive\n\n- point a\n- point b\n"

    def _harness(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        store.ensure_layout()
        claims = registry_for(store)
        ssot = Ssot(store.root / "ssot.csv")
        digest = outline_digest(self.MD)
        preimage = build_artifact_preimage(
            topic=EntryBinding("t"),
            persona=EntryBinding("p"),
            format=EntryBinding("f"),
            voice=EntryBinding("v"),
            goals=[],
            source_subset=["s"],
            source_commit={"s": "c0ffee0123ab"},
            outline_digest=digest,
        )
        item = PlanItem(
            artifact_id=mint_artifact_id(preimage),
            preimage=preimage,
            topic="t",
            persona="p",
            format="f",
            voice="v",
            goals=(),
            m3=resolve_selection(run=None),
            deliverables=(),
            outline_digest=digest,
        )
        plan = Plan(
            workspace="ws",
            recipe="r",
            source_subset=("s",),
            source_commit={"s": "c0ffee0123ab"},
            items=(item,),
            plan_hash="feedfacefeedface",
            warnings=(),
        )
        return store, claims, ssot, plan, item

    def _patch_stages(self, monkeypatch):
        monkeypatch.setattr(
            driver,
            "ground_item",
            lambda **kw: SimpleNamespace(
                status="ok", publishable_facts=("F",), facts=("F",), commit_map={}
            ),
        )
        monkeypatch.setattr(
            driver,
            "resolve_compose",
            lambda env, sel: SimpleNamespace(
                topic=SimpleNamespace(values={}, entry_id="t"),
                persona=SimpleNamespace(values={}, entry_id="p"),
                format=SimpleNamespace(values={}, entry_id="f"),
                voice=SimpleNamespace(values={}, entry_id="v"),
                goals=(),
                lexicon=None,  # DR-2: the real ComposeResolution.lexicon (None = no lexicon)
                # C5: the real ComposeResolution.recipe (ResolvedEntry). No `diagram_style` set →
                # the "" floor → the driver resolves the framework `default` style (pinned dot).
                recipe=SimpleNamespace(effective={}),
            ),
        )

    def _run(self, store, claims, ssot, plan, item):
        return driver._run_artifact(
            # C5: `_run_artifact` resolves the diagram-style tool via `env.resolver` — stub it to
            # return the framework default (pinned dot), matching the real CascadeEnv.resolver.
            env=SimpleNamespace(
                workspace="ws",
                resolver=SimpleNamespace(
                    resolve=lambda coll, eid: SimpleNamespace(effective={"tool": "dot"})
                ),
            ),
            store=store,
            claims=claims,
            ssot=ssot,
            plan=plan,
            item=item,
            pool=(),
            adapters={},
            source_repos={"s": "repo"},
            now=date.today(),
            model=None,
            log=lambda _m: None,
        )

    def test_brief_is_loaded_from_the_store_and_set_on_the_request(self, tmp_path, monkeypatch):
        store, claims, ssot, plan, item = self._harness(tmp_path)
        put_outline(store, self.MD)  # ingest the DRIVING outline into the pre-compose store
        self._patch_stages(monkeypatch)

        class _Stop(Exception):
            pass

        captured = {}

        def _capture(request, **_kw):
            captured["brief"] = request.outline_brief
            captured["preimage_digest"] = request.preimage.get("outline-digest")
            raise _Stop()

        monkeypatch.setattr(driver, "compose_artifact", _capture)
        with pytest.raises(_Stop):
            self._run(store, claims, ssot, plan, item)
        # the driver loaded N(md) by the item's digest and set it on the ComposeRequest, and the
        # request's identity carries the SAME digest (the fidelity guard would bind them).
        assert captured["brief"] == normalize_outline(self.MD)
        assert captured["preimage_digest"] == item.outline_digest

    def test_missing_outline_is_a_loud_driver_error(self, tmp_path, monkeypatch):
        store, claims, ssot, plan, item = self._harness(tmp_path)
        # deliberately do NOT put the outline -> the store lacks item.outline_digest.
        self._patch_stages(monkeypatch)
        monkeypatch.setattr(
            driver, "compose_artifact", lambda *a, **k: pytest.fail("compose must not run")
        )
        with pytest.raises(driver.DriverError, match="no such outline"):
            self._run(store, claims, ssot, plan, item)


class _FormatStructuralEnvStub:
    """A minimal env exposing only `resolver.resolve('platforms', …).effective` — the surface
    `_platform_format_structural` reads (DR-4 C8, M2-EXCLUDED: it reads the raw entry, never bound
    values)."""

    def __init__(self, effective: dict) -> None:
        self._effective = effective

    @property
    def resolver(self):
        return self

    def resolve(self, collection: str, key: str):
        assert collection == "platforms"
        return SimpleNamespace(effective=self._effective)


_JOURNAL_FS = {
    "academic-paper": [
        {"rule": "presence", "axis": "role", "value": "acknowledgements",
         "required": False, "severity": "error"},
    ],
    "readme": [
        {"rule": "length", "axis": "role", "value": "abstract",
         "min_len": 0, "max_len": 200, "severity": "error"},
    ],
}


class TestPlatformFormatStructural:
    """DR-4 C8 obligation 3 (pinned-format scoping): `_platform_format_structural` threads ONLY THIS
    artifact's format entry — an unrelated venue-tightening never enters this fit's identity."""

    def test_pinned_format_returns_a_single_entry_scoped_map(self):
        env = _FormatStructuralEnvStub({"format_structural": _JOURNAL_FS})
        fs, defaults = driver._platform_format_structural(env, "journal-b", "academic-paper")
        # SINGLE-ENTRY: only the pinned `academic-paper` schema; `readme` (a sibling) never leaks.
        assert fs == {"academic-paper": _JOURNAL_FS["academic-paper"]}
        assert "readme" not in fs
        assert defaults == {}

    def test_an_absent_format_returns_the_empty_floor(self):
        # Obligation 3: format B (here `short-opinion-post`) has NO venue tightening on this
        # platform -> the resolver returns `({}, {})`, so its preimage omits `structural` entirely.
        env = _FormatStructuralEnvStub({"format_structural": _JOURNAL_FS})
        got = driver._platform_format_structural(env, "journal-b", "short-opinion-post")
        assert got == ({}, {})

    def test_a_platform_with_no_format_structural_attribute_returns_empty(self):
        # A floor platform (the shipped set): no `format_structural` key -> `({}, {})`, gate INERT.
        env = _FormatStructuralEnvStub({"hard_limits": {"max_chars": 280}})
        assert driver._platform_format_structural(env, "github", "readme") == ({}, {})

    def test_an_empty_format_structural_map_returns_empty(self):
        # An explicit floor `{}` (the schema default) also resolves to `({}, {})`.
        env = _FormatStructuralEnvStub({"format_structural": {}})
        assert driver._platform_format_structural(env, "github", "readme") == ({}, {})


class TestReconcileBlockSurfacesBothConcernSets:
    """DR-4 C8: a venue-structural reconcile block surfaces `section-conformance-violation` as the
    threaded `stage_code` AND carries BOTH concern-sets (`structural_violations` + `blocked_limits`)
    in the DriverError message — proven over the REAL `_run_deliverable` raise-site."""

    def test_structural_block_raises_with_both_concern_sets_and_threaded_code(self, monkeypatch):
        from pipeline.reconcile import CODE_SECTION_CONFORMANCE_VIOLATION, ReconcileOutcome

        # The code is a real `("block",)` taxonomy code, so the driver's guard threads it.
        assert CODE_SECTION_CONFORMANCE_VIOLATION in results.ALL_CODES

        # Stubs: reach the reconcile-block raise WITHOUT a live thread (no grounding/compose).
        monkeypatch.setattr(
            driver, "resolve_render", lambda *a, **k: SimpleNamespace(advisories={})
        )
        monkeypatch.setattr(driver, "_platform_hard_limits", lambda *a, **k: ({}, {}))
        monkeypatch.setattr(
            driver,
            "_platform_format_structural",
            lambda *a, **k: ({"readme": _JOURNAL_FS["readme"]}, {}),
        )
        block = ReconcileOutcome(
            status="block",
            code=CODE_SECTION_CONFORMANCE_VIOLATION,
            fitted_id=None,
            fitted_ir=None,
            fit_binding=None,
            preimage={},
            digest="x",
            is_noop=False,
            dropped_facts=(),
            blocked_limits=("max_chars",),
            structural_violations=("forbidden venue section role 'acknowledgements' is PRESENT",),
            attempts=0,
            violations=(),
            transport_result=None,
        )
        monkeypatch.setattr(driver, "reconcile", lambda *a, **k: block)

        ssot = SimpleNamespace(register=lambda *a, **k: None)
        store = SimpleNamespace(
            output_path=lambda *_: SimpleNamespace(relative_to=lambda *_: "p"),
            root="/",
        )
        d = SimpleNamespace(
            deliverable_id="del-x",
            platform="journal-b",
            language="en",
            output_type="md",
            presentation="plain",
            reconcile_strategy="pass",
        )
        item = SimpleNamespace(artifact_id="a-0000000000000000", format="readme")

        with pytest.raises(driver.DriverError) as exc:
            driver._run_deliverable(
                env=None,
                store=store,
                claims=None,
                ssot=ssot,
                compose=None,
                recipe="explainer-post",
                item=item,
                deliverable=d,
                canonical_ir={},
                source_commit_digest="c",
                model=None,
                log=lambda *_: None,
            )
        # The threaded stage code is the §21.7 taxonomy code (a coded block, never a bare hint).
        assert exc.value.stage_code == CODE_SECTION_CONFORMANCE_VIOLATION
        msg = str(exc.value)
        # BOTH concern-sets surface in the message (the early-return refactor's payload).
        assert "acknowledgements" in msg and "structural_violations=" in msg
        assert "blocked_limits=('max_chars',)" in msg
