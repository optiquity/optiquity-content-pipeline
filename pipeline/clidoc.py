"""Deterministic CLI-reference generator (mirrors `pipeline.attrdoc`; authoring layer D13).

`pipeline docs cli` renders `docs/reference/cli.md` — a user-facing reference of EVERY `pipeline`
command and subcommand: its description, a usage synopsis, and every flag/argument (with metavar/
choices, default, whether it is required, and its help). It is rendered from the LIVE argparse tree
that `pipeline.__main__.build_parser()` returns — the SAME per-command `_build_<cmd>_parser` the
runtime `--help` walks — so the doc can never disagree with the real CLI.

Deterministic by construction: the tree is walked in DEFINITION order (argparse preserves the add
order of arguments and the insertion order of subparser choices), the argument table is a pure
function of each parser's structure, and the usage synopsis is built HERE (never via argparse's
`format_usage`/`format_help`, which wrap to the ambient terminal width and would make the byte-
equality drift test diverge by environment). No clock, no environment, no cwd. `render_cli_doc()`
returns the exact bytes the drift test (`tests/test_cli_doc_contract.py`) asserts are committed at
`docs/reference/cli.md`.

This is a LOCAL operator generator (design D13): it writes a framework doc via the local CLI and is
never wired to an HTTP `_VERB_HANDLERS` verb (not a spend door, no identity surface).
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path

__all__ = [
    "DOC_RELPATH",
    "GENERATED_HEADER",
    "command_count",
    "documented_arguments",
    "framework_root",
    "iter_command_tree",
    "render_cli_doc",
    "subcommand_help",
    "subparsers_action",
    "write_cli_doc",
]

#: The committed artifact this generator owns (repo-relative).
DOC_RELPATH = "docs/reference/cli.md"

#: The "do not edit — regenerate" banner (first line of the emitted doc).
GENERATED_HEADER = "<!-- GENERATED — do not edit; run `pipeline docs cli` -->"


def framework_root() -> Path:
    """The framework repo root — derived from this module's own location, cwd-independent."""
    return Path(__file__).resolve().parents[1]


# --- Introspection (shared by the renderer AND the completeness contract test) --------------------


def subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    """The parser's subcommand container, or None if the command is a leaf (has no subcommands)."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def subcommand_help(action: argparse._SubParsersAction) -> dict[str, str | None]:
    """Map each subcommand name → its parent-list one-line `help=` (the `add_parser(help=...)`)."""
    return {choice.dest: choice.help for choice in action._choices_actions}


def documented_arguments(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    """Every REAL argument of a parser, in definition order — excluding the two argparse-internal
    container/meta actions that are not user-authored flags: the auto-added `-h/--help` action and
    the subcommand container (rendered as nested sections, not as a row)."""
    return [
        action
        for action in parser._actions
        if not isinstance(action, (argparse._HelpAction, argparse._SubParsersAction))
    ]


def iter_command_tree(
    parser: argparse.ArgumentParser,
    *,
    path: tuple[str, ...] = (),
    help_text: str | None = None,
) -> Iterator[tuple[tuple[str, ...], argparse.ArgumentParser, str | None]]:
    """Depth-first walk of the whole command tree. Yields `(path, parser, help)` for the ROOT
    (path == (parser.prog,), help is None) and then every subcommand in definition order (path is
    the full command path e.g. `("pipeline", "transport", "store-key")`, help is the parent-list
    one-liner threaded down from the parent's subparsers action). Deterministic: argparse preserves
    subparser insertion order in `.choices`."""
    here = path or (parser.prog,)
    yield here, parser, help_text
    action = subparsers_action(parser)
    if action is None:
        return
    help_map = subcommand_help(action)
    for name, child in action.choices.items():
        yield from iter_command_tree(child, path=here + (name,), help_text=help_map.get(name))


def command_count(parser: argparse.ArgumentParser) -> int:
    """The number of commands documented (every node below the root; not the root itself)."""
    action = subparsers_action(parser)
    if action is None:
        return 0
    return sum(1 + command_count(child) for child in action.choices.values())


# --- Deterministic rendering primitives (never argparse's width-dependent formatters) -------------


def _metavar(action: argparse.Action) -> str:
    """The value placeholder for an argument — its explicit metavar, else `{choices}`, else the
    conventional argparse default (dest upper-cased for an option, dest as-is for a positional)."""
    if action.metavar is not None:
        return str(action.metavar)
    if action.choices is not None:
        return "{" + ",".join(str(c) for c in action.choices) + "}"
    if action.option_strings:
        return action.dest.upper()
    return action.dest


def _takes_value(action: argparse.Action) -> bool:
    """True when the argument consumes a value (so a metavar/default is meaningful) — i.e. it is not
    a nargs=0 flag such as `store_true`/`store_const`/`version`."""
    if isinstance(action, argparse._VersionAction):
        return False
    return action.nargs != 0


def _is_required(action: argparse.Action) -> bool:
    """Whether the argument must be supplied: an option honors `required=`; a positional is required
    unless its nargs makes it optional (`?`/`*`)."""
    if action.option_strings:
        return bool(action.required)
    return action.nargs not in ("?", "*")


def _cell(text: str) -> str:
    """One Markdown table cell: escape the `|` column separator; help is already one line."""
    return text.replace("|", "\\|")


def _synopsis(parser: argparse.ArgumentParser) -> str:
    """A deterministic usage synopsis built from the parser's own structure (NOT argparse's
    width-wrapping `format_usage`): required tokens bare, optional tokens in `[...]`, the subcommand
    container as its metavar. Definition order (argparse `_actions` order, sans the help action)."""
    tokens: list[str] = [f"`{parser.prog}`"]
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        if isinstance(action, argparse._SubParsersAction):
            tokens.append(f"`{_metavar(action)} ...`")
            continue
        if action.option_strings:  # an optional flag
            flag = action.option_strings[0]
            body = f"{flag} {_metavar(action)}" if _takes_value(action) else flag
        else:  # a positional
            body = _metavar(action)
        tokens.append(f"`{body}`" if _is_required(action) else f"[`{body}`]")
    return " ".join(tokens)


def _argument_rows(parser: argparse.ArgumentParser) -> list[str]:
    """The Markdown table rows for a parser's arguments, or `[]` when it has none (a pure group)."""
    args = documented_arguments(parser)
    if not args:
        return []
    rows = [
        "| argument | value | default | required | description |",
        "| --- | --- | --- | --- | --- |",
    ]
    for action in args:
        name = ", ".join(action.option_strings) if action.option_strings else _metavar(action)
        value = _metavar(action) if _takes_value(action) else ""
        if _takes_value(action) and action.default is not None:
            default = f"`{action.default}`"
        else:
            default = ""
        required = "yes" if _is_required(action) else ""
        help_text = action.help or ""
        rows.append(
            f"| `{_cell(name)}` | {_cell(value)} | {_cell(default)} | {required} "
            f"| {_cell(help_text)} |"
        )
    return rows


def _command_section(path: tuple[str, ...], parser: argparse.ArgumentParser) -> list[str]:
    """One command's Markdown block: a depth-scaled heading (its full path), the description, the
    usage synopsis, and the argument table (omitted for a pure subcommand group)."""
    level = min(1 + len(path), 6)  # `pipeline` → ##, `pipeline x` → ###, `pipeline x y` → ####
    lines = [f"{'#' * level} `{' '.join(path)}`", ""]
    if parser.description:
        lines += [str(parser.description), ""]
    lines += [f"Usage: {_synopsis(parser)}", ""]
    lines += _argument_rows(parser)
    if lines[-1] != "":
        lines.append("")
    return lines


def render_cli_doc(parser: argparse.ArgumentParser) -> str:
    """Render the full `cli.md` document as a string (the drift-test ground truth)."""
    n_commands = command_count(parser)
    lines: list[str] = [
        GENERATED_HEADER,
        "",
        "# Pipeline CLI reference",
        "",
        (
            "Every `pipeline` command and subcommand — its description, usage synopsis, and every "
            "flag/argument (value, default, whether it is required, and its help). This page is "
            "generated from the live argparse command tree (`pipeline.__main__.build_parser()`), "
            "the SAME tree the runtime `--help` walks, so it carries the real CLI surface, never a "
            "hand-maintained copy that could drift."
        ),
        "",
        (
            "Regenerate with `pipeline docs cli`. A byte-equality CI test "
            "(`tests/test_cli_doc_contract.py`) fails loudly if a command or flag changes without "
            "regenerating this file, and asserts every command + flag carries help."
        ),
        "",
        f"Documented: {n_commands} commands.",
        "",
    ]
    for path, node, _help in iter_command_tree(parser):
        lines += _command_section(path, node)
    return "\n".join(lines).rstrip("\n") + "\n"


def write_cli_doc(parser: argparse.ArgumentParser, root: str | Path | None = None) -> Path:
    """Render and write `docs/reference/cli.md`; return the written path."""
    base = Path(root) if root is not None else framework_root()
    out_path = base / DOC_RELPATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_cli_doc(parser), encoding="utf-8")
    return out_path
