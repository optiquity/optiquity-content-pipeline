"""Sources subsystem P2a: the driver HEAD-FREEZE (full N2 for a HEAD-mode cache config) + the
GAP-12 empty-`published` message split.

Two builds are covered:

- **The freeze (mechanism (a)).** A HEAD-mode cache connection (which a STATIC config MUST use —
  it cannot hardcode a per-acquisition digest) has no N2 on its own: `ground()` follows the live
  namespace HEAD, so a mid-session seal-AND-publish shifts what it reads. The driver closes this by
  FREEZING the plan-time pinned digest into the connection's `slice` selector (via the
  `SourceAdapter.freeze_connection` contract hook — connection-AUGMENTATION, the `ground` signature
  untouched) BEFORE grounding, so the drive reads the PINNED slice. Applied at BOTH pin→ground
  seams — `driver.run_thread` and the production `session._generate_next`. CF-1 is preserved
  (the frozen connection pins the SAME digest); graphify/folder/fsast keep the default NO-OP.
- **GAP-12.** `_run_artifact`'s empty-`published` block now splits into two loud typed messages:
  genuinely no EXTRACTED facts vs EXTRACTED facts ALL withheld by `reuse_rights` (leads only).

Content is SYNTHETIC-GENERIC (CLAUDE.md rule 4): invented widget/gadget claims, example.test
anchors. Everything runs under `tmp_path`; the real `users/` tree is never touched. The P1 sealing
helpers (`pipeline.sources.cache`) are reused verbatim.
"""

from __future__ import annotations

import ast
import datetime
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

import pipeline.api.session as session
from pipeline import driver
from pipeline.adapters import default_adapters
from pipeline.adapters.base import (
    TIER_AMBIGUOUS,
    TIER_EXTRACTED,
    TIER_INFERRED,
    AdapterError,
    Anchor,
    Fact,
)
from pipeline.adapters.folder import FolderAdapter
from pipeline.adapters.fsast import FsAstAdapter
from pipeline.adapters.graphify import GraphifyAdapter
from pipeline.adapters.mock import MockAdapter, synthetic_commit
from pipeline.api import invoke
from pipeline.api import token as token_mod
from pipeline.driver import DriverError
from pipeline.grounding import SourceInstance, ground_item
from pipeline.ids import (
    EntryBinding,
    build_artifact_preimage,
    mint_artifact_id,
)
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m3 import resolve_selection
from pipeline.plan import Plan, PlanItem
from pipeline.sources.cache import (
    namespace_dir,
    publish_head,
    read_head,
    seal_slice,
)
from pipeline.sources.reader import CacheReaderAdapter
from pipeline.spine import registry_for
from pipeline.ssot import Ssot
from pipeline.store import WorkspaceStore

NOW = datetime.date(2026, 7, 12)


def sample_facts() -> list[Fact]:
    """Slice A: two 'widget' facts + one 'gadget' fact (the P1 fixture set)."""
    return [
        Fact(
            subject="widget-service.timeout",
            claim="The widget service default timeout is 30 seconds.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("file-line", "src/widget/config.py:42"),),
            as_of=datetime.date(2026, 5, 1),
        ),
        Fact(
            subject="gadget-cache.capacity",
            claim="The gadget cache holds 512 entries.",
            tier=TIER_EXTRACTED,
            anchors=(Anchor("sha", "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"),),
            as_of=datetime.date(2026, 4, 20),
        ),
        Fact(
            subject="widget-service.retries",
            claim="The widget client retries failed calls three times.",
            tier=TIER_INFERRED,
            anchors=(),
            as_of=None,
        ),
    ]


def other_facts() -> list[Fact]:
    """Slice B: a DIFFERENT set — a single 'widget-service.protocol' fact (mid-session acquire)."""
    return [
        Fact(
            subject="widget-service.protocol",
            claim="The widget service speaks the example wire protocol v2.",
            tier=TIER_AMBIGUOUS,
            anchors=(Anchor("url-fragment", "https://example.test/spec#protocol"),),
            as_of=datetime.date(2026, 6, 1),
        ),
    ]


def make_ns(tmp_path, name: str = "x-widget") -> Path:
    """A bare cache-namespace directory under tmp_path (the reader binds a namespace by path)."""
    ns_dir = tmp_path / name
    ns_dir.mkdir(parents=True, exist_ok=True)
    return ns_dir


# ---------------------------------------------------------------------------
# The `freeze_connection` contract hook: default NO-OP; cache names its slice; CF-1 holds.
# ---------------------------------------------------------------------------


class TestFreezeConnectionContract:
    def test_default_is_a_noop_for_non_freezing_adapters(self):
        # graphify/folder/fsast read externally-stable snapshots — the default freeze returns the
        # connection UNCHANGED (SAME object), so no reserved key is injected into their CLOSED
        # keysets. Their `ground`/`pin_commit` therefore see EXACTLY the static connection.
        for adapter in (GraphifyAdapter(), FolderAdapter(), FsAstAdapter(), MockAdapter()):
            conn = {"path": "/some/where", "budget": 5}
            frozen = adapter.freeze_connection(conn, "deadbeefcafe0123")
            assert frozen is conn  # identity: no augmentation, no copy

    def test_cache_injects_the_slice_and_preserves_cf1(self, tmp_path):
        adapter = CacheReaderAdapter()
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest)
        head_conn = {"path": str(ns_dir)}  # HEAD mode — no `slice`

        pin = adapter.pin_commit(head_conn)
        assert pin == digest
        frozen = adapter.freeze_connection(head_conn, pin)
        # the pinned digest is now named as the slice selector
        assert frozen["slice"] == digest
        assert "path" in frozen
        # the ORIGINAL connection is not mutated (a NEW mapping is returned)
        assert "slice" not in head_conn
        # CF-1: pin over the frozen connection re-resolves the SAME digest, and ground reads it
        assert adapter.pin_commit(frozen) == digest
        assert adapter.ground(connection=frozen, query="widget").built_at_commit == digest

    def test_cache_freeze_is_idempotent_on_an_already_pinned_connection(self, tmp_path):
        adapter = CacheReaderAdapter()
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        pinned_conn = {"path": str(ns_dir), "slice": digest}
        frozen = adapter.freeze_connection(pinned_conn, digest)
        assert frozen["slice"] == digest  # already-pinned rides through to the same digest

    def test_cache_freeze_refuses_a_non_digest_pin_loud(self, tmp_path):
        adapter = CacheReaderAdapter()
        ns_dir = make_ns(tmp_path)
        with pytest.raises(AdapterError):
            adapter.freeze_connection({"path": str(ns_dir)}, "not-a-slice-digest")


# ---------------------------------------------------------------------------
# `driver._freeze_pool`: freezes cache HEAD instances; identity-neutral for the rest.
# ---------------------------------------------------------------------------


class TestFreezePool:
    def test_cache_head_instance_gets_its_slice_frozen(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        digest = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest)
        inst = SourceInstance(id="x-cache", adapter="cache", connection={"path": str(ns_dir)})
        frozen = driver._freeze_pool((inst,), default_adapters(), {"x-cache": digest})
        assert frozen[0].connection["slice"] == digest
        assert frozen[0].id == "x-cache"
        assert "slice" not in inst.connection  # the source instance is not mutated in place

    def test_non_cache_instance_is_identity_unchanged(self):
        # A pinned mock source: the freeze is a NO-OP, so the SAME frozen dataclass rides through
        # (no `replace`) — a graphify/folder/mock pool is byte-for-byte the same after freezing.
        inst = SourceInstance(id="m", adapter="mock", connection={"dataset": "alpha-docs"})
        frozen = driver._freeze_pool(
            (inst,), {"mock": MockAdapter()}, {"m": synthetic_commit("alpha-docs")}
        )
        assert frozen[0] is inst

    def test_commitless_source_rides_through_unchanged(self, tmp_path):
        # A HEAD-mode cache with nothing published pins None → not in source_commit → nothing to
        # freeze (the SM1 empty posture); the instance is returned unchanged.
        inst = SourceInstance(
            id="x-cache", adapter="cache", connection={"path": str(make_ns(tmp_path))}
        )
        frozen = driver._freeze_pool((inst,), default_adapters(), {})
        assert frozen[0] is inst


# ---------------------------------------------------------------------------
# The full N2 integration: pin → freeze → (mid-session advance) → drive reads the PLAN-TIME slice.
# ---------------------------------------------------------------------------


class TestDriverFreezeN2:
    def _pin(self, pool, adapters):
        """The driver's plan-time pin loop (`run_thread`): build the §7.2 commit-map."""
        source_commit: dict[str, str] = {}
        for inst in pool:
            commit = driver._pin_source_commit(adapters.get(inst.adapter), inst.connection)
            if commit is not None:
                source_commit[inst.id] = commit
        return source_commit

    def test_head_mode_cache_freeze_holds_across_a_midsession_publish(self, tmp_path):
        ns_dir = make_ns(tmp_path)
        adapters = default_adapters()
        # -- acquire slice A + publish it as HEAD (the plan-time state)
        digest_a = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest_a)
        # a STATIC config binds the cache in HEAD mode (NO `slice` — it cannot hardcode a digest)
        inst = SourceInstance(id="x-cache", adapter="cache", connection={"path": str(ns_dir)})
        pool = (inst,)

        # -- PLAN: pin the commit-map, then FREEZE the pool (mechanism (a))
        source_commit = self._pin(pool, adapters)
        assert source_commit == {"x-cache": digest_a}
        frozen_pool = driver._freeze_pool(pool, adapters, source_commit)

        # -- MID-SESSION: an out-of-band acquire seals slice B AND advances HEAD to it
        digest_b = seal_slice(ns_dir, other_facts())
        assert digest_b != digest_a
        publish_head(ns_dir, digest_b)
        assert read_head(ns_dir) == digest_b  # HEAD really moved

        # -- DRIVE: ground the FROZEN pool — it reads the PLAN-TIME slice A, not the live HEAD B
        outcome = ground_item(
            item="item-1",
            query="widget",
            pool=frozen_pool,
            selection=resolve_selection(),
            adapters=adapters,
            now=NOW,
        )
        assert dict(outcome.commit_map) == {"x-cache": digest_a}  # frozen to the plan-time head
        subjects = {f.subject for f in outcome.facts}
        assert subjects == {"widget-service.timeout", "widget-service.retries"}  # slice A facts
        assert "widget-service.protocol" not in subjects  # NOT slice B
        # the §7.2 commit-map the freeze read is itself untouched (identity is stable)
        assert source_commit == {"x-cache": digest_a}

    def test_without_the_freeze_head_mode_follows_the_advance(self, tmp_path):
        # The CONTRAST that proves the freeze is load-bearing: the SAME HEAD-mode connection,
        # grounded UNFROZEN after the advance, follows HEAD to slice B (the documented boundary).
        ns_dir = make_ns(tmp_path)
        adapters = default_adapters()
        digest_a = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest_a)
        inst = SourceInstance(id="x-cache", adapter="cache", connection={"path": str(ns_dir)})

        digest_b = seal_slice(ns_dir, other_facts())
        publish_head(ns_dir, digest_b)

        outcome = ground_item(
            item="item-1",
            query="widget",
            pool=(inst,),  # UNFROZEN
            selection=resolve_selection(),
            adapters=adapters,
            now=NOW,
        )
        assert dict(outcome.commit_map) == {"x-cache": digest_b}  # followed the live HEAD


# ---------------------------------------------------------------------------
# No disturbance: a graphify/folder/mock source pins + grounds IDENTICALLY through the freeze.
# ---------------------------------------------------------------------------


class TestNoDisturbance:
    def test_mock_source_pins_and_grounds_identically_after_freeze(self):
        adapters = {"mock": MockAdapter()}
        inst = SourceInstance(id="m", adapter="mock", connection={"dataset": "alpha-docs"})

        commit = driver._pin_source_commit(adapters["mock"], inst.connection)
        before = ground_item(
            item="i", query="widget", pool=(inst,), selection=resolve_selection(),
            adapters=adapters, now=NOW,
        )
        frozen = driver._freeze_pool((inst,), adapters, {"m": commit})
        after = ground_item(
            item="i", query="widget", pool=frozen, selection=resolve_selection(),
            adapters=adapters, now=NOW,
        )
        # the injection is a pure no-op for a non-cache adapter: same instance, same facts + commits
        assert frozen[0] is inst
        assert "slice" not in frozen[0].connection
        assert after.facts == before.facts
        assert dict(after.commit_map) == dict(before.commit_map)


# ---------------------------------------------------------------------------
# GAP-12: the empty-`published` block splits into two loud, typed, distinct messages.
# ---------------------------------------------------------------------------


class TestGap12PublishedSplit:
    """`_run_artifact` raises BEFORE compose when `published` is empty. Post-P0 that has TWO
    causes; the driver now names the right axis for each. Grounding is monkeypatched (no live
    call); the raise fires at the publish gate, well before `resolve_compose`."""

    def _harness(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        store.ensure_layout()
        claims = registry_for(store)
        ssot = Ssot(store.root / "ssot.csv")
        preimage = build_artifact_preimage(
            topic=EntryBinding("t"),
            persona=EntryBinding("p"),
            format=EntryBinding("f"),
            voice=EntryBinding("v"),
            goals=[],
            source_subset=["s"],
            source_commit={"s": "c0ffee0123ab"},
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
            outline_digest=None,
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

    def _run(self, store, claims, ssot, plan, item):
        return driver._run_artifact(
            env=SimpleNamespace(workspace="ws"),
            store=store,
            claims=claims,
            ssot=ssot,
            plan=plan,
            item=item,
            pool=(),
            adapters={},
            source_repos={"s": "repo"},
            now=NOW,
            model=None,
            log=lambda _m: None,
        )

    def _patch_ground(self, monkeypatch, *, publishable, facts):
        monkeypatch.setattr(
            driver,
            "ground_item",
            lambda **kw: SimpleNamespace(
                status="ok", publishable_facts=publishable, facts=facts, commit_map={}
            ),
        )
        # compose must never run — the raise precedes it; assert loudly if it does.
        monkeypatch.setattr(
            driver, "compose_artifact",
            lambda *a, **k: pytest.fail("compose must not run when `published` is empty"),
        )

    def test_rights_withheld_names_the_reuse_rights_axis(self, tmp_path, monkeypatch):
        store, claims, ssot, plan, item = self._harness(tmp_path)
        # EXTRACTED facts EXIST (publishable non-empty) but ALL are non-republishable (rights).
        held = SimpleNamespace(republishable=False)
        self._patch_ground(monkeypatch, publishable=(held, held), facts=(held, held))
        with pytest.raises(DriverError, match="WITHHELD BY reuse_rights") as exc:
            self._run(store, claims, ssot, plan, item)
        msg = str(exc.value)
        assert "reuse_rights" in msg
        assert "leads only" in msg
        assert "no publishable (EXTRACTED) facts" not in msg  # the WRONG axis is not named

    def test_no_extracted_facts_keeps_the_original_message(self, tmp_path, monkeypatch):
        store, claims, ssot, plan, item = self._harness(tmp_path)
        # genuinely no EXTRACTED fact survived: publishable_facts is empty.
        lead = SimpleNamespace(republishable=False)
        self._patch_ground(monkeypatch, publishable=(), facts=(lead,))
        with pytest.raises(DriverError, match=r"no publishable \(EXTRACTED\) facts") as exc:
            self._run(store, claims, ssot, plan, item)
        assert "reuse_rights" not in str(exc.value)  # never points at the rights config

    def test_the_two_messages_are_distinct(self, tmp_path, monkeypatch):
        store, claims, ssot, plan, item = self._harness(tmp_path)
        held = SimpleNamespace(republishable=False)
        self._patch_ground(monkeypatch, publishable=(held,), facts=(held,))
        with pytest.raises(DriverError) as rights:
            self._run(store, claims, ssot, plan, item)
        self._patch_ground(monkeypatch, publishable=(), facts=(held,))
        with pytest.raises(DriverError) as tiers:
            self._run(store, claims, ssot, plan, item)
        assert str(rights.value) != str(tiers.value)  # distinct diagnostics


# ---------------------------------------------------------------------------
# The PRODUCTION seam: `session._generate_next` freezes the pool it drives (the real invoke path).
# ---------------------------------------------------------------------------


class _CapturingRun:
    """The injected per-item generation seam: records the `pool` it is driven with (so the test
    can inspect the FROZEN drive connection), materializes the artifact-id, returns a minimal
    outcome — never a live compose/render call."""

    def __init__(self) -> None:
        self.pools: list = []

    def __call__(self, *, store, item, **kwargs):
        self.pools.append(kwargs.get("pool"))
        store.output_path(item.artifact_id).write_bytes(b"{}\n")
        return SimpleNamespace(artifact_id=item.artifact_id, deliverables=())


class TestSessionProductionFreeze:
    WS = "testws"
    USER = "acme"
    L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
    TOPIC = (
        "---\nid: x-t-alpha\nprovenance: instance\nschema_version: 1\n"
        "why: First.\n---\n\nBody.\n"
    )

    def _build_root(self, tmp_path: Path) -> Path:
        repo_root = Path(__file__).resolve().parents[1]
        root = tmp_path / "root"
        root.mkdir(parents=True)
        for reg in REGISTRY_ROOTS:
            src = registry_dir(repo_root, reg)
            if src.is_dir():
                dst = registry_dir(root, reg)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src, dst)
        (root / "instance").mkdir()
        (root / "instance" / "defaults.yaml").write_text(self.L2, encoding="utf-8")
        ws_dir = root / "users" / self.USER / "workspaces" / self.WS
        (ws_dir / "topics").mkdir(parents=True)
        (ws_dir / "topics" / "x-t-alpha.md").write_text(self.TOPIC, encoding="utf-8")
        return root

    def _write_cache_source(self, root: Path, ns_dir: Path) -> None:
        sources_dir = root / "users" / self.USER / "workspaces" / self.WS / "sources"
        sources_dir.mkdir(parents=True, exist_ok=True)
        (sources_dir / "x-cache-src.md").write_text(
            "---\nid: x-cache-src\nprovenance: instance\nschema_version: 1\n"
            f"adapter: cache\nconnection:\n  path: {ns_dir}\n"
            "content_kind: general\n---\n\nA HEAD-mode cache source (synthetic).\n",
            encoding="utf-8",
        )

    def _handlers(self, run):
        return {
            "begin-session": session.begin_session_handler(),
            "continue-session": session.continue_session_handler(run_artifact=run),
        }

    def test_generate_next_freezes_the_head_mode_cache_to_the_plan_time_slice(self, tmp_path):
        root = self._build_root(tmp_path)
        store = WorkspaceStore.at(root, self.USER, self.WS)
        ns_dir = namespace_dir(store, "x-widget")
        self._write_cache_source(root, ns_dir)

        # -- acquire slice A + publish it as HEAD (the plan-time state), then begin the session
        digest_a = seal_slice(ns_dir, sample_facts())
        publish_head(ns_dir, digest_a)
        run = _CapturingRun()
        hs = self._handlers(run)
        params = {"recipe": "explainer-post", "topics": ["x-t-alpha"], "platforms": ["github"]}
        begun = invoke.invoke(
            "begin-session", self.WS, self.USER, params, store=store, root=str(root), handlers=hs
        )
        assert begun["envelope"]["ok"] is True
        token = begun["token"]
        # the plan-time pin captured slice A as the source commit
        decoded = token_mod.decode(token, expected_workspace=self.WS)
        assert decoded.inputs["source_commit"] == {"x-cache-src": digest_a}

        # -- MID-SESSION: an out-of-band acquire seals slice B AND advances HEAD
        digest_b = seal_slice(ns_dir, other_facts())
        publish_head(ns_dir, digest_b)
        assert read_head(ns_dir) == digest_b

        # -- generate-next: the pool the driver grounds must be FROZEN to slice A, not live HEAD B
        out = invoke.invoke(
            "continue-session", self.WS, self.USER, {"action": "generate-next"},
            token=token, store=store, root=str(root), handlers=hs,
        )
        assert out["envelope"]["ok"] is True
        assert run.pools, "generate-next must have driven at least one artifact"
        cache_inst = next(i for i in run.pools[0] if i.adapter == "cache")
        assert cache_inst.connection.get("slice") == digest_a  # frozen to the plan-time slice
        assert cache_inst.connection["slice"] != digest_b  # NOT the mid-session advance


# ---------------------------------------------------------------------------
# Wiring guard: both pin→ground seams call the freeze (source-level pin, ast — never regresses).
# ---------------------------------------------------------------------------


class TestFreezeIsWiredAtBothSeams:
    def _fn(self, module, name):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        return next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        )

    def _calls_freeze_pool(self, fn) -> bool:
        # accept both the bare in-module call (`_freeze_pool(...)`, driver.run_thread) and the
        # cross-module call (`driver._freeze_pool(...)`, session._generate_next)
        for n in ast.walk(fn):
            if not isinstance(n, ast.Call):
                continue
            func = n.func
            if isinstance(func, ast.Attribute) and func.attr == "_freeze_pool":
                return True
            if isinstance(func, ast.Name) and func.id == "_freeze_pool":
                return True
        return False

    def test_run_thread_freezes_the_pool(self):
        assert self._calls_freeze_pool(self._fn(driver, "run_thread"))

    def test_generate_next_freezes_the_pool(self):
        # the PRODUCTION invoke/generate-next drive seam must freeze too, else HEAD-mode N2 leaks
        assert self._calls_freeze_pool(self._fn(session, "_generate_next"))
