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

from pipeline import ir
from pipeline.canonical import canonical_json_bytes
from pipeline.claims import ClaimRegistry
from pipeline.grounding import GroundedFact
from pipeline.ids import part_id
from pipeline.prompts import load_template
from pipeline.spine import AdvanceHook, SpineResult, WorkUnit, drive
from pipeline.store import WorkspaceStore, is_done
from pipeline.transport import Runner, TransportResult, invoke_headless

__all__ = [
    "CODE_CONTRACT_VIOLATION",
    "DEFAULT_MAX_ATTEMPTS",
    "WRITER_TEMPLATE",
    "ComposeError",
    "ComposeOutcome",
    "ComposeRequest",
    "build_grounding_ledger",
    "build_writer_prompt",
    "compose_artifact",
    "parse_writer_output",
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
    is the last transport outcome (None on the idempotent path).
    """

    status: Literal["ok", "error"]
    code: str
    artifact_id: str
    ir: Mapping[str, Any] | None
    attempts: int
    violations: tuple[str, ...]
    spine_result: SpineResult | None
    transport_result: TransportResult | None


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
        ledger[fact_id] = {
            "tier": fact.tier,
            "source_instance_id": fact.instance_id,
            "source_repo": repo,
            "source_commit": fact.commit,
            "traceability_anchor": _anchor_strings(fact),
            "scores_snapshot": _json_safe_scores(fact.scores),
        }
        entries.append((fact_id, fact))
    ir.validate_grounding_ledger(ledger)  # closed schema + §3.3 secret scan — loud on a secret
    return ledger, tuple(entries)


# ---------------------------------------------------------------------------
# The writer prompt (§15 contract): template + grounded facts + effective values +
# Format part structure + the roster context slot (§9.6 — context, never identity).
# ---------------------------------------------------------------------------


def _fact_context(fact_id: str, fact: GroundedFact) -> dict[str, Any]:
    return {
        "fact_id": fact_id,
        "tier": fact.tier,
        "subject": fact.subject,
        "claim": fact.claim,
        "citable": fact.citable,
        "source_instance": fact.instance_id,
        "anchors": _anchor_strings(fact),
    }


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


def build_writer_prompt(
    request: ComposeRequest,
    entries: Sequence[tuple[str, GroundedFact]],
    *,
    reask_note: str | None = None,
) -> str:
    """Assemble the writer prompt: the versioned `writer.md` contract + one JSON context
    block (effective values, the Format part structure, the grounded facts with their
    fact-ids + tiers, and the sibling roster). The roster is compose CONTEXT only (§9.6);
    it rides the prompt, never identity. On a re-ask, the correction note is appended."""
    template = load_template(WRITER_TEMPLATE).text
    context = {
        "artifact_id": request.artifact_id,
        "effective_values": request.effective_values,
        "structure": _structure_context(request),
        "grounded_facts": [_fact_context(fid, fact) for fid, fact in entries],
        "roster": list(request.roster),
    }
    # json (not canonical): the prompt is LLM-facing TEXT, so `default=str` may soften a
    # date/set in the effective-value view without failing — never a persisted record.
    context_json = json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False, default=str)
    blocks = [template.rstrip(), "", "## Compose context (JSON)", "```json", context_json, "```"]
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
    The `metadata` bag rides through (§11.3); an empty bag is omitted."""
    metadata = dict(request.metadata) if request.metadata else None
    if request.is_flat:
        return ir.build_ir(
            artifact_id=request.artifact_id,
            preimage=request.preimage,
            grounding=ledger,
            body=writer_out["body"],
            metadata=metadata,
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


def _reask_note(violations: Sequence[str]) -> str:
    """The corrective note appended on a re-ask: the most recent violation + the contract
    reminder. Concise and machine-derived — never invents new requirements (§3.1)."""
    latest = violations[-1] if violations else "unspecified"
    return (
        f"Your previous output was REJECTED by the IR contract: {latest}. Return ONLY the "
        "JSON object in the exact shape the compose context's `structure.output_contract` "
        "declares. Reference each grounded claim inline as `[claim text]{.TIER "
        'data-fact="fN"}` using ONLY the fact-ids and tiers listed under `grounded_facts` — '
        "an unknown fact-id or a promoted tier (e.g. asserting an INFERRED lead as EXTRACTED) "
        "is rejected again."
    )


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
    """
    if max_attempts < 1:
        raise ComposeError(f"compose-error: max_attempts must be ≥ 1, got {max_attempts}")
    ledger, entries = build_grounding_ledger(
        request.grounded_facts, source_repos=request.source_repos
    )
    lookup = _recorded_preimage_lookup(store)

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
        )

    own_cwd = cwd is None
    scratch = Path(tempfile.mkdtemp(prefix="optiquity-compose-")) if own_cwd else Path(cwd)
    extra = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
    violations: list[str] = []
    last_transport: TransportResult | None = None
    try:
        for attempt in range(1, max_attempts + 1):
            note = _reask_note(violations) if violations else None
            prompt = build_writer_prompt(request, entries, reask_note=note)
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
                violations.append(f"[{exc.code}] {exc}")
                continue  # bounded re-ask (§21.9)
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
            )
        # Re-ask bound exhausted: caught, and NEVER persisted (§21.9).
        return ComposeOutcome(
            status="error",
            code=CODE_CONTRACT_VIOLATION,
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
