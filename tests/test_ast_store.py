"""Step-27 tests: the layer-3 AST store keyed by (fitted-id, reader-pin digest) (§18/FR7.1).

Coverage (plan step-27 acceptance):
- AST persisted keyed by fitted-id + reader-pin digest (api-version + extension set + pandoc
  version); the digest is the visible disambiguator in the filename.
- **Reader-pin DRIFT → a FRESH key, NEVER an overwrite** — the old AST stays put; a stale-pin
  fetch returns None so the caller re-derives (§17/§18).
- **Content-addressed idempotency**: a re-put of byte-identical bytes under the same key is a
  no-op success; a same-key/different-bytes put is refused LOUDLY (a determinism defect).
- api-version is the dominant reader-pin component; a bad key/level is refused.

pandoc is required (the AST under test is the real serialize output); the guard fails loudly
under CI-absent. All stores live under pytest tmp_path — never the repo tree.
"""

from pathlib import Path

import pytest

from pipeline.ast_store import (
    AstStoreError,
    ast_path,
    default_reader_pin_bundle,
    get_ast,
    put_ast,
    reader_pin_bundle,
    reader_pin_digest,
)
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate, serialize_fitted
from pipeline.store import WorkspaceStore

_PANDOC_AVAILABLE = pandoc_available()


@pytest.fixture(autouse=True)
def _require_pandoc():
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the serialize pass MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the AST-store tests derive a real serialize AST")


ART = "a-0123456789abcdef"
FIT = "a-0123456789abcdef.linkedin.en"

_FITTED = {
    "grounding": {
        "f0": {
            "tier": "EXTRACTED",
            "source_instance_id": "repo-a",
            "source_repo": "r",
            "source_commit": "abc123",
            "traceability_anchor": ["x.py:1"],
            "scores_snapshot": {},
        }
    },
    "body": 'Rate [100/s]{.EXTRACTED data-fact="f0"} holds.',
}


def _ast():
    return serialize_fitted(_FITTED)[0].ast


def test_reader_pin_digest_is_deterministic_and_api_version_dominant():
    b = default_reader_pin_bundle()
    assert reader_pin_digest(b) == reader_pin_digest(dict(b))  # order-independent, canonical
    # a change to ANY of the three components moves the digest
    bumped = reader_pin_bundle(pandoc_api_version=(1, 24, 0, 0))
    assert reader_pin_digest(b) != reader_pin_digest(bumped)
    assert reader_pin_digest(b) != reader_pin_digest(reader_pin_bundle(pandoc_version="9.99"))
    assert reader_pin_digest(b) != reader_pin_digest(reader_pin_bundle(reader="markdown"))


def test_put_get_round_trip(tmp_path):
    store = WorkspaceStore(tmp_path)
    ast = _ast()
    path, digest = put_ast(store, FIT, ast, bundle=default_reader_pin_bundle())
    assert digest in path.name and path.name.startswith(FIT)
    assert get_ast(store, FIT, bundle=default_reader_pin_bundle()) == ast


def test_reput_identical_is_idempotent(tmp_path):
    store = WorkspaceStore(tmp_path)
    ast = _ast()
    p1, _ = put_ast(store, FIT, ast, bundle=default_reader_pin_bundle())
    p2, _ = put_ast(store, FIT, ast, bundle=default_reader_pin_bundle())
    assert p1 == p2  # same key, identical bytes — a no-op success, not an error


def test_reput_different_bytes_same_key_is_refused_loudly(tmp_path):
    store = WorkspaceStore(tmp_path)
    put_ast(store, FIT, _ast(), bundle=default_reader_pin_bundle())
    tampered = _ast()
    tampered["meta"] = {"injected": {"t": "MetaBool", "c": True}}
    with pytest.raises(AstStoreError):
        put_ast(store, FIT, tampered, bundle=default_reader_pin_bundle())


def test_drift_lands_on_a_fresh_key_never_overwrites(tmp_path):
    store = WorkspaceStore(tmp_path)
    ast = _ast()
    base = default_reader_pin_bundle()
    drifted = reader_pin_bundle(pandoc_api_version=(1, 24, 0, 0))  # an api-version bump

    p_base, d_base = put_ast(store, FIT, ast, bundle=base)
    p_drift, d_drift = put_ast(store, FIT, ast, bundle=drifted)

    assert p_base != p_drift and d_base != d_drift
    assert p_base.exists() and p_drift.exists()  # BOTH present — drift never overwrites
    # a stale-pin fetch under the NEW toolchain sees no AST (must re-derive), never the old one
    novel = reader_pin_bundle(pandoc_version="9.99")
    assert get_ast(store, FIT, bundle=novel) is None
    assert get_ast(store, FIT, bundle=base) == ast


def test_standalone_part_label_keys_a_distinct_ast(tmp_path):
    store = WorkspaceStore(tmp_path)
    ast = _ast()
    p_whole, _ = put_ast(store, FIT, ast, bundle=default_reader_pin_bundle())
    p_part, _ = put_ast(store, FIT, ast, bundle=default_reader_pin_bundle(), label="appendix")
    assert p_whole != p_part
    assert "~appendix" in p_part.name and "~appendix" not in p_whole.name


def test_ast_path_refuses_non_fitted_id(tmp_path):
    store = WorkspaceStore(tmp_path)
    digest = reader_pin_digest(default_reader_pin_bundle())
    with pytest.raises(AstStoreError):
        ast_path(store, ART, digest)  # a bare artifact-id is not a fitted-level key
    with pytest.raises(AstStoreError):
        ast_path(store, "a-0123456789abcdef.linkedin.en.html.plain", digest)  # deliverable-level
    with pytest.raises(AstStoreError):
        ast_path(store, FIT, "NOThex")  # a bad reader-pin digest


def test_ast_records_live_under_artifacts_dir(tmp_path):
    store = WorkspaceStore(tmp_path)
    path, _ = put_ast(store, FIT, _ast(), bundle=default_reader_pin_bundle())
    assert path.parent == store.artifacts_dir
    # never collides with the bare-fitted-id IR-fitted record name
    assert path.name != FIT and Path(path.name).name.startswith(f"{FIT}.ast.")
