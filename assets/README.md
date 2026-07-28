---
provenance: framework
---

# assets/ — the framework content-asset home

This top-level `assets/` directory is the **framework** example-image / content-asset home
(`provenance: framework`). It is the public-repo counterpart to each client's own
`workspaces/<client>/assets/`.

## Where assets live

- **Client / instance assets live ONLY under `workspaces/<client>/assets/`.** They must never
  appear here or in any other client's workspace (CLAUDE.md rule 2; design §10 — scope is encoded
  by location). Generated assets are content-addressed (named by the SHA-256 of their bytes), so
  the same image is never written twice.
- **Framework example images** — generic, client-free illustrations that ship in the public repo —
  belong here. They are **DEFERRED**: until a filename/path client-name scan exists to prove an
  example image carries no client identity, this home admits only this README.

## Emptiness is a mechanism, not a hope

This directory is deliberately outside the content-scan SCOPES (binaries carry no `provenance:`
frontmatter to default-deny on), so a stray client image dropped here would otherwise ship in the
public repo UNFLAGGED. `scripts/check-no-content.sh` therefore holds this home empty with a real
guard arm: any tracked file under `assets/` other than this `README.md` fails the build as
`LEAK[framework-asset]`. Framework example images ship later by extending that arm to the
client-name path scan.
