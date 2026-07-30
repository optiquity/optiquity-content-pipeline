"""Discovery — `list <type> [filters]` / `get <type> <id>` (§21.3, §13.2), SSOT-FREE.

Design authority: `docs/design.md`
  §21.3  — the CLOSED discovery type list + the self-describing META-TYPES (`verbs`, `actions`,
           `types`, `codes`) so callers never hardcode a vocabulary that could drift; the §13.2
           `Pred` filters, AND-combined; the reserved filters (`provenance`; artifact lineage —
           `generating_run`, `source_commit` map-contains, `created` range); and the FIVE
           COMPUTED CURRENCY FIELDS — `fit_revision`, `fit_current`, `serialize_revision`,
           `serialize_current`, `minted_ts` — **computed at read time from the content-addressed
           STORE, NEVER stored and NEVER read from the SSOT** (currency is non-monotonic — a
           config/tool-pin revert un-stales old outputs — so any stored marker would be a lie
           window, §24). All five are also `list deliverables` filters; the blast-radius remedy
           is `list deliverables {platform, fit_current: false}` → a `render force_reconcile`
           loop (§21.8).
  §13.2  — the unified operator grammar: `Pred(path, op, value)`; wire form `{"path","op","value"}`;
           `pred_op ∈ {eq, in, prefix, ge, le, gt, lt, range}`; the map shorthand `{field: value}`
           is the terse `eq` form (§21.3's own `{platform, fit_current: false}` example).
  §22.7  — SSOT never gates control flow; correctness rides the content-addressed store. This
           module reads the OUTPUT STORE + config ONLY; it imports no SSOT module and NOTHING
           here branches on a tracker read (the currency currency-resolver reads config, never
           the SSOT — step-22 INV-CORRECTNESS). `verbs`/`codes`/`types` read the LIVE constants
           (`invoke.KNOWN_VERBS`, `results.CODES`, this module's `TYPES`); `actions` reads the
           step-33 closed set INJECTED at wiring (single source = `session.CONTINUE_ACTIONS`) so
           this read-only module never imports the generation stack — no import cycle, no ssot.

**Currency, computed at read (the heart of this step).** For a deliverable, `fit_current`
compares its recorded fit-binding digest against the CURRENTLY-RESOLVED reconcile-inputs digest
(the §16 fit "current" rule, `reconcile.fit_digest`); `serialize_current` compares its recorded
render-binding digest against the CURRENTLY-RESOLVED serialize-inputs digest (the §17 rule,
`serialize.serialize_digest`). The "current" digest is produced by a `CurrencyResolver` seam
(default: re-read the platform hard-limits + the pinned tool bundle from live config — the exact
inputs the platform-tightened blast radius and a tool-pin bump move; injected in tests). Nothing
is stored; a fresh read recomputes, so a revert self-heals `fit_current` to True with no write.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pipeline import outline_store, reconcile, serialize
from pipeline.api import invoke as invoke_mod
from pipeline.api import results
from pipeline.api import token as token_mod
from pipeline.canonical import canonical_json_str
from pipeline.folios import (
    FolioError,
    FolioNotFoundError,
    get_folio,
    list_folio_members,
)
from pipeline.ids import IdError, parse_id
from pipeline.store import WorkspaceStore, is_temp_name

__all__ = [
    "BASELINE",
    "DATA_TYPES",
    "META_TYPES",
    "TYPES",
    "CurrencyResolver",
    "DefaultCurrencyResolver",
    "PredError",
    "apply_preds",
    "deliverable_detail",
    "discovery_handlers",
    "get_handler",
    "list_handler",
    "parse_preds",
    "register_discovery_handlers",
]

#: §21.3 the `baseline | hex12` currency revision label — no qualifier means the baseline.
BASELINE = "baseline"

#: §21.3 the CLOSED discovery data-type list (store- and registry-backed).
DATA_TYPES = (
    "schemas",
    "dimensions",
    "dimension-entries",
    "recipes",
    "voices",
    "lexicons",
    "folios",
    "folio-members",
    "folio-types",
    "artifacts",
    "deliverables",
    "outlines",
    "sources",
    "content-kinds",
    "render-targets",
    "plan-progress",
)

#: §21.3 the self-describing META-TYPES — a caller never hardcodes a vocabulary that could drift.
META_TYPES = ("verbs", "actions", "types", "codes")

#: The complete closed `list <type>` vocabulary — `list types` reports exactly this.
TYPES = (*DATA_TYPES, *META_TYPES)

#: The §5 registries that back the config data-types (one file per value — the matrix, §3/§4).
#: `<type> → (framework-root subdir, glob)`; entries are one markdown/yaml file each.
_REGISTRY_DIRS: dict[str, tuple[str, str]] = {
    "dimensions": ("", ""),  # handled specially (the axis directories themselves)
    "dimension-entries": ("", ""),  # handled specially (entries across all axis dirs)
    "recipes": ("recipes", "*.md"),
    "voices": ("voices", "*.md"),  # a §3/§4 axis dir, also directly listable by name (C3c)
    "lexicons": ("lexicons", "*.md"),  # the §5 lexicon registry (C3c)
    "folio-types": ("folio-types", "*.md"),
    "content-kinds": ("content-kinds", "*.md"),
    "render-targets": ("render-targets", "*.md"),
    "schemas": ("", "_schema.yaml"),  # the co-located per-collection schemas
}

#: The dimension axis registries (one directory per axis — the §3/§4 matrix).
_AXIS_DIRS = (
    "personas",
    "platforms",
    "formats",
    "topics",
    "voices",
    "goals",
    "languages",
    "output-types",
    "presentations",
)


class PredError(ValueError):
    """A malformed §13.2 discovery filter — refused loudly (never silently dropped, §3.1)."""

    code = "invalid-filter"


# ---------------------------------------------------------------------------
# The currency-resolver seam (§21.3): the CURRENT reconcile-/serialize-inputs digests.
# ---------------------------------------------------------------------------


class CurrencyResolver(Protocol):
    """Resolves the CURRENTLY-effective reconcile-/serialize-inputs digests for a coordinate.

    The seam that makes currency computed-at-read (§21.3) yet SSOT-FREE (§22.7): it reads live
    CONFIG + the stored binding's preimage, never the tracker. `current_fit_digest` returns the
    `hex12` a fresh unqualified render's reconcile inputs would digest to (the §16 "current"
    rule); `current_serialize_digest` the same for serialize (§17). Returning the stored digest
    unchanged means "no config drift detected" (the safe, self-healing default)."""

    def current_fit_digest(
        self, *, root: Path, workspace: str, fitted_id: str, stored_preimage: Mapping[str, Any]
    ) -> str: ...

    def current_serialize_digest(
        self, *, root: Path, workspace: str, deliverable_id: str, stored_preimage: Mapping[str, Any]
    ) -> str: ...


@dataclass(frozen=True)
class DefaultCurrencyResolver:
    """The production currency resolver — re-reads live config, reuses the step-26/29 digests.

    `current_fit_digest`: re-derive the reconcile-inputs preimage with the platform's CURRENT
    hard-limits (the input the platform-tightened blast radius moves, §21.3) substituted into the
    stored preimage's other components, then `reconcile.fit_digest`. `current_serialize_digest`:
    re-derive the serialize-inputs preimage with the CURRENT pinned tool bundle (a pandoc/reader/
    strip-filter pin bump, §17) via `serialize.serialize_inputs_preimage`, then
    `serialize.serialize_digest`. Any config-read failure returns the stored digest — "no
    detectable drift" — never a fabricated staleness. NEVER reads the SSOT (§22.7).

    Full recipe-aware re-resolution of the advisory/render-dim/strategy reconcile components
    rides the gated transport-wiring step (§21.9); the platform-hard-limit + tool-pin re-read
    here is exactly the blast-radius the design's acceptance names, and every test injects a
    precise resolver."""

    def current_fit_digest(
        self, *, root: Path, workspace: str, fitted_id: str, stored_preimage: Mapping[str, Any]
    ) -> str:
        stored_digest = reconcile.fit_digest(stored_preimage)
        try:
            parsed = parse_id(fitted_id)
            platform = parsed.platform
            if platform is None:
                return stored_digest
            current_limits_delta = self._platform_hard_limits_delta(root, workspace, platform)
            rebuilt = {**dict(stored_preimage), "hard-limits": current_limits_delta}
            canonical = json.loads(canonical_json_str(rebuilt))
            return reconcile.fit_digest(canonical)
        except Exception:  # noqa: BLE001 — a config-read failure is "no detectable drift", never a lie
            return stored_digest

    def current_serialize_digest(
        self, *, root: Path, workspace: str, deliverable_id: str, stored_preimage: Mapping[str, Any]
    ) -> str:
        stored_digest = serialize.serialize_digest(stored_preimage)
        try:
            render_target = stored_preimage.get("render_target")
            render_inputs = stored_preimage.get("render_inputs")
            if not isinstance(render_target, Mapping) or not isinstance(render_inputs, Mapping):
                return stored_digest
            # DR-4 C9 carry-forward: a TYPED deliverable's stored `tool_bundle` carries the SD-5
            # `section_attr_transform_version` key (present only when the section-attr strip altered
            # published bytes, §17 FR7.1 OMIT-WHEN-ABSENT). The rebuild must re-derive that flag
            # from the stored bundle and thread it through — otherwise the rebuilt tool_bundle omits
            # the key, the digest differs, and a stable typed deliverable reads as SPURIOUS drift.
            stored_tool = stored_preimage.get("tool_bundle", {})
            section_attr_transformed = (
                isinstance(stored_tool, Mapping)
                and "section_attr_transform_version" in stored_tool
            )
            # DR-5 C6 carry-forward (the EXACT twin of the SD-5 line above): a CITING deliverable's
            # stored `tool_bundle` carries the `citeproc_enablement_version` key OMIT-WHEN-ABSENT.
            # The rebuild must re-derive that flag from the stored bundle and thread it through — or
            # the rebuilt bundle omits the key, the digest differs, and a stable citing deliverable
            # reads as SPURIOUS drift (the same bug the SD-5/C10 discovery fix closed).
            citeproc_enabled = (
                isinstance(stored_tool, Mapping)
                and "citeproc_enablement_version" in stored_tool
            )
            # B (F2) carry-forward (the THIRD such OMIT-WHEN-ABSENT twin): an EMBEDDING
            # deliverable's stored `tool_bundle` carries `asset_embed_version` (present only when a
            # body figure embedded). The rebuild must re-derive it — else the rebuilt bundle omits
            # the key, the digest differs, and a stable picture-bearing html/docx deliverable reads
            # as SPURIOUS drift (phantom re-mint). The `embedded_assets` CONTENT half needs nothing
            # here: it is baked into the stored `render_inputs` and passed through verbatim by the
            # rebuild below (exactly like the stored `csl`), so re-deriving the pin flag reproduces
            # the digest.
            assets_embedded = (
                isinstance(stored_tool, Mapping) and "asset_embed_version" in stored_tool
            )
            # Rebuild with the CURRENT pinned tool bundle (serialize_inputs_preimage sources the
            # pins from the live module constants); the stored render_target/inputs are kept.
            rebuilt = serialize.serialize_inputs_preimage(
                render_target=render_target,
                render_inputs=render_inputs,
                section_attr_transformed=section_attr_transformed,
                citeproc_enabled=citeproc_enabled,
                assets_embedded=assets_embedded,
            )
            return serialize.serialize_digest(rebuilt)
        except Exception:  # noqa: BLE001 — no detectable drift on a config-read failure
            return stored_digest

    @staticmethod
    def _platform_hard_limits_delta(root: Path, workspace: str, platform: str) -> dict[str, Any]:
        """The platform's CURRENT hard-limits, delta-vs-floor — the live config re-read (§16)."""
        from pipeline.cascade import CascadeEnv
        from pipeline.ids import delta_vs_floor

        env = CascadeEnv(root, workspace=workspace)
        entry = env.resolver.resolve("platforms", platform)
        schema = env.resolver.schema("platforms")
        limits = dict(entry.effective.get("hard_limits") or {})
        floor = dict(schema.attributes["hard_limits"].default or {})
        return delta_vs_floor(limits, floor, where="hard-limits")


# ---------------------------------------------------------------------------
# §13.2 predicate filters, AND-combined.
# ---------------------------------------------------------------------------

_PRED_OPS = frozenset({"eq", "in", "prefix", "ge", "le", "gt", "lt", "range"})


@dataclass(frozen=True)
class Pred:
    """One §13.2 discovery predicate: `Pred(path, op, operand)` — a filter over a record field."""

    path: str
    op: str
    value: Any


def parse_preds(raw: Any) -> tuple[Pred, ...]:
    """Parse the supplied filters (§13.2), AND-combined. Accepts the map shorthand
    `{field: value}` (each an `eq`, the §21.3 `{platform, fit_current: false}` form) OR a
    sequence of wire preds `{"path","op","value"}`. Malformed → `PredError` (never dropped)."""
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        return tuple(Pred(path=str(k), op="eq", value=v) for k, v in raw.items())
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        preds: list[Pred] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise PredError(
                    f"invalid-filter: a wire filter is a {{path,op,value}} object, got {item!r}"
                )
            path = item.get("path")
            op = item.get("op", "eq")
            if not isinstance(path, str) or not path:
                raise PredError(f"invalid-filter: a filter needs a string `path`, got {item!r}")
            if op not in _PRED_OPS:
                raise PredError(
                    f"invalid-filter: op {op!r} is not one of {sorted(_PRED_OPS)} (§13.2)"
                )
            preds.append(Pred(path=path, op=op, value=item.get("value")))
        return tuple(preds)
    raise PredError(
        f"invalid-filter: filters are a map shorthand or a list of preds, got {type(raw).__name__}"
    )


def apply_preds(record: Mapping[str, Any], preds: Sequence[Pred]) -> bool:
    """AND-combine every predicate over `record` (§13.2). A field absent from the record fails
    its predicate (never a silent pass). `source_commit` uses map-contains; the rest are direct."""
    return all(_eval_pred(record, pred) for pred in preds)


def _eval_pred(record: Mapping[str, Any], pred: Pred) -> bool:
    # Reserved lineage filter: source_commit matches an artifact whose commit-map CONTAINS the
    # sha for ANY instance (§21.3/§7.2) — map-contains, not a scalar equal.
    if pred.path == "source_commit":
        commit_map = record.get("source_commit")
        if isinstance(commit_map, Mapping):
            return pred.value in commit_map.values()
        return commit_map == pred.value
    if pred.path not in record:
        return False
    field = record[pred.path]
    op = pred.op
    if op == "eq":
        return field == pred.value
    if op == "in":
        return _is_seq(pred.value) and field in pred.value
    if op == "prefix":
        return (
            isinstance(field, str)
            and isinstance(pred.value, str)
            and field.startswith(pred.value)
        )
    if op == "range":
        if not (_is_seq(pred.value) and len(pred.value) == 2):
            raise PredError(
                f"invalid-filter: `range` operand is a [lo, hi] pair, got {pred.value!r}"
            )
        lo, hi = pred.value
        return _cmp(field, lo, "ge") and _cmp(field, hi, "le")
    return _cmp(field, pred.value, op)


def _is_seq(value: Any) -> bool:
    """A non-string sequence operand (the `in`/`range` operand shape, §13.2)."""
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def _cmp(field: Any, value: Any, op: str) -> bool:
    try:
        if op == "ge":
            return field >= value
        if op == "le":
            return field <= value
        if op == "gt":
            return field > value
        if op == "lt":
            return field < value
    except TypeError:
        return False
    return False  # pragma: no cover — every op is enumerated above


# ---------------------------------------------------------------------------
# Store readers + the detail shapes (§21.3).
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Mapping[str, Any] | None:
    try:
        raw = path.read_bytes()
    except (FileNotFoundError, IsADirectoryError):
        return None
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, Mapping) else None


def _submap(record: Mapping[str, Any], key: str) -> dict[str, Any]:
    """The nested mapping at `record[key]`, or an empty dict — a total, shape-safe reader."""
    value = record.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _iter_records(directory: Path, level: str) -> list[str]:
    """The ids of the stored RECORDS at `directory` whose parsed level is `level` (§18).

    Only exact-parse ids are records — a layer-2 bytes sibling `<id>.<ext>` fails `parse_id`
    (an extra dotted segment) and is skipped, so records and payloads never conflate (§7.4)."""
    ids: list[str] = []
    if not directory.is_dir():
        return ids
    for entry in sorted(directory.iterdir()):
        if not entry.is_file() or is_temp_name(entry.name):
            continue
        try:
            parsed = parse_id(entry.name)
        except IdError:
            continue
        if parsed.family == "artifact" and parsed.level == level and parsed.part is None:
            ids.append(entry.name)
    return ids


def deliverable_detail(
    store: WorkspaceStore,
    deliverable_id: str,
    *,
    root: Path,
    workspace: str,
    resolver: CurrencyResolver,
) -> dict[str, Any] | None:
    """The `get deliverable` detail shape (§21.3): coordinates + path + render-binding/pins + the
    FIVE computed currency fields + part-ids + side. Currency is COMPUTED HERE, at read, from the
    store + the resolver — never stored, never the SSOT (§21.3/§22.7). None if no such record."""
    record = _read_json(store.output_path(deliverable_id))
    if record is None:
        return None
    binding = _submap(record, "binding")
    parsed = parse_id(deliverable_id)
    artifact_id = f"a-{parsed.root_hex}"
    fitted_id = _submap(binding, "fit_binding_ref").get("fitted_id")

    # -- serialize-level currency (§17): recorded digest vs the CURRENTLY-resolved digest.
    serialize_recorded = binding.get("digest")
    serialize_current = None
    if isinstance(serialize_recorded, str):
        current_s = resolver.current_serialize_digest(
            root=root, workspace=workspace, deliverable_id=deliverable_id,
            stored_preimage=_submap(binding, "preimage"),
        )
        serialize_current = serialize_recorded == current_s

    # -- fit-level currency (§16): the deliverable's fit-binding digest vs the current one.
    fit_current = None
    if isinstance(fitted_id, str):
        fit_binding = _submap(_read_json(store.output_path(fitted_id)) or {}, "binding")
        fit_recorded = fit_binding.get("digest")
        if isinstance(fit_recorded, str):
            current_d = resolver.current_fit_digest(
                root=root, workspace=workspace, fitted_id=fitted_id,
                stored_preimage=_submap(fit_binding, "preimage"),
            )
            fit_current = fit_recorded == current_d

    layer2 = _submap(record, "layer2")
    detail: dict[str, Any] = {
        "deliverable_id": deliverable_id,
        "artifact_id": artifact_id,
        "platform": parsed.platform,
        "language": parsed.language,
        "output_type": parsed.output_type,
        "presentation": parsed.presentation,
        # the five COMPUTED currency fields (§21.3) — never stored, computed here at read:
        "fit_revision": parsed.fit_revision or BASELINE,
        "fit_current": fit_current,
        "serialize_revision": parsed.serialize_revision or BASELINE,
        "serialize_current": serialize_current,
        "minted_ts": binding.get("minted_ts"),
        # coordinates, path, pins, side, provenance:
        "path": layer2.get("path"),
        "side": record.get("side"),
        "pin_bundle": binding.get("pin_bundle"),
        "provenance": record.get("provenance", "instance"),
        "part_ids": list(record.get("part_ids", [])),
    }
    return detail


def artifact_detail(store: WorkspaceStore, artifact_id: str) -> dict[str, Any] | None:
    """The `get artifact` detail shape (§21.3): binding (the id preimage) + metadata + grounding
    summary + generating_run + deliverable-ids + part-ids + the reserved lineage fields."""
    record = _read_json(store.output_path(artifact_id))
    if record is None:
        return None
    binding = _submap(record, "binding")
    preimage = _submap(binding, "preimage")
    grounding = _submap(record, "grounding")
    parts = record.get("parts") if isinstance(record.get("parts"), Sequence) else ()
    part_ids = [p.get("part-id") for p in parts if isinstance(p, Mapping) and p.get("part-id")]
    return {
        "artifact_id": artifact_id,
        "preimage": dict(preimage),
        "digest": binding.get("digest"),
        "metadata": dict(record.get("metadata", {})),
        "grounding_ledger_size": len(grounding),
        "deliverable_ids": _deliverables_of(store, artifact_id),
        "part_ids": part_ids,
        # reserved lineage filters (§21.3/§7.2):
        "provenance": record.get("provenance", "instance"),
        "generating_run": record.get("generating_run", preimage.get("generating_run")),
        "source_commit": preimage.get("source-commit"),
        "created": record.get("created", binding.get("minted_ts")),
    }


def _deliverables_of(store: WorkspaceStore, artifact_id: str) -> list[str]:
    """The deliverable-ids whose fitted prefix roots at `artifact_id` (§21.3: every fit visible
    through its deliverables). A prefix-by-root-hex scan of the store (§7.4)."""
    root_hex = parse_id(artifact_id).root_hex
    out: list[str] = []
    for did in _iter_records(store.deliverables_dir, "deliverable"):
        if parse_id(did).root_hex == root_hex:
            out.append(did)
    return out


# ---------------------------------------------------------------------------
# The type enumerators (list) + detail (get).
# ---------------------------------------------------------------------------


def _list_deliverables(
    store: WorkspaceStore, *, root: Path, workspace: str, resolver: CurrencyResolver
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for did in _iter_records(store.deliverables_dir, "deliverable"):
        detail = deliverable_detail(store, did, root=root, workspace=workspace, resolver=resolver)
        if detail is not None:
            out.append(detail)
    return out


def _list_artifacts(store: WorkspaceStore) -> list[dict[str, Any]]:
    return [
        detail
        for aid in _iter_records(store.artifacts_dir, "artifact")
        if (detail := artifact_detail(store, aid)) is not None
    ]


def _list_folios(store: WorkspaceStore) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    folios_dir = store.folios_dir
    if not folios_dir.is_dir():
        return out
    for entry in sorted(folios_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            view = get_folio(store, entry.name)
        except FolioError:
            continue
        out.append(_folio_detail(view))
    return out


def _folio_detail(view: Any) -> dict[str, Any]:
    return {
        "folio_id": view.folio_id,
        "purpose": view.purpose,
        "folio_type": view.folio_type,
        "provenance": view.provenance,
        "members": [
            {"artifact_id": m.artifact_id, "added_ts": m.added_ts, "pin": m.pin, "role": m.role}
            for m in view.members
        ],
    }


def _list_folio_members(store: WorkspaceStore, folio_id: str | None) -> list[dict[str, Any]]:
    """Members of a given folio (`folio_id` filter) or across all folios (§21.3/§9.2)."""
    out: list[dict[str, Any]] = []
    folio_ids = [folio_id] if isinstance(folio_id, str) else [
        e.name for e in sorted(store.folios_dir.iterdir()) if e.is_dir()
    ] if store.folios_dir.is_dir() else []
    for fid in folio_ids:
        try:
            members = list_folio_members(store, fid)
        except FolioError:
            continue
        for m in members:
            out.append({
                "folio_id": fid,
                "artifact_id": m.artifact_id,
                "added_ts": m.added_ts,
                "pin": m.pin,
                "role": m.role,
                "provenance": "instance",
            })
    return out


def _list_registry(root: Path, type_name: str) -> list[dict[str, Any]]:
    """Enumerate a §5 registry data-type (one file per value — the matrix, §3/§4). Reads the
    framework-root registry dirs; each entry surfaces `{id, provenance, path}` from frontmatter."""
    if type_name == "dimensions":
        return [
            {"id": axis, "provenance": "framework"}
            for axis in _AXIS_DIRS
            if (root / axis).is_dir()
        ]
    if type_name == "dimension-entries":
        out: list[dict[str, Any]] = []
        for axis in _AXIS_DIRS:
            out.extend(_scan_dir(root / axis, "*.md", axis=axis))
        return out
    if type_name == "sources":
        return _scan_dir(root / "sources", "*.md")
    subdir, glob = _REGISTRY_DIRS.get(type_name, ("", ""))
    if not subdir:
        return []
    return _scan_dir(root / subdir, glob)


def _scan_dir(directory: Path, glob: str, *, axis: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob(glob)):
        if ".template." in path.name or path.name.startswith("_"):
            continue
        entry = {
            "id": path.stem,
            "provenance": _frontmatter_provenance(path),
            "path": str(path.relative_to(directory.parent)),
        }
        if axis is not None:
            entry["dimension"] = axis
        out.append(entry)
    return out


def _frontmatter_provenance(path: Path) -> str:
    """The entry's declared `provenance:` (framework|instance), best-effort from the leading
    `---` frontmatter block. Defaults to `framework` (the public-repo default, §CLAUDE rule 4)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "framework"
    seen_open = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "---":
            if not seen_open:
                seen_open = True
                continue
            break  # end of the frontmatter block
        if seen_open and stripped.startswith("provenance:"):
            return stripped.split(":", 1)[1].strip()
    return "framework"


def _plan_progress(store: WorkspaceStore) -> list[dict[str, Any]]:
    """The §22.3 completeness view from the OUTPUT STORE (§22.7: the sweep reads materialized
    ids, never SSOT rows). A store inventory — artifact + deliverable counts, token-optional."""
    artifacts = _iter_records(store.artifacts_dir, "artifact")
    fitted = _iter_records(store.artifacts_dir, "fitted")
    deliverables = _iter_records(store.deliverables_dir, "deliverable")
    return [{
        "materialized_artifacts": len(artifacts),
        "materialized_fitted": len(fitted),
        "materialized_deliverables": len(deliverables),
    }]


def _list_outlines(store: WorkspaceStore) -> list[dict[str, Any]]:
    """The DR-3 pre-compose OUTLINE store (`<root>/outlines/<digest>`, §21.8 RETAIN-ALL): every
    content-addressed authored/edited outline in this workspace. Read-only, ssot-free (a directory
    listing of the OUTPUT-side store, §22.7). Each surfaces the SAME `{id, provenance, path}` shape
    as the registry `list` types — the `id` is the bare 64-hex `outline-digest` (a content address,
    NOT a §7.4 id), `provenance` is `instance` (workspace-authored content, like folio-members),
    `path` is workspace-relative. The filename IS the digest (no extension)."""
    out: list[dict[str, Any]] = []
    outlines_dir = store.root / outline_store.OUTLINES_SUBDIR
    if not outlines_dir.is_dir():
        return out
    for entry in sorted(outlines_dir.iterdir()):
        if not entry.is_file() or is_temp_name(entry.name):
            continue
        out.append({
            "id": entry.name,
            "provenance": "instance",
            "path": f"{outline_store.OUTLINES_SUBDIR}/{entry.name}",
        })
    return out


# ---------------------------------------------------------------------------
# The self-describing META-TYPES (§21.3) — LIVE constant reads, never a hardcode.
# ---------------------------------------------------------------------------


def _list_codes() -> list[dict[str, Any]]:
    """`list codes` → the LIVE `results.CODES` taxonomy, each `CodeSpec` self-describing (§21.3).
    Add/remove a code in `results` → this reflects it with no second edit (the results.py
    docstring anticipates exactly this wiring)."""
    return [
        {
            "code": spec.code,
            "tier": spec.tier,
            "statuses": list(spec.statuses),
            "remediation_action": spec.remediation_action,
            "section": spec.section,
            "summary": spec.summary,
        }
        for spec in results.CODES.values()
    ]


def _list_verbs() -> list[dict[str, Any]]:
    """`list verbs` → the LIVE `invoke.KNOWN_VERBS` closed set (§21.1) — never hardcoded."""
    return [{"verb": v} for v in sorted(invoke_mod.KNOWN_VERBS)]


def _list_types() -> list[dict[str, Any]]:
    """`list types` → this module's closed `TYPES` vocabulary, tagged data vs meta (§21.3)."""
    return [{"type": t, "meta": t in META_TYPES} for t in TYPES]


def _list_actions(action_vocab: frozenset[str]) -> list[dict[str, Any]]:
    """`list actions` → the step-33 closed continue-session action set (§21.2), sourced from the
    INJECTED `session.CONTINUE_ACTIONS` (single source; a vocabulary change flows here with no
    second edit) — read ssot-free without importing the generation stack."""
    return [{"action": a} for a in sorted(action_vocab)]


# ---------------------------------------------------------------------------
# The list / get dispatch (§21.3).
# ---------------------------------------------------------------------------


def _root_of(store: WorkspaceStore) -> Path:
    """The framework root for a workspace store (`root/workspaces/<ws>` → grandparent, §21.1)."""
    return store.root.parent.parent


def _list(
    ctx: invoke_mod.HandlerContext, *, resolver: CurrencyResolver, action_vocab: frozenset[str]
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """`list <type> [filters]` (§21.3): enumerate a closed type, AND-filter (§13.2), one
    ResultItem per record. An unknown type → `not-found`; a malformed filter → a code-less
    block naming the defect (the closed §21.7 vocabulary has no `invalid-filter` code)."""
    type_name = ctx.params.get("type")
    if not isinstance(type_name, str) or type_name not in TYPES:
        return (
            [results.make_result(
                results.CODE_NOT_FOUND,
                item=str(type_name) if type_name is not None else "",
                hint=f"unknown discovery type {type_name!r}; closed set: {list(TYPES)} (§21.3)",
            )],
            None,
        )
    try:
        preds = parse_preds(ctx.params.get("filters"))
    except PredError as exc:
        return ([_block(f"list {type_name}: {exc}")], None)

    records = _enumerate(ctx, type_name, resolver=resolver, action_vocab=action_vocab)
    id_key = _ID_KEY.get(type_name, "id")
    items = [
        results.ResultItem(
            item=str(record.get(id_key, "")),
            status="ok",
            ids={id_key: record.get(id_key)} if record.get(id_key) is not None else {},
            context=record,
        )
        for record in records
        if apply_preds(record, preds)
    ]
    return (items, None)


#: The field naming the record's primary id, per type (drives `item` + `ids`).
_ID_KEY = {
    "deliverables": "deliverable_id",
    "artifacts": "artifact_id",
    "folios": "folio_id",
    "folio-members": "artifact_id",
    "verbs": "verb",
    "actions": "action",
    "types": "type",
    "codes": "code",
}


def _enumerate(
    ctx: invoke_mod.HandlerContext,
    type_name: str,
    *,
    resolver: CurrencyResolver,
    action_vocab: frozenset[str],
) -> list[dict[str, Any]]:
    store = ctx.store
    root = _root_of(store)
    if type_name == "deliverables":
        return _list_deliverables(store, root=root, workspace=ctx.workspace, resolver=resolver)
    if type_name == "artifacts":
        return _list_artifacts(store)
    if type_name == "folios":
        return _list_folios(store)
    if type_name == "folio-members":
        folio_id = ctx.params.get("folio_id")
        return _list_folio_members(store, folio_id if isinstance(folio_id, str) else None)
    if type_name == "plan-progress":
        return _plan_progress(store)
    if type_name == "outlines":
        return _list_outlines(store)
    if type_name == "codes":
        return _list_codes()
    if type_name == "verbs":
        return _list_verbs()
    if type_name == "types":
        return _list_types()
    if type_name == "actions":
        return _list_actions(action_vocab)
    return _list_registry(root, type_name)  # the §5 registry data-types


def _get(
    ctx: invoke_mod.HandlerContext, *, resolver: CurrencyResolver
) -> tuple[Sequence[results.ResultItem], token_mod.Token | None]:
    """`get <type> <id>` (§21.3): one record's detail shape. `id` is Gate-3-isolated (§21.1).
    An unknown type or unknown id → `not-found`."""
    type_name = ctx.params.get("type")
    id_str = ctx.params.get("id")
    if not isinstance(type_name, str) or type_name not in TYPES:
        return ([results.make_result(
            results.CODE_NOT_FOUND, item=str(type_name),
            hint=f"unknown discovery type {type_name!r} (§21.3)",
        )], None)
    if not isinstance(id_str, str) or not id_str:
        return ([results.make_result(
            results.CODE_NOT_FOUND, item=str(id_str), hint="get needs an `id` (§21.3)"
        )], None)

    detail = _get_detail(ctx, type_name, id_str, resolver=resolver)
    if detail is None:
        return ([results.make_result(
            results.CODE_NOT_FOUND, item=id_str, ids={"id": id_str},
            hint=f"no {type_name} record for {id_str!r} in this workspace (§21.3)",
        )], None)
    id_key = _ID_KEY.get(type_name, "id")
    return (
        [results.ResultItem(item=id_str, status="ok", ids={id_key: id_str}, context=detail)],
        None,
    )


def _get_detail(
    ctx: invoke_mod.HandlerContext, type_name: str, id_str: str, *, resolver: CurrencyResolver
) -> dict[str, Any] | None:
    store = ctx.store
    root = _root_of(store)
    try:
        if type_name == "deliverables":
            return deliverable_detail(
                store, id_str, root=root, workspace=ctx.workspace, resolver=resolver
            )
        if type_name == "artifacts":
            return artifact_detail(store, id_str)
        if type_name == "folios":
            try:
                return _folio_detail(get_folio(store, id_str))
            except FolioNotFoundError:
                return None
    except (IdError, FolioError):
        return None
    return None  # get on a meta/registry type is not id-addressed in v1


def _block(hint: str) -> results.ResultItem:
    """A code-less block (§21.7 closed) — a malformed discovery call the taxonomy does not name."""
    return results.ResultItem(item="discovery", status="block", remediation={"hint": hint})


# ---------------------------------------------------------------------------
# Handler factories + the wiring point (§21.1). EXPLICIT — never at import.
# ---------------------------------------------------------------------------


def list_handler(
    *, resolver: CurrencyResolver | None = None, action_vocab: frozenset[str] = frozenset()
) -> invoke_mod.Handler:
    """The `list` verb handler. `resolver` computes currency (default: `DefaultCurrencyResolver`);
    `action_vocab` is the injected `session.CONTINUE_ACTIONS` for the `actions` meta-type."""
    r = resolver if resolver is not None else DefaultCurrencyResolver()

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _list(ctx, resolver=r, action_vocab=action_vocab)

    return handler


def get_handler(*, resolver: CurrencyResolver | None = None) -> invoke_mod.Handler:
    """The `get` verb handler. `resolver` computes deliverable currency (default resolver)."""
    r = resolver if resolver is not None else DefaultCurrencyResolver()

    def handler(ctx: invoke_mod.HandlerContext) -> Any:
        return _get(ctx, resolver=r)

    return handler


def discovery_handlers(
    *, resolver: CurrencyResolver | None = None, action_vocab: frozenset[str] = frozenset()
) -> dict[str, invoke_mod.Handler]:
    """The `list`/`get` handler pair — the seam continue-session's `list`/`get` actions reuse."""
    return {
        "list": list_handler(resolver=resolver, action_vocab=action_vocab),
        "get": get_handler(resolver=resolver),
    }


def register_discovery_handlers(
    *, resolver: CurrencyResolver | None = None, action_vocab: frozenset[str] = frozenset()
) -> None:
    """Wire `list` + `get` into the invoke dispatch registry (§21.1). EXPLICIT — never at import.
    `action_vocab` is passed `session.CONTINUE_ACTIONS` by the production wiring (single source)."""
    handlers = discovery_handlers(resolver=resolver, action_vocab=action_vocab)
    invoke_mod.register_handler("list", handlers["list"])
    invoke_mod.register_handler("get", handlers["get"])
