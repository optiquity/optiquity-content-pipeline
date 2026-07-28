"""The asset-reference containment guard — the security core (increment A, commit A3).

These tests pin `pipeline.asset_ref`, the pure resolve-and-contain guard the compose gate (A4)
calls at COMPOSE, pre-persist, to enforce CLAUDE.md rule 2 (client isolation) on every body
image reference. The guarantee under test: a reference that points — or tries to point, however
disguised — OUTSIDE the client's own `assets/` root is REFUSED as `uncontained`, and security
does NOT depend on whether the referenced file happens to exist. A merely empty or dangling
reference is the DISTINCT, honest `invalid` outcome (a benign broken link, never dressed up as
a cross-client breach).

Every REFUSE vector the plan enumerates is exercised here (percent-encoding, backslash,
absolute, `..` segments that normalize both out AND back in, bare/unprefixed names, and a real
symlink escape a string check cannot see), plus the two PASS cases and the AST-walk behaviour.
All fixtures are generic (`assets/x.png`, a tmp workspace); no instance/client content.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from pipeline.asset_ref import (
    AssetRefError,
    assert_asset_refs_contained,
    has_raw_markup,
    iter_image_targets,
)
from pipeline.serialize import is_ci, pandoc_available, pandoc_gate, parse_to_ast

_PANDOC_AVAILABLE = pandoc_available()


def _requires_pandoc() -> None:
    """The AST-walk behaviour tests parse REAL Markdown through the pinned reader, so they need
    pandoc. Absent + CI ⇒ fail loudly; absent locally ⇒ skip; present ⇒ run (PA-12). The
    security core (`assert_asset_refs_contained`) is a pure path check and needs NO pandoc."""
    decision = pandoc_gate(available=_PANDOC_AVAILABLE, ci=is_ci())
    if decision == "fail":
        pytest.fail(
            "pandoc absent under CI=true — the asset-ref AST-walk proof MUST run in CI (PA-12)",
            pytrace=False,
        )
    if decision == "skip":
        pytest.skip("pandoc not installed; the asset-ref AST-walk behaviour needs the reader")


# A real sha256 hex, to mirror a machine-written nested asset `assets/diagrams/<hash>.svg`.
_HASH = hashlib.sha256(b"<svg/>").hexdigest()


@pytest.fixture
def ws(tmp_path):
    """A workspace store root with an `assets/` tree holding the two PASS fixtures — a top-level
    image and a NESTED, content-addressed diagram. The guard resolves body refs against this
    root (the S5 base contract: containment base == render resource-path base == store.root)."""
    assets = tmp_path / "assets"
    (assets / "diagrams").mkdir(parents=True)
    (assets / "throughput.png").write_bytes(b"\x89PNG fixture")
    (assets / "diagrams" / f"{_HASH}.svg").write_bytes(b"<svg/>")
    return tmp_path


def _refuse(target: str, kind: str, workspace_root) -> AssetRefError:
    """Assert the single `target` is refused with the expected honest `kind`, and return the
    error so a caller can pin its detail. A one-target list exercises the same loop A4 calls."""
    with pytest.raises(AssetRefError) as exc:
        assert_asset_refs_contained([target], workspace_root=workspace_root)
    assert exc.value.kind == kind, f"{target!r} should be {kind!r}, got {exc.value.kind!r}"
    assert exc.value.target == target
    return exc.value


# ---------------------------------------------------------------------------
# REFUSE → uncontained (a client-isolation escape; CLAUDE.md rule 2 / §10).
# ---------------------------------------------------------------------------

#: Every escape vector, each tagged with the ordered step that catches it. The value never
#: reaches the filesystem for steps 2-7 — the shape allowlist runs BEFORE resolve, so containment
#: holds independent of the existence check (S1). First block: the plan's mandated vectors.
#: Second block: the NUL/control totality vector (BLOCKER 1) plus defense-in-depth coverage —
#: each is ALREADY refused, pinned here so a future reorder of the ordered checks cannot silently
#: reopen any of them.
UNCONTAINED_VECTORS = {
    "cross_client_rule2": "../../workspaces/other/secret.png",  # MANDATORY — step 6 (`..`)
    "parent_traversal": "../secret.png",  # step 6 (`..`)
    "absolute": "/etc/passwd",  # step 5 (leading `/`)
    "bare_name_no_prefix": "secret.png",  # step 7 (no `assets/` prefix)
    "percent_encoding_prefixed": "assets/%2e%2e/%2e%2e/secret.png",  # step 3 (`%`) — the S1 hole
    "percent_encoding_bare": "%2e%2e/secret.png",  # step 3 (`%`)
    "backslash": "assets\\..\\secret.png",  # step 4 (backslash)
    "dotdot_normalizes_out": "assets/../secret.png",  # step 6 (`..`, exits)
    "dotdot_normalizes_back_in": "assets/../assets/x.png",  # step 6 (`..`, DELIBERATELY refused)
    "dot_slash_prefix": "./assets/x.png",  # step 7 (no literal `assets/` prefix, DELIBERATE)
    # NUL / control char — step 2; would otherwise raise a bare ValueError at resolve() (BLOCKER 1).
    "embedded_nul": "assets/x\x00.png",  # step 2 (control character)
    # defense-in-depth: already refused, pinned so a check-reorder cannot silently reopen them.
    "case_sensitive_prefix": "ASSETS/x.png",  # step 7 (the `assets/` prefix is case-sensitive)
    "encoded_slash": "%2f",  # step 3 (`%` — an encoded slash)
    "drive_backslash": "C:\\x.png",  # step 4 (backslash — a Windows drive path)
    "bare_assets_no_slash": "assets",  # step 7 (bare `assets`, not the `assets/` prefix)
    "double_slash_dotdot": "assets//../secret.png",  # step 6 (`..` segment past an empty segment)
    "unicode_lookalike": "аssets/x.png",  # step 7 (Cyrillic 'а' U+0430, not ASCII `assets/`)
}


@pytest.mark.parametrize(
    "target", list(UNCONTAINED_VECTORS.values()), ids=list(UNCONTAINED_VECTORS)
)
def test_uncontained_vectors_are_refused(ws, target):
    _refuse(target, "uncontained", ws)


def test_uncontained_holds_without_the_assets_dir(tmp_path):
    # The shape allowlist (steps 2-6) never touches the filesystem, so an escape is refused even
    # with NO assets/ dir present — proving security is not backed by the existence check (S1).
    assert not (tmp_path / "assets").exists()
    for target in UNCONTAINED_VECTORS.values():
        _refuse(target, "uncontained", tmp_path)


def test_symlink_escape_is_caught_by_resolve_and_contain(ws, tmp_path):
    # `assets/evil` is a shape-clean segment whose dir is a symlink pointing OUTSIDE the asset
    # root. Only the PRIMARY resolve-and-contain step (7, resolving BOTH sides) catches it —
    # proving the resolve, not a lexical check, is the real protection at depth.
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, ws / "assets" / "evil")
    err = _refuse("assets/evil/x.png", "uncontained", ws)
    assert "resolves outside" in err.detail


def test_embedded_nul_refuses_as_assetreferror_not_raw_valueerror(ws):
    # BLOCKER 1: a NUL passes the %/backslash/leading-'/'/'..' shape checks and, absent the
    # step-2 control guard, reaches `Path(...).resolve()` — which raises a BARE `ValueError`
    # ("embedded null byte"). A4's `except AssetRefError` would MISS that and the compose gate
    # would CRASH. The guard must instead refuse it as a clean, recoverable AssetRefError.
    err = _refuse("assets/x\x00.png", "uncontained", ws)
    assert "control character" in err.detail
    assert not isinstance(err, ValueError)  # AssetRefError is NOT a ValueError subclass


def test_control_chars_across_the_range_refuse_as_uncontained(ws):
    # The whole ASCII control range (0x00-0x1f, 0x7f) is refused BEFORE any resolve, so no
    # surprising byte can reach pathlib and throw a non-AssetRefError (totality guarantee).
    for code in (0x00, 0x09, 0x0A, 0x0D, 0x1F, 0x7F):
        _refuse(f"assets/x{chr(code)}.png", "uncontained", ws)


def test_nul_reaches_the_guard_through_pandoc_and_stays_assetreferror(ws):
    # BLOCKER 2, reachability leg: pandoc carries a NUL straight from a Markdown image URL into
    # the AST, so the full A4 path (parse -> iter_image_targets -> assert_asset_refs_contained)
    # must raise AssetRefError, NEVER a bare ValueError — proven on real pinned-reader input.
    _requires_pandoc()
    ast = parse_to_ast("![a](assets/x\x00.png)")
    targets = iter_image_targets(ast)
    assert any("\x00" in t for t in targets)  # the NUL really survives the parse
    with pytest.raises(AssetRefError) as exc:
        assert_asset_refs_contained(targets, workspace_root=ws)
    assert exc.value.kind == "uncontained"


# ---------------------------------------------------------------------------
# REFUSE → invalid (a benign broken reference — NOT an isolation escape).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["", ".", "   "], ids=["empty", "dot", "whitespace"])
def test_empty_dot_whitespace_is_invalid(ws, target):
    _refuse(target, "invalid", ws)


def test_contained_but_missing_file_is_invalid(ws):
    # Shape-clean AND contained, but no such file → an honest broken-image link (step 8),
    # reported as `invalid`, never as a security label — the distinct-code guarantee (S2).
    _refuse("assets/missing.png", "invalid", ws)


# ---------------------------------------------------------------------------
# PASS (contained, shape-clean, present).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    ["assets/throughput.png", f"assets/diagrams/{_HASH}.svg"],
    ids=["top_level", "nested_content_addressed"],
)
def test_contained_present_refs_pass(ws, target):
    # No raise — a contained, shape-clean, existing ref (including a NESTED diagram, proving
    # containment is descendant-at-any-depth, not direct-child) is accepted.
    assert assert_asset_refs_contained([target], workspace_root=ws) is None


def test_empty_target_list_passes(ws):
    # A body with no image references trivially passes.
    assert assert_asset_refs_contained([], workspace_root=ws) is None


def test_raises_on_the_first_failure_in_a_list(ws):
    # The guard refuses the FIRST offending ref even when a valid ref precedes it (A4 feeds the
    # whole body's targets in one call).
    with pytest.raises(AssetRefError) as exc:
        assert_asset_refs_contained(
            ["assets/throughput.png", "../../workspaces/other/secret.png"], workspace_root=ws
        )
    assert exc.value.kind == "uncontained"
    assert exc.value.target == "../../workspaces/other/secret.png"


# ---------------------------------------------------------------------------
# AST-walk behaviour — `iter_image_targets` / `has_raw_markup`.
# Hand-built ASTs need no pandoc; the parse-behaviour tests are pandoc-gated.
# ---------------------------------------------------------------------------


def _image_node(url: str) -> dict:
    """A minimal well-formed Pandoc `Image` node (`c = [attr, caption, [url, title]]`)."""
    return {"t": "Image", "c": [["", [], []], [{"t": "Str", "c": "alt"}], [url, ""]]}


def test_iter_image_targets_collects_nested_image_url():
    # An Image nested inside a Figure (pandoc's implicit_figures shape) is reached at depth.
    figure = {"t": "Figure", "c": [["", [], []], [None, []], [{"t": "Plain", "c": [
        _image_node("assets/x.png")]}]]}
    assert iter_image_targets({"blocks": [figure]}) == ["assets/x.png"]


def test_iter_image_targets_is_defensive_against_malformed_nodes():
    # A malformed Image (short `c`, non-string url) contributes NOTHING rather than raising, so a
    # surprising AST can never crash the compose gate — only the well-formed url is collected.
    malformed_short = {"t": "Image", "c": [["", [], []], []]}
    malformed_url = {"t": "Image", "c": [["", [], []], [], [123, ""]]}
    good = _image_node("assets/ok.png")
    assert iter_image_targets([malformed_short, malformed_url, good]) == ["assets/ok.png"]


def test_has_raw_markup_on_hand_built_asts():
    assert has_raw_markup({"blocks": [{"t": "RawBlock", "c": ["html", "<div>"]}]}) is True
    assert has_raw_markup([{"t": "RawInline", "c": ["tex", "\\x"]}]) is True
    assert has_raw_markup({"blocks": [{"t": "Para", "c": [{"t": "Str", "c": "hi"}]}]}) is False


class TestWalkBehaviourOnRealParses:
    """The plan's AST-walk behaviour, proven on REAL pinned-reader parses (pandoc-gated)."""

    def test_plain_markdown_image_is_collected(self):
        _requires_pandoc()
        ast = parse_to_ast("![alt](assets/throughput.png)")
        assert iter_image_targets(ast) == ["assets/throughput.png"]

    def test_reference_style_image_resolves_to_a_collected_url(self):
        _requires_pandoc()
        ast = parse_to_ast("![alt][ref]\n\n[ref]: assets/x.png\n")
        assert iter_image_targets(ast) == ["assets/x.png"]

    def test_image_syntax_inside_a_code_span_is_not_an_image(self):
        _requires_pandoc()
        # `![](x.png)` inside a code span is a Code node, not an Image — AST-walk robustness a
        # regex would get wrong. Nothing is collected.
        ast = parse_to_ast("`![](x.png)`")
        assert iter_image_targets(ast) == []

    def test_raw_html_img_is_raw_markup(self):
        _requires_pandoc()
        # The B1 vector: raw HTML `<img>` becomes a RawInline (invisible to the Image walk), so
        # has_raw_markup flags it — the compose gate (A4) refuses the body outright.
        ast = parse_to_ast('<img src="../../workspaces/other/secret.png">')
        assert iter_image_targets(ast) == []  # NOT seen as an Image
        assert has_raw_markup(ast) is True  # BUT caught by the raw-markup ban

    def test_pure_markdown_body_has_no_raw_markup(self):
        _requires_pandoc()
        ast = parse_to_ast("# Title\n\nSome **bold** and a [link](https://example.test).\n")
        assert has_raw_markup(ast) is False
