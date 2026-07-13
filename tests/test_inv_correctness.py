"""Step-21 tests: the §22.7 INV-CORRECTNESS guardrails — the CI teeth.

Design §22.7 names three build guardrails; all three are enforced here, and the whole
default pytest run is the CI job (T4: the import lint is a custom pytest/AST check —
"or the build fails" is satisfied by this test job failing):

1. **Signature scoping** — `is_done(id)` / `claim(id)` (and the spine's `drive`) take
   only output-store + claim-registry handles; no SSOT handle exists in any signature.
2. **The import lint** — the correctness modules (materialize/claim/idempotency-check/
   the spine/the future sweep) must not import the SSOT module, transitively, or this
   test fails the build. The lint is proven to BITE on planted violation fixtures.
3. **The SSOT interface contract stub** — S5's hook shape (`AdvanceHook`) is write-only
   w.r.t. control flow: returns None by contract, its call result is syntactically
   discarded (AST-verified), and behaviorally a branch-worthy return value changes
   nothing.

The SSOT module itself does not exist yet (plan step 22); the lint is pre-wired for it
(any `*ssot*`-named import bites) and for the step-36 sweep modules (present-if-exist
roots), so the teeth outlive this step without edits.
"""

import ast
import dataclasses
import inspect
import json
import typing
from collections import deque
from pathlib import Path

import pytest

import pipeline.spine as spine_module
from pipeline.canonical import canonical_json_str
from pipeline.claims import ClaimRegistry
from pipeline.spine import AdvanceHook, WorkUnit, drive
from pipeline.store import WorkspaceStore, is_done

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "pipeline"

#: The §22.7 correctness plane: materialize + idempotency check (`store`), the lock
#: authority (`claims`), the S0–S6 spine (`spine`), and the FUTURE completeness-sweep
#: homes (step 36: `parallel`; `sweep` reserved) — pre-wired so step 36 lands already
#: covered. Absent files are skipped; present ones MUST be clean.
CORRECTNESS_ROOTS = ("store", "claims", "spine", "sweep", "parallel")

#: Any imported dotted name with a segment containing this substring is a violation
#: (`pipeline.ssot`, `ssot_backend`, `from pipeline import ssot`, …).
FORBIDDEN = "ssot"


# ---------------------------------------------------------------------------
# The import lint (guardrail 2): a transitive AST walk over in-package imports.
# ---------------------------------------------------------------------------


def _module_file(package_root: Path, dotted_tail: str) -> Path | None:
    """Resolve `pkg.a.b`'s tail to a file under the package root (None = not a module)."""
    parts = dotted_tail.split(".")
    as_module = package_root.joinpath(*parts).with_suffix(".py")
    if as_module.is_file():
        return as_module
    as_package = package_root.joinpath(*parts, "__init__.py")
    if as_package.is_file():
        return as_package
    return None


def _imports_of(path: Path, module_dotted: str) -> set[str]:
    """Every dotted name `path` imports — absolute and resolved-relative forms.

    For `from M import x`, both `M` and `M.x` are candidates: `x` may itself be a
    submodule (`from pipeline import ssot` must bite).
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: resolve against this module's dotted location
                base = module_dotted.split(".")[: -node.level]
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            if module:
                names.add(module)
            for alias in node.names:
                names.add(f"{module}.{alias.name}" if module else alias.name)
    return names


def _offending(names: set[str]) -> list[str]:
    return sorted(
        name for name in names if any(FORBIDDEN in segment.lower() for segment in name.split("."))
    )


def closure_violations(
    package: str, package_root: Path, roots: tuple[str, ...]
) -> tuple[dict[str, list[str]], set[str]]:
    """BFS the in-package import graph from `roots`; return (violations, visited).

    `violations` maps each reachable module to the ssot-shaped names it imports —
    empty means the correctness plane is clean, TRANSITIVELY. Out-of-package imports
    are checked by name but not followed.

    Python executes the package `__init__.py` on EVERY `pkg.*` import — an implicit,
    unconditional edge into every root — so it is seeded into the walk unconditionally;
    likewise, following `pkg.a.b` enqueues each ancestor package's `__init__.py` (RV-1).
    """
    queue: deque[tuple[str, Path]] = deque()
    init = package_root / "__init__.py"
    if init.is_file():
        queue.append((package, init))
    for root in roots:
        file = _module_file(package_root, root)
        if file is not None:
            queue.append((f"{package}.{root}", file))
    visited: set[str] = set()
    violations: dict[str, list[str]] = {}
    while queue:
        dotted, file = queue.popleft()
        if dotted in visited:
            continue
        visited.add(dotted)
        imports = _imports_of(file, dotted)
        offending = _offending(imports)
        if offending:
            violations[dotted] = offending
        for name in imports:
            if name == package:
                candidate = package_root / "__init__.py"
                if candidate.is_file() and package not in visited:
                    queue.append((package, candidate))
            elif name.startswith(package + "."):
                tail = name.removeprefix(package + ".")
                parts = tail.split(".")
                for depth in range(1, len(parts) + 1):
                    prefix = ".".join(parts[:depth])
                    candidate = _module_file(package_root, prefix)
                    if candidate is not None:
                        queue.append((f"{package}.{prefix}", candidate))
    return violations, visited


class TestImportLint:
    def test_correctness_modules_import_no_ssot_module_transitively(self):
        violations, visited = closure_violations("pipeline", PACKAGE_ROOT, CORRECTNESS_ROOTS)
        assert violations == {}, (
            f"§22.7 INV-CORRECTNESS violated: correctness modules import SSOT code: {violations}"
        )
        # Walker sanity: the closure really traversed the correctness plane's graph —
        # a vacuous pass (nothing visited) can never masquerade as clean. "pipeline"
        # is the package __init__ edge (RV-1): executed on every pipeline.* import,
        # so it must be walked on every run.
        assert {
            "pipeline",
            "pipeline.store",
            "pipeline.claims",
            "pipeline.spine",
            "pipeline.ids",
            "pipeline.canonical",
        } <= visited

    def test_future_sweep_modules_are_pre_wired_into_the_lint(self):
        # Step 36's sweep home is covered the moment its file appears — no lint edit.
        assert "sweep" in CORRECTNESS_ROOTS
        assert "parallel" in CORRECTNESS_ROOTS

    @pytest.mark.parametrize(
        "stmt",
        [
            "import fake.ssot",
            "import fake.ssot as bookkeeping",
            "from fake.ssot import advance",
            "from fake import ssot",
            "from . import ssot",
            "import ssot_backend",
        ],
    )
    def test_lint_bites_on_a_planted_violation(self, tmp_path, stmt):
        # The teeth are real: a fixture module importing an ssot-named module FAILS it,
        # whatever the import spelling.
        pkg = tmp_path / "fake"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "ssot.py").write_text("def advance(_id):\n    return None\n")
        (pkg / "victim.py").write_text(stmt + "\n")
        violations, _ = closure_violations("fake", pkg, ("victim",))
        assert "fake.victim" in violations
        assert violations["fake.victim"]  # names the offending import

    def test_lint_bites_transitively_through_an_intermediary(self, tmp_path):
        # A correctness module hiding the SSOT import one hop away still fails.
        pkg = tmp_path / "fake"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "ssot.py").write_text("ROW = None\n")
        (pkg / "helper.py").write_text("from fake.ssot import ROW\n")
        (pkg / "clean_looking.py").write_text("import fake.helper\n")
        violations, visited = closure_violations("fake", pkg, ("clean_looking",))
        assert "fake.helper" in violations
        assert {"fake.clean_looking", "fake.helper"} <= visited

    def test_lint_bites_on_a_violation_planted_in_the_package_init(self, tmp_path):
        # RV-1: the package __init__ executes on every in-package import — an implicit
        # transitive edge into every correctness module. An SSOT import hidden there
        # must fail the build even though no root imports the package by name.
        pkg = tmp_path / "fake"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("import fake.ssot\n")
        (pkg / "ssot.py").write_text("")
        (pkg / "victim.py").write_text("import json\n")
        violations, visited = closure_violations("fake", pkg, ("victim",))
        assert "fake" in violations
        assert "fake" in visited

    def test_clean_fixture_passes(self, tmp_path):
        pkg = tmp_path / "fake"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "clean.py").write_text("import json\nfrom pathlib import Path\n")
        violations, visited = closure_violations("fake", pkg, ("clean",))
        assert violations == {}
        assert "fake.clean" in visited

    def test_absent_roots_are_skipped_not_failed(self, tmp_path):
        pkg = tmp_path / "fake"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        violations, visited = closure_violations("fake", pkg, ("not_written_yet",))
        assert violations == {}
        # The absent root contributes nothing; only the always-walked package
        # __init__ (RV-1) is visited.
        assert visited == {"fake"}


# ---------------------------------------------------------------------------
# Signature scoping (guardrail 1): no SSOT handle exists in any signature.
# ---------------------------------------------------------------------------


class TestSignatureScoping:
    def test_is_done_takes_exactly_the_output_store_handle(self):
        params = list(inspect.signature(is_done).parameters)
        assert params == ["store", "id_str"]

    def test_claim_registry_holds_exactly_the_claim_registry_handle(self):
        fields = {f.name for f in dataclasses.fields(ClaimRegistry)}
        assert fields == {"claims_dir", "holder", "ttl_seconds", "clock"}
        for method in ("acquire", "release", "peek"):
            params = list(inspect.signature(getattr(ClaimRegistry, method)).parameters)
            assert params == ["self", "id_str"], method

    def test_drive_signature_is_scoped_to_store_plus_claims(self):
        sig = inspect.signature(drive)
        assert list(sig.parameters) == [
            "unit",
            "store",
            "claims",
            "recorded_preimage",
            "advance",
            "checkpoint",
        ]
        # Everything after the unit is keyword-only — no positional smuggling.
        for name, param in sig.parameters.items():
            if name != "unit":
                assert param.kind is inspect.Parameter.KEYWORD_ONLY, name

    def test_no_ssot_shaped_name_appears_in_any_correctness_signature(self):
        surfaces = [drive, is_done, ClaimRegistry.acquire, ClaimRegistry.release]
        for surface in surfaces:
            sig = inspect.signature(surface)
            for name, param in sig.parameters.items():
                assert "ssot" not in name.lower(), surface
                assert "ssot" not in str(param.annotation).lower(), surface

    def test_workunit_carries_no_ssot_coordinate(self):
        fields = {f.name for f in dataclasses.fields(WorkUnit)}
        assert fields == {"id", "payload", "preimage", "folios"}


# ---------------------------------------------------------------------------
# The SSOT contract stub (guardrail 3): S5 is write-only w.r.t. control flow.
# ---------------------------------------------------------------------------


class ManualClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


class TestS5WriteOnlyContract:
    def test_advance_hook_shape_takes_the_id_and_returns_none(self):
        arg_types, return_type = typing.get_args(AdvanceHook)
        assert arg_types == [str]
        # Nothing to consume, by contract (`None` vs `NoneType` is a typing-internals
        # spelling difference across alias kinds — both mean "returns nothing").
        assert return_type is None or return_type is type(None)

    def test_spine_source_discards_every_hook_call_result(self):
        # AST teeth: each `advance(...)` call in the spine is a bare expression
        # statement — its value is never assigned, compared, or branched on.
        tree = ast.parse(Path(spine_module.__file__).read_text(encoding="utf-8"))
        hook_calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "advance"
        ]
        assert hook_calls, "the spine must invoke the S5 hook somewhere"
        bare_expression_values = [
            node.value for node in ast.walk(tree) if isinstance(node, ast.Expr)
        ]
        for call in hook_calls:
            assert call in bare_expression_values

    def test_spine_exposes_no_ssot_read_surface(self):
        # No public name offers a status predicate the spine (or a caller inside the
        # correctness plane) could branch on.
        assert not [
            name
            for name in spine_module.__all__
            if "ssot" in name.lower() or "status" in name.lower() or "row" in name.lower()
        ]

    def test_branch_worthy_hook_returns_change_nothing(self, tmp_path):
        # Behavioral proof: hooks returning maximally branchy values (falsy vs truthy)
        # produce identical SpineResults and identical store end-states.
        art = "a-9f3c07d21b44e8aa"
        payload = (canonical_json_str({"v": 1}) + "\n").encode()
        results, states = [], []
        for name, ret in (("falsy", False), ("truthy", object())):
            store = WorkspaceStore(tmp_path / name)
            claims = ClaimRegistry(
                store.claims_dir, holder="worker-a", ttl_seconds=60.0, clock=ManualClock()
            )
            results.append(
                drive(
                    WorkUnit(id=art, payload=lambda: payload),
                    store=store,
                    claims=claims,
                    advance=lambda _id, _ret=ret: _ret,
                )
            )
            states.append(
                (
                    store.output_path(art).read_bytes(),
                    sorted(p.name for p in (store.root / "claims").iterdir()),
                )
            )
        assert results[0] == results[1]
        assert states[0] == states[1]
        assert json.loads(states[0][0]) == {"v": 1}
