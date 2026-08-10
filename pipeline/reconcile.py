"""The reconcile pass (pass 1) core — PURE fit machinery (§16) — plan step 25.

Design authority: `docs/design.md`
  §16 — the reconcile pass. Consumes IR-canonical + one `(platform, language)` target + the
        effective constraints (advisory values from M2; the hard limits from the platform
        entry) + the reconcile-strategy selection (`adapt | split | pass | truncate`, §12.3)
        + the voice/content parameters to preserve; produces a persisted IR-fitted variant
        per `fitted-id`. **Internal ordering is FIXED (RI5):** (1) localize [DEFERRED slot,
        designed] → (2) reshape per strategy → (3) the TERMINAL hard-limit gate, which runs
        LAST (localization/reshape alter length) and is **fit-or-block, never silent-pass**
        (CA9): unfittable content BLOCKS that deliverable (`hard-limit-exceeded`, §21.7)
        while other fanout items continue (the §6.4 block-and-report pattern). The **pass-1
        fidelity constraint** (RI3-fidelity): preserve (i) voice/content parameters, (ii)
        meaning, (iii) the per-claim provenance/tier bindings re-anchored onto the fitted
        text — never promote a tier (§6.5). The **reconcile-inputs preimage** + the
        **fit-binding** (below). The **no-op path**: language matches, nothing breaches,
        capabilities match, no reshape requested → pass 1 skipped, IR-fitted ≡ IR-canonical,
        ZERO LLM cost.
  §7.4 — the fit-revision qualifier: a `_hex12` on the LANGUAGE segment of the fitted-id,
        where `hex12` = the first 12 hex of SHA-256 over the reconcile-inputs preimage. The
        fitted-id is minted via `pipeline.ids.fitted_id` (never hand-rolled); baseline
        (never-forced) fits are byte-identical to the unqualified template.
  §12.3 — the reshape-strategy set + its L0 schema floor `adapt`; the strategy is user
        config the system executes and records (never switches on its own).
  §21.7 — the pinned block code `hard-limit-exceeded` (block, §16), carried as a typed
        module constant here (the drift.py `CODE_*` pattern).

**Reuse, never reinvent.** Fidelity validation rides `pipeline.ir` — `extract_fact_refs`
(balanced-bracket-aware), `validate_refs`/`validate_ir` (structural + tier machinery), and
the typed errors `TierViolation`/`UnknownFactError`/`SchemaViolation`. The id family rides
`pipeline.ids` (`fitted_id` + the `fit_revision` qualifier, `delta_vs_floor`); digests ride
`pipeline.canonical` (`digest_hex12` for the preimage/qualifier); the reconciler LLM call
rides `pipeline.transport` (`invoke_headless`, MOCKED in tests via an injected `runner`).
This module imports NO SSOT module (INV-CORRECTNESS, §22.7).

**The step-26 seam (clean, deliberate).** This module exposes ONLY pure fit machinery:
preimage/digest computation, fitted-IR production, fit-binding records, and fidelity
validation. It carries NO resolution rules, NO claims, NO spine persistence, and NO
FR2/force_reconcile logic — those layer OVER these records at step 26. The `revision` flag
is the one seam parameter step 26 sets (it computes the FR2 hit/miss decision and asks this
module to mint the baseline or the revision fitted-id); this module never decides it.

In-latitude decisions (step-25 coder; grounded in the report):

- **The reconcile-inputs preimage carries EXACTLY the §16 four-component INCLUSION set**
  (`RECONCILE_INPUT_COMPONENTS`), each delta-vs-floor (CA6 zero-churn — an additively
  shipped constraint attribute at its default churns nothing), and EXCLUDES EXACTLY the
  §16 seven-item list (`RECONCILE_INPUT_EXCLUSIONS`). The excluded items are either absent
  from the preimage constructor's inputs by construction (`platform`/`language` are minting
  coordinates, not preimage inputs; `serialize_pins`/`presentation_inputs` are deliverable-
  level per §17) or refused as identity inputs by `ids.delta_vs_floor` (`schema_version`/
  `metadata`, §7.3). `ReconcileRequest` carries the excluded items so the acceptance test
  can prove — over concrete sentinel values — that none reach the preimage bytes.
- **`minted_ts` is a RECORD field ONLY.** It never enters the preimage or the digest and so
  never touches the fitted-id — identity is byte-reproducible across runs (no wall-clock in
  identity). It rides the fit-binding as provenance and nothing more.
- **The fitted IR is a validate_ir-compatible IR envelope with RESHAPED leaves** — the same
  composition `binding` (the artifact-id is unchanged; reconcile fits, it does not
  re-compose), the same grounding ledger (provenance intact), the same stamps — so the
  fidelity check reuses `ir.validate_ir` wholesale (structural + tier promotion + unknown
  fact) and adds only the §16 COVERAGE checks it cannot express: every ledger fact present
  inline OR explicitly dropped-as-lead (a silent drop is rejected), and the voice/content
  params echoed. The `fit-binding` is a SEPARATE record (the persisted IR-fitted envelope
  carries it as a sibling key — that assembly is step 26's persistence concern, not a fit
  internal), so `fitted_ir` stays byte-identical to the canonical on the no-op path.
- **`pass` is the only never-LLM strategy.** Reshape is "requested" for `adapt`/`split`/
  `truncate` (they always invoke the reconciler); `pass` reshapes nothing — it either
  no-ops (fits, language matches → bit-identical, zero LLM) or is blocked by the terminal
  gate (breaches → `hard-limit-exceeded`, still zero LLM). The deliverable-level split-part
  `(deliverable-id, part-id)` addressing of a `split` fit is step 26; step 25's `split`
  reshapes leaf CONTENT within the existing part topology and records the strategy.
- **The hard-limit gate is measurement-pluggable.** `default_measure` scores total leaf-body
  length under `max_chars`; a caller injects a platform-driven measurer (step 27+) without
  touching the gate. The gate compares only limit names present in BOTH the effective
  hard-limit set and the measurement.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pipeline import ir
from pipeline.canonical import canonical_json_bytes, canonical_json_str, digest_hex12
from pipeline.ids import IdError, delta_vs_floor, fitted_id
from pipeline.outline import normalize_outline
from pipeline.prompts import load_template
from pipeline.sections import (
    AXIS_ROLE,
    AXIS_TYPE,
    SEVERITY_ERROR,
    Count,
    Length,
    Order,
    Presence,
    Schema,
    Section,
    SectionGrammarError,
    Violation,
    check_conformance,
    parse_sections,
    reconstruct_rule,
)
from pipeline.transport import Runner, TransportPlan, TransportResult, invoke_headless

__all__ = [
    "CODE_CITATION_NOT_PRESERVED",
    "CODE_FIDELITY_VIOLATION",
    "CODE_HARD_LIMIT_EXCEEDED",
    "CODE_SECTION_CONFORMANCE_VIOLATION",
    "CODE_STRUCTURE_NOT_PRESERVED",
    "DEFAULT_CHAR_LIMIT_KEY",
    "DEFAULT_MAX_ATTEMPTS",
    "RECONCILER_TEMPLATE",
    "RECONCILE_INPUT_COMPONENTS",
    "RECONCILE_INPUT_EXCLUSIONS",
    "RECONCILE_STRATEGIES",
    "RECONCILE_STRATEGY_FLOOR",
    "CitationPreservationViolation",
    "FidelityViolation",
    "ReconcileError",
    "ReconcileOutcome",
    "ReconcileRequest",
    "StructuralPreservationViolation",
    "breached_limits",
    "build_fit_binding",
    "build_reconciler_prompt",
    "default_measure",
    "fit_digest",
    "parse_reconciler_output",
    "reconcile",
    "reconcile_inputs_preimage",
    "validate_citation_preservation",
    "validate_fidelity",
    "validate_structural_preservation",
]

#: §12.3 — the reshape-strategy set. `pass` is the never-LLM strategy (no-op or block only).
RECONCILE_STRATEGIES = ("adapt", "split", "pass", "truncate")

#: §12.3 — the single-attribute schema floor (L0). A strategy at the floor churns no id
#: (delta-vs-floor, CA6), so a baseline `adapt` fit contributes nothing to the preimage.
RECONCILE_STRATEGY_FLOOR = "adapt"

#: §16 / DR-4 C8 — the reconcile-inputs preimage's five INCLUSION components (delta-vs-floor each).
#: (1) the effective reconcile-strategy; (2) the platform entry's effective hard-limit set;
#: (3) the effective advisory constraint values bound at M2-render, scoped to the attributes
#: the reconcile pass consumes; (4) any other reconcile-consumed rendering-dimension binding;
#: (5) this artifact's pinned-format `format_structural` venue tightening — the HARD structural
#: class, sibling of `hard-limits`. Component (5) is OMIT-WHEN-FLOOR: a floor `{}` value produces
#: NO `structural` key at all, so every floor platform's preimage/`fit_digest` is byte-identical to
#: the pre-C8 four-key preimage (the golden fit-digest corpus is unperturbed); only a non-floor
#: venue tightening adds the key and churns identity.
RECONCILE_INPUT_COMPONENTS = ("strategy", "hard-limits", "advisory", "render-dims", "structural")

#: §16 — EXCLUDED from the reconcile-inputs preimage, EXACTLY (each already identity-covered
#: or identity-irrelevant). Enumerated so the acceptance test proves the exclusion set is
#: neither wider nor narrower than the design's.
RECONCILE_INPUT_EXCLUSIONS = (
    "voice/content parameters to preserve (fixed by artifact-id, §7.2)",
    "platform (a coordinate, not a preimage input)",
    "language (a coordinate, not a preimage input)",
    "serialize-side pins (deliverable-level, §17)",
    "Presentation inputs (deliverable-level, §17)",
    "schema_version (§7.3 — never an identity input)",
    "the metadata bag (§7.3 — never an identity input)",
)

#: The reconciler prompt-template name (`pipeline/prompts/reconciler.md`, §16 contract; T9).
RECONCILER_TEMPLATE = "reconciler"

#: §21.9-style bounded re-ask limit — one initial ask + two corrective re-asks. The
#: reconciler LLM path owns the ONLY re-ask; a persistently-infidelitous fit past this bound
#: is caught and NEVER fitted (`CODE_FIDELITY_VIOLATION`). Mirrors compose (§15).
DEFAULT_MAX_ATTEMPTS = 3

#: §21.7 pinned code: content that cannot be made to fit a hard limit BLOCKS the deliverable
#: (block, §16). A typed module constant (the drift.py `CODE_*` pattern), never inlined.
CODE_HARD_LIMIT_EXCEEDED = "hard-limit-exceeded"

#: DR-4 C8 §15/§16 pinned block code: the FITTED body violates the selected venue's HARD
#: `format_structural` section contract (a required/forbidden/ordered/count/length rule at ERROR
#: severity) — the deliverable is BLOCKED at the TERMINAL structural gate (block, §16), siblings
#: continue (§6.4). The SAME string as `pipeline.api.results.CODE_SECTION_CONFORMANCE_VIOLATION` (a
#: `("block",)`/TIER_GENERATION code the driver's `stage_code` guard threads unchanged via
#: `ALL_CODES`), carried here as a typed module constant (the drift.py `CODE_*` pattern) so this
#: pure fit core imports no §21.7 taxonomy module — neither directly nor transitively: the venue
#: schema is decoded through `sections.reconstruct_rule` (R1: the shared C2-vocabulary home, NOT
#: compose), so this module does not import `pipeline.compose` at all and never reaches
#: `pipeline.api.results`. DISTINCT from `CODE_STRUCTURE_NOT_PRESERVED` (the C7 preserve/no-mint
#: re-ask code) and `CODE_FIDELITY_VIOLATION` (the coverage/echo re-ask code):
#: those two ride the bounded fidelity re-ask, THIS one is the terminal block-and-report verdict.
CODE_SECTION_CONFORMANCE_VIOLATION = "section-conformance-violation"

#: A §21.7-style internal code (the compose `compose-contract-violation` sibling): the
#: reconciler never produced a fidelity-valid fit within the re-ask bound — NEVER fitted.
CODE_FIDELITY_VIOLATION = "fit-fidelity-violation"

#: DR-4 C7 — a §16 preserve-section-keys breach: the fit dropped/renamed a schema-referenced
#: (non-forbidden) section the compose declared, OR MINTED a schema-satisfying section absent at
#: compose (GAP-2 no-mint). A DISTINCT code from `CODE_FIDELITY_VIOLATION` (the coverage/echo
#: contract) and from C8's TERMINAL `CODE_SECTION_CONFORMANCE_VIOLATION` block code — this one
#: first-remediates via the SAME bounded re-ask (an `ir.IRError`), and C8's distinct terminal
#: structural gate is the block-and-report layer. It never appears on a `ReconcileOutcome.code` (a
#: persistent breach exhausts the re-ask bound and surfaces as `CODE_FIDELITY_VIOLATION`, never
#: fitted).
CODE_STRUCTURE_NOT_PRESERVED = "structure-not-preserved"

#: DR-5 C8 — a §16 preserve-citation-keys breach: the fit MINTED an inline Pandoc `[@key]` absent
#: from the composed body (a new key) OR MANGLED an existing key into a different one (`[@key]`→
#: `[@keytypo]`) — either ships an UNRESOLVABLE citation. The citation analog of C7's
#: `CODE_STRUCTURE_NOT_PRESERVED`; the fabrication half (an unresolvable `[@key]` against the
#: projected reference set) is C4's COMPOSE-locus job. A DISTINCT code from both C7's
#: `structure-not-preserved` (the section-key preserve) and `CODE_FIDELITY_VIOLATION` (the
#: coverage/echo contract): all three ride the SAME bounded fidelity re-ask (an `ir.IRError`); a
#: persistent breach exhausts the bound and surfaces as `CODE_FIDELITY_VIOLATION`, never on a
#: `ReconcileOutcome.code` and never a `pipeline.api.results` taxonomy code (this pure fit core
#: imports no §21.7 taxonomy module). Per D7 = SUBSET-only (S5) a citation DROP (fitted ⊆ composed)
#: is PERMITTED — a benign orphaned reference; only a fitted key NOT in the composed set breaches.
CODE_CITATION_NOT_PRESERVED = "citation-not-preserved"

#: `default_measure`'s single hard-limit key — total leaf-body character length. A caller
#: injects a richer measurer (per-platform limits) without touching the gate.
DEFAULT_CHAR_LIMIT_KEY = "max_chars"

#: A fenced code block (``` or ```json) — the common wrapper an LLM puts around JSON.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


class ReconcileError(RuntimeError):
    """A reconcile-stage WIRING defect (bad strategy, an IR/artifact-id mismatch, a malformed
    request) — loud, typed, never a re-ask and never silent (§3.1). Distinct from a reconciler
    CONTRACT/fidelity failure, which is a typed `ReconcileOutcome`, not an exception."""

    code = "reconcile-error"


class FidelityViolation(ir.IRError):
    """A §16 fidelity breach the reused `ir.validate_ir` cannot express on its own: a ledger
    fact silently dropped (present in the ledger, neither cited inline nor listed as an
    explicit drop-as-lead), a fact both cited AND dropped, a drop of a non-ledger fact-id, or
    a voice/content parameter the reconciler failed to echo. A subclass of `ir.IRError` so it
    rides the SAME bounded-re-ask catch as a tier promotion / unknown fact (§16)."""

    code = CODE_FIDELITY_VIOLATION


class StructuralPreservationViolation(ir.IRError):
    """A §16/DR-4 C7 preserve-section-keys breach, scoped to the keys the IR's resolved
    `section_conformance` base schema references: a schema-referenced section the compose
    declared that the fit DROPPED/renamed without a venue-forbid (preserve-through), or a
    schema-satisfying section the fit MINTED from content absent at compose (GAP-2 no-mint).
    A subclass of `ir.IRError` — a DISTINCT `code` from `FidelityViolation` — so a breach rides
    the SAME bounded fidelity re-ask (§16); a persistent breach exhausts the bound and is NEVER
    fitted (surfacing as `CODE_FIDELITY_VIOLATION`). C8's terminal structural gate + its
    `section-conformance-violation` block-and-report layer over this same distinct code."""

    code = CODE_STRUCTURE_NOT_PRESERVED


class CitationPreservationViolation(ir.IRError):
    """A §16/DR-5 C8 preserve-citation-keys breach: the reshape introduced an inline Pandoc `[@key]`
    NOT in the composed body's citation set — a MINT of a new key or a MANGLE of an existing key
    into a different (unresolvable) one. Per D7 = SUBSET-only (S5) a citation DROP is PERMITTED
    (fitted ⊆ composed — a benign orphaned reference); only `fitted ⊄ composed` breaches. A subclass
    of `ir.IRError` — a DISTINCT `code` from `FidelityViolation`/`StructuralPreservationViolation` —
    so a breach rides the SAME bounded fidelity re-ask (§16); a persistent breach exhausts the bound
    and is NEVER fitted (surfacing as `CODE_FIDELITY_VIOLATION`). The citation analog of C7's
    `StructuralPreservationViolation`; the fabrication half (an unresolvable key against the
    projected reference set) is C4's COMPOSE-locus resolution, not this reshape-preserve check."""

    code = CODE_CITATION_NOT_PRESERVED


# ---------------------------------------------------------------------------
# The reconcile request + outcome (§16 inputs/results).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileRequest:
    """One fit's inputs — the §16 consume set, plus the excluded items carried for the seam.

    `canonical_ir` is a validate_ir-valid IR-canonical envelope (from compose, §15);
    `artifact_id` MUST equal its composition binding's id (a fit does not re-compose).
    `platform`/`language` are the target coordinates the fitted-id extends (§7.4);
    `source_language` is the IR's own language, the localize seam's comparand (§16 step 1).
    `strategy` ∈ `RECONCILE_STRATEGIES` (§12.3). The `*_defaults` maps supply the schema floors
    for delta-vs-floor (CA6). `voice_content_params` is the §16 preserve set — EXCLUDED from the
    preimage (fixed by artifact-id, §7.2) but echoed by the reconciler.

    `format_structural` / `format_structural_defaults` (DR-4 C6/C7/C8) carry the per-format HARD
    structural tightening — `{format_id: <C2 section-conformance schema list>}` exactly as the
    Platform attribute stores it — SINGLE-ENTRY scoped to THIS artifact's format (the driver
    threads only the pinned format so an unrelated venue never churns this fit's identity). They
    are LIVE at C8 on TWO seams: (i) C7's preserve-through check reads their venue-forbids, and
    (ii) they are the 5th OMIT-WHEN-FLOOR reconcile-inputs preimage component (a HARD class, the
    sibling of `hard_limits`) AND the reconstructed schema the TERMINAL structural gate enforces.
    An empty map / no entry ⇒ no venue tightening: no preimage `structural` key (byte-identical
    `fit_digest`) and an INERT gate.

    The trailing four fields are EXCLUDED from the reconcile-inputs preimage (§16) and are
    carried only so a caller assembling the full render context has one home for them — and
    so the acceptance test can prove, over concrete values, that none reach the preimage.
    """

    canonical_ir: Mapping[str, Any]
    artifact_id: str
    platform: str
    language: str
    source_language: str
    strategy: str
    hard_limits: Mapping[str, Any] = field(default_factory=dict)
    hard_limit_defaults: Mapping[str, Any] = field(default_factory=dict)
    advisory: Mapping[str, Any] = field(default_factory=dict)
    advisory_defaults: Mapping[str, Any] = field(default_factory=dict)
    render_dims: Mapping[str, Any] = field(default_factory=dict)
    render_dim_defaults: Mapping[str, Any] = field(default_factory=dict)
    # DR-4 C6/C7/C8 per-format HARD structural tightening — a delta-vs-floor CONSUMED pair, LIVE at
    # C8: it is the 5th OMIT-WHEN-FLOOR preimage component, the TERMINAL structural gate's schema,
    # and C7's preserve-through venue-forbids source (pinned to THIS artifact's format only).
    format_structural: Mapping[str, Any] = field(default_factory=dict)
    format_structural_defaults: Mapping[str, Any] = field(default_factory=dict)
    voice_content_params: Mapping[str, Any] = field(default_factory=dict)
    strategy_default: str = RECONCILE_STRATEGY_FLOOR
    # --- EXCLUDED from the reconcile-inputs preimage (§16); never read by it ---
    serialize_pins: Mapping[str, Any] = field(default_factory=dict)
    presentation_inputs: Mapping[str, Any] = field(default_factory=dict)
    schema_version: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReconcileOutcome:
    """One fit result — a typed outcome, never a raised exception for a reconciler defect.

    `status`/`code`: `ok`/`ok` (fitted — including the no-op passthrough), `block`/
    `hard-limit-exceeded` (unfittable — the deliverable is blocked, siblings continue, §16),
    `error`/`fit-fidelity-violation` (the reconciler never produced a fidelity-valid fit
    within the re-ask bound — NEVER fitted), or `error`/<transport code> (a transport-level
    failure surfaced verbatim). `fitted_ir` is the reshaped IR envelope on `ok` (None
    otherwise); `fit_binding` is the §16 record on `ok` (None otherwise); `preimage`/`digest`
    are always present (computed before the gate). `is_noop` marks the zero-LLM passthrough;
    `dropped_facts` is the explicit drop-as-lead set; `blocked_limits` names the breached
    hard limits on a `block`; `structural_violations` names the FITTED body's HARD venue
    `format_structural` breaches on a `block` (DR-4 C8 — DISTINCT from the fidelity `violations`
    field: those are the bounded-re-ask fidelity/coverage strings, these are the terminal
    structural gate's error-severity venue breaches, and a JOINT structural+limit block populates
    BOTH `structural_violations` AND `blocked_limits`); `attempts` counts reconciler invocations
    (0 on the no-op/pass paths); `transport_result` is the last transport outcome (None when no
    LLM ran)."""

    status: Literal["ok", "block", "error"]
    code: str
    fitted_id: str | None
    fitted_ir: Mapping[str, Any] | None
    fit_binding: Mapping[str, Any] | None
    preimage: Mapping[str, Any]
    digest: str
    is_noop: bool
    dropped_facts: tuple[str, ...]
    blocked_limits: tuple[str, ...]
    structural_violations: tuple[str, ...]
    attempts: int
    violations: tuple[str, ...]
    transport_result: TransportResult | None


# ---------------------------------------------------------------------------
# The reconcile-inputs preimage (§16 / §7.4) + its hex12 digest (the fit-revision qualifier).
# ---------------------------------------------------------------------------


def reconcile_inputs_preimage(request: ReconcileRequest) -> dict[str, Any]:
    """Build the canonical §16 reconcile-inputs preimage (delta-vs-floor per CA6).

    Comprises the five `RECONCILE_INPUT_COMPONENTS` — (1) the effective strategy, (2) the
    effective hard-limit set, (3) the reconcile-consumed advisory bindings, (4) any other
    reconcile-consumed render-dim binding, and (5) this artifact's pinned-format
    `format_structural` venue tightening — each reduced to its deviation from the schema floor (an
    attribute at its default is ABSENT, so an additively shipped constraint at its default churns
    nothing). Component (5) is OMIT-WHEN-FLOOR: a floor `{}` `format_structural` yields an empty
    delta and NO `structural` key at all, so a floor platform's preimage is byte-identical to the
    pre-C8 four-key preimage (the golden `fit_digest` corpus is unperturbed); only a non-floor venue
    tightening adds the key. EXCLUDES EXACTLY `RECONCILE_INPUT_EXCLUSIONS`: the excluded items are
    never read here (`platform`/`language` are minting coordinates;
    `voice_content_params`/`serialize_pins`/`presentation_inputs`/`schema_version`/`metadata` are
    separate request fields), and `delta_vs_floor` independently refuses the §7.3 keys. The returned
    value is the canonical pure-JSON object — exactly what the fit-binding records and the §22.3 S0
    preimage check reads back. `minted_ts` is NOT part of it."""
    preimage: dict[str, Any] = {
        "strategy": delta_vs_floor(
            {"strategy": request.strategy},
            {"strategy": request.strategy_default},
            where="strategy",
        ),
        "hard-limits": delta_vs_floor(
            request.hard_limits, request.hard_limit_defaults, where="hard-limits"
        ),
        "advisory": delta_vs_floor(request.advisory, request.advisory_defaults, where="advisory"),
        "render-dims": delta_vs_floor(
            request.render_dims, request.render_dim_defaults, where="render-dims"
        ),
    }
    # (5) OMIT-WHEN-FLOOR: a floor `{}` `format_structural` produces an empty delta, so the guard
    # drops the `structural` key ENTIRELY — the byte-identity every floor platform depends on.
    structural = delta_vs_floor(
        request.format_structural, request.format_structural_defaults, where="structural"
    )
    if structural:
        preimage["structural"] = structural
    # Total-construction: every value above was vetted by delta_vs_floor; the round-trip makes
    # the returned preimage its own canonical pure-JSON value (mirrors ids.build_artifact_preimage).
    return json.loads(canonical_json_str(preimage))


def fit_digest(preimage: Mapping[str, Any]) -> str:
    """The `hex12` fit-revision qualifier: first 12 hex of SHA-256 over the reconcile-inputs
    preimage (§7.4). Deterministic — the SAME preimage always yields the SAME qualifier, and
    `minted_ts` is excluded by construction (it never enters the preimage)."""
    return digest_hex12(preimage)


# ---------------------------------------------------------------------------
# The terminal hard-limit gate (§16 step 3): measurement-pluggable, fit-or-block.
# ---------------------------------------------------------------------------

#: A measurer scores a fitted IR envelope into `{limit-name: measured-value}` (§16 gate).
Measurer = Callable[[Mapping[str, Any]], Mapping[str, float]]


def _is_flat(ir_doc: Mapping[str, Any]) -> bool:
    """§15 flat-body collapse: a canonical/fitted IR carries `body` XOR `parts`."""
    return "body" in ir_doc


def _iter_leaves(ir_doc: Mapping[str, Any]):
    """Yield `(where, body)` for every Markdown leaf of an IR envelope (flat or parts)."""
    if _is_flat(ir_doc):
        yield "body", ir_doc["body"]
        return
    for index, part in enumerate(ir_doc.get("parts", ())):
        yield f"parts[{index}].body", part.get("body", "")


def default_measure(ir_doc: Mapping[str, Any]) -> dict[str, float]:
    """The default gate measurement: total leaf-body character length under `max_chars`.

    A working, fully-testable default; a caller injects a platform-driven measurer (per-format
    word/slide/section limits, step 27+) that returns richer keys without touching the gate."""
    total = sum(len(body) for _, body in _iter_leaves(ir_doc))
    return {DEFAULT_CHAR_LIMIT_KEY: float(total)}


def breached_limits(
    fitted_ir: Mapping[str, Any],
    hard_limits: Mapping[str, Any],
    *,
    measure: Measurer = default_measure,
) -> tuple[str, ...]:
    """The names of every hard limit the fitted IR breaches (§16 CA9), sorted.

    Compares only limit names present in BOTH the effective hard-limit set and the
    measurement — an advisory-only or unmeasured attribute never blocks (advisory norms only
    warn, §3.1). A breach is `measured > limit` for numeric limits; a non-numeric limit is a
    wiring defect (loud `ReconcileError`), never a silent pass."""
    measured = measure(fitted_ir)
    breached: list[str] = []
    for name, limit in hard_limits.items():
        if name not in measured:
            continue
        if isinstance(limit, bool) or not isinstance(limit, int | float):
            raise ReconcileError(
                f"reconcile-error: hard limit {name!r} must be a numeric ceiling for the gate "
                f"(§16 CA9), got {limit!r}"
            )
        if measured[name] > limit:
            breached.append(name)
    return tuple(sorted(breached))


# ---------------------------------------------------------------------------
# The fidelity contract (§16) — REUSE ir.validate_ir, add the §16 coverage checks.
# ---------------------------------------------------------------------------


def _referenced_fact_ids(fitted_ir: Mapping[str, Any]) -> set[str]:
    """Every fact-id cited inline across the fitted IR's leaves (via ir.extract_fact_refs — the
    balanced-bracket-aware parser; NEVER a second parser)."""
    cited: set[str] = set()
    for where, body in _iter_leaves(fitted_ir):
        for ref in ir.extract_fact_refs(body, where=where):
            cited.add(ref.fact_id)
    return cited


def validate_fidelity(
    fitted_ir: Mapping[str, Any],
    *,
    dropped_facts: Sequence[str],
    voice_content_echo: Mapping[str, Any],
    voice_content_params: Mapping[str, Any],
) -> None:
    """The §16 fidelity contract on an ALREADY-`validate_ir`-valid fitted IR.

    `ir.validate_ir` (run by `_assemble_fitted_ir` before this) already caught tier promotion
    and unknown inline fact-ids (the tier machinery reused, §6.5). This adds the two §16
    COVERAGE checks it cannot express on its own:

    1. **Every ledger fact-id is present inline OR explicitly dropped-as-lead.** A ledger fact
       neither cited nor listed in `dropped_facts` is a SILENT DROP — rejected (§16). A dropped
       id must name a real ledger fact, and a fact cannot be both cited and dropped.
    2. **The voice/content parameters are echoed.** Every preserve-param key must appear in
       `voice_content_echo` with a byte-equal (canonical) value — the reconciler's confirmation
       that it saw and preserved them (§16 fidelity constraint (i)).

    Raises `FidelityViolation` (an `ir.IRError`) on any breach, so it rides the same bounded
    re-ask as a tier promotion."""
    ledger = set(fitted_ir.get("grounding", {}))
    cited = _referenced_fact_ids(fitted_ir)
    dropped = set(dropped_facts)

    unknown_dropped = dropped - ledger
    if unknown_dropped:
        raise FidelityViolation(
            f"fit-fidelity-violation: dropped_facts names fact-id(s) {sorted(unknown_dropped)} "
            "absent from the grounding ledger — only a real ledger fact may be dropped-as-lead "
            "(§16)"
        )
    both = cited & dropped
    if both:
        raise FidelityViolation(
            f"fit-fidelity-violation: fact-id(s) {sorted(both)} are BOTH cited inline and listed "
            "as dropped-as-lead — a fit either re-anchors a fact or drops it, never both (§16)"
        )
    silently_dropped = ledger - cited - dropped
    if silently_dropped:
        raise FidelityViolation(
            f"fit-fidelity-violation: ledger fact-id(s) {sorted(silently_dropped)} are neither "
            "re-anchored inline nor listed in dropped_facts — a SILENT drop blinds the "
            "deliverable review's grounding re-check (§16/§19); drop-as-lead must be explicit"
        )
    for key, value in voice_content_params.items():
        if key not in voice_content_echo:
            raise FidelityViolation(
                f"fit-fidelity-violation: the reconciler did not echo voice/content parameter "
                f"{key!r} — every preserve-parameter must be echoed (§16 fidelity (i))"
            )
        if canonical_json_bytes(voice_content_echo[key]) != canonical_json_bytes(value):
            raise FidelityViolation(
                f"fit-fidelity-violation: voice/content parameter {key!r} was echoed as "
                f"{voice_content_echo[key]!r} but must be preserved as {value!r} (§16 fidelity (i))"
            )


# ---------------------------------------------------------------------------
# The preserve-section-keys contract (§16 / DR-4 C7) — REUSE compose's C1 parse path, add the
# preserve-through + no-mint (GAP-2) coverage the reshape (whole-leaf-body swap) cannot preserve
# mechanically. SCOPED to the keys the IR's resolved C4 `section_conformance` base schema
# references — a global `fitted ⊆ composed` would regress every plain-outline adapt/split.
# ---------------------------------------------------------------------------


def _parse_body_sections(ir_doc: Mapping[str, Any]) -> tuple[Section, ...]:
    """Parse EVERY Markdown leaf of an IR envelope into its C1 heading-sections, via compose's
    EXACT parse path — `parse_sections(normalize_outline(body))` — so the composed body and the
    fitted body key their sections IDENTICALLY (never a forked parser). Flat or parts (iterates
    the leaves like `_iter_leaves`). Propagates `SectionGrammarError`: a FITTED-body derail (an
    unknown section `type=`) is a writer-correctable content defect the CALLER feeds to the SAME
    bounded re-ask compose.py uses at its base gate; a composed body carries a compose-gated
    skeleton so it does not raise in practice. This shared parse is what C8's terminal structural
    gate reuses on the already-parsed FITTED sections (no double-parse)."""
    sections: list[Section] = []
    for _where, body in _iter_leaves(ir_doc):
        sections.extend(parse_sections(normalize_outline(body)))
    return tuple(sections)


def _schema_referenced_keys(canonical_ir: Mapping[str, Any]) -> set[tuple[str, str]]:
    """The `(axis, value)` selector keys the IR's RESOLVED `section_conformance` base schema
    references (DR-4 C4). Reads the serialized C2 rule maps (the `sections.reconstruct_rule`
    shape, already `validate_ir`-shape-checked): `presence`/`count`/`length` carry `(axis, value)`;
    an `order` rule carries a list of `{axis, value}` selectors. EMPTY/ABSENT ⇒ NO schema-
    referenced keys ⇒ the whole preserve/no-mint check is INERT (every reconcile path stays
    byte-unchanged — no-op safety)."""
    keys: set[tuple[str, str]] = set()
    for rule in canonical_ir.get("section_conformance", ()):
        if not isinstance(rule, Mapping):
            continue  # pragma: no cover — validate_ir already shape-checked every rule
        if rule.get("rule") == "order":
            for sel in rule.get("selectors", ()):
                if isinstance(sel, Mapping) and "axis" in sel and "value" in sel:
                    keys.add((sel["axis"], sel["value"]))
        elif "axis" in rule and "value" in rule:
            keys.add((rule["axis"], rule["value"]))
    return keys


def _has_section_key(sections: Sequence[Section], axis: str, value: str) -> bool:
    """True iff some parsed section bears `value` on the selected axis (the C2 `Selector.matches`
    predicate, inlined to avoid re-validating a `type` selector against the carrier — the keys
    come from an already-validated `section_conformance` and the fitted `type`s from
    `parse_sections`, both carrier-clean)."""
    if axis == AXIS_ROLE:
        return any(section.role == value for section in sections)
    if axis == AXIS_TYPE:
        return any(section.type == value for section in sections)
    return False  # pragma: no cover — validate_ir refuses any axis outside {role, type}


def _format_forbids(request: ReconcileRequest, axis: str, value: str) -> bool:
    """True iff THIS artifact's format's `format_structural` schema declares a `presence`
    rule with `required: false` for the `(axis, value)` key — a venue-FORBID, the ONE legitimate
    reason a composed schema-referenced section may be dropped by the fit (DR-4 C7). The
    format-id is the composition preimage's bound format entry; an empty map / no entry for this
    format ⇒ no forbids. (C8 threads ONLY this artifact's pinned-format tightening so an unrelated
    format's venue-forbid never churns this fit's identity.)"""
    format_id = (
        request.canonical_ir.get("binding", {})
        .get("preimage", {})
        .get("dimensions", {})
        .get("format", {})
        .get("entry")
    )
    schema = request.format_structural.get(format_id, ())
    for rule in schema:
        if (
            isinstance(rule, Mapping)
            and rule.get("rule") == "presence"
            and rule.get("required") is False
            and rule.get("axis") == axis
            and rule.get("value") == value
        ):
            return True
    return False


def validate_structural_preservation(
    request: ReconcileRequest, fitted_ir: Mapping[str, Any]
) -> None:
    """The §16/DR-4 C7 preserve-section-keys contract on an ALREADY-fidelity-valid fitted IR.

    The reshape swaps WHOLE leaf bodies (`_assemble_fitted_ir`), so the composed body's section
    keys are NOT mechanically preserved — they must be CHECKED. Two rules, both SCOPED to the
    `(axis, value)` keys the IR's resolved `section_conformance` base schema references (C4):

    1. **PRESERVE-THROUGH** — every schema-referenced key present in the COMPOSED sections must be
       present in the FITTED sections, UNLESS this format's `format_structural` FORBIDS it (a
       `presence required=false` venue-forbid = a legitimate drop). A dropped/renamed non-forbidden
       schema-referenced key is a breach.
    2. **NO-MINT (GAP-2)** — a schema-referenced key present in the FITTED sections but ABSENT from
       the COMPOSED sections is a breach (the reconciler may DROP or PRESERVE a schema-satisfying
       role/type, but NEVER MINT one from arbitrary content — the machine analog of
       author-declaration-trust).

    SCOPING is load-bearing: a NON-schema-referenced heading a plain-outline `adapt`/`split`
    legitimately ADDS or RENAMES is NEVER touched (a global `fitted ⊆ composed` would regress
    every existing reshape). INERT — a byte-unchanged no-op — when the IR carries no schema-
    referenced keys (a plain outline with no `section_schema`).

    Raises `StructuralPreservationViolation` (an `ir.IRError`, a DISTINCT code from the fidelity
    violation) so a breach rides the SAME bounded re-ask (§16); a persistent breach exhausts the
    bound and is NEVER fitted. A `SectionGrammarError` from the FITTED body is folded into the
    same re-ask, exactly as compose.py does at its base gate."""
    schema_keys = _schema_referenced_keys(request.canonical_ir)
    if not schema_keys:
        return  # INERT: no schema-referenced keys → byte-unchanged no-op (no-op safety)
    composed = _parse_body_sections(request.canonical_ir)
    try:
        fitted = _parse_body_sections(fitted_ir)
    except SectionGrammarError as exc:
        # A writer-correctable fitted-body grammar derail — feed the SAME bounded re-ask.
        raise StructuralPreservationViolation(
            f"structure-not-preserved: the fitted body's section grammar is invalid ({exc}) — "
            "reshape the body's `##`-heading skeleton so it parses, keeping every schema-"
            "referenced heading the outline declared (§16/DR-4 C7)"
        ) from exc
    for axis, value in sorted(schema_keys):
        in_composed = _has_section_key(composed, axis, value)
        in_fitted = _has_section_key(fitted, axis, value)
        if in_composed and not in_fitted and not _format_forbids(request, axis, value):
            raise StructuralPreservationViolation(
                f"structure-not-preserved: the schema-referenced section {axis} {value!r} was "
                "present at compose but is DROPPED/renamed in the fit, and this format does not "
                "forbid it — keep its EXACT heading so its slug/{#id} still matches; drop a "
                "section ONLY when the venue forbids it (§16/DR-4 C7)"
            )
        if in_fitted and not in_composed:
            raise StructuralPreservationViolation(
                f"structure-not-preserved: the schema-referenced section {axis} {value!r} is "
                "MINTED in the fit (absent at compose) — the reconciler may DROP or PRESERVE a "
                "schema-satisfying section but NEVER invent one from ungrounded content (GAP-2)"
            )


# ---------------------------------------------------------------------------
# The preserve-citation-keys contract (§16 / DR-5 C8) — the CITATION analog of C7's section-key
# preserve-through. The reshape swaps WHOLE leaf bodies, so a composed inline `[@key]` is NOT
# mechanically preserved: a reshape that MANGLES `[@key]`→`[@keytypo]` or MINTS a `[@newkey]` would
# ship an UNRESOLVABLE citation. Per D7 = SUBSET-only (S5): a DROP is PERMITTED (a benign orphaned
# reference), a fitted key ABSENT from the composed set is a breach. TEXT-level (NO pandoc — the
# authoritative `[@key]`→`references` AST resolution stays at the C4 COMPOSE locus; the fabrication
# half is C4's job, this is the reshape-preservation half). INERT for a citation-less body.
# ---------------------------------------------------------------------------

#: A bracketed Pandoc citation group: `[...]` carrying an `@` citation marker (DR-5 C8). Covers each
#: pinned bracketed form — `[@key]`, multi-key `[@a; @b]`, locator `[@k, p. 5]`, prefix `[see @k]`,
#: suppressed-author `[-@k]` — with NO nested brackets, so the grounded-fact spans
#: `[claim]{.TIER data-fact="…"}` (which carry NO `@`) never match. A TEXT scan, no pandoc.
_CITE_BRACKET_RE = re.compile(r"\[[^\[\]]*@[^\[\]]*\]")

#: One Pandoc citation KEY inside a bracketed citation: an `@` NOT preceded by a word char (so a
#: bare `repo@commit`/e-mail never registers) then the key — a leading word char plus Pandoc's
#: internal-punctuation charset. Applied SYMMETRICALLY to the composed and the fitted sets, so any
#: extractor imprecision cancels across the SUBSET comparison (an over/under-capture hits both).
_CITE_KEY_RE = re.compile(r"(?<!\w)@([\w][\w:.#$%&+?<>~/-]*)")


def _iter_cite_keys(body: str) -> set[str]:
    """Every Pandoc citation KEY carried by a Markdown body's BRACKETED citation forms (DR-5 C8).

    A TEXT-level scan (NO pandoc): find each bracketed group carrying an `@` citation marker
    (`[@key]`, `[@a; @b]`, `[@k, p. 5]`, `[see @k]`, `[-@k]`) and pull every `@key` inside. This is
    the SINGLE-SOURCED extractor — the SAME function feeds BOTH the composed and the fitted key sets
    in `validate_citation_preservation`, so a minor quirk (a permissive key charset, a bracket edge
    case) affects both sides equally and the SUBSET comparison stays robust. INERT on a body with no
    `[@` citation (returns an empty set → the check is a pure no-op). The authoritative
    `[@key]`→`references` resolution is C4's COMPOSE-locus AST parse, not this preservation scan."""
    keys: set[str] = set()
    for bracket in _CITE_BRACKET_RE.findall(body):
        for match in _CITE_KEY_RE.finditer(bracket):
            keys.add(match.group(1))
    return keys


def validate_citation_preservation(
    request: ReconcileRequest, fitted_ir: Mapping[str, Any]
) -> None:
    """The §16/DR-5 C8 preserve-citation-keys contract on an ALREADY-fidelity-valid fitted IR.

    The reshape swaps WHOLE leaf bodies, so a composed inline `[@key]` is NOT mechanically preserved
    — a reshape that MANGLES `[@key]`→`[@keytypo]` or MINTS a `[@newkey]` would ship an UNRESOLVABLE
    citation (the citation analog of C7's section-key preserve-through). Per **D7 = SUBSET-only
    (S5)**: the reconciler MAY DROP a citation (a benign orphaned reference — fitted ⊆ composed with
    fewer keys is NO breach), but a fitted key NOT in the composed set (a mint OR a mangle) IS a
    breach.

    Composed set = ∪ `_iter_cite_keys` over the canonical leaves; fitted set = ∪ over the fitted
    leaves — the SAME single-sourced text extractor on both sides, so an extractor imprecision
    cancels across the SUBSET test. If `fitted ⊄ composed`, raise `CitationPreservationViolation`
    (an `ir.IRError`, a DISTINCT code) so a breach rides the SAME bounded fidelity re-ask (§16); a
    persistent breach exhausts the bound and is NEVER fitted (as `CODE_FIDELITY_VIOLATION`).
    INERT — a byte-unchanged no-op — when neither body carries `[@` (no keys → a pure pass; every
    citation-less reconcile path stays byte-identical). This is the reshape-preservation half;
    the anti-fabrication half (an `[@key]` that names no projected reference) is C4's COMPOSE-locus
    resolution — a read-only check, it NEVER inspects the fitted-id/preimage nor writes identity."""
    composed_keys: set[str] = set()
    for _where, body in _iter_leaves(request.canonical_ir):
        composed_keys |= _iter_cite_keys(body)
    fitted_keys: set[str] = set()
    for _where, body in _iter_leaves(fitted_ir):
        fitted_keys |= _iter_cite_keys(body)
    minted = fitted_keys - composed_keys
    if minted:
        raise CitationPreservationViolation(
            f"citation-not-preserved: the fit introduced inline citation key(s) {sorted(minted)} "
            "absent from the composed body — a reshape MAY DROP a citation but NEVER invent a new "
            "key nor MANGLE an existing one into a different key (an unresolvable citation, "
            "§16/DR-5 C8)"
        )


# ---------------------------------------------------------------------------
# The TERMINAL venue-structural gate (§15/§16 / DR-4 C8) — the HARD `format_structural` contract,
# reconstructed into C2 (via `sections.reconstruct_rule`, SINGLE-SOURCED, never forked) and run
# over the FITTED sections. #4a per-section Length/Count limits are checked HERE, never by the
# whole-artifact `max_chars` gate. INERT for a floor / no-entry format.
# ---------------------------------------------------------------------------


def _pinned_format_schema(request: ReconcileRequest) -> Schema:
    """Reconstruct THIS artifact's pinned-format `format_structural` venue schema into the C2
    vocabulary, or `()` when the format carries no venue tightening.

    The format-id is the composition preimage's bound format entry — the SAME indexing C7's
    `_format_forbids` uses — so ONLY this artifact's venue tightening participates; an unrelated
    format's schema never reaches this gate (the C7→C8 identity obligation). The serialized rule
    maps are decoded through `sections.reconstruct_rule` (SINGLE-SOURCED against C2, never a
    forked decoder — the SAME decoder compose's base gate uses). A MALFORMED venue rule is a loud
    platform-authoring `ReconcileError` (never a silent pass, never a writer re-ask; §3.1) —
    mirrors compose's `_resolve_base_gate_schema`."""
    format_id = (
        request.canonical_ir.get("binding", {})
        .get("preimage", {})
        .get("dimensions", {})
        .get("format", {})
        .get("entry")
    )
    raw = request.format_structural.get(format_id)
    if not raw:
        return ()
    try:
        return tuple(reconstruct_rule(rule) for rule in raw)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ReconcileError(
            f"reconcile-error: this format's `format_structural` venue schema is malformed ({exc}) "
            "— a per-format HARD structural class is a list of C2 conformance rules (DR-4 C6/C8); "
            "fix the Platform entry (never a writer re-ask, never silent)"
        ) from exc


def _describe_structural_violation(violation: Violation) -> str:
    """A concise, machine-derived description of ONE venue-structural breach (mirrors compose's
    `_describe_violation`, venue-scoped wording). Presentation text only — never invents a rule."""
    rule = violation.rule
    selector = getattr(rule, "selector", None)
    target = f"{selector.axis} {selector.value!r}" if selector is not None else "section"
    if isinstance(rule, Presence):
        if rule.required:
            return f"required venue section {target} is MISSING"
        where = f" (heading {violation.section.heading!r})" if violation.section else ""
        return f"forbidden venue section {target} is PRESENT{where}"
    if isinstance(rule, Order):
        seq = " -> ".join(f"{sel.axis} {sel.value!r}" for sel in rule.selectors)
        return f"venue sections are out of the required order [{seq}]"
    if isinstance(rule, Count):
        return f"venue section {target} breaks its count bound"
    if isinstance(rule, Length):
        where = f" (heading {violation.section.heading!r})" if violation.section else ""
        return f"venue section {target} breaks its per-section length bound{where}"
    return "venue section contract violated"  # pragma: no cover — the C2 menu is closed


def _structural_gate_violations(
    request: ReconcileRequest, fitted_ir: Mapping[str, Any]
) -> tuple[str, ...]:
    """The DR-4 C8 TERMINAL venue-structural gate on the FITTED body (§15/§16).

    Reconstructs THIS artifact's pinned-format `format_structural` schema (`_pinned_format_schema`)
    and runs C2 `check_conformance` over the FITTED sections (the shared `_parse_body_sections`
    parse — the SAME C1 parse compose/C7 use, never a fork). Returns the ERROR-severity breaches as
    concise machine-derived strings (mirrors compose's C5 `_base_conformance_note`); warning/info
    violations never block (advisory, §3.1). INERT — returns `()` — when this format has no venue
    tightening (a floor platform never blocks structurally). #4a per-section Length/Count limits are
    checked HERE (they ride the venue schema), NEVER by the whole-artifact `max_chars` gate. A
    FITTED-body grammar derail at this TERMINAL point is a loud wiring/late `ReconcileError`: the
    body already cleared the re-ask loop, so it must parse (never a silent pass; §3.1)."""
    schema = _pinned_format_schema(request)
    if not schema:
        return ()
    try:
        sections = _parse_body_sections(fitted_ir)
    except SectionGrammarError as exc:
        raise ReconcileError(
            f"reconcile-error: the FITTED body's section grammar is invalid ({exc}) at the "
            "terminal venue-structural gate — a fitted body reaching the gate must parse (a "
            "wiring/late defect, never a silent pass; §3.1/§16 DR-4 C8)"
        ) from exc
    errors = [v for v in check_conformance(sections, schema) if v.severity == SEVERITY_ERROR]
    return tuple(_describe_structural_violation(v) for v in errors)


# ---------------------------------------------------------------------------
# Fitted-IR assembly (§16): the canonical envelope with RESHAPED leaves, re-validated.
# ---------------------------------------------------------------------------


def _assemble_fitted_ir(
    reshaped: Mapping[str, Any], canonical_ir: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the fitted IR from the reconciler's reshaped leaves + the canonical envelope.

    The fitted IR is the canonical envelope (binding, grounding, stamps, metadata — all
    unchanged: a fit does not re-compose) with its leaves replaced by the reshaped content.
    `ir.validate_ir` re-validates the whole thing — structural schema, the composition binding
    still reproducing the artifact-id, and every inline reference known + tier-honest (tier
    promotion caught here, §6.5/§16). Raises an `ir.IRError` the reconcile loop re-asks on."""
    doc: dict[str, Any] = {
        key: value for key, value in canonical_ir.items() if key not in ("body", "parts")
    }
    if _is_flat(canonical_ir):
        doc["body"] = reshaped["body"]
    else:
        doc["parts"] = [
            {**part, "body": reshaped["parts"][part["role"]]} for part in canonical_ir["parts"]
        ]
    ir.validate_ir(doc)
    return doc


def _passthrough(canonical_ir: Mapping[str, Any]) -> dict[str, Any]:
    """The no-op / pass fitted IR: a byte-identical canonical copy (zero LLM). Canonicalizing
    both makes `canonical_json_bytes(passthrough) == canonical_json_bytes(canonical_ir)`."""
    return json.loads(canonical_json_str(canonical_ir))


# ---------------------------------------------------------------------------
# The fit-binding (§16): {preimage, hex12 digest, fitted-id, minted_ts, outcome record}.
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Wall-clock UTC ISO-8601 — the DEFAULT `minted_ts` (a RECORD field only, never identity)."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def _mint_fitted_id(
    artifact_id: str, platform: str, language: str, digest: str, *, revision: bool
) -> str:
    """Mint the fitted-id via `ids.fitted_id` (never hand-rolled). A `revision` fit carries the
    `_hex12` fit-revision qualifier on the language segment (§7.4); a baseline fit is the
    unqualified template. Step 26's FR2 logic decides `revision`; this module only mints."""
    fit_revision = digest if revision else None
    try:
        return fitted_id(artifact_id, platform, language, fit_revision=fit_revision)
    except IdError as exc:
        raise ReconcileError(f"reconcile-error: cannot mint the fitted-id ({exc})") from exc


def build_fit_binding(
    *,
    artifact_id: str,
    platform: str,
    language: str,
    preimage: Mapping[str, Any],
    strategy: str,
    localize_languages: Sequence[str],
    gate_outcome: str,
    minted_ts: str | None = None,
    revision: bool = False,
) -> dict[str, Any]:
    """Assemble the §16 fit-binding: the reconcile-inputs preimage, its `hex12` digest, the
    full fitted-id, `minted_ts`, and the reconcile outcome record (strategy, localize
    languages, gate outcome). CRITICAL: `minted_ts` is a record field ONLY — it is NOT in the
    preimage and NOT in the digest, so the identity (preimage → digest → fitted-id) is
    byte-reproducible across runs regardless of wall clock (§16)."""
    digest = fit_digest(preimage)
    return {
        "fitted_id": _mint_fitted_id(artifact_id, platform, language, digest, revision=revision),
        "preimage": dict(preimage),
        "digest": digest,
        "minted_ts": minted_ts if minted_ts is not None else _now_iso(),
        "outcome": {
            "strategy": strategy,
            "localize_languages": list(localize_languages),
            "gate_outcome": gate_outcome,
        },
    }


# ---------------------------------------------------------------------------
# The reconciler prompt (§16 contract) + strict output parsing (compose's separation of
# authority: the LLM supplies reshaped CONTENT + its drop/echo declarations; the machinery
# owns the fitted-id, the fit-binding, the preimage/digest, and the gate).
# ---------------------------------------------------------------------------


def _content_view(canonical_ir: Mapping[str, Any]) -> dict[str, Any]:
    """The leaves the reconciler reshapes — the flat body or the role→body map."""
    if _is_flat(canonical_ir):
        return {"body": canonical_ir["body"]}
    return {"parts": {part["role"]: part["body"] for part in canonical_ir["parts"]}}


def _structure_context(canonical_ir: Mapping[str, Any]) -> dict[str, Any]:
    if _is_flat(canonical_ir):
        return {
            "shape": "flat",
            "output_contract": {"body": "<reshaped Markdown for the whole artifact>"},
        }
    roles = [part["role"] for part in canonical_ir["parts"]]
    return {
        "shape": "parts",
        "roles": roles,
        "output_contract": {"parts": {role: "<reshaped Markdown>" for role in roles}},
    }


def build_reconciler_prompt(
    request: ReconcileRequest, *, reask_note: str | None = None
) -> str:
    """Assemble the reconciler prompt: the versioned `reconciler.md` contract + one JSON
    context block (the target coordinates, the strategy + hard limits + advisory, the
    grounding ledger to re-anchor, the voice/content params to echo, the canonical leaves
    to reshape, and — when the artifact was composed under a house-style lexicon — the
    already-applied house-style rules to preserve, omit-when-absent). On a re-ask the
    correction note is appended."""
    template = load_template(RECONCILER_TEMPLATE).text
    context = {
        "target": {
            "artifact_id": request.artifact_id,
            "platform": request.platform,
            "language": request.language,
            "source_language": request.source_language,
        },
        "strategy": request.strategy,
        "hard_limits": dict(request.hard_limits),
        "advisory": dict(request.advisory),
        "voice_content_params": dict(request.voice_content_params),
        "grounding_ledger": request.canonical_ir.get("grounding", {}),
        "canonical_content": _content_view(request.canonical_ir),
        "structure": _structure_context(request.canonical_ir),
    }
    # DR-2 C4 (§16, ADVISORY): surface the ALREADY-APPLIED house-style (lexicon) rules so the
    # reconciler PRESERVES them through the reshape. Read-only FROM the binding the artifact
    # already carries — `binding.preimage.lexicon` is the C2 `{entry, delta}`; its `delta` map
    # holds the non-floor terminology/mechanical rules C3 applied at compose. OMIT-WHEN-ABSENT:
    # a lexicon-less IR adds NO key, so the assembled context is byte-identical (the clause is
    # INERT). PROMPT input ONLY — it NEVER enters `reconcile_inputs_preimage`/`fit_digest`: the
    # lexicon is already covered by the ARTIFACT-id and §16 EXCLUDES it from the reconcile-inputs
    # preimage (this is the read-only preserve of §16, not a new identity input).
    lexicon = request.canonical_ir.get("binding", {}).get("preimage", {}).get("lexicon")
    if lexicon:
        context["lexicon"] = lexicon
    # json (not canonical): the prompt is LLM-facing TEXT, so `default=str` may soften a
    # date/set in the context view without failing — this is never a persisted record.
    context_json = json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    blocks = [template.rstrip(), "", "## Reconcile context (JSON)", "```json", context_json, "```"]
    if reask_note:
        blocks += ["", "## Correction required (bounded re-ask)", reask_note]
    return "\n".join(blocks)


def _extract_json_object(text: str) -> Any:
    """Parse the reconciler's JSON object, tolerating a code fence or surrounding prose (raw,
    then a ```json block, then the first `{` … last `}` span). No parseable object is a
    contract violation the loop re-asks on (§3.1 — never guess at partial content)."""
    candidates = [text.strip()]
    fence = _FENCE_RE.search(text)
    if fence is not None:
        candidates.append(fence.group(1).strip())
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ir.SchemaViolation(
        "ir-schema-invalid: the reconciler output contains no parseable JSON object (§16)"
    )


def parse_reconciler_output(text: str | None, request: ReconcileRequest) -> dict[str, Any]:
    """Validate the reconciler's declaration envelope against the shape the canonical IR
    declared. Exactly `{fitted, dropped_facts, voice_content_echo}`; `fitted` is `{"body": …}`
    for a flat IR or `{"parts": {role: …}}` keyed by EXACTLY the canonical roles. Raises
    `ir.SchemaViolation` on any mismatch — the reconciler supplies reshaped CONTENT + its
    drop/echo declarations only; the ids/binding/gate are the machinery's."""
    if not isinstance(text, str) or not text.strip():
        raise ir.SchemaViolation("ir-schema-invalid: the reconciler returned empty output (§16)")
    payload = _extract_json_object(text)
    if not isinstance(payload, dict) or set(payload) != {
        "fitted",
        "dropped_facts",
        "voice_content_echo",
    }:
        raise ir.SchemaViolation(
            "ir-schema-invalid: the reconciler output must be exactly "
            "{fitted, dropped_facts, voice_content_echo} (§16), got "
            f"{sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
        )
    fitted = payload["fitted"]
    if not isinstance(fitted, dict):
        raise ir.SchemaViolation("ir-schema-invalid: reconciler `fitted` must be a JSON object")
    if _is_flat(request.canonical_ir):
        if set(fitted) != {"body"} or not (
            isinstance(fitted["body"], str) and fitted["body"].strip()
        ):
            raise ir.SchemaViolation(
                "ir-schema-invalid: a flat IR expects `fitted` = {'body': <non-empty Markdown>} "
                "(§16)"
            )
    else:
        roles = {part["role"] for part in request.canonical_ir["parts"]}
        parts = fitted.get("parts")
        if set(fitted) != {"parts"} or not isinstance(parts, dict) or set(parts) != roles:
            raise ir.SchemaViolation(
                f"ir-schema-invalid: a multi-part IR expects `fitted` = {{'parts': {{role: …}}}} "
                f"covering EXACTLY the roles {sorted(roles)} (§16)"
            )
        for role, body in parts.items():
            if not (isinstance(body, str) and body.strip()):
                raise ir.SchemaViolation(
                    f"ir-schema-invalid: reconciler part {role!r} must be non-empty Markdown"
                )
    dropped = payload["dropped_facts"]
    if not isinstance(dropped, list) or not all(isinstance(d, str) for d in dropped):
        raise ir.SchemaViolation(
            "ir-schema-invalid: reconciler `dropped_facts` must be a list of fact-id strings (§16)"
        )
    echo = payload["voice_content_echo"]
    if not isinstance(echo, dict):
        raise ir.SchemaViolation(
            "ir-schema-invalid: reconciler `voice_content_echo` must be a map (§16 fidelity (i))"
        )
    return {"fitted": fitted, "dropped_facts": list(dropped), "voice_content_echo": dict(echo)}


def _reask_note(violations: Sequence[str]) -> str:
    """The corrective note appended on a re-ask: the most recent violation + the fidelity
    reminder. Machine-derived — never invents new requirements (§3.1)."""
    latest = violations[-1] if violations else "unspecified"
    return (
        f"Your previous fitted output was REJECTED by the fit/fidelity contract: {latest}. "
        "Return ONLY the JSON object {fitted, dropped_facts, voice_content_echo}. Re-anchor "
        'EVERY grounding-ledger fact-id inline as `[text]{.TIER data-fact="fN"}` with its '
        "EXACT ledger tier (NEVER promote a tier); list any fact you intentionally drop-as-lead "
        "in `dropped_facts` (a SILENT drop is rejected); echo every voice/content parameter "
        "verbatim in `voice_content_echo`."
    )


# ---------------------------------------------------------------------------
# The localize seam (§16 step 1) — DEFERRED, designed, a clearly-marked no-op.
# ---------------------------------------------------------------------------


def _localize(
    canonical_ir: Mapping[str, Any], target_language: str, source_language: str
) -> tuple[Mapping[str, Any], tuple[str, ...]]:
    """The FIRST step of the fixed internal ordering (§16) — DEFERRED (§5.3/§26).

    Localization is not implemented in v1; the slot is DESIGNED and fixed first because
    localization alters length and can breach a limit reshape had satisfied (which is why the
    gate is terminal). In v1 the content passes through UNCHANGED and the languages, when they
    differ, are recorded for the fit outcome; localization GA (§26) fills this seam
    additively (its non-coordinate knobs then join the reconcile-inputs preimage, §16). This
    is a NO-OP, not a stub to fail on — a v1 fit whose target language equals its source
    language never needs it, and that is the exercised path.

    FORWARD contract (NOT built now): at localization GA (§26) the SAME preserve-section-keys
    rule (`validate_structural_preservation`, DR-4 C7) applies ADDITIVELY across the localize
    seam — a localized body must keep every schema-referenced section heading exactly as the
    source did (its slug/{#id} must still match), so a translation may not drop or rename a
    schema-referenced section any more than a reshape may."""
    if target_language == source_language:
        return canonical_ir, ()
    return canonical_ir, (source_language, target_language)


# ---------------------------------------------------------------------------
# The reconcile entry point: preimage → localize → reshape → terminal gate → fit-binding.
# ---------------------------------------------------------------------------


def _validate_request(request: ReconcileRequest) -> None:
    """Loud, typed WIRING guards (§3.1) — never a re-ask. The canonical IR must be a valid
    §15 envelope whose binding names `request.artifact_id`, and the strategy must be known."""
    if request.strategy not in RECONCILE_STRATEGIES:
        raise ReconcileError(
            f"reconcile-error: unknown reshape strategy {request.strategy!r} "
            f"(§12.3: {', '.join(RECONCILE_STRATEGIES)})"
        )
    try:
        ir.validate_ir(request.canonical_ir)
    except ir.IRError as exc:
        raise ReconcileError(
            f"reconcile-error: canonical_ir is not a valid IR-canonical envelope ({exc})"
        ) from exc
    bound = request.canonical_ir.get("binding", {}).get("artifact_id")
    if bound != request.artifact_id:
        raise ReconcileError(
            f"reconcile-error: request.artifact_id {request.artifact_id!r} does not match the "
            f"canonical IR's composition binding {bound!r} — a fit does not re-compose (§16)"
        )


def _outcome(
    *,
    status: Literal["ok", "block", "error"],
    code: str,
    preimage: Mapping[str, Any],
    digest: str,
    fitted_id: str | None = None,
    fitted_ir: Mapping[str, Any] | None = None,
    fit_binding: Mapping[str, Any] | None = None,
    is_noop: bool = False,
    dropped_facts: tuple[str, ...] = (),
    blocked_limits: tuple[str, ...] = (),
    structural_violations: tuple[str, ...] = (),
    attempts: int = 0,
    violations: tuple[str, ...] = (),
    transport_result: TransportResult | None = None,
) -> ReconcileOutcome:
    return ReconcileOutcome(
        status=status,
        code=code,
        fitted_id=fitted_id,
        fitted_ir=fitted_ir,
        fit_binding=fit_binding,
        preimage=preimage,
        digest=digest,
        is_noop=is_noop,
        dropped_facts=dropped_facts,
        blocked_limits=blocked_limits,
        structural_violations=structural_violations,
        attempts=attempts,
        violations=violations,
        transport_result=transport_result,
    )


def reconcile(
    request: ReconcileRequest,
    *,
    runner: Runner | None = None,
    revision: bool = False,
    minted_ts: str | None = None,
    measure: Measurer = default_measure,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    cwd: Path | str | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    plan: TransportPlan | None = None,
) -> ReconcileOutcome:
    """Fit one IR-canonical artifact to a `(platform, language)` target — PURE fit machinery.

    Ordering is FIXED and internal (§16): localize [deferred no-op seam] → reshape per
    strategy → the TERMINAL joint gate (fit-or-block; DR-4 C8 evaluates the HARD venue-structural
    contract AND the hard-limit gate together, populating both concern-sets on a joint breach).
    `pass` never invokes the LLM (it no-ops when it fits + the language matches — a bit-identical
    passthrough, ZERO LLM — or is blocked by the gate); `adapt`/`split`/`truncate` invoke the
    reconciler (`runner` injectable for tests) with a bounded fidelity re-ask. A transport-level
    failure surfaces immediately (an account-side condition a re-ask cannot fix); a persistent
    fidelity failure past `max_attempts` returns `fit-fidelity-violation` and is NEVER fitted.
    Unfittable content BLOCKS (`section-conformance-violation` for a venue-structural breach, else
    `hard-limit-exceeded`) while siblings continue. On a fit, the fit-binding
    (preimage, hex12 digest, fitted-id, `minted_ts` [record-only], outcome) is returned
    alongside the reshaped IR; `revision` selects the baseline vs revision fitted-id (step
    26's FR2 decision, this module only mints). NEVER raises for a reconciler defect — those
    are typed outcomes; only wiring defects raise (`ReconcileError`). `plan` (plan G1) threads
    the run's shared cost accumulator through to the reconciler's chokepoint call; a `pass`
    (ZERO-LLM) reconcile never reaches the chokepoint, so it contributes nothing."""
    _validate_request(request)
    if max_attempts < 1:
        raise ReconcileError(f"reconcile-error: max_attempts must be ≥ 1, got {max_attempts}")

    preimage = reconcile_inputs_preimage(request)
    digest = fit_digest(preimage)

    # 1. Localize (deferred, designed no-op seam) — FIRST, before the terminal gate.
    localized_ir, localize_languages = _localize(
        request.canonical_ir, request.language, request.source_language
    )

    # 2. Reshape per strategy. `pass` reshapes nothing (candidate no-op / block); the other
    #    three invoke the reconciler with the bounded fidelity re-ask.
    attempts = 0
    dropped_facts: tuple[str, ...] = ()
    transport_result: TransportResult | None = None
    violations: list[str] = []

    if request.strategy == "pass":
        fitted_ir: dict[str, Any] | None = _passthrough(localized_ir)
    else:
        fitted_ir = None
        own_cwd = cwd is None
        scratch = Path(tempfile.mkdtemp(prefix="optiquity-reconcile-")) if own_cwd else Path(cwd)
        extra = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
        try:
            for attempt in range(1, max_attempts + 1):
                attempts = attempt
                note = _reask_note(violations) if violations else None
                prompt = build_reconciler_prompt(request, reask_note=note)
                transport = invoke_headless(
                    prompt, cwd=scratch, runner=runner, model=model, plan=plan, **extra
                )
                transport_result = transport
                if transport.status != "ok":
                    # A transport-level failure — re-asking cannot fix an account-side condition.
                    return _outcome(
                        status="error",
                        code=transport.code,
                        preimage=preimage,
                        digest=digest,
                        attempts=attempt,
                        violations=tuple(violations),
                        transport_result=transport,
                    )
                try:
                    parsed = parse_reconciler_output(transport.text, request)
                    candidate = _assemble_fitted_ir(parsed["fitted"], localized_ir)
                    validate_fidelity(
                        candidate,
                        dropped_facts=parsed["dropped_facts"],
                        voice_content_echo=parsed["voice_content_echo"],
                        voice_content_params=request.voice_content_params,
                    )
                    # DR-4 C7 preserve-through + no-mint (a distinct `ir.IRError` code); first
                    # remediated by this SAME bounded re-ask, then C8's terminal gate blocks.
                    validate_structural_preservation(request, candidate)
                    # DR-5 C8 preserve-citation-keys: a fitted inline `[@key]` not in the composed
                    # set (a mint/mangle → an unresolvable citation) rides the SAME bounded re-ask
                    # (a distinct `ir.IRError` code); a DROP is permitted (D7 = SUBSET-only).
                    validate_citation_preservation(request, candidate)
                except ir.IRError as exc:
                    violations.append(f"[{exc.code}] {exc}")
                    continue  # bounded fidelity re-ask (§16)
                fitted_ir = candidate
                dropped_facts = tuple(parsed["dropped_facts"])
                break
            else:
                # Re-ask bound exhausted: caught, and NEVER fitted (§16).
                return _outcome(
                    status="error",
                    code=CODE_FIDELITY_VIOLATION,
                    preimage=preimage,
                    digest=digest,
                    attempts=max_attempts,
                    violations=tuple(violations),
                    transport_result=transport_result,
                )
        finally:
            if own_cwd:
                shutil.rmtree(scratch, ignore_errors=True)

    # 3. The TERMINAL joint gate (§16 step 3 / DR-4 C8) — LAST, fit-or-block, never silent-pass.
    #    BOTH concern-sets are evaluated BEFORE any block-return, so a JOINT structural+limit case
    #    populates BOTH fields (no early-return masking): the venue-structural gate (the HARD
    #    `format_structural` contract, #4a per-section limits included; INERT at a floor format) and
    #    the whole-artifact hard-limit gate. On a block the primary `code` is the structural code
    #    when any venue rule breached, else the hard-limit code — BOTH fields populate regardless.
    structural_violations = _structural_gate_violations(request, fitted_ir)
    breached = breached_limits(fitted_ir, request.hard_limits, measure=measure)
    if structural_violations or breached:
        code = (
            CODE_SECTION_CONFORMANCE_VIOLATION
            if structural_violations
            else CODE_HARD_LIMIT_EXCEEDED
        )
        return _outcome(
            status="block",
            code=code,
            preimage=preimage,
            digest=digest,
            blocked_limits=breached,
            structural_violations=structural_violations,
            attempts=attempts,
            violations=tuple(violations),
            transport_result=transport_result,
        )

    # A fit: mint the fit-binding (minted_ts is record-only — never in identity, §16).
    is_noop = request.strategy == "pass" and request.language == request.source_language
    binding = build_fit_binding(
        artifact_id=request.artifact_id,
        platform=request.platform,
        language=request.language,
        preimage=preimage,
        strategy=request.strategy,
        localize_languages=localize_languages,
        gate_outcome="fit",
        minted_ts=minted_ts,
        revision=revision,
    )
    return _outcome(
        status="ok",
        code="ok",
        preimage=preimage,
        digest=digest,
        fitted_id=binding["fitted_id"],
        fitted_ir=fitted_ir,
        fit_binding=binding,
        is_noop=is_noop,
        dropped_facts=dropped_facts,
        attempts=attempts,
        violations=tuple(violations),
        transport_result=transport_result,
    )
