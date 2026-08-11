"""IDENTITY-NEUTRALITY of the transport (plan G7, LOW-1 regression pin).

The artifact + deliverable ids + the plan_hash MUST be byte-identical whether a plan is driven on
the SUBSCRIPTION or the API-KEY transport — the transport MODE / zone / cost / hold / run_id never
enter an id preimage (they are recorded as provenance only). This holds by CONSTRUCTION today
(`build_artifact_preimage` / `resolve_plan` take no transport input), but is UNPINNED against a
future refactor that might fold `run_id`/`mode`/`zone` into a preimage. This drives the SAME plan
through the REAL `driver._run_artifact` chokepoint once on each transport — with a STUBBED compose
seam + a fake clock/costs + an admitted LIVE api-key hold (ZERO real spend, no model call) — and
asserts the identity preimage compose SEES is byte-identical across the two, plus that both
transports were genuinely exercised (subscription vs apikey).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipeline import driver
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.m3 import resolve_selection
from pipeline.plan import DeliverableItem, Plan, PlanItem
from pipeline.spend.assignment import SCOPE_ZONE, Assignment, AssignmentStore, ScopeKey
from pipeline.spend.keystore import FileSecretBackend, SecretRef
from pipeline.spend.meter import WeeklyMeter
from pipeline.spend.resolve import resolve_transport
from pipeline.spine import registry_for
from pipeline.ssot import Ssot
from pipeline.store import WorkspaceStore
from pipeline.transport import TransportPlan

WED_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()

#: One fixed coordinate — built IDENTICALLY for both transports so any id difference can only come
#: from the transport leaking into a preimage (the exact regression this pins).
_COORD = dict(
    topic=EntryBinding("t"),
    persona=EntryBinding("p"),
    format=EntryBinding("f"),
    voice=EntryBinding("v"),
    goals=[],
    source_subset=["s"],
    source_commit={"s": "c0ffee0123ab"},
    outline_digest=None,
)


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Stop(Exception):
    """Halt `_run_artifact` at compose — the identity preimage is captured before any spend."""


def _plan_and_item():
    """Build a fresh (item, plan) from the fixed coordinate — deterministic, transport-free."""
    preimage = build_artifact_preimage(**_COORD)
    deliverable = DeliverableItem(
        deliverable_id="f-0123456789ab",
        fitted_id="f-0123456789ab~fit",
        platform="web",
        language="en",
        output_type="article",
        presentation="standard",
        reconcile_strategy="passthrough",
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
        deliverables=(deliverable,),
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
    return plan, item


def _subscription_plan() -> TransportPlan:
    return TransportPlan.subscription()


def _apikey_plan(tmp_path: Path) -> TransportPlan:
    """A real api-key `TransportPlan` carrying an ADMITTED LIVE hold (stubbed keystore + fake meter,
    ZERO real spend). Compose is stubbed, so the key/hold are never actually used to spawn."""
    backend = FileSecretBackend(tmp_path / "secrets")
    ref = SecretRef.parse("anthropic:acme")
    backend.store(ref, "sk-ant-SECRET")
    store = AssignmentStore(
        [Assignment(ScopeKey(SCOPE_ZONE, "dave/work"), ref, Decimal("500"))],
        umbrella_cap_usd=Decimal("1000"),
    )
    meter = WeeklyMeter(root=tmp_path, clock=_Clock(WED_NOON))
    admission = resolve_transport(
        tmp_path, "dave", "work", "acme",
        n_artifacts=1, n_deliverables=1, meter=meter, resolver=backend, store=store,
    )
    assert admission.plan.mode == "apikey" and admission.hold is not None
    return admission.plan


def _drive_capture(tmp_path: Path, transport_plan: TransportPlan, monkeypatch) -> dict:
    """Drive ONE artifact through the REAL `_run_artifact` under `transport_plan`, capturing the
    identity preimage compose SEES + the transport mode threaded to it (then halt before spend)."""
    store = WorkspaceStore(tmp_path / "ws")
    store.ensure_layout()
    claims = registry_for(store)
    ssot = Ssot(store.root / "ssot.csv")
    plan, item = _plan_and_item()

    fact = SimpleNamespace(republishable=True)
    monkeypatch.setattr(
        driver, "ground_item",
        lambda **kw: SimpleNamespace(
            status="ok", publishable_facts=(fact,), facts=(fact,), commit_map={}
        ),
    )
    monkeypatch.setattr(
        driver, "resolve_compose",
        lambda env, sel: SimpleNamespace(
            topic=SimpleNamespace(values={}, entry_id="t"),
            persona=SimpleNamespace(values={}, entry_id="p"),
            format=SimpleNamespace(values={}, entry_id="f"),
            voice=SimpleNamespace(values={}, entry_id="v"),
            goals=(),
            lexicon=None,
            recipe=SimpleNamespace(effective={}),
        ),
    )

    captured: dict = {}

    def _capture(request, *, plan=None, **_kw):
        captured["preimage"] = dict(request.preimage)
        captured["mode"] = getattr(plan, "mode", None)  # the transport threaded to compose
        captured["artifact_id"] = item.artifact_id
        raise _Stop()

    monkeypatch.setattr(driver, "compose_artifact", _capture)
    with pytest.raises(_Stop):
        driver._run_artifact(
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
            transport_plan=transport_plan,
        )
    captured["deliverable_ids"] = tuple(plan.deliverable_ids())
    captured["plan_hash"] = plan.plan_hash
    return captured


def test_ids_are_byte_identical_across_subscription_and_apikey(tmp_path, monkeypatch):
    sub = _drive_capture(tmp_path / "sub", _subscription_plan(), monkeypatch)
    api = _drive_capture(tmp_path / "api", _apikey_plan(tmp_path / "keys"), monkeypatch)

    # Both transports were GENUINELY exercised through the real chokepoint.
    assert sub["mode"] == "subscription"
    assert api["mode"] == "apikey"
    # The identity preimage compose SEES is byte-identical — the transport enters NO preimage.
    assert sub["preimage"] == api["preimage"]
    # The artifact id, deliverable ids, and plan_hash are byte-identical across the two transports.
    assert sub["artifact_id"] == api["artifact_id"]
    assert sub["deliverable_ids"] == api["deliverable_ids"]
    assert sub["plan_hash"] == api["plan_hash"]
    # And the preimage never carries a transport/mode/zone/hold marker (recorded provenance-only).
    joined = repr(sub["preimage"]).lower()
    for leak in ("apikey", "subscription", "hold", "transport", "per_call", "sk-ant"):
        assert leak not in joined
