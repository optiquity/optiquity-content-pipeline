# Operating model — public framework + private instances

How to run this as an **open-source framework you maintain** plus **private instances** (yours and,
if you like, others') that pull your improvements non-destructively.

> **Authority:** provenance/scope authority now lives in `docs/design.md` §10; this document is the
> conforming two-repo how-to.

## The two repos

| Repo | Contains | Never contains |
|---|---|---|
| **Public framework** (MIT) | `CLAUDE.md`, `docs/`, `*.template.*` registry files, `.claude/` agents+skills, `scripts/`, `templates/workspace/`, QuickStart | Any populated registries, `instance/profile.md`, real workspaces, generated output |
| **Private instance** | Everything from public **+** populated registries, `instance/profile.md`, real `users/<user>/workspaces/<workspace>/`, output | — |

Your own instance is just the first private instance; you are `users/<user>/workspaces/self`. Others
clone the public repo to make their own private instances.

## The ownership boundary (why updates stay clean)

**Ownership is mixed-provenance** (`docs/design.md` §10): **provenance** — who authored an entry
(`provenance: framework | instance`) — is a **metadata tag**; **scope** — where it applies — is
**location**. Shared registry directories hold framework-shipped defaults and instance-global
additions side by side, distinguished by the tag, never by the directory. Client scope is still
structural: `users/<user>/zones/<zone>/workspaces/<workspace>/` entries apply to that client only.
(The `users/<user>/` and `zones/<zone>/` segments are both isolation/addressing prefixes — a **zone**
groups a user's workspaces and changes only *where* a workspace lives, not the value cascade;
`docs/design.md` §10/§23.)

Updates stay clean because framework and instance content never share a **file** (git merges at
file granularity, so a merge only conflicts when *both* sides edit the *same* file):

- **Framework-owned (upstream edits these):** `CLAUDE.md`, `docs/*`, `*.template.*`, `.claude/*`,
  `scripts/*`, `.github/*`, `.gitignore`, `LICENSE`, `README.md`, `quickstart.md`, and every
  shipped `provenance: framework` registry entry (default voices, platform profiles, recipes,
  folio types, content-kinds, the `plain` presentation).
- **Instance-owned (you add these; upstream never touches them):** instance-global registry
  entries in the shared dirs (`provenance: instance`, ids/filenames carrying the reserved `x-`
  prefix — `docs/design.md` §11.4 — so framework↔instance filename collisions are impossible),
  `content-kinds/` additions, `users/<user>/workspaces/<workspace>/**` — including client-scoped entries and
  **workspace `extends:` partials**, the partial-customization path that field-merges over a
  shipped entry instead of editing it — `instance/profile.md`, `instance/ops/` stores
  (presence-lease registry, telemetry — mechanism framework, data instance; `docs/design.md`
  §22.5, §23), and `state.md` (derived from the spreadsheet SSOT, **but tracked in your instance
  for history**).

**The linchpin rule:** downstream **extends by adding files** and **never edits framework files —
including shipped `provenance: framework` entries**. Customizing a shipped entry means adding a
workspace (or instance-global) `extends:` partial, never an in-place edit. Want to change
framework behavior? Change it in the **public** repo (you maintain it) and pull. This guarantees
conflict-free updates.

## Updating a private instance

```bash
scripts/update-from-upstream.sh      # fetch upstream, show framework diff, confirm, merge
```

Because your content lives in separate files, the merge applies framework improvements and leaves
your content untouched. If you ever did edit a framework file locally (don't), that's the only
place a conflict can arise — resolve by moving your change into an instance-owned file or upstream.

## Migrating the on-disk layout (users, then zones)

A handful of framework releases have **re-homed** where workspaces live on disk. These are the one
class of framework change that also moves your (gitignored, instance-owned) *data*, so each ships a
**one-shot, idempotent, never-destructive** migration script you run once, in a fixed **pull →
migrate → use** order. The script only ever `mv`s a workspace directory and `rmdir`s a proven-empty
parent — it edits no file contents and deletes no data; a re-run after a complete move is a clean
no-op.

- `scripts/migrate-to-users-layout.sh` — the earlier flat → per-owner re-home (into `users/<user>/`).
- `scripts/migrate-to-zones-layout.sh` — the **zones** re-home: every workspace moves from
  `users/<user>/workspaces/<workspace>/` to `users/<user>/zones/default/workspaces/<workspace>/`, so
  a **zone** (a grouping of a user's workspaces) sits between the user and the workspace. See the
  [Interfaces guide → Zones](guide/interfaces.md#zones-grouping-a-users-workspaces) for the concept.

**The pull → migrate → use order (why it is safe).** The two halves are non-destructive *only in
this order*:

1. **Pull** the framework — `scripts/update-from-upstream.sh`. This brings the zoned CODE (which now
   resolves every workspace through the 5-level path) **and** the additive `.gitignore` for the
   zoned tree, BEFORE any data moves.
2. **Migrate** — run `scripts/migrate-to-zones-layout.sh` ONCE (all users in one sweep; `--dry-run`
   first if you want to preview the moves). It re-homes the on-disk data the new code expects under
   `zones/default/`.
3. **Use** — post-migration, un-flagged commands resolve zone `default` and land on the moved homes.

Neither half is destructive alone: pulling the code before migrating just means un-migrated
workspaces are not yet found (a loud "not found", never a silent wrong-zone write); migrating without
first pulling would move data the old code cannot address. Running them in order closes the window.

**BREAKING — the HTTP-shim allow-list config format.** If you run the `pipeline serve` shim, the
served-workspace allow-list key in `instance/shim.yaml` (`workspaces.allowed`) changed from the
pre-zone **`user/workspace`** form to **`user/zone/workspace`** (plus the `user/zone/*` and `user/*`
wildcards). A deployed shim must migrate its entries to the zoned form or a `user/*` wildcard;
`instance/shim.yaml` is instance-owned, so this is a manual config edit the pull does not make for
you. (Unlike the data re-home, this is a *configuration* break, not a data move.)

## Keeping the public repo empty of client content

Enforced two ways, not willpower:

1. `scripts/check-no-content.sh` fails if populated registries, a real `profile.md`, or any tracked
   client content under `users/*` appear. (The shared scaffold at `templates/workspace/` is
   framework, so it stays; its subtree is scanned for the `x-`/`provenance: instance` signals only.)
2. `.github/workflows/guard.yml` runs that check on every push/PR to the public repo. A private
   instance **skips the job**, so it tracks your content freely with green CI. That skip is an
   explicit `if: github.event.repository.private != true` on the job — not an assumption that the
   instance lacks the file, because the workflow ships downstream like every framework file. The
   same reasoning gates the one pytest assertion that is true only of the public tree
   (`OPTIQUITY_PUBLIC_REPO`, set by `ci.yml`).

Do all content work in the **private** repo; push only framework changes to public.

## Client isolation (inside the private repo)

- Each client repo is `users/<user>/workspaces/<workspace>/` with its own `topics/`, `select/`, `output/`.
- Source/client repos are **read-only** (durable rule, CLAUDE.md). Their Graphify graph lives in the
  client-repo checkout (`graphify-out/`, gitignored there) and is **read by path**; no graphs are stored here.
- `personas/`, `platforms/`, `formats/` are **shared defaults** across clients (they describe
  audiences/channels/formats, not client secrets). Need a client-specific variant? Add
  `users/<user>/workspaces/<workspace>/overrides/` and have the resolver prefer overrides for that workspace.
- Content and output never cross workspaces.

## Setup recap

```bash
# Private instance, one-time:
git clone <PUBLIC_REPO_URL> optiquity-content-pipeline-private
cd optiquity-content-pipeline-private
git remote rename origin upstream
git remote add origin <YOUR_PRIVATE_REPO_URL>
git push -u origin main
cp instance/profile.template.md instance/profile.md    # fill with your goals/audiences
uv run pipeline workspace new self --user <user>        # your first workspace under users/<user>/workspaces/self (§23)
```

## Backward compatibility of framework changes

The whole point of the two-repo model is that framework improvements merge cleanly into any
instance. That only holds if the public framework evolves **additively and backward-compatibly**.
Rules for maintaining the public repo:

- **Settle conventions before v1.0.** Renames/moves are the one change that causes downstream merge
  churn. Do all structural/naming decisions now, before any instance exists; freeze them at v1.0.
- **After v1.0, additive only.** New files, new *optional* registry fields, new agents/skills — yes.
  Renaming or removing framework files, or changing a field's meaning — no.
- **Deprecate, don't delete.** Mark a framework file/field deprecated and keep it working for a
  release or two; provide a migration note before removal.
- **Version + changelog the framework.** Tag releases; note what a `update-from-upstream` pull brings.
- **Instances never edit framework files** (the linchpin rule) — so upstream edits and instance
  content never touch the same file, and merges stay conflict-free.

Result: `scripts/update-from-upstream.sh` on any instance — yours or a client's — applies framework
improvements without disturbing that instance's tracked content and history.

## Your content is tracked (durability)

Your private instance versions its **full** history: populated registries,
`users/<user>/zones/<zone>/workspaces/<workspace>/` (topics, selection configs, and generated
`output/`), `instance/profile.md`, and `state.md`. The framework `.gitignore` ignores only local
cruft (`reference/`, OS/editor files) — **never your content**, and that is deliberate rather than
incidental: `.gitignore` is a framework file that ships downstream, so a client-content pattern in
it would be inherited by your instance and would leave exactly the content §B exists to preserve
silently untracked.

The **public** framework clone takes that protection per-clone instead — `bash
scripts/protect-public-clone.sh` writes it to `.git/info/exclude`. So no *tracked* file differs
between public and private, and merges from upstream stay clean because upstream never has files
under your workspaces.

## Why not the obvious alternatives

- **GitHub "template repository":** creates repos with **no shared history** → you can't merge
  upstream improvements later. Fails the core requirement.
- **git submodule / subtree:** enforce the boundary but fight Claude Code's expectation of a
  root `CLAUDE.md`, and add operational friction. The remote+ownership model is simpler and
  git-native (history, PRs, attribution all work — important for an OSS project you maintain).
