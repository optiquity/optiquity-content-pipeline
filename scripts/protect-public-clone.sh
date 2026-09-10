#!/usr/bin/env bash
# protect-public-clone.sh — apply the PUBLIC framework's client-content ignore to THIS clone only.
#
# WHY THIS IS NOT IN .gitignore
# `.gitignore` is a FRAMEWORK file that ships downstream (durable rule 5), so a pattern there is
# inherited by every PRIVATE instance — where the same client content must be TRACKED
# (docs/operating-model.md, "Your content is tracked"; quickstart.md §B). Carrying the ignore in a
# shipped file silently defeated that: §B produced an instance whose content was still untracked.
# Keeping it in .git/info/exclude makes it per-clone, so the public framework ignores client content,
# a private instance versions it, and NO TRACKED FILE DIFFERS between them — which is what keeps
# scripts/update-from-upstream.sh conflict-free.
#
# A `!users/...` negation in the instance cannot substitute: git does not descend into an excluded
# directory, so nothing inside it can be re-included.
#
# This is the LOCAL BELT. The braces are scripts/check-no-content.sh in CI, which fails on any
# tracked file under users/<user>/workspaces/<workspace>/ (LEAK[workspace-content]) and is the half
# that actually breaks a build. Run this once per public clone; it is idempotent.
#
#   bash scripts/protect-public-clone.sh [<repo-root>]
set -euo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel)}"
GIT_DIR="$(git -C "$ROOT" rev-parse --git-dir)"
case "$GIT_DIR" in
  /*) ;;                       # already absolute
  *) GIT_DIR="$ROOT/$GIT_DIR" ;;
esac

EXCLUDE="$GIT_DIR/info/exclude"
MARKER="# --- optiquity public-clone client-content ignore (scripts/protect-public-clone.sh) ---"

mkdir -p "$(dirname "$EXCLUDE")"
[ -f "$EXCLUDE" ] || : > "$EXCLUDE"

if grep -qF -- "$MARKER" "$EXCLUDE"; then
  echo "protect-public-clone: already applied — $EXCLUDE"
  exit 0
fi

cat >> "$EXCLUDE" <<'PATTERNS'

# --- optiquity public-clone client-content ignore (scripts/protect-public-clone.sh) ---
# Per-clone and untracked BY DESIGN: a private instance must version this content instead.
# `users/*/zones/` is the zoned layout; `users/*/workspaces/` covers a pre-migration clone.
users/*/workspaces/
users/*/zones/
PATTERNS

echo "protect-public-clone: applied — $EXCLUDE"
