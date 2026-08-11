"""Sources paid-key SEAM (plan G9) — the sources subsystem's keys converge on the SHARED keystore.

Proves the three G9 properties, with NO spend and NO real secret in the repo tree (every store is
under a pytest `tmp_path`):

- **convergence** — a keyed source resolves a `fred:*`-style handle via the SAME
  `pipeline.spend.keystore.SecretResolver`/`FileSecretBackend` the transport path uses; the seam
  defaults to the identical zero-arg store, so a sources key and a transport key share ONE store.
- **module boundary (the G9 MINOR)** — `pipeline/sources/**` imports ONLY `pipeline.spend.keystore`
  (never resolve/meter/wall/entitlement/assignment/construction); `compose`/`review`/`reconcile`
  import NO `pipeline.spend` at all. An import-graph (ast) check — precise, never tripped by a
  docstring that merely names a forbidden module.
- **no secret leakage (I5)** — the seam surfaces the HANDLE, never the value: a `ResolvedSecret`
  redacts in `repr`/`str`, the value is reachable only via `.reveal()`, and a keyless source yields
  `None` (no value at all).

The seam adds NO new spend surface — it converges only KEY resolution; paid research spend still
rides the unchanged `--go` / `ResearchBudget` path.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from pipeline.sources import keystore as sources_keystore
from pipeline.sources.keystore import (
    SOURCE_KEY_FIELD,
    KeyStoreError,
    ResolvedSecret,
    SecretHandleError,
    SecretNotFoundError,
    SecretPermissionsError,
    SecretRef,
    SecretResolver,
    SourceKeyError,
    default_source_resolver,
    resolve_source_key,
    resolve_source_secret,
    source_secret_ref,
)
from pipeline.spend.keystore import FileSecretBackend
from pipeline.spend.keystore import SecretResolver as SpendSecretResolver

REPO_ROOT = Path(__file__).resolve().parents[1]

# A recognizable, high-entropy sentinel: if these bytes ever surface in a repr/str/log/exception,
# a leak assertion fails LOUDLY on the exact string.
FRED_KEY = "fred-SUPER-SECRET-abcdef0123456789-do-not-log"
FRED_HANDLE = "fred:default"


def _store(tmp_path: Path) -> FileSecretBackend:
    """A shared-keystore backend rooted at an ABSOLUTE out-of-repo tmp dir (never the repo tree)."""
    return FileSecretBackend(tmp_path / "secrets")


# --- convergence: sources resolves a paid key via the SHARED resolver -------------------------


def test_sources_resolves_a_fred_key_via_the_shared_resolver(tmp_path: Path):
    """A keyed source resolves its `fred:*` handle through the SAME `SecretResolver` transport uses
    (here a `FileSecretBackend`), getting the exact stored value back — at USE time."""
    store = _store(tmp_path)
    store.store(SecretRef.parse(FRED_HANDLE), FRED_KEY)

    resolved = resolve_source_secret(FRED_HANDLE, resolver=store)
    assert isinstance(resolved, ResolvedSecret)
    assert resolved.reveal() == FRED_KEY
    assert resolved.ref.handle == FRED_HANDLE


def test_the_seam_resolver_is_the_same_class_the_transport_path_uses():
    """`SecretResolver` re-exported by the sources seam IS the spend-package contract, and the
    default backend IS `FileSecretBackend` — the SAME class G7's `resolve.py` builds. One keystore
    type, one store, serving both `anthropic:*` (transport) and `fred:*` (sources)."""
    assert SecretResolver is SpendSecretResolver
    resolver = default_source_resolver(env={"OPTIQUITY_SECRETS_DIR": "/tmp/does-not-matter-here"})
    assert isinstance(resolver, FileSecretBackend)
    assert isinstance(resolver, SecretResolver)


def test_one_store_serves_both_transport_and_sources_handles(tmp_path: Path):
    """The SAME store holds an `anthropic:*` transport key AND a `fred:*` sources key — proving the
    single-keystore convergence (design once, serve both). The sources seam reads the `fred:*` one
    via the shared resolver; both namespaces coexist in one 0600 store."""
    store = _store(tmp_path)
    store.store(SecretRef.parse("anthropic:acme-prod"), "sk-ant-transport-key")
    store.store(SecretRef.parse(FRED_HANDLE), FRED_KEY)

    assert resolve_source_secret(FRED_HANDLE, resolver=store).reveal() == FRED_KEY
    # Both handles live in the one store; the sources seam never needs a store of its own.
    assert store.list_handles() == ["anthropic:acme-prod", FRED_HANDLE]


def test_default_source_resolver_matches_the_transport_default_store(tmp_path: Path):
    """`default_source_resolver()` builds the SAME zero-arg `FileSecretBackend` the transport
    resolver builds — so both point at the identical default store (`$OPTIQUITY_SECRETS_DIR`)."""
    env = {"OPTIQUITY_SECRETS_DIR": str(tmp_path / "shared-secrets")}
    sources_backend = default_source_resolver(env=env)
    transport_backend = FileSecretBackend(env=env)  # how resolve.py builds it (zero-arg / env)
    assert sources_backend.secrets_dir == transport_backend.secrets_dir


# --- the connection-config seam: a source references a handle ---------------------------------


def test_resolve_source_key_reads_the_handle_from_connection_and_resolves(tmp_path: Path):
    """A keyed source's `connection` names its handle under `api_key_handle`; `resolve_source_key`
    reads it and resolves via the shared store — the end-to-end keyed-source pattern."""
    store = _store(tmp_path)
    store.store(SecretRef.parse(FRED_HANDLE), FRED_KEY)
    connection = {"api_key_handle": FRED_HANDLE, "series": "GDP"}

    resolved = resolve_source_key(connection, resolver=store)
    assert resolved is not None
    assert resolved.reveal() == FRED_KEY


def test_source_secret_ref_extracts_the_non_secret_handle():
    ref = source_secret_ref({"api_key_handle": FRED_HANDLE})
    assert ref == SecretRef.parse(FRED_HANDLE)
    assert SOURCE_KEY_FIELD == "api_key_handle"


def test_a_keyless_source_yields_none_not_a_value():
    """The common case: a source names no handle → `None` (keyless), never a fabricated value."""
    assert source_secret_ref({"user_agent": "ua"}) is None
    assert resolve_source_key({"user_agent": "ua"}) is None


def test_a_required_but_absent_handle_is_a_loud_config_refusal():
    """A paid source that needs a key but configures none refuses LOUDLY (never a silent keyless
    fall-through), naming the field, never a value."""
    with pytest.raises(SourceKeyError) as excinfo:
        resolve_source_key({"series": "GDP"}, required=True)
    assert excinfo.value.code == "sources-key-error"
    assert SOURCE_KEY_FIELD in str(excinfo.value)


def test_a_non_string_handle_is_a_loud_config_refusal():
    with pytest.raises(SourceKeyError):
        source_secret_ref({"api_key_handle": 1234})


def test_a_malformed_handle_string_surfaces_the_typed_keystore_error():
    """A bad handle string surfaces the keystore's own typed `SecretHandleError` (a
    `KeyStoreError`), naming the handle, never a value."""
    with pytest.raises(SecretHandleError):
        source_secret_ref({"api_key_handle": "not a handle"})


def test_a_missing_stored_secret_raises_the_typed_keystore_miss(tmp_path: Path):
    """A configured handle with nothing stored raises the keystore's typed miss (naming the
    handle) — the seam does not invent a value."""
    store = _store(tmp_path)
    with pytest.raises(SecretNotFoundError):
        resolve_source_key({"api_key_handle": FRED_HANDLE}, resolver=store)


# --- no secret leakage (I5): the seam surfaces the handle, never the value --------------------


def test_the_seam_never_surfaces_the_value_in_repr_str_or_logs(tmp_path: Path, caplog):
    """Resolving through the sources seam surfaces the HANDLE only: the value never appears in the
    `ResolvedSecret` repr/str, nor in any log line the seam emits (I5)."""
    store = _store(tmp_path)
    store.store(SecretRef.parse(FRED_HANDLE), FRED_KEY)
    with caplog.at_level(logging.DEBUG):
        resolved = resolve_source_key({"api_key_handle": FRED_HANDLE}, resolver=store)
    assert resolved is not None
    assert FRED_KEY not in repr(resolved)
    assert FRED_KEY not in str(resolved)
    assert FRED_HANDLE in str(resolved)
    assert resolved.reveal() == FRED_KEY  # reachable ONLY via the explicit reveal seam
    for record in caplog.records:
        assert FRED_KEY not in record.getMessage()


def test_the_seam_reexports_the_keystore_no_leak_guarantees():
    """The seam re-exports the keystore's redacting `ResolvedSecret` (not a leaky wrapper), so the
    no-leak guarantees proven in `test_keystore.py` hold verbatim for the sources path."""
    resolved = ResolvedSecret(SecretRef.parse(FRED_HANDLE), FRED_KEY)
    assert FRED_KEY not in repr(resolved)
    assert FRED_KEY not in str(resolved)
    with pytest.raises(TypeError):  # cannot be pickled/copied out — value never leaves in the clear
        resolved.__reduce__()


# --- module boundary (the G9 MINOR): sources imports ONLY pipeline.spend.keystore --------------


def _spend_imports(py_path: Path) -> list[str]:
    """Every `pipeline.spend[.x]` module a python file IMPORTS (ast-parsed — precise, never tripped
    by a docstring/comment that merely names a module). Normalizes `from pipeline.spend import X`
    to `pipeline.spend.X` so submodule imports are seen too."""
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names if a.name.split(".")[:2] == ["pipeline", "spend"]]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            parts = module.split(".")
            if parts[:2] != ["pipeline", "spend"]:
                continue
            if module == "pipeline.spend":
                mods += [f"pipeline.spend.{a.name}" for a in node.names]
            else:
                mods.append(module)
    return mods


def _is_keystore_import(module: str) -> bool:
    return module == "pipeline.spend.keystore" or module.startswith("pipeline.spend.keystore.")


# The other spend modules a sources import must NEVER reach — the paid-selection machinery.
_FORBIDDEN_SPEND = ("resolve", "meter", "wall", "entitlement", "assignment", "construction")


def test_sources_imports_only_the_keystore_from_spend():
    """`pipeline/sources/**` may import ONLY `pipeline.spend.keystore` — any other `pipeline.spend`
    module (resolve/meter/wall/entitlement/assignment/construction) is FORBIDDEN. Sources resolves a
    secret; it never selects a transport, admits, or meters (that is the transport machinery)."""
    offenders: dict[str, list[str]] = {}
    keystore_importers: list[str] = []
    for py in sorted((REPO_ROOT / "pipeline" / "sources").rglob("*.py")):
        spend = _spend_imports(py)
        if not spend:
            continue
        bad = [m for m in spend if not _is_keystore_import(m)]
        if bad:
            offenders[str(py.relative_to(REPO_ROOT))] = bad
        if any(_is_keystore_import(m) for m in spend):
            keystore_importers.append(str(py.relative_to(REPO_ROOT)))
    assert offenders == {}, (
        f"pipeline/sources/** may import ONLY pipeline.spend.keystore; forbidden: {offenders}"
    )
    # The seam exists and is exercised: at least the G9 sources keystore module imports it.
    assert "pipeline/sources/keystore.py" in keystore_importers


def test_no_sources_module_imports_a_forbidden_spend_submodule():
    """Belt-and-braces on the exact forbidden set the MINOR names."""
    for py in sorted((REPO_ROOT / "pipeline" / "sources").rglob("*.py")):
        for module in _spend_imports(py):
            tail = module.split(".")
            leaf = tail[2] if len(tail) >= 3 else ""
            assert leaf not in _FORBIDDEN_SPEND, (
                f"{py.name} imports forbidden pipeline.spend.{leaf} — sources may import only "
                "pipeline.spend.keystore"
            )


@pytest.mark.parametrize("module_file", ["compose.py", "review.py", "reconcile.py"])
def test_generation_modules_import_no_spend_at_all(module_file: str):
    """compose/review/reconcile import NOTHING from `pipeline.spend` — the generation hot path stays
    entirely off the paid/keystore package (the plan's second boundary clause)."""
    spend = _spend_imports(REPO_ROOT / "pipeline" / module_file)
    assert spend == [], f"pipeline/{module_file} must import no pipeline.spend, found: {spend}"


def test_the_seam_imports_no_other_pipeline_machinery():
    """The sources keystore seam itself pulls in ONLY `pipeline.spend.keystore` from the whole
    `pipeline` package — no transport/driver/session/paid-selection coupling rides in with it."""
    tree = ast.parse(Path(sources_keystore.__file__).read_text(encoding="utf-8"))
    pipeline_mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            pipeline_mods += [a.name for a in node.names if a.name.split(".")[0] == "pipeline"]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] == "pipeline":
                pipeline_mods.append(module)
    assert pipeline_mods == ["pipeline.spend.keystore"], (
        f"the sources keystore seam must import only pipeline.spend.keystore, got: {pipeline_mods}"
    )


def test_the_seam_pulls_in_no_forbidden_error_types_by_reexport():
    """The re-exported error types are the keystore's own (a `KeyStoreError` hierarchy), so the
    seam's typed refusals are the SAME ones proven not to leak in test_keystore.py."""
    assert issubclass(SecretNotFoundError, KeyStoreError)
    assert issubclass(SecretPermissionsError, KeyStoreError)
    assert issubclass(SecretHandleError, KeyStoreError)
    assert not issubclass(SourceKeyError, KeyStoreError)  # a distinct sources-config error family
