"""UNIFORM S4 at the SHARED chokepoint (plan G7 / B-1): the zone-required refusal fires for BOTH
the CLI and the served `generate-next`/`render` re-entry — not just the CLI (the B-1 hole).

The B-1 finding: the served HTTP doors default `zone` silently and DODGED the CLI-only S4 guard, so
>1-zone user's served spend would charge the wrong bucket. G7 moves the "name a zone or refuse" rule
INTO the shared `invoke()` spend path, threaded by a zone-provenance signal (explicit vs defaulted)
from BOTH doors through `jobrunner`/`JobSpec`. This drives the REAL `invoke()` (never a synthetic
S4 stub) directly AND through the REAL detached `jobrunner.run_job` re-entry, with a STUBBED paid
seam (no handler ever spends), and proves:

- a >1-zone user's SPEND call (`generate-next`, `render`) with a DEFAULTED zone → whole-invocation
  `zone-required` refusal at `invoke()`;
- an EXPLICIT zone is honored (no refusal); a Tier-A verb NEVER refuses (S2, never spends);
- the REAL `jobrunner.run_job` re-entry (the served door's detached runner) hits the SAME refusal;
- the `JobSpec` carries the zone-provenance + transport override across the process boundary.
"""

from __future__ import annotations

from pathlib import Path

from pipeline.api import invoke as invoke_mod
from pipeline.api import jobrunner
from pipeline.api.http_shim import _ShimRequestHandler
from pipeline.jobs import JobStore, job_key
from pipeline.telemetry import PresenceRegistry

USER = "dave"
WS = "acme"
#: A valid artifact id to build a real run-family job key from (the runner records terminals against
#: this key, and `JobStore` parses it as an id — a bare 'k-…' string is not a valid key).
_A = "a-9f3c07d21b44e8aa"


def _make_multizone_user(root: Path) -> None:
    """Give `dave` MORE THAN ONE zone (the S4 trigger): two zone dirs under his namespace."""
    for zone in ("work", "personal", "default"):
        (root / "users" / USER / "zones" / zone / "workspaces").mkdir(parents=True, exist_ok=True)


def _stub_handler(_ctx):
    """A STUBBED paid seam: dispatch reaches here ONLY when S4 did NOT refuse — it spends nothing
    (returns an empty result set), so a 'not refused' assertion never makes a real call."""
    return ([], None)


def _invoke(root: Path, verb: str, params: dict, *, zone_explicit: bool):
    return invoke_mod.invoke(
        verb,
        WS,
        USER,
        params,
        root=str(root),
        zone="default",
        zone_explicit=zone_explicit,
        handlers={verb: _stub_handler},
    )


# ---------------------------------------------------------------------------------------
# The refusal fires at the SHARED invoke() for a defaulted-zone spend call
# ---------------------------------------------------------------------------------------


def test_generate_next_defaulted_zone_multizone_user_is_refused(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    out = _invoke(tmp_path, "continue-session", {"action": "generate-next"}, zone_explicit=False)
    assert out["envelope"]["ok"] is False
    assert out["envelope"]["code"] == "zone-required"


def test_render_defaulted_zone_multizone_user_is_refused(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    out = _invoke(tmp_path, "render", {}, zone_explicit=False)
    assert out["envelope"]["ok"] is False
    assert out["envelope"]["code"] == "zone-required"


def test_explicit_zone_is_honored_no_refusal(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    # zone_explicit=True (the caller NAMED it) → S4 does NOT refuse → dispatch to the stub → ok.
    out = _invoke(tmp_path, "continue-session", {"action": "generate-next"}, zone_explicit=True)
    assert out["envelope"]["ok"] is True


def test_tier_a_verb_never_refuses_even_multizone_defaulted(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    # begin-session {generate=none} is Tier-A — it never spends, so S4 never fires (S2 preserved).
    out = _invoke(tmp_path, "begin-session", {"generate": "none"}, zone_explicit=False)
    assert out["envelope"]["ok"] is True


def test_single_zone_user_defaulted_zone_is_not_refused(tmp_path: Path) -> None:
    # One zone only → the friendly `default` is materialized, NO refusal (0/1 zone never raises).
    (tmp_path / "users" / USER / "zones" / "default" / "workspaces").mkdir(parents=True)
    out = _invoke(tmp_path, "continue-session", {"action": "generate-next"}, zone_explicit=False)
    assert out["envelope"]["ok"] is True


# ---------------------------------------------------------------------------------------
# The REAL served re-entry: jobrunner.run_job → invoke() → the SAME refusal (not a synthetic stub)
# ---------------------------------------------------------------------------------------


def test_served_generate_next_reentry_hits_the_same_s4_refusal(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    spec = jobrunner.JobSpec(
        key=job_key((_A,), "idem-s4"),
        verb="continue-session",
        workspace=WS,
        user=USER,
        zone="default",
        params={"action": "generate-next"},
        idempotency_key="idem-s4",
        root=str(tmp_path),
        token=None,
        zone_explicit=False,  # the served door DEFAULTED the zone (no `zone` in the payload)
    )
    job_store = JobStore(tmp_path / "jobs")
    presence = PresenceRegistry(tmp_path / "presence")
    # The REAL invoke() is re-entered (no synthetic S4 stub) — the detached runner's exact path.
    outcome = jobrunner.run_job(spec, job_store=job_store, presence=presence)
    assert outcome.disposition == "terminal-returned"
    assert outcome.code == "zone-required"


def test_served_render_reentry_hits_the_same_s4_refusal(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    spec = jobrunner.JobSpec(
        key=job_key((_A,), "idem-s4r"),
        verb="render",
        workspace=WS,
        user=USER,
        zone="default",
        params={},
        idempotency_key="idem-s4r",
        root=str(tmp_path),
        token=None,
        zone_explicit=False,
    )
    outcome = jobrunner.run_job(
        spec, job_store=JobStore(tmp_path / "jobs"), presence=PresenceRegistry(tmp_path / "p")
    )
    assert outcome.disposition == "terminal-returned"
    assert outcome.code == "zone-required"


def test_explicit_zone_served_reentry_passes_s4(tmp_path: Path) -> None:
    _make_multizone_user(tmp_path)
    spec = jobrunner.JobSpec(
        key=job_key((_A,), "idem-ok"),
        verb="continue-session",
        workspace=WS,
        user=USER,
        zone="work",
        params={"action": "generate-next"},
        idempotency_key="idem-ok",
        root=str(tmp_path),
        token=None,
        zone_explicit=True,  # the client NAMED the zone → no S4 refusal
    )
    # No token → generate-next surfaces a code-less "token required" block (re-drivable), NOT the
    # zone-required whole-invocation refusal — proving S4 did NOT fire on the explicit-zone path.
    outcome = jobrunner.run_job(
        spec, job_store=JobStore(tmp_path / "jobs"), presence=PresenceRegistry(tmp_path / "p")
    )
    assert outcome.code != "zone-required"


# ---------------------------------------------------------------------------------------
# The provenance signal crosses the process boundary (spawn file) losslessly
# ---------------------------------------------------------------------------------------


def test_jobspec_round_trip_preserves_zone_provenance_and_override() -> None:
    spec = jobrunner.JobSpec(
        key="k",
        verb="continue-session",
        workspace=WS,
        user=USER,
        zone="work",
        params={"action": "generate-next"},
        idempotency_key="idem",
        root="/root",
        zone_explicit=False,
        transport_override="key:anthropic:acme",
    )
    restored = jobrunner.JobSpec.from_json(spec.as_json())
    assert restored.zone_explicit is False
    assert restored.transport_override == "key:anthropic:acme"


def test_shim_zone_explicit_reads_the_provenance_signal() -> None:
    # The served door's provenance extractor: `zone` present → explicit; absent → defaulted.
    assert _ShimRequestHandler._zone_explicit({"zone": "work"}) is True
    assert _ShimRequestHandler._zone_explicit({}) is False


# ---------------------------------------------------------------------------------------
# LOW-2: a MALFORMED transport config → a clean PRE-SPEND refusal, never a runner crash
# ---------------------------------------------------------------------------------------


def _write_malformed_transport_config(root: Path) -> None:
    cfg = root / "instance" / "ops" / "transport" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    # A scalar (not a mapping) → `load_store` raises `assignment.ConfigError` at the chokepoint.
    cfg.write_text("this is not a transport-config mapping, just a scalar string\n")


def test_malformed_config_is_a_prespend_refusal_block_not_a_crash(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from pipeline.api import session

    _write_malformed_transport_config(tmp_path)
    to_generate = [SimpleNamespace(artifact_id=_A, deliverables=(1,))]
    plan = SimpleNamespace(plan_hash="feedfacefeed")
    admission, transport_plan, refusal = session._admit_batch_transport(
        tmp_path, "dave", "default", "acme", None, to_generate, plan
    )
    # Caught at the chokepoint → a per-item refusal reason, NOT a raise, NO admission/plan/hold.
    assert admission is None and transport_plan is None
    assert refusal is not None and "config" in refusal.lower()


def test_config_error_escaping_to_the_runner_records_a_clean_terminal(tmp_path: Path) -> None:
    from pipeline.spend.assignment import ConfigError

    def _raises_config_error(*_a, **_k):
        raise ConfigError("assignment-bad-config: transport config.yaml: not a mapping")

    # A `ConfigError` escaping to the detached runner on ANY other invoke path is CAUGHT by the
    # jobrunner raiser set (LOW-2) → a clean recorded terminal, never a runner CRASH (pre-spawn).
    outcome = jobrunner.run_job(
        jobrunner.JobSpec(
            key=job_key((_A,), "idem-cfg"),
            verb="continue-session",
            workspace=WS,
            user=USER,
            zone="default",
            params={"action": "generate-next"},
            idempotency_key="idem-cfg",
            root=str(tmp_path),
            token=None,
            zone_explicit=True,
        ),
        job_store=JobStore(tmp_path / "jobs"),
        presence=PresenceRegistry(tmp_path / "p"),
        invoke=_raises_config_error,
    )
    # A CRASH would propagate the ConfigError out of run_job (failing this call); instead it is
    # CAUGHT and routed to a clean terminal carrying the config-error code (money-safe, pre-spawn).
    assert outcome.disposition == "terminal-raised"
    assert outcome.code == "assignment-bad-config"
