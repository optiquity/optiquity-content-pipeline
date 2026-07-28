"""Step-34 tests: `pipeline.api.discovery` — `list`/`get` (§21.3), filters (§13.2), currency.

Covers, per the acceptance list:

- the self-describing META-TYPES read the LIVE constants (no hardcode): `list codes` ==
  `results.CODES` (a monkeypatched code flows through with no second edit), `list verbs` ==
  `invoke.KNOWN_VERBS`, `list types` == the closed `TYPES`, `list actions` == the injected
  `session.CONTINUE_ACTIONS`;
- the FIVE computed currency fields (`fit_revision`/`fit_current`/`serialize_revision`/
  `serialize_current`/`minted_ts`) surface on the deliverable detail AND filter it — currency
  computed at read from the STORE via the resolver seam, never stored;
- §13.2 `Pred` filters, AND-combined; the reserved filters (`provenance`; lineage
  `source_commit` map-contains);
- **the blast-radius remedy works LITERALLY**: `list deliverables {platform, fit_current:
  false}` returns exactly the stale-fit deliverables, feedable to a `render force_reconcile` loop;
- the `get artifact`/`get deliverable`/`get folio` detail shapes;
- **discovery.py is SSOT-FREE** (§21.3/§22.7): it imports no ssot module and branches on no
  tracker read.

Hermetic: handlers injected via `invoke(handlers=…)`; the currency resolver is a controllable
fake (no live config read); no registry mutation.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from pipeline import reconcile, serialize
from pipeline.api import discovery, results
from pipeline.api.invoke import KNOWN_VERBS, invoke
from pipeline.folios import add_to_folio, create_folio
from pipeline.store import WorkspaceStore

WS = "wsA"
ART = "a-9f3c07d21b44e8aa"
ART2 = "a-1234567890abcdef"
FIXED_TS = "2024-01-01T00:00:00+00:00"
COMMIT = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"

ACTION_VOCAB = frozenset(
    {"generate-next", "render", "add-to-folio", "emit-manifest", "fetch", "status", "list", "get"}
)


@pytest.fixture()
def store(tmp_path):
    s = WorkspaceStore(tmp_path / WS)
    s.ensure_layout()
    return s


class FakeResolver:
    """A controllable currency resolver (no config read): everything is FRESH (current digest ==
    the stored digest) unless its fitted-/deliverable-id is marked STALE, in which case a
    never-matching digest is returned (fit_current/serialize_current → False)."""

    def __init__(self, stale_fits=frozenset(), stale_serials=frozenset()):
        self.stale_fits = set(stale_fits)
        self.stale_serials = set(stale_serials)

    def current_fit_digest(self, *, root, workspace, fitted_id, stored_preimage):
        if fitted_id in self.stale_fits:
            return "ffffffffffff"
        return reconcile.fit_digest(stored_preimage)

    def current_serialize_digest(self, *, root, workspace, deliverable_id, stored_preimage):
        if deliverable_id in self.stale_serials:
            return "ffffffffffff"
        return serialize.serialize_digest(stored_preimage)


def _fit_pre(max_chars: int) -> dict:
    return {
        "strategy": {},
        "hard-limits": {"max_chars": max_chars},
        "advisory": {},
        "render-dims": {},
    }


def _ser_pre(pandoc: str) -> dict:
    return {"tool_bundle": {"pandoc_version": pandoc}, "render_target": {}, "render_inputs": {}}


def seed_deliverable(
    store: WorkspaceStore,
    *,
    artifact_id: str = ART,
    platform: str = "github",
    language: str = "en",
    output_type: str = "md",
    presentation: str = "plain",
    fit_preimage: dict | None = None,
    serialize_preimage: dict | None = None,
    fit_revision: bool = False,
    serialize_revision: bool = False,
) -> tuple[str, str]:
    """Seed a fit record + a render-binding + bytes; return (deliverable_id, fitted_id)."""
    fb = reconcile.build_fit_binding(
        artifact_id=artifact_id,
        platform=platform,
        language=language,
        preimage=fit_preimage or _fit_pre(500),
        strategy="pass",
        localize_languages=[],
        gate_outcome="ok",
        revision=fit_revision,
        minted_ts=FIXED_TS,
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
        minted_ts=FIXED_TS,
    )
    deliverable_id = rb["deliverable_id"]
    record = {
        "binding": rb,
        "layer2": {"path": f"deliverables/{deliverable_id}.md"},
        "side": "internal",
    }
    _write_json(store.output_path(deliverable_id), record)
    store.bytes_path(deliverable_id, "md").write_bytes(b"BODY\n")
    return deliverable_id, fitted_id


def seed_artifact(store: WorkspaceStore, artifact_id: str, commit: str) -> None:
    # The artifact record IS the §15 IR envelope: parts/grounding/metadata/binding at TOP level.
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
            "provenance": "instance",
        },
    )


def _write_json(path: Path, obj) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(obj) + "\n").encode())


def _list(store, type_name, filters=None, *, resolver=None, folio_id=None):
    params = {"type": type_name}
    if filters is not None:
        params["filters"] = filters
    if folio_id is not None:
        params["folio_id"] = folio_id
    handler = discovery.list_handler(resolver=resolver or FakeResolver(), action_vocab=ACTION_VOCAB)
    return invoke("list", WS, params, store=store, handlers={"list": handler})


def _get(store, type_name, id_str, *, resolver=None):
    handler = discovery.get_handler(resolver=resolver or FakeResolver())
    params = {"type": type_name, "id": id_str}
    return invoke("get", WS, params, store=store, handlers={"get": handler})


def _items(out):
    return out["results"]


def _ctx(out):
    """The single-result detail context (the `get` detail shape)."""
    return out["results"][0]["context"]


# ---------------------------------------------------------------------------
# Meta-types — the self-describing vocabularies (LIVE constant reads).
# ---------------------------------------------------------------------------


class TestMetaTypes:
    def test_list_codes_equals_the_live_results_taxonomy(self, store):
        out = _list(store, "codes")
        assert {item["item"] for item in _items(out)} == set(results.CODES)

    def test_list_codes_reflects_a_taxonomy_change_with_no_second_edit(self, store, monkeypatch):
        # Prove `codes` reads the LIVE constant: shrink CODES and discovery reflects it exactly.
        monkeypatch.setattr(results, "CODES", {"not-found": results.CODES["not-found"]})
        out = _list(store, "codes")
        assert {item["item"] for item in _items(out)} == {"not-found"}

    def test_list_verbs_equals_known_verbs(self, store):
        out = _list(store, "verbs")
        assert {item["item"] for item in _items(out)} == set(KNOWN_VERBS)

    def test_list_types_is_the_closed_vocabulary(self, store):
        out = _list(store, "types")
        assert {item["item"] for item in _items(out)} == set(discovery.TYPES)

    def test_list_actions_reads_the_injected_continue_action_set(self, store):
        out = _list(store, "actions")
        assert {item["item"] for item in _items(out)} == set(ACTION_VOCAB)

    def test_unknown_type_is_not_found(self, store):
        out = _list(store, "nonsense")
        assert out["results"][0]["code"] == "not-found"


# ---------------------------------------------------------------------------
# Currency — the five computed-at-read fields (§21.3).
# ---------------------------------------------------------------------------


class TestCurrencyFields:
    def test_deliverable_detail_carries_the_five_currency_fields(self, store):
        did, _ = seed_deliverable(store)
        ctx = _ctx(_get(store, "deliverables", did))
        five = (
            "fit_revision", "fit_current", "serialize_revision", "serialize_current", "minted_ts",
        )
        for field in five:
            assert field in ctx
        assert ctx["minted_ts"] == FIXED_TS

    def test_fresh_vs_stale_fit_current(self, store):
        fresh, fresh_fit = seed_deliverable(store)
        stale, stale_fit = seed_deliverable(store, artifact_id=ART2, fit_preimage=_fit_pre(200))
        resolver = FakeResolver(stale_fits={stale_fit})
        assert _ctx(_get(store, "deliverables", fresh, resolver=resolver))["fit_current"] is True
        assert _ctx(_get(store, "deliverables", stale, resolver=resolver))["fit_current"] is False

    def test_serialize_current_and_revision_label(self, store):
        did, _ = seed_deliverable(store, serialize_revision=True)  # a revision deliverable
        ctx = _ctx(_get(store, "deliverables", did))
        assert ctx["serialize_revision"] != "baseline"  # a hex12 revision qualifier
        assert ctx["serialize_current"] is True  # fresh by default (resolver)

    def test_baseline_revision_labels(self, store):
        did, _ = seed_deliverable(store)  # baseline fit + baseline serialize
        ctx = _ctx(_get(store, "deliverables", did))
        assert ctx["fit_revision"] == "baseline" and ctx["serialize_revision"] == "baseline"


# ---------------------------------------------------------------------------
# §13.2 filters, AND-combined + the blast-radius remedy.
# ---------------------------------------------------------------------------


GITHUB_STALE = {"platform": "github", "fit_current": False}


class TestFilters:
    def test_and_combined_platform_and_currency(self, store):
        fresh, _ = seed_deliverable(store, platform="github")
        stale, stale_fit = seed_deliverable(
            store, artifact_id=ART2, platform="github", fit_preimage=_fit_pre(200)
        )
        resolver = FakeResolver(stale_fits={stale_fit})
        # AND: github AND stale → exactly the stale one.
        out = _list(store, "deliverables", GITHUB_STALE, resolver=resolver)
        assert {i["item"] for i in _items(out)} == {stale}
        # A non-matching platform in the conjunction → empty.
        other = {"platform": "linkedin", "fit_current": False}
        assert _items(_list(store, "deliverables", other, resolver=resolver)) == []

    def test_blast_radius_remedy_is_literal_and_feedable_to_render(self, store):
        # THE acceptance loop: list the platform-tightened stale-fit deliverables, then feed each
        # to a `render force_reconcile`. Here we assert the query returns exactly the stale set.
        s1, _ = seed_deliverable(store, platform="github")  # fresh
        s2, fit2 = seed_deliverable(
            store, artifact_id=ART2, platform="github", fit_preimage=_fit_pre(200)
        )
        resolver = FakeResolver(stale_fits={fit2})
        out = _list(store, "deliverables", GITHUB_STALE, resolver=resolver)
        stale_ids = [i["ids"]["deliverable_id"] for i in _items(out)]
        assert stale_ids == [s2]  # exactly the stale-fit deliverable, feedable to force_reconcile
        # Each returned id carries the coordinates a `render(..., force_reconcile=True)` needs.
        ctx = _items(out)[0]["context"]
        assert ctx["platform"] == "github" and ctx["output_type"] and ctx["presentation"]

    def test_pred_ops_in_prefix_range(self, store):
        seed_deliverable(store, output_type="md")
        in_pred = [{"path": "output_type", "op": "in", "value": ["md", "html"]}]
        assert len(_items(_list(store, "deliverables", in_pred))) == 1
        prefix_pred = [{"path": "platform", "op": "prefix", "value": "git"}]
        assert len(_items(_list(store, "deliverables", prefix_pred))) == 1
        range_pred = [{"path": "minted_ts", "op": "range", "value": ["2020-01-01", "2030-01-01"]}]
        assert len(_items(_list(store, "deliverables", range_pred))) == 1
        none_pred = [{"path": "platform", "op": "eq", "value": "nope"}]
        assert _items(_list(store, "deliverables", none_pred)) == []

    def test_reserved_provenance_filter(self, store):
        seed_deliverable(store)
        assert len(_items(_list(store, "deliverables", {"provenance": "instance"}))) == 1
        assert _items(_list(store, "deliverables", {"provenance": "framework"})) == []

    def test_reserved_source_commit_map_contains(self, store):
        seed_artifact(store, ART, COMMIT)
        seed_artifact(store, ART2, "0" * 40)
        hit_pred = [{"path": "source_commit", "op": "eq", "value": COMMIT}]
        hit = _list(store, "artifacts", hit_pred)
        assert {i["item"] for i in _items(hit)} == {ART}  # map-contains: the sha is a commit value
        miss_pred = [{"path": "source_commit", "op": "eq", "value": "deadbeef"}]
        assert _items(_list(store, "artifacts", miss_pred)) == []

    def test_malformed_filter_is_a_typed_block(self, store):
        out = _list(store, "deliverables", [{"op": "eq", "value": "x"}])  # missing `path`
        assert out["results"][0]["status"] == "block"


# ---------------------------------------------------------------------------
# get detail shapes + folios.
# ---------------------------------------------------------------------------


class TestGetDetail:
    def test_get_artifact_detail_shape(self, store):
        seed_artifact(store, ART, COMMIT)
        ctx = _get(store, "artifacts", ART)["results"][0]["context"]
        assert ctx["preimage"] and ctx["metadata"] == {"k": "v"}
        assert ctx["grounding_ledger_size"] == 1
        assert ctx["source_commit"] == {"acme": COMMIT}
        assert ctx["part_ids"] == [f"{ART}~intro"]

    def test_get_deliverable_detail_has_path_and_side(self, store):
        did, _ = seed_deliverable(store)
        ctx = _get(store, "deliverables", did)["results"][0]["context"]
        assert ctx["path"].endswith(".md") and ctx["side"] == "internal"


# ---------------------------------------------------------------------------
# DR-5 C6 carry-forward: the REAL currency resolver re-derives the OMIT-WHEN-ABSENT
# `citeproc_enablement_version` flag from the stored tool_bundle so a CITING deliverable reports NO
# spurious drift (the EXACT twin of the SD-5 `section_attr_transform_version` derivation).
# ---------------------------------------------------------------------------


_C6_RT = {"writer": "html5", "engine": "", "reference_doc": ""}
_C6_RI = {"flags": [], "variables": {}, "assets": [], "engine": ""}


class TestC6CiteprocCurrencyCarryForward:
    def test_stored_citing_deliverable_reports_no_spurious_drift(self, tmp_path):
        resolver = discovery.DefaultCurrencyResolver()
        # A CITING stored preimage (`--citeproc` resolved a bibliography, altering bytes) mints a
        # DIFFERENT digest than the same inputs non-citing — so a rebuild MUST re-derive the flag.
        citing = serialize.serialize_inputs_preimage(
            render_target=_C6_RT, render_inputs=_C6_RI, citeproc_enabled=True
        )
        non_citing = serialize.serialize_inputs_preimage(
            render_target=_C6_RT, render_inputs=_C6_RI, citeproc_enabled=False
        )
        assert "citeproc_enablement_version" in citing["tool_bundle"]
        assert serialize.serialize_digest(citing) != serialize.serialize_digest(non_citing)

        # The live resolver re-derives the flag from the stored bundle → the citing deliverable
        # reports NO spurious drift (a pre-fix rebuild would omit the key and drift).
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="citing", stored_preimage=citing
        )
        assert current == serialize.serialize_digest(citing)

    def test_non_citing_deliverable_still_reports_no_drift(self, tmp_path):
        # Control: the fix is additive — a non-citing deliverable (no citeproc key) is unperturbed.
        resolver = discovery.DefaultCurrencyResolver()
        non_citing = serialize.serialize_inputs_preimage(
            render_target=_C6_RT, render_inputs=_C6_RI, citeproc_enabled=False
        )
        assert "citeproc_enablement_version" not in non_citing["tool_bundle"]
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="plain", stored_preimage=non_citing
        )
        assert current == serialize.serialize_digest(non_citing)

    def test_citeproc_and_section_attr_flags_both_carry_forward(self, tmp_path):
        # A deliverable that is BOTH typed AND citing carries both keys; the resolver re-derives
        # BOTH → no drift (the two carry-forwards are independent and compose).
        resolver = discovery.DefaultCurrencyResolver()
        both = serialize.serialize_inputs_preimage(
            render_target=_C6_RT,
            render_inputs=_C6_RI,
            section_attr_transformed=True,
            citeproc_enabled=True,
        )
        assert {"section_attr_transform_version", "citeproc_enablement_version"} <= set(
            both["tool_bundle"]
        )
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="both", stored_preimage=both
        )
        assert current == serialize.serialize_digest(both)

    def test_get_nonresolving_id_is_isolation_fatal(self, store):
        # `get`'s id is Gate-3-isolated: a non-resolving id is refused envelope-fatally by the
        # invoke gate BEFORE the handler (the honest contract — never a masked not-found).
        out = _get(store, "deliverables", "a-9f3c07d21b44e8aa.github.en.md.plain")
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["code"] == "isolation-violation"

    def test_get_unknown_type_is_not_found(self, store):
        seed_artifact(store, ART, COMMIT)  # a resolvable id so the gate passes
        out = _get(store, "codes", ART)  # `codes` is a meta-type — not id-addressed
        assert out["results"][0]["code"] == "not-found"

    def test_folios_and_members(self, store):
        seed_artifact(store, ART, COMMIT)  # is_done(ART) → membership allowed
        folio = create_folio(store, purpose="launch", nonce="n").folio_id
        add_to_folio(store, folio, [ART])
        folios = _list(store, "folios")
        assert {i["item"] for i in _items(folios)} == {folio}
        members = _list(store, "folio-members", folio_id=folio)
        assert {i["context"]["artifact_id"] for i in _items(members)} == {ART}
        detail = _get(store, "folios", folio)["results"][0]["context"]
        assert detail["purpose"] == "launch" and len(detail["members"]) == 1


# ---------------------------------------------------------------------------
# B (F2) carry-forward: the REAL currency resolver re-derives the OMIT-WHEN-ABSENT
# `asset_embed_version` flag from the stored tool_bundle so a picture-bearing html/docx deliverable
# reports NO spurious drift (the THIRD such twin, after SD-5 section-attr and C6 citeproc).
# ---------------------------------------------------------------------------


_EMBED_RT = {"writer": "html5", "engine": "", "reference_doc": ""}
_EMBED_RI = {"flags": [], "variables": {}, "assets": [], "engine": ""}
_EMBED_FOLD = (("assets/x.png", "a" * 64),)


class TestBAssetEmbedCurrencyCarryForward:
    def test_stored_embedded_deliverable_reports_no_spurious_drift(self, tmp_path):
        resolver = discovery.DefaultCurrencyResolver()
        # An EMBEDDING stored preimage (a figure was inlined → the bytes carry it) mints a DIFFERENT
        # digest than the same inputs non-embedding — so a rebuild MUST re-derive the flag.
        embedded = serialize.serialize_inputs_preimage(
            render_target=_EMBED_RT,
            render_inputs=_EMBED_RI,
            assets_embedded=True,
            embedded_assets=_EMBED_FOLD,
        )
        non_embedded = serialize.serialize_inputs_preimage(
            render_target=_EMBED_RT, render_inputs=_EMBED_RI
        )
        assert "asset_embed_version" in embedded["tool_bundle"]
        assert embedded["render_inputs"]["embedded_assets"] == [["assets/x.png", "a" * 64]]
        assert serialize.serialize_digest(embedded) != serialize.serialize_digest(non_embedded)

        # The live resolver re-derives the flag from the stored bundle AND carries the stored
        # `embedded_assets` through verbatim → the embedded deliverable reports NO phantom drift.
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="pic", stored_preimage=embedded
        )
        assert current == serialize.serialize_digest(embedded)

    def test_non_embedded_deliverable_still_reports_no_drift(self, tmp_path):
        # Control: additive — a by-reference (md/image-less) deliverable is unperturbed.
        resolver = discovery.DefaultCurrencyResolver()
        non_embedded = serialize.serialize_inputs_preimage(
            render_target=_EMBED_RT, render_inputs=_EMBED_RI
        )
        assert "asset_embed_version" not in non_embedded["tool_bundle"]
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="ref", stored_preimage=non_embedded
        )
        assert current == serialize.serialize_digest(non_embedded)

    def test_embed_composes_with_the_other_two_carry_forwards(self, tmp_path):
        # A deliverable that is typed AND citing AND embedding carries all three keys; the resolver
        # re-derives all three → no drift (the carry-forwards are independent and compose).
        resolver = discovery.DefaultCurrencyResolver()
        allthree = serialize.serialize_inputs_preimage(
            render_target=_EMBED_RT,
            render_inputs=_EMBED_RI,
            section_attr_transformed=True,
            citeproc_enabled=True,
            assets_embedded=True,
            embedded_assets=_EMBED_FOLD,
        )
        assert {
            "section_attr_transform_version",
            "citeproc_enablement_version",
            "asset_embed_version",
        } <= set(allthree["tool_bundle"])
        current = resolver.current_serialize_digest(
            root=tmp_path, workspace=WS, deliverable_id="all3", stored_preimage=allthree
        )
        assert current == serialize.serialize_digest(allthree)


# ---------------------------------------------------------------------------
# INV-CORRECTNESS: discovery.py is SSOT-free (§21.3/§22.7).
# ---------------------------------------------------------------------------


class TestSsotFree:
    def test_discovery_module_imports_no_ssot(self):
        src = Path(discovery.__file__).read_text(encoding="utf-8")
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
        assert offending == [], f"discovery imports ssot: {offending}"

    def test_discovery_does_not_import_session_no_cycle(self):
        # discovery must NOT import session (session imports discovery for the list/get delegation
        # — an import cycle) and stays off the generation/ssot stack.
        src = Path(discovery.__file__).read_text(encoding="utf-8")
        assert "import session" not in src and "api.session" not in src
