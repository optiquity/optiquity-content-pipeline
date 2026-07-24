# DR-1 result-delivery reshape — poll hardening + webhook callback (FOCUSED design record)

**Author:** ops-architect (RO), mode = initial (focused) · **Repo @ `main` `92b70b6`** · **Design only — no plan, no build.**
**Scope:** redesign DR-1's result-delivery mechanism per the maintainer's ratified direction — a double-charge-proof
poll + an additive webhook callback — **without** the deferred compose-core "claim the writer" change (old Option A / the
GAP-11 idea; DEFERRED per the maintainer, NOT designed here).
**Grounded against built code:** `pipeline/jobs.py`, `pipeline/api/http_shim.py`, `pipeline/api/jobrunner.py`,
`pipeline/transport.py`, `pipeline/opdefaults.py`, `pipeline/claims.py` (Commit 6, `92b70b6`).

---

## 0. The one core rule this design realizes (maintainer's key insight)

If the pipeline is asked to do a job it is **already doing**, it must RECOGNIZE that (a job record within its
lifetime) and answer **"already in progress"** instead of starting a second paid run. That single recognition makes
**both** poll and webhook double-write-proof, so neither delivery mode needs the delicate compose-core claim change.
The recognition authority is the workspace-scoped `jobs/` record (§22.7-class LOSSY bookkeeping) read against a
**generous job-lifetime window** plus the built id-keyed claim/lease (`claims.peek`). No new correctness authority is
introduced: output-existence (`is_done`) and the S1 claim/lease remain the sole DONE / exactly-once authorities.

---

## 1. The reshaped poll / already-running recognition (double-write-proof, no compose-core change)

### 1.1 The bug in the Commit-6 boundary (why 120 s is wrong as the running-vs-dead line)

`resolve_job_state` (`jobs.py:231-259`) uses `STARTUP_GRACE_SECONDS` (120 s, `opdefaults.py:89`) as BOTH the
202→first-claim window AND the running-vs-dead boundary (step 3, `jobs.py:252-254`). `JobStore.submit` reuses the same
120 s as its "already in progress" window (`within_grace`, `jobs.py:437-439`). A `generate-next` job is ONE `invoke()`
call that composes a **batch** of artifacts serially/at width; the runner holds a live S1 claim (30-min lease) only on
the artifact it is *currently* composing, and there are short **no-claim gaps** (202→first-claim startup, between
artifacts, the commit tail). Once past 120 s:

- A poll for a not-yet-started target in a no-claim gap falls through to step 5 → **FAILED-redrivable** — telling a
  client to resend a job that is still legitimately running (`jobs.py:258-259`).
- Worse, a client RETRY (same idempotency key) landing in a no-claim gap past 120 s hits `submit`'s stale branch
  (`jobs.py:440-441`) → **STEAL + re-spawn = a second paid run**. This is exactly the double-charge the maintainer's
  rule forbids.

The claim-live check (`jobs.py:250-251`, `_claim_is_live`) already covers *active* paid work of arbitrary total
duration (each artifact under a live 30-min lease > the 20-min per-call timeout, `transport.py:133`). The defect is
purely that the **record-based fallback window is far too short** to cover a legitimate job's no-claim gaps.

### 1.2 The fix: one generous JOB-LIFETIME window replaces 120 s as the running-vs-dead line

Introduce **`JOB_LIFETIME_SECONDS`** in `opdefaults.py`, DERIVED from the two existing constants:

```
JOB_LIFETIME_SECONDS = WRAPPER_HARD_TIMEOUT_SECONDS + STARTUP_GRACE_SECONDS   # 1200 + 120 = 1320 s (22 min)
```

Meaning: "a job spawned less than one full paid call (20 min) + one startup window (2 min) ago, with no output and no
live claim, is presumed to be in a slow start / a no-claim gap — NOT dead." Relationship to the existing constants
(all in `opdefaults.py`): it sits ABOVE `WRAPPER_HARD_TIMEOUT_SECONDS` (a single in-flight paid call, 1200 s) and
BELOW `LEASE_TTL_SECONDS` (1800 s). Below the lease TTL is the load-bearing relationship: the **live-claim check
remains the authority** for any in-flight lease (a claim acquired late in a long batch stays live to S1+30 min, past
the record window), so the record window only ever governs the *no-claim* spans — startup and the tiny inter-artifact
gaps — which it now covers with a ~10× margin.

**STARTUP_GRACE_SECONDS is retired as a running-vs-dead boundary and folded in**: its 202→first-claim role is
subsumed by the (much larger) lifetime window. It is KEPT, narrowly, for ONE distinct job only — the §22.3
**nascent-write** race in `submit` (`jobs.py:419-430`): a `create_exclusive` names the file atomically but the content
write lands a moment later, so a racing submit may read a torn record; within a SHORT mtime-anchored grace the
incumbent submitter is presumed to be finishing the write, do-not-steal. That grace must stay SHORT (a torn record
from a crashed submitter must become stealable in seconds, not 22 min) and is therefore a SEPARATE, small constant —
NOT the job-lifetime window. Recommend renaming it to its real role (`NASCENT_RECORD_GRACE_SECONDS`, value unchanged
at 120 s or smaller) to end the double-meaning; `JobStore` gains `job_lifetime` (the running-vs-dead window) alongside
a short `nascent_grace` (the torn-write window).

### 1.3 Reshaped `resolve_job_state` truth-table (evaluated in THIS order)

```
1. is_done(target_id)                                  -> DONE            (output existence, §22.7 authority #1; unchanged, jobs.py:246-248)
2. peek(target_id) live (now < lease_expiry)           -> RUNNING         (S1 claim/lease, §22.7 authority #2; unchanged, jobs.py:249-251)
3. record.terminal is not None                         -> FAILED          (a recorded genuine failure; MOVED ABOVE the window — see below)
4. record present AND now < spawn_time + JOB_LIFETIME   -> NOT-READY       (RUNNING/"keep checking"; REPLACES the 120 s startup-grace branch)
5. else (past window, no output/claim/terminal)        -> DEAD-RESEND     (failed-redrivable; "looks dead, safe to resend")
```

**What changes vs Commit 6:**
- **Terminal check moves from step 4 to step 3** — ABOVE the lifetime window. A `record_terminal` is written by the
  runner ONLY after its single `run_job` → `invoke()` call returns/raises (`jobrunner.py:307-351`), i.e. the runner has
  EXITED. So a present terminal always means "finished with a failure," never "still running" — it must surface
  PROMPTLY, not be masked as NOT-READY for up to 22 min. This is safe against a stale terminal because a steal writes a
  FRESH record with `terminal=None` (`_steal`, `jobs.py:446-453`), so any terminal present belongs to the current
  (un-stolen) runner; steps 1/2 still mask it if output/claim appeared.
- **Step 4 (`now < spawn_time + JOB_LIFETIME`) REPLACES the old step-3 `startup_grace` branch** (`jobs.py:252-254`) —
  same shape, generous bound. This is the "NEVER emit resend while within the window" guarantee: any not-done target
  whose record is inside its lifetime resolves RUNNING/NOT-READY, never redrivable.
- **Step 5 (DEAD-RESEND) now fires ONLY past the window** — it can no longer fire for a live job in a no-claim gap.
- The four `JobState.kind` values (`done|running|failed|failed-redrivable`, `jobs.py:216`) are **UNCHANGED** — only
  the routing conditions change, so the HTTP poll mapping in `http_shim._handle_poll` (`http_shim.py:880-935`) needs
  **no change**: NOT-READY still maps `running`→202 "keep polling"; DEAD-RESEND still maps `failed-redrivable`→409
  "re-submit same key"; FAILED still maps `failed`→504/429/… via `_terminal_status_for`. Minimal blast radius.

### 1.4 Reshaped `JobStore.submit` (the anti-double-charge core)

Branch order on an existing incumbent record (replacing `jobs.py:431-441`):

```
1. all(is_done(t) for targets)                         -> DONE           (idempotent completed re-submit; unchanged, jobs.py:433-434)
2. record.terminal is not None                         -> STEAL + re-spawn   (the retry path: the runner EXITED with a failure; safe to re-drive by the same key)
3. any live claim  OR  now < spawn_time + JOB_LIFETIME  -> EXISTING       ("already in progress", NO re-spawn — the double-charge guard)
4. else (past window, no claim, no output, no terminal)-> STEAL + re-spawn   (stale/dead runner; unchanged shape, jobs.py:440-441)
```

- Branch 3 is the load-bearing recognition: `within_grace` (`jobs.py:437`) becomes `within JOB_LIFETIME` — a retry of
  a job still inside its lifetime is answered `existing` (disposition already exists, `jobs.py:206`), NO second spawn,
  NO second paid run. Idempotency-key + target-set keep the same `job_key` (`job_key`, `jobs.py:151-170`, unchanged),
  so a retry collides on one record by construction.
- Branch 2 is NEW and necessary: without it, a re-drivable failure re-submitted inside the (now 22-min) window would
  be answered `existing` and WEDGE the retry for up to 22 min. A terminaled record means the runner exited, so
  steal+re-spawn is the correct, double-charge-free retry (the S1 claim admits one LLM run per artifact-id and
  `commit_new` admits one output — a concurrent steal is a bounded COST leak, never a double output; §22.3).
- The nascent-write branch (`jobs.py:419-430`) stays on the SHORT `nascent_grace`, unchanged in intent.

**Residual, honestly stated:** a pathological long SERIAL batch that runs beyond ~22 min AND is polled/re-submitted
in a between-artifact no-claim micro-gap past the window could spawn one extra runner. This is (a) very low
probability (the gap is seconds, and a live claim covers active work), and (b) STILL not a double OUTPUT — the S1
claim + no-replace commit cap it at a one-artifact cost leak. This is the same cost-not-correctness posture the whole
jobs subsystem already rests on; eliminating it entirely would require a runner heartbeat (a second liveness
mechanism the prior planner explicitly rejected — H1 Option B) and is not worth the surface.

---

## 2. The webhook callback (net-new)

### 2.1 Where the client supplies it + what we POST

- **Submit param:** an OPTIONAL `callback_url` in `params` on a Tier-B `generate-next` submit (validated in
  `_submit_generate_next`, alongside the existing `idempotency_key`/`token` checks, `http_shim.py:711-735`). Poll
  remains ALWAYS available and is unaffected by whether a callback is set.
- **Payload (a WAKEUP, not the result):** on completion or genuine failure we POST a small self-describing JSON:

```json
{ "event": "job.done" | "job.failed",
  "job":   {"key": "<r-id>", "workspace": "<name>", "target_ids": ["<a-...>", ...]},
  "status":"done" | "failed",
  "poll":  {"path": "/poll", "method": "POST", "needs": ["workspace","key","target_ids"]},
  "code":  "<terminal code>",   // failure only
  "redrivable": true|false }    // failure only
```

  **Rationale (orthogonality):** the callback WAKES the client; the client then FETCHES the result through the same
  authenticated poll/`fetch-by-id` door (`http_shim.py:947-960`). This aligns exactly with n8n's Wait "On Webhook
  Call" / `$execution.resumeUrl` model (research §2.1/§3.4): the resume URL is hit to resume the workflow, which then
  reads the result via its next node. Keeping the callback a wakeup (not a result payload) means **one** result-
  delivery contract (the poll), no large/secret client data pushed to an outbound URL, and no second serialization
  path. (Inline-result-in-callback is a rejected default — see Decision D-2.)

### 2.2 Who delivers + retry policy

- **WHO:** the **detached runner** (`jobrunner.main`), as the final step AFTER `run_job` returns (`jobrunner.py:365`).
  It is the only component that (a) knows the job finished, (b) outlives both the 202 response and the shim process
  (`start_new_session=True`, `spawn_runner`, `jobrunner.py:238`), and (c) already holds the job/workspace context. No
  new daemon/process. `run_job` already returns a `RunOutcome` (`jobrunner.py:181-189`) that names the outcome:
  `clean`/`skip-deterministic` → `job.done`; `terminal-returned`/`terminal-raised` → `job.failed` (with the stored
  `code`/`redrivable`). `callback_url` reaches the runner via the `JobSpec` spawn file (§2.3).
- **RETRY:** bounded attempts + exponential backoff, then GIVE UP (poll is the fallback). Framework constants (NOT new
  config knobs — keep the surface small): `CALLBACK_MAX_ATTEMPTS = 3`, backoff `~1s, 4s, 16s` (total bounded ≈ 20 s),
  a per-attempt connect/read timeout (~10 s). A 2xx = delivered; any non-2xx / connection error / timeout retries then
  stops. **Record delivery status in the job record** (`callback_status ∈ {pending, delivered, failed, skipped}`) as
  §22.7-class LOSSY bookkeeping (a lost status just means the client falls back to poll). Blocking the detached runner
  up to ~20 s is fine — it is a background process whose only remaining task is this delivery, then exit.
- **Un-caught runner crash → NO callback** (the process died before delivery). That is acceptable and by design: the
  always-available poll is the floor — the client's poll hits the DEAD-RESEND path past the lifetime window (§1.3
  step 5). The webhook is strictly additive over the poll floor; it is never the sole delivery path.
- **Transport:** stdlib `urllib.request` (confirmed: NO outbound-HTTP client exists in `pipeline/` today — the shim's
  zero-new-dependency posture holds). **Do NOT follow redirects** (a 3xx to an internal host is an SSRF bypass) — treat
  a 3xx as a non-2xx delivery outcome.

### 2.3 SECURITY — the load-bearing part (why this was originally deferred): allow-list + SSRF guard

Both are validated at **SUBMIT time → 400 before any spawn or paid run**, and BOTH must pass (defense in depth):

**(a) Operator allow-list of approved callback hosts** (instance-config, sibling of the workspace allow-list).
`instance/shim.yaml` gains `callbacks.allowed_hosts` (a `frozenset[str]` of `host` or `host:port`), loaded into
`ShimConfig` by `load_shim_config` exactly like `allowed_workspaces` (`http_shim.py:315-321`), `provenance: instance`,
gitignored. **OPT-IN / fail-closed default:** if the allow-list is UNSET/empty, callbacks are **DISABLED** — a submit
carrying `callback_url` is refused **400** (`callbacks-not-enabled`). (This differs deliberately from the workspace
allow-list's unset=serve-any default: outbound egress is a higher-risk surface, so the safe default is off, and the
operator must consciously name their n8n/orchestrator host.) A host allow-list (not full-URL) is the right grain: n8n
resume URLs carry a dynamic execution-id path segment, so host+optional-port membership matches "the operator's
orchestrator" cleanly.

**(b) SSRF guard** (independent of the allow-list). At submit, reject the `callback_url` **400**
(`callback-url-rejected`) unless ALL hold:
- scheme ∈ {`http`, `https`} only (reject `file:`/`gopher:`/`ftp:`/… and schemeless);
- no credentials in the URL (`user:pass@host`);
- every address the host resolves to (`socket.getaddrinfo`) is a **global** address — reject if ANY resolved IP is
  loopback (127/8, ::1), link-local (169.254/16 incl. the 169.254.169.254 cloud-metadata address, fe80::/10), private
  (10/8, 172.16/12, 192.168/16, fc00::/7 unique-local), unspecified (0.0.0.0, ::), multicast, or reserved. Use stdlib
  `ipaddress` classification (`is_global` false → reject); `ipaddress`/`socket` are not yet imported in `pipeline/`, so
  this adds only stdlib, no new dependency.
- **DNS-rebinding / TOCTOU:** submit resolves-and-validates for fast 400 feedback; the **delivery step in the runner
  RE-VALIDATES at connect time** (the authority), refusing if the host now resolves to a non-global address, and does
  not follow redirects. (Hardening option, D-3: pin the submit-resolved global IP and connect to it with an explicit
  `Host` header — stronger against rebinding, more code.)

Placement: a small PURE `pipeline/callback_policy.py` (`validate_callback_url(url, allowed_hosts) -> ok | reason`) —
unit-testable with no sockets by injecting the resolver, mirroring how `jobs.py` injects `is_done`/`peek`. The shim
calls it at submit; the runner calls it (with a live resolver) at delivery.

### 2.4 Coexistence

The webhook is purely additive. The poll is ALWAYS available (even with a callback set); a failed/undelivered callback
degrades to poll with no correctness impact. The 202 ack (`_accepted_body`, `http_shim.py:465-473`) gains an optional
`"callback": {"registered": true}` note so the client knows to expect a POST — but the poll `needs` block still ships,
so a client can always poll. The poll and the webhook read the SAME job record and the SAME §22.7 authorities.

---

## 3. Data + config deltas

- **`JobRecord`** (`jobs.py:187-197`) gains `callback_url: str | None = None` and `callback_status: str | None = None`.
  `_record_bytes` / `_parse_record` (`jobs.py:267-328`) serialize/parse them lossily (absent → None), same discipline
  as `terminal`. `submit` threads `callback_url` into the `fresh` record (`jobs.py:399-405`); the runner updates
  `callback_status` via a small `record_callback_status(key, status)` helper (mirrors `record_terminal`,
  `jobs.py:455-474`, `write_replace` a lossy update).
- **`JobSpec`** (`jobrunner.py:126-160`) gains `callback_url: str | None = None`; `as_json`/`from_json`
  (`jobrunner.py:147-178`) carry it. Transient invocation input — no identity.
- **`ShimConfig`** (`http_shim.py:241-262`) gains `allowed_callback_hosts: frozenset[str] = frozenset()`;
  `load_shim_config` (`http_shim.py:265-347`) parses `callbacks.allowed_hosts`; `instance/shim.template.yaml` documents
  it (framework deliverable). Retry/backoff/timeout are framework constants (`opdefaults.py`), NOT config, to keep the
  knob surface minimal.
- **`opdefaults.py`** gains `JOB_LIFETIME_SECONDS` (derived, §1.2) and the callback constants
  (`CALLBACK_MAX_ATTEMPTS`, backoff base, per-attempt timeout); `STARTUP_GRACE_SECONDS` is repurposed/renamed to the
  nascent-write role.
- **`schema_version` / `ir_version`: NO bump — confirmed.** The `jobs.py` module docstring already pins this
  (`jobs.py:13-14`: "Job records are §22.7-class LOSSY bookkeeping, NOT identity: deliberately NO
  schema_version/ir_version bump"); the `jobrunner` docstring pins the same for the spawn spec (`jobrunner.py:56-58`).
  `callback_url`/`callback_status` are more lossy bookkeeping on the same records — no artifact-id preimage, no IR
  field, no registry `_schema.yaml`. The version-equality lints stay green untouched.

---

## 4. What of the built Commit 6 stays vs is reworked, and where the runner-registration fix lands

**STAYS (untouched):** `job_key` (`jobs.py:151-170`); the create-exclusive happy path (`jobs.py:407-414`); `_steal`
(`jobs.py:446-453`); `record_terminal`'s nondeterministic-only N-5 discipline (`jobs.py:455-474`); the poll
authorities #1/#2 order (steps 1-2); the four `JobState.kind` values and the HTTP poll/submit mapping
(`http_shim._handle_poll` `:880-935`, dispositions `:786-812`); the auth / workspace-allow-list / isolation / DoS
gates (`http_shim.py:586-660`); the 202-ack shape (`:465-473`); the `fetch-by-id` result path (`:947-960`); the
detached-spawn primitive (`spawn_runner`, `jobrunner.py:207-246`); the Tier-A/Tier-B classification
(`classify_verb`, `:369-384`); the GAP-9 containment delegation (`_open_workspace`, `:421-439`).

**REWORKED:**
- `resolve_job_state` — reorder terminal above the window; `startup_grace` param → `job_lifetime`; step 5 gated on
  past-window (`jobs.py:231-259`).
- `JobStore.submit` — `within_grace` → `within JOB_LIFETIME`; add the terminal→steal retry branch; keep the short
  nascent grace (`jobs.py:431-441`, `419-430`); `JobStore` field split into `job_lifetime` + `nascent_grace`
  (`jobs.py:345-346`).
- `JobRecord` + (de)serialization + `JobSpec` — add the two callback fields (§3).
- `jobrunner.run_job`/`main` — add callback delivery after `run_job` (§2.2), with connect-time SSRF re-check + retry.
- `http_shim._submit_generate_next` — validate `callback_url` (allow-list + SSRF) → 400; thread it into the record +
  `JobSpec` (`http_shim.py:698-812`).
- `ShimConfig`/`load_shim_config`/`shim.template.yaml`/`opdefaults.py` — config + constants (§3).

**The runner-handler-registration fix (fold in here):** `jobrunner.main()` (`jobrunner.py:354-368`) never calls
`register_api_handlers()`, so a detached runner is a FRESH process with an EMPTY handler registry — its
`run_job → invoke()` (`jobrunner.py:321`) raises `HandlerNotWired`, caught by `_RAISER_SET` (`jobrunner.py:112-118`)
and recorded as a `runner-failed` terminal. **Tier-B is therefore inert in production today** (every real
`generate-next` job fails with a wiring terminal; the injected-seam unit tests never exercised `main()`). Fix: in
`main()`, before `run_job(spec)`, add the function-scoped `from pipeline.api.session import register_api_handlers;
register_api_handlers()` — the exact pattern `serve()` uses (`http_shim.py:1092-1097`). One place, mirrors the shim.
This is a prerequisite for ANY Tier-B result delivery (poll OR webhook) to work end-to-end; it belongs with this
rework and must be covered by a NON-injected test that drives the real `main()` entry point (the gap that let it ship
inert).

---

## 5. Orthogonality / boundary

- **Still framework transport code.** The shim + jobs + runner + the new `callback_policy` + callback delivery are
  `provenance: framework` (the public deliverable). No business/LLM logic added — the runner still re-enters the same
  `invoke()` door; the callback is a transport notification.
- **No new content identity.** Jobs and callback fields are §22.7-class lossy bookkeeping; no `artifact-id` preimage,
  no IR field, no `schema_version`/`ir_version` bump (§3, grounded `jobs.py:13-14`, `jobrunner.py:56-58`).
- **Instance-scoped config.** The callback allow-list joins the secret / workspace-allow-list / bind as
  `provenance: instance` (gitignored `instance/shim.yaml`); the template is framework. Per-request `callback_url` is
  client-supplied but gated by the instance allow-list + SSRF guard.
- **The callback is the ONLY new outbound network surface — kept tightly bounded:** opt-in (disabled unless the
  operator sets an allow-list), allow-list + SSRF double-gate validated at submit (400 before spend) and re-validated
  at delivery, no redirects, bounded retries, a wakeup-only payload (no client data pushed outbound by default), and
  stdlib-only (no new dependency). The poll floor is unchanged and always available.

---

## 6. Genuine decisions the maintainer must still make (with recommendations)

- **D-1 [LB] — `JOB_LIFETIME_SECONDS` value.** *Recommend:* `WRAPPER_HARD_TIMEOUT_SECONDS + STARTUP_GRACE_SECONDS =
  1320 s (22 min)` — derived from existing constants, above one paid call, below the 30-min lease TTL. *Trade-off:* a
  larger value makes a genuinely-dead poll-only job wait longer before "safe to resend"; a smaller value re-opens the
  no-claim-gap double-charge. 22 min is the honest floor that covers a slow start with margin.
- **D-2 [LB] — Callback payload: wakeup-only vs inline result.** *Recommend:* wakeup-only (client fetches via the
  authenticated poll). *Trade-off:* inline saves one round-trip but pushes possibly-large/secret client data to an
  outbound URL and forks the result contract; wakeup-only keeps one result door and a minimal egress surface.
- **D-3 [LB] — SSRF robustness: re-validate-at-delivery vs pin-the-resolved-IP.** *Recommend:* re-validate at delivery
  + no redirects for v1; register IP-pinning (connect to the submit-resolved global IP with an explicit Host header)
  as a hardening follow-up. *Trade-off:* pinning is strictly stronger against DNS rebinding but is more code; re-
  validate + no-redirects closes the common vectors.
- **D-4 [m] — Callback allow-list default.** *Recommend:* OPT-IN / fail-closed (unset ⇒ callbacks disabled ⇒ 400 on a
  `callback_url`). *Trade-off:* stricter than the workspace allow-list's unset=serve-any, but outbound egress warrants
  the safer default; the operator names their orchestrator host once.
- **D-5 [m] — Rename `STARTUP_GRACE_SECONDS` → `NASCENT_RECORD_GRACE_SECONDS`.** *Recommend:* yes — it now serves only
  the torn-write race, and the double-meaning (startup vs running-vs-dead) is exactly what caused the Commit-6 defect.
  *Trade-off:* a touch of churn across `opdefaults`/`jobs.py` for a clearer, single-purpose constant.
- **D-6 [m] — Where the runner-registration fix lands.** *Recommend:* fold into this rework (it gates all Tier-B
  delivery) with a non-injected `main()` test. *Trade-off:* could be a standalone one-line hotfix first; either way it
  must precede any real poll/webhook validation.

---

## 7. Sources (verified this pass, repo @ `main` `92b70b6`)

- `pipeline/jobs.py` — `resolve_job_state` truth-table (231-259), `submit` H2 + `within_grace` (380-444, 437),
  `_steal` (446-453), nascent window (419-430), `record_terminal` N-5 (455-474), `JobRecord` (187-197),
  (de)serialization (267-328), no-version-bump pin (13-14), `job_key` (151-170).
- `pipeline/opdefaults.py` — `STARTUP_GRACE_SECONDS=120` (84-89), `WRAPPER_HARD_TIMEOUT_SECONDS=1200` (74-76),
  `LEASE_TTL_SECONDS=1800` (71-72).
- `pipeline/api/jobrunner.py` — `main()` MISSING `register_api_handlers` (354-368), `run_job` single `invoke()`
  (307-351), `_RAISER_SET` incl. `HandlerNotWired` (112-118), `spawn_runner` detach (207-246), `JobSpec`
  (126-178), `RunOutcome` (181-189), no-version-bump pin (56-58).
- `pipeline/api/http_shim.py` — `_submit_generate_next` (698-812), `_handle_poll` mapping (814-935), `_accepted_body`
  (465-473), `_fetch_outputs` (947-960), `ShimConfig` (241-262) + `load_shim_config` allow-list parse (315-321),
  `serve` registers handlers (1092-1097), auth/allow-list/isolation/DoS gates (586-660).
- `pipeline/transport.py` — `DEFAULT_TIMEOUT_SECONDS` 20 min (133).
- `pipeline/claims.py` — `peek` returns expired records; live iff now < lease_expiry (282-290).
- `docs/design.md` — §21.9 amendment "OPTIONAL transport FRONT … no LLM/session/correctness state" (2481-2482).
- Research `research-01/report.md` — n8n Wait "On Webhook Call" / `$execution.resumeUrl` (§2.1, §3.4); outbound-egress/
  SSRF was the reason the webhook was originally deferred (reconciliation §D; planner §E).
- Confirmed: no outbound-HTTP client and no `ipaddress`/`socket` import exists in `pipeline/` today (stdlib-only fit).
