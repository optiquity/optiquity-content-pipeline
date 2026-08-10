"""The two review gates (§19) — PURE producers of immutable, id-addressed review records.

Design authority: `docs/design.md`
  §19 (Q16, FR5, FR7.5) — the two complementary reviews:
        1. **Artifact review (Review 1) — the early substance gate.** A full content/quality
           review of the platform-neutral IR, run **ONCE per artifact, before rendering**
           (pre-fanout — one review amortized over every deliverable). Reads the IR +
           grounding ledger; verifies grounding (the EXTRACTED publish floor, §6.5), goal
           fit, persona fit, and citability (§6.5). Keyed by `artifact-id`.
        2. **Deliverable review (Review 2) — the complete final validation.** A **FULL**
           review of **EVERY** final deliverable — including every fit-revision and every
           serialize-revision deliverable (FR5, FR7.5) — checking substance, §16 rendering
           fidelity, the per-claim provenance bindings at the IR-fitted/AST layer (§17),
           platform hard limits, and correct format/splits. Keyed by `deliverable-id`. A
           revision is a NEW deliverable with a NEW id → its OWN review; a review record
           **NEVER transfers across revisions** (§19).
  §6.5 — the EXTRACTED publish floor + `traceability` ⟂ tier: the review consumes citability
        independently of confidence. Only EXTRACTED facts publish as fact; INFERRED/AMBIGUOUS
        are leads. This gate never *enforces* the floor (that is compose's/reconcile's job,
        upstream) — it *reports* residual soft advisories (§19: "reviews handle residual soft
        advisories … and full-content quality"; hard drift/limits block earlier).
  §16 — the pass-1 fidelity constraint the deliverable review re-checks at the fitted layer:
        voice/content parameters preserved, meaning intact, per-claim provenance/tier bindings
        re-anchored (never promoted). The bindings are consumed at the IR/AST layers only,
        NEVER recovered from output bytes (§17) — so this gate reads the fitted IR + the AST,
        never the layer-2 bytes.
  §24 — the review OUTCOME advances the SSOT status (artifact rows → `artifact-reviewed`;
        deliverable rows → `deliverable-reviewed`). **That advance is NOT this module's job:**
        this module is INV-CORRECTNESS-clean of the SSOT (it imports NO SSOT module) — it
        PRODUCES + PERSISTS the record and returns a typed outcome; the caller (compose /
        dispatch, via the write-only `AdvanceHook` the driver supplies) performs the advance.
        A review advances STATUS ONLY and **NEVER mutates the content-addressed output** — this
        module writes ONLY under `reviews/<reviewed-id>` and reads (never writes) the
        artifact/deliverable records.
  PA-9d / §19 / §23 — records persist IMMUTABLE + id-addressed at the store's `reviews/<id>`
        home (`WorkspaceStore.review_path`), through the store's NO-REPLACE commit
        (`write_new`): a second write to the same reviewed-id is REFUSED, never overwritten
        (§22.3 existence authority). The filename is the reviewed id EXACTLY (§7.4 filename
        discipline — extension-free, exactly like the IR/deliverable records under
        `artifacts/`/`deliverables/`; the plan's `<id>.json` names the JSON *content*, not a
        literal extension).

**Reviews are ADVISORY (§19).** Hard drift and hard limits never reach review — they block
earlier (§11.5, §16). A review therefore never *blocks* the pipeline: it records a `verdict`
(`pass` | `concerns`) with per-check advisories and full-content quality notes. A transport
failure or a persistently-malformed reviewer is surfaced as a typed `error` outcome that
produces NO record and NO advance — the item's SSOT row simply lags at `composed`/`rendered`
(the lagging-projection posture, §22.7), never a crash and never a false review.

**Reuse, never reinvent.** The LLM call rides `pipeline.transport` (`invoke_headless`, MOCKED
in tests via an injected `runner`); the prompt-template loader is `pipeline.prompts`; the
no-secrets scan reuses `pipeline.ir.looks_secret_shaped` (§3.3: a review note that echoed a
secret is refused before persistence); persistence rides `pipeline.store` (`review_path` +
`write_new`). This module imports NO SSOT module (INV-CORRECTNESS, §22.7).

In-latitude decisions (step-30 coder; documented for the reviewer):

- **Separation of authority (mirrors compose/reconcile).** The reviewer LLM supplies a typed
  ASSESSMENT ONLY (`{verdict, checks, summary}`); this module owns the record's identity
  fields (`reviewed_id`, `reviewed_digest`, the version + type stamps, `minted_ts`). A
  reviewer cannot forge the id, the content digest it is bound to, or the review type.
- **The bounded re-ask (mirrors compose's §21.9 re-ask).** `DEFAULT_MAX_ATTEMPTS = 3`: a
  malformed assessment (unparseable JSON, wrong check set, bad verdict/status) appends a
  correction note and re-asks up to the bound; a persistently-malformed reviewer is returned
  as a typed `review-contract-violation` outcome and NEVER persisted (advisory — it does not
  block). A TRANSPORT-level failure surfaces immediately with its own code (re-asking cannot
  fix an account-side condition).
- **`reviewed_digest` binds the record to the exact content it reviewed** — the artifact's
  composition-binding digest (§15 RI4) for Review 1, and a canonical digest over the fitted IR
  + the AST for Review 2. It is provenance, never identity: the record's id-address IS its
  identity (`reviews/<reviewed-id>`).
- **Idempotency by output existence (mirrors §21.8/§22.3).** A review checks `review_path`
  existence FIRST and short-circuits to `already-reviewed` with ZERO LLM cost — so a re-drive
  after a crash (or a re-compose of an already-materialized artifact) never re-runs the LLM,
  and the once-per-artifact guarantee holds even under re-entry. `write_new` is the ultimate
  authority: a lost race on persistence is caught as `already-reviewed`, never an overwrite.
- **`minted_ts` is a RECORD field only** — it never enters the reviewed-id or the
  reviewed-digest, so a re-review of the same content would bind to the same digest; the store
  refuses the second write regardless.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pipeline import ir
from pipeline.canonical import canonical_json_bytes, digest_full
from pipeline.prompts import load_template
from pipeline.store import AlreadyMaterializedError, WorkspaceStore, write_new
from pipeline.transport import Runner, TransportPlan, TransportResult, invoke_headless

__all__ = [
    "ARTIFACT_CHECKS",
    "ARTIFACT_REVIEWER_TEMPLATE",
    "CHECK_STATUSES",
    "CODE_ALREADY_REVIEWED",
    "CODE_CONTRACT_VIOLATION",
    "CODE_REVIEWED",
    "DELIVERABLE_CHECKS",
    "DELIVERABLE_REVIEWER_TEMPLATE",
    "DEFAULT_MAX_ATTEMPTS",
    "REVIEW_RECORD_FIELDS",
    "REVIEW_VERSION",
    "VERDICTS",
    "ReviewError",
    "ReviewOutcome",
    "ReviewSchemaViolation",
    "build_artifact_review_prompt",
    "build_deliverable_review_prompt",
    "build_review_record",
    "parse_review_output",
    "persist_review_record",
    "review_artifact",
    "review_deliverable",
    "validate_review_record",
]

#: The two reviewer prompt-template names (`pipeline/prompts/*.md`, §19 contracts; T9).
ARTIFACT_REVIEWER_TEMPLATE = "artifact_reviewer"
DELIVERABLE_REVIEWER_TEMPLATE = "deliverable_reviewer"

#: §19-review record schema generation (a provenance stamp; a review record is immutable and
#: never migrated — it attaches to one id forever, §19).
REVIEW_VERSION = 1

#: §21.9-style bounded re-ask limit — one initial ask + two corrective re-asks. Mirrors
#: compose (§15) and reconcile (§16): the review LLM path owns the ONLY re-ask; a
#: persistently-malformed assessment past this bound is caught and NEVER persisted (advisory).
DEFAULT_MAX_ATTEMPTS = 3

#: §19 Review 1 check set (artifact review — reads the IR + ledger). CLOSED: a record must
#: carry EXACTLY these check keys, so a reviewer can neither drop a required check nor smuggle
#: an unexpected one.
ARTIFACT_CHECKS: tuple[str, ...] = (
    "grounding",
    "extracted_floor",
    "goal_fit",
    "persona_fit",
    "citability",
)

#: §19 Review 2 check set (deliverable review — the FULL final validation). CLOSED.
DELIVERABLE_CHECKS: tuple[str, ...] = (
    "substance",
    "fidelity",
    "provenance_bindings",
    "hard_limits",
    "format_splits",
)

#: The advisory verdict vocabulary (§19). `pass` = ship; `concerns` = residual soft advisories
#: the human/publisher weighs — NEVER a pipeline block (hard conditions block upstream, §16).
VERDICTS: tuple[str, ...] = ("pass", "concerns")

#: Per-check advisory status (§19). `concern` is an advisory flag, never a block.
CHECK_STATUSES: tuple[str, ...] = ("pass", "concern")

#: The CLOSED review-record key set (§19; PA-9d). An undeclared key is a smuggling surface.
REVIEW_RECORD_FIELDS: tuple[str, ...] = (
    "review_version",
    "review_type",
    "reviewed_id",
    "reviewed_digest",
    "verdict",
    "checks",
    "summary",
    "minted_ts",
)

#: §21.7-style outcome codes.
CODE_REVIEWED = "reviewed"  #: a fresh review was produced + persisted this call.
CODE_ALREADY_REVIEWED = "already-reviewed"  #: a record already existed — idempotent, zero LLM.
CODE_CONTRACT_VIOLATION = "review-contract-violation"  #: persistently malformed — NEVER persisted.

#: The per-check assessment sub-schema keys (closed).
_CHECK_KEYS = frozenset({"status", "note"})

#: A fenced code block (``` or ```json) — the common wrapper an LLM puts around JSON.
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)


class ReviewError(RuntimeError):
    """A review-stage WIRING defect (a malformed request, a wrong-level reviewed id, a missing
    IR) — loud, typed, never a re-ask and never silent (§3.1). Distinct from a reviewer
    CONTRACT violation, which is a typed `ReviewOutcome`, not an exception."""

    code = "review-error"


class ReviewSchemaViolation(ValueError):
    """The reviewer's assessment envelope violates the §19 typed output contract (shape, keys,
    verdict/status vocabulary, or a secret-shaped note) — the gate re-asks, never guesses."""

    code = "review-schema-invalid"


@dataclass(frozen=True)
class ReviewOutcome:
    """One review result — a typed outcome, never a raised exception for a reviewer defect.

    `status`/`code`: `ok`/`reviewed` (a fresh assessment was produced + persisted), `ok`/
    `already-reviewed` (a record already existed — idempotent, zero LLM), `error`/
    `review-contract-violation` (the reviewer never produced a contract-valid assessment within
    the re-ask bound — NEVER persisted), or `error`/<transport code> (a transport-level failure
    surfaced verbatim). `persisted` is True whenever a review record EXISTS for this id after
    the call (freshly written OR pre-existing) — the caller advances the SSOT status iff
    `persisted`. `record` is the freshly-built record on `reviewed` (None otherwise — an
    already-reviewed call does not re-read the existing record; identity is the id-address).
    `verdict` is the advisory verdict on a produced review (None on error). `attempts` counts
    reviewer invocations (0 on the idempotent path); `violations` accumulates the per-attempt
    contract-violation messages; `transport_result` is the last transport outcome (None when no
    LLM ran)."""

    status: Literal["ok", "error"]
    code: str
    review_type: Literal["artifact", "deliverable"]
    reviewed_id: str
    persisted: bool
    record: Mapping[str, Any] | None
    verdict: str | None
    attempts: int
    violations: tuple[str, ...]
    transport_result: TransportResult | None


# ---------------------------------------------------------------------------
# The no-secrets scan (§3.3): a review note must never carry a secret into a persisted record.
# ---------------------------------------------------------------------------


def _scan_no_secrets(obj: Any, where: str) -> None:
    """Refuse any secret-shaped STRING anywhere under `obj` (§3.3), reusing the `ir` scanner's
    pattern set so the review record honors the same no-secrets guarantee as the IR/ledger. A
    reviewer that echoed a credential from the content into its note is refused before persist."""
    if isinstance(obj, str):
        hit = ir.looks_secret_shaped(obj)
        if hit is not None:
            raise ReviewSchemaViolation(
                f"review-schema-invalid: {where} carries a {hit}-shaped value — a review record "
                "stores an advisory assessment, NEVER a secret (§3.3); refusing to persist it"
            )
        return
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            _scan_no_secrets(key, f"{where} (key)")
            _scan_no_secrets(value, f"{where}.{key}")
        return
    if isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _scan_no_secrets(item, f"{where}[{i}]")


# ---------------------------------------------------------------------------
# The typed reviewer output contract (§19): {verdict, checks, summary} — CONTENT only.
# ---------------------------------------------------------------------------


def _extract_json_object(text: str) -> Any:
    """Parse the reviewer's JSON object, tolerating a code fence or surrounding prose (raw,
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
    raise ReviewSchemaViolation(
        "review-schema-invalid: the reviewer output contains no parseable JSON object (§19)"
    )


def parse_review_output(text: str | None, *, checks: Sequence[str]) -> dict[str, Any]:
    """Validate the reviewer's assessment envelope against the §19 typed contract.

    Exactly `{verdict, checks, summary}`: `verdict ∈ VERDICTS`; `checks` covers EXACTLY the
    review type's `checks` set, each `{status ∈ CHECK_STATUSES, note: str}`; `summary` a
    string. Raises `ReviewSchemaViolation` on any mismatch (or a secret-shaped note) — the
    reviewer supplies an ASSESSMENT only; the record's identity fields are the machinery's."""
    if not isinstance(text, str) or not text.strip():
        raise ReviewSchemaViolation(
            "review-schema-invalid: the reviewer returned empty output (§19)"
        )
    payload = _extract_json_object(text)
    if not isinstance(payload, dict) or set(payload) != {"verdict", "checks", "summary"}:
        raise ReviewSchemaViolation(
            "review-schema-invalid: the reviewer output must be exactly {verdict, checks, summary} "
            f"(§19), got {sorted(payload) if isinstance(payload, dict) else type(payload).__name__}"
        )
    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise ReviewSchemaViolation(
            f"review-schema-invalid: verdict must be one of {VERDICTS} (§19), got {verdict!r}"
        )
    assessed = payload["checks"]
    expected = set(checks)
    if not isinstance(assessed, dict) or set(assessed) != expected:
        raise ReviewSchemaViolation(
            f"review-schema-invalid: `checks` must cover EXACTLY {sorted(expected)} (§19), got "
            f"{sorted(assessed) if isinstance(assessed, dict) else type(assessed).__name__}"
        )
    clean_checks: dict[str, dict[str, Any]] = {}
    for name, result in assessed.items():
        if not isinstance(result, dict) or set(result) != _CHECK_KEYS:
            raise ReviewSchemaViolation(
                f"review-schema-invalid: check {name!r} must be exactly {{status, note}} (§19), "
                f"got {sorted(result) if isinstance(result, dict) else type(result).__name__}"
            )
        if result["status"] not in CHECK_STATUSES:
            raise ReviewSchemaViolation(
                f"review-schema-invalid: check {name!r} status must be one of {CHECK_STATUSES} "
                f"(§19), got {result['status']!r}"
            )
        if not isinstance(result["note"], str):
            raise ReviewSchemaViolation(
                f"review-schema-invalid: check {name!r} note must be a string (§19)"
            )
        clean_checks[name] = {"status": result["status"], "note": result["note"]}
    if not isinstance(payload["summary"], str):
        raise ReviewSchemaViolation("review-schema-invalid: `summary` must be a string (§19)")
    result = {"verdict": verdict, "checks": clean_checks, "summary": payload["summary"]}
    _scan_no_secrets(result, "reviewer assessment")  # §3.3 — refuse a secret-shaped note
    return result


# ---------------------------------------------------------------------------
# The review record (§19; PA-9d): typed, closed schema, secret-scanned.
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """Wall-clock UTC ISO-8601 — the DEFAULT `minted_ts` (a RECORD field only, never identity
    and never in the reviewed-digest; mirrors reconcile's fit-binding `minted_ts`)."""
    return datetime.datetime.now(datetime.UTC).isoformat()


def build_review_record(
    *,
    review_type: Literal["artifact", "deliverable"],
    reviewed_id: str,
    reviewed_digest: str,
    assessment: Mapping[str, Any],
    minted_ts: str | None = None,
) -> dict[str, Any]:
    """Assemble one §19 review record from the reviewer's typed `assessment` + the machinery's
    identity fields. `reviewed_digest` binds the record to the EXACT content reviewed (§15 RI4
    digest for an artifact; the fitted-IR+AST digest for a deliverable). `minted_ts` is a record
    field ONLY — never in the reviewed-id or the digest, so identity is the id-address alone.
    The assembled record is validated (closed schema + secret scan) before it is returned."""
    record = {
        "review_version": REVIEW_VERSION,
        "review_type": review_type,
        "reviewed_id": reviewed_id,
        "reviewed_digest": reviewed_digest,
        "verdict": assessment["verdict"],
        "checks": {name: dict(result) for name, result in assessment["checks"].items()},
        "summary": assessment["summary"],
        "minted_ts": minted_ts if minted_ts is not None else _now_iso(),
    }
    validate_review_record(record)
    return record


def validate_review_record(record: Any) -> None:
    """Validate one §19 review record: the CLOSED key set, the review type + its check set, the
    verdict/status vocabulary, and the §3.3 no-secrets scan. Raises `ReviewSchemaViolation`."""
    if not isinstance(record, Mapping) or set(record) != set(REVIEW_RECORD_FIELDS):
        got = sorted(record) if isinstance(record, Mapping) else type(record).__name__
        raise ReviewSchemaViolation(
            f"review-schema-invalid: a review record carries EXACTLY "
            f"{sorted(REVIEW_RECORD_FIELDS)} (§19), got {got}"
        )
    if record["review_version"] != REVIEW_VERSION:
        raise ReviewSchemaViolation(
            f"review-schema-invalid: review_version must be {REVIEW_VERSION}, got "
            f"{record['review_version']!r}"
        )
    review_type = record["review_type"]
    if review_type not in ("artifact", "deliverable"):
        raise ReviewSchemaViolation(
            f"review-schema-invalid: review_type must be artifact|deliverable, got {review_type!r}"
        )
    expected = ARTIFACT_CHECKS if review_type == "artifact" else DELIVERABLE_CHECKS
    checks = record["checks"]
    if not isinstance(checks, Mapping) or set(checks) != set(expected):
        raise ReviewSchemaViolation(
            f"review-schema-invalid: a {review_type} review's `checks` must cover EXACTLY "
            f"{sorted(expected)} (§19), got "
            f"{sorted(checks) if isinstance(checks, Mapping) else type(checks).__name__}"
        )
    if record["verdict"] not in VERDICTS:
        raise ReviewSchemaViolation(
            f"review-schema-invalid: verdict must be one of {VERDICTS}, got {record['verdict']!r}"
        )
    for name, result in checks.items():
        if not isinstance(result, Mapping) or set(result) != _CHECK_KEYS:
            raise ReviewSchemaViolation(
                f"review-schema-invalid: check {name!r} must be exactly {{status, note}} (§19)"
            )
        if result["status"] not in CHECK_STATUSES:
            raise ReviewSchemaViolation(
                f"review-schema-invalid: check {name!r} status must be one of {CHECK_STATUSES}"
            )
    _scan_no_secrets(record, "review record")


# ---------------------------------------------------------------------------
# Persistence (§19/PA-9d): IMMUTABLE + id-addressed under `reviews/`, no-replace commit.
# ---------------------------------------------------------------------------


def persist_review_record(store: WorkspaceStore, record: Mapping[str, Any]) -> bool:
    """Persist one review record IMMUTABLY at `reviews/<reviewed-id>` via the store's NO-REPLACE
    commit (§22.3). Returns True iff THIS call wrote the record; False when the id was already
    materialized (a lost race or a re-drive) — the pre-existing record is left untouched, never
    overwritten (§22.3 existence authority). The record is re-validated before the write so a
    malformed record can never reach the store."""
    validate_review_record(record)
    target = store.review_path(record["reviewed_id"])
    try:
        write_new(target, canonical_json_bytes(record))
    except AlreadyMaterializedError:
        return False
    return True


# ---------------------------------------------------------------------------
# The reviewer prompts (§19 contracts): template + a faithful JSON review context.
# ---------------------------------------------------------------------------


def _content_view(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The leaves under review — the flat body or the role→body map (each carries its inline
    `[claim]{.TIER data-fact="fN"}` provenance spans, so the reviewer sees the bindings)."""
    if "body" in doc:
        return {"shape": "flat", "body": doc["body"]}
    return {
        "shape": "parts",
        "parts": {part["role"]: part["body"] for part in doc.get("parts", ())},
    }


def _coordinate_view(doc: Mapping[str, Any]) -> dict[str, Any]:
    """The artifact's resolved coordinates for goal/persona fit — read from the IR's composition
    binding preimage (§7.2, delta-vs-floor: entry ids + goal-set + source subset). Content is
    judged against the coordinates it was composed for; the preimage is the only in-IR carrier."""
    return dict(doc.get("binding", {}).get("preimage", {}))


def _review_context_block(context: Mapping[str, Any]) -> str:
    """Render one JSON "Review context" block (json, not canonical: LLM-facing text — `default=str`
    may soften a date/set in a supplementary value without failing; never a persisted record)."""
    return json.dumps(context, indent=2, sort_keys=True, ensure_ascii=False, default=str)


def build_artifact_review_prompt(
    ir_doc: Mapping[str, Any], *, context: Mapping[str, Any] | None = None
) -> str:
    """Assemble the artifact-review prompt: the versioned `artifact_reviewer.md` contract + one
    JSON context block (the IR content leaves, the grounding ledger, the resolved coordinates,
    and any supplementary effective-value `context` the caller supplies for goal/persona fit)."""
    template = load_template(ARTIFACT_REVIEWER_TEMPLATE).text
    block = {
        "artifact_id": ir_doc.get("binding", {}).get("artifact_id"),
        "coordinates": _coordinate_view(ir_doc),
        "content": _content_view(ir_doc),
        "grounding_ledger": ir_doc.get("grounding", {}),
        "effective_values": dict(context) if context else {},
    }
    blocks = [
        template.rstrip(),
        "",
        "## Review context (JSON)",
        "```json",
        _review_context_block(block),
        "```",
    ]
    return "\n".join(blocks)


def _ast_provenance_summary(ast: Mapping[str, Any]) -> dict[str, Any]:
    """A bounded AST-layer fingerprint (§17 RI8): the count of DISTINCT provenance facts
    (`data-fact` kv) surviving into the AST and the tier classes they carry, plus the top-level
    block types (two Spans citing one fact count as one — this is the distinct-fact count).
    Lets the deliverable review cross-check that provenance bindings survived to the AST layer
    WITHOUT shipping the whole (potentially large) AST into the prompt (§19 reads IR/AST)."""
    fact_ids: set[str] = set()
    tiers: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, Mapping):
            if node.get("t") == "Span":
                attr = node.get("c", [None])[0]
                if isinstance(attr, (list, tuple)) and len(attr) == 3:
                    classes, kvs = attr[1], attr[2]
                    kv_map = {k: v for k, v in kvs} if isinstance(kvs, (list, tuple)) else {}
                    if "data-fact" in kv_map:
                        fact_ids.add(kv_map["data-fact"])
                        tiers.update(c for c in classes if c in ir.TIERS)
            for value in node.values():
                walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(ast)
    blocks = ast.get("blocks", []) if isinstance(ast, Mapping) else []
    block_types = [b.get("t") for b in blocks if isinstance(b, Mapping)]
    return {
        "provenance_fact_count": len(fact_ids),
        "provenance_fact_ids": sorted(fact_ids),
        "provenance_tiers": sorted(tiers),
        "top_level_block_types": block_types,
    }


def build_deliverable_review_prompt(
    fitted_ir: Mapping[str, Any],
    ast: Mapping[str, Any],
    *,
    hard_limits: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
) -> str:
    """Assemble the deliverable-review prompt: the versioned `deliverable_reviewer.md` contract +
    one JSON context block (the fitted content leaves with their inline provenance spans, the
    grounding ledger to re-check, the effective hard limits, an AST-layer provenance fingerprint,
    and any supplementary `context` — coordinates, writer/side/splits — the caller supplies)."""
    template = load_template(DELIVERABLE_REVIEWER_TEMPLATE).text
    block = {
        "content": _content_view(fitted_ir),
        "grounding_ledger": fitted_ir.get("grounding", {}),
        "hard_limits": dict(hard_limits) if hard_limits else {},
        "ast_provenance": _ast_provenance_summary(ast),
        "render": dict(context) if context else {},
    }
    blocks = [
        template.rstrip(),
        "",
        "## Review context (JSON)",
        "```json",
        _review_context_block(block),
        "```",
    ]
    return "\n".join(blocks)


def _reask_note(violations: Sequence[str], checks: Sequence[str]) -> str:
    """The corrective note appended on a re-ask: the most recent violation + the contract
    reminder. Machine-derived — never invents new requirements (§3.1)."""
    latest = violations[-1] if violations else "unspecified"
    return (
        f"Your previous assessment was REJECTED by the review contract: {latest}. Return ONLY the "
        "JSON object {verdict, checks, summary}. `verdict` is exactly \"pass\" or \"concerns\". "
        f"`checks` must cover EXACTLY these keys: {sorted(checks)}, each as "
        '{"status": "pass"|"concern", "note": "<string>"}. `summary` is a string. Do not add or '
        "omit any check, and never emit a secret/credential in a note."
    )


# ---------------------------------------------------------------------------
# The shared review pass: bounded re-ask → typed assessment → record → no-replace persist.
# ---------------------------------------------------------------------------


def _already_reviewed(review_type: str, reviewed_id: str) -> ReviewOutcome:
    return ReviewOutcome(
        status="ok",
        code=CODE_ALREADY_REVIEWED,
        review_type=review_type,  # type: ignore[arg-type]
        reviewed_id=reviewed_id,
        persisted=True,
        record=None,
        verdict=None,
        attempts=0,
        violations=(),
        transport_result=None,
    )


def _produce_review(
    *,
    review_type: Literal["artifact", "deliverable"],
    reviewed_id: str,
    reviewed_digest: str,
    prompt: str,
    checks: Sequence[str],
    store: WorkspaceStore,
    runner: Runner | None,
    model: str | None,
    timeout_seconds: float | None,
    cwd: Path | str | None,
    max_attempts: int,
    minted_ts: str | None,
    plan: TransportPlan | None = None,
) -> ReviewOutcome:
    """Run one review LLM pass with a bounded re-ask, build the typed record, and persist it
    immutably. Idempotency is the CALLER's existence pre-check; `write_new` is the final
    authority (a lost race → `already-reviewed`, never an overwrite). Advisory: a transport
    failure or persistent malformed assessment yields a typed `error` outcome, NO record, NO
    advance — never a block (§19). `plan` (plan G1) threads the run's shared cost accumulator
    through to the review's chokepoint call (both Review-1 and Review-2 route through here)."""
    if max_attempts < 1:
        raise ReviewError(f"review-error: max_attempts must be ≥ 1, got {max_attempts}")
    own_cwd = cwd is None
    scratch = Path(tempfile.mkdtemp(prefix="optiquity-review-")) if own_cwd else Path(cwd)
    extra = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
    violations: list[str] = []
    last_transport: TransportResult | None = None
    try:
        for attempt in range(1, max_attempts + 1):
            note = _reask_note(violations, checks) if violations else None
            full_prompt = prompt if note is None else (
                f"{prompt}\n\n## Correction required (bounded re-ask)\n{note}"
            )
            transport = invoke_headless(
                full_prompt, cwd=scratch, runner=runner, model=model, plan=plan, **extra
            )
            last_transport = transport
            if transport.status != "ok":
                # A transport-level failure — re-asking cannot fix an account-side condition.
                return ReviewOutcome(
                    status="error",
                    code=transport.code,
                    review_type=review_type,
                    reviewed_id=reviewed_id,
                    persisted=False,
                    record=None,
                    verdict=None,
                    attempts=attempt,
                    violations=tuple(violations),
                    transport_result=transport,
                )
            try:
                assessment = parse_review_output(transport.text, checks=checks)
                record = build_review_record(
                    review_type=review_type,
                    reviewed_id=reviewed_id,
                    reviewed_digest=reviewed_digest,
                    assessment=assessment,
                    minted_ts=minted_ts,
                )
            except ReviewSchemaViolation as exc:
                violations.append(f"[{exc.code}] {exc}")
                continue  # bounded re-ask (§19)
            wrote = persist_review_record(store, record)
            return ReviewOutcome(
                status="ok",
                code=CODE_REVIEWED if wrote else CODE_ALREADY_REVIEWED,
                review_type=review_type,
                reviewed_id=reviewed_id,
                persisted=True,
                record=record if wrote else None,
                verdict=record["verdict"],
                attempts=attempt,
                violations=tuple(violations),
                transport_result=transport,
            )
        # Re-ask bound exhausted: caught, and NEVER persisted (advisory, §19).
        return ReviewOutcome(
            status="error",
            code=CODE_CONTRACT_VIOLATION,
            review_type=review_type,
            reviewed_id=reviewed_id,
            persisted=False,
            record=None,
            verdict=None,
            attempts=max_attempts,
            violations=tuple(violations),
            transport_result=last_transport,
        )
    finally:
        if own_cwd:
            shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# Review 1 — the artifact review (ONCE per artifact, pre-fanout).
# ---------------------------------------------------------------------------


def _load_ir(store: WorkspaceStore, artifact_id: str) -> Mapping[str, Any]:
    """Read the persisted IR-canonical record for `artifact_id` from the OUTPUT store (read-only
    — a review NEVER writes an output). A missing record is a wiring defect: Review 1 runs
    POST-mint, so the IR must exist (loud `ReviewError`, never a fabricated review)."""
    try:
        raw = store.output_path(artifact_id).read_bytes()
    except FileNotFoundError as exc:
        raise ReviewError(
            f"review-error: no IR-canonical record for {artifact_id!r} to review — the artifact "
            "review runs POST-mint (§19), so the IR must be persisted first"
        ) from exc
    return json.loads(raw)


def review_artifact(
    *,
    store: WorkspaceStore,
    artifact_id: str,
    ir_doc: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    runner: Runner | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    cwd: Path | str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    minted_ts: str | None = None,
    plan: TransportPlan | None = None,
) -> ReviewOutcome:
    """Run Review 1 — the artifact review — ONCE per artifact (§19), and persist its record.

    Idempotent by output existence (§21.8/§22.3): if `reviews/<artifact-id>` already exists this
    returns `already-reviewed` with ZERO LLM cost — so a re-drive (or a re-compose of an
    already-materialized artifact) never re-runs Review 1, and a FORCED RE-FIT never touches this
    path at all (a re-fit renders a new deliverable; the artifact-id, and thus this review, is
    unchanged — FR5). `ir_doc` is the fresh IR when the caller has it (compose's hot path);
    otherwise the IR is loaded from the store. `context` supplies the resolved goal/persona
    effective values for the fit checks. Reviews are ADVISORY — this never blocks (§19)."""
    review_path = store.review_path(artifact_id)  # validates the id is a bare artifact-id (§19)
    if review_path.exists():
        return _already_reviewed("artifact", artifact_id)
    doc = ir_doc if ir_doc is not None else _load_ir(store, artifact_id)
    bound = doc.get("binding", {}).get("artifact_id")
    if bound != artifact_id:
        raise ReviewError(
            f"review-error: the IR under review binds artifact_id {bound!r}, not the requested "
            f"{artifact_id!r} — a review must match the content it is bound to (§19)"
        )
    reviewed_digest = doc.get("binding", {}).get("digest")
    if not isinstance(reviewed_digest, str) or not reviewed_digest:
        raise ReviewError(
            f"review-error: the IR for {artifact_id!r} carries no composition-binding digest "
            "(§15 RI4) — the review record must bind to the exact content it reviewed"
        )
    prompt = build_artifact_review_prompt(doc, context=context)
    return _produce_review(
        review_type="artifact",
        reviewed_id=artifact_id,
        reviewed_digest=reviewed_digest,
        prompt=prompt,
        checks=ARTIFACT_CHECKS,
        store=store,
        runner=runner,
        model=model,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        max_attempts=max_attempts,
        minted_ts=minted_ts,
        plan=plan,
    )


# ---------------------------------------------------------------------------
# Review 2 — the deliverable review (FULL, on EVERY deliverable incl. every revision).
# ---------------------------------------------------------------------------


def review_deliverable(
    *,
    store: WorkspaceStore,
    deliverable_id: str,
    fitted_ir: Mapping[str, Any],
    ast: Mapping[str, Any],
    hard_limits: Mapping[str, Any] | None = None,
    context: Mapping[str, Any] | None = None,
    runner: Runner | None = None,
    model: str | None = None,
    timeout_seconds: float | None = None,
    cwd: Path | str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    minted_ts: str | None = None,
    plan: TransportPlan | None = None,
) -> ReviewOutcome:
    """Run Review 2 — the FULL deliverable review — for one deliverable (§19), and persist its
    record keyed by `deliverable_id`.

    Runs on EVERY deliverable INCLUDING every fit-revision and serialize-revision deliverable
    (FR5, FR7.5): each revision has a DISTINCT deliverable-id, so its `reviews/<id>` record is
    absent and a FULL review runs — the record NEVER transfers from a prior revision (§19). The
    per-id existence pre-check only ever short-circuits a genuine re-drive of the SAME id, never
    a revision. Reads the fitted IR + the AST (§17: provenance is consumed at the IR/AST layer,
    never from output bytes) + the effective hard limits. Reviews are ADVISORY — never a block."""
    review_path = store.review_path(deliverable_id)  # validates a deliverable-level id (§19)
    if review_path.exists():
        return _already_reviewed("deliverable", deliverable_id)
    reviewed_digest = digest_full({"fitted_ir": fitted_ir, "ast": ast})
    prompt = build_deliverable_review_prompt(
        fitted_ir, ast, hard_limits=hard_limits, context=context
    )
    return _produce_review(
        review_type="deliverable",
        reviewed_id=deliverable_id,
        reviewed_digest=reviewed_digest,
        prompt=prompt,
        checks=DELIVERABLE_CHECKS,
        store=store,
        runner=runner,
        model=model,
        timeout_seconds=timeout_seconds,
        cwd=cwd,
        max_attempts=max_attempts,
        minted_ts=minted_ts,
        plan=plan,
    )
