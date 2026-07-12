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
| `workspace-content/` | `LEAK[workspace-content]` — tracked path under `workspaces/` outside `workspace.template/` |

The step-13 review (RV-1/RV-2) added four trees proving a `*.template.*` basename never
defeats the structural classes or hides an explicit instance tag:

| tree | leak class it fires |
|---|---|
| `template-name-workspace/` | `LEAK[workspace-content]` — `workspaces/acme/secret.template.md` (RV-1: the path alone names a client) |
| `template-name-instance-ops/` | `LEAK[instance-ops]` — `instance/ops/telemetry.template.jsonl` (RV-1: no exemption under `instance/ops/`) |
| `template-name-x-file/` | `LEAK[x-file]` — `topics/x-dir/notes.template.md` (RV-1: SV5 leaks by path, template-named or not) |
| `template-name-provenance-instance/` | `LEAK[provenance-instance]` — `topics/fixture-instance-tagged.template.md` (RV-2: an explicit `provenance: instance` line leaks even under a template name) |

`clean-framework/` is the POSITIVE tree: a populated `provenance: framework` registry
entry (which the pre-step-13 guard would have rejected — the ordering-invariant proof for
step 14), plus the exempt surfaces (a `*.template.*` file without provenance, the
`instance/*.template.*` direct-child allowlist, `workspaces/workspace.template/` content,
a co-located `_schema.yaml`). The new guard passes it.
