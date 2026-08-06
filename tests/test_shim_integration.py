"""tests/test_shim_integration.py — DR-1 W4: the NON-INJECTED Tier-B integration harness.

This harness proves the reshaped Tier-B result-delivery machinery works END TO END over the
**real** detached spawn / claims / store / jobs path — the class of test that previously caught
the inert-runner bug (`jobrunner.main()` never wired the handler registry, so every real
`generate-next` job died with a `HandlerNotWired` terminal). Its whole value is that it injects
**no** seam on the spawn/claims/materialize/delivery path: a real `spawn_runner` detached
subprocess, a real `JobStore.submit`, a real `resolve_job_state` (real `is_done` + real
`claims.peek`), and a real `jobrunner.main()` that wires its own registry and re-enters the real
`invoke()` door.

**The fake-binary mechanism (hermetic — NO real `claude`, NO LLM, NO spend, NO outbound network).**
`pipeline.transport` locates the headless binary by NAME (`claude`) via the child env `PATH`
(`DEFAULT_BINARY = "claude"`, resolved by `subprocess.run` in the child env). We put a FAKE `claude`
executable on `PATH` (`monkeypatch.setenv("PATH", ...)`); the detached runner (a `Popen` that
inherits `os.environ`) therefore reaches the fake binary through the REAL transport with ZERO
transport edits. The fake emits a deterministic, valid headless result envelope, so a REAL
`generate-next` artifact MATERIALIZES through the REAL compose→persist→(review)→serialize path. The
fake distinguishes the writer prompt (`## Compose context (JSON)`) from the advisory review prompt
(`## Review context (JSON)`) and answers each with a valid, fully-grounded/cited body or a `pass`
assessment. It also supports a HOLD mode (block the writer on a release sentinel — a deterministic
"slow runner") and a `nonok` mode (emit `is_error: true` — a real generation failure).

**Two facts are proven here:**

1. **Poll materialize + anti-double-charge, end to end (the make-or-break, fully non-injected).**
   A submit spawns a REAL detached runner that outlives the caller; a bounded poll over the REAL
   `resolve_job_state` transitions to DONE with the real output fetchable. A re-submit WHILE the
   runner is still running resolves `existing` with NO second spawn and NO steal (the reshaped
   guard). And a poll past the OLD 120 s startup-grace line but within the job lifetime resolves
   RUNNING (`within-lifetime`) — the exact W1 fix, proven against a REAL slow (sentinel-held) runner
   in a genuine no-claim gap (the claim is acquired only at persist, AFTER the held writer returns,
   so `claims.peek` is None during the hold — the poll reaches the record-window branch, not the
   claim-live branch). The same record under the OLD 120 s window would have resolved
   `failed-redrivable` — the bug that caused a second paid run.

2. **The webhook SSRF guard is ENFORCED in the REAL detached delivery (non-injected).** A real
   detached runner materializes a job carrying a `callback_url` at a REAL loopback `http.server`
   receiver whose host is ALLOW-LISTED. Because the SSRF guard CORRECTLY blocks loopback, the real
   runner's `deliver_callback` re-validation REFUSES at delivery: the receiver logs ZERO hits and
   the job record's `callback_status` is `rejected-at-delivery`. This proves the guard is active in
   the production delivery path (a real detached runner, not a mock).

**Honest scope note (also in the implementation report).** A POSITIVE webhook delivery — a real
receiver actually RECEIVING the ping — CANNOT be proven through a detached spawn to a LOOPBACK
receiver, because the SSRF guard rightly blocks loopback and the detached runner exposes no
injection point. Faking a "positive non-injected loopback delivery" would require BYPASSING the
guard, which is dishonest. That positive path (the wakeup-only payload shape + a `delivered`
status) is asserted in W3c's `tests/test_callback_delivery.py`, in
`test_done_posts_wakeup_only_and_reports_delivered`, through an INJECTED `_RecordingOpener`
(with a global-IP resolver) — NOT a real receiver. W3c's ONE real loopback `http.server` proves
only the no-redirect REFUSAL (the redirect target is never reached), not a positive delivery. So
this harness proves (poll-materialize end to end) + (the guard is enforced in the real delivery);
the positive wakeup shape is proven in W3c. The webhook test constructs the runner's `JobSpec`
directly (mirroring the shim's submit)
rather than posting a loopback `callback_url` through the shim — the shim's SUBMIT-time guard would
(correctly) 400 a loopback URL before any spawn, so exercising the DELIVERY-time re-validation in a
real detached runner requires handing the runner a spec the way a DNS-rebind would (global at
submit, internal at
delivery). The HTTP wire layer (auth / body caps / status mapping / submit-time guard) is covered by
`tests/test_http_shim.py` over injected seams; THIS file is the non-injected spawn/materialize core.
"""

from __future__ import annotations

import http.server
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from pipeline.adapters import default_adapters
from pipeline.api import fetch, jobrunner, session
from pipeline.api import invoke as invoke_mod
from pipeline.jobs import JOB_LIFETIME_SECONDS, JobStore, resolve_job_state
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.review import ARTIFACT_CHECKS, DELIVERABLE_CHECKS
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate
from pipeline.spine import registry_for
from pipeline.store import WorkspaceStore, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]
WS = "shim-int"
USER = "acme"

#: The FULL §6.3 grounding grammar over ≥2 folder sources — the same shape the MVP scenario uses so
#: the widget topic GROUNDS (a ≥2-instance resolved conflict on the timeout claim), which lets the
#: real compose→persist path materialize the artifact.
M3_RUN_SELECTION: dict[str, object] = {
    "require": ["trusted >= 3"],
    "span": {"independence": ["first-party", "independent"]},
    "prefer": [{"authoritative": 1}],
    "on_conflict": "preserve-and-attribute",
}

_HAS_GIT = shutil.which("git") is not None
_PANDOC_AVAILABLE = pandoc_available()

_BEGIN_PARAMS = {
    "recipe": "explainer-post",
    "topics": ["x-widget-service"],
    "platforms": ["github"],
    "languages": ["en"],
    "output_types": ["md"],
    "presentations": ["plain"],
    "run_selection": M3_RUN_SELECTION,
}


@pytest.fixture(autouse=True)
def _require_substrate() -> None:
    """Gate on the two REAL externals this non-injected harness needs (besides the fake `claude`):
    pandoc (the real serialize legs run real bytes through the pinned binary — PA-12: absent+CI ⇒
    FAIL loudly, absent locally ⇒ skip) and git (the folder-adapter corpus is a real checkout so it
    pins a §7.2 commit — a plain folder is commitless and the preimage refuses it)."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the non-injected harness serializes real bytes and MUST "
            "run in CI (PA-12); a silent skip cannot make CI green",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the non-injected materialize path requires it")
    if not _HAS_GIT:
        pytest.skip("git not available; the folder-adapter corpus needs a checkout to pin a commit")


# ---------------------------------------------------------------------------
# The hermetic world (real framework registries + a folder-adapter git corpus + a tmp workspace).
# Grounding rides the PRODUCTION-default `folder` adapter (the detached runner wires bare production
# defaults — no `mock` adapter is reachable there), so the world must ground through a real adapter.
# ---------------------------------------------------------------------------

_L2_DEFAULTS = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
_TOPIC = (
    "---\nid: x-widget-service\nprovenance: instance\nschema_version: 1\n"
    "why: Explain the widget service.\n---\n\nBody.\n"
)
_SOURCE = (
    "---\nid: {sid}\nprovenance: instance\nschema_version: 1\nadapter: folder\n"
    "connection:\n  path: {path}\ncontent_kind: general\ntrusted: {t}\n"
    "independence: {ind}\nprimariness: {pri}\n---\n\nSynthetic folder source {sid}.\n"
)
#: A tmp `github` platform adding a `short-opinion-post: pass` reconcile default (§12.3) so the demo
#: format reconciles with the never-LLM `pass` strategy (no reconciler transport call), and a large
#: markdown limit `default_measure` does not measure (so the deliverable never blocks).
_GITHUB_PASS = (
    "---\nid: github\nprovenance: framework\nschema_version: 1\n"
    "destination: GitHub repository surfaces.\nadvisory_norms:\n  preferred_line_length: 120\n"
    "hard_limits:\n  markdown_body_char_limit: 65536\n"
    "reconcile_strategy_defaults:\n  short-opinion-post: pass\ndefault_output_type: md\n"
    "---\n\n# github — platform (test fixture)\n"
)
_DOC_A = (
    "# Widget service\n\nThe widget service default timeout is 30 seconds.\n\n"
    "The widget service retries failed calls three times.\n"
)
_DOC_B = (
    "# Widget service mirror\n\nThe widget service default timeout is 60 seconds.\n\n"
    "The widget service caches results for one hour.\n"
)


def _git_init(root: Path) -> None:
    """Init a throwaway git checkout so the folder adapter pins its HEAD as the §7.2 commit. This
    instance's own synthetic-generic corpus under tmp — never a client repo, never committed."""

    def g(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
        )

    g("init", "-q")
    g("config", "user.email", "shim-int@example.invalid")
    g("config", "user.name", "Shim Integration Test")
    g("add", "-A")
    g("-c", "commit.gpgsign=false", "commit", "-q", "-m", "corpus")


def _build_world(tmp: Path) -> Path:
    """A full framework root (real registries) + a tmp `github` platform + a tmp workspace whose two
    folder sources point at synthetic git corpora — the entire hermetic §25-shaped world, in tmp."""
    root = tmp / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(_L2_DEFAULTS, encoding="utf-8")
    (registry_dir(root, "platforms") / "github.md").write_text(_GITHUB_PASS, encoding="utf-8")

    topics_dir = root / "users" / USER / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    (topics_dir / "x-widget-service.md").write_text(_TOPIC, encoding="utf-8")

    corpus_a, corpus_b = tmp / "corpus-a", tmp / "corpus-b"
    (corpus_a / "docs").mkdir(parents=True)
    (corpus_a / "docs" / "widget.md").write_text(_DOC_A, encoding="utf-8")
    (corpus_b / "docs").mkdir(parents=True)
    (corpus_b / "docs" / "widget.md").write_text(_DOC_B, encoding="utf-8")
    _git_init(corpus_a)
    _git_init(corpus_b)

    sources_dir = root / "users" / USER / "workspaces" / WS / "sources"
    sources_dir.mkdir(parents=True)
    (sources_dir / "x-alpha.md").write_text(
        _SOURCE.format(sid="x-alpha", path=str(corpus_a), t=5, ind="first-party", pri="primary"),
        encoding="utf-8",
    )
    (sources_dir / "x-beta.md").write_text(
        _SOURCE.format(sid="x-beta", path=str(corpus_b), t=4, ind="independent", pri="secondary"),
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# The FAKE `claude` binary. Self-contained (no `pipeline` import): the review check sets are
# embedded from the SSOT at generation time, so it can never drift yet needs no venv coupling.
# ---------------------------------------------------------------------------

_FAKE_CLAUDE = '''#!{py}
"""A hermetic fake `claude` — reads the prompt on stdin, emits a valid headless result envelope on
stdout. NO LLM, NO network. Behaviour keyed off env vars the detached runner inherits."""
import json, os, re, sys, time
from pathlib import Path

ARTIFACT_CHECKS = {artifact_checks!r}
DELIVERABLE_CHECKS = {deliverable_checks!r}
_CTX = re.compile(r"## Compose context \\(JSON\\)\\s*```json\\s*\\n(.*?)\\n```", re.DOTALL)


def _envelope(text):
    # The step-04 success envelope the transport reads (`.result` = the stage output).
    return json.dumps({{"type": "result", "subtype": "success", "is_error": False,
                        "result": text, "session_id": "sess", "uuid": "uuid"}})


def _cited_body(facts):
    # Cite EVERY grounded fact at its EXACT tier so the §16 fidelity coverage check passes.
    cites = " ".join(
        '[grounded %s]{{.%s data-fact="%s"}}.' % (f["fact_id"], f["tier"], f["fact_id"])
        for f in facts
    )
    return "Hook: a sharp observation. The point, stated plainly. Evidence: " + cites + " Takeaway."


def _writer_content(prompt):
    ctx = json.loads(_CTX.search(prompt).group(1))
    facts, structure = ctx["grounded_facts"], ctx["structure"]
    body = _cited_body(facts)
    if structure["shape"] == "flat":
        return {{"body": body}}
    roles = structure["roles"]
    return {{"parts": {{r: (body if i == 0 else "Notes for " + r + ".")
                        for i, r in enumerate(roles)}}}}


def _review(prompt):
    checks = DELIVERABLE_CHECKS if "ast_provenance" in prompt else ARTIFACT_CHECKS
    return {{"verdict": "pass",
             "checks": {{c: {{"status": "pass", "note": "ok"}} for c in checks}},
             "summary": "hermetic fake review — grounded and fitting"}}


def main():
    prompt = sys.stdin.read()
    if "## Compose context (JSON)" in prompt:  # the WRITER (compose) prompt
        log = os.environ.get("FAKE_CLAUDE_WRITER_LOG")
        if log:  # one line PER writer invocation — proves how many runners reached compose
            with open(log, "a") as fh:
                fh.write(str(os.getpid()) + "\\n")
                fh.flush()
        release = os.environ.get("FAKE_CLAUDE_RELEASE_FILE")
        if release:  # HOLD mode: block (bounded) until released — a deterministic slow runner
            deadline = time.time() + 120
            while not Path(release).exists() and time.time() < deadline:
                time.sleep(0.02)
        if os.environ.get("FAKE_CLAUDE_MODE") == "nonok":  # a real generation failure
            print(json.dumps({{"type": "result", "subtype": "success", "is_error": True,
                               "terminal_reason": "api_error", "session_id": "s", "uuid": "u"}}))
            return
        print(_envelope(json.dumps(_writer_content(prompt))))
    elif "## Review context (JSON)" in prompt:  # the advisory REVIEW prompt
        print(_envelope(json.dumps(_review(prompt))))
    else:  # no other prompt shape reaches the transport in this harness
        print(_envelope("unrecognized-prompt"))


main()
'''


def _install_fake_claude(bin_dir: Path) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = _FAKE_CLAUDE.format(
        py=sys.executable,
        artifact_checks=list(ARTIFACT_CHECKS),
        deliverable_checks=list(DELIVERABLE_CHECKS),
    )
    path = bin_dir / "claude"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


# ---------------------------------------------------------------------------
# Reaping + bounded-wait helpers (deterministic: sentinel-gated, no wall-clock races).
# ---------------------------------------------------------------------------


@pytest.fixture
def spawned():
    """Track detached `SpawnHandle`s and REAP them in teardown: kill the runner's whole process
    GROUP (which also reaps a held fake `claude`) and wait the `Popen` so no zombie survives."""
    handles: list = []
    yield handles
    for handle in handles:
        pid = getattr(handle, "pid", None)
        if pid is not None:
            try:
                os.killpg(os.getpgid(pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        child = getattr(handle, "handle", None)
        if child is not None:
            try:
                child.wait(timeout=10)
            except Exception:
                pass


def _wait_until(predicate, *, timeout: float = 60.0, interval: float = 0.05) -> bool:
    """Bounded poll for `predicate()` truthiness — the ONLY timing primitive; every assertion that
    follows a wait is otherwise deterministic (fixed clocks / sentinel state)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _writer_calls(writer_log: Path) -> int:
    return writer_log.read_text(encoding="utf-8").count("\n") if writer_log.exists() else 0


def _begin_and_plan(root: Path, store: WorkspaceStore, adapters) -> tuple[str, list[str]]:
    """Real begin-session (folder adapter pins the §7.2 commit) → the resumption token + the
    LLM-free predictable target-id set (`plan_next_batch_ids`), exactly what the shim resolves."""
    begin = invoke_mod.invoke(
        "begin-session",
        WS,
        USER,
        dict(_BEGIN_PARAMS),
        store=store,
        root=str(root),
        handlers={"begin-session": session.begin_session_handler(adapters=adapters)},
    )
    assert begin["envelope"]["ok"], begin["envelope"]
    token = begin["token"]
    decoded = invoke_mod.token_mod.decode(token, expected_workspace=WS)
    target_ids = list(session.plan_next_batch_ids(root, USER, WS, decoded, {"batch_size": 1}))
    assert target_ids, "the plan must resolve a predictable target artifact-id"
    return token, target_ids


# ---------------------------------------------------------------------------
# FACT 1 — poll materialize end to end + anti-double-charge, fully non-injected.
# ---------------------------------------------------------------------------


def test_poll_materialize_within_lifetime_and_no_double_spawn(tmp_path, monkeypatch, spawned):
    root = _build_world(tmp_path)
    bin_dir = tmp_path / "bin"
    _install_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    writer_log = tmp_path / "writer.log"
    release_file = tmp_path / "release.sentinel"
    monkeypatch.setenv("FAKE_CLAUDE_WRITER_LOG", str(writer_log))
    monkeypatch.setenv("FAKE_CLAUDE_RELEASE_FILE", str(release_file))  # HOLD the writer

    store = WorkspaceStore.at(root, USER, WS)
    store.ensure_layout()
    adapters = default_adapters()
    token, target_ids = _begin_and_plan(root, store, adapters)
    tid = target_ids[0]

    job_store = JobStore(store.jobs_dir)
    claims = registry_for(store)

    def _done(target: str) -> bool:
        return is_done(store, target)

    # REAL submit (create-exclusive) at a FIXED clock T0, then a REAL detached spawn.
    t0 = 1_000_000.0
    outcome = job_store.submit(target_ids, "idem-1", now=t0, is_done=_done, peek=claims.peek)
    assert outcome.disposition == "spawned" and outcome.spawn
    spec = jobrunner.JobSpec(
        key=outcome.key,
        verb="continue-session",
        workspace=WS,
        user=USER,
        params={"action": "generate-next", "batch_size": 1, "idempotency_key": "idem-1"},
        idempotency_key="idem-1",
        root=str(root),
        token=token,
        pins=None,
        target_ids=tuple(target_ids),
    )
    handle = jobrunner.spawn_runner(spec, spawn_dir=store.jobs_dir)  # REAL detached subprocess
    spawned.append(handle)

    # The runner outlives the caller: wait until it REACHES the held writer (a real slow runner).
    assert _wait_until(lambda: _writer_calls(writer_log) >= 1), "runner never reached the writer"

    # No live claim during the writer hold — the claim is acquired at persist, AFTER the held writer
    # returns, so this is a genuine no-claim gap and the poll reaches the record-window branch.
    assert claims.peek(tid) is None

    record = job_store.load(outcome.key)
    assert record is not None and record.spawn_time == t0
    # W1 FIX: past the OLD 120 s startup line but within the job lifetime → RUNNING
    # (within-lifetime), not the resend the old boundary would have emitted.
    fixed = resolve_job_state(
        record, tid, now=t0 + 200, is_done=_done, peek=claims.peek,
        job_lifetime=JOB_LIFETIME_SECONDS,
    )
    assert fixed.kind == "running" and fixed.detail == "within-lifetime"
    # The exact bug the fix closes: the SAME record under the old 120 s window resolves redrivable
    # (telling a client to resend a job that is still legitimately running → a second paid run).
    bug = resolve_job_state(
        record, tid, now=t0 + 200, is_done=_done, peek=claims.peek, job_lifetime=120.0
    )
    assert bug.kind == "failed-redrivable"

    # Anti-double-charge: a re-submit (same idempotency_key) WHILE running → existing, NO second
    # spawn and NO steal (the incumbent record is neither re-spawned nor rewritten).
    resubmit = job_store.submit(
        target_ids, "idem-1", now=t0 + 200, is_done=_done, peek=claims.peek
    )
    assert resubmit.disposition == "existing" and not resubmit.spawn
    assert job_store.load(outcome.key).spawn_time == t0  # unchanged → no steal
    assert _writer_calls(writer_log) == 1  # no second runner reached the writer

    # Release the held writer → the artifact MATERIALIZES through the real compose→persist path.
    release_file.write_text("go", encoding="utf-8")
    assert _wait_until(lambda: all(_done(t) for t in target_ids)), "artifact did not materialize"

    # The REAL poll resolver now transitions to DONE by OUTPUT existence (§22.7 authority #1).
    done_state = resolve_job_state(
        job_store.load(outcome.key), tid, now=t0 + 300, is_done=_done, peek=claims.peek
    )
    assert done_state.kind == "done" and done_state.detail == "output-exists"

    # The real output is fetchable through the existing `fetch-by-id` door.
    fetched = invoke_mod.invoke(
        "fetch-by-id", WS, USER, {"id": tid}, root=str(root),
        handlers={"fetch-by-id": fetch.fetch_handler()},
    )
    assert fetched["envelope"]["ok"] and fetched["results"]
    # Exactly ONE paid writer call across the whole flow — the guard held end to end.
    assert _writer_calls(writer_log) == 1


# ---------------------------------------------------------------------------
# FACT 2 — the webhook SSRF guard is ENFORCED in the REAL detached delivery.
# ---------------------------------------------------------------------------


class _CountingReceiver:
    """A REAL loopback `http.server` on 127.0.0.1:0 that COUNTS every request it receives. It must
    receive ZERO — the SSRF guard refuses the loopback callback at delivery, so nothing is ever
    POSTed. (Loopback-only; it never egresses.)"""

    def __init__(self) -> None:
        outer = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                outer.hits += 1
                length = int(self.headers.get("Content-Length", 0) or 0)
                if length:
                    self.rfile.read(length)
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_a) -> None:  # silence the test log
                pass

        self.hits = 0
        self.server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def test_webhook_guard_rejects_loopback_at_real_detached_delivery(tmp_path, monkeypatch, spawned):
    root = _build_world(tmp_path)
    bin_dir = tmp_path / "bin"
    _install_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    # No release sentinel → the writer emits immediately; the job materializes, THEN the runner
    # reaches the real delivery step.

    store = WorkspaceStore.at(root, USER, WS)
    store.ensure_layout()
    adapters = default_adapters()
    token, target_ids = _begin_and_plan(root, store, adapters)

    receiver = _CountingReceiver()
    try:
        callback_url = f"http://127.0.0.1:{receiver.port}/hook"
        job_store = JobStore(store.jobs_dir)
        claims = registry_for(store)

        def _done(target: str) -> bool:
            return is_done(store, target)

        # REAL submit writes a record carrying the callback_url (JobStore.submit does not validate
        # the URL — that guard is the shim's; here we exercise the DELIVERY-time re-validation).
        outcome = job_store.submit(
            target_ids, "idem-cb", now=time.time(), is_done=_done, peek=claims.peek,
            callback_url=callback_url,
        )
        assert outcome.spawn
        # The runner re-validates against the FROZEN allow-list snapshot on the spec — the
        # receiver's host IS allow-listed, so the allow-list gate PASSES and the SSRF loopback
        # block is what fires (proving the SSRF guard, not merely the allow-list).
        spec = jobrunner.JobSpec(
            key=outcome.key,
            verb="continue-session",
            workspace=WS,
            user=USER,
            params={"action": "generate-next", "batch_size": 1, "idempotency_key": "idem-cb"},
            idempotency_key="idem-cb",
            root=str(root),
            token=token,
            pins=None,
            callback_url=callback_url,
            target_ids=tuple(target_ids),
            allowed_callback_hosts=frozenset({"127.0.0.1"}),
        )
        handle = jobrunner.spawn_runner(spec, spawn_dir=store.jobs_dir)  # REAL detached subprocess
        spawned.append(handle)

        # The runner materializes the job, then attempts delivery and records the outcome.
        def _status() -> object:
            rec = job_store.load(outcome.key)
            return rec.callback_status if rec is not None else None

        assert _wait_until(lambda: _status() is not None), "runner never recorded a callback status"
        assert all(_done(t) for t in target_ids)  # the job really materialized
        assert job_store.load(outcome.key).callback_status == "rejected-at-delivery"
        # The load-bearing proof: the receiver was NEVER hit — the guard refused before any POST.
        assert receiver.hits == 0
    finally:
        receiver.close()


# ---------------------------------------------------------------------------
# The fake binary's `nonok` mode: a REAL generation failure records a re-drivable terminal on the
# real record, which the REAL poll resolver surfaces as `failed` (the record_terminal path,
# non-injected). Complements the clean materialize path above.
# ---------------------------------------------------------------------------


def test_nonok_records_a_terminal_surfaced_by_the_real_poll(tmp_path, monkeypatch, spawned):
    root = _build_world(tmp_path)
    bin_dir = tmp_path / "bin"
    _install_fake_claude(bin_dir)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "nonok")  # the writer emits is_error: true

    store = WorkspaceStore.at(root, USER, WS)
    store.ensure_layout()
    adapters = default_adapters()
    token, target_ids = _begin_and_plan(root, store, adapters)
    tid = target_ids[0]

    job_store = JobStore(store.jobs_dir)
    claims = registry_for(store)

    def _done(target: str) -> bool:
        return is_done(store, target)

    t0 = 2_000_000.0
    outcome = job_store.submit(target_ids, "idem-nonok", now=t0, is_done=_done, peek=claims.peek)
    assert outcome.spawn
    spec = jobrunner.JobSpec(
        key=outcome.key,
        verb="continue-session",
        workspace=WS,
        user=USER,
        params={"action": "generate-next", "batch_size": 1, "idempotency_key": "idem-nonok"},
        idempotency_key="idem-nonok",
        root=str(root),
        token=token,
        pins=None,
        target_ids=tuple(target_ids),
    )
    handle = jobrunner.spawn_runner(spec, spawn_dir=store.jobs_dir)
    spawned.append(handle)

    # The runner's invoke() returns a coded failure; run_job records a terminal on the real record.
    def _has_terminal() -> bool:
        rec = job_store.load(outcome.key)
        return rec is not None and rec.terminal is not None

    assert _wait_until(_has_terminal), "runner never recorded a terminal"
    assert not _done(tid)  # the artifact did NOT materialize (compose failed)

    record = job_store.load(outcome.key)
    # The REAL poll resolver surfaces the stored terminal (§22.7 truth-table step 3), above the
    # lifetime window — a real failure is not masked as RUNNING.
    state = resolve_job_state(record, tid, now=t0 + 5, is_done=_done, peek=claims.peek)
    assert state.kind == "failed" and state.detail == "stored-terminal"
    assert state.terminal is not None and state.terminal.code == jobrunner.RE_DRIVABLE_CODE
