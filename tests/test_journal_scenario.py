"""DR-4 COMMIT C10 — the driving example: one academic-paper IR, THREE journal deliverables.

Design authority: `docs/design.md` §5.2/§5.3/§12.7/§16/§17 and the FINAL RECONCILED DR-4 build
plan, COMMIT C10 (materialize the driving example with per-venue enforcement LIVE).

C1–C9 built the machinery; C10 ships the three framework venue-PROFILES (`platforms/journal-*.md`)
and their looks (`presentations/journal-*-look.md`) and proves, over the REAL
compose -> reconcile -> serialize path with the SHIPPED registry entries:

- **One composed `academic-paper` IR reconciled against THREE journals** that each TIGHTEN the base
  genre differently: `journal-strict` FORBIDS acknowledgements, `journal-structured` REQUIRES a
  discussion section (which the base leaves optional), `journal-concise` caps the abstract length
  (a #4a per-section numeric bound). The per-venue block/fit SET is a perfect diagonal, and one
  venue's block never aborts the others — reconcile returns a TYPED block outcome, never an
  exception, so siblings continue (§6.4 block-and-report).
- **A fitted TYPED deliverable renders VALID public bytes (C9).** A section carrying a bare
  `type=` heading kv is stripped on the html public writer: the bytes carry NO raw `type=`/`role=`
  and DO keep the `{#id}` anchor (`id="…"`).
- **The discovery C9 carry-forward (A).** A stored TYPED deliverable's `current_serialize_digest`
  equals its stored digest — NO spurious drift — because `DefaultCurrencyResolver` now re-derives
  the SD-5 `section_attr_transform_version` flag from the stored bundle before rebuilding.

Hermetic (REC-3): a tmp world with the REAL framework registries + a tmp workspace; the compose
writer TRANSPORT is faked (a `ProcessOutcome` in-process — NO child `claude`, NO subscription
spend, no `ANTHROPIC_API_KEY`), so this passes `scripts/check-no-content.sh`. Only the
serialize-byte tests need the pinned pandoc; the block/fit matrix and the looks run without it.
"""

from __future__ import annotations

import datetime
import json
import shutil
from pathlib import Path

import pytest

from pipeline import driver, ir
from pipeline.api import discovery
from pipeline.cascade import CascadeEnv
from pipeline.compose import ComposeRequest, compose_artifact
from pipeline.dispatch import dispatch, render_target_from_entry
from pipeline.grounding import Anchor, GroundedFact
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.lint import REGISTRY_ROOTS
from pipeline.presentation import lower, presentation_from_entry, render_inputs_to_mapping
from pipeline.reconcile import (
    CODE_SECTION_CONFORMANCE_VIOLATION,
    ReconcileRequest,
    reconcile,
)
from pipeline.serialize import (
    is_ci,
    pandoc_available,
    pandoc_gate,
    serialize_digest,
    serialize_fitted,
    serialize_inputs_preimage,
)
from pipeline.spine import registry_for
from pipeline.store import WorkspaceStore
from pipeline.transport import ProcessOutcome

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "journal-demo"
COMMIT = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"
_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

#: The three shipped C10 venue profiles + what each TIGHTENS on `academic-paper`.
VENUES = ("journal-strict", "journal-structured", "journal-concise")
_PANDOC_AVAILABLE = pandoc_available()


def _requires_pandoc() -> None:
    """PA-12: absent + CI ⇒ fail loudly; absent locally ⇒ skip; present ⇒ run. Only the
    serialize-byte tests need the pinned binary (the block/fit matrix is pure)."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the C10 serialize-byte proof MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the serialize-byte assertions need the pinned writer")


# ---------------------------------------------------------------------------
# The hermetic world: the REAL registries (incl. the C10 journals) + a tmp workspace.
# ---------------------------------------------------------------------------


def _build_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    for reg in REGISTRY_ROOTS:
        src = REPO_ROOT / reg
        if src.is_dir():
            shutil.copytree(src, root / reg)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2_DEFAULTS, encoding="utf-8")
    (root / "workspaces" / WS).mkdir(parents=True)
    return root


# ---------------------------------------------------------------------------
# The paper bodies. `academic-paper` is a single-part genre: the body IS a `##`-heading
# skeleton whose sections carry ROLES via `{#id}`. Each variant flips exactly one property
# so it blocks at exactly one venue and fits the other two (the diagonal + siblings-continue).
# The conforming body's `## Results {#results type=table}` is a TYPED section (a bare `type=`
# heading kv), so its public render exercises the C9 section-attr strip.
# ---------------------------------------------------------------------------

_CONFORMING = (
    "## Abstract {#abstract}\n\nA short, scannable abstract well under the concise cap.\n\n"
    "## Methods {#methods}\n\nWhat we did, in reproducible detail.\n\n"
    '## Results {#results type=table}\n\nWe observed a [linear-time result]'
    '{.EXTRACTED data-fact="f0"}.\n\n'
    "## Discussion {#discussion}\n\nWhat the result means, and the limits of the evidence."
)

_WITH_ACKS = (
    "## Abstract {#abstract}\n\nA short abstract.\n\n"
    "## Methods {#methods}\n\nWhat we did.\n\n"
    "## Results {#results}\n\nA neutral report of what we observed.\n\n"
    "## Discussion {#discussion}\n\nWhat it means.\n\n"
    "## Acknowledgements {#acknowledgements}\n\nThanks to the reviewers."
)

_NO_DISCUSSION = (
    "## Abstract {#abstract}\n\nA short abstract.\n\n"
    "## Methods {#methods}\n\nWhat we did.\n\n"
    "## Results {#results}\n\nA neutral report of what we observed."
)

_LONG_ABSTRACT = (
    "## Abstract {#abstract}\n\n" + ("word " * 200) + "\n\n"
    "## Methods {#methods}\n\nWhat we did.\n\n"
    "## Results {#results}\n\nA neutral report.\n\n"
    "## Discussion {#discussion}\n\nWhat it means."
)


class _NeverRunner:
    """A reconciler transport that must never run: every venue fit here is `pass` (ZERO LLM)."""

    def __call__(self, request):  # pragma: no cover — asserted never-called
        raise AssertionError("the reconciler transport must not be invoked on the pass path")


# ---------------------------------------------------------------------------
# Compose ONE conforming academic-paper through the REAL compose path (faked writer).
# ---------------------------------------------------------------------------


def _result_envelope(text: str) -> str:
    return json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": text,
            "session_id": "sess",
            "uuid": "uuid",
        }
    )


class _WriterRunner:
    """The faked WRITER transport: returns the fixed conforming body as a valid content envelope."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.requests: list = []

    def __call__(self, request) -> ProcessOutcome:
        self.requests.append(request)
        return ProcessOutcome(
            timed_out=False,
            returncode=0,
            stdout=_result_envelope(json.dumps({"body": self.body})),
            stderr="",
        )


def _grounded_fact() -> GroundedFact:
    return GroundedFact(
        subject="parser",
        claim="runs in linear time",
        instance_id="acme-graph",
        adapter="graphify",
        commit=COMMIT,
        base_tier="EXTRACTED",
        tier="EXTRACTED",
        corroboration=0,
        agreeing_instances=("acme-graph",),
        anchors=(Anchor(kind="file-line", value="src/parser.py:42"),),
        citable=True,
        as_of=datetime.date(2026, 6, 1),
        scores={"trusted": 5, "review_status": "merged", "freshness": datetime.date(2026, 6, 1)},
        weight=1.0,
        attestation=None,
    )


def _paper_preimage() -> dict:
    return build_artifact_preimage(
        topic=EntryBinding("x-parsing-study"),
        persona=EntryBinding("technical-evaluator"),
        format=EntryBinding("academic-paper"),
        voice=EntryBinding("clear-explainer"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT},
    )


def _compose_conforming_ir(root: Path) -> dict:
    """Genuinely compose ONE conforming `academic-paper` IR over the REAL compose path (faked
    writer, real IR mint + grounding validation). Returns the validated canonical IR."""
    store = WorkspaceStore(root / "workspaces" / WS)
    store.ensure_layout()
    claims = registry_for(store)
    preimage = _paper_preimage()
    request = ComposeRequest(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        format_parts=(),
        effective_values={"voice": {"tone": "clear"}, "persona": {"knowledge_level": 3}},
        grounded_facts=(_grounded_fact(),),
        source_repos={"acme-graph": "github.com/acme/parser"},
    )
    outcome = compose_artifact(
        request, store=store, claims=claims, runner=_WriterRunner(_CONFORMING)
    )
    assert outcome.status == "ok" and outcome.ir is not None, outcome
    return outcome.ir


def _variant_ir(body: str) -> dict:
    """A canonical `academic-paper` IR carrying `body` — the SAME `ir.build_ir` primitive compose
    assembles through — pinned to the `academic-paper` format so the reconcile structural gate
    reads THIS genre's venue schema (`binding.preimage.dimensions.format.entry`)."""
    preimage = _paper_preimage()
    return ir.build_ir(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        grounding={},
        body=body,
        parts=None,
    )


def _reconcile_at(env: CascadeEnv, canonical_ir: dict, platform: str):
    """Reconcile ONE canonical IR at ONE venue over the REAL path, reading the SHIPPED entry's
    `format_structural` + `hard_limits` through the production driver seams (M2-EXCLUDED reads).
    `pass` fits are a ZERO-LLM passthrough; the terminal structural gate still runs (C8)."""
    fs, fs_defaults = driver._platform_format_structural(env, platform, "academic-paper")
    hard_limits, hard_limit_defaults = driver._platform_hard_limits(env, platform)
    return reconcile(
        ReconcileRequest(
            canonical_ir=canonical_ir,
            artifact_id=canonical_ir["binding"]["artifact_id"],
            platform=platform,
            language="en",
            source_language="en",
            strategy="pass",
            hard_limits=hard_limits,
            hard_limit_defaults=hard_limit_defaults,
            format_structural=fs,
            format_structural_defaults=fs_defaults,
        ),
        runner=_NeverRunner(),
    )


# ---------------------------------------------------------------------------
# (D) One paper, three journals — the per-venue block/fit SET + siblings continue.
# ---------------------------------------------------------------------------


def test_one_paper_three_journals_block_fit_set_and_siblings_continue(tmp_path):
    root = _build_root(tmp_path)
    env = CascadeEnv(root, workspace=WS)

    papers = {
        "conforming": _compose_conforming_ir(root),  # the genuinely-composed driving example
        "with_acks": _variant_ir(_WITH_ACKS),
        "no_discussion": _variant_ir(_NO_DISCUSSION),
        "long_abstract": _variant_ir(_LONG_ABSTRACT),
    }

    # Reconcile EVERY (paper × venue) pair. A block is a TYPED outcome, never an exception, so the
    # loop completing over all 12 cells IS the siblings-continue proof (§6.4 block-and-report):
    # one venue's block never aborts the reconcile of another.
    matrix: dict[tuple[str, str], object] = {}
    for name, paper in papers.items():
        for venue in VENUES:
            matrix[(name, venue)] = _reconcile_at(env, paper, venue)

    def status(name: str, venue: str) -> str:
        return matrix[(name, venue)].status

    # The conforming driving example FITS all three venues (one paper, three journal deliverables).
    assert all(status("conforming", v) == "ok" for v in VENUES)

    # A perfect diagonal: each variant BLOCKS at exactly the one venue whose contract it breaks,
    # and FITS the other two (proving both the per-venue gate AND that siblings continue).
    assert (
        status("with_acks", "journal-strict"),
        status("with_acks", "journal-structured"),
        status("with_acks", "journal-concise"),
    ) == ("block", "ok", "ok")
    assert (
        status("no_discussion", "journal-strict"),
        status("no_discussion", "journal-structured"),
        status("no_discussion", "journal-concise"),
    ) == ("ok", "block", "ok")
    assert (
        status("long_abstract", "journal-strict"),
        status("long_abstract", "journal-structured"),
        status("long_abstract", "journal-concise"),
    ) == ("ok", "ok", "block")

    # Each block carries the DR-4 C8 code + a populated, correctly-scoped `structural_violations`.
    v1 = matrix[("with_acks", "journal-strict")]
    assert v1.code == CODE_SECTION_CONFORMANCE_VIOLATION and v1.blocked_limits == ()
    assert any("acknowledgements" in s for s in v1.structural_violations)

    v2 = matrix[("no_discussion", "journal-structured")]
    assert v2.code == CODE_SECTION_CONFORMANCE_VIOLATION
    assert any("discussion" in s for s in v2.structural_violations)

    v3 = matrix[("long_abstract", "journal-concise")]
    assert v3.code == CODE_SECTION_CONFORMANCE_VIOLATION
    # #4a: the abstract cap is enforced by the STRUCTURAL gate (a per-section length rule), NEVER
    # the whole-artifact `max_chars` gate — so no `blocked_limits` on a length breach.
    assert any("length" in s and "abstract" in s for s in v3.structural_violations)
    assert v3.blocked_limits == ()


# ---------------------------------------------------------------------------
# (D) A fitted TYPED deliverable renders VALID public bytes (C9) + no spurious drift (A, e2e).
# ---------------------------------------------------------------------------


def _serialize_html(env: CascadeEnv, fitted_ir: dict, presentation: str):
    """Serialize a fitted IR to the `html` public writer through the REAL serialize leg — the SAME
    threaded sequence `driver._run_deliverable` uses (serialize_fitted -> dispatch ->
    serialize_inputs_preimage(section_attr_transformed=dout.section_attr_transformed))."""
    ast = serialize_fitted(fitted_ir)[0].ast
    target_values = driver._render_target_values(env, "html")
    target = render_target_from_entry(target_values)
    pentry = env.resolver.resolve("presentations", presentation)

    def _no_asset(*_a, **_k):  # these looks set no css/template/reference-doc assets
        raise AssertionError("no asset should be loaded for a variables-only look")

    pres = presentation_from_entry(
        {**pentry.defaults(), **pentry.effective, "id": pentry.id},
        load_asset=_no_asset,
        defaults=pentry.defaults(),
    )
    render_inputs = lower(pres, target.writer, "html", target_engine=target.engine)
    dout = dispatch(target, ast, render_inputs=render_inputs)
    serialize_preimage = serialize_inputs_preimage(
        render_target=target_values,
        render_inputs=render_inputs_to_mapping(render_inputs),
        section_attr_transformed=dout.section_attr_transformed,
    )
    return dout, serialize_preimage


def test_fitted_typed_deliverable_renders_valid_public_bytes(tmp_path):
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, workspace=WS)
    composed = _compose_conforming_ir(root)

    fit = _reconcile_at(env, composed, "journal-strict")  # conforming fits (no acknowledgements)
    assert fit.status == "ok" and fit.fitted_ir is not None

    dout, _preimage = _serialize_html(env, fit.fitted_ir, "journal-strict-look")
    # It IS a typed deliverable: the `## Results {#results type=table}` heading carried a bare
    # structural kv, so the html public-writer strip fired (C9 signal → the OMIT-WHEN-ABSENT
    # preimage key rides).
    assert dout.section_attr_transformed is True
    assert dout.stripped is True  # the provenance strip also ran (public writer)

    text = dout.output_bytes.decode("utf-8")
    # C9: the published bytes carry NO raw structural typing attrs …
    assert "type=" not in text
    assert "role=" not in text
    # … yet DO keep the `{#id}` section anchors (a valid, published heading id survives the strip).
    assert 'id="results"' in text
    assert 'id="abstract"' in text


def test_two_phase_render_engine_records_the_typed_version(tmp_path):
    """RT: `DefaultRenderEngine.serialize_preimage` runs BEFORE dispatch (two-phase), so it
    computes the SD-5 flag from the fitted AST itself (gated by `should_strip`). A TYPED
    deliverable's preimage therefore records `section_attr_transform_version` — the SAME conclusion
    dispatch reaches — so a typed standalone-API render mints an id matching its bytes."""
    _requires_pandoc()
    from pipeline.api.render import DefaultRenderEngine, SerializeLeg

    root = _build_root(tmp_path)
    env = CascadeEnv(root, workspace=WS)
    fit = _reconcile_at(env, _compose_conforming_ir(root), "journal-strict")
    assert fit.status == "ok" and fit.fitted_ir is not None

    # dispatch (the reference) confirms this typed deliverable's public-writer strip fires:
    dout, _driver_preimage = _serialize_html(env, fit.fitted_ir, "journal-strict-look")
    assert dout.section_attr_transformed is True

    # the two-phase engine, WITHOUT running dispatch, must reach the SAME conclusion and record it:
    leg = SerializeLeg(
        root=root,
        workspace=WS,
        store=WorkspaceStore(root / "workspaces" / WS),
        fitted_id=fit.fitted_id,
        fitted_ir=fit.fitted_ir,
        output_type="html",
        presentation="journal-strict-look",
    )
    preimage = DefaultRenderEngine().serialize_preimage(leg)
    assert "section_attr_transform_version" in preimage["tool_bundle"]


def test_render_engine_memoizes_serialize_fitted_by_fitted_id(monkeypatch, tmp_path):
    """The two-phase seam (serialize_preimage then mint_deliverable) must shell the pinned pandoc
    reader ONCE per fitted artifact, not twice — DefaultRenderEngine memoizes `serialize_fitted` by
    fitted-id (RT double-read fix). No pandoc here: `serialize_fitted` is spied."""
    from pipeline.api import render as render_api

    calls: list[int] = []
    sentinel = ["units"]  # a stand-in for the SerializedUnit list

    def _spy(fitted_ir):
        calls.append(id(fitted_ir))
        return sentinel

    monkeypatch.setattr(render_api.serialize, "serialize_fitted", _spy)
    engine = render_api.DefaultRenderEngine()
    store = WorkspaceStore(tmp_path)  # unused by _fitted_units, required by the dataclass

    def _leg(fitted_id: str, body: str):
        return render_api.SerializeLeg(
            root=tmp_path, workspace=WS, store=store, fitted_id=fitted_id,
            fitted_ir={"body": body}, output_type="html", presentation="plain",
        )

    leg_a = _leg("fitted-A", "x")
    assert engine._fitted_units(leg_a) is sentinel
    assert engine._fitted_units(leg_a) is sentinel  # cache HIT — no second reader shell
    assert len(calls) == 1
    # a DIFFERENT fitted-id reads afresh (the key is the fitted artifact, not the engine):
    assert engine._fitted_units(_leg("fitted-B", "y")) is sentinel
    assert len(calls) == 2


def test_stored_typed_deliverable_reports_no_spurious_drift(tmp_path):
    """(A) end-to-end: the render-binding preimage of a REAL fitted typed deliverable reports NO
    spurious drift through the live `DefaultCurrencyResolver` — the C9 carry-forward fix threads
    the SD-5 `section_attr_transform_version` flag on the rebuild."""
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, workspace=WS)
    composed = _compose_conforming_ir(root)
    fit = _reconcile_at(env, composed, "journal-strict")
    _dout, serialize_preimage = _serialize_html(env, fit.fitted_ir, "journal-strict-look")
    assert "section_attr_transform_version" in serialize_preimage["tool_bundle"]  # typed

    resolver = discovery.DefaultCurrencyResolver()
    current = resolver.current_serialize_digest(
        root=root, workspace=WS, deliverable_id="d", stored_preimage=serialize_preimage
    )
    assert current == serialize_digest(serialize_preimage)  # NO spurious drift


# ---------------------------------------------------------------------------
# (A) The discovery C9 carry-forward — a focused regression proving the flag is load-bearing.
# ---------------------------------------------------------------------------

_RT = {"writer": "html5", "engine": "", "reference_doc": ""}
_RI = {"flags": ["--variable=mainfont=Georgia"], "variables": {"mainfont": "Georgia"},
       "assets": [], "engine": ""}


def test_default_currency_resolver_threads_the_section_attr_flag(tmp_path):
    resolver = discovery.DefaultCurrencyResolver()

    # A TYPED stored preimage (the transform altered bytes) mints a DIFFERENT digest than the same
    # inputs untyped — so a rebuild MUST re-derive the flag to reproduce it (the fix's whole point).
    typed = serialize_inputs_preimage(
        render_target=_RT, render_inputs=_RI, section_attr_transformed=True
    )
    untyped = serialize_inputs_preimage(
        render_target=_RT, render_inputs=_RI, section_attr_transformed=False
    )
    assert serialize_digest(typed) != serialize_digest(untyped)

    # The live resolver re-derives the flag from the stored bundle → the typed deliverable reports
    # NO spurious drift (the pre-fix rebuild omitted the key and drifted).
    current_typed = resolver.current_serialize_digest(
        root=tmp_path, workspace=WS, deliverable_id="typed", stored_preimage=typed
    )
    assert current_typed == serialize_digest(typed)

    # Control: an UNTYPED deliverable (no transform key) still reports no drift — the fix is
    # additive, never perturbing the existing SAFE-writer / non-typed corpus.
    current_untyped = resolver.current_serialize_digest(
        root=tmp_path, workspace=WS, deliverable_id="untyped", stored_preimage=untyped
    )
    assert current_untyped == serialize_digest(untyped)


# ---------------------------------------------------------------------------
# (C) The three journal looks load + lower cleanly (VISUAL only — variables + highlight_style).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "look",
    ["journal-strict-look", "journal-structured-look", "journal-concise-look"],
)
def test_journal_looks_load_and_lower_to_valid_render_inputs(tmp_path, look):
    root = _build_root(tmp_path)
    env = CascadeEnv(root, workspace=WS)
    pentry = env.resolver.resolve("presentations", look)

    def _no_asset(*_a, **_k):  # pragma: no cover — the looks declare no file assets
        raise AssertionError("no asset should be loaded for a variables-only look")

    pres = presentation_from_entry(
        {**pentry.defaults(), **pentry.effective, "id": pentry.id},
        load_asset=_no_asset,
        defaults=pentry.defaults(),
    )
    render_inputs = lower(pres, "html5", "html", target_engine="")
    mapping = render_inputs_to_mapping(render_inputs)
    # VISUAL-only: the look sets fonts (inside `variables`) + a highlight style, and NEVER a
    # render-target field — a `--variable=…` flag per scalar and one `--highlight-style=…` flag.
    assert any(f.startswith("--variable=mainfont=") for f in mapping["flags"])
    assert any(f.startswith("--highlight-style=") for f in mapping["flags"])
    assert mapping["assets"] == []  # a variables-only look pins no css/template/reference-doc
