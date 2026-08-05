"""The generic RSS 2.0 / Atom web feed (sources P2b-feeds) — a LEAD source, never a published fact.

Where EDGAR is a CHARACTERIZED PRIMARY that earns EXTRACTED (a regulatory filing), a generic web
feed is UNCHARACTERIZED: an arbitrary blog/news RSS or Atom stream. Its entries are stamped
**INFERRED** — a LEAD to verify, never published as fact (§6.5 tier-honesty; EXTRACTED stays
EDGAR-class). The `web-article` content-kind pins `reuse_rights: lead-only`, so even a hypothetical
upgrade could never republish it — doubly a lead.

Parsing rides **feedparser** (the maintainer-approved 2nd runtime dep) — RSS 2.0 + Atom in one
lenient parser. The `http_get` fetch seam is INJECTED (tests hand fixture feed bytes straight to
`feedparser.parse`), so NO test touches the live network (rule 1). The feed is keyless + read-only;
a declared User-Agent is config, not a secret (§3.3).

**Conditional GET.** A descriptor MAY carry `etag`/`modified` validators; the fetch sends them as
`If-None-Match`/`If-Modified-Since`. A server that finds nothing changed answers **304 Not
Modified** with no body — `default_http_get` reads that as an EMPTY payload, and an empty body is
the feed's "nothing new to acquire" path (zero records → zero novel facts → an idempotent no-op).

**Bozo (malformed feed) is soft.** feedparser sets the `bozo` bit on any well-formedness problem;
this feed NEVER raises on that alone (§ resilience) — it processes whatever entries feedparser
recovered, and a bozo feed with zero usable entries is simply an empty acquire, not a crash.

**Temporality = `live`.** A web feed is a rolling window: each pull is the moving head, superseded
by the next (contrast EDGAR's `archival` immutability). That slice-provenance rides the cache-reader
connection onto the §15 ledger; it is never a §6.2 score and never a fact-identity input (§7.2).
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping, Sequence
from typing import Any

import feedparser

from pipeline.adapters.base import TIER_INFERRED, Anchor, Fact
from pipeline.sources.acquire import Feed, FeedConfig, FeedError, HttpGet
from pipeline.sources.control import CostMeter

__all__ = ["RssFeed"]

#: A polite default User-Agent when the descriptor names none (a UA is courtesy config, §3.3).
_DEFAULT_UA = "optiquity-content-pipeline (feed reader; +https://github.com/optiquity)"

#: Strip HTML/XML markup from an entry's text so a lead claim is clean prose, not tag soup.
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


class RssFeed(Feed):
    """`kind: rss` — a generic RSS 2.0 / Atom web feed; entries normalize to INFERRED leads."""

    kind = "rss"

    def fetch(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter
    ) -> list[Mapping[str, Any]]:
        """GET the feed URL (read-only, keyless) with any conditional validators, parse with
        feedparser, and split entries into per-entry records. NOT host-pinned (a web feed is
        host-generic — unlike EDGAR, it earns no EXTRACTED characterization, so there is nothing
        to self-verify by host). An empty body (a 304 Not Modified) yields ZERO records — the
        no-new-work path. A malformed (bozo) feed is soft: take recovered entries, never raise."""
        conn = config.connection
        url = conn.get("url")
        if not isinstance(url, str) or not url.strip():
            raise FeedError(
                "sources-feed-error: rss feed requires a `url` string in connection "
                f"(the RSS 2.0 / Atom feed URL), got {url!r}"
            )
        if not url.strip().lower().startswith("https://"):
            raise FeedError(
                "sources-feed-error: rss feed `url` must be https (keyless, read-only, §3.3), "
                f"got {url!r}"
            )
        user_agent = conn.get("user_agent")
        headers = {
            "User-Agent": user_agent if isinstance(user_agent, str) and user_agent.strip()
            else _DEFAULT_UA
        }
        etag = conn.get("etag")
        if isinstance(etag, str) and etag.strip():
            headers["If-None-Match"] = etag
        modified = conn.get("modified")
        if isinstance(modified, str) and modified.strip():
            headers["If-Modified-Since"] = modified

        content = http_get(url.strip(), headers=headers, timeout=30.0)
        meter.record_response(content)
        if not content:
            # A 304 Not Modified (empty body) — nothing new to acquire. Not an error; not a bozo.
            return []

        parsed = feedparser.parse(content)
        # Bozo is SOFT: never raise on well-formedness alone. feedparser is lenient and usually
        # still recovers entries from a slightly malformed feed; we take whatever it yields. Only a
        # bozo feed with zero recovered entries is an empty acquire (still no crash).
        entries = getattr(parsed, "entries", []) or []
        feed_meta = getattr(parsed, "feed", {}) or {}
        feed_id = (
            str(conn.get("feed_id") or "").strip()
            or str(feed_meta.get("id") or "").strip()
            or str(feed_meta.get("link") or "").strip()
            or config.source_id
        )
        records: list[Mapping[str, Any]] = []
        for entry in entries:
            # feedparser maps BOTH RSS <guid> and Atom <id> onto `entry.id`; fall back to the link.
            guid = str(entry.get("id") or entry.get("link") or "").strip()
            records.append(
                {
                    "feed_id": feed_id,
                    "guid": guid,
                    "title": str(entry.get("title") or "").strip(),
                    "summary": str(entry.get("summary") or "").strip(),
                    "link": str(entry.get("link") or "").strip(),
                    "published": str(entry.get("published") or entry.get("updated") or "").strip(),
                    "date_parsed": entry.get("published_parsed") or entry.get("updated_parsed"),
                    "bozo": bool(getattr(parsed, "bozo", 0)),
                }
            )
        return records

    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """One entry → one INFERRED `Fact`: `subject` = `<feed-id>#<guid/atom-id>` (stable, dedup
        key), `claim` = the entry title/summary text, one `url-fragment` anchor (the entry link),
        `as_of` = the entry published/updated date. DEDUP BY GUID within the pull (first wins) so a
        feed that repeats an item collapses it; cross-ingest idempotency then rides the sealed
        cache's content address. An entry with no guid or no usable text is skipped (never a
        subject-less / claim-less Fact)."""
        seen_guids: set[str] = set()
        facts: list[Fact] = []
        for rec in raw:
            guid = str(rec.get("guid") or "").strip()
            if not guid or guid in seen_guids:
                continue  # dedup by guid / Atom id (§ within-pull; content address covers re-pulls)
            seen_guids.add(guid)
            claim = self._claim(rec)
            if not claim:
                continue  # a Fact needs a non-empty claim; a text-less entry is not a lead
            feed_id = str(rec.get("feed_id") or config.source_id).strip() or config.source_id
            link = str(rec.get("link") or "").strip()
            anchors = (Anchor("url-fragment", link),) if link else ()
            facts.append(
                Fact(
                    subject=f"{feed_id}#{guid}",
                    claim=claim,
                    # INFERRED, ALWAYS: an uncharacterized web entry is a LEAD to verify, never
                    # EXTRACTED (EXTRACTED is reserved for a characterized primary — EDGAR-class).
                    tier=TIER_INFERRED,
                    anchors=anchors,
                    as_of=self._as_of(rec),
                )
            )
        return facts

    @staticmethod
    def _clean(text: str) -> str:
        """Markup-stripped, whitespace-collapsed lead text (feedparser summaries may carry HTML)."""
        return _WS_RE.sub(" ", _TAG_RE.sub(" ", text)).strip()

    def _claim(self, rec: Mapping[str, Any]) -> str:
        """The entry's title/summary as clean lead text: the title, enriched with a differing
        summary when present; the de-marked-up summary alone when there is no title."""
        title = self._clean(str(rec.get("title") or ""))
        summary = self._clean(str(rec.get("summary") or ""))
        if title and summary and summary != title:
            return f"{title} — {summary}"
        return title or summary

    @staticmethod
    def _as_of(rec: Mapping[str, Any]) -> datetime.date | None:
        """The entry's published/updated date as a BARE date (§6.2 date-granular freshness).

        Prefers feedparser's robust `*_parsed` struct_time; falls back to an ISO-date prefix of the
        raw string. Returns `None` (the adapter derives no freshness basis) when neither yields a
        date — NEVER an ambient `today()`, which would make the sealed slice non-deterministic and
        break content-addressed idempotency (a daily-changing digest)."""
        parsed = rec.get("date_parsed")
        if parsed is not None:
            try:
                return datetime.date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
            except (ValueError, TypeError, AttributeError, OverflowError):
                pass
        raw = str(rec.get("published") or "").strip()
        if len(raw) >= 10:
            try:
                return datetime.date.fromisoformat(raw[:10])
            except (ValueError, TypeError):
                pass
        return None
