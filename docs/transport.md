# Transport selection, keys & the weekly spend meter — operator guide

**Audience:** the operator of a pipeline instance who wants to run generation on an **API key**
(single- or multi-tenant) instead of, or alongside, the default **Claude subscription** — and who
wants a hard, auditable ceiling on what that can cost.

This is the AS-BUILT operator guide. The design of record is `docs/design.md` **§21.9** (the
transport invariant) and **§21.10** (the single home for the resolver, keystore, and meter);
this page is the how-to. Nothing here spends by reading it; the commands below are all local
config edits until you actually run a generation verb.

## Money-safety in one paragraph

A paid run cannot exceed a number you set. Before the first model call, the run computes its
**worst-case ceiling** (every stage × its retry budget × the per-call cap) and **admits** that
ceiling — under a cross-process lock — against BOTH the key's **weekly cap** and one install-wide
**umbrella** weekly cap; if either would be exceeded it **refuses before spending anything**. Every
paid call is additionally forced under `--max-budget-usd = min(caller, $5)` (the default per-call
cap). The reservation is **settled to the real cost in a `finally`** on every exit (a crash
self-expires it at the full ceiling). The API key is injected into the child process **only** while
a live, unexpired reservation exists — no reservation, no key, no spawn. The subscription path is
flat-rate and money-irrelevant, and is used **only** for the one user you have entitled.

## The two transports

| | **SUBSCRIPTION** | **API-KEY** |
|---|---|---|
| Auth | the Claude subscription (OAuth), headless | `ANTHROPIC_API_KEY`, injected per-call |
| Who may use it | ONLY the single **config-entitled** user (ToS) | any scope you explicitly **assign** a key to |
| How it is chosen | the fallback when no key is assigned | opt-in, per-scope assignment (or a per-run override) |
| Money model | flat-rate (no per-call $ ceiling) | metered: weekly cap + umbrella + `$5`/call |
| The wall | the widened env-strip + controlled-settings wall (below) | the weekly meter + hold-gated key injection |

Both are enforced at the **same shared chokepoint** (see *Enforcement*, below), so the rules fire
identically whether you drive from the CLI or over the served HTTP shim.

### The subscription wall (why subscription is safe)

Stripping `ANTHROPIC_API_KEY` from the child env is necessary but **not sufficient** — a
`settings.json` `apiKeyHelper` can hand the CLI a key at auth time with no env var involved, and
sibling provider vars (`ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY`) can
divert auth. So every subscription spawn (a) strips that **widened** set of vars, and (b) runs under
a pipeline-controlled settings file (`--settings … --setting-sources ""`) proven to define no
`apiKeyHelper`. If that wall cannot be proven — a missing/unreadable controlled file, or a
**managed/enterprise apiKeyHelper** — the subscription spawn **fails closed** (a loud refusal, no
spawn). See the [operator note on managed hosts](#operator-note-managed-hosts) below.

## Setup

Three steps get you from nothing to a metered API-key run. Steps 2–3 are `pipeline transport`
admin verbs (local file edits over `instance/ops/transport/config.yaml`; they spend nothing and
never read or print a secret).

### 1. Store the secret key in the keystore

Secrets live **outside the repo** in a 0600-per-handle store under `$OPTIQUITY_SECRETS_DIR`
(default `~/.optiquity/secrets/`). A key is referenced everywhere else by a **non-secret handle**
`<namespace>:<name>` (e.g. `anthropic:acme`) — the secret value itself never appears in config,
argv, logs, the ledger, or telemetry.

There is **no CLI verb that takes a secret value** (by design — a secret on a command line lands in
your shell history and `ps`). Store it with the keystore's file backend, which writes the file at
exactly 0600:

```bash
# One handle → one 0600 file under $OPTIQUITY_SECRETS_DIR (default ~/.optiquity/secrets/).
export KEY=sk-ant-…    # in your shell first — keeps the value off argv
python -c 'import os; from pipeline.spend.keystore import FileSecretBackend, SecretRef; \
FileSecretBackend().store(SecretRef.parse("anthropic:acme"), os.environ["KEY"])'
```

The equivalent by hand is a 0600 file named exactly `anthropic:acme` in `$OPTIQUITY_SECRETS_DIR`.
The store **fails closed** if `$OPTIQUITY_SECRETS_DIR` is relative or resolves inside the repo tree,
and refuses to hand back any secret whose file perms are looser than 0600.

### 2. Assign the handle to a scope, with a HARD weekly cap

```bash
pipeline transport assign-key \
  --scope workspace:dave/work/acme \
  --handle anthropic:acme \
  --weekly-cap 40
```

`--weekly-cap` is **mandatory** — there is no default and no uncapped key; omit it and the command
refuses, writing nothing. `--scope` is one of:

| Scope | Grammar | Applies to |
|---|---|---|
| global | `global` | every run with no more-specific assignment |
| user | `user:<u>` | all of user `<u>`'s zones/workspaces |
| zone | `zone:<u>/<z>` | one zone (and all its workspaces) |
| workspace | `workspace:<u>/<z>/<w>` | one workspace |

The scope-id is parsed from `--scope`; it is **never** derived from a `users/…` path, keeping the
credential cascade orthogonal to the addressing/value cascade.

Inspect or remove assignments:

```bash
pipeline transport list-keys                 # scope + handle + cap per assignment (NEVER a secret)
pipeline transport clear-key --scope workspace:dave/work/acme   # idempotent
pipeline transport show                       # entitled user + umbrella cap + every assignment
```

### 3. (Optional) Entitle the subscription user; set the umbrella cap

```bash
pipeline transport set-subscription-user dave   # the ONE user allowed to fall back to subscription
pipeline transport set-umbrella-cap 200         # the install-wide weekly ceiling (default $50)
```

The entitled subscription user is **single-valued and swappable**, set **only** here — never as a
run parameter (so a run can never re-point *who* may spend on the subscription). The umbrella cap is
one install-wide number that bounds total weekly spend across **all** keys; unset, it defaults to
**$50/week**. (`clear-subscription-user` / `clear-umbrella-cap` remove either, idempotently.)

## The cascade & per-run overrides

For a given run the transport is resolved as: an explicit **override** → else the **cascade** key
→ else the **subscription** if (and only if) the run's user is the entitled one → else a **loud
refusal** (no key, not entitled, nothing spent).

The cascade is **most-specific-wins: workspace → zone → user → global**. Same-named zones under
**different** users are distinct scopes (and distinct spend buckets).

The per-run override (`--transport` on the spend verbs, `transport_override` over HTTP) forces one
run's transport without touching config:

```bash
pipeline generate … --transport subscription        # force subscription (only works for the entitled user)
pipeline generate … --transport api                 # force the cascade-resolved API key
pipeline generate … --transport key:anthropic:acme  # force one specific assigned handle
```

The override vocabulary is **closed** — it names a *mode* or an *assigned handle*, never a user.

## The disclosure line

Before the first spawn, a live run prints one **pre-spend disclosure line to stderr** (a
money-safety notice, kept off the stdout JSON envelope); a CLI dry-run/preview prints the same line
to **stdout** as part of the preview and spends nothing. The shape:

```
cost-disclosure: mode=api-key anthropic:acme · bucket=workspace:dave/work/acme · ≤ $12.50 over 5 artifacts / 5 deliverables · headroom bucket $28.00 of $40.00 / umbrella $173.00 of $200.00
```

Subscription discloses `mode=subscription (flat-rate — no per-call $ ceiling)`. The `≤ $C` is the
**worst-case ceiling** (it carries the retry multiplier at every stage, so it is never an
understatement); the headroom is `cap − week-to-date` for both the key bucket and the umbrella. A
run that *would* be refused on a real `--go` is disclosed as a `would refuse …` line, not a crash.
On an unconfigured subscription-only install nothing is disclosed (byte-unchanged).

## The weekly meter

- **Per-bucket weekly cap.** A bucket is `(scope-level, scope-id, handle, week-key)`. Week-to-date =
  the settled ledger total **plus every live (unexpired) reservation** for that bucket.
- **Calendar week.** Monday 00:00 UTC by default (install policy; the reset weekday + timezone are
  configurable). A pure function of the injectable clock — deterministic and auditable.
- **Umbrella.** Every admission ALSO charges one install-wide bucket, so total weekly spend is
  bounded by one number even across many keys.
- **Admit-before-spend + settle-in-finally.** The worst-case ceiling is reserved under an
  **inter-process lock** (safe across separate `pipeline` processes and detached job-runner
  subprocesses) before any spawn; the reservation is settled to the real cost in a `finally`. A
  crash self-expires the reservation at its full ceiling (a TTL hold) — never a leaked reservation.
- **Edit-EVIDENT ledger.** The settled ledger is a hash-chained append-only file: an edited,
  reordered, or dropped line is **detected** and admission refuses. This is tamper-*evidence*, not
  tamper-*proofing* — see residual risk **R2**.
- Ledgers and holds live under `instance/ops/spend/` (gitignored, per-bucket).

## Per-zone scopes (delivered)

Zones give **store isolation** between same-named workspaces; this build adds the matching
**spend isolation**. You can assign a key and a weekly cap **per zone**
(`--scope zone:<u>/<z>`), and same-named zones under different users key **distinct** spend
buckets — so `dave/work` and `dave/personal` (or two users' `work` zones) never cross-charge. This
closes the zone restructure's deferred "transport-build item" (design §10, §12.6, §23).

## Enforcement — one chokepoint, both doors

Money-safety lives at the **shared chokepoint both the CLI and the served HTTP doors traverse**, not
in the CLI handler:

- At **`invoke()` / the session handler** (which the CLI and the detached `jobrunner → invoke()`
  re-entry both reach identically): resolve the transport → **admit** the ceiling → drive →
  **settle** in a `finally`.
- At **`build_child_env`** (the lowest shared node): the API key is injected and the widened strip
  disarmed **only** under a live reservation whose embedded expiry is ahead of an injected clock —
  an absent or expired hold **fails closed** (no spawn). The subscription/`None` path takes today's
  widened strip + wall.
- The **multi-zone "name a zone or refuse"** guard now fires **uniformly** at this chokepoint, so a
  multi-zone user's served `generate-next`/`render` can no longer silently default the zone and
  charge the wrong bucket — closing the zone restructure's CLI-only gap.

Because the disarm and the admit both live below every door, a forgotten thread, a mis-resolved
plan, or an expired hold can **never** silently spend on a key.

## <a id="operator-note-managed-hosts"></a>Operator note — managed/enterprise hosts

A host that ships an **enterprise/managed `apiKeyHelper`** (e.g. macOS
`/Library/Application Support/ClaudeCode/managed-settings.json`) sits in a policy tier that
`--setting-sources` **cannot** exclude. Because that helper could hand the CLI an API key behind the
subscription's back, **every subscription spawn on such a host is refused** (loud, fail-closed,
detect-and-refuse). This is correct and deliberate — not a bug — but it will surprise an operator
who does not expect it: on a managed host, run on an **API key** (assign one) rather than the
subscription. Detection re-runs every spawn; a managed helper added *after* detection but *before*
the child authenticates is a narrow TOCTOU window (part of the honest residual surface).

## Residual risks (v1 does NOT solve these)

- **R1 — `--user` is addressing, not authentication.** The guarantee is a **bounded blast radius**
  via caps, not an authenticated identity. Real auth is future work.
- **R2 — a local `rm` reopens the cap.** Deleting `instance/ops/spend/` resets the meter. The ledger
  is edit-*evident*, not reset-*proof*: the model is "the operator bounds their own bill."
- **R3 — single writer host.** The inter-process lock assumes one host. Shared-host clock skew or a
  non-locking network filesystem (NFS) is out of scope for v1.
- **R4 — hand-forged in-process plan.** A caller who constructs a `TransportPlan` by hand in-process
  is outside the trust boundary (same as calling the subprocess directly).
- **R5 — key visible via `/proc`.** The injected `ANTHROPIC_API_KEY` is in the child env, visible to
  the **same UID** via `/proc`. An `apiKeyHelper`-resolver backend is deferred hardening.
- **R6 — metered-OAuth under-count.** An assigned OAuth token tied to a *metered* plan would
  under-count against the flat-rate assumption; v1 states that assumption rather than solving it.

## Where things live

| What | Where | Tracked? |
|---|---|---|
| Secret VALUES (0600 per handle) | `$OPTIQUITY_SECRETS_DIR` (default `~/.optiquity/secrets/`) | no (outside the repo) |
| Handle assignments + entitlement + umbrella | `instance/ops/transport/config.yaml` | no (`instance/ops/` gitignored) |
| Weekly ledgers + holds | `instance/ops/spend/` | no (`instance/ops/` gitignored) |

`instance/ops/` is gitignored (the public-boundary guard flags any tracked file under it), so the
**mechanism** ships in the framework while all **data** stays instance-side — nothing here is ever
committed.
