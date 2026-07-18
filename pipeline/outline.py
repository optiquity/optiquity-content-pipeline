"""The outline normalizer `N` + `outline_digest` — the identity-safe FOUNDATION for DR-3
(horn (a) / B1 build). Pure, total, import-light: NO identity-surface change lands here.

Design authority: `docs/design.md` §7.2 (canonical preimages: identical logical inputs MUST
yield identical bytes/digests), §7.4 (digest form: SHA-256, the FULL digest recorded), §15
(the substance floor) and §3.3 (no secret ever persists). This module is the shared outline
canonicalizer every later DR-3 surface calls, so a cosmetic edit to an outline can never
churn its identity.

The normalizer `N` — `normalize_outline(md)` — is pinned EXACTLY, in this order:

  1. NFC-normalize (`unicodedata.normalize("NFC", ...)`) — one Unicode spelling per string.
  2. Line-endings fold to LF (a CRLF and a lone CR both become a single LF).
  3. Strip TRAILING per-line whitespace.
  4. Collapse blank-line runs (two or more consecutive blank lines become exactly one).
  5. Strip leading and trailing blank lines.
  6. PRESERVE leading indentation as OPAQUE content — never stripped, never reinterpreted;
     N assigns NO semantics to nesting depth.

`N` is IDEMPOTENT: `N(N(x)) == N(x)` (steps 2-5 reach a fixed point in one pass; NFC and
LF-folding are themselves idempotent). `outline_digest(md)` is
`sha256_hex(normalize_outline(md).encode("utf-8"))` — the FULL 64-char lowercase hex, the ONE
shared function every later surface reuses.

**`outline_digest` is a BARE content hash, NOT an identity.** It is deliberately NOT a §7.4
id root: it carries NO `o-` (or any) prefix, is NEVER minted through `pipeline.ids`, and is
NEVER `parse_id`-parsed. Keeping it a raw content digest is what lets Commit 2/3 layer an
identity surface ON TOP without this foundation already having taken an identity shape.

#3a N-INVARIANCE RESERVATION (the DR-4/F1 forward-contract)
----------------------------------------------------------
A future F1 (DR-4) section-boundary grammar MUST derive boundaries only from N-preserved
structure (full-line content + leading indentation). It MUST NOT rely on trailing per-line
whitespace, blank-line-run counts, or nesting depth — N destroys all three. This reserves the
structural CLASS (the N-preserved property), NOT any specific marker token/prefix (that is
DR-4's grammar). Note the boundary: a single interior blank line IS N-preserved (step 4 only
collapses runs of two-or-more), so F1 may key on blank *presence* — never on blank *count*.

#3a HONESTY (D-5) — the ACCEPTED, DELIBERATE, LOUD losses of v1
--------------------------------------------------------------
Step 3 (strip TRAILING per-line whitespace) is SEMANTICALLY LOSSY, not "cosmetic":
  - a Markdown HARD LINE BREAK is a line ending in two or more spaces — step 3 deletes those
    spaces, so the hard break is lost;
  - TRAILING WHITESPACE INSIDE A FENCED CODE BLOCK is significant to the code, and step 3
    deletes it too — v1 does NOT special-case fenced code.
These are ACCEPTED, DELIBERATE losses in v1, NAMED here rather than hidden as "cosmetic". A
later version that wants to preserve hard breaks or fenced-code whitespace must special-case
them; v1 does not, and says so out loud.

ACCEPT-PATH SAFETY (§15 / §3.3)
-------------------------------
`normalize_outline` and `outline_digest` stay PURE and TOTAL — they never raise on content;
they only canonicalize / hash. The REFUSAL lives in the explicit `accept_outline(md)` helper
the store/emit paths call: it returns `N(md)` but raises LOUDLY on an empty / no-substance
outline (§15 substance floor) and on a secret-shaped one (§3.3). The substance-floor and
secret-scan checks REUSE the existing helpers from `pipeline.ir` (`_has_substance`,
`looks_secret_shaped`) — one place of record for both policies.
"""

from __future__ import annotations

import unicodedata

from pipeline.canonical import sha256_hex
from pipeline.ir import _has_substance, looks_secret_shaped

__all__ = [
    "EmptyOutlineError",
    "OutlineError",
    "SecretShapedOutlineError",
    "accept_outline",
    "normalize_outline",
    "outline_digest",
]


class OutlineError(ValueError):
    """Base outline-accept refusal — loud, typed, never repaired (§3.1)."""

    code = "outline-invalid"


class EmptyOutlineError(OutlineError):
    """An outline with no substantive content (no Unicode letter/digit) — refused (§15)."""

    code = "outline-empty-substance"


class SecretShapedOutlineError(OutlineError):
    """A secret-shaped value reached an outline being accepted — refused (§3.3)."""

    code = "outline-secret-shaped-value"


def normalize_outline(md: str) -> str:
    """`N`: the pinned, idempotent outline normalizer (module docstring for the full contract).

    Pure and TOTAL — never raises on content. `N(N(x)) == N(x)`. Leading indentation is
    PRESERVED as opaque content (step 6); trailing per-line whitespace, blank-line-run counts,
    and CRLF/CR line endings are all destroyed (steps 2-5) so none can churn the digest.
    """
    # 1. NFC — one Unicode spelling.
    text = unicodedata.normalize("NFC", md)
    # 2. Line endings fold to LF (CRLF first so no CR dangles, then any lone CR).
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 3. Strip TRAILING per-line whitespace (leading indentation is preserved — step 6).
    lines = [line.rstrip() for line in text.split("\n")]
    # 4 + 5. Collapse blank-line runs to one, then strip leading/trailing blank lines.
    collapsed: list[str] = []
    prev_blank = False
    for line in lines:
        if line == "":
            if prev_blank:
                continue  # a second-or-later consecutive blank — drop it (run collapses to one)
            prev_blank = True
        else:
            prev_blank = False
        collapsed.append(line)
    while collapsed and collapsed[0] == "":
        collapsed.pop(0)
    while collapsed and collapsed[-1] == "":
        collapsed.pop()
    return "\n".join(collapsed)


def outline_digest(md: str) -> str:
    """The FULL 64-char lowercase-hex SHA-256 of `normalize_outline(md)`'s UTF-8 bytes.

    A BARE content hash — NOT a §7.4 id root, NO prefix, never `parse_id`-parsed (module
    docstring). Pure and TOTAL: it canonicalizes then hashes, and never raises on content.
    """
    return sha256_hex(normalize_outline(md).encode("utf-8"))


def accept_outline(md: str) -> str:
    """Accept `md` as a storable outline: return `N(md)`, or raise LOUDLY.

    The refusal surface the store/emit paths call (the pure `normalize_outline` /
    `outline_digest` never raise on content). Refuses an empty / no-substance outline
    (`EmptyOutlineError`, §15 substance floor) and a secret-shaped one
    (`SecretShapedOutlineError`, §3.3), reusing `pipeline.ir._has_substance` /
    `pipeline.ir.looks_secret_shaped` so both policies keep one place of record.
    """
    normalized = normalize_outline(md)
    if not _has_substance(normalized):
        raise EmptyOutlineError(
            "outline-empty-substance: the outline has no substantive content (no Unicode "
            "letter or digit) — write a real outline, not whitespace or a placeholder (§15)"
        )
    hit = looks_secret_shaped(normalized)
    if hit is not None:
        raise SecretShapedOutlineError(
            f"outline-secret-shaped-value: the outline carries a {hit}-shaped value — an "
            "outline stores authored structure, NEVER a secret (§3.3); refusing to accept it"
        )
    return normalized
