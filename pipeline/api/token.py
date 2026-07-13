"""The resumption token (§20; the §21 wire contract): a documented, actor-held cursor.

Design authority: `docs/design.md` §20 (the pure-function run contract — session state is
ephemeral and ACTOR-held; the system persists none of it; the token is a documented,
actor-inspectable structure carrying an integrity/version stamp, the bound workspace, a
plan_hash, the run's inputs, the cursor, the produced ids, and the target folio-id ref —
ids only, never document contents), §21.1 (the token is a CURSOR, not a capability gate),
§21.7 (`invalid-token`; there is NO `stale-token`), §21.8 (idempotency by construction —
correctness comes from id existence, never the cursor).

**The integrity model — a digest, NOT a secret (INV-CORRECTNESS, §22.7).** `integrity_hash`
is a canonical SHA-256 DIGEST over the token body (via `pipeline.canonical`). There are no
shared secrets or keys in this system, so it is not a MAC and offers no defence against a
deliberate forgery — and that is CORRECT, because a forged or absent token can never cause
wrong output: every durable output is re-addressable by its content-addressed id from the
store WITHOUT the token (`lost-token-survivable`, §20). The digest exists to detect accidental
CORRUPTION and VERSION SKEW so the system fails LOUD (`invalid-token`, §3.1 no-overstep)
instead of misreading a mangled cursor — never to gate a correctness boundary the store
already owns.

**Detection, never misreading (§3.1).** `decode` refuses — as the ONE code `invalid-token`
(§21.7) — a token that is: structurally malformed (wrong key set); corrupt/tampered
(recomputed digest ≠ recorded); cross-version (`token_schema_version` ≠ current); or bound to
another workspace. There is deliberately NO age check: a well-formed out-of-date token is
never rejected (`re-use is idempotent`, §21.8; a drifted plan surfaces as `plan-stale`, §22.6,
not here) — §20 is explicit that there is no `stale-token`.

Lost-token survivability lives in the STORE, not here: `produced_ids` and `folio_id` are ids
that re-address their durable work directly (`store.output_path`, discovery, fetch — §21.3,
§21.5). This module imports no store and no SSOT; it validates ids only for well-formedness
via `pipeline.ids`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pipeline.canonical import CanonicalizationError, digest_full
from pipeline.ids import IdError, parse_id

__all__ = [
    "TOKEN_SCHEMA_VERSION",
    "TOKEN_BODY_KEYS",
    "TOKEN_WIRE_KEYS",
    "InvalidTokenError",
    "Token",
    "decode",
    "encode",
    "integrity_hash",
    "mint",
]

#: The current on-wire token schema. A wire token stamped with any other value is refused
#: (`invalid-token`, cross-version) — never silently coerced (§20, §3.1). Bump on any change
#: to `TOKEN_BODY_KEYS` or the body semantics.
TOKEN_SCHEMA_VERSION = 1

#: The token body — the fields the `integrity_hash` digests. Exactly these keys, always.
TOKEN_BODY_KEYS = (
    "token_schema_version",
    "workspace",
    "plan_hash",
    "inputs",
    "cursor",
    "produced_ids",
    "folio_id",
)

#: The full wire shape = the body plus the derived `integrity_hash`. `decode` requires the
#: wire to carry EXACTLY these keys (a differing key set → malformed → `invalid-token`).
TOKEN_WIRE_KEYS = (*TOKEN_BODY_KEYS, "integrity_hash")


class InvalidTokenError(ValueError):
    """§21.7 `invalid-token`: a token detected as malformed/corrupt/cross-version/wrong-
    workspace — refused, never misread (§20, §3.1). `reason` distinguishes the cause for the
    human hint; the machine CODE is uniformly `invalid-token`."""

    code = "invalid-token"

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"invalid-token: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Token:
    """One run's ephemeral session state (§20) — the actor holds it; the system persists none.

    Logical fields only; `integrity_hash` is DERIVED (computed at `encode`, verified at
    `decode`), never a stored member that could disagree with the body. `produced_ids` is an
    ordered tuple (the cursor keys on item coordinates, not indexes, §21.6, but order is
    preserved for the actor's convenience); `folio_id` is the target folio ref or None.
    """

    workspace: str
    plan_hash: str
    inputs: Mapping[str, Any] = field(default_factory=dict)
    cursor: Mapping[str, Any] = field(default_factory=dict)
    produced_ids: tuple[str, ...] = ()
    folio_id: str | None = None
    token_schema_version: int = TOKEN_SCHEMA_VERSION


def _body(token: Token) -> dict[str, Any]:
    """The canonical body dict (pure JSON) — the exact object the integrity digest covers.

    Built identically at `encode` (from a `Token`) and at `decode` (from the wire minus
    `integrity_hash`), so the two digests are byte-identical for an untampered token.
    """
    return {
        "token_schema_version": token.token_schema_version,
        "workspace": token.workspace,
        "plan_hash": token.plan_hash,
        "inputs": dict(token.inputs),
        "cursor": dict(token.cursor),
        "produced_ids": list(token.produced_ids),
        "folio_id": token.folio_id,
    }


def integrity_hash(token: Token) -> str:
    """The canonical SHA-256 digest over the token body (§20). A digest, not a secret."""
    try:
        return digest_full(_body(token))
    except CanonicalizationError as exc:  # a non-canonical input smuggled into inputs/cursor
        raise InvalidTokenError(
            "malformed", f"token body is not canonicalizable: {exc}"
        ) from exc


def mint(
    workspace: str,
    plan_hash: str,
    *,
    inputs: Mapping[str, Any] | None = None,
    cursor: Mapping[str, Any] | None = None,
    produced_ids: Sequence[str] = (),
    folio_id: str | None = None,
) -> Token:
    """Construct a `Token`, validating the run-facing invariants (never silent, §3.1).

    `workspace`/`plan_hash` must be non-empty strings; every `produced_ids` entry must be a
    well-formed §7.4 id; `folio_id`, when set, must be a folio-family id. Ids are validated
    for SHAPE only — resolution against a workspace store is the invoke layer's job (§21.1),
    kept out of this store-free module.
    """
    if not isinstance(workspace, str) or not workspace:
        raise InvalidTokenError("malformed", "a token binds a non-empty workspace (§20)")
    if not isinstance(plan_hash, str) or not plan_hash:
        raise InvalidTokenError("malformed", "a token carries a non-empty plan_hash (§20)")
    ids: list[str] = []
    for produced in produced_ids:
        try:
            parse_id(produced)
        except IdError as exc:
            raise InvalidTokenError(
                "malformed", f"produced id {produced!r} is not a valid id: {exc}"
            ) from exc
        ids.append(produced)
    if folio_id is not None:
        try:
            parsed = parse_id(folio_id)
        except IdError as exc:
            raise InvalidTokenError(
                "malformed", f"folio ref {folio_id!r} is not a valid id: {exc}"
            ) from exc
        if parsed.family != "folio":
            raise InvalidTokenError(
                "malformed", f"folio ref {folio_id!r} is not a folio id (§7.4: f-<hex12>)"
            )
    return Token(
        workspace=workspace,
        plan_hash=plan_hash,
        inputs=dict(inputs) if inputs else {},
        cursor=dict(cursor) if cursor else {},
        produced_ids=tuple(ids),
        folio_id=folio_id,
    )


def encode(token: Token) -> dict[str, Any]:
    """The wire token: the body + its computed `integrity_hash` (§20). JSON-ready (§13)."""
    body = _body(token)
    body["integrity_hash"] = integrity_hash(token)
    return body


def decode(wire: Any, *, expected_workspace: str) -> Token:
    """Validate a wire token for `expected_workspace` and return the `Token` (§20, §21.7).

    Refuses — always as `invalid-token`, never misreading (§3.1) — in this order:
    1. **malformed** — not a mapping with EXACTLY `TOKEN_WIRE_KEYS`;
    2. **tampered/corrupt** — recomputed body digest ≠ the recorded `integrity_hash`;
    3. **cross-version** — `token_schema_version` ≠ `TOKEN_SCHEMA_VERSION`;
    4. **wrong-workspace** — `workspace` ≠ `expected_workspace`.

    There is NO age/staleness check (§20): a well-formed out-of-date token is accepted;
    re-use is idempotent (§21.8) and plan drift surfaces later as `plan-stale` (§22.6).
    """
    if not isinstance(wire, Mapping):
        raise InvalidTokenError(
            "malformed", f"a token is a mapping, got {type(wire).__name__}"
        )
    if set(wire) != set(TOKEN_WIRE_KEYS):
        raise InvalidTokenError(
            "malformed",
            f"token keys must be exactly {sorted(TOKEN_WIRE_KEYS)!r}, got {sorted(wire)!r}",
        )
    recorded = wire["integrity_hash"]
    if not isinstance(recorded, str) or not recorded:
        raise InvalidTokenError("malformed", "integrity_hash must be a non-empty digest string")
    # Rebuild the exact body and recompute — a mangled/forged field flips the digest.
    body = {key: wire[key] for key in TOKEN_BODY_KEYS}
    try:
        recomputed = digest_full(body)
    except CanonicalizationError as exc:
        raise InvalidTokenError(
            "corrupt", f"token body is not canonicalizable: {exc}"
        ) from exc
    if recomputed != recorded:
        raise InvalidTokenError(
            "tampered",
            "integrity digest mismatch — the token is corrupt or tampered (§20; a digest "
            "detects corruption, not a keyed forgery — correctness rides ids, not the token)",
        )
    version = wire["token_schema_version"]
    if version != TOKEN_SCHEMA_VERSION:
        raise InvalidTokenError(
            "cross-version",
            f"token_schema_version {version!r} ≠ current {TOKEN_SCHEMA_VERSION} (§20)",
        )
    if wire["workspace"] != expected_workspace:
        raise InvalidTokenError(
            "wrong-workspace",
            f"token binds workspace {wire['workspace']!r}, invoked against "
            f"{expected_workspace!r} — workspaces never cross (§10)",
        )
    # A validated wire token round-trips to a Token whose re-encode reproduces this digest.
    return Token(
        workspace=wire["workspace"],
        plan_hash=wire["plan_hash"],
        inputs=dict(wire["inputs"]) if isinstance(wire["inputs"], Mapping) else wire["inputs"],
        cursor=dict(wire["cursor"]) if isinstance(wire["cursor"], Mapping) else wire["cursor"],
        produced_ids=tuple(wire["produced_ids"]),
        folio_id=wire["folio_id"],
        token_schema_version=version,
    )
