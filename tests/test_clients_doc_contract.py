"""Anti-drift accuracy check: `docs/guide/clients.md` == the server's OWN wire vocabulary.

`docs/guide/clients.md` is the single neutral source every language client wrapper reads for the
error/status token sets (F2). This test keeps that page HONEST by binding its four machine-readable
`<!-- wire-tokens:<name>:begin/end -->` blocks to ground truth the SERVER emits — and it derives
that truth by **importing the server's own constants**, never by scraping prose:

- **sync-errors** and **async-status** are inline `"error"`/`"status"` string literals in
  `http_shim.py` with no named constant, so their truth is a regex over those literals PLUS a count
  tripwire (17 / 6): if a future token becomes a variable/f-string the count shifts and the test
  flags it loudly instead of silently under-counting.
- **terminal-codes** is the load-bearing set (F-A/F-C). It is the IMPORT-DERIVED union of the
  envelope-fatal codes (`http_shim._FATAL_STATUS`), the runner's synthesized codes
  (`jobrunner.TERMINAL_FAILED_CODE` / `RE_DRIVABLE_CODE`), the transport `"timeout"` literal,
  `results.CODE_RATE_LIMIT_BACKPRESSURE`, and every NONDETERMINISTIC block-capable taxonomy code
  (`results.CODES` block arm minus `jobs.DETERMINISTIC_BLOCK_CODES`). `runner-failed`, `re-drivable`
  and `timeout` are NOT in `results.CODES` at all, so a text-scrape of `http_shim.py` would MISS
  them — the explicit imports are what make the guarantee real. A doc that forgets `runner-failed`
  or `rate-limit-backpressure` FAILS set-equality here; adding/renaming a code shifts the union and
  breaks the test until the doc is updated.
- **callback-events** is imported directly (`callback_delivery.EVENT_DONE` / `EVENT_FAILED`).

**The one honest boundary (F-G).** The wire `code` field is an OPEN string, not a closed enum. This
test bounds the KNOWN/MAPPED terminal-code vocabulary only; the transport/session layer can carry an
unlisted structured code (e.g. `api-error`) that the server maps to a generic terminal 500. The doc
states that open-string rule in prose, and the client surfaces the raw `code` (branching on
`redrivable`/`terminal`), so an unrecognized code is reported, never a crash. This test asserts only
the token SETS — not full body shapes or the status-code map (those stay prose). Overlap across the
four sets is expected and legal (`not-found` is both a sync error and a terminal code;
`re-drivable` is both a status and a terminal code) — each set is compared independently.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipeline import callback_delivery, jobs
from pipeline.api import http_shim, jobrunner, results

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CLIENTS_DOC = _REPO_ROOT / "docs" / "guide" / "clients.md"

#: A wire token: lowercase, may carry hyphens (`re-drivable`) or a dot (`job.done`). Deliberately
#: does NOT match code-fence lines (```) or blank/prose lines, so the block parser ignores them.
_TOKEN_RE = re.compile(r"[a-z][a-z0-9.\-]*")

#: The inline `{"error": "<tok>"}` / `{"status": "<tok>"}` literals — genuine strings, no constant.
_ERROR_LITERAL_RE = re.compile(r'"error":\s*"([a-z][a-z0-9\-]*)"')
_STATUS_LITERAL_RE = re.compile(r'"status":\s*"([a-z][a-z0-9\-]*)"')


def _doc_text() -> str:
    return _CLIENTS_DOC.read_text(encoding="utf-8")


def _shim_source() -> str:
    """The `http_shim.py` SOURCE (via `__file__`) — the regex sub-sets read the literals from it."""
    return Path(http_shim.__file__).read_text(encoding="utf-8")


def _doc_block(name: str) -> set[str]:
    """The token set inside the `<!-- wire-tokens:<name>:begin/end -->` block of clients.md.

    Tokens are one-per-line inside a fenced block; the fence lines and any blank/prose lines are
    ignored (they do not match `_TOKEN_RE`). A missing sentinel fails loudly (a renamed sentinel
    would otherwise yield an empty set and silently pass only against an empty truth — never one of
    ours)."""
    text = _doc_text()
    begin = f"<!-- wire-tokens:{name}:begin -->"
    end = f"<!-- wire-tokens:{name}:end -->"
    assert begin in text, f"clients.md is missing the {begin!r} sentinel"
    assert end in text, f"clients.md is missing the {end!r} sentinel"
    inner = text.split(begin, 1)[1].split(end, 1)[0]
    return {line.strip() for line in inner.splitlines() if _TOKEN_RE.fullmatch(line.strip())}


# --- Ground truth by IMPORT (terminal/callback) + regex-over-literals (sync/async) ---------------


def _sync_error_tokens() -> set[str]:
    return set(_ERROR_LITERAL_RE.findall(_shim_source()))


def _async_status_tokens() -> set[str]:
    return set(_STATUS_LITERAL_RE.findall(_shim_source()))


def _terminal_codes() -> set[str]:
    """The import-derived terminal `code` union — the F-A/F-C anti-drift set (module docstring)."""
    return (
        set(http_shim._FATAL_STATUS)
        | {jobrunner.TERMINAL_FAILED_CODE, jobrunner.RE_DRIVABLE_CODE}
        | {"timeout"}
        | {results.CODE_RATE_LIMIT_BACKPRESSURE}
        | (
            {code for code, spec in results.CODES.items() if "block" in spec.statuses}
            - jobs.DETERMINISTIC_BLOCK_CODES
        )
    )


def _callback_events() -> set[str]:
    return {callback_delivery.EVENT_DONE, callback_delivery.EVENT_FAILED}


def _assert_block_equals(name: str, truth: set[str]) -> None:
    doc = _doc_block(name)
    missing = truth - doc
    extra = doc - truth
    assert not missing and not extra, (
        f"clients.md `wire-tokens:{name}` drifted from the server's own vocabulary — "
        f"missing (code emits it, doc omits it)={sorted(missing)}; "
        f"extra (doc lists it, code never emits it)={sorted(extra)}"
    )


# --- The count tripwires (A/B): a literal that becomes a variable shifts the count, loudly ------


def test_sync_error_count_tripwire() -> None:
    tokens = _sync_error_tokens()
    assert len(tokens) == 17, (
        f"expected 17 inline sync `error` literals in http_shim.py, found {len(tokens)}: "
        f"{sorted(tokens)} — if a token became a variable/f-string, source it explicitly here"
    )


def test_async_status_count_tripwire() -> None:
    tokens = _async_status_tokens()
    assert len(tokens) == 6, (
        f"expected 6 inline async `status` literals in http_shim.py, found {len(tokens)}: "
        f"{sorted(tokens)}"
    )


# --- Set-equality per sub-block: the doc lists EXACTLY what the server can emit ------------------


def test_sync_errors_block_matches() -> None:
    _assert_block_equals("sync-errors", _sync_error_tokens())


def test_async_status_block_matches() -> None:
    _assert_block_equals("async-status", _async_status_tokens())


def test_terminal_codes_block_matches() -> None:
    _assert_block_equals("terminal-codes", _terminal_codes())


def test_callback_events_block_matches() -> None:
    _assert_block_equals("callback-events", _callback_events())


def test_terminal_codes_include_the_non_scrapable_codes() -> None:
    """The codes a text-scrape of http_shim.py would MISS must be present (the F-A/F-C fix).

    `runner-failed`/`re-drivable`/`timeout` are jobrunner/transport literals absent from
    `results.CODES`; `rate-limit-backpressure` is the 429 backstop code. A doc omitting any of them
    must fail — this makes that requirement explicit alongside the set-equality above."""
    doc = _doc_block("terminal-codes")
    for code in ("runner-failed", "re-drivable", "timeout", "rate-limit-backpressure"):
        assert code in doc, (
            f"clients.md terminal-codes must list {code!r} — a client branches on it when a job "
            "dies mid-flight (F-A/F-C anti-drift)"
        )
