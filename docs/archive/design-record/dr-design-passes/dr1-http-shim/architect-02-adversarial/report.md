# DR-1 (HTTP/webhook shim for cloud orchestrators) — ADVERSARIAL design record

**Author:** ops-architect (RO), mode = ADVERSARIAL · **Stage:** DR-1 design pipeline, stage 3 (attack the initial)
**Repo @ main** · **Attacking:** `ops-handoff/dr1-http-shim/architect-01-initial/report.md`
**Remit:** design critique only — try to BREAK the initial; no plan, no build.

---

## 0. Bottom line

The initial is **directionally sound and its file:line citations check out** — but it papers over
three load-bearing seams, and two of its "honest weak points" are worse than stated while one is
*better* than stated (it under-read its own substrate). The single most important corrections:

- **§21.9 (D-2) needs an AMENDMENT, not a gate "reinterpretation."** The letter genuinely conflicts;
  intent supports the shim; the honest, permanent fix constrains **state, not process-lifetime** — and
  that dissolves the long-running-vs-on-demand deployment fork entirely.
- **Poll correctness has a real hole the initial hand-waves** (N-1): the claim-lease dead-process
  signal covers ONLY the LLM-work window. The gap between `202` and claim-acquisition, and every
  transport-level exception (the 20-min timeout, subprocess crash, OOM — none of which produce an
  `invoke()` envelope), is a **stuck-RUNNING-forever / undefined** poll state.
- **The `render` always-Tier-B justification is unsound** (D-4): the design's fit/serialize
  resolution is an explicit **LLM-free** function (`design.md:2398-2407,2445-2465`), so "the shim
  can't predict whether a render mints" is false. The decision may survive on simplicity grounds, but
  not on the reason given.

Verification note: I independently confirmed `invoke.py:329-331` (raw workspace string → store root),
`store.py:144-151` (caller-trusted placement), `transport.py:133` (`DEFAULT_TIMEOUT_SECONDS = 20*60`)
strictly < `claims.py:77` (`DEFAULT_LEASE_TTL_SECONDS = 30*60`), the absence of any workspace-name
validator (grep of `pipeline/`+`scripts/`), the absence of a `jobs/` store subdir (`store.py:158-273`
lists artifacts/deliverables/claims/folios/reviews/select/output/manifests — no jobs), and the
§22.5 presence-lease registry as an account-wide in-flight observable (`design.md:2597-2604,2706`).
The initial's citations are accurate; my critique is about what they IMPLY, not whether they hold.

---

## 1. Per-decision verdicts (D-1 … D-8)

### D-1 — "Thin shim (Tier A) + small async layer (Tier B)" framing → **HOLDS-WITH-CHANGE**

The framing is honest and correct as far as it goes, but "thin because it rides the substrate"
survives ONLY with a qualifier the initial never states, and it mis-classifies the job record.

- **The DONE path is genuinely thin** — it collapses into id-existence (§22.7) + claim-lease
  exactly-once (`design.md:2532-2548`). Zero new correctness surface. Correct.
- **The FAILED path is an irreducible NEW subsystem, and it is a THIRD status structure.** §22.7 is
  emphatic (`design.md:2621-2626`): execution correctness is enforced **SOLELY** by (1) output
  existence + (2) the claim registry, **never** by any other status store. The initial's
  terminal-envelope job record is a new persisted status structure. It is §22.7-safe **only if
  positioned as lossy BOOKKEEPING** — like the SSOT: a lagging projection that may be lost with zero
  correctness impact (a lost failure envelope just means the poll falls back to lease-expiry →
  re-drivable). The initial never frames it this way; it must, or the poll risks treating the job
  record as a correctness authority (which would violate §22.7). The DONE path already reads
  id-existence, so the initial got the *authority* right — but it owes the explicit "§22.7-class
  bookkeeping, lossy-safe, never consulted for DONE/exactly-once" statement.
- **The job record is a NEW persisted store surface the initial listed as code, not data.**
  `store.py:158-273` has no `jobs/` subdir. A `jobs/` (or equivalent) subdir is a framework store
  addition, and its CONTENTS are **client-derived instance data** — the terminal envelope carries
  `results[]` with artifact-ids, coordinates, and human `hint` text (`design.md:2327-2329`). So it is
  workspace-scoped, gitignored, rule-2-isolated, and needs retention/GC. The initial's §5 boundary
  analysis omits this entirely (it lists config knobs, not the data surface). See D-7.
- **Net:** Tier B is "thin for success, new-subsystem-but-bookkeeping for failure." The maintainer
  must ratify that sharper statement, not "thin because it rides the substrate."

### D-2 — Bless the long-running front against §21.9 → **HOLDS-WITH-CHANGE (reinterpret → AMEND)**

This is the top target and the initial correctly flags it — but its resolution is too weak.

- **Read §21.9 in full (`design.md:2477-2479`; `transport.py:1-5`).** The section is titled "Transport
  & flags" and its whole subject is the pipeline↔MODEL transport (how the pipeline invokes headless
  Claude Code). "Not a long-running server; one synchronous invocation per verb: params + optional
  token in → results + token out" describes the pipeline's execution model — one stateless headless
  subprocess per verb, no daemon carrying conversation/session state across calls. `transport.py:5`
  quotes it in exactly that context.
- **Intent supports the shim.** §21.9 itself gates "the exact n8n→headless mechanism" as future work
  (`design.md:2482`), and known-issues DR-1 (`known-issues.md:161-181`) registers the HTTP shim as
  planned, additive, over the same `invoke()`. The design authors plainly did NOT read §21.9 as
  forbidding an HTTP front. So the initial's reinterpretation is **directionally right**.
- **BUT the LETTER conflicts, and the initial understates the shim's statefulness.** A persistent HTTP
  process holds: a listening socket, in-flight detached-runner handles, concurrency/rate-limit state,
  and (per D-1) job records. "Not a long-running server" describes *that* accurately. The initial's
  "the shim holds no LLM/session state" is true but narrow — it holds plenty of *transport/correctness-
  adjacent* state.
- **The honest fix is an AMENDMENT, not an unwritten gate-blessing.** Amend §21.9 to constrain
  **state, not process-lifetime**: *"The pipeline core is not a long-running server (one synchronous
  per-verb headless invocation, no persistent process carrying LLM/session state). An OPTIONAL
  transport front (the CLI door, or the DR-1 HTTP shim) MAY be a persistent process provided it holds
  no LLM/session/correctness state — all cross-request correctness state lives on disk (output store +
  claim/presence-lease registry), and it dispatches only to stateless per-verb invocations."* This is
  one file, permanent, and removes the ambiguity for **every future door**. A gate-record "we hereby
  bless the reinterpretation" lives only in a handoff the next reader will never find — per the
  maintainer's standing preference (simple + honest over a hidden convention), amend-and-be-explicit
  beats reinterpret-and-hope.
- **The on-demand alternative is under-argued.** The initial rejects a CGI/socket-activated shape
  because "202+poll needs a background executor surviving the response." That is wrong in spirit: the
  whole point of the id-addressed design is you DON'T hold the worker — a fully **detached** runner
  (double-fork / systemd-run) outlives the request, writes its terminal envelope + materializes ids on
  the filesystem, and exits; a later short-lived request-spawn serves the poll off id-existence + the
  durable job record + the presence-lease. That is MORE faithful to §21.9's letter (no stateful
  daemon). Its real friction is deployment-environment specificity (inetd/systemd/launchd) and that a
  thin accept-loop is *still* a persistent listener. **Which is exactly why the amendment matters:**
  once §21.9 constrains STATE not lifetime, the long-running-vs-on-demand choice becomes a deployment
  detail, not an architecture fork. The initial treats it as a fork; the amendment dissolves it.

### D-3 — 202+poll primary, sync-hold for Tier A, callback deferred → **HOLDS-WITH-CHANGE**

The transport *choice* holds (202+poll is the right primary; callback's outbound-egress/SSRF surface
justifies deferral; sync-hold for ms-scale Tier A is fine). But **poll correctness BREAKS** in two
windows the initial's "runner alive OR a live claim-lease" rule does not cover — see **N-1**. The
completeness-sweep interaction is fine and actually *helps* — see **N-5**. Verdict is
HOLDS-WITH-CHANGE only because N-1 must be closed before the poll model is sound.

### D-4 — Verb exposure + `render` always-Tier-B + `begin-session` plan-only → **BREAKS (render reason) / HOLDS-WITH-CHANGE (begin-session)**

Two sub-decisions, graded separately:

- **`render` always-Tier-B — the STATED REASON is false → BREAKS (re-justify or re-decide).** The
  initial routes ALL render through 202+poll "so the shim never guesses whether a render mints." But
  the fit-resolution (FR2, `design.md:2398-2407`) and serialize-resolution (FR7.3,
  `design.md:2445-2465`) rules are **pure, LLM-free** functions explicitly placed as "plan/coordinate
  resolution reading config + output store, never the SSOT" (`design.md:2462-2465`). A cache-hit is
  *deterministically knowable without minting*. So the premise is refuted. Worse, always-Tier-B taxes
  the **common** case: after the first render, most renders are cache hits (`already-materialized`) —
  a sub-second local pandoc serialize — yet the initial spawns a detached runner + writes a job record
  + forces a poll round-trip to do it. A cleaner design with the SAME single runner path: **spawn the
  runner detached, WAIT up to a short HTTP-safe bound (e.g. 30-60s) for it to finish; if it completes
  (cache hit) return `200` synchronously, else return `202` + the predictable `deliverable-id` and let
  the detached runner continue.** No mint-prediction, no second code path, and render idempotency-by-
  `deliverable-id` (`design.md:2381,2424-2428`) makes the timed-out-then-polled mint safe. The
  always-Tier-B decision *may* still be chosen for shim simplicity, but the gate must decide on the
  real trade (one round-trip tax on every render vs slightly more shim logic), not on a false "can't
  predict."
- **`begin-session` forced plan-only over HTTP — HOLDS-WITH-CHANGE (imprecise premise + a cost the
  initial ignores).** The design DEFAULT is already plan-only (`design.md:2314`), so this constrains
  the non-default inline-first-batch path. The initial's justification — "an async result would carry
  a token not recoverable by id" — is imprecise: `begin-session` with an `idempotency_key` is already
  retry-safe and returns the SAME session/token (`design.md:2385-2387`), so a lost async token IS
  recoverable by re-submit. The *real* (and defensible) reason is narrower: keeping `begin-session`
  synchronous keeps the async result contract **token-free** (async results are only
  id-materializations + terminal envelopes). That is a genuine simplification — but it is **not free**
  and cuts against DR-1's own purpose: it forbids compose-in-one-call (adds a round-trip) AND it
  **pushes token-forwarding onto the stateless cloud caller** — every cloud orchestrator node must now
  store and forward the token between the begin-session node and the generate-next node. For n8n
  Cloud/Make/Zapier that inter-node state is precisely the friction DR-1 exists to remove. So the
  constraint simplifies the SHIM at the cost of the CLOUD CALLER. Legitimate fork, wrong premise —
  the gate must weigh it honestly (see fork #4).
- Operator-verb structural exclusion (not in `KNOWN_VERBS`, `invoke.py:59-72,321-327`) and
  `emit-outline` as cheap Tier-A both hold.

### D-5 — Static bearer/`X-API-Key`, loopback-bind, exposure behind operator TLS → **HOLDS-WITH-CHANGE**

The mechanism is the right minimal fit and net-new is correctly identified (no caller auth today; the
session token is a cursor, not a capability gate — `design.md:2135`). Gaps to add:

- **Fail-CLOSED on a missing secret.** The initial says "auth must land before any network bind" but
  never states the default: a missing/empty secret MUST refuse to start (or bind loopback AND refuse
  all dispatch), never fail-open. Load-bearing given the paid-spend vector.
- **Secret redaction in logs + no request-body dumping.** Inherit `transport.py`'s §3.3 discipline
  ("never logs or persists the child env or the prompt text", `transport.py:8-9`): the shim must never
  log the `Authorization`/`X-API-Key` header. Named as a NEW hole (N-7).
- **Rotation story.** A single static secret with no rotation forces a hard cutover (downtime or
  broken orchestrators mid-rotation). Accept a SET of valid secrets so old+new overlap during
  rotation. Small, additive, worth naming for v1.
- **The auth gate must cover the POLL surface too** (N-6) — the initial specified it on submit/
  dispatch but the poll reads client-derived data and is currently unspecified.

### D-6 — Workspace-name traversal fix + placement → **HOLDS (gap real) / HOLDS-WITH-CHANGE (fix)**

- **Gap CONFIRMED and it is worse than "a traversal."** `invoke.py:329-331` builds the store root from
  the raw caller string: `WorkspaceStore(Path(root) / "workspaces" / workspace)`. `store.py:144-151`
  explicitly trusts caller placement. My grep of `pipeline/`+`scripts/` found **no** workspace-name
  validator (only id/token/member/scope validators). **The severity the initial understates:** the
  traversal doesn't merely reach a sibling dir — it **NEUTERS the isolation gate**. The gate
  (`invoke.py:347-356`, `_isolation_violations` over `referenced_ids`) checks that referenced ids
  resolve *inside the store root* — but the attacker just MOVED the store root with `workspace=
  "../other-client"`. The referenced ids then resolve inside the WRONG workspace and **pass** the gate.
  So the framework's stated invariant "isolation is enforced by the API, not by trust" (research §1.3)
  is **unmet for the workspace root**: the gate validates ids against a root the caller controls.
- **The framework validator is effectively MANDATORY, not defense-in-depth.** Because it corrects a
  stated-but-unmet invariant, a shim-only allow-list is a bandage over a framework hole that any future
  untrusted `invoke()` caller re-opens. Today the only doors are trusted (OS shell / in-process), so it
  is not *exploitable* yet — which is exactly why it belongs in the framework as a **standalone
  known-issue filed NOW**, independent of DR-1's timeline. If DR-1 defers again, the invariant is still
  false.
- **The fix should be resolve-and-CONTAIN, not charset-regex-alone.** The initial proposes
  `^[a-z0-9][a-z0-9._-]{0,63}$`. A charset regex is hygiene, but the load-bearing check is a
  containment assertion: `(root/"workspaces"/workspace).resolve()` MUST be a direct child of
  `(root/"workspaces").resolve()` — this catches `..`, absolute paths, and symlink escapes a charset
  cannot. Keep the charset as an early-reject nicety; make containment the correctness gate. (Note:
  the shim allow-list — an instance-configured served-workspace set — is still the right *policy* layer
  on top; it just isn't sufficient as the *only* layer.)

### D-7 — Framework/instance boundary for shim config → **HOLDS-WITH-CHANGE**

The config split (code=framework; secret/bind/allow-list/caps/TLS=instance) is correct. What is
**missing**: the **job-record DATA surface**. The terminal envelope carries client-derived content
(artifact-ids, coordinates, `hint` text — `design.md:2327-2329`), so the `jobs/` store subdir is
per-workspace, client-scoped, `provenance: instance`, gitignored, rule-2-isolated (no cross-workspace
leak), with retention/GC. The initial's boundary section treats the async layer purely as framework
code and never accounts for this persisted client data. Add it, and confirm the terminal envelope
cannot leak one workspace's `hint`/ids into another's poll response (ties to N-6).

### D-8 — Concurrency cap at ≤ `max_parallel_sessions`, backpressure→429 → **HOLDS-WITH-CHANGE (the pessimism BREAKS)**

The 429/`rate-limit-backpressure` mapping (`design.md:2594-2596`) is right and the cap is load-bearing.
But the initial's fatalism — "the true ceiling is account-wide and shared… a same-account CLI/
interactive session still competes… **the shim cannot see that**" — is **refuted by the design's own
substrate.** §22.5 defines a "**self-healing presence-lease registry** (live-lease count = account-wide
in-flight concurrency; a dead worker's lease self-expires)" living in `instance/ops/`
(`design.md:2597-2604,2706`), and it is explicitly cross-workspace: "sessions across workspaces register
in the same registry seeing only a count" (`design.md:2602`). So the account-wide truth — including
CLI/interactive competition, provided those sessions register via the same mechanism — **is observable**.
The correct enforcement point is **register-and-read the presence-lease registry**, not a shim-local
counter. That makes D-8 both thinner (delegate to the designed mechanism) and MORE correct (sees
cross-caller load). The one honest caveat is a **build dependency**: the presence-lease registry is a
§22.5 *capture* mechanism whose implementation status must be confirmed — if it is not yet built, the
shim's account-wide cap depends on building it. Either way, "the shim cannot see" is wrong; the design
provides the observable.

---

## 2. NEW findings the initial missed

### N-1 — Poll has a stuck-RUNNING / undefined window the claim-lease does NOT cover (SEVERITY: high)

The initial leans on "runner alive OR a live claim-lease" and on the timeout<lease invariant. But the
claim-lease is created **only before the LLM work** (§22.3 S1, `design.md:2532`) — the guarantee
"a timed-out call always implies a dead process an expired lease can steal" (`transport.py:129-133`)
holds **only inside the S1→S3 critical section.** Two windows escape it:

1. **Pre-claim window (202 → S1).** After the shim returns `202` and before the runner acquires the
   claim, there is: no materialized id, no claim-lease yet, no terminal envelope. If the runner dies
   here (spawn failure, OOM, crash during gate-checks/plan-resolve), the poll sees all-three-absent.
   By the initial's own "runner alive OR live lease" rule, BOTH are false — yet there is no id (not
   DONE) and no envelope (not FAILED). **Undefined → stuck RUNNING forever.**
2. **Transport-exception window.** A 20-min hard timeout, a subprocess crash, or an OOM during the LLM
   call may propagate as an EXCEPTION, not as an `invoke()` return — so there is **no `{envelope,
   results}` to store.** The initial's "the runner writes its terminal envelope" assumes `invoke()`
   returns cleanly; the ugliest failures don't. The lease DOES eventually expire here (covered), so
   this degrades to "re-drivable after ≤30 min," but the initial's terminal-envelope mechanism has a
   hole exactly where operators most want a reason.

**Fix (irreducible new machinery the initial hand-waves):** the detached runner must (a) acquire a
**spawn-time liveness lease BEFORE the claim** — reuse the §22.5 presence-lease — so the poll's
RUNNING/FAILED disambiguation keys on *that* lease, not on an in-memory PID the shim loses on restart;
and (b) **catch transport-level exceptions and synthesize a terminal envelope** (e.g. a
`rate-limit-backpressure`/timeout ResultItem) so the failure has a reason. The poll rule becomes:
id exists → DONE; else spawn-liveness-lease OR work-claim-lease live → RUNNING; else terminal envelope
present → FAILED/BLOCKED with reason; else (no id, no live lease, no envelope) → FAILED-re-drivable
(the runner died without recording anything; safe to re-submit by idempotency key). This closes the
undefined state — but it is *more* than "a small job map."

### N-2 — Concurrent double-submit from two orchestrator nodes must be create-EXCLUSIVE (SEVERITY: med)

The initial's job-handle idempotency ("keyed on the idempotency key") does not specify the write
primitive. Two orchestrator nodes firing the same `(verb, workspace, params, idempotency_key)`
CONCURRENTLY — before either job record exists — will both pass a check-then-act test and **double-
spawn**. Correctness is still safe (the claim/lease registry admits exactly one LLM run per id;
the loser gets `claim-held`/`already-materialized` — `design.md:2544-2548`), so this is a **cost leak,
not a correctness leak** — but it also yields a duplicate job handle. **Fix:** the job-record write
must use the SAME atomic **create-if-absent** primitive the claim registry uses (§22.3), not a
check-then-write. This is the third place the shim should reuse an existing primitive rather than
invent one — reinforcing that Tier B is thin only when it delegates.

### N-3 — The `202` body IS a second wire contract (the "no second contract" claim is partly false) (SEVERITY: med)

The initial asserts "No second result contract: the poll returns the same envelope." True for the
**terminal poll** — but the `202 Accepted` acknowledgment itself (`{job handle / predictable ids}`) is
a **net-new response shape** distinct from `invoke()`'s `{envelope, results, [token]}`
(`invoke.py:372-379`). The known-issues DR-1 invariant "returning the **same JSON envelope** the CLI
emits… adds **no business logic**" (`known-issues.md:168-171`) is therefore NOT literally preserved:
DR-1 introduces a 202-ack shape the CLI door never emits. This is small and defensible, but it must be
**explicitly designed and the invariant amended** ("same envelope for terminal results; plus a
202-ack shape for Tier-B admission"), not smuggled in under "no second contract."

### N-4 — HTTP-status ↔ error-tier mapping has three hazards the initial flattens (SEVERITY: med)

The initial maps "HTTP 200/4xx by the CLI's exit-code contract" (`invoke.py:418-420`). That flattening
hides three edges:

1. **`200` ≠ "all items succeeded."** A per-item BLOCK rides `results[]` at `envelope.ok=true` → CLI
   exit 0 → `200` (`invoke.py:413-416`; `design.md:2332-2334`). A cloud orchestrator that branches on
   HTTP status alone will treat a blocked/empty item as success. The outcome authority is the
   ENVELOPE, not the status — this must be documented as a first-class contract fact, because cloud
   orchestrators love to branch on status.
2. **`invalid-token` must NOT map to `401`.** There are TWO "token" concepts: the AUTH secret (whose
   failure is `401`) and the session TOKEN/cursor (a bad one is `invalid-token`, `invoke.py:333-345`,
   a domain error → `400`/`422`). Conflating them is a category error — a bad cursor is not an
   authentication failure.
3. **Transport timeout has no envelope to map** (ties to N-1) — so a `504`/re-drivable status must be
   synthesized by the runner, not derived from a (non-existent) `invoke()` return.

### N-5 — The completeness sweep already re-derives DETERMINISTIC blocks → the job record is narrower than the initial thinks (SEVERITY: low, but it makes Tier B thinner)

§22.3's completeness sweep re-resolves the plan and computes "blocked" by re-resolution: "a wave is
done when materialized ∪ blocked = expected… Blocked ≠ missing" (`design.md:2569-2572`). Deterministic
blocks — `empty-pool`, `out-of-window`, `drift-block`, `hard-limit-exceeded` — are recomputable by the
sweep with NO stored record and NO LLM. So the shim's poll can re-derive them the same way (it IS a
narrow sweep). The terminal-envelope job record is therefore needed **only for NONDETERMINISTIC runtime
failures** (backpressure, timeout, crash) that the sweep cannot re-derive. The initial's "store the
terminal `{envelope, results}`" over-scopes it. The initial should reconcile its new job record
against the sweep's existing block-visibility rather than duplicate it — and this NARROWS the
irreducible new surface (good for the thinness argument).

### N-6 — The POLL surface is a client-data read that needs auth + isolation (SEVERITY: med)

The poll (status-by-handle / by-id / `get plan-progress`) reads client-derived job records +
deliverables. The initial specified auth on submit/dispatch but never on the poll read path. Without
it, an unauthenticated party can enumerate job handles / read another workspace's terminal envelope
(client-data leak across the rule-2 isolation boundary). The poll MUST carry the same auth gate AND
the same workspace-isolation gate (`invoke.py:347-356`) as submit — a poll for workspace B's id from a
caller scoped to A must be refused, exactly like a submit.

### N-7 — Auth secret: fail-closed default, log redaction, rotation (SEVERITY: med)

(Folded into D-5.) Missing secret → refuse to start/dispatch (never fail-open); never log the auth
header or dump request bodies (inherit `transport.py` §3.3 discipline); accept a SET of valid secrets
for zero-downtime rotation.

---

## 3. The real forks the reconciliation + maintainer gate must resolve

Sharpened, honest, in priority order:

1. **§21.9 — AMEND vs REINTERPRET.** Recommend **AMEND** §21.9 to constrain STATE, not
   process-lifetime ("core is not a long-running server; an optional transport front MAY persist iff
   it holds no LLM/session/correctness state, all cross-request correctness state on disk"). The
   letter conflicts, intent supports the shim, and an amendment is the permanent one-file honest fix.
   **This subsumes the deployment-shape fork** (long-running-front vs socket-activated-CGI both conform
   once state, not lifetime, is the rule).

2. **Tier-B thinness — accept the async layer under an explicit §22.7 discipline, or rescope.** Accept
   IF: (a) the failure-envelope store is positioned as §22.7-class **lossy bookkeeping** (never
   consulted for DONE/exactly-once; a lost envelope is safe), (b) the runner takes a **spawn-time
   liveness lease** (§22.5 presence-lease) to close N-1's pre-claim/unclean-death hole, (c) the
   job-record and idempotency writes reuse the **create-exclusive** claim primitive (N-2), and (d) the
   terminal envelope is scoped to nondeterministic failures only (N-5). Decide **where the job data
   lives** — a new workspace-scoped `jobs/` store subdir (client instance data, retention/GC,
   rule-2-isolated) — and confirm it is not a new *identity* namespace (key every job by its
   predictable target id set, `design.md:2380,2412-2415`; the initial's "opaque handle when the id set
   isn't knowable" fallback appears unnecessary — for both Tier-B verbs the ids ARE knowable, so
   eliminating the opaque-handle key space collapses the record further toward id-addressing).

3. **`render` fast-path — always-Tier-B vs optimistic-sync-then-202.** The initial's "can't predict
   the mint" premise is FALSE (resolution is LLM-free, `design.md:2398-2407,2445-2465`). Decide on the
   real trade: a one-round-trip tax on EVERY render (including the common cache-hit) for maximal shim
   simplicity, vs a spawn-detached-then-wait-≤60s fast-path that serves cache-hits synchronously with
   the SAME single runner path and the same `deliverable-id` idempotency. Re-justify honestly; don't
   keep the false premise.

4. **`begin-session` plan-only-over-HTTP — shim-simplicity vs cloud-caller ergonomics.** The
   "token not recoverable by id" premise is imprecise (`idempotency_key` already makes it retry-safe,
   `design.md:2385-2387`). The real trade: a token-free async contract (simpler shim) vs
   compose-in-one-call + not pushing token-forwarding onto stateless cloud nodes (friendlier to the
   exact consumers DR-1 targets). Decide on the accurate premise.

5. **Workspace-name gap — framework resolve-and-contain fix, filed as a standalone known-issue NOW.**
   The gap NEUTERS the isolation gate (moves the store root the gate validates against), so it is a
   framework defect independent of DR-1, mandatory not defense-in-depth, and the fix is
   resolve-and-CONTAIN (catches symlink/absolute escapes) with the charset regex as hygiene and the
   instance allow-list as policy on top.

6. **Concurrency enforcement point — §22.5 presence-lease registry (account-wide) vs shim-local
   counter.** The registry is the design's account-wide observable (`design.md:2597-2604`); the shim
   should register-and-read it, not maintain a blind local counter. Confirm the registry's build
   status as a dependency.

---

## 4. What I could NOT break (fair to the initial)

- The additivity claim (same `invoke()`, same handlers, HTTP sibling of `main_cli`, no handler of its
  own) holds by construction — verified against `invoke.py:292-379,398-473`.
- Operator-verb structural exclusion via `KNOWN_VERBS` (`invoke.py:59-72,321-327`) is a real free win.
- 202+poll as the transport PRIMARY (over sync-hold and callback) is the right call for the cloud
  consumers, and the callback-egress/SSRF deferral is sound.
- Idempotency-under-retry is genuinely largely inherited (`design.md:2380-2387,2424-2428`,
  claim-lease `2532-2548`); the shim's job is to carry the key, not re-implement exactly-once — correct.
- The file:line citations I spot-checked are accurate. This was not a rubber-stamp because the
  substrate is genuinely strong; the breaks are at the seams the initial named plus N-1..N-7.
