"""The S-3 crux: N REAL subprocesses admitting against the meter's INTER-PROCESS lock (plan G6).

The real race is SEPARATE `pipeline` processes + detached `jobrunner` subprocesses re-entering
`invoke()` — NOT threads. So this test spawns N genuine OS processes that all admit at once against
a SHARED meter dir, synchronized by a file BARRIER so they storm the critical section TOGETHER. Each
admits a ceiling that individually fits under the umbrella but TOGETHER exceeds it.

To make the inter-process lock's necessity DETERMINISTIC (not a timing accident), each worker
injects the meter's `after_read_probe` — a small sleep INSIDE the critical section, after the
week-to-date read and before the hold write. That widens the read→write window so:

- WITH the OS `flock` (production): the section still serializes — EXACTLY the headroom admits, the
  rest REFUSE pre-spend (no over-admit).
- WITHOUT the `flock` (the negative control disables it, simulating a per-process `threading.Lock`):
  overlapping probes all read the SAME stale total and all pass → the meter OVER-admits.

The negative control proves the `flock` is load-bearing: a `threading.Lock` would fail this. FAKE
clock (a fixed epoch → deterministic week key + holds that never expire mid-test) + FAKE costs; NO
real spend, no transport, no secret, no model call.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import UTC
from decimal import Decimal
from pathlib import Path

from pipeline.spend import meter as M
from pipeline.spend.assignment import SCOPE_ZONE, ScopeKey
from pipeline.spend.meter import WeeklyMeter

_REPO_ROOT = Path(M.__file__).resolve().parents[2]  # <root>/pipeline/spend/meter.py → <root>

# The worker: a standalone script (a REAL separate process) that admits ONCE under the meter's
# inter-process lock, after a file-barrier release, with an in-section probe sleep that FORCES the
# read→write windows to overlap. A FIXED clock keeps the week key deterministic and every hold live
# for the whole test (no settle → holds accumulate). `disable_lock=1` no-ops `fcntl.flock` (the
# negative control — what a per-process threading.Lock would amount to across processes).
_WORKER = r'''
import sys, time, fcntl
from datetime import datetime, timezone
from pathlib import Path

(repo_root, meter_dir, bucket_cap, umbrella_cap, ceiling, run_id, scope_id, ready_dir, n,
 probe_ms, disable_lock) = sys.argv[1:12]
sys.path.insert(0, repo_root)

if disable_lock == "1":
    fcntl.flock = lambda *a, **k: None  # DISABLE the inter-process lock (≈ a per-process lock)

from pipeline.spend import meter as M
from pipeline.spend.assignment import SCOPE_ZONE, ScopeKey

FIXED = datetime(2024, 8, 7, 12, 0, 0, tzinfo=timezone.utc).timestamp()  # fixed Wednesday noon UTC

def _probe():
    time.sleep(int(probe_ms) / 1000.0)  # widen the read→write window inside the critical section

def main():
    m = M.WeeklyMeter(root=meter_dir, clock=lambda: FIXED, after_read_probe=_probe)
    rd = Path(ready_dir); rd.mkdir(parents=True, exist_ok=True)
    (rd / ("ready-" + run_id)).write_text("1")
    # BARRIER: proceed only once all N workers have imported + registered — so they storm together.
    deadline = time.time() + 30.0
    while len(list(rd.iterdir())) < int(n) and time.time() < deadline:
        time.sleep(0.003)
    try:
        m.admit(scope=ScopeKey(SCOPE_ZONE, scope_id), handle="anthropic:acme",
                bucket_cap=bucket_cap, umbrella_cap=umbrella_cap, ceiling=ceiling, run_id=run_id)
        sys.stdout.write("admitted")
    except M.MeterRefusedError:
        sys.stdout.write("refused")
    except Exception as exc:  # any other error is a genuine failure the parent must see
        sys.stdout.write("error:" + type(exc).__name__ + ":" + str(exc))

main()
'''


def _run_workers(
    *,
    tmp_path: Path,
    n: int,
    bucket_cap: str,
    umbrella_cap: str,
    ceiling: str,
    distinct_buckets: bool,
    probe_ms: int = 80,
    disable_lock: bool = False,
) -> list[str]:
    """Launch `n` REAL subprocesses that all admit at once; return their verdicts."""
    worker_py = tmp_path / "worker.py"
    worker_py.write_text(_WORKER, encoding="utf-8")
    meter_dir = tmp_path / "meter"
    ready_dir = tmp_path / "ready"

    procs: list[subprocess.Popen] = []
    for i in range(n):
        scope_id = f"u{i}/work" if distinct_buckets else "dave/work"
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(worker_py),
                    str(_REPO_ROOT),
                    str(meter_dir),
                    bucket_cap,
                    umbrella_cap,
                    ceiling,
                    f"run-{i}",
                    scope_id,
                    str(ready_dir),
                    str(n),
                    str(probe_ms),
                    "1" if disable_lock else "0",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        )
    verdicts: list[str] = []
    for proc in procs:
        out, err = proc.communicate(timeout=90)
        assert not out.startswith("error:"), f"worker errored: {out} / stderr: {err}"
        verdicts.append(out.strip())
    return verdicts


def _fixed_meter(tmp_path: Path) -> WeeklyMeter:
    from datetime import datetime

    fixed = datetime(2024, 8, 7, 12, 0, 0, tzinfo=UTC).timestamp()
    return WeeklyMeter(root=tmp_path / "meter", clock=lambda: fixed)


# ---------------------------------------------------------------------------------------
# the umbrella binds across processes: exactly the headroom admits, the rest refuse pre-spend
# ---------------------------------------------------------------------------------------


def test_concurrent_multiprocess_umbrella_admits_exactly_the_headroom(tmp_path: Path) -> None:
    # 12 processes, each ceiling $3, generous per-bucket caps, a $10 install umbrella. Individually
    # each fits; together (12×3=36) they blow the umbrella. floor(10/3)=3 must admit, 9 refuse —
    # even with the read→write window forced wide open (the flock still serializes them).
    n = 12
    verdicts = _run_workers(
        tmp_path=tmp_path,
        n=n,
        bucket_cap="1000",  # per-bucket headroom is huge — ONLY the umbrella can bind
        umbrella_cap="10",
        ceiling="3",
        distinct_buckets=True,  # a distinct bucket per worker → isolates the UMBRELLA as the guard
    )
    admitted = verdicts.count("admitted")
    refused = verdicts.count("refused")
    assert admitted == 3, f"expected exactly 3 admits (floor(10/3)), got {admitted}: {verdicts}"
    assert refused == n - 3, f"expected {n - 3} refusals, got {refused}: {verdicts}"
    # The umbrella ledger + live holds reflect ONLY the admitted runs — no over-admit slipped in.
    m = _fixed_meter(tmp_path)
    assert m.umbrella_week_to_date() == Decimal("9")  # 3 live holds × $3
    umbrella_holds = m._bucket_dir(M.umbrella_bucket_key(m.current_week())) / "holds"
    assert len(list(umbrella_holds.iterdir())) == 3


def test_concurrent_multiprocess_same_bucket_admits_exactly_the_headroom(tmp_path: Path) -> None:
    # The per-bucket inter-process guard: 10 processes, all the SAME bucket, each ceiling $4, a $20
    # bucket cap (umbrella generous). floor(20/4)=5 admit, 5 refuse — no cross-process over-admit.
    n = 10
    verdicts = _run_workers(
        tmp_path=tmp_path,
        n=n,
        bucket_cap="20",
        umbrella_cap="10000",  # umbrella won't bind — the per-bucket cap is the guard here
        ceiling="4",
        distinct_buckets=False,  # ALL workers hit ONE shared bucket
    )
    admitted = verdicts.count("admitted")
    assert admitted == 5, f"expected exactly 5 admits (floor(20/4)), got {admitted}: {verdicts}"
    assert verdicts.count("refused") == n - 5

    m = _fixed_meter(tmp_path)
    bucket = ScopeKey(SCOPE_ZONE, "dave/work")
    assert m.bucket_week_to_date(bucket, "anthropic:acme") == Decimal("20")


# ---------------------------------------------------------------------------------------
# negative control: WITHOUT the inter-process lock the meter OVER-admits (proves flock is needed)
# ---------------------------------------------------------------------------------------


def test_without_the_interprocess_lock_the_meter_over_admits(tmp_path: Path) -> None:
    # Same race, but `fcntl.flock` is no-op'd in every worker — i.e. what a per-process
    # `threading.Lock` amounts to across SEPARATE processes: zero cross-process mutual exclusion.
    # With the read→write window forced wide (the probe sleep), the concurrent admits all read the
    # SAME stale total (~0) and all pass → the umbrella is BLOWN. This is the failure the real flock
    # prevents (the two tests above), and it is why a threading.Lock would NOT do.
    n = 12
    verdicts = _run_workers(
        tmp_path=tmp_path,
        n=n,
        bucket_cap="1000",
        umbrella_cap="10",  # a correct lock admits exactly floor(10/3)=3
        ceiling="3",
        distinct_buckets=True,
        disable_lock=True,
    )
    admitted = verdicts.count("admitted")
    assert admitted > 3, (
        f"WITHOUT the inter-process lock the meter must OVER-admit (>3), got {admitted}: {verdicts}"
        " — if this ever equals 3 the race did not materialize; widen probe_ms"
    )
