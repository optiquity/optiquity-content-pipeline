"""Step-22 tests: the tracking SSOT v1 (docs/design.md §24) — two row kinds, the monotonic
CSV single-writer, and the derived `state.md` projection.

Under test (plan step 22 acceptance + the mandated coverage):

- **Both row kinds' full lifecycles** — artifact `planned→composed→artifact-reviewed`;
  deliverable `planned→fitted→rendered→deliverable-reviewed→ready` (§24, PA-4).
- **Monotonic advance** — a lower-rank write is a typed, logged rejection (`regressed`);
  an equal-status write is an idempotent no-op; a wrong-kind status is rejected (PC4);
  an unknown id is rejected. NONE of these raise — the SSOT never breaks control flow
  (§22.7).
- **`blocked` is an annotation, terminal-until-redriven** — it never regresses the status;
  a forward advance (a re-drive) clears it (§24).
- **One item, one row** — an advance for id X never touches row Y (PC4); revisions are new
  rows only (FR4/FR7.6).
- **The write-only contract** — no per-id read predicate is exported; the correctness plane
  (`store`/`claims`/`spine`) imports no ssot module, and `ssot` is a leaf that imports the
  `store` primitive (direction verified); the FORBIDDEN="ssot" lint pattern catches the name.
- **The single writer** — concurrent multiprocess advances funnel through the file lock and
  the atomic replacing-rename swap: no torn CSV, no lost update (§22.3/PC4b).
- **The deriver** — CSV → status section is byte-deterministic across runs and byte-exact
  under `read_bytes().decode()` (the Python-3.12 `read_text(newline=)` pitfall the prior
  attempt hit).
- **Spine integration** — `drive()` with `ssot.advance_hook(...)` advances the right row at
  S5; a hook failure is contained and never breaks the drive (§22.7 S5 side-effect-only).
"""

import ast
import csv
import io
import multiprocessing
from pathlib import Path

import pytest

from pipeline.canonical import canonical_json_str
from pipeline.claims import ClaimRegistry
from pipeline.spine import WorkUnit, drive
from pipeline.ssot import (
    ARTIFACT_LIFECYCLE,
    COLUMNS,
    DELIVERABLE_LIFECYCLE,
    AdvanceOutcome,
    BlockOutcome,
    RegisterOutcome,
    Ssot,
    SsotError,
    derive_state,
)
from pipeline.store import WorkspaceStore

# §7.4 literal ids (as used by the step-20/21 batteries).
ART = "a-9f3c07d21b44e8aa"
ART2 = "a-1122334455667788"
DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain"
SER_REV = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain_9c2e11ab34cd"

_SPAWN = multiprocessing.get_context("spawn")

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "pipeline"


class ManualClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def _read_raw(csv_path: Path) -> tuple[list[str], dict[str, list[str]]]:
    """Parse the CSV INDEPENDENTLY of the module (no `ssot._read_rows`): returns the header
    and an id→record map. Also the torn-file oracle — every record must have exactly the
    column count."""
    text = csv_path.read_bytes().decode("utf-8")
    reader = csv.reader(io.StringIO(text, newline=""))
    rows = list(reader)
    header = rows[0]
    records: dict[str, list[str]] = {}
    for record in rows[1:]:
        if not record:
            continue
        assert len(record) == len(header), f"torn/short record: {record!r}"
        records[record[1]] = record  # column 1 is `id`
    return header, records


def _status_of(csv_path: Path, id_str: str) -> str:
    _, records = _read_raw(csv_path)
    return records[id_str][COLUMNS.index("status")]


def _block_of(csv_path: Path, id_str: str) -> str:
    _, records = _read_raw(csv_path)
    return records[id_str][COLUMNS.index("block_reason")]


# ---------------------------------------------------------------------------
# The schema: two row kinds, the §24 column set.
# ---------------------------------------------------------------------------


class TestSchema:
    def test_column_set_is_the_section24_shape(self):
        assert COLUMNS == (
            "row_kind",
            "id",
            "coordinates",
            "source_commit",
            "status",
            "output_path",
            "block_reason",
        )

    def test_the_two_lifecycles_are_the_pa4_ladders(self):
        assert ARTIFACT_LIFECYCLE == ("planned", "composed", "artifact-reviewed")
        assert DELIVERABLE_LIFECYCLE == (
            "planned",
            "fitted",
            "rendered",
            "deliverable-reviewed",
            "ready",
        )
        # Both ladders share the entry status; the two ladders otherwise never overlap in a
        # progress-bearing status (a single row can carry only its kind's statuses).
        assert ARTIFACT_LIFECYCLE[0] == DELIVERABLE_LIFECYCLE[0] == "planned"
        assert set(ARTIFACT_LIFECYCLE[1:]).isdisjoint(DELIVERABLE_LIFECYCLE[1:])

    def test_register_writes_the_header_and_one_planned_row(self, tmp_path):
        csv_path = tmp_path / "ssot.csv"
        ssot = Ssot(csv_path=csv_path)
        assert ssot.register(ART, "artifact", coordinates="topic/persona") == RegisterOutcome(
            ART, "registered"
        )
        header, records = _read_raw(csv_path)
        assert header == list(COLUMNS)
        assert records[ART][COLUMNS.index("status")] == "planned"
        assert records[ART][COLUMNS.index("row_kind")] == "artifact"

    def test_register_is_idempotent_one_item_one_row(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact", coordinates="first")
        # A second register never mutates the existing row (returns `exists`).
        assert ssot.register(ART, "artifact", coordinates="second").code == "exists"
        _, records = _read_raw(ssot.csv_path)
        assert len(records) == 1
        assert records[ART][COLUMNS.index("coordinates")] == "first"


class TestRegisterValidation:
    def test_unknown_kind_is_refused_at_planning_time(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        with pytest.raises(SsotError):
            ssot.register(ART, "bogus")

    def test_id_level_must_match_the_declared_kind(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        with pytest.raises(SsotError):
            ssot.register(DEL, "artifact")  # deliverable id, artifact kind
        with pytest.raises(SsotError):
            ssot.register(ART, "deliverable")  # artifact id, deliverable kind

    def test_malformed_id_is_refused(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        with pytest.raises(SsotError):
            ssot.register("not-an-id", "artifact")


# ---------------------------------------------------------------------------
# Both row kinds' full lifecycles.
# ---------------------------------------------------------------------------


class TestLifecycles:
    def test_artifact_row_full_lifecycle(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        first = ssot.advance(ART, "composed")
        assert first == AdvanceOutcome(ART, "advanced", "planned", "composed")
        assert ssot.advance(ART, "artifact-reviewed").code == "advanced"
        assert _status_of(ssot.csv_path, ART) == "artifact-reviewed"

    def test_deliverable_row_full_lifecycle(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(DEL, "deliverable")
        for status in ("fitted", "rendered", "deliverable-reviewed", "ready"):
            assert ssot.advance(DEL, status).code == "advanced"
        assert _status_of(ssot.csv_path, DEL) == "ready"


# ---------------------------------------------------------------------------
# Monotonic advance: regression rejected, equal idempotent, wrong-kind, unknown.
# ---------------------------------------------------------------------------


class TestMonotonicAdvance:
    def test_regression_is_rejected_and_logged_never_raised(self, tmp_path, caplog):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        ssot.advance(ART, "artifact-reviewed")
        with caplog.at_level("WARNING", logger="pipeline.ssot"):
            outcome = ssot.advance(ART, "composed")  # rank 1 < rank 2 — stale
        assert outcome.code == "regressed"
        assert _status_of(ssot.csv_path, ART) == "artifact-reviewed"  # unchanged
        assert any("regressed" in rec.message for rec in caplog.records)

    def test_equal_status_is_idempotent_no_write(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        ssot.advance(ART, "composed")
        before = ssot.csv_path.read_bytes()
        outcome = ssot.advance(ART, "composed")
        assert outcome.code == "idempotent"
        assert ssot.csv_path.read_bytes() == before  # byte-identical: nothing written

    def test_wrong_kind_status_is_rejected_pc4(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        ssot.register(DEL, "deliverable")
        # A deliverable status on an artifact row (and vice versa) — never a silent write.
        assert ssot.advance(ART, "fitted").code == "wrong-kind"
        assert ssot.advance(DEL, "composed").code == "wrong-kind"
        assert _status_of(ssot.csv_path, ART) == "planned"
        assert _status_of(ssot.csv_path, DEL) == "planned"

    def test_unknown_row_is_rejected_never_raised(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        outcome = ssot.advance(ART, "composed")  # never registered
        assert outcome == AdvanceOutcome(ART, "unknown-row", None, "composed")
        assert not ssot.csv_path.exists()  # no row invented


# ---------------------------------------------------------------------------
# `blocked`: an annotation, never a regression, terminal-until-redriven.
# ---------------------------------------------------------------------------


class TestBlocked:
    def test_block_annotates_without_touching_status(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(DEL, "deliverable")
        ssot.advance(DEL, "fitted")
        assert ssot.block(DEL, "hard-limit-exceeded") == BlockOutcome(
            DEL, "blocked", "hard-limit-exceeded"
        )
        assert _status_of(ssot.csv_path, DEL) == "fitted"  # status unchanged — not a regression
        assert _block_of(ssot.csv_path, DEL) == "hard-limit-exceeded"

    def test_block_is_idempotent_on_the_same_reason(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        assert ssot.block(ART, "empty-pool").code == "blocked"
        before = ssot.csv_path.read_bytes()
        assert ssot.block(ART, "empty-pool").code == "already-blocked"
        assert ssot.csv_path.read_bytes() == before

    def test_block_is_terminal_until_a_forward_advance_redrives_it(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        ssot.block(ART, "empty-pool")
        # Terminal: the status sits at planned with the annotation held.
        assert _status_of(ssot.csv_path, ART) == "planned"
        assert _block_of(ssot.csv_path, ART) == "empty-pool"
        # A re-drive that makes forward progress clears the block.
        assert ssot.advance(ART, "composed").code == "advanced"
        assert _block_of(ssot.csv_path, ART) == ""

    def test_block_on_unknown_row_is_rejected(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        assert ssot.block(ART, "empty-pool").code == "unknown-row"

    def test_empty_block_reason_is_refused(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        with pytest.raises(SsotError):
            ssot.block(ART, "")


# ---------------------------------------------------------------------------
# One item, one row — an advance for X never touches Y; revisions = new rows.
# ---------------------------------------------------------------------------


class TestPerItemRowIsolation:
    def test_advancing_one_row_never_touches_another(self, tmp_path):
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact", coordinates="A")
        ssot.register(DEL, "deliverable", coordinates="D")
        _, before = _read_raw(ssot.csv_path)
        del_row_before = before[DEL]
        ssot.advance(ART, "composed")
        _, after = _read_raw(ssot.csv_path)
        assert after[DEL] == del_row_before  # the deliverable row is byte-for-byte untouched
        assert after[ART][COLUMNS.index("status")] == "composed"

    def test_revisions_are_new_rows_only_old_row_untouched(self, tmp_path):
        # FR4/FR7.6: a serialize-revision deliverable is a NEW id → a NEW row; the baseline
        # row is never mutated into a revision.
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(DEL, "deliverable")
        ssot.advance(DEL, "rendered")
        ssot.register(SER_REV, "deliverable")  # the revision — a distinct fanout item
        ssot.advance(SER_REV, "fitted")
        _, records = _read_raw(ssot.csv_path)
        assert set(records) == {DEL, SER_REV}
        assert records[DEL][COLUMNS.index("status")] == "rendered"  # baseline untouched
        assert records[SER_REV][COLUMNS.index("status")] == "fitted"


# ---------------------------------------------------------------------------
# The write-only contract (§22.7 guardrail 3) + INV-CORRECTNESS direction.
# ---------------------------------------------------------------------------


def _imported_dotted_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module:
                names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


class TestWriteOnlyContract:
    def test_ssot_exports_no_per_id_read_predicate(self):
        import pipeline.ssot as ssot_module

        # No is_*/has_* predicate and no status-getter lookalike in the public surface.
        for name in ssot_module.__all__:
            assert not name.startswith(("is_", "has_")), name
            assert name.lower() not in {
                "status_of",
                "get_status",
                "statusof",
                "done",
                "ready",
                "lookup",
                "query",
                "get_row",
            }, name

    def test_ssot_public_methods_are_exactly_the_write_surface_plus_hook(self):
        # The ONLY per-id surface is write (register/advance/block) + the S5 hook factory.
        # No read method that returns a row's status for a caller to branch on. (Dataclass
        # field defaults like `lock_path` are data, not methods — filter to callables.)
        methods = {
            name for name, val in vars(Ssot).items() if not name.startswith("_") and callable(val)
        }
        assert methods == {"register", "advance", "advance_hook", "block"}

    def test_the_only_module_read_surface_is_the_whole_report(self):
        import pipeline.ssot as ssot_module

        # derive_state renders the WHOLE table (a human report, §22.7) — not a per-id fact.
        assert "derive_state" in ssot_module.__all__

    def test_correctness_modules_do_not_import_ssot(self):
        # Belt-and-suspenders to test_inv_correctness: the correctness plane never imports
        # an ssot-named module (the FORBIDDEN="ssot" lint pattern).
        for module in ("store.py", "claims.py", "spine.py"):
            names = _imported_dotted_names(PACKAGE_ROOT / module)
            offenders = [n for n in names if any("ssot" in seg.lower() for seg in n.split("."))]
            assert offenders == [], f"{module} imports ssot code: {offenders}"

    def test_ssot_is_a_leaf_importing_the_store_primitive(self):
        # Direction check: ssot → store (the write_replace primitive), store ⇏ ssot.
        ssot_imports = _imported_dotted_names(PACKAGE_ROOT / "ssot.py")
        assert any(n.startswith("pipeline.store") for n in ssot_imports)
        store_imports = _imported_dotted_names(PACKAGE_ROOT / "store.py")
        assert not any("ssot" in seg.lower() for n in store_imports for seg in n.split("."))

    def test_module_name_is_caught_by_the_forbidden_pattern(self):
        # The lint's ssot-pattern must catch this module's name (guardrail 2 pre-wiring).
        forbidden = "ssot"
        assert any(forbidden in seg.lower() for seg in "pipeline.ssot".split("."))


# ---------------------------------------------------------------------------
# The single writer (§22.3/PC4b): concurrent advances, no torn CSV, no lost update.
# ---------------------------------------------------------------------------


def _advance_worker(csv_path_str: str, id_str: str, statuses: tuple[str, ...], barrier, queue):
    from pathlib import Path as _Path

    from pipeline.ssot import Ssot as _Ssot

    ssot = _Ssot(csv_path=_Path(csv_path_str))
    barrier.wait()
    codes = [ssot.advance(id_str, status).code for status in statuses]
    queue.put((id_str, codes))


class TestSingleWriter:
    def test_distinct_rows_all_advance_no_torn_csv(self, tmp_path):
        csv_path = tmp_path / "ssot.csv"
        ssot = Ssot(csv_path=csv_path)
        n_procs = 8
        ids = [f"a-{i:016x}" for i in range(n_procs)]
        for id_str in ids:
            ssot.register(id_str, "artifact")
        barrier = _SPAWN.Barrier(n_procs)
        queue = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(
                target=_advance_worker,
                args=(str(csv_path), id_str, ("composed", "artifact-reviewed"), barrier, queue),
            )
            for id_str in ids
        ]
        for p in procs:
            p.start()
        drained = [queue.get() for _ in ids]
        for p in procs:
            p.join(30)
            assert p.exitcode == 0
        # Every worker drove its own row all the way — no lost update.
        assert {id_str for id_str, _ in drained} == set(ids)
        header, records = _read_raw(csv_path)  # the torn-file oracle asserts column counts
        assert header == list(COLUMNS)
        assert set(records) == set(ids)
        for id_str in ids:
            assert records[id_str][COLUMNS.index("status")] == "artifact-reviewed"

    def test_concurrent_same_row_serializes_to_one_advance(self, tmp_path):
        csv_path = tmp_path / "ssot.csv"
        ssot = Ssot(csv_path=csv_path)
        ssot.register(ART, "artifact")
        n_procs = 8
        barrier = _SPAWN.Barrier(n_procs)
        queue = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(
                target=_advance_worker, args=(str(csv_path), ART, ("composed",), barrier, queue)
            )
            for _ in range(n_procs)
        ]
        for p in procs:
            p.start()
        outcomes = [queue.get() for _ in range(n_procs)]
        for p in procs:
            p.join(30)
            assert p.exitcode == 0
        codes = [code for _, (code,) in outcomes]
        # Exactly one worker made the forward write; the rest saw the equal status.
        assert codes.count("advanced") == 1
        assert codes.count("idempotent") == n_procs - 1
        assert _status_of(csv_path, ART) == "composed"


# ---------------------------------------------------------------------------
# The derived state.md projection: byte-deterministic, byte-exact reads.
# ---------------------------------------------------------------------------


class TestDeriveState:
    def _populated(self, tmp_path) -> Path:
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact", coordinates="topic/persona", source_commit="c0ffee")
        ssot.advance(ART, "composed")
        ssot.register(DEL, "deliverable", coordinates="topic/persona/linkedin")
        ssot.advance(DEL, "fitted")
        ssot.block(DEL, "hard-limit-exceeded")
        return ssot.csv_path

    def test_projection_is_byte_deterministic_across_runs(self, tmp_path):
        csv_path = self._populated(tmp_path)
        assert derive_state(csv_path) == derive_state(csv_path)

    def test_projection_reads_byte_exact_no_newline_pitfall(self, tmp_path):
        # The Python-3.12 pitfall: `Path.read_text` has no `newline=`. Prove the derivation
        # is identical whether or not the CSV ends with a trailing newline — read_bytes()
        # .decode() (not read_text(newline=...)) makes both byte-exact.
        csv_path = self._populated(tmp_path)
        raw = csv_path.read_bytes()
        with_nl = tmp_path / "with_nl.csv"
        without_nl = tmp_path / "without_nl.csv"
        with_nl.write_bytes(raw if raw.endswith(b"\n") else raw + b"\n")
        without_nl.write_bytes(raw.rstrip(b"\n"))
        assert derive_state(with_nl) == derive_state(without_nl)

    def test_projection_names_both_kinds_and_counts(self, tmp_path):
        rendered = derive_state(self._populated(tmp_path))
        assert "NOT the source of truth" in rendered
        assert "Artifact rows (planned → composed → artifact-reviewed)" in rendered
        assert (
            "Deliverable rows (planned → fitted → rendered → deliverable-reviewed → ready)"
            in rendered
        )
        assert "composed 1" in rendered  # the artifact roll-up
        assert "blocked 1" in rendered  # the deliverable annotation is surfaced

    def test_empty_ssot_derives_a_stable_placeholder(self, tmp_path):
        missing = tmp_path / "nope.csv"
        rendered = derive_state(missing)
        assert "_(none)_" in rendered
        assert rendered == derive_state(missing)


# ---------------------------------------------------------------------------
# Spine integration (§22.7): S5 advances the right row; a hook failure is contained.
# ---------------------------------------------------------------------------


def _payload_bytes() -> bytes:
    return (canonical_json_str({"v": 1}) + "\n").encode()


class TestSpineIntegration:
    def _store_and_claims(self, tmp_path, name: str):
        store = WorkspaceStore(tmp_path / name)
        claims = ClaimRegistry(
            store.claims_dir, holder="worker-a", ttl_seconds=60.0, clock=ManualClock()
        )
        return store, claims

    def test_s5_hook_advances_the_correct_row(self, tmp_path):
        store, claims = self._store_and_claims(tmp_path, "ws")
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        ssot.register(DEL, "deliverable")  # a sibling row that must stay put
        result = drive(
            WorkUnit(id=ART, payload=_payload_bytes),
            store=store,
            claims=claims,
            advance=ssot.advance_hook("composed"),
        )
        assert result.code == "ok"
        assert result.advanced is True
        assert result.advance_error is None
        assert _status_of(ssot.csv_path, ART) == "composed"
        assert _status_of(ssot.csv_path, DEL) == "planned"  # sibling untouched (PC4)

    def test_redrive_completes_the_lagging_bookkeeping_idempotently(self, tmp_path):
        # §22.7 crash table: an already-materialized re-drive still runs S5 and advances the
        # (already-advanced) row idempotently — never a regression.
        store, claims = self._store_and_claims(tmp_path, "ws")
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact")
        hook = ssot.advance_hook("composed")
        drive(WorkUnit(id=ART, payload=_payload_bytes), store=store, claims=claims, advance=hook)
        second = drive(
            WorkUnit(id=ART, payload=_payload_bytes), store=store, claims=claims, advance=hook
        )
        assert second.code == "already-materialized"
        assert second.advanced is True  # the hook ran; advance was idempotent
        assert _status_of(ssot.csv_path, ART) == "composed"

    def test_a_hook_failure_never_breaks_the_drive(self, tmp_path):
        # Containment (§22.7 S5 side-effect-only): point the SSOT at an unwritable location
        # (its lock dir is a FILE) so every advance raises — the drive still materializes and
        # releases; the failure is contained in advance_error.
        store, claims = self._store_and_claims(tmp_path, "ws")
        blocker = tmp_path / "blocker"
        blocker.write_bytes(b"x")  # a FILE where the ssot wants a directory
        broken = Ssot(csv_path=blocker / "ssot.csv")
        result = drive(
            WorkUnit(id=ART, payload=_payload_bytes),
            store=store,
            claims=claims,
            advance=broken.advance_hook("composed"),
        )
        assert result.code == "ok"
        assert result.materialized is True
        assert result.advanced is False
        assert result.advance_error is not None
        assert store.output_path(ART).exists()  # the drive completed despite the SSOT failure


# ---------------------------------------------------------------------------
# The CLI: `pipeline ssot derive-state` (plan step 22).
# ---------------------------------------------------------------------------


class TestCli:
    def _csv(self, tmp_path) -> Path:
        ssot = Ssot(csv_path=tmp_path / "ssot.csv")
        ssot.register(ART, "artifact", coordinates="t/p")
        ssot.advance(ART, "composed")
        return ssot.csv_path

    def test_derive_state_to_out_matches_the_library(self, tmp_path):
        from pipeline.__main__ import main

        csv_path = self._csv(tmp_path)
        out = tmp_path / "mirror.md"
        rc = main(["ssot", "derive-state", "--csv", str(csv_path), "--out", str(out)])
        assert rc == 0
        assert out.read_bytes().decode("utf-8") == derive_state(csv_path)

    def test_derive_state_to_stdout(self, tmp_path, capsys):
        from pipeline.__main__ import main

        csv_path = self._csv(tmp_path)
        rc = main(["ssot", "derive-state", "--csv", str(csv_path)])
        assert rc == 0
        assert capsys.readouterr().out == derive_state(csv_path)

    def test_ssot_without_subcommand_is_a_usage_error(self, tmp_path):
        from pipeline.__main__ import main

        assert main(["ssot"]) == 2

    def test_unknown_ssot_subcommand_is_refused(self, tmp_path):
        from pipeline.__main__ import main

        with pytest.raises(SystemExit) as exc:
            main(["ssot", "read-status"])
        assert exc.value.code == 2
