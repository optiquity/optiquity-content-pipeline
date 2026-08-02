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
structural: `users/<user>/workspaces/<workspace>/` entries apply to that client only. (The
`users/<user>/` segment is an isolation/addressing prefix — it changes *where* a workspace lives,
not the value cascade; `docs/design.md` §10/§23.)

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

## Keeping the public repo empty of client content

Enforced two ways, not willpower:

1. `scripts/check-no-content.sh` fails if populated registries, a real `profile.md`, or any tracked
   client content under `users/*` appear. (The shared scaffold at `templates/workspace/` is
   framework, so it stays; its subtree is scanned for the `x-`/`provenance: instance` signals only.)
2. `.github/workflows/guard.yml` runs that check on every push/PR to the public repo. The private
   repo simply doesn't run it, so it tracks your content freely.

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
mkdir -p users/<user>/workspaces                        # your isolation/addressing prefix (§23)
cp -R templates/workspace users/<user>/workspaces/self  # your first workspace (a future `workspace new`)
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

Your private instance versions its **full** history: populated registries, `users/<user>/workspaces/<workspace>/`
(topics, selection configs, and generated `output/`), `instance/profile.md`, and `state.md`.
The framework `.gitignore` ignores only local cruft (`reference/`, OS/editor files) — never your
content. Merges from upstream stay clean because upstream never has files under your workspaces.

## Why not the obvious alternatives

- **GitHub "template repository":** creates repos with **no shared history** → you can't merge
  upstream improvements later. Fails the core requirement.
- **git submodule / subtree:** enforce the boundary but fight Claude Code's expectation of a
  root `CLAUDE.md`, and add operational friction. The remote+ownership model is simpler and
  git-native (history, PRs, attribution all work — important for an OSS project you maintain).
