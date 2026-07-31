# QuickStart

Get running fast. Two audiences: **A) anyone trying the framework on their own repos**, and
**B) the maintainer running the public/private model** (see `docs/operating-model.md` for the full
model). The design SSOT is `docs/design.md`. Commands are reference — verify current flags against
each tool's docs (`--help`).

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
graphify install               # registers the skill/hooks for your assistant
graphify --help                # confirm current subcommands/flags
```

**3. Create a workspace** (your own repo is a client too)

```bash
cp -R workspaces/workspace.template workspaces/self
```

**4. Build the graph in your checked-out client repo (gitignored there)**

```bash
cd /path/to/your-checked-out-client-repo
graphify extract .                # builds graphify-out/ here; gitignored in that repo
graphify export wiki              # optional agent-crawlable wiki snapshot (needs the extract first)
```

Record the checkout path + its `graphify-out/graph.json` path in `workspaces/self/source.md`.
The pipeline reads the graph by that path; it stores no graphs itself.

**5. Smoke test the grounding (read-only)**

```bash
graphify query "high-level architecture and main components" \
  --graph /path/to/your-checked-out-client-repo/graphify-out/graph.json --budget 2000
```

(`--budget` defaults to 2000 tokens; raise it for broader context. A cross-machine MCP server is
`graphify-mcp` — see `docs/claude-code-usage.md`.)

**6. Fill the matrix — the nine axes**

The pipeline resolves over **nine axes** (design §5.4): five content dimensions (**Topic, Persona,
Format, Voice, Goal**) × four rendering dimensions (**Platform, Language, Output-type,
Presentation**). Each axis is a registry directory with a co-located `_schema.yaml`. Pairing is
user-driven — no filter vetoes a combination you select; the effective allow-list is emergent from
your configuration (design §8), and a strange pairing only draws a one-time advisory lint, never a
block.

**Adding a value is a one-file change** (design §5.4 / §3.2): create one file in the right registry
directory, conforming to that directory's `_schema.yaml`. The framework already ships real default
entries (`provenance: framework`) for most axes — you extend by **adding** files, never by editing a
shipped entry. Start from the templates for the axes you customize most:

```bash
cp personas/persona.template.md   personas/x-hiring-manager.md      # per audience
cp platforms/platform.template.md platforms/x-company-blog.md       # per platform
cp formats/format.template.md     formats/x-launch-note.md          # per format
cp topics/topic.template.md       workspaces/self/topics/<id>.md    # per topic (client-scoped)
```

Private, instance-only entries take the reserved `x-` filename prefix and `provenance: instance`
(design §11.4, §10); to tweak a shipped framework entry, add an `extends:` partial rather than
editing it (design §10 rule 2). The remaining axes (Voice, Goal, Language, Output-type,
Presentation) ship framework defaults and schemas — add a new entry by writing one file that
conforms to the axis's `_schema.yaml`.

**Three ways to author an entry:**

1. **Fully manual (the one-file contract).** Copy the template (or write a bare entry), fill the
   YAML frontmatter to match the co-located `_schema.yaml`, and validate with
   `bash scripts/schema-lint.sh` (and, for the public repo, `bash scripts/check-no-content.sh`).
   The schema is the authority for the field set.
2. **Interactive / assisted.** Have a Claude Code session author the entry and a second pass review
   it (an author → reviewer chain) against the schema + the dimension's design section — good for a
   handful of entries where you want the wording checked.
3. **Researcher-assisted batch.** For many candidate entries, run a researcher → author → reviewer
   chain: a research pass proposes candidate entries (grounded in your goals/graph), an author pass
   writes the files, a reviewer pass validates them. You pick which to keep; nothing lands
   unreviewed. (Process only — no new machinery; it is the same one-file entries either way.)

**7. Try it — preview, then generate** (the friendly CLI; nothing paid happens without `--go`)

```bash
# See the plan + the exact paid count — spends nothing:
uv run pipeline preview --topic <your-topic> --workspace self

# Same plan as a free dry-run, then --go to actually compose (Claude SUBSCRIPTION quota, never an API key):
uv run pipeline generate --topic <your-topic> --workspace self          # dry-run
uv run pipeline generate --topic <your-topic> --workspace self --go     # spends
```

`preview`/`generate` default to the `explainer-post` recipe; add `--persona/--format/--voice/--goals`
to pick content axes and `--platform/--language/--output-type/--presentation` to route the output.
Review the deliverable in `workspaces/self/output/`. The full authoring surface — recipes, saved
selections, entries, outlines, discovery — lives in `docs/guide/authoring.md`.

(Prefer to drive it from a Claude Code session instead? Open the repo and ask it to preview then
generate one thread for `workspaces/self` — it runs the very same commands, and still spends nothing
until you approve `--go`.)

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
scripts/update-from-upstream.sh            # merges upstream, then runs `pipeline drift-report`
```

The update script runs `scripts/pipeline drift-report` after merging so any schema drift the
framework introduced surfaces immediately (read-only; remediation is `scripts/migrate.sh`, never
auto-run — design §11.5/§11.6).

Improve the framework in the **public** repo, then pull into private. Never edit framework files
in the private repo (extend by adding files instead). Full rationale: `docs/operating-model.md`.

---

## Next steps

1. Populate `instance/profile.md` (your goals/audiences) from `instance/profile.template.md`.
2. Fill the registries with real values — one file per entry, conforming to each `_schema.yaml`.
3. Wire the product-plane agents/skills (researcher + writer + reviewer) when they ship, then run
   first ideation (their packaging is an open area — design §27.4).
4. Track everything in the **spreadsheet (SSOT)**; `state.md` mirrors it.
