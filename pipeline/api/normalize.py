"""Door-class-aware friendly-request normalizer (CLI-UX C2, §21 friendly surface).

Design authority: `docs/design.md` §13.2 (the two-surface-one-AST override grammar),
§8 (recipe -> selection fan-out), §21 (the invocation doors); the ratified CLI-UX design
`ops-handoff/cli-ux-design/architect-reconciliation.md` ("The canonical normalizer — now
DOOR-CLASS-AWARE") and its settled plan `ops-handoff/cli-ux-plan/planner-final.md` (C2).

WHAT THIS IS. One PURE function: `normalize(friendly_inputs, door_class) -> Normalized`.
It SHAPES friendly, English-ish inputs (by-name axes, `--set`, sane defaults) into the
canonical params the EXISTING `invoke()` doors already validate — the same
`SelectionRequest` fields (`session.py:219-234`) and the same `overrides` map the JSON
`--overrides` form produces (`overrides.collect_overrides`). It owns NO engine internals
and NO identity surface: every value it emits is validated downstream at the real walls
(M1 override wall `attrtypes.validate_value`/`validate_combine_operator`; the fan-out).

DOOR-CLASS is a PARAMETER, not a second normalizer — the interactive human shell and the
paid automation door have OPPOSITE correct defaults for the three safety-relevant
omissions (recipe, workspace, idempotency key). See the resolver docs below.

IMPORT DISCIPLINE (R8). This module is a LEAF: it imports only the stdlib. It never
top-imports `session`/`invoke` (that would risk a cycle and nothing needs it to). The two
`target_folio` sentinels are mirrored from `session.py:116-117` (stable strings); a test
asserts they stay in lock-step without this module importing session.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DEFAULT_RECIPE",
    "DOOR_AUTOMATION",
    "DOOR_CLASSES",
    "DOOR_INTERACTIVE",
    "NormalizeError",
    "Normalized",
    "compile_overrides",
    "normalize",
]

# --- Door classes -----------------------------------------------------------------------

#: The local human shell: ergonomic defaults are welcome (a human catches a wrong default
#: before spend).
DOOR_INTERACTIVE = "interactive"
#: The HTTP / webhook / library-as-service door: NO silent default may mask a mis-spend or
#: a double-charge — the three safety-relevant omissions are FATAL here.
DOOR_AUTOMATION = "automation"
DOOR_CLASSES = frozenset({DOOR_INTERACTIVE, DOOR_AUTOMATION})

#: The interactive default recipe. `recipes/explainer-post.md` is the self-declared
#: framework default (design §10; `recipes/explainer-post.md` body). A test asserts the
#: entry file exists so this default always resolves to a real, shipped recipe.
DEFAULT_RECIPE = "explainer-post"

#: `target_folio` sentinels — MIRRORED from `session.py:116-117` (kept a leaf module, R8).
#: `test_normalize.py::test_target_folio_sentinels_match_session` pins them in lock-step.
TARGET_FOLIO_NONE = "none"
TARGET_FOLIO_AUTO = "auto"

#: The nine by-name axes → the `SelectionRequest` list fields (`session.py:219-234`).
#: Multi-select = a REPEATED flag → a list (NOT a comma-split). `goals` STACK into ONE
#: goal-set (below); every other axis fans out into several artifacts.
_AXIS_KEYS: tuple[str, ...] = (
    "topics",
    "personas",
    "formats",
    "voices",
    "platforms",
    "languages",
    "output_types",
    "presentations",
)

_INT_RE = re.compile(r"^-?\d+$")
#: The bounded explicit-cast escape for `--set` (the ambiguous "string that looks numeric"
#: case): `<cast>:<value>`, e.g. `str:2` → the string "2".
_CASTS: tuple[str, ...] = ("str", "int", "float", "bool")

ScalarValue = str | int | float | bool | None


class NormalizeError(ValueError):
    """A LOUD, typed normalizer refusal (a fatal automation omission, or a malformed
    `--set`). `field` names the offending input (`recipe`/`workspace`/`user`/`set`/
    `door_class`) so a door can map it to its exit/HTTP code. Raised BEFORE the engine — an
    omitted recipe/workspace/user on the paid door is an error, never a silent spend."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Normalized:
    """The shaped, canonical invocation the door hands to `invoke()`.

    - `workspace` — the resolved workspace (the separate `invoke()` positional; may be
      `None` only for an interactive READ verb with no sole/env workspace).
    - `user` — the resolved owning user (§23 isolation prefix; the separate `invoke()`
      positional parallel to `workspace`). MANDATORY whenever `workspace` is non-None — a
      workspace with no user is refused (never a `users/None/…` path); `None` only when
      `workspace` is `None` (an interactive read with nothing to invoke against).
    - `params` — the canonical `invoke()` params dict (exactly what `ctx.params` carries
      for begin-session): `recipe`, the by-name axis lists, `overrides`, `target_folio`,
      `purpose`, `idempotency_key`, `explain`. Empty axes/maps are OMITTED (zero-churn).
    - `generated_key` — the auto-generated interactive idempotency key, surfaced so the
      caller PRINTS it; `None` when the key was explicit, absent, or on the automation door.
    - `notices` — advisory lines the caller prints verbatim (the auto-key line; the
      `target_folio=auto` duplicate-empty-folio warning). Never blocks.
    """

    workspace: str | None
    user: str | None
    params: dict[str, Any]
    generated_key: str | None = None
    notices: tuple[str, ...] = field(default_factory=tuple)


# --- `--set` grammar → the `overrides` map (§13.2) --------------------------------------


def _apply_cast(cast: str, text: str) -> ScalarValue:
    if cast == "str":
        return text
    if cast == "int":
        try:
            return int(text)
        except ValueError as exc:
            raise NormalizeError(
                f"invalid-set: cast `int:` could not parse {text!r} as an integer", field="set"
            ) from exc
    if cast == "float":
        try:
            return float(text)
        except ValueError as exc:
            raise NormalizeError(
                f"invalid-set: cast `float:` could not parse {text!r} as a float", field="set"
            ) from exc
    # bool
    if text == "true":
        return True
    if text == "false":
        return False
    raise NormalizeError(
        f"invalid-set: cast `bool:` expects true/false, got {text!r}", field="set"
    )


def _infer_scalar(text: str) -> ScalarValue:
    """Infer the typed scalar for one `--set` operand (§13.2 operands ride a native
    literal): `2`→int, `true`/`false`→bool, `null`→None, else the string verbatim. An
    explicit `<cast>:<value>` escape (`str:`/`int:`/`float:`/`bool:`) forces the type for
    the ambiguous "string that looks numeric" case. The normalizer TYPES but never
    VALIDATES — a wrong type is refused downstream at `attrtypes.validate_value`."""
    head, sep, rest = text.partition(":")
    if sep and head in _CASTS:
        return _apply_cast(head, rest)
    if text == "true":
        return True
    if text == "false":
        return False
    if text == "null":
        return None
    if _INT_RE.match(text):
        return int(text)
    return text


def _split_set(raw: str) -> tuple[str, str, str]:
    """Split one `--set` string into `(path, op, value)`. `path=value` → op `replace`;
    `path+=value` → op `union` (the `+` suffix = §13.2's `tags+: [c]` union sugar)."""
    eq = raw.find("=")
    if eq <= 0:
        raise NormalizeError(
            "invalid-set: expected `<dim>.<attr>=<value>` or `<dim>.<attr>+=<value>`, "
            f"got {raw!r}",
            field="set",
        )
    if raw[eq - 1] == "+":
        return raw[: eq - 1], "union", raw[eq + 1 :]
    return raw[:eq], "replace", raw[eq + 1 :]


def compile_overrides(set_entries: Sequence[str]) -> dict[str, Any]:
    """Compile `--set` strings into the `overrides` mapping `collect_overrides` accepts
    (the frontmatter surface: `{"voice.formality": 2}`, `{"format.tags+": ["x"]}`).

    `path=value` → `{path: typed(value)}` (replace). `path+=value` → `{path+: [typed…]}`
    (union; the operand is a LIST — a bare `+=x` wraps to `["x"]`, `+=a,b` comma-splits to
    `["a","b"]`). A path bound more than once (in any op mix) is refused LOUD — never a
    silent last-wins (§3.1). Values only: this never invents an entry (the M1 wall holds).
    """
    overrides: dict[str, Any] = {}
    seen: set[str] = set()
    for raw in set_entries:
        if not isinstance(raw, str):
            raise NormalizeError(
                f"invalid-set: each --set is a string, got {type(raw).__name__}", field="set"
            )
        path, op, value = _split_set(raw)
        if not path:
            raise NormalizeError(f"invalid-set: empty path in {raw!r}", field="set")
        if path in seen:
            raise NormalizeError(
                f"invalid-set: {path!r} is set more than once — ambiguous, refused "
                "(never last-wins, §3.1)",
                field="set",
            )
        seen.add(path)
        if op == "union":
            overrides[f"{path}+"] = [_infer_scalar(part) for part in value.split(",")]
        else:
            overrides[path] = _infer_scalar(value)
    return overrides


# --- Door-class default resolution ------------------------------------------------------


def _resolve_recipe(friendly: Mapping[str, Any], door_class: str) -> str:
    recipe = friendly.get("recipe")
    if recipe:
        return str(recipe)
    if door_class == DOOR_AUTOMATION:
        raise NormalizeError(
            "missing-recipe: the automation door must pass an explicit recipe — an omitted "
            "recipe on the paid door is an error, never a silent spend",
            field="recipe",
        )
    return DEFAULT_RECIPE


def _resolve_workspace(friendly: Mapping[str, Any], door_class: str, *, spend: bool) -> str | None:
    explicit = friendly.get("workspace")
    if explicit:
        return str(explicit)
    if door_class == DOOR_AUTOMATION:
        raise NormalizeError(
            "missing-workspace: the automation door must pass an explicit workspace — never "
            "a silent env/config default (a stale default would spend on the wrong client)",
            field="workspace",
        )
    # interactive
    available = [str(w) for w in (friendly.get("available_workspaces") or ())]
    if spend:
        # A spend verb NEVER takes a silent env/config default: sole-workspace, else require
        # an explicit `--workspace`.
        if len(available) == 1:
            return available[0]
        raise NormalizeError(
            "missing-workspace: pass an explicit --workspace on a spend verb — an "
            "env/config default is read-verb-only (there is no sole workspace to infer)",
            field="workspace",
        )
    # a read verb MAY take the env/config default, else the sole workspace, else none
    env_ws = friendly.get("env_workspace")
    if env_ws:
        return str(env_ws)
    if len(available) == 1:
        return available[0]
    return None


def _resolve_user(friendly: Mapping[str, Any], door_class: str) -> str | None:
    """The resolved owning user (§23) — parallel to `_resolve_workspace`, but NEVER inferred from
    env/sole (a user is the isolation prefix; a wrong silent default would spend on another owner's
    tree). An explicit `user` passes both doors; the automation door REFUSES an omission
    (`missing-user`); interactive returns `None` when absent (the `normalize` pairing check then
    refuses a workspace-without-user, so a resolved workspace always carries its user)."""
    explicit = friendly.get("user")
    if explicit:
        return str(explicit)
    if door_class == DOOR_AUTOMATION:
        raise NormalizeError(
            "missing-user: the automation door must pass an explicit user — never a silent "
            "default (a stale default would spend under the wrong owner; §23)",
            field="user",
        )
    return None


def _resolve_idempotency_key(
    friendly: Mapping[str, Any],
    door_class: str,
    *,
    spend: bool,
    key_factory: Callable[[], str] | None,
) -> tuple[str | None, str | None]:
    """Return `(key, generated)`. An explicit key passes through both doors. On a paid
    verb with the key OMITTED: interactive MAY auto-generate AND surface it for printing
    (`generated` set); automation NEVER auto-fills — the key stays absent so the shim's
    missing-key→400 anti-double-charge path fires (`known-issues.md:198-199`). A read verb
    needs no key. (Automation never auto-keys, so `target_folio=auto` can never mint a
    duplicate empty folio there — the fold of the auto-key/auto-folio hazard.)"""
    explicit = friendly.get("idempotency_key")
    if explicit:
        return str(explicit), None
    if not spend or door_class == DOOR_AUTOMATION:
        return None, None
    key = (key_factory or _new_key)()
    return key, key


def _new_key() -> str:
    return uuid.uuid4().hex


def _as_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, Sequence):
        return [str(v) for v in raw]
    return [str(raw)]


# --- The one public entry point ---------------------------------------------------------


def normalize(
    friendly_inputs: Mapping[str, Any],
    door_class: str,
    *,
    key_factory: Callable[[], str] | None = None,
) -> Normalized:
    """Shape friendly inputs into canonical `invoke()` params under a door-class policy.

    `friendly_inputs` (all optional): `recipe`; `workspace` / `available_workspaces` /
    `env_workspace`; the axis lists `topics`/`personas`/`formats`/`voices`/`goals`/
    `platforms`/`languages`/`output_types`/`presentations`; `set` (a list of `--set`
    strings); `idempotency_key`; `target_folio`; `purpose`; `explain` (bool); `spend`
    (bool — is this a paid verb; governs the workspace/key door-class policy);
    `outline_parent` / `allow_drift` (the CLI-UX C7 outline-drift-guard inputs, DR-3).

    `key_factory` is an injection seam for deterministic tests; production uses uuid4.
    Raises `NormalizeError` on a fatal automation omission or a malformed `--set`.
    """
    if door_class not in DOOR_CLASSES:
        raise NormalizeError(
            f"invalid-door-class: expected one of {sorted(DOOR_CLASSES)}, got {door_class!r}",
            field="door_class",
        )
    spend = bool(friendly_inputs.get("spend"))
    recipe = _resolve_recipe(friendly_inputs, door_class)
    workspace = _resolve_workspace(friendly_inputs, door_class, spend=spend)
    user = _resolve_user(friendly_inputs, door_class)
    if workspace is not None and user is None:
        # §23: a resolved workspace ALWAYS carries its owning user — a workspace without a user
        # would build a `users/None/…` path. Fail LOUD here (never a silent default).
        raise NormalizeError(
            "missing-user: a workspace requires its owning --user (the §23 isolation prefix; "
            "users/<user>/workspaces/<workspace>/) — never a users/None/ path",
            field="user",
        )

    params: dict[str, Any] = {"recipe": recipe}
    for key in _AXIS_KEYS:
        values = _as_str_list(friendly_inputs.get(key))
        if values:
            params[key] = values
    goals = _as_str_list(friendly_inputs.get("goals"))
    if goals:
        # Goals STACK into ONE goal-set (§8): several goals shape one artifact, they do not
        # fan out (that is the per-axis behavior). Shape: `goal_sets = [[g1, g2, …]]`.
        params["goal_sets"] = [goals]

    overrides = compile_overrides(_as_str_list(friendly_inputs.get("set")))
    if overrides:
        params["overrides"] = overrides

    target_folio = friendly_inputs.get("target_folio")
    if target_folio is not None:
        params["target_folio"] = target_folio
    purpose = friendly_inputs.get("purpose")
    if purpose:
        params["purpose"] = str(purpose)
    if friendly_inputs.get("explain"):
        # The read-only `explain` projection (C1) — a pure preview side-channel, never an
        # identity input.
        params["explain"] = True

    # CLI-UX C7 (DR-3): pass the outline-drift-guard inputs straight through, values-only. Both are
    # PURE guard inputs — no door-class defaulting, and (like `explain`) never identity components:
    # the server-side guard reads them from `ctx.params` but never folds them into the token /
    # preimage, so the driven artifact-id is byte-identical with and without `--from`.
    outline_parent = friendly_inputs.get("outline_parent")
    if outline_parent:
        params["outline_parent"] = str(outline_parent)
    if friendly_inputs.get("allow_drift"):
        params["allow_drift"] = True

    key, generated = _resolve_idempotency_key(
        friendly_inputs, door_class, spend=spend, key_factory=key_factory
    )
    if key is not None:
        params["idempotency_key"] = key

    notices: list[str] = []
    if generated is not None:
        notices.append(f"generated idempotency key {generated} — reuse it to make a retry safe")
        if target_folio == TARGET_FOLIO_AUTO:
            notices.append(
                "target_folio=auto with an auto-generated key: reuse the printed key or a "
                "retry mints a second empty folio"
            )

    return Normalized(
        workspace=workspace,
        user=user,
        params=params,
        generated_key=generated,
        notices=tuple(notices),
    )
