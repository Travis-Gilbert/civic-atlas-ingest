"""OpenBIM sidecar export for Civic Atlas archetype renders."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JsonDict = dict[str, Any]

_IFC_GUID_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"


def make_ifc_text(*, archetype: str, spec: JsonDict) -> str:
    """Create a minimal IFC4 semantic sidecar for a rendered archetype."""
    spec_id = str(spec.get("spec_id") or "unknown")
    name = str(spec.get("display_name") or spec_id)
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = _parts_from_spec(spec)

    lines = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');",
        f"FILE_NAME('{_esc(spec_id)}.ifc','{timestamp}',('Civic Atlas'),('Our Civic Atlas'),",
        "'civic-atlas-ingest','Scene Foundry','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
        f"#1=IFCPROJECT('{_guid(spec_id + ':project')}',$,'Our Civic Atlas',$,$,$,$,$);",
        f"#2=IFCSITE('{_guid(spec_id + ':site')}',$,'{_esc(spec_id)} Site',$,$,$,$,$,$,$,$,$,$,$);",
        f"#3=IFCBUILDING('{_guid(spec_id + ':building')}',$,'{_esc(name)}',$,"
        f"'archetype:{_esc(archetype)}',$,$,$,$,$,$,$);",
        f"#4=IFCBUILDINGSTOREY('{_guid(spec_id + ':storey')}',$,'Generated Storey',$,$,$,$,$,$);",
        "#5=IFCRELAGGREGATES('" + _guid(spec_id + ":rel:site") + "',$,$,$,#1,(#2));",
        "#6=IFCRELAGGREGATES('" + _guid(spec_id + ":rel:building") + "',$,$,$,#2,(#3));",
        "#7=IFCRELAGGREGATES('" + _guid(spec_id + ":rel:storey") + "',$,$,$,#3,(#4));",
    ]

    proxy_ids: list[str] = []
    next_id = 20
    for part_type, labels in parts.items():
        proxy_id = f"#{next_id}"
        proxy_ids.append(proxy_id)
        description = json.dumps(labels, sort_keys=True)
        lines.append(
            f"{proxy_id}=IFCBUILDINGELEMENTPROXY('{_guid(spec_id + ':' + part_type)}',$,"
            f"'{_esc(part_type)}','{_esc(description)}',$,$,$,$,.ELEMENT.);"
        )
        next_id += 1

    if proxy_ids:
        lines.append(
            "#8=IFCRELCONTAINEDINSPATIALSTRUCTURE('"
            + _guid(spec_id + ":rel:contains")
            + "',$,$,$,("
            + ",".join(proxy_ids)
            + "),#4);"
        )

    lines.extend(["ENDSEC;", "END-ISO-10303-21;"])
    return "\n".join(lines) + "\n"


def write_ifc(path: Path, *, archetype: str, spec: JsonDict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(make_ifc_text(archetype=archetype, spec=spec), encoding="utf-8")
    return path


def _parts_from_spec(spec: JsonDict) -> JsonDict:
    parts: JsonDict = {}
    for key in ("mass", "roof", "ground_floor"):
        value = spec.get(key)
        if isinstance(value, dict):
            parts[key] = value
    facades = spec.get("facades")
    if isinstance(facades, list):
        for index, facade in enumerate(facades):
            if isinstance(facade, dict):
                parts[f"facade_{index}"] = facade
    ornaments = spec.get("ornaments")
    if isinstance(ornaments, list):
        for index, ornament in enumerate(ornaments):
            if isinstance(ornament, dict):
                parts[f"ornament_{index}"] = ornament
    return parts or {"mass": {"form": "unknown"}}


def _guid(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    value = int.from_bytes(digest, "big")
    chars = []
    for _ in range(22):
        value, index = divmod(value, len(_IFC_GUID_CHARS))
        chars.append(_IFC_GUID_CHARS[index])
    return "".join(chars)


def _esc(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")
