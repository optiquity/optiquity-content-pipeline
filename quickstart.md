# QuickStart

Get running fast. Two audiences: **A) anyone trying the framework on their own repos**, and
**B) the maintainer running the public/private model** (see `docs/operating-model.md` for the full
model). Commands are reference — verify current flags against each tool's docs.

---

## A. Try it on your own repo (public framework users)

**1. Get the framework**

```bash
git clone <PUBLIC_REPO_URL> optiquity-content-pipeline
cd optiquity-content-pipeline
```

**2. Install prerequisites** (macOS shown; see `docs/bootstrap.md` for detail)

```bash
brew install node python pipx
pipx ensurepath
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install graphifyy      # PyPI name has two y's; CLI stays `graphify`
graphify install
graphify --help | head -20     # confirm current subcommands/flags
```

**3. Create a workspace** (your own repo is a client too)

```bash
cp -R workspaces/workspace.template workspaces/self
```

**4. Build the graph in your checked-out client repo (gitignored there)**

```bash
cd /path/to/your-checked-out-client-repo
graphify . --wiki                 # produces graphify-out/ here; gitignored in that repo
```

Record the checkout path + its `graphify-out/graph.json` path in `workspaces/self/source.md`.
The pipeline reads the graph by that path; it stores no graphs itself.

**5. Smoke test the grounding (read-only)**

```bash
graphify query "high-level architecture and main components" \
  --graph /path/to/your-checked-out-client-repo/graphify-out/graph.json --budget 3000
```

**6. Define your matrix** — copy the templates and fill them in. This is authoring work: do it in
a normal Claude chat or Claude Code session (no pipeline agents needed — those are for generation).

```bash
cp personas/persona.template.md   personas/users.md          # repeat per audience
cp platforms/platform.template.md platforms/linkedin.md      # repeat per platform
cp formats/format.template.md     formats/how-to-doc.md      # repeat per format
cp topics/topic.template.md       workspaces/self/topics/<id>.md   # seed from GRAPH_REPORT.md
```

**7. Open Claude Code in the repo** and say:

> Read state.md and docs/mission.md, then propose a plan to prove one thread: one topic × one
> persona × one format for `workspaces/self`, grounded via the graph.

Approve the plan; review the draft in `workspaces/self/output/`.

---

## B. Maintainer: run the public/private model

One-time, per your private instance:

```bash
git clone <PUBLIC_REPO_URL> optiquity-content-pipeline-private
cd optiquity-content-pipeline-private
git remote rename origin upstream          # public becomes 'upstream'
git remote add origin <YOUR_PRIVATE_REPO_URL>
git push -u origin main
```

Do all client work here (workspaces, populated registries, PROFILE). Pull framework updates
non-destructively anytime:

```bash
scripts/update-from-upstream.sh
```

Improve the framework in the **public** repo, then pull into private. Never edit framework files
in the private repo (extend by adding files instead). Full rationale: `docs/operating-model.md`.

---

## Next steps

1. Populate `instance/profile.md` (your goals/audiences) from `instance/profile.template.md`.
2. Finish the four registries with real values.
3. Wire `.claude/agents/` (researcher + writer), then run first ideation.
4. Track everything in the **spreadsheet (SSOT)**; `state.md` mirrors it.
