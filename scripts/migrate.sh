#!/usr/bin/env bash
# scripts/migrate.sh — the §11.6 owner-triggered migration runner (MIG-1…MIG-7).
#
# USER-TRIGGERED, MANDATORY BEFORE USE: resolve-time drift enforcement (design §11.5)
# blocks stale config until this has run; it is never silent-auto-run. IDEMPOTENT:
# migration is ONE fold over the half-open interval (entry-stamp, current]; an empty
# interval is a structural no-op (MIG-1), so re-running is always safe.
#
# MAINTENANCE VERB — NOT on the external-actor API (§21.9; step-6 parameter sheet): the
# API only surfaces drift-block / out-of-window / ambiguous-migration-decisions and
# points remediation here.
#
# Scope (MIG-7): instance-owned, schema-stamped CONFIG only. Framework defaults are
# lockstep-maintained upstream; ARTIFACTS ARE IMMUTABLE — migrate config, then
# regenerate. Ambiguous changes halt into a decisions-needed worklist
# (default: instance/ops/migration-worklist.yaml) — edit the decision: slots, re-run.
#
# Exit codes: 0 clean · 1 blocked/error (incl. out-of-window, MIG-2) · 2 usage ·
# 3 decisions needed (MIG-5). Flags (see --help): --root --registry --worklist --now.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# --root defaults to the repo checkout; a caller-supplied --root later in "$@" wins
# (argparse takes the last occurrence).
exec uv run --project "$REPO_ROOT" python -m pipeline.migration --root "$REPO_ROOT" "$@"
