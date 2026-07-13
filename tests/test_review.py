"""Step-30 tests: `pipeline/review.py` + the compose/dispatch/driver review wiring (§19).

Transport is MOCKED throughout — every test injects a fake `Runner` (a `ScriptedRunner`
returning canned `ProcessOutcome`s) or a `NeverRunner`; NO real `claude` process is spawned.
Covers, per the acceptance list:

- Review 1 (artifact) runs ONCE per artifact, and a forced re-fit does NOT re-run it;
- Review 2 (deliverable) runs FULL on EVERY deliverable, INCLUDING every revision;
- review records are per-id, IMMUTABLE (a second write to the same reviewed-id is refused),
  and id-addressed under `reviews/`, NEVER transferred across revisions;
- a review NEVER mutates the content-addressed output (the artifact/deliverable bytes and
  records are byte-unchanged after a review — the only new file is under `reviews/`);
- the SSOT statuses advance to `artifact-reviewed` / `deliverable-reviewed`, STATUS ONLY;
- reviews are ADVISORY: a malformed reviewer / transport failure produces no record and no
  advance, never a block.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest

from pipeline import ir
from pipeline.adapters.base import Anchor
from pipeline.canonical import canonical_json_bytes
from pipeline.claims import ClaimRegistry
from pipeline.compose import ComposeRequest, compose_artifact
from pipeline.dispatch import review_deliverable
from pipeline.grounding import GroundedFact
from pipeline.ids import (
    EntryBinding,
    build_artifact_preimage,
    deliverable_id,
    fitted_id,
    mint_artifact_id,
)
from pipeline.review import (
    ARTIFACT_CHECKS,
    CODE_ALREADY_REVIEWED,
    CODE_CONTRACT_VIOLATION,
    CODE_REVIEWED,
    DELIVERABLE_CHECKS,
    REVIEW_RECORD_FIELDS,
    ReviewSchemaViolation,
    build_review_record,
    parse_review_output,
    persist_review_record,
    review_artifact,
    validate_review_record,
)
from pipeline.ssot import Ssot
from pipeline.store import WorkspaceStore, write_new
from pipeline.transport import ProcessOutcome, ProcessRequest

COMMIT = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"


# --- the mocked transport seam (mirrors tests/test_compose.py) ------------------------------


def _result_envelope(result_text: str) -> str:
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


def ok_outcome(result_text: str) -> ProcessOutcome:
    return ProcessOutcome(
        timed_out=False, returncode=0, stdout=_result_envelope(result_text), stderr=""
    )


def review_ok(assessment: dict) -> ProcessOutcome:
    """A successful transport call whose `.result` is the reviewer's JSON assessment string."""
    return ok_outcome(json.dumps(assessment))


def backpressure_outcome() -> ProcessOutcome:
    env = json.dumps(
        {"type": "result", "is_error": True, "terminal_reason": "api_error",
         "errors": ["rate limit exceeded"]}
    )
    return ProcessOutcome(timed_out=False, returncode=1, stdout=env, stderr="")


class ScriptedRunner:
    """A fake `Runner`: returns programmed `ProcessOutcome`s in order (last one repeats),
    recording every `ProcessRequest`."""

    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.requests: list[ProcessRequest] = []

    @property
    def calls(self) -> int:
        return len(self.requests)

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self._outcomes) - 1)
        return self._outcomes[index]


class NeverRunner:
    """A fake `Runner` that must never be invoked (the idempotent / already-reviewed paths)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:  # pragma: no cover
        self.calls += 1
        raise AssertionError("the review transport must not be invoked on this path")


# --- assessment + IR builders --------------------------------------------------------------


def artifact_assessment(verdict: str = "pass") -> dict:
    return {
        "verdict": verdict,
        "checks": {c: {"status": "pass", "note": "ok"} for c in ARTIFACT_CHECKS},
        "summary": "reads well and is grounded",
    }


def deliverable_assessment(verdict: str = "pass") -> dict:
    return {
        "verdict": verdict,
        "checks": {c: {"status": "pass", "note": "ok"} for c in DELIVERABLE_CHECKS},
        "summary": "fits the platform and preserves provenance",
    }


def make_preimage() -> dict:
    return build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("readme"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT},
    )


def make_ledger() -> dict:
    return {
        "f0": {
            "tier": "EXTRACTED",
            "source_instance_id": "acme-graph",
            "source_repo": "github.com/acme/widget",
            "source_commit": COMMIT,
            "traceability_anchor": ["file-line:src/parser.py:42"],
            "scores_snapshot": {},
        }
    }


def make_ir(body: str = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'):
    preimage = make_preimage()
    aid = mint_artifact_id(preimage)
    doc = ir.build_ir(artifact_id=aid, preimage=preimage, grounding=make_ledger(), body=body)
    return aid, doc


def make_ast() -> dict:
    """A minimal-but-realistic layer-3 AST carrying one provenance Span (§17 RI8) — no pandoc
    binary needed; the deliverable review only walks it for the provenance fingerprint."""
    return {
        "pandoc-api-version": [1, 23, 1, 2],
        "meta": {},
        "blocks": [
            {
                "t": "Para",
                "c": [
                    {
                        "t": "Span",
                        "c": [
                            ["", ["EXTRACTED"], [["data-fact", "f0"]]],
                            [{"t": "Str", "c": "claim"}],
                        ],
                    }
                ],
            }
        ],
    }


def make_fact(tier: str = "EXTRACTED") -> GroundedFact:
    return GroundedFact(
        subject="parser",
        claim="runs in linear time",
        instance_id="acme-graph",
        adapter="graphify",
        commit=COMMIT,
        base_tier=tier,
        tier=tier,
        corroboration=0,
        agreeing_instances=("acme-graph",),
        anchors=(Anchor(kind="file-line", value="src/parser.py:42"),),
        citable=True,
        as_of=None,
        scores={"trusted": 5},
        weight=1.0,
    )


def make_request() -> ComposeRequest:
    preimage = make_preimage()
    return ComposeRequest(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        format_parts=(),
        effective_values={"voice": {"tone": "business"}, "persona": {"knowledge_level": 3}},
        grounded_facts=(make_fact(),),
        source_repos={"acme-graph": "github.com/acme/widget"},
    )


# --- helpers -------------------------------------------------------------------------------


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file under `root` → its bytes (for a byte-exact no-mutation proof)."""
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def row_status(csv_path: Path, id_str: str) -> str | None:
    text = Path(csv_path).read_bytes().decode("utf-8")
    reader = csv.reader(io.StringIO(text, newline=""))
    header = next(reader)
    for record in reader:
        row = dict(zip(header, record, strict=True))
        if row["id"] == id_str:
            return row["status"]
    return None


@pytest.fixture
def store(tmp_path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "ws")


@pytest.fixture
def claims(store) -> ClaimRegistry:
    return ClaimRegistry(
        store.claims_dir, holder="worker-a", ttl_seconds=60.0, clock=lambda: 1_000_000.0
    )


def make_deliverable_id(aid: str, *, fit_revision: str | None = None) -> str:
    fit = fitted_id(aid, "github", "en", fit_revision=fit_revision)
    return deliverable_id(fit, "md", "plain")


# --- review.py direct: immutable, id-addressed, per-id records -----------------------------


class TestReviewRecordPersistence:
    def test_artifact_review_produces_immutable_id_addressed_record(self, store):
        aid, doc = make_ir()
        runner = ScriptedRunner([review_ok(artifact_assessment())])
        outcome = review_artifact(store=store, artifact_id=aid, ir_doc=doc, runner=runner)
        assert (outcome.status, outcome.code, outcome.attempts) == ("ok", CODE_REVIEWED, 1)
        assert outcome.persisted and outcome.verdict == "pass"
        # id-addressed under reviews/, keyed by the reviewed id EXACTLY.
        path = store.review_path(aid)
        assert path.exists() and path.parent == store.reviews_dir and path.name == aid
        record = json.loads(path.read_bytes())
        validate_review_record(record)
        assert record["review_type"] == "artifact"
        assert record["reviewed_id"] == aid
        assert record["reviewed_digest"] == doc["binding"]["digest"]  # bound to the exact content
        assert set(record) == set(REVIEW_RECORD_FIELDS)

    def test_review_runs_once_and_is_idempotent(self, store):
        aid, doc = make_ir()
        first = review_artifact(
            store=store, artifact_id=aid, ir_doc=doc,
            runner=ScriptedRunner([review_ok(artifact_assessment())]),
        )
        assert first.code == CODE_REVIEWED
        before = store.review_path(aid).read_bytes()
        # A second review of the SAME id: the record exists → ZERO LLM (NeverRunner), no rewrite.
        never = NeverRunner()
        second = review_artifact(store=store, artifact_id=aid, ir_doc=doc, runner=never)
        assert (second.code, second.attempts, second.persisted) == (CODE_ALREADY_REVIEWED, 0, True)
        assert never.calls == 0
        assert store.review_path(aid).read_bytes() == before  # byte-identical — never overwritten

    def test_second_write_to_same_id_is_refused_even_with_different_content(self, store):
        aid, doc = make_ir()
        digest = doc["binding"]["digest"]
        rec1 = build_review_record(
            review_type="artifact", reviewed_id=aid, reviewed_digest=digest,
            assessment=artifact_assessment("pass"),
        )
        assert persist_review_record(store, rec1) is True
        before = store.review_path(aid).read_bytes()
        rec2 = build_review_record(
            review_type="artifact", reviewed_id=aid, reviewed_digest=digest,
            assessment=artifact_assessment("concerns"),  # DIFFERENT content
        )
        assert persist_review_record(store, rec2) is False  # no-replace commit refused it
        assert store.review_path(aid).read_bytes() == before  # the first record is untouched


# --- review NEVER mutates the content-addressed output -------------------------------------


class TestReviewNeverMutatesOutput:
    def test_artifact_review_only_adds_a_reviews_file(self, store):
        aid, doc = make_ir()
        write_new(store.output_path(aid), canonical_json_bytes(doc))  # the persisted artifact
        before = snapshot(store.root)
        review_artifact(
            store=store, artifact_id=aid, ir_doc=doc,
            runner=ScriptedRunner([review_ok(artifact_assessment())]),
        )
        after = snapshot(store.root)
        added = set(after) - set(before)
        assert added and all(k.startswith("reviews/") for k in added)  # ONLY a reviews/ file
        for key in set(before) & set(after):
            assert before[key] == after[key]  # every pre-existing file byte-unchanged

    def test_deliverable_review_only_adds_a_reviews_file(self, store):
        aid, doc = make_ir()
        did = make_deliverable_id(aid)
        # a pre-existing deliverable byte output + its record, to prove they are untouched.
        write_new(store.bytes_path(did, "md"), b"# rendered bytes\n")
        before = snapshot(store.root)
        review_deliverable(
            store=store, deliverable_id=did, fitted_ir=doc, ast=make_ast(),
            hard_limits={"max_chars": 10_000},
            review_runner=ScriptedRunner([review_ok(deliverable_assessment())]),
        )
        after = snapshot(store.root)
        added = set(after) - set(before)
        assert added and all(k.startswith("reviews/") for k in added)
        for key in set(before) & set(after):
            assert before[key] == after[key]


# --- Review 2 runs FULL on EVERY deliverable, per-id, never transferred across revisions ----


class TestDeliverableReviewPerRevision:
    def test_every_revision_deliverable_takes_its_own_full_review(self, store):
        aid, doc = make_ir()
        base_did = make_deliverable_id(aid)
        rev_did = make_deliverable_id(aid, fit_revision="abc123def456")  # a forced-refit revision
        assert base_did != rev_did

        runner = ScriptedRunner([review_ok(deliverable_assessment())])
        out_base = review_deliverable(
            store=store, deliverable_id=base_did, fitted_ir=doc, ast=make_ast(),
            review_runner=runner,
        )
        out_rev = review_deliverable(
            store=store, deliverable_id=rev_did, fitted_ir=doc, ast=make_ast(),
            review_runner=runner,
        )
        # A FULL review ran for BOTH — the revision did NOT inherit the baseline's record.
        assert (out_base.code, out_rev.code) == (CODE_REVIEWED, CODE_REVIEWED)
        assert runner.calls == 2  # every deliverable is reviewed, revisions included
        base_rec = json.loads(store.review_path(base_did).read_bytes())
        rev_rec = json.loads(store.review_path(rev_did).read_bytes())
        assert base_rec["reviewed_id"] == base_did and rev_rec["reviewed_id"] == rev_did
        assert base_rec["reviewed_id"] != rev_rec["reviewed_id"]  # per-id, never transferred


# --- Review is ADVISORY: malformed / transport failure → no record, no block ---------------


class TestReviewIsAdvisory:
    def test_malformed_reviewer_is_reasked_then_not_persisted(self, store):
        aid, doc = make_ir()
        runner = ScriptedRunner([ok_outcome("not json at all")])  # repeats — always malformed
        outcome = review_artifact(
            store=store, artifact_id=aid, ir_doc=doc, runner=runner, max_attempts=3
        )
        assert (outcome.status, outcome.code) == ("error", CODE_CONTRACT_VIOLATION)
        assert runner.calls == 3 and len(outcome.violations) == 3  # bounded re-ask
        assert not outcome.persisted and not store.review_path(aid).exists()

    def test_transport_failure_surfaces_and_is_not_persisted(self, store):
        aid, doc = make_ir()
        runner = ScriptedRunner([backpressure_outcome()])
        outcome = review_artifact(store=store, artifact_id=aid, ir_doc=doc, runner=runner)
        assert outcome.status == "error" and outcome.code == "rate-limit-backpressure"
        assert runner.calls == 1  # NOT re-asked — an account-side condition
        assert not outcome.persisted and not store.review_path(aid).exists()

    def test_wrong_check_set_and_bad_verdict_are_rejected(self):
        with pytest.raises(ReviewSchemaViolation):
            parse_review_output(json.dumps({"verdict": "pass", "checks": {}, "summary": ""}),
                                checks=ARTIFACT_CHECKS)
        bad_verdict = artifact_assessment()
        bad_verdict["verdict"] = "blocked"  # not in the advisory vocabulary
        with pytest.raises(ReviewSchemaViolation):
            parse_review_output(json.dumps(bad_verdict), checks=ARTIFACT_CHECKS)

    def test_secret_shaped_note_is_refused(self, store):
        aid, doc = make_ir()
        leaky = artifact_assessment()
        leaky["checks"]["grounding"]["note"] = "leaked sk-live-0123456789abcdefghijklmn"
        runner = ScriptedRunner([review_ok(leaky)])
        outcome = review_artifact(
            store=store, artifact_id=aid, ir_doc=doc, runner=runner, max_attempts=2
        )
        assert outcome.status == "error" and outcome.code == CODE_CONTRACT_VIOLATION
        assert not store.review_path(aid).exists()  # a secret-bearing record never persisted


# --- compose wiring: Review 1 once, post-mint, advances SSOT to artifact-reviewed ----------


class TestComposeReviewWiring:
    def test_compose_runs_review1_and_advances_ssot(self, store, claims, tmp_path):
        request = make_request()
        ssot = Ssot(tmp_path / "ssot.csv")
        ssot.register(request.artifact_id, "artifact", coordinates="c", output_path="p")
        writer = ScriptedRunner(
            [review_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]  # writer JSON
        )
        reviewer = ScriptedRunner([review_ok(artifact_assessment())])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=writer,
            advance=ssot.advance_hook("composed"),
            review_runner=reviewer,
            review_advance=ssot.advance_hook("artifact-reviewed"),
        )
        assert outcome.status == "ok"
        assert outcome.review is not None and outcome.review.code == CODE_REVIEWED
        assert reviewer.calls == 1  # Review 1 ran exactly once
        assert store.review_path(request.artifact_id).exists()
        assert row_status(ssot.csv_path, request.artifact_id) == "artifact-reviewed"

    def test_recompose_does_not_rerun_review1(self, store, claims, tmp_path):
        request = make_request()
        ssot = Ssot(tmp_path / "ssot.csv")
        ssot.register(request.artifact_id, "artifact", coordinates="c", output_path="p")
        compose_artifact(
            request, store=store, claims=claims,
            runner=ScriptedRunner([review_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]),
            advance=ssot.advance_hook("composed"),
            review_runner=ScriptedRunner([review_ok(artifact_assessment())]),
            review_advance=ssot.advance_hook("artifact-reviewed"),
        )
        review_bytes = store.review_path(request.artifact_id).read_bytes()
        # Re-compose the SAME (already-materialized) artifact: writer AND reviewer must NOT run.
        never_write, never_review = NeverRunner(), NeverRunner()
        second = compose_artifact(
            request, store=store, claims=claims, runner=never_write,
            advance=ssot.advance_hook("composed"),
            review_runner=never_review,
            review_advance=ssot.advance_hook("artifact-reviewed"),
        )
        assert never_write.calls == 0 and never_review.calls == 0
        assert second.review is not None and second.review.code == CODE_ALREADY_REVIEWED
        assert store.review_path(request.artifact_id).read_bytes() == review_bytes  # unchanged

    def test_compose_without_review_wiring_is_unchanged(self, store, claims):
        request = make_request()
        outcome = compose_artifact(
            request, store=store, claims=claims,
            runner=ScriptedRunner([review_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]),
        )
        assert outcome.status == "ok" and outcome.review is None  # review OFF by default
        assert not store.review_path(request.artifact_id).exists()


# --- dispatch wiring: Review 2 advances SSOT to deliverable-reviewed -----------------------


class TestDispatchReviewWiring:
    def test_review_deliverable_advances_ssot(self, store, tmp_path):
        aid, doc = make_ir()
        did = make_deliverable_id(aid)
        ssot = Ssot(tmp_path / "ssot.csv")
        ssot.register(did, "deliverable", coordinates="github/en/md/plain", output_path="p")
        ssot.advance(did, "fitted")
        ssot.advance(did, "rendered")  # the render S5 got it here; the review advances past it
        outcome = review_deliverable(
            store=store, deliverable_id=did, fitted_ir=doc, ast=make_ast(),
            hard_limits={"max_chars": 10_000},
            review_runner=ScriptedRunner([review_ok(deliverable_assessment())]),
            review_advance=ssot.advance_hook("deliverable-reviewed"),
        )
        assert outcome.code == CODE_REVIEWED and outcome.verdict == "pass"
        assert row_status(ssot.csv_path, did) == "deliverable-reviewed"


# --- the headline invariant: a forced re-fit does NOT re-run Review 1, and every -----------
#     revision deliverable takes a FULL Review 2 ---------------------------------------------


class TestForcedRefitReviewInvariant:
    def test_forced_refit_does_not_rerun_review1_but_runs_full_review2(self, store, claims):
        request = make_request()
        aid = request.artifact_id
        # 1. Compose the artifact once WITH Review 1 wiring.
        reviewer1 = ScriptedRunner([review_ok(artifact_assessment())])
        compose_artifact(
            request, store=store, claims=claims,
            runner=ScriptedRunner([review_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]),
            review_runner=reviewer1,
            review_advance=lambda _id: None,  # advance is exercised elsewhere; count calls here
        )
        assert reviewer1.calls == 1  # Review 1 ran exactly once for this artifact

        # 2. A forced re-fit renders a NEW deliverable (a distinct `_hex12` revision id) — it
        #    goes through reconcile + the deliverable review, NEVER through compose/Review 1.
        _, fitted_doc = make_ir()  # a valid fitted IR (same-shape) for the render leg
        base_did = make_deliverable_id(aid)
        rev_did = make_deliverable_id(aid, fit_revision="0f1e2d3c4b5a")
        reviewer2 = ScriptedRunner([review_ok(deliverable_assessment())])
        for did in (base_did, rev_did):
            out = review_deliverable(
                store=store, deliverable_id=did, fitted_ir=fitted_doc, ast=make_ast(),
                review_runner=reviewer2,
            )
            assert out.code == CODE_REVIEWED  # a FULL Review 2 for each, revision included

        # 3. The forced re-fit + its Review 2 NEVER re-ran Review 1.
        assert reviewer1.calls == 1
        assert reviewer2.calls == 2  # one FULL Review 2 per deliverable (baseline + revision)
        # per-id records, never transferred across the revision.
        assert store.review_path(base_did).exists() and store.review_path(rev_did).exists()
        assert store.review_path(aid).exists()  # the single Review 1 record, on the artifact-id
