"""The FEEDS code registry (sources P2) — the one place the framework feed set is declared.

A FEED is framework CODE (a `pipeline.sources.acquire.Feed` subclass); a feed INSTANCE is
per-workspace client DATA (`sources/feeds/<id>.yaml`), never a shipped entry (§10 rule 4). Adding a
new feed kind is a one-file change here — the matrix rule applied to the acquisition axis. v1 ships
EDGAR (a characterized primary, public-domain source that PUBLISHES).

`feed_for(kind)` is the accessor the ingest body binds; an unknown kind fails LOUD (never a silent
skip). This module holds NO acquisition body itself — it only names the framework feeds.
"""

from __future__ import annotations

from pipeline.sources.acquire import Feed, FeedError
from pipeline.sources.feeds.edgar import EdgarFeed

__all__ = ["feed_for", "feed_kinds"]

#: The shipped feed set (kind → the stateless feed instance). A fresh module-level singleton per
#: kind is fine (feeds are stateless — cost/state ride the per-run `CostMeter`, never the feed).
_FEEDS: dict[str, Feed] = {EdgarFeed.kind: EdgarFeed()}


def feed_for(kind: str) -> Feed:
    """The framework feed for `kind`, or a LOUD `FeedError` naming the known kinds."""
    feed = _FEEDS.get(kind)
    if feed is None:
        raise FeedError(
            f"sources-feed-error: unknown feed kind {kind!r} — known feeds: "
            f"{', '.join(feed_kinds())} (add one in pipeline/sources/feeds/, §10 one-file rule)"
        )
    return feed


def feed_kinds() -> tuple[str, ...]:
    """The currently shipped feed kinds (discovery surface), sorted."""
    return tuple(sorted(_FEEDS))
