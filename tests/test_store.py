"""Step-20 tests: the §23 workspace store layout + the G1 atomic-write primitives.

Plan step-20 acceptance under test here: two racing committers → exactly one winner, the
loser gets `already-materialized` and the winner's bytes are intact (B4-4); the replacing
rename never tears a concurrent reader; store paths derive from ids with filename = id
EXACTLY (no extension on claims/markers, §7.4/§13.3); the 8-process race mirrors the gate-1
probe (one winner, seven clean losers); a crash-dropped temp is identifiable and never a
partial final; `is_done` takes only output-store handles (§22.7 — no SSOT parameter
exists, asserted by API shape and by import lint).

Id strings are the verbatim §7.4 examples. All stores live under pytest tmp_path — nothing
is ever created under the repo's `workspaces/` (rule 4 / standing constraint).
"""

import ast
import inspect
import json
import multiprocessing
import os
from pathlib import Path

import pytest

import pipeline.store as store_module
from pipeline.canonical import sha256_hex
from pipeline.ids import IdError, parse_id
from pipeline.store import (
    STORE_SUBDIRS,
    TEMP_PREFIX,
    AlreadyMaterializedError,
    StorePathError,
    StoreWriteError,
    WorkspaceStore,
    append_jsonl_line,
    commit_new,
    create_exclusive,
    is_done,
    is_temp_name,
    stage_temp,
    write_new,
    write_replace,
)

# The §7.4 literal examples, verbatim.
ART = "a-9f3c07d21b44e8aa"
FIT = "a-9f3c07d21b44e8aa.linkedin.en"
DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain"
FIT_REV_DEL = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain"
SER_REV_DEL = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain_9c2e11ab34cd"
BOTH_REV_DEL = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd"
BOTH_REV_DEL_PART = "a-9f3c07d21b44e8aa.linkedin.en_4b7a90ce12d3.docx.plain_9c2e11ab34cd~p03"
DEL_PART = "a-9f3c07d21b44e8aa.linkedin.en.docx.plain~p03"
ART_PART = "a-9f3c07d21b44e8aa~slides"
FOLIO = "f-0123456789ab"
RUN = "r-9f3c07d21b44e8aa"

# A DR-1 job record's key (§22.7-class lossy bookkeeping): a run-family id — NOT an artifact id
# — whose root is the digest of the sorted target-id set + idempotency_key (the keying helper is
# DR-1 Commit 3's JobStore; Commit 2 lands only the subdir + this convention). It can never
# route through `output_path`/`is_done` — the boundary pin in TestJobsBoundary below.
JOB_KEY = RUN  # a run-family job key: parses, family != artifact ⇒ StorePathError at output_path
# A bare-digest filename (a plain content hash, no §7.4 family prefix): not a valid id at all, so
# `parse_id` refuses it with IdError before any family check — proof the boundary holds for
# EITHER plausible Commit-3 encoding, run-id or bare digest.
JOB_BARE_DIGEST = "9f3c07d21b44e8aa9f3c07d21b44e8aa"

_SPAWN = multiprocessing.get_context("spawn")


@pytest.fixture()
def ws(tmp_path):
    return WorkspaceStore(tmp_path / "ws")


# ---------------------------------------------------------------------------
# The §23 layout builder.
# ---------------------------------------------------------------------------


class TestLayout:
    def test_ensure_layout_creates_every_store_plus_manifests(self, ws):
        created = ws.ensure_layout()
        for name in STORE_SUBDIRS:
            assert (ws.root / name).is_dir(), name
        assert (ws.root / "output" / "manifests").is_dir()
        assert set(created) == {ws.root / name for name in STORE_SUBDIRS} | {
            ws.root / "output" / "manifests"
        }

    def test_subdir_set_is_exactly_the_section_23_tree(self):
        # `jobs` (DR-1) and `assets` (increment A) are APPENDED subdirs (additive; see
        # test_store_subdirs_is_additive_over_the_original_seven) — identity-inert.
        assert STORE_SUBDIRS == (
            "artifacts",
            "deliverables",
            "claims",
            "folios",
            "reviews",
            "select",
            "output",
            "jobs",
            "assets",
        )

    def test_store_subdirs_is_additive_over_the_original_seven(self):
        # DR-1 Commit 2 + increment A: adding `jobs` then `assets` must be PURELY ADDITIVE — every
        # original §23 subdir keeps its exact position (byte-identical prefix) and the appended tail
        # is `("jobs", "assets")`. This is the tuple half of the identity-inertness claim; the
        # routing half is TestJobsBoundary (jobs) and TestContentAssets (assets).
        original_seven = (
            "artifacts",
            "deliverables",
            "claims",
            "folios",
            "reviews",
            "select",
            "output",
        )
        assert STORE_SUBDIRS[: len(original_seven)] == original_seven  # prefix unchanged
        assert STORE_SUBDIRS[len(original_seven) :] == ("jobs", "assets")  # appended, nothing else

    def test_jobs_dir_created_on_demand(self, tmp_path):
        # DR-1 Commit 2: `jobs_dir` is created on first access, like every other store, and
        # touches nothing else (construction is inert; only what was asked for appears).
        ws = WorkspaceStore(tmp_path / "lazy-jobs")
        assert not (tmp_path / "lazy-jobs").exists()  # construction touches nothing
        jobs = ws.jobs_dir
        assert jobs == ws.root / "jobs"
        assert jobs.is_dir()
        assert not (tmp_path / "lazy-jobs" / "artifacts").exists()  # only jobs/ was asked for

    def test_jobs_dir_materialized_by_ensure_layout(self, ws):
        # DR-1 Commit 2: `ensure_layout()` materializes `jobs/` (it iterates STORE_SUBDIRS) and
        # returns it among the created directories.
        created = ws.ensure_layout()
        assert (ws.root / "jobs").is_dir()
        assert ws.jobs_dir in set(created)

    def test_ensure_layout_is_idempotent(self, ws):
        assert ws.ensure_layout() == ws.ensure_layout()

    def test_dirs_created_on_demand_not_at_construction(self, tmp_path):
        ws = WorkspaceStore(tmp_path / "lazy")
        assert not (tmp_path / "lazy").exists()  # construction touches nothing
        claims = ws.claims_dir
        assert claims.is_dir()
        assert not (tmp_path / "lazy" / "artifacts").exists()  # only what was asked for
        assert ws.artifacts_dir.is_dir()

    def test_string_root_is_coerced_to_path(self, tmp_path):
        ws = WorkspaceStore(str(tmp_path / "coerced"))
        assert isinstance(ws.root, Path)
        assert ws.select_dir.is_dir()

    def test_reviews_and_select_homes_exist(self, ws):
        # PA-15 / PA-9d: `select/` and the id-addressed `reviews/` are layout members.
        assert ws.select_dir == ws.root / "select"
        assert ws.reviews_dir == ws.root / "reviews"


# ---------------------------------------------------------------------------
# Path derivation: paths derive from ids; filename = id EXACTLY (§7.4, §18).
# ---------------------------------------------------------------------------


class TestPaths:
    @pytest.mark.parametrize(
        ("id_str", "subdir"),
        [
            (ART, "artifacts"),
            (FIT, "artifacts"),
            (ART_PART, "artifacts"),
            (DEL, "deliverables"),
            (FIT_REV_DEL, "deliverables"),
            (SER_REV_DEL, "deliverables"),
            (DEL_PART, "deliverables"),
        ],
    )
    def test_output_path_routes_by_level_filename_is_the_id(self, ws, id_str, subdir):
        path = ws.output_path(id_str)
        assert path == ws.root / subdir / id_str
        assert path.name == id_str  # exactly — no extension, no mangling (§7.4)

    @pytest.mark.parametrize("bad", [FOLIO, RUN])
    def test_output_path_refuses_non_artifact_families(self, ws, bad):
        with pytest.raises(StorePathError, match="invalid-store-path"):
            ws.output_path(bad)

    @pytest.mark.parametrize(
        "id_str",
        [ART, FIT, DEL, FIT_REV_DEL, DEL_PART, BOTH_REV_DEL, BOTH_REV_DEL_PART],
    )
    def test_claim_path_filename_is_the_id_no_extension(self, ws, id_str):
        # Includes the §7.4 BOTH-qualifiers example and its ~p03 part form: "claim
        # files and markers use the qualified id exactly" stays pinned by a test.
        path = ws.claim_path(id_str)
        assert path == ws.root / "claims" / id_str
        assert path.name == id_str  # exactly the id — nothing appended (§13.3, §7.4)

    def test_folio_member_path_is_the_members_artifact_id(self, ws):
        path = ws.folio_member_path(FOLIO, ART)
        assert path == ws.root / "folios" / FOLIO / "members" / ART
        assert path.name == ART  # §13.3: marker filename = the member's artifact-id
        assert path.parent.is_dir()  # created on demand

    @pytest.mark.parametrize("bad_member", [FIT, DEL, ART_PART, FOLIO])
    def test_folio_member_requires_bare_artifact_id(self, ws, bad_member):
        with pytest.raises(StorePathError, match="invalid-store-path"):
            ws.folio_member_path(FOLIO, bad_member)

    @pytest.mark.parametrize("bad_folio", [ART, RUN, "folio-1"])
    def test_folio_member_requires_folio_id(self, ws, bad_folio):
        with pytest.raises((StorePathError, IdError)):
            ws.folio_member_path(bad_folio, ART)

    @pytest.mark.parametrize("id_str", [ART, DEL, FIT_REV_DEL, SER_REV_DEL])
    def test_review_path_takes_artifact_and_deliverable_ids(self, ws, id_str):
        path = ws.review_path(id_str)
        assert path == ws.root / "reviews" / id_str

    @pytest.mark.parametrize("bad", [FIT, ART_PART, DEL_PART, FOLIO, RUN])
    def test_review_path_refuses_other_levels(self, ws, bad):
        # §19: reviews attach to artifact-ids (gate 1) and deliverable-ids (gate 2) only.
        with pytest.raises(StorePathError, match="invalid-store-path"):
            ws.review_path(bad)

    def test_bytes_path_appends_conventional_extension(self, ws):
        assert ws.bytes_path(DEL, "docx") == ws.root / "deliverables" / f"{DEL}.docx"

    @pytest.mark.parametrize("bad", [ART, FIT, FOLIO])
    def test_bytes_path_requires_deliverable_level(self, ws, bad):
        with pytest.raises(StorePathError, match="invalid-store-path"):
            ws.bytes_path(bad, "docx")

    @pytest.mark.parametrize("bad", ["A-9F3C07D21B44E8AA", "../escape", "a-123", ""])
    def test_invalid_ids_are_refused_everywhere(self, ws, bad):
        for method in (ws.output_path, ws.claim_path, ws.review_path):
            with pytest.raises(IdError):
                method(bad)

    def test_manifests_dir_lives_under_output(self, ws):
        assert ws.manifests_dir == ws.root / "output" / "manifests"


# ---------------------------------------------------------------------------
# DR-1 jobs boundary (§22.7 pin): a job key can NEVER route through output_path.
# ---------------------------------------------------------------------------


class TestJobsBoundary:
    """The load-bearing DR-1 Commit 2 pin: a job record is keyed by a NON-artifact id and can
    never masquerade as an output. `output_path`/`is_done` route by id FAMILY and refuse every
    non-artifact family, so no job key can reach the artifact/deliverable path (§22.7)."""

    def test_output_path_refuses_a_run_family_job_key(self, ws):
        # THE boundary pin: a run-family job key (family != artifact) is refused with the typed
        # StorePathError — a job record can never be an output route.
        with pytest.raises(StorePathError, match="invalid-store-path"):
            ws.output_path(JOB_KEY)

    def test_is_done_refuses_a_run_family_job_key(self, ws):
        # is_done delegates to output_path, so the same refusal holds: a job key can never be
        # tested for output existence (the §22.7 authority reads artifact ids only).
        with pytest.raises(StorePathError, match="invalid-store-path"):
            is_done(ws, JOB_KEY)

    def test_a_bare_digest_job_filename_also_never_routes(self, ws):
        # Belt-and-suspenders: even if Commit 3 keyed jobs by a bare content digest (no family
        # prefix), output_path still refuses it — parse_id raises IdError before any family
        # check. The invariant "a job filename never routes through output_path" holds for
        # EITHER plausible encoding (run-id or bare digest).
        with pytest.raises(IdError):
            ws.output_path(JOB_BARE_DIGEST)

    def test_a_job_key_is_a_run_not_an_artifact_id(self):
        # The identity half of the pin: the documented job key parses as a run id, NOT an
        # artifact id, so it can never collide with an artifact/fitted/deliverable output name.
        assert parse_id(JOB_KEY).family == "run"


# ---------------------------------------------------------------------------
# Content-addressed content assets (increment A): a DISTINCT keying scheme +
# the idempotent `commit_asset` write helper.
# ---------------------------------------------------------------------------


class TestContentAssets:
    """Increment A: the content-addressed content-asset store. Assets are keyed by the SHA-256 of
    their own BYTES (extension-bearing), a DISTINCT scheme from the id-addressed records — never a
    `parse_id`-valid id, never routed through `output_path`/`is_done`. `commit_asset` writes
    idempotently (identical bytes → identical path → the swallowed `already-materialized` no-op)."""

    def test_asset_path_is_sha256_named_extension_bearing_under_assets(self, ws):
        content = b"a throughput chart, as PNG bytes\n"
        path = ws.asset_path(content, extension="png")
        assert path == ws.root / "assets" / f"{sha256_hex(content)}.png"
        assert path.parent == ws.root / "assets"
        assert path.parent.is_dir()  # assets/ created on demand (as output_path mkdirs artifacts/)
        assert path.suffix == ".png"
        assert path.stem == sha256_hex(content)  # the filename IS the content hash

    def test_asset_path_nests_under_a_subdir(self, ws):
        # The generated-SVG home: assets/diagrams/<sha256hex>.svg (increment C rides this path).
        content = b"<svg>...generated diagram...</svg>"
        path = ws.asset_path(content, subdir="diagrams", extension="svg")
        assert path == ws.root / "assets" / "diagrams" / f"{sha256_hex(content)}.svg"
        assert (ws.root / "assets" / "diagrams").is_dir()  # the nested dir is created on demand

    def test_assets_dir_is_the_home_root_created_on_demand(self, tmp_path):
        ws = WorkspaceStore(tmp_path / "lazy-assets")
        assert not (tmp_path / "lazy-assets").exists()  # construction touches nothing
        assets = ws.assets_dir
        assert assets == ws.root / "assets"
        assert assets.is_dir()
        assert not (tmp_path / "lazy-assets" / "artifacts").exists()  # only assets/ was asked for

    def test_assets_dir_materialized_by_ensure_layout(self, ws):
        # `ensure_layout()` iterates STORE_SUBDIRS, so `assets/` is materialized and returned.
        created = ws.ensure_layout()
        assert (ws.root / "assets").is_dir()
        assert ws.assets_dir in set(created)

    def test_commit_asset_writes_bytes_and_returns_the_content_addressed_path(self, ws):
        content = b"PNG-bytes-v1\n"
        path = ws.commit_asset(content, extension="png")
        assert path == ws.asset_path(content, extension="png")
        assert path.read_bytes() == content
        assert not [n for n in os.listdir(path.parent) if is_temp_name(n)]  # no temp left behind

    def test_commit_asset_is_idempotent_identical_bytes_same_path_no_raise(self, ws):
        # S4: content-addressing ⇒ identical bytes resolve to the identical path; the second write
        # is the DESIGNED already-materialized no-op, SWALLOWED (never raises), winner bytes intact.
        content = b"identical-asset-bytes\n"
        first = ws.commit_asset(content, extension="png")
        second = ws.commit_asset(content, extension="png")  # must NOT raise
        assert first == second
        assert first.read_bytes() == content
        assert not [n for n in os.listdir(first.parent) if is_temp_name(n)]

    def test_commit_asset_is_idempotent_in_a_subdir(self, ws):
        content = b"<svg>diagram</svg>"
        first = ws.commit_asset(content, subdir="diagrams", extension="svg")
        second = ws.commit_asset(content, subdir="diagrams", extension="svg")  # must NOT raise
        assert first == second == ws.root / "assets" / "diagrams" / f"{sha256_hex(content)}.svg"
        assert first.read_bytes() == content

    def test_different_bytes_yield_different_paths_no_same_path_collision(self, ws):
        # Different content ⇒ different hash ⇒ different path, so a same-path DIFFERENT-content
        # collision cannot arise by construction (the write is only ever an identical-bytes no-op).
        a = ws.commit_asset(b"asset-A\n", extension="png")
        b = ws.commit_asset(b"asset-B\n", extension="png")
        assert a != b
        assert a.read_bytes() == b"asset-A\n"
        assert b.read_bytes() == b"asset-B\n"

    def test_asset_filename_is_content_addressed_not_a_parse_id_valid_id(self, ws):
        # The content-asset boundary: an asset filename is a bare SHA-256 hex + extension — a
        # DISTINCT keying scheme, deliberately NOT a §7.4 id. `asset_path`/`commit_asset` never call
        # `parse_id`, and the produced name is not even a valid id (parse_id refuses it), so assets
        # can never route through the id-addressed `output_path`/`is_done` surface.
        content = b"content-addressed, id-free\n"
        path = ws.commit_asset(content, extension="png")
        assert path.name == f"{sha256_hex(content)}.png"
        with pytest.raises(IdError):
            parse_id(path.name)  # a content-hash-plus-extension filename is not a valid pipeline id
        with pytest.raises(IdError):
            parse_id(path.stem)  # nor is the bare 64-hex digest (no §7.4 family prefix)


# ---------------------------------------------------------------------------
# The no-replace commit (§22.3, B4-4; G1 P2).
# ---------------------------------------------------------------------------


class TestNoReplaceCommit:
    def test_write_new_commits_bytes_and_leaves_no_temp(self, ws):
        target = ws.output_path(ART)
        write_new(target, b"winner-payload-A\n")
        assert target.read_bytes() == b"winner-payload-A\n"
        assert not [n for n in os.listdir(target.parent) if is_temp_name(n)]

    def test_commit_against_existing_target_fails_typed_winner_intact(self, ws):
        target = ws.output_path(ART)
        write_new(target, b"winner-payload-A\n")
        with pytest.raises(AlreadyMaterializedError) as exc_info:
            write_new(target, b"late-payload-B\n")
        # B4-4: the loss is typed, the winner's bytes are untouched, the temp is discarded.
        assert exc_info.value.code == "already-materialized"
        assert exc_info.value.target == target
        assert target.read_bytes() == b"winner-payload-A\n"
        assert not [n for n in os.listdir(target.parent) if is_temp_name(n)]

    def test_two_step_stage_then_commit(self, ws):
        target = ws.output_path(FIT)
        temp = stage_temp(target, b"fitted-record\n")
        assert temp.parent == target.parent  # same dir ⇒ same volume for os.link
        assert is_temp_name(temp.name)
        assert not target.exists()  # nothing at the target until commit — never partial
        commit_new(temp, target)
        assert target.read_bytes() == b"fitted-record\n"
        assert not temp.exists()

    def test_loser_temp_is_discarded_on_typed_loss(self, ws):
        target = ws.output_path(DEL)
        write_new(target, b"first\n")
        loser_temp = stage_temp(target, b"second\n")
        with pytest.raises(AlreadyMaterializedError):
            commit_new(loser_temp, target)
        assert not loser_temp.exists()  # §22.3: the loser discards its temp
        assert target.read_bytes() == b"first\n"

    def test_crash_drop_leaves_gc_able_temp_never_a_partial_final(self, ws):
        target = ws.output_path(ART)
        dropped = stage_temp(target, b"crashed-before-commit\n")
        # Simulated crash between stage and commit: the worker is gone.
        assert not target.exists()  # the final is wholly absent — never partial (§22.3)
        assert dropped.exists()
        assert dropped.name.startswith(TEMP_PREFIX)
        assert is_temp_name(dropped.name)  # identifiable → GC-able by a future ops sweep
        # The drop is inert: a later writer commits cleanly regardless.
        write_new(target, b"re-driven\n")
        assert target.read_bytes() == b"re-driven\n"
        assert dropped.exists()  # and is NEVER auto-deleted by the store module (A4)

    def test_staged_temp_bytes_are_complete_before_commit(self, ws):
        target = ws.output_path(ART)
        temp = stage_temp(target, b"complete-by-construction\n")
        assert temp.read_bytes() == b"complete-by-construction\n"
        commit_new(temp, target)

    def test_create_exclusive_is_create_if_absent(self, ws):
        claim = ws.claim_path(FIT)
        create_exclusive(claim, b'{"holder": "w-first", "lease_expiry": 9999999999}\n')
        with pytest.raises(FileExistsError):
            create_exclusive(claim, b'{"holder": "w-second", "lease_expiry": 9999999999}\n')
        assert json.loads(claim.read_bytes())["holder"] == "w-first"


# ---------------------------------------------------------------------------
# The replacing rename (markers, §21.2; G1 P3) — incl. the concurrent reader.
# ---------------------------------------------------------------------------


def _marker_reader(marker_str: str, ready_event, stop_event, stats_path_str: str) -> None:
    """Concurrent reader: every read must parse complete — old or new, never torn."""
    marker, stats_path = Path(marker_str), Path(stats_path_str)
    reads = anomalies = 0
    notes = []
    ready_event.set()  # handshake: the writer holds its replaces until we are looping
    while not stop_event.is_set():
        try:
            data = marker.read_bytes()
            obj = json.loads(data)
            if not (data.endswith(b"\n") and "v" in obj and obj["pad"] == "p" * 32):
                anomalies += 1
                notes.append(f"incomplete read: {data[:60]!r}")
        except FileNotFoundError:
            anomalies += 1
            notes.append("marker missing during replacing rename")
        except ValueError as exc:
            anomalies += 1
            notes.append(f"torn read: {exc}")
        reads += 1
    stats_path.write_text(json.dumps({"reads": reads, "anomalies": anomalies, "notes": notes[:5]}))


class TestReplacingRename:
    def test_write_replace_updates_in_place(self, ws):
        marker = ws.folio_member_path(FOLIO, ART)
        write_replace(marker, b'{"added_ts": "t1"}\n')
        write_replace(marker, b'{"added_ts": "t1", "role": "chapter"}\n')  # member-updated
        assert marker.read_bytes() == b'{"added_ts": "t1", "role": "chapter"}\n'
        assert not [n for n in os.listdir(marker.parent) if is_temp_name(n)]

    def test_replacing_rename_never_tears_a_concurrent_reader(self, ws):
        # Plan step-20 acceptance, mirroring the G1 P3 probe: reader sees old or new,
        # both complete — zero anomalies across every read during 300 replaces.
        marker = ws.folio_member_path(FOLIO, ART)
        stats_path = ws.root / "p3-reader-stats.json"
        write_replace(marker, (json.dumps({"v": 0, "pad": "p" * 32}) + "\n").encode())

        ready, stop = _SPAWN.Event(), _SPAWN.Event()
        reader = _SPAWN.Process(
            target=_marker_reader, args=(str(marker), ready, stop, str(stats_path))
        )
        reader.start()
        try:
            assert ready.wait(timeout=60)  # reader provably overlaps the replaces
            for v in range(1, 301):
                write_replace(marker, (json.dumps({"v": v, "pad": "p" * 32}) + "\n").encode())
        finally:
            stop.set()
            reader.join(timeout=60)
        assert reader.exitcode == 0
        stats = json.loads(stats_path.read_text())
        assert stats["reads"] > 0
        assert stats["anomalies"] == 0, stats["notes"]
        assert json.loads(marker.read_bytes())["v"] == 300


# ---------------------------------------------------------------------------
# The JSONL single-line append (§13.3; G1 P5).
# ---------------------------------------------------------------------------


def _jsonl_appender(path_str: str, wid: int, count: int, barrier) -> None:
    from pipeline.store import append_jsonl_line

    barrier.wait(timeout=60)
    for i in range(count):
        append_jsonl_line(Path(path_str), {"w": wid, "i": i, "pad": "x" * 64})


class TestJsonlAppend:
    def test_appends_one_canonical_line_per_record(self, ws):
        log = ws.output_dir / "telemetry.jsonl"
        append_jsonl_line(log, {"b": 2, "a": 1})
        append_jsonl_line(log, {"event": "second"})
        lines = log.read_bytes().splitlines(keepends=True)
        assert lines == [b'{"a":1,"b":2}\n', b'{"event":"second"}\n']  # canonical, sorted keys

    def test_creates_file_and_parents_on_demand(self, tmp_path):
        log = tmp_path / "deep" / "nested" / "log.jsonl"
        append_jsonl_line(log, {"first": True})
        assert json.loads(log.read_text()) == {"first": True}

    def test_concurrent_multiprocess_append_never_tears(self, ws):
        # Mirror of G1 P5 (scaled): N procs × M single-write appends → zero torn lines,
        # every writer's full sequence present.
        n_procs, count = 4, 100
        log = ws.output_dir / "telemetry.jsonl"
        barrier = _SPAWN.Barrier(n_procs)
        procs = [
            _SPAWN.Process(target=_jsonl_appender, args=(str(log), wid, count, barrier))
            for wid in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)
        assert all(p.exitcode == 0 for p in procs)
        lines = log.read_bytes().splitlines()
        assert len(lines) == n_procs * count
        seen: dict[int, set[int]] = {w: set() for w in range(n_procs)}
        for line in lines:
            obj = json.loads(line)  # any torn/interleaved line fails here, loudly
            assert obj["pad"] == "x" * 64
            seen[obj["w"]].add(obj["i"])
        assert all(seen[w] == set(range(count)) for w in range(n_procs))


# ---------------------------------------------------------------------------
# The 8-process commit race on ONE id (plan acceptance; G1 P6 as a test).
# ---------------------------------------------------------------------------


def _commit_racer(target_str: str, wid: int, barrier, queue) -> None:
    from pipeline.store import AlreadyMaterializedError, write_new

    try:
        barrier.wait(timeout=60)
        try:
            write_new(Path(target_str), f"payload-from-w{wid}\n".encode())
            queue.put((wid, "win"))
        except AlreadyMaterializedError:
            queue.put((wid, "lose-already-materialized"))
    except Exception as exc:  # noqa: BLE001 — any other outcome is a dirty failure
        queue.put((wid, f"ERROR:{type(exc).__name__}:{exc}"))


class TestCommitRace:
    def test_eight_process_race_one_winner_seven_clean_losers(self, ws):
        n_procs = 8
        target = ws.output_path(ART)
        target.parent.mkdir(parents=True, exist_ok=True)
        barrier = _SPAWN.Barrier(n_procs)
        queue = _SPAWN.Queue()
        procs = [
            _SPAWN.Process(target=_commit_racer, args=(str(target), wid, barrier, queue))
            for wid in range(n_procs)
        ]
        for p in procs:
            p.start()
        results = [queue.get(timeout=120) for _ in range(n_procs)]
        for p in procs:
            p.join(timeout=60)
        winners = [wid for wid, r in results if r == "win"]
        losers = [wid for wid, r in results if r == "lose-already-materialized"]
        errors = [(wid, r) for wid, r in results if r.startswith("ERROR")]
        assert errors == []
        assert len(winners) == 1  # §22.3: exactly one winner per id
        assert len(losers) == n_procs - 1  # every loser got the typed already-materialized
        # The winner's bytes are intact and no loser temp survives (B4-4 / §22.3).
        assert target.read_bytes() == f"payload-from-w{winners[0]}\n".encode()
        assert not [n for n in os.listdir(target.parent) if is_temp_name(n)]


# ---------------------------------------------------------------------------
# is_done: output existence ONLY — §22.7 scoping starts here.
# ---------------------------------------------------------------------------


class TestIsDone:
    def test_false_then_true_on_output_existence(self, ws):
        assert is_done(ws, ART) is False
        write_new(ws.output_path(ART), b"ir-canonical\n")
        assert is_done(ws, ART) is True
        assert is_done(ws, FIT) is False  # a different id is a different output

    def test_signature_takes_only_output_store_handles(self):
        # §22.7 CI teeth (signature scoping): no SSOT handle EXISTS in the signature.
        params = list(inspect.signature(is_done).parameters)
        assert params == ["store", "id_str"]
        assert not any("ssot" in p.lower() for p in params)

    def test_store_module_imports_no_ssot_code(self):
        # §22.7 import discipline (the full CI lint lands at step 21; it must already hold).
        tree = ast.parse(Path(store_module.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or "", *(alias.name for alias in node.names)]
            else:
                continue
            assert not any("ssot" in name.lower() for name in names), names

    def test_store_exposes_no_deletion_primitive(self):
        # A4 build note: retain-all — no delete/cleanup surface for store content.
        forbidden = ("delete", "remove", "unlink", "cleanup", "purge", "prune", "gc")
        public = [n for n in store_module.__all__]
        assert not [n for n in public if any(k in n.lower() for k in forbidden)]


# ---------------------------------------------------------------------------
# Typed-error surfaces.
# ---------------------------------------------------------------------------


class TestErrorTypes:
    def test_error_codes(self):
        assert StorePathError.code == "invalid-store-path"
        assert AlreadyMaterializedError.code == "already-materialized"
        assert StoreWriteError.code == "store-write-failed"

    def test_already_materialized_is_not_a_value_error(self, ws):
        # It is the designed ok-class loser OUTCOME (§22.6), typed for unmistakability.
        target = ws.output_path(ART)
        write_new(target, b"x")
        with pytest.raises(AlreadyMaterializedError):
            write_new(target, b"y")
        assert not issubclass(AlreadyMaterializedError, ValueError)
