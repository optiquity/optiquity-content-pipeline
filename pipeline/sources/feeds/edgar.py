"""The SEC EDGAR feed (sources P2) — the first non-code source that ACTUALLY PUBLISHES.

EDGAR is a CHARACTERIZED PRIMARY, public-domain source: the authoritative first-party record a
filer submits to the SEC. That characterization is what earns the **EXTRACTED** tier HONESTLY (the
`regulatory-filing` content-kind: `authoritative: 5`, `reuse_rights: attribution`) — so an EDGAR
fact both `publishable` (tier) AND `republishable` (rights) and PUBLISHES as fact. The EXTRACTED
tier is stamped ONLY for this class of source here; uncharacterized web content is never EXTRACTED.

Keyless + read-only (rule 1): the filings submissions JSON at `data.sec.gov` needs no credential —
only a declared User-Agent string (config, NOT a secret; §3.3 permits a UA). SEC asks a ~10 req/s
courtesy; one ingest is a single GET. The `http_get` fetch seam is injected, so tests feed canned
JSON and no test touches the live network.
"""

from __future__ import annotations

import datetime
import json
from collections.abc import Mapping, Sequence
from typing import Any

from pipeline.adapters.base import TIER_EXTRACTED, Anchor, Fact
from pipeline.sources.acquire import Feed, FeedConfig, FeedError, HttpGet
from pipeline.sources.control import CostMeter

__all__ = ["EdgarFeed"]

#: The EDGAR submissions host — the per-filer JSON index of recent filings (keyless, public-domain).
#: HOST-PINNED (not configurable): `kind: edgar` may ONLY ever fetch SEC, so the EXTRACTED
#: characterization is self-verifying by code — an arbitrary `base_url` could point EDGAR-shaped
#: JSON at a non-EDGAR host and stamp EXTRACTED on uncharacterized content (also an SSRF override).
_SUBMISSIONS_HOST = "https://data.sec.gov"

#: The Archives host where a filing's primary document / index actually lives (the anchor URL).
#: Host-pinned for the same reason (the anchor must resolve to a real SEC filing).
_ARCHIVES_HOST = "https://www.sec.gov"


class EdgarFeed(Feed):
    """`kind: edgar` — fetch a filer's recent filings from `data.sec.gov` submissions JSON."""

    kind = "edgar"

    def fetch(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter
    ) -> list[Mapping[str, Any]]:
        """GET `data.sec.gov/submissions/CIK##########.json` and split its parallel arrays into
        per-filing records. Read-only; the User-Agent rides from config (a UA is not a secret,
        §3.3). The fetch is HOST-PINNED to SEC — no `base_url` override — so `kind: edgar` can only
        ever fetch EDGAR, making the EXTRACTED characterization self-verifying by code."""
        conn = config.connection
        if "base_url" in conn:
            # The EXTRACTED-honesty invariant is code, not convention: an off-host override would
            # let `kind: edgar` stamp EXTRACTED on non-EDGAR content (also SSRF). Refuse it.
            raise FeedError(
                "sources-feed-error: the edgar feed is HOST-PINNED to SEC "
                f"({_SUBMISSIONS_HOST} / {_ARCHIVES_HOST}); a `base_url` override is not honored "
                "(it would let `kind: edgar` stamp EXTRACTED on non-EDGAR content) — remove it"
            )
        user_agent = conn.get("user_agent")
        if not isinstance(user_agent, str) or not user_agent.strip():
            raise FeedError(
                "sources-feed-error: edgar feed requires a `user_agent` string in connection "
                "(SEC courtesy identifier — config, not a secret, §3.3)"
            )
        cik = conn.get("cik")
        if not (isinstance(cik, str | int)) or not str(cik).strip().isdigit():
            raise FeedError(
                f"sources-feed-error: edgar feed needs a numeric `cik` in connection, got {cik!r}"
            )
        cik10 = str(cik).strip().zfill(10)
        url = f"{_SUBMISSIONS_HOST}/submissions/CIK{cik10}.json"
        payload = http_get(url, headers={"User-Agent": user_agent}, timeout=30.0)
        meter.record_response(payload)
        try:
            doc = json.loads(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FeedError(
                f"sources-feed-error: edgar submissions for CIK{cik10} is not valid JSON: {exc}"
            ) from exc
        return self._records(doc, cik10)

    @staticmethod
    def _records(doc: Any, cik10: str) -> list[Mapping[str, Any]]:
        """The `filings.recent` parallel arrays → one dict per filing (verbatim fields only)."""
        if not isinstance(doc, Mapping):
            raise FeedError("sources-feed-error: edgar submissions body must be a JSON object")
        recent = doc.get("filings", {})
        recent = recent.get("recent", {}) if isinstance(recent, Mapping) else {}
        if not isinstance(recent, Mapping):
            raise FeedError(
                "sources-feed-error: edgar submissions `filings.recent` must be an object"
            )
        company = str(doc.get("name", "") or "")
        accession = recent.get("accessionNumber", []) or []
        form = recent.get("form", []) or []
        filing_date = recent.get("filingDate", []) or []
        primary_document = recent.get("primaryDocument", []) or []
        primary_desc = recent.get("primaryDocDescription", []) or []
        records: list[Mapping[str, Any]] = []
        for i in range(len(accession)):
            records.append(
                {
                    "cik10": cik10,
                    "company": company,
                    "accession": str(accession[i]),
                    "form": str(form[i]) if i < len(form) else "",
                    "filing_date": str(filing_date[i]) if i < len(filing_date) else "",
                    "primary_document": (
                        str(primary_document[i]) if i < len(primary_document) else ""
                    ),
                    "primary_desc": str(primary_desc[i]) if i < len(primary_desc) else "",
                }
            )
        return records

    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """One filing → one EXTRACTED `Fact`: a stable filing coordinate `subject`, a claim built
        from VERBATIM filing fields, one `url-fragment` anchor (the filing URL), and the filing date
        as `as_of`. A `forms` connection filter keeps only the named forms (empty = all)."""
        forms_filter = {str(f) for f in (config.connection.get("forms") or [])}
        facts: list[Fact] = []
        for rec in raw:
            form = rec.get("form", "")
            if forms_filter and form not in forms_filter:
                continue
            accession = rec.get("accession", "")
            if not accession:
                continue
            cik10 = rec.get("cik10", "")
            company = rec.get("company", "") or f"CIK {cik10}"
            filing_date = rec.get("filing_date", "")
            desc = rec.get("primary_desc") or rec.get("primary_document") or form
            subject = f"edgar:CIK{cik10}:{accession}"
            claim = (
                f"{company} filed a {form} on {filing_date} with the SEC "
                f"(accession {accession}): {desc}."
            )
            facts.append(
                Fact(
                    subject=subject,
                    claim=claim,
                    # EXTRACTED is stamped ONLY for this characterized primary + authoritative
                    # first-party class (a regulatory filing) — never for uncharacterized content.
                    tier=TIER_EXTRACTED,
                    anchors=(Anchor("url-fragment", self._filing_url(rec)),),
                    as_of=self._as_of(filing_date),
                )
            )
        return facts

    @staticmethod
    def _filing_url(rec: Mapping[str, Any]) -> str:
        """The public EDGAR Archives URL for the filing's primary document (or its index)."""
        cik10 = str(rec.get("cik10", "0"))
        cik_int = str(int(cik10)) if cik10.isdigit() else cik10
        accession = str(rec.get("accession", ""))
        acc_nodash = accession.replace("-", "")
        primary = str(rec.get("primary_document", ""))
        base = f"{_ARCHIVES_HOST}/Archives/edgar/data/{cik_int}/{acc_nodash}"
        return f"{base}/{primary}" if primary else f"{base}/{accession}-index.htm"

    @staticmethod
    def _as_of(filing_date: str) -> datetime.date | None:
        """The filing date as a BARE date (§6.2 date-granular freshness); `None` if unparseable."""
        try:
            return datetime.date.fromisoformat(filing_date)
        except (ValueError, TypeError):
            return None
