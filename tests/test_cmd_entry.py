"""CLI tests for `pipeline entry new` (authoring layer C3) — the second consumer of C2a.

`entry new DIMENSION ID [--workspace W] [--force] [--root DIR]` wires the thin
`pipeline.entryscaffold` leaf (which itself REUSES the C2a `pipeline.authoring` core: the slug
validator, the overwrite guard, and the pinned frontmatter dumper) into the operator CLI. These
tests exercise the SUBCOMMAND end to end (through `cli.main`/`cli._cmd_entry`): the scaffold
lints GREEN unedited (floor-only + the envelope, valid by construction, D11/W5) and re-parses to
exactly `Schema.defaults()`; the `definition:` prose lands as inline `#`-comments; `--workspace`
homes an `x-`-prefixed instance file under the workspace; `entry new topic` REFUSES without a
`--workspace`; a bad dimension / non-slug id / framework `x-` id refuse loudly (never a crash);
the overwrite guard refuses-if-exists headless and `--force` wins; exactly one file is written;
and the §21.9 money-safety invariant holds (`entry new` never registers an invoke verb / mutates
the module-global handler map).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline.entries import (
    INSTANCE_ID_PREFIX,
    PROVENANCE_FRAMEWORK,
    PROVENANCE_INSTANCE,
    load_entry,
)
from pipeline.lint import lint_tree, render_report
from pipeline.m1 import DIMENSION_COLLECTIONS
from pipeline.schema import SCHEMA_FILENAME, load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = date(2026, 7, 30)
USER = "acme"


# --- fixtures ---------------------------------------------------------------------------------


def _copy_schema(root: Path, collection: str, *, at: Path | None = None) -> None:
    """Copy the real framework `<collection>/_schema.yaml` into `root` (or `at`) so the scaffold
    generates from — and lint validates against — the SAME schema."""
    dst = (at or (root / collection)) / SCHEMA_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (REPO_ROOT / collection / SCHEMA_FILENAME).read_text(encoding="utf-8"), encoding="utf-8"
    )


def _dim_root(tmp_path: Path, *dimensions: str) -> Path:
    """A minimal lintable root carrying only the named dimensions' real framework schemas."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for dim in dimensions:
        _copy_schema(root, DIMENSION_COLLECTIONS[dim])
    return root


def _run(*argv: str) -> int:
    """Drive the subcommand exactly as the shim does (`cli.main(["entry", "new", …])`)."""
    return cli.main(["entry", *argv])


def _framework_schema(collection: str):
    return load_schema(REPO_ROOT / collection / SCHEMA_FILENAME)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke dispatch registry so the money-safety negative
    assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


# --- the crux: a floor-only scaffold lints GREEN unedited (D11/W5) ----------------------------


def test_scaffold_lints_green_unedited(tmp_path, capsys):
    """`entry new persona my-eval --root <root>` writes personas/my-eval.md (prints id + path),
    provenance framework, every attribute at its floor + `definition:` comments; the tree lints
    GREEN with NO edits (the scaffold conforms by construction)."""
    root = _dim_root(tmp_path, "persona")
    code = _run("new", "persona", "my-eval", "--root", str(root))
    assert code == 0
    out = capsys.readouterr().out
    written = root / "personas" / "my-eval.md"
    assert written.is_file()
    assert "my-eval" in out and str(written) in out  # prints the exact id + path

    # lints GREEN unedited — and the entry was actually scanned/validated (not vacuously clean).
    report = lint_tree(root, now=NOW, baseline=None)
    assert report.ok, render_report(report)
    assert report.entries_scanned >= 1

    schema = _framework_schema("personas")
    entry = load_entry(written, schema)
    assert entry.provenance == PROVENANCE_FRAMEWORK
    assert not entry.id.startswith(INSTANCE_ID_PREFIX)
    # every attribute present at its exact schema floor (floor-only, no edits)
    assert entry.attributes == schema.defaults()
    assert set(entry.attributes) == set(schema.attributes)


def test_scaffold_carries_definition_prose_as_comments(tmp_path):
    """Every attribute's `definition:` prose is emitted as inline `#`-comment guidance (the same
    text the C1 reference surfaces) — carried IN the file, invisible to the parsed values."""
    root = _dim_root(tmp_path, "persona")
    assert _run("new", "persona", "guide", "--root", str(root)) == 0
    text = (root / "personas" / "guide.md").read_text(encoding="utf-8")
    comment_lines = [ln[2:] for ln in text.splitlines() if ln.startswith("# ")]
    joined = " ".join(comment_lines)
    schema = _framework_schema("personas")
    for spec in schema.attributes.values():
        first = spec.definition.split("\n", 1)[0].rstrip()
        assert first and first in joined, f"missing definition comment for {spec.name!r}"


def test_zero_attribute_dimension_scaffolds_and_lints(tmp_path):
    """A zero-attribute dimension (`output-types`, attributes: {}) scaffolds a documented
    'no attributes' envelope — never a crash — and lints green (C1 zero-attr precedent)."""
    root = _dim_root(tmp_path, "output-type")
    assert _run("new", "output-type", "my-fmt", "--root", str(root)) == 0
    written = root / "output-types" / "my-fmt.md"
    text = written.read_text(encoding="utf-8")
    assert "no attributes" in text
    report = lint_tree(root, now=NOW, baseline=None)
    assert report.ok, render_report(report)
    entry = load_entry(written, _framework_schema("output-types"))
    assert entry.attributes == {}


# --- instance home: --workspace → an x--prefixed instance file (rule 2/§10) -------------------


def test_workspace_gives_x_prefixed_instance_file(tmp_path, capsys):
    """`entry new persona x-my-eval --workspace demo` writes
    workspaces/demo/personas/x-my-eval.md (provenance instance, x--prefixed), NOT public — and
    with a co-located workspace schema it lints GREEN unedited."""
    root = _dim_root(tmp_path, "persona")
    # a co-located workspace schema so lint actually SCANS + validates the instance entry
    _copy_schema(root, "personas", at=root / "users" / USER / "workspaces" / "demo" / "personas")
    code = _run(
        "new", "persona", "x-my-eval", "--workspace", "demo", "--user", USER, "--root", str(root)
    )
    assert code == 0
    written = root / "users" / USER / "workspaces" / "demo" / "personas" / "x-my-eval.md"
    assert written.is_file()
    assert not (root / "personas" / "x-my-eval.md").exists()  # NOT public
    out = capsys.readouterr().out
    assert "x-my-eval" in out and str(written) in out

    report = lint_tree(root, now=NOW, baseline=None)
    assert report.ok, render_report(report)
    # B7: lint's EXTRA_SCOPE_DIRS now names `users/`, so the instance entry written under
    # users/<user>/workspaces/demo/personas/ IS in scope and gets scanned/validated (not
    # vacuously clean) — a well-formed `provenance: instance` x- entry is lint-clean (§10 rule 5).
    assert report.entries_scanned >= 1

    entry = load_entry(written, _framework_schema("personas"))
    assert entry.provenance == PROVENANCE_INSTANCE
    assert entry.id.startswith(INSTANCE_ID_PREFIX)
    assert entry.attributes == _framework_schema("personas").defaults()


def test_workspace_auto_prefixes_x(tmp_path):
    """A `--workspace` id WITHOUT the `x-` prefix is auto-prefixed (an instance entry is always
    `x-`-namespaced, §11.4): `my-eval` → x-my-eval.md."""
    root = _dim_root(tmp_path, "persona")
    assert _run(
        "new", "persona", "my-eval", "--workspace", "demo", "--user", USER, "--root", str(root)
    ) == 0
    ws = root / "users" / USER / "workspaces" / "demo" / "personas"
    assert (ws / "x-my-eval.md").is_file()
    assert not (ws / "my-eval.md").exists()


# --- topic REQUIRES --workspace (topics are workspace editorial data, rule 2/§10) -------------


def test_entry_new_topic_requires_workspace(tmp_path, capsys):
    """`entry new topic foo` WITHOUT --workspace refuses loudly (exit 1) and writes NO file —
    topics are workspace editorial data, never a framework default."""
    root = _dim_root(tmp_path, "topic")
    code = _run("new", "topic", "foo", "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert "requires --workspace" in err
    assert not (root / "topics" / "foo.md").exists()


def test_entry_new_topic_with_workspace_ok(tmp_path):
    """The same topic WITH --workspace homes under the workspace as an x- instance entry."""
    root = _dim_root(tmp_path, "topic")
    assert _run(
        "new", "topic", "launch", "--workspace", "demo", "--user", USER, "--root", str(root)
    ) == 0
    assert (root / "users" / USER / "workspaces" / "demo" / "topics" / "x-launch.md").is_file()


# --- loud dimension / id refusals (never a crash) ---------------------------------------------


def test_bad_dimension_refused_no_crash(tmp_path, capsys):
    """`entry new nonsense x` is a loud refusal (exit 1) naming the real dimension set — not a
    traceback, and no file."""
    root = _dim_root(tmp_path, "persona")
    code = _run("new", "nonsense", "x", "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline entry new:")
    assert "not a scaffoldable dimension" in err
    assert "Traceback" not in err


def test_recipe_is_not_a_dimension(tmp_path):
    """A mechanism registry (`recipe`) is NOT a scaffoldable dimension (it has its own verb)."""
    root = _dim_root(tmp_path, "persona")
    assert _run("new", "recipe", "x", "--root", str(root)) == 1


def test_slug_invalid_id_refused(tmp_path, capsys):
    """A non-slug entry id is a loud refusal (§7.4) → exit 1, no file."""
    root = _dim_root(tmp_path, "persona")
    assert _run("new", "persona", "Bad Id!", "--root", str(root)) == 1
    assert "slug" in capsys.readouterr().err
    assert not (root / "personas" / "Bad Id!.md").exists()


def test_framework_x_prefix_refused(tmp_path, capsys):
    """A framework (no --workspace) id carrying the reserved `x-` prefix is refused (§11.4)."""
    root = _dim_root(tmp_path, "persona")
    code = _run("new", "persona", "x-leak", "--root", str(root))
    assert code == 1
    assert INSTANCE_ID_PREFIX in capsys.readouterr().err
    assert not (root / "personas" / "x-leak.md").exists()


def test_entry_requires_subcommand_is_usage_error():
    """`pipeline entry` with no subcommand is a usage error (exit 2), never a silent no-op."""
    assert cli.main(["entry"]) == 2


def test_missing_schema_root_refuses_cleanly(tmp_path, capsys):
    """A root with no dimension schema is a clean typed refusal (exit 1), not a bare traceback."""
    empty = tmp_path / "empty"
    empty.mkdir()
    code = _run("new", "persona", "x", "--root", str(empty))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline entry new:")
    assert "Traceback" not in err


# --- overwrite guard (D8): refuse-if-exists headless; `--force` overwrites --------------------


def test_overwrite_refused_headless_then_force(tmp_path, capsys):
    """A second write to the same id fails FAST headless (never hangs) → exit 1; `--force` wins."""
    root = _dim_root(tmp_path, "persona")
    assert _run("new", "persona", "once", "--root", str(root)) == 0
    code = _run("new", "persona", "once", "--root", str(root))
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    assert _run("new", "persona", "once", "--root", str(root), "--force") == 0


# --- exactly ONE file per invocation (the §5.4 one-file-add) ----------------------------------


def test_entry_new_writes_exactly_one_file(tmp_path):
    """Authoring an entry adds EXACTLY one file to the collection (§5.4 one-file-add)."""
    root = _dim_root(tmp_path, "voice")
    before = {p for p in (root / "voices").iterdir()}
    assert _run("new", "voice", "solo", "--root", str(root)) == 0
    after = {p for p in (root / "voices").iterdir()}
    assert after - before == {root / "voices" / "solo.md"}


# --- §21.9 money-safety: a LOCAL Tier-A write never touches the invoke door --------------------


def test_entry_new_never_registers_a_verb(tmp_path):
    """`entry new` is a LOCAL file write: it never registers a verb / mutates the module-global
    `_VERB_HANDLERS` (it cannot spend quota or mint a token; §21.9)."""
    root = _dim_root(tmp_path, "persona")
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run("new", "persona", "ms", "--root", str(root)) == 0
    assert invoke_mod._VERB_HANDLERS == before  # handler map untouched


def test_entry_scaffold_source_calls_no_register():
    """Structural: the `entryscaffold` module + the `_cmd_entry` region contain no `register_`
    call and never dispatch through the invoke door — money-safety by construction (§21.9)."""
    scaffold_src = (REPO_ROOT / "pipeline" / "entryscaffold.py").read_text(encoding="utf-8")
    assert "register_" not in scaffold_src
    assert "invoke_mod" not in scaffold_src

    main_src = (REPO_ROOT / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    start = main_src.index("def _entry_error_types")
    end = main_src.index("_COMMANDS = {")
    region = main_src[start:end]
    assert "register_" not in region
    assert "invoke_mod" not in region and "main_cli(" not in region
