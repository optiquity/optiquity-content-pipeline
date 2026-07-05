#!/usr/bin/env bash
# update-from-upstream.sh
# Pull framework updates from the public repo into this private instance, non-destructively.
# Safe because framework and instance content never share a file (see docs/operating-model.md).
set -euo pipefail

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

echo ">> Done. Review the merge, run your smoke tests, then push to your private origin."
