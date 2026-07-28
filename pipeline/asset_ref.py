"""The intra-body asset-reference containment guard — client isolation for image paths.

Design authority: CLAUDE.md rule 2 (client isolation via workspaces) + `docs/design.md` §10
(client isolation is structural). A composed document body may reference an image by a
relative path (`![alt](assets/throughput.png)`). That path is later handed to the renderer
(increment B) as a `--resource-path`/cwd-relative reference. Without a guard, a body carrying
`![](../../workspaces/other/secret.png)` — or a disguised `assets/%2e%2e/%2e%2e/secret.png` —
would let one client's document reach into ANOTHER client's files at render time. This module
is the single **resolve-and-contain** guard the compose gate (increment A4) calls at COMPOSE,
PRE-persist, so an escaping body can never be written and no re-ask ever reads the offending
file.

**THE BASE CONTRACT (S5), pinned here so increment B inherits it exactly.** The containment
base is the WORKSPACE STORE ROOT (`pipeline.store.WorkspaceStore.root`), and the asset root a
reference must stay inside is `<workspace_root>/assets`. This SAME root is B's render
resource-path base: B MUST resolve a relative `assets/...` reference at render time (pandoc
`--resource-path`/cwd) against `workspace_root`. If B picks a different base, this module's
containment proof does not transfer — **guard base == render resource-path base ==
`store.root`** is the invariant that makes the compose-time proof cover the render-time read.

**Airtight-and-simple posture — a shape allowlist BEFORE any resolve, then resolve-and-contain.**
Security must NOT depend on whether the referenced file happens to exist. So
`assert_asset_refs_contained` runs, per target and in order, a PRIMARY shape-allowlist hygiene
check (reject empty/`.`/whitespace, any `%` percent-encoding, any backslash, any absolute path,
any `..` segment, and anything not literally prefixed `assets/`) BEFORE it touches the
filesystem. Only a shape-clean reference reaches the resolve-and-contain step, which resolves
BOTH sides — mirroring GAP-9's `pipeline.workspace_name` SHAPE (not its code: that guard checks
a DIRECT-CHILD name relation; this one checks CONTAINMENT at ANY depth via `is_relative_to`,
because a generated asset nests, e.g. `assets/diagrams/<hash>.svg`) — and so also defeats a
symlink escape a pure string check cannot see. Existence is the LAST, separate check and is
explicitly NOT load-bearing for security (increment B may rely on it or relax it).

**Two honest outcomes.** A reference that points (or tries to point) OUTSIDE the client's own
asset root is a client-isolation escape (`AssetRefError.kind == "uncontained"`); a reference
that is merely empty or a dangling/missing file is a benign broken link
(`AssetRefError.kind == "invalid"`). A benign broken link is never dressed up as a cross-client
breach. Increment A4 maps these two kinds to the distinct result codes `asset-ref-uncontained`
and `asset-ref-invalid`.

This module imports ONLY the standard library (`pathlib`) — no `pipeline` import, no cycle
risk — and mutates no filesystem state: it inspects and resolves paths, and stats an
already-shape-cleaned, already-contained path for the existence check.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "ASSETS_DIRNAME",
    "AssetRefError",
    "assert_asset_refs_contained",
    "has_raw_markup",
    "iter_image_targets",
]

#: The single directory, under each workspace store root, that content assets live in — the
#: only path prefix a body image reference may carry (CLAUDE.md rule 2; §10). A reference is
#: contained iff it resolves inside `<workspace_root>/assets`.
ASSETS_DIRNAME = "assets"

#: The two raw-passthrough Pandoc node types a persisted body may not contain. A `RawInline`/
#: `RawBlock` (any format — HTML, TeX, anything) can express a file reference the Markdown
#: `Image` walk never sees (`<img src=...>`, `\includegraphics{...}`), so the compose gate
#: (A4) refuses a body whose AST carries either, rather than trying to enumerate every raw
#: file-reference vector. `has_raw_markup` reports their presence.
_RAW_MARKUP_TYPES = frozenset({"RawInline", "RawBlock"})


class AssetRefError(Exception):
    """A body image reference is not a shape-clean, contained `assets/...` path.

    Mirrors `pipeline.workspace_name.WorkspaceNameError`'s target/kind/detail shape so the
    compose gate can surface the machine `kind` in a result's `context` and the human `detail`
    as its `hint`. `kind` is one of `uncontained` (a client-isolation escape — the reference
    points, or tries to point, outside the client's own asset root) or `invalid` (a benign
    broken reference — empty, `.`, whitespace-only, or a dangling/missing file). The two map to
    the distinct result codes `asset-ref-uncontained` and `asset-ref-invalid` in A4.
    """

    def __init__(self, target: object, kind: str, detail: str) -> None:
        super().__init__(f"invalid-asset-ref: {detail}")
        self.target = target
        self.kind = kind
        self.detail = detail


def iter_image_targets(node: object) -> list[str]:
    """Every Pandoc `Image` URL in the AST subtree, at ANY nesting depth.

    The AST is WALKED, never regex-matched: an `Image` node is
    `{"t":"Image","c":[attr, caption-inlines, [url, title]]}`, so the target URL is `c[2][0]`,
    read DEFENSIVELY (type/length guards — a malformed node contributes nothing rather than
    raising). An `Image` nested inside a `Figure` (pandoc's `implicit_figures`, the shape a
    plain `![alt](url)` block takes) is reached because the walk descends every value; an
    `![](...)` inside a code span/fence is a `Code` node, not an `Image`, so it is correctly
    NOT collected. Mirrors `pipeline.compose._iter_citations`.
    """
    found: list[str] = []
    if isinstance(node, dict):
        if node.get("t") == "Image":
            content = node.get("c")
            if isinstance(content, list) and len(content) >= 3:
                target = content[2]
                if isinstance(target, list) and target and isinstance(target[0], str):
                    found.append(target[0])
        for value in node.values():
            found.extend(iter_image_targets(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(iter_image_targets(value))
    return found


def has_raw_markup(node: object) -> bool:
    """True iff the AST subtree carries any raw-passthrough node (`RawInline`/`RawBlock`).

    Any format counts (HTML, TeX, anything): a raw node can smuggle a file reference the
    `Image` walk never sees, so the compose gate (A4) refuses a body when this returns True
    rather than enumerating every raw file-reference vector. The AST is walked, never
    regex-matched.
    """
    if isinstance(node, dict):
        if node.get("t") in _RAW_MARKUP_TYPES:
            return True
        return any(has_raw_markup(value) for value in node.values())
    if isinstance(node, list):
        return any(has_raw_markup(value) for value in node)
    return False


def assert_asset_refs_contained(targets: list[str], *, workspace_root: str | Path) -> None:
    """Raise `AssetRefError` on the FIRST reference that is not a contained `assets/...` path.

    `workspace_root` is the workspace store root (`WorkspaceStore.root`); the asset root a
    reference must stay inside is `<workspace_root>/assets`. Per target, in order — each a
    fail-closed refusal that runs BEFORE any filesystem stat except the last:

    1. empty / `.` / whitespace-only                       -> `invalid`
    2. contains an ASCII control char (0x00-0x1f, 0x7f, incl. NUL) -> `uncontained`
    3. contains `%` (percent-encoding)                      -> `uncontained`
    4. contains a backslash `\\`                            -> `uncontained`
    5. absolute (leading `/`)                               -> `uncontained`
    6. any `..` path segment                                -> `uncontained`
    7. does not start with `assets/`                        -> `uncontained`
    8. resolves outside `<workspace_root>/assets` (resolve BOTH sides — catches the symlink
       escape a shape check cannot see)                     -> `uncontained`
    9. resolves to a non-existent / non-file path (a shape-clean, CONTAINED, dangling
       reference)                                           -> `invalid`

    Steps 1-8 make containment airtight WITHOUT step 9: existence (9) is an honest broken-image
    quality check, NOT a security backstop (S1). A disguised-traversal reference like
    `assets/%2e%2e/%2e%2e/secret.png` is refused at step 3 as `uncontained`, before any resolve.
    The step-2 control-char guard is a TOTALITY guarantee: an embedded NUL otherwise reaches
    `pathlib` and raises a bare `ValueError` ("embedded null character") that A4's
    `except AssetRefError` would NOT catch — so the guard must refuse EVERY control char BEFORE
    `resolve()`, ensuring it never lets a non-`AssetRefError` escape to the compose gate.
    """
    root = Path(workspace_root)
    assets_root = (root / ASSETS_DIRNAME).resolve(strict=False)
    for target in targets:
        # (1) empty / `.` / whitespace-only — a benign broken reference, not an escape.
        stripped = target.strip()
        if not stripped or stripped == ".":
            raise AssetRefError(
                target,
                "invalid",
                f"image reference {target!r} is empty, '.', or whitespace-only — a body image "
                "must be a contained assets/... path (CLAUDE.md rule 2, §10)",
            )
        # (2) control characters — runs BEFORE resolve so no surprising byte reaches `pathlib`.
        # An embedded NUL makes `Path(...).resolve()` raise a bare `ValueError`, NOT an
        # `AssetRefError`, which would crash A4's compose gate (`except AssetRefError` misses it);
        # refusing the WHOLE control range (0x00-0x1f, 0x7f) upfront keeps the guard total — it
        # only ever raises `AssetRefError`. A control byte is never a legitimate asset path.
        control = next((ch for ch in target if ord(ch) < 0x20 or ord(ch) == 0x7f), None)
        if control is not None:
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} contains a control character (0x{ord(control):02x}) "
                "— a body image must be plain printable text; a NUL or other control byte can "
                "smuggle a path past a naive check or crash the resolver (CLAUDE.md rule 2, §10)",
            )
        # (3)-(7) PRIMARY shape allowlist — runs BEFORE any resolve, so security never depends
        # on the existence check. Each is an escape vector, hence `uncontained`.
        if "%" in target:
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} contains '%' (percent-encoding) — a decoded escape "
                "like assets/%2e%2e/secret.png can leave the client's asset root; author a plain "
                "assets/... path with no percent-encoding (CLAUDE.md rule 2, §10)",
            )
        if "\\" in target:
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} contains a backslash — a body image must be a plain "
                "forward-slash assets/... path (CLAUDE.md rule 2, §10)",
            )
        if target.startswith("/"):
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} is an absolute path — a body image must be a "
                "workspace-relative assets/... path (CLAUDE.md rule 2, §10)",
            )
        if ".." in target.split("/"):
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} contains a '..' segment — a body image may not "
                "traverse out of the client's asset root, even if it normalizes back inside "
                "(CLAUDE.md rule 2, §10)",
            )
        if not target.startswith(f"{ASSETS_DIRNAME}/"):
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} is not prefixed 'assets/' — a body image must be a "
                "contained assets/... path (CLAUDE.md rule 2, §10)",
            )
        # (8) resolve-and-contain — resolve BOTH sides (mirrors GAP-9's shape) so a symlink
        # escape a string check cannot see is still caught; CONTAINMENT is descendant-at-any-
        # depth (`is_relative_to`), because a generated asset nests (assets/diagrams/<hash>.svg).
        resolved = (root / target).resolve(strict=False)
        if not resolved.is_relative_to(assets_root):
            raise AssetRefError(
                target,
                "uncontained",
                f"image reference {target!r} resolves outside the client's asset root "
                f"{str(assets_root)!r} (e.g. via a symlink) — client isolation is enforced by "
                "resolve-and-contain, not by trust (CLAUDE.md rule 2, §10)",
            )
        # (9) existence — an HONEST broken-image quality check on an already-contained path;
        # NOT load-bearing for security (steps 1-8 already guarantee containment).
        if not resolved.is_file():
            raise AssetRefError(
                target,
                "invalid",
                f"image reference {target!r} is contained but points to no file — a broken "
                "image link (this is a quality check, not an isolation escape)",
            )
