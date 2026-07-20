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
    ATTESTATION_RELATIONS,
    IR_VERSION,
    KNOWN_IR_VERSIONS,
    LEDGER_FIELDS,
    LEDGER_OPTIONAL,
    LEDGER_REQUIRED,
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


def valid_attestation(**overrides) -> dict:
    """A well-formed §15 RI3 (DR-6) scenario-2 attestation: a STRUCTURED CSL-JSON `primary`, a
    non-empty `anchor` into the held pool source, and a `wasQuotedFrom` PROV-O `relation`."""
    att = {
        "primary": {
            "type": "article-journal",
            "title": "On Linear-Time Parsing",
            "author": [{"family": "Smith", "given": "A."}],
            "issued": {"date-parts": [[2020]]},
            "DOI": "10.1000/xyz123",
        },
        "anchor": "file-line:docs/refs.md:5",
        "relation": "wasQuotedFrom",
    }
    att.update(overrides)
    return att


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


# --- The DR-6 attestation carrier (§15 RI3): the optional PROV-O scenario-2 pool-relation record --


class TestAttestationCarrier:
    """§15 RI3 (DR-6 COMMIT 2): the OPTIONAL PROV-O `attestation? {primary, anchor, relation}`
    scenario-2 pool-relation carrier. Validated ONLY when the key is present; a bare-string
    `primary`, an unknown sub-key, and a non-vocabulary `relation` are all refused."""

    def test_valid_attestation_validates(self):
        validate_grounding_ledger(one_fact_ledger(attestation=valid_attestation()))

    def test_attestation_rides_a_full_envelope(self, preimage, artifact_id):
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(attestation=valid_attestation()),
            body='The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.',
        )
        assert doc["grounding"]["f0"]["attestation"]["relation"] == "wasQuotedFrom"

    def test_bare_string_primary_is_refused(self):
        # checklist #8: `primary` is a STRUCTURED CSL-JSON Mapping, NEVER a bare citation string.
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(
                one_fact_ledger(attestation=valid_attestation(primary="Smith 2020"))
            )

    def test_unknown_attestation_sub_key_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(attestation=valid_attestation(smuggled="x")))

    def test_non_wasquotedfrom_relation_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(
                one_fact_ledger(attestation=valid_attestation(relation="wasDerivedFrom"))
            )

    def test_empty_anchor_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(attestation=valid_attestation(anchor="")))

    def test_missing_attestation_sub_key_is_refused(self):
        att = valid_attestation()
        del att["anchor"]
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(attestation=att))

    def test_non_mapping_attestation_is_refused(self):
        with pytest.raises(SchemaViolation):
            validate_grounding_ledger(one_fact_ledger(attestation="wasQuotedFrom"))

    def test_primary_csl_key_set_stays_open(self):
        # One-file-extensibility: extra CSL-JSON keys on `primary` do NOT close the set.
        att = valid_attestation()
        att["primary"]["container-title"] = "J. Parsing"
        att["primary"]["publisher"] = "ACM"
        validate_grounding_ledger(one_fact_ledger(attestation=att))

    def test_relation_vocabulary_is_the_v1_named_set(self):
        # The accepted PROV-O relation vocabulary is a NAMED frozenset; v1 = {"wasQuotedFrom"}.
        assert ATTESTATION_RELATIONS == frozenset({"wasQuotedFrom"})

    def test_scenario1_ledger_omits_attestation_and_stays_valid(self):
        # Absent-by-default: a 6-field scenario-1 entry carries no `attestation` and validates.
        ledger = one_fact_ledger()
        assert "attestation" not in ledger["f0"]
        validate_grounding_ledger(ledger)

    def test_secret_hidden_in_attestation_is_refused(self):
        # The recursive no-secrets scan reaches the nested attestation Mapping (NO new scan added).
        att = valid_attestation()
        att["primary"]["note"] = "ghp_0123456789abcdefghij0123456789"
        with pytest.raises(SecretShapedValueError):
            validate_grounding_ledger(one_fact_ledger(attestation=att))


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


# --- F-a: ir_version generation-tolerant validation + additive-optional ledger (DR-6 build) ---


class TestIrVersionGenerationTolerance:
    def test_fresh_build_stamps_the_current_generation(self, preimage, artifact_id):
        # `build_ir` stamps IR_VERSION on every fresh envelope — the F-a bump lands here.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="x")
        assert doc["ir_version"] == IR_VERSION == 2

    def test_stored_v1_envelope_with_a_6_field_ledger_still_validates(
        self, preimage, artifact_id
    ):
        # The whole point of F-a: a stored PRIOR-generation envelope (ir_version=1, the 6
        # LEDGER_REQUIRED fields, NO optional carrier) stays read-compatible under the v2 code.
        # The binding preimage excludes ir_version + the ledger, so re-stamping is identity-safe.
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),  # exactly the 6 LEDGER_REQUIRED fields, no attestation
            body='The parser runs in [linear time]{.EXTRACTED data-fact="f0"}.',
        )
        doc["ir_version"] = 1  # a stored pre-F-a record
        validate_ir(doc)  # returns cleanly — no raise
        assert 1 in KNOWN_IR_VERSIONS

    def test_ledger_required_alias_and_dr6_optional_carrier(self):
        # The required set is the pre-F-a `LEDGER_FIELDS` verbatim (back-compat alias); DR-6
        # COMMIT 2 lands the FIRST optional carrier (`attestation`), so scenario-1 6-field
        # ledgers stay valid while a scenario-2 entry MAY carry it.
        assert LEDGER_FIELDS == LEDGER_REQUIRED
        assert LEDGER_OPTIONAL == ("attestation",)


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


# --- DR-4 C4: the OPTIONAL `section_conformance` field (additive-optional; NOT in identity) -------


def academic_conformance() -> list[dict]:
    """A well-formed RESOLVED base schema exercising the WHOLE C2 vocabulary: presence (role),
    order (role selectors), length (role), and count (a TYPE-axis selector into the carrier)."""
    return [
        {"rule": "presence", "axis": "role", "value": "abstract", "required": True,
         "severity": "error"},
        {"rule": "presence", "axis": "role", "value": "methods", "severity": "error"},
        {"rule": "order", "selectors": [
            {"axis": "role", "value": "abstract"},
            {"axis": "role", "value": "methods"},
        ], "severity": "warning"},
        {"rule": "length", "axis": "role", "value": "abstract", "min_len": 0, "max_len": 2500,
         "severity": "warning"},
        {"rule": "count", "axis": "type", "value": "figure", "cardinality": "{1,}",
         "severity": "info"},
    ]


class TestSectionConformanceField:
    def test_section_conformance_is_a_declared_top_level_key(self):
        # The additive-optional key joined the closed top-level set (mirrors LEDGER_OPTIONAL).
        assert "section_conformance" in TOP_LEVEL_KEYS

    def test_no_ir_version_bump_s5(self):
        # S-5: the field rides `keys <= TOP_LEVEL_KEYS`, NOT a generation bump — untouched.
        assert IR_VERSION == 2 and KNOWN_IR_VERSIONS == frozenset({1, 2})

    def test_v2_envelope_without_the_field_still_validates(self, preimage, artifact_id):
        # BACK-COMPAT: a fresh v2 IR carrying NO section_conformance validates unchanged.
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body='The parser runs in [linear time]{.EXTRACTED data-fact="f0"}.',
        )
        assert "section_conformance" not in doc
        validate_ir(doc)  # no raise
        assert doc["ir_version"] == 2

    def test_v1_envelope_without_the_field_still_validates(self, preimage, artifact_id):
        # BACK-COMPAT: a stored PRIOR-generation (ir_version=1) IR with NO field stays valid.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["ir_version"] = 1
        assert "section_conformance" not in doc
        validate_ir(doc)  # no raise
        assert 1 in KNOWN_IR_VERSIONS

    def test_well_formed_field_validates_and_round_trips(self, preimage, artifact_id):
        schema = academic_conformance()
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding={},
            body="Body text.",
            section_conformance=schema,
        )
        assert doc["section_conformance"] == schema  # recorded verbatim (resolved base schema)
        validate_ir(doc)  # idempotent — build_ir already validated

    def test_well_formed_field_validates_on_a_v1_envelope(self, preimage, artifact_id):
        # The field is additive-optional across BOTH read generations, not v2-only.
        doc = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            section_conformance=academic_conformance(),
        )
        doc["ir_version"] = 1
        validate_ir(doc)  # no raise

    @pytest.mark.parametrize(
        "bad",
        [
            "not-a-list",  # not a list at all
            [],  # present but EMPTY — omit-when-absent invariant (never []/null)
            [{"rule": "bogus", "axis": "role", "value": "x"}],  # unknown menu kind
            [{"rule": "presence", "axis": "role", "value": "x", "severity": "loud"}],  # severity
            [{"rule": "presence", "axis": "type", "value": "sidebar", "severity": "error"}],  # type
            [{"rule": "presence", "axis": "role", "value": "x", "bogus": 1}],  # unknown rule key
            [{"rule": "presence", "axis": "role"}],  # missing required `value`
            [{"rule": "count", "axis": "role", "value": "x", "cardinality": "??",
              "severity": "error"}],  # malformed cardinality
            [{"rule": "order", "selectors": [{"axis": "role", "value": "a"}],
              "severity": "warning"}],  # order needs >= 2 selectors
            [{"rule": "length", "axis": "role", "value": "a", "min_len": 5, "max_len": 1,
              "severity": "error"}],  # max < min
        ],
    )
    def test_malformed_field_is_refused_loudly_typed(self, preimage, artifact_id, bad):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["section_conformance"] = bad
        with pytest.raises(SchemaViolation) as exc:
            validate_ir(doc)
        assert exc.value.code == "ir-schema-invalid"

    def test_build_ir_refuses_a_malformed_field(self, preimage, artifact_id):
        # build_ir validates before returning, so a malformed schema can never be built.
        with pytest.raises(SchemaViolation):
            build_ir(
                artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
                section_conformance=[{"rule": "presence", "axis": "role", "value": "x",
                                      "severity": "loud"}],
            )

    def test_omit_when_absent_floor_and_none(self, preimage, artifact_id):
        # A floor [] (or None) records NO key — never [] / null on the envelope.
        floor = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            section_conformance=[],
        )
        none = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            section_conformance=None,
        )
        assert "section_conformance" not in floor
        assert "section_conformance" not in none

    def test_the_field_is_identity_neutral(self, preimage, artifact_id):
        # THE identity test: two build_ir with the SAME preimage, one WITH and one WITHOUT the
        # field, mint the SAME artifact_id and the SAME binding digest — the field is DERIVED and
        # is recorded OUTSIDE binding.preimage, so it can never move identity.
        without = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body text."
        )
        with_field = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body text.",
            section_conformance=academic_conformance(),
        )
        assert "section_conformance" in with_field and "section_conformance" not in without
        # Same id, same full digest, byte-identical binding (incl. its preimage).
        assert with_field["binding"]["artifact_id"] == without["binding"]["artifact_id"]
        assert with_field["binding"]["digest"] == without["binding"]["digest"]
        assert with_field["binding"] == without["binding"]
        # The field never leaks into the preimage (the identity SSOT).
        assert "section_conformance" not in with_field["binding"]["preimage"]
        assert mint_artifact_id(with_field["binding"]["preimage"]) == artifact_id


# --- DR-5 C1: the OPTIONAL `references` CSL-JSON block (additive-optional; body-blind) -----------


def valid_references() -> list[dict]:
    """A well-formed `references` block: a list of >= 2 CSL-JSON citation items, each with a
    DISTINCT non-empty `id` and OPEN descriptor fields (type/title/author/issued/DOI/…)."""
    return [
        {
            "id": "smith2020",
            "type": "article-journal",
            "title": "On Linear-Time Parsing",
            "author": [{"family": "Smith", "given": "A."}],
            "issued": {"date-parts": [[2020]]},
            "DOI": "10.1000/xyz123",
        },
        {
            "id": "jones2021",
            "type": "book",
            "title": "Compilers in Practice",
            "container-title": "MIT Press",
        },
    ]


class TestReferencesBlock:
    """DR-5 C1: the OPTIONAL top-level `references` CSL-JSON citation block — additive-optional,
    OMIT-WHEN-ABSENT, BODY-BLIND (recorded OUTSIDE binding.preimage, moves NO artifact-id). Nothing
    consumes it yet (C2 projects it from the ledger, C3+ teach `[@key]`); C1 is envelope + validator
    + build_ir wiring only. Modeled on TestSectionConformanceField (the DR-4 C4 additive analog)."""

    def test_references_is_a_declared_top_level_key(self):
        # The additive-optional key joined the closed top-level set (mirrors section_conformance).
        assert "references" in TOP_LEVEL_KEYS

    def test_no_ir_version_bump(self):
        # The block rides `keys <= TOP_LEVEL_KEYS`, NOT a generation bump — versions untouched.
        assert IR_VERSION == 2 and KNOWN_IR_VERSIONS == frozenset({1, 2})

    def test_envelope_without_references_still_validates(self, preimage, artifact_id):
        # BACK-COMPAT: a fresh IR carrying NO references validates unchanged and adds NO key — the
        # whole pre-C1 corpus (references absent) is untouched (green golden suite proves byte-id).
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body='The parser runs in [linear time]{.EXTRACTED data-fact="f0"}.',
        )
        assert "references" not in doc
        validate_ir(doc)  # no raise
        baseline = build_ir(  # a second identical build is byte-for-byte the same (determinism)
            artifact_id=artifact_id,
            preimage=preimage,
            grounding=one_fact_ledger(),
            body='The parser runs in [linear time]{.EXTRACTED data-fact="f0"}.',
        )
        assert doc == baseline

    def test_well_formed_references_validates_and_round_trips(self, preimage, artifact_id):
        refs = valid_references()
        doc = build_ir(
            artifact_id=artifact_id,
            preimage=preimage,
            grounding={},
            body="Body text.",
            references=refs,
        )
        assert doc["references"] == refs  # recorded verbatim
        assert [r["id"] for r in doc["references"]] == ["smith2020", "jones2021"]
        validate_ir(doc)  # idempotent — build_ir already validated

    def test_well_formed_references_validates_on_a_v1_envelope(self, preimage, artifact_id):
        # additive-optional across BOTH read generations, not v2-only.
        doc = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            references=valid_references(),
        )
        doc["ir_version"] = 1
        validate_ir(doc)  # no raise

    def test_open_descriptor_keys_are_accepted(self, preimage, artifact_id):
        # The NON-`id` keys stay OPEN (CSL-JSON is one-file-upgradeable) — a novel descriptor field
        # rides through unrefused, exactly like attestation.primary's open key set (checklist #8).
        doc = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            references=[{"id": "x", "publisher-place": "Cambridge", "custom-field": "ok"}],
        )
        validate_ir(doc)  # no raise

    def test_entry_missing_id_is_refused(self, preimage, artifact_id):
        # STRICTER than attestation.primary: every citation item MUST carry a citation key.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = [{"type": "book", "title": "No Key"}]  # no `id`
        with pytest.raises(SchemaViolation) as exc:
            validate_ir(doc)
        assert exc.value.code == "ir-schema-invalid"

    @pytest.mark.parametrize("bad_id", ["", "   ", 7, None])
    def test_empty_or_nonstring_id_is_refused(self, preimage, artifact_id, bad_id):
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = [{"id": bad_id, "title": "Bad Key"}]
        with pytest.raises(SchemaViolation):
            validate_ir(doc)

    def test_bare_string_entry_is_refused(self, preimage, artifact_id):
        # A CSL item is a Mapping, never a bare "Smith 2020" string (mirrors attestation.primary).
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = ["Smith 2020"]
        with pytest.raises(SchemaViolation) as exc:
            validate_ir(doc)
        assert exc.value.code == "ir-schema-invalid"

    @pytest.mark.parametrize("bad", ["not-a-list", {"id": "x"}, []])
    def test_non_list_or_empty_references_is_refused(self, preimage, artifact_id, bad):
        # A bare string / a Mapping / a present-but-EMPTY list are each refused: a str IS a Sequence
        # and a Mapping is iterable, so the list gate is explicit; [] violates OMIT-WHEN-ABSENT (an
        # artifact with no citations DROPS the key, never []/null).
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = bad
        with pytest.raises(SchemaViolation):
            validate_ir(doc)

    def test_duplicate_ids_are_refused(self, preimage, artifact_id):
        # C4 `[@key]` resolution needs a UNIQUE key per item — a duplicate is an ambiguous target.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = [
            {"id": "dup", "title": "First"},
            {"id": "dup", "title": "Second"},
        ]
        with pytest.raises(SchemaViolation) as exc:
            validate_ir(doc)
        assert exc.value.code == "ir-schema-invalid"

    def test_build_ir_refuses_a_malformed_references(self, preimage, artifact_id):
        # build_ir validates before returning, so a malformed block can never be built.
        with pytest.raises(SchemaViolation):
            build_ir(
                artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
                references=[{"title": "no id"}],
            )

    def test_omit_when_absent_none_and_empty(self, preimage, artifact_id):
        # None or an empty list records NO key — never []/null on the envelope.
        none = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            references=None,
        )
        empty = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.",
            references=[],
        )
        assert "references" not in none
        assert "references" not in empty

    def test_planted_secret_in_a_reference_is_refused(self, preimage, artifact_id):
        # The §3.3 no-secrets scan reaches a `references` descriptor value: `references` is a NEW
        # top-level key (NOT nested under the already-scanned grounding/metadata), so the scan is
        # added in _validate_references — a secret-shaped value can never reach persistence.
        doc = build_ir(artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body.")
        doc["references"] = [{"id": "leak", "note": "ghp_0123456789abcdefghij0123456789"}]
        with pytest.raises(SecretShapedValueError):
            validate_ir(doc)

    def test_references_is_identity_neutral(self, preimage, artifact_id):
        # THE identity test: two build_ir with the SAME preimage/body, one WITH and one WITHOUT
        # references, mint the SAME artifact_id and byte-identical binding — references is
        # body-blind (recorded OUTSIDE binding.preimage), so it can never move identity.
        without = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body text."
        )
        with_refs = build_ir(
            artifact_id=artifact_id, preimage=preimage, grounding={}, body="Body text.",
            references=valid_references(),
        )
        assert "references" in with_refs and "references" not in without
        # Same id, same full digest, byte-identical binding (incl. its preimage).
        assert with_refs["binding"]["artifact_id"] == without["binding"]["artifact_id"]
        assert with_refs["binding"]["digest"] == without["binding"]["digest"]
        assert with_refs["binding"] == without["binding"]
        # The block never leaks into the preimage (the identity SSOT).
        assert "references" not in with_refs["binding"]["preimage"]
        assert mint_artifact_id(with_refs["binding"]["preimage"]) == artifact_id
