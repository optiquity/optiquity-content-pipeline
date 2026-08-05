"""The trafilatura main-text + publication-date extractor (sources P3a) — a DETERMINISTIC primitive.

The research-side counterpart to the feed `normalize` step: given the RAW BYTES of a web page, pull
its clean MAIN TEXT (article body, boilerplate stripped) and, when the page carries one, its
PUBLICATION DATE — the two things a Common-Crawl LEAD needs to become an INFERRED `Fact`.

**Fed BYTES, never a URL (rule 1).** The extractor is a pure transform over bytes: it calls only
trafilatura's in-memory `bare_extraction` and NEVER a fetch primitive, so extraction can never
touch the network. The caller (the Common Crawl feed) does the READ-ONLY fetch through the injected
`http_get` seam and hands the bytes here. A `url` may ride along as a METADATA HINT (it sharpens
trafilatura's date/host metadata) — it is passed as the document's origin, never fetched.

**Failure is SOFT.** trafilatura returns `None` for an empty/malformed/text-less page; this wrapper
maps that (and any extractor exception) to an `Extraction(ok=False)` with empty text — it NEVER
raises. A feed treats a non-ok extraction as "nothing to acquire here" (skip/annotate), so one bad
page never aborts a whole pull.

**Determinism (idempotency backstop).** trafilatura's cross-call `deduplicate` cache is left OFF
(the default), so extracting the SAME bytes twice yields the SAME text — a precondition for the
content-addressed seal to treat a re-ingest of unchanged content as a no-op.

**`date` → the Fact `as_of`, or `None`.** trafilatura yields a bare `YYYY-MM-DD` string; this parses
it to a `datetime.date`. When the page carries NO date, `date` is `None` — NEVER `today()`
(a wall-clock date would poison the deterministic seal: the digest would change every day). This
mirrors the P2b feeds' `_as_of` discipline (rss/gdelt).

Tier is NOT set here — the extractor is tier-agnostic. The open web is an INFERRED LEAD (never
EXTRACTED — that tier is reserved for a characterized primary, EDGAR-class); the FEED stamps
INFERRED when it turns an `Extraction` into a `Fact`.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

import trafilatura

__all__ = ["Extraction", "extract"]


@dataclass(frozen=True)
class Extraction:
    """One page's extracted content: clean main `text`, an optional publication `date`, an optional
    `title`, and an `ok` flag (False = trafilatura recovered no usable main text — a soft skip).

    `date` is a BARE date or `None` (§6.2 date-granular freshness; never a timestamp, never a
    wall-clock fallback). `text` is the empty string when `ok` is False, so a caller can branch on
    `ok` OR on a truthy `text` interchangeably.
    """

    text: str
    date: datetime.date | None = None
    title: str | None = None
    ok: bool = True


def extract(html_bytes: bytes | str, url: str | None = None) -> Extraction:
    """Extract clean main text + publication date from page BYTES via trafilatura.

    `html_bytes` is the RAW page payload (bytes preferred; a str is tolerated) the caller already
    fetched through its injected `http_get` — this function performs NO fetch and never touches the
    network (rule 1). `url` is an OPTIONAL metadata hint (origin for trafilatura's date/host
    heuristics); it is NEVER fetched. Returns an `Extraction`; on empty/malformed/text-less input or
    any extractor error, returns `Extraction(ok=False, text="")` — it NEVER raises (soft failure).
    """
    if not html_bytes:
        return Extraction(text="", date=None, ok=False)
    try:
        # bare_extraction is a pure in-memory transform: it parses the given bytes only. No fetch
        # helper is passed, so it cannot reach the network. `deduplicate` stays OFF (the default) so
        # the SAME bytes always extract to the SAME text — the content-addressed-seal precondition.
        doc: Any = trafilatura.bare_extraction(
            html_bytes,
            url=url,
            with_metadata=True,
            include_comments=False,
            include_tables=False,
        )
    except Exception:  # SOFT by contract: ANY extractor failure is a skip, never a crash (rule)
        return Extraction(text="", date=None, ok=False)
    if doc is None:
        return Extraction(text="", date=None, ok=False)
    text = (_field(doc, "text") or "").strip()
    date = _as_of(_field(doc, "date"))
    title = (_field(doc, "title") or "").strip() or None
    if not text:
        # Metadata may still have parsed (a date/title) but with no main text there is no lead.
        return Extraction(text="", date=date, title=title, ok=False)
    return Extraction(text=text, date=date, title=title, ok=True)


def _field(doc: Any, name: str) -> Any:
    """Read a field off trafilatura's result whether it is a `Document` object or a plain dict."""
    if isinstance(doc, dict):
        return doc.get(name)
    return getattr(doc, name, None)


def _as_of(value: Any) -> datetime.date | None:
    """A trafilatura date (`YYYY-MM-DD` string, or a `date`) as a BARE date; `None` when absent or
    unparseable — NEVER a wall-clock `today()` (that would make the sealed slice non-deterministic
    and break content-addressed idempotency, exactly as the rss/gdelt `_as_of` guards against)."""
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()[:10]
    try:
        return datetime.date.fromisoformat(text)
    except (ValueError, TypeError):
        return None
