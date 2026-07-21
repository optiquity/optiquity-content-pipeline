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
import re
from pathlib import Path

import pytest

from pipeline.adapters.base import Anchor
from pipeline.canonical import canonical_json_bytes, digest_full
from pipeline.claims import ClaimRegistry
from pipeline.compose import (
    CODE_CITATION_UNRESOLVED,
    CODE_CONTRACT_VIOLATION,
    CODE_SECTION_CONFORMANCE_VIOLATION,
    ComposeError,
    ComposeRequest,
    _citation_resolution_note,
    build_grounding_ledger,
    build_outline_ir,
    build_writer_prompt,
    compose_artifact,
    parse_writer_output,
    project_references,
)
from pipeline.grounding import GroundedFact
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id, parse_id
from pipeline.ir import SchemaViolation, SecretShapedValueError, build_ir, validate_ir
from pipeline.outline import normalize_outline, outline_digest
from pipeline.serialize import (
    PANDOC_API_VERSION,
    PandocOutcome,
    is_ci,
    pandoc_available,
    pandoc_gate,
)
from pipeline.store import WorkspaceStore
from pipeline.transport import ProcessOutcome, ProcessRequest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMIT_SHA = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"

_PANDOC_AVAILABLE = pandoc_available()


def _requires_pandoc() -> None:
    """DR-5 C4 (D-cite-locus = COMPOSE): a CITING compose parses through the pinned reader, so it
    needs pandoc. Absent + CI ⇒ fail loudly; absent locally ⇒ skip; present ⇒ run (PA-12). The
    non-citing corpus never parses (gated on the `[@` marker), so it needs no pandoc."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the DR-5 C4 `[@key]`→references proof MUST run in CI "
            "(PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the C4 `[@key]`→references resolution needs the reader")


def _forbidden_pandoc_runner(args, stdin_text):
    """A `PandocRunner` that must NEVER be called — proves the `[@` marker gate skips the parse for
    a non-citing (or lone-bare-`@`) body, so that corpus stays parse-free + byte-identical."""
    raise AssertionError("pandoc must not be invoked for a body with no `[@` citation marker")


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
    *,
    subject="parser",
    claim="runs in linear time",
    tier="EXTRACTED",
    instance="acme-graph",
    commit=COMMIT_SHA,
    attestation=None,
):
    return GroundedFact(
        subject=subject,
        claim=claim,
        instance_id=instance,
        adapter="graphify",
        commit=commit,
        base_tier=tier,
        tier=tier,
        corroboration=0,
        agreeing_instances=(instance,),
        anchors=(Anchor(kind="file-line", value="src/parser.py:42"),),
        citable=True,
        as_of=datetime.date(2026, 6, 1),
        scores={"trusted": 5, "review_status": "merged", "freshness": datetime.date(2026, 6, 1)},
        weight=1.0,
        attestation=attestation,
    )


#: A well-formed §15 RI3 (DR-6) scenario-2 attestation — a STRUCTURED CSL-JSON `primary`, a
#: non-empty `anchor` into the held pool source, and a `wasQuotedFrom` PROV-O `relation`.
VALID_ATTESTATION = {
    "primary": {"type": "article-journal", "title": "On Parsing", "DOI": "10.1000/xyz"},
    "anchor": "file-line:docs/refs.md:5",
    "relation": "wasQuotedFrom",
}


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
        ledger, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        prompt = build_writer_prompt(request, entries, ledger)
        assert "getting-started" in prompt and "architecture" in prompt
        assert '"fact_id": "f0"' in prompt and "EXTRACTED" in prompt
        assert "business" in prompt  # effective values ride the prompt too

    def test_reask_note_is_appended_on_correction(self):
        request = make_request()
        ledger, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        prompt = build_writer_prompt(
            request, entries, ledger, reask_note="prior output was rejected"
        )
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


# --- The §15 substance floor (GAP-6): substance-free bodies re-ask, fail loud, never persist ------


class TestSubstanceFloor:
    """A substance-free body (`"..."`) PARSES the writer contract (`"...".strip()` is truthy) but
    fails `validate_ir`'s §15 substance floor into the EXISTING bounded re-ask → fail-loud
    `compose-contract-violation`, NEVER persisted, with the `ir-empty-substance` marker recorded in
    `violations` (the derail is observable at the object level, F1)."""

    def test_flat_substanceless_body_is_reasked_and_never_persisted(self, store, claims):
        request = make_request()
        runner = ScriptedRunner([writer_ok({"body": "..."})])  # parses, yet ships empty
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        assert outcome.status == "error"
        assert outcome.code == CODE_CONTRACT_VIOLATION
        assert outcome.ir is None
        assert not store.output_path(request.artifact_id).exists()
        assert runner.calls == 2  # the floor re-asked up to the bound
        assert len(outcome.violations) == 2
        assert all("ir-empty-substance" in v for v in outcome.violations)

    def test_parts_substanceless_body_is_reasked_and_never_persisted(self, store, claims):
        request = make_request(format_parts=("slides", "presenter-notes"))
        runner = ScriptedRunner(
            [writer_ok({"parts": {"slides": "...", "presenter-notes": "..."}})]
        )
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        assert outcome.status == "error"
        assert outcome.code == CODE_CONTRACT_VIOLATION
        assert outcome.ir is None
        assert not store.output_path(request.artifact_id).exists()
        assert any("ir-empty-substance" in v for v in outcome.violations)

    def test_substanceless_then_valid_recovers_within_the_bound(self, store, claims):
        # A RECOVERED derail: attempt-1 `"..."` (substance floor) → attempt-2 valid prose. The
        # outcome carries the recovered `ir-empty-substance` marker (object-level rate evidence
        # the driver F1 emit surfaces in production).
        request = make_request()
        runner = ScriptedRunner(
            [
                writer_ok({"body": "..."}),  # attempt 1 — substance floor
                writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}),  # attempt 2 — valid
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.attempts) == ("ok", 2)
        assert len(outcome.violations) == 1
        assert "ir-empty-substance" in outcome.violations[0]
        assert store.output_path(request.artifact_id).exists()


# --- DR-6 attestation carrier + pass-through (§15 RI3): scenario-1 byte-identity ---


class TestAttestationCarrierPassThrough:
    """DR-6 COMMIT 2: `build_grounding_ledger` passes a fact's `attestation` into the ledger entry
    ONLY when present. A scenario-1 fact (attestation None) yields a byte-IDENTICAL 6-field entry
    (zero churn, no artifact-id/binding impact); a scenario-2 fact carries the attestation through
    to the persisted, validated IR."""

    def _six_field_entry(self, repo):
        # The EXACT pre-DR-6 (6 LEDGER_REQUIRED fields) entry shape that make_fact() produces.
        return {
            "tier": "EXTRACTED",
            "source_instance_id": "acme-graph",
            "source_repo": repo,
            "source_commit": COMMIT_SHA,
            "traceability_anchor": ["file-line:src/parser.py:42"],
            "scores_snapshot": {"trusted": 5, "review_status": "merged", "freshness": "2026-06-01"},
        }

    def test_scenario1_ledger_entry_is_byte_identical_pre_step(self):
        repo = "github.com/acme/x"
        ledger, _ = build_grounding_ledger((make_fact(),), source_repos={"acme-graph": repo})
        assert "attestation" not in ledger["f0"]
        expected = {"f0": self._six_field_entry(repo)}
        assert ledger == expected
        # byte-identity under canonical persistence — the scenario-1 ledger is unchanged.
        assert canonical_json_bytes(ledger) == canonical_json_bytes(expected)

    def test_scenario1_artifact_identity_is_unchanged(self, store, claims):
        # Zero identity churn: the ledger is NOT an artifact-id input (§7.2). A scenario-1 compose
        # mints the SAME artifact_id + binding the preimage alone dictates.
        preimage = make_preimage()
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.ir["binding"] == {
            "artifact_id": mint_artifact_id(preimage),
            "preimage": dict(preimage),
            "digest": digest_full(preimage),
        }

    def test_attestation_is_carried_through_when_present(self):
        ledger, _ = build_grounding_ledger(
            (make_fact(attestation=VALID_ATTESTATION),),
            source_repos={"acme-graph": "github.com/acme/x"},
        )
        assert ledger["f0"]["attestation"] == VALID_ATTESTATION

    def test_scenario2_fact_composes_and_persists_with_attestation(self, store, claims):
        request = make_request(grounded_facts=(make_fact(attestation=VALID_ATTESTATION),))
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        validate_ir(persisted)
        assert persisted["grounding"]["f0"]["attestation"] == VALID_ATTESTATION

    def test_scenario2_binding_matches_scenario1_binding(self, store, claims):
        # scenario-2 mints the SAME artifact_id + binding as scenario-1 — attestation rides the
        # ledger, never identity (§7.2). Same preimage-derived binding as the scenario-1 test.
        preimage = make_preimage()
        request = make_request(grounded_facts=(make_fact(attestation=VALID_ATTESTATION),))
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.ir["binding"] == {
            "artifact_id": mint_artifact_id(preimage),
            "preimage": dict(preimage),
            "digest": digest_full(preimage),
        }


# --- DR-3 Commit 4: the emit bridge (outline -> Format=outline IR) + PO-4/5/6 -------------


class TestOutlineEmit:
    """DR-3 Commit 4 (horn (a) / B1): `build_outline_ir` realizes an outline as an ORDINARY
    `Format=outline` IR through the EXISTING `ir.build_ir` + `write_new` machinery — no new IR
    type, no schema change, no new registry root. The IR body IS the canonical Markdown (a WRAP),
    the grounding ledger is empty, and there are NO `data-fact` spans. Discharges the identity
    proof-obligations PO-4 (the emit re-mints its own id from its preimage — the R4 own-body
    exception), PO-5 (N-stability: cosmetic edits do not churn the id, semantic edits do), and PO-6
    (no new §7.4 id-family surface — an ordinary artifact-id; the digest a bare content hash)."""

    def _preimage(self, md: str) -> dict:
        return build_artifact_preimage(
            topic=EntryBinding("topic-x"),
            persona=EntryBinding("hiring-manager"),
            format=EntryBinding("outline"),  # Format=outline
            voice=EntryBinding("business"),
            goals=[EntryBinding("explain")],
            source_subset=["acme-graph"],
            source_commit={"acme-graph": COMMIT_SHA},
            outline_digest=outline_digest(md),  # the R4 own-body digest (Commit 6 supplies it)
        )

    def test_outline_emit_validates_and_wraps_body_byte_exact(self, store):
        # (i) validate_ir ACCEPTS the envelope; (ii) the body equals N(md) BYTE-for-byte.
        md = "# Launch outline\r\n\r\n- Problem   \n- Approach\n\n\n- Ship\n"
        preimage = self._preimage(md)
        artifact_id = mint_artifact_id(preimage)
        doc = build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)

        validate_ir(doc)  # (i) — accepts an ordinary flat-body artifact
        expected = normalize_outline(md)
        assert doc["body"] == expected
        assert doc["body"].encode("utf-8") == expected.encode("utf-8")  # (ii) byte-exact WRAP
        # ordinary artifact: empty ledger, no data-fact spans, a flat body (never a parts list).
        assert doc["grounding"] == {}
        assert "data-fact" not in doc["body"]
        assert "body" in doc and "parts" not in doc

    def test_outline_emit_persists_under_its_artifact_id(self, store):
        md = "# Outline\n\n- one\n- two\n"
        preimage = self._preimage(md)
        artifact_id = mint_artifact_id(preimage)
        doc = build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)
        # persisted via the no-replace write_new path, keyed by the artifact-id (§22.3).
        target = store.output_path(artifact_id)
        assert target.exists()
        persisted = json.loads(target.read_bytes())
        validate_ir(persisted)
        assert persisted == doc  # the persisted record IS the returned raw envelope (no wrapper)

    def test_outline_emit_id_reproduced_from_preimage_PO4(self, store):
        # PO-4: build_ir -> _validate_binding -> mint_artifact_id(binding["preimage"]) reproduces
        # the recorded artifact_id byte-exact; the emit id DEPENDS on the outline-digest (R4).
        md = "# Outline\n\n- alpha\n- beta\n"
        preimage = self._preimage(md)
        artifact_id = mint_artifact_id(preimage)
        doc = build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)
        binding = doc["binding"]
        assert binding["artifact_id"] == artifact_id
        assert mint_artifact_id(binding["preimage"]) == artifact_id  # re-mints its OWN id
        assert binding["digest"] == digest_full(binding["preimage"])
        assert binding["preimage"]["outline-digest"] == outline_digest(md)  # the R4 own-body home

    def test_outline_emit_id_is_N_stable_and_body_dependent_PO5(self, store):
        # PO-5: N idempotent -> a COSMETIC edit (trailing ws + blank-run collapse) does NOT churn
        # the digest/id; a SEMANTIC edit DOES (the accepted R2 re-compose cost).
        md = "# Outline\n\n- one\n- two\n"
        base_id = mint_artifact_id(self._preimage(md))

        cosmetic = "# Outline\n\n\n- one   \n- two\n\n"  # N-identical to md
        assert outline_digest(cosmetic) == outline_digest(md)
        assert mint_artifact_id(self._preimage(cosmetic)) == base_id  # no id churn

        semantic = "# Outline\n\n- one\n- two\n- three\n"  # a real content change
        assert outline_digest(semantic) != outline_digest(md)
        assert mint_artifact_id(self._preimage(semantic)) != base_id  # a NEW id

    def test_outline_emit_no_new_id_family_surface_PO6(self, store):
        # PO-6: the outline is an ORDINARY artifact-id (a-<hex16>); no `o-` root, no new §7.4
        # family — the outline-digest rides the preimage as a bare content hash, never parse_id'd.
        md = "# Outline\n\n- only\n"
        preimage = self._preimage(md)
        artifact_id = mint_artifact_id(preimage)
        build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)
        parsed = parse_id(artifact_id)
        assert parsed.family == "artifact" and parsed.level == "artifact" and parsed.part is None
        assert not artifact_id.startswith("o-")

    def test_outline_emit_is_idempotent(self, store):
        # §22.7: re-emitting the SAME outline is a benign no-op — the bytes are untouched.
        md = "# Outline\n\n- one\n"
        preimage = self._preimage(md)
        artifact_id = mint_artifact_id(preimage)
        first = build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)
        before = store.output_path(artifact_id).read_bytes()
        second = build_outline_ir(md, artifact_id=artifact_id, preimage=preimage, store=store)
        assert store.output_path(artifact_id).read_bytes() == before
        assert second == first


# --- DR-3 Commit 6: the outline DRIVE path (digest fidelity; B2 total rule; fixed posture) ---


class TestOutlineDriveCompose:
    """DR-3 Commit 6 (horn (a) / B1): a driven `ComposeRequest.outline_brief` inserts a
    HIGH-SALIENCE drive block into the writer PROMPT and is bound to the artifact's claimed
    identity by the compose digest-fidelity guard. B2 total rule: the brief NEVER sets
    `format.parts` / any cascade-bound attribute and never enters the binding. Fixed posture
    (horn (a)): no facet parameter, no new preimage key — the `outline-digest` alone is the
    identity carrier."""

    MD = "# Brief\n\n- lead with the problem\n- then the fix\n"

    def _preimage(self, md: str) -> dict:
        return build_artifact_preimage(
            topic=EntryBinding("topic-x"),
            persona=EntryBinding("hiring-manager"),
            format=EntryBinding("readme"),
            voice=EntryBinding("business"),
            goals=[EntryBinding("explain")],
            source_subset=["acme-graph"],
            source_commit={"acme-graph": COMMIT_SHA},
            outline_digest=outline_digest(md),
        )

    def _driven_request(self, **over) -> ComposeRequest:
        preimage = self._preimage(self.MD)
        base = {
            "artifact_id": mint_artifact_id(preimage),
            "preimage": preimage,
            "format_parts": (),
            "effective_values": {"voice": {"tone": "business"}},
            "grounded_facts": (make_fact(),),
            "source_repos": {"acme-graph": "github.com/acme/widget"},
            "outline_brief": normalize_outline(self.MD),
        }
        base.update(over)
        return ComposeRequest(**base)

    def test_matching_brief_passes_the_guard_and_persists(self, store, claims):
        request = self._driven_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        # the brief rode the PROMPT (high-salience), never identity/binding.
        prompt = runner.requests[0].stdin_text
        assert "lead with the problem" in prompt
        assert "HIGHEST PRECEDENCE (DR-3" in prompt
        # B2 total rule: a FLAT body (never a parts list); the binding is preimage-only.
        assert "body" in outcome.ir and "parts" not in outcome.ir
        assert outcome.ir["binding"]["preimage"] == dict(request.preimage)
        assert outcome.ir["binding"]["artifact_id"] == request.artifact_id

    def test_the_brief_never_appears_in_the_persisted_binding(self, store, claims):
        # the brief is a compose INPUT; only the outline-DIGEST rides identity, never the text.
        request = self._driven_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert "lead with the problem" not in json.dumps(outcome.ir["binding"])
        assert "format.parts" not in json.dumps(outcome.ir["binding"])

    def test_mismatched_brief_digest_raises_compose_error(self, store, claims):
        # (ii) a brief whose digest != the pinned preimage outline-digest is a LOUD ComposeError,
        # BEFORE any LLM call, and NEVER persisted (never a re-ask, never silent).
        request = self._driven_request(outline_brief="# DIFFERENT\n\n- other point\n")
        never = NeverRunner()
        with pytest.raises(ComposeError, match="digest fidelity|does not match"):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0
        assert not store.output_path(request.artifact_id).exists()

    def test_brief_on_an_outline_less_preimage_raises(self, store, claims):
        # a brief set on a 4-key (outline-less) preimage is a wiring defect — the claimed identity
        # carries no outline-digest, so the guard refuses loudly (None != actual digest).
        preimage = make_preimage()  # 4-key, no outline-digest
        request = ComposeRequest(
            artifact_id=mint_artifact_id(preimage),
            preimage=preimage,
            format_parts=(),
            effective_values={},
            grounded_facts=(make_fact(),),
            source_repos={"acme-graph": "github.com/acme/widget"},
            outline_brief=normalize_outline(self.MD),
        )
        with pytest.raises(ComposeError):
            compose_artifact(request, store=store, claims=claims, runner=NeverRunner())

    def test_cosmetic_brief_edit_keeps_identity_and_passes_the_guard(self, store, claims):
        # a COSMETIC edit (N-identical: trailing ws + blank-run collapse) keeps the same digest ->
        # the same artifact-id, and the guard still passes (the loaded brief is always N(md)).
        cosmetic = "# Brief\n\n\n- lead with the problem   \n- then the fix\n\n"
        assert outline_digest(cosmetic) == outline_digest(self.MD)
        request = self._driven_request(outline_brief=normalize_outline(cosmetic))
        assert request.artifact_id == mint_artifact_id(self._preimage(self.MD))
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]
        )
        assert compose_artifact(request, store=store, claims=claims, runner=runner).status == "ok"

    def test_outline_less_compose_is_unchanged_and_has_no_drive_block(self, store, claims):
        # (iii) an outline-LESS request (default outline_brief=None) composes exactly as before and
        # the prompt carries NO drive block (the brief CONTENT is absent).
        request = make_request()
        assert request.outline_brief is None
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        assert "lead with the problem" not in runner.requests[0].stdin_text
        assert "HIGHEST PRECEDENCE (DR-3" not in runner.requests[0].stdin_text


# --- DR-4 C5: the HARD base structural gate at compose (platform-NEUTRAL) ------------------


class TestBaseStructuralGate:
    """DR-4 C5 (D-2 severities, D-4 defer): the platform-NEUTRAL base structural gate runs
    post-mint INSIDE the bounded re-ask. A conforming body ships; an ERROR-severity base violation
    (required-missing) re-asks then BLOCKS with the NEW never-persisted `section-conformance-
    violation`; a Format with NO `section_schema` composes BYTE-IDENTICAL to the pre-DR-4 golden; a
    `section_schema`-bearing Format with a NON-outline body is EXEMPT (never a false block); an
    advisory (warning-severity) order breach WARNS and never blocks; a malformed Format schema is a
    loud wiring defect. The schema is resolved from `request.effective_values["format"]` (NO new
    ComposeRequest field) — the artifact is outline-shaped iff its preimage carries an
    `outline-digest`."""

    OUTLINE_MD = "# Paper\n\n- intro\n- body\n"
    REQUIRE_INTRO = [{"rule": "presence", "axis": "role", "value": "intro", "required": True}]

    def _outline_preimage(self, md: str) -> dict:
        return build_artifact_preimage(
            topic=EntryBinding("topic-x"),
            persona=EntryBinding("hiring-manager"),
            format=EntryBinding("academic-paper"),
            voice=EntryBinding("business"),
            goals=[EntryBinding("explain")],
            source_subset=["acme-graph"],
            source_commit={"acme-graph": COMMIT_SHA},
            outline_digest=outline_digest(md),  # the DR-3 identity coverage of the structure
        )

    def _request(self, *, section_schema, preimage=None, **over) -> ComposeRequest:
        preimage = preimage if preimage is not None else self._outline_preimage(self.OUTLINE_MD)
        base = {
            "artifact_id": mint_artifact_id(preimage),
            "preimage": preimage,
            "format_parts": (),
            "effective_values": {"format": {"section_schema": section_schema}},
            "grounded_facts": (make_fact(),),
            "source_repos": {"acme-graph": "github.com/acme/widget"},
        }
        base.update(over)
        return ComposeRequest(**base)

    def test_conforming_body_ships(self, store, claims):
        # `## Intro` auto-slugs to role "intro" → the required section is present → ships.
        request = self._request(section_schema=self.REQUIRE_INTRO)
        body = '## Intro\n\nThe parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
        runner = ScriptedRunner([writer_ok({"body": body})])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.code, outcome.attempts) == ("ok", "ok", 1)
        assert store.output_path(request.artifact_id).exists()

    def test_required_missing_reasks_then_blocks_and_never_persists(self, store, claims):
        # Every attempt renames the required-role heading, so its implicit slug ("overview") never
        # matches the required role "intro" — the rename-broken implicit slug the section-typing
        # design relies on the hard gate to catch. RE-ASKS then BLOCKS, never persisted.
        request = self._request(section_schema=self.REQUIRE_INTRO)
        body = '## Overview\n\nThe parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
        runner = ScriptedRunner([writer_ok({"body": body})])
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=3
        )
        assert outcome.status == "error"
        assert outcome.code == CODE_SECTION_CONFORMANCE_VIOLATION  # the NEW sibling code
        assert outcome.code == "section-conformance-violation"
        assert outcome.ir is None
        assert outcome.attempts == 3 and runner.calls == 3  # re-asked (attempts > 1) then blocked
        assert len(outcome.violations) == 3
        assert all("intro" in v for v in outcome.violations)
        # NEVER persisted — the sibling of compose-contract-violation.
        assert not store.output_path(request.artifact_id).exists()
        assert not store.artifacts_dir.joinpath(request.artifact_id).exists()

    def test_reask_recovers_within_the_bound(self, store, claims):
        # attempt-1 breaks the required slug ("overview"); attempt-2 fixes it ("intro") → ships. The
        # STRUCTURAL correction note (writer.md 'Section structure') rides the re-ask prompt.
        request = self._request(section_schema=self.REQUIRE_INTRO)
        bad = '## Overview\n\nA [claim]{.EXTRACTED data-fact="f0"}.'
        good = '## Intro\n\nA [claim]{.EXTRACTED data-fact="f0"}.'
        runner = ScriptedRunner([writer_ok({"body": bad}), writer_ok({"body": good})])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.attempts) == ("ok", 2)
        assert len(outcome.violations) == 1 and "intro" in outcome.violations[0]
        assert store.output_path(request.artifact_id).exists()
        second_prompt = runner.requests[1].stdin_text.lower()
        assert "base section contract" in second_prompt  # the structural re-ask note fired

    def test_no_section_schema_is_byte_identical_no_op(self, store, claims):
        # A Format with NO `section_schema` (the default make_request has none) composes BYTE-
        # IDENTICAL to the pre-DR-4 golden: the persisted envelope is EXACTLY ir.build_ir's
        # assembly of the writer body — the base gate added nothing (no section_conformance key).
        request = make_request()
        content = {"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=ScriptedRunner([writer_ok(content)])
        )
        assert outcome.status == "ok"
        persisted = store.output_path(request.artifact_id).read_bytes()
        ledger, _ = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        expected = build_ir(
            artifact_id=request.artifact_id,
            preimage=request.preimage,
            grounding=ledger,
            body=content["body"],
        )
        assert persisted == canonical_json_bytes(expected)  # the pre-DR-4 golden, byte-for-byte
        assert "section_conformance" not in json.loads(persisted)

    def test_non_outline_section_schema_is_exempt(self, store, claims):
        # FOLDED NIT #2: a `section_schema`-bearing Format whose artifact is NOT outline-shaped (no
        # `outline-digest` in the preimage) is EXEMPT — the gate SKIPS cleanly, so a body that WOULD
        # violate the schema still ships (never a false block, never silently "unconformant").
        request = self._request(section_schema=self.REQUIRE_INTRO, preimage=make_preimage())
        body = '## Overview\n\nA [claim]{.EXTRACTED data-fact="f0"}.'  # no "intro" section
        runner = ScriptedRunner([writer_ok({"body": body})])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"  # EXEMPT — not blocked despite the missing required role
        assert store.output_path(request.artifact_id).exists()

    def test_advisory_order_violation_warns_never_blocks(self, store, claims):
        # An order rule defaults to WARNING severity (D-2) — an out-of-order body WARNS, never
        # blocks (its warn-surfacing is the DEFERRED Review-1 advisory check, D-4).
        schema = [
            {
                "rule": "order",
                "selectors": [
                    {"axis": "role", "value": "intro"},
                    {"axis": "role", "value": "body"},
                ],
            }
        ]
        request = self._request(section_schema=schema)
        body = '## Body\n\nA [claim]{.EXTRACTED data-fact="f0"}.\n\n## Intro\n\nmore prose'
        runner = ScriptedRunner([writer_ok({"body": body})])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.attempts) == ("ok", 1)  # advisory → never blocks/re-asks
        assert store.output_path(request.artifact_id).exists()

    def test_malformed_format_schema_is_a_loud_wiring_defect(self, store, claims):
        # A bad Format entry is a loud ComposeError BEFORE any LLM call — never a writer re-ask.
        request = self._request(section_schema=[{"rule": "not-a-real-kind"}])
        never = NeverRunner()
        with pytest.raises(ComposeError):
            compose_artifact(request, store=store, claims=claims, runner=never)
        assert never.calls == 0
        assert not store.output_path(request.artifact_id).exists()


# --- DR-5 C2: `references` projected from the ledger's DISTINCT pool sources -----------------


class TestProjectReferences:
    """DR-5 C2: `project_references` maps the grounding ledger's DISTINCT `source_instance_id`s to
    CSL-JSON `references`. The writer authors NONE (D1 is (b)-PROJECTED, forced by NO-GO #5) — every
    entry is MACHINERY-minted from real per-source metadata, with a UNIQUE, deterministic citation
    key (`s0`/`s1`…, mirroring the ledger's own `f0`/`f1` idiom) the C3 writer can cite as `[@s0]`.
    Built from the REAL `build_grounding_ledger` (never a hand-rolled ledger dict)."""

    def _ledger(self, facts, repos):
        ledger, _ = build_grounding_ledger(facts, source_repos=repos)
        return ledger

    def test_distinct_sources_map_to_distinct_ordinal_ids(self):
        ledger = self._ledger(
            (make_fact(instance="z-graph"), make_fact(instance="a-graph")),
            {"z-graph": "github.com/z/z", "a-graph": "github.com/a/a"},
        )
        refs = project_references(ledger)
        # sorted instance-id order (mirrors the fact ordering): a-graph → s0, z-graph → s1.
        assert [r["id"] for r in refs] == ["s0", "s1"]
        assert len({r["id"] for r in refs}) == 2  # UNIQUE keys — C1 refuses duplicates
        assert [r["title"] for r in refs] == ["a-graph", "z-graph"]

    def test_single_source_ledger_projects_one_entry(self):
        refs = project_references(self._ledger((make_fact(),), {"acme-graph": "github.com/acme/w"}))
        assert len(refs) == 1 and refs[0]["id"] == "s0"

    def test_multiple_facts_from_one_source_collapse_to_one_reference(self):
        # Two FACTS, ONE instance → two ledger entries but ONE reference (per DISTINCT source).
        ledger = self._ledger(
            (make_fact(claim="c1"), make_fact(claim="c2")),
            {"acme-graph": "github.com/acme/widget"},
        )
        assert len(ledger) == 2  # per-fact ledger entries
        refs = project_references(ledger)
        assert len(refs) == 1 and refs[0]["title"] == "acme-graph"

    def test_descriptor_is_honest_per_source_metadata(self):
        ledger = self._ledger((make_fact(),), {"acme-graph": "github.com/acme/widget"})
        (ref,) = project_references(ledger)
        assert ref == {
            "id": "s0",
            "type": "software",
            "title": "acme-graph",  # the source's own name
            "note": f"github.com/acme/widget@{COMMIT_SHA}",  # repo@commit — the exact locator
        }

    def test_commitless_source_note_is_the_bare_repo(self):
        # A commitless adapter (`source_commit` null, legal per §15) → the note is the repo alone.
        ledger = self._ledger((make_fact(commit=None),), {"acme-graph": "github.com/acme/widget"})
        (ref,) = project_references(ledger)
        assert ref["note"] == "github.com/acme/widget"

    def test_order_is_deterministic_regardless_of_input_ordering(self):
        repos = {
            "a-graph": "github.com/a/a",
            "m-graph": "github.com/m/m",
            "z-graph": "github.com/z/z",
        }
        forward = project_references(
            self._ledger(
                (
                    make_fact(instance="a-graph"),
                    make_fact(instance="m-graph"),
                    make_fact(instance="z-graph"),
                ),
                repos,
            )
        )
        reverse = project_references(
            self._ledger(
                (
                    make_fact(instance="z-graph"),
                    make_fact(instance="m-graph"),
                    make_fact(instance="a-graph"),
                ),
                repos,
            )
        )
        assert forward == reverse  # sorted instance-id order — input order is irrelevant
        assert [r["title"] for r in forward] == ["a-graph", "m-graph", "z-graph"]


class TestReferencesProjectionGate:
    """DR-5 C2 gate: `references` attaches ONLY when the composed body carries a citation marker
    `[@`. At C2 the writer is NOT yet taught to cite, so NO body cites → `references` attaches to
    NOTHING → every existing golden compose is byte-identical (the omit-when-absent key is absent).
    A citing body (simulated) gets the projection, and it VALIDATES under C1's rule (the real
    `build_ir` runs `_validate_references`). Both the flat and the parts envelopes are covered."""

    def test_flat_citationless_body_omits_references(self, store, claims):
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        assert "references" not in persisted  # nothing cites → omit-when-absent → byte-identical
        assert "references" not in outcome.ir

    def test_flat_citing_body_attaches_and_validates_references(self, store, claims):
        _requires_pandoc()  # DR-5 C4: a citing body now parses through the pinned reader
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0].'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        validate_ir(persisted)  # the projected references pass C1's _validate_references
        assert [r["id"] for r in persisted["references"]] == ["s0"]
        assert persisted["references"][0]["title"] == "acme-graph"

    def test_parts_citationless_body_omits_references(self, store, claims):
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
        assert "references" not in persisted  # no part cites → byte-identical

    def test_parts_citing_body_attaches_and_validates_references(self, store, claims):
        # A citation marker in ANY part body trips the gate.
        _requires_pandoc()  # DR-5 C4: the citing part body now parses through the pinned reader
        request = make_request(format_parts=("slides", "presenter-notes"))
        runner = ScriptedRunner(
            [
                writer_ok(
                    {
                        "parts": {
                            "slides": '# Deck\n\n- [linear time]{.EXTRACTED data-fact="f0"} [@s0]',
                            "presenter-notes": "Speaker notes, ungrounded prose.",
                        }
                    }
                )
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        validate_ir(persisted)
        assert [r["id"] for r in persisted["references"]] == ["s0"]

    def test_projected_references_validate_through_the_real_build_ir(self):
        # The projection wired straight through the REAL build_ir with a citing body validates —
        # N distinct sources → N entries with distinct ids, resolvable by a later `[@key]` (C4).
        request = make_request(
            grounded_facts=(make_fact(instance="a-graph"), make_fact(instance="b-graph")),
            source_repos={"a-graph": "github.com/a/a", "b-graph": "github.com/b/b"},
        )
        ledger, _ = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        refs = project_references(ledger)
        doc = build_ir(
            artifact_id=request.artifact_id,
            preimage=request.preimage,
            grounding=ledger,
            body='A [claim]{.EXTRACTED data-fact="f0"} — see [@s0] and [@s1].',
            references=refs,
        )
        validate_ir(doc)  # no raise — unique ids, each with a non-empty-string id (C1)
        assert [r["id"] for r in doc["references"]] == ["s0", "s1"]


# --- DR-5 C3: the writer is TAUGHT the projected citation keys + FORBIDDEN from authoring refs ---

#: Anchored on the exact heading `build_writer_prompt` appends (the template itself carries
#: illustrative ```json fences, so a bare fence match would grab the wrong block).
_CTX_RE = re.compile(r"## Compose context \(JSON\)\s*```json\s*\n(.*?)\n```", re.DOTALL)


def _compose_context(prompt: str) -> dict:
    """Extract the writer prompt's JSON compose-context block (facts + available_citations)."""
    match = _CTX_RE.search(prompt)
    assert match is not None, "the writer prompt must carry a ## Compose context (JSON) block"
    return json.loads(match.group(1))


class TestWriterCitationContext:
    """DR-5 C3: the writer prompt HANDS the writer the projected citation keys — each fact's
    `citation_key` + the top-level `available_citations` set — SINGLE-SOURCED with C2's
    `project_references`, so the writer cites EXACTLY the ids C4 later resolves `[@key]` against.
    Prompt CONTEXT only: it never enters identity (`references` is body-blind, C1/C2)."""

    def _context(self, request):
        ledger, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        return _compose_context(build_writer_prompt(request, entries, ledger)), ledger

    def test_each_fact_carries_its_source_citation_key(self):
        # Two facts from two sources → each fact's citation_key is that source's projected id.
        request = make_request(
            grounded_facts=(make_fact(instance="a-graph"), make_fact(instance="z-graph")),
            source_repos={"a-graph": "github.com/a/a", "z-graph": "github.com/z/z"},
        )
        context, ledger = self._context(request)
        projected = {r["title"]: r["id"] for r in project_references(ledger)}
        for fact in context["grounded_facts"]:
            assert fact["citation_key"] == projected[fact["source_instance"]]

    def test_available_citations_slot_lists_the_projected_set(self):
        request = make_request(
            grounded_facts=(make_fact(instance="a-graph"), make_fact(instance="z-graph")),
            source_repos={"a-graph": "github.com/a/a", "z-graph": "github.com/z/z"},
        )
        context, ledger = self._context(request)
        refs = project_references(ledger)
        assert context["available_citations"] == [
            {"citation_key": r["id"], "label": r["title"]} for r in refs
        ]
        # the keys the writer sees are EXACTLY C2's projected ids (C4's [@key] ⊆ set).
        assert [c["citation_key"] for c in context["available_citations"]] == ["s0", "s1"]

    def test_citation_key_is_single_sourced_with_the_c2_projection(self):
        # The prompt's fact `citation_key` equals `project_references`' id for that source — proving
        # the s{n} derivation is defined ONCE, never forked (a fork would make C4 reject cites).
        request = make_request()
        context, ledger = self._context(request)
        (ref,) = project_references(ledger)
        (fact,) = context["grounded_facts"]
        assert fact["citation_key"] == ref["id"] == "s0"

    def test_citation_key_and_slot_never_reach_the_persisted_ir(self, store, claims):
        # The prompt carries citation keys; a citation-LESS compose persists NONE of it — the keys
        # are LLM-facing context, not identity (`references` is body-blind, C1/C2).
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        assert "citation_key" not in json.dumps(outcome.ir)
        assert "available_citations" not in json.dumps(outcome.ir)


class TestWriterLexiconContext:
    """DR-2 C3: the writer prompt carries the RESOLVED house-style lexicon ATTRIBUTES as a
    prompt-only, attribute-ONLY (P1), byte-STABLE (P2) context slot the writer APPLIES (§2.2).
    Present ONLY when a lexicon is selected; absent -> the compose context is byte-identical to
    the pre-DR-2 assembly (omit-when-absent). Never identity: the lexicon's IDENTITY input is
    its `{entry, delta}` in the artifact preimage, minted separately."""

    LEX = {
        "preferred_terms": {"utilize": "use"},
        "banned_terms": ["irregardless"],
        "proper_names": {"github": "GitHub"},
        "spelling": "us",
        "mechanical": {"oxford_comma": True},
    }

    def test_slot_lists_the_resolved_attributes(self):
        request = make_request(lexicon=self.LEX)
        context = _compose_context(build_writer_prompt(*self._ledger(request)))
        assert context["lexicon"] == self.LEX  # exactly the resolved attributes, nothing else

    def test_no_lexicon_no_slot(self):
        # Omit-when-absent: a lexicon-LESS request carries NO `lexicon` context key.
        request = make_request()  # no lexicon
        context = _compose_context(build_writer_prompt(*self._ledger(request)))
        assert "lexicon" not in context

    def test_block_is_attribute_only_P1(self):
        # P1: the slot is a PURE function of `request.lexicon` (the resolved ATTRIBUTES) — nothing
        # else (no body, no facts, no roster) reaches it. Two requests with the SAME lexicon attrs
        # but DIFFERENT grounded facts (the "body" analog) yield the byte-IDENTICAL lexicon slot.
        r1 = make_request(lexicon=self.LEX, grounded_facts=(make_fact(claim="alpha claim"),))
        r2 = make_request(
            lexicon=self.LEX, grounded_facts=(make_fact(claim="a wholly other claim"),)
        )
        c1 = _compose_context(build_writer_prompt(*self._ledger(r1)))
        c2 = _compose_context(build_writer_prompt(*self._ledger(r2)))
        assert c1["lexicon"] == c2["lexicon"] == self.LEX

    def test_block_is_byte_stable_P2(self):
        # P2: the SAME resolved lexicon -> the byte-IDENTICAL prompt, INDEPENDENT of dict insertion
        # order (json.dumps sort_keys canonicalizes; set values arrive canonical sorted from M1).
        reordered = {k: self.LEX[k] for k in reversed(list(self.LEX))}
        p1 = build_writer_prompt(*self._ledger(make_request(lexicon=dict(self.LEX))))
        p2 = build_writer_prompt(*self._ledger(make_request(lexicon=reordered)))
        assert p1 == p2

    def test_slot_never_reaches_the_persisted_ir(self, store, claims):
        # Prompt-only: a lexicon-context compose persists NONE of the house-style slot into the IR
        # (the make_request preimage carries no lexicon key -> the IR is lexicon-free).
        request = make_request(lexicon=self.LEX)
        runner = ScriptedRunner(
            [writer_ok({"body": 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        assert "irregardless" not in json.dumps(outcome.ir)  # the banned-term slot never persisted

    @staticmethod
    def _ledger(request):
        ledger, entries = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        return request, entries, ledger


class TestWriterMayNotAuthorReferences:
    """DR-5 C3 / NO-GO #5: the writer emits `[@key]` markers ONLY and NEVER authors the
    `references` block — the pipeline PROJECTS it (C2). Enforcement is the EXISTING strict shape
    check in `parse_writer_output`: a flat output must be EXACTLY `{"body"}` and a parts output
    EXACTLY `{"parts"}`, so a surplus `references` key is REFUSED as a `SchemaViolation`. No new
    code — the shape check already covers #5; these tests PROVE it."""

    def test_flat_output_with_a_references_key_is_refused(self):
        request = make_request()
        writer_supplied = json.dumps(
            {"body": "A claim.", "references": [{"id": "s0", "type": "software", "title": "x"}]}
        )
        with pytest.raises(SchemaViolation):
            parse_writer_output(writer_supplied, request)

    def test_parts_output_with_a_references_key_is_refused(self):
        request = make_request(format_parts=("slides", "presenter-notes"))
        writer_supplied = json.dumps(
            {
                "parts": {"slides": "# Deck", "presenter-notes": "Notes."},
                "references": [{"id": "s0", "type": "software", "title": "x"}],
            }
        )
        with pytest.raises(SchemaViolation):
            parse_writer_output(writer_supplied, request)

    def test_writer_authored_references_is_never_persisted_end_to_end(self, store, claims):
        # End-to-end: a writer that persistently supplies `references` is caught by the shape check,
        # re-asked to the bound, and returned as compose-contract-violation — NEVER persisted (#5).
        request = make_request()
        runner = ScriptedRunner(
            [
                writer_ok(
                    {
                        "body": 'A [claim]{.EXTRACTED data-fact="f0"}.',
                        "references": [{"id": "s0", "type": "software", "title": "x"}],
                    }
                )
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "error" and outcome.code == CODE_CONTRACT_VIOLATION
        assert not store.output_path(request.artifact_id).exists()


class TestC3CitationCompose:
    """DR-5 C3 round-trip through the REAL build_grounding_ledger + parse_writer_output + build_ir
    (via `compose_artifact`): a `[@key]`-citing body persists the C2-projected `references` with the
    cited key among the projected ids (C4's `[@key]` ⊆ set); a citation-LESS body composes
    BYTE-IDENTICAL to the pre-DR-5 envelope (prompt changes are LLM-facing, not persisted)."""

    def test_citing_body_persists_projected_references_with_the_key_in_the_set(self, store, claims):
        _requires_pandoc()  # DR-5 C4: the citing body now parses through the pinned reader
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0].'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        validate_ir(persisted)
        projected_ids = {r["id"] for r in persisted["references"]}
        assert "s0" in projected_ids  # the cited [@s0] ⊆ projected ids (C4 now enforces this)

    def test_citationless_flat_body_composes_byte_identical_to_pre_dr5(self, store, claims):
        request = make_request()
        body = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
        runner = ScriptedRunner([writer_ok({"body": body})])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = store.output_path(request.artifact_id).read_bytes()
        # pre-DR-5 = the SAME IR built with NO `references` key (omit-when-absent, C1).
        ledger, _ = build_grounding_ledger(
            request.grounded_facts, source_repos=request.source_repos
        )
        pre_dr5 = build_ir(
            artifact_id=request.artifact_id,
            preimage=request.preimage,
            grounding=ledger,
            body=body,
        )
        assert persisted == canonical_json_bytes(pre_dr5)
        assert "references" not in json.loads(persisted)


# --- DR-5 C4: the HARD `[@key]`→projected-`references` resolution at the COMPOSE locus ----------


class TestC4CitationResolution:
    """DR-5 C4 (ratified D-cite-locus = COMPOSE): the authoritative `[@key]`→`references`
    resolution runs post-mint, PRE-persist, INSIDE the bounded re-ask — so an unresolvable citation
    is structurally impossible to ship (the analog of the shipped `data-fact`→ledger check, closing
    the §6.5 fabrication leak with teeth). Because C2 PROJECTS `references` and C3 hands the writer
    EXACTLY those keys, an unresolved `[@key]` is a writer BUG this gate catches. Resolution reads
    pandoc's `Cite` AST via the SINGLE pinned reader — robust against EVERY citation form, NO regex
    (S1). REAL pandoc, gated (`_requires_pandoc`); the unit-level marker-gate proof needs none."""

    def _ledger_two_sources(self):
        # Two DISTINCT sources → the projection is {s0: a-graph, s1: b-graph} (sorted instance-id).
        ledger, _ = build_grounding_ledger(
            (make_fact(instance="a-graph"), make_fact(instance="b-graph")),
            source_repos={"a-graph": "github.com/a/a", "b-graph": "github.com/b/b"},
        )
        return ledger

    def _ledger_one_source(self):
        ledger, _ = build_grounding_ledger(
            (make_fact(),), source_repos={"acme-graph": "github.com/acme/widget"}
        )
        return ledger  # projects {s0: acme-graph}

    # -- the resolution note (unit) over REAL pandoc: every VALID citation FORM resolves ⊆ projected

    @pytest.mark.parametrize(
        "body",
        [
            "See [@s0].",  # normal single-key
            "See [@s0; @s1].",  # multi-key
            "See [@s0, p. 5].",  # locator/suffix
            "See [see @s0].",  # prefix
            "See [-@s0].",  # suppressed-author
            "See [@s0] and separately [@s1].",  # two separate cites
        ],
    )
    def test_valid_forms_resolve_via_the_ast(self, body):
        _requires_pandoc()
        # Every citation FORM with a PROJECTED key resolves through the `Cite` AST → no re-ask note.
        assert _citation_resolution_note({"body": body}, self._ledger_two_sources()) is None

    def test_unresolved_key_yields_a_note_naming_it(self):
        _requires_pandoc()
        # `[@zzz]` is a valid FORM but an UNPROJECTED key — the anti-fabrication core catches it.
        note = _citation_resolution_note({"body": "See [@zzz]."}, self._ledger_two_sources())
        assert note is not None and "zzz" in note

    def test_braced_and_cooccurring_bare_forms_are_caught(self):
        _requires_pandoc()
        ledger = self._ledger_two_sources()  # s0, s1 projected → isolates the FORM check
        # A braced `[@s0]{…}` contains `[@` (trips the marker) and parses to an AuthorInText `Cite`.
        assert _citation_resolution_note({"body": "See [@s0]{.foo}."}, ledger) is not None
        # A bare `@s0` CO-OCCURRING with a bracketed `[@s1]` is reached by the running parse.
        assert _citation_resolution_note({"body": "See [@s1] and @s0 too."}, ledger) is not None

    def test_lone_bare_citation_does_not_trip_the_marker_gate(self):
        # DOCUMENTED LIMITATION (flagged for follow-up): a bare `@key` with NO bracketed `[@` does
        # not trip the cheap `[@` marker gate, so it is NOT parsed and NOT caught. The forbidden
        # runner proves NO parse fires. Widening the marker to a bare `@` would force a pandoc parse
        # across the whole (email/handle-bearing) non-citing corpus, breaking the byte-identical /
        # no-subprocess cost containment (D-cite-locus) — a maintainer call, not self-decided here.
        note = _citation_resolution_note(
            {"body": "@s0 stands alone, no brackets."},
            self._ledger_one_source(),
            runner=_forbidden_pandoc_runner,
        )
        assert note is None

    def test_citation_and_data_fact_span_do_not_cross_contaminate(self):
        _requires_pandoc()
        # A `[@s0]` cite ALONGSIDE a `[claim]{.EXTRACTED data-fact="f0"}` span: the span is NOT a
        # `Cite` (it never enters the cited set) and the cite resolves — both clean, note is None.
        body = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"} — see [@s0].'
        assert _citation_resolution_note({"body": body}, self._ledger_one_source()) is None

    def test_non_citing_body_returns_none_without_pandoc(self):
        # The cost-containment gate: NO `[@` marker → None with NO pandoc parse (forbidden runner
        # never called) → the whole non-citing corpus runs exactly as pre-C4 (byte-identical).
        body = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
        note = _citation_resolution_note(
            {"body": body}, self._ledger_one_source(), runner=_forbidden_pandoc_runner
        )
        assert note is None

    # -- end-to-end through compose_artifact (REAL pandoc): re-ask → block, never persisted --------

    def test_unresolvable_citation_reasks_then_blocks_and_never_persists(self, store, claims):
        _requires_pandoc()
        request = make_request()  # single source → projects s0 ONLY; `[@zzz]` cannot resolve
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@zzz].'})]
        )
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=3
        )
        assert outcome.status == "error"
        assert outcome.code == CODE_CITATION_UNRESOLVED  # the NEW never-persisted sibling code
        assert outcome.code == "citation-unresolved"
        assert outcome.ir is None
        assert outcome.attempts == 3 and runner.calls == 3  # re-asked (attempts > 1) then blocked
        assert len(outcome.violations) == 3 and all("zzz" in v for v in outcome.violations)
        # NEVER persisted — the sibling of compose-contract-violation / section-conformance.
        assert not store.output_path(request.artifact_id).exists()
        assert not store.artifacts_dir.joinpath(request.artifact_id).exists()
        # the corrective citation note rode the re-ask prompt (machine-derived from the contract).
        assert "available_citations" in runner.requests[1].stdin_text

    def test_valid_citation_composes_and_persists(self, store, claims):
        _requires_pandoc()
        request = make_request()  # projects s0
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0].'})]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.code, outcome.attempts) == ("ok", "ok", 1)
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        validate_ir(persisted)
        assert [r["id"] for r in persisted["references"]] == ["s0"]  # cited [@s0] ⊆ projected

    def test_reask_recovers_from_an_unresolvable_citation_within_the_bound(self, store, claims):
        _requires_pandoc()
        request = make_request()
        bad = writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@zzz].'})
        good = writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0].'})
        runner = ScriptedRunner([bad, good])
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert (outcome.status, outcome.attempts) == ("ok", 2)
        assert len(outcome.violations) == 1 and "zzz" in outcome.violations[0]
        assert store.output_path(request.artifact_id).exists()

    def test_braced_form_blocks_end_to_end(self, store, claims):
        _requires_pandoc()
        # A braced `[@s0]{…}` (s0 IS projected) renders invalidly — caught as a FORM breach and
        # blocked as citation-unresolved, never persisted.
        request = make_request()
        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0]{.foo}.'})]
        )
        outcome = compose_artifact(
            request, store=store, claims=claims, runner=runner, max_attempts=2
        )
        assert outcome.status == "error" and outcome.code == "citation-unresolved"
        assert not store.output_path(request.artifact_id).exists()

    def test_multi_part_citing_body_resolves_and_persists(self, store, claims):
        _requires_pandoc()
        # A `[@s0]` in ANY part body trips the gate; a projected key resolves → composes + persists.
        request = make_request(format_parts=("slides", "presenter-notes"))
        runner = ScriptedRunner(
            [
                writer_ok(
                    {
                        "parts": {
                            "slides": '# Deck\n\n- [linear time]{.EXTRACTED data-fact="f0"} [@s0]',
                            "presenter-notes": "Speaker notes, ungrounded prose.",
                        }
                    }
                )
            ]
        )
        outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
        assert outcome.status == "ok"
        persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
        assert [r["id"] for r in persisted["references"]] == ["s0"]

    def test_injected_pandoc_runner_drives_the_gate(self, store, claims):
        # The pandoc seam is INJECTABLE (mirrors serialize.parse_to_ast's `runner`): a fake runner
        # returning a canned, api-version-pinned AST with an UNPROJECTED `Cite` id blocks WITHOUT
        # the real binary — so a compose test can drive the C4 gate with no pandoc installed.
        request = make_request()  # projects s0 only
        fake_ast = {
            "pandoc-api-version": list(PANDOC_API_VERSION),
            "meta": {},
            "blocks": [
                {
                    "t": "Para",
                    "c": [
                        {
                            "t": "Cite",
                            "c": [
                                [
                                    {
                                        "citationId": "nope",
                                        "citationPrefix": [],
                                        "citationSuffix": [],
                                        "citationMode": {"t": "NormalCitation"},
                                        "citationNoteNum": 1,
                                        "citationHash": 0,
                                    }
                                ],
                                [{"t": "Str", "c": "[@nope]"}],
                            ],
                        }
                    ],
                }
            ],
        }

        def pandoc_runner(args, stdin_text):
            return PandocOutcome(returncode=0, stdout=json.dumps(fake_ast), stderr="")

        runner = ScriptedRunner(
            [writer_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"} — see [@s0].'})]
        )
        outcome = compose_artifact(
            request,
            store=store,
            claims=claims,
            runner=runner,
            pandoc_runner=pandoc_runner,
            max_attempts=1,
        )
        assert outcome.status == "error" and outcome.code == "citation-unresolved"
        assert not store.output_path(request.artifact_id).exists()
