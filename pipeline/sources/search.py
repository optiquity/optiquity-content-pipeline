"""The pluggable SEARCH-BACKEND interface (sources P3a) — a DETERMINISTIC research primitive.

A search backend turns a QUERY (a domain / URL pattern, a phrase) into a list of `SearchHit`s (a
URL, an optional snippet, an optional stable locator). It is the "find candidate pages" half of the
free/Tier-A research primitives; `pipeline.sources.extract` is the "read a page" half. Everything
here is READ-ONLY toward the source and spends NOTHING (free HTTP, $0 model spend) — the PAID
agentic loop is a separate, later increment and lives nowhere near this module.

**Two registration slots (`backend_for`), mirroring the feed registry (`feed_for`):**

- **`commoncrawl`** — the v1 default. It queries the Common Crawl CDX/index for captures whose URL
  matches the query pattern and returns one hit per capture (the captured URL + a `filename@offset`
  WARC locator). It needs NO hosted service: Common Crawl is a reproducible MONTHLY snapshot,
  so a pinned crawl index gives the same hit set on every run. HOST-PINNED to the Common Crawl hosts
  (`index.commoncrawl.org` for the CDX API, `data.commoncrawl.org` for WARC data): an off-host
  override is refused LOUDLY (mirroring the EDGAR/GDELT feed host-pin — a backend that could be
  pointed anywhere is an SSRF door and would let non-CC results masquerade as CC captures).

- **`searxng`** — a DEFERRED, pluggable seam. SearXNG is the OPTIONAL LIVE backend: an operator who
  self-hosts a SearXNG instance can plug a concrete implementation in here to get live web search.
  It is intentionally a LOUD STUB (never a silent empty result), so a descriptor that names it fails
  with a clear "not implemented yet — Common Crawl is the no-service v1 default" message rather than
  quietly returning nothing.

The fetch seam is INJECTED (`http_get`), so a backend NEVER hits the network under test — a fixture
`http_get` returns canned index/page bytes. The production seam is `acquire.default_http_get`
(https-only, keyless, read-only).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from urllib.parse import quote, urlsplit

from pipeline.sources.acquire import HttpGet

__all__ = [
    "CommonCrawlBackend",
    "SearchBackend",
    "SearchError",
    "SearchHit",
    "SearxngBackend",
    "backend_for",
    "backend_names",
]

#: The Common Crawl CDX/index API host — the per-crawl capture index (keyless, public). HOST-PINNED.
_CC_INDEX_HOST = "https://index.commoncrawl.org"

#: The Common Crawl WARC DATA host — where a capture's raw bytes live (the future WARC-offset fetch,
#: deferred with the anchor-depth ordinal). Pinned into the allow-set for that later enhancement.
_CC_DATA_HOST = "https://data.commoncrawl.org"

#: The host allow-set the CDX backend host-pins against (netloc only). An off-host override is loud.
_CC_HOSTS = frozenset({"index.commoncrawl.org", "data.commoncrawl.org"})

#: A polite default User-Agent when the caller names none (courtesy config, §3.3 — not a secret).
_DEFAULT_UA = "optiquity-content-pipeline (common-crawl reader; +https://github.com/optiquity)"

#: A modest default capture cap for one CDX query, and a hard ceiling (a lead pull, not a dump).
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 1000


class SearchError(RuntimeError):
    """A search-backend failure — an unknown backend, an off-host override, a missing crawl index,
    or the DEFERRED SearXNG stub. Loud, typed, never a silent empty result."""

    code = "sources-search-error"


@dataclass(frozen=True)
class SearchHit:
    """One search result: a `url` plus an optional `snippet` and an optional stable `locator`.

    `locator` is a stable coordinate for the hit — for Common Crawl the `filename@offset+length`
    WARC address of the capture, which a later increment resolves to the exact snapshot bytes (the
    deferred WARC-offset anchor). `None` when the backend exposes no stable locator.
    """

    url: str
    snippet: str | None = None
    locator: str | None = None


class SearchBackend(ABC):
    """The search-backend CONTRACT: a named, READ-ONLY query provider (§6.1 acquisition side).

    Subclasses set `name` (the `backend:` token) and implement `search`. The contract exposes NO
    write primitive toward the source (rule 1) and spends no paid quota — search is free HTTP, $0
    model spend. Concrete backends MAY accept extra keyword options (a crawl `index`, a `limit`, a
    host override) with safe defaults; a base-signature caller is always valid.
    """

    name: ClassVar[str] = ""

    @abstractmethod
    def search(self, query: str, *, http_get: HttpGet) -> list[SearchHit]:
        """Return the hits for `query`, fetching READ-ONLY via the injected `http_get`."""


class CommonCrawlBackend(SearchBackend):
    """`backend: commoncrawl` — query the Common Crawl CDX/index for URL-pattern captures.

    HOST-PINNED to the Common Crawl hosts: the CDX query is built against `index.commoncrawl.org`,
    and an off-host `base_url` override is refused LOUDLY (SSRF + provenance guard). No hosted
    service is required — a pinned monthly crawl index is a reproducible snapshot, so the same query
    yields the same captures on every run.
    """

    name = "commoncrawl"

    def search(
        self,
        query: str,
        *,
        http_get: HttpGet,
        index: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        base_url: str | None = None,
        user_agent: str | None = None,
    ) -> list[SearchHit]:
        """Query the CDX index for `query` (a domain / URL pattern, e.g. `example.com/*`) and return
        one `SearchHit` per capture. `index` is the crawl id (`CC-MAIN-2024-51`) — REQUIRED, so the
        snapshot is explicit/reproducible, never guessed. `base_url` may only ever name a Common
        Crawl host; an off-host value is refused LOUDLY. Read-only + keyless."""
        if not isinstance(query, str) or not query.strip():
            raise SearchError(
                f"sources-search-error: commoncrawl search needs a non-empty URL pattern query, "
                f"got {query!r}"
            )
        if not isinstance(index, str) or not index.strip():
            raise SearchError(
                "sources-search-error: commoncrawl search needs an `index` crawl id "
                "(e.g. 'CC-MAIN-2024-51') — the exact monthly snapshot to query, never guessed"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise SearchError(
                f"sources-search-error: commoncrawl `limit` must be a positive integer "
                f"(<= {_MAX_LIMIT}), got {limit!r}"
            )
        host = self._pinned_host(base_url)
        ua = user_agent if isinstance(user_agent, str) and user_agent.strip() else _DEFAULT_UA
        url = (
            f"{host}/{index.strip()}-index"
            f"?url={quote(query.strip(), safe='')}"
            f"&output=json&limit={min(limit, _MAX_LIMIT)}"
        )
        payload = http_get(url, headers={"User-Agent": ua}, timeout=30.0)
        return self._parse(payload)

    @staticmethod
    def _pinned_host(base_url: str | None) -> str:
        """The Common Crawl host to query. `None` → the pinned CDX host. A provided `base_url` is
        accepted ONLY when it is https AND its netloc is a known Common Crawl host; anything else is
        refused LOUDLY (the EXTRACTED-honesty / anti-SSRF invariant, mirrored from EDGAR/GDELT)."""
        if base_url is None:
            return _CC_INDEX_HOST
        parts = urlsplit(base_url)
        if parts.scheme != "https" or parts.netloc not in _CC_HOSTS:
            raise SearchError(
                "sources-search-error: the commoncrawl backend is HOST-PINNED to Common Crawl "
                f"({_CC_INDEX_HOST} / {_CC_DATA_HOST}); an off-host `base_url` override "
                f"({base_url!r}) is not honored (it would let non-CC results masquerade as Common "
                "Crawl captures — also SSRF) — remove it"
            )
        return f"https://{parts.netloc}"

    @staticmethod
    def _parse(payload: bytes) -> list[SearchHit]:
        """The CDX `output=json` body is NEWLINE-DELIMITED JSON (one capture object per line). Parse
        each line into a `SearchHit` (the captured `url` + a `filename@offset+length` WARC locator).
        An empty body / a 'no captures' text line yields zero hits (soft — nothing matched, never an
        error); a single unparseable line is skipped, never fatal."""
        if not payload:
            return []
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for line in payload.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue  # a non-JSON line (e.g. a "no captures found" message) — skip softly
            if not isinstance(rec, dict):
                continue
            url = str(rec.get("url") or "").strip()
            if not url or url in seen:
                continue  # dedup captures by URL within one index response (first wins)
            seen.add(url)
            hits.append(SearchHit(url=url, snippet=None, locator=_warc_locator(rec)))
        return hits


class SearxngBackend(SearchBackend):
    """`backend: searxng` — the DEFERRED, pluggable LIVE search seam (a self-hosted SearXNG).

    A LOUD STUB by design: it never returns a silent empty result. SearXNG is the OPTIONAL live
    backend an operator self-hosts; Common Crawl is the no-service v1 default. A later increment (or
    the paid research loop) plugs a concrete implementation in here.
    """

    name = "searxng"

    def search(self, query: str, *, http_get: HttpGet) -> list[SearchHit]:
        raise SearchError(
            "sources-search-error: the 'searxng' search backend is a DEFERRED pluggable seam — not "
            "implemented in P3a. SearXNG is the OPTIONAL live backend (an operator self-hosts a "
            "SearXNG instance); Common Crawl (`backend: commoncrawl`) is the no-service default. "
            "Add a concrete SearxngBackend.search in pipeline/sources/search.py to enable it."
        )


def _warc_locator(rec: dict) -> str | None:
    """A stable Common Crawl WARC coordinate `filename@offset+length` for a CDX capture, or `None`
    when the record omits the fields. This is the carrier for the DEFERRED WARC-offset anchor (a
    later enhancement resolves it to the exact snapshot bytes; v1 fetches the live page URL)."""
    filename = str(rec.get("filename") or "").strip()
    if not filename:
        return None
    offset = str(rec.get("offset") or "").strip()
    length = str(rec.get("length") or "").strip()
    if offset and length:
        return f"{filename}@{offset}+{length}"
    return filename


#: The shipped search backends (name → the stateless backend singleton), mirroring the feed
#: registry. Adding a backend is a ONE-FILE change here (the matrix rule on the search axis).
#: v1: `commoncrawl` (the no-service default) + `searxng` (the deferred, loud-stub live seam).
_BACKENDS: dict[str, SearchBackend] = {
    CommonCrawlBackend.name: CommonCrawlBackend(),
    SearxngBackend.name: SearxngBackend(),
}


def backend_for(name: str) -> SearchBackend:
    """The search backend for `name`, or a LOUD `SearchError` naming the known backends."""
    backend = _BACKENDS.get(name)
    if backend is None:
        raise SearchError(
            f"sources-search-error: unknown search backend {name!r} — known backends: "
            f"{', '.join(backend_names())} (add one in pipeline/sources/search.py, §10 rule)"
        )
    return backend


def backend_names() -> Sequence[str]:
    """The currently shipped search-backend names (discovery surface), sorted."""
    return tuple(sorted(_BACKENDS))
