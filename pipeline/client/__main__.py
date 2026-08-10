"""``python -m pipeline.client`` — the thin CLI over the stdlib reference :class:`Client`.

Commit 3 of the API-client build. A small ``argparse`` front over the committed
:class:`pipeline.client.Client`; it holds NO transport or poll logic of its own — every subcommand
maps 1:1 to a Client method and prints ONE JSON object on stdout.

THE VERB SURFACE IS PINNED (F-F). Exactly four subcommands — ``generate`` / ``render`` / ``list`` /
``get`` — and nothing else. There is deliberately NO generic ``invoke <verb>`` passthrough: the raw
``scripts/pipeline invoke`` door is a separate operator surface (design §21) and is not re-exposed
here.

SECRET HANDLING (F-F). The auth secret is read ONLY from the environment
(``OPTIQUITY_SHIM_SECRET``); there is **no ``--secret`` / ``--api-key`` flag**, so the secret never
appears in ``argv``, in ``--help``, or in a process listing. The shim URL comes from
``OPTIQUITY_SHIM_URL`` (or an explicit ``--url``). A failure outcome maps to a non-zero exit with a
clear stderr message that never contains the secret.

Exit codes (echoing the operator CLI, ``pipeline/__main__.py``): ``0`` ok · ``1`` a failure outcome
(a raised :class:`ClientError`, a transport failure, or a Tier-A error envelope) · ``2`` a usage /
configuration error (argparse, an invalid ``--*-json`` value, missing env, or an empty idempotency
key).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from collections.abc import Callable, Mapping
from typing import Any

from pipeline.client import Client, ClientError

# The env config keys are the client's SSOT (identical across languages); import them so the CLI
# never drifts from the library's names (an anti-drift test pins the equality too). DEFAULT_ZONE is
# the wire default the library owns (§23/Z4) — imported so `--zone` never diverges from it.
from pipeline.client.client import _ENV_SECRET, _ENV_URL, DEFAULT_ZONE

# The pinned four-verb surface (F-F): NO generic `invoke`, no operator verbs.
VERBS = ("generate", "render", "list", "get")


# ---------------------------------------------------------------------------------------------
# Small emit / run helpers.
# ---------------------------------------------------------------------------------------------
def _json_arg(raw: str) -> Any:
    """An argparse ``type=`` converter for a JSON-object flag. Invalid JSON becomes a usage error
    (argparse turns the raised ``ArgumentTypeError`` into an exit-2 message) — never a traceback."""
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not valid JSON: {exc}") from exc


def _print_json(obj: Any) -> None:
    """Emit exactly ONE JSON object on stdout — the sole success/result channel."""
    print(json.dumps(obj))


def _run_await(name: str, thunk: Callable[[], Any]) -> int:
    """Run an ergonomic ``_and_wait`` call and map its outcome: a returned :class:`Result` → print
    its body, exit 0; a raised :class:`ClientError` (JobFailed / JobTimeout / RenderBlocked /
    MalformedResponse) → a clear stderr line, exit 1; a genuine transport failure → exit 1; a
    bad-argument ``ValueError`` (e.g. an empty idempotency key) → a usage error, exit 2. No branch
    ever prints the secret."""
    try:
        result = thunk()
    except ValueError as exc:
        print(f"pipeline.client {name}: {exc}", file=sys.stderr)
        return 2
    except ClientError as exc:
        print(f"pipeline.client {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, OSError) as exc:
        print(f"pipeline.client {name}: transport error: {exc}", file=sys.stderr)
        return 1
    _print_json(result.json)
    return 0


def _run_sync(name: str, thunk: Callable[[], Any]) -> int:
    """Run a Tier-A raw call (`list`/`get`) that returns a :class:`Response`: print its body, then
    exit 0 only on a 2xx, non-``ok:false`` envelope; otherwise a clear stderr line and exit 1. A
    genuine transport failure also exits 1. The secret never reaches stdout/stderr."""
    try:
        response = thunk()
    except (urllib.error.URLError, OSError) as exc:
        print(f"pipeline.client {name}: transport error: {exc}", file=sys.stderr)
        return 1
    _print_json(response.json)
    ok = 200 <= response.status < 300 and not (
        isinstance(response.json, Mapping) and response.json.get("ok") is False
    )
    if ok:
        return 0
    print(f"pipeline.client {name}: request failed (status={response.status})", file=sys.stderr)
    return 1


# ---------------------------------------------------------------------------------------------
# The four subcommand handlers — each maps 1:1 to a Client method.
# ---------------------------------------------------------------------------------------------
def _cmd_render(client: Client, args: argparse.Namespace) -> int:
    """`render` → :meth:`Client.render_and_wait` (content-addressed; idempotency key OPTIONAL). A
    cache hit returns 200 at submit and collapses into the same Result as a 202-then-poll."""
    return _run_await(
        "render",
        lambda: client.render_and_wait(
            args.workspace,
            args.user,
            args.item,
            args.platform,
            args.language,
            args.output_type,
            presentation=args.presentation,
            force_reconcile=args.force_reconcile,
            idempotency_key=args.idempotency_key,
            callback_url=args.callback_url,
            zone=args.zone,
        ),
    )


def _cmd_generate(client: Client, args: argparse.Namespace) -> int:
    """`generate` → :meth:`Client.begin_session` (generate FORCED to ``"none"``) then
    :meth:`Client.generate_and_wait` (idempotency key REQUIRED). The two-call path is the supported
    one (the one-call ``begin-session{generate!=none}`` is a deferred 501)."""
    try:
        handle = client.begin_session(
            args.workspace,
            args.user,
            args.selection,
            overrides=args.overrides,
            pins=args.pins,
            zone=args.zone,
        )
    except (urllib.error.URLError, OSError) as exc:
        print(f"pipeline.client generate: transport error: {exc}", file=sys.stderr)
        return 1
    if handle.token is None:
        _print_json(handle.response.json)
        print(
            "pipeline.client generate: begin-session returned no session token "
            f"(status={handle.response.status})",
            file=sys.stderr,
        )
        return 1
    return _run_await(
        "generate",
        lambda: client.generate_and_wait(
            args.workspace,
            args.user,
            handle.token,
            args.idempotency_key,
            batch_size=args.batch_size,
            only=args.only,
            callback_url=args.callback_url,
            zone=args.zone,
        ),
    )


def _cmd_list(client: Client, args: argparse.Namespace) -> int:
    """`list` → :meth:`Client.list` (a Tier-A discovery verb): enumerate registry values of a
    type."""
    return _run_sync(
        "list",
        lambda: client.list(args.type, args.workspace, args.user, args.filters, zone=args.zone),
    )


def _cmd_get(client: Client, args: argparse.Namespace) -> int:
    """`get` → :meth:`Client.get` (a Tier-A discovery verb): fetch one registry value by id."""
    return _run_sync(
        "get", lambda: client.get(args.type, args.id, args.workspace, args.user, zone=args.zone)
    )


# ---------------------------------------------------------------------------------------------
# The parser (factored out so a test can introspect the pinned verb surface + the no-secret rule).
# ---------------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the pinned four-verb client CLI. No ``--secret`` flag exists on
    any subparser — the secret is env-only (``OPTIQUITY_SHIM_SECRET``)."""
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.client",
        description=(
            "The stdlib reference client CLI (docs/guide/clients.md). Four subcommands — "
            "generate / render / list / get — each mapping 1:1 to a Client method and printing one "
            "JSON object on stdout. Config is env-only: OPTIQUITY_SHIM_URL (or --url) plus "
            "OPTIQUITY_SHIM_SECRET. The secret is read ONLY from the environment — there is no "
            "--secret flag, so it never appears in argv or --help."
        ),
    )
    # A shared parent for the env/url options — the secret is deliberately NOT an option.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help=(
            f"shim base URL (default: ${_ENV_URL}); the secret is ALWAYS read from "
            f"${_ENV_SECRET} (env-only, never a flag)"
        ),
    )
    common.add_argument(
        "--zone",
        default=DEFAULT_ZONE,
        metavar="ZONE",
        help=(
            f"the §23/Z4 isolation zone between user and workspace (default: {DEFAULT_ZONE!r}); it "
            "rides every request body next to --user/--workspace, 1:1 with the wire"
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    gen = sub.add_parser(
        "generate",
        parents=[common],
        help="begin a session then drive continue-session{generate-next} to a terminal outcome",
        description=(
            'Two-call generate: begin_session (generate is FORCED to "none") mints the session '
            "token, then generate_and_wait drives the served continue-session{generate-next} "
            "door to a terminal outcome. --idempotency-key is REQUIRED (a 409 re-drive reuses "
            "it, so a retry is exactly-once)."
        ),
    )
    gen.add_argument("--workspace", required=True, help="the invoked workspace")
    gen.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix)"
    )
    gen.add_argument(
        "--selection",
        required=True,
        type=_json_arg,
        metavar="JSON",
        help="the selection grammar as a JSON object (begin_session selection)",
    )
    gen.add_argument("--idempotency-key", required=True, help="REQUIRED idempotency key")
    gen.add_argument(
        "--overrides", type=_json_arg, default=None, metavar="JSON", help="run overrides (JSON)"
    )
    gen.add_argument(
        "--pins", type=_json_arg, default=None, metavar="JSON", help="commit pins (JSON)"
    )
    gen.add_argument("--batch-size", type=int, default=None, help="generate-next batch size")
    gen.add_argument(
        "--only", type=_json_arg, default=None, metavar="JSON", help="restrict to a subset (JSON)"
    )
    gen.add_argument("--callback-url", default=None, help="optional wakeup webhook URL")
    gen.set_defaults(handler=_cmd_generate)

    ren = sub.add_parser(
        "render",
        parents=[common],
        help="render an item and resolve at the terminal outcome",
        description=(
            "Map to render_and_wait: render is content-addressed + token-free (a cache hit returns "
            "200 at submit and collapses into the same Result as 202-then-poll). --idempotency-key "
            "is OPTIONAL."
        ),
    )
    ren.add_argument("item", help="the artifact-id to render")
    ren.add_argument("--workspace", required=True, help="the invoked workspace")
    ren.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix)"
    )
    ren.add_argument("--platform", required=True, help="the target platform slug")
    ren.add_argument("--language", required=True, help="the target language slug")
    ren.add_argument("--output-type", required=True, help="the render output-type slug")
    ren.add_argument("--presentation", default=None, help="the presentation slug (optional)")
    ren.add_argument(
        "--force-reconcile", action="store_true", help="force a fresh reconcile revision fit"
    )
    ren.add_argument("--idempotency-key", default=None, help="optional idempotency key")
    ren.add_argument("--callback-url", default=None, help="optional wakeup webhook URL")
    ren.set_defaults(handler=_cmd_render)

    lst = sub.add_parser(
        "list",
        parents=[common],
        help="enumerate registry values of a type (Tier-A discovery)",
        description="Map to Client.list: enumerate the registry values of TYPE in a workspace.",
    )
    lst.add_argument("type", help="the registry type to enumerate (e.g. persona, platform)")
    lst.add_argument("--workspace", required=True, help="the invoked workspace")
    lst.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix)"
    )
    lst.add_argument(
        "--filters", type=_json_arg, default=None, metavar="JSON", help="optional filters (JSON)"
    )
    lst.set_defaults(handler=_cmd_list)

    get = sub.add_parser(
        "get",
        parents=[common],
        help="fetch one registry value by id (Tier-A discovery)",
        description="Map to Client.get: fetch the registry value of TYPE with ID in a workspace.",
    )
    get.add_argument("type", help="the registry type")
    get.add_argument("id", help="the registry value id")
    get.add_argument("--workspace", required=True, help="the invoked workspace")
    get.add_argument(
        "--user", required=True, help="the owning user (§23 isolation prefix)"
    )
    get.set_defaults(handler=_cmd_get)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse args, resolve the env-only config, construct the :class:`Client`, and dispatch. Returns
    a process exit code. ``--help`` and argparse usage errors raise ``SystemExit`` (0 / 2) directly
    from ``parse_args`` (standard argparse behavior)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    url = args.url or os.environ.get(_ENV_URL)
    if not url:
        print(f"pipeline.client: no shim URL — pass --url or set ${_ENV_URL}", file=sys.stderr)
        return 2
    secret = os.environ.get(_ENV_SECRET)  # env ONLY — never from argv (F-F)
    if not secret:
        print(
            f"pipeline.client: no secret — set ${_ENV_SECRET} (there is no --secret flag)",
            file=sys.stderr,
        )
        return 2

    client = Client(url, secret)
    return args.handler(client, args)


if __name__ == "__main__":
    raise SystemExit(main())
