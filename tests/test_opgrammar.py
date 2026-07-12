"""Step-9 tests: the D1.1 unified operator grammar (`pipeline/opgrammar.py`).

Acceptance under test (plan step 9): every §13.2 table row parses to the exact documented
AST and re-renders to both surfaces; both syntaxes yield an identical AST for every
operator; the `=` Bind/Pred disambiguation; the reserved set-subtract `-` is refused loudly
and typed; `+` (union) on a non-set is the §11.1 schema-ERROR path; malformed paths are
refused per the §7.4-grounded alphabet; wire objects with unknown ops or extra keys are
refused; round-trips (AST → each syntax → AST) are stable.
"""

import datetime
import json

import pytest

from pipeline.attrtypes import (
    AttrTypeSpec,
    CombineOperatorError,
    ValueValidationError,
    validate_combine_operator,
)
from pipeline.opgrammar import (
    BIND_OPS,
    PRED_OPS,
    PRED_STRING_TOKENS,
    RESERVED_SET_SUBTRACT,
    Bind,
    PathSyntaxError,
    Pred,
    PredOperatorError,
    SurfaceSyntaxError,
    parse_frontmatter_binding,
    parse_pred_string,
    parse_wire_bind,
    parse_wire_pred,
    render_frontmatter_binding,
    render_pred_string,
    render_wire,
    validate_bind_against_spec,
    validate_path,
)

# ---------------------------------------------------------------------------
# The §13.2 table, row by row: documented AST, terse surface, wire surface
# ---------------------------------------------------------------------------


def test_table_row_1_bind_replace_list() -> None:
    expected = Bind("tags", "replace", ["a", "b"])
    assert parse_frontmatter_binding("tags", ["a", "b"]) == expected
    wire = json.loads('{"path":"tags","op":"replace","value":["a","b"]}')
    assert parse_wire_bind(wire) == expected
    assert render_frontmatter_binding(expected) == ("tags", ["a", "b"])
    assert render_wire(expected) == {"path": "tags", "op": "replace", "value": ["a", "b"]}


def test_table_row_2_bind_union_both_terse_spellings() -> None:
    expected = Bind("tags", "union", ["c"])
    # First documented spelling: the `+` key suffix.
    assert parse_frontmatter_binding("tags+", ["c"]) == expected
    # Second documented spelling: the wrapper.
    assert parse_frontmatter_binding("tags", {"combine": "union", "add": ["c"]}) == expected
    wire = json.loads('{"path":"tags","op":"union","value":["c"]}')
    assert parse_wire_bind(wire) == expected
    # Canonical terse rendering is the `+` suffix; the wrapper rendering is also stable.
    assert render_frontmatter_binding(expected) == ("tags+", ["c"])
    assert render_frontmatter_binding(expected, wrapper=True) == (
        "tags",
        {"combine": "union", "add": ["c"]},
    )
    assert render_wire(expected) == {"path": "tags", "op": "union", "value": ["c"]}


def test_table_row_3_bind_replace_dotted_path_scalar() -> None:
    expected = Bind("voice.formality", "replace", 2)
    assert parse_frontmatter_binding("voice.formality", 2) == expected
    wire = json.loads('{"path":"voice.formality","op":"replace","value":2}')
    assert parse_wire_bind(wire) == expected
    assert render_frontmatter_binding(expected) == ("voice.formality", 2)
    assert render_wire(expected) == {"path": "voice.formality", "op": "replace", "value": 2}


def test_table_row_4_pred_eq() -> None:
    expected = Pred("provenance", "eq", "instance")
    assert parse_pred_string("provenance = instance") == expected
    wire = json.loads('{"path":"provenance","op":"eq","value":"instance"}')
    assert parse_wire_pred(wire) == expected
    # Byte-exact re-render of the documented interactive form.
    assert render_pred_string(expected) == "provenance = instance"
    assert render_wire(expected) == {"path": "provenance", "op": "eq", "value": "instance"}


def test_table_row_5_pred_ge_with_documented_underscore_path() -> None:
    # `word_limit` is the design's OWN table row — medial `_` in a path ident is ratified
    # by §13.2 itself (the strict §7.4 slug alphabet governs registry entry ids).
    expected = Pred("word_limit", "ge", 400)
    assert parse_pred_string("word_limit >= 400") == expected
    wire = json.loads('{"path":"word_limit","op":"ge","value":400}')
    assert parse_wire_pred(wire) == expected
    assert render_pred_string(expected) == "word_limit >= 400"
    assert render_wire(expected) == {"path": "word_limit", "op": "ge", "value": 400}
    assert isinstance(parse_pred_string("word_limit >= 400").value, int)


# ---------------------------------------------------------------------------
# Both syntaxes → identical AST, for EVERY operator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "value", "wire"),
    [
        ("tags", ["a"], {"path": "tags", "op": "replace", "value": ["a"]}),
        ("tags+", ["c"], {"path": "tags", "op": "union", "value": ["c"]}),
        (
            "tags",
            {"combine": "union", "add": ["c"]},
            {"path": "tags", "op": "union", "value": ["c"]},
        ),
        (
            "tags",
            {"combine": "replace", "add": ["a"]},
            {"path": "tags", "op": "replace", "value": ["a"]},
        ),
    ],
)
def test_every_bind_op_terse_and_wire_agree(key: str, value: object, wire: dict) -> None:
    assert parse_frontmatter_binding(key, value) == parse_wire_bind(wire)


@pytest.mark.parametrize(
    ("text", "wire"),
    [
        ("provenance = instance", {"path": "provenance", "op": "eq", "value": "instance"}),
        ("tags in [a, b]", {"path": "tags", "op": "in", "value": ["a", "b"]}),
        ("topic prefix intro-", {"path": "topic", "op": "prefix", "value": "intro-"}),
        ("word_limit >= 400", {"path": "word_limit", "op": "ge", "value": 400}),
        ("word_limit <= 900", {"path": "word_limit", "op": "le", "value": 900}),
        ("voice.formality > 2", {"path": "voice.formality", "op": "gt", "value": 2}),
        ("voice.formality < 5", {"path": "voice.formality", "op": "lt", "value": 5}),
        ("word_limit range [400, 900]", {"path": "word_limit", "op": "range", "value": [400, 900]}),
    ],
)
def test_every_pred_op_string_and_wire_agree(text: str, wire: dict) -> None:
    assert parse_pred_string(text) == parse_wire_pred(wire)


def test_pred_op_battery_is_the_whole_ratified_vocabulary() -> None:
    # The parametrization above covers each pred_op exactly once — pin that claim.
    assert PRED_OPS == frozenset({"eq", "in", "prefix", "ge", "le", "gt", "lt", "range"})
    assert BIND_OPS == frozenset({"replace", "union"})


# ---------------------------------------------------------------------------
# The `=` disambiguation: Bind=replace vs Pred=equals, by node kind
# ---------------------------------------------------------------------------


def test_assignment_in_binding_context_is_replace() -> None:
    # The frontmatter assignment (`provenance: instance`) IS the binding-site `=`.
    node = parse_frontmatter_binding("provenance", "instance")
    assert node == Bind("provenance", "replace", "instance")


def test_equals_token_in_predicate_context_is_eq() -> None:
    node = parse_pred_string("provenance = instance")
    assert node == Pred("provenance", "eq", "instance")


def test_node_kind_is_the_disambiguator_never_field_equality() -> None:
    bind = Bind("provenance", "replace", "instance")
    pred = Pred("provenance", "eq", "instance")
    assert bind != pred  # distinct AST node kinds, even over the same path/value
    assert (bind.path, bind.value) == (pred.path, pred.value)


def test_contexts_never_co_occur_wire_vocabularies_are_walled() -> None:
    # A pred_op in a Bind context is refused by the ONE §12.4 validator…
    with pytest.raises(CombineOperatorError):
        parse_wire_bind({"path": "provenance", "op": "eq", "value": "instance"})
    # …and a bind_op in a Pred context is refused by the pred vocabulary.
    with pytest.raises(PredOperatorError, match="contexts never co-occur"):
        parse_wire_pred({"path": "tags", "op": "replace", "value": ["a"]})
    with pytest.raises(PredOperatorError):
        parse_wire_pred({"path": "tags", "op": "union", "value": ["c"]})
    assert BIND_OPS.isdisjoint(PRED_OPS)


def test_renderers_refuse_the_wrong_node_kind() -> None:
    with pytest.raises(SurfaceSyntaxError):
        render_frontmatter_binding(Pred("a", "eq", 1))  # type: ignore[arg-type]
    with pytest.raises(SurfaceSyntaxError):
        render_pred_string(Bind("a", "replace", 1))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Set-subtract `-`: RESERVED-REFUSED — loud and typed, on every surface
# ---------------------------------------------------------------------------


def test_reserved_token_constant() -> None:
    assert RESERVED_SET_SUBTRACT == "-"
    assert RESERVED_SET_SUBTRACT not in BIND_OPS


def test_subtract_key_suffix_is_refused_loudly() -> None:
    with pytest.raises(CombineOperatorError, match="reserved") as excinfo:
        parse_frontmatter_binding("tags-", ["c"])
    assert excinfo.value.code == "invalid-combine-operator"


def test_subtract_in_wrapper_is_refused_loudly() -> None:
    with pytest.raises(CombineOperatorError, match="reserved"):
        parse_frontmatter_binding("tags", {"combine": "-", "add": ["c"]})


def test_subtract_on_the_wire_is_refused_loudly() -> None:
    with pytest.raises(CombineOperatorError, match="reserved"):
        parse_wire_bind({"path": "tags", "op": "-", "value": ["c"]})


def test_subtract_at_direct_ast_construction_is_refused() -> None:
    with pytest.raises(CombineOperatorError, match="reserved"):
        Bind("tags", "-", ["c"])
    with pytest.raises(PredOperatorError):
        Pred("tags", "-", ["c"])


# ---------------------------------------------------------------------------
# `+` (union) on a non-set: the §11.1 schema-ERROR path via the ONE validator
# ---------------------------------------------------------------------------


def test_union_on_ordered_list_is_a_schema_error() -> None:
    bind = parse_frontmatter_binding("parts+", ["intro"])  # grammar-legal shape…
    list_spec = AttrTypeSpec(kind="list", element=AttrTypeSpec(kind="text"))
    with pytest.raises(CombineOperatorError, match="schema ERROR") as excinfo:
        validate_bind_against_spec(bind, list_spec)  # …refused at the schema layer
    assert excinfo.value.code == "invalid-combine-operator"


@pytest.mark.parametrize("kind", ["number", "text", "map", "enum"])
def test_union_on_other_non_set_kinds_is_a_schema_error(kind: str) -> None:
    spec = (
        AttrTypeSpec(kind="enum", values=("a", "b")) if kind == "enum" else AttrTypeSpec(kind=kind)
    )
    bind = Bind("field", "union", ["a"])
    with pytest.raises(CombineOperatorError):
        validate_bind_against_spec(bind, spec)


def test_union_on_a_set_passes_and_operand_is_type_checked() -> None:
    set_spec = AttrTypeSpec(kind="set", element=AttrTypeSpec(kind="ref"))
    validate_bind_against_spec(parse_frontmatter_binding("tags+", ["c"]), set_spec)
    # The delegated §11.1 operand check refuses a bad element (refusal, not coercion).
    with pytest.raises(ValueValidationError):
        validate_bind_against_spec(parse_frontmatter_binding("tags+", [400]), set_spec)


def test_replace_operand_is_type_checked_too() -> None:
    with pytest.raises(ValueValidationError):
        validate_bind_against_spec(
            parse_frontmatter_binding("word_limit", "four hundred"),
            AttrTypeSpec(kind="number"),
        )


# ---------------------------------------------------------------------------
# Malformed paths (§13.2 path over the §7.4 alphabet; medial `_` per the table row)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "Tags",  # uppercase
        "voice.Formality",  # uppercase in a later segment
        ".tags",  # leading dot (empty first segment)
        "tags.",  # trailing dot (empty last segment)
        "a..b",  # empty interior segment
        "_tags",  # leading underscore (`_` is the §7.4 revision-qualifier separator)
        "tags_",  # trailing underscore
        "ta~gs",  # `~` is the §7.4 part-suffix separator, never a path char
        "-tags",  # leading hyphen (slug rule)
        "tags-",  # NOTE: as a KEY this is the reserved `-` suffix; as a PATH it is invalid
        "",  # empty
        "a" * 41,  # over the 40-char segment cap (§7.4)
        "voice formality",  # whitespace
    ],
)
def test_malformed_paths_are_refused_typed(bad: str) -> None:
    with pytest.raises(PathSyntaxError) as excinfo:
        validate_path(bad)
    assert excinfo.value.code == "invalid-path"


@pytest.mark.parametrize(
    "good",
    [
        "tags",
        "voice.formality",
        "word_limit",  # the §13.2 table's own row
        "content-kinds.review_status",  # hyphen + underscore, both medial
        "a",  # single char
        "a1.b2.c3",  # grammar is `ident ("." ident)*` — depth limits are the consumers' job
        "a" * 40,  # exactly at the cap
    ],
)
def test_wellformed_paths_pass(good: str) -> None:
    validate_path(good)


def test_malformed_path_refused_on_every_surface() -> None:
    with pytest.raises(PathSyntaxError):
        parse_frontmatter_binding("Voice.formality", 2)
    with pytest.raises(PathSyntaxError):
        parse_wire_bind({"path": ".tags", "op": "replace", "value": []})
    with pytest.raises(PathSyntaxError):
        parse_wire_pred({"path": "ta~gs", "op": "eq", "value": 1})
    with pytest.raises(PathSyntaxError):
        parse_pred_string("_hidden = 1")
    with pytest.raises(PathSyntaxError):
        parse_wire_bind({"path": 7, "op": "replace", "value": []})  # non-string path


# ---------------------------------------------------------------------------
# Wire objects: unknown ops, extra keys, `field` key, missing keys — refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("parse", [parse_wire_bind, parse_wire_pred])
def test_wire_extra_key_refused(parse) -> None:
    with pytest.raises(SurfaceSyntaxError, match="extra"):
        parse({"path": "tags", "op": "eq", "value": 1, "note": "x"})


@pytest.mark.parametrize("parse", [parse_wire_bind, parse_wire_pred])
def test_wire_field_key_refused_single_path_key(parse) -> None:
    # §13.2: there is no `field` wire key — the single wire key is `path`.
    with pytest.raises(SurfaceSyntaxError, match="no 'field' wire key"):
        parse({"field": "tags", "op": "eq", "value": 1, "path": "tags"})
    with pytest.raises(SurfaceSyntaxError):
        parse({"field": "tags", "op": "eq", "value": 1})


@pytest.mark.parametrize("parse", [parse_wire_bind, parse_wire_pred])
@pytest.mark.parametrize(
    "obj",
    [
        {"path": "tags", "op": "eq"},  # missing value
        {"path": "tags", "value": 1},  # missing op
        {"op": "eq", "value": 1},  # missing path
        {},  # missing everything
        ["path", "op", "value"],  # not a mapping
        "provenance = instance",  # a string is the OTHER surface
    ],
)
def test_wire_wrong_shape_refused(parse, obj) -> None:
    with pytest.raises(SurfaceSyntaxError):
        parse(obj)


def test_wire_unknown_ops_refused_typed() -> None:
    with pytest.raises(CombineOperatorError) as bind_exc:
        parse_wire_bind({"path": "tags", "op": "subtract", "value": ["c"]})
    assert bind_exc.value.code == "invalid-combine-operator"
    with pytest.raises(PredOperatorError) as pred_exc:
        parse_wire_pred({"path": "tags", "op": "matches", "value": "x"})
    assert pred_exc.value.code == "invalid-pred-operator"


def test_wire_op_must_be_the_canonical_name_not_the_string_token() -> None:
    with pytest.raises(PredOperatorError):
        parse_wire_pred({"path": "word_limit", "op": ">=", "value": 400})


def test_wire_non_string_op_refused() -> None:
    with pytest.raises(SurfaceSyntaxError):
        parse_wire_bind({"path": "tags", "op": 3, "value": ["c"]})
    with pytest.raises(SurfaceSyntaxError):
        parse_wire_pred({"path": "tags", "op": None, "value": ["c"]})


def test_wire_non_string_key_mimicking_a_wire_key_refused_typed() -> None:
    # RV-2: a non-string key whose str() mimics "path" passes the str()-coerced key-set
    # check; the extraction guard must turn the raw KeyError into the module's typed refusal.
    class K:
        def __str__(self) -> str:
            return "path"

    with pytest.raises(SurfaceSyntaxError, match="strings path/op/value"):
        parse_wire_bind({K(): "tags", "op": "replace", "value": []})


def test_m3_date_window_operators_are_not_carried_by_this_ast() -> None:
    # §13.2: `contains`/`overlaps` (§6.2) belong to M3's own grammar (plan step 17).
    for op in ("contains", "overlaps"):
        with pytest.raises(PredOperatorError, match="M3"):
            parse_wire_pred({"path": "freshness", "op": op, "value": "2026-01"})
    with pytest.raises(PredOperatorError, match="M3"):
        parse_pred_string("freshness contains 2026-01")
    with pytest.raises(PredOperatorError, match="M3"):
        parse_pred_string("freshness == fresh")  # `==` is M3-flavored; `=` is the Pred token


# ---------------------------------------------------------------------------
# The terse surfaces: malformed strings and wrapper shapes — refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "provenance =",  # missing value
        "provenance",  # missing op + value
        "",  # empty
        "provenance = a\nb = c",  # multi-line
    ],
)
def test_malformed_pred_strings_refused(bad: str) -> None:
    with pytest.raises(SurfaceSyntaxError):
        parse_pred_string(bad)


def test_pred_string_unknown_token_refused() -> None:
    with pytest.raises(PredOperatorError):
        parse_pred_string("provenance is instance")


def test_pred_string_bad_host_literal_refused() -> None:
    with pytest.raises(SurfaceSyntaxError, match="host"):
        parse_pred_string("tags in [a,")


def test_pred_string_non_string_input_refused() -> None:
    with pytest.raises(SurfaceSyntaxError):
        parse_pred_string({"path": "tags", "op": "eq", "value": 1})


@pytest.mark.parametrize(
    "wrapper",
    [
        {"combine": "union"},  # missing add
        {"combine": "union", "add": ["c"], "x": 1},  # extra key
        {"combine": "union", "extend": ["c"]},  # wrong operand key
        {"combine": None, "add": ["c"]},  # non-string op
    ],
)
def test_malformed_wrapper_refused_never_read_as_plain_value(wrapper: dict) -> None:
    with pytest.raises((SurfaceSyntaxError, CombineOperatorError)):
        parse_frontmatter_binding("tags", wrapper)


def test_suffix_plus_wrapper_is_two_spellings_refused() -> None:
    with pytest.raises(SurfaceSyntaxError, match="one operator spelling"):
        parse_frontmatter_binding("tags+", {"combine": "union", "add": ["c"]})


def test_wrapper_unknown_op_refused() -> None:
    with pytest.raises(CombineOperatorError):
        parse_frontmatter_binding("tags", {"combine": "merge", "add": ["c"]})


def test_plain_map_operand_without_combine_key_is_a_replace_binding() -> None:
    # Only the `combine` key triggers the reserved wrapper shape; other maps are operands.
    node = parse_frontmatter_binding("scores", {"add": [1], "weights": {"a": 2}})
    assert node == Bind("scores", "replace", {"add": [1], "weights": {"a": 2}})


def test_wrapper_shaped_map_operand_self_escapes_on_render() -> None:
    # RV-1: a map operand containing `combine` must render via the wrapper spelling —
    # a bare (path, value) pair would re-parse as the reserved wrapper shape and SILENTLY
    # change op replace→union and swap the value for the `add` payload.
    node = parse_wire_bind(
        {"path": "scores", "op": "replace", "value": {"combine": "union", "add": ["c"]}}
    )
    key, value = render_frontmatter_binding(node)
    assert value == {"combine": "replace", "add": {"combine": "union", "add": ["c"]}}
    assert parse_frontmatter_binding(key, value) == node


def test_wrapper_shaped_map_operand_self_escapes_under_union_too() -> None:
    # RV-1, other ordering: the union variant previously rendered a `+`-suffixed key with a
    # wrapper value — a form its OWN parser refuses (two spellings). Self-escape fixes both.
    node = Bind("scores", "union", {"combine": "replace", "add": ["x"]})
    key, value = render_frontmatter_binding(node)
    assert (key, value) == (
        "scores",
        {"combine": "union", "add": {"combine": "replace", "add": ["x"]}},
    )
    assert parse_frontmatter_binding(key, value) == node


def test_non_string_binding_key_refused() -> None:
    with pytest.raises(SurfaceSyntaxError):
        parse_frontmatter_binding(4, [1])


# ---------------------------------------------------------------------------
# Round-trips: AST → each surface → AST, stable for every operator
# ---------------------------------------------------------------------------

_BIND_BATTERY = [
    Bind("tags", "replace", ["a", "b"]),
    Bind("tags", "union", ["c"]),
    Bind("voice.formality", "replace", 2),
    Bind("summary", "replace", "no"),  # YAML 1.2: `no` is a string — the Norway guard
    Bind("scores", "replace", {"clarity": 4, "on": True}),
    Bind("window", "replace", datetime.date(2026, 7, 1)),
    Bind("flag", "replace", False),
    Bind("ratio", "replace", -0.5),
    Bind("note", "replace", None),
    Bind("scores", "replace", {"combine": "union", "add": ["c"]}),  # wrapper-shaped operand
]

_PRED_BATTERY = [
    Pred("provenance", "eq", "instance"),
    Pred("region", "eq", "no"),  # renders BARE and survives — YAML 1.2 pin at work
    Pred("kind", "eq", "true"),  # a STRING "true" must render quoted to survive
    Pred("tags", "in", ["a", "b"]),
    Pred("topic", "prefix", "intro-"),
    Pred("word_limit", "ge", 400),
    Pred("word_limit", "le", 900),
    Pred("voice.formality", "gt", 2),
    Pred("voice.formality", "lt", 5),
    Pred("word_limit", "range", [400, 900]),
    Pred("freshness", "ge", datetime.date(2026, 1, 1)),  # bare date rides the D2 host literal
    Pred("title", "eq", "a b"),  # interior space in a bare plain scalar
    Pred("note", "eq", "x: y"),  # would parse as a map — must self-quote
    Pred("ratio", "gt", -0.5),
]


@pytest.mark.parametrize("node", _BIND_BATTERY, ids=lambda n: f"{n.path}-{n.op}")
def test_bind_roundtrip_terse_and_wire(node: Bind) -> None:
    assert parse_frontmatter_binding(*render_frontmatter_binding(node)) == node
    assert parse_frontmatter_binding(*render_frontmatter_binding(node, wrapper=True)) == node
    assert parse_wire_bind(render_wire(node)) == node


@pytest.mark.parametrize("node", _PRED_BATTERY, ids=lambda n: f"{n.path}-{n.op}")
def test_pred_roundtrip_string_and_wire(node: Pred) -> None:
    assert parse_pred_string(render_pred_string(node)) == node
    assert parse_wire_pred(render_wire(node)) == node


@pytest.mark.parametrize("node", _PRED_BATTERY, ids=lambda n: f"{n.path}-{n.op}")
def test_pred_render_is_idempotently_stable(node: Pred) -> None:
    once = render_pred_string(node)
    assert render_pred_string(parse_pred_string(once)) == once


def test_wire_roundtrip_survives_json_serialization() -> None:
    for node in (_BIND_BATTERY[0], _BIND_BATTERY[1], _PRED_BATTERY[0], _PRED_BATTERY[9]):
        rewired = json.loads(json.dumps(render_wire(node)))
        parsed = (parse_wire_bind if isinstance(node, Bind) else parse_wire_pred)(rewired)
        assert parsed == node


def test_norway_string_renders_bare_and_true_string_renders_quoted() -> None:
    assert render_pred_string(Pred("region", "eq", "no")) == "region = no"
    assert render_pred_string(Pred("kind", "eq", "true")) == 'kind = "true"'


def test_string_surface_refuses_unrenderable_operands() -> None:
    with pytest.raises(SurfaceSyntaxError, match="timestamp"):
        render_pred_string(Pred("t", "eq", datetime.datetime(2026, 7, 1, 12, 0)))
    with pytest.raises(SurfaceSyntaxError, match="container"):
        window = [datetime.date(2026, 1, 1), datetime.date(2026, 6, 30)]
        render_pred_string(Pred("w", "range", window))


def test_operands_ride_the_host_literal_untouched() -> None:
    # D1 (G4 deviation): the host loader reads `1_000` as int 1000 — the grammar passes the
    # host's literal through untyped; §11.1 typing is the schema layer's job.
    assert parse_pred_string("word_limit >= 1_000").value == 1000
    # A map operand rides the wire natively.
    node = parse_wire_bind({"path": "scores", "op": "replace", "value": {"a": [1, 2]}})
    assert node.value == {"a": [1, 2]}


# ---------------------------------------------------------------------------
# Vocabulary discipline: one validator, exported tokens (step-6 disposition A7)
# ---------------------------------------------------------------------------


def test_bind_vocabulary_agrees_with_the_type_system() -> None:
    # The §12.4 vocabulary has ONE implementation (attrtypes); the exported constants must
    # agree with it exactly — accepted members pass, everything else raises.
    spec = AttrTypeSpec(kind="set")
    for op in BIND_OPS:
        validate_combine_operator(spec, op)
    for bad in (RESERVED_SET_SUBTRACT, "merge", "eq"):
        with pytest.raises(CombineOperatorError):
            validate_combine_operator(spec, bad)


def test_pred_string_token_map_is_bijective_over_the_vocabulary() -> None:
    assert set(PRED_STRING_TOKENS.values()) == PRED_OPS
    assert len(PRED_STRING_TOKENS) == len(PRED_OPS)


def test_exported_constants_are_importable_tokens() -> None:
    # Step 17 imports these instead of re-declaring strings (A7): pin names + values.
    from pipeline import opgrammar

    assert opgrammar.BIND_REPLACE == "replace"
    assert opgrammar.BIND_UNION == "union"
    assert (
        opgrammar.PRED_EQ,
        opgrammar.PRED_IN,
        opgrammar.PRED_PREFIX,
        opgrammar.PRED_GE,
        opgrammar.PRED_LE,
        opgrammar.PRED_GT,
        opgrammar.PRED_LT,
        opgrammar.PRED_RANGE,
    ) == ("eq", "in", "prefix", "ge", "le", "gt", "lt", "range")


def test_error_types_are_typed_and_coded() -> None:
    from pipeline.opgrammar import OperatorGrammarError

    for exc_type, code in (
        (PathSyntaxError, "invalid-path"),
        (PredOperatorError, "invalid-pred-operator"),
        (SurfaceSyntaxError, "invalid-operator-surface"),
    ):
        assert issubclass(exc_type, OperatorGrammarError)
        assert issubclass(exc_type, ValueError)
        assert exc_type.code == code
    assert CombineOperatorError.code == "invalid-combine-operator"


def test_ast_nodes_are_frozen() -> None:
    node = Bind("tags", "replace", ["a"])
    with pytest.raises(AttributeError):
        node.op = "union"  # type: ignore[misc]
