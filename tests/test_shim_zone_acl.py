"""Z4 (Blocker 2): the HTTP-shim served-workspace allow-list is keyed by `user/zone/workspace`.

The pre-Z4 allow-list keyed `user/workspace`, so `dave/work/acme` and `dave/personal/acme` collided
on ONE policy key — a served `work/acme` would silently also serve `personal/acme` (a zone-isolation
hole). Z4 makes the membership a `(user, zone, workspace)` TRIPLE, with two wildcards:

- `dave/work/acme` — serves EXACTLY that zone+workspace (and 403s the sibling `dave/personal/acme`);
- `dave/work/*` — serves ANY workspace under the `work` zone;
- `dave/*` — serves ANY zone (and any workspace) under `dave`.

Applied at BOTH doors (`/invoke` and `/poll`, N-6). A served request clears the allow-list and
reaches dispatch (invoke → 200; poll → past the 403 into key validation); a non-member is refused
403 `workspace-not-served` BEFORE any store access. The `zone` rides the request body (defaulting to
`default`); an escaping user/zone/workspace is still refused by the delegated §23 gate inside
`invoke()`. All fixtures are generic; no instance content.
"""

from __future__ import annotations

import pytest

# Reuse the shim harness (ephemeral loopback server + the POST helper) from the shim test module —
# under pytest's prepend import mode a sibling test module imports by bare name.
from test_http_shim import TEST_SECRET, post, running_server  # noqa: E402

from pipeline.api import http_shim

INVOKE = http_shim.INVOKE_PATH
POLL = http_shim.POLL_PATH


def _ok(verb, workspace, user, params, token, *, root, zone="default"):  # noqa: ANN001, ANN202
    """A served-request invoke seam: a valid ok envelope → 200 (proves the request cleared)."""
    return {
        "envelope": {"ok": True, "verb": verb, "workspace": workspace, "user": user},
        "results": [],
    }


def _invoke(host, port, *, user, zone, workspace):  # noqa: ANN001, ANN202
    return post(
        host,
        port,
        {"verb": "list", "workspace": workspace, "user": user, "zone": zone, "params": {}},
        path=INVOKE,
        auth=TEST_SECRET,
    )


def _poll(host, port, *, user, zone, workspace):  # noqa: ANN001, ANN202
    return post(
        host,
        port,
        {
            "workspace": workspace,
            "user": user,
            "zone": zone,
            "key": "r-0000000000000000",
            "target_ids": ["a-0000000000000000"],
        },
        path=POLL,
        auth=TEST_SECRET,
    )


def _served(status: int, body: dict) -> bool:
    """A request is SERVED iff it cleared the allow-list — never a 403 `workspace-not-served`."""
    return not (status == 403 and body.get("error") == "workspace-not-served")


def _denied(status: int, body: dict) -> bool:
    return status == 403 and body.get("error") == "workspace-not-served"


class TestExactTripleAllowList:
    def test_exact_triple_serves_only_that_zone_and_workspace(self, tmp_path):
        # `dave/work/acme` serves `dave/work/acme` at BOTH doors, and 403s the SIBLING zone.
        with running_server(
            invoke_fn=_ok, root=str(tmp_path), allowed_workspaces=frozenset({"dave/work/acme"})
        ) as (host, port):
            s_inv, b_inv = _invoke(host, port, user="dave", zone="work", workspace="acme")
            assert (s_inv, b_inv["envelope"]["ok"]) == (200, True)  # served → dispatch → 200

            s_poll, b_poll = _poll(host, port, user="dave", zone="work", workspace="acme")
            assert _served(s_poll, b_poll)  # served → cleared the allow-list (past the 403)

            # the SIBLING zone `personal` is NOT listed → 403 at both doors (the isolation fix).
            s_deny_i, b_deny_i = _invoke(host, port, user="dave", zone="personal", workspace="acme")
            assert _denied(s_deny_i, b_deny_i)
            s_deny_p, b_deny_p = _poll(host, port, user="dave", zone="personal", workspace="acme")
            assert _denied(s_deny_p, b_deny_p)
            assert "user/zone/workspace" in b_deny_i["detail"]  # the 403 names the triple


class TestZoneWildcard:
    def test_zone_wildcard_serves_any_workspace_in_that_zone(self, tmp_path):
        # `dave/work/*` serves EVERY workspace under the `work` zone, and 403s another zone.
        with running_server(
            invoke_fn=_ok, root=str(tmp_path), allowed_workspaces=frozenset({"dave/work/*"})
        ) as (host, port):
            for ws in ("acme", "beta", "gamma"):
                s, b = _invoke(host, port, user="dave", zone="work", workspace=ws)
                assert (s, b["envelope"]["ok"]) == (200, True)
            # a DIFFERENT zone is still refused (the wildcard is scoped to `work`).
            s_deny, b_deny = _invoke(host, port, user="dave", zone="personal", workspace="acme")
            assert _denied(s_deny, b_deny)


class TestUserWildcard:
    def test_user_wildcard_serves_any_zone_and_workspace(self, tmp_path):
        # `dave/*` serves any zone AND any workspace under `dave` (but not another user).
        with running_server(
            invoke_fn=_ok, root=str(tmp_path), allowed_workspaces=frozenset({"dave/*"})
        ) as (host, port):
            for zone, ws in (("work", "acme"), ("personal", "acme"), ("staging", "beta")):
                s, b = _invoke(host, port, user="dave", zone=zone, workspace=ws)
                assert (s, b["envelope"]["ok"]) == (200, True)
            # another USER is refused — the wildcard is scoped to `dave`.
            s_deny, b_deny = _invoke(host, port, user="erin", zone="work", workspace="acme")
            assert _denied(s_deny, b_deny)


class TestUnsetServesAny:
    def test_empty_allow_list_serves_any_triple(self, tmp_path):
        # UNSET (empty) allow-list → serve any triple (the §23 resolve-and-contain gate governs).
        with running_server(invoke_fn=_ok, root=str(tmp_path)) as (host, port):
            s, b = _invoke(host, port, user="dave", zone="personal", workspace="acme")
            assert (s, b["envelope"]["ok"]) == (200, True)


@pytest.mark.parametrize("bad_zone", ["", 123, None])
def test_present_but_invalid_zone_is_a_bad_request(bad_zone, tmp_path):
    # A present-but-empty/non-string `zone` is a 400 (never silently defaulted) at the door.
    with running_server(invoke_fn=_ok, root=str(tmp_path)) as (host, port):
        status, _ = post(
            host,
            port,
            {"verb": "list", "workspace": "acme", "user": "dave", "zone": bad_zone, "params": {}},
            path=INVOKE,
            auth=TEST_SECRET,
        )
        assert status == 400
