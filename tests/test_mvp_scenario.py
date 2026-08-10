"""tests/test_mvp_scenario.py — the hermetic ★ MVP acceptance scenario (§25; build step 39).

This is the CI-safe twin of the `pipeline mvp-demo` subcommand: it exercises EVERY §25 clause
end to end over the REAL pipeline (real grounding, resolution, compose→reconcile→serialize,
reviews, folios, manifest, sequential + parallel, SSOT) — but with the writer/review TRANSPORT
faked (a `ProcessOutcome` returned in-process, NO child `claude` spawned, NO subscription spend,
no `ANTHROPIC_API_KEY`). The world is built entirely in a tmp dir (real framework registries +
a synthetic mock-source pool + a tmp workspace + a tmp styled presentation) — it reads NO real
client graph and depends on NO untracked `workspaces/mvp-demo/` data, so it passes
`scripts/check-no-content.sh`.

Two hard gates are proven here:

- **GATE-1 (§21.7 code threading).** `test_gate1_*` drives generate-next against a tmp platform
  whose ONLY hard limit is a tiny `max_chars`; with a `pass` reconcile strategy the terminal
  hard-limit gate blocks (the reconciler LLM is never called), the driver threads the REAL
  `hard-limit-exceeded` taxonomy code across the driver→session boundary, and generate-next
  surfaces a CODED block (`code == "hard-limit-exceeded"`, `status == "block"`) — never a bare
  code-less hint, never a fabricated code.
- **GATE-2 (§21.9 currency).** The scenario injects a PRECISE fake `CurrencyResolver` at every
  edge; `discovery.DefaultCurrencyResolver` is never constructed on this path. The test asserts
  the injected resolver was actually consulted (so the explicit seam — not the unsafe default —
  is what computed currency).
"""

from __future__ import annotations

import functools
import json
import re
import shutil
from datetime import date
from pathlib import Path

import pytest

from pipeline import driver, reconcile, serialize
from pipeline.adapters.mock import MockAdapter
from pipeline.api import invoke as invoke_mod
from pipeline.api import session
from pipeline.api.render import DefaultRenderEngine
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.mvpdemo import (
    M3_RUN_SELECTION,
    PLAIN_PRESENTATION,
    STYLED_PRESENTATION,
    MvpFailSafeCurrencyResolver,
    run_mvp_scenario,
)
from pipeline.review import ARTIFACT_CHECKS, DELIVERABLE_CHECKS
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate
from pipeline.store import WorkspaceStore
from pipeline.transport import ProcessOutcome, ProcessRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "mvp-demo"
USER = "acme"
NOW = date(2026, 7, 7)
_PANDOC_AVAILABLE = pandoc_available()


@pytest.fixture(autouse=True)
def _require_pandoc():
    """PA-12 gate: absent + CI ⇒ FAIL loudly; absent locally ⇒ skip; present ⇒ run. The whole
    scenario serializes real bytes through the pinned pandoc, so it needs the binary."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the MVP scenario serializes real bytes and MUST run "
            "in CI (PA-12); a silent skip cannot make CI green",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the MVP scenario requires the pinned binary")


# ---------------------------------------------------------------------------
# The mocked transport (writer + reviewer): a ProcessOutcome, in-process. No child, no spend.
# ---------------------------------------------------------------------------


def _result_envelope(result_text: str) -> str:
    """The step-04 success envelope the transport reads (`.result` = the stage output)."""
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": result_text,
            "session_id": "sess",
            "uuid": "uuid",
        }
    )


def _ok(result_text: str) -> ProcessOutcome:
    return ProcessOutcome(
        timed_out=False, returncode=0, stdout=_result_envelope(result_text), stderr=""
    )


#: Anchored on the exact heading `build_writer_prompt` appends (the template itself carries
#: illustrative ```json fences, so a bare fence match would grab the wrong block).
_CTX = re.compile(r"## Compose context \(JSON\)\s*```json\s*\n(.*?)\n```", re.DOTALL)


def _prompt_context(prompt: str) -> dict:
    """Extract the writer prompt's JSON compose-context block (grounded_facts + structure)."""
    match = _CTX.search(prompt)
    assert match is not None, "the writer prompt must carry a ## Compose context (JSON) block"
    return json.loads(match.group(1))


def _cited_body(facts: list[dict]) -> str:
    """A short-opinion-post body that cites EVERY grounded fact at its EXACT tier (so the §16
    fidelity coverage check — every ledger fact cited or dropped — passes) and nests no bracket
    inside a citation span (so the balanced-scanner tier gate is satisfied)."""
    cites = " ".join(
        f'[grounded {f["fact_id"]}]{{.{f["tier"]} data-fact="{f["fact_id"]}"}}.' for f in facts
    )
    return f"Hook: a sharp observation. The point, stated plainly. Evidence: {cites} Takeaway."


def _writer_content(prompt: str) -> dict:
    """The writer's CONTENT envelope, derived from the prompt: flat `{body}` for a single-part
    format (short-opinion-post), else `{parts}` covering exactly the declared roles."""
    ctx = _prompt_context(prompt)
    facts = ctx["grounded_facts"]
    structure = ctx["structure"]
    body = _cited_body(facts)
    if structure["shape"] == "flat":
        return {"body": body}
    roles = structure["roles"]
    return {
        "parts": {role: (body if i == 0 else f"Notes for {role}.") for i, role in enumerate(roles)}
    }


class WriterRunner:
    """The injected WRITER transport (compose stage): parses the prompt's grounded facts and
    returns a valid, fully-cited content envelope. Records every request (call-count evidence)."""

    def __init__(self) -> None:
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        return _ok(json.dumps(_writer_content(request.stdin_text)))


class ReviewRunner:
    """The injected REVIEW transport (§19 Review 1 + Review 2): returns a `pass` assessment over
    EXACTLY the review type's check set — artifact vs deliverable discriminated by the unique
    `ast_provenance` marker the deliverable-review prompt carries."""

    def __init__(self) -> None:
        self.requests: list[ProcessRequest] = []

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        deliverable = "ast_provenance" in request.stdin_text
        checks = DELIVERABLE_CHECKS if deliverable else ARTIFACT_CHECKS
        assessment = {
            "verdict": "pass",
            "checks": {c: {"status": "pass", "note": "ok"} for c in checks},
            "summary": "mvp fake review — grounded and fitting",
        }
        return _ok(json.dumps(assessment))


class PreciseCurrencyResolver:
    """GATE-2: a PRECISE currency resolver (NOT `discovery.DefaultCurrencyResolver`) — it
    recomputes the fit/serialize digest FROM the stored preimage, which necessarily equals the
    recorded digest (nothing drifted), so every deliverable reads `*_current == True`. It has NO
    `except → stored_digest` branch (that is the exact §21.9 hazard the gate closes). Records
    call-counts so the test can prove the injected seam was actually consulted."""

    def __init__(self) -> None:
        self.fit_calls = 0
        self.serialize_calls = 0

    def current_fit_digest(
        self, *, root, user, workspace, fitted_id, stored_preimage, zone="default"
    ) -> str:
        self.fit_calls += 1
        return reconcile.fit_digest(stored_preimage)

    def current_serialize_digest(
        self, *, root, user, workspace, deliverable_id, stored_preimage, zone="default"
    ) -> str:
        self.serialize_calls += 1
        return serialize.serialize_digest(stored_preimage)


# ---------------------------------------------------------------------------
# The hermetic world: real registries + a tmp styled presentation + tmp platforms + a mock pool.
# ---------------------------------------------------------------------------

_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

_TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"

_SOURCE = (
    "---\n"
    "id: {sid}\n"
    "provenance: instance\n"
    "schema_version: 1\n"
    "adapter: mock\n"
    "connection:\n"
    "  dataset: {dataset}\n"
    "content_kind: general\n"
    "trusted: {trusted}\n"
    "independence: {independence}\n"
    "primariness: {primariness}\n"
    "---\n\nSynthetic mock source {sid}.\n"
)

#: The tmp styled presentation (§5.3 PD5) — sets a non-empty `variables` map, so it lowers to a
#: real variables snapshot (distinct from the `plain` floor's empty one). Authored in the tmp
#: registry, NEVER a tracked framework `presentations/*` entry (scope fence).
_DOCUMENTATION_PRES = (
    "---\n"
    "id: documentation\n"
    "provenance: framework\n"
    "schema_version: 1\n"
    "variables:\n"
    "  mainfont: Fira Sans\n"
    "---\n\n# documentation — styled presentation (test fixture)\n"
)

#: A tmp `github` that adds a `short-opinion-post: pass` reconcile default (the per-format
#: PROJECTION rung, §12.3), so the demo format reconciles with the never-LLM `pass` strategy.
#: (github's own hard limit is the large `markdown_body_char_limit`, which `default_measure`
#: does not measure, so the normal deliverables never block.)
_GITHUB_PASS = (
    "---\n"
    "id: github\n"
    "provenance: framework\n"
    "schema_version: 1\n"
    "destination: GitHub repository surfaces.\n"
    "advisory_norms:\n"
    "  preferred_line_length: 120\n"
    "hard_limits:\n"
    "  markdown_body_char_limit: 65536\n"
    "reconcile_strategy_defaults:\n"
    "  short-opinion-post: pass\n"
    "default_output_type: md\n"
    "---\n\n# github — platform (test fixture; adds the short-opinion-post pass default)\n"
)

#: The GATE-1 platform: its ONLY hard limit is a tiny `max_chars` (which `default_measure` DOES
#: measure) + a `short-opinion-post: pass` reconcile default → the terminal gate blocks with
#: `hard-limit-exceeded` and the reconciler LLM is never called.
_TINY_LIMIT = (
    "---\n"
    "id: tiny-limit\n"
    "provenance: framework\n"
    "schema_version: 1\n"
    "destination: A test platform with a tiny hard char limit (GATE-1 proof).\n"
    "hard_limits:\n"
    "  max_chars: 5\n"
    "reconcile_strategy_defaults:\n"
    "  short-opinion-post: pass\n"
    "default_output_type: md\n"
    "---\n\n# tiny-limit — platform (GATE-1 fixture)\n"
)

_SOURCES = (
    ("x-alpha-docs", "alpha-docs", 5, "first-party", "primary"),
    ("x-beta-mirror", "beta-mirror", 4, "first-party", "secondary"),
    ("x-gamma-review", "gamma-review", 4, "independent", "secondary"),
)

_TOPICS = (
    ("x-widget-service", "Explain the widget service."),
    ("x-gadget-cache", "Explain the gadget cache."),
)


def build_world(tmp_path: Path) -> Path:
    """A full framework root (real registries) + a tmp styled presentation, tmp platforms, and a
    tmp workspace with a synthetic mock-source pool — the entire §25 world, in tmp (REC-3)."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2_DEFAULTS, encoding="utf-8")
    (registry_dir(root, "presentations") / "documentation.md").write_text(
        _DOCUMENTATION_PRES, encoding="utf-8"
    )
    (registry_dir(root, "platforms") / "github.md").write_text(_GITHUB_PASS, encoding="utf-8")
    (registry_dir(root, "platforms") / "tiny-limit.md").write_text(_TINY_LIMIT, encoding="utf-8")

    topics_dir = root / "users" / USER / "zones" / "default" / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    for tid, why in _TOPICS:
        (topics_dir / f"{tid}.md").write_text(_TOPIC.format(tid=tid, why=why), encoding="utf-8")

    sources_dir = root / "users" / USER / "zones" / "default" / "workspaces" / WS / "sources"
    sources_dir.mkdir(parents=True)
    for sid, dataset, trusted, independence, primariness in _SOURCES:
        (sources_dir / f"{sid}.md").write_text(
            _SOURCE.format(
                sid=sid,
                dataset=dataset,
                trusted=trusted,
                independence=independence,
                primariness=primariness,
            ),
            encoding="utf-8",
        )
    return root


def _adapters() -> dict:
    return {"mock": MockAdapter()}


# ---------------------------------------------------------------------------
# The full §25 scenario (every clause) — mock transport, real everything else.
# ---------------------------------------------------------------------------


def test_mvp_scenario_covers_every_section_25_clause(tmp_path):
    root = build_world(tmp_path)
    writer, review = WriterRunner(), ReviewRunner()
    currency = PreciseCurrencyResolver()

    report = run_mvp_scenario(
        root=root,
        user=USER,
        workspace=WS,
        adapters=_adapters(),
        runner=writer,
        review_runner=review,
        render_engine=DefaultRenderEngine(),
        currency_resolver=currency,
        now=NOW,
        model="mvp-fake-model",
    )

    # -- NINE dimensions, interacting (the §25 mandate; no staged/partial axis set). ------------
    axes = report.axes
    assert axes["topic"] == "x-widget-service"
    assert axes["persona"] == "technical-evaluator"  # the recipe persona (sequential branch)
    assert axes["format"] == "short-opinion-post"
    assert axes["voice"] == "clear-explainer"
    assert axes["goals"] == ["explain"]
    assert axes["platform"] == "github" and axes["language"] == "en"
    assert set(axes["output_type"]) == {"md", "epub"}  # ≥1 internal + ≥1 external
    assert set(axes["presentation"]) == {PLAIN_PRESENTATION, STYLED_PRESENTATION}

    # -- §6 grounding grammar: require+span+prefer+on_conflict, a ≥2-instance RESOLVED conflict.
    g = report.grounding
    assert g["selection"]["on_conflict"] == "preserve-and-attribute"
    assert g["selection"]["require"] and g["selection"]["prefer"]
    assert g["selection"]["span"]["independence"] == ["first-party", "independent"]
    assert len(g["survivor_instances"]) >= 2
    assert g["published_fact_count"] >= 2
    # BOTH conflicting timeout claims survive, attributed (30s vs 60s).
    assert len(g["conflict_claims"]) == 2
    assert any("30 seconds" in c for c in g["conflict_claims"])
    assert any("60 seconds" in c for c in g["conflict_claims"])

    # -- §12 override: a RESOLVED effective-value entry changed (not merely the id hash). --------
    o = report.override
    assert o["attribute"] == "voice.formality"
    assert o["with_override"] == 5 and o["with_override"] != o["without_override"]

    # -- §5.3 PD5 (B1): plain vs styled — distinct ids; the styled preimage carries variables. ---
    s = report.styled
    assert s["distinct_ids"] is True
    assert s["plain_variables"] in ({}, None)  # the plain floor lowers to the empty snapshot
    assert s["styled_variables"] == {"mainfont": "Fira Sans"}  # the styled delta-vs-floor

    # -- §19 both review gates ran (advisory; records exist, verdict pass). ----------------------
    r = report.reviews
    assert r["artifact_review_present"] and r["artifact_verdict"] == "pass"
    assert r["deliverable_review_present"] and r["deliverable_verdict"] == "pass"

    # -- §14–§17 ≥1 EXTERNAL-side target: an epub deliverable, provenance stripped, layer-3. -----
    e = report.external
    assert e["side"] == "external" and e["writer"] == "epub3"
    assert e["provenance_stripped"] is True
    assert e["deliverable_id"] and e["deliverable_id"] != s["plain_deliverable_id"]

    # -- §21.6 sequential batch+cursor: cursor advances 0 → 1 → 2 over the two artifacts. --------
    seq = report.sequential
    assert seq["cursor_progression"] == [0, 1, 2]
    assert len(seq["artifact_ids"]) == 2
    assert seq["status_progress"]["consumed"] == 2

    # -- §22 parallel: a genuine wave plan + an incomplete → complete sweep over 2 artifacts. ----
    par = report.parallel
    assert par["wave_count"] == 2
    assert par["sweep_before"]["complete"] is False
    assert par["sweep_partial"]["complete"] is False
    assert par["sweep_after"]["complete"] is True
    # M3: the parallel artifacts are DISJOINT from the sequential ones (distinct persona).
    assert set(par["artifact_ids"]).isdisjoint(set(seq["artifact_ids"]))

    # -- §9 folio: a TYPED member (role) + an UNTYPED member (no role). --------------------------
    f = report.folio
    assert f["folio_type"] == "repo-docs"
    assert f["typed_member_role"] == "architecture"
    assert f["untyped_member_role"] is None

    # -- §21.5 emit-manifest: rows reference an INTERNAL path AND an EXTERNAL layer-3 payload. ----
    m = report.manifest
    assert m["has_internal_path"] is True
    assert m["has_external_layer3"] is True
    assert m["path"].startswith("output/manifests/")

    # -- §24 SSOT: both row kinds present + a derived-state mirror. -------------------------------
    ssot = report.ssot
    assert ssot["has_artifact_rows"] and ssot["has_deliverable_rows"]
    assert ssot["derive_state"].strip()

    # -- §21.3 discovery reads (list/get). Currency for every listed deliverable is computed
    #    through the injected resolver (GATE-2). --------------------------------------------------
    d = report.discovery
    assert d["get_artifact_present"] is True
    assert d["list_deliverable_count"] >= 2

    # -- GATE-2: the injected PRECISE currency resolver was actually consulted (not the default).
    assert currency.serialize_calls > 0

    # -- NO live spend: only the injected fakes were called; both were exercised. -----------------
    assert writer.requests, "the fake writer transport must have been invoked (no live call)"
    assert review.requests, "the fake review transport must have been invoked (no live call)"


# ---------------------------------------------------------------------------
# B1 (§5.3 PD5): render.py's presentation lowering on the `plain` floor is byte-identical to the
# retired `lower_plain(target)` — the render-verb minting path churns NO existing deliverable.
# ---------------------------------------------------------------------------


def test_render_py_b1_plain_floor_is_byte_identical_to_lower_plain(tmp_path):
    """render.py `_lower_for_leg` on a `plain`-floor leg yields the EMPTY RenderInputs — the exact
    struct `dispatch.lower_plain(target)` produced before B1. So every existing (all-`plain`)
    deliverable resolves to the same serialize preimage → the same id + bytes (PD5 zero-churn)."""
    from pipeline.api import render as render_api
    from pipeline.cascade import CascadeEnv
    from pipeline.dispatch import lower_plain, render_target_from_entry
    from pipeline.presentation import render_inputs_to_mapping

    root = build_world(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    entry = env.resolver.resolve("render-targets", "md")
    target = render_target_from_entry({**entry.defaults(), **entry.effective, "id": entry.id})
    leg = render_api.SerializeLeg(
        root=root,
        user=USER,
        workspace=WS,
        store=WorkspaceStore.at(root, USER, WS, zone="default"),
        fitted_id="a-0000000000000000.github.en",
        fitted_ir={},
        output_type="md",
        presentation="plain",
    )
    b1 = render_api._lower_for_leg(env, leg, target)
    plain = lower_plain(target)
    assert render_inputs_to_mapping(b1) == render_inputs_to_mapping(plain)
    assert render_inputs_to_mapping(b1) == {
        "flags": [],
        "variables": {},
        "assets": [],
        "engine": target.engine,
    }


# ---------------------------------------------------------------------------
# GATE-1 (§21.7): a hermetic hard-limit block threads the REAL taxonomy code to generate-next.
# ---------------------------------------------------------------------------


def _handlers(root: Path, writer: WriterRunner, review: ReviewRunner, currency) -> dict:
    return {
        "begin-session": session.begin_session_handler(adapters=_adapters()),
        "continue-session": session.continue_session_handler(
            adapters=_adapters(),
            run_artifact=functools.partial(
                driver._run_artifact, runner=writer, review_runner=review
            ),
            now=NOW,
            model="mvp-fake-model",
            render_engine=DefaultRenderEngine(),
            currency_resolver=currency,
        ),
    }


def test_gate1_hard_limit_block_carries_the_taxonomy_code(tmp_path):
    """Compose SUCCEEDS (the fake writer), the `pass` reconcile invokes no LLM, and the terminal
    hard-limit gate blocks on the tiny `max_chars`. The driver threads the REAL `hard-limit-
    exceeded` §21.7 code; generate-next surfaces a CODED block — never a bare hint, never a
    fabricated code."""
    root = build_world(tmp_path)
    store = WorkspaceStore.at(root, USER, WS, zone="default")
    store.ensure_layout()
    writer, review = WriterRunner(), ReviewRunner()
    handlers = _handlers(root, writer, review, PreciseCurrencyResolver())

    begin = invoke_mod.invoke(
        "begin-session",
        WS,
        USER,
        {
            "recipe": "explainer-post",
            "topics": ["x-widget-service"],
            "platforms": ["tiny-limit"],
            "languages": ["en"],
            "output_types": ["md"],
            "presentations": ["plain"],
            # so the widget GROUNDS (its EXTRACTED facts publish; conflict preserved) → compose
            # succeeds → the block is the reconcile TERMINAL gate, not an upstream grounding block.
            "run_selection": M3_RUN_SELECTION,
        },
        store=store,
        root=str(root),
        handlers=handlers,
    )
    assert begin["envelope"]["ok"] is True

    step = invoke_mod.invoke(
        "continue-session",
        WS,
        USER,
        {"action": "generate-next", "batch_size": 1},
        token=begin["token"],
        store=store,
        root=str(root),
        handlers=handlers,
    )
    results = step["results"]
    blocked = [r for r in results if r.get("code") == "hard-limit-exceeded"]
    assert blocked, f"expected a hard-limit-exceeded coded block, got {results!r}"
    assert blocked[0]["status"] == "block"  # status DERIVED from the code's CodeSpec, not hardcoded
    # the reconciler LLM was never asked; only the compose writer ran (once), review at most once.
    assert len(writer.requests) == 1


# ---------------------------------------------------------------------------
# GATE-2 (§21.9): the live fail-safe resolver is conservative (never `stored_digest` on error).
# ---------------------------------------------------------------------------


def test_gate2_failsafe_resolver_is_conservative_never_current(tmp_path):
    """The MVP live-edge resolver reads EVERY deliverable as NOT-current (a distinct non-`hex12`
    sentinel), so it can never mistake an un-verifiable input for no-drift — the exact §21.9
    hazard the gate closes. It is NOT `discovery.DefaultCurrencyResolver`."""
    from pipeline.api import discovery

    resolver = MvpFailSafeCurrencyResolver()
    assert not isinstance(resolver, discovery.DefaultCurrencyResolver)
    sentinel_fit = resolver.current_fit_digest(
        root=Path(tmp_path),
        user=USER,
        workspace=WS,
        fitted_id="fitted",
        stored_preimage={"any": "value"},
    )
    sentinel_ser = resolver.current_serialize_digest(
        root=Path(tmp_path),
        user=USER,
        workspace=WS,
        deliverable_id="deliv",
        stored_preimage={"any": "value"},
    )
    # a real recorded digest is 12 lowercase hex; the sentinel can never equal one → not-current.
    assert not re.fullmatch(r"[0-9a-f]{12}", sentinel_fit)
    assert sentinel_fit == sentinel_ser  # a single conservative sentinel for both edges


# ---------------------------------------------------------------------------
# Driver-seam tests (F1 + C5): drive `driver._run_artifact` DIRECTLY over the hermetic mock
# transport. The LIVE `run_thread` has NO runner seam, and the generate-next path passes
# `log=_nolog` (discarding the F1 emit) — so these target `_run_artifact` directly (the plan's
# state-verified seam refinement). They ride the module's autouse pandoc gate.
# ---------------------------------------------------------------------------


class _FailThenSucceedWriter:
    """attempt 1 → a substance-free `"..."` body (fails the §15 substance floor → bounded re-ask);
    attempt 2 → a valid, fully-cited body. Proves the driver SURFACES a RECOVERED derail (F1)."""

    def __init__(self) -> None:
        self.requests: list = []

    def __call__(self, request) -> ProcessOutcome:
        self.requests.append(request)
        if len(self.requests) == 1:
            return _ok(json.dumps({"body": "..."}))  # substance floor → re-ask
        return _ok(json.dumps(_writer_content(request.stdin_text)))  # recovered


class _NeverWriter:
    """A writer that must NOT be invoked — the idempotent re-drive path skips compose (C5)."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, request) -> ProcessOutcome:  # pragma: no cover
        self.calls += 1
        raise AssertionError("the writer must not be invoked on the idempotent re-drive (§21.8)")


def _drive_widget_artifact(root, *, runner, review, log, now=NOW):
    """Drive `driver._run_artifact` for the sequential-widget artifact hermetically (real grounding
    / resolution / compose→reconcile→serialize / reviews over the mock transport; NO subscription
    spend). Returns the ArtifactResult (raises DriverError on a genuine stage failure)."""
    from pipeline.spine import registry_for
    from pipeline.ssot import Ssot

    store = WorkspaceStore.at(root, USER, WS, zone="default")
    store.ensure_layout()
    begin = invoke_mod.invoke(
        "begin-session",
        WS,
        USER,
        {
            "recipe": "explainer-post",
            "topics": ["x-widget-service"],
            "platforms": ["github"],
            "languages": ["en"],
            "output_types": ["md"],
            "presentations": ["plain"],
            "run_selection": M3_RUN_SELECTION,
        },
        store=store,
        root=str(root),
        handlers={"begin-session": session.begin_session_handler(adapters=_adapters())},
    )
    token = invoke_mod.token_mod.decode(begin["token"], expected_workspace=WS)
    plan, env, pool, source_repos = session._resolve_from_inputs(
        root, USER, WS, "default", token.inputs
    )
    item = next(i for i in plan.items if i.topic == "x-widget-service")
    return driver._run_artifact(
        env=env,
        store=store,
        claims=registry_for(store),
        ssot=Ssot(store.root / "ssot.csv"),
        plan=plan,
        item=item,
        pool=pool,
        adapters=_adapters(),
        source_repos=source_repos,
        now=now,
        model="mvp-fake-model",
        log=log,
        runner=runner,
        review_runner=review,
    )


def test_driver_surfaces_recovered_reask_on_success_path(tmp_path):
    """F1 (GAP-6 observability): a fail-then-succeed writer (`"..."` → valid) drives a RECOVERED
    derail through `driver._run_artifact`; the driver SURFACES it on the SUCCESS path (a captured
    `RE-ASK` log line), not merely carrying it on `cout`."""
    root = build_world(tmp_path)
    writer = _FailThenSucceedWriter()
    lines: list[str] = []
    result = _drive_widget_artifact(root, runner=writer, review=ReviewRunner(), log=lines.append)
    assert len(writer.requests) == 2  # attempt-1 re-asked, attempt-2 recovered
    assert any("RE-ASK" in line for line in lines), lines  # the driver SURFACED the recovery
    assert result.artifact_id  # the artifact still materialized (the derail recovered)


def test_driver_idempotent_redrive_reserializes_without_recomposing(tmp_path):
    """C5 (GAP-1d): a second `driver._run_artifact` over an already-materialized artifact re-drives
    serialize-only — compose short-circuits (`status="ok", ir=None`), the driver LOADS the stored IR
    via `ir.unwrap_ir` and continues to the serialize legs; the writer is NEVER re-invoked and no
    DriverError is raised (the old guard hard-blocked this idempotent no-op)."""
    root = build_world(tmp_path)
    first = _drive_widget_artifact(
        root, runner=WriterRunner(), review=ReviewRunner(), log=lambda _m: None
    )
    never = _NeverWriter()
    second = _drive_widget_artifact(root, runner=never, review=ReviewRunner(), log=lambda _m: None)
    assert never.calls == 0  # compose short-circuited — the writer was not invoked
    assert second.artifact_id == first.artifact_id
    assert second.deliverables  # the serialize legs re-drove over the stored IR, no raise


def test_driver_idempotent_redrive_raises_on_vanished_record(tmp_path, monkeypatch):
    """C5 NEW-F: the idempotent re-drive guards its load — if the stored record vanished/corrupted
    between compose's `is_done` check and the load, the driver raises a clear DriverError, NEVER
    `ir.unwrap_ir(None)`. Modeled by forcing the load to return None on the re-drive (the real
    race); compose still short-circuits on the intact record."""
    root = build_world(tmp_path)
    _drive_widget_artifact(root, runner=WriterRunner(), review=ReviewRunner(), log=lambda _m: None)
    monkeypatch.setattr(driver, "_read_stored_record", lambda store, id_str: None)
    with pytest.raises(driver.DriverError):
        _drive_widget_artifact(
            root, runner=_NeverWriter(), review=ReviewRunner(), log=lambda _m: None
        )
