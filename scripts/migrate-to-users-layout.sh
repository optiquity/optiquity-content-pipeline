#!/usr/bin/env bash
# scripts/migrate-to-users-layout.sh — the §23 on-disk re-home migration (increment B8).
#
# USER-TRIGGERED, ONE-SHOT, IDEMPOTENT: moves EXISTING local instance workspaces from the OLD
# flat layout `<root>/workspaces/<ws>/` to the NEW per-owner layout
# `<root>/users/<owner>/workspaces/<ws>/` (CLAUDE.md rule 2; design §23). The B5 cutover made the
# code REQUIRE the new addressing; this script re-homes the on-disk data that predates it. It is
# never silent-auto-run — the operator runs it once, then works from the new layout.
#
# DISTINCT FROM scripts/migrate.sh (the §11.6 SCHEMA/config migration) — different concern,
# different data. This one is a pure directory re-home; it edits NO file contents.
#
# SAFETY (the data it moves is IRREPLACEABLE, gitignored instance data — CLAUDE.md rules 1/2/4):
#   * IDEMPOTENT — a re-run after a complete move is a clean no-op ("nothing to migrate").
#   * REFUSE, DON'T OVERWRITE — if a target already exists it is REFUSED (never merged/clobbered)
#     unless --force, and --force still NEVER overwrites an existing target file (see below).
#   * NEVER DELETES DATA — only `mv` (atomic on one filesystem) and `rmdir` on a proven-EMPTY dir.
#   * NEVER MOVES OUTSIDE <root> — every source and target is a validated, contained path segment.
#
# It also runs two read-only gates before moving:
#   * NAME HYGIENE — the owner and every workspace dir name must be one lowercase-safe path
#     segment ([a-z0-9_] then [a-z0-9._-]; no separator, no leading '-', never a bare '.'/'..';
#     mirrors pipeline/workspace_name.py's grammar + the case-insensitive-id lowercase rule, §23).
#   * SELF-REFERENCE SCAN — warns (does NOT rewrite) if a workspace's own config
#     (defaults.yaml / *.yaml / source.md / sources/*.md) hard-codes an absolute path into its OLD
#     flat store (`.../workspaces/<ws>/...`), which the move would break. EXTERNAL absolute paths
#     (a client repo / graph path) are fine and never warned on.
#
# Flags (see --help):
#   --owner OWNER   owner dir under users/ (default: optiquity)
#   --root DIR      repo root holding workspaces/ (default: this script's parent dir)
#   --dry-run       print the planned moves; change NOTHING on disk
#   --force         proceed past a target-exists refusal WITHOUT overwriting: an empty target is
#                   cleared and reused; a non-empty target absorbs only the NON-colliding entries,
#                   any colliding entry is left untouched and reported (never-delete-data holds)
#   -h, --help      usage
#
# Exit codes: 0 clean (incl. nothing-to-migrate) · 1 refusal (target exists / bad workspace name /
# unmovable collision) · 2 usage (bad flag / invalid --owner / bad --root).
set -euo pipefail

SELF="$(basename "$0")"

usage() {
  cat <<'EOF'
usage: migrate-to-users-layout.sh [--owner OWNER] [--root DIR] [--dry-run] [--force]

Re-home local instance workspaces from workspaces/<ws>/ to users/<owner>/workspaces/<ws>/
(design §23; CLAUDE.md rule 2). Idempotent, refuse-don't-overwrite, never-delete-data.

  --owner OWNER  owner directory under users/ (default: optiquity); must be one lowercase-safe
                 path segment
  --root DIR     repo root that contains workspaces/ (default: the parent of this script)
  --dry-run      print the planned moves and warnings; change NOTHING on disk
  --force        proceed past a target-exists refusal without overwriting any existing file
  -h, --help     show this help

Exit: 0 clean (incl. nothing to migrate) · 1 refusal · 2 usage.
EOF
}

# --- argument parsing -------------------------------------------------------------------------
OWNER="optiquity"
ROOT=""
DRY_RUN=0
FORCE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --owner)
      [ "$#" -ge 2 ] || { echo "$SELF: --owner requires a value" >&2; exit 2; }
      OWNER="$2"; shift 2 ;;
    --root)
      [ "$#" -ge 2 ] || { echo "$SELF: --root requires a value" >&2; exit 2; }
      ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --force)   FORCE=1;   shift ;;
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

# --- name hygiene (mirrors pipeline/workspace_name.py, lowercase-only per §23/W5) --------------
# First char [a-z0-9_] (rejects a bare '.'/'..' and a leading '-'); remainder adds interior
# '.'/'-'; no separator or other char; lowercase-only; single segment. Kept in a variable and
# used UNQUOTED on the RHS of [[ =~ ]] for bash 3.2 compatibility.
SAFE_SEGMENT_RE='^[a-z0-9_][a-z0-9._-]*$'

valid_segment() {  # $1=segment -> 0 if a lowercase-safe single path segment, else 1
  local seg="$1"
  [ -n "$seg" ] || return 1
  [ "${#seg}" -le 255 ] || return 1
  [[ "$seg" =~ $SAFE_SEGMENT_RE ]] || return 1
  return 0
}

if ! valid_segment "$OWNER"; then
  echo "$SELF: refusing invalid --owner '$OWNER' — an owner is ONE lowercase-safe path segment" \
       "([a-z0-9_] then [a-z0-9._-]; no separator, no leading '-', never a bare '.'/'..'; §23)." >&2
  exit 2
fi

WS_SRC="$ROOT/workspaces"
USERS_DST="$ROOT/users/$OWNER/workspaces"

# --- discover direct-child entries of workspaces/ ---------------------------------------------
shopt -s nullglob 2>/dev/null || true

if [ ! -d "$WS_SRC" ]; then
  echo "$SELF: nothing to migrate (no $WS_SRC)."
  exit 0
fi

# Collect direct-child DIRECTORY names to move; note any non-dir / symlink child as a leftover.
move_names=()
leftover=0
for entry in "$WS_SRC"/*; do
  [ -e "$entry" ] || continue                 # nullglob guard (no match -> literal '*')
  base="$(basename "$entry")"
  if [ -L "$entry" ]; then
    echo "$SELF: WARNING: skipping symlink child '$base' under workspaces/ (never followed/moved)." >&2
    leftover=1
    continue
  fi
  if [ ! -d "$entry" ]; then
    echo "$SELF: WARNING: skipping non-directory child '$base' under workspaces/ (only workspace dirs move)." >&2
    leftover=1
    continue
  fi
  move_names+=("$base")
done

if [ "${#move_names[@]}" -eq 0 ]; then
  echo "$SELF: nothing to migrate (no workspace directories under $WS_SRC)."
  exit 0
fi

# --- PRE-FLIGHT: every workspace name must be lowercase-safe (refuse the whole run if not) -----
bad_names=()
for name in "${move_names[@]}"; do
  valid_segment "$name" || bad_names+=("$name")
done
if [ "${#bad_names[@]}" -gt 0 ]; then
  echo "$SELF: REFUSING to migrate — these workspace directory names are not lowercase-safe" \
       "path segments (the re-homed code requires lowercase; rename them first, §23):" >&2
  for name in "${bad_names[@]}"; do
    echo "  - $name" >&2
  done
  exit 1
fi

# --- self-reference scan (read-only WARNING, never a rewrite) ----------------------------------
# Escape '.' in the workspace name for use inside an ERE (the only regex-special char the safe
# grammar admits). Warn on an absolute path into the OLD flat store `.../workspaces/<name>/`,
# EXCLUDING the NEW `.../users/<seg>/workspaces/<name>/` form (already forward-looking).
selfref_scan() {  # $1=workspace dir, $2=workspace name -> prints WARNINGs; sets warn flag via echo
  local wsdir="$1" name="$2" name_re g hits
  name_re="$(printf '%s' "$name" | sed 's/[.]/\\./g')"
  for g in "$wsdir"/*.yaml "$wsdir"/*.yml "$wsdir"/source.md "$wsdir"/sources/*.md; do
    [ -f "$g" ] || continue
    hits="$(grep -nE "/workspaces/${name_re}/" "$g" 2>/dev/null \
            | grep -vE "/users/[a-z0-9._-]+/workspaces/${name_re}/" 2>/dev/null || true)"
    if [ -n "$hits" ]; then
      printf 'SELF-REF[%s] %s: config hard-codes an absolute path into its OLD flat store (.../workspaces/%s/) — FIX it after the move:\n' \
        "$name" "$g" "$name"
      printf '%s\n' "$hits" | sed 's/^/    /'
    fi
  done
}

# --- move helpers -----------------------------------------------------------------------------
run() {  # execute $@, or (in --dry-run) just log the would-be action
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '  DRY-RUN would: %s\n' "$*"
  else
    "$@"
  fi
}

dir_empty() {  # $1=dir -> 0 if the dir exists and has no entries (incl. dotfiles)
  [ -d "$1" ] || return 1
  [ -z "$(ls -A "$1" 2>/dev/null)" ]
}

# --- migrate ----------------------------------------------------------------------------------
moved=()
refused=()
warned_any=0
fail=0

echo "$SELF: root=$ROOT  owner=$OWNER  dry-run=$DRY_RUN  force=$FORCE"
run mkdir -p "$USERS_DST"

for name in "${move_names[@]}"; do
  src="$WS_SRC/$name"
  dst="$USERS_DST/$name"

  # Read-only self-ref gate on the source config (works in every mode).
  scan_out="$(selfref_scan "$src" "$name" || true)"
  if [ -n "$scan_out" ]; then
    printf '%s\n' "$scan_out"
    warned_any=1
  fi

  if [ -e "$dst" ]; then
    if [ "$FORCE" -eq 0 ]; then
      echo "$SELF: REFUSING '$name' — target already exists: $dst" >&2
      echo "       (not overwriting/merging; re-run with --force to proceed without overwrite)." >&2
      refused+=("$name (target exists: $dst)")
      leftover=1; fail=1
      continue
    fi
    # --force: proceed WITHOUT overwriting any existing target file.
    if dir_empty "$dst"; then
      echo "$SELF: --force: target '$dst' is empty; clearing and moving '$name' in."
      run rmdir "$dst"
      run mv "$src" "$dst"
      moved+=("$name -> $dst")
    else
      echo "$SELF: --force: merging '$name' into existing non-empty target '$dst' (non-colliding entries only)."
      collided=0
      for e in "$src"/* "$src"/.[!.]* "$src"/..?*; do
        [ -e "$e" ] || continue
        ebase="$(basename "$e")"
        if [ -e "$dst/$ebase" ]; then
          echo "$SELF: REFUSING to overwrite existing '$dst/$ebase' — left '$e' in place." >&2
          collided=1
        else
          run mv "$e" "$dst/$ebase"
        fi
      done
      if [ "$collided" -eq 1 ]; then
        refused+=("$name (collisions left in $src)")
        leftover=1; fail=1
      elif [ "$DRY_RUN" -eq 1 ]; then
        moved+=("$name -> $dst (merge)")
      elif dir_empty "$src"; then
        run rmdir "$src"
        moved+=("$name -> $dst (merge)")
      else
        leftover=1
        moved+=("$name -> $dst (merge; source not empty)")
      fi
    fi
  else
    run mv "$src" "$dst"
    moved+=("$name -> $dst")
  fi
done

# --- remove the now-empty flat workspaces/ dir (only if truly empty) --------------------------
if [ "$DRY_RUN" -eq 1 ]; then
  if [ "$leftover" -eq 0 ]; then
    printf '  DRY-RUN would: rmdir %s\n' "$WS_SRC"
  else
    echo "$SELF: would leave $WS_SRC in place (refusals / non-workspace entries remain)."
  fi
elif dir_empty "$WS_SRC"; then
  rmdir "$WS_SRC"
  echo "$SELF: removed the now-empty $WS_SRC."
else
  echo "$SELF: left $WS_SRC in place (not empty — refusals or non-workspace entries remain)."
fi

# --- summary ----------------------------------------------------------------------------------
echo
echo "===== migrate-to-users-layout summary ====="
if [ "${#moved[@]}" -gt 0 ]; then
  echo "moved (${#moved[@]}):"
  for m in "${moved[@]}"; do echo "  + $m"; done
else
  echo "moved (0): none"
fi
if [ "${#refused[@]}" -gt 0 ]; then
  echo "refused (${#refused[@]}):"
  for r in "${refused[@]}"; do echo "  ! $r"; done
fi
if [ "$warned_any" -eq 1 ]; then
  echo "warnings: self-referential store paths found above — fix that config after the move."
fi
if [ "$DRY_RUN" -eq 1 ]; then
  echo "mode: DRY-RUN — nothing changed on disk."
fi
echo "==========================================="

exit "$fail"
