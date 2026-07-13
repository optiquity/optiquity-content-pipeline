"""The external-actor API (design §20-§22): the stateless `invoke` contract and its parts.

`invoke(verb, workspace, params, [token], [pins]) → {envelope, results, [token']}` (§21.1) is
the one synchronous entry a stateless caller (n8n, a wrapper app) drives. Its three parts:

- `results` — the typed `ResultItem`/`Envelope` (§21.7) + the CONSOLIDATED §21.7/§22.6 code
  taxonomy (`ALL_CODES`/`CODES`); the one home for the wire code vocabulary.
- `token` — the documented, actor-held resumption token (§20): a cursor, not a capability
  gate; integrity by canonical digest, lost-token-survivable.
- `invoke` — the contract, the whole-invocation envelope, workspace isolation on every id,
  token handling, and the (step-32 thin) verb-dispatch seam. It lives in the `.invoke`
  submodule (`from pipeline.api.invoke import invoke, main_cli, …`); it is intentionally NOT
  re-exported here so the `python -m pipeline.api.invoke` CLI entry (behind `scripts/pipeline
  invoke`) does not double-import via this package.

Step 32 (plan) delivers the contract/envelope/isolation/token/results; the real verb handlers
(generate-next, render, fetch, emit) wire into `invoke._VERB_HANDLERS` at later steps.
"""

from __future__ import annotations

from pipeline.api import results, token
from pipeline.api.results import (
    ALL_CODES,
    CODES,
    Envelope,
    ResultItem,
    make_result,
)
from pipeline.api.token import Token

__all__ = [
    "ALL_CODES",
    "CODES",
    "Envelope",
    "ResultItem",
    "Token",
    "make_result",
    "results",
    "token",
]
