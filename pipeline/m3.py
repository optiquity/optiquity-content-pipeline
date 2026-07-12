"""M3 — the source-selection grammar & its four-layer cascade (Mechanism 3, design §12.1).

Design authority: `docs/design.md`
  §6.2 — the score vocabulary: eight scores + `review_status` (SM6), each with ONE fixed
         type and scale; predicate operators FOLLOW FROM THE TYPE (scalar → `>= <= > < ==`;
         categorical/ordinal → `== in` plus order comparisons where an order exists;
         boolean → `is`; date-window → `< Nmo`, `contains`, `overlaps`). `volatility` is
         deferred (SM7); `coverage` is resolver-internal, NOT a selectable score (SM8).
  §6.3 — the two-clause grammar plus coverage and conflict clauses: `require` (HARD
         predicates — exclude), `prefer` (SOFT weights — rank, NEVER exclude), `span`
         (positive coverage, a hard clause), `on_conflict` (a selectable, extensible
         strategy — SM4). Hard vs soft is a property of the CLAUSE, not the score (SM2);
         only SCOPE constrains (per-fact scores cannot select instances). Selection
         references CHARACTERISTICS, never identity — scores and content-kind tags only,
         never source ids.
  §6.4 — locality & relaxation (SM3): the four M3 layers may add, tighten, or —
         most-local-wins — RELAX an upstream hard clause; a relax is the user's explicit
         local act and fires a warning; the system never relaxes anything on its own
         initiative (§3.1). There is no `locked:` flag.
  §12.1 — M3 rides its OWN four-layer cascade (workspace-default → goal-implied →
         recipe → run) and carries the FULL selection expression (require + prefer +
         span + on_conflict). M3 never binds attribute values; M2 never touches source
         selection.
  §12.7 (CA10) — a goal-implied weight nudge ADJUSTS only the workspace baseline; an
         explicit user weight at recipe/run is the most-local rung and wins outright.

Vocabulary discipline (step-6 disposition A7; §13.2): M3 clauses are NOT carried by the
§13.2 Bind/Pred AST — this module is their own grammar — but the operator VOCABULARY is
shared: the comparison-operator names and surface tokens are IMPORTED from
`pipeline.opgrammar` and the clause-token table is DERIVED from `PRED_STRING_TOKENS`
mechanically, so vocabulary drift fails at import, never silently. The M3-only operators
(`is`, `contains`, `overlaps`) are pinned against opgrammar's own M3-reservation set at
import time. Extending `pred_op` with the date-window operators remains a REGISTERED
open item — M3 is deliberately not folded into the Pred AST.

Step-15 carry-forwards discharged here (state.md):
  (i)  the score → attach-tier / selection-scope mapping is CODE CONSTANTS below
       (`SCORE_ATTACH_TIERS`, `SCORE_SELECTION_SCOPES`) — machine truth, not prose;
  (ii) `freshness` date-window EXPRESSIONS are validated (`validate_window_expression`) —
       the config carrier ("12mo") no longer accepts garbage silently at its consumers;
  (iii) YAML 1.2 loads the §6.3 sample weight `+2` as int `2` — prefer weights are
       therefore INTEGERS here (bool refused; floats refused as unauthored precision).

In-latitude decisions (step-17 coder; grounded in the report):

- **Clause surface = `score op value`**, one line, exactly as §6.3's block authors them;
  the operand tail is ONE pinned-YAML-1.2 literal (`pipeline.yamlio.load_yaml` — the same
  bounded posture as opgrammar; this module is never a general expression language).
- **`==` is the M3 equals token** (§13.2 fixes `=` as the Pred token and `==` as M3's);
  each grammar refuses the other's spelling with a pointing error.
- **Order comparisons need a declared order**: `independence` and `primariness` are the
  §6.2 ordinal scores (orders declared below, low → high); `review_status` is categorical
  (its `unknown` member breaks any total order — the G6 degradation target), so order
  comparisons on it are refused.
- **`content-kind` is a selectable characteristic** (§6.3: "scores and content-kind tags
  only"): categorical over the OPEN kind-id vocabulary (one-file-add kinds, §5.4), so
  members validate as slugs, not against a closed list.
- **Span axes** are the instance-scope categorical characteristics: `content-kind`,
  `independence`, `primariness` (§6.3's span example + "≥1 surviving INSTANCE per named
  member" — a span member must be checkable on the pre-query pool).
- **Relax targets** are exact canonical clause strings (or `span <axis>`): a relax names
  precisely the inherited clause it removes; a relax that matches nothing inherited is a
  loud error (config that does nothing is an authoring mistake, §3.1 posture).
- **The date-window convention** (documented once, tested): `Nmo` measures back N
  calendar months from the injected clock (day clamped to month end); `freshness < Nmo`
  passes iff the value is STRICTLY newer than that cutoff; `contains` is inclusive;
  `overlaps` treats a bare date as the point window [d, d] and a month expression as
  [cutoff, now]. An UNKNOWN value (None) never satisfies a hard clause.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value
from pipeline.m1 import ResolutionWarning
from pipeline.opgrammar import (
    _M3_ONLY_OPERATORS as _OPGRAMMAR_M3_RESERVED,  # the A7 drift pin (checked at import)
)
from pipeline.opgrammar import (
    BIND_OPS,
    PRED_EQ,
    PRED_GE,
    PRED_GT,
    PRED_IN,
    PRED_LE,
    PRED_LT,
    PRED_OPS,
    PRED_STRING_TOKENS,
    RESERVED_SET_SUBTRACT,
)
from pipeline.yamlio import YAMLLoadError, load_yaml

__all__ = [
    "CATEGORICAL_MEMBERS",
    "CONTENT_KIND",
    "DEFAULT_ON_CONFLICT",
    "EffectivePrefer",
    "EffectiveSelection",
    "LAYER_KEYS",
    "LAYER_RECIPE",
    "LAYER_RUN",
    "LAYER_WORKSPACE",
    "M3GrammarError",
    "M3OperatorError",
    "M3VocabularyDriftError",
    "M3_CLAUSE_TOKENS",
    "M3_CONTAINS",
    "M3_IS",
    "M3_ONLY_OPERATORS",
    "M3_OVERLAPS",
    "ORDINAL_MEMBERS",
    "PER_FACT_REFINABLE_SCORES",
    "PreferTerm",
    "RelaxEvent",
    "RelaxTargetError",
    "SCOPE_FACT",
    "SCOPE_INSTANCE",
    "SCORES",
    "SCORE_ATTACH_TIERS",
    "SCORE_SELECTION_SCOPES",
    "SCORE_TYPES",
    "SELECTABLE_CHARACTERISTICS",
    "SPAN_AXES",
    "SelectionClause",
    "SelectionLayer",
    "UnknownScoreError",
    "WindowExpressionError",
    "bare_score_contribution",
    "evaluate_clause",
    "fold_layers",
    "goal_layer_origin",
    "month_window",
    "parse_clause",
    "parse_prefer_item",
    "parse_selection_layer",
    "parse_window_expression",
    "render_clause",
    "resolve_selection",
    "validate_window_expression",
]


# --- Typed errors -----------------------------------------------------------------------


class M3GrammarError(ValueError):
    """A §6.3 selection-grammar refusal — loud, typed, never repaired."""

    code = "invalid-selection-grammar"


class UnknownScoreError(M3GrammarError):
    """A clause names something outside the selectable characteristic vocabulary —
    including any attempt to select by source IDENTITY (§6.3: characteristics only)."""

    code = "unknown-selection-score"


class M3OperatorError(M3GrammarError):
    """An operator illegal for the score's §6.2 type (operators follow from the type)."""

    code = "invalid-selection-operator"


class WindowExpressionError(M3GrammarError):
    """A malformed freshness date-window expression (the `Nmo` config carrier, §6.2)."""

    code = "invalid-date-window-expression"


class RelaxTargetError(M3GrammarError):
    """A `relax:` item that names no inherited clause (SM3: a relax is an explicit act
    on a REAL upstream clause; relaxing nothing is an authoring error)."""

    code = "invalid-relax"


class M3VocabularyDriftError(RuntimeError):
    """The A7 import-time pin tripped: the M3 operator vocabulary drifted from
    `pipeline.opgrammar`'s tokens. Fix the vocabulary, never this check."""


# --- The score vocabulary (§6.2) — machine truth, the step-15 carry-forward ---------------

#: The §6.3 selectable content-kind TAG (not a score; open one-file-add vocabulary).
CONTENT_KIND = "content-kind"

#: §6.2: eight scores + `review_status` (SM6). `volatility` deferred (SM7); `coverage`
#: resolver-internal (SM8) — deliberately NOT in this set.
SCORES = frozenset(
    {
        "trusted",
        "independence",
        "primariness",
        "authoritative",
        "opinionated",
        "freshness",
        "corroboration",
        "traceability",
        "review_status",
    }
)

SELECTABLE_CHARACTERISTICS = SCORES | {CONTENT_KIND}

#: §6.2 type per score — the operator set follows from this (SM2's "typed by the score").
#: "slider" = scalar 1–5 · "count" = scalar 0–n · "ordinal"/"categorical" per the table ·
#: "categorical-open" = the open content-kind tag vocabulary.
SCORE_TYPES: dict[str, str] = {
    "trusted": "slider",
    "independence": "ordinal",
    "primariness": "ordinal",
    "authoritative": "slider",
    "opinionated": "slider",
    "freshness": "date-window",
    "corroboration": "count",
    "traceability": "bool",
    "review_status": "categorical",
    CONTENT_KIND: "categorical-open",
}

#: §6.1/§6.2 attach tiers (Q10) — code constants per the step-15 carry-forward.
SCORE_ATTACH_TIERS: dict[str, str] = {
    "trusted": "instance",
    "independence": "instance",
    "primariness": "instance",
    "authoritative": "content-kind",
    "opinionated": "content-kind",
    "freshness": "content-kind",
    "review_status": "content-kind",
    "corroboration": "per-fact",
    "traceability": "per-fact",
}

SCOPE_INSTANCE = "instance"
SCOPE_FACT = "fact"

#: Where a HARD clause on each characteristic evaluates in the §6.3 resolver walk.
#: Instance-tier scores narrow the pool pre-query (§6.3's own comment labels:
#: "primariness == primary # instance-scope"); kind-tier and per-fact scores evaluate
#: per fact after union ("freshness < 12mo # content-kind/fact-scope"; "corroboration
#: >= 2 # fact-scope"). SM2's scope rule — per-fact scores cannot select instances —
#: is this table.
SCORE_SELECTION_SCOPES: dict[str, str] = {
    "trusted": SCOPE_INSTANCE,
    "independence": SCOPE_INSTANCE,
    "primariness": SCOPE_INSTANCE,
    CONTENT_KIND: SCOPE_INSTANCE,
    "authoritative": SCOPE_FACT,
    "opinionated": SCOPE_FACT,
    "freshness": SCOPE_FACT,
    "review_status": SCOPE_FACT,
    "corroboration": SCOPE_FACT,
    "traceability": SCOPE_FACT,
}

#: §6.1: kind-tier scores an adapter may refine PER FACT ("where the adapter classifies
#: facts") plus semi-derived `primariness` ("instance → per-fact"). `corroboration` and
#: `traceability` are computed by the RESOLVER, never adapter-supplied; `freshness` rides
#: the fact's `as_of`, not a refinement key.
PER_FACT_REFINABLE_SCORES = frozenset(
    {"authoritative", "opinionated", "review_status", "primariness"}
)

#: §6.2 ordinal orders, LOW → HIGH (order comparisons compare these ranks).
ORDINAL_MEMBERS: dict[str, tuple[str, ...]] = {
    "independence": ("first-party", "affiliated", "independent"),
    "primariness": ("tertiary", "secondary", "primary"),
}

#: §6.2 categorical member sets (closed). `content-kind` is open — validated as slugs.
CATEGORICAL_MEMBERS: dict[str, tuple[str, ...]] = {
    "review_status": ("unreviewed", "reviewed", "formally-vetted", "unknown"),
}

#: §6.3: span coverage runs over the instance-scope categorical characteristics.
SPAN_AXES = (CONTENT_KIND, "independence", "primariness")

#: The names whose use as a "score" gets the pointed §6.3 identity refusal.
_IDENTITY_TOKENS = frozenset(
    {
        "id",
        "ids",
        "source",
        "sources",
        "source-id",
        "source_id",
        "instance",
        "instances",
        "instance-id",
        "instance_id",
        "adapter",
    }
)


# --- Operator vocabulary (imported/derived from opgrammar — A7) ---------------------------

M3_IS = "is"
M3_CONTAINS = "contains"
M3_OVERLAPS = "overlaps"
M3_ONLY_OPERATORS = frozenset({M3_IS, M3_CONTAINS, M3_OVERLAPS})

#: The comparison operators M3 shares with the §13.2 pred_op vocabulary (imported names).
_SHARED_PRED_OPS = frozenset({PRED_EQ, PRED_IN, PRED_GE, PRED_LE, PRED_GT, PRED_LT})

#: Surface token → canonical operator name. DERIVED from opgrammar's own token table for
#: the shared six (drift fails mechanically), plus `==` (the M3 equals spelling, §13.2)
#: and the M3-only operators.
M3_CLAUSE_TOKENS: dict[str, str] = {"==": PRED_EQ}
for _token, _op in PRED_STRING_TOKENS.items():
    if _op in _SHARED_PRED_OPS and _token != "=":
        M3_CLAUSE_TOKENS[_token] = _op
M3_CLAUSE_TOKENS[M3_IS] = M3_IS
M3_CLAUSE_TOKENS[M3_CONTAINS] = M3_CONTAINS
M3_CLAUSE_TOKENS[M3_OVERLAPS] = M3_OVERLAPS

_OP_TO_TOKEN = {op: token for token, op in M3_CLAUSE_TOKENS.items()}

# The A7 import-time pins: the M3-only set must equal opgrammar's reservation for the
# date-window operators, and the vocabularies must stay disjoint. Explicit `if` (never
# `assert` — stripped under -O).
if {M3_CONTAINS, M3_OVERLAPS} != _OPGRAMMAR_M3_RESERVED:
    raise M3VocabularyDriftError(
        "A7 vocabulary drift: pipeline.m3's date-window operators "
        f"{sorted({M3_CONTAINS, M3_OVERLAPS})} != pipeline.opgrammar's M3 reservation "
        f"{sorted(_OPGRAMMAR_M3_RESERVED)} — the two modules share ONE vocabulary (§13.2)"
    )
if M3_ONLY_OPERATORS & (PRED_OPS | BIND_OPS):
    raise M3VocabularyDriftError(
        "A7 vocabulary drift: an M3-only operator collides with a §13.2 pred_op/bind_op "
        f"token ({sorted(M3_ONLY_OPERATORS & (PRED_OPS | BIND_OPS))})"
    )

#: Legal operators per §6.2 score type ("predicate operators follow from the type").
_TYPE_OPERATORS: dict[str, frozenset[str]] = {
    "slider": frozenset({PRED_EQ, PRED_GE, PRED_LE, PRED_GT, PRED_LT}),
    "count": frozenset({PRED_EQ, PRED_GE, PRED_LE, PRED_GT, PRED_LT}),
    "ordinal": frozenset({PRED_EQ, PRED_IN, PRED_GE, PRED_LE, PRED_GT, PRED_LT}),
    "categorical": frozenset({PRED_EQ, PRED_IN}),
    "categorical-open": frozenset({PRED_EQ, PRED_IN}),
    "bool": frozenset({M3_IS}),
    "date-window": frozenset({PRED_LT, M3_CONTAINS, M3_OVERLAPS}),
}

_REF_SPEC = AttrTypeSpec(kind="ref")  # slug validation via the ONE §11.1 implementation


# --- The freshness window expression (§6.2 `Nmo`; step-15 carry-forward ii) ----------------

_WINDOW_RE = re.compile(r"\A([1-9][0-9]*)mo\Z")


def parse_window_expression(text: Any, *, where: str = "") -> int:
    """Parse the §6.2 date-window config carrier (`"12mo"`) → months (positive int)."""
    label = f" at {where}" if where else ""
    if not isinstance(text, str):
        raise WindowExpressionError(
            f"invalid-date-window-expression{label}: expected an `Nmo` string "
            f"(§6.2 date-window vocabulary), got {type(text).__name__}: {text!r}"
        )
    match = _WINDOW_RE.match(text.strip())
    if match is None:
        raise WindowExpressionError(
            f"invalid-date-window-expression{label}: {text!r} — the carrier grammar is "
            "`<N>mo` with N a positive integer (§6.2: `< Nmo`), e.g. '12mo'"
        )
    return int(match.group(1))


def validate_window_expression(text: Any, *, where: str = "") -> None:
    """Validate-only form of `parse_window_expression` (returns None or raises)."""
    parse_window_expression(text, where=where)


def _shift_months(day: datetime.date, months_back: int) -> datetime.date:
    """`day` shifted BACK by N calendar months, day-of-month clamped to month end."""
    month_index = day.year * 12 + (day.month - 1) - months_back
    year, month = divmod(month_index, 12)
    month += 1
    # clamp the day to the target month's length
    if month == 12:
        next_first = datetime.date(year + 1, 1, 1)
    else:
        next_first = datetime.date(year, month + 1, 1)
    last_day = (next_first - datetime.timedelta(days=1)).day
    return datetime.date(year, month, min(day.day, last_day))


def month_window(now: datetime.date, months: int) -> tuple[datetime.date, datetime.date]:
    """The `Nmo` window against the injected clock: (cutoff, now). The clock is always
    injected at the edge (the house discipline), never read ambiently."""
    return _shift_months(now, months), now


# --- The clause AST (§6.3) -----------------------------------------------------------------


def _refuse_unknown_score(name: Any) -> None:
    if not isinstance(name, str):
        raise UnknownScoreError(
            f"unknown-selection-score: a clause names a score by string, got "
            f"{type(name).__name__}: {name!r}"
        )
    if name in SELECTABLE_CHARACTERISTICS:
        return
    if name in _IDENTITY_TOKENS:
        raise UnknownScoreError(
            f"unknown-selection-score: {name!r} — selection references CHARACTERISTICS, "
            "never identity: scores and content-kind tags only, never source ids (§6.3). "
            "Instance ids exist for provenance and addressing; a new instance with the "
            "right scores is automatically eligible with zero recipe changes."
        )
    raise UnknownScoreError(
        f"unknown-selection-score: {name!r} is not a selectable characteristic "
        f"(§6.2/§6.3 vocabulary: {', '.join(sorted(SELECTABLE_CHARACTERISTICS))}; "
        "selection is by characteristics only, never source ids)"
    )


def _validate_member(score: str, member: Any, *, what: str) -> None:
    """One categorical/ordinal member value, validated against the score's vocabulary."""
    if not isinstance(member, str):
        raise M3GrammarError(
            f"invalid-selection-grammar: {what} for {score!r} must be a string member, "
            f"got {type(member).__name__}: {member!r}"
        )
    members = ORDINAL_MEMBERS.get(score) or CATEGORICAL_MEMBERS.get(score)
    if members is not None:
        if member not in members:
            raise M3GrammarError(
                f"invalid-selection-grammar: {member!r} is not a member of {score!r} "
                f"(§6.2 members: {', '.join(members)})"
            )
        return
    # content-kind: open one-file-add vocabulary (§5.4) — validate as an entry-id slug.
    try:
        validate_value(_REF_SPEC, member, path=f"{score} {what}")
    except ValueValidationError as exc:
        raise M3GrammarError(
            f"invalid-selection-grammar: {what} for {score!r} must be an entry-id slug "
            f"(§7.4), got {member!r}"
        ) from exc


def _validate_operand(score: str, op: str, operand: Any) -> Any:
    """Type-check (and normalize: sequences → tuples) one clause operand."""
    score_type = SCORE_TYPES[score]
    if score_type in {"slider", "count"}:
        if not isinstance(operand, int) or isinstance(operand, bool):
            raise M3GrammarError(
                f"invalid-selection-grammar: {score!r} is a scalar score — the operand "
                f"must be an integer, got {type(operand).__name__}: {operand!r}"
            )
        if score_type == "slider" and not (1 <= operand <= 5):
            raise M3GrammarError(
                f"invalid-selection-grammar: {score!r} is scalar 1-5 (§6.2) — operand "
                f"{operand!r} is out of scale"
            )
        if score_type == "count" and operand < 0:
            raise M3GrammarError(
                f"invalid-selection-grammar: {score!r} is scalar 0-n (§6.2) — operand "
                f"{operand!r} is negative"
            )
        return operand
    if score_type in {"ordinal", "categorical", "categorical-open"}:
        if op == PRED_IN:
            if not isinstance(operand, list | tuple) or not operand:
                raise M3GrammarError(
                    f"invalid-selection-grammar: `{score} in …` requires a non-empty "
                    f"member sequence, got {operand!r}"
                )
            members = tuple(operand)
            if len(set(members)) != len(members):
                raise M3GrammarError(
                    f"invalid-selection-grammar: duplicate member in `{score} in "
                    f"{list(members)!r}` — loud, never silently deduped"
                )
            for member in members:
                _validate_member(score, member, what="`in` member")
            return members
        _validate_member(score, operand, what="operand")
        return operand
    if score_type == "bool":
        if not isinstance(operand, bool):
            raise M3GrammarError(
                f"invalid-selection-grammar: `{score} is …` requires true/false, "
                f"got {type(operand).__name__}: {operand!r}"
            )
        return operand
    # date-window (freshness)
    if op == PRED_LT:
        parse_window_expression(operand, where=f"`{score} <` operand")
        return operand.strip()
    if op == M3_CONTAINS:
        if isinstance(operand, datetime.datetime) or not isinstance(operand, datetime.date):
            raise M3GrammarError(
                f"invalid-selection-grammar: `{score} contains …` requires a bare date "
                f"(date-granular, §6.2/D2), got {operand!r}"
            )
        return operand
    # overlaps: an `Nmo` expression or an explicit [start, end] date pair
    if isinstance(operand, str):
        parse_window_expression(operand, where=f"`{score} overlaps` operand")
        return operand.strip()
    if isinstance(operand, list | tuple) and len(operand) == 2:
        start, end = operand
        for edge in (start, end):
            if isinstance(edge, datetime.datetime) or not isinstance(edge, datetime.date):
                raise M3GrammarError(
                    f"invalid-selection-grammar: `{score} overlaps [start, end]` edges "
                    f"must be bare dates, got {operand!r}"
                )
        if start > end:
            raise M3GrammarError(
                f"invalid-selection-grammar: `{score} overlaps` window must satisfy "
                f"start <= end, got {operand!r}"
            )
        return (start, end)
    raise M3GrammarError(
        f"invalid-selection-grammar: `{score} overlaps …` requires an `Nmo` expression "
        f"or a [start, end] date pair, got {operand!r}"
    )


@dataclass(frozen=True)
class SelectionClause:
    """One §6.3 predicate: `score op operand`. Hard vs soft is where it APPEARS
    (`require` vs `prefer` — SM2), never a property of this node."""

    score: str
    op: str
    operand: Any

    def __post_init__(self) -> None:
        _refuse_unknown_score(self.score)
        legal = _TYPE_OPERATORS[SCORE_TYPES[self.score]]
        if self.op not in legal:
            hint = ""
            if self.score == "review_status" and self.op in {PRED_GE, PRED_LE, PRED_GT, PRED_LT}:
                hint = (
                    " — review_status is CATEGORICAL (§6.2 SM6): its `unknown` member "
                    "(the G6 degradation) breaks any total order"
                )
            elif SCORE_TYPES[self.score] == "bool" and self.op == PRED_EQ:
                hint = " — boolean scores take `is` (§6.2), not `==`"
            raise M3OperatorError(
                f"invalid-selection-operator: {_OP_TO_TOKEN.get(self.op, self.op)!r} is "
                f"not legal for {self.score!r} (type {SCORE_TYPES[self.score]!r}; legal: "
                f"{', '.join(sorted(_OP_TO_TOKEN[o] for o in legal))}){hint}"
            )
        object.__setattr__(self, "operand", _validate_operand(self.score, self.op, self.operand))

    @property
    def scope(self) -> str:
        """Where this clause evaluates as a HARD gate (§6.3 walk): instance or fact."""
        return SCORE_SELECTION_SCOPES[self.score]

    def canonical(self) -> str:
        """The canonical string rendering (parse → canonical → parse is identity)."""
        return render_clause(self)


def _render_operand(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return value
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_render_operand(v) for v in value) + "]"
    raise M3GrammarError(
        f"invalid-selection-grammar: operand {value!r} has no canonical rendering"
    )


def render_clause(clause: SelectionClause) -> str:
    """`score token operand` — the §6.3 authored surface, canonically spelled."""
    return f"{clause.score} {_OP_TO_TOKEN[clause.op]} {_render_operand(clause.operand)}"


def parse_clause(text: Any, *, where: str = "") -> SelectionClause:
    """Parse one authored clause string: `score op value` (§6.3), single line."""
    label = f"{where}: " if where else ""
    if not isinstance(text, str):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}a clause is a string "
            f"(`score op value`, §6.3), got {type(text).__name__}: {text!r}"
        )
    if "\n" in text or "\r" in text:
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}a clause is a single line, got {text!r}"
        )
    parts = text.split(None, 2)
    if len(parts) != 3:
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}expected `score op value` (§6.3), "
            f"got {text!r}"
        )
    score_token, op_token, operand_text = parts
    op = M3_CLAUSE_TOKENS.get(op_token)
    if op is None:
        if op_token == "=":
            raise M3OperatorError(
                f"invalid-selection-operator: {label}'=' is the §13.2 Pred equals token — "
                "the M3 equals spelling is '==' (§6.3; the two grammars share vocabulary, "
                "not surface)"
            )
        if PRED_STRING_TOKENS.get(op_token) in PRED_OPS:
            raise M3OperatorError(
                f"invalid-selection-operator: {label}{op_token!r} is a §13.2 pred_op "
                "with no M3 clause meaning — M3 operators follow from the score type "
                "(§6.2)"
            )
        if op_token in BIND_OPS or op_token == RESERVED_SET_SUBTRACT:
            raise M3OperatorError(
                f"invalid-selection-operator: {label}{op_token!r} is a §12.4 bind-side "
                "token — M3 clauses are predicates, never bindings (§13.2)"
            )
        raise M3OperatorError(
            f"invalid-selection-operator: {label}unknown operator token {op_token!r} "
            f"(M3 tokens: {' '.join(sorted(M3_CLAUSE_TOKENS))})"
        )
    try:
        operand = load_yaml(operand_text)
    except YAMLLoadError as exc:
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}operand {operand_text!r} is not a valid "
            "host (YAML 1.2) literal"
        ) from exc
    return SelectionClause(score=score_token, op=op, operand=operand)


# --- prefer terms (§6.3 soft weights) -------------------------------------------------------

#: Score types a BARE prefer key can rank by (a scalar contribution exists). Categorical
#: characteristics have none — prefer them via a predicate key (`independence ==
#: independent: +1`).
_BARE_PREFER_TYPES = frozenset({"slider", "count", "ordinal", "bool", "date-window"})


@dataclass(frozen=True)
class PreferTerm:
    """One `prefer` entry's identity: a bare score key or a predicate key (§6.3).

    The WEIGHT rides separately (`EffectivePrefer`) because layers adjust it (CA10);
    the term itself is the stable key the four layers meet on.
    """

    key: str
    score: str
    clause: SelectionClause | None

    def __post_init__(self) -> None:
        if self.clause is None:
            _refuse_unknown_score(self.score)
            if SCORE_TYPES[self.score] not in _BARE_PREFER_TYPES:
                raise M3GrammarError(
                    f"invalid-selection-grammar: bare `prefer {self.score}` has no scalar "
                    f"contribution ({self.score!r} is {SCORE_TYPES[self.score]!r}) — "
                    "prefer it via a predicate key, e.g. "
                    f"`{self.score} == <member>: +1` (§6.3)"
                )


def parse_prefer_item(item: Any, *, where: str = "") -> tuple[PreferTerm, int]:
    """Parse one authored prefer entry: a single-key map `{key: weight}` (§6.3).

    The key is a bare score name (`authoritative: +2`) or a predicate clause string
    (`independence == independent: +1`). YAML 1.2 loads `+2` as int 2 (the step-15
    note); weights are integers — bool refused, floats refused.
    """
    label = f"{where}: " if where else ""
    if not isinstance(item, Mapping) or len(item) != 1:
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}a prefer entry is a single-key map "
            f"`{{score-or-clause: weight}}` (§6.3), got {item!r}"
        )
    ((key, weight),) = item.items()
    if not isinstance(key, str) or not key.strip():
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}prefer key must be a non-empty string, "
            f"got {key!r}"
        )
    if not isinstance(weight, int) or isinstance(weight, bool):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}prefer weight for {key!r} must be an "
            f"integer (YAML 1.2 loads `+2` as 2), got {type(weight).__name__}: {weight!r}"
        )
    key = key.strip()
    if any(ch.isspace() for ch in key):
        clause = parse_clause(key, where=where or "prefer key")
        return PreferTerm(key=clause.canonical(), score=clause.score, clause=clause), weight
    return PreferTerm(key=key, score=key, clause=None), weight


# --- span (§6.3 positive coverage) ----------------------------------------------------------


def _parse_span(raw: Any, *, where: str) -> dict[str, tuple[str, ...]]:
    if not isinstance(raw, Mapping):
        raise M3GrammarError(
            f"invalid-selection-grammar: {where}: `span` is a map of axis -> members "
            f"(§6.3), got {type(raw).__name__}: {raw!r}"
        )
    span: dict[str, tuple[str, ...]] = {}
    for axis, members in raw.items():
        if axis not in SPAN_AXES:
            raise M3GrammarError(
                f"invalid-selection-grammar: {where}: unknown span axis {axis!r} — span "
                f"covers the instance-scope categorical characteristics "
                f"({', '.join(SPAN_AXES)}); §6.3: ≥1 surviving INSTANCE per named member"
            )
        if not isinstance(members, list | tuple) or not members:
            raise M3GrammarError(
                f"invalid-selection-grammar: {where}: span axis {axis!r} requires a "
                f"non-empty member list, got {members!r}"
            )
        seen: list[str] = []
        for member in members:
            _validate_member(axis, member, what="span member")
            if member in seen:
                raise M3GrammarError(
                    f"invalid-selection-grammar: {where}: duplicate span member "
                    f"{member!r} on axis {axis!r} — loud, never silently deduped"
                )
            seen.append(member)
        span[axis] = tuple(seen)
    return span


# --- Layers & the four-layer fold (§12.1; SM3 relax) ----------------------------------------

LAYER_WORKSPACE = "workspace"
LAYER_RECIPE = "recipe"
LAYER_RUN = "run"


def goal_layer_origin(goal_id: str) -> str:
    """The origin label of one goal-implied layer (§12.1)."""
    return f"goal:{goal_id}"


#: The closed authored-layer key vocabulary (§6.3 block + the SM3 relax surface).
LAYER_KEYS = frozenset({"require", "prefer", "span", "on_conflict", "relax"})

#: §6.3: the default conflict strategy.
DEFAULT_ON_CONFLICT = "downgrade-AMBIGUOUS"

_SPAN_RELAX_PREFIX = "span "


@dataclass(frozen=True)
class SelectionLayer:
    """One parsed M3 layer (workspace / goal:<id> / recipe / run), as authored."""

    origin: str
    require: tuple[SelectionClause, ...] = ()
    prefer: tuple[tuple[PreferTerm, int], ...] = ()
    span: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    on_conflict: str | None = None
    relax: tuple[str, ...] = ()


def parse_selection_layer(
    raw: Mapping[str, Any] | None, *, origin: str, where: str = ""
) -> SelectionLayer:
    """Parse one authored `source_selection` map (the goal-schema/T10 carrier shape)."""
    label = where or origin
    if raw is None:
        return SelectionLayer(origin=origin)
    if not isinstance(raw, Mapping):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}: a source_selection layer is a map, "
            f"got {type(raw).__name__}: {raw!r}"
        )
    unknown = sorted(str(k) for k in raw if k not in LAYER_KEYS)
    if unknown:
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}: unknown selection key(s) {unknown!r} "
            f"(§6.3 vocabulary: {', '.join(sorted(LAYER_KEYS))})"
        )

    require: list[SelectionClause] = []
    raw_require = raw.get("require", [])
    if not isinstance(raw_require, list | tuple):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}: `require` is a clause list (§6.3), "
            f"got {raw_require!r}"
        )
    for entry in raw_require:
        require.append(parse_clause(entry, where=f"{label} require"))

    prefer: list[tuple[PreferTerm, int]] = []
    raw_prefer = raw.get("prefer", [])
    if not isinstance(raw_prefer, list | tuple):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}: `prefer` is a list of single-key maps "
            f"(§6.3), got {raw_prefer!r}"
        )
    seen_keys: set[str] = set()
    for entry in raw_prefer:
        term, weight = parse_prefer_item(entry, where=f"{label} prefer")
        if term.key in seen_keys:
            raise M3GrammarError(
                f"invalid-selection-grammar: {label}: duplicate prefer key {term.key!r} "
                "in one layer — one weight per key per layer"
            )
        seen_keys.add(term.key)
        prefer.append((term, weight))

    span = _parse_span(raw["span"], where=label) if "span" in raw else {}

    on_conflict = raw.get("on_conflict")
    if on_conflict is not None:
        if not isinstance(on_conflict, str) or not on_conflict.strip():
            raise M3GrammarError(
                f"invalid-selection-grammar: {label}: `on_conflict` names one strategy "
                f"(§6.3 SM4), got {on_conflict!r}"
            )
        on_conflict = on_conflict.strip()
        if any(ch.isspace() for ch in on_conflict):
            raise M3GrammarError(
                f"invalid-selection-grammar: {label}: `on_conflict` is a single strategy "
                f"token, got {on_conflict!r}"
            )

    relax: list[str] = []
    raw_relax = raw.get("relax", [])
    if not isinstance(raw_relax, list | tuple):
        raise M3GrammarError(
            f"invalid-selection-grammar: {label}: `relax` is a list of inherited-clause "
            f"strings (SM3, §6.4), got {raw_relax!r}"
        )
    for entry in raw_relax:
        if not isinstance(entry, str) or not entry.strip():
            raise M3GrammarError(
                f"invalid-selection-grammar: {label}: a relax target is a clause string "
                f"or `span <axis>`, got {entry!r}"
            )
        target = entry.strip()
        if target.startswith(_SPAN_RELAX_PREFIX):
            axis = target[len(_SPAN_RELAX_PREFIX) :].strip()
            if axis not in SPAN_AXES:
                raise M3GrammarError(
                    f"invalid-selection-grammar: {label}: `relax: span {axis}` names an "
                    f"unknown span axis (axes: {', '.join(SPAN_AXES)})"
                )
            relax.append(f"{_SPAN_RELAX_PREFIX}{axis}")
        else:
            relax.append(parse_clause(target, where=f"{label} relax").canonical())

    return SelectionLayer(
        origin=origin,
        require=tuple(require),
        prefer=tuple(prefer),
        span=span,
        on_conflict=on_conflict,
        relax=tuple(relax),
    )


@dataclass(frozen=True)
class EffectivePrefer:
    """One effective soft-weight term after the CA10 fold."""

    term: PreferTerm
    weight: int
    origin: str


@dataclass(frozen=True)
class RelaxEvent:
    """One SM3 relaxation: which layer removed which inherited hard clause."""

    target: str  # the canonical clause string, or "span <axis>"
    set_at: str  # the origin that set the clause
    relaxed_by: str  # the (more local) origin that relaxed it


@dataclass(frozen=True)
class EffectiveSelection:
    """M3's resolved output for one item: what the grounding resolver executes (§6.3)."""

    require: tuple[SelectionClause, ...]
    require_origins: Mapping[str, str]  # canonical clause -> origin
    span: Mapping[str, tuple[str, ...]]  # axis -> members (authored order, deduped)
    span_origins: Mapping[str, str]  # axis -> origin that first set it
    prefer: tuple[EffectivePrefer, ...]
    on_conflict: str
    on_conflict_origin: str  # "default" or a layer origin
    relaxed: tuple[RelaxEvent, ...] = ()
    warnings: tuple[ResolutionWarning, ...] = ()


def fold_layers(layers: Sequence[SelectionLayer]) -> EffectiveSelection:
    """The four-layer M3 fold (§12.1), least → most local.

    `require`/`span` union and tighten; a `relax` removes an INHERITED clause,
    most-local-wins, WITH a warning (SM3 — the user's explicit local act; the system
    never relaxes on its own initiative, §3.1). `on_conflict` is a selection —
    most-local-wins, no warning. `prefer` folds per CA10: goal-implied nudges ADJUST
    the workspace baseline; an explicit recipe/run weight wins outright.
    """
    require: dict[str, SelectionClause] = {}  # canonical -> clause (insertion-ordered)
    require_origins: dict[str, str] = {}
    span: dict[str, tuple[str, ...]] = {}
    span_origins: dict[str, str] = {}
    on_conflict: str | None = None
    on_conflict_origin = "default"
    relaxed: list[RelaxEvent] = []
    warnings: list[ResolutionWarning] = []

    # prefer bookkeeping (CA10): key -> ...
    terms: dict[str, PreferTerm] = {}
    term_order: list[str] = []
    workspace_weight: dict[str, int] = {}
    goal_nudges: dict[str, int] = {}
    recipe_weight: dict[str, int] = {}
    run_weight: dict[str, int] = {}
    weight_origin: dict[str, str] = {}

    for layer in layers:
        is_goal = layer.origin.startswith("goal:")

        # -- relax first: a layer's relax acts on what it INHERITS (§6.4), and its own
        #    additions below are never self-relaxed.
        for target in layer.relax:
            if target.startswith(_SPAN_RELAX_PREFIX):
                axis = target[len(_SPAN_RELAX_PREFIX) :]
                if axis not in span:
                    raise RelaxTargetError(
                        f"invalid-relax: {layer.origin} relaxes `span {axis}` but no "
                        "inherited layer set that span axis — a relax names a real "
                        "upstream clause (SM3, §6.4)"
                    )
                set_at = span_origins.pop(axis)
                del span[axis]
                relaxed.append(RelaxEvent(target=target, set_at=set_at, relaxed_by=layer.origin))
                warnings.append(
                    ResolutionWarning(
                        key=f"m3-relax:{layer.origin}:{target}",
                        message=(
                            f"{layer.origin} relaxed `span: {axis}` set at {set_at} "
                            "scope (SM3, §6.4) — the user's explicit local act; the "
                            "system never relaxes on its own initiative (§3.1)"
                        ),
                    )
                )
                continue
            if target not in require:
                raise RelaxTargetError(
                    f"invalid-relax: {layer.origin} relaxes `require: {target}` but no "
                    "inherited layer set that clause — a relax names a real upstream "
                    "clause (SM3, §6.4)"
                )
            set_at = require_origins.pop(target)
            del require[target]
            relaxed.append(RelaxEvent(target=target, set_at=set_at, relaxed_by=layer.origin))
            warnings.append(
                ResolutionWarning(
                    key=f"m3-relax:{layer.origin}:{target}",
                    message=(
                        f"{layer.origin} relaxed `require: {target}` set at {set_at} "
                        "scope (SM3, §6.4) — the user's explicit local act; the system "
                        "never relaxes on its own initiative (§3.1)"
                    ),
                )
            )

        # -- require: union; identical clauses dedupe on the FIRST setting layer.
        for clause in layer.require:
            canonical = clause.canonical()
            if canonical not in require:
                require[canonical] = clause
                require_origins[canonical] = layer.origin

        # -- span: per-axis member union (tighten = add members/axes).
        for axis, members in layer.span.items():
            if axis not in span:
                span[axis] = members
                span_origins[axis] = layer.origin
            else:
                merged = list(span[axis])
                merged.extend(m for m in members if m not in merged)
                span[axis] = tuple(merged)

        # -- on_conflict: most-local-wins selection (no warning — a selection, not a relax).
        if layer.on_conflict is not None:
            on_conflict = layer.on_conflict
            on_conflict_origin = layer.origin

        # -- prefer (CA10 lanes).
        for term, weight in layer.prefer:
            if term.key not in terms:
                terms[term.key] = term
                term_order.append(term.key)
            if layer.origin == LAYER_WORKSPACE:
                workspace_weight[term.key] = weight
                weight_origin[term.key] = layer.origin
            elif is_goal:
                goal_nudges[term.key] = goal_nudges.get(term.key, 0) + weight
                weight_origin.setdefault(term.key, layer.origin)
            elif layer.origin == LAYER_RECIPE:
                recipe_weight[term.key] = weight
                weight_origin[term.key] = layer.origin
            elif layer.origin == LAYER_RUN:
                run_weight[term.key] = weight
                weight_origin[term.key] = layer.origin
            else:
                raise M3GrammarError(
                    f"invalid-selection-grammar: unknown layer origin {layer.origin!r} "
                    "(workspace / goal:<id> / recipe / run — §12.1)"
                )

    prefer: list[EffectivePrefer] = []
    for key in term_order:
        if key in run_weight:  # the most-local explicit weight wins outright (CA10)
            prefer.append(EffectivePrefer(terms[key], run_weight[key], LAYER_RUN))
        elif key in recipe_weight:
            prefer.append(EffectivePrefer(terms[key], recipe_weight[key], LAYER_RECIPE))
        else:  # goal nudges adjust the workspace BASELINE (0 when the workspace is silent)
            weight = workspace_weight.get(key, 0) + goal_nudges.get(key, 0)
            prefer.append(EffectivePrefer(terms[key], weight, weight_origin[key]))

    return EffectiveSelection(
        require=tuple(require.values()),
        require_origins=require_origins,
        span=span,
        span_origins=span_origins,
        prefer=tuple(prefer),
        on_conflict=on_conflict if on_conflict is not None else DEFAULT_ON_CONFLICT,
        on_conflict_origin=on_conflict_origin,
        relaxed=tuple(relaxed),
        warnings=tuple(warnings),
    )


def resolve_selection(
    *,
    workspace: Mapping[str, Any] | None = None,
    goals: Sequence[tuple[str, Mapping[str, Any]]] = (),
    recipe: Mapping[str, Any] | None = None,
    run: Mapping[str, Any] | None = None,
) -> EffectiveSelection:
    """Parse + fold the four M3 layers (§12.1) into one effective expression.

    `workspace` and `goals` are exactly `pipeline.cascade.M3Inputs`' fields
    (`workspace_baseline`, `goal_implied`); `recipe`/`run` are the two more-local
    layers their owning steps supply. Order of record: workspace-default →
    goal-implied (selection order) → recipe → run.
    """
    layers: list[SelectionLayer] = [
        parse_selection_layer(workspace, origin=LAYER_WORKSPACE),
    ]
    for goal_id, contribution in goals:
        layers.append(parse_selection_layer(contribution, origin=goal_layer_origin(goal_id)))
    layers.append(parse_selection_layer(recipe, origin=LAYER_RECIPE))
    layers.append(parse_selection_layer(run, origin=LAYER_RUN))
    return fold_layers(layers)


# --- Clause evaluation (shared by the grounding resolver) -----------------------------------


def _freshness_window(value: Any) -> tuple[datetime.date, datetime.date] | None:
    """A fact-side freshness value as an inclusive [start, end] window (point date →
    [d, d]); None when unknown."""
    if value is None:
        return None
    if isinstance(value, datetime.date) and not isinstance(value, datetime.datetime):
        return value, value
    if isinstance(value, list | tuple) and len(value) == 2:
        start, end = value
        if (
            isinstance(start, datetime.date)
            and not isinstance(start, datetime.datetime)
            and isinstance(end, datetime.date)
            and not isinstance(end, datetime.datetime)
            and start <= end
        ):
            return start, end
    raise M3GrammarError(
        f"invalid-selection-grammar: freshness value must be a bare date or a "
        f"[start, end] pair, got {value!r}"
    )


def evaluate_clause(clause: SelectionClause, value: Any, *, now: datetime.date) -> bool:
    """Evaluate one clause against one effective value. UNKNOWN (None) never satisfies
    a hard clause — a gate a value cannot be shown to pass is not passed. The clock is
    injected (`now`), never read ambiently."""
    if value is None:
        return False
    score_type = SCORE_TYPES[clause.score]

    if score_type in {"slider", "count"}:
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        if clause.op == PRED_EQ:
            return value == clause.operand
        if clause.op == PRED_GE:
            return value >= clause.operand
        if clause.op == PRED_LE:
            return value <= clause.operand
        if clause.op == PRED_GT:
            return value > clause.operand
        return value < clause.operand  # PRED_LT

    if score_type == "ordinal":
        order = ORDINAL_MEMBERS[clause.score]
        if value not in order:
            return False
        if clause.op == PRED_EQ:
            return value == clause.operand
        if clause.op == PRED_IN:
            return value in clause.operand
        rank, want = order.index(value), order.index(clause.operand)
        if clause.op == PRED_GE:
            return rank >= want
        if clause.op == PRED_LE:
            return rank <= want
        if clause.op == PRED_GT:
            return rank > want
        return rank < want  # PRED_LT

    if score_type in {"categorical", "categorical-open"}:
        if clause.op == PRED_EQ:
            return value == clause.operand
        return value in clause.operand  # PRED_IN

    if score_type == "bool":
        return isinstance(value, bool) and value is clause.operand  # M3_IS

    # date-window (freshness)
    window = _freshness_window(value)
    if window is None:
        return False
    start, end = window
    if clause.op == PRED_LT:
        cutoff, _ = month_window(now, parse_window_expression(clause.operand))
        return start > cutoff  # strictly newer than the cutoff (module-doc convention)
    if clause.op == M3_CONTAINS:
        return start <= clause.operand <= end
    # M3_OVERLAPS
    if isinstance(clause.operand, str):
        o_start, o_end = month_window(now, parse_window_expression(clause.operand))
    else:
        o_start, o_end = clause.operand
    return start <= o_end and end >= o_start


def bare_score_contribution(score: str, value: Any, *, now: datetime.date) -> float:
    """The scalar ranking contribution of one bare-prefer score value (weight applied by
    the caller). Deterministic; unknown (None) contributes 0. Conventions (in-latitude,
    documented): scalar scores contribute their value; ordinals their low→high rank;
    booleans 1/0; freshness a recency factor in [0, 1] (1 at `now`, linearly down to 0
    at 365 days old — `prefer fresh`, §6.3)."""
    _refuse_unknown_score(score)
    if value is None:
        return 0.0
    score_type = SCORE_TYPES[score]
    if score_type in {"slider", "count"}:
        return float(value)
    if score_type == "ordinal":
        order = ORDINAL_MEMBERS[score]
        return float(order.index(value)) if value in order else 0.0
    if score_type == "bool":
        return 1.0 if value is True else 0.0
    if score_type == "date-window":
        window = _freshness_window(value)
        if window is None:
            return 0.0
        age_days = (now - window[1]).days
        return max(0.0, min(1.0, 1.0 - age_days / 365.0))
    raise M3GrammarError(  # categorical — structurally unreachable (PreferTerm refuses)
        f"invalid-selection-grammar: bare prefer on categorical {score!r}"
    )
