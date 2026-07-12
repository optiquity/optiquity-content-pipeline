"""Pinned YAML 1.2 typed safe-load + the bounded frontmatter splitter (framework mechanism).

Design authority: `docs/design.md` §13.4 (schema & stamp encoding), §13.5 (build flags — the
Norway-problem guard; pinned loader + pinned splitter). Gate authority: the step-2 G4 report
(`ruamel.yaml==0.19.1`, `YAML(typ='safe', pure=True)`) whose §4 splitter spec this module
implements verbatim, including the S-E1..S-E12 edge-case table.

Splitter invariants (step-2 §4, enforced by tests/test_yamlio.py):
  (i)   the split is deterministic and total over `str` (every input either splits or raises a
        typed error — never undefined behavior);
  (ii)  for any recognized frontmatter block, the returned body is byte-identical to the
        input's post-fence remainder (no normalization, no stripping);
  (iii) the splitter itself never invokes YAML parsing (pure text);
  (iv)  `load_frontmatter` uses ONLY the pinned `YAML(typ='safe', pure=True)` loader.

Typed error codes (step-2 spec; the step-32 taxonomy maps these later):
  `unterminated-frontmatter` (S-E7) · `frontmatter-directive-refused` (S-E8, closes the
  verified D3 hazard: an in-document `%YAML 1.1` directive re-enables the Norway problem) ·
  `frontmatter-not-a-mapping` (S-E9 — mapping-ness is OUR check, not the library's).

YAML *syntax* errors inside a recognized frontmatter block propagate as the library's own
`ruamel.yaml.YAMLError` (re-exported here as `YAMLLoadError`) — loud, never silent (S-E10).
"""

from __future__ import annotations

import io
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError as YAMLLoadError

__all__ = [
    "FrontmatterDirectiveError",
    "FrontmatterError",
    "FrontmatterNotAMappingError",
    "UnterminatedFrontmatterError",
    "YAMLLoadError",
    "load_frontmatter",
    "load_yaml",
    "split_frontmatter",
]

# Open fence: the FIRST line only, optionally preceded by exactly one U+FEFF BOM, `---` plus
# optional spaces/tabs, terminated by LF, CRLF, or EOF (step-2 §4; S-E1/S-E2/S-E6/S-E12).
# (`\ufeff` is the step-2 regex's literal BOM, written as an escape for visibility; the `re`
# module resolves `\uXXXX` escapes inside raw patterns.)
_OPEN_FENCE_RE = re.compile(r"\A\ufeff?---[ \t]*(\r\n|\n|\Z)")

# Close fence: the next subsequent full line `---` (+ optional spaces/tabs) ending in LF, CRLF,
# or EOF. First match wins (S-E3); only `---` closes — `...` does not (step-2 I3).
_CLOSE_FENCE_RE = re.compile(r"(?m)^---[ \t]*(\r\n|\n|\Z)")


class FrontmatterError(ValueError):
    """Base class for typed frontmatter errors. `code` is the stable error-code string."""

    code = "frontmatter-error"


class UnterminatedFrontmatterError(FrontmatterError):
    """S-E7: an open fence with EOF before any close fence."""

    code = "unterminated-frontmatter"


class FrontmatterDirectiveError(FrontmatterError):
    """S-E8: a `%` directive line at column 0 inside frontmatter (closes hazard D3)."""

    code = "frontmatter-directive-refused"


class FrontmatterNotAMappingError(FrontmatterError):
    """S-E9: frontmatter parses to a non-mapping YAML document (scalar or sequence)."""

    code = "frontmatter-not-a-mapping"


def make_loader() -> YAML:
    """Return a fresh pinned loader: `YAML(typ='safe', pure=True)` — YAML 1.2 typed safe-load.

    G4 (step-2): under this loader `no`/`yes`/`on`/`off` (all case variants) and `y`/`n` load
    as strings for values AND keys; the two documented deviations from strict 1.2 core —
    D1 (`1_000` → int) and D2 (bare dates → `datetime.date`) — are covered by the §11.1 typed
    validation in `pipeline/attrtypes.py`. A fresh instance per call keeps callers reentrant.
    """
    return YAML(typ="safe", pure=True)


def load_yaml(text: str) -> Any:
    """Load one YAML document from `text` with the pinned YAML 1.2 typed safe loader."""
    return make_loader().load(io.StringIO(text))


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split `text` into `(fm_text | None, body)` — pure text, no YAML parsing inside.

    Per the step-2 §4 contract: input is already-decoded `str` (UTF-8 decode and its errors
    happen upstream, at file read). Returns:

    - `(None, text)` verbatim when the first line is not an open fence (S-E4/S-E6), including
      a BOM-only-no-fence input where the BOM is preserved (S-E1);
    - `(fm_text, body)` when a block is recognized: `fm_text` is the verbatim lines strictly
      between the fences (CRLF preserved, S-E2; `""` for an empty block, S-E5) and `body` is
      everything after the close-fence line's terminator, verbatim (`""` if the close fence
      ends the file, S-E11).

    Raises `UnterminatedFrontmatterError` (S-E7) on an open fence with no close fence.
    Documented limitation S-E10: a bare `---` line inside a block scalar closes the fence
    early — the truncated YAML then fails loudly downstream, never silently.
    """
    open_match = _OPEN_FENCE_RE.match(text)
    if open_match is None:
        return (None, text)
    rest = text[open_match.end() :]
    close_match = _CLOSE_FENCE_RE.search(rest)
    if close_match is None:
        raise UnterminatedFrontmatterError(
            "unterminated-frontmatter: open fence with EOF before any close fence (S-E7)"
        )
    return (rest[: close_match.start()], rest[close_match.end() :])


def load_frontmatter(text: str) -> tuple[dict[Any, Any] | None, str]:
    """Split + S-E8 refusal + pinned load + mapping check (the step-2 §4 contract).

    Returns `(None, text)` when no frontmatter block exists — the missing-frontmatter policy
    is the CALLER's (the step-11 registry entry loader rejects; non-registry callers may
    accept), which is why the mapping slot is `dict | None`, keeping S-E4 (`None`) distinct
    from S-E5 (`{}`). An empty/whitespace-only block normalizes to `{}` (the pinned loader
    yields `None` for empty input — step-2 probe 2.4).

    Raises `FrontmatterDirectiveError` on any `%` line at column 0 inside the block (S-E8)
    and `FrontmatterNotAMappingError` when the block parses to a non-mapping (S-E9). YAML
    syntax errors propagate as `YAMLLoadError`.
    """
    fm_text, body = split_frontmatter(text)
    if fm_text is None:
        return (None, body)
    for line in fm_text.splitlines():
        if line.startswith("%"):
            raise FrontmatterDirectiveError(
                "frontmatter-directive-refused: a %-directive line inside frontmatter "
                f"(S-E8; refused line: {line!r})"
            )
    data = load_yaml(fm_text)
    if data is None:
        # Empty / whitespace-only / comments-only frontmatter block.
        return ({}, body)
    if not isinstance(data, dict):
        raise FrontmatterNotAMappingError(
            "frontmatter-not-a-mapping: frontmatter must be a YAML mapping, got "
            f"{type(data).__name__} (S-E9)"
        )
    return (data, body)
