# DR-1 (HTTP/webhook shim for cloud orchestrators) — RECONCILED design record

**Author:** ops-architect (RO), mode = RECONCILIATION · **Stage:** DR-1 design pipeline, stage 4 (settle for the maintainer gate)
**Repo @ main** · **Reconciles:** `architect-01-initial/report.md` + `architect-02-adversarial/report.md` over `research-01/report.md`
**Remit:** design only — no plan, no build. This is the last pass before the maintainer sees it; open forks are minimized.

---

## A. The settled design in brief

DR-1 is a **new framework transport process** — the HTTP sibling of `main_cli` — that imports `invoke()`,
wires the exact existing handlers (no handler of its own, no business logic), and serves the closed
`KNOWN_VERBS` set over HTTP for the cloud orchestrators (n8n Cloud / Make / Zapier / Google) that cannot
shell the CLI door. It is **two things, and the gate must be told both**:

1. **A literal thin shim over `invoke()` for the CHEAP verbs, served synchronously** (Tier A): `list`,
   `get`, `fetch-by-id`, `create-folio`, `add-to-folio`, `emit-manifest`, `emit-outline`, `render` on a
   cache-hit, and `begin-session` (plan-only). Request → `invoke(verb, workspace, params, token, pins,
   root=<pinned>)` → serialize the returned dict → HTTP by the CLI exit-code contract.

2. **A small BUT real jobs subsystem for the PAID (≤20-min LLM) verbs, served 202-Accepted + poll-by-id**
   (Tier B): `continue-session{generate-next}`, `begin-session{generate≠none}` (opt-in), and any `render`
   that mints a fit. It is thin **only because it delegates all correctness to the built substrate** —
   content-addressed output existence (§22.7 authority #1) and the id-keyed claim/lease registry (§22.7
   authority #2, `pipeline/claims.py`, BUILT). Its own state — a workspace-scoped `jobs/` record — is
   positioned as **§22.7-class LOSSY bookkeeping** (like the SSOT: a lagging projection, never consulted
   for DONE/exactly-once; a lost job record degrades to lease-expiry re-drive, never to a correctness
   fault).

**The spine that makes Tier B thin (all verified against built code):**
- **DONE** is `is_done(store, target-id)` — output existence, the §22.7 authority. The runner materializes
  the **predictable** target-id (`deliverable-id` for render; the plan's settled `artifact-id`s for
  generate-next), so every Tier-B job is keyed by its predictable target-id set — **no opaque-handle
  keyspace** (the initial's opaque-handle fallback is unnecessary; both Tier-B verbs have knowable ids).
- **RUNNING** is disambiguated by the **id-keyed claim registry** `ClaimRegistry.peek(target-id)`
  (`claims.py:282`, built for exactly "polls by id") for the LLM critical section, plus the shim's own
  create-exclusive job record within a short **startup grace** for the pre-claim window (see V-B / N-1).
- **FAILED/BLOCKED** for **nondeterministic** failures only (backpressure, timeout, crash) rides the
  stored terminal envelope; **deterministic** blocks (`empty-pool`, `out-of-window`, `drift-block`,
  `hard-limit-exceeded`) need **no** record — the completeness sweep re-derives them (§22.3, N-5). This
  narrows the new surface.
- **Idempotency** under HTTP retry is inherited (`generate-next` by artifact-id; `render` by
  deliverable-id; `idempotency_key` for begin-session/create-folio; the claim registry admits exactly one
  LLM run per id — a double-steal is a cost leak, never a correctness leak). The shim's only additions are
  a **create-exclusive** job/idempotency write (N-2) so concurrent double-submits don't double-spawn.

**Security (net-new, load-bearing, not optional):** a static bearer / `X-API-Key` header (constant-time,
**fail-closed** on a missing secret, accept a **set** of secrets for rotation, redact the header from logs)
gating **both submit AND poll**; the poll also re-runs the **workspace-isolation gate** (it reads
client-derived data); loopback-bind by default (network exposure only behind operator TLS/proxy); a
concurrency cap enforced against the **built account-wide presence-lease registry** with
`rate-limit-backpressure`→HTTP 429; and — **independently of DR-1** — the framework **workspace-name
containment fix** that closes a currently-latent isolation-gate bypass (V-A / D-6 / §E).

**§21.9 is resolved by a one-line AMENDMENT** (constrain STATE, not process-lifetime), not an unwritten
gate-blessing — which also dissolves the long-running-vs-on-demand deployment fork.

**Boundary:** the shim module + jobs mechanism + verb policy + workspace-containment validator are
`provenance: framework` (the public deliverable); the secret/bind/allow-list/caps/TLS **and the `jobs/`
DATA** are `provenance: instance` (gitignored, per-deployment). No new axis, no new content-identity
surface, no second code path.

---

## B. The two verification results (I did not take either report's word)

### V-A — Is the §22.5 presence-lease / claim-lease registry actually BUILT? **YES — both are built and unit-tested. But they are TWO DIFFERENT registries, and the adversarial conflated them.**

- **Claim/lease registry — BUILT.** `pipeline/claims.py` `ClaimRegistry`, tested `tests/test_claims.py`.
  Scope: **WORKSPACE-scoped** (`claims_dir` = `WorkspaceStore.claims_dir`, i.e. `<workspace>/claims/`).
  Keying: **id-keyed** — the filename IS the claimed target-id IS the lock (§13.3). API: `acquire(id)`,
  `release(id)` (holder-checked), and crucially **`peek(id) -> ClaimRecord | None`** (`claims.py:282`,
  docstring: "polls by id"). TTL `DEFAULT_LEASE_TTL_SECONDS = 30min` (`claims.py:77`) > the 20-min
  transport timeout (`transport.py:129-133`) — the dead-process invariant holds. Acquired at **S1**
  (§22.7 crash-safety ordering, `design.md:2634-2639`: S1 acquire → S2 work → S3 commit → S6 release),
  so it is live throughout the LLM critical section. **This is the correct per-job liveness primitive.**
- **Presence-lease registry — BUILT.** `pipeline/telemetry.py` `PresenceRegistry`, tested
  `tests/test_telemetry.py`. Scope: **ACCOUNT-WIDE** (`ops_dir` = `instance/ops/presence`, cross-workspace).
  Keying: **CONTENT-FREE / COUNT-ONLY** — a lease filename is a random opaque token (never a workspace or
  id), content a single `lease_expiry`. API: `register() -> PresenceLease`, `refresh`, `release`, and
  **`live_count() -> int`** (= account-wide count of non-expired leases). This is the correct account-wide
  **concurrency** observable — and it can be registered+read by a shim.
- **THE WIRING GAP (neither report caught this precisely).** Grep of `pipeline/` + `scripts/`:
  `PresenceRegistry.register()` / `live_count()` are **NOT called anywhere in the live compose/session/
  driver path.** Only `recommend_width` — which reads the telemetry *log's backpressure records*, a
  different structure — is wired into `begin-session` (`session.py:171`). So the account-wide in-flight
  COUNTER exists and is tested, but **nothing registers into it yet.** A shim that calls `live_count()`
  today would see only leases **it itself** registers — NOT concurrent CLI/interactive compose.

**Consequences (this splits cleanly across the two adversarial claims):**
- **D-8 (concurrency):** the presence registry IS the designed account-wide observable and IS built —
  refuting the initial's "the shim cannot see" fatalism **in principle**. But the adversarial **overstated
  readiness**: it is not wired into the live path, so seeing cross-caller (CLI) competition requires
  wiring presence-**registration** at the shared paid-call chokepoint. → **Adopt** register-and-read
  presence for the cap; **name the build dependency**; keep backpressure→429 as the always-correct
  backstop.
- **N-1 (poll liveness):** the adversarial's fix — "reuse the §22.5 **presence-lease** as a spawn-time
  liveness lease keyed to the job" — is **imprecise and would not work as written**: the presence-lease is
  count-only and **cannot attribute liveness to a specific job/id.** The correct per-job liveness primitive
  is the **id-keyed CLAIM registry** `peek(target-id)` (built). The pre-claim window (202→S1) — where the
  claim does not yet exist — is covered instead by the shim's **create-exclusive job record + a short
  startup grace**, and the ugliest transport failures (timeout/OOM/crash that raise instead of returning
  an envelope) by the runner **catching the exception and synthesizing a terminal envelope**. The HOLE
  the adversarial found is real; its named FIX needed this correction.

### V-B — Is `render` fit-resolution (FR2) + serialize-resolution (FR7.3) genuinely LLM-FREE? **YES — definitively. The adversarial is right; the initial's "can't predict the mint" premise is FALSE.**

- `pipeline/fit_resolution.py` is "**PURE plan/coordinate resolution**" that reads config + output store +
  claim registry and "**NEVER the SSOT**," carrying "**NO fit internals (no reshape, no gate, no fidelity
  check**)" — the expensive reshape is elsewhere.
- In `pipeline/api/render.py` the flow is explicit: compute preimage (LLM-free) → `fit_resolution.
  resolve_fit` / `resolve_force_reconcile` (LLM-free) yields `fit_res.should_mint` + `fit_res.disposition`
  → **the engine mint (the paid LLM reshape) is called ONLY at `render.py:205`:
  `if fit_res.should_mint and not is_done(ctx.store, fitted_id):`.** Serialize is the same shape
  (`serialize.resolve_deliverable` → `ser_res.should_mint` gates a **local pandoc** serialize at line 236
  — not even an LLM call).
- **Therefore post-resolution a runner/shim deterministically KNOWS whether the paid reshape will fire**
  (`fit_res.should_mint`). "The shim can't predict whether a render mints" is refuted. → **D-4-render:
  drop always-Tier-B's stated justification; adopt optimistic-sync-then-202.**

---

## C. Decisions the maintainer must ratify (numbered; single recommendation + one-line tradeoff)

> Load-bearing = **[LB]**; minor = **[m]**. Where I leave a fork open I say exactly why it needs you.

### C-1 [LB] — §21.9 "not a long-running server": AMEND, do not reinterpret. *(settles D-2)*
**Recommend:** ratify a one-line design.md amendment that constrains **STATE, not process-lifetime**.
A gate-record "we bless the reinterpretation" is a non-transferable convention the next reader never finds
(cuts against your standing simple+honest-over-hidden-convention preference); one amended line is permanent
and settles it for **every** future door. This also **dissolves the long-running-vs-on-demand deployment
fork** — once STATE (not lifetime) is the rule, both a persistent front and a socket-activated/detached
shape conform, so it becomes a deployment detail, not an architecture fork.
**Proposed amendment text (you ratify wording), appended to §21.9's first bullet:**

> *"The pipeline CORE is not a long-running server: one synchronous per-verb headless invocation, no
> persistent process carrying LLM/session state across calls. An OPTIONAL transport FRONT (the CLI door,
> or the DR-1 HTTP shim) MAY be a persistent process, provided it holds no LLM/session/correctness state —
> all cross-request correctness state lives on disk (the content-addressed output store + the claim/
> presence-lease registries) and the front dispatches only to stateless per-verb invocations."*

*Tradeoff:* touches a HARD-worded design rule (needs your ratification) — but the letter genuinely
conflicts today and intent already registered the shim (`known-issues.md`), so amend-and-be-explicit is
the honest fix.

### C-2 [LB] — Frame Tier B to the gate as "a small but REAL jobs subsystem, thin by delegation," under an explicit §22.7 discipline. *(settles D-1; folds N-1, N-2, N-5)*
**Recommend:** accept the async layer **only** under all five disciplines, and tell the gate it is a jobs
subsystem (not "just a thin shim"):
  (a) the failure/job record is **§22.7-class LOSSY bookkeeping** — never consulted for DONE or
      exactly-once; a lost record falls back to lease-expiry → re-drivable;
  (b) **RUNNING** keys on the id-keyed claim `peek(target-id)` for the LLM window + the shim's
      create-exclusive job record within a **short startup grace** for the pre-claim (202→S1) window;
      the runner **catches transport exceptions and synthesizes a terminal envelope** (closes N-1's
      stuck-RUNNING/undefined state — the corrected fix per V-A, NOT the count-only presence-lease);
  (c) the job/idempotency write uses the **create-exclusive** G1 primitive (`store.create_exclusive`),
      not check-then-write, so concurrent double-submits can't double-spawn (N-2 — a cost leak at worst,
      never correctness);
  (d) the terminal envelope is scoped to **NONDETERMINISTIC** failures only; deterministic blocks are
      re-derived by the completeness sweep, un-stored (N-5 — narrows the surface);
  (e) jobs are keyed by the **predictable target-id set** — **kill the opaque-handle keyspace** (both
      Tier-B verbs have knowable ids).
The poll rule becomes: `is_done(target-id)` → **DONE** (fetch); else claim `peek` live → **RUNNING**;
else job record within startup grace → **RUNNING**; else terminal envelope present → **FAILED/BLOCKED**
(reason); else → **FAILED-re-drivable** (safe re-submit by idempotency_key).
*Tradeoff:* honest and larger than the known-issues "thin shim over invoke()" wording — but every piece
delegates to a **built** primitive (`claims.peek`, `create_exclusive`, the sweep), so it adds no new
correctness path. The genuinely-thinner alternative (Tier-A only, no compose over HTTP) guts DR-1's purpose.

### C-3 [LB] — Workspace-name gap: file as a STANDALONE known-issue NOW, fix by resolve-and-CONTAIN. *(settles D-6; = §E)*
**Recommend:** confirm this is a **framework defect independent of DR-1** and MANDATORY (not
defense-in-depth), and file it as its own known-issue immediately. `invoke.py:329-331` builds the store
root from the raw caller string (`WorkspaceStore(Path(root)/"workspaces"/workspace)`); `store.py:144-151`
trusts caller placement; grep confirms **no** workspace-name validator exists. The severity the initial
understated and the adversarial got right: `workspace="../other-client"` **NEUTERS the isolation gate** —
`invoke.py:347-356` validates referenced ids against a store root the attacker just MOVED, so the ids
resolve inside the wrong workspace and **pass**. The stated invariant "isolation is enforced by the API,
not by trust" is currently **false for the workspace root**. Fix = **resolve-and-contain**:
`(root/"workspaces"/workspace).resolve()` MUST be a direct child of `(root/"workspaces").resolve()`
(catches `..`, absolute paths, symlink escapes — a charset regex cannot); keep the charset regex as
early-reject hygiene; the instance served-workspace **allow-list** sits on top as policy.
*Tradeoff:* touches a framework file (`invoke()`/a shared helper) beyond the shim — but it is behavior-
preserving for valid names and closes a latent hole any future untrusted `invoke()` caller re-opens. Only
question for you: fix it **now** (recommended) or **at DR-1 build** — either way it is filed now.

### C-4 [LB] — Auth covers submit AND poll; fail-closed; isolation on the poll; envelope is the outcome authority. *(settles D-5; folds N-3, N-4, N-6, N-7)*
**Recommend:** static bearer / `X-API-Key` header, constant-time, on **every** request incl. the poll;
plus:
  - **N-7:** a missing/empty secret **fails closed** (refuse to start or refuse all dispatch — never
    fail-open, given the paid-spend vector); **never log** the auth header or dump request bodies (inherit
    `transport.py` §3.3's "never persists env/prompt" discipline); accept a **SET** of valid secrets so
    old+new overlap during rotation (no downtime cutover).
  - **N-6:** the **poll** reads client-derived job records/deliverables, so it carries the **same auth
    gate AND the same workspace-isolation gate** (`invoke.py:347-356`) as submit — a poll for workspace
    B's id from a caller scoped to A is refused exactly like a submit.
  - **N-3:** the **`202`-ack is a second wire shape** (`{predictable target-ids}`) the CLI door never
    emits, so the known-issues "same JSON envelope / no business logic" invariant must be **amended** to:
    *"same envelope for TERMINAL results; plus a 202-ack admission shape for Tier-B."* State it; don't
    smuggle it under "no second contract."
  - **N-4:** the HTTP-status mapping has three edges to pin as first-class contract facts: (1) **`200` ≠
    all-succeeded** — a per-item BLOCK rides `results[]` at `envelope.ok=true`; the **envelope, not the
    status, is the outcome authority** (cloud orchestrators love to branch on status); (2) a bad session
    **cursor** `invalid-token` is a domain error → **`400`/`422`, NOT `401`** (`401` is reserved for the
    auth secret — two different "token" concepts); (3) a transport **timeout** has no envelope → the
    runner synthesizes a **`504`/re-drivable** (ties to C-2's exception-synthesis).
*Tradeoff:* a single shared secret is coarse (no per-caller audit); per-caller keys are a later additive
step. There is **no** auth today, so all of this is net-new and must land before any network bind.

### C-5 [LB] — Concurrency: register-and-read the BUILT presence registry; wire the shared chokepoint; 429 is the backstop. *(settles D-8)*
**Recommend:** enforce the cap by **registering into and reading `PresenceRegistry.live_count()`** against
`opdefaults.MAX_PARALLEL_SESSIONS` (=3, G2-validated), not a blind shim-local counter — it is the designed,
built, account-wide observable (refutes the initial's fatalism). **Name the build dependency (V-A):** the
registry is not yet wired into the live compose path, so to actually see CLI/interactive competition, DR-1
build must register a presence lease at the **shared paid-call chokepoint** (cleanest: the `transport`
`invoke_headless` boundary every paid call funnels through, so BOTH doors register). Until that wire lands,
`live_count()` bounds only shim-spawned runners. **Keep `rate-limit-backpressure`→HTTP 429 + `retry-after`
as the always-correct backstop** — it catches real subscription pushback regardless of registration
coverage, so this de-risks the build-dep.
*Tradeoff:* the shared-chokepoint wire is a small additive change to a framework file; declining it leaves
the cap shim-local for v1 (CLI competition unseen) but the 429 backstop still prevents a crash. **Open sub-fork
for you (the one place I leave it open):** wire presence-registration at the chokepoint **now** vs accept
shim-local `live_count` + 429 for v1 — this is a build-scope/effort call only you can price.

### C-6 [m] — `render` fast-path: optimistic-sync(≤~60s)-then-202, on the verified LLM-free fact. *(settles D-4-render)*
**Recommend:** replace always-Tier-B with **spawn the single runner detached, WAIT ≤~60s; a cache-hit /
local pandoc serialize returns `200` synchronously; a fit mint times out the wait → return `202` +
the predictable `deliverable-id`** and the detached runner continues. One runner path (no second code
path), no mint-prediction second-guess, and render idempotency-by-`deliverable-id` makes the
timed-out-then-polled mint safe. ≤60s is well inside even proxy caps (research §3.2). The always-Tier-B
option survives only as a shim-simplicity choice — but its stated "can't predict the mint" reason is
false (V-B), so decide on the real trade (one round-trip tax on the COMMON cache-hit vs slightly more
shim logic). *Tradeoff:* the optimistic wait holds an HTTP connection up to ~60s (bounded, safe); minor.

### C-7 [m] — `begin-session` over HTTP: don't FORBID compose-in-one-call; pin "async results are token-free." *(settles D-4-begin-session)*
**Recommend:** keep plan-only (`generate=none`) as the **default** synchronous Tier-A shape, but **do not
forbid** `begin-session{generate≠none}` — admit it as an opt-in **Tier-B** path (202+poll, `idempotency_key`
required). The initial's "async token not recoverable by id" premise is inaccurate: `idempotency_key`
already makes begin-session retry-safe and returns the **same** session/token (`design.md:2385-2387`). So
the honest invariant is not "forbid generate≠none" but **"async results never CARRY a token; the token is
recovered by re-submitting begin-session with the same idempotency_key"** (cheap, same token, no re-charge).
This keeps the async contract token-free (the real simplification) WITHOUT pushing token-forwarding onto
the stateless cloud caller — the exact friction DR-1 exists to remove. *Tradeoff:* one extra Tier-B path
vs a cloud-caller that must store+forward a token between nodes; I judge the capability worth it (favors
"generalized/reusable over crippled"). Product-ergonomics call — flagged for you, but with a clear rec.

### C-8 [m] — `jobs/` DATA surface is instance-scoped client data. *(settles D-7; the initial omitted it)*
**Recommend:** ratify that the async layer adds a **workspace-scoped `jobs/` store subdir** (there is none
today — `store.py` confirmed) whose CONTENTS are **client-derived** (terminal envelopes carry artifact-ids,
coordinates, human `hint` text): `provenance: instance`, gitignored, rule-2-isolated (no cross-workspace
leak in a poll response — ties to C-4/N-6), with retention/GC (register alongside §27.3). The shim *code* +
jobs *mechanism* stay framework; the *data* is instance. *Tradeoff:* none material — this is the rule-4/5
posture; it was simply missing from the initial's boundary section.

### C-9 [m] — Transport primary + verb subset (confirmations, largely unchanged).
**Recommend:** confirm 202+poll as the Tier-B primary (sync-hold for ms-scale Tier A only; webhook/
Wait-node `resumeUrl` callback deferred as a registered optional enhancement — its outbound-egress/SSRF
surface justifies deferral); operator verbs stay **structurally excluded** (not in `KNOWN_VERBS`);
`emit-outline` exposed as cheap Tier-A. *Tradeoff:* none new — both reports agree; listed so the gate
ratifies the verb surface explicitly.

---

## D. Deferred / registered (not for v1, but recorded)

- **Webhook/Wait-node callback** (`$execution.resumeUrl`) as a `callback_url?` enhancement over the
  always-available poll floor — deferred for its outbound-egress/SSRF surface + per-orchestrator wiring.
- **Per-caller API keys / audit** (v1 is one shared secret set) — later additive step.
- **SSE/streaming** — rejected for v1 (heavier contract, no benefit for a batch-of-artifacts producer).
- **AIMD width auto-tuner** — already deferred by §22.5/§26; DR-1 does not touch it.
- **`jobs/` retention/GC policy** — register with the §27.3 retention item.
- **Execute-Command door** — remains the zero-new-surface option for same-host self-hosted n8n ≤ v1.x
  (research §0/§2.2); DR-1 is explicitly for the consumers that CANNOT shell it. Not superseded.

---

## E. Standalone recommendation: the workspace-name isolation-gate bypass (file NOW, independent of DR-1)

**This is not a DR-1 deliverable — it is a pre-existing framework defect that DR-1 merely makes
exploitable.** File it as its own known-issue immediately, regardless of DR-1's timeline:

- **What:** `invoke.py:329-331` constructs the workspace store root from the **unvalidated** caller string
  `workspace`; `store.py:144-151` trusts caller placement; grep of `pipeline/`+`scripts/` confirms **no**
  workspace-name validator anywhere.
- **Why it is worse than "a traversal":** `workspace="../other-client"` **moves the very store root the
  isolation gate validates against** (`invoke.py:347-356` checks referenced ids resolve *inside* the
  root), so referenced ids resolve inside the WRONG workspace and **pass** the gate. The framework's
  stated invariant "isolation is enforced by the API, not by trust" is **currently false for the workspace
  root.** It is not exploitable *today* only because both live doors (OS-shell CLI / in-process) are
  trusted — which is exactly why it must be fixed in the **framework**, not patched shim-side.
- **Fix:** **resolve-and-contain** — assert `(root/"workspaces"/workspace).resolve()` is a direct child of
  `(root/"workspaces").resolve()` (catches `..`, absolute paths, symlink escapes); charset regex
  (`^[a-z0-9][a-z0-9._-]{0,63}$`) as early-reject hygiene; the instance served-workspace allow-list as the
  policy layer on top (necessary but not sufficient alone). Behavior-preserving for all valid names.
- **Maintainer choice:** fix immediately (recommended) or at DR-1 build — but registered as a known-issue
  now either way.

---

## F. What I adopted vs defended (per-decision ledger)

| # | Decision | Final position | Basis |
|---|---|---|---|
| D-1 | Tier-B framing | **Hybrid** — defend "rides the substrate" spine, adopt adversarial's "real jobs subsystem, lossy bookkeeping" honesty | §22.7 + built `claims.peek`/`create_exclusive`/sweep |
| D-2 | §21.9 | **Adopt adversarial** — AMEND, not reinterpret (exact text in C-1) | letter conflicts; intent + maintainer simple/honest pref |
| D-3 | Transport | **Defend initial** — 202+poll primary — with N-1 closed, N-3/N-4 folded | research §3; poll-hole corrected |
| D-4 render | Fast-path | **Adopt adversarial** — optimistic-sync-then-202 | V-B: resolution is LLM-free (`render.py:205`) |
| D-4 begin-session | plan-only | **Hybrid** — don't forbid compose-in-one-call; pin "async results token-free" | accurate `idempotency_key` premise (`design.md:2385`) |
| D-5 | Auth | **Defend initial** mechanism + adopt N-6/N-7/N-3/N-4 | net-new; poll + fail-closed + status edges |
| D-6 | Workspace gap | **Adopt adversarial** — neuters the gate; resolve-and-contain; standalone known-issue | verified: no validator; gate validates a moved root |
| D-7 | Boundary | **Defend initial** split + adopt the `jobs/` DATA surface | `store.py` has no `jobs/`; envelope carries client data |
| D-8 | Concurrency | **Adopt adversarial's direction, correct its readiness** — presence registry built but UNWIRED; 429 backstop | V-A: `live_count` exists, no live-path registration |
| N-1 | Poll liveness | **Adopt the hole, CORRECT the fix** — id-keyed claim `peek` + job-record grace + exception-synthesis (NOT the count-only presence-lease) | V-A: presence registry is content-free/count-only |
| N-2 | Double-submit | **Adopt** — create-exclusive job write | `store.create_exclusive` is the built G1 primitive |
| N-3 | 202-ack | **Adopt** — amend the "same envelope" invariant | 202-ack is a shape the CLI never emits |
| N-4 | Status mapping | **Adopt** — envelope-is-authority; cursor≠401; timeout→504 | `invoke.py:413-416`; two token concepts |
| N-5 | Sweep vs record | **Adopt** — terminal envelope for nondeterministic failures only | §22.3 sweep re-derives deterministic blocks |
| N-6 | Poll auth+isolation | **Adopt** — poll carries submit's gates | poll reads client data |
| N-7 | Secret hygiene | **Adopt** — fail-closed, redaction, rotation-set | inherit `transport.py` §3.3 |

**Load-bearing for the gate:** C-1, C-2, C-3, C-4, C-5. **Minor:** C-6, C-7, C-8, C-9.
**The single open sub-fork left for you:** C-5's build-scope choice (wire presence-registration at the
shared chokepoint now vs shim-local `live_count`+429 for v1) — left open only because it is an
effort/scope call, not a design ambiguity.

---

## G. Sources (verified this pass, repo @ main)

- `pipeline/claims.py` — `ClaimRegistry` (workspace-scoped, id-keyed), `acquire`/`release`/**`peek`** (282),
  `DEFAULT_LEASE_TTL_SECONDS=30min` (77). Tested `tests/test_claims.py`.
- `pipeline/telemetry.py` — `PresenceRegistry` (account-wide, content-free/**count-only**), `register`/
  `refresh`/`release`/**`live_count`** (295); `recommend_width` (335). Tested `tests/test_telemetry.py`.
- **Wiring grep:** `PresenceRegistry.register()`/`live_count()` absent from live compose/session/driver
  path; only `recommend_width` wired at `session.py:171`.
- `pipeline/fit_resolution.py` — "PURE plan/coordinate resolution … NEVER the SSOT … no reshape/gate."
- `pipeline/api/render.py` — engine mint gated at **205** `if fit_res.should_mint and not is_done(...)`;
  serialize mint gated at 236; resolution (200/202/232) is LLM-free.
- `pipeline/store.py` — `create_exclusive`/`write_new`/`append_jsonl_line`/`write_replace` (G1 primitives);
  subdir set artifacts/deliverables/claims/folios/reviews/select/output/manifests — **no `jobs/`** (confirmed).
- `pipeline/opdefaults.py` — `MAX_PARALLEL_SESSIONS=3`, `LEASE_TTL_SECONDS=1800` (G2-validated).
- `docs/design.md` — §21.9 (2475-2486, "Not a long-running server" 2479); §22.5 (2587-2609, presence-lease
  "live-lease count = account-wide in-flight" 2598, cross-workspace count 2601-2602); §22.7 (2619-2654,
  "SOLELY (1) output existence (2) claim registry, never the SSOT" 2621-2626; crash-safety S1→S6 2634-2639);
  §22.6 codes (2611-2617).
- `docs/known-issues.md` — DR-1 requirement + "thin shim / same envelope / no business logic / additive".
- `pipeline/transport.py` — subscription auth, `ANTHROPIC_API_KEY` stripped (28-38,120-121); 20-min timeout
  (129-133) < 30-min lease; §3.3 no-log discipline; the shared paid-call chokepoint for C-5.
