"""`python -m pipeline` — the module entry point behind the `scripts/pipeline` shim (T8).

Subcommands are added by their owning plan steps; unknown subcommands are refused loudly.
Implemented:

  drift-report   (plan step 12, PA-9c) — the NAMED update-time drift entry point: runs the
                 SV7/MIG-6 report (docs/design.md §11.5) over every config collection.
                 READ-ONLY operator verb; NEVER on the external-actor API (§21.9). Plan
                 step 40 hooks it into `scripts/update-from-upstream.sh` post-update.

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


_COMMANDS = {
    "drift-report": _cmd_drift_report,
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
