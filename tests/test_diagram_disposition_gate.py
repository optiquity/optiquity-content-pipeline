"""C4b (DR-9) — the per-artifact diagram-disposition GATE (the compose-time half of the knob C4a
DECLARED). Transport MOCKED throughout (a `ScriptedRunner` — no real `claude`, no LLM call).

The gate acts ONLY on the two HARD `diagram_disposition` members, at the SAME post-mint,
INSIDE-the-bounded-re-ask locus as the base structural gate, REUSING its
`section-conformance-violation` result code (a diagram stance IS a per-artifact section-conformance
concern — NO new `results.CODES` entry):

- `require` — the artifact MUST carry a GROUNDED `{type=diagram}` section that PASSED the
  transform's HARD grounding gate. THE CRUX: a `posture: illustrative` sketch (which carries the
  reader-visible "illustrative — not source-checked" stamp) does NOT satisfy `require`. For a
  multi-part artifact ONE grounded diagram part is enough.
- `suppress` — the artifact must carry NO `{type=diagram}` section (grounded OR illustrative).
- NEUTRAL `""` and the SOFT members `resist`/`prefer` are writer-directive-only → the gate is a
  NO-OP (they ride `writer.md` into the prompt, never a hard gate).

D3 (pre-writer, ZERO spend): a CONTRADICTORY Format — a `section_schema` that FORBIDS the very
`{type=diagram}` section `require` demands — is refused LOUDLY before any writer call.

The end-to-end require/suppress-with-diagram cases need `dot` (to compile the diagram) + `pandoc`
(the A-gate parses the rewritten `![…]` figure), so they gate on `_requires_pandoc()`; the
no-diagram, neutral/soft, and pre-writer-contradiction cases need NEITHER and always run. The pure
`_diagram_disposition_note` / `_schema_forbids_diagram` unit tests exercise the crux classification
with hand-built docs, tool-free.
"""

from __future__ import annotations

import json

import pytest
from conftest import requires_dot  # noqa: E402

# Reuse the mocked-transport harness + builders from the compose test module (prepend import mode
# puts `tests/` on the path — the SAME cross-import pattern test_parallel_plan/test_normalize use).
from test_compose import (  # noqa: E402
    COMMIT_SHA,
    DIAGRAM_FIGURE_RE,
    GROUNDED_DIAGRAM,
    NeverRunner,
    ScriptedRunner,
    _requires_pandoc,
    make_fact,
    make_request,
    writer_ok,
)

from pipeline.canonical import canonical_json_bytes
from pipeline.claims import ClaimRegistry
from pipeline.compose import (
    CODE_SECTION_CONFORMANCE_VIOLATION,
    ComposeError,
    ComposeRequest,
    _diagram_disposition_note,
    _schema_forbids_diagram,
    _schema_requires_diagram,
    build_grounding_ledger,
    compose_artifact,
)
from pipeline.ids import EntryBinding, build_artifact_preimage, mint_artifact_id
from pipeline.ir import build_ir
from pipeline.outline import outline_digest
from pipeline.sections import Cardinality, Count, Presence, Selector
from pipeline.store import WorkspaceStore


@pytest.fixture
def store(tmp_path) -> WorkspaceStore:
    return WorkspaceStore(tmp_path / "ws")


@pytest.fixture
def claims(store) -> ClaimRegistry:
    return ClaimRegistry(
        store.claims_dir, holder="worker-a", ttl_seconds=60.0, clock=lambda: 1_000_000.0
    )


# A `posture: illustrative` diagram body: uncited edges are allowed under the explicit illustrative
# posture, so it compiles — but it carries the reader-visible stamp and NEVER satisfies `require`.
ILLUSTRATIVE_DIAGRAM = (
    "## Sketch {type=diagram}\n\n"
    "posture: illustrative\n"
    "nodes:\n- a: Box A\n- b: Box B\n"
    "edges:\n- a -> b\n"
)

# A grounded prose claim carried ALONGSIDE a diagram — used to prove `suppress` drops the diagram,
# never the fact.
PROSE_CLAIM = 'The parser [runs in linear time]{.EXTRACTED data-fact="f0"}.'


# --- the pure gate: `_diagram_disposition_note` (hand-built docs, tool-free) ----------------

# The post-transform figure bodies the gate reads: a grounded figure carries NO stamp; an
# illustrative figure carries the reader-visible marker in its rewritten alt/caption.
_GROUNDED_FIG = (
    "## System architecture {type=diagram}\n\n"
    "![System architecture](assets/diagrams/" + "a" * 64 + ".svg)\n"
)
_ILLUSTRATIVE_FIG = (
    "## Sketch {type=diagram}\n\n"
    "![Sketch (illustrative — not source-checked)](assets/diagrams/" + "b" * 64 + ".svg)\n"
)
_PLAIN = 'Just prose, [a claim]{.EXTRACTED data-fact="f0"}. No diagram here.'


@pytest.mark.parametrize("disposition", ["", "resist", "prefer"])
@pytest.mark.parametrize("body", [_PLAIN, _GROUNDED_FIG, _ILLUSTRATIVE_FIG])
def test_neutral_and_soft_members_never_gate(disposition, body):
    # NEUTRAL "" and the SOFT members resist/prefer are directive-only — the gate is a NO-OP for
    # EVERY body shape (with, without, or with an illustrative diagram).
    assert _diagram_disposition_note({"body": body}, disposition) is None


def test_require_grounded_figure_satisfies():
    assert _diagram_disposition_note({"body": _GROUNDED_FIG}, "require") is None


def test_require_illustrative_figure_does_not_satisfy_unit():
    # THE CRUX, at the unit level: an illustrative diagram does NOT satisfy `require`.
    note = _diagram_disposition_note({"body": _ILLUSTRATIVE_FIG}, "require")
    assert note is not None
    assert "illustrative" in note and "require" in note
    assert note.startswith("[diagram-disposition]")  # the internal re-ask ROUTING tag, not a code


def test_require_no_diagram_note():
    note = _diagram_disposition_note({"body": _PLAIN}, "require")
    assert note is not None and "no `{type=diagram}` section is present" in note


def test_suppress_grounded_or_illustrative_both_refuse():
    assert _diagram_disposition_note({"body": _GROUNDED_FIG}, "suppress") is not None
    assert _diagram_disposition_note({"body": _ILLUSTRATIVE_FIG}, "suppress") is not None


def test_suppress_no_diagram_is_clean():
    assert _diagram_disposition_note({"body": _PLAIN}, "suppress") is None


def test_multipart_one_grounded_part_satisfies_require_unit():
    doc = {"parts": [{"role": "slides", "body": _GROUNDED_FIG}, {"role": "notes", "body": _PLAIN}]}
    assert _diagram_disposition_note(doc, "require") is None


def test_multipart_only_illustrative_does_not_satisfy_require_unit():
    doc = {
        "parts": [
            {"role": "slides", "body": _ILLUSTRATIVE_FIG},
            {"role": "notes", "body": _PLAIN},
        ]
    }
    assert _diagram_disposition_note(doc, "require") is not None


# --- the D3 predicate: `_schema_forbids_diagram` --------------------------------------------


def test_schema_forbids_diagram_via_presence():
    assert _schema_forbids_diagram((Presence(Selector.by_type("diagram"), required=False),)) is True


def test_schema_forbids_diagram_via_count_zero():
    schema = (Count(Selector.by_type("diagram"), Cardinality(0, 0), "error"),)
    assert _schema_forbids_diagram(schema) is True


def test_schema_requiring_diagram_is_not_a_forbid():
    assert _schema_forbids_diagram((Presence(Selector.by_type("diagram"), required=True),)) is False


def test_schema_forbidding_other_type_is_not_a_diagram_forbid():
    assert _schema_forbids_diagram((Presence(Selector.by_type("figure"), required=False),)) is False


def test_empty_schema_forbids_nothing():
    assert _schema_forbids_diagram(()) is False


def test_schema_requires_diagram_via_presence():
    assert _schema_requires_diagram((Presence(Selector.by_type("diagram"), required=True),)) is True


def test_schema_requires_diagram_via_count_min_one():
    schema = (Count(Selector.by_type("diagram"), Cardinality(1, None), "error"),)
    assert _schema_requires_diagram(schema) is True


def test_schema_forbidding_diagram_is_not_a_require():
    schema = (Presence(Selector.by_type("diagram"), required=False),)
    assert _schema_requires_diagram(schema) is False


def test_schema_merely_allowing_a_diagram_is_not_a_require():
    # A `?`/`*`-style Count (min 0) merely ALLOWS a diagram — it must NOT trip the mandate predicate
    # (else D3 would refuse a perfectly satisfiable `suppress`).
    schema = (Count(Selector.by_type("diagram"), Cardinality(0, 1), "error"),)
    assert _schema_requires_diagram(schema) is False


def test_schema_requiring_other_type_is_not_a_diagram_require():
    assert _schema_requires_diagram((Presence(Selector.by_type("figure"), required=True),)) is False


def test_empty_schema_requires_nothing():
    assert _schema_requires_diagram(()) is False


# --- end-to-end through compose_artifact ----------------------------------------------------


def test_require_with_illustrative_refuses_section_conformance(store, claims):
    # THE CRUX, end-to-end: a `require` artifact whose ONLY diagram is `posture: illustrative` is
    # REFUSED — an illustrative sketch is not source-checked, so it never satisfies `require`. It
    # re-asks to the bound, then BLOCKS with the REUSED `section-conformance-violation`, never
    # persisted.
    _requires_pandoc()  # the rewritten illustrative `![…]` figure parses through the A-gate reader
    request = make_request(diagram_disposition="require")
    runner = ScriptedRunner([writer_ok({"body": ILLUSTRATIVE_DIAGRAM})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner, max_attempts=3)
    assert outcome.status == "error"
    assert outcome.code == CODE_SECTION_CONFORMANCE_VIOLATION == "section-conformance-violation"
    assert outcome.ir is None
    assert outcome.attempts == 3 and runner.calls == 3  # re-asked (attempts > 1) then blocked
    assert not store.output_path(request.artifact_id).exists()
    assert all("illustrative" in v and "require" in v for v in outcome.violations)


def test_require_with_no_diagram_refuses(store, claims):
    # A `require` artifact with no diagram at all re-asks then BLOCKS (no dot/pandoc — the plain
    # body never compiles a diagram nor trips the A-gate). The relax escape (`require`->`prefer`)
    # surfaces on the re-ask.
    request = make_request(diagram_disposition="require")
    runner = ScriptedRunner([writer_ok({"body": PROSE_CLAIM})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner, max_attempts=3)
    assert outcome.status == "error"
    assert outcome.code == "section-conformance-violation"
    assert outcome.ir is None
    assert outcome.attempts == 3 and runner.calls == 3
    assert not store.output_path(request.artifact_id).exists()
    assert all("no `{type=diagram}` section is present" in v for v in outcome.violations)
    reask = runner.requests[1].stdin_text
    assert "diagram_disposition" in reask  # the disposition note fired, NOT heading-skeleton
    assert "`require`->`prefer`" in reask  # the budget-exhaustion relax escape surfaced


@requires_dot  # real `dot` compile of the grounded diagram; a tool-less host degrades to text-alt
def test_require_with_grounded_proceeds(store, claims):
    # A `require` artifact carrying a GROUNDED diagram passes the gate first try and ships.
    _requires_pandoc()
    request = make_request(diagram_disposition="require")
    runner = ScriptedRunner([writer_ok({"body": GROUNDED_DIAGRAM})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
    assert (outcome.status, outcome.code, outcome.attempts) == ("ok", "ok", 1)
    persisted = json.loads(store.output_path(request.artifact_id).read_bytes())["body"]
    assert DIAGRAM_FIGURE_RE.search(persisted)  # the grounded diagram is a contained figure
    assert "illustrative" not in persisted  # and carries NO warning


def test_suppress_reasks_then_blocks_no_dropped_fact(store, claims):
    # A `suppress` artifact carrying a diagram (here grounded, alongside a grounded prose claim)
    # re-asks then BLOCKS. "No dropped fact": the re-ask note tells the writer to KEEP every
    # grounded fact — drop the diagram, never the facts.
    _requires_pandoc()
    request = make_request(diagram_disposition="suppress")
    body = PROSE_CLAIM + "\n\n" + GROUNDED_DIAGRAM
    runner = ScriptedRunner([writer_ok({"body": body})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner, max_attempts=3)
    assert outcome.status == "error"
    assert outcome.code == "section-conformance-violation"
    assert outcome.ir is None
    assert outcome.attempts == 3 and runner.calls == 3
    assert not store.output_path(request.artifact_id).exists()
    assert all("suppress" in v.lower() for v in outcome.violations)
    reask = runner.requests[1].stdin_text
    assert "KEEP every grounded fact" in reask  # facts are preserved, only the diagram is dropped
    assert "`suppress`->`resist`" in reask  # the relax escape surfaced


@requires_dot  # real `dot` compile of the grounded diagram part (degrades to text-alt when absent)
def test_multipart_require_satisfied_by_one_grounded_part(store, claims):
    # For a multi-part artifact, ONE grounded diagram part satisfies `require`.
    _requires_pandoc()
    request = make_request(format_parts=("slides", "notes"), diagram_disposition="require")
    runner = ScriptedRunner(
        [writer_ok({"parts": {"slides": GROUNDED_DIAGRAM, "notes": "Speaker notes, prose."}})]
    )
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
    assert (outcome.status, outcome.code, outcome.attempts) == ("ok", "ok", 1)
    persisted = json.loads(store.output_path(request.artifact_id).read_bytes())
    slides = next(p["body"] for p in persisted["parts"] if p["role"] == "slides")
    assert DIAGRAM_FIGURE_RE.search(slides)  # the one grounded diagram part satisfied require


def test_section_schema_forbids_vs_require_refuses_pre_writer_zero_spend(store, claims):
    # D3: a contradictory Format — a `section_schema` that FORBIDS `{type=diagram}` while
    # `diagram_disposition` is `require` — is an unwinnable re-ask. Refuse LOUDLY before any writer
    # call: the NeverRunner is never invoked (ZERO spend).
    md = "# Paper\n\n- intro\n"
    preimage = build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("academic-paper"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
        outline_digest=outline_digest(md),  # outline-shaped → the base gate (and D3) are ACTIVE
    )
    forbid_diagram = [{"rule": "presence", "axis": "type", "value": "diagram", "required": False}]
    request = ComposeRequest(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        format_parts=(),
        effective_values={"format": {"section_schema": forbid_diagram}},
        grounded_facts=(make_fact(),),
        source_repos={"acme-graph": "github.com/acme/widget"},
        diagram_disposition="require",
    )
    runner = NeverRunner()
    with pytest.raises(ComposeError) as exc:
        compose_artifact(request, store=store, claims=claims, runner=runner)
    assert "contradiction" in str(exc.value).lower()
    assert runner.calls == 0  # refused PRE-writer — never spent a token
    assert not store.output_path(request.artifact_id).exists()


def test_section_schema_requires_vs_suppress_refuses_pre_writer_zero_spend(store, claims):
    # D3, the MIRROR: a `section_schema` that REQUIRES `{type=diagram}` while `diagram_disposition`
    # is `suppress` is the symmetric unwinnable contradiction (base gate mandates a diagram, the
    # disposition gate forbids one). Refuse LOUDLY before any writer call — ZERO spend — rather than
    # burning the whole re-ask budget.
    md = "# Paper\n\n- intro\n"
    preimage = build_artifact_preimage(
        topic=EntryBinding("topic-x"),
        persona=EntryBinding("hiring-manager"),
        format=EntryBinding("academic-paper"),
        voice=EntryBinding("business"),
        goals=[EntryBinding("explain")],
        source_subset=["acme-graph"],
        source_commit={"acme-graph": COMMIT_SHA},
        outline_digest=outline_digest(md),  # outline-shaped → the base gate (and D3) are ACTIVE
    )
    require_diagram = [{"rule": "presence", "axis": "type", "value": "diagram", "required": True}]
    request = ComposeRequest(
        artifact_id=mint_artifact_id(preimage),
        preimage=preimage,
        format_parts=(),
        effective_values={"format": {"section_schema": require_diagram}},
        grounded_facts=(make_fact(),),
        source_repos={"acme-graph": "github.com/acme/widget"},
        diagram_disposition="suppress",
    )
    runner = NeverRunner()
    with pytest.raises(ComposeError) as exc:
        compose_artifact(request, store=store, claims=claims, runner=runner)
    assert "contradiction" in str(exc.value).lower()
    assert runner.calls == 0  # refused PRE-writer — never spent a token
    assert not store.output_path(request.artifact_id).exists()


# --- neutral/soft do not disturb the compose path (identity + no false gate) -----------------


def test_neutral_disposition_composes_byte_identical(store, claims):
    # A neutral ("") disposition leaves the compose path byte-identical to the pre-C4b golden: the
    # gate is a pure NO-OP (no diagram forced, none forbidden, nothing added to the IR).
    request = make_request(diagram_disposition="")
    content = {"body": 'A [claim]{.EXTRACTED data-fact="f0"}.'}
    outcome = compose_artifact(
        request, store=store, claims=claims, runner=ScriptedRunner([writer_ok(content)])
    )
    assert outcome.status == "ok"
    persisted = store.output_path(request.artifact_id).read_bytes()
    ledger, _ = build_grounding_ledger(
        request.grounded_facts, source_repos=request.source_repos
    )
    expected = build_ir(
        artifact_id=request.artifact_id,
        preimage=request.preimage,
        grounding=ledger,
        body=content["body"],
    )
    assert persisted == canonical_json_bytes(expected)  # byte-for-byte the pre-C4b golden


def test_prefer_without_a_diagram_still_ships(store, claims):
    # `prefer` is a NUDGE, not a gate — an artifact with no diagram still ships (no re-ask/block).
    request = make_request(diagram_disposition="prefer")
    runner = ScriptedRunner([writer_ok({"body": PROSE_CLAIM})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
    assert (outcome.status, outcome.attempts) == ("ok", 1)


def test_resist_with_a_diagram_still_ships(store, claims):
    # `resist` is a NUDGE, not a gate — an artifact that DOES carry a diagram still ships.
    _requires_pandoc()
    request = make_request(diagram_disposition="resist")
    runner = ScriptedRunner([writer_ok({"body": GROUNDED_DIAGRAM})])
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
    assert outcome.status == "ok"


def test_require_recovers_within_the_bound(store, claims):
    # attempt-1 ships no diagram (require unsatisfied) → the DISPOSITION-specific re-ask note fires;
    # attempt-2 ships a grounded diagram → composes. Proves the re-ask routes to the diagram note
    # (NOT the base heading-skeleton note) even though both reuse `section-conformance-violation`.
    _requires_pandoc()
    request = make_request(diagram_disposition="require")
    runner = ScriptedRunner(
        [writer_ok({"body": PROSE_CLAIM}), writer_ok({"body": GROUNDED_DIAGRAM})]
    )
    outcome = compose_artifact(request, store=store, claims=claims, runner=runner)
    assert (outcome.status, outcome.attempts) == ("ok", 2)
    assert len(outcome.violations) == 1 and "diagram" in outcome.violations[0].lower()
    reask = runner.requests[1].stdin_text
    assert "VIOLATED the Format's diagram_disposition" in reask  # disposition note, not skeleton
    # the base heading-skeleton re-ask note (its unique opener) did NOT fire
    assert "VIOLATED the Format's base section contract" not in reask
