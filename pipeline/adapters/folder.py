"""The REAL `folder` adapter (plan step 18) — read-only local folder/doc grounding.

Design authority: `docs/design.md` §6.1 — `folder` is a design-listed adapter type (the
v1 second adapter, plan T11: "the cheapest second adapter"), a pluggable READ-ONLY
grounding provider. §6.2 — per-fact tier, anchors, freshness basis "derived
(commit/mtime)". §3.3 + CLAUDE.md rule 1 — sources are READ-ONLY, always.

What it does: walks one bound local folder (deterministically: parent-first,
lexicographic, hidden entries and symlinks skipped, `DOC_SUFFIXES` only), splits each
document into paragraph blocks, and grounds each block that matches the query as one
verbatim `Fact`:

- **`tier` = EXTRACTED for every fact** — the claim is a VERBATIM quotation of the
  document at a resolvable anchor; "the source literally says this" is exactly the
  EXTRACTED answer to §6.5's *how sure*. Whether the document is authoritative,
  opinionated, or reviewed is NOT the tier's question — those are the content-kind
  scores riding the instance's kind tag (below).
- **`subject` = ``<relpath>#p<n>``** (paragraph coordinate), **`claim`** = the verbatim
  block. Byte-identical docs at the same relative path across two folder instances
  (mirrors) yield equal (subject, claim) — the resolver's §6.5 corroboration arithmetic
  works unchanged, exactly as with the mock.
- **`anchors`** = one `file-line` anchor ``<relpath>:L<start>[-L<end>]`` (§6.2
  traceability: a resolvable file:line locator).
- **`as_of`** = the document's mtime date (§6.2 freshness basis "derived (commit/
  mtime)": a plain folder has no commit, so mtime IS the basis).
- **`built_at_commit` = None** — the folder adapter is THE commitless adapter kind the
  contract names (`base.GroundingResult`: "None when the adapter kind has no commit
  notion (e.g. a plain folder)").
- **Content-kind tagging (§6.1 Q10/SM5, plan step 18 "with content-kind tagging"):**
  the kind tag lives on the SOURCE INSTANCE (`sources/_schema.yaml` `content_kind:`),
  not on the adapter — a folder of research notes tags `research-notes`, a docs mirror
  tags its own kind, and the kind's default score bundle characterizes every fact this
  adapter returns. The adapter itself classifies nothing per fact (it has no signal
  to), so it emits NO refinements and the kind defaults ride intact — the same
  no-overstep posture as the graphify adapter's G6 disposition.
- **Query filter** = case-insensitive substring over subject + claim, empty query =
  the whole corpus — byte-parity with the mock adapter's documented filter, so the
  step-17 resolver behaves identically over both.

Rule 1 is STRUCTURAL: the module contains no write primitive at all (reads via
`Path.read_text`, walks via `os.walk` with `followlinks=False`), and the bound path is
asserted OUTSIDE this repo's `workspaces/` (plan step 18) — a step-18 test scans this
source for write primitives and snapshots a grounded folder byte-for-byte.

Loud, never silent: an absent/relative/non-directory path, an unknown connection key,
and an undecodable document are typed `AdapterError`s. An EMPTY result (no documents,
or nothing matches) is NOT an error — the resolver's SM1 walk owns that outcome.
"""

from __future__ import annotations

import datetime
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.adapters.base import (
    TIER_EXTRACTED,
    AdapterError,
    Anchor,
    Fact,
    GroundingResult,
    SourceAdapter,
)

__all__ = [
    "CONNECTION_KEYS",
    "DOC_SUFFIXES",
    "FolderAdapter",
    "REPO_WORKSPACES",
]

#: The closed v1 document allowlist (one-constant change when a new doc kind is needed —
#: the same extension discipline as `base.ANCHOR_KINDS`).
DOC_SUFFIXES = (".md", ".txt")

#: The closed connection-key set: one bound folder, nothing else.
CONNECTION_KEYS = frozenset({"path"})

#: This repo's workspaces root (CLAUDE.md rule 2): client CONTENT lives there; grounding
#: SOURCES live outside it. A folder path under it is refused loudly (plan step 18).
REPO_WORKSPACES = Path(__file__).resolve().parents[2] / "workspaces"


@dataclass(frozen=True)
class _Block:
    """One paragraph block: 1-based line span + the verbatim text."""

    start: int
    end: int
    text: str


def _paragraph_blocks(text: str) -> list[_Block]:
    """Split a document into blank-line-separated paragraph blocks, tracking lines."""
    blocks: list[_Block] = []
    current: list[str] = []
    start = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            if not current:
                start = lineno
            current.append(line)
        elif current:
            blocks.append(_Block(start=start, end=lineno - 1, text="\n".join(current).strip()))
            current = []
    if current:
        blocks.append(
            _Block(start=start, end=start + len(current) - 1, text="\n".join(current).strip())
        )
    return blocks


def _validate_connection(connection: Mapping[str, Any]) -> Path:
    if not isinstance(connection, Mapping):
        raise AdapterError(
            f"adapter-failure: folder connection must be a mapping, "
            f"got {type(connection).__name__}"
        )
    unknown = sorted(set(connection) - CONNECTION_KEYS)
    if unknown:
        raise AdapterError(
            f"adapter-failure: unknown folder connection key(s) {unknown!r} — the key "
            f"set is CLOSED ({', '.join(sorted(CONNECTION_KEYS))})"
        )
    raw_path = connection.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise AdapterError(
            "adapter-failure: folder connection requires `path`: the local folder to "
            f"ground from (read by path, rule 1); got {raw_path!r}"
        )
    path = Path(raw_path)
    if not path.is_absolute():
        raise AdapterError(
            f"adapter-failure: folder connection path must be ABSOLUTE, got {raw_path!r}"
        )
    resolved = path.resolve()
    if resolved == REPO_WORKSPACES or REPO_WORKSPACES in resolved.parents:
        raise AdapterError(
            f"adapter-failure: folder source path {str(resolved)!r} lies inside this "
            f"repo's workspaces ({str(REPO_WORKSPACES)!r}) — grounding sources live "
            "OUTSIDE the pipeline's client workspaces (CLAUDE.md rules 1/2; plan step 18)"
        )
    if not resolved.exists():
        raise AdapterError(
            f"adapter-failure: folder not found: {resolved} — an absent source is a "
            "typed error, never a silent empty"
        )
    if not resolved.is_dir():
        raise AdapterError(
            f"adapter-failure: folder connection path is not a directory: {resolved}"
        )
    return resolved


def _collect_documents(root: Path) -> tuple[str, ...]:
    """The deterministic corpus walk: parent-first, lexicographic, POSIX relpaths.

    Hidden entries (dot-prefixed) are skipped; symlinks are never followed nor read
    (`followlinks=False` + a per-file symlink check) — the corpus is structurally
    contained inside the bound folder.
    """
    documents: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            file = Path(dirpath) / name
            if file.suffix.lower() not in DOC_SUFFIXES:
                continue
            if file.is_symlink():
                continue
            documents.append(file.relative_to(root).as_posix())
    return tuple(documents)


class FolderAdapter(SourceAdapter):
    """`adapter: folder` — verbatim paragraph grounding over one read-only local folder."""

    name = "folder"

    def ground(self, *, connection: Mapping[str, Any], query: str) -> GroundingResult:
        if not isinstance(query, str):
            raise AdapterError(
                f"adapter-failure: query must be a string, got {type(query).__name__}"
            )
        root = _validate_connection(connection)
        needle = query.strip().lower()
        facts: list[Fact] = []
        for relpath in _collect_documents(root):
            file = root / relpath
            try:
                text = file.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise AdapterError(
                    f"adapter-failure: document {relpath!r} is not UTF-8 text: {exc} "
                    "(undecodable sources fail loudly, never silently skip)"
                ) from exc
            except OSError as exc:
                raise AdapterError(
                    f"adapter-failure: could not read document {relpath!r}: {exc}"
                ) from exc
            as_of = datetime.date.fromtimestamp(file.stat().st_mtime)
            for index, block in enumerate(_paragraph_blocks(text), start=1):
                subject = f"{relpath}#p{index}"
                if needle and needle not in f"{subject} {block.text}".lower():
                    continue
                span = (
                    f"L{block.start}"
                    if block.start == block.end
                    else f"L{block.start}-L{block.end}"
                )
                facts.append(
                    Fact(
                        subject=subject,
                        claim=block.text,
                        tier=TIER_EXTRACTED,  # verbatim quotation (module docstring)
                        anchors=(Anchor("file-line", f"{relpath}:{span}"),),
                        as_of=as_of,
                        refinements={},  # the adapter classifies nothing; kind defaults ride
                    )
                )
        return GroundingResult(facts=tuple(facts), built_at_commit=None)
