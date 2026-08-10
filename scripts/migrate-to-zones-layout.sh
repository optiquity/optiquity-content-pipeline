#!/usr/bin/env bash
# scripts/migrate-to-zones-layout.sh — the §23 ZONES on-disk re-home migration (increment Z6).
#
# USER-TRIGGERED, ONE-SHOT, IDEMPOTENT: moves EVERY local instance workspace from the pre-zone
# per-owner layout `<root>/users/<u>/workspaces/<ws>/` to the NEW zoned layout
# `<root>/users/<u>/zones/default/workspaces/<ws>/` (CLAUDE.md rule 2; design §23, Z1–Z6). The Z1–Z5
# cutover made the CODE resolve every workspace through the zoned path; this script re-homes the
# on-disk data that predates it. It is never silent-auto-run — the operator runs it once, then works
# from the new layout.
#
# The default zone is the fixed literal `default`, which MIRRORS `pipeline.workspace_name.DEFAULT_ZONE`
# (and the `--zone` CLI default). Migrating into `default` is what makes post-migration UN-FLAGGED
# commands (which resolve to zone `default`) land on the moved home. The two other layout literals —
# `zones` and `workspaces` — mirror `ZONES_DIRNAME` / `WORKSPACES_DIRNAME`. This is a pure directory
# re-home; it edits NO file contents and needs no python import.
#
# DISTINCT FROM scripts/migrate-to-users-layout.sh (the earlier flat→per-owner re-home),
# scripts/migrate-to-foundation-layout.sh (the framework-registry re-home, which uses tracked
# `git mv`), and scripts/migrate.sh (the §11.6 schema/config migration). This one moves GITIGNORED
# instance workspace data with plain `mv` (a tracked `git mv` would be WRONG — the data is not
# tracked) and re-homes EVERY user under users/ in one sweep.
#
# SAFETY (the data it moves is IRREPLACEABLE, gitignored instance data — CLAUDE.md rules 1/2/4):
#   * IDEMPOTENT — a re-run after a complete move is a clean no-op ("nothing to migrate").
#   * REFUSE, DON'T OVERWRITE — a per-workspace target that already exists is REFUSED (never
#     merged/clobbered) unless --force, and --force still NEVER overwrites an existing target file.
#   * NEVER DELETES DATA — only `mv` (atomic on one filesystem) and `rmdir` on a proven-EMPTY dir.
#     The rmdir target is ALWAYS the now-empty per-user `users/<u>/workspaces/` — NEVER `users/<u>/`
#     itself and NEVER any zone dir. `users/<u>/` always survives a run.
#   * NEVER MOVES OUTSIDE <root> — every source and target is a validated, contained path segment.
#
# It also runs two read-only gates before moving each user's workspaces:
#   * NAME HYGIENE — the user dir name (NEW: swept level) and every workspace dir name must be one
#     lowercase-safe path segment ([a-z0-9_] then [a-z0-9._-]; no separator, no leading '-', never a
#     bare '.'/'..'; mirrors pipeline/workspace_name.py's grammar + the lowercase rule, §23).
#   * SELF-REFERENCE SCAN — warns (does NOT rewrite) if a workspace's own config
#     (defaults.yaml / *.yaml / source.md / sources/*.md) hard-codes an absolute path into its
#     PRE-ZONE store (`.../users/<u>/workspaces/<ws>/...`), which the zone move would break. The NEW
#     zoned form (`.../users/<u>/zones/<z>/workspaces/<ws>/...`) and EXTERNAL absolute paths are fine.
#
# Flags (see --help):
#   --root DIR   repo root holding users/ (default: this script's parent dir)
#   --dry-run    print the planned moves; change NOTHING on disk
#   --force      proceed past a target-exists refusal WITHOUT overwriting: an empty target is cleared
#                and reused; a non-empty target absorbs only the NON-colliding entries, any colliding
#                entry is left untouched and reported (never-delete-data holds)
#   -h, --help   usage
#
# Exit codes: 0 clean (incl. nothing-to-migrate) · 1 refusal (target exists / bad workspace name /
# unmovable collision, for ANY user) · 2 usage (bad flag / bad --root).
set -euo pipefail

SELF="$(basename "$0")"

# Fixed layout literals — the JOIN `zones/default/workspaces` is fixed (NOT a flag). See header:
# these mirror pipeline.workspace_name.{ZONES_DIRNAME,DEFAULT_ZONE,WORKSPACES_DIRNAME}.
ZONES_DIRNAME="zones"
ZONE="default"
WORKSPACES_DIRNAME="workspaces"

usage() {
  cat <<'EOF'
usage: migrate-to-zones-layout.sh [--root DIR] [--dry-run] [--force]

Re-home EVERY local instance workspace from users/<u>/workspaces/<ws>/ to
users/<u>/zones/default/workspaces/<ws>/ (design §23, Z6; CLAUDE.md rule 2). Sweeps every user
under users/. Idempotent, refuse-don't-overwrite, never-delete-data.

  --root DIR   repo root that contains users/ (default: the parent of this script)
  --dry-run    print the planned moves and warnings; change NOTHING on disk
  --force      proceed past a target-exists refusal without overwriting any existing file
  -h, --help   show this help

Exit: 0 clean (incl. nothing to migrate) · 1 refusal · 2 usage.
EOF
}

# --- argument parsing -------------------------------------------------------------------------
ROOT=""
DRY_RUN=0
FORCE=0

while [ "$#" -gt 0 ]; do
  case "$1" in
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

# --- helpers ----------------------------------------------------------------------------------
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

# --- self-reference scan (read-only WARNING, never a rewrite) ----------------------------------
# DELTA 4 (INVERTED regex): warn on an absolute path into the PRE-ZONE store
# `.../workspaces/<name>/` — the OLD per-owner form `.../users/<u>/workspaces/<name>/` and any bare
# `.../workspaces/<name>/` both BREAK after the zone move — EXCLUDING only the NEW zoned form
# `.../users/<u>/zones/<z>/workspaces/<name>/` (already forward-looking). This inverts the model,
# whose exclusion (`/users/<u>/workspaces/<name>/`) is exactly the form we must now WARN on.
selfref_scan() {  # $1=workspace dir, $2=workspace name -> prints WARNINGs on stdout
  local wsdir="$1" name="$2" name_re g hits
  name_re="$(printf '%s' "$name" | sed 's/[.]/\\./g')"
  for g in "$wsdir"/*.yaml "$wsdir"/*.yml "$wsdir"/source.md "$wsdir"/sources/*.md; do
    [ -f "$g" ] || continue
    hits="$(grep -nE "/${WORKSPACES_DIRNAME}/${name_re}/" "$g" 2>/dev/null \
            | grep -vE "/users/[a-z0-9._-]+/${ZONES_DIRNAME}/[a-z0-9._-]+/${WORKSPACES_DIRNAME}/${name_re}/" 2>/dev/null || true)"
    if [ -n "$hits" ]; then
      printf 'SELF-REF[%s] %s: config hard-codes an absolute path into its PRE-ZONE store (.../%s/%s/) — the zone move BREAKS it; FIX it after the move:\n' \
        "$name" "$g" "$WORKSPACES_DIRNAME" "$name"
      printf '%s\n' "$hits" | sed 's/^/    /'
    fi
  done
}

# --- global coverage accumulators (DELTA 2) ---------------------------------------------------
users_scanned=0
users_migrated=0
users_skipped=0
users_refused=0
skipped_reasons=()
refused_details=()
moved_all=()
warned_any=0
fail=0
SUMMARY_PRINTED=0

print_summary() {
  [ "$SUMMARY_PRINTED" -eq 1 ] && return 0
  SUMMARY_PRINTED=1
  echo
  echo "===== migrate-to-zones-layout summary ====="
  echo "users scanned:  $users_scanned"
  echo "users migrated: $users_migrated"
  echo "users skipped:  $users_skipped"
  if [ "${#skipped_reasons[@]}" -gt 0 ]; then
    for r in "${skipped_reasons[@]}"; do echo "    - skip: $r"; done
  fi
  echo "users refused:  $users_refused"
  if [ "${#refused_details[@]}" -gt 0 ]; then
    for r in "${refused_details[@]}"; do echo "    ! refused: $r"; done
  fi
  if [ "${#moved_all[@]}" -gt 0 ]; then
    echo "workspaces moved (${#moved_all[@]}):"
    for m in "${moved_all[@]}"; do echo "  + $m"; done
  else
    echo "workspaces moved (0): none"
  fi
  if [ "$warned_any" -eq 1 ]; then
    echo "warnings: self-referential PRE-ZONE store paths found above — fix that config after the move."
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "mode: DRY-RUN — nothing changed on disk."
  fi
  echo "==========================================="
}

# FIX 2 (belt-and-suspenders): even if an unexpected error aborts the sweep, ALWAYS print the
# coverage summary so a run NEVER ends silently. On the normal path print_summary already ran and
# set the guard, so this trap is a no-op there.
on_exit() {
  if [ "$SUMMARY_PRINTED" -eq 0 ]; then
    echo "$SELF: WARNING: run ended before the sweep completed — partial coverage follows." >&2
    print_summary
  fi
}
trap on_exit EXIT

USERS_ROOT="$ROOT/users"
echo "$SELF: root=$ROOT  zone=$ZONE  dry-run=$DRY_RUN  force=$FORCE"

shopt -s nullglob 2>/dev/null || true

if [ ! -d "$USERS_ROOT" ]; then
  echo "$SELF: nothing to migrate (no $USERS_ROOT)."
  print_summary
  exit 0
fi

# --- DELTA 1: OUTER SWEEP over every user under users/ ----------------------------------------
# The model took a single --owner and moved ROOT/workspaces/<ws>. users/<u>/workspaces/ is already
# multi-user, so we sweep EVERY user dir. Per user we move each <ws> under workspaces/ into
# zones/default/workspaces/. A per-user problem is a `continue` (DELTA 2), never a run terminator.
for udir in "$USERS_ROOT"/*/; do
  udir="${udir%/}"
  uname="$(basename "$udir")"

  # --- DELTA 3: NEW user-level guard (the swept users/*/ level is a new symlink surface) --------
  # A symlinked user dir must NEVER be followed by mv/rmdir; the model only guarded workspace
  # CHILDREN. Also valid_segment-check the user name before treating it as an owner.
  if [ -L "$udir" ]; then
    echo "$SELF: WARNING: skipping symlinked user dir '$uname' (never followed/moved)." >&2
    users_scanned=$((users_scanned + 1))
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (symlinked user dir)")
    continue
  fi
  [ -d "$udir" ] || continue   # `*/` only yields dirs/symlinks-to-dirs; belt-and-suspenders
  if ! valid_segment "$uname"; then
    echo "$SELF: WARNING: skipping user dir '$uname' — not a lowercase-safe path segment (§23)." >&2
    users_scanned=$((users_scanned + 1))
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (unsafe user name)")
    continue
  fi

  users_scanned=$((users_scanned + 1))

  WS_SRC="$udir/$WORKSPACES_DIRNAME"
  ZONE_DST="$udir/$ZONES_DIRNAME/$ZONE/$WORKSPACES_DIRNAME"
  ZONES_ROOT="$udir/$ZONES_DIRNAME"

  # --- FIX 1 (source side): NEVER follow or rmdir a SYMLINKED workspaces/ (a new symlink surface) -
  # The DELTA-2 `[ ! -d "$WS_SRC" ]` below FOLLOWS a symlink; guard it first (mirroring the user-dir
  # guard) so a symlinked workspaces/ (e.g. -> another tree) is a per-user skip, never traversed.
  if [ -L "$WS_SRC" ]; then
    echo "$SELF: [$uname] WARNING: skipping — '$WS_SRC' is a symlink (never followed/moved)." >&2
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (symlinked workspaces/)")
    continue
  fi

  # --- DELTA 2: missing workspaces/ is a PER-USER skip (continue), not an exit ------------------
  if [ ! -d "$WS_SRC" ]; then
    echo "$SELF: [$uname] nothing to migrate (no $WS_SRC)."
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (no workspaces/)")
    continue
  fi

  # Collect direct-child DIRECTORY names to move; note any non-dir / symlink child as a leftover.
  move_names=()
  leftover=0
  for entry in "$WS_SRC"/*; do
    [ -e "$entry" ] || continue                 # nullglob guard (no match -> nothing)
    base="$(basename "$entry")"
    if [ -L "$entry" ]; then
      echo "$SELF: [$uname] WARNING: skipping symlink child '$base' under workspaces/ (never followed/moved)." >&2
      leftover=1
      continue
    fi
    if [ ! -d "$entry" ]; then
      echo "$SELF: [$uname] WARNING: skipping non-directory child '$base' under workspaces/ (only workspace dirs move)." >&2
      leftover=1
      continue
    fi
    move_names+=("$base")
  done

  # --- DELTA 2: empty workspaces/ is a PER-USER skip (continue), not an exit --------------------
  if [ "${#move_names[@]}" -eq 0 ]; then
    echo "$SELF: [$uname] nothing to migrate (no workspace directories under $WS_SRC)."
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (empty workspaces/)")
    continue
  fi

  # PRE-FLIGHT: every workspace name must be lowercase-safe. DELTA 2: refuse THIS USER (continue),
  # not the whole run.
  bad_names=()
  for name in "${move_names[@]}"; do
    valid_segment "$name" || bad_names+=("$name")
  done
  if [ "${#bad_names[@]}" -gt 0 ]; then
    echo "$SELF: [$uname] REFUSING — these workspace directory names are not lowercase-safe path" \
         "segments (the re-homed code requires lowercase; rename them first, §23):" >&2
    for name in "${bad_names[@]}"; do
      echo "  - $name" >&2
    done
    users_refused=$((users_refused + 1))
    refused_details+=("$uname (unsafe workspace names: ${bad_names[*]})")
    fail=1
    continue
  fi

  # --- migrate THIS user's workspaces ----------------------------------------------------------
  # --- FIX 1/3 (target side): the zone layer is a NEW symlink surface — users/<u>/zones must be a
  # real dir we own, NEVER a symlink or a non-dir file, or `mkdir -p` / `mv` would escape <root>
  # (e.g. a symlinked zones/ -> elsewhere). Refuse the user (per-user skip) if so.
  if [ -L "$ZONES_ROOT" ] || { [ -e "$ZONES_ROOT" ] && [ ! -d "$ZONES_ROOT" ]; }; then
    echo "$SELF: [$uname] WARNING: skipping — '$ZONES_ROOT' is a symlink or non-directory" \
         "(never migrated through — would escape <root>)." >&2
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (zones/ is a symlink or non-directory)")
    continue
  fi

  echo "$SELF: [$uname] migrating $WS_SRC -> $ZONE_DST"

  # --- FIX R1 (pre-mkdir PHYSICAL CONTAINMENT): a symlink at ANY intermediate target level (zones,
  # zones/default, zones/default/workspaces, …) would let `mkdir -p` create/traverse OUTSIDE the user
  # home and `mv` relocate the ONLY copy of client data out of <root> (the leaf `[ -L "$dst" ]` and
  # first-level `$ZONES_ROOT` checks miss the middle levels). ONE `pwd -P` on the deepest EXISTING
  # ancestor catches EVERY level in a single generic check (not per-level [ -L ]); doing it BEFORE
  # mkdir means we never even create an empty dir THROUGH a symlinked intermediate (keeps any
  # external tree byte-for-byte unchanged). A resolve failure is a per-user skip, never an abort.
  owner_phys="$(cd "$udir" 2>/dev/null && pwd -P)" || owner_phys=""
  if [ -z "$owner_phys" ]; then
    echo "$SELF: [$uname] WARNING: skipping — cannot resolve user home '$udir'." >&2
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (cannot resolve user home)")
    continue
  fi
  anc="$ZONE_DST"
  while [ ! -e "$anc" ] && [ "$anc" != "/" ] && [ "$anc" != "." ]; do anc="$(dirname "$anc")"; done
  anc_phys="$(cd "$anc" 2>/dev/null && pwd -P)" || anc_phys=""
  case "${anc_phys:+$anc_phys/}" in
    "$owner_phys"/*) : ;;   # deepest existing ancestor is physically under the user home — safe
    *)
      echo "$SELF: [$uname] WARNING: skipping — zone target '$ZONE_DST' escapes <root> via a" \
           "symlinked intermediate (resolves outside the user home) — nothing created or moved." >&2
      users_skipped=$((users_skipped + 1))
      skipped_reasons+=("$uname (zone target escapes <root>)")
      continue ;;
  esac

  # FIX 2: guard the mkdir so any failure is a per-user skip, never a whole-sweep abort under set -e.
  if ! run mkdir -p "$ZONE_DST"; then
    echo "$SELF: [$uname] WARNING: skipping — could not create target '$ZONE_DST'." >&2
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (could not create zone target)")
    continue
  fi
  # FIX R1 (post-mkdir re-check, real mode + TOCTOU): re-derive the FULL physical target right before
  # the move loop and re-assert containment — defends against a symlink swapped in after the
  # pre-check/mkdir. (Dry-run creates nothing, so there is nothing to re-resolve.)
  if [ "$DRY_RUN" -eq 0 ]; then
    zone_dst_phys="$(cd "$ZONE_DST" 2>/dev/null && pwd -P)" || zone_dst_phys=""
    case "${zone_dst_phys:+$zone_dst_phys/}" in
      "$owner_phys"/*) : ;;   # physically contained under the user home — OK to move
      *)
        echo "$SELF: [$uname] WARNING: skipping — zone target '$ZONE_DST' is not physically contained" \
             "under the user home after mkdir (symlinked intermediate?) — nothing moved." >&2
        users_skipped=$((users_skipped + 1))
        skipped_reasons+=("$uname (zone target escapes <root>)")
        continue ;;
    esac
  fi

  user_moved=0
  user_refused=0
  for name in "${move_names[@]}"; do
    src="$WS_SRC/$name"
    dst="$ZONE_DST/$name"

    # Read-only self-ref gate on the source config (works in every mode).
    scan_out="$(selfref_scan "$src" "$name" || true)"
    if [ -n "$scan_out" ]; then
      printf '%s\n' "$scan_out"
      warned_any=1
    fi

    # FIX 3: NEVER move into/through a symlinked target path (covers a DANGLING symlink too, which
    # `[ -e "$dst" ]` below would miss and `mv` would then follow OUT of <root>). Refuse this ws.
    if [ -L "$dst" ]; then
      echo "$SELF: [$uname] REFUSING '$name' — target path '$dst' is a symlink (never moved through)." >&2
      refused_details+=("$uname/$name (target is a symlink: $dst)")
      leftover=1; user_refused=1; fail=1
      continue
    fi

    if [ -e "$dst" ]; then
      if [ "$FORCE" -eq 0 ]; then
        echo "$SELF: [$uname] REFUSING '$name' — target already exists: $dst" >&2
        echo "       (not overwriting/merging; re-run with --force to proceed without overwrite)." >&2
        refused_details+=("$uname/$name (target exists: $dst)")
        leftover=1; user_refused=1; fail=1
        continue
      fi
      # --force: proceed WITHOUT overwriting any existing target file.
      if dir_empty "$dst"; then
        echo "$SELF: [$uname] --force: target '$dst' is empty; clearing and moving '$name' in."
        # FIX 2: guard the rmdir + mv so a failure skips this workspace, never aborts the sweep.
        if ! run rmdir "$dst"; then
          echo "$SELF: [$uname] WARNING: could not clear empty target '$dst' — skipping '$name'." >&2
          refused_details+=("$uname/$name (could not clear empty target)")
          leftover=1; user_refused=1; fail=1
          continue
        fi
        if ! run mv "$src" "$dst"; then
          echo "$SELF: [$uname] WARNING: mv of '$name' into '$dst' failed — left in place." >&2
          refused_details+=("$uname/$name (mv failed)")
          leftover=1; user_refused=1; fail=1
          continue
        fi
        moved_all+=("$uname/$name -> $dst")
        user_moved=1
      else
        echo "$SELF: [$uname] --force: merging '$name' into existing non-empty target '$dst' (non-colliding entries only)."
        collided=0
        for e in "$src"/* "$src"/.[!.]* "$src"/..?*; do
          [ -e "$e" ] || continue
          ebase="$(basename "$e")"
          if [ -e "$dst/$ebase" ]; then
            echo "$SELF: [$uname] REFUSING to overwrite existing '$dst/$ebase' — left '$e' in place." >&2
            collided=1
          else
            # FIX 2: guard the merge mv — a failure leaves the entry (like a collision), never aborts.
            if ! run mv "$e" "$dst/$ebase"; then
              echo "$SELF: [$uname] WARNING: could not merge '$e' -> '$dst/$ebase' — left in place." >&2
              collided=1
            fi
          fi
        done
        if [ "$collided" -eq 1 ]; then
          refused_details+=("$uname/$name (collisions left in $src)")
          leftover=1; user_refused=1; fail=1
        elif [ "$DRY_RUN" -eq 1 ]; then
          moved_all+=("$uname/$name -> $dst (merge)")
          user_moved=1
        elif dir_empty "$src"; then
          # FIX 2: guard the source rmdir — a failure leaves the emptied dir, never aborts.
          if run rmdir "$src"; then
            moved_all+=("$uname/$name -> $dst (merge)")
          else
            echo "$SELF: [$uname] WARNING: could not rmdir emptied source '$src' — left in place." >&2
            leftover=1
            moved_all+=("$uname/$name -> $dst (merge; source dir remains)")
          fi
          user_moved=1
        else
          leftover=1
          moved_all+=("$uname/$name -> $dst (merge; source not empty)")
          user_moved=1
        fi
      fi
    else
      # FIX 2: guard the mv so a failure skips this workspace, never aborts the sweep under set -e.
      if ! run mv "$src" "$dst"; then
        echo "$SELF: [$uname] WARNING: mv of '$name' into '$dst' failed — left in place." >&2
        refused_details+=("$uname/$name (mv failed)")
        leftover=1; user_refused=1; fail=1
        continue
      fi
      moved_all+=("$uname/$name -> $dst")
      user_moved=1
    fi
  done

  # --- remove the now-empty PER-USER workspaces/ dir (only if truly empty) ----------------------
  # NEVER-DELETE-users/<u>/ INVARIANT: the rmdir target is ALWAYS $WS_SRC (= users/<u>/workspaces/),
  # NEVER $udir (= users/<u>/) and NEVER any zone dir. users/<u>/ always survives.
  if [ "$DRY_RUN" -eq 1 ]; then
    if [ "$leftover" -eq 0 ]; then
      printf '  DRY-RUN would: rmdir %s\n' "$WS_SRC"
    else
      echo "$SELF: [$uname] would leave $WS_SRC in place (refusals / non-workspace entries remain)."
    fi
  elif dir_empty "$WS_SRC"; then
    # FIX 2: guard the rmdir — a racing/non-empty source must NOT abort the sweep; leaving it is safe.
    if rmdir "$WS_SRC" 2>/dev/null; then
      echo "$SELF: [$uname] removed the now-empty $WS_SRC."
    else
      echo "$SELF: [$uname] WARNING: could not rmdir $WS_SRC — left in place." >&2
    fi
  else
    echo "$SELF: [$uname] left $WS_SRC in place (not empty — refusals or non-workspace entries remain)."
  fi

  # --- per-user tally (refused > migrated > no-op; keeps scanned = migrated+skipped+refused) -----
  if [ "$user_refused" -eq 1 ]; then
    users_refused=$((users_refused + 1))
  elif [ "$user_moved" -eq 1 ]; then
    users_migrated=$((users_migrated + 1))
  else
    users_skipped=$((users_skipped + 1))
    skipped_reasons+=("$uname (no-op)")
  fi
done

print_summary
exit "$fail"
