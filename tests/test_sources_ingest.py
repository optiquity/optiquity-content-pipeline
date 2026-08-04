"""Sources P2b-core: the acquisition skeleton + `sources ingest` + EDGAR — the first source that
ACTUALLY PUBLISHES (design §6; the acquire→cache→ground→publish path, end to end).

FIXTURES ONLY — the `http_get` fetch seam is injected, so NO test hits the live network (rule 1).
Content is SYNTHETIC-GENERIC (rule 4): an invented "Widget Systems Inc." filer, an invented CIK,
example.test-shaped anchors — no real/client filing content. Everything runs under `tmp_path`; the
real `users/` tree is never touched.

Coverage map (the P2b-core acceptance set):
  - PUBLISH     ingest an EDGAR fixture → sealed slice → cache source (regulatory-filing) → an
                EXTRACTED + attribution fact PUBLISHES (publishable AND republishable → published).
  - HONESTY     an uncharacterized web-ish fact (INFERRED) is WITHHELD as a lead — never published.
  - temporality `archival` rides the §15 grounding ledger for the published EDGAR fact, and is NOT
                a §6.2 score (absent from m3.SCORES / ASSERTABLE_SCORES / the scores_snapshot).
  - θ / dedup   the θ stop rule halts at budget; duplicate filings collapse; a re-ingest is a no-op.
  - Tier-A      pipeline/sources/* references NO paid path; the CLI ingest command mints no job.
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest

from pipeline.adapters import default_adapters
from pipeline.adapters.base import (
    TIER_EXTRACTED,
    TIER_INFERRED,
    Anchor,
    Fact,
)
from pipeline.compose import build_grounding_ledger
from pipeline.grounding import ASSERTABLE_SCORES, SourceInstance, ground_item
from pipeline.m1 import Resolver
from pipeline.m3 import SCORES, resolve_selection
from pipeline.sources.acquire import DEFAULT_MAX_FACTS, FeedConfig, FeedError, ingest_feed
from pipeline.sources.cache import namespace_dir, read_head, seal_slice
from pipeline.sources.control import (
    STOP_BUDGET,
    STOP_DRAINED,
    Budget,
    CostMeter,
    select_novel,
)
from pipeline.sources.feeds import feed_for, feed_kinds
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.date(2026, 7, 16)
UA = "Optiquity Test Harness (test@example.test)"
CIK = "0000012345"

# --- Synthetic EDGAR submissions fixtures (rule 4: invented filer, no client content) ------------

_8K = {
    "accession": "0000012345-24-000001",
    "form": "8-K",
    "filing_date": "2024-05-01",
    "primary_document": "widget-8k.htm",
    "primary_desc": "Current report of a widget product recall",
}
_10Q = {
    "accession": "0000012345-24-000002",
    "form": "10-Q",
    "filing_date": "2024-06-15",
    "primary_document": "widget-10q.htm",
    "primary_desc": "Quarterly report",
}
_8K_B = {
    "accession": "0000012345-24-000003",
    "form": "8-K",
    "filing_date": "2024-07-01",
    "primary_document": "widget-8k-b.htm",
    "primary_desc": "Current report of a leadership change",
}


def edgar_bytes(filings, *, company="Widget Systems Inc.", cik=CIK) -> bytes:
    """Build a `data.sec.gov` submissions JSON body (parallel arrays) from filing dicts."""
    recent = {
        "accessionNumber": [f["accession"] for f in filings],
        "form": [f["form"] for f in filings],
        "filingDate": [f["filing_date"] for f in filings],
        "primaryDocument": [f.get("primary_document", "") for f in filings],
        "primaryDocDescription": [f.get("primary_desc", "") for f in filings],
    }
    doc = {"cik": int(cik), "name": company, "filings": {"recent": recent}}
    return json.dumps(doc).encode("utf-8")


def make_http_get(payload: bytes, *, calls: list | None = None):
    """A fixture fetch seam: returns canned bytes + records (url, headers). NEVER hits network."""

    def _get(url, *, headers, timeout):
        if calls is not None:
            calls.append((url, dict(headers)))
        assert url.startswith("https://") and url.endswith(".json"), url
        assert headers.get("User-Agent"), "a UA header must ride the request (§3.3 config, not key)"
        return payload

    return _get


def edgar_feed_config(namespace, *, forms=("8-K",), budget=None) -> FeedConfig:
    return FeedConfig(
        source_id="x-edgar-widget",
        kind="edgar",
        namespace=namespace,
        content_kind="regulatory-filing",
        temporality="archival",
        budget=budget or Budget(max_facts=100),
        connection={"user_agent": UA, "cik": CIK, "forms": list(forms)},
    )


def regulatory_filing_kind_defaults() -> dict:
    """Resolve the REAL shipped `regulatory-filing` content-kind → its default score bundle (the
    same resolution `build_instance` performs). Proves the shipped entry drives reuse_rights."""
    kind = Resolver(REPO_ROOT).resolve("content-kinds", "regulatory-filing")
    defaults = kind.defaults()
    defaults.update(kind.effective)
    return defaults


# ---------------------------------------------------------------------------
# The shipped content-kind + feed registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_regulatory_filing_kind_resolves_to_attribution(self):
        defaults = regulatory_filing_kind_defaults()
        assert defaults["reuse_rights"] == "attribution"  # clears the publish threshold
        assert defaults["authoritative"] == 5  # a filing is the definitive record
        assert defaults["opinionated"] == 1

    def test_edgar_feed_is_registered(self):
        assert "edgar" in feed_kinds()
        assert feed_for("edgar").kind == "edgar"

    def test_unknown_feed_kind_is_loud(self):
        with pytest.raises(FeedError):
            feed_for("no-such-feed")


# ---------------------------------------------------------------------------
# THE PUBLISH MILESTONE — the headline: an EDGAR fact PUBLISHES end to end.
# ---------------------------------------------------------------------------


class TestPublishMilestone:
    def _ingest_and_bind(self, tmp_path, filings):
        store = WorkspaceStore(tmp_path / "ws")
        config = edgar_feed_config("edgar-widget")
        report = ingest_feed(config, store, http_get=make_http_get(edgar_bytes(filings)))
        ns_dir = namespace_dir(store, "edgar-widget")
        digest = read_head(ns_dir)
        inst = SourceInstance(
            id="x-edgar-cache",
            adapter="cache",
            connection={"path": str(ns_dir), "slice": digest, "temporality": "archival"},
            content_kind="regulatory-filing",
            kind_defaults=regulatory_filing_kind_defaults(),
        )
        outcome = ground_item(
            item="item-1",
            query="filed",
            pool=[inst],
            selection=resolve_selection(),
            adapters=default_adapters(),
            now=NOW,
        )
        return report, ns_dir, inst, outcome

    def test_extracted_attribution_fact_publishes(self, tmp_path):
        report, ns_dir, inst, outcome = self._ingest_and_bind(tmp_path, [_8K, _10Q])
        # only the 8-K survived the forms filter → one sealed EXTRACTED fact
        assert report.novel_cached == 1
        assert outcome.status == "ok"
        # the driver's publish set: EXTRACTED (publishable) AND republishable (§6.1 rights gate)
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert published, "an EXTRACTED + attribution EDGAR fact must PUBLISH"
        fact = published[0]
        assert fact.tier == TIER_EXTRACTED
        assert fact.publishable is True
        assert fact.reuse_rights == "attribution"
        assert fact.republishable is True
        assert "8-K" in fact.claim  # the verbatim filing field rode into the claim
        assert fact.anchors[0].kind == "url-fragment"
        assert fact.as_of == datetime.date(2024, 5, 1)

    def test_temporality_archival_rides_the_grounding_ledger(self, tmp_path):
        _report, _ns, inst, outcome = self._ingest_and_bind(tmp_path, [_8K])
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert published and published[0].temporality == "archival"
        ledger, _entries = build_grounding_ledger(
            published, source_repos={inst.id: "edgar-widget-cache"}
        )
        entry = next(iter(ledger.values()))
        # temporality is §15 ledger PROVENANCE (like attestation) — omit-when-absent, here present
        assert entry["temporality"] == "archival"
        # …and it is NOT a §6.2 score: never in the selection grammar nor the scores snapshot
        assert "temporality" not in entry["scores_snapshot"]
        assert "temporality" not in SCORES
        assert "temporality" not in ASSERTABLE_SCORES

    def test_uncharacterized_web_fact_is_withheld_as_a_lead(self, tmp_path):
        # What an UNCHARACTERIZED web feed would emit: INFERRED, never EXTRACTED. It grounds as a
        # LEAD to verify, never a published fact (§6.5) — the tier-honesty rule.
        store = WorkspaceStore(tmp_path / "ws")
        ns_dir = namespace_dir(store, "web-scrape")
        digest = seal_slice(
            ns_dir,
            [
                Fact(
                    subject="widget-market.share",
                    claim="A blog post claims Widget Systems holds 40% market share.",
                    tier=TIER_INFERRED,
                    anchors=(Anchor("url-fragment", "https://example.test/blog#share"),),
                    as_of=datetime.date(2024, 3, 1),
                )
            ],
        )
        inst = SourceInstance(
            id="x-web",
            adapter="cache",
            connection={"path": str(ns_dir), "slice": digest},
            content_kind="general",  # floors reuse_rights to `full`, but the TIER is INFERRED
        )
        outcome = ground_item(
            item="item-web",
            query="widget",
            pool=[inst],
            selection=resolve_selection(),
            adapters=default_adapters(),
            now=NOW,
        )
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert not published, "an INFERRED web fact must never publish"
        assert outcome.leads and outcome.leads[0].tier == TIER_INFERRED


# ---------------------------------------------------------------------------
# θ stop rule + dedup + idempotency (control.py + the sealed cache)
# ---------------------------------------------------------------------------


class TestControlAndIdempotency:
    def test_theta_stop_halts_at_budget(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = edgar_feed_config("edgar-cap", budget=Budget(max_facts=1))
        report = ingest_feed(
            config, store, http_get=make_http_get(edgar_bytes([_8K, _8K_B]))
        )
        assert report.novel_cached == 1  # capped
        assert report.stop_reason == STOP_BUDGET  # a further novel filing remained

    def test_duplicate_filings_collapse(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = edgar_feed_config("edgar-dup")
        # the same filing twice in one pull → one novel fact, one duplicate
        report = ingest_feed(config, store, http_get=make_http_get(edgar_bytes([_8K, _8K])))
        assert report.novel_cached == 1
        assert report.duplicates == 1
        assert report.stop_reason == STOP_DRAINED

    def test_reingest_of_unchanged_content_is_a_noop(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        config = edgar_feed_config("edgar-idem")
        payload = edgar_bytes([_8K, _8K_B])  # both are 8-K → both survive the filter
        first = ingest_feed(config, store, http_get=make_http_get(payload))
        assert first.novel_cached == 2 and first.head_advanced is True
        second = ingest_feed(config, store, http_get=make_http_get(payload))
        assert second.novel_cached == 0  # everything already cached
        assert second.duplicates == 2
        assert second.head_advanced is False  # the content-addressed seal is the no-op
        assert second.digest == first.digest  # same fact set → same digest → HEAD unmoved

    def test_select_novel_theta_below_threshold(self):
        # A trailing window of all-duplicates drops the novelty rate below θ → STOP_THETA.
        from pipeline.sources.control import STOP_THETA

        facts = ["a", "b", "dup", "dup"]
        outcome = select_novel(
            facts,
            budget=Budget(max_facts=100, theta=0.6, window=2),
            seen_ids={"dup"},
            stable_id=lambda f: f,
        )
        assert outcome.stop_reason == STOP_THETA

    def test_cost_meter_accrues_bytes_and_requests(self):
        meter = CostMeter()
        meter.record_response(b"hello")
        meter.record_response(b"world!")
        assert meter.requests == 2 and meter.bytes == 11

    def test_budget_default_is_the_shipped_cap(self):
        assert Budget(max_facts=DEFAULT_MAX_FACTS).max_facts == DEFAULT_MAX_FACTS


# ---------------------------------------------------------------------------
# EDGAR is HOST-PINNED — the EXTRACTED-honesty invariant is code, not convention.
# ---------------------------------------------------------------------------


class TestHostPinning:
    def test_off_host_base_url_is_refused_loud(self, tmp_path):
        # An arbitrary `base_url` would let `kind: edgar` + EDGAR-shaped JSON stamp EXTRACTED on
        # non-EDGAR content (also SSRF) — the feed refuses it LOUDLY, before any fetch.
        store = WorkspaceStore(tmp_path / "ws")
        config = FeedConfig(
            source_id="x-edgar-evil",
            kind="edgar",
            namespace="edgar-evil",
            content_kind="regulatory-filing",
            temporality="archival",
            connection={"user_agent": UA, "cik": CIK, "base_url": "https://evil.test"},
        )
        with pytest.raises(FeedError, match="HOST-PINNED"):
            ingest_feed(config, store, http_get=make_http_get(edgar_bytes([_8K])))

    def test_fetch_targets_the_sec_submissions_host(self, tmp_path):
        # The EXTRACTED path still works — and can ONLY reach the SEC host (self-verifying in code).
        store = WorkspaceStore(tmp_path / "ws")
        calls: list = []
        report = ingest_feed(
            edgar_feed_config("edgar-host"),
            store,
            http_get=make_http_get(edgar_bytes([_8K]), calls=calls),
        )
        assert report.novel_cached == 1  # the real-host EXTRACTED path still publishes
        assert calls, "the fetch must have run"
        url = calls[0][0]
        assert url.startswith("https://data.sec.gov/submissions/CIK")
