"""Step-25 tests: `pipeline/reconcile.py` — the reconcile pass core, transport MOCKED.

Every test that exercises the reconciler LLM injects a fake `Runner` (a `ScriptedRunner`
returning canned `ProcessOutcome`s) or a `NeverRunner` — NO real `claude` process is
spawned (durable rule: tests mock transport). Covers, per the acceptance list:

- **the reconcile-inputs preimage excludes EXACTLY the §16 exclusion list** and includes
  exactly the four §16 components, delta-vs-floor (an at-floor attribute churns nothing);
- **the fit-binding preimage reproduces the fitted-id deterministically** — the SAME preimage
  yields the SAME fitted-id across runs, and `minted_ts` (a record field) is NOT in identity;
- **the no-op path is a bit-identical IR passthrough with ZERO LLM** (a `pass` fit that fits);
- **fidelity validation catches a dropped-fact fixture AND a tier-promotion fixture** — both
  are re-asked to the bound and NEVER fitted; an EXPLICIT drop-as-lead is accepted;
- **the hard-limit gate blocks unfittable content while a sibling still fits** (block
  isolation — a per-item block is a typed outcome, never an exception);
- **each reshape strategy path** (`adapt`/`split`/`truncate` via the LLM, `pass` deterministic);
- a transport-level failure surfaces immediately (not re-asked); wiring defects raise loudly.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline import ir
from pipeline.canonical import canonical_json_bytes, canonical_json_str
from pipeline.ids import (
    EntryBinding,
    build_artifact_preimage,
    fitted_id,
    mint_artifact_id,
    part_id,
)
from pipeline.reconcile import (
    CODE_FIDELITY_VIOLATION,
    CODE_HARD_LIMIT_EXCEEDED,
    RECONCILE_INPUT_COMPONENTS,
    RECONCILE_INPUT_EXCLUSIONS,
    ReconcileError,
    ReconcileRequest,
    breached_limits,
    build_reconciler_prompt,
    fit_digest,
    reconcile,
    reconcile_inputs_preimage,
)
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


def reconciler_content(fitted, *, dropped=None, echo=None) -> dict:
    return {
        "fitted": fitted,
        "dropped_facts": list(dropped or []),
        "voice_content_echo": echo if echo is not None else {"tone": "business"},
    }


def reconciler_ok(fitted, *, dropped=None, echo=None) -> ProcessOutcome:
    """A successful transport call whose `.result` is the reconciler's declaration JSON."""
    return ok_outcome(json.dumps(reconciler_content(fitted, dropped=dropped, echo=echo)))


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
    """A fake `Runner` that must never be invoked (the no-op / pass / block paths)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, request: ProcessRequest) -> ProcessOutcome:  # pragma: no cover
        self.calls += 1
        raise AssertionError("the reconciler transport must not be invoked on this path")


# --- fixtures + builders -------------------------------------------------------------------


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


def ledger_entry(*, tier: str = "EXTRACTED") -> dict:
    return {
        "tier": tier,
        "source_instance_id": "acme-graph",
        "source_repo": "github.com/acme/widget",
        "source_commit": COMMIT_SHA,
        "traceability_anchor": ["file-line:src/parser.py:42"],
        "scores_snapshot": {"trusted": 5, "review_status": "merged"},
    }


def make_canonical_ir(*, body=None, parts=None, grounding=None) -> dict:
    """A valid §15 IR-canonical envelope (via ir.build_ir) — the fit input."""
    preimage = make_preimage()
    artifact_id = mint_artifact_id(preimage)
    if grounding is None:
        grounding = {"f0": ledger_entry()}
    if body is None and parts is None:
        body = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'
    return ir.build_ir(
        artifact_id=artifact_id,
        preimage=preimage,
        grounding=grounding,
        body=body,
        parts=parts,
    )


def make_request(*, canonical_ir=None, strategy="adapt", **overrides) -> ReconcileRequest:
    ci = canonical_ir if canonical_ir is not None else make_canonical_ir()
    base = {
        "canonical_ir": ci,
        "artifact_id": ci["binding"]["artifact_id"],
        "platform": "linkedin",
        "language": "en",
        "source_language": "en",
        "strategy": strategy,
        "hard_limits": {},
        "voice_content_params": {"tone": "business"},
    }
    base.update(overrides)
    return ReconcileRequest(**base)


# --- the reconcile-inputs preimage: excludes EXACTLY the §16 list (delta-vs-floor) ---------


class TestReconcileInputsPreimage:
    def test_preimage_carries_exactly_the_four_components(self):
        request = make_request(
            strategy="split",
            advisory={"heading_style": "title-case"},
            render_dims={"emphasis": "bold"},
            hard_limits={"max_chars": 500},
            hard_limit_defaults={"max_chars": 1000},
        )
        preimage = reconcile_inputs_preimage(request)
        assert set(preimage) == set(RECONCILE_INPUT_COMPONENTS)
        # The non-default strategy, advisory, render-dim, and breached limit all enter.
        text = canonical_json_str(preimage)
        assert preimage["strategy"] == {"strategy": "split"}
        assert preimage["hard-limits"] == {"max_chars": 500}
        assert "title-case" in text and "bold" in text

    def test_at_floor_attributes_churn_nothing(self):
        # A strategy at the `adapt` floor and a hard limit at its default are ABSENT (CA6).
        request = make_request(
            strategy="adapt",
            hard_limits={"max_chars": 1000, "max_words": 100},
            hard_limit_defaults={"max_chars": 1000, "max_words": 100},
        )
        preimage = reconcile_inputs_preimage(request)
        assert preimage["strategy"] == {}  # adapt == floor → no churn
        assert preimage["hard-limits"] == {}  # both limits at default → no churn

    def test_preimage_excludes_exactly_the_section16_list(self):
        # Distinctive sentinels in EVERY excluded field; none may reach the preimage bytes.
        request = make_request(
            strategy="split",
            platform="linkedin",
            language="fr",
            hard_limits={"max_chars": 500},
            hard_limit_defaults={"max_chars": 1000},
            voice_content_params={"marker": "vvv-sentinel"},
            serialize_pins={"marker": "ppp-sentinel"},
            presentation_inputs={"marker": "rrr-sentinel"},
            schema_version="sss-sentinel",
            metadata={"marker": "mmm-sentinel"},
        )
        text = canonical_json_str(reconcile_inputs_preimage(request))
        for sentinel in (
            "vvv-sentinel",  # voice/content params
            "ppp-sentinel",  # serialize-side pins
            "rrr-sentinel",  # Presentation inputs
            "sss-sentinel",  # schema_version
            "mmm-sentinel",  # the metadata bag
            "linkedin",  # platform coordinate
            "fr",  # language coordinate
        ):
            assert sentinel not in text, sentinel
        # And the exclusion list is EXACTLY the design's seven items (neither wider nor narrower).
        assert len(RECONCILE_INPUT_EXCLUSIONS) == 7

    def test_identical_logical_inputs_yield_identical_preimage_bytes(self):
        # Input order never matters — the canonical form is stable.
        a = reconcile_inputs_preimage(
            make_request(strategy="split", advisory={"x": 1, "y": 2}, advisory_defaults={})
        )
        b = reconcile_inputs_preimage(
            make_request(strategy="split", advisory={"y": 2, "x": 1}, advisory_defaults={})
        )
        assert canonical_json_bytes(a) == canonical_json_bytes(b)


# --- the fit-binding: deterministic fitted-id; minted_ts NOT in identity -------------------


class TestFitBindingDeterminism:
    def test_same_preimage_reproduces_the_fitted_id_across_runs_regardless_of_minted_ts(self):
        request = make_request(strategy="adapt")
        content = reconciler_ok({"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'})
        out1 = reconcile(
            request,
            runner=ScriptedRunner([content]),
            revision=True,
            minted_ts="2020-01-01T00:00:00+00:00",
        )
        out2 = reconcile(
            request,
            runner=ScriptedRunner([content]),
            revision=True,
            minted_ts="2099-12-31T23:59:59+00:00",
        )
        assert out1.status == "ok" and out2.status == "ok"
        # Identity (preimage → digest → fitted-id) is byte-reproducible; minted_ts is not in it.
        assert out1.fit_binding["fitted_id"] == out2.fit_binding["fitted_id"]
        assert out1.fit_binding["preimage"] == out2.fit_binding["preimage"]
        assert out1.fit_binding["digest"] == out2.fit_binding["digest"]
        assert out1.fit_binding["minted_ts"] != out2.fit_binding["minted_ts"]

    def test_revision_fitted_id_carries_the_preimage_digest_as_the_fit_revision(self):
        request = make_request(strategy="adapt")
        out = reconcile(
            request,
            runner=ScriptedRunner([reconciler_ok({"body": 'A [c]{.EXTRACTED data-fact="f0"}.'})]),
            revision=True,
            minted_ts="2026-07-13T00:00:00+00:00",
        )
        digest = fit_digest(reconcile_inputs_preimage(request))
        assert out.digest == digest and len(digest) == 12
        expected = fitted_id(
            request.artifact_id, request.platform, request.language, fit_revision=digest
        )
        assert out.fit_binding["fitted_id"] == expected == out.fitted_id
        # The fit-revision `_hex12` rides the language segment (§7.4).
        assert f".{request.language}_{digest}" in expected

    def test_baseline_fitted_id_is_the_unqualified_template(self):
        request = make_request(strategy="pass")  # deterministic, no LLM
        out = reconcile(request, runner=NeverRunner(), revision=False)
        assert out.status == "ok"
        baseline = fitted_id(request.artifact_id, request.platform, request.language)
        assert out.fit_binding["fitted_id"] == baseline
        assert "_" not in baseline  # no revision qualifier on the never-forced path


# --- the no-op path: bit-identical passthrough, ZERO LLM -----------------------------------


class TestNoOpPath:
    def test_pass_that_fits_is_a_bit_identical_passthrough_with_zero_llm(self):
        canonical = make_canonical_ir()
        request = make_request(canonical_ir=canonical, strategy="pass", hard_limits={})
        never = NeverRunner()
        out = reconcile(request, runner=never)
        assert never.calls == 0  # ZERO LLM on the no-op path
        assert out.status == "ok" and out.is_noop is True and out.attempts == 0
        # IR-fitted ≡ IR-canonical, byte-for-byte (§16).
        assert canonical_json_bytes(out.fitted_ir) == canonical_json_bytes(canonical)
        assert out.fit_binding["outcome"]["gate_outcome"] == "fit"

    def test_adapt_that_fits_still_invokes_the_llm_and_is_not_a_noop(self):
        # Only `pass` no-ops; `adapt` always reshapes (§16 "no reshape requested" is `pass`).
        request = make_request(strategy="adapt", hard_limits={})
        reshaped = 'Reshaped [c]{.EXTRACTED data-fact="f0"}.'
        runner = ScriptedRunner([reconciler_ok({"body": reshaped})])
        out = reconcile(request, runner=runner)
        assert out.status == "ok" and out.is_noop is False
        assert runner.calls == 1


# --- fidelity validation: dropped-fact + tier-promotion fixtures ---------------------------


class TestFidelityValidation:
    def _two_fact_ir(self):
        grounding = {"f0": ledger_entry(), "f1": ledger_entry()}
        body = (
            'A [first]{.EXTRACTED data-fact="f0"} and a '
            '[second]{.EXTRACTED data-fact="f1"} claim.'
        )
        return make_canonical_ir(body=body, grounding=grounding)

    def test_a_silently_dropped_fact_is_rejected_and_never_fitted(self):
        request = make_request(canonical_ir=self._two_fact_ir(), strategy="adapt")
        # The reshaped body drops f1 WITHOUT declaring it — a silent drop.
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'Only [first]{.EXTRACTED data-fact="f0"}.'})]
        )
        out = reconcile(request, runner=runner, max_attempts=2)
        assert out.status == "error" and out.code == CODE_FIDELITY_VIOLATION
        assert out.fitted_ir is None and out.attempts == 2
        assert any("f1" in v for v in out.violations)

    def test_an_explicit_drop_as_lead_is_accepted(self):
        request = make_request(canonical_ir=self._two_fact_ir(), strategy="truncate")
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'Only [first]{.EXTRACTED data-fact="f0"}.'}, dropped=["f1"])]
        )
        out = reconcile(request, runner=runner)
        assert out.status == "ok" and out.dropped_facts == ("f1",)
        assert out.fit_binding["outcome"]["strategy"] == "truncate"

    def test_a_tier_promotion_is_rejected_and_never_fitted(self):
        # The fact is INFERRED; the reconciler re-anchors it as EXTRACTED — tier promotion.
        grounding = {"f0": ledger_entry(tier="INFERRED")}
        canonical = make_canonical_ir(
            body='A [lead]{.INFERRED data-fact="f0"}.', grounding=grounding
        )
        request = make_request(canonical_ir=canonical, strategy="adapt")
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'A [lead]{.EXTRACTED data-fact="f0"}.'})]
        )
        out = reconcile(request, runner=runner, max_attempts=2)
        assert out.status == "error" and out.code == CODE_FIDELITY_VIOLATION
        assert out.fitted_ir is None
        assert any("tier" in v.lower() for v in out.violations)

    def test_a_dropped_non_ledger_fact_is_rejected(self):
        request = make_request(strategy="truncate")
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'A [c]{.EXTRACTED data-fact="f0"}.'}, dropped=["f9"])]
        )
        out = reconcile(request, runner=runner, max_attempts=1)
        assert out.status == "error" and out.code == CODE_FIDELITY_VIOLATION

    def test_an_unechoed_voice_parameter_is_rejected(self):
        request = make_request(strategy="adapt", voice_content_params={"tone": "business"})
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'A [c]{.EXTRACTED data-fact="f0"}.'}, echo={"tone": "casual"})]
        )
        out = reconcile(request, runner=runner, max_attempts=1)
        assert out.status == "error" and out.code == CODE_FIDELITY_VIOLATION

    def test_a_self_healing_reconciler_within_the_bound_is_fitted(self):
        request = make_request(canonical_ir=self._two_fact_ir(), strategy="adapt")
        runner = ScriptedRunner(
            [
                reconciler_ok({"body": 'Only [first]{.EXTRACTED data-fact="f0"}.'}),  # silent drop
                reconciler_ok(  # attempt 2: re-anchors both facts
                    {
                        "body": (
                            'A [first]{.EXTRACTED data-fact="f0"} and '
                            '[second]{.EXTRACTED data-fact="f1"}.'
                        )
                    }
                ),
            ]
        )
        out = reconcile(request, runner=runner, max_attempts=3)
        assert out.status == "ok" and out.attempts == 2
        assert len(out.violations) == 1


# --- the terminal hard-limit gate: block isolation (block-one-continue-others) -------------


class TestHardLimitGate:
    def test_unfittable_content_blocks_while_a_sibling_fits(self):
        # A per-item block is a typed OUTCOME, not an exception — siblings are independent.
        blocking = make_request(strategy="pass", hard_limits={"max_chars": 5})
        fitting = make_request(strategy="pass", hard_limits={})
        never = NeverRunner()

        blocked = reconcile(blocking, runner=never)
        assert blocked.status == "block" and blocked.code == CODE_HARD_LIMIT_EXCEEDED
        assert blocked.blocked_limits == ("max_chars",)
        assert blocked.fitted_ir is None and blocked.fit_binding is None
        assert blocked.preimage is not None  # the preimage/digest are computed before the gate

        # The sibling still fits — the block never fails the batch.
        fit = reconcile(fitting, runner=never)
        assert fit.status == "ok" and fit.is_noop is True

    def test_the_gate_is_terminal_after_reshape(self):
        # An `adapt` reshape runs (LLM) but STILL breaches — the gate blocks last (§16).
        request = make_request(strategy="adapt", hard_limits={"max_chars": 5})
        runner = ScriptedRunner(
            [reconciler_ok({"body": 'A long reshaped [claim]{.EXTRACTED data-fact="f0"}.'})]
        )
        out = reconcile(request, runner=runner)
        assert out.status == "block" and out.code == CODE_HARD_LIMIT_EXCEEDED
        assert out.attempts == 1 and out.fitted_ir is None

    def test_breached_limits_compares_only_shared_measurable_names(self):
        fitted = make_canonical_ir()  # a small body
        # An advisory-only / unmeasured limit name never blocks.
        assert breached_limits(fitted, {"max_slides": 3}) == ()
        assert breached_limits(fitted, {"max_chars": 5}) == ("max_chars",)

    def test_a_non_numeric_hard_limit_is_a_loud_wiring_defect(self):
        fitted = make_canonical_ir()
        with pytest.raises(ReconcileError):
            breached_limits(fitted, {"max_chars": "lots"})


# --- each reshape strategy path ------------------------------------------------------------


class TestReshapeStrategies:
    def test_adapt_reshapes_leaves_and_records_the_strategy(self):
        request = make_request(strategy="adapt")
        reshaped = 'Adapted for the platform: [linear time]{.EXTRACTED data-fact="f0"}.'
        out = reconcile(request, runner=ScriptedRunner([reconciler_ok({"body": reshaped})]))
        assert out.status == "ok" and out.fit_binding["outcome"]["strategy"] == "adapt"
        assert out.fitted_ir["body"] == reshaped
        ir.validate_ir(out.fitted_ir)  # the fitted IR is a valid IR envelope (fidelity reuse)

    def test_split_records_the_strategy_and_enters_the_preimage(self):
        request = make_request(strategy="split")
        split_body = 'Split: [c]{.EXTRACTED data-fact="f0"}.'
        out = reconcile(request, runner=ScriptedRunner([reconciler_ok({"body": split_body})]))
        assert out.status == "ok" and out.fit_binding["outcome"]["strategy"] == "split"
        assert out.preimage["strategy"] == {"strategy": "split"}  # non-default → in identity

    def test_pass_never_invokes_the_llm(self):
        out = reconcile(make_request(strategy="pass"), runner=NeverRunner())
        assert out.status == "ok" and out.attempts == 0

    def test_multi_part_reshape_preserves_the_part_topology(self):
        preimage = make_preimage()
        artifact_id = mint_artifact_id(preimage)
        parts = [
            {
                "part-id": part_id(artifact_id, "slides"),
                "role": "slides",
                "packaging_hint": "in-document",
                "body": '# Deck\n\n- [linear time]{.EXTRACTED data-fact="f0"}',
            },
            {
                "part-id": part_id(artifact_id, "notes"),
                "role": "notes",
                "packaging_hint": "in-document",
                "body": "Speaker notes, ungrounded prose.",
            },
        ]
        canonical = ir.build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding={"f0": ledger_entry()},
            parts=parts,
        )
        request = make_request(canonical_ir=canonical, strategy="adapt")
        runner = ScriptedRunner(
            [
                reconciler_ok(
                    {
                        "parts": {
                            "slides": '# Deck\n\n- [linear]{.EXTRACTED data-fact="f0"}',
                            "notes": "Reshaped speaker notes.",
                        }
                    }
                )
            ]
        )
        out = reconcile(request, runner=runner)
        assert out.status == "ok"
        assert [p["role"] for p in out.fitted_ir["parts"]] == ["slides", "notes"]
        assert out.fitted_ir["parts"][1]["body"] == "Reshaped speaker notes."


# --- transport failure surfaces immediately; wiring defects raise --------------------------


class TestTransportAndWiring:
    def test_backpressure_is_surfaced_and_not_reasked(self):
        request = make_request(strategy="adapt")
        runner = ScriptedRunner([backpressure_outcome()])
        out = reconcile(request, runner=runner, max_attempts=3)
        assert out.status == "error" and out.code == "rate-limit-backpressure"
        assert runner.calls == 1  # NOT re-asked — an account-side condition
        assert out.fitted_ir is None and out.transport_result is not None

    def test_unknown_strategy_is_a_loud_wiring_defect(self):
        request = make_request(strategy="mangle")
        with pytest.raises(ReconcileError):
            reconcile(request, runner=NeverRunner())

    def test_artifact_id_mismatch_is_a_loud_wiring_defect(self):
        request = make_request(strategy="pass", artifact_id="a-0000000000000000")
        with pytest.raises(ReconcileError):
            reconcile(request, runner=NeverRunner())

    def test_max_attempts_below_one_is_refused(self):
        with pytest.raises(ReconcileError):
            reconcile(make_request(strategy="adapt"), runner=NeverRunner(), max_attempts=0)

    def test_a_malformed_canonical_ir_is_a_loud_wiring_defect(self):
        request = ReconcileRequest(
            canonical_ir={"not": "an ir"},
            artifact_id="a-9f3c07d21b44e8aa",
            platform="linkedin",
            language="en",
            source_language="en",
            strategy="pass",
        )
        with pytest.raises(ReconcileError):
            reconcile(request, runner=NeverRunner())


# --- the reconciler prompt -----------------------------------------------------------------


class TestReconcilerPrompt:
    def test_prompt_carries_the_ledger_strategy_and_voice_params(self):
        request = make_request(strategy="split", voice_content_params={"tone": "business"})
        prompt = build_reconciler_prompt(request)
        assert '"f0"' in prompt  # the grounding ledger to re-anchor
        assert "split" in prompt  # the strategy
        assert "business" in prompt  # the voice/content params to echo
        assert "runs in linear time" in prompt  # the canonical leaves to reshape

    def test_reask_note_is_appended_on_correction(self):
        request = make_request(strategy="adapt")
        prompt = build_reconciler_prompt(request, reask_note="prior fit was rejected")
        assert "Correction required" in prompt and "prior fit was rejected" in prompt
