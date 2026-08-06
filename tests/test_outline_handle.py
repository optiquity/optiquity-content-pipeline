"""CLI-UX C7 (DR-3): the outline continuation-handle drift guard (`--from` / `--allow-drift`).

The safe-outline crux, driven end to end on the REAL paths — never a hand-built matching preimage
(the inert-test trap the adversarial pass caught). Every scenario drives the REAL `emit-outline`
handler + the REAL `begin-session` handler in a workspace that CONTAINS `sources/*.md`, so both the
emit side and the drive side compute their `source_subset` from the SAME non-empty pool (the B-2
fix). The grounding pass never runs (begin-session is plan-only), so no live subscription call is
made; the source commit-map is pinned through a `MockAdapter` (a read-only provenance read).

What the guard does (design `ops-handoff/cli-ux-design/architect-reconciliation.md`, "The WORKING
outline continuation-handle"): the drive carries the emit-outline artifact-id as `outline_parent`
(friendly `--from`); the guard recovers the phase-1 emit preimage by that id from THIS workspace's
output store and compares it to the phase-2 drive preimage over the EDIT-INVARIANT, FORMAT-
INDEPENDENT projection σ = {topic, persona, voice, goals, source-subset, lexicon}. It EXCLUDES
`format` (emit=outline vs drive=real), `source-commit` (live-pinned afresh at drive), and
`outline-digest` (D1 vs the hand-edited D2) — the three keys that legitimately differ emit→drive.

  B-2 crux ....... unchanged config, emit→hand-edit→drive → MATCH / proceed (no false alarm)
  fat-finger ..... a different --persona → outline-config-drift BLOCK, nothing spends
  source pool .... a source added between the phases → BLOCK (σ includes source-subset)
  format+commit .. a real-format drive under a different pinned commit → MATCH (both excluded)
  S-3 ............ a present-but-unresolved --from → not-found BLOCK (loud, pre-spend)
  absent --from .. → outline-config-unverified WARN + proceed
  --allow-drift .. the block downgrades to a recorded WARN + proceeds
  identity ....... the driven artifact-id + preimage are byte-identical with vs without --from
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline.adapters.base import TIER_EXTRACTED, Anchor, Fact
from pipeline.adapters.mock import MockAdapter
from pipeline.api import token as token_mod
from pipeline.api.invoke import KNOWN_VERBS, invoke
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.outline import outline_digest
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "c7ws"
USER = "acme"
RECIPE = "explainer-post"
TOPIC_ID = "x-architecture"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC_MD = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"
SOURCE_MD = (
    "---\n"
    "id: {sid}\n"
    "provenance: instance\n"
    "schema_version: 1\n"
    "adapter: mock\n"
    "connection:\n"
    "  dataset: {ds}\n"
    "content_kind: general\n"
    "trusted: 4\n"
    "independence: first-party\n"
    "primariness: primary\n"
    "---\n\nSynthetic mock source.\n"
)

#: A DRAFT outline (emit) and a hand-EDITED one (drive): a different normalized body → a different
#: `outline-digest` (D2 ≠ D1). The guard EXCLUDES the digest, so the edit alone never false-alarms.
DRAFT = "# Architecture\n\n- what it is\n- how it is arranged\n"
EDITED = (
    "# Architecture\n\n## What it is\n- a concise definition\n\n"
    "## How it is arranged\n- the parts\n"
)

FACTS = (
    Fact(
        subject="architecture.layers",
        claim="The architecture is arranged in three layers.",
        tier=TIER_EXTRACTED,
        anchors=(Anchor("file-line", "docs/arch.md:1"),),
        as_of=date(2026, 5, 1),
    ),
)


# --- fixtures ---------------------------------------------------------------------------------


def build_root(tmp_path: Path, *, sources: tuple[tuple[str, str], ...] = (("x-arch-src", "arch"),)):
    """A full framework root (real registries) + a tmp instance/workspace WITH `sources/*.md`, so
    `driver._list_source_ids` is NON-EMPTY (the whole point of the B-2 real-path acceptance)."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    ws = root / "users" / USER / "workspaces" / WS
    (ws / "topics").mkdir(parents=True)
    (ws / "topics" / f"{TOPIC_ID}.md").write_text(
        TOPIC_MD.format(tid=TOPIC_ID, why="Architecture."), encoding="utf-8"
    )
    add_sources(root, *sources)
    return root


def add_sources(root: Path, *sources: tuple[str, str]) -> None:
    """Write `sources/<sid>.md` mock source entries into the workspace (used to CHANGE the pool
    between emit and drive — the σ source-subset probe)."""
    sources_dir = root / "users" / USER / "workspaces" / WS / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    for sid, dataset in sources:
        (sources_dir / f"{sid}.md").write_text(
            SOURCE_MD.format(sid=sid, ds=dataset), encoding="utf-8"
        )


def store_for(root: Path) -> WorkspaceStore:
    store = WorkspaceStore.at(root, USER, WS)
    store.ensure_layout()
    return store


def mocks(*, arch_commit: str | None = None, arch2_commit: str | None = None) -> dict:
    """The injected `{adapter: MockAdapter}` set. `pin_commit` returns a per-dataset commit
    (synthetic unless overridden) — a read-only provenance read, never a grounding/live call."""
    commits: dict[str, str] = {}
    if arch_commit is not None:
        commits["arch"] = arch_commit
    if arch2_commit is not None:
        commits["arch2"] = arch2_commit
    return {"mock": MockAdapter({"arch": FACTS, "arch2": FACTS}, commits=commits or None)}


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke registry (the §21.9 money-safety idiom)."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


class FakeRun:
    """The injected per-item generation seam: MATERIALIZES the artifact-id in the store (proving the
    spend path is reachable) — never a live compose/render call. `calls` records every driven id."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *, store: WorkspaceStore, item, **_kwargs):
        aid = item.artifact_id
        self.calls.append(aid)
        store.output_path(aid).write_bytes(b"{}\n")
        return SimpleNamespace(artifact_id=aid, deliverables=())


# --- driving the REAL emit + begin-session paths ----------------------------------------------


def emit(root: Path, store: WorkspaceStore, adapters: dict, *, outline: str = DRAFT, **over) -> str:
    """Drive the REAL `emit-outline` handler (with a mock commit-pin adapter) and return the emitted
    artifact-id — the continuation HANDLE. Passes NO source flags: the B-2 emit-side default pins
    the workspace pool identically to the drive path."""
    params = {"outline": outline, "recipe": RECIPE, "topic": TOPIC_ID, **over}
    out = invoke(
        "emit-outline", WS, USER, params, store=store, root=str(root),
        handlers={"emit-outline": session.emit_outline_handler(adapters=adapters)},
    )
    assert out["envelope"]["ok"] is True, out
    item = out["results"][0]
    assert item["status"] == "ok", item  # a fresh emit is plain ok (not a block)
    return item["ids"]["artifact_id"]


def drive(
    root: Path,
    store: WorkspaceStore,
    adapters: dict,
    *,
    outline: str = EDITED,
    persona: str | None = None,
    outline_parent: str | None = None,
    allow_drift: bool = False,
) -> dict:
    """Drive the REAL `begin-session` handler over an INGESTED outline (no source flags). The ingest
    coordinate mirrors the fanned combo (topic + optional persona) so the outline drives exactly the
    one artifact `outline_for` matches. Returns the raw `{envelope, results, [token]}` output."""
    coordinate: dict = {"topic": TOPIC_ID}
    params: dict = {
        "recipe": RECIPE,
        "topics": [TOPIC_ID],
        "platforms": ["github"],
        "target_folio": "auto",  # a folio would mint on proceed — proves a BLOCK mints none (R7)
    }
    if persona is not None:
        coordinate["persona"] = persona
        params["personas"] = [persona]
    params["ingest_outlines"] = [{"coordinate": coordinate, "text": outline}]
    if outline_parent is not None:
        params["outline_parent"] = outline_parent
    if allow_drift:
        params["allow_drift"] = True
    return invoke(
        "begin-session", WS, USER, params, store=store, root=str(root),
        handlers={"begin-session": session.begin_session_handler(adapters=adapters)},
    )


def _codes(out: dict) -> list[str | None]:
    return [item.get("code") for item in out["results"]]


def _statuses(out: dict) -> list[str]:
    return [item["status"] for item in out["results"]]


# --- the walkthrough, as tests ----------------------------------------------------------------


def test_edited_outline_unchanged_config_matches(tmp_path):
    """B-2 (a), the crux: emit → hand-edit → drive under the SAME config → σ MATCH → proceed. The
    run the FIRST design false-blocked (emit's empty source-subset vs drive's full pool)."""
    root = build_root(tmp_path)
    store = store_for(root)
    adapters = mocks()
    handle = emit(root, store, adapters, outline=DRAFT)
    out = drive(root, store, adapters, outline=EDITED, outline_parent=handle)

    assert out["envelope"]["ok"] is True
    assert "token" in out  # proceeded: the token minted, the runner is reachable
    assert "outline-config-drift" not in _codes(out)  # NO false alarm despite D1≠D2
    assert "not-found" not in _codes(out)
    # the edit really changed the driving digest — the guard survived it (excludes outline-digest).
    assert outline_digest(EDITED) != outline_digest(DRAFT)


def test_edited_outline_drift_blocks(tmp_path):
    """B-2 (b), the fat-finger: drive with a DIFFERENT persona → outline-config-drift BLOCK, and
    NOTHING spends — no token, no auto-folio minted (the guard fires before both, R7)."""
    root = build_root(tmp_path)
    store = store_for(root)
    adapters = mocks()
    handle = emit(root, store, adapters, outline=DRAFT)  # default persona (technical-evaluator)
    out = drive(root, store, adapters, outline=EDITED, persona="product-manager",
                outline_parent=handle)

    assert "outline-config-drift" in _codes(out)
    block = out["results"][0]
    assert block["status"] == "block" and block["code"] == "outline-config-drift"
    assert "token" not in out  # nothing spends
    assert not any(store.folios_dir.iterdir())  # NO empty folio leaked (guard before folio mint)


def test_source_pool_change_blocks(tmp_path):
    """B-2 (c): a source ADDED between emit and drive changes the pool {arch} → {arch, arch2}, so
    σ.source-subset differs → outline-config-drift BLOCK (σ genuinely includes source-subset)."""
    root = build_root(tmp_path)
    store = store_for(root)
    adapters = mocks()
    handle = emit(root, store, adapters, outline=DRAFT)  # pool captured = {x-arch-src}
    add_sources(root, ("x-arch-src2", "arch2"))  # the drive now sees a two-source pool
    out = drive(root, store, adapters, outline=EDITED, outline_parent=handle)

    assert "outline-config-drift" in _codes(out)
    assert "token" not in out


def test_format_and_source_commit_differ_still_match(tmp_path):
    """A real-format drive of an edited outline under a DIFFERENT pinned commit → MATCH. `format`
    (emit=outline vs drive=short-opinion-post) and `source-commit` (emit-pinned vs drive-pinned) are
    BOTH excluded from σ, so neither false-alarms."""
    root = build_root(tmp_path)
    store = store_for(root)
    handle = emit(root, store, mocks(arch_commit="a" * 40), outline=DRAFT)
    out = drive(root, store, mocks(arch_commit="b" * 40), outline=EDITED, outline_parent=handle)

    assert out["envelope"]["ok"] is True and "token" in out
    assert "outline-config-drift" not in _codes(out)
    assert "a" * 40 != "b" * 40  # the pinned commits genuinely differed across the two phases


def test_present_but_unresolved_from_is_not_found_block(tmp_path):
    """S-3: a PRESENT-but-unresolved --from (a typo / cross-workspace id) is a LOUD pre-spend
    not-found BLOCK — mint no token, spend nothing. Distinct from the absent-handle warn below."""
    root = build_root(tmp_path)
    store = store_for(root)
    out = drive(root, store, mocks(), outline=EDITED, outline_parent="a-deadbeefdeadbeef")

    assert "not-found" in _codes(out)
    block = out["results"][0]
    assert block["status"] == "block" and block["item"] == "a-deadbeefdeadbeef"
    assert "token" not in out
    assert not any(store.folios_dir.iterdir())  # nothing spent, no folio minted


def test_absent_from_warns_unverified(tmp_path):
    """A driven outline with NO --from handle: nothing to check against → outline-config-unverified
    WARN + proceed (the ONLY warned case for a driven outline)."""
    root = build_root(tmp_path)
    store = store_for(root)
    out = drive(root, store, mocks(), outline=EDITED, outline_parent=None)

    assert "outline-config-unverified" in _codes(out)
    warn = next(it for it in out["results"] if it.get("code") == "outline-config-unverified")
    assert warn["status"] == "warn"
    assert "token" in out  # proceeded


def test_allow_drift_downgrades_to_coded_warn(tmp_path):
    """--allow-drift: a real σ mismatch downgrades from a BLOCK to a recorded WARN carrying its OWN
    §21.7 code `outline-config-drift` (one condition, two dispositions — not a code-less warn), the
    token mints, and the spend proceeds under a --go drive (the honest 'I meant to change it')."""
    root = build_root(tmp_path)
    store = store_for(root)
    adapters = mocks()
    handle = emit(root, store, adapters, outline=DRAFT)
    out = drive(root, store, adapters, outline=EDITED, persona="product-manager",
                outline_parent=handle, allow_drift=True)

    assert "block" not in _statuses(out)  # NOT a block anymore
    assert "token" in out  # the token minted — spend is now allowed
    warn = next(it for it in out["results"] if it["status"] == "warn")
    assert warn["code"] == "outline-config-drift"  # recorded under its OWN code, status=warn
    assert warn["category"] == "generation"  # the §21.7 generation tier
    assert "allow-drift" in (warn.get("remediation") or {}).get("hint", "")

    # the spend truly proceeds: a --go generate-next drives the one artifact through a fake runner.
    run = FakeRun()
    cont = invoke(
        "continue-session", WS, USER, {"action": "generate-next", "batch_size": "all"},
        token=out["token"], store=store, root=str(root),
        handlers={"continue-session": session.continue_session_handler(
            adapters=adapters, run_artifact=run
        )},
    )
    assert cont["envelope"]["ok"] is True
    assert len(run.calls) == 1  # the driven artifact materialized (spend reached)


def test_handle_is_identity_neutral(tmp_path):
    """Identity: driving WITH and WITHOUT --from (same coordinate, matching config) yields a
    BYTE-IDENTICAL driven artifact-id + plan_hash (so the preimage is identical). `outline_parent`
    is a pure guard input, never folded into identity (DR-3 horn-(a))."""
    root = build_root(tmp_path)
    store = store_for(root)
    adapters = mocks()
    handle = emit(root, store, adapters, outline=DRAFT)

    with_from = drive(root, store, adapters, outline=EDITED, outline_parent=handle)
    without_from = drive(root, store, adapters, outline=EDITED, outline_parent=None)

    ids_with = with_from["results"][0]["ids"]["artifact_ids"]
    ids_without = without_from["results"][0]["ids"]["artifact_ids"]
    assert ids_with == ids_without  # the driven artifact-id is unchanged by the handle
    tok_with = token_mod.decode(with_from["token"], expected_workspace=WS)
    tok_without = token_mod.decode(without_from["token"], expected_workspace=WS)
    assert tok_with.plan_hash == tok_without.plan_hash  # ⇒ byte-identical preimage


# --- the σ projection: exactly the right keys in / out ----------------------------------------


def test_sigma_excludes_format_source_commit_outline_digest():
    """`_outline_config_sigma` keeps topic/persona/voice/goals/source-subset/lexicon and DROPS
    format, source-commit, and outline-digest — the three that legitimately differ emit→drive."""
    preimage = {
        "dimensions": {
            "topic": {"entry": "x-architecture", "delta": {}},
            "persona": {"entry": "technical-evaluator", "delta": {}},
            "format": {"entry": "outline", "delta": {}},
            "voice": {"entry": "clear-explainer", "delta": {}},
        },
        "goals": [["explain", {}]],
        "source-subset": ["x-arch-src"],
        "source-commit": {"x-arch-src": "a" * 40},
        "outline-digest": "d" * 64,
        "lexicon": {"entry": "house-standard", "delta": {}},
    }
    sigma = session._outline_config_sigma(preimage)
    assert set(sigma["dimensions"]) == {"topic", "persona", "voice"}  # NO format
    assert "source-commit" not in sigma
    assert "outline-digest" not in sigma
    assert sigma["source-subset"] == ["x-arch-src"]  # source-subset IS compared
    assert sigma["goals"] == [["explain", {}]]
    assert sigma["lexicon"] == {"entry": "house-standard", "delta": {}}

    # a format-only difference projects to the SAME σ (no false alarm).
    drive_like = {
        **preimage,
        "dimensions": {
            **preimage["dimensions"],
            "format": {"entry": "short-opinion-post", "delta": {}},
        },
        "source-commit": {"x-arch-src": "b" * 40},
        "outline-digest": "e" * 64,
    }
    assert session._outline_config_sigma(preimage) == session._outline_config_sigma(drive_like)


# --- the CLI door: --from / --allow-drift flag threading + exit codes --------------------------
#
# The operator CLI emit uses the DEFAULT adapters (no mock injection seam), so these run in a
# NO-SOURCE workspace: the pool is [] on both sides, `σ.source-subset` matches trivially, and the
# guard's discriminator is `σ.persona` — enough to prove the flag threading + exit-code mapping.


def _cli_root(tmp_path: Path) -> Path:
    return build_root(tmp_path, sources=())  # no `sources/*.md` → empty pool, default adapters OK


def _write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _cli_emit(root: Path, draft: str) -> str:
    from pipeline import __main__ as cli

    return cli._cmd_outline(["emit", draft, "--recipe", RECIPE, "--topic", TOPIC_ID,
                             "--workspace", WS, "--user", USER, "--root", str(root)])


def _cli_generate(root: Path, edited: str, *extra: str) -> int:
    from pipeline import __main__ as cli

    return cli._cmd_generate(
        ["--outline", edited, "--recipe", RECIPE, "--topic", TOPIC_ID,
         "--workspace", WS, "--user", USER, "--root", str(root), *extra]
    )


def test_cli_outline_emit_prints_the_handle_and_drive_line(tmp_path, capsys):
    root = _cli_root(tmp_path)
    draft = _write(tmp_path, "draft.md", DRAFT)
    assert _cli_emit(root, draft) == 0
    out = capsys.readouterr().out
    handle = next(ln for ln in out.splitlines() if ln.startswith("handle")).split(":", 1)[1].strip()
    assert handle.startswith("a-")
    assert "— drive with:" in out
    assert f"--from {handle}" in out  # the copy-paste drive line carries the handle


def test_cli_generate_from_matching_config_is_exit_0(tmp_path, capsys):
    root = _cli_root(tmp_path)
    assert _cli_emit(root, _write(tmp_path, "draft.md", DRAFT)) == 0
    handle = next(
        ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("handle")
    ).split(":", 1)[1].strip()
    edited = _write(tmp_path, "edited.md", EDITED)
    assert _cli_generate(root, edited, "--from", handle) == 0  # σ match → free dry-run proceeds


def test_cli_generate_from_drifted_persona_is_exit_1(tmp_path, capsys):
    root = _cli_root(tmp_path)
    assert _cli_emit(root, _write(tmp_path, "draft.md", DRAFT)) == 0  # default persona
    handle = next(
        ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("handle")
    ).split(":", 1)[1].strip()
    edited = _write(tmp_path, "edited.md", EDITED)
    code = _cli_generate(root, edited, "--from", handle, "--persona", "product-manager")
    err = capsys.readouterr().err
    assert code == 1  # a pre-spend drift refusal
    assert "outline-config-drift" in err


def test_cli_generate_from_bogus_handle_is_exit_1(tmp_path, capsys):
    root = _cli_root(tmp_path)
    edited = _write(tmp_path, "edited.md", EDITED)
    code = _cli_generate(root, edited, "--from", "a-deadbeefdeadbeef")
    assert code == 1  # S-3 not-found refusal, pre-spend
    assert "not-found" in capsys.readouterr().err


def test_cli_generate_allow_drift_downgrades_to_exit_0(tmp_path, capsys):
    root = _cli_root(tmp_path)
    assert _cli_emit(root, _write(tmp_path, "draft.md", DRAFT)) == 0
    handle = next(
        ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("handle")
    ).split(":", 1)[1].strip()
    edited = _write(tmp_path, "edited.md", EDITED)
    code = _cli_generate(root, edited, "--from", handle, "--persona", "product-manager",
                         "--allow-drift")
    assert code == 0  # --allow-drift downgrades the block → the dry-run proceeds


# --- money-safety unchanged (§21.9) -----------------------------------------------------------


def test_invoke_begin_session_is_exit_3_and_render_fetch_only(tmp_path):
    """The C7 guard did not widen the shared automation door: `pipeline invoke begin-session` still
    reaches a CLI-UNWIRED verb → HandlerNotWired → exit 3, and the ONLY KNOWN verbs `main_cli`
    registers stay the safe stateless render + fetch-by-id."""
    root = build_root(tmp_path)
    code = invoke_mod.main_cli(
        ["begin-session", "--workspace", WS, "--user", USER, "--params-json", "{}",
         "--root", str(root)]
    )
    assert code == 3
    assert set(KNOWN_VERBS) & set(invoke_mod._VERB_HANDLERS) == {"render", "fetch-by-id"}
