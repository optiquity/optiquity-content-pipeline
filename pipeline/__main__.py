"""`python -m pipeline` — the module entry point behind the `scripts/pipeline` shim (T8).

Step 7 lands the stub only. Subcommands are added by their owning plan steps
(e.g. `drift-report` at step 12, `ssot derive-state` at step 22); until then every
subcommand is refused loudly rather than silently accepted.
"""

import sys

_USAGE = """\
usage: pipeline [-h|--help] [--version] <command> [args...]

The optiquity-content-pipeline operator CLI (framework mechanism).

No subcommands are implemented yet: this is the plan step-7 scaffolding stub.
Subcommands land with their owning plan steps (see docs/design.md and the build plan).
"""


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code (0 ok, 2 usage error)."""
    from pipeline import __version__

    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(_USAGE, end="")
        return 0
    if args[0] == "--version":
        print(f"pipeline {__version__}")
        return 0
    print(
        f"pipeline: unknown command {args[0]!r} (no subcommands are implemented yet)",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
