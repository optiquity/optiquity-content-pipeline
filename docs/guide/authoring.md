# Authoring and running

This is the hands-on guide to the **friendly local CLI** — the English-ish operator surface you
drive with `scripts/pipeline` (or `uv run pipeline`). Every command here is a *door* onto the same
verbs the engine runs; these doors just take readable flags instead of raw JSON, and they are built
so that **the expensive thing never happens by accident**. For the vocabulary behind the flags
(recipes, selections, the cascade, artifacts vs. deliverables) read [Concepts](concepts.md) first;
for what every tunable attribute *means* see the [attribute reference](../reference/attributes.md).

## Money-safety comes first: dry-run by default, `--go` is the only spend

The single most important thing about this surface is what it costs, so read this before anything
else:

- **Nothing spends unless you type `--go`.** `preview` spends nothing, ever. `generate` is a
  **dry-run by default** — it prints the exact same plan a `preview` would and then *stops*. Only
  adding `--go` drives the plan to completion, and driving it is the *only* path that spends.
- **Spend is subscription-only.** Composition runs through your local Claude Code CLI on your Claude
  **subscription** — never an API key, never `ANTHROPIC_API_KEY`. The engine will not reach for a
  paid API.
- **The remote door stays closed.** These friendly commands are local operator doors; none of them
  is an HTTP verb, so a cloud orchestrator can never trip a spend through them (the remote surface is
  the separate, login-gated [HTTP shim](interfaces.md#http-access-cloud-orchestrators), and even it
  refuses to start without an auth secret).
- **Every plan tells you the bill in advance.** A dry-run always ends with `spend-scope: N paid
  artifact(s)` — the exact count of paid pieces the run would compose — so you approve a number, not
  a surprise.

The rhythm, then, is always the same: **preview → dry-run → read the count → add `--go`.**

## The friendly doors at a glance

| Door | What it does | Spends? |
|------|--------------|---------|
| `pipeline workspace new` / `list` / `delete` | scaffold a workspace from the blueprint, list them, or safely remove one (`delete` needs confirmation + `--force` over generated output) | never |
| `pipeline user new` | create an empty per-user namespace | never |
| `pipeline preview` | plan-only: effective settings + the plan + the paid count | never |
| `pipeline generate` | dry-run by default; `--go` drives + spends | only with `--go` |
| `pipeline recipe new` | author a reusable starting point (a recipe file) | never |
| `pipeline entry new` | scaffold a new persona/format/voice/… entry | never |
| `pipeline outline emit` / `drive` | realize, then drive, an editable outline | emit never; drive only with `--go` |
| `pipeline list` / `get` | read-only discovery | never |
| `pipeline docs attributes` | regenerate the attribute reference | never |

Everything below walks these in the order you would actually use them. Run any of them with
`--help` for the authoritative flag list — the CLI's own help is the source of truth, and these
pages track it.

**`--user` is required with `--workspace`.** Every workspace lives at
`users/<user>/workspaces/<workspace>/` (§23), so any command that names a `--workspace` must also
name its owning `--user` — a missing `--user` is a usage error, never a default. The examples below
use `--user <you> --workspace myrepo`; substitute your own owner and workspace.

## Step 1 — Preview the plan (spends nothing)

`preview` takes your picks and prints three things: the **effective settings** (and which cascade
layer set each), the **plan** (the artifact and deliverable ids it would produce), and the
**spend-scope** — the count of paid pieces. It spends nothing.

The minimal first run leans on the default recipe (`explainer-post`) and one topic you authored in
your workspace:

```bash
uv run pipeline preview --topic <your-topic> --user <you> --workspace myrepo
```

A fuller pick names the axes explicitly:

```bash
uv run pipeline preview \
  --topic <your-topic> \
  --persona product-manager \
  --format readme \
  --voice clear-explainer \
  --goals explain \
  --user <you> --workspace myrepo
```

Output looks like this (trimmed):

```text
=== preview: user=<you> workspace=myrepo recipe=explainer-post ===
effective settings (which cascade layer set each):
  a-5dc2cbd9676240e9
    topic        : <your-topic>  [why=L1-entry-default]
    persona      : product-manager  [knowledge_level=L1-entry-default, role=L1-entry-default, …]
    format       : readme
    voice        : clear-explainer
    goals        : explain
plan:
  artifact-ids   : ['a-5dc2cbd9676240e9']
  deliverable-ids: []
spend-scope: 1 paid artifact(s)
```

Read `spend-scope` as the price tag. Content axes (`--topic/--persona/--format/--voice`) are
repeatable and each combination fans out into its own paid artifact; `--goals` is the exception —
repeat it and the goals **stack into one** goal-set rather than fanning out. Render axes
(`--platform/--language/--output-type/--presentation`) fan out into deliverables *of* an artifact,
so they add rendering work but not new paid composes.

## Step 2 — Generate (dry-run first, then `--go`)

`generate` takes the **same flags** as `preview`. With no `--go` it is a dry-run identical to
preview — the plan and the count, and nothing spent:

```bash
uv run pipeline generate --topic <your-topic> --user <you> --workspace myrepo
```

It ends with an explicit reminder:

```text
spend-scope: 1 paid artifact(s)

(dry-run: nothing spent — re-run with --go to drive the plan to completion)
```

When the count is what you intended, add `--go` — and *only* then does it spend subscription quota
to compose (and, if you gave render axes, render):

```bash
uv run pipeline generate --topic <your-topic> --platform github --user <you> --workspace myrepo --go
```

Other `generate` flags you will reach for: `--set path=value` for run overrides (next step),
`--outline FILE` / `--from AID` to drive an authored outline (Step 7), `--save-selection` /
`--selection` to save or replay a fan-out (Step 5), and `--force` to overwrite a saved-selection
file. `--allow-drift` is an escape hatch for the outline drift guard, used on purpose.

## Step 3 — Tune at run time with `--set`

`--set PATH=VALUE` binds a one-off value on top of everything else, just for this run. It is the
ephemeral top of the cascade — captured in the artifact's identity, never persisted. The path is
`dimension.attribute`; repeat `--set` for several tweaks:

```bash
uv run pipeline preview \
  --topic <your-topic> --user <you> --workspace myrepo \
  --set voice.formality=5 \
  --set voice.warmth=2
```

The voice **sliders** — `formality`, `humor`, `warmth`, `energy`, each `1`–`5` — are the most common
thing to tune this way. What each level *means* is spelled out in the
[attribute reference](../reference/attributes.md) (regenerate it any time with `pipeline docs
attributes`; see below). A `--set` can also use the type-driven combine operators, e.g.
`--set format.tags+=launch` to add a tag rather than replace the set. For the full path/operator
grammar see the [operator grammar reference](../reference/operator-grammar.md).

## Step 4 — Save a recipe (`pipeline recipe new`)

A **recipe** is a reusable, *partial* starting point — a saved set of axis picks plus tweaks that
`generate --recipe` builds on. It is not a full run description; it binds only the slots it sets, and
everything it leaves unset falls through the workspace, global, entry, and schema defaults. (Contrast
this with a saved selection in Step 5, which is a concrete "generate exactly these N" list.)

`recipe new` writes one schema-conforming recipe file from a single **edit grammar**:

- **Axis PICKS** — `--topic/--persona/--format/--voice/--goals` plus the render axes
  `--platform/--language/--output-type/--presentation`. Naming an axis **replaces** whatever that
  slot held; repeat the flag to accumulate several values into the slot (`--goals` stacks into one
  goal-set).
- **`--set path=value`** — TWEAK a configured value (values only), e.g. `--set voice.formality=2`.
- **`--unset PATH`** — CLEAR a slot (one segment, e.g. `--unset voice`) or a single value binding
  (two segments, e.g. `--unset voice.formality`).
- **`--from BASE`** — seed from an existing recipe and MATERIALIZE a standalone derived file (a full
  copy with your edits applied, never a base+delta link; an unknown base refuses loudly).

```bash
uv run pipeline recipe new launch-readme \
  --persona product-manager \
  --format readme \
  --voice clear-explainer \
  --set voice.formality=4
```

That writes `recipes/launch-readme.md`. Provenance is **inferred over every binding**: a
framework-only recipe homes public at `recipes/<id>.md`; the moment a binding references a client
(`x-`) entry, the recipe refuses to land in the public repo and homes under the workspace instead —
`users/<user>/workspaces/<ws>/recipes/x-<id>.md` — which requires `--user U --workspace W`. `recipe new` **refuses if the
file exists** unless you pass `--force`, and it **never spends** (it is a local file write, not a
paid verb).

## Step 5 — Save and replay a selection (`--save-selection` / `--selection`)

Where a recipe is a partial *starting point*, a **saved selection** is a concrete *list*: "generate
exactly these N deliverables." Save one by adding `--save-selection ID` to a `generate` run (it works
with or without `--go`):

```bash
uv run pipeline generate \
  --topic <your-topic> --platform github \
  --user <you> --workspace myrepo --save-selection my-diagonal
```

The saved file is `{base: <recipe ref>, variants: [...]}` — one delta per resulting deliverable, each
pinning its own content picks, its render coordinate, and any shared `--set` values from the run. The
`base` stays a **reference** to the recipe (not a frozen copy), so if you edit that recipe later, a
replay surfaces the change as a new version rather than silently serving a stale one.

> A selection replays a **fan-out**, so the run must resolve at least one deliverable — give it a
> render axis such as `--platform`, or `--save-selection` has nothing to save. And, as with recipes,
> a client (`x-`) binding homes the selection under `users/<user>/workspaces/<ws>/selections/` and takes an `x-`
> id.

Replay it 1:1 with `--selection ID` — the exact saved set, with **no cartesian re-expansion**, so a
curated diagonal stays a diagonal:

```bash
uv run pipeline generate --selection my-diagonal --user <you> --workspace myrepo        # dry-run
uv run pipeline generate --selection my-diagonal --user <you> --workspace myrepo --go   # drive it
```

`--selection` is mutually exclusive with the axis flags / `--set` / `--recipe` / `--outline` — a
saved selection already fixes the whole run.

## Step 6 — Author a new entry (`pipeline entry new`)

Need a new persona, format, voice, goal, platform, language, output-type, presentation, or topic?
`entry new DIMENSION ID` scaffolds one from a **self-documenting skeleton**: the envelope, every
attribute at its schema floor, and each attribute's `definition:` prose inline as `#`-comments (the
same guidance the attribute reference surfaces). A floor-only entry **lints green** unedited, so you
can scaffold first and fill in what you want to change.

```bash
uv run pipeline entry new voice warm-mentor --user <you> --workspace myrepo
```

`--user U --workspace W` homes an **instance** entry (auto-prefixed `x-`, `provenance: instance`) under
`users/<U>/workspaces/<W>/<dimension>/x-<id>.md`. **Without** `--workspace` it writes a framework-default
candidate (`<dimension>/<id>.md`, `provenance: framework`) for a deliberate human commit into the
public repo. One special case: `entry new topic` **requires** `--user`+`--workspace`, because topics are
per-workspace editorial data. (Whenever `--workspace` is given, `--user` is mandatory.) As with recipes, it refuses if the file exists unless `--force`, and it
never spends.

## Step 7 — Author with an editable outline (`pipeline outline emit` / `drive`)

Sometimes you want to shape a piece's structure before you pay to write it. The optional two-phase
outline flow lets you: **emit** an authored outline as a viewable artifact, review/edit it, then
**drive** it into a full compose.

```bash
# realize the outline as a viewable artifact — SPENDS NOTHING — and print a --from handle
uv run pipeline outline emit my-outline.md --topic <your-topic> --user <you> --workspace myrepo
```

`emit` prints the artifact id (the continuation **handle**) and a copy-paste drive line:

```text
=== outline emit: user=<you> workspace=myrepo recipe=explainer-post ===
artifact-id: a-a5046e6c1423f2e3
handle     : a-a5046e6c1423f2e3
— drive with: pipeline generate --outline my-outline.md --from a-a5046e6c1423f2e3 --go
```

Then `drive` ingests the outline and drives the plan — **dry-run by default, `--go` to spend** —
just like `generate`. Carry the emit handle with `--from AID` so the drift guard refuses to spend if
your config has drifted from the emit; `--allow-drift` proceeds on purpose:

```bash
uv run pipeline outline drive my-outline.md --from a-a5046e6c1423f2e3 --user <you> --workspace myrepo --go
```

`outline drive FILE` is exactly `generate --outline FILE` — same behavior, two spellings. Either way
an outline asserts no new facts; it only steers structure and emphasis.

## Step 8 — Discover what's there (`pipeline list` / `get`)

`list` and `get` are **read-only** — they spend nothing and mint no token. `list <type>` enumerates a
discovery type; run `pipeline list types` for the full set (recipes, voices, lexicons, outlines,
deliverables, artifacts, folios, …):

```bash
uv run pipeline list types --user <you> --workspace myrepo
uv run pipeline list recipes --user <you> --workspace myrepo
```

```text
=== list recipes: 2 entry(ies) — user=<you> workspace=myrepo ===
  explainer-post  provenance=framework path=recipes/explainer-post.md
  project-manual  provenance=framework path=recipes/project-manual.md
```

`get <type> <id>` fetches one entry:

```bash
uv run pipeline get voices clear-explainer --user <you> --workspace myrepo
```

```text
=== get voices clear-explainer — workspace=myrepo ===
  id: clear-explainer
  path: voices/clear-explainer.md
  provenance: framework
```

## The attribute reference and voice sliders (`pipeline docs attributes`)

Everything you can pick or `--set` is a schema attribute, and each one carries a prose `definition:`.
`pipeline docs attributes` regenerates [`docs/reference/attributes.md`](../reference/attributes.md) —
the reference of what every framework registry attribute *means*, verbatim from the schema, plus its
type, floor default, and version:

```bash
uv run pipeline docs attributes
```

It is the place to understand the **voice sliders** (`formality`, `humor`, `warmth`, `energy`, each
`1`–`5`), which the reference now describes level by level — for example `formality`: `1` casual, `3`
neutral-professional (the default), `5` formal/institutional. Read the level you want, then tune it
at run time:

```bash
uv run pipeline generate --topic <your-topic> --user <you> --workspace myrepo --set voice.formality=5
```

The generator walks framework registries only (no client content) and is deterministic, so a
re-run over an unchanged tree rewrites identical bytes.

## Diagrams and the diagram-disposition knob

An artifact can carry a grounded `{type=diagram}` section — a node/edge list the pipeline draws,
where **every edge is cited** back to a fact. Whether a given genre gets one is controlled by the
Format's **diagram-disposition** knob, tunable per run with
`--set format.diagram_disposition=<value>`:

- **(default, neutral)** — the writer decides; today's behavior. The floor leaves the choice open.
- **`require`** — the compose must ship a **grounded** diagram that passes the hard grounding gate,
  or it **refuses**. An illustrative sketch never satisfies `require`.
- **`suppress`** — a hard guarantee of **no** diagram section.
- **`resist`** / **`prefer`** — **soft** nudges against / toward a diagram, without guaranteeing the
  outcome.

```bash
# demand a grounded diagram or refuse the compose:
uv run pipeline generate --topic <your-topic> --user <you> --workspace myrepo --set format.diagram_disposition=require

# guarantee no diagram:
uv run pipeline preview --topic <your-topic> --user <you> --workspace myrepo --set format.diagram_disposition=suppress
```

A value outside the allowed set is refused **before any writer call** (closed-schema validation at
plan resolution), so a typo costs nothing.

---

Where to go next: [Getting started](getting-started.md) for the first-run setup, the
[Interfaces guide](interfaces.md) for the local-CLI-vs-HTTP map, [Concepts](concepts.md) for the
vocabulary, and the [attribute reference](../reference/attributes.md) for every tunable field.

[← Manual home](../../README.md) · Related: [Getting started](getting-started.md) · [Interfaces](interfaces.md) · [Concepts](concepts.md) · [Attribute reference](../reference/attributes.md)
</content>
