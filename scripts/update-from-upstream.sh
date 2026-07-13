#!/usr/bin/env bash
# update-from-upstream.sh
# Pull framework updates from the public repo into this private instance, non-destructively.
# Safe because framework and instance content never share a file (see docs/operating-model.md).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_BRANCH="${UPSTREAM_BRANCH:-main}"

if ! git remote get-url "$UPSTREAM_REMOTE" >/dev/null 2>&1; then
  echo "No '$UPSTREAM_REMOTE' remote found. Add the public repo as upstream:"
  echo "  git remote add $UPSTREAM_REMOTE <PUBLIC_REPO_URL>"
  exit 1
fi

echo ">> Fetching $UPSTREAM_REMOTE/$UPSTREAM_BRANCH ..."
git fetch "$UPSTREAM_REMOTE" "$UPSTREAM_BRANCH"

echo ">> Incoming framework changes:"
git --no-pager diff --stat "HEAD..${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}" || true
echo

# Warn if the working tree is dirty (uncommitted local work).
if ! git diff-index --quiet HEAD --; then
  echo "!! Working tree has uncommitted changes. Commit or stash before updating."
  exit 1
fi

read -r -p ">> Merge these framework updates now? [y/N] " ans
case "$ans" in
  y|Y) : ;;
  *) echo "Aborted. Nothing changed."; exit 0 ;;
esac

git merge --no-ff "${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}" \
  -m "chore: merge framework updates from ${UPSTREAM_REMOTE}/${UPSTREAM_BRANCH}"

echo
echo ">> Running the update-time drift report (SV7/MIG-6, design §11.5) over the config tree ..."
# PA-9c: surface any schema drift the merge introduced. drift-report is READ-ONLY; exit 1 = blocking
# drift found (remediate with scripts/migrate.sh — never auto-run), 0 = clean, 2 = usage. It must NOT
# abort this script (set -e): the merge already landed, so the report is informational only.
drift_rc=0
"$SCRIPT_DIR/pipeline" drift-report --root "$SCRIPT_DIR/.." || drift_rc=$?
if [ "$drift_rc" -eq 1 ]; then
  echo "!! Blocking schema drift detected above — review it and run scripts/migrate.sh before generating."
elif [ "$drift_rc" -ne 0 ]; then
  echo "!! drift-report did not run cleanly (exit $drift_rc) — run 'scripts/pipeline drift-report' manually."
fi

echo ">> Done. Review the merge + drift report, run your smoke tests, then push to your private origin."
