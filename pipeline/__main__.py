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

  demo-thread    (plan step 28, ★ FIRST END-TO-END OUTPUT) — drive ONE full thread end to
                 end against a LOCAL demo instance (`instance/defaults.yaml` +
                 `workspaces/<ws>/`): ground the client graph → resolve/bind → compose (a
                 LIVE subscription writer call) → reconcile → serialize → persist the
                 artifact + deliverable + bindings, advancing both SSOT row kinds (§2.1
                 stages 1–5). A BUILD MILESTONE, not the MVP (§25). Spends subscription
                 quota (the compose call is real). Writes only under the workspace store;
                 the client graph is read-only (rule 1).

  mvp-demo       (plan step 39, ★ THE MVP DEMONSTRATION, §25) — drive the ONE scripted §25
                 acceptance scenario against a LOCAL demo instance, exercising ALL NINE
                 dimensions interacting end to end: grounding with the full selection grammar
                 (§6), one run override (§12), compose→reconcile→serialize across an internal
                 AND an external-side target (§14–§17), both review gates (§19), a typed folio
                 with a typed + an untyped member (§9), emit-manifest (§21.5), the sequential
                 AND parallel consumption modes (§21.6/§22), and the SSOT projection (§24). The
                 SAME callable the hermetic `tests/test_mvp_scenario.py` drives — here with the
                 REAL transport (LIVE compose + review calls; subscription quota) and the MVP
                 fail-safe currency resolver (never the unsafe §21.9 default). Writes only under
                 the workspace store; the client graph is read-only (rule 1).

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
  demo-thread    drive one full end-to-end thread (design §2.1 stages 1–5, plan step 28).
                 A LIVE writer call (subscription quota); a build milestone, not the MVP
                 (§25). Options: --workspace NAME (required) · --root DIR (default .) ·
                 --now YYYY-MM-DD (grounding clock; default today) · --model NAME (writer
                 model; default: the CLI's own). Exit 0 ok; 1 thread failure; 2 usage.
  mvp-demo       drive THE §25 MVP scenario (all nine dimensions, interacting; plan step 39).
                 LIVE compose + review calls (subscription quota). Options: --workspace NAME
                 (required) · --root DIR (default .) · --now YYYY-MM-DD (grounding clock;
                 default today) · --model NAME (writer model; default: the CLI's own).
                 Prerequisites: the workspace must declare the source pool + the §25 topics +
                 a styled `documentation` presentation (see docs/design.md §25 / the step-39
                 report). Exit 0 ok; 1 scenario failure; 2 usage.
  invoke         the external-actor API door (design §21, GAP-2): one verb invocation → one
                 JSON envelope {envelope, results, [token]} on stdout — the n8n Execute Command
                 door AND the human door. Usage: invoke <verb> --workspace W --params-json JSON
                 [--token-json JSON] [--pins-json JSON] [--root DIR]. Safe verbs wired: render
                 (mint) + fetch-by-id (retrieve); operator verbs stay unreachable (§21.9). Exit
                 0 = envelope ok; 1 = whole-invocation failure (JSON still emitted); 2 = usage;
                 3 = a known verb not wired. n8n CAVEAT: Execute Command is off-by-default in
                 n8n v2.0 and unavailable on n8n Cloud (self-hosted only; a cloud orchestrator
                 needs the deferred HTTP shim, docs/known-issues.md DR-1).

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


def _cmd_demo_thread(argv: list[str]) -> int:
    """Plan step 28: `scripts/pipeline demo-thread` — the FIRST END-TO-END OUTPUT.

    Drives one full thread (ground → resolve/bind → compose LIVE → reconcile → serialize
    → persist + SSOT advance, design §2.1 stages 1–5) against a local demo instance and
    prints the transcript. A build milestone, NOT the MVP (§25). The compose call spends
    subscription quota. Exit 0 on a real deliverable, 1 on a thread failure, 2 on usage.
    """
    import argparse
    from datetime import date

    from pipeline.driver import DriverError, run_thread

    parser = argparse.ArgumentParser(
        prog="pipeline demo-thread",
        description=(
            "Drive ONE full thread end to end (design §2.1 stages 1–5): ground the client "
            "graph, resolve/bind, compose via a LIVE subscription writer call, reconcile, "
            "serialize to an internal target, and persist the artifact + deliverable + "
            "bindings, advancing both SSOT row kinds. A build milestone (§25), not the MVP."
        ),
    )
    parser.add_argument("--workspace", required=True, help="the demo workspace (e.g. mvp-demo)")
    parser.add_argument("--root", default=".", help="the framework repo root (default: cwd)")
    parser.add_argument(
        "--now",
        default=None,
        metavar="YYYY-MM-DD",
        help="grounding clock override (default: today; injected at the edge, never ambient)",
    )
    parser.add_argument(
        "--model", default=None, help="writer model to pin (default: the CLI's own default)"
    )
    args = parser.parse_args(argv)

    try:
        now = date.fromisoformat(args.now) if args.now else date.today()
    except ValueError:
        print(f"pipeline demo-thread: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2

    print(f"=== demo-thread: workspace={args.workspace} root={args.root} now={now} ===")
    try:
        result = run_thread(
            root=args.root,
            workspace=args.workspace,
            now=now,
            model=args.model,
            log=lambda line: print(line),
        )
    except DriverError as exc:
        print(f"\nBLOCKED: {exc}", file=sys.stderr)
        return 1

    _print_thread_report(result)
    return 0


def _print_thread_report(result: object) -> None:
    """Render the completed thread's transcript summary (the report the maintainer reads)."""
    from pipeline.driver import ThreadResult

    assert isinstance(result, ThreadResult)
    print("\n=== THREAD COMPLETE ===")
    print(f"workspace       : {result.workspace}")
    print(f"recipe          : {result.recipe}")
    print(f"plan_hash       : {result.plan_hash}")
    print(f"source_subset   : {list(result.source_subset)}")
    print(f"source_commit   : {dict(result.source_commit)}")
    print("nine axes:")
    for axis, value in result.axes.items():
        print(f"  {axis:<14}: {value}")
    for art in result.artifacts:
        print(f"\nartifact-id     : {art.artifact_id}")
        print(f"  query         : {art.query!r}")
        print(f"  facts         : {art.fact_count} grounded, {art.published_fact_count} published")
        print(f"  record        : {art.artifact_record_path}")
        print(
            f"  binding       : digest {art.composition_digest[:16]}… "
            f"verify={'VERIFIED' if art.composition_verified else 'MISMATCH'}"
        )
        print(f"  writer cost   : {art.transport_cost_usd}")
        for dv in art.deliverables:
            print(f"  deliverable-id: {dv.deliverable_id}")
            print(f"    fitted-id   : {dv.fitted_id}")
            print(
                f"    reconcile   : {dv.reconcile_strategy} "
                f"({'no-op' if dv.reconcile_is_noop else 'live'})"
            )
            print(f"    writer/side : {dv.writer}/{dv.side}")
            print(f"    bytes       : {dv.bytes_path} ({dv.byte_count} bytes)")
            print(f"    sha256      : {dv.sha256}")
            print("    --- output preview (first 600 bytes) ---")
            for pline in dv.preview.splitlines():
                print(f"    | {pline}")
            print("    --- end preview ---")
    print(f"\nSSOT CSV        : {result.ssot_csv_path}")
    print("SSOT rows (both kinds — the derived convenience, §24):")
    for line in result.ssot_report.splitlines():
        print(f"  {line}")


def _cmd_mvp_demo(argv: list[str]) -> int:
    """Plan step 39: `scripts/pipeline mvp-demo` — ★ THE MVP DEMONSTRATION (§25).

    Drives the ONE scripted §25 acceptance scenario (all nine dimensions, interacting) via the
    shared `pipeline.mvpdemo.run_mvp_scenario` callable — the SAME callable the hermetic CI test
    drives, but here with the LIVE transport (`runner=None`/`review_runner=None` → the real
    subscription compose + review calls) and the real graphify source adapter.

    GATE-2 (§21.9): the currency resolver is supplied EXPLICITLY as the MVP fail-safe resolver
    (`MvpFailSafeCurrencyResolver`), NEVER left to default to `discovery.DefaultCurrencyResolver`
    — the live path can never reach the unsafe `except → stored_digest` partial detector.

    Exit 0 on a completed scenario, 1 on a scenario failure, 2 on usage. Spends subscription
    quota (compose + review are real); writes only under the workspace store (the client graph
    is read-only, rule 1).
    """
    import argparse
    from datetime import date

    from pipeline.api.render import DefaultRenderEngine
    from pipeline.api.session import _default_adapters
    from pipeline.driver import DriverError
    from pipeline.mvpdemo import MvpFailSafeCurrencyResolver, run_mvp_scenario

    parser = argparse.ArgumentParser(
        prog="pipeline mvp-demo",
        description=(
            "Drive THE §25 MVP scenario (all nine dimensions, interacting) against a local demo "
            "instance: grounding with the full selection grammar, one run override, "
            "compose→reconcile→serialize across an internal AND an external target, both review "
            "gates, a typed folio (typed + untyped member), emit-manifest, the sequential AND "
            "parallel consumption modes, and the SSOT projection. LIVE compose + review calls."
        ),
    )
    parser.add_argument("--workspace", required=True, help="the demo workspace (e.g. mvp-demo)")
    parser.add_argument("--root", default=".", help="the framework repo root (default: cwd)")
    parser.add_argument(
        "--now",
        default=None,
        metavar="YYYY-MM-DD",
        help="grounding clock override (default: today; injected at the edge, never ambient)",
    )
    parser.add_argument(
        "--model", default=None, help="writer model to pin (default: the CLI's own default)"
    )
    args = parser.parse_args(argv)

    try:
        now = date.fromisoformat(args.now) if args.now else date.today()
    except ValueError:
        print(f"pipeline mvp-demo: --now must be YYYY-MM-DD, got {args.now!r}", file=sys.stderr)
        return 2

    print(f"=== mvp-demo (§25): workspace={args.workspace} root={args.root} now={now} ===")
    try:
        report = run_mvp_scenario(
            root=args.root,
            workspace=args.workspace,
            adapters=_default_adapters(),  # the real graphify adapter (LIVE grounding + pin)
            runner=None,  # None → the real subscription WRITER transport (LIVE compose)
            review_runner=None,  # None → the real subscription REVIEW transport (LIVE §19)
            render_engine=DefaultRenderEngine(),  # real reconcile/serialize legs
            # GATE-2: explicit fail-safe resolver, NEVER the unsafe discovery default.
            currency_resolver=MvpFailSafeCurrencyResolver(),
            now=now,
            model=args.model,
            log=lambda line: print(line),
        )
    except DriverError as exc:
        print(f"\nBLOCKED: {exc}", file=sys.stderr)
        return 1

    _print_mvp_report(report)
    return 0


def _print_mvp_report(report: object) -> None:
    """Render the §25 clause→evidence checklist the maintainer reads (the acceptance transcript)."""
    from pipeline.mvpdemo import MvpReport

    assert isinstance(report, MvpReport)
    print("\n=== ★ MVP SCENARIO COMPLETE (§25) ===")
    print(f"workspace       : {report.workspace}")
    print("nine axes (interacting):")
    for axis, value in report.axes.items():
        print(f"  {axis:<12}: {value}")
    g = report.grounding
    print("\n§6 grounding    :")
    print(f"  selection     : {g['selection']}")
    print(f"  survivors     : {g['survivor_instances']}")
    print(f"  published     : {g['published_fact_count']} EXTRACTED fact(s)")
    print(f"  conflict      : {g['conflict_subject']} → {g['conflict_claims']}")
    print(f"  strategy      : {g['conflict_strategy']}")
    o = report.override
    print(f"\n§12 override    : {o['attribute']} {o['without_override']} → {o['with_override']}")
    s = report.styled
    print("\n§5.3 B1 styled  :")
    print(f"  plain  did    : {s['plain_deliverable_id']} vars={s['plain_variables']}")
    print(f"  styled did    : {s['styled_deliverable_id']} vars={s['styled_variables']}")
    e = report.external
    print("\n§17 external    :")
    print(f"  {e['deliverable_id']}")
    print(f"  side={e['side']} writer={e['writer']} stripped={e['provenance_stripped']}")
    rv = report.reviews
    print(
        f"\n§19 reviews     : artifact={rv['artifact_verdict']} "
        f"deliverable={rv['deliverable_verdict']}"
    )
    seq = report.sequential
    print("\n§21.6 sequential:")
    print(f"  artifacts     : {seq['artifact_ids']}")
    print(f"  cursor        : {seq['cursor_progression']}")
    par = report.parallel
    print("\n§22 parallel    :")
    print(f"  artifacts     : {par['artifact_ids']} (waves={par['wave_kinds']})")
    print(
        f"  sweep         : before={par['sweep_before']['complete']} "
        f"partial={par['sweep_partial']['complete']} after={par['sweep_after']['complete']}"
    )
    fo = report.folio
    print("\n§9 folio        :")
    print(f"  {fo['folio_id']} ({fo['folio_type']})")
    print(f"  typed member  : {fo['typed_member']} role={fo['typed_member_role']}")
    print(f"  untyped member: {fo['untyped_member']} role={fo['untyped_member_role']}")
    m = report.manifest
    print(f"\n§21.5 manifest  : {m['path']} rows={m['row_count']} kinds={m['payload_kinds']}")
    print(f"\n§24 SSOT        : {report.ssot['csv_path']}")
    for line in report.ssot["derive_state"].splitlines():
        print(f"  {line}")


def _cmd_invoke(argv: list[str]) -> int:
    """Plan step 32 / GAP-2: `pipeline invoke <verb> …` — the external-actor API door (§21).

    Routes straight to the api-layer CLI (`pipeline.api.invoke.main_cli`) so the `python -m
    pipeline invoke …` module form works identically to the `scripts/pipeline invoke …` shim
    path (the shim already `exec`s `python -m pipeline.api.invoke`; both share the SAME wired
    verbs and exit codes). This is BOTH the n8n Execute Command door and the human door: one
    verb invocation → one JSON envelope on stdout. Only the safe stateless verbs are wired
    (`render` + `fetch-by-id`); operator verbs are structurally unreachable (§21.9). Exit codes
    are `main_cli`'s: 0 ok · 1 whole-invocation failure (JSON still emitted) · 2 usage · 3 a
    known verb not wired."""
    from pipeline.api.invoke import main_cli

    return main_cli(argv)


_COMMANDS = {
    "drift-report": _cmd_drift_report,
    "ssot": _cmd_ssot,
    "demo-thread": _cmd_demo_thread,
    "mvp-demo": _cmd_mvp_demo,
    "invoke": _cmd_invoke,
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
