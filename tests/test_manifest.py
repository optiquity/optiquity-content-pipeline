"""Step-35 tests: `pipeline.api.manifest` — `emit-manifest`, the point-in-time WORK ORDER (§21.5).

Covers, per the acceptance list (the currency resolver is an INJECTED fake — no live config read,
no `live` marker; the store is seeded directly, never via a minting render):

- **NO MINT during emit** (the load-bearing invariant): the store inventory (fit/serialize/artifact
  ids + bytes) is byte-for-byte UNCHANGED before vs after emit-manifest — for members that are
  current, stale, and render-needed alike;
- **byte-identical regenerability**: same membership + targets + store state ⇒ byte-identical
  work-order CONTENT (wall-clock lives only in the `<ts>` filename, never the tabular body);
- a **FROZEN stale pin** is referenced VERBATIM and annotated with computed currency — never
  re-resolved;
- **`needs-input: unresolved-member`** for a member with no target and no pin (never guessed);
- a **render-needed** row for a coordinate that is resolvable but not yet materialized;
- **payload by side**: `side: external` → a layer-3 payload ref; `side: internal` → path + pins;
- **no folio-level ordering/schedule columns**; the per-member SORTABLE FACTS columns ARE present;
- the manifest is PERSISTED under `output/manifests/` AND returned in-band;
- **manifest.py is SSOT-FREE** (§22.7): imports no ssot module.
"""

from __future__ import annotations

import ast
import datetime
import hashlib
from pathlib import Path

import pytest

from pipeline import reconcile, serialize
from pipeline.api import manifest
from pipeline.api.invoke import invoke
from pipeline.folios import add_to_folio, create_folio
from pipeline.store import WorkspaceStore

WS = "wsA"
ART = "a-9f3c07d21b44e8aa"
ART2 = "a-1234567890abcdef"
FIXED_TS = "2024-01-01T00:00:00+00:00"
LATER_TS = "2024-06-01T00:00:00+00:00"  # a strictly-later minted_ts for the multi-fit lineage tests
COMMIT = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"
PLATFORM, LANGUAGE, OUTPUT_TYPE, PRESENTATION = "github", "en", "md", "plain"
COORD = {
    "platform": PLATFORM,
    "language": LANGUAGE,
    "output_type": OUTPUT_TYPE,
    "presentation": PRESENTATION,
}


# ---------------------------------------------------------------------------
# Fixtures / seams (hermetic; no live call).
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path):
    s = WorkspaceStore(tmp_path / WS)
    s.ensure_layout()
    return s


class FakeResolver:
    """A controllable currency resolver (no config read): FRESH unless a fitted-/deliverable-id is
    marked stale, in which case a never-matching digest → fit_current/serialize_current False."""

    def __init__(self, stale_fits=frozenset(), stale_serials=frozenset()):
        self.stale_fits = set(stale_fits)
        self.stale_serials = set(stale_serials)
        self.calls = 0

    def current_fit_digest(self, *, root, workspace, fitted_id, stored_preimage):
        self.calls += 1
        if fitted_id in self.stale_fits:
            return "ffffffffffff"
        return reconcile.fit_digest(stored_preimage)

    def current_serialize_digest(self, *, root, workspace, deliverable_id, stored_preimage):
        self.calls += 1
        if deliverable_id in self.stale_serials:
            return "ffffffffffff"
        return serialize.serialize_digest(stored_preimage)


class CountingNow:
    """A deterministic emission clock: each call advances one second, so successive emits get
    DISTINCT filenames while the tabular CONTENT stays byte-identical (the §21.5 property)."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> datetime.datetime:
        self.n += 1
        return datetime.datetime(2024, 1, 1, 0, 0, self.n, tzinfo=datetime.UTC)


def _fit_pre(max_chars: int) -> dict:
    return {
        "strategy": {},
        "hard-limits": {"max_chars": max_chars},
        "advisory": {},
        "render-dims": {},
    }


def _ser_pre(pandoc: str) -> dict:
    return {"tool_bundle": {"pandoc_version": pandoc}, "render_target": {}, "render_inputs": {}}


def _write_json(path: Path, obj) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj) + "\n").encode())


def seed_artifact(store: WorkspaceStore, artifact_id: str = ART, commit: str = COMMIT) -> None:
    """The bare artifact IR envelope so the member id `is_done` (add-to-folio) + carries lineage."""
    _write_json(
        store.output_path(artifact_id),
        {
            "ir_version": 1,
            "parts": [{"part-id": f"{artifact_id}~intro"}],
            "binding": {
                "artifact_id": artifact_id,
                "digest": "d" * 64,
                "preimage": {"source-commit": {"acme": commit}, "source-subset": ["acme"]},
            },
            "grounding": {"f1": {"tier": "EXTRACTED"}},
            "metadata": {"k": "v"},
            "generating_run": "run-xyz",
            "provenance": "instance",
        },
    )


def seed_fit(
    store: WorkspaceStore,
    *,
    artifact_id: str = ART,
    fit_preimage: dict | None = None,
    fit_revision: bool = False,
    minted_ts: str = FIXED_TS,
) -> str:
    """Seed ONLY a fitted record (no deliverable) — the render-needed precondition."""

    fb = reconcile.build_fit_binding(
        artifact_id=artifact_id,
        platform=PLATFORM,
        language=LANGUAGE,
        preimage=fit_preimage or _fit_pre(500),
        strategy="pass",
        localize_languages=[],
        gate_outcome="ok",
        revision=fit_revision,
        minted_ts=minted_ts,
    )
    _write_json(store.output_path(fb["fitted_id"]), {"ir": {"body": "x"}, "binding": fb})
    return fb["fitted_id"]


def seed_deliverable(
    store: WorkspaceStore,
    *,
    artifact_id: str = ART,
    output_type: str = OUTPUT_TYPE,
    presentation: str = PRESENTATION,
    fit_preimage: dict | None = None,
    serialize_preimage: dict | None = None,
    fit_revision: bool = False,
    serialize_revision: bool = False,
    side: str = "internal",
    fit_minted_ts: str = FIXED_TS,
    serialize_minted_ts: str = FIXED_TS,
) -> tuple[str, str]:
    """Seed a fit + render-binding + bytes; return (deliverable_id, fitted_id). The fit and
    serialize `minted_ts` are independently settable so a multi-fit case can make the latest-minted
    FIT differ from the latest-minted DELIVERABLE (§21.8 rule 2 keys on the FIT)."""
    fb = reconcile.build_fit_binding(
        artifact_id=artifact_id,
        platform=PLATFORM,
        language=LANGUAGE,
        preimage=fit_preimage or _fit_pre(500),
        strategy="pass",
        localize_languages=[],
        gate_outcome="ok",
        revision=fit_revision,
        minted_ts=fit_minted_ts,
    )
    fitted_id = fb["fitted_id"]
    _write_json(store.output_path(fitted_id), {"ir": {"body": "x"}, "binding": fb})
    rb = serialize.build_render_binding(
        fitted_id=fitted_id,
        output_type=output_type,
        presentation=presentation,
        preimage=serialize_preimage or _ser_pre("3.1"),
        fit_binding_ref=fb,
        serialize_revision=serialize_revision,
        minted_ts=serialize_minted_ts,
    )
    deliverable_id = rb["deliverable_id"]
    _write_json(
        store.output_path(deliverable_id),
        {"binding": rb, "layer2": {"path": f"deliverables/{deliverable_id}.md"}, "side": side},
    )
    store.bytes_path(deliverable_id, "md").write_bytes(b"BODY\n")
    return deliverable_id, fitted_id


def make_folio(store: WorkspaceStore, members) -> str:
    """Create a folio and add members (each `(artifact_id, pin?, role?)` or a bare artifact-id)."""
    folio = create_folio(store, purpose="launch", nonce="n").folio_id
    specs = []
    for m in members:
        if isinstance(m, tuple):
            aid, pin, role = m
            specs.append({"artifact_id": aid, "pin": pin, "role": role})
        else:
            specs.append(m)
    if specs:
        add_to_folio(store, folio, specs)
    return folio


def _emit(store, folio_id, *, member_targets=None, resolver=None, now=None):
    handler = manifest.emit_manifest_handler(
        resolver=resolver or FakeResolver(), now=now or CountingNow()
    )
    params = {"folio_id": folio_id}
    if member_targets is not None:
        params["member_targets"] = member_targets
    return invoke("emit-manifest", WS, params, store=store, handlers={"emit-manifest": handler})


def _manifest(out) -> dict:
    return out["results"][0]["context"]["manifest"]


def _rows(out) -> list[dict]:
    return _manifest(out)["rows"]


def _inventory(store: WorkspaceStore) -> dict[str, str]:
    """Every fit/deliverable/artifact record + bytes, by content hash — the no-mint witness. The
    `output/manifests/` tree is DELIBERATELY excluded (that is the manifest's own artifact)."""
    inv: dict[str, str] = {}
    for directory in (store.artifacts_dir, store.deliverables_dir):
        if directory.is_dir():
            for p in sorted(directory.iterdir()):
                if p.is_file():
                    inv[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return inv


# ---------------------------------------------------------------------------
# NO MINT — the load-bearing invariant.
# ---------------------------------------------------------------------------


class TestNoMint:
    def test_inventory_unchanged_across_current_stale_and_render_needed(self, store):
        # A folio spanning ALL member states: current (fresh deliverable), stale-fit (a stale
        # deliverable), and render-needed (a fit with no deliverable). Emit and prove the store's
        # fit/serialize/artifact inventory is byte-for-byte unchanged — emit mints NOTHING.
        seed_artifact(store, ART)
        seed_artifact(store, ART2)
        did_current, fit_current = seed_deliverable(store, artifact_id=ART)
        did_stale, fit_stale = seed_deliverable(
            store, artifact_id=ART2, fit_preimage=_fit_pre(200)
        )
        fit_only = seed_fit(store, artifact_id=ART, fit_preimage=_fit_pre(999))  # render-needed src
        assert fit_only  # a bare fit exists, no deliverable
        folio = make_folio(store, [ART, ART2])
        targets = {
            ART: [COORD, {**COORD, "output_type": "html"}],  # md → current; html → render-needed
            ART2: [COORD],  # md on a stale fit → stale-fit
        }
        resolver = FakeResolver(stale_fits={fit_stale})

        before = _inventory(store)
        out = _emit(store, folio, member_targets=targets, resolver=resolver)
        after = _inventory(store)

        assert out["envelope"]["ok"] is True
        assert before == after  # NOTHING minted — every fit/serialize/artifact id + bytes intact
        # And all three states are actually present in the work order (a non-vacuous witness).
        states = {r["state"] for r in _rows(out)}
        assert {"current", "stale-fit", "render-needed"} <= states

    def test_frozen_pin_row_mints_nothing_and_never_re_resolves_the_pin(self, store):
        seed_artifact(store, ART)
        pin_did, pin_fit = seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [(ART, pin_did, None)])
        resolver = FakeResolver(stale_serials={pin_did})
        before = _inventory(store)
        _emit(store, folio, resolver=resolver)
        assert _inventory(store) == before  # a pinned member mints nothing either


# ---------------------------------------------------------------------------
# Byte-identical regenerability (§21.5).
# ---------------------------------------------------------------------------


class TestByteIdenticalRegeneration:
    def test_same_inputs_yield_byte_identical_work_order_content(self, store):
        from pipeline.canonical import canonical_json_str

        seed_artifact(store, ART)
        did, _ = seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        targets = {ART: [COORD]}
        clock = CountingNow()  # advances each emit → DISTINCT filenames, identical content
        one = _emit(store, folio, member_targets=targets, now=clock)
        two = _emit(store, folio, member_targets=targets, now=clock)
        # The tabular CONTENT is byte-identical; only the persisted filename (its <ts>) differs.
        assert canonical_json_str(_manifest(one)) == canonical_json_str(_manifest(two))
        assert one["results"][0]["output"]["path"] != two["results"][0]["output"]["path"]

    def test_no_wall_clock_in_the_tabular_body(self, store):
        # The manifest body carries no emission wall-clock; the <ts> lives only in the filename.
        seed_artifact(store, ART)
        seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        now = CountingNow()
        out = _emit(store, folio, member_targets={ART: [COORD]}, now=now)
        body = _manifest(out)
        assert "20240101" not in repr(body)  # the emission ts is NOT in the content
        assert "20240101" in out["results"][0]["output"]["path"]  # it IS in the filename


# ---------------------------------------------------------------------------
# The row taxonomy (§21.5): frozen-pin / current / stale-fit / render-needed / unresolved-member.
# ---------------------------------------------------------------------------


class TestFrozenPin:
    def test_stale_pin_is_annotated_not_re_resolved(self, store):
        seed_artifact(store, ART)
        pin_did, _ = seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [(ART, pin_did, None)])
        resolver = FakeResolver(stale_serials={pin_did})  # the pinned deliverable is stale
        out = _emit(store, folio, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["state"] == "frozen-pin"]
        assert row["deliverable_id"] == pin_did  # referenced VERBATIM — never re-resolved
        assert row["pin"] == pin_did
        assert row["serialize_current"] is False  # annotated stale (§21.3), the pin unchanged
        assert row["side"] == "internal"

    def test_current_pin_is_annotated_current(self, store):
        seed_artifact(store, ART)
        pin_did, _ = seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [(ART, pin_did, None)])
        out = _emit(store, folio)  # default resolver: fresh
        (row,) = [r for r in _rows(out) if r["state"] == "frozen-pin"]
        assert row["deliverable_id"] == pin_did
        assert row["fit_current"] is True and row["serialize_current"] is True


class TestResolvedRows:
    def test_current_row_references_the_materialized_deliverable(self, store):
        seed_artifact(store, ART)
        did, _ = seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        (row,) = [r for r in _rows(out) if r["state"] == "current"]
        assert row["deliverable_id"] == did
        assert row["fit_current"] is True
        assert (row["platform"], row["output_type"]) == (PLATFORM, OUTPUT_TYPE)

    def test_stale_fit_row_carries_render_input_mismatch(self, store):
        seed_artifact(store, ART)
        did, fit = seed_deliverable(store, artifact_id=ART, fit_preimage=_fit_pre(200))
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_fits={fit})
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["state"] == "stale-fit"]
        assert row["deliverable_id"] == did  # the latest-minted (stale) fit's deliverable
        assert row["warn"] == "render-input-mismatch"  # the warn rides the row (§21.8)
        assert row["fit_current"] is False

    def test_render_needed_from_stale_fit_still_carries_render_input_mismatch(self, store):
        # GAP-5(b): a STALE fit (§21.8 rule 2 — no fit-current candidate) whose only materialized
        # deliverable is ALSO serialize-stale → the serialize level finds nothing current → the row
        # is `render-needed`. The `render-input-mismatch` warn must STILL ride that row (it rode the
        # latest-minted stale fit at the fit level); dropping it under-reports fit-staleness for one
        # cycle. Contrast test_stale_fit_row_carries_render_input_mismatch (a MATERIALIZED
        # serialize-current stale-fit row) — here nothing is materializable, but the warn persists.
        seed_artifact(store, ART)
        did, fit = seed_deliverable(store, artifact_id=ART, fit_preimage=_fit_pre(200))
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_fits={fit}, stale_serials={did})  # stale fit AND stale bytes
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["member_artifact_id"] == ART]
        assert row["state"] == "render-needed"  # no serialize-current deliverable to reference
        assert row["deliverable_id"] is None  # the stale bytes are NOT handed to the publisher
        assert row["fitted_id"] == fit  # the chosen (latest-minted stale) fit names the target
        assert row["warn"] == "render-input-mismatch"  # the FIX: fit-staleness surfaced

    def test_render_needed_for_resolvable_but_unmaterialized(self, store):
        seed_artifact(store, ART)
        fit = seed_fit(store, artifact_id=ART)  # a fit exists; NO deliverable materialized
        folio = make_folio(store, [ART])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        (row,) = [r for r in _rows(out) if r["state"] == "render-needed"]
        assert row["deliverable_id"] is None  # nothing to reference — the work order says render
        assert row["fitted_id"] == fit  # resolvable from the existing fit
        assert row["platform"] == PLATFORM

    def test_fit_current_but_serialize_stale_is_render_needed_not_current(self, store):
        # HIGH (FR7.3): a fit-CURRENT but serialize-STALE materialized deliverable must NEVER be
        # labelled `current` with its stale bytes referenced — the serialize-current deliverable-id
        # is resolvable but not yet materialized, so the row is `render-needed` (the caller renders,
        # which auto-mints §17, and re-emits). Handing a publisher stale-marked-current bytes is the
        # violation this closes.
        seed_artifact(store, ART)
        did, fit = seed_deliverable(store, artifact_id=ART)  # fit fresh; serialize made stale below
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_serials={did})  # the deliverable is serialize-STALE
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["member_artifact_id"] == ART]
        assert row["state"] == "render-needed"  # NOT "current" — stale bytes are never referenced
        assert row["deliverable_id"] is None  # the stale bytes are NOT handed to the publisher
        assert row["fitted_id"] == fit  # the current-matching fit names the render target

    def test_serialize_current_revision_referenced_over_stale_baseline(self, store):
        # HIGH defect 2: under ONE current fit, a serialize-STALE baseline AND a serialize-CURRENT
        # revision are both materialized. The row must reference the serialize-CURRENT revision —
        # never the baseline (whose id sorts FIRST, which the old min(...)-by-id selection wrongly
        # preferred, unrelated to serialize currency).
        seed_artifact(store, ART)
        baseline, fit = seed_deliverable(store, artifact_id=ART, serialize_preimage=_ser_pre("3.1"))
        revision, fit2 = seed_deliverable(
            store, artifact_id=ART, serialize_preimage=_ser_pre("3.2"), serialize_revision=True
        )
        assert fit == fit2  # the SAME current fit; two serialize deliverables under it
        assert baseline != revision
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_serials={baseline})  # the baseline is serialize-STALE
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["state"] == "current"]
        assert row["deliverable_id"] == revision  # the serialize-CURRENT revision, not the baseline
        assert row["serialize_current"] is True

    def test_render_needed_fitted_id_is_the_current_matching_fit_not_latest_minted(self, store):
        # LOW fix 1 (§21.8 fit rule 1): with NO deliverable materialized but TWO fits — a
        # current-matching baseline (minted EARLY) and a LATER-minted stale revision — the
        # render-needed row names the CURRENT-matching fit, not the latest-minted one.
        seed_artifact(store, ART)
        fit_current = seed_fit(
            store, artifact_id=ART, fit_preimage=_fit_pre(500), minted_ts=FIXED_TS
        )
        fit_stale = seed_fit(
            store,
            artifact_id=ART,
            fit_preimage=_fit_pre(200),
            fit_revision=True,
            minted_ts=LATER_TS,
        )
        assert fit_current != fit_stale
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_fits={fit_stale})  # the LATER-minted fit is stale
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["state"] == "render-needed"]
        assert row["fitted_id"] == fit_current  # the current-matching fit, NOT the latest-minted
        assert row["deliverable_id"] is None

    def test_stale_fit_row_selects_the_latest_minted_fit_not_deliverable(self, store):
        # LOW fix 2 (§21.8 fit rule 2): two STALE fits, where the latest-minted FIT carries an
        # EARLIER-minted deliverable and vice versa. The stale-fit row must key on the latest-minted
        # FIT (fit-binding minted_ts) — the old key on the DELIVERABLE's minted_ts picked the wrong
        # fit's deliverable.
        seed_artifact(store, ART)
        did_a, fit_a = seed_deliverable(
            store,
            artifact_id=ART,
            fit_preimage=_fit_pre(200),
            fit_minted_ts=LATER_TS,  # the LATEST-minted FIT...
            serialize_minted_ts=FIXED_TS,  # ...but its deliverable was minted EARLIEST
        )
        did_b, fit_b = seed_deliverable(
            store,
            artifact_id=ART,
            fit_preimage=_fit_pre(300),
            fit_revision=True,
            fit_minted_ts=FIXED_TS,  # an EARLIER-minted FIT...
            serialize_minted_ts=LATER_TS,  # ...whose deliverable was minted LATEST
        )
        assert fit_a != fit_b and did_a != did_b
        folio = make_folio(store, [ART])
        resolver = FakeResolver(stale_fits={fit_a, fit_b})  # BOTH fits stale → the stale-fit branch
        out = _emit(store, folio, member_targets={ART: [COORD]}, resolver=resolver)
        (row,) = [r for r in _rows(out) if r["state"] == "stale-fit"]
        assert row["fitted_id"] == fit_a  # the latest-minted FIT (not fit_b, whose deliverable is)
        assert row["deliverable_id"] == did_a  # fit_a's deliverable, though minted earliest
        assert row["warn"] == "render-input-mismatch"


class TestUnresolvedMember:
    def test_no_target_and_no_pin_is_needs_input(self, store):
        seed_artifact(store, ART)
        folio = make_folio(store, [ART])  # a member with no pin
        out = _emit(store, folio)  # and no member_targets
        # The row records the unresolved state...
        (row,) = [r for r in _rows(out) if r["state"] == "unresolved-member"]
        assert row["member_artifact_id"] == ART
        assert row["deliverable_id"] is None
        # ...and a needs-input ResultItem rides the response (never guessed, §21.5/§3.1).
        needs = [r for r in out["results"] if r.get("code") == "unresolved-member"]
        assert len(needs) == 1
        assert needs[0]["status"] == "needs-input"
        assert needs[0]["ids"]["artifact_id"] == ART


# ---------------------------------------------------------------------------
# Payload by side (§21.5 / §17 RI14) + the column contract (A4-4).
# ---------------------------------------------------------------------------


class TestPayloadBySide:
    def test_external_layer3_ref_vs_internal_path_pins(self, store):
        seed_artifact(store, ART)
        seed_artifact(store, ART2)
        internal, _ = seed_deliverable(store, artifact_id=ART, side="internal")
        external, _ = seed_deliverable(store, artifact_id=ART2, side="external")
        folio = make_folio(store, [ART, ART2])
        targets = {ART: [COORD], ART2: [COORD]}
        out = _emit(store, folio, member_targets=targets)
        by_side = {r["side"]: r["payload"] for r in _rows(out) if r["state"] == "current"}
        # internal → path + pins.
        assert by_side["internal"]["kind"] == "path"
        assert by_side["internal"]["path"].endswith(".md")
        assert "pins" in by_side["internal"]
        # external → a layer-3 payload REFERENCE (never the materialized payload).
        assert by_side["external"]["kind"] == "layer-3"
        assert by_side["external"]["deliverable_id"] == external


class TestColumnContract:
    def test_no_ordering_or_schedule_columns_but_sortable_facts_present(self, store):
        seed_artifact(store, ART)
        seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        columns = set(_manifest(out)["columns"])
        # A folio holds ZERO ordering/schedule state (§9.1) — no such column, ever.
        forbidden = {"order", "ordering", "schedule", "sequence", "suggested_order", "position"}
        assert columns.isdisjoint(forbidden)
        # The per-member SORTABLE FACTS (A4-4 condition i) ARE exposed.
        assert {
            "added_ts", "role", "pin", "platform", "language", "output_type", "presentation",
            "generating_run", "source_commit", "created",
        } <= columns
        # Every row carries every column (a well-formed table).
        for row in _rows(out):
            assert set(row) == columns

    def test_lineage_facts_ride_each_row(self, store):
        seed_artifact(store, ART, COMMIT)
        seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        row = _rows(out)[0]
        assert row["source_commit"] == {"acme": COMMIT}
        assert row["generating_run"] == "run-xyz"
        assert row["added_ts"] is not None  # the insertion-order sortable fact


# ---------------------------------------------------------------------------
# Persistence + in-band return (§21.5).
# ---------------------------------------------------------------------------


class TestPersistenceAndReturn:
    def test_persisted_under_manifests_and_returned_in_band(self, store):
        seed_artifact(store, ART)
        seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        # Returned in-band.
        assert out["results"][0]["context"]["manifest"]["folio_id"] == folio
        # AND persisted under output/manifests/<folio-id>-<ts>.
        rel = out["results"][0]["output"]["path"]
        persisted = store.root / rel
        assert persisted.is_file()
        assert persisted.parent == store.manifests_dir
        assert persisted.name.startswith(f"{folio}-")
        import json

        assert json.loads(persisted.read_bytes())["folio_id"] == folio

    def test_empty_folio_emits_an_empty_work_order(self, store):
        folio = create_folio(store, purpose="p", nonce="n").folio_id
        out = _emit(store, folio)
        assert out["envelope"]["ok"] is True
        assert _rows(out) == []

    def test_missing_folio_is_not_found(self, store):
        # A folio DIRECTORY exists (so the invoke isolation gate resolves the id) but its record is
        # absent — the handler reports not-found honestly (never auto-creates a folio, §20 F6).
        (store.folios_dir / "f-abcabcabcabc").mkdir(parents=True)
        out = _emit(store, "f-abcabcabcabc")
        assert out["results"][0]["code"] == "not-found"

    def test_missing_folio_id_param_is_a_block(self, store):
        handler = manifest.emit_manifest_handler(resolver=FakeResolver(), now=CountingNow())
        out = invoke("emit-manifest", WS, {}, store=store, handlers={"emit-manifest": handler})
        assert out["results"][0]["status"] == "block"


class TestPinAndTargetCoexist:
    def test_a_member_with_both_pin_and_target_yields_both_rows(self, store):
        seed_artifact(store, ART)
        pin_did, _ = seed_deliverable(store, artifact_id=ART, output_type="docx")
        target_did, _ = seed_deliverable(store, artifact_id=ART, output_type=OUTPUT_TYPE)
        folio = make_folio(store, [(ART, pin_did, None)])
        out = _emit(store, folio, member_targets={ART: [COORD]})
        states = sorted(r["state"] for r in _rows(out))
        assert states == ["current", "frozen-pin"]  # the pin row AND the resolved target row


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: manifest.py is SSOT-free (§22.7).
# ---------------------------------------------------------------------------


class TestSsotFree:
    def test_manifest_module_imports_no_ssot(self):
        src = Path(manifest.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    names.add(node.module)
                names.update(f"{node.module or ''}.{a.name}" for a in node.names)
        offending = [n for n in names if "ssot" in n.lower()]
        assert offending == [], f"manifest imports ssot: {offending}"

    def test_manifest_never_writes_ssot_csv(self, store):
        # A behavioral witness: emitting a manifest creates NO ssot.csv anywhere in the store.
        seed_artifact(store, ART)
        seed_deliverable(store, artifact_id=ART)
        folio = make_folio(store, [ART])
        _emit(store, folio, member_targets={ART: [COORD]})
        assert not list(store.root.rglob("ssot.csv"))
