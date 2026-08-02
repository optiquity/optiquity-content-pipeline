"""SV11 schema-lint (design §11.7) — the public repo's schema/registry CI gate.

Entry point: `scripts/schema-lint.sh` → `python -m pipeline.lint` (plan step 13; T8 thin
entrypoint). WIRES the existing pipeline modules — `schema.load_schema` (manifest
validation), `entries.load_entry` (the §11.1 B4 entry-identity match, §7.4 slug alphabet,
§10 Q15 default-deny provenance + closed-schema validation, §11.4 SV5 namespacing, §11.2
stamp shape), `drift.meaning_changed_attributes` (the lockstep math) and
`migration.load_step_registry` (MIG-1 registry discipline) — it never re-implements them.

The SV11 clauses (design §11.7), with this module's finding codes:

  1. **Schema change without a `schema_version` bump** — detected against a BASELINE (the
     previous RELEASE: `--baseline DIR`, or by default the commit named by the committed
     release marker `pipeline/released_baseline` when `--root` is a git checkout's toplevel
     — and NONE pre-release, when the marker is absent, so the diff clauses are inert) →
     `schema-change-without-version-bump`; a version moving BACKWARDS is
     `schema-version-regression`. The baseline is RELEASE-relative, not per-commit: a
     version in development makes many schema changes before its release, and only the
     FIRST change AFTER a release must bump the global version (see `_released_ref`).
  2. **Meaning change without a shipped map-or-prompt** (MIG-4) — a baseline→current
     `definition_version` bump or attribute removal with no covering migration step at
     the trigger version → `meaning-change-without-migration-step`; an incompatible type
     change WITHOUT a `definition_version` bump → `undeclared-meaning-change`; a
     `definition_version` moving backwards → `definition-version-regression`.
  3. **Lockstep violation** — a framework-provenance entry stamped older than current for
     a redefined attribute it sets → `lockstep-violation`. (An entry stamped AHEAD of its
     schema is `stamp-ahead-of-schema` — a mixed checkout, §11.2.)
  4. **Window sanity** — a step present in the baseline registry but pruned while still
     inside the 1-year window (MIG-2) → `premature-prune`; plus the step-12 RV-3
     carry-forward: `released:` dates must not be future-dated
     (`future-dated-migration-release`) and must be monotonic non-decreasing in registry
     order (`non-monotonic-migration-releases`). A mutated step violates append-only
     (MIG-1) → `migration-step-mutated`; a step targeting a version ahead of the current
     global schema version → `migration-step-ahead-of-schema`.

  Additionally (§27.4 registered build item — absorbed by schema-lint): the
  deterministic-map **totality** rule (`migration-map-not-total` — a `map` step at the
  current release must cover the baseline enum/bool domain) and **composition** rules
  (`migration-step-composition` — current-release step outputs must compose with the
  current schema: map values type-valid, `rename_to` declared, `drop` targets actually
  removed, `edit.set` keys declared). Totality over infinite domains (number/text) is not
  finitely checkable here — the fold-time `TotalityError` (pipeline/migration.py) is the
  loud backstop.

  Carry-forward (step-11 review RV-3, binding on this step): CROSS-COLLECTION EQUALITY of
  the per-file `schema_version:` values — one global number copied across N
  `_schema.yaml` files (SV2 §11.2); a skewed file → `schema-version-skew`.

Per-entry validation failures surface under their OWN typed codes from the wired modules
(`entry-identity-mismatch`, `missing-or-ambiguous-provenance`, `namespace-violation`,
`invalid-version-stamp`, `undeclared-attribute`, `invalid-schema`, …) — this is the Q15
guard's "missing/ambiguous provenance rejected + schema validation run" half (§10 rule 4);
the public-boundary LEAK scan is `scripts/check-no-content.sh` (§10 rule 5, public only —
schema-lint itself runs identically on instance-side repos, where `provenance: instance`
entries are legitimate and lint-clean).

Scan scope mirrors the PA-1 guard scope: the named registry roots plus `instance/` and
`users/` (the §23 re-home — client collections live at
`users/<user>/workspaces/<workspace>/<dimension>/`) — NEVER `tests/`, `docs/`, `pipeline/`,
`scripts/`, `.claude/`, `.github/` (so tracked test fixtures cannot self-flag, PA-1b).
`*.template.*` files are exempt by name (PA-1a — the stale
`platforms/platform.template.md` stays green until the step-40 sweep); the framework
workspace blueprint at `templates/workspace/` sits OUTSIDE the scanned scopes, so it is
exempt automatically. The migration
registry is read from its NAMED path `pipeline/migrations.yaml` (an input file, not a
scanned surface). Known limits (§11.7): a disguised rename (remove+add, same meaning) is
review-only; a whole-collection removal is not diffed (no v1 collection is removable).

Test seam (REC-3 pattern): `--root DIR` + `--baseline DIR`/`--no-baseline` + `--now
YYYY-MM-DD` — fixtures run against copied trees, so CI stays green with fixtures tracked.
Clock discipline: `lint_tree` takes an explicit `now`; `main()` injects real time at the
CLI edge. This module is READ-ONLY toward the tree; the only subprocess use is read-only
`git rev-parse` / `git show` for the default baseline.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from pipeline.attrtypes import validate_value
from pipeline.drift import (
    iter_collections,
    iter_entry_files,
    meaning_changed_attributes,
)
from pipeline.entries import PROVENANCE_FRAMEWORK, load_entry
from pipeline.migration import (
    MIGRATION_REGISTRY_RELPATH,
    WINDOW_DAYS,
    MigrationStep,
    StepRegistry,
    load_step_registry,
    load_step_registry_text,
)
from pipeline.schema import SCHEMA_FILENAME, AttributeSpec, Schema, load_schema, load_schema_text

__all__ = [
    "CODE_CHANGE_WITHOUT_BUMP",
    "CODE_DEFINITION_VERSION_REGRESSION",
    "CODE_FUTURE_RELEASE",
    "CODE_LOCKSTEP",
    "CODE_MAP_NOT_TOTAL",
    "CODE_MEANING_WITHOUT_STEP",
    "CODE_MISSING_SCHEMA",
    "CODE_NON_MONOTONIC",
    "CODE_PREMATURE_PRUNE",
    "CODE_SCHEMA_VERSION_SKEW",
    "CODE_STAMP_AHEAD",
    "CODE_STEP_AHEAD",
    "CODE_STEP_COMPOSITION",
    "CODE_STEP_MUTATED",
    "CODE_UNDECLARED_MEANING_CHANGE",
    "CODE_VERSION_REGRESSION",
    "RELEASE_MARKER",
    "REGISTRY_ROOTS",
    "BaselineReader",
    "LintFinding",
    "LintReport",
    "ReleaseMarkerError",
    "baseline_from_dir",
    "baseline_from_git",
    "iter_lint_collections",
    "lint_tree",
    "main",
    "render_report",
]

#: The named registry-root directories (PA-1 scan scope; design §5, §23). One directory
#: per collection, schema co-located (SV4). This list IS the lint/guard scope boundary —
#: `tests/ docs/ pipeline/ scripts/ .claude/ .github/` are structurally never scanned.
REGISTRY_ROOTS = (
    "topics",
    "personas",
    "formats",
    "voices",
    "goals",
    "platforms",
    "languages",
    "output-types",
    "presentations",
    "content-kinds",
    "sources",
    "render-targets",
    "recipes",
    "folio-types",
    "lexicons",  # DR-2 discharge: schema-lint scans the class-(ii) lexicons registry too
    "diagram-styles",  # mixed-media increment C: the referenced diagram-style registry
    "selections",  # authoring layer C5a: the referenced saved-selection registry (base + variants)
)

#: Scanned subtrees beyond the registry roots (PA-1): collections discovered by their
#: co-located `_schema.yaml` (SV4), e.g. `users/<user>/workspaces/<workspace>/<dimension>/`
#: on an instance-side run (the §23 re-home). The framework workspace blueprint lives at
#: `templates/workspace/`, OUTSIDE these scanned scopes, so it is exempt automatically —
#: no by-name skip is needed.
EXTRA_SCOPE_DIRS = ("instance", "users")

# SV11 finding codes (clause numbers per design §11.7).
CODE_CHANGE_WITHOUT_BUMP = "schema-change-without-version-bump"  # clause 1
CODE_VERSION_REGRESSION = "schema-version-regression"  # clause 1 (backwards)
CODE_MEANING_WITHOUT_STEP = "meaning-change-without-migration-step"  # clause 2
CODE_UNDECLARED_MEANING_CHANGE = "undeclared-meaning-change"  # clause 2
CODE_DEFINITION_VERSION_REGRESSION = "definition-version-regression"  # clause 2
CODE_LOCKSTEP = "lockstep-violation"  # clause 3
CODE_PREMATURE_PRUNE = "premature-prune"  # clause 4
CODE_FUTURE_RELEASE = "future-dated-migration-release"  # clause 4 (step-12 RV-3)
CODE_NON_MONOTONIC = "non-monotonic-migration-releases"  # clause 4 (step-12 RV-3)
CODE_STEP_MUTATED = "migration-step-mutated"  # MIG-1 append-only
CODE_STEP_AHEAD = "migration-step-ahead-of-schema"
CODE_MAP_NOT_TOTAL = "migration-map-not-total"  # §27.4 totality
CODE_STEP_COMPOSITION = "migration-step-composition"  # §27.4 composition
CODE_SCHEMA_VERSION_SKEW = "schema-version-skew"  # step-11 RV-3 carry-forward
CODE_MISSING_SCHEMA = "missing-collection-schema"
CODE_STAMP_AHEAD = "stamp-ahead-of-schema"

#: A baseline reader: repo-relative path → previous-release file text, or None if the
#: path did not exist at the baseline.
BaselineReader = Callable[[str], "str | None"]


@dataclass(frozen=True)
class LintFinding:
    """One named lint failure (the loud, greppable unit of this gate)."""

    code: str
    path: str
    detail: str


@dataclass
class LintReport:
    """One lint run over a tree. `ok` iff no findings."""

    root: str
    now: date
    findings: list[LintFinding] = field(default_factory=list)
    collections_scanned: int = 0
    entries_scanned: int = 0
    steps_scanned: int = 0
    baseline_label: str = "none"

    @property
    def ok(self) -> bool:
        return not self.findings

    def add(self, code: str, path: str, detail: str) -> None:
        self.findings.append(LintFinding(code=code, path=path, detail=detail))

    def codes(self) -> list[str]:
        return [f.code for f in self.findings]


# ---------------------------------------------------------------------------------------
# Baseline readers (clause 1/2/4 need the PREVIOUS release to diff against)
# ---------------------------------------------------------------------------------------


def baseline_from_dir(base: str | Path) -> BaselineReader:
    """A directory tree holding the previous release (the REC-3 test seam form)."""
    base_path = Path(base)

    def read(relpath: str) -> str | None:
        p = base_path / relpath
        return p.read_text(encoding="utf-8") if p.is_file() else None

    return read


def baseline_from_git(root: str | Path, ref: str = "HEAD") -> BaselineReader:
    """The committed tree at `ref` as the baseline (read-only `git show`). Used for
    `--git-ref REF` and for the release-relative default baseline (the commit named by the
    release marker, `_released_ref`). A path absent at `ref` — or a repo with no commits at
    all — reads as None (no baseline for that file: a NEW file has no previous release to
    diff against)."""

    def read(relpath: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "show", f"{ref}:{relpath}"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        return proc.stdout if proc.returncode == 0 else None

    return read


def _git_toplevel(root: Path) -> Path | None:
    """The enclosing git worktree toplevel, or None (read-only probe)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


# ---------------------------------------------------------------------------------------
# The release marker (the RELEASE-relative default baseline; §11.2/§11.7)
# ---------------------------------------------------------------------------------------

#: The committed release marker: a plain-text file holding the git ref/SHA of the LAST
#: release, set by the release process. Its ABSENCE is the pre-release signal — the
#: framework is in development, the default baseline is None, and the clause-1/2/4 diff
#: passes are inert (a version in development makes many schema changes before its release;
#: only the FIRST change AFTER a release must bump the ONE global schema_version). A
#: COMMITTED file, not a git tag, is deliberate: a present-but-unreadable marker fails LOUD
#: (see `_released_ref`) instead of silently degrading to "no baseline". Lives under
#: `pipeline/` (framework mechanism) — never `instance/`/`users/`, and outside every
#: lint/guard scan scope. Not created until release; do NOT create it to signal pre-release.
RELEASE_MARKER = "pipeline/released_baseline"

#: An explicit "still pre-release" sentinel the marker file MAY carry (equivalent to an
#: absent/empty marker → None). Lets the release tooling stage the file with a clear
#: value before the first release without arming the diff.
UNRELEASED_SENTINEL = "unreleased"


class ReleaseMarkerError(ValueError):
    """The release marker names a ref that does not resolve to a commit — "released, but
    the baseline commit is unreachable" (a stale/typo'd marker, or a shallow clone that
    never fetched the release commit). This fails LOUD by design: the whole point of a
    COMMITTED marker (vs. a git tag) is that a present-but-unusable baseline is an error,
    never a silent fall-through to "no baseline". Subclasses `ValueError` so the module's
    typed-refusal handling and `pytest.raises(ValueError)` both catch it."""


def _ref_resolves(root: str | Path, ref: str) -> bool:
    """True iff `ref` resolves to a commit object in the repo at `root` (read-only probe:
    `git rev-parse --verify --quiet <ref>^{commit}`)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def _released_ref(root: str | Path) -> str | None:
    """The git ref for the RELEASE-relative default baseline, read off the committed
    release marker (`RELEASE_MARKER`).

    Returns None PRE-RELEASE — when the marker is ABSENT, empty, or the `unreleased`
    sentinel — so the caller wires NO baseline and the diff clauses are inert. Returns the
    named ref when the marker is present and that ref resolves to a commit.

    Raises `ReleaseMarkerError` (a LOUD, nonzero-exit condition) when the marker is present
    and names a ref that does NOT resolve: "released, but the baseline commit is missing".
    NEVER silently falls back to None in that case — a present-but-unreadable marker is the
    exact failure a committed file (over a git tag) is chosen to surface loudly."""
    marker = Path(root) / RELEASE_MARKER
    if not marker.is_file():
        return None  # pre-release: no marker → no baseline → diff clauses inert
    ref = marker.read_text(encoding="utf-8").strip()
    if not ref or ref == UNRELEASED_SENTINEL:
        return None  # explicitly still pre-release
    if not _ref_resolves(root, ref):
        raise ReleaseMarkerError(
            f"release marker {RELEASE_MARKER!r} names ref {ref!r}, which does not resolve "
            "to a commit — 'released, but the baseline commit is missing' (a stale/typo'd "
            "marker, or a shallow clone that never fetched the release commit). Fetch the "
            "release commit (CI uses fetch-depth: 0) or correct the marker; schema-lint "
            "fails LOUD here rather than silently skipping the release-relative diff."
        )
    return ref


# ---------------------------------------------------------------------------------------
# Scope iteration (PA-1 mirror)
# ---------------------------------------------------------------------------------------


def iter_lint_collections(root: str | Path) -> Iterator[Path]:
    """Every in-scope collection directory: the named registry roots carrying a
    co-located `_schema.yaml`, plus `_schema.yaml`-bearing directories under `instance/`
    and `users/` (the §23 re-home — e.g. `users/<user>/workspaces/<workspace>/<dimension>/`).
    Nothing else is ever visited — `tests/` fixtures cannot self-flag (PA-1b), and the
    framework blueprint at `templates/workspace/` sits outside these scopes entirely (so it
    is exempt automatically, no by-name skip)."""
    root = Path(root)
    for name in REGISTRY_ROOTS:
        coll = root / name
        if (coll / SCHEMA_FILENAME).is_file():
            yield coll
    for scope in EXTRA_SCOPE_DIRS:
        base = root / scope
        if not base.is_dir():
            continue
        yield from iter_collections(base)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:  # pragma: no cover - defensive; scope paths sit under root
        return str(path)


# ---------------------------------------------------------------------------------------
# The lint passes
# ---------------------------------------------------------------------------------------


def _lint_collection(report: LintReport, root: Path, coll: Path) -> Schema | None:
    """Schema + entry validation for one collection (wires load_schema/load_entry).
    Returns the loaded schema, or None when the manifest itself failed."""
    schema_path = coll / SCHEMA_FILENAME
    try:
        schema = load_schema(schema_path)
    except ValueError as exc:
        report.add(getattr(exc, "code", "invalid-schema"), _rel(root, schema_path), str(exc))
        return None
    for entry_path in iter_entry_files(coll):
        report.entries_scanned += 1
        rel = _rel(root, entry_path)
        try:
            entry = load_entry(entry_path, schema)
        except ValueError as exc:
            # The wired typed refusals: entry-identity-mismatch (§11.1 B4),
            # missing-or-ambiguous-provenance (§10 Q15), namespace-violation (§11.4),
            # invalid-version-stamp (§11.2), undeclared-attribute/… (SV3), slug (§7.4).
            report.add(getattr(exc, "code", "invalid-entry"), rel, str(exc))
            continue
        if entry.schema_version > schema.schema_version:
            report.add(
                CODE_STAMP_AHEAD,
                rel,
                f"entry stamp v{entry.schema_version} is ahead of the current schema "
                f"v{schema.schema_version} — a mixed checkout or hand-edited stamp (§11.2)",
            )
            continue
        if entry.provenance == PROVENANCE_FRAMEWORK:
            # SV11 clause 3: framework defaults are lockstep-maintained upstream — a
            # framework entry stamped older than current for a REDEFINED attribute it
            # sets means the release shipped without updating its own defaults.
            drifted = meaning_changed_attributes(schema, entry)
            if drifted:
                listing = ", ".join(
                    f"{a!r} (redefined at v{v})" for a, v in sorted(drifted.items())
                )
                report.add(
                    CODE_LOCKSTEP,
                    rel,
                    f"framework entry stamped v{entry.schema_version} < current "
                    f"v{schema.schema_version} for redefined attribute(s) it sets: "
                    f"{listing} — framework defaults ship lockstep (SV11 clause 3, §11.7)",
                )
    return schema


def _lint_missing_schemas(report: LintReport, root: Path) -> None:
    """A named registry root holding entry files but no co-located `_schema.yaml` —
    entries that can never be validated are default-denied (SV4/§11.7)."""
    for name in REGISTRY_ROOTS:
        coll = root / name
        if not coll.is_dir() or (coll / SCHEMA_FILENAME).is_file():
            continue
        entries = [p.name for p in iter_entry_files(coll)]
        if entries:
            report.add(
                CODE_MISSING_SCHEMA,
                name,
                f"registry root has entry file(s) {entries} but no co-located "
                f"{SCHEMA_FILENAME} (SV4 §13.4) — entries cannot be schema-validated",
            )


def _lint_version_equality(report: LintReport, schemas: dict[str, Schema]) -> None:
    """Step-11 RV-3 carry-forward: SV2's ONE global number, copied across N files —
    cross-collection EQUALITY of every `_schema.yaml`'s `schema_version`."""
    versions = {rel: s.schema_version for rel, s in schemas.items()}
    if len(set(versions.values())) > 1:
        listing = ", ".join(f"{rel}={v}" for rel, v in sorted(versions.items()))
        report.add(
            CODE_SCHEMA_VERSION_SKEW,
            "(cross-collection)",
            f"`schema_version` must be the ONE global number in every {SCHEMA_FILENAME} "
            f"(SV2 §11.2; step-11 RV-3), got: {listing}",
        )


def _covering_step(
    registry: StepRegistry, collection: str, attribute: str, version: int
) -> MigrationStep | None:
    """The MIG-4 covering step for a meaning change: same collection, trigger version ==
    the change's version, targeting the attribute (or object-scope — the escape hatch)."""
    for step in registry.steps:
        if step.collection != collection or step.version != version:
            continue
        if step.scope == "object" or step.attribute == attribute:
            return step
    return None


def _is_empty_floor_default(spec: AttributeSpec) -> bool:
    """§11.2: True iff `spec`'s declared default is its type's EMPTY L0 floor — a container's
    empty (`map` `{}`, `set`/`list` `[]`), an empty `text`/`markdown` `""`, or an `enum` whose
    default is the empty member `""`. An enum can carry `default: ""` ONLY when `""` is a declared
    member (schema-load runs `validate_value` on the default against `spec.values`), so the empty
    member is a genuine empty floor: a pre-existing entry rides `""`, which `ids.delta_vs_floor`
    omits, so every id/digest is byte-identical (§7.2). A NON-empty scalar default — an `enum` at a
    real member, or any `ref`/`bool`/`number` — is NEVER auto-empty: it can change the rendered
    value for a pre-existing entry, so those are NOT additive-at-floor and DO need a bump. This is
    the same "at-floor" notion `ids.delta_vs_floor` uses (effective == default ⇒ omitted), read off
    the declared type kind."""
    kind = spec.type.kind
    if kind == "map":
        return spec.default == {}
    if kind in ("set", "list"):
        return spec.default == []
    if kind in ("text", "markdown", "enum"):
        # `enum` joins here: a `default: ""` is the declared empty member (schema-load already
        # verified `""` is a value), a true empty floor; a NON-empty enum default falls through
        # to the bump below, exactly like `ref`/`bool`/`number`.
        return spec.default == ""
    return False  # ref/bool/number (or a non-empty enum default): no empty floor -> needs a bump


def _is_additive_at_floor(baseline: Schema, current: Schema) -> bool:
    """§11.2 (SV2): True iff `current` differs from `baseline` ONLY by NEW attributes, each
    declared at its type's EMPTY L0 floor — the in-development additive-at-floor evolution that
    needs NO schema_version bump (every pre-existing entry rides the floor; every id/digest is
    byte-identical, §7.2). ANY removal, ANY change to a shared attribute's spec, or a NEW attribute
    at a NON-empty default falls OUTSIDE the exemption — clause 1 (and, for removals/meaning
    changes, clause 2) still fires."""
    for name, bspec in baseline.attributes.items():
        # No removal, and every SHARED attribute's spec must be byte-identical.
        if current.attributes.get(name) != bspec:
            return False
    for name, cspec in current.attributes.items():
        # Every NEW attribute must be declared at its empty L0 floor.
        if name not in baseline.attributes and not _is_empty_floor_default(cspec):
            return False
    return True


def _lint_schema_diff(
    report: LintReport,
    rel_schema: str,
    baseline: Schema,
    current: Schema,
    registry: StepRegistry,
) -> None:
    """Clauses 1–2 against the baseline: any change needs a bump — EXCEPT an in-development
    additive-at-floor manifest change (§11.2, `_is_additive_at_floor`), which needs none; any
    meaning change needs a shipped map-or-prompt (MIG-4) at its trigger version."""
    if current.schema_version < baseline.schema_version:
        report.add(
            CODE_VERSION_REGRESSION,
            rel_schema,
            f"schema_version went backwards: baseline v{baseline.schema_version} -> "
            f"v{current.schema_version} (SV2 §11.2 — the global version only advances)",
        )
    elif (
        current.attributes != baseline.attributes
        and current.schema_version == baseline.schema_version
        # §11.2: an additive-at-floor change (only NEW attributes, each at its empty L0 floor)
        # is legal in-development with NO bump — the version-equality lint keeps all schemas at
        # one number, so a per-schema mid-stream bump would itself fail. Removals and shared-spec
        # changes are NOT additive-at-floor and still require the bump (and clause 2 below).
        and not _is_additive_at_floor(baseline, current)
    ):
        report.add(
            CODE_CHANGE_WITHOUT_BUMP,
            rel_schema,
            f"the attribute manifest changed (a removal, a shared-attribute change, or a new "
            f"attribute at a NON-empty default) but schema_version is still "
            f"v{current.schema_version} — a non-additive-at-floor change bumps the ONE global "
            "version (SV11 clause 1 / §11.2; a purely additive-at-floor change needs none)",
        )

    for name, bspec in baseline.attributes.items():
        cspec = current.attributes.get(name)
        if cspec is None:
            # Removal is a meaning change (§11.7 clause 2): needs a forward step at the
            # release that removed it — i.e. the CURRENT version.
            if _covering_step(registry, current.collection, name, current.schema_version) is None:
                report.add(
                    CODE_MEANING_WITHOUT_STEP,
                    rel_schema,
                    f"attribute {name!r} was removed (a meaning change, §11.7 clause 2) "
                    f"with no migration step at v{current.schema_version} covering it — "
                    "ship a total forward map/drop/rename or a prompt (MIG-4)",
                )
            continue
        _diff_attribute(report, rel_schema, current, name, bspec, cspec, registry)


def _diff_attribute(
    report: LintReport,
    rel_schema: str,
    current: Schema,
    name: str,
    bspec: AttributeSpec,
    cspec: AttributeSpec,
    registry: StepRegistry,
) -> None:
    if cspec.definition_version < bspec.definition_version:
        report.add(
            CODE_DEFINITION_VERSION_REGRESSION,
            rel_schema,
            f"{name!r}: definition_version went backwards "
            f"(v{bspec.definition_version} -> v{cspec.definition_version}) — it is valued "
            "in the monotonic global number-space (SV1 §11.2)",
        )
        return
    if cspec.definition_version > bspec.definition_version:
        # A declared meaning change at v = the new definition_version (SV1): MIG-4
        # demands a shipped map-or-prompt at exactly that trigger version.
        version = cspec.definition_version
        if _covering_step(registry, current.collection, name, version) is None:
            report.add(
                CODE_MEANING_WITHOUT_STEP,
                rel_schema,
                f"{name!r} changed meaning at v{version} (definition_version bump) with "
                "no migration step at that version covering it — a meaning change ships "
                "a total forward map or a prompt (SV11 clause 2, MIG-4)",
            )
        return
    if cspec.type != bspec.type:
        report.add(
            CODE_UNDECLARED_MEANING_CHANGE,
            rel_schema,
            f"{name!r}: the declared type changed ({bspec.type.kind!r} -> "
            f"{cspec.type.kind!r} spec) without a definition_version bump — an "
            "incompatible type change IS a meaning change (§11.7 clause 2, §11.5)",
        )


def _lint_registry_snapshot(
    report: LintReport,
    registry: StepRegistry,
    schemas_by_collection: dict[str, Schema],
    baseline_schemas: dict[str, Schema],
    *,
    now: date,
    global_version: int | None,
) -> None:
    """Snapshot registry checks: window sanity (clause 4, incl. the step-12 RV-3
    carry-forwards) + the §27.4 totality/composition rules for current-release steps."""
    registry_rel = MIGRATION_REGISTRY_RELPATH
    previous_released: date | None = None
    previous_id = ""
    for step in registry.steps:
        report.steps_scanned += 1
        if step.released > now:
            report.add(
                CODE_FUTURE_RELEASE,
                registry_rel,
                f"{step.describe()}: released {step.released} is in the future (as of "
                f"{now}) — a future date corrupts the MIG-2 window math (step-12 RV-3)",
            )
        if previous_released is not None and step.released < previous_released:
            report.add(
                CODE_NON_MONOTONIC,
                registry_rel,
                f"{step.describe()}: released {step.released} predates the preceding "
                f"step {previous_id!r} ({previous_released}) — the append-only registry "
                "carries monotonic non-decreasing release dates (MIG-1; step-12 RV-3)",
            )
        previous_released, previous_id = step.released, step.id
        if global_version is not None and step.version > global_version:
            report.add(
                CODE_STEP_AHEAD,
                registry_rel,
                f"{step.describe()}: trigger version v{step.version} is ahead of the "
                f"current global schema_version v{global_version} — a shipped change "
                "without its version bump (SV11 clause 1 adjunct)",
            )

    # §27.4 totality/composition: validated for steps at the CURRENT release only — older
    # steps were validated at their own release, and the schema has legally moved since.
    for step in registry.steps:
        schema = schemas_by_collection.get(step.collection)
        if schema is None:
            if global_version is not None and step.version == global_version:
                report.add(
                    CODE_STEP_COMPOSITION,
                    registry_rel,
                    f"{step.describe()}: targets collection {step.collection!r}, which "
                    "has no in-scope schema at the current release",
                )
            continue
        if step.version != schema.schema_version:
            continue
        _check_step_composition(
            report, registry_rel, step, schema, baseline_schemas.get(step.collection)
        )


def _check_step_composition(
    report: LintReport,
    registry_rel: str,
    step: MigrationStep,
    schema: Schema,
    baseline: Schema | None,
) -> None:
    """One current-release step against the current (and, for totality, baseline)
    schema. Composition: the step's OUTPUT must be valid under the current schema."""
    if step.action == "map":
        assert step.attribute is not None and step.value_map is not None
        spec = schema.attributes.get(step.attribute)
        if spec is None:
            report.add(
                CODE_STEP_COMPOSITION,
                registry_rel,
                f"{step.describe()}: maps attribute {step.attribute!r}, which the current "
                f"{schema.collection!r} schema does not declare — removal is `drop`, a "
                "rename is `rename_to` (MIG-3)",
            )
            return
        for old, new in step.value_map.items():
            try:
                validate_value(spec.type, new, path=f"{step.id}.map[{old!r}]")
            except ValueError as exc:
                report.add(
                    CODE_STEP_COMPOSITION,
                    registry_rel,
                    f"{step.describe()}: mapped value {new!r} (from {old!r}) is not valid "
                    f"under the current {step.attribute!r} type — the map must compose "
                    f"with the current schema (§27.4): {exc}",
                )
        # Totality (§27.4): checkable exactly when the OLD value domain is finite and
        # known — the baseline's enum members / bool. Infinite domains rely on the
        # fold-time TotalityError backstop (pipeline/migration.py).
        old_spec = baseline.attributes.get(step.attribute) if baseline is not None else None
        domain: list[object] | None = None
        if old_spec is not None and old_spec.type.kind == "enum":
            assert old_spec.type.values is not None
            domain = list(old_spec.type.values)
        elif old_spec is not None and old_spec.type.kind == "bool":
            domain = [True, False]
        if domain is not None:
            missing = [v for v in domain if v not in step.value_map]
            if missing:
                report.add(
                    CODE_MAP_NOT_TOTAL,
                    registry_rel,
                    f"{step.describe()}: the map does not cover baseline value(s) "
                    f"{missing!r} — a deterministic step ships a TOTAL typed forward map "
                    "(SV6/MIG-4, §27.4)",
                )
    elif step.action == "rename":
        assert step.attribute is not None and step.rename_to is not None
        if step.rename_to not in schema.attributes:
            report.add(
                CODE_STEP_COMPOSITION,
                registry_rel,
                f"{step.describe()}: rename target {step.rename_to!r} is not declared by "
                f"the current {schema.collection!r} schema (a rename is a lossless remap "
                "onto a declared attribute, MIG-3)",
            )
        if step.attribute in schema.attributes:
            report.add(
                CODE_STEP_COMPOSITION,
                registry_rel,
                f"{step.describe()}: renames {step.attribute!r} but the current schema "
                "still declares it — a rename removes the old name (MIG-3)",
            )
    elif step.action == "drop":
        assert step.attribute is not None
        if step.attribute in schema.attributes:
            report.add(
                CODE_STEP_COMPOSITION,
                registry_rel,
                f"{step.describe()}: drops {step.attribute!r} but the current schema "
                "still declares it — `drop` accompanies an actual removal (MIG-3)",
            )
    elif step.action == "edit":
        for name, value in (step.edit_set or {}).items():
            spec = schema.attributes.get(name)
            if spec is None:
                report.add(
                    CODE_STEP_COMPOSITION,
                    registry_rel,
                    f"{step.describe()}: edit.set targets {name!r}, which the current "
                    f"{schema.collection!r} schema does not declare (SV3 — the fold "
                    "output must validate)",
                )
                continue
            try:
                validate_value(spec.type, value, path=f"{step.id}.edit.set.{name}")
            except ValueError as exc:
                report.add(
                    CODE_STEP_COMPOSITION,
                    registry_rel,
                    f"{step.describe()}: edit.set value for {name!r} is not valid under "
                    f"the current schema (§27.4): {exc}",
                )
    # `prompt` steps carry no machine-checkable output shape: the human decision is
    # validated at fold time against the current schema (pipeline/migration.py).


def _lint_registry_diff(
    report: LintReport, baseline_registry: StepRegistry, registry: StepRegistry, *, now: date
) -> None:
    """Clause 4 + MIG-1 against the baseline registry: pruning is legal only past the
    1-year window; existing steps are append-only (never re-authored)."""
    current_by_id = {s.id: s for s in registry.steps}
    horizon = now - timedelta(days=WINDOW_DAYS)
    for bstep in baseline_registry.steps:
        cstep = current_by_id.get(bstep.id)
        if cstep is None:
            if bstep.released >= horizon:
                report.add(
                    CODE_PREMATURE_PRUNE,
                    MIGRATION_REGISTRY_RELPATH,
                    f"baseline {bstep.describe()} (released {bstep.released}) was pruned "
                    f"while still inside the 1-year window (horizon {horizon}) — pruning "
                    "a supported step strands configs (SV11 clause 4, MIG-2)",
                )
            continue
        if cstep != bstep:
            report.add(
                CODE_STEP_MUTATED,
                MIGRATION_REGISTRY_RELPATH,
                f"{bstep.describe()} differs from its baseline form — the registry is "
                "APPEND-ONLY; steps are never re-authored (MIG-1)",
            )


# ---------------------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------------------


def lint_tree(
    root: str | Path,
    *,
    now: date,
    baseline: BaselineReader | None = None,
    baseline_label: str = "none",
) -> LintReport:
    """Run every SV11 pass over the tree at `root`. Read-only; returns the report."""
    root = Path(root)
    report = LintReport(root=str(root), now=now, baseline_label=baseline_label)

    schemas: dict[str, Schema] = {}  # rel schema path -> loaded schema
    schemas_by_collection: dict[str, Schema] = {}
    baseline_schemas: dict[str, Schema] = {}
    collections: list[tuple[Path, Schema]] = []

    _lint_missing_schemas(report, root)
    for coll in iter_lint_collections(root):
        report.collections_scanned += 1
        schema = _lint_collection(report, root, coll)
        if schema is None:
            continue
        rel_schema = _rel(root, coll / SCHEMA_FILENAME)
        schemas[rel_schema] = schema
        schemas_by_collection[schema.collection] = schema
        collections.append((coll, schema))

    _lint_version_equality(report, schemas)
    global_version = max((s.schema_version for s in schemas.values()), default=None)

    registry_path = root / MIGRATION_REGISTRY_RELPATH
    try:
        registry = load_step_registry(registry_path)  # missing file = empty registry
    except ValueError as exc:
        report.add(
            getattr(exc, "code", "invalid-migration-registry"),
            MIGRATION_REGISTRY_RELPATH,
            str(exc),
        )
        registry = StepRegistry(steps=(), source=str(registry_path))

    if baseline is not None:
        for coll, schema in collections:
            rel_schema = _rel(root, coll / SCHEMA_FILENAME)
            btext = baseline(rel_schema)
            if btext is None:
                continue  # a NEW collection: no previous release to diff against
            try:
                bschema = load_schema_text(btext, collection=schema.collection)
            except ValueError as exc:
                report.add(
                    getattr(exc, "code", "invalid-schema"),
                    rel_schema,
                    f"the BASELINE ({baseline_label}) form of this schema does not load — "
                    f"cannot diff clauses 1-2: {exc}",
                )
                continue
            baseline_schemas[schema.collection] = bschema
            _lint_schema_diff(report, rel_schema, bschema, schema, registry)
        breg_text = baseline(MIGRATION_REGISTRY_RELPATH)
        if breg_text is not None:
            try:
                baseline_registry = load_step_registry_text(
                    breg_text, source=f"baseline:{MIGRATION_REGISTRY_RELPATH}"
                )
            except ValueError as exc:
                report.add(
                    getattr(exc, "code", "invalid-migration-registry"),
                    MIGRATION_REGISTRY_RELPATH,
                    f"the BASELINE ({baseline_label}) registry does not load — cannot "
                    f"diff clause 4: {exc}",
                )
            else:
                _lint_registry_diff(report, baseline_registry, registry, now=now)

    _lint_registry_snapshot(
        report,
        registry,
        schemas_by_collection,
        baseline_schemas,
        now=now,
        global_version=global_version,
    )
    return report


def render_report(report: LintReport) -> str:
    """Deterministic human-readable rendering (the schema-lint CLI output)."""
    lines = [
        f"SCHEMA LINT (SV11, design §11.7) — root: {report.root} — as of {report.now}",
        f"collections: {report.collections_scanned} · entries: {report.entries_scanned} "
        f"· migration steps: {report.steps_scanned} · baseline: {report.baseline_label}",
    ]
    for f in report.findings:
        lines.append(f"  FAIL [{f.code}] {f.path}: {f.detail}")
    if report.ok:
        lines.append("OK: schema-lint clean.")
    else:
        lines.append(
            f"summary: {len(report.findings)} finding(s) — the public repo fails on any "
            "SV11 clause (design §11.7)."
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI for `scripts/schema-lint.sh`. Exit: 0 clean · 1 findings · 2 usage."""
    parser = argparse.ArgumentParser(
        prog="schema-lint.sh",
        description=(
            "SV11 schema-lint (docs/design.md §11.7): schema-change-without-bump, "
            "meaning-change-without-map-or-prompt, lockstep, window sanity, map "
            "totality/composition (§27.4), slug + entry-identity + provenance + closed-"
            "schema validation (§7.4, §11.1, §10). Exit 0 clean · 1 findings · 2 usage."
        ),
    )
    parser.add_argument("--root", default=".", help="tree to lint (default: cwd)")
    parser.add_argument(
        "--baseline",
        default=None,
        metavar="DIR",
        help="previous-RELEASE tree to diff clauses 1/2/4 against (default: the commit "
        "named by the release marker pipeline/released_baseline when --root is a git "
        "checkout's toplevel; NONE pre-release — the marker is absent — and none for a "
        "non-git tree)",
    )
    parser.add_argument(
        "--git-ref",
        default=None,
        metavar="REF",
        help="git ref for the default baseline, overriding the release marker (default: "
        "the last release via the marker, or NONE pre-release)",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="disable the baseline diff entirely (snapshot clauses only)",
    )
    parser.add_argument(
        "--now",
        default=None,
        metavar="YYYY-MM-DD",
        help="override the lint clock (ops/testing; default: today). The clock is "
        "injected here at the edge — the library never reads ambient time.",
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        now = date.fromisoformat(args.now) if args.now else date.today()  # the clock edge
    except ValueError:
        print(f"schema-lint: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2

    baseline: BaselineReader | None = None
    baseline_label = "none"
    if args.no_baseline:
        pass
    elif args.baseline is not None:
        base_dir = Path(args.baseline)
        if not base_dir.is_dir():
            print(f"schema-lint: --baseline {args.baseline!r} is not a directory", file=sys.stderr)
            return 2
        baseline = baseline_from_dir(base_dir)
        baseline_label = f"dir:{base_dir}"
    else:
        toplevel = _git_toplevel(root)
        if toplevel is not None and toplevel.resolve() == root.resolve():
            # RELEASE-relative default baseline: an explicit --git-ref overrides; otherwise
            # the commit named by the release marker (None pre-release → no baseline → the
            # diff clauses are inert). A present-but-unresolvable marker fails LOUD here.
            try:
                ref = args.git_ref if args.git_ref is not None else _released_ref(root)
            except ReleaseMarkerError as exc:
                print(f"schema-lint: {exc}", file=sys.stderr)
                return 2
            if ref is not None:
                baseline = baseline_from_git(root, ref)
                baseline_label = f"git:{ref}"

    report = lint_tree(root, now=now, baseline=baseline, baseline_label=baseline_label)
    sys.stdout.write(render_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":  # `python -m pipeline.lint` (via scripts/schema-lint.sh)
    raise SystemExit(main())
