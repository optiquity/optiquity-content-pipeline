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
  docs           LOCAL/operator doc generators (authoring layer D12/D13; never an HTTP door,
                 §21.9 preserved). Subcommand:
                   attributes  regenerate docs/reference/attributes.md — a reference of what
                               every framework registry attribute MEANS (its schema `definition:`
                               prose, verbatim) + type/floor/definition_version. Walks
                               pipeline.lint.REGISTRY_ROOTS only (framework-only, no instance/
                               client content); deterministic (sorted, no clock); guarded by a
                               byte-equality drift test. Options: --root DIR (default: the
                               package's repo root). Exit 0 ok; 2 usage.
  recipe         the FRIENDLY recipe authoring/derive door (authoring layer C2b, design §8).
                 LOCAL Tier-A file write — never an invoke verb / HTTP door (§21.9 preserved:
                 a recipe write cannot spend quota or mint a token). Subcommand:
                   new ID   author (or --from-derive) one schema-conforming recipe file from the
                            unified grammar: by-name axis PICKS (--topic/--persona/--format/
                            --voice/--goals + --platform/--language/--output-type/--presentation;
                            mention REPLACES the slot's set, repeat to accumulate), --set
                            path=value TWEAKS a configured value, --unset PATH CLEARS an axis slot
                            (1 seg) or a value binding (2 seg). --from BASE seeds from an existing
                            recipe and MATERIALIZES a standalone derived file (never base+delta;
                            an unknown base refuses loudly). Provenance is inferred over every
                            binding: a framework-only recipe homes public (recipes/<id>.md); a
                            client (x-) binding REFUSES into public and homes under
                            workspaces/<ws>/recipes/x-<id>.md (--workspace W). Refuse-if-exists
                            unless --force (TTY-gated prompt; headless fails fast). Options:
                            --from BASE · axis picks · --set · --unset · --workspace W · --root DIR
                            · --force. Exit 0 ok; 1 refusal (bad edit / provenance-refused /
                            unknown base / non-slug id / refuse-if-exists); 2 usage.
  entry          the FRIENDLY dimension-entry scaffolder (authoring layer C3, design D11).
                 LOCAL Tier-A file write — never an invoke verb / HTTP door (§21.9 preserved).
                 Subcommand:
                   new DIMENSION ID   scaffold ONE new entry (persona/format/voice/…) from a
                            schema-conforming, self-documenting skeleton: the envelope + every
                            attribute at its schema floor + each attribute's `definition:` prose
                            as inline `#`-comments (the same guidance `docs attributes` surfaces).
                            A floor-only entry lints GREEN unedited. --workspace W homes an
                            instance entry (x--prefixed, provenance instance) under
                            workspaces/<W>/<dimension>/x-<id>.md; without --workspace it writes a
                            framework-default candidate (<dimension>/<id>.md, provenance framework)
                            for a deliberate human commit. `entry new topic` REQUIRES --workspace
                            (topics are workspace editorial data). Refuse-if-exists unless --force
                            (TTY-gated prompt; headless fails fast). Options: --workspace W ·
                            --root DIR · --force. Exit 0 ok; 1 refusal (bad dimension / non-slug id
                            / topic-without-workspace / refuse-if-exists); 2 usage.
  workspace      the FRIENDLY local workspace lifecycle (design §23) over the self-contained
                 users/<user>/workspaces/<workspace>/ layout. LOCAL Tier-A file ops — never an
                 invoke verb / HTTP door (§21.9 preserved). Subcommands:
                   new WORKSPACE   seed ONE new client workspace under
                            users/<user>/workspaces/<workspace>/
                            by copying the shared framework blueprint templates/workspace/ (the
                            friendly form of `cp -R templates/workspace users/<user>/workspaces/
                            <ws>`). --user is REQUIRED (§23 isolation prefix); the user namespace is
                            auto-created on demand (a brand-new user home is announced so a mistyped
                            --user is visible). Refuse-if-exists unless --force; --force NEVER
                            overwrites an existing file (non-destructive — tops up MISSING blueprint
                            files only, never deletes client data). --zone Z targets one concrete
                            zone (default: default); a brand-new zone is auto-created + announced (a
                            mistyped --zone is visible). Options: --user U (required) · --zone Z ·
                            --root DIR · --force. Exit 0 ok; 1 refusal (bad name / refuse-if-exists
                            / missing blueprint); 2 usage (no subcommand / missing --user).
                   list            READ-ONLY: list workspaces as <user>/<zone>/<workspace> with a
                            topic-count + has-output summary. With --user, one user's workspaces;
                            without it, ALL users (scan users/*/zones/*/workspaces/*). --zone Z
                            FILTERS to one zone (default: all zones). A missing/empty users/ prints
                            "no workspaces found" (exit 0), never a traceback. Options: --user U ·
                            --zone Z · --root DIR. Exit 0 ok; 1 refusal (bad --user).
                   delete WORKSPACE  DESTRUCTIVE, SAFE-BY-DEFAULT: remove ONE workspace. --user is
                            REQUIRED; --zone Z picks the zone (default: default). Refuse-by-default
                            — interactive TYPE the workspace name to confirm (a mismatch aborts);
                            headless pass --yes. A workspace holding generated output is refused
                            even with --yes unless --force is ALSO passed. Never deletes through a
                            symlink; removes only the validated contained dir (users/<user>/ +
                            zones/<zone>/workspaces/ survive). Options: --user U (required) · --zone
                            Z · --yes · --force · --root DIR. Exit 0 ok; 1 refusal (bad name /
                            non-existent / symlink / unconfirmed / has-output); 2 usage (no
                            subcommand / missing --user).
  user           the FRIENDLY per-user namespace setup (design §23). LOCAL Tier-A file op — never an
                 invoke verb / HTTP door (§21.9 preserved). Subcommand:
                   new USER   create the empty per-user namespace users/<user>/workspaces/ (the
                            extensible per-user home) WITHOUT a workspace. <user> is a §23
                            lowercase-safe segment. Refuse-if-exists unless --force (a safe no-op;
                            deletes nothing). Options: --root DIR · --force. Exit 0 ok; 1 refusal
                            (bad user / refuse-if-exists); 2 usage.
  zone           the FRIENDLY per-zone lifecycle (design §23) over users/<user>/zones/<zone>/
                 workspaces/ — a zone groups a user's workspaces (it sits between user and
                 workspace). LOCAL Tier-A file ops — never an invoke verb / HTTP door (§21.9
                 preserved). Subcommands:
                   new ZONE   create ONE new zone users/<user>/zones/<zone>/workspaces/ (the
                            per-zone workspace home). --user is REQUIRED (§23 prefix); the user
                            namespace is auto-created on demand (a brand-new user home is announced
                            so a mistyped --user is visible). Refuse-if-exists unless --force (a
                            safe no-op; deletes nothing). Options: --user U (required) · --root DIR
                            · --force. Exit 0 ok; 1 refusal (bad name / refuse-if-exists); 2 usage
                            (no subcommand / missing --user).
                   list            READ-ONLY: list zones as <user>/<zone> with a workspace count.
                            With --user, one user's zones; without it, ALL users (scan
                            users/*/zones/*). A missing/empty users/ prints "no zones found"
                            (exit 0), never a traceback. Options: --user U · --root DIR. Exit 0 ok;
                            1 refusal (bad --user).
                   delete ZONE  DESTRUCTIVE, RECURSIVE, SAFE-BY-DEFAULT: remove ONE zone AND every
                            workspace it contains. --user is REQUIRED. Refuse-by-default —
                            interactive TYPE the zone name to confirm (a mismatch aborts); headless
                            pass --yes. STRICTER because recursive: if ANY contained workspace
                            holds generated output the whole zone is refused even with --yes unless
                            --force is ALSO passed. Never deletes through a symlink; removes only
                            the validated contained zone dir (users/<user>/ survives). Options:
                            --user U (required) · --yes · --force · --root DIR. Exit 0 ok; 1 refusal
                            (bad name / non-existent / symlink / unconfirmed / has-output); 2 usage
                            (no subcommand / missing --user).
  sources        the OUT-OF-BAND acquisition maintenance door (design §6; sources P2). LOCAL Tier-A:
                 it fetches FREE HTTP and writes the LOCAL sealed cache; it NEVER spends quota,
                 mints a token, or touches the paid job path (§21.9 preserved; no paid-drive flag /
                 session / external door). Subcommand:
                   ingest WORKSPACE  acquire the workspace's feed sources (sources/feeds/<id>.yaml)
                            fetch → normalize → dedup + θ-gate → SEAL into the sealed cache under
                            users/<user>/workspaces/<ws>/sources/cache/<namespace>/ (gitignored; the
                            rule-1 carve-out) and advance HEAD. Idempotent: a re-ingest of unchanged
                            content is a no-op. --user is REQUIRED (§23 prefix); --source ID picks
                            one feed (default: all). Prints per-feed facts-cached + θ-stop reason +
                            bytes/requests ($0 model spend). Options: --user U (required) · --source
                            ID · --root DIR. Exit 0 ok; 1 refusal (bad name / unknown feed / busy
                            namespace); 2 usage (no subcommand / missing --user).

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
    parser.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
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

    print(
        f"=== demo-thread: user={args.user} workspace={args.workspace} "
        f"root={args.root} now={now} ==="
    )
    try:
        result = run_thread(
            root=args.root,
            user=args.user,
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
    print(f"user            : {result.user}")
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
    parser.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
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

    print(
        f"=== mvp-demo (§25): user={args.user} workspace={args.workspace} "
        f"root={args.root} now={now} ==="
    )
    try:
        report = run_mvp_scenario(
            root=args.root,
            user=args.user,
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
    parser.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
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
            "--user",
            args.user,
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
        "--user",
        default=None,
        help="the owning user (§23 isolation prefix; required whenever --workspace is given)",
    )
    # S4 (§21.9/§23-Z4) zone-required guard: SENTINEL default None = "omitted". An OMITTED --zone
    # resolves DEFAULT_ZONE for a single-zone user, but REFUSES loudly (listing the zones) for a
    # user who owns >1 zone — a spend verb never silently picks a zone. An EXPLICIT --zone (even
    # `default`) is honored verbatim (`resolve_spend_zone`). NOT DEFAULT_ZONE here — the default
    # must be distinguishable from an explicit `--zone default`.
    parser.add_argument(
        "--zone",
        default=None,
        metavar="ZONE",
        help=(
            "the §23/Z4 zone to spend in (users/<user>/zones/<zone>/workspaces/<W>/). OMIT for the "
            "friendly default when you own one zone; a user with MORE THAN ONE zone MUST name one "
            "here (the door refuses-and-lists rather than silently pick `default`, §21.9/S4)"
        ),
    )
    parser.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd)",
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
        "user": args.user,
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


def _resolve_spend_zone_or_refuse(
    root: str, user: str, zone_arg: "str | None", prog: str
) -> "tuple[str | None, int]":
    """S4 (§21.9) zone-required guard for the FRIENDLY SPEND door — the ONE chokepoint `preview`,
    `generate`, and `outline drive` funnel through (never copy-pasted per verb). Delegates the rule
    to `workspacescaffold.resolve_spend_zone` (which REUSES the `list_zones` scan): an EXPLICIT
    `--zone` (even `default`) is honored; an OMITTED `--zone` resolves `DEFAULT_ZONE` for a 0/1-zone
    user but is a LOUD, PRE-spend refusal for a user who owns >1 zone. On refusal it prints the
    zone-required message + a copy-paste `--zone <name>` line per available zone and returns
    `(None, 1)` (nothing composed, nothing spent); on success `(resolved_zone, 0)`."""
    from pipeline import workspacescaffold

    try:
        zone = workspacescaffold.resolve_spend_zone(root, user, zone_arg)
    except workspacescaffold.SpendZoneError as exc:
        print(f"pipeline {prog}: {exc}", file=sys.stderr)
        for name in exc.zones:
            print(f"  --zone {name}", file=sys.stderr)
        print(
            f"pipeline {prog}: re-run naming one of the zones above with --zone (nothing spent)",
            file=sys.stderr,
        )
        return None, 1
    return zone, 0


def _print_dim(indent: str, label: str, view: dict) -> None:
    """One bound-dimension line: `entry` + the per-attribute winning cascade rung (provenance),
    so the operator sees WHICH layer set each value (the C1 `_dim_view`: entry/values/prov)."""
    if not view:
        return
    prov = ", ".join(f"{k}={v}" for k, v in sorted((view.get("provenance") or {}).items()))
    tail = f"  [{prov}]" if prov else ""
    print(f"{indent}{label:<13}: {view.get('entry')}{tail}")


def _print_plan_preview(
    workspace: str, user: str, recipe: str, summary: dict, *, header: str, zone: str
) -> None:
    """Print the free preview (C3a): the effective compose+render settings (which cascade layer
    set each), the plan (artifact/deliverable ids + advisory warnings), and `spend-scope: N paid
    artifact(s)`. Reads ONLY the C1 `explain` projection carried on the begin-session summary. The
    header ECHOES the RESOLVED `zone` (§23/Z4/S4) so the operator can confirm which zone this run
    spends in (the friendly `default`, or the one they named with --zone)."""
    ids = summary.get("ids") or {}
    context = summary.get("context") or {}
    effective = context.get("effective_settings") or {}
    artifact_ids = list(ids.get("artifact_ids") or [])
    deliverable_ids = list(ids.get("deliverable_ids") or [])
    warnings = list(context.get("warnings") or [])
    spend_scope = context.get("spend_scope", len(artifact_ids))

    print(
        f"=== {header}: user={user} workspace={workspace} zone={zone} recipe={recipe} ==="
    )
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
    normalized: "object",
    root: str,
    prog: str,
    *,
    header: str,
    adapters: "object | None",
    zone: str,
) -> "tuple[dict | None, int]":
    """Run the plan-only begin-session door via the DIRECT-HANDLER pattern and print the free
    preview. `zone` is the S4-resolved spend zone (§23/Z4) threaded into `invoke()` so the plan
    resolves + the store is built in the right zone, and echoed in the preview header. Returns
    `(begin_result, 0)` when a session began (a token was minted — the plan is real and printable),
    else `(None, 1)` on a refusal (whole-invocation `ok=False`, or a per-item block that mints no
    token: not-found / invalid-override / malformed-source / …)."""
    from pipeline.api import invoke as invoke_mod
    from pipeline.api import session

    begin_handler = session.begin_session_handler(adapters=adapters)
    result = invoke_mod.invoke(
        "begin-session",
        normalized.workspace,
        normalized.user,
        normalized.params,
        handlers={"begin-session": begin_handler},
        root=root,
        zone=zone,
    )
    if not result["envelope"]["ok"] or "token" not in result:
        _print_refusal(prog, result)
        return None, 1
    for notice in normalized.notices:
        print(notice)
    _print_plan_preview(
        normalized.workspace,
        normalized.user,
        normalized.params.get("recipe", ""),
        result["results"][0],
        header=header,
        zone=zone,
    )
    return result, 0


def _drive_generate(
    normalized: "object",
    begin_result: dict,
    root: str,
    *,
    adapters: "object | None",
    run_artifact: "object | None",
    zone: str,
) -> int:
    """`generate --go`: drive `continue-session` `generate-next` to completion over the plan cover.
    The per-item generation seam `run_artifact` is INJECTABLE (default `driver._run_artifact`, the
    LIVE transport) so tests exercise the spend path without spending. `zone` is the S4-resolved
    spend zone (§23/Z4) — the SAME value `_begin_and_preview` used, threaded into every
    `continue-session` `invoke()` so the drive spends in exactly the plan's zone. Loops
    with `batch_size=all` until the cursor consumes the whole cover, or a call makes NO progress
    (e.g. `plan-stale` echoes the token and composes nothing — stop rather than loop forever). A
    whole-invocation failure mid-drive → exit 1; any per-item generation BLOCK → exit 1 (a `--go`
    spend failure); else 0."""
    from pipeline.api import invoke as invoke_mod
    from pipeline.api import session
    from pipeline.api import token as token_mod

    continue_handler = session.continue_session_handler(
        adapters=adapters, run_artifact=run_artifact
    )
    workspace = normalized.workspace
    user = normalized.user
    token = begin_result["token"]
    planned = set(begin_result["results"][0]["ids"].get("artifact_ids") or [])
    consumed: set[str] = set()
    drive_items: list[dict] = []
    print("\n=== generate --go: driving to completion ===")
    while consumed < planned:
        out = invoke_mod.invoke(
            "continue-session",
            workspace,
            user,
            {"action": "generate-next", "batch_size": "all"},
            token=token,
            handlers={"continue-session": continue_handler},
            root=root,
            zone=zone,
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


def _save_selection(
    result: dict, normalized: "object", root: str, selection_id: str, *, force: bool, prog: str
) -> int:
    """CLI-UX C5b: serialize + write this run's OWN fan-out as a replayable selection file.

    Reads the floor-faithful per-deliverable variant capture off the SAME begin-session resolve
    (`context["selection_variants"]` — never a second `resolve_plan`); `base` is the recipe
    REFERENCE the run used and the run's shared `--set` tweaks persist as each variant's `values`
    (§12.5). A provenance/overwrite refusal is exit 1 — a client (`x-`) binding homes under
    `workspaces/<ws>/selections/`, never the public root (rule 4). Returns 0 on success."""
    from pipeline import authoring

    context = result["results"][0].get("context") or {}
    variants = context.get("selection_variants") or []
    if not variants:
        print(
            f"pipeline {prog}: --save-selection: this plan resolves no deliverable to save — a "
            "saved selection replays a fan-out (select a --platform, §7.4)",
            file=sys.stderr,
        )
        return 1
    base = normalized.params.get("recipe", "")
    values = normalized.params.get("overrides") or None
    try:
        target = authoring.write_selection(
            root,
            selection_id,
            base,
            variants,
            values=values,
            user=normalized.user,
            workspace=normalized.workspace,
            force=force,
        )
    except authoring.AuthoringError as exc:
        print(f"pipeline {prog}: {exc}", file=sys.stderr)
        return 1
    print(f"\nsaved selection {target.selection_id!r} ({target.provenance}) -> {target.path}")
    return 0


def _attach_selection_or_usage(
    args: "object", normalized: "object", selection_id: str, prog: str
) -> int:
    """CLI-UX C5c: LOAD a saved selection and DRIVE it 1:1 — inject the saved base recipe REFERENCE,
    the EXPLICIT per-artifact render map, and the run's shared value tweaks into the normalized
    begin-session params, REPLACING a fresh fan-out. A saved selection fully specifies the run, so
    combining --selection with any content/render axis flag, `--set`, or an explicit `--recipe` is a
    pre-engine usage error (exit 2): they would re-expand the curated set the selection exists to
    replay. A missing / malformed / boundary-refused selection is exit 1 (a loud refusal). Money-
    safety is untouched — the injected params flow through the SAME begin-session preview door, so a
    selection previews (spends nothing) by default and drives only under --go. `normalized.params`
    is a mutable dict (the frozen `Normalized` field is not reassigned). Returns 0 on success."""
    from pipeline import authoring

    conflicting = [
        flag
        for flag, value in (
            ("--recipe", getattr(args, "recipe", None)),
            ("--topic", getattr(args, "topic", None)),
            ("--persona", getattr(args, "persona", None)),
            ("--format", getattr(args, "format", None)),
            ("--voice", getattr(args, "voice", None)),
            ("--goals", getattr(args, "goals", None)),
            ("--platform", getattr(args, "platform", None)),
            ("--language", getattr(args, "language", None)),
            ("--output-type", getattr(args, "output_type", None)),
            ("--presentation", getattr(args, "presentation", None)),
            ("--set", getattr(args, "set", None)),
        )
        if value
    ]
    if conflicting:
        print(
            f"pipeline {prog}: --selection drives a SAVED fan-out 1:1 — do not also pass "
            f"{conflicting} (they would re-expand the curated set); drive the selection alone",
            file=sys.stderr,
        )
        return 2
    try:
        base, variants, values = authoring.load_selection(
            args.root, selection_id, user=normalized.user, workspace=normalized.workspace
        )
    except authoring.AuthoringError as exc:
        print(f"pipeline {prog}: --selection: {exc}", file=sys.stderr)
        return 1
    normalized.params["recipe"] = base
    normalized.params["render_map"] = variants
    if values:
        normalized.params["overrides"] = dict(values)
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
    # S4 (§21.9): resolve the spend zone up front — a user who owns >1 zone MUST name --zone, else
    # a LOUD pre-spend refusal listing the zones (never a silent `default`). Checked BEFORE the
    # selection/outline attach + begin-session so nothing is composed or spent on refusal.
    zone, code = _resolve_spend_zone_or_refuse(args.root, normalized.user, args.zone, prog)
    if zone is None:
        return code
    selection_id = getattr(args, "selection", None)
    if selection_id is not None and outline_path is not None:
        print(
            f"pipeline {prog}: --selection and --outline are mutually exclusive (a saved selection "
            "already fixes the fan-out)",
            file=sys.stderr,
        )
        return 2
    if selection_id is not None:
        # C5c: DRIVE a saved selection 1:1 — inject the saved base + render map into params.
        code = _attach_selection_or_usage(args, normalized, selection_id, prog)
        if code:
            return code
    if outline_path is not None:
        code = _attach_outline_or_usage(normalized, outline_path, prog)
        if code:
            return code
    header = f"{prog} --go" if go else f"{prog} (dry-run)"
    result, code = _begin_and_preview(
        normalized, args.root, prog, header=header, adapters=adapters, zone=zone
    )
    if result is None:
        return code  # a refusal — nothing to drive
    # C5b: `--save-selection ID` persists the run's OWN fan-out (works WITH and WITHOUT --go — the
    # plan resolved on the preview path too). Defensive getattr: the shared core also serves
    # `outline drive`, which declares no `--save-selection` (mirrors the outline-handle reads).
    save_selection = getattr(args, "save_selection", None)
    force = bool(getattr(args, "force", False))
    if not go:
        if save_selection is not None:
            # Save the previewed plan without spending (§21.9: only the begin-session handler was
            # built; the writer is a pure file write, never a session/spend verb).
            save_code = _save_selection(
                result, normalized, args.root, save_selection, force=force, prog=prog
            )
            if save_code:
                return save_code
        print("\n(dry-run: nothing spent — re-run with --go to drive the plan to completion)")
        return 0
    drive_code = _drive_generate(
        normalized, result, args.root, adapters=adapters, run_artifact=run_artifact, zone=zone
    )
    if drive_code == 0 and save_selection is not None:
        return _save_selection(
            result, normalized, args.root, save_selection, force=force, prog=prog
        )
    return drive_code


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
    # S4 (§21.9): a multi-zone user must name --zone (else refuse-and-list) before begin-session.
    zone, code = _resolve_spend_zone_or_refuse(args.root, normalized.user, args.zone, "preview")
    if zone is None:
        return code
    _result, code = _begin_and_preview(
        normalized, args.root, "preview", header="preview", adapters=adapters, zone=zone
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
    parser.add_argument(
        "--save-selection",
        default=None,
        metavar="ID",
        help=(
            "SAVE this run's fan-out as a replayable selection file selections/ID.md (§8, "
            "authoring D4) — works with or without --go. A client (x-) content/render binding "
            "homes under workspaces/<workspace>/selections/ (never the public root)"
        ),
    )
    parser.add_argument(
        "--selection",
        default=None,
        metavar="ID",
        help=(
            "DRIVE a saved selection selections/ID.md (or workspaces/<workspace>/selections/ for "
            "an x- id, §8/authoring D4) 1:1 — replays the EXACT saved fan-out, no re-expansion. "
            "Preview by default (spends nothing); add --go to drive. Mutually exclusive with the "
            "axis flags / --set / --recipe / --outline (a saved selection already fixes the run)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing saved-selection file (default: refuse; --save-selection only)",
    )
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


def _emit_and_print(
    workspace: str, user: str, root: str, emit_params: dict, *, outline_file: str
) -> int:
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
        user,
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
    print(
        f"=== outline emit: user={user} workspace={workspace} "
        f"recipe={emit_params['recipe']} ==="
    )
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
        "--user",
        default=None,
        help="the owning user (§23 isolation prefix; required whenever --workspace is given)",
    )
    parser.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/workspaces/<workspace>/ (default: cwd)",
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
    for key, value in (("recipe", args.recipe), ("workspace", args.workspace), ("user", args.user)):
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
    return _emit_and_print(
        normalized.workspace, normalized.user, args.root, emit_params, outline_file=args.file
    )


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
    type_name: str, workspace: str, user: str, root: str, filters: "object | None" = None
) -> dict:
    """Dispatch ONE discovery `list` call via the direct-handler pattern (reused by `list` + `get`,
    both of which enumerate a type). Returns the raw `{envelope, results}` invoke output."""
    from pipeline.api import invoke as invoke_mod

    params: dict[str, object] = {"type": type_name}
    if filters is not None:
        params["filters"] = filters
    return invoke_mod.invoke(
        "list", workspace, user, params, handlers={"list": _discovery_list_handler()}, root=root
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
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
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

    result = _invoke_discovery_list(args.type, args.workspace, args.user, args.root, filters)
    if not result["envelope"]["ok"]:
        _print_refusal("list", result)
        return 1
    rows = result["results"]
    if any(r.get("status") == "block" for r in rows):  # unknown type → not-found (no silent empty)
        _print_refusal("list", result)
        return 1
    print(
        f"=== list {args.type}: {len(rows)} entry(ies) — "
        f"user={args.user} workspace={args.workspace} ==="
    )
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
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
    parser.add_argument(
        "--root", default=".", help="framework repo root → workspaces/<workspace>/ (default: cwd)"
    )
    args = parser.parse_args(argv)

    result = _invoke_discovery_list(args.type, args.workspace, args.user, args.root)
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


def _cmd_docs(argv: list[str]) -> int:
    """Authoring-layer D12/D13: `pipeline docs <subcommand>` — LOCAL operator doc generators.

    LOCAL/operator only (never an HTTP `_VERB_HANDLERS` verb; §21.9 preserved): regenerates a
    committed framework reference doc from the code. Subcommand:
      attributes  regenerate `docs/reference/attributes.md` from the framework registry schemas
                  (`pipeline.lint.REGISTRY_ROOTS` — framework-only, no client/instance content).
    Deterministic + framework-only; a CI drift test asserts the committed file byte-for-byte.
    Exit 0 ok; 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline docs",
        description=(
            "Regenerate a committed framework reference doc from the code (authoring layer D12; "
            "LOCAL/operator only, never an HTTP door). Subcommands: attributes."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    p_attr = sub.add_parser(
        "attributes",
        help="regenerate docs/reference/attributes.md from the framework registry schemas",
        description=(
            "Regenerate docs/reference/attributes.md: a reference of what every framework "
            "registry attribute MEANS (its schema `definition:` prose, verbatim) and its type, "
            "floor default, and definition_version. Walks pipeline.lint.REGISTRY_ROOTS only "
            "(framework-only — no instance/client content); deterministic (sorted, no clock). A "
            "byte-equality CI test guards it against un-regenerated edits."
        ),
    )
    p_attr.add_argument(
        "--root",
        default=None,
        help="framework repo root (default: the installed package's own repo root)",
    )
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help(sys.stderr)
        return 2

    from pipeline import attrdoc

    out_path = attrdoc.write_attributes_doc(args.root)
    schemas = attrdoc.iter_documented_schemas(args.root)
    attr_count = sum(len(schema.attributes) for _, schema in schemas)
    print(
        f"pipeline docs attributes: wrote {attrdoc.DOC_RELPATH} "
        f"({len(schemas)} collections, {attr_count} attributes) — {out_path}"
    )
    return 0


# ---------------------------------------------------------------------------
# Authoring layer C2b: `pipeline recipe new` — the FRIENDLY recipe authoring/derive door.
#
# The FIRST consumer of the C2a authoring core (`pipeline.authoring`): friendly flags in → the
# PICK/TWEAK/CLEAR edit-set (`build_edit_set`) → the `base ⊕ edits` merge (`merge_bundle`) → the
# provenance-homed, overwrite-guarded, schema-conforming recipe file out (`write_recipe`). Every
# hard part — the edit-verb router, the merge, the serializer, `infer_provenance`/
# `resolve_recipe_target`, and the overwrite helper — lives in C2a and is REUSED here, never
# re-implemented; this subcommand is only the argparse surface + the `--from` base loader.
#
# MONEY-SAFETY (§21.9): `recipe new` is a LOCAL Tier-A file write. It NEVER registers an invoke
# verb, never touches `_VERB_HANDLERS`, and never dispatches through the invoke door — so it cannot
# spend subscription quota or mint a token. A recipe NAME never enters `build_artifact_preimage`
# (D10/W4), so a saved recipe run resolves byte-identically to the same flags inlined.
# ---------------------------------------------------------------------------

#: The `recipe new` by-name PICK flags (argparse dest → recipe slot) — the unified grammar (§2).
#: Content axes are SINGULAR here (a recipe binds ONE per content dimension, §8); the four render
#: axes carry the plural SET slot; `--goals` stacks the goal-set. Every flag is REPEATABLE and
#: mention → REPLACE the slot's set (`build_edit_set`/`merge_bundle` own that semantics).
_RECIPE_PICK_SLOTS: dict[str, str] = {
    "topic": "topic",
    "persona": "persona",
    "format": "format",
    "voice": "voice",
    "goals": "goals",
    "platform": "platforms",
    "language": "languages",
    "output_type": "output_types",
    "presentation": "presentations",
}


def _recipe_error_types() -> tuple:
    """The typed authoring / edit / base-load refusals `recipe new` maps to a loud exit 1 (never
    a stack trace): a bad edit-set or provenance/overwrite refusal (`AuthoringError`), a malformed
    `--set` path (`overrides.OverrideError`), a typed-wrong binding the serializer rejects
    (`ValueValidationError`), an unknown/invalid `--from` base (`m1.M1Error`), or a malformed base
    FILE — the strict loader's envelope refusal (`entries.EntryError`) OR its closed-schema /
    version-stamp refusal (`schema.SchemaValidationError`, which covers `UndeclaredAttributeError`
    for an `extends:`/undeclared frontmatter key, and `schema.VersionStampError`). These
    schema-layer classes are bare `ValueError` subclasses (NOT `EntryError`s), so they must be
    named explicitly here or a malformed base would escape uncaught. The tuple stays specific so a
    genuine bug is never swallowed."""
    from pipeline import authoring, entries, m1, overrides
    from pipeline.attrtypes import ValueValidationError
    from pipeline.schema import SchemaValidationError, VersionStampError

    return (
        authoring.AuthoringError,
        overrides.OverrideError,
        ValueValidationError,
        m1.M1Error,
        entries.EntryError,
        SchemaValidationError,
        VersionStampError,
    )


def _load_base_bundle(
    root: str, base_id: str, user: "str | None", workspace: "str | None"
) -> dict:
    """`--from BASE`: load an existing recipe's explicitly-SET slots (its bundle) — loud on unknown.

    Locates the base exactly as M1 does (`recipes/<id>.md`, workspace-shadowed for an `x-` id,
    innermost wins — §12.1) and returns `authoring.bundle_from_entry` (the C2a partial the merge
    seeds from). Reference-faithful: ONLY the base's SET slots seed the merge — unset floors stay
    unset so they fall through the cascade, and the derived file MATERIALIZES the merged bundle as
    a standalone recipe (never a base+delta reference). An unknown/invalid base id is a loud
    `m1.UnknownEntryError` (never a silent seed-from-nothing); a malformed base file raises the
    strict loader's typed refusal — an ENVELOPE error (`entries.EntryError`) OR a closed-schema /
    version-stamp error (`schema.SchemaValidationError`/`VersionStampError`, e.g. a base carrying
    an undeclared `extends:` key). ALL of these are named in `_recipe_error_types()`, so the caller
    turns every one into a clean `pipeline recipe new: …` exit-1 (never a traceback). READ-ONLY
    toward the tree."""
    from pathlib import Path

    from pipeline import authoring, entries, m1
    from pipeline.attrtypes import AttrTypeSpec, ValueValidationError, validate_value
    from pipeline.layout import registry_dir
    from pipeline.workspace_name import DEFAULT_ZONE, workspace_path

    try:  # the SSOT §7.4 slug validator (the one `_require_slug` wraps) — blocks a traversal id
        validate_value(AttrTypeSpec(kind="ref"), base_id)
    except ValueValidationError as exc:
        raise m1.UnknownEntryError(
            f"unknown-entry: --from {base_id!r} is not a §7.4 recipe id slug ([a-z0-9-], 1-40 "
            "chars, no leading/trailing '-'); an unknown base is an error, never silent (§11.1)"
        ) from exc

    # §23: a `--from` base named under a workspace needs its owning user BEFORE the eager join —
    # a clean typed refusal (mirroring `authoring.resolve_recipe_target`), never a raw `TypeError`
    # traceback from `workspace_path(..., None, ...)` (LOUD-and-clean; never a `users/None/` path).
    if workspace is not None and user is None:
        raise authoring.AuthoringError(
            f"invalid-authoring: --from base {base_id!r} under a --workspace requires a --user + "
            "--workspace home (instance config lives under users/<user>/workspaces/<client>/, "
            "rule 2/§10)"
        )
    root_path = Path(root)
    filename = f"{base_id}{entries.ENTRY_SUFFIX}"
    shared = registry_dir(root_path, authoring.RECIPE_COLLECTION) / filename
    local = (
        workspace_path(
            root_path, user, workspace, authoring.RECIPE_COLLECTION, filename, zone=DEFAULT_ZONE
        )
        if workspace is not None
        else None
    )
    candidates = [p for p in (shared, local) if p is not None and p.is_file()]
    if not candidates:
        looked = [str(shared)] + ([str(local)] if local is not None else [])
        raise m1.UnknownEntryError(
            f"unknown-entry: recipes/{base_id!r} does not resolve — an unknown --from base is an "
            f"error, never silent (§11.1); looked at: {looked}"
        )
    schema = authoring.load_recipe_schema()
    entry = entries.load_entry(candidates[-1], schema)  # innermost (workspace) shadows shared
    return authoring.bundle_from_entry(entry)


def _cmd_recipe(argv: list[str]) -> int:
    """Authoring layer C2b: `pipeline recipe new ID [--from BASE] [picks] [--set] [--unset]` —
    author (or derive) a schema-conforming recipe file from friendly flags (the C2a core).

    A LOCAL Tier-A file write: build the PICK/TWEAK/CLEAR edit-set, merge it over an EMPTY base
    (or the `--from` base), infer provenance over every binding, home the file (public
    `recipes/<id>.md`, or `workspaces/<ws>/recipes/x-<id>.md` for a client binding — REFUSED into
    public), overwrite-guard it, and print the exact id + path. NEVER registers an invoke verb /
    touches `_VERB_HANDLERS` / hits the invoke door (§21.9). Exit 0 ok; 1 refusal (bad edit /
    provenance-refused / unknown base / non-slug id / refuse-if-exists); 2 usage."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline recipe",
        description=(
            "The friendly recipe authoring/derive door (authoring layer C2b, design §8): the "
            "first consumer of the C2a authoring core. LOCAL Tier-A file write — never an invoke "
            "verb / HTTP door (§21.9). Subcommand: new."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    new = sub.add_parser(
        "new",
        help="author (or --from-derive) one schema-conforming recipe file from friendly flags",
        description=(
            "Author (or derive with --from) one schema-conforming recipe file (design §8) from "
            "the unified grammar: by-name axis PICKS (mention REPLACES the slot's set, repeat to "
            "accumulate), --set path=value TWEAKS a configured value (values only), --unset PATH "
            "CLEARS an axis slot (1 segment) or a value binding (2 segments). Provenance is "
            "inferred over every binding: framework-only homes public (recipes/<id>.md); a client "
            "(x-) binding REFUSES into public and homes under workspaces/<ws>/recipes/x-<id>.md. "
            "Refuse-if-exists unless --force. NEVER spends quota (never an invoke verb; §21.9)."
        ),
    )
    new.add_argument("id", help="the recipe id to write (§7.4 slug; the filename stem)")
    new.add_argument(
        "--from",
        dest="base",
        default=None,
        metavar="BASE",
        help="seed from an existing recipe → a standalone derived file (loud on unknown)",
    )
    new.add_argument(
        "--topic", action="append", default=None, metavar="ID", help="bind a topic (repeatable)"
    )
    new.add_argument(
        "--persona", action="append", default=None, metavar="ID", help="bind a persona (repeatable)"
    )
    new.add_argument(
        "--format", action="append", default=None, metavar="ID", help="bind a format (repeatable)"
    )
    new.add_argument(
        "--voice", action="append", default=None, metavar="ID", help="bind a voice (repeatable)"
    )
    new.add_argument(
        "--goals",
        action="append",
        default=None,
        metavar="ID",
        help="bind a goal (repeatable → STACKS the goal-set, §8)",
    )
    new.add_argument(
        "--platform",
        action="append",
        default=None,
        metavar="ID",
        help="pin a render platform (repeatable → REPLACES the set, §5)",
    )
    new.add_argument(
        "--language",
        action="append",
        default=None,
        metavar="ID",
        help="pin a render language (repeatable → REPLACES the set, §5)",
    )
    new.add_argument(
        "--output-type",
        action="append",
        default=None,
        metavar="ID",
        help="pin a render output-type (repeatable → REPLACES the set, §17)",
    )
    new.add_argument(
        "--presentation",
        action="append",
        default=None,
        metavar="ID",
        help="pin a render presentation (repeatable → REPLACES the set, §5.3)",
    )
    new.add_argument(
        "--set",
        action="append",
        default=None,
        metavar="PATH=VALUE",
        help="tweak a configured value, e.g. voice.formality=2 or format.tags+=x (repeatable)",
    )
    new.add_argument(
        "--unset",
        action="append",
        default=None,
        metavar="PATH",
        help="clear an axis slot (1 seg: voice) or a value binding (2 seg: voice.formality)",
    )
    new.add_argument(
        "--workspace",
        default=None,
        help="the workspace home for a client (x-) recipe (§10); framework recipes need none",
    )
    new.add_argument(
        "--user",
        default=None,
        help="the owning user (§23) for a client (x-) recipe home; required with --workspace",
    )
    new.add_argument(
        "--root", default=".", help="framework repo root → recipes/<id>.md (default: cwd)"
    )
    new.add_argument(
        "--force", action="store_true", help="overwrite an existing recipe file (default: refuse)"
    )
    args = parser.parse_args(argv)

    if args.subcommand != "new":
        parser.print_usage(sys.stderr)
        print("pipeline recipe: a subcommand is required (known: new)", file=sys.stderr)
        return 2

    from pipeline import authoring

    picks: dict[str, list[str]] = {}
    for dest, slot in _RECIPE_PICK_SLOTS.items():
        values = getattr(args, dest)
        if values:
            picks[slot] = values

    try:
        edits = authoring.build_edit_set(
            picks=picks, set_entries=args.set or [], unset=args.unset or []
        )
        base_bundle: dict = (
            _load_base_bundle(args.root, args.base, args.user, args.workspace)
            if args.base is not None
            else {}
        )
        bundle = authoring.merge_bundle(base_bundle, edits)
        target = authoring.write_recipe(
            args.root, args.id, bundle, user=args.user, workspace=args.workspace, force=args.force
        )
    except _recipe_error_types() as exc:
        print(f"pipeline recipe new: {exc}", file=sys.stderr)
        return 1

    seeded = f" (derived from {args.base!r})" if args.base is not None else ""
    print(
        f"pipeline recipe new: wrote recipe {target.recipe_id!r} [{target.provenance}]{seeded} "
        f"— {target.path}"
    )
    return 0


# ---------------------------------------------------------------------------
# Authoring layer C3: `pipeline entry new` — the FRIENDLY dimension-entry scaffolder.
#
# The second consumer of the C2a authoring core (`pipeline.authoring`), via the thin
# `pipeline.entryscaffold` leaf: a dimension token + id in → a schema-conforming, self-
# documenting floor skeleton out (envelope + every attribute at `Schema.defaults()` + the
# `definition:` prose as inline `#`-comments). Every hard part — slug validation
# (`authoring._require_slug`), the overwrite guard (`authoring.ensure_writable`), and the pinned
# frontmatter dumper (`authoring._dump_yaml`) — is REUSED from C2a, never re-implemented; this
# subcommand is only the argparse surface. The scaffold LINTS GREEN unedited (floor-only is valid
# by construction, D11/W5).
#
# MONEY-SAFETY (§21.9): `entry new` is a LOCAL Tier-A file write. It NEVER registers an invoke
# verb, never touches `_VERB_HANDLERS`, and never dispatches through the invoke door — so it
# cannot spend subscription quota or mint a token. An entry NAME never enters the artifact
# preimage; a scaffolded entry is inert to identity until a run selects it (D10).
# ---------------------------------------------------------------------------


def _entry_error_types() -> tuple:
    """The typed refusals `entry new` maps to a loud exit 1 (never a stack trace): a bad
    dimension / non-slug id / topic-without-workspace / overwrite refusal / missing-schema root
    (`authoring.AuthoringError`); a workspace-name escape (`workspace_name.WorkspaceNameError`);
    or a malformed dimension schema at the root (`schema.SchemaError`/`SchemaValidationError` —
    bare `ValueError` subclasses that must be named explicitly). The tuple stays specific so a
    genuine bug is never swallowed."""
    from pipeline import authoring
    from pipeline.schema import SchemaError, SchemaValidationError
    from pipeline.workspace_name import WorkspaceNameError

    return (
        authoring.AuthoringError,
        WorkspaceNameError,
        SchemaError,
        SchemaValidationError,
    )


def _cmd_entry(argv: list[str]) -> int:
    """Authoring layer C3: `pipeline entry new DIMENSION ID [--workspace W] [--force]` — scaffold
    ONE new dimension entry from a schema-conforming floor skeleton (the C2a core, via
    `pipeline.entryscaffold`).

    A LOCAL Tier-A file write: validate the dimension against the real dimension set
    (`m1.DIMENSION_COLLECTIONS`), slug-validate the id, home the file by `--workspace`
    (instance x- under the workspace, or a public framework-default candidate), overwrite-guard
    it, and print the exact id + path. NEVER registers an invoke verb / touches `_VERB_HANDLERS`
    / hits the invoke door (§21.9). Exit 0 ok; 1 refusal (bad dimension / non-slug id /
    topic-without-workspace / refuse-if-exists); 2 usage."""
    import argparse

    from pipeline.workspace_name import DEFAULT_ZONE

    parser = argparse.ArgumentParser(
        prog="pipeline entry",
        description=(
            "The friendly dimension-entry scaffolder (authoring layer C3, design D11): a second "
            "consumer of the C2a authoring core. LOCAL Tier-A file write — never an invoke verb / "
            "HTTP door (§21.9). Subcommand: new."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    new = sub.add_parser(
        "new",
        help="scaffold one schema-conforming dimension entry from its floor skeleton",
        description=(
            "Scaffold ONE new dimension entry (design D11) from a schema-conforming, self-"
            "documenting skeleton: the envelope + EVERY attribute at its schema floor + each "
            "attribute's `definition:` prose as inline #-comments (the same guidance `docs "
            "attributes` surfaces). A floor-only entry lints GREEN unedited. --workspace W homes "
            "an instance entry (x--prefixed, provenance instance) under "
            "workspaces/<W>/<dimension>/x-<id>.md; without it, a framework-default candidate "
            "(<dimension>/<id>.md, provenance framework) for a deliberate human commit. `entry "
            "new topic` REQUIRES --workspace (topics are workspace editorial data). Refuse-if-"
            "exists unless --force. NEVER spends quota (never an invoke verb; §21.9)."
        ),
    )
    new.add_argument(
        "dimension",
        help="the dimension token (persona/format/voice/goal/platform/language/output-type/"
        "presentation/topic)",
    )
    new.add_argument("id", help="the entry id to write (§7.4 slug; the filename stem)")
    new.add_argument(
        "--workspace",
        default=None,
        help="home an instance (x-) entry under users/<user>/workspaces/<W>/ (required for "
        "`topic`); a framework-default candidate needs none",
    )
    new.add_argument(
        "--user",
        default=None,
        help="the owning user (§23) for a client (x-) entry home; required with --workspace",
    )
    new.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help=(
            "the zone the --workspace lives in (§23; "
            f"users/<user>/zones/<zone>/workspaces/<W>/, default: {DEFAULT_ZONE}). Ignored for a "
            "framework-default entry (no --workspace)."
        ),
    )
    new.add_argument(
        "--root", default=".", help="framework repo root → <dimension>/<id>.md (default: cwd)"
    )
    new.add_argument(
        "--force", action="store_true", help="overwrite an existing entry file (default: refuse)"
    )
    args = parser.parse_args(argv)

    if args.subcommand != "new":
        parser.print_usage(sys.stderr)
        print("pipeline entry: a subcommand is required (known: new)", file=sys.stderr)
        return 2

    from pipeline import entryscaffold

    try:
        target = entryscaffold.write_entry(
            args.root, args.dimension, args.id,
            user=args.user, workspace=args.workspace, zone=args.zone, force=args.force,
        )
    except _entry_error_types() as exc:
        print(f"pipeline entry new: {exc}", file=sys.stderr)
        return 1

    homed = f" under workspace {target.workspace!r}" if target.workspace is not None else ""
    print(
        f"pipeline entry new: wrote {target.dimension} entry {target.entry_id!r} "
        f"[{target.provenance}]{homed} — {target.path}"
    )
    return 0


# ---------------------------------------------------------------------------
# W1/W2: `pipeline workspace new|list|delete` + `pipeline user new` — the FRIENDLY local workspace
# lifecycle (scaffold / list / delete).
#
# The local, friendly form of the documented onboarding flow (`cp -R templates/workspace
# users/<user>/workspaces/<ws>`): a dimension-entry/recipe-authoring sibling that seeds a new
# workspace from the shared framework blueprint `templates/workspace/` (via the thin
# `pipeline.workspacescaffold` leaf, which REUSES the C2a `pipeline.authoring` overwrite guard +
# the `pipeline.workspace_name` isolation gate — nothing re-implemented). `user new` is the
# sibling that stands up just the empty per-user namespace `users/<user>/workspaces/`.
#
# MONEY-SAFETY (§21.9): both are LOCAL Tier-A file scaffolds. Neither registers an invoke verb,
# touches `_VERB_HANDLERS`, or dispatches through the invoke door — so neither can spend
# subscription quota or mint a token. A workspace name never enters the artifact preimage; a
# scaffolded workspace is inert to identity until a run selects it.
# ---------------------------------------------------------------------------


def _workspace_error_types() -> tuple:
    """The typed refusals `workspace new` / `user new` map to a loud exit 1 (never a stack trace):
    a bad / uppercase / escaping user or workspace name (`workspace_name.WorkspaceNameError`), and a
    refuse-if-exists or missing-blueprint refusal (`authoring.AuthoringError`). The tuple stays
    specific so a genuine bug is never swallowed."""
    from pipeline import authoring
    from pipeline.workspace_name import WorkspaceNameError

    return (authoring.AuthoringError, WorkspaceNameError)


def _cmd_workspace(argv: list[str]) -> int:
    """W1/W2: `pipeline workspace <new|list|delete> …` — the FRIENDLY local workspace lifecycle.

    Sub-dispatches (mirroring `_cmd_entry`) over the SAME self-contained
    `users/<user>/workspaces/<workspace>/` layout, all LOCAL Tier-A file ops (never an invoke verb /
    HTTP door; §21.9):

    - `new WORKSPACE --user U [--root DIR] [--force]` (W1) — seed one new workspace from the shared
      blueprint `templates/workspace/`.
    - `list [--user U] [--root DIR]` (W2) — READ-ONLY: list workspaces (one user, or all users) with
      a topic-count + has-output summary.
    - `delete WORKSPACE --user U [--yes] [--force] [--root DIR]` (W2) — DESTRUCTIVE,
      safe-by-default: remove ONE workspace; refuse-by-default (typed-name confirm / --yes), refuse
      a has-output workspace unless --force too, never delete through a symlink.

    Exit 0 ok; 1 refusal (bad name / refuse-if-exists / missing blueprint / delete refusal);
    2 usage (no subcommand / missing required flag)."""
    import argparse

    from pipeline.workspace_name import DEFAULT_ZONE

    parser = argparse.ArgumentParser(
        prog="pipeline workspace",
        description=(
            "The friendly local workspace lifecycle (design §23) over the self-contained "
            "users/<user>/workspaces/<workspace>/ layout. LOCAL Tier-A file ops — never an invoke "
            "verb / HTTP door (§21.9). Subcommands: new, list, delete."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")

    new = sub.add_parser(
        "new",
        help="seed one new workspace under users/<user>/workspaces/ from templates/workspace/",
        description=(
            "Seed ONE new client workspace users/<user>/workspaces/<workspace>/ by copying the "
            "shared framework blueprint templates/workspace/ (design §23; the friendly form of "
            "`cp -R templates/workspace users/<user>/workspaces/<ws>`). --user is REQUIRED (the "
            "§23 isolation prefix); the user namespace is auto-created on demand (a brand-new user "
            "home is announced so a mistyped --user is visible). Refuse-if-exists unless --force; "
            "--force NEVER overwrites an existing file (the copy is non-destructive — it only tops "
            "up MISSING blueprint files, never deletes client data). Then edit source.md (the "
            "graph path) and add topics. NEVER spends quota (never an invoke verb; §21.9)."
        ),
    )
    new.add_argument(
        "workspace",
        help="the workspace name to create (§23 lowercase-safe segment; the directory name)",
    )
    new.add_argument(
        "--user",
        required=True,
        help="the owning user (§23 isolation prefix; users/<user>/workspaces/<workspace>/)",
    )
    new.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help=(
            "the zone segment between user and workspace (§23; "
            f"users/<user>/zones/<zone>/workspaces/<ws>/, default: {DEFAULT_ZONE}). A brand-new "
            "zone is auto-created and announced so a mistyped --zone is visible."
        ),
    )
    new.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/workspaces/<workspace>/ (default: "
        "cwd)",
    )
    new.add_argument(
        "--force",
        action="store_true",
        help="proceed if the workspace exists — seeds only MISSING files, never overwrites "
        "(default: refuse)",
    )

    lst = sub.add_parser(
        "list",
        help="list workspaces (one user, or all users) with a topic-count + has-output summary",
        description=(
            "READ-ONLY: list workspaces under users/. With --user, list that one user's "
            "workspaces; without it, scan EVERY user (users/*/workspaces/*), each row shown as "
            "<user>/<workspace> (workspaces are discovered by scanning — no global index). "
            "Each row carries a light TRUE summary: the authored-topic count and whether the "
            "workspace holds generated output. A missing/empty users/ prints 'no workspaces found' "
            "(exit 0), never a traceback. Mutates nothing (never an invoke verb; §21.9)."
        ),
    )
    lst.add_argument(
        "--user",
        default=None,
        help="restrict to one user's workspaces (§23 lowercase-safe segment; default: all users)",
    )
    lst.add_argument(
        "--zone",
        default=None,
        help="restrict to one zone across the selected user(s) (§23; default: ALL zones)",
    )
    lst.add_argument(
        "--root", default=".", help="framework repo root → users/ (default: cwd)"
    )

    dele = sub.add_parser(
        "delete",
        help="remove ONE workspace (destructive, safe-by-default: --user + confirmation required)",
        description=(
            "DESTRUCTIVE, SAFE-BY-DEFAULT: remove ONE workspace users/<user>/workspaces/"
            "<workspace>/. --user is REQUIRED. Validates + resolves + contains the target via the "
            "isolation gate, REFUSES a non-existent target, and NEVER deletes through a symlink "
            "(removes only the validated contained real directory). Tier-1 confirmation is ALWAYS "
            "required: interactively you TYPE the workspace name (a mismatch aborts); headless you "
            "pass --yes. Tier-2: a workspace holding GENERATED output (spent work/money) is "
            "refused even with --yes unless --force is ALSO passed. On success, users/<user>/ and "
            "workspaces/ are left in place. LOCAL file op (never an invoke verb; §21.9)."
        ),
    )
    dele.add_argument(
        "workspace",
        help="the workspace name to delete (§23 lowercase-safe segment; the directory name)",
    )
    dele.add_argument(
        "--user",
        required=True,
        help="the owning user (§23 isolation prefix; users/<user>/workspaces/<workspace>/)",
    )
    dele.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help=(
            "the zone the workspace lives in (§23; "
            f"users/<user>/zones/<zone>/workspaces/<ws>/, default: {DEFAULT_ZONE})"
        ),
    )
    dele.add_argument(
        "--yes",
        action="store_true",
        help="supply the confirmation non-interactively (skip the type-the-name prompt)",
    )
    dele.add_argument(
        "--force",
        action="store_true",
        help="ALSO required (with --yes) to delete a workspace holding generated output",
    )
    dele.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/workspaces/<workspace>/ (default: cwd)",
    )

    args = parser.parse_args(argv)

    if args.subcommand == "new":
        return _workspace_new(args)
    if args.subcommand == "list":
        return _workspace_list(args)
    if args.subcommand == "delete":
        return _workspace_delete(args)
    parser.print_usage(sys.stderr)
    print(
        "pipeline workspace: a subcommand is required (known: new, list, delete)", file=sys.stderr
    )
    return 2


def _workspace_new(args: "object") -> int:
    """W1: `workspace new` — seed one workspace from the blueprint + print the path/next hint."""
    from pathlib import Path

    from pipeline import workspacescaffold

    try:
        result = workspacescaffold.scaffold_workspace(
            args.root, args.workspace, user=args.user, zone=args.zone, force=args.force
        )
    except _workspace_error_types() as exc:
        print(f"pipeline workspace new: {exc}", file=sys.stderr)
        return 1

    if result.created_user_namespace:
        # §23/Z4 S1: derive the namespace path from IDENTITY (`result.user`), never fragile
        # positional path math on the 5-level target (`.parent.parent` = zones/<zone>, WRONG).
        user_namespace = Path(args.root) / "users" / result.user
        print(
            f"pipeline workspace new: created new user namespace {user_namespace} "
            f"(users/{result.user}/)"
        )
    if result.created_zone:
        print(
            f"pipeline workspace new: created new zone {result.zone!r} for user {result.user!r} "
            f"(users/{result.user}/zones/{result.zone}/)"
        )
    print(
        f"pipeline workspace new: seeded workspace {result.workspace!r} for user {result.user!r} "
        f"({len(result.copied)} blueprint file(s)) — {result.path}"
    )
    if result.skipped:
        print(
            f"pipeline workspace new: left {len(result.skipped)} existing file(s) untouched "
            f"(never overwritten): {', '.join(result.skipped)}"
        )
    print(
        f"  next: edit {result.path / 'source.md'} (the graph path), add topics under "
        f"{result.path / 'topics'}/, then `pipeline preview --user {result.user} "
        f"--workspace {result.workspace} …`"
    )
    return 0


def _workspace_list(args: "object") -> int:
    """W2: `workspace list` — READ-ONLY enumeration with a TRUE per-workspace summary.

    One user (`--user`) or every user (`users/*/workspaces/*`, rows shown `<user>/<workspace>`). A
    bad/uppercase `--user` is a loud refusal (exit 1); a missing/empty users/ prints a clean
    'no workspaces found' (exit 0), never a traceback. Mutates nothing (§21.9)."""
    from pipeline import workspacescaffold

    try:
        rows = workspacescaffold.list_workspaces(args.root, user=args.user, zone=args.zone)
    except _workspace_error_types() as exc:
        print(f"pipeline workspace list: {exc}", file=sys.stderr)
        return 1

    if not rows:
        scope = f" for user {args.user!r}" if args.user else ""
        scope += f" in zone {args.zone!r}" if args.zone else ""
        print(f"pipeline workspace list: no workspaces found{scope}")
        return 0

    for row in rows:
        output_note = "has output" if row.has_output else "no output"
        print(
            f"{row.user}/{row.zone}/{row.workspace}  "
            f"({row.topic_count} topic(s), {output_note})  — {row.path}"
        )
    return 0


def _workspace_delete(args: "object") -> int:
    """W2: `workspace delete` — DESTRUCTIVE, safe-by-default removal of ONE workspace.

    --user is mandatory (argparse). The layered guards (validate/contain, symlink refusal,
    non-existent refusal, Tier-2 has-output override, Tier-1 confirmation) live in
    `workspacescaffold.delete_workspace`; every refusal is a typed exit-1, never a traceback. On
    success, only the one contained workspace dir is removed. LOCAL file op (§21.9)."""
    from pipeline import workspacescaffold

    try:
        result = workspacescaffold.delete_workspace(
            args.root,
            args.user,
            args.workspace,
            zone=args.zone,
            assume_yes=args.yes,
            force=args.force,
        )
    except _workspace_error_types() as exc:
        print(f"pipeline workspace delete: {exc}", file=sys.stderr)
        return 1

    forced = " (forced: held generated output)" if result.had_output else ""
    print(
        f"pipeline workspace delete: removed workspace {result.workspace!r} for user "
        f"{result.user!r} ({result.file_count} file(s)){forced} — {result.path}"
    )
    return 0


def _cmd_user(argv: list[str]) -> int:
    """W1 (sibling): `pipeline user new <user> [--root DIR] [--force]` — create just the empty
    per-user namespace users/<user>/workspaces/ (the extensible per-user home) without a workspace.

    A LOCAL Tier-A file op (never an invoke verb / HTTP door; §21.9): validate `<user>` via the
    isolation gate, create users/<user>/workspaces/, refuse an existing namespace unless --force
    (a SAFE no-op that deletes nothing), and print the created namespace path. Exit 0 ok; 1 refusal
    (bad user / refuse-if-exists); 2 usage (no subcommand)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline user",
        description=(
            "The explicit per-user namespace setup (design §23): create users/<user>/workspaces/ "
            "(the extensible per-user home) without a workspace. LOCAL Tier-A file op — never an "
            "invoke verb / HTTP door (§21.9). Subcommand: new."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    new = sub.add_parser(
        "new",
        help="create the empty per-user namespace users/<user>/workspaces/",
        description=(
            "Create the empty per-user namespace users/<user>/workspaces/ (design §23) — the "
            "extensible per-user home, set up explicitly BEFORE any workspace exists. <user> is a "
            "§23 lowercase-safe segment. Refuse-if-exists unless --force (a safe no-op; deletes "
            "nothing). NEVER spends quota (never an invoke verb; §21.9)."
        ),
    )
    new.add_argument(
        "user",
        help="the user name to create (§23 lowercase-safe segment) → users/<user>/workspaces/",
    )
    new.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/workspaces/ (default: cwd)",
    )
    new.add_argument(
        "--force",
        action="store_true",
        help="proceed if the namespace exists — a safe no-op, never deletes (default: refuse)",
    )
    args = parser.parse_args(argv)

    if args.subcommand != "new":
        parser.print_usage(sys.stderr)
        print("pipeline user: a subcommand is required (known: new)", file=sys.stderr)
        return 2

    from pipeline import workspacescaffold

    try:
        result = workspacescaffold.scaffold_user(args.root, args.user, force=args.force)
    except _workspace_error_types() as exc:
        print(f"pipeline user new: {exc}", file=sys.stderr)
        return 1

    print(f"pipeline user new: created user namespace {result.user!r} — {result.path}")
    print(
        f"  next: `pipeline workspace new <workspace> --user {result.user}` to seed a workspace"
    )
    return 0


# ---------------------------------------------------------------------------
# Z7: `pipeline zone new|list|delete` — the FRIENDLY per-zone lifecycle (one level UP from the
# workspace CRUD). A zone groups a user's workspaces (§23): `users/<user>/zones/<zone>/workspaces/`.
#
# Sibling of `_cmd_workspace`/`_cmd_user`, wiring the thin `pipeline.workspacescaffold` zone leaf
# (which REUSES the C2a `pipeline.authoring` overwrite guard + the `pipeline.workspace_name`
# isolation gate — nothing re-implemented). `zone delete` is STRICTER because it is RECURSIVE (it
# removes every contained workspace at once), so its Tier-2 guard aggregates the has-output oracle.
#
# MONEY-SAFETY (§21.9): every verb is a LOCAL Tier-A file op — none registers an invoke verb,
# touches `_VERB_HANDLERS`, or dispatches through the invoke door, so none can spend quota or mint a
# token.
# ---------------------------------------------------------------------------


def _cmd_zone(argv: list[str]) -> int:
    """Z7: `pipeline zone <new|list|delete> …` — the FRIENDLY per-zone lifecycle (design §23).

    Sub-dispatches (mirroring `_cmd_workspace`) over `users/<user>/zones/<zone>/workspaces/`, all
    LOCAL Tier-A file ops (never an invoke verb / HTTP door; §21.9):

    - `new ZONE --user U [--root DIR] [--force]` — create one new zone (the per-zone home);
      the user namespace is auto-created on demand.
    - `list [--user U] [--root DIR]` — READ-ONLY: zones as <user>/<zone> with a workspace count.
    - `delete ZONE --user U [--yes] [--force] [--root DIR]` — DESTRUCTIVE, RECURSIVE, safe:
      remove one zone AND every workspace it contains; refuse-by-default (typed-zone-name confirm /
      --yes), refuse if ANY contained workspace holds generated output unless --force too, never
      delete through a symlink.

    Exit 0 ok; 1 refusal (bad name / refuse-if-exists / non-existent / symlink / delete refusal);
    2 usage (no subcommand / missing --user)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="pipeline zone",
        description=(
            "The friendly per-zone lifecycle (design §23) over users/<user>/zones/<zone>/"
            "workspaces/. A zone groups a user's workspaces (it sits between user and workspace). "
            "LOCAL Tier-A file ops — never an invoke verb / HTTP door (§21.9). Subcommands: new, "
            "list, delete."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")

    new = sub.add_parser(
        "new",
        help="create one new zone (users/<user>/zones/<zone>/workspaces/)",
        description=(
            "Create ONE new zone users/<user>/zones/<zone>/workspaces/ — the per-zone workspace "
            "home (design §23). --user is REQUIRED (the §23 isolation prefix); the user namespace "
            "is auto-created on demand (a brand-new user home is announced so a mistyped --user is "
            "visible). Refuse-if-exists unless --force (a safe no-op). NEVER spends "
            "quota (never an invoke verb; §21.9)."
        ),
    )
    new.add_argument(
        "zone",
        help="the zone name to create (§23 lowercase-safe segment; the directory name)",
    )
    new.add_argument(
        "--user",
        required=True,
        help="the owning user (§23 isolation prefix; users/<user>/zones/<zone>/workspaces/)",
    )
    new.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd)",
    )
    new.add_argument(
        "--force",
        action="store_true",
        help="proceed if the zone exists — a safe no-op, never deletes (default: refuse)",
    )

    lst = sub.add_parser(
        "list",
        help="list zones (one user, or all users) with a workspace count",
        description=(
            "READ-ONLY: list zones under users/. With --user, list that one user's zones; without "
            "it, scan EVERY user (users/*/zones/*), each row shown as <user>/<zone> with the count "
            "of workspaces the zone contains. A missing/empty users/ prints 'no zones found' "
            "(exit 0), never a traceback. Mutates nothing (never an invoke verb; §21.9)."
        ),
    )
    lst.add_argument(
        "--user",
        default=None,
        help="restrict to one user's zones (§23 lowercase-safe segment; default: all users)",
    )
    lst.add_argument(
        "--root", default=".", help="framework repo root → users/ (default: cwd)"
    )

    dele = sub.add_parser(
        "delete",
        help="remove ONE zone + every workspace it holds (destructive, recursive, safe-by-default)",
        description=(
            "DESTRUCTIVE, RECURSIVE, SAFE-BY-DEFAULT: remove ONE zone users/<user>/zones/<zone>/ "
            "AND every workspace it contains. --user is REQUIRED. Validates + resolves + contains "
            "the zone via the isolation gate, REFUSES a non-existent zone, and NEVER deletes "
            "through a symlink (removes only the validated contained real zone dir). Tier-1 "
            "confirmation is ALWAYS required: interactive: TYPE the zone name (a mismatch aborts); "
            "headless you "
            "pass --yes. Tier-2 (STRICTER, because recursive): if ANY contained workspace holds "
            "GENERATED output (spent work/money) the whole zone is refused even with --yes unless "
            "--force is ALSO passed. On success, users/<user>/ is left in place. LOCAL file op "
            "(never an invoke verb; §21.9)."
        ),
    )
    dele.add_argument(
        "zone",
        help="the zone name to delete (§23 lowercase-safe segment; the directory name)",
    )
    dele.add_argument(
        "--user",
        required=True,
        help="the owning user (§23 isolation prefix; users/<user>/zones/<zone>/)",
    )
    dele.add_argument(
        "--yes",
        action="store_true",
        help="supply the confirmation non-interactively (skip the type-the-zone-name prompt)",
    )
    dele.add_argument(
        "--force",
        action="store_true",
        help="ALSO required (with --yes) to delete a zone whose workspaces hold generated output",
    )
    dele.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/ (default: cwd)",
    )

    # `--zone` never appears on this group: the ZONE is the positional subject of new/delete (a zone
    # verb never defaults its own subject), and the per-zone `workspaces/` home is a fixed literal
    # (§23).
    args = parser.parse_args(argv)

    if args.subcommand == "new":
        return _zone_new(args)
    if args.subcommand == "list":
        return _zone_list(args)
    if args.subcommand == "delete":
        return _zone_delete(args)
    parser.print_usage(sys.stderr)
    print("pipeline zone: a subcommand is required (known: new, list, delete)", file=sys.stderr)
    return 2


def _zone_new(args: "object") -> int:
    """Z7: `zone new` — create one zone + print the path/next hint. The user namespace is
    auto-created on demand; a brand-new user/zone is announced so a mistyped --user/--zone shows."""
    from pathlib import Path

    from pipeline import workspacescaffold

    try:
        result = workspacescaffold.scaffold_zone(
            args.root, args.zone, user=args.user, force=args.force
        )
    except _workspace_error_types() as exc:
        print(f"pipeline zone new: {exc}", file=sys.stderr)
        return 1

    if result.created_user_namespace:
        # Derive the namespace path from IDENTITY (`result.user`), never positional path math.
        user_namespace = Path(args.root) / "users" / result.user
        print(
            f"pipeline zone new: created new user namespace {user_namespace} "
            f"(users/{result.user}/)"
        )
    if result.created_zone:
        print(
            f"pipeline zone new: created zone {result.zone!r} for user {result.user!r} — "
            f"{result.path}"
        )
    else:
        # A --force no-op over an existing zone: honest about what happened (nothing new created).
        print(
            f"pipeline zone new: zone {result.zone!r} for user {result.user!r} already existed "
            f"(--force: no-op) — {result.path}"
        )
    print(
        f"  next: `pipeline workspace new <workspace> --user {result.user} --zone {result.zone}` "
        "to seed a workspace in this zone"
    )
    return 0


def _zone_list(args: "object") -> int:
    """Z7: `zone list` — READ-ONLY enumeration of zones with a TRUE per-zone workspace count.

    One user (`--user`) or every user (`users/*/zones/*`, rows shown `<user>/<zone>`). A
    bad/uppercase `--user` is a loud refusal (exit 1); a missing/empty users/ prints a clean
    'no zones found' (exit 0), never a traceback. Mutates nothing (§21.9)."""
    from pipeline import workspacescaffold

    try:
        rows = workspacescaffold.list_zones(args.root, user=args.user)
    except _workspace_error_types() as exc:
        print(f"pipeline zone list: {exc}", file=sys.stderr)
        return 1

    if not rows:
        scope = f" for user {args.user!r}" if args.user else ""
        print(f"pipeline zone list: no zones found{scope}")
        return 0

    for row in rows:
        print(
            f"{row.user}/{row.zone}  "
            f"({row.workspace_count} workspace(s))  — {row.path}"
        )
    return 0


def _zone_delete(args: "object") -> int:
    """Z7: `zone delete` — DESTRUCTIVE, RECURSIVE, safe-by-default removal of ONE zone.

    --user is mandatory (argparse). The layered guards (validate/contain, symlink refusal,
    non-existent refusal, Tier-2 AGGREGATE has-output override, Tier-1 zone-name confirmation) live
    in `workspacescaffold.delete_zone`; every refusal is a typed exit-1, never a traceback. On
    success, only the one contained zone dir is removed (users/<user>/ survives). LOCAL file op."""
    from pipeline import workspacescaffold

    try:
        result = workspacescaffold.delete_zone(
            args.root,
            args.user,
            args.zone,
            assume_yes=args.yes,
            force=args.force,
        )
    except _workspace_error_types() as exc:
        print(f"pipeline zone delete: {exc}", file=sys.stderr)
        return 1

    forced = " (forced: contained generated output)" if result.had_output else ""
    print(
        f"pipeline zone delete: removed zone {result.zone!r} for user {result.user!r} "
        f"({result.workspace_count} workspace(s), {result.file_count} file(s)){forced} — "
        f"{result.path}"
    )
    return 0


def _transport_llm_call(
    *,
    model: "str | None" = None,
    timeout_seconds: "float | None" = None,
    runner: "object | None" = None,
    base_env: "object | None" = None,
    env_overrides: "object | None" = None,
):
    """Build the DEFAULT research LLM seam: the SUBSCRIPTION transport chokepoint (F10, §21.9).

    Every planning / synthesis / gap-find call routes through `transport.invoke_headless`
    (`build_child_env` STRIPS `ANTHROPIC_API_KEY`; headless `claude -p --output-format json`; the
    per-call `budget` becomes the `--max-budget-usd` cap). NEVER an API key. A non-`ok` outcome
    (timeout / backpressure / budget cutoff / malformed) becomes a loud `FeedError` so the loop
    stops cleanly rather than fabricating a partial. `runner`/`base_env`/`env_overrides` are TEST
    seams (a fake `Runner` proves no real model/network call and the F10 key-strip); production
    leaves them `None` (real subprocess, ambient env stripped). This factory — NOT the sources feed
    code — is the single place the transport is imported, so sources stays paid-path-free."""
    from pipeline.sources.acquire import FeedError
    from pipeline.transport import invoke_headless

    def _call(prompt: str, *, budget: float) -> str:
        extra = {} if timeout_seconds is None else {"timeout_seconds": timeout_seconds}
        result = invoke_headless(
            prompt,
            max_budget_usd=budget,
            model=model,
            runner=runner,
            base_env=base_env,
            env_overrides=env_overrides,
            **extra,
        )
        if result.status != "ok" or result.text is None:
            raise FeedError(
                f"sources-feed-error: the research LLM call did not succeed ({result.code}) — the "
                "subscription transport returned no usable result; the loop stops (never a silent "
                "partial)"
            )
        return result.text

    return _call


def _research_dry_run_lines(config: "object", budget: "object") -> list[str]:
    """The DRY-RUN disclosure for a PAID research source: the resolved plan header + the
    `acquire-scope` ceiling, spending NOTHING (the LLM seam is never even built). Honest by design —
    a bounded CEILING, not an exact bill (§21.9 money-safety default)."""
    conn = config.connection
    question = str(conn.get("question") or "")
    backend = str(conn.get("backend") or "commoncrawl")
    return [
        f"research {config.source_id!r} (research) → namespace {config.namespace!r}  [DRY-RUN]",
        f"  question     : {question}",
        f"  backend      : {backend}  temporality: {config.temporality or '(none)'}",
        f"  {budget.acquire_scope()}",
        "  disclosure   : a bounded CEILING covering plan + synthesis + gap-find (the true",
        "                 worst-case total, never undershot), not an exact bill — the θ stop-rule",
        "                 usually halts earlier. NOTHING was spent (the LLM seam was not even",
        "                 built). Re-run with --go to approve the ceiling and drive the paid loop.",
    ]


def _cmd_sources(
    argv: list[str],
    *,
    http_get: "object | None" = None,
    llm_call: "object | None" = None,
) -> int:
    """Sources P2/P3: `pipeline sources ingest <workspace> --user <u>` — the OUT-OF-BAND acquisition
    maintenance door (design §6).

    FREE feed sources (edgar/rss/gdelt/commoncrawl) fetch FREE HTTP and write the LOCAL sealed
    cache — no paid quota, no token, $0 model spend (§21.9). The PAID `research` source (P3b) SPENDS
    subscription LLM tokens in an agentic loop, so it is TRANSPORT-AWARE and money-safe by
    construction: WITHOUT `--go` it DRY-RUNS (prints the `acquire-scope` ceiling and spends nothing,
    never even building the LLM seam); WITH `--go` it drives the loop through the subscription
    transport (no API key, a per-call `--max-budget-usd` cap, a hard round/fan-out ceiling +
    θ-stop). Feed sources ignore `--go` (always free). Both fetch seams are INJECTABLE (`http_get`,
    `llm_call`) so a test drives the whole command with fixtures and NEVER hits the network or a
    real model. Exit 0 ok; 1 refusal (bad name / unknown feed / busy namespace / paid failure); 2
    usage.
    """
    import argparse

    from pipeline.sources.feeds import feed_kinds  # the shipped feed set (discovery surface)
    from pipeline.workspace_name import DEFAULT_ZONE

    known_kinds = ", ".join(feed_kinds())

    parser = argparse.ArgumentParser(
        prog="pipeline sources",
        description=(
            "The out-of-band acquisition maintenance door (design §6; sources P2/P3): fetch a "
            "workspace's source(s), normalize + dedup + θ-gate, and SEAL into the local sealed "
            "cache. Feed kinds are LOCAL Tier-A (free HTTP, $0 model spend); the `research` kind "
            "SPENDS subscription LLM tokens and is dry-run by default (needs --go). Subcommand: "
            "ingest."
        ),
    )
    sub = parser.add_subparsers(dest="subcommand", metavar="<subcommand>")
    ingest = sub.add_parser(
        "ingest",
        help="acquire a workspace's source(s) (feeds free; the research kind spends, needs --go)",
        description=(
            "Resolve the workspace's descriptor(s) under sources/feeds/<id>.yaml and run each "
            "through fetch → normalize → dedup + θ-gate → SEAL (advancing the namespace HEAD). "
            "Idempotent: a re-ingest of unchanged feed content is a content-addressed no-op. "
            "Writes only the gitignored sealed cache under the workspace (rule-1 carve-out); reads "
            "every source read-only. Feed kinds spend NOTHING (free HTTP; $0 model spend). The "
            "`research` kind SPENDS subscription LLM tokens: WITHOUT --go it DRY-RUNS (prints "
            "acquire-scope, spends nothing); WITH --go it drives the paid loop under a hard cost "
            f"ceiling + θ-stop. Known kinds: {known_kinds} (research is the paid one)."
        ),
    )
    ingest.add_argument("workspace", help="the workspace to acquire into (§21.1)")
    ingest.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix; users/<user>/…)"
    )
    ingest.add_argument(
        "--source",
        default=None,
        metavar="ID",
        help="a single source id under sources/feeds/ (default: every descriptor)",
    )
    ingest.add_argument(
        "--root",
        default=".",
        help="framework repo root → users/<user>/zones/<zone>/workspaces/<ws>/ (def: cwd)",
    )
    ingest.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        help=(
            "the zone segment between user and workspace (§23; "
            f"users/<user>/zones/<zone>/workspaces/<ws>/, default: {DEFAULT_ZONE})"
        ),
    )
    ingest.add_argument(
        "--go",
        action="store_true",
        help=(
            "approve the PAID research loop's cost ceiling and DRIVE it (research sources only; "
            "feeds are always free and ignore --go). Omit for a dry-run acquire-scope estimate "
            "that SPENDS NOTHING."
        ),
    )
    args = parser.parse_args(argv)

    if args.subcommand != "ingest":
        parser.print_usage(sys.stderr)
        print("pipeline sources: a subcommand is required (known: ingest)", file=sys.stderr)
        return 2

    from pipeline.sources import acquire
    from pipeline.sources.cache import CacheError
    from pipeline.sources.control import ControlError, ResearchBudget
    from pipeline.sources.feeds import feed_spends
    from pipeline.sources.feeds import research as research_mod
    from pipeline.store import WorkspaceStore
    from pipeline.workspace_name import WorkspaceNameError, validate_workspace_path

    try:
        # door: resolve-and-contain (zone materialized at the --zone flag, exactly one chokepoint)
        validate_workspace_path(args.root, args.user, args.workspace, zone=args.zone)
    except WorkspaceNameError as exc:
        print(f"pipeline sources ingest: {exc}", file=sys.stderr)
        return 1

    store = WorkspaceStore.at(args.root, args.user, args.workspace, zone=args.zone)
    fetch = http_get if http_get is not None else acquire.default_http_get
    try:
        # Resolve descriptors FIRST (no fetch, no spend) so the paid gate can inspect each kind
        # before deciding what — if anything — to run. A malformed `namespace:`/`budget:` surfaces
        # as a typed CacheError/ControlError; catch alongside FeedError → clean exit-1 refusal.
        configs = acquire.resolve_workspace_feeds(store, source=args.source)
    except (acquire.FeedError, CacheError, ControlError) as exc:
        print(f"pipeline sources ingest: {exc}", file=sys.stderr)
        return 1

    if not configs:
        print(
            "pipeline sources ingest: no feed sources found under "
            f"users/{args.user}/workspaces/{args.workspace}/sources/feeds/ — add a "
            "sources/feeds/<id>.yaml descriptor (kind/namespace/connection), then re-run",
            file=sys.stderr,
        )
        return 1

    lines: list[str] = []
    try:
        for config in configs:
            if feed_spends(config.kind):
                # PAID research source: dry-run by DEFAULT (money-safety); --go is the only spend
                # path. The LLM seam is built ONLY on the --go branch — a dry-run never touches it.
                budget = ResearchBudget.from_mapping(config.connection.get("budget"))
                if not args.go:
                    lines.extend(_research_dry_run_lines(config, budget))
                    continue
                seam = llm_call if llm_call is not None else _transport_llm_call()
                report = research_mod.run_research(config, store, http_get=fetch, llm_call=seam)
                lines.extend(report.summary_lines())
            else:
                lines.extend(
                    acquire.ingest_feed(config, store, http_get=fetch).summary_lines()
                )
    except (acquire.FeedError, CacheError, ControlError) as exc:
        print(f"pipeline sources ingest: {exc}", file=sys.stderr)
        return 1

    mode = "--go: paid loop driven" if args.go else "dry-run for paid sources"
    print(
        f"=== sources ingest: user={args.user} workspace={args.workspace} "
        f"sources={len(configs)} ({mode}) ==="
    )
    for line in lines:
        print(line)
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
    "docs": _cmd_docs,
    "recipe": _cmd_recipe,
    "entry": _cmd_entry,
    "workspace": _cmd_workspace,
    "user": _cmd_user,
    "zone": _cmd_zone,
    "sources": _cmd_sources,
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
