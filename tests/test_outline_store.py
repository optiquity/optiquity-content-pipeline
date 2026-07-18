"""DR-3 COMMIT 5 tests: `pipeline/outline_store.py` — the pre-compose outline store.

Each test pins a clause of the ratified Commit-5 contract:

- **Round-trip**: `put_outline(store, md)` returns `outline_digest(md)`; `get_outline` reads back
  bytes that are byte-for-byte `normalize_outline(md)`; the stored key (filename) IS the digest.
- **Content-addressed dedup**: a COSMETIC variant of an outline (extra trailing whitespace / blank
  runs / CRLF) writes to the SAME digest/key — one file, an idempotent no-op (§22.7).
- **Accept-path refusals**: an empty / no-substance outline and a secret-shaped one are REFUSED
  LOUDLY (nothing reaches disk) — §15 substance floor / §3.3 secret scan.
- **Clean not-found**: reading an unknown (but well-shaped) digest returns None — never a crash.
- **Keying discipline**: the key is a BARE 64-hex content address, validated DIRECTLY; a §7.4 id
  string is REFUSED as a key, and the module never imports / references `parse_id` / `pipeline.ids`.
- **Retain-all (v1)**: no delete / no GC surface exists; distinct outlines accumulate side by side.

All stores live under pytest `tmp_path` — nothing is ever created under the repo's `workspaces/`.
"""

from __future__ import annotations

import ast
import inspect

import pytest

import pipeline.outline_store as outline_store_module
from pipeline.canonical import sha256_hex
from pipeline.outline import (
    EmptyOutlineError,
    OutlineError,
    SecretShapedOutlineError,
    normalize_outline,
    outline_digest,
)
from pipeline.outline_store import (
    OUTLINES_SUBDIR,
    OutlineStoreError,
    get_outline,
    outline_path,
    put_outline,
)
from pipeline.store import WorkspaceStore

# A real, substantive outline (headings + indented nesting exercise N's step-6 indent preserve).
OUTLINE_MD = "# Launch note\n\n- opening hook\n  - supporting point\n- call to action\n"

# A §7.4 id string — must be REFUSED as an outline key (a digest is not an id).
SECTION_74_ID = "a-9f3c07d21b44e8aa"


@pytest.fixture()
def ws(tmp_path):
    return WorkspaceStore(tmp_path / "ws")


# ---------------------------------------------------------------------------
# Round-trip: write raw md -> digest; read back == N(md) byte-for-byte; key == digest.
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_put_returns_the_bare_outline_digest(self, ws):
        digest = put_outline(ws, OUTLINE_MD)
        assert digest == outline_digest(OUTLINE_MD)

    def test_read_back_is_normalize_outline_byte_for_byte(self, ws):
        digest = put_outline(ws, OUTLINE_MD)
        got = get_outline(ws, digest)
        assert got == normalize_outline(OUTLINE_MD)
        assert got.encode("utf-8") == normalize_outline(OUTLINE_MD).encode("utf-8")

    def test_stored_key_and_filename_are_the_digest(self, ws):
        digest = put_outline(ws, OUTLINE_MD)
        path = outline_path(ws, digest)
        assert path.name == digest
        assert path.parent == ws.root / OUTLINES_SUBDIR
        assert path.is_file()
        # The persisted bytes hash back to the key (the filename IS the content address).
        assert sha256_hex(path.read_bytes()) == digest

    def test_persisted_bytes_are_exactly_the_normalized_form(self, ws):
        digest = put_outline(ws, OUTLINE_MD)
        expected = normalize_outline(OUTLINE_MD).encode("utf-8")
        assert outline_path(ws, digest).read_bytes() == expected


# ---------------------------------------------------------------------------
# Content-addressed dedup + idempotency (§22.7): a cosmetic variant -> the SAME key.
# ---------------------------------------------------------------------------


class TestContentAddressedDedup:
    def test_cosmetic_variant_writes_to_the_same_digest_and_key(self, ws):
        # Extra trailing whitespace, blank-line runs, and CRLF endings — all destroyed by N.
        variant = (
            "# Launch note   \r\n\r\n\r\n- opening hook\t\r\n"
            "  - supporting point \n- call to action\n\n\n"
        )
        assert variant != OUTLINE_MD
        first = put_outline(ws, OUTLINE_MD)
        second = put_outline(ws, variant)
        assert second == first  # same normalized bytes -> same content address
        # Exactly ONE file materialized under outlines/ — the second write deduped.
        files = list((ws.root / OUTLINES_SUBDIR).iterdir())
        assert [p.name for p in files] == [first]

    def test_repeat_put_is_an_idempotent_no_op(self, ws):
        # No AlreadyMaterializedError leaks; the byte-identical re-write is swallowed (§22.7).
        d1 = put_outline(ws, OUTLINE_MD)
        d2 = put_outline(ws, OUTLINE_MD)
        d3 = put_outline(ws, OUTLINE_MD)
        assert d1 == d2 == d3
        assert len(list((ws.root / OUTLINES_SUBDIR).iterdir())) == 1
        assert get_outline(ws, d1) == normalize_outline(OUTLINE_MD)


# ---------------------------------------------------------------------------
# Accept-path refusals (§15 / §3.3): nothing invalid ever reaches disk.
# ---------------------------------------------------------------------------


class TestAcceptRefusals:
    @pytest.mark.parametrize("empty", ["", "   \n\t\n", "\r\n\r\n   \n"])
    def test_empty_or_no_substance_outline_is_refused(self, ws, empty):
        with pytest.raises(EmptyOutlineError) as exc:
            put_outline(ws, empty)
        assert exc.value.code == "outline-empty-substance"
        assert isinstance(exc.value, OutlineError)
        assert not (ws.root / OUTLINES_SUBDIR).exists()  # nothing written

    @pytest.mark.parametrize(
        "secret",
        [
            "# Keys\n- api_key = sk-abcdef0123456789ABCDEF",
            "# Config\n- AWS: AKIAIOSFODNN7EXAMPLE",
        ],
    )
    def test_secret_shaped_outline_is_refused(self, ws, secret):
        with pytest.raises(SecretShapedOutlineError) as exc:
            put_outline(ws, secret)
        assert exc.value.code == "outline-secret-shaped-value"
        assert isinstance(exc.value, OutlineError)
        assert not (ws.root / OUTLINES_SUBDIR).exists()  # nothing written


# ---------------------------------------------------------------------------
# Clean not-found + keying discipline (the bare digest is never an id).
# ---------------------------------------------------------------------------


class TestKeyingDiscipline:
    def test_unknown_digest_reads_as_none(self, ws):
        absent = "0" * 64  # well-shaped, never stored
        assert get_outline(ws, absent) is None  # clean not-found, no crash

    def test_unknown_digest_read_does_not_crash_on_missing_dir(self, ws):
        # The outlines/ dir has never been created; a read must still return None cleanly.
        assert not (ws.root / OUTLINES_SUBDIR).exists()
        assert get_outline(ws, "a" * 64) is None

    @pytest.mark.parametrize(
        "bad",
        [
            SECTION_74_ID,  # a §7.4 id is NOT a content address — refused
            "f-0123456789ab",  # a folio id, likewise
            "ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789",  # uppercase
            "0" * 63,  # too short
            "0" * 65,  # too long
            "g" * 64,  # non-hex
            "",
        ],
    )
    def test_malformed_key_is_refused_by_both_surfaces(self, ws, bad):
        with pytest.raises(OutlineStoreError):
            outline_path(ws, bad)
        with pytest.raises(OutlineStoreError):
            get_outline(ws, bad)

    def test_module_never_routes_a_digest_through_parse_id(self):
        # Keying-discipline teeth: the store validates the bare digest DIRECTLY and never touches
        # the id family — mirrors test_store's ast/inspect import-lint of INV-CORRECTNESS. Parse
        # the AST so only CODE identifiers count (the docstring may name `parse_id` to disclaim it).
        tree = ast.parse(inspect.getsource(outline_store_module))
        imported_modules: set[str] = set()
        imported_names: set[str] = set()
        code_identifiers: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported_modules.add(node.module or "")
                imported_names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                code_identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                code_identifiers.add(node.attr)
        assert "pipeline.ids" not in imported_modules
        assert "parse_id" not in imported_names
        assert "parse_id" not in code_identifiers
        assert not any(name.startswith("mint_") for name in imported_names | code_identifiers)


# ---------------------------------------------------------------------------
# Retain-all (v1): distinct outlines accumulate; no delete / GC surface exists.
# ---------------------------------------------------------------------------


class TestRetainAll:
    def test_distinct_outlines_are_retained_side_by_side(self, ws):
        d1 = put_outline(ws, "# First\n- alpha\n")
        d2 = put_outline(ws, "# Second\n- beta\n")
        assert d1 != d2
        names = {p.name for p in (ws.root / OUTLINES_SUBDIR).iterdir()}
        assert names == {d1, d2}
        assert get_outline(ws, d1) == normalize_outline("# First\n- alpha\n")
        assert get_outline(ws, d2) == normalize_outline("# Second\n- beta\n")

    def test_no_delete_or_gc_surface_is_exported(self):
        exported = set(outline_store_module.__all__)
        for banned in ("delete", "remove", "gc", "evict", "purge", "clear"):
            assert not any(banned in name.lower() for name in exported), banned
