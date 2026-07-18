"""DR-3 COMMIT 1 tests: `pipeline/outline.py` — the outline normalizer `N`, `outline_digest`,
the accept-path refusals, and the #3a N-invariance reservation guard.

Covers (each a pinned clause of the module contract):

- **Idempotency** (`N(N(x)) == N(x)`) across a spread of dirty inputs.
- **The digest SHAPE**: a FULL 64-char lowercase-hex SHA-256, and `outline_digest ==
  sha256_hex(N(x).encode())` (the ONE shared function).
- **Cosmetic-invariance**: trailing per-line whitespace, blank-line runs, and CRLF/CR line
  endings do NOT churn the digest — N destroys all three.
- **Indent-churn**: leading indentation DOES change the digest and survives N — it is OPAQUE
  content, never stripped or reinterpreted (step 6 / the #3a reservation).
- **The #3a structural class survives N unchanged**: a full-line marker line plus
  leading-indented content are already-normal, so N is the identity on them.
- **#3a honesty (D-5)**: the ACCEPTED, deliberate v1 losses — a Markdown hard line break and
  trailing whitespace inside a fenced code block are BOTH dropped — are characterized here,
  not hidden.
- **Accept-path refusals**: an empty / no-substance outline and a secret-shaped one are
  refused LOUDLY, while a normal outline is accepted and returned normalized.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from pipeline.canonical import sha256_hex
from pipeline.outline import (
    EmptyOutlineError,
    SecretShapedOutlineError,
    accept_outline,
    normalize_outline,
    outline_digest,
)

# A spread of dirty inputs exercising every N step: CRLF, lone CR, blank runs, trailing ws,
# leading/trailing blanks, and preserved leading indentation.
DIRTY_INPUTS = [
    "# H\r\n\n\n  indented  \n\n",
    "\r\n\r\n- a\r- b\t \n\n\n  - nested   \n",
    "   \n\n  # Title \n\n\n    body content\n\n\n",
    "",
    "   \n\t\n",
    "## Heading\n    code line\n- bullet\n  nested bullet",
]


@pytest.mark.parametrize("raw", DIRTY_INPUTS)
def test_normalize_is_idempotent(raw: str) -> None:
    once = normalize_outline(raw)
    assert normalize_outline(once) == once


@pytest.mark.parametrize("raw", DIRTY_INPUTS)
def test_digest_is_full_64_lowercase_hex(raw: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{64}", outline_digest(raw))


@pytest.mark.parametrize("raw", DIRTY_INPUTS)
def test_digest_is_the_one_shared_hash_of_the_normal_form(raw: str) -> None:
    expected = sha256_hex(normalize_outline(raw).encode("utf-8"))
    assert outline_digest(raw) == expected
    # And that equals a hand-rolled SHA-256 of the normal form's UTF-8 bytes.
    assert outline_digest(raw) == hashlib.sha256(
        normalize_outline(raw).encode("utf-8")
    ).hexdigest()


def test_cosmetic_edits_do_not_churn_the_digest() -> None:
    base = "# Title\n\n- point one\n- point two"
    trailing_ws = "# Title   \n\n- point one   \n- point two\t"
    blank_runs = "# Title\n\n\n\n- point one\n- point two"
    crlf = "# Title\r\n\r\n- point one\r\n- point two"
    lone_cr = "# Title\r\r- point one\r- point two"
    d = outline_digest(base)
    assert outline_digest(trailing_ws) == d
    assert outline_digest(blank_runs) == d
    assert outline_digest(crlf) == d
    assert outline_digest(lone_cr) == d


def test_cosmetic_invariant_matches_the_spawn_pin() -> None:
    # The literal cosmetic-invariance the spawn prompt pins.
    s = "# H\r\n\n\n  indented  \n\n"
    assert outline_digest(s) == outline_digest("# H\n\n  indented")


def test_leading_indentation_is_opaque_content_and_churns_the_digest() -> None:
    # Leading indentation is PRESERVED (step 6) and is content: different indent -> different
    # digest. This is the #3a "no semantics to nesting" pin.
    assert normalize_outline("  x") == "  x"
    assert normalize_outline("    x") == "    x"
    assert outline_digest("  x") != outline_digest("    x")


def test_hash3a_full_line_marker_and_indented_content_survive_N_unchanged() -> None:
    # A representative full-line marker line + leading-indented content: already-normal, so N
    # is the identity. This is the property F1 (DR-4) may derive boundaries from — full-line
    # content + leading indentation, both N-preserved.
    src = "## Heading marker\n    indented body content\n- bullet marker\n  nested bullet"
    assert normalize_outline(src) == src
    # Digest is stable under a re-run (idempotent normal form under the shared hash).
    assert outline_digest(src) == outline_digest(normalize_outline(src))


def test_hash3a_v1_drops_markdown_hard_line_break_accepted_loss() -> None:
    # D-5 honesty: a Markdown hard line break (line ending in two spaces) is DESTROYED by step
    # 3 — an ACCEPTED, deliberate v1 loss, characterized here (not "cosmetic").
    with_hard_break = "line one  \nline two"
    assert normalize_outline(with_hard_break) == "line one\nline two"
    # It collides with the plain-newline form — the break is gone from identity.
    assert outline_digest(with_hard_break) == outline_digest("line one\nline two")


def test_hash3a_v1_strips_trailing_ws_inside_fenced_code_accepted_loss() -> None:
    # D-5 honesty: v1 does NOT special-case fenced code, so significant trailing whitespace
    # inside a fence is stripped too — an ACCEPTED v1 limitation, characterized here.
    fenced = "```\ncode = 1    \n```"
    assert normalize_outline(fenced) == "```\ncode = 1\n```"


@pytest.mark.parametrize("empty", ["", "   \n\t\n  ", "\r\n\r\n", "###", "  ...  "])
def test_accept_refuses_empty_or_no_substance_outline(empty: str) -> None:
    with pytest.raises(EmptyOutlineError) as exc:
        accept_outline(empty)
    assert exc.value.code == "outline-empty-substance"


@pytest.mark.parametrize(
    "secret",
    [
        "# Config\n- password: hunter2supersecret",
        "# Keys\n- api_key = sk-abcdef0123456789ABCDEF",
        "clone: https://user:s3cr3tpw@github.com/x/y.git",
    ],
)
def test_accept_refuses_secret_shaped_outline(secret: str) -> None:
    with pytest.raises(SecretShapedOutlineError) as exc:
        accept_outline(secret)
    assert exc.value.code == "outline-secret-shaped-value"


def test_accept_returns_the_normalized_outline_on_the_happy_path() -> None:
    raw = "# Title\r\n\n\n- point one   \n\n"
    accepted = accept_outline(raw)
    assert accepted == normalize_outline(raw)
    assert accepted == "# Title\n\n- point one"
    # Accept is exactly N on accepted content — idempotent, no extra churn.
    assert normalize_outline(accepted) == accepted
