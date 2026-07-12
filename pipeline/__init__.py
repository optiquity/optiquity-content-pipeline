"""optiquity-content-pipeline — framework mechanism package (provenance: framework).

This package holds mechanism code only (design `docs/design.md` §10 mechanism/data split;
plan T8). Instance/client data never lives here.

INV-CORRECTNESS note (design §22.7): correctness modules (materialize / claim /
idempotency-check / sweep) must never import the SSOT module. The CI import lint enforcing
this lands with the execution spine (plan step 21); modules added to this package before
then must already honor the boundary.
"""

__version__ = "0.1.0"
