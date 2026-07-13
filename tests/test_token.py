"""Step-32 tests: the resumption token (§20) — a documented cursor, not a secret.

Covers the four acceptance points: token round-trip with integrity intact; tamper /
cross-version / wrong-workspace each → `invalid-token` (never a misread, §3.1); and the
load-bearing LOST-TOKEN SURVIVABILITY proof — everything a token references is re-addressable
by id from the store WITHOUT the token, so losing it loses only the cursor, never any work.

All fixtures are obviously generic (`wsA`/`wsB`, §7.4 literal ids); no instance content.
"""

from __future__ import annotations

import pytest

from pipeline.api import token as token_mod
from pipeline.api.token import InvalidTokenError, Token, decode, encode, integrity_hash, mint
from pipeline.canonical import digest_full
from pipeline.store import WorkspaceStore

# §7.4 literal ids (generic). ARTs are bare artifact-ids; the folio ref is f-<hex12>.
ART_A = "a-9f3c07d21b44e8aa"
ART_B = "a-1234567890abcdef"
FOLIO = "f-abcabcabcabc"
PLAN_HASH = "d3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33f0"


def _sample(workspace: str = "wsA") -> Token:
    return mint(
        workspace,
        PLAN_HASH,
        inputs={"selection": {"topic": "x"}, "overrides": {"voice.tone": "warm"}, "pins": {}},
        cursor={"next": "topic=x/persona=y"},
        produced_ids=[ART_A, ART_B],
        folio_id=FOLIO,
    )


class TestRoundTrip:
    def test_encode_decode_is_the_identity(self):
        tok = _sample()
        assert decode(encode(tok), expected_workspace="wsA") == tok

    def test_integrity_hash_is_deterministic(self):
        assert integrity_hash(_sample()) == integrity_hash(_sample())
        assert encode(_sample())["integrity_hash"] == encode(_sample())["integrity_hash"]

    def test_wire_carries_exactly_the_documented_shape(self):
        wire = encode(_sample())
        assert set(wire) == set(token_mod.TOKEN_WIRE_KEYS)
        assert wire["token_schema_version"] == token_mod.TOKEN_SCHEMA_VERSION
        assert wire["workspace"] == "wsA"
        assert wire["plan_hash"] == PLAN_HASH
        assert wire["produced_ids"] == [ART_A, ART_B]
        assert wire["folio_id"] == FOLIO

    def test_integrity_is_a_plain_digest_not_a_secret(self):
        # Anyone can recompute it from the public body — no key, no shared secret (§20). It
        # detects corruption/version-skew, and that suffices BECAUSE of lost-token
        # survivability: the store, not the token, is the correctness authority (§22.7).
        wire = encode(_sample())
        body = {k: wire[k] for k in token_mod.TOKEN_BODY_KEYS}
        assert wire["integrity_hash"] == digest_full(body)
        assert len(wire["integrity_hash"]) == 64  # a full SHA-256 hex digest


class TestInvalidToken:
    def test_tampered_produced_ids_is_invalid_token(self):
        wire = encode(_sample())
        wire["produced_ids"] = [ART_A]  # drop one — the digest no longer matches
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsA")
        assert exc.value.reason == "tampered"
        assert exc.value.code == "invalid-token"

    def test_tampered_plan_hash_is_invalid_token(self):
        wire = encode(_sample())
        wire["plan_hash"] = "0" * 64
        with pytest.raises(InvalidTokenError):
            decode(wire, expected_workspace="wsA")

    def test_tampered_integrity_hash_is_invalid_token(self):
        wire = encode(_sample())
        wire["integrity_hash"] = "0" * 64
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsA")
        assert exc.value.reason == "tampered"

    def test_cross_version_is_invalid_token(self):
        # A token HONESTLY minted at another schema version: its digest is self-consistent
        # (integrity passes), so the refusal is specifically the version skew (§20).
        future = Token(workspace="wsA", plan_hash=PLAN_HASH, token_schema_version=999)
        wire = encode(future)
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsA")
        assert exc.value.reason == "cross-version"

    def test_wrong_workspace_is_invalid_token(self):
        wire = encode(_sample("wsA"))
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsB")
        assert exc.value.reason == "wrong-workspace"

    def test_malformed_missing_key_is_invalid_token(self):
        wire = encode(_sample())
        del wire["cursor"]
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsA")
        assert exc.value.reason == "malformed"

    def test_malformed_extra_key_is_invalid_token(self):
        wire = encode(_sample())
        wire["smuggled"] = "extra"
        with pytest.raises(InvalidTokenError) as exc:
            decode(wire, expected_workspace="wsA")
        assert exc.value.reason == "malformed"

    def test_malformed_not_a_mapping_is_invalid_token(self):
        with pytest.raises(InvalidTokenError):
            decode(["not", "a", "token"], expected_workspace="wsA")

    def test_the_one_code_is_invalid_token(self):
        # Every refusal cause surfaces the SAME machine code (§21.7) — reason is for the hint.
        assert InvalidTokenError.code == "invalid-token"


class TestNoStaleToken:
    def test_a_well_formed_token_is_never_rejected_for_age(self):
        # There is NO time input to decode: a token is never stale (§20). The same wire decodes
        # identically no matter how "old" it is — correctness never depends on token freshness.
        wire = encode(_sample())
        assert decode(wire, expected_workspace="wsA") == decode(wire, expected_workspace="wsA")

    def test_stale_token_is_not_a_code(self):
        from pipeline.api import results

        assert "stale-token" not in results.ALL_CODES


class TestLostTokenSurvivability:
    def test_produced_work_is_re_addressable_without_the_token(self, tmp_path):
        # Mint a token whose produced_ids name real materialized work in a workspace store.
        store = WorkspaceStore(tmp_path / "wsA")
        payloads = {ART_A: b'{"artifact": "a"}\n', ART_B: b'{"artifact": "b"}\n'}
        for aid, data in payloads.items():
            store.output_path(aid).write_bytes(data)
        (store.folios_dir / FOLIO).mkdir(parents=True, exist_ok=True)

        tok = mint("wsA", PLAN_HASH, produced_ids=list(payloads), folio_id=FOLIO)
        produced = tuple(tok.produced_ids)
        folio_ref = tok.folio_id

        # LOSE the token entirely — the actor's DB row is gone.
        del tok

        # Re-address every durable output DIRECTLY by id, with NO token in hand.
        for aid in produced:
            assert store.output_path(aid).exists()
            assert store.output_path(aid).read_bytes() == payloads[aid]
        assert (store.folios_dir / folio_ref).exists()
        # Losing the token lost only the cursor; every produced id survived, byte-for-byte.

    def test_a_forged_or_absent_token_cannot_conjure_work(self, tmp_path):
        # The dual of survivability: without the store, an id resolves to nothing — the token
        # never carries the work, only its ids. An empty store yields no bytes for a valid id.
        store = WorkspaceStore(tmp_path / "wsB")
        assert not store.output_path(ART_A).exists()


class TestMintValidation:
    def test_bad_produced_id_is_refused(self):
        with pytest.raises(InvalidTokenError):
            mint("wsA", PLAN_HASH, produced_ids=["not a valid id"])

    def test_non_folio_folio_ref_is_refused(self):
        with pytest.raises(InvalidTokenError):
            mint("wsA", PLAN_HASH, folio_id=ART_A)  # an artifact id is not a folio ref

    def test_empty_workspace_is_refused(self):
        with pytest.raises(InvalidTokenError):
            mint("", PLAN_HASH)

    def test_empty_plan_hash_is_refused(self):
        with pytest.raises(InvalidTokenError):
            mint("wsA", "")
