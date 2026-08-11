"""The pre-spend COST DISCLOSURE line (plan G8) — mode / bucket / ceiling / headroom, NO spend.

Proves the money-safety disclosure with a STUBBED paid seam (a fake `Runner` + a fake `Clock` +
fake costs) + a tmp keystore OUTSIDE the repo tree — ZERO real spend, no model call, no network:

- a DRY-RUN/preview of an api-key-resolving run discloses the ceiling + headroom and admits NOTHING
  (no hold written, week-to-date stays $0 — it spends nothing and touches no secret);
- a PAID `generate-next` run prints the disclosure header to stderr BEFORE the first spawn;
- the disclosed ceiling is ALWAYS ≥ the actual (it is the construction worst-case × attempts, S-5);
- the SUBSCRIPTION path discloses `mode=subscription` with NO `$` ceiling (flat-rate);
- the disclosure shows the non-secret HANDLE, NEVER the secret value (I5).
"""

from __future__ import annotations

import io
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

# The shared full-root + friendly-CLI helpers (the established sibling-import idiom, e.g.
# `test_normalize` / `test_parallel_plan`): USER=acme, WS=testws, zone=default.
from test_cli_generate import USER, base_argv, build_root

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline.spend.assignment import (
    SCOPE_ZONE,
    Assignment,
    AssignmentStore,
    ScopeKey,
    save_store,
)
from pipeline.spend.construction import (
    COMPOSE_MAX_ATTEMPTS,
    RECONCILE_MAX_ATTEMPTS,
    REVIEW_MAX_ATTEMPTS,
)
from pipeline.spend.keystore import FileSecretBackend, SecretRef
from pipeline.spend.meter import WeeklyMeter
from pipeline.spend.resolve import preview_transport, resolve_transport
from pipeline.transport import ProcessOutcome, invoke_headless

#: A recognizable mid-week epoch (Wednesday noon UTC).
WED_NOON = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()

#: A recognizable secret token — a leak into the disclosure line would be obvious.
SECRET = "sk-ant-SECRET-must-never-appear-in-a-disclosure"

#: The handle assigned in these tests (a NON-secret keystore reference).
HANDLE = "anthropic:acme"


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class _RecordingRunner:
    """A STUBBED paid seam: a fake ok result with a fake cost — never spawns, never spends."""

    def __init__(self, cost: float) -> None:
        self.cost = cost

    def __call__(self, _request) -> ProcessOutcome:
        import json

        stdout = json.dumps(
            {"type": "result", "is_error": False, "subtype": "success",
             "result": "stub", "total_cost_usd": self.cost}
        )
        return ProcessOutcome(timed_out=False, returncode=0, stdout=stdout, stderr="")


def _apikey_setup(
    tmp_path: Path, *, bucket_cap: str = "100", umbrella: str = "200"
) -> tuple[FileSecretBackend, SecretRef, ScopeKey, AssignmentStore, _Clock, WeeklyMeter]:
    """Store the secret in a tmp keystore OUTSIDE the repo, assign the handle at zone `dave/work`,
    build a fake-clock meter — the `test_apikey_transport` injection shape."""
    backend = FileSecretBackend(tmp_path / "secrets")
    ref = SecretRef.parse(HANDLE)
    backend.store(ref, SECRET)
    scope = ScopeKey(SCOPE_ZONE, "dave/work")
    store = AssignmentStore(
        [Assignment(scope, ref, Decimal(bucket_cap))], umbrella_cap_usd=Decimal(umbrella)
    )
    meter = WeeklyMeter(root=tmp_path, clock=_Clock(WED_NOON))
    return backend, ref, scope, store, _Clock(WED_NOON), meter


def _admit(tmp_path, backend, store, meter, *, n_artifacts=1, n_deliverables=1, override=None):
    return resolve_transport(
        tmp_path, "dave", "work", "acme",
        override=override, n_artifacts=n_artifacts, n_deliverables=n_deliverables,
        meter=meter, resolver=backend, store=store,
    )


# ---------------------------------------------------------------------------------------
# The api-key disclosure: mode / bucket / worst-case ceiling / live headroom
# ---------------------------------------------------------------------------------------


def test_apikey_disclosure_names_mode_bucket_ceiling_and_headroom(tmp_path: Path) -> None:
    backend, ref, _scope, store, _clock, meter = _apikey_setup(tmp_path)
    admission = _admit(tmp_path, backend, store, meter)  # 1 artifact / 1 deliverable → 12 calls
    line = admission.disclose().line()

    assert line.startswith("cost-disclosure: mode=api-key ")
    assert HANDLE in line                       # the NON-secret handle names the transport
    assert "bucket=zone:dave/work" in line      # the exact charged bucket (§23 identity)
    assert "construction-scope: ≤ $60.00" in line  # $5 × 12 worst-case calls
    assert "(≤ 12 calls)" in line
    # After admit the live hold ($60) rides the week-to-date, so the headroom already reflects it.
    assert "headroom: bucket $40.00 of $100.00 / umbrella $140.00 of $200.00" in line


def test_disclosed_ceiling_is_always_ge_the_actual_spend(tmp_path: Path) -> None:
    backend, _ref, _scope, store, clock, meter = _apikey_setup(tmp_path)
    admission = _admit(tmp_path, backend, store, meter, n_artifacts=1, n_deliverables=1)
    budget = admission.disclose().budget

    # The ceiling carries the ×attempts multiplier at EVERY stage (writer + Review-1 per artifact,
    # reconcile + Review-2 per deliverable) — never a bare ×1 (S-5).
    expected_calls = 1 * (COMPOSE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS) + 1 * (
        RECONCILE_MAX_ATTEMPTS + REVIEW_MAX_ATTEMPTS
    )
    assert budget.total_call_budget == expected_calls == 12
    assert budget.ceiling_usd == 5.0 * expected_calls  # $60.00, the disclosed `≤ $C`

    # Drive the stubbed paid seam a few times UNDER the forced $5 per-call cap; the accumulated
    # ACTUAL is far below the disclosed ceiling — the disclosure never understates.
    for _ in range(3):
        invoke_headless("p", plan=admission.plan, runner=_RecordingRunner(4.99), clock=clock)
    actual = admission.plan.cost_accumulator.total
    assert actual == pytest.approx(14.97)
    assert budget.ceiling_usd >= actual


def test_disclosure_shows_the_handle_never_the_secret_value(tmp_path: Path) -> None:
    backend, _ref, _scope, store, _clock, meter = _apikey_setup(tmp_path)
    admission = _admit(tmp_path, backend, store, meter)
    line = admission.disclose().line()
    assert HANDLE in line          # discloses the handle reference
    assert SECRET not in line      # NEVER the resolved secret value (I5)


# ---------------------------------------------------------------------------------------
# The subscription disclosure: flat-rate mode, NO dollar ceiling
# ---------------------------------------------------------------------------------------


def test_subscription_disclosure_has_no_dollar_ceiling(tmp_path: Path) -> None:
    # No key assigned; the entitled user IS dave → the flat-rate subscription (per_call_cap=None).
    store = AssignmentStore(entitled_user="dave")
    meter = WeeklyMeter(root=tmp_path, clock=_Clock(WED_NOON))
    admission = resolve_transport(tmp_path, "dave", "work", "acme", meter=meter, store=store)

    assert admission.plan.mode == "subscription"
    line = admission.disclose().line()
    assert line.startswith("cost-disclosure: mode=subscription")
    assert "flat-rate" in line
    assert "≤ $" not in line     # no finite dollar ceiling on the flat-rate path (S-1)
    assert "headroom" not in line  # subscription is not metered here — nothing to bound


# ---------------------------------------------------------------------------------------
# The DRY-RUN / preview path: discloses ceiling + headroom, admits NOTHING (spends nothing)
# ---------------------------------------------------------------------------------------


def test_dry_run_discloses_ceiling_and_headroom_without_admitting(tmp_path: Path) -> None:
    backend, ref, scope, store, _clock, meter = _apikey_setup(tmp_path)
    # A dry-run resolves the DECISION + reads headroom — it never resolves the secret, so it takes
    # NO resolver (backend) at all: proof there is no paid seam to build.
    disclosure = preview_transport(
        tmp_path, "dave", "work", "acme", n_artifacts=1, n_deliverables=1, meter=meter, store=store
    )
    line = disclosure.line()
    assert line.startswith("cost-disclosure: mode=api-key ")
    assert "construction-scope: ≤ $60.00" in line
    # No admit → week-to-date is still $0, so the disclosed headroom is the FULL cap.
    assert "headroom: bucket $100.00 of $100.00 / umbrella $200.00 of $200.00" in line

    # THE money-safety guarantee: the dry-run admitted NOTHING and spent NOTHING.
    assert meter.bucket_week_to_date(scope, ref) == Decimal("0")  # no hold reserved
    assert meter.umbrella_week_to_date() == Decimal("0")
    holds_root = tmp_path / "instance" / "ops" / "spend"
    spend_files = list(holds_root.rglob("*")) if holds_root.exists() else []
    # The ONLY artifact a read-only headroom read may leave is the empty admission LOCK — never a
    # HOLD file and never a SETTLED ledger line (a dry-run reserves nothing, settles nothing).
    written = [p for p in spend_files if p.is_file() and p.name != ".admit.lock"]
    assert written == []
    _ = backend  # the resolver is unused by a dry-run (no secret touched)


def test_dry_run_subscription_discloses_flat_rate_without_metering(tmp_path: Path) -> None:
    store = AssignmentStore(entitled_user="dave")
    disclosure = preview_transport(
        tmp_path, "dave", "work", "acme", n_artifacts=1, n_deliverables=1, store=store
    )
    line = disclosure.line()
    assert line.startswith("cost-disclosure: mode=subscription")
    assert "≤ $" not in line


# ---------------------------------------------------------------------------------------
# The PAID session path: the disclosure header prints BEFORE the first spawn (real drive)
# ---------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the invoke dispatch registry so the CLI drive stays hermetic."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


class _SpawnRecorder:
    """The injected per-item generation seam: on its FIRST call it SNAPSHOTS the disclosure stream
    (so a 'disclosed before the first spawn' assertion is exact), then materializes the id."""

    def __init__(self, stream: io.StringIO) -> None:
        self.calls: list[str] = []
        self._stream = stream
        self.stderr_at_first_spawn: str | None = None

    def __call__(self, *, store, item, **_kwargs):
        from types import SimpleNamespace

        if not self.calls:
            self.stderr_at_first_spawn = self._stream.getvalue()
        self.calls.append(item.artifact_id)
        store.output_path(item.artifact_id).write_bytes(b"{}\n")
        deliverables = tuple(
            SimpleNamespace(deliverable_id=d.deliverable_id) for d in item.deliverables
        )
        return SimpleNamespace(artifact_id=item.artifact_id, deliverables=deliverables)


def test_paid_generate_next_discloses_before_the_first_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = build_root(tmp_path)
    # Enforce the api-key transport: a tmp keystore (env-resolved, OUTSIDE the repo) + a config
    # assigning the handle at the acme/default zone the plan spends in.
    secrets_dir = tmp_path / "secrets"
    monkeypatch.setenv("OPTIQUITY_SECRETS_DIR", str(secrets_dir))
    ref = SecretRef.parse(HANDLE)
    FileSecretBackend().store(ref, SECRET)
    store = AssignmentStore(
        [Assignment(ScopeKey(SCOPE_ZONE, f"{USER}/default"), ref, Decimal("500"))],
        umbrella_cap_usd=Decimal("1000"),
    )
    save_store(store, root)

    # Redirect the money-safety disclosure stream and snapshot it at the first spawn.
    stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", stderr)
    recorder = _SpawnRecorder(stderr)
    code = cli._cmd_generate(base_argv(root, "--go"), run_artifact=recorder)

    assert code == 0
    assert recorder.calls  # at least one artifact was driven (a real spawn happened)
    snapshot = recorder.stderr_at_first_spawn
    assert snapshot is not None
    # The disclosure header was on the stream BEFORE the first spawn — and names the api-key mode
    # + the non-secret handle, never the secret value.
    assert "cost-disclosure: mode=api-key" in snapshot
    assert HANDLE in snapshot
    assert SECRET not in snapshot
