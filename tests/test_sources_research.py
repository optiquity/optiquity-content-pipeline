"""Sources P3b: the agentic RESEARCH loop — the FINAL, money-safety-critical lead source.

FIXTURES ONLY. The LLM seam is a FAKE (canned plans / syntheses / gap-finds) and the fetch seam is
the P3a injected `http_get`, so NO test makes a real model call or hits the live network (rule 1).
Content is SYNTHETIC-GENERIC (rule 4): invented example.test pages, no real/client content.
Everything runs under `tmp_path`; the real `users/` tree is never touched.

Money-safety is the load-bearing property here. The loop SPENDS subscription LLM tokens, so this
suite proves — with fixtures — that:
  - it is DRY-RUN by default (the fake LLM is never called; nothing cached; `acquire-scope` prints)
  - `--go` is the only spend path (the fake plan/synth/gap-find drive the loop; leads are cached)
  - open web stays INFERRED lead-only (WITHHELD from publish; never EXTRACTED)
  - synthesis is page-ANCHORED (a supporting page → a fact anchored to it; a barren page → nothing)
  - corroboration is a distinct-origin signal only (same claim, distinct anchors; tier stays same)
  - the θ stop-rule halts at saturation; the ceiling caps rounds at `max_rounds`
  - the real LLM path routes through the subscription transport and STRIPS `ANTHROPIC_API_KEY` (F10)
  - `begin-session` stays exit 3; feeds still ingest FREE (no `--go`).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from pipeline.__main__ import _cmd_sources, _transport_llm_call
from pipeline.adapters.base import TIER_INFERRED
from pipeline.sources.acquire import FeedConfig, FeedError, ingest_feed
from pipeline.sources.cache import namespace_dir, read_head, read_slice
from pipeline.sources.control import (
    STOP_CEILING,
    STOP_DRAINED,
    STOP_THETA,
    ControlError,
    ResearchBudget,
)
from pipeline.sources.feeds import feed_kinds, feed_spends
from pipeline.sources.feeds.research import ResearchFeed, run_research
from pipeline.store import WorkspaceStore
from pipeline.transport import ANTHROPIC_API_KEY_ENV, ApiKeyPresentError, ProcessOutcome

# Reuse the sibling suites' grounding + EDGAR helpers (the established cross-module test pattern).
from tests.test_sources_feeds import bind_and_ground, kind_defaults
from tests.test_sources_ingest import _8K, CIK, UA, edgar_bytes, make_http_get

INDEX = "CC-MAIN-2024-51"
CDX_HOST = "https://index.commoncrawl.org"
QUESTION = "What are the reliability issues with Widget 2.0?"


# --- Synthetic fixtures (rule 4: invented example.test content) -----------------------------------


def _page(title: str, body: str, *, date: str | None = None) -> bytes:
    meta = f'<meta property="article:published_time" content="{date}T12:00:00Z"/>' if date else ""
    return (
        f"<html><head><title>{title}</title>{meta}</head>"
        f"<body><article><h1>{title}</h1><p>{body}</p></article></body></html>"
    ).encode()


def _cdx_line(url: str) -> bytes:
    """One Common Crawl CDX `output=json` capture line naming `url` (verbatim-shaped fields)."""
    return json.dumps(
        {
            "urlkey": "test)/",
            "timestamp": "20241201120000",
            "url": url,
            "mime": "text/html",
            "status": "200",
            "digest": "SHA1TESTDIGEST",
            "length": "2048",
            "offset": "100",
            "filename": "crawl-data/CC-MAIN-2024-51/segments/seg/warc/x.warc.gz",
        }
    ).encode("utf-8")


def _decode_cdx_query(url: str) -> str:
    """Recover the sub-query a CDX request encodes in its `url=` param (the search phrase)."""
    values = parse_qs(urlsplit(url).query).get("url", [])
    return values[0] if values else ""


def make_research_get(query_to_page: dict[str, tuple[str, bytes]], *, calls: list | None = None):
    """A fixture fetch seam: a CDX request for sub-query Q → a single capture at Q's page URL; a
    page request → that page's fixture HTML. NEVER hits the network; asserts https + a UA header."""
    url_to_html = {page_url: html for (page_url, html) in query_to_page.values()}

    def _get(url, *, headers, timeout=30.0):
        if calls is not None:
            calls.append(url)
        assert url.startswith("https://"), url
        assert headers.get("User-Agent"), "a UA header must ride every request (§3.3 config)"
        if url.startswith(f"{CDX_HOST}/"):
            page = query_to_page.get(_decode_cdx_query(url))
            return _cdx_line(page[0]) if page is not None else b""
        return url_to_html.get(url, b"")

    return _get


def _prompt_field(prompt: str, label: str) -> str:
    for line in prompt.splitlines():
        if line.startswith(label):
            return line[len(label) :].strip()
    return ""


class FakeLlm:
    """The injected LLM seam under test: canned plan / synthesis / gap-find keyed on the prompt's
    stable TASK marker. It records every call (task + budget) so a test can assert the loop's spend
    routes through the seam — and that a DRY-RUN never calls it at all."""

    def __init__(
        self,
        *,
        plan: list[str],
        synth: dict[str, list[str]],
        gaps: list[list[str]] | None = None,
    ) -> None:
        self.plan = plan
        self.synth = synth
        self.gaps = list(gaps or [])
        self.calls: list[tuple[str, float]] = []
        self._gap_i = 0

    def __call__(self, prompt: str, *, budget: float) -> str:
        if "TASK: research-plan" in prompt:
            self.calls.append(("plan", budget))
            return json.dumps(self.plan)
        if "TASK: research-synthesize" in prompt:
            self.calls.append(("synth", budget))
            return json.dumps(self.synth.get(_prompt_field(prompt, "SUB-QUERY:"), []))
        if "TASK: research-gapfind" in prompt:
            self.calls.append(("gap", budget))
            nxt = self.gaps[self._gap_i] if self._gap_i < len(self.gaps) else []
            self._gap_i += 1
            return json.dumps(nxt)
        raise AssertionError(f"unexpected prompt task: {prompt[:40]!r}")


def research_config(
    namespace, *, source_id="x-research", budget=None, connection=None
) -> FeedConfig:
    conn = {"question": QUESTION, "backend": "commoncrawl", "index": INDEX, "user_agent": UA}
    if budget is not None:
        conn["budget"] = budget
    if connection:
        conn.update(connection)
    return FeedConfig(
        source_id=source_id,
        kind="research",
        namespace=namespace,
        content_kind="web-article",
        temporality="snapshot",
        connection=conn,
    )


def _budget(**over) -> dict:
    base = {"max_rounds": 3, "fan_out": 2, "per_call_usd": 0.5, "theta": 0.0, "k": 2}
    base.update(over)
    return base


def _make_research_ws(tmp_path, *, namespace="res-cli", budget=None, user="acme", ws="widgets"):
    feeds_dir = (
        tmp_path / "users" / user / "zones" / "default" / "workspaces" / ws / "sources" / "feeds"
    )
    feeds_dir.mkdir(parents=True, exist_ok=True)
    b = budget or _budget()
    lines = "\n".join(f"    {k}: {json.dumps(v)}" for k, v in b.items())
    (feeds_dir / "x-research.yaml").write_text(
        "kind: research\n"
        f"namespace: {namespace}\n"
        "content_kind: web-article\n"
        "temporality: snapshot\n"
        "connection:\n"
        f'  question: "{QUESTION}"\n'
        "  backend: commoncrawl\n"
        f"  index: {INDEX}\n"
        f'  user_agent: "{UA}"\n'
        "  budget:\n" + lines + "\n",
        encoding="utf-8",
    )
    return user, ws


# ---------------------------------------------------------------------------
# Registry — the research feed ships one-file and is marked PAID.
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_research_feed_registered_and_marked_paid(self):
        assert "research" in feed_kinds()
        assert feed_spends("research") is True
        assert ResearchFeed().spends is True

    def test_free_feeds_are_not_marked_paid(self):
        assert feed_spends("edgar") is False
        assert feed_spends("commoncrawl") is False
        assert feed_spends("rss") is False and feed_spends("gdelt") is False

    def test_web_article_kind_is_lead_only(self):
        # The research content-kind pins reuse_rights: lead-only → doubly withheld (tier + rights)
        assert kind_defaults("web-article")["reuse_rights"] == "lead-only"


class TestBudgetFromMapping:
    def test_range_violation_keeps_its_accurate_typed_message(self):
        # per_call_usd=0 is NUMERIC but non-positive → __post_init__ raises a typed ControlError
        # with the ACCURATE range message; from_mapping must NOT relabel it "non-numeric".
        with pytest.raises(ControlError, match="per_call_usd must be a positive dollar amount"):
            ResearchBudget.from_mapping({"per_call_usd": 0})

    def test_non_numeric_field_is_the_non_numeric_message(self):
        with pytest.raises(ControlError, match="non-numeric field"):
            ResearchBudget.from_mapping({"per_call_usd": "free"})

    def test_true_total_ceiling_covers_plan_and_gapfind(self):
        # ceiling_usd is the TRUE total: per_call × (1 plan + R×F synth + (R−1) gap-finds).
        budget = ResearchBudget.from_mapping(
            {"max_rounds": 4, "fan_out": 3, "per_call_usd": 0.5, "theta": 0.0, "k": 2}
        )
        assert budget.synth_ceiling_usd == pytest.approx(4 * 3 * 0.5)  # 6.00 (synthesis only)
        assert budget.ceiling_usd == pytest.approx((1 + 4 * 3 + 3) * 0.5)  # 8.00 (true total)
        assert budget.ceiling_usd > budget.synth_ceiling_usd  # the headline is the larger, true one
        assert "$8.00" in budget.acquire_scope()


# ---------------------------------------------------------------------------
# The loop under --go — INFERRED leads cached, WITHHELD from publish (never EXTRACTED).
# ---------------------------------------------------------------------------


class TestGoRunsLoop:
    def test_go_caches_inferred_leads_withheld_from_publish(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        q2p = {
            "q-overheat": (
                "https://a.example.test/overheat",
                _page("Overheating", "The Widget 2.0 battery can overheat.", date="2024-05-01"),
            ),
            "q-recall": (
                "https://b.example.test/recall",
                _page("Recall", "A voluntary Widget 2.0 recall was issued.", date="2024-05-02"),
            ),
        }
        fake = FakeLlm(
            plan=["q-overheat", "q-recall"],
            synth={
                "q-overheat": ["Widget 2.0 battery can overheat under sustained load"],
                "q-recall": ["A voluntary recall was issued for early Widget 2.0 units"],
            },
            gaps=[[]],
        )
        report = run_research(
            research_config("res-go", budget=_budget()),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        assert report.novel_cached == 2 and report.leads_found == 2
        assert [t for t, _ in fake.calls].count("plan") == 1  # the loop DID spend via the seam

        _inst, outcome = bind_and_ground(
            store, "res-go", content_kind="web-article", temporality="snapshot", query="widget"
        )
        published = tuple(f for f in outcome.publishable_facts if f.republishable)
        assert not published, "an INFERRED open-web lead must NEVER publish (tier gate)"
        assert outcome.leads and all(f.tier == TIER_INFERRED for f in outcome.leads)
        assert all(f.subject.startswith("research:") for f in outcome.leads)

    def test_every_llm_call_is_budget_capped(self, tmp_path):
        # Money-safety: EVERY seam call carries the per_call_usd cap (→ transport --max-budget-usd).
        store = WorkspaceStore(tmp_path / "ws")
        page = _page("A", "Widget fact one.", date="2024-05-01")
        q2p = {"q1": ("https://a.example.test/1", page)}
        fake = FakeLlm(plan=["q1"], synth={"q1": ["Widget fact one"]}, gaps=[[]])
        run_research(
            research_config("res-cap", budget=_budget(fan_out=1, per_call_usd=0.25)),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        assert fake.calls, "the loop must have spent through the seam"
        assert all(budget == 0.25 for _task, budget in fake.calls)


# ---------------------------------------------------------------------------
# Anchored synthesis — a supporting page → an anchored fact; a barren page → NO fact.
# ---------------------------------------------------------------------------


class TestAnchoredSynthesis:
    def test_supported_page_anchors_and_barren_page_yields_nothing(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        q2p = {
            "q-supported": (
                "https://p.example.test/support",
                _page("Support", "The device supports fast charging.", date="2024-05-01"),
            ),
            "q-empty": (
                "https://p.example.test/empty",
                _page("Empty", "Nothing relevant about the topic here.", date=None),
            ),
        }
        fake = FakeLlm(
            plan=["q-supported", "q-empty"],
            # the supporting page yields a grounded claim; the barren page yields NOTHING (no
            # hallucinated free-floating fact) — the loop trusts the empty array.
            synth={"q-supported": ["The device supports fast charging"], "q-empty": []},
            gaps=[[]],
        )
        run_research(
            research_config("res-anchor", budget=_budget(max_rounds=2)),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        ns_dir = namespace_dir(store, "res-anchor")
        facts = read_slice(ns_dir, read_head(ns_dir))
        assert len(facts) == 1, "only the supporting page becomes a fact"
        (fact,) = facts
        assert fact.tier == TIER_INFERRED
        assert fact.anchors[0].kind == "url-fragment"
        assert fact.anchors[0].value == "https://p.example.test/support"  # ANCHORED to the page
        assert "fast charging" in fact.claim


# ---------------------------------------------------------------------------
# Corroboration — distinct-origin signal only; tier stays INFERRED (independence can't be faked).
# ---------------------------------------------------------------------------


class TestCorroboration:
    def test_two_agreeing_origins_stay_distinct_and_inferred(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        claim = "Widget 2.0 ships with a two-year warranty"
        q2p = {
            "q-a": (
                "https://vendor-a.example.test/spec",
                _page("A", "Warranty details from vendor A.", date="2024-05-01"),
            ),
            "q-b": (
                "https://vendor-b.example.test/spec",
                _page("B", "Warranty details from vendor B.", date="2024-05-02"),
            ),
        }
        fake = FakeLlm(plan=["q-a", "q-b"], synth={"q-a": [claim], "q-b": [claim]})
        run_research(
            research_config("res-corrob", budget=_budget(max_rounds=1)),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        facts = read_slice(*_head(store, "res-corrob"))
        # two DISTINCT-origin facts: one claim coordinate (subject), one assertion, two anchors.
        assert len(facts) == 2
        assert len({f.subject for f in facts}) == 1  # same claim → same coordinate (groupable)
        assert len({f.claim for f in facts}) == 1
        assert {f.anchors[0].value for f in facts} == {
            "https://vendor-a.example.test/spec",
            "https://vendor-b.example.test/spec",
        }
        assert all(f.tier == TIER_INFERRED for f in facts)  # NO tier upgrade — web stays INFERRED


# ---------------------------------------------------------------------------
# θ-stop + ceiling — diminishing returns halt; the ceiling caps rounds at max_rounds.
# ---------------------------------------------------------------------------


class TestStopRules:
    def test_theta_halts_at_saturation(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        # round 1 yields 2 NEW claims; every later round re-surfaces the SAME claims (0 novel) →
        # yield-per-dollar falls below θ for k=2 consecutive rounds → STOP_THETA (under max_rounds).
        q2p = {
            f"q{i}": (f"https://s{i}.example.test/p", _page(f"P{i}", f"body {i}"))
            for i in range(1, 7)
        }
        fake = FakeLlm(
            plan=["q1", "q2"],
            synth={
                "q1": ["CLAIM ALPHA"],
                "q2": ["CLAIM BETA"],
                "q3": ["CLAIM ALPHA"],
                "q4": ["CLAIM BETA"],
                "q5": ["CLAIM ALPHA"],
                "q6": ["CLAIM BETA"],
            },
            gaps=[["q3", "q4"], ["q5", "q6"], ["q7", "q8"]],
        )
        report = run_research(
            research_config("res-theta", budget=_budget(max_rounds=6, fan_out=2, theta=1.0, k=2)),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        assert report.stop_reason == STOP_THETA
        assert report.rounds == 3  # round 1 (novel) + 2 barren rounds = the k-streak

    def test_ceiling_caps_rounds_when_never_saturating(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        # a fake that returns a FRESH claim every round (θ disabled) still stops at max_rounds; the
        # synthesis spend never exceeds the synthesis sub-ceiling (max_rounds × fan_out × per_call).
        q2p = {
            f"q{i}": (f"https://c{i}.example.test/p", _page(f"C{i}", f"body {i}"))
            for i in range(1, 5)
        }
        fake = FakeLlm(
            plan=["q1"],
            synth={"q1": ["FACT 1"], "q2": ["FACT 2"], "q3": ["FACT 3"], "q4": ["FACT 4"]},
            gaps=[["q2"], ["q3"], ["q4"]],
        )
        report = run_research(
            research_config("res-ceil", budget=_budget(max_rounds=3, fan_out=1, theta=0.0)),
            store,
            http_get=make_research_get(q2p),
            llm_call=fake,
        )
        assert report.stop_reason == STOP_CEILING
        assert report.rounds == 3  # exactly max_rounds
        assert report.synth_calls == 3  # ≤ max_rounds × fan_out
        # synthesis sub-ceiling holds (the dominant-cost bound), AND the TOTAL ceiling holds.
        assert report.synth_ceiling_usd == pytest.approx(3 * 1 * 0.5)
        assert report.synth_spend_usd <= report.synth_ceiling_usd + 1e-9
        assert report.total_ceiling_usd == pytest.approx((1 + 3 * 1 + 2) * 0.5)  # plan+synth+gap
        assert report.total_spend_usd <= report.total_ceiling_usd + 1e-9

    def test_disclosed_ceiling_is_never_undershot_by_a_real_run(self, tmp_path):
        # MONEY-SAFETY DISCLOSURE: the acquire-scope `≤ $C` a --go user approves must be ≥ the
        # ACTUAL maximum a run can spend across plan + synthesis + gap-find. Drive a fake that never
        # saturates (fresh claim every sub-query, θ disabled) to the worst case and assert the
        # disclosed total ceiling bounds the real total spend — and equals the true call budget.
        store = WorkspaceStore(tmp_path / "ws")
        rounds, fan, per_call = 3, 2, 0.75
        q2p = {
            f"q{i}": (f"https://d{i}.example.test/p", _page(f"D{i}", f"body {i}"))
            for i in range(1, 40)
        }
        # every sub-query yields a UNIQUE claim → maximal synthesis; gaps keep proposing fresh work.
        synth = {f"q{i}": [f"UNIQUE FACT {i}"] for i in range(1, 40)}
        gaps = [[f"q{2 * r}", f"q{2 * r + 1}"] for r in range(1, 12)]
        budget = _budget(max_rounds=rounds, fan_out=fan, per_call_usd=per_call, theta=0.0)
        report = run_research(
            research_config("res-nofloor", budget=budget),
            store,
            http_get=make_research_get(q2p),
            llm_call=FakeLlm(plan=["q1", "q2"], synth=synth, gaps=gaps),
        )
        expected_ceiling = (1 + rounds * fan + (rounds - 1)) * per_call  # plan + synth + gap-finds
        assert report.total_ceiling_usd == pytest.approx(expected_ceiling)
        # the DISCLOSED headline equals the ceiling and is ≥ the real worst-case total spend.
        assert f"${expected_ceiling:.2f}" in ResearchBudget.from_mapping(budget).acquire_scope()
        assert report.total_spend_usd <= report.total_ceiling_usd + 1e-9
        assert report.llm_calls <= 1 + rounds * fan + (rounds - 1)  # never exceeds the call budget

    def test_drained_when_planner_proposes_nothing(self, tmp_path):
        store = WorkspaceStore(tmp_path / "ws")
        fake = FakeLlm(plan=[], synth={})  # the planner returns no sub-queries
        report = run_research(
            research_config("res-drain", budget=_budget()),
            store,
            http_get=make_research_get({}),
            llm_call=fake,
        )
        assert report.stop_reason == STOP_DRAINED
        assert report.rounds == 0 and report.novel_cached == 0


# ---------------------------------------------------------------------------
# Money-safety: dry-run spends nothing; --go is the only spend path (CLI).
# ---------------------------------------------------------------------------


def _cli_get():
    q2p = {
        "q-overheat": (
            "https://a.example.test/overheat",
            _page("Overheating", "The Widget 2.0 battery can overheat.", date="2024-05-01"),
        )
    }
    return make_research_get(q2p)


def _cli_fake():
    return FakeLlm(
        plan=["q-overheat"],
        synth={"q-overheat": ["Widget 2.0 battery can overheat under sustained load"]},
        gaps=[[]],
    )


class TestDryRunAndGoCli:
    def test_dry_run_prints_scope_and_never_calls_the_llm(self, tmp_path, capsys):
        user, ws = _make_research_ws(tmp_path, namespace="res-dry")
        fake = _cli_fake()
        code = _cmd_sources(
            ["ingest", ws, "--user", user, "--root", str(tmp_path), "--source", "x-research"],
            http_get=_cli_get(),
            llm_call=fake,
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "acquire-scope" in out and "DRY-RUN" in out
        assert "bounded CEILING" in out  # honest disclosure: a range, not an exact bill
        assert fake.calls == [], "the fake LLM must NEVER be called on a dry-run (spends nothing)"
        head = (
            tmp_path
            / "users"
            / user
            / "zones"
            / "default"
            / "workspaces"
            / ws
            / "sources"
            / "cache"
            / "res-dry"
            / "HEAD"
        )
        assert not head.exists(), "a dry-run must cache nothing (no HEAD, no spend)"

    def test_go_drives_the_loop_and_caches(self, tmp_path, capsys):
        user, ws = _make_research_ws(tmp_path, namespace="res-drive")
        fake = _cli_fake()
        code = _cmd_sources(
            [
                "ingest",
                ws,
                "--user",
                user,
                "--root",
                str(tmp_path),
                "--source",
                "x-research",
                "--go",
            ],
            http_get=_cli_get(),
            llm_call=fake,
        )
        out = capsys.readouterr().out
        assert code == 0
        assert fake.calls, "with --go the loop MUST drive the fake LLM"
        assert "newly cached" in out and "subscription LLM" in out
        head = (
            tmp_path
            / "users"
            / user
            / "zones"
            / "default"
            / "workspaces"
            / ws
            / "sources"
            / "cache"
            / "res-drive"
            / "HEAD"
        )
        assert head.is_file(), "--go must seal a slice + advance HEAD"

    def test_ingest_help_lists_research_and_go(self, capsys):
        with pytest.raises(SystemExit):
            _cmd_sources(["ingest", "--help"])
        out = capsys.readouterr().out
        assert "research" in out and "--go" in out


# ---------------------------------------------------------------------------
# Money-safety: the LLM path routes through the subscription transport (F10 key-strip).
# ---------------------------------------------------------------------------


def _ok_runner(recorded: dict | None = None):
    def _runner(request):
        if recorded is not None:
            recorded["env"] = dict(request.env)
            recorded["argv"] = tuple(request.argv)
            recorded["stdin"] = request.stdin_text
        body = json.dumps(
            {"type": "result", "subtype": "success", "is_error": False, "result": "[]"}
        )
        return ProcessOutcome(timed_out=False, returncode=0, stdout=body, stderr="")

    return _runner


class TestTransportMoneySafety:
    def test_real_seam_routes_through_transport_and_strips_api_key(self):
        # The DEFAULT seam is the subscription transport; an ambient ANTHROPIC_API_KEY is STRIPPED
        # from the child env (F10), and the per-call budget rides as --max-budget-usd. No real call.
        recorded: dict = {}
        base_env = {"PATH": "/usr/bin", ANTHROPIC_API_KEY_ENV: "sk-should-be-stripped"}
        seam = _transport_llm_call(runner=_ok_runner(recorded), base_env=base_env)
        text = seam("hello", budget=0.5)
        assert text == "[]"
        assert ANTHROPIC_API_KEY_ENV not in recorded["env"], "F10: the API key must be stripped"
        assert "--max-budget-usd" in recorded["argv"] and "0.5" in recorded["argv"]
        assert "-p" in recorded["argv"] and "--no-session-persistence" in recorded["argv"]

    def test_injected_api_key_is_refused(self):
        # An explicit attempt to smuggle the key back via env overrides is refused LOUDLY (F10).
        seam = _transport_llm_call(
            runner=_ok_runner(), env_overrides={ANTHROPIC_API_KEY_ENV: "sk-x"}
        )
        with pytest.raises(ApiKeyPresentError):
            seam("hello", budget=0.5)

    def test_research_feed_refuses_the_free_ingest_path(self, tmp_path):
        # Routing a PAID research source through the FREE ingest_feed conduit (no seam) refuses
        # LOUDLY — the loop can never spend silently on the wrong path.
        store = WorkspaceStore(tmp_path / "ws")
        with pytest.raises(FeedError, match="PAID loop"):
            ingest_feed(research_config("res-refuse"), store, http_get=make_research_get({}))


# ---------------------------------------------------------------------------
# Regression: feeds still ingest FREE (no --go); begin-session stays exit 3.
# ---------------------------------------------------------------------------

EDGAR_FEED_YAML = f"""\
kind: edgar
namespace: edgar-widget
content_kind: regulatory-filing
temporality: archival
connection:
  user_agent: "{UA}"
  cik: "{CIK}"
  forms: ["8-K"]
"""


class TestFreeAndSessionInvariants:
    def test_feeds_ingest_still_free_without_go(self, tmp_path, capsys):
        feeds_dir = (
            tmp_path
            / "users"
            / "acme"
            / "zones"
            / "default"
            / "workspaces"
            / "widgets"
            / "sources"
            / "feeds"
        )
        feeds_dir.mkdir(parents=True)
        (feeds_dir / "x-edgar.yaml").write_text(EDGAR_FEED_YAML, encoding="utf-8")
        code = _cmd_sources(
            ["ingest", "widgets", "--user", "acme", "--root", str(tmp_path)],
            http_get=make_http_get(edgar_bytes([_8K])),
        )
        out = capsys.readouterr().out
        assert code == 0
        assert "$0 model spend" in out  # a feed source is free — no --go needed, no paid gate

    def test_begin_session_stays_unwired_exit_3(self):
        # The research verb is a LOCAL maintenance command; it never wires the paid session door.
        from pipeline.api import invoke as invoke_mod
        from pipeline.api.invoke import main_cli

        snapshot = dict(invoke_mod._VERB_HANDLERS)
        try:
            code = main_cli(
                [
                    "begin-session",
                    "--workspace",
                    "workspace.template",
                    "--user",
                    "acme",
                    "--params-json",
                    "{}",
                ]
            )
        finally:
            invoke_mod._VERB_HANDLERS.clear()
            invoke_mod._VERB_HANDLERS.update(snapshot)
        assert code == 3


def _head(store, namespace) -> tuple[Path, str]:
    ns_dir = namespace_dir(store, namespace)
    return ns_dir, read_head(ns_dir)
