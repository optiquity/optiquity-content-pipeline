"""Step-8 tests: canonical JSON + SHA-256 digest helpers + §12.4 canonical set semantics.

Acceptance criterion under test (plan step 8): identical logical inputs → identical
canonical bytes → identical digests. Also pins the step-8 canonical-JSON DATE DECISION
(assigned by the G4 gate): `datetime.date` serializes as its ISO-8601 string;
`datetime.datetime` is refused (see `pipeline/canonical.py` module docstring).
"""

import datetime
import hashlib

import pytest

from pipeline.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    canonical_json_str,
    canonical_set,
    digest_full,
    digest_hex12,
    digest_hex16,
    sha256_hex,
)
from pipeline.yamlio import load_yaml

# ---------------------------------------------------------------------------
# Canonical bytes: identical logical inputs → identical bytes
# ---------------------------------------------------------------------------


def test_key_order_never_changes_the_bytes() -> None:
    a = {"topic": "graphify", "persona": "cto", "format": "post"}
    b = {"format": "post", "topic": "graphify", "persona": "cto"}
    assert canonical_json_bytes(a) == canonical_json_bytes(b)


def test_keys_are_sorted_and_separators_compact() -> None:
    assert canonical_json_str({"b": 2, "a": 1}) == '{"a":1,"b":2}'
    assert canonical_json_bytes({"b": 2, "a": 1}) == b'{"a":1,"b":2}'


def test_nested_structures_canonicalize_recursively() -> None:
    a = {"dims": {"voice": {"formality": 4}, "topic": "t"}, "goals": [{"z": 1, "a": 2}]}
    b = {"goals": [{"a": 2, "z": 1}], "dims": {"topic": "t", "voice": {"formality": 4}}}
    assert canonical_json_bytes(a) == canonical_json_bytes(b)


def test_tuples_and_lists_render_identically() -> None:
    assert canonical_json_bytes(("a", "b")) == canonical_json_bytes(["a", "b"])


def test_list_order_is_meaning_and_is_preserved() -> None:
    # Ordered lists (§11.1) are NOT sorted — order is content.
    assert canonical_json_bytes(["b", "a"]) != canonical_json_bytes(["a", "b"])


def test_unicode_is_raw_utf8_not_ascii_escaped() -> None:
    assert canonical_json_bytes({"t": "café"}) == '{"t":"café"}'.encode()


def test_scalar_documents_canonicalize() -> None:
    assert canonical_json_bytes("x") == b'"x"'
    assert canonical_json_bytes(7) == b"7"
    assert canonical_json_bytes(None) == b"null"
    assert canonical_json_bytes(True) == b"true"


def test_bool_and_int_render_distinctly() -> None:
    assert canonical_json_bytes({"v": True}) != canonical_json_bytes({"v": 1})


def test_yaml_loaded_mappings_with_different_key_orders_digest_identically() -> None:
    # End-to-end through the pinned loader (yamlio): logical identity survives the trip.
    a = load_yaml("topic: graphify\nweight: 3\ntags: [a, b]\n")
    b = load_yaml("tags: [a, b]\nweight: 3\ntopic: graphify\n")
    assert canonical_json_bytes(a) == canonical_json_bytes(b)
    assert digest_full(a) == digest_full(b)


# ---------------------------------------------------------------------------
# The step-8 date decision (assigned by gate G4; grounded in §7.2/§13)
# ---------------------------------------------------------------------------


def test_dates_serialize_as_iso_8601_strings() -> None:
    assert canonical_json_bytes({"until": datetime.date(2026, 7, 12)}) == b'{"until":"2026-07-12"}'


def test_date_serialization_is_source_faithful_through_yaml() -> None:
    # The YAML author wrote `2026-07-12`; the canonical preimage carries those same bytes.
    loaded = load_yaml("until: 2026-07-12\n")
    assert type(loaded["until"]) is datetime.date
    assert canonical_json_bytes(loaded) == b'{"until":"2026-07-12"}'


def test_date_and_its_iso_string_canonicalize_identically() -> None:
    # Single-valued on purpose: an attribute's type is schema-fixed (§11.1), so one
    # attribute path never carries both a date and a string — no ambiguity can arise.
    assert canonical_json_bytes(datetime.date(2026, 7, 12)) == canonical_json_bytes("2026-07-12")


def test_datetimes_are_refused_including_the_date_subclass_trap() -> None:
    # datetime.datetime SUBCLASSES datetime.date — a naive isinstance(date) check would
    # silently serialize timestamps; the refusal must win.
    with pytest.raises(CanonicalizationError) as excinfo:
        canonical_json_bytes({"at": datetime.datetime(2026, 7, 12, 0, 0)})
    assert excinfo.value.code == "canonicalization-refused"
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(datetime.datetime(2026, 7, 12, 10, 30, tzinfo=datetime.UTC))


# ---------------------------------------------------------------------------
# Refusals: nothing with two possible renderings gets one silently
# ---------------------------------------------------------------------------


def test_non_string_mapping_keys_are_refused() -> None:
    # json.dumps would silently stringify these — a preimage corruption.
    for bad_key in (1, True, None, 2.5):
        with pytest.raises(CanonicalizationError):
            canonical_json_bytes({bad_key: "v"})


def test_non_finite_floats_are_refused() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(CanonicalizationError):
            canonical_json_bytes({"v": bad})


def test_raw_python_sets_are_refused() -> None:
    with pytest.raises(CanonicalizationError) as excinfo:
        canonical_json_bytes({"tags": {"a", "b"}})
    assert "canonical_set" in str(excinfo.value)  # the error names the remedy
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(frozenset({"a"}))


def test_unsupported_object_types_are_refused() -> None:
    for bad in (b"bytes", object(), Exception("x")):
        with pytest.raises(CanonicalizationError):
            canonical_json_bytes({"v": bad})


# ---------------------------------------------------------------------------
# Digest helpers (§7.4 digest form)
# ---------------------------------------------------------------------------


def test_digest_is_sha256_of_the_canonical_bytes() -> None:
    obj = {"b": [1, 2], "a": "x"}
    expected = hashlib.sha256(canonical_json_bytes(obj)).hexdigest()
    assert digest_full(obj) == expected
    assert sha256_hex(canonical_json_bytes(obj)) == expected


def test_truncations_are_prefixes_of_the_full_digest() -> None:
    # §7.4: hex16 (64 bits) roots artifact/run ids; hex12 (48 bits) is the folio-id /
    # revision-qualifier form; the FULL digest is what bindings record.
    obj = {"topic": "graphify"}
    full = digest_full(obj)
    assert len(full) == 64
    assert digest_hex16(obj) == full[:16]
    assert digest_hex12(obj) == full[:12]
    assert full == full.lower()
    assert set(full) <= set("0123456789abcdef")


def test_identical_logical_inputs_yield_identical_digests() -> None:
    a = {"persona": "cto", "goals": ["convince", "explain"]}
    b = {"goals": ["convince", "explain"], "persona": "cto"}
    assert digest_full(a) == digest_full(b)
    assert digest_hex16(a) == digest_hex16(b)
    assert digest_hex12(a) == digest_hex12(b)


def test_different_logical_inputs_yield_different_digests() -> None:
    assert digest_full({"a": 1}) != digest_full({"a": 2})
    assert digest_full({"a": 1}) != digest_full({"a": "1"})


# ---------------------------------------------------------------------------
# Canonical set semantics (§12.4: dedupe by exact value + sorted; feeds §7.2)
# ---------------------------------------------------------------------------


def test_canonical_set_is_order_insensitive_and_deduped() -> None:
    assert canonical_set(["b", "a", "b"]) == ["a", "b"]
    assert canonical_set(["a", "b"]) == canonical_set(["b", "a"])


def test_canonical_set_goal_set_shape_identical_ids_any_order() -> None:
    # §12.4: identical inputs give an identical set and an identical artifact-id every run.
    goal_sets = (
        ["explain", "convince"],
        ["convince", "explain"],
        ["convince", "explain", "convince"],
    )
    digests = {digest_hex16({"goal-set": canonical_set(gs)}) for gs in goal_sets}
    assert len(digests) == 1


def test_canonical_set_dedupe_is_type_distinguishing() -> None:
    # `True` is not `1`, `1` is not `1.0` — they render differently, so a silent merge
    # would make canonical bytes depend on input order.
    result = canonical_set([True, 1, 1.0])
    assert len(result) == 3
    assert canonical_set([1, True, 1.0]) == result


def test_canonical_set_negative_zero_is_order_insensitive() -> None:
    # RV-1 regression: -0.0 == 0.0 under Python `==`, but they RENDER differently
    # (b'-0.0' vs b'0.0'). An ==-keyed dedupe merged them keeping whichever arrived
    # FIRST, making canonical bytes input-order-dependent. The rendering key keeps both.
    a, b = canonical_set([0.0, -0.0]), canonical_set([-0.0, 0.0])
    assert canonical_json_bytes(a) == canonical_json_bytes(b) == b"[-0.0,0.0]"
    assert digest_full(a) == digest_full(b)
    assert len(a) == 2  # they render differently; merging either way is a coercion
    # Genuinely-identical members still dedupe (byte-level: [-0.0] == [0.0] under `==`).
    assert canonical_json_bytes(canonical_set([-0.0, -0.0])) == b"[-0.0]"
    assert canonical_json_bytes(canonical_set([0.0, 0.0])) == b"[0.0]"
    assert canonical_json_bytes(canonical_set([0.0, -0.0, 1.5])) == b"[-0.0,0.0,1.5]"


def test_canonical_set_mixed_classes_sort_deterministically() -> None:
    a = canonical_set(["zeta", 10, 2, "alpha", False])
    b = canonical_set([False, "alpha", 2, 10, "zeta"])
    assert a == b
    assert canonical_json_bytes(a) == canonical_json_bytes(b)


def test_canonical_set_output_is_canonicalizable_and_stable() -> None:
    payload = {"tags": canonical_set(["m3", "grounding", "ids"])}
    again = {"tags": canonical_set(["ids", "m3", "grounding"])}
    assert canonical_json_bytes(payload) == canonical_json_bytes(again)
    assert digest_hex12(payload) == digest_hex12(again)


def test_canonical_set_refuses_non_leaf_elements() -> None:
    for bad in ([{"k": "v"}], [["nested"]], [None], [datetime.date(2026, 7, 12)]):
        with pytest.raises(CanonicalizationError):
            canonical_set(bad)
    with pytest.raises(CanonicalizationError):
        canonical_set([float("nan")])


def test_canonical_set_empty_is_empty_list() -> None:
    assert canonical_set([]) == []
    assert canonical_json_bytes(canonical_set([])) == b"[]"
