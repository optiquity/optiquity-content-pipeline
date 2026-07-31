#!/usr/bin/env bash
# scripts/schema-lint.sh — the SV11 schema/registry CI lint (design §11.7), plan step 13.
#
# Thin T8 entrypoint wrapping `python -m pipeline.lint` in the uv-managed project venv —
# all real behavior (and its documentation) lives in pipeline/lint.py. The lint WIRES the
# schema/entry/drift/migration modules; it re-implements nothing.
#
# Clauses (SV11, §11.7): (1) schema change without a schema_version bump; (2) meaning
# change without a shipped map-or-prompt (MIG-4); (3) lockstep violation (a framework
# entry stamped older than current for a redefined attribute it sets); (4) window sanity
# (premature prune; future-dated / non-monotonic released: dates — the step-12 RV-3
# carry-forward). Plus: deterministic-map totality/composition (§27.4), the §7.4 slug
# constraints, the §11.1 B4 entry-identity match, the Q15 default-deny provenance check +
# closed-schema validation (§10 rule 4), and cross-collection schema_version equality
# (the step-11 RV-3 carry-forward).
#
# Pairs with scripts/check-no-content.sh (the public-boundary leak guard, §10 rule 5) in
# .github/workflows/guard.yml. Exit: 0 clean · 1 findings · 2 usage.
#
# Baseline is RELEASE-relative, not per-commit: with no --baseline/--git-ref/--no-baseline
# override, clauses 1/2/4 diff the checkout against the commit named by the committed
# release marker (pipeline/released_baseline). PRE-RELEASE that marker is ABSENT, so there
# is no baseline and the diff clauses are inert — only the FIRST schema change AFTER a
# release must bump the global schema_version. The within-tree invariants (structural
# validity, cross-collection version equality, lockstep, entry/provenance validation) run
# ALWAYS. A present-but-unresolvable marker fails LOUD (nonzero) — see pipeline/lint.py.
# Flags pass through (see --help): --root --baseline --no-baseline --git-ref --now.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# --root defaults to the repo checkout; a caller-supplied --root later in "$@" wins
# (argparse takes the last occurrence).
exec uv run --project "$REPO_ROOT" python -m pipeline.lint --root "$REPO_ROOT" "$@"
