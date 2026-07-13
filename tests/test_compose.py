"""Step-24 tests: `pipeline/compose.py` — the writer stage, transport MOCKED.

Every test injects a fake `Runner` (a `ScriptedRunner` returning canned `ProcessOutcome`s)
— NO real `claude` process is spawned, no real LLM call is made (durable rule: tests mock
transport). Covers, per the acceptance list:

- a valid writer output is composed + PERSISTED via a spine claim on the artifact-id (§22.3),
  for both the flat single-part and the multi-part shapes;
- a VIOLATING writer output (schema-invalid JSON / unknown fact-id / a non-EXTRACTED lead
  asserted as EXTRACTED) is caught by the gate, re-asked up to the bound, and NEVER persisted;
- a writer that FIXES itself within the bound is persisted (attempt count observed);
- a TRANSPORT-level failure (backpressure) is surfaced immediately, not re-asked, not persisted;
- **roster is compose CONTEXT, not identity** (§9.6): two requests differing only in roster
  share the artifact-id and produce byte-identical composition bindings, and the roster never
  appears in the persisted IR — while the PROMPT carries it;
- idempotency (§21.8): re-composing an existing artifact skips the writer entirely;
- a secret-shaped grounded value aborts LOUDLY before any LLM call (§3.3); a missing
  source_repo is a loud wiring defect;
- the A2 non-repo cwd: the headless child's cwd is a dedicated dir outside the repo tree.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from pipeline.adapters.base import Anchor
from pipeline.claims import ClaimRegistry
from pipeline.compose import (
    CODE_CONTRACT_VIOLATION,
    ComposeError,
    ComposeRequest,
    build_grounding_ledger,
    build_writer_prompt,
    compose_artifact,
)
from pipeline.grounding import GroundedFact
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.ir import SecretShapedValueError, validate_ir
from pipeline.store import WorkspaceStore
from pipeline.transport import ProcessOutcome, ProcessRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT_SHA = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"


# --- the mocked transport seam -------------------------------------------------------------


def _result_envelope(result_text: str) -> str:
    """The step-04 success envelope shape, trimmed to the fields transport reads."""
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


def writer_ok(content: dict) -> ProcessOutcome:
    """A successful transport call whose `.result` is the writer's JSON content string."""
    return ok_outcome(json.dumps(content))


def backpressure_outcome() -> ProcessOutcome:
    env = json.dumps(
        {
            "type": "result",
            "is_error": True,
            "terminal_reason": "api_error",
            "errors": ["rate limit exceeded"],
        }
    )
    return ProcessOutcome(timed_out=False, returncode=1, stdout=env, stderr="")


class ScriptedRunner:
    """A fake `Runner`: returns programmed `ProcessOutcome`s in order (last one repeats),
    recording every `ProcessRequest` for prompt/cwd inspection."""

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
    """A fake `Runner` that must never be invoked (the idempotent / abort-before-LLM paths)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:  # pragma: no cover
        self.calls += 1
        raise AssertionError("the writer transport must not be invoked on this path")


# --- fixtures + builders -------------------------------------------------------------------


def make_fact(
    *, subject="parser", claim="runs in linear time", tier="EXTRACTED", instance="acme-graph"
):
    return GroundedFact(
        subject=subject,
        claim=claim,
        instance_id=instance,
        adapter="graphify",
        commit=COMMIT_SHA,
        base_tier=tier,
        tier=tier,
        corroboration=0,
        agreeing_instances=(instance,),
        anchors=(Anchor(kind="file-line", value="src/parser.py:42"),),
        citable=True,
        as_of=datetime.date(2026, 6, 1),
        scores={"trusted": 5, "review_status": "merged", "freshness": datetime.date(2026, 6, 1)},
        weight=1.0,
    )


def make_preimage() -> dict:
    return build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("readme"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
    )


def make_request(**overrides) -> ComposeRequest:
    preimage = make_preimage()
    base = {
        "artifact_id": mint_artifact_id(preimage),
        "preimage": preimage,
        "format_parts": (),
        "effective_values": {"voice": {"tone": "business"}, "persona": {"knowledge_level": 3}},
        "grounded_facts": (make_fact(),),
        "source_repos": {"acme-graph": "github.com/acme/widget"},
    }
    base.update(overrides)
    return ComposeRequest(**base)


@pytest.fixture
def store(tmp_path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "ws")


@pytest.fixture
def claims(store) -> ClaimRegistry:
    return ClaimRegistry(
        store.claims_dir, holder="worker-a", ttl_seconds=60.0, clock=lambda: 1_000_000.0
    )


# --- valid compose persists ----------------------------------------------------------------


class TestValidComposePersists:
    def test_flat_artifact_is_composed_and_persisted(self, store, claims):
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.code, outcome.attempts) == ("ok", "ok", 1)
        assert outcome.ir is not None and "body" in outcome.ir
        target = store.output_path(request.artifact_id)
        assert target.exists()
        persisted = json.loads(target.read_bytes())
        validate_ir(persisted)
        assert persisted["binding"]["artifact_id"] == request.artifact_id
        assert persisted["grounding"]["f0"]["source_repo"] == "github.com/acme/widget"

    def test_multi_part_artifact_is_composed_and_persisted(self, store, claims):
        request = make_request(format_parts=("slides", "presenter-notes"))
        runner = ScriptedRunner(
            [
                writer_ok(
                    {
                        "parts": {
                            "slides": '# Deck\n\n- [linear time]{.EXTRACTED data-fact="f0"}',
                            "presenter-notes": "Speaker notes, ungrounded prose.",
                        }
                    }
                )
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        assert [p["role"] for p in persisted["parts"]] == ["slides", "presenter-notes"]

    def test_writer_that_fixes_itself_within_the_bound_is_persisted(self, store, claims):
        request = make_request()
        runner = ScriptedRunner(
            [
                writer_ok({"wrong": "shape"}),  # attempt 1: schema-invalid
                writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}),  # attempt 2: valid
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.attempts) == ("ok", 2)
        assert runner.calls == 2
        assert len(outcome.violations) == 1
        assert store.output_path(request.artifact_id).exists()


# --- violating writer output is caught and NEVER persisted --------------------------------


class TestViolationNeverPersisted:
    def _assert_not_persisted(self, outcome, request, store, runner, *, expected_calls):
        assert outcome.status == "error"
        assert outcome.code == CODE_CONTRACT_VIOLATION
        assert outcome.ir is None
        assert not store.output_path(request.artifact_id).exists()
        assert not store.artifacts_dir.joinpath(request.artifact_id).exists()
        assert runner.calls == expected_calls
        assert len(outcome.violations) == expected_calls

    def test_schema_invalid_json_is_caught_and_never_persisted(self, store, claims):
        request = make_request()
        runner = ScriptedRunner([ok_outcome("I'm sorry, I can't produce JSON here.")])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=3
        )
        self._assert_not_persisted(outcome, request, store, runner, expected_calls=3)

    def test_unknown_fact_id_is_caught_and_never_persisted(self, store, claims):
        request = make_request()
        runner = ScriptedRunner([writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f9"}.'})])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        self._assert_not_persisted(outcome, request, store, runner, expected_calls=2)

    def test_non_extracted_lead_asserted_as_fact_is_caught_and_never_persisted(self, store, claims):
        # The fact is INFERRED; the writer asserts it as EXTRACTED — tier promotion, refused.
        request = make_request(grounded_facts=(make_fact(tier="INFERRED"),))
        runner = ScriptedRunner([writer_ok({"body": 'A [lead]{.EXTRACTED data-fact="f0"}.'})])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        self._assert_not_persisted(outcome, request, store, runner, expected_calls=2)

    def test_tier_promotion_inside_nested_bracket_span_is_caught_and_never_persisted(
        self, store, claims
    ):
        # The blind-spot bug: an INFERRED lead asserted as EXTRACTED inside a span whose
        # visible text nests brackets (`foo[1]`). The old `[^\]]*` regex extracted 0 refs, so
        # the gate passed and the body PERSISTED. The balanced scanner now catches it.
        request = make_request(grounded_facts=(make_fact(tier="INFERRED"),))
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [lead about foo[1] bar]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        self._assert_not_persisted(outcome, request, store, runner, expected_calls=2)


# --- transport-level failure surfaces immediately -----------------------------------------


class TestTransportFailureSurfaces:
    def test_backpressure_is_surfaced_and_not_reasked(self, store, claims):
        request = make_request()
        runner = ScriptedRunner([backpressure_outcome()])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=3
        )
        assert outcome.status == "error"
        assert outcome.code == "rate-limit-backpressure"
        assert outcome.ir is None
        assert runner.calls == 1  # NOT re-asked — an account-side condition
        assert not store.output_path(request.artifact_id).exists()
        assert outcome.transport_result is not None


# --- roster is compose CONTEXT, not identity (§9.6) ----------------------------------------


class TestRosterIsContextNotIdentity:
    def test_roster_does_not_change_identity_or_binding(self, tmp_path, claims):
        content = {"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}
        req_a = make_request(roster=())
        req_b = make_request(roster=("getting-started", "architecture"))
        assert req_a.artifact_id == req_b.artifact_id  # identity is coordinate-only (§7.1)

        store_a = WorkspaceStore(tmp_path / "a")
        store_b = WorkspaceStore(tmp_path / "b")
        out_a = compose_artifact(
            req_a, store=store_a, claims=claims, runner=ScriptedRunner([writer_ok(content)])
        )
        out_b = compose_artifact(
            req_b, store=store_b, claims=claims, runner=ScriptedRunner([writer_ok(content)])
        )

        # Bindings are byte-identical; the roster appears NOWHERE in the persisted IR.
        assert out_a.ir["binding"] == out_b.ir["binding"]
        assert "getting-started" not in json.dumps(out_b.ir)
        assert "roster" not in json.dumps(out_b.ir)

    def test_roster_rides_the_prompt(self):
        request = make_request(roster=("getting-started", "architecture"))
        _, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        prompt = build_writer_prompt(request, entries)
        assert "getting-started" in prompt and "architecture" in prompt
        assert '"fact_id": "f0"' in prompt and "EXTRACTED" in prompt
        assert "business" in prompt  # effective values ride the prompt too

    def test_reask_note_is_appended_on_correction(self):
        request = make_request()
        _, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        prompt = build_writer_prompt(request, entries, reask_note="prior output was rejected")
        assert "Correction required" in prompt and "prior output was rejected" in prompt


# --- idempotency (§21.8): an existing artifact skips the writer ----------------------------


class TestIdempotency:
    def test_recomposing_an_existing_artifact_skips_the_writer(self, store, claims):
        request = make_request()
        content = {"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}
        first = compose_artifact(
            request, store=store, claims=claims, runner=ScriptedRunner([writer_ok(content)])
        )
        assert first.status == "ok" and store.output_path(request.artifact_id).exists()

        never = NeverRunner()
        second = compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0
        assert second.attempts == 0
        assert second.code == "already-materialized"
        assert store.output_path(request.artifact_id).exists()


# --- loud aborts before the LLM (§3.3 / wiring) -------------------------------------------


class TestLoudAbortsBeforeLLM:
    def test_secret_shaped_source_repo_aborts_before_any_llm_call(self, store, claims):
        request = make_request(
            source_repos={"acme-graph": "https://u:s3cr3t@github.com/acme/widget"}
        )
        never = NeverRunner()
        with pytest.raises(SecretShapedValueError):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0
        assert not store.output_path(request.artifact_id).exists()

    def test_missing_source_repo_is_a_loud_wiring_defect(self, store, claims):
        request = make_request(source_repos={})
        never = NeverRunner()
        with pytest.raises(ComposeError):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0

    def test_secret_shaped_claim_aborts_before_any_llm_call(self, store, claims):
        # A fact VALUE (claim) from a graph node would be copied into the writer prompt/body;
        # a secret-shaped claim is refused at ledger-build, before any LLM call (§3.3).
        request = make_request(
            grounded_facts=(make_fact(claim="auth token sk-live-0123456789abcdefghijklmn"),)
        )
        never = NeverRunner()
        with pytest.raises(SecretShapedValueError):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0
        assert not store.output_path(request.artifact_id).exists()

    def test_secret_shaped_subject_aborts_before_any_llm_call(self, store, claims):
        request = make_request(grounded_facts=(make_fact(subject="AKIAIOSFODNN7EXAMPLE"),))
        never = NeverRunner()
        with pytest.raises(SecretShapedValueError):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0

    def test_max_attempts_below_one_is_refused(self, store, claims):
        with pytest.raises(ComposeError):
            compose_artifact(
                make_request(), store=store, claims=claims, runner=NeverRunner(), max_attempts=0
            )


# --- the A2 non-repo cwd -------------------------------------------------------------------


class TestNonRepoCwd:
    def test_child_runs_in_a_dedicated_non_repo_cwd(self, store, claims):
        request = make_request()
        runner = ScriptedRunner([writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})])
        compose_artifact(request, store=store, claims=claims, runner=runner)
        cwd = runner.requests[0].cwd
        assert cwd is not None
        resolved = cwd.resolve()
        assert resolved != REPO_ROOT
        assert REPO_ROOT not in resolved.parents  # never the repo working tree (A2)

    def test_caller_supplied_cwd_is_honored(self, store, claims, tmp_path):
        request = make_request()
        supplied = tmp_path / "scratch"
        supplied.mkdir()
        runner = ScriptedRunner([writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})])
        compose_artifact(request, store=store, claims=claims, runner=runner, cwd=supplied)
        assert runner.requests[0].cwd == supplied


# --- the ledger builder --------------------------------------------------------------------


class TestGroundingLedgerBuilder:
    def test_fact_ids_are_assigned_deterministically(self):
        facts = (
            make_fact(subject="z-topic", claim="c1"),
            make_fact(subject="a-topic", claim="c2"),
        )
        ledger, entries = build_grounding_ledger(
            facts, source_repos={"acme-graph": "github.com/acme/x"}
        )
        # ordered by (instance, subject, claim): a-topic before z-topic → f0, f1.
        assert [fid for fid, _ in entries] == ["f0", "f1"]
        assert ledger["f0"]["source_instance_id"] == "acme-graph"
        assert entries[0][1].subject == "a-topic"

    def test_anchor_is_rendered_kind_colon_value(self):
        ledger, _ = build_grounding_ledger(
            (make_fact(),), source_repos={"acme-graph": "github.com/acme/x"}
        )
        assert ledger["f0"]["traceability_anchor"] == ["file-line:src/parser.py:42"]

    @pytest.mark.parametrize(
        "field,value",
        [
            ("claim", "auth token sk-live-0123456789abcdefghijklmn"),
            ("subject", "AKIAIOSFODNN7EXAMPLE"),
        ],
    )
    def test_secret_shaped_fact_value_is_refused_at_ledger_build(self, field, value):
        # A secret in a fact `subject`/`claim` never reaches the ledger (so ir's ledger scan
        # can't see it) — it is scanned at compose's input boundary and refused (§3.3).
        with pytest.raises(SecretShapedValueError):
            build_grounding_ledger(
                (make_fact(**{field: value}),), source_repos={"acme-graph": "github.com/acme/x"}
            )
