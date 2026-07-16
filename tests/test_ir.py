"""Step-24 tests: `pipeline/ir.py` — the IR-canonical model + its §15 validation schema.

Covers (each an acceptance line or a §15 RI1–RI4 clause):

- **IR fixtures validate** against the schema — flat single-part and multi-part envelopes.
- **The composition binding reproduces the artifact-id byte-exact** (§15 RI4/§7.4): the
  recorded id equals `mint_artifact_id(preimage)` and the digest equals `digest_full`.
- **Flat-body collapse** (§15): 0 or 1 declared parts → a flat `body`; a 0- or 1-element
  `parts` list is a defect.
- **The grounding ledger is a CLOSED schema and secret-free** (§15 RI3/§3.3): an undeclared
  key, a missing key, or a bad tier is refused; a secret-shaped value ANYWHERE in the ledger
  (or the metadata bag) is refused — while a plain hex commit SHA is NEVER flagged.
- **The inline-reference gate** (§6.5/§16 via §17 RI8): an unknown `data-fact` id, a
  class-less grounded span, and a non-EXTRACTED lead asserted as EXTRACTED (tier promotion)
  are all refused; an INFERRED lead tagged `.INFERRED` is legal.
- **Implicit sequence** (§15 RI2/A4-4): a part carrying an explicit `sequence` field is
  refused; the ordinal is positional.
"""

from __future__ import annotations

import pytest

from pipeline.canonical import digest_full
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id, part_id
from pipeline.ir import (
    IR_VERSION,
    PANDOC_API_VERSION,
    TOP_LEVEL_KEYS,
    BindingMismatchError,
    EmptySubstanceError,
    SchemaViolation,
    SecretShapedValueError,
    TierViolation,
    UnknownFactError,
    build_ir,
    extract_fact_refs,
    looks_secret_shaped,
    unwrap_ir,
    validate_grounding_ledger,
    validate_ir,
)

# --- fixtures ------------------------------------------------------------------------------

#: A legitimate 40-hex commit SHA — MUST never be flagged as secret-shaped.
COMMIT_SHA = "9f3c07d21b44e8aa9f3c07d21b44e8aa9f3c07d2"


def make_preimage() -> dict:
    """A canonical §7.2 artifact preimage over slug-valid coordinates."""
    return build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("readme"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
    )


def ledger_entry(**overrides) -> dict:
    entry = {
        "tier": "EXTRACTED",
        "source_instance_id": "acme-graph",
        "source_repo": "github.com/acme/widget",
        "source_commit": COMMIT_SHA,
        "traceability_anchor": ["file-line:src/parser.py:42"],
        "scores_snapshot": {"trusted": 5, "review_status": "merged"},
    }
    entry.update(overrides)
    return entry


def one_fact_ledger(**overrides) -> dict:
    return {"f0": ledger_entry(**overrides)}


@pytest.fixture
def preimage() -> dict:
    return make_preimage()


@pytest.fixture
def artifact_id(preimage) -> str:
    return mint_artifact_id(preimage)


# --- IR fixtures validate (both shapes) ----------------------------------------------------


class TestValidEnvelopes:
    def test_flat_single_part_envelope_validates(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body='The parser runs in [linear time]{.EXTRACTED data-fact="f0"}.',
        )
        validate_ir(doc)  # idempotent — build_ir already validated
        assert "body" in doc and "parts" not in doc
        assert doc["ir_version"] == IR_VERSION
        assert doc["pandoc_api_version"] == list(PANDOC_API_VERSION)

    def test_multi_part_envelope_validates(self, preimage, artifact_id):
        parts = [
            {
                "part-id": part_id(artifact_id, "slides"),
                "role": "slides",
                "packaging_hint": "in-document",
                "body": '# Title\n\n- [a point]{.EXTRACTED data-fact="f0"}',
            },
            {
                "part-id": part_id(artifact_id, "presenter-notes"),
                "role": "presenter-notes",
                "packaging_hint": "standalone",
                "body": "Speaker notes, no grounded claims here.",
            },
        ]
        doc = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding=one_fact_ledger(), parts=parts
        )
        validate_ir(doc)
        assert [p["role"] for p in doc["parts"]] == ["slides", "presenter-notes"]

    def test_metadata_bag_rides_through(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body="Prose without any grounded span is legal.",
            metadata={"campaign": "launch", "priority": 3},
        )
        assert doc["metadata"] == {"campaign": "launch", "priority": 3}

    def test_anchorless_extracted_and_null_commit_are_legal(self, preimage, artifact_id):
        # SM9: an EXTRACTED fact may be anchor-less; a commitless (folder) adapter → null.
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(traceability_anchor=[], source_commit=None),
            body='A [claim]{.EXTRACTED data-fact="f0"} with no anchor.',
        )
        assert doc["grounding"]["f0"]["source_commit"] is None


# --- Composition binding reproduces the artifact-id byte-exact (§15 RI4) --------------------


class TestCompositionBinding:
    def test_binding_preimage_reproduces_the_artifact_id_byte_exact(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="No grounded spans."
        )
        binding = doc["binding"]
        assert binding["artifact_id"] == artifact_id
        assert mint_artifact_id(binding["preimage"]) == artifact_id
        assert binding["digest"] == digest_full(binding["preimage"])
        assert digest_full(binding["preimage"])[:16] == artifact_id.split("-", 1)[1]

    def test_forged_artifact_id_is_refused(self, preimage):
        # A binding whose id does not mint from its preimage is a forgery — refused.
        wrong = "a-0000000000000000"
        with pytest.raises(BindingMismatchError):
            build_ir(artifact_id=wrong, preimage=preimage, grounding={}, body="x")

    def test_tampered_digest_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        doc["binding"]["digest"] = "deadbeef" * 8
        with pytest.raises(BindingMismatchError):
            validate_ir(doc)


# --- Flat-body collapse (§15) --------------------------------------------------------------


class TestFlatBodyCollapse:
    def test_zero_or_one_element_parts_list_is_refused(self, preimage, artifact_id):
        one_part = [
            {
                "part-id": part_id(artifact_id, "solo"),
                "role": "solo",
                "packaging_hint": "in-document",
                "body": "only part",
            }
        ]
        with pytest.raises(SchemaViolation):
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, parts=one_part)

    def test_both_parts_and_body_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        doc["parts"] = []
        with pytest.raises(SchemaViolation):
            validate_ir(doc)

    def test_neither_parts_nor_body_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        del doc["body"]
        with pytest.raises(SchemaViolation):
            validate_ir(doc)


# --- The grounding ledger: closed schema + no secrets (§15 RI3 / §3.3) ----------------------


class TestGroundingLedgerSchema:
    def test_undeclared_ledger_key_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(access_token="smuggled"))

    def test_missing_ledger_key_is_refused(self):
        entry = ledger_entry()
        del entry["source_repo"]
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger({"f0": entry})

    def test_bad_tier_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(tier="GOSPEL"))

    def test_bad_fact_id_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger({"../etc": ledger_entry()})

    def test_commit_sha_is_never_flagged_as_secret(self):
        # A 40-hex commit SHA is legitimate ledger data — pattern-based, not entropy-based.
        assert looks_secret_shaped(COMMIT_SHA) is None
        validate_grounding_ledger(one_fact_ledger(source_commit=COMMIT_SHA))


class TestNoSecretsInLedger:
    @pytest.mark.parametrize(
        "field,value",
        [
            ("source_repo", "https://user:s3cr3t-pw@github.com/acme/widget"),
            ("source_repo", "git@host/repo -----BEGIN OPENSSH PRIVATE KEY-----"),
            ("source_commit", "sk-live-0123456789abcdefghijklmn"),
        ],
    )
    def test_secret_shaped_scalar_field_is_refused(self, field, value):
        with pytest.raises(SecretShapedValueError):
            validate_grounding_ledger(one_fact_ledger(**{field: value}))

    def test_secret_hidden_in_scores_snapshot_is_refused(self):
        # The scan recurses — a token in a nested scores value is still caught.
        with pytest.raises(SecretShapedValueError):
            validate_grounding_ledger(
                one_fact_ledger(scores_snapshot={"note": "ghp_0123456789abcdefghij0123456789"})
            )

    def test_secret_in_metadata_bag_is_refused(self, preimage, artifact_id):
        with pytest.raises(SecretShapedValueError):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding={},
                body="x",
                metadata={"webhook": "https://svc:p4ssword@hooks.example.com/x"},
            )

    @pytest.mark.parametrize(
        "sample",
        [
            "authorization: bearer abcdefghijklmnop",
            "-----BEGIN RSA PRIVATE KEY-----",
            "AKIAIOSFODNN7EXAMPLE",
            "eyJhbGciOi.eyJzdWIiOiIx.SflKxwRJSMeKKF2Q",
            "client_secret=hunter2hunter2",
        ],
    )
    def test_looks_secret_shaped_flags_known_shapes(self, sample):
        assert looks_secret_shaped(sample) is not None


# --- The inline-reference gate (§6.5/§16 via §17 RI8) --------------------------------------


class TestInlineReferenceGate:
    def test_unknown_fact_id_is_refused(self, preimage, artifact_id):
        with pytest.raises(UnknownFactError):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(),
                body='A [claim]{.EXTRACTED data-fact="f9"}.',
            )

    def test_tier_promotion_of_a_lead_is_refused(self, preimage, artifact_id):
        # ledger tier INFERRED, span asserts EXTRACTED — a lead published as fact.
        with pytest.raises(TierViolation):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(tier="INFERRED"),
                body='A [lead]{.EXTRACTED data-fact="f0"}.',
            )

    def test_classless_grounded_span_is_refused(self, preimage, artifact_id):
        with pytest.raises(TierViolation):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(),
                body='A [claim]{data-fact="f0"} with no tier class.',
            )

    def test_inferred_lead_tagged_with_its_own_tier_is_legal(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(tier="INFERRED"),
            body='One indication is [this pattern]{.INFERRED data-fact="f0"}, to verify.',
        )
        assert doc["grounding"]["f0"]["tier"] == "INFERRED"

    def test_extract_fact_refs_parses_spans_and_ignores_plain_links(self):
        md = (
            'See [the docs](https://x) and a [grounded claim]{.EXTRACTED data-fact="f1"} '
            "plus [styled]{.highlight} text."
        )
        refs = extract_fact_refs(md, where="body")
        assert len(refs) == 1
        assert (refs[0].fact_id, refs[0].tier) == ("f1", "EXTRACTED")


# --- Balanced-bracket span extraction (§17 RI7/RI8): nested brackets are not a blind spot ---
#
# The old `[^\]]*` span regex could not span visible text containing a `]`, so a grounded span
# like `[a lead about foo[1] bar]{.EXTRACTED data-fact="f0"}` extracted ZERO refs — a
# tier-promotion or unknown-fact-id inside it rode straight through the ONLY deterministic
# tier-honesty gate. The scanner now matches Pandoc's balanced `bracketed_spans` reader.


class TestBalancedBracketSpanExtraction:
    #: A grounded span whose VISIBLE TEXT nests balanced brackets (a footnote-style `[1]`).
    NESTED = 'A [lead about foo[1] bar]{{.{tier} data-fact="{fid}"}} asserted.'

    def test_nested_bracket_span_is_extracted(self):
        # (1) extraction: the nested-bracket span is now SEEN (old regex returned 0 refs).
        refs = extract_fact_refs(
            self.NESTED.format(tier="EXTRACTED", fid="f0"), where="body"
        )
        assert len(refs) == 1
        assert (refs[0].fact_id, refs[0].tier) == ("f0", "EXTRACTED")

    def test_link_with_nested_brackets_is_still_ignored(self):
        # `items[0]` visible text, but followed by `(url)` not `{attrs}` → a link, not a span.
        refs = extract_fact_refs("See [items[0] here](https://x).", where="body")
        assert refs == ()

    def test_honest_nested_bracket_span_passes(self, preimage, artifact_id):
        # REQUIRED (1): a LEGITIMATE honest span with nested brackets + correct tier BUILDS.
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),  # f0 EXTRACTED
            body=self.NESTED.format(tier="EXTRACTED", fid="f0"),
        )
        assert doc["grounding"]["f0"]["tier"] == "EXTRACTED"

    def test_unknown_fact_id_in_nested_bracket_span_is_refused(self, preimage, artifact_id):
        # REQUIRED (2): an unknown fact-id inside a nested-bracket span is caught.
        with pytest.raises(UnknownFactError):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(),  # only f0 exists
                body=self.NESTED.format(tier="EXTRACTED", fid="f9"),
            )

    def test_tier_promotion_in_nested_bracket_span_is_refused(self, preimage, artifact_id):
        # REQUIRED (3): the reviewer's confirmed bug — INFERRED ledger, span asserts EXTRACTED
        # inside nested brackets. Previously BUILT (0 refs extracted); now REFUSED.
        with pytest.raises(TierViolation):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(tier="INFERRED"),
                body=self.NESTED.format(tier="EXTRACTED", fid="f0"),
            )

    def test_crafted_undercount_fails_closed(self, preimage, artifact_id):
        # REQUIRED (4): a `data-fact` attribute that is NOT inside a parseable span (here loose
        # in prose) is a genuine undercount — the fail-closed backstop refuses it.
        with pytest.raises(SchemaViolation):
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(),
                body='A stray data-fact="f0" sits outside any span.',
            )

    def test_undercount_backstop_fires_on_unbalanced_span(self):
        # An unbalanced `[` never closes → no span → the data-fact is uncaptured → fail closed.
        with pytest.raises(SchemaViolation):
            extract_fact_refs('[unclosed {.EXTRACTED data-fact="f0"}', where="body")

    def test_honest_nested_grounded_span_never_false_refuses(self, preimage, artifact_id):
        # A grounded span nested inside another span's VISIBLE TEXT: Pandoc parses both, so both
        # must be extracted (else the fail-closed cross-check would false-refuse honest content).
        body = (
            'A [summary citing [detail]{.INFERRED data-fact="f1"} inline]'
            '{.EXTRACTED data-fact="f0"} holds.'
        )
        refs = extract_fact_refs(body, where="body")
        assert {(r.fact_id, r.tier) for r in refs} == {("f0", "EXTRACTED"), ("f1", "INFERRED")}
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding={"f0": ledger_entry(), "f1": ledger_entry(tier="INFERRED")},
            body=body,
        )
        assert set(doc["grounding"]) == {"f0", "f1"}


# --- Parts: implicit sequence, part-id binding, uniqueness (§15 RI2) -----------------------


class TestPartShape:
    def _parts(self, artifact_id):
        return [
            {
                "part-id": part_id(artifact_id, "slides"),
                "role": "slides",
                "packaging_hint": "in-document",
                "body": "slides body",
            },
            {
                "part-id": part_id(artifact_id, "notes"),
                "role": "notes",
                "packaging_hint": "in-document",
                "body": "notes body",
            },
        ]

    def test_explicit_sequence_field_is_refused(self, preimage, artifact_id):
        parts = self._parts(artifact_id)
        parts[0]["sequence"] = 0
        with pytest.raises(SchemaViolation):
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, parts=parts)

    def test_part_id_must_be_the_composite_handle(self, preimage, artifact_id):
        parts = self._parts(artifact_id)
        parts[0]["part-id"] = part_id(artifact_id, "wrong-role")
        with pytest.raises(SchemaViolation):
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, parts=parts)

    def test_bad_packaging_hint_is_refused(self, preimage, artifact_id):
        parts = self._parts(artifact_id)
        parts[0]["packaging_hint"] = "sideways"
        with pytest.raises(SchemaViolation):
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, parts=parts)

    def test_duplicate_roles_are_refused(self, preimage, artifact_id):
        dup = [
            {
                "part-id": part_id(artifact_id, "slides"),
                "role": "slides",
                "packaging_hint": "in-document",
                "body": f"body {i}",
            }
            for i in range(2)
        ]
        with pytest.raises(SchemaViolation):
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, parts=dup)


# --- Top-level schema + stamps -------------------------------------------------------------


class TestTopLevelSchema:
    def test_unknown_top_level_key_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        doc["extra"] = 1
        with pytest.raises(SchemaViolation):
            validate_ir(doc)

    def test_wrong_pandoc_api_version_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        doc["pandoc_api_version"] = [1, 22]
        with pytest.raises(SchemaViolation):
            validate_ir(doc)

    def test_wrong_ir_version_is_refused(self, preimage, artifact_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        doc["ir_version"] = 999
        with pytest.raises(SchemaViolation):
            validate_ir(doc)


# --- The §15 substance floor (GAP-6): a body whose VISIBLE text has no letter/digit is refused ---


class TestSubstanceFloor:
    @pytest.mark.parametrize("body", ["...", "…", "   ", "###", "---", "* * *"])
    def test_flat_substanceless_body_is_refused_with_the_substance_code(
        self, preimage, artifact_id, body
    ):
        # Every one of these PARSES/validates as non-empty under bare truthiness yet ships empty.
        with pytest.raises(EmptySubstanceError) as exc:
            build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body=body)
        assert exc.value.code == "ir-empty-substance"

    def test_markup_wrapped_placeholder_is_refused_by_the_substance_floor(
        self, preimage, artifact_id
    ):
        # F4: seed f0 EXTRACTED so the floor (:632) is the ONLY rejection path — it PRECEDES the
        # ref-check (:633). A broken stripper that kept the attrs' letters ("EXTRACTED"/"data"/
        # "fact") would PASS the floor and then BUILD (f0 known, tier matches) → this test fails; a
        # correct stripper yields visible text `...` → EmptySubstanceError. Asserting the SUBSTANCE
        # code rules out a wrong-reason pass (e.g. UnknownFactError had f0 not been seeded).
        with pytest.raises(EmptySubstanceError) as exc:
            build_ir(
                artifact_id=artifact_id,
                preimage=preimage,
                grounding=one_fact_ledger(),  # f0 EXTRACTED
                body='[...]{.EXTRACTED data-fact="f0"}',
            )
        assert exc.value.code == "ir-empty-substance"

    def test_part_substanceless_body_is_refused(self, preimage, artifact_id):
        parts = [
            {
                "part-id": part_id(artifact_id, "slides"),
                "role": "slides",
                "packaging_hint": "in-document",
                "body": '# [a point]{.EXTRACTED data-fact="f0"}',
            },
            {
                "part-id": part_id(artifact_id, "notes"),
                "role": "notes",
                "packaging_hint": "in-document",
                "body": "...",  # substance-free — refused
            },
        ]
        with pytest.raises(EmptySubstanceError) as exc:
            build_ir(
                artifact_id=artifact_id, preimage=preimage, grounding=one_fact_ledger(), parts=parts
            )
        assert exc.value.code == "ir-empty-substance"

    @pytest.mark.parametrize("body", ["x", "5", "文", "hi there"])
    def test_letter_or_digit_bearing_body_is_accepted(self, preimage, artifact_id, body):
        # A single letter/digit (incl. CJK) passes: a hard SHAPE gate, not a quality judgment.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body=body)
        assert doc["body"] == body

    def test_grounded_span_body_is_accepted(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body='The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.',
        )
        assert "body" in doc


class TestVisibleTextStripper:
    """Pin the visible-text stripper DIRECTLY (F4): a broken stripper is caught here independently
    of build_ir. It reuses only `match_bracket`, keeps visible text, drops `{attrs}` blocks."""

    def test_strips_span_attrs_and_keeps_visible_text(self):
        from pipeline.ir import _visible_text  # a private helper — imported locally, not at top

        assert _visible_text('[...]{.EXTRACTED data-fact="f0"}') == "..."
        assert _visible_text('X [claim]{.EXTRACTED data-fact="f0"} Y') == "X claim Y"
        assert _visible_text("[a]{.A}[b]{.B}") == "ab"
        assert _visible_text("[[in]{.X}]{.Y}") == "in"  # recurses into nested span visible text
        assert _visible_text("see [x](http://u)") == "see [x](http://u)"  # a link, not a span


# --- unwrap_ir (GAP-1a): tolerate both persisted record shapes; the coupling is guarded ----------


class TestUnwrapIr:
    def test_wrapped_record_unwraps_to_the_inner_ir(self):
        assert unwrap_ir({"ir": {"body": "x"}, "binding": {"z": 1}}) == {"body": "x"}

    def test_raw_envelope_returns_itself(self):
        raw = {"body": "x", "binding": {"z": 1}, "grounding": {}}
        assert unwrap_ir(raw) == raw

    def test_ir_is_not_a_top_level_key(self):
        # NEW-E: the discriminator's totality guard — a raw IR can never carry a top-level `"ir"`.
        assert "ir" not in TOP_LEVEL_KEYS
