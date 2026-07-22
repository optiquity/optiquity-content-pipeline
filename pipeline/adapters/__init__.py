"""Source adapters — pluggable, READ-ONLY grounding providers (design §6.1; plan T11).

The contract lives in `pipeline.adapters.base` (plan step 17); the deterministic mock
adapter (`pipeline.adapters.mock`) implements it for full-branch resolver coverage. The
real v1 adapters — `graphify` + `folder` — land at plan step 18 against the same contract.

Durable rule 1 rides every adapter: source/client repos are READ-ONLY, always. The
contract exposes no write primitive, structurally.

`default_adapters()` is the ONE place the production adapter set is registered — both the
real API (`begin-session`/`invoke`, via `pipeline.api.session._default_adapters`) and the
driver (`pipeline.driver.run_thread`) resolve their adapters from here, so registering a
new adapter is a one-file change (the matrix rule, applied to the adapter axis).
"""

from __future__ import annotations

from pipeline.adapters.base import SourceAdapter
from pipeline.adapters.folder import FolderAdapter
from pipeline.adapters.fsast import FsAstAdapter
from pipeline.adapters.graphify import GraphifyAdapter

__all__ = ["default_adapters"]


def default_adapters() -> dict[str, SourceAdapter]:
    """The production source-adapter set: the READ-ONLY grounding + §7.2 commit-pin
    providers reachable through the real API + driver. A fresh dict of fresh instances per
    call (adapters are stateless, but callers may mutate the mapping). Register a new adapter
    HERE and every production path picks it up."""
    return {
        "graphify": GraphifyAdapter(),
        "folder": FolderAdapter(),
        "fsast": FsAstAdapter(),
    }
