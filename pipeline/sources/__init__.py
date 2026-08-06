"""The sources SUBSYSTEM: the shared acquire+read+storage core (design §6; sources P1).

This package holds the ONE common abstraction the ratified sources design extracted from the
otherwise-separate acquisition families (feeds P2, research P3): a **sealed, content-addressed
slice store** (`pipeline.sources.cache`) plus a **read-only cache-reader adapter**
(`pipeline.sources.reader`) that grounds over a PINNED, immutable slice. The acquisition LOOPS
are deliberately NOT shared — only this storage+read core is.

**What lives here is READ+STORAGE plus READ-ONLY acquisition bodies.** P1 shipped no fetcher (the
cache was populated by TEST FIXTURES); from P2/P3 the feed/research acquisition bodies target this
same core. The reader is pure/deterministic/read-only, and acquisition is READ-ONLY toward every
source (CLAUDE.md rule 1). The ENFORCED money-safety invariant (`test_sources_ingest_cli.py`) is
that `pipeline/sources/*` references NO PAID PATH — no paid `transport` / session / driver / paid
handler import — so the whole subsystem spends $0 model quota by construction. FREE HTTP via
`urllib` is
allowed and used (feed fetch since P2; research search/fetch in P3b); the PAID research LLM seam is
INJECTED from the CLI (behind the paid gate), never wired here.

**What the cache holds:** ACQUIRED THIRD-PARTY CONTENT — gitignored (it lives under
`users/<user>/workspaces/<ws>/sources/cache/`, covered by `.gitignore`'s `users/*/workspaces/`),
never committed. The CLAUDE.md rule-1 carve-out that blesses storing acquired content here is the
MAIN SESSION's edit (ratified by the maintainer); this package never edits CLAUDE.md.
"""

from __future__ import annotations
