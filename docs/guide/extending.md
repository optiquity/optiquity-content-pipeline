# Extending it

## Extending it

Every extension point is a one-file change; a new axis/stage is a config addition plus its own registry directory, not a rewrite.

- **A new matrix value.** Drop a Markdown entry into the axis directory — topics/, personas/, platforms/, or formats/ — and the resolver picks it up.
- **A recipe.** Add a file under recipes/ to bundle a genre's settings.
- **A source adapter.** Add a reader module under pipeline/adapters/ next to folder.py, fsast.py, and graphify.py, then register it so the driver can select it.
- **A scope default.** Set instance- or workspace-level defaults that load_scope_defaults reads into a ScopeDefaults. (The `users/<user>/` addressing prefix is **not** a scope-default rung — the value cascade stays framework → instance-global → workspace; the user level only changes *where* a workspace lives, §23.)
- **A whole pipeline stage.** Adding an editor-style stage is three steps: Add the agent file... Register it in the pipeline stage list (config), positioned after writer... items flow through the new stage and record its result column. New stages attach here without disturbing existing ones.

## Schema evolution and versioning

The registry schemas all share **one global `schema_version`**, and bumping it is a **release act, not a per-change one**. During development you make schema changes freely — add a new attribute at its floor, widen a type, clarify a `definition:` — with **no version bump**: a new attribute that rides its L0 floor leaves every existing entry valid and every id byte-identical, so nothing needs to move (design §11.2).

The schema-lint enforces this **release-relative**, not per-commit. It baselines the *last release* — a committed `pipeline/released_baseline` marker, which is **absent before the first release** — so pre-release the version-bump clauses are inert and schemas evolve without ceremony. The first schema change *after* a release is the first that must bump the version and ship a migration step. (The fix that made the lint release-relative rather than demanding a bump for every pre-release change is commit `330fc6d`.)

What still **always fails**, release or not: a malformed schema, a `schema_version` **skew** across the co-located schemas, and any slug, provenance, or closed-schema violation. Those are structural correctness checks, independent of the release baseline.

**The attribute reference.** Every registry attribute's type, floor, and prose meaning lives in [`docs/reference/attributes.md`](../reference/attributes.md), regenerated with `pipeline docs attributes`. Adding or clarifying an attribute's `definition:` is a free doc improvement — regenerate the reference in the same change, and a byte-equality drift test (`tests/test_attributes_doc_contract.py`) fails loudly if a schema `definition:` is edited without regenerating the page.

## Known issues and open items

Some things are deliberately deferred; treat the tracker as the authority, not this manual.

- **The known-issues tracker.** docs/ carries known-issues.md, the register that named deferrals point to.
- **Reserved and deferred features.** The design's reservation table defers a range of features — Language/localization fanout GA... AIMD width auto-tune... Per-part dimension overrides among them — each designed to slot in additively later. (The HTTP shim for cloud orchestrators, once on this list, has since shipped — see *HTTP access* in the [Interfaces guide](interfaces.md#http-access-cloud-orchestrators).)
- **HTTP shim — known limits.** A few honest deferrals on the `pipeline serve` door: composing in a single HTTP call — one `begin-session` that also generates — is not wired; the supported path is two calls (open the session, then generate), which already covers the case. The concurrency cap is advisory: the account-wide count currently sees only the shim's own in-flight jobs, so bounding true spend across other callers is a fidelity follow-up. And pinning a webhook's connection to its validated IP — the last edge of the DNS-rebinding case — is deferred; the shipped mitigation re-checks the address again at delivery time.
- **Unverified transport.** The invocation details are not yet proven: the transport's specifics are unverified and gated before build, including subscription-auth headless operation and the n8n→headless mechanism.
- **Maintainer-gated runs.** Actions that cost or commit are held for a maintainer. The bootstrap commit runs only on approval, and a session should update state.md and propose (not make) a commit.
- **Presentation-asset lowering on the production path.** This manual has no grounded fact fixing whether presentation-asset lowering runs on the production path, so it stays a lead to verify in the known-issues tracker rather than a claim stated here.

---
[← Manual home](../../README.md) · Previous: [Clients](clients.md)
