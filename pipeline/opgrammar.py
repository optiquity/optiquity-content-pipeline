"""The D1.1 unified operator grammar (§13.2): one AST, two surfaces, one validator.

Design authority: `docs/design.md` §13.2 (the canonical `Bind`/`Pred` AST, the two surface
syntaxes, the `=` disambiguation, the single `path` wire key, the M3 boundary), §12.4 (combine
semantics; the CM3 binding-site operator spellings — bare/assignment = replace, `+` key suffix
and the `{combine: …, add: …}` wrapper), §7.4 (the slug alphabet grounding path segments),
§21.3/§21.4 (the consumers: discovery filters ride `Pred`, run overrides ride `Bind`).
Spec doc: `docs/reference/operator-grammar.md` (the §27.4 grammar-spec deliverable).

The grammar (verbatim from §13.2):

    Expr    := Bind(path, bind_op, operand)   # a binding (combine-mode, overrides)
             | Pred(path, pred_op, operand)   # a predicate (discovery filters)
    path    := ident ("." ident)*             # dimension.attribute, or bare field
    bind_op := replace | union                # set-subtract '-' reserved, not v1
    pred_op := eq | in | prefix | ge | le | gt | lt | range
    operand := scalar | seq | map             # §11.1 literals, in the HOST format's native literal

**Bounded by design (§13.2/§13.5):** operands always ride the host format's native literal
(YAML value in the frontmatter surface, JSON value on the wire, and — for the interactive
`field op value` string — one pinned-YAML-1.2 literal via `pipeline.yamlio.load_yaml`). The
only custom parsing here is the dotted path + the operator token. This module is NEVER a
general expression language. **M3 source-selection clauses are NOT carried by this AST**
(§13.2): they ride M3's own grammar (§6.3, plan step 17), sharing only the operator-VOCABULARY
discipline — step 17 imports the token constants below instead of re-declaring strings, so
vocabulary drift fails mechanically (step-6 disposition A7).

**One validator.** Bind-op tokens are validated by `pipeline.attrtypes.validate_combine_operator`
(the §12.4 vocabulary's single implementation — the reserved set-subtract `-` refusal and the
union-on-non-set schema ERROR live there, re-exported here); `pred_op` is homed HERE (its only
home). The two vocabularies are disjoint, which is what lets each wire context refuse the
other's operators loudly.

**`=` disambiguation (§13.2):** the assignment token means *replace* in a binding context and
*equals* in a predicate context. The contexts never co-occur — bindings arrive via
`parse_frontmatter_binding`/`parse_wire_bind`, predicates via `parse_pred_string`/
`parse_wire_pred` — and the AST tags the node kind (`Bind` vs `Pred` are distinct types that
never compare equal), so no ambiguity exists at the semantic layer.

In-latitude decisions (grounded in the coder report, step 9):

- **Path ident alphabet** = the §7.4 slug alphabet extended with MEDIAL `_`:
  `[a-z0-9]([a-z0-9_-]{0,38}[a-z0-9])?` per dot-separated segment. §7.4's strict slug
  alphabet governs registry ENTRY ids; path segments also name schema ATTRIBUTES, and the
  design's own ratified surfaces use `_` there (`word_limit` in the §13.2 table itself,
  `definition_version` §11.2, `default_voice` §5.2). Uppercase, empty segments, leading dots,
  `~`, and leading/trailing `_`/`-` are refused. Whether a path's segments name a real declared
  attribute is the schema-aware consumers' job (§21.4 API5, plan step 16) — this layer
  validates shape only.
- **The wrapper is the general explicit-operator spelling:** `{combine: <bind_op>, add: <operand>}`
  accepts any §12.4 bind_op (`combine: replace` is legal-but-redundant; the canonical rendering
  of replace is the bare form). A mapping value containing the key `combine` is ALWAYS treated
  as the wrapper — a malformed wrapper is refused loudly, never silently read as a plain map
  operand (the wrapper shape is reserved; documented in the spec doc).
- **Pred-string rendering is self-verifying:** a string operand renders bare only if the pinned
  loader parses the bare text back to the identical string (so `no` stays bare — YAML 1.2! —
  while `true` gets JSON quotes); everything else renders as canonical JSON, which is valid
  YAML 1.2 flow style. Bare `datetime.date` renders ISO-8601 (the pinned loader's D2 deviation
  loads it back as a date); timestamps and dates inside containers are refused — no lossless
  single-line host literal exists for them.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pipeline.attrtypes import (
    AttrTypeSpec,
    CombineOperatorError,
    validate_combine_operator,
    validate_value,
)
from pipeline.canonical import canonical_json_str
from pipeline.yamlio import YAMLLoadError, load_yaml

__all__ = [
    "BIND_OPS",
    "BIND_REPLACE",
    "BIND_UNION",
    "Bind",
    "CombineOperatorError",
    "OperatorGrammarError",
    "PRED_EQ",
    "PRED_GE",
    "PRED_GT",
    "PRED_IN",
    "PRED_LE",
    "PRED_LT",
    "PRED_OPS",
    "PRED_PREFIX",
    "PRED_RANGE",
    "PRED_STRING_TOKENS",
    "PathSyntaxError",
    "Pred",
    "PredOperatorError",
    "RESERVED_SET_SUBTRACT",
    "SurfaceSyntaxError",
    "parse_frontmatter_binding",
    "parse_pred_string",
    "parse_wire_bind",
    "parse_wire_pred",
    "render_frontmatter_binding",
    "render_pred_string",
    "render_wire",
    "validate_bind_against_spec",
    "validate_path",
]

# --- Operator vocabularies (§13.2) — THE token constants; step 17 imports these (A7). ------

BIND_REPLACE = "replace"
BIND_UNION = "union"
BIND_OPS = frozenset({BIND_REPLACE, BIND_UNION})

#: Set-subtract is RESERVED, not v1 (§12.4/§13.2/§26) — always refused, loudly.
RESERVED_SET_SUBTRACT = "-"

PRED_EQ = "eq"
PRED_IN = "in"
PRED_PREFIX = "prefix"
PRED_GE = "ge"
PRED_LE = "le"
PRED_GT = "gt"
PRED_LT = "lt"
PRED_RANGE = "range"
PRED_OPS = frozenset(
    {PRED_EQ, PRED_IN, PRED_PREFIX, PRED_GE, PRED_LE, PRED_GT, PRED_LT, PRED_RANGE}
)

#: Interactive `field op value` string tokens (§13.2/§21.3) → canonical pred_op names.
#: `=` is the Pred equals token (the §13.2 disambiguation); word-ops use their own names.
PRED_STRING_TOKENS: dict[str, str] = {
    "=": PRED_EQ,
    ">=": PRED_GE,
    "<=": PRED_LE,
    ">": PRED_GT,
    "<": PRED_LT,
    "in": PRED_IN,
    "prefix": PRED_PREFIX,
    "range": PRED_RANGE,
}
_PRED_OP_TO_TOKEN = {op: token for token, op in PRED_STRING_TOKENS.items()}

#: §6.2 date-window operators — M3-clause vocabulary, explicitly NOT pred_op members (§13.2).
_M3_ONLY_OPERATORS = frozenset({"contains", "overlaps"})

# The wire object shape (§13.2): the SINGLE path key — there is no `field` wire key.
_WIRE_KEYS = frozenset({"path", "op", "value"})

# Path segment: §7.4 slug alphabet + medial `_` (see module docstring), 1-40 chars.
_IDENT_RE = re.compile(r"\A[a-z0-9](?:[a-z0-9_-]{0,38}[a-z0-9])?\Z")

# A set-kind spec makes validate_combine_operator a PURE vocabulary check (union is legal on
# set), so the §12.4 token validation has exactly one implementation (attrtypes).
_BIND_TOKEN_CONTEXT = AttrTypeSpec(kind="set")


# --- Typed errors ---------------------------------------------------------------------------


class OperatorGrammarError(ValueError):
    """Base class for §13.2 grammar refusals. `code` is the stable error-code string."""

    code = "operator-grammar-refused"


class PathSyntaxError(OperatorGrammarError):
    """A malformed dotted path (§13.2 `path`; segment alphabet per §7.4 — see module doc)."""

    code = "invalid-path"


class PredOperatorError(OperatorGrammarError):
    """An operator that is not a §13.2 `pred_op` used in a predicate context."""

    code = "invalid-pred-operator"


class SurfaceSyntaxError(OperatorGrammarError):
    """A malformed surface form (wire object shape, wrapper shape, `field op value` string)."""

    code = "invalid-operator-surface"


# --- Shape validation -----------------------------------------------------------------------


def validate_path(path: Any) -> None:
    """Validate a §13.2 dotted path: `ident ("." ident)*`; return None or raise, never fix."""
    if not isinstance(path, str):
        raise PathSyntaxError(f"invalid-path: a path is a dotted string, got {type(path).__name__}")
    if not path:
        raise PathSyntaxError("invalid-path: empty path")
    for segment in path.split("."):
        if not _IDENT_RE.match(segment):
            raise PathSyntaxError(
                f"invalid-path: segment {segment!r} in path {path!r} — segments are "
                "lowercase [a-z0-9] with medial [-_], 1-40 chars (§13.2 path over the "
                "§7.4 alphabet); no uppercase, no empty segments, no '~', no "
                "leading/trailing '-' or '_'"
            )


def _validate_bind_op_token(op: Any) -> None:
    """Vocabulary-check a bind_op token via the ONE §12.4 validator (attrtypes)."""
    if not isinstance(op, str):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: bind_op must be a string token, got {type(op).__name__}"
        )
    # Reserved '-' and unknown ops (incl. pred_ops in a Bind context) raise
    # CombineOperatorError here — the single §12.4 implementation.
    validate_combine_operator(_BIND_TOKEN_CONTEXT, op)


def _validate_pred_op_token(op: Any) -> None:
    """Vocabulary-check a pred_op name (§13.2; this module is the pred_op home)."""
    if not isinstance(op, str):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: pred_op must be a string token, got {type(op).__name__}"
        )
    if op in PRED_OPS:
        return
    if op in _M3_ONLY_OPERATORS:
        raise PredOperatorError(
            f"invalid-pred-operator: {op!r} is an M3 date-window operator (§6.2) — M3 "
            "clauses ride M3's own grammar and are not carried by this AST (§13.2)"
        )
    if op in BIND_OPS or op == RESERVED_SET_SUBTRACT:
        raise PredOperatorError(
            f"invalid-pred-operator: {op!r} is a bind_op-side token in a Pred context — "
            "the contexts never co-occur (§13.2)"
        )
    raise PredOperatorError(
        f"invalid-pred-operator: unknown pred_op {op!r} "
        f"(§13.2 vocabulary: {', '.join(sorted(PRED_OPS))})"
    )


# --- The canonical AST (§13.2) — node kind is the Bind/Pred type itself ----------------------


@dataclass(frozen=True)
class Bind:
    """`Bind(path, bind_op, operand)` — a binding (combine-mode §12.4, overrides §21.4)."""

    path: str
    op: str
    value: Any

    def __post_init__(self) -> None:
        validate_path(self.path)
        _validate_bind_op_token(self.op)


@dataclass(frozen=True)
class Pred:
    """`Pred(path, pred_op, operand)` — a predicate (discovery filters §21.3)."""

    path: str
    op: str
    value: Any

    def __post_init__(self) -> None:
        validate_path(self.path)
        _validate_pred_op_token(self.op)


def validate_bind_against_spec(bind: Bind, spec: AttrTypeSpec) -> None:
    """Type-level validation of a parsed Bind against its attribute's §11.1 type.

    Delegates BOTH checks to the step-8 single implementations: §12.4 operator×type legality
    (`union` on a non-set is a schema ERROR — `CombineOperatorError`) and §11.1 operand typing
    (`ValueValidationError`). The grammar layer itself never type-checks operands; consumers
    with a schema in hand (plan steps 16/17) call this.
    """
    if not isinstance(bind, Bind):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: expected a Bind node, got {type(bind).__name__}"
        )
    validate_combine_operator(spec, bind.op)
    validate_value(spec, bind.value, path=bind.path)


# --- Surface 1: terse frontmatter (human) ----------------------------------------------------


def parse_frontmatter_binding(key: Any, value: Any) -> Bind:
    """Parse one frontmatter binding `(key, value)` — the already-YAML-loaded host pair.

    Spellings (§12.4/§13.2): bare key = replace (`tags: [a, b]`); `+` key suffix = union
    (`tags+: [c]`); wrapper mapping = explicit operator (`tags: {combine: union, add: [c]}`).
    A `-` key suffix (set-subtract) is reserved and refused. A wrapper on a `+`-suffixed key
    is two operator spellings on one binding — refused.
    """
    if not isinstance(key, str):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: binding key must be a string, got {type(key).__name__}"
        )
    path, op = key, BIND_REPLACE
    suffixed = False
    if key.endswith("+"):
        path, op, suffixed = key[:-1], BIND_UNION, True
    elif key.endswith(RESERVED_SET_SUBTRACT):
        raise CombineOperatorError(
            f"invalid-combine-operator: key {key!r} uses the set-subtract '-' suffix — "
            "set-subtract is reserved and not v1 (§13.2/§26)"
        )
    if isinstance(value, Mapping) and "combine" in value:
        # The wrapper shape is reserved: malformed wrappers are refused loudly, never
        # silently treated as a plain map operand.
        if suffixed:
            raise SurfaceSyntaxError(
                f"invalid-operator-surface: key {key!r} combines the '+' suffix with a "
                "{combine: …} wrapper — one operator spelling per binding (§12.4)"
            )
        if set(value) != {"combine", "add"}:
            raise SurfaceSyntaxError(
                "invalid-operator-surface: the combine wrapper is exactly "
                "{combine: <op>, add: <operand>} (§12.4/§13.2), got keys "
                f"{sorted(str(k) for k in value)!r}"
            )
        return Bind(path=path, op=value["combine"], value=value["add"])
    return Bind(path=path, op=op, value=value)


def render_frontmatter_binding(bind: Bind, *, wrapper: bool = False) -> tuple[str, Any]:
    """Render a Bind to its frontmatter `(key, value)` pair (the host emitter serializes).

    Canonical rendering: bare key for replace, `+` key suffix for union (the first documented
    §13.2 spelling). `wrapper=True` renders the equivalent `{combine: …, add: …}` spelling.
    """
    if not isinstance(bind, Bind):
        raise SurfaceSyntaxError(
            "invalid-operator-surface: only Bind has a frontmatter binding surface — a Pred "
            f"renders as the 'field op value' string or the wire object (got "
            f"{type(bind).__name__})"
        )
    if wrapper or (isinstance(bind.value, Mapping) and "combine" in bind.value):
        # A map operand containing `combine` would re-parse as the reserved wrapper shape —
        # self-escape by rendering the explicit wrapper spelling (its `add` carries the
        # operand verbatim, so the round-trip is exact).
        return bind.path, {"combine": bind.op, "add": bind.value}
    if bind.op == BIND_UNION:
        return f"{bind.path}+", bind.value
    return bind.path, bind.value


# --- Surface 1b: the interactive `field op value` string (Pred; §13.2/§21.3) -----------------


def parse_pred_string(text: Any) -> Pred:
    """Parse the interactive predicate string: `field op value`, single line.

    The custom parsing is EXACTLY the path token + the operator token (§13.2); the value tail
    is one host-native literal, parsed by the pinned YAML 1.2 loader (`yamlio.load_yaml`).
    """
    if not isinstance(text, str):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: a predicate string is a str, got {type(text).__name__}"
        )
    if "\n" in text or "\r" in text:
        raise SurfaceSyntaxError(
            "invalid-operator-surface: a predicate string is a single line ('field op value')"
        )
    parts = text.split(None, 2)
    if len(parts) != 3:
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: expected 'field op value' (§13.2/§21.3), got {text!r}"
        )
    path_token, op_token, operand_text = parts
    if op_token == "==":
        raise PredOperatorError(
            "invalid-pred-operator: '==' is not a token of this grammar — '=' is the Pred "
            "equals token (§13.2); '==' belongs to the M3 clause grammar (§6.3), which this "
            "AST does not carry"
        )
    if op_token in _M3_ONLY_OPERATORS:
        raise PredOperatorError(
            f"invalid-pred-operator: {op_token!r} is an M3 date-window operator (§6.2), not "
            "a pred_op — M3 clauses are not carried by this AST (§13.2)"
        )
    op = PRED_STRING_TOKENS.get(op_token)
    if op is None:
        raise PredOperatorError(
            f"invalid-pred-operator: unknown operator token {op_token!r} "
            f"(tokens: {' '.join(PRED_STRING_TOKENS)})"
        )
    try:
        operand = load_yaml(operand_text)
    except YAMLLoadError as exc:
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: operand {operand_text!r} is not a valid host "
            "(YAML 1.2) literal"
        ) from exc
    return Pred(path=path_token, op=op, value=operand)


def _contains_date(value: Any) -> bool:
    if isinstance(value, datetime.date):  # covers datetime.datetime (subclass)
        return True
    if isinstance(value, list | tuple):
        return any(_contains_date(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_date(v) for v in value.values())
    return False


def _render_operand_text(value: Any) -> str:
    """Render an operand as a single host (YAML 1.2) literal — self-verifying, lossless.

    Strings render bare iff the pinned loader parses the bare text back to the identical
    string; otherwise canonical JSON (valid YAML 1.2 flow style). Bare dates render ISO-8601
    (the pinned loader's D2 deviation loads them back as dates); timestamps and dates inside
    containers have no lossless single-line literal and are refused — use the wire surface.
    """
    if isinstance(value, datetime.datetime):
        raise SurfaceSyntaxError(
            "invalid-operator-surface: timestamps have no string-surface rendering (the "
            "grammar carries bare dates only — cf. pipeline/canonical.py)"
        )
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, str):
        if "\n" not in value and "\r" not in value:
            try:
                if load_yaml(value) == value:
                    return value
            except YAMLLoadError:
                pass
        return canonical_json_str(value)
    if _contains_date(value):
        raise SurfaceSyntaxError(
            "invalid-operator-surface: dates inside container operands have no lossless "
            "string-surface rendering — use the wire / host-native surface"
        )
    # bool/int/float/None/seq/map: canonical JSON is a valid YAML 1.2 flow literal that the
    # pinned loader reads back type-identically. Non-JSON-able values are refused loudly by
    # canonical_json_str (CanonicalizationError — typed).
    return canonical_json_str(value)


def render_pred_string(pred: Pred) -> str:
    """Render a Pred to the canonical interactive string: `field op value`."""
    if not isinstance(pred, Pred):
        raise SurfaceSyntaxError(
            "invalid-operator-surface: only Pred has the 'field op value' string surface — "
            f"a Bind renders as a frontmatter pair or the wire object (got "
            f"{type(pred).__name__})"
        )
    return f"{pred.path} {_PRED_OP_TO_TOKEN[pred.op]} {_render_operand_text(pred.value)}"


# --- Surface 2: the wire (JSON object; §13.2) -------------------------------------------------


def _wire_parts(obj: Any, node_kind: str) -> tuple[str, Any, Any]:
    """Shape-check a wire object: exactly the keys {path, op, value}, string path."""
    if not isinstance(obj, Mapping):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: the wire form of a {node_kind} is a JSON object "
            f'{{"path","op","value"}} (§13.2), got {type(obj).__name__}'
        )
    keys = {str(k) for k in obj}
    if keys != _WIRE_KEYS:
        extra = sorted(keys - _WIRE_KEYS)
        missing = sorted(_WIRE_KEYS - keys)
        hint = (
            " — there is no 'field' wire key; the single wire key is 'path' (§13.2)"
            if "field" in extra
            else ""
        )
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: wire object keys must be exactly path/op/value; "
            f"extra: {extra!r}, missing: {missing!r}{hint}"
        )
    try:
        return obj["path"], obj["op"], obj["value"]
    except KeyError as exc:  # non-string keys whose str() mimics a wire key
        raise SurfaceSyntaxError(
            "invalid-operator-surface: wire object keys must be the strings path/op/value"
        ) from exc


def parse_wire_bind(obj: Any) -> Bind:
    """Parse a wire object in a BINDING context (§21.4 overrides, §12.4 combine bindings)."""
    path, op, value = _wire_parts(obj, "Bind")
    return Bind(path=path, op=op, value=value)


def parse_wire_pred(obj: Any) -> Pred:
    """Parse a wire object in a PREDICATE context (§21.3 discovery filters)."""
    path, op, value = _wire_parts(obj, "Pred")
    return Pred(path=path, op=op, value=value)


def render_wire(node: Bind | Pred) -> dict[str, Any]:
    """Render either node kind to its wire object — one shape, the single `path` key."""
    if not isinstance(node, Bind | Pred):
        raise SurfaceSyntaxError(
            f"invalid-operator-surface: expected a Bind or Pred node, got {type(node).__name__}"
        )
    return {"path": node.path, "op": node.op, "value": node.value}
