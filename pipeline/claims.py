"""The claim/lease registry: §22.3 acquire → live-skip → steal → holder-checked release.

Design authority: `docs/design.md` §22.3 (claims, the two qualified primitives, the steal),
§13.3 (encoding: one JSON object per file, **filename = the claimed id = the lock**, content
`{holder, lease_expiry}`), §22.7 (claim registry = lock authority; `claim(id)` takes only
the claim-registry handle — never an SSOT handle), §22.8/G1 (the verified primitives;
step-06 parameter sheet item 1), B4-4 (the slow-holder case: (a) commit is no-replace, so a
stolen-from worker's late commit LOSES; (b) release is holder-checked, so its late release
NO-OPS — it can never unlock the stealer's live critical section).

The protocol (per work-unit id; `fitted-id` is also a claim key — §22.3):

- **acquire** — atomic create-if-absent of `claims/<id>` (`O_CREAT|O_EXCL`, the ratified
  §22.8 primitive) with `{holder, lease_expiry}`. Outcomes ride the §22.6 code vocabulary:
  free → created → `ok`; live lease → skip → `claim-held` (caller moves on or polls by id);
  expired lease → **steal** → `lease-expired-redrive`. The steal is read-check-replace
  (temp + atomic replacing rename), deliberately NOT atomic: a double steal is a duplicate
  LLM **cost** leak, never a correctness leak — the no-replace commit admits exactly one
  winner per id (§22.3). No extra locking is added for it (parameter sheet item 1).
- **release** — HOLDER-CHECKED: re-READ the claim at release time (B4-4(b), G1 P4
  transcript); unlink only if `holder` is self; on mismatch the release is a NO-OP
  (`claim-held`); on a missing file it is a no-op (`already-released`, the G1-probe
  vocabulary — an internal outcome, not a §21.7 ResultItem code). This unlink is the SOLE
  sanctioned removal in the store plane (A4 build note): claims are self-expiring lock
  data, never retained content.

**Clocks are injectable** — no ambient `now()` inside the lease logic: every time read goes
through the registry's `clock` field (default `time.time`, epoch seconds UTC; tests inject
a manual clock). `lease_expiry` is recorded as an epoch-seconds JSON number; a lease is
live iff `clock() < lease_expiry`. The default TTL is the G2 seed (30 min — step-06
parameter sheet item 6; step 36 lands the ops-default constants that wire it).

**The nascent-claim window (implicit mtime lease):** `O_CREAT|O_EXCL` creates the name
atomically but the `{holder, lease_expiry}` write lands a moment later, so a racing reader
may glimpse an empty/partial claim. An unreadable claim is HELD for one IMPLICIT TTL
anchored at the claim file's mtime — the timestamp the ratified create itself left behind —
expiring at `mtime + ttl_seconds` (§22.4 PC7: a dead worker's lease must expire; §22.3:
the table is self-expiring); past that, the normal read-check-replace steal applies
(`lease-expired-redrive`), safe under a merely-slow nascent writer by the same B4-4
backstop as any steal. Seam: the implicit anchor is the FILESYSTEM clock (mtime) compared
against the injected `clock` — commensurate under the production default (`time.time`);
tests set mtime via `os.utime` to keep an injected manual clock coherent. Release stays
conservative: a release can never prove an unreadable claim its own, so it is never
unlinked (B4-4(b)).

INV-CORRECTNESS (§22.7): no SSOT import, no SSOT handle in any signature — the registry
answers "who holds the lock?", never "what is the status row?".
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pipeline.canonical import canonical_json_str
from pipeline.ids import parse_id
from pipeline.store import create_exclusive, write_replace

__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "AcquireOutcome",
    "ClaimError",
    "ClaimRecord",
    "ClaimRegistry",
    "Clock",
    "ReleaseOutcome",
]

#: The G2 seed (step-06 parameter sheet item 6): lease TTL 30 min — injectable per
#: registry; step 36's ops-default constants become the wiring source of record.
DEFAULT_LEASE_TTL_SECONDS = 30.0 * 60.0

#: Epoch-seconds time source (UTC). Injectable — lease logic never calls `time.time`
#: directly; the module default is applied only at the constructor boundary.
Clock = Callable[[], float]


class ClaimError(RuntimeError):
    """The registry could not reach a defined §22.3 outcome — refused loudly."""

    code = "claim-registry-error"


@dataclass(frozen=True)
class ClaimRecord:
    """A parsed `{holder, lease_expiry}` claim record (§13.3)."""

    holder: str
    lease_expiry: float


@dataclass(frozen=True)
class AcquireOutcome:
    """One §22.3 acquisition outcome, coded per §22.6.

    `code`: `ok` (claim created — do the work) · `claim-held` (live lease, or an
    unreadable-nascent claim within its one implicit mtime-anchored TTL — skip; `holder`
    names the incumbent when readable) · `lease-expired-redrive` (expired lease stolen —
    explicit or implicit — do the work). `acquired` is True exactly when this caller now
    holds the claim; `lease_expiry` is this caller's lease end when acquired, else the
    incumbent's (None when unreadable).
    """

    code: Literal["ok", "claim-held", "lease-expired-redrive"]
    acquired: bool
    holder: str | None
    lease_expiry: float | None


@dataclass(frozen=True)
class ReleaseOutcome:
    """One §22.3 holder-checked release outcome.

    `code`: `ok` (holder matched — claim unlinked) · `claim-held` (holder mismatch or
    unreadable claim — NO-OP, B4-4(b)) · `already-released` (no claim file — no-op; the
    G1-probe vocabulary for the benign late-release-after-stealer-finished case).
    `released` is True exactly when THIS call unlinked the claim file.
    """

    code: Literal["ok", "claim-held", "already-released"]
    released: bool
    holder: str | None


def _load(path: Path) -> ClaimRecord | Literal["missing", "unreadable"]:
    """Read one claim file: a validated record, `missing`, or `unreadable` (nascent/torn)."""
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return "missing"
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return "unreadable"
    if not isinstance(obj, dict):
        return "unreadable"
    holder = obj.get("holder")
    expiry = obj.get("lease_expiry")
    if not isinstance(holder, str) or not holder:
        return "unreadable"
    if isinstance(expiry, bool) or not isinstance(expiry, int | float) or not math.isfinite(expiry):
        return "unreadable"
    return ClaimRecord(holder=holder, lease_expiry=float(expiry))


@dataclass(frozen=True)
class ClaimRegistry:
    """The workspace-scoped claim/lease table (§22.3): one registry per claims dir + holder.

    `claims_dir` is the workspace's `claims/` store (a `WorkspaceStore.claims_dir` in
    production; any tmp dir in tests) — the only handle the registry holds (§22.7).
    `holder` is this worker's identity for holder-compare semantics. The claim filename is
    the claimed id EXACTLY (validated via `pipeline.ids.parse_id` — §13.3/§7.4), never an
    extension.
    """

    claims_dir: Path
    holder: str
    ttl_seconds: float = DEFAULT_LEASE_TTL_SECONDS
    clock: Clock = time.time

    def __post_init__(self) -> None:
        object.__setattr__(self, "claims_dir", Path(self.claims_dir))
        if not isinstance(self.holder, str) or not self.holder:
            raise ClaimError("claim-registry-error: holder must be a non-empty string (§22.3)")
        if (
            isinstance(self.ttl_seconds, bool)
            or not isinstance(self.ttl_seconds, int | float)
            or not math.isfinite(self.ttl_seconds)
            or self.ttl_seconds <= 0
        ):
            raise ClaimError(
                f"claim-registry-error: ttl_seconds must be a positive finite number, "
                f"got {self.ttl_seconds!r}"
            )

    def path_for(self, id_str: str) -> Path:
        """`claims/<id>` — the filename IS the claimed id IS the lock (§13.3), no extension."""
        parse_id(id_str)
        self.claims_dir.mkdir(parents=True, exist_ok=True)
        return self.claims_dir / id_str

    def _record_line(self, lease_expiry: float) -> bytes:
        record = {"holder": self.holder, "lease_expiry": lease_expiry}
        return (canonical_json_str(record) + "\n").encode("utf-8")

    def acquire(self, id_str: str) -> AcquireOutcome:
        """Claim `id_str` before expensive work (§22.3). Never blocks, never waits.

        Free → atomic create-if-absent wins → `ok`. Live lease → `claim-held` (skip).
        Expired lease → steal via read-check-replace → `lease-expired-redrive`. The
        vanishing-claim race (incumbent releases between our loss and our read) retries
        the create — bounded, then refused loudly.
        """
        path = self.path_for(id_str)
        for _ in range(64):
            now = self.clock()
            expiry = now + self.ttl_seconds
            try:
                create_exclusive(path, self._record_line(expiry))
            except FileExistsError:
                pass
            else:
                return AcquireOutcome(
                    code="ok", acquired=True, holder=self.holder, lease_expiry=expiry
                )
            current = _load(path)
            if current == "missing":
                continue  # released in the window — retry the create-if-absent
            if current == "unreadable":
                # Nascent/torn claim: no readable lease_expiry. The O_EXCL create left an
                # mtime — treat it as an IMPLICIT lease anchored there (§22.4 PC7: a dead
                # worker's lease must expire; §22.3: the table is self-expiring). Same TTL,
                # same steal primitive, same B4-4 backstop as any expired lease.
                try:
                    anchored = os.stat(path).st_mtime
                except FileNotFoundError:
                    continue  # vanished in the window — retry the create-if-absent
                if self.clock() < anchored + self.ttl_seconds:
                    return AcquireOutcome(
                        code="claim-held", acquired=False, holder=None, lease_expiry=None
                    )
                steal_expiry = self.clock() + self.ttl_seconds
                write_replace(path, self._record_line(steal_expiry))
                return AcquireOutcome(
                    code="lease-expired-redrive",
                    acquired=True,
                    holder=self.holder,
                    lease_expiry=steal_expiry,
                )
            if self.clock() < current.lease_expiry:
                return AcquireOutcome(
                    code="claim-held",
                    acquired=False,
                    holder=current.holder,
                    lease_expiry=current.lease_expiry,
                )
            # Expired → steal: read-check-replace (temp + atomic replacing rename, §22.3).
            # Deliberately not atomic — a double steal is a cost leak, never correctness.
            steal_expiry = self.clock() + self.ttl_seconds
            write_replace(path, self._record_line(steal_expiry))
            return AcquireOutcome(
                code="lease-expired-redrive",
                acquired=True,
                holder=self.holder,
                lease_expiry=steal_expiry,
            )
        raise ClaimError(
            f"claim-registry-error: acquire({id_str!r}) exhausted retries against a "
            "vanishing claim file — filesystem misbehaving?"
        )

    def release(self, id_str: str) -> ReleaseOutcome:
        """HOLDER-CHECKED release (§22.3 S6; B4-4(b)): re-read at release time, then unlink.

        Only a claim whose `holder` equals this registry's holder is unlinked (`ok`). A
        mismatch — the stolen-from worker's late release — is a NO-OP (`claim-held`): it
        can never unlock the stealer's live critical section. A missing file is a no-op
        (`already-released`). An unreadable claim can never be proven our own → no-op
        (`claim-held`). This unlink is the sole sanctioned store-plane removal (A4).
        """
        path = self.path_for(id_str)
        current = _load(path)
        if current == "missing":
            return ReleaseOutcome(code="already-released", released=False, holder=None)
        if current == "unreadable":
            return ReleaseOutcome(code="claim-held", released=False, holder=None)
        if current.holder != self.holder:
            return ReleaseOutcome(code="claim-held", released=False, holder=current.holder)
        try:
            os.unlink(path)
        except FileNotFoundError:
            return ReleaseOutcome(code="already-released", released=False, holder=None)
        return ReleaseOutcome(code="ok", released=True, holder=self.holder)

    def peek(self, id_str: str) -> ClaimRecord | None:
        """Read-only view of the current claim (diagnostics/polling — §22.3 'polls by id').

        None when no claim file exists OR the record is unreadable (nascent/torn — see the
        module doc; an unreadable claim holds for acquire only within its implicit
        mtime-anchored TTL and is never released).
        """
        record = _load(self.path_for(id_str))
        return record if isinstance(record, ClaimRecord) else None
