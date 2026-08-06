"""The agentic RESEARCH feed (sources P3b) — the FINAL, money-safety-critical lead source.

Where the P2/P3a feeds are FREE (bytes/requests only, $0 model spend), this feed SPENDS subscription
LLM tokens to RESEARCH a question: **plan → search → fetch/extract → synthesize → corroborate →
gap-find → repeat, θ-stop.** Its output is INFERRED leads + a corroboration signal, cached for later
GROUNDING — the open web is a LEAD to verify, **NEVER EXTRACTED, never published** (that tier is
reserved for a characterized primary, EDGAR-class; §6.5 tier-honesty). The `web-article` content
kind pins `reuse_rights: lead-only`, so a research fact is DOUBLY withheld: neither true-enough
(INFERRED) nor allowed (lead-only) to publish.

**Money-safety is by construction (§21.9):**

- **Injected `llm_call` seam.** Every planning / synthesis / gap-find call rides an injectable
  ``llm_call(prompt, *, budget) -> str`` seam. The CLI binds the DEFAULT (the subscription transport
  chokepoint — headless `claude -p`, no API key, a per-call `--max-budget-usd` cap) only behind the
  paid gate; tests inject a FAKE returning canned plans/syntheses, so NO test makes a real model
  call or hits the network (search/fetch use the P3a injected `http_get`). This module imports NO
  transport and knows nothing about the gate — it only calls the seam it is handed.
- **A HARD CEILING** (`ResearchBudget.ceiling_usd`), the TRUE worst-case TOTAL: `per_call_usd × (1
  plan + max_rounds×fan_out syntheses + (max_rounds−1) gap-finds)`. EVERY call — plan, synthesis,
  gap-find — is `per_call_usd`-capped, and the loop issues at most `fan_out` syntheses per round
  across at most `max_rounds` rounds (a gap-find only BETWEEN rounds), so its TOTAL spend CANNOT
  exceed the disclosed ceiling — the number the paid gate approves is never undershot by a real run.
  The synthesis-only sub-ceiling (`max_rounds × fan_out × per_call_usd`) is reported alongside.
- **The θ stop-rule** (`ResearchControl`): when a round's novel-fact yield PER DOLLAR stays below θ
  for `k` rounds, the loop halts on diminishing returns — usually well under the ceiling.

**Anchored synthesis (no free-floating facts).** A candidate claim becomes a `Fact` ONLY when it is
tied to a fetched + extracted page: the synthesis prompt is the page's own text, and each emitted
fact carries that page's URL as a `url-fragment` anchor. A page that supports nothing yields no
fact. The claim's `subject` is a STABLE claim coordinate (a hash of the normalized claim), so the
SAME claim seen on DIFFERENT pages shares a subject with DISTINCT origins (anchors) — a
corroboration signal the resolver's §6.5 arithmetic can count. Corroboration is a RANKING/benefit
signal only: it NEVER raises the tier (independence cannot be machine-faked; open web stays
INFERRED).

**Reuse, never re-implement.** Search rides the P3a `backend_for` (`commoncrawl` default; `searxng`
is the deferred live seam), extraction the P3a trafilatura `extract`, budget/θ the extended
`control`, and sealing the P2 content-addressed cache under the §22.3 namespace lease.
`run_research` threads the paid `llm_call` into that same seal path — the paid loop does NOT ride
the free
`ingest_feed` conduit (which passes no seam and would be a silent-spend hazard), it reuses the same
cache/control PRIMITIVES with the spend accounting inline.

**Temporality.** `snapshot` for a Common Crawl-backed run (a reproducible monthly capture); `live`
for the deferred SearXNG backend. That slice provenance rides the cache-reader connection onto the
§15 ledger; it is never a §6.2 score and never a fact-identity input.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from pipeline.adapters.base import TIER_INFERRED, Anchor, Fact
from pipeline.canonical import sha256_hex
from pipeline.sources.acquire import Feed, FeedConfig, FeedError, HttpGet
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
from pipeline.sources.control import (
    STOP_CEILING,
    STOP_DRAINED,
    CostMeter,
    ResearchBudget,
    ResearchControl,
    select_novel,
)
from pipeline.sources.extract import extract
from pipeline.sources.search import SearchError, backend_for

__all__ = [
    "LlmCall",
    "ResearchFeed",
    "ResearchLoopResult",
    "ResearchReport",
    "run_research",
]

#: The injectable LLM seam: ``llm_call(prompt, *, budget) -> str`` (returns the model's text, which
#: the loop parses as JSON). The CLI binds the real subscription-transport invocation; tests bind a
#: fake. The loop NEVER constructs the real call itself — it only invokes what it is handed.
LlmCall = Callable[..., str]

#: A default User-Agent for the free HTTP search/fetch (courtesy config, §3.3; never a secret).
_DEFAULT_UA = "optiquity-content-pipeline (research reader; +https://github.com/optiquity)"

#: A default per-sub-query capture cap when the descriptor sets none (a lead pull, not a bulk dump).
_DEFAULT_LIMIT = 10

#: The synthesized claim carries a BOUNDED excerpt — enough to be a useful lead, never the whole
#: article (lead-only content is never republished).
_MAX_CLAIM_CHARS = 600

#: Cap the page text handed to the synthesis prompt (bounds the prompt; the lead is an excerpt).
_MAX_PAGE_CHARS = 6000

#: Cap the claims-so-far list echoed into the gap-find prompt (keeps the prompt bounded).
_MAX_GAP_CLAIMS = 40

#: Stable task markers at the head of each prompt — the seam contract a fake keys on (and a stable
#: label in the real prompt). Never user data.
_TASK_PLAN = "TASK: research-plan"
_TASK_SYNTH = "TASK: research-synthesize"
_TASK_GAP = "TASK: research-gapfind"


# ---------------------------------------------------------------------------
# Prompt builders (the seam's request side) + tolerant JSON parsers (its response side).
# ---------------------------------------------------------------------------


def _plan_prompt(question: str, fan_out: int) -> str:
    return (
        f"{_TASK_PLAN}\n"
        "You are a research planner. Decompose the QUESTION into focused, independent web-search "
        f"sub-queries — at most {fan_out}. Each is a short search phrase that would surface pages "
        "answering part of the question.\n"
        'Return ONLY a JSON array of strings, e.g. ["sub query one", "sub query two"].\n\n'
        f"QUESTION: {question}\n"
    )


def _synth_prompt(sub_query: str, page_text: str, url: str) -> str:
    return (
        f"{_TASK_SYNTH}\n"
        "You are a careful research analyst. From the PAGE TEXT below extract 0 or more factual "
        "claims that (a) help answer the SUB-QUERY and (b) are DIRECTLY GROUNDED in this page's "
        "text. If the page supports no such claim, return an empty array. NEVER invent a claim the "
        "page does not state — an unsupported page yields nothing.\n"
        'Return ONLY a JSON array of claim strings, e.g. ["claim one", "claim two"].\n\n'
        f"SUB-QUERY: {sub_query}\n"
        f"PAGE URL: {url}\n"
        f"PAGE TEXT:\n{page_text[:_MAX_PAGE_CHARS]}\n"
    )


def _gapfind_prompt(question: str, claims: Sequence[str], fan_out: int) -> str:
    known = "; ".join(claims[:_MAX_GAP_CLAIMS]) or "(none gathered yet)"
    return (
        f"{_TASK_GAP}\n"
        "You are a research gap-finder. Given the QUESTION and the CLAIMS gathered so far, list "
        f"the most valuable MISSING angles as at most {fan_out} new web-search sub-queries. Return "
        "EMPTY array if the question is already well covered.\n"
        "Return ONLY a JSON array of strings.\n\n"
        f"QUESTION: {question}\n"
        f"CLAIMS SO FAR: {known}\n"
    )


def _parse_json(text: Any) -> Any:
    """Tolerant JSON parse of a model's text: exact `json.loads` first, else the first balanced
    array/object span pulled out of surrounding prose. A seam that already returns a parsed
    object/list is passed through. `None` on nothing parseable (a soft empty, never a crash)."""
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i = stripped.find(open_c)
        j = stripped.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(stripped[i : j + 1])
            except (ValueError, TypeError):
                continue
    return None


def _parse_query_list(text: Any) -> list[str]:
    """A plan / gap-find response → a list of non-empty sub-query strings (a bare array or a
    `{sub_queries|queries|subqueries: [...]}` wrapper)."""
    data = _parse_json(text)
    if isinstance(data, Mapping):
        data = data.get("sub_queries") or data.get("queries") or data.get("subqueries")
    if not isinstance(data, list):
        return []
    return [item.strip() for item in data if isinstance(item, str) and item.strip()]


def _parse_claims(text: Any) -> list[str]:
    """A synthesis response → a list of supported claim strings (bare strings, or
    `{claim, supported?}` objects — an explicit `supported: false` drops the claim)."""
    data = _parse_json(text)
    if isinstance(data, Mapping):
        data = data.get("claims")
    if not isinstance(data, list):
        return []
    out: list[str] = []
    for item in data:
        if isinstance(item, str):
            claim = item.strip()
            if claim:
                out.append(claim)
        elif isinstance(item, Mapping):
            claim = str(item.get("claim") or "").strip()
            if claim and item.get("supported", True):
                out.append(claim)
    return out


# ---------------------------------------------------------------------------
# Small shared helpers (fetch metering, claim excerpt, the stable claim coordinate).
# ---------------------------------------------------------------------------


def _metered(http_get: HttpGet, meter: CostMeter) -> HttpGet:
    """Wrap the injected fetch seam so every search/page fetch accrues bytes + requests onto the
    run's `CostMeter` (free-HTTP courtesy cost; the model spend is metered separately as call
    count × per_call_usd)."""

    def _get(url: str, *, headers: Mapping[str, str], timeout: float = 30.0) -> bytes:
        payload = http_get(url, headers=headers, timeout=timeout)
        meter.record_response(payload)
        return payload

    return _get


def _excerpt(text: str) -> str:
    """A BOUNDED lead excerpt of a synthesized claim: whitespace-collapsed and capped at
    `_MAX_CLAIM_CHARS`, truncated at a word boundary with an ellipsis when longer."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _MAX_CLAIM_CHARS:
        return collapsed
    cut = collapsed[:_MAX_CLAIM_CHARS].rsplit(" ", 1)[0].rstrip()
    return f"{cut or collapsed[:_MAX_CLAIM_CHARS].rstrip()}…"


def _subject_for(claim: str) -> str:
    """A STABLE claim coordinate `research:<sha16 of the normalized claim>`. Identical claims from
    DIFFERENT pages share it, so the §6.5 corroboration arithmetic can group them (distinct
    `url-fragment` anchors keep the origins distinct); a re-run of the same claim re-derives it."""
    normalized = " ".join(claim.split()).lower()
    return f"research:{sha256_hex(normalized.encode('utf-8'))[:16]}"


# ---------------------------------------------------------------------------
# The loop result + the operator's spend report.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResearchLoopResult:
    """One research loop's output: the synthesized raw records + the spend/stop accounting."""

    records: tuple[dict[str, Any], ...]
    stop_reason: str
    rounds: int
    synth_calls: int  # page-synthesis LLM calls — bounded by the sub-ceiling (≤ max_rounds×fan_out)
    overhead_calls: int  # plan + gap-find LLM calls — the bounded per-round overhead
    synth_ceiling_usd: float  # the synthesis-only sub-ceiling (max_rounds × fan_out × per_call_usd)
    total_ceiling_usd: float  # the TRUE worst-case TOTAL ceiling (plan + syntheses + gap-finds)
    per_call_usd: float

    @property
    def llm_calls(self) -> int:
        return self.synth_calls + self.overhead_calls

    @property
    def synth_spend_usd(self) -> float:
        """Worst-case synthesis spend (calls × per_call cap) — provably ≤ `synth_ceiling_usd`."""
        return self.synth_calls * self.per_call_usd

    @property
    def total_spend_usd(self) -> float:
        """Worst-case total spend (plan + synthesis + gap-find) — provably ≤ `total_ceiling_usd`."""
        return self.llm_calls * self.per_call_usd


@dataclass(frozen=True)
class ResearchReport:
    """One research ingest's summary — the operator's PAID spend/coverage view (honest disclosure:
    total spend ≤ the TRUE total ceiling; the synthesis sub-ceiling is surfaced alongside)."""

    source_id: str
    namespace: str
    question: str
    backend: str
    temporality: str | None
    stop_reason: str
    rounds: int
    synth_calls: int
    overhead_calls: int
    total_spend_usd: float
    synth_spend_usd: float
    synth_ceiling_usd: float
    total_ceiling_usd: float
    leads_found: int
    novel_cached: int
    duplicates: int
    bytes: int
    requests: int
    digest: str
    head_advanced: bool

    @property
    def llm_calls(self) -> int:
        return self.synth_calls + self.overhead_calls

    def summary_lines(self) -> list[str]:
        """The printable per-research summary block."""
        state = "HEAD advanced" if self.head_advanced else "HEAD unchanged (idempotent no-op)"
        return [
            f"research {self.source_id!r} (research) → namespace {self.namespace!r}",
            f"  question     : {self.question}",
            f"  backend      : {self.backend}  temporality: {self.temporality or '(none)'}",
            f"  leads        : {self.novel_cached} newly cached, {self.duplicates} duplicate(s), "
            f"{self.leads_found} synthesized — INFERRED, lead-only (never published)",
            f"  θ-stop       : {self.stop_reason} after {self.rounds} round(s)",
            f"  spend        : ~${self.total_spend_usd:.2f} of ≤ ${self.total_ceiling_usd:.2f} "
            f"ceiling over {self.llm_calls} subscription LLM call(s) — {self.synth_calls} synth "
            f"(~${self.synth_spend_usd:.2f} of ≤ ${self.synth_ceiling_usd:.2f}) + "
            f"{self.overhead_calls} plan/gap-find",
            f"  fetch        : {self.bytes} bytes over {self.requests} request(s) (free HTTP)",
            f"  slice        : {self.digest[:16]}… ({state})",
        ]


# ---------------------------------------------------------------------------
# The research feed — a `Feed` whose loop SPENDS (via the injected seam) into INFERRED leads.
# ---------------------------------------------------------------------------


class ResearchFeed(Feed):
    """`kind: research` — the agentic loop over the P3a search/extract primitives + an injected LLM
    seam, yielding INFERRED leads. `spends = True` marks it PAID (the CLI's transport-aware gate);
    the FREE `ingest_feed` conduit passes no seam, so routing a research source through it refuses
    LOUDLY rather than spending or crashing silently."""

    kind = "research"
    spends: ClassVar[bool] = True

    def fetch(
        self,
        config: FeedConfig,
        *,
        http_get: HttpGet,
        meter: CostMeter,
        llm_call: LlmCall | None = None,
    ) -> list[Mapping[str, Any]]:
        """The `Feed` contract entry. It REFUSES without an injected `llm_call` (the paid seam),
        so the research loop can never run through the free ingest path silently — it runs only via
        `run_research`, which threads the seam the CLI binds behind the paid gate."""
        if llm_call is None:
            raise FeedError(
                "sources-feed-error: the research feed is a PAID loop — it requires an injected "
                "llm_call seam (the subscription transport, bound by the CLI behind the paid "
                "gate). It never runs through the free ingest path; drive it via run_research"
            )
        loop = self.run_loop(config, http_get=http_get, meter=meter, llm_call=llm_call)
        return list(loop.records)

    def run_loop(
        self, config: FeedConfig, *, http_get: HttpGet, meter: CostMeter, llm_call: LlmCall
    ) -> ResearchLoopResult:
        """Run the agentic loop: plan → (search → fetch → extract → synthesize)×fan-out → gap-find,
        halting on θ, the ceiling (`max_rounds`), or a source-drain. Returns the raw records + the
        spend/stop accounting. Every model call rides `llm_call` capped at `per_call_usd`; every
        fetch rides the metered injected `http_get`."""
        conn = config.connection
        question = conn.get("question")
        if not isinstance(question, str) or not question.strip():
            raise FeedError(
                "sources-feed-error: the research feed requires a `question` string in connection"
            )
        question = question.strip()
        backend_name = (str(conn.get("backend") or "commoncrawl").strip()) or "commoncrawl"
        budget = ResearchBudget.from_mapping(conn.get("budget"))
        ua = conn.get("user_agent")
        ua = ua if isinstance(ua, str) and ua.strip() else _DEFAULT_UA

        metered = _metered(http_get, meter)
        try:
            backend = backend_for(backend_name)
        except SearchError as exc:
            raise FeedError(
                f"sources-feed-error: research backend {backend_name!r} unavailable: {exc}"
            ) from exc
        search_opts = self._search_opts(backend_name, conn, ua)

        control = ResearchControl(budget)
        records: list[dict[str, Any]] = []
        claim_texts: list[str] = []
        seen_subjects: set[str] = set()
        seen_origins: set[tuple[str, str]] = set()
        synth_calls = 0
        overhead_calls = 0

        # PLAN (LLM): decompose the question into ≤ fan_out sub-queries.
        queries = _parse_query_list(
            llm_call(_plan_prompt(question, budget.fan_out), budget=budget.per_call_usd)
        )[: budget.fan_out]
        overhead_calls += 1

        stop = STOP_DRAINED
        rounds = 0
        for round_index in range(budget.max_rounds):
            if not queries:
                stop = STOP_DRAINED  # the planner/gap-finder proposed nothing more to search
                break
            rounds += 1
            round_novel = 0
            round_synth = 0
            for sub_query in queries[: budget.fan_out]:
                page = self._first_page(backend, sub_query, metered, search_opts, ua)
                if page is None:
                    continue
                url, extraction = page
                # SYNTHESIZE (LLM): the page's OWN text → 0+ claims, each anchored to this page.
                claims = _parse_claims(
                    llm_call(
                        _synth_prompt(sub_query, extraction.text, url),
                        budget=budget.per_call_usd,
                    )
                )
                synth_calls += 1
                round_synth += 1
                for raw_claim in claims:
                    claim = _excerpt(raw_claim)
                    if not claim:
                        continue
                    subject = _subject_for(claim)
                    origin = (subject, url)
                    if origin in seen_origins:
                        continue  # same claim, same page — one origin record
                    seen_origins.add(origin)
                    records.append(
                        {"subject": subject, "claim": claim, "url": url, "date": extraction.date}
                    )
                    claim_texts.append(claim)
                    if subject not in seen_subjects:
                        seen_subjects.add(subject)
                        round_novel += 1  # a NEW claim (corroborating origins are not novel-for-θ)
            # θ-stop: marginal novel-fact yield per dollar below θ for k consecutive rounds.
            round_cost = round_synth * float(budget.per_call_usd)
            theta_stop = control.round_stop(novel=round_novel, round_cost_usd=round_cost)
            if theta_stop is not None:
                stop = theta_stop
                break
            if round_index == budget.max_rounds - 1:
                stop = STOP_CEILING  # the hard round ceiling — no further rounds are permitted
                break
            # GAP-FIND (LLM): what is missing → next round's ≤ fan_out sub-queries.
            queries = _parse_query_list(
                llm_call(
                    _gapfind_prompt(question, claim_texts, budget.fan_out),
                    budget=budget.per_call_usd,
                )
            )[: budget.fan_out]
            overhead_calls += 1

        return ResearchLoopResult(
            records=tuple(records),
            stop_reason=stop,
            rounds=rounds,
            synth_calls=synth_calls,
            overhead_calls=overhead_calls,
            synth_ceiling_usd=budget.synth_ceiling_usd,
            total_ceiling_usd=budget.ceiling_usd,
            per_call_usd=float(budget.per_call_usd),
        )

    def normalize(self, config: FeedConfig, raw: Sequence[Mapping[str, Any]]) -> list[Fact]:
        """One synthesized record → one INFERRED `Fact`: `subject` = the stable claim coordinate,
        `claim` = the anchored assertion, one `url-fragment` anchor (the origin page), `as_of` = the
        extracted date or None. Open web = INFERRED lead, ALWAYS (never EXTRACTED). DISTINCT origins
        (same claim, different page) are RETAINED as distinct facts — the corroboration signal."""
        facts: list[Fact] = []
        seen: set[tuple[str, str]] = set()
        for rec in raw:
            subject = str(rec.get("subject") or "").strip()
            claim = str(rec.get("claim") or "").strip()
            url = str(rec.get("url") or "").strip()
            if not subject or not claim or not url:
                continue
            key = (subject, url)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                Fact(
                    subject=subject,
                    claim=claim,
                    # INFERRED, ALWAYS: an open-web page is a LEAD to verify, never EXTRACTED.
                    tier=TIER_INFERRED,
                    anchors=(Anchor("url-fragment", url),),
                    as_of=rec.get("date"),
                )
            )
        return facts

    def _search_opts(
        self, backend_name: str, conn: Mapping[str, Any], ua: str
    ) -> dict[str, Any]:
        """The backend-specific search kwargs. `commoncrawl` requires a pinned `index` (reproducible
        snapshot); a non-commoncrawl backend (e.g. the deferred `searxng` live seam) takes the base
        `search(query, *, http_get)` signature."""
        if backend_name != "commoncrawl":
            return {}
        index = conn.get("index")
        if not isinstance(index, str) or not index.strip():
            raise FeedError(
                "sources-feed-error: the research feed with the commoncrawl backend requires an "
                "`index` crawl id in connection (e.g. 'CC-MAIN-2024-51') — the exact monthly "
                "snapshot to search (reproducible; never guessed)"
            )
        opts: dict[str, Any] = {"index": index.strip(), "user_agent": ua}
        limit = conn.get("limit", _DEFAULT_LIMIT)
        if limit is not None:
            opts["limit"] = limit  # the backend validates it (positive int)
        return opts

    def _first_page(
        self,
        backend: Any,
        sub_query: str,
        metered: HttpGet,
        search_opts: Mapping[str, Any],
        ua: str,
    ) -> tuple[str, Any] | None:
        """Search `sub_query`, then fetch + extract hits in order, returning the FIRST page that
        yields usable main text — one synthesis per sub-query, bounding spend to fan_out/round. A
        single unfetchable/unextractable page is SOFT (skipped); `None` when nothing is usable."""
        try:
            hits = backend.search(sub_query, http_get=metered, **dict(search_opts))
        except SearchError as exc:
            raise FeedError(f"sources-feed-error: research search failed: {exc}") from exc
        for hit in hits:
            url = hit.url.strip()
            if not url:
                continue
            try:
                page = metered(url, headers={"User-Agent": ua}, timeout=30.0)
                extraction = extract(page, url=url)
            except Exception:  # best-effort lead pull: one bad page is a skip, never a crash
                continue
            if extraction.ok and extraction.text:
                return url, extraction
        return None


# ---------------------------------------------------------------------------
# The paid ingest entry — reuses the P2 seal path under the §22.3 lease, threading the LLM seam.
# ---------------------------------------------------------------------------


def run_research(
    config: FeedConfig,
    store: Any,
    *,
    http_get: HttpGet,
    llm_call: LlmCall,
    registry: Any | None = None,
) -> ResearchReport:
    """Run ONE research source's loop and seal its INFERRED leads into the namespace; return the
    PAID summary. Mirrors `ingest_feed`'s lock → read HEAD → normalize → dedup + θ-gate → SEAL →
    publish HEAD structure (RETAIN-ALL, content-addressed idempotency, the §22.3 lease), but drives
    the loop through the injected `llm_call` seam. Refuses without a seam — the paid loop never runs
    seamless. The seal's `config.budget` (a control `Budget`) caps how many leads enter the slice;
    the loop's own `ResearchBudget` (under connection) caps the SPEND."""
    if llm_call is None:
        raise FeedError(
            "sources-feed-error: run_research requires an injected llm_call seam (the paid "
            "subscription transport) — refusing to run the research loop without it"
        )
    from pipeline.sources.feeds import feed_for  # lazy: avoids the feeds↔research import cycle

    feed = feed_for(config.kind)
    if not isinstance(feed, ResearchFeed):
        raise FeedError(
            f"sources-feed-error: run_research expected a research feed, got kind {config.kind!r}"
        )
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
        loop = feed.run_loop(config, http_get=http_get, meter=meter, llm_call=llm_call)
        facts = feed.normalize(config, loop.records)
        outcome = select_novel(
            facts,
            budget=config.budget,
            seen_ids=seen,
            stable_id=lambda f: stable_fact_id(fact_to_record(f)),
        )
        sealed = tuple(existing) + outcome.kept
        digest = seal_slice(ns_dir, sealed)  # content-addressed; RETAIN-ALL
        publish_head(ns_dir, digest)  # atomic HEAD advance under the lease
    finally:
        lock.release()
    conn = config.connection
    return ResearchReport(
        source_id=config.source_id,
        namespace=config.namespace,
        question=str(conn.get("question") or ""),
        backend=str(conn.get("backend") or "commoncrawl"),
        temporality=config.temporality,
        stop_reason=loop.stop_reason,
        rounds=loop.rounds,
        synth_calls=loop.synth_calls,
        overhead_calls=loop.overhead_calls,
        total_spend_usd=loop.total_spend_usd,
        synth_spend_usd=loop.synth_spend_usd,
        synth_ceiling_usd=loop.synth_ceiling_usd,
        total_ceiling_usd=loop.total_ceiling_usd,
        leads_found=len(facts),
        novel_cached=len(outcome.kept),
        duplicates=outcome.duplicates,
        bytes=meter.bytes,
        requests=meter.requests,
        digest=digest,
        head_advanced=(digest != prior_digest),
    )
