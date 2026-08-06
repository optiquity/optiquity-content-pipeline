#!/usr/bin/env bash
# scripts/migrate-to-foundation-layout.sh — the `foundation/` reorg on-disk re-home (reorg B-3).
#
# USER-TRIGGERED, ONE-SHOT, IDEMPOTENT: moves the 17 FRAMEWORK registries from the OLD FLAT layout
# (`<root>/<token>/`) to the NEW `foundation/`-anchored homes (`<root>/foundation/…/<token>/`) that
# `pipeline.layout.REGISTRY_BASE` now declares, then rewrites the ONLY in-registry content that
# hard-codes its own physical path — the three journal looks' `csl:` self-reference. It is the
# durable counterpart to the code flip: the code started resolving every framework registry through
# `registry_dir` (foundation-anchored) the moment `REGISTRY_BASE` was filled, so this script re-homes
# the committed files to match. A downstream/instance clone runs it ONCE after pulling the reorg.
#
# The src→dst pairs are DERIVED from the layout SSOT (`pipeline.layout.REGISTRY_BASE`), never
# hard-coded here — so this tool can never drift from the map it mirrors. `lexicons` re-homes to the
# depth-2 singleton `foundation/lexicons`; every other token to its `foundation/<bin>/<token>` home.
#
# DISTINCT FROM scripts/migrate-to-users-layout.sh (the §23 workspace re-home) and scripts/migrate.sh
# (the §11.6 schema/config migration): this one re-homes the FRAMEWORK registry roots + rewrites the
# three `csl:` self-refs. It touches NO other file content (§10 rule 5 — extend, don't edit).
#
# SAFETY (mirrors migrate-to-users-layout.sh):
#   * IDEMPOTENT — a re-run after a complete migration is a clean no-op ("nothing to migrate"): a
#     token whose flat src is gone and whose foundation dst exists is already home. The `csl:`
#     rewrite is anchored on the BARE `csl: presentations/assets/…` form, so it never re-prefixes an
#     already-migrated `csl: foundation/dimensions/presentations/…` value.
#   * REFUSE, DON'T CLOBBER — if BOTH the flat src AND the foundation dst exist (a partial/conflicting
#     state) the token is REFUSED, never merged/overwritten.
#   * USES `git mv` — the move is a TRACKED rename so git's content-based rename detection preserves
#     each file's history; run it from inside the git checkout.
#   * SELF-REF SCAN — after the move+rewrite it FAILS LOUD on any surprise `presentations/assets/…`
#     reference that is NOT the migrated `foundation/dimensions/presentations/assets/…` form (and is
#     not the generic `<style>` placeholder in the shipped `.csl` doc-comments), or any journal-look
#     `csl:` value that is not `foundation/`-anchored — i.e. an un-rewritten self-ref the move broke.
#
# Flags (see --help):
#   --root DIR   repo root holding the flat registries (default: this script's parent dir)
#   --dry-run    print the planned moves + rewrites; change NOTHING on disk
#   -h, --help   usage
#
# Exit codes: 0 clean (incl. nothing-to-migrate) · 1 refusal (conflicting src+dst / surprise self-ref)
#             · 2 usage (bad flag / bad --root / cannot derive the map).
set -euo pipefail

SELF="$(basename "$0")"

usage() {
  cat <<'EOF'
usage: migrate-to-foundation-layout.sh [--root DIR] [--dry-run]

Re-home the 17 framework registries from the flat layout (<root>/<token>/) to their
foundation/-anchored homes (pipeline.layout.REGISTRY_BASE), then rewrite the three journal
looks' `csl:` self-reference. Idempotent, refuse-don't-clobber, tracked `git mv`.

  --root DIR   repo root that contains the flat registries (default: the parent of this script)
  --dry-run    print the planned moves and rewrites; change NOTHING on disk
  -h, --help   show this help

Exit: 0 clean (incl. nothing to migrate) · 1 refusal · 2 usage.
EOF
}

# --- argument parsing -------------------------------------------------------------------------
ROOT=""
DRY_RUN=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      [ "$#" -ge 2 ] || { echo "$SELF: --root requires a value" >&2; exit 2; }
      ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "$SELF: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

# --- resolve --root ---------------------------------------------------------------------------
if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
if [ ! -d "$ROOT" ]; then
  echo "$SELF: --root '$ROOT' is not a directory" >&2; exit 2
fi
ROOT="$(cd "$ROOT" && pwd)"

# --- derive the src→dst map from the layout SSOT (never hard-coded here) -----------------------
# Prints one `<token> <foundation-relpath>` pair per line, straight from pipeline.layout.REGISTRY_BASE.
# PYTHONPATH pins the repo root so `import pipeline.layout` resolves without an install.
PY="${PYTHON:-python3}"
PAIRS="$(PYTHONPATH="$ROOT" "$PY" - <<'PYEOF'
import sys
try:
    from pipeline.layout import REGISTRY_BASE
except Exception as exc:  # pragma: no cover - surfaced as a usage refusal below
    sys.stderr.write(f"cannot import pipeline.layout.REGISTRY_BASE: {exc}\n")
    sys.exit(3)
for token, home in REGISTRY_BASE.items():
    print(token, home)
PYEOF
)" || { echo "$SELF: could not derive the layout map (need a python that can import pipeline.layout; set PYTHON=... or run from a checkout)" >&2; exit 2; }

if [ -z "$PAIRS" ]; then
  echo "$SELF: pipeline.layout.REGISTRY_BASE is empty — nothing to migrate (is the B-3 flip applied?)."
  exit 0
fi

# The presentations home carries the `csl:` self-refs to rewrite; capture its foundation relpath.
PRES_REL="$(printf '%s\n' "$PAIRS" | awk '$1=="presentations"{print $2}')"

# --- helpers ----------------------------------------------------------------------------------
run() {  # execute $@, or (in --dry-run) just log the would-be action
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  DRY-RUN would: %s\n' "$*"
  else
    "$@"
  fi
}

# --- migrate ----------------------------------------------------------------------------------
moved=()
already=()
refused=()
fail=0

echo "$SELF: root=$ROOT  dry-run=$DRY_RUN"

while read -r token dstrel; do
  [ -n "$token" ] || continue
  src="$ROOT/$token"
  dst="$ROOT/$dstrel"

  if [ -e "$dst" ] && [ ! -e "$src" ]; then
    already+=("$token -> $dstrel")
    continue
  fi
  if [ -e "$dst" ] && [ -e "$src" ]; then
    echo "$SELF: REFUSING '$token' — BOTH the flat src ($token) and the foundation dst ($dstrel) exist;" >&2
    echo "       not merging/clobbering. Resolve the conflict by hand, then re-run." >&2
    refused+=("$token (src+dst conflict)")
    fail=1
    continue
  fi
  if [ ! -e "$src" ]; then
    echo "$SELF: WARNING: neither the flat src ($token) nor the foundation dst ($dstrel) exists — skipping '$token'." >&2
    continue
  fi
  # src exists, dst does not: make the bin, then TRACKED-move the whole registry dir into it.
  run mkdir -p "$(dirname "$dst")"
  run git -C "$ROOT" mv "$token" "$dstrel"
  moved+=("$token -> $dstrel")
done <<EOF
$PAIRS
EOF

# --- rewrite the three journal looks' `csl:` self-reference (the ONLY content touch) ----------
# Anchored on the BARE `csl: presentations/assets/` form, so already-migrated
# `csl: foundation/dimensions/presentations/assets/` values are left untouched (idempotent).
rewrote=()
if [ -n "$PRES_REL" ]; then
  pres_dst="$ROOT/$PRES_REL"
  for look in "$pres_dst"/journal-concise-look.md "$pres_dst"/journal-strict-look.md \
              "$pres_dst"/journal-structured-look.md; do
    [ -f "$look" ] || continue
    if grep -q 'csl: presentations/assets/' "$look" 2>/dev/null; then
      run sed -i.bak "s#csl: presentations/assets/#csl: ${PRES_REL}/assets/#g" "$look"
      [ "$DRY_RUN" -eq 1 ] || rm -f "$look.bak"
      rewrote+=("$(basename "$look")")
    fi
  done
fi

# --- self-ref scan: FAIL LOUD on a surprise physical-path reference ----------------------------
# (1) Any `presentations/assets/…` reference under the moved presentations home that is NOT the
#     migrated `foundation/dimensions/presentations/assets/…` form AND is not the generic `<style>`
#     placeholder documented in the shipped `.csl` files — an un-rewritten self-ref the move broke.
# (2) Any journal-look `csl:` frontmatter value that is not `foundation/`-anchored — a bare
#     registry-path csl the rewrite missed.
if [ -n "$PRES_REL" ] && [ "$DRY_RUN" -eq 0 ]; then
  pres_dst="$ROOT/$PRES_REL"
  if [ -d "$pres_dst" ]; then
    surprises="$(grep -rn 'presentations/assets/' "$pres_dst" 2>/dev/null \
                  | grep -v "${PRES_REL}/assets/" \
                  | grep -v '<style>' || true)"
    if [ -n "$surprises" ]; then
      echo "$SELF: SELF-REF FAILURE — surprise bare 'presentations/assets/' reference(s) after the move:" >&2
      printf '%s\n' "$surprises" | sed 's/^/    /' >&2
      fail=1
    fi
    badcsl="$(grep -rh '^csl:' "$pres_dst" 2>/dev/null | grep -v '^csl: foundation/' || true)"
    if [ -n "$badcsl" ]; then
      echo "$SELF: SELF-REF FAILURE — a journal-look 'csl:' value is not foundation/-anchored:" >&2
      printf '%s\n' "$badcsl" | sed 's/^/    /' >&2
      fail=1
    fi
  fi
fi

# --- summary ----------------------------------------------------------------------------------
echo
echo "===== migrate-to-foundation-layout summary ====="
if [ "${#moved[@]}" -gt 0 ]; then
  echo "moved (${#moved[@]}):"
  for m in "${moved[@]}"; do echo "  + $m"; done
else
  echo "moved (0): none"
fi
if [ "${#already[@]}" -gt 0 ]; then
  echo "already home (${#already[@]}): idempotent no-op"
fi
if [ "${#rewrote[@]}" -gt 0 ]; then
  echo "csl self-ref rewritten in: ${rewrote[*]}"
fi
if [ "${#refused[@]}" -gt 0 ]; then
  echo "refused (${#refused[@]}):"
  for r in "${refused[@]}"; do echo "  ! $r"; done
fi
if [ "$DRY_RUN" -eq 1 ]; then
  echo "mode: DRY-RUN — nothing changed on disk."
fi
echo "================================================"

exit "$fail"
