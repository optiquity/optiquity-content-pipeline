#!/usr/bin/env bash
# tests/test_migrate_to_zones.sh — committed fixture harness for scripts/migrate-to-zones-layout.sh
# (§23 zones re-home, increment Z6). Builds a THROWAWAY users/ fixture under a mktemp -d and runs the
# migration against it ONLY (NEVER the repo's real users/ tree). Each assertion is a real check with a
# clear PASS/FAIL. Exits 0 iff every assertion passes.
#
# Run: bash tests/test_migrate_to_zones.sh
#
# NOTE: deliberately does NOT `set -e` — assertions must keep running past a script's non-zero exit
# (refusal paths return 1 by design), and we capture each run's exit code explicitly.
set -uo pipefail

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SELF_DIR/.." && pwd)"
SCRIPT="$REPO_ROOT/scripts/migrate-to-zones-layout.sh"

PASS=0
FAIL=0
pass() { PASS=$((PASS + 1)); echo "PASS: $1"; }
fail() { FAIL=$((FAIL + 1)); echo "FAIL: $1"; }

assert_file()     { if [ -f "$1" ]; then pass "$2"; else fail "$2 (missing file: $1)"; fi; }
assert_dir()      { if [ -d "$1" ]; then pass "$2"; else fail "$2 (missing dir: $1)"; fi; }
assert_symlink()  { if [ -L "$1" ]; then pass "$2"; else fail "$2 (not a symlink: $1)"; fi; }
assert_absent()   { if [ ! -e "$1" ] && [ ! -L "$1" ]; then pass "$2"; else fail "$2 (still exists: $1)"; fi; }
assert_eq()       { if [ "$1" = "$2" ]; then pass "$3"; else fail "$3 (got '$1' want '$2')"; fi; }
# substring (literal) presence / absence in a captured blob:
assert_has()      { if printf '%s' "$1" | grep -qF -- "$2"; then pass "$3"; else fail "$3 (missing: $2)"; fi; }
assert_hasnt()    { if printf '%s' "$1" | grep -qF -- "$2"; then fail "$3 (unexpected: $2)"; else pass "$3"; fi; }
# regex presence in a captured blob:
assert_re()       { if printf '%s' "$1" | grep -qE -- "$2"; then pass "$3"; else fail "$3 (no match: $2)"; fi; }

filehash() { shasum "$1" 2>/dev/null | awk '{print $1}'; }
# stable content+shape manifest of a tree, relative-pathed so two identical trees compare equal:
manifest() { ( cd "$1" 2>/dev/null && { find . -type f -exec shasum {} \; | sort;
                                        echo "--dirs--";  find . -type d | sort;
                                        echo "--links--"; find . -type l | sort; } ); }

[ -f "$SCRIPT" ] && pass "script present: $SCRIPT" || { fail "script missing: $SCRIPT"; echo "PASS=$PASS FAIL=$FAIL"; exit 1; }

TMP="$(mktemp -d 2>/dev/null || mktemp -d -t zonesmig)"
trap 'rm -rf "$TMP"' EXIT
echo "# tmp fixture root: $TMP"

# =============================================================================================
# Fixture builder — a fresh users/ tree under $ROOT, plus an EXTERNAL tree the symlinked user
# points at (outside $ROOT so a followed symlink would be detectable).
# Scan order is the alphabetical `users/*/` glob; 'auser_no_ws' (B) sorts BEFORE 'buser_has_ws'
# (A) to prove a no-workspaces user is a per-user skip, not an early halt.
# =============================================================================================
build_main() {
  ROOT="$TMP/repo"
  EXT="$TMP/external_home"
  rm -rf "$ROOT" "$EXT"

  # --- B: user with NO workspaces/ but OTHER content (a stray file + a pre-existing zones/) ------
  mkdir -p "$ROOT/users/auser_no_ws/zones"
  printf 'stray-bytes\n'    > "$ROOT/users/auser_no_ws/stray.txt"
  printf 'preexisting-zone\n' > "$ROOT/users/auser_no_ws/zones/keep.txt"

  # --- A: user WITH workspaces to migrate (incl. ws named 'zones'/'default' + self-ref configs) --
  mkdir -p "$ROOT/users/buser_has_ws/workspaces/blog/sources"
  mkdir -p "$ROOT/users/buser_has_ws/workspaces/docs"
  mkdir -p "$ROOT/users/buser_has_ws/workspaces/zones"     # workspace literally named 'zones'
  mkdir -p "$ROOT/users/buser_has_ws/workspaces/default"   # workspace literally named 'default'
  printf 'blog-content-bytes\n' > "$ROOT/users/buser_has_ws/workspaces/blog/content.md"
  printf 'note\n'               > "$ROOT/users/buser_has_ws/workspaces/blog/sources/note.md"
  printf 'z\n' > "$ROOT/users/buser_has_ws/workspaces/zones/marker.txt"
  printf 'd\n' > "$ROOT/users/buser_has_ws/workspaces/default/marker.txt"
  # blog config: an OLD pre-zone self-ref (MUST warn) + a zoned self-ref + an external path.
  cat > "$ROOT/users/buser_has_ws/workspaces/blog/defaults.yaml" <<'YAML'
old_store: /srv/users/buser_has_ws/workspaces/blog/store
new_store: /srv/users/buser_has_ws/zones/default/workspaces/blog/store
external:  /Users/someone/client-repo/graphify-out/graph.json
YAML
  # docs config: ONLY the zoned self-ref + an external path (MUST NOT warn).
  cat > "$ROOT/users/buser_has_ws/workspaces/docs/defaults.yaml" <<'YAML'
new_store: /srv/users/buser_has_ws/zones/default/workspaces/docs/store
external:  /Users/someone/other-repo/graph.json
YAML

  # --- D: already-migrated user (content already under zones/default/, no workspaces/) -----------
  mkdir -p "$ROOT/users/cuser_migrated/zones/default/workspaces/done"
  printf 'already-migrated\n' > "$ROOT/users/cuser_migrated/zones/default/workspaces/done/file.txt"

  # --- C1: uppercase (unsafe) user name → must be skipped-with-warning, tree intact --------------
  mkdir -p "$ROOT/users/BadUser/workspaces/keepme"
  printf 'keep\n' > "$ROOT/users/BadUser/workspaces/keepme/data.txt"

  # --- C2: symlinked user dir → must be skipped, NEVER followed -----------------------------------
  mkdir -p "$EXT/workspaces/ws1"
  printf 'payload\n' > "$EXT/workspaces/ws1/payload.txt"
  ln -s "$EXT" "$ROOT/users/sym_user"
}

# =============================================================================================
# SCENARIO 1 — --dry-run mutates NOTHING (manifest before == after).
# =============================================================================================
echo; echo "### scenario: --dry-run mutates nothing"
build_main
before="$(manifest "$ROOT")"
ext_before="$(manifest "$EXT")"
dry_out="$(bash "$SCRIPT" --dry-run --root "$ROOT" 2>&1)"; dry_rc=$?
after="$(manifest "$ROOT")"
ext_after="$(manifest "$EXT")"
assert_eq "$dry_rc" "0" "dry-run exits 0"
assert_eq "$before" "$after" "dry-run leaves \$ROOT byte-for-byte unchanged"
assert_eq "$ext_before" "$ext_after" "dry-run leaves the external (symlinked) tree unchanged"
assert_has "$dry_out" "DRY-RUN — nothing changed on disk." "dry-run summary announces no changes"
assert_has "$dry_out" "DRY-RUN would: rmdir $ROOT/users/buser_has_ws/workspaces" "dry-run predicts rmdir of the empty per-user workspaces/ only"

# =============================================================================================
# SCENARIO 2 — real migration run; assert A/B/C/D + zones/default names + self-ref + counts.
# =============================================================================================
echo; echo "### scenario: real migration run"
# checksums captured BEFORE the move, to prove byte preservation across the mv:
h_blog="$(filehash "$ROOT/users/buser_has_ws/workspaces/blog/content.md")"
h_zonesws="$(filehash "$ROOT/users/buser_has_ws/workspaces/zones/marker.txt")"
h_stray="$(filehash "$ROOT/users/auser_no_ws/stray.txt")"
h_done="$(filehash "$ROOT/users/cuser_migrated/zones/default/workspaces/done/file.txt")"
h_bad="$(filehash "$ROOT/users/BadUser/workspaces/keepme/data.txt")"

out="$(bash "$SCRIPT" --root "$ROOT" 2>&1)"; rc=$?
assert_eq "$rc" "0" "run exits 0 (no refusals in the main fixture)"

# --- A: each workspace relocated under zones/default/workspaces/, BYTES preserved --------------
assert_file "$ROOT/users/buser_has_ws/zones/default/workspaces/blog/content.md" "A: blog relocated under zones/default/workspaces/"
assert_file "$ROOT/users/buser_has_ws/zones/default/workspaces/blog/sources/note.md" "A: blog subtree (sources/) moved wholesale"
assert_eq "$(filehash "$ROOT/users/buser_has_ws/zones/default/workspaces/blog/content.md")" "$h_blog" "A: blog/content.md bytes preserved across the move"
assert_file "$ROOT/users/buser_has_ws/zones/default/workspaces/docs/defaults.yaml" "A: docs workspace relocated"
assert_absent "$ROOT/users/buser_has_ws/workspaces" "A: emptied per-user workspaces/ was rmdir'd"

# --- ws literally named 'zones' / 'default' moved correctly (it's the ws name, not the join) ---
assert_file "$ROOT/users/buser_has_ws/zones/default/workspaces/zones/marker.txt" "ws named 'zones' moved to .../zones/default/workspaces/zones"
assert_eq "$(filehash "$ROOT/users/buser_has_ws/zones/default/workspaces/zones/marker.txt")" "$h_zonesws" "ws named 'zones' bytes preserved"
assert_file "$ROOT/users/buser_has_ws/zones/default/workspaces/default/marker.txt" "ws named 'default' moved to .../zones/default/workspaces/default"

# --- B: no-workspaces user UNTOUCHED, and the sweep CONTINUED to the later has-ws user ----------
assert_file "$ROOT/users/auser_no_ws/stray.txt" "B: no-ws user's stray file untouched"
assert_eq "$(filehash "$ROOT/users/auser_no_ws/stray.txt")" "$h_stray" "B: no-ws user's stray file bytes unchanged"
assert_file "$ROOT/users/auser_no_ws/zones/keep.txt" "B: no-ws user's pre-existing zones/ untouched"
assert_absent "$ROOT/users/auser_no_ws/zones/default" "B: no join created under a skipped user's pre-existing zones/"
# (buser_has_ws being migrated above already proves the sweep did not halt at auser_no_ws.)

# --- C1: uppercase user name skipped-with-warning, tree intact ---------------------------------
assert_has "$out" "skipping user dir 'BadUser'" "C1: uppercase user name skipped-with-warning"
assert_file "$ROOT/users/BadUser/workspaces/keepme/data.txt" "C1: unsafe-named user's tree left intact"
assert_eq "$(filehash "$ROOT/users/BadUser/workspaces/keepme/data.txt")" "$h_bad" "C1: unsafe-named user's file bytes unchanged"
assert_absent "$ROOT/users/BadUser/zones" "C1: unsafe-named user never got a zones/ join"

# --- C2: symlinked user dir skipped, NEVER followed (external tree untouched) -------------------
assert_has "$out" "skipping symlinked user dir 'sym_user'" "C2: symlinked user dir skipped-with-warning"
assert_symlink "$ROOT/users/sym_user" "C2: symlinked user dir still a symlink after the run"
assert_file "$EXT/workspaces/ws1/payload.txt" "C2: symlink target's workspaces/ NOT moved (never followed)"
assert_absent "$EXT/zones" "C2: no zones/ join created inside the symlink target"

# --- D: already-migrated user is a no-op, its content intact -----------------------------------
assert_file "$ROOT/users/cuser_migrated/zones/default/workspaces/done/file.txt" "D: already-migrated content untouched"
assert_eq "$(filehash "$ROOT/users/cuser_migrated/zones/default/workspaces/done/file.txt")" "$h_done" "D: already-migrated file bytes unchanged"
assert_absent "$ROOT/users/cuser_migrated/workspaces" "D: no stray workspaces/ created for an already-migrated user"

# --- self-ref inversion: OLD form WARNS; zoned form does NOT ------------------------------------
assert_has "$out" "SELF-REF[blog]" "self-ref: OLD pre-zone path (.../workspaces/blog/) WARNS"
assert_hasnt "$out" "SELF-REF[docs]" "self-ref: zoned-only config (.../zones/default/workspaces/docs/) does NOT warn"

# --- aggregate coverage summary prints and counts A–D correctly --------------------------------
assert_re "$out" "users scanned: +5"  "summary: users scanned = 5"
assert_re "$out" "users migrated: +1" "summary: users migrated = 1 (buser_has_ws)"
assert_re "$out" "users skipped: +4"  "summary: users skipped = 4 (B no-ws, D migrated, C1 badname, C2 symlink)"
assert_re "$out" "users refused: +0"  "summary: users refused = 0"
assert_re "$out" "workspaces moved \(4\)" "summary: 4 workspaces moved (blog, docs, zones, default)"

# --- NEVER-DELETE-users/<u>/ invariant: every user dir still exists after the run ---------------
assert_dir     "$ROOT/users/auser_no_ws"   "never-delete: users/auser_no_ws still exists"
assert_dir     "$ROOT/users/buser_has_ws"  "never-delete: users/buser_has_ws still exists (only its empty workspaces/ was rmdir'd)"
assert_dir     "$ROOT/users/cuser_migrated" "never-delete: users/cuser_migrated still exists"
assert_dir     "$ROOT/users/BadUser"       "never-delete: users/BadUser still exists"
assert_symlink "$ROOT/users/sym_user"      "never-delete: users/sym_user still exists"

# =============================================================================================
# SCENARIO 3 — idempotent re-run over the migrated tree is a clean no-op.
# =============================================================================================
echo; echo "### scenario: idempotent re-run"
pre_rerun="$(manifest "$ROOT")"
out2="$(bash "$SCRIPT" --root "$ROOT" 2>&1)"; rc2=$?
post_rerun="$(manifest "$ROOT")"
assert_eq "$rc2" "0" "re-run exits 0"
assert_eq "$pre_rerun" "$post_rerun" "re-run leaves the migrated tree byte-for-byte unchanged"
assert_has "$out2" "workspaces moved (0): none" "re-run moves nothing (clean no-op)"
assert_re  "$out2" "users migrated: +0" "re-run: users migrated = 0"

# =============================================================================================
# SCENARIO 4 — refuse-don't-clobber, and --force merges non-colliding entries WITHOUT overwriting.
# =============================================================================================
echo; echo "### scenario: refuse-don't-clobber + --force merge (never-overwrite)"
FROOT="$TMP/frepo"
rm -rf "$FROOT"
mkdir -p "$FROOT/users/fuser/workspaces/blog"
printf 'SOURCE-A\n' > "$FROOT/users/fuser/workspaces/blog/collide.txt"
printf 'SOURCE-B\n' > "$FROOT/users/fuser/workspaces/blog/onlysrc.txt"
# a pre-existing NON-EMPTY target with a COLLIDING file whose bytes differ from the source's:
mkdir -p "$FROOT/users/fuser/zones/default/workspaces/blog"
printf 'TARGET-A\n' > "$FROOT/users/fuser/zones/default/workspaces/blog/collide.txt"
h_target_collide="$(filehash "$FROOT/users/fuser/zones/default/workspaces/blog/collide.txt")"

# (a) WITHOUT --force → refuse, exit 1, nothing moved, target file untouched.
rout="$(bash "$SCRIPT" --root "$FROOT" 2>&1)"; rrc=$?
assert_eq "$rrc" "1" "refuse: run without --force exits 1 (target exists)"
assert_has "$rout" "REFUSING 'blog' — target already exists" "refuse: reports target-exists refusal"
assert_file "$FROOT/users/fuser/workspaces/blog/collide.txt" "refuse: source workspace left in place"
assert_eq "$(filehash "$FROOT/users/fuser/zones/default/workspaces/blog/collide.txt")" "$h_target_collide" "refuse: existing target file NOT overwritten"

# (b) WITH --force → merge non-colliding, leave the colliding file, NEVER overwrite; exit 1.
fout="$(bash "$SCRIPT" --root "$FROOT" --force 2>&1)"; frc=$?
assert_eq "$frc" "1" "force-merge: collision keeps the run's exit 1 (unmovable collision)"
assert_file "$FROOT/users/fuser/zones/default/workspaces/blog/onlysrc.txt" "force-merge: non-colliding entry merged into target"
assert_eq "$(filehash "$FROOT/users/fuser/zones/default/workspaces/blog/collide.txt")" "$h_target_collide" "force-merge: colliding target file STILL not overwritten"
assert_file "$FROOT/users/fuser/workspaces/blog/collide.txt" "force-merge: colliding source entry left in place (never deleted)"
assert_dir "$FROOT/users/fuser" "force-merge: users/fuser still exists"

# =============================================================================================
# SCENARIO 5 — usage/flag handling.
# =============================================================================================
echo; echo "### scenario: usage / flags"
bash "$SCRIPT" --help >/dev/null 2>&1; hrc=$?
assert_eq "$hrc" "0" "--help exits 0"
bash "$SCRIPT" --bogus-flag >/dev/null 2>&1; brc=$?
assert_eq "$brc" "2" "unknown flag exits 2"
bash "$SCRIPT" --root "$TMP/does-not-exist" >/dev/null 2>&1; nrc=$?
assert_eq "$nrc" "2" "non-existent --root exits 2"

# =============================================================================================
# SCENARIO 6 — ADVERSARIAL zone-path / symlink surface (data-safety review Fixes 1/2/3): no client
# file may ESCAPE <root>, and no bad user may ABORT the sweep. Users are named s1/s2/s3 (bad) and
# s9valid (alphabetically LAST, good) to prove the sweep reaches a later valid user + prints its
# summary. Externals live OUTSIDE <root> so any followed symlink is detectable as data-escape.
# =============================================================================================
echo; echo "### scenario: adversarial symlink/non-dir zone surface (no escape, no abort)"
AROOT="$TMP/arepo"
AEXT1="$TMP/aext_zones"    # target of a symlinked zones/
AEXT2="$TMP/aext_ws"       # target of a symlinked workspaces/
AEXT4="$TMP/aext_default"  # [R1] target of a symlinked zones/default (intermediate level 2)
AEXT5="$TMP/aext_zwsp"     # [R1] target of a symlinked zones/default/workspaces (intermediate level 3)
rm -rf "$AROOT" "$AEXT1" "$AEXT2" "$AEXT4" "$AEXT5"
mkdir -p "$AEXT1" "$AEXT2/ws1" "$AEXT4" "$AEXT5"
printf 'ext-zones-sentinel\n'   > "$AEXT1/sentinel.txt"
printf 'ext-ws-payload\n'       > "$AEXT2/ws1/payload.txt"
printf 'ext-default-sentinel\n' > "$AEXT4/sentinel.txt"
printf 'ext-zwsp-sentinel\n'    > "$AEXT5/sentinel.txt"
ext1_before="$(manifest "$AEXT1")"; ext2_before="$(manifest "$AEXT2")"
ext4_before="$(manifest "$AEXT4")"; ext5_before="$(manifest "$AEXT5")"

# (a) user with a real workspaces/ AND a SYMLINKED zones/ -> external dir (intermediate level 1)
mkdir -p "$AROOT/users/s1sym_zones/workspaces/wsa"
printf 'A\n' > "$AROOT/users/s1sym_zones/workspaces/wsa/file.txt"
ln -s "$AEXT1" "$AROOT/users/s1sym_zones/zones"
# (b) user with a SYMLINKED workspaces/ -> external dir
mkdir -p "$AROOT/users/s2sym_ws"
ln -s "$AEXT2" "$AROOT/users/s2sym_ws/workspaces"
# (c) user with a real workspaces/ AND a plain FILE named 'zones'
mkdir -p "$AROOT/users/s3file_zones/workspaces/wsc"
printf 'C\n' > "$AROOT/users/s3file_zones/workspaces/wsc/file.txt"
printf 'i-am-a-file\n' > "$AROOT/users/s3file_zones/zones"
# (f) [R1] user with a real workspaces/ AND a SYMLINKED zones/default -> external (intermediate lvl 2)
mkdir -p "$AROOT/users/s4sym_default/workspaces/wsf" "$AROOT/users/s4sym_default/zones"
printf 'F\n' > "$AROOT/users/s4sym_default/workspaces/wsf/file.txt"
ln -s "$AEXT4" "$AROOT/users/s4sym_default/zones/default"
# (g) [R1] user with a real workspaces/ AND a SYMLINKED zones/default/workspaces -> external (lvl 3)
mkdir -p "$AROOT/users/s5sym_zwsp/workspaces/wsg" "$AROOT/users/s5sym_zwsp/zones/default"
printf 'G\n' > "$AROOT/users/s5sym_zwsp/workspaces/wsg/file.txt"
ln -s "$AEXT5" "$AROOT/users/s5sym_zwsp/zones/default/workspaces"
# (d) a normal valid user that MUST still migrate (sorts last)
mkdir -p "$AROOT/users/s9valid/workspaces/wsd"
printf 'D\n' > "$AROOT/users/s9valid/workspaces/wsd/file.txt"

aout="$(bash "$SCRIPT" --root "$AROOT" 2>&1)"; arc=$?

# --- sweep COMPLETED, printed its summary, and did NOT abort (exit 0 — all bad users are skips) --
assert_eq "$arc" "0" "adversarial: sweep exits 0 (bad users skipped, none abort the run)"
assert_has "$aout" "migrate-to-zones-layout summary" "adversarial: coverage summary still printed"
assert_re  "$aout" "users scanned: +6"  "adversarial: all 6 users scanned"
assert_re  "$aout" "users migrated: +1" "adversarial: exactly the 1 valid user migrated"
assert_re  "$aout" "users skipped: +5"  "adversarial: the 5 bad users skipped (not aborted)"

# --- (a) symlinked zones/: NOT followed; nothing escaped into the external dir; ws data in place --
assert_has "$aout" "'$AROOT/users/s1sym_zones/zones' is a symlink or non-directory" "a: symlinked zones/ skipped-with-warning"
assert_symlink "$AROOT/users/s1sym_zones/zones" "a: symlinked zones/ still a symlink"
assert_file "$AROOT/users/s1sym_zones/workspaces/wsa/file.txt" "a: NO ESCAPE — wsa still under <root> (not moved through the symlink)"
assert_eq "$(manifest "$AEXT1")" "$ext1_before" "a: NO ESCAPE — external zones-target tree byte-for-byte unchanged"
assert_absent "$AEXT1/default" "a: NO ESCAPE — no zone join created inside the external target"

# --- (b) symlinked workspaces/: NOT followed; external tree untouched --------------------------
assert_has "$aout" "'$AROOT/users/s2sym_ws/workspaces' is a symlink" "b: symlinked workspaces/ skipped-with-warning"
assert_symlink "$AROOT/users/s2sym_ws/workspaces" "b: symlinked workspaces/ still a symlink"
assert_file "$AEXT2/ws1/payload.txt" "b: NO ESCAPE — external workspaces-target payload untouched"
assert_eq "$(manifest "$AEXT2")" "$ext2_before" "b: NO ESCAPE — external workspaces-target tree unchanged"
assert_absent "$AROOT/users/s2sym_ws/zones" "b: no zones/ join created for the symlinked-workspaces user"

# --- (c) plain FILE named 'zones': skipped; ws data left in place under <root> ------------------
assert_has "$aout" "'$AROOT/users/s3file_zones/zones' is a symlink or non-directory" "c: plain-file zones skipped-with-warning"
assert_file "$AROOT/users/s3file_zones/zones" "c: the 'zones' file left intact"
assert_file "$AROOT/users/s3file_zones/workspaces/wsc/file.txt" "c: NO ESCAPE — wsc still under <root> (not moved)"

# --- (f) [R1] symlinked zones/default (INTERMEDIATE level 2): caught by physical-containment ------
assert_has "$aout" "[s4sym_default] WARNING: skipping — zone target" "f: symlinked zones/default skipped-with-warning"
assert_has "$aout" "escapes <root> via a symlinked intermediate" "f: warning names the intermediate-symlink escape"
assert_eq "$(manifest "$AEXT4")" "$ext4_before" "f: NO ESCAPE — external zones/default-target tree byte-for-byte unchanged"
assert_absent "$AEXT4/workspaces" "f: NO ESCAPE — mkdir -p did NOT create workspaces/ inside the external target"
assert_file "$AROOT/users/s4sym_default/workspaces/wsf/file.txt" "f: NO COPY LEFT <root> — real wsf copy still UNDER <root> (not moved out)"
assert_symlink "$AROOT/users/s4sym_default/zones/default" "f: symlinked zones/default still a symlink"

# --- (g) [R1] symlinked zones/default/workspaces (INTERMEDIATE level 3): also caught ---------------
assert_has "$aout" "[s5sym_zwsp] WARNING: skipping — zone target" "g: symlinked zones/default/workspaces skipped-with-warning"
assert_eq "$(manifest "$AEXT5")" "$ext5_before" "g: NO ESCAPE — external zones/default/workspaces-target tree byte-for-byte unchanged"
assert_file "$AROOT/users/s5sym_zwsp/workspaces/wsg/file.txt" "g: NO COPY LEFT <root> — real wsg copy still UNDER <root> (not moved out)"
assert_symlink "$AROOT/users/s5sym_zwsp/zones/default/workspaces" "g: symlinked zones/default/workspaces still a symlink"

# --- (d) the LATER valid user STILL migrated (proves the sweep never halted) --------------------
assert_file "$AROOT/users/s9valid/zones/default/workspaces/wsd/file.txt" "d: later valid user migrated (sweep continued past all bad users)"
assert_absent "$AROOT/users/s9valid/workspaces" "d: valid user's emptied workspaces/ rmdir'd"
# every users/<u>/ still exists (never-delete invariant across bad + good users):
for u in s1sym_zones s2sym_ws s3file_zones s4sym_default s5sym_zwsp s9valid; do
  assert_dir "$AROOT/users/$u" "adversarial: never-delete — users/$u still exists"
done

# --- (e) --force with a SYMLINKED $dst leaf: refuse, never merge through it --------------------
echo; echo "### scenario: --force refuses a symlinked target leaf (\$dst)"
SROOT="$TMP/srepo"; SEXT="$TMP/sext"
rm -rf "$SROOT" "$SEXT"
mkdir -p "$SEXT"; printf 'sext-sentinel\n' > "$SEXT/sentinel.txt"
sext_before="$(manifest "$SEXT")"
mkdir -p "$SROOT/users/fsym/workspaces/blog"
printf 'src\n' > "$SROOT/users/fsym/workspaces/blog/f.txt"
mkdir -p "$SROOT/users/fsym/zones/default/workspaces"     # real zone dirs...
ln -s "$SEXT" "$SROOT/users/fsym/zones/default/workspaces/blog"   # ...but the LEAF is a symlink
sout="$(bash "$SCRIPT" --root "$SROOT" --force 2>&1)"; src2=$?
assert_eq "$src2" "1" "e: --force with a symlinked \$dst leaf exits 1 (refusal)"
assert_has "$sout" "is a symlink (never moved through)" "e: symlinked \$dst leaf refused-with-warning"
assert_symlink "$SROOT/users/fsym/zones/default/workspaces/blog" "e: symlinked \$dst leaf still a symlink"
assert_file "$SROOT/users/fsym/workspaces/blog/f.txt" "e: NO ESCAPE — source ws left in place (not merged through the symlink)"
assert_eq "$(manifest "$SEXT")" "$sext_before" "e: NO ESCAPE — external symlink-target tree unchanged"

# =============================================================================================
echo
echo "================= RESULT ================="
echo "PASS=$PASS FAIL=$FAIL"
echo "========================================="
[ "$FAIL" -eq 0 ]
