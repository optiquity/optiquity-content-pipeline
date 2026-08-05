"""Sources P3a: the deterministic research primitives — trafilatura extract + the pluggable search
backend + the Common Crawl LEAD feed. FREE / Tier-A (NO LLM, NO spend); open web = INFERRED leads.

FIXTURES ONLY — the `http_get` fetch seam is injected, so NO test hits the live network (rule 1),
and the extractor is fed BYTES the fixture returns (extraction itself never fetches). Content is
SYNTHETIC-GENERIC (rule 4): invented example.test pages + a canned Common Crawl CDX index response,
no real/client content. Everything runs under `tmp_path`; the real `users/` tree is never touched.

Coverage map (the P3a acceptance set):
  - EXTRACT   trafilatura pulls clean main text + a publication date from a fixture; a dateless page
              → `as_of=None`; a malformed/empty page is handled SOFTLY (no crash).
  - SEARCH    the `commoncrawl` backend parses a canned CDX index into hits; an off-host `base_url`
              override is refused LOUD; the `searxng` slot is a LOUD stub (never silently empty).
  - FEED      canned CDX + canned page HTML → search → extract → INFERRED Facts WITHHELD as leads
              (never published); temporality == "snapshot"; dedup by URL; a dateless-page pull is a
              byte-identical re-ingest no-op (idempotency); cost is metered ($0 model spend).
  - REGRESS   EDGAR still publishes and RSS/GDELT stay INFERRED (asserted here + sibling suites).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_sources
from pipeline.adapters.base import TIER_INFERRED
from pipeline.compose import build_grounding_ledger
from pipeline.sources.acquire import FeedConfig, FeedError, ingest_feed
from pipeline.sources.cache import namespace_dir, read_head, read_slice
from pipeline.sources.control import Budget
from pipeline.sources.extract import Extraction, extract
from pipeline.sources.feeds import feed_for, feed_kinds
from pipeline.sources.search import (
    CommonCrawlBackend,
    SearchError,
    SearxngBackend,
    backend_for,
    backend_names,
)
from pipeline.store import WorkspaceStore

# Reuse the sibling suites' grounding helpers (the established cross-test-module pattern).
from tests.test_sources_feeds import bind_and_ground, kind_defaults

REPO_ROOT = Path(__file__).resolve().parents[1]
UA = "Optiquity Test Harness (test@example.test)"
INDEX = "CC-MAIN-2024-51"
CDX_HOST = "https://index.commoncrawl.org"

# --- Synthetic page fixtures (rule 4: invented example.test content) ------------------------------

# A page WITH a publication date (article:published_time meta) and ample main text.
PAGE_DATED = b"""<html><head><title>Widget 2.0 announced</title>
<meta property="article:published_time" content="2024-05-01T12:00:00Z"/></head>
<body><article><h1>Widget 2.0 announced</h1>
<p>The new Widget 2.0 ships next quarter with major reliability and performance improvements across
the entire product line, alongside a redesigned enclosure and a longer warranty.</p>
</article></body></html>"""

# A page with NO date anywhere → trafilatura recovers text but no date → as_of must be None.
PAGE_DATELESS = b"""<html><head><title>Widget recall notice</title></head>
<body><article><h1>Widget recall notice</h1>
<p>A voluntary recall of early Widget units has been issued after a small number of reports of
overheating; affected owners can request a free replacement unit from any authorized service
center.</p></article></body></html>"""

# A page trafilatura cannot turn into main text (no body content) → a SOFT skip, never a crash.
PAGE_NOTEXT = b"<html><head><title>Empty</title></head><body></body></html>"

URL_DATED = "https://blog.example.test/widget-2"
URL_DATELESS = "https://blog.example.test/recall"
URL_NOTEXT = "https://blog.example.test/empty"

PAGES = {URL_DATED: PAGE_DATED, URL_DATELESS: PAGE_DATELESS, URL_NOTEXT: PAGE_NOTEXT}


def _cdx_line(url: str, *, offset: str = "100", length: str = "2048") -> str:
    """One Common Crawl CDX `output=json` capture line (verbatim-shaped fields)."""
    return json.dumps(
        {
            "urlkey": "test)/",
            "timestamp": "20241201120000",
            "url": url,
            "mime": "text/html",
            "status": "200",
            "digest": "SHA1TESTDIGEST",
            "length": length,
            "offset": offset,
            "filename": "crawl-data/CC-MAIN-2024-51/segments/seg/warc/x.warc.gz",
        }
    )


# Two distinct pages + a DUPLICATE url (dedup) + a no-text page (soft skip).
CDX_NDJSON = "\n".join(
    [
        _cdx_line(URL_DATED),
        _cdx_line(URL_DATELESS),
        _cdx_line(URL_DATED, offset="9000"),  # duplicate URL → must collapse
        _cdx_line(URL_NOTEXT),
    ]
).encode("utf-8")

# A single dateless capture (for the idempotency / as_of=None proof).
CDX_DATELESS = _cdx_line(URL_DATELESS).encode("utf-8")


def make_get(index_body: bytes, pages: dict[str, bytes], *, calls: list | None = None):
    """A fixture fetch seam: routes the CDX index query to `index_body` and each page URL to its
    fixture HTML. NEVER hits the network; asserts https + a UA header rides every request."""

    def _get(url, *, headers, timeout):
        if calls is not None:
            calls.append((url, dict(headers)))
        assert url.startswith("https://"), url
        assert headers.get("User-Agent"), "a UA header must ride the request (§3.3 config, not key)"
        if url.startswith(f"{CDX_HOST}/"):
            return index_body
        return pages.get(url, b"")  # an unknown page → empty → soft skip

    return _get


def cc_config(namespace, *, source_id="x-cc", connection=None, budget=None) -> FeedConfig:
    conn = {"query": "blog.example.test/*", "index": INDEX, "user_agent": UA}
    if connection is not None:
        conn = {**conn, **connection}
    return FeedConfig(
        source_id=source_id,
        kind="commoncrawl",
        namespace=namespace,
        content_kind="web-article",
        temporality="snapshot",
        budget=budget or Budget(max_facts=100),
        connection=conn,
    )


# ---------------------------------------------------------------------------
# Registries — the feed + the search backend both ship one-file.
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_commoncrawl_feed_is_registered(self):
        assert "commoncrawl" in feed_kinds()
        assert feed_for("commoncrawl").kind == "commoncrawl"

    def test_prior_feeds_still_registered(self):
        # Adding commoncrawl did not disturb the P2 feed set (edgar publishes; rss/gdelt lead).
        assert {"edgar", "rss", "gdelt"} <= set(feed_kinds())

    def test_search_backends_registered(self):
        assert "commoncrawl" in backend_names() and "searxng" in backend_names()
        assert backend_for("commoncrawl").name == "commoncrawl"

    def test_unknown_backend_is_loud(self):
        with pytest.raises(SearchError):
            backend_for("no-such-backend")

    def test_web_article_kind_is_lead_only(self):
        # The feed's content-kind pins reuse_rights: lead-only → never republishable.
        assert kind_defaults("web-article")["reuse_rights"] == "lead-only"


# ---------------------------------------------------------------------------
# The trafilatura extractor — clean text + date; dateless → None; malformed → SOFT.
# ---------------------------------------------------------------------------


class TestExtractor:
    def test_extract_clean_text_and_date(self):
        ex = extract(PAGE_DATED, url=URL_DATED)
        assert isinstance(ex, Extraction)
        assert ex.ok is True
        assert "Widget 2.0" in ex.text
        assert ex.date == datetime.date(2024, 5, 1)

    def test_dateless_page_yields_as_of_none(self):
        ex = extract(PAGE_DATELESS, url=URL_DATELESS)
        assert ex.ok is True and ex.text  # main text recovered
        assert ex.date is None  # NEVER a wall-clock date

    @pytest.mark.parametrize("bad", [b"", b"   ", b"<<<not html at all {", PAGE_NOTEXT])
    def test_malformed_or_empty_is_soft_never_raises(self, bad):
        ex = extract(bad)  # must not raise
        assert ex.ok is False and ex.text == ""


# ---------------------------------------------------------------------------
# The commoncrawl search backend — CDX parse + host-pin + the searxng loud stub.
# ---------------------------------------------------------------------------


class TestSearchBackend:
    def test_cdx_index_parses_into_hits(self):
        hits = CommonCrawlBackend().search(
            "blog.example.test/*", http_get=make_get(CDX_NDJSON, PAGES), index=INDEX
        )
        urls = [h.url for h in hits]
        assert urls == [URL_DATED, URL_DATELESS, URL_NOTEXT]  # dup URL collapsed, order preserved
        assert hits[0].locator and hits[0].locator.startswith("crawl-data/CC-MAIN-2024-51")

    def test_search_targets_the_pinned_index_host(self):
        calls: list = []
        CommonCrawlBackend().search(
            "blog.example.test/*",
            http_get=make_get(CDX_NDJSON, PAGES, calls=calls),
            index=INDEX,
        )
        assert calls[0][0].startswith(f"{CDX_HOST}/{INDEX}-index?url=")

    def test_off_host_base_url_refused_loud(self):
        with pytest.raises(SearchError, match="HOST-PINNED"):
            CommonCrawlBackend().search(
                "blog.example.test/*",
                http_get=make_get(CDX_NDJSON, PAGES),
                index=INDEX,
                base_url="https://evil.test",
            )

    def test_missing_index_is_loud(self):
        with pytest.raises(SearchError, match="index"):
            CommonCrawlBackend().search("q", http_get=make_get(CDX_NDJSON, PAGES))

    def test_searxng_slot_is_a_loud_stub(self):
        # DEFERRED/pluggable — never a silent empty result.
        with pytest.raises(SearchError, match="DEFERRED"):
            SearxngBackend().search("q", http_get=make_get(CDX_NDJSON, PAGES))
        assert backend_for("searxng").name == "searxng"


# ---------------------------------------------------------------------------
# The Common Crawl feed — INFERRED leads WITHHELD; snapshot; dedup; metered.
# ---------------------------------------------------------------------------


class TestCommonCrawlLeads:
    def test_facts_are_inferred_leads_never_published(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        report = ingest_feed(cc_config("cc-web"), store, http_get=make_get(CDX_NDJSON, PAGES))
        # two distinct pages (dup URL collapsed, the no-text page softly skipped)
        assert report.novel_cached == 2
        assert report.temporality == "snapshot"

        _inst, outcome = bind_and_ground(
            store, "cc-web", content_kind="web-article", temporality="snapshot", query="widget"
        )
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert not published, "an INFERRED open-web fact must NEVER publish (tier gate)"
        assert outcome.leads, "the web pages must ground as leads"
        assert all(f.tier == TIER_INFERRED for f in outcome.leads)
        assert all(f.subject.startswith("commoncrawl:") for f in outcome.leads)

    def test_temporality_snapshot_rides_the_grounding_ledger(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        ingest_feed(cc_config("cc-tempo"), store, http_get=make_get(CDX_NDJSON, PAGES))
        _inst, outcome = bind_and_ground(
            store, "cc-tempo", content_kind="web-article", temporality="snapshot", query="widget"
        )
        ledger, _entries = build_grounding_ledger(
            outcome.leads, source_repos={"x-cache": "cc-web-cache"}
        )
        assert next(iter(ledger.values()))["temporality"] == "snapshot"

    def test_extracted_date_rides_onto_the_lead(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        ingest_feed(cc_config("cc-date"), store, http_get=make_get(CDX_NDJSON, PAGES))
        ns_dir = namespace_dir(store, "cc-date")
        facts = {f.subject: f for f in read_slice(ns_dir, read_head(ns_dir))}
        assert facts[f"commoncrawl:{URL_DATED}"].as_of == datetime.date(2024, 5, 1)
        assert facts[f"commoncrawl:{URL_DATELESS}"].as_of is None  # dateless → None

    def test_cost_is_metered_zero_model_spend(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        report = ingest_feed(cc_config("cc-cost"), store, http_get=make_get(CDX_NDJSON, PAGES))
        # 1 CDX index query + 3 unique page fetches (dated, dateless, no-text) = 4 metered requests
        assert report.requests == 4
        assert report.bytes > 0

    def test_dedup_by_url_collapses_repeats(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        # the CDX carries URL_DATED twice; the sealed slice holds it once
        report = ingest_feed(cc_config("cc-dedup"), store, http_get=make_get(CDX_NDJSON, PAGES))
        ns_dir = namespace_dir(store, "cc-dedup")
        subjects = [f.subject for f in read_slice(ns_dir, read_head(ns_dir))]
        assert subjects.count(f"commoncrawl:{URL_DATED}") == 1
        assert report.novel_cached == 2


# ---------------------------------------------------------------------------
# Idempotency — a re-ingest of unchanged content is a content-addressed no-op.
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_reingest_is_a_noop(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        first = ingest_feed(cc_config("cc-idem"), store, http_get=make_get(CDX_NDJSON, PAGES))
        assert first.novel_cached == 2 and first.head_advanced is True
        second = ingest_feed(cc_config("cc-idem"), store, http_get=make_get(CDX_NDJSON, PAGES))
        assert second.novel_cached == 0
        assert second.head_advanced is False  # the content-addressed seal is the no-op
        assert second.digest == first.digest

    def test_dateless_page_reingest_is_byte_identical_noop(self, tmp_path):
        # A page with NO date → as_of=None (not today()); the seal is stable, so a re-ingest is a
        # byte-identical no-op — a wall-clock date would poison this (a daily-changing digest).
        store = WorkspaceStore(tmp_path / "ws")
        pages = {URL_DATELESS: PAGE_DATELESS}
        first = ingest_feed(cc_config("cc-noda"), store, http_get=make_get(CDX_DATELESS, pages))
        assert first.novel_cached == 1
        ns_dir = namespace_dir(store, "cc-noda")
        (fact,) = read_slice(ns_dir, read_head(ns_dir))
        assert fact.as_of is None
        second = ingest_feed(cc_config("cc-noda"), store, http_get=make_get(CDX_DATELESS, pages))
        assert second.novel_cached == 0 and second.digest == first.digest


# ---------------------------------------------------------------------------
# Host-pin at the FEED boundary + required config (mirror EDGAR/GDELT).
# ---------------------------------------------------------------------------


class TestFeedHostPinAndConfig:
    def test_feed_base_url_override_refused_loud(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        with pytest.raises(FeedError, match="HOST-PINNED"):
            ingest_feed(
                cc_config("cc-evil", connection={"base_url": "https://evil.test"}),
                store,
                http_get=make_get(CDX_NDJSON, PAGES),
            )

    def test_feed_requires_a_query(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = FeedConfig(
            source_id="x-cc-noq",
            kind="commoncrawl",
            namespace="cc-noq",
            content_kind="web-article",
            temporality="snapshot",
            connection={"index": INDEX, "user_agent": UA},
        )
        with pytest.raises(FeedError, match="query"):
            ingest_feed(config, store, http_get=make_get(CDX_NDJSON, PAGES))

    def test_feed_requires_an_index(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = FeedConfig(
            source_id="x-cc-noidx",
            kind="commoncrawl",
            namespace="cc-noidx",
            content_kind="web-article",
            temporality="snapshot",
            connection={"query": "blog.example.test/*", "user_agent": UA},
        )
        with pytest.raises(FeedError, match="index"):
            ingest_feed(config, store, http_get=make_get(CDX_NDJSON, PAGES))


# ---------------------------------------------------------------------------
# The CLI surfaces the new feed kind in `sources ingest --help` (discovery).
# ---------------------------------------------------------------------------


class TestCliSurfacesKind:
    def test_ingest_help_lists_commoncrawl(self, capsys):
        with pytest.raises(SystemExit):
            _cmd_sources(["ingest", "--help"])
        out = capsys.readouterr().out
        assert "commoncrawl" in out
