"""Anti-drift + completeness contract: `docs/reference/cli.md` == the generator's OWN output.

The CLI reference (authoring layer D13) is generated from the live argparse command tree
(`pipeline.__main__.build_parser()`) by `pipeline.clidoc`. This test keeps the committed page HONEST
in two ways, mirroring `tests/test_attributes_doc_contract.py`:

  - **Byte-equality** — regenerate the doc in memory and assert byte-for-byte equality, so a command
    or flag added/renamed/re-helped WITHOUT running `pipeline docs cli` fails loudly in CI. Because
    every command's flags come from the SAME `_build_<cmd>_parser` the runtime `--help` uses, this
    also proves the doc matches the real CLI.
  - **Completeness** — walk the whole tree and assert EVERY subcommand carries a non-empty `help=`
    (its one-line entry in the parent's list) AND a non-empty `description=` (shown atop its own
    `--help`), and EVERY argument carries a non-empty `help=`. So a future flag or subcommand added
    without help fails CI here, not silently ships an undocumented surface.
"""

from __future__ import annotations

import argparse

from pipeline import clidoc
from pipeline.__main__ import build_parser

_DOC = clidoc.framework_root() / clidoc.DOC_RELPATH


# --- The load-bearing byte-equality contract -----------------------------------------------------


def test_cli_doc_regenerates_identically() -> None:
    """The committed doc IS the generator's output — regenerating changes nothing."""
    committed = _DOC.read_text(encoding="utf-8")
    assert clidoc.render_cli_doc(build_parser()) == committed, (
        "docs/reference/cli.md is stale — run `pipeline docs cli` and commit it (a command, "
        "subcommand, flag, default, or help string changed without regenerating)"
    )


def test_render_is_deterministic() -> None:
    """No clock/env/cwd/terminal-width: two renders of the same tree are byte-identical."""
    assert clidoc.render_cli_doc(build_parser()) == clidoc.render_cli_doc(build_parser())


def test_doc_has_generated_header_first_line() -> None:
    committed = _DOC.read_text(encoding="utf-8")
    assert committed.startswith(clidoc.GENERATED_HEADER + "\n")
    assert "run `pipeline docs cli`" in clidoc.GENERATED_HEADER


# --- Completeness: every command + flag carries help --------------------------------------------


def _help_gaps(parser: argparse.ArgumentParser) -> list[str]:
    """Every completeness violation in the tree: a subcommand missing help= or description=, or an
    argument missing help=. Reused by the contract assertion AND the guard-bites test below."""
    gaps: list[str] = []
    for path, node, help_text in clidoc.iter_command_tree(parser):
        label = " ".join(path)
        if path != (parser.prog,):  # every non-root command is a subparser
            if not (help_text or "").strip():
                gaps.append(f"subcommand {label!r} has no help=")
            if not (node.description or "").strip():
                gaps.append(f"subcommand {label!r} has no description=")
        for action in clidoc.documented_arguments(node):
            name = action.option_strings[0] if action.option_strings else action.dest
            if not (action.help or "").strip():
                gaps.append(f"argument {label} {name!r} has no help=")
    return gaps


def test_every_command_and_flag_has_help() -> None:
    """The whole live CLI tree is fully documented — no bare subcommand or flag."""
    gaps = _help_gaps(build_parser())
    assert gaps == [], "CLI help is incomplete:\n  " + "\n  ".join(gaps)


def test_completeness_guard_bites_a_helpless_flag() -> None:
    """The completeness check is real: a flag added WITHOUT help is caught (so CI would fail)."""
    parser = build_parser()
    sub = clidoc.subparsers_action(parser)
    assert sub is not None
    victim = sub.choices["list"]
    victim.add_argument("--no-help-flag")  # deliberately no help=
    gaps = _help_gaps(parser)
    assert any("--no-help-flag" in g for g in gaps), "completeness walk missed a helpless flag"


def test_completeness_guard_bites_a_helpless_subcommand() -> None:
    """The SUBCOMMAND branch of the completeness walk is real too: a subcommand added WITHOUT a
    help= / description= is caught (so CI would fail), not only a helpless flag."""
    parser = build_parser()
    sub = clidoc.subparsers_action(parser)
    assert sub is not None
    sub.add_parser("zzz-bare")  # deliberately no help= AND no description=
    gaps = _help_gaps(parser)
    assert any("zzz-bare" in g and "no help=" in g for g in gaps), "missed a helpless subcommand"
    assert any(
        "zzz-bare" in g and "no description=" in g for g in gaps
    ), "missed a description-less subcommand"


# --- The byte-equality drift guard BITES (a CLI change without regeneration fails) ---------------


def test_drift_guard_bites_a_new_command() -> None:
    """Adding a command to the tree changes the rendered bytes — exactly the divergence
    `test_cli_doc_regenerates_identically` raises when the CLI changes without regenerating."""
    baseline = clidoc.render_cli_doc(build_parser())
    parser = build_parser()
    sub = clidoc.subparsers_action(parser)
    assert sub is not None
    extra = sub.add_parser("zzz-drift", help="a drift probe", description="drift probe")
    extra.add_argument("--probe", help="a probe flag")
    assert clidoc.render_cli_doc(parser) != baseline, (
        "the drift guard did NOT bite a newly added command"
    )


# --- The §3 enumerated surface is really documented (spot-checks) --------------------------------


def test_transport_group_and_store_key_documented() -> None:
    """The doc lists the `transport` group AND every transport subcommand — including `store-key`,
    the store-a-secret verb the task calls out explicitly."""
    doc = _DOC.read_text(encoding="utf-8")
    assert "### `pipeline transport`" in doc
    for sub in (
        "store-key",
        "assign-key",
        "list-keys",
        "clear-key",
        "set-subscription-user",
        "clear-subscription-user",
        "set-umbrella-cap",
        "clear-umbrella-cap",
        "show",
    ):
        assert f"#### `pipeline transport {sub}`" in doc, f"transport {sub} missing from cli.md"


def test_every_top_level_command_documented() -> None:
    """Every top-level command the runtime dispatches (`_COMMANDS`) has a section in the doc — plus
    the new `docs cli` generator itself (the self-reference)."""
    from pipeline.__main__ import _COMMANDS

    doc = _DOC.read_text(encoding="utf-8")
    for command in _COMMANDS:
        assert f"`pipeline {command}`" in doc, f"top-level command {command!r} missing from cli.md"
    assert "#### `pipeline docs cli`" in doc
