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
# uncommitted instance/demo data never false-positives), restricted to the named FLAT registry
# roots PLUS `foundation/` (the reorg grouping — a dual-safe union for the B-2→B-3 window: it is
# inert on today's still-flat repo where no `foundation/` dir exists, and scans the moved registries
# once B-3 lands), plus instance/, users/ (the §23 re-home — all client content lives under
# users/<user>/workspaces/<workspace>/), and templates/ (framework blueprints). NEVER scans
# tests/ docs/ pipeline/ scripts/
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
# nested instance/ paths, or users/ — a template-named file there is still
# client/instance content, and its path alone can leak a user/client name. The framework
# workspace blueprint at templates/workspace/ is NOT exempt: its whole subtree is scanned
# by the [W8] templates/* arm (its 8 generic framework files carry no x-/provenance-instance
# instance signal, so they PASS; the stale platforms/platform.template.md stays green until
# the step-40 sweep). A co-located `_schema.yaml` is framework mechanism (SV4) and is likewise exempt
# BY BASENAME at ANY depth — so a flat `<root>/_schema.yaml` and a `foundation/**/_schema.yaml` are
# both exempt from the missing-provenance default-deny.
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
#   workspace-content     tracked client content under users/ (any depth beneath
#                         users/<user>/workspaces/<workspace>/) — client isolation,
#                         CLAUDE.md rule 2/4; no template exemption, the path alone names
#                         a user/client (RV-1; §23 re-home)
#   x-file / provenance-instance (under templates/)  the [W8] templates/ scan arm: an x-*
#                         path or an explicit `provenance: instance` line ANYWHERE under
#                         templates/ (including templates/workspace/**) leaks; templates/ is
#                         framework mechanism — owner-agnostic blueprints, so generic
#                         framework files (no instance signal) PASS. A marker-less generic
#                         file is an accepted residual (cf. the GAP-4a marker-less-dir limit)
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

# REGISTRY_ROOTS is the hardcoded whitelist of FLAT (today's live layout) registry roots the content
# scan covers. It is self-enforcing: the GAP-4a coverage check below fails the guard if any top-level
# dir has registry SHAPE (the SV4 `<dir>/_schema.yaml` marker) but is missing from this list — so a
# new registry root (e.g. a future `lexicons/`) can never ship UNSCANNED. Add a new root here. It is
# the bash mirror of `pipeline.lint.REGISTRY_ROOTS`; the parity test (tests/test_layout_guard_parity.py)
# fails on any drift between the two, so an 18th registry can never desync bash↔Python.
REGISTRY_ROOTS="topics personas formats voices goals platforms languages output-types presentations content-kinds sources render-targets recipes folio-types lexicons diagram-styles selections"
# FOUNDATION_REGISTRY_DIRS is the whitelist of full `foundation/`-anchored registry directories — the
# homes the framework registries move to under the `foundation/` reorg (the bash mirror of the values
# of `pipeline.layout.REGISTRY_BASE`, the Python SSOT the B-3 flip fills). It is the foundation-arm
# counterpart to REGISTRY_ROOTS: the GAP-4a check below leaks `unknown-registry-root` on any
# `foundation/**/_schema.yaml` whose registry dir is NOT in this list (an unlisted foundation registry
# shipping unvetted). DUAL-SAFE for the B-2→B-3 window: today's live repo has no `foundation/` dir, so
# this arm no-ops (nothing to match); it fires only once the registries are `foundation/`-shaped (B-3,
# or a foundation-shaped `--root` fixture/tree). The AUTHORITATIVE binning (reconciled design of
# record, Option-3): the nine §3/§4 dimension axes home under `foundation/dimensions/<axis>`; the
# grounding registries under `foundation/grounding/` (sources, content-kinds); the composition
# registries under `foundation/composition/` (recipes, selections, folio-types); the render-config
# registries under `foundation/render-config/` (render-targets, diagram-styles); and `lexicons` sits
# flat at `foundation/lexicons` (the sole depth-2 singleton). These are the exact values B-3 assigns
# into `pipeline.layout.REGISTRY_BASE` VERBATIM — the parity test (tests/test_layout_guard_parity.py)
# locks this list to that SSOT (value-parity engages the moment REGISTRY_BASE is populated at B-3).
FOUNDATION_REGISTRY_DIRS="foundation/dimensions/topics foundation/dimensions/personas foundation/dimensions/formats foundation/dimensions/voices foundation/dimensions/goals foundation/dimensions/platforms foundation/dimensions/languages foundation/dimensions/output-types foundation/dimensions/presentations foundation/grounding/sources foundation/grounding/content-kinds foundation/composition/recipes foundation/composition/selections foundation/composition/folio-types foundation/render-config/render-targets foundation/render-config/diagram-styles foundation/lexicons"
# SCOPES feeds `git ls-files -- $SCOPES` (and the --mode all find loop). For the B-2 dual-safe window it
# is a UNION: the flat REGISTRY_ROOTS (today's live layout) PLUS `foundation` (the reorg grouping — a
# single pathspec that recurses the whole foundation subtree once the registries move) PLUS the
# non-registry scan surfaces: instance/ (per-deployment config), users/ (the §23 re-home — ALL client
# content lives under users/<user>/workspaces/<workspace>/) and templates/ (framework-owned,
# owner-agnostic blueprints — the [W8] framework mechanism scan surface; a client file must not hide
# under templates/ unscanned). On the still-flat repo the `foundation` pathspec/dir simply matches
# nothing (no error); B-4 later tightens the union to `foundation instance users templates` once the
# move has landed.
SCOPES="$REGISTRY_ROOTS foundation instance users templates"

MODE="tracked"
ROOT=""

usage() {
  cat <<'EOF'
usage: check-no-content.sh [--root DIR] [--mode tracked|all]

Public-boundary guard (design §10; PA-1 scope). Scans the registry roots + instance/ +
users/ + templates/ for client/instance content. Default: tracked files of the repo checkout.
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

# GAP-4a (docs/known-issues.md): every directory that carries the SV4 registry-root marker (a
# co-located `<dir>/_schema.yaml`), at ANY depth. The caller uses this to catch an UNKNOWN registry
# root — a flat top-level one outside the REGISTRY_ROOTS whitelist, OR a `foundation/`-shaped one
# outside FOUNDATION_REGISTRY_DIRS — hence outside the vetted scan and NEVER consciously whitelisted.
# Emits candidate `**/_schema.yaml` paths (git `*` spans '/', so nested markers appear too; the caller
# filters by the `foundation/`-anchored `case` below). Honors --mode exactly like list_files — tracked
# = committed markers only (a local uncommitted scratch dir never false-positives), all = markers on
# disk. NOTE: --mode all uses `find .` (recursive), so it MUST emit depth ≥2 markers too — the old
# `*/_schema.yaml` glob only saw depth-1 and would MISS every `foundation/**/_schema.yaml`; the caller
# strips a leading `./` before matching so the `foundation/`-anchored patterns line up.
list_schema_roots() {
  if [ "$MODE" = "tracked" ]; then
    git ls-files -- '*/_schema.yaml'
  else
    find . -name _schema.yaml -type f
  fi
}

fail=0
leak() { # $1=class  $2=path  $3=message
  echo "LEAK[$1] $2: $3"
  fail=1
}

# GAP-4a — REGISTRY-ROOT COVERAGE CHECK (docs/known-issues.md GAP-4): the file scan below only covers
# $SCOPES (REGISTRY_ROOTS + `foundation` + instance/ + users/ + templates/). A registry root OUTSIDE
# the vetted whitelists would pass UNSCANNED / unvetted — a silent client-content leak surface (e.g. a
# future `lexicons/` holding a corporate lexicon, or an unlisted `foundation/**` registry). Fail LOUDLY
# on any directory that has REGISTRY SHAPE (the SV4 marker: a co-located `<dir>/_schema.yaml`) yet is
# not a consciously-whitelisted registry, so no new registry root can ship without a deliberate
# whitelist edit. This is an ADDITIVE structural check — it never alters the content scan of the
# existing roots.
#
# The `case` is FIRST-MATCH and anchored to the LITERAL `foundation/` prefix (no leading `*/`), so a
# marker whose path merely CONTAINS "foundation" further down (e.g. a `.venv/**/foundation/_schema.yaml`
# or a `tests/fixtures/**/foundation/…` fixture) does NOT match the foundation arm — it falls through
# to the deep-skip. The leading `./` that `find .` prints in --mode all is stripped first so the
# anchored patterns line up (a top-level `./topics/_schema.yaml` would otherwise carry two slashes and
# be misread as deep).
while IFS= read -r schema; do
  [ -n "$schema" ] || continue
  schema="${schema#./}"                      # normalize the `find .` leading `./` (tracked mode has none)
  case "$schema" in
    foundation/*/_schema.yaml | foundation/*/*/_schema.yaml)
      # A `foundation/`-anchored registry marker (depth-2 singleton like `foundation/lexicons`, or the
      # binned depth-3 like `foundation/dimensions/topics`). Its registry dir must be a whitelisted
      # FOUNDATION_REGISTRY_DIRS home; anything else is an unlisted foundation registry shipping unvetted.
      reg_dir="${schema%/_schema.yaml}"
      case " $FOUNDATION_REGISTRY_DIRS " in
        *" $reg_dir "*) continue ;;          # a known, whitelisted foundation registry
      esac
      leak unknown-registry-root "$reg_dir" \
        "foundation registry-shaped directory (SV4 marker: a co-located ${reg_dir}/_schema.yaml) is NOT in FOUNDATION_REGISTRY_DIRS, so it ships unvetted — add '${reg_dir}' to FOUNDATION_REGISTRY_DIRS in scripts/check-no-content.sh (and its token to pipeline.layout.REGISTRY_BASE) so the public-boundary scan vets it (GAP-4a)" ;;
    */*/*) continue ;;                       # a deep NON-foundation marker (tests/fixtures/**, .venv/**) — ignored
    */_schema.yaml)
      # A depth-1 top-level flat registry root (PRESERVED original protection): `<dir>/_schema.yaml`.
      root_dir="${schema%/_schema.yaml}"
      case " $SCOPES " in
        *" $root_dir "*) continue ;;         # already scanned (a whitelisted flat root, or foundation/instance/users/templates)
      esac
      leak unknown-registry-root "$root_dir" \
        "registry-shaped directory (SV4 marker: a co-located ${root_dir}/_schema.yaml) is NOT in REGISTRY_ROOTS, so its contents are NEVER scanned by this guard — add '${root_dir}' to REGISTRY_ROOTS in scripts/check-no-content.sh so the public-boundary scan covers it (GAP-4a)" ;;
    *) continue ;;
  esac
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

  # NOTE: the framework workspace blueprint at templates/workspace/ is NOT exempt wholesale —
  # its whole subtree flows through the [W8] templates/* arm below (so templates/workspace/**/x-*
  # and a provenance: instance file under it still LEAK). The 8 real blueprint files pass that arm
  # because none is x--named or provenance: instance (they are generic framework files).
  #
  # NOTE (RV-1): the *.template.* basename exemption is scoped PER CLASS below — the
  # registry-root arm and DIRECT children of instance/ only, never under instance/ops/,
  # nested instance/ paths, or users/.
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
    users/*)
      # §23 re-home + zone restructure: ALL client content lives under
      # users/<user>/zones/<zone>/workspaces/<workspace>/, and the shell `case *` glob spans '/', so
      # this catches any tracked file at any depth beneath users/ (the deeper zone level is already
      # covered — no structural change needed). No template exemption (RV-1): the path alone names a
      # user/client. The framework blueprint no longer lives here — it moved to templates/workspace/.
      leak workspace-content "$f" \
        "tracked client content under users/ — every user/zone/workspace tree (users/<user>/zones/<zone>/workspaces/<workspace>/) is instance-owned and never ships in the public framework (CLAUDE.md rules 2/4; design §23)" ;;
    templates/*)
      # [W8] templates/ is FRAMEWORK MECHANISM: owner-agnostic blueprints, the counterpart to the
      # assets/ arm above. The WHOLE subtree flows through here (including templates/workspace/), so no
      # part is a blind spot. The arm catches the two INSTANCE SIGNALS: an x-* path segment (the
      # reserved instance namespace, SV5) or an explicit `provenance: instance` line LEAKS. A
      # generic-named file with NO provenance line PASSES — templates legitimately carry no provenance
      # frontmatter, so this arm CANNOT default-deny on its absence. That marker-less generic file is an
      # ACCEPTED RESIDUAL (same class as the GAP-4a marker-less-dir limit); templates/ is extensible, so
      # no allowlist/emptiness backstop is imposed.
      case "/$f" in
        */x-*)
          leak x-file "$f" \
            "instance-namespaced 'x-*' path under the framework template home templates/ — templates carry no reserved x- namespace; a client blueprint must never hide here (design §11.4 SV5; CLAUDE.md rules 2/4)"
          continue ;;
      esac
      if grep -q -E '^provenance:[[:space:]]*instance[[:space:]]*$' "$f" 2>/dev/null; then
        leak provenance-instance "$f" \
          "template file under templates/ carrying an explicit 'provenance: instance' line — templates are framework mechanism (owner-agnostic, provenance framework), never instance content (design §10 Q15 rule 5)"
      fi ;;
    *)
      # A registry-root file. SV5 FIRST (RV-1): an `x-*` path segment leaks by PATH, template-named or
      # not — and this MUST run BEFORE the schema-manifest exemption below. An `x-*` extension registry
      # is itself registry-shaped and carries a co-located `_schema.yaml` (e.g. `topics/x-acme/_schema.yaml`,
      # or at B-3 `foundation/dimensions/topics/x-acme/_schema.yaml`); a basename exemption running first
      # would silently let that reserved instance namespace ship. The framework never ships an `x-*`
      # path, so a legit framework manifest never has an `x-*` ancestor and stays exempt at the next step.
      case "/$f" in
        */x-*)
          leak x-file "$f" \
            "instance-namespaced 'x-*' path in a registry root — the framework never ships the reserved x- namespace (design §11.4 SV5)"
          continue ;;
      esac
      # NOW the co-located schema manifest exemption (framework mechanism, SV4) — by BASENAME and
      # depth-agnostic (safe here: any `x-*`-ancestor manifest already leaked above), so a genuine
      # framework `foundation/**/_schema.yaml` (depth ≥2) is exempt exactly like a flat
      # `<root>/_schema.yaml`. The old position-based check (`[ "$f" = "$top/_schema.yaml" ]`) only
      # matched depth-1 and would false-positive `missing-provenance` on every foundation manifest.
      case "$base" in
        _schema.yaml) continue ;;
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
