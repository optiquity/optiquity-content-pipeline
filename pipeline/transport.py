"""The headless Claude Code transport wrapper (F10, §21.9) — plan step 23, decision T6.

Design authority: `docs/design.md` §21.9 ("HARD, NON-NEGOTIABLE: the pipeline is a headless
Claude Code CLI invocation authenticated on the Claude SUBSCRIPTION — never API keys, never
`ANTHROPIC_API_KEY`" — F10; "Not a long-running server; one synchronous invocation per verb:
params + optional token in → results + token out"), §22.5 (backpressure surfaces as typed
`rate-limit-backpressure`, never a crash; `remediation.action = retry-after(+retry_after) |
reduce-width`), §3.1 (no-overstep: never silently reinterpret a failure as success), §3.3
(no secrets ever surface — this module never logs or persists the child env or the prompt
text itself); plan decision T6 (this module) / T9 (`pipeline/prompts/`, the sibling
package). The literal wire contract of record is gate **G5** (step 4) as consolidated by
the step-6 **BUILD PARAMETER SHEET item 5** (`ops-handoff/build/step-06/report.md`) and
carried into `state.md`'s G5 gate-outcome block — every flag, env var, and JSON-field name
below is verified transcript, not invention.

**The G5 wrapper contract (mandatory, reproduced here for the reader; the parameter sheet
is the source of record):**

- Invocation: ``claude -p --output-format json --no-session-persistence [--model M]
  [--max-budget-usd C] [--fallback-model F]``. **Never** `--bare` (API-key-only auth — an
  F10 violation) and **never** `--resume`/`--continue`/`--session-id`/`--fork-session`
  (the only ways conversation state crosses `-p` calls).
- Prompt delivery is **stdin only** — never argv. The step-04 probe found a flat ~3s stdin
  hazard when an argv prompt leaves stdin open; passing the prompt as `subprocess`'s
  `input=` sidesteps the hazard entirely rather than requiring an argv mode plus
  `< /dev/null` discipline (an in-latitude simplification: the mandatory contract is
  "stdin preferred", and this module makes it the *only* path).
- **Env (F10, both mandatory):** `ANTHROPIC_API_KEY` MUST be absent from the child env —
  stripped from whatever base env is copied AND asserted absent before spawn (belt and
  suspenders: `build_child_env` strips silently on the expected hot path — this dev
  machine's ambient shell has the key set, a standing F10 hazard the maintainer was
  flagged about — and then hard-refuses with a typed `ApiKeyPresentError` if the key is
  *still* present afterward, which is only reachable if a caller explicitly tries to
  inject it via `env_overrides`). `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` MUST be set — the
  step-04 probe proved Claude Code's auto-memory (default-on) leaks state across `-p`
  calls sharing a cwd, and that this exact env var closes both the write and the load
  side. **This is what makes per-call statelessness a construction property, not a
  convention.**
- **F10 was env-only, and env-only is NECESSARY-BUT-INSUFFICIENT (plan G2, S-4).** Stripping
  `ANTHROPIC_API_KEY` from the child env does NOT, by itself, guarantee a subscription spawn:
  (a) a `settings.json` `apiKeyHelper` supplies an api key the CLI resolves at auth time —
  no env var involved; (b) sibling env vars OUTRANK or DIVERT the subscription —
  `ANTHROPIC_AUTH_TOKEN` (an alternate bearer credential) and the
  `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY` provider switches (which flip the CLI onto a
  3P provider authenticated on ITS OWN credentials, never the Claude subscription). G2
  therefore **STRENGTHENS** F10 in two places, so the subscription spawn is now
  "strengthened — still no key, tighter", **NOT byte-for-byte identical to pre-G2**: (1)
  `build_child_env` WIDENS the strip to those four sibling vars (below); and (2) every
  subscription spawn is walled under pipeline-controlled settings that provably define NO
  `apiKeyHelper` (`build_subscription_wall`: `--settings <controlled-file>` +
  `--setting-sources ""`, which loads ONLY the controlled file and excludes ambient
  user/project/local settings — verified on the pinned CLI 2.1.223). An ENTERPRISE/MANAGED
  `apiKeyHelper` is a SEPARATE policy tier `--setting-sources` cannot exclude (the S-4 hole):
  the wall DETECTS it and FAILS CLOSED (a typed refusal, never an uncontrolled spawn). **No
  api-key path is built at G2** — the wall only ever tightens the subscription path.
- **Timeout:** no CLI flag exists (verified absent from `--help`); the wrapper owns it via
  a `subprocess` timeout, not an external `timeout(1)` wrapper. Default
  `DEFAULT_TIMEOUT_SECONDS` = 20 minutes (the G5 preliminary seed), caller-overridable.
  **Invariant (do not break): this default must stay strictly less than the claim-lease
  TTL** (`pipeline.claims.DEFAULT_LEASE_TTL_SECONDS`, 30 min) — an expired lease must
  always imply a dead process (§22.3/§22.4); `tests/test_transport.py` pins this
  cross-module inequality so a change to either constant fails loudly rather than
  silently drifting the invariant. This module does not import `pipeline.claims` itself
  (transport has no lease/claim concerns of its own — §21.9: transport only).
- **Result classification — never key off `subtype` alone** (the step-04 probe's load-
  bearing QUIRK: `subtype` stays `"success"` even on a genuine API error). Success is the
  documented three-way conjunction: `exit == 0 and .is_error is False and .subtype ==
  "success"`. `.result` is OPTIONAL (absent on a budget-exhausted kill — verified). Error
  classification reads `.terminal_reason` / `.api_error_status` / `.errors[]`, never
  `.subtype`.
- **Typed backpressure (§22.5).** The exact usage-limit JSON shape is **UNVERIFIED** — it
  was unsafe to trigger deliberately during the gate probe (step-06 sheet item 5.8
  explicitly flags this). Per that item's directive, this module detects defensively:
  known non-backpressure error shapes (`api_error`, `budget_exhausted`) are named
  explicitly; a string-pattern scan over `terminal_reason`/`errors[]`/`result` catches
  keyword-recognizable rate/usage/capacity language even under an `api_error` terminal
  reason; and — per the sheet's literal instruction — **any other unrecognized
  `is_error: true` shape is treated as `rate-limit-backpressure`-eligible** rather than
  silently swallowed or crashed on, with the raw JSON preserved on the result for the
  step 37-38 telemetry work to tighten this classifier without an API change.
- **No LLM/correctness logic here.** This module parses transport-level JSON envelope
  fields only; it never inspects `.result`'s content, never validates IR/fit/serialize
  contracts, and never retries or re-asks — that is every consuming step's job (24+).

**Design ambiguities resolved in this module (documented for the reviewer):**

1. **`budget_exhausted` is classified separately from `rate-limit-backpressure`**
   (`code = "budget-exhausted"`), not folded into it. §22.5's backpressure surface is
   specifically the **account-wide** rate/concurrency ceiling; `budget_exhausted` fires
   from the caller's own `--max-budget-usd` cap — a self-imposed, caller-controlled
   condition with a different remediation (raise the cap) than backpressure's
   (retry-after / reduce width). Both are still `status="error"`, never a crash.
2. **`model` is optional and unpinned here.** No model identifier is ratified anywhere in
   the build-so-far for "the" pipeline model — §21.9 says "pin per verb", which is a
   decision for the verb-owning steps (24+: writer/reconciler/reviewers), not transport
   plumbing. `invoke_headless(model=None)` omits `--model` entirely, letting the CLI use
   its own default; callers pin explicitly once a verb-level model decision exists.
3. **`--json-schema` is not wired in this module.** Its behavior is explicitly UNTESTED
   per the gate probe, and structured-output validation belongs to the IR/fit contracts
   landing at step 24+ (§13 payload validation), not to transport-only plumbing.
4. **cwd isolation (`--setting-sources`/`--settings`/`--strict-mcp-config`/`--tools ""`)
   is left to the caller.** The step-04 report calls dedicated-cwd + explicit isolation
   flags an INFERRED recommendation with UNTESTED flag behavior ("a small step-23
   verification item"), not a G5 MANDATE. `invoke_headless` accepts an optional `cwd` so
   a caller CAN run from a dedicated non-repo directory (recommended), but this module
   does not enforce it or wire the extra isolation flags — flagged below as an open item
   for the maintainer/reviewer rather than invented scope.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "ANTHROPIC_API_KEY_ENV",
    "ANTHROPIC_AUTH_TOKEN_ENV",
    "CLAUDE_CODE_USE_BEDROCK_ENV",
    "CLAUDE_CODE_USE_FOUNDRY_ENV",
    "CLAUDE_CODE_USE_VERTEX_ENV",
    "DEFAULT_BINARY",
    "DEFAULT_TIMEOUT_SECONDS",
    "DISABLE_AUTO_MEMORY_ENV",
    "F10_STRIPPED_ENV_VARS",
    "SETTING_SOURCES_NONE",
    "ApiKeyPresentError",
    "BinaryNotFoundError",
    "ControlledSettingsError",
    "CostAccumulator",
    "ManagedApiKeyHelperError",
    "ProcessOutcome",
    "ProcessRequest",
    "Remediation",
    "Runner",
    "SubscriptionWall",
    "SubscriptionWallError",
    "TransportError",
    "TransportMode",
    "TransportPlan",
    "TransportResult",
    "build_child_env",
    "build_subscription_wall",
    "invoke_headless",
]

#: F10's forbidden var: MUST be absent from every child env this module constructs. The
#: hard-refused one — the trailing assertion in `build_child_env` fires only on this var.
ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"

#: G2's WIDENED F10 strip (S-4): sibling auth/provider vars that OUTRANK or DIVERT the Claude
#: subscription. `ANTHROPIC_AUTH_TOKEN` is an alternate bearer credential the CLI would honor;
#: the `CLAUDE_CODE_USE_*` trio flips the CLI onto a 3P provider (Bedrock/Vertex/Foundry) that
#: authenticates on ITS OWN credentials — either way NOT the subscription (F10). These are
#: STRIPPED from every child env (no assertion — env-only stripping is necessary but not, on
#: its own, sufficient; the controlled-settings wall closes the `apiKeyHelper` hole below).
ANTHROPIC_AUTH_TOKEN_ENV = "ANTHROPIC_AUTH_TOKEN"
CLAUDE_CODE_USE_BEDROCK_ENV = "CLAUDE_CODE_USE_BEDROCK"
CLAUDE_CODE_USE_VERTEX_ENV = "CLAUDE_CODE_USE_VERTEX"
CLAUDE_CODE_USE_FOUNDRY_ENV = "CLAUDE_CODE_USE_FOUNDRY"

#: The full ordered set of F10-forbidden env vars `build_child_env` removes from every child
#: env: the hard-refused api key first, then the G2-widened siblings.
F10_STRIPPED_ENV_VARS: tuple[str, ...] = (
    ANTHROPIC_API_KEY_ENV,
    ANTHROPIC_AUTH_TOKEN_ENV,
    CLAUDE_CODE_USE_BEDROCK_ENV,
    CLAUDE_CODE_USE_VERTEX_ENV,
    CLAUDE_CODE_USE_FOUNDRY_ENV,
)

#: The per-call-statelessness kill switch (step-04 probe, §21.9). MUST be set to "1".
DISABLE_AUTO_MEMORY_ENV = "CLAUDE_CODE_DISABLE_AUTO_MEMORY"

#: Gate G5's verified binary; a caller can point elsewhere via `invoke_headless(binary=...)`.
DEFAULT_BINARY = "claude"

#: The G5 preliminary wrapper hard-timeout (20 min) — strictly less than the claim-lease
#: TTL (30 min, `pipeline.claims.DEFAULT_LEASE_TTL_SECONDS`) so a timed-out call always
#: implies a dead process an expired lease can safely steal from (§22.3/§22.4). Pinned by
#: cross-module inequality test in `tests/test_transport.py`, not by an import here.
DEFAULT_TIMEOUT_SECONDS = 20.0 * 60.0

#: Defensive string-pattern scan (step-06 sheet item 5.8: the exact usage-limit JSON
#: shape is UNVERIFIED — unsafe to trigger deliberately). Matched case-insensitively
#: against `terminal_reason` / `errors[]` / `result`. Kept as data (not inlined) so a
#: future tightening (once the real shape is observed at steps 37-38) is a one-place edit.
_BACKPRESSURE_KEYWORDS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "ratelimit",
    "usage limit",
    "usage_limit",
    "usagelimit",
    "quota",
    "overloaded",
    "too many requests",
    "429",
    "capacity",
    "throttle",
    "concurrent session",
    "concurrency limit",
)

#: Known, NAMED non-backpressure `terminal_reason` values (step-04 probe transcripts).
_TERMINAL_REASON_API_ERROR = "api_error"
_TERMINAL_REASON_BUDGET_EXHAUSTED = "budget_exhausted"


class TransportError(RuntimeError):
    """The wrapper met a state it must refuse loudly, never guess through (§3.1)."""

    code = "transport-error"


class ApiKeyPresentError(TransportError):
    """F10 refusal: `ANTHROPIC_API_KEY` would ride the child env — refused before spawn.

    This is the hard, non-negotiable subscription-only boundary (§21.9). It fires when a
    caller's `env_overrides` explicitly sets the key (the only reachable path — the
    ambient-env strip in `build_child_env` removes it silently on the expected hot path,
    since this dev machine's shell has it set as a standing F10 hazard); the trailing
    assertion in `build_child_env` is defense-in-depth against any other injection path.
    """

    code = "api-key-present"

    def __init__(self, source: str) -> None:
        super().__init__(
            f"api-key-present: {ANTHROPIC_API_KEY_ENV} would be present in the child env "
            f"via {source} — the pipeline is subscription-only transport, never API keys "
            "(F10, §21.9); refusing to spawn"
        )
        self.source = source


class BinaryNotFoundError(TransportError):
    """The headless binary was not found on the invocation path — never a silent no-op."""

    code = "binary-not-found"


# ---------------------------------------------------------------------------
# The chokepoint CONTRACT (plan G1, §21.10): how ONE drive run authenticates + accounts.
#
# The plan TYPE lives HERE, in transport.py — the LOWEST shared node the CLI and the served
# `jobrunner→invoke()` re-entry both traverse — so this module imports NOTHING new (no
# `pipeline.spend` import, no cycle). `pipeline.spend.resolve` (G7) is the ONLY place a plan
# is BUILT for a paid run; pre-G7 the ONLY reachable variant is the flat-rate subscription.
# ---------------------------------------------------------------------------


class CostAccumulator:
    """A simple additive running-$ total threaded through ONE drive run (plan G1, B1 fix).

    The driver is SEQUENTIAL (§21.9: one synchronous invocation per verb; the fan-out over
    artifacts/deliverables is a plain generator, never a thread pool), so this is a plain
    additive counter — **NO thread-safety claim is made or needed.** The only real concurrency
    in the transport-selection design is the G6 inter-process meter lock, a separate mechanism.

    `add(None)` is a NO-OP — a `TransportResult.total_cost_usd` is documented OPTIONAL (absent
    on a timeout / cli-arg-error, and a subscription call may report no cost), and a missing
    cost must never be guessed at. Only a real numeric cost moves the total; a non-numeric,
    non-None value is refused LOUDLY (§3.1 — never silently reinterpret a bad envelope field).
    This replaces the overwrite-lossy single read at driver.py:976: every call at the
    chokepoint adds into ONE accumulator, so the RUN total is the sum across writer + Review-1
    + every reconcile + every Review-2 + every re-ask, never just the last call.
    """

    __slots__ = ("total", "calls")

    def __init__(self, total: float = 0.0, calls: int = 0) -> None:
        self.total = float(total)
        self.calls = int(calls)

    def add(self, cost: float | None) -> None:
        if cost is None:
            return
        if isinstance(cost, bool) or not isinstance(cost, int | float):
            raise TransportError(
                f"transport-error: a cost contribution must be a number or None, got "
                f"{cost!r} ({type(cost).__name__}) — never silently coerce a malformed "
                "total_cost_usd (§3.1)"
            )
        self.total += float(cost)
        self.calls += 1

    def __repr__(self) -> str:  # pragma: no cover — debug convenience only
        return f"CostAccumulator(total={self.total!r}, calls={self.calls!r})"


#: The closed transport-mode set. `"subscription"` is the ONLY variant any pre-G7 code can
#: reach; the paid `"apikey"` variant (its finite per-call cap + live-hold disarm) lands at G7.
TransportMode = Literal["subscription"]


@dataclass(frozen=True)
class TransportPlan:
    """The chokepoint CONTRACT: how ONE drive run authenticates + accounts (plan G1, §21.10).

    - `mode="subscription"`: today's flat-rate subscription transport. `per_call_cap` is
      **None** (S-1) — the subscription is flat-rate, so forcing a finite `--max-budget-usd`
      would TRUNCATE a real artifact for no money reason (a regression + a design divergence).
      A None cap forces NOTHING at the chokepoint, so the subscription spawn stays byte-for-byte
      what `plan=None` produces — the widened F10 strip, the F10 assertion, AND the G2
      controlled-settings wall fire identically on both (both are strengthened vs pre-G2).
    - `cost_accumulator`: the ONE run-scoped running-$ total EVERY chokepoint call adds into
      (the B1 accounting fix — replaces the last-call-only read at driver.py:976).

    `per_call_cap` becomes a FINITE dollar cap ONLY on the G7 `apikey` variant (not built here)
    — the finite cap that makes loop-caps × cap a true spend bound. Building a `subscription`
    plan with a finite `per_call_cap` is refused LOUDLY (the S-1 truncation regression).
    """

    mode: TransportMode
    cost_accumulator: CostAccumulator
    per_call_cap: float | None = None

    def __post_init__(self) -> None:
        if self.mode == "subscription" and self.per_call_cap is not None:
            raise TransportError(
                "transport-error: a subscription TransportPlan MUST carry per_call_cap=None "
                f"(the subscription is flat-rate; got {self.per_call_cap!r}) — forcing a finite "
                "--max-budget-usd on the subscription path truncates real artifacts for no money "
                "reason (S-1: a truncation regression + a design divergence). The finite cap is "
                "real only on the G7 api-key path."
            )
        if not isinstance(self.cost_accumulator, CostAccumulator):
            raise TransportError(
                "transport-error: a TransportPlan needs a CostAccumulator, got "
                f"{type(self.cost_accumulator).__name__}"
            )

    @classmethod
    def subscription(cls, *, cost_accumulator: CostAccumulator | None = None) -> TransportPlan:
        """Build the flat-rate SUBSCRIPTION plan (the only pre-G7 variant): `per_call_cap=None`
        (S-1). Uses a fresh `CostAccumulator` when the caller supplies none (else the run's shared
        one)."""
        return cls(
            mode="subscription",
            cost_accumulator=cost_accumulator or CostAccumulator(),
            per_call_cap=None,
        )


# ---------------------------------------------------------------------------
# Env construction (F10 belt-and-suspenders — strip, then assert absence).
# ---------------------------------------------------------------------------


def build_child_env(
    base_env: Mapping[str, str] | None = None,
    *,
    overrides: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Construct the EXACT child env for one headless invocation (F10, §21.9).

    `base_env` defaults to a copy of `os.environ` (the ambient shell — on this machine
    that ambient env carries `ANTHROPIC_API_KEY`, the standing F10 hazard flagged at gate
    G5; this is the expected, SILENT strip path — no error, no warning, just absence).
    `overrides` layers caller-supplied values on top (e.g. per-verb env additions); if a
    caller's `overrides` explicitly sets `ANTHROPIC_API_KEY`, that is treated as an
    explicit attempt to smuggle the key back in and is refused loudly rather than
    silently re-stripped a second time. `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` is always
    set last, so no override can accidentally unset per-call statelessness. The trailing
    assertion is defense-in-depth: by construction it can never fire except via the
    explicit-override path above, but it is the literal "assert + raise" the G5 contract
    calls for, and it survives any future refactor of the strip step.

    **G2 widened strip (S-4):** the strip covers the whole `F10_STRIPPED_ENV_VARS` set —
    `ANTHROPIC_API_KEY` PLUS `ANTHROPIC_AUTH_TOKEN` and the
    `CLAUDE_CODE_USE_BEDROCK`/`_VERTEX`/`_FOUNDRY` provider switches — and the strip is
    re-applied to the WIDENED siblings AFTER `overrides` merge, so an override can neither
    re-add nor smuggle one back in. Only `ANTHROPIC_API_KEY` hard-refuses on an explicit
    override (its F10 assertion is unchanged); the siblings are removed silently. Env-only
    stripping is NECESSARY-BUT-INSUFFICIENT on its own — the `apiKeyHelper` hole is closed
    by `build_subscription_wall`, applied at every spawn in `invoke_headless`.
    """
    env = dict(os.environ if base_env is None else base_env)
    for var in F10_STRIPPED_ENV_VARS:  # the expected, silent hot-path strip (widened at G2)
        env.pop(var, None)
    if overrides:
        if ANTHROPIC_API_KEY_ENV in overrides:
            raise ApiKeyPresentError("an explicit env_overrides entry")
        env.update(overrides)
        # Re-strip the WIDENED siblings after the merge so an override cannot re-add one
        # (the hard-refused ANTHROPIC_API_KEY is handled above; here it is only re-stripped
        # for symmetry and can never be present via overrides at this point).
        for var in F10_STRIPPED_ENV_VARS:
            env.pop(var, None)
    env[DISABLE_AUTO_MEMORY_ENV] = "1"  # per-call statelessness, set unconditionally last
    if ANTHROPIC_API_KEY_ENV in env:  # pragma: no cover — structurally unreachable; belt+suspenders
        raise ApiKeyPresentError("the constructed child env")
    return env


# ---------------------------------------------------------------------------
# The subscription controlled-settings WALL (plan G2, §21.10, S-4). Env-only F10 is
# necessary-but-INSUFFICIENT: a `settings.json` `apiKeyHelper` supplies an api key at auth
# time with NO env var involved — a hole `build_child_env` cannot see. This wall pins every
# subscription spawn under pipeline-controlled settings that provably define NO `apiKeyHelper`
# — `--settings <controlled-file>` + `--setting-sources ""` (empty => load ZERO ambient
# user/project/local sources; verified on the pinned CLI 2.1.223: a bogus source errors, the
# empty list is accepted and loads nothing, and `--settings` then loads ONLY the controlled
# file). It NEVER uses `--bare` (that is the API-key-only mode — an F10 violation). It is
# FAIL-CLOSED: any un-provable state (a MANAGED/ENTERPRISE `apiKeyHelper` that
# `--setting-sources` cannot exclude — the S-4 hole; a controlled file that will not
# write/read/verify) is a LOUD typed refusal, never an uncontrolled spawn. NO api-key path is
# built here — the wall only ever TIGHTENS the subscription path.
#
# RESIDUAL (named per plan G2 item 3): the managed case is DETECT-and-REFUSE (the maintainer's
# money-safety-first default), NOT a proof of exclusion. `--setting-sources` cannot exclude the
# managed tier, so the guarantee rests on detection COMPLETENESS + a TOCTOU window: (a) a
# managed `apiKeyHelper`/hazard added AFTER detection but BEFORE the child authenticates is not
# caught (detection re-runs every spawn, shrinking but not closing the window); (b) any managed
# auth mechanism this scanner does not model (beyond a top-level `apiKeyHelper` and an `env`
# block re-injecting a stripped var) would not be seen. On a machine with NO managed tier (the
# ordinary case — this dev machine has none) the wall applies the strongest exclusion and the
# residual is inert.
# ---------------------------------------------------------------------------


class SubscriptionWallError(TransportError):
    """The subscription wall hit an un-provable state and FAILS CLOSED — a loud refusal, never
    an uncontrolled spawn (plan G2, the money-safety-first default; §3.1)."""

    code = "subscription-wall"


class ManagedApiKeyHelperError(SubscriptionWallError):
    """S-4 detect-and-refuse: a MANAGED/ENTERPRISE settings tier that `--setting-sources`
    (user/project/local) cannot exclude either DEFINES an `apiKeyHelper` (or re-injects a
    stripped auth/provider var via an `env` block), or exists-but-cannot-be-read to PROVE it is
    safe, or lives on a platform whose managed path is unknown. Either way the subscription
    spawn is refused — an api-key auth path could ride the managed tier (F10), and
    money-safety-first prefers refusal over an unprovable spawn."""

    code = "managed-apikey-helper"


class ControlledSettingsError(SubscriptionWallError):
    """The pipeline-controlled settings file could not be written, read back, or verified to
    define NO `apiKeyHelper` — the wall refuses rather than fall back to an uncontrolled spawn
    (plan G2 item 4, fail-closed)."""

    code = "controlled-settings"


#: `--setting-sources` value that loads ZERO ambient sources. The empty list excludes
#: user/project/local (where an ambient `apiKeyHelper` could live) — verified valid (exit 0)
#: and eagerly parsed on the pinned CLI 2.1.223 (a bogus value errors; the empty string yields
#: no tokens, so no ambient source loads).
SETTING_SOURCES_NONE = ""

#: The settings key that would supply an api key at auth time with NO env var involved — the
#: exact hole env-only F10 cannot see. The controlled file MUST NOT define it; a managed file
#: that DOES is the S-4 refusal trigger.
_API_KEY_HELPER_KEY = "apiKeyHelper"

#: The controlled settings CONTENT: an empty settings object — it adds nothing and, crucially,
#: defines NO `apiKeyHelper`. `--settings` loads it; `--setting-sources ""` loads nothing else.
_CONTROLLED_SETTINGS_BODY = "{}"

#: The per-PROCESS controlled-settings temp dir (created lazily, removed at interpreter exit).
_controlled_settings_dir: Path | None = None


def _managed_settings_paths() -> tuple[Path, ...]:
    """The MANAGED/ENTERPRISE settings locations for THIS platform — the policy tier
    `--setting-sources` (user/project/local) cannot exclude (the S-4 hole). Paths pinned against
    the actual CLI 2.1.223 binary's own literals (macOS `/Library/Application
    Support/ClaudeCode`, Linux `/etc/claude-code`, Windows `%PROGRAMDATA%\\ClaudeCode`), each
    with a `managed-settings.json` file and a `managed-settings.d/` drop-in directory. An
    UNKNOWN platform, or a drop-in dir that cannot be listed, is an un-provable state and raises
    `ManagedApiKeyHelperError` (fail-closed: we cannot PROVE the absence of a managed
    `apiKeyHelper` where we do not know to look)."""
    plat = sys.platform
    if plat == "darwin":
        base = Path("/Library/Application Support/ClaudeCode")
    elif plat.startswith("linux"):
        base = Path("/etc/claude-code")
    elif plat.startswith("win"):
        base = Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "ClaudeCode"
    else:
        raise ManagedApiKeyHelperError(
            f"subscription-wall: cannot locate the MANAGED settings tier on this platform "
            f"({plat!r}); the wall cannot PROVE there is no managed apiKeyHelper, so it refuses "
            "the subscription spawn (fail-closed, S-4). Extend `_managed_settings_paths` with "
            "this platform's managed-settings path to re-enable spawning here."
        )
    paths: list[Path] = [base / "managed-settings.json"]
    dropin = base / "managed-settings.d"
    try:
        if dropin.is_dir():
            paths.extend(sorted(dropin.glob("*.json")))
    except OSError as exc:
        raise ManagedApiKeyHelperError(
            f"subscription-wall: the managed drop-in directory {dropin} exists but cannot be "
            "listed; the wall cannot PROVE it holds no apiKeyHelper, so it refuses the "
            "subscription spawn (fail-closed, S-4)."
        ) from exc
    return tuple(paths)


def _managed_hazard_reason(data: object) -> str | None:
    """A human reason string if this managed settings object carries an api-key auth HAZARD,
    else None. Catches BOTH a top-level `apiKeyHelper` AND an `env` block that re-injects any
    F10-stripped auth/provider var (a managed `env` block is applied by the CLI and would
    survive `build_child_env`'s process-env strip). A non-object shape is itself un-provable and
    is treated as a hazard (fail-closed)."""
    if not isinstance(data, dict):
        return "a non-object managed settings shape (cannot be proven free of apiKeyHelper)"
    if _API_KEY_HELPER_KEY in data:
        return f"a top-level {_API_KEY_HELPER_KEY!r}"
    env_block = data.get("env")
    if isinstance(env_block, dict):
        injected = [var for var in F10_STRIPPED_ENV_VARS if var in env_block]
        if injected:
            return f"an env block re-injecting {', '.join(injected)}"
    return None


def _detect_managed_apikey_helper(paths: Sequence[Path] | None = None) -> None:
    """S-4 detect-and-refuse. Scan each managed settings file; a file that is simply ABSENT is
    provably safe (skipped), a present-and-hazardous file (`_managed_hazard_reason`) or a
    present-but-UNREADABLE file both raise `ManagedApiKeyHelperError`. `paths=None` resolves the
    real platform tier; tests inject an explicit list (an empty list = a known platform with no
    managed files = provably safe)."""
    resolved = _managed_settings_paths() if paths is None else tuple(paths)
    for path in resolved:
        if not path.exists():
            continue  # a managed file that is simply absent is provably safe
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ManagedApiKeyHelperError(
                f"subscription-wall: managed settings at {path} exist but are unreadable/"
                "unparseable; the wall cannot PROVE they define no apiKeyHelper, so it refuses "
                "the subscription spawn (fail-closed, S-4)."
            ) from exc
        reason = _managed_hazard_reason(data)
        if reason is not None:
            raise ManagedApiKeyHelperError(
                f"subscription-wall: managed settings at {path} define {reason}. This "
                "ENTERPRISE/MANAGED policy tier CANNOT be excluded by --setting-sources "
                "(user/project/local), so an api-key auth path could ride it (F10). Refusing the "
                "subscription spawn (S-4 detect-and-refuse — money-safety-first)."
            )


def _default_controlled_settings_path() -> Path:
    """A stable, per-PROCESS controlled-settings file path in a private temp dir (created once,
    removed at interpreter exit). STABLE within a process so two subscription spawns produce a
    BYTE-IDENTICAL `--settings` argv (the plan=None vs plan=subscription identity the tests pin);
    per-process (not a fixed shared path) so concurrent pipeline processes never race on it."""
    global _controlled_settings_dir
    if _controlled_settings_dir is None:
        directory = Path(tempfile.mkdtemp(prefix="optiquity-subwall-"))
        atexit.register(_cleanup_controlled_settings_dir, directory)
        _controlled_settings_dir = directory
    return _controlled_settings_dir / "subscription-controlled-settings.json"


def _cleanup_controlled_settings_dir(directory: Path) -> None:  # pragma: no cover — atexit only
    shutil.rmtree(directory, ignore_errors=True)


def _ensure_controlled_settings_file(path: Path | None = None) -> Path:
    """Write (idempotently) + VERIFY the pipeline-controlled settings file that defines NO
    `apiKeyHelper`. Re-written and re-verified on EVERY spawn (cheap; defends against a mid-run
    deletion/tamper). FAIL-CLOSED: any write/read/parse failure — or a read-back that does not
    PROVE the absence of `apiKeyHelper` — raises `ControlledSettingsError`, never a fallback to
    an uncontrolled spawn (plan G2 item 4)."""
    target = _default_controlled_settings_path() if path is None else path
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_CONTROLLED_SETTINGS_BODY, encoding="utf-8")
        verify = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ControlledSettingsError(
            f"subscription-wall: the controlled settings file at {target} could not be written, "
            "read back, or parsed; the wall cannot PROVE a no-apiKeyHelper settings surface, so "
            "it refuses the subscription spawn (fail-closed, never an uncontrolled spawn)."
        ) from exc
    if not isinstance(verify, dict) or _API_KEY_HELPER_KEY in verify:
        raise ControlledSettingsError(
            f"subscription-wall: the controlled settings file at {target} did not read back as an "
            f"object free of {_API_KEY_HELPER_KEY!r}; refusing the subscription spawn "
            "(fail-closed)."
        )
    return target


@dataclass(frozen=True)
class SubscriptionWall:
    """The applied wall for ONE subscription spawn: the controlled settings file + the argv the
    spawn adds. `argv` is `("--settings", <controlled-file>, "--setting-sources", "")` — it loads
    ONLY the controlled file (which defines no `apiKeyHelper`) and excludes every ambient
    user/project/local source. It NEVER contains `--bare`."""

    settings_path: Path
    argv: tuple[str, ...]


def build_subscription_wall(
    *,
    managed_settings_paths: Sequence[Path] | None = None,
    controlled_settings_path: Path | None = None,
) -> SubscriptionWall:
    """Construct the controlled-settings WALL for ONE subscription spawn (plan G2, S-4).

    FAIL-CLOSED by construction — RAISES rather than ever returning an uncontrolled spawn:
    `ManagedApiKeyHelperError` when a managed/enterprise `apiKeyHelper` is present, unexcludable,
    or unprovable (the S-4 detect-and-refuse); `ControlledSettingsError` when the controlled file
    cannot be written/read/verified. On success returns the `--settings`/`--setting-sources` argv
    that loads ONLY the controlled (no-`apiKeyHelper`) file and excludes ambient sources — never
    `--bare`.

    `managed_settings_paths` / `controlled_settings_path` are TEST seams (inject a simulated
    managed file, or an unwritable controlled path); production passes neither, resolving the real
    platform managed tier and the per-process controlled file. The managed check runs FIRST so a
    managed refusal never even writes a controlled file.
    """
    _detect_managed_apikey_helper(managed_settings_paths)  # raises → refuse (S-4)
    settings_path = _ensure_controlled_settings_file(controlled_settings_path)  # raises → refuse
    argv = ("--settings", str(settings_path), "--setting-sources", SETTING_SOURCES_NONE)
    return SubscriptionWall(settings_path=settings_path, argv=argv)


# ---------------------------------------------------------------------------
# The subprocess seam (injectable for tests; adapts `pipeline.adapters.graphify`'s
# Runner pattern — a 5-field ProcessRequest, not the graphify seam's 2 positional args —
# extended with the fields a timed, stdin-fed invocation needs).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessRequest:
    """Everything one real (or faked) subprocess call needs — no ambient reads."""

    argv: tuple[str, ...]
    env: Mapping[str, str]
    stdin_text: str
    timeout_seconds: float
    cwd: Path | None


@dataclass(frozen=True)
class ProcessOutcome:
    """One finished (or timed-out) subprocess: `timed_out` short-circuits classification.

    On a timeout, `returncode` is None and `stdout`/`stderr` carry whatever partial
    output the OS captured before the kill (Python surfaces this on
    `TimeoutExpired.stdout/.stderr` when using `capture_output=True, text=True`) — the
    G5 contract treats a timed-out call as having produced no usable JSON regardless.
    """

    timed_out: bool
    returncode: int | None
    stdout: str
    stderr: str


#: The process seam. Default (`runner=None` at `invoke_headless`) is `_subprocess_runner`.
Runner = Callable[[ProcessRequest], ProcessOutcome]


def _subprocess_runner(request: ProcessRequest) -> ProcessOutcome:
    """The real runner: list-form exec (no shell), stdin-fed prompt, wrapper-owned timeout.

    No CLI timeout flag exists (verified absent from `--help`, step-04 §2) — this
    `subprocess.run(timeout=...)` call IS the wrapper-owned timeout the G5 contract
    requires; it is never delegated to an external `timeout(1)` process.
    """
    try:
        completed = subprocess.run(  # noqa: S603 — list-form, fixed binary slot, no shell
            list(request.argv),
            input=request.stdin_text,
            env=dict(request.env),
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds,
            cwd=str(request.cwd) if request.cwd is not None else None,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ProcessOutcome(
            timed_out=True, returncode=None, stdout=exc.stdout or "", stderr=exc.stderr or ""
        )
    except FileNotFoundError as exc:
        raise BinaryNotFoundError(
            f"binary-not-found: executable not found: {request.argv[0]!r} — install it "
            "or point `invoke_headless(binary=...)` at its location (never a silent "
            "no-op)"
        ) from exc
    return ProcessOutcome(
        timed_out=False,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


# ---------------------------------------------------------------------------
# The typed result contract (transport-scoped; never the full §21.7 `ResultItem` — that
# envelope belongs to the external-actor API layer built at later steps).
# ---------------------------------------------------------------------------

#: The closed transport-level code set. `"ok"` is the only success code; every other
#: value is `status="error"` — a per-call outcome, never a raised exception (§22.5: a
#: backpressure/timeout/malformed hit is surfaced typed, never a crash).
TransportCode = Literal[
    "ok",
    "timeout",
    "rate-limit-backpressure",
    "api-error",
    "budget-exhausted",
    "malformed-output",
    "cli-arg-error",
]


@dataclass(frozen=True)
class Remediation:
    """A machine-actionable next step (§21.7/§22.5 shape, transport-scoped subset).

    `action` mirrors the §22.5 vocabulary (`retry-after`, `reduce-width`) plus one
    transport-local action (`increase-budget` for `budget-exhausted`); `
    retry_after_seconds` is populated only when the (unverified) response shape happens
    to carry a numeric `retry_after`/`retry_after_seconds` field — absence is the
    expected case, never treated as a parse failure.
    """

    action: Literal["retry-after", "reduce-width", "increase-budget"]
    retry_after_seconds: float | None = None


@dataclass(frozen=True)
class TransportResult:
    """One `invoke_headless` outcome — transport-scoped, content-blind (§21.9).

    `text` is `.result` on success (never populated on any error code — `.result` is
    documented OPTIONAL and this module never guesses partial success). `raw` is the
    full parsed JSON envelope when one was parsed at all (None on `timeout` and on a
    `cli-arg-error`, where no JSON exists) — kept so a caller (or the step 37-38
    telemetry work) can inspect any field this module does not surface explicitly,
    without this module having to hardcode the complete, still-drifting JSON schema.
    """

    status: Literal["ok", "error"]
    code: TransportCode
    text: str | None
    raw: Mapping[str, Any] | None
    terminal_reason: str | None
    api_error_status: int | None
    session_id: str | None
    uuid: str | None
    duration_ms: float | None
    total_cost_usd: float | None
    remediation: Remediation | None
    stderr: str | None
    returncode: int | None


def _common_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "terminal_reason": payload.get("terminal_reason"),
        "api_error_status": payload.get("api_error_status"),
        "session_id": payload.get("session_id"),
        "uuid": payload.get("uuid"),
        "duration_ms": payload.get("duration_ms"),
        "total_cost_usd": payload.get("total_cost_usd"),
    }


def _looks_like_backpressure(payload: Mapping[str, Any]) -> bool:
    """Defensive string-pattern scan (step-06 sheet item 5.8 — the exact usage-limit
    shape is UNVERIFIED; never hardcode a guessed exact schema as the only path)."""
    errors = payload.get("errors")
    errors_text = " ".join(str(e) for e in errors) if isinstance(errors, list) else ""
    haystack = " ".join(
        (
            str(payload.get("terminal_reason") or ""),
            str(payload.get("subtype") or ""),
            errors_text,
            str(payload.get("result") or ""),
        )
    ).lower()
    return any(keyword in haystack for keyword in _BACKPRESSURE_KEYWORDS)


def _remediation_for_backpressure(payload: Mapping[str, Any]) -> Remediation:
    retry_after = payload.get("retry_after")
    if retry_after is None:
        retry_after = payload.get("retry_after_seconds")
    if isinstance(retry_after, int | float) and not isinstance(retry_after, bool):
        return Remediation(action="retry-after", retry_after_seconds=float(retry_after))
    return Remediation(action="reduce-width")


def _parse_json_object(stdout: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _malformed_output_result(
    outcome: ProcessOutcome, *, raw: Mapping[str, Any] | None = None
) -> TransportResult:
    return TransportResult(
        status="error",
        code="malformed-output",
        text=None,
        raw=raw,
        terminal_reason=None,
        api_error_status=None,
        session_id=None,
        uuid=None,
        duration_ms=None,
        total_cost_usd=None,
        remediation=None,
        stderr=outcome.stderr,
        returncode=outcome.returncode,
    )


def _cli_arg_error_result(outcome: ProcessOutcome) -> TransportResult:
    return TransportResult(
        status="error",
        code="cli-arg-error",
        text=None,
        raw=None,
        terminal_reason=None,
        api_error_status=None,
        session_id=None,
        uuid=None,
        duration_ms=None,
        total_cost_usd=None,
        remediation=None,
        stderr=outcome.stderr,
        returncode=outcome.returncode,
    )


def _timeout_result(outcome: ProcessOutcome) -> TransportResult:
    return TransportResult(
        status="error",
        code="timeout",
        text=None,
        raw=None,
        terminal_reason=None,
        api_error_status=None,
        session_id=None,
        uuid=None,
        duration_ms=None,
        total_cost_usd=None,
        remediation=None,
        stderr=outcome.stderr,
        returncode=outcome.returncode,
    )


def _classify_payload(payload: dict[str, Any], outcome: ProcessOutcome) -> TransportResult:
    is_error = payload.get("is_error")
    if not isinstance(is_error, bool) or "type" not in payload:
        # Not the documented result envelope at all — never guess at a shape (§3.1).
        return _malformed_output_result(outcome, raw=payload)

    common = _common_fields(payload)
    if outcome.returncode == 0 and is_error is False and payload.get("subtype") == "success":
        # The documented three-way conjunction (step-06 sheet item 5) — never `subtype`
        # alone (the QUIRK: `subtype` stays "success" even on a genuine API error).
        return TransportResult(
            status="ok",
            code="ok",
            text=payload.get("result"),
            raw=payload,
            remediation=None,
            stderr=outcome.stderr,
            returncode=outcome.returncode,
            **common,
        )

    terminal_reason = common["terminal_reason"]
    if terminal_reason == _TERMINAL_REASON_BUDGET_EXHAUSTED:
        return TransportResult(
            status="error",
            code="budget-exhausted",
            text=None,
            raw=payload,
            remediation=Remediation(action="increase-budget"),
            stderr=outcome.stderr,
            returncode=outcome.returncode,
            **common,
        )
    if _looks_like_backpressure(payload):
        return TransportResult(
            status="error",
            code="rate-limit-backpressure",
            text=None,
            raw=payload,
            remediation=_remediation_for_backpressure(payload),
            stderr=outcome.stderr,
            returncode=outcome.returncode,
            **common,
        )
    if terminal_reason == _TERMINAL_REASON_API_ERROR:
        return TransportResult(
            status="error",
            code="api-error",
            text=None,
            raw=payload,
            remediation=None,
            stderr=outcome.stderr,
            returncode=outcome.returncode,
            **common,
        )
    # Unrecognized `is_error: true` shape — including `terminal_reason == "completed"`
    # paired with `is_error: true`, a contradictory combination that has never been
    # observed but must still be routed somewhere loud rather than silently accepted.
    # Step-06 sheet item 5.8's literal directive: treat as backpressure-eligible and
    # keep the raw JSON on the result for steps 37-38 to tighten this classifier.
    return TransportResult(
        status="error",
        code="rate-limit-backpressure",
        text=None,
        raw=payload,
        remediation=_remediation_for_backpressure(payload),
        stderr=outcome.stderr,
        returncode=outcome.returncode,
        **common,
    )


def _classify(outcome: ProcessOutcome) -> TransportResult:
    if outcome.timed_out:
        return _timeout_result(outcome)
    stdout = outcome.stdout or ""
    if not stdout.strip():
        # Empty stdout: exit!=0 + stderr text is the documented CLI-arg-error shape
        # (step-04 §3.3a); exit==0 with nothing on stdout is equally unexpected but
        # still routed loudly, as malformed output rather than a silent "ok".
        if outcome.returncode != 0:
            return _cli_arg_error_result(outcome)
        return _malformed_output_result(outcome)
    payload = _parse_json_object(stdout)
    if payload is None:
        return _malformed_output_result(outcome)
    return _classify_payload(payload, outcome)


# ---------------------------------------------------------------------------
# The public entry point.
# ---------------------------------------------------------------------------


def _build_argv(
    *,
    binary: str,
    model: str | None,
    max_budget_usd: float | None,
    fallback_model: str | None,
) -> list[str]:
    argv = [binary, "-p", "--output-format", "json", "--no-session-persistence"]
    if model is not None:
        argv += ["--model", model]
    if max_budget_usd is not None:
        argv += ["--max-budget-usd", str(max_budget_usd)]
    if fallback_model is not None:
        argv += ["--fallback-model", fallback_model]
    return argv


def invoke_headless(
    prompt: str,
    *,
    model: str | None = None,
    max_budget_usd: float | None = None,
    fallback_model: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    binary: str = DEFAULT_BINARY,
    cwd: Path | str | None = None,
    base_env: Mapping[str, str] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    runner: Runner | None = None,
    plan: TransportPlan | None = None,
) -> TransportResult:
    """One synchronous headless invocation (§21.9): params in, a typed result out.

    Raises `ApiKeyPresentError` (never returns a result) if the child env this call
    would spawn under still carries `ANTHROPIC_API_KEY` after the mandatory strip — the
    F10 refusal is a hard stop, never a typed error-code result, because it means the
    caller is trying to authenticate on an API key, which this pipeline never does.
    Raises `BinaryNotFoundError` if `binary` is not on the invocation path.

    Every other failure mode (timeout, backpressure, a malformed/unparseable JSON
    envelope, a CLI argument error, a genuine API error, a budget cutoff) is returned as
    a typed `TransportResult`, never raised and never a crash (§22.5).

    `prompt` always rides stdin (never argv — module docstring, the step-04 §3.3d
    hazard). `model`/`max_budget_usd`/`fallback_model` are omitted from argv entirely
    when `None` — this module pins nothing on the caller's behalf (§3.1, design
    ambiguity 2 in the module docstring). `runner=None` uses the real subprocess; tests
    inject a fake `Runner` (mirrors `pipeline.adapters.graphify`'s seam).

    `plan` (optional, plan G1) is the chokepoint CONTRACT. `plan is None` OR
    `plan.mode=="subscription"` are IDENTICAL TO EACH OTHER: `plan.per_call_cap is None`
    forces NO `--max-budget-usd` (the subscription is flat-rate — S-1: a finite cap would
    truncate a real artifact), and BOTH paths carry the same G2 subscription wall, so the argv
    + child env + returned result are byte-identical between them. (Both are STRENGTHENED versus
    pre-G2 — the widened env strip + the controlled-settings wall now ride every subscription
    spawn — so neither is byte-identical to the pre-G2 spawn.) When a plan IS present its
    `cost_accumulator` receives
    `result.total_cost_usd` on EVERY call (both modes) — the B1 accounting fix that replaces
    the last-call-only read at driver.py:976 with the RUN total. A finite `plan.per_call_cap`
    (only ever set on the G7 api-key path) forces `--max-budget-usd = min(caller, cap)`.
    """
    child_env = build_child_env(base_env, overrides=env_overrides)  # raises loudly (F10)
    # The per-call cap MECHANISM (plan G1): a finite `plan.per_call_cap` forces
    # `--max-budget-usd = min(caller, cap)`; `per_call_cap is None` (the subscription path,
    # S-1) forces NOTHING, so the caller's value (usually None) rides through unchanged.
    effective_budget = max_budget_usd
    if plan is not None and plan.per_call_cap is not None:
        effective_budget = (
            plan.per_call_cap
            if max_budget_usd is None
            else min(max_budget_usd, plan.per_call_cap)
        )
    argv = _build_argv(
        binary=binary,
        model=model,
        max_budget_usd=effective_budget,
        fallback_model=fallback_model,
    )
    # The subscription WALL (plan G2, S-4): EVERY subscription spawn is pinned under
    # pipeline-controlled settings that provably define NO apiKeyHelper, and no ambient/managed
    # apiKeyHelper may supply an api key. This is the ONLY transport at G2 (no api-key path is
    # built), so it fires on every spawn — generation AND the research seam alike, with no
    # unwalled path. FAIL-CLOSED: build_subscription_wall RAISES (a managed apiKeyHelper, or an
    # unverifiable controlled file) rather than ever spawning uncontrolled, and the raise happens
    # BEFORE the runner is called.
    wall = build_subscription_wall()
    argv += list(wall.argv)
    request = ProcessRequest(
        argv=tuple(argv),
        env=child_env,
        stdin_text=prompt,
        timeout_seconds=timeout_seconds,
        cwd=Path(cwd) if cwd is not None else None,
    )
    run = _subprocess_runner if runner is None else runner
    outcome = run(request)
    result = _classify(outcome)
    # B1 accounting fix: accumulate this call's cost into the run-scoped total on EVERY call
    # (both modes). `add(None)` is a no-op, so a costless outcome (timeout / cli-arg-error)
    # never fabricates a cost.
    if plan is not None:
        plan.cost_accumulator.add(result.total_cost_usd)
    return result
