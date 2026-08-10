"""The single entitled SUBSCRIPTION user — the U==entitled check + admin API (plan G5, §21.10).

Names EXACTLY ONE user entitled to the subscription fallback at a time (ToS: the subscription is
used ONLY for that one user). The entitlement is USER-level, single-valued, and SWAPPABLE:
reassigning REPLACES the prior value — there is never a second entitled user. It is persisted in
the SAME gitignored transport config as the G4 key assignments
(`instance/ops/transport/config.yaml`) via the SAME store (`pipeline.spend.assignment`): one store,
one renderer, so the entitlement and the assignment block never clobber each other.

This gate STORES + CHECKS the entitlement only. It selects no transport and spends nothing —
transport selection ("subscription is used ONLY for the one entitled user") is the G7 resolver,
which CONSULTS `is_entitled` / `entitled_user`. There is NO spend surface here.

Two invariants shape every line:

- **I2/I3 — the entitled user is set ONLY via config/admin, NEVER a run parameter.** The mutators
  (`set_entitled_user` / `clear_entitled_user`) are reachable ONLY through the Tier-A
  `transport set-subscription-user` / `transport clear-subscription-user` admin verbs. No
  `generate` / `invoke` / `begin-session` / spend-verb argument parser exposes any flag that
  names or changes the subscription user — a run can pick subscription-vs-key (a future per-run
  OVERRIDE, G7) but can NEVER re-point WHO is entitled.

- **single-valued + swappable.** `set_entitled_user` REPLACES; the config carries at most one
  `subscription_user`; `is_entitled` is a PURE equality against that one value.

The check API (`entitled_user`, `is_entitled`) is what G7 consults; the admin API
(`set_entitled_user`, `clear_entitled_user`) is what the two transport verbs call.
"""

from __future__ import annotations

import os
from pathlib import Path

from pipeline.spend.assignment import load_store, save_store
from pipeline.workspace_name import WorkspaceNameError, validate_user_segment

__all__ = [
    "EntitlementError",
    "InvalidUserError",
    "clear_entitled_user",
    "entitled_user",
    "is_entitled",
    "set_entitled_user",
]


class EntitlementError(RuntimeError):
    """Base: an entitlement operation hit a state it must refuse LOUDLY, never guess through.

    One catchable family for the CLI (mirrors `AssignmentError` in the sibling G4 module)."""

    code = "entitlement-error"


class InvalidUserError(EntitlementError):
    """`set-subscription-user <u>` was given a `<u>` that is not a valid §23 user segment.

    Wraps the `WorkspaceNameError.detail` so a bad / uppercase / empty / traversing user surfaces
    as ONE entitlement-error family — and NOTHING is written (the validation runs before any load
    or save)."""

    code = "entitlement-bad-user"


# ---------------------------------------------------------------------------------------
# The check API — pure equality against the config (what the G7 resolver consults)
# ---------------------------------------------------------------------------------------


def entitled_user(framework_root: str | os.PathLike[str]) -> str | None:
    """The SINGLE entitled subscription user under `framework_root`, or `None` if none is set.

    Reads the shared transport config (`instance/ops/transport/config.yaml`). A missing config → no
    entitlement (`None`). A malformed config raises the G4 `ConfigError` (never a silent guess)."""
    return load_store(framework_root).entitled_user


def is_entitled(framework_root: str | os.PathLike[str], user: object) -> bool:
    """True iff `user` is EXACTLY the one entitled subscription user (a PURE equality check).

    This is what the G7 resolver consults ("subscription is used ONLY for the one entitled user").
    A non-string / empty `user` — and the unset case (`entitled_user is None`) — is `False`
    (nobody is entitled when none is set; `None == None` never entitles)."""
    if not isinstance(user, str) or user == "":
        return False
    return load_store(framework_root).entitled_user == user


# ---------------------------------------------------------------------------------------
# The admin API — reachable ONLY via the two Tier-A `transport …-subscription-user` verbs (I2/I3)
# ---------------------------------------------------------------------------------------


def set_entitled_user(framework_root: str | os.PathLike[str], user: str) -> Path:
    """Set (REPLACE) the entitled subscription user; return the written config path (I2/I3).

    Validates `user` as a §23 user segment FIRST (a bad / uppercase / empty / traversing user is a
    loud `InvalidUserError` and NOTHING is written), then REPLACES any prior entitlement
    (single-valued — never a second entry) and saves the shared config atomically. Selects no
    transport, spends nothing."""
    try:
        validate_user_segment(framework_root, user)
    except WorkspaceNameError as exc:
        raise InvalidUserError(f"entitlement-bad-user: {exc.detail} (§23)") from None
    store = load_store(framework_root)
    store.set_entitled_user(user)  # REPLACES any prior — single-valued, never a second entry.
    return save_store(store, framework_root)


def clear_entitled_user(framework_root: str | os.PathLike[str]) -> Path:
    """Remove the entitled subscription user (idempotent); return the written config path.

    Clearing an unset entitlement is a clean no-op (the config simply carries no
    `subscription_user`). Preserves the G4 key assignments (one store, one renderer). No spend."""
    store = load_store(framework_root)
    store.clear_entitled_user()
    return save_store(store, framework_root)
