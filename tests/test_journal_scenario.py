"""DR-4 COMMIT C10 — the driving example: one academic-paper IR, THREE journal deliverables.

Design authority: `docs/design.md` §5.2/§5.3/§12.7/§16/§17 and the FINAL RECONCILED DR-4 build
plan, COMMIT C10 (materialize the driving example with per-venue enforcement LIVE).

C1–C9 built the machinery; C10 ships the three framework venue-PROFILES (`platforms/journal-*.md`)
and their looks (`foundation/dimensions/presentations/journal-*-look.md`) and proves, over the REAL
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

DR-5 COMMIT C11 closes the DR-5 driving example ON TOP of this DR-4 structure: the three journal
looks now each declare a per-venue `csl` citation STYLE (strict → numeric `[1]`, structured →
author-date `(source)`, concise → note/footnote), shipped under
`foundation/dimensions/presentations/assets/csl/*.csl`.
`test_one_ast_three_venues_differ_by_citation_style_only` composes ONE citing `academic-paper` IR
(references PROJECTED from a two-source grounding ledger, C2/C4 — no fabrication) and renders it to
the three journal deliverables FROM ONE AST, asserting their bibliographies differ by STYLE only,
while `plain` resolves under pandoc's DEFAULT author-date CSL. The pre-existing citing tests now
render through a csl-declaring look (`journal-strict-look` → numeric), an EXPECTED style change;
non-citing renders through a csl-set look stay byte-identical to the `plain` floor (C7 S4), and the
looks' `.csl` is loaded by an INJECTED `load_asset` (the deferred §17/step-29 production loader),
so the e2e validates the actual shipped `.csl` bytes.

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
from pipeline.asset_loader import filesystem_asset_loader
from pipeline.cascade import CascadeEnv
from pipeline.compose import ComposeRequest, compose_artifact
from pipeline.dispatch import dispatch, render_target_from_entry
from pipeline.grounding import Anchor, GroundedFact
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.layout import registry_dir
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
USER = "acme"
COMMIT = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"
_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"

#: The three shipped C10 venue profiles + what each TIGHTENS on `academic-paper`.
VENUES = ("journal-strict", "journal-structured", "journal-concise")
_PANDOC_AVAILABLE = pandoc_available()

#: DR-5 C11 — the SHIPPED per-venue citation STYLE each journal look declares (its `csl` frontmatter
#: path, repo-root-relative). The venue→style map: strict → numeric (`[1]`), structured →
#: author-date (`(source)`), concise → note (footnote). Generic framework `.csl` files under
#: `foundation/dimensions/presentations/assets/csl/` (the B-3 foundation-anchored home; no
#: real-journal impersonation, no client content).
LOOK_CSL = {
    "journal-strict-look": "foundation/dimensions/presentations/assets/csl/numeric.csl",
    "journal-structured-look": "foundation/dimensions/presentations/assets/csl/author-date.csl",
    "journal-concise-look": "foundation/dimensions/presentations/assets/csl/note.csl",
}


def _load_shipped_asset(path: str) -> bytes:
    """The REFERENCE Presentation `load_asset` (DR-5 C11 → B/C1): read a SHIPPED framework asset (a
    `.csl` style) by its declared repo-root-relative path, straight off the REAL repo root. The
    production path now uses the real `filesystem_asset_loader` (fenced to `<root>/presentations`);
    this reference reader reads the SAME repo-root-relative path from `REPO_ROOT`, so the B/C1 F7
    identity test can assert the swap is ZERO-CHURN (same bytes → same csl content hash → same
    rendered bytes AND same deliverable serialize digest, §17 FR7.1)."""
    return (REPO_ROOT / path).read_bytes()


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
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2_DEFAULTS, encoding="utf-8")
    (root / "users" / USER / "zones" / "default" / "workspaces" / WS).mkdir(parents=True)
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
    store = WorkspaceStore.at(root, USER, WS, zone="default")
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


def _citing_paper_ir() -> dict:
    """A flat-body `academic-paper` IR that CITES — built through the SAME `ir.build_ir` primitive,
    carrying two `[@key]` citations + the CSL-JSON `references` they resolve against (DR-5 C6). Its
    serialized AST carries `Cite` nodes + `meta.references`; dispatch appends `--citeproc`."""
    preimage = _paper_preimage()
    return ir.build_ir(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        grounding={},
        body="Prior work established the bound; see [@s0] and [@s1].",
        references=[
            {"title": "Acme Graph", "id": "s0", "type": "webpage", "author": [{"literal": "Acme"}]},
            {"id": "s1", "type": "webpage", "title": "Beta Graph", "author": [{"literal": "Beta"}]},
        ],
    )


# ---------------------------------------------------------------------------
# DR-5 C11: genuinely COMPOSE a conforming, CITING academic-paper whose `references` are PROJECTED
# (C2) from a TWO-source grounding ledger and whose `[@key]`s RESOLVE against that projection (C4) —
# no fabrication. The conforming skeleton fits all three venues, so ONE composed AST renders to
# three journal deliverables that differ ONLY by the look's citation STYLE.
# ---------------------------------------------------------------------------

#: A conforming academic-paper skeleton (no acks, a discussion, a short abstract → fits every venue)
#: that CITES both projected pool sources `[@s0]`/`[@s1]` in Results (and grounds two EXTRACTED
#: facts via `data-fact` spans). The ONE composed body the three looks render to three STYLES.
_CITING_CONFORMING = (
    "## Abstract {#abstract}\n\nA short, scannable abstract well under the concise cap.\n\n"
    "## Methods {#methods}\n\nWhat we did, in reproducible detail.\n\n"
    '## Results {#results}\n\nWe observed a [linear-time result]{.EXTRACTED data-fact="f0"} '
    'and a [constant-space result]{.EXTRACTED data-fact="f1"}; prior work established the '
    "bounds; see [@s0] and [@s1].\n\n"
    "## Discussion {#discussion}\n\nWhat the result means, and the limits of the evidence."
)


def _beta_fact() -> GroundedFact:
    """The SECOND pool source (beta-graph) — a DISTINCT `instance_id`, so `project_references` emits
    a second reference `s1` (the sorted-instance ordinal), giving the composed body two RESOLVABLE
    `[@key]`s tied to real graphed sources (never fabricated)."""
    return GroundedFact(
        subject="cache",
        claim="uses constant space",
        instance_id="beta-graph",
        adapter="graphify",
        commit=COMMIT,
        base_tier="EXTRACTED",
        tier="EXTRACTED",
        corroboration=0,
        agreeing_instances=("beta-graph",),
        anchors=(Anchor(kind="file-line", value="src/cache.py:7"),),
        citable=True,
        as_of=datetime.date(2026, 6, 1),
        scores={"trusted": 5, "review_status": "merged", "freshness": datetime.date(2026, 6, 1)},
        weight=1.0,
        attestation=None,
    )


def _citing_paper_preimage() -> dict:
    """The `academic-paper` preimage for the C11 citing driving example — TWO pool sources in the
    subset (acme-graph + beta-graph), so the projected reference set is exactly {s0, s1}."""
    return build_artifact_preimage(
        topic=EntryBinding("x-parsing-study"),
        persona=EntryBinding("technical-evaluator"),
        format=EntryBinding("academic-paper"),
        voice=EntryBinding("clear-explainer"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph", "beta-graph"],
        source_commit={"acme-graph": COMMIT, "beta-graph": COMMIT},
    )


def _compose_citing_paper_ir(root: Path) -> dict:
    """Genuinely compose ONE conforming, CITING `academic-paper` IR over the REAL compose path (a
    faked writer, real IR mint + grounding validation + the C2 projection + the C4 `[@key]`→
    projection resolution gate). Its `references` are MACHINERY-projected from the TWO-source ledger
    (C2), and every `[@key]` in the body resolves against exactly that projected set (C4) — no
    fabrication. Returns the validated canonical IR (references == the projection; body cites)."""
    store = WorkspaceStore.at(root, USER, WS, zone="default")
    store.ensure_layout()
    claims = registry_for(store)
    preimage = _citing_paper_preimage()
    request = ComposeRequest(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        format_parts=(),
        effective_values={"voice": {"tone": "clear"}, "persona": {"knowledge_level": 3}},
        grounded_facts=(_grounded_fact(), _beta_fact()),
        source_repos={
            "acme-graph": "github.com/acme/parser",
            "beta-graph": "github.com/beta/graph",
        },
    )
    outcome = compose_artifact(
        request, store=store, claims=claims, runner=_WriterRunner(_CITING_CONFORMING)
    )
    assert outcome.status == "ok" and outcome.ir is not None, outcome
    return outcome.ir


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
    env = CascadeEnv(root, user=USER, workspace=WS)

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


def _serialize_html(env: CascadeEnv, fitted_ir: dict, presentation: str, *, load_asset=None):
    """Serialize a fitted IR to the `html` public writer through the REAL serialize leg — the SAME
    threaded sequence `driver._run_deliverable` uses (serialize_fitted -> dispatch ->
    serialize_inputs_preimage(section_attr_transformed=dout.section_attr_transformed,
    citeproc_enabled=dout.citeproc_enabled, csl=render_inputs.csl)).

    B/C1: the looks declare a `csl` STYLE asset, and `load_asset` now defaults to the REAL
    production `filesystem_asset_loader` (fenced to `<root>/presentations`, F3) — the SAME loader
    the driver + render legs wire. A caller passes `load_asset=` to compare against the reference
    reader for the F7 zero-churn identity assertion. The `csl` labeled field is threaded into the
    preimage EXACTLY as the driver does; `serialize_inputs_preimage` adds it to the `render_inputs`
    component ONLY when citeproc ran (a non-citing render through a csl-set look stays
    byte-identical to the floor, C7 S4)."""
    ast = serialize_fitted(fitted_ir)[0].ast
    target_values = driver._render_target_values(env, "html")
    target = render_target_from_entry(target_values)
    pentry = env.resolver.resolve("presentations", presentation)
    loader = load_asset or filesystem_asset_loader(
        resolve_base=env.root, contain_root=registry_dir(env.root, "presentations")
    )
    pres = presentation_from_entry(
        {**pentry.defaults(), **pentry.effective, "id": pentry.id},
        load_asset=loader,
        defaults=pentry.defaults(),
    )
    render_inputs = lower(pres, target.writer, "html", target_engine=target.engine)
    dout = dispatch(target, ast, render_inputs=render_inputs)
    serialize_preimage = serialize_inputs_preimage(
        render_target=target_values,
        render_inputs=render_inputs_to_mapping(render_inputs),
        section_attr_transformed=dout.section_attr_transformed,
        citeproc_enabled=dout.citeproc_enabled,
        csl=render_inputs.csl,
    )
    return dout, serialize_preimage


def test_fitted_typed_deliverable_renders_valid_public_bytes(tmp_path):
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
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

    # B/C1: `journal-strict-look` declares `csl`; the render engine's `_lower_for_leg` now uses the
    # REAL `filesystem_asset_loader` (fenced to `<leg.root>/presentations`), so the two-phase engine
    # lowers the real style with NO injection — the tmp world copies `presentations/` under the same
    # root. The deliverable is NON-citing, so csl never enters the preimage (this test probes SD-5).
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    fit = _reconcile_at(env, _compose_conforming_ir(root), "journal-strict")
    assert fit.status == "ok" and fit.fitted_ir is not None

    # dispatch (the reference) confirms this typed deliverable's public-writer strip fires:
    dout, _driver_preimage = _serialize_html(env, fit.fitted_ir, "journal-strict-look")
    assert dout.section_attr_transformed is True

    # the two-phase engine, WITHOUT running dispatch, must reach the SAME conclusion and record it:
    leg = SerializeLeg(
        root=root,
        user=USER,
        workspace=WS,
        store=WorkspaceStore.at(root, USER, WS, zone="default"),
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
            root=tmp_path, user=USER, workspace=WS, store=store, fitted_id=fitted_id,
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
    env = CascadeEnv(root, user=USER, workspace=WS)
    composed = _compose_conforming_ir(root)
    fit = _reconcile_at(env, composed, "journal-strict")
    _dout, serialize_preimage = _serialize_html(env, fit.fitted_ir, "journal-strict-look")
    assert "section_attr_transform_version" in serialize_preimage["tool_bundle"]  # typed

    resolver = discovery.DefaultCurrencyResolver()
    current = resolver.current_serialize_digest(
        root=root, user=USER, workspace=WS, deliverable_id="d", stored_preimage=serialize_preimage
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
        root=tmp_path, user=USER, workspace=WS, deliverable_id="typed", stored_preimage=typed
    )
    assert current_typed == serialize_digest(typed)

    # Control: an UNTYPED deliverable (no transform key) still reports no drift — the fix is
    # additive, never perturbing the existing SAFE-writer / non-typed corpus.
    current_untyped = resolver.current_serialize_digest(
        root=tmp_path, user=USER, workspace=WS, deliverable_id="untyped", stored_preimage=untyped
    )
    assert current_untyped == serialize_digest(untyped)


# ---------------------------------------------------------------------------
# (C6) A fitted CITING deliverable resolves a real bibliography + records the OMIT-WHEN-ABSENT
# `citeproc_enablement_version` (driver thread + two-phase parity + discovery no-drift, e2e).
# ---------------------------------------------------------------------------


def test_fitted_citing_deliverable_resolves_bibliography_and_records_version(tmp_path):
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)

    # The driver's threaded sequence (serialize_fitted -> dispatch -> serialize_inputs_preimage)
    # over a CITING fitted IR: dispatch appends `--citeproc`, the flag threads into the preimage.
    dout, preimage = _serialize_html(env, _citing_paper_ir(), "journal-strict-look")
    assert dout.citeproc_enabled is True
    assert "citeproc_enablement_version" in preimage["tool_bundle"]  # OMIT-WHEN-ABSENT → present

    text = dout.output_bytes.decode("utf-8")
    # C6: the `[@key]` markers are RESOLVED (fixing C5's unresolved Cites) into a bibliography Div.
    assert "[@s0]" not in text and "[@s1]" not in text
    assert 'id="refs"' in text
    assert 'id="ref-s0"' in text and 'id="ref-s1"' in text
    # DR-5 C11 — EXPECTED, NOT a regression: `journal-strict-look` now declares `csl = numeric.csl`,
    # so this citing render emits `--citeproc --csl=<numeric>` and resolves under the NUMBERED style
    # (`[1]`/`[2]`), not pandoc's default author-date. The csl STYLE asset therefore rides the
    # serialize preimage's render_inputs (citeproc ran → the S3×S4 identity gate opened, §17 FR7.1).
    assert "[1]" in text and "[2]" in text  # the numbered in-text citations of the numeric style
    assert preimage["render_inputs"]["csl"][0] == LOOK_CSL["journal-strict-look"]


def test_two_phase_render_engine_records_the_citeproc_version(tmp_path):
    """RT: `DefaultRenderEngine.serialize_preimage` runs BEFORE dispatch (two-phase), so it computes
    the C6 citeproc flag from the fitted AST itself — UNCONDITIONALLY (content-driven, not
    writer-gated). A CITING deliverable's preimage therefore records `citeproc_enablement_version`
    — the SAME conclusion dispatch reaches — so a citing standalone-API render mints an id matching
    its resolved bytes (the twin of the SD-5 two-phase parity test)."""
    _requires_pandoc()
    from pipeline.api.render import DefaultRenderEngine, SerializeLeg

    # B/C1: `journal-strict-look` declares `csl`; the render engine's `_lower_for_leg` now uses the
    # REAL fenced `filesystem_asset_loader` (no injection) — the tmp world copies `presentations/`
    # under the leg root. This deliverable CITES, so the csl STYLE asset enters the preimage's
    # render_inputs.
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    citing_ir = _citing_paper_ir()

    # dispatch (the reference) confirms this deliverable cites and appends `--citeproc`:
    dout, _driver_preimage = _serialize_html(env, citing_ir, "journal-strict-look")
    assert dout.citeproc_enabled is True

    # the two-phase engine, WITHOUT running dispatch, must reach the SAME conclusion and record it:
    leg = SerializeLeg(
        root=root,
        user=USER,
        workspace=WS,
        store=WorkspaceStore.at(root, USER, WS, zone="default"),
        fitted_id=citing_ir["binding"]["artifact_id"] + ".journal-strict.en",
        fitted_ir=citing_ir,
        output_type="html",
        presentation="journal-strict-look",
    )
    preimage = DefaultRenderEngine().serialize_preimage(leg)
    assert "citeproc_enablement_version" in preimage["tool_bundle"]
    # DR-5 C11 (S3×S4): the csl STYLE asset rides the preimage's render_inputs (citeproc ran).
    assert preimage["render_inputs"]["csl"][0] == LOOK_CSL["journal-strict-look"]


def test_stored_citing_deliverable_reports_no_spurious_drift(tmp_path):
    """(C6 carry-forward) end-to-end: the render-binding preimage of a REAL citing deliverable
    reports NO spurious drift through the live `DefaultCurrencyResolver` — the resolver re-derives
    the `citeproc_enablement_version` flag from the stored bundle on the rebuild."""
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    _dout, serialize_preimage = _serialize_html(env, _citing_paper_ir(), "journal-strict-look")
    assert "citeproc_enablement_version" in serialize_preimage["tool_bundle"]  # citing

    resolver = discovery.DefaultCurrencyResolver()
    current = resolver.current_serialize_digest(
        root=root, user=USER, workspace=WS, deliverable_id="d", stored_preimage=serialize_preimage
    )
    assert current == serialize_digest(serialize_preimage)  # NO spurious drift


def test_production_loader_is_byte_and_id_identical_to_the_reference_loader(tmp_path):
    """B/C1 (F7): swapping the deferred-then-injected `_load_shipped_asset` for the REAL production
    `filesystem_asset_loader` (fenced to `<root>/presentations`) is ZERO-CHURN — it resolves the
    SAME repo-root-relative `.csl` path to the SAME bytes, so a CITING journal render is
    BYTE-IDENTICAL and its serialize digest (the deliverable-id component) is IDENTICAL under both
    loaders. Asserted, not assumed."""
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    citing_ir = _citing_paper_ir()

    # (a) reference: read the shipped `.csl` straight off the REAL repo root.
    dout_ref, preimage_ref = _serialize_html(
        env, citing_ir, "journal-strict-look", load_asset=_load_shipped_asset
    )
    # (b) production: the REAL loader, FENCED to `<root>/presentations` (F3), reads the copied
    #     `.csl` under the tmp root (default `load_asset=None` → `_serialize_html` builds it).
    dout_real, preimage_real = _serialize_html(env, citing_ir, "journal-strict-look")

    assert dout_real.output_bytes == dout_ref.output_bytes  # byte-identical rendered deliverable
    assert serialize_digest(preimage_real) == serialize_digest(preimage_ref)  # id-identical
    # and the numeric csl STYLE really rode the preimage under BOTH loaders (citing render):
    assert preimage_real["render_inputs"]["csl"][0] == LOOK_CSL["journal-strict-look"]
    assert preimage_ref["render_inputs"]["csl"][0] == LOOK_CSL["journal-strict-look"]


# ---------------------------------------------------------------------------
# (B) The DefaultRenderEngine leg EMBEDS a body figure end-to-end (two-phase: the preimage folds
# the figure by content-hash; mint_deliverable inlines it), and the stored embedded deliverable
# reports NO phantom drift through the live currency resolver (F2). Reuses the real registries.
# ---------------------------------------------------------------------------

_EMBED_PNG = __import__("base64").b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _embed_leg(root, fitted_ir, *, body_png=_EMBED_PNG):
    """A SerializeLeg for a figure-bearing html render on the real registries, with the figure at
    `store.root/assets/x.png` and a persisted fit record so `mint_deliverable` can read its ref."""
    from pipeline.api.render import SerializeLeg
    from pipeline.reconcile import build_fit_binding

    store = WorkspaceStore.at(root, USER, WS, zone="default")
    store.ensure_layout()
    (store.root / "assets").mkdir(parents=True, exist_ok=True)
    (store.root / "assets" / "x.png").write_bytes(body_png)
    fb = build_fit_binding(
        artifact_id="a-0123456789abcdef",
        platform="linkedin",
        language="en",
        preimage={"strategy": {}, "hard-limits": {}, "advisory": {}, "render-dims": {}},
        strategy="pass",
        localize_languages=[],
        gate_outcome="ok",
        revision=False,
        minted_ts="2026-01-01T00:00:00+00:00",
    )
    store.output_path(fb["fitted_id"]).parent.mkdir(parents=True, exist_ok=True)
    store.output_path(fb["fitted_id"]).write_bytes(
        (json.dumps({"ir": {"body": "x"}, "binding": fb}) + "\n").encode()
    )
    return SerializeLeg(
        root=root,
        user=USER,
        workspace=WS,
        store=store,
        fitted_id=fb["fitted_id"],
        fitted_ir=fitted_ir,
        output_type="html",
        presentation="plain",
    )


def test_default_render_engine_embeds_a_body_figure_end_to_end(tmp_path):
    """B end-to-end through the REAL render leg: an html render of a figure body folds the figure
    by content-hash into the preimage AND inlines it in the minted bytes; editing the figure bytes
    re-mints the deliverable-id; and the stored embedded deliverable reports NO phantom drift."""
    _requires_pandoc()
    from pipeline.api.render import DefaultRenderEngine

    root = _build_root(tmp_path)
    fitted_ir = {"grounding": {}, "body": "![alt text](assets/x.png)"}
    engine = DefaultRenderEngine()

    leg = _embed_leg(root, fitted_ir)
    preimage = engine.serialize_preimage(leg)
    assert "asset_embed_version" in preimage["tool_bundle"]  # the embed pin rode the identity
    assert preimage["render_inputs"]["embedded_assets"][0][0] == "assets/x.png"

    mint = engine.mint_deliverable(leg, preimage=preimage, serialize_revision=False)
    assert mint.side == "internal"
    assert b'src="data:image/png;base64,' in mint.output_bytes  # the figure is INLINED
    assert str(leg.store.root).encode() not in mint.output_bytes  # no absolute path leak

    # F2: the live currency resolver reports NO phantom drift for the picture-bearing deliverable.
    resolver = discovery.DefaultCurrencyResolver()
    current = resolver.current_serialize_digest(
        root=root, user=USER, workspace=WS, deliverable_id="pic", stored_preimage=preimage
    )
    assert current == serialize_digest(preimage)

    # Editing the figure bytes re-mints the html deliverable-id (honest identity). The fold reads
    # the figure fresh, so rewriting the SAME path's bytes changes the preimage digest (same AST).
    edited_png = _EMBED_PNG[:-1] + bytes([_EMBED_PNG[-1] ^ 0xFF])
    (leg.store.root / "assets" / "x.png").write_bytes(edited_png)
    preimage2 = engine.serialize_preimage(leg)
    assert serialize_digest(preimage2) != serialize_digest(preimage)


# ---------------------------------------------------------------------------
# (C) The three journal looks load + lower cleanly (variables + highlight_style + C11 csl style).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "look",
    ["journal-strict-look", "journal-structured-look", "journal-concise-look"],
)
def test_journal_looks_load_and_lower_to_valid_render_inputs(tmp_path, look):
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)
    pentry = env.resolver.resolve("presentations", look)

    pres = presentation_from_entry(
        {**pentry.defaults(), **pentry.effective, "id": pentry.id},
        # B/C1: load the `csl` STYLE asset through the REAL production loader (fenced to
        # `<root>/presentations`) — the tmp world copies the shipped `.csl` under that fence.
        load_asset=filesystem_asset_loader(
            resolve_base=root, contain_root=registry_dir(root, "presentations")
        ),
        defaults=pentry.defaults(),
    )
    render_inputs = lower(pres, "html5", "html", target_engine="")
    mapping = render_inputs_to_mapping(render_inputs)
    # VISUAL: the look sets fonts (inside `variables`) + a highlight style, and NEVER a
    # render-target field — a `--variable=…` flag per scalar and one `--highlight-style=…` flag.
    assert any(f.startswith("--variable=mainfont=") for f in mapping["flags"])
    assert any(f.startswith("--highlight-style=") for f in mapping["flags"])
    # DR-5 C11: `csl` is the α LABELED field — it pins NO css/template/reference-doc asset (so
    # `assets` stays empty) and emits NO `--csl` flag in `lower` (dispatch content-gates it WITH
    # `--citeproc`); `render_inputs_to_mapping` OMITS it (it enters the preimage only when citeproc
    # ran). The lowered `RenderInputs.csl` labeled field carries the style this look declares.
    assert mapping["assets"] == []  # a csl-set look still pins no css/template/reference-doc asset
    assert "csl" not in mapping  # the labeled field is omitted from the base render_inputs mapping
    assert render_inputs.csl is not None
    assert render_inputs.csl[0] == LOOK_CSL[look]  # the venue→style map, resolved from the entry


# ---------------------------------------------------------------------------
# (D) DR-5 C11 — the driving example CLOSED: ONE composed citing AST → THREE journal deliverables
# that differ ONLY by citation STYLE (numeric / author-date / note) + `plain`'s default author-date.
# ---------------------------------------------------------------------------


def test_one_ast_three_venues_differ_by_citation_style_only(tmp_path):
    """DR-5 C11 (the driving example): ONE composed `academic-paper` IR — references PROJECTED from
    a two-source grounding ledger (C2), every `[@key]` resolved against that projection (C4), NO
    fabrication — reconciles + serializes to the THREE shipped journal deliverables whose
    bibliographies DIFFER by STYLE only (strict → numeric `[1]`, structured → author-date, concise
    → note/footnote), FROM ONE AST; `plain` resolves under pandoc's DEFAULT author-date CSL. The
    `.csl` styles are the ACTUAL shipped framework files (injected `load_asset`). Real pandoc."""
    _requires_pandoc()
    root = _build_root(tmp_path)
    env = CascadeEnv(root, user=USER, workspace=WS)

    composed = _compose_citing_paper_ir(root)

    # C2/C4 — NO fabrication: the composed `references` ARE exactly the projected pool-source set,
    # each an HONEST per-source descriptor (a graphed pool source titled by its instance-id, not an
    # authored citation) — so every `[@key]` the body cites points at a work the pipeline grounded.
    refs = {r["id"]: r for r in composed["references"]}
    assert set(refs) == {"s0", "s1"}  # exactly the two DISTINCT projected pool sources
    assert refs["s0"]["title"] == "acme-graph" and refs["s1"]["title"] == "beta-graph"
    assert all(r["type"] == "software" for r in refs.values())  # projected descriptor, not authored

    # ONE composed AST → three journal deliverables (one per look) + the `plain` floor. The
    # conforming skeleton fits every venue (pass strategy), so all four render from structurally
    # IDENTICAL ASTs; the ONLY per-venue difference is the look's `csl` citation STYLE.
    renders: dict[str, str] = {}
    csl_hashes: dict[str, str] = {}
    for venue, look in (
        ("journal-strict", "journal-strict-look"),
        ("journal-structured", "journal-structured-look"),
        ("journal-concise", "journal-concise-look"),
    ):
        fit = _reconcile_at(env, composed, venue)
        assert fit.status == "ok" and fit.fitted_ir is not None, (venue, fit.status)
        dout, preimage = _serialize_html(env, fit.fitted_ir, look)
        assert dout.citeproc_enabled is True  # content-driven: the body cites (C6)
        renders[look] = dout.output_bytes.decode("utf-8")
        # each look rides its OWN csl STYLE asset; its content hash enters the preimage (citeproc
        # ran, so the S3×S4 identity gate opened) — a citing journal id differs by the presentation
        # slug + this csl hash (§17 FR7.1).
        assert preimage["render_inputs"]["csl"][0] == LOOK_CSL[look]
        csl_hashes[look] = preimage["render_inputs"]["csl"][1]

    # `plain` (the floor): no csl → pandoc's DEFAULT author-date CSL resolves the SAME projection.
    fit_plain = _reconcile_at(env, composed, "journal-strict")
    dout_plain, preimage_plain = _serialize_html(env, fit_plain.fitted_ir, "plain")
    renders["plain"] = dout_plain.output_bytes.decode("utf-8")
    assert "csl" not in preimage_plain["render_inputs"]  # the floor pins no style

    strict = renders["journal-strict-look"]  # numeric
    structured = renders["journal-structured-look"]  # author-date
    concise = renders["journal-concise-look"]  # note
    plain = renders["plain"]  # pandoc default author-date

    # EVERY `[@key]` RESOLVED to a PROJECTED reference at EVERY venue — no unresolved marker
    # survives, and BOTH projected refs render — the SAME AST + SAME projection, four styles.
    for text in (strict, structured, concise, plain):
        assert "[@s0]" not in text and "[@s1]" not in text
        assert 'id="ref-s0"' in text and 'id="ref-s1"' in text

    # The THREE journal deliverables DIFFER by citation STYLE only:
    #  · strict = NUMERIC: bracketed ordinals `[1]`/`[2]`, no footnotes.
    assert "[1]" in strict and "[2]" in strict
    assert "footnote-ref" not in strict
    #  · structured = AUTHOR-DATE: parenthetical source labels, no numbered brackets, no footnotes.
    assert "(acme-graph)" in structured and "(beta-graph)" in structured
    assert "[1]" not in structured and "footnote-ref" not in structured
    #  · concise = NOTE: superscript footnote markers + an end-of-document footnotes section.
    assert 'class="footnote-ref"' in concise and 'id="footnotes"' in concise
    #  · plain = pandoc's DEFAULT author-date CSL: "n.d." (no projected date) — distinct from ours.
    assert "n.d." in plain

    # From ONE AST, the four rendered documents are pairwise DISTINCT — the citation STYLE is the
    # sole axis of difference (the looks' fonts/highlight ride template variables a fragment
    # `-t html5` render does not apply, so ONLY the csl-driven citation markup varies)…
    assert len({strict, structured, concise, plain}) == 4
    # …and the three journal styles are three DISTINCT shipped `.csl` files (distinct hashes).
    assert len(set(csl_hashes.values())) == 3
