"""The GDELT DOC 2.0 feed (sources P2b-feeds) — news METADATA leads, never article prose.

GDELT is a global news AGGREGATOR: its DOC 2.0 API returns, keyless, the metadata it computed about
articles it indexed (the article URL, domain, source country, language, seen-date, and — in the
relevant modes — GDELT's own tone/theme/entity tags). This feed normalizes each record into an
**INFERRED** `Fact` (aggregator metadata is a SECONDARY lead / corroboration signal, never a
published primary) whose `claim` is a METADATA ASSERTION citable to GDELT.

**Licensing (from the research).** GDELT's redistributable content is its METADATA, NOT the article
text. The `claim` therefore states what GDELT recorded ABOUT an article — it NEVER carries scraped
article prose. The `news-metadata` content-kind pins `reuse_rights: attribution` (GDELT metadata is
redistributable with attribution), but the facts stay INFERRED, so the TIER gate keeps them leads /
corroboration regardless of the reuse right.

**Host-pinned** to the GDELT API host (like EDGAR is pinned to SEC): `kind: gdelt` may ONLY ever
fetch GDELT, so a `base_url` override is refused LOUDLY (an off-host override would let GDELT-shaped
JSON masquerade as GDELT metadata — also an SSRF door). Keyless + read-only; a declared User-Agent
is courtesy config, not a secret (§3.3). The `http_get` fetch seam is injected — no test hits the
live network. **Temporality = `snapshot`**: a DOC pull is a point-in-time capture (true AS OF the
seen date; the underlying index moves on), distinct from EDGAR's `archival` immutability.
"""

from __future__ import annotations

import datetime
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlencode

from pipeline.adapters.base import TIER_INFERRED, Anchor, Fact
from pipeline.sources.acquire import Feed, FeedConfig, FeedError, HttpGet
from pipeline.sources.control import CostMeter

__all__ = ["GdeltFeed"]

#: The GDELT DOC 2.0 API host — HOST-PINNED (not configurable): `kind: gdelt` can only ever fetch
#: GDELT, so the "this is GDELT metadata" characterization is self-verifying by code (an arbitrary
#: `base_url` could point GDELT-shaped JSON at a non-GDELT host — also SSRF). Keyless, public REST.
_GDELT_HOST = "https://api.gdeltproject.org"
_DOC_PATH = "/api/v2/doc/doc"

#: A polite default User-Agent when the descriptor names none (courtesy config, §3.3).
_DEFAULT_UA = "optiquity-content-pipeline (news-metadata reader; +https://github.com/optiquity)"

#: GDELT DOC caps a single ArtList response at 250 records; default to a modest pull.
_DEFAULT_MAX_RECORDS = 75
_MAX_RECORDS_CAP = 250


class GdeltFeed(Feed):
    """`kind: gdelt` — fetch GDELT DOC 2.0 ArtList JSON; normalize metadata to INFERRED leads."""

    kind = "gdelt"

    def fetch(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter
    ) -> list[Mapping[str, Any]]:
        """GET `api.gdeltproject.org/api/v2/doc/doc?query=…&mode=ArtList&format=json` and return
        its `articles` records (verbatim GDELT metadata fields only). HOST-PINNED to GDELT — a
        `base_url` override is refused (it would let GDELT-shaped JSON masquerade as GDELT metadata;
        also SSRF). Read-only + keyless; the UA rides from config (courtesy, not a secret, §3.3)."""
        conn = config.connection
        if "base_url" in conn:
            raise FeedError(
                "sources-feed-error: the gdelt feed is HOST-PINNED to the GDELT API "
                f"({_GDELT_HOST}); a `base_url` override is not honored (it would let "
                "`kind: gdelt` present non-GDELT JSON as GDELT metadata) — remove it"
            )
        query = conn.get("query")
        if not isinstance(query, str) or not query.strip():
            raise FeedError(
                "sources-feed-error: gdelt feed requires a `query` string in connection "
                f"(the GDELT DOC search expression), got {query!r}"
            )
        max_records = conn.get("max_records", _DEFAULT_MAX_RECORDS)
        if isinstance(max_records, bool) or not isinstance(max_records, int) or max_records < 1:
            raise FeedError(
                "sources-feed-error: gdelt feed `max_records` must be a positive integer "
                f"(<= {_MAX_RECORDS_CAP}), got {max_records!r}"
            )
        params = {
            "query": query.strip(),
            "mode": "ArtList",
            "format": "json",
            "maxrecords": min(max_records, _MAX_RECORDS_CAP),
            "sort": "DateDesc",
        }
        timespan = conn.get("timespan")
        if isinstance(timespan, str) and timespan.strip():
            params["timespan"] = timespan.strip()
        user_agent = conn.get("user_agent")
        headers = {
            "User-Agent": user_agent if isinstance(user_agent, str) and user_agent.strip()
            else _DEFAULT_UA
        }
        url = f"{_GDELT_HOST}{_DOC_PATH}?{urlencode(params)}"
        payload = http_get(url, headers=headers, timeout=30.0)
        meter.record_response(payload)
        if not payload:
            return []  # an empty body — nothing indexed for the query window; not an error
        try:
            doc = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FeedError(
                f"sources-feed-error: gdelt DOC response for query {query!r} is not valid JSON: "
                f"{exc}"
            ) from exc
        if not isinstance(doc, Mapping):
            raise FeedError("sources-feed-error: gdelt DOC response body must be a JSON object")
        articles = doc.get("articles", []) or []
        if not isinstance(articles, Sequence) or isinstance(articles, str | bytes):
            raise FeedError(
                "sources-feed-error: gdelt DOC `articles` must be a JSON array of records"
            )
        return [a for a in articles if isinstance(a, Mapping)]

    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """One GDELT article record → one INFERRED `Fact` carrying GDELT's OWN metadata: `subject`
        = `gdelt:<article-url>` (stable, dedup key), `claim` = a METADATA ASSERTION (NEVER scraped
        article prose — GDELT redistributes metadata, not text), one `url-fragment` anchor (the
        article URL), `as_of` = the seen date. DEDUP BY article URL within the pull (first wins)."""
        seen_urls: set[str] = set()
        facts: list[Fact] = []
        for rec in raw:
            url = str(rec.get("url") or "").strip()
            if not url or url in seen_urls:
                continue  # dedup by article URL (§ within-pull; content address covers re-pulls)
            seen_urls.add(url)
            facts.append(
                Fact(
                    subject=f"gdelt:{url}",
                    claim=self._claim(rec),
                    # INFERRED, ALWAYS: aggregator metadata is a SECONDARY lead / corroboration
                    # signal, never a published primary (EXTRACTED stays EDGAR-class).
                    tier=TIER_INFERRED,
                    anchors=(Anchor("url-fragment", url),),
                    as_of=self._as_of(str(rec.get("seendate") or "")),
                )
            )
        return facts

    @staticmethod
    def _claim(rec: Mapping[str, Any]) -> str:
        """A metadata assertion built from GDELT's OWN returned fields — citable to GDELT, never the
        article body. The article title is GDELT's recorded headline metadata (short), framed here
        as GDELT's assertion ('GDELT DOC indexed …'), so no article prose is ever republished."""
        title = str(rec.get("title") or "").strip() or "(untitled)"
        domain = str(rec.get("domain") or "").strip() or "an unlisted domain"
        country = str(rec.get("sourcecountry") or "").strip()
        language = str(rec.get("language") or "").strip()
        seendate = str(rec.get("seendate") or "").strip()
        facets = ", ".join(
            part for part in (domain, country, language) if part
        )
        claim = f"GDELT DOC indexed a news article ({facets}) titled {title!r}"
        if seendate:
            claim += f", seen {seendate}"
        tone = rec.get("tone")
        if isinstance(tone, int | float) and not isinstance(tone, bool):
            claim += f"; GDELT tone score {tone}"
        return claim + "."

    @staticmethod
    def _as_of(seendate: str) -> datetime.date | None:
        """The GDELT seen date (`YYYYMMDDThhmmssZ`) as a BARE date (§6.2 date-granular freshness);
        `None` when it does not yield a valid date (never an ambient `today()` — that would make the
        sealed slice non-deterministic and break content-addressed idempotency)."""
        digits = re.sub(r"\D", "", seendate)[:8]
        if len(digits) == 8:
            try:
                return datetime.date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
            except (ValueError, TypeError):
                return None
        return None
