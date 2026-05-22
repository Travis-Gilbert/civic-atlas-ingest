"""Deterministic buildable-envelope computation for Phase C."""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Literal

from .zoning_schema import BuildableEnvelopeSeed, ZoningRuleRecord

EARTH_RADIUS_M = 6_371_008.8
DEFAULT_STORY_HEIGHT_M = 3.5
UNCONSTRAINED_SENTINEL_HEIGHT_M = 50.0
RESIDENTIAL_UNIT_AREA_M2 = 80.0

CardinalDirection = Literal["north", "south", "east", "west"]


@dataclass(frozen=True)
class CardinalEdgeClassification:
    front: CardinalDirection
    rear: CardinalDirection
    secondary_front: CardinalDirection | None = None
    is_corner: bool = False


@dataclass(frozen=True)
class EnvelopeComputationResult:
    seed: BuildableEnvelopeSeed
    glb_bytes: bytes
    glb_sha256: str


def compute_buildable_envelope_seed(
    *,
    parcel_key: str,
    parcel_geometry: dict[str, object],
    rule: ZoningRuleRecord,
    edges: CardinalEdgeClassification,
    scenario_id: str = "current",
    existing_floor_area_m2: float | None = None,
) -> BuildableEnvelopeSeed:
    return compute_buildable_envelope_result(
        parcel_key=parcel_key,
        parcel_geometry=parcel_geometry,
        rule=rule,
        edges=edges,
        scenario_id=scenario_id,
        existing_floor_area_m2=existing_floor_area_m2,
    ).seed


def compute_buildable_envelope_result(
    *,
    parcel_key: str,
    parcel_geometry: dict[str, object],
    rule: ZoningRuleRecord,
    edges: CardinalEdgeClassification,
    scenario_id: str = "current",
    existing_floor_area_m2: float | None = None,
) -> EnvelopeComputationResult:
    """Compute one envelope payload from a simple parcel polygon and zoning rule.

    This v1 math handles the deterministic single-parcel proof. The later
    OSMnx/Shapely lane replaces the cardinal-edge simplification with
    per-edge buffers for irregular parcels.
    """
    lonlat_ring = _polygon_ring(parcel_geometry)
    local_ring, origin = _project_ring(lonlat_ring)
    parcel_area = abs(_ring_area(local_ring))
    if parcel_area <= 0:
        raise ValueError("parcel geometry area must be positive")

    footprint = _apply_cardinal_setbacks(
        local_ring,
        rule=rule,
        edges=edges,
    )
    footprint_area = abs(_ring_area(footprint))
    if footprint_area <= 0:
        raise ValueError("setbacks exceed parcel buildable area")

    binding_constraint = "height"
    if rule.max_lot_coverage is not None:
        max_coverage_area = parcel_area * rule.max_lot_coverage
        if footprint_area > max_coverage_area:
            footprint = _scale_ring_to_area(footprint, max_coverage_area)
            footprint_area = abs(_ring_area(footprint))
            binding_constraint = "coverage"

    height_m, floors_for_gfa, height_binding = _height_and_floor_count(
        parcel_area_m2=parcel_area,
        footprint_area_m2=footprint_area,
        rule=rule,
    )
    if binding_constraint != "coverage":
        binding_constraint = height_binding

    buildable_floor_area = footprint_area * floors_for_gfa
    max_units_estimated = _estimate_units(rule, buildable_floor_area)
    headroom = None
    if existing_floor_area_m2 is not None:
        headroom = max(buildable_floor_area - existing_floor_area_m2, 0)

    footprint_lonlat = _unproject_ring(footprint, origin)
    envelope_geometry = _polygon_z_from_footprint(footprint_lonlat, height_m)
    glb_bytes = _export_extruded_polygon_glb(footprint, height_m)
    glb_sha256 = hashlib.sha256(glb_bytes).hexdigest()
    seed = BuildableEnvelopeSeed(
        city_pack=rule.city_pack,
        scenario_id=scenario_id,
        parcel_key=parcel_key,
        zoning_code=rule.zoning_code,
        base_geometry={"type": "Polygon", "coordinates": [footprint_lonlat]},
        envelope_geometry=envelope_geometry,
        max_height_m=height_m,
        max_stories=rule.max_stories,
        max_far=rule.max_far,
        buildable_floor_area_m2=round(buildable_floor_area, 4),
        existing_floor_area_m2=existing_floor_area_m2,
        headroom_floor_area_m2=round(headroom, 4) if headroom is not None else None,
        max_units_estimated=max_units_estimated,
        binding_constraint=binding_constraint,
        asset_uri=f"sha256://{glb_sha256}",
        content_hash=glb_sha256,
        warnings=(),
        metrics={
            "parcel_area_m2": round(parcel_area, 4),
            "buildable_footprint_area_m2": round(footprint_area, 4),
            "floors_for_gfa": floors_for_gfa,
            "unit_area_assumption_m2": (
                RESIDENTIAL_UNIT_AREA_M2 if max_units_estimated is not None else None
            ),
        },
    )
    return EnvelopeComputationResult(seed=seed, glb_bytes=glb_bytes, glb_sha256=glb_sha256)


def _height_and_floor_count(
    *,
    parcel_area_m2: float,
    footprint_area_m2: float,
    rule: ZoningRuleRecord,
) -> tuple[float, float, str]:
    if rule.max_height_m is not None:
        height_m = rule.max_height_m
        binding = "height"
    elif rule.max_stories is not None:
        height_m = rule.max_stories * DEFAULT_STORY_HEIGHT_M
        binding = "height"
    else:
        height_m = UNCONSTRAINED_SENTINEL_HEIGHT_M
        binding = "unconstrained"

    if rule.max_stories is not None:
        floors = rule.max_stories
    else:
        floors = max(math.floor(height_m / DEFAULT_STORY_HEIGHT_M), 1)

    if rule.max_far is None:
        return height_m, floors, binding

    max_gfa = parcel_area_m2 * rule.max_far
    far_floors = max_gfa / footprint_area_m2
    if far_floors < floors:
        return far_floors * DEFAULT_STORY_HEIGHT_M, far_floors, "far"
    return height_m, floors, binding


def _apply_cardinal_setbacks(
    ring: list[tuple[float, float]],
    *,
    rule: ZoningRuleRecord,
    edges: CardinalEdgeClassification,
) -> list[tuple[float, float]]:
    xmin, ymin, xmax, ymax = _bbox(ring)
    side = rule.min_side_setback_m or 0
    setbacks: dict[CardinalDirection, float] = {
        "north": side,
        "south": side,
        "east": side,
        "west": side,
    }
    setbacks[edges.front] = rule.min_front_setback_m or 0
    setbacks[edges.rear] = rule.min_rear_setback_m or 0
    if edges.secondary_front is not None:
        setbacks[edges.secondary_front] = rule.min_front_setback_m or 0

    xmin += setbacks["west"]
    xmax -= setbacks["east"]
    ymin += setbacks["south"]
    ymax -= setbacks["north"]

    if xmin >= xmax or ymin >= ymax:
        return []
    return _closed_ring([(xmin, ymin), (xmax, ymin), (xmax, ymax), (xmin, ymax)])


def _polygon_ring(geometry: dict[str, object]) -> list[tuple[float, float]]:
    if geometry.get("type") != "Polygon":
        raise ValueError("parcel geometry must be a Polygon")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or not coordinates:
        raise ValueError("polygon coordinates must be a non-empty list")
    exterior = coordinates[0]
    if not isinstance(exterior, list) or len(exterior) < 4:
        raise ValueError("polygon exterior must have at least four positions")
    ring = []
    for position in exterior:
        if not isinstance(position, list) or len(position) < 2:
            raise ValueError("polygon positions must contain lon and lat")
        ring.append((float(position[0]), float(position[1])))
    return _closed_ring(ring)


def _project_ring(
    ring: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    lon0 = sum(lon for lon, _lat in ring[:-1]) / (len(ring) - 1)
    lat0 = sum(lat for _lon, lat in ring[:-1]) / (len(ring) - 1)
    cos_lat0 = math.cos(math.radians(lat0))
    projected = [
        (
            math.radians(lon - lon0) * EARTH_RADIUS_M * cos_lat0,
            math.radians(lat - lat0) * EARTH_RADIUS_M,
        )
        for lon, lat in ring
    ]
    return projected, (lon0, lat0)


def _unproject_ring(
    ring: list[tuple[float, float]],
    origin: tuple[float, float],
) -> list[list[float]]:
    lon0, lat0 = origin
    cos_lat0 = math.cos(math.radians(lat0))
    return [
        [
            lon0 + math.degrees(x / (EARTH_RADIUS_M * cos_lat0)),
            lat0 + math.degrees(y / EARTH_RADIUS_M),
        ]
        for x, y in ring
    ]


def _polygon_z_from_footprint(
    footprint: list[list[float]],
    height_m: float,
) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[lon, lat, round(height_m, 4)] for lon, lat in footprint]],
    }


def _export_extruded_polygon_glb(
    footprint: list[tuple[float, float]],
    height_m: float,
) -> bytes:
    points = footprint[:-1] if footprint[0] == footprint[-1] else footprint
    if len(points) < 3:
        raise ValueError("footprint must have at least three points")

    vertices = [(x, y, 0.0) for x, y in points] + [(x, y, height_m) for x, y in points]
    indices: list[int] = []
    point_count = len(points)

    for i in range(1, point_count - 1):
        indices.extend([0, i + 1, i])
        indices.extend([point_count, point_count + i, point_count + i + 1])

    for i in range(point_count):
        j = (i + 1) % point_count
        indices.extend([i, j, point_count + j])
        indices.extend([i, point_count + j, point_count + i])

    positions = b"".join(struct.pack("<fff", *vertex) for vertex in vertices)
    index_padding = _pad4_len(len(positions))
    indices_offset = len(positions) + index_padding
    index_bytes = b"".join(struct.pack("<I", index) for index in indices)
    binary = positions + (b"\0" * index_padding) + index_bytes
    binary += b"\0" * _pad4_len(len(binary))

    min_xyz = [min(vertex[i] for vertex in vertices) for i in range(3)]
    max_xyz = [max(vertex[i] for vertex in vertices) for i in range(3)]
    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "civic-atlas-ingest envelope_compute",
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [
            {
                "primitives": [
                    {
                        "attributes": {"POSITION": 0},
                        "indices": 1,
                        "mode": 4,
                    }
                ]
            }
        ],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {
                "buffer": 0,
                "byteOffset": 0,
                "byteLength": len(positions),
                "target": 34962,
            },
            {
                "buffer": 0,
                "byteOffset": indices_offset,
                "byteLength": len(index_bytes),
                "target": 34963,
            },
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": len(vertices),
                "type": "VEC3",
                "min": min_xyz,
                "max": max_xyz,
            },
            {
                "bufferView": 1,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }
    json_bytes = json.dumps(gltf, separators=(",", ":"), sort_keys=True).encode("utf-8")
    json_bytes += b" " * _pad4_len(len(json_bytes))

    total_length = 12 + 8 + len(json_bytes) + 8 + len(binary)
    return b"".join(
        [
            struct.pack("<III", 0x46546C67, 2, total_length),
            struct.pack("<II", len(json_bytes), 0x4E4F534A),
            json_bytes,
            struct.pack("<II", len(binary), 0x004E4942),
            binary,
        ]
    )


def _estimate_units(
    rule: ZoningRuleRecord,
    buildable_floor_area_m2: float,
) -> int | None:
    use_hints = {*rule.allowed_uses, *rule.conditional_uses}
    if "residential" not in use_hints and "mixed_use" not in use_hints:
        return None
    return max(math.floor(buildable_floor_area_m2 / RESIDENTIAL_UNIT_AREA_M2), 0)


def _pad4_len(length: int) -> int:
    return (4 - (length % 4)) % 4


def _scale_ring_to_area(
    ring: list[tuple[float, float]],
    target_area: float,
) -> list[tuple[float, float]]:
    current_area = abs(_ring_area(ring))
    if current_area <= 0:
        return []
    scale = math.sqrt(target_area / current_area)
    cx = sum(x for x, _y in ring[:-1]) / (len(ring) - 1)
    cy = sum(y for _x, y in ring[:-1]) / (len(ring) - 1)
    scaled = [(cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in ring[:-1]]
    return _closed_ring(scaled)


def _ring_area(ring: list[tuple[float, float]]) -> float:
    area = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:], strict=False):
        area += x0 * y1 - x1 * y0
    return area / 2


def _bbox(ring: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs = [x for x, _y in ring]
    ys = [y for _x, y in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _closed_ring(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if points[0] == points[-1]:
        return points
    return [*points, points[0]]
