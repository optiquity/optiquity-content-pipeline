# DR-1 (HTTP/webhook shim) — RECONCILED implementation plan (final, for the maintainer PLAN GATE)

**Author:** ops-planner (RO), mode = RECONCILIATION · **Stage:** DR-1 build pipeline, stage 5 (final plan)
**Repo @ main** · Reconciles `planner-01-initial` + `planner-02-adversarial` over the ratified
`architect-03-reconciliation`. **Plan only — no build.** Every commit is `coder → reviewer → commit`,
identity-safe, additive, guard-green (`scripts/check-no-content.sh` exit 0) at each step.

I re-verified the adversarial's three load-bearing code facts against `main` before reconciling — all three
CONFIRMED — and found one decisive change of state and one nuance neither report had:

- **STATE CHANGE (updates the plan):** the C-3 / GAP-9 workspace-name **resolve-and-contain** containment fix
  has ALREADY LANDED on `main` (`pipeline/workspace_name.py`, wired at `invoke.py:335-356`, commit
  `2f29e88`, `known-issues.md` §GAP-9 "RESOLVED 2026-07-23"). The initial plan's "EXTERNAL PRECONDITION …
  being built SEPARATELY and lands first" is **SATISFIED**. known-issues even records that the served-
  workspace **allow-list is "the deferred DR-1 shim's POLICY layer, distinct from this framework
  containment."** → DR-1 Commit 5c adds ONLY the allow-list policy; the GAP-9 gate is closed.
- **NUANCE (sharpens H3):** transport-return-not-raise is **verb-asymmetric.** For `generate-next` a
  transport timeout is a RETURNED coded block (driver carries it as a result). For `render`, `mint_fit`
  CONVERTS a non-ok reconcile (incl. a transport-carried timeout) into a **RAISED `_EngineError`**
  (`render.py:568-571`), and `invoke()` has no dispatch-level catch (`invoke.py:387`; render's own
  `try/except` at `:193/:224` catch only `FitResolutionError`/`SerializeError`), so it propagates to the
  runner. The runner must therefore do BOTH: classify RETURNED codes AND catch the genuine raiser set.

---

## (A) H1 / H2 / H3 — two-line resolution each + verification result

### Verification of the three facts (repo @ main)

- **Fact 1 (render acquires NO claim) — CONFIRMED.** `render.py:205` / `:236` are bare
  `if …should_mint and not is_done(...)` check-then-mint; grep of `render.py` for
  `acquire|claim|peek|ClaimRegistry|spine` yields only a docstring word (`:26`). `reconcile.py` has no
  acquire. `fit_resolution.claim_fit` (`:471`) and `serialize.claim_deliverable` (`:1209`) are called
  ONLY from `tests/` (`test_fit_resolution.py:323-324`, `test_serialize_revision.py:196-197`). ⇒
  `claims.peek(fitted-id|deliverable-id)` is None for the ENTIRE paid render mint.
- **Fact 2 (generate-next claims at S1) — CONFIRMED.** `session.py:572 claims = registry_for(store)` →
  `:598-601 run_artifact(..., claims=claims)` → `compose` → `spine.drive` → `spine.py:376
  claim = claims.acquire(unit.id)  # S1`. ⇒ `peek(artifact-id)` is live throughout the generate-next LLM
  window.
- **Fact 3 (transport RETURNS on timeout/backpressure) — CONFIRMED, with the verb-asymmetry above.**
  `transport._timeout_result` (`:447-462`, `code="timeout"`) and `rate-limit-backpressure` (`:498-508`)
  RETURN a `TransportResult`; `driver.py:122-125` states a transport error is "carried as a result, not
  raised." **Genuine RAISERS** (propagate out of `invoke()` to the runner): `_EngineError`
  (`render.py:714`, raised at `:568-571`/`:619` on non-ok reconcile — the render timeout path),
  `HandlerNotWired` (`invoke.py:76/386`), `ApiKeyPresentError` (`transport.py:167/222/226`),
  `BinaryNotFoundError` (`transport.py:188/291`), `DriverError` (`driver.py:122`).
- **peek semantics — CONFIRMED.** `claims.py:282-290`: `peek` returns the `ClaimRecord` **even for an
  EXPIRED lease** (no clock check — it just loads), and returns **None** for a nascent/torn claim.
  `ClaimRecord.lease_expiry` is a field (`:95`); a lease is live iff `clock() < lease_expiry`
  (module doc `:29-30`); `DEFAULT_LEASE_TTL_SECONDS = 30min` (`:77`) > 20-min transport timeout.
- **store — CONFIRMED.** `create_exclusive` RAISES `FileExistsError` on an existing target
  (`store.py:363`); `commit_new` is no-replace, raising `AlreadyMaterializedError` on an existing output
  (`:338-352`) ⇒ a double-mint is a COST leak, never a double output. `output_path` RAISES
  `StorePathError` for any non-artifact-family id (`:212-224`) ⇒ a job id can never route through
  `output_path`/`is_done`. `STORE_SUBDIRS` (`:88-96`) = artifacts/deliverables/claims/folios/reviews/
  select/output — no `jobs/`; `+= ("jobs",)` is additive and consumed only by `ensure_layout`.
- **claim_fit is ready — CONFIRMED.** `fit_resolution.claim_fit` (`:471-480`) is a thin, tested wrapper
  over `registry.acquire(resolved_fitted_id)`, its docstring: "Acquire the claim on the resolution's
  fitted-id BEFORE the expensive reconcile (§22.3) … Meaningful only when `resolution.should_mint`." It
  is DESIGNED for the live render path and merely dead there. Option A is genuinely low-effort.

### H1 — render has no claim → **Option A (wire the existing claim primitives), as a STANDALONE pre-DR-1 fix (GAP-10), like GAP-9.**
Wire `fit_resolution.claim_fit` / `serialize.claim_deliverable` around the two live render mints
(`render.py:205/236`): S1 `acquire` → mint → no-replace commit → S6 `release` (release-on-failure in a
`finally`); a `claim-held` outcome surfaces as a coded re-drivable block (mirroring `spine`'s
`claim-held`). This gives render the SAME `peek`-based RUNNING semantics as generate-next (one uniform
liveness model, no second code path) AND closes the latent CLI-door check-then-mint double-spend race —
a pre-existing framework defect DR-1 merely makes hotter (exactly the GAP-9 pattern). **Fix it standalone
(file GAP-10 now, land it before DR-1 Commit 7)**, so the DR-1 sequence stays purely additive-over-
`invoke()` and Commit 7 just RELIES on peek being true for render. Option B (runner heartbeats a job-lease,
RUNNING keys on record freshness) is shim-only, leaves the CLI race, and adds a SECOND liveness mechanism —
rejected. *(Decision #1 in §C — the A/B and standalone/DR-1 forks are the maintainer's to ratify.)*

### H2 — create-exclusive vs "re-drivable" wedge → **TTL + steal on the lossy job record, modeled on the built `claims` steal; output-existence + the S1 claim remain the exactly-once authorities.**
`submit` writes the record with `create_exclusive` (happy path: no double-spawn, N-2). On `FileExistsError`
it READS the record and branches: `is_done`→DONE; **live `peek` OR `now < record.spawn_expiry`**→return
the existing 202 (do NOT re-spawn — the legitimate 202→S1 window); **else (stale: grace expired, no live
claim, not done)**→**STEAL** via `write_replace` (reset `spawn_expiry`) → spawn → 202. This makes
"re-drivable" HONEST — a stale record is stealable, so a runner that died pre-claim after the grace
re-spawns instead of wedging. A concurrent-double-steal on an already-dead job is bounded to at-most-one-
extra-spawn (a cost leak) because the S1 claim admits one LLM run per id and `commit_new` admits one
output — never a correctness or double-output fault. **Exact lifecycle:** record write (`create_exclusive`,
`spawn_expiry = now + STARTUP_GRACE`) → spawn detached → runner acquires S1 claim (30-min TTL now the
liveness authority) → on failure-after-record the `spawn_expiry` lapses with no live claim/no output →
poll resolves FAILED-re-drivable and re-submit steals-and-respawns. Needs a NEW `STARTUP_GRACE`
constant (`opdefaults.py`, ~90-120s: must exceed observed 202→S1 latency, far below the 20-min timeout).
*(Decision #2 in §C — the maintainer prices the grace value + accepting the bounded double-spawn-on-dead-
job, which is the same cost-not-correctness posture the whole design already rests on.)*

### H3 — transport RETURNS, not raises → **the runner does BOTH: classify RETURNED codes AND catch the genuine raiser set; exception-synthesis is scoped to the raisers only.**
`generate-next`: a `timeout` / `rate-limit-backpressure` / `api-error` is a RETURNED coded block in
`results[]` (driver carries it) — the runner reads the returned codes: `timeout`→re-drivable(504),
`rate-limit-backpressure`→429/re-drivable, deterministic blocks (`empty-pool`/`out-of-window`/`drift-
block`/`hard-limit-exceeded`) un-stored (sweep re-derives, N-5). `render`: the same transport timeout
becomes reconcile-non-ok → **`mint_fit` RAISES `_EngineError`** → the runner CATCHES it (+ `HandlerNotWired`/
`ApiKeyPresentError`/`BinaryNotFoundError`/`DriverError`) and synthesizes the terminal envelope
(timeout-ish→504/re-drivable; wiring/env→terminal FAILED). **Correct C-2(b)/C-4-N-4/C-5 everywhere the plan
said "catch the exception" for a timeout** — for generate-next it is a RETURNED code (the C-5 429 backstop
reads the returned envelope code, NOT a caught exception); for render it is a raised `_EngineError`.

---

## (B) FINAL ordered commit sequence (revised)

**Guard invariance (holds at EVERY commit — adversarial-confirmed against `check-no-content.sh`):**
`jobs/` DATA is gitignored (`workspaces/*/jobs/`; a tracked leak is caught by the `workspace-content`
class, `:215-218`); `instance/shim.yaml` gitignored (a stray non-template is caught as `instance-file`,
`:213`); `instance/shim.template.yaml` is a direct-child `*.template.*` (template exemption `:207-212`).
`pipeline/ tests/ docs/ scripts/` are never scanned. Guard exit 0 throughout.

**PRECONDITIONS (not DR-1 commits):**
- **P-GAP-9 — DONE.** Workspace-name resolve-and-contain (`pipeline/workspace_name.py`, `invoke.py:335-356`,
  commit `2f29e88`). No DR-1 work; Commit 5c layers the allow-list on top.
- **P-GAP-10 — RECOMMENDED (Decision #1): file now, land before Commit 7.** Standalone framework fix wiring
  `claim_fit`/`claim_deliverable` around `render.py:205/236` (S1 acquire → mint → commit → release;
  `claim-held`→coded re-drivable block; release-in-`finally`). Own coder→reviewer→commit, like GAP-9.
  **Verify:** two concurrent identical `render` mints ⇒ one mints, the other gets `claim-held` (assert one
  `mint_fit` call); `peek(fitted-id)` is live DURING the mint (probe from a second process/thread);
  release-on-`_EngineError` leaves no dangling claim; every existing render test stays green; cache-hit /
  `should_mint=False` acquires NO claim (read-only path unchanged).

**DR-1 COMMITS:**

### Commit 1 — §21.9 AMENDMENT (constrain STATE, not process-lifetime) [C-1] — docs only, FIRST
- **Files:** `docs/design.md` (append the C-1 wording to §21.9's first bullet).
- **Order:** FIRST; no code. Authorizes the persistent HTTP front for every later commit.
- **Verify:** `grep -n "OPTIONAL transport FRONT\|no LLM/session/correctness state" docs/design.md` returns
  the text; `uv run pytest -q` unchanged-green; `ruff check .` clean; guard exit 0.

### Commit 2 — `jobs/` store subdir + boundary registration + FILENAME-SCHEME PIN [C-8]
- **Files:** `pipeline/store.py` (`STORE_SUBDIRS += ("jobs",)` + a `jobs_dir` property mirroring
  `claims_dir`), `.gitignore` (`workspaces/*/jobs/`), `docs/design.md` (§23 layout + §27.3 retention),
  `tests/test_store.py`, `tests/test_guard.py` (jobs/ leak fixture).
- **PIN (adversarial add):** a job id is NOT an artifact-family id, so `output_path`/`is_done` RAISE
  `StorePathError` on it (`store.py:212-224`). Jobs are keyed in `jobs/` by a **NON-id filename** — the
  hex digest of the sorted target-id set (or the `idempotency_key`) — and are NEVER routed through
  `output_path`. State this in the module/docstring now.
- **Order:** after 1; before 3/4.
- **Verify:** `jobs_dir` created on demand + in `ensure_layout()`; **assert `output_path(job_filename)`
  RAISES `StorePathError`** (jobs are not an output route); existing subdirs byte-identical (additive);
  guard flags a planted tracked `workspaces/x/jobs/j-…` fixture.

### Commit 3 — `pipeline/jobs.py`: lossy record + poll resolver + TTL+steal lifecycle [C-2 (a)(c)(d)(e), H2, H3-truth-table]
- **Files:** `pipeline/jobs.py` (NEW), `tests/test_jobs.py` (NEW), `pipeline/opdefaults.py`
  (`STARTUP_GRACE` constant, new).
- **Builds:**
  - `JobStore.submit(target_ids, idempotency_key, *, now)` — `create_exclusive` write; on `FileExistsError`
    apply the **H2 branch**: `is_done`→DONE; `peek` live OR `now < spawn_expiry`→existing (RUNNING, no
    re-spawn); else STEAL via `write_replace(spawn_expiry=now+STARTUP_GRACE)` and signal re-spawn.
  - `JobStore.record_terminal(...)` scoped to NONDETERMINISTIC failures only (N-5).
  - `resolve_job_state(...)` — the CORRECTED truth table (H3-adjacent): `is_done`→**DONE**; else
    **`peek(id) is not None AND now < peek(id).lease_expiry`**→**RUNNING** (peek returns expired
    records — `claims.py:289`); else **nascent-None window** (claim file exists but peek is None) OR job
    record within `spawn_expiry`→**RUNNING**; else terminal envelope→**FAILED/BLOCKED**(reason); else
    →**FAILED-re-drivable**.
- **Order:** after 2. Reuses `store.create_exclusive`/`write_replace`, `claims.peek`, `is_done`.
- **Verify (`test_jobs.py`, pure-logic, fake clock + tmp store/claims):** (a) two same-key `submit`→ONE
  record, loser sees existing (N-2); **(b-H2) runner-died-pre-claim: submit → (advance clock past
  spawn_expiry, no claim, not done) → re-submit STEALS + re-spawns (assert the second submit returns
  re-spawn, not FileExistsError-wedge and not a second spawn while within grace);** **(c-H3) `peek`
  returns an EXPIRED-lease record → resolver does NOT report RUNNING (compares lease_expiry to now); a
  nascent-None claim within grace → RUNNING (falls through to the record branch, NOT FAILED);** (d) §22.7
  lossy: record present + output absent is NEVER DONE; a deleted record still resolves re-drivable;
  (e) deterministic block → `record_terminal` stores NOTHING; nondeterministic → round-trips; (f) keys are
  the non-id target-id-set digest.

### Commit 4 — `pipeline/api/jobrunner.py`: detached runner (verb-aware failure model) + detached-spawn primitive [C-2 (b), H3, adversarial-missing #2]
- **Files:** `pipeline/api/jobrunner.py` (NEW, `python -m pipeline.api.jobrunner` entry),
  `tests/test_jobrunner.py` (NEW).
- **Builds:**
  1. **record→spawn→claim ORDERING** with an explicit **detached-spawn primitive**
     (`subprocess.Popen(..., start_new_session=True, close_fds=True)` — child outlives the shim and does
     NOT inherit the server socket; confirm the exact call at build). A spawn FAILURE after the record
     write is exactly the H2 stale-record case → the next poll/submit steals-and-respawns (tested here).
  2. calls `invoke(verb, workspace, params, token, pins, root)`.
  3. **verb-aware failure classification (H3):** classify the RETURNED envelope/`results[]` codes
     (`timeout`→504/re-drivable; `rate-limit-backpressure`→429/re-drivable; deterministic blocks→un-stored)
     AND wrap the `invoke()` call in `try/except` catching the GENUINE raiser set
     (`_EngineError`/`HandlerNotWired`/`ApiKeyPresentError`/`BinaryNotFoundError`/`DriverError`) →
     synthesize a terminal envelope. **No claim-peek-visibility is asserted for render here — that comes
     from P-GAP-10.**
  4. `record_terminal` for nondeterministic failures only.
- **Order:** after 3.
- **Verify (`test_jobrunner.py`, injected `invoke`/engine seam):** (a) clean success materializes the
  predictable id → DONE via existence, no terminal envelope; **(b-H3-generate-next) an injected invoke()
  RETURN with a `timeout` code in `results[]` → synthesized re-drivable terminal (NOT via a caught
  exception);** **(b-H3-render) an injected `_EngineError` RAISE → synthesized re-drivable terminal (via
  the catch);** (c) a deterministic block RESULT → NO terminal envelope; (d) re-entry same
  `idempotency_key` → no-op; **(e) spawn-failure-after-record leaves a stealable record (ties Commit 3
  (b-H2)).**

### Commit 5a — HTTP shim skeleton + `serve` + Tier-A dispatch + N-4 status mapping [C-4 skeleton, C-9 Tier-A]  (SPLIT)
- **Files:** `pipeline/api/http_shim.py` (NEW — stdlib `http.server.ThreadingHTTPServer`, confirm no new
  dependency at build), `scripts/pipeline` (add `serve` → `python -m pipeline.api.http_shim`),
  `tests/test_http_shim.py` (NEW).
- **Builds:** request → `register_api_handlers()` at startup → `invoke(...)` → serialize by the exit-code
  contract for the CHEAP set (`list get fetch-by-id create-folio add-to-folio emit-manifest emit-outline
  begin-session{generate=none} continue-session{status|list}`). N-4 mapping: envelope-is-authority
  (per-item block rides `results[]` at `ok=true`→200); `invalid-token` cursor→400/422 (NOT 401);
  timeout→504.
- **Order:** after 1. Independent of 2/3/4.
- **Verify:** (a) good-auth-stub + Tier-A verb → 200 + same envelope; (b) unknown verb → `unknown-verb`;
  **(c) `emit-outline` → 200 (it IS wired by `register_api_handlers`, `session.py:996`, despite being
  un-CLI-wired);** **(d) `scripts/pipeline serve --help` dispatches to the shim (assert the subcommand
  resolves);** (e) `invalid-token` cursor → 400/422 not 401; (f) per-item block → 200 with the block in
  `results[]`.

### Commit 5b — auth (fail-closed / const-time / rotation-set / redaction) + config template + DoS guard [C-4 N-7, adversarial-missing #3]  (SPLIT)
- **Files:** `pipeline/api/http_shim.py` (auth + body/socket guards), `instance/shim.template.yaml` (NEW),
  `.gitignore` (`instance/shim.yaml`), `tests/test_http_shim.py`.
- **Builds:** bearer/`X-API-Key`, constant-time, **fail-CLOSED** on a missing/empty secret (refuse to
  start), **redact** the header from all logs, accept a **SET** of secrets (rotation). **DoS guard:**
  check auth **BEFORE reading the body**, enforce a max `Content-Length` (refuse oversized pre-auth), set
  a **socket timeout** (slow-loris).
- **Order:** after 5a.
- **Verify:** (a) missing secret → refuse to start; (b) no/wrong auth → 401; (c) rotation set accepts
  old+new; (d) captured logs NEVER contain the auth header; **(e) oversized body → refused BEFORE auth-
  passed body read; (f) auth is checked before the body is consumed; (g) a stalled client hits the socket
  timeout.**

### Commit 5c — workspace allow-list (policy on the LANDED GAP-9 containment) + loopback bind [C-3 policy]  (SPLIT)
- **Files:** `pipeline/api/http_shim.py`, `tests/test_http_shim.py`, `instance/shim.template.yaml`
  (allow-list/bind placeholders).
- **Builds:** an instance-configured served-workspace SET → non-listed → 403. **The framework containment
  (GAP-9) is already enforced in `invoke()`** — this is the policy layer ONLY (do NOT duplicate the
  containment guard).
- **Order:** after 5b. **GAP-9 gate: already closed (`2f29e88`).**
- **Verify:** (a) allow-listed workspace → dispatches; (b) non-listed → 403; (c) a malformed/escaping
  workspace name is ALREADY refused by `invoke()`'s `isolation-violation` gate (assert the shim surfaces
  it, does not re-implement it); (d) default bind is 127.0.0.1.

### Commit 6 — Tier-B submit + poll over HTTP [C-2 wiring, C-9 202+poll]
- **Files:** `pipeline/api/http_shim.py` (Tier-B routes), `tests/test_http_shim.py`.
- **Builds:** submit `continue-session{generate-next}` → `JobStore.submit` (create-exclusive + H2 steal) →
  spawn detached `jobrunner` → **202 + {predictable artifact-ids}**. Poll by target-id → `resolve_job_state`
  → DONE(200+fetch) | RUNNING(202) | FAILED/BLOCKED | FAILED-re-drivable. **Poll carries the SAME auth
  gate AND the same workspace-isolation gate as submit (N-6).**
- **Order:** after 3+4+5a/b/c. `{status|list}`→Tier-A (5a); `{generate-next}`→Tier-B.
- **Verify (injected spawner — no live transport):** (a) submit → 202 + predictable ids; (b) concurrent
  double-submit → ONE spawn, same 202 (count spawns); **(c-H2) submit → runner-died-pre-claim → poll after
  grace → FAILED-re-drivable → re-submit re-spawns (not wedged);** (d) poll before/after materialization →
  202 / 200+output; (e) poll with a synthesized terminal → FAILED + reason (the RETURNED-code path, not a
  fiction); (f) cross-workspace poll (workspace-B id from an A-scoped caller) → refused (N-6); (g) poll
  without auth → 401.

### Commit I — NON-INJECTED integration harness [adversarial-missing #1 — THE central de-risk]
- **Files:** `tests/test_shim_integration.py` (NEW) + a trivial fake `claude` binary fixture (or a Tier-A
  verb); **real spawner, real `claims`, real `store`, real `invoke()`** — NO mocked spawner/claims.
- **Builds/asserts (generate-next, the machinery all 6 prior commits ride on):** (a) a DETACHED runner
  SURVIVES the shim-process exit and materializes an output; (b) a claim acquired by process **P1** is
  `peek`-visible from a DIFFERENT process **P2** (proves the cross-process RUNNING signal); (c) a REAL
  `invoke()` timeout RETURN flows through `resolve_job_state` to **re-drivable** (proves fact 3, not a
  mock).
- **Order:** after 6 — the earliest point all three facts are exercisable end-to-end. Placed here (not
  last) so nothing downstream is "green on a fiction." **Commit 7 EXTENDS this harness with the render
  assertions** (see Commit 7 verify) so render's real-substrate fact is checked the moment render lands.
- **Verify:** the three assertions above pass on the real substrate; the fake `claude` binary path is
  `live`-marker-free (deterministic, no network).

### Commit 7 — `render` optimistic-sync-≤60s-then-202 [C-6]  (RELIES on P-GAP-10)
- **Files:** `pipeline/api/http_shim.py` (render route), `tests/test_http_shim.py`,
  `tests/test_shim_integration.py` (render assertions).
- **Builds:** spawn the runner detached, WAIT ≤~60s; cache-hit / local-pandoc serialize → **200**; a fit
  mint exceeding the wait → **202 + predictable `deliverable-id`**, detached runner continues. **RELIES on
  P-GAP-10**: `peek(fitted-id|deliverable-id)` is now live during the render mint, so render uses the SAME
  peek-based RUNNING as generate-next (no render-special heartbeat).
- **Order:** after 6 + I; **GATE: P-GAP-10 landed.**
- **Verify:** (a) cache-hit (`should_mint=False` or `is_done`) → 200 within the wait, NO claim acquired;
  (b) a mint exceeding the wait → 202 + predictable `deliverable-id`, later poll → DONE; **(c, non-injected,
  extends Commit I) render mint holds a live `peek`-visible claim across processes (P-GAP-10); a render
  `_EngineError` RAISE → synthesized terminal → resolver → re-drivable;** (d) NO double mint under a
  timed-out-then-polled-then-re-submitted render (the S1 claim admits one — now TRUE for render; assert one
  `mint_fit`). **Surface at the gate (Decision #5): the ≤60s optimistic hold × `ThreadingHTTPServer`
  thread-per-request is a thread-exhaustion smell** — may argue for a shorter wait or a bounded pool.

### Commit 8 — `begin-session{generate≠none}` opt-in Tier-B [C-7]
- **Files:** `pipeline/api/http_shim.py`, `tests/test_http_shim.py`.
- **Builds:** keep `generate=none` Tier-A default; ADMIT `generate≠none` as opt-in Tier-B (202+poll,
  `idempotency_key` REQUIRED). **Token recovery is by re-submitting with IDENTICAL PARAMS reproducing the
  same `plan_hash`+`folio_id`+pinned source commits — NOT an `idempotency_key` lookup** (`token.mint` has
  no timestamp/nonce; token is a pure function of workspace/plan_hash/inputs/cursor/produced_ids/folio_id).
  Async results carry NO token.
- **Order:** after 6.
- **Verify:** (a) `generate=none` → Tier-A 200 (unchanged); (b) `generate≠none` WITHOUT `idempotency_key`
  → 400; (c) WITH key **+ identical params incl. supplied pinned `source_commit`** → re-submit yields the
  SAME session/token; **(d) note-and-test the edges: `target_folio="auto"` without `idempotency_key` mints
  a FRESH folio each call (`session.py:321-324`) → different token (so Tier-B REQUIRES the key); a moving
  source-repo HEAD between submit and recovery changes `plan_hash` → a DIFFERENT token (so token-recovery
  stability REQUIRES supplied pins);** (e) the 202-ack and poll result carry NO token.

### Commit 9 — Concurrency cap: Path A ADVISORY + returned-code 429 backstop [C-5]  (Path B DEFERRED)
- **Files:** `pipeline/api/http_shim.py`, `pipeline/api/jobrunner.py` (lease register/refresh/release
  around the runner's paid work), `tests/test_http_shim.py`.
- **Builds:** the shim reads `PresenceRegistry.live_count()` vs `opdefaults.MAX_PARALLEL_SESSIONS` (=3).
  **State it HONESTLY (adversarial): the pre-spawn `live_count` check is ADVISORY — it is racy
  (thundering-herd: N simultaneous submits all read `< cap` and all spawn; registration happens only
  after spawn).** The **always-correct bound is the `rate-limit-backpressure`→429 + `retry-after`
  backstop, read from the RETURNED envelope code (H3), NOT a caught exception.** **Path B (wire the
  `transport.invoke_headless` chokepoint so BOTH doors register) is DEFERRED** (Decision #3).
- **Order:** after 6.
- **Verify:** (a) N runners already registered at the cap → next submit 429 + retry-after (steady state);
  **(b) EXPLICITLY assert the advisory cap is best-effort — a burst may exceed it briefly (document the
  race, do not claim atomicity);** (c) a runner `rate-limit-backpressure` RETURN → 429 via the backstop
  (the real bound); (d) a released lease frees a slot; `live_count` reads only shim leases.

### Commit 10 — Docs closeout [C-4 N-3/N-4, C-9, deferrals] — docs only, LAST
- **Files:** `docs/known-issues.md` (DR-1): amend the "same-envelope" invariant to admit the 202-ack (N-3);
  document the status mapping (N-4); record the verb surface (C-9); **register GAP-10 as RESOLVED (if
  landed) and the deferrals** (webhook callback, per-caller keys, SSE, AIMD, jobs GC, C-5 Path B); flip
  DR-1 status to BUILT. `docs/design.md` — any §21 pointer note.
- **Order:** LAST.
- **Verify:** doc-only; `grep` the amended invariant + status facts; full suite + ruff + guard green.

**Where each ratified decision lands:** C-1→1 · C-2→3+4+6+I · C-3→5c (containment=landed GAP-9) ·
C-4→5a+5b+6+10 · C-5→9 (Path A advisory; Path B deferred) · C-6→7 (relies on P-GAP-10) · C-7→5a+8 ·
C-8→2 · C-9→5a+6+10. H1→P-GAP-10 · H2→3+6 · H3→4 (+ 9 backstop).

---

## (C) PLAN-GATE DECISION LIST (numbered; recommendation + one-line tradeoff)

1. **[LB] H1 render-claim — A vs B, AND standalone vs DR-1 commit.**
   **Recommend: Option A (wire `claim_fit`/`claim_deliverable`), fixed STANDALONE as GAP-10 before Commit
   7 (the GAP-9 precedent).** *Tradeoff:* A touches a framework file (`render.py`) and changes concurrent-
   render behavior from "both mint, one commit-loses" to "one mints, other claim-held" (strictly better,
   uniform with generate-next); B is shim-only but leaves the CLI double-spend race and adds a second
   liveness model. Standalone keeps the DR-1 sequence additive-over-`invoke()`; if you prefer, it can
   instead be DR-1 Commit 0 — same landing point, less clean separation.

2. **[LB] H2 job-record lifecycle — create-exclusive-only vs TTL+steal vs re-spawn.**
   **Recommend: create-exclusive for the happy path + TTL+steal on stale records (modeled on `claims`
   steal), with output-existence + the S1 claim as the exactly-once authorities; new `STARTUP_GRACE`
   ~90-120s.** *Tradeoff:* accepts a bounded at-most-one-extra-spawn on an ALREADY-dead job under a
   concurrent re-submit (a cost leak, never double output) — the only alternative that keeps "re-drivable"
   honest without wedging; create-exclusive-only wedges, unconditional re-spawn re-opens N-2.

3. **[LB] C-5 concurrency — Path A now vs also wire Path B now.**
   **Recommend: Path A ADVISORY + returned-code 429 backstop for v1; DEFER Path B (chokepoint wire).**
   *Tradeoff:* the backstop is always-correct so v1 never crashes/overspends; declining B leaves the cap
   shim-local (CLI competition unseen) — a fidelity, not correctness, gap. (This is the one fork the
   architect explicitly left open.)

4. **[m] Integration-commit placement.**
   **Recommend: Commit I right after Commit 6 (not last), extended by Commit 7 for render.** *Tradeoff:*
   one extra commit + a fake-`claude` fixture, bought against the adversarial's #1 risk (green on
   fictions); the alternative (one integration commit at the end) leaves 3-4 commits un-validated on the
   real substrate.

5. **[m] Render optimistic-hold × thread-per-request.**
   **Recommend: keep ≤60s for v1 but cap the shim thread pool / consider a shorter wait; surface as a
   build knob.** *Tradeoff:* a burst of render submits each pinning a thread ≤60s risks self-inflicted
   thread exhaustion; a bounded pool or shorter wait trades a little latency for stability.

6. **[m] Split Commit 5 into 5a/5b/5c.**
   **Recommend: yes (skeleton/Tier-A/mapping · auth+DoS · allow-list/bind).** *Tradeoff:* three smaller
   reviewable commits vs one; auth is the load-bearing net-new security surface and deserves its own gate.

7. **[m] `serve` and stdlib `http.server` sufficiency.**
   **Recommend: stdlib `ThreadingHTTPServer`, confirm request-size/socket-timeout/thread behavior at
   build (CLAUDE.md rule 8); escalate ONLY if a real dependency proves necessary.** *Tradeoff:* zero new
   dependency vs a small amount of hand-rolled request hardening (covered by Commit 5b's DoS verify).

---

## (D) Standalone render-race finding (independent of DR-1, like GAP-9)

**File GAP-10 now, regardless of DR-1's timeline.** `pipeline/api/render.py:205/236` mint a fit/deliverable
under a bare `should_mint and not is_done(...)` check-then-mint with **no claim** (grep-confirmed; the
built `fit_resolution.claim_fit`/`serialize.claim_deliverable` are called only from `tests/`). Two
concurrent identical renders (today: two CLI callers; tomorrow: a shim + a CLI) BOTH pass `not is_done`
and BOTH run the paid reshape — a double-spend. `commit_new`'s no-replace (`store.py:338-352`) prevents a
double OUTPUT, so it is a COST leak, never a correctness fault — which is exactly why it is a latent
framework defect DR-1 makes hotter, not a DR-1 bug. This mirrors GAP-9 precisely (a pre-existing invariant
gap DR-1 merely makes exploitable, fixed upstream in the framework). **Fix = Option A** (wire the existing,
tested claim primitives; §A/H1). **Maintainer choice: fix now (recommended, like GAP-9 landed 2026-07-23)
or at DR-1 build — but registered as a known-issue now either way, and it MUST land before Commit 7.**

---

## (E) Deferred / registered (recorded, not v1)

Webhook/`resumeUrl` callback (outbound-egress/SSRF); per-caller API keys / audit (v1 = one shared secret
set); SSE/streaming; AIMD width auto-tuner (already §22.5/§26-deferred); `jobs/` retention/GC tuning
(registered with §27.3); **C-5 Path B chokepoint wire** (fast-follow — Decision #3). The Execute-Command
door remains the zero-new-surface option for same-host self-hosted n8n ≤ v1.x — DR-1 does not supersede it.

## Open risks (residual)

- **P-GAP-10 gates Commit 7.** If the maintainer declines Option A / defers GAP-10, Commit 7 CANNOT use
  peek-based RUNNING for render and must fall back to H1 Option B (job-record heartbeat) — a materially
  different Commit 7. Resolve Decision #1 before build starts.
- **`STARTUP_GRACE` value (Decision #2)** must be validated against the real 202→S1 latency at build
  (spawn + handler entry + grounding/resolution + claim acquire) — a state-verifiable build measurement,
  not a design fork.
- **stdlib `http.server` request hardening** (Decision #7) — confirmable at build; escalate only a genuine
  new-dependency need.
- **Identity/additivity gates hold** (re-verified): `STORE_SUBDIRS` additive & `ensure_layout`-only;
  `KNOWN_VERBS` untouched; `register_api_handlers` wires only existing handlers (no new handler); no
  `schema_version`/`ir_version` bump; jobs keyed by a non-id filename (never `output_path`).
