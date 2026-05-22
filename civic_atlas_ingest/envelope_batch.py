"""Batch computation for current Flint buildable envelopes."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .envelope_compute import CardinalEdgeClassification, compute_buildable_envelope_result
from .envelope_edge_classifier import classify_cardinal_edges_by_roads
from .parcel_sources import (
    ParcelEnvelopeInput,
    fetch_flint_zoned_parcels,
    parcel_inputs_from_geojson,
)
from .zoning_schema import BuildableEnvelopeSeed, ZoningRuleRecord

DEFAULT_RULES_PATH = Path("city_packs/flint/zoning/rules-current.json")
DEFAULT_ROADS_PATH = Path("city_packs/flint/zoning/road-network-current.json")
DEFAULT_ENVELOPES_PATH = Path("city_packs/flint/zoning/envelopes-current.json")
DEFAULT_SPOTCHECK_PATH = Path("city_packs/flint/zoning/edge-spotcheck-current.json")
DEFAULT_ASSET_ROOT = Path("city_packs/flint/zoning/envelope-assets")
ROAD_PREFILTER_PADDING_DEGREES = 0.003
RoadGeometryIndex = tuple[tuple[tuple[float, float, float, float], dict[str, object]], ...]


@dataclass(frozen=True)
class EnvelopeBatchRecord:
    parcel_key: str
    zoning_code: str
    edge_classification: CardinalEdgeClassification
    envelope: BuildableEnvelopeSeed
    glb_sha256: str
    glb_asset_path: str | None = None


@dataclass(frozen=True)
class EnvelopeBatchSkip:
    parcel_key: str
    zoning_code: str | None
    reason: str


@dataclass(frozen=True)
class EnvelopeBatchResult:
    scenario_id: str
    row_count: int
    skipped_count: int
    asset_count: int
    content_hash: str
    rows: tuple[EnvelopeBatchRecord, ...]
    skipped: tuple[EnvelopeBatchSkip, ...]


def compute_current_envelope_batch(
    *,
    parcels: tuple[ParcelEnvelopeInput, ...],
    rules_by_code: dict[str, ZoningRuleRecord],
    road_geometries: tuple[dict[str, object], ...],
    scenario_id: str = "current",
    asset_root: Path | None = None,
) -> EnvelopeBatchResult:
    rows: list[EnvelopeBatchRecord] = []
    skipped: list[EnvelopeBatchSkip] = []
    asset_count = 0
    road_index = _road_geometry_index(road_geometries)

    for parcel in sorted(parcels, key=lambda item: item.parcel_key):
        rule = rules_by_code.get(parcel.zoning_code)
        if rule is None:
            skipped.append(
                EnvelopeBatchSkip(
                    parcel_key=parcel.parcel_key,
                    zoning_code=parcel.zoning_code,
                    reason="missing_zoning_rule",
                )
            )
            continue
        try:
            parcel_geometry, geometry_warnings = _parcel_polygon(parcel.geometry)
            nearby_roads = _nearby_road_geometries(parcel_geometry, road_index)
            edges = classify_cardinal_edges_by_roads(
                parcel_geometry=parcel_geometry,
                road_geometries=nearby_roads,
            )
            result = compute_buildable_envelope_result(
                parcel_key=parcel.parcel_key,
                parcel_geometry=parcel_geometry,
                rule=rule,
                edges=edges,
                scenario_id=scenario_id,
            )
        except ValueError as exc:
            skipped.append(
                EnvelopeBatchSkip(
                    parcel_key=parcel.parcel_key,
                    zoning_code=parcel.zoning_code,
                    reason=str(exc),
                )
            )
            continue

        asset_path = None
        if asset_root is not None:
            asset_path = _write_glb_asset(asset_root, result.glb_sha256, result.glb_bytes)
            asset_count += 1
        envelope = replace(
            result.seed,
            warnings=(*result.seed.warnings, *geometry_warnings),
        )
        rows.append(
            EnvelopeBatchRecord(
                parcel_key=parcel.parcel_key,
                zoning_code=parcel.zoning_code,
                edge_classification=edges,
                envelope=envelope,
                glb_sha256=result.glb_sha256,
                glb_asset_path=asset_path,
            )
        )

    hash_payload = {
        "scenario_id": scenario_id,
        "rows": [_record_to_jsonable(row) for row in rows],
        "skipped": [asdict(row) for row in skipped],
    }
    content_hash = hashlib.sha256(_stable_json(hash_payload).encode()).hexdigest()
    return EnvelopeBatchResult(
        scenario_id=scenario_id,
        row_count=len(rows),
        skipped_count=len(skipped),
        asset_count=asset_count,
        content_hash=content_hash,
        rows=tuple(rows),
        skipped=tuple(skipped),
    )


def build_edge_spotcheck_report(
    *,
    parcels: tuple[ParcelEnvelopeInput, ...],
    road_geometries: tuple[dict[str, object], ...],
    sample_size: int = 20,
) -> dict[str, Any]:
    corner_target = max(1, sample_size // 4)
    non_corner_target = sample_size - corner_target
    corners: list[dict[str, Any]] = []
    non_corners: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    road_index = _road_geometry_index(road_geometries)
    for parcel in sorted(parcels, key=lambda item: item.parcel_key):
        if len(corners) >= corner_target and len(non_corners) >= non_corner_target:
            break
        try:
            geometry, geometry_warnings = _parcel_polygon(parcel.geometry)
            nearby_roads = _nearby_road_geometries(geometry, road_index)
            edges = classify_cardinal_edges_by_roads(
                parcel_geometry=geometry,
                road_geometries=nearby_roads,
            )
        except ValueError as exc:
            skipped_rows.append(
                {
                    "parcel_key": parcel.parcel_key,
                    "zoning_code": parcel.zoning_code,
                    "reason": str(exc),
                }
            )
            continue
        row = {
            "parcel_key": parcel.parcel_key,
            "pid_dash": parcel.pid_dash,
            "zoning_code": parcel.zoning_code,
            "land_use": parcel.land_use,
            "front": edges.front,
            "rear": edges.rear,
            "secondary_front": edges.secondary_front,
            "is_corner": edges.is_corner,
            "warnings": list(geometry_warnings),
        }
        if edges.is_corner and len(corners) < corner_target:
            corners.append(row)
        elif not edges.is_corner and len(non_corners) < non_corner_target:
            non_corners.append(row)
        elif len(fallback_rows) < sample_size:
            fallback_rows.append(row)

    selected = [*corners]
    selected.extend(non_corners[: sample_size - len(selected)])
    if len(selected) < sample_size:
        selected.extend(fallback_rows[: sample_size - len(selected)])
    selected = selected[:sample_size]
    return {
        "city_pack": "flint",
        "scenario_id": "current",
        "sample_size": len(selected),
        "corner_count": sum(1 for row in selected if row["is_corner"]),
        "retrieved_at": datetime.now(UTC).isoformat(),
        "source_policy": (
            "Public parcel geometry and OSM road lines only; no owner/address fields "
            "or proprietary GIS runtime are included."
        ),
        "rows": selected,
        "skipped": skipped_rows,
    }


def write_envelope_batch_result(output_path: Path, result: EnvelopeBatchResult) -> None:
    payload = {
        "city_pack": "flint",
        "scenario_id": result.scenario_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "row_count": result.row_count,
        "skipped_count": result.skipped_count,
        "asset_count": result.asset_count,
        "content_hash": result.content_hash,
        "rows": [_record_to_jsonable(row) for row in result.rows],
        "skipped": [asdict(row) for row in result.skipped],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_edge_spotcheck_report(output_path: Path, report: dict[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_zoning_rules(path: Path) -> dict[str, ZoningRuleRecord]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rules", [])
    if not isinstance(rows, list):
        raise ValueError("rules payload must contain a list under 'rules'")
    return {rule.zoning_code: rule for rule in (_rule_from_json(row) for row in rows)}


def load_road_geometries(path: Path) -> tuple[dict[str, object], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    roads = payload.get("road_geometries")
    if not isinstance(roads, list):
        raise ValueError("road snapshot must contain a road_geometries list")
    return tuple(_require_linestring(road) for road in roads)


def load_parcels_from_geojson(path: Path) -> tuple[ParcelEnvelopeInput, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("parcel GeoJSON must be an object")
    return parcel_inputs_from_geojson(payload)


def _rule_from_json(row: dict[str, Any]) -> ZoningRuleRecord:
    return ZoningRuleRecord(
        city_pack=str(row["city_pack"]),
        rule_id=str(row["rule_id"]),
        zoning_code=str(row["zoning_code"]),
        display_name=str(row.get("display_name") or ""),
        max_height_m=_optional_float(row.get("max_height_m")),
        max_stories=_optional_float(row.get("max_stories")),
        max_far=_optional_float(row.get("max_far")),
        max_lot_coverage=_optional_float(row.get("max_lot_coverage")),
        min_front_setback_m=_optional_float(row.get("min_front_setback_m")),
        min_side_setback_m=_optional_float(row.get("min_side_setback_m")),
        min_rear_setback_m=_optional_float(row.get("min_rear_setback_m")),
        allowed_uses=tuple(row.get("allowed_uses", ())),
        conditional_uses=tuple(row.get("conditional_uses", ())),
        source_key=row.get("source_key"),
        source_section=row.get("source_section"),
        valid_from=_optional_date(row.get("valid_from")),
        valid_to=_optional_date(row.get("valid_to")),
        confidence=float(row.get("confidence", 0.7)),
        payload=row.get("payload", {}),
    )


def _parcel_polygon(geometry: dict[str, object]) -> tuple[dict[str, object], tuple[str, ...]]:
    geometry_type = geometry.get("type")
    if geometry_type == "Polygon":
        return geometry, ()
    if geometry_type != "MultiPolygon":
        raise ValueError("parcel geometry must be a Polygon or MultiPolygon")

    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("MultiPolygon coordinates must be a non-empty list")
    largest = max(coordinates, key=_polygon_area_hint)
    return {"type": "Polygon", "coordinates": largest}, ("multipolygon_largest_part_used",)


def _polygon_area_hint(polygon_coordinates: object) -> float:
    if not isinstance(polygon_coordinates, list) or not polygon_coordinates:
        return 0.0
    exterior = polygon_coordinates[0]
    if not isinstance(exterior, list) or len(exterior) < 4:
        return 0.0
    points = []
    for position in exterior:
        if not isinstance(position, list | tuple) or len(position) < 2:
            return 0.0
        points.append((float(position[0]), float(position[1])))
    return abs(_ring_area(points))


def _ring_area(points: list[tuple[float, float]]) -> float:
    if points[0] != points[-1]:
        points = [*points, points[0]]
    area = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:], strict=False):
        area += x0 * y1 - x1 * y0
    return area / 2


def _write_glb_asset(asset_root: Path, sha256: str, glb_bytes: bytes) -> str:
    relative_path = Path("sha256") / sha256[:2] / f"{sha256}.glb"
    output_path = asset_root / relative_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(glb_bytes)
    return relative_path.as_posix()


def _road_geometry_index(road_geometries: tuple[dict[str, object], ...]) -> RoadGeometryIndex:
    return tuple((_geometry_bbox(road), road) for road in road_geometries)


def _nearby_road_geometries(
    parcel_geometry: dict[str, object],
    road_index: RoadGeometryIndex,
) -> tuple[dict[str, object], ...]:
    bbox = _expand_bbox(_geometry_bbox(parcel_geometry), ROAD_PREFILTER_PADDING_DEGREES)
    selected = tuple(road for road_bbox, road in road_index if _bbox_intersects(bbox, road_bbox))
    if selected:
        return selected
    return tuple(road for _road_bbox, road in road_index)


def _geometry_bbox(geometry: dict[str, object]) -> tuple[float, float, float, float]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    points: list[tuple[float, float]] = []
    if geometry_type == "LineString" and isinstance(coordinates, list):
        points.extend(_positions_to_points(coordinates))
    elif geometry_type == "Polygon" and isinstance(coordinates, list):
        for ring in coordinates:
            points.extend(_positions_to_points(ring))
    elif geometry_type == "MultiPolygon" and isinstance(coordinates, list):
        for polygon in coordinates:
            if isinstance(polygon, list):
                for ring in polygon:
                    points.extend(_positions_to_points(ring))
    if not points:
        raise ValueError("geometry coordinates must contain lon/lat positions")
    xs = [x for x, _y in points]
    ys = [y for _x, y in points]
    return min(xs), min(ys), max(xs), max(ys)


def _positions_to_points(positions: object) -> list[tuple[float, float]]:
    if not isinstance(positions, list | tuple):
        return []
    points: list[tuple[float, float]] = []
    for position in positions:
        if isinstance(position, list | tuple) and len(position) >= 2:
            points.append((float(position[0]), float(position[1])))
    return points


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    padding: float,
) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = bbox
    return xmin - padding, ymin - padding, xmax + padding, ymax + padding


def _bbox_intersects(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> bool:
    axmin, aymin, axmax, aymax = first
    bxmin, bymin, bxmax, bymax = second
    return axmin <= bxmax and axmax >= bxmin and aymin <= bymax and aymax >= bymin


def _record_to_jsonable(record: EnvelopeBatchRecord) -> dict[str, Any]:
    return {
        "parcel_key": record.parcel_key,
        "zoning_code": record.zoning_code,
        "edge_classification": asdict(record.edge_classification),
        "envelope": asdict(record.envelope),
        "glb_sha256": record.glb_sha256,
        "glb_asset_path": record.glb_asset_path,
    }


def _require_linestring(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("type") != "LineString":
        raise ValueError("road geometry must be a GeoJSON LineString")
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("road LineString coordinates must contain at least two positions")
    return value


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)


def _optional_date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(str(value))


def _stable_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Batch current Flint buildable envelopes.")
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES_PATH)
    parser.add_argument("--roads", type=Path, default=DEFAULT_ROADS_PATH)
    parser.add_argument("--parcels", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_ENVELOPES_PATH)
    parser.add_argument("--spotcheck-output", type=Path, default=DEFAULT_SPOTCHECK_PATH)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-assets", action="store_true")
    args = parser.parse_args(argv)

    rules = load_zoning_rules(args.rules)
    roads = load_road_geometries(args.roads)
    parcels = (
        load_parcels_from_geojson(args.parcels)
        if args.parcels is not None
        else fetch_flint_zoned_parcels(limit=args.limit)
    )
    if args.limit is not None:
        parcels = parcels[: args.limit]

    asset_root = None if args.no_assets else args.asset_root
    result = compute_current_envelope_batch(
        parcels=parcels,
        rules_by_code=rules,
        road_geometries=roads,
        asset_root=asset_root,
    )
    write_envelope_batch_result(args.output, result)
    write_edge_spotcheck_report(
        args.spotcheck_output,
        build_edge_spotcheck_report(parcels=parcels, road_geometries=roads),
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "spotcheck_output": str(args.spotcheck_output),
                "row_count": result.row_count,
                "skipped_count": result.skipped_count,
                "asset_count": result.asset_count,
                "content_hash": result.content_hash,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1:])
