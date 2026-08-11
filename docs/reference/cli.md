<!-- GENERATED — do not edit; run `pipeline docs cli` -->

# Pipeline CLI reference

Every `pipeline` command and subcommand — its description, usage synopsis, and every flag/argument (value, default, whether it is required, and its help). This page is generated from the live argparse command tree (`pipeline.__main__.build_parser()`), the SAME tree the runtime `--help` walks, so it carries the real CLI surface, never a hand-maintained copy that could drift.

Regenerate with `pipeline docs cli`. A byte-equality CI test (`tests/test_cli_doc_contract.py`) fails loudly if a command or flag changes without regenerating this file, and asserts every command + flag carries help.

Documented: 43 commands.

## `pipeline`

The optiquity-content-pipeline operator CLI (framework mechanism): one synchronous command per invocation (see each subcommand's own --help). Money-safe by construction (§21.9) — only `generate --go`, `mvp-demo`, `demo-thread`, and `sources ingest --go` research loop ever spend.

Usage: `pipeline` [`--version`] `<command> ...`

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--version` |  |  |  | print the pipeline version and exit |

### `pipeline drift-report`

Run the update-time drift report (docs/design.md §11.5 SV7/MIG-6) over every config collection under --root: redefinitions to review (BLOCK), removed attributes still present (BLOCK), out-of-window stamps (BLOCK, MIG-2), new attributes riding defaults (WARN). Wording-only changes are silent by design. Read-only; remediation is scripts/migrate.sh (never auto-run).

Usage: `pipeline drift-report` [`--root ROOT`] [`--registry REGISTRY`] [`--now YYYY-MM-DD`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT | `.` |  | config tree root (default: cwd) |
| `--registry` | REGISTRY |  |  | migration step registry, the out-of-window oracle (default: <root>/pipeline/migrations.yaml; missing = empty registry) |
| `--now` | YYYY-MM-DD |  |  | override the report clock (ops/testing; default: today). The clock is injected here at the edge — the library never reads ambient time. |

### `pipeline ssot`

Tracking-SSOT operator verbs (design §24).

Usage: `pipeline ssot` `<subcommand> ...`

#### `pipeline ssot derive-state`

Render the derived, read-only state.md-style status mirror (CLAUDE.md rule 3; docs/design.md §24) from an SSOT CSV. Byte-deterministic for a fixed CSV. The output is written to --out (a caller-supplied path) or stdout — never the repo's own state.md, which is the maintainer's live session document.

Usage: `pipeline ssot derive-state` `--csv FILE` [`--out FILE`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--csv` | FILE |  | yes | the SSOT CSV to project (read-only) |
| `--out` | FILE |  |  | caller-supplied destination for the mirror (default: stdout) |

### `pipeline demo-thread`

Drive ONE full thread end to end (design §2.1 stages 1–5): ground the client graph, resolve/bind, compose via a LIVE subscription writer call, reconcile, serialize to an internal target, and persist the artifact + deliverable + bindings, advancing both SSOT row kinds. A build milestone (§25), not the MVP.

Usage: `pipeline demo-thread` `--workspace WORKSPACE` `--user USER` [`--root ROOT`] [`--now YYYY-MM-DD`] [`--model MODEL`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--workspace` | WORKSPACE |  | yes | the demo workspace (e.g. mvp-demo) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--root` | ROOT | `.` |  | the framework repo root (default: cwd) |
| `--now` | YYYY-MM-DD |  |  | grounding clock override (default: today; injected at the edge, never ambient) |
| `--model` | MODEL |  |  | writer model to pin (default: the CLI's own default) |

### `pipeline mvp-demo`

Drive THE §25 MVP scenario (all nine dimensions, interacting) against a local demo instance: grounding with the full selection grammar, one run override, compose→reconcile→serialize across an internal AND an external target, both review gates, a typed folio (typed + untyped member), emit-manifest, the sequential AND parallel consumption modes, and the SSOT projection. LIVE compose + review calls.

Usage: `pipeline mvp-demo` `--workspace WORKSPACE` `--user USER` [`--root ROOT`] [`--now YYYY-MM-DD`] [`--model MODEL`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--workspace` | WORKSPACE |  | yes | the demo workspace (e.g. mvp-demo) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--root` | ROOT | `.` |  | the framework repo root (default: cwd) |
| `--now` | YYYY-MM-DD |  |  | grounding clock override (default: today; injected at the edge, never ambient) |
| `--model` | MODEL |  |  | writer model to pin (default: the CLI's own default) |

### `pipeline invoke`

The external-actor API (design §21): one synchronous verb invocation → a single JSON object {envelope, results, [token]} on stdout (the n8n-facing shape).

Usage: `pipeline invoke` `verb` `--workspace WORKSPACE` `--user USER` [`--params-json JSON`] [`--token-json JSON`] [`--pins-json JSON`] [`--root ROOT`] [`--zone ZONE`] [`--transport MODE`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `verb` | verb |  | yes | the API verb (design §21.1 verb map) |
| `--workspace` | WORKSPACE |  | yes | the invoked workspace (§21.1) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--params-json` | JSON |  |  | verb params as a JSON object |
| `--token-json` | JSON |  |  | the resumption token as JSON (§20) |
| `--pins-json` | JSON |  |  | explicit reproducibility pins (§21.8) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/<ws>/ (default: cwd) |
| `--zone` | ZONE |  |  | the zone segment between user and workspace (§23; users/<user>/zones/<zone>/workspaces/<workspace>/, default: default). For a SPEND verb (render), OMITTING it lets a >1-zone user be refused (uniform S4, G7); naming it (even 'default') is honored verbatim. |
| `--transport` | MODE |  |  | per-run transport override (G7): 'subscription' \| 'api' \| 'key:<namespace>:<name>'. Selects a MODE / an assigned handle, never a user (I3). Default: the cascade decides. |

### `pipeline render`

The ergonomic render door (design §21.8, GAP-2): the friendly form of `pipeline invoke render` — a positional artifact-id + the render coordinates as flags, the SAME JSON envelope out. render is token-free and deterministic (strategy=pass, no live call): it mints/serves the deliverable for `item` at the given platform/language/output-type/presentation and prints one JSON object on stdout.

Usage: `pipeline render` `item` `--workspace WORKSPACE` `--user USER` [`--platform PLATFORM`] [`--language LANGUAGE`] `--output-type OUTPUT_TYPE` [`--presentation PRESENTATION`] [`--root ROOT`] [`--force-reconcile`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `item` | item |  | yes | the artifact-id to render (§7.4; the render `item`) |
| `--workspace` | WORKSPACE |  | yes | the invoked workspace (§21.1) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--platform` | PLATFORM |  |  | the target platform slug (§5) |
| `--language` | LANGUAGE |  |  | the target language slug (§5) |
| `--output-type` | OUTPUT_TYPE |  | yes | the render output-type slug (§17; required) |
| `--presentation` | PRESENTATION | `plain` |  | the presentation slug (§5.3; default: plain) |
| `--root` | ROOT | `.` |  | framework repo root → workspaces/<workspace>/ (default: cwd) |
| `--force-reconcile` |  |  |  | force a re-reconcile → a NEW revision fit, never mutating the old (§21.8) |

### `pipeline preview`

The friendly plan-only door (CLI-UX C3a): English-ish flags in, the whole plan + the exact count of paid pieces out — and it SPENDS NOTHING (begin-session with generate=none, explain=true, via the direct-handler pattern; §21.9 preserved).

Usage: `pipeline preview` [`--recipe RECIPE`] [`--topic ID`] [`--persona ID`] [`--format ID`] [`--voice ID`] [`--goals ID`] [`--platform ID`] [`--language ID`] [`--output-type ID`] [`--presentation ID`] [`--set PATH=VALUE`] [`--workspace WORKSPACE`] [`--user USER`] [`--zone ZONE`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--recipe` | RECIPE |  |  | recipe id (default: explainer-post, §10) |
| `--topic` | ID |  |  | a topic id (repeatable) |
| `--persona` | ID |  |  | a persona id (repeatable) |
| `--format` | ID |  |  | a format id (repeatable) |
| `--voice` | ID |  |  | a voice id (repeatable) |
| `--goals` | ID |  |  | a goal id (repeatable → STACKS into one goal-set, §8) |
| `--platform` | ID |  |  | a render platform slug (repeatable → one deliverable each, §5) |
| `--language` | ID |  |  | a render language slug (repeatable → fans out, §5) |
| `--output-type` | ID |  |  | a render output-type slug (repeatable → fans out, §17) |
| `--presentation` | ID |  |  | a presentation slug (repeatable → fans out, §5.3) |
| `--set` | PATH=VALUE |  |  | a run override, e.g. voice.formality=2 or format.tags+=x (repeatable, §13.2) |
| `--workspace` | WORKSPACE |  |  | the invoked workspace (§21.1) |
| `--user` | USER |  |  | the owning user (§23 isolation prefix; required whenever --workspace is given) |
| `--zone` | ZONE |  |  | the §23/Z4 zone to spend in (users/<user>/zones/<zone>/workspaces/<W>/). OMIT for the friendly default when you own one zone; a user with MORE THAN ONE zone MUST name one here (the door refuses-and-lists rather than silently pick `default`, §21.9/S4) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd) |

### `pipeline generate`

The friendly generate door (CLI-UX C3a). Same flags as `preview`; the DEFAULT is a DRY-RUN (prints the plan + spend estimate and STOPS, spending nothing). Add --go to DRIVE the plan to completion (the ONLY path that spends subscription quota). Direct-handler pattern throughout — never registers a session verb (§21.9 preserved).

Usage: `pipeline generate` [`--recipe RECIPE`] [`--topic ID`] [`--persona ID`] [`--format ID`] [`--voice ID`] [`--goals ID`] [`--platform ID`] [`--language ID`] [`--output-type ID`] [`--presentation ID`] [`--set PATH=VALUE`] [`--workspace WORKSPACE`] [`--user USER`] [`--zone ZONE`] [`--root ROOT`] [`--go`] [`--transport MODE`] [`--outline FILE`] [`--from AID`] [`--allow-drift`] [`--save-selection ID`] [`--selection ID`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--recipe` | RECIPE |  |  | recipe id (default: explainer-post, §10) |
| `--topic` | ID |  |  | a topic id (repeatable) |
| `--persona` | ID |  |  | a persona id (repeatable) |
| `--format` | ID |  |  | a format id (repeatable) |
| `--voice` | ID |  |  | a voice id (repeatable) |
| `--goals` | ID |  |  | a goal id (repeatable → STACKS into one goal-set, §8) |
| `--platform` | ID |  |  | a render platform slug (repeatable → one deliverable each, §5) |
| `--language` | ID |  |  | a render language slug (repeatable → fans out, §5) |
| `--output-type` | ID |  |  | a render output-type slug (repeatable → fans out, §17) |
| `--presentation` | ID |  |  | a presentation slug (repeatable → fans out, §5.3) |
| `--set` | PATH=VALUE |  |  | a run override, e.g. voice.formality=2 or format.tags+=x (repeatable, §13.2) |
| `--workspace` | WORKSPACE |  |  | the invoked workspace (§21.1) |
| `--user` | USER |  |  | the owning user (§23 isolation prefix; required whenever --workspace is given) |
| `--zone` | ZONE |  |  | the §23/Z4 zone to spend in (users/<user>/zones/<zone>/workspaces/<W>/). OMIT for the friendly default when you own one zone; a user with MORE THAN ONE zone MUST name one here (the door refuses-and-lists rather than silently pick `default`, §21.9/S4) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd) |
| `--go` |  |  |  | DRIVE the plan to completion (spends quota); omit for a free dry-run preview |
| `--transport` | MODE |  |  | per-run transport override (G7): 'subscription' \| 'api' \| 'key:<namespace>:<name>'. Forces the subscription, the scope's assigned api key, or a specific assigned handle. Selects a MODE / a handle, never a user (I3). Default: the workspace→zone→user→global cascade decides (an assigned key → api-key transport; else the entitled subscription). |
| `--outline` | FILE |  |  | drive an authored/edited outline file (DR-3 ingest leg); identical to `pipeline outline drive FILE` |
| `--from` | AID |  |  | the emit-outline HANDLE to verify the driven outline's config against (C7 §21.7) |
| `--allow-drift` |  |  |  | proceed under a config that differs from the emit-time config (downgrades the block) |
| `--save-selection` | ID |  |  | SAVE this run's fan-out as a replayable selection file selections/ID.md (§8, authoring D4) — works with or without --go. A client (x-) content/render binding homes under workspaces/<workspace>/selections/ (never the public root) |
| `--selection` | ID |  |  | DRIVE a saved selection selections/ID.md (or workspaces/<workspace>/selections/ for an x- id, §8/authoring D4) 1:1 — replays the EXACT saved fan-out, no re-expansion. Preview by default (spends nothing); add --go to drive. Mutually exclusive with the axis flags / --set / --recipe / --outline (a saved selection already fixes the run) |
| `--force` |  |  |  | overwrite an existing saved-selection file (default: refuse; --save-selection only) |

### `pipeline outline`

The friendly two-phase outline door (design §21, CLI-UX C3b): thin wrappers over the DR-3 emit-outline / begin-session ingest legs, via the direct-handler pattern (never registers a session verb; §21.9 preserved). Subcommands: emit, drive.

Usage: `pipeline outline` `<subcommand> ...`

#### `pipeline outline emit`

Realize an authored/edited outline as a viewable Format=outline artifact (CLI-UX C3b, DR-3 horn (a)): Tier-A, SPENDS NOTHING. Prints the emitted artifact-id — the continuation HANDLE. A re-emit of the same bytes is the idempotent no-op.

Usage: `pipeline outline emit` `file` [`--recipe RECIPE`] [`--topic ID`] [`--persona ID`] [`--voice ID`] [`--goals ID`] [`--set PATH=VALUE`] [`--workspace WORKSPACE`] [`--user USER`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `file` | file |  | yes | the authored outline Markdown file to emit (§15 substance floor) |
| `--recipe` | RECIPE |  |  | recipe id (default: explainer-post, §10) |
| `--topic` | ID |  |  | a topic id (repeatable) |
| `--persona` | ID |  |  | a persona id (repeatable) |
| `--voice` | ID |  |  | a voice id (repeatable) |
| `--goals` | ID |  |  | a goal id (repeatable → STACKS into one goal-set, §8) |
| `--set` | PATH=VALUE |  |  | a run override, e.g. voice.formality=2 (repeatable, §13.2) |
| `--workspace` | WORKSPACE |  |  | the invoked workspace (§21.1) |
| `--user` | USER |  |  | the owning user (§23 isolation prefix; required whenever --workspace is given) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/workspaces/<workspace>/ (default: cwd) |

#### `pipeline outline drive`

Ingest an authored/edited outline and DRIVE the plan to completion (CLI-UX C3b, DR-3 ingest leg). Identical to `pipeline generate --outline FILE`: the DEFAULT is a DRY-RUN (prints the plan + spend estimate and STOPS, spending nothing); add --go. Direct-handler pattern throughout — never registers a session verb (§21.9 preserved).

Usage: `pipeline outline drive` `file` [`--recipe RECIPE`] [`--topic ID`] [`--persona ID`] [`--format ID`] [`--voice ID`] [`--goals ID`] [`--platform ID`] [`--language ID`] [`--output-type ID`] [`--presentation ID`] [`--set PATH=VALUE`] [`--workspace WORKSPACE`] [`--user USER`] [`--zone ZONE`] [`--root ROOT`] [`--go`] [`--from AID`] [`--allow-drift`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `file` | file |  | yes | the authored/edited outline Markdown file to drive (DR-3 ingest leg) |
| `--recipe` | RECIPE |  |  | recipe id (default: explainer-post, §10) |
| `--topic` | ID |  |  | a topic id (repeatable) |
| `--persona` | ID |  |  | a persona id (repeatable) |
| `--format` | ID |  |  | a format id (repeatable) |
| `--voice` | ID |  |  | a voice id (repeatable) |
| `--goals` | ID |  |  | a goal id (repeatable → STACKS into one goal-set, §8) |
| `--platform` | ID |  |  | a render platform slug (repeatable → one deliverable each, §5) |
| `--language` | ID |  |  | a render language slug (repeatable → fans out, §5) |
| `--output-type` | ID |  |  | a render output-type slug (repeatable → fans out, §17) |
| `--presentation` | ID |  |  | a presentation slug (repeatable → fans out, §5.3) |
| `--set` | PATH=VALUE |  |  | a run override, e.g. voice.formality=2 or format.tags+=x (repeatable, §13.2) |
| `--workspace` | WORKSPACE |  |  | the invoked workspace (§21.1) |
| `--user` | USER |  |  | the owning user (§23 isolation prefix; required whenever --workspace is given) |
| `--zone` | ZONE |  |  | the §23/Z4 zone to spend in (users/<user>/zones/<zone>/workspaces/<W>/). OMIT for the friendly default when you own one zone; a user with MORE THAN ONE zone MUST name one here (the door refuses-and-lists rather than silently pick `default`, §21.9/S4) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd) |
| `--go` |  |  |  | DRIVE the plan to completion (spends quota); omit for a free dry-run preview |
| `--from` | AID |  |  | the emit-outline HANDLE to verify the driven outline's config against (C7 §21.7) |
| `--allow-drift` |  |  |  | proceed under a config that differs from the emit-time config (downgrades the block) |

### `pipeline list`

Enumerate a discovery type by name (design §21.3): recipes, voices, lexicons, outlines, codes, deliverables, artifacts, folios, … (see `pipeline list types`). Tier-A, READ-ONLY — spends nothing, mints no token. Direct-handler pattern (§21.9 preserved).

Usage: `pipeline list` `type` `--workspace WORKSPACE` `--user USER` [`--filters JSON`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `type` | type |  | yes | the discovery type to enumerate (see `pipeline list types`) |
| `--workspace` | WORKSPACE |  | yes | the invoked workspace (§21.1) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--filters` | JSON |  |  | §13.2 filters as JSON: a {field: value} map or a [{path,op,value}] pred list |
| `--root` | ROOT | `.` |  | framework repo root → workspaces/<workspace>/ (default: cwd) |

### `pipeline get`

Fetch one discovery entry by id (design §21.3): e.g. `get voices clear-explainer`. Tier-A, READ-ONLY — spends nothing. Enumerate-then-match keeps §10 isolation structural; the id-addressed rich `get` is on `pipeline invoke get`.

Usage: `pipeline get` `type` `id` `--workspace WORKSPACE` `--user USER` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `type` | type |  | yes | the discovery type (see `pipeline list types`) |
| `id` | id |  | yes | the entry id to fetch |
| `--workspace` | WORKSPACE |  | yes | the invoked workspace (§21.1) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--root` | ROOT | `.` |  | framework repo root → workspaces/<workspace>/ (default: cwd) |

### `pipeline docs`

Regenerate a committed framework reference doc from the code (authoring layer D12; LOCAL/operator only, never an HTTP door). Subcommands: attributes, cli.

Usage: `pipeline docs` `<subcommand> ...`

#### `pipeline docs attributes`

Regenerate docs/reference/attributes.md: a reference of what every framework registry attribute MEANS (its schema `definition:` prose, verbatim) and its type, floor default, and definition_version. Walks pipeline.lint.REGISTRY_ROOTS only (framework-only — no instance/client content); deterministic (sorted, no clock). A byte-equality CI test guards it against un-regenerated edits.

Usage: `pipeline docs attributes` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT |  |  | framework repo root (default: the installed package's own repo root) |

#### `pipeline docs cli`

Regenerate docs/reference/cli.md: a reference of EVERY `pipeline` command and subcommand — each one's description, a usage synopsis, and every flag/argument (with its default, whether it is required, and its help) — rendered from the live argparse tree that `build_parser()` returns (the SAME tree the runtime `--help` walks). Deterministic (definition-order; no clock, env, cwd, or terminal width); a byte-equality CI test (tests/test_cli_doc_contract.py) fails loudly if a command or flag changes without regenerating. LOCAL/operator only, never an HTTP door (§21.9).

Usage: `pipeline docs cli` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT |  |  | framework repo root (default: the installed package's own repo root) |

### `pipeline recipe`

The friendly recipe authoring/derive door (authoring layer C2b, design §8): the first consumer of the C2a authoring core. LOCAL Tier-A file write — never an invoke verb / HTTP door (§21.9). Subcommand: new.

Usage: `pipeline recipe` `<subcommand> ...`

#### `pipeline recipe new`

Author (or derive with --from) one schema-conforming recipe file (design §8) from the unified grammar: by-name axis PICKS (mention REPLACES the slot's set, repeat to accumulate), --set path=value TWEAKS a configured value (values only), --unset PATH CLEARS an axis slot (1 segment) or a value binding (2 segments). Provenance is inferred over every binding: framework-only homes public (recipes/<id>.md); a client (x-) binding REFUSES into public and homes under workspaces/<ws>/recipes/x-<id>.md. Refuse-if-exists unless --force. NEVER spends quota (never an invoke verb; §21.9).

Usage: `pipeline recipe new` `id` [`--from BASE`] [`--topic ID`] [`--persona ID`] [`--format ID`] [`--voice ID`] [`--goals ID`] [`--platform ID`] [`--language ID`] [`--output-type ID`] [`--presentation ID`] [`--set PATH=VALUE`] [`--unset PATH`] [`--workspace WORKSPACE`] [`--user USER`] [`--root ROOT`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `id` | id |  | yes | the recipe id to write (§7.4 slug; the filename stem) |
| `--from` | BASE |  |  | seed from an existing recipe → a standalone derived file (loud on unknown) |
| `--topic` | ID |  |  | bind a topic (repeatable) |
| `--persona` | ID |  |  | bind a persona (repeatable) |
| `--format` | ID |  |  | bind a format (repeatable) |
| `--voice` | ID |  |  | bind a voice (repeatable) |
| `--goals` | ID |  |  | bind a goal (repeatable → STACKS the goal-set, §8) |
| `--platform` | ID |  |  | pin a render platform (repeatable → REPLACES the set, §5) |
| `--language` | ID |  |  | pin a render language (repeatable → REPLACES the set, §5) |
| `--output-type` | ID |  |  | pin a render output-type (repeatable → REPLACES the set, §17) |
| `--presentation` | ID |  |  | pin a render presentation (repeatable → REPLACES the set, §5.3) |
| `--set` | PATH=VALUE |  |  | tweak a configured value, e.g. voice.formality=2 or format.tags+=x (repeatable) |
| `--unset` | PATH |  |  | clear an axis slot (1 seg: voice) or a value binding (2 seg: voice.formality) |
| `--workspace` | WORKSPACE |  |  | the workspace home for a client (x-) recipe (§10); framework recipes need none |
| `--user` | USER |  |  | the owning user (§23) for a client (x-) recipe home; required with --workspace |
| `--root` | ROOT | `.` |  | framework repo root → recipes/<id>.md (default: cwd) |
| `--force` |  |  |  | overwrite an existing recipe file (default: refuse) |

### `pipeline entry`

The friendly dimension-entry scaffolder (authoring layer C3, design D11): a second consumer of the C2a authoring core. LOCAL Tier-A file write — never an invoke verb / HTTP door (§21.9). Subcommand: new.

Usage: `pipeline entry` `<subcommand> ...`

#### `pipeline entry new`

Scaffold ONE new dimension entry (design D11) from a schema-conforming, self-documenting skeleton: the envelope + EVERY attribute at its schema floor + each attribute's `definition:` prose as inline #-comments (the same guidance `docs attributes` surfaces). A floor-only entry lints GREEN unedited. --workspace W homes an instance entry (x--prefixed, provenance instance) under workspaces/<W>/<dimension>/x-<id>.md; without it, a framework-default candidate (<dimension>/<id>.md, provenance framework) for a deliberate human commit. `entry new topic` REQUIRES --workspace (topics are workspace editorial data). Refuse-if-exists unless --force. NEVER spends quota (never an invoke verb; §21.9).

Usage: `pipeline entry new` `dimension` `id` [`--workspace WORKSPACE`] [`--user USER`] [`--zone ZONE`] [`--root ROOT`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `dimension` | dimension |  | yes | the dimension token (persona/format/voice/goal/platform/language/output-type/presentation/topic) |
| `id` | id |  | yes | the entry id to write (§7.4 slug; the filename stem) |
| `--workspace` | WORKSPACE |  |  | home an instance (x-) entry under users/<user>/workspaces/<W>/ (required for `topic`); a framework-default candidate needs none |
| `--user` | USER |  |  | the owning user (§23) for a client (x-) entry home; required with --workspace |
| `--zone` | ZONE | `default` |  | the zone the --workspace lives in (§23; users/<user>/zones/<zone>/workspaces/<W>/, default: default). Ignored for a framework-default entry (no --workspace). |
| `--root` | ROOT | `.` |  | framework repo root → <dimension>/<id>.md (default: cwd) |
| `--force` |  |  |  | overwrite an existing entry file (default: refuse) |

### `pipeline workspace`

The friendly local workspace lifecycle (design §23) over the self-contained users/<user>/workspaces/<workspace>/ layout. LOCAL Tier-A file ops — never an invoke verb / HTTP door (§21.9). Subcommands: new, list, delete.

Usage: `pipeline workspace` `<subcommand> ...`

#### `pipeline workspace new`

Seed ONE new client workspace users/<user>/workspaces/<workspace>/ by copying the shared framework blueprint templates/workspace/ (design §23; the friendly form of `cp -R templates/workspace users/<user>/workspaces/<ws>`). --user is REQUIRED (the §23 isolation prefix); the user namespace is auto-created on demand (a brand-new user home is announced so a mistyped --user is visible). Refuse-if-exists unless --force; --force NEVER overwrites an existing file (the copy is non-destructive — it only tops up MISSING blueprint files, never deletes client data). Then edit source.md (the graph path) and add topics. NEVER spends quota (never an invoke verb; §21.9).

Usage: `pipeline workspace new` `workspace` `--user USER` [`--zone ZONE`] [`--root ROOT`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `workspace` | workspace |  | yes | the workspace name to create (§23 lowercase-safe segment; the directory name) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/workspaces/<workspace>/) |
| `--zone` | ZONE | `default` |  | the zone segment between user and workspace (§23; users/<user>/zones/<zone>/workspaces/<ws>/, default: default). A brand-new zone is auto-created and announced so a mistyped --zone is visible. |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/<workspace>/ (default: cwd) |
| `--force` |  |  |  | proceed if the workspace exists — seeds only MISSING files, never overwrites (default: refuse) |

#### `pipeline workspace list`

READ-ONLY: list workspaces under users/. With --user, list that one user's workspaces; without it, scan EVERY user (users/*/workspaces/*), each row shown as <user>/<workspace> (workspaces are discovered by scanning — no global index). Each row carries a light TRUE summary: the authored-topic count and whether the workspace holds generated output. A missing/empty users/ prints 'no workspaces found' (exit 0), never a traceback. Mutates nothing (never an invoke verb; §21.9).

Usage: `pipeline workspace list` [`--user USER`] [`--zone ZONE`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--user` | USER |  |  | restrict to one user's workspaces (§23 lowercase-safe segment; default: all users) |
| `--zone` | ZONE |  |  | restrict to one zone across the selected user(s) (§23; default: ALL zones) |
| `--root` | ROOT | `.` |  | framework repo root → users/ (default: cwd) |

#### `pipeline workspace delete`

DESTRUCTIVE, SAFE-BY-DEFAULT: remove ONE workspace users/<user>/workspaces/<workspace>/. --user is REQUIRED. Validates + resolves + contains the target via the isolation gate, REFUSES a non-existent target, and NEVER deletes through a symlink (removes only the validated contained real directory). Tier-1 confirmation is ALWAYS required: interactively you TYPE the workspace name (a mismatch aborts); headless you pass --yes. Tier-2: a workspace holding GENERATED output (spent work/money) is refused even with --yes unless --force is ALSO passed. On success, users/<user>/ and workspaces/ are left in place. LOCAL file op (never an invoke verb; §21.9).

Usage: `pipeline workspace delete` `workspace` `--user USER` [`--zone ZONE`] [`--yes`] [`--force`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `workspace` | workspace |  | yes | the workspace name to delete (§23 lowercase-safe segment; the directory name) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/workspaces/<workspace>/) |
| `--zone` | ZONE | `default` |  | the zone the workspace lives in (§23; users/<user>/zones/<zone>/workspaces/<ws>/, default: default) |
| `--yes` |  |  |  | supply the confirmation non-interactively (skip the type-the-name prompt) |
| `--force` |  |  |  | ALSO required (with --yes) to delete a workspace holding generated output |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/workspaces/<workspace>/ (default: cwd) |

### `pipeline user`

The explicit per-user namespace setup (design §23): create users/<user>/workspaces/ (the extensible per-user home) without a workspace. LOCAL Tier-A file op — never an invoke verb / HTTP door (§21.9). Subcommand: new.

Usage: `pipeline user` `<subcommand> ...`

#### `pipeline user new`

Create the empty per-user namespace users/<user>/workspaces/ (design §23) — the extensible per-user home, set up explicitly BEFORE any workspace exists. <user> is a §23 lowercase-safe segment. Refuse-if-exists unless --force (a safe no-op; deletes nothing). NEVER spends quota (never an invoke verb; §21.9).

Usage: `pipeline user new` `user` [`--root ROOT`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `user` | user |  | yes | the user name to create (§23 lowercase-safe segment) → users/<user>/workspaces/ |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/workspaces/ (default: cwd) |
| `--force` |  |  |  | proceed if the namespace exists — a safe no-op, never deletes (default: refuse) |

### `pipeline zone`

The friendly per-zone lifecycle (design §23) over users/<user>/zones/<zone>/workspaces/. A zone groups a user's workspaces (it sits between user and workspace). LOCAL Tier-A file ops — never an invoke verb / HTTP door (§21.9). Subcommands: new, list, delete.

Usage: `pipeline zone` `<subcommand> ...`

#### `pipeline zone new`

Create ONE new zone users/<user>/zones/<zone>/workspaces/ — the per-zone workspace home (design §23). --user is REQUIRED (the §23 isolation prefix); the user namespace is auto-created on demand (a brand-new user home is announced so a mistyped --user is visible). Refuse-if-exists unless --force (a safe no-op). NEVER spends quota (never an invoke verb; §21.9).

Usage: `pipeline zone new` `zone` `--user USER` [`--root ROOT`] [`--force`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `zone` | zone |  | yes | the zone name to create (§23 lowercase-safe segment; the directory name) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/zones/<zone>/workspaces/) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/ (default: cwd) |
| `--force` |  |  |  | proceed if the zone exists — a safe no-op, never deletes (default: refuse) |

#### `pipeline zone list`

READ-ONLY: list zones under users/. With --user, list that one user's zones; without it, scan EVERY user (users/*/zones/*), each row shown as <user>/<zone> with the count of workspaces the zone contains. A missing/empty users/ prints 'no zones found' (exit 0), never a traceback. Mutates nothing (never an invoke verb; §21.9).

Usage: `pipeline zone list` [`--user USER`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--user` | USER |  |  | restrict to one user's zones (§23 lowercase-safe segment; default: all users) |
| `--root` | ROOT | `.` |  | framework repo root → users/ (default: cwd) |

#### `pipeline zone delete`

DESTRUCTIVE, RECURSIVE, SAFE-BY-DEFAULT: remove ONE zone users/<user>/zones/<zone>/ AND every workspace it contains. --user is REQUIRED. Validates + resolves + contains the zone via the isolation gate, REFUSES a non-existent zone, and NEVER deletes through a symlink (removes only the validated contained real zone dir). Tier-1 confirmation is ALWAYS required: interactive: TYPE the zone name (a mismatch aborts); headless you pass --yes. Tier-2 (STRICTER, because recursive): if ANY contained workspace holds GENERATED output (spent work/money) the whole zone is refused even with --yes unless --force is ALSO passed. On success, users/<user>/ is left in place. LOCAL file op (never an invoke verb; §21.9).

Usage: `pipeline zone delete` `zone` `--user USER` [`--yes`] [`--force`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `zone` | zone |  | yes | the zone name to delete (§23 lowercase-safe segment; the directory name) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/zones/<zone>/) |
| `--yes` |  |  |  | supply the confirmation non-interactively (skip the type-the-zone-name prompt) |
| `--force` |  |  |  | ALSO required (with --yes) to delete a zone whose workspaces hold generated output |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/ (default: cwd) |

### `pipeline sources`

The out-of-band acquisition maintenance door (design §6; sources P2/P3): fetch a workspace's source(s), normalize + dedup + θ-gate, and SEAL into the local sealed cache. Feed kinds are LOCAL Tier-A (free HTTP, $0 model spend); the `research` kind SPENDS subscription LLM tokens and is dry-run by default (needs --go). Subcommand: ingest.

Usage: `pipeline sources` `<subcommand> ...`

#### `pipeline sources ingest`

Resolve the workspace's descriptor(s) under sources/feeds/<id>.yaml and run each through fetch → normalize → dedup + θ-gate → SEAL (advancing the namespace HEAD). Idempotent: a re-ingest of unchanged feed content is a content-addressed no-op. Writes only the gitignored sealed cache under the workspace (rule-1 carve-out); reads every source read-only. Feed kinds spend NOTHING (free HTTP; $0 model spend). The `research` kind SPENDS subscription LLM tokens: WITHOUT --go it DRY-RUNS (prints acquire-scope, spends nothing); WITH --go it drives the paid loop under a hard cost ceiling + θ-stop. Known kinds: commoncrawl, edgar, gdelt, research, rss (research is the paid one).

Usage: `pipeline sources ingest` `workspace` `--user USER` [`--source ID`] [`--root ROOT`] [`--zone ZONE`] [`--go`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `workspace` | workspace |  | yes | the workspace to acquire into (§21.1) |
| `--user` | USER |  | yes | the owning user (§23 isolation prefix; users/<user>/…) |
| `--source` | ID |  |  | a single source id under sources/feeds/ (default: every descriptor) |
| `--root` | ROOT | `.` |  | framework repo root → users/<user>/zones/<zone>/workspaces/<ws>/ (def: cwd) |
| `--zone` | ZONE | `default` |  | the zone segment between user and workspace (§23; users/<user>/zones/<zone>/workspaces/<ws>/, default: default) |
| `--go` |  |  |  | approve the PAID research loop's cost ceiling and DRIVE it (research sources only; feeds are always free and ignore --go). Omit for a dry-run acquire-scope estimate that SPENDS NOTHING. |

### `pipeline transport`

Key-assignment admin (plan G4, §21.10). Tier-A LOCAL file ops over the gitignored instance/ops/transport/config.yaml — never an invoke verb / HTTP door / spend. Each assignment maps an EXPLICIT (scope-level, scope-id) to a keystore HANDLE (a non-secret reference) + a HARD weekly dollar cap. `store-key` puts the SECRET VALUE in the keystore (read from stdin/getpass, NEVER argv). Subcommands: store-key, assign-key, list-keys, clear-key.

Usage: `pipeline transport` `<subcommand> ...`

#### `pipeline transport store-key`

Store a secret VALUE in the 0600-per-handle keystore under $OPTIQUITY_SECRETS_DIR (default ~/.optiquity/secrets/), referenced everywhere else by the NON-secret handle '<namespace>:<name>'. The VALUE is read from STDIN — a HIDDEN getpass prompt when stdin is a TTY, else the piped bytes with a single trailing newline stripped (or --from-file PATH). There is DELIBERATELY no --value/--secret flag: a secret on argv lands in `ps`, the process table, and your shell history. Overwriting an existing handle ROTATES it. Announces created-vs-updated with the HANDLE + store path — NEVER the value (I5). Tier-A: spends nothing; resolves no transport.

Usage: `pipeline transport store-key` `--handle HANDLE` [`--from-file PATH`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--handle` | HANDLE |  | yes | the keystore handle '<namespace>:<name>' to store under (a NON-secret ref; e.g. anthropic:acme) |
| `--from-file` | PATH |  |  | read the secret VALUE from this file's bytes instead of stdin (still NEVER from argv); a single trailing newline is stripped |

#### `pipeline transport assign-key`

Assign (or replace) a keystore HANDLE for one EXPLICIT scope (global | user:<u> | zone:<u>/<z> | workspace:<u>/<z>/<ws>). The scope-id is PARSED from --scope, never derived from a users/ path (M3, §23 addressing purity). --weekly-cap is HARD-REQUIRED (S3): a missing cap is a loud refusal and NOTHING is written — no silent default cap. The handle is a non-secret ref; NO secret is read/stored/printed. Spends nothing.

Usage: `pipeline transport assign-key` `--scope SCOPE` `--handle HANDLE` [`--weekly-cap WEEKLY_CAP`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--scope` | SCOPE |  | yes | global \| user:<u> \| zone:<u>/<z> \| workspace:<u>/<z>/<ws> (parsed EXPLICITLY, M3) |
| `--handle` | HANDLE |  | yes | the keystore handle '<namespace>:<name>' (a NON-secret ref; e.g. anthropic:acme) |
| `--weekly-cap` | WEEKLY_CAP |  |  | the HARD weekly dollar cap, e.g. 50 (S3: REQUIRED — no default; no uncapped key) |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport list-keys`

READ-ONLY: list every key assignment as scope + handle + weekly cap. A handle is a non-secret reference — no secret is ever printed. A missing/empty config prints 'no key assignments' (exit 0). Mutates nothing, spends nothing (§21.9).

Usage: `pipeline transport list-keys` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport clear-key`

Remove the key assignment for one EXPLICIT scope (same --scope grammar as assign). Idempotent: clearing an unassigned scope is a clean no-op (exit 0). NOTHING spends.

Usage: `pipeline transport clear-key` `--scope SCOPE` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--scope` | SCOPE |  | yes | global \| user:<u> \| zone:<u>/<z> \| workspace:<u>/<z>/<ws> (parsed EXPLICITLY, M3) |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport set-subscription-user`

Name the SINGLE user entitled to the subscription fallback (ToS: subscription is used ONLY for this one user, G5). Validates the user segment (§23); REPLACES any prior entitled user — never a second entry. The entitled user is set ONLY here (an admin/config verb) — NEVER via a run/spend verb (I2/I3). Tier-A: spends nothing, resolves no transport. A bad / uppercase / empty user is a loud refusal, NOTHING written.

Usage: `pipeline transport set-subscription-user` `user` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `user` | user |  | yes | the entitled subscription user segment (lowercase, one path segment; §23) |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport clear-subscription-user`

Remove the entitled subscription user (G5). Idempotent: clearing an unset entitlement is a clean no-op (exit 0). Preserves the key assignments (one shared config). Tier-A: spends nothing.

Usage: `pipeline transport clear-subscription-user` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport set-umbrella-cap`

Set the SINGLE install-wide UMBRELLA weekly cap (plan G6): a HARD ceiling bounding the WHOLE install's weekly spend on top of every per-bucket cap. The amount is REQUIRED and must be a POSITIVE dollar amount — an absent / zero / negative amount is a loud refusal with NOTHING written (no uncapped umbrella). Swappable, single-valued; preserves the key assignments + entitlement (one shared config). Tier-A admin: resolves no transport, spends nothing (the meter that ENFORCES it is pure bookkeeping until G7).

Usage: `pipeline transport set-umbrella-cap` [`amount`] [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `amount` | amount |  |  | the HARD install-wide weekly umbrella cap, e.g. 200 (REQUIRED; a positive amount) |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport clear-umbrella-cap`

Remove the install-wide umbrella weekly cap (G6). Idempotent: clearing an unset umbrella is a clean no-op (exit 0). Preserves the key assignments + entitlement (one shared config). Tier-A: spends nothing.

Usage: `pipeline transport clear-umbrella-cap` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |

#### `pipeline transport show`

READ-ONLY combined view: the SINGLE entitled subscription user (if any), the install-wide umbrella weekly cap (if any), plus every key assignment (scope + handle + cap; NEVER a secret). Mutates + spends nothing.

Usage: `pipeline transport show` [`--root ROOT`]

| argument | value | default | required | description |
| --- | --- | --- | --- | --- |
| `--root` | ROOT | `.` |  | framework repo root → instance/ops/transport/config.yaml (default: cwd) |
