"""Mixed-media increment C — Commit C5: the `diagram-styles/` referenced registry + the `tool` knob.

Covers the plan's C5 verification (planner-C-final.md §C5) and the amendment's honesty model
(architect-amendment-reconciliation.md §2.D/§2.F/§2.K):

* the registry LOADS (schema + the shipped framework `default` style) and a new style is a
  ONE-FILE add (the matrix promise, §5.4);
* the `tool` knob resolves: `dot` (pinned default) / `d2` (selectable) / `auto` (opt-in probe);
* `auto` is honored ONLY as an explicit opt-in — never the framework default;
* the low-level `_select_diagram_tool` resolver stays LOUD (`auto` with none installed →
  `DiagramToolUnavailableError`); the compose transform CALL SITE catches tool-ABSENCE and
  GRACEFULLY DEGRADES the section to its text-alt (a recorded warning) — the ratified reversal of
  §17 PA-12 for the tool-ABSENCE case ONLY (a malformed source with the tool present stays hard);
* END-TO-END through the compose transform: the default draws with `dot`; a `d2`-selecting style
  draws with `d2` (byte-differs → new content hash); an `auto` style is honored;
* the `diagram-styles/` root is COVERED by the public-boundary guard (a stray client-content style
  file is caught) and by schema-lint (add-root coverage, GAP-4a);
* the recipe→registry ref wiring is REAL (loud on an unknown id), not inert.

Real `dot`/`d2` (pinned CI deps, per PART 6); no LLM, no network.
"""

from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pipeline import compose, diagram
from pipeline.canonical import sha256_hex
from pipeline.compose import ComposeRequest
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.m1 import (
    REF_ATTRIBUTE_TARGETS,
    TEXT_REF_ATTRIBUTE_TARGETS,
    DanglingRefError,
    Resolver,
)
from pipeline.schema import SCHEMA_FILENAME, load_schema
from pipeline.store import WorkspaceStore

REPO_ROOT = Path(__file__).resolve().parents[1]
DIAGRAM_STYLES = registry_dir(REPO_ROOT, "diagram-styles")
GUARD = REPO_ROOT / "scripts" / "check-no-content.sh"

# Diagram GENERATION shells to the real `dot`/`d2`; both are OPTIONAL (a tool-less host degrades to
# the text-alt), so a test requiring them SKIPS when absent rather than failing CI (the ratified
# "works without graphviz" contract). The degradation tests below simulate absence and run anyway.
# The skip markers are the SINGLE canonical copy in `tests/conftest.py`.
from conftest import requires_d2, requires_dot  # noqa: E402

#: A well-formed GROUNDED diagram flat body citing the single EXTRACTED fact `f1`.
DIAGRAM_BODY = (
    "## System architecture {type=diagram}\n\n"
    "nodes:\n- gw: Gateway\n- auth: Auth\n"
    'edges:\n- gw -> auth [routes]{.EXTRACTED data-fact="f1"}\n'
)
LEDGER = {"f1": {"tier": "EXTRACTED"}}
FIGURE_RE = re.compile(r"assets/diagrams/([0-9a-f]{64})\.svg")


def _transform(body: str, store: WorkspaceStore, tool: str) -> str:
    """Run the C5-wired diagram transform for `tool`, returning the rewritten flat body."""
    return compose._apply_diagram_transform({"body": body}, LEDGER, store, tool)["body"]


def _stored_svg(store: WorkspaceStore, rewritten_body: str) -> bytes:
    """The SVG bytes the transform minted + stored, read back by the body's content-hash ref."""
    match = FIGURE_RE.search(rewritten_body)
    assert match, f"no contained figure in rewritten body: {rewritten_body!r}"
    return (store.root / "assets" / "diagrams" / f"{match.group(1)}.svg").read_bytes()


def _run_guard(root: Path, mode: str = "all") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD), "--root", str(root), "--mode", mode],
        capture_output=True,
        text=True,
        check=False,
    )


# --------------------------------------------------------------------------- #
# The registry: schema + the shipped framework default + one-file-add.        #
# --------------------------------------------------------------------------- #


def test_schema_declares_tool_enum_default_dot():
    schema = load_schema(DIAGRAM_STYLES / SCHEMA_FILENAME)
    assert schema.collection == "diagram-styles"
    assert schema.schema_version == 1
    assert set(schema.attributes) == {"tool"}
    tool = schema.attributes["tool"]
    assert tool.type.kind == "enum"
    assert set(tool.type.values) == {"dot", "d2", "auto"}
    assert tool.default == "dot"  # the pinned, byte-deterministic default (amendment §2.D)


def test_default_style_loads_and_pins_dot():
    entry = Resolver(REPO_ROOT).resolve("diagram-styles", "default")
    assert entry.effective["tool"] == diagram.TOOL_DOT == "dot"


def test_default_style_is_framework_provenance():
    # The shipped style is the public deliverable — `provenance: framework` (CLAUDE.md rule 4).
    text = (DIAGRAM_STYLES / "default.md").read_text(encoding="utf-8")
    assert re.search(r"^provenance:[ \t]*framework[ \t]*$", text, re.MULTILINE)


def test_adding_a_style_is_one_file(tmp_path: Path):
    # The matrix promise (§5.4): a new diagram-style — e.g. a `d2`-selecting one — is ONE conforming
    # file, immediately selectable via the standard resolver, with zero second edits.
    shutil.copytree(DIAGRAM_STYLES, registry_dir(tmp_path, "diagram-styles"))
    before = {p.name for p in (registry_dir(tmp_path, "diagram-styles")).iterdir()}
    (registry_dir(tmp_path, "diagram-styles") / "grouped.md").write_text(
        "---\nid: grouped\nprovenance: framework\nschema_version: 1\ntool: d2\n---\n"
        "# grouped — a d2-drawn style (test fixture)\n",
        encoding="utf-8",
    )
    after = {p.name for p in (registry_dir(tmp_path, "diagram-styles")).iterdir()}
    assert after - before == {"grouped.md"}  # exactly ONE new file
    entry = Resolver(tmp_path).resolve("diagram-styles", "grouped")
    assert entry.effective["tool"] == "d2"  # selectable, validated, immediately


def test_envelope_only_style_rides_the_dot_floor(tmp_path: Path):
    # §5.4 L0: an attribute-free style (no `tool:`) rides the schema floor — honest `dot`.
    shutil.copytree(DIAGRAM_STYLES, registry_dir(tmp_path, "diagram-styles"))
    (registry_dir(tmp_path, "diagram-styles") / "bare.md").write_text(
        "---\nid: bare\nprovenance: framework\nschema_version: 1\n---\n# bare style\n",
        encoding="utf-8",
    )
    entry = Resolver(tmp_path).resolve("diagram-styles", "bare")
    assert entry.effective.get("tool", diagram.TOOL_DOT) == "dot"


# --------------------------------------------------------------------------- #
# The `tool` knob resolver: dot / d2 pass through; auto is an opt-in probe.    #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tool", [diagram.TOOL_DOT, diagram.TOOL_D2])
def test_select_tool_concrete_passthrough(tool):
    assert compose._select_diagram_tool(tool) == tool


def test_select_tool_auto_prefers_dot_when_both_installed():
    # `auto` is deterministic WITHIN an environment: the pinned default (`dot`) wins when present.
    assert compose._select_diagram_tool("auto", installed=lambda _t: True) == "dot"


def test_select_tool_auto_picks_the_only_installed():
    only_d2 = {"dot": False, "d2": True}
    assert compose._select_diagram_tool("auto", installed=only_d2.__getitem__) == "d2"


def test_select_tool_auto_none_installed_is_loud():
    with pytest.raises(diagram.DiagramToolUnavailableError) as exc:
        compose._select_diagram_tool("auto", installed=lambda _t: False)
    assert exc.value.code == "diagram-tool-unavailable"  # LOUD install signal, never a no-op


def test_select_tool_unknown_is_loud():
    with pytest.raises(diagram.DiagramCompileError):
        compose._select_diagram_tool("mermaid")  # outside the enum — fail-closed backstop


def test_tool_installed_probe_uses_path_reflects_which():
    # The presence probe is exactly `shutil.which` — robust in ANY environment (present OR absent).
    assert compose._diagram_tool_installed("dot") is (shutil.which("dot") is not None)
    assert compose._diagram_tool_installed("d2") is (shutil.which("d2") is not None)


@requires_dot
def test_tool_installed_probe_true_when_dot_present():
    # When `dot` IS on PATH the probe reports True (skipped on a tool-less host — dot is optional).
    assert compose._diagram_tool_installed("dot") is True


# --------------------------------------------------------------------------- #
# `auto` is NEVER the default — it fires ONLY as an explicit opt-in.          #
# --------------------------------------------------------------------------- #


def test_framework_default_style_is_not_auto():
    # The shipped `default` style pins `dot`, so a zero-touch author never triggers the
    # env-dependent `auto` probe (amendment §2.D: identity is machine-independent by default).
    assert Resolver(REPO_ROOT).resolve("diagram-styles", "default").effective["tool"] != "auto"


def test_compose_request_diagram_tool_defaults_to_dot():
    field = {f.name: f for f in dataclasses.fields(ComposeRequest)}["diagram_tool"]
    assert field.default == diagram.TOOL_DOT == "dot"  # every pre-C5 caller is byte-identical


# --------------------------------------------------------------------------- #
# END-TO-END through the compose transform (the task's headline verification). #
# --------------------------------------------------------------------------- #


@requires_dot
def test_default_no_ref_compiles_via_dot(tmp_path: Path):
    store = WorkspaceStore(tmp_path / "ws")
    svg = _stored_svg(store, _transform(DIAGRAM_BODY, store, diagram.TOOL_DOT))
    assert b"graphviz" in svg and b"d2-version" not in svg  # drawn by dot


@requires_dot
@requires_d2
def test_d2_selecting_style_compiles_via_d2_and_byte_differs(tmp_path: Path):
    dot_store = WorkspaceStore(tmp_path / "dot")
    d2_store = WorkspaceStore(tmp_path / "d2")
    dot_svg = _stored_svg(dot_store, _transform(DIAGRAM_BODY, dot_store, diagram.TOOL_DOT))
    d2_svg = _stored_svg(d2_store, _transform(DIAGRAM_BODY, d2_store, diagram.TOOL_D2))
    assert b"d2-version" in d2_svg and b"graphviz" not in d2_svg  # drawn by d2
    # A tool swap changes the SVG bytes → a new content hash (= new render identity), the design's
    # intent. MINOR-4: assert the HASHES differ, never a frozen golden.
    assert sha256_hex(d2_svg) != sha256_hex(dot_svg)


@requires_dot
def test_auto_style_is_honored_end_to_end(tmp_path: Path, monkeypatch):
    # An explicit `auto` style compiles (both tools installed → the deterministic `dot` preference);
    # the transform's lazy `auto` resolution happens only because a diagram section is present.
    store = WorkspaceStore(tmp_path / "ws")
    svg = _stored_svg(store, _transform(DIAGRAM_BODY, store, "auto"))
    assert b"graphviz" in svg  # auto → dot (preferred when both present)


def test_diagram_free_body_never_probes_tools(tmp_path: Path, monkeypatch):
    # A diagram-FREE body under an `auto` style is byte-identical and fires ZERO tool probes: the
    # transform returns the raw body unchanged before any tool resolution. A probe here would be a
    # spurious failure for a run that draws no diagram.
    monkeypatch.setattr(
        compose, "_diagram_tool_installed", lambda _t: pytest.fail("probed with no diagram")
    )
    store = WorkspaceStore(tmp_path / "ws")
    prose = "## Overview\n\nJust prose, no diagram here.\n"
    assert _transform(prose, store, "auto") == prose


def test_missing_selected_tool_degrades_to_text_alt(tmp_path: Path, monkeypatch, caplog):
    # RATIFIED REVERSAL of PA-12 for the tool-ABSENCE case: a chosen-but-missing tool at compile
    # time GRACEFULLY DEGRADES — the diagram is SKIPPED, its text-alt substituted, a VISIBLE warning
    # emitted AND recorded (never silent, never a half-diagram, never a hard crash). Simulates
    # absence by pointing `d2` at a bogus path, so it runs REGARDLESS of what is installed — this
    # is the CI-visible "works without a diagram tool" proof for the compose transform.
    monkeypatch.setitem(diagram._TOOL_BINARY, diagram.TOOL_D2, "no-such-d2-binary-xyz")
    store = WorkspaceStore(tmp_path / "ws")
    degraded: list[str] = []
    with caplog.at_level("WARNING", logger="pipeline.compose"):
        body = compose._apply_diagram_transform(
            {"body": DIAGRAM_BODY}, LEDGER, store, diagram.TOOL_D2, degraded=degraded
        )["body"]
    # NO SVG was compiled or stored — the pipeline generated nothing that requires the tool.
    assert not FIGURE_RE.search(body)
    assert not (store.root / "assets" / "diagrams").exists()
    # The reader still gets a readable text-alt (the heading is kept; the body is fallback prose).
    assert "System architecture" in body
    assert "Diagram unavailable" in body
    # The skip is RECORDED (traceable) AND logged — never silent.
    assert degraded and "diagram-tool-unavailable" in degraded[0]
    assert any("diagram skipped" in r.message for r in caplog.records)


def test_missing_tool_still_refuses_an_ungrounded_diagram(tmp_path: Path, monkeypatch):
    # The HARD grounding gate is UNAFFECTED by degradation: an UNGROUNDED diagram is REFUSED even
    # when the tool is absent (the gate runs BEFORE compile). We never emit an ungrounded picture —
    # degraded or not. The edge cites nothing, so `gate_diagram` raises before the tool-absence.
    monkeypatch.setitem(diagram._TOOL_BINARY, diagram.TOOL_D2, "no-such-d2-binary-xyz")
    ungrounded = (
        "## Architecture {type=diagram}\n\n"
        "nodes:\n- gw: Gateway\n- auth: Auth\n"
        "edges:\n- gw -> auth\n"  # no citation → ungrounded → HARD refusal (tool absence unreached)
    )
    store = WorkspaceStore(tmp_path / "ws")
    with pytest.raises(diagram.DiagramGroundingError):
        compose._apply_diagram_transform({"body": ungrounded}, LEDGER, store, diagram.TOOL_D2)


# --------------------------------------------------------------------------- #
# Loader wiring: the recipe→registry ref is REAL (loud on unknown), not inert. #
# --------------------------------------------------------------------------- #


def test_ref_attribute_row_wires_recipe_to_diagram_styles():
    # O2: the ratified `(collection, attribute) -> diagram-styles` row. It rides the TEXT table
    # (empty "" floor, mirroring `("recipes","topic"):"topics"`) so the add is additive-at-floor and
    # needs no global schema_version bump; it is NOT in the ref table.
    assert TEXT_REF_ATTRIBUTE_TARGETS[("recipes", "diagram_style")] == "diagram-styles"
    assert ("recipes", "diagram_style") not in REF_ATTRIBUTE_TARGETS


def test_real_recipe_leaves_diagram_style_at_the_empty_floor():
    # A shipped recipe selects no style → the "" floor → the driver falls back to the framework
    # `default` style (pinned dot). Zero identity churn (an empty floor is omitted from deltas).
    recipe = Resolver(REPO_ROOT).resolve("recipes", "explainer-post")
    assert recipe.effective.get("diagram_style", "") == ""


def _recipe_scan_tree(tmp_path: Path, diagram_style: str) -> Path:
    root = tmp_path / f"tree-{diagram_style}"
    dstyles = registry_dir(root, "diagram-styles")
    dstyles.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DIAGRAM_STYLES, dstyles)
    (dstyles / "grouped.md").write_text(
        "---\nid: grouped\nprovenance: framework\nschema_version: 1\ntool: d2\n---\n# grouped\n",
        encoding="utf-8",
    )
    recipes_dir = registry_dir(root, "recipes")
    recipes_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        registry_dir(REPO_ROOT, "recipes") / SCHEMA_FILENAME, recipes_dir / SCHEMA_FILENAME
    )
    (recipes_dir / "r-test.md").write_text(
        "---\nid: r-test\nprovenance: framework\nschema_version: 1\n"
        f"diagram_style: {diagram_style}\n---\n# r-test recipe\n",
        encoding="utf-8",
    )
    return root


def test_recipe_binding_a_known_style_resolves(tmp_path: Path):
    root = _recipe_scan_tree(tmp_path, "grouped")
    recipe = Resolver(root).resolve("recipes", "r-test")
    assert recipe.effective["diagram_style"] == "grouped"  # the ref validated at M1


def test_recipe_binding_an_unknown_style_is_loud(tmp_path: Path):
    # §11.1 loud resolution: an unknown diagram-style id fails at M1 (a DanglingRefError naming the
    # referrer), never a silent skip — proof the ref row is REAL, not inert.
    root = _recipe_scan_tree(tmp_path, "no-such-style")
    with pytest.raises(DanglingRefError):
        Resolver(root).resolve("recipes", "r-test")


# --------------------------------------------------------------------------- #
# Add-root coverage: the guard + schema-lint SCAN the new registry root.       #
# --------------------------------------------------------------------------- #


def test_schema_lint_covers_diagram_styles_root():
    assert "diagram-styles" in REGISTRY_ROOTS  # iter_lint_collections walks it (SV11 coverage)


def test_guard_scans_diagram_styles_stray_client_content_is_caught(tmp_path: Path):
    # The whitelist entry brings `diagram-styles/` INTO the content scan (not merely the GAP-4a
    # structural check): a planted instance-namespaced `x-*` style is caught by PATH, and the
    # unknown-registry-root check must NOT fire for the now-whitelisted root.
    root = tmp_path / "scanned"
    (root / "diagram-styles").mkdir(parents=True)
    (root / "diagram-styles" / SCHEMA_FILENAME).write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "diagram-styles" / "x-acme-house.md").write_text(
        "# synthetic client diagram style — never real\n", encoding="utf-8"
    )
    proc = _run_guard(root)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[x-file] diagram-styles/x-acme-house.md" in proc.stdout
    assert "unknown-registry-root" not in proc.stdout


def test_guard_diagram_styles_missing_provenance_is_default_denied(tmp_path: Path):
    root = tmp_path / "deny"
    (root / "diagram-styles").mkdir(parents=True)
    (root / "diagram-styles" / SCHEMA_FILENAME).write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "diagram-styles" / "house.md").write_text(
        "# a style with no provenance line\n", encoding="utf-8"
    )
    proc = _run_guard(root)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "LEAK[missing-provenance] diagram-styles/house.md" in proc.stdout


def test_guard_diagram_styles_framework_entry_passes(tmp_path: Path):
    # The shipped shape (a co-located schema + a `provenance: framework` entry) stays green.
    root = tmp_path / "ok"
    (root / "diagram-styles").mkdir(parents=True)
    (root / "diagram-styles" / SCHEMA_FILENAME).write_text(
        "schema_version: 1\nattributes: {}\n", encoding="utf-8"
    )
    (root / "diagram-styles" / "default.md").write_text(
        "---\nprovenance: framework\n---\n# a framework style\n", encoding="utf-8"
    )
    proc = _run_guard(root)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "LEAK[" not in proc.stdout
