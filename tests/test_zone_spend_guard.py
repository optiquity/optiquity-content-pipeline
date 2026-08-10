"""S4: the SPEND-verb zone-required guard (§21.9 / §23-Z4 money-safety).

The ratified rule: once a user owns MORE THAN ONE zone, a SPEND verb MUST carry an explicit
`--zone` (refuse-and-list otherwise) — the door NEVER silently picks `default` and spends in the
wrong zone. Single-zone users (the post-migration norm) and every Tier-A verb keep the friendly
`DEFAULT_ZONE` default unconditionally (Tier-A never spends; §21.9).

These tests exercise:

- the reusable chokepoint `workspacescaffold.resolve_spend_zone` directly (0 / 1 / >1 zone, explicit
  vs. omitted `--zone`), REUSING the SAME `list_zones` scan the CRUD uses — nothing re-implemented;
- the FRIENDLY SPEND door end to end (`generate` dry-run + `--go`, `preview`, `outline drive`): a
  2-zone user WITHOUT `--zone` is REFUSED (loud, lists both zones, exit 1, begin-session NEVER
  constructed → nothing composed, nothing spent); an explicit `--zone work` / `--zone default`
  PROCEEDS (no refusal); a single-zone user PROCEEDS on the friendly `default`;
- the Tier-A verbs (`workspace list`, `zone list`) are UNAFFECTED for a 2-zone user (they never
  call the guard, so no `--zone` is ever required of them).

Every write is under a `tmp_path` `--root`; the real `users/` is never touched. An AUTOUSE
snapshot/restore of the module-global invoke dispatch registry keeps the money-safety negative
assertions (begin-session never constructed) clean of sibling registrations.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import pipeline.api.invoke as invoke_mod
import pipeline.api.session as session
from pipeline import __main__ as cli
from pipeline.layout import registry_dir
from pipeline.lint import REGISTRY_ROOTS
from pipeline.workspace_name import DEFAULT_ZONE
from pipeline.workspacescaffold import SpendZoneError, resolve_spend_zone

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_L2 = "voice: clear-explainer\nlanguage: en\noutput_type: md\n"
TOPIC = "---\nid: {tid}\nprovenance: instance\nschema_version: 1\nwhy: {why}\n---\n\nBody.\n"


# --- fixtures ---------------------------------------------------------------------------------


def build_zone_root(tmp_path: Path, *, user: str, layout: dict[str, tuple[str, ...]]) -> Path:
    """A full framework root (real registries) + a per-(zone, workspace) topic tree.

    `layout` maps a zone name → the workspaces to seed under it. An empty tuple seeds a BARE zone
    dir (`users/<user>/zones/<zone>/workspaces/` with no workspace) — which STILL counts toward the
    user's zone total (the guard counts zones, not workspaces). Registries are copied so a proceeded
    `begin-session` binds shipped entries; the repo is read-only toward the suite."""
    root = tmp_path / "root"
    root.mkdir(parents=True)
    for reg in REGISTRY_ROOTS:
        src = registry_dir(REPO_ROOT, reg)
        if src.is_dir():
            dst = registry_dir(root, reg)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst)
    (root / "instance").mkdir()
    (root / "instance" / "defaults.yaml").write_text(BASE_L2, encoding="utf-8")
    for zone, workspaces in layout.items():
        zone_ws_base = root / "users" / user / "zones" / zone / "workspaces"
        zone_ws_base.mkdir(parents=True, exist_ok=True)  # a bare zone still counts
        for ws in workspaces:
            topics_dir = zone_ws_base / ws / "topics"
            topics_dir.mkdir(parents=True)
            (topics_dir / "x-t-alpha.md").write_text(
                TOPIC.format(tid="x-t-alpha", why="First."), encoding="utf-8"
            )
    return root


def gen_argv(root: Path, *, user: str, workspace: str, extra: tuple[str, ...] = ()) -> list[str]:
    """The minimal friendly SPEND invocation resolving a one-item plan (mirrors
    `test_cli_generate.base_argv`)."""
    return [
        "--recipe", "explainer-post",
        "--topic", "x-t-alpha",
        "--platform", "github",
        "--workspace", workspace, "--user", user,
        "--root", str(root),
        *extra,
    ]


class FakeRun:
    """The injected per-item generation seam (stands in for `driver._run_artifact`): records every
    artifact-id it is asked to drive. In these tests the guard REFUSES before any drive, so
    `calls == []` PROVES nothing was composed or spent."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, *, store, item, **_kwargs):  # pragma: no cover - never reached on refusal
        self.calls.append(item.artifact_id)
        raise AssertionError("run_artifact must NOT run when the zone guard refuses")


@pytest.fixture(autouse=True)
def _clean_registry():
    """Snapshot/restore the module-global invoke dispatch registry so the AFTER-work negative
    assertions can never be polluted by a sibling test's registration."""
    snapshot = dict(invoke_mod._VERB_HANDLERS)
    try:
        yield
    finally:
        invoke_mod._VERB_HANDLERS.clear()
        invoke_mod._VERB_HANDLERS.update(snapshot)


@pytest.fixture
def _no_begin_session(monkeypatch):
    """Spy `session.begin_session_handler` and record every construction. A REFUSED spend verb must
    NEVER construct it — begin-session is where a plan resolves + a token mints, so 'never
    constructed' is the strongest 'nothing composed, nothing spent' proof."""
    constructed: list[str] = []
    real = session.begin_session_handler

    def spy(*args, **kwargs):
        constructed.append("begin")
        return real(*args, **kwargs)

    monkeypatch.setattr(session, "begin_session_handler", spy)
    return constructed


# --- the reusable chokepoint: resolve_spend_zone ----------------------------------------------


def test_resolve_zero_zones_omitted_is_default(tmp_path):
    # A brand-new user with no zones/ dir → 0 zones → the friendly DEFAULT_ZONE (never a refusal).
    root = tmp_path / "root"
    (root / "users" / "ghost").mkdir(parents=True)
    assert resolve_spend_zone(root, "ghost", None) == DEFAULT_ZONE


def test_resolve_one_zone_omitted_is_default_even_when_named_work(tmp_path):
    # Exactly ONE zone → DEFAULT_ZONE, EVEN when that single zone is named `work` (the rule is
    # literal: 0/1 zone → the friendly `default`, unchanged — the post-migration norm).
    root = build_zone_root(tmp_path, user="solo", layout={"work": ("acme",)})
    assert resolve_spend_zone(root, "solo", None) == DEFAULT_ZONE


def test_resolve_two_zones_omitted_raises_listing_both(tmp_path):
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    with pytest.raises(SpendZoneError) as excinfo:
        resolve_spend_zone(root, "dave", None)
    err = excinfo.value
    assert set(err.zones) == {"work", "personal"}  # BOTH zones carried
    assert "zone-required" in str(err)
    assert "work" in str(err) and "personal" in str(err)


def test_resolve_explicit_zone_is_honored_no_scan(tmp_path):
    # An EXPLICIT --zone is honored verbatim even for a >1-zone user — including `default` (the user
    # NAMED it, so there is no refusal, no silent pick).
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    assert resolve_spend_zone(root, "dave", "work") == "work"
    assert resolve_spend_zone(root, "dave", "default") == "default"


# --- generate (dry-run + --go): the friendly SPEND door ---------------------------------------


def test_generate_two_zones_no_zone_is_refused(tmp_path, capsys, _no_begin_session):
    # A 2-zone user running `generate` WITHOUT --zone → REFUSED loud (exit 1), the message LISTS
    # BOTH zones, and begin-session is NEVER constructed (nothing composed, nothing spent).
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    code = cli._cmd_generate(gen_argv(root, user="dave", workspace="acme"))
    err = capsys.readouterr().err
    assert code == 1
    assert "zone-required" in err
    assert "work" in err and "personal" in err
    assert "--zone" in err
    assert _no_begin_session == []  # begin-session never reached → nothing composed/spent


def test_generate_go_two_zones_no_zone_refuses_before_any_spend(tmp_path, capsys):
    # The money-safety proof on the SPEND path: `generate --go` WITHOUT --zone for a 2-zone user
    # REFUSES (exit 1) and the injected runner is NEVER called (run.calls == []) — no generate-next
    # spend happens.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    run = FakeRun()
    code = cli._cmd_generate(
        gen_argv(root, user="dave", workspace="acme", extra=("--go",)), run_artifact=run
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "zone-required" in err
    assert run.calls == []  # generate-next never drove an artifact → nothing spent


def test_generate_two_zones_explicit_work_proceeds(tmp_path, capsys):
    # The SAME 2-zone user with an EXPLICIT --zone work PROCEEDS (dry-run exit 0), resolving to work
    # (echoed in the header) — no refusal.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    code = cli._cmd_generate(
        gen_argv(root, user="dave", workspace="acme", extra=("--zone", "work"))
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "zone=work" in out  # the resolved zone is echoed
    assert "spend-scope:" in out


def test_generate_single_zone_no_zone_proceeds_on_default(tmp_path, capsys):
    # A single-zone user (only `default`, the post-migration norm) running `generate` WITHOUT --zone
    # PROCEEDS on the friendly default — the guard never fires.
    root = build_zone_root(tmp_path, user="solo", layout={"default": ("acme",)})
    code = cli._cmd_generate(gen_argv(root, user="solo", workspace="acme"))
    out = capsys.readouterr().out
    assert code == 0
    assert "zone=default" in out
    assert "spend-scope:" in out


def test_generate_multi_zone_explicit_default_proceeds(tmp_path, capsys):
    # `--zone default` explicitly on a MULTI-zone user PROCEEDS (the user NAMED default, so there is
    # no refusal even though >1 zone exists); the same user WITHOUT --zone would be refused.
    root = build_zone_root(tmp_path, user="dixie", layout={"default": ("acme",), "work": ()})
    code = cli._cmd_generate(
        gen_argv(root, user="dixie", workspace="acme", extra=("--zone", "default"))
    )
    out = capsys.readouterr().out
    assert code == 0
    assert "zone=default" in out
    assert "spend-scope:" in out


# --- preview + outline drive: the other SPEND-verb forms are guarded too ----------------------


def test_preview_two_zones_no_zone_is_refused(tmp_path, capsys, _no_begin_session):
    # `preview` is the free plan-only form of the SPEND door — it carries the SAME S4 guard.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    code = cli._cmd_preview(gen_argv(root, user="dave", workspace="acme"))
    err = capsys.readouterr().err
    assert code == 1
    assert "zone-required" in err
    assert "work" in err and "personal" in err
    assert _no_begin_session == []


def test_preview_single_zone_proceeds(tmp_path, capsys):
    root = build_zone_root(tmp_path, user="solo", layout={"default": ("acme",)})
    code = cli._cmd_preview(gen_argv(root, user="solo", workspace="acme"))
    out = capsys.readouterr().out
    assert code == 0
    assert "zone=default" in out


def test_outline_drive_two_zones_no_zone_is_refused(tmp_path, capsys, _no_begin_session):
    # `outline drive` (== `generate --outline`) is a SPEND-verb form and is guarded identically.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    outline = tmp_path / "outline.md"
    outline.write_text("# Heading\n\nA substantive paragraph of real prose.\n", encoding="utf-8")
    code = cli._cmd_outline(
        [
            "drive", str(outline),
            "--recipe", "explainer-post",
            "--topic", "x-t-alpha",
            "--workspace", "acme", "--user", "dave",
            "--root", str(root),
        ]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "zone-required" in err
    assert "work" in err and "personal" in err
    assert _no_begin_session == []


# --- Tier-A verbs are UNAFFECTED --------------------------------------------------------------


def test_tier_a_workspace_list_two_zones_unaffected(tmp_path, capsys):
    # A Tier-A verb (`workspace list`) for a 2-zone user WITHOUT --zone is UNAFFECTED (never calls
    # the guard) → exit 0, no zone-required refusal.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ("beta",)})
    code = cli.main(["workspace", "list", "--user", "dave", "--root", str(root)])
    captured = capsys.readouterr()
    assert code == 0
    assert "zone-required" not in captured.err
    assert "acme" in captured.out and "beta" in captured.out  # both zones' workspaces listed


def test_tier_a_zone_list_two_zones_unaffected(tmp_path, capsys):
    # `zone list` for a 2-zone user WITHOUT --zone is UNAFFECTED → exit 0, lists both zones.
    root = build_zone_root(tmp_path, user="dave", layout={"work": ("acme",), "personal": ()})
    code = cli.main(["zone", "list", "--user", "dave", "--root", str(root)])
    captured = capsys.readouterr()
    assert code == 0
    assert "zone-required" not in captured.err
    assert "work" in captured.out and "personal" in captured.out
