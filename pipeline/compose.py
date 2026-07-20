"""The compose (writer) stage: grounded facts → a persisted IR-canonical artifact (§15).

Design authority: `docs/design.md`
  §15    — the writer emits the IR-canonical envelope this stage assembles + persists; the
           grounding ledger (RI3), the composition binding (RI4), and the version stamps are
           STAMPED HERE (`pipeline.ir.build_ir`), never trusted from the LLM — the writer
           supplies leaf CONTENT only, so it can neither forge the `artifact-id` nor promote
           a tier.
  §6.5/§16 — the EXTRACTED publish floor + no tier promotion: the strict IR validation gate
           (`pipeline.ir.validate_ir`) refuses any inline reference to an unknown fact-id or
           one whose Span tier class contradicts the ledger — the ONLY re-ask point in the
           system (transport has none, §21.9).
  §9.6   — **roster awareness is generating-run compose CONTEXT, not an identity input.** The
           sibling-role roster rides the PROMPT (light cross-linking) but never the
           `artifact-id` preimage: this stage receives an already-minted `artifact_id` +
           preimage and never re-mints, so the roster (and the grounded fact set) is
           structurally incapable of reaching identity — `build_ir` re-mints from the
           preimage and refuses a mismatch, pinning the guarantee.
  §22.3  — persistence rides the S0–S6 spine (`pipeline.spine.drive`): a claim on the
           `artifact-id`, a no-replace commit, holder-checked release. Re-composing an
           existing `artifact-id` is an idempotent no-op (§21.8) — this stage checks
           `is_done` FIRST and skips the (expensive) LLM entirely, driving the spine only to
           complete any lagging bookkeeping. INV-CORRECTNESS (§22.7): this module imports NO
           SSOT module; S5 advancement rides the write-only `AdvanceHook` a caller supplies.
  §19    — **Review 1 (the artifact review) is wired here (PA-10).** Post-mint, ONCE per
           artifact, this stage runs the ADVISORY artifact review (`pipeline.review`, itself
           SSOT-free) and advances the artifact SSOT row to `artifact-reviewed` through the
           SAME write-only hook mechanism (`review_advance`) — so compose still imports no
           SSOT module. The review NEVER mutates the persisted IR; it only produces an
           immutable id-addressed record and advances STATUS. It is off by default
           (backward-compatible): the pre-review compose path is unchanged.
  §21.9 (F10) — the writer is invoked through `pipeline.transport` on the Claude SUBSCRIPTION,
           never API keys; per step-23 advisory A2 the child runs in a dedicated NON-REPO
           `cwd` (see below), never the repo working tree.

Design ambiguities resolved in this module (documented for the reviewer):

1. **Separation of authority — the writer produces CONTENT, compose owns STRUCTURE.** The
   LLM returns only leaf Markdown (`{"body": …}` for a flat single-part format, or
   `{"parts": {role: …}}` keyed by the Format-declared roles). Compose stamps the binding,
   ledger, stamps, part-ids and packaging hints. This is what makes "a violating writer
   output is caught and NEVER persisted" airtight: an invalid content envelope never becomes
   an IR at all, and even a valid one cannot carry a forged id or a promoted tier.

2. **The bounded re-ask lives HERE and only here (§21.9).** `DEFAULT_MAX_ATTEMPTS = 3` (one
   initial ask + two corrective re-asks). A CONTRACT violation (unparseable/mis-shaped JSON,
   unknown fact-id, tier mismatch) appends a correction note and re-asks up to the bound; a
   persistently-violating writer is returned as a typed `compose-contract-violation` outcome
   and NEVER persisted. A TRANSPORT-level failure (timeout, backpressure, api-error) is
   surfaced immediately with the transport's own code — re-asking cannot fix an account-side
   condition, so it does not burn attempts.

3. **The A2 non-repo cwd.** When `cwd` is not supplied, this module creates a fresh, empty
   `tempfile.mkdtemp()` scratch directory (system temp — outside the repo working tree),
   passes it to `invoke_headless(cwd=…)`, and removes it after. The headless child therefore
   never runs in the repo root (step-23 report A2). Tests inject a fake `runner` (no child is
   spawned), so this path is about the real invocation only.

4. **Fact-id assignment is compose's, deterministic.** Each `GroundedFact` becomes one ledger
   entry keyed `f0`, `f1`, … in a stable order (by `source_instance_id`, `subject`, `claim`);
   the writer is handed exactly those ids + tiers and must reference them inline as
   `[claim]{.TIER data-fact="fN"}`. Corroborated facts from two instances are two ledger
   entries (each separately citable, per its own commit) — the ledger is per (fact, instance).

5. **`source_repo` is required, per instance.** The §15 ledger names `source_repo`; the
   run supplies an instance-id → repo map (the natural companion to the grounding
   commit-map). A grounded fact whose instance is missing from that map is a wiring defect
   (`ComposeError`, loud) — not a silent blank, and not a re-ask.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pipeline import ir, review
from pipeline.api.results import CODE_SECTION_CONFORMANCE_VIOLATION
from pipeline.canonical import canonical_json_bytes
from pipeline.claims import ClaimRegistry
from pipeline.grounding import GroundedFact
from pipeline.ids import part_id
from pipeline.outline import normalize_outline, outline_digest
from pipeline.prompts import load_template
from pipeline.review import ReviewOutcome
from pipeline.sections import (
    SEVERITY_ERROR,
    Count,
    Length,
    Order,
    Presence,
    Schema,
    SectionGrammarError,
    Selector,
    Violation,
    check_conformance,
    parse_sections,
    reconstruct_rule,
)
from pipeline.spine import AdvanceHook, SpineResult, WorkUnit, drive
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, is_done, write_new
from pipeline.transport import Runner, TransportResult, invoke_headless

__all__ = [
    "CODE_CONTRACT_VIOLATION",
    "CODE_SECTION_CONFORMANCE_VIOLATION",
    "DEFAULT_MAX_ATTEMPTS",
    "WRITER_TEMPLATE",
    "ComposeError",
    "ComposeOutcome",
    "ComposeRequest",
    "build_grounding_ledger",
    "build_outline_ir",
    "build_writer_prompt",
    "compose_artifact",
    "parse_writer_output",
    "project_references",
]

#: The writer prompt-template name (`pipeline/prompts/writer.md`, §15 contract; T9).
WRITER_TEMPLATE = "writer"

#: §21.9: the bounded re-ask limit — one initial ask + two corrective re-asks. Transport
#: owns NO re-ask; this is the single re-ask point. A persistently-violating writer past
#: this bound is caught and never persisted (`CODE_CONTRACT_VIOLATION`).
DEFAULT_MAX_ATTEMPTS = 3

#: §21.7-style code: the writer never produced a contract-valid IR within the re-ask bound.
CODE_CONTRACT_VIOLATION = "compose-contract-violation"


class ComposeError(RuntimeError):
    """A compose-stage WIRING defect (missing source_repo, malformed request) — loud, typed,
    never a re-ask and never silent (§3.1). Distinct from a writer CONTRACT violation, which
    is a typed `ComposeOutcome`, not an exception."""

    code = "compose-error"


@dataclass(frozen=True)
class ComposeRequest:
    """One artifact's compose inputs — everything the writer prompt + the IR need (§15).

    `artifact_id` and `preimage` come already-minted from plan resolution (§7.2/§21.8) and
    are NEVER recomputed here — that is what keeps the roster and grounded facts out of
    identity (§9.6). `format_parts` is the Format-declared ordered role list (empty or one →
    a flat single-part body, the §15 collapse). `effective_values` is the per-dimension M2
    view for the prompt (topic/persona/format/voice/goals). `grounded_facts` is the
    grounding stage's output; `source_repos` maps each fact's instance-id to its source
    repo (the §15 ledger field). `roster` is the sibling-role compose context (§9.6 — NOT
    identity); `metadata` is the opaque §11.3 bag; `packaging_hints` maps a role to its §17
    packaging hint (default `in-document`).
    """

    artifact_id: str
    preimage: Mapping[str, Any]
    format_parts: tuple[str, ...]
    effective_values: Mapping[str, Any]
    grounded_facts: tuple[GroundedFact, ...]
    source_repos: Mapping[str, str]
    roster: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    packaging_hints: Mapping[str, str] = field(default_factory=dict)
    #: DR-3 (horn (a) / B1): the DRIVING outline brief — the stored, normalized outline
    #: Markdown (`N(md)`) the driver loads by the item's `outline-digest`. When set it inserts
    #: a HIGH-SALIENCE drive block into the writer prompt (outranks the dimensions for the body
    #: skeleton / emphasis / order) and is bound to identity by the compose digest-fidelity
    #: guard. None -> no drive block -> the prompt is byte-identical to the pre-DR-3 assembly.
    outline_brief: str | None = None

    @property
    def is_flat(self) -> bool:
        """§15 flat-body collapse: 0 or 1 declared parts → one flat body, never a parts list."""
        return len(self.format_parts) <= 1


@dataclass(frozen=True)
class ComposeOutcome:
    """One compose result — a typed outcome, never a raised exception for a writer defect.

    `status`/`code`: `ok`/`ok` (the IR was composed + persisted, or the idempotent
    `already-materialized` no-op), `error`/`compose-contract-violation` (the writer never
    produced a contract-valid IR within the re-ask bound — NEVER persisted), or
    `error`/<transport code> (a transport-level failure surfaced verbatim). `ir` is the
    persisted envelope on success (None otherwise); `spine_result` carries the §22.3
    persistence outcome; `attempts` counts writer invocations (0 on the idempotent path);
    `violations` accumulates the per-attempt contract-violation messages; `transport_result`
    is the last transport outcome (None on the idempotent path). `review` is the §19 artifact
    review (Review 1) outcome when the caller wired review in (None when review is disabled —
    the default; the review is ADVISORY and never changes `status`/`code`, §19).
    """

    status: Literal["ok", "error"]
    code: str
    artifact_id: str
    ir: Mapping[str, Any] | None
    attempts: int
    violations: tuple[str, ...]
    spine_result: SpineResult | None
    transport_result: TransportResult | None
    review: ReviewOutcome | None = None


# ---------------------------------------------------------------------------
# The grounding ledger: one entry per (fact, instance), deterministically keyed (§15 RI3).
# ---------------------------------------------------------------------------


def _anchor_strings(fact: GroundedFact) -> list[str]:
    """The §15 `traceability_anchor` field: each anchor as `<kind>:<value>` (ids/anchors
    only, never secret values — §3.3)."""
    return [f"{anchor.kind}:{anchor.value}" for anchor in fact.anchors]


def _json_safe_scores(scores: Mapping[str, Any]) -> dict[str, Any]:
    """The §15 `scores_snapshot`, JSON-native: a bare date (freshness `as_of`) becomes its
    ISO-8601 string — exactly what canonical persistence would render (§13.1), so the
    in-memory IR round-trips byte-identically to the persisted one. A timestamp has no place
    in a date-granular snapshot (§6.2) — refused loudly rather than silently coerced."""
    safe: dict[str, Any] = {}
    for key, value in scores.items():
        if isinstance(value, datetime.datetime):
            raise ComposeError(
                f"compose-error: scores_snapshot[{key!r}] is a datetime — freshness is "
                "date-granular (§6.2); no timezone policy exists to serialize it deterministically"
            )
        safe[key] = value.isoformat() if isinstance(value, datetime.date) else value
    return safe


def build_grounding_ledger(
    facts: Sequence[GroundedFact], *, source_repos: Mapping[str, str]
) -> tuple[dict[str, dict[str, Any]], tuple[tuple[str, GroundedFact], ...]]:
    """Assemble the §15 grounding ledger from resolved facts; return (ledger, entries).

    Facts are ordered deterministically (by instance, subject, claim) and keyed `f0`,
    `f1`, …; `entries` preserves that (fact-id, fact) pairing for the writer prompt. Each
    fact's instance MUST appear in `source_repos` (a wiring defect otherwise — loud
    `ComposeError`). The assembled ledger is validated immediately, so a secret-shaped
    grounded value (a credential-bearing repo URL, a token in a score) is refused LOUDLY
    before any LLM call — never a re-ask (§3.3).
    """
    ordered = sorted(facts, key=lambda f: (f.instance_id, f.subject, f.claim))
    ledger: dict[str, dict[str, Any]] = {}
    entries: list[tuple[str, GroundedFact]] = []
    for index, fact in enumerate(ordered):
        repo = source_repos.get(fact.instance_id)
        if repo is None:
            raise ComposeError(
                f"compose-error: grounded fact from instance {fact.instance_id!r} has no "
                f"source_repo in the supplied map {sorted(source_repos)} — the §15 ledger "
                "requires source_repo per fact; supply it (never a silent blank)"
            )
        # §3.3: a fact's `subject`/`claim` come straight from graph nodes and flow into the
        # writer prompt → a leaf `body` — but they never enter the ledger, so ir's ledger scan
        # can't see them. Scan them at this INPUT boundary, BEFORE any prompt is built, so a
        # secret-shaped value is refused loudly rather than copied into a persisted body. This
        # is structured, bounded EXTRACTED text — no prose false-positive risk (§3.3, PC11c).
        for value_name, value in (("subject", fact.subject), ("claim", fact.claim)):
            hit = ir.looks_secret_shaped(value)
            if hit is not None:
                raise ir.SecretShapedValueError(
                    f"ir-secret-shaped-value: grounded fact f{index} (instance "
                    f"{fact.instance_id!r}) carries a {hit}-shaped {value_name} — a fact value "
                    "must never carry a secret into the writer prompt or a persisted leaf body "
                    "(§3.3); refusing before any LLM call"
                )
        fact_id = f"f{index}"
        entry: dict[str, Any] = {
            "tier": fact.tier,
            "source_instance_id": fact.instance_id,
            "source_repo": repo,
            "source_commit": fact.commit,
            "traceability_anchor": _anchor_strings(fact),
            "scores_snapshot": _json_safe_scores(fact.scores),
        }
        # DR-6 scenario-2 carrier (§15 RI3): emit the optional `attestation` ONLY when the fact
        # carries one. Scenario-1 facts (attestation is None) leave the entry at its pre-DR-6
        # 6-field shape → byte-identical ledgers, zero churn, no artifact-id/binding impact (the
        # ledger is not an identity input, §7.2). Pass-through only — nothing here SETS attestation.
        if fact.attestation is not None:
            entry["attestation"] = fact.attestation
        ledger[fact_id] = entry
        entries.append((fact_id, fact))
    ir.validate_grounding_ledger(ledger)  # closed schema + §3.3 secret scan — loud on a secret
    return ledger, tuple(entries)


# ---------------------------------------------------------------------------
# DR-5 C2: project `references` from the ledger's DISTINCT pool sources (the machinery half of
# D1's (b)-PROJECTED model, forced by NO-GO #5). The writer NEVER authors `references`; they are
# MACHINERY-projected HERE from the grounding ledger's real per-source metadata, so every citation
# is structurally forced to point at a work the pipeline actually grounded — this closes the §6.5
# fabrication leak by CONSTRUCTION. `references` is body-blind + not an identity input (§7.2/C1),
# so projecting from the ledger moves no artifact-id.
# ---------------------------------------------------------------------------

#: The Pandoc citation sentinel: a citation opens `[@key]`. The C2 gate is a CHEAP presence check
#: for this marker over the composed leaf body/bodies — NOT a pandoc parse. C4 adds the
#: authoritative pandoc-`Cite` AST resolution (`[@key]` ⊆ the projected id set) and may refine it.
_CITATION_MARKER = "[@"


def _source_citation_keys(ledger: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """The SINGLE-SOURCED `source_instance_id -> citation_key` derivation (DR-5 C2/C3).

    ONE key `s0`, `s1`, … per DISTINCT `source_instance_id` across the ledger, in SORTED
    instance-id order — the SAME ordering `project_references` emits, so a fact's handed key is
    EXACTLY the `id` of that source's projected reference. Both the C2 reference projection
    (`project_references`) AND the C3 writer context (`_fact_context` / `_available_citations`)
    read their keys from HERE — the `s{n}` logic is defined ONCE, so the keys the writer cites with
    can NEVER drift from the projected id set C4 resolves `[@key]` against (a drift would make C4
    reject valid citations)."""
    distinct = sorted({entry["source_instance_id"] for entry in ledger.values()})
    return {instance_id: f"s{index}" for index, instance_id in enumerate(distinct)}


def project_references(ledger: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Project the §15 grounding ledger's DISTINCT pool sources into a `references` list (DR-5 C2).

    ONE CSL-JSON citation item per DISTINCT `source_instance_id` across the ledger, in SORTED
    instance-id order — mirroring `build_grounding_ledger`'s fact ordering (which sorts by
    `instance_id` first), so the projection is stable + reproducible regardless of ledger iteration
    order. Each item's citation key (`id`) comes from `_source_citation_keys` — the ordinal `s0`,
    `s1`, … mirroring the ledger's own `f0`/`f1` fact-id idiom (design ambiguity 4), SINGLE-SOURCED
    so the C3 writer context hands the writer EXACTLY these keys. That key is UNIQUE by construction
    (C1's `_validate_references` REFUSES a duplicate `id`), deterministic, and short enough for the
    C3 writer to cite as `[@s0]` (C3 receives exactly this projected id set; C4 checks `[@key]`
    ⊆ it).

    The descriptor is HONEST, per-source metadata ONLY — the writer supplies none (NO-GO #5):
      * `type` = `software` — the graphed pool source IS a code repo pinned at a commit;
      * `title` = the `source_instance_id` — the source's own name (a stable, real label);
      * `note` = `repo@commit` — the exact locator; just the repo when the adapter is commitless
        (`source_commit` is null, legal per the §15 ledger). Not a `URL`: `source_repo` is a repo
        SLUG (`github.com/acme/widget`), not a scheme-bearing dereferenceable URL — labelling it
        `URL` would be dishonest, so the locator rides the free-form `note`.
    The per-span `traceability_anchor` is deliberately NOT projected: it is FINER than per-source
    (many facts → many anchors per instance), so pinning one fact's anchor onto a source-level
    reference would misrepresent its granularity — anchors stay in the ledger where each fact owns
    its own. The non-`id` keys stay OPEN (C1's open CSL-JSON descriptor), so this shape is
    one-file-upgradeable (a `URL`/`author`/`issued` field can be added later without a schema bump).
    """
    keys = _source_citation_keys(ledger)  # SINGLE-SOURCED s{n} derivation (shared with C3)
    sources: dict[str, dict[str, Any]] = {}
    for entry in ledger.values():
        instance_id = entry["source_instance_id"]
        if instance_id not in sources:
            sources[instance_id] = {
                "repo": entry["source_repo"],
                "commit": entry.get("source_commit"),
            }
    references: list[dict[str, Any]] = []
    for instance_id in sorted(sources):
        repo = sources[instance_id]["repo"]
        commit = sources[instance_id]["commit"]
        references.append(
            {
                "id": keys[instance_id],
                "type": "software",
                "title": instance_id,
                "note": f"{repo}@{commit}" if commit else repo,
            }
        )
    return references


def _body_has_citation(writer_out: Mapping[str, Any]) -> bool:
    """True iff the composed FLAT body (or ANY part body) carries a Pandoc citation marker `[@`
    (the DR-5 C2 gate). A cheap presence check over the leaf CONTENT — NOT a pandoc parse (C4 adds
    the authoritative `Cite`-AST resolution). At C2 the writer is NOT yet taught to cite, so NO
    composed body cites → this is False for every existing (citation-clean) artifact → `references`
    attaches to NOTHING → the golden compose corpus stays BYTE-IDENTICAL. Handles both the flat
    (`{"body": …}`) and the parts (`{"parts": {role: …}}`) envelopes `parse_writer_output` returns.
    """
    if "body" in writer_out:
        return _CITATION_MARKER in writer_out["body"]
    return any(_CITATION_MARKER in body for body in writer_out["parts"].values())


# ---------------------------------------------------------------------------
# The writer prompt (§15 contract): template + grounded facts + effective values +
# Format part structure + the roster context slot (§9.6 — context, never identity).
# ---------------------------------------------------------------------------


def _fact_context(fact_id: str, fact: GroundedFact, citation_key: str) -> dict[str, Any]:
    """One grounded-fact context row for the writer prompt. `citation_key` (DR-5 C3) is the
    projected `[@key]` that cites the pool SOURCE this fact was grounded in — SINGLE-SOURCED via
    `_source_citation_keys`, so it is EXACTLY the `id` of that source's projected reference (C2).
    Prompt CONTEXT only, never identity (`references` is body-blind, C1/C2)."""
    return {
        "fact_id": fact_id,
        "tier": fact.tier,
        "subject": fact.subject,
        "claim": fact.claim,
        "citable": fact.citable,
        "source_instance": fact.instance_id,
        "citation_key": citation_key,
        "anchors": _anchor_strings(fact),
    }


def _available_citations(ledger: Mapping[str, Mapping[str, Any]]) -> list[dict[str, str]]:
    """The DR-5 C3 available-citations context slot: the C2-projected reference `id` (the citation
    key) + a short human `label` (the source's own name) for EACH distinct pool source — the FULL
    citable set the writer draws `[@key]` from. The analog of `grounded_facts`: compose CONTEXT,
    never identity (`references` is body-blind, C1/C2). Built THROUGH `project_references`, so the
    keys are EXACTLY the projected ids C4 resolves `[@key]` against."""
    refs = project_references(ledger)
    return [{"citation_key": ref["id"], "label": ref["title"]} for ref in refs]


def _structure_context(request: ComposeRequest) -> dict[str, Any]:
    if request.is_flat:
        return {
            "shape": "flat",
            "note": "single-part format — return ONE flat body (§15 flat-body collapse)",
            "output_contract": {"body": "<Markdown for the whole artifact>"},
        }
    return {
        "shape": "parts",
        "roles": list(request.format_parts),
        "note": "return ONE body per role, keyed by role; order is the roles list above",
        "output_contract": {"parts": {role: "<Markdown>" for role in request.format_parts}},
    }


def _outline_brief_blocks(brief: str) -> list[str]:
    """The HIGH-SALIENCE drive-brief block (DR-3 horn (a), FIXED posture). Present ONLY when the
    request carries an `outline_brief`; the pre-DR-3 assembly is byte-unchanged without one. The
    posture is a compose CONSTANT — the outline drives BOTH content AND structure — never a facet
    parameter, never a cascade rung, and never sets `format.parts` / any bound attr (B2)."""
    return [
        "",
        "## Drive brief — HIGHEST PRECEDENCE (DR-3, follow for BOTH content and structure)",
        (
            "An author-supplied outline drives THIS artifact. It OUTRANKS the dimension "
            "parameters above for the rhetorical body skeleton, the content emphasis, and the "
            "ordering — follow it for BOTH content and structure. It is INSTRUCTION, not grounded "
            "fact: it asserts nothing citable and licenses NO new claim. A point the outline calls "
            "for that no listed fact supports stays an INFERRED/AMBIGUOUS lead (or is left "
            "uncovered) — NEVER promote it to an EXTRACTED assertion, and never invent facts to "
            "satisfy it (the grounding discipline still binds every span, §6.5)."
        ),
        "```markdown",
        brief,
        "```",
    ]


def build_writer_prompt(
    request: ComposeRequest,
    entries: Sequence[tuple[str, GroundedFact]],
    ledger: Mapping[str, Mapping[str, Any]],
    *,
    reask_note: str | None = None,
) -> str:
    """Assemble the writer prompt: the versioned `writer.md` contract + one JSON context
    block (effective values, the Format part structure, the grounded facts with their
    fact-ids + tiers, the sibling roster, and — DR-5 C3 — each fact's `citation_key` plus the
    top-level `available_citations` set the writer may draw `[@key]` from). The roster and the
    citation keys are compose CONTEXT only (§9.6 / C1); they ride the prompt, never identity —
    `references` is projected from the ledger, never authored. The keys are SINGLE-SOURCED via
    `_source_citation_keys` (the same derivation C2's `project_references` uses), so the writer is
    handed EXACTLY the projected id set C4 resolves `[@key]` against. On a re-ask, the correction
    note is appended."""
    template = load_template(WRITER_TEMPLATE).text
    citation_keys = _source_citation_keys(ledger)  # SINGLE-SOURCED, identical to C2's projection
    context = {
        "artifact_id": request.artifact_id,
        "effective_values": request.effective_values,
        "structure": _structure_context(request),
        "grounded_facts": [
            _fact_context(fid, fact, citation_keys[fact.instance_id]) for fid, fact in entries
        ],
        "available_citations": _available_citations(ledger),
        "roster": list(request.roster),
    }
    # json (not canonical): the prompt is LLM-facing TEXT, so `default=str` may soften a
    # date/set in the effective-value view without failing — never a persisted record.
    context_json = json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    blocks = [template.rstrip(), "", "## Compose context (JSON)", "```json", context_json, "```"]
    if request.outline_brief:  # DR-3: the high-salience drive block fires ONLY when set
        blocks += _outline_brief_blocks(request.outline_brief)
    if reask_note:
        blocks += ["", "## Correction required (bounded re-ask)", reask_note]
    return "\n".join(blocks)


# ---------------------------------------------------------------------------
# The strict validation gate: parse the writer output, assemble + validate the IR.
# ---------------------------------------------------------------------------


def _extract_json_object(text: str) -> Any:
    """Parse the writer's JSON object, tolerating a code fence or surrounding prose.

    Tries the raw text, then a ```json fenced block, then the first `{` … last `}` span.
    A writer that returns no parseable JSON object is a contract violation (SchemaViolation)
    — the gate re-asks, never guesses at partial content (§3.1)."""
    for candidate in _json_candidates(text):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    raise ir.SchemaViolation(
        "ir-schema-invalid: the writer output contains no parseable JSON object (§15 RI1)"
    )


def _json_candidates(text: str) -> list[str]:
    candidates = [text.strip()]
    fence = _FENCE_RE.search(text)
    if fence is not None:
        candidates.append(fence.group(1).strip())
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        candidates.append(text[first : last + 1])
    return candidates


def parse_writer_output(text: str | None, request: ComposeRequest) -> dict[str, Any]:
    """Validate the writer's CONTENT envelope against the shape the request declared.

    Flat request → exactly `{"body": <non-empty Markdown>}`; parts request → exactly
    `{"parts": {role: <non-empty Markdown>}}` keyed by EXACTLY the Format-declared roles
    (a missing or surplus role is a violation). Raises `ir.SchemaViolation` on any
    mismatch — the writer supplies CONTENT only; the ids/binding/ledger/stamps are compose's
    (design ambiguity 1)."""
    if not isinstance(text, str) or not text.strip():
        raise ir.SchemaViolation("ir-schema-invalid: the writer returned empty output (§15)")
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        raise ir.SchemaViolation("ir-schema-invalid: the writer output must be a JSON object (§15)")
    if request.is_flat:
        if set(payload) != {"body"}:
            raise ir.SchemaViolation(
                "ir-schema-invalid: a single-part format expects exactly {'body': …} "
                f"(§15 flat-body collapse), got keys {sorted(payload)}"
            )
        if not (isinstance(payload["body"], str) and payload["body"].strip()):
            raise ir.SchemaViolation("ir-schema-invalid: writer `body` must be non-empty Markdown")
        return {"body": payload["body"]}
    if set(payload) != {"parts"}:
        raise ir.SchemaViolation(
            "ir-schema-invalid: a multi-part format expects exactly {'parts': {role: …}} "
            f"(§15 RI2), got keys {sorted(payload)}"
        )
    parts = payload["parts"]
    if not isinstance(parts, dict):
        raise ir.SchemaViolation("ir-schema-invalid: writer `parts` must be a role -> body map")
    expected = set(request.format_parts)
    if set(parts) != expected:
        raise ir.SchemaViolation(
            f"ir-schema-invalid: writer parts must cover EXACTLY the Format roles "
            f"{sorted(expected)} (§15 RI2), got {sorted(parts)}"
        )
    for role in request.format_parts:
        if not (isinstance(parts[role], str) and parts[role].strip()):
            raise ir.SchemaViolation(
                f"ir-schema-invalid: writer part {role!r} must be non-empty Markdown"
            )
    return {"parts": dict(parts)}


def _assemble_ir(
    writer_out: Mapping[str, Any], request: ComposeRequest, ledger: Mapping[str, Any]
) -> dict[str, Any]:
    """Assemble + validate the full IR from the writer's content (compose owns structure).

    Any grounding/tier/binding defect surfaces here as an `ir.IRError` (the caller re-asks).
    The `metadata` bag rides through (§11.3); an empty bag is omitted.

    DR-5 C2: `references` is MACHINERY-projected from the ledger's DISTINCT pool sources
    (`project_references`) and threaded into `build_ir` ONLY when the composed body actually carries
    a citation marker (`_body_has_citation` — the C2 gate). At C2 the writer is not yet taught to
    cite, so no body cites → `references=None` (OMIT-WHEN-ABSENT, C1) → the golden compose corpus is
    byte-identical. The projection is body-BLIND and reads only the ledger (not an identity input,
    §7.2), so it moves NO artifact-id."""
    metadata = dict(request.metadata) if request.metadata else None
    # C2 gate: attach the projection ONLY when the composed body cites (else None → byte-identical).
    references = project_references(ledger) if _body_has_citation(writer_out) else None
    if request.is_flat:
        return ir.build_ir(
            artifact_id=request.artifact_id,
            preimage=request.preimage,
            grounding=ledger,
            body=writer_out["body"],
            metadata=metadata,
            references=references,
        )
    parts = [
        {
            "part-id": part_id(request.artifact_id, role),
            "role": role,
            "packaging_hint": request.packaging_hints.get(role, ir.PACKAGING_HINT_DEFAULT),
            "body": writer_out["parts"][role],
        }
        for role in request.format_parts  # Format order = the implicit sequence (§15 RI2)
    ]
    return ir.build_ir(
        artifact_id=request.artifact_id,
        preimage=request.preimage,
        grounding=ledger,
        parts=parts,
        metadata=metadata,
        references=references,
    )


#: A fenced code block (``` or ```json) — the common wrapper an LLM puts around JSON.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


# ---------------------------------------------------------------------------
# Persistence (§22.3): the valid IR rides the S0–S6 spine, claimed on the artifact-id.
# ---------------------------------------------------------------------------


def _unreachable_payload() -> bytes:
    """The idempotent `already-materialized` path short-circuits at S0 and never runs a
    payload (§21.8); if it ever did, that is a spine-contract break — fail loudly."""
    raise ComposeError(
        "compose-error: the already-materialized idempotent path must never invoke the "
        "writer payload (§21.8/§22.3) — S0 short-circuits before S2"
    )


def _recorded_preimage_lookup(store: WorkspaceStore):
    """The S0 preimage-check reader (§7.4/§22.3): the recorded §7.2 preimage from a stored
    IR's composition binding (§15 RI4), or None when the id is unseen. Reads the OUTPUT
    STORE only (INV-CORRECTNESS, §22.7)."""

    def lookup(id_str: str) -> Any:
        try:
            raw = store.output_path(id_str).read_bytes()
        except FileNotFoundError:
            return None
        doc = json.loads(raw)
        return doc.get("binding", {}).get("preimage") if isinstance(doc, dict) else None

    return lookup


def _reask_note(violations: Sequence[str], failure_code: str) -> str:
    """The corrective note appended on a re-ask: the most recent violation + the relevant
    contract reminder. A base structural derail (DR-4 C5) points the writer at the section
    contract; every other derail points at the IR/grounding contract. Concise and
    machine-derived — never invents new requirements (§3.1)."""
    latest = violations[-1] if violations else "unspecified"
    if failure_code == CODE_SECTION_CONFORMANCE_VIOLATION:
        return _base_structural_reask_note(latest)
    return (
        f"Your previous output was REJECTED by the IR contract: {latest}. Return ONLY the "
        "JSON object in the exact shape the compose context's `structure.output_contract` "
        "declares. Reference each grounded claim inline as `[claim text]{.TIER "
        'data-fact="fN"}` using ONLY the fact-ids and tiers listed under `grounded_facts` — '
        "an unknown fact-id or a promoted tier (e.g. asserting an INFERRED lead as EXTRACTED) "
        "is rejected again."
    )


# ---------------------------------------------------------------------------
# DR-4 C5: the HARD base structural gate at compose (platform-NEUTRAL). Post-mint, INSIDE the
# bounded re-ask, the composed FLAT body's `##`-heading skeleton (C1 `parse_sections`) is checked
# against the base Format `section_schema` (C2 `check_conformance`), resolved from
# `request.effective_values["format"]` (NO new ComposeRequest field). An ERROR-severity base
# violation (required-missing / forbidden-present / an error-severity order/count/length) feeds the
# SAME bounded re-ask with a correction note; a PERSISTENT failure blocks as the NEW never-persisted
# `section-conformance-violation` (a SIBLING of `compose-contract-violation`, NOT a reuse). No-op
# when the Format declares no schema (pre-DR-4 compose bytes byte-identical); EXEMPT when a
# `section_schema`-bearing Format composes a NON-outline body (FOLDED NIT #2 — never silently
# "unconformant"). Advisory (warning/info) violations are NON-blocking here; their warn-surfacing is
# the DEFERRED Review-1 advisory check (D-4). Platform-NEUTRAL: genre BASE sections only (per-venue
# tightening is C8). The gate NEVER mutates the IR (it parses a normalized COPY of the body).
# ---------------------------------------------------------------------------


def _base_structural_reask_note(latest: str) -> str:
    """The corrective note for an ERROR-severity BASE structural violation (DR-4 C5): the specific
    breach + a concise pointer to the writer.md `Section structure` contract. Machine-derived — it
    never invents a new structural requirement (§3.1)."""
    return (
        f"Your previous output VIOLATED the Format's base section contract: {latest}. Fix ONLY the "
        "body's `##`-heading skeleton, per the 'Section structure' contract above: include every "
        "REQUIRED section (keep each required heading's exact text so its implicit slug still "
        "matches — do NOT rename or drop it), omit every FORBIDDEN section, and keep the required "
        "relative order. Return the SAME JSON shape; NEVER invent a fact to add a section (the "
        "grounding discipline still binds every claim)."
    )


def _is_outline_shaped(request: ComposeRequest) -> bool:
    """True iff this artifact's heading STRUCTURE is identity-covered by a DR-3 `outline-digest` AND
    is a single FLAT body — the precondition for the platform-NEUTRAL base gate to be meaningful
    (the `section_schema` schema-doc / FOLDED NIT #2). A NON-outline artifact (no `outline-digest`
    coverage of its structure, or a multi-part body) has no identity-covered heading skeleton to
    enforce, so the base gate treats it as EXEMPT."""
    preimage = request.preimage
    covered = isinstance(preimage, Mapping) and preimage.get("outline-digest") is not None
    return covered and request.is_flat


def _resolve_base_gate_schema(request: ComposeRequest) -> Schema | None:
    """Resolve the base Format `section_schema` to enforce at compose — reconstructed into the C2
    vocabulary — or None when the base gate does NOT apply. Two documented None cases:

    * **NO-OP** — the Format declares no `section_schema` (unset / floor `[]`), so the pre-DR-4
      compose path is byte-IDENTICAL (the gate does nothing).
    * **EXEMPT (FOLDED NIT #2)** — a `section_schema`-bearing Format composes a NON-outline body (no
      `outline-digest` identity coverage of its structure), so the gate SKIPS cleanly — never
      silently "unconformant-by-absence".

    A MALFORMED base schema is a loud wiring `ComposeError` (a bad Format entry — never a writer
    re-ask, never silent), raised BEFORE any LLM call."""
    fmt = request.effective_values.get("format")
    raw = fmt.get("section_schema") if isinstance(fmt, Mapping) else None
    if not raw:
        return None  # NO-OP: no base contract → pre-DR-4 compose bytes are byte-identical
    if not _is_outline_shaped(request):
        return None  # EXEMPT: a non-outline body has no identity-covered heading skeleton
    try:
        return tuple(reconstruct_rule(rule) for rule in raw)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ComposeError(
            f"compose-error: the Format `section_schema` is malformed ({exc}) — a base section "
            "contract must be a list of C2 conformance rules (DR-4 C5); fix the Format entry "
            "(never a writer re-ask, never silent)"
        ) from exc


def _describe_selector(selector: Selector) -> str:
    return f"{selector.axis} {selector.value!r}"


def _describe_violation(violation: Violation) -> str:
    """A concise, machine-derived description of ONE base-conformance breach for the re-ask."""
    rule = violation.rule
    if isinstance(rule, Presence):
        target = _describe_selector(rule.selector)
        if rule.required:
            return f"required base section {target} is MISSING"
        where = f" (heading {violation.section.heading!r})" if violation.section else ""
        return f"forbidden base section {target} is PRESENT{where}"
    if isinstance(rule, Order):
        seq = " -> ".join(_describe_selector(sel) for sel in rule.selectors)
        return f"base sections are out of the required order [{seq}]"
    if isinstance(rule, Count):
        return f"base section {_describe_selector(rule.selector)} breaks its count bound"
    if isinstance(rule, Length):
        where = f" (heading {violation.section.heading!r})" if violation.section else ""
        return f"base section {_describe_selector(rule.selector)} breaks its length bound{where}"
    return "base section contract violated"  # pragma: no cover — the C2 menu is closed


def _base_conformance_note(doc: Mapping[str, Any], schema: Schema) -> str | None:
    """Run the C5 base gate on the composed FLAT body; return a re-ask correction note for the
    error-severity base violations, or None when the body conforms (or carries no flat body). ONLY
    error-severity violations block via the re-ask; advisory (warning/info) violations are
    NON-blocking here (their warn-surfacing is the DEFERRED Review-1 check, D-4). NEVER mutates
    `doc` — it parses a NORMALIZED COPY of the body, so a conforming compose is byte-identical."""
    body = doc.get("body")
    if not isinstance(body, str):
        return None  # no flat body (a parts envelope is EXEMPT — filtered by _is_outline_shaped)
    try:
        sections = parse_sections(normalize_outline(body))
    except SectionGrammarError as exc:
        # The writer body declares an unknown section `type=` — a writer-correctable content defect;
        # feed it to the SAME bounded re-ask like any other base structural derail.
        return f"[{exc.code}] {exc}"
    errors = [v for v in check_conformance(sections, schema) if v.severity == SEVERITY_ERROR]
    if not errors:
        return None
    return "; ".join(_describe_violation(v) for v in errors)


def _persist(
    doc: Mapping[str, Any],
    request: ComposeRequest,
    *,
    store: WorkspaceStore,
    claims: ClaimRegistry,
    advance: AdvanceHook | None,
    lookup: Any,
) -> SpineResult:
    payload_bytes = canonical_json_bytes(doc)
    unit = WorkUnit(
        id=request.artifact_id,
        payload=lambda data=payload_bytes: data,
        preimage=request.preimage,
    )
    return drive(unit, store=store, claims=claims, recorded_preimage=lookup, advance=advance)


# ---------------------------------------------------------------------------
# Review 1 wiring (§19, PA-10): the artifact review runs POST-mint, ONCE per artifact. It is
# ADVISORY — it produces an immutable id-addressed record (`pipeline.review`, which imports NO
# SSOT module) and advances the SSOT STATUS via the write-only `review_advance` hook the caller
# supplies. It NEVER mutates the persisted IR and never changes the compose status/code.
# ---------------------------------------------------------------------------


def _run_artifact_review(
    request: ComposeRequest,
    ir_doc: Mapping[str, Any] | None,
    *,
    store: WorkspaceStore,
    review_runner: Runner | None,
    review_advance: AdvanceHook | None,
    review_model: str | None,
    review_timeout_seconds: float | None,
) -> ReviewOutcome:
    """Run the §19 artifact review after the IR is materialized, then advance the artifact SSOT
    row to `artifact-reviewed` (via the opaque `review_advance` hook — compose never imports the
    SSOT). `ir_doc` is the fresh envelope on the hot path; None on the idempotent path, where the
    review loads the persisted IR itself. Idempotent by review-record existence (§19): a re-drive
    never re-runs the LLM. The advance runs only when a record now exists (`persisted`)."""
    outcome = review.review_artifact(
        store=store,
        artifact_id=request.artifact_id,
        ir_doc=ir_doc,
        context=request.effective_values,
        runner=review_runner,
        model=review_model,
        timeout_seconds=review_timeout_seconds,
    )
    if outcome.persisted and review_advance is not None:
        review_advance(request.artifact_id)  # SSOT advance is write-only w.r.t. control flow
    return outcome


# ---------------------------------------------------------------------------
# The compose stage entry point.
# ---------------------------------------------------------------------------


def compose_artifact(
    request: ComposeRequest,
    *,
    store: WorkspaceStore,
    claims: ClaimRegistry,
    runner: Runner | None = None,
    advance: AdvanceHook | None = None,
    cwd: Path | str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    model: str | None = None,
    timeout_seconds: float | None = None,
    review_runner: Runner | None = None,
    review_advance: AdvanceHook | None = None,
    review_model: str | None = None,
    review_timeout_seconds: float | None = None,
) -> ComposeOutcome:
    """Compose one artifact: prompt → writer → strict IR gate (bounded re-ask) → persist.

    The grounding ledger is built + secret-scanned first (a secret aborts loudly before any
    LLM call, §3.3). If the artifact-id is already materialized, the writer is SKIPPED
    (idempotent no-op, §21.8) and the spine is driven only to complete lagging bookkeeping.
    Otherwise the writer is invoked (`runner` injectable for tests; real invocations run in
    a dedicated NON-REPO cwd — A2). A transport-level failure surfaces immediately with its
    own code; a CONTRACT violation re-asks up to `max_attempts`, and a persistently-violating
    writer is returned as `compose-contract-violation` and NEVER persisted. A valid IR is
    persisted via a spine claim on the artifact-id (§22.3).

    **Review 1 wiring (§19, PA-10).** When `review_advance` is supplied, the ADVISORY artifact
    review runs POST-mint (on both the fresh and the idempotent paths — ONCE per artifact by
    review-record existence), producing an immutable id-addressed record and advancing the
    artifact SSOT row to `artifact-reviewed` via the write-only hook. It NEVER mutates the
    persisted IR and never changes this outcome's `status`/`code`; its result rides
    `ComposeOutcome.review`. Review is DISABLED by default (`review_advance=None`) — the
    pre-review compose behavior is unchanged. `review_runner` is the review transport seam
    (injectable for tests; None = real transport, like the writer)."""
    if max_attempts < 1:
        raise ComposeError(f"compose-error: max_attempts must be ≥ 1, got {max_attempts}")
    # DR-3 digest-fidelity guard (horn (a)): when a drive brief is shown it MUST be exactly the
    # outline the artifact's identity claims. Bind the shown brief to the pinned preimage digest —
    # a mismatch is a loud wiring defect (NEVER a re-ask, NEVER silent, §3.1). Runs on every path
    # (fresh + idempotent) so a wrong-outline drive can never persist under a claimed id.
    if request.outline_brief is not None:
        claimed = (
            request.preimage.get("outline-digest")
            if isinstance(request.preimage, Mapping)
            else None
        )
        actual = outline_digest(normalize_outline(request.outline_brief))
        if claimed != actual:
            raise ComposeError(
                f"compose-error: the drive-brief outline-digest {actual} does not match the "
                f"artifact's claimed preimage outline-digest {claimed!r} — the shown brief must "
                "be EXACTLY the outline the identity claims (DR-3 digest fidelity); never a "
                "re-ask, never silent"
            )
    ledger, entries = build_grounding_ledger(
        request.grounded_facts, source_repos=request.source_repos
    )
    lookup = _recorded_preimage_lookup(store)

    # §19: the artifact review is wired iff the caller supplied a `review_advance` hook (the
    # driver's opt-in). A closure keeps the four review knobs out of the ok-path signatures.
    def maybe_review(ir_doc: Mapping[str, Any] | None) -> ReviewOutcome | None:
        if review_advance is None:
            return None
        return _run_artifact_review(
            request,
            ir_doc,
            store=store,
            review_runner=review_runner,
            review_advance=review_advance,
            review_model=review_model,
            review_timeout_seconds=review_timeout_seconds,
        )

    # §21.8 idempotency floor: an existing artifact is composed exactly once — no LLM.
    if is_done(store, request.artifact_id):
        idempotent_unit = WorkUnit(
            id=request.artifact_id, payload=_unreachable_payload, preimage=request.preimage
        )
        result = drive(
            idempotent_unit,
            store=store,
            claims=claims,
            recorded_preimage=lookup,
            advance=advance,
        )
        return ComposeOutcome(
            status="ok",
            code=result.code,
            artifact_id=request.artifact_id,
            ir=None,
            attempts=0,
            violations=(),
            spine_result=result,
            transport_result=None,
            review=maybe_review(None),  # §19: review runs post-mint (loads the IR if absent)
        )

    # DR-4 C5: resolve the platform-NEUTRAL base structural gate ONCE (a malformed Format
    # schema aborts LOUDLY here, before any writer call). None = the gate does not apply — no
    # Format `section_schema` (pre-DR-4 no-op, byte-identical) or a non-outline body (EXEMPT,
    # NIT #2). The gate itself runs post-mint INSIDE the bounded re-ask below (D-2 severities;
    # D-4: HARD at compose now, the advisory Review-1 check deferred).
    base_schema = _resolve_base_gate_schema(request)

    own_cwd = cwd is None
    scratch = Path(tempfile.mkdtemp(prefix="optiquity-compose-")) if own_cwd else Path(cwd)
    extra = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
    violations: list[str] = []
    last_transport: TransportResult | None = None
    last_failure_code = CODE_CONTRACT_VIOLATION  # the exhaustion code = the last derail's kind
    try:
        for attempt in range(1, max_attempts + 1):
            note = _reask_note(violations, last_failure_code) if violations else None
            prompt = build_writer_prompt(request, entries, ledger, reask_note=note)
            transport = invoke_headless(prompt, cwd=scratch, runner=runner, model=model, **extra)
            last_transport = transport
            if transport.status != "ok":
                # A transport-level failure — re-asking cannot fix an account-side condition.
                return ComposeOutcome(
                    status="error",
                    code=transport.code,
                    artifact_id=request.artifact_id,
                    ir=None,
                    attempts=attempt,
                    violations=tuple(violations),
                    spine_result=None,
                    transport_result=transport,
                )
            try:
                writer_out = parse_writer_output(transport.text, request)
                doc = _assemble_ir(writer_out, request, ledger)
            except ir.IRError as exc:
                # A CONTRACT violation rides this ONE catch → `violations` → the bounded re-ask:
                # unparseable/mis-shaped JSON, unknown fact-id, tier mismatch, AND the §15 substance
                # floor `ir.EmptySubstanceError` (`ir-empty-substance`, GAP-6 — a `"..."` or a
                # markup-wrapped placeholder that PARSES yet ships empty). On exhaustion it is
                # caught and NEVER persisted (`compose-contract-violation`); the substance-specific
                # message surfaces to the model via `_reask_note` (`violations[-1]`).
                violations.append(f"[{exc.code}] {exc}")
                last_failure_code = CODE_CONTRACT_VIOLATION
                continue  # bounded re-ask (§21.9)
            # DR-4 C5 base structural gate (platform-NEUTRAL), post-mint, INSIDE the bounded re-ask:
            # an ERROR-severity base violation (required-missing / forbidden-present / order) feeds
            # the SAME re-ask with a correction note; a PERSISTENT failure blocks as the NEW
            # never-persisted `section-conformance-violation` (a SIBLING of the contract violation,
            # NOT a reuse). No-op / EXEMPT when `base_schema is None`; advisory severities never
            # block (D-2 / D-4). The gate never mutates `doc`, so a pass is byte-exact.
            if base_schema is not None:
                base_note = _base_conformance_note(doc, base_schema)
                if base_note is not None:
                    violations.append(base_note)
                    last_failure_code = CODE_SECTION_CONFORMANCE_VIOLATION
                    continue  # bounded re-ask (§21.9 / D-2)
            result = _persist(
                doc, request, store=store, claims=claims, advance=advance, lookup=lookup
            )
            return ComposeOutcome(
                status="ok",
                code=result.code,
                artifact_id=request.artifact_id,
                ir=doc,
                attempts=attempt,
                violations=tuple(violations),
                spine_result=result,
                transport_result=transport,
                review=maybe_review(doc),  # §19: Review 1, post-mint, on the fresh IR
            )
        # Re-ask bound exhausted: caught, and NEVER persisted (§21.9). The exhaustion CODE is the
        # LAST derail's kind — `section-conformance-violation` when the terminal failure was the
        # DR-4 base structural gate, else `compose-contract-violation` (the IR/grounding contract).
        return ComposeOutcome(
            status="error",
            code=last_failure_code,
            artifact_id=request.artifact_id,
            ir=None,
            attempts=max_attempts,
            violations=tuple(violations),
            spine_result=None,
            transport_result=last_transport,
        )
    finally:
        if own_cwd:
            shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# The DR-3 emit bridge (Commit 4): an outline -> an ordinary `Format=outline` IR.
# ---------------------------------------------------------------------------


def build_outline_ir(
    canonical_md: str,
    *,
    artifact_id: str,
    preimage: Mapping[str, Any],
    store: WorkspaceStore,
) -> dict[str, Any]:
    """Realize an outline as an ordinary `Format=outline` IR artifact (DR-3 Commit 4, horn (a)).

    A THIN bridge through the EXISTING machinery — NO new IR type, NO schema change, NO new
    registry root. The IR `body` IS the canonical outline Markdown,
    `normalize_outline(canonical_md)` (N): a WRAP, never a transform. The grounding ledger is EMPTY
    (`{}`) and the body carries NO `data-fact` spans, so the emitted envelope is an ORDINARY
    flat-body artifact — `validate_ir` (run inside `ir.build_ir`) accepts it, `render` fits +
    serializes it, and `fetch-by-id` / `emit-manifest` resolve it by `parse_id`, with NO
    special-casing (S5/Part-D: a flat body has no part circularity; `outline` is non-parametric).

    Identity (PO-4, the R4 own-body exception): the CALLER supplies the already-minted `artifact_id`
    and its §7.2 `preimage` (which carries `format=outline` + the `outline-digest` of THIS body —
    constructed by the caller in Commit 6, NEVER here). `ir.build_ir` re-mints from that preimage
    and refuses a mismatch (`BindingMismatchError`), so the recorded id always reproduces from
    `mint_artifact_id(binding["preimage"])` and a forged id can never persist. This helper only
    WRAPS and PERSISTS — it never constructs the preimage and never re-mints.

    Persistence rides the existing no-replace `write_new` path (§22.3 existence authority): a
    same-id re-emit of the SAME outline (identical digest -> identical preimage -> identical body ->
    byte-identical envelope) is the designed `already-materialized` no-op, swallowed idempotently so
    the winner's bytes stand untouched (§22.7). Returns the validated envelope.
    """
    body = normalize_outline(canonical_md)
    doc = ir.build_ir(
        artifact_id=artifact_id,
        preimage=preimage,
        grounding={},
        body=body,
    )
    try:
        write_new(store.output_path(artifact_id), canonical_json_bytes(doc))
    except AlreadyMaterializedError:
        pass  # idempotent: the same outline is already emitted; the old bytes stand (§22.7)
    return doc
