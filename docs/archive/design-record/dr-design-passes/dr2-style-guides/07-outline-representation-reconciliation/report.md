# DR-3 outline — representation / emit-bridge / round-trip — Architect RECONCILIATION (stage 07)

**Pass:** RECONCILIATION of `05-outline-representation-initial` (structured-JSON pick) vs
`06-outline-representation-adversarial` (F1–F8), under the maintainer's format challenge AND the
new any-format-emit HARD CONSTRAINT. **Class:** read-only. No repo edits, no commit. Design only —
no code, no implementation plan; the planner runs after the maintainer gate.
**Verified this pass against live code, not the reports:** `pipeline/ir.py`
(`validate_ir`, `_validate_binding`, `build_ir`, empty-ledger + no-span acceptance — executed),
`pipeline/ids.py` (`build_artifact_preimage` frozen kwargs, `_require_artifact_preimage_shape`
frozen-shape guard hard-refusing an extra top-level key — executed), `pipeline/compose.py`
(`build_writer_prompt`, `_persist`/`write_new` no-replace), `pipeline/api/render.py`
(internal-vs-external mint, `MintOutcome`, `_read_record`/`parse_id` retrieval), `pipeline/serialize.py`,
`render-targets/{md,plain-text,html,pdf,epub}.md`, `formats/_schema.yaml`; SSOT `docs/design.md`
§7.1–§7.4, §13.1, §13.3, §15, §16, §17 (RI7–RI14), §18, §27.3; `docs/known-issues.md` DR-3/GAP-8.
**Frame not reopened:** the stage-03 rulings (B1 tier-immutability, B2 outline-is-a-cascade-non-participant,
the {D,A1,A2,B,C} taxonomy, one-outline-per-driven-`artifact-id`) stand. The initial's structured-JSON
canonical (C2) is **OVERTURNED**; see §1.

---

## 1. THE REPRESENTATION VERDICT (lead) — C3: the canonical outline is MARKDOWN; the IR returns only at emit

**VERDICT: C3. The outline's canonical, persisted, human-edited form is plain Markdown** — the
same format §13.1 assigns to human-authored prose surfaces and §15 RI1 assigns to IR leaves.
**No new internal format is introduced.** The outline is *content-addressed* by an
`outline-digest` computed over the normalized Markdown; it becomes an IR **only on the emit path**,
via a thin `outline→IR` bridge that realizes it as an ordinary **`Format=outline` artifact** (§2).
C2 (the initial's new structured-JSON record) is **rejected**; C1-as-canonical (the outline *is* an
IR at rest) is **rejected**; C1's *machinery* is **retained but relocated** to the emit bridge only.

### 1.1 Direct answer to the maintainer's challenge
*"Why yet another internal format? What does it buy us? What can it do the IR can't? Why a better
input format than the IR? Justify the heaviness."*

**There is no new internal format.** The canonical is Markdown, which the pipeline already runs two
ways: as the human-authored config/prose surface (§13.1 row 1) and as the IR leaf body (§15 RI1).
The emit realization reuses the **existing IR** unchanged. So the "heaviness of another supported
internal format" is not paid — the challenge dissolves because the honest answer is *don't add one*.

What Markdown-canonical buys over using the IR as the canonical (i.e. why not C1-at-rest):
- **A human can hand-edit it; nobody hand-edits IR** — the maintainer's own premise. An IR carries a
  §15 RI4 binding, a grounding ledger, `pandoc_api_version`/`ir_version` stamps, and (for composite
  formats) part-ids — none hand-editable. Markdown is exactly "the something simple" the maintainer
  said the IR must be rendered into for editing.
- **It is authorable before the full request context exists.** Verified: `_validate_binding`
  re-mints `mint_artifact_id(binding["preimage"])` on every read, so a valid IR *requires* a complete
  §7.2 preimage — topic, persona, format, voice, goal-set, **and a pinned `source-subset` +
  `source-commit` map**. Forcing the editable object to be an IR forces a full source-commit snapshot
  and a (empty) grounding ledger onto a thing that is a *plan*. Markdown needs none of it.
- **It is the better compose-input** (the maintainer's first-order generation-quality concern, and
  DR-3's "far more influence than any other content input"). A readable Markdown brief is the
  natural high-salience precedence mechanism; GAP-8 is logged evidence this writer is acutely
  prompt-*framing* sensitive (a structured header read as "pasted file content" derailed 3/8 runs).
  Feeding a JSON array of `{heading,intent}` is the *untested* option on the exact axis the
  maintainer weighted first (adversarial F4). Markdown is what the writer reads best.
- **The drive-only path (mode A1) never builds an IR at all** — a throwaway scaffold that seeds one
  compose and is discarded pays zero IR-envelope cost under C3; under C1-at-rest it would pay the
  full envelope for nothing.

What Markdown-canonical *cannot* do that the IR can — **and why that is correct, not a gap:** it
cannot be rendered to output-types directly (no AST/serialize path). That is *exactly* why the emit
path bridges to an IR (§2). The IR is reused precisely where it is load-bearing (render/serialize/
payload); Markdown is used where the human works and where the writer reads best. Each format is used
per §13.1's own discipline — **zero new formats, no misuse of either.**

### 1.2 Why C2 (the initial's structured JSON) is OVERTURNED
1. **It mis-applied §13.1.** The initial classified the outline as a "machine record → JSON."
   But the outline is **human-authored and human-edited** content; §13.1 row 1 maps that class to
   **Markdown + frontmatter**, not JSON. §13.1, read correctly, *points to C3*. (JSON is for
   machine-*written* records — which is what the emit IR is, and it correctly uses JSON.)
2. **It carries adversarial F1 as a structural blocker.** A structured canonical + a lossy Markdown
   edit-projection needs a round-trip whose fidelity test (the initial's `render∘parse∘render`)
   checks *byte-retraction, not meaning*: a `##` or `(≤N words)` living in free-text intent
   mis-segments into structure yet round-trips byte-faithfully, surfacing no residual (F1, verified
   sound). C3 has **no lossy projection** — the canonical *is* the edited Markdown — so F1's failure
   mode cannot arise in v1 (§3, F1).
3. **It ships the untested compose-input as the default** on the maintainer's flagged concern (F4),
   and self-contradicts on whether the writer reads the JSON block or a "readable rendering."
4. **It multiplies mechanisms:** a new schema + a new store + `render_edit`/`parse_edit` + a new
   prompt block + a fenced `constraint?` vocabulary to police. C3 needs none of the first four and
   **defers** `constraint?` (§3, F6/orthogonality).

### 1.3 Why C1-at-rest (canonical = IR) is rejected as the canonical form
- **It does not remove the bridge or the human projection.** A human still cannot edit IR, so you
  still project to Markdown and parse back — C1-at-rest only *moves* the Markdown from "the
  canonical" to "a projection of the canonical," adding the whole IR envelope with no offsetting win.
- **It hits the body-blind-identity wall.** An `artifact-id` is deliberately **body-independent**:
  compose mints it from the preimage *before* the writer runs, so `is_done`/`preimage_check` can
  short-circuit the LLM (§21.8). The body is **not** in the preimage. But an outline's identity
  *must be its edited content*. So if the outline "simply IS a `Format=outline` artifact," two
  different edited outlines sharing topic/persona/voice/goals/source mint the **same** `artifact-id`,
  and `write_new` (atomic no-replace) **silently keeps the old bytes** — the edit vanishes. Verified
  mechanism (`compose._persist` → `write_new` → `AlreadyMaterializedError` → old bytes stand). The
  fix is an `outline-digest` (a *content* hash) in the preimage — which C1 needs **anyway**, so C1
  buys no identity advantage. C3 carries that same digest without the envelope overhead.
- **Verified positive:** a content-only `Format=outline` IR *does* validate (empty grounding ledger,
  plain-Markdown body, no `data-fact` spans — executed). So C1's machinery is sound; it is simply
  the wrong home for the **edit** surface. It is the right home for **emit** (§2).

**Net:** canonical/edit surface = **Markdown** (C3); emit realization = **IR** (`Format=outline`,
C1's machinery via the §2 bridge). This is the §13.1 surface→format split done correctly:
human-authored prose → Markdown; machine record → IR/JSON. One `outline-digest` is the outline's
single content-identity, consumed by both the driven artifact and the emitted-outline artifact.

### 1.4 v1 scope cuts that the verdict depends on (each named, each deferred cleanly)
- **Holistic Markdown, no machine section-parse in v1.** Identity, compose-input, and emit all treat
  the outline as *whole normalized Markdown*. Nothing segments headings into a machine list. This is
  what dissolves F1 and F3 (no parse to mislead, no structured model to contradict the digest).
- **`constraint?` DEFERRED.** The one field that could become a backdoor cascade-override rung is not
  in v1. The stage-03 orthogonality watch-item (constraint must be closed-vocab, non-cascade) is
  therefore *moot in v1* — one fewer guard to build. It returns as an additive fenced-block/sidecar
  convention when needed (with F1's sentinel grammar, §3, F6).
- **Multi-part formats DEFERRED** (F6): v1 outlines drive/emit **single-part (flat-body) formats
  only**.

---

## 2. The outline→IR EMIT BRIDGE (mandatory on every E=1 path; single mechanism, near-free)

The hard constraint is confirmed against code: **every output type is produced from the IR** —
internal types via `serialize` (pandoc writers over the AST), external types (epub/pptx/pdf) via the
RI14 payload (`render.py` branches on `MintOutcome.side`; `render-targets/*.md` carry
`side: internal|external`). So emit MUST convert the outline to an IR. The de-scope-to-in-session
render (adversarial F2 option a) is rejected by the maintainer and by this design.

**The bridge = realize the outline as an ordinary `Format=outline` artifact:**

1. **One-file framework Format entry `formats/outline.md`** (`provenance: framework`; a public-repo
   deliverable per CLAUDE.md rule 4). It is a fixed platform-agnostic genre — "an outline" — exactly
   like `readme`/`short-opinion-post`. `parts: []` (single-part). Its body prose is the genre's
   rhetorical description (§5.2). **No parametric Format** (see Part-D below).
2. **Build the IR:** `build_ir(artifact_id=<minted>, preimage=<§7.2 with format=outline + the
   outline-digest>, grounding={}, body=<the normalized canonical Markdown>)`. Executed and verified:
   this validates (empty ledger, plain body, no spans). The IR body **is** the canonical Markdown —
   the bridge is a wrap, not a transform.
3. **Persist under its `artifact-id`.** It is now an ordinary artifact: `render` fits (a `pass`
   no-op, §16) and serializes to **any** output-type — internal bytes (md/plain/html) or the RI14
   external payload (pdf/epub/pptx). `fetch-by-id`/`emit-manifest`/folio-membership all work
   unchanged, because they key on a real `parse_id`-valid `artifact-id` (this is what closes F2).

**This is the single mechanism for all E=1 modes (B, C, A2-emit).** In A2 (drive AND emit), the
emit-IR body, the compose seed, and the digested bytes are the **same normalized Markdown** — there
is one projection, not two, so drift is impossible by construction (sharper than the initial's
"two-projections" claim).

**Identity of the emitted outline (resolves the S5 / Part-D interaction, per F2):**
- **`outline-digest` sits in the emitted-outline artifact's OWN preimage**, making its
  human-authored body identity-bearing (the body-blind wall of §1.3 is escaped precisely here,
  because for this one genre the digest of the content *is* an input). Edit → new digest → new
  emitted `artifact-id` → re-emit yields new bytes; no stale-serve.
- **S5 RI2 circularity does NOT arise.** The emitted outline is **flat-body, single-part** — no
  `parts`, no `role`, no `(artifact-id, part-id)`. RI2's part machinery is bypassed entirely; there
  is no point at which an outline heading becomes a `role` or a `part-id`, so the
  `role`/`(artifact-id,part-id)` circularity F2 feared cannot form.
- **Part-D (no parametric Format) is HONORED.** `outline` is a fixed one-file genre; the
  per-artifact structure lives in the **body** (Markdown content), exactly per §5.2 ("the genre's
  rhetorical structure is the entry's body prose"). No structure is carried *as/through* a Format
  value; Format stays non-parametric.
- **No DAG-of-`artifact-id`s.** The driven prose artifact references the **`outline-digest`** (a
  content hash), never the emitted-outline `artifact-id`. In A2 both artifacts independently carry
  the same digest in their preimages; neither references the other's id. (This also sharpens
  stage-03 S1/S6: one digest, two consumers, no second id family, no `o-` root.)

---

## 3. F1–F8 recomputed UNDER C3 (dissolved / changed / corrected for overreach)

**F1 (was blocker) — DISSOLVED in v1; requirement registered for the deferred feature.** The
byte-retraction-vs-meaning break requires a lossy projection between an editable form and a
structured canonical, plus a machine section-parse. C3-v1 has **neither**: the canonical *is* the
edited Markdown, and nothing segments it into machine sections. The compose-input is those same
bytes read by the writer (an LLM parsing Markdown), not a parser we can mislead. F1 was a *correct*
blocker against C2 — and dissolving it is one reason C3 wins. **Forward requirement (registered):**
when section-level machine features land (deferred `constraint?`/section-addressing), they MUST use
an **escapable/sentinel grammar** (boundaries drawn only from sentinel lines content cannot forge)
plus a **structural** fidelity check above any byte check — never free-text-under-`##`.

**F2 (was blocker) — RESOLVED by §2.** The emitted outline is a real `Format=outline` `artifact-id`,
retrievable by the existing `fetch-by-id`/`emit-manifest`/render verbs (all resolve through
`parse_id`, verified). The "optional upgrade" framing of the initial is corrected: the Format=outline
path is **mandatory** for any E=1 delivery, not a post-gate nicety. S5/Part-D interaction resolved
above (flat-body ⇒ no part circularity; fixed genre ⇒ non-parametric).

**F3 (should-fix) — RESOLVED by pinning N and dropping modeled nesting.** The self-contradiction
(whitespace-immune digest vs. preserve-nesting-and-surface-it) came from a structured model making a
nesting claim the digest had to both keep and drop. C3 has no such model. Pin the normalizer **N**:
NFC Unicode normalization (precedent: `ir._has_substance` NFC-normalizes, `ir.py:475`); normalize
line endings to `\n`; strip trailing per-line whitespace; collapse blank-line runs; strip
leading/trailing blank lines; **and N must be idempotent** (`N(N(x)) == N(x)`) so re-editing is
stable. **N preserves LEADING indentation as opaque content** — so a human's indented list/code is
never silently eaten (no silent semantic loss), while the common cosmetic edits (trailing spaces,
blank lines, smart-quote/accent form) do not churn. v1 assigns **no** semantics to nesting, so there
is nothing structural for N to violate. Whitespace-immunity (for cosmetic edits) and no-silent-loss
are thereby *jointly* satisfied; the residual cost — a deliberate re-indent churns the digest — is
correct and **loud** (it re-composes), not silent.

**F4 (should-fix) — RESOLVED; the compose-input presentation is designed as the DR-3 precedence
mechanism.** The exact bytes the writer reads when U=1 are the **canonical `N(Markdown)`** — the same
bytes `outline-digest` pins — so input ≡ identity, losslessly, by construction (no JSON-block vs.
readable-rendering split to reconcile; that whole self-contradiction is gone). The readable Markdown
brief IS the "far more influence" mechanism DR-3 demands; the drive facets (`use-sections?`,
`use-order?`, `intents-must-cover?`) ride as prompt flags + `writer.md` instructions layered over
that brief. **Registered as a first-order build item to ablate** (GAP-8-style): the prompt framing of
the outline brief is the precedence lever and must be measured, not assumed.

**F5 (should-fix) — RESOLVED; no lossy round-trip in v1, hard gates retained where they bite.** With
canonical = editable there is no round-trip residual to gate in v1. The gates that DO apply are
**hard**, reusing existing IR machinery: the **substance floor + secret scan** (`_has_substance`,
`looks_secret_shaped`) run (a) when the human's Markdown is accepted as canonical and (b) again inside
`validate_ir` when the emit bridge builds the IR. **Forward ruling (registered):** if/when the
deferred section-parse lands, a non-empty *structural* residual MUST be a **HARD GATE** (block +
require human re-confirmation), not advisory — per the maintainer's "verification of success" framing;
advisory is too weak.

**F6 (should-fix) — RESOLVED by a named scope cut.** A flat/holistic v1 outline cannot scope per-part
bodies for a `format.parts` multi-part format (verified: `_assemble_ir` builds one body per role).
**v1 de-scopes outline drive/emit to single-part (flat-body) formats only** — named explicitly. A
multi-part artifact gets no outline in v1. Per-part outline scoping is a deferred extension that
needs both the section-grouping shape and F1's sentinel grammar.

**F7 (minor) — RESOLVED; §18 citation down-ranked, store registered for GC.** §18 is precedent only
for the **narrow** claim "a digest can key an internal store without a §7.4 grammar change." Verified:
the AST-store key is `fitted-id (+ reader-pin digest)` — the digest *disambiguates* an id-family
primary key; it is neither a bare-digest primary key nor an identity input. The pre-compose outline
store is keyed by a **bare `outline-digest`** that also *is* a preimage component — §18 does not
precede that, so it is justified **separately**: the digest is the content-address of a real content
input (the plan), the same category as `source-commit` pinning a source input. **Register the
pre-compose outline store under §27.3 GC/retention: retain-all in v1** (consistent with §21.8
"RETAINED indefinitely"; abandoned A1 scaffolds and every intermediate edit are orphans by design);
GC deferred. It is a **new store class** the §27.3 register must name.

**F8 (minor) — CONFIRMED as a concrete, non-free code requirement (sharpened against the guard).**
The `outline-digest` §7.2 extension is achievable with zero churn but is **not** a free rename:
- It must be **omitted from the canonical preimage bytes when absent** (not `outline-digest: null`),
  so every already-stored binding (which has no outline key) re-mints byte-identically via
  `_validate_binding` → `mint_artifact_id(binding["preimage"])`. **Verified:** a 4-key preimage
  re-mints to the same id today.
- **AND** the **frozen shape guard `_require_artifact_preimage_shape` must be extended.** Verified by
  execution: it hard-refuses *any* top-level preimage key outside
  `{dimensions, goals, source-subset, source-commit}` (`set(preimage) != expected` → `PreimageError`).
  So does the frozen closed-kwargs `build_artifact_preimage`. Both must be extended to accept
  `outline-digest` as an **optional** top-level component (absent = today's 4-key shape, byte-identical).
  This is a §7-authority change (gate item), flagged precisely for the planner.

**Adversarial claims I affirm (survived, unchanged):** the {D,A1,A2,B,C} taxonomy; "no markdown→IR
reverse parser exists"; the JSON-context mechanics; the re-render decoupling from the outline; A2
no-intra-digest-drift. One-outline-per-driven-`artifact-id` (initial §1.2) stands and is unaffected;
the emitted outline is additionally its **own** `artifact-id`, which is consistent (different genre,
different id, same `outline-digest`).

---

## 4. Residual risks + updated maintainer-gate items

**Residual risks (honest):**
- **R1 — quality of Markdown-brief compose-input is asserted, not proven.** F4's ablation is
  directional-at-best until run (n-limited, like GAP-8). The design is safe regardless (input ≡
  identity; the writer's own §6.5 tier gate + substance floor bind every published span, outline or
  not), but the "far more influence" *degree* is empirical.
- **R2 — re-indentation churns identity.** Accepted and loud (re-composes), but a user who reflows an
  outline pays an LLM recompose. Documented behavior, not a defect.
- **R3 — deferred features carry the hard problems.** `constraint?`, section-addressing, and
  multi-part outlines all inherit F1's sentinel-grammar + F5's hard-gate requirements. They are
  *registered*, not solved. Do not let a later pass reintroduce free-text-under-`##`.
- **R4 — `outline-digest` in the emitted outline's own preimage is unusual** (an artifact whose id
  depends on a digest of its own body). It is correct for this one human-authored genre, but it is a
  local exception to "body is never in the preimage" — call it out at the gate so it is a ratified
  exception, not an accident.

**Maintainer-gate items (design decisions above the planner):**
1. **Ratify C3 (Markdown canonical) + the mandatory `Format=outline` emit bridge; reject C2 and
   C1-at-rest.** This overturns the stage-05 pick; it is the load-bearing decision.
2. **Ratify the §7.2 `outline-digest` extension** (a §7-authority change): optional/absent-by-default,
   omit-when-absent canonicalization, and the extension of `_require_artifact_preimage_shape` +
   `build_artifact_preimage`. It is one digest with two consumers (driven artifact; emitted outline).
   Zero churn for existing ids (verified). Ratify the R4 "digest-of-own-body in the outline's
   preimage" exception explicitly.
3. **Ratify `formats/outline.md`** as a framework Format entry (single-part, non-parametric) and the
   emit-bridge realization path.
4. **Ratify the v1 scope cuts** as named: holistic Markdown (no machine section-parse),
   `constraint?` deferred, multi-part outlines deferred (F6).
5. **Pin N** (F3) and **register the pre-compose outline store under §27.3 GC/retention** (F7,
   retain-all v1).
6. **Authorize the F4 compose-input-brief ablation** as a first-order build item (the DR-3 precedence
   mechanism), not an optional nicety.
7. **Standing item (unchanged from stage-03 #4): is the outline worth its cost?** C3 makes it
   *cheaper* than the initial (no new format, no new schema, no `render_edit`/`parse_edit`, no fenced
   constraint vocabulary; the emit bridge is a wrap). The residual cost is the generate-outline LLM
   stage + the human authoring touchpoint + one preimage component + the pre-compose store. Still the
   heavier of the two DR features; now materially lighter than stage-05 proposed.

*End of reconciliation. Verdict: C3 — Markdown-canonical outline, content-addressed by
`outline-digest`, realized as a `Format=outline` IR artifact only at emit. This introduces no new
internal format (answering the maintainer head-on), gives the best generation-quality compose-input
posture (F4), dissolves F1 and F3 by not parsing structure in v1, resolves F2/S5/Part-D via the
flat-body emit bridge, and reuses the IR exactly where it is load-bearing. The stage-05
structured-JSON canonical is overturned. No code, no plan; the maintainer gate runs next.*
