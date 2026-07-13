"""Fit resolution (step 26) — PURE plan/coordinate resolution over step-25's fit-bindings.

Design authority: `docs/design.md`
  §21.8 — the **fit-resolution rule (FR2)** and the **`force_reconcile` behavior matrix (FR1)**.
        The FR2 three-row rule over the fit-bindings under prefix `artifact.platform.language`
        and the CURRENT effective reconcile-inputs digest `d`:
          1. some `fit.digest == d`      → **hit** (reuse; baseline or revision alike);
          2. fits nonempty, none match   → serve the **latest-minted** fit + a
             `render-input-mismatch` warn carrying `current_inputs_digest: d` and a
             `force-re-reconcile` remediation (serve the existing bytes, flag the mismatch —
             NEVER a silent re-mint, §3.1);
          3. no fit                      → **miss** → first mint (the unqualified baseline).
        Rule 1 makes a config revert **self-healing**: reverting the platform limit re-selects
        the matching baseline (a hit) — no warn, no re-mint. The `force_reconcile` matrix:
          - no fit  → **baseline** mint (force is a no-op qualifier on a miss);
          - a fit matches current inputs (baseline OR revision) → **no mint**,
            `already-materialized` (idempotent re-issue; n8n-retry-safe);
          - fits exist, none match → mint the **revision fit** `…_<hex12>`, `re-reconciled`.
  §16 — reconcile-split parts are addressed `(deliverable-id, part-id)`; **save-stable**
        ordinals (stable within a saved deliverable, not re-chunk-reproducible, §9.5). The
        ordinal is the part's 1-based position in the fit's IMMUTABLE (content-addressed) parts
        sequence — a pure function of the fit, so a re-save renumbers nothing.
  §22.3 — claims ride the **fitted-id**. Because the fitted-id is content-addressed, two forcers
        with identical inputs compute the SAME fitted-id → the SAME claim key → the no-replace
        create-if-absent admits EXACTLY one winner (B4-4); the loser gets `claim-held`.
  §7.4 — every id is minted via `pipeline.ids` (`fitted_id`, `deliverable_id`, `part_id`,
        `split_part_label`); the fit-revision `_hex12` is the reconcile-inputs digest (§7.4).
  §22.7 (INV-CORRECTNESS / PC12) — both resolution rules are plan/coordinate resolution: they
        read config (the current preimage) + the output store (the fit-bindings) + the claim
        registry, and **NEVER the SSOT**. This module imports no SSOT module.

**Reuse, never reinvent.** The reconcile-inputs preimage + its `hex12` digest ride
`pipeline.reconcile` (`reconcile_inputs_preimage`, `fit_digest`, `RECONCILE_INPUT_COMPONENTS`);
this module never recomputes a digest by hand. The id family rides `pipeline.ids` (never a
hand-rolled id string). The claim/lease primitives ride the step-20 `pipeline.claims`
`ClaimRegistry` — the no-replace commit + holder-checked release (B4-4) are reused, not
reimplemented. Canonical comparison rides `pipeline.canonical`.

**This module carries NO fit internals** (no reshape, no gate, no fidelity check — those are
step 25's `pipeline.reconcile`) and NO spine persistence (S0–S6 is the spine's, step 36). It
RESOLVES over the fit-binding records and decides WHEN to mint (baseline/revision) vs reuse.

Two BINDING carry-forwards from the step-25 review, owned here:

- **obs-3 — scope the reconcile-consumed attributes.** `reconcile.reconcile_inputs_preimage`
  folds ALL of `request.advisory` / `request.render_dims` into the fit preimage, so an
  UNCONSUMED attribute would churn the fit-revision `_hex12` spuriously (§16: "scoped to
  attributes the reconcile pass consumes"). `scope_request` projects both maps down to the
  declared consumed key set BEFORE the request reaches reconcile.
- **obs-1 — fail fast on a non-numeric hard limit.** Reconcile's terminal gate only raises on a
  non-numeric ceiling AFTER a wasted LLM call (on a non-`pass` strategy). `scope_request`
  validates every effective hard limit is numeric first (§16 CA9: a hard limit is a numeric
  ceiling), so the wasted spend never happens.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pipeline import ids, reconcile
from pipeline.canonical import canonical_json_bytes
from pipeline.claims import AcquireOutcome, ClaimRegistry
from pipeline.reconcile import RECONCILE_INPUT_COMPONENTS, ReconcileRequest

__all__ = [
    "CODE_ALREADY_MATERIALIZED",
    "CODE_RENDER_INPUT_MISMATCH",
    "CODE_RE_RECONCILED",
    "DISPOSITION_FORCED_BASELINE",
    "DISPOSITION_FORCED_MATCH",
    "DISPOSITION_FORCED_REVISION",
    "DISPOSITION_HIT",
    "DISPOSITION_MISMATCH",
    "DISPOSITION_MISS",
    "REMEDIATION_FORCE_RE_RECONCILE",
    "FitCoordinate",
    "FitRecord",
    "FitResolution",
    "FitResolutionError",
    "FitWarning",
    "SplitPart",
    "claim_fit",
    "parse_fit_binding",
    "resolve_fit",
    "resolve_force_reconcile",
    "resolved_fitted_id",
    "scope_consumed",
    "scope_request",
    "split_part_addresses",
]

#: §21.7/§22.6 stable codes (REUSED, not new): a forced render resolving to an existing
#: matching fit is `already-materialized`; a forced revision mint is `re-reconciled`; a
#: stale unqualified serve warns `render-input-mismatch` (reconcile-scoped only, §21.8).
CODE_ALREADY_MATERIALIZED = "already-materialized"
CODE_RE_RECONCILED = "re-reconciled"
CODE_RENDER_INPUT_MISMATCH = "render-input-mismatch"

#: §21.8 rule-2 machine remediation: a caller diverts on the token, never the human hint.
REMEDIATION_FORCE_RE_RECONCILE = "force-re-reconcile"

#: The FR2 (non-forced) dispositions (§21.8): a true cache hit, a none-match stale serve, or a
#: no-fit first mint.
DISPOSITION_HIT = "hit"
DISPOSITION_MISMATCH = "mismatch"
DISPOSITION_MISS = "miss"

#: The `force_reconcile` matrix dispositions (§21.8): baseline mint on a miss, no-mint match,
#: or a revision mint on a none-match.
DISPOSITION_FORCED_BASELINE = "forced-baseline"
DISPOSITION_FORCED_MATCH = "forced-match"
DISPOSITION_FORCED_REVISION = "forced-revision"

#: The §7.4 fit-revision qualifier shape (first 12 hex of SHA-256 over the preimage).
_HEX12_RE = re.compile(r"\A[0-9a-f]{12}\Z")


class FitResolutionError(RuntimeError):
    """A fit-resolution WIRING defect — a malformed fit-binding record, a coordinate mismatch,
    a non-numeric hard limit (obs-1 fail-fast), or a split-address misuse. Loud and typed
    (§3.1), never a silent repair. Distinct from a resolution DECISION, which is a typed
    `FitResolution` value, never a raised exception."""

    code = "fit-resolution-error"


# ---------------------------------------------------------------------------
# The fit-binding record view (§16) + the resolution coordinate.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FitCoordinate:
    """The `(artifact-id, platform, language)` triple a fit resolves under (§21.8).

    `artifact_id` is a BARE artifact root (`a-<hex16>`); `platform`/`language` are the fitted
    coordinates the fitted-id extends (§7.4). Validated so a resolution can mint the baseline /
    revision fitted-id from it without a second parse.
    """

    artifact_id: str
    platform: str
    language: str

    def __post_init__(self) -> None:
        try:
            parsed = ids.parse_id(self.artifact_id)
        except ids.IdError as exc:
            raise FitResolutionError(
                f"fit-resolution-error: artifact_id {self.artifact_id!r} is not a valid id ({exc})"
            ) from exc
        if parsed.level != "artifact" or parsed.part is not None:
            raise FitResolutionError(
                f"fit-resolution-error: a fit coordinate needs a BARE artifact root (§7.1), got "
                f"level {parsed.level!r}"
            )


@dataclass(frozen=True)
class FitRecord:
    """A parsed step-25 fit-binding (`reconcile.build_fit_binding` output): the fitted-id, its
    `hex12` reconcile-inputs digest, `minted_ts` (a record field — order lives here, never in
    the id, §21.8), the canonical reconcile-inputs preimage, and the outcome record. The
    matcher reads `digest`; the latest-minted tiebreak reads `(minted_ts, fitted_id)`."""

    fitted_id: str
    digest: str
    minted_ts: str
    preimage: Mapping[str, Any]
    outcome: Mapping[str, Any]


def parse_fit_binding(binding: Mapping[str, Any]) -> FitRecord:
    """Validate one fit-binding dict into a `FitRecord` (loud on a malformed record, §3.1).

    The fitted-id must parse to the fitted level (§7.4); the digest must be a `hex12` string;
    `minted_ts` must be a non-empty string; the preimage must be a mapping. The recorded
    `digest` is TRUSTED as the match key (§21.8 reads `fit.digest`), not recomputed here."""
    if not isinstance(binding, Mapping):
        raise FitResolutionError(
            f"fit-resolution-error: a fit-binding must be a mapping, got {type(binding).__name__}"
        )
    fitted = binding.get("fitted_id")
    if not isinstance(fitted, str) or not fitted:
        raise FitResolutionError("fit-resolution-error: fit-binding is missing a `fitted_id`")
    try:
        parsed = ids.parse_id(fitted)
    except ids.IdError as exc:
        raise FitResolutionError(
            f"fit-resolution-error: fit-binding fitted_id {fitted!r} is not a valid id ({exc})"
        ) from exc
    if parsed.level != "fitted":
        raise FitResolutionError(
            f"fit-resolution-error: a fit-binding names a fitted-level id (§7.1), got level "
            f"{parsed.level!r} in {fitted!r}"
        )
    digest = binding.get("digest")
    if not isinstance(digest, str) or not _HEX12_RE.match(digest):
        raise FitResolutionError(
            f"fit-resolution-error: fit-binding digest must be 12 lowercase hex chars (§7.4), "
            f"got {digest!r}"
        )
    minted_ts = binding.get("minted_ts")
    if not isinstance(minted_ts, str) or not minted_ts:
        raise FitResolutionError(
            f"fit-resolution-error: fit-binding {fitted!r} is missing a `minted_ts` record field"
        )
    preimage = binding.get("preimage")
    if not isinstance(preimage, Mapping):
        raise FitResolutionError(
            f"fit-resolution-error: fit-binding {fitted!r} is missing its reconcile-inputs preimage"
        )
    outcome = binding.get("outcome", {})
    if not isinstance(outcome, Mapping):
        raise FitResolutionError(
            f"fit-resolution-error: fit-binding {fitted!r} `outcome` must be a mapping"
        )
    return FitRecord(
        fitted_id=fitted,
        digest=digest,
        minted_ts=minted_ts,
        preimage=preimage,
        outcome=outcome,
    )


def _parse_records(
    coordinate: FitCoordinate, records: Sequence[Mapping[str, Any]]
) -> tuple[FitRecord, ...]:
    """Parse every fit-binding and CONFIRM each belongs to `coordinate` (§21.8: the fits under
    prefix `artifact.platform.language`). A wrong-coordinate record is a caller wiring defect —
    refused loudly, never silently resolved against the wrong triple."""
    root = ids.parse_id(coordinate.artifact_id).root_hex
    parsed: list[FitRecord] = []
    for raw in records:
        record = parse_fit_binding(raw)
        pid = ids.parse_id(record.fitted_id)
        if (pid.root_hex, pid.platform, pid.language) != (
            root,
            coordinate.platform,
            coordinate.language,
        ):
            raise FitResolutionError(
                f"fit-resolution-error: fit-binding {record.fitted_id!r} is not under the "
                f"resolution coordinate {coordinate.artifact_id}.{coordinate.platform}."
                f"{coordinate.language} (§21.8 resolves within one prefix)"
            )
        parsed.append(record)
    return tuple(parsed)


# ---------------------------------------------------------------------------
# The resolution outcome (both the FR2 rule and the force matrix speak this type).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FitWarning:
    """The §21.8 rule-2 `render-input-mismatch` payload (warn, reconcile-scoped): the stale fit
    served, its recorded digest, the CURRENT inputs digest `d`, which reconcile-input components
    differ, and the `force-re-reconcile` machine remediation. The bytes are returned unchanged
    and the mismatch is never silent (§3.1); the caller can re-issue deterministically (API8)."""

    code: str
    served_fitted_id: str
    served_inputs_digest: str
    current_inputs_digest: str
    differing_components: tuple[str, ...]
    remediation_action: str


@dataclass(frozen=True)
class FitResolution:
    """One fit-resolution decision (§21.8) — a typed value, never an exception.

    `disposition` is the `DISPOSITION_*` row; `forced` distinguishes the FR2 rule from the
    force matrix. `should_mint` + `revision` tell the caller HOW to invoke `reconcile`
    (mint nothing / mint the baseline `revision=False` / mint the revision `revision=True`);
    `selected` is the fit to SERVE on a non-mint disposition (the hit, the latest-minted stale
    fit, or the forced match). `current_inputs_digest` is `d` (§21.8). `warning` carries the
    rule-2 mismatch payload (None on every other disposition). The claim key (§22.3) is
    `resolved_fitted_id(...)`."""

    disposition: str
    forced: bool
    status: Literal["ok", "warn"]
    code: str
    should_mint: bool
    revision: bool
    selected: FitRecord | None
    current_inputs_digest: str
    warning: FitWarning | None = None


def _match(records: Sequence[FitRecord], digest: str) -> FitRecord | None:
    """The fit whose recorded digest equals `digest`, or None (§21.8 rule 1 / force row 2).

    Distinct fits for one triple carry DISTINCT digests by construction (a fit is minted only
    when its digest is new — §21.8), so there is at most one match; a deterministic
    fitted-id sort makes the pick total even against a hypothetically-degenerate store."""
    matches = sorted((r for r in records if r.digest == digest), key=lambda r: r.fitted_id)
    return matches[0] if matches else None


def _latest_minted(records: Sequence[FitRecord]) -> FitRecord:
    """The §21.8 rule-2 latest-minted fit: MAX by `(minted_ts, fitted_id)`.

    `minted_ts` (a same-format UTC ISO-8601 string, so lexicographic == chronological) is the
    primary key; the fitted-id is the deterministic tiebreak that closes the wall-clock hole —
    two fits minted in the SAME instant still resolve to ONE fit (§21.8: "deterministic
    lexicographic-id tiebreak"), so "latest" is a total order, never insertion-order luck."""
    return max(records, key=lambda r: (r.minted_ts, r.fitted_id))


def _differing_components(
    served_preimage: Mapping[str, Any], current_preimage: Mapping[str, Any]
) -> tuple[str, ...]:
    """The `RECONCILE_INPUT_COMPONENTS` whose canonical value differs between the served fit's
    preimage and the current inputs — names the differing inputs for the rule-2 warn (§21.8)."""
    differ: list[str] = []
    for component in RECONCILE_INPUT_COMPONENTS:
        if canonical_json_bytes(served_preimage.get(component)) != canonical_json_bytes(
            current_preimage.get(component)
        ):
            differ.append(component)
    return tuple(differ)


def resolve_fit(
    coordinate: FitCoordinate,
    records: Sequence[Mapping[str, Any]],
    current_preimage: Mapping[str, Any],
) -> FitResolution:
    """The FR2 fit-resolution rule for an UNQUALIFIED (non-forced) render (§21.8).

    `records` are the fit-bindings under the coordinate's prefix (an output-store read, §22.7);
    `current_preimage` is the CURRENT effective reconcile-inputs preimage — the canonical
    `reconcile.reconcile_inputs_preimage` output of the CONSUMED-scoped request (obs-3). Never
    reads the SSOT (§22.7). Returns:
      - **hit** (rule 1): some fit matches `d` → serve it (`should_mint=False`), `ok`, no warn —
        this is what makes a config revert self-healing (the reverted baseline matches again);
      - **miss** (rule 3): no fits → first baseline mint (`should_mint=True, revision=False`);
      - **mismatch** (rule 2): fits exist, none match → serve the LATEST-MINTED fit
        (`should_mint=False`) with a `render-input-mismatch` warn (bytes unchanged, never a
        silent re-mint, §3.1)."""
    fits = _parse_records(coordinate, records)
    current_digest = reconcile.fit_digest(current_preimage)

    match = _match(fits, current_digest)
    if match is not None:
        return FitResolution(
            disposition=DISPOSITION_HIT,
            forced=False,
            status="ok",
            code="ok",
            should_mint=False,
            revision=False,
            selected=match,
            current_inputs_digest=current_digest,
        )
    if not fits:
        return FitResolution(
            disposition=DISPOSITION_MISS,
            forced=False,
            status="ok",
            code="ok",
            should_mint=True,
            revision=False,
            selected=None,
            current_inputs_digest=current_digest,
        )
    latest = _latest_minted(fits)
    warning = FitWarning(
        code=CODE_RENDER_INPUT_MISMATCH,
        served_fitted_id=latest.fitted_id,
        served_inputs_digest=latest.digest,
        current_inputs_digest=current_digest,
        differing_components=_differing_components(latest.preimage, current_preimage),
        remediation_action=REMEDIATION_FORCE_RE_RECONCILE,
    )
    return FitResolution(
        disposition=DISPOSITION_MISMATCH,
        forced=False,
        status="warn",
        code=CODE_RENDER_INPUT_MISMATCH,
        should_mint=False,
        revision=False,
        selected=latest,
        current_inputs_digest=current_digest,
        warning=warning,
    )


def resolve_force_reconcile(
    coordinate: FitCoordinate,
    records: Sequence[Mapping[str, Any]],
    current_preimage: Mapping[str, Any],
) -> FitResolution:
    """The `force_reconcile: true` behavior matrix (§21.8) — the explicit reconcile remedy.

    Same inputs as `resolve_fit`; the force carries NO values (it re-uses the CONFIGURED current
    effective inputs, so `current_preimage` is authoritative). Deterministic + retry-safe:
      - **no fit** → the force is a no-op qualifier on a miss → **baseline** mint
        (`should_mint=True, revision=False`), `ok`;
      - **match** (some fit's inputs equal `d`, baseline OR revision) → **no mint**, return it,
        `already-materialized` (idempotent re-issue / force-after-revert, n8n-retry-safe);
      - **none match** → mint the **revision fit** `…_<hex12>`
        (`should_mint=True, revision=True`), `re-reconciled`.
    Same forced inputs → same `d` → same revision fitted-id → same claim key: PC3 disjointness
    (two forcers → exactly one LLM run) follows by construction (§22.3)."""
    fits = _parse_records(coordinate, records)
    current_digest = reconcile.fit_digest(current_preimage)

    if not fits:
        return FitResolution(
            disposition=DISPOSITION_FORCED_BASELINE,
            forced=True,
            status="ok",
            code="ok",
            should_mint=True,
            revision=False,
            selected=None,
            current_inputs_digest=current_digest,
        )
    match = _match(fits, current_digest)
    if match is not None:
        return FitResolution(
            disposition=DISPOSITION_FORCED_MATCH,
            forced=True,
            status="ok",
            code=CODE_ALREADY_MATERIALIZED,
            should_mint=False,
            revision=False,
            selected=match,
            current_inputs_digest=current_digest,
        )
    return FitResolution(
        disposition=DISPOSITION_FORCED_REVISION,
        forced=True,
        status="ok",
        code=CODE_RE_RECONCILED,
        should_mint=True,
        revision=True,
        selected=None,
        current_inputs_digest=current_digest,
    )


def resolved_fitted_id(resolution: FitResolution, coordinate: FitCoordinate) -> str:
    """The fitted-id this resolution SERVES or MINTS — the §22.3 claim key.

    A non-mint disposition (hit / mismatch / forced-match) serves the `selected` record's id.
    A baseline mint (miss / forced-baseline) is the UNQUALIFIED fitted-id; a revision mint
    (forced-revision) carries the current-inputs `_hex12` (§7.4). Minted via `ids.fitted_id`,
    never hand-rolled — so two forcers with identical inputs compute the IDENTICAL id (§22.3)."""
    if resolution.selected is not None and not resolution.should_mint:
        return resolution.selected.fitted_id
    fit_revision = resolution.current_inputs_digest if resolution.revision else None
    return ids.fitted_id(
        coordinate.artifact_id,
        coordinate.platform,
        coordinate.language,
        fit_revision=fit_revision,
    )


def claim_fit(
    registry: ClaimRegistry, resolution: FitResolution, coordinate: FitCoordinate
) -> AcquireOutcome:
    """Acquire the claim on the resolution's fitted-id before the expensive reconcile (§22.3).

    Thin over the step-20 `ClaimRegistry.acquire` — no new lock logic. The fitted-id is
    content-addressed, so two forcers with identical inputs pass the SAME key to `acquire`; the
    no-replace create-if-absent admits EXACTLY one winner (B4-4), the other gets `claim-held`.
    Meaningful only when `resolution.should_mint` (a serve is read-only, needs no claim)."""
    return registry.acquire(resolved_fitted_id(resolution, coordinate))


# ---------------------------------------------------------------------------
# obs-3 (scope the reconcile-consumed attributes) + obs-1 (numeric hard-limit fail-fast).
# ---------------------------------------------------------------------------


def scope_consumed(values: Mapping[str, Any], consumed_keys: Iterable[str]) -> dict[str, Any]:
    """Project an advisory / render-dim map to ONLY the reconcile-consumed keys (obs-3, §16).

    `reconcile.reconcile_inputs_preimage` folds ALL of `request.advisory` / `request.render_dims`
    into the fit preimage; an unconsumed attribute would churn the fit-revision `_hex12`
    spuriously. A declared-consumed key that is absent (at its default) simply does not appear —
    `delta_vs_floor` would drop it anyway (CA6)."""
    if not isinstance(values, Mapping):
        raise FitResolutionError(
            f"fit-resolution-error: consumed-scoping needs a mapping, got {type(values).__name__}"
        )
    consumed = set()
    for key in consumed_keys:
        if not isinstance(key, str) or not key:
            raise FitResolutionError(
                f"fit-resolution-error: a consumed attribute name must be a non-empty string, "
                f"got {key!r}"
            )
        consumed.add(key)
    return {key: value for key, value in values.items() if key in consumed}


def _validate_hard_limits_numeric(hard_limits: Mapping[str, Any]) -> None:
    """obs-1: every effective hard limit is a numeric ceiling BEFORE reconcile's LLM path.

    Reconcile's terminal gate (`breached_limits`) raises the same defect only AFTER a wasted
    LLM call on a non-`pass` strategy; failing fast here (§16 CA9: a hard limit IS a numeric
    ceiling) spends nothing. `bool` is refused explicitly — `True` is not a ceiling."""
    if not isinstance(hard_limits, Mapping):
        raise FitResolutionError(
            f"fit-resolution-error: hard_limits must be a mapping, got {type(hard_limits).__name__}"
        )
    for name, limit in hard_limits.items():
        if isinstance(limit, bool) or not isinstance(limit, int | float):
            raise FitResolutionError(
                f"fit-resolution-error: hard limit {name!r} must be a numeric ceiling (§16 CA9), "
                f"got {limit!r} — fail fast before the reconcile LLM path (obs-1)"
            )


def scope_request(
    request: ReconcileRequest,
    *,
    consumed_advisory_keys: Iterable[str],
    consumed_render_dim_keys: Iterable[str],
) -> ReconcileRequest:
    """Return a copy of `request` fit for reconcile: advisory + render-dims projected to ONLY the
    consumed keys (obs-3), after fail-fast numeric validation of every hard limit (obs-1).

    Build the `ReconcileRequest` with the FULL M2 advisory / render-dim sets, then scope here:
    the resulting preimage (and thus the fit-revision `_hex12`) reflects the consumed attributes
    ONLY, so an unconsumed-attribute change never churns identity (§16). The excluded/seam fields
    (`serialize_pins`, `presentation_inputs`, `schema_version`, `metadata`, voice/content params)
    are untouched — they never reach the preimage anyway (§16)."""
    _validate_hard_limits_numeric(request.hard_limits)
    return dataclasses.replace(
        request,
        advisory=scope_consumed(request.advisory, consumed_advisory_keys),
        advisory_defaults=scope_consumed(request.advisory_defaults, consumed_advisory_keys),
        render_dims=scope_consumed(request.render_dims, consumed_render_dim_keys),
        render_dim_defaults=scope_consumed(request.render_dim_defaults, consumed_render_dim_keys),
    )


# ---------------------------------------------------------------------------
# Split parts (§16/§9.5): (deliverable-id, part-id) with SAVE-STABLE ordinals.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SplitPart:
    """One reconcile-split part addressed `(deliverable-id, part-id)` (§7.1/§16).

    `ordinal` is the part's 1-based position in the fit's parts sequence; `role` is the part's
    IR role; `part_label` is the `p01…` slug (§7.4, width fixed by the part count); `part_id`
    is the full addressed unit id (`<deliverable-id>~<label>`); `deliverable_id` is the owner.
    The ordinal is SAVE-STABLE: it is a pure function of the immutable (content-addressed) fit,
    so re-saving the same fit renumbers nothing (§9.5 — stable within a saved deliverable)."""

    ordinal: int
    role: str | None
    part_label: str
    part_id: str
    deliverable_id: str


def split_part_addresses(
    fitted_ir: Mapping[str, Any],
    *,
    fitted_id: str,
    output_type: str,
    presentation: str,
    serialize_revision: str | None = None,
) -> tuple[SplitPart, ...]:
    """Address every reconcile-split part of `fitted_ir` as `(deliverable-id, part-id)` (§16).

    The deliverable-id is `ids.deliverable_id(fitted_id, output_type, presentation)` (a fit
    revision / serialize revision carries through, §7.4); each part-id is
    `ids.part_id(deliverable_id, ids.split_part_label(ordinal, count))`. The ordinal is the
    part's 1-based position in the fit's IMMUTABLE parts sequence — SAVE-STABLE by construction
    (§9.5): the fitted IR is content-addressed, so a re-save yields the same parts in the same
    order and the same ordinals. A flat (single-body) fit is not a split — refused loudly."""
    parts = fitted_ir.get("parts")
    if not isinstance(parts, Sequence) or isinstance(parts, str | bytes) or not parts:
        raise FitResolutionError(
            "fit-resolution-error: split addressing needs a fitted IR with a non-empty `parts` "
            "list — a flat (single-body) fit is not a split (§9.5/§16)"
        )
    deliverable = ids.deliverable_id(
        fitted_id, output_type, presentation, serialize_revision=serialize_revision
    )
    count = len(parts)
    addresses: list[SplitPart] = []
    for ordinal, part in enumerate(parts, start=1):
        label = ids.split_part_label(ordinal, count)
        role = part.get("role") if isinstance(part, Mapping) else None
        addresses.append(
            SplitPart(
                ordinal=ordinal,
                role=role,
                part_label=label,
                part_id=ids.part_id(deliverable, label),
                deliverable_id=deliverable,
            )
        )
    return tuple(addresses)
