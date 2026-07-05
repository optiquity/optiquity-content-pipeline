#!/usr/bin/env bash
# check-no-content.sh
# Fails if client/instance content has leaked into the PUBLIC framework repo.
# Run in CI on the public repo (see .github/workflows/guard.yml). The private instance does not
# run this, so it can track its own content freely.
#
# Convention: templates are named *.template.md (or the workspace.template/ directory). Anything
# else in a registry or under workspaces/ is populated instance content and must not be public.
set -euo pipefail

fail=0

# 1) No populated registry entries (only *.template.md allowed).
for dir in personas platforms formats topics; do
  [ -d "$dir" ] || continue
  while IFS= read -r f; do
    case "$(basename "$f")" in
      *.template.md) : ;;
      *) echo "LEAK: populated registry file in public repo: $f"; fail=1 ;;
    esac
  done < <(find "$dir" -maxdepth 1 -name '*.md')
done

# 2) No real workspaces (only workspace.template/ allowed).
if [ -d workspaces ]; then
  while IFS= read -r d; do
    [ "$(basename "$d")" = "workspace.template" ] || { echo "LEAK: workspace in public repo: $d"; fail=1; }
  done < <(find workspaces -mindepth 1 -maxdepth 1 -type d)
fi

# 3) No populated instance profile (only profile.template.md allowed).
if [ -f instance/profile.md ]; then
  echo "LEAK: instance/profile.md present in public repo (only profile.template.md allowed)"; fail=1
fi

if [ "$fail" -ne 0 ]; then
  echo "Public framework repo must stay empty of client/instance content. See docs/operating-model.md."
  exit 1
fi
echo "OK: no client/instance content in framework repo."
