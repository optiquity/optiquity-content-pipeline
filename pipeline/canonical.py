"""Canonical JSON (sorted keys, deterministic bytes) + SHA-256 digest helpers + canonical sets.

Design authority: `docs/design.md` §7.2 (identity preimages are canonical maps — sorted keys,
sorted deduped goal-set; identical logical inputs MUST yield identical ids), §7.4 (digest
form: SHA-256 over the canonical preimage; `hex16` roots for artifact/run ids, `hex12` for
folio ids and revision qualifiers, the FULL digest recorded in bindings), §12.4 (canonical
set semantics: value union + dedupe by exact value + sorted canonicalization), §13.1/§13.3
(machine records are JSON).

Canonical form: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
allow_nan=False)` encoded UTF-8. Anything without exactly one deterministic rendering is
REFUSED, never guessed — the same refuse-don't-coerce discipline as `pipeline/attrtypes.py`:

- mapping keys must be `str` (json.dumps silently stringifies int/bool keys — refused here
  by a pre-walk, because a silent key coercion is a preimage corruption);
- floats must be finite (JSON has no NaN/Infinity);
- Python `set`/`bytes`/arbitrary objects are refused (`canonical_set` turns unordered leaf
  sets into their canonical LIST form first — §12.4);
- **`datetime.date` serializes as its ISO-8601 string (`"YYYY-MM-DD"`) — the STEP-8 DECISION
  the G4 gate assigned here** (step-2 D2 disposition: "serialize dates as ISO-8601 strings or
  refuse them — decide there, deterministically"). Decision grounds: §11.1 ratifies
  `date-window` as an attribute type, and §7.2 requires every effective-value deviation to
  enter the identity preimage — refusing dates would make a ratified type unpreimageable.
  `date.isoformat()` is total and single-valued (one date → exactly one string), and it
  reproduces the author's YAML 1.2 source token byte-for-byte (`2026-07-12` loads as
  `date(2026, 7, 12)` and canonicalizes back to `"2026-07-12"`), so the recorded preimage
  stays source-faithful and human-readable. No date/string ambiguity can arise inside a
  preimage: an attribute's type is schema-fixed (§11.1), so one path never carries both.
- **`datetime.datetime` is REFUSED** (checked FIRST — it subclasses `datetime.date`):
  `date-window` is date-granular (§6.2 operators are calendar-level; attrtypes refuses
  timestamps), and naive-vs-aware timestamps have no deterministic rendering without a
  timezone policy this step has no mandate to invent. A datetime reaching canonicalization
  means upstream typed validation was bypassed — fail loudly.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
from collections.abc import Iterable
from typing import Any

__all__ = [
    "CanonicalizationError",
    "canonical_json_bytes",
    "canonical_json_str",
    "canonical_set",
    "digest_full",
    "digest_hex12",
    "digest_hex16",
    "sha256_hex",
]

_LEAF_SET_TYPES = (str, bool, int, float)


class CanonicalizationError(ValueError):
    """A value with no single deterministic canonical-JSON rendering — refused, never guessed."""

    code = "canonicalization-refused"


def _validate(obj: Any, path: str) -> None:
    """Pre-walk refusing everything json.dumps would coerce, guess at, or crash on."""
    # datetime.datetime FIRST — it subclasses datetime.date (module docstring: refused).
    if isinstance(obj, datetime.datetime):
        raise CanonicalizationError(
            f"canonicalization-refused at {path}: datetime.datetime has no deterministic "
            "canonical form (timezone policy); date-window values are bare dates"
        )
    if isinstance(obj, datetime.date):
        return  # serialized as ISO-8601 by the json default hook
    if obj is None or isinstance(obj, str | bool | int):
        return
    if isinstance(obj, float):
        if not math.isfinite(obj):
            raise CanonicalizationError(
                f"canonicalization-refused at {path}: non-finite float {obj!r} (JSON has no "
                "NaN/Infinity)"
            )
        return
    if isinstance(obj, dict):
        for key, value in obj.items():
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"canonicalization-refused at {path}: non-string mapping key {key!r} "
                    "(json.dumps would silently stringify it — a preimage corruption)"
                )
            _validate(value, f"{path}.{key}")
        return
    if isinstance(obj, list | tuple):
        for i, item in enumerate(obj):
            _validate(item, f"{path}[{i}]")
        return
    if isinstance(obj, set | frozenset):
        raise CanonicalizationError(
            f"canonicalization-refused at {path}: raw Python sets are unordered — pass "
            "canonical_set(...) output (a canonical list, §12.4) instead"
        )
    raise CanonicalizationError(
        f"canonicalization-refused at {path}: unsupported type {type(obj).__name__}"
    )


def _json_default(obj: Any) -> str:
    # _validate has already refused datetime.datetime; only bare dates reach here.
    if isinstance(obj, datetime.date) and not isinstance(obj, datetime.datetime):
        return obj.isoformat()
    raise CanonicalizationError(  # pragma: no cover — _validate refuses these first
        f"canonicalization-refused: unsupported type {type(obj).__name__}"
    )


def canonical_json_str(obj: Any) -> str:
    """Render `obj` as canonical JSON text: sorted keys, compact separators, raw UTF-8."""
    _validate(obj, path="$")
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=_json_default,
    )


def canonical_json_bytes(obj: Any) -> bytes:
    """Canonical bytes of `obj`: identical logical inputs → identical bytes (§7.2)."""
    return canonical_json_str(obj).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """Full lowercase-hex SHA-256 of raw bytes (64 chars)."""
    return hashlib.sha256(data).hexdigest()


def digest_full(obj: Any) -> str:
    """Full SHA-256 hex digest (64 chars) of the canonical JSON bytes of `obj`.

    §7.4: the FULL digest is what bindings and lineage record; the id string carries a
    truncation of this same digest.
    """
    return sha256_hex(canonical_json_bytes(obj))


def digest_hex16(obj: Any) -> str:
    """First 16 lowercase hex chars (64 bits) of the digest — artifact/run id roots (§7.4)."""
    return digest_full(obj)[:16]


def digest_hex12(obj: Any) -> str:
    """First 12 lowercase hex chars (48 bits) — folio ids and revision qualifiers (§7.4)."""
    return digest_full(obj)[:12]


def _set_sort_key(value: Any) -> tuple[int, Any, str, str]:
    """Deterministic TOTAL order over leaf scalars.

    Class ranks keep the sort total when a set mixes classes (bool is rank 2, NOT a number —
    it subclasses int and must not interleave); within a rank the natural order applies, with
    the type name as a tiebreak so numerically-equal int/float (1 vs 1.0) order stably, and
    the canonical rendering as the final tiebreak so ==-equal values that RENDER differently
    (`-0.0` vs `0.0`) order deterministically instead of by input order.
    """
    if isinstance(value, bool):
        return (2, value, "bool", canonical_json_str(value))
    if isinstance(value, int | float):
        return (1, value, type(value).__name__, canonical_json_str(value))
    return (0, value, "str", canonical_json_str(value))


def canonical_set(values: Iterable[Any]) -> list[Any]:
    """Canonicalize an unordered leaf-element set to its canonical list form (§12.4/§7.2).

    Dedupe by exact RENDERING (type-distinguishing: `True` is not `1`, `1` is not `1.0`,
    and `-0.0` is not `0.0` — each renders differently; an ==-keyed dedupe would merge
    `-0.0`/`0.0` and make the surviving bytes input-order-dependent) + the sorted()
    canonicalization the goal-set uses (§7.2), so identical logical sets yield identical
    lists, identical canonical bytes, and identical digests regardless of input order.
    Elements must be leaf scalars (§11.1: enum/number/ref/bool/string); dates and non-leaf
    values are refused.
    """
    deduped: dict[tuple[str, str], Any] = {}
    for value in values:
        if isinstance(value, datetime.date):  # covers datetime.datetime (subclass)
            raise CanonicalizationError(
                "canonicalization-refused: set elements must be leaf scalars (§11.1); "
                "dates are date-window values, not set members"
            )
        if not isinstance(value, _LEAF_SET_TYPES):
            raise CanonicalizationError(
                "canonicalization-refused: set elements must be leaf scalars (§11.1), got "
                f"{type(value).__name__}"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise CanonicalizationError(
                "canonicalization-refused: non-finite float in a set (JSON has no NaN/Infinity)"
            )
        # Values reaching this line are already-vetted finite leaf scalars, so
        # canonical_json_str is total here; keying on the rendering (not ==) keeps
        # differently-rendering equals (-0.0 vs 0.0) distinct.
        deduped.setdefault((type(value).__name__, canonical_json_str(value)), value)
    return sorted(deduped.values(), key=_set_sort_key)
