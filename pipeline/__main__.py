"""`python -m pipeline` — the module entry point behind the `scripts/pipeline` shim (T8).

Subcommands are added by their owning plan steps; unknown subcommands are refused loudly.
Implemented:

  drift-report   (plan step 12, PA-9c) — the NAMED update-time drift entry point: runs the
                 SV7/MIG-6 report (docs/design.md §11.5) over every config collection.
                 READ-ONLY operator verb; NEVER on the external-actor API (§21.9). Plan
                 step 40 hooks it into `scripts/update-from-upstream.sh` post-update.

  ssot           (plan step 22) — tracking-SSOT operator verbs. `ssot derive-state` renders
                 the derived `state.md`-style status mirror (CLAUDE.md rule 3; §24) from an
                 SSOT CSV to a CALLER-SUPPLIED path (or stdout) — READ-ONLY, never touching
                 the repo's own state.md. The SSOT is write-only w.r.t. control flow (§22.7):
                 there is no read-a-status verb here, only the whole-report projection.

(`migrate` is deliberately NOT a subcommand here: migration is a maintenance verb with its
own entry point, `scripts/migrate.sh` → `python -m pipeline.migration` — §11.6/§21.9.)
"""

import sys

_USAGE = """\
usage: pipeline [-h|--help] [--version] <command> [args...]

The optiquity-content-pipeline operator CLI (framework mechanism).

commands:
  drift-report   update-time drift report (SV7/MIG-6, design §11.5) over a config tree.
                 Read-only. Exit 0 = nothing blocks; 1 = blocking drift found; 2 = usage.
                 Options: --root DIR (default .) · --registry FILE (default
                 <root>/pipeline/migrations.yaml; missing = empty) · --now YYYY-MM-DD
                 (clock override; default today).
  ssot           tracking-SSOT verbs (design §24). Subcommand:
                   derive-state  render the derived state.md-style mirror from an SSOT CSV.
                                 Read-only; writes to a caller-supplied path or stdout,
                                 never the repo's own state.md. Options: --csv FILE
                                 (required) · --out FILE (default: stdout). Exit 0 ok; 2 usage.

Further subcommands land with their owning plan steps (see docs/design.md and the build
plan). Migration is NOT a subcommand: run scripts/migrate.sh (§11.6).
"""


def _cmd_drift_report(argv: list[str]) -> int:
    """PA-9c: `scripts/pipeline drift-report` — the update-time report (§11.5 SV7)."""
    import argparse
    from datetime import date
    from pathlib import Path

    from pipeline import drift, migration

    parser = argparse.ArgumentParser(
        prog="pipeline drift-report",
        description=(
            "Run the update-time drift report (docs/design.md §11.5 SV7/MIG-6) over every "
            "config collection under --root: redefinitions to review (BLOCK), removed "
            "attributes still present (BLOCK), out-of-window stamps (BLOCK, MIG-2), new "
            "attributes riding defaults (WARN). Wording-only changes are silent by "
            "design. Read-only; remediation is scripts/migrate.sh (never auto-run)."
        ),
    )
    parser.add_argument("--root", default=".", help="config tree root (default: cwd)")
    parser.add_argument(
        "--registry",
        default=None,
        help=(
            "migration step registry, the out-of-window oracle (default: "
            f"<root>/{migration.MIGRATION_REGISTRY_RELPATH}; missing = empty registry)"
        ),
    )
    parser.add_argument(
        "--now",
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "override the report clock (ops/testing; default: today). The clock is "
            "injected here at the edge — the library never reads ambient time."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root)
    registry_path = (
        Path(args.registry) if args.registry else root / migration.MIGRATION_REGISTRY_RELPATH
    )
    try:
        now = date.fromisoformat(args.now) if args.now else date.today()  # the clock edge
    except ValueError:
        print(f"pipeline drift-report: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2
    try:
        registry = migration.load_step_registry(registry_path)
    except migration.RegistryError as exc:
        print(f"pipeline drift-report: {exc}", file=sys.stderr)
        return 2

    report = drift.build_drift_report(root, now=now, window=registry)
    sys.stdout.write(drift.render_drift_report(report))
    return 1 if report.has_blocks else 0


def _cmd_ssot(argv: list[str]) -> int:
    """Plan step 22: `scripts/pipeline ssot <subcommand>` — tracking-SSOT operator verbs.

    Only `derive-state` exists in v1: it renders the derived `state.md`-style mirror
    (CLAUDE.md rule 3; docs/design.md §24) from an SSOT CSV. Read-only; the output goes to a
    CALLER-SUPPLIED `--out` path or stdout — never the repo's live `state.md`. There is
    deliberately no read-a-status verb: the SSOT is write-only w.r.t. control flow (§22.7).
    """
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="pipeline ssot",
        description="Tracking-SSOT operator verbs (design §24).",
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    derive = sub.add_parser(
        "derive-state",
        help="render the derived state.md-style mirror from an SSOT CSV (read-only)",
        description=(
            "Render the derived, read-only state.md-style status mirror (CLAUDE.md rule 3; "
            "docs/design.md §24) from an SSOT CSV. Byte-deterministic for a fixed CSV. The "
            "output is written to --out (a caller-supplied path) or stdout — never the repo's "
            "own state.md, which is the maintainer's live session document."
        ),
    )
    derive.add_argument(
        "--csv", required=True, metavar="FILE", help="the SSOT CSV to project (read-only)"
    )
    derive.add_argument(
        "--out",
        default=None,
        metavar="FILE",
        help="caller-supplied destination for the mirror (default: stdout)",
    )
    args = parser.parse_args(argv)

    if args.subcommand != "derive-state":
        parser.print_usage(sys.stderr)
        print("pipeline ssot: a subcommand is required (known: derive-state)", file=sys.stderr)
        return 2

    from pipeline.ssot import derive_state

    rendered = derive_state(Path(args.csv))
    if args.out:
        # Byte-exact write (write_bytes, not write_text): the mirror is what derive_state
        # produced, no newline translation. Caller-supplied path ONLY (never state.md).
        Path(args.out).write_bytes(rendered.encode("utf-8"))
    else:
        sys.stdout.write(rendered)
    return 0


_COMMANDS = {
    "drift-report": _cmd_drift_report,
    "ssot": _cmd_ssot,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok; 1 command-reported findings;
    2 usage error; command-specific codes documented per command)."""
    from pipeline import __version__

    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE, end="")
        return 0
    if args[0] == "--version":
        print(f"pipeline {__version__}")
        return 0
    command = _COMMANDS.get(args[0])
    if command is None:
        print(
            f"pipeline: unknown command {args[0]!r} (known: {sorted(_COMMANDS)})",
            file=sys.stderr,
        )
        return 2
    return command(args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
