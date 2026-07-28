#!/usr/bin/env bash
# check-no-content.sh — the Q15 public-boundary guard (plan step 13; PA-1 scope spec).
#
# Fails when client/instance content has leaked into the PUBLIC framework repo
# (CLAUDE.md rule 4; design docs/design.md §10). Runs in CI on the public repo only
# (§10 rule 5 — instance-side repos are not gated by it; see .github/workflows/guard.yml).
#
# RATIFIED MODEL (§10, the §27.4 deferred guard change): shared registry directories are
# MIXED-PROVENANCE — `provenance: framework` default entries are the public deliverable
# and are WELCOME; what must never ship is instance/client content. The guard therefore
# default-denies by provenance instead of rejecting every populated entry.
#
# SCAN SCOPE (PA-1): tracked files only in the default mode (`git ls-files`, so local
# uncommitted instance/demo data never false-positives), restricted to the named registry
# roots plus instance/ and workspaces/. NEVER scans tests/ docs/ pipeline/ scripts/
# .claude/ .github/ — tracked negative fixtures under tests/fixtures/guard/ cannot
# self-flag (PA-1b). `--mode all` walks the same scope dirs on disk, including symlinks
# (step-13 review RV-4 — a symlinked file is scanned like any other; tracked mode already
# behaves so because `git ls-files` lists symlinks and grep follows them).
#
# TEMPLATE EXEMPTION BY NAME, SCOPED PER CLASS (PA-1a; tightened by step-13 review RV-1):
# `*.template.*` basenames are exempt ONLY in a registry root (from the missing-provenance
# default-deny — but not from the x-file path class, and an explicit
# `provenance: instance` line still leaks even under a template name, RV-2) and as DIRECT
# children of instance/ (the shipped allowlist: instance/profile.template.md,
# instance/defaults.template.yaml). The exemption NEVER applies under instance/ops/,
# nested instance/ paths, or workspaces/ — a template-named file there is still
# client/instance content, and its path alone can leak a client name. The
# workspaces/workspace.template/ directory is exempt wholesale (it is the framework
# deliverable; templates carry no provenance frontmatter, and the stale
# platforms/platform.template.md stays green until the step-40 sweep). A co-located
# `<root>/_schema.yaml` is framework mechanism (SV4) and is likewise exempt.
#
# LEAK CLASSES (each named in the output; negative fixtures per class under
# tests/fixtures/guard/):
#   missing-provenance    registry file without an unambiguous `provenance: framework`
#                         line (default-deny, §10 Q15 rule 4)
#   provenance-instance   registry file tagged `provenance: instance` — template-named
#                         files included (RV-2)
#   x-file                `x-*` path in a registry root (§11.4 SV5 — the framework never
#                         ships the reserved instance namespace; by PATH, so `x-*` dirs
#                         and template-named files inside them are caught too, RV-1)
#   instance-defaults     tracked instance/defaults.yaml (the T10 global scope-default
#                         surface — PA-1c; only instance/defaults.template.yaml ships)
#   instance-ops          tracked file under instance/ops/ (instance ops state, §23;
#                         template-named files included, RV-1)
#   instance-file         any other tracked file under instance/ (allowlist: DIRECT-child
#                         *.template.* only, e.g. instance/profile.template.md; nested
#                         paths leak regardless of name, RV-1)
#   workspace-content     tracked path under workspaces/ outside workspace.template/
#                         (client isolation, CLAUDE.md rule 2/4; no template exemption —
#                         the path alone names a client, RV-1)
#   framework-asset       tracked file under the top-level framework asset home assets/
#                         other than README.md (S3; the emptiness arm below — assets/ is
#                         outside $SCOPES, so a stray binary would ship UNFLAGGED)
#
# TEST INTERFACE (REC-3): --root DIR (default: the repo root) and --mode tracked|all
# (default: tracked). tests/test_guard.py exercises copied fixture trees with
# `--root <tmpdir> --mode all`, so no nested git repo is needed and CI stays green with
# the fixtures tracked. Exit: 0 clean · 1 leak(s) found · 2 usage.
#
# Schema/provenance PARSING is not this script's job: `scripts/schema-lint.sh`
# (python -m pipeline.lint) runs the full Q15 default-deny + schema validation (§11.7);
# this guard is the grep-level tracked-file boundary scan that pairs with it.
set -euo pipefail

# REGISTRY_ROOTS is the hardcoded whitelist of registry roots the content scan covers. It is
# self-enforcing: the GAP-4a coverage check below fails the guard if any top-level dir has
# registry SHAPE (the SV4 `<dir>/_schema.yaml` marker) but is missing from this list — so a
# new registry root (e.g. a future `lexicons/`) can never ship UNSCANNED. Add a new root here.
REGISTRY_ROOTS="topics personas formats voices goals platforms languages output-types presentations content-kinds sources render-targets recipes folio-types lexicons diagram-styles"
SCOPES="$REGISTRY_ROOTS instance workspaces"

MODE="tracked"
ROOT=""

usage() {
  cat <<'EOF'
usage: check-no-content.sh [--root DIR] [--mode tracked|all]

Public-boundary guard (design §10; PA-1 scope). Scans the registry roots + instance/ +
workspaces/ for client/instance content. Default: tracked files of the repo checkout.
  --root DIR   tree to scan (default: the repo root containing this script)
  --mode M     tracked = git ls-files (default; requires a git checkout)
               all     = every file on disk (the REC-3 test seam for fixture trees)
Exit: 0 clean · 1 leak(s) · 2 usage.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --root)
      [ "$#" -ge 2 ] || { echo "check-no-content.sh: --root requires a value" >&2; exit 2; }
      ROOT="$2"; shift 2 ;;
    --mode)
      [ "$#" -ge 2 ] || { echo "check-no-content.sh: --mode requires a value" >&2; exit 2; }
      MODE="$2"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "check-no-content.sh: unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$MODE" in
  tracked|all) : ;;
  *) echo "check-no-content.sh: --mode must be 'tracked' or 'all', got '$MODE'" >&2; exit 2 ;;
esac

if [ -z "$ROOT" ]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
cd "$ROOT" || { echo "check-no-content.sh: cannot cd to --root '$ROOT'" >&2; exit 2; }

if [ "$MODE" = "tracked" ]; then
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "check-no-content.sh: --mode tracked requires a git checkout at '$ROOT'" \
         "(use --mode all for plain directory trees)" >&2
    exit 2
  fi
fi

list_files() {
  if [ "$MODE" = "tracked" ]; then
    # shellcheck disable=SC2086  # intentional word-split: one pathspec per scope dir
    git ls-files -- $SCOPES
  else
    for d in $SCOPES; do
      if [ -d "$d" ]; then
        # Symlinks included (RV-4): --mode all must never silently skip a path that
        # tracked mode would scan.
        find "$d" \( -type f -o -type l \)
      fi
    done
  fi
}

# GAP-4a (docs/known-issues.md): every TOP-LEVEL directory that carries the SV4
# registry-root marker (a co-located `<dir>/_schema.yaml`). The caller uses this to catch
# an UNKNOWN registry root — one outside the REGISTRY_ROOTS whitelist, hence outside $SCOPES
# and NEVER scanned by list_files above. Emits candidate `<dir>/_schema.yaml` paths (git
# `*` spans '/', so nested markers appear too; the caller filters to depth-1). Honors --mode
# exactly like list_files — tracked = committed markers only (a local uncommitted scratch
# dir never false-positives), all = markers on disk.
list_schema_roots() {
  if [ "$MODE" = "tracked" ]; then
    git ls-files -- '*/_schema.yaml'
  else
    for s in */_schema.yaml; do
      if [ -f "$s" ]; then
        printf '%s\n' "$s"
      fi
    done
  fi
}

fail=0
leak() { # $1=class  $2=path  $3=message
  echo "LEAK[$1] $2: $3"
  fail=1
}

# GAP-4a — REGISTRY-ROOT COVERAGE CHECK (docs/known-issues.md GAP-4): the file scan below
# only covers $SCOPES (the hardcoded REGISTRY_ROOTS whitelist + instance/ + workspaces/). A
# brand-new top-level registry root OUTSIDE that whitelist would therefore pass UNSCANNED —
# a silent client-content leak surface (e.g. a future `lexicons/` holding a corporate
# lexicon). Fail LOUDLY on any top-level directory that has REGISTRY SHAPE (the SV4 marker: a
# co-located `<dir>/_schema.yaml`) yet is not already a scanned scope, so no new registry
# root can ship without a CONSCIOUS decision to whitelist (and thus scan) it here. This is an
# ADDITIVE structural check — it never alters the content scan of the existing roots.
while IFS= read -r schema; do
  [ -n "$schema" ] || continue
  case "$schema" in
    */*/*) continue ;;            # deeper than <dir>/_schema.yaml — not a top-level root marker
    */_schema.yaml) : ;;
    *) continue ;;
  esac
  root_dir="${schema%/_schema.yaml}"
  case " $SCOPES " in
    *" $root_dir "*) continue ;;  # already scanned (a whitelisted root, or instance/workspaces)
  esac
  leak unknown-registry-root "$root_dir" \
    "registry-shaped directory (SV4 marker: a co-located ${root_dir}/_schema.yaml) is NOT in REGISTRY_ROOTS, so its contents are NEVER scanned by this guard — add '${root_dir}' to REGISTRY_ROOTS in scripts/check-no-content.sh so the public-boundary scan covers it (GAP-4a)"
done < <(list_schema_roots)

# S3 — FRAMEWORK ASSET-HOME EMPTINESS ARM (mixed-media increment A1). The top-level `assets/`
# directory is the framework example-image / content-asset home (assets/README.md documents the
# `provenance: framework` convention). It is DELIBERATELY OUTSIDE $SCOPES: binaries carry no
# `provenance:` frontmatter to default-deny on, and the GAP-4a coverage check keys on a co-located
# `_schema.yaml` an image home will never have — so a stray client image dropped here would ship in
# the PUBLIC repo UNFLAGGED (a client-isolation hole, CLAUDE.md rules 2/4). Until a filename/path
# client-name scan ships, this home admits ONLY its README; this arm makes that emptiness a real,
# tested MECHANISM rather than hope. Honors --mode exactly like list_files (tracked = git ls-files,
# all = every file/symlink on disk). Additive — it never alters the existing scope scan above.
list_asset_home() {
  if [ "$MODE" = "tracked" ]; then
    git ls-files -- assets
  else
    if [ -d assets ]; then
      find assets \( -type f -o -type l \)
    fi
  fi
}

while IFS= read -r f; do
  [ -n "$f" ] || continue
  # The convention doc is the only permitted resident of the framework asset home.
  case "$f" in
    assets/README.md) continue ;;
  esac
  leak framework-asset "$f" \
    "tracked file under the framework asset home assets/ other than README.md — admits only the convention doc until a client-name path scan ships; a binary here would ship in the public repo UNFLAGGED (CLAUDE.md rules 2/4)"
done < <(list_asset_home)

while IFS= read -r f; do
  [ -n "$f" ] || continue

  # PA-1a directory exemption: the shipped workspace template.
  case "$f" in
    workspaces/workspace.template/*) continue ;;
  esac

  # NOTE (RV-1): the *.template.* basename exemption is scoped PER CLASS below — the
  # registry-root arm and DIRECT children of instance/ only, never under instance/ops/,
  # nested instance/ paths, or workspaces/.
  base="${f##*/}"

  case "$f" in
    instance/ops/*)
      leak instance-ops "$f" \
        "tracked instance ops state — instance/ops/ is gitignored-in-public instance data (design §23; CLAUDE.md rule 4)" ;;
    instance/defaults.yaml)
      leak instance-defaults "$f" \
        "tracked instance/defaults.yaml — the T10 global scope-default surface is instance data (PA-1c); only instance/defaults.template.yaml ships" ;;
    instance/*/*)
      # Nested under instance/: never template-exempt (RV-1).
      leak instance-file "$f" \
        "tracked nested file under instance/ (allowlist: direct-child *.template.* only, e.g. instance/profile.template.md, instance/defaults.template.yaml)" ;;
    instance/*)
      # Direct child of instance/: the ONLY place the instance-side template
      # allowlist applies (RV-1).
      case "$base" in
        *.template.*) continue ;;
      esac
      leak instance-file "$f" \
        "tracked non-template file under instance/ (allowlist: direct-child *.template.* only, e.g. instance/profile.template.md, instance/defaults.template.yaml)" ;;
    workspaces/*)
      # No template exemption under workspaces/ (RV-1): the path alone names a client.
      leak workspace-content "$f" \
        "tracked client-workspace content — only workspaces/workspace.template/ ships in the public framework (CLAUDE.md rules 2/4)" ;;
    *)
      # A registry-root file. The co-located schema manifest is framework mechanism.
      top="${f%%/*}"
      if [ "$f" = "$top/_schema.yaml" ]; then
        continue
      fi
      case "/$f" in
        */x-*)
          # SV5 before the template exemption (RV-1): an x-* path segment leaks by
          # PATH, template-named or not.
          leak x-file "$f" \
            "instance-namespaced 'x-*' path in a registry root — the framework never ships the reserved x- namespace (design §11.4 SV5)"
          continue ;;
      esac
      case "$base" in
        *.template.*)
          # PA-1a's home: template-named files are exempt from the missing-provenance
          # default-deny — but an EXPLICIT instance tag never belongs in a template
          # (RV-2; shipped templates carry no provenance frontmatter at all).
          if grep -q -E '^provenance:[[:space:]]*instance[[:space:]]*$' "$f" 2>/dev/null; then
            leak provenance-instance "$f" \
              "template-named registry file carrying an explicit 'provenance: instance' line — instance entries never ship in the public repo (design §10 Q15 rule 5; templates carry no provenance frontmatter)"
          fi
          continue ;;
      esac
      if grep -q -E '^provenance:[[:space:]]*instance[[:space:]]*$' "$f" 2>/dev/null; then
        leak provenance-instance "$f" \
          "registry file tagged 'provenance: instance' — instance entries never ship in the public repo (design §10 Q15 rule 5)"
      elif ! grep -q -E '^provenance:[[:space:]]*framework[[:space:]]*$' "$f" 2>/dev/null; then
        leak missing-provenance "$f" \
          "registry file without an unambiguous 'provenance: framework' tag — the guard default-denies (design §10 Q15 rule 4)"
      fi ;;
  esac
done < <(list_files)

if [ "$fail" -ne 0 ]; then
  echo "Public framework repo must stay empty of client/instance content (CLAUDE.md rule 4; design §10; docs/operating-model.md)."
  exit 1
fi
echo "OK: no client/instance content in framework scan scope (mode: $MODE, root: $ROOT)."
