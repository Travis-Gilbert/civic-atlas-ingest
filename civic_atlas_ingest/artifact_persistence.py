"""Artifact persistence helpers for GIS-backed ingest records."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .training_corpus import TrainingCorpusRecord


@dataclass(frozen=True)
class PersistArtifactEnvelope:
    artifact_key: str
    source_type: str
    title: str
    uri: str
    citation: str
    captured_at_ms: int | None
    payload_json: str
    parcel_ref: str
    building_id: str
    building_part_id: str
    anchor_kind: str
    anchor_geometry_wkt: str
    anchor_time_start_ms: int | None
    anchor_time_end_ms: int | None
    anchor_payload_json: str


def build_gis_artifact_envelopes(
    records: list[TrainingCorpusRecord],
    *,
    source_class: str,
    source_uri: str,
    capabilities: dict[str, Any] | None,
    city: str,
) -> list[PersistArtifactEnvelope]:
    source_layer = _source_layer(capabilities)
    envelopes: list[PersistArtifactEnvelope] = []
    for record in records:
        footprint_wkt = _geometry_wkt(record.geometry)
        captured_at_ms = _iso_to_epoch_ms(record.observed_at)
        attributes = dict(record.extra.get("assessor_row") or {})
        for key, value in record.fields.items():
            if key not in attributes and value not in (None, ""):
                attributes[key] = value
        payload = {
            "footprint_wkt": footprint_wkt,
            "attributes": attributes,
            "source_layer": source_layer,
            "capture_date_ms": captured_at_ms,
            "metadata": {
                "source_class": source_class,
                "coverage_quality": round(record.coverage.quality, 4),
                "city": city,
            },
        }
        anchor_payload = {
            "record_id": record.record_id,
            "source_class": source_class,
            "coverage_quality": round(record.coverage.quality, 4),
            "field_lanes": record.field_lanes,
            "bbox": record.to_json().get("bbox"),
        }
        parcel_ref = str(record.fields.get("parcel_id") or record.source_id or "")
        label = parcel_ref or record.record_id
        title = f"{source_layer or source_class} {label}".strip()
        envelopes.append(
            PersistArtifactEnvelope(
                artifact_key=record.record_id,
                source_type="gis_feature",
                title=title,
                uri=source_uri,
                citation=f"{source_class}:{source_layer or city}",
                captured_at_ms=captured_at_ms,
                payload_json=json.dumps(payload, sort_keys=True),
                parcel_ref=parcel_ref,
                building_id="",
                building_part_id="",
                anchor_kind="observation",
                anchor_geometry_wkt=footprint_wkt,
                anchor_time_start_ms=None,
                anchor_time_end_ms=None,
                anchor_payload_json=json.dumps(anchor_payload, sort_keys=True),
            )
        )
    return envelopes


def persist_gis_artifacts(
    records: list[TrainingCorpusRecord],
    *,
    source_class: str,
    source_uri: str,
    capabilities: dict[str, Any] | None,
    city: str,
    tenant_id: str = "flint",
    grpc_url: str | None = None,
    timeout_s: float = 30.0,
) -> list[dict[str, str]]:
    target = _grpc_target(grpc_url or os.environ.get("CIVIC_ATLAS_GRPC_URL", ""))
    if not target:
        return []
    if not records:
        return []
    import grpc

    _ensure_backend_generated_on_path()
    from civic_atlas.v1 import civic_atlas_pb2, civic_atlas_pb2_grpc

    envelopes = build_gis_artifact_envelopes(
        records,
        source_class=source_class,
        source_uri=source_uri,
        capabilities=capabilities,
        city=city,
    )
    responses: list[dict[str, str]] = []
    with grpc.insecure_channel(target) as channel:
        stub = civic_atlas_pb2_grpc.CivicAtlasServiceStub(channel)
        for envelope in envelopes:
            response = stub.PersistArtifact(
                civic_atlas_pb2.PersistArtifactRequest(
                    tenant_context=civic_atlas_pb2.TenantContext(
                        tenant_id=tenant_id,
                        atlas_node_id=f"atlas:{tenant_id}",
                    ),
                    artifact_key=envelope.artifact_key,
                    source_type=envelope.source_type,
                    title=envelope.title,
                    uri=envelope.uri,
                    citation=envelope.citation,
                    captured_at_ms=envelope.captured_at_ms,
                    payload_json=envelope.payload_json,
                    parcel_ref=envelope.parcel_ref,
                    building_id=envelope.building_id,
                    building_part_id=envelope.building_part_id,
                    anchor_kind=envelope.anchor_kind,
                    anchor_geometry_wkt=envelope.anchor_geometry_wkt,
                    anchor_time_start_ms=envelope.anchor_time_start_ms,
                    anchor_time_end_ms=envelope.anchor_time_end_ms,
                    anchor_payload_json=envelope.anchor_payload_json,
                ),
                timeout=timeout_s,
            )
            responses.append(
                {
                    "artifact_id": response.artifact_id,
                    "status": response.status,
                }
            )
    return responses


def _source_layer(capabilities: dict[str, Any] | None) -> str:
    if not isinstance(capabilities, dict):
        return ""
    for key in ("layer_name", "collection_id", "service_title", "catalog_id", "title"):
        value = capabilities.get(key)
        if value:
            return str(value)
    return ""


def _geometry_wkt(geometry: dict[str, Any]) -> str:
    if not geometry:
        return ""
    try:
        from shapely.geometry import shape
    except ModuleNotFoundError:
        return _geojson_to_wkt(geometry)
    return shape(geometry).wkt


def _iso_to_epoch_ms(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return int(datetime.fromisoformat(normalized).timestamp() * 1000)
    except ValueError:
        return None


def _grpc_target(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.scheme and parsed.netloc:
        return parsed.netloc
    return text


def _ensure_backend_generated_on_path() -> None:
    generated_root = os.environ.get("CIVIC_ATLAS_BACKEND_GENERATED_ROOT", "").strip()
    if not generated_root:
        repo_root = Path(__file__).resolve().parents[2]
        generated_root = str(
            repo_root / "our-civic-atlas-backend" / "python" / "civic_atlas" / "generated"
        )
    if generated_root not in sys.path:
        sys.path.insert(0, generated_root)


def _geojson_to_wkt(geometry: dict[str, Any]) -> str:
    geometry_type = str(geometry.get("type") or "").strip()
    coordinates = geometry.get("coordinates")
    if geometry_type == "Point":
        return f"POINT {_coord_tuple(coordinates)}"
    if geometry_type == "LineString":
        return f"LINESTRING {_coord_sequence(coordinates)}"
    if geometry_type == "Polygon":
        rings = ", ".join(_coord_sequence(ring) for ring in coordinates or [])
        return f"POLYGON ({rings})"
    if geometry_type == "MultiPoint":
        parts = ", ".join(_coord_tuple(coord) for coord in coordinates or [])
        return f"MULTIPOINT ({parts})"
    if geometry_type == "MultiLineString":
        parts = ", ".join(_coord_sequence(line) for line in coordinates or [])
        return f"MULTILINESTRING ({parts})"
    if geometry_type == "MultiPolygon":
        polygons = []
        for polygon in coordinates or []:
            rings = ", ".join(_coord_sequence(ring) for ring in polygon)
            polygons.append(f"({rings})")
        return f"MULTIPOLYGON ({', '.join(polygons)})"
    raise ValueError(f"unsupported geometry type for WKT fallback: {geometry_type or '<empty>'}")


def _coord_sequence(coords: Any) -> str:
    return f"({', '.join(_coord_text(coord) for coord in coords or [])})"


def _coord_tuple(coord: Any) -> str:
    return f"({_coord_text(coord)})"


def _coord_text(coord: Any) -> str:
    if not isinstance(coord, (list, tuple)) or len(coord) < 2:
        raise ValueError(f"invalid coordinate: {coord!r}")
    values = [coord[0], coord[1], *coord[2:]]
    return " ".join(_format_number(value) for value in values)


def _format_number(value: Any) -> str:
    if isinstance(value, bool):
        raise ValueError("boolean coordinate values are invalid")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".15g")
    return str(value)
