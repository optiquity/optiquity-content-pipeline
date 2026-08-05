"""The Common Crawl feed (sources P3a) — a WEB LEAD source built on the deterministic primitives.

Common Crawl is a public, reproducible MONTHLY web snapshot. This feed pins one crawl index, asks
the `commoncrawl` SEARCH backend (`pipeline.sources.search`) for the captures whose URL matches a
descriptor pattern, fetches each matching page's bytes READ-ONLY through the injected `http_get`,
and runs them through the trafilatura EXTRACTOR (`pipeline.sources.extract`) to recover clean main
text + a publication date. Each page becomes ONE **INFERRED** `Fact` — the open web is a LEAD to
verify, NEVER a published primary (EXTRACTED is reserved for a characterized primary, EDGAR-class;
§6.5 tier-honesty). The `web-article` content-kind pins `reuse_rights: lead-only`, so a Common Crawl
fact is DOUBLY a lead: neither true-enough (INFERRED tier) nor allowed (lead-only) to publish.

**Host-pinned** (mirroring EDGAR/GDELT): the search runs only against the Common Crawl hosts, and a
`base_url` override in the descriptor is refused LOUDLY. The extractor is fed BYTES the feed already
fetched — extraction itself never touches the network (rule 1). The `http_get` seam is injected, so
NO test hits the live network.

**Temporality = `snapshot`.** A pinned crawl index is a point-in-time capture (reproducible AS OF
that crawl), distinct from EDGAR's `archival` immutability and a live RSS window. That slice
provenance rides the cache-reader connection onto the §15 ledger; it is never a §6.2 score and never
a fact-identity input (§7.2).

**Idempotency.** trafilatura extracts the same bytes to the same text (`deduplicate` off), and a
dateless page yields `as_of=None` (never a wall-clock date) — so a re-ingest of unchanged content
re-normalizes to the SAME facts, dedups against HEAD, and re-seals the SAME content-addressed digest
(a no-op). Dedup is by page URL within a pull; the sealed cache's content address covers re-pulls.

**Deferred (v1).** The stable WARC-offset anchor (fetching the exact snapshot bytes from the CC data
host) is a future enhancement carried by the search hit's `filename@offset+length` locator; v1
anchors each fact with a single `url-fragment` (the page URL) and fetches the live page. CDX
pagination beyond one `limit` page is likewise a later increment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pipeline.adapters.base import TIER_INFERRED, Anchor, Fact
from pipeline.sources.acquire import Feed, FeedConfig, FeedError, HttpGet
from pipeline.sources.control import CostMeter
from pipeline.sources.extract import extract
from pipeline.sources.search import SearchError, backend_for

__all__ = ["CommonCrawlFeed"]

#: A polite default User-Agent when the descriptor names none (courtesy config, §3.3).
_DEFAULT_UA = "optiquity-content-pipeline (common-crawl reader; +https://github.com/optiquity)"

#: A default per-pull capture cap when the descriptor sets none (a lead pull, not a bulk dump).
_DEFAULT_LIMIT = 50

#: The claim carries a BOUNDED excerpt of the extracted main text — enough to be a useful lead,
#: never the whole article (keeps the sealed slice tidy; lead-only content is never republished).
_MAX_CLAIM_CHARS = 600


class CommonCrawlFeed(Feed):
    """`kind: commoncrawl` — search the Common Crawl index for matching pages, extract → INFERRED
    leads. Host-pinned; the extractor is fed injected-fetch bytes; temporality `snapshot`."""

    kind = "commoncrawl"

    def fetch(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter
    ) -> list[Mapping[str, Any]]:
        """Search the pinned crawl index for the descriptor's URL pattern, fetch each matching page
        READ-ONLY, and extract clean text + date. HOST-PINNED — a `base_url` override is refused
        LOUDLY (it would let non-CC results masquerade as CC captures; also SSRF). A single
        unfetchable/unextractable page is SOFT (skipped), so one bad page never aborts the pull."""
        conn = config.connection
        if "base_url" in conn:
            raise FeedError(
                "sources-feed-error: the commoncrawl feed is HOST-PINNED to Common Crawl; a "
                "`base_url` override is not honored (it would let `kind: commoncrawl` present "
                "non-CC results as Common Crawl captures — also SSRF) — remove it"
            )
        query = conn.get("query")
        if not isinstance(query, str) or not query.strip():
            raise FeedError(
                "sources-feed-error: commoncrawl feed requires a `query` string in connection "
                f"(a Common Crawl URL/domain pattern, e.g. 'example.com/*'), got {query!r}"
            )
        index = conn.get("index")
        if not isinstance(index, str) or not index.strip():
            raise FeedError(
                "sources-feed-error: commoncrawl feed requires an `index` crawl id in connection "
                "(e.g. 'CC-MAIN-2024-51') — the exact monthly snapshot to query (reproducible; "
                "never guessed)"
            )
        limit = conn.get("limit", _DEFAULT_LIMIT)
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise FeedError(
                f"sources-feed-error: commoncrawl `limit` must be a positive integer, got {limit!r}"
            )
        user_agent = conn.get("user_agent")
        ua = user_agent if isinstance(user_agent, str) and user_agent.strip() else _DEFAULT_UA

        metered = _metered(http_get, meter)  # every fetch (the CDX query + each page) accrues cost
        backend = backend_for("commoncrawl")
        try:
            hits = backend.search(
                query.strip(), http_get=metered, index=index.strip(), limit=limit, user_agent=ua
            )
        except SearchError as exc:
            # Translate the primitive's typed failure to a FeedError so the CLI stays a clean
            # exit-1 refusal (never a traceback), consistent with the other feeds.
            raise FeedError(f"sources-feed-error: commoncrawl search failed: {exc}") from exc

        records: list[Mapping[str, Any]] = []
        seen: set[str] = set()
        for hit in hits:
            url = hit.url.strip()
            if not url or url in seen:
                continue  # dedup by page URL within the pull (first wins)
            seen.add(url)
            try:
                page = metered(url, headers={"User-Agent": ua}, timeout=30.0)
                extraction = extract(page, url=url)
            except Exception:  # best-effort lead pull: one bad page is a skip, never a crash
                continue
            if not extraction.ok or not extraction.text:
                continue  # a page trafilatura could not turn into main text is no lead
            records.append(
                {
                    "url": url,
                    "text": extraction.text,
                    "title": extraction.title or "",
                    "date": extraction.date,  # a datetime.date or None (never a wall-clock date)
                    "locator": hit.locator or "",
                }
            )
        return records

    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """One extracted page → one INFERRED `Fact`: `subject` = `commoncrawl:<url>` (a stable page
        coordinate + dedup key), `claim` = a BOUNDED excerpt of the extracted clean text, one
        `url-fragment` anchor (the page URL), `as_of` = the extracted date or None. Open web =
        INFERRED lead, ALWAYS. DEDUP BY URL (first wins); a text-less record is skipped."""
        seen: set[str] = set()
        facts: list[Fact] = []
        for rec in raw:
            url = str(rec.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            claim = _excerpt(str(rec.get("text") or ""))
            if not claim:
                continue  # a Fact needs a non-empty claim; a text-less page is not a lead
            facts.append(
                Fact(
                    subject=f"commoncrawl:{url}",
                    claim=claim,
                    # INFERRED, ALWAYS: an open-web page is a LEAD to verify, never EXTRACTED
                    # (EXTRACTED is reserved for a characterized primary — EDGAR-class).
                    tier=TIER_INFERRED,
                    anchors=(Anchor("url-fragment", url),),
                    as_of=rec.get("date"),
                )
            )
        return facts


def _metered(http_get: HttpGet, meter: CostMeter) -> HttpGet:
    """Wrap the injected fetch seam so every call (the CDX index query + each page) accrues bytes +
    requests onto the run's `CostMeter` — the feed meters cost even though the backend does the
    fetching. Free-HTTP courtesy cost only; $0 model spend."""

    def _get(url: str, *, headers: Mapping[str, str], timeout: float = 30.0) -> bytes:
        payload = http_get(url, headers=headers, timeout=timeout)
        meter.record_response(payload)
        return payload

    return _get


def _excerpt(text: str) -> str:
    """A BOUNDED lead excerpt of the extracted main text: whitespace-collapsed and capped at
    `_MAX_CLAIM_CHARS`, truncated at a word boundary with an ellipsis when longer. Enough to be a
    useful lead, never the whole article (lead-only content is never republished)."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_CLAIM_CHARS:
        return collapsed
    cut = collapsed[:_MAX_CLAIM_CHARS].rsplit(" ", 1)[0].rstrip()
    return f"{cut or collapsed[:_MAX_CLAIM_CHARS].rstrip()}…"
