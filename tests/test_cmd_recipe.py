"""CLI tests for `pipeline recipe new` (authoring layer C2b) — the first consumer of C2a.

`recipe new ID [--from BASE] [picks] [--set] [--unset] [--force] --workspace` wires the pure
`pipeline.authoring` core (the PICK/TWEAK/CLEAR router, the `base ⊕ edits` merge, the provenance
home resolver, the conforming serializer, and the overwrite guard) into the operator CLI. These
tests exercise the SUBCOMMAND end to end (through `cli.main`/`cli._cmd_recipe`): the worked-example
round-trips (write → lints green → re-parses to the expected bundle), `--from` derive (seed → swap
→ MATERIALIZE a standalone file; a set-axis REPLACES, `--unset` drops a base pin), the boundary
refusals (a client `x-` binding REFUSED from public, homed under the workspace; unknown base /
non-slug id / bad edit), the overwrite guard (refuse-if-exists headless; `--force`), the
identity-neutral round-trip (a saved recipe resolves byte-identically to the same bindings inlined),
and the §21.9 money-safety invariant (`recipe new` never registers an invoke verb / mutates the
module-global handler map).
"""

from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
from pipeline import __main__ as cli
from pipeline.authoring import RECIPE_COLLECTION, VALUES_SLOT, bundle_from_entry
from pipeline.entries import PROVENANCE_FRAMEWORK, PROVENANCE_INSTANCE, load_entry
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS, lint_tree, render_report
from pipeline.schema import SCHEMA_FILENAME, load_schema

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = date(2026, 7, 30)
WS = "testws"
USER = "acme"
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"


# --- fixtures ---------------------------------------------------------------------------------


def _recipe_root(tmp_path: Path) -> Path:
    """A minimal lintable/loadable root carrying only the real recipe schema — enough for the
    write → lint → re-parse round-trips (lint resolves no cross-registry refs, C2a precedent)."""
    dst = registry_dir(tmp_path, RECIPE_COLLECTION) / SCHEMA_FILENAME
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(
        (registry_dir(REPO_ROOT, RECIPE_COLLECTION) / SCHEMA_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return tmp_path


def _seed_recipe(root: Path, name: str) -> None:
    """Copy a shipped framework recipe into a root's `recipes/` so `--from` can seed from it."""
    registry_dir(root, RECIPE_COLLECTION).mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        registry_dir(REPO_ROOT, RECIPE_COLLECTION) / f"{name}.md",
        registry_dir(root, RECIPE_COLLECTION) / f"{name}.md",
    )


def _recipe_schema(root: Path):
    return load_schema(registry_dir(root, RECIPE_COLLECTION) / SCHEMA_FILENAME)


def _reparsed_bundle(root: Path, path: Path) -> dict:
    """The written recipe's bindings, re-parsed through the strict loader (the C2a partial)."""
    return bundle_from_entry(load_entry(path, _recipe_schema(root)))


def _run(*argv: str) -> int:
    """Drive the subcommand exactly as the shim does (`cli.main(["recipe", "new", …])`)."""
    return cli.main(["recipe", *argv])


def build_root(tmp_path: Path) -> Path:
    """A full framework root (real registries) + a tmp instance/workspace — the SAME shape
    `tests/test_cli_generate.py` builds, so `resolve_plan` binds shipped entries and the
    identity-neutral run-level test can resolve a real plan."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    topics_dir = root / "users" / USER / "workspaces" / WS / "topics"
    topics_dir.mkdir(parents=True)
    (topics_dir / "x-t-alpha.md").write_text(
        TOPIC.format(tid="x-t-alpha", why="First."), encoding="utf-8"
    )
    return root


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke dispatch registry so the money-safety
    negative assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


# --- the plain-author worked example (write → prints id+path → lints → re-parses) -------------


def test_recipe_new_writes_public_file_prints_id_and_lints(tmp_path, capsys):
    """`recipe new my-brief --persona … --format … --set voice.formality=2` writes
    recipes/my-brief.md (prints the exact id + path), lints green, re-parses to the bundle."""
    root = _recipe_root(tmp_path)
    code = _run(
        "new", "my-brief", "--persona", "product-manager", "--format", "whitepaper",
        "--set", "voice.formality=2", "--root", str(root),
    )
    assert code == 0
    out = capsys.readouterr().out
    written = registry_dir(root, RECIPE_COLLECTION) / "my-brief.md"
    assert "my-brief" in out and str(written) in out  # prints the exact id + path

    report = lint_tree(root, now=NOW, baseline=None)
    assert report.ok, render_report(report)  # lints GREEN

    assert _reparsed_bundle(root, written) == {
        "persona": "product-manager",
        "format": "whitepaper",
        VALUES_SLOT: {"voice.formality": 2},
    }


def test_recipe_new_writes_exactly_one_file(tmp_path):
    """The §5.4 one-file-add: authoring a recipe adds EXACTLY one file to the root."""
    root = _recipe_root(tmp_path)
    before = {p for p in (registry_dir(root, RECIPE_COLLECTION)).iterdir()}
    assert _run("new", "solo", "--persona", "technical-evaluator", "--root", str(root)) == 0
    after = {p for p in (registry_dir(root, RECIPE_COLLECTION)).iterdir()}
    assert after - before == {registry_dir(root, RECIPE_COLLECTION) / "solo.md"}


def test_pick_writes_only_stated_slots(tmp_path):
    """`recipe new x --persona … --format …` writes ONLY those two slots (rest fall through)."""
    root = _recipe_root(tmp_path)
    assert _run(
        "new", "x", "--persona", "technical-evaluator", "--format", "short-opinion-post",
        "--root", str(root),
    ) == 0
    bundle = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "x.md")
    assert bundle == {"persona": "technical-evaluator", "format": "short-opinion-post"}


def test_repeated_goal_flag_stacks_the_set(tmp_path):
    """A repeated `--goals` accumulates into the ONE goal-set the recipe binds (§8)."""
    root = _recipe_root(tmp_path)
    assert _run("new", "g", "--goals", "explain", "--goals", "convince", "--root", str(root)) == 0
    bundle = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "g.md")
    assert set(bundle["goals"]) == {"explain", "convince"}


# --- `--from` derive (seed → swap → MATERIALIZE a standalone file) ----------------------------


def test_derive_seeds_base_and_swaps_a_pick(tmp_path, capsys):
    """`recipe new v2 --from explainer-post --persona …` seeds the base's slots and swaps the
    persona; the result is a STANDALONE recipe file (no base+delta / `extends` reference)."""
    root = _recipe_root(tmp_path)
    _seed_recipe(root, "explainer-post")
    assert _run(
        "new", "v2", "--from", "explainer-post", "--persona", "product-manager", "--root", str(root)
    ) == 0
    assert "derived from 'explainer-post'" in capsys.readouterr().out
    bundle = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "v2.md")
    # base persona (technical-evaluator) is REPLACED; base format + goals are inherited.
    assert bundle["persona"] == "product-manager"
    assert bundle["format"] == "short-opinion-post"
    assert bundle["goals"] == ["explain"]
    assert "extends" not in bundle  # materialized standalone, never a base reference


def test_derive_replaces_a_set_axis(tmp_path):
    """A set-axis pick REPLACES the base's set (not append): a base pinning platforms=[medium-post],
    derived with `--platform github --platform linkedin`, yields {github, linkedin} — NO medium."""
    root = _recipe_root(tmp_path)
    assert _run("new", "plat-base", "--platform", "medium-post", "--root", str(root)) == 0
    assert _run(
        "new", "social", "--from", "plat-base", "--platform", "github", "--platform", "linkedin",
        "--root", str(root),
    ) == 0
    social = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "social.md")
    platforms = social["platforms"]
    assert set(platforms) == {"github", "linkedin"}  # REPLACED
    assert "medium-post" not in platforms  # the base pin did NOT survive (no append)


def test_derive_unset_drops_a_base_pin(tmp_path):
    """`--unset voice` drops a base-pinned axis so it falls back through the cascade."""
    root = _recipe_root(tmp_path)
    assert _run("new", "vbase", "--voice", "clear-explainer", "--root", str(root)) == 0
    assert _run("new", "vd", "--from", "vbase", "--unset", "voice", "--root", str(root)) == 0
    assert "voice" not in _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "vd.md")


def test_derive_set_and_unset_together(tmp_path):
    """`--from … --set voice.formality=4 --unset diagram_style` applies BOTH edits."""
    root = _recipe_root(tmp_path)
    _seed_recipe(root, "explainer-post")
    assert _run(
        "new", "formal-brief", "--from", "explainer-post", "--set", "voice.formality=4",
        "--unset", "diagram_style", "--root", str(root),
    ) == 0
    bundle = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "formal-brief.md")
    assert bundle[VALUES_SLOT] == {"voice.formality": 4}
    assert "diagram_style" not in bundle


def test_unknown_base_refused_no_file(tmp_path, capsys):
    """An unknown `--from` base refuses loudly (m1 unknown-entry) → exit 1, no file written."""
    root = _recipe_root(tmp_path)
    code = _run("new", "nope", "--from", "does-not-exist", "--root", str(root))
    assert code == 1
    assert "unknown-entry" in capsys.readouterr().err
    assert not (registry_dir(root, RECIPE_COLLECTION) / "nope.md").exists()


def test_derive_from_extends_base_refuses_cleanly_no_traceback(tmp_path, capsys):
    """Deriving `--from` a base carrying an undeclared frontmatter key — e.g. the documented M1
    `extends:` partial `explainer-post.md`'s body advertises — is a CLEAN typed refusal: exit 1,
    a `pipeline recipe new:` message, and NO Python traceback (the strict loader's closed-schema
    `UndeclaredAttributeError`, a bare `ValueError`, is caught by `_recipe_error_types`, not
    leaked). Safe direction holds: no derived file is written."""
    root = _recipe_root(tmp_path)
    (registry_dir(root, RECIPE_COLLECTION) / "extends-base.md").write_text(
        "---\nid: extends-base\nprovenance: framework\nschema_version: 1\n"
        "extends: explainer-post\npersona: product-manager\n---\n\nBody.\n",
        encoding="utf-8",
    )
    code = _run("new", "derived", "--from", "extends-base", "--root", str(root))
    assert code == 1
    err = capsys.readouterr().err
    assert err.startswith("pipeline recipe new:")  # the clean typed refusal, not a raw trace
    assert "Traceback" not in err
    assert not (registry_dir(root, RECIPE_COLLECTION) / "derived.md").exists()


# --- provenance boundary (rule 4 / §10): a client binding never lands in public ---------------


def test_client_binding_refused_from_public_no_file(tmp_path, capsys):
    """A client (`x-`) topic pick under a public id is REFUSED from public → exit 1, no file."""
    root = _recipe_root(tmp_path)
    code = _run("new", "leak-brief", "--topic", "x-secret", "--root", str(root))
    assert code == 1
    assert "never the public repo" in capsys.readouterr().err
    assert not (registry_dir(root, RECIPE_COLLECTION) / "leak-brief.md").exists()


def test_client_binding_homes_under_workspace(tmp_path):
    """The same binding with an `x-` id + `--workspace` homes under the workspace (instance)."""
    root = _recipe_root(tmp_path)
    (root / "users" / USER / "workspaces" / "demo").mkdir(parents=True)
    assert _run(
        "new", "x-brief", "--topic", "x-secret",
        "--workspace", "demo", "--user", USER, "--root", str(root),
    ) == 0
    written = root / "users" / USER / "workspaces" / "demo" / RECIPE_COLLECTION / "x-brief.md"
    assert written.is_file()
    assert not (registry_dir(root, RECIPE_COLLECTION) / "x-brief.md").exists()  # NOT in public
    entry = load_entry(written, _recipe_schema(root))
    assert entry.provenance == PROVENANCE_INSTANCE
    assert entry.attributes["topic"] == "x-secret"


def test_framework_recipe_is_framework_provenance(tmp_path):
    """A framework-only binding homes public with framework provenance."""
    root = _recipe_root(tmp_path)
    assert _run("new", "fw", "--persona", "technical-evaluator", "--root", str(root)) == 0
    entry = load_entry(registry_dir(root, RECIPE_COLLECTION) / "fw.md", _recipe_schema(root))
    assert entry.provenance == PROVENANCE_FRAMEWORK


def test_from_base_under_workspace_without_user_is_clean_typed_refusal(tmp_path, capsys):
    """F1 (§23): `recipe new x-foo --from BASE --workspace demo` WITHOUT --user is a CLEAN typed
    refusal (exit 1, an authoring message class) — NEVER a raw TypeError traceback from the eager
    `_load_base_bundle` join, and never a `users/None/` path (LOUD-*and-clean*)."""
    root = build_root(tmp_path)
    code = _run(
        "new", "x-foo", "--from", "explainer-post", "--workspace", "demo", "--root", str(root)
    )
    assert code == 1
    err = capsys.readouterr().err
    assert "requires a --user" in err  # mirrors resolve_recipe_target's typed refusal
    assert "Traceback" not in err  # a clean typed refusal, never a stack trace
    assert "users/None" not in err


def test_from_base_under_workspace_with_user_still_works(tmp_path):
    """The SAME --from base WITH --user + --workspace resolves the base and homes the derived
    recipe under `users/<user>/workspaces/<ws>/recipes/` (the happy path is unbroken)."""
    root = build_root(tmp_path)
    code = _run(
        "new", "x-foo", "--from", "explainer-post",
        "--user", "acme", "--workspace", "demo", "--root", str(root),
    )
    assert code == 0
    written = root / "users" / "acme" / "workspaces" / "demo" / RECIPE_COLLECTION / "x-foo.md"
    assert written.is_file()


# --- loud edit / id refusals -----------------------------------------------------------------


def test_slug_invalid_id_refused(tmp_path, capsys):
    """A non-slug recipe id is a loud refusal (§7.4) → exit 1."""
    root = _recipe_root(tmp_path)
    assert _run("new", "Bad Id!", "--persona", "technical-evaluator", "--root", str(root)) == 1
    assert "slug" in capsys.readouterr().err


def test_bad_set_path_refused(tmp_path, capsys):
    """A 1-segment `--set` (a bare dimension, not a value) is the M1-wall refusal → exit 1."""
    root = _recipe_root(tmp_path)
    assert _run("new", "b", "--set", "voice=2", "--root", str(root)) == 1
    assert "dimension" in capsys.readouterr().err


def test_recipe_requires_subcommand_is_usage_error(tmp_path):
    """`pipeline recipe` with no subcommand is a usage error (exit 2), never a silent no-op."""
    assert cli.main(["recipe"]) == 2


# --- overwrite guard (D8): refuse-if-exists headless; `--force` overwrites --------------------


def test_overwrite_refused_headless_then_force(tmp_path, capsys):
    """A second write to the same id fails FAST headless (never hangs) → exit 1; `--force` wins."""
    root = _recipe_root(tmp_path)
    assert _run("new", "once", "--persona", "technical-evaluator", "--root", str(root)) == 0
    code = _run("new", "once", "--persona", "product-manager", "--root", str(root))
    assert code == 1
    assert "already exists" in capsys.readouterr().err
    # `--force` overwrites (the new binding lands).
    assert _run(
        "new", "once", "--persona", "product-manager", "--root", str(root), "--force"
    ) == 0
    reparsed = _reparsed_bundle(root, registry_dir(root, RECIPE_COLLECTION) / "once.md")
    assert reparsed["persona"] == "product-manager"


# --- identity-neutral: a saved recipe resolves byte-identically to the same bindings inlined ---


def _preview_artifact_ids(root: Path, recipe: str, capsys) -> str:
    """Resolve a one-item plan via the REAL `pipeline preview` door and return its artifact-ids
    line (the plan-only preview mints the artifact-id at resolution, spending nothing)."""
    code = cli._cmd_preview(
        ["--recipe", recipe, "--topic", "x-t-alpha", "--platform", "github",
         "--workspace", WS, "--user", USER, "--root", str(root)]
    )
    assert code == 0
    out = capsys.readouterr().out
    for line in out.splitlines():
        if "artifact-ids" in line:
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no artifact-ids line in preview output:\n{out}")


def test_saved_recipe_run_id_byte_identical_to_inlined(tmp_path, capsys):
    """A recipe AUTHORED from flags (r-eq: persona/format/goals) resolves to the SAME artifact-id
    as the shipped recipe carrying identical bindings — the recipe NAME never enters the artifact
    preimage (D10/W4), so authoring is identity-neutral."""
    root = build_root(tmp_path)
    assert _run(
        "new", "r-eq", "--persona", "technical-evaluator", "--format", "short-opinion-post",
        "--goals", "explain", "--root", str(root),
    ) == 0
    authored = _preview_artifact_ids(root, "r-eq", capsys)
    shipped = _preview_artifact_ids(root, "explainer-post", capsys)
    assert authored == shipped  # byte-identical artifact-id — the name is not in the preimage


# --- §21.9 money-safety: a LOCAL Tier-A write never touches the invoke door -------------------


def test_recipe_new_never_registers_a_verb(tmp_path):
    """`recipe new` is a LOCAL file write: it never registers a verb / mutates the module-global
    `_VERB_HANDLERS` (it cannot spend quota or mint a token; §21.9)."""
    root = _recipe_root(tmp_path)
    before = dict(invoke_mod._VERB_HANDLERS)
    assert _run("new", "ms", "--persona", "technical-evaluator", "--root", str(root)) == 0
    assert invoke_mod._VERB_HANDLERS == before  # handler map untouched


def test_recipe_source_calls_no_register(tmp_path):
    """Structural: the `_cmd_recipe` + helper source contains no `register_` call and never
    dispatches `invoke(` — money-safety by construction (grep the new code, §21.9)."""
    src = (REPO_ROOT / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    start = src.index("def _load_base_bundle")
    end = src.index("_COMMANDS = {")
    region = src[start:end]
    assert "register_" not in region
    assert "invoke_mod" not in region and "main_cli(" not in region
