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
  render         the FRIENDLY form of `invoke render` (design §21.8, GAP-2): the SAME external-
                 actor render door with flags instead of raw --params-json. Usage: render <item>
                 --workspace W --output-type TYPE [--platform P] [--language L] [--presentation
                 NAME (default plain)] [--root DIR] [--force-reconcile]. Builds the render params
                 and dispatches the SAME handler as `invoke render`, printing the SAME one-line
                 JSON envelope on stdout. render is token-free + deterministic (no live call); only
                 render is reachable here (§21.9 operator-verb exclusion unchanged). Exit 0 =
                 envelope ok; 1 = whole-invocation failure (JSON still emitted); 2 = usage.
  preview        the FRIENDLY plan-only door (design §21, CLI-UX C3a): English-ish flags in, the
                 whole plan + the exact count of paid pieces out — and it SPENDS NOTHING. Runs
                 begin-session with {generate=none, explain=true} via the direct-handler pattern
                 (never registers a session verb; §21.9 stays intact). Usage: preview [--recipe R]
                 [--topic ID ...] [--persona ID ...] [--format ID ...] [--voice ID ...]
                 [--goals ID ...] [--platform P] [--language L] [--output-type T] [--presentation
                 NAME] [--set path=value ...] --workspace W [--root DIR]. Prints the effective
                 settings, the plan (artifact/deliverable ids + warnings), and `spend-scope: N paid
                 artifact(s)`. Exit 0 ok; 1 refusal; 2 usage.
  generate       the FRIENDLY generate door (design §21, CLI-UX C3a). SAME friendly flags as
                 preview; the DEFAULT is a DRY-RUN identical to preview (prints the plan + spend
                 estimate and STOPS, spending nothing). Add --go to DRIVE the plan to completion
                 (begin-session then continue-session generate-next), the ONLY path that spends
                 subscription quota. Add --outline FILE to drive an authored/edited outline; carry
                 its emit HANDLE with --from AID so the C7 drift guard refuses a config drift
                 pre-spend (--allow-drift proceeds on purpose). Direct-handler pattern throughout
                 (never registers a session verb; §21.9 stays intact). Exit 0 ok; 1 refusal / drift
                 refusal / --go spend failure; 2 usage.
  outline        the FRIENDLY two-phase outline door (design §21, CLI-UX C3b). Subcommands:
                   emit  FILE  realize an authored/edited outline as a viewable Format=outline
                               artifact (Tier-A, SPENDS NOTHING) and print its artifact-id — the
                               continuation HANDLE — plus a copy-paste `--from` drive line (a
                               re-emit of the same bytes is the idempotent already-materialized
                               no-op). Exit 0 ok; 1 refusal; 2 usage.
                   drive FILE  ingest the outline and DRIVE the plan to completion. Identical to
                               `generate --outline FILE`: the DEFAULT is a DRY-RUN (spends nothing);
                               add --go to spend, --from AID to guard the config against the emit
                               (C7), --allow-drift to proceed on purpose. Direct-handler pattern
                               (never registers a session verb; §21.9 stays intact). Exit 0 ok; 1
                               refusal / --go spend failure; 2 usage.
  list           the FRIENDLY read-only DISCOVERY door (design §21.3, CLI-UX C3c): enumerate a
                 discovery type by name. Usage: list <type> --workspace W [--filters JSON]
                 [--root DIR]. Types: recipes, voices, lexicons, outlines, codes, deliverables,
                 artifacts, folios, … (run `pipeline list types`). Tier-A, READ-ONLY — spends
                 nothing, mints no token (direct-handler pattern; §21.9 preserved). Prints one
                 `id [provenance path]` row per entry. Exit 0 ok; 1 refusal (unknown type /
                 not-found — never a silent empty); 2 usage.
  get            fetch ONE discovery entry by id (design §21.3, CLI-UX C3c). Usage: get <type>
                 <id> --workspace W [--root DIR]. Tier-A, READ-ONLY. Enumerate-then-match keeps
                 §10 isolation structural; the id-addressed rich get (deliverables/artifacts/
                 folios, per-id isolation + currency detail) stays on `pipeline invoke get`.
                 Exit 0 ok; 1 no such entry; 2 usage.

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


def _cmd_render(argv: list[str]) -> int:
    """render-output-fix (GAP-2): `pipeline render <item> …` — the ERGONOMIC render door.

    The friendly form of `pipeline invoke render`: friendly flags in (a positional artifact-id +
    the render coordinates as options) instead of raw `--params-json`, the SAME behavior out. It
    builds the §21.2 render params dict and hands them to the SAME door
    (`pipeline.api.invoke.main_cli` → `register_render_handler()` + `invoke()`), so it prints the
    SAME one-line JSON envelope on stdout and returns the SAME exit codes: 0 ok · 1 whole-invocation
    failure (JSON still emitted) · 2 usage · 3 a known verb not wired. A THIN ergonomic wrapper — no
    handler logic is duplicated. render is token-free and the default engine is `pass`-strategy, so
    no live subscription/LLM call runs. Only `render` is reachable through this subcommand (the verb
    is HARDCODED); the §21.9 operator-verb exclusion is unchanged — an operator verb is not in
    KNOWN_VERBS and cannot be named here."""
    import argparse
    import json

    from pipeline.api.invoke import main_cli

    parser = argparse.ArgumentParser(
        prog="pipeline render",
        description=(
            "The ergonomic render door (design §21.8, GAP-2): the friendly form of `pipeline "
            "invoke render` — a positional artifact-id + the render coordinates as flags, the SAME "
            "JSON envelope out. render is token-free and deterministic (strategy=pass, no live "
            "call): it mints/serves the deliverable for `item` at the given "
            "platform/language/output-type/presentation and prints one JSON object on stdout."
        ),
    )
    parser.add_argument("item", help="the artifact-id to render (§7.4; the render `item`)")
    parser.add_argument("--workspace", required=True, help="the invoked workspace (§21.1)")
    parser.add_argument("--platform", default=None, help="the target platform slug (§5)")
    parser.add_argument("--language", default=None, help="the target language slug (§5)")
    parser.add_argument(
        "--output-type", required=True, help="the render output-type slug (§17; required)"
    )
    parser.add_argument(
        "--presentation", default="plain", help="the presentation slug (§5.3; default: plain)"
    )
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    parser.add_argument(
        "--force-reconcile",
        action="store_true",
        help="force a re-reconcile → a NEW revision fit, never mutating the old (§21.8)",
    )
    args = parser.parse_args(argv)

    # Build the §21.2 render params from the friendly flags, then hand them to the SAME door as
    # `pipeline invoke render`. Delegating to `main_cli` (rather than re-implementing the
    # register→invoke→print→exit tail) is what guarantees the byte-identical envelope + exit codes
    # 0/1/3 — this stays a thin wrapper, never a second render path. Absent platform/language rides
    # as-omitted (the handler treats absent and null identically → its own per-item block).
    params: dict[str, object] = {
        "item": args.item,
        "output_type": args.output_type,
        "presentation": args.presentation,
    }
    if args.platform is not None:
        params["platform"] = args.platform
    if args.language is not None:
        params["language"] = args.language
    if args.force_reconcile:
        params["force_reconcile"] = True

    return main_cli(
        [
            "render",
            "--workspace",
            args.workspace,
            "--root",
            args.root,
            "--params-json",
            json.dumps(params),
        ]
    )


# ---------------------------------------------------------------------------
# CLI-UX C3a: `pipeline preview` / `pipeline generate` — the FRIENDLY operator door.
#
# English-ish flags in → `normalize(door_class="interactive")` (C2) → canonical begin-session
# params (with `explain=True`, the C1 read side-channel) → the plan-only door via the
# DIRECT-LIBRARY-HANDLER pattern, exactly as `mvp-demo` calls the library directly. We dispatch
# through `invoke.invoke(..., handlers={verb: handler})`: `handlers=` is a PER-CALL override
# (`invoke.py:324`) that NEVER writes the module-global `_VERB_HANDLERS` (R1), so `pipeline invoke
# begin-session` still hits `HandlerNotWired` → exit 3 (§21.9 preserved), AND the call still runs
# the workspace-name containment root gate + Gate-3 id-isolation. A bare `handler(HandlerContext)`
# would skip both — rejected. `preview` and `generate` (without `--go`) construct ONLY the
# begin-session handler: no `continue_session_handler`, so the LIVE runner is never instantiated —
# zero spend by construction. `generate --go` additionally builds the continue-session handler and
# drives `generate-next` to completion; its per-item generation seam (`run_artifact`) is INJECTABLE
# (default `driver._run_artifact`, the live transport) so tests drive the spend path without
# spending live quota.
# ---------------------------------------------------------------------------


def _add_friendly_generate_args(parser: "object") -> None:
    """The shared friendly-flag surface for `preview`/`generate` (C3a). All nine by-name axes are
    REPEATABLE (repeat the flag → the four render axes fan out ONE deliverable each, §5; the five
    content axes fan out more artifacts); `--goals` STACKS into one goal-set; `--set` is the §13.2
    override surface (repeatable). Only `--recipe`/`--workspace` are genuinely single-valued."""
    import argparse

    assert isinstance(parser, argparse.ArgumentParser)
    parser.add_argument("--recipe", default=None, help="recipe id (default: explainer-post, §10)")
    parser.add_argument(
        "--topic", action="append", default=None, metavar="ID", help="a topic id (repeatable)"
    )
    parser.add_argument(
        "--persona", action="append", default=None, metavar="ID", help="a persona id (repeatable)"
    )
    parser.add_argument(
        "--format", action="append", default=None, metavar="ID", help="a format id (repeatable)"
    )
    parser.add_argument(
        "--voice", action="append", default=None, metavar="ID", help="a voice id (repeatable)"
    )
    parser.add_argument(
        "--goals",
        action="append",
        default=None,
        metavar="ID",
        help="a goal id (repeatable → STACKS into one goal-set, §8)",
    )
    parser.add_argument(
        "--platform",
        action="append",
        default=None,
        metavar="ID",
        help="a render platform slug (repeatable → one deliverable each, §5)",
    )
    parser.add_argument(
        "--language",
        action="append",
        default=None,
        metavar="ID",
        help="a render language slug (repeatable → fans out, §5)",
    )
    parser.add_argument(
        "--output-type",
        action="append",
        default=None,
        metavar="ID",
        help="a render output-type slug (repeatable → fans out, §17)",
    )
    parser.add_argument(
        "--presentation",
        action="append",
        default=None,
        metavar="ID",
        help="a presentation slug (repeatable → fans out, §5.3)",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=None,
        metavar="PATH=VALUE",
        help="a run override, e.g. voice.formality=2 or format.tags+=x (repeatable, §13.2)",
    )
    parser.add_argument("--workspace", default=None, help="the invoked workspace (§21.1)")
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )


def _add_outline_handle_args(parser: "object") -> None:
    """CLI-UX C7 (DR-3): the outline continuation-handle drift-guard flags shared by `generate`
    and `outline drive`. `--from` carries the emit-outline HANDLE (the phase-1 artifact-id printed
    by `outline emit`); the server-side guard refuses a real config drift PRE-SPEND. `--allow-drift`
    is the honest "I meant to change it" opt-in that downgrades the block to a recorded warning.
    Both are pure guard inputs — never identity (the driven artifact-id is unchanged by them)."""
    import argparse

    assert isinstance(parser, argparse.ArgumentParser)
    parser.add_argument(
        "--from",
        dest="outline_parent",
        default=None,
        metavar="AID",
        help="the emit-outline HANDLE to verify the driven outline's config against (C7 §21.7)",
    )
    parser.add_argument(
        "--allow-drift",
        action="store_true",
        help="proceed under a config that differs from the emit-time config (downgrades the block)",
    )


def _friendly_from_args(args: "object", *, spend: bool) -> dict:
    """Project the parsed friendly flags into the `normalize()` input mapping (C2). Every axis is
    OMITTED when unset (zero-churn). `explain=True` always — the plan preview is the whole point;
    it is a pure read side-channel (C1) and never an identity input. `spend` governs the
    door-class workspace/idempotency-key policy (a paid `--go` run vs. a free preview/dry-run)."""
    friendly: dict = {"explain": True, "spend": spend}
    single = {
        "recipe": args.recipe,
        "workspace": args.workspace,
        "platforms": args.platform,
        "languages": args.language,
        "output_types": args.output_type,
        "presentations": args.presentation,
    }
    for key, value in single.items():
        if value:
            friendly[key] = value
    multi = {
        "topics": args.topic,
        "personas": args.persona,
        "formats": args.format,
        "voices": args.voice,
        "goals": args.goals,
        "set": args.set,
    }
    for key, value in multi.items():
        if value:
            friendly[key] = value
    # CLI-UX C7 (DR-3): the outline continuation-handle drift-guard inputs. Only `generate` /
    # `outline drive` declare `--from` / `--allow-drift` (never `preview`), so read them defensively
    # — they pass straight through the normalizer to `outline_parent` / `allow_drift` (values-only,
    # never identity).
    outline_parent = getattr(args, "outline_parent", None)
    if outline_parent:
        friendly["outline_parent"] = outline_parent
    if getattr(args, "allow_drift", False):
        friendly["allow_drift"] = True
    return friendly


def _normalize_or_usage(friendly: dict, prog: str) -> "tuple[object | None, int]":
    """Run the C2 normalizer under the interactive door class. A `NormalizeError` (a malformed
    `--set`, a fatal omission) is a pre-engine USAGE error → exit 2; a resolved-but-None workspace
    (nothing to preview/generate against) is likewise a usage error. Returns `(Normalized, 0)` on
    success, else `(None, 2)`."""
    from pipeline.api.normalize import NormalizeError, normalize

    try:
        normalized = normalize(friendly, door_class="interactive")
    except NormalizeError as exc:
        print(f"pipeline {prog}: {exc}", file=sys.stderr)
        return None, 2
    if normalized.workspace is None:
        print(
            f"pipeline {prog}: pass --workspace NAME (there is no workspace to infer)",
            file=sys.stderr,
        )
        return None, 2
    return normalized, 0


def _print_dim(indent: str, label: str, view: dict) -> None:
    """One bound-dimension line: `entry` + the per-attribute winning cascade rung (provenance),
    so the operator sees WHICH layer set each value (the C1 `_dim_view`: entry/values/prov)."""
    if not view:
        return
    prov = ", ".join(f"{k}={v}" for k, v in sorted((view.get("provenance") or {}).items()))
    tail = f"  [{prov}]" if prov else ""
    print(f"{indent}{label:<13}: {view.get('entry')}{tail}")


def _print_plan_preview(workspace: str, recipe: str, summary: dict, *, header: str) -> None:
    """Print the free preview (C3a): the effective compose+render settings (which cascade layer
    set each), the plan (artifact/deliverable ids + advisory warnings), and `spend-scope: N paid
    artifact(s)`. Reads ONLY the C1 `explain` projection carried on the begin-session summary."""
    ids = summary.get("ids") or {}
    context = summary.get("context") or {}
    effective = context.get("effective_settings") or {}
    artifact_ids = list(ids.get("artifact_ids") or [])
    deliverable_ids = list(ids.get("deliverable_ids") or [])
    warnings = list(context.get("warnings") or [])
    spend_scope = context.get("spend_scope", len(artifact_ids))

    print(f"=== {header}: workspace={workspace} recipe={recipe} ===")
    print("effective settings (which cascade layer set each):")
    for aid in artifact_ids:
        print(f"  {aid}")
        view = effective.get(aid) or {}
        for dim in ("topic", "persona", "format", "voice"):
            _print_dim("    ", dim, view.get(dim) or {})
        goals = view.get("goals") or []
        if goals:
            print(f"    {'goals':<13}: " + ", ".join(str(g.get("entry")) for g in goals))
        lexicon = view.get("lexicon")
        if lexicon:
            print(f"    {'lexicon':<13}: {lexicon.get('entry')}")
        render = view.get("render") or {}
        for did in sorted(render):
            print(f"    render {did}:")
            for rdim in ("platform", "language", "output_type", "presentation"):
                _print_dim("      ", rdim, (render[did] or {}).get(rdim) or {})
    print("plan:")
    print(f"  artifact-ids   : {artifact_ids}")
    print(f"  deliverable-ids: {deliverable_ids}")
    print(f"  warnings       : {warnings if warnings else 'none'}")
    print(f"spend-scope: {spend_scope} paid artifact(s)")


def _print_refusal(prog: str, result: dict) -> None:
    """Print a begin/continue-session refusal (a whole-invocation `ok=False`, or a per-item block
    that mints no token) to stderr — the friendly door's exit-1 explanation."""
    envelope = result.get("envelope") or {}
    if not envelope.get("ok", True):
        detail = envelope.get("message") or envelope.get("code") or "whole-invocation failure"
        print(f"pipeline {prog}: refused ({envelope.get('code')}): {detail}", file=sys.stderr)
    for item in result.get("results") or []:
        if item.get("status") in ("block", "warn"):
            code = item.get("code") or "block"
            hint = (item.get("remediation") or {}).get("hint", "")
            print(f"pipeline {prog}: {code} — {hint}", file=sys.stderr)


def _begin_and_preview(
    normalized: "object", root: str, prog: str, *, header: str, adapters: "object | None"
) -> "tuple[dict | None, int]":
    """Run the plan-only begin-session door via the DIRECT-HANDLER pattern and print the free
    preview. Returns `(begin_result, 0)` when a session began (a token was minted — the plan is
    real and printable), else `(None, 1)` on a refusal (whole-invocation `ok=False`, or a per-item
    block that mints no token: not-found / invalid-override / malformed-source / …)."""
    from pipeline.api import invoke as invoke_mod
    from pipeline.api import session

    begin_handler = session.begin_session_handler(adapters=adapters)
    result = invoke_mod.invoke(
        "begin-session",
        normalized.workspace,
        normalized.params,
        handlers={"begin-session": begin_handler},
        root=root,
    )
    if not result["envelope"]["ok"] or "token" not in result:
        _print_refusal(prog, result)
        return None, 1
    for notice in normalized.notices:
        print(notice)
    _print_plan_preview(
        normalized.workspace,
        normalized.params.get("recipe", ""),
        result["results"][0],
        header=header,
    )
    return result, 0


def _drive_generate(
    normalized: "object",
    begin_result: dict,
    root: str,
    *,
    adapters: "object | None",
    run_artifact: "object | None",
) -> int:
    """`generate --go`: drive `continue-session` `generate-next` to completion over the plan cover.
    The per-item generation seam `run_artifact` is INJECTABLE (default `driver._run_artifact`, the
    LIVE transport) so tests exercise the spend path without spending. Loops with `batch_size=all`
    until the cursor consumes the whole cover, or a call makes NO progress (e.g. `plan-stale` echoes
    the token and composes nothing — stop rather than loop forever). A whole-invocation failure
    mid-drive → exit 1; any per-item generation BLOCK → exit 1 (a `--go` spend failure); else 0."""
    from pipeline.api import invoke as invoke_mod
    from pipeline.api import session
    from pipeline.api import token as token_mod

    continue_handler = session.continue_session_handler(
        adapters=adapters, run_artifact=run_artifact
    )
    workspace = normalized.workspace
    token = begin_result["token"]
    planned = set(begin_result["results"][0]["ids"].get("artifact_ids") or [])
    consumed: set[str] = set()
    drive_items: list[dict] = []
    print("\n=== generate --go: driving to completion ===")
    while consumed < planned:
        out = invoke_mod.invoke(
            "continue-session",
            workspace,
            {"action": "generate-next", "batch_size": "all"},
            token=token,
            handlers={"continue-session": continue_handler},
            root=root,
        )
        if not out["envelope"]["ok"]:
            _print_refusal("generate", out)
            return 1
        drive_items.extend(out.get("results") or [])
        token = out.get("token", token)
        advanced = set(
            token_mod.decode(token, expected_workspace=workspace).cursor.get("consumed", [])
        )
        if advanced == consumed:  # no forward progress — never spin
            break
        consumed = advanced

    blocks = 0
    for item in drive_items:
        label = item.get("code") or item.get("status")
        if item.get("status") == "block":
            blocks += 1
            hint = (item.get("remediation") or {}).get("hint", "")
            print(f"  {item.get('item')}: block — {hint}")
        else:
            dids = (item.get("ids") or {}).get("deliverable_ids") or []
            tail = f"  deliverables={dids}" if dids else ""
            print(f"  {item.get('item')}: {label}{tail}")
    print(f"generated {len(drive_items) - blocks} artifact(s); {blocks} block(s).")
    return 1 if blocks else 0


def _outline_coordinate(params: dict) -> dict:
    """Build the ONE DR-3 drive coordinate the outline attaches to, from the normalized
    content-axis picks (the `fanout.coordinate_payload` shape: topic/persona/format/voice/goals).
    An outline drives ONE artifact (`fanout._normalize_outlines`), so each content axis contributes
    its FIRST pick; an unset axis stays `None` — the cascade supplies it and the coordinate MATCHES
    the outline-less fanned coordinate (`SelectionRequest.outline_for`). `format` rides the DRIVE
    pick (None → the real resolved format): the emit side fixes `format=outline`, but that
    difference is excluded from C7's σ guard and is NEVER compared here — C3b carries no
    cross-phase guard (the guard is C7)."""

    def _first(key: str) -> "str | None":
        values = params.get(key)
        return values[0] if values else None

    goal_sets = params.get("goal_sets")
    goals = list(goal_sets[0]) if goal_sets else None
    return {
        "topic": _first("topics"),
        "persona": _first("personas"),
        "format": _first("formats"),
        "voice": _first("voices"),
        "goals": goals,
    }


def _attach_outline_or_usage(normalized: "object", outline_path: str, prog: str) -> int:
    """Read the authored/edited outline file and INJECT it into the normalized begin-session
    params as a single `ingest_outlines` entry — a THIN wrapper over the EXISTING DR-3 ingest leg
    (`session._ingest_outlines` puts the raw text in the pre-compose store, folds it to its bare
    digest, and drives the matching coordinate). No new engine. An unreadable file is a pre-engine
    usage error (exit 2). Returns 0 on success, else 2. `normalized.params` is a mutable dict (the
    frozen `Normalized` field is not reassigned)."""
    from pathlib import Path

    try:
        text = Path(outline_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"pipeline {prog}: cannot read --outline file {outline_path!r}: {exc}", file=sys.stderr
        )
        return 2
    normalized.params["ingest_outlines"] = [
        {"coordinate": _outline_coordinate(normalized.params), "text": text}
    ]
    return 0


def _run_friendly_generate(
    args: "object",
    *,
    go: bool,
    outline_path: "str | None",
    prog: str,
    adapters: "object | None",
    run_artifact: "object | None",
) -> int:
    """The shared C3a generate core, reused by `generate`, `generate --outline`, and `outline
    drive` (the SINGLE normalizer path — `outline drive <f>` == `generate --outline <f>`). Friendly
    flags → `normalize(interactive)` → (optionally) inject the DR-3 outline drive leg → the
    plan-only begin-session preview via the direct-handler pattern. The DEFAULT is a DRY-RUN (no
    `--go` → prints the plan + spend estimate and STOPS, spending nothing — only the begin-session
    handler is constructed). `--go` drives `continue-session generate-next` to completion through
    the INJECTABLE `run_artifact` seam. Exit 0 ok; 1 refusal / --go spend failure; 2 usage."""
    friendly = _friendly_from_args(args, spend=go)
    normalized, code = _normalize_or_usage(friendly, prog)
    if normalized is None:
        return code
    if outline_path is not None:
        code = _attach_outline_or_usage(normalized, outline_path, prog)
        if code:
            return code
    header = f"{prog} --go" if go else f"{prog} (dry-run)"
    result, code = _begin_and_preview(normalized, args.root, prog, header=header, adapters=adapters)
    if result is None:
        return code  # a refusal — nothing to drive
    if not go:
        print("\n(dry-run: nothing spent — re-run with --go to drive the plan to completion)")
        return 0
    return _drive_generate(
        normalized, result, args.root, adapters=adapters, run_artifact=run_artifact
    )


def _cmd_preview(argv: list[str], *, adapters: "object | None" = None) -> int:
    """CLI-UX C3a: `pipeline preview` — the FREE plan-only door. Friendly flags →
    `normalize(interactive)` → begin-session `{generate=none, explain=true}` via the direct-handler
    pattern → print the effective settings, the plan, and `spend-scope: N`. NEVER spends (only the
    begin-session handler is constructed; no continue-session, no live runner). `adapters` is a test
    injection seam. Exit 0 ok; 1 refusal; 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline preview",
        description=(
            "The friendly plan-only door (CLI-UX C3a): English-ish flags in, the whole plan + the "
            "exact count of paid pieces out — and it SPENDS NOTHING (begin-session with "
            "generate=none, explain=true, via the direct-handler pattern; §21.9 preserved)."
        ),
    )
    _add_friendly_generate_args(parser)
    args = parser.parse_args(argv)

    friendly = _friendly_from_args(args, spend=False)
    normalized, code = _normalize_or_usage(friendly, "preview")
    if normalized is None:
        return code
    _result, code = _begin_and_preview(
        normalized, args.root, "preview", header="preview", adapters=adapters
    )
    return code


def _cmd_generate(
    argv: list[str], *, adapters: "object | None" = None, run_artifact: "object | None" = None
) -> int:
    """CLI-UX C3a: `pipeline generate` — the friendly generate door. Friendly flags →
    `normalize(interactive)` → begin-session `{generate=none, explain=true}`. The DEFAULT is a
    DRY-RUN identical to `preview` (prints the plan + spend estimate and STOPS, spending nothing —
    only the begin-session handler is constructed). `--go` DRIVES the plan to completion via
    continue-session `generate-next` (the ONLY spend path). `adapters`/`run_artifact` are test
    injection seams — `run_artifact` is the drive seam (default `driver._run_artifact`, live) so
    tests never spend live quota. Exit 0 ok; 1 refusal / --go spend failure; 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline generate",
        description=(
            "The friendly generate door (CLI-UX C3a). Same flags as `preview`; the DEFAULT is a "
            "DRY-RUN (prints the plan + spend estimate and STOPS, spending nothing). Add --go to "
            "DRIVE the plan to completion (the ONLY path that spends subscription quota). Direct-"
            "handler pattern throughout — never registers a session verb (§21.9 preserved)."
        ),
    )
    _add_friendly_generate_args(parser)
    parser.add_argument(
        "--go",
        action="store_true",
        help="DRIVE the plan to completion (spends quota); omit for a free dry-run preview",
    )
    parser.add_argument(
        "--outline",
        default=None,
        metavar="FILE",
        help=(
            "drive an authored/edited outline file (DR-3 ingest leg); identical to "
            "`pipeline outline drive FILE`"
        ),
    )
    _add_outline_handle_args(parser)
    args = parser.parse_args(argv)

    return _run_friendly_generate(
        args,
        go=args.go,
        outline_path=args.outline,
        prog="generate",
        adapters=adapters,
        run_artifact=run_artifact,
    )


# ---------------------------------------------------------------------------
# CLI-UX C3b: `pipeline outline emit / drive` — the FRIENDLY two-phase outline door.
#
# Thin wrappers over the EXISTING DR-3 legs (no new engine), via the SAME C3a direct-handler
# pattern (`invoke(handlers={verb: handler})`, a PER-CALL override — never `register_*`, so
# §21.9 money-safety holds by construction):
#   - `outline emit <file>` calls the Tier-A `emit-outline` library verb (NO spend, no live
#     runner) to realize an authored/edited outline as a viewable `Format=outline` artifact,
#     and PRINTS the emitted artifact-id — the continuation HANDLE C7's drift guard will consume.
#   - `outline drive <file>` == `generate --outline <file>`: ingest the outline and drive the
#     plan to completion (the paid path, behind `--go`, through the injectable runner).
#
# HARD C3b/C7 BOUNDARY (respected here): NO drift guard, NO `--from`/`--allow-drift` flags, NO
# `outline-config-*` codes, and NO change to the emit-side `source_subset` default — those all
# land in C6/C7. C3b is JUST the two subcommand wrappers; between C3b and C7 the drive path
# carries no cross-phase guard (the intended ordering — the guard is C7).
# ---------------------------------------------------------------------------

_OUTLINE_USAGE = """\
usage: pipeline outline <emit|drive> FILE [friendly flags...]

The FRIENDLY two-phase outline door (design §21, CLI-UX C3b). Thin wrappers over the existing
DR-3 emit-outline / begin-session ingest legs, via the direct-handler pattern (never registers a
session verb; §21.9 stays intact).

subcommands:
  emit  FILE   realize an authored/edited outline as a viewable Format=outline artifact — Tier-A,
               SPENDS NOTHING — and print its artifact-id, the continuation HANDLE, plus a
               copy-paste `--from` drive line. A re-emit of the same bytes is the idempotent
               already-materialized no-op. Options:
               [--recipe R] [--topic ID ...] [--persona ID ...] [--voice ID ...] [--goals ID ...]
               [--set path=value ...] --workspace W [--root DIR].
               Exit 0 ok; 1 refusal (empty/secret outline, unknown selection); 2 usage.
  drive FILE   ingest the outline and DRIVE the plan to completion. Identical to
               `pipeline generate --outline FILE` (the single normalizer path): the DEFAULT is a
               DRY-RUN (prints the plan + spend estimate and STOPS, spending nothing); add --go to
               spend. SAME friendly flags as `generate`, plus [--from AID] (the emit HANDLE — the
               C7 drift guard refuses a config drift pre-spend) and [--allow-drift] (proceed on
               purpose). Exit 0 ok; 1 refusal / drift refusal / --go spend failure; 2 usage.
"""


def _emit_params_from_normalized(normalized: "object", text: str) -> dict:
    """Project the normalized (multi-select) begin-session params into the SINGULAR emit-outline
    coordinate params `session._emit_outline` reads: `recipe` + `topic`/`persona`/`voice` singular
    + `goals` (list) + `overrides` (`format` is FIXED = outline by the handler, so it is never
    passed). An outline emit names ONE coordinate, so each content axis contributes its FIRST pick.
    Passes NO source flags — the emit-side `source_subset` default (B-2) is a server-side handler
    default landing in C7, which this thin wrapper transparently inherits."""
    params = normalized.params
    emit: dict = {"outline": text, "recipe": params["recipe"]}
    for singular, plural in (("topic", "topics"), ("persona", "personas"), ("voice", "voices")):
        values = params.get(plural)
        if values:
            emit[singular] = values[0]
    goal_sets = params.get("goal_sets")
    if goal_sets:
        emit["goals"] = list(goal_sets[0])
    overrides = params.get("overrides")
    if overrides:
        emit["overrides"] = overrides
    return emit


def _emit_and_print(workspace: str, root: str, emit_params: dict, *, outline_file: str) -> int:
    """Dispatch ONE `emit-outline` call via the direct-handler pattern and print the emitted
    artifact-id (the continuation HANDLE) + the copy-paste drive line C7's `--from` guard consumes.
    ONLY `emit_outline_handler` is constructed — no continue-session handler, no live runner is ever
    instantiated (emit is deterministic store I/O, Tier-A). A per-item block (empty/secret outline)
    or a `not-found` selection mints no artifact → a refusal (exit 1); a fresh mint or the
    idempotent `already-materialized` re-emit prints the id (exit 0)."""
    from pipeline.api import invoke as invoke_mod
    from pipeline.api import session

    result = invoke_mod.invoke(
        "emit-outline",
        workspace,
        emit_params,
        handlers={"emit-outline": session.emit_outline_handler()},
        root=root,
    )
    if not result["envelope"]["ok"]:
        _print_refusal("outline emit", result)
        return 1
    item = result["results"][0]
    aid = (item.get("ids") or {}).get("artifact_id")
    if item.get("status") == "block" or aid is None:
        _print_refusal("outline emit", result)
        return 1
    reused = item.get("code") == "already-materialized"
    print(f"=== outline emit: workspace={workspace} recipe={emit_params['recipe']} ===")
    print(f"artifact-id: {aid}")
    if reused:
        print("status     : already-materialized (idempotent re-emit no-op)")
    print(f"handle     : {aid}")
    # C7 (DR-3): the copy-paste drive line — hand-edit the outline, then drive it under the SAME
    # config carrying this handle; the server-side guard refuses pre-spend on a real config drift.
    print(f"— drive with: pipeline generate --outline {outline_file} --from {aid} --go")
    return 0


def _outline_emit(argv: list[str]) -> int:
    """CLI-UX C3b: `pipeline outline emit <file>` — realize an authored outline as a viewable
    artifact. Tier-A, NO spend: builds emit-outline params from the friendly content axes and
    dispatches ONLY the `emit_outline_handler` (direct-handler pattern). Prints the emitted
    artifact-id (the continuation HANDLE). Exit 0 ok; 1 refusal; 2 usage."""
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="pipeline outline emit",
        description=(
            "Realize an authored/edited outline as a viewable Format=outline artifact (CLI-UX C3b, "
            "DR-3 horn (a)): Tier-A, SPENDS NOTHING. Prints the emitted artifact-id — the "
            "continuation HANDLE. A re-emit of the same bytes is the idempotent no-op."
        ),
    )
    parser.add_argument(
        "file", help="the authored outline Markdown file to emit (§15 substance floor)"
    )
    parser.add_argument("--recipe", default=None, help="recipe id (default: explainer-post, §10)")
    parser.add_argument(
        "--topic", action="append", default=None, metavar="ID", help="a topic id (repeatable)"
    )
    parser.add_argument(
        "--persona", action="append", default=None, metavar="ID", help="a persona id (repeatable)"
    )
    parser.add_argument(
        "--voice", action="append", default=None, metavar="ID", help="a voice id (repeatable)"
    )
    parser.add_argument(
        "--goals",
        action="append",
        default=None,
        metavar="ID",
        help="a goal id (repeatable → STACKS into one goal-set, §8)",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=None,
        metavar="PATH=VALUE",
        help="a run override, e.g. voice.formality=2 (repeatable, §13.2)",
    )
    parser.add_argument("--workspace", default=None, help="the invoked workspace (§21.1)")
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)

    try:
        text = Path(args.file).read_text(encoding="utf-8")
    except OSError as exc:
        print(
            f"pipeline outline emit: cannot read outline file {args.file!r}: {exc}", file=sys.stderr
        )
        return 2

    friendly: dict = {"spend": False}  # emit is Tier-A — never a spend verb (no idempotency key)
    for key, value in (("recipe", args.recipe), ("workspace", args.workspace)):
        if value:
            friendly[key] = value
    for key, value in (
        ("topics", args.topic),
        ("personas", args.persona),
        ("voices", args.voice),
        ("goals", args.goals),
        ("set", args.set),
    ):
        if value:
            friendly[key] = value

    normalized, code = _normalize_or_usage(friendly, "outline emit")
    if normalized is None:
        return code
    emit_params = _emit_params_from_normalized(normalized, text)
    return _emit_and_print(normalized.workspace, args.root, emit_params, outline_file=args.file)


def _outline_drive(
    argv: list[str], *, adapters: "object | None" = None, run_artifact: "object | None" = None
) -> int:
    """CLI-UX C3b: `pipeline outline drive <file>` — ingest an authored/edited outline and drive it
    to completion. Identical to `generate --outline <file>` (the single normalizer path): default
    DRY-RUN (no spend), `--go` to drive `generate-next` through the injectable runner. Exit 0 ok;
    1 refusal / --go spend failure; 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline outline drive",
        description=(
            "Ingest an authored/edited outline and DRIVE the plan to completion (CLI-UX C3b, DR-3 "
            "ingest leg). Identical to `pipeline generate --outline FILE`: the DEFAULT is a "
            "DRY-RUN (prints the plan + spend estimate and STOPS, spending nothing); add --go. "
            "Direct-handler pattern throughout — never registers a session verb (§21.9 preserved)."
        ),
    )
    parser.add_argument(
        "file", help="the authored/edited outline Markdown file to drive (DR-3 ingest leg)"
    )
    _add_friendly_generate_args(parser)
    parser.add_argument(
        "--go",
        action="store_true",
        help="DRIVE the plan to completion (spends quota); omit for a free dry-run preview",
    )
    _add_outline_handle_args(parser)
    args = parser.parse_args(argv)

    return _run_friendly_generate(
        args,
        go=args.go,
        outline_path=args.file,
        prog="outline drive",
        adapters=adapters,
        run_artifact=run_artifact,
    )


def _cmd_outline(
    argv: list[str], *, adapters: "object | None" = None, run_artifact: "object | None" = None
) -> int:
    """CLI-UX C3b: `pipeline outline <emit|drive>` — the FRIENDLY two-phase outline door.

    `outline emit <file>` realizes a HAND-AUTHORED/edited outline as a viewable Format=outline
    artifact (Tier-A, NO spend) and prints its artifact-id — the continuation HANDLE. `outline
    drive <file>` (== `generate --outline <file>`) ingests the outline and drives the plan to
    completion (the paid path, behind `--go`). Thin wrappers over the EXISTING DR-3 legs via the
    C3a direct-handler pattern — never registers a session verb (§21.9). Exit 0 ok; 1 refusal /
    --go spend failure; 2 usage."""
    if not argv or argv[0] in ("-h", "--help"):
        print(_OUTLINE_USAGE, end="")
        return 0
    sub, rest = argv[0], argv[1:]
    if sub == "emit":
        return _outline_emit(rest)
    if sub == "drive":
        return _outline_drive(rest, adapters=adapters, run_artifact=run_artifact)
    print(f"pipeline outline: unknown subcommand {sub!r} (known: emit, drive)", file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# CLI-UX C3c: `pipeline list <type>` / `pipeline get <type> <id>` — the FRIENDLY read-only
# DISCOVERY door (design §21.3). The operator-facing shell for the discovery `list`/`get` layer:
# enumerate a closed discovery type by name (recipes, voices, lexicons, outlines, codes,
# deliverables, …) or fetch one entry. Tier-A, READ-ONLY — no spend, no token, no idempotency key,
# no live runner. Wired via the SAME C3a/C3b direct-handler pattern (`invoke(handlers={"list":
# <discovery handler>})`, a PER-CALL override that never writes the module-global `_VERB_HANDLERS`),
# so §21.9 money-safety holds by construction: `pipeline invoke begin-session` stays exit 3 and
# these subcommands register nothing.
#
# WHY `get` enumerates via the `list` handler (not the discovery `get` VERB): invoke's Gate-3
# isolation (a durable §10 boundary) refuses any `id` that is not a workspace-materialized
# artifact/folio, so a registry NAME (`clear-explainer`) or a bare outline digest resolves nowhere
# → `isolation-violation`. Enumerate-then-match keeps isolation STRUCTURAL (the enumeration only
# ever sees THIS workspace's store + the framework registry) without weakening any gate. The
# genuine id-addressed `get` (deliverables/artifacts/folios, with per-id isolation + the rich
# currency detail) stays reachable through `pipeline invoke get`.
# ---------------------------------------------------------------------------


def _discovery_list_handler() -> "object":
    """Construct the Tier-A discovery `list` handler the SAME way the production wiring does
    (`discovery.register_discovery_handlers` / `session.py`): the default currency resolver + the
    single-source `session.CONTINUE_ACTIONS` action vocabulary (so `list actions` is correct).
    READ-ONLY — computes no spend, mints no token; passed as a PER-CALL `handlers=` override that
    never writes the module-global `_VERB_HANDLERS` (§21.9). Importing `session` here registers
    NOTHING (handler registration is explicit-only, never at import)."""
    from pipeline.api import discovery, session

    return discovery.list_handler(action_vocab=session.CONTINUE_ACTIONS)


def _invoke_discovery_list(
    type_name: str, workspace: str, root: str, filters: "object | None" = None
) -> dict:
    """Dispatch ONE discovery `list` call via the direct-handler pattern (reused by `list` + `get`,
    both of which enumerate a type). Returns the raw `{envelope, results}` invoke output."""
    from pipeline.api import invoke as invoke_mod

    params: dict[str, object] = {"type": type_name}
    if filters is not None:
        params["filters"] = filters
    return invoke_mod.invoke(
        "list", workspace, params, handlers={"list": _discovery_list_handler()}, root=root
    )


def _discovery_row_tail(context: dict) -> str:
    """The compact `{provenance, path}` tail for a discovery row — appended when the record carries
    them (registry/outline entries), else empty (meta rows like `codes` print just the id)."""
    parts = []
    if context.get("provenance") is not None:
        parts.append(f"provenance={context['provenance']}")
    if context.get("path") is not None:
        parts.append(f"path={context['path']}")
    return ("  " + " ".join(parts)) if parts else ""


def _cmd_list(argv: list[str]) -> int:
    """CLI-UX C3c: `pipeline list <type> [--filters JSON]` — enumerate a discovery type by name
    (design §21.3). Tier-A, READ-ONLY (no spend, no token). Prints one `id [provenance path]` row
    per entry. An unknown type is a `not-found` refusal (exit 1, never a silent empty). Exit 0 ok;
    1 refusal; 2 usage."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        prog="pipeline list",
        description=(
            "Enumerate a discovery type by name (design §21.3): recipes, voices, lexicons, "
            "outlines, codes, deliverables, artifacts, folios, … (see `pipeline list types`). "
            "Tier-A, READ-ONLY — spends nothing, mints no token. Direct-handler pattern (§21.9 "
            "preserved)."
        ),
    )
    parser.add_argument(
        "type", help="the discovery type to enumerate (see `pipeline list types`)"
    )
    parser.add_argument("--workspace", required=True, help="the invoked workspace (§21.1)")
    parser.add_argument(
        "--filters",
        default=None,
        metavar="JSON",
        help="§13.2 filters as JSON: a {field: value} map or a [{path,op,value}] pred list",
    )
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)

    filters: object | None = None
    if args.filters is not None:
        try:
            filters = json.loads(args.filters)
        except json.JSONDecodeError as exc:
            print(f"pipeline list: --filters is not valid JSON: {exc}", file=sys.stderr)
            return 2

    result = _invoke_discovery_list(args.type, args.workspace, args.root, filters)
    if not result["envelope"]["ok"]:
        _print_refusal("list", result)
        return 1
    rows = result["results"]
    if any(r.get("status") == "block" for r in rows):  # unknown type → not-found (no silent empty)
        _print_refusal("list", result)
        return 1
    print(f"=== list {args.type}: {len(rows)} entry(ies) — workspace={args.workspace} ===")
    for r in rows:
        print(f"  {r.get('item')}{_discovery_row_tail(r.get('context') or {})}")
    return 0


def _cmd_get(argv: list[str]) -> int:
    """CLI-UX C3c: `pipeline get <type> <id>` — fetch ONE discovery entry by id (design §21.3).
    Tier-A, READ-ONLY. Enumerates the type via the `list` handler and selects the matching id
    (invoke's Gate-3 isolation refuses a registry NAME / bare outline digest through the `get`
    VERB — see the section note); the id-addressed rich `get` stays on `pipeline invoke get`. Prints
    the entry's fields. Exit 0 ok; 1 refusal / no such entry; 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline get",
        description=(
            "Fetch one discovery entry by id (design §21.3): e.g. `get voices clear-explainer`. "
            "Tier-A, READ-ONLY — spends nothing. Enumerate-then-match keeps §10 isolation "
            "structural; the id-addressed rich `get` is on `pipeline invoke get`."
        ),
    )
    parser.add_argument("type", help="the discovery type (see `pipeline list types`)")
    parser.add_argument("id", help="the entry id to fetch")
    parser.add_argument("--workspace", required=True, help="the invoked workspace (§21.1)")
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)

    result = _invoke_discovery_list(args.type, args.workspace, args.root)
    if not result["envelope"]["ok"]:
        _print_refusal("get", result)
        return 1
    rows = result["results"]
    if any(r.get("status") == "block" for r in rows):  # unknown type → not-found refusal
        _print_refusal("get", result)
        return 1
    match = next((r for r in rows if r.get("item") == args.id), None)
    if match is None:
        print(
            f"pipeline get: no {args.type} entry with id {args.id!r} in workspace "
            f"{args.workspace!r} (§21.3)",
            file=sys.stderr,
        )
        return 1
    print(f"=== get {args.type} {args.id} — workspace={args.workspace} ===")
    context = match.get("context") or {}
    for key in sorted(context):
        print(f"  {key}: {context[key]}")
    return 0


_COMMANDS = {
    "drift-report": _cmd_drift_report,
    "ssot": _cmd_ssot,
    "demo-thread": _cmd_demo_thread,
    "mvp-demo": _cmd_mvp_demo,
    "invoke": _cmd_invoke,
    "render": _cmd_render,
    "preview": _cmd_preview,
    "generate": _cmd_generate,
    "outline": _cmd_outline,
    "list": _cmd_list,
    "get": _cmd_get,
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
