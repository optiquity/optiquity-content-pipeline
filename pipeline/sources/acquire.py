"""The acquisition SKELETON (sources P2): fetch → normalize → dedup + θ-gate → SEAL → publish HEAD.

The out-of-band, Tier-A ingest body the P1 sealed-cache core (`pipeline.sources.cache`) was built to
receive. It fetches FREE HTTP and writes the LOCAL sealed cache under the owning workspace
(`users/<user>/workspaces/<ws>/sources/cache/<namespace>/` — the CLAUDE.md rule-1 carve-out:
gitignored, never committed, read-only toward every upstream source). It NEVER touches the paid job
path: no paid transport layer, no paid-drive flag, no session, no external-actor door, $0 model
spend. The `http_get` fetch seam is INJECTABLE so tests pass a fixture fn and NEVER hit the network.

The pipeline, per feed (`ingest_feed`):

  1. `feed.fetch(config, http_get=…, meter=…)`  → raw records (the source-fetcher seam + cost meter)
  2. `feed.normalize(config, raw)`              → list[Fact]  (tier-stamped, anchored, dated)
  3. `control.select_novel(...)`               → dedup + θ stop rule
  4. `seal_slice` + `publish_head` UNDER the §22.3 namespace lease (`cache.CacheNamespaceLock`)

**Idempotency.** A re-ingest of unchanged content re-normalizes to the SAME facts, which dedup
against the current HEAD's facts (admit zero) and RETAIN-ALL re-seals the SAME fact set → the SAME
content-addressed digest → the seal is the already-materialized no-op and HEAD never moves. A
conditional-GET hook belongs to the feed; the content-addressed seal is the backstop that makes an
unchanged pull a no-op even without one.

The FEED CODE is framework (`pipeline.sources.feeds`). A FEED INSTANCE — a per-workspace descriptor
naming a `kind` + connection + namespace — is client/instance DATA and lives under the workspace at
`sources/feeds/<id>.yaml` (never a shipped framework entry; §10 rule 4). The DRIVER's grounding pool
globs `sources/*.md` (non-recursive), so a feed descriptor in `sources/feeds/` is invisible to
grounding — the CACHE-reader source (`adapter: cache`) is the grounding face of an acquired feed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pipeline.adapters.base import Fact, temporality_ok
from pipeline.sources.cache import (
    CacheNamespaceLock,
    fact_to_record,
    namespace_dir,
    publish_head,
    read_head,
    read_slice,
    seal_slice,
    stable_fact_id,
)
from pipeline.sources.control import Budget, CostMeter, NoveltyOutcome, select_novel

__all__ = [
    "DEFAULT_MAX_FACTS",
    "Feed",
    "FeedConfig",
    "FeedError",
    "HttpGet",
    "IngestReport",
    "default_http_get",
    "ingest_feed",
    "ingest_workspace",
]

#: The default θ cost budget when a feed descriptor sets none — a conservative per-run novel-fact
#: cap (a feed pull is free HTTP, so this only bounds one ingest's cache growth, never spend).
DEFAULT_MAX_FACTS = 500

#: The fetch seam: `http_get(url, *, headers, timeout) -> bytes`. The CLI binds `default_http_get`
#: (real urllib); tests bind a fixture fn returning canned bytes — so no test hits the network.
HttpGet = Callable[..., bytes]


class FeedError(RuntimeError):
    """A feed-side acquisition failure — an unknown feed kind, a malformed descriptor/connection, a
    non-JSON body, or a busy namespace. Loud, typed, never a silent partial acquire."""

    code = "sources-feed-error"


def default_http_get(url: str, *, headers: Mapping[str, str], timeout: float = 30.0) -> bytes:
    """The production fetch seam: an HTTPS GET returning the response body bytes.

    Read-only toward the source (rule 1) and keyless — the ONLY credential-shaped input is a
    declared User-Agent header, which §3.3 permits (a UA is config, not a secret). Restricted to
    `https` (an `http`/`file`/other scheme is refused) so a mistyped descriptor can never read a
    local file or an unencrypted endpoint. This is the SOLE live-network path; it is never reached
    under test (the fixture `http_get` is injected)."""
    import urllib.request

    scheme = urlsplit(url).scheme
    if scheme != "https":
        raise FeedError(
            f"sources-feed-error: a feed fetch must be an https URL (keyless, read-only), "
            f"got scheme {scheme!r} in {url!r}"
        )
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — https-only, guarded above
        return response.read()


@dataclass(frozen=True)
class FeedConfig:
    """One resolved feed descriptor: WHAT to acquire and HOW to characterize + home it.

    `source_id` names the descriptor; `kind` selects the framework feed code (`edgar`); `namespace`
    is the sealed-cache namespace to seal into; `content_kind`/`temporality` are the
    characterization the acquisition RECORDS (the grounding-side values ride the cache-reader source
    entry + its `temporality` connection key, kept consistent by the workspace author). `budget` is
    the θ stop rule; `connection` is the feed-specific bound config (a UA, a CIK, forms — never a
    secret, §3.3).
    """

    source_id: str
    kind: str
    namespace: str
    content_kind: str = "general"
    temporality: str | None = None
    budget: Budget = field(default_factory=lambda: Budget(max_facts=DEFAULT_MAX_FACTS))
    connection: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for label, value in (
            ("source_id", self.source_id),
            ("kind", self.kind),
            ("namespace", self.namespace),
            ("content_kind", self.content_kind),
        ):
            if not isinstance(value, str) or not value.strip():
                raise FeedError(
                    f"sources-feed-error: feed {label} must be a non-empty string, got {value!r}"
                )
        if not temporality_ok(self.temporality):
            raise FeedError(
                f"sources-feed-error: feed temporality must be None or a known token "
                f"(§6.1 slice provenance), got {self.temporality!r}"
            )
        if not isinstance(self.budget, Budget):
            raise FeedError(
                f"sources-feed-error: feed budget must be a control.Budget, got {self.budget!r}"
            )
        if not isinstance(self.connection, Mapping):
            raise FeedError(
                f"sources-feed-error: feed connection must be a mapping, got {self.connection!r}"
            )

    @classmethod
    def from_mapping(cls, source_id: str, data: Mapping[str, Any]) -> FeedConfig:
        """Build a validated `FeedConfig` from a parsed descriptor mapping (`sources/feeds/<id>`
        YAML). A `budget:` sub-map becomes a `control.Budget`; an absent one takes the default."""
        if not isinstance(data, Mapping):
            raise FeedError(
                f"sources-feed-error: feed descriptor {source_id!r} must be a mapping, got "
                f"{type(data).__name__}"
            )
        raw_budget = data.get("budget")
        if raw_budget is None:
            budget = Budget(max_facts=DEFAULT_MAX_FACTS)
        elif isinstance(raw_budget, Mapping):
            budget = Budget(
                max_facts=int(raw_budget.get("max_facts", DEFAULT_MAX_FACTS)),
                theta=float(raw_budget.get("theta", 0.0)),
                window=int(raw_budget.get("window", 20)),
            )
        else:
            raise FeedError(
                f"sources-feed-error: feed {source_id!r} budget must be a map "
                f"{{max_facts, theta?, window?}}, got {raw_budget!r}"
            )
        return cls(
            source_id=source_id,
            kind=str(data.get("kind", "")),
            namespace=str(data.get("namespace", "")),
            content_kind=str(data.get("content_kind", "general")),
            temporality=data.get("temporality"),
            budget=budget,
            connection=data.get("connection", {}),
        )


class Feed(ABC):
    """The source-fetcher CONTRACT (§6.1 acquisition side): a named, READ-ONLY acquisition provider.

    Subclasses set `kind` (the descriptor's `kind:` token) and implement the two-step seam:
    `fetch` (source → raw records, via the injected `http_get` + the cost `meter`) and `normalize`
    (raw records → tier-stamped `Fact`s). The contract exposes NO write primitive toward the source
    (rule 1). Neither method may spend paid quota — acquisition is free HTTP, $0 model spend.
    """

    kind: ClassVar[str] = ""

    @abstractmethod
    def fetch(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter
    ) -> list[Mapping[str, Any]]:
        """Read the source READ-ONLY via `http_get`, metering cost; return raw per-item records."""

    @abstractmethod
    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """Turn raw records into tier-stamped `Fact`s (subject/claim/tier/anchors/as_of)."""


@dataclass(frozen=True)
class IngestReport:
    """One feed ingest's summary (the operator's Tier-A spend/coverage view — no paid quota)."""

    source_id: str
    kind: str
    namespace: str
    content_kind: str
    temporality: str | None
    fetched: int
    novel_cached: int
    duplicates: int
    stop_reason: str
    bytes: int
    requests: int
    digest: str
    head_advanced: bool

    def summary_lines(self) -> list[str]:
        """The printable per-feed summary block."""
        state = "HEAD advanced" if self.head_advanced else "HEAD unchanged (idempotent no-op)"
        return [
            f"feed {self.source_id!r} ({self.kind}) → namespace {self.namespace!r}",
            f"  content-kind : {self.content_kind}  temporality: {self.temporality or '(none)'}",
            f"  facts        : {self.novel_cached} newly cached, {self.duplicates} duplicate(s), "
            f"{self.fetched} fetched",
            f"  θ-stop       : {self.stop_reason}",
            f"  cost         : {self.bytes} bytes over {self.requests} request(s), $0 model spend",
            f"  slice        : {self.digest[:16]}… ({state})",
        ]


def ingest_feed(
    config: FeedConfig,
    store: Any,
    *,
    http_get: HttpGet,
    registry: Any | None = None,
) -> IngestReport:
    """Run ONE feed's ingest pipeline and seal into its namespace; return the summary.

    RETAIN-ALL (§22.7): the sealed slice accumulates the prior HEAD's facts plus this run's admitted
    novel facts, so grounding never loses an earlier acquisition. Content-addressed idempotency: an
    unchanged pull re-seals the SAME fact set → the SAME digest → the no-op. The seal + HEAD advance
    run UNDER the §22.3 namespace lease so a concurrent HEAD-mode reader never tears.
    """
    from pipeline.sources.feeds import feed_for  # lazy: avoids an acquire↔feeds import cycle

    feed = feed_for(config.kind)
    ns_dir = namespace_dir(store, config.namespace)
    if registry is None:
        from pipeline.spine import registry_for  # lazy: the workspace claims table (§22.3)

        registry = registry_for(store)
    lock = CacheNamespaceLock(registry, config.namespace)
    acquired = lock.acquire()
    if not acquired.acquired:
        raise FeedError(
            f"sources-feed-error: cache namespace {config.namespace!r} is busy "
            f"(lease {acquired.code}) — another ingest holds it; retry once it releases"
        )
    try:
        prior_digest = read_head(ns_dir)
        existing = read_slice(ns_dir, prior_digest) if prior_digest is not None else ()
        seen: set[str] = {stable_fact_id(fact_to_record(f)) for f in existing}
        meter = CostMeter()
        raw = feed.fetch(config, http_get=http_get, meter=meter)
        facts = feed.normalize(config, raw)
        outcome: NoveltyOutcome = select_novel(
            facts,
            budget=config.budget,
            seen_ids=seen,
            stable_id=lambda f: stable_fact_id(fact_to_record(f)),
        )
        sealed = tuple(existing) + outcome.kept
        digest = seal_slice(ns_dir, sealed)  # content-addressed; a no-op when unchanged
        publish_head(ns_dir, digest)  # atomic HEAD advance under the lease
    finally:
        lock.release()
    return IngestReport(
        source_id=config.source_id,
        kind=config.kind,
        namespace=config.namespace,
        content_kind=config.content_kind,
        temporality=config.temporality,
        fetched=outcome.fetched,
        novel_cached=len(outcome.kept),
        duplicates=outcome.duplicates,
        stop_reason=outcome.stop_reason,
        bytes=meter.bytes,
        requests=meter.requests,
        digest=digest,
        head_advanced=(digest != prior_digest),
    )


def _feeds_dir(store: Any) -> Path:
    """The workspace feed-descriptor home: `<workspace>/sources/feeds/` (instance data, §10)."""
    return Path(store.root) / "sources" / "feeds"


def ingest_workspace(
    store: Any, *, source: str | None = None, http_get: HttpGet
) -> list[IngestReport]:
    """Resolve the workspace's feed descriptor(s) and ingest each; return the reports in id order.

    Reads `sources/feeds/*.yaml` DIRECTLY (never the M1 grounding registry), so feed descriptors
    never enter the grounding pool. `--source <id>` restricts to one descriptor; absent = all.
    """
    from pipeline.yamlio import load_yaml

    feeds_dir = _feeds_dir(store)
    if not feeds_dir.is_dir():
        return []
    paths = sorted(feeds_dir.glob("*.yaml"))
    if source is not None:
        paths = [p for p in paths if p.stem == source]
        if not paths:
            raise FeedError(
                f"sources-feed-error: no feed descriptor {source!r} under {feeds_dir} "
                "(expected sources/feeds/<source>.yaml)"
            )
    reports: list[IngestReport] = []
    for path in paths:
        try:
            data = load_yaml(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FeedError(
                f"sources-feed-error: cannot read feed descriptor {path}: {exc}"
            ) from exc
        config = FeedConfig.from_mapping(path.stem, data)
        reports.append(ingest_feed(config, store, http_get=http_get))
    return reports
