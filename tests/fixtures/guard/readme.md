# Guard negative fixtures (plan step 13, PA-1)

Fixture trees for `tests/test_guard.py`, exercising `scripts/check-no-content.sh` via its
REC-3 test seam (`--root <copied tmpdir> --mode all`). This directory lives under
`tests/`, which is **structurally outside the guard's scan scope** (PA-1b) — these files
are tracked, yet the repo-root guard run never sees them and CI stays green.

Every violation-shaped file here is **obviously synthetic** (`fixture-*` / `x-fixture-*`
names, `x-fixture:` marker content) — never real client or instance data. One tree per
leak class:

| tree | leak class it fires |
|---|---|
| `missing-provenance/` | `LEAK[missing-provenance]` — registry entry without `provenance:` (default-deny, §10 Q15 rule 4) |
| `provenance-instance/` | `LEAK[provenance-instance]` — registry entry tagged `provenance: instance` (§10 rule 5) |
| `x-file/` | `LEAK[x-file]` — `x-*` file in a registry root (§11.4 SV5) |
| `instance-defaults/` | `LEAK[instance-defaults]` — tracked `instance/defaults.yaml` (the T10 surface, PA-1c) |
| `instance-ops/` | `LEAK[instance-ops]` — tracked file under `instance/ops/` |
| `workspace-content/` | `LEAK[workspace-content]` — tracked client content under `users/` (any depth beneath `users/<user>/workspaces/<workspace>/`; §23 re-home) |
| `templates-x-file/` | `LEAK[x-file]` — an `x-*` client blueprint directly under `templates/` ([W8]: templates/ is framework mechanism, §11.4 SV5) |
| `templates-workspace-x-file/` | `LEAK[x-file]` — an `x-*` file nested DEEP in `templates/workspace/sub/` (BLOCKER close: the blueprint subtree is NOT exempt wholesale — it flows through the [W8] arm) |

The step-13 review (RV-1/RV-2) added four trees proving a `*.template.*` basename never
defeats the structural classes or hides an explicit instance tag:

| tree | leak class it fires |
|---|---|
| `template-name-workspace/` | `LEAK[workspace-content]` — `users/acme/workspaces/proj/secret.template.md` (RV-1: the path alone names a user/client) |
| `template-name-instance-ops/` | `LEAK[instance-ops]` — `instance/ops/telemetry.template.jsonl` (RV-1: no exemption under `instance/ops/`) |
| `template-name-x-file/` | `LEAK[x-file]` — `topics/x-dir/notes.template.md` (RV-1: SV5 leaks by path, template-named or not) |
| `template-name-provenance-instance/` | `LEAK[provenance-instance]` — `topics/fixture-instance-tagged.template.md` (RV-2: an explicit `provenance: instance` line leaks even under a template name) |
| `x-schema-registry/` | `LEAK[x-file]` — `topics/x-acme/_schema.yaml` (RV-1 ordering lock, B-2: an `x-*` extension registry is registry-shaped and carries a `_schema.yaml`; the `x-*` PATH check fires BEFORE the depth-agnostic `_schema.yaml` basename exemption, so the reserved instance namespace still leaks) |

`clean-framework/` is the POSITIVE tree: a populated `provenance: framework` registry
entry (which the pre-step-13 guard would have rejected — the ordering-invariant proof for
step 14), plus the exempt/passing surfaces (a `*.template.*` file without provenance, the
`instance/*.template.*` direct-child allowlist, a GENERIC `templates/workspace/` blueprint
file — scanned by the [W8] arm and passed because it carries no instance signal, the §23
re-home — and a co-located `_schema.yaml`). The new guard passes it.

## B-2 foundation-arm fixtures (the `foundation/` reorg, dual-safe)

The B-2 content-guard rework makes the guard `foundation/`-anchored while staying green on
today's still-flat repo. Two parallel fixture trees exercise the foundation arm (the flat
trees above continue to cover the flat path — the guard is dual-safe):

| tree | outcome |
|---|---|
| `foundation-clean/` | exit 0 — a clean `foundation/dimensions/topics/` registry (co-located `_schema.yaml`, exempt by BASENAME at depth, + a `provenance: framework` entry). The registry IS in `FOUNDATION_REGISTRY_DIRS`, so the GAP-4a coverage check passes it. |
| `foundation-unknown-root/` | `LEAK[unknown-registry-root]`, exit 1 — a `foundation/dimensions/gadgets/` registry whose token is NOT in `pipeline.layout.REGISTRY_BASE` / `FOUNDATION_REGISTRY_DIRS` (it would ship unvetted). The foundation-anchored counterpart of the flat `glossaries/` unknown-root case. |

The `foundation/` marker paths inside these trees begin with `tests/…` at the repo root, so
the anchored `foundation/`-prefix `case` never matches them on a real-repo guard run — they
are inert exactly like every other tracked fixture (PA-1b).
