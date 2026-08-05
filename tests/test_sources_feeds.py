"""Sources P2b-feeds: generic RSS/Atom + GDELT — INFERRED LEAD sources (never published as fact).

FIXTURES ONLY — the `http_get` fetch seam is injected, so NO test hits the live network (rule 1).
Content is SYNTHETIC-GENERIC (rule 4): invented example.test feeds/articles, no real/client content.
Everything runs under `tmp_path`; the real `users/` tree is never touched.

Coverage map (the P2b-feeds acceptance set):
  - RSS/Atom  ingest a canned RSS 2.0 + a canned Atom fixture → sealed slice → resolve+drive → the
              facts are INFERRED and WITHHELD as leads (never published); dedup by guid; a
              conditional-GET 304 yields no new facts; a bozo/malformed feed is SOFT (no crash);
              temporality `live` rides the §15 grounding ledger.
  - GDELT     a canned DOC 2.0 JSON fixture → INFERRED metadata leads (claim = GDELT metadata, NEVER
              scraped article prose); the host-pin refuses an off-host `base_url` LOUD; temporality
              `snapshot`.
  - HONESTY   EXTRACTED stays EDGAR-class: every RSS/GDELT fact is INFERRED, so none publishes even
              when its reuse_rights clear the republish gate (GDELT `news-metadata` = attribution).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from pipeline.__main__ import _cmd_sources
from pipeline.adapters import default_adapters
from pipeline.adapters.base import TIER_INFERRED
from pipeline.compose import build_grounding_ledger
from pipeline.grounding import SourceInstance, ground_item
from pipeline.m1 import Resolver
from pipeline.m3 import resolve_selection
from pipeline.sources.acquire import FeedConfig, FeedError, ingest_feed
from pipeline.sources.cache import namespace_dir, read_head
from pipeline.sources.control import Budget
from pipeline.sources.feeds import feed_for, feed_kinds
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.date(2026, 7, 16)
UA = "Optiquity Test Harness (test@example.test)"

# --- Synthetic feed fixtures (rule 4: invented example.test content, no client data) -------------

RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Widget Blog</title>
    <link>https://blog.example.test/</link>
    <item>
      <title>Widget 2.0 announced</title>
      <link>https://blog.example.test/widget-2</link>
      <guid>https://blog.example.test/widget-2</guid>
      <pubDate>Wed, 01 May 2024 12:00:00 GMT</pubDate>
      <description>The new Widget 2.0 ships next quarter.</description>
    </item>
    <item>
      <title>Widget recall notice</title>
      <link>https://blog.example.test/recall</link>
      <guid>https://blog.example.test/recall</guid>
      <pubDate>Thu, 02 May 2024 09:00:00 GMT</pubDate>
      <description>A voluntary recall of early Widget units.</description>
    </item>
  </channel>
</rss>
"""

# The SAME guid twice — must collapse to one fact (dedup by guid).
RSS_DUP = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Widget Blog</title>
    <link>https://blog.example.test/</link>
    <item>
      <title>Widget 2.0 announced</title>
      <link>https://blog.example.test/widget-2</link>
      <guid>https://blog.example.test/widget-2</guid>
      <pubDate>Wed, 01 May 2024 12:00:00 GMT</pubDate>
      <description>The new Widget 2.0 ships next quarter.</description>
    </item>
    <item>
      <title>Widget 2.0 announced (mirror)</title>
      <link>https://blog.example.test/widget-2</link>
      <guid>https://blog.example.test/widget-2</guid>
      <pubDate>Wed, 01 May 2024 12:00:00 GMT</pubDate>
      <description>The new Widget 2.0 ships next quarter.</description>
    </item>
  </channel>
</rss>
"""

ATOM_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Gadget News</title>
  <link href="https://news.example.test/"/>
  <id>urn:uuid:gadget-feed</id>
  <entry>
    <title>Gadget X reviewed</title>
    <link href="https://news.example.test/gadget-x"/>
    <id>urn:uuid:gadget-x-0001</id>
    <updated>2024-06-15T08:30:00Z</updated>
    <summary>An in-depth look at the new Gadget X.</summary>
  </entry>
</feed>
"""

# Plainly not a feed — feedparser sets the bozo bit; the feed must handle it softly (no crash).
BOZO = b"This is plainly not XML or a feed at all >>> {"

GDELT_JSON = json.dumps(
    {
        "articles": [
            {
                "url": "https://news.example.test/widget-rally",
                "title": "Widget markets rally on strong demand",
                "seendate": "20240501T120000Z",
                "domain": "news.example.test",
                "language": "English",
                "sourcecountry": "United States",
                "tone": -1.5,
            },
            {
                "url": "https://press.example.test/widget-recall",
                "title": "Regulator reviews Widget recall",
                "seendate": "20240502T090000Z",
                "domain": "press.example.test",
                "language": "English",
                "sourcecountry": "United Kingdom",
            },
            {
                # a DUPLICATE url — must collapse (dedup by article URL)
                "url": "https://news.example.test/widget-rally",
                "title": "Widget markets rally (syndicated copy)",
                "seendate": "20240501T130000Z",
                "domain": "news.example.test",
                "language": "English",
                "sourcecountry": "United States",
            },
        ]
    }
).encode("utf-8")


def make_get(payload: bytes, *, calls: list | None = None, require_conditional: bool = False):
    """A fixture fetch seam: returns canned bytes + records (url, headers). NEVER hits network."""

    def _get(url, *, headers, timeout):
        if calls is not None:
            calls.append((url, dict(headers)))
        assert url.startswith("https://"), url
        assert headers.get("User-Agent"), "a UA header must ride the request (§3.3 config, not key)"
        if require_conditional:
            assert headers.get("If-None-Match") or headers.get(
                "If-Modified-Since"
            ), "a conditional GET must send the stored etag/modified validator"
        return payload

    return _get


def kind_defaults(kind_id: str) -> dict:
    """Resolve a REAL shipped content-kind → its default score bundle (as `build_instance` does)."""
    kind = Resolver(REPO_ROOT).resolve("content-kinds", kind_id)
    defaults = kind.defaults()
    defaults.update(kind.effective)
    return defaults


def rss_config(namespace, *, source_id="x-rss", connection=None, budget=None) -> FeedConfig:
    conn = {"url": "https://blog.example.test/feed.xml", "user_agent": UA}
    if connection:
        conn.update(connection)
    return FeedConfig(
        source_id=source_id,
        kind="rss",
        namespace=namespace,
        content_kind="web-article",
        temporality="live",
        budget=budget or Budget(max_facts=100),
        connection=conn,
    )


def gdelt_config(namespace, *, source_id="x-gdelt", connection=None) -> FeedConfig:
    conn = {"query": "widget", "user_agent": UA}
    if connection:
        conn.update(connection)
    return FeedConfig(
        source_id=source_id,
        kind="gdelt",
        namespace=namespace,
        content_kind="news-metadata",
        temporality="snapshot",
        connection=conn,
    )


def bind_and_ground(store, namespace, *, content_kind, temporality, query, inst_id="x-cache"):
    """Bind a cache-reader source over the sealed slice and DRIVE the §6.3 resolver walk once."""
    ns_dir = namespace_dir(store, namespace)
    digest = read_head(ns_dir)
    inst = SourceInstance(
        id=inst_id,
        adapter="cache",
        connection={"path": str(ns_dir), "slice": digest, "temporality": temporality},
        content_kind=content_kind,
        kind_defaults=kind_defaults(content_kind),
    )
    outcome = ground_item(
        item="item-1",
        query=query,
        pool=[inst],
        selection=resolve_selection(),
        adapters=default_adapters(),
        now=NOW,
    )
    return inst, outcome


# ---------------------------------------------------------------------------
# Registry: the two new LEAD feeds + their content-kinds ship one-file.
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_rss_and_gdelt_are_registered(self):
        assert "rss" in feed_kinds() and "gdelt" in feed_kinds()
        assert feed_for("rss").kind == "rss"
        assert feed_for("gdelt").kind == "gdelt"

    def test_web_article_kind_is_lead_only(self):
        defaults = kind_defaults("web-article")
        # lead-only sits BELOW the `attribution` publish threshold → never republishable
        assert defaults["reuse_rights"] == "lead-only"

    def test_news_metadata_kind_is_attribution(self):
        defaults = kind_defaults("news-metadata")
        # attribution clears the RIGHTS gate — but the feed's INFERRED tier keeps facts as leads
        assert defaults["reuse_rights"] == "attribution"


# ---------------------------------------------------------------------------
# RSS / Atom — INFERRED leads, WITHHELD from publish; dedup; 304; bozo; temporality live.
# ---------------------------------------------------------------------------


class TestRssLeads:
    def test_rss_facts_are_inferred_leads_never_published(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        report = ingest_feed(rss_config("rss-blog"), store, http_get=make_get(RSS_XML))
        assert report.novel_cached == 2  # two distinct items
        assert report.temporality == "live"

        inst, outcome = bind_and_ground(
            store, "rss-blog", content_kind="web-article", temporality="live", query="widget"
        )
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert not published, "an INFERRED web-feed fact must never publish"
        assert outcome.leads, "the web entries must ground as leads"
        assert all(f.tier == TIER_INFERRED for f in outcome.leads)

    def test_temporality_live_rides_the_grounding_ledger(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        ingest_feed(rss_config("rss-live"), store, http_get=make_get(RSS_XML))
        _inst, outcome = bind_and_ground(
            store, "rss-live", content_kind="web-article", temporality="live", query="widget"
        )
        ledger, _entries = build_grounding_ledger(
            outcome.leads, source_repos={"x-cache": "rss-blog-cache"}
        )
        entry = next(iter(ledger.values()))
        assert entry["temporality"] == "live"  # §15 ledger provenance, omit-when-absent, here live

    def test_atom_entry_grounds_as_a_lead_keyed_by_atom_id(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        report = ingest_feed(
            rss_config("atom-feed", connection={"url": "https://news.example.test/atom.xml"}),
            store,
            http_get=make_get(ATOM_XML),
        )
        assert report.novel_cached == 1
        _inst, outcome = bind_and_ground(
            store, "atom-feed", content_kind="web-article", temporality="live", query="gadget"
        )
        assert outcome.leads and outcome.leads[0].tier == TIER_INFERRED
        # the Atom <id> is the stable dedup key baked into the subject
        assert "urn:uuid:gadget-x-0001" in outcome.leads[0].subject

    def test_dedup_by_guid_collapses_repeated_items(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        # two items share one <guid> → one fact (dedup by guid, first wins)
        report = ingest_feed(rss_config("rss-dup"), store, http_get=make_get(RSS_DUP))
        assert report.novel_cached == 1

    def test_conditional_get_304_yields_no_new_facts(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        first = ingest_feed(rss_config("rss-cond"), store, http_get=make_get(RSS_XML))
        assert first.novel_cached == 2 and first.head_advanced is True

        # a re-ingest carrying a stored validator; the server answers 304 (empty body) → no new work
        second = ingest_feed(
            rss_config("rss-cond", connection={"etag": '"abc-123"'}),
            store,
            http_get=make_get(b"", require_conditional=True),
        )
        assert second.fetched == 0 and second.novel_cached == 0
        assert second.head_advanced is False  # HEAD unmoved — the 304 = no-new-work path
        assert second.digest == first.digest

    def test_malformed_bozo_feed_is_soft_never_raises(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        # a malformed feed is a WARNING, not a crash — the ingest completes with zero facts
        report = ingest_feed(rss_config("rss-bozo"), store, http_get=make_get(BOZO))
        assert report.novel_cached == 0
        assert report.temporality == "live"

    def test_rss_url_must_be_https(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        with pytest.raises(FeedError, match="https"):
            ingest_feed(
                rss_config("rss-bad", connection={"url": "http://blog.example.test/feed.xml"}),
                store,
                http_get=make_get(RSS_XML),
            )


# ---------------------------------------------------------------------------
# GDELT — INFERRED news metadata leads; host-pinned; metadata-only claim; temporality snapshot.
# ---------------------------------------------------------------------------


class TestGdeltLeads:
    def test_gdelt_metadata_facts_are_inferred_leads(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        report = ingest_feed(gdelt_config("gdelt-news"), store, http_get=make_get(GDELT_JSON))
        assert report.novel_cached == 2  # three articles, one duplicate url collapsed
        assert report.temporality == "snapshot"

        inst, outcome = bind_and_ground(
            store, "gdelt-news", content_kind="news-metadata", temporality="snapshot",
            query="widget",
        )
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert not published, "an INFERRED GDELT metadata fact must never publish (tier gate)"
        assert outcome.leads and all(f.tier == TIER_INFERRED for f in outcome.leads)

    def test_gdelt_claim_is_metadata_not_article_prose(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        ingest_feed(gdelt_config("gdelt-claim"), store, http_get=make_get(GDELT_JSON))
        _inst, outcome = bind_and_ground(
            store, "gdelt-claim", content_kind="news-metadata", temporality="snapshot",
            query="widget",
        )
        claims = [f.claim for f in outcome.leads]
        # every claim is GDELT's OWN metadata assertion — citable to GDELT, never scraped prose
        assert all(c.startswith("GDELT DOC indexed") for c in claims)
        joined = " ".join(claims)
        assert "news.example.test" in joined  # the article DOMAIN (GDELT metadata) rode in
        assert "GDELT tone score" in joined  # GDELT's computed tone metadata rode in

    def test_gdelt_temporality_snapshot_rides_the_ledger(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        ingest_feed(gdelt_config("gdelt-tempo"), store, http_get=make_get(GDELT_JSON))
        _inst, outcome = bind_and_ground(
            store, "gdelt-tempo", content_kind="news-metadata", temporality="snapshot",
            query="widget",
        )
        ledger, _entries = build_grounding_ledger(
            outcome.leads, source_repos={"x-cache": "gdelt-news-cache"}
        )
        assert next(iter(ledger.values()))["temporality"] == "snapshot"

    def test_gdelt_host_pin_refuses_off_host_base_url_loud(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        with pytest.raises(FeedError, match="HOST-PINNED"):
            ingest_feed(
                gdelt_config("gdelt-evil", connection={"base_url": "https://evil.test"}),
                store,
                http_get=make_get(GDELT_JSON),
            )

    def test_gdelt_requires_a_query(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = FeedConfig(
            source_id="x-gdelt-noq",
            kind="gdelt",
            namespace="gdelt-noq",
            content_kind="news-metadata",
            temporality="snapshot",
            connection={"user_agent": UA},
        )
        with pytest.raises(FeedError, match="query"):
            ingest_feed(config, store, http_get=make_get(GDELT_JSON))

    def test_gdelt_fetch_targets_the_pinned_host(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        calls: list = []
        ingest_feed(
            gdelt_config("gdelt-host"),
            store,
            http_get=make_get(GDELT_JSON, calls=calls),
        )
        assert calls and calls[0][0].startswith("https://api.gdeltproject.org/api/v2/doc/doc?")


# ---------------------------------------------------------------------------
# The CLI surfaces the new feed kinds in `sources ingest --help` (discovery).
# ---------------------------------------------------------------------------


class TestCliSurfacesKinds:
    def test_ingest_help_lists_the_new_kinds(self, capsys):
        with pytest.raises(SystemExit):
            _cmd_sources(["ingest", "--help"])
        out = capsys.readouterr().out
        assert "rss" in out and "gdelt" in out and "edgar" in out
