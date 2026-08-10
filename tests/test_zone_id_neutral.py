"""Z4 proofs — a ZONE is NOT part of identity (§23/§7 content-addressing; the atomic cutover).

Two committed proofs the reviewer named:

- **NO-ID-CHURN (e.3).** Produce a FULL workspace tree (grounded artifacts + fitted/serialized
  deliverables + a folio + the SSOT) at the default zone, then RELOCATE the whole subtree through
  the legacy 2-level layout (`users/<u>/workspaces/<ws>`) into a DIFFERENT zone
  (`users/<u>/zones/work/workspaces/<ws>`), and re-read via the ZONED door. Every id-bearing surface
  is BYTE-IDENTICAL: the `list`-visible record ids, the re-resolved `plan_hash` +
  `plan.deliverable_ids()` + preview artifact-ids, `folios_for_artifact`, and the SSOT bytes. Ids
  are content-addressed, so relocating the tree (a different framework root / user / zone) never
  renames a single record — proof the zone is a PLACEMENT prefix, never identity.

- **Q2 store-isolation (e.4).** Two stores for the SAME `(user, workspace)` in DISTINCT zones mint
  IDENTICAL id STRINGS (the filename is the content-addressed id, zone-free) but resolve to DISTINCT
  `.root`s, and a write into one never appears in the other — structural isolation by root, with no
  id collision across zones.

The producer is the hermetic §25 MVP scenario (real registries + a mock source pool + a faked
transport — no spend, no `ANTHROPIC_API_KEY`); it serializes real bytes via the pinned pandoc, so
the relocation proof is pandoc-gated (skip when the binary is absent, like the MVP scenario). All
fixtures are generic; no instance content (passes `scripts/check-no-content.sh`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

# The hermetic §25 world builder + faked transport seams live in the MVP scenario module (reused,
# never duplicated). Under pytest's prepend import mode a sibling test module imports by bare name.
from test_mvp_scenario import (  # noqa: E402
    NOW,
    USER,
    WS,
    PreciseCurrencyResolver,
    ReviewRunner,
    WriterRunner,
    _adapters,
    build_world,
)

from pipeline import mvpdemo
from pipeline.api import invoke as invoke_mod
from pipeline.api import session
from pipeline.api.render import DefaultRenderEngine
from pipeline.folios import folios_for_artifact
from pipeline.ids import IdError, parse_id
from pipeline.serialize import pandoc_available
from pipeline.store import WorkspaceStore

#: A valid artifact id (a-<hex16>) + a fitted id, for the zone-free store-isolation proof.
ART = "a-9f3c07d21b44e8aa"
FIT = "a-9f3c07d21b44e8aa.linkedin.en"

#: The begin-session (preview) params the MVP scenario drives — reused so the re-resolved plan is
#: EXACTLY the one produced, and the preview is LLM-free (no spend on the re-read).
BEGIN_PARAMS = {
    "recipe": mvpdemo.RECIPE,
    "topics": list(mvpdemo.SEQ_TOPICS),
    "platforms": [mvpdemo.PLATFORM],
    "languages": [mvpdemo.LANGUAGE],
    "output_types": [mvpdemo.INTERNAL_OUTPUT_TYPE],
    "presentations": [mvpdemo.PLAIN_PRESENTATION, mvpdemo.STYLED_PRESENTATION],
    "overrides": mvpdemo.OVERRIDES,
    "run_selection": mvpdemo.M3_RUN_SELECTION,
}


def _record_names(store: WorkspaceStore) -> list[str]:
    """The sorted id-addressed record + folio names across the store — the `list`-visible id set.
    Every name is a content-addressed id (or an id-derived layer-2 sibling / folio dir), so it is
    PLACEMENT-independent: relocating the store tree must not rename any of them."""
    out: list[str] = []
    for d in (store.artifacts_dir, store.deliverables_dir, store.folios_dir, store.reviews_dir):
        if d.is_dir():
            out.extend(p.name for p in d.iterdir())
    return sorted(out)


def _first_artifact_id(store: WorkspaceStore) -> str:
    """The first artifact-level record id in the store (for the folio-membership read)."""
    for p in sorted(store.artifacts_dir.iterdir()):
        try:
            parsed = parse_id(p.name)
        except IdError:
            continue
        if parsed.family == "artifact" and parsed.level == "artifact" and parsed.part is None:
            return p.name
    raise AssertionError("the produced workspace must hold at least one artifact record")


def _preview(root: Path, zone: str) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Re-resolve the plan via the ZONED begin-session door (LLM-free): returns the byte-stable
    (plan_hash, plan.deliverable_ids(), preview artifact-ids). Mirrors the scenario's own
    begin-session → decode → `_resolve_from_inputs` path, so the values are the produced plan's."""
    handler = session.begin_session_handler(adapters=_adapters())
    result = invoke_mod.invoke(
        "begin-session",
        WS,
        USER,
        dict(BEGIN_PARAMS),
        root=str(root),
        zone=zone,
        handlers={"begin-session": handler},
    )
    token = invoke_mod.token_mod.decode(result["token"], expected_workspace=WS)
    plan, _env, _pool, _repos = session._resolve_from_inputs(
        Path(root), USER, WS, zone, token.inputs
    )
    return (
        plan.plan_hash,
        tuple(plan.deliverable_ids()),
        tuple(item.artifact_id for item in plan.items),
    )


@pytest.mark.skipif(
    not pandoc_available(), reason="the id-churn relocation proof serializes real bytes via pandoc"
)
def test_ids_survive_the_legacy_to_zoned_relocation(tmp_path):
    root = build_world(tmp_path)  # the workspace config/sources live at zones/default/workspaces/WS

    # -- PRODUCE the full tree at the default zone (artifacts + deliverables + a folio + the SSOT).
    mvpdemo.run_mvp_scenario(
        root=root,
        user=USER,
        workspace=WS,
        zone="default",
        adapters=_adapters(),
        runner=WriterRunner(),
        review_runner=ReviewRunner(),
        render_engine=DefaultRenderEngine(),
        currency_resolver=PreciseCurrencyResolver(),
        now=NOW,
    )
    store_default = WorkspaceStore.at(root, USER, WS, zone="default")
    names_before = _record_names(store_default)
    assert names_before, "the produced workspace must hold id-addressed records"
    art_id = _first_artifact_id(store_default)
    folios_before = folios_for_artifact(store_default, art_id)
    assert folios_before, (
        "the scenario adds the artifact to a folio (folios_for_artifact non-empty)"
    )
    ssot_before = (store_default.root / "ssot.csv").read_bytes()
    assert b"artifact" in ssot_before  # a real SSOT coordinate row is present
    ph_before, del_before, prev_before = _preview(root, "default")

    # -- RELOCATE the whole workspace subtree: default -> the LEGACY 2-level layout -> a DIFFERENT
    #    zone. The registries + instance defaults stay at `root` (shared); only the workspace moves.
    ws_default = root / "users" / USER / "zones" / "default" / "workspaces" / WS
    ws_legacy = root / "users" / USER / "workspaces" / WS  # the pre-zone (legacy) 2-level home
    ws_legacy.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ws_default), str(ws_legacy))
    ws_work = root / "users" / USER / "zones" / "work" / "workspaces" / WS
    ws_work.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(ws_legacy), str(ws_work))

    # -- RE-READ via the ZONED door at the relocated zone: every id-bearing surface is byte-stable.
    store_work = WorkspaceStore.at(root, USER, WS, zone="work")
    assert store_work.root != store_default.root  # the tree really moved (a distinct placement)
    assert _record_names(store_work) == names_before  # list ids: byte-identical (content-address)
    assert folios_for_artifact(store_work, art_id) == folios_before  # folio ids: byte-identical
    assert (store_work.root / "ssot.csv").read_bytes() == ssot_before  # SSOT bytes: byte-identical

    ph_after, del_after, prev_after = _preview(root, "work")  # RE-RESOLVE via the relocated config
    assert ph_after == ph_before  # plan_hash: byte-identical (the zone is not in the plan identity)
    assert del_after == del_before  # plan.deliverable_ids(): byte-identical
    assert prev_after == prev_before  # preview artifact-ids: byte-identical


def test_store_isolation_identical_ids_distinct_roots(tmp_path):
    # Q2: the SAME (user, workspace) in two DISTINCT zones — identical id STRINGS, distinct roots.
    s_work = WorkspaceStore.at(tmp_path, "dave", "acme", zone="work")
    s_personal = WorkspaceStore.at(tmp_path, "dave", "acme", zone="personal")

    # IDENTICAL id strings: the filename IS the zone-free content-addressed id.
    assert s_work.output_path(ART).name == s_personal.output_path(ART).name == ART
    assert s_work.claim_path(FIT).name == s_personal.claim_path(FIT).name == FIT
    # DISTINCT roots: the zone is the placement prefix, so the stores never overlap.
    assert s_work.root != s_personal.root
    assert s_work.zone == "work" and s_personal.zone == "personal"

    # A write into one zone NEVER appears in the other (structural isolation by root).
    written = s_work.output_path(ART)
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_text("work-only", encoding="utf-8")
    assert s_work.output_path(ART).exists()
    assert not s_personal.output_path(ART).exists()
