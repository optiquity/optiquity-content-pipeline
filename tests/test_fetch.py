"""Step-34 tests: `pipeline.api.fetch` — the `fetch-by-id` DUMB HOT PATH (§21.5/§21.8).

Covers, per the acceptance list:

- **return = path** (default) → a stable workspace-relative path; **return = bytes** → the
  stored bytes verbatim (UTF-8 where decodable, else base64);
- **the dumb hot path mints NOTHING and evaluates NO currency** (§21.8): a fetch leaves the
  store's artifact/deliverable inventory byte-for-byte unchanged (zero new revisions);
- **immutability / indefinite retention** (§21.8): a fetch of a SUPERSEDED deliverable-id
  returns byte-identical old content AFTER a newer revision exists — the old id is never rebound;
- fetch resolves the layer-2 BYTES for a deliverable (not its render-binding record), and the
  JSON record for an artifact/fitted id (the §21.5 `bytes`-mode AST-JSON case);
- a malformed `return` / a missing payload is a typed result, never a raised exception.

Hermetic: handlers are injected via `invoke(handlers=…)`; no registry mutation, no live call.
"""

from __future__ import annotations

import pytest

from pipeline.api import fetch
from pipeline.api.invoke import invoke
from pipeline.store import WorkspaceStore

ART = "a-9f3c07d21b44e8aa"
FITTED = "a-9f3c07d21b44e8aa.github.en"
DELIVERABLE = "a-9f3c07d21b44e8aa.github.en.md.plain"
DELIVERABLE_REV = "a-9f3c07d21b44e8aa.github.en.md.plain_0123456789ab"
WS = "wsA"


@pytest.fixture()
def store(tmp_path):
    s = WorkspaceStore(tmp_path / WS)
    s.ensure_layout()
    return s


def _handlers():
    return {"fetch-by-id": fetch.fetch_handler()}


def _seed_deliverable(store: WorkspaceStore, deliverable_id: str, body: bytes) -> None:
    """Write a deliverable's render-binding RECORD (so isolation resolves) + its layer-2 bytes."""
    store.output_path(deliverable_id).write_bytes(b'{"binding": {"deliverable_id": "x"}}\n')
    store.bytes_path(deliverable_id, "md").write_bytes(body)


def _fetch(store, id_str, return_mode="path"):
    return invoke(
        "fetch-by-id", WS, {"id": id_str, "return": return_mode}, store=store, handlers=_handlers()
    )


def _inventory(store: WorkspaceStore) -> set[str]:
    arts = (
        {p.name for p in store.artifacts_dir.iterdir()}
        if store.artifacts_dir.is_dir()
        else set()
    )
    dels = (
        {p.name for p in store.deliverables_dir.iterdir()}
        if store.deliverables_dir.is_dir()
        else set()
    )
    return arts | dels


class TestFetchByIdPathAndBytes:
    def test_return_path_gives_the_layer2_bytes_path(self, store):
        _seed_deliverable(store, DELIVERABLE, b"# hello\n")
        out = _fetch(store, DELIVERABLE, "path")
        assert out["envelope"]["ok"] is True
        item = out["results"][0]
        assert item["status"] == "ok" and item["ids"]["id"] == DELIVERABLE
        assert item["output"]["path"].endswith(".md")  # the layer-2 bytes, not the record
        assert item["context"]["return"] == "path"

    def test_return_bytes_gives_verbatim_utf8(self, store):
        _seed_deliverable(store, DELIVERABLE, b"# hello\n")
        out = _fetch(store, DELIVERABLE, "bytes")
        item = out["results"][0]
        assert item["output"]["bytes"] == "# hello\n"
        assert item["context"]["encoding"] == "utf-8"

    def test_return_bytes_base64_falls_back_for_binary(self, store):
        _seed_deliverable(store, DELIVERABLE, b"\xff\xfe\x00\x01")
        out = _fetch(store, DELIVERABLE, "bytes")
        item = out["results"][0]
        assert item["context"]["encoding"] == "base64"
        import base64

        assert base64.b64decode(item["output"]["bytes"]) == b"\xff\xfe\x00\x01"

    def test_default_return_is_path(self, store):
        _seed_deliverable(store, DELIVERABLE, b"x")
        out = invoke("fetch-by-id", WS, {"id": DELIVERABLE}, store=store, handlers=_handlers())
        assert out["results"][0]["context"]["return"] == "path"

    def test_fetch_an_artifact_record_returns_the_json_bytes(self, store):
        store.output_path(ART).write_bytes(b'{"ir": {"body": "hi"}}\n')
        out = _fetch(store, ART, "bytes")
        assert out["results"][0]["output"]["bytes"] == '{"ir": {"body": "hi"}}\n'


class TestDumbHotPath:
    def test_fetch_mints_nothing_and_evaluates_no_currency(self, store):
        _seed_deliverable(store, DELIVERABLE, b"# hello\n")
        before = _inventory(store)
        _fetch(store, DELIVERABLE, "path")
        _fetch(store, DELIVERABLE, "bytes")
        assert _inventory(store) == before  # ZERO new revisions — no mint, no resolution

    def test_superseded_id_returns_byte_identical_old_content(self, store):
        # An OLD deliverable + its bytes; then a NEWER revision lands. Fetching the OLD id STILL
        # returns its unchanged bytes (immutability / indefinite retention, §21.8) — never rebound.
        _seed_deliverable(store, DELIVERABLE, b"ORIGINAL BODY\n")
        original = _fetch(store, DELIVERABLE, "bytes")["results"][0]["output"]["bytes"]
        _seed_deliverable(store, DELIVERABLE_REV, b"REVISED BODY\n")  # a superseding revision
        after = _fetch(store, DELIVERABLE, "bytes")["results"][0]["output"]["bytes"]
        assert after == original == "ORIGINAL BODY\n"  # the old id is byte-identical, forever


class TestFetchRefusals:
    def test_missing_id_is_a_typed_not_found(self, store):
        out = invoke("fetch-by-id", WS, {}, store=store, handlers=_handlers())
        assert out["results"][0]["code"] == "not-found"

    def test_bad_return_mode_is_a_typed_not_found(self, store):
        _seed_deliverable(store, DELIVERABLE, b"x")
        out = _fetch(store, DELIVERABLE, "sideways")
        assert out["results"][0]["code"] == "not-found"
