"""The workspace store: §23 layout + the G1 atomic-write primitives + `is_done`.

Design authority: `docs/design.md` §23 (the per-client tree under `workspaces/<client>/`),
§22.3/§22.8 (the commit primitives, verified by gate G1 — step-01 probe, step-06 parameter
sheet item 1), §13.3 (machine-record encodings; filename = id, no extension, for claims and
folio member markers), §18 (what persists, keyed how), §19 (review records are id-addressed —
the `reviews/` home, PA-9d), §7.4 (store filenames derive from ids; filename exactness),
§21.2 (marker updates = atomic replacing rename), PA-15 (`select/` homed here).

**Interface contract (plan step 20 → step 21):** this module (`store`) plus
`pipeline.claims` are the COMPLETE shared-write primitive set. The S0–S6 spine consumes
them by contract and adds no new filesystem primitives.

The layout (§23, structure only — created on demand under a CALLER-SUPPLIED root; this
module never names or creates any instance workspace itself):

    <root>/artifacts/       IR-canonical + IR-fitted + AST records (artifact-/fitted-level
                            keys, §18) — flat, prefix-queryable by id (§7.4)
    <root>/deliverables/    layer-2 bytes + render-bindings (deliverable-level keys, §18)
    <root>/claims/          the claim/lease table (§22.3) — data owned by pipeline.claims
    <root>/folios/<folio-id>/members/<artifact-id>   marker-per-member records (§13.3)
    <root>/reviews/         id-addressed review records (§19; PA-9d)
    <root>/select/          selection inputs (§23; PA-15)
    <root>/output/          outputs, incl. output/manifests/ (§21.5)
    <root>/jobs/<run-id>    DR-1 async job/idempotency records — §22.7-class LOSSY
                            bookkeeping, keyed by a NON-artifact run-family id (never an
                            output route; see "The DR-1 jobs/ boundary" below)
    <root>/assets/[subdir/]<sha256hex>.<ext>   content-addressed content assets (images,
                            generated SVG diagrams under assets/diagrams/) — a DISTINCT
                            CONTENT-HASH keying scheme, never routed by `output_path`/`is_done`
                            (see "The content-asset boundary" below)

**The content-asset boundary** (increment A — the mixed-media asset foundation): a content
asset lives at `assets/[subdir/]<sha256hex>.<ext>` and is keyed by the SHA-256 of its own
BYTES (`sha256_hex(content)`), not by a §7.4 id. This is a DISTINCT keying scheme from every
id-addressed record above — the asset filename is a bare content digest + a conventional
extension, so it is deliberately NOT a `parse_id`-valid id and NEVER routes through
`output_path`/`is_done` (which parse and refuse non-artifact ids). Content-addressing makes the
write idempotent by construction: identical bytes yield the identical path, so a re-write is the
designed `already-materialized` no-op (`commit_asset` swallows it — the `jobs/` precedent for an
additive, identity-inert store). The client surface is `workspaces/<client>/assets/`; the
containment guard (increment A, at compose) refuses any body image reference that escapes it.

**The DR-1 `jobs/` boundary** (async subsystem; the subdir + this keying convention land here,
the `JobStore` record logic lands in DR-1 Commit 3): a `jobs/` record is §22.7-class LOSSY
bookkeeping — a lagging projection consulted for NOTHING that gates correctness (DONE is output
existence, §22.7; RUNNING is the id-keyed claim/lease, §22.3). Two invariants pin it:

- **A job record is keyed by a NON-artifact id** — a run-family `r-<hex16>` whose root is the
  digest of the job's sorted target-id set + `idempotency_key` (the keying helper is Commit 3).
  It is therefore never an artifact/fitted/deliverable id.
- **A job key can NEVER route through `output_path`/`is_done`.** Those route by id FAMILY and
  refuse every non-artifact family with `StorePathError` (below), so a job record can never
  masquerade as an output nor be mistaken for materialized work; even a bare-digest filename
  would be refused (`IdError`). The two §22.7 authorities (output existence + the claim/lease
  table) never read `jobs/`.

Its DATA is `provenance: instance`, gitignored (`workspaces/*/jobs/`, §10/§23); retention/GC is
registered as deferred (§27.3), like the claim table and the non-current-fit stores.

The G1 primitives (all proven on the real APFS volume — gate G1 PASS, 6/6):

- **write-temp-then-atomic-NO-REPLACE commit** (`stage_temp` + `commit_new`, or `write_new`):
  `os.link(temp, target)` + `os.unlink(temp)` — the PRIMARY commit primitive per the step-06
  parameter sheet (`renamex_np(RENAME_EXCL)` is the proven Darwin-only alternative,
  deliberately not used — stdlib is portable and behaved identically). A commit against an
  EXISTING target FAILS (`AlreadyMaterializedError`): the loser's temp is discarded and the
  winner's bytes are untouched (§22.3, B4-4). An output is wholly absent or wholly present,
  never partial, never overwritten — this is what makes output existence the idempotency
  authority (§22.7).
- **atomic create-if-absent** (`create_exclusive`): `os.open(O_CREAT|O_EXCL)` — the §22.3
  claim-acquisition primitive (consumed by `pipeline.claims`).
- **atomic replacing rename** (`write_replace`): temp + `os.rename` — for MARKER updates only
  (§21.2 `member-updated`, §13.3) and the §22.3 claim steal. Never for outputs: a plain
  rename REPLACES an existing target, which would break the §22.7 existence authority.
- **atomic single-line append** (`append_jsonl_line`): one `write()` per line on an
  `O_APPEND` fd (§13.3 JSONL; a torn final line is discardable — proven for short records;
  do not assume for large lines, per the parameter sheet).

**INV-CORRECTNESS (§22.7) starts here:** this module takes no SSOT handle and imports no
SSOT code. `is_done(store, id_str)` reads OUTPUT EXISTENCE ONLY — the §7.4 preimage
comparison half of S0 lands with the spine (step 21) and also reads only the output store.

**Retention (A4, step-06 build note):** this module exposes NO deletion primitive for
artifacts/deliverables/bindings/reviews/folio markers — v1 retains all, id-addressed. The
only `os.unlink` here targets the caller's OWN uncommitted temp file (part of the commit
primitive itself, per the G1 probe); claim release/steal — the sole sanctioned removal —
lives in `pipeline.claims`. A crashed writer's dropped temp is inert and identifiable
(`is_temp_name`) but is never auto-deleted here: a `cleanup()` convenience would be a
silent GC design call (A4 — GC is registered, not designed).

Time never enters this module; lease logic (with its injectable clock) is `pipeline.claims`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.canonical import canonical_json_str, sha256_hex
from pipeline.ids import output_filename, parse_id
from pipeline.workspace_name import USERS_DIRNAME, WORKSPACES_DIRNAME, ZONES_DIRNAME

__all__ = [
    "STORE_SUBDIRS",
    "TEMP_PREFIX",
    "AlreadyMaterializedError",
    "StorePathError",
    "StoreWriteError",
    "WorkspaceStore",
    "WorkspaceStoreIdentityError",
    "append_jsonl_line",
    "commit_new",
    "create_exclusive",
    "framework_root_of",
    "is_done",
    "is_temp_name",
    "stage_temp",
    "write_new",
    "write_replace",
]

#: §23: the per-client stores created on demand under `workspaces/<client>/`. `jobs/` (DR-1),
#: `assets/` (increment A), and `sources/cache` (sources P1) are ADDITIVE subdirs consumed ONLY by
#: `ensure_layout` here — each is in NO id/preimage/digest and `output_path` routes by id family
#: (never this tuple), so appending them is identity-inert (no `schema_version`/`ir_version` bump).
#: `assets/` is the content-addressed content-asset home; `sources/cache` is the sealed
#: acquired-content slice store (see the respective boundary notes / `pipeline.sources.cache`). The
#: nested `sources/cache` segment flows through `_dir` (joinpath + `mkdir(parents=True)`) exactly.
STORE_SUBDIRS = (
    "artifacts",
    "deliverables",
    "claims",
    "folios",
    "reviews",
    "select",
    "output",
    "jobs",
    "assets",
    "sources/cache",
)

#: Staged-temp filenames start with this. A leading dot can never collide with an id
#: (§7.4: no leading dot) and never matches a §7.4 prefix listing; the fixed pattern makes
#: a crash-dropped temp identifiable (GC-able by a FUTURE ops sweep — never deleted here, A4).
TEMP_PREFIX = ".tmp-"

_FILE_MODE = 0o644


class StorePathError(ValueError):
    """An id routed at the wrong store surface (e.g. a folio id as an output) — refused."""

    code = "invalid-store-path"


class AlreadyMaterializedError(Exception):
    """A no-replace commit found its target already present (§22.3, §22.6 `already-materialized`).

    This is the designed LOSER outcome, not a fault: the §22.6 code class is `ok` — the id
    is materialized, the winner's bytes are intact, and this committer's temp has been
    discarded. It is raised (rather than returned) so a loser can never mistake itself for
    the winner (B4-4: after a lease steal, the stolen-from worker's late commit takes
    exactly this path).
    """

    code = "already-materialized"

    def __init__(self, target: Path) -> None:
        super().__init__(
            f"already-materialized: {target} exists — temp discarded, winner bytes intact (§22.3)"
        )
        self.target = target


class StoreWriteError(RuntimeError):
    """A write primitive could not uphold its atomicity contract — refused loudly."""

    code = "store-write-failed"


class WorkspaceStoreIdentityError(ValueError):
    """An identity accessor was read on a store built without identity — refused loudly.

    A `WorkspaceStore` carries identity ONLY when constructed via `WorkspaceStore.at(...)`
    (the sole constructor that knows the `users/<user>/workspaces/<workspace>/` layout depth).
    A bare `WorkspaceStore(root)` — production's positional construction and the test-injection
    seam — has NO identity: reading `framework_root`/`user`/`workspace`/`user_root` on it raises
    THIS error rather than returning `None` or guessing framework-root/name by fragile positional
    path math (`root.parent.parent` / `root.name`), which silently mis-resolves at any layout
    depth. A ValueError subclass so an `except ValueError` door still catches it; `code` follows
    the module's typed-error convention (cf. `StorePathError`).
    """

    code = "workspace-store-identity-unavailable"


# ---------------------------------------------------------------------------
# The §23 workspace store layout: paths derive from ids (§7.4, §18).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkspaceStore:
    """One client workspace's store tree, rooted at a CALLER-SUPPLIED path (§23).

    The caller owns workspace placement (`workspaces/<client>/` in production — rule 2;
    any tmp dir in tests): this class creates directories on demand under `root` and
    nothing anywhere else. Every path-returning method validates its id via
    `pipeline.ids.parse_id`, so a filename is always a §7.4-safe exact id — no separators,
    no traversal, ≤ 255 bytes by construction.

    **Identity (increment B3, additive).** `root` alone cannot say WHICH workspace this is
    nor WHERE its framework root lives — callers used to recover both by positional path math
    (`root.parent.parent` for the framework root, `root.name` for the workspace name). That
    math silently mis-resolves once the tree deepens to `users/<user>/workspaces/<workspace>/`
    (the re-home). The cure: a store MAY carry explicit identity, recorded (never guessed) by
    the ONE constructor that knows the layout depth — `WorkspaceStore.at(framework_root, user,
    workspace)`. The identity fields (`_framework_root`/`_user`/`_workspace`) are private and
    default to `None`; the public accessors `framework_root`/`user`/`workspace`/`user_root` are
    raise-loud PROPERTIES — there is deliberately NO public nullable identity attribute, so a
    caller can never read a silent `None` (they raise `WorkspaceStoreIdentityError` on an
    identity-less bare store). Bare `WorkspaceStore(root)` (production's positional construction
    and the test-injection seam) is byte-for-byte unaffected: the identity fields are optional,
    appended AFTER `root`, so every existing single-arg construction and id-addressed method is
    unchanged. No reader/producer consumes the identity API yet — that switch is a later
    increment; B3 only lays the cure.
    """

    root: Path
    #: Identity (increment B3) — set ONLY by `WorkspaceStore.at(...)`, else `None`. Private so
    #: the sole read path is the raise-loud public property (never a silent-`None` attribute).
    _framework_root: Path | None = None
    _user: str | None = None
    _workspace: str | None = None
    #: The zone this workspace lives under (Z2) — `users/<user>/zones/<zone>/workspaces/<ws>`.
    #: Set ONLY by `WorkspaceStore.at(..., zone=<zone>)`; `None` on the legacy 3-level `.at`
    #: (`zone=None`) and on a bare store. Appended AFTER `_workspace` so bare positional
    #: `WorkspaceStore(root)` and `.at(...)` with no zone stay byte-identical (default `None`).
    _zone: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        if self._framework_root is not None:  # parity with root's str→Path coercion
            object.__setattr__(self, "_framework_root", Path(self._framework_root))

    @classmethod
    def at(
        cls,
        framework_root: str | Path,
        user: str,
        workspace: str,
        *,
        zone: str,
    ) -> WorkspaceStore:
        """Build the store for a workspace AND record its identity (increment B3; zone since Z2).

        THE ONLY constructor that knows the layout depth: it composes `root` from the layout
        literals (imported from `pipeline.workspace_name`, their single home) and stores
        `framework_root`/`user`/`workspace`/`zone` so the accessors return recorded facts, never
        positional guesses. `framework_root` is coerced to `Path` (parity with `root`). Callers
        that already hold a full root keep using bare `WorkspaceStore(root)`; this factory is for
        callers that hold the framework root + identity and want depth-robust accessors.

        `zone` is a REQUIRED KEYWORD-ONLY argument (Z4, the atomic cutover): the root is the 4-level
        `framework_root / USERS_DIRNAME / user / ZONES_DIRNAME / zone / WORKSPACES_DIRNAME /
        workspace` (a zone sits BETWEEN user and workspace), recording `_zone=zone`. A forgotten
        `zone` is a LOUD missing-keyword `TypeError`, and a `zone=None` is a LOUD `TypeError` from
        the `zones/None` join — NEVER a silent legacy 3-level path (Z4 deleted the `zone=None`
        compatibility scaffold every pre-cutover caller relied on).

        This factory does NOT validate `zone` (the `validate_zone_segment` hygiene/containment gate
        is the door's job, mirroring how `.at` never re-validates `user`/`workspace`). `user_root`
        and every other method are unchanged.
        """
        fr = Path(framework_root)
        root = fr / USERS_DIRNAME / user / ZONES_DIRNAME / zone / WORKSPACES_DIRNAME / workspace
        return cls(root, fr, user, workspace, zone)

    # -- identity accessors (§23 re-home; raise-loud, never silent-None) ----

    @property
    def framework_root(self) -> Path:
        """The instance framework root this workspace lives under — raise-loud if absent.

        Returns the value recorded by `WorkspaceStore.at(...)`. On an identity-less bare store
        raises `WorkspaceStoreIdentityError` rather than returning `None` or reconstructing it
        by positional path math (`root.parent.parent`), which breaks at the re-home depth.
        """
        if self._framework_root is None:
            raise WorkspaceStoreIdentityError(
                "framework_root unavailable — this store was constructed without identity; "
                "use WorkspaceStore.at(framework_root, user, workspace)"
            )
        return self._framework_root

    @property
    def user(self) -> str:
        """The owning user for this workspace — raise-loud if absent (never silent-`None`)."""
        if self._user is None:
            raise WorkspaceStoreIdentityError(
                "user unavailable — this store was constructed without identity; "
                "use WorkspaceStore.at(framework_root, user, workspace)"
            )
        return self._user

    @property
    def workspace(self) -> str:
        """This workspace's name — raise-loud if absent (never silent-`None`).

        The identity-recorded name; distinct from `root.name` (which stays the depth-robust
        fallback some readers keep by design). On a bare store this raises rather than guessing.
        """
        if self._workspace is None:
            raise WorkspaceStoreIdentityError(
                "workspace unavailable — this store was constructed without identity; "
                "use WorkspaceStore.at(framework_root, user, workspace)"
            )
        return self._workspace

    @property
    def zone(self) -> str:
        """This workspace's zone — raise-loud if absent (never silent-`None`).

        Recorded ONLY by `WorkspaceStore.at(..., zone=<zone>)`. A store built with `zone=None`
        (the legacy 3-level compatibility scaffold) or a bare `WorkspaceStore(root)` records NO
        zone: reading `.zone` raises `WorkspaceStoreIdentityError` rather than returning `None`,
        exactly as `user`/`workspace` do — "no zone recorded" is refused loudly, never guessed.
        """
        if self._zone is None:
            raise WorkspaceStoreIdentityError(
                "zone unavailable — this store was constructed without a zone; "
                "use WorkspaceStore.at(framework_root, user, workspace, zone=<zone>)"
            )
        return self._zone

    @property
    def user_root(self) -> Path:
        """The per-user home `framework_root / users / <user>` — the REST-forward anchor for
        future per-user collections (raise-loud if identity is absent, via the accessors above).
        """
        return self.framework_root / USERS_DIRNAME / self.user

    def _dir(self, *parts: str) -> Path:
        path = self.root.joinpath(*parts)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- the §23 stores, created on demand ---------------------------------

    @property
    def artifacts_dir(self) -> Path:
        """IR-canonical / IR-fitted / AST records — artifact- and fitted-level keys (§18)."""
        return self._dir("artifacts")

    @property
    def deliverables_dir(self) -> Path:
        """Layer-2 bytes + render-bindings — deliverable-level keys (§18)."""
        return self._dir("deliverables")

    @property
    def claims_dir(self) -> Path:
        """The workspace-scoped claim/lease table (§22.3) — data owned by `pipeline.claims`."""
        return self._dir("claims")

    @property
    def folios_dir(self) -> Path:
        """Folio trees: `folios/<folio-id>/members/<artifact-id>` markers (§13.3, §23)."""
        return self._dir("folios")

    @property
    def reviews_dir(self) -> Path:
        """Id-addressed review records (§19: outcomes attach to ids — PA-9d)."""
        return self._dir("reviews")

    @property
    def select_dir(self) -> Path:
        """Selection inputs (§23; PA-15)."""
        return self._dir("select")

    @property
    def output_dir(self) -> Path:
        """Outputs (§23)."""
        return self._dir("output")

    @property
    def manifests_dir(self) -> Path:
        """Manifest emissions: `output/manifests/` (§21.5, §23)."""
        return self._dir("output", "manifests")

    @property
    def jobs_dir(self) -> Path:
        """DR-1 async job/idempotency records — §22.7-class LOSSY bookkeeping (see the
        module docstring's "DR-1 `jobs/` boundary" note).

        Keyed by a NON-artifact id — a run-family `r-<hex16>` digesting the sorted target-id
        set + `idempotency_key` (the keying helper is DR-1 Commit 3's `JobStore`). A job key
        NEVER routes through `output_path`/`is_done`: those refuse every non-artifact family
        with `StorePathError`, so a job record can never be mistaken for an output. DATA is
        `provenance: instance`, gitignored (`workspaces/*/jobs/`, §10/§23).
        """
        return self._dir("jobs")

    @property
    def assets_dir(self) -> Path:
        """Content-addressed content assets: `assets/[subdir/]<sha256hex>.<ext>` (increment A).

        A DISTINCT CONTENT-HASH keying scheme (see "The content-asset boundary" in the module
        docstring), never routed by `output_path`/`is_done`. This is the store ROOT of the
        home; `asset_path`/`commit_asset` derive the per-asset content-addressed path (and the
        nested `assets/diagrams/` generated-SVG path) beneath it.
        """
        return self._dir("assets")

    @property
    def sources_cache_dir(self) -> Path:
        """The sealed acquired-content slice store: `sources/cache/` (sources P1).

        The per-workspace home for `pipeline.sources.cache` — ACQUIRED THIRD-PARTY CONTENT written
        as immutable, content-addressed sealed slices, gitignored (`users/*/workspaces/`) and never
        committed. A DISTINCT keying scheme (bare slice digests + a namespace `HEAD` marker), never
        routed by `output_path`/`is_done`: like `jobs/` and `assets/` it is identity-inert (in no
        id/preimage/digest), so appending its STORE_SUBDIR is a purely additive change. Namespaces
        + slices are derived beneath it by `pipeline.sources.cache.namespace_dir`/`slice_path`."""
        return self._dir("sources", "cache")

    def ensure_layout(self) -> tuple[Path, ...]:
        """Materialize the full §23 tree (idempotent); returns the created directories."""
        dirs = tuple(self._dir(name) for name in STORE_SUBDIRS)
        return (*dirs, self.manifests_dir)

    # -- id-derived paths (§7.4: the filename IS the id, exactly) ----------

    def output_path(self, id_str: str) -> Path:
        """THE output location for a work-unit id — the §22.7 existence authority.

        Routes by the id's level (§18 keys): artifact-/fitted-level records live under
        `artifacts/`, deliverable-level records under `deliverables/`; parts ride their
        owner's level (§7.1). The filename is the id EXACTLY — extension-free names are
        always valid and authoritative (§7.4). Folio/run ids are not outputs — refused (a
        DR-1 job key is a run-family id, so a job record can never route here — §22.7 pin).
        """
        parsed = parse_id(id_str)
        if parsed.family != "artifact":
            raise StorePathError(
                f"invalid-store-path: {id_str!r} is a {parsed.family} id — only "
                "artifact-family ids key output records (§18)"
            )
        if parsed.level == "deliverable":
            return self.deliverables_dir / id_str
        return self.artifacts_dir / id_str

    def bytes_path(self, id_str: str, extension: str) -> Path:
        """A layer-2 byte output: the deliverable id plus a conventional extension (§7.4).

        The extension is never part of the id and is appended only when the result still
        fits 255 bytes (`pipeline.ids.output_filename` — otherwise the extension-free name
        is returned). Deliverable-level ids only (§18: layer-2 bytes key by deliverable-id).
        """
        parsed = parse_id(id_str)
        if parsed.level != "deliverable":
            raise StorePathError(
                f"invalid-store-path: layer-2 bytes key by deliverable-id (§18), got "
                f"level {parsed.level!r} in {id_str!r}"
            )
        return self.deliverables_dir / output_filename(id_str, extension)

    def claim_path(self, id_str: str) -> Path:
        """A claim file: `claims/<id>` — the filename IS the claimed id IS the lock (§13.3).

        No extension, ever (§7.4 filename scope). Any valid pipeline id is a legal claim
        key (§22.3 names artifact-level work and `fitted-id` explicitly). The claim
        PROTOCOL (acquire/release/steal) lives in `pipeline.claims`.
        """
        parse_id(id_str)
        return self.claims_dir / id_str

    def folio_member_path(self, folio_id: str, artifact_id: str) -> Path:
        """A folio membership marker: `folios/<folio-id>/members/<artifact-id>` (§13.3, §23).

        The marker filename is the member's artifact-id EXACTLY (§13.3) — members are
        artifacts (§9.2), so a bare artifact-level id with no part suffix is required.
        Marker updates go through `write_replace` (§21.2); membership is append-only in v1.
        """
        folio = parse_id(folio_id)
        if folio.family != "folio":
            raise StorePathError(
                f"invalid-store-path: {folio_id!r} is not a folio id (§7.4: f-<hex12>)"
            )
        member = parse_id(artifact_id)
        if member.family != "artifact" or member.level != "artifact" or member.part is not None:
            raise StorePathError(
                f"invalid-store-path: a folio member marker is keyed by the member's "
                f"bare artifact-id (§13.3), got {artifact_id!r}"
            )
        return self._dir("folios", folio_id, "members") / artifact_id

    def review_path(self, id_str: str) -> Path:
        """An id-addressed review record: `reviews/<id>` (§19; PA-9d).

        Review outcomes attach to ids and never transfer across revisions (§19): artifact
        review (gate 1) keys by artifact-id, deliverable review (gate 2) by deliverable-id
        — exactly those two levels; parts are reviewed via their owner (§19), refused here.
        """
        parsed = parse_id(id_str)
        if (
            parsed.family != "artifact"
            or parsed.level not in ("artifact", "deliverable")
            or parsed.part is not None
        ):
            raise StorePathError(
                f"invalid-store-path: review records attach to artifact-ids and "
                f"deliverable-ids only (§19), got {id_str!r}"
            )
        return self.reviews_dir / id_str

    # -- content-addressed content assets (increment A; a DISTINCT keying scheme) ----

    def asset_path(self, content: bytes, *, subdir: str = "", extension: str) -> Path:
        """The content-addressed location for an asset: `assets/[subdir/]<sha256hex>.<ext>`.

        Keyed by the SHA-256 of the asset's own BYTES (`sha256_hex(content)`), NOT by a §7.4 id —
        the "content-asset boundary" (module docstring): the filename is a bare content digest plus
        a conventional extension, deliberately NOT `parse_id`-valid, and never routed through
        `output_path`/`is_done`. `subdir` nests the asset — e.g. `subdir="diagrams"` yields the
        generated-SVG path `assets/diagrams/<sha256hex>.<ext>`. The containing `assets/[subdir/]`
        directory is created on demand (exactly as `output_path` materializes `artifacts/`). This
        is a pure calculator (plus the mkdir); `commit_asset` writes the bytes idempotently.
        """
        return self._dir("assets", subdir) / f"{sha256_hex(content)}.{extension}"

    def commit_asset(self, content: bytes, *, subdir: str = "", extension: str) -> Path:
        """Idempotently write a content asset; return its content-addressed path (§22.3/§22.7).

        Rides the existing no-replace `write_new` commit but SWALLOWS `AlreadyMaterializedError`:
        because the asset is content-addressed, identical bytes always resolve to the identical
        path, so a re-write is the DESIGNED `already-materialized` no-op — the winner's
        byte-identical content stands untouched (mirroring `build_outline_ir`'s idempotent-emit
        pattern in `compose.py`). Different content yields a different hash, hence a different path,
        so a same-path collision with DIFFERENT bytes cannot arise by construction. This is the
        reusable primitive later increments consume to persist figures (B) and generated diagrams
        (C); `asset_path` alone is only the calculator. Returns the path whether the bytes were
        newly committed or already present.
        """
        path = self.asset_path(content, subdir=subdir, extension=extension)
        try:
            write_new(path, content)
        except AlreadyMaterializedError:
            pass  # idempotent: content-addressed ⇒ identical bytes already present (§22.7)
        return path


def framework_root_of(store: WorkspaceStore) -> Path:
    """The framework root a store lives under — a functional mirror of `store.framework_root`.

    A convenience in the `is_done(store, ...)` free-function idiom: it gives future readers a
    drop-in for the positional `store.root.parent.parent` expression (increment B5) that is
    loud-on-absent (it delegates to the raise-loud property, so an identity-less bare store
    raises `WorkspaceStoreIdentityError` — never a silent `None` or a depth-fragile guess).
    """
    return store.framework_root


# ---------------------------------------------------------------------------
# G1 atomic primitives (§22.8; step-06 parameter sheet item 1).
# ---------------------------------------------------------------------------


def is_temp_name(name: str) -> bool:
    """True iff `name` is a staged-temp filename (crash-drop identification — never deletion)."""
    return name.startswith(TEMP_PREFIX)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def stage_temp(target: Path, data: bytes) -> Path:
    """Write `data` to a fresh temp file BESIDE `target` (same dir ⇒ same volume for link).

    The temp name is `.tmp-<pid>-<hex>` — never id-shaped (§7.4: ids have no leading dot),
    invisible to prefix listings, and identifiable via `is_temp_name` if a crash drops it.
    Contents are fully written and fsynced before return: a staged temp is complete by
    construction, so a crash before `commit_new` leaves NO partial final — the target
    simply does not exist yet (§22.3: wholly absent or wholly present).
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(3):  # O_EXCL collision on 8 random bytes is astronomically unlikely
        temp = target.parent / f"{TEMP_PREFIX}{os.getpid()}-{os.urandom(8).hex()}"
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
        except FileExistsError:
            continue
        try:
            _write_all(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        return temp
    raise StoreWriteError("store-write-failed: could not stage a unique temp file")


def commit_new(temp: Path, target: Path) -> None:
    """The atomic NO-REPLACE commit: `os.link(temp, target)` + `os.unlink(temp)` (G1 primary).

    Against an ABSENT target the staged bytes become the target atomically. Against an
    EXISTING target the commit FAILS: the temp is discarded (the §22.3 loser discipline)
    and `AlreadyMaterializedError` is raised — the winner's bytes are untouched (B4-4).
    Never overwrites, never partial: the existence authority of §22.7.
    """
    temp, target = Path(temp), Path(target)
    try:
        os.link(temp, target)
    except FileExistsError:
        os.unlink(temp)  # the loser discards its OWN temp (§22.3) — never touches the target
        raise AlreadyMaterializedError(target) from None
    os.unlink(temp)  # the committed target holds the inode; drop the staging name


def write_new(target: Path, data: bytes) -> None:
    """Write-temp-then-atomic-no-replace-commit in one call (§22.3 layer-1 discipline)."""
    commit_new(stage_temp(target, data), target)


def create_exclusive(target: Path, data: bytes) -> None:
    """Atomic create-if-absent: `os.open(O_CREAT|O_EXCL)` (§22.8; claim acquisition, §22.3).

    Raises `FileExistsError` if `target` exists — the caller interprets (for claims:
    somebody holds the lock). Content is written and fsynced on the exclusively-created
    fd; note the create→write window is not atomic (a reader may glimpse an empty file) —
    `pipeline.claims` handles that window conservatively.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, _FILE_MODE)
    try:
        _write_all(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def write_replace(target: Path, data: bytes) -> None:
    """Atomic REPLACING rename (temp + `os.rename`) — for marker/claim-record updates ONLY.

    §21.2/§13.3: a differing folio-marker re-append atomically updates that one marker
    (last-writer-wins, `member-updated`); §22.3: the lease steal replaces a claim record.
    A reader never tears (G1 P3: 1543 concurrent reads, 0 anomalies) — it sees the old or
    the new version, both complete. NEVER use this for outputs: replacing an existing
    output would break the §22.7 existence authority — outputs go through `write_new`.
    """
    target = Path(target)
    temp = stage_temp(target, data)
    os.rename(temp, target)


def append_jsonl_line(path: Path, record: Any) -> None:
    """Append one canonical-JSON record as ONE line via a single `write()` on `O_APPEND` (§13.3).

    Collision-free across processes for short records (G1 P5: 8 procs × 250 lines, zero
    torn); a torn FINAL line (crash mid-write) is discardable by readers per §13.3. The
    single-write discipline is the atomicity contract — a partial write raises loudly.
    """
    line = (canonical_json_str(record) + "\n").encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, _FILE_MODE)
    try:
        written = os.write(fd, line)  # ONE write per line — the §13.3 append discipline
    finally:
        os.close(fd)
    if written != len(line):
        raise StoreWriteError(
            f"store-write-failed: single-write append wrote {written}/{len(line)} bytes "
            f"to {path} — the §13.3 atomic-append contract did not hold"
        )


# ---------------------------------------------------------------------------
# S0's existence half (§22.7): output existence ONLY — no SSOT handle exists.
# ---------------------------------------------------------------------------


def is_done(store: WorkspaceStore, id_str: str) -> bool:
    """Is this id materialized? Output existence ONLY (§22.7 signature scoping).

    Takes exactly the output-store handle and the id — no SSOT handle exists in this
    signature or this module (INV-CORRECTNESS CI teeth land at step 21; the discipline
    starts here). The §7.4 preimage-comparison half of S0 is the spine's (step 21) and
    likewise reads only the output store.
    """
    return store.output_path(id_str).exists()
