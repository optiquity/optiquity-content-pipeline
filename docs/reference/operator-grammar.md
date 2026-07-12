# The unified operator grammar (D1.1) — spec of record

**Status:** implements `docs/design.md` §13.2 verbatim; semantics per §12.4; path alphabet
grounded in §7.4. This is the §27.4 "bounded string parser" grammar-spec deliverable (plan
step 9). Implementation: `pipeline/opgrammar.py` · tests: `tests/test_opgrammar.py`.
`provenance: framework` (mechanism documentation — no instance or client content).

One canonical expression AST serves all three operator surfaces — combine-mode bindings
(§12.4), run-override params (§21.4), and discovery filters (§21.3) — so they cannot drift.

## 1. The grammar (§13.2, verbatim)

```
Expr    := Bind(path, bind_op, operand)      # a binding (combine-mode, overrides)
         | Pred(path, pred_op, operand)      # a predicate (discovery filters)
path    := ident ("." ident)*                # dimension.attribute, or bare field
bind_op := replace | union                   # set-subtract '-' reserved, not v1
pred_op := eq | in | prefix | ge | le | gt | lt | range
operand := scalar | seq | map                # §11.1 type literals, in the HOST format's native literal
```

**Bounded by design** (§13.2/§13.5): the only custom parsing is the dotted path + the
operator token. Operands always ride the host format's native literal — a YAML value in the
frontmatter surface, a JSON value on the wire, one pinned-YAML-1.2 literal in the interactive
string. This grammar is never a general expression language; extending it beyond the forms
below is a defect, not a feature.

## 2. `ident` — the path segment alphabet

```
ident := [a-z0-9] ( [a-z0-9_-]{0,38} [a-z0-9] )?     # 1-40 chars
```

The §7.4 slug alphabet (`[a-z0-9-]`, 1–40, no leading/trailing `-`) governs registry **entry
ids**; path segments additionally name **schema attributes**, whose ratified names use `_`
(`word_limit` in §13.2's own table, `definition_version` §11.2, `default_voice` §5.2) — so the
ident alphabet is the slug alphabet plus **medial** `_`. Refused: uppercase, empty segments
(leading/trailing/double dots), `~` (the §7.4 part-suffix separator), leading/trailing `_`
(the §7.4 revision-qualifier separator) or `-`, whitespace, segments over 40 chars. Whether a
path names a real declared attribute of a selected entry is the schema-aware consumer's job
(§21.4 API5, cascade M2) — the grammar validates shape only.

## 3. The two surface syntaxes over the one AST

| AST node | Frontmatter / human (terse) | Wire (JSON object) |
|---|---|---|
| `Bind(tags, replace, [a,b])` | `tags: [a, b]` | `{"path":"tags","op":"replace","value":["a","b"]}` |
| `Bind(tags, union, [c])` | `tags+: [c]` *or* `tags: {combine: union, add: [c]}` | `{"path":"tags","op":"union","value":["c"]}` |
| `Bind(voice.formality, replace, 2)` | `voice.formality: 2` | `{"path":"voice.formality","op":"replace","value":2}` |
| `Pred(provenance, eq, instance)` | `provenance = instance` | `{"path":"provenance","op":"eq","value":"instance"}` |
| `Pred(word_limit, ge, 400)` | `word_limit >= 400` | `{"path":"word_limit","op":"ge","value":400}` |

### 3.1 Binding surface (terse frontmatter; `parse_frontmatter_binding`)

A binding is a host-YAML `(key, value)` pair. Spellings (§12.4 CM3):

- **bare key** → `replace` (the naive-user default; most-local-wins);
- **`+` key suffix** (`tags+:`) → `union` — canonical union rendering;
- **wrapper mapping** `{combine: <bind_op>, add: <operand>}` → the explicit-operator
  spelling. The wrapper accepts any `bind_op` (`combine: replace` is legal-but-redundant);
  its `combine` value goes through the same single validator, so `combine: -` is the loud
  reserved refusal and `combine: merge` the loud unknown-operator refusal.
- **`-` key suffix** (`tags-:`) → **RESERVED-REFUSED** (set-subtract is not v1; §12.4/§26).

**Reserved wrapper shape:** any mapping VALUE containing the key `combine` is parsed as the
wrapper; a malformed wrapper (missing `add`, extra keys, non-string `combine`, or a wrapper on
an already-`+`-suffixed key) is refused loudly — never silently read as a plain map operand.
A mapping without a `combine` key is an ordinary map operand. Symmetrically, the renderer
self-escapes: a map operand that itself contains a `combine` key always renders via the
wrapper spelling (its `add` carries the operand verbatim), so the reserved shape can never
silently capture an operand on re-parse.

### 3.2 Predicate surface (interactive string; `parse_pred_string`)

`field op value` (§21.3), single line, whitespace-separated. Operator tokens:

| pred_op | eq | ge | le | gt | lt | in | prefix | range |
|---|---|---|---|---|---|---|---|---|
| token | `=` | `>=` | `<=` | `>` | `<` | `in` | `prefix` | `range` |

The value tail (everything after the operator token) is **one host literal**, parsed by the
pinned YAML 1.2 loader (`pipeline.yamlio.load_yaml`) — e.g. `400` → int, `instance` → string
(and `no` → string: the Norway guard, §13.5), `[a, b]` → seq, a bare ISO date → date (loader
deviation D2). `==` is refused with guidance (`=` is the equals token here; `==` belongs to
M3's clause grammar).

Rendering is **self-verifying**: a string operand renders bare only if the pinned loader
parses the bare text back to the identical string (`no` stays bare; `true`, `x: y`, `[a` get
canonical-JSON quotes); other operands render as canonical JSON, which is valid YAML 1.2 flow.
A bare `datetime.date` renders ISO-8601; timestamps, and dates inside containers, have no
lossless single-line literal and are refused (use the wire surface).

### 3.3 Wire surface (`parse_wire_bind` / `parse_wire_pred`)

One JSON object shape for both node kinds: exactly the keys `path`, `op`, `value` — **the
single wire key is `path`; there is no `field` key** (§13.2). `op` is the canonical operator
name (`ge`, never `>=`). Extra keys, missing keys, unknown ops, and non-string paths/ops are
refused. The caller's context picks the node kind; each context refuses the other vocabulary.

## 4. `=` disambiguation & node kinds

`=` (the assignment) means **replace** in a `Bind` and **equals** in a `Pred`. The contexts
never co-occur — bindings arrive through the binding surfaces, predicates through the
predicate surfaces — and the AST tags the node kind (`Bind` and `Pred` are distinct types that
never compare equal), so no ambiguity exists at the semantic layer (§13.2).

## 5. One validator

- **bind_op vocabulary** has one implementation: `pipeline.attrtypes.validate_combine_operator`
  (§12.4). The reserved `-` refusal and the `union`-on-non-`set` **schema ERROR** (§11.1) live
  there. `pipeline.opgrammar.validate_bind_against_spec(bind, spec)` is the hook consumers
  call with a schema in hand: operator×type legality + §11.1 operand typing, both delegated.
- **pred_op vocabulary** is homed in `pipeline/opgrammar.py` (its only home).
- The grammar layer never type-checks operands (they ride the host literal untouched — e.g.
  the loader's D1 deviation `1_000` → `1000` passes through; §11.1 typing is the schema
  layer's job) and never resolves paths against schemas.

## 6. Typed errors

| Error | `code` | Raised for |
|---|---|---|
| `PathSyntaxError` | `invalid-path` | malformed dotted path (§2 above) |
| `attrtypes.CombineOperatorError` (re-exported) | `invalid-combine-operator` | reserved `-`; unknown/cross-vocabulary op in a Bind context; union-on-non-set at `validate_bind_against_spec` |
| `PredOperatorError` | `invalid-pred-operator` | unknown/cross-vocabulary/M3-only op in a Pred context |
| `SurfaceSyntaxError` | `invalid-operator-surface` | malformed wire shape, wrapper shape, or `field op value` string; non-string tokens; unrenderable string-surface operands |

All subclass `OperatorGrammarError(ValueError)` except `CombineOperatorError`, which lives
with the type system (§12.4's single implementation) and is re-exported here.

## 7. What this grammar does NOT carry

**M3 source-selection clauses** (`require`/`prefer`/`span`/`on_conflict`, §6.3) ride M3's own
grammar (plan step 17). They share the operator-**vocabulary** discipline and §11.1's
typed-operand rules, but their date-window operators (`contains`, `overlaps`; §6.2) are not
`pred_op` members, and their `==` token is not this grammar's `=`. Per step-6 disposition A7:
step 17 **imports the token constants from `pipeline/opgrammar.py`** (`BIND_*`, `PRED_*`,
`RESERVED_SET_SUBTRACT`) instead of re-declaring strings, so vocabulary drift fails
mechanically. Folding the M3 clause grammar into this AST remains a registered maintainer
question (§27.3) — additive if ever taken.

Also out of scope here: entry selection (M1), schema resolution, cascade folding (§12.2), and
any operator not listed above. Set-subtract `-` is reserved and refused on every surface.
