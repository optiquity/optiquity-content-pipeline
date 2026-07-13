"""Step-31 tests: folios — the pure purposeful set (§9.1–§9.3, §21.2, §20 F6, A4-4).

Acceptance under test here (plan step-31): a folio holds ZERO folio-level state (no
dimension/ordering/schedule field — asserted by record shape AND view/fact introspection,
A4-4); `create-folio` is system-assigned + explicit + workspace-scoped, never auto-created
(F6); `add-to-folio` §21.2 semantics — dedupe no-op `ok`, differing pin/role → atomic
replacing-rename update preserving `added_ts` → `member-updated`, membership append-only,
intra-workspace enforcement, pins FROZEN in id-form (B4-2/FR3); concurrent differing updates →
exactly one atomic winner and BOTH callers get `member-updated`; the reverse index is DERIVED;
and `pipeline.folios` imports no status-authority module (INV-CORRECTNESS, §22.7).
"""

import ast
import dataclasses
import inspect
import json
import multiprocessing
from pathlib import Path

import pytest

import pipeline.folios as folios_module
from pipeline.folios import (
    CreateFolioOutcome,
    CrossWorkspaceMemberError,
    FolioExistsError,
    FolioNotFoundError,
    FolioView,
    MemberFact,
    MemberShapeError,
    MemberSpec,
    add_to_folio,
    create_folio,
    folio_exists,
    folios_for_artifact,
    get_folio,
    list_folio_members,
)
from pipeline.ids import parse_id
from pipeline.store import WorkspaceStore

# §7.4 literal id examples. ART/ART2 are bare artifact-ids (folio membership is
# artifact-level, F3); DEL* are deliverable-ids usable as FROZEN member pins (§9.2).
ART = "a-9f3c07d21b44e8aa"
ART2 = "a-1234567890abcdef"
DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain"
DEL_X = "a-9f3c07d21b44e8aa.x.en.docx.plain"
DEL_REDDIT = "a-9f3c07d21b44e8aa.reddit.en.docx.plain"
DEL_REV = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain_0123456789ab"  # a revision-qualified pin

_SPAWN = multiprocessing.get_context("spawn")
_FIXED = 1000.0  # an injected epoch-seconds clock — the test owns `added_ts`


@pytest.fixture()
def store(tmp_path):
    return WorkspaceStore(tmp_path / "ws")


def materialize(store: WorkspaceStore, artifact_id: str) -> None:
    """Stand in an artifact-canonical record so the intra-workspace add check passes (§9.2)."""
    store.output_path(artifact_id).write_bytes(b"{}\n")


# ---------------------------------------------------------------------------
# create-folio (§9.3, §20 F6): system-assigned, explicit, empty, distinct.
# ---------------------------------------------------------------------------


class TestCreateFolio:
    def test_mints_a_workspace_scoped_folio_id_and_an_empty_folio(self, store):
        out = create_folio(store, purpose="launch week")
        assert isinstance(out, CreateFolioOutcome) and out.created
        assert parse_id(out.folio_id).family == "folio"  # f-<hex12> (§7.1 F8)
        assert folio_exists(store, out.folio_id)
        assert list_folio_members(store, out.folio_id) == ()  # empty — nothing auto-added (F6)

    def test_two_creates_yield_distinct_folios(self, store):
        a = create_folio(store, purpose="same purpose")
        b = create_folio(store, purpose="same purpose")
        assert a.folio_id != b.folio_id  # an actor may hold many empty folios (§9.1)

    def test_same_nonce_is_the_idempotent_recreate(self, store):
        a = create_folio(store, purpose="p", folio_type="repo-docs", nonce="seed-1")
        b = create_folio(store, purpose="p", folio_type="repo-docs", nonce="seed-1")
        assert a.folio_id == b.folio_id
        assert a.created and not b.created

    def test_id_collision_with_a_different_record_is_loud(self, store, monkeypatch):
        # The purpose/type are part of the mint seed, so distinct folios never share an id in
        # practice; this guard is the defensive backstop for a hex12 digest collision. Force one
        # by pinning the mint to a constant id: the second, differing record is refused loudly
        # (never silent reuse — the §7.4 preimage-mismatch discipline).
        monkeypatch.setattr(folios_module, "mint_folio_id", lambda seed: "f-abcabcabcabc")
        create_folio(store, purpose="p")
        with pytest.raises(FolioExistsError):
            create_folio(store, purpose="DIFFERENT")

    def test_empty_purpose_is_refused(self, store):
        with pytest.raises(folios_module.FolioError):
            create_folio(store, purpose="")

    def test_folio_type_is_recorded_and_surfaced(self, store):
        out = create_folio(store, purpose="docs", folio_type="repo-docs")
        assert get_folio(store, out.folio_id).folio_type == "repo-docs"


# ---------------------------------------------------------------------------
# add-to-folio (§21.2): dedupe / member-updated / append-only / isolation / pins.
# ---------------------------------------------------------------------------


class TestAddToFolio:
    def _folio_with_artifact(self, store, *artifact_ids):
        for art in artifact_ids:
            materialize(store, art)
        return create_folio(store, purpose="p").folio_id

    def test_fresh_add_then_identical_readd_dedupes_to_ok(self, store):
        folio = self._folio_with_artifact(store, ART)
        spec = MemberSpec(ART, role="readme")
        (first,) = add_to_folio(store, folio, [spec], clock=lambda: _FIXED)
        assert first.code == "ok" and first.created
        (again,) = add_to_folio(store, folio, [spec], clock=lambda: 5.0)
        assert again.code == "ok" and not again.created  # idempotent dedupe no-op (§21.2)

    def test_differing_pin_is_an_atomic_update_preserving_added_ts(self, store):
        folio = self._folio_with_artifact(store, ART)
        add_to_folio(store, folio, [MemberSpec(ART, pin=DEL)], clock=lambda: _FIXED)
        (updated,) = add_to_folio(store, folio, [MemberSpec(ART, pin=DEL_X)], clock=lambda: 9.0)
        assert updated.code == "member-updated" and not updated.created
        (fact,) = list_folio_members(store, folio)
        assert fact.pin == DEL_X  # last write wins
        assert fact.added_ts == _FIXED  # original added_ts PRESERVED across the update (§21.2)

    def test_pin_is_frozen_in_id_form_and_stored_verbatim(self, store):
        folio = self._folio_with_artifact(store, ART)
        add_to_folio(store, folio, [MemberSpec(ART, pin=DEL_REV)], clock=lambda: _FIXED)
        # The exact deliverable-id string, revision qualifier and all, is stored unchanged and
        # never re-resolved (B4-2/FR3) — read it straight off the marker.
        marker = store.folio_member_path(folio, ART)
        assert json.loads(marker.read_bytes())["pin"] == DEL_REV
        assert get_folio(store, folio).members[0].pin == DEL_REV

    def test_no_auto_create_add_to_missing_folio_refused(self, store):
        materialize(store, ART)
        with pytest.raises(FolioNotFoundError):
            add_to_folio(store, "f-000000000000", [MemberSpec(ART)])

    def test_intra_workspace_cross_workspace_artifact_refused(self, store):
        folio = create_folio(store, purpose="p").folio_id  # ART2 never materialized here
        with pytest.raises(CrossWorkspaceMemberError):
            add_to_folio(store, folio, [MemberSpec(ART2)])

    def test_a_bad_member_refuses_the_whole_batch_before_any_write(self, store):
        folio = self._folio_with_artifact(store, ART)  # ART ok, ART2 cross-workspace
        with pytest.raises(CrossWorkspaceMemberError):
            add_to_folio(store, folio, [MemberSpec(ART), MemberSpec(ART2)])
        assert list_folio_members(store, folio) == ()  # nothing written (validate-all-first)

    def test_pin_must_be_a_deliverable_id(self, store):
        folio = self._folio_with_artifact(store, ART)
        with pytest.raises(MemberShapeError):
            add_to_folio(store, folio, [MemberSpec(ART, pin=ART)])  # a bare artifact-id, not a pin

    def test_membership_is_artifact_level_only(self, store):
        materialize(store, ART)
        folio = create_folio(store, purpose="p").folio_id
        with pytest.raises(MemberShapeError):
            add_to_folio(store, folio, [MemberSpec(DEL)])  # a deliverable-id is not a member

    def test_membership_is_append_only_no_removal_verb_exists(self):
        # §9.2/§27.3: member removal/supersede is a registered open item — the module ships no
        # removal at all. A grep-able acceptance: nothing named remove/delete/drop is public.
        public = set(folios_module.__all__)
        assert not any(v in name.lower() for name in public for v in ("remove", "delete", "drop"))

    def test_artifact_ids_string_sugar(self, store):
        folio = self._folio_with_artifact(store, ART)
        (out,) = add_to_folio(store, folio, [ART])  # bare-string sugar (§21.2 artifact_ids)
        assert out.code == "ok"
        assert list_folio_members(store, folio)[0].role is None


# ---------------------------------------------------------------------------
# Concurrent differing updates → one atomic winner, both callers `member-updated`.
# ---------------------------------------------------------------------------


def _add_racer(root_str, folio_id, artifact_id, pin, barrier, queue):
    from pipeline.folios import MemberSpec, add_to_folio
    from pipeline.store import WorkspaceStore

    try:
        store = WorkspaceStore(Path(root_str))
        barrier.wait(timeout=60)
        (outcome,) = add_to_folio(store, folio_id, [MemberSpec(artifact_id, pin=pin)])
        queue.put((pin, outcome.code))
    except Exception as exc:  # noqa: BLE001 — any other outcome is a dirty failure
        queue.put((pin, f"ERROR:{type(exc).__name__}:{exc}"))


class TestConcurrentUpdate:
    def test_concurrent_differing_updates_one_winner_both_member_updated(self, tmp_path):
        root = tmp_path / "ws"
        store = WorkspaceStore(root)
        materialize(store, ART)
        folio = create_folio(store, purpose="race").folio_id
        add_to_folio(store, folio, [MemberSpec(ART, pin=DEL)], clock=lambda: _FIXED)  # seed marker

        racers = [DEL_X, DEL_REDDIT]  # two DIFFERING updates of the one member
        barrier = _SPAWN.Barrier(len(racers))
        queue = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(target=_add_racer, args=(str(root), folio, ART, pin, barrier, queue))
            for pin in racers
        ]
        for p in procs:
            p.start()
        results = dict(queue.get(timeout=120) for _ in racers)
        for p in procs:
            p.join(timeout=60)

        assert not any(str(code).startswith("ERROR") for code in results.values()), results
        # BOTH callers get member-updated — never silence (§21.2 acceptance).
        assert set(results.values()) == {"member-updated"}
        # Exactly ONE atomic winner: the marker is a COMPLETE record (never torn), its pin is
        # one of the two racers', and the original added_ts survived (last-writer-wins atomic).
        record = json.loads(store.folio_member_path(folio, ART).read_bytes())
        assert record["pin"] in set(racers)
        assert record["added_ts"] == _FIXED


# ---------------------------------------------------------------------------
# Discovery: get folio / list members / the DERIVED reverse index.
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_get_folio_exposes_records_and_member_facts(self, store):
        materialize(store, ART)
        folio = create_folio(store, purpose="p", folio_type="repo-docs").folio_id
        add_to_folio(store, folio, [MemberSpec(ART, pin=DEL, role="readme")], clock=lambda: _FIXED)
        view = get_folio(store, folio)
        assert isinstance(view, FolioView)
        assert view.purpose == "p" and view.folio_type == "repo-docs"
        assert view.provenance == "instance"
        (fact,) = view.members
        assert fact.artifact_id == ART and fact.added_ts == _FIXED
        assert fact.pin == DEL and fact.role == "readme"

    def test_list_members_is_deterministic_and_stable(self, store):
        for art in (ART, ART2):
            materialize(store, art)
        folio = create_folio(store, purpose="p").folio_id
        add_to_folio(store, folio, [MemberSpec(ART2), MemberSpec(ART)])
        assert [m.artifact_id for m in list_folio_members(store, folio)] == sorted([ART, ART2])

    def test_reverse_index_is_derived_across_folios(self, store):
        materialize(store, ART)
        f1 = create_folio(store, purpose="a").folio_id
        f2 = create_folio(store, purpose="b").folio_id
        create_folio(store, purpose="c")  # a folio ART does NOT join
        add_to_folio(store, f1, [MemberSpec(ART)])
        add_to_folio(store, f2, [MemberSpec(ART)])
        assert folios_for_artifact(store, ART) == tuple(sorted([f1, f2]))  # many-to-many (§9.2)

    def test_get_missing_folio_is_not_found(self, store):
        with pytest.raises(FolioNotFoundError):
            get_folio(store, "f-abcabcabcabc")


# ---------------------------------------------------------------------------
# A4-4: ZERO folio-level dimension / ordering / schedule state, ever.
# ---------------------------------------------------------------------------


class TestZeroFolioLevelState:
    _BANNED = (
        "rendering_intent",
        "ordering",
        "schedule",
        "suggested_order",
        "platform",
        "language",
        "output_type",
        "presentation",
    )

    def test_folio_record_carries_only_collection_intrinsic_keys(self, store):
        out = create_folio(store, purpose="p", folio_type="repo-docs")
        record = json.loads((store.folios_dir / out.folio_id / "folio.json").read_bytes())
        assert set(record) <= {"id", "purpose", "folio_type", "provenance"}  # §9.1 — nothing else
        assert not (set(record) & set(self._BANNED))

    def test_folio_view_and_member_fact_have_no_dimension_or_ordering_field(self):
        view_fields = {f.name for f in dataclasses.fields(FolioView)}
        fact_fields = {f.name for f in dataclasses.fields(MemberFact)}
        assert view_fields == {"folio_id", "purpose", "folio_type", "provenance", "members"}
        assert fact_fields == {"artifact_id", "added_ts", "pin", "role"}
        assert not (view_fields & set(self._BANNED)) and not (fact_fields & set(self._BANNED))

    def test_no_rendering_intent_token_in_the_module(self):
        # The grep-able headline acceptance: verify #2 is `grep rendering_intent pipeline/` → 0.
        source = inspect.getsource(folios_module)
        assert "rendering_intent" not in source


# ---------------------------------------------------------------------------
# INV-CORRECTNESS (§22.7): folios ride markers + atomics, never the status authority.
# ---------------------------------------------------------------------------


class TestNoStatusAuthorityCoupling:
    def test_module_imports_no_status_authority_code(self):
        source = inspect.getsource(folios_module)
        tree = ast.parse(source)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
        assert not any("ssot" in name.lower() for name in names), names

    def test_no_status_authority_token_in_the_source(self):
        # Verify #7: `grep -rn ssot pipeline/folios.py` expects no match (case-sensitive lower).
        assert "ssot" not in inspect.getsource(folios_module)
