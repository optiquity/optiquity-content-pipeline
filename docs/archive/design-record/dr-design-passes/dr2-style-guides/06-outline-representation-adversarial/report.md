# DR-3 outline — representation / round-trip / compose-input — Architect ADVERSARIAL (stage 06)

**Pass:** ADVERSARIAL attack on `05-outline-representation-initial/report.md`. **Class:** read-only. No repo edits, no commit. Critique only — no plan, no code.
**Frame (not reopened):** the `03-architect-reconciliation` rulings B1/B2/S1/S5/S6 and the `docs/known-issues.md` DR-3 requirement stand; I attack the initial's *extension* of them.
**Verified this pass against the live SSOT and code, not the initial's summary:** `docs/design.md` §7.1/§7.2/§7.4, §13.1/§13.3, §15, §18, §21.1/§21.8, §27.3; and `pipeline/compose.py` (`build_writer_prompt`, `parse_writer_output`, `_assemble_ir`), `pipeline/ir.py` (`build_ir`, `_validate_binding`, `unwrap_ir`), `pipeline/serialize.py` (`parse_to_ast`, `emit_fitted_markdown`), `pipeline/api/render.py` (`_render`), `pipeline/ids.py` (`build_artifact_preimage`, `parse_id`, `_ROOT_RE`).

Bottom line: two of the initial's four self-flagged residuals conceal **blocker-class** defects, and the initial is blind to a third structural seam. The round-trip "fidelity success test" verifies the **wrong invariant**, and the emit path has **no retrieval verb in the code**. Several of the initial's load-bearing claims, however, survived a genuine attack — listed honestly at the end.

---

## F1 — BLOCKER — the round-trip "success test" checks byte-retraction, not meaning; a `##`/annotation/fence collision silently MIS-MAPS free text into structure and surfaces NO residual

**What is wrong.** The initial's entire editability guarantee rests on the success test (§3.2): starting from `E = render_edit(C)`, a human edits to `E'`; success iff `render_edit(parse_edit(E')) = N(E')`, and the residual `diff(N(E'), E'')` is "surfaced, never silently dropped." This is a **byte-level retraction check**. It cannot detect the failure mode the maintainer most needs caught: a semantic mis-segmentation that happens to round-trip byte-faithfully.

**Evidence (constructed break).** `render_edit` maps each section to `## {heading}` + free-text `intent` body + `constraint?` as a trailing annotation (§3.1). The section delimiter is a markdown heading line; the constraint is a trailing `(≤N words)`/fenced tag. **These delimiters live in the same alphabet as legal `intent`/`heading` content, and the initial specifies no escaping/fencing discipline.** Take a section whose human `intent` is multi-line and legitimately contains `## `:

```
## Real Heading
Cover these subtopics:
## Auth flow
## Token refresh
```

`parse_edit` (headings → section boundaries, §3.1) segments this into **three** sections, not one-section-with-a-multi-line-intent. Now `render_edit(parse_edit(E'))` re-emits three `##` headings with the same interstitial text — which, after `N` collapses blank lines, is **byte-equal to `N(E')`**. The success test PASSES. The residual is EMPTY. Nothing is surfaced. Yet the canonical the compose stage ingests now has three sections where the human meant one — the exact "bytes preserved but meaning wrong" mis-map the task names as *worse than a visible drop*. The identical break exists for `constraint?`: an `intent` reading "keep examples short (≤20 words each)" is parsed with `(≤20 words)` stripped into a machine `constraint` that then drives compose length — byte-round-trips, no residual, silent semantic promotion of prose into a compose directive. A pasted code fence containing `## ` lines compounds it (the initial never specifies fence-awareness in `parse_edit`).

The initial's §6.2/§3.4-item-1 defense ("deeper nesting → surfaced diff") only covers cases that **break** byte-retraction. The dangerous cases **preserve** it. So the design's own verification is structurally incapable of catching them.

**Severity: blocker.** Round-trip fidelity is the load-bearing claim; the proposed verifier tests a weaker property (byte-retraction) than the one asserted (meaning-preservation), and the gap is not a corner case — any planning-of-markdown-about-markdown, any concise-writing constraint phrased in prose, any pasted fence hits it.

**What reconciliation must answer / the concrete alternative.** The editable form needs an **unambiguous, escapable grammar**, not free-text-under-headings: either (a) a fenced/escaped body convention so a literal `##` or `(≤…)` inside an intent cannot be read as structure (and `parse_edit` must be fence-aware and escape-aware), or (b) drop the "free-text intent under a markdown heading" projection entirely in favor of an editable form whose delimiter alphabet is disjoint from content (e.g. a per-field labeled block the parser keys on a reserved sentinel that content cannot contain by construction). And the fidelity test must be re-specified over the **canonical structure** (does `parse_edit` recover the same *section count and field assignment* the human intended?), which a pure byte-diff cannot express — at minimum, a **structural** check (section boundaries derived only from sentinel lines that content cannot forge) must sit above the byte check.

---

## F2 — BLOCKER (for any E=1 mode) — the emitted outline has NO id-family retrieval path; "digest-addressed derived view" is unshippable as a "first-class final artifact," and the mandatory fix reopens Part-D

**What is wrong.** The initial rules the v1 emitted outline is "a DERIVED RENDERED VIEW of the `outline-digest`-addressed stage-product... Retrievable by `outline-digest`... with zero new identity machinery" (§4.3), and demotes the first-class `artifact-id`/manifest path to an **optional** "named additive upgrade... not a v1 requirement." That disposition is wrong: there is **no verb, in the code, that can retrieve a bare digest.**

**Evidence (verified in code, not design).** `pipeline/ids.py`: `_ROOT_RE = re.compile(r"\A([a-z])-([0-9a-f]+)\Z")` and `_ROOT_HEX_LEN = {"artifact":16,"folio":12,"run":16}` — every id the family knows carries a family-letter root. `parse_id` raises `IdError` on anything else. `render`/`fetch-by-id`/`emit-manifest` all resolve through `parse_id` (`pipeline/api/render.py` `_read_record` → `parse_id`; §21.1 verb map). The initial's own ruling keeps "**no `o-` root; §7.4 untouched**" (§4.2). Therefore a bare `outline-digest` **cannot be parsed as an id and cannot be fetched, rendered, emit-manifested, or made a folio member** — folio membership keys on the member's `artifact-id` filename (§13.3), which a digest is not. DR-3 explicitly requires the outline be "an OUTPUT — **a first-class final artifact format in its own right** (you can render just the outline)" (`known-issues.md` DR-3). A deliverable that no external-actor verb can retrieve is not first-class; it is not deliverable at all.

This gap hits **every** E=1 mode (B, C, A2-emit), not just B — in A2 the *prose* artifact is fetchable but the *emitted outline*, as a distinct deliverable, is still bare-digest-addressed and unreachable. The initial's A2 "two projections of one canonical cannot drift" answer (§4.3) is about drift; it dodges retrieval entirely.

**The mandatory fix reopens the ruling the initial says it avoids.** To deliver any emitted outline through the API, the outline needs an id-family address → the "ordinary artifact with **Format=outline**" path. The initial waves this in as "no new machinery, no rework" (§4.3). It is not free: an `outline` Format value whose *body IS an outline*, while the same outline is *also* the pre-compose input that shapes other formats' bodies, is precisely the RI2 `role`/`(artifact-id, part-id)` **circularity** that reconciliation S5 rejected, resurfacing at the Format layer; and it presses on the Part-D **no-parametric-Format** ruling (reconciliation §5, Part D), because the outline's per-artifact structure would now have to be carried as/through a Format value.

**Severity: blocker for mode B (and any E=1 delivery) in v1; the "optional upgrade" framing is the specific error.**

**What reconciliation must answer.** State crisply: **which verb retrieves an emitted outline in v1?** If the honest answer is "none without the Format=outline artifact-id path," then either (a) v1 explicitly **de-scopes** outline-as-deliverable (mode B/C/A2-emit render only in-session, never fetchable/emit-manifestable — name the scope cut against DR-3's first-class requirement), or (b) v1 **requires** the Format=outline path, and reconciliation must resolve the S5 circularity and the Part-D interaction it creates — it cannot be left as an optional post-gate upgrade while claiming mode B is satisfied.

---

## F3 — SHOULD-FIX — the whitespace-immune digest (G-d) and the "nesting → surfaced diff" promise are the SAME normalizer pulling opposite directions; one of them is false

**What is wrong.** G-d requires `N` aggressive enough that a cosmetic whitespace edit yields the identical canonical → identical `outline-digest` → no re-compose (§4.2). §3.4-item-1 requires `N` conservative enough that indentation-as-nesting is preserved and surfaced as an uncaptured diff, "never silently flattened." The initial itself admits (§3.4-item-6) "the normalizer must be **conservative**." **It cannot be both.**

**Evidence.** The residual is computed as `render_edit(parse_edit(E)) vs N(E)` — i.e. **after** `N` is applied. Case (a), silent loss: if `N` collapses indentation (needed for G-d), then a human's nested sub-structure is eaten by `N` before `parse_edit`, `parse_edit(E)` has no nesting, its re-render has no nesting, and `N(E)` also has no nesting → the two are equal → **no residual surfaces, and no re-compose fires**. A real semantic edit is lost silently — the exact case (a) the task asked me to find ("two outlines a human considers DIFFERENT that normalize identical → silent no-churn"). Conversely, if `N` preserves indentation (needed for the §3.4 promise), then cosmetic re-indentation churns the digest and G-d is false. The initial ships both promises and resolves neither. Case (b) is also open: the initial never specifies **Unicode** normalization for the canonical (contrast `ir._has_substance`, which explicitly NFC-normalizes, `pipeline/ir.py:475`). Composed-vs-decomposed accents, smart-vs-straight quotes from an editor, or trailing-space-in-heading under a conservative `N` all yield different canonical bytes → different digest → **spurious re-compose** (expensive LLM) on a human-invisible change.

**Severity: should-fix** (blocker for G-d *as stated* — G-d is not safely ratifiable until `N` is pinned).

**What reconciliation must answer.** Pin `N` precisely and prove the two claims are jointly satisfiable, or drop one. Concretely: define the canonical over a **structured** field set where "insignificant whitespace" is well-defined *per field* (heading = trimmed single line; intent = a normalized text block) and where **indentation is not part of the v1 model at all** (so there is no nesting to lose — but then §3.4-item-1's "nesting → surfaced diff" is retired, not promised). Specify Unicode NFC in the canonical. Only then is a whitespace-immune digest safe.

---

## F4 — SHOULD-FIX — structured-only compose-input defaults to the UNTESTED option on the maintainer's first-order concern, and §4.1 contradicts itself on what the writer actually reads

**What is wrong.** The initial RULES (§4.1) that compose ingests the structured canonical "injected into the writer's existing JSON context block — one new `outline` key," then says the prompt "MAY render the structured outline into a readable form at prompt-build time," and defers whether that helps to "an empirical build question... decided like GAP-8's ablation." This (a) makes the JSON-block-injection the **v1 default** while the maintainer named generation quality first-order, and (b) is internally inconsistent.

**Evidence the default is the risky one.** `build_writer_prompt` (`pipeline/compose.py:296-320`) confirms the mechanical claim — the context dict (`artifact_id`, `effective_values`, `structure`, `grounded_facts`, `roster`) is `json.dumps`'d, so a new `outline` key slots in cleanly; *that* part is true and I could not break it. But the **quality** question is exactly where the maintainer put the weight: DR-3 requires the driving outline have "**far more influence than any other content- or dimension-related input**." The mechanism by which the outline gets "far more influence" IS the prompt presentation. And GAP-8 is direct, logged evidence that this writer is acutely prompt-**framing**-sensitive: a static contract *comment* header caused a 3/8 refusal derail because the model read structured framing as "pasted file content" (`known-issues.md` GAP-8). Deferring "does a JSON plan drive the writer as well as a readable brief" to a post-hoc ablation, while simultaneously ruling the JSON block the v1 input, ships the untested option as the default on the maintainer's flagged concern.

**Evidence of the self-contradiction.** §4.1 point 3 rejects "a markdown-in-prompt outline alongside the structured canonical" as "two representations that can disagree." But the permitted "readable rendering at prompt-build time" **is** a second representation, and the writer would read *it*, not the JSON. The initial never says whether the writer sees the JSON block, the readable rendering, or both. If both → the very drift surface point 3 forbids. If only the readable → the §4.1-point-1 argument ("the writer sees exactly what identity fixed") collapses, because the readable projection is **lossy** unless proven otherwise (does it carry the `constraint?` fields, the exact order, every intent verbatim?) — a lossy readable rendering means input ≠ what the digest pinned, the exact idempotency/cache hazard the initial claims to prevent.

**Severity: should-fix.** The ruling isn't wrong that identity must pin the canonical (undisputed); it is wrong to treat the writer-facing presentation as a deferrable detail when it is the DR-3 precedence mechanism.

**What reconciliation must answer.** (1) Decide the bytes the writer actually reads. (2) If a readable rendering, prove it is **lossless** w.r.t. everything the `outline-digest` pins (structure, order, constraints), so input still equals identity. (3) Treat the compose-input **presentation** (not persistence) as a first-order design item bound to the "far more influence" requirement — the planner must design *and ablate* the readable rendering as the precedence mechanism, not offer it as an optional nicety.

---

## F5 — SHOULD-FIX — "surfaced, never silently dropped" is advisory, not a gate; the corrupted canonical still reaches compose

**What is wrong.** Even for the byte-detectable non-retraction cases, the initial's mechanism only *shows* `diff(N(E'), E'')` "to the human" (§3.2). It never says a non-empty residual **blocks** compose or forces resolution. A surfaced-but-non-blocking residual still ships the possibly-mis-parsed canonical into `_assemble_ir`/compose.

**Evidence.** The initial's own phrasing is "surfaced... never silently dropped" — that is a *notification* contract, not a *gate* contract. This mirrors the B1 grounding posture (advisory reviews, not a hard gate) that reconciliation §2/§6.2 already flagged as the residual — here it re-appears on the edit path. The maintainer framed this as "verification of **success**"; an advisory diff the compose ignores is not success verification.

**Severity: should-fix.** Compounds F1: F1 shows some losses are invisible; F5 shows even the visible ones aren't prevented.

**What reconciliation must answer.** Is a non-empty round-trip residual a **hard gate** (blocks compose / requires human re-confirmation of the parsed canonical) or advisory (compose proceeds)? Given the maintainer's success-verification framing, advisory is almost certainly too weak — say so or justify it.

---

## F6 — SHOULD-FIX (blind spot) — the flat one-level section list cannot express B2's per-part-body outline scoping for a `format.parts` multi-part format

**What is wrong.** §1.2 asserts "one outline per `artifact-id`... covers that artifact's **entire** ... fanout" and is decisive that the outline seeds one artifact. But reconciliation B2 ruled the outline "structures **that part's body**" *within* each part declared by `format.parts`. The initial's v1 outline shape is a **flat ordered section list, one heading level** (§3.4-item-1). A flat list has no way to say "these sections for the `slides` part, those for the `notes` part." The initial is blind to this seam — §1.2 claims clean multi-part coverage that §3.4's shape cannot deliver.

**Evidence.** `format.parts` is a declared, cascade-bound, `artifact-id`-entering, part-addressing attribute (reconciliation B2 table; `part-id = (artifact-id, part-id)`, design §7.1). `_assemble_ir` builds one body **per role** for a multi-part format (`pipeline/compose.py:415-423`). So a multi-part artifact has N distinct part bodies; B2 says the outline shapes each. A single flat section list maps onto N parts only by (a) applying identically to every part (nonsensical — `slides` structure ≠ `notes` structure), or (b) applying to none (outline silently unavailable for multi-part formats — an unnamed capability gap), or (c) needing per-part structure (contradicting the flat-list v1 bound).

**Severity: should-fix.**

**What reconciliation must answer.** Either restrict v1 outlines to single-part (flat-body) formats and **name that scope cut** explicitly (multi-part formats get no outline in v1), or extend the shape to a per-part section grouping — which reopens the flat-list bound. It cannot claim both "one flat outline" and "covers multi-part artifacts."

---

## F7 — MINOR/SHOULD-FIX — the §18 precedent is disanalogous in shape; orphaned-outline lineage/GC is unaddressed

**What is wrong.** The initial "leans hard" (task's word, accurate) on §18: the AST store "is keyed by its reader-pin digest and is explicitly 'not an id-family member, so no grammar change.'" That text exists and I confirmed it (design §18: "This is internal store keying, not a D2 id — the AST is not an id-family member, so no grammar change (§7.4)"). But the analogy is weaker than the initial presents. **The AST store key is `fitted-id (+ reader-pin digest)` (design §18 table + "The AST store key's disambiguator is the reader-pin digest"): the digest DISAMBIGUATES an id-family primary key and is NOT itself an identity input.** The outline store, as designed, is keyed by a **bare digest** that (i) in C≥1 modes IS simultaneously an `artifact-id` **preimage component** (an identity input — reconciliation S1), and (ii) in mode B is a member of **no** id-family preimage at all. §18 provides precedent for *neither* a bare-digest primary key *nor* a store key that doubles as an identity input. The narrow claim the initial cites it for ("a digest can key a store without a §7.4 grammar change") holds; the weight it bears ("direct precedent") oversells it.

Separately, the initial never addresses **lineage/GC**: every authoring-gate re-edit re-derives a new canonical → new digest → new store entry (§3.4-item-2 makes even a reorder a new digest); abandoned mode-A1 outlines and every intermediate edit are **orphans referenced by no `artifact-id`**. This is consistent with the system's retain-all/GC-deferred posture (§21.8 "RETAINED indefinitely in v1... retention/GC policy registered §27.3"), but it is unstated and the pre-compose store is a **new** store class the §27.3 GC register does not yet cover.

**Severity: minor** (consistency defect + unstated gap), rising to should-fix if the pre-compose store is meant to be first-class.

**What reconciliation must answer.** Down-rank the §18 citation to the narrow claim it supports; and either register the pre-compose outline store under the §27.3 GC/retention item explicitly or state the retain-all posture for it.

---

## F8 — MINOR — the §7.2 preimage extension must preserve re-mint compatibility for all EXISTING stored bindings; the zero-churn claim omits this

**What is wrong.** The "absent-by-default → zero churn" claim (§4.2, inherited from reconciliation S1) is implementable, but the initial states it at the design level without the code-level compatibility requirement it entails.

**Evidence.** `pipeline/ir.py::_validate_binding` re-mints **every stored IR's preimage on read**: `mint_artifact_id(binding["preimage"])` must reproduce the recorded `artifact_id` byte-exact or the read fails `ir-binding-mismatch`. `build_artifact_preimage` (`pipeline/ids.py:587`) is a **frozen, closed-keyword** shape (`topic, persona, format, voice, goals, source_subset, source_commit` — no `**kwargs`). Adding `outline-digest` therefore requires: the new component must be **omitted from the canonical bytes when absent** (not `outline-digest: null`), AND `mint_artifact_id`/`digest_full` must treat a missing key as byte-identical to the pre-extension canonicalization — otherwise every already-stored artifact (which has no outline key) fails re-mint on its next read. The §7.2 model supports this (absent attribute not in the map, design §7.2), so it is achievable — but it is a hard compatibility constraint on the extension, not a free rename.

**Severity: minor** (a real, concrete requirement for the gate item #1 / planner, not a design flaw).

**What reconciliation/gate must answer.** The §7.2 outline-digest extension MUST specify omit-when-absent canonicalization and preserve re-mint of all existing stored bindings; note it alongside gate item #1.

---

## Claims I attacked and could NOT break (honest list)

1. **The 16-row taxonomy enumeration is exhaustive and correct.** I re-derived it: under (i) U⇒C and (ii) G=0⇒E=0∧U=0, exactly {D(0001), A1(1011), B(1100), C(1101), A2(1111)} + null(0000) survive; 1010/1110 die by (i), 1000/1001 are generate-and-discard, 6 G=0 rows die by (ii). Matches the initial. The G/E/U-vs-C facet split is clean (E is outline-emission only; prose delivery rides the normal render verb — no hidden "is the prose emitted?" facet).
2. **"No markdown→IR reverse parser exists anywhere" — TRUE.** Verified: `serialize.parse_to_ast` is markdown→**Pandoc-AST** (fed by `emit_fitted_markdown`, `serialize_fitted` line 609), not markdown→IR; `compose.parse_writer_output`/`reconcile.parse_reconciler_output`/`review.parse_review_output` all parse the **LLM's JSON envelope** (`_extract_json_object`); serialize is forward-only. The "edit→canonical" leg genuinely has no machinery to reuse.
3. **"The writer context is already JSON-assembled so a structured outline slots in" — TRUE.** `build_writer_prompt` `json.dumps`'s a context dict; a new `outline` key is a clean, orthogonal addition. (The *quality* of that as the writer-facing form is F4; the *mechanical* claim holds.)
4. **The GAP-1 re-render path does NOT require the outline present — TRUE and clean.** `render.py::_render` loads the stored artifact via `ir.unwrap_ir` and drives reconcile/serialize; it never reads the outline. The outline-digest lives in the `artifact-id` preimage/binding as lineage only; re-render is fully decoupled. The identity-coupling worry on the re-render path is unfounded.
5. **The "don't reuse the full-IR↔pandoc machinery on the edit path" ruling is sound.** The machinery's raison d'être is provenance preservation (fenced Divs + `data-*` spans, verified in `serialize.py` `emit_part_div`/`enrich_leaf`/`emit_claim_span`), which the outline has none of; and there is no reverse parser to reuse (point 2). The "pandoc only for rich-output-type emit, off the edit path" split is correct.
6. **A2 "two projections of one canonical cannot drift" holds for a FIXED digest.** Both the emit-view and the compose-seed are pure functions of the same canonical; a re-edit simply mints a new digest / new artifact (old persists as lineage per §18 RI11). No intra-digest drift. (The retrieval problem F2 is orthogonal to drift.)
7. **"Absent-by-default → zero churn" for the outline-digest preimage component is consistent with §7.2's additive-evolution model** and implementable given `build_artifact_preimage`'s structure (modulo the F8 compatibility requirement).
8. **The `constraint?`-must-be-schema-fenced orthogonality watch-item (§5) is a genuine, correct guard** — a free-text `constraint: platform.hard_limit=280` would be a real backdoor attribute-override rung, and fencing it to a closed non-cascade vocabulary is the right defense.

---

*End of adversarial pass. Two blockers (F1 round-trip verifies the wrong invariant; F2 emit has no id-family retrieval verb — verified in `pipeline/ids.py`), four should-fixes (F3 normalizer self-contradiction; F4 compose-input default + §4.1 inconsistency; F5 advisory-not-gate residual; F6 flat-list vs multi-part), two minors (F7 §18 disanalogy + GC; F8 re-mint compatibility). The taxonomy, the no-reverse-parser finding, the JSON-context mechanics, and the re-render decoupling survived attack. No code, no plan — reconciliation and the maintainer gate run next.*
