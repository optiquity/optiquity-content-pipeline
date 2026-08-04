"""The sources SUBSYSTEM: the shared acquire+read+storage core (design §6; sources P1).

This package holds the ONE common abstraction the ratified sources design extracted from the
otherwise-separate acquisition families (feeds P2, research P3): a **sealed, content-addressed
slice store** (`pipeline.sources.cache`) plus a **read-only cache-reader adapter**
(`pipeline.sources.reader`) that grounds over a PINNED, immutable slice. The acquisition LOOPS
are deliberately NOT shared — only this storage+read core is.

**What lives here is READ+STORAGE, never an acquisition body.** P1 ships no fetcher: the cache is
populated by TEST FIXTURES (and, from P2/P3, by acquisition bodies that target this same core).
The reader is pure/deterministic/read-only — no network, no LLM, no spend path (CLAUDE.md rules
1/8; the money-safety grep pins `pipeline/sources/*` free of `transport`/`requests`/`urllib`).

**What the cache holds:** ACQUIRED THIRD-PARTY CONTENT — gitignored (it lives under
`users/<user>/workspaces/<ws>/sources/cache/`, covered by `.gitignore`'s `users/*/workspaces/`),
never committed. The CLAUDE.md rule-1 carve-out that blesses storing acquired content here is the
MAIN SESSION's edit (ratified by the maintainer); this package never edits CLAUDE.md.
"""

from __future__ import annotations
