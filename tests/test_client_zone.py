"""Z8: the client library carries the §23/Z4 `zone`, and the resume/spawn paths FAIL SAFE.

Four slices, all CI-safe (no live network / subscription):

* **Client zone threading + echo** — the stdlib :class:`Client` sends `zone` in the request body
  next to `user`/`workspace` (default ``"default"``), on every request path (invoke / poll / the
  ergonomic submit→poll traversal / begin-session), and SURFACES the door's ECHOED zone
  (:func:`echoed_zone` + :attr:`SessionHandle.zone`). Driven by a fake urllib opener — no socket.
* **Spawn-JSON back-compat (MINOR 7)** — a PRE-zone spawned-job record (a `JobSpec` JSON with NO
  `zone`) re-read post-cutover raises a LOUD ``KeyError`` (the Z4 mandatory-field contract →
  the H2 re-drive path), never a silent default.
* **Token cross-zone-resume (MINOR 7)** — a session begun in zone A, then resumed with ``--zone B``,
  is refused ``isolation-violation`` (the session's nested id does not resolve in the B store) —
  never a silent cross-zone resume. The token is a workspace-bound cursor (zone-blind), so the
  fail-safe is STRUCTURAL: it comes from the store leaf, not the token.
* **Example parity (MINOR 6)** — the committed `examples/cpp` + `examples/n8n` request payloads
  carry a valid `zone` field, so the examples cannot silently drift from the wire contract.

All fixtures are obviously generic (`acme`/`dave`, literal ids); no instance/client content.
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

import pytest

import pipeline.client.client as client_mod
from pipeline.client import DEFAULT_ZONE, Client, SessionHandle, echoed_zone, parse_callback

#: The repo root (tests/ is its direct child) — anchors the example-parity reads regardless of cwd.
_REPO = Path(__file__).resolve().parents[1]

#: A generic 64-hex plan hash (mirrors `tests/test_api_invoke.py`) for minting a session token.
_PLAN_HASH = "d3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33fd3adb33f0"

#: A generic artifact id that resolves by output existence (§22.7) — the session's produced id.
_ART = "a-9f3c07d21b44e8aa"


# =============================================================================================
# Fake urllib transport (no socket): capture the outgoing body, script the reply.
# =============================================================================================
class _FakeResponse:
    """A minimal stand-in for an ``http.client.HTTPResponse`` (`.status`/`.headers`/`.read`)."""

    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self._body = body

    def read(self) -> bytes:
        return self._body

    def close(self) -> None:  # pragma: no cover — trivial
        pass


class _RecordingOpener:
    """Capture every outgoing ``Request``; return a single response or a list popped in order."""

    def __init__(self, script) -> None:  # noqa: ANN001
        self._script = script
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout=None):  # noqa: ANN001, ANN201
        self.requests.append(request)
        return self._script.pop(0) if isinstance(self._script, list) else self._script


def _sent(opener: _RecordingOpener, index: int = 0) -> dict:
    """The decoded JSON body of the ``index``-th captured outgoing request."""
    return json.loads(opener.requests[index].data)


# =============================================================================================
# Slice 1 — the client sends `zone` and surfaces the ECHOED zone (every request path).
# =============================================================================================
class TestClientZoneThreading:
    def test_invoke_sends_zone_next_to_user_and_workspace_and_surfaces_the_echo(self) -> None:
        # `client.invoke(..., zone="work")` puts `zone: "work"` in the payload that reaches the door
        # (next to user/workspace, 1:1 with the wire), and the ECHOED zone comes back in the result.
        echoed = json.dumps(
            {
                "envelope": {
                    "ok": True,
                    "verb": "list",
                    "workspace": "acme",
                    "user": "dave",
                    "zone": "work",
                },
                "results": [],
            }
        ).encode()
        opener = _RecordingOpener(_FakeResponse(200, echoed))
        resp = Client("http://shim.test", "sek", opener=opener).invoke(
            "list", "acme", "dave", {}, zone="work"
        )
        body = _sent(opener)
        assert body["zone"] == "work"
        assert body["user"] == "dave"
        assert body["workspace"] == "acme"
        assert echoed_zone(resp.json) == "work"

    def test_zone_defaults_to_the_wire_default_when_omitted(self) -> None:
        opener = _RecordingOpener(_FakeResponse())
        Client("http://shim.test", "sek", opener=opener).invoke("list", "acme", "dave", {})
        assert _sent(opener)["zone"] == DEFAULT_ZONE == "default"

    def test_poll_sends_zone(self) -> None:
        opener = _RecordingOpener(_FakeResponse())
        Client("http://shim.test", "sek", opener=opener).poll(
            "acme", "dave", "r-1", ["t-1"], zone="work"
        )
        assert _sent(opener)["zone"] == "work"

    def test_begin_session_threads_zone_and_echoes_it_on_the_handle(self) -> None:
        opener = _RecordingOpener(_FakeResponse(200, b'{"token": {"cursor": 1}}'))
        handle = Client("http://shim.test", "sek", opener=opener).begin_session(
            "acme", "dave", {"select": 1}, zone="work"
        )
        assert _sent(opener)["zone"] == "work"
        assert isinstance(handle, SessionHandle)
        # §23/Z4: the handle ECHOES the begin zone so the paired resume carries the SAME zone.
        assert handle.zone == "work"

    def test_render_and_wait_carries_zone_on_submit_and_poll(self, monkeypatch) -> None:
        # The whole ergonomic traversal (submit → 202 → poll → done) stays in one zone: BOTH the
        # /invoke submit and the /poll carry `zone`, so a poll never resolves in another zone.
        monkeypatch.setattr(client_mod.time, "sleep", lambda *_: None)
        accepted = json.dumps(
            {"status": "accepted", "job": {"key": "r-1", "target_ids": ["t-1"]}}
        ).encode()
        done = json.dumps(
            {"status": "done", "job": {"key": "r-1", "target_ids": ["t-1"]}, "results": []}
        ).encode()
        opener = _RecordingOpener([_FakeResponse(202, accepted), _FakeResponse(200, done)])
        client = Client("http://shim.test", "sek", opener=opener, poll_interval=0.01)
        client.render_and_wait("acme", "dave", "item", "linkedin", "en", "post", zone="work")
        assert len(opener.requests) == 2
        assert opener.requests[0].full_url.endswith("/invoke")
        assert opener.requests[1].full_url.endswith("/poll")
        assert _sent(opener, 0)["zone"] == "work"  # the submit
        assert _sent(opener, 1)["zone"] == "work"  # the poll

    def test_echoed_zone_reads_none_when_the_body_carries_no_zone(self) -> None:
        # NO-INVENT: a body with no echoed zone reads None (never a fabricated "default"), so a
        # client can tell "the door echoed no zone" from "the door echoed default".
        assert echoed_zone({"envelope": {"ok": True, "verb": "list"}}) is None
        assert echoed_zone({"status": "done", "results": []}) is None
        assert echoed_zone(None) is None
        assert echoed_zone("not a mapping") is None
        # A flat top-level echo (a future 202/200 shape) is surfaced too.
        assert echoed_zone({"status": "accepted", "zone": "work"}) == "work"

    def test_parse_callback_reads_the_wakeup_zone(self) -> None:
        # The callback delivery names `job.zone`; parse_callback surfaces it on CallbackEvent.zone.
        event = parse_callback(
            {
                "event": "job.done",
                "job": {"key": "r-1", "workspace": "acme", "zone": "work", "target_ids": ["t-1"]},
            }
        )
        assert event.zone == "work"
        # A PRE-zone wakeup (no `job.zone`) → None (so fetch_after_callback can back-compat).
        legacy = parse_callback(
            {"event": "job.done", "job": {"key": "r-1", "workspace": "acme", "target_ids": ["t-1"]}}
        )
        assert legacy.zone is None

    def test_fetch_after_callback_polls_in_the_wakeup_zone_not_the_default(self) -> None:
        # The canonical client fetches in the SAME zone the job ran in: the /poll carries the
        # wakeup's `job.zone` ("work"), NEVER a silent "default".
        event = parse_callback(
            {
                "event": "job.done",
                "job": {"key": "r-1", "workspace": "acme", "zone": "work", "target_ids": ["t-1"]},
            }
        )
        done = json.dumps(
            {"status": "done", "job": {"key": "r-1", "target_ids": ["t-1"]}, "results": []}
        ).encode()
        opener = _RecordingOpener(_FakeResponse(200, done))
        Client("http://shim.test", "sek", opener=opener).fetch_after_callback(event, "dave")
        assert _sent(opener)["zone"] == "work"

    def test_fetch_after_callback_defaults_only_when_the_wakeup_named_no_zone(self) -> None:
        # Back-compat: a pre-zone wakeup (event.zone is None) falls back to the default; an explicit
        # zone arg still overrides everything.
        legacy = parse_callback(
            {"event": "job.done", "job": {"key": "r-1", "workspace": "acme", "target_ids": ["t-1"]}}
        )
        done = json.dumps(
            {"status": "done", "job": {"key": "r-1", "target_ids": ["t-1"]}, "results": []}
        ).encode()
        opener = _RecordingOpener([_FakeResponse(200, done), _FakeResponse(200, done)])
        client = Client("http://shim.test", "sek", opener=opener)
        client.fetch_after_callback(legacy, "dave")
        assert _sent(opener, 0)["zone"] == DEFAULT_ZONE  # no wakeup zone → the default
        client.fetch_after_callback(legacy, "dave", zone="work")
        assert _sent(opener, 1)["zone"] == "work"  # an explicit arg overrides


# =============================================================================================
# Slice 2 — spawn-JSON back-compat (MINOR 7): a pre-zone record fails LOUD, never a silent default.
# =============================================================================================
class TestSpawnJsonBackCompat:
    @staticmethod
    def _record(**overrides) -> dict:  # noqa: ANN003
        base = {
            "key": "r-1",
            "verb": "render",
            "workspace": "acme",
            "user": "dave",
            "params": {},
            "idempotency_key": None,
            "root": ".",
            "token": None,
            "pins": None,
            "callback_url": None,
            "target_ids": [],
            "allowed_callback_hosts": [],
        }
        base.update(overrides)
        return base

    def test_pre_zone_spawn_json_reread_raises_loud_keyerror(self) -> None:
        from pipeline.api.jobrunner import JobSpec

        # A PRE-cutover spawn record HAS `user` but LACKS `zone`. Re-reading it post-cutover must
        # fail LOUD (never build a `zones/None/…` path, never silently default) → the H2 re-drive.
        pre_zone = self._record()  # no "zone" key
        assert "zone" not in pre_zone
        with pytest.raises(KeyError) as exc:
            JobSpec.from_json(json.dumps(pre_zone))
        assert "zone" in str(exc.value)

    def test_post_cutover_spawn_json_round_trips_the_zone(self) -> None:
        from pipeline.api.jobrunner import JobSpec

        # The mirror: WITH `zone`, the record re-reads cleanly and the zone survives the round-trip.
        spec = JobSpec.from_json(json.dumps(self._record(zone="work")))
        assert spec.zone == "work"
        assert json.loads(spec.as_json())["zone"] == "work"


# =============================================================================================
# Slice 3 — token cross-zone-resume (MINOR 7): a resume in another zone fails SAFE.
# =============================================================================================
class TestCrossZoneResume:
    def test_resuming_a_session_in_another_zone_is_an_isolation_violation(self, tmp_path) -> None:
        from pipeline.api import token as token_mod
        from pipeline.api.invoke import invoke
        from pipeline.store import WorkspaceStore

        root = str(tmp_path)
        user, ws = "dave", "acme"

        # Begin a session in zone A ("work"): mint the workspace-bound cursor token, and materialize
        # the session's produced artifact under zone A's store leaf ONLY.
        store_a = WorkspaceStore.at(tmp_path, user, ws, zone="work")
        store_a.output_path(_ART).write_bytes(b"{}\n")
        token_a = token_mod.encode(token_mod.mint(ws, _PLAN_HASH, produced_ids=[_ART]))

        # Resume with --zone B ("personal"): the store leaf is zone B, where the session's nested id
        # does NOT resolve → isolation-violation. NEVER a silent cross-zone resume.
        out_b = invoke(
            "continue-session",
            ws,
            user,
            {"action": "render", "item": _ART},
            token=token_a,
            root=root,
            zone="personal",
        )
        assert out_b["envelope"]["ok"] is False
        assert out_b["envelope"]["code"] == "isolation-violation"
        assert out_b["results"][0]["code"] == "isolation-violation"

        # The mirror (proves it is ZONE-specific, not always-failing): resuming in the SAME zone A
        # resolves the id, clears the gate, and reaches dispatch — with the right zone in context.
        seen: dict[str, object] = {}

        def _stub(ctx):  # noqa: ANN001, ANN202
            seen["zone"] = ctx.zone
            return [], None

        out_a = invoke(
            "continue-session",
            ws,
            user,
            {"action": "render", "item": _ART},
            token=token_a,
            root=root,
            zone="work",
            handlers={"continue-session": _stub},
        )
        assert out_a["envelope"]["ok"] is True
        assert seen["zone"] == "work"


# =============================================================================================
# Slice 4 — example parity (MINOR 6): the committed examples carry a valid `zone` field.
# =============================================================================================
class TestExampleParity:
    def _n8n_request_bodies(self, workflow_path: Path) -> list[str]:
        """Every HTTP-Request `jsonBody` that names `workspace` (a request to the door), from a
        PARSED n8n workflow file — a json.load that also guards the file against JSON drift."""
        workflow = json.loads(workflow_path.read_text())
        return [
            node["parameters"]["jsonBody"]
            for node in workflow["nodes"]
            if isinstance(node.get("parameters"), dict)
            and isinstance(node["parameters"].get("jsonBody"), str)
            and '"workspace"' in node["parameters"]["jsonBody"]
        ]

    @pytest.mark.parametrize(
        "workflow",
        ["examples/n8n/pipeline-poll.json", "examples/n8n/pipeline-webhook.json"],
    )
    def test_every_n8n_request_body_carries_a_nonempty_zone(self, workflow: str) -> None:
        bodies = self._n8n_request_bodies(_REPO / workflow)
        assert bodies, f"{workflow}: no request bodies found"
        for body in bodies:
            match = re.search(r'"zone"\s*:\s*"([^"]+)"', body)
            assert match is not None, f"{workflow}: a request body has no `zone` field: {body!r}"
            assert match.group(1).strip(), f"{workflow}: `zone` is empty in {body!r}"

    def test_cpp_client_request_bodies_carry_the_zone_field(self) -> None:
        # The C++ example is not JSON, so parity is a source-level check: the two request-body
        # builders (`invoke`/`poll`) place a `zone` field in the outgoing body, and the header
        # declares a non-empty string default — 1:1 with the Python client + the wire contract.
        cpp = (_REPO / "examples/cpp/optiquity_client.cpp").read_text()
        assert cpp.count('{"zone", zone}') >= 2  # the invoke() body AND the poll() body
        header = (_REPO / "examples/cpp/optiquity_client.hpp").read_text()
        assert 'zone = "default"' in header  # a non-empty string default on the public surface


# =============================================================================================
# Slice 5 — the door ECHOES the resolved zone in the result envelope (end-to-end with the client).
# =============================================================================================
class TestEnvelopeZoneEcho:
    def test_tier_a_success_envelope_echoes_the_resolved_zone(self, tmp_path) -> None:
        from pipeline.api.invoke import invoke
        from pipeline.store import WorkspaceStore

        store = WorkspaceStore.at(tmp_path, "dave", "acme", zone="work")

        def _stub(ctx):  # noqa: ANN001, ANN202
            return [], None

        out = invoke(
            "list",
            "acme",
            "dave",
            {"type": "persona"},
            store=store,
            zone="work",
            handlers={"list": _stub},
        )
        assert out["envelope"]["ok"] is True
        assert out["envelope"]["zone"] == "work"
        # END-TO-END: the client's reader now resolves the echoed zone (previously always None).
        assert echoed_zone(out) == "work"

    def test_tier_a_fatal_envelope_also_echoes_the_zone(self) -> None:
        from pipeline.api.invoke import invoke

        # Even a refusal (unknown-verb, returns before the store) echoes the asked-for zone.
        out = invoke("no-such-verb", "acme", "dave", {}, root=".", zone="work")
        assert out["envelope"]["ok"] is False
        assert out["envelope"]["zone"] == "work"
        assert echoed_zone(out) == "work"

    def test_a_zoneless_directly_built_envelope_omits_zone_additive(self) -> None:
        # Additive: the sync door always resolves a zone (default "default"), but a hypothetical
        # zone-less envelope simply omits the key — echoed_zone reads None, never a fabrication.
        from pipeline.api import results

        wire = results.Envelope(ok=True, verb="list", workspace="acme", user="dave").as_dict()
        assert "zone" not in wire
        assert echoed_zone({"envelope": wire}) is None
