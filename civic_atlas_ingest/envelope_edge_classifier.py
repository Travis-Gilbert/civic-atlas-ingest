"""Parcel edge classification for buildable-envelope setbacks."""

from __future__ import annotations

import math

from .envelope_compute import CardinalDirection, CardinalEdgeClassification

EARTH_RADIUS_M = 6_371_008.8


def classify_cardinal_edges_by_roads(
    *,
    parcel_geometry: dict[str, object],
    road_geometries: tuple[dict[str, object], ...],
    corner_tolerance_m: float = 3.0,
) -> CardinalEdgeClassification:
    """Classify a parcel's cardinal front/rear side from road-line geometry.

    This is the deterministic v1 edge classifier. It works on a parcel bbox and
    a road snapshot; the later OSMnx task can feed richer road lines without
    changing the output contract.
    """
    parcel_ring = _polygon_ring(parcel_geometry)
    local_parcel, origin = _project_ring(parcel_ring)
    local_roads = [_project_linestring(_linestring(road), origin) for road in road_geometries]
    if not local_roads:
        raise ValueError("at least one road geometry is required")

    sides = _bbox_sides(local_parcel)
    distances = {
        direction: min(
            _side_midpoint_distance(side, road_segment)
            for road in local_roads
            for road_segment in zip(road, road[1:], strict=False)
        )
        for direction, side in sides.items()
    }
    ordered = sorted(distances.items(), key=lambda item: (item[1], _direction_order(item[0])))
    front, front_distance = ordered[0]
    secondary_front = None
    if len(ordered) > 1 and ordered[1][1] - front_distance <= corner_tolerance_m:
        candidate = ordered[1][0]
        if candidate != _opposite(front):
            secondary_front = candidate
    return CardinalEdgeClassification(
        front=front,
        rear=_opposite(front),
        secondary_front=secondary_front,
        is_corner=secondary_front is not None,
    )


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
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def _linestring(geometry: dict[str, object]) -> list[tuple[float, float]]:
    if geometry.get("type") != "LineString":
        raise ValueError("road geometry must be a LineString")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError("road LineString coordinates must have at least two positions")
    line = []
    for position in coordinates:
        if not isinstance(position, list) or len(position) < 2:
            raise ValueError("road positions must contain lon and lat")
        line.append((float(position[0]), float(position[1])))
    return line


def _project_ring(
    ring: list[tuple[float, float]],
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    lon0 = sum(lon for lon, _lat in ring[:-1]) / (len(ring) - 1)
    lat0 = sum(lat for _lon, lat in ring[:-1]) / (len(ring) - 1)
    projected = [_project_point(lon, lat, (lon0, lat0)) for lon, lat in ring]
    return projected, (lon0, lat0)


def _project_linestring(
    line: list[tuple[float, float]],
    origin: tuple[float, float],
) -> list[tuple[float, float]]:
    return [_project_point(lon, lat, origin) for lon, lat in line]


def _project_point(
    lon: float,
    lat: float,
    origin: tuple[float, float],
) -> tuple[float, float]:
    lon0, lat0 = origin
    cos_lat0 = math.cos(math.radians(lat0))
    return (
        math.radians(lon - lon0) * EARTH_RADIUS_M * cos_lat0,
        math.radians(lat - lat0) * EARTH_RADIUS_M,
    )


def _bbox_sides(
    ring: list[tuple[float, float]],
) -> dict[CardinalDirection, tuple[tuple[float, float], tuple[float, float]]]:
    xs = [x for x, _y in ring]
    ys = [y for _x, y in ring]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    return {
        "south": ((xmin, ymin), (xmax, ymin)),
        "north": ((xmin, ymax), (xmax, ymax)),
        "west": ((xmin, ymin), (xmin, ymax)),
        "east": ((xmax, ymin), (xmax, ymax)),
    }


def _side_midpoint_distance(
    first: tuple[tuple[float, float], tuple[float, float]],
    second: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    midpoint = ((first[0][0] + first[1][0]) / 2, (first[0][1] + first[1][1]) / 2)
    return _point_segment_distance(midpoint, second)


def _point_segment_distance(
    point: tuple[float, float],
    segment: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    px, py = point
    (x1, y1), (x2, y2) = segment
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    closest_x = x1 + t * dx
    closest_y = y1 + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _opposite(direction: CardinalDirection) -> CardinalDirection:
    return {
        "north": "south",
        "south": "north",
        "east": "west",
        "west": "east",
    }[direction]


def _direction_order(direction: CardinalDirection) -> int:
    return {"south": 0, "west": 1, "north": 2, "east": 3}[direction]
