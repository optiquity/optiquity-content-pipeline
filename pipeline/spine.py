"""The S0–S6 execution spine (§22.3): one work unit, driven crash-safe end to end.

Design authority: `docs/design.md` §22.3 (the canonical ordering; the two qualified
primitives), §22.7 (INV-CORRECTNESS — the crash table and the guardrails, built WITH the
spine, not bolted on), §7.4 (the S0 preimage check), §21.2/§13.3 (S4 folio-marker
semantics), §23 (store homes), B4-4 (slow-holder steal safety); plan step 21.

The canonical sequence (§22.7 "crash-safety by ordering"). The spine adds NO filesystem
primitives of its own (the step-20 interface contract): every write goes through
`pipeline.store`, every lock through `pipeline.claims`:

    S0  idempotency pre-check — output EXISTENCE (`store.is_done`) + the §7.4 preimage
        check, BOTH reading only the output store. Existing id + matching preimage →
        `already-materialized` short-circuit: no work, no claim — but S4/S5 still run,
        because a re-drive after a crash between S3 and S5 must complete the lagging
        bookkeeping ("the re-drive is an `already-materialized` no-op that then advances
        the row", §22.7). Existing id + DIFFERENT preimage → loud `PreimageMismatchError`
        (§7.4: never silent reuse).
    S1  acquire the claim (`claims.acquire`): free → `ok`; live lease → `claim-held`
        (return; the caller moves on or polls by id, §22.3); expired lease → steal
        (`lease-expired-redrive`) and proceed.
    S2  work → temp: `unit.payload()` runs only under a held claim; the bytes are staged
        BESIDE the target (`store.stage_temp`), never at it.
    S3  atomic NO-REPLACE commit (`store.commit_new`): a commit finding the target
        present discards its temp and CONTINUES as `already-materialized` — the designed
        loser path (§22.3, B4-4a), never an error, never an overwrite.
    S4  folio append (when applicable): marker-per-member with §21.2 semantics —
        idempotent dedupe / `member-updated`; a membership record, never a generation
        gate (§22.7).
    S5  advance the SSOT — LAST among the bookkeeping writes, SIDE-EFFECT-ONLY. The SSOT
        does not exist yet (plan step 22); S5 is the pluggable `AdvanceHook` this module
        DEFINES but does not implement. Its return value is discarded and its exceptions
        are contained (`SpineResult.advance_error`): a slow, failing, or offline SSOT
        writer only lags the human view (§22.7) — it can never alter control flow, and
        S6 still runs.
    S6  holder-checked release (`claims.release`): unlink only if the claim is ours; a
        stolen-from worker's late release NO-OPS (`claim-held`, B4-4b).

Every crash point is benign (the §22.7 crash table): before S3 the target is absent and
the claim self-expires (a dropped temp is inert and identifiable — never GC'd here, A4);
from S3 on, the id exists and any re-drive short-circuits at S0 to `already-materialized`
and completes S4/S5. The critical section is S1–S3. A payload EXCEPTION propagates
without release — indistinguishable from a crash at S2 and exactly as benign (§22.4 PC7:
the lease expires → safe re-drive).

INV-CORRECTNESS guardrails built here (§22.7):

1. **Signature scoping** — `drive` takes exactly the output-store handle
   (`WorkspaceStore`) and the claim-registry handle (`ClaimRegistry`); no SSOT handle
   TYPE exists in this module. (`store.is_done` / `claims.acquire` are already scoped
   the same way — step 20.)
2. **The import lint** — the correctness modules (`store`, `claims`, this spine, the
   future sweep) must never import an SSOT module; `tests/test_inv_correctness.py` is
   the CI teeth (T4: a custom pytest/AST check — the test job fails the build).
3. **The SSOT contract stub** — `AdvanceHook = Callable[[str], None]`: write-only
   w.r.t. control flow. No return value is consumed, no predicate exists for the spine
   to branch on; step 22 plugs its monotonic `advance()` into exactly this shape.

**Holder identities are minted, not chosen** (step-20 carry-forward RV-4): holder-compare
is cooperative trust, so a guessable/duplicated holder string could release another
worker's claim. `mint_holder()` returns a collision-resistant random token (128 random
bits; the pid prefix is diagnostic garnish, never the identity), and `registry_for` is
the one-call registry constructor that wires it — this module is where the spine plane
constructs holders.

`checkpoint` is an observability/test seam ONLY: it receives each `S_POINTS` label once,
immediately after that stage completes, and returns nothing the spine reads. The §22.7
conformance battery injects crashes there (`os._exit`); production callers keep the
default no-op.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pipeline.canonical import canonical_json_str
from pipeline.claims import (
    DEFAULT_LEASE_TTL_SECONDS,
    AcquireOutcome,
    ClaimRegistry,
    Clock,
    ReleaseOutcome,
)
from pipeline.ids import PreimageLookup, preimage_check
from pipeline.store import (
    AlreadyMaterializedError,
    WorkspaceStore,
    commit_new,
    is_done,
    stage_temp,
    write_new,
    write_replace,
)

__all__ = [
    "S_POINTS",
    "AdvanceHook",
    "Checkpoint",
    "FolioAppendOutcome",
    "FolioMembership",
    "SpineError",
    "SpineResult",
    "WorkUnit",
    "append_folio_member",
    "drive",
    "mint_holder",
    "registry_for",
]

#: The canonical S-point labels in execution order (§22.3/§22.7). The `checkpoint` seam
#: receives exactly these; each fires once, immediately after its stage completes.
S_POINTS = ("S0", "S1", "S2", "S3", "S4", "S5", "S6")

#: Guardrail 3 (§22.7): the S5 hook shape. WRITE-ONLY w.r.t. control flow — it takes the
#: unit id whose row should advance and returns nothing the spine consumes; there is no
#: predicate to branch on. Step 22's monotonic `advance()` plugs in here.
AdvanceHook = Callable[[str], None]

#: The observability/test seam: called with one `S_POINTS` label after each stage.
Checkpoint = Callable[[str], None]


class SpineError(RuntimeError):
    """The spine met state it can never repair silently — refused loudly."""

    code = "spine-error"


@dataclass(frozen=True)
class FolioMembership:
    """One S4 target: add the unit's artifact to `folio_id` (§9.2; record A4-4)."""

    folio_id: str
    pin: str | None = None
    role: str | None = None


@dataclass(frozen=True)
class FolioAppendOutcome:
    """One §21.2 member-append outcome.

    `code`: `ok` (marker created, or the idempotent identical-re-append dedupe no-op) ·
    `member-updated` (warn — differing `pin`/`role`; atomic in-place update of that one
    marker, `added_ts` preserved, last-writer-wins, never silent). `created` is True
    exactly when THIS call created the marker.
    """

    folio_id: str
    code: Literal["ok", "member-updated"]
    created: bool


@dataclass(frozen=True)
class WorkUnit:
    """One id-keyed unit of work for the spine.

    `id` is the settled work-unit id — claim key and output key alike (§22.1).
    `payload` is S2: the (expensive) work, returning the output-record bytes; it runs
    only after the claim is held. `preimage` is the CANDIDATE §7.4 preimage for S0's
    check (None = existence-only, until the owning binding formats land — §15/§16/§17).
    `folios` are the S4 targets — artifact-level units only (§9.2); empty when S4 does
    not apply.
    """

    id: str
    payload: Callable[[], bytes]
    preimage: Any = None
    folios: tuple[FolioMembership, ...] = ()


@dataclass(frozen=True)
class SpineResult:
    """One drive's outcome, coded from the closed §21.7/§22.6 vocabulary (no new codes).

    `code`: `ok` (our S3 commit won) · `already-materialized` (the S0 short-circuit, or
    our S3 lost — either way the id is done and the trailing bookkeeping was completed) ·
    `claim-held` (live lease; skipped — the caller moves on or polls by id, §22.3).
    `claim` is None exactly on the S0 short-circuit (no claim was ever taken); the S1
    steal is visible as `claim.code == "lease-expired-redrive"`. `release` is None
    whenever no claim was held. `advanced` is True iff the S5 hook ran to completion; a
    contained hook failure is reported in `advance_error` and NEVER alters `code`
    (§22.7: S5 is side-effect-only).
    """

    id: str
    code: Literal["ok", "already-materialized", "claim-held"]
    materialized: bool
    short_circuit: bool
    claim: AcquireOutcome | None
    folio: tuple[FolioAppendOutcome, ...]
    advanced: bool
    advance_error: str | None
    release: ReleaseOutcome | None


# ---------------------------------------------------------------------------
# Holder minting (step-20 carry-forward RV-4): random tokens, never guessable.
# ---------------------------------------------------------------------------


def mint_holder() -> str:
    """A collision-resistant worker holder token (RV-4).

    128 random bits — never guessable and never derived from ambient identity alone:
    two workers minting on the SAME pid still get distinct holders, so one worker can
    never satisfy another's holder-compare (B4-4b). The pid prefix is diagnostic
    garnish for humans reading claim files; the entropy is the identity.
    """
    return f"h{os.getpid()}-{os.urandom(16).hex()}"


def registry_for(
    store: WorkspaceStore,
    *,
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS,
    clock: Clock = time.time,
) -> ClaimRegistry:
    """A claim registry on this workspace's `claims/`, holder freshly MINTED (RV-4)."""
    return ClaimRegistry(
        store.claims_dir, holder=mint_holder(), ttl_seconds=ttl_seconds, clock=clock
    )


# ---------------------------------------------------------------------------
# S4: the folio member append (§21.2 semantics over the §13.3 marker encoding).
# ---------------------------------------------------------------------------


def _marker_bytes(record: dict[str, Any]) -> bytes:
    return (canonical_json_str(record) + "\n").encode("utf-8")


def _parse_marker(path: Path, raw: bytes) -> dict[str, Any]:
    """Validate one member-marker record `{added_ts, pin?, role?}` (§13.3, A4-4)."""
    try:
        obj: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        obj = None
    added = obj.get("added_ts") if isinstance(obj, dict) else None
    if isinstance(added, bool) or not isinstance(added, int | float):
        raise SpineError(
            f"spine-error: corrupt folio member marker {path} — markers are written "
            "atomically (§13.3/§21.2), so this is damage, not a race; refusing to guess"
        )
    return obj


def _record_for(membership: FolioMembership, added_ts: float) -> dict[str, Any]:
    record: dict[str, Any] = {"added_ts": added_ts}
    if membership.pin is not None:
        record["pin"] = membership.pin
    if membership.role is not None:
        record["role"] = membership.role
    return record


def append_folio_member(
    store: WorkspaceStore,
    membership: FolioMembership,
    artifact_id: str,
    *,
    clock: Clock,
) -> FolioAppendOutcome:
    """S4: append one member marker — §21.2 semantics, explicit, never silent.

    Fresh member → create via the no-replace primitive → `ok` (created). Identical
    re-append (same `pin` and `role`) → the idempotent dedupe no-op → `ok`. Differing
    `pin`/`role` → atomic in-place update via replacing rename with the ORIGINAL
    `added_ts` preserved → `member-updated` (§21.2; concurrent differing updates
    resolve last-writer-wins, never torn). Membership is append-only in v1 (§9.2):
    nothing here removes a marker. Never a generation gate (§22.7).
    """
    path = store.folio_member_path(membership.folio_id, artifact_id)
    for _ in range(8):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            try:
                write_new(path, _marker_bytes(_record_for(membership, clock())))
            except AlreadyMaterializedError:
                continue  # raced: another appender created it — loop to compare (§21.2)
            return FolioAppendOutcome(membership.folio_id, code="ok", created=True)
        existing = _parse_marker(path, raw)
        if existing.get("pin") == membership.pin and existing.get("role") == membership.role:
            return FolioAppendOutcome(membership.folio_id, code="ok", created=False)
        updated = _record_for(membership, existing["added_ts"])  # added_ts PRESERVED
        write_replace(path, _marker_bytes(updated))
        return FolioAppendOutcome(membership.folio_id, code="member-updated", created=False)
    raise SpineError(
        f"spine-error: folio append for {artifact_id!r} in {membership.folio_id!r} "
        "exhausted retries against a vanishing marker — filesystem misbehaving?"
    )


def _append_folios(
    store: WorkspaceStore, unit: WorkUnit, clock: Clock
) -> tuple[FolioAppendOutcome, ...]:
    return tuple(
        append_folio_member(store, membership, unit.id, clock=clock) for membership in unit.folios
    )


# ---------------------------------------------------------------------------
# S5: the pluggable SSOT-advance hook — defined here, implemented at step 22.
# ---------------------------------------------------------------------------


def _run_advance_hook(advance: AdvanceHook | None, id_str: str) -> tuple[bool, str | None]:
    """S5, side-effect-only (§22.7): return value DISCARDED, exceptions CONTAINED."""
    if advance is None:
        return False, None
    try:
        advance(id_str)  # any return value is deliberately ignored (guardrail 3)
    except Exception as exc:  # a failing SSOT writer only lags the human view (§22.7)
        return False, f"{type(exc).__name__}: {exc}"
    return True, None


# ---------------------------------------------------------------------------
# The spine.
# ---------------------------------------------------------------------------


def _no_checkpoint(label: str) -> None:
    """The production default: the seam observes nothing and nothing observes it."""


def drive(
    unit: WorkUnit,
    *,
    store: WorkspaceStore,
    claims: ClaimRegistry,
    recorded_preimage: PreimageLookup | None = None,
    advance: AdvanceHook | None = None,
    checkpoint: Checkpoint = _no_checkpoint,
) -> SpineResult:
    """Drive one work unit through the canonical S0–S6 sequence (§22.3/§22.7).

    Handles in scope: exactly the output store and the claim registry — INV-CORRECTNESS
    signature scoping (§22.7 guardrail 1); there is no SSOT handle to pass.
    `recorded_preimage` reads the RECORDED §7.4 preimage back from the OUTPUT STORE for
    S0's comparison (the owning IR/fit/render binding once §15/§16/§17 land; None while
    the id is unseen). `advance` is the write-only S5 hook (guardrail 3). `checkpoint`
    is the observability/test seam (module doc).
    """
    done = is_done(store, unit.id)  # S0, existence half: output store ONLY (§22.7)
    if done and unit.preimage is not None:
        recorded = recorded_preimage(unit.id) if recorded_preimage is not None else None
        preimage_check(unit.id, unit.preimage, recorded)  # mismatch = LOUD (§7.4)
    checkpoint("S0")
    clock = claims.clock  # the one injected time source; stamps S4 `added_ts` (§13.3)
    if done:
        # The already-materialized re-drive: no work, no claim — complete the lagging
        # bookkeeping (S4 idempotent, S5 monotonic) per the §22.7 crash table.
        folio = _append_folios(store, unit, clock)
        checkpoint("S4")
        advanced, advance_error = _run_advance_hook(advance, unit.id)
        checkpoint("S5")
        return SpineResult(
            id=unit.id,
            code="already-materialized",
            materialized=False,
            short_circuit=True,
            claim=None,
            folio=folio,
            advanced=advanced,
            advance_error=advance_error,
            release=None,
        )
    claim = claims.acquire(unit.id)  # S1
    checkpoint("S1")
    if not claim.acquired:
        return SpineResult(
            id=unit.id,
            code="claim-held",
            materialized=False,
            short_circuit=False,
            claim=claim,
            folio=(),
            advanced=False,
            advance_error=None,
            release=None,
        )
    data = unit.payload()  # S2: the expensive work, under a held claim
    if not isinstance(data, bytes):
        raise SpineError(
            f"spine-error: unit {unit.id!r} payload returned {type(data).__name__}, "
            "not bytes — the spine stages exactly the bytes the store commits (§22.3)"
        )
    target = store.output_path(unit.id)
    temp = stage_temp(target, data)
    checkpoint("S2")
    materialized = True
    try:
        commit_new(temp, target)  # S3: atomic NO-REPLACE
    except AlreadyMaterializedError:
        materialized = False  # the designed loser path (§22.3/B4-4a); bookkeeping continues
    checkpoint("S3")
    folio = _append_folios(store, unit, clock)  # S4
    checkpoint("S4")
    advanced, advance_error = _run_advance_hook(advance, unit.id)  # S5: LAST, side-effect-only
    checkpoint("S5")
    release = claims.release(unit.id)  # S6: holder-checked (B4-4b)
    checkpoint("S6")
    return SpineResult(
        id=unit.id,
        code="ok" if materialized else "already-materialized",
        materialized=materialized,
        short_circuit=False,
        claim=claim,
        folio=folio,
        advanced=advanced,
        advance_error=advance_error,
        release=release,
    )
